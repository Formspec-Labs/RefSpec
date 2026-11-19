"""Polite, strictly rate-limited Library of Congress client using stdlib urllib.request.

Enforces:
- >= 8.5s spacing between requests (including redirect hops) to www.loc.gov (ONLY ?fo=json allowed; HTML forbidden)
- >= 2.2s spacing between requests (including redirect hops) to tile.loc.gov and id.loc.gov
- Cross-process lockfile coordination via fcntl.flock when a shared state_file is configured
- Hard block on webarchive.loc.gov / webarchive-beta.loc.gov, unknown hosts, or unsupported expect_kind
- Immediate hard stop on HTTP 403, 429, Retry-After, Content-Range on 200, or cf-mitigated BEFORE reading body bytes
- Atomic file + .meta.json sidecar writes and SHA-256 verification on cache reuse
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

USER_AGENT = "RefSpec-Research/1.0 (+https://github.com/civictechdc/congressional-tech; polite-research)"

HOST_MIN_INTERVAL_SECONDS: dict[str, float] = {
    "www.loc.gov": 8.5,
    "tile.loc.gov": 2.2,
    "id.loc.gov": 2.2,
}
FORBIDDEN_HOSTS = frozenset({"webarchive.loc.gov", "webarchive-beta.loc.gov"})
ALLOWED_EXPECT_KINDS = frozenset({"json", "pdf", "xml"})


class LocClientError(RuntimeError):
    """Hard failure or safety abort during LoC HTTP fetch."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _check_headers_before_body_read(status: int, resp_headers: dict[str, str], url: str) -> dict[str, str]:
    """Raise LocClientError immediately on mitigation, rate-limit, or partial headers before reading body bytes."""

    lh = {k.lower(): v for k, v in resp_headers.items()}
    if "cf-mitigated" in lh:
        raise LocClientError(f"STOP: cf-mitigated header on {url} (status {status})")
    if "retry-after" in lh:
        raise LocClientError(f"STOP: Retry-After={lh['retry-after']!r} on {url} (status {status})")
    if status in {403, 429}:
        raise LocClientError(f"STOP: HTTP {status} on {url}")
    if status == 200 and "content-range" in lh:
        raise LocClientError(f"Rejected partial HTTP 200 with Content-Range on {url}")
    return lh


class PoliteLocClient:
    def __init__(self, state_file: Path | None = None) -> None:
        self.state_file = state_file
        self._last_request_by_host: dict[str, float] = {}
        self._opener = urllib.request.build_opener(
            _NoRedirectHandler(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        if state_file and state_file.is_file():
            try:
                loaded = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._last_request_by_host = {
                        str(k): float(v) for k, v in loaded.items() if isinstance(v, (int, float))
                    }
            except (OSError, ValueError):
                self._last_request_by_host = {}

    def _save_state(self) -> None:
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._last_request_by_host, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.state_file)

    @staticmethod
    def _validate_url(url: str, *, expect_kind: str) -> str:
        if expect_kind not in ALLOWED_EXPECT_KINDS:
            raise LocClientError(f"Unsupported expect_kind {expect_kind!r}; expected one of {sorted(ALLOWED_EXPECT_KINDS)}")
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host in FORBIDDEN_HOSTS:
            raise LocClientError(f"Forbidden host: {host} ({url})")
        if parts.scheme != "https":
            raise LocClientError(f"Only HTTPS URLs permitted: {url}")
        if host not in HOST_MIN_INTERVAL_SECONDS:
            raise LocClientError(f"Host {host!r} not in allowlist {sorted(HOST_MIN_INTERVAL_SECONDS)}: {url}")
        if host == "www.loc.gov":
            fo_vals = [v.lower() for v in parse_qs(parts.query).get("fo", [])]
            if "json" not in fo_vals:
                raise LocClientError(f"www.loc.gov URL missing fo=json (HTML forbidden): {url}")
            if expect_kind != "json":
                raise LocClientError(f"www.loc.gov only allowed for json, got {expect_kind!r}: {url}")
        return host

    @staticmethod
    def _validate_payload_bytes(
        raw: bytes,
        *,
        current_url: str,
        current_host: str,
        ctype: str,
        expect_kind: str,
    ) -> None:
        if expect_kind == "json":
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LocClientError(f"Invalid UTF-8 JSON from {current_url} (Content-Type {ctype!r}): {exc}") from exc
            if (
                current_host == "www.loc.gov"
                and "/collections/" in current_url
                and (not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list))
            ):
                raise LocClientError(f"LoC collection payload missing list 'results' on {current_url}")
        elif expect_kind == "pdf":
            if not raw.startswith(b"%PDF-"):
                raise LocClientError(f"Response lacks %PDF- magic bytes on {current_url} (Content-Type {ctype!r})")
        elif expect_kind == "xml":
            stripped = raw.lstrip()
            if not (stripped.startswith(b"<?xml") or stripped.startswith(b"<alto")):
                raise LocClientError(f"Response is not ALTO/XML on {current_url} (Content-Type {ctype!r})")
        else:
            raise LocClientError(f"Unsupported expect_kind {expect_kind!r}")

    def _single_get(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], dict[str, str], bytes]:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                status = resp.status
                resp_headers = dict(resp.headers.items())
                lh = _check_headers_before_body_read(status, resp_headers, url)
                if status != 200:
                    return status, resp_headers, lh, b""
                body = resp.read()
                return status, resp_headers, lh, body
        except urllib.error.HTTPError as err:
            resp_headers = dict(err.headers.items()) if err.headers else {}
            try:
                lh = _check_headers_before_body_read(err.code, resp_headers, url)
            finally:
                err.close()
            return err.code, resp_headers, lh, b""

    def _paced_single_get(
        self, host: str, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], dict[str, str], bytes]:
        """Hold the cross-process pacing lock across both the sleep window and request start/timestamp write."""

        min_gap = HOST_MIN_INTERVAL_SECONDS[host]
        if self.state_file is None:
            wall_now = time.time()
            last_wall = self._last_request_by_host.get(host, 0.0)
            wait = (last_wall + min_gap) - wall_now
            if wait > 0:
                time.sleep(wait)
            self._last_request_by_host[host] = time.time()
            try:
                return self._single_get(url, headers, timeout)
            finally:
                self._last_request_by_host[host] = max(self._last_request_by_host.get(host, 0.0), time.time())

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_file.with_suffix(".lock")
        with lock_path.open("a+", encoding="utf-8") as lock_fp:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
            try:
                if self.state_file.is_file():
                    try:
                        loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            for k, v in loaded.items():
                                if isinstance(v, (int, float)):
                                    self._last_request_by_host[str(k)] = max(
                                        self._last_request_by_host.get(str(k), 0.0),
                                        float(v),
                                    )
                    except (OSError, ValueError):
                        pass
                wall_now = time.time()
                last_wall = self._last_request_by_host.get(host, 0.0)
                wait = (last_wall + min_gap) - wall_now
                if wait > 0:
                    time.sleep(wait)
                self._last_request_by_host[host] = time.time()
                self._save_state()
                try:
                    return self._single_get(url, headers, timeout)
                finally:
                    self._last_request_by_host[host] = max(self._last_request_by_host.get(host, 0.0), time.time())
                    self._save_state()
            finally:
                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)

    def fetch_cached(
        self,
        url: str,
        cache_path: Path,
        *,
        expect_kind: str,
        timeout: float = 90.0,
        max_redirects: int = 4,
    ) -> tuple[bytes, dict[str, Any]]:
        host = self._validate_url(url, expect_kind=expect_kind)
        meta_path = cache_path.with_name(cache_path.name + ".meta.json")

        if cache_path.is_file() and meta_path.is_file():
            raw = cache_path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            actual_sha = hashlib.sha256(raw).hexdigest()
            if meta.get("sha256") != actual_sha or meta.get("bytes") != len(raw):
                raise LocClientError(
                    f"Cached file SHA/size mismatch for {cache_path}: "
                    f"meta=({meta.get('sha256')}, {meta.get('bytes')}) vs actual=({actual_sha}, {len(raw)})"
                )
            if meta.get("requested_url") != url:
                raise LocClientError(
                    f"Cached file URL mismatch for {cache_path}: meta={meta.get('requested_url')} vs {url}"
                )
            final_url = str(meta.get("final_url") or url)
            final_host = (urlsplit(final_url).hostname or host).lower()
            self._validate_payload_bytes(
                raw,
                current_url=final_url,
                current_host=final_host,
                ctype=str(meta.get("content_type") or "").lower(),
                expect_kind=expect_kind,
            )
            return raw, {**meta, "cached": True}

        accept = (
            "application/json"
            if expect_kind == "json"
            else ("application/xml,text/xml;q=0.9" if expect_kind == "xml" else "application/pdf,*/*;q=0.8")
        )
        headers = {"User-Agent": USER_AGENT, "Accept": accept}

        current_url = url
        current_host = host
        hops = 0
        while True:
            status, resp_headers, lh, raw = self._paced_single_get(current_host, current_url, headers, timeout)
            if status in {301, 302, 303, 307, 308}:
                if hops >= max_redirects:
                    raise LocClientError(f"Too many redirects ({hops}) starting from {url}")
                loc = lh.get("location")
                if not loc:
                    raise LocClientError(f"Redirect {status} without Location on {current_url}")
                next_url = urljoin(current_url, loc)
                if next_url.startswith("http://id.loc.gov/"):
                    next_url = "https://" + next_url[len("http://") :]
                next_host = self._validate_url(next_url, expect_kind=expect_kind)
                current_url = next_url
                current_host = next_host
                hops += 1
                continue
            if status != 200:
                raise LocClientError(f"Unexpected HTTP {status} on {current_url}")
            break

        ctype = lh.get("content-type", "").lower()
        self._validate_payload_bytes(
            raw,
            current_url=current_url,
            current_host=current_host,
            ctype=ctype,
            expect_kind=expect_kind,
        )

        sha = hashlib.sha256(raw).hexdigest()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_data = cache_path.with_name(cache_path.name + ".tmp")
        tmp_data.write_bytes(raw)
        os.replace(tmp_data, cache_path)

        meta = {
            "requested_url": url,
            "final_url": current_url,
            "redirect_hops": hops,
            "http_status": status,
            "content_type": resp_headers.get("Content-Type") or lh.get("content-type"),
            "content_length_header": resp_headers.get("Content-Length") or lh.get("content-length"),
            "bytes": len(raw),
            "sha256": sha,
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp_meta = meta_path.with_name(meta_path.name + ".tmp")
        tmp_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_meta, meta_path)
        return raw, {**meta, "cached": False}

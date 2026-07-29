"""Explicit, content-addressed Federal Register source acquisition tests."""

from __future__ import annotations

import hashlib
import importlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from refspec.registry import federal_register_acquisition as acquisition


@contextmanager
def _source_server(payload: bytes) -> Iterator[tuple[str, list[str]]]:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/thesaurus-alpha.txt", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_explicit_acquisition_verifies_before_content_addressed_publish(
    tmp_path: Path,
) -> None:
    payload = b"exact historical-style source bytes\n"
    expected = _digest(payload)

    with _source_server(payload) as (url, requests):
        acquired = acquisition.acquire_content_addressed_source(
            url,
            expected,
            tmp_path,
        )
        cached = acquisition.acquire_content_addressed_source(
            url,
            expected,
            tmp_path,
        )

    digest_hex = expected.removeprefix("sha256:")
    assert acquired.path == (tmp_path / "sha256" / digest_hex / acquisition.DEFAULT_FILENAME)
    assert acquired.path.read_bytes() == payload
    assert acquired.sha256 == expected
    assert acquired.byte_length == len(payload)
    assert acquired.cache_hit is False
    assert cached == acquisition.AcquiredSource(
        path=acquired.path,
        source_url=url,
        resolved_url=url,
        sha256=expected,
        byte_length=len(payload),
        cache_hit=True,
    )
    assert requests == ["/thesaurus-alpha.txt"]


def test_digest_mismatch_leaves_no_published_source_object(
    tmp_path: Path,
) -> None:
    payload = b"wrong source bytes\n"
    expected = _digest(b"different bytes\n")
    expected_path = tmp_path / "sha256" / expected.removeprefix("sha256:") / acquisition.DEFAULT_FILENAME

    with (
        _source_server(payload) as (url, requests),
        pytest.raises(acquisition.AcquisitionError, match="digest mismatch"),
    ):
        acquisition.acquire_content_addressed_source(
            url,
            expected,
            tmp_path,
        )

    assert requests == ["/thesaurus-alpha.txt"]
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_module_import_does_not_open_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def fail_if_called(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("network access on module import")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", fail_if_called)
    importlib.reload(acquisition)

    assert calls == []
    assert (
        acquisition.FEDERAL_REGISTER_THESAURUS_1995_SHA256 == "sha256:"
        "d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"
    )

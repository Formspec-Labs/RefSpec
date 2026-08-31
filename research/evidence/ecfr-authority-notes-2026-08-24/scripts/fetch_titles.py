#!/usr/bin/env python3
"""Fetch every non-reserved CFR title's full XML from the eCFR versioner API.

Public, keyless endpoint. Sequential, one title at a time, two seconds between
titles, an honest User-Agent, and at most three attempts per title with
backoff. A title that will not come down after three attempts is recorded as a
hole and the run continues -- completeness is reported, never assumed.

    python3 fetch_titles.py OUTPUT_DIR

``OUTPUT_DIR`` must already hold ``titles.json`` (fetched separately, verbatim).
Writes ``title-{N}.xml`` beside it and ``manifest.json`` describing every
attempt: url, the title's latest issue date, bytes, sha256, HTTP status and the
UTC timestamp the fetch finished.

Re-running skips a title whose file is already present, complete and non-empty,
so an interrupted run resumes without re-downloading gigabytes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

TITLES_URL = "https://www.ecfr.gov/api/versioner/v1/titles.json"
FULL_URL = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{number}.xml"
USER_AGENT = "RefSpec-research/1.0 (Atlas regulatory-vocabulary research; contact michael.f.deeb@gmail.com)"

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (15, 45)
BETWEEN_TITLES_SECONDS = 2
MAX_TIME_SECONDS = 5400


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def looks_complete(path: Path) -> bool:
    """The versioner closes a title document with ``</ECFR>``.

    A truncated transfer ends mid-element, so the closing tag is the cheap
    end-to-end check that the whole document arrived.
    """

    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 4096))
        return b"</ECFR>" in handle.read()


def fetch(url: str, destination: Path, resume: bool) -> tuple[int, int]:
    """One curl attempt. Returns (curl exit code, HTTP status)."""

    command = [
        "curl",
        "-sS",
        "--max-time",
        str(MAX_TIME_SECONDS),
        "--speed-limit",
        "1024",
        "--speed-time",
        "120",
        "-A",
        USER_AGENT,
        "-w",
        "%{http_code}",
        "-o",
        str(destination),
    ]
    if resume:
        command.insert(1, "-C")
        command.insert(2, "-")
    command.append(url)
    completed = subprocess.run(command, capture_output=True, text=True)
    status = 0
    tail = completed.stdout.strip()[-3:]
    if tail.isdigit():
        status = int(tail)
    if completed.stderr.strip():
        print(f"    curl stderr: {completed.stderr.strip()[:300]}", flush=True)
    return completed.returncode, status


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    titles = json.loads((out / "titles.json").read_text())

    records = []
    for title in titles["titles"]:
        number = int(title["number"])
        if title.get("reserved") or not title.get("latest_issue_date"):
            records.append(
                {
                    "title": number,
                    "name": title.get("name"),
                    "reserved": True,
                    "date": title.get("latest_issue_date"),
                    "url": None,
                    "path": None,
                    "http_status": None,
                    "bytes": None,
                    "sha256": None,
                    "fetched_at": None,
                    "attempts": 0,
                    "ok": False,
                    "hole_reason": "reserved title, no document published",
                }
            )
            print(f"title {number}: reserved, skipped", flush=True)
            continue

        date = title["latest_issue_date"]
        url = FULL_URL.format(date=date, number=number)
        destination = out / f"title-{number}.xml"

        attempts = 0
        status = None
        if looks_complete(destination):
            print(f"title {number}: already on disk, skipped", flush=True)
        else:
            while attempts < MAX_ATTEMPTS:
                attempts += 1
                resume = attempts > 1 and destination.exists() and destination.stat().st_size > 0
                print(
                    f"title {number}: attempt {attempts} ({date}){' resume' if resume else ''}",
                    flush=True,
                )
                code, status = fetch(url, destination, resume)
                if code == 0 and status == 200 and looks_complete(destination):
                    break
                if code == 33 or status == 416:
                    # No range support, or the file is already whole: start over.
                    destination.unlink(missing_ok=True)
                print(f"    failed: curl exit {code}, http {status}", flush=True)
                if attempts < MAX_ATTEMPTS:
                    time.sleep(BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)])

        ok = looks_complete(destination)
        record = {
            "title": number,
            "name": title.get("name"),
            "reserved": False,
            "date": date,
            "url": url,
            "path": destination.name,
            "http_status": status if status is not None else 200,
            "bytes": destination.stat().st_size if destination.exists() else 0,
            "sha256": sha256_of(destination) if ok else None,
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "attempts": attempts,
            "ok": ok,
            "hole_reason": None if ok else f"incomplete after {attempts} attempts (last http {status})",
        }
        records.append(record)
        print(
            f"title {number}: {'ok' if ok else 'HOLE'} {record['bytes']:,} bytes"
            f" {(record['sha256'] or '')[:12]}",
            flush=True,
        )
        time.sleep(BETWEEN_TITLES_SECONDS)

    manifest = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "titles_endpoint": TITLES_URL,
        "titles_json_sha256": sha256_of(out / "titles.json"),
        "titles_json_bytes": (out / "titles.json").stat().st_size,
        "titles_json_meta": titles.get("meta"),
        "full_endpoint_template": FULL_URL,
        "user_agent": USER_AGENT,
        "titles": records,
        "fetched_titles": sum(1 for r in records if r["ok"]),
        "reserved_titles": [r["title"] for r in records if r["reserved"]],
        "holes": [r["title"] for r in records if not r["ok"] and not r["reserved"]],
        "total_bytes": sum(r["bytes"] or 0 for r in records),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"done: {manifest['fetched_titles']} titles, {manifest['total_bytes']:,} bytes,"
        f" holes={manifest['holes']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

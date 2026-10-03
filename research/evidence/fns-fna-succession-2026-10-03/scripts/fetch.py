"""Fetch the public records behind the FNS -> FNA succession candidate; write raw/ and manifest.json.

Every request is a keyless GET to the publisher, sequential, with one User-Agent.
The manifest records each URL, the file it landed in, its HTTP status, size,
SHA-256 and fetch time, so a reader can tell which bytes the candidate cites.
Run from the repository root: ``uv run python research/evidence/fns-fna-succession-2026-10-03/scripts/fetch.py``.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
AGENT = "RefSpec-research/1.0 (agency registry succession candidate)"
FR = "https://www.federalregister.gov"
FIELDS = "&".join(f"fields[]={f}" for f in ("document_number", "citation", "title", "publication_date", "type",
                                             "action", "agencies", "html_url", "effective_on"))
REQUESTS = (
    ("fr-document-2026-12700.json", f"{FR}/api/v1/documents/2026-12700.json"),
    ("fr-document-2026-12700.txt", f"{FR}/documents/full_text/text/2026/06/24/2026-12700.txt"),
    ("fr-document-2026-11917.json", f"{FR}/api/v1/documents/2026-11917.json"),
    ("fr-document-2026-11917.txt", f"{FR}/documents/full_text/text/2026/06/15/2026-11917.txt"),
    ("fr-document-2026-10828.json", f"{FR}/api/v1/documents/2026-10828.json"),
    ("fr-document-2024-07437.json", f"{FR}/api/v1/documents/2024-07437.json"),
    ("fr-agency-625.json", f"{FR}/api/v1/agencies/625"),
    ("fr-agency-200.json", f"{FR}/api/v1/agencies/200"),
    ("fr-fns-documents-since-2026-05-15.json",
     f"{FR}/api/v1/documents.json?conditions[agencies][]=food-and-nutrition-service"
     f"&conditions[publication_date][gte]=2026-05-15&order=newest&per_page=20&{FIELDS}"),
    ("fr-fna-documents-oldest.json",
     f"{FR}/api/v1/documents.json?conditions[agencies][]=food-and-nutrition-administration"
     f"&order=oldest&per_page=5&{FIELDS}"),
    ("ecfr-title-7-chapter-II-ancestry-2026-06-23.json",
     "https://www.ecfr.gov/api/versioner/v1/ancestry/2026-06-23/title-7.json?chapter=II"),
    ("ecfr-title-7-chapter-II-ancestry-2026-06-24.json",
     "https://www.ecfr.gov/api/versioner/v1/ancestry/2026-06-24/title-7.json?chapter=II"),
    ("usda-press-release-0062.26.html", "https://www.fns.usda.gov/newsroom/usda-0062.26"),
    ("fns-about-reorganization.html", "https://www.fns.usda.gov/about/reorganization"),
    ("usda-sm-1078-015.pdf", "https://www.usda.gov/sites/default/files/documents/sm-1078-015.pdf"),
)


def main() -> int:
    (HERE / "raw").mkdir(exist_ok=True)
    manifest = []
    for name, url in REQUESTS:
        request = urllib.request.Request(url, headers={"User-Agent": AGENT})
        fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
        entry = {"file": f"raw/{name}", "url": url, "http_status": status, "bytes": len(body),
                 "sha256": "sha256:" + hashlib.sha256(body).hexdigest(), "fetched_at": fetched_at}
        if status == 200:
            (HERE / "raw" / name).write_bytes(body)
        else:
            entry["file"] = None  # nothing retained: the publisher refused the request
        manifest.append(entry)
        time.sleep(1)
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

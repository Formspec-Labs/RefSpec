"""Retain the public records the agency alias batch cites, from official hosts, with a fixed anonymous User-Agent.

Run from the repository root: ``python research/evidence/agency-alias-records-2026-11-08/scripts/fetch.py``.
U.S. Code sections come from govinfo's link service (the newest annual edition it serves); the public law
from govinfo; the executive order from the Federal Register API and its full text. Writes ``raw/`` and
``manifest.json`` beside this directory; an existing file is not fetched again.
"""

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
USER_AGENT = "refspec-agency-aliases/0.1 (research probe)"
USC = [
    (2, "166"), (10, "131"), (10, "151"), (10, "155"), (10, "161"), (10, "7062"), (10, "8062"), (10, "8063"),
    (10, "9062"), (10, "9081"), (10, "10501"), (12, "1"), (12, "241"), (12, "635"), (16, "1609"), (38, "2400"),
    (38, "7301"), (38, "7701"), (42, "1863"), (42, "285f"), (44, "3503"), (50, "3056"),
    # Read after the first pass, where a cited section did not itself state the parent, or a row cited none.
    (2, "1381"), (2, "1901"), (6, "652"), (10, "111"), (10, "167"), (10, "167b"), (10, "205"), (10, "1073c"),
    (10, "4127"), (10, "8031"), (10, "8041"), (10, "9031"), (18, "4041"), (22, "6431"), (42, "281"), (42, "1861"),
]
SOURCES = [
    *((f"usc-{t}-{s}.htm", f"https://www.govinfo.gov/link/uscode/{t}/{s}?link-type=html") for t, s in USC),
    ("plaw-108-271.htm", "https://www.govinfo.gov/content/pkg/PLAW-108publ271/html/PLAW-108publ271.htm"),
    ("fr-eo-14347-search.json",
     "https://www.federalregister.gov/api/v1/documents.json?conditions%5Bpresidential_document_type%5D=executive_order"
     "&conditions%5Bexecutive_order_numbers%5D%5B%5D=14347&fields%5B%5D=document_number&fields%5B%5D=title"
     "&fields%5B%5D=signing_date&fields%5B%5D=citation&fields%5B%5D=executive_order_number&fields%5B%5D=raw_text_url"
     "&fields%5B%5D=html_url"),
]


def fetch(url: str) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, response.geturl(), response.read()


def main() -> None:
    manifest_path = HERE / "manifest.json"
    manifest = {entry["file"].removeprefix("raw/"): entry for entry in json.loads(manifest_path.read_text())} if manifest_path.exists() else {}
    sources = list(SOURCES)
    search = HERE / "raw" / "fr-eo-14347-search.json"
    if search.exists():
        for result in json.loads(search.read_text()).get("results", []):
            sources.append((f"fr-eo-{result['executive_order_number']}.txt", result["raw_text_url"]))
    for name, url in sources:
        path = HERE / "raw" / name
        if path.exists() and name in manifest:
            continue
        status, final, body = fetch(url)
        path.write_bytes(body)
        manifest[name] = {
            "file": f"raw/{name}", "url": url, "final_url": final, "http_status": status, "bytes": len(body),
            "sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        print(status, name, len(body))
        time.sleep(1)
    manifest_path.write_text(json.dumps(sorted(manifest.values(), key=lambda e: e["file"]), indent=2) + "\n")


if __name__ == "__main__":
    main()

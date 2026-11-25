"""Retain the public records agency alias batch 2 cites, from official hosts, with a fixed anonymous User-Agent.

Run from the repository root:
    python research/evidence/agency-alias-records-2026-11-25/scripts/fetch.py
Writes ``raw/`` and ``manifest.json`` beside this script; an existing file in ``manifest.json`` is not re-fetched.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
USER_AGENT = "refspec-agency-aliases/0.1 (research probe)"

USC = [
    (2, "1151"),
    (10, "111"),
    (10, "134"),
    (10, "137"),
    (10, "138"),
    (10, "161"),
    (10, "167"),
    (10, "4173"),
    (10, "7016"),
    (10, "8016"),
    (10, "8591"),
    (10, "10104"),
    (10, "10105"),
    (10, "10110"),
    (10, "10111"),
    (10, "10171"),
    (12, "222"),
    (12, "241"),
    (15, "313"),
    (15, "5511"),
    (19, "2171"),
    (20, "77"),
    (20, "5603"),
    (22, "4831"),
    (22, "9611"),
    (28, "581"),
    (38, "323"),
    (42, "280b"),
    (42, "281"),
    (42, "1396"),
    (42, "1975"),
    (42, "6611"),
    (42, "11311"),
    (42, "12651"),
    (44, "301"),
    (50, "3023"),
    (50, "3033"),
    (52, "20301"),
]

SOURCES = [
    *((f"usc-{t}-{s}.htm", f"https://www.govinfo.gov/link/uscode/{t}/{s}?link-type=html") for t, s in USC),
    ("plaw-113-235.htm", "https://www.govinfo.gov/content/pkg/PLAW-113publ235/html/PLAW-113publ235.htm"),
    # Federal Register documents (statutory renames, line offices, OIGs, sub-units)
    ("fr-06-2124.txt", "https://www.federalregister.gov/documents/full_text/text/2006/03/07/06-2124.txt"),
    ("fr-2015-26486.txt", "https://www.federalregister.gov/documents/full_text/text/2015/12/01/2015-26486.txt"),
    ("fr-2015-27713.txt", "https://www.federalregister.gov/documents/full_text/text/2015/10/30/2015-27713.txt"),
    ("fr-2016-09120.txt", "https://www.federalregister.gov/documents/full_text/text/2016/04/27/2016-09120.txt"),
    ("fr-2016-31686.txt", "https://www.federalregister.gov/documents/full_text/text/2017/01/05/2016-31686.txt"),
    ("fr-2017-01169.txt", "https://www.federalregister.gov/documents/full_text/text/2017/01/17/2017-01169.txt"),
    ("fr-2020-01490.txt", "https://www.federalregister.gov/documents/full_text/text/2020/01/28/2020-01490.txt"),
    ("fr-2016-30271.txt", "https://www.federalregister.gov/documents/full_text/text/2016/12/16/2016-30271.txt"),
    ("fr-2012-27189.txt", "https://www.federalregister.gov/documents/full_text/text/2012/11/07/2012-27189.txt"),
    ("fr-2021-27841.txt", "https://www.federalregister.gov/documents/full_text/text/2021/12/21/2021-27841.txt"),
    ("fr-2022-18471.txt", "https://www.federalregister.gov/documents/full_text/text/2022/08/26/2022-18471.txt"),
    ("fr-2023-28203.txt", "https://www.federalregister.gov/documents/full_text/text/2024/02/05/2023-28203.txt"),
    ("fr-2024-01555.txt", "https://www.federalregister.gov/documents/full_text/text/2024/02/01/2024-01555.txt"),
    ("fr-2024-03586.txt", "https://www.federalregister.gov/documents/full_text/text/2024/02/22/2024-03586.txt"),
    ("fr-2024-07613.txt", "https://www.federalregister.gov/documents/full_text/text/2024/04/23/2024-07613.txt"),
    ("fr-2024-09203.txt", "https://www.federalregister.gov/documents/full_text/text/2024/05/22/2024-09203.txt"),
    ("fr-2024-09373.txt", "https://www.federalregister.gov/documents/full_text/text/2024/05/06/2024-09373.txt"),
    ("fr-2024-12399.txt", "https://www.federalregister.gov/documents/full_text/text/2024/06/06/2024-12399.txt"),
    ("fr-2024-16724.txt", "https://www.federalregister.gov/documents/full_text/text/2024/07/30/2024-16724.txt"),
    ("fr-2024-19473.txt", "https://www.federalregister.gov/documents/full_text/text/2024/08/29/2024-19473.txt"),
    ("fr-2024-19819.txt", "https://www.federalregister.gov/documents/full_text/text/2024/09/11/2024-19819.txt"),
    ("fr-2024-19930.txt", "https://www.federalregister.gov/documents/full_text/text/2024/09/05/2024-19930.txt"),
    ("fr-2024-20680.txt", "https://www.federalregister.gov/documents/full_text/text/2024/09/12/2024-20680.txt"),
    ("fr-2024-24461.txt", "https://www.federalregister.gov/documents/full_text/text/2024/10/22/2024-24461.txt"),
    ("fr-2024-24830.txt", "https://www.federalregister.gov/documents/full_text/text/2024/10/25/2024-24830.txt"),
    ("fr-2024-26843.txt", "https://www.federalregister.gov/documents/full_text/text/2024/11/18/2024-26843.txt"),
    ("fr-2024-27459.txt", "https://www.federalregister.gov/documents/full_text/text/2024/11/22/2024-27459.txt"),
    ("fr-2024-29437.txt", "https://www.federalregister.gov/documents/full_text/text/2024/12/13/2024-29437.txt"),
    ("fr-2024-31221.txt", "https://www.federalregister.gov/documents/full_text/text/2024/12/30/2024-31221.txt"),
    ("fr-2025-01685.txt", "https://www.federalregister.gov/documents/full_text/text/2025/01/24/2025-01685.txt"),
    ("fr-2025-02121.txt", "https://www.federalregister.gov/documents/full_text/text/2025/01/31/2025-02121.txt"),
    ("fr-2025-06579.txt", "https://www.federalregister.gov/documents/full_text/text/2025/04/17/2025-06579.txt"),
    ("fr-2025-07258.txt", "https://www.federalregister.gov/documents/full_text/text/2025/04/28/2025-07258.txt"),
    ("fr-2025-08853.txt", "https://www.federalregister.gov/documents/full_text/text/2025/05/20/2025-08853.txt"),
    ("fr-2025-13203.txt", "https://www.federalregister.gov/documents/full_text/text/2025/07/15/2025-13203.txt"),
    ("fr-2025-16825.txt", "https://www.federalregister.gov/documents/full_text/text/2025/09/03/2025-16825.txt"),
    ("fr-2025-17223.txt", "https://www.federalregister.gov/documents/full_text/text/2025/09/08/2025-17223.txt"),
    ("fr-2025-17697.txt", "https://www.federalregister.gov/documents/full_text/text/2025/09/12/2025-17697.txt"),
    ("fr-2025-19855.txt", "https://www.federalregister.gov/documents/full_text/text/2025/11/12/2025-19855.txt"),
    ("fr-2025-21734.txt", "https://www.federalregister.gov/documents/full_text/text/2025/12/02/2025-21734.txt"),
    ("fr-2025-22150.txt", "https://www.federalregister.gov/documents/full_text/text/2025/12/08/2025-22150.txt"),
    ("fr-2026-00684.txt", "https://www.federalregister.gov/documents/full_text/text/2026/01/15/2026-00684.txt"),
    ("fr-2026-04237.txt", "https://www.federalregister.gov/documents/full_text/text/2026/03/04/2026-04237.txt"),
    ("fr-2026-04842.txt", "https://www.federalregister.gov/documents/full_text/text/2026/03/12/2026-04842.txt"),
    ("fr-2026-07695.txt", "https://www.federalregister.gov/documents/full_text/text/2026/04/21/2026-07695.txt"),
    ("fr-2026-11925.txt", "https://www.federalregister.gov/documents/full_text/text/2026/06/15/2026-11925.txt"),
    ("fr-2026-14603.txt", "https://www.federalregister.gov/documents/full_text/text/2026/07/21/2026-14603.txt"),
    ("fr-2026-15156.txt", "https://www.federalregister.gov/documents/full_text/text/2026/07/28/2026-15156.txt"),
    ("fr-2026-17436.txt", "https://www.federalregister.gov/documents/full_text/text/2026/08/27/2026-17436.txt"),
    ("fr-2026-19607.txt", "https://www.federalregister.gov/documents/full_text/text/2026/09/25/2026-19607.txt"),
    ("fr-2026-20724.txt", "https://www.federalregister.gov/documents/full_text/text/2026/10/09/2026-20724.txt"),
    ("fr-2026-21343.txt", "https://www.federalregister.gov/documents/full_text/text/2026/10/19/2026-21343.txt"),
    ("fr-2026-21777.txt", "https://www.federalregister.gov/documents/full_text/text/2026/10/26/2026-21777.txt"),
    ("fr-E6-22472.txt", "https://www.federalregister.gov/documents/full_text/text/2007/01/03/E6-22472.txt"),
    # Congressional hearings & official agency pages where statutes/FR are silent
    ("chrg-114hhrg97822.htm", "https://www.govinfo.gov/content/pkg/CHRG-114hhrg97822/html/CHRG-114hhrg97822.htm"),
    ("chrg-117hhrg45602.htm", "https://www.govinfo.gov/content/pkg/CHRG-117hhrg45602/html/CHRG-117hhrg45602.htm"),
    ("chrg-118hhrg52384.htm", "https://www.govinfo.gov/content/pkg/CHRG-118hhrg52384/html/CHRG-118hhrg52384.htm"),
    ("nasa-nari.html", "https://nari.arc.nasa.gov/"),
    ("nsceb-about.html", "https://www.biotech.senate.gov/about/"),
]


def fetch(url: str) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status, response.geturl(), response.read()


def main() -> None:
    raw_dir = HERE / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = HERE / "manifest.json"
    manifest = (
        {entry["file"].removeprefix("raw/"): entry for entry in json.loads(manifest_path.read_text())}
        if manifest_path.exists()
        else {}
    )
    for name, url in SOURCES:
        path = raw_dir / name
        if path.exists() and name in manifest:
            continue
        status, final, body = fetch(url)
        path.write_bytes(body)
        manifest[name] = {
            "file": f"raw/{name}",
            "url": url,
            "final_url": final,
            "http_status": status,
            "bytes": len(body),
            "sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        print(status, name, len(body))
        time.sleep(0.25)
    manifest_path.write_text(json.dumps(sorted(manifest.values(), key=lambda e: e["file"]), indent=2) + "\n")


if __name__ == "__main__":
    main()

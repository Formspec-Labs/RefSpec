#!/usr/bin/env python3
"""Fetch Federal Register documents.json for Dec 15-31 of each year 1994-2025,
save the raw response verbatim, and report per-year stats for building
volumes.csv afterward.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import hashlib
from pathlib import Path
from datetime import datetime, timezone

OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol/raw")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FIELDS = ["end_page", "start_page", "volume", "document_number", "publication_date", "type"]

def build_url(gte, lte, per_page=1000):
    base = "https://www.federalregister.gov/api/v1/documents.json"
    params = [
        ("conditions[publication_date][gte]", gte),
        ("conditions[publication_date][lte]", lte),
        ("order", "newest"),
        ("per_page", str(per_page)),
    ]
    for f in FIELDS:
        params.append(("fields[]", f))
    return base + "?" + urllib.parse.urlencode(params)

def fetch(url, retries=4):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "refspec-research/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                return body, resp.status
        except urllib.error.HTTPError as e:
            last_err = e
            body = e.read()
            return body, e.code
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err

def main():
    years = list(range(1994, 2026))
    summary = []
    for year in years:
        gte = f"{year}-12-15"
        lte = f"{year}-12-31"
        url = build_url(gte, lte)
        fetched_at = datetime.now(timezone.utc).isoformat()
        body, status = fetch(url)
        sha256 = hashlib.sha256(body).hexdigest()
        out_path = OUT_DIR / f"fr_{year}.json"
        out_path.write_bytes(body)
        try:
            data = json.loads(body)
            count = data.get("count")
            nresults = len(data.get("results", []))
        except Exception as e:
            count = None
            nresults = None
        meta = {
            "year": year,
            "url": url,
            "status": status,
            "count": count,
            "results_fetched": nresults,
            "fetched_at": fetched_at,
            "sha256": sha256,
            "bytes": len(body),
        }
        summary.append(meta)
        print(json.dumps(meta))
        time.sleep(0.4)
    meta_path = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol/fetch_summary.json")
    meta_path.write_text(json.dumps(summary, indent=2))
    print("WROTE", meta_path)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""For each year 1936-1993 (volume 1-58), find the last published FR issue via
govinfo's per-year sitemap, then fetch that issue's MODS record and read the
publisher-stated printPageRange -- a keyless, per-volume source independent of
the Federal Register API (which does not cover pre-1994).
"""
import json
import re
import time
import urllib.request
import urllib.error
import hashlib
import csv
from pathlib import Path
from datetime import datetime, timezone

BASE = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol")
SITEMAP_DIR = BASE / "raw/govinfo_sitemaps"
MODS_DIR = BASE / "raw/govinfo_mods"
SITEMAP_DIR.mkdir(parents=True, exist_ok=True)
MODS_DIR.mkdir(parents=True, exist_ok=True)

ISSUE_RE = re.compile(r"FR-(\d{4})-(\d{2})-(\d{2})")

def fetch(url, retries=4, timeout=40):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "refspec-research/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.status
        except urllib.error.HTTPError as e:
            return e.read(), e.code
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err

def main():
    rows = []
    log = []
    for year in range(1936, 1994):
        expected_volume = year - 1935
        sitemap_url = f"https://www.govinfo.gov/sitemap/FR_{year}_sitemap.xml"
        body, status = fetch(sitemap_url)
        sitemap_path = SITEMAP_DIR / f"FR_{year}_sitemap.xml"
        sitemap_path.write_bytes(body)
        sitemap_sha = hashlib.sha256(body).hexdigest()
        text = body.decode("utf-8", errors="replace")
        dates = sorted(set(ISSUE_RE.findall(text)))  # (yyyy, mm, dd) tuples, string-sorted = chronological
        if not dates or status != 200:
            log.append(f"{year}: sitemap fetch problem (status={status}, dates_found={len(dates)})")
            rows.append({
                "volume": expected_volume, "year": year, "last_page": "",
                "evidence_issue": "", "evidence_source": "no-sitemap-data",
                "sitemap_url": sitemap_url, "sitemap_sha256": sitemap_sha,
                "mods_url": "", "mods_sha256": "", "fetched_at": "",
                "mods_volume_stated": "", "mods_digital_origin": "",
            })
            time.sleep(0.3)
            continue
        last_date = dates[-1]
        package_id = f"FR-{last_date[0]}-{last_date[1]}-{last_date[2]}"
        mods_url = f"https://www.govinfo.gov/metadata/pkg/{package_id}/mods.xml"
        mbody, mstatus = fetch(mods_url)
        mods_path = MODS_DIR / f"{package_id}_mods.xml"
        mods_path.write_bytes(mbody)
        mods_sha = hashlib.sha256(mbody).hexdigest()
        mtext = mbody.decode("utf-8", errors="replace")
        fetched_at = datetime.now(timezone.utc).isoformat()

        # Prefer the explicit printPageRange element; fall back to part/extent.
        m = re.search(r'<printPageRange first="(\d+)" last="(\d+)"', mtext)
        if not m:
            m = re.search(r"<start>(\d+)</start>\s*<end>(\d+)</end>", mtext)
        vol_m = re.search(r"<volume>(\d+)</volume>", mtext)
        origin_m = re.search(r"<digitalOrigin>([^<]*)</digitalOrigin>", mtext)
        is_error_page = "Govinfo" not in mtext and "<mods" not in mtext

        if is_error_page or not m:
            log.append(f"{year}: mods fetch for {package_id} unusable (status={mstatus}, has_mods_tag={'<mods' in mtext}, has_range={bool(m)})")
            rows.append({
                "volume": expected_volume, "year": year, "last_page": "",
                "evidence_issue": package_id, "evidence_source": "mods-unparseable",
                "sitemap_url": sitemap_url, "sitemap_sha256": sitemap_sha,
                "mods_url": mods_url, "mods_sha256": mods_sha, "fetched_at": fetched_at,
                "mods_volume_stated": vol_m.group(1) if vol_m else "",
                "mods_digital_origin": origin_m.group(1) if origin_m else "",
            })
            time.sleep(0.3)
            continue

        last_page = int(m.group(2))
        stated_vol = int(vol_m.group(1)) if vol_m else None
        note = ""
        if stated_vol is not None and stated_vol != expected_volume:
            note = f"MODS states volume {stated_vol}, expected {expected_volume}"
            log.append(f"{year}: {note} (issue {package_id})")

        rows.append({
            "volume": expected_volume, "year": year, "last_page": last_page,
            "evidence_issue": package_id, "evidence_source": "govinfo-mods",
            "sitemap_url": sitemap_url, "sitemap_sha256": sitemap_sha,
            "mods_url": mods_url, "mods_sha256": mods_sha, "fetched_at": fetched_at,
            "mods_volume_stated": stated_vol if stated_vol is not None else "",
            "mods_digital_origin": origin_m.group(1) if origin_m else "",
        })
        print(f"{year} (vol {expected_volume}): last issue {package_id}, last_page={last_page}, mods_volume={stated_vol}")
        time.sleep(0.35)

    out_csv = BASE / "govinfo_volumes_1_58_raw.csv"
    fieldnames = [
        "volume", "year", "last_page", "evidence_issue", "evidence_source",
        "sitemap_url", "sitemap_sha256", "mods_url", "mods_sha256", "fetched_at",
        "mods_volume_stated", "mods_digital_origin",
    ]
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"\nWROTE {out_csv} ({len(rows)} rows)")

    log_path = BASE / "govinfo_1_58_log.txt"
    log_path.write_text("\n".join(log) + ("\n" if log else "no issues logged\n"))
    print(f"WROTE {log_path} ({len(log)} entries)")

if __name__ == "__main__":
    main()

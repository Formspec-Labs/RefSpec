#!/usr/bin/env python3
"""Build volumes.csv from the raw per-year Federal Register API responses.

For each year, filter to the expected volume (year - 1935), drop rows with
end_page None or <= 0 (an API metadata gap, not a real page number), and take
the max end_page. Flag any year where a later-dated row with a zero/None page
exists after the winning document's date (a sign the true max may be hidden
behind bad metadata).
"""
import csv
import json
from pathlib import Path
from collections import defaultdict, Counter

RAW_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol/raw")
OUT_CSV = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol/volumes.csv")
ANOMALY_LOG = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol/volumes_anomalies.txt")

rows_out = []
anomalies = []

fetch_summary = json.loads(Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-frvol/fetch_summary.json").read_text())
summary_by_year = {m["year"]: m for m in fetch_summary}

for year in range(1994, 2026):
    expected_volume = year - 1935
    path = RAW_DIR / f"fr_{year}.json"
    data = json.loads(path.read_text())
    results = data["results"]
    meta = summary_by_year[year]

    total = len(results)
    zero_or_null = sum(1 for r in results if not r.get("end_page"))
    wrong_volume = sum(1 for r in results if r.get("volume") != expected_volume)

    usable = [r for r in results if r.get("end_page") and r.get("volume") == expected_volume]
    if not usable:
        anomalies.append(f"{year}: NO usable rows (volume={expected_volume}) -- cannot determine last page")
        rows_out.append({
            "volume": expected_volume, "year": year, "last_page": "",
            "evidence_document_number": "", "evidence_publication_date": "",
            "source_url": meta["url"], "fetched_at": meta["fetched_at"],
            "source_sha256": meta["sha256"],
        })
        continue

    winner = max(usable, key=lambda r: r["end_page"])
    max_page = winner["end_page"]

    # Anomaly check: any zero/null-page row dated AFTER the winner's date,
    # within the expected volume -- would mean the true max might be hidden.
    winner_date = winner["publication_date"]
    later_bad = [
        r for r in results
        if r.get("publication_date", "") > winner_date
        and r.get("volume") == expected_volume
        and not r.get("end_page")
    ]
    if later_bad:
        anomalies.append(
            f"{year}: {len(later_bad)} zero/null-page row(s) dated AFTER the winning document "
            f"({winner_date}, {winner['document_number']}, page {max_page}) -- true max may be understated. "
            f"Example later doc: {later_bad[0].get('document_number')} on {later_bad[0].get('publication_date')}"
        )

    # Anomaly check: did we hit the per_page=1000 cap while the LAST calendar
    # date in the window (Dec 31, or the winner's date) might be truncated?
    if meta["results_fetched"] == 1000 and meta["count"] > 1000:
        # verify winner's date rows are fully captured: count how many results
        # share winner_date; if that count could plausibly be truncated
        # (i.e. it's exactly at some boundary), flag for manual look. We
        # approximate by checking that at least one EARLIER date than the
        # winner's date also appears in results (proving winner's date was
        # not the cut-off boundary).
        dates_present = sorted({r["publication_date"] for r in results})
        if dates_present and dates_present[0] >= winner_date:
            anomalies.append(
                f"{year}: results truncated at per_page=1000 (count={meta['count']}) and the "
                f"earliest date present ({dates_present[0]}) is not before the winning date "
                f"({winner_date}) -- winner's date may be partially cut off, widen window to confirm"
            )

    if zero_or_null:
        pct = 100.0 * zero_or_null / total
        if pct > 20:
            anomalies.append(
                f"{year}: {zero_or_null}/{total} ({pct:.0f}%) rows in window carry end_page None/0 "
                f"(API metadata gap) -- max taken over the {len(usable)} usable rows only"
            )

    rows_out.append({
        "volume": expected_volume,
        "year": year,
        "last_page": max_page,
        "evidence_document_number": winner["document_number"],
        "evidence_publication_date": winner["publication_date"],
        "source_url": meta["url"],
        "fetched_at": meta["fetched_at"],
        "source_sha256": meta["sha256"],
    })

# Monotonic plausibility check across years
prev_page = None
for row in rows_out:
    if row["last_page"] == "":
        continue
    page = int(row["last_page"])
    if prev_page is not None and page < prev_page * 0.85:
        anomalies.append(
            f"{row['year']} (vol {row['volume']}): last_page {page} drops >15% vs prior year's {prev_page} -- check"
        )
    prev_page = page

with OUT_CSV.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "volume", "year", "last_page", "evidence_document_number",
        "evidence_publication_date", "source_url", "fetched_at", "source_sha256",
    ])
    writer.writeheader()
    for row in rows_out:
        writer.writerow(row)

with ANOMALY_LOG.open("w") as f:
    if anomalies:
        f.write("\n".join(anomalies) + "\n")
    else:
        f.write("no anomalies flagged\n")

print(f"wrote {OUT_CSV} ({len(rows_out)} rows)")
print(f"wrote {ANOMALY_LOG} ({len(anomalies)} anomalies)")
for a in anomalies:
    print("ANOMALY:", a)

"""Dry-run: corroborated CFR-title correction under bounded operators + OFR oracle."""
import csv, duckdb, pathlib

parts = set()
for row in csv.DictReader(open("research/evidence/cfr-subject-index-2026-08-20/part-subjects.csv")):
    parts.add((int(row["cfr_title"]), row["cfr_part"].lstrip("0").lower() or "0"))
titles_in_index = {t for t, _ in parts}

def candidates(title: int) -> set[int]:
    s = str(title)
    out = set()
    # named operators only: drop one digit; swap adjacent digits
    for i in range(len(s)):
        drop = s[:i] + s[i+1:]
        if drop and drop[0] != "0":
            out.add(int(drop))
    for i in range(len(s) - 1):
        swap = s[:i] + s[i+1] + s[i] + s[i+2:]
        if swap[0] != "0":
            out.add(int(swap))
    return {c for c in out if 1 <= c <= 50 and c != title}

c = duckdb.connect()
R = "'output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet'"
rows = c.execute(f"select cfr_title, cfr_part, reference_text, count(*) n from {R} "
                 "where cfr_title_is_possible=false and cfr_title != 0 and cfr_part is not null "
                 "group by 1,2,3").fetchall()
print("row | candidates surviving the OFR-part oracle | verdict")
for title, part, text, n in rows:
    survivors = sorted(t for t in candidates(title) if (t, part.lower()) in parts)
    verdict = f"CORRECT -> {survivors[0]}" if len(survivors) == 1 else ("ambiguous" if survivors else "no survivor")
    print(f"  x{n} {text!r:<28} ops->{sorted(candidates(title))} oracle->{survivors}  {verdict}")

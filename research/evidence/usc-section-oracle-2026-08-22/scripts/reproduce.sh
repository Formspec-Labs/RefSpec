#!/bin/zsh
# The derivation, in the order it was run on 2026-08-22. Every script keeps the
# hard-coded /tmp/silent working paths it was run with, so this is a record,
# not a portable pipeline: create /tmp/silent, put the agenda build under
# measurement at /tmp/silent/AGENDA_SNAPSHOT.parquet, and run top to bottom.
set -euo pipefail
W=/tmp/silent
S=$(cd "$(dirname "$0")" && pwd)
mkdir -p $W

# 1. sources (OLRC). Digests of the files actually used are in ../README.md.
curl -sS -L --http1.1 --retry 3 -o $W/xml_uscAll_119-102.zip \
  "https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip"
for y in {1994..2024}; do
  curl -sS -L --http1.1 --retry 3 -o $W/usc_annual_$y.zip \
    "https://uscode.house.gov/download/annualhistoricalarchives/XHTML/$y.zip"
done

# 2. the oracles
python3 $S/extract_sections.py      # -> usc_oracle_exact.parquet, usc_oracle_ranges.parquet
python3 $S/extract_annual.py        # -> usc_oracle_annual.parquet, usc_oracle_annual_rng.parquet
python3 $S/extract_subsections.py   # -> usc_oracle_subsec.parquet
python3 $S/extract_chapters.py      # -> usc_oracle_chapter.parquet

# 3. the corpus side and the join
duckdb < $S/corpus_pairs.sql                          # -> usc_corpus_pairs.parquet
rm -f $W/usc.duckdb
duckdb $W/usc.duckdb -c ".read $S/join.sql"           # -> verdict2
duckdb $W/usc.duckdb < $S/rows_and_headline.sql       # -> rowsv, headline counts

# 4. triage, corroboration, summaries
python3 $S/triage.py                # -> usc_triage.json
python3 $S/sibling.py               # -> usc_sibling.json
python3 $S/summarize_triage.py
duckdb $W/usc.duckdb < $S/reverse_test.sql

# nearmiss_firstpass.py is the first-pass near-miss scan (superseded by
# triage.py, which subsumes it); kept because the report cites its counts.

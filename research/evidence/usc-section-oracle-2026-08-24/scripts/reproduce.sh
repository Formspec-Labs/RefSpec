#!/bin/zsh
# Generation 2 of the U.S.C. section-existence oracle, in the order it was run
# on 2026-08-24. Working directory is output/usc-annual-2026-08-24/ (untracked);
# the scripts take it from $USC_WORK, defaulting to that path.
set -euo pipefail
R=${REFSPEC_ROOT:-/Users/mikewolfd/Work/RefSpec}
W=${USC_WORK:-$R/output/usc-annual-2026-08-24}
S=$(cd "$(dirname "$0")" && pwd)
G1=$R/research/evidence/usc-section-oracle-2026-08-22
G2=$R/research/evidence/usc-section-oracle-2026-08-24
export USC_WORK=$W
mkdir -p $W

# 1. sources (OLRC, keyless, sleep 1 between fetches). fetch_all.sh records URL,
#    bytes, sha256 and fetch time per file in $W/fetch_log.tsv; every digest is
#    restated in ../README.md and compared there with generation 1's.
$S/fetch_all.sh

# 1b. the sources against generation 1's re-fetch digest table (32 identical)
python3 $S/compare_source_digests.py $G1/README.md $W/fetch_log.tsv

# 2. what generation 1's case-sensitive matcher skipped, all 31 years
python3 $S/skipped_by_generation_1.py $W | tee $G2/evidence/skipped_by_generation_1.tsv

# 3. the oracles. extract_annual.py is generation 1's script with the matcher
#    made case-insensitive and a loud guard on any unclassified member; the
#    other three are generation 1's verbatim but for the working path.
python3 $S/extract_annual.py        # -> usc_oracle_annual.parquet, usc_oracle_annual_rng.parquet
python3 $S/extract_sections.py      # -> usc_oracle_exact.parquet, usc_oracle_ranges.parquet
python3 $S/extract_subsections.py   # -> usc_oracle_subsec.parquet
python3 $S/extract_chapters.py      # -> usc_oracle_chapter.parquet

cp $W/usc_oracle_annual.parquet     $G2/usc-oracle-annual-sections.parquet
cp $W/usc_oracle_annual_rng.parquet $G2/usc-oracle-annual-ranges.parquet
cp $W/usc_oracle_exact.parquet      $G2/usc-oracle-sections.parquet
cp $W/usc_oracle_ranges.parquet     $G2/usc-oracle-ranges.parquet
cp $W/usc_oracle_subsec.parquet     $G2/usc-oracle-subsections.parquet
cp $W/usc_oracle_chapter.parquet    $G2/usc-oracle-chapters.parquet

# 4. the proof: generation 1 against generation 2
python3 $S/compare_generations.py $G1 $G2 | tee $G2/evidence/compare_generations.txt
python3 $S/seeded_headings.py $G2 $W 20   | tee $G2/evidence/seeded_headings.tsv

# 5. the consumer side against the pinned build.  --write is what lets it put
# the flip list in evidence/would_flip_rows.tsv; without it the script writes
# nothing at all and the list goes to stdout with the rest of the report.
python3 $S/would_flip.py $G1 $G2 \
  $R/output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet \
  --write | tee $G2/evidence/would_flip.txt

# 5b. the flip list against the investigation's hand-bucketed answer key
python3 $S/check_against_answer_key.py $G2/evidence/would_flip.txt \
  $R/research/evidence/investigations-2026-08-24/inv-2012/exists_not_attested_8258_bucketed.csv \
  | tee $G2/evidence/answer_key_confusion.tsv

# 5c. the publisher's own rows for the twelve uppercase volumes
python3 $S/publisher_index_rows.py \
  $R/research/evidence/investigations-2026-08-24/inv-2012/{2010,2012,2013}-index.html

# 6. the manifest
python3 $S/manifest.py $G2 $W

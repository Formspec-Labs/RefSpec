"""The flip list against the investigation's hand-bucketed answer key.

``../investigations-2026-08-24/inv-2012/exists_not_attested_8258_bucketed.csv``
buckets all 8,258 rows by hand-checked cause: 1,881 ``1-case-bug-high-confidence``,
30 ``2-case-bug-uncertain``, 36 ``3-future-edition-beyond-2024``, 6,311
``4-genuine-era-mismatch``.  Generation 2 decides the same question from the
volumes themselves.  This prints the confusion between the two.

Usage:  python3 check_against_answer_key.py <would_flip.txt> <bucketed.csv>
"""

import collections
import csv
import sys
from pathlib import Path

FLIPS = Path(sys.argv[1])
KEY = Path(sys.argv[2])
TAB = "\t"

# would_flip.py prints the per-pair table and the seeded sample; the full flip
# set is recovered from its per-(title, year) block plus its own totals, so
# read the machine-readable list it writes beside it.
flips = set()
with (FLIPS.parent / "would_flip_rows.tsv").open() as fh:
    reader = csv.reader(fh, delimiter="\t")
    header = next(reader)
    for row in reader:
        rec = dict(zip(header, row, strict=True))
        flips.add((rec["usc_title"], rec["edition_year"], rec["usc_section"], rec["rin"]))

key = {}
with KEY.open() as fh:
    for rec in csv.DictReader(fh):
        key[(rec["usc_title"], rec["edition_year"], rec["usc_section"], rec["rin"])] = rec["bucket"]

confusion = collections.Counter()
for row_key, bucket in key.items():
    confusion[(bucket, "flips" if row_key in flips else "stays")] += 1
extra = [k for k in flips if k not in key]

print("keys are distinct (title, edition_year, section, rin); the CSV and the flip list\nboth carry several rows per key, so these are key counts, not row counts.")
print(TAB.join(["answer_key_bucket", "generation_2_says", "distinct_keys"]))
for (bucket, says), n in sorted(confusion.items()):
    print(TAB.join([bucket, says, str(n)]))
print()
print(f"keys generation 2 flips that the answer key does not carry at all: {len(extra)}")
for k in sorted(extra):
    print(TAB.join(["EXTRA", *k]))

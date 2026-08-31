"""Which rows of the pinned build would read ``attested_at_edition = true``
under generation 2 of the oracle, and which read ``false`` under generation 1.

Read-only.  Nothing here writes to the artifact or to ``src/``: it imports
:mod:`refspec.registry.usc_section_oracle` and asks the module's OWN
``section_verdict`` twice -- once against the generation-1 directory as pinned,
once against an oracle whose two annual tables have been swapped for
generation 2's.  The swap is done by seeding the ``cached_property`` slots in
the instance ``__dict__`` before anything reads them, so the generation-1
digests still guard the four release-point tables and no pin is bypassed for a
table that did not change.

Usage:  python3 would_flip.py <gen1-dir> <gen2-dir> <legal-authorities.parquet>
"""

import random
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from refspec.registry.usc_section_oracle import (  # noqa: E402
    UscSectionOracle,
    _section_key,
    _SpanIndex,
    normalize_section,
)

G1 = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "research/evidence/usc-section-oracle-2026-08-22"
G2 = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "research/evidence/usc-section-oracle-2026-08-24"
ARTIFACT = (
    Path(sys.argv[3])
    if len(sys.argv) > 3
    else ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"
)
TAB = "\t"


def annual_tables(directory: Path):
    """The two annual mappings, built exactly the way the module builds them."""

    table = pq.read_table(directory / "usc-oracle-annual-sections.parquet")
    sections: dict[tuple[int, bool, str], list[int]] = {}
    for year, title, appendix, section in zip(
        table.column("year").to_pylist(),
        table.column("title").to_pylist(),
        table.column("appendix").to_pylist(),
        table.column("section").to_pylist(),
        strict=True,
    ):
        sections.setdefault((title, appendix, normalize_section(section)), []).append(year)
    sections = {key: tuple(sorted(years)) for key, years in sections.items()}

    table = pq.read_table(directory / "usc-oracle-annual-ranges.parquet")
    ranges: dict[tuple[int, bool], list] = {}
    for year, title, appendix, low, high in zip(
        table.column("year").to_pylist(),
        table.column("title").to_pylist(),
        table.column("appendix").to_pylist(),
        table.column("lo").to_pylist(),
        table.column("hi").to_pylist(),
        strict=True,
    ):
        low_key, high_key = _section_key(normalize_section(low)), _section_key(normalize_section(high))
        if low_key and high_key:
            ranges.setdefault((title, appendix), []).append((low_key, high_key, year))
    ranges = {key: tuple(spans) for key, spans in ranges.items()}
    return sections, ranges


gen1 = UscSectionOracle.from_directory(G1)  # verifies all six generation-1 pins
gen2 = UscSectionOracle(directory=G1)  # release-point halves still generation-1-pinned
sections, ranges = annual_tables(G2)
gen2.__dict__["annual_sections"] = sections
gen2.__dict__["annual_ranges"] = ranges
gen2.__dict__["_annual_ranges_index"] = {key: _SpanIndex.build(spans) for key, spans in ranges.items()}

con = duckdb.connect()
P = str(ARTIFACT)

# ---------------------------------------------------------------- usc rows --
usc = con.execute(
    f"""SELECT rin, publication_id, authority_text, usc_title, usc_section,
               usc_appendix, usc_section_verdict, usc_section_attested_at_edition,
               coalesce(authority_join_text, authority_text) AS whole_citation
        FROM '{P}'
        WHERE usc_section_verdict = 'exists'
          AND usc_section_attested_at_edition = false"""
).fetchall()
print(f"usc rows reading exists / attested_at_edition = false in the pinned build: {len(usc)}")

memo: dict[tuple, tuple[bool | None, bool | None]] = {}


def both(title, section, appendix, year):
    key = (title, normalize_section(section), bool(appendix), year)
    if key not in memo:
        v1 = gen1.section_verdict(title, section, year, appendix=bool(appendix))
        v2 = gen2.section_verdict(title, section, year, appendix=bool(appendix))
        memo[key] = (v1.attested_at_edition, v2.attested_at_edition, v1.verdict, v2.verdict)
    return memo[key]


flip, stay, other = [], [], []
for row in usc:
    rin, pub, text, title, section, appendix, verdict, attested, whole = row
    year = int(pub[:4])
    a1, a2, v1, v2 = both(title, section, appendix, year)
    if a1 is not True and a2 is True:
        flip.append((*row, year, v1, v2))
    elif a1 == a2:
        stay.append((*row, year, v1, v2))
    else:
        other.append((*row, year, a1, a2, v1, v2))

print(f"would flip to attested_at_edition = true under generation 2: {len(flip)}")
print(f"unchanged: {len(stay)}")
print(f"changed some other way (should be 0): {len(other)}")
for row in other:
    print("   OTHER", row)

# Reconciliation: recomputing under generation 1 must return the column the
# build already wrote, or the harness is not asking the build's question.
agree = sum(1 for row in usc if memo[(row[3], normalize_section(row[4]), bool(row[5]), int(row[1][:4]))][0] is False)
print(f"rows whose generation-1 recomputation returns the pinned column (false): {agree} of {len(usc)}")

out = G2 / "evidence" / "would_flip_rows.tsv"
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w") as fh:
    fh.write(TAB.join(["rin", "publication_id", "edition_year", "usc_title", "usc_section",
                       "usc_appendix", "authority_text", "whole_citation"]) + "\n")
    for rin, pub, text, title, section, appendix, verdict, attested, whole, year, v1, v2 in sorted(flip):
        fh.write(TAB.join([rin, pub, str(year), str(title), str(section), str(appendix),
                           text.replace("\t", " "), (whole or "").replace("\t", " ")]) + "\n")
print(f"full flip list written to {out}")

print()
print("-- flips per (title, edition year) --")
print(TAB.join(["usc_title", "edition_year", "rows", "rins", "texts"]))
per = {}
for rin, pub, text, title, section, appendix, verdict, attested, whole, year, v1, v2 in flip:
    bucket = per.setdefault((title, year), [0, set(), set()])
    bucket[0] += 1
    bucket[1].add(rin)
    bucket[2].add(text)
for (title, year), (n, rins, texts) in sorted(per.items(), key=lambda kv: -kv[1][0]):
    print(TAB.join([str(title), str(year), str(n), str(len(rins)), str(len(texts))]))

print()
print("-- twenty seeded flips, verbatim --")
rng = random.Random(20260824)
sample = rng.sample(flip, min(20, len(flip)))
print(TAB.join(["rin", "publication_id", "usc_title", "usc_section", "authority_text", "whole_citation"]))
for rin, pub, text, title, section, appendix, verdict, attested, whole, year, v1, v2 in sorted(sample):
    print(TAB.join([rin, pub, str(title), str(section), text, whole or ""]))

# ------------------------------------------------------- act-derived rows --
print()
print("-- act-derived rows (authority_type = 'act_relative') carrying a usc section --")
act = con.execute(
    f"""SELECT rin, publication_id, authority_text, usc_title, usc_section, usc_appendix,
               usc_section_verdict, usc_section_attested_at_edition,
               coalesce(authority_join_text, authority_text) AS whole_citation
        FROM '{P}'
        WHERE authority_type = 'act_relative' AND usc_title IS NOT NULL AND usc_section IS NOT NULL"""
).fetchall()
print(f"act_relative rows with a resolved (title, section): {len(act)}")
act_flip = []
for row in act:
    rin, pub, text, title, section, appendix, verdict, attested, whole = row
    year = int(pub[:4])
    a1, a2, v1, v2 = both(title, section, appendix, year)
    if a1 is not True and a2 is True:
        act_flip.append((*row, year, a1, a2, v1, v2))
print(f"act_relative rows the oracle would newly attest at their edition: {len(act_flip)}")
per = {}
for row in act_flip:
    per.setdefault((row[3], row[9]), []).append(row)
print(TAB.join(["usc_title", "edition_year", "rows"]))
for (title, year), rows_ in sorted(per.items()):
    print(TAB.join([str(title), str(year), str(len(rows_))]))
print()
print(TAB.join(["rin", "publication_id", "usc_title", "usc_section", "authority_text",
                "verdict_now", "attested_now", "attested_gen1", "attested_gen2"]))
for rin, pub, text, title, section, appendix, verdict, attested, whole, year, a1, a2, v1, v2 in sorted(act_flip):
    print(TAB.join([rin, pub, str(title), str(section), text, str(verdict), str(attested), str(a1), str(a2)]))

"""Which rows of the pinned build read ``attested_at_edition`` differently, and
which read a different ``verdict``, between generation 1 and generation 2.

**Read-only by default.** Nothing here writes to ``src/`` ever, and nothing
writes into the artifact unless ``--write`` is passed: the full flip list goes
to stdout with the rest of the report otherwise. (It used to overwrite
``evidence/would_flip_rows.tsv`` unconditionally while its own docstring
claimed to be read-only — a tracked file rewritten by a script advertised not
to write one.)

It imports :mod:`refspec.registry.usc_section_oracle` and asks the module's OWN
``section_verdict`` twice -- once against an oracle carrying generation 1's two
annual tables, once against the module's pinned directory as it stands. The
swap is done by seeding the ``cached_property`` slots in the instance
``__dict__`` before anything reads them, so the module's own digests still
guard the four release-point tables and no pin is bypassed for a table that did
not change.

**The direction of the swap follows the pin, and must.** Until the module
switched to generation 2 (2026-08-24) the pinned directory WAS generation 1 and
generation 2's annual tables were the ones seeded in; now it is the other way
round. ``from_directory`` verifies against :data:`_ORACLE_PINS`, so calling it
on whichever directory the module is not pinned to raises -- which is the pin
doing its job, and the reason this script seeds rather than re-pins. The
comparison it prints is identical either way.

**Three populations, and the third is the one the report's blast-radius claim
rests on.**

1. ``authority_type = 'usc'`` rows reading ``exists`` /
   ``attested_at_edition = false`` -- the receipt's own census
   (``uscSectionExistsNotAtEditionRows``), and the slice a flip pays off. This
   query is typed: it used to be untyped and returned 8,280 rows under the
   label "usc rows", 19 of which were ``act_relative``.
2. ``authority_type = 'act_relative'`` rows carrying a resolved
   ``(title, section)`` -- the act-derived path, counted separately because it
   is a different fence answering the same oracle.
3. **Every row of the build that carries a ``(usc_title, usc_section)``**, of
   any authority type and any verdict, with BOTH the verdict and the
   attestation recomputed under each generation. Populations 1 and 2 can only
   ever find rows that already read ``exists``; only this one can catch a
   verdict MOVING -- an ``absent`` that becomes ``exists`` because the other
   generation prints the section somewhere. The report claims "no verdict
   moves anywhere in the table"; this is what checks it.

Usage:  python3 would_flip.py [gen1-dir] [gen2-dir] [legal-authorities.parquet] [--write]
"""

import argparse
import random
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from refspec.registry.usc_section_oracle import (  # noqa: E402
    USC_SECTION_ORACLE_ARTIFACT,
    UscSectionOracle,
    _section_key,
    _SpanIndex,
    normalize_section,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("gen1", nargs="?", default=ROOT / "research/evidence/usc-section-oracle-2026-08-22", type=Path)
parser.add_argument("gen2", nargs="?", default=ROOT / "research/evidence/usc-section-oracle-2026-08-24", type=Path)
parser.add_argument(
    "artifact",
    nargs="?",
    type=Path,
    default=ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet",
)
parser.add_argument(
    "--write",
    action="store_true",
    help="also write evidence/would_flip_rows.tsv into the generation-2 directory (a tracked file)",
)
args = parser.parse_args()
G1, G2, ARTIFACT = args.gen1, args.gen2, args.artifact
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


PINNED = ROOT / USC_SECTION_ORACLE_ARTIFACT
SEEDED = G1 if PINNED.resolve() == G2.resolve() else G2

# The pinned side, verified through all six digests, and the other generation's
# two annual tables seeded onto a second instance of the same pinned directory
# -- so the four release-point tables (identical row-for-row across the two
# generations) are authenticated on both sides and only the annual halves
# differ.
pinned = UscSectionOracle.from_directory(PINNED)
seeded_side = UscSectionOracle(directory=PINNED)
sections, ranges = annual_tables(SEEDED)
seeded_side.__dict__["annual_sections"] = sections
seeded_side.__dict__["annual_ranges"] = ranges
seeded_side.__dict__["_annual_ranges_index"] = {key: _SpanIndex.build(spans) for key, spans in ranges.items()}
gen1, gen2 = (seeded_side, pinned) if SEEDED == G1 else (pinned, seeded_side)

con = duckdb.connect()
P = str(ARTIFACT)

memo: dict[tuple, tuple] = {}


def both(title, section, appendix, year):
    key = (title, normalize_section(section), bool(appendix), year)
    if key not in memo:
        v1 = gen1.section_verdict(title, section, year, appendix=bool(appendix))
        v2 = gen2.section_verdict(title, section, year, appendix=bool(appendix))
        memo[key] = (v1.attested_at_edition, v2.attested_at_edition, v1.verdict, v2.verdict)
    return memo[key]


# ---------------------------------------------------------------- usc rows --
# TYPED. The receipt's uscSectionExistsNotAtEditionRows census is
# authority_type = 'usc'; an untyped query here reported a different population
# under the same name.
usc = con.execute(
    f"""SELECT rin, publication_id, authority_text, usc_title, usc_section,
               usc_appendix, usc_section_verdict, usc_section_attested_at_edition,
               coalesce(authority_join_text, authority_text) AS whole_citation
        FROM '{P}'
        WHERE authority_type = 'usc'
          AND usc_section_verdict = 'exists'
          AND usc_section_attested_at_edition = false"""
).fetchall()
print(f"usc-typed rows reading exists / attested_at_edition = false in the pinned build: {len(usc)}")

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

header = TAB.join(
    ["rin", "publication_id", "edition_year", "usc_title", "usc_section",
     "usc_appendix", "authority_text", "whole_citation"]
)


def flip_lines(rows):
    for rin, pub, text, title, section, appendix, verdict, attested, whole, year, v1, v2 in sorted(rows):
        yield TAB.join([rin, pub, str(year), str(title), str(section), str(appendix),
                        text.replace("\t", " "), (whole or "").replace("\t", " ")])


if args.write:
    out = G2 / "evidence" / "would_flip_rows.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write(header + "\n")
        for line in flip_lines(flip):
            fh.write(line + "\n")
    print(f"full flip list written to {out}")
else:
    print(f"full flip list ({len(flip)} usc rows) follows; pass --write to put it in {G2}/evidence/would_flip_rows.tsv")

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

# ------------------------------------------------- the whole-table verdict --
# The claim this pays for: "no verdict moves anywhere in the table". Neither
# query above can establish it -- both are restricted to rows that already read
# exists, and a verdict MOVING means an absent becoming an exists. So every row
# carrying a (title, section) is recomputed, of any authority type and any
# verdict, and both halves of the answer are compared.
print()
print("-- whole-table recomputation: every row carrying a (usc_title, usc_section) --")
addressed = con.execute(
    f"""SELECT rin, publication_id, authority_type, authority_text, usc_title, usc_section,
               usc_appendix, usc_section_verdict, usc_section_attested_at_edition
        FROM '{P}'
        WHERE usc_title IS NOT NULL AND usc_section IS NOT NULL"""
).fetchall()
print(f"rows addressed: {len(addressed)}")
verdict_moves, attest_moves, pinned_disagrees, unjudged = [], 0, 0, 0
for row in addressed:
    rin, pub, atype, text, title, section, appendix, verdict, attested = row
    year = int(pub[:4])
    a1, a2, v1, v2 = both(title, section, appendix, year)
    if v1 != v2:
        verdict_moves.append((*row, year, v1, v2))
    if a1 != a2:
        attest_moves += 1
    if verdict is None:
        unjudged += 1
    elif v1 != verdict:
        pinned_disagrees += 1
# The reconciliation is over the rows the BUILD judged. It writes no verdict at
# all for a citation whose title cannot be the Code's -- 129 rows naming titles
# 59, 61, 80, 94, ... 41349, and 5 more naming titles 52 and 54 in editions
# before those titles existed -- and calling ``section_verdict`` directly, as
# this script does, answers ``absent`` for them because it is asked. That is a
# difference in what gets ASKED, not in what the oracle answers, so counting it
# as a disagreement would be an artefact of this harness.
print(f"rows the build declined to judge (title-impossible; not reconciled here): {unjudged}")
print(f"rows whose generation-1 recomputation returns the build's own verdict: "
      f"{len(addressed) - unjudged - pinned_disagrees} of {len(addressed) - unjudged}")
print(f"rows whose VERDICT differs between the generations: {len(verdict_moves)}")
print(f"rows whose ATTESTATION differs between the generations: {attest_moves}")
print(TAB.join(["rin", "publication_id", "authority_type", "usc_title", "usc_section",
                "verdict_gen1", "verdict_gen2", "authority_text"]))
for rin, pub, atype, text, title, section, appendix, verdict, attested, year, v1, v2 in sorted(verdict_moves):
    print(TAB.join([rin, pub, atype, str(title), str(section), str(v1), str(v2), text]))

if not args.write:
    print()
    print(f"-- the {len(flip)} usc flips, verbatim (stdout because --write was not passed) --")
    print(header)
    for line in flip_lines(flip):
        print(line)

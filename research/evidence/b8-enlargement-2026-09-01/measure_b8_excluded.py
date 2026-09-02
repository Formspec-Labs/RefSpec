"""Read-only measurement of what the shipped B8 rule DOES NOT publish.

Companion to ``measure_b8_two_witness.py``, which measures the rule's own
three outcomes. This one measures the populations the rule deliberately
declines, so DELTAS.md can quantify each narrowing rather than assert it:

1. **The sole-survivor gate's excluded population.** Rows where the oracle's
   B8 candidate survives ALONGSIDE another survivor. Broken down by what the
   two witnesses WOULD have said had the gate not fired -- the number the
   2026-09-01 adversarial review asked for, because "smaller than inv-b8's
   1,171" is mostly this.
2. **The counter-evidence rider's two sub-populations.** Of the rows refused
   because the held note names the BARE section ``present``, how many have
   that same note ALSO naming the lettered section ``present`` (it names both
   and chooses nothing) against how many name the bare section only.
3. **The witness-2b text-scan proxy.** A properly BOUNDED same-RIN text scan
   over the witnessless rows: how much corroboration a future text-scan
   widening would actually find today.
4. **The appendix population.** How many rows in the whole B8-survivor
   population carry ``usc_appendix``, for the guard's measured-zero comment.
5. **Witness 2b's edition spread.** Whether a 2b-only promotion's structural
   witness sits in another edition or the same one.
6. **The FTC specimen's edition count**, since the docstring and the lane
   report disagreed about it.

Everything is read from the artifact this checkout carries and computed
through the SHIPPED helpers (``_held_parts_by_rule``, the oracle's own
``correction_candidates``, ``notes.judge``) -- never a re-derived heuristic.
Writes only ``excluded_summary.json`` beside this file; nothing under
``output/``.

Run with: PYTHONPATH=src .venv/bin/python
research/evidence/b8-enlargement-2026-09-01/measure_b8_excluded.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")

import pyarrow.parquet as pq

from refspec.registry.cfr_authority_notes import CfrAuthorityNotes, usc_citation
from refspec.registry.unified_agenda_parquet import (
    _USC_B8_ORACLE_RULE,
    _held_parts_by_rule,
)
from refspec.registry.usc_section_oracle import UscSectionOracle

ROOT = Path(".")
OUT = Path(__file__).parent

LA_PATH = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"
REF_PATH = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet"

print("loading oracle + notes ...", flush=True)
oracle = UscSectionOracle.from_repository(ROOT)
notes = CfrAuthorityNotes.from_repository(ROOT)

authorities = pq.read_table(LA_PATH).to_pylist()
references = pq.read_table(REF_PATH).to_pylist()
print("legal_authorities rows:", len(authorities), "| cfr_references rows:", len(references), flush=True)

held_by_rule = _held_parts_by_rule(references, notes)

# The same structural history witness 2b reads, rebuilt here with the SAME
# exclusions `_CitationHistory.build` applies (corroborated rows never
# bootstrap corroboration; appendix and impossible-title rows never enter).
history: dict[str, set[tuple[int, str]]] = {}
texts_by_rin: dict[str, list[str]] = {}
rows_by_rin: dict[str, list[tuple[str, int, str]]] = {}
for row in authorities:
    if row["parse_status"] == "corroborated":
        continue
    texts_by_rin.setdefault(row["rin"], []).append(str(row["authority_text"] or ""))
    if (
        row["authority_type"] == "usc"
        and row["usc_title"] is not None
        and row["usc_section"]
        and not row["usc_appendix"]
        and row["usc_title_is_possible"]
    ):
        history.setdefault(row["rin"], set()).add((row["usc_title"], row["usc_section"].lower()))
        rows_by_rin.setdefault(row["rin"], []).append(
            (row["publication_id"], row["usc_title"], row["usc_section"].lower())
        )

memo: dict[tuple[int, str, str], tuple] = {}


def survivors_for(title: int, section: str, text: str) -> tuple:
    key = (title, section, text)
    if key not in memo:
        memo[key] = tuple(
            candidate
            for candidate in oracle.correction_candidates(title, section, text)
            if candidate.fenced_by is None
        )
    return memo[key]


lone: list[tuple[dict, object]] = []
multi: list[tuple[dict, object]] = []
appendix_rows = 0
for row in authorities:
    if (
        row["authority_type"] != "usc"
        or row["usc_title"] is None
        or row["usc_section"] is None
        or row["usc_section_corrected"] is not None
        or not re.fullmatch(r"\d+", row["usc_section"])
    ):
        continue
    survivors = survivors_for(row["usc_title"], row["usc_section"], row["authority_text"])
    b8 = next((c for c in survivors if c.rule == _USC_B8_ORACLE_RULE), None)
    if b8 is None:
        continue
    if row["usc_appendix"]:
        appendix_rows += 1
    (lone if len(survivors) == 1 else multi).append((row, b8))

print()
print("B8-survivor rows:", len(lone) + len(multi), "| LONE:", len(lone), "| MULTI:", len(multi))
print("appendix rows anywhere in the B8-survivor population:", appendix_rows)


def witnesses(row: dict, nnnx: str) -> tuple[str | None, bool, bool]:
    """(bare-note verdict, witness 2a, witness 2b) exactly as the rule asks them."""

    parts = held_by_rule.get((row["rin"], row["publication_id"]))
    bare = notes.judge(usc_citation(row["usc_title"], row["usc_section"]), parts) if parts else None
    lettered = notes.judge(usc_citation(row["usc_title"], nnnx), parts) if parts else None
    return (
        bare.verdict if bare is not None else None,
        lettered is not None and lettered.verdict == "present",
        (row["usc_title"], nnnx) in history.get(row["rin"], ()),
    )


# --- 1. the sole-survivor gate's excluded population ---------------------- #
multi_counts: Counter[str] = Counter()
for row, candidate in multi:
    bare, w2a, w2b = witnesses(row, candidate.section)
    if bare == "present":
        multi_counts["note_names_bare_section"] += 1
    elif w2a and w2b:
        multi_counts["would_publish_on_both"] += 1
    elif w2a:
        multi_counts["would_publish_on_2a"] += 1
    elif w2b:
        multi_counts["would_publish_on_2b"] += 1
    else:
        multi_counts["witnessless"] += 1
excluded_but_corroborated = (
    multi_counts["would_publish_on_2a"] + multi_counts["would_publish_on_2b"] + multi_counts["would_publish_on_both"]
)
print()
print("=== 1. what the sole-survivor gate excludes ===")
print("multi-survivor B8 rows by what the witnesses WOULD have said:", dict(multi_counts))
print("  witness-corroborated AND conflict-free (blocked only by the gate):", excluded_but_corroborated)

# --- 2. the counter-evidence rider's two sub-populations ------------------ #
rider = Counter()
lone_counts: Counter[str] = Counter()
witnessless_rows: list[tuple[dict, object]] = []
for row, candidate in lone:
    bare, w2a, w2b = witnesses(row, candidate.section)
    if bare == "present":
        lone_counts["note_names_bare_section"] += 1
        rider["both_named" if w2a else "bare_only"] += 1
        continue
    if w2a or w2b:
        lone_counts["promoted"] += 1
    else:
        lone_counts["witnessless"] += 1
        witnessless_rows.append((row, candidate))
print()
print("=== 2. the counter-evidence rider's two sub-populations ===")
print("LONE outcomes (replay of the shipped rule's own arithmetic):", dict(lone_counts))
print("  of the refusals: note names BOTH bare and lettered:", rider["both_named"])
print("  of the refusals: note names the BARE section only:", rider["bare_only"])

# --- 3. the bounded text-scan proxy over the witnessless rows ------------- #
# The bound the mined survey's own regex lacked: a following HYPHEN is
# excluded as well as a following digit/letter, so "615a" inside "615a-1"
# -- a different, real, separately enumerated section -- never counts.
text_hits = 0
for row, candidate in witnessless_rows:
    pattern = re.compile(
        rf"(?<![0-9]){row['usc_title']}\s*U\.?\s*S\.?\s*C\.?\s*\.?\s*{re.escape(candidate.section)}(?![0-9a-z-])",
        re.IGNORECASE,
    )
    if any(pattern.search(text) for text in texts_by_rin.get(row["rin"], ())):
        text_hits += 1
print()
print("=== 3. would a bounded same-RIN text scan rescue any witnessless row? ===")
print("witnessless rows:", len(witnessless_rows), "| rescued by a bounded text scan:", text_hits)

# --- 4/5. witness 2b's edition spread among the rows it alone promotes ---- #
same_edition = cross_edition = 0
for row, candidate in lone:
    bare, w2a, w2b = witnesses(row, candidate.section)
    if bare == "present" or w2a or not w2b:
        continue
    sightings = [
        publication
        for (publication, title, section) in rows_by_rin.get(row["rin"], ())
        if title == row["usc_title"] and section == candidate.section
    ]
    if any(publication == row["publication_id"] for publication in sightings):
        same_edition += 1
    else:
        cross_edition += 1
print()
print("=== 5. witness 2b's edition spread (rows 2b alone promotes) ===")
print("witness in the SAME edition:", same_edition, "| cross-edition only:", cross_edition)

# --- 6. the FTC specimen's own edition count ------------------------------ #
ftc = [
    row
    for row in authorities
    if row["rin"] == "3084-AB46" and row["authority_text"] == "15 U.S.C. 18(a), Clayton Act"
]
ftc_editions = sorted({row["publication_id"] for row in ftc})
print()
print("=== 6. the FTC specimen (RIN 3084-AB46, '15 U.S.C. 18(a), Clayton Act') ===")
print("rows:", len(ftc), "| distinct editions:", len(ftc_editions))
print("editions:", ftc_editions)

summary = {
    "b8_survivor_rows": len(lone) + len(multi),
    "b8_survivor_appendix_rows": appendix_rows,
    "lone_b8_rows": len(lone),
    "lone_outcomes": dict(lone_counts),
    "multi_b8_rows": len(multi),
    "multi_b8_by_would_be_outcome": dict(multi_counts),
    "multi_b8_corroborated_and_conflict_free": excluded_but_corroborated,
    "rider_note_names_both": rider["both_named"],
    "rider_note_names_bare_only": rider["bare_only"],
    "witnessless_rows": len(witnessless_rows),
    "witnessless_rescued_by_bounded_text_scan": text_hits,
    "witness_2b_only_same_edition": same_edition,
    "witness_2b_only_cross_edition": cross_edition,
    "ftc_specimen_rows": len(ftc),
    "ftc_specimen_editions": len(ftc_editions),
    "ftc_specimen_edition_range": [ftc_editions[0], ftc_editions[-1]] if ftc_editions else [],
}
with open(OUT / "excluded_summary.json", "w") as handle:
    json.dump(summary, handle, indent=2, sort_keys=True)
print()
print("wrote", OUT / "excluded_summary.json")
print(json.dumps(summary, indent=2, sort_keys=True))

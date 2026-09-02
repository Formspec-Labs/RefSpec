"""Read-only measurement: run the SHIPPED two-witness B8 promotion in-memory
against the current pinned artifact, and derive the receipt deltas its
integration into a real rebuild is expected to produce.

This does NOT run the shared rebuild (forbidden for this lane) and does NOT
write anything under output/. It loads the current
unified_agenda_legal_authorities / unified_agenda_cfr_references parquet
files read-only, copies the legal-authorities rows into fresh dicts (so
nothing here mutates the artifact on disk), and calls the REAL
`refspec.registry.unified_agenda_parquet._promote_two_witness_b8` and its
sibling `_held_parts_by_rule` -- the exact functions now wired into the
builder -- rather than re-deriving their logic. This is the "dry-run
function call in-memory" the lane brief allows.

Run with: PYTHONPATH=src .venv/bin/python
research/evidence/b8-enlargement-2026-09-01/measure_b8_two_witness.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")

import pyarrow.parquet as pq

from refspec.registry.cfr_authority_notes import CfrAuthorityNotes, usc_citation
from refspec.registry.unified_agenda_parquet import (
    _USC_B8_ORACLE_RULE,
    USC_B8_PROMOTION_OUTCOMES,
    USC_B8_PROMOTION_RULE,
    _held_parts_by_rule,
    _promote_two_witness_b8,
)
from refspec.registry.usc_section_oracle import UscSectionOracle

ROOT = Path(".")
OUT = Path(__file__).parent

LA_PATH = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"
REF_PATH = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet"

print("loading oracle + notes ...", flush=True)
oracle = UscSectionOracle.from_repository(ROOT)
notes = CfrAuthorityNotes.from_repository(ROOT)

print("loading legal_authorities parquet (all columns, current artifact) ...", flush=True)
la_table = pq.read_table(LA_PATH)
authorities = la_table.to_pylist()
print("legal_authorities rows:", len(authorities), flush=True)

print("loading cfr_references parquet ...", flush=True)
ref_table = pq.read_table(REF_PATH)
references = ref_table.to_pylist()
print("cfr_references rows:", len(references), flush=True)

# --- Baseline: today's LONE:B8 census hole, measured directly ------------- #
# Replays _judge_usc_sections's own two questions (correction_candidates,
# corrected_section) over the SAME population _promote_two_witness_b8 will
# see, to name exactly which rows are "B8 named alone, published nowhere" --
# the hole inv-b8's rider #1 names -- before any promotion runs.
print()
print("=== baseline: rows where the oracle's B8 candidate stands ALONE ===", flush=True)
lone_b8_rows = 0
lone_b8_texts: set[str] = set()
lone_b8_rins: set[str] = set()
memo_baseline: dict[tuple[int, str, str], bool] = {}
for row in authorities:
    if (
        row["authority_type"] != "usc"
        or row["usc_title"] is None
        or row["usc_section"] is None
        or row["usc_section_corrected"] is not None
    ):
        continue
    section = row["usc_section"]
    if not section.isdigit():
        continue
    key = (row["usc_title"], section, row["authority_text"])
    is_lone_b8 = memo_baseline.get(key)
    if is_lone_b8 is None:
        survivors = tuple(
            c for c in oracle.correction_candidates(row["usc_title"], section, row["authority_text"])
            if c.fenced_by is None
        )
        is_lone_b8 = len(survivors) == 1 and survivors[0].rule == _USC_B8_ORACLE_RULE
        memo_baseline[key] = is_lone_b8
    if is_lone_b8:
        lone_b8_rows += 1
        lone_b8_texts.add(row["authority_text"])
        lone_b8_rins.add(row["rin"])

print("LONE:B8 rows (correction=None, survivors=None today):", lone_b8_rows)
print("  distinct texts:", len(lone_b8_texts))
print("  distinct RINs:", len(lone_b8_rins))

# --- Run the shipped promotion, on a COPY, read-only against the artifact - #
print()
print("=== running the shipped _promote_two_witness_b8 (in-memory copy) ===", flush=True)
copy_rows = [dict(row) for row in authorities]  # fresh dicts; never touches the loaded `authorities`
counts = _promote_two_witness_b8(copy_rows, references, oracle, notes)
print("outcome counts:", counts)
assert set(counts) == set(USC_B8_PROMOTION_OUTCOMES)
assert sum(counts.values()) == lone_b8_rows, (
    f"promotion outcomes {sum(counts.values())} != measured LONE:B8 population {lone_b8_rows} "
    "-- the census would not be honest"
)
print("sum(outcomes) == LONE:B8 population:", sum(counts.values()), "== ", lone_b8_rows, "(closes the hole)")

promoted_rows = [row for row in copy_rows if row["usc_section_correction_evidence"] == USC_B8_PROMOTION_RULE]
promoted_rins = {row["rin"] for row in promoted_rows}
promoted_texts = {row["authority_text"] for row in promoted_rows}
promoted_pairs = {(row["usc_title"], row["usc_section"]) for row in promoted_rows}
promoted_targets = {(row["usc_title"], row["usc_section_corrected_section"]) for row in promoted_rows}

print()
print("=== promoted population detail ===")
print("promoted rows:", len(promoted_rows))
print("promoted distinct RINs:", len(promoted_rins))
print("promoted distinct authority_text:", len(promoted_texts))
print("promoted distinct (title, bare section) pairs:", len(promoted_pairs))
print("promoted distinct (title, corrected identity) targets:", len(promoted_targets))

# Every promoted row's verdict on the BARE section today, for the receipt
# cross-check ("every one reading `exists` today" -- inv-b8's own claim).
verdicts = Counter(row["usc_section_verdict"] for row in promoted_rows)
print("promoted rows' CURRENT usc_section_verdict (bare section):", dict(verdicts))

print()
print("=== the two conflict specimens the mission named (rider #2) ===")
for rin in ("1904-AC49", "3060-AK40"):
    outcome = {row["usc_section_correction_evidence"] for row in copy_rows if row["rin"] == rin}
    print(f"  {rin}: usc_section_correction_evidence values across its rows = {outcome}")

with open(OUT / "promoted_rows.jsonl", "w") as f:
    for row in promoted_rows:
        f.write(
            json.dumps(
                {
                    "rin": row["rin"],
                    "publication_id": row["publication_id"],
                    "ordinal": row["ordinal"],
                    "citation_ordinal": row["citation_ordinal"],
                    "authority_text": row["authority_text"],
                    "usc_title": row["usc_title"],
                    "usc_section": row["usc_section"],
                    "usc_section_corrected_section": row["usc_section_corrected_section"],
                }
            )
            + "\n"
        )
print()
print("wrote", OUT / "promoted_rows.jsonl", f"({len(promoted_rows)} rows)")

# --- Witness attribution, for the report (informational -- not a gate) ---- #
print()
print("=== witness attribution among the 666 promoted rows ===")
held_by_rule = _held_parts_by_rule(references, notes)
history_pairs: dict[str, set[tuple[int, str]]] = {}
for row in authorities:
    if row["parse_status"] == "corroborated":
        continue
    if (
        row["authority_type"] == "usc"
        and row["usc_title"] is not None
        and row["usc_section"]
        and not row["usc_appendix"]
        and row["usc_title_is_possible"]
    ):
        history_pairs.setdefault(row["rin"], set()).add((row["usc_title"], row["usc_section"].lower()))

both = only_2a = only_2b = 0
for row in promoted_rows:
    parts = held_by_rule.get((row["rin"], row["publication_id"]))
    nnnx = row["usc_section_corrected_section"]
    note_lettered = notes.judge(usc_citation(row["usc_title"], nnnx), parts) if parts else None
    w2a = note_lettered is not None and note_lettered.verdict == "present"
    w2b = (row["usc_title"], nnnx) in history_pairs.get(row["rin"], ())
    if w2a and w2b:
        both += 1
    elif w2a:
        only_2a += 1
    elif w2b:
        only_2b += 1
print(f"  witness 2a only (note names it, no sibling-edition structural match): {only_2a}")
print(f"  witness 2b only (a sibling row's own parse, no note coverage/match): {only_2b}")
print(f"  both witnesses fire: {both}")
assert only_2a + only_2b + both == len(promoted_rows)

summary = {
    "la_rows_scanned": len(authorities),
    "lone_b8_rows_baseline": lone_b8_rows,
    "lone_b8_texts_baseline": len(lone_b8_texts),
    "lone_b8_rins_baseline": len(lone_b8_rins),
    "promotion_outcome_counts": counts,
    "promoted_rows": len(promoted_rows),
    "promoted_distinct_rins": len(promoted_rins),
    "promoted_distinct_texts": len(promoted_texts),
    "promoted_distinct_base_pairs": len(promoted_pairs),
    "promoted_distinct_target_pairs": len(promoted_targets),
    "promoted_verdicts_on_bare_section": dict(verdicts),
    "promoted_witness_2a_only": only_2a,
    "promoted_witness_2b_only": only_2b,
    "promoted_both_witnesses": both,
}
with open(OUT / "summary.json", "w") as f:
    json.dump(summary, f, indent=2, sort_keys=True)
print("wrote", OUT / "summary.json")
print(json.dumps(summary, indent=2, sort_keys=True))

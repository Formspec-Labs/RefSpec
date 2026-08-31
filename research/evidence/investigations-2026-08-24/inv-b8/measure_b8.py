"""Read-only B8 two-witness measurement. Import-only, PYTHONPATH=src.

Population: rows with a bare-digit usc_section (NNN) whose authority_text
carries a parenthesised SINGLE-LETTER pinpoint on that exact section, where
NNN+letter (NNNx) is enumerated by the section oracle.

Witness 1: the subsection oracle on the bare section NNN, letter x.
Witness 2a: the CFR authority note held by the rule (rin, publication_id).
Witness 2b: the same RIN's other editions, text-spelling NNNx / "NNN x" / "NNN-x".
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")

import pyarrow.parquet as pq

from refspec.registry.usc_section_oracle import (
    UscSectionOracle,
    normalize_section,
)
from refspec.registry.cfr_authority_notes import (
    CfrAuthorityNotes,
    normalize_part,
    usc_citation,
)

ROOT = Path(".")
OUT = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-b8")
OUT.mkdir(parents=True, exist_ok=True)

LA_PATH = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"
REF_PATH = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet"

print("loading oracle + notes ...", flush=True)
oracle = UscSectionOracle.from_repository(ROOT)
notes = CfrAuthorityNotes.from_repository(ROOT)
print("oracle sections:", len(oracle.enumerated), "notes:", len(notes.records), flush=True)

print("loading legal_authorities parquet ...", flush=True)
la_cols = [
    "rin", "publication_id", "ordinal", "citation_ordinal",
    "authority_text", "authority_type", "parse_status",
    "usc_title", "usc_section", "usc_section_end",
    "usc_section_verdict", "usc_section_correction_evidence",
]
la_table = pq.read_table(LA_PATH, columns=la_cols)
la_rows = la_table.to_pylist()
print("legal_authorities rows:", len(la_rows), flush=True)

print("loading cfr_references parquet ...", flush=True)
ref_table = pq.read_table(REF_PATH, columns=["rin", "publication_id", "cfr_title", "cfr_part"])
ref_rows = ref_table.to_pylist()
print("cfr_references rows:", len(ref_rows), flush=True)

# -- held parts per (rin, publication_id), mirroring the builder's own join -- #
held_by_rule: dict[tuple[str, str], set[tuple[int, str]]] = defaultdict(set)
for r in ref_rows:
    title, part = r["cfr_title"], normalize_part(r["cfr_part"])
    if title is None or part is None or not notes.holds(title, part):
        continue
    held_by_rule[(r["rin"], r["publication_id"])].add((int(title), part))
print("rules with a held part:", len(held_by_rule), flush=True)

# -- per-RIN box texts by edition, for witness 2b -- #
texts_by_rin_edition: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
for r in la_rows:
    texts_by_rin_edition[r["rin"]][r["publication_id"]].add(r["authority_text"] or "")

# structural: (rin) -> set of usc_section values seen anywhere for that rin
sections_by_rin_edition: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
for r in la_rows:
    if r["usc_section"]:
        sections_by_rin_edition[r["rin"]][r["publication_id"]].add(r["usc_section"])


def edition_year(pub_id: str | None) -> int | None:
    s = str(pub_id or "")[:4]
    return int(s) if s.isdigit() else None


BARE = re.compile(r"^\d+$")
# single-letter pinpoint bound so it can't be a longer suffix or mid-token
PINPOINT_TMPL = r"(?<![0-9a-z-]){sec}\s*\(\s*([a-z])\s*\)(?![a-z])"
# entry["match_end"] already points PAST the pinpoint's closing paren, so the
# tail (if any) starts immediately with the hyphen -- no paren to consume.
# NOTE: no literal "^" -- .match(string, pos) anchors at pos already; "^"
# would instead demand pos == 0 and silently match nothing for pos > 0.
TAIL_AFTER = re.compile(r"\s*-\s*([0-9a-z]+)")

print("scanning population ...", flush=True)
population: list[dict] = []
scanned = 0
for r in la_rows:
    scanned += 1
    section = r["usc_section"]
    if not section or not BARE.match(section):
        continue
    title = r["usc_title"]
    if title is None:
        continue
    text_norm = normalize_section(r["authority_text"])
    pattern = re.compile(PINPOINT_TMPL.format(sec=re.escape(section)))
    seen_letters: set[str] = set()
    for m in pattern.finditer(text_norm):
        letter = m.group(1)
        if letter in seen_letters:
            continue
        seen_letters.add(letter)
        nnnx = section + letter
        if not oracle.section_is_enumerated(title, nnnx):
            continue  # gate: NNNx must exist as a section
        population.append(
            {
                "row": r,
                "title": title,
                "section": section,
                "letter": letter,
                "nnnx": nnnx,
                "match_end": m.end(),
                "text_norm": text_norm,
            }
        )

print("rows scanned:", scanned, "population entries (row,letter):", len(population), flush=True)

# dedupe population to one entry per (rin, publication_id, ordinal, citation_ordinal, letter)
# -- a (row, letter) pair is the unit; a row could in principle carry >1 distinct
#    qualifying letter for its own section, which we keep as separate population
#    rows since each is its own ambiguous/witnessed reading.
print("computing witnesses ...", flush=True)

records = []
for entry in population:
    r = entry["row"]
    title, section, letter, nnnx = entry["title"], entry["section"], entry["letter"], entry["nnnx"]
    ey = edition_year(r["publication_id"])

    sv_nnnx = oracle.section_verdict(title, nnnx, ey)
    structure = oracle.subsection_verdict(title, section, letter)

    if structure.verdict == "exists":
        structure_bucket = "ambiguous-both-real"
    elif structure.verdict == "absent":
        structure_bucket = "witness1-no-such-subsection"
    else:
        structure_bucket = f"unknown-structure:{structure.reason}"

    # tail: does the text carry a further tail right after the pinpoint?
    tail_match = TAIL_AFTER.match(entry["text_norm"], entry["match_end"])
    text_tail = tail_match.group(1) if tail_match else None
    affirmed_tails = oracle.tail_stated_sections(title, section, r["authority_text"], letter=letter)
    candidate_identity = affirmed_tails[0] if affirmed_tails else nnnx

    # witness 2a: the rule's held CFR authority note
    parts = held_by_rule.get((r["rin"], r["publication_id"]))
    note_bucket = "no-note-held"
    note_verdict_x = None
    note_verdict_bare = None
    note_part = None
    if parts:
        cite_x = usc_citation(title, candidate_identity)
        cite_bare = usc_citation(title, section)
        v_x = notes.judge(cite_x, parts) if cite_x else None
        v_bare = notes.judge(cite_bare, parts) if cite_bare else None
        note_verdict_x = v_x.verdict if v_x else None
        note_verdict_bare = v_bare.verdict if v_bare else None
        note_part = v_x.cited_as if (v_x and v_x.verdict == "present") else (v_bare.cited_as if v_bare else None)
        agree = v_x is not None and v_x.verdict == "present"
        disagree = v_bare is not None and v_bare.verdict == "present" and not agree
        if agree and disagree:
            note_bucket = "both-present"
        elif agree:
            note_bucket = "agree-names-NNNx"
        elif disagree:
            note_bucket = "disagree-names-NNN"
        else:
            note_bucket = "absent-in-note"

    # witness 2b: the RIN's other editions
    rin = r["rin"]
    this_pub = r["publication_id"]
    other_editions = [pub for pub in texts_by_rin_edition[rin] if pub != this_pub]
    w2b_bucket = "no-other-editions" if not other_editions else "absent-elsewhere"
    w2b_evidence = None
    if other_editions:
        letter_re = re.escape(letter)
        sec_re = re.escape(section)
        bare_pat = re.compile(rf"(?<![0-9a-z]){sec_re}{letter_re}(?![0-9a-z])")
        space_pat = re.compile(rf"(?<![0-9a-z]){sec_re}\s+{letter_re}(?![a-z0-9])")
        hyphen_pat = re.compile(rf"(?<![0-9a-z]){sec_re}-{letter_re}(?![a-z0-9])")
        found = False
        for pub in other_editions:
            for txt in texts_by_rin_edition[rin][pub]:
                tn = normalize_section(txt)
                if bare_pat.search(tn):
                    w2b_evidence = f"bare NNNx in {pub}"
                    found = True
                    break
                if space_pat.search(tn):
                    w2b_evidence = f"'NNN x' in {pub}"
                    found = True
                    break
                if hyphen_pat.search(tn):
                    w2b_evidence = f"'NNN-x' in {pub}"
                    found = True
                    break
            if found:
                break
        # structural corroboration: another row for this rin (any edition) parsed usc_section == nnnx
        structural = any(
            nnnx in sections_by_rin_edition[rin][pub]
            for pub in sections_by_rin_edition[rin]
            if pub != this_pub
        )
        if found:
            w2b_bucket = "text-spells-NNNx"
        elif structural:
            w2b_bucket = "structural-only-NNNx"
            w2b_evidence = "another edition's row parsed usc_section == NNNx"
        else:
            w2b_bucket = "absent-elsewhere"

    records.append(
        {
            "rin": r["rin"],
            "publication_id": r["publication_id"],
            "ordinal": r["ordinal"],
            "citation_ordinal": r["citation_ordinal"],
            "authority_text": r["authority_text"],
            "title": title,
            "section": section,
            "letter": letter,
            "nnnx": nnnx,
            "candidate_identity": candidate_identity,
            "has_tail": text_tail is not None,
            "text_tail": text_tail,
            "affirmed_tail_reading": affirmed_tails[0] if affirmed_tails else None,
            "sv_nnnx_verdict": sv_nnnx.verdict,
            "sv_nnnx_attested_at_edition": sv_nnnx.attested_at_edition,
            "structure_verdict": structure.verdict,
            "structure_reason": structure.reason,
            "structure_lettered": sorted(structure.lettered),
            "structure_bucket": structure_bucket,
            "note_bucket": note_bucket,
            "note_verdict_x": note_verdict_x,
            "note_verdict_bare": note_verdict_bare,
            "note_part": note_part,
            "w2b_bucket": w2b_bucket,
            "w2b_evidence": w2b_evidence,
        }
    )

print("population records:", len(records), flush=True)

with open(OUT / "population_all.jsonl", "w") as f:
    for rec in records:
        f.write(json.dumps(rec) + "\n")

print("wrote", OUT / "population_all.jsonl", flush=True)

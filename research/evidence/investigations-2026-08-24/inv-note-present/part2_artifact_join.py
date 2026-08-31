"""Part 2: join the flagged note identities (Part 1) to the rebuild-#11
artifact's authority_in_own_cfr_note='present' rows.

Read-only: DuckDB opened without any write flags, parquet files under
output/ only read. No files under src/ or tests/ touched.
"""
from __future__ import annotations

import json
import random
import re
import sys

ROOT = "/Users/mikewolfd/Work/RefSpec"
sys.path.insert(0, f"{ROOT}/src")

import duckdb  # noqa: E402

from refspec.registry.usc_section_oracle import normalize_section  # noqa: E402

OUT_DIR = "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-note-present"
PARQUET = f"{ROOT}/output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"

flagged = json.load(open(f"{OUT_DIR}/part1_note_identity_flags.json"))
# key "title:part" -> {identity: {"classes": [...], "oracle_verdict": ..., "raw": {...}}}

con = duckdb.connect(database=":memory:", read_only=False)  # in-memory catalog; parquet itself is only read
rows = con.execute(
    f"""
    SELECT rin, publication_id, ordinal, citation_ordinal, authority_text,
           usc_title, usc_section, cfr_note_part
    FROM read_parquet('{PARQUET}')
    WHERE authority_in_own_cfr_note = 'present' AND authority_type = 'usc'
    """
).fetchall()
print(f"present usc rows: {len(rows)}", file=sys.stderr)

CFR_NOTE_PART_RE = re.compile(r"^(\d+) CFR (.+)$")


def note_key_for(cfr_note_part: str) -> str | None:
    m = CFR_NOTE_PART_RE.match(cfr_note_part or "")
    if not m:
        return None
    return f"{int(m.group(1))}:{m.group(2)}"


# -- join: which present rows matched a FLAGGED note identity (exact, not span) --
matched_rows = []  # dicts
rows_by_class = {"paren": set(), "spaced": set(), "lost_hyphen": set(), "cross_family_bleed": set(), "any": set()}
texts_by_class = {"paren": set(), "spaced": set(), "lost_hyphen": set(), "cross_family_bleed": set(), "any": set()}
parts_by_class = {"paren": set(), "spaced": set(), "lost_hyphen": set(), "cross_family_bleed": set(), "any": set()}

for rin, pub_id, ordinal, cit_ordinal, authority_text, usc_title, usc_section, cfr_note_part in rows:
    if usc_title is None or usc_section is None:
        continue
    section = normalize_section(usc_section)
    identity = f"{int(usc_title)}:{section}"
    note_key = note_key_for(cfr_note_part)
    if note_key is None:
        continue
    note_flags = flagged.get(note_key)
    if not note_flags or identity not in note_flags:
        continue
    info = note_flags[identity]
    row_key = (rin, pub_id, ordinal, cit_ordinal)
    matched_rows.append(
        {
            "row_key": row_key,
            "authority_text": authority_text,
            "identity": identity,
            "cfr_note_part": cfr_note_part,
            "note_key": note_key,
            "classes": info["classes"],
            "oracle_verdict": info["oracle_verdict"],
            "note_raw": info["raw"],
        }
    )
    for c in info["classes"]:
        rows_by_class[c].add(row_key)
        texts_by_class[c].add(authority_text)
        parts_by_class[c].add(note_key)
    rows_by_class["any"].add(row_key)
    texts_by_class["any"].add(authority_text)
    parts_by_class["any"].add(note_key)

print(f"matched (present-via-flagged-note-token) rows: {len(matched_rows)}", file=sys.stderr)

# -- among matched rows: is the ROW'S OWN citation also shape-damaged, or clean? --
_PAREN_SUFFIX = re.compile(r"(?<![0-9A-Za-z])(\d{1,5})\(\s*([a-zA-Z]{1,4})\s*\)")
import refspec.registry.usc_section_oracle as oraclemod  # noqa: E402

_SPACED_SUFFIX = oraclemod._SPACED_SUFFIX
_DOTTED_ABBREV_TAIL = re.compile(r"^\.\s*[a-z]")


def row_own_citation_is_shape_damaged(authority_text: str, section: str) -> bool:
    norm = normalize_section(authority_text)
    for m in _PAREN_SUFFIX.finditer(norm):
        if m.group(1) == section:
            return True
    for m in _SPACED_SUFFIX.finditer(norm):
        if m.group("stem") == section and not _DOTTED_ABBREV_TAIL.match(norm[m.end("suffix") :]):
            return True
    return False


both_damaged = 0
row_clean_note_damaged_only = 0
for row in matched_rows:
    section = row["identity"].split(":", 1)[1]
    if row_own_citation_is_shape_damaged(row["authority_text"], section):
        both_damaged += 1
        row["row_own_shape_damaged"] = True
    else:
        row_clean_note_damaged_only += 1
        row["row_own_shape_damaged"] = False

# -- item 3: the coincidental-stem class --
# rows 'present' where the row's RAW text carries a decoration the parsed
# identity dropped (.NNN reg tail / (x) suffix run / -N tail) and the note's
# matching token is the BARE stem -- identity equality by truncation.
stem_rows = con.execute(
    f"""
    SELECT rin, publication_id, ordinal, citation_ordinal, authority_text,
           usc_title, usc_section, cfr_note_part
    FROM read_parquet('{PARQUET}')
    WHERE authority_in_own_cfr_note = 'present' AND authority_type = 'usc'
      AND usc_section ~ '^[0-9]+$'
      AND usc_section_verdict = 'absent'
    """
).fetchall()
print(f"present usc rows, bare-digit usc_section, oracle-absent: {len(stem_rows)}", file=sys.stderr)

# A single "(a)" pinpoint after a REAL section (usc_section_verdict='absent'
# already excludes that -- a real section wouldn't verdict absent) is still
# routine grammar (7 U.S.C. 2(c)(2)(E) is a genuine chained pinpoint on a
# real section 2). What the task calls a "(x) suffix run" is TWO OR MORE
# chained parenthetical groups directly on a section the oracle says does
# not exist -- the shape a dropped regulation number leaves behind
# ("1.104-1(c)" truncates to bare "1" with nothing chained, so in practice
# this decoration mostly co-occurs with a reg_tail; kept as its own signal
# since a filer can drop the "1." and keep the letter run: "104-1(c)").
_REG_TAIL = re.compile(r"\.\d")  # ".NNN" reg tail immediately after the bare number
_PAREN_RUN = re.compile(r"(?:\(\s*[0-9a-zA-Z]{1,4}\s*\)){2,}")
_DASH_TAIL = re.compile(r"-\d")

coincidental_stem_candidates = []
for rin, pub_id, ordinal, cit_ordinal, authority_text, usc_title, usc_section, cfr_note_part in stem_rows:
    section = normalize_section(usc_section)
    norm_text = normalize_section(authority_text)
    # find the bare-token occurrence(s) of `section` in the row's own text and
    # see what immediately follows it there
    decorations = []
    for m in re.finditer(rf"(?<![0-9A-Za-z]){re.escape(section)}", norm_text):
        tail = norm_text[m.end() : m.end() + 10]
        if _REG_TAIL.match(tail):
            decorations.append(("reg_tail", tail[:6]))
        elif _PAREN_RUN.match(tail):
            decorations.append(("paren_run", tail[:6]))
        elif _DASH_TAIL.match(tail):
            decorations.append(("dash_tail", tail[:6]))
    if not decorations:
        continue
    note_key = note_key_for(cfr_note_part)
    identity = f"{int(usc_title)}:{section}"
    coincidental_stem_candidates.append(
        {
            "row_key": (rin, pub_id, ordinal, cit_ordinal),
            "authority_text": authority_text,
            "identity": identity,
            "cfr_note_part": cfr_note_part,
            "note_key": note_key,
            "decorations": decorations,
        }
    )

print(f"coincidental-stem candidates (row text decorated, identity by truncation): {len(coincidental_stem_candidates)}", file=sys.stderr)

# seeded 20, per review2's own method: sorted keys, random.Random(20260823)
sorted_keys = sorted(c["row_key"] for c in coincidental_stem_candidates)
rng = random.Random(20260823)
seeded_20_keys = rng.sample(sorted_keys, min(20, len(sorted_keys)))
by_key = {c["row_key"]: c for c in coincidental_stem_candidates}
seeded_20 = [by_key[k] for k in seeded_20_keys]

# -- item 4: recommendation -- compare on the note's VERBATIM token --
# For each matched (flagged-note-token) row, does the row's own raw
# authority_text contain (whitespace/entity normalized) the exact verbatim
# substring that produced the note's identity?
def whitespace_normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


would_move_to_present_by_stem = []
would_stay_present = []
for row in matched_rows:
    row_text_norm = whitespace_normalize(row["authority_text"])
    note_tokens = []
    for cls, toks in row["note_raw"].items():
        note_tokens.extend(toks)
    verbatim_hit = any(whitespace_normalize(tok) in row_text_norm for tok in note_tokens)
    row["verbatim_note_token_in_row_text"] = verbatim_hit
    if verbatim_hit:
        would_stay_present.append(row)
    else:
        would_move_to_present_by_stem.append(row)

summary = {
    "present_usc_rows_total": len(rows),
    "matched_present_rows_via_flagged_note_token": len(matched_rows),
    "rows_by_class": {k: len(v) for k, v in rows_by_class.items()},
    "distinct_texts_by_class": {k: len(v) for k, v in texts_by_class.items()},
    "distinct_note_parts_by_class": {k: len(v) for k, v in parts_by_class.items()},
    "row_own_citation_also_shape_damaged": both_damaged,
    "row_own_citation_clean_note_only_damaged": row_clean_note_damaged_only,
    "coincidental_stem_candidates_total": len(coincidental_stem_candidates),
    "coincidental_stem_candidates_by_decoration": {
        kind: sum(1 for c in coincidental_stem_candidates if any(d[0] == kind for d in c["decorations"]))
        for kind in ("reg_tail", "paren_run", "dash_tail")
    },
    "recommendation_item4": {
        "rows_that_would_move_present_to_present_by_stem": len(would_move_to_present_by_stem),
        "rows_that_would_stay_present_verbatim_token_matches": len(would_stay_present),
    },
}

print(json.dumps(summary, indent=2))

with open(f"{OUT_DIR}/part2_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
with open(f"{OUT_DIR}/part2_matched_rows.json", "w") as f:
    json.dump(matched_rows, f, indent=2, default=str)
with open(f"{OUT_DIR}/part2_coincidental_stem_seeded20.json", "w") as f:
    json.dump(seeded_20, f, indent=2, default=str)
with open(f"{OUT_DIR}/part2_coincidental_stem_all.json", "w") as f:
    json.dump(coincidental_stem_candidates, f, indent=2, default=str)
print("wrote part2 outputs", file=sys.stderr)

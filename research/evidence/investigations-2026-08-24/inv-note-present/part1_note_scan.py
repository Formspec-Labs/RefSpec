"""Part 1: scan all 8,240 CFR authority notes for shape-damaged raw tokens
that reduce to a bare-digit U.S.C. identity, plus the Comp.-year phantom
check and the oracle-absent check over every U.S.C. identity a note names.

Read-only. Imports only. No files under src/ or tests/ are touched.
"""
from __future__ import annotations

import json
import re
import sys

ROOT = "/Users/mikewolfd/Work/RefSpec"
sys.path.insert(0, f"{ROOT}/src")

from refspec.registry.cfr_authority_notes import CfrAuthorityNotes  # noqa: E402
import refspec.registry.usc_section_oracle as oraclemod  # noqa: E402
from refspec.registry.usc_section_oracle import UscSectionOracle, normalize_section  # noqa: E402

_SPACED_SUFFIX = oraclemod._SPACED_SUFFIX
_DAMAGED_TOKEN = oraclemod._DAMAGED_TOKEN

_PAREN_SUFFIX = re.compile(r"(?<![0-9A-Za-z])(\d{1,5})\(\s*([a-zA-Z]{1,4})\s*\)")
_YEAR_PART = re.compile(r"^(1[789]|20)\d{2}$")

#: Which citation family a bare digit run belongs to depends on what labelled
#: it -- "48 Stat. 74, 78, 81, 85" lists STATUTE PAGES, not U.S.C. sections,
#: and a naive "is this bare token written anywhere in the note" scan reads
#: the "78" in that Statutes list as a clean witness for U.S.C. section 78,
#: which it is not (17 CFR 240's note does this: "48 Stat. 74, 78, 81, 85"
#: sits a few sentences from the note's real 15 U.S.C. list). So a candidate
#: "clean" occurrence is only trusted when the label immediately governing it
#: -- the last of these markers seen looking backward -- is a U.S.C. one.
_FAMILY_LABEL = re.compile(r"u\.?\s*s\.?\s*c\b|stat\b|c\.?\s*f\.?\s*r\b|\bfr\b|pub\.?\s*l")
_USC_LABEL = re.compile(r"u\.?\s*s\.?\s*c\b")
_LABEL_LOOKBACK = 120

print("loading notes...", file=sys.stderr)
notes = CfrAuthorityNotes.from_repository(ROOT)
print(f"loaded {len(notes.records)} notes, sha256={notes.sha256}", file=sys.stderr)
print("binding oracle...", file=sys.stderr)
oracle = UscSectionOracle.from_repository(ROOT)
print("oracle bound", file=sys.stderr)


def classify_bare_section(body_norm: str, section: str) -> dict:
    """Every raw occurrence of the bare token `section` in body_norm, classified."""

    out = {"paren": [], "spaced": [], "lost_hyphen": [], "clean": []}

    paren_hits = [m for m in _PAREN_SUFFIX.finditer(body_norm) if m.group(1) == section]
    for m in paren_hits:
        out["paren"].append(m.group(0))

    # _SPACED_SUFFIX is the codebase's own regex, but its real callers always
    # run it against one row's short authority_text with `section` already
    # the PARSED SECTION (never the title digit, and never a volume number in
    # an adjacent citation family). Run loose over a whole 7,000-character
    # note it also matches: the TITLE digit right before a "U.S.C." label
    # ("5 U.S.C. 1302" reads stem="5", suffix="u"), a Treaty Series volume
    # ("19 U.S.T. 6223"), a UNTS volume ("1870 U.N.T.S. 167") and a case
    # reporter volume ("444 U.S. 507") -- all four are real production
    # readings this note's own `read_note_citations` produces (verified by
    # hand for 8 CFR 223 -> usc 8:19 and 32 CFR 1905 -> usc 50:340/50:444),
    # which is itself a finding, but they are a DIFFERENT mechanism
    # (title-carried-across-a-semicolon into the next citation's volume
    # number) from a genuine lost-space letter suffix. A real Code suffix is
    # bare letters; every one of these false suffixes is immediately
    # followed by MORE dotted abbreviation letters (".s.c", ".s.t", ".n.t.s",
    # ". 507" for a bare "U.S." reporter). That shape is the guard.
    _DOTTED_ABBREV_TAIL = re.compile(r"^\.\s*[a-z]")
    spaced_hits = []
    cross_family_bleed = []
    for m in _SPACED_SUFFIX.finditer(body_norm):
        if m.group("stem") != section:
            continue
        if _DOTTED_ABBREV_TAIL.match(body_norm[m.end("suffix") :]):
            cross_family_bleed.append(m.group(0))
            continue
        spaced_hits.append(m)
    for m in spaced_hits:
        out["spaced"].append(m.group(0))
    out["cross_family_bleed"] = cross_family_bleed

    lost_hyphen_hits = []
    for m in _DAMAGED_TOKEN.finditer(body_norm):
        token = m.group(1)
        dm = re.match(r"\d+", token)
        if dm is None or dm.group(0) != section:
            continue
        # exclude a token that is actually a clean single-repeated-letter
        # compound (not damage at all) -- same guard
        # recovered_lost_hyphen_sections uses.
        if re.fullmatch(r"\d+([a-z])\1*", token):
            continue
        lost_hyphen_hits.append((m.start(), m.end(), token))
    for start, end, token in lost_hyphen_hits:
        out["lost_hyphen"].append(body_norm[start:end])

    damaged_spans = (
        [m.span() for m in paren_hits]
        + [m.span() for m in spaced_hits]
        + [(s, e) for s, e, _ in lost_hyphen_hits]
    )

    for m in re.finditer(rf"(?<![0-9A-Za-z]){re.escape(section)}(?![0-9A-Za-z])", body_norm):
        if any(start <= m.start() < end for start, end in damaged_spans):
            continue
        window = body_norm[max(0, m.start() - _LABEL_LOOKBACK) : m.start()]
        labels = list(_FAMILY_LABEL.finditer(window))
        if not labels:
            continue  # no governing label at all -- not a U.S.C. witness either
        nearest = labels[-1]
        if not _USC_LABEL.match(nearest.group(0)):
            continue  # nearest label is Stat./CFR/FR/Pub. L., not U.S.C.
        out["clean"].append(body_norm[max(0, m.start() - 12) : m.end() + 12])

    return out


# -- Part 1a: per-note, per bare-digit U.S.C. identity, shape classification --
note_identity_flags: dict = {}  # (title, part) -> {identity: {...}}
class_occurrence_counts = {"paren": 0, "spaced": 0, "lost_hyphen": 0, "cross_family_bleed": 0}
class_note_sets = {"paren": set(), "spaced": set(), "lost_hyphen": set(), "cross_family_bleed": set()}
flagged_identity_note_sets = {"paren": set(), "spaced": set(), "lost_hyphen": set(), "cross_family_bleed": set(), "any": set()}
flagged_identity_count = {"paren": 0, "spaced": 0, "lost_hyphen": 0, "cross_family_bleed": 0, "any": 0}

# -- Part 1b: Comp.-year phantom --
comp_year_hits = []  # (title, part, identity)
comp_year_notes = set()

# -- Part 1c: oracle-absent over EVERY usc identity a note names --
oracle_absent_hits = []  # (title, part, identity)
oracle_absent_notes = set()
oracle_unknown_hits = []
oracle_exists_count = 0

total_usc_identities = 0
total_bare_digit_identities = 0

for note in notes.records:
    key = (note.cfr_title, note.cfr_part)
    body_norm = normalize_section(note.authority_note)  # lowercase + dash-fold, same length
    per_note_flags = {}
    any_flagged_this_note = {"paren": False, "spaced": False, "lost_hyphen": False, "cross_family_bleed": False}

    for citation in note.citations:
        if citation.family == "cfr":
            note_title, note_part_id = citation.identity.split(":", 1)
            if note_title == "3" and _YEAR_PART.match(note_part_id):
                comp_year_hits.append((note.cfr_title, note.cfr_part, citation.identity))
                comp_year_notes.add(key)
            continue

        if citation.family != "usc":
            continue

        total_usc_identities += 1
        title_str, section = citation.identity.split(":", 1)
        title = int(title_str)

        verdict = oracle.section_verdict(title, section).verdict
        if verdict == "absent":
            oracle_absent_hits.append((note.cfr_title, note.cfr_part, citation.identity))
            oracle_absent_notes.add(key)
        elif verdict == "unknown":
            oracle_unknown_hits.append((note.cfr_title, note.cfr_part, citation.identity))
        else:
            oracle_exists_count += 1

        if not section.isdigit():
            continue
        total_bare_digit_identities += 1

        occ = classify_bare_section(body_norm, section)
        has_clean = bool(occ["clean"])
        # The C3 / space-lost gate this codebase already uses: a digit(letter)
        # or spaced-suffix or lost-hyphen shape is only a DEFECT candidate
        # when the BARE stem itself is not a real section on its own --
        # otherwise "7 U.S.C. 2(c)(2)(E)" (a genuine pinpoint on a real
        # section 2) would be flagged identically to "15 U.S.C. 78(f)" (78
        # is not real). Both this module's own C3 and space-lost rules gate
        # on exactly this (`self.section_exists(title, section)`).
        bare_stem_is_real = oracle.section_exists(title, section)
        has_paren = bool(occ["paren"]) and not bare_stem_is_real
        has_spaced = bool(occ["spaced"]) and not bare_stem_is_real
        has_lost_hyphen = bool(occ["lost_hyphen"]) and not bare_stem_is_real
        has_cross_bleed = bool(occ["cross_family_bleed"]) and not bare_stem_is_real

        for cls, hits in (
            ("paren", occ["paren"]),
            ("spaced", occ["spaced"]),
            ("lost_hyphen", occ["lost_hyphen"]),
            ("cross_family_bleed", occ["cross_family_bleed"]),
        ):
            if hits:
                class_occurrence_counts[cls] += len(hits)
                class_note_sets[cls].add(key)

        is_flagged = (has_paren or has_spaced or has_lost_hyphen or has_cross_bleed) and not has_clean
        if is_flagged:
            classes_here = [
                c
                for c, h in (
                    ("paren", has_paren),
                    ("spaced", has_spaced),
                    ("lost_hyphen", has_lost_hyphen),
                    ("cross_family_bleed", has_cross_bleed),
                )
                if h
            ]
            per_note_flags[citation.identity] = {
                "classes": classes_here,
                "oracle_verdict": verdict,
                "raw": {c: occ[c] for c in classes_here},
            }
            for c in classes_here:
                flagged_identity_count[c] += 1
                flagged_identity_note_sets[c].add(key)
                any_flagged_this_note[c] = True
            flagged_identity_count["any"] += 1

    if per_note_flags:
        note_identity_flags[f"{key[0]}:{key[1]}"] = per_note_flags
    if any(any_flagged_this_note.values()):
        flagged_identity_note_sets["any"].add(key)

print("scan complete", file=sys.stderr)

summary = {
    "notes_total": len(notes.records),
    "usc_identities_total_distinct_per_note": total_usc_identities,
    "usc_identities_bare_digit": total_bare_digit_identities,
    "class_raw_occurrences": {
        "paren_suffix": class_occurrence_counts["paren"],
        "spaced_suffix": class_occurrence_counts["spaced"],
        "lost_hyphen": class_occurrence_counts["lost_hyphen"],
        "cross_family_bleed": class_occurrence_counts["cross_family_bleed"],
    },
    "class_notes_with_any_raw_occurrence": {
        "paren_suffix": len(class_note_sets["paren"]),
        "spaced_suffix": len(class_note_sets["spaced"]),
        "lost_hyphen": len(class_note_sets["lost_hyphen"]),
        "cross_family_bleed": len(class_note_sets["cross_family_bleed"]),
    },
    "flagged_identities_no_clean_witness": {
        "paren_suffix": flagged_identity_count["paren"],
        "spaced_suffix": flagged_identity_count["spaced"],
        "lost_hyphen": flagged_identity_count["lost_hyphen"],
        "cross_family_bleed": flagged_identity_count["cross_family_bleed"],
        "any_class": flagged_identity_count["any"],
    },
    "notes_with_flagged_identity": {
        "paren_suffix": len(flagged_identity_note_sets["paren"]),
        "spaced_suffix": len(flagged_identity_note_sets["spaced"]),
        "lost_hyphen": len(flagged_identity_note_sets["lost_hyphen"]),
        "cross_family_bleed": len(flagged_identity_note_sets["cross_family_bleed"]),
        "any_class": len(flagged_identity_note_sets["any"]),
    },
    "comp_year_phantom": {
        "occurrences": len(comp_year_hits),
        "notes": len(comp_year_notes),
        "examples": comp_year_hits[:20],
    },
    "oracle_absent_usc_identities": {
        "occurrences": len(oracle_absent_hits),
        "notes": len(oracle_absent_notes),
    },
    "oracle_unknown_usc_identities": len(oracle_unknown_hits),
    "oracle_exists_usc_identities": oracle_exists_count,
}

print(json.dumps(summary, indent=2))

out_dir = "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-note-present"
with open(f"{out_dir}/part1_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
with open(f"{out_dir}/part1_note_identity_flags.json", "w") as f:
    json.dump(note_identity_flags, f, indent=2)
with open(f"{out_dir}/part1_oracle_absent_hits.json", "w") as f:
    json.dump(
        {
            "absent": [{"cfr_title": t, "cfr_part": p, "identity": i} for t, p, i in oracle_absent_hits],
            "unknown": [{"cfr_title": t, "cfr_part": p, "identity": i} for t, p, i in oracle_unknown_hits],
        },
        f,
        indent=2,
    )
print("wrote outputs to", out_dir, file=sys.stderr)

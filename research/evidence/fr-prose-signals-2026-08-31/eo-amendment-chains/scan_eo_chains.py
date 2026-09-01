#!/usr/bin/env python3
"""Census EO-to-EO relation mentions in roster titles, with per-target verb attribution.

Run from the repo root: ``.venv/bin/python
research/evidence/fr-prose-signals-2026-08-31/eo-amendment-chains/scan_eo_chains.py``.
Prints every number the README cites and writes ``receipt.json`` alongside
this script. The receipt records the sha256 and byte size of every input it
read, so a re-run against different inputs is visibly a different run.

Inputs (read, not modified -- a parallel lane owns promoting these into a
module; this script consumes their evidence as of 2026-08-31):

- ``research/evidence/investigations-2026-08-24/inv-eo/derived/eo-roster.csv``
  (EO numbers with the publisher's own ``title`` field, built from the
  Federal Register API's presidential-document listing plus NARA
  codification indexes).
- ``research/evidence/investigations-2026-08-24/inv-eo-gap/eo-gap.csv`` (the
  1990-1993 NARA-codification gap closure named in
  research/investigations-mined-2026-08-31.md silent item 5).
- ``research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl`` and the
  Unified Agenda ``legal_authorities`` parquet, as supplementary free-prose
  corpora.

WHY THIS SCRIPT WAS REWRITTEN (2026-08-31, after review)
--------------------------------------------------------
The first version searched a title for ONE leading verb phrase and applied it
to every Executive-Order number found after it. That is wrong in two
directions at once, and the roster contains specimens of both:

- it MISSES targets, because a plural head noun with a bare number list
  (``Executive Orders 12824, 12835, 12859, and 13532``) was not expanded, and
  because targets sitting before the matched ``Executive Order`` token were
  invisible (EO 13672's own first target, 11478);
- it MISLABELS relations, because a title can carry several verb clauses
  (EO 13716 revokes four orders AND amends a fifth; the old pass called the
  fifth a revocation).

This version segments the title into verb clauses and binds each number list
to the clause it actually sits in. Attribution is graded, and the grade is
carried on every edge rather than smoothed away:

``direct``
    The verb phrase immediately precedes the ``Executive Order(s)`` head noun
    (only whitespace between them). Highest confidence.
``coordinated``
    The mention is not itself verb-led, but it follows an already-attributed
    mention inside the same clause and the text immediately before it ends in
    a coordinator (``,`` / ``and`` / ``&`` / ``or``). This is the
    ``... Executive Order A, <A's own title>, and Executive Order B ...``
    shape (EO 13672) and the repeated-head-noun list shape (EO 13350). The
    inference is named so a reader can subtract it.
``unattributed``
    Anything else: a mention with no clause verb, or one separated from its
    clause verb by prose that re-governs it. The relation field is literally
    ``"unattributed"``. Specimens: EO 13350's ``Termination of Emergency
    Declared in Executive Order 12722`` (the object of "termination" is the
    emergency, not the order) and EO 13764's ``Amending the Civil Service
    Rules, Executive Order 13488, and Executive Order 13467`` (both targets
    are genuinely amended, and this parser refuses to say so from the title
    alone). Refusing here is the point: the brief asks for
    ``relation=unattributed`` over a guess.

The verb vocabulary is a curated closed list, printed into the receipt, so
what the parser can and cannot name is auditable rather than implied.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from refspec.registry.iri_minting import mint_executive_order_iri  # noqa: E402

ROSTER_PATH = (
    REPO_ROOT
    / "research/evidence/investigations-2026-08-24/inv-eo/derived/eo-roster.csv"
)
GAP_PATH = REPO_ROOT / "research/evidence/investigations-2026-08-24/inv-eo-gap/eo-gap.csv"
NOTES_PATH = REPO_ROOT / "research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl"
UA_LEGAL_AUTHORITIES_PARQUET = (
    REPO_ROOT
    / "output/registry-real-data-sources/unified-agenda-parquet/"
    "unified_agenda_legal_authorities.parquet"
)

# --- Title grammar -------------------------------------------------------
#
# A "mention" is one ``Executive Order(s) [No.] N[, N][, and N]`` span. The
# bare-number continuation is required: the plural head noun is written once
# and the rest of the list is bare digits ("Executive Orders 13038 and 13054",
# "Executive Orders 12824, 12835, 12859, and 13532").
MENTION = re.compile(
    r"Executive Orders?\s+(?:Nos?\.?\s*)?"
    r"(\d{4,5}(?:\s*(?:,|,?\s*and|,?\s*&)\s*(?:Nos?\.?\s*)?\d{4,5})*)",
    re.IGNORECASE,
)
NUMBER_IN_MENTION = re.compile(r"\d{4,5}")

# Curated, closed verb vocabulary. An optional degree modifier (Further /
# Partial / Additional / Initial) is captured as part of the verb so
# "Further Amendment to" and "Amendment to" stay distinct census rows.
VERB_PATTERN = re.compile(
    r"\b((?:Further|Partial|Additional|Initial)\s+)?"
    r"(Amendments?\s+(?:to|of)|Amending|Revocations?\s+of|Revoking|"
    r"Supersedure\s+of|Superseding|Rescissions?\s+of|Rescinding|"
    r"Terminations?\s+of|Terminating|Continuance\s+of|Continuing|"
    r"Reestablishment\s+Pursuant\s+to|Reestablishing|Reinstatement\s+of|"
    r"Reinstating|Suspensions?\s+of|Suspending|Modifications?\s+of|"
    r"Modifying|Clarifications?\s+of|Clarifying|Extensions?\s+of|Extending|"
    r"Exemption\s+From)\b",
    re.IGNORECASE,
)

# Only whitespace may separate a verb phrase from its head noun for the
# binding to count as ``direct``.
ONLY_SPACE = re.compile(r"^\s*$")
# The gap before a ``coordinated`` mention must end in a coordinator.
ENDS_IN_COORDINATOR = re.compile(r"(?:,|\band\b|&|\bor\b)[\s,]*$", re.IGNORECASE)

# Free-prose relation sentences (authority notes, agenda authority_text).
# Both voices, with the two endpoint numbers captured so hits collapse to
# distinct EDGES rather than being counted as distinct witnesses.
PROSE_PASSIVE = re.compile(
    r"Executive Order\s+(?:No\.?\s*)?(?P<target>\d{4,5})[^.;]{0,60}?"
    r"\b(?P<verb>as amended by|amended by|superseded by|revoked by|rescinded by)\b"
    r"[^.;]{0,60}?Executive Order\s+(?:No\.?\s*)?(?P<actor>\d{4,5})",
    re.IGNORECASE,
)
PROSE_ACTIVE = re.compile(
    r"Executive Order\s+(?:No\.?\s*)?(?P<actor>\d{4,5})[^.;]{0,60}?"
    r"\b(?P<verb>amending|superseding|revoking|rescinding)\b"
    r"[^.;]{0,60}?Executive Order\s+(?:No\.?\s*)?(?P<target>\d{4,5})",
    re.IGNORECASE,
)
PASSIVE_TO_RELATION = {
    "as amended by": "amends",
    "amended by": "amends",
    "superseded by": "supersedes",
    "revoked by": "revokes",
    "rescinded by": "rescinds",
}
ACTIVE_TO_RELATION = {
    "amending": "amends",
    "superseding": "supersedes",
    "revoking": "revokes",
    "rescinding": "rescinds",
}


def digest(path: Path) -> dict:
    """sha256 + size of one input, so the receipt binds what was read."""
    if not path.exists():
        return {"path": str(path.relative_to(REPO_ROOT)), "present": False}
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "present": True,
        "bytes": path.stat().st_size,
        "sha256": h.hexdigest(),
    }


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def normalize_verb(match: re.Match) -> str:
    modifier = (match.group(1) or "").strip()
    head = re.sub(r"\s+", " ", match.group(2)).strip()
    return re.sub(r"\s+", " ", f"{modifier} {head}").strip().lower()


def attribute_title(subject: str, title: str) -> list[dict]:
    """Bind every EO-number mention in one title to its own verb clause.

    Returns one record per (mention, target number) pair, each carrying its
    attribution grade and the exact text the grade was decided from.
    """
    verbs = list(VERB_PATTERN.finditer(title))
    records: list[dict] = []
    previous_attributed_end: int | None = None
    previous_verb: str | None = None
    previous_clause_start: int | None = None

    for mention in MENTION.finditer(title):
        numbers = NUMBER_IN_MENTION.findall(mention.group(1))
        targets = [n for n in dict.fromkeys(numbers) if n != subject]
        self_reference = [n for n in numbers if n == subject]

        # Governing clause: the last verb phrase that closes before this
        # mention opens.
        governing = None
        for v in verbs:
            if v.end() <= mention.start():
                governing = v
            else:
                break

        gap = title[governing.end() : mention.start()] if governing else None
        grade = "unattributed"
        verb = None
        basis = None

        if governing is not None and ONLY_SPACE.match(gap or ""):
            grade = "direct"
            verb = normalize_verb(governing)
            basis = "verb phrase immediately precedes the head noun"
        elif (
            governing is not None
            and previous_attributed_end is not None
            and previous_clause_start == governing.start()
            and previous_attributed_end <= mention.start()
            and ENDS_IN_COORDINATOR.search(title[previous_attributed_end : mention.start()])
        ):
            grade = "coordinated"
            verb = previous_verb
            basis = (
                "follows an attributed mention in the same clause, joined by a "
                "coordinator"
            )
        else:
            basis = (
                "no clause verb"
                if governing is None
                else f"clause verb separated by non-coordinating text: {gap!r}"
            )

        if grade in ("direct", "coordinated"):
            previous_attributed_end = mention.end()
            previous_verb = verb
            previous_clause_start = governing.start()

        for target in targets:
            records.append(
                {
                    "subject": subject,
                    "relation": verb if grade != "unattributed" else "unattributed",
                    "object": target,
                    "attribution": grade,
                    "attribution_basis": basis,
                    "mention_text": mention.group(0),
                    "clause_verb_text": governing.group(0) if governing else None,
                }
            )
        for _ in self_reference:
            records.append(
                {
                    "subject": subject,
                    "relation": "self-reference",
                    "object": subject,
                    "attribution": "self_reference_dropped",
                    "attribution_basis": "target number equals the subject",
                    "mention_text": mention.group(0),
                    "clause_verb_text": governing.group(0) if governing else None,
                }
            )
    return records


def parse_prose_edges(text: str) -> list[dict]:
    """Extract (actor, relation, target) triples from a free-prose sentence."""
    out = []
    for m in PROSE_PASSIVE.finditer(text):
        out.append(
            {
                "subject": m.group("actor"),
                "relation": PASSIVE_TO_RELATION[m.group("verb").lower()],
                "object": m.group("target"),
                "voice": "passive",
                "matched_span": m.group(0),
            }
        )
    for m in PROSE_ACTIVE.finditer(text):
        out.append(
            {
                "subject": m.group("actor"),
                "relation": ACTIVE_TO_RELATION[m.group("verb").lower()],
                "object": m.group("target"),
                "voice": "active",
                "matched_span": m.group(0),
            }
        )
    return out


def main() -> None:
    inputs = {
        "eo_roster_csv": digest(ROSTER_PATH),
        "eo_gap_csv": digest(GAP_PATH),
        "ecfr_authority_notes_jsonl": digest(NOTES_PATH),
        "unified_agenda_legal_authorities_parquet": digest(
            UA_LEGAL_AUTHORITIES_PARQUET
        ),
    }

    roster_rows = load_csv(ROSTER_PATH)
    gap_rows = load_csv(GAP_PATH)
    roster_numbers = {r["eo_number"] for r in roster_rows}
    gap_numbers = {r["eo_number"] for r in gap_rows}
    combined_numbers = roster_numbers | gap_numbers

    all_records: list[dict] = []
    titles_with_mention = 0
    fused_titles = []
    plural_head_titles = []
    multi_clause_titles = []

    for row in roster_rows:
        subject = row["eo_number"]
        title = row.get("title") or ""
        if not MENTION.search(title):
            continue
        titles_with_mention += 1

        if re.search(r"Executive Orders\s+(?:Nos?\.?\s*)?\d{4,5}", title, re.I):
            plural_head_titles.append({"eo_number": subject, "title": title})

        fm = re.search(r"Executive Order\s+(?:No\.?\s*)?(\d{4,5})([A-Za-z])", title)
        if fm:
            fused_titles.append(
                {
                    "eo_number": subject,
                    "title": title,
                    "target_number": fm.group(1),
                    "fused_next_char": fm.group(2),
                }
            )

        records = attribute_title(subject, title)
        clause_verbs = {
            r["clause_verb_text"] for r in records if r["clause_verb_text"]
        }
        if len(clause_verbs) >= 2:
            multi_clause_titles.append(
                {
                    "eo_number": subject,
                    "title": title,
                    "clause_verbs": sorted(clause_verbs),
                    "bindings": [
                        {
                            "object": r["object"],
                            "relation": r["relation"],
                            "attribution": r["attribution"],
                        }
                        for r in records
                    ],
                }
            )
        for r in records:
            r["witness_title"] = title
            r["witness_president"] = row.get("president")
            r["witness_signing_date"] = row.get("signing_date")
            r["witness_source"] = row.get("source")
            r["witness_source_url"] = row.get("source_url")
            r["witness_source_sha256"] = row.get("source_sha256")
        all_records.extend(records)

    self_refs = [r for r in all_records if r["attribution"] == "self_reference_dropped"]
    mentions = [r for r in all_records if r["attribution"] != "self_reference_dropped"]
    direct = [r for r in mentions if r["attribution"] == "direct"]
    coordinated = [r for r in mentions if r["attribution"] == "coordinated"]
    unattributed = [r for r in mentions if r["attribution"] == "unattributed"]
    attributed = direct + coordinated

    verb_counts: dict[str, int] = {}
    for r in attributed:
        verb_counts[r["relation"]] = verb_counts.get(r["relation"], 0) + 1

    unresolved_vs_roster = [r for r in mentions if r["object"] not in roster_numbers]
    unresolved_vs_combined = [r for r in mentions if r["object"] not in combined_numbers]

    # --- Supplementary corpora: free prose, not a document title. Counted as
    # distinct EDGES and, separately, as witnesses -- the same edge can be
    # stated in several notes (40 CFR 117 and 40 CFR 118 carry byte-identical
    # sentences about 11735/12777). ---
    note_witnesses = []
    if NOTES_PATH.exists():
        with NOTES_PATH.open() as fh:
            for line in fh:
                d = json.loads(line)
                note = d.get("authority_note") or ""
                for edge in parse_prose_edges(note):
                    note_witnesses.append(
                        {
                            "cfr_title": d["cfr_title"],
                            "cfr_part": d["cfr_part"],
                            "note": note,
                            **edge,
                        }
                    )

    ua_witnesses = []
    if UA_LEGAL_AUTHORITIES_PARQUET.exists():
        import pyarrow.parquet as pq

        t = pq.read_table(UA_LEGAL_AUTHORITIES_PARQUET, columns=["authority_text"])
        seen_text = set()
        for i in range(t.num_rows):
            v = t.column("authority_text")[i].as_py()
            if not v or "Executive Order" not in v or v in seen_text:
                continue
            edges = parse_prose_edges(v)
            if edges:
                seen_text.add(v)
                for edge in edges:
                    ua_witnesses.append({"authority_text": v, **edge})

    prose_witnesses = note_witnesses + ua_witnesses
    distinct_prose_edges = sorted(
        {(w["subject"], w["relation"], w["object"]) for w in prose_witnesses}
    )

    # Sketch (not build): mint both endpoints of real edges to show the shape
    # a promoted reader would emit -- including one unattributed mention, so
    # the refusal case has a shape too.
    sketch_source = [
        next(r for r in direct if r["subject"] == "13516"),
        next(r for r in direct if r["subject"] == "13716" and r["object"] == "13628"),
        next(r for r in coordinated if r["subject"] == "13672"),
        next(r for r in unattributed if r["subject"] == "13350"),
    ]
    sketch_edges = []
    for r in sketch_source:
        subj_iri = mint_executive_order_iri(r["subject"])
        obj_iri = mint_executive_order_iri(r["object"])
        sketch_edges.append(
            {
                "subject_iri": subj_iri.iri if subj_iri else None,
                "relation": r["relation"],
                "attribution": r["attribution"],
                "object_iri": obj_iri.iri if obj_iri else None,
                "object_resolution_evidence": {
                    "in_roster": r["object"] in roster_numbers,
                    "in_roster_plus_gap": r["object"] in combined_numbers,
                },
                "witness": {
                    "title": r["witness_title"],
                    "source": r["witness_source"],
                    "source_url": r["witness_source_url"],
                    "source_sha256": r["witness_source_sha256"],
                },
            }
        )

    receipt = {
        "inputs": inputs,
        "verb_vocabulary_regex": VERB_PATTERN.pattern,
        "mention_regex": MENTION.pattern,
        "attribution_grades": {
            "direct": "verb phrase immediately precedes the Executive Order(s) head noun",
            "coordinated": (
                "follows an attributed mention in the same clause, joined only by a "
                "coordinator"
            ),
            "unattributed": (
                "no clause verb, or clause verb separated by re-governing prose; "
                "relation is emitted as the literal string 'unattributed'"
            ),
        },
        "roster_size": len(roster_numbers),
        "gap_size": len(gap_numbers),
        "combined_roster_size": len(combined_numbers),
        "roster_titles_carrying_an_eo_number_mention": titles_with_mention,
        "target_mentions_total": len(mentions),
        "self_reference_mentions_dropped": len(self_refs),
        "edges_direct": len(direct),
        "edges_coordinated": len(coordinated),
        "mentions_unattributed": len(unattributed),
        "edges_attributed_total": len(attributed),
        "distinct_subject_eo_count": len({r["subject"] for r in attributed}),
        "distinct_object_eo_count": len({r["object"] for r in attributed}),
        "verb_census_attributed_only": verb_counts,
        "mentions_object_unresolved_vs_roster_only": len(unresolved_vs_roster),
        "mentions_object_unresolved_vs_roster_plus_gap": len(unresolved_vs_combined),
        "unresolved_after_combined": [
            {
                "subject": r["subject"],
                "object": r["object"],
                "relation": r["relation"],
                "attribution": r["attribution"],
                "title": r["witness_title"],
            }
            for r in unresolved_vs_combined
        ],
        "plural_head_titles_count": len(plural_head_titles),
        "plural_head_titles": plural_head_titles,
        "multi_clause_titles_count": len(multi_clause_titles),
        "multi_clause_titles": multi_clause_titles,
        "unattributed_specimens": [
            {
                "subject": r["subject"],
                "object": r["object"],
                "basis": r["attribution_basis"],
                "title": r["witness_title"],
            }
            for r in unattributed
        ],
        "fused_title_damage_count": len(fused_titles),
        "fused_titles": fused_titles,
        "sketch_edges": sketch_edges,
        "all_records": all_records,
        "prose_witness_count": len(prose_witnesses),
        "prose_distinct_edge_count": len(distinct_prose_edges),
        "prose_distinct_edges": [
            {"subject": s, "relation": v, "object": o} for s, v, o in distinct_prose_edges
        ],
        "prose_witnesses": prose_witnesses,
    }
    (OUT_DIR / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    print("=== EO RELATION CENSUS (per-target verb attribution) ===")
    print("Inputs (sha256-bound in receipt.json):")
    for key, meta in inputs.items():
        if meta.get("present"):
            print(f"  {key}: {meta['path']} ({meta['bytes']} bytes, {meta['sha256'][:16]}...)")
        else:
            print(f"  {key}: {meta['path']} ABSENT")
    print()
    print(f"Roster size (inv-eo derived): {len(roster_numbers)}")
    print(f"Gap-closure size (inv-eo-gap): {len(gap_numbers)}")
    print(f"Combined roster+gap size: {len(combined_numbers)}")
    print()
    print(f"Roster titles carrying >=1 EO-number mention: {titles_with_mention}")
    print(f"Target mentions (subject-excluded): {len(mentions)}")
    print(f"  self-reference mentions dropped: {len(self_refs)}")
    print(f"  attributed edges: {len(attributed)}  "
          f"(direct {len(direct)}, coordinated {len(coordinated)})")
    print(f"  unattributed mentions (relation='unattributed'): {len(unattributed)}")
    print(f"Distinct subject EOs (attributed): {len({r['subject'] for r in attributed})}")
    print(f"Distinct object EOs (attributed): {len({r['object'] for r in attributed})}")
    print()
    print("Verb census (attributed edges only):")
    for v, n in sorted(verb_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:3d}  {v}")
    print()
    print(f"Objects unresolved against roster alone: {len(unresolved_vs_roster)}")
    print(f"Objects STILL unresolved after adding the gap list: {len(unresolved_vs_combined)}")
    for u in receipt["unresolved_after_combined"]:
        print(f"    {u['subject']} --[{u['relation']}]--> {u['object']}")
    print()
    print(f"Plural-head titles ('Executive Orders N, N, and N'): {len(plural_head_titles)}")
    for p in plural_head_titles:
        print(f"    EO {p['eo_number']}: {p['title']}")
    print()
    print(f"Multi-clause titles (>=2 distinct clause verbs): {len(multi_clause_titles)}")
    for m in multi_clause_titles:
        print(f"    EO {m['eo_number']}: {m['clause_verbs']}")
        for b in m["bindings"]:
            print(f"        -> {b['object']}  {b['relation']}  [{b['attribution']}]")
    print()
    print(f"Unattributed mentions (parser refuses to name a relation): {len(unattributed)}")
    for u in receipt["unattributed_specimens"]:
        print(f"    EO {u['subject']} -> {u['object']}: {u['basis']}")
        print(f"        title: {u['title']}")
    print()
    print(f"Fused-title damage (number glued to the target's own title): {len(fused_titles)}")
    for f in fused_titles:
        print(f"    EO {f['eo_number']}: {f['title']!r}")
    print()
    print(
        f"Free-prose corpora: {len(prose_witnesses)} witnesses -> "
        f"{len(distinct_prose_edges)} DISTINCT edges"
    )
    for w in prose_witnesses:
        where = (
            f"{w['cfr_title']} CFR {w['cfr_part']}"
            if "cfr_title" in w
            else "unified-agenda authority_text"
        )
        print(f"    [{where}] {w['subject']} --[{w['relation']}]--> {w['object']}"
              f"  ({w['voice']})")
    print("  distinct edges:")
    for s, v, o in distinct_prose_edges:
        print(f"    {s} --[{v}]--> {o}")
    print()
    print("--- Sketch edges (minted endpoints; one per attribution grade) ---")
    for s in sketch_edges:
        print(f"  {s['subject_iri']} --[{s['relation']}]--> {s['object_iri']}"
              f"  [{s['attribution']}]")
        print(f"      object resolution evidence: {s['object_resolution_evidence']}")
        print(f"      witness: {s['witness']['title']!r} "
              f"[{s['witness']['source']} sha256={s['witness']['source_sha256'][:16]}...]")


if __name__ == "__main__":
    main()

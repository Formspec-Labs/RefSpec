"""Assemble the agency registry's succession batch and its owner adjudication sheet (candidates, never assertions).

Batch 1 (plans/agency-registry-design.md, REF-072) is decided and released, and
that release pins its candidate and decision files by digest, so a succession
found since goes into a batch of its own. This batch holds dated change events
between Federal Register roster records, built exactly as batch 1 builds its
events: the same types, ids, rows and ``content_digest``. Each event must rest on
a dated public record of a kind the release admits (``DATED_PUBLIC_RECORD_KINDS``),
and an event batch 1 already proposes is refused here.

Every row is ``candidate-pending-owner-adjudication`` and carries no reviewer,
evidence tier or decision. The owner (``urn:ref:reviewer:refspec-owner``) answers
in plans/agency-registry-succession-batch-decisions.json, which this tool only
reads, through the decision contract the batch-1 release reads
(``load_decisions``). The candidates follow from the pinned rosters alone, so
``--check`` re-derives the JSON and the sheet byte for byte without a replay.
What a decided event does to spicy-regs' codes is not measured here; the owner
note states what its rule implies.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.atlas import v3_registry_alignments_entity as entity_alignments

try:
    from tools import analyze_agency_roster_identifiers as census
    from tools import assemble_agency_registry_batch_1 as batch1
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_agency_roster_identifiers as census
    import assemble_agency_registry_batch_1 as batch1

PublicRecord = batch1.PublicRecord
Rejected = batch1.Rejected
SuccessionEvent = batch1.SuccessionEvent
SuccessorRow = batch1.SuccessorRow

SCHEMA_VERSION = "refspec-agency-registry-succession-batch-candidates/1"
REPORT_JSON = Path("plans/agency-registry-succession-batch-candidates.json")
ADJUDICATION_MARKDOWN = Path("plans/agency-registry-succession-batch-adjudication.md")
DECISIONS_JSON = Path("plans/agency-registry-succession-batch-decisions.json")
EVIDENCE_MANIFEST = Path("research/evidence/fns-fna-succession-2026-10-03/manifest.json")
CANDIDATES_DIGEST_COVERS = entity_alignments.CANDIDATES_DIGEST_COVERS

# Verified against the publishers on 2026-10-03; the bytes are retained under
# research/evidence/fns-fna-succession-2026-10-03/ (manifest.json names each URL).
FR_2026_12700 = PublicRecord(
    "frDocument",
    (
        "91 FR 37779 (2026-06-24), FR Doc 2026-12700, Special Supplemental Nutrition Program for Women, "
        "Infants, and Children (WIC): Revisions in the WIC Food Packages; Delay of Vitamin D in Yogurt "
        "Implementation Date and Technical Corrections"
    ),
    (
        "https://www.federalregister.gov/documents/2026/06/24/2026-12700/special-supplemental-nutrition-program-"
        "for-women-infants-and-children-wic-revisions-in-the-wic-food"
    ),
    (
        "Amendment 1, 'Under the authority of the Reorganization Plan No. 2 of 1953 (5 U.S.C. app.; 7 U.S.C. "
        "2201 note) and the Department of Agriculture Reorganization Act of 1994 (Pub. L. 103-354)', revises the "
        "heading of 7 CFR chapter II to 'FOOD AND NUTRITION ADMINISTRATION, DEPARTMENT OF AGRICULTURE'; 'This "
        "rule is effective on June 24, 2026.' It continues FNS's rulemaking under the same docket and RIN as the "
        "2024 rule FNS published (FNS-2022-0007, RIN 0584-AE82; 89 FR 28488, FR Doc 2024-07437), and calls that "
        "rule's author the Food and Nutrition Administration."
    ),
)
FR_2026_11917 = PublicRecord(
    "frDocument",
    (
        "91 FR 35951 (2026-06-15), FR Doc 2026-11917, Agency Information Collection Activities: Proposed "
        "Collection: Comment Request-EmpowHR/Person Model Non-Employee Data Sheet-FNA-775"
    ),
    (
        "https://www.federalregister.gov/documents/2026/06/15/2026-11917/agency-information-collection-"
        "activities-proposed-collection-comment-request-empowhrperson-model"
    ),
    (
        "The Register's first document under FR 625 ('AGENCY: Food and Nutrition Administration (FNA), USDA'); "
        "its form keeps FNS's OMB number 0584-0686. The Register's last document under FR 200 is FR Doc "
        "2026-10828 (91 FR 32372, 2026-06-01)."
    ),
)
FR_ROSTER_625 = PublicRecord(
    "publisherRoster",
    "Federal Register agency roster record 625, Food and Nutrition Administration",
    "https://www.federalregister.gov/agencies/food-and-nutrition-administration",
    (
        "Parent 12 (Agriculture Department), short name FNA, agency_url "
        "https://www.fns.usda.gov/about/reorganization, where USDA states that 'the Food and Nutrition Service "
        "and the Food, Nutrition, and Consumer Services mission area are now the Food and Nutrition "
        "Administration'. Its description takes over FR 200's ('administers the USDA food assistance programs')."
    ),
)

SUCCESSION_EVENTS = (
    SuccessionEvent(
        (200,),
        "2026-06-24",
        (
            "the effective date of 91 FR 37779's revision of the 7 CFR chapter II heading, the one public record "
            "in hand that puts the new name into effect; eCFR's point-in-time API heads chapter II 'Food and "
            "Nutrition Service' on 2026-06-23 and 'Food and Nutrition Administration' on 2026-06-24. USDA's own "
            "instrument, which the agency page names as the reorganization plan SM 1078-015, refused the "
            "fetch (HTTP 403) and was not read"
        ),
        (
            SuccessorRow(
                625,
                None,
                (FR_2026_12700, FR_2026_11917, FR_ROSTER_625),
                (
                    "USDA renamed the Food and Nutrition Service the Food and Nutrition Administration: the CFR "
                    "heading of its chapter changed on 2026-06-24, the Register filed nothing under FR 200 after "
                    "2026-06-01 and has filed under FR 625 since 2026-06-15, and the new name carries on the old "
                    "one's rulemaking (RIN 0584-AE82, docket FNS-2022-0007) and OMB numbers (0584-)."
                ),
                Rejected(
                    "Food and Nutrition Service sameEntityAs Food and Nutrition Administration, folded into identity.",
                    (
                        "The Register keeps two records and files documents under each name on either side of "
                        "June 2026; identity would erase the date and file every earlier FNS document under a "
                        "name that did not yet exist."
                    ),
                ),
            ),
        ),
        date_alternatives=(
            (
                "2026-06-15",
                (
                    "the Register's first document under FR 625, FR Doc 2026-11917; a filing date, not a stated "
                    "effective date"
                ),
            ),
            (
                "2026-04-30",
                (
                    "USDA's announcement of 'its intention to introduce the Food and Nutrition Administration' "
                    "(press release 0062.26, https://www.fns.usda.gov/newsroom/usda-0062.26); an intention, not a "
                    "dated record of effect"
                ),
            ),
        ),
        owner_note=(
            "The periods are not disjoint: the Register filed FNA documents from 2026-06-15, nine days before "
            "the CFR heading changed. USDA says the Food and Nutrition Service and the Food, Nutrition, and "
            "Consumer Services mission area became FNA; the mission area has no record in any held roster, so "
            "FNS is the only original. Two publishers disagree with the Register: regulations.gov's roster "
            "(2026-08-16) files FNA under parent DOI, and eCFR's agency roster (2026-08-15) still names chapter "
            "II's agency Food and Nutrition Service. The cost under spicy-regs' rule (ontology/agencies.py "
            "_build_projection at d2b5f53, not measured here): an original takes every code its current "
            "successors carry, and FR 200 already carries FNS, so it would carry FNS and FNA and resolve to no "
            "code -- FR documents naming only FNS would lose their code unless spicy-regs lets a coded original "
            "keep its own."
        ),
    ),
)


def _batch1_originals(root: Path) -> set[int]:
    """The FR ids batch 1 already proposes as event originals; its decided events are not re-proposed here."""

    report = json.loads((root / batch1.REPORT_JSON).read_text())
    return {original["id"] for event in report["events"] for original in event["originals"]}


def assemble(root: Path, releases: Sequence[Any] | None = None) -> dict[str, Any]:
    """The batch's report: event rows and events from the pinned rosters, and the digests that bind decisions."""

    releases = census.load_five_agency_rosters(root) if releases is None else releases
    rows, events = batch1._succession_candidates(batch1._rosters(releases), SUCCESSION_EVENTS)
    decided = _batch1_originals(root)
    for event in events:
        originals = {original["id"] for original in event["originals"]}
        batch1._require(not originals & decided, f"{event['event_id']} is batch 1's to decide")
        batch1._require(
            any(record["kind"] in entity_alignments.DATED_PUBLIC_RECORD_KINDS for record in event["public_records"]),
            f"{event['event_id']} rests on no dated public record the release admits",
        )
    fr_key = batch1.FR
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": batch1.CANDIDATE_STATUS,
        "owner_reviewer_iri": batch1.OWNER_REVIEWER_IRI,
        "inputs": {
            "roster_releases": {release.key: release.source_release_digest for release in releases if release.key == fr_key},
            "evidence_manifest": {
                "path": str(EVIDENCE_MANIFEST),
                "sha256": batch1._file_digest(root / EVIDENCE_MANIFEST),
            },
        },
        "candidates": rows,
        "events": events,
        "non_emissions": [],
        "no_fr_bridge": [],
        "candidates_digest_covers": list(CANDIDATES_DIGEST_COVERS),
    }
    report["candidates_digest"] = batch1._digest({key: report[key] for key in CANDIDATES_DIGEST_COVERS})
    report["digest"] = batch1._digest(report)
    return report


def render_adjudication_sheet(report: Mapping[str, Any], decisions: entity_alignments.Decisions) -> str:
    """The owner's sheet, generated from the JSON and the decisions file; it adjudicates nothing."""

    rows = {row["candidate_id"]: row for row in report["candidates"]}
    answers = entity_alignments.decision_answers(report)
    digests = entity_alignments.decision_digests(report)
    undecided = len(set(answers) - set(decisions.current))
    lines = [
        "<!-- markdownlint-disable MD013 -->",
        "",
        "# Agency registry succession batch — owner adjudication sheet",
        "",
        (
            "Generated from [agency-registry-succession-batch-candidates.json]"
            "(agency-registry-succession-batch-candidates.json) and [agency-registry-succession-batch-decisions.json]"
            "(agency-registry-succession-batch-decisions.json) by `tools/assemble_agency_registry_succession_batch.py`; "
            "`--check` fails if this sheet disagrees with either. **Do not edit this sheet.** You (reviewer "
            f"`{report['owner_reviewer_iri']}`) answer through the question tool or by editing the decisions file, "
            "exactly as for batch 1: each decision is keyed by the event id and records the answer, the date, the "
            "channel and the event's `content_digest` (the Decision keys table). Every row is still "
            "`candidate-pending-owner-adjudication`; an accepted event becomes an assertion carrying your reviewer "
            "IRI and the decision date. Batch 1's release cannot take these: a release of its own needs the release "
            "step generalized beyond batch 1's pinned files, and REF-072's known limit (events cannot stand alone in "
            "a mapping release) lifted or a bridge to ride with."
        ),
        "",
        (
            f"Decisions recorded: {len(decisions.current)} current, {len(decisions.stale)} stale, "
            f"{undecided} of {len(answers)} decidable items undecided. Candidates digest "
            f"`{report['candidates_digest']}`; evidence `{report['inputs']['evidence_manifest']['path']}` "
            f"(`{report['inputs']['evidence_manifest']['sha256']}`)."
        ),
        "",
    ]
    for event in report["events"]:
        row = rows[event["rows"][0]]
        lines.extend(
            [
                f"## `{event['event_id']}`: did {batch1._originals(event)} become {batch1._named(row['target'])}?",
                "",
                f"Answers: {' / '.join(f'`{answer}`' for answer in answers[event['event_id']])} (`wrong-date` with a note naming the date).",
                "",
                *batch1._table(
                    ("Field", "Value"),
                    (
                        ("Row", f"`{row['candidate_id']}`"),
                        ("Original", f"{batch1._named(row['source'])}, parent {batch1._parent(row['source'])}"),
                        ("Result", f"{batch1._named(row['target'])}, parent {batch1._parent(row['target'])}"),
                        ("Proposed date", batch1._date_text(event)),
                        ("Reasoning", row["reasoning"]),
                        ("Closest rejected alternative", f"{row['closest_rejected_alternative']['description']} Rejected: {row['closest_rejected_alternative']['why_rejected']}"),
                        ("Owner note", event["owner_note"]),
                        ("Owner decision / date", batch1._decision_cell(decisions, event["event_id"])),
                    ),
                ),
                "",
                *batch1._table(
                    ("Record", "Kind", "What it says"),
                    ((f"[{record['citation']}]({record['url']})", f"`{record['kind']}`", record["note"]) for record in event["public_records"]),
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Decision keys",
            "",
            *batch1._table(
                ("Id", "Answers", "Content digest"),
                ((f"`{key}`", " / ".join(f"`{answer}`" for answer in offered), f"`{digests[key]}`") for key, offered in answers.items()),
            ),
            "",
        ]
    )
    if decisions.stale:
        lines.extend(
            [
                "## Stale decisions",
                "",
                *batch1._table(
                    ("Id", "Answer", "Decided on", "Decided on content digest", "Content digest now"),
                    (
                        (f"`{key}`", decision["answer"], decision["decided_on"], f"`{decision['content_digest']}`", f"`{digests[key]}`")
                        for key, decision in decisions.stale.items()
                    ),
                ),
                "",
            ]
        )
    return "\n".join(lines)


def _outputs(report: Mapping[str, Any], decisions: entity_alignments.Decisions) -> dict[Path, bytes]:
    return {
        REPORT_JSON: batch1._canonical_json_bytes(report) + b"\n",
        ADJUDICATION_MARKDOWN: render_adjudication_sheet(report, decisions).encode("utf-8"),
    }


def write_or_check(root: Path, *, write: bool, releases: Sequence[Any] | None = None) -> list[str]:
    """Write the generated plans/ artifacts, or return the ones missing or drifted; the decisions file is only read."""

    report = assemble(root, releases)
    decisions = entity_alignments.load_decisions(root / DECISIONS_JSON, report)
    problems = []
    for relative, payload in _outputs(report, decisions).items():
        path = root / relative
        if write:
            path.write_bytes(payload)
        elif not path.is_file() or path.read_bytes() != payload:
            problems.append(f"{'drifted' if path.is_file() else 'missing'}: {relative}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the generated plans/ artifacts (default: check them)")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = write_or_check(args.repo_root.resolve(), write=args.write)
    if problems:
        raise SystemExit("succession batch artifacts out of date: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

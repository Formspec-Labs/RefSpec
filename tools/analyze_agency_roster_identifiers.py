"""Measure identifiers, then layer owner adjudication over the 52-value residue.

The first pass compares publisher identifier strings exactly. It never reads a
label for matching, normalizes a name, or computes name similarity. The second
pass reports the separate, per-value E4 decisions carried by the asserted
agency identity mapping release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.atlas import agency_projection, v3_registry_nonemitters, v3_registry_rosters
from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from refspec.atlas.v3_source_data import RegistryRelease

REPORT_DATE = "2026-08-16"
REPORT_DIRECTORY = Path("research/evidence/agency-identifier-census-2026-08-16")
REPORT_JSON = REPORT_DIRECTORY / "census.json"
REPORT_MARKDOWN = REPORT_DIRECTORY / "README.md"
ROSTER_ORDER = agency_projection.AGENCY_ROSTER_ORDER
EXPECTED_ROSTER_COUNTS = agency_projection.EXPECTED_AGENCY_ROSTER_COUNTS
KIND_TO_ROSTER = agency_projection.IDENTIFIER_KIND_TO_ROSTER
KIND_ORDER = agency_projection.IDENTIFIER_KIND_ORDER
ADMISSIBLE_ACRONYM_PAIRS = agency_projection.ADMISSIBLE_ACRONYM_PAIRS
_FR_KEY = agency_projection.FR_RELEASE_KEY
_FH_KEY = agency_projection.FH_RELEASE_KEY
_OPM_KEY = agency_projection.OPM_RELEASE_KEY
_ECFR_KEY = agency_projection.ECFR_RELEASE_KEY
_REGS_KEY = agency_projection.REGULATIONS_GOV_RELEASE_KEY
extract_identifier_claims = agency_projection.extract_agency_identifier_claims

# REF-038 admits exact equality only across publisher-minted acronyms, and
# records each resulting identity claim as E4 adjudication. Everything else
# remains a string coincidence between different identifier authorities.


def _canonical_json_bytes(value: Any) -> bytes:
    value = _json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_json_value(child) for child in value]
    return value


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def load_five_agency_rosters(repo_root: Path) -> tuple[RegistryRelease, ...]:
    """Load exactly the five releases in the REF-038 census."""

    roster_releases = v3_registry_rosters.load_registry_roster_releases(
        repo_root,
        only_keys={_FR_KEY, _FH_KEY, _ECFR_KEY, _REGS_KEY},
    )
    opm_release = v3_registry_nonemitters.load_registry_nonemitter_releases(
        repo_root,
        only_keys={_OPM_KEY},
    )
    by_key = {release.key: release for release in (*roster_releases, *opm_release)}
    required = (_FR_KEY, _FH_KEY, _OPM_KEY, _ECFR_KEY, _REGS_KEY)
    if set(by_key) != set(required):
        raise ValueError(
            "five-roster census release set drifted: "
            f"expected {sorted(required)!r}, got {sorted(by_key)!r}"
        )
    return tuple(by_key[key] for key in required)


def _kind_census(
    releases: Sequence[RegistryRelease],
    claims: Mapping[str, Mapping[str, set[str]]],
) -> list[dict[str, Any]]:
    resources_by_roster = {
        roster: len(release.resources)
        for roster, release in zip(ROSTER_ORDER, releases, strict=True)
    }
    rows: list[dict[str, Any]] = []
    for kind in KIND_ORDER:
        roster = KIND_TO_ROSTER[kind]
        values = claims[kind]
        resource_ids = {resource for members in values.values() for resource in members}
        collision_values = {
            value: sorted(members)
            for value, members in values.items()
            if len(members) > 1
        }
        rows.append(
            {
                "roster": roster,
                "identifierKind": kind,
                "rosterResourceCount": resources_by_roster[roster],
                "resourceCountWithValue": len(resource_ids),
                "claimCount": sum(len(members) for members in values.values()),
                "distinctValueCount": len(values),
                "collisionValueCount": len(collision_values),
                "maxResourcesPerValue": max((len(members) for members in values.values()), default=0),
                "collisions": [
                    {"value": value, "resources": members}
                    for value, members in sorted(collision_values.items())
                ],
            }
        )
    return rows


def _cross_roster_equality(
    claims: Mapping[str, Mapping[str, set[str]]],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for left_index, left_kind in enumerate(KIND_ORDER):
        for right_kind in KIND_ORDER[left_index + 1 :]:
            if KIND_TO_ROSTER[left_kind] == KIND_TO_ROSTER[right_kind]:
                continue
            shared_values = sorted(set(claims[left_kind]) & set(claims[right_kind]))
            if not shared_values:
                continue
            pair = frozenset({left_kind, right_kind})
            admissible = pair in ADMISSIBLE_ACRONYM_PAIRS
            matches = []
            for value in shared_values:
                left_resources = sorted(claims[left_kind][value])
                right_resources = sorted(claims[right_kind][value])
                matches.append(
                    {
                        "value": value,
                        "leftResources": left_resources,
                        "rightResources": right_resources,
                        "edgeCount": len(left_resources) * len(right_resources),
                        "ambiguous": len(left_resources) != 1 or len(right_resources) != 1,
                    }
                )
            comparisons.append(
                {
                    "leftRoster": KIND_TO_ROSTER[left_kind],
                    "leftKind": left_kind,
                    "rightRoster": KIND_TO_ROSTER[right_kind],
                    "rightKind": right_kind,
                    "disposition": (
                        "admissibleE4AcronymAdjudication"
                        if admissible
                        else "refusedDifferentIdentifierAuthorities"
                    ),
                    "sharedValueCount": len(matches),
                    "candidateEdgeCount": sum(match["edgeCount"] for match in matches),
                    "unambiguousValueCount": sum(not match["ambiguous"] for match in matches),
                    "ambiguousValueCount": sum(match["ambiguous"] for match in matches),
                    "matches": matches,
                }
            )
    return comparisons


def _regulations_gov_coverage(
    comparisons: Sequence[Mapping[str, Any]],
    claims: Mapping[str, Mapping[str, set[str]]],
) -> dict[str, Any]:
    regs_values = set(claims["regulationsGovAgencyId"])
    paths_by_value: dict[str, list[dict[str, str]]] = defaultdict(list)
    ambiguous_by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comparison in comparisons:
        if comparison["disposition"] != "admissibleE4AcronymAdjudication":
            continue
        if "regulationsGovAgencyId" not in {
            comparison["leftKind"],
            comparison["rightKind"],
        }:
            continue
        other_kind = (
            comparison["rightKind"]
            if comparison["leftKind"] == "regulationsGovAgencyId"
            else comparison["leftKind"]
        )
        other_roster = KIND_TO_ROSTER[other_kind]
        for match in comparison["matches"]:
            value = match["value"]
            if match["ambiguous"]:
                ambiguous_by_value[value].append(
                    {
                        "identifierKind": other_kind,
                        "roster": other_roster,
                        "leftResources": match["leftResources"],
                        "rightResources": match["rightResources"],
                    }
                )
                continue
            paths_by_value[value].append(
                {
                    "identifierKind": other_kind,
                    "roster": other_roster,
                    "basis": "exactPublisherAcronymEquality",
                }
            )
    resolved_values = sorted(paths_by_value)
    abstention_values = sorted(regs_values - set(paths_by_value))
    return {
        "sourceValueKind": "regulationsGovAgencyId",
        "totalValueCount": len(regs_values),
        "resolvedValueCount": len(resolved_values),
        "abstentionValueCount": len(abstention_values),
        "coverageRatio": f"{len(resolved_values)}/{len(regs_values)}",
        "resolvedValues": [
            {"value": value, "identifierPaths": paths_by_value[value]}
            for value in resolved_values
        ],
        "abstentions": [
            {
                "value": value,
                "reason": (
                    "ambiguousAcronymEquality"
                    if value in ambiguous_by_value
                    else "noAdmissibleIdentifierEquality"
                ),
                "ambiguousCandidates": ambiguous_by_value.get(value, []),
            }
            for value in abstention_values
        ],
    }


def _release_census_row(roster: str, release: RegistryRelease) -> dict[str, Any]:
    parent_relations = [
        relation
        for relation in release.relations
        if relation.predicate == v3_registry_rosters.ATLAS_PARENT_ENTITY
    ]
    return {
        "roster": roster,
        "releaseKey": release.key,
        "resourceCount": len(release.resources),
        "relationCount": len(release.relations),
        "parentRelationCount": len(parent_relations),
        "distinctParentResourceCount": len(
            {relation.object for relation in parent_relations}
        ),
        "otherRelationCount": len(release.relations) - len(parent_relations),
        "crossRingRelationCount": len(release.cross_ring_relations),
        "sourceReleaseDigest": release.source_release_digest,
        "inputPins": [
            {
                "logicalPath": pin.logical_path,
                "sha256": pin.sha256,
                "byteLength": pin.byte_length,
                "sourceIri": pin.source_iri,
            }
            for pin in release.inputs
        ],
    }


def build_census(releases: Sequence[RegistryRelease]) -> dict[str, Any]:
    """Build the unchanged census and a separate residue-adjudication layer."""

    if tuple(len(release.resources) for release in releases) != tuple(
        EXPECTED_ROSTER_COUNTS[roster] for roster in ROSTER_ORDER
    ):
        raise ValueError("five-roster resource counts drifted from the REF-038 evidence base")
    claims = extract_identifier_claims(releases)
    comparisons = _cross_roster_equality(claims)
    report: dict[str, Any] = {
        "schemaVersion": "refspec-agency-identifier-census/1",
        "censusDate": REPORT_DATE,
        "method": {
            "comparison": "Unicode code-point exact equality; no normalization",
            "nameSimilarityUsed": False,
            "admissionRule": (
                "Only exact equality across publisher-minted acronym fields is "
                "admissible, and only as REF-035 E4 adjudication."
            ),
            "otherEqualityRule": (
                "Equal strings from different identifier authorities are counted "
                "and refused; equality alone does not merge their entities."
            ),
        },
        "releases": [
            _release_census_row(roster, release)
            for roster, release in zip(ROSTER_ORDER, releases, strict=True)
        ],
        "identifierKinds": _kind_census(releases, claims),
        "identifierEqualityComparisons": comparisons,
        "regulationsGovCoverage": _regulations_gov_coverage(comparisons, claims),
    }
    report["censusDigest"] = _digest(report)
    identity_release = (
        entity_alignments.load_regulations_gov_agency_identity_mapping_release(
            releases
        )
    )
    residue_values = {
        row.source_value
        for row in (
            *entity_alignments.RESIDUE_ADOPTIONS,
            *entity_alignments.RESIDUE_ABSTENTIONS,
        )
    }
    decisions = [
        dict(row)
        for row in identity_release.metadata["candidateDecisions"]
        if row["sourceValue"] in residue_values
    ]
    adjudication: dict[str, Any] = {
        "label": "secondPassPerValueAdjudication",
        "mappingReleaseKey": identity_release.key,
        "mappingPredicate": entity_alignments.ATLAS_SAME_ENTITY_AS,
        "startingResolvedValueCount": report["regulationsGovCoverage"][
            "resolvedValueCount"
        ],
        "residueValueCount": len(decisions),
        "adoptedResidueValueCount": sum(
            row["decision"] == "adopted" for row in decisions
        ),
        "abstainedResidueValueCount": sum(
            row["decision"] == "abstained" for row in decisions
        ),
        "finalResolvedValueCount": len(identity_release.mappings),
        "finalAbstainedValueCount": identity_release.metadata["abstentionCount"],
        "mappingEvidenceRecordCount": identity_release.metadata[
            "evidenceRecordCount"
        ],
        "reviewerIri": (
            entity_alignments.REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI
        ),
        "decidedAt": (
            entity_alignments.REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT
        ),
        "decisions": decisions,
    }
    adjudication["adjudicationDigest"] = _digest(adjudication)
    report["agencyIdentityAdjudication"] = adjudication
    return report


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the compact, reviewable form of the full JSON census."""

    coverage = report["regulationsGovCoverage"]
    adjudication = report["agencyIdentityAdjudication"]
    lines = [
        "# Agency identifier census — 2026-08-16",
        "",
        (
            "REF-038 first measures exact publisher-identifier equality across five agency "
            "rosters without name similarity or identifier normalization. It then layers "
            "per-value E4 review over the 52-value residue. The adjacent `census.json` "
            "contains both passes."
        ),
        "",
        "## Roster and identifier census",
        "",
    ]
    lines.extend(
        _markdown_table(
            (
                "Roster",
                "Resources",
                "Relations",
                "Parent relations",
                "Distinct parents",
                "Other relations",
                "Cross-ring",
            ),
            (
                (
                    row["roster"],
                    row["resourceCount"],
                    row["relationCount"],
                    row["parentRelationCount"],
                    row["distinctParentResourceCount"],
                    row["otherRelationCount"],
                    row["crossRingRelationCount"],
                )
                for row in report["releases"]
            ),
        )
    )
    lines.extend(["", "### Identifier kinds", ""])
    lines.extend(
        _markdown_table(
            (
                "Roster",
                "Identifier kind",
                "Resources",
                "Claims",
                "Distinct",
                "Collision values",
            ),
            (
                (
                    row["roster"],
                    row["identifierKind"],
                    row["rosterResourceCount"],
                    row["claimCount"],
                    row["distinctValueCount"],
                    row["collisionValueCount"],
                )
                for row in report["identifierKinds"]
            ),
        )
    )
    lines.extend(["", "## Cross-roster exact equality", ""])
    lines.extend(
        _markdown_table(
            (
                "Left kind",
                "Right kind",
                "Disposition",
                "Shared values",
                "Edges",
                "Unambiguous",
                "Ambiguous",
            ),
            (
                (
                    row["leftKind"],
                    row["rightKind"],
                    row["disposition"],
                    row["sharedValueCount"],
                    row["candidateEdgeCount"],
                    row["unambiguousValueCount"],
                    row["ambiguousValueCount"],
                )
                for row in report["identifierEqualityComparisons"]
            ),
        )
    )
    lines.extend(["", "### Ambiguities", ""])
    for comparison in report["identifierEqualityComparisons"]:
        ambiguous = [match for match in comparison["matches"] if match["ambiguous"]]
        if not ambiguous:
            continue
        lines.append(
            f"- `{comparison['leftKind']}` = `{comparison['rightKind']}`: "
            + ", ".join(
                f"`{match['value']}` ({len(match['leftResources'])}×{len(match['rightResources'])})"
                for match in ambiguous
            )
        )
    lines.extend(
        [
            "",
            "## regulations.gov first-pass coverage and residue",
            "",
            f"- Total agency ids: {coverage['totalValueCount']}",
            f"- At least one unambiguous admitted identifier path: {coverage['resolvedValueCount']}",
            f"- Values requiring per-value review: {coverage['abstentionValueCount']}",
            "- Residue values: "
            + ", ".join(f"`{row['value']}`" for row in coverage["abstentions"]),
            "",
            (
                "An equality marked `admissibleE4AcronymAdjudication` is evidence input, "
                "not a publisher assertion. REF-038 requires the asserted mapping release "
                "to retain the E4 tier, adjudication warrant, basis, and source records. "
                "All other equal strings remain refused coincidences between different "
                "identifier authorities."
            ),
            "",
            (
                "The identifier census above is unchanged. The next section is a "
                "second pass over its 52-value residue and does not alter the exact-equality measurements."
            ),
            "",
            "## Per-value residue adjudication",
            "",
            (
                f"The owner ruling adopts {adjudication['adoptedResidueValueCount']} "
                f"obvious identities and abstains on {adjudication['abstainedResidueValueCount']} "
                "values for which no held roster contains the same entity. The final "
                f"split is {adjudication['finalResolvedValueCount']} resolved and "
                f"{adjudication['finalAbstainedValueCount']} abstained."
            ),
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            (
                "regulations.gov id",
                "Publisher name",
                "Decision",
                "Basis or reason",
                "Counterpart",
            ),
            (
                (
                    row["sourceValue"],
                    row["sourcePublisherName"],
                    row["decision"],
                    row.get("basis", row.get("reason", "")),
                    (
                        f"{row['objectPublisherName']} (`{row['objectResource']}`)"
                        if row["decision"] == "adopted"
                        else (
                            f"ABSTAIN; closest: {row['closestNonAdoptedCandidate']['publisherName']} "
                            f"(`{row['closestNonAdoptedCandidate']['resource']}`)"
                            if "closestNonAdoptedCandidate" in row
                            else "ABSTAIN; no candidate"
                        )
                    ),
                )
                for row in adjudication["decisions"]
            ),
        )
    )
    lines.extend(
        [
            "",
            (
                "Each adoption records both publisher names, its closed-vocabulary basis, "
                "reviewer, decision time, and a specific reasoning sentence in `census.json` "
                "and the mapping release. Abstentions use `noCounterpartInHeldRosters` and "
                "record the closest rejected candidate when one exists."
            ),
            "",
            f"Identifier census digest: `{report['censusDigest']}`",
            f"Adjudication digest: `{adjudication['adjudicationDigest']}`",
            "",
            "Reproduce with `uv run python tools/analyze_agency_roster_identifiers.py --check`.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_or_check(repo_root: Path, report: Mapping[str, Any], *, write: bool) -> None:
    json_payload = _canonical_json_bytes(report) + b"\n"
    markdown_payload = render_markdown(report).encode("utf-8")
    targets = {
        repo_root / REPORT_JSON: json_payload,
        repo_root / REPORT_MARKDOWN: markdown_payload,
    }
    if write:
        (repo_root / REPORT_DIRECTORY).mkdir(parents=True, exist_ok=True)
        for path, payload in targets.items():
            path.write_bytes(payload)
        return
    for path, payload in targets.items():
        if not path.is_file():
            raise SystemExit(f"missing checked agency census artifact: {path}")
        if path.read_bytes() != payload:
            raise SystemExit(f"agency census artifact drifted: {path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the dated evidence artifact")
    mode.add_argument("--check", action="store_true", help="verify the checked evidence artifact")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    report = build_census(load_five_agency_rosters(root))
    if args.write or args.check:
        _write_or_check(root, report, write=args.write)
    else:
        print(_canonical_json_bytes(report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

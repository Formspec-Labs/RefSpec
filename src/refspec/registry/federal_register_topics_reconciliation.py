"""Unresolved reconciliation proof for two Federal Register topic sources.

The 1995 thesaurus and a captured ``/api/v1/topics.json`` response are exact
source artifacts, but neither comparison labels nor API slugs establish
cross-source concept identity.  This module records the observed differences
as a RefSpec ``RegistryReconciliationReport`` whose only valid outcome is
``unresolved``.

The API source-record identifier deliberately uses only the exact capture
digest, collection, and zero-based source ordinal.  Names and slugs remain
evidence fields and can never become identifiers through this module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from refspec import binding
from refspec.registry.federal_register_thesaurus import (
    FEDERAL_REGISTER_THESAURUS_1995_URL,
    FederalRegisterThesaurus,
    parse_federal_register_thesaurus,
)
from refspec.registry.federal_register_topics_api import (
    FEDERAL_REGISTER_TOPICS_API_URL,
    FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
    FederalRegisterTopicRecord,
    FederalRegisterTopicsComparison,
    FederalRegisterTopicsSnapshot,
    compare_historical_thesaurus_to_topics,
    open_federal_register_topics_capture,
)
from refspec.storage import canonical_json
from refspec.vocabulary import RegistryReconciliationReport

HISTORICAL_SOURCE_SHA256 = (
    "sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"
)
HISTORICAL_SOURCE_BYTE_LENGTH = 99_349
CURRENT_TOPICS_SOURCE_SHA256 = (
    "sha256:aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b"
)
CURRENT_TOPICS_SOURCE_BYTE_LENGTH = 920_705
EVIDENCE_RECORDED_AT = "2026-07-29T22:30:00Z"
EVIDENCE_RECORDED_BY = "urn:ref:agent:managed-vocabulary-experiment"

HISTORICAL_PARSER_PROFILE = (
    "refspec.registry.federal_register_thesaurus."
    "parse_federal_register_thesaurus:"
    "source-faithful-historical-grouping-v2"
)

EXPECTED_COMPARISON_COUNTS = {
    "currentAdHocRecords": 6_723,
    "currentAdHocSlugCollisionGroups": 68,
    "currentEmptySlugRecords": 3,
    "currentThesaurusRecords": 1_044,
    "currentThesaurusRelationAssertions": 1_428,
    "currentThesaurusSlugCollisionGroups": 8,
    "historicalAnyLabelOverlap": 629,
    "historicalPreferredHeadings": 629,
    "historicalPreferredOnly": 10,
    "historicalRelationAssertions": 1_496,
    "preferredLabelOverlap": 619,
    "currentPreferredOnly": 425,
}


class FederalRegisterTopicsReconciliationError(ValueError):
    """The pinned comparison cannot be reproduced exactly."""


@dataclass(frozen=True, slots=True)
class FederalRegisterTopicsReconciliationProof:
    """One exact unresolved report and its compact reproducibility evidence."""

    report: RegistryReconciliationReport
    evidence: dict[str, Any]

    @property
    def record(self) -> dict[str, Any]:
        """Return the sealed RefSpec reconciliation record."""

        return self.report.sealed_payload()


def _sha256_json(value: object) -> str:
    encoded = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _digest_hex(value: str) -> str:
    prefix = "sha256:"
    if not value.startswith(prefix) or len(value) != len(prefix) + 64:
        raise FederalRegisterTopicsReconciliationError(
            "source identity must be a sha256:<64 lowercase hex> digest"
        )
    digest_hex = value.removeprefix(prefix)
    if any(character not in "0123456789abcdef" for character in digest_hex):
        raise FederalRegisterTopicsReconciliationError(
            "source identity must be a sha256:<64 lowercase hex> digest"
        )
    return digest_hex


def federal_register_topic_source_record_id(
    capture_sha256: str,
    record: FederalRegisterTopicRecord,
) -> str:
    """Identify one API row without using its mutable name or slug."""

    capture_hex = _digest_hex(capture_sha256)
    if record.collection not in {"thesaurus", "ad_hoc"}:
        raise FederalRegisterTopicsReconciliationError(
            "source record collection is not supported"
        )
    if record.source_ordinal < 0:
        raise FederalRegisterTopicsReconciliationError(
            "source record ordinal must be non-negative"
        )
    return (
        "urn:ref:source-record:federal-register-topics:"
        f"{capture_hex}:{record.collection}:{record.source_ordinal}"
    )


def require_unique_capture_local_observation_ids(
    observations: Iterable[tuple[str, str, int, str]],
) -> None:
    """Reject duplicate capture-local locators or their generated identifiers."""

    seen_locators: dict[tuple[str, str, int], int] = {}
    seen_identifiers: dict[str, int] = {}
    for position, (
        capture_sha256,
        collection_or_path,
        source_ordinal,
        identifier,
    ) in enumerate(observations):
        _digest_hex(capture_sha256)
        if not collection_or_path:
            raise FederalRegisterTopicsReconciliationError(
                "capture-local collection or path must not be empty"
            )
        if (
            not isinstance(source_ordinal, int)
            or isinstance(source_ordinal, bool)
            or source_ordinal < 0
        ):
            raise FederalRegisterTopicsReconciliationError(
                "capture-local source ordinal must be a non-negative integer"
            )
        if not identifier:
            raise FederalRegisterTopicsReconciliationError(
                "capture-local observation identifier must not be empty"
            )

        locator = (
            capture_sha256,
            collection_or_path,
            source_ordinal,
        )
        previous_locator_position = seen_locators.get(locator)
        if previous_locator_position is not None:
            raise FederalRegisterTopicsReconciliationError(
                "duplicate capture-local source locator at positions "
                f"{previous_locator_position} and {position}; names and "
                "slugs cannot disambiguate source observations"
            )
        previous_identifier_position = seen_identifiers.get(identifier)
        if previous_identifier_position is not None:
            raise FederalRegisterTopicsReconciliationError(
                "duplicate capture-local observation identifier at positions "
                f"{previous_identifier_position} and {position}"
            )
        seen_locators[locator] = position
        seen_identifiers[identifier] = position


def _stage_evidence(
    *,
    family: str,
    source_sha256: str,
    parser_profile: str,
    name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    source_hex = _digest_hex(source_sha256)
    stage_basis = {
        "name": name,
        "parserProfile": parser_profile,
        "rows": rows,
        "sourceSha256": source_sha256,
    }
    return {
        "id": (
            f"urn:ref:development-stage:{family}:{source_hex}:{name}"
        ),
        "digest": _sha256_json(stage_basis),
        "itemCount": len(rows),
        "parserProfile": parser_profile,
        "sourceSha256": source_sha256,
    }


def _digest_reference(value: dict[str, Any]) -> dict[str, str]:
    return {"id": str(value["id"]), "digest": str(value["digest"])}


def _development_release_descriptor(
    *,
    family: str,
    source_url: str,
    source_sha256: str,
    source_byte_length: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    source_hex = _digest_hex(source_sha256)
    identifier = (
        "urn:ref:development-snapshot:reference-resource-release:"
        f"{family}:{source_hex}"
    )
    version = f"source-sha256-{source_hex}"
    descriptor = {
        "authorityStatus": "none",
        "candidateUseAuthorized": False,
        "id": identifier,
        "kind": "developmentSourceSnapshotReference",
        "sourceArtifact": {
            "byteLength": source_byte_length,
            "digest": source_sha256,
            "id": source_url,
        },
        "version": version,
    }
    reference = {
        "id": identifier,
        "version": version,
        "digest": _sha256_json(descriptor),
    }
    return descriptor, reference


def _development_import_descriptor(
    *,
    family: str,
    source_sha256: str,
    stage_evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    source_hex = _digest_hex(source_sha256)
    identifier = (
        "urn:ref:development-snapshot:registry-import:"
        f"{family}:{source_hex}"
    )
    descriptor = {
        "acceptedOutputUseAuthorized": False,
        "candidateUseAuthorized": False,
        "id": identifier,
        "kind": "developmentImportSnapshotReference",
        "sourceSha256": source_sha256,
        "stageDigests": [
            _digest_reference(stage) for stage in stage_evidence
        ],
    }
    reference = {"id": identifier, "digest": _sha256_json(descriptor)}
    return descriptor, reference


def _historical_stages(
    historical: FederalRegisterThesaurus,
) -> list[dict[str, Any]]:
    return [
        _stage_evidence(
            family="federal-register-thesaurus-1995",
            source_sha256=historical.source_sha256,
            parser_profile=HISTORICAL_PARSER_PROFILE,
            name="source-entry-inventory",
            rows=[asdict(item) for item in historical.entries],
        ),
        _stage_evidence(
            family="federal-register-thesaurus-1995",
            source_sha256=historical.source_sha256,
            parser_profile=HISTORICAL_PARSER_PROFILE,
            name="label-expression-inventory",
            rows=[asdict(item) for item in historical.labels],
        ),
        _stage_evidence(
            family="federal-register-thesaurus-1995",
            source_sha256=historical.source_sha256,
            parser_profile=HISTORICAL_PARSER_PROFILE,
            name="relation-assertion-inventory",
            rows=[asdict(item) for item in historical.relations],
        ),
        _stage_evidence(
            family="federal-register-thesaurus-1995",
            source_sha256=historical.source_sha256,
            parser_profile=HISTORICAL_PARSER_PROFILE,
            name="unresolved-source-reference-inventory",
            rows=[asdict(item) for item in historical.unresolved_references],
        ),
    ]


def federal_register_topic_source_identity_rows(
    current: FederalRegisterTopicsSnapshot,
    *,
    collection: str | None = None,
) -> list[dict[str, Any]]:
    """Build one identity stage and reject capture-local collisions."""

    if collection not in {None, "thesaurus", "ad_hoc"}:
        raise FederalRegisterTopicsReconciliationError(
            f"unknown topics collection: {collection}"
        )
    rows = current.records if collection is None else getattr(current, collection)
    identity_rows = [
        {
            "collection": item.collection,
            "sourceOrdinal": item.source_ordinal,
            "sourceRecordDigest": item.source_record_digest,
            "sourceRecordId": federal_register_topic_source_record_id(
                current.source_sha256,
                item,
            ),
        }
        for item in rows
    ]
    require_unique_capture_local_observation_ids(
        (
            current.source_sha256,
            str(row["collection"]),
            int(row["sourceOrdinal"]),
            str(row["sourceRecordId"]),
        )
        for row in identity_rows
    )
    return identity_rows


def _current_relation_rows(
    current: FederalRegisterTopicsSnapshot,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_hex = _digest_hex(current.source_sha256)
    for record in current.thesaurus:
        source_record_id = federal_register_topic_source_record_id(
            current.source_sha256,
            record,
        )
        for link_ordinal, link in enumerate(record.see_also):
            rows.append(
                {
                    "assertionId": (
                        "urn:ref:source-relation:federal-register-topics:"
                        f"{source_hex}:thesaurus:{record.source_ordinal}:"
                        f"see-also:{link_ordinal}"
                    ),
                    "linkOrdinal": link_ordinal,
                    "sourceRecordDigest": record.source_record_digest,
                    "sourceRecordId": source_record_id,
                    "sourceRelation": "see_also",
                    "targetAuthoredName": link.name,
                    "targetAuthoredSlug": link.slug,
                }
            )
    return rows


def _current_stages(
    current: FederalRegisterTopicsSnapshot,
) -> list[dict[str, Any]]:
    identity_rows = federal_register_topic_source_identity_rows(current)
    thesaurus_label_rows = [
        {
            "authoredName": item.name,
            "sourceRecordDigest": item.source_record_digest,
            "sourceRecordId": federal_register_topic_source_record_id(
                current.source_sha256,
                item,
            ),
        }
        for item in current.thesaurus
    ]
    slug_rows = [
        {
            "authoredSlug": item.slug,
            "collection": item.collection,
            "sourceOrdinal": item.source_ordinal,
            "sourceRecordId": federal_register_topic_source_record_id(
                current.source_sha256,
                item,
            ),
        }
        for item in current.records
    ]
    return [
        _stage_evidence(
            family="federal-register-topics-api",
            source_sha256=current.source_sha256,
            parser_profile=FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
            name="source-record-identity-inventory",
            rows=identity_rows,
        ),
        _stage_evidence(
            family="federal-register-topics-api",
            source_sha256=current.source_sha256,
            parser_profile=FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
            name="thesaurus-label-evidence",
            rows=thesaurus_label_rows,
        ),
        _stage_evidence(
            family="federal-register-topics-api",
            source_sha256=current.source_sha256,
            parser_profile=FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
            name="thesaurus-relation-assertion-inventory",
            rows=_current_relation_rows(current),
        ),
        _stage_evidence(
            family="federal-register-topics-api",
            source_sha256=current.source_sha256,
            parser_profile=FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
            name="ad-hoc-source-record-identity-inventory",
            rows=federal_register_topic_source_identity_rows(
                current,
                collection="ad_hoc",
            ),
        ),
        _stage_evidence(
            family="federal-register-topics-api",
            source_sha256=current.source_sha256,
            parser_profile=FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
            name="slug-observation-inventory",
            rows=slug_rows,
        ),
    ]


def _comparison_counts(
    historical: FederalRegisterThesaurus,
    current: FederalRegisterTopicsSnapshot,
    comparison: FederalRegisterTopicsComparison,
) -> dict[str, int]:
    collisions = current.slug_collisions()
    return {
        "currentAdHocRecords": len(current.ad_hoc),
        "currentAdHocSlugCollisionGroups": sum(
            collection == "ad_hoc" for collection, _slug in collisions
        ),
        "currentEmptySlugRecords": sum(
            item.slug == "" for item in current.records
        ),
        "currentThesaurusRecords": len(current.thesaurus),
        "currentThesaurusRelationAssertions": sum(
            len(item.see_also) for item in current.thesaurus
        ),
        "currentThesaurusSlugCollisionGroups": sum(
            collection == "thesaurus"
            for collection, _slug in collisions
        ),
        "historicalAnyLabelOverlap": (
            comparison.historical_any_label_overlap_count
        ),
        "historicalPreferredHeadings": (
            comparison.historical_preferred_count
        ),
        "historicalPreferredOnly": len(
            comparison.historical_preferred_only
        ),
        "historicalRelationAssertions": len(historical.relations),
        "preferredLabelOverlap": (
            comparison.preferred_label_overlap_count
        ),
        "currentPreferredOnly": len(comparison.current_preferred_only),
    }


def _require_expected_comparison(counts: dict[str, int]) -> None:
    if counts != EXPECTED_COMPARISON_COUNTS:
        changed = {
            key: {
                "expected": EXPECTED_COMPARISON_COUNTS.get(key),
                "observed": counts.get(key),
            }
            for key in sorted(
                set(counts) | set(EXPECTED_COMPARISON_COUNTS)
            )
            if counts.get(key) != EXPECTED_COMPARISON_COUNTS.get(key)
        }
        raise FederalRegisterTopicsReconciliationError(
            f"pinned Federal Register comparison changed: {changed}"
        )


def _precedence_policy() -> tuple[dict[str, Any], dict[str, str]]:
    identifier = (
        "urn:ref:policy:federal-register-topics:"
        "unresolved-comparison-boundary"
    )
    version = "1.0.0-development"
    declaration = {
        "acceptedOutputUseAuthorized": False,
        "adHocCollectionTreatment": "distinct",
        "candidateUseAuthorized": False,
        "conceptIdentityInference": "none",
        "conceptMappingCount": 0,
        "id": identifier,
        "inputSelectionAuthorized": False,
        "synthesizedUnionAuthorized": False,
        "version": version,
    }
    reference = {
        "id": identifier,
        "version": version,
        "digest": _sha256_json(declaration),
    }
    return declaration, reference


def _difference(
    *,
    report_key: str,
    suffix: str,
    kind: str,
    input_ids: tuple[str, str],
    description: str,
) -> dict[str, Any]:
    return {
        "id": f"urn:ref:difference:{report_key}:{suffix}",
        "kind": kind,
        "inputRefs": list(input_ids),
        "description": description,
        "resolution": "unresolved",
    }


def build_federal_register_topics_reconciliation(
    historical_source_path: Path,
    current_topics_path: Path,
    *,
    recorded_at: str = EVIDENCE_RECORDED_AT,
    recorded_by: str = EVIDENCE_RECORDED_BY,
) -> FederalRegisterTopicsReconciliationProof:
    """Reproduce the exact comparison and emit no selection or union."""

    historical_path = Path(historical_source_path)
    if historical_path.is_symlink() or not historical_path.is_file():
        raise FederalRegisterTopicsReconciliationError(
            f"historical source is not a regular file: {historical_path}"
        )
    historical_bytes = historical_path.read_bytes()
    if len(historical_bytes) != HISTORICAL_SOURCE_BYTE_LENGTH:
        raise FederalRegisterTopicsReconciliationError(
            "historical source byte length does not match its pin"
        )
    historical = parse_federal_register_thesaurus(
        historical_bytes,
        require_resolved=False,
    )
    if historical.source_sha256 != HISTORICAL_SOURCE_SHA256:
        raise FederalRegisterTopicsReconciliationError(
            "historical source digest does not match its pin"
        )

    current = open_federal_register_topics_capture(
        Path(current_topics_path),
        expected_sha256=CURRENT_TOPICS_SOURCE_SHA256,
        expected_byte_length=CURRENT_TOPICS_SOURCE_BYTE_LENGTH,
    )
    comparison = compare_historical_thesaurus_to_topics(
        historical,
        current,
    )
    counts = _comparison_counts(historical, current, comparison)
    _require_expected_comparison(counts)

    historical_stages = _historical_stages(historical)
    current_stages = _current_stages(current)
    historical_release_descriptor, historical_release_ref = (
        _development_release_descriptor(
            family="federal-register-thesaurus-1995",
            source_url=FEDERAL_REGISTER_THESAURUS_1995_URL,
            source_sha256=historical.source_sha256,
            source_byte_length=historical.source_bytes,
        )
    )
    current_release_descriptor, current_release_ref = (
        _development_release_descriptor(
            family="federal-register-topics-api",
            source_url=FEDERAL_REGISTER_TOPICS_API_URL,
            source_sha256=current.source_sha256,
            source_byte_length=current.source_byte_length,
        )
    )
    historical_import_descriptor, historical_import_ref = (
        _development_import_descriptor(
            family="federal-register-thesaurus-1995",
            source_sha256=historical.source_sha256,
            stage_evidence=historical_stages,
        )
    )
    current_import_descriptor, current_import_ref = (
        _development_import_descriptor(
            family="federal-register-topics-api",
            source_sha256=current.source_sha256,
            stage_evidence=current_stages,
        )
    )

    historical_input_id = (
        "urn:ref:reconciliation-input:federal-register-thesaurus-1995:"
        f"{_digest_hex(historical.source_sha256)}"
    )
    current_input_id = (
        "urn:ref:reconciliation-input:federal-register-topics-api:"
        f"{_digest_hex(current.source_sha256)}"
    )
    inputs = (
        {
            "id": historical_input_id,
            "referenceResourceRelease": historical_release_ref,
            "distributionArtifacts": [
                {
                    "id": FEDERAL_REGISTER_THESAURUS_1995_URL,
                    "digest": historical.source_sha256,
                }
            ],
            "registryImportSnapshot": historical_import_ref,
            "stageDigests": [
                _digest_reference(stage)
                for stage in historical_stages
            ],
        },
        {
            "id": current_input_id,
            "referenceResourceRelease": current_release_ref,
            "distributionArtifacts": [
                {
                    "id": FEDERAL_REGISTER_TOPICS_API_URL,
                    "digest": current.source_sha256,
                }
            ],
            "registryImportSnapshot": current_import_ref,
            "stageDigests": [
                _digest_reference(stage) for stage in current_stages
            ],
        },
    )

    policy_declaration, policy_ref = _precedence_policy()
    proof_identity = {
        "comparisonDigest": comparison.canonical_digest,
        "currentImportSnapshot": current_import_ref,
        "historicalImportSnapshot": historical_import_ref,
        "precedencePolicy": policy_ref,
    }
    report_key = _digest_hex(_sha256_json(proof_identity))
    input_ids = (historical_input_id, current_input_id)
    differences = (
        _difference(
            report_key=report_key,
            suffix="preferred-label-membership",
            kind="member",
            input_ids=input_ids,
            description=(
                "Normalized literal evidence has 619 preferred-label "
                "overlaps, 10 historical-only preferred labels, and 425 "
                "current-only thesaurus names; labels do not establish "
                "cross-source concept identity."
            ),
        ),
        _difference(
            report_key=report_key,
            suffix="source-record-identity",
            kind="field",
            input_ids=input_ids,
            description=(
                "The current capture contains 8 thesaurus and 68 ad_hoc "
                "slug-collision groups plus 3 empty slugs, so neither name "
                "nor slug can identify a source record."
            ),
        ),
        _difference(
            report_key=report_key,
            suffix="relation-assertions",
            kind="relation",
            input_ids=input_ids,
            description=(
                "The historical source has 1496 authored relation "
                "assertions; the current thesaurus collection has 1428 "
                "authored see_also assertions. No relation or concept "
                "mapping has been asserted."
            ),
        ),
        _difference(
            report_key=report_key,
            suffix="ad-hoc-collection-boundary",
            kind="member",
            input_ids=input_ids,
            description=(
                "The current API contains 6723 ad_hoc rows in a distinct "
                "source collection; they are not historical thesaurus "
                "members and cannot enter a synthesized union."
            ),
        ),
        _difference(
            report_key=report_key,
            suffix="historical-unresolved-references",
            kind="relation",
            input_ids=input_ids,
            description=(
                "The source-faithful historical parse retains 20 unresolved "
                "source references, so its development snapshot is not a "
                "selection authority."
            ),
        ),
    )
    report = RegistryReconciliationReport(
        report_id=(
            "urn:ref:reconciliation:federal-register-topics:"
            f"{report_key}"
        ),
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="complete",
        inputs=inputs,
        compared_items=(
            {
                "kind": "stageDigest",
                "left": historical_stages[0]["id"],
                "right": current_stages[0]["id"],
            },
            {
                "kind": "member",
                "left": historical_stages[1]["id"],
                "right": current_stages[1]["id"],
            },
            {
                "kind": "relation",
                "left": historical_stages[2]["id"],
                "right": current_stages[2]["id"],
            },
            {
                "kind": "member",
                "left": historical_stages[0]["id"],
                "right": current_stages[3]["id"],
            },
        ),
        differences=differences,
        concept_mappings=(),
        precedence_policy=policy_ref,
        rulespec_authority_refs=(
            (
                "urn:ref:development-governance:"
                f"rulespec-authority-declaration:{report_key}"
            ),
        ),
        attestation_refs=(
            (
                "urn:ref:development-governance:"
                f"attestation-declaration:{report_key}"
            ),
        ),
        local_adoption_refs=(
            (
                "urn:ref:development-governance:"
                f"local-adoption-declaration:{report_key}"
            ),
        ),
        unresolved_items=tuple(
            str(item["id"]) for item in differences
        ),
        activity=(
            "urn:ref:activity:federal-register-topics-reconciliation:"
            f"{report_key}"
        ),
        outcome="unresolved",
    )
    record = report.sealed_payload()
    diagnostics = binding.validate([record])
    if diagnostics:
        rendered = "; ".join(
            f"{item.requirement}: {item.message}" for item in diagnostics
        )
        raise FederalRegisterTopicsReconciliationError(
            f"generated reconciliation report is not conforming: {rendered}"
        )

    evidence = {
        "evidenceType": (
            "FederalRegisterTopicsUnresolvedReconciliationProof"
        ),
        "recordedAt": recorded_at,
        "sources": {
            "historical": {
                "byteLength": historical.source_bytes,
                "digest": historical.source_sha256,
                "id": FEDERAL_REGISTER_THESAURUS_1995_URL,
                "inputId": historical_input_id,
                "parserProfile": HISTORICAL_PARSER_PROFILE,
            },
            "current": {
                "byteLength": current.source_byte_length,
                "digest": current.source_sha256,
                "id": FEDERAL_REGISTER_TOPICS_API_URL,
                "inputId": current_input_id,
                "parserProfile": FEDERAL_REGISTER_TOPICS_PARSER_VERSION,
                "sourceRecordSetDigest": (
                    current.source_record_set_digest
                ),
            },
        },
        "sourceCounts": {
            "historical": {
                **asdict(historical.counts),
            },
            "current": current.counts,
        },
        "comparison": {
            "counts": counts,
            "digest": comparison.canonical_digest,
            "identityInference": "none",
            "outcome": "unresolved",
        },
        "sourceRecordIdentity": {
            "identityInputs": [
                "captureSha256",
                "collection",
                "sourceOrdinal",
            ],
            "excludedIdentityInputs": ["name", "slug"],
            "ordinalBase": 0,
            "template": (
                "urn:ref:source-record:federal-register-topics:"
                "{capture-sha256-hex}:{collection}:{source-ordinal}"
            ),
        },
        "stageDigests": {
            "historical": historical_stages,
            "current": current_stages,
        },
        "developmentSnapshotReferences": {
            "historicalReleaseDescriptor": (
                historical_release_descriptor
            ),
            "historicalReleaseReference": historical_release_ref,
            "historicalImportDescriptor": (
                historical_import_descriptor
            ),
            "historicalImportReference": historical_import_ref,
            "currentReleaseDescriptor": current_release_descriptor,
            "currentReleaseReference": current_release_ref,
            "currentImportDescriptor": current_import_descriptor,
            "currentImportReference": current_import_ref,
        },
        "precedencePolicy": {
            "declaration": policy_declaration,
            "reference": policy_ref,
        },
        "authorityBoundary": {
            "acceptedOutputAuthority": False,
            "adHocCollectionTreatment": "distinct",
            "conceptMappingsAsserted": 0,
            "governanceReferenceStatus": (
                "unvalidated development declarations for recording the "
                "unresolved result only"
            ),
            "inputReferenceStatus": (
                "development snapshot references derived from exact "
                "captures; not authoritative concept releases"
            ),
            "selectedDeploymentAuthority": False,
            "synthesizedUnionAuthority": False,
        },
        "reconciliationReport": record,
    }
    return FederalRegisterTopicsReconciliationProof(
        report=report,
        evidence=evidence,
    )


__all__ = [
    "CURRENT_TOPICS_SOURCE_BYTE_LENGTH",
    "CURRENT_TOPICS_SOURCE_SHA256",
    "EVIDENCE_RECORDED_AT",
    "EVIDENCE_RECORDED_BY",
    "EXPECTED_COMPARISON_COUNTS",
    "HISTORICAL_SOURCE_BYTE_LENGTH",
    "HISTORICAL_SOURCE_SHA256",
    "FederalRegisterTopicsReconciliationError",
    "FederalRegisterTopicsReconciliationProof",
    "build_federal_register_topics_reconciliation",
    "federal_register_topic_source_identity_rows",
    "federal_register_topic_source_record_id",
    "require_unique_capture_local_observation_ids",
]

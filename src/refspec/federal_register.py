"""Reproducible April 1, 2025 Federal Register first-slice release."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .canonical import stable_record
from .records import (
    AgentValidationReceipt,
    BaselineValidationReceipt,
    RecordReference,
    SourceTermKey,
    SourceTermResolution,
    TargetConceptRelease,
    VocabularyCoverage,
    VocabularyRelease,
    create_support_record,
)
from .reference_resource import (
    build_reference_resource_release,
    reference_release_node,
)
from .release import (
    seal_external_concept,
    validate_vocabulary_release,
    vocabulary_distribution_payload,
)
from .rulespec_core import rulespec_core_fixture_pin, rulespec_core_release_ref
from .source_fixtures import (
    federal_register_source_fixture_pin,
    load_federal_register_source_fixture,
)


FIXED_EVALUATION_TIME = "2026-07-31T16:00:00Z"


def _support_ref(record: Mapping[str, Any]) -> RecordReference:
    return RecordReference.from_record(
        record,
        id_field="record_id",
        digest_field="record_digest",
    )


def _label_record(
    *,
    concept_id: str,
    label: str,
    label_kind: str,
    source_locator: Mapping[str, Any],
) -> dict[str, Any]:
    return stable_record(
        {
            "concept_id": concept_id,
            "label": label,
            "language": "en",
            "label_kind": label_kind,
            "source_locator": dict(source_locator),
        },
        id_field="label_id",
        digest_field="label_digest",
        id_prefix="urn:refspec:label:",
    )


def _redirect_record(variant: Mapping[str, Any]) -> dict[str, Any]:
    return stable_record(
        {
            "source_label": variant["label"],
            "language": "en",
            "target_concept_id": variant["target_concept_id"],
            "basis": "publisher-authored recognized variant",
            "source_locator": variant["source_locator"],
        },
        id_field="redirect_id",
        digest_field="redirect_digest",
        id_prefix="urn:refspec:redirect:",
    )


def build_federal_register_2025_first_slice() -> dict[str, Any]:
    """Build and validate the deterministic Federal Register release fixture."""

    fixture = load_federal_register_source_fixture()
    vocabulary = fixture["vocabulary"]
    source = fixture["source"]

    concepts = [
        seal_external_concept(
            {
                "concept_id": concept["concept_id"],
                "scheme_id": vocabulary["scheme_id"],
                "preferred_label": concept["label"],
                "language": "en",
                "source_locator": concept["source_locator"],
            }
        )
        for concept in fixture["concepts"]
    ]
    labels = [
        _label_record(
            concept_id=concept["concept_id"],
            label=concept["label"],
            label_kind="preferred",
            source_locator=concept["source_locator"],
        )
        for concept in fixture["concepts"]
    ]
    labels.extend(
        _label_record(
            concept_id=variant["target_concept_id"],
            label=variant["label"],
            label_kind="recognizedVariant",
            source_locator=variant["source_locator"],
        )
        for variant in fixture["recognized_variants"]
    )
    redirects = [
        _redirect_record(variant) for variant in fixture["recognized_variants"]
    ]
    distribution_payload = vocabulary_distribution_payload(
        concepts=concepts,
        labels=labels,
        hierarchy=(),
        mappings=(),
        redirects=redirects,
    )
    reference_release = build_reference_resource_release(
        scheme_id=vocabulary["scheme_id"],
        release_version=vocabulary["version"],
        concept_ids=[concept["concept_id"] for concept in concepts],
        distribution_payload=distribution_payload,
    )
    reference_node = reference_release_node(reference_release)
    reference_release_ref = RecordReference(
        str(reference_node["@id"]),
        str(reference_node["rkaf:referenceReleaseDigest"]),
    )

    source_evidence = create_support_record(
        "VocabularySourceEvidence",
        {
            "publisher": source["publisher"],
            "issued": source["issued"],
            "url": source["url"],
            "media_type": source["media_type"],
            "source_digest": source["sha256"],
            "source_byte_length": source["byte_length"],
            "page_count": source["page_count"],
            "parser_version": fixture["parser_version"],
        },
    )
    resolution_evidence = create_support_record(
        "SourceTermResolutionEvidence",
        {
            "source_fixture_id": fixture["fixture_id"],
            "examples": fixture["resolution_examples"],
            "recognized_variants": fixture["recognized_variants"],
        },
    )
    sample_manifest = create_support_record(
        "ValidationSampleManifest",
        {
            "fixture_id": fixture["fixture_id"],
            "reference_resource_release_ref": reference_release_ref.to_dict(),
            "concept_ids": sorted(concept["concept_id"] for concept in concepts),
            "required_resolution_states": [
                "officialTerm",
                "recognizedVariant",
                "sourceLocalOpenTerm",
                "unresolved",
            ],
        },
    )
    request_contract = create_support_record(
        "ValidationRequestContract",
        {
            "protocol_and_version": "refspec-vocabulary-baseline-v1",
            "instructions": [
                "Inspect only the sealed source and resolution evidence.",
                "Check target meaning, ambiguity, and unsupported claims.",
                "Return a result for each named check and cite evidence records.",
            ],
            "secret_fields": [],
        },
    )
    response_a = create_support_record(
        "AgentResponseArtifact",
        {
            "fixture_role": "independent conformance example A",
            "outcomes": {
                "official-and-variant-targets": "pass",
                "open-and-unresolved-terms": "pass",
            },
        },
    )
    response_b = create_support_record(
        "AgentResponseArtifact",
        {
            "fixture_role": "independent conformance example B",
            "outcomes": {
                "official-and-variant-targets": "pass",
                "open-and-unresolved-terms": "pass",
            },
        },
    )
    deterministic_receipt = create_support_record(
        "DeterministicValidationReceipt",
        {
            "checks": [
                "canonical-json",
                "stable-identifiers",
                "complete-membership",
                "reference-closure",
                "resolution-cardinality",
            ],
            "outcome": "pass",
            "fixture_role": "conformance example",
        },
    )
    support_records = [
        source_evidence,
        resolution_evidence,
        sample_manifest,
        request_contract,
        response_a,
        response_b,
        deterministic_receipt,
    ]

    check_outcomes = (
        {
            "check_id": "official-and-variant-targets",
            "outcome": "pass",
            "rationale": (
                "The sealed examples distinguish official terms from the "
                "publisher-authored recognized variant."
            ),
            "evidence_refs": [
                _support_ref(source_evidence).to_dict(),
                _support_ref(resolution_evidence).to_dict(),
            ],
        },
        {
            "check_id": "open-and-unresolved-terms",
            "outcome": "pass",
            "rationale": (
                "Open and ambiguous terms remain untargeted and fail closed."
            ),
            "evidence_refs": [_support_ref(resolution_evidence).to_dict()],
        },
    )
    agent_a = AgentValidationReceipt.create(
        attempt_id="refspec-first-slice-conformance-a1",
        owner="RefSpec conformance fixture",
        target_ref_and_digest=reference_release_ref,
        protocol_and_version="refspec-vocabulary-baseline-v1",
        input_manifest_ref_and_digest=_support_ref(sample_manifest),
        validator_actor_ref="urn:refspec:fixture-validator:independent-a",
        validator_kind="aiAgent",
        independence_group="conformance-validator-family-a",
        provider_and_model_id="conformance-fixture/validator-a-v1",
        request_contract_ref_and_digest=_support_ref(request_contract),
        response_artifact_ref_and_digest=_support_ref(response_a),
        execution_status="completed",
        check_outcomes=check_outcomes,
        overall_recommendation="supports",
        started_at=FIXED_EVALUATION_TIME,
        completed_at=FIXED_EVALUATION_TIME,
    )
    agent_b = AgentValidationReceipt.create(
        attempt_id="refspec-first-slice-conformance-b1",
        owner="RefSpec conformance fixture",
        target_ref_and_digest=reference_release_ref,
        protocol_and_version="refspec-vocabulary-baseline-v1",
        input_manifest_ref_and_digest=_support_ref(sample_manifest),
        validator_actor_ref="urn:refspec:fixture-validator:independent-b",
        validator_kind="aiAgent",
        independence_group="conformance-validator-family-b",
        provider_and_model_id="conformance-fixture/validator-b-v1",
        request_contract_ref_and_digest=_support_ref(request_contract),
        response_artifact_ref_and_digest=_support_ref(response_b),
        execution_status="completed",
        check_outcomes=check_outcomes,
        overall_recommendation="supports",
        started_at=FIXED_EVALUATION_TIME,
        completed_at=FIXED_EVALUATION_TIME,
    )
    baseline = BaselineValidationReceipt.create(
        owner="RefSpec conformance fixture",
        target_profile_and_release_ref=reference_release_ref,
        sample_manifest_ref_and_digest=_support_ref(sample_manifest),
        rubric_and_version="refspec-vocabulary-rubric-v1",
        aggregation_policy_and_version="refspec-independent-baseline-v1",
        deterministic_check_receipt_refs=(_support_ref(deterministic_receipt),),
        deterministic_check_outcomes=(
            {
                "check_id": "release-integrity",
                "outcome": "pass",
                "receipt_ref": _support_ref(deterministic_receipt).to_dict(),
            },
        ),
        agent_validation_receipt_refs=(agent_a.reference(), agent_b.reference()),
        aggregate_result="usable_for_search",
        disagreements_and_flags=(),
        known_limitations=(
            "This sealed first-slice fixture publishes five of 705 source concepts.",
            "Its validation receipts are conformance examples, not production claims.",
        ),
        evaluated_at=FIXED_EVALUATION_TIME,
    )

    source_term_keys: list[SourceTermKey] = []
    resolutions: list[SourceTermResolution] = []
    target_by_id = {concept["concept_id"] for concept in concepts}
    for example in fixture["resolution_examples"]:
        key = SourceTermKey.create(
            source_system_and_profile_version=example[
                "source_system_and_profile_version"
            ],
            observation_kind=example["observation_kind"],
            source_native_path=example["source_native_path"],
            raw_value=example["raw_value"],
            language=example["language"],
            source_context_discriminator=example.get("source_context_discriminator"),
        )
        target = None
        if "target_concept_id" in example:
            if example["target_concept_id"] not in target_by_id:
                raise ValueError("source fixture target is outside the release")
            target = TargetConceptRelease(
                concept_id=example["target_concept_id"],
                reference_resource_release_id=str(reference_node["@id"]),
                reference_resource_release_digest=str(
                    reference_node["rkaf:referenceReleaseDigest"]
                ),
            )
        resolution = SourceTermResolution.create(
            source_term_key_ref=key.reference(),
            resolution_status=example["status"],
            policy_and_version="federal-register-source-term-resolution-v1",
            reason=example["reason"],
            target_concept_and_release=target,
            evidence_refs=(
                _support_ref(source_evidence),
                _support_ref(resolution_evidence),
            ),
            baseline_validation_receipt_ref=baseline.reference(),
        )
        source_term_keys.append(key)
        resolutions.append(resolution)

    status_counts = Counter(resolution.resolution_status for resolution in resolutions)
    coverage = VocabularyCoverage.create(
        source_complete_concept_count=vocabulary["complete_source_concept_count"],
        published_concept_count=len(concepts),
        resolution_key_count=len(source_term_keys),
        resolution_counts_by_status={
            status: status_counts.get(status, 0)
            for status in sorted(
                {
                    "officialTerm",
                    "recognizedVariant",
                    "sourceLocalOpenTerm",
                    "unresolved",
                }
            )
        },
        included_source_locators=tuple(
            concept["source_locator"] for concept in fixture["concepts"]
        ),
        excluded_scope=(
            "Concepts outside the sealed five-concept first slice",
            "Document observations and their capture history",
            "Search indexes, ranking, and result records",
        ),
    )

    payload = {
        "schema_version": "refspec-vocabulary-release-v1",
        "vocabulary": {
            "scheme_id": vocabulary["scheme_id"],
            "title": vocabulary["title"],
            "version": vocabulary["version"],
            "publisher": source["publisher"],
            "release_scope": vocabulary["release_scope"],
            "default_for_source_profiles": vocabulary["default_for_source_profiles"],
            "root_ontology": vocabulary["root_ontology"],
            "source_distribution": {
                "url": source["url"],
                "issued": source["issued"],
                "digest": source["sha256"],
            },
        },
        "source_fixture_pin": federal_register_source_fixture_pin(),
        "rulespec_core_fixture": rulespec_core_fixture_pin(),
        "rulespec_core_release": rulespec_core_release_ref(),
        "reference_resource_release": reference_release,
        "concepts": concepts,
        "labels": labels,
        "hierarchy": [],
        "mappings": [],
        "redirects": redirects,
        "source_term_keys": [item.to_dict() for item in source_term_keys],
        "source_term_resolutions": [item.to_dict() for item in resolutions],
        "support_records": support_records,
        "agent_validation_receipts": [agent_a.to_dict(), agent_b.to_dict()],
        "baseline_validation_receipts": [baseline.to_dict()],
        "resolution_policy": {
            "policy_and_version": "federal-register-source-term-resolution-v1",
            "missing_resolution_behavior": "failClosed",
            "targeted_statuses": ["officialTerm", "recognizedVariant"],
            "untargeted_statuses": ["sourceLocalOpenTerm", "unresolved"],
            "human_approval_required": False,
        },
        "coverage": coverage.to_dict(),
    }
    release = VocabularyRelease.create(payload).to_dict()
    validate_vocabulary_release(release)
    return release

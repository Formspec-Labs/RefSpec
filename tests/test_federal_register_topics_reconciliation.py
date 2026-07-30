from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from refspec import binding
from refspec.registry.federal_register_topics_api import (
    FederalRegisterTopicRecord,
    FederalRegisterTopicsSnapshot,
)
from refspec.registry.federal_register_topics_reconciliation import (
    CURRENT_TOPICS_SOURCE_SHA256,
    EXPECTED_COMPARISON_COUNTS,
    FederalRegisterTopicsReconciliationError,
    build_federal_register_topics_reconciliation,
    federal_register_topic_source_identity_rows,
    federal_register_topic_source_record_id,
    require_unique_capture_local_observation_ids,
)
from refspec.vocabulary import (
    ReferenceRuntimeError,
    RegistryDeploymentDecision,
    seal_payload,
)

REFSPEC_ROOT = Path(__file__).parents[1]
SPICY_REGS_ROOT = Path(__file__).parents[2]
HISTORICAL_SOURCE = (
    SPICY_REGS_ROOT
    / "output"
    / "managed-vocabulary-experiment"
    / "source-store"
    / "sha256"
    / "d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"
    / "thesaurus-alpha.txt"
)
CURRENT_SOURCE = (
    SPICY_REGS_ROOT
    / "output"
    / "federal-register-topics-source-store"
    / "sha256"
    / "aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b"
    / "topics.json"
)
EVIDENCE = (
    REFSPEC_ROOT
    / "research"
    / "evidence"
    / "federal-register-topics-reconciliation-2026-07-29"
    / "evidence.json"
)
HAS_EXACT_SOURCES = HISTORICAL_SOURCE.is_file() and CURRENT_SOURCE.is_file()
requires_exact_sources = pytest.mark.skipif(
    not HAS_EXACT_SOURCES,
    reason=(
        "exact content-addressed Federal Register development sources are "
        "not present beside the RefSpec checkout"
    ),
)


def _topic_record(
    *,
    collection: str = "thesaurus",
    source_ordinal: int = 7,
    name: str = "Example name",
    slug: str = "example-slug",
) -> FederalRegisterTopicRecord:
    return FederalRegisterTopicRecord(
        collection=collection,  # type: ignore[arg-type]
        source_ordinal=source_ordinal,
        name=name,
        slug=slug,
        see=(),
        see_also=(),
        cfr_reference_json=(),
    )


def _proof():
    return build_federal_register_topics_reconciliation(
        HISTORICAL_SOURCE,
        CURRENT_SOURCE,
    )


def _selected_deployment(
    proof_record: dict[str, object],
    release_ref: dict[str, str],
) -> tuple[
    RegistryDeploymentDecision,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    rights_ref = {
        "id": "urn:test:rights-assessment:development",
        "digest": "sha256:" + "1" * 64,
    }
    policy_ref = "urn:test:policy:development"
    output_profile = seal_payload(
        {
            "id": "urn:test:output-profile:development",
            "type": "urn:ref:type:OutputProfile",
            "version": "1.0.0-development",
        }
    )
    output_ref = {
        "id": str(output_profile["id"]),
        "version": str(output_profile["version"]),
        "digest": str(output_profile["contentDigest"]),
    }
    import_snapshot = seal_payload(
        {
            "id": "urn:test:import:development",
            "type": "urn:ref:type:RegistryImportSnapshot",
            "rightsAssessment": rights_ref,
            "adoptedPolicyRefs": [policy_ref],
        }
    )
    import_ref = {
        "id": str(import_snapshot["id"]),
        "digest": str(import_snapshot["canonicalPayloadDigest"]),
    }
    coverage = seal_payload(
        {
            "id": "urn:test:coverage:development",
            "type": "urn:ref:type:RegistryImportCoverageReport",
            "registryImportSnapshot": import_ref,
            "referenceResourceRelease": release_ref,
            "outputProfile": output_ref,
            "reportStatus": "pass",
        }
    )
    coverage_ref = {
        "id": str(coverage["id"]),
        "digest": str(coverage["canonicalPayloadDigest"]),
    }
    reconciliation_ref = {
        "id": str(proof_record["id"]),
        "digest": str(proof_record["canonicalPayloadDigest"]),
    }
    decision = RegistryDeploymentDecision(
        decision_id="urn:test:deployment:must-fail",
        recorded_at="2026-07-29T23:00:00Z",
        recorded_by="urn:test:actor:negative-proof",
        operational_state="proposed",
        environment={
            "id": "urn:test:environment:development",
            "classification": "development",
        },
        registry_import_snapshot=import_ref,
        rights_assessment=rights_ref,
        adopted_policy_refs=(policy_ref,),
        reference_resource_release=release_ref,
        coverage_report=coverage_ref,
        output_profile=output_ref,
        selection_state="selected",
        effective_at="2026-07-29T23:00:00Z",
        reason=(
            "Prove that an unresolved reconciliation cannot select a "
            "deployment."
        ),
        activity="urn:test:activity:negative-proof",
        rulespec_attestation_refs=(),
        local_adoption_refs=(),
        reconciliation_report=reconciliation_ref,
    )
    return decision, import_snapshot, coverage, output_profile


def test_api_source_record_identity_excludes_name_and_slug() -> None:
    original = _topic_record()
    changed_labels = replace(
        original,
        name="Completely different name",
        slug="completely-different-slug",
    )
    changed_capture = "sha256:" + "b" * 64
    changed_ordinal = replace(original, source_ordinal=8)
    changed_collection = replace(original, collection="ad_hoc")

    original_id = federal_register_topic_source_record_id(
        CURRENT_TOPICS_SOURCE_SHA256,
        original,
    )
    assert original_id == federal_register_topic_source_record_id(
        CURRENT_TOPICS_SOURCE_SHA256,
        changed_labels,
    )
    assert original_id != federal_register_topic_source_record_id(
        changed_capture,
        original,
    )
    assert original_id != federal_register_topic_source_record_id(
        CURRENT_TOPICS_SOURCE_SHA256,
        changed_ordinal,
    )
    assert original_id != federal_register_topic_source_record_id(
        CURRENT_TOPICS_SOURCE_SHA256,
        changed_collection,
    )
    assert original.name not in original_id
    assert original.slug not in original_id


def test_same_name_and_empty_slug_remain_distinct_by_source_ordinal() -> None:
    first = _topic_record(
        source_ordinal=10,
        name="Same mutable name",
        slug="",
    )
    second = replace(first, source_ordinal=11)
    snapshot = FederalRegisterTopicsSnapshot(
        source_sha256=CURRENT_TOPICS_SOURCE_SHA256,
        source_byte_length=1,
        thesaurus=(first, second),
        ad_hoc=(),
    )
    identity_rows = federal_register_topic_source_identity_rows(
        snapshot,
    )
    first_id, second_id = (
        str(row["sourceRecordId"]) for row in identity_rows
    )

    assert first_id != second_id
    assert first.name == second.name
    assert first.slug == second.slug == ""


def test_duplicate_collection_and_ordinal_fail_without_label_fallback() -> None:
    first = _topic_record(
        source_ordinal=3,
        name="First name",
        slug="first-slug",
    )
    duplicate_locator = replace(
        first,
        name="A name that could have hidden the collision",
        slug="a-different-slug",
    )
    snapshot = FederalRegisterTopicsSnapshot(
        source_sha256=CURRENT_TOPICS_SOURCE_SHA256,
        source_byte_length=1,
        thesaurus=(first, duplicate_locator),
        ad_hoc=(),
    )
    record_ids = tuple(
        federal_register_topic_source_record_id(
            snapshot.source_sha256,
            item,
        )
        for item in snapshot.records
    )

    with pytest.raises(
        FederalRegisterTopicsReconciliationError,
        match=(
            "duplicate capture-local source locator.*names and slugs "
            "cannot disambiguate"
        ),
    ):
        federal_register_topic_source_identity_rows(snapshot)

    with pytest.raises(
        FederalRegisterTopicsReconciliationError,
        match="duplicate capture-local observation identifier",
    ):
        require_unique_capture_local_observation_ids(
            (
                (
                    snapshot.source_sha256,
                    first.collection,
                    first.source_ordinal,
                    record_ids[0],
                ),
                (
                    snapshot.source_sha256,
                    first.collection,
                    first.source_ordinal + 1,
                    record_ids[0],
                ),
            )
        )


@requires_exact_sources
def test_exact_sources_reproduce_checked_unresolved_evidence() -> None:
    proof = _proof()
    checked_evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert proof.evidence == checked_evidence
    assert proof.evidence["comparison"]["counts"] == (
        EXPECTED_COMPARISON_COUNTS
    )
    assert binding.validate([proof.record]) == []

    record = proof.record
    assert record["outcome"] == "unresolved"
    assert record["synthesizedUnionAuthorized"] is False
    assert record["conceptMappings"] == []
    assert "selectedInputRelease" not in record
    assert "reconciledRelease" not in record
    assert len(record["unresolvedItems"]) == 5


@requires_exact_sources
def test_exact_stage_counts_preserve_ad_hoc_as_a_distinct_collection() -> None:
    evidence = _proof().evidence
    historical_stages = {
        item["id"].rsplit(":", 1)[-1]: item
        for item in evidence["stageDigests"]["historical"]
    }
    current_stages = {
        item["id"].rsplit(":", 1)[-1]: item
        for item in evidence["stageDigests"]["current"]
    }

    assert historical_stages["source-entry-inventory"]["itemCount"] == 1_004
    assert (
        historical_stages["label-expression-inventory"]["itemCount"]
        == 1_553
    )
    assert (
        historical_stages["relation-assertion-inventory"]["itemCount"]
        == 1_496
    )
    assert (
        historical_stages[
            "unresolved-source-reference-inventory"
        ]["itemCount"]
        == 20
    )
    assert (
        current_stages["source-record-identity-inventory"]["itemCount"]
        == 7_767
    )
    assert current_stages["thesaurus-label-evidence"]["itemCount"] == 1_044
    assert (
        current_stages[
            "thesaurus-relation-assertion-inventory"
        ]["itemCount"]
        == 1_428
    )
    assert (
        current_stages[
            "ad-hoc-source-record-identity-inventory"
        ]["itemCount"]
        == 6_723
    )
    assert evidence["authorityBoundary"]["adHocCollectionTreatment"] == (
        "distinct"
    )


@requires_exact_sources
def test_unresolved_report_cannot_authorize_union_or_input_selection() -> None:
    proof = _proof()
    input_release = proof.report.inputs[0]["referenceResourceRelease"]
    invented_union = {
        "id": "urn:test:release:invented-union",
        "version": "development",
        "digest": "sha256:" + "2" * 64,
    }

    with pytest.raises(
        ReferenceRuntimeError,
        match="cannot authorize a synthesized union",
    ):
        replace(
            proof.report,
            reconciled_release=invented_union,
        ).sealed_payload()

    with pytest.raises(
        ReferenceRuntimeError,
        match="cannot select an input release",
    ):
        replace(
            proof.report,
            selected_input_release=input_release,
        ).sealed_payload()


@requires_exact_sources
def test_unresolved_report_cannot_authorize_selected_deployment() -> None:
    proof = _proof()
    proof_record = proof.record
    current_release = dict(
        proof.report.inputs[1]["referenceResourceRelease"]
    )
    decision, import_snapshot, coverage, output_profile = (
        _selected_deployment(proof_record, current_release)
    )

    with pytest.raises(
        ReferenceRuntimeError,
        match=(
            "selected registry deployment cannot use unresolved "
            "reconciliation"
        ),
    ):
        decision.sealed_payload(
            import_snapshot_record=import_snapshot,
            coverage_report_record=coverage,
            output_profile_record=output_profile,
            reconciliation_report_record=proof_record,
        )

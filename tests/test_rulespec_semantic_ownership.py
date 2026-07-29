"""Regressions for the RefSpec and Rulespec semantic ownership boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from refspec import (
    ConceptEventParticipant,
    ConceptLabel,
    ConceptRelation,
    EnrichmentProfile,
    OutputProfile,
    ReferenceRuntimeError,
    ReferenceRuntimeStore,
    binding,
    materialize_open_label_value_assertion,
    seal_payload,
)

NOW = "2026-07-29T12:00:00Z"
ACTOR = "urn:test:actor:semantic-ownership"
FACET = "urn:ref:facet:general-subject"
ROLE = "urn:rkaf:assignmentPrimary"
RELEASE = "urn:test:release:subjects"
IMPORT = "urn:test:import:subjects"
DISTRIBUTION = "urn:test:artifact:subjects"
FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "bindings"
    / "json"
    / "1.0"
    / "fixtures"
    / "valid"
)


def _versioned_reference(name: str) -> dict[str, str]:
    return {
        "id": f"urn:test:{name}",
        "version": "1",
        "digest": "sha256:" + "a" * 64,
    }


def _open_label_profile() -> OutputProfile:
    enrichment = EnrichmentProfile(
        profile_id="urn:test:enrichment-profile:semantic-ownership",
        version="1",
        recorded_at=NOW,
        recorded_by=ACTOR,
        operational_state="active",
        facets=(
            {
                "iri": FACET,
                "label": "General subject",
                "definition": "General subject matter.",
                "inclusionCues": ["subject"],
                "exclusionCues": ["not a subject"],
                "compatibleResourceRoutes": ["document"],
                "compatibleAssignmentPredicates": [ROLE],
            },
        ),
    )
    return OutputProfile(
        profile_id="urn:test:output-profile:semantic-ownership",
        version="1",
        recorded_at=NOW,
        recorded_by=ACTOR,
        operational_state="active",
        enrichment_profile=enrichment.reference,
        acceptance_policies=(
            _versioned_reference("acceptance-policy"),
        ),
        publication_views=(
            _versioned_reference("publication-view"),
        ),
        open_label_permissions=(
            {
                "facet": FACET,
                "assignmentRole": ROLE,
                "mode": "explicitLanguage",
                "candidateUse": True,
                "acceptedOutputUse": True,
            },
        ),
        enrichment_profile_record=enrichment,
    )


def _release_graph_receipt(
    *,
    publication: Mapping[str, Any],
) -> dict[str, Any]:
    return seal_payload(
        {
            "id": "urn:test:receipt:semantic-ownership",
            "type": "urn:ref:type:ReleaseGraphValidationReceipt",
            "recordedAt": NOW,
            "recordedBy": ACTOR,
            "schemaVersion": "1.0",
            "operationalState": "passed",
            "receiptVersion": "1.0",
            "rulespecDependencyManifest": {
                "id": "urn:test:rulespec-dependency",
                "digest": "sha256:" + "1" * 64,
            },
            "rulespecGraph": dict(publication["rulespecReleaseGraph"]),
            "refRecordDigests": [
                {
                    "id": publication["id"],
                    "digest": publication["canonicalPayloadDigest"],
                },
            ],
            "rulespecValidator": {
                "id": "urn:test:validator:rulespec",
                "revision": "test",
                "digest": "sha256:" + "2" * 64,
            },
            "rulespecBehaviorRuntime": {
                "id": "urn:test:runtime:rulespec-behavior",
                "revision": "test",
                "digest": "sha256:" + "5" * 64,
            },
            "gateImplementation": {
                "id": "urn:test:gate:combined",
                "revision": "test",
                "digest": "sha256:" + "3" * 64,
            },
            "verdicts": {
                "refBinding": "pass",
                "rulespecConformance": "pass",
                "rulespecBehavior": "pass",
                "crossBoundary": "pass",
            },
            "authorizationEvaluations": [],
            "coveredRulespecIdentifiers": [
                publication["rulespecReleaseGraph"]["id"],
            ],
            "crossReferencesDigest": "sha256:" + "4" * 64,
            "validatedAt": NOW,
            "activity": "urn:test:activity:validate-release",
        }
    )


def _validate_binding(
    records: Sequence[Mapping[str, Any]],
) -> None:
    diagnostics = binding.validate(list(records))
    if diagnostics:
        raise ReferenceRuntimeError(
            "binding rejected records: "
            + " | ".join(
                diagnostic.render() for diagnostic in diagnostics
            )
        )


def test_normalized_rows_preserve_rulespec_fields_without_local_enums() -> None:
    label = ConceptLabel(
        label_id="urn:test:label:future-role",
        concept_iri="urn:test:concept:one",
        scheme_iri="urn:test:scheme:one",
        release_iri=RELEASE,
        import_snapshot_id=IMPORT,
        distribution_artifact_id=DISTRIBUTION,
        source_property_iri="urn:test:property:future-label",
        label_role="futureRulespecLabelRole",
        original_literal="Future label",
        language_tag="en",
        status="futureRulespecStatus",
    )
    relation = ConceptRelation(
        relation_id="urn:test:relation:cross-scheme",
        release_iri=RELEASE,
        import_snapshot_id=IMPORT,
        distribution_artifact_id=DISTRIBUTION,
        subject_concept_iri="urn:test:concept:one",
        subject_scheme_iri="urn:test:scheme:one",
        predicate_iri="urn:test:predicate:future-relation",
        object_concept_iri="urn:test:concept:two",
        object_scheme_iri="urn:test:scheme:two",
        source_property_or_path="future:relation",
    )
    participant = ConceptEventParticipant(
        event_id="urn:test:event:future-operation",
        operation="futureRulespecOperation",
        participant_role="futureRulespecParticipantRole",
        concept_iri="urn:test:concept:one",
        concept_kind="futureRulespecConceptKind",
        release_iri=RELEASE,
        complete_membership=False,
        ordinal=0,
    )

    assert label.label_role == "futureRulespecLabelRole"
    assert label.status == "futureRulespecStatus"
    assert relation.subject_scheme_iri != relation.object_scheme_iri
    assert participant.operation == "futureRulespecOperation"
    assert participant.complete_membership is False


def test_open_label_builder_preserves_rulespec_terms_without_local_ranges() -> None:
    graph = materialize_open_label_value_assertion(
        output_profile=_open_label_profile(),
        facet=FACET,
        assignment_role=ROLE,
        resource_route="document",
        mode="explicitLanguage",
        declared_default_language=None,
        literal="Air quality",
        language_tag="en",
        assertion_id="urn:test:assertion:open-label",
        subject_iri="urn:test:artifact:one",
        extraction_activity_iri="urn:test:activity:extract",
        asserted_at=NOW,
        evidence_binding_id="urn:test:evidence:open-label",
        source_fragment_iris=("urn:test:fragment:one",),
        assertion_origin="urn:test:rulespec-origin:future",
        epistemic_basis="urn:test:rulespec-basis:future",
        evidence_role="urn:test:rulespec-evidence-role:future",
        ai_lineage_iri="urn:test:ai-lineage:one",
        usage_eligibility="urn:test:rulespec-usage:future",
    )

    assertion = graph["assertion"]
    evidence = graph["evidenceBinding"]
    assert assertion["rkaf:assertionOrigin"] == (
        "urn:test:rulespec-origin:future"
    )
    assert assertion["rkaf:epistemicBasis"] == (
        "urn:test:rulespec-basis:future"
    )
    assert assertion["rkaf:hasAILineage"] == "urn:test:ai-lineage:one"
    assert assertion["rkaf:usageEligibility"] == (
        "urn:test:rulespec-usage:future"
    )
    assert evidence["rkaf:evidenceRole"] == (
        "urn:test:rulespec-evidence-role:future"
    )


def test_complete_publication_store_requires_exact_gate_receipt(
    tmp_path: Path,
) -> None:
    fixture = json.loads(
        (FIXTURE_ROOT / "managed-release-minimal.json").read_text(
            encoding="utf-8"
        )
    )
    publication = next(
        dict(record)
        for record in fixture["records"]
        if record.get("type")
        == "urn:ref:type:PublicationReleaseManifest"
    )
    publication["releaseState"] = "complete"
    publication["consumerEligible"] = True
    publication = seal_payload(publication)
    store = ReferenceRuntimeStore(tmp_path)

    with pytest.raises(
        ReferenceRuntimeError,
        match="gate-issued ReleaseGraphValidationReceipt",
    ):
        store.put_record(
            "publication-release-manifest",
            publication,
            binding_validator=_validate_binding,
        )

    receipt = _release_graph_receipt(publication=publication)
    path = store.put_record(
        "publication-release-manifest",
        publication,
        binding_validator=_validate_binding,
        linked_records=(receipt,),
    )
    assert path.is_file()

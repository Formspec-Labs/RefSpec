"""End-to-end tests for the bounded Federal Register vocabulary slice."""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

import pytest

from refspec import binding
from refspec.managed_release import ManagedReleaseView
from refspec.registry.federal_register_thesaurus import (
    BROADER_PREDICATE_IRI,
    parse_federal_register_thesaurus,
)
from refspec.registry.federal_register_vertical_slice import (
    DEVELOPMENT_ENVIRONMENT_IRI,
    GRAPH_IRI,
    HISTORICAL_SOURCE_SHA256,
    SELECTED_DEPLOYMENT_IRI,
    SELECTION_ASSERTION_IRI,
    LocalCandidateGovernance,
    VerticalSliceError,
    build_federal_register_vertical_slice,
    build_from_verified_source,
    build_registry_selection_rollback_proof,
    reduce_registry_selection_history,
)
from refspec.vocabulary import RegistryDeploymentDecision, seal_payload

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESPEC_DIR = REFSPEC_ROOT.parents[1] / "rulespec"
FULL_SOURCE_ENV = "REFSPEC_FR_THESAURUS_1995_PATH"
RECORDED_AT = "2026-07-29T17:00:00Z"
RECORDED_BY = "urn:ref:agent:fr-thesaurus-test"

SYNTHETIC_THESAURUS = """FEDERAL REGISTER THESAURUS OF INDEXING TERMS
November 16, 1995

Alphabetic list of indexing terms, with references to preferred or
related terms:

Accidents
    see
          Safety
Accounting (02, 08)
     sa
          Uniform System of Accounts
      x
          Auditing
     xx
          Business and industry
          Law
Additives
    see
          Color additives
          Food additives
Business and industry (02)
Color additives (17)
Food additives (17)
     (The names of specific foods are not listed in this Thesaurus but
may be used as indexing terms.)
Law (08)
Safety (13)
Uniform System of Accounts (02)
Work Incentive Programs (WIN) (11)
"""


@pytest.fixture
def rulespec_dir() -> Path:
    configured = os.environ.get("RULESPEC_DIR")
    path = Path(configured).resolve() if configured else DEFAULT_RULESPEC_DIR.resolve()
    if not (path / ".git").exists():
        pytest.skip(f"live Rulespec checkout is unavailable: {path}")
    return path


def _build(rulespec_dir: Path):
    parsed = parse_federal_register_thesaurus(SYNTHETIC_THESAURUS)
    return build_federal_register_vertical_slice(
        parsed,
        rulespec_root=rulespec_dir,
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
    )


def _governance() -> LocalCandidateGovernance:
    return LocalCandidateGovernance(
        actor_iri="urn:ref:actor:spicy-regs-local-reviewer",
        organization_iri="urn:ref:organization:spicy-regs",
        effective_at=RECORDED_AT,
    )


def _build_selected(rulespec_dir: Path):
    parsed = parse_federal_register_thesaurus(SYNTHETIC_THESAURUS)
    return build_federal_register_vertical_slice(
        parsed,
        rulespec_root=rulespec_dir,
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        governance=_governance(),
    )


def test_slice_is_validated_but_stops_before_governed_selection(
    rulespec_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_networked(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"builder attempted network access: {args!r} {kwargs!r}")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_networked)
    bundle = _build(rulespec_dir)
    written = bundle.write_to(tmp_path)
    second_write = bundle.write_to(tmp_path)

    graph_nodes = bundle.rulespec_graph["@graph"]
    concepts = [node for node in graph_nodes if node.get("@type") == "rkaf:LocalConcept"]
    assert len(concepts) == 8
    assert not [
        node for node in graph_nodes if node.get("@type") == "rkaf:RegisteredConcept" or "rkaf:registeredAt" in node
    ]
    assert all(node["rkaf:definedInScope"].startswith("urn:ref:fr-thesaurus-1995:import-scope:") for node in concepts)

    assert len(bundle.normalized_labels) == 12
    assert len(bundle.normalized_relations) == 3
    assert sum(row["predicate_iri"] == BROADER_PREDICATE_IRI for row in bundle.normalized_relations) == 2
    assert len(bundle.indexed_expressions) == 21
    assert all("record=" in record["sourcePath"] for record in bundle.indexed_expressions)

    record_types = {record["type"] for record in bundle.operational_records}
    assert "urn:ref:type:RegistryReconciliationReport" not in record_types
    assert "urn:ref:type:RegistryDeploymentDecision" not in record_types
    run_receipt = next(record for record in bundle.operational_records if record["type"] == "urn:ref:type:RunReceipt")
    assert run_receipt["counts"]["officialSourceInputs"] == 1
    assert run_receipt["counts"]["reconciliationReports"] == 0
    assert run_receipt["counts"]["deploymentSelections"] == 0

    rights = next(record for record in bundle.operational_records if record["type"] == "urn:ref:type:RightsAssessment")
    assert set(rights["permissions"].values()) == {"permitted"}
    assert "accepts that uncertainty" in rights["purpose"]
    assert "not legal clearance" in rights["purpose"]
    assert rights["attestationRefs"] == []
    assert rights["localAdoptionRefs"] == []

    publication = bundle.publication_release_manifest
    assert publication["releaseState"] == "incomplete"
    assert publication["consumerEligible"] is False
    assert publication["deploymentClass"] == "developmentOnly"
    receipt = bundle.combined_validation_receipt
    assert receipt["type"] == "urn:ref:type:ReleaseGraphValidationReceipt"
    assert receipt["operationalState"] == "passed"
    assert set(receipt["verdicts"].values()) == {"pass"}
    assert receipt["rulespecGraph"]["id"] == GRAPH_IRI

    manifest = bundle.manifest()
    assert manifest["rulespecGraphId"] == GRAPH_IRI
    assert "rulespecDependencyManifest" in manifest
    assert "thesaurus-alpha.txt" not in written
    assert written == second_write


def test_slice_artifacts_are_byte_identical_for_the_same_pinned_inputs(
    rulespec_dir: Path,
) -> None:
    first = _build(rulespec_dir)
    second = _build(rulespec_dir)

    assert first.artifact_bytes() == second.artifact_bytes()


def test_local_selection_is_gate_authorized_and_rollback_is_separate(
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    active = _build_selected(rulespec_dir)
    active_dir = tmp_path / "active"
    active.write_to(active_dir)

    selected = next(
        record
        for record in active.operational_records
        if record.get("id") == SELECTED_DEPLOYMENT_IRI
    )
    assert selected["selectionState"] == "selected"
    assert "authorizationValidations" not in selected
    assert selected["rulespecAttestationRefs"]
    assert selected["localAdoptionRefs"]
    assert active.publication_release_manifest["releaseState"] == "complete"
    assert (
        active.publication_release_manifest["consumerEligible"] is True
    )
    run_receipt = next(
        record
        for record in active.operational_records
        if record["type"] == "urn:ref:type:RunReceipt"
    )
    assert run_receipt["counts"]["deploymentSelections"] == 1

    gate_receipt = active.combined_validation_receipt
    assert gate_receipt["verdicts"] == {
        "refBinding": "pass",
        "rulespecConformance": "pass",
        "rulespecBehavior": "pass",
        "crossBoundary": "pass",
    }
    evaluations = gate_receipt["authorizationEvaluations"]
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation["governanceRecord"] == {
        "id": selected["id"],
        "digest": selected["canonicalPayloadDigest"],
    }
    assert evaluation["subjectAssertion"] == SELECTION_ASSERTION_IRI
    assert evaluation["evaluationScope"] == DEVELOPMENT_ENVIRONMENT_IRI
    assert (
        evaluation["minimumUsageEligibility"]
        == "rkaf:localOperationalUse"
    )
    assert evaluation["effectiveUsageEligibility"] in {
        "rkaf:localOperationalUse",
        "rkaf:publicationAllowed",
        "rkaf:officialUse",
    }
    assert evaluation["runtime"] == gate_receipt[
        "rulespecBehaviorRuntime"
    ]
    assert evaluation["result"] == "pass"

    manifest_path = active_dir / "managed-release-bundle.json"
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=(
            "sha256:"
            + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        ),
    )
    assert len(tuple(view.iter_expressions())) == 21

    rollback = build_registry_selection_rollback_proof(
        active,
        rulespec_root=rulespec_dir,
    )
    rollback_dir = tmp_path / "rollback"
    rollback.write_to(rollback_dir)
    assert rollback.reduction.final_state == (
        rollback.reduction.initial_state
    )
    assert (
        rollback.reduction.state_digests[0]
        == rollback.reduction.state_digests[-1]
    )
    assert (
        rollback.rollback_decision["predecessor"]
        == evaluation["governanceRecord"]
    )
    assert set(
        rollback.combined_validation_receipt["verdicts"].values()
    ) == {"pass"}
    assert (
        rollback.combined_validation_receipt[
            "authorizationEvaluations"
        ][0]["governanceRecord"]
        == evaluation["governanceRecord"]
    )
    assert "rollback" not in str(active.manifest()).casefold()
    assert not list(active_dir.rglob("*rollback*"))
    assert (
        rollback_dir / "history/registry-deployment-rollback.json"
    ).is_file()

    records_by_type = {
        record["type"]: record for record in active.operational_records
    }
    coverage = records_by_type[
        "urn:ref:type:RegistryImportCoverageReport"
    ]
    output_profile = records_by_type["urn:ref:type:OutputProfile"]
    import_snapshot = records_by_type[
        "urn:ref:type:RegistryImportSnapshot"
    ]
    failed = RegistryDeploymentDecision(
        decision_id=(
            "urn:ref:fr-thesaurus-1995:"
            "registry-deployment:development-failed:v1"
        ),
        recorded_at="2026-07-29T17:00:01Z",
        recorded_by=RECORDED_BY,
        operational_state="developmentOnly",
        environment={
            "id": DEVELOPMENT_ENVIRONMENT_IRI,
            "classification": "development",
        },
        registry_import_snapshot={
            "id": import_snapshot["id"],
            "digest": import_snapshot["canonicalPayloadDigest"],
        },
        reference_resource_release=dict(
            selected["referenceResourceRelease"]
        ),
        coverage_report={
            "id": coverage["id"],
            "digest": coverage["canonicalPayloadDigest"],
        },
        output_profile={
            "id": output_profile["id"],
            "version": output_profile["version"],
            "digest": output_profile["contentDigest"],
        },
        selection_state="failed",
        effective_at="2026-07-29T17:00:01Z",
        reason=(
            "Synthetic failed selection attempt used to prove that failure "
            "cannot change the active release."
        ),
        activity=selected["activity"],
        rulespec_attestation_refs=(),
        local_adoption_refs=(),
        predecessor=evaluation["governanceRecord"],
    ).sealed_payload(
        coverage_report_record=coverage,
        output_profile_record=output_profile,
    )
    assert not binding.validate(
        [
            records_by_type["urn:ref:type:EnrichmentProfile"],
            output_profile,
            coverage,
            failed,
        ]
    )
    failed_reduction = reduce_registry_selection_history(
        [selected, failed]
    )
    selected_reduction = reduce_registry_selection_history([selected])
    assert (
        failed_reduction.final_state
        == selected_reduction.final_state
    )
    assert (
        failed_reduction.state_digests[-1]
        == selected_reduction.state_digests[-1]
    )


def test_local_builder_rejects_wrong_source_digest_before_writing(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "wrong.txt"
    source_path.write_text(SYNTHETIC_THESAURUS, encoding="utf-8")
    output_path = tmp_path / "output"

    with pytest.raises(VerticalSliceError, match="digest mismatch"):
        build_from_verified_source(
            source_path,
            output_path,
            rulespec_root=DEFAULT_RULESPEC_DIR,
            recorded_at=RECORDED_AT,
            recorded_by=RECORDED_BY,
        )

    assert not output_path.exists()


def _history_decision(
    *,
    identifier: str,
    selection_state: str,
    effective_at: str,
    predecessor: dict[str, str] | None = None,
) -> dict:
    decision = {
        "id": identifier,
        "type": "urn:ref:type:RegistryDeploymentDecision",
        "environment": {
            "id": DEVELOPMENT_ENVIRONMENT_IRI,
            "classification": "development",
        },
        "referenceResourceRelease": {
            "id": "urn:ref:release:test",
            "version": "1",
            "digest": "sha256:" + ("1" * 64),
        },
        "selectionState": selection_state,
        "effectiveAt": effective_at,
    }
    if predecessor is not None:
        decision["predecessor"] = predecessor
    return seal_payload(decision)


def test_selection_history_restores_empty_state_and_failed_event_is_noop() -> None:
    selected = _history_decision(
        identifier="urn:ref:deployment:test:selected",
        selection_state="selected",
        effective_at="2026-07-29T18:00:00Z",
    )
    selected_reference = {
        "id": selected["id"],
        "digest": selected["canonicalPayloadDigest"],
    }
    rollback = _history_decision(
        identifier="urn:ref:deployment:test:rollback",
        selection_state="deselected",
        effective_at="2026-07-29T18:01:00Z",
        predecessor=selected_reference,
    )
    reduction = reduce_registry_selection_history([selected, rollback])

    assert reduction.initial_state.selected_decision is None
    assert reduction.final_state == reduction.initial_state
    assert reduction.state_digests[0] == reduction.state_digests[-1]
    assert reduction.state_digests[1] != reduction.state_digests[0]

    failed = _history_decision(
        identifier="urn:ref:deployment:test:failed",
        selection_state="failed",
        effective_at="2026-07-29T18:01:00Z",
        predecessor=selected_reference,
    )
    failed_reduction = reduce_registry_selection_history([selected, failed])
    selected_only = reduce_registry_selection_history([selected])
    assert failed_reduction.final_state == selected_only.final_state
    assert failed_reduction.state_digests[-1] == selected_only.state_digests[-1]


@pytest.mark.skipif(
    not os.environ.get(FULL_SOURCE_ENV),
    reason=f"set {FULL_SOURCE_ENV} to the verified 1995 source",
)
def test_verified_full_source_build_closes_exact_historical_counts(
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    bundle = build_from_verified_source(
        Path(os.environ[FULL_SOURCE_ENV]),
        tmp_path / "active",
        rulespec_root=rulespec_dir,
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        governance=_governance(),
    )

    assert bundle.source_sha256 == HISTORICAL_SOURCE_SHA256
    assert len(bundle.normalized_labels) == 1_553
    assert len(bundle.normalized_relations) == 1_477
    assert len(bundle.indexed_expressions) == 2_213
    assert len(bundle.rulespec_graph["@graph"]) == 648
    assert bundle.publication_release_manifest["consumerEligible"] is True
    rollback = build_registry_selection_rollback_proof(
        bundle,
        rulespec_root=rulespec_dir,
    )
    rollback.write_to(tmp_path / "rollback")
    assert rollback.reduction.final_state == (
        rollback.reduction.initial_state
    )
    manifest_path = (
        tmp_path / "active" / "managed-release-bundle.json"
    )
    view = ManagedReleaseView.open(
        manifest_path,
        expected_manifest_digest=(
            "sha256:"
            + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        ),
    )
    assert len(tuple(view.iter_expressions())) == 2_213
    assert not list(tmp_path.rglob("thesaurus-alpha.txt"))

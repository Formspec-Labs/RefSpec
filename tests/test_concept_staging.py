"""Concept staging seals governed local authoring without minting identity."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

import refspec.atlas as atlas_api
import refspec.atlas.concept_staging as concept_staging_module
from refspec import binding, seal_payload
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
)
from refspec.atlas.concept_staging import (
    CONCEPT_AUTHORING_TRANSITION_TYPE,
    CONCEPT_AUTHORING_TRANSITION_VERSION,
    ConceptAuthoringSource,
    ConceptAuthoringTransition,
    ConceptStagingError,
    build_concept_authoring_transition,
    read_concept_authoring_transition,
)
from refspec.managed_release import ManagedReleaseGraphFactsView
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7
from refspec.release_graph import rulespec_graph_digest

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_concept_staging_managed_release_fixture",
    Path(__file__).with_name("test_managed_release_view.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_FIXTURE_SPEC)
sys.modules[_FIXTURE_SPEC.name] = _FIXTURE
_FIXTURE_SPEC.loader.exec_module(_FIXTURE)

AUTHORED_CONCEPT = _FIXTURE.ELIGIBILITY_MEMBER_ID
AUTHORING_ATTESTATION = "urn:rkaf:test:attestation:author-local-concept"
AUTHORITY = "https://refspec.org/authorities/subject-concept-minting"
ATTESTED_AT = "2026-08-04T18:00:00Z"
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64

CAPTURED_AT = "2026-08-04T12:00:00Z"
SOURCE_ID = "https://publisher.example/source/subjects.json"
SCHEME_ID = "https://publisher.example/schemes/subjects"


def _source_release() -> SourceConceptReleaseBundle:
    """One exact subject-ring source release the transition may cite."""

    payload = b'{"subjects":["oversight"]}\n'
    observation = {
        "id": "urn:ref:test:source-observation:subject-1",
        "sourceArtifact": SOURCE_ID,
        "sourcePath": "subjects/0",
        "sourceOrdinal": 0,
        "localRecordId": "urn:uuid:" + derive_uuid7(CAPTURED_AT, seed=b"concept-staging-test-concept"),
        "labels": [
            {
                "value": "Congressional oversight",
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
    }
    source = build_source_controlled_resource_bundle(
        resource_id="concept-staging-test-capture",
        title="Concept staging test capture",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=CAPTURED_AT,
        observations=(observation,),
        source_artifacts={SOURCE_ID: payload},
        source_scheme={
            "id": SCHEME_ID,
            "code": "concept-staging-test",
            "label": "Concept staging test scheme",
            "sourceArtifact": SOURCE_ID,
            "sourceFetchId": derive_uuid7(
                CAPTURED_AT,
                seed=b"concept-staging-test-source-fetch",
            ),
            "sourceObservedAt": CAPTURED_AT,
        },
    )
    return build_source_concept_release_bundle(
        source,
        semantic_ring="subject",
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": "urn:ref:test:source-concept-selection:v1",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": SOURCE_ID,
                "sourceDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            },
        ),
    )


def test_concept_authoring_is_part_of_the_atlas_governance_api() -> None:
    assert atlas_api.ConceptAuthoringTransition is ConceptAuthoringTransition
    assert atlas_api.build_concept_authoring_transition is build_concept_authoring_transition
    assert atlas_api.read_concept_authoring_transition is read_concept_authoring_transition


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _rewrite_json(path: Path, value: object) -> None:
    _FIXTURE._write_json(path, value)


def _reseal_graph(
    manifest_path: Path,
    *,
    attestor_kind: str = "rkaf:conceptMintingAuthority",
    decision: str = "rkaf:approved",
    target: str = AUTHORED_CONCEPT,
    revoked: bool = False,
    include_attestation: bool = True,
    include_authored_text: bool = True,
) -> None:
    """Update the fixture's exact graph and every dependent REF digest."""

    root = manifest_path.parent
    manifest = _json(manifest_path)
    graph_path = root / manifest["rulespecGraph"]["path"]
    graph = _json(graph_path)
    nodes = graph["@graph"]
    concept = next(node for node in nodes if node["@id"] == AUTHORED_CONCEPT)
    if include_authored_text:
        concept["skos:altLabel"] = {"en": ["Eligibility requirement", "Eligibility rule"]}
        concept["skos:definition"] = {"en": "A governed subject describing eligibility requirements."}
    if include_attestation:
        attestation = {
            "@id": AUTHORING_ATTESTATION,
            "@type": "rkaf:Attestation",
            "rkaf:attestor": AUTHORITY,
            "rkaf:attestorKind": attestor_kind,
            "rkaf:targets": [target],
            "rkaf:decision": decision,
            "rkaf:attestationScope": "urn:ref:scope:subject-concept-authoring",
            "rkaf:attestedAt": ATTESTED_AT,
            "rkaf:rationale": "The named vocabulary review completed every authoring gate.",
        }
        if revoked:
            attestation["rkaf:revokedAt"] = "2026-08-04T19:00:00Z"
        nodes.append(attestation)
    _rewrite_json(graph_path, graph)
    graph_digest = rulespec_graph_digest(graph)

    publication_path = root / manifest["publicationReleaseManifest"]["path"]
    publication = _json(publication_path)
    publication["rulespecReleaseGraph"]["digest"] = graph_digest
    publication = seal_payload(publication)
    _rewrite_json(publication_path, publication)

    receipt_path = root / manifest["combinedValidationReceipt"]["path"]
    receipt = _json(receipt_path)
    receipt["rulespecGraph"]["digest"] = graph_digest
    publication_reference = next(
        reference for reference in receipt["refRecordDigests"] if reference["id"] == publication["id"]
    )
    publication_reference["digest"] = publication["canonicalPayloadDigest"]
    if include_attestation:
        receipt["coveredRulespecIdentifiers"] = sorted([*receipt["coveredRulespecIdentifiers"], AUTHORING_ATTESTATION])
    receipt = seal_payload(receipt)
    _rewrite_json(receipt_path, receipt)

    manifest["rulespecGraph"] = _FIXTURE._descriptor(graph_path, root)
    manifest["publicationReleaseManifest"] = _FIXTURE._descriptor(
        publication_path,
        root,
    )
    manifest["combinedValidationReceipt"] = _FIXTURE._descriptor(
        receipt_path,
        root,
    )
    _rewrite_json(manifest_path, manifest)


def _managed_release(
    tmp_path: Path,
    *,
    name: str = "authored",
    ring: str = "subject",
    attestor_kind: str = "rkaf:conceptMintingAuthority",
    decision: str = "rkaf:approved",
    target: str = AUTHORED_CONCEPT,
    revoked: bool = False,
    include_attestation: bool = True,
    include_authored_text: bool = True,
) -> PinnedManagedConceptRelease:
    manifest_path = _FIXTURE.build_bundle(
        tmp_path / name,
        local_eligibility_concept=True,
    )
    _reseal_graph(
        manifest_path,
        attestor_kind=attestor_kind,
        decision=decision,
        target=target,
        revoked=revoked,
        include_attestation=include_attestation,
        include_authored_text=include_authored_text,
    )
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=_file_digest(manifest_path),
        release_id=_FIXTURE.RELEASE_ID,
        semantic_ring=ring,  # type: ignore[arg-type]
        assigned_by="https://refspec.org/actors/ring-reviewer",
        assigned_at=ATTESTED_AT,
        evidence=("urn:ref:test:evidence:subject-ring-assignment",),
    )
    assignment_path = assignment.write_to(tmp_path / f"{name}-ring.json")
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=_file_digest(assignment_path),
    )
    return PinnedManagedConceptRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
        release_id=_FIXTURE.RELEASE_ID,
        ring_assignment=pinned_assignment,
    )


def _proposal(*, accepted: bool = True) -> dict[str, Any]:
    fixture = _json(Path("bindings/json/1.0/fixtures/valid/concept-proposal.json"))
    proposal = fixture["records"][0]
    proposal["workflowState"] = "acceptedForPromotion" if accepted else "underReview"
    proposal["operationalState"] = proposal["workflowState"]
    proposal["canonicalPayloadDigest"] = binding.canonical_payload_digest(proposal)
    return proposal


def _rights() -> dict[str, Any]:
    fixture = _json(Path("bindings/json/1.0/fixtures/valid/managed-release-minimal.json"))
    return fixture["records"][0]


def _policy(name: str) -> dict[str, str]:
    return {
        "id": f"urn:ref:test:{name}:v1",
        "version": "1.0",
        "contentDigest": SHA_A if name == "governance-policy" else SHA_B,
    }


def _build(
    release: PinnedManagedConceptRelease,
    *,
    proposal: dict[str, Any] | None = None,
    source_concepts: tuple[ConceptAuthoringSource, ...] = (),
    authoring_kind: str = "newMeaning",
) -> ConceptAuthoringTransition:
    return build_concept_authoring_transition(
        _proposal() if proposal is None else proposal,
        release,
        authored_concept=AUTHORED_CONCEPT,
        authoring_attestation=AUTHORING_ATTESTATION,
        authoring_kind=authoring_kind,  # type: ignore[arg-type]
        source_concepts=source_concepts,
        inclusion_cues=("Programs with an explicit eligibility requirement.",),
        exclusion_cues=("General program descriptions without an eligibility rule.",),
        placement={"status": "topConcept"},
        duplicate_and_mapping_analysis=(
            "No source identity expresses the reviewed scope; close candidates remain separately mapped."
        ),
        evidence_policy=_policy("evidence-policy"),
        expected_assignment_effect=(
            "Future assignments may use the new identity; prior assignments retain their recorded origin."
        ),
        rights_assessment=_rights(),
        governance_policy=_policy("governance-policy"),
    )


def test_transition_seals_the_full_checklist_over_real_rulespec_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _managed_release(tmp_path)
    proposal = _proposal()
    original_open = ManagedReleaseGraphFactsView.open.__func__
    graph_fact_opens = 0

    def counted_open(
        cls: type[ManagedReleaseGraphFactsView],
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> ManagedReleaseGraphFactsView:
        nonlocal graph_fact_opens
        graph_fact_opens += 1
        return original_open(
            cls,
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )

    monkeypatch.setattr(
        ManagedReleaseGraphFactsView,
        "open",
        classmethod(counted_open),
    )
    transition = _build(release, proposal=proposal)
    assert graph_fact_opens == 1
    record = transition.as_record()

    assert record["type"] == CONCEPT_AUTHORING_TRANSITION_TYPE
    assert record["schemaVersion"] == CONCEPT_AUTHORING_TRANSITION_VERSION
    assert record["proposal"] == {
        "id": proposal["id"],
        "digest": proposal["canonicalPayloadDigest"],
    }
    assert record["authoredConcept"] == AUTHORED_CONCEPT
    assert record["authoredConceptRelease"]["releaseKind"] == ("managedReferenceRelease")
    assert record["authoringAttestation"] == {"id": AUTHORING_ATTESTATION}
    assert record["checklist"]["preferredLabels"] == {"en": "Eligibility policy"}
    assert record["checklist"]["alternateLabels"] == {"en": ["Eligibility requirement", "Eligibility rule"]}
    assert record["checklist"]["definition"] == {"en": ["A governed subject describing eligibility requirements."]}
    assert "decision" not in record
    assert "reviewer" not in record
    graph_fact_opens = 0
    transition.validate_context(
        proposal=proposal,
        authored_release=release,
        source_concepts=(),
        rights_assessment=_rights(),
    )
    assert graph_fact_opens == 1

    path = transition.write_to(tmp_path / "transition.json")
    reopened = read_concept_authoring_transition(path)
    assert reopened.as_record() == record
    assert reopened.artifact_bytes() == transition.artifact_bytes()
    with pytest.raises(TypeError):
        transition.record["authoredConcept"] = "urn:test:changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        transition.record = {}  # type: ignore[misc]


def test_source_context_opens_one_repeated_managed_release_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _managed_release(tmp_path)
    source = ConceptAuthoringSource(release, AUTHORED_CONCEPT)
    original_open = ManagedReleaseGraphFactsView.open.__func__
    graph_fact_opens = 0

    def counted_open(
        cls: type[ManagedReleaseGraphFactsView],
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> ManagedReleaseGraphFactsView:
        nonlocal graph_fact_opens
        graph_fact_opens += 1
        return original_open(
            cls,
            manifest_path,
            expected_manifest_digest=expected_manifest_digest,
        )

    monkeypatch.setattr(
        ManagedReleaseGraphFactsView,
        "open",
        classmethod(counted_open),
    )

    with pytest.raises(ConceptStagingError, match="repeat a concept identity"):
        concept_staging_module._source_context(
            (source, source),
            authored_concept="urn:ref:test:another-authored-concept",
            authoring_kind="consolidation",
            facts_by_release={},
        )

    assert graph_fact_opens == 1


def test_accepted_proposal_never_authorizes_automated_minting(tmp_path: Path) -> None:
    release = _managed_release(tmp_path, include_attestation=False)

    with pytest.raises(ConceptStagingError, match="authoringAttestation must resolve"):
        _build(release)

    under_review = _proposal(accepted=False)
    authorized_release = _managed_release(tmp_path, name="authorized")
    with pytest.raises(ConceptStagingError, match="acceptedForPromotion"):
        _build(authorized_release, proposal=under_review)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"attestor_kind": "rkaf:aiAgent"}, "concept-minting authority"),
        ({"decision": "rkaf:rejected"}, "must approve"),
        ({"target": _FIXTURE.MEMBER_ID}, "must target"),
        ({"revoked": True}, "revoked"),
    ],
)
def test_only_an_effective_concept_minting_attestation_completes_authoring(
    tmp_path: Path,
    changes: dict[str, Any],
    message: str,
) -> None:
    release = _managed_release(tmp_path, **changes)

    with pytest.raises(ConceptStagingError, match=message):
        _build(release)


def test_exact_local_concept_text_and_every_governance_gate_are_required(
    tmp_path: Path,
) -> None:
    missing_text = _managed_release(tmp_path, include_authored_text=False)
    with pytest.raises(ConceptStagingError, match="skos:altLabel must be an object"):
        _build(missing_text)

    release = _managed_release(tmp_path, name="complete-text")
    with pytest.raises(ConceptStagingError, match="inclusionCues must not be empty"):
        build_concept_authoring_transition(
            _proposal(),
            release,
            authored_concept=AUTHORED_CONCEPT,
            authoring_attestation=AUTHORING_ATTESTATION,
            authoring_kind="newMeaning",
            inclusion_cues=(),
            exclusion_cues=("Outside scope.",),
            placement={"status": "topConcept"},
            duplicate_and_mapping_analysis="Reviewed for duplicates and mappings.",
            evidence_policy=_policy("evidence-policy"),
            expected_assignment_effect="No prior assignment is rewritten.",
            rights_assessment=_rights(),
            governance_policy=_policy("governance-policy"),
        )


def test_existing_source_identity_is_cited_and_never_reminted(tmp_path: Path) -> None:
    release = _managed_release(tmp_path)
    source_release = _source_release()
    source_id = source_release.concepts[0]["id"]
    source = ConceptAuthoringSource(source_release, source_id)
    transition = _build(
        release,
        source_concepts=(source,),
        authoring_kind="splitRefinement",
    )

    assert transition.as_record()["sourceConcepts"][0]["conceptId"] == source_id
    transition.validate_context(
        proposal=_proposal(),
        authored_release=release,
        source_concepts=(source,),
        rights_assessment=_rights(),
    )

    with pytest.raises(ConceptStagingError, match="at least two source concepts"):
        _build(
            release,
            source_concepts=(source,),
            authoring_kind="consolidation",
        )

    forged = transition.as_record()
    forged["authoredConcept"] = source_id
    with pytest.raises(ConceptStagingError, match="must not reuse a cited source identity"):
        ConceptAuthoringTransition.from_record(forged)


def test_transition_rejects_non_subject_output_and_context_drift(tmp_path: Path) -> None:
    entity_release = _managed_release(tmp_path, ring="entity")
    with pytest.raises(ConceptStagingError, match="non-subject"):
        _build(entity_release)

    release = _managed_release(tmp_path, name="subject")
    transition = _build(release)
    changed_proposal = copy.deepcopy(_proposal())
    changed_proposal["wording"]["value"] = "Changed reviewed wording"
    changed_proposal["canonicalPayloadDigest"] = binding.canonical_payload_digest(changed_proposal)
    with pytest.raises(ConceptStagingError, match="names another proposal"):
        transition.validate_context(
            proposal=changed_proposal,
            authored_release=release,
            source_concepts=(),
            rights_assessment=_rights(),
        )


def test_transition_shape_and_digest_are_closed(tmp_path: Path) -> None:
    transition = _build(_managed_release(tmp_path))
    extra = transition.as_record()
    extra["approval"] = True
    with pytest.raises(ConceptStagingError, match="fields differ"):
        ConceptAuthoringTransition.from_record(extra)

    stale = transition.as_record()
    stale["checklist"]["expectedAssignmentEffect"] = "Rewrite prior assignments."
    with pytest.raises(ConceptStagingError, match="stale"):
        ConceptAuthoringTransition.from_record(stale)

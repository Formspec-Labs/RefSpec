"""Admission reviews authorize existing subject identities without re-minting."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from refspec import binding
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    SubjectConceptRelease,
)
from refspec.atlas.subject_admission import (
    SUBJECT_ADMISSION_ADMIT,
    SUBJECT_ADMISSION_REJECT,
    SubjectAdmissionError,
    SubjectAdmissionReview,
    admitted_subject_concept_ids,
    build_subject_admission_review,
    validate_subject_admission_reviews,
)
from refspec.atlas.subject_emission import (
    SubjectEmissionError,
    SubjectEmissionPolicy,
    SubjectEmissionPolicyResolution,
    build_subject_emission_policy,
    resolve_subject_emission_policy,
    subject_emission_eligibility,
)
from refspec.managed_release import ManagedReleaseGraphFactsView
from refspec.registry.infrastructure.semantic_foundation import EvidenceAssertion
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7
from refspec.vocabulary import EnrichmentProfile, OutputProfile, ReferenceRuntimeError

CAPTURED_AT = "2026-08-04T12:00:00Z"
REVIEWED_AT = "2026-08-04T16:00:00Z"
SOURCE_ID = "https://publisher.example/source/subjects.json"
SCHEME_ID = "https://publisher.example/schemes/subjects"
REVIEWER = "https://refspec.org/actors/reviewer-1"
FACET = "urn:ref:facet:public-policy"
PRODUCT_USE = "urn:ref:product-use:subject-emission"
ASSIGNMENT_ROLE = "https://rulespec.org/ns/v1#assignmentPrimary"
NORMAL_ACCEPTANCE_POLICY = {
    "id": "urn:ref:test:acceptance-policy:subject-extraction",
    "version": "2026-08-04",
    "digest": "sha256:" + "c" * 64,
}

_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_subject_admission_managed_release_fixture",
    Path(__file__).with_name("test_managed_release_view.py"),
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
sys.modules[_FIXTURE_SPEC.name] = _FIXTURE_MODULE
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
build_managed_bundle = _FIXTURE_MODULE.build_bundle
MANAGED_RELEASE_ID = _FIXTURE_MODULE.RELEASE_ID
MANAGED_LOCAL_CONCEPT_ID = _FIXTURE_MODULE.ELIGIBILITY_MEMBER_ID
MANAGED_REGISTERED_CONCEPT_ID = _FIXTURE_MODULE.MEMBER_ID


def _release(
    *,
    ring: str = "subject",
    payload: bytes = b'{"subjects":["oversight"]}\n',
) -> SourceConceptReleaseBundle:
    observation = {
        "id": "urn:ref:test:source-observation:subject-1",
        "sourceArtifact": SOURCE_ID,
        "sourcePath": "subjects/0",
        "sourceOrdinal": 0,
        "localRecordId": "urn:uuid:" + derive_uuid7(CAPTURED_AT, seed=b"subject-admission-test-concept"),
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
        resource_id="subject-admission-test-capture",
        title="Subject admission test capture",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=CAPTURED_AT,
        observations=(observation,),
        source_artifacts={SOURCE_ID: payload},
        source_scheme={
            "id": SCHEME_ID,
            "code": "subject-admission-test",
            "label": "Subject admission test scheme",
            "sourceArtifact": SOURCE_ID,
            "sourceFetchId": derive_uuid7(
                CAPTURED_AT,
                seed=b"subject-admission-test-source-fetch",
            ),
            "sourceObservedAt": CAPTURED_AT,
        },
    )
    return build_source_concept_release_bundle(
        source,
        semantic_ring=ring,  # type: ignore[arg-type]
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


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _managed_release(
    tmp_path: Path,
    *,
    local_eligibility_concept: bool = True,
    ring: str = "subject",
    name: str = "managed-subject",
) -> PinnedManagedConceptRelease:
    manifest = build_managed_bundle(
        tmp_path / name,
        local_eligibility_concept=local_eligibility_concept,
    )
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        semantic_ring=ring,  # type: ignore[arg-type]
        assigned_by="https://refspec.org/actors/portfolio-reviewer-1",
        assigned_at=REVIEWED_AT,
        evidence=("urn:ref:test:atlas-index:managed-subject-release",),
    )
    assignment_path = assignment.write_to(tmp_path / f"{name}-ring.json")
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=_file_digest(assignment_path),
    )
    return PinnedManagedConceptRelease.open(
        manifest,
        expected_manifest_digest=_file_digest(manifest),
        release_id=MANAGED_RELEASE_ID,
        ring_assignment=pinned_assignment,
    )


def _managed_rights(
    release: PinnedManagedConceptRelease,
    *,
    digest: str | None = None,
) -> tuple[dict[str, str], ...]:
    graph = release.pin()["rulespecGraph"]
    assert isinstance(graph, Mapping)
    return (
        {
            "type": "RightsMetadata",
            "rightsStatus": "notStated",
            "sourceArtifact": str(graph["id"]),
            "sourceDigest": str(graph["digest"] if digest is None else digest),
        },
    )


def _review_evidence(
    decision_iri: str,
    *,
    reviewer: str = REVIEWER,
) -> EvidenceAssertion:
    return EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by=reviewer,
        asserted_at=REVIEWED_AT,
        evidence=("urn:ref:test:evidence:editorial-workpaper-1",),
        review_decision=decision_iri,
    )


def _review(
    release: SubjectConceptRelease,
    *,
    decision: str = "admit",
    reviewer: str = REVIEWER,
    hierarchy_placement: Mapping[str, str] | None = None,
    subject_concept: str | None = None,
    rights_metadata: tuple[Mapping[str, Any], ...] | None = None,
) -> SubjectAdmissionReview:
    decision_iri = SUBJECT_ADMISSION_ADMIT if decision == "admit" else SUBJECT_ADMISSION_REJECT
    if subject_concept is None:
        assert isinstance(release, SourceConceptReleaseBundle)
        subject_concept = str(release.concepts[0]["id"])
    return build_subject_admission_review(
        release,
        subject_concept=subject_concept,
        decision=decision,  # type: ignore[arg-type]
        definition_or_scope_note="Government oversight exercised by a legislature.",
        hierarchy_placement=(
            {
                "status": "anchored",
                "relation": "narrowerThan",
                "anchor": "urn:ref:subject:government-operations",
            }
            if hierarchy_placement is None
            else hierarchy_placement
        ),
        facet=FACET,
        evidence_assertions=(_review_evidence(decision_iri, reviewer=reviewer),),
        reviewer=reviewer,
        reviewed_at=REVIEWED_AT,
        intended_product_uses=(PRODUCT_USE,),
        rights_metadata=rights_metadata,
    )


def _mapping_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {key for child in value.values() for key in _mapping_keys(child)}
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _mapping_keys(child)}
    return set()


def _emission_policy(
    release: SubjectConceptRelease,
    review: SubjectAdmissionReview,
) -> SubjectEmissionPolicy:
    return build_subject_emission_policy(
        release,
        (review,),
        version="2026-08-04",
        recorded_at=REVIEWED_AT,
        recorded_by=REVIEWER,
        eligibility=(
            subject_emission_eligibility(
                review,
                assignment_role=ASSIGNMENT_ROLE,
                intended_product_use=PRODUCT_USE,
            ),
        ),
    )


def _output_profile(
    policy: SubjectEmissionPolicy,
    *,
    candidate_use: bool = True,
    accepted_output_use: bool = True,
    include_permission: bool = True,
    operational_state: str = "active",
    permission_policy: Mapping[str, str] | None = None,
) -> OutputProfile:
    enrichment = EnrichmentProfile(
        profile_id="urn:ref:test:enrichment-profile:subject-emission",
        version="2026-08-04",
        recorded_at=REVIEWED_AT,
        recorded_by=REVIEWER,
        operational_state="active",
        facets=(
            {
                "iri": FACET,
                "label": "Public policy",
                "definition": "Government policy subject matter.",
                "inclusionCues": ["policy subject"],
                "exclusionCues": ["named organization"],
                "compatibleResourceRoutes": ["document"],
                "compatibleAssignmentPredicates": [ASSIGNMENT_ROLE],
            },
        ),
    )
    permission = {
        "facet": FACET,
        "assignmentRole": ASSIGNMENT_ROLE,
        "subjectEmissionPolicy": dict(policy.reference if permission_policy is None else permission_policy),
        "intendedProductUse": PRODUCT_USE,
        "candidateUse": candidate_use,
        "acceptedOutputUse": accepted_output_use,
    }
    return OutputProfile(
        profile_id="urn:ref:test:output-profile:subject-emission",
        version="2026-08-04",
        recorded_at=REVIEWED_AT,
        recorded_by=REVIEWER,
        operational_state=operational_state,
        enrichment_profile=enrichment.reference,
        acceptance_policies=(NORMAL_ACCEPTANCE_POLICY,),
        publication_views=(
            {
                "id": "urn:ref:test:publication-view:subject-emission",
                "version": "2026-08-04",
                "digest": "sha256:" + "a" * 64,
            },
        ),
        subject_admission_permissions=(permission,) if include_permission else (),
        enrichment_profile_record=enrichment,
    )


def test_admission_preserves_the_exact_source_identity_and_is_content_derived() -> None:
    release = _release()

    first = _review(release)
    second = _review(release)

    assert first == second
    assert first.identifier.endswith(first.record_digest.removeprefix("sha256:"))
    assert first.subject_concept == release.concepts[0]["id"]
    assert admitted_subject_concept_ids(release, (first,)) == (first.subject_concept,)
    assert SubjectAdmissionReview.from_record(first.as_record()) == first
    assert first.record["rightsMetadata"] == release.rights_metadata
    assert first.record["subjectConceptRelease"]["releaseKind"] == (
        "sourceConceptRelease"
    )
    assert "sourceConceptRelease" not in first.record
    assert "LocalConcept" not in str(first.as_record())
    assert not _mapping_keys(first.as_record()) & {
        "authorization",
        "emissionAuthorized",
        "permission",
        "productPolicy",
    }


def test_managed_local_identity_is_admitted_and_emitted_without_reminting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _managed_release(tmp_path)
    rights = _managed_rights(release)
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
    review = _review(
        release,
        subject_concept=MANAGED_LOCAL_CONCEPT_ID,
        rights_metadata=rights,
    )
    assert graph_fact_opens == 1
    graph_fact_opens = 0
    policy = _emission_policy(release, review)
    assert graph_fact_opens == 1
    graph_fact_opens = 0
    output_profile = _output_profile(policy)

    authorization = resolve_subject_emission_policy(
        output_profile=output_profile,
        policy=policy,
        release=release,
        admission_reviews=(review,),
        subject_concept=MANAGED_LOCAL_CONCEPT_ID,
        facet=FACET,
        assignment_role=ASSIGNMENT_ROLE,
        intended_product_use=PRODUCT_USE,
        resource_route="document",
    )
    assert graph_fact_opens == 1

    assert review.subject_concept == MANAGED_LOCAL_CONCEPT_ID
    graph_fact_opens = 0
    assert admitted_subject_concept_ids(release, (review,)) == (
        MANAGED_LOCAL_CONCEPT_ID,
    )
    assert graph_fact_opens == 1
    assert policy.record["subjectConceptRelease"]["releaseKind"] == (
        "managedReferenceRelease"
    )
    assert authorization.subject_concept == MANAGED_LOCAL_CONCEPT_ID
    assert authorization.subject_concept_release == release.pin()
    assert authorization.admission_review == review.reference
    assert "sourceConceptRelease" not in review.record
    assert "sourceConceptRelease" not in policy.record


def test_managed_admission_requires_local_type_subject_ring_and_exact_rights(
    tmp_path: Path,
) -> None:
    registered = _managed_release(
        tmp_path,
        local_eligibility_concept=False,
        name="managed-registered",
    )
    with pytest.raises(SubjectAdmissionError, match="rkaf:LocalConcept"):
        _review(
            registered,
            subject_concept=MANAGED_REGISTERED_CONCEPT_ID,
            rights_metadata=_managed_rights(registered),
        )

    entity = _managed_release(tmp_path, ring="entity", name="managed-entity")
    with pytest.raises(SubjectAdmissionError, match="non-subject"):
        _review(
            entity,
            subject_concept=MANAGED_LOCAL_CONCEPT_ID,
            rights_metadata=_managed_rights(entity),
        )

    subject = _managed_release(tmp_path, name="managed-wrong-rights")
    with pytest.raises(SubjectAdmissionError, match="exact Rulespec graph"):
        _review(
            subject,
            subject_concept=MANAGED_LOCAL_CONCEPT_ID,
            rights_metadata=_managed_rights(
                subject,
                digest="sha256:" + "0" * 64,
            ),
        )
    with pytest.raises(SubjectAdmissionError, match="explicit release-bound rights"):
        _review(
            subject,
            subject_concept=MANAGED_LOCAL_CONCEPT_ID,
        )


def test_managed_release_alone_never_admits_or_authorizes_a_local_concept(
    tmp_path: Path,
) -> None:
    release = _managed_release(tmp_path)

    assert admitted_subject_concept_ids(release, ()) == ()
    with pytest.raises(SubjectEmissionError, match="eligibility must be a non-empty"):
        build_subject_emission_policy(
            release,
            (),
            version="2026-08-04",
            recorded_at=REVIEWED_AT,
            recorded_by=REVIEWER,
            eligibility=(),
        )


def test_rejection_is_a_final_review_but_not_curated_tier_membership() -> None:
    release = _release()
    review = _review(release, decision="reject")

    assert validate_subject_admission_reviews(release, (review,)) == (review,)
    assert admitted_subject_concept_ids(release, (review,)) == ()


def test_review_is_valid_only_for_the_exact_content_derived_release() -> None:
    original = _release()
    changed = _release(payload=b'{"subjects":["oversight","review"]}\n')
    review = _review(original)

    with pytest.raises(SubjectAdmissionError, match="another exact release"):
        review.validate_for_release(changed)


def test_admission_rejects_non_subject_missing_concept_and_unmatched_review() -> None:
    subject = _release()
    entity = _release(ring="entity")

    with pytest.raises(SubjectAdmissionError, match="non-subject"):
        _review(entity)
    with pytest.raises(SubjectAdmissionError, match="outside the exact release"):
        build_subject_admission_review(
            subject,
            subject_concept="urn:ref:test:subject:missing",
            decision="admit",
            definition_or_scope_note="A missing source concept.",
            hierarchy_placement={"status": "unresolved", "reason": "No parent yet."},
            facet=FACET,
            evidence_assertions=(_review_evidence(SUBJECT_ADMISSION_ADMIT),),
            reviewer=REVIEWER,
            reviewed_at=REVIEWED_AT,
            intended_product_uses=(PRODUCT_USE,),
        )
    with pytest.raises(SubjectAdmissionError, match="matching humanReviewed"):
        build_subject_admission_review(
            subject,
            subject_concept=str(subject.concepts[0]["id"]),
            decision="admit",
            definition_or_scope_note="A valid source concept.",
            hierarchy_placement={"status": "unresolved", "reason": "No parent yet."},
            facet=FACET,
            evidence_assertions=(
                _review_evidence(
                    SUBJECT_ADMISSION_ADMIT,
                    reviewer="https://refspec.org/actors/other-reviewer",
                ),
            ),
            reviewer=REVIEWER,
            reviewed_at=REVIEWED_AT,
            intended_product_uses=(PRODUCT_USE,),
        )


def test_admission_shape_is_closed_and_hierarchy_placement_is_explicit() -> None:
    release = _release()

    with pytest.raises(SubjectAdmissionError, match="unsupported"):
        _review(
            release,
            hierarchy_placement={
                "status": "anchored",
                "relation": "sameAs",
                "anchor": "urn:ref:subject:government-operations",
            },
        )

    record: dict[str, Any] = _review(release).as_record()
    record["permission"] = "granted"
    with pytest.raises(SubjectAdmissionError, match="extra=.*permission"):
        SubjectAdmissionReview.from_record(record)


def test_one_concept_cannot_have_two_final_admission_decisions() -> None:
    release = _release()

    with pytest.raises(SubjectAdmissionError, match="multiple final decisions"):
        validate_subject_admission_reviews(
            release,
            (_review(release, decision="admit"), _review(release, decision="reject")),
        )


def test_admission_record_is_deeply_immutable() -> None:
    review = _review(_release())

    with pytest.raises(TypeError):
        review.record["decision"] = "reject"  # type: ignore[index]
    with pytest.raises(TypeError):
        review.record["hierarchyPlacement"]["status"] = "unresolved"  # type: ignore[index]
    assert isinstance(review.record["intendedProductUses"], tuple)


def test_exact_output_grant_resolves_the_existing_source_identity() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    output_profile = _output_profile(policy)

    authorization = resolve_subject_emission_policy(
        output_profile=output_profile,
        policy=policy,
        release=release,
        admission_reviews=(review,),
        subject_concept=review.subject_concept,
        facet=FACET,
        assignment_role=ASSIGNMENT_ROLE,
        intended_product_use=PRODUCT_USE,
        resource_route="document",
    )

    assert authorization.subject_concept == release.concepts[0]["id"]
    assert authorization.admission_review == review.reference
    assert authorization.emission_policy == policy.reference
    assert authorization.output_profile == output_profile.reference
    assert authorization.eligibility["subjectConcept"] == review.subject_concept
    assert authorization.output_permission["acceptedOutputUse"] is True
    assert authorization.resolution == "productPolicyAuthorized"
    assert dict(policy.reference) not in output_profile.acceptance_policies
    assert SubjectEmissionPolicy.from_record(policy.as_record()) == policy
    assert "LocalConcept" not in str(authorization)


def test_subject_emission_resolution_is_resolver_only() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    authorization = resolve_subject_emission_policy(
        output_profile=_output_profile(policy),
        policy=policy,
        release=release,
        admission_reviews=(review,),
        subject_concept=review.subject_concept,
        facet=FACET,
        assignment_role=ASSIGNMENT_ROLE,
        intended_product_use=PRODUCT_USE,
        resource_route="document",
    )

    with pytest.raises(SubjectEmissionError, match="only be created by resolve_subject_emission_policy"):
        SubjectEmissionPolicyResolution(
            subject_concept=authorization.subject_concept,
            facet=authorization.facet,
            assignment_role=authorization.assignment_role,
            intended_product_use=authorization.intended_product_use,
            subject_concept_release=authorization.subject_concept_release,
            admission_review=authorization.admission_review,
            emission_policy=authorization.emission_policy,
            output_profile=authorization.output_profile,
            eligibility=authorization.eligibility,
            output_permission=authorization.output_permission,
        )

    with pytest.raises(SubjectEmissionError, match="only be created by resolve_subject_emission_policy"):
        replace(authorization, output_permission=authorization.output_permission)


def test_admission_policy_alone_never_grants_product_use() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)

    with pytest.raises(SubjectEmissionError, match="authorization must match"):
        resolve_subject_emission_policy(
            output_profile=_output_profile(policy, include_permission=False),
            policy=policy,
            release=release,
            admission_reviews=(review,),
            subject_concept=review.subject_concept,
            facet=FACET,
            assignment_role=ASSIGNMENT_ROLE,
            intended_product_use=PRODUCT_USE,
            resource_route="document",
        )


def test_candidate_only_permission_cannot_authorize_accepted_output() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)

    with pytest.raises(SubjectEmissionError, match="acceptedOutputUse=true"):
        resolve_subject_emission_policy(
            output_profile=_output_profile(policy, accepted_output_use=False),
            policy=policy,
            release=release,
            admission_reviews=(review,),
            subject_concept=review.subject_concept,
            facet=FACET,
            assignment_role=ASSIGNMENT_ROLE,
            intended_product_use=PRODUCT_USE,
            resource_route="document",
        )


def test_output_profile_rejects_accepted_use_without_candidate_use() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)

    with pytest.raises(ReferenceRuntimeError, match="requires candidate permission"):
        _output_profile(
            policy,
            candidate_use=False,
            accepted_output_use=True,
        ).payload()


def test_output_grant_must_pin_the_same_exact_eligibility_policy() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    other_policy = {
        "id": "urn:ref:test:subject-emission-policy:other",
        "version": "2026-08-04",
        "digest": "sha256:" + "b" * 64,
    }

    output_profile = _output_profile(policy, permission_policy=other_policy)
    output_profile.payload()

    with pytest.raises(SubjectEmissionError, match="authorization must match"):
        resolve_subject_emission_policy(
            output_profile=output_profile,
            policy=policy,
            release=release,
            admission_reviews=(review,),
            subject_concept=review.subject_concept,
            facet=FACET,
            assignment_role=ASSIGNMENT_ROLE,
            intended_product_use=PRODUCT_USE,
            resource_route="document",
        )


def test_output_profile_rejects_duplicate_subject_grant_selectors() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    output_profile = _output_profile(policy)
    first = output_profile.subject_admission_permissions[0]

    with pytest.raises(ReferenceRuntimeError, match="duplicate permission selector"):
        replace(
            output_profile,
            subject_admission_permissions=(
                first,
                {**first, "acceptedOutputUse": False},
            ),
        ).payload()


def test_json_binding_checks_shape_but_never_claims_full_subject_authorization() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    output_profile = _output_profile(policy)
    enrichment = output_profile.enrichment_profile_record
    assert enrichment is not None
    output_record = output_profile.sealed_payload()
    enrichment_record = enrichment.sealed_payload()
    permission_check = {
        "id": "urn:ref:test:permission-check:subject-emission",
        "profile": output_profile.profile_id,
        "kind": "subjectAdmission",
        "use": "acceptedOutput",
        "resourceRoute": "document",
        "tuple": {
            "facet": FACET,
            "assignmentRole": ASSIGNMENT_ROLE,
            "subjectEmissionPolicy": dict(policy.reference),
            "intendedProductUse": PRODUCT_USE,
        },
        "claimedAuthorized": True,
    }

    assert binding.validate([enrichment_record, output_record]) == []
    diagnostics = binding.validate(
        [enrichment_record, output_record],
        permission_checks=[permission_check],
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].requirement == "REF-TEST-150"
    assert "unknown permission-check kind 'subjectAdmission'" in diagnostics[0].message


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("subject_concept", "urn:ref:test:subject:unreviewed"),
        ("facet", "urn:ref:facet:other"),
        ("assignment_role", "https://rulespec.org/ns/v1#assignmentSecondary"),
        ("intended_product_use", "urn:ref:product-use:other"),
    ),
)
def test_subject_emission_requires_the_exact_reviewed_scope(
    field: str,
    value: str,
) -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    arguments = {
        "subject_concept": review.subject_concept,
        "facet": FACET,
        "assignment_role": ASSIGNMENT_ROLE,
        "intended_product_use": PRODUCT_USE,
    }
    arguments[field] = value

    with pytest.raises(SubjectEmissionError):
        resolve_subject_emission_policy(
            output_profile=_output_profile(policy),
            policy=policy,
            release=release,
            admission_reviews=(review,),
            resource_route="document",
            **arguments,
        )


def test_subject_emission_rejects_stale_release_review_and_inactive_profile() -> None:
    release = _release()
    changed_release = _release(payload=b'{"subjects":["oversight","review"]}\n')
    review = _review(release)
    policy = _emission_policy(release, review)
    common = {
        "policy": policy,
        "subject_concept": review.subject_concept,
        "facet": FACET,
        "assignment_role": ASSIGNMENT_ROLE,
        "intended_product_use": PRODUCT_USE,
        "resource_route": "document",
    }

    with pytest.raises(SubjectEmissionError, match="another exact release"):
        resolve_subject_emission_policy(
            output_profile=_output_profile(policy),
            release=changed_release,
            admission_reviews=(review,),
            **common,
        )

    changed_review = _review(
        release,
        hierarchy_placement={
            "status": "unresolved",
            "reason": "A different review result.",
        },
    )
    with pytest.raises(SubjectEmissionError, match="exactly its pinned admission review set"):
        resolve_subject_emission_policy(
            output_profile=_output_profile(policy),
            release=release,
            admission_reviews=(changed_review,),
            **common,
        )

    with pytest.raises(SubjectEmissionError, match="active OutputProfile"):
        resolve_subject_emission_policy(
            output_profile=_output_profile(policy, operational_state="inactive"),
            release=release,
            admission_reviews=(review,),
            **common,
        )


def test_rejection_cannot_enter_subject_emission_policy() -> None:
    release = _release()
    review = _review(release, decision="reject")

    with pytest.raises(SubjectEmissionError, match="rejected review"):
        subject_emission_eligibility(
            review,
            assignment_role=ASSIGNMENT_ROLE,
            intended_product_use=PRODUCT_USE,
        )


def test_subject_emission_policy_and_authorization_are_deeply_immutable() -> None:
    release = _release()
    review = _review(release)
    policy = _emission_policy(release, review)
    authorization = resolve_subject_emission_policy(
        output_profile=_output_profile(policy),
        policy=policy,
        release=release,
        admission_reviews=(review,),
        subject_concept=review.subject_concept,
        facet=FACET,
        assignment_role=ASSIGNMENT_ROLE,
        intended_product_use=PRODUCT_USE,
        resource_route="document",
    )

    with pytest.raises(TypeError):
        policy.record["eligibility"][0]["subjectConcept"] = "urn:ref:changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        authorization.output_permission["acceptedOutputUse"] = False  # type: ignore[index]
    with pytest.raises(SubjectEmissionError, match="only be created by resolve_subject_emission_policy"):
        replace(
            authorization,
            output_permission={
                **authorization.output_permission,
                "acceptedOutputUse": False,
            },
        )

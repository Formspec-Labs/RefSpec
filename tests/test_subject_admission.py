"""Admission reviews authorize existing subject identities without re-minting."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest

from refspec.atlas.subject_admission import (
    SUBJECT_ADMISSION_ADMIT,
    SUBJECT_ADMISSION_REJECT,
    SubjectAdmissionError,
    SubjectAdmissionReview,
    admitted_subject_concept_ids,
    build_subject_admission_review,
    validate_subject_admission_reviews,
)
from refspec.registry.infrastructure.semantic_foundation import EvidenceAssertion
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

CAPTURED_AT = "2026-08-04T12:00:00Z"
REVIEWED_AT = "2026-08-04T16:00:00Z"
SOURCE_ID = "https://publisher.example/source/subjects.json"
SCHEME_ID = "https://publisher.example/schemes/subjects"
REVIEWER = "https://refspec.org/actors/reviewer-1"
FACET = "urn:ref:facet:public-policy"
PRODUCT_USE = "urn:ref:product-use:subject-emission"


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
        "localRecordId": "urn:uuid:"
        + derive_uuid7(CAPTURED_AT, seed=b"subject-admission-test-concept"),
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


def _review_evidence(
    decision_iri: str,
    *,
    reviewer: str = REVIEWER,
) -> EvidenceAssertion:
    return EvidenceAssertion(
        identifier=f"urn:ref:test:subject-admission-evidence:{decision_iri.rsplit(':', 1)[-1]}",
        semantic_ring="subject",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by=reviewer,
        asserted_at=REVIEWED_AT,
        evidence=("urn:ref:test:evidence:editorial-workpaper-1",),
        review_decision=decision_iri,
    )


def _review(
    release: SourceConceptReleaseBundle,
    *,
    decision: str = "admit",
    reviewer: str = REVIEWER,
    hierarchy_placement: Mapping[str, str] | None = None,
) -> SubjectAdmissionReview:
    decision_iri = (
        SUBJECT_ADMISSION_ADMIT if decision == "admit" else SUBJECT_ADMISSION_REJECT
    )
    return build_subject_admission_review(
        release,
        subject_concept=str(release.concepts[0]["id"]),
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
    )


def _mapping_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key for child in value.values() for key in _mapping_keys(child)
        }
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _mapping_keys(child)}
    return set()


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
    assert "LocalConcept" not in str(first.as_record())
    assert not _mapping_keys(first.as_record()) & {
        "authorization",
        "emissionAuthorized",
        "permission",
        "productPolicy",
    }


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

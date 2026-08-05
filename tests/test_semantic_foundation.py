"""The four semantic rings share immutable records but keep relation meaning separate."""

from __future__ import annotations

from dataclasses import replace

import pytest

from refspec.registry.infrastructure.semantic_foundation import (
    ENTITY_SAME_IDENTITY,
    EVIDENCE_USE_CEILINGS,
    LEGAL_CITES,
    SUBJECT_BROAD_MATCH,
    SUBJECT_EXACT_MATCH,
    VALUE_EXACT_CROSSWALK,
    EvidenceAssertion,
    MappingAssertion,
    RightsMetadata,
    SemanticFoundationError,
    validate_evidence_assertions,
    validate_mapping_assertions,
    validate_rights_metadata,
    validate_rights_metadata_records,
)

ASSERTED_AT = "2026-08-04T14:00:00Z"
DIGEST = "sha256:" + "a" * 64


def _human(*, ring: str = "subject", decision: str = "review-1") -> EvidenceAssertion:
    return EvidenceAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/reviewer-1",
        asserted_at=ASSERTED_AT,
        evidence=(f"urn:ref:test:evidence:{ring}:{decision}:workpaper",),
        review_decision=f"urn:ref:test:decision:{ring}:{decision}",
    )


def _publisher(*, ring: str = "subject") -> EvidenceAssertion:
    return EvidenceAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        evidence_class="publisherAsserted",
        basis="publisherCrosswalk",
        asserted_by="https://publisher.example/",
        asserted_at=ASSERTED_AT,
        evidence=(f"urn:ref:test:evidence:{ring}:publisher-row",),
        source_artifact=f"https://publisher.example/source/{ring}-crosswalk.json",
        source_digest=DIGEST,
    )


def _machine(
    *,
    evidence_class: str = "machineQualified",
    ring: str = "subject",
    relation: str = SUBJECT_EXACT_MATCH,
) -> EvidenceAssertion:
    common = {
        "semantic_ring": ring,
        "evidence_class": evidence_class,
        "basis": "statisticalInference",
        "asserted_by": "https://refspec.org/software/qualification-runner-v2",
        "asserted_at": ASSERTED_AT,
        "evidence": (f"urn:ref:test:proof:{ring}:{evidence_class}",),
        "candidate": f"urn:ref:test:candidate:{ring}:{evidence_class}",
        "machine_proof": f"urn:ref:test:proof:{ring}:{evidence_class}",
        "source_concept": f"urn:ref:test:concept:{ring}:source",
        "target_concept": f"urn:ref:test:concept:{ring}:target",
        "source_release": f"urn:ref:test:release:{ring}:source",
        "target_release": f"urn:ref:test:release:{ring}:target",
        "relation": relation,
    }
    if evidence_class == "machineQualified":
        return EvidenceAssertion(
            validation_receipts=(
                f"urn:ref:test:validation:{ring}:one",
                f"urn:ref:test:validation:{ring}:two",
            ),
            **common,  # type: ignore[arg-type]
        )
    return EvidenceAssertion(
        validation_receipts=(f"urn:ref:test:validation:{ring}:one",),
        **common,  # type: ignore[arg-type]
    )


def _mapping(
    *,
    ring: str,
    relation: str,
    evidence: tuple[str, ...],
    context: dict[str, str] | None = None,
) -> MappingAssertion:
    return MappingAssertion(
        semantic_ring=ring,  # type: ignore[arg-type]
        source_concept=f"urn:ref:test:concept:{ring}:source",
        target_concept=f"urn:ref:test:concept:{ring}:target",
        source_release=f"urn:ref:test:release:{ring}:source",
        target_release=f"urn:ref:test:release:{ring}:target",
        relation=relation,
        evidence=evidence,
        asserted_at=ASSERTED_AT,
        context=context,
    )


@pytest.mark.parametrize("semantic_ring", ([], {}))
def test_malformed_semantic_ring_is_a_domain_error(
    semantic_ring: object,
) -> None:
    with pytest.raises(
        SemanticFoundationError,
        match="must be subject, entity, value, or legalIdentity",
    ):
        EvidenceAssertion(
            semantic_ring=semantic_ring,  # type: ignore[arg-type]
            evidence_class="humanReviewed",
            basis="editorialReview",
            asserted_by="https://refspec.org/actors/reviewer-1",
            asserted_at=ASSERTED_AT,
            evidence=("urn:ref:test:evidence:malformed-ring",),
            review_decision="urn:ref:test:decision:malformed-ring",
        )


def test_rights_metadata_represents_facts_and_canonicalizes_holders() -> None:
    stated = RightsMetadata(
        rights_status="stated",
        rights_statement="https://publisher.example/terms",
        source_artifact="https://publisher.example/source/terms.json",
        source_digest=DIGEST,
        license="https://creativecommons.org/licenses/by/4.0/",
        rights_holders=("Publisher B", "Publisher A"),
        attribution="Example Publisher vocabulary",
    )
    not_stated = validate_rights_metadata(
        {
            "type": "RightsMetadata",
            "rightsStatus": "notStated",
            "sourceArtifact": "https://publisher.example/source/other.json",
            "sourceDigest": "sha256:" + "b" * 64,
        }
    )

    assert stated.as_record()["rightsHolders"] == ["Publisher A", "Publisher B"]
    assert (
        RightsMetadata(
            rights_status="stated",
            rights_statement="https://publisher.example/terms",
            source_artifact="https://publisher.example/source/terms.json",
            source_digest=DIGEST,
            rights_holders=("Publisher A", "Publisher B"),
        ).rights_holders
        == stated.rights_holders
    )
    assert [value.source_artifact for value in validate_rights_metadata_records((not_stated, stated))] == [
        "https://publisher.example/source/other.json",
        "https://publisher.example/source/terms.json",
    ]

    with pytest.raises(SemanticFoundationError, match="cannot imply unstated"):
        RightsMetadata(
            rights_status="notStated",
            source_artifact="https://publisher.example/source/terms.json",
            source_digest=DIGEST,
            license="https://creativecommons.org/licenses/by/4.0/",
        )


def test_all_evidence_classes_have_closed_content_derived_shapes() -> None:
    reviewed = _machine(evidence_class="machineReviewed")
    assertions = validate_evidence_assertions(
        (
            _machine(),
            reviewed,
            _publisher(),
            EvidenceAssertion(
                semantic_ring="subject",
                evidence_class="operatorAdopted",
                basis="operatorDirection",
                asserted_by="https://refspec.org/actors/operator-1",
                asserted_at=ASSERTED_AT,
                evidence=("urn:ref:test:evidence:operator-decision",),
                adopted_evidence=reviewed.identifier,
            ),
            _human(),
            EvidenceAssertion(
                semantic_ring="subject",
                evidence_class="ruleGenerated",
                basis="deterministicDerivation",
                asserted_by="https://refspec.org/software/generator-v1",
                asserted_at=ASSERTED_AT,
                evidence=("urn:ref:test:evidence:generator-run",),
                generator="urn:ref:test:generator:lexical-v1",
                generator_inputs=("urn:ref:test:generator-input:one",),
            ),
        ),
        semantic_ring="subject",
    )

    assert {value.evidence_class for value in assertions} == set(EVIDENCE_USE_CEILINGS)
    assert all(value.identifier.startswith("urn:ref:evidence-assertion:subject:") for value in assertions)
    assert all(EvidenceAssertion.from_record(value.as_record()) == value for value in assertions)
    assert {value.evidence_class: value.use_ceiling for value in assertions} == dict(EVIDENCE_USE_CEILINGS)


def test_machine_shape_binds_candidate_endpoints_relation_and_rejects_proof_labels() -> None:
    assertion = _machine()

    assert assertion.relation == SUBJECT_EXACT_MATCH
    assert assertion.as_record()["machineProof"] == assertion.machine_proof
    assert assertion.as_record()["contentDigest"] == assertion.content_digest

    with pytest.raises(SemanticFoundationError, match="unknown fields"):
        EvidenceAssertion.from_record({**assertion.as_record(), "proofStatus": "callerSelected"})
    with pytest.raises(SemanticFoundationError, match="requires machineProof"):
        replace(assertion, machine_proof=None)
    with pytest.raises(SemanticFoundationError, match="at least 2 unique IRIs"):
        replace(assertion, validation_receipts=("urn:ref:test:validation:one",))


def test_evidence_and_mapping_ids_change_with_content_and_reject_aliases() -> None:
    first = _human(decision="first")
    second = _human(decision="second")
    mapping = _mapping(ring="subject", relation=SUBJECT_EXACT_MATCH, evidence=(first.identifier,))

    assert first.identifier != second.identifier
    assert mapping.identifier.startswith("urn:ref:mapping-assertion:subject:")
    assert mapping.lifecycle_status == "current"
    assert mapping.supersedes == ()
    assert mapping.as_record()["lifecycleStatus"] == "current"
    assert mapping.as_record()["supersedes"] == []
    assert MappingAssertion.from_record(mapping.as_record()) == mapping

    evidence_alias = {**first.as_record(), "id": "urn:ref:test:mutable-alias"}
    with pytest.raises(SemanticFoundationError, match="content identity"):
        EvidenceAssertion.from_record(evidence_alias)
    mapping_alias = {**mapping.as_record(), "id": "urn:ref:test:mutable-mapping-alias"}
    with pytest.raises(SemanticFoundationError, match="content identity"):
        MappingAssertion.from_record(mapping_alias)

    legacy = mapping.as_record()
    del legacy["lifecycleStatus"]
    del legacy["supersedes"]
    with pytest.raises(SemanticFoundationError, match="missing fields"):
        MappingAssertion.from_record(legacy)


def test_mapping_supersession_is_content_derived_closed_and_preserves_disagreement() -> None:
    evidence = _human()
    prior = _mapping(
        ring="subject",
        relation=SUBJECT_EXACT_MATCH,
        evidence=(evidence.identifier,),
    )
    successor = replace(
        prior,
        asserted_at="2026-08-04T14:01:00Z",
        supersedes=(prior.identifier,),
    )
    contradictory = replace(
        prior,
        relation=SUBJECT_BROAD_MATCH,
        asserted_at="2026-08-04T14:02:00Z",
    )

    assertions = validate_mapping_assertions(
        (contradictory, successor, prior),
        evidence_assertions=(evidence,),
    )

    assert {value.identifier for value in assertions} == {
        prior.identifier,
        successor.identifier,
        contradictory.identifier,
    }
    assert successor.as_record()["supersedes"] == [prior.identifier]
    assert successor.identifier != prior.identifier

    with pytest.raises(SemanticFoundationError, match="must be current"):
        replace(prior, lifecycle_status="withdrawn")  # type: ignore[arg-type]
    with pytest.raises(SemanticFoundationError, match="unknown prior assertions"):
        validate_mapping_assertions(
            (replace(successor, supersedes=("urn:ref:mapping-assertion:subject:missing",)),),
            evidence_assertions=(evidence,),
        )
    with pytest.raises(SemanticFoundationError, match="asserted after"):
        validate_mapping_assertions(
            (prior, replace(prior, supersedes=(prior.identifier,))),
            evidence_assertions=(evidence,),
        )


def test_use_ceiling_is_derived_and_never_caller_selected() -> None:
    publisher = _publisher()
    assert publisher.use_ceiling == "searchOnly"

    changed = {**publisher.as_record(), "useCeiling": "localOperationalUse"}
    with pytest.raises(SemanticFoundationError, match="derived from evidenceClass"):
        EvidenceAssertion.from_record(changed)


def test_subject_exact_match_is_a_mapping_and_never_identity() -> None:
    evidence = _human()
    mapping = _mapping(ring="subject", relation=SUBJECT_EXACT_MATCH, evidence=(evidence.identifier,))
    assertion = validate_mapping_assertions(
        (mapping,),
        evidence_assertions=(evidence,),
        semantic_ring="subject",
    )[0]

    assert assertion.relation == SUBJECT_EXACT_MATCH
    assert assertion.as_record()["type"] == "MappingAssertion"
    with pytest.raises(SemanticFoundationError, match="not valid for the subject ring"):
        replace(mapping, relation=ENTITY_SAME_IDENTITY)


def test_machine_evidence_cannot_be_reused_for_another_relation() -> None:
    evidence = _machine()
    exact = _mapping(ring="subject", relation=SUBJECT_EXACT_MATCH, evidence=(evidence.identifier,))
    with pytest.raises(SemanticFoundationError, match="path-backed RelationAssertionBundle"):
        validate_mapping_assertions((exact,), evidence_assertions=(evidence,))

    broad = replace(exact, relation=SUBJECT_BROAD_MATCH)
    with pytest.raises(SemanticFoundationError, match="path-backed RelationAssertionBundle"):
        validate_mapping_assertions((broad,), evidence_assertions=(evidence,))


def test_entity_identity_requires_more_than_name_or_statistical_similarity() -> None:
    generated = EvidenceAssertion(
        semantic_ring="entity",
        evidence_class="ruleGenerated",
        basis="nameEquality",
        asserted_by="https://refspec.org/software/name-generator-v1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:entity-name-input",),
        generator="urn:ref:test:generator:normalized-name-v1",
        generator_inputs=("urn:ref:test:entity-name:one",),
    )
    mapping = _mapping(ring="entity", relation=ENTITY_SAME_IDENTITY, evidence=(generated.identifier,))
    with pytest.raises(SemanticFoundationError, match="name equality"):
        validate_mapping_assertions((mapping,), evidence_assertions=(generated,))

    machine = _machine(ring="entity", relation=ENTITY_SAME_IDENTITY)
    with pytest.raises(SemanticFoundationError, match="path-backed RelationAssertionBundle"):
        validate_mapping_assertions(
            (replace(mapping, evidence=(machine.identifier,)),),
            evidence_assertions=(machine,),
        )

    publisher = _publisher(ring="entity")
    accepted = validate_mapping_assertions(
        (replace(mapping, evidence=(publisher.identifier,)),),
        evidence_assertions=(publisher,),
    )
    assert accepted[0].relation == ENTITY_SAME_IDENTITY


def test_value_crosswalk_and_legal_identity_require_typed_time_context() -> None:
    value_evidence = _publisher(ring="value")
    with pytest.raises(SemanticFoundationError, match="require context"):
        _mapping(ring="value", relation=VALUE_EXACT_CROSSWALK, evidence=(value_evidence.identifier,))

    value = _mapping(
        ring="value",
        relation=VALUE_EXACT_CROSSWALK,
        evidence=(value_evidence.identifier,),
        context={
            "sourceEdition": "2017",
            "targetEdition": "2022",
            "effectiveFrom": "2022-01-01",
            "effectiveThrough": "2026-12-31",
        },
    )
    validate_mapping_assertions((value,), evidence_assertions=(value_evidence,))

    legal_evidence = _human(ring="legalIdentity")
    legal = _mapping(
        ring="legalIdentity",
        relation=LEGAL_CITES,
        evidence=(legal_evidence.identifier,),
        context={"effectiveAt": "2026-08-04"},
    )
    assert validate_mapping_assertions((legal,), evidence_assertions=(legal_evidence,))[0].context == {
        "effectiveAt": "2026-08-04"
    }


def test_operator_adoption_requires_one_scoped_machine_review() -> None:
    reviewed = _machine(evidence_class="machineReviewed")
    adopted = EvidenceAssertion(
        semantic_ring="subject",
        evidence_class="operatorAdopted",
        basis="operatorDirection",
        asserted_by="https://refspec.org/actors/operator-1",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:evidence:operator-decision",),
        adopted_evidence=reviewed.identifier,
    )
    mapping = _mapping(ring="subject", relation=SUBJECT_EXACT_MATCH, evidence=(adopted.identifier,))

    with pytest.raises(SemanticFoundationError, match="path-backed RelationAssertionBundle"):
        validate_mapping_assertions((mapping,), evidence_assertions=(reviewed, adopted))

    publisher = _publisher()
    invalid = replace(adopted, adopted_evidence=publisher.identifier)
    with pytest.raises(SemanticFoundationError, match="cite one machineReviewed assertion directly"):
        validate_evidence_assertions((publisher, invalid))

    chained = replace(
        adopted,
        asserted_at="2026-08-04T14:01:00Z",
        adopted_evidence=adopted.identifier,
    )
    with pytest.raises(SemanticFoundationError, match="cite one machineReviewed assertion directly"):
        validate_evidence_assertions((reviewed, adopted, chained))

    with pytest.raises(SemanticFoundationError, match="candidate-only evidence"):
        validate_mapping_assertions(
            (replace(mapping, evidence=(reviewed.identifier,)),),
            evidence_assertions=(reviewed,),
        )


def test_mapping_evidence_stays_ring_scoped_and_non_authorizing() -> None:
    evidence = _human(ring="entity")
    mapping = _mapping(ring="subject", relation=SUBJECT_EXACT_MATCH, evidence=(evidence.identifier,))
    with pytest.raises(SemanticFoundationError, match="crosses semantic rings"):
        validate_mapping_assertions((mapping,), evidence_assertions=(evidence,))

    record = _human().as_record()
    with pytest.raises(SemanticFoundationError, match="admission or permission"):
        EvidenceAssertion.from_record({**record, "emissionAuthorized": True})

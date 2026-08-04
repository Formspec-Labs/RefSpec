"""The four semantic rings share records but keep relation meaning separate."""

from __future__ import annotations

from typing import Any

import pytest

from refspec.registry.infrastructure.semantic_foundation import (
    ENTITY_SAME_IDENTITY,
    LEGAL_CITES,
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


def _evidence(
    identifier: str,
    *,
    ring: str,
    evidence_class: str = "humanReviewed",
    basis: str = "editorialReview",
    **specialized: Any,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": "EvidenceAssertion",
        "semanticRing": ring,
        "evidenceClass": evidence_class,
        "basis": basis,
        "assertedBy": "https://refspec.org/actors/reviewer-1",
        "assertedAt": ASSERTED_AT,
        "evidence": [f"{identifier}:support"],
        **(
            {"reviewDecision": f"{identifier}:decision"}
            if evidence_class == "humanReviewed" and not specialized
            else specialized
        ),
    }


def _mapping(
    *,
    ring: str,
    relation: str,
    evidence: str,
    context: dict[str, str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": f"urn:ref:test:mapping:{ring}:1",
        "type": "MappingAssertion",
        "semanticRing": ring,
        "sourceConcept": f"urn:ref:test:concept:{ring}:source",
        "targetConcept": f"urn:ref:test:concept:{ring}:target",
        "sourceRelease": f"urn:ref:test:release:{ring}:source",
        "targetRelease": f"urn:ref:test:release:{ring}:target",
        "relation": relation,
        "evidence": [evidence],
        "assertedAt": ASSERTED_AT,
    }
    if context is not None:
        result["context"] = context
    return result


def test_rights_metadata_represents_stated_and_explicitly_not_stated_facts() -> None:
    stated_record = {
        "type": "RightsMetadata",
        "rightsStatus": "stated",
        "rightsStatement": "https://publisher.example/terms",
        "sourceArtifact": "https://publisher.example/source/terms.json",
        "sourceDigest": DIGEST,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "rightsHolders": ["Example Publisher"],
        "attribution": "Example Publisher vocabulary",
    }
    stated = validate_rights_metadata(stated_record)
    not_stated = validate_rights_metadata(
        {
            "type": "RightsMetadata",
            "rightsStatus": "notStated",
            "sourceArtifact": "https://publisher.example/source/other.json",
            "sourceDigest": "sha256:" + "b" * 64,
        }
    )

    assert stated.as_record() == stated_record
    assert not_stated.as_record()["rightsStatus"] == "notStated"
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
    with pytest.raises(SemanticFoundationError, match="repeats a sourceArtifact"):
        validate_rights_metadata_records((stated, stated))


def test_all_evidence_classes_have_closed_honest_shapes() -> None:
    publisher = _evidence(
        "urn:ref:test:evidence:publisher",
        ring="subject",
        evidence_class="publisherAsserted",
        basis="sourceExplicit",
        sourceArtifact="https://publisher.example/source/mapping.json",
        sourceDigest=DIGEST,
    )
    records = (
        _evidence(
            "urn:ref:test:evidence:machine",
            ring="subject",
            evidence_class="machineQualified",
            basis="statisticalInference",
            qualificationPolicy="urn:ref:test:qualification-policy:v2",
            validationReceipts=(
                "urn:ref:test:validation:one",
                "urn:ref:test:validation:two",
            ),
        ),
        publisher,
        _evidence(
            "urn:ref:test:evidence:operator",
            ring="subject",
            evidence_class="operatorAdopted",
            basis="operatorDirection",
            adoptedEvidence=publisher["id"],
        ),
        _evidence("urn:ref:test:evidence:human", ring="subject"),
        _evidence(
            "urn:ref:test:evidence:rule",
            ring="subject",
            evidence_class="ruleGenerated",
            basis="deterministicDerivation",
            generator="urn:ref:test:generator:lexical-v1",
            generatorInputs=("urn:ref:test:generator-input:one",),
        ),
    )

    assertions = validate_evidence_assertions(records, semantic_ring="subject")  # type: ignore[arg-type]

    assert {value.evidence_class for value in assertions} == {
        "machineQualified",
        "publisherAsserted",
        "operatorAdopted",
        "humanReviewed",
        "ruleGenerated",
    }
    assert all(EvidenceAssertion.from_record(value.as_record()) == value for value in assertions)

    with pytest.raises(SemanticFoundationError, match="does not match machineQualified"):
        EvidenceAssertion.from_record(
            _evidence(
                "urn:ref:test:evidence:wrong-basis",
                ring="subject",
                evidence_class="machineQualified",
                basis="nameEquality",
                qualificationPolicy="urn:ref:test:qualification-policy:v2",
                validationReceipts=(
                    "urn:ref:test:validation:one",
                    "urn:ref:test:validation:two",
                ),
            )
        )


def test_subject_exact_match_is_a_mapping_and_never_an_identity_relation() -> None:
    evidence = _evidence("urn:ref:test:evidence:subject-review", ring="subject")
    mapping = _mapping(
        ring="subject",
        relation=SUBJECT_EXACT_MATCH,
        evidence=evidence["id"],
    )

    assertion = validate_mapping_assertions(
        (mapping,),
        evidence_assertions=(evidence,),
        semantic_ring="subject",
    )[0]

    assert assertion.relation == SUBJECT_EXACT_MATCH
    assert assertion.as_record()["type"] == "MappingAssertion"
    assert "identity" not in " ".join(assertion.as_record()).lower()

    with pytest.raises(SemanticFoundationError, match="not valid for the subject ring"):
        MappingAssertion.from_record({**mapping, "relation": ENTITY_SAME_IDENTITY})


def test_entity_identity_requires_more_than_name_or_statistical_similarity() -> None:
    name_equality = _evidence(
        "urn:ref:test:evidence:name-equality",
        ring="entity",
        evidence_class="ruleGenerated",
        basis="nameEquality",
        generator="urn:ref:test:generator:normalized-name-v1",
        generatorInputs=("urn:ref:test:entity-name:one",),
    )
    name_mapping = _mapping(
        ring="entity",
        relation=ENTITY_SAME_IDENTITY,
        evidence=name_equality["id"],
    )
    with pytest.raises(SemanticFoundationError, match="name equality"):
        validate_mapping_assertions((name_mapping,), evidence_assertions=(name_equality,))

    machine = _evidence(
        "urn:ref:test:evidence:entity-machine",
        ring="entity",
        evidence_class="machineQualified",
        basis="statisticalInference",
        qualificationPolicy="urn:ref:test:qualification-policy:v2",
        validationReceipts=("urn:ref:test:validation:one", "urn:ref:test:validation:two"),
    )
    machine_mapping = {**name_mapping, "evidence": [machine["id"]]}
    with pytest.raises(SemanticFoundationError, match="requires identifiers"):
        validate_mapping_assertions((machine_mapping,), evidence_assertions=(machine,))

    publisher = _evidence(
        "urn:ref:test:evidence:entity-publisher",
        ring="entity",
        evidence_class="publisherAsserted",
        basis="publisherCrosswalk",
        sourceArtifact="https://publisher.example/source/entity-crosswalk.json",
        sourceDigest=DIGEST,
    )
    accepted = validate_mapping_assertions(
        ({**name_mapping, "evidence": [publisher["id"]]},),
        evidence_assertions=(publisher,),
    )
    assert accepted[0].relation == ENTITY_SAME_IDENTITY


def test_value_crosswalk_requires_both_editions_and_effective_dates() -> None:
    evidence = _evidence(
        "urn:ref:test:evidence:value-publisher",
        ring="value",
        evidence_class="publisherAsserted",
        basis="publisherCrosswalk",
        sourceArtifact="https://publisher.example/source/value-crosswalk.json",
        sourceDigest=DIGEST,
    )
    base = _mapping(
        ring="value",
        relation=VALUE_EXACT_CROSSWALK,
        evidence=evidence["id"],
    )
    with pytest.raises(SemanticFoundationError, match="missing fields.*context"):
        MappingAssertion.from_record(base)
    with pytest.raises(SemanticFoundationError, match="targetEdition"):
        MappingAssertion.from_record(
            {
                **base,
                "context": {
                    "sourceEdition": "2017",
                    "effectiveFrom": "2022-01-01",
                },
            }
        )

    accepted = validate_mapping_assertions(
        (
            {
                **base,
                "context": {
                    "sourceEdition": "2017",
                    "targetEdition": "2022",
                    "effectiveFrom": "2022-01-01",
                    "effectiveThrough": "2026-12-31",
                },
            },
        ),
        evidence_assertions=(evidence,),
    )
    assert accepted[0].context == {
        "sourceEdition": "2017",
        "targetEdition": "2022",
        "effectiveFrom": "2022-01-01",
        "effectiveThrough": "2026-12-31",
    }


def test_legal_identity_accepts_only_typed_point_in_time_edges() -> None:
    evidence = _evidence("urn:ref:test:evidence:legal-review", ring="legalIdentity")
    assertion = validate_mapping_assertions(
        (
            _mapping(
                ring="legalIdentity",
                relation=LEGAL_CITES,
                evidence=evidence["id"],
                context={"effectiveAt": "2026-08-04"},
            ),
        ),
        evidence_assertions=(evidence,),
    )[0]
    assert assertion.relation == LEGAL_CITES
    assert assertion.context == {"effectiveAt": "2026-08-04"}

    with pytest.raises(SemanticFoundationError, match="not valid for the legalIdentity ring"):
        MappingAssertion.from_record(
            _mapping(
                ring="legalIdentity",
                relation=SUBJECT_EXACT_MATCH,
                evidence=evidence["id"],
                context={"effectiveAt": "2026-08-04"},
            )
        )


def test_mapping_evidence_stays_ring_scoped_and_non_authorizing() -> None:
    entity_evidence = _evidence("urn:ref:test:evidence:entity-review", ring="entity")
    subject_mapping = _mapping(
        ring="subject",
        relation=SUBJECT_EXACT_MATCH,
        evidence=entity_evidence["id"],
    )
    with pytest.raises(SemanticFoundationError, match="crosses semantic rings"):
        validate_mapping_assertions((subject_mapping,), evidence_assertions=(entity_evidence,))

    with pytest.raises(SemanticFoundationError, match="admission or permission"):
        EvidenceAssertion.from_record(
            {
                **_evidence("urn:ref:test:evidence:permission", ring="subject"),
                "emissionAuthorized": True,
            }
        )

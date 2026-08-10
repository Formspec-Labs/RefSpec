from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.atlas.v3_source_data import (
    MAPPING_REVIEW_METHODS,
    RegistryInputPin,
    RegistryLabel,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryResource,
)

_DIGEST = "sha256:" + ("0" * 64)
_REVIEW_METHODS = {
    "deterministicTransformation",
    "humanReview",
    "operatorAdoption",
    "publisherAssertion",
    "trustedPipelineReview",
    "twoMachineAdjudication",
}


def _resource(labels: tuple[RegistryLabel, ...]) -> RegistryResource:
    return RegistryResource(
        iri="urn:example:resource",
        labels=labels,
        native_payload={"id": "example"},
        source_locator="urn:example:source-record",
        source_digest=_DIGEST,
    )


def _mapping_evidence(
    *,
    review_method: str = "operatorAdoption",
    decided_at: str = "2026-08-06T00:00:00+00:00",
) -> RegistryMappingEvidence:
    return RegistryMappingEvidence(
        source_locator="urn:example:mapping-source",
        source_digest=_DIGEST,
        native_payload={"row": 1},
        review_warrant=review_method,  # type: ignore[arg-type]
        reviewer_iri="urn:example:reviewer",
        attested_at=decided_at,
    )


def _mapping(
    *,
    asserted_at: str = "2026-08-06T01:00:00+00:00",
    evidence: tuple[RegistryMappingEvidence, ...] | None = None,
) -> RegistryMapping:
    return RegistryMapping(
        subject="urn:example:subject",
        predicate="http://www.w3.org/2004/02/skos/core#exactMatch",
        object="urn:example:object",
        subject_atlas_release_iri="urn:example:atlas-release:subject:v1",
        object_atlas_release_iri="urn:example:atlas-release:object:v1",
        asserted_at=asserted_at,
        evidence=evidence or (_mapping_evidence(),),
    )


def _mapping_release(
    *,
    mappings: tuple[RegistryMapping, ...] | None = None,
) -> RegistryMappingRelease:
    pin = RegistryInputPin(
        path=Path("mapping.json"),
        logical_path="test/mapping.json",
        sha256=_DIGEST,
        byte_length=1,
        source_iri="urn:example:mapping-source",
        role="mappingSource",
    )
    return RegistryMappingRelease(
        key="example-mappings-v1",
        resource_id="example-mappings",
        source_module="tests.example",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-06",
        source_release_iri="urn:example:mapping-release:v1",
        source_release_digest=_DIGEST,
        inputs=(pin,),
        mappings=mappings or (_mapping(),),
        editorial_policy={"version": "example-v1"},
    )


def test_registry_resource_accepts_publisher_alternate_only_identity() -> None:
    resource = _resource(
        (
            RegistryLabel(
                value="Publisher alternate",
                role="alternate",
                source_path="$.labels[0]",
            ),
        )
    )

    assert resource.labels[0].role == "alternate"


def test_registry_resource_rejects_multiple_preferred_labels() -> None:
    labels = tuple(
        RegistryLabel(value=value, role="preferred", source_path=f"$.labels[{index}]")
        for index, value in enumerate(("First", "Second"))
    )

    with pytest.raises(ValueError, match="more than one preferred"):
        _resource(labels)


def test_registry_resource_rejects_duplicate_label_claim() -> None:
    label = RegistryLabel(
        value="Repeated",
        role="alternate",
        source_path="$.labels[0]",
    )

    with pytest.raises(ValueError, match="repeats label claim"):
        _resource((label, label))


def test_registry_resource_rejects_label_value_across_roles() -> None:
    with pytest.raises(ValueError, match="reuses label value.*across roles"):
        _resource(
            (
                RegistryLabel(
                    value="Same value",
                    role="preferred",
                    source_path="$.labels[0]",
                ),
                RegistryLabel(
                    value="Same value",
                    role="hidden",
                    source_path="$.labels[1]",
                ),
            )
        )


def test_registry_resource_requires_at_least_one_label() -> None:
    with pytest.raises(ValueError, match="has no English label"):
        _resource(())


@pytest.mark.parametrize("review_method", sorted(_REVIEW_METHODS))
def test_registry_mapping_evidence_accepts_every_binding_review_method(
    review_method: str,
) -> None:
    evidence = _mapping_evidence(review_warrant=review_method)

    assert evidence.review_warrant == review_method
    assert MAPPING_REVIEW_METHODS == _REVIEW_METHODS


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        ("source_locator", "not-an-iri", "source locator must be an absolute IRI"),
        ("source_digest", "sha256:not-a-digest", "source digest must be SHA-256"),
        ("review_method", "legacyReview", "unsupported.*review method"),
        ("reviewer_iri", "not-an-iri", "reviewer must be an absolute IRI"),
        ("decided_at", "2026-08-06T00:00:00", "explicit timezone"),
    ),
)
def test_registry_mapping_evidence_rejects_invalid_identity_and_decision_fields(
    field_name: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_mapping_evidence(), **{field_name: value})


def test_registry_mapping_accepts_multiple_immutable_approvals() -> None:
    machine = _mapping_evidence(
        review_warrant="twoMachineAdjudication",
        attested_at="2026-08-06T00:00:00+00:00",
    )
    human = replace(
        _mapping_evidence(
            review_warrant="humanReview",
            attested_at="2026-08-07T00:00:00+00:00",
        ),
        source_locator="urn:example:human-review",
        reviewer_iri="urn:example:human-reviewer",
    )

    mapping = _mapping(evidence=(machine, human))

    assert mapping.asserted_at == "2026-08-06T01:00:00+00:00"
    assert [row.review_warrant for row in mapping.evidence] == [
        "twoMachineAdjudication",
        "humanReview",
    ]


@pytest.mark.parametrize(
    "field_name",
    (
        "subject",
        "predicate",
        "object",
        "subject_atlas_release_iri",
        "object_atlas_release_iri",
    ),
)
def test_registry_mapping_rejects_non_iri_terms_and_release_pins(
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match="terms and releases must be absolute IRIs"):
        replace(_mapping(), **{field_name: "not-an-iri"})


def test_registry_mapping_requires_two_exact_distinct_endpoint_releases() -> None:
    mapping = _mapping()

    with pytest.raises(ValueError, match="different Atlas releases"):
        replace(
            mapping,
            object_atlas_release_iri=mapping.subject_atlas_release_iri,
        )


def test_registry_mapping_requires_at_least_one_evidence_decision() -> None:
    with pytest.raises(ValueError, match="at least one evidence decision"):
        replace(_mapping(), evidence=())


def test_registry_mapping_rejects_a_repeated_evidence_decision() -> None:
    evidence = _mapping_evidence()

    with pytest.raises(ValueError, match="repeats an evidence decision"):
        _mapping(evidence=(evidence, evidence))


def test_registry_mapping_rejects_equivalent_utc_evidence_times() -> None:
    evidence = _mapping_evidence()

    with pytest.raises(ValueError, match="repeats an evidence decision"):
        _mapping(
            evidence=(
                evidence,
                replace(evidence, attested_at="2026-08-06T00:00:00Z"),
            )
        )


def test_registry_mapping_rejects_naive_assertion_time() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        _mapping(asserted_at="2026-08-06T01:00:00")


def test_registry_mapping_requires_an_approval_no_later_than_the_assertion() -> None:
    first = _mapping_evidence(attested_at="2026-08-07T00:00:00+00:00")
    second = replace(
        first,
        source_locator="urn:example:second-review",
        reviewer_iri="urn:example:second-reviewer",
        attested_at="2026-08-08T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="asserted before every approving decision"):
        _mapping(evidence=(first, second))


def test_registry_mapping_release_carries_scope_and_editorial_policy() -> None:
    release = _mapping_release()

    assert release.scope == "captureSubset"
    assert release.editorial_policy == {"version": "example-v1"}


def test_registry_mapping_release_rejects_an_unsupported_scope() -> None:
    with pytest.raises(ValueError, match="unsupported mapping release scope"):
        replace(_mapping_release(), scope="legacyScope")  # type: ignore[arg-type]


def test_registry_mapping_release_requires_an_editorial_policy() -> None:
    with pytest.raises(ValueError, match="has no editorial policy payload"):
        replace(_mapping_release(), editorial_policy={})


@pytest.mark.parametrize("issued", ("2026-8-6", "2026-08-06T00:00:00Z"))
def test_registry_mapping_release_requires_a_canonical_issue_date(issued: str) -> None:
    with pytest.raises(ValueError, match="issued must"):
        replace(_mapping_release(), issued=issued)


def test_registry_mapping_release_rejects_assertions_before_release() -> None:
    mapping = _mapping(
        asserted_at="2026-08-05T01:00:00+00:00",
        evidence=(
            _mapping_evidence(attested_at="2026-08-05T00:00:00+00:00"),
        ),
    )

    with pytest.raises(ValueError, match="assertion predates its release"):
        _mapping_release(mappings=(mapping,))


def test_registry_mapping_release_rejects_evidence_before_release() -> None:
    mapping = _mapping(
        evidence=(
            _mapping_evidence(attested_at="2026-08-05T00:00:00+00:00"),
        ),
    )

    with pytest.raises(ValueError, match="evidence decision predates its release"):
        _mapping_release(mappings=(mapping,))

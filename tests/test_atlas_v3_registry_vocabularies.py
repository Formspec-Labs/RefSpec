from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from refspec.atlas import v3_registry_vocabularies as vocabularies
from refspec.registry.infrastructure.source_identity import validate_uuid7


def _assert_native_payload_is_english(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in {"@language", "lang", "language", "languagetag"}:
                assert child == "en"
            _assert_native_payload_is_english(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_native_payload_is_english(child)


def test_source_scoped_identity_is_stable_readable_uuid7() -> None:
    first, first_evidence = vocabularies._source_scoped_identity(
        namespace="test-source",
        source_scheme="https://example.test/scheme",
        source_key="publisher-row-42",
        recorded_at="2026-08-03T12:00:00Z",
    )
    second, second_evidence = vocabularies._source_scoped_identity(
        namespace="test-source",
        source_scheme="https://example.test/scheme",
        source_key="publisher-row-42",
        recorded_at="2026-08-03T12:00:00Z",
    )

    assert first == second
    assert first_evidence == second_evidence
    assert first.startswith("urn:ref:source-concept:v2:test-source:")
    validate_uuid7(first.rsplit(":", 1)[1])
    assert first_evidence == {
        "identityKind": "refspecSourceScoped",
        "localRecordId": "urn:uuid:" + first.rsplit(":", 1)[1],
        "namespaceToken": "test-source",
        "sourceKey": "publisher-row-42",
        "sourceScheme": "https://example.test/scheme",
    }


def test_label_role_normalization_prefers_stronger_skos_role_and_receipts_source() -> None:
    retained, conflicts = vocabularies._normalize_skos_label_roles(
        (
            vocabularies.RegistryLabel(
                value="urban waste water",
                role="hidden",
                source_path="concept/12284::skos:hiddenLabel",
            ),
            vocabularies.RegistryLabel(
                value="urban waste water",
                role="preferred",
                source_path="concept/12284::skos:prefLabel",
            ),
        )
    )

    assert [(label.value, label.role) for label in retained] == [
        ("urban waste water", "preferred")
    ]
    assert conflicts == (
        {
            "language": "en",
            "retainedRole": "preferred",
            "retainedSourcePath": "concept/12284::skos:prefLabel",
            "suppressedRole": "hidden",
            "suppressedSourcePath": "concept/12284::skos:hiddenLabel",
            "value": "urban waste water",
        },
    )


def test_label_role_normalization_rejects_duplicate_normalized_claim() -> None:
    with pytest.raises(ValueError, match="repeat the same value and role"):
        vocabularies._normalize_skos_label_roles(
            (
                vocabularies.RegistryLabel(
                    value="same",
                    role="alternate",
                    source_path="source:a",
                ),
                vocabularies.RegistryLabel(
                    value="same",
                    role="alternate",
                    source_path="source:b",
                ),
            )
        )


def test_direct_relations_keep_only_unique_member_triples() -> None:
    member = SimpleNamespace(
        subject_iri="https://example.test/a",
        predicate_iri="http://www.w3.org/2004/02/skos/core#broader",
        object_iri="https://example.test/b",
    )
    outside = SimpleNamespace(
        subject_iri="https://example.test/a",
        predicate_iri="http://www.w3.org/2004/02/skos/core#broader",
        object_iri="https://outside.test/c",
    )

    relations = vocabularies._direct_relations(
        (member, member, outside),
        {"https://example.test/a", "https://example.test/b"},
    )

    assert len(relations) == 1
    assert (
        relations[0].subject,
        relations[0].predicate,
        relations[0].object,
    ) == (
        member.subject_iri,
        member.predicate_iri,
        member.object_iri,
    )


def test_s27_conflict_keeps_publisher_relation_as_transformation_evidence() -> None:
    broader = vocabularies.RegistryRelation(
        subject="https://example.test/a",
        predicate="http://www.w3.org/2004/02/skos/core#broader",
        object="https://example.test/b",
        source_payload={"publisher": "broader"},
    )
    related = vocabularies.RegistryRelation(
        subject="https://example.test/a",
        predicate="http://www.w3.org/2004/02/skos/core#related",
        object="https://example.test/b",
        source_payload={"publisher": "related"},
    )

    normalized = vocabularies._preserve_s27_conflicts((broader, related))

    assert normalized[0] == broader
    assert normalized[1].predicate == "https://refspec.org/ns/atlas/v3#thesaurusRelated"
    assert normalized[1].source_payload["publisherRelation"] == related.source_payload
    assert normalized[1].source_payload["editorialTransformation"]["reason"] == ("SKOS-S27-hierarchy-path")


@pytest.mark.skipif(
    not (vocabularies.DEFAULT_SOURCE_ROOT / "gcmd-science-keywords-24.4.csv").is_file(),
    reason="exact cached GCMD 24.4 publisher source is not available",
)
def test_gcmd_cache_normalizes_complete_source_without_inferred_hierarchy() -> None:
    release = vocabularies.load_gcmd_24_4_release()

    assert release.resource_id == "gcmd-science-keywords"
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:gcmd-science-keywords"
    assert len(release.resources) == vocabularies.EXPECTED_RESOURCE_COUNTS[release.key]
    assert release.relations == ()
    assert all(
        resource.iri.startswith("urn:ref:source-concept:v2:gcmd-science-keywords:") for resource in release.resources
    )
    assert all(label.language == "en" for resource in release.resources for label in resource.labels)
    assert all(resource.native_payload["hierarchyIsDescriptiveNotInferred"] for resource in release.resources)


@pytest.mark.skipif(
    not (vocabularies.DEFAULT_SOURCE_ROOT / "federal-register-thesaurus-2025.pdf").is_file(),
    reason="exact cached Federal Register 2025 PDF is not available",
)
def test_federal_register_cache_reads_pdf_without_managed_release_dependency() -> None:
    release = vocabularies.load_federal_register_2025_release()

    assert release.resource_id == "federal-register-thesaurus-2025"
    assert release.scheme_iri == ("urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025")
    assert len(release.resources) == 705
    assert len(release.relations) == 1_451
    assert all(
        resource.iri.startswith("urn:ref:source-concept:v2:federal-register-thesaurus:")
        for resource in release.resources
    )
    assert all(label.language == "en" for resource in release.resources for label in resource.labels)


@pytest.mark.skipif(
    os.environ.get("REFSPEC_ATLAS_V3_FULL_VOCABULARY_SOURCES") != "1",
    reason="set REFSPEC_ATLAS_V3_FULL_VOCABULARY_SOURCES=1 for all large cached sources",
)
@pytest.mark.parametrize(
    "loader",
    (
        vocabularies.load_doe_osti_release,
        vocabularies.load_elsst_r6_release,
        vocabularies.load_gemet_release,
        vocabularies.load_mesh_2026_release,
        vocabularies.load_nasa_thesaurus_release,
    ),
)
def test_large_pinned_vocabulary_normalizes_complete_source(loader: object) -> None:
    release = loader(Path(vocabularies.DEFAULT_SOURCE_ROOT))  # type: ignore[operator]

    assert len(release.resources) == vocabularies.EXPECTED_RESOURCE_COUNTS[release.key]
    assert len(release.relations) == vocabularies.EXPECTED_RELATION_COUNTS[release.key]
    assert (
        sum(len(resource.labels) for resource in release.resources) == (vocabularies.EXPECTED_LABEL_COUNTS[release.key])
    )
    assert release.scheme_iri == f"urn:ref:atlas-resource-scheme:{release.resource_id}"
    assert all(label.language == "en" for resource in release.resources for label in resource.labels)
    assert all(
        "www.w3.org/2004/02/skos/core#" not in relation.predicate or not relation.predicate.endswith("Match")
        for relation in release.relations
    )
    for resource in release.resources:
        _assert_native_payload_is_english(resource.native_payload)

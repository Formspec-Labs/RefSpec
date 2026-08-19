from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from refspec.atlas import v3_registry_vocabularies as vocabularies
from refspec.atlas.registry_claim_input import AtlasRegistryClaimInput
from refspec.registry.infrastructure.source_identity import validate_uuid7

EUROVOC_CLAIM_ROOT = (
    Path(__file__).parents[1]
    / "output"
    / "registry-claim-releases"
    / "eurovoc-4.24"
)


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


def test_label_role_normalization_deduplicates_same_value_and_role() -> None:
    retained, conflicts = vocabularies._normalize_skos_label_roles(
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

    assert retained == (
        vocabularies.RegistryLabel(
            value="same",
            role="alternate",
            source_path="source:a",
        ),
    )
    assert conflicts == ()


def test_gemet_normalization_keeps_variant_synonym_and_deduplicates_twins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    concept_iri = "https://example.test/gemet/concept/1"

    def label(
        value: str,
        language: str,
        role: str,
        predicate: str,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            subject_iri=concept_iri,
            property_iri=predicate,
            role=role,
            value=SimpleNamespace(
                lexical_form=value,
                language_tag=language,
            ),
        )

    parsed = SimpleNamespace(
        concepts=(
            SimpleNamespace(
                concept_iri=concept_iri,
                scheme_iris=("https://example.test/gemet",),
                top_concept_of_iris=(),
            ),
        ),
        labels=(
            label("organisation", "en", "preferred", "skos:prefLabel"),
            label("organization", "en", "alternate", "skos:altLabel"),
            label("organisation", "en-US", "preferred", "skos:prefLabel"),
            label("organization", "en-US", "preferred", "skos:prefLabel"),
            label("organizational", "en-US", "preferred", "skos:prefLabel"),
        ),
        metadata_literals=(),
        notes=(),
        notations=(),
        semantic_relations=(),
        organization_resources=(),
        organization_labels=(),
        organization_metadata_literals=(),
        organization_membership_relations=(),
        organization_hierarchy_relations=(),
    )
    monkeypatch.setitem(vocabularies.EXPECTED_RESOURCE_COUNTS, "gemet-4.2.3", 1)
    monkeypatch.setitem(vocabularies.EXPECTED_LABEL_COUNTS, "gemet-4.2.3", 3)
    monkeypatch.setitem(vocabularies.EXPECTED_RELATION_COUNTS, "gemet-4.2.3", 0)
    source = vocabularies.RegistryInputPin(
        path=tmp_path / "gemet.rdf",
        logical_path="output/registry-real-data-sources/gemet.rdf",
        sha256="sha256:" + "0" * 64,
        byte_length=1,
        source_iri="https://example.test/gemet.rdf",
    )

    release = vocabularies._normalize_gemet(parsed, source)

    assert [(row.value, row.role) for row in release.resources[0].labels] == [
        ("organisation", "preferred"),
        ("organization", "alternate"),
        ("organizational", "alternate"),
    ]
    assert release.metadata["englishFamilyVariantLabelCount"] == 3
    assert release.metadata["englishFamilyDuplicateLabelCount"] == 2
    assert release.metadata["englishFamilyVariantSynonymCount"] == 1


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


@pytest.mark.skipif(
    not EUROVOC_CLAIM_ROOT.is_dir()
    or not (
        vocabularies.DEFAULT_SOURCE_ROOT / "eurovoc-4.24-skos-core.zip"
    ).is_file(),
    reason="verified EuroVoc source and claim bundle are not available",
)
def test_eurovoc_claim_views_match_parser_compatibility_releases() -> None:
    manifest = EUROVOC_CLAIM_ROOT / "release-manifest.json"
    claim_input = AtlasRegistryClaimInput(
        path=EUROVOC_CLAIM_ROOT,
        expected_manifest_digest=(
            "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
        ),
    )
    parser_releases = vocabularies.load_eurovoc_4_24_releases()
    claim_releases = vocabularies.load_eurovoc_4_24_releases_from_claims(
        claim_input
    )

    for claim_release, parser_release in zip(
        claim_releases,
        parser_releases,
        strict=True,
    ):
        assert replace(claim_release, inputs=parser_release.inputs) == parser_release
        assert [
            (pin.logical_path, pin.sha256, pin.byte_length, pin.source_iri, pin.role)
            for pin in claim_release.inputs
        ] == [
            (pin.logical_path, pin.sha256, pin.byte_length, pin.source_iri, pin.role)
            for pin in parser_release.inputs
        ]
        assert all(
            pin.path.is_relative_to(EUROVOC_CLAIM_ROOT)
            for pin in claim_release.inputs
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


def _skip_unless_source_present(filename: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        not (vocabularies.DEFAULT_SOURCE_ROOT / filename).is_file(),
        reason=f"exact cached large-vocabulary publisher source is not available: {filename}",
    )


@pytest.mark.parametrize(
    "loader",
    (
        pytest.param(
            vocabularies.load_doe_osti_release,
            marks=_skip_unless_source_present("osti-semantic-thesaurus-2020.rdf"),
        ),
        pytest.param(
            vocabularies.load_elsst_r6_release,
            marks=_skip_unless_source_present("ELSST_R6.ttl"),
        ),
        pytest.param(
            vocabularies.load_gemet_release,
            marks=_skip_unless_source_present("gemet.rdf"),
        ),
        pytest.param(
            vocabularies.load_mesh_2026_release,
            marks=_skip_unless_source_present("desc2026.xml"),
        ),
        pytest.param(
            vocabularies.load_nasa_thesaurus_release,
            marks=_skip_unless_source_present("thesaurus-SKOS.xml"),
        ),
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

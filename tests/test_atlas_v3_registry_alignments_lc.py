"""Atlas 3 releases derived from LC's pinned external-links archive."""

from __future__ import annotations

import importlib
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import RDF, Dataset, Namespace, URIRef

from refspec.atlas import v3_registry_alignments_lc as alignments
from refspec.registry import lc_external_links as external

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = alignments.DEFAULT_SOURCE_ROOT
REQUIRED_FILES = (
    SOURCE_ROOT / external.LC_EXTERNAL_LINKS_FILENAME,
    SOURCE_ROOT / alignments.LCSH_BULK_FILENAME,
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
)
HAS_OFFICIAL_SOURCES = all(path.is_file() for path in REQUIRED_FILES)


def _generator_module():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        return importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))


@pytest.fixture(scope="module")
def endpoint_release():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official LC, LCSH, and FAST sources are not cached")
    return alignments.load_lcsh_external_links_endpoint_release(SOURCE_ROOT)


@pytest.fixture(scope="module")
def mapping_release():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official LC, LCSH, and FAST sources are not cached")
    return alignments.load_lc_external_links_mapping_release(SOURCE_ROOT)


@pytest.fixture(scope="module")
def external_target_releases():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official LC external-link source is not cached")
    return alignments.load_lc_external_target_endpoint_releases(SOURCE_ROOT)


class _MappingEndpointResources:
    """Present every mapping endpoint to refusal guards without copying rows."""

    def __init__(self, mappings: object) -> None:
        self._mappings = mappings

    def __iter__(self) -> Iterator[SimpleNamespace]:
        for mapping in self._mappings:  # type: ignore[union-attr]
            yield SimpleNamespace(iri=mapping.subject)
            yield SimpleNamespace(iri=mapping.object)


def test_mapping_release_preserves_lc_direction_and_exact_predicate_mix(
    mapping_release,
) -> None:
    assert mapping_release.key == alignments.LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY
    assert mapping_release.ring == "subject"
    assert mapping_release.scope == "captureSubset"
    assert len(mapping_release.mappings) == 801_992
    assert sum(row.object.startswith("http://id.worldcat.org/fast/") for row in mapping_release.mappings) == 534_968
    assert sum(not row.object.startswith("http://id.worldcat.org/fast/") for row in mapping_release.mappings) == 267_024
    assert all(
        row.subject.startswith(external.LCSH_SUBJECT_PREFIX)
        for row in mapping_release.mappings
    )
    assert len({(row.subject, row.predicate, row.object) for row in mapping_release.mappings}) == len(
        mapping_release.mappings
    )


def test_every_translated_mapping_carries_the_ref_035_adoption_chain(
    mapping_release,
) -> None:
    for row in mapping_release.mappings:
        (evidence,) = row.evidence
        publisher_claim = evidence.native_payload["publisherClaim"]
        adoption = evidence.native_payload["operatorAdoption"]

        assert evidence.review_warrant == "operatorAdoption"
        assert evidence.reviewer_iri == alignments.LC_MAPPING_ADOPTION_REVIEWER_IRI
        assert publisher_claim["subjectIri"] == row.subject
        assert publisher_claim["objectIri"] == row.object
        assert publisher_claim["predicateIri"] in alignments.MADS_TO_SKOS_PREDICATE
        assert adoption == {
            "adoptedBy": alignments.LC_MAPPING_ADOPTION_REVIEWER_IRI,
            "fromPredicateIri": publisher_claim["predicateIri"],
            "toPredicateIri": row.predicate,
        }
        assert row.predicate == alignments.MADS_TO_SKOS_PREDICATE[publisher_claim["predicateIri"]]


def test_release_accounts_for_held_absent_and_external_endpoints(mapping_release) -> None:
    metadata = mapping_release.metadata

    assert metadata["assertionCountsByTargetVocabulary"] == dict(external.EXPECTED_ASSERTION_COUNTS_BY_VOCABULARY)
    assert metadata["assertionCountsByPublisherPredicate"] == dict(
        external.EXPECTED_ASSERTION_COUNTS_BY_PUBLISHER_PREDICATE
    )
    assert metadata["emittedAssertionCount"] == 801_992
    assert metadata["unemittedAssertionCount"] == 600
    assert metadata["fastEndpointOutsideCurrentReleaseCount"] == 108_531
    assert metadata["lcshEndpointAbsentCount"] == 469
    assert metadata["externalEndpointDisposition"] == {
        "capturedNonFastAssertionCount": 267_220,
        "classifiedTargetCount": 792_134,
        "emittedNonFastAssertionCount": 267_024,
        "explicitEnglishLabelCount": 0,
        "missingNonFastSubjectAssertionCount": 196,
        "recoveredEndpointCount": 365_293,
        "reusedCurrentFastEndpointCount": 426_841,
        "reason": (
            "target labels use deterministic authority or source conventions; "
            "rows are omitted only when the pinned LCSH source has no subject record"
        ),
        "status": "emittedWithDeterminedLanguage",
    }
    assert metadata["endpointCoverage"] == {
        "activeFastResourceCount": 441_127,
        "exactIriCoveragePercent": "96.75966331691328",
        "reachedFastResourceCount": 426_833,
    }


def test_source_rights_and_rolling_archive_identity_are_verbatim(mapping_release) -> None:
    artifact = mapping_release.metadata["sourceArtifact"]

    assert artifact == {
        "byteLength": 239_565_667,
        "digest": "sha256:7d279d69c6920b41a579634a84a1b31ff73af764345fe51df3f7c480efeba9d1",
        "exactSourceUrl": "https://id.loc.gov/download/externallinks.nt.zip",
        "license": "CC0 1.0 Universal",
        "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
        "publisherVersionedSourceUrl": "publisher provides no versioned URL",
        "retrievedAt": "2026-08-15T22:49:53Z",
        "rightsStatement": ("These works are also available for worldwide use and reuse under CC0 1.0 Universal."),
        "rightsStatementUrl": ("https://www.loc.gov/legal/security-copyright-and-privacy/understanding-copyright/"),
        "versioning": (
            "LC publishes a rolling latest file; the digest and byte length pin "
            "the retrieved bytes so later drift is detectable"
        ),
    }


def test_endpoint_release_is_complete_for_every_emitted_lc_subject(
    endpoint_release,
    mapping_release,
) -> None:
    assert endpoint_release.key == alignments.LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY
    assert len(endpoint_release.resources) == 359_728
    assert Counter(resource.status for resource in endpoint_release.resources) == {
        "alignmentEndpoint": 358_103,
        "deprecatedAlignmentEndpoint": 1_625,
    }
    assert endpoint_release.metadata["existingEndpointOverlapCount"] == 1_951
    assert endpoint_release.metadata["missingLcshSubjectCount"] == 469

    new_endpoint_iris = {resource.iri for resource in endpoint_release.resources}
    assert {
        row.subject
        for row in mapping_release.mappings
        if row.subject_atlas_release_iri == alignments.LCSH_EXTERNAL_LINKS_ENDPOINT_ATLAS_RELEASE_IRI
    } == new_endpoint_iris


def test_language_determined_external_endpoints_are_contentful(external_target_releases) -> None:
    assert {release.key for release in external_target_releases} == set(
        alignments.LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS.values()
    )
    assert sum(len(release.resources) for release in external_target_releases) == 365_293
    assert {
        release.metadata["targetVocabulary"]: len(release.resources)
        for release in external_target_releases
    } == dict(alignments.LC_EXTERNAL_TARGET_COUNTS_BY_VOCABULARY)
    assert Counter(
        label.language
        for release in external_target_releases
        for resource in release.resources
        for label in resource.labels
    ) == dict(alignments.LC_EXTERNAL_RECOVERED_LABEL_COUNTS_BY_LANGUAGE)
    for release in external_target_releases:
        assert release.metadata["publisherLanguageTagPresent"] is False
        assert release.metadata["sourceIdentifierCount"] == 0
        for resource in release.resources:
            assert resource.labels
            assert resource.native_payload["publisherLanguageTagPresent"] is False
            assert resource.native_payload["languageDeterminedBy"]
            assert all(
                label["publisherLanguageTagPresent"] is False
                and label["languageDeterminedBy"]
                and label["nativeStatement"]
                for label in resource.native_payload["publisherLabels"]
            )


def test_release_never_mints_inverse_or_transitive_claims(mapping_release) -> None:
    triples = {(row.subject, row.predicate, row.object) for row in mapping_release.mappings}

    assert len(triples) == len(mapping_release.mappings)
    assert all((object_iri, predicate, subject_iri) not in triples for subject_iri, predicate, object_iri in triples)
    assert all(row.evidence[0].native_payload["publisherClaim"]["nativeStatement"] for row in mapping_release.mappings)


def test_new_releases_pass_all_three_population_refusal_guards(
    endpoint_release,
    mapping_release,
    external_target_releases,
) -> None:
    generator = _generator_module()
    shaped_mapping = SimpleNamespace(
        spec=SimpleNamespace(
            key=mapping_release.key,
            logical_path=mapping_release.inputs[0].logical_path,
            input_pins=mapping_release.inputs,
        ),
        scheme_iri=f"urn:ref:atlas-mapping-endpoints:{mapping_release.key}",
        resources=_MappingEndpointResources(mapping_release.mappings),
    )
    shaped_endpoint = SimpleNamespace(
        spec=SimpleNamespace(
            key=endpoint_release.key,
            logical_path=endpoint_release.inputs[0].logical_path,
            input_pins=endpoint_release.inputs,
        ),
        scheme_iri=endpoint_release.scheme_iri,
        resources=endpoint_release.resources,
    )

    shaped_targets = tuple(
        SimpleNamespace(
            spec=SimpleNamespace(
                key=release.key,
                logical_path=release.inputs[0].logical_path,
                input_pins=release.inputs,
            ),
            scheme_iri=release.scheme_iri,
            resources=release.resources,
        )
        for release in external_target_releases
    )
    for release in (shaped_endpoint, shaped_mapping, *shaped_targets):
        generator._refuse_registrant_population_release(release)
        generator._refuse_document_population_release(release)
        generator._refuse_observed_inventory_release(release)


def test_identifier_authority_tripwire_is_nonvacuous(
    endpoint_release,
    mapping_release,
    external_target_releases,
) -> None:
    atlas = Namespace("https://refspec.org/ns/atlas/v3#")
    dataset = Dataset()
    dataset.parse(
        ROOT / "bindings" / "atlas" / "3.1" / "tests" / "registry-descriptors.nq",
        format="nquads",
    )
    graph = dataset.graph(URIRef("urn:ref:atlas-v3:registry-descriptors"))
    authorities = {
        str(subject)
        for subject in graph.subjects(atlas.resourceProfile, atlas.identifierScheme)
        if (subject, RDF.type, atlas.ResourceScheme) in graph
    }

    assert "urn:ref:atlas-resource-scheme:treasury-account-symbol-structure" in authorities
    assert [identifier for resource in endpoint_release.resources for identifier in resource.identifiers] == []
    assert endpoint_release.metadata["sourceIdentifierCount"] == 0
    assert mapping_release.metadata["sourceIdentifierCount"] == 0
    assert all(
        not resource.identifiers
        for release in external_target_releases
        for resource in release.resources
    )
    assert all(
        "identifiers" not in evidence.native_payload and "identifierScheme" not in evidence.native_payload
        for mapping in mapping_release.mappings
        for evidence in mapping.evidence
    )


def test_adapter_declares_all_lc_construction_units() -> None:
    assert alignments.LCSH_EXTERNAL_LINKS_ENDPOINT_RELEASE_KEY in (
        alignments.LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS
    )
    assert set(alignments.LC_EXTERNAL_TARGET_ENDPOINT_RELEASE_KEYS.values()) < set(
        alignments.LC_REGISTRY_ALIGNMENT_ENDPOINT_RELEASE_KEYS
    )
    assert alignments.LC_REGISTRY_MAPPING_RELEASE_KEYS == {
        alignments.LCSH_EXTERNAL_LINKS_MAPPING_RELEASE_KEY
    }

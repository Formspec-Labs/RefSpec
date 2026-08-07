"""Atlas 3 adapters for official publisher-authored mappings and endpoints."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from rdflib.namespace import SKOS

from refspec.atlas import v3_registry_alignments as alignments
from refspec.atlas.v3_registry_vocabularies import load_eurovoc_4_24_releases
from refspec.atlas.v3_source_data import mapping_triple_digest
from refspec.registry.eurovoc_lcsh_alignment import (
    EUROVOC_4_20_RELEASE_IRI,
    EUROVOC_LCSH_ALIGNMENT_SHA256,
    EXPECTED_PREDICATE_COUNTS,
)

SOURCE_ROOT = alignments.DEFAULT_SOURCE_ROOT
REQUIRED_FILES = (
    SOURCE_ROOT / alignments.LCSH_BULK_FILENAME,
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711-metadata.rdf",
    SOURCE_ROOT / "eurovoc-4.20-20240711-metadata.rdf",
    SOURCE_ROOT / "eurovoc-4.24-metadata.ttl",
)
HAS_OFFICIAL_SOURCES = all(path.is_file() for path in REQUIRED_FILES)
HAS_COMPLETE_EUROVOC = (
    SOURCE_ROOT / "eurovoc-4.24-skos-core.zip"
).is_file()


@pytest.fixture(scope="module")
def mapping_release():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official EuroVoc--LCSH alignment sources are not cached")
    return alignments.load_eurovoc_lcsh_mapping_release(Path(SOURCE_ROOT))


@pytest.fixture(scope="module")
def endpoint_release():
    if not HAS_OFFICIAL_SOURCES:
        pytest.skip("official LCSH bulk and EuroVoc alignment sources are not cached")
    return alignments.load_lcsh_alignment_endpoint_release(Path(SOURCE_ROOT))


@pytest.fixture(scope="module")
def eurovoc_releases():
    if not HAS_COMPLETE_EUROVOC:
        pytest.skip("official EuroVoc 4.24 source is not cached")
    return load_eurovoc_4_24_releases(Path(SOURCE_ROOT))


def test_mapping_release_is_separately_pinned_publisher_evidence(mapping_release) -> None:
    assert mapping_release.key == "eurovoc-lcsh-alignment-20240711"
    assert mapping_release.resource_id == "eurovoc-lcsh-alignment"
    assert mapping_release.issued == "2024-07-11"
    assert mapping_release.ring == "subject"
    assert mapping_release.source_release_digest == EUROVOC_LCSH_ALIGNMENT_SHA256
    assert [source.role for source in mapping_release.inputs] == [
        "publisherAlignment",
        "publisherAlignmentReleaseMetadata",
        "publisherSourceReleaseMetadata",
        "currentPublisherLinksetMetadata",
    ]
    assert mapping_release.reviewer_iri == (
        alignments.ATLAS_MAPPING_ADOPTION_REVIEWER_IRI
    )
    assert mapping_release.decision_date == "2026-08-06"
    assert mapping_release.review_method == "operatorAdoption"
    assert mapping_release.confidence is None
    assert mapping_release.metadata["adoptionDecision"] == "atlasOperatorAdoption"
    assert mapping_release.metadata["currentEuroVocRelease"] == "4.24"
    assert mapping_release.metadata["publisherEuroVocVersion"] == "4.20"
    assert mapping_release.metadata["publisherEuroVocRelease"] == (
        EUROVOC_4_20_RELEASE_IRI
    )
    assert mapping_release.metadata["lcshTargetRelease"] == "unspecifiedByPublisher"
    assert mapping_release.metadata["publisherRequalificationForEuroVoc4_24"] is False


def test_mapping_release_preserves_only_the_2003_direct_publisher_triples(
    mapping_release,
) -> None:
    assert len(mapping_release.mappings) == alignments.EUROVOC_LCSH_MAPPING_COUNT
    assert len(
        {
            (row.subject, row.predicate, row.object)
            for row in mapping_release.mappings
        }
    ) == 2_003
    assert Counter(row.predicate for row in mapping_release.mappings) == (
        EXPECTED_PREDICATE_COUNTS
    )
    assert len({row.subject for row in mapping_release.mappings}) == 1_829
    assert len({row.object for row in mapping_release.mappings}) == 1_966
    assert {row.predicate for row in mapping_release.mappings} == {
        str(SKOS.closeMatch),
        str(SKOS.exactMatch),
    }
    assert all(
        row.source_payload == {
            "currentEuroVocLinksetCounts": dict(EXPECTED_PREDICATE_COUNTS),
            "currentEuroVocLinksetMetadataDigest": mapping_release.inputs[3].sha256,
            "currentEuroVocRelease": "4.24",
            "currentMetadataRequalifiesIndividualPairs": False,
            "mappingTripleDigest": mapping_triple_digest(
                subject_iri=row.subject,
                predicate_iri=row.predicate,
                object_iri=row.object,
            ),
            "objectIri": row.object,
            "predicateIri": row.predicate,
            "publisherAlignmentDigest": EUROVOC_LCSH_ALIGNMENT_SHA256,
            "publisherAlignmentIssued": "2024-07-11",
            "publisherAlignmentRelease": mapping_release.source_release_iri,
            "publisherAlignmentVersion": "20240711-0",
            "publisherEuroVocRelease": EUROVOC_4_20_RELEASE_IRI,
            "publisherEuroVocVersion": "4.20",
            "publisherLcshRelease": "unspecifiedByPublisher",
            "subjectIri": row.subject,
        }
        and row.source_digest == EUROVOC_LCSH_ALIGNMENT_SHA256
        and row.source_locator == mapping_release.inputs[0].source_iri
        for row in mapping_release.mappings
    )


def test_lcsh_endpoint_release_covers_every_alignment_target(endpoint_release) -> None:
    assert endpoint_release.key == "lcsh-eurovoc-alignment-endpoints-2026-08-06"
    assert endpoint_release.scope == "captureSubset"
    assert endpoint_release.source_release_digest == (
        "sha256:8a6278bb451422874dbecae55f509d6f3f050fd63997c91679e9a53cee1afe93"
    )
    assert len(endpoint_release.resources) == alignments.LCSH_ALIGNMENT_ENDPOINT_COUNT
    assert len({resource.iri for resource in endpoint_release.resources}) == 1_966
    assert len(endpoint_release.relations) == 933
    assert endpoint_release.metadata["linesScanned"] == 521_055
    assert endpoint_release.metadata["completePublisherRelease"] is False
    assert endpoint_release.metadata["publisherReleaseUnspecified"] is True


def test_lcsh_endpoint_release_is_english_only_and_keeps_publisher_iris_without_lccn(
    endpoint_release,
) -> None:
    assert sum(len(resource.labels) for resource in endpoint_release.resources) == 7_522
    assert endpoint_release.dropped_label_count == 86
    assert all(
        label.language == "en"
        for resource in endpoint_release.resources
        for label in resource.labels
    )
    assert all(
        sum(label.role == "preferred" for label in resource.labels) == 1
        for resource in endpoint_release.resources
    )
    without_lccn = [
        resource for resource in endpoint_release.resources if not resource.notations
    ]
    assert len(without_lccn) == 6
    assert all(resource.native_payload["lccn"] is None for resource in without_lccn)
    assert all(
        resource.iri.startswith("http://id.loc.gov/authorities/subjects/")
        for resource in without_lccn
    )


def test_lcsh_endpoint_release_preserves_all_authority_classes(endpoint_release) -> None:
    assert endpoint_release.metadata["authorityTypeCounts"] == {
        "madsrdf:ComplexSubject": 70,
        "madsrdf:CorporateName": 3,
        "madsrdf:FamilyName": 2,
        "madsrdf:GenreForm": 13,
        "madsrdf:Geographic": 90,
        "madsrdf:Topic": 1_788,
    }
    resource_iris = {resource.iri for resource in endpoint_release.resources}
    assert all(
        relation.subject in resource_iris
        and relation.object in resource_iris
        and relation.predicate == str(SKOS.broader)
        for relation in endpoint_release.relations
    )


def test_mapping_targets_match_the_exact_lcsh_endpoint_release(
    mapping_release,
    endpoint_release,
) -> None:
    assert {row.object for row in mapping_release.mappings} == {
        resource.iri for resource in endpoint_release.resources
    }


def test_mapping_subjects_match_the_complete_eurovoc_release_partitions(
    mapping_release,
    eurovoc_releases,
) -> None:
    resources_by_release = {
        release.key: {resource.iri for resource in release.resources}
        for release in eurovoc_releases
    }
    mapping_subjects = {row.subject for row in mapping_release.mappings}

    assert mapping_subjects <= set().union(*resources_by_release.values())
    assert mapping_subjects & resources_by_release["eurovoc-domains-4.24"] == {
        "http://eurovoc.europa.eu/100162"
    }

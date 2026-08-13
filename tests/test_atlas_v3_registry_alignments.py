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
from refspec.registry.lcsh_topical import LcshTopicalLabel, LcshTopicalRecord

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


def test_mapping_release_is_separately_pinned_evidence_backed_input(
    mapping_release,
) -> None:
    assert mapping_release.key == "eurovoc-lcsh-alignment-20240711"
    assert mapping_release.resource_id == "eurovoc-lcsh-alignment"
    assert mapping_release.issued == "2024-07-11"
    assert mapping_release.ring == "subject"
    assert mapping_release.scope == "publisherRelease"
    assert mapping_release.source_release_digest == EUROVOC_LCSH_ALIGNMENT_SHA256
    assert mapping_release.editorial_policy == (
        alignments.EUROVOC_LCSH_MAPPING_POLICY_PAYLOAD
    )
    assert [source.role for source in mapping_release.inputs] == [
        "publisherAlignment",
        "publisherAlignmentReleaseMetadata",
        "publisherSourceReleaseMetadata",
        "currentPublisherLinksetMetadata",
    ]
    assert {
        row.asserted_at for row in mapping_release.mappings
    } == {alignments.ATLAS_MAPPING_ADOPTION_DECIDED_AT}
    assert {
        evidence.review_warrant
        for row in mapping_release.mappings
        for evidence in row.evidence
    } == {"operatorAdoption"}
    assert {
        evidence.reviewer_iri
        for row in mapping_release.mappings
        for evidence in row.evidence
    } == {alignments.ATLAS_MAPPING_ADOPTION_REVIEWER_IRI}
    assert {
        evidence.attested_at
        for row in mapping_release.mappings
        for evidence in row.evidence
    } == {alignments.ATLAS_MAPPING_ADOPTION_DECIDED_AT}
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
        len(row.evidence) == 1
        and row.evidence[0].native_payload == {
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
        and row.evidence[0].source_digest == EUROVOC_LCSH_ALIGNMENT_SHA256
        and row.evidence[0].source_locator == mapping_release.inputs[0].source_iri
        for row in mapping_release.mappings
    )


def test_mapping_claims_pin_both_exact_atlas_endpoint_releases(mapping_release) -> None:
    # The publisher aligned one EuroVoc domain alongside 1,702 thesaurus
    # concepts, and Atlas loads domains as their own release, so both endpoint
    # releases legitimately appear. Assert the split rather than a single value.
    subject_releases = {row.subject_atlas_release_iri for row in mapping_release.mappings}
    assert subject_releases == {
        alignments.EUROVOC_ATLAS_RELEASE_IRI,
        alignments.EUROVOC_DOMAINS_ATLAS_RELEASE_IRI,
    }
    domain_rows = {
        row.subject
        for row in mapping_release.mappings
        if row.subject_atlas_release_iri == alignments.EUROVOC_DOMAINS_ATLAS_RELEASE_IRI
    }
    assert domain_rows == set(alignments.EUROVOC_DOMAIN_SUBJECT_IRIS)
    assert {
        row.object_atlas_release_iri for row in mapping_release.mappings
    } == {alignments.LCSH_ALIGNMENT_ENDPOINT_ATLAS_RELEASE_IRI}


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
    assert sum(len(resource.labels) for resource in endpoint_release.resources) == 7_608
    assert endpoint_release.dropped_label_count == 0
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


def test_lcsh_adapter_keeps_variant_tagged_label_and_deduplicates_twin() -> None:
    record = LcshTopicalRecord(
        concept_iri="https://example.test/lcsh/one",
        lccn=None,
        preferred_label=LcshTopicalLabel(value="Main heading", language="en"),
        variant_labels=(
            LcshTopicalLabel(value="Main heading", language="en-Latn"),
            LcshTopicalLabel(value="Search synonym", language="en-Latn"),
            LcshTopicalLabel(value="Terme francais", language="fr"),
        ),
        broader_iris=(),
        authority_types=("madsrdf:Authority",),
        source_url="https://example.test/lcsh.ndjson",
        line_number=1,
        raw_line=b"{}",
    )

    labels = alignments._english_labels(record)

    assert [(label.value, label.role, label.language) for label in labels] == [
        ("Main heading", "preferred", "en"),
        ("Search synonym", "alternate", "en"),
    ]


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

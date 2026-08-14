from __future__ import annotations

from pathlib import Path

from refspec.atlas.v3_registry_documents import load_registry_document_releases
from refspec.registry.infrastructure.source_identity import validate_uuid7

ROOT = Path(__file__).resolve().parents[1]


def test_loads_the_gao_witness_and_its_observed_topics() -> None:
    releases = load_registry_document_releases(ROOT)
    by_key = {release.key: release for release in releases}

    # REF-031: the CBO publication population left for SpicyRegs. What stays
    # is the GAO product that witnesses the observed-topics unit.
    assert len(releases) == 2
    assert "cbo-119th-congress-publications" not in by_key
    assert len(by_key["gao-report-gao-26-108505"].resources) == 1
    assert len(by_key["gao-topics-observed-on-gao-26-108505"].resources) == 1
    assert {release.profile for release in releases} == {
        "conceptScheme",
        "identifierScheme",
    }
    assert {release.ring for release in releases} == {"entity", "subject"}
    assert by_key["gao-report-gao-26-108505"].scope == "captureSubset"


def test_gao_report_identity_retains_topic_assignment_as_source_evidence() -> None:
    gao_release = load_registry_document_releases(ROOT)[0]
    report = gao_release.resources[0]

    assert report.iri == "https://www.gao.gov/products/gao-26-108505"
    assert report.identifiers[0].value == "GAO-26-108505"
    assert report.identifiers[0].scheme_iri == gao_release.scheme_iri
    assert report.native_payload["publicationDate"] == "2026-05-12"
    assert report.native_payload["topicAssignments"] == (
        {
            "label": "Auditing and Financial Management",
            "recordIri": (
                "urn:ref:gao-topic-assignment:"
                "c50268888ddb9c7cae2277d55229394b6434ba7503d79a61cb3ff3775a0683fd:"
                "GAO-26-108505:0"
            ),
            "sourceOrdinal": 0,
            "topicPath": "/topics/auditing-and-financial-management",
        },
    )


def test_gao_topic_without_publisher_id_gets_readable_source_scoped_uuid7() -> None:
    releases = load_registry_document_releases(ROOT)
    report_release = releases[0]
    topic_release = releases[1]
    topic = topic_release.resources[0]

    prefix = "urn:ref:source-concept:v2:gao-topics:"
    assert topic.iri.startswith(prefix)
    validate_uuid7(topic.iri.removeprefix(prefix))
    assert topic.labels[0].value == "Auditing and Financial Management"
    assert topic.native_payload["topicPath"] == (
        "/topics/auditing-and-financial-management"
    )
    assert topic.native_payload["conceptIdentityClaimedByPublisher"] is False
    assert len(report_release.cross_ring_relations) == 1
    relation = report_release.cross_ring_relations[0]
    assert relation.subject == report_release.resources[0].iri
    assert relation.object == topic.iri
    assert relation.source_ring == "entity"
    assert relation.target_ring == "subject"
    assert relation.predicate.endswith("#hasIndexedSubject")


def test_document_release_build_is_repeatable() -> None:
    first = load_registry_document_releases(ROOT)
    second = load_registry_document_releases(ROOT)

    assert [release.source_release_digest for release in first] == [
        release.source_release_digest for release in second
    ]
    assert [[resource.iri for resource in release.resources] for release in first] == [
        [resource.iri for resource in release.resources] for release in second
    ]

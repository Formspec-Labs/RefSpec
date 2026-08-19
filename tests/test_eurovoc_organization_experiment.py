"""EuroVoc organization sidecar separation and integrity tests."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from rdflib import Graph

from refspec.registry.eurovoc_organization_experiment import (
    ASSERTIONS_PATH,
    CANDIDATES_PATH,
    CHANGE_EVENTS_PATH,
    MANIFEST_PATH,
    OBJECTS_PATH,
    RIGHTS_PATH,
    EuroVocOrganizationExperimentError,
    build_eurovoc_organization_artifact_from_paths,
    materialize_eurovoc_organization_artifact,
    verify_eurovoc_organization_directory,
)
from refspec.registry.eurovoc_thesaurus import (
    EUROVOC_RELEASE_4_24,
    EuroVocMetadataSource,
    EuroVocReleaseSource,
)

SKOS_IN_SCHEME = "http://www.w3.org/2004/02/skos/core#inScheme"
EUVOC_DOMAIN = "http://publications.europa.eu/ontology/euvoc#domain"
DATASET_IRI = "http://example.test/void.ttl#dataset_eurovoc-20260709"
NORMALIZED_PARTITION = "urn:example:operator-partition:20260708"

SKOS_TURTLE = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix schema: <http://eurovoc.europa.eu/schema#> .

<urn:example:thesaurus> a skos:ConceptScheme ;
    owl:versionInfo "9.9" .

<urn:example:domains> a skos:ConceptScheme .

<urn:example:domain-01> a skos:Concept, schema:Domain ;
    skos:notation "01" ;
    skos:prefLabel "Domain one"@en, "Domaine un"@fr ;
    skos:inScheme <urn:example:domains> .

<urn:example:domain-02> a skos:Concept, schema:Domain ;
    skos:notation "02" ;
    skos:prefLabel "Domain two"@en ;
    skos:inScheme <urn:example:domains> .

<urn:example:micro-0101> a skos:ConceptScheme ;
    skos:notation "0101" ;
    skos:prefLabel "Area one"@en, "Zone un"@fr .

<urn:example:micro-0201> a skos:ConceptScheme ;
    skos:notation "0201" ;
    skos:prefLabel "Area two"@en .

<urn:example:concept-1> a skos:Concept ;
    skos:notation "1" ;
    skos:prefLabel "Concept one"@en ;
    skos:inScheme <urn:example:thesaurus>, <urn:example:micro-0101> .

<urn:example:concept-2> a skos:Concept ;
    skos:notation "2" ;
    skos:prefLabel "Concept two"@en ;
    skos:inScheme <urn:example:thesaurus>, <urn:example:micro-0101>, <urn:example:micro-0201> .

<urn:example:concept-3> a skos:Concept ;
    skos:notation "3" ;
    skos:prefLabel "Concept three"@en ;
    skos:inScheme <urn:example:thesaurus>, <urn:example:micro-0201> .
"""

METADATA_TURTLE = """\
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix void: <http://rdfs.org/ns/void#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .

<http://example.test/void.ttl> a void:DatasetDescription ;
    foaf:primaryTopic <http://example.test/void.ttl#EuroVoc_9.9> .

<http://example.test/void.ttl#dataset_eurovoc-abs> a dcat:Dataset ;
    dcterms:publisher <http://publications.europa.eu/resource/authority/corporate-body/PUBL> ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
    dcat:currentVersion <http://example.test/void.ttl#dataset_eurovoc-20260709> .

<http://example.test/void.ttl#dataset_eurovoc-20260709> a dcat:Dataset ;
    dcat:version "9.9" ;
    dcterms:issued "2026-07-09"^^xsd:date ;
    dcterms:modified "2026-07-09"^^xsd:date ;
    dcat:distribution <http://example.test/void.ttl#EuroVoc_9.9> .

<http://example.test/void.ttl#EuroVoc_9.9> a dcat:Distribution, void:Dataset ;
    dcterms:title "Fixture EuroVoc"@en ;
    void:dataDump <https://example.test/distribution/20260709/eurovoc.zip> ;
    void:classPartition [ void:class skos:Concept ; void:entities 3 ] .
"""


def _zip_payload(member: bytes) -> bytes:
    output = io.BytesIO()
    info = zipfile.ZipInfo("eurovoc.rdf", date_time=(2026, 7, 7, 6, 8, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(info, member)
    return output.getvalue()


def _fixture_inputs(tmp_path: Path) -> tuple[EuroVocReleaseSource, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    graph = Graph()
    graph.parse(data=SKOS_TURTLE, format="turtle")
    member = graph.serialize(format="xml", encoding="utf-8")
    archive = _zip_payload(member)
    metadata = METADATA_TURTLE.encode("utf-8")
    archive_path = tmp_path / "eurovoc.zip"
    metadata_path = tmp_path / "metadata.ttl"
    archive_path.write_bytes(archive)
    metadata_path.write_bytes(metadata)
    metadata_source = EuroVocMetadataSource(
        source_url="https://example.test/acquisition/20260708/metadata.ttl",
        expected_sha256="sha256:" + hashlib.sha256(metadata).hexdigest(),
        expected_byte_length=len(metadata),
        filename="metadata.ttl",
    )
    release = EuroVocReleaseSource(
        release_id="fixture-9.9",
        version="9.9",
        issued="2026-07-08",
        concept_scheme_iri="urn:example:thesaurus",
        source_url="https://example.test/acquisition/20260708/eurovoc.zip",
        landing_page_url="https://example.test/eurovoc",
        expected_sha256="sha256:" + hashlib.sha256(archive).hexdigest(),
        expected_byte_length=len(archive),
        filename="eurovoc.zip",
        member_filename="eurovoc.rdf",
        expected_member_sha256="sha256:" + hashlib.sha256(member).hexdigest(),
        expected_member_byte_length=len(member),
        metadata_source=metadata_source,
    )
    return release, archive_path, metadata_path


def _build(tmp_path: Path):
    release, archive_path, metadata_path = _fixture_inputs(tmp_path)
    return build_eurovoc_organization_artifact_from_paths(
        release,
        archive_path=archive_path,
        metadata_path=metadata_path,
        normalized_partition_iri=NORMALIZED_PARTITION,
    )


def _jsonl(payload: bytes) -> list[dict]:
    return [json.loads(line) for line in payload.decode("utf-8").splitlines()]


def test_experiment_preserves_publisher_memberships_and_separates_domain_candidates(
    tmp_path: Path,
) -> None:
    artifact = _build(tmp_path)
    objects = _jsonl(artifact.files[OBJECTS_PATH])
    assertions = _jsonl(artifact.files[ASSERTIONS_PATH])
    candidates = _jsonl(artifact.files[CANDIDATES_PATH])

    assert len(objects) == 4
    assert sum(row["organizationKind"] == "domain" for row in objects) == 2
    assert sum(row["organizationKind"] == "microthesaurus" for row in objects) == 2
    assert any(
        label["language"] == "fr"
        for row in objects
        for label in row["labels"]
    )

    assert len(assertions) == 4
    assert {row["sourcePredicate"] for row in assertions} == {SKOS_IN_SCHEME}
    assert {row["sourceSubject"] for row in assertions} == {
        "urn:example:concept-1",
        "urn:example:concept-2",
        "urn:example:concept-3",
    }
    assert {row["sourceObject"] for row in assertions} == {
        "urn:example:micro-0101",
        "urn:example:micro-0201",
    }
    assert all(row["sourcePredicate"] != EUVOC_DOMAIN for row in assertions)

    assert len(candidates) == 2
    assert {row["candidatePredicate"] for row in candidates} == {EUVOC_DOMAIN}
    assert all(row["authority"] == "RefSpecOperator" for row in candidates)
    assert all(row["publisherAssertion"] is False for row in candidates)

    manifest = artifact.manifest
    rights = json.loads(artifact.files[RIGHTS_PATH])
    for row in [*objects, *assertions, *candidates]:
        assert row["publisherDatasetIri"] == DATASET_IRI
        assert row["publisherIssued"] == "2026-07-09"
        assert row["normalizedPartitionIri"] == NORMALIZED_PARTITION
        assert row["publisherMetadataArtifactDigest"] == (
            manifest["inputs"]["publisherMetadata"]["sha256"]
        )
        assert row["skosInputArtifactDigest"] == manifest["inputs"]["skosCoreArchive"]["sha256"]
        assert row["skosRdfMemberDigest"] == manifest["inputs"]["skosRdfMember"]["sha256"]
    assert manifest["identityReconciliation"]["status"] == "unresolvedSameVersionLineage"
    assert manifest["identityReconciliation"]["publisherDataset"]["iri"] == DATASET_IRI
    assert manifest["identityReconciliation"]["publisherDistributionMatchesSkosCoreAcquisition"] == []
    assert manifest["claims"]["lifecycleSupport"] is False
    assert manifest["claims"]["publisherOrganizationSlicePreserved"] is True
    assert manifest["claims"]["completePublisherOrganizationGraphPreserved"] is False
    assert manifest["status"]["canonicalAtlas"] is False
    assert manifest["status"]["spicySearchUseAuthorized"] is False
    assert "20260708" in manifest["inputs"]["skosCoreArchive"]["acquisitionUrl"]
    assert "20260709" in manifest["identityReconciliation"]["publisherDataset"]["iri"]
    assert manifest["identityReconciliation"]["publisherDataset"]["iri"] != NORMALIZED_PARTITION
    assert rights["publisherRightsMetadata"]["sourceArtifact"].endswith("/metadata.ttl")
    assert "rightsHolders" not in rights["publisherRightsMetadata"]
    assert rights["sourcePublisher"]["evidencePredicate"] == "http://purl.org/dc/terms/publisher"


def test_experiment_build_is_byte_stable_and_materialization_is_idempotent(
    tmp_path: Path,
) -> None:
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second")
    assert dict(first.files) == dict(second.files)

    output = tmp_path / "experiment"
    assert materialize_eurovoc_organization_artifact(output, first) is True
    verify_eurovoc_organization_directory(output, second)
    assert materialize_eurovoc_organization_artifact(output, second) is False
    assert (output / CHANGE_EVENTS_PATH).read_bytes() == b""
    assert json.loads((output / MANIFEST_PATH).read_text())["canonicalPayloadDigest"] == (
        first.manifest["canonicalPayloadDigest"]
    )


def test_verifier_refuses_a_reversed_or_otherwise_changed_assertion(tmp_path: Path) -> None:
    artifact = _build(tmp_path / "input")
    output = tmp_path / "experiment"
    materialize_eurovoc_organization_artifact(output, artifact)
    rows = _jsonl((output / ASSERTIONS_PATH).read_bytes())
    rows[0]["sourceSubject"], rows[0]["sourceObject"] = (
        rows[0]["sourceObject"],
        rows[0]["sourceSubject"],
    )
    (output / ASSERTIONS_PATH).write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(EuroVocOrganizationExperimentError, match="cold rebuild"):
        verify_eurovoc_organization_directory(output, artifact)


def test_verifier_refuses_an_extra_member(tmp_path: Path) -> None:
    artifact = _build(tmp_path / "input")
    output = tmp_path / "experiment"
    materialize_eurovoc_organization_artifact(output, artifact)
    (output / "unlisted.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(EuroVocOrganizationExperimentError, match="file set differs"):
        verify_eurovoc_organization_directory(output, artifact)


def test_real_pinned_release_builds_the_frozen_organization_counts() -> None:
    """REF-046's audit-gap closure: the module exercised over real bytes.

    Gated on the same two publisher artifacts `claim_release_exports.py`
    already pins (`eurovocSkosCore`/`eurovocMetadata`) -- one shared pin
    for one shared artifact, not a second capture, mirroring how REF-043
    closed the equivalent GCMD gap.
    """

    archive_text = os.environ.get("REFSPEC_EUROVOC_SKOS_CORE_PATH")
    metadata_text = os.environ.get("REFSPEC_EUROVOC_METADATA_PATH")
    if archive_text is None or metadata_text is None:
        pytest.skip("real EuroVoc publisher distribution is not configured")

    artifact = build_eurovoc_organization_artifact_from_paths(
        EUROVOC_RELEASE_4_24,
        archive_path=Path(archive_text),
        metadata_path=Path(metadata_text),
    )

    members_by_role = {member["role"]: member for member in artifact.manifest["members"]}
    assert members_by_role["publisherOrganizationObjects"]["rowCount"] == 148
    assert members_by_role["publisherOrganizationAssertions"]["rowCount"] == 7_902
    assert members_by_role["operatorDerivedDomainCandidates"]["rowCount"] == 127
    assert artifact.manifest["claims"]["publisherOrganizationSlicePreserved"] is True
    assert artifact.manifest["claims"]["publisherMicrothesaurusDomainRelationsPresent"] is False

    objects = _jsonl(artifact.files[OBJECTS_PATH])
    domains = [row for row in objects if row["organizationKind"] == "domain"]
    microthesauri = [row for row in objects if row["organizationKind"] == "microthesaurus"]
    assert len(domains) == 21
    assert len(microthesauri) == 127

    # Cold rebuild determinism: independently regenerating from the same
    # pinned bytes yields byte-identical artifact files.
    again = build_eurovoc_organization_artifact_from_paths(
        EUROVOC_RELEASE_4_24,
        archive_path=Path(archive_text),
        metadata_path=Path(metadata_text),
    )
    assert dict(artifact.files) == dict(again.files)

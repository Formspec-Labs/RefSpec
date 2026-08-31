"""Atlas 3 release tests for GEMET and Northwestern subject mappings."""

from __future__ import annotations

import importlib
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import RDF, Dataset, Namespace, URIRef
from rdflib.namespace import SKOS

from refspec.atlas import v3_registry_alignments_lcsh as lcsh_release
from refspec.atlas import v3_registry_alignments_subject as adapters
from refspec.registry import gemet_alignments as gemet
from refspec.registry import lc_external_links as external
from refspec.registry import lcsh_mesh_mapping as mesh_lcsh
from refspec.registry import umthes_content as umthes

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = adapters.DEFAULT_SOURCE_ROOT
REQUIRED_SOURCES = (
    SOURCE_ROOT / gemet.GEMET_ALIGNMENT_FILENAME,
    SOURCE_ROOT / mesh_lcsh.LCSH_MESH_MAPPING_FILENAME,
    SOURCE_ROOT / adapters.MESH_2026_FILENAME,
    SOURCE_ROOT / adapters.LCSH_BULK_FILENAME,
    SOURCE_ROOT / umthes.UMTHES_CAPTURE_FILENAME,
    # The consolidated LCSH release's referenced-deprecated selection also
    # depends on the LC external-links archive and the EuroVoc-LCSH
    # alignment (see v3_registry_alignments_lcsh.gather_referenced_lcsh_iris).
    SOURCE_ROOT / external.LC_EXTERNAL_LINKS_FILENAME,
    SOURCE_ROOT / "eurovoc-lcsh-alignment-20240711.rdf",
)
HAS_REAL_SOURCES = all(path.is_file() for path in REQUIRED_SOURCES)


def _generator_module():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        return importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))


@pytest.fixture(scope="module")
def gemet_release():
    if not HAS_REAL_SOURCES:
        pytest.skip("pinned subject-mapping sources are not cached")
    return adapters.load_gemet_eurovoc_mapping_release(SOURCE_ROOT)


@pytest.fixture(scope="module")
def mesh_mapping_release():
    if not HAS_REAL_SOURCES:
        pytest.skip("pinned subject-mapping sources are not cached")
    return adapters._lcsh_mesh_mapping_release(SOURCE_ROOT)


@pytest.fixture(scope="module")
def consolidated_lcsh_release():
    if not HAS_REAL_SOURCES:
        pytest.skip("pinned subject-mapping sources are not cached")
    return lcsh_release.load_lcsh_consolidated_release(SOURCE_ROOT)


@pytest.fixture(scope="module")
def umthes_assets():
    if not HAS_REAL_SOURCES:
        pytest.skip("pinned subject-mapping sources are not cached")
    return adapters._umthes_assets(SOURCE_ROOT)


@pytest.mark.slow
def test_gemet_release_emits_only_the_immediately_joinable_held_pair(gemet_release) -> None:
    assert gemet_release.key == "gemet-eurovoc-alignments-4.2.3"
    assert len(gemet_release.mappings) == 1_936
    assert Counter(row.predicate for row in gemet_release.mappings) == {
        str(SKOS.broadMatch): 215,
        str(SKOS.exactMatch): 1_683,
        str(SKOS.narrowMatch): 38,
    }
    assert {(row.subject_atlas_release_iri, row.object_atlas_release_iri) for row in gemet_release.mappings} == {
        (adapters.GEMET_ATLAS_RELEASE_IRI, adapters.EUROVOC_ATLAS_RELEASE_IRI)
    }
    assert all(row.subject.startswith(gemet.GEMET_CONCEPT_PREFIX) for row in gemet_release.mappings)
    assert all(row.object.startswith(gemet.TARGET_PREFIXES["eurovoc"]) for row in gemet_release.mappings)
    assert gemet_release.metadata["externalEndpointCounts"] == {
        "agrovoc": 1_199,
        "dbpedia": 3_006,
        "eionet-determinations": 32,
        "umthes": 3_483,
    }
    assert sum(gemet_release.metadata["externalEndpointCounts"].values()) == 7_720
    assert gemet_release.metadata["externalEndpointDisposition"] == {
        "umthes": "emittedBySeparateContentfulEndpointAndMappingReleases",
        "remaining": "capturedByReaderPendingSourceFaithfulEndpointReleases",
    }
    assert gemet_release.metadata["heldEndpointPublisherAssertionCount"] == 1_938
    assert gemet_release.metadata["skosS46RefusalCount"] == 2
    assert {
        (row["subjectIri"], row["predicateIri"], row["objectIri"])
        for row in gemet_release.metadata["skosS46RefusedPublisherClaims"]
    } == adapters.GEMET_EUROVOC_S46_REFUSALS["gemet"]


@pytest.mark.slow
def test_gemet_release_carries_verbatim_publisher_assertions(gemet_release) -> None:
    for row in gemet_release.mappings:
        (evidence,) = row.evidence
        claim = evidence.native_payload["publisherClaim"]
        assert evidence.review_warrant == "publisherAssertion"
        assert evidence.reviewer_iri == adapters.GEMET_PUBLISHER_ATTESTOR_IRI
        assert claim["subjectIri"] == row.subject
        assert claim["predicateIri"] == row.predicate
        assert claim["objectIri"] == row.object
        assert "operatorAdoption" not in evidence.native_payload

    assert gemet_release.metadata["licenseStatement"] == gemet.GEMET_LICENSE_STATEMENT
    assert gemet_release.metadata["licenseUrl"] == gemet.GEMET_LICENSE_URL
    assert gemet_release.metadata["retrievedAt"] == gemet.GEMET_ALIGNMENT_RETRIEVED_AT
    assert gemet_release.metadata["sourceUrl"] == gemet.GEMET_ALIGNMENT_SOURCE_URL
    assert gemet_release.metadata["sourceDigest"] == gemet.GEMET_ALIGNMENT_SHA256
    assert gemet_release.metadata["sourceByteLength"] == gemet.GEMET_ALIGNMENT_BYTE_LENGTH
    assert gemet_release.metadata["versionedSourceUrl"] is True
    assert gemet_release.metadata["rollingSourceUrl"] is False


@pytest.mark.slow
def test_umthes_endpoints_carry_real_multilingual_publisher_content(umthes_assets) -> None:
    endpoint, _mapping = umthes_assets

    assert endpoint.key == adapters.UMTHES_ENDPOINT_RELEASE_KEY
    assert len(endpoint.resources) == 3_365
    assert len(endpoint.relations) == 4_900
    assert Counter(resource.status for resource in endpoint.resources) == {
        "alignmentEndpoint": 2_391,
        "deprecatedAlignmentEndpoint": 974,
    }
    assert endpoint.metadata["labelCountsByLanguage"] == {"de": 11_127, "en": 6_116}
    assert endpoint.metadata["publisherLabelCount"] == 17_243
    assert endpoint.metadata["emittedLabelCount"] == 17_241
    assert endpoint.metadata["duplicateAcrossRoleLabelClaimCount"] == 2
    assert endpoint.metadata["definitionCountsByLanguage"] == {}
    assert endpoint.metadata["capturedRelationCount"] == 13_060
    assert endpoint.metadata["emittedRelationCount"] == 4_900
    assert endpoint.metadata["unemittedRelationCount"] == 8_160
    assert endpoint.metadata["skosS27Transformation"] == {
        "frozenConflictList": {
            "canonicalItemShape": {"leftIri": "IRI", "rightIri": "IRI"},
            "count": 25,
            "digest": adapters.UMTHES_S27_RELATED_PAIR_DIGEST,
        },
        "publisherRelationCount": 50,
        "reason": "SKOS-S27-hierarchy-path",
        "toPredicateIri": adapters.ATLAS_THESAURUS_RELATED,
    }
    assert endpoint.metadata["unavailableEndpointCount"] == 13
    assert endpoint.metadata["licenseStatement"] == umthes.UMTHES_LICENSE_STATEMENT
    assert endpoint.metadata["attributionStatement"] == umthes.UMTHES_ATTRIBUTION_STATEMENT
    assert endpoint.metadata["licensingIsAdmissionGate"] is False
    assert all(resource.labels for resource in endpoint.resources)


@pytest.mark.slow
def test_gemet_umthes_mappings_resolve_the_publisher_namespace(umthes_assets) -> None:
    endpoint, release = umthes_assets

    assert release.key == adapters.GEMET_UMTHES_MAPPING_RELEASE_KEY
    assert len(release.mappings) == 3_470
    assert Counter(row.predicate for row in release.mappings) == {
        str(SKOS.closeMatch): 3_469,
        str(SKOS.exactMatch): 1,
    }
    assert release.metadata["unavailableMappingCount"] == 13
    assert {row.object for row in release.mappings} <= {resource.iri for resource in endpoint.resources}
    for row in release.mappings:
        evidence = row.evidence[0]
        claim = evidence.native_payload["publisherClaim"]
        resolution = evidence.native_payload["endpointResolution"]
        assert evidence.review_warrant == "publisherAssertion"
        assert claim["objectIri"].startswith(umthes.UMTHES_LEGACY_PREFIX)
        assert row.object.startswith(umthes.UMTHES_CURRENT_PREFIX)
        assert resolution == {
            "fromObjectIri": claim["objectIri"],
            "method": "publisherNamespaceMigrationByStableLocalIdentifier",
            "predicateChanged": False,
            "toObjectIri": row.object,
        }


@pytest.mark.slow
def test_lcsh_mesh_release_is_an_e3_opt_in_adoption(
    mesh_mapping_release,
    consolidated_lcsh_release,
) -> None:
    # REF-040 retired this module's own bespoke active-only LCSH endpoint
    # capture: the LCSH (object) side now resolves against the consolidated
    # LCSH release, which also admits a deprecated-but-referenced target.
    release = mesh_mapping_release

    assert len(release.mappings) == 13_260
    assert len({row.subject for row in release.mappings}) == 12_702
    assert Counter(row.predicate for row in release.mappings) == {
        str(SKOS.broadMatch): 134,
        str(SKOS.exactMatch): 13_062,
        str(SKOS.narrowMatch): 35,
        str(SKOS.relatedMatch): 29,
    }
    assert {(row.subject_atlas_release_iri, row.object_atlas_release_iri) for row in release.mappings} == {
        (adapters.MESH_ATLAS_RELEASE_IRI, lcsh_release.LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI)
    }
    assert {row.object for row in release.mappings} <= {
        resource.iri for resource in consolidated_lcsh_release.resources
    }
    assert all(row.subject.startswith(mesh_lcsh.MESH_DESCRIPTOR_PREFIX) for row in release.mappings)
    assert all(row.object.startswith(mesh_lcsh.LCSH_SUBJECT_PREFIX) for row in release.mappings)
    assert "opt-in" in release.editorial_policy["serving"]
    assert "defaultServedPredicateIri" not in release.metadata
    assert "defaultServed" not in release.metadata


@pytest.mark.slow
def test_lcsh_mesh_evidence_records_each_marc_translation(mesh_mapping_release) -> None:
    release = mesh_mapping_release

    for row in release.mappings:
        for evidence in row.evidence:
            claim = evidence.native_payload["publisherClaim"]
            adoption = evidence.native_payload["operatorAdoption"]
            assert evidence.review_warrant == "operatorAdoption"
            assert evidence.reviewer_iri == adapters.LCSH_MESH_ADOPTED_BY
            assert claim["subjectIri"] == row.subject
            assert claim["predicateIri"] == mesh_lcsh.MARC_750_FIELD_IRI
            assert claim["objectIri"] == row.object
            assert adoption == {
                "adoptedBy": adapters.LCSH_MESH_ADOPTED_BY,
                "fromPredicateIri": mesh_lcsh.MARC_750_FIELD_IRI,
                "toPredicateIri": row.predicate,
            }

    assert release.metadata["licenseStatement"] == mesh_lcsh.LCSH_MESH_LICENSE_STATEMENT
    assert release.metadata["licenseUrl"] == mesh_lcsh.LCSH_MESH_LICENSE_URL
    assert release.metadata["retrievedAt"] == mesh_lcsh.LCSH_MESH_MAPPING_RETRIEVED_AT
    assert release.metadata["sourceUrl"] == mesh_lcsh.LCSH_MESH_MAPPING_SOURCE_URL
    assert release.metadata["sourceDigest"] == mesh_lcsh.LCSH_MESH_MAPPING_SHA256
    assert release.metadata["sourceByteLength"] == mesh_lcsh.LCSH_MESH_MAPPING_BYTE_LENGTH
    assert release.metadata["versionedSourceUrl"] is True
    assert release.metadata["unavailableCurrentEndpointMappingCount"] == 10
    assert release.metadata["refusalCounts"] == dict(mesh_lcsh.EXPECTED_REFUSAL_COUNTS)


@pytest.mark.slow
def test_new_releases_pass_all_three_population_refusal_guards(
    gemet_release,
    mesh_mapping_release,
    umthes_assets,
) -> None:
    # The consolidated LCSH release these mappings' targets resolve against
    # is exercised by its own refusal-guard checks in
    # test_atlas_v3_registry_alignments.py and
    # test_atlas_v3_registry_alignments_lc.py; this test covers only the
    # releases this module itself mints.
    generator = _generator_module()
    umthes_endpoint, umthes_mapping = umthes_assets
    shaped_releases = [umthes_endpoint]
    for release in (gemet_release, umthes_mapping, mesh_mapping_release):
        endpoint_iris = {endpoint_iri for row in release.mappings for endpoint_iri in (row.subject, row.object)}
        shaped_releases.append(
            SimpleNamespace(
                spec=SimpleNamespace(
                    key=release.key,
                    logical_path=release.inputs[0].logical_path,
                    input_pins=release.inputs,
                ),
                scheme_iri=f"urn:ref:atlas-mapping-endpoints:{release.key}",
                resources=tuple(SimpleNamespace(iri=iri) for iri in endpoint_iris),
            )
        )

    for release in shaped_releases:
        loaded = (
            SimpleNamespace(
                spec=SimpleNamespace(
                    key=release.key,
                    logical_path=release.inputs[0].logical_path,
                    input_pins=release.inputs,
                ),
                scheme_iri=release.scheme_iri,
                resources=release.resources,
            )
            if release is umthes_endpoint
            else release
        )
        generator._refuse_registrant_population_release(loaded)
        generator._refuse_document_population_release(loaded)
        generator._refuse_observed_inventory_release(loaded)


@pytest.mark.slow
def test_lcsh_endpoint_identifier_tripwire_is_nonvacuous(mesh_mapping_release, umthes_assets) -> None:
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
    assert mesh_mapping_release.metadata["sourceIdentifierCount"] == 0
    umthes_endpoint, umthes_mapping = umthes_assets
    assert umthes_endpoint.metadata["sourceIdentifierCount"] == 0
    assert umthes_mapping.metadata["sourceIdentifierCount"] == 0
    assert all(not resource.identifiers for resource in umthes_endpoint.resources)


@pytest.mark.slow
def test_new_mapping_releases_never_mint_an_inverse_or_closure(
    gemet_release,
    mesh_mapping_release,
    umthes_assets,
) -> None:
    _umthes_endpoint, umthes_mapping = umthes_assets
    for release in (gemet_release, umthes_mapping, mesh_mapping_release):
        triples = {(row.subject, row.predicate, row.object) for row in release.mappings}
        assert len(triples) == len(release.mappings)
        assert all((obj, predicate, subject) not in triples for subject, predicate, obj in triples)


def test_group_loaders_refuse_unknown_keys_without_opening_sources() -> None:
    with pytest.raises(ValueError, match="does not know release keys"):
        adapters.load_subject_registry_alignment_endpoint_releases(
            ROOT,
            only_keys={"not-an-endpoint-release"},
        )
    with pytest.raises(ValueError, match="does not know release keys"):
        adapters.load_subject_registry_mapping_releases(
            ROOT,
            only_keys={"not-a-mapping-release"},
        )


@pytest.mark.skipif(not HAS_REAL_SOURCES, reason="pinned subject-mapping sources are not cached")
def test_mapping_group_loader_selects_only_the_requested_release() -> None:
    releases = adapters.load_subject_registry_mapping_releases(
        SOURCE_ROOT,
        only_keys={"gemet-eurovoc-alignments-4.2.3"},
    )

    assert [release.key for release in releases] == ["gemet-eurovoc-alignments-4.2.3"]


@pytest.mark.skipif(not HAS_REAL_SOURCES, reason="pinned subject-mapping sources are not cached")
def test_adapter_refuses_gemet_source_drift(tmp_path: Path) -> None:
    target = tmp_path / gemet.GEMET_ALIGNMENT_FILENAME
    shutil.copyfile(SOURCE_ROOT / gemet.GEMET_ALIGNMENT_FILENAME, target)
    target.write_bytes(target.read_bytes() + b"drift")

    with pytest.raises(ValueError, match="input pin differs"):
        adapters.load_gemet_eurovoc_mapping_release(tmp_path)

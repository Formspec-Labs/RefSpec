"""Atlas 3 release tests for bulk FAST and EuroVoc publisher alignments."""

from __future__ import annotations

import importlib
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib.namespace import SKOS

from refspec.atlas import v3_registry_alignments_bulk as adapters
from refspec.registry import eurovoc_alignment_portfolio as eurovoc
from refspec.registry import oclc_fast_external_links as fast

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = adapters.DEFAULT_SOURCE_ROOT
REQUIRED_SOURCES = (
    SOURCE_ROOT / fast.FAST_EXTERNAL_LINKS_FILENAME,
    *(SOURCE_ROOT / pin.filename for pin in eurovoc.EUROVOC_ALIGNMENT_PINS),
)
HAS_REAL_SOURCES = all(path.is_file() for path in REQUIRED_SOURCES)


def _generator_module():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        return importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.remove(str(ROOT / "tools"))


@pytest.fixture(scope="module")
def releases():
    if not HAS_REAL_SOURCES:
        pytest.skip("pinned bulk mapping sources are not cached")
    loaded = adapters.load_all_registry_bulk_mapping_releases(SOURCE_ROOT)
    return {release.key: release for release in loaded}


@pytest.fixture(scope="module")
def see_also_endpoint():
    if not HAS_REAL_SOURCES:
        pytest.skip("pinned bulk mapping sources are not cached")
    return adapters.load_fast_bulk_see_also_endpoint_release(SOURCE_ROOT)


@pytest.mark.slow
def test_group_topology_is_one_fast_delta_and_two_eurovoc_pairs(releases) -> None:
    assert set(releases) == adapters.BULK_REGISTRY_MAPPING_RELEASE_KEYS
    assert {key: len(release.mappings) for key, release in releases.items()} == {
        "eurovoc-gemet-alignment-20201218": 1_998,
        "eurovoc-mesh-alignment-20171215": 5,
        "fast-bulk-external-links-delta-2026-07-27": 9,
    }
    assert all(release.ring == "subject" for release in releases.values())
    assert all(release.scope == "captureSubset" for release in releases.values())


@pytest.mark.slow
def test_fast_bulk_release_emits_only_the_frozen_nonoverlapping_delta(releases) -> None:
    release = releases["fast-bulk-external-links-delta-2026-07-27"]
    triples = {(row.subject, row.predicate, row.object) for row in release.mappings}

    assert triples == set(adapters.FAST_BULK_DELTA_CLAIMS)
    assert Counter(row.predicate for row in release.mappings) == {
        str(SKOS.relatedMatch): 9,
    }
    assert release.metadata["reconciliation"] == {
        "bulkHeldEndpointCount": 64_461,
        "bulkHeldEndpointPredicateCounts": {
            str(SKOS.exactMatch): 1_683,
            str(SKOS.relatedMatch): 62_778,
        },
        "bulkOnlyDeltaCount": 9,
        "bulkOnlyDeltaPredicateCounts": {str(SKOS.relatedMatch): 9},
        "choice": "emitBulkOnlyDelta",
        "currentMarcDerivedCount": 64_464,
        "currentOnlyCount": 12,
        "currentOnlyPredicateCounts": {str(SKOS.relatedMatch): 12},
        "currentPredicateCounts": {
            str(SKOS.exactMatch): 1_683,
            str(SKOS.relatedMatch): 62_781,
        },
        "evidence": (
            "The October 2024 bulk snapshot does not strictly contain the current MARC-derived scope: "
            "nine held-endpoint claims occur only in bulk and 12 occur only after later changes."
        ),
        "overlapCount": 64_452,
        "overlapEmitted": False,
        "overlapPredicateCounts": {
            str(SKOS.exactMatch): 1_683,
            str(SKOS.relatedMatch): 62_769,
        },
        "supersedesCurrentScope": False,
    }


@pytest.mark.slow
def test_fast_bulk_release_records_complete_capture_refusals_and_endpoint_accounting(releases) -> None:
    metadata = releases["fast-bulk-external-links-delta-2026-07-27"].metadata

    assert metadata["bulkCapture"]["assertionCount"] == 935_540
    assert metadata["bulkCapture"]["predicateCounts"] == {
        fast.RDFS_SEE_ALSO: 155_171,
        fast.SCHEMA_SAME_AS: 311_890,
        fast.SKOS_RELATED_MATCH: 468_479,
    }
    assert metadata["bulkCapture"]["refusedPredicateCounts"] == {
        fast.RDFS_SEE_ALSO: 2,
        fast.OWL_SAME_AS: 2,
    }
    assert metadata["endpointAccounting"] == {
        "bothEndpointsHeldUniqueAssertionCount": 64_461,
        "externalObjectStatementCount": 714_716,
        "externalSubjectStatementCount": 14_017,
        "heldObjectStatementCount": 65_653,
        "heldObjectUniqueAssertionCount": 65_652,
        "heldSubjectStatementCount": 766_352,
        "selectedExternalSubjectStatementCount": 1_192,
        "selectedExternalSubjectUniqueAssertionCount": 1_191,
    }


@pytest.mark.slow
def test_fast_warrants_preserve_related_and_record_same_as_adoption(releases) -> None:
    release = releases["fast-bulk-external-links-delta-2026-07-27"]
    for row in release.mappings:
        (evidence,) = row.evidence
        assert evidence.review_warrant == "publisherAssertion"
        assert evidence.native_payload["publisherClaim"]["predicateIri"] == fast.SKOS_RELATED_MATCH
        assert evidence.native_payload["predicateIri"] == str(SKOS.relatedMatch)
        assert "operatorAdoption" not in evidence.native_payload

    fixture = ROOT / "tests" / "fixtures" / "oclc_fast_external_links" / "fast-external-links-mini.nt"
    link = fast.parse_oclc_fast_external_link_statement(
        fixture.read_bytes().splitlines(keepends=True)[0],
        line_number=1,
    )
    assert link is not None
    evidence = adapters._fast_bulk_evidence(
        link,
        mapping_predicate=str(SKOS.exactMatch),
        source_pin=adapters._fast_bulk_input(SOURCE_ROOT),
    )
    assert evidence.review_warrant == "operatorAdoption"
    assert evidence.native_payload["operatorAdoption"] == {
        "adoptedBy": adapters.FAST_LCSH_ADOPTION_REVIEWER_IRI,
        "fromPredicateIri": fast.SCHEMA_SAME_AS,
        "toPredicateIri": str(SKOS.exactMatch),
    }


@pytest.mark.slow
def test_fast_see_also_keeps_content_but_emits_no_unlicensed_semantic_relation(
    see_also_endpoint,
) -> None:
    assert len(see_also_endpoint.resources) == 45_929
    assert Counter(resource.status for resource in see_also_endpoint.resources) == {
        "deprecatedAlignmentEndpoint": 45_927,
        "alignmentEndpoint": 2,
    }
    assert see_also_endpoint.metadata["missingEndpointCount"] == 668
    assert all(
        resource.labels
        and resource.native_payload["publisherLanguageTagPresent"] is False
        and "publisherLanguageTag" not in resource.native_payload
        and "publisherLanguageTag" not in resource.native_payload["label"]
        for resource in see_also_endpoint.resources
    )
    assert len(see_also_endpoint.relations) == adapters.FAST_SEE_ALSO_EMITTED_ASSERTION_COUNT == 0
    assert see_also_endpoint.metadata["assertionComposition"]["publisherSeeAlso"] == {
        "contentBackedAssertionCount": 47_049,
        "emittedAssertionCount": 0,
        "predicateIri": fast.RDFS_SEE_ALSO,
        "semanticDisposition": "counted source navigation; no Atlas 3.1 semantic predicate",
    }
    assert see_also_endpoint.metadata["endpointAccounting"] == {
        "capturedFastSeeAlsoCount": 78_981,
        "capturedWikipediaSeeAlsoCount": 76_190,
        "contentBackedFastSeeAlsoCount": 47_049,
        "contentfulCapturedEndpointCount": 45_929,
        "emittedAssertionCount": 0,
        "missingFastEndpointAssertionCount": 31_932,
        "missingFastEndpointCount": 668,
        "wikipediaAssertionDisposition": "omitted because no target publisher content is captured",
    }
    assert see_also_endpoint.metadata["skosS27ConflictList"] == {
        "canonicalItemShape": {"leftIri": "IRI", "rightIri": "IRI"},
        "count": 0,
        "digest": adapters.FAST_SEE_ALSO_S27_CONFLICT_PAIR_DIGEST,
    }


@pytest.mark.slow
def test_fast_release_records_the_rolling_source_pin_and_license(releases) -> None:
    metadata = releases["fast-bulk-external-links-delta-2026-07-27"].metadata
    assert metadata["licenseStatement"] == fast.FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT
    assert metadata["licenseUrl"] == fast.FAST_EXTERNAL_LINKS_LICENSE_URL
    assert metadata["licenseTitle"] == fast.FAST_EXTERNAL_LINKS_LICENSE_TITLE
    assert metadata["licensingIsAdmissionGate"] is False
    assert metadata["retrievalPrecision"] == "dateOnly"
    assert metadata["sourceHasVersionedUrl"] is False
    assert metadata["sourceCapture"] == {
        "byteLength": fast.FAST_EXTERNAL_LINKS_BYTE_LENGTH,
        "retrievedAt": fast.FAST_EXTERNAL_LINKS_RETRIEVED_AT,
        "sha256": fast.FAST_EXTERNAL_LINKS_SHA256,
        "sourceUrl": fast.FAST_EXTERNAL_LINKS_SOURCE_URL,
        "sourceVersionNote": (
            "OCLC publishes this rolling URL without a versioned path; the digest and byte length pin this capture."
        ),
    }


@pytest.mark.slow
def test_eurovoc_gemet_and_mesh_land_every_currently_held_pair(releases) -> None:
    gemet = releases["eurovoc-gemet-alignment-20201218"]
    mesh = releases["eurovoc-mesh-alignment-20171215"]

    assert Counter(row.predicate for row in gemet.mappings) == {
        str(SKOS.closeMatch): 79,
        str(SKOS.exactMatch): 1_919,
    }
    assert Counter(row.predicate for row in mesh.mappings) == {
        str(SKOS.exactMatch): 5,
    }
    assert {(row.subject_atlas_release_iri, row.object_atlas_release_iri) for row in gemet.mappings} == {
        (adapters.EUROVOC_ATLAS_RELEASE_IRI, adapters.GEMET_ATLAS_RELEASE_IRI)
    }
    assert {(row.subject_atlas_release_iri, row.object_atlas_release_iri) for row in mesh.mappings} == {
        (adapters.EUROVOC_ATLAS_RELEASE_IRI, adapters.MESH_ATLAS_RELEASE_IRI)
    }
    assert gemet.metadata["bothEndpointsHeldCount"] == 2_035
    assert gemet.metadata["emittedAssertionCount"] == 1_998
    assert gemet.metadata["skosS46RefusalCount"] == 37
    assert {
        (row["subjectIri"], row["predicateIri"], row["objectIri"])
        for row in gemet.metadata["skosS46RefusedPublisherClaims"]
    } == adapters.GEMET_EUROVOC_S46_REFUSALS["eurovoc"]


@pytest.mark.slow
def test_eurovoc_warrants_are_verbatim_publisher_assertions(releases) -> None:
    gemet = releases["eurovoc-gemet-alignment-20201218"]
    mesh = releases["eurovoc-mesh-alignment-20171215"]

    for row in gemet.mappings:
        (evidence,) = row.evidence
        claim = evidence.native_payload["publisherClaim"]
        assert evidence.review_warrant == "publisherAssertion"
        assert (claim["subjectIri"], claim["predicateIri"], claim["objectIri"]) == (
            row.subject,
            row.predicate,
            row.object,
        )
        assert "operatorAdoption" not in evidence.native_payload

    for row in mesh.mappings:
        (evidence,) = row.evidence
        claim = evidence.native_payload["publisherClaim"]
        resolution = evidence.native_payload["endpointResolution"]
        assert evidence.review_warrant == "publisherAssertion"
        assert claim["subjectIri"] == row.subject
        assert claim["predicateIri"] == row.predicate
        assert claim["objectIri"].startswith(adapters.MESH_HTTP_IRI_PREFIX)
        assert row.object.startswith(adapters.MESH_HTTPS_IRI_PREFIX)
        assert resolution == {
            "fromObjectIri": claim["objectIri"],
            "method": "publisherIdentifierHttpToHttpsRedirect",
            "predicateChanged": False,
            "toObjectIri": row.object,
        }


@pytest.mark.slow
def test_eurovoc_releases_record_all_17_pins_counts_and_rights(releases) -> None:
    for key in ("eurovoc-gemet-alignment-20201218", "eurovoc-mesh-alignment-20171215"):
        metadata = releases[key].metadata
        assert metadata["licenseStatement"] == "publisher states no license"
        assert metadata["licensingIsAdmissionGate"] is False
        assert metadata["generalReuseBasis"] == eurovoc.EUROVOC_ALIGNMENT_GENERAL_REUSE_BASIS_URL
        assert metadata["thirdPartyRightsExclusion"] == (eurovoc.EUROVOC_ALIGNMENT_THIRD_PARTY_RIGHTS_EXCLUSION)
        assert metadata["portfolioAssertionCountExcludingLcsh"] == 22_710
        assert metadata["catalogueAssertionCountIncludingLcsh"] == 24_713
        assert metadata["catalogueExactMatchRatio"] == {
            "denominator": 10_000,
            "numerator": 9_375,
        }
        assert len(metadata["portfolioCapture"]) == 17
        assert sum(item["assertionCount"] for item in metadata["portfolioCapture"]) == 22_710
        assert sum(item["bothEndpointsHeldAssertionCount"] for item in metadata["portfolioCapture"]) == 2_040
        assert sum(item["heldTargetAssertionCount"] for item in metadata["portfolioCapture"]) == 2_042
        assert sum(item["externalTargetAssertionCount"] for item in metadata["portfolioCapture"]) == 20_668
        by_alignment = {item["key"]: item for item in metadata["portfolioCapture"]}
        assert (
            by_alignment["gemet"]["bothEndpointsHeldAssertionCount"],
            by_alignment["gemet"]["externalEndpointAssertionCount"],
            by_alignment["gemet"]["heldTargetAssertionCount"],
            by_alignment["gemet"]["externalTargetAssertionCount"],
        ) == (2_035, 1, 2_036, 0)
        assert (
            by_alignment["mesh"]["bothEndpointsHeldAssertionCount"],
            by_alignment["mesh"]["externalEndpointAssertionCount"],
            by_alignment["mesh"]["heldTargetAssertionCount"],
            by_alignment["mesh"]["externalTargetAssertionCount"],
        ) == (5, 6, 6, 5)
        assert all(
            set(item["sourceCapture"]) == {"byteLength", "retrievedAt", "sha256", "sourceUrl", "sourceVersionNote"}
            for item in metadata["portfolioCapture"]
        )


@pytest.mark.slow
def test_releases_never_mint_inverse_or_transitive_claims(releases) -> None:
    all_triples = {
        (row.subject, row.predicate, row.object) for release in releases.values() for row in release.mappings
    }
    assert len(all_triples) == sum(len(release.mappings) for release in releases.values())
    assert all((obj, predicate, subject) not in all_triples for subject, predicate, obj in all_triples)


@pytest.mark.slow
def test_mapping_inputs_pass_all_three_population_refusal_guards(releases, see_also_endpoint) -> None:
    generator = _generator_module()
    for release in releases.values():
        endpoints = {iri for row in release.mappings for iri in (row.subject, row.object)}
        shaped = SimpleNamespace(
            spec=SimpleNamespace(
                key=release.key,
                logical_path=release.inputs[0].logical_path,
                input_pins=release.inputs,
            ),
            scheme_iri=f"urn:ref:atlas-mapping-endpoints:{release.key}",
            resources=tuple(SimpleNamespace(iri=iri) for iri in endpoints),
        )
        generator._refuse_registrant_population_release(shaped)
        generator._refuse_document_population_release(shaped)
        generator._refuse_observed_inventory_release(shaped)
    shaped_endpoint = SimpleNamespace(
        spec=SimpleNamespace(
            key=see_also_endpoint.key,
            logical_path=see_also_endpoint.inputs[0].logical_path,
            input_pins=see_also_endpoint.inputs,
        ),
        scheme_iri=see_also_endpoint.scheme_iri,
        resources=see_also_endpoint.resources,
    )
    generator._refuse_registrant_population_release(shaped_endpoint)
    generator._refuse_document_population_release(shaped_endpoint)
    generator._refuse_observed_inventory_release(shaped_endpoint)


@pytest.mark.slow
def test_identifier_authority_tripwire_stays_empty(releases, see_also_endpoint) -> None:
    for release in releases.values():
        assert release.metadata["sourceIdentifierCount"] == 0
        for row in release.mappings:
            for evidence in row.evidence:
                assert "identifiers" not in evidence.native_payload
                assert "identifierScheme" not in evidence.native_payload
    assert see_also_endpoint.metadata["sourceIdentifierCount"] == 0
    assert all(not resource.identifiers for resource in see_also_endpoint.resources)


def test_group_loader_refuses_unknown_keys_without_opening_sources() -> None:
    with pytest.raises(ValueError, match="does not know release keys"):
        adapters.load_all_registry_bulk_mapping_releases(
            ROOT,
            only_keys={"not-a-bulk-mapping-release"},
        )

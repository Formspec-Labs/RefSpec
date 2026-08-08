from __future__ import annotations

import hashlib
import os
from collections import Counter
from pathlib import Path

import pytest
from rdflib.namespace import RDF, SKOS, XSD

from refspec.atlas.registry_claim_input import (
    AtlasRegistryClaimInput,
    adapt_registry_claim_release,
    validate_atlas_registry_claims,
)
from refspec.registry.claim_release_exports import (
    EUROVOC_CLAIM_RELEASE_ID,
    GEMET_CLAIM_RELEASE_ID,
    export_eurovoc_4_24_claim_release,
    export_gemet_4_2_3_claim_release,
)
from refspec.registry.infrastructure.rdf_claim_export import (
    extract_rdf_claims,
    parse_rdf_graph,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE_ROOT = ROOT / "output" / "registry-real-data-sources"
RELEASE_ID = "urn:ref:registry-claim-release:test-rdf:v1"
RECIPE_ID = "urn:ref:recipe:test-rdf-export:v1"
SOURCE_IRI = "https://example.test/source.ttl"

RDF_FIXTURE = b"""@prefix ex: <https://example.test/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:one a skos:Concept ;
  skos:prefLabel " One "@en ;
  skos:prefLabel "Un"@fr ;
  skos:broader ex:two ;
  ex:empty ""^^xsd:dateTime ;
  ex:details [ ex:value "blank-node shape" ] .
"""


def test_rdf_export_preserves_terms_and_declares_omissions() -> None:
    digest = "sha256:" + hashlib.sha256(RDF_FIXTURE).hexdigest()
    extraction = extract_rdf_claims(
        parse_rdf_graph(RDF_FIXTURE, rdf_format="turtle", public_id=SOURCE_IRI),
        release_id=RELEASE_ID,
        source_locator=SOURCE_IRI,
        source_digest=digest,
        logical_path="raw/source.ttl",
        recipe_id=RECIPE_ID,
    )

    assert extraction.source_triple_count == 7
    assert extraction.omitted_non_english_literal_count == 1
    assert extraction.omitted_blank_node_claim_count == 2
    assert extraction.omitted_unsupported_term_count == 0
    assert len(extraction.claims) == 4
    preferred = next(
        claim for claim in extraction.claims if claim.predicate == str(SKOS.prefLabel)
    )
    assert preferred.lexical_value == " One "
    assert preferred.language == "en"
    broader = next(
        claim for claim in extraction.claims if claim.predicate == str(SKOS.broader)
    )
    assert broader.subject == "https://example.test/one"
    assert broader.object_iri == "https://example.test/two"
    typed = next(
        claim for claim in extraction.claims if claim.predicate == "https://example.test/empty"
    )
    assert typed.lexical_value == ""
    assert typed.datatype == str(XSD.dateTime)
    assert any(claim.predicate == str(RDF.type) for claim in extraction.claims)


@pytest.mark.skipif(
    os.environ.get("REFSPEC_REGISTRY_CLAIM_REAL_DATA") != "1",
    reason="set REFSPEC_REGISTRY_CLAIM_REAL_DATA=1 to export pinned real releases",
)
def test_pinned_real_eurovoc_and_gemet_claim_releases(tmp_path: Path) -> None:
    eurovoc = export_eurovoc_4_24_claim_release(
        REAL_SOURCE_ROOT,
        tmp_path / "eurovoc",
    )
    gemet = export_gemet_4_2_3_claim_release(
        REAL_SOURCE_ROOT,
        tmp_path / "gemet",
    )

    eurovoc_counts = Counter(claim.predicate for claim in eurovoc.claims)
    assert eurovoc.manifest["releaseId"] == EUROVOC_CLAIM_RELEASE_ID
    assert eurovoc_counts[str(SKOS.inScheme)] == 15_438
    assert eurovoc_counts[str(SKOS.definition)] >= 1_557
    assert eurovoc.manifest["languageScope"]["mode"] == "englishOnly"

    gemet_counts = Counter(claim.predicate for claim in gemet.claims)
    assert gemet.manifest["releaseId"] == GEMET_CLAIM_RELEASE_ID
    assert gemet_counts[str(SKOS.member)] == 16_178
    assert gemet.manifest["metadata"]["mappingRelationCount"] == 9_658
    assert gemet.manifest["metadata"]["subgroupRelationCount"] == 32

    for release in (eurovoc, gemet):
        input_ = AtlasRegistryClaimInput(
            path=release.root,
            expected_manifest_digest=release.manifest_digest,
        )
        adapted = adapt_registry_claim_release(input_)
        report = validate_atlas_registry_claims(input_, adapted.records)
        assert report.passed is True
        assert report.expected_count == len(release.claims)
        assert report.exact_count == len(release.claims)

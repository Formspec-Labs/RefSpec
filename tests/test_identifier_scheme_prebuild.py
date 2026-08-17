from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from refspec.atlas.v3_source_data import RegistryIdentifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
generator = importlib.import_module("generate_atlas_v3_full")

IDENTIFIER_SCHEME_IRI = "urn:test:atlas-resource-scheme:identifier-authority"
RELEASE_SCHEME_IRI = "urn:test:atlas-resource-scheme:release"


def _identifier_release(tmp_path: Path) -> generator.LoadedRelease:
    source = tmp_path / "identifier-source.json"
    source.write_text("{}\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    resource = generator.SourceResource(
        iri="urn:test:resource:identified",
        labels=(
            generator.SourceLabel(
                value="Identified resource",
                language="en",
                role="preferred",
                source_path="identifier-source.json#label",
            ),
        ),
        native_payload={"id": "identified"},
        source_locator="https://example.test/identifier-source.json#identified",
        source_digest=digest,
        identifiers=(
            RegistryIdentifier(
                value="ID-1",
                scheme_iri=IDENTIFIER_SCHEME_IRI,
                source_path="identifier-source.json#identifier",
            ),
        ),
    )
    spec = generator.SourceSpec(
        key="synthetic-identifier-release",
        kind="test",
        path=source,
        logical_path="tests/synthetic/identifier-source.json",
        expected_digest=digest,
        expected_resources=1,
        profile="codeScheme",
        ring="entity",
    )
    return generator.LoadedRelease(
        spec=spec,
        source_release_iri="urn:test:source-release:identifier",
        source_release_digest=digest,
        atlas_release_iri="urn:test:atlas-release:identifier",
        scheme_iri=RELEASE_SCHEME_IRI,
        issued="2026-08-16",
        resources=(resource,),
        relations=(),
    )


def _identifier_descriptor_graph() -> Graph:
    descriptors: Graph = generator._registry_asserted_graph()
    release_scheme = URIRef(RELEASE_SCHEME_IRI)
    descriptors.add((release_scheme, RDF.type, generator.ATLAS.ResourceScheme))
    descriptors.add(
        (
            release_scheme,
            generator.ATLAS.resourceProfile,
            generator.ATLAS.codeScheme,
        )
    )
    descriptors.add(
        (
            release_scheme,
            generator.ATLAS.supportedRing,
            generator.ATLAS.entity,
        )
    )
    identifier_scheme = URIRef(IDENTIFIER_SCHEME_IRI)
    descriptors.add(
        (identifier_scheme, RDF.type, generator.ATLAS.ResourceScheme)
    )
    descriptors.add(
        (
            identifier_scheme,
            generator.ATLAS.resourceProfile,
            generator.ATLAS.identifierScheme,
        )
    )
    descriptors.add(
        (
            identifier_scheme,
            generator.ATLAS.supportedRing,
            generator.ATLAS.entity,
        )
    )
    return descriptors


def test_streamed_prebuild_resolves_identifier_scheme_from_descriptor_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptors = _identifier_descriptor_graph()
    monkeypatch.setattr(generator, "_registry_asserted_graph", lambda: descriptors)

    validation = generator.validate_prebuild_loaded_releases(
        (_identifier_release(tmp_path),),
        deep=True,
    )

    assert validation.compiled_rows.expected_counts["identifiers"] == 1
    assert validation.deep_compiled_output is not None


def test_default_prebuild_refuses_identifier_scheme_with_wrong_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptors = _identifier_descriptor_graph()
    scheme = URIRef(IDENTIFIER_SCHEME_IRI)
    descriptors.remove((scheme, generator.ATLAS.resourceProfile, None))
    descriptors.add(
        (
            scheme,
            generator.ATLAS.resourceProfile,
            generator.ATLAS.codeScheme,
        )
    )
    monkeypatch.setattr(generator, "_registry_asserted_graph", lambda: descriptors)

    with pytest.raises(ValueError, match="not an Atlas identifier authority") as error:
        generator.validate_prebuild_loaded_releases(
            (_identifier_release(tmp_path),),
        )

    assert error.value.__cause__ is not None
    assert "must be an atlas:ResourceScheme with the atlas:identifierScheme profile" in str(
        error.value.__cause__
    )

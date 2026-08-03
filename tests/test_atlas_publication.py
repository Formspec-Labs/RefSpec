"""Static publication and offline-explorer regressions."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from refspec import binding
from refspec.atlas import VocabularyAtlasAsset, VocabularyAtlasError
from refspec.atlas.publication import (
    ATLAS_MANIFEST,
    COMPRESSED_ATLAS,
    EXPLORER_DATA,
    EXPLORER_HTML,
    PUBLICATION_MANIFEST,
    build_explorer_model,
    publish_vocabulary_atlas,
)

_REPO_ROOT = Path(__file__).parents[1]
_FIXTURE_ROOT = _REPO_ROOT / "bindings" / "atlas" / "1.0" / "fixtures"
_CORPUS = json.loads((_FIXTURE_ROOT / "corpus.json").read_text(encoding="utf-8"))


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _asset(name: str) -> VocabularyAtlasAsset:
    case = next(value for value in _CORPUS["cases"] if value["directory"] == f"valid/{name}")
    return VocabularyAtlasAsset.open(
        _FIXTURE_ROOT / "valid" / name,
        expected_manifest_digest=case["manifestDigest"],
        expected_output_digest=case["outputDigest"],
    )


def test_explorer_view_keeps_qualified_mappings_and_distinguishes_equal_labels() -> None:
    asset = _asset("qualified-search-only")

    model = build_explorer_model(asset, max_nodes=20)

    mapping_edges = [edge for edge in model["edges"] if edge["type"] == "qualifiedMapping"]
    label_edges = [edge for edge in model["edges"] if edge["type"] == "sharedLabel"]
    assert model["atlas"] == {
        "assetId": asset.manifest["id"],
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
        "counts": dict(asset.manifest["counts"]),
        "quadCount": asset.manifest["output"]["quadCount"],
        "byteLength": asset.manifest["output"]["byteLength"],
        "managedInputs": [
            {
                "manifestDigest": value["manifestDigest"],
                "publicationReleaseId": value["publicationReleaseId"],
                "rulespecGraph": dict(value["rulespecGraph"]),
            }
            for value in asset.manifest["inputs"]
            if value["role"] == "ManagedReleaseView"
        ],
    }
    assert len(mapping_edges) == model["summary"]["availableQualifiedMappingCount"] == 1
    assert len(mapping_edges[0]["validationIds"]) == 2
    assert len(label_edges) == 1
    assert mapping_edges[0]["id"].startswith("urn:ref:vocabulary-atlas-search-only-mapping:")
    assert label_edges[0]["clusterId"].startswith("urn:ref:vocabulary-atlas-label-cluster:")
    assert {edge["id"] for edge in mapping_edges}.isdisjoint(edge["id"] for edge in label_edges)


def test_explorer_view_includes_real_hierarchy_context() -> None:
    model = build_explorer_model(
        _asset("hierarchy"),
        max_nodes=20,
        max_mappings=0,
        max_shared_clusters=0,
    )

    hierarchy = [edge for edge in model["edges"] if edge["type"] == "broader"]
    assert hierarchy
    assert model["summary"]["referenceReleaseCount"] == 2
    assert all(edge["label"] == "broader concept" for edge in hierarchy)
    assert any("hierarchyContext" in node["roles"] for node in model["nodes"])


def test_publication_is_deterministic_self_contained_and_reopens_as_an_atlas(tmp_path: Path) -> None:
    asset = _asset("qualified-search-only")
    title = "Atlas </script><img src=x onerror=alert(1)>"
    first = publish_vocabulary_atlas(asset, tmp_path / "first", title=title, max_nodes=20)
    second = publish_vocabulary_atlas(asset, tmp_path / "second", title=title, max_nodes=20)

    expected_files = {
        ATLAS_MANIFEST,
        COMPRESSED_ATLAS,
        EXPLORER_DATA,
        EXPLORER_HTML,
        PUBLICATION_MANIFEST,
    }
    assert {path.name for path in first.directory.iterdir()} == expected_files
    for name in expected_files:
        assert (first.directory / name).read_bytes() == (second.directory / name).read_bytes()

    publication = json.loads((first.directory / PUBLICATION_MANIFEST).read_text(encoding="utf-8"))
    explorer = json.loads((first.directory / EXPLORER_DATA).read_text(encoding="utf-8"))
    assert publication["canonicalPayloadDigest"] == binding.canonical_payload_digest(publication)
    assert first.manifest_digest == _digest((first.directory / PUBLICATION_MANIFEST).read_bytes())
    assert publication["atlas"] == {
        "assetId": asset.manifest["id"],
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }
    assert explorer["atlas"]["distributionDigest"] == asset.output_digest
    assert {artifact["path"] for artifact in publication["artifacts"]} == expected_files - {
        PUBLICATION_MANIFEST
    }
    for artifact in publication["artifacts"]:
        payload = (first.directory / artifact["path"]).read_bytes()
        assert artifact["digest"] == _digest(payload)
        assert artifact["byteLength"] == len(payload)

    compressed = (first.directory / COMPRESSED_ATLAS).read_bytes()
    assert gzip.decompress(compressed) == asset.payload
    compressed_record = next(
        artifact for artifact in publication["artifacts"] if artifact["path"] == COMPRESSED_ATLAS
    )
    assert compressed_record["uncompressedDigest"] == asset.output_digest
    assert compressed_record["uncompressedByteLength"] == len(asset.payload)

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "atlas-manifest.json").write_bytes((first.directory / ATLAS_MANIFEST).read_bytes())
    (extracted / "atlas.nq").write_bytes(gzip.decompress(compressed))
    reopened = VocabularyAtlasAsset.open(
        extracted,
        expected_manifest_digest=publication["atlas"]["manifestDigest"],
        expected_output_digest=publication["atlas"]["distributionDigest"],
    )
    assert reopened.manifest["id"] == asset.manifest["id"]

    page = (first.directory / EXPLORER_HTML).read_text(encoding="utf-8")
    assert "<script src=" not in page
    assert "fetch(" not in page
    assert title not in page
    assert "&lt;/script&gt;&lt;img" in page
    assert "\\u003c/script\\u003e\\u003cimg" in page
    assert "atlas.nq.gz" in page


def test_publication_refuses_ambiguous_limits_and_existing_output(tmp_path: Path) -> None:
    asset = _asset("qualified-search-only")

    with pytest.raises(VocabularyAtlasError, match="at least 2"):
        build_explorer_model(asset, max_nodes=1)
    with pytest.raises(VocabularyAtlasError, match="must not be negative"):
        build_explorer_model(asset, max_mappings=-1)

    output = tmp_path / "publication"
    publish_vocabulary_atlas(asset, output, max_nodes=20)
    with pytest.raises(VocabularyAtlasError, match="already exists"):
        publish_vocabulary_atlas(asset, output, max_nodes=20)


def test_release_label_override_is_display_only() -> None:
    asset = _asset("qualified-search-only")
    release_id = "urn:ref:conformance:alpha-thesaurus:2026:reference-resource-release"

    model = build_explorer_model(asset, release_labels={release_id: "Alpha source"}, max_nodes=20)

    release = next(value for value in model["releases"] if value["id"] == release_id)
    assert release["label"] == "Alpha source"
    assert model["atlas"]["assetId"] == asset.manifest["id"]

    with pytest.raises(VocabularyAtlasError, match="does not match"):
        build_explorer_model(asset, release_labels={"urn:missing": "Missing"}, max_nodes=20)


def test_publication_model_contains_only_json_portable_values() -> None:
    model: dict[str, Any] = build_explorer_model(_asset("qualified-search-only"), max_nodes=20)

    binding.validate_canonical_value(model)

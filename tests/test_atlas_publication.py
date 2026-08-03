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


# ---------------------------------------------------------------------------
# Display semantics for ISO-25964 lead-in terms and associative relations
# ---------------------------------------------------------------------------

_USE_IRI = "https://refspec.org/ns/vocabulary-atlas/v1#thesaurusUse"
_RELATED_IRI = "http://www.w3.org/2004/02/skos/core#related"
_BROADER_IRI = "http://www.w3.org/2004/02/skos/core#broader"


def _display_view(
    *,
    publication: str,
    release: str,
    concepts: dict[str, dict[str, Any]],
) -> Any:
    """A one-release view whose member records state display-relevant facts.

    Each concept spec may carry ``prefLabel``, ``altLabel``, and ``links``
    (predicate IRI to target members), mirroring how the ICPSR reader states
    non-descriptor USE references and associative relations.
    """

    from types import MappingProxyType

    import test_vocabulary_atlas as tva

    from refspec.managed_release import (
        ManagedReleaseExpression,
        ManagedReleaseMember,
        ManagedReleaseView,
    )

    records: dict[str, Any] = {}
    members: dict[str, Any] = {}
    expressions: list[Any] = []
    for member, spec in concepts.items():
        record: dict[str, Any] = {
            "@id": member,
            "@type": "https://rulespec.org/ns/v1#RegisteredConcept",
        }
        if "prefLabel" in spec:
            record["http://www.w3.org/2004/02/skos/core#prefLabel"] = spec["prefLabel"]
        if "altLabel" in spec:
            record["http://www.w3.org/2004/02/skos/core#altLabel"] = spec["altLabel"]
        for predicate, literal in spec.get("literals", {}).items():
            record[predicate] = literal
        for predicate, targets in spec.get("links", {}).items():
            record[predicate] = tuple({"@id": target} for target in targets)
        records[member] = MappingProxyType(record)
        members[member] = ManagedReleaseMember(
            member_iri=member,
            release_iri=release,
            scheme_iri=release + ":scheme",
            record=records[member],
        )
        label = spec.get("prefLabel") or spec["altLabel"]
        preferred = "prefLabel" in spec
        expressions.append(
            ManagedReleaseExpression(
                expression_id=member + ":expression",
                member_iri=member,
                indexed_text=label.casefold(),
                original_literal=label,
                language_tag="en",
                semantic_property_iri=(
                    "http://www.w3.org/2004/02/skos/core#prefLabel"
                    if preferred
                    else "http://www.w3.org/2004/02/skos/core#altLabel"
                ),
                source_property_or_path="prefLabel" if preferred else "altLabel",
                record=MappingProxyType({}),
                label_role="preferred" if preferred else "alternate",
                source_status="current",
            )
        )
    release_record = MappingProxyType(
        {
            "@id": release,
            "@type": "https://rulespec.org/ns/v1#ReferenceResourceRelease",
            "http://www.w3.org/ns/prov#hadMember": tuple(concepts),
            "https://rulespec.org/ns/v1#referenceReleaseDigest": tva.SHA_A,
        }
    )
    return ManagedReleaseView(
        _release_id=publication,
        _rulespec_graph_id=publication + ":graph",
        _rulespec_graph=MappingProxyType({"@graph": (release_record, *records.values())}),
        _expression_corpus_snapshot=MappingProxyType({"id": publication + ":corpus", "digest": tva.SHA_A}),
        _members=MappingProxyType(members),
        _expressions=tuple(expressions),
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=MappingProxyType({}),
    )


def test_explorer_labels_non_descriptors_and_pulls_use_targets(tmp_path: Path) -> None:
    """A lead-in term shows its alternate label, and its USE target joins the view.

    The non-descriptor sorts first so it becomes the release representative;
    its descriptor is reachable only through ``thesaurusUse``, never through
    hierarchy, so this fails without USE-target context expansion.
    """

    import test_vocabulary_atlas as tva

    from refspec.atlas import build_vocabulary_atlas

    lead_in = "urn:test:pub:use:a-ageism"
    descriptor = "urn:test:pub:use:z-age-discrimination"
    view = _display_view(
        publication="urn:test:pub:use",
        release="urn:test:pub:use:release",
        concepts={
            lead_in: {"altLabel": "ageism", "links": {_USE_IRI: (descriptor,)}},
            descriptor: {"prefLabel": "Age discrimination"},
        },
    )
    asset = build_vocabulary_atlas(
        (tva._FixturePinnedRelease(tmp_path / "use.json", tva.SHA_A, view),),
        rulespec_core=tva._core_release(tmp_path),
    )

    model = build_explorer_model(asset, max_nodes=20)

    labels = {node["id"]: node["label"] for node in model["nodes"]}
    assert labels[lead_in] == "ageism"
    assert labels[descriptor] == "Age discrimination"
    use_edges = [edge for edge in model["edges"] if edge["type"] == "use"]
    assert [(edge["source"], edge["target"]) for edge in use_edges] == [(lead_in, descriptor)]
    assert model["summary"]["useEdgeCount"] == 1


def test_explorer_draws_each_related_pair_once(tmp_path: Path) -> None:
    """A reciprocal skos:related statement renders as one edge, not two."""

    import test_vocabulary_atlas as tva

    from refspec.atlas import build_vocabulary_atlas

    age = "urn:test:pub:rel:a-age"
    research = "urn:test:pub:rel:d-ageism-research"
    view = _display_view(
        publication="urn:test:pub:rel",
        release="urn:test:pub:rel:release",
        concepts={
            age: {"prefLabel": "Age", "links": {_RELATED_IRI: (research,)}},
            research: {
                "prefLabel": "Ageism research",
                "links": {_RELATED_IRI: (age,), _BROADER_IRI: (age,)},
            },
        },
    )
    asset = build_vocabulary_atlas(
        (tva._FixturePinnedRelease(tmp_path / "rel.json", tva.SHA_A, view),),
        rulespec_core=tva._core_release(tmp_path),
    )

    model = build_explorer_model(asset, max_nodes=20)

    related = [edge for edge in model["edges"] if edge["type"] == "related"]
    assert len(related) == 1
    assert {related[0]["source"], related[0]["target"]} == {age, research}
    assert model["summary"]["relatedEdgeCount"] == 1
    assert model["summary"]["hierarchyEdgeCount"] == 1


_DEPRECATED_IRI = "http://www.w3.org/2002/07/owl#deprecated"
_IS_REPLACED_BY_IRI = "http://purl.org/dc/terms/isReplacedBy"
_REPLACES_IRI = "http://purl.org/dc/terms/replaces"
_TOP_CONCEPT_OF_IRI = "http://www.w3.org/2004/02/skos/core#topConceptOf"
_DEFINITION_IRI = "http://www.w3.org/2004/02/skos/core#definition"
_SCOPE_NOTE_IRI = "http://www.w3.org/2004/02/skos/core#scopeNote"
_NOTATION_IRI = "http://www.w3.org/2004/02/skos/core#notation"


def test_explorer_marks_deprecated_concepts_and_draws_replacement_edges(tmp_path: Path) -> None:
    """A retired concept is flagged, and one replacedBy edge joins it to its successor.

    The reciprocal ``dcterms:replaces`` statement folds into the same edge.
    """

    import test_vocabulary_atlas as tva

    from refspec.atlas import build_vocabulary_atlas

    retired = "urn:test:pub:life:a-capital-punishment"
    successor = "urn:test:pub:life:z-death-penalty"
    view = _display_view(
        publication="urn:test:pub:life",
        release="urn:test:pub:life:release",
        concepts={
            retired: {
                "prefLabel": "Capital punishment",
                "literals": {_DEPRECATED_IRI: True},
                "links": {_IS_REPLACED_BY_IRI: (successor,)},
            },
            successor: {
                "prefLabel": "Death penalty",
                "links": {_REPLACES_IRI: (retired,)},
            },
        },
    )
    asset = build_vocabulary_atlas(
        (tva._FixturePinnedRelease(tmp_path / "life.json", tva.SHA_A, view),),
        rulespec_core=tva._core_release(tmp_path),
    )

    model = build_explorer_model(asset, max_nodes=20)

    nodes = {node["id"]: node for node in model["nodes"]}
    assert nodes[retired]["deprecated"] is True
    assert "deprecated" not in nodes[successor]
    replaced = [edge for edge in model["edges"] if edge["type"] == "replacedBy"]
    assert [(edge["source"], edge["target"]) for edge in replaced] == [(retired, successor)]
    assert model["summary"]["replacedByEdgeCount"] == 1


def test_explorer_surfaces_notes_notation_and_top_concept_badges(tmp_path: Path) -> None:
    """Definition, scope note, notation, and top-concept status reach the node payload."""

    import test_vocabulary_atlas as tva

    from refspec.atlas import build_vocabulary_atlas

    concept = "urn:test:pub:notes:a-ageism"
    plain = "urn:test:pub:notes:b-plain"
    scheme = "urn:test:pub:notes:release:scheme"
    view = _display_view(
        publication="urn:test:pub:notes",
        release="urn:test:pub:notes:release",
        concepts={
            concept: {
                "prefLabel": "Ageism",
                "literals": {
                    _DEFINITION_IRI: "Prejudice on the basis of age.",
                    _SCOPE_NOTE_IRI: "Use for age-based discrimination attitudes.",
                    _NOTATION_IRI: "24128",
                },
                "links": {_TOP_CONCEPT_OF_IRI: (scheme,), _BROADER_IRI: (plain,)},
            },
            plain: {"prefLabel": "Attitudes"},
        },
    )
    asset = build_vocabulary_atlas(
        (tva._FixturePinnedRelease(tmp_path / "notes.json", tva.SHA_A, view),),
        rulespec_core=tva._core_release(tmp_path),
    )

    model = build_explorer_model(asset, max_nodes=20)

    nodes = {node["id"]: node for node in model["nodes"]}
    assert nodes[concept]["definition"] == "Prejudice on the basis of age."
    assert nodes[concept]["scopeNote"] == "Use for age-based discrimination attitudes."
    assert nodes[concept]["notation"] == "24128"
    assert "topConcept" in nodes[concept]["roles"]
    for field in ("definition", "scopeNote", "notation"):
        assert field not in nodes[plain]
    assert "topConcept" not in nodes[plain]["roles"]


def test_explorer_offers_rejected_candidates_as_their_own_edge_type(tmp_path: Path) -> None:
    """A candidate the gate refused renders as a rejectedCandidate edge, not silence.

    ``same_provider=True`` produces two validations without independence, so
    the candidate is ``notEligible`` — the shape of every refused pair.
    """

    import test_vocabulary_atlas as tva

    from refspec.atlas import build_vocabulary_atlas

    bundle = tva._qualified_bundle(same_provider=True)
    asset = build_vocabulary_atlas(
        tva._two_releases(tmp_path),
        rulespec_core=tva._core_release(tmp_path),
        crosswalks=(bundle,),
    )

    model = build_explorer_model(asset, max_nodes=20)

    rejected = [edge for edge in model["edges"] if edge["type"] == "rejectedCandidate"]
    assert len(rejected) == 1
    assert rejected[0]["candidateId"].startswith("urn:ref:vocabulary-atlas-mapping-candidate:")
    assert {rejected[0]["source"], rejected[0]["target"]} == {tva.SOURCE_MEMBER, tva.TARGET_MEMBER}
    assert model["summary"]["rejectedCandidateEdgeCount"] == 1
    assert model["summary"]["qualifiedMappingCount"] == 0

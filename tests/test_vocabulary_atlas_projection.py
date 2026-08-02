"""A projection is a distinct distribution kind that names its parent."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from refspec import binding
from refspec.atlas import (
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    VocabularyAtlasQueries,
)
from refspec.atlas.projection import (
    ASSET_ID_PREFIX,
    CONSUMER_READ_CLOSURE_V1,
    FORMAT_ID,
    MANIFEST_TYPE,
    VocabularyAtlasProjection,
    build_atlas_projection,
    distribution_kind,
    reproduce_distribution,
)

_REPO_ROOT = Path(__file__).parents[1]
_FIXTURE_ROOT = _REPO_ROOT / "bindings" / "atlas" / "1.0" / "fixtures"
_CORPUS = json.loads((_FIXTURE_ROOT / "corpus.json").read_text(encoding="utf-8"))
_CASES = {case["directory"]: case for case in _CORPUS["cases"]}

_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
_NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"
_NORMALIZED_LABEL = "https://refspec.org/ns/vocabulary-atlas/v1#normalizedLabel"


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _parent(directory: str) -> tuple[Path, str, str]:
    case = _CASES[directory]
    return (
        _FIXTURE_ROOT / directory,
        case["manifestDigest"],
        case["outputDigest"],
    )


def _projection(directory: str) -> VocabularyAtlasProjection:
    root, manifest_digest, output_digest = _parent(directory)
    return build_atlas_projection(
        root,
        expected_manifest_digest=manifest_digest,
        expected_output_digest=output_digest,
    )


def test_projection_identity_names_the_parent_and_cannot_collide_with_it() -> None:
    """The defect this kind exists to fix: one identifier for two files.

    A projection's id is a digest of its parent's identity and both of its
    digests, its named policy version, and the implementation that cut it.
    None of those is the parent's own generation digest, so the two can never
    be the same string.
    """

    root, manifest_digest, output_digest = _parent("valid/qualified-search-only")
    parent = VocabularyAtlasAsset.open(
        root,
        expected_manifest_digest=manifest_digest,
        expected_output_digest=output_digest,
    )
    projection = _projection("valid/qualified-search-only")

    assert projection.manifest["type"] == MANIFEST_TYPE
    assert projection.manifest["format"] == FORMAT_ID
    assert str(projection.manifest["id"]).startswith(ASSET_ID_PREFIX)
    assert projection.manifest["id"] != parent.manifest["id"]
    assert projection.parent_pin == {
        "assetId": str(parent.manifest["id"]),
        "manifestDigest": manifest_digest,
        "distributionDigest": output_digest,
    }
    assert projection.manifest["projectionPolicy"]["id"] == (
        CONSUMER_READ_CLOSURE_V1["id"]
    )
    assert projection.manifest["projectionPolicy"]["version"] == "1"
    # The payload's named graphs still name the generation it was cut from.
    assert {row["id"] for row in projection.manifest["graphs"]} == {
        str(parent.manifest["id"]) + ":release-facts",
        str(parent.manifest["id"]) + ":analysis",
    }


def test_projection_rebuilds_byte_identically(tmp_path: Path) -> None:
    first = _projection("valid/qualified-search-only")
    second = _projection("valid/qualified-search-only")

    assert first.payload == second.payload
    assert first.manifest_bytes() == second.manifest_bytes()

    written = first.write(tmp_path / "projection")
    assert _digest(written / "atlas.nq") == first.output_digest
    assert _digest(written / "atlas-manifest.json") == first.manifest_digest


def test_projection_opens_and_reproduces_from_its_parent(tmp_path: Path) -> None:
    root, manifest_digest, output_digest = _parent("valid/qualified-search-only")
    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")

    opened = VocabularyAtlasProjection.open(
        written,
        expected_manifest_digest=projection.manifest_digest,
        expected_output_digest=projection.output_digest,
    )
    assert opened.parent_pin["manifestDigest"] == manifest_digest

    reproduced = VocabularyAtlasProjection.reproduce_from_parent(
        written,
        parent_directory=root,
        expected_manifest_digest=projection.manifest_digest,
        expected_output_digest=projection.output_digest,
    )
    assert reproduced.output_digest == projection.output_digest
    del output_digest


def test_projection_refuses_an_unrelated_parent(tmp_path: Path) -> None:
    """A projection claiming a parent that did not produce it must refuse."""

    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")
    other_root, _manifest_digest, _output_digest = _parent("valid/hierarchy")

    with pytest.raises(VocabularyAtlasError, match="external manifest digest differs"):
        VocabularyAtlasProjection.reproduce_from_parent(
            written,
            parent_directory=other_root,
            expected_manifest_digest=projection.manifest_digest,
            expected_output_digest=projection.output_digest,
        )


def _reseal(directory: Path, manifest: dict[str, object]) -> str:
    manifest.pop("canonicalPayloadDigest", None)
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    path = directory / "atlas-manifest.json"
    path.write_bytes(binding.canonical_json_bytes(manifest) + b"\n")
    return _digest(path)


def test_projection_refuses_a_dropped_fact_the_consumer_reads(tmp_path: Path) -> None:
    """Dropping one kept quad must fail even when the forgery reseals itself.

    A tampered payload is caught by the external digest first. The check that
    matters is the one after that: a forger who also rewrites `output` and
    `graphs` still has to explain the counts, which are re-derived from the
    bytes the file actually carries.
    """

    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")
    lines = (written / "atlas.nq").read_bytes().decode("utf-8").splitlines()
    forged = [line for line in lines if "prov#hadMember" not in line]
    assert len(forged) < len(lines)
    payload = ("\n".join(forged) + "\n").encode("utf-8")
    (written / "atlas.nq").write_bytes(payload)
    forged_output_digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    with pytest.raises(VocabularyAtlasError, match="external output digest differs"):
        VocabularyAtlasProjection.open(
            written,
            expected_manifest_digest=projection.manifest_digest,
            expected_output_digest=projection.output_digest,
        )

    manifest = json.loads((written / "atlas-manifest.json").read_text(encoding="utf-8"))
    release_id = next(
        row["id"] for row in manifest["graphs"] if row["role"] == "releaseFacts"
    )
    release_quads = sum(1 for line in forged if line.endswith(f"<{release_id}> ."))
    for row in manifest["graphs"]:
        if row["role"] == "releaseFacts":
            row["quadCount"] = release_quads
    manifest["output"]["byteLength"] = len(payload)
    manifest["output"]["quadCount"] = len(forged)
    manifest["output"]["digest"] = forged_output_digest
    manifest_digest = _reseal(written, manifest)

    with pytest.raises(VocabularyAtlasError, match="declared counts differ"):
        VocabularyAtlasProjection.open(
            written,
            expected_manifest_digest=manifest_digest,
            expected_output_digest=forged_output_digest,
        )


def test_projection_refuses_an_unregistered_policy(tmp_path: Path) -> None:
    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")
    manifest = json.loads((written / "atlas-manifest.json").read_text(encoding="utf-8"))
    manifest["projectionPolicy"]["version"] = "2"
    manifest_digest = _reseal(written, manifest)

    with pytest.raises(VocabularyAtlasError, match="unregistered policy"):
        VocabularyAtlasProjection.open(
            written,
            expected_manifest_digest=manifest_digest,
            expected_output_digest=projection.output_digest,
        )


def test_an_atlas_reader_names_a_projection_instead_of_calling_it_corrupt(
    tmp_path: Path,
) -> None:
    """The finding that motivated this kind, pinned as behaviour.

    Before this module a projection opened under `VocabularyAtlasAsset.open`
    with its parent's asset id, and `reproduce_from_inputs` refused it with
    "atlas files do not reproduce from the exact pinned inputs" — the message
    reserved for a corrupted atlas. A projection is now refused at the door,
    on its manifest shape, and the corrupted-atlas message is unreachable.
    """

    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")

    with pytest.raises(VocabularyAtlasError) as refusal:
        VocabularyAtlasAsset.open(
            written,
            expected_manifest_digest=projection.manifest_digest,
            expected_output_digest=projection.output_digest,
        )
    assert "fields differ from v1" in str(refusal.value)
    assert "do not reproduce from the exact pinned inputs" not in str(refusal.value)

    assert distribution_kind(written) == "vocabularyAtlasProjection"
    root, _manifest_digest, _output_digest = _parent("valid/qualified-search-only")
    assert distribution_kind(root) == "vocabularyAtlas"

    with pytest.raises(VocabularyAtlasError, match="reproduces from its parent distribution"):
        reproduce_distribution(
            written,
            expected_manifest_digest=projection.manifest_digest,
            expected_output_digest=projection.output_digest,
        )
    reproduced = reproduce_distribution(
        written,
        parent_directory=root,
        expected_manifest_digest=projection.manifest_digest,
        expected_output_digest=projection.output_digest,
    )
    assert isinstance(reproduced, VocabularyAtlasProjection)


def test_projection_preserves_every_qualified_mapping_and_its_closure(
    tmp_path: Path,
) -> None:
    """Read equivalence, proved through the producer's own query surface."""

    root, manifest_digest, output_digest = _parent("valid/qualified-search-only")
    parent = VocabularyAtlasAsset.open(
        root,
        expected_manifest_digest=manifest_digest,
        expected_output_digest=output_digest,
    )
    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")
    opened = VocabularyAtlasProjection.open(
        written,
        expected_manifest_digest=projection.manifest_digest,
        expected_output_digest=projection.output_digest,
    )

    parent_mappings = VocabularyAtlasQueries(parent).search_only_mappings()
    assert parent_mappings
    assert opened.manifest["counts"]["searchOnlyMappings"] == len(parent_mappings)
    # Two independent machines qualify each mapping, and only those survive:
    # the fixture's third validation belongs to the near-miss candidate the
    # consumer never reads.
    assert opened.manifest["counts"]["machineValidations"] == 2 * len(parent_mappings)
    assert parent.manifest["counts"]["machineValidations"] == 3
    assert opened.manifest["counts"]["mappingCandidates"] == len(parent_mappings)
    assert parent.manifest["counts"]["mappingCandidates"] == 2

    kept = opened.payload.decode("utf-8")
    for mapping in parent_mappings:
        assert f"<{mapping.source_member}>" in kept
        assert f"<{mapping.target_member}>" in kept

    # Label clusters are validated on open and read by nothing, so they go.
    assert opened.manifest["counts"]["labelClusters"] == 0
    assert _NORMALIZED_LABEL not in kept


def test_projection_carries_hierarchy_from_the_broader_direction(
    tmp_path: Path,
) -> None:
    """`skos:broader` survives; the reciprocal `skos:narrower` does not.

    No consumer accessor reads hierarchy yet. It is carried anyway because
    hierarchy is the release fact the atlas spent two days admitting, and a
    projection kind that structurally could not hold it would need a second
    format change before that work reached anyone.
    """

    root, manifest_digest, output_digest = _parent("valid/hierarchy")
    parent = VocabularyAtlasAsset.open(
        root,
        expected_manifest_digest=manifest_digest,
        expected_output_digest=output_digest,
    )
    projection = _projection("valid/hierarchy")
    written = projection.write(tmp_path / "projection")
    opened = VocabularyAtlasProjection.open(
        written,
        expected_manifest_digest=projection.manifest_digest,
        expected_output_digest=projection.output_digest,
    )

    parent_edges = VocabularyAtlasQueries(parent).hierarchy_edges()
    assert parent_edges
    assert opened.manifest["counts"]["hierarchyEdges"] == len(parent_edges)
    assert parent.manifest["counts"]["hierarchyEdges"] == len(parent_edges)

    kept = opened.payload.decode("utf-8")
    assert kept.count(f"<{_BROADER}>") == len(parent_edges)
    assert f"<{_NARROWER}>" not in kept


def test_a_hierarchy_free_projection_declares_no_hierarchy_count() -> None:
    projection = _projection("valid/qualified-search-only")
    assert "hierarchyEdges" not in projection.manifest["counts"]


def test_two_parents_never_share_a_projection_identity() -> None:
    first = _projection("valid/qualified-search-only")
    second = _projection("valid/hierarchy")

    assert first.manifest["id"] != second.manifest["id"]
    assert first.parent_pin["assetId"] != second.parent_pin["assetId"]


def test_projection_of_a_projection_directory_is_refused(tmp_path: Path) -> None:
    """A projection is not an atlas, so it cannot be a projection's parent."""

    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")

    with pytest.raises(VocabularyAtlasError, match="fields differ from v1"):
        build_atlas_projection(
            written,
            expected_manifest_digest=projection.manifest_digest,
            expected_output_digest=projection.output_digest,
        )


def test_projection_directory_must_hold_exactly_its_two_files(tmp_path: Path) -> None:
    projection = _projection("valid/qualified-search-only")
    written = projection.write(tmp_path / "projection")
    assert {path.name for path in written.iterdir()} == {
        "atlas.nq",
        "atlas-manifest.json",
    }
    shutil.rmtree(written)


def test_projection_manifest_matches_its_published_schema() -> None:
    """A reader in another language needs the shape without the producer."""

    schema = json.loads(
        (
            _REPO_ROOT
            / "bindings"
            / "atlas"
            / "1.0"
            / "schemas"
            / "vocabulary-atlas-projection-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    for directory in ("valid/qualified-search-only", "valid/hierarchy"):
        projection = _projection(directory)
        validator.validate(json.loads(projection.manifest_bytes().decode("utf-8")))

    atlas_manifest = json.loads(
        (_FIXTURE_ROOT / "valid/qualified-search-only" / "atlas-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    # The two kinds are not interchangeable in either direction.
    assert not validator.is_valid(atlas_manifest)

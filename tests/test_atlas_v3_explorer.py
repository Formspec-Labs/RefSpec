"""Atlas 3.0 explorer integrity and authority-boundary tests."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import RDF

import refspec.atlas.explorer_rdf as explorer_module
from refspec.atlas.explorer_rdf import (
    ATLAS,
    ATLAS_V3_EXPLORER_TYPE,
    EXPLORER_TYPE,
    Atlas3ExplorerError,
    build_atlas_v3_explorer_model,
    open_atlas_v3_explorer_distribution,
    render_atlas_explorer,
)
from refspec.atlas.explorer_rdf_cli import build_preview
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SOURCE = (
    ROOT / "bindings" / "atlas" / "3.0" / "fixtures" / "valid" / "source-native-thesaurus"
)
FIXTURE = FIXTURE_SOURCE


def _mapping_adoption_payload() -> dict[str, object]:
    return {
        "currentEuroVocLinksetCounts": {
            "http://www.w3.org/2004/02/skos/core#closeMatch": 99,
            "http://www.w3.org/2004/02/skos/core#exactMatch": 1_904,
        },
        "currentEuroVocLinksetMetadataDigest": "sha256:" + "4" * 64,
        "currentEuroVocRelease": "4.24",
        "currentMetadataRequalifiesIndividualPairs": False,
        "objectIri": "http://id.loc.gov/authorities/subjects/sh85000001",
        "predicateIri": "http://www.w3.org/2004/02/skos/core#exactMatch",
        "publisherAlignmentDigest": "sha256:" + "1" * 64,
        "publisherAlignmentIssued": "2024-07-11",
        "publisherAlignmentRelease": (
            "http://publications.europa.eu/resource/dataset/"
            "eurovoc_alignment_lcsh/20240711-0"
        ),
        "publisherAlignmentVersion": "20240711-0",
        "publisherEuroVocRelease": (
            "http://publications.europa.eu/resource/dataset/eurovoc/20240711-0"
        ),
        "publisherEuroVocVersion": "4.20",
        "publisherLcshRelease": "unspecifiedByPublisher",
        "subjectIri": "http://eurovoc.europa.eu/100141",
    }


def _canonical_digest_without_lf(value: object) -> str:
    payload = canonical_json_bytes(value)
    assert payload.endswith(b"\n")
    return sha256_digest(payload[:-1])


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _read_static_shard(root: Path, reference: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    transport = (root / reference["url"]).read_bytes()
    assert len(transport) == reference["transport"]["byteLength"]
    assert sha256_digest(transport) == reference["transport"]["digest"]
    content = gzip.decompress(transport)
    assert len(content) == reference["content"]["byteLength"]
    assert sha256_digest(content) == reference["content"]["digest"]
    return transport, json.loads(content)


def _source_fixture_lines(source: Path, manifest: dict[str, object]) -> list[bytes]:
    if manifest["format"] == "refspec-atlas-nquads-3.0":
        return (source / "atlas.nq").read_bytes().splitlines(keepends=True)
    lines: list[bytes] = []
    for raw_pack in manifest["packs"]:  # type: ignore[index]
        pack = dict(raw_pack)
        path = source / str(pack["path"])
        if pack["transport"]["compression"] == "zstd":  # type: ignore[index]
            with explorer_module.zstd.open(path, "rb") as stream:
                lines.extend(stream.readlines())
        else:
            lines.extend(path.read_bytes().splitlines(keepends=True))
    return sorted(set(lines))


def _write_current_packed_fixture(
    source: Path,
    target: Path,
    *,
    include_views: bool = True,
    compression: str = "none",
    split_asserted_packs: bool = False,
) -> None:
    source_manifest = json.loads((source / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: row["id"] for row in source_manifest["graphs"]}
    suffixes = {
        role: f" <{graph_id}> .\n".encode()
        for role, graph_id in graph_ids.items()
    }
    lines = _source_fixture_lines(source, source_manifest)
    if not include_views:
        lines = [line for line in lines if line.endswith(suffixes["asserted"])]
    lines.sort()
    if split_asserted_packs:
        assert not include_views
        subjects = sorted({line.split(b" ", 1)[0] for line in lines})
        midpoint = len(subjects) // 2
        first_subjects = set(subjects[:midpoint])
        pack_line_groups = [
            [line for line in lines if line.split(b" ", 1)[0] in first_subjects],
            [line for line in lines if line.split(b" ", 1)[0] not in first_subjects],
        ]
        assert all(pack_line_groups)
    else:
        pack_line_groups = [lines]

    target.mkdir()
    (target / "packs").mkdir()
    shutil.copyfile(
        source / "atlas-source-accounting.json",
        target / "atlas-source-accounting.json",
    )
    packs = []
    for index, pack_lines in enumerate(pack_line_groups):
        payload = b"".join(pack_lines)
        graph_counts = {
            role: sum(line.endswith(suffix) for line in pack_lines)
            for role, suffix in suffixes.items()
        }
        suffix = ".nq.zst" if compression == "zstd" else ".nq"
        stem = "aggregate" if len(pack_line_groups) == 1 else f"aggregate-{index}"
        relative_pack_path = f"packs/{stem}{suffix}"
        pack_path = target / relative_pack_path
        if compression == "zstd":
            with explorer_module.zstd.open(pack_path, "wb", level=1) as stream:
                stream.write(payload)
            transport_media_type = "application/zstd"
        else:
            pack_path.write_bytes(payload)
            transport_media_type = "application/n-quads"
        content_digest = sha256_digest(payload)
        pack_id = "urn:ref:atlas-test:pack:" + content_digest.removeprefix("sha256:")
        packs.append(
            {
                "content": {
                    "byteLength": len(payload),
                    "digest": content_digest,
                    "mediaType": "application/n-quads",
                    "quadCount": len(pack_lines),
                },
                "dependencies": [],
                "graphCounts": graph_counts,
                "kind": "aggregate",
                "packId": pack_id,
                "path": relative_pack_path,
                "rings": [],
                "sourceReleases": [],
                "transport": {
                    "byteLength": pack_path.stat().st_size,
                    "compression": compression,
                    "digest": sha256_digest(pack_path.read_bytes()),
                    "mediaType": transport_media_type,
                },
            }
        )
    packs.sort(key=lambda row: row["packId"])

    graph_rows = []
    for role in ("asserted", "projection", "derived"):
        inventory_rows = [
            {
                "contentDigest": pack["content"]["digest"],
                "packId": pack["packId"],
                "quadCount": pack["graphCounts"][role],
            }
            for pack in packs
            if pack["graphCounts"][role]
        ]
        graph_rows.append(
            {
                "id": graph_ids[role],
                "inventoryDigest": _canonical_digest_without_lf(inventory_rows),
                "packCount": len(inventory_rows),
                "quadCount": sum(row["quadCount"] for row in inventory_rows),
                "role": role,
            }
        )
    for pack in packs:
        if pack["graphCounts"]["projection"] or pack["graphCounts"]["derived"]:
            pack["inputAssertedDigest"] = graph_rows[0]["inventoryDigest"]

    binding = {"validatorVersion": "3.0", "version": "3.0", **explorer_module._binding_digests()}
    accounting_path = target / "atlas-source-accounting.json"
    acceptance_inputs = {
        "atlasDigest": graph_rows[0]["inventoryDigest"],
        "sourceAccountingDigest": sha256_digest(accounting_path.read_bytes()),
        **explorer_module._binding_digests(),
    }
    validator = {"name": "refspec-atlas-conformance", "version": "3.0"}
    acceptance = {
        "distributionId": source_manifest["distributionId"],
        "evaluatedAt": source_manifest["createdAt"],
        "gates": [
            {
                "evidenceDigest": _canonical_digest_without_lf(
                    {
                        "inputs": acceptance_inputs,
                        "name": gate,
                        "status": "passed",
                        "validator": validator,
                    }
                ),
                "name": gate,
                "status": "passed",
            }
            for gate in sorted(explorer_module.REQUIRED_ACCEPTANCE_GATES)
        ],
        "inputs": acceptance_inputs,
        "type": "AtlasAcceptance",
        "validator": validator,
        "verdict": "passed",
        "version": "3.0",
    }
    acceptance_path = target / "atlas-acceptance.json"
    _write_json(acceptance_path, acceptance)

    counts = dict(source_manifest["counts"])
    if not include_views:
        counts["projectedRelations"] = 0
        counts["derivedRelations"] = 0
    manifest = {
        "binding": binding,
        "counts": counts,
        "createdAt": source_manifest["createdAt"],
        "distributionId": source_manifest["distributionId"],
        "format": "refspec-atlas-packed-nquads-3.0",
        "graphs": graph_rows,
        "members": [
            {
                "byteLength": accounting_path.stat().st_size,
                "digest": sha256_digest(accounting_path.read_bytes()),
                "mediaType": "application/json",
                "path": "atlas-source-accounting.json",
                "role": "sourceAccounting",
            },
            {
                "byteLength": acceptance_path.stat().st_size,
                "digest": sha256_digest(acceptance_path.read_bytes()),
                "mediaType": "application/json",
                "path": "atlas-acceptance.json",
                "role": "acceptance",
            },
        ],
        "packs": packs,
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }

    compact_content = b'{"fixture":"explorer-transport-only"}\n'
    compact_transport = explorer_module.zstd.compress(compact_content)
    compact_content_digest = sha256_digest(compact_content)
    compact_path = "packs/compact/fixture/release.jsonl.zst"
    compact_target = target / compact_path
    compact_target.parent.mkdir(parents=True)
    compact_target.write_bytes(compact_transport)
    compact_pack = {
        "content": {
            "byteLength": len(compact_content),
            "digest": compact_content_digest,
            "mediaType": "application/x-ndjson",
            "recordCount": 1,
        },
        "defaults": {},
        "dependencies": [],
        "globalInvariantSummary": {
            "digest": sha256_digest(b"fixture-global-invariant-summary"),
            "fieldCounts": {},
            "recordCount": 1,
            "recordRole": "Release",
            "schemaVersion": "1.0",
        },
        "logicalRowsDigest": sha256_digest(b"fixture-logical-row"),
        "packId": (
            "urn:ref:atlas:compact-pack:"
            + compact_content_digest.removeprefix("sha256:")
        ),
        "path": compact_path,
        "recordSchemaVersion": "1.0",
        "role": "Release",
        "transport": {
            "byteLength": len(compact_transport),
            "compression": "zstd",
            "digest": sha256_digest(compact_transport),
            "mediaType": "application/zstd",
        },
    }
    construction_releases = [
        {
            "adapterRecipeDigest": sha256_digest(b"explorer-fixture-adapter"),
            "compactPackPaths": [compact_path],
            "key": "explorer-fixture",
        }
    ]
    construction_summary = {
        "assertedInventoryDigest": graph_rows[0]["inventoryDigest"],
        "bindingBundleDigest": binding["bindingBundleDigest"],
        "catalog": {},
        "compactPackCount": 1,
        "compactPackInventoryDigest": sha256_digest(
            canonical_json_bytes([compact_pack])
        ),
        "compactPacks": [compact_pack],
        "distributionId": source_manifest["distributionId"],
        "profile": "atlas-3-release-local-construction-v1",
        "recipeDigest": sha256_digest(b"explorer-fixture-recipe"),
        "releaseCount": 1,
        "releaseInventoryDigest": sha256_digest(
            canonical_json_bytes(construction_releases)
        ),
        "releases": construction_releases,
        "sourceAccountingDigest": sha256_digest(accounting_path.read_bytes()),
        "type": "AtlasConstructionSummary",
        "version": "3.0",
    }
    construction_summary["canonicalPayloadDigest"] = _canonical_digest_without_lf(
        construction_summary
    )
    construction_path = target / "atlas-construction-summary.json"
    _write_json(construction_path, construction_summary)
    construction_digest = sha256_digest(construction_path.read_bytes())

    accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
    proof = {
        "assertedInventoryDigest": graph_rows[0]["inventoryDigest"],
        "binding": binding,
        "checks": ["unit-test compiled producer proof"],
        "constructionSummary": {
            "compactPackCount": 1,
            "compactPackInventoryDigest": construction_summary[
                "compactPackInventoryDigest"
            ],
            "digest": construction_digest,
            "path": "atlas-construction-summary.json",
            "profile": "atlas-3-authenticated-construction-summary-v1",
            "releaseCount": 1,
            "releaseInventoryDigest": construction_summary[
                "releaseInventoryDigest"
            ],
        },
        "constructorProfile": "atlas-3-source-and-evidence-backed-mapping-compiled-shacl-v1",
        "counts": counts,
        "implementationDigest": sha256_digest(b"explorer-fixture-producer"),
        "mode": "compiledSourceAndEvidenceBackedMappingProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "sourceAccountingDigest": sha256_digest(accounting_path.read_bytes()),
        "sourceReleaseCount": accounting["totals"]["sourceReleases"],
        "status": "passed",
        "type": "AtlasProducerValidation",
        "version": "3.0",
    }
    proof_path = target / "atlas-producer-validation.json"
    _write_json(proof_path, proof)
    proof_digest = sha256_digest(proof_path.read_bytes())
    acceptance["inputs"]["producerValidationDigest"] = proof_digest
    for gate in acceptance["gates"]:
        gate["evidenceDigest"] = _canonical_digest_without_lf(
            {
                "inputs": acceptance["inputs"],
                "name": gate["name"],
                "status": "passed",
                "validator": acceptance["validator"],
            }
        )
    _write_json(acceptance_path, acceptance)
    manifest["members"] = [
        {
            "byteLength": accounting_path.stat().st_size,
            "digest": sha256_digest(accounting_path.read_bytes()),
            "mediaType": "application/json",
            "path": "atlas-source-accounting.json",
            "role": "sourceAccounting",
        },
        {
            "byteLength": acceptance_path.stat().st_size,
            "digest": sha256_digest(acceptance_path.read_bytes()),
            "mediaType": "application/json",
            "path": "atlas-acceptance.json",
            "role": "acceptance",
        },
        {
            "byteLength": proof_path.stat().st_size,
            "digest": proof_digest,
            "mediaType": "application/json",
            "path": "atlas-producer-validation.json",
            "role": "producerValidation",
        },
        {
            "byteLength": construction_path.stat().st_size,
            "digest": construction_digest,
            "mediaType": "application/json",
            "path": "atlas-construction-summary.json",
            "role": "constructionSummary",
        },
    ]
    manifest["canonicalPayloadDigest"] = _canonical_digest_without_lf(manifest)
    _write_json(target / "atlas-manifest.json", manifest)


@pytest.fixture(autouse=True)
def _packed_fixture(tmp_path: Path) -> None:
    global FIXTURE
    previous = FIXTURE
    FIXTURE = tmp_path / "source-native-thesaurus"
    _write_current_packed_fixture(FIXTURE_SOURCE, FIXTURE)
    try:
        yield
    finally:
        FIXTURE = previous


def _open_distribution(root: Path | None = None):
    root = FIXTURE if root is None else root
    return open_atlas_v3_explorer_distribution(
        root,
        trusted_manifest_digest=sha256_digest((root / "atlas-manifest.json").read_bytes()),
    )


def _reseal_changed_json_members(root: Path) -> None:
    manifest_path = root / "atlas-manifest.json"
    acceptance_path = root / "atlas-acceptance.json"
    accounting_path = root / "atlas-source-accounting.json"
    construction_path = root / "atlas-construction-summary.json"
    proof_path = root / "atlas-producer-validation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    construction = json.loads(construction_path.read_text(encoding="utf-8"))
    proof = json.loads(proof_path.read_text(encoding="utf-8"))

    accounting_digest = sha256_digest(accounting_path.read_bytes())
    construction["sourceAccountingDigest"] = accounting_digest
    construction_basis = dict(construction)
    construction_basis.pop("canonicalPayloadDigest")
    construction["canonicalPayloadDigest"] = _canonical_digest_without_lf(
        construction_basis
    )
    _write_json(construction_path, construction)
    construction_digest = sha256_digest(construction_path.read_bytes())

    proof["sourceAccountingDigest"] = accounting_digest
    proof["constructionSummary"] = {
        "compactPackCount": construction["compactPackCount"],
        "compactPackInventoryDigest": construction["compactPackInventoryDigest"],
        "digest": construction_digest,
        "path": "atlas-construction-summary.json",
        "profile": "atlas-3-authenticated-construction-summary-v1",
        "releaseCount": construction["releaseCount"],
        "releaseInventoryDigest": construction["releaseInventoryDigest"],
    }
    _write_json(proof_path, proof)
    proof_digest = sha256_digest(proof_path.read_bytes())

    acceptance["inputs"]["sourceAccountingDigest"] = accounting_digest
    acceptance["inputs"]["producerValidationDigest"] = proof_digest
    for gate in acceptance["gates"]:
        gate["evidenceDigest"] = _canonical_digest_without_lf(
            {
                "inputs": acceptance["inputs"],
                "name": gate["name"],
                "status": "passed",
                "validator": acceptance["validator"],
            }
        )
    _write_json(acceptance_path, acceptance)

    for member in manifest["members"]:
        path = root / member["path"]
        member["digest"] = sha256_digest(path.read_bytes())
        member["byteLength"] = len(path.read_bytes())
    basis = dict(manifest)
    basis.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = _canonical_digest_without_lf(basis)
    _write_json(manifest_path, manifest)


def _install_producer_validation(root: Path, **overrides: Any) -> None:
    manifest_path = root / "atlas-manifest.json"
    acceptance_path = root / "atlas-acceptance.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    accounting = json.loads(
        (root / "atlas-source-accounting.json").read_text(encoding="utf-8")
    )
    construction = json.loads(
        (root / "atlas-construction-summary.json").read_text(encoding="utf-8")
    )
    proof = {
        "assertedInventoryDigest": manifest["graphs"][0]["inventoryDigest"],
        "binding": dict(manifest["binding"]),
        "checks": ["unit-test compiled producer proof"],
        "constructionSummary": {
            "compactPackCount": construction["compactPackCount"],
            "compactPackInventoryDigest": construction[
                "compactPackInventoryDigest"
            ],
            "digest": sha256_digest(
                (root / "atlas-construction-summary.json").read_bytes()
            ),
            "path": "atlas-construction-summary.json",
            "profile": "atlas-3-authenticated-construction-summary-v1",
            "releaseCount": construction["releaseCount"],
            "releaseInventoryDigest": construction["releaseInventoryDigest"],
        },
        "constructorProfile": "atlas-3-source-and-evidence-backed-mapping-compiled-shacl-v1",
        "counts": dict(manifest["counts"]),
        "implementationDigest": "sha256:" + "1" * 64,
        "mode": "compiledSourceAndEvidenceBackedMappingProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "sourceAccountingDigest": sha256_digest(
            (root / "atlas-source-accounting.json").read_bytes()
        ),
        "sourceReleaseCount": accounting["totals"]["sourceReleases"],
        "status": "passed",
        "type": "AtlasProducerValidation",
        "version": "3.0",
    }
    proof.update(overrides)
    proof_path = root / "atlas-producer-validation.json"
    _write_json(proof_path, proof)
    proof_payload = proof_path.read_bytes()
    proof_digest = sha256_digest(proof_payload)
    producer_member = next(
        row for row in manifest["members"] if row["role"] == "producerValidation"
    )
    producer_member.update(
        {
            "byteLength": len(proof_payload),
            "digest": proof_digest,
            "mediaType": "application/json",
            "path": "atlas-producer-validation.json",
        }
    )
    acceptance["inputs"]["producerValidationDigest"] = proof_digest
    for gate in acceptance["gates"]:
        gate["evidenceDigest"] = _canonical_digest_without_lf(
            {
                "inputs": acceptance["inputs"],
                "name": gate["name"],
                "status": "passed",
                "validator": acceptance["validator"],
            }
        )
    _write_json(acceptance_path, acceptance)
    acceptance_member = next(
        row for row in manifest["members"] if row["role"] == "acceptance"
    )
    acceptance_payload = acceptance_path.read_bytes()
    acceptance_member["byteLength"] = len(acceptance_payload)
    acceptance_member["digest"] = sha256_digest(acceptance_payload)
    basis = dict(manifest)
    basis.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = _canonical_digest_without_lf(basis)
    _write_json(manifest_path, manifest)


def _semantic_construction(**overrides: Any) -> dict[str, Any]:
    construction = {
        "inputFileCount": 37,
        "inputInventoryDigest": "sha256:" + "2" * 64,
        "profile": "atlas-3-exact-input-whole-distribution-reuse-v1",
        "recipeDigest": "sha256:" + "3" * 64,
        "reuseScope": "wholeDistributionExactInputsOnly",
    }
    construction.update(overrides)
    return construction


def test_opens_packed_distribution_and_checks_trusted_manifest() -> None:
    trusted_digest = sha256_digest((FIXTURE / "atlas-manifest.json").read_bytes())
    distribution = open_atlas_v3_explorer_distribution(
        FIXTURE,
        trusted_manifest_digest=trusted_digest,
    )

    assert distribution.trusted_manifest
    assert distribution.manifest_digest == trusted_digest
    assert distribution.dataset_quad_counts == {
        row["role"]: row["quadCount"] for row in distribution.manifest["graphs"]
    }
    assert len(distribution.asserted_graph) <= distribution.dataset_quad_counts["asserted"]
    assert len(distribution.projection_graph) <= distribution.dataset_quad_counts["projection"]
    assert len(distribution.derived_graph) <= distribution.dataset_quad_counts["derived"]
    assert distribution.visual_index["fullDatasetRdfLibParsed"] is False
    with pytest.raises(Atlas3ExplorerError, match="unknown Atlas 3.0 graph role"):
        distribution.graph("union")


def test_requires_authenticated_construction_summary_and_hashes_compact_transport(
    tmp_path: Path,
) -> None:
    target = tmp_path / "compact-transport-tamper"
    shutil.copytree(FIXTURE, target)
    summary = json.loads(
        (target / "atlas-construction-summary.json").read_text(encoding="utf-8")
    )
    compact_path = target / summary["compactPacks"][0]["path"]
    damaged = bytearray(compact_path.read_bytes())
    damaged[len(damaged) // 2] ^= 1
    compact_path.write_bytes(damaged)

    with pytest.raises(Atlas3ExplorerError, match="compact pack .* transport pin"):
        _open_distribution(target)


def test_compact_pack_rows_are_not_decoded_for_visualization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = explorer_module.zstd.open

    def reject_compact_decode(path_or_stream, *args, **kwargs):
        name = str(getattr(path_or_stream, "name", path_or_stream))
        if "/packs/compact/" in name:
            raise AssertionError("the explorer must not decode compact logical rows")
        return original(path_or_stream, *args, **kwargs)

    monkeypatch.setattr(explorer_module.zstd, "open", reject_compact_decode)

    distribution = _open_distribution()

    assert distribution.construction_summary["compactPackCount"] == 1


def test_opens_distribution_with_compiled_producer_proof(tmp_path: Path) -> None:
    target = tmp_path / "with-producer-proof"
    shutil.copytree(FIXTURE, target)
    _install_producer_validation(target)

    distribution = _open_distribution(target)

    assert distribution.trusted_manifest
    assert distribution.manifest["members"][2]["role"] == "producerValidation"


def test_opens_producer_proof_with_closed_semantic_construction_receipt(
    tmp_path: Path,
) -> None:
    target = tmp_path / "with-semantic-construction"
    shutil.copytree(FIXTURE, target)
    construction_summary = json.loads(
        (target / "atlas-construction-summary.json").read_text(encoding="utf-8")
    )
    recipe_digest = explorer_module._canonical_digest(
        {
            "adapterRecipes": [
                {
                    "adapterRecipeDigest": release["adapterRecipeDigest"],
                    "key": release["key"],
                }
                for release in construction_summary["releases"]
            ],
            "profile": "atlas-3-exact-input-whole-distribution-reuse-v1",
            "sharedRecipeDigest": construction_summary["recipeDigest"],
        }
    )
    _install_producer_validation(
        target,
        semanticConstruction=_semantic_construction(recipeDigest=recipe_digest),
    )

    distribution = _open_distribution(target)

    assert distribution.trusted_manifest


@pytest.mark.parametrize(
    "semantic_construction, message",
    [
        (_semantic_construction(inputFileCount=0), "inputFileCount must be positive"),
        (_semantic_construction(inputFileCount=True), "non-negative integer"),
        (_semantic_construction(inputInventoryDigest="sha256:bad"), "inputInventoryDigest"),
        (_semantic_construction(recipeDigest="sha256:bad"), "recipeDigest"),
        (_semantic_construction(profile="another-profile"), "identity differs"),
        (_semantic_construction(reuseScope="partialInputs"), "identity differs"),
        (_semantic_construction(unexpected=True), "fields differ"),
        ("not-an-object", "must be an object"),
    ],
)
def test_rejects_invalid_semantic_construction_receipts(
    tmp_path: Path,
    semantic_construction: object,
    message: str,
) -> None:
    target = tmp_path / "invalid-semantic-construction"
    shutil.copytree(FIXTURE, target)
    _install_producer_validation(
        target,
        semanticConstruction=semantic_construction,
    )

    with pytest.raises(Atlas3ExplorerError, match=message):
        _open_distribution(target)


def test_rejects_unknown_producer_validation_field_with_semantic_construction(
    tmp_path: Path,
) -> None:
    target = tmp_path / "unknown-producer-field"
    shutil.copytree(FIXTURE, target)
    _install_producer_validation(
        target,
        semanticConstruction=_semantic_construction(),
        unexpectedProducerField=True,
    )

    with pytest.raises(Atlas3ExplorerError, match="producer validation fields differ"):
        _open_distribution(target)


def test_compiled_producer_source_release_count_uses_accounting_total(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "producer-proof-source-count"
    shutil.copytree(FIXTURE, target)
    manifest_release_count = json.loads(
        (target / "atlas-manifest.json").read_text(encoding="utf-8")
    )["counts"]["releases"]
    expected = manifest_release_count + 1
    _install_producer_validation(target, sourceReleaseCount=expected)

    original_summary = explorer_module._source_accounting_summary

    def accounting_summary(*args, **kwargs):
        summary = original_summary(*args, **kwargs)
        summary["totals"]["sourceReleases"] = expected
        return summary

    monkeypatch.setattr(
        explorer_module,
        "_source_accounting_summary",
        accounting_summary,
    )
    observed: list[int] = []
    original = explorer_module._verify_producer_validation

    def capture(*args, **kwargs):
        observed.append(args[4])
        return original(*args, **kwargs)

    monkeypatch.setattr(explorer_module, "_verify_producer_validation", capture)

    distribution = _open_distribution(target)

    assert observed == [expected]
    assert expected != distribution.manifest["counts"]["releases"]


def test_rejects_legacy_source_only_compiled_producer_identity(
    tmp_path: Path,
) -> None:
    target = tmp_path / "legacy-producer-proof"
    shutil.copytree(FIXTURE, target)
    _install_producer_validation(
        target,
        constructorProfile="atlas-3-source-only-compiled-shacl-v1",
        mode="compiledSourceProducerValidation",
    )

    with pytest.raises(Atlas3ExplorerError, match="producer validation identity"):
        _open_distribution(target)


def test_build_preview_writes_digest_pinned_full_corpus_shards(tmp_path: Path) -> None:
    output = tmp_path / "atlas-preview.html"
    digest = sha256_digest((FIXTURE / "atlas-manifest.json").read_bytes())

    assert build_preview(FIXTURE, output, manifest_digest=digest) == output
    rendered = output.read_text(encoding="utf-8")
    assert "RefSpec Atlas 3.0 explorer" in rendered
    assert "<canvas" in rendered
    embedded_match = re.search(
        r'<script id="atlas-data" type="application/json">(.*?)</script>',
        rendered,
        re.DOTALL,
    )
    assert embedded_match is not None
    embedded = json.loads(embedded_match.group(1))
    bundle = embedded["fullCorpus"]
    asserted_inventory = next(
        row["inventoryDigest"]
        for row in _open_distribution().manifest["graphs"]
        if row["role"] == "asserted"
    )
    assert bundle["manifestDigest"] == digest
    assert bundle["assertedInventoryDigest"] == asserted_inventory
    assert bundle["builderRecipe"] == "atlas-3-static-full-corpus-shards-gzip-v3"
    assert bundle["schema"] == (
        "https://refspec.org/schema/atlas-explorer-static-shards/v2"
    )

    index_path = output.parent / bundle["index"]["url"]
    index_transport, index = _read_static_shard(output.parent, bundle["index"])
    assert index_transport[:4] == b"\x1f\x8b\x08\x00"
    assert index_transport[4:8] == b"\x00\x00\x00\x00"
    assert index["manifestDigest"] == bundle["manifestDigest"]
    assert index["assertedInventoryDigest"] == bundle["assertedInventoryDigest"]
    assert index["builderRecipe"] == bundle["builderRecipe"]
    assert index["schema"] == bundle["schema"]
    assert index["counts"]["resources"] == embedded["summary"]["availableResources"]

    records: list[dict[str, Any]] = []
    for prefix, reference in index["records"]["shards"].items():
        assert len(prefix) == index["records"]["prefixLength"]
        _transport, shard = _read_static_shard(output.parent, reference)
        assert shard["key"] == prefix
        assert shard["kind"] == "records"
        assert all(
            hashlib.sha256(record["id"].encode()).hexdigest().startswith(prefix)
            for record in shard["records"]
        )
        records.extend(shard["records"])
    assert len(records) == index["counts"]["records"]
    summaries = [record["summary"] for record in records if "summary" in record]
    assert len(summaries) == index["counts"]["resources"]
    assert any(record.get("relations") for record in records)
    release_resource_entries: list[dict[str, Any]] = []
    for release, references in index["releaseResources"]["shards"].items():
        observed = 0
        for reference in references:
            assert reference["release"] == release
            _transport, shard = _read_static_shard(output.parent, reference)
            assert shard["kind"] == "releaseResources"
            assert shard["release"] == release
            assert all(row["release"] == release for row in shard["entries"])
            observed += len(shard["entries"])
            release_resource_entries.extend(shard["entries"])
        assert observed == index["releaseResources"]["counts"][release]
    assert len(release_resource_entries) == index["counts"]["releaseResourceEntries"]
    assert len(release_resource_entries) == index["counts"]["resources"]
    release_graph_entries: list[dict[str, Any]] = []
    for release, references in index["releaseGraphs"]["shards"].items():
        observed = 0
        for reference in references:
            assert reference["release"] == release
            _transport, shard = _read_static_shard(output.parent, reference)
            assert shard["kind"] == "releaseGraph"
            assert shard["release"] == release
            assert all(
                row["layer"] in {"asserted", "projection", "derived"}
                for row in shard["entries"]
            )
            assert all(row["subjectLabel"] for row in shard["entries"])
            assert all(row["objectLabel"] for row in shard["entries"])
            observed += len(shard["entries"])
            release_graph_entries.extend(shard["entries"])
        assert observed == index["releaseGraphs"]["counts"][release]
    assert release_graph_entries
    assert len(release_graph_entries) == index["counts"]["releaseGraphEntries"]
    relation_ids_by_layer = {
        layer: {
            row["id"] for row in release_graph_entries if row["layer"] == layer
        }
        for layer in ("asserted", "projection", "derived")
    }
    assert len(relation_ids_by_layer["asserted"]) == embedded["summary"][
        "availableAssertedRelations"
    ]
    assert len(relation_ids_by_layer["projection"]) == embedded["summary"][
        "availableProjectedRelations"
    ]
    assert len(relation_ids_by_layer["derived"]) == embedded["summary"][
        "availableDerivedRelations"
    ]
    assert all(path.name.endswith(".json.gz") for path in index_path.parent.iterdir())

    # Rebuilding the same manifest at the same location is byte-identical.
    before = {path.name: path.read_bytes() for path in index_path.parent.iterdir()}
    assert build_preview(FIXTURE, output, manifest_digest=digest) == output
    after = {path.name: path.read_bytes() for path in index_path.parent.iterdir()}
    assert after == before


def test_opens_zstd_multi_pack_distribution_without_projection(tmp_path: Path) -> None:
    asserted_only = tmp_path / "asserted-only"
    _write_current_packed_fixture(
        FIXTURE_SOURCE,
        asserted_only,
        include_views=False,
        compression="zstd",
        split_asserted_packs=True,
    )

    first = _open_distribution(asserted_only)
    second = _open_distribution(asserted_only)
    first_model = build_atlas_v3_explorer_model(first)
    second_model = build_atlas_v3_explorer_model(second)

    assert first.visual_index["packCount"] == 2
    assert first.dataset_quad_counts["projection"] == 0
    assert len(first.projection_graph) == 0
    assert first_model["projectedRelations"] == []
    assert first_model["assertedRelations"]
    assert first_model["assertedRelations"][0]["id"] in render_atlas_explorer(first_model)
    assert first_model["resources"] == second_model["resources"]
    assert first_model["assertedRelations"] == second_model["assertedRelations"]
    assert [pack["packId"] for pack in first.manifest["packs"]] == sorted(
        pack["packId"] for pack in first.manifest["packs"]
    )


def test_zstd_pack_transport_is_hashed_during_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asserted_only = tmp_path / "asserted-only"
    _write_current_packed_fixture(
        FIXTURE_SOURCE,
        asserted_only,
        include_views=False,
        compression="zstd",
        split_asserted_packs=True,
    )
    original = explorer_module._scan_binary_stream

    def reject_compressed_prescan(stream):
        if str(getattr(stream, "name", "")).endswith(".nq.zst"):
            raise AssertionError("compressed RDF packs must be read only by the decoder")
        return original(stream)

    monkeypatch.setattr(
        explorer_module,
        "_scan_binary_stream",
        reject_compressed_prescan,
    )

    distribution = _open_distribution(asserted_only)

    assert distribution.visual_index["packCount"] == 2


def test_rejects_zstd_transport_or_uncompressed_content_drift(tmp_path: Path) -> None:
    transport_drift = tmp_path / "transport-drift"
    _write_current_packed_fixture(
        FIXTURE_SOURCE,
        transport_drift,
        include_views=False,
        compression="zstd",
    )
    manifest_path = transport_drift / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack_path = transport_drift / manifest["packs"][0]["path"]
    with pack_path.open("ab") as stream:
        stream.write(b"\x00")
    with pytest.raises(Atlas3ExplorerError, match="transport pin differs"):
        _open_distribution(transport_drift)

    content_drift = tmp_path / "content-drift"
    _write_current_packed_fixture(
        FIXTURE_SOURCE,
        content_drift,
        include_views=False,
        compression="zstd",
    )
    manifest_path = content_drift / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pack = manifest["packs"][0]
    pack_path = content_drift / pack["path"]
    with explorer_module.zstd.open(pack_path, "rb") as stream:
        payload = stream.read()
    marker = payload.index(b"sha256:") + len(b"sha256:")
    replacement = b"0" if payload[marker : marker + 1] != b"0" else b"1"
    payload = payload[:marker] + replacement + payload[marker + 1 :]
    with explorer_module.zstd.open(pack_path, "wb", level=1) as stream:
        stream.write(payload)
    pack["transport"]["byteLength"] = pack_path.stat().st_size
    pack["transport"]["digest"] = sha256_digest(pack_path.read_bytes())
    basis = dict(manifest)
    basis.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = _canonical_digest_without_lf(basis)
    _write_json(manifest_path, manifest)
    with pytest.raises(Atlas3ExplorerError, match="content pin or counts differ"):
        _open_distribution(content_drift)


def test_model_preserves_authority_provenance_and_alternate_only_labels() -> None:
    distribution = _open_distribution()
    model = build_atlas_v3_explorer_model(distribution)

    assert EXPLORER_TYPE == ATLAS_V3_EXPLORER_TYPE
    assert model["authority"]["asserted"]["status"] == "authoritative"
    assert model["authority"]["projection"]["status"] == "reproducibleConvenienceView"
    assert model["authority"]["derived"]["status"] == "nonAuthoritative"
    assert model["acceptance"]["receiptVerified"] is True
    assert model["acceptance"]["bindingDigestChecked"] is True
    assert model["acceptance"]["gatesReexecutedByExplorer"] is False
    assert len(model["resourceIndex"]) == model["summary"]["availableResources"]
    assert model["visualIndex"]["complete"] is True
    assert sum(model["coverage"]["resourcesByRing"].values()) == model["summary"]["availableResources"]
    assert sum(row["count"] for row in model["coverage"]["resourcesByRelease"]) == model["summary"]["availableResources"]
    assert sum(row["sourceRecords"] for row in model["coverage"]["sourceRecordsByRelease"]) == model["summary"]["availableSourceRecords"]
    assert all(
        "representedAssertions" in row
        for row in model["sourceAccounting"]["inputs"]
    )
    assert {row["id"] for row in model["resources"]} <= {
        row["id"] for row in model["resourceIndex"]
    }
    assert {
        label.get("language")
        for resource in model["resources"]
        for label in resource["labels"]
    } <= {None, "en"}

    alternate_only = next(row for row in model["resources"] if row["id"].endswith("subject-a-child"))
    assert alternate_only["displayLabel"] == "Agency procedure"
    assert alternate_only["displayLabelRole"] == "alternate"
    assert {label["role"] for label in alternate_only["labels"]} == {"alternate"}
    source_record = next(row for row in model["sourceRecords"] if row["id"] in alternate_only["sourceRecords"])
    assert source_record["nativePayload"]["publisherOptionalValue"] is None

    related = next(
        row
        for row in model["assertedRelations"]
        if row["predicate"] == str(ATLAS.thesaurusRelated)
    )
    assert related["authority"] == "authoritative"
    assert related["authoritative"] is True
    assert "direct associative link" in related["predicateMeaning"]
    assert "directly relevant" in related["predicateMeaning"]
    evidence_source = next(
        row for row in model["sourceRecords"] if row["id"] == related["evidence"][0]["sourceRecord"]
    )
    assert evidence_source["nativePayload"]
    assert related["evidence"][0]["sourceRecordContentDigest"] == evidence_source["contentDigest"]
    assert related["policy"]["payload"]

    projected = next(
        row for row in model["projectedRelations"] if related["id"] in row["supportingAssertions"]
    )
    assert projected["authoritative"] is False
    assert projected["authority"] == "reproducibleProjection"

    derived = model["derivedRelations"][0]
    assert derived["authoritative"] is False
    assert derived["authority"] == "nonAuthoritative"
    assert len(derived["derivedFromAssertions"]) == 2
    assert derived["rule"] == "urn:ref:rule:skos-exact-match-closure-path"

    rendered = render_atlas_explorer(model)
    assert '<canvas id="graph"' in rendered
    assert 'id="authority-asserted"' in rendered
    assert 'id="authority-projection"' in rendered
    assert 'id="authority-derived"' in rendered
    assert 'id="show-source-assignments"' in rendered
    assert 'id="ring-filter"' in rendered
    assert 'ringLabels={subject:"Subject",entity:"Entity"' in rendered
    assert "data.resourceIndex.forEach" in rendered
    assert 'id="inspector"' in rendered
    assert "Projection duplicates and source assignments stay hidden" in rendered
    assert "Meaning" in rendered
    assert "Why it is here" in rendered
    assert "Back to relations" in rendered
    assert "Evidence" in rendered
    assert "Supporting assertions" in rendered
    assert "Technical details" in rendered
    assert "It is provenance, not a topic relation" in rendered
    assert rendered.index(">Relations</h3>") < rendered.index(">About this resource</summary>")
    assert "Evidence and source records" not in rendered
    assert "<summary>Policy</summary>" not in rendered
    assert "requestAnimationFrame" in rendered
    assert "<table" not in rendered


def test_mapping_provenance_survives_full_and_compact_source_record_views() -> None:
    distribution = _open_distribution()
    graph = distribution.asserted_graph
    assertion = next(graph.subjects(RDF.type, ATLAS.MappingAssertion))
    binding = next(graph.subjects(RKAF.bindsAssertion, assertion))
    record = graph.value(binding, ATLAS.evidenceSourceRecord)
    assert isinstance(record, URIRef)
    payload = _mapping_adoption_payload()
    graph.remove((record, ATLAS.nativePayload, None))
    graph.add(
        (
            record,
            ATLAS.nativePayload,
            Literal(json.dumps(payload, sort_keys=True, separators=(",", ":"))),
        )
    )

    full = explorer_module._source_record_view(graph, record)
    compact = explorer_module._source_record_view(
        graph,
        record,
        compact_native_payload=True,
    )

    assert full["nativePayload"] == payload
    assert compact["nativePayload"] == {
        key: value
        for key, value in payload.items()
        if key in explorer_module._MAPPING_PROVENANCE_PAYLOAD_FIELDS
    }
    assert compact["nativePayloadMetadataOnly"] is True


def test_mapping_inspector_explains_versioned_operator_adoption() -> None:
    rendered = render_atlas_explorer(
        build_atlas_v3_explorer_model(_open_distribution())
    )
    provenance = re.search(
        r"/\* atlas-mapping-provenance:start \*/(.*?)"
        r"/\* atlas-mapping-provenance:end \*/",
        rendered,
        flags=re.DOTALL,
    )
    assert provenance is not None
    payload = json.dumps(_mapping_adoption_payload(), separators=(",", ":"))
    script = "\n".join(
        (
            (
                "const esc=value=>String(value??'').replace(/[&<>\"']/g, char=>"
                "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[char]));"
            ),
            "const reviewMethod=method=>({title:String(method)});",
            f"const sourceById=new Map([['urn:test:record',{{nativePayload:{payload}}}]]);",
            provenance.group(1),
            (
                "process.stdout.write(mappingEvidenceBrief({"
                "kind:'mapping',sourceRelease:'urn:ref:atlas-release:3:eurovoc:4.24',"
                "targetRelease:'urn:ref:atlas-release:3:lcsh:2026-08-06',"
                "evidence:[{sourceRecord:'urn:test:record',reviewMethod:'operatorAdoption',"
                "decidedAt:'2026-08-06T00:00:00Z'}]}));"
            ),
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Official alignment 20240711-0 · issued 2024-07-11" in completed.stdout
    assert "EuroVoc 4.20 · LCSH release not stated" in completed.stdout
    assert "Atlas decision 2026-08-06 · Operator adoption" in completed.stdout
    assert "urn:ref:atlas-release:3:eurovoc:4.24" in completed.stdout
    assert "urn:ref:atlas-release:3:lcsh:2026-08-06" in completed.stdout
    assert (
        "EuroVoc 4.24 aggregate metadata does not re-review individual pairs."
        in completed.stdout
    )


def test_source_accounting_summary_counts_assertion_only_representation() -> None:
    distribution = _open_distribution()
    accounting = {
        "type": "AtlasSourceAccounting",
        "version": "3.0",
        "distributionId": distribution.manifest["distributionId"],
        "inputs": [
            {
                "sourceRelease": "urn:test:alignment-release",
                "membershipMode": "complete",
                "declaredMemberCount": 1,
                "dispositions": [
                    {
                        "sourceRecord": "urn:test:mapping-row",
                        "status": "represented",
                        "atlasAssertions": ["urn:test:mapping-assertion"],
                    }
                ],
            }
        ],
        "totals": {
            "sourceReleases": 1,
            "sourceRecords": 1,
            "represented": 1,
            "excluded": 0,
            "unresolved": 0,
        },
    }

    summary = explorer_module._source_accounting_summary(
        distribution.manifest,
        distribution._streamed_index,
        accounting,
        directly_verified=True,
    )

    assert summary["inputs"][0]["representedResources"] == 0
    assert summary["inputs"][0]["representedAssertions"] == 1


def test_identifier_records_are_attached_to_their_resource_with_readable_authority() -> None:
    model = build_atlas_v3_explorer_model(_open_distribution())
    resource = next(
        row for row in model["resources"] if row["id"].endswith("resource:entity-agency")
    )

    assert resource["identifiers"] == [
        {
            "id": "urn:ref:atlas-fixture:identifier:agency",
            "value": "AGENCY-001",
            "scheme": "urn:ref:atlas-fixture:scheme:entities",
            "schemeLabel": "entities",
            "schemeProfile": "identifierScheme",
            "identifies": resource["id"],
            "contentDigest": "sha256:3eb59d5612ca3693b9f92003854abf9d6acd81a702756000251622af0de6b8af",
            "sourceRecordCount": 1,
            "sourceRecord": "urn:ref:atlas-fixture:source-record:entity-agency",
        }
    ]
    assert model["summary"]["availableIdentifiers"] == 1
    assert model["summary"]["indexedIdentifiers"] == 1
    assert model["summary"]["shownIdentifiers"] == 1
    assert model["visualIndex"]["materialized"]["identifiers"] == 1
    assert model["visualIndex"]["limits"]["identifiers"] == explorer_module._VISUAL_IDENTIFIER_LIMIT

    rendered = render_atlas_explorer(model)
    assert "Identifiers" in rendered
    assert "Scheme / authority" in rendered
    assert "AGENCY-001" in rendered
    assert "row.value,row.schemeLabel" in rendered

    resource["identifiers"][0]["identifies"] = "urn:ref:atlas-fixture:resource:wrong"
    with pytest.raises(Atlas3ExplorerError, match="attached to the wrong resource"):
        render_atlas_explorer(model)


def test_streaming_identifier_selection_is_deterministic_and_bounded() -> None:
    scheme = b"<urn:test:identifier-scheme>"

    def build_index():
        builder = explorer_module._StreamingIndexBuilder()
        for index in range(5_000):
            builder.consume(
                f"<urn:test:identifier:{index:05d}>".encode(),
                {explorer_module._IDENTIFIER_TYPE_TOKEN},
                {
                    explorer_module._ATLAS_IDENTIFIER_SCHEME_TOKEN: scheme,
                    explorer_module._ATLAS_IDENTIFIES_TOKEN: (
                        f"<urn:test:resource:{index:05d}>".encode()
                    ),
                },
                (),
                0,
                (),
                0,
                0,
                0,
            )
        return builder.finish(
            byte_length=1,
            digest="sha256:" + "0" * 64,
            graph_quad_counts={"asserted": 25_000, "projection": 0, "derived": 0},
        )

    first = build_index()
    second = build_index()

    assert len(first.identifier_ids) == explorer_module._VISUAL_IDENTIFIER_LIMIT
    assert len(first.resource_ids) == explorer_module._VISUAL_IDENTIFIER_LIMIT
    assert first.identifier_ids == second.identifier_ids
    assert first.resource_ids == second.resource_ids
    assert first.record_counts["identifiers"] == 5_000


def test_model_exposes_cross_ring_assertions_and_projections_by_both_endpoint_rings() -> None:
    model = build_atlas_v3_explorer_model(_open_distribution())
    assertions = [row for row in model["assertedRelations"] if row["kind"] == "crossRing"]

    assert {
        (row["sourceRing"], row["targetRing"], row["predicateLabel"])
        for row in assertions
    } == {
        ("entity", "legalIdentity", "referencesLegalIdentity"),
        ("entity", "subject", "hasIndexedSubject"),
        ("legalIdentity", "subject", "hasIndexedSubject"),
    }
    assert all("semanticRing" not in row for row in assertions)
    assert all(row["semanticRings"] == [row["sourceRing"], row["targetRing"]] for row in assertions)
    assert all(row["predicateMeaning"] for row in assertions)
    assert {
        (row["sourceRing"], row["targetRing"])
        for row in model["projectedRelations"]
        if "sourceRing" in row
    } == {
        ("entity", "legalIdentity"),
        ("entity", "subject"),
        ("legalIdentity", "subject"),
    }
    assert model["coverage"]["crossRingRelationsByPair"] == [
        {"sourceRing": "entity", "targetRing": "legalIdentity", "count": 1},
        {"sourceRing": "entity", "targetRing": "subject", "count": 1},
        {"sourceRing": "legalIdentity", "targetRing": "subject", "count": 1},
    ]

    rendered = render_atlas_explorer(model)
    assert "is indexed under the subject" in rendered
    assert "references the legal identity" in rendered
    assert "Back to relations" in rendered


def test_cross_ring_filter_matches_either_endpoint_and_rejects_unrelated_rings() -> None:
    model = build_atlas_v3_explorer_model(_open_distribution())
    rendered = render_atlas_explorer(model)
    filter_core = re.search(
        r"/\* atlas-edge-ring-filter:start \*/(.*?)/\* atlas-edge-ring-filter:end \*/",
        rendered,
        flags=re.DOTALL,
    )

    assert filter_core is not None
    assert "ringEndpointIds.has(node.id)" in rendered
    script = "\n".join(
        (
            filter_core.group(1),
            """
const crossRing = {semanticRings: ["entity", "subject"]};
const sameRing = {semanticRing: "value", semanticRings: ["value"]};
process.stdout.write(JSON.stringify({
  source: edgeMatchesRing(crossRing, "entity"),
  target: edgeMatchesRing(crossRing, "subject"),
  unrelated: edgeMatchesRing(crossRing, "legalIdentity"),
  same: edgeMatchesRing(sameRing, "value")
}));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "source": True,
        "target": True,
        "unrelated": False,
        "same": True,
    }

    assertions = [row for row in model["assertedRelations"] if row["kind"] == "crossRing"]
    assertions[0]["predicate"] = "https://refspec.org/ns/atlas/v3#disallowedCrossRing"
    with pytest.raises(Atlas3ExplorerError, match="violates its policy"):
        render_atlas_explorer(model)


def test_rendered_explorer_javascript_is_syntactically_valid() -> None:
    rendered = render_atlas_explorer(
        build_atlas_v3_explorer_model(_open_distribution())
    )
    scripts = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", rendered, re.DOTALL)

    assert len(scripts) == 2
    subprocess.run(
        ["node", "--check", "-"],
        input=scripts[-1],
        check=True,
        capture_output=True,
        text=True,
    )
    verified_load = re.search(
        r"/\* atlas-verified-shard-load:start \*/(.*?)/\* atlas-verified-shard-load:end \*/",
        scripts[-1],
        re.DOTALL,
    )
    assert verified_load is not None
    verification = verified_load.group(1)
    transport_digest = verification.index(
        "observedTransportDigest=await sha256Bytes(transportBytes)"
    )
    decompression = verification.index("contentBytes=await decompressGzip(transportBytes)")
    content_digest = verification.index(
        "observedContentDigest=await sha256Bytes(contentBytes)"
    )
    parsing = verification.index("JSON.parse")
    assert transport_digest < decompression < content_digest < parsing
    assert "index.assertedInventoryDigest!==data.distribution.assertedInventoryDigest" in scripts[-1]
    assert 'location.protocol!=="file:"' in scripts[-1]
    assert 'typeof DecompressionStream==="function"' in scripts[-1]


def test_render_limit_loads_verified_catalog_pages_without_a_second_action() -> None:
    rendered = render_atlas_explorer(
        build_atlas_v3_explorer_model(_open_distribution())
    )

    assert 'id="browse-more"' not in rendered
    assert "function browseMore()" not in rendered
    assert "async function loadCatalogToLimit()" in rendered
    assert "const target=visibleResourceTarget()" in rendered
    assert "while(loaded<target)" in rendered
    assert "limitLoadTimer=setTimeout(applyRenderLimit,140)" in rendered
    assert "if(!fullIndex?.releaseResources)await loadCatalogToLimit()" in rendered
    assert "if(fullMode)void loadSelectedReleaseGraphs()" in rendered
    assert "Move the slider to load more resources." in rendered
    assert "async function loadReleaseGraph(release)" in rendered
    assert "async function loadReleaseResources(release)" in rendered
    assert "active.size>8" not in rendered
    assert "Math.max(1,fullBundle.counts.resources)" in rendered
    assert "state.renderedNodes.length<=5000" in rendered
    assert "let requestedRenderLimit=state.renderLimit" in rendered
    assert 'shard.kind!=="releaseResources"' in rendered
    assert 'shard.kind!=="releaseGraph"' in rendered
    assert "visible relations" in rendered


def test_search_results_scroll_through_ranked_matches() -> None:
    rendered = render_atlas_explorer(
        build_atlas_v3_explorer_model(_open_distribution())
    )

    assert 'id="search-pagination"' not in rendered
    assert 'id="search-previous"' not in rendered
    assert 'id="search-next"' not in rendered
    assert 'id="search-result-status"' in rendered
    assert "const searchPageSize=40" in rendered
    assert "state.searchRows.slice(0,state.searchVisible)" in rendered
    assert "if(localMatches.size>=24)break" not in rendered
    assert 'searchResults.addEventListener("scroll"' in rendered
    assert 'fetch("/api/capabilities"' in rendered
    assert "Ranking results with DuckDB BM25" in rendered
    assert "offset:String(state.searchOffset)" in rendered


def test_release_controls_hide_other_rings_and_clear_only_visible_releases() -> None:
    rendered = render_atlas_explorer(
        build_atlas_v3_explorer_model(_open_distribution())
    )
    controls = re.search(
        r"/\* atlas-release-filter-controls:start \*/(.*?)/\* atlas-release-filter-controls:end \*/",
        rendered,
        flags=re.DOTALL,
    )

    assert controls is not None
    assert 'id="select-no-releases"' in rendered
    script = "\n".join(
        (
            """
const state={ring:"subject",activeReleases:new Set(["subject-a","value-a"]),selected:{},inspectorReturn:{}};
const releaseById=new Map([
  ["subject-a",{id:"subject-a",title:"Subject A",semanticRing:"subject",color:"#111",memberCount:2}],
  ["value-a",{id:"value-a",title:"Value A",semanticRing:"value",color:"#222",memberCount:3}]
]);
const appended=[];
const root={replaceChildren(){appended.length=0;},append(value){appended.push(value);},querySelectorAll(){return[];}};
const clearButton={disabled:false};
const document={getElementById(id){return id==="release-filters"?root:clearButton;},createElement(){return{className:"",innerHTML:""};}};
const search={value:""};
const releaseLabel=row=>row.title;
const esc=value=>String(value);
const format=value=>String(value);
let refreshed=0;
function refresh(){refreshed++;}
function syncRenderCapacity(){}
async function renderSearch(){}
""",
            controls.group(1),
            """
const before={visible:visibleReleaseRows().map(row=>row.id),active:[...activeVisibleReleases()]};
selectNoReleases();
const after={active:[...state.activeReleases],selected:state.selected,inspectorReturn:state.inspectorReturn,refreshed};
state.ring="";
renderReleaseFilters();
process.stdout.write(JSON.stringify({before,after,allRows:appended.map(row=>row.innerHTML)}));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["before"] == {"visible": ["subject-a"], "active": ["subject-a"]}
    assert result["after"] == {
        "active": ["value-a"],
        "selected": None,
        "inspectorReturn": None,
        "refreshed": 1,
    }
    assert 'data-release="subject-a"' in result["allRows"][0]
    assert " checked" not in result["allRows"][0]
    assert 'data-release="value-a"' in result["allRows"][1]
    assert " checked" in result["allRows"][1]


def test_left_control_column_supports_pointer_and_keyboard_resize() -> None:
    rendered = render_atlas_explorer(
        build_atlas_v3_explorer_model(_open_distribution())
    )
    controls = re.search(
        r"/\* atlas-controls-resize:start \*/(.*?)/\* atlas-controls-resize:end \*/",
        rendered,
        flags=re.DOTALL,
    )

    assert controls is not None
    assert 'id="controls-resizer"' in rendered
    script = "\n".join(
        (
            """
globalThis.innerWidth=1440;
let width=272,captured=false;
const classes=new Set(),attributes={},handlers={};
const workspace={clientWidth:1400,style:{setProperty(_name,value){width=Number.parseInt(value,10);}},classList:{add(value){classes.add(value);},remove(value){classes.delete(value);}}};
const controlsPanel={getBoundingClientRect(){return{width};}};
const controlsResizer={
  addEventListener(name,handler){handlers[name]=handler;},
  setAttribute(name,value){attributes[name]=value;},
  setPointerCapture(){captured=true;},
  hasPointerCapture(){return captured;},
  releasePointerCapture(){captured=false;}
};
""",
            controls.group(1),
            """
handlers.pointerdown({button:0,pointerId:7,clientX:100,preventDefault(){}});
handlers.pointermove({pointerId:7,clientX:180});
const dragged=width;
handlers.pointerup({pointerId:7});
handlers.keydown({key:"ArrowRight",preventDefault(){}});
const keyboard=width;
handlers.dblclick();
process.stdout.write(JSON.stringify({dragged,keyboard,reset:width,captured,resizing:classes.has("resizing"),attributes}));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "dragged": 352,
        "keyboard": 368,
        "reset": 272,
        "captured": False,
        "resizing": False,
        "attributes": {"aria-valuemax": "520", "aria-valuenow": "272"},
    }


def test_browser_shard_loader_rejects_transport_and_content_tampering(
    tmp_path: Path,
) -> None:
    output = tmp_path / "verified-shards.html"
    manifest_digest = sha256_digest((FIXTURE / "atlas-manifest.json").read_bytes())
    build_preview(FIXTURE, output, manifest_digest=manifest_digest)
    rendered = output.read_text(encoding="utf-8")
    embedded_match = re.search(
        r'<script id="atlas-data" type="application/json">(.*?)</script>',
        rendered,
        re.DOTALL,
    )
    verified_load = re.search(
        r"/\* atlas-verified-shard-load:start \*/(.*?)/\* atlas-verified-shard-load:end \*/",
        rendered,
        re.DOTALL,
    )
    assert embedded_match is not None
    assert verified_load is not None
    embedded = json.loads(embedded_match.group(1))
    reference = embedded["fullCorpus"]["index"]
    transport = (output.parent / reference["url"]).read_bytes()

    transport_tamper = bytearray(transport)
    transport_tamper[-1] ^= 1
    content = gzip.decompress(transport)
    modified_content = content.replace(b'"type"', b'"tyPe"', 1)
    assert modified_content != content
    modified_transport = gzip.compress(modified_content, compresslevel=9, mtime=0)
    content_tamper_reference = json.loads(json.dumps(reference))
    content_tamper_reference["transport"] = {
        "byteLength": len(modified_transport),
        "compression": "gzip",
        "digest": sha256_digest(modified_transport),
    }

    script = "\n".join(
        (
            f"const data={json.dumps({'distribution': {'manifestDigest': manifest_digest}})};",
            "const shardPayloads=new Map();",
            'const textDecoder=new TextDecoder("utf-8",{fatal:true});',
            verified_load.group(1),
            "let responseBody;",
            "globalThis.fetch=async()=>new Response(responseBody,{status:200});",
            "async function attempt(encoded,ref){",
            "  shardPayloads.clear();",
            '  responseBody=Buffer.from(encoded,"base64");',
            "  try{await fetchVerifiedShard(ref);return 'accepted';}",
            "  catch(error){return String(error.message||error);}",
            "}",
            "(async()=>console.log(JSON.stringify({",
            f"  good:await attempt('{base64.b64encode(transport).decode()}',{json.dumps(reference)}),",
            f"  transport:await attempt('{base64.b64encode(transport_tamper).decode()}',{json.dumps(reference)}),",
            f"  content:await attempt('{base64.b64encode(modified_transport).decode()}',{json.dumps(content_tamper_reference)})",
            "})))();",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    results = json.loads(completed.stdout)
    assert results["good"] == "accepted"
    assert "transport digest" in results["transport"]
    assert "content digest" in results["content"]


def test_renderer_rejects_an_incomplete_resource_index() -> None:
    model = build_atlas_v3_explorer_model(_open_distribution())
    model["resourceIndex"] = model["resourceIndex"][:-1]

    with pytest.raises(Atlas3ExplorerError, match="resource index count differs"):
        render_atlas_explorer(model)


def test_model_limits_precede_detailed_views_and_preserve_full_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = _open_distribution()
    full_model = build_atlas_v3_explorer_model(distribution)
    function_names = (
        "_resource_view",
        "_assertion_view",
        "_projected_view",
        "_derived_view",
        "_source_record_view",
    )
    calls = dict.fromkeys(function_names, 0)

    for function_name in function_names:
        original = getattr(explorer_module, function_name)

        def counted(*args, _name=function_name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(explorer_module, function_name, counted)

    limited = build_atlas_v3_explorer_model(
        distribution,
        max_resources=1,
        max_assertions=1,
        max_projected_relations=1,
        max_derived_relations=0,
    )

    assert limited["resources"] == full_model["resources"][:1]
    assert limited["resourceIndex"] == full_model["resourceIndex"]
    assert len(limited["resourceIndex"]) == limited["summary"]["availableResources"]
    primary_assertion_id = full_model["assertedRelations"][0]["id"]
    assert primary_assertion_id in {row["id"] for row in limited["assertedRelations"]}
    assert limited["projectedRelations"] == full_model["projectedRelations"][:1]
    assert limited["derivedRelations"] == []
    assert calls["_resource_view"] == 1
    assert calls["_assertion_view"] == limited["summary"]["shownAssertedRelations"]
    assert limited["summary"]["provenanceClosureAssertedRelations"] >= 1
    assert calls["_projected_view"] == 1
    assert calls["_derived_view"] == 0
    assert calls["_source_record_view"] == limited["summary"]["shownSourceRecords"]
    assert calls["_source_record_view"] < limited["summary"]["availableSourceRecords"]
    assert all("nativePayload" in row for row in limited["sourceRecords"])

    for field in (
        "availableResources",
        "availableIdentifiers",
        "indexedIdentifiers",
        "availableSourceRecords",
        "availableAssertedRelations",
        "currentAuthoritativeRelations",
        "availableProjectedRelations",
        "availableDerivedRelations",
    ):
        assert limited["summary"][field] == full_model["summary"][field]
    assert limited["summary"]["truncated"] is True


def test_open_streams_nquads_packs_instead_of_reading_them_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes
    original_open = Path.open
    pack_open_count = 0

    def guarded_read_bytes(path: Path) -> bytes:
        if path.is_relative_to(FIXTURE / "packs") and path.name.endswith((".nq", ".nq.zst")):
            raise AssertionError("an Atlas pack must not be materialized as one bytes object")
        return original(path)

    def counted_open(path: Path, *args, **kwargs):
        nonlocal pack_open_count
        if path.is_relative_to(FIXTURE / "packs") and path.name.endswith((".nq", ".nq.zst")):
            pack_open_count += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "open", counted_open)
    monkeypatch.setattr(
        Dataset,
        "parse",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("the full Atlas must not be parsed into RDFLib")
        ),
    )

    distribution = _open_distribution()

    assert distribution.dataset_quad_counts["asserted"] == distribution.manifest["graphs"][0]["quadCount"]
    assert len(distribution.asserted_graph) <= distribution.dataset_quad_counts["asserted"]
    assert pack_open_count == 2


def test_streaming_index_is_deterministic_and_resource_bounded() -> None:
    release = b"<urn:test:release>"
    rings = tuple(f"<https://refspec.org/ns/atlas/v3#ring-{index}>".encode() for index in range(4))

    def build_index():
        builder = explorer_module._StreamingIndexBuilder()
        for index in range(5_000):
            builder.consume(
                f"<urn:test:resource:{index:05d}>".encode(),
                {explorer_module._ATLAS_RESOURCE_TYPE_TOKEN},
                {
                    explorer_module._ATLAS_IN_RELEASE_TOKEN: release,
                    explorer_module._ATLAS_SEMANTIC_RING_TOKEN: rings[index % len(rings)],
                },
                (),
                0,
                (),
                0,
                0,
                0,
            )
        return builder.finish(
            byte_length=1,
            digest="sha256:" + "0" * 64,
            graph_quad_counts={"asserted": 5_000, "projection": 0, "derived": 0},
        )

    first = build_index()
    second = build_index()

    assert len(first.resource_ids) == explorer_module._VISUAL_RESOURCE_LIMIT
    assert first.resource_ids == second.resource_ids
    assert first.resources_by_ring == dict.fromkeys(rings, 1_250)


def test_selected_node_neighbor_lookup_is_linear_and_keeps_direct_neighbors_visible() -> None:
    distribution = _open_distribution()
    rendered = render_atlas_explorer(build_atlas_v3_explorer_model(distribution))
    neighbor_core = re.search(
        r"/\* atlas-selected-node-neighbors:start \*/(.*?)/\* atlas-selected-node-neighbors:end \*/",
        rendered,
        flags=re.DOTALL,
    )

    assert neighbor_core is not None
    assert "state.renderedEdges.some(" not in rendered
    assert "selectedNodeNeighborIds(state.selected,eligibleEdges)" in rendered
    assert "selectedNeighbors.has(node.id)" in rendered
    assert 'state.selected={kind:"node",id:node.id};refresh(false,false)' in rendered
    script = "\n".join(
        (
            neighbor_core.group(1),
            """
const edges = [
  {subject: "a", object: "b"},
  {subject: "c", object: "a"},
  {subject: "d", object: "e"}
];
const result = {
  selectedNode: [...selectedNodeNeighborIds({kind: "node", id: "a"}, edges)].sort(),
  selectedEdge: [...selectedNodeNeighborIds({kind: "edge", id: "edge-1"}, edges)].sort(),
  noSelection: [...selectedNodeNeighborIds(null, edges)].sort()
};
process.stdout.write(JSON.stringify(result));
""",
        )
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "selectedNode": ["a", "b", "c"],
        "selectedEdge": [],
        "noSelection": [],
    }


def test_bounded_model_adds_every_referenced_assertion_for_provenance() -> None:
    distribution = _open_distribution()
    projection = distribution.projection_graph
    relation = next(projection.subjects(None, ATLAS.ProjectedRelation))
    existing_support = set(projection.objects(relation, ATLAS.supportingAssertion))
    extra_assertion = next(
        assertion
        for assertion in distribution.asserted_graph.subjects(None, ATLAS.RelationAssertion)
        if assertion not in existing_support
    )
    projection.add((relation, ATLAS.supportingAssertion, extra_assertion))

    model = build_atlas_v3_explorer_model(
        distribution,
        max_assertions=0,
        max_derived_relations=1,
    )
    row = next(item for item in model["projectedRelations"] if item["id"] == str(relation))
    assert str(extra_assertion) in row["supportingAssertions"]
    assert row["supportingAssertions"] == sorted(row["supportingAssertions"])
    shown_assertions = {item["id"] for item in model["assertedRelations"]}
    assert set(row["supportingAssertions"]).issubset(shown_assertions)
    assert set(model["derivedRelations"][0]["derivedFromAssertions"]).issubset(shown_assertions)
    assert model["summary"]["provenanceClosureAssertedRelations"] == len(shown_assertions)

    unclosed = dict(model)
    unclosed["assertedRelations"] = []
    with pytest.raises(Atlas3ExplorerError, match="not provenance-closed"):
        render_atlas_explorer(unclosed)


def test_rejects_dataset_path_replacement_during_streaming_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raced = tmp_path / "raced"
    shutil.copytree(FIXTURE, raced)
    original_materialize = explorer_module._materialize_visual_dataset

    def replacing_materialize(plans, index, graph_ids):
        pack_path = plans[0].path
        moved_path = pack_path.with_name("opened-" + pack_path.name)
        pack_path.replace(moved_path)
        shutil.copyfile(moved_path, pack_path)
        try:
            return original_materialize(plans, index, graph_ids)
        finally:
            moved_path.unlink()

    monkeypatch.setattr(explorer_module, "_materialize_visual_dataset", replacing_materialize)

    with pytest.raises(Atlas3ExplorerError, match="changed while it was being (?:opened|read)"):
        _open_distribution(raced)


def test_rejects_changed_dataset_and_forged_gate_receipt(tmp_path: Path) -> None:
    changed_dataset = tmp_path / "changed-dataset"
    shutil.copytree(FIXTURE, changed_dataset)
    changed_manifest = json.loads(
        (changed_dataset / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    with (changed_dataset / changed_manifest["packs"][0]["path"]).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(Atlas3ExplorerError, match="pack .* lines must be non-empty"):
        _open_distribution(changed_dataset)

    forged_gate = tmp_path / "forged-gate"
    shutil.copytree(FIXTURE, forged_gate)
    acceptance_path = forged_gate / "atlas-acceptance.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["gates"][0]["evidenceDigest"] = "sha256:" + "0" * 64
    _write_json(acceptance_path, acceptance)
    manifest_path = forged_gate / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acceptance_member = next(row for row in manifest["members"] if row["path"] == "atlas-acceptance.json")
    acceptance_member["digest"] = sha256_digest(acceptance_path.read_bytes())
    acceptance_member["byteLength"] = len(acceptance_path.read_bytes())
    basis = dict(manifest)
    basis.pop("canonicalPayloadDigest")
    manifest["canonicalPayloadDigest"] = _canonical_digest_without_lf(basis)
    _write_json(manifest_path, manifest)
    with pytest.raises(Atlas3ExplorerError, match="evidenceDigest differs"):
        _open_distribution(forged_gate)


def test_dataset_scan_bounds_each_physical_line_before_accumulating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "atlas.nq"
    dataset.write_bytes(b"<urn:a> <urn:p> <urn:o> <urn:g> .\n")
    monkeypatch.setattr(explorer_module, "_NQUADS_MAX_LINE_BYTES", 8)

    with dataset.open("rb") as stream, pytest.raises(
        Atlas3ExplorerError,
        match="dataset line 1 exceeds 8 bytes",
    ):
        explorer_module._scan_dataset_member(
            stream,
            {
                "asserted": URIRef("urn:g"),
                "projection": URIRef("urn:projection"),
                "derived": URIRef("urn:derived"),
            },
        )


def test_rejects_receipt_for_a_different_atlas_v3_binding(tmp_path: Path) -> None:
    altered = tmp_path / "different-binding"
    shutil.copytree(FIXTURE, altered)
    manifest_path = altered / "atlas-manifest.json"
    acceptance_path = altered / "atlas-acceptance.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    forged_digest = "sha256:" + "0" * 64
    manifest["binding"]["bindingBundleDigest"] = forged_digest
    acceptance["inputs"]["bindingBundleDigest"] = forged_digest
    _write_json(manifest_path, manifest)
    _write_json(acceptance_path, acceptance)
    _reseal_changed_json_members(altered)

    with pytest.raises(Atlas3ExplorerError, match="authoritative v3 binding"):
        _open_distribution(altered)


def test_rejects_source_accounting_that_disagrees_with_rdf(tmp_path: Path) -> None:
    altered = tmp_path / "altered-accounting"
    shutil.copytree(FIXTURE, altered)
    accounting_path = altered / "atlas-source-accounting.json"
    accounting = json.loads(accounting_path.read_text(encoding="utf-8"))
    disposition = accounting["inputs"][0]["dispositions"][0]
    disposition["atlasResources"] = ["urn:ref:atlas-fixture:resource:not-this-record"]
    _write_json(accounting_path, accounting)
    _reseal_changed_json_members(altered)

    with pytest.raises(Atlas3ExplorerError, match="bidirectional RDF resource links"):
        _open_distribution(altered)


def test_unversioned_renderer_rejects_retired_atlas_2_shape() -> None:
    with pytest.raises(Atlas3ExplorerError, match="type or schemaVersion"):
        render_atlas_explorer(
            {
                "type": "urn:ref:type:VocabularyAtlasExplorerView",
                "schemaVersion": "4.0",
                "title": "Retired Atlas 2 view",
            }
        )

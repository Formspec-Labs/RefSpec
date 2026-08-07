from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "bindings" / "atlas" / "3.0" / "schemas"
DIGEST = "sha256:" + "1" * 64


def _validator() -> Draft202012Validator:
    registry = Registry()
    manifest_schema: dict[str, Any] | None = None
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        if path.name == "atlas-manifest.schema.json":
            manifest_schema = schema
    assert manifest_schema is not None
    return Draft202012Validator(
        manifest_schema,
        registry=registry,
        format_checker=FormatChecker(),
    )


def _counts() -> dict[str, int]:
    return {
        "crossRingRelationAssertions": 0,
        "derivedRelations": 0,
        "identifiers": 0,
        "labels": 0,
        "mappingAssertions": 0,
        "nativeRelationAssertions": 0,
        "projectedRelations": 0,
        "relationAssertions": 0,
        "releases": 1,
        "resources": 1,
        "sourceAssignments": 0,
        "sourceRecords": 1,
    }


def _binding() -> dict[str, str]:
    return {
        "acceptanceSchemaDigest": DIGEST,
        "bindingBundleDigest": DIGEST,
        "manifestSchemaDigest": DIGEST,
        "ontologyDigest": DIGEST,
        "shapesDigest": DIGEST,
        "sourceAccountingSchemaDigest": DIGEST,
        "validatorVersion": "3.0",
        "version": "3.0",
    }


def _members() -> list[dict[str, Any]]:
    return [
        {
            "byteLength": 10,
            "digest": DIGEST,
            "mediaType": "application/json",
            "path": "atlas-source-accounting.json",
            "role": "sourceAccounting",
        },
        {
            "byteLength": 10,
            "digest": DIGEST,
            "mediaType": "application/json",
            "path": "atlas-acceptance.json",
            "role": "acceptance",
        },
        {
            "byteLength": 10,
            "digest": DIGEST,
            "mediaType": "application/json",
            "path": "atlas-producer-validation.json",
            "role": "producerValidation",
        },
        {
            "byteLength": 10,
            "digest": DIGEST,
            "mediaType": "application/json",
            "path": "atlas-construction-summary.json",
            "role": "constructionSummary",
        },
    ]


def _manifest() -> dict[str, Any]:
    return {
        "binding": _binding(),
        "canonicalPayloadDigest": DIGEST,
        "counts": _counts(),
        "createdAt": "2026-08-06T00:00:00Z",
        "distributionId": "urn:ref:atlas-test:distribution",
        "format": "refspec-atlas-packed-nquads-3.0",
        "graphs": [
            {
                "id": "urn:ref:atlas-test:graph:asserted",
                "inventoryDigest": DIGEST,
                "packCount": 1,
                "quadCount": 1,
                "role": "asserted",
            },
            {
                "id": "urn:ref:atlas-test:graph:projection",
                "inventoryDigest": DIGEST,
                "packCount": 0,
                "quadCount": 0,
                "role": "projection",
            },
            {
                "id": "urn:ref:atlas-test:graph:derived",
                "inventoryDigest": DIGEST,
                "packCount": 0,
                "quadCount": 0,
                "role": "derived",
            },
        ],
        "members": _members(),
        "packs": [
            {
                "content": {
                    "byteLength": 100,
                    "digest": DIGEST,
                    "mediaType": "application/n-quads",
                    "quadCount": 1,
                },
                "dependencies": [],
                "graphCounts": {
                    "asserted": 1,
                    "derived": 0,
                    "projection": 0,
                },
                "kind": "aggregate",
                "packId": "urn:ref:atlas-test:pack:aggregate",
                "path": "atlas.nq",
                "rings": [],
                "sourceReleases": [],
                "transport": {
                    "byteLength": 100,
                    "compression": "none",
                    "digest": DIGEST,
                    "mediaType": "application/n-quads",
                },
            }
        ],
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }


def _zstd_manifest() -> dict[str, Any]:
    manifest = _manifest()
    source_pack_id = "urn:ref:atlas-test:pack:source:00"
    manifest["packs"] = [
        {
            "content": {
                "byteLength": 1_000,
                "digest": DIGEST,
                "mediaType": "application/n-quads",
                "quadCount": 10,
            },
            "dependencies": [],
            "graphCounts": {
                "asserted": 10,
                "derived": 0,
                "projection": 0,
            },
            "kind": "sourceRelease",
            "packId": source_pack_id,
            "partition": {
                "prefix": "00",
                "strategy": "sha256-subject-iri-prefix",
            },
            "path": "packs/source/00.nq.zst",
            "rings": ["subject"],
            "sourceReleases": ["urn:ref:atlas-test:source-release:1"],
            "transport": {
                "byteLength": 200,
                "compression": "zstd",
                "digest": DIGEST,
                "mediaType": "application/zstd",
            },
        },
        {
            "content": {
                "byteLength": 500,
                "digest": DIGEST,
                "mediaType": "application/n-quads",
                "quadCount": 5,
            },
            "dependencies": [source_pack_id],
            "graphCounts": {
                "asserted": 0,
                "derived": 0,
                "projection": 5,
            },
            "inputAssertedDigest": DIGEST,
            "kind": "view",
            "packId": "urn:ref:atlas-test:pack:projection",
            "path": "views/projection.nq.zst",
            "rings": ["subject"],
            "sourceReleases": [],
            "transport": {
                "byteLength": 100,
                "compression": "zstd",
                "digest": DIGEST,
                "mediaType": "application/zstd",
            },
        },
    ]
    manifest["graphs"][0]["packCount"] = 1
    manifest["graphs"][0]["quadCount"] = 10
    manifest["graphs"][1]["packCount"] = 1
    manifest["graphs"][1]["quadCount"] = 5
    return manifest


def _errors(manifest: dict[str, Any]) -> list[Any]:
    return list(_validator().iter_errors(manifest))


def test_one_uncompressed_aggregate_pack_is_valid() -> None:
    assert _errors(_manifest()) == []


def test_zstd_source_and_optional_projection_packs_are_valid() -> None:
    assert _errors(_zstd_manifest()) == []


def test_view_pack_cannot_carry_authoritative_quads_or_omit_its_input_pin() -> None:
    manifest = _zstd_manifest()
    manifest["packs"][1]["graphCounts"]["asserted"] = 1
    del manifest["packs"][1]["inputAssertedDigest"]

    assert _errors(manifest)


def test_source_release_pack_has_one_release_and_zstd_path() -> None:
    manifest = _zstd_manifest()
    source_pack = manifest["packs"][0]
    source_pack["sourceReleases"].append("urn:ref:atlas-test:source-release:2")
    source_pack["path"] = "packs/source/00.nq"

    assert _errors(manifest)


def test_manifest_and_pack_records_are_closed() -> None:
    manifest = copy.deepcopy(_manifest())
    manifest["packs"][0]["authority"] = "authoritative"

    assert _errors(manifest)


def test_pack_path_cannot_escape_the_distribution() -> None:
    manifest = _manifest()
    manifest["packs"][0]["path"] = "packs/../atlas.nq"

    assert _errors(manifest)


def test_empty_graph_role_cannot_claim_a_pack() -> None:
    manifest = _manifest()
    manifest["graphs"][1]["packCount"] = 1

    assert _errors(manifest)

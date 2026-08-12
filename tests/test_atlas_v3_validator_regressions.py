from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sys
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from random import Random
from typing import Any

import pytest
import rdflib
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SH, SKOS, XSD

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.0"
VALID_DISTRIBUTION = BINDING_ROOT / "fixtures" / "valid" / "all-resource-profiles"
ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
RKAF = Namespace("https://rulespec.org/ns/v1#")
PROV = Namespace("http://www.w3.org/ns/prov#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import build_fixtures as atlas_fixtures
import validate as atlas_validate


def test_validator_status_reporter_is_rate_limited_and_quiet_is_supported() -> None:
    ticks = iter((20.0, 20.0, 21.0, 36.0, 37.0))
    stream = io.StringIO()
    reporter = atlas_validate._StatusReporter(
        enabled=True,
        stream=stream,
        interval_seconds=15.0,
        clock=lambda: next(ticks),
    )

    reporter.phase("load")
    reporter.progress("compact", 1, 3, current="packs/one")
    reporter.progress("compact", 2, 3, current="packs/two")
    reporter.progress("compact", 3, 3, current="packs/three")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert lines[0] == 'atlas-validate elapsed=0.0s phase="load"'
    assert "progress=1/3" not in stream.getvalue()
    assert 'progress=2/3 current="packs/two"' in lines[1]
    assert 'progress=3/3 current="packs/three"' in lines[2]
    assert atlas_validate._parser().parse_args(["--quiet"]).quiet is True


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_independent_compact_reader_replays_all_authenticated_receipts(
    tmp_path: Path,
) -> None:
    from refspec.atlas.compact_pack import CompactPackHeader, build_compact_record_pack

    artifact = build_compact_record_pack(
        CompactPackHeader(
            role="Resource",
            path="packs/compact/source/resource.jsonl.zst",
        ),
        [
            {
                "contentDigest": _sha256(b"resource-rdf-facts"),
                "id": "urn:ref:atlas-test:resource:one",
                "release": "urn:ref:atlas-test:release:one",
                "resourceProfile": "conceptScheme",
                "scheme": "urn:ref:atlas-test:scheme:one",
                "semanticRing": "subject",
                "sourceRecord": "urn:ref:atlas-test:source-record:one",
            }
        ],
    )
    target = tmp_path / artifact.inventory.path
    target.parent.mkdir(parents=True)
    target.write_bytes(artifact.transport)

    observed = atlas_validate._read_compact_pack(
        tmp_path,
        artifact.inventory.to_dict(),
    )

    assert observed.rows == artifact.rows
    assert observed.full_summary == artifact.global_invariant_summary

    streamed: list[Mapping[str, Any]] = []
    streamed_observed = atlas_validate._read_compact_pack(
        tmp_path,
        artifact.inventory.to_dict(),
        retain_rows=False,
        row_consumer=streamed.append,
    )

    assert streamed_observed.rows == ()
    assert tuple(streamed) == artifact.rows
    assert streamed_observed.full_summary == artifact.global_invariant_summary


@pytest.mark.parametrize(
    ("record_count", "expected"),
    (
        (0, frozenset()),
        (1, frozenset({0})),
        (3, frozenset({0, 1, 2})),
        (100, frozenset({0, 24, 49, 74, 99})),
    ),
)
def test_compact_rdf_sample_is_bounded_stable_and_spread_across_each_pack(
    record_count: int,
    expected: frozenset[int],
) -> None:
    assert atlas_validate._compact_sample_indices(record_count) == expected


@pytest.mark.parametrize(
    ("role", "filename", "row"),
    (
        (
            "Statement",
            "statement",
            {
                "assertedAt": "2026-08-06T00:00:00+00:00",
                "assertionIdentityDigest": "sha256:" + "1" * 64,
                "id": "urn:ref:atlas-test:statement:new",
                "object": "urn:ref:atlas-test:resource:two",
                "policy": "urn:ref:atlas-test:policy:one",
                "predicate": str(SKOS.related),
                "semanticRing": "subject",
                "sourceRelease": "urn:ref:atlas-test:release:one",
                "statementType": "NativeRelationAssertion",
                "subject": "urn:ref:atlas-test:resource:one",
                "supersedesAssertion": "urn:ref:atlas-test:statement:old",
                "targetRelease": "urn:ref:atlas-test:release:one",
            },
        ),
        (
            "LifecycleEvent",
            "lifecycle-event",
            {
                "effectiveDate": "2026-08-06T00:00:00+00:00",
                "appliesTo": "urn:ref:atlas-test:resource:one",
                "lifecycleEventKind": "urn:ref:atlas-test:event-type:retired",
                "fromRelease": "urn:ref:atlas-test:release:one",
                "id": "urn:ref:atlas-test:lifecycle-event:one",
                "sourceRecords": [
                    "urn:ref:atlas-test:source-record:one",
                    "urn:ref:atlas-test:source-record:two",
                ],
                "toRelease": "urn:ref:atlas-test:release:two",
            },
        ),
    ),
)
def test_independent_compact_reader_supports_complete_lossless_roles(
    tmp_path: Path,
    role: str,
    filename: str,
    row: dict[str, Any],
) -> None:
    from refspec.atlas.compact_pack import CompactPackHeader, build_compact_record_pack

    artifact = build_compact_record_pack(
        CompactPackHeader(
            role=role,
            path=f"packs/compact/source/{filename}.jsonl.zst",
        ),
        [row],
    )
    target = tmp_path / artifact.inventory.path
    target.parent.mkdir(parents=True)
    target.write_bytes(artifact.transport)

    observed = atlas_validate._read_compact_pack(
        tmp_path,
        artifact.inventory.to_dict(),
    )

    assert observed.rows == artifact.rows
    assert observed.full_summary == artifact.global_invariant_summary


@pytest.mark.parametrize(
    ("role", "row", "expected"),
    (
        (
            "Statement",
            {
                "id": "urn:statement:new",
                "subject": "urn:resource:one",
                "object": "urn:resource:two",
                "sourceRelease": "urn:release:one",
                "targetRelease": "urn:release:two",
                "supersedesAssertion": "urn:statement:old",
            },
            {
                "urn:resource:one",
                "urn:resource:two",
                "urn:release:one",
                "urn:release:two",
                "urn:statement:old",
            },
        ),
        (
            "LifecycleEvent",
            {
                "id": "urn:event:one",
                "appliesTo": "urn:resource:one",
                "fromRelease": "urn:release:one",
                "toRelease": "urn:release:two",
                "sourceRecords": ["urn:record:one", "urn:record:two"],
            },
            {
                "urn:resource:one",
                "urn:release:one",
                "urn:release:two",
                "urn:record:one",
                "urn:record:two",
            },
        ),
    ),
)
def test_compact_direct_dependencies_include_every_replay_prerequisite(
    role: str,
    row: Mapping[str, Any],
    expected: set[str],
) -> None:
    assert atlas_validate._compact_direct_dependency_subjects(role, row) == expected


def test_compact_size_gate_rejects_aggregate_role_count_drift(
    tmp_path: Path,
) -> None:
    asserted = Graph()
    asserted.add((URIRef("urn:resource:one"), RDF.type, ATLAS.AtlasResource))
    construction_summary = {
        "compactPacks": [
            {
                "content": {"recordCount": 2},
                "path": "packs/compact/source/resource.jsonl.zst",
                "role": "Resource",
            }
        ],
        "releases": [
            {
                "atlasRelease": "urn:release:one",
                "compactPackPaths": ["packs/compact/source/resource.jsonl.zst"],
                "key": "source",
                "sourceRelease": "urn:source-release:one",
            }
        ],
    }

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_compact_shape_size_and_rdf_sample(
            tmp_path,
            asserted,
            construction_summary,
        )

    assert raised.value.code == "construction.compact"
    assert "logical record counts differ" in raised.value.detail


def test_construction_reused_input_paths_require_one_global_identity() -> None:
    first = {
        "key": "first",
        "inputs": [
            {
                "byteLength": 4,
                "path": "cache/shared.json",
                "role": "source",
                "sha256": _sha256(b"same"),
                "sourceIri": "urn:source:shared",
            }
        ],
    }
    second = {
        "key": "second",
        "inputs": [
            {
                **first["inputs"][0],
                "sha256": _sha256(b"different"),
            }
        ],
    }

    assert atlas_validate._check_construction_input_path_identities([first]) == [
        {
            "byteLength": 4,
            "path": "cache/shared.json",
            "sha256": _sha256(b"same"),
        }
    ]

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_construction_input_path_identities([first, second])

    assert raised.value.code == "construction.release"
    assert "conflicting pinned identities" in raised.value.detail


def test_semantic_first_issue_precedes_compact_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def reject_semantics(*_args: object, **_kwargs: object) -> dict[str, Any]:
        calls.append("semantic")
        raise atlas_validate.AtlasValidationError(
            "semantic.first-issue",
            "intended semantic fixture failure",
        )

    def reject_compact(*_args: object, **_kwargs: object) -> None:
        calls.append("compact")
        raise AssertionError("compact checks must not mask a semantic first issue")

    monkeypatch.setattr(atlas_validate, "_validate_semantic_graphs", reject_semantics)
    monkeypatch.setattr(
        atlas_validate,
        "_check_compact_shape_size_and_rdf_sample",
        reject_compact,
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_semantics_then_compact_checks(
            tmp_path,
            {},
            {},
            {},
            {"asserted": Graph()},
            {},
            member_digests={},
        )

    assert raised.value.code == "semantic.first-issue"
    assert calls == ["semantic"]


def test_compact_shape_size_and_sample_run_after_successful_semantic_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def accept_semantics(*_args: object, **_kwargs: object) -> dict[str, Any]:
        calls.append("semantic")
        return {"status": "passed"}

    def reject_compact(*_args: object, **_kwargs: object) -> None:
        calls.append("compact")
        raise atlas_validate.AtlasValidationError(
            "construction.sample",
            "intended construction fixture failure",
        )

    monkeypatch.setattr(atlas_validate, "_validate_semantic_graphs", accept_semantics)
    monkeypatch.setattr(
        atlas_validate,
        "_check_compact_shape_size_and_rdf_sample",
        reject_compact,
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_semantics_then_compact_checks(
            tmp_path,
            {},
            {},
            {},
            {"asserted": Graph()},
            {},
            member_digests={},
        )

    assert raised.value.code == "construction.sample"
    assert calls == ["semantic", "compact"]


@pytest.mark.parametrize(
    ("receipt", "expected_code"),
    (
        ("transport", "pack.transport"),
        ("content", "construction.compact"),
        ("logical", "construction.compact"),
        ("summary", "construction.compact"),
    ),
)
def test_independent_compact_reader_rejects_each_tampered_receipt(
    tmp_path: Path,
    receipt: str,
    expected_code: str,
) -> None:
    from refspec.atlas.compact_pack import CompactPackHeader, build_compact_record_pack

    artifact = build_compact_record_pack(
        CompactPackHeader(
            role="Identifier",
            path="packs/compact/source/identifier.jsonl.zst",
        ),
        [
            {
                "id": "urn:ref:atlas-test:identifier:one",
                "identifierScheme": "urn:ref:atlas-test:identifier-scheme:one",
                "identifierValue": "ONE",
                "identifies": "urn:ref:atlas-test:resource:one",
                "sourceRecord": "urn:ref:atlas-test:source-record:one",
            }
        ],
    )
    target = tmp_path / artifact.inventory.path
    target.parent.mkdir(parents=True)
    target.write_bytes(artifact.transport)
    descriptor = artifact.inventory.to_dict()
    if receipt == "logical":
        descriptor["logicalRowsDigest"] = "sha256:" + "0" * 64
    elif receipt == "summary":
        descriptor["globalInvariantSummary"]["digest"] = "sha256:" + "0" * 64
    else:
        descriptor[receipt]["digest"] = "sha256:" + "0" * 64

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._read_compact_pack(tmp_path, descriptor)

    assert raised.value.code == expected_code


def test_shacl_data_view_truth_does_not_count_the_complete_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph(store="SimpleMemory")
    graph.add((URIRef("urn:s"), URIRef("urn:p"), URIRef("urn:o")))
    view = atlas_validate._ShaclDataView([graph])

    def reject_full_count(_graph: Graph) -> int:
        raise AssertionError("SHACL truth testing must not count every triple")

    monkeypatch.setattr(Graph, "__len__", reject_full_count)

    assert bool(view)
    assert bool(view)
    assert not atlas_validate._ShaclDataView([Graph(store="SimpleMemory")])


def _reference_hierarchy_connected_pairs(
    hierarchy: Mapping[URIRef, URIRef | set[URIRef]],
    pairs: set[tuple[URIRef, URIRef]],
) -> set[tuple[URIRef, URIRef]]:
    """Small positive-path reference used only for differential tests."""

    connected: set[tuple[URIRef, URIRef]] = set()
    for raw_pair in pairs:
        pair = atlas_validate._canonical_pair(*raw_pair)
        for source, target in (pair, (pair[1], pair[0])):
            frontier = [source]
            visited: set[URIRef] = set()
            found = False
            while frontier and not found:
                node = frontier.pop()
                targets = hierarchy.get(node)
                if targets is None:
                    continue
                broader_nodes = targets if isinstance(targets, set) else (targets,)
                for broader in broader_nodes:
                    if broader == target:
                        found = True
                        break
                    if broader not in visited:
                        visited.add(broader)
                        frontier.append(broader)
            if found:
                connected.add(pair)
                break
    return connected


@pytest.mark.parametrize(
    ("items", "expected"),
    (
        ([{"a": [1, True], "b": "x"}, {"b": "x", "a": [1, True]}], False),
        ([{"a": [1, True]}, {"a": [1, False]}], True),
        ([True, 1], True),
        ([1, 1.0], False),
        ([["a", "b"], ["b", "a"]], True),
        ([None, None], False),
    ),
)
def test_linear_unique_items_preserves_json_schema_equality(
    items: list[Any],
    expected: bool,
) -> None:
    assert atlas_validate._json_items_are_unique(items) is expected


def test_linear_unique_items_indexes_each_distinct_object_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "atlasResources": [f"urn:ref:atlas-test:resource:{index}"],
            "sourceRecord": f"urn:ref:atlas-test:record:{index}",
            "status": "represented",
        }
        for index in range(10_000)
    ]
    original = atlas_validate._json_equality_fingerprint
    calls = 0

    def counted(value: Any) -> bytes:
        nonlocal calls
        calls += 1
        return original(value)

    def reject_pairwise_comparison(_first: Any, _second: Any) -> bool:
        raise AssertionError("distinct uniqueItems must not use pairwise equality")

    monkeypatch.setattr(atlas_validate, "_json_equality_fingerprint", counted)
    monkeypatch.setattr(atlas_validate.jsonschema_utils, "equal", reject_pairwise_comparison)

    assert atlas_validate._json_items_are_unique(rows)
    assert calls == len(rows)


def test_linear_unique_items_checks_exact_values_after_fingerprint_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        atlas_validate,
        "_json_equality_fingerprint",
        lambda _value: b"one-forced-fingerprint",
    )

    assert atlas_validate._json_items_are_unique([{"value": 1}, {"value": 2}])
    assert not atlas_validate._json_items_are_unique(
        [{"value": 1}, {"value": 2}, {"value": 1}]
    )


def test_source_accounting_duplicate_disposition_keeps_json_schema_error() -> None:
    disposition = {
        "atlasResources": ["urn:ref:atlas-test:resource"],
        "sourceRecord": "urn:ref:atlas-test:record",
        "status": "represented",
    }
    accounting = {
        "distributionId": "urn:ref:atlas-test:distribution",
        "inputs": [
            {
                "declaredMemberCount": 2,
                "dispositions": [disposition, dict(disposition)],
                "membershipMode": "complete",
                "sourceRelease": "urn:ref:atlas-test:source-release",
            }
        ],
        "totals": {
            "excluded": 0,
            "represented": 2,
            "sourceRecords": 2,
            "sourceReleases": 1,
            "unresolved": 0,
        },
        "type": "AtlasSourceAccounting",
        "version": "3.0",
    }
    schemas, registry = atlas_validate._schema_registry()

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_json_schema(
            accounting,
            "sourceAccounting",
            schemas=schemas,
            registry=registry,
            label="source accounting",
        )

    assert raised.value.code == "json.schema"
    assert "$.inputs[0].dispositions" in raised.value.detail
    assert "has non-unique elements" in raised.value.detail


@pytest.mark.parametrize(
    ("disposition", "valid"),
    (
        (
            {
                "atlasResources": ["urn:ref:atlas-test:resource"],
                "sourceRecord": "urn:ref:atlas-test:record",
                "status": "represented",
            },
            True,
        ),
        (
            {
                "atlasAssertions": ["urn:ref:atlas-test:assertion"],
                "sourceRecord": "urn:ref:atlas-test:record",
                "status": "represented",
            },
            True,
        ),
        (
            {
                "sourceRecord": "urn:ref:atlas-test:record",
                "status": "represented",
            },
            False,
        ),
        (
            {
                "reason": "Not represented.",
                "sourceRecord": "urn:ref:atlas-test:record",
                "status": "excluded",
            },
            True,
        ),
        (
            {
                "atlasResources": [],
                "reason": "Not represented.",
                "sourceRecord": "urn:ref:atlas-test:record",
                "status": "excluded",
            },
            False,
        ),
        (
            {
                "atlasAssertions": [],
                "reason": "Not resolved.",
                "sourceRecord": "urn:ref:atlas-test:record",
                "status": "unresolved",
            },
            False,
        ),
    ),
)
def test_source_accounting_disposition_targets_are_status_specific(
    disposition: dict[str, Any],
    valid: bool,
) -> None:
    status = disposition["status"]
    accounting = {
        "distributionId": "urn:ref:atlas-test:distribution",
        "inputs": [
            {
                "declaredMemberCount": 1,
                "dispositions": [disposition],
                "membershipMode": "complete",
                "sourceRelease": "urn:ref:atlas-test:source-release",
            }
        ],
        "totals": {
            "excluded": int(status == "excluded"),
            "represented": int(status == "represented"),
            "sourceRecords": 1,
            "sourceReleases": 1,
            "unresolved": int(status == "unresolved"),
        },
        "type": "AtlasSourceAccounting",
        "version": "3.0",
    }
    schemas, registry = atlas_validate._schema_registry()

    if valid:
        atlas_validate._validate_json_schema(
            accounting,
            "sourceAccounting",
            schemas=schemas,
            registry=registry,
            label="source accounting",
        )
    else:
        with pytest.raises(atlas_validate.AtlasValidationError) as raised:
            atlas_validate._validate_json_schema(
                accounting,
                "sourceAccounting",
                schemas=schemas,
                registry=registry,
                label="source accounting",
            )
        assert raised.value.code == "json.schema"


def _write_packed_distribution(
    root: Path,
    *,
    compression: str = "none",
    include_projection: bool = True,
    include_derived: bool = True,
) -> Path:
    """Repack the broad valid fixture using the current manifest at test time."""

    if (VALID_DISTRIBUTION / atlas_validate.CONSTRUCTION_SUMMARY_FILE).exists():
        shutil.copytree(VALID_DISTRIBUTION, root)
        manifest_path = root / "atlas-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        graph_ids = {row["role"]: row["id"] for row in manifest["graphs"]}
        suffixes = {
            role: f" <{graph_id}> .\n".encode()
            for role, graph_id in graph_ids.items()
        }
        enabled_roles = {"asserted"}
        if include_projection:
            enabled_roles.add("projection")
        if include_derived:
            enabled_roles.add("derived")

        retained: list[dict[str, Any]] = []
        id_map: dict[str, str] = {}
        path_map: dict[str, str] = {}
        for raw_pack in manifest["packs"]:
            pack = dict(raw_pack)
            pack["content"] = dict(pack["content"])
            pack["transport"] = dict(pack["transport"])
            pack["graphCounts"] = dict(pack["graphCounts"])
            original_relative = pack["path"]
            pack_path = root / original_relative
            stored = pack_path.read_bytes()
            content = (
                atlas_validate.zstd.decompress(stored)
                if pack["transport"]["compression"] == "zstd"
                else stored
            )
            lines = content.splitlines(keepends=True)
            filtered = b"".join(
                line
                for line in lines
                if any(
                    role in enabled_roles and line.endswith(suffix)
                    for role, suffix in suffixes.items()
                )
            )
            if not filtered:
                pack_path.unlink()
                continue
            content_digest = _sha256(filtered)
            new_pack_id = (
                "urn:ref:atlas:pack:"
                + content_digest.removeprefix("sha256:")
            )
            id_map[pack["packId"]] = new_pack_id
            packed = (
                atlas_validate.zstd.compress(filtered)
                if compression == "zstd"
                else filtered
            )
            relative = (
                original_relative
                if compression == "none" or original_relative.endswith(".zst")
                else original_relative + ".zst"
            )
            target_path = root / relative
            target_path.write_bytes(packed)
            if target_path != pack_path:
                pack_path.unlink()
            path_map[original_relative] = relative
            graph_counts = {
                role: sum(line.endswith(suffix) for line in filtered.splitlines(keepends=True))
                for role, suffix in suffixes.items()
            }
            pack["packId"] = new_pack_id
            pack["path"] = relative
            pack["content"].update(
                {
                    "byteLength": len(filtered),
                    "digest": content_digest,
                    "quadCount": sum(graph_counts.values()),
                }
            )
            pack["graphCounts"] = graph_counts
            pack["transport"].update(
                {
                    "byteLength": len(packed),
                    "compression": compression,
                    "digest": _sha256(packed),
                    "mediaType": (
                        "application/zstd"
                        if compression == "zstd"
                        else "application/n-quads"
                    ),
                }
            )
            retained.append(pack)
        for pack in retained:
            pack["dependencies"] = sorted(
                id_map[dependency]
                for dependency in pack["dependencies"]
                if dependency in id_map
            )
        retained.sort(key=lambda pack: pack["packId"])
        manifest["packs"] = retained
        asserted_inventory = atlas_validate._graph_inventory_digest(
            retained, "asserted"
        )
        for row in manifest["graphs"]:
            role = row["role"]
            role_packs = [pack for pack in retained if pack["graphCounts"][role]]
            row.update(
                {
                    "inventoryDigest": atlas_validate._graph_inventory_digest(
                        retained, role
                    ),
                    "packCount": len(role_packs),
                    "quadCount": sum(
                        pack["graphCounts"][role] for pack in role_packs
                    ),
                }
            )
        for pack in retained:
            if pack["graphCounts"]["projection"] or pack["graphCounts"]["derived"]:
                pack["inputAssertedDigest"] = asserted_inventory
        if not include_projection:
            manifest["counts"]["projectedRelations"] = 0
        if not include_derived:
            manifest["counts"]["derivedRelations"] = 0

        construction_path = root / atlas_validate.CONSTRUCTION_SUMMARY_FILE
        construction = json.loads(construction_path.read_text(encoding="utf-8"))
        construction["assertedInventoryDigest"] = asserted_inventory
        construction["catalog"]["rdfPack"]["path"] = path_map[
            construction["catalog"]["rdfPack"]["path"]
        ]
        for release in construction["releases"]:
            for receipt in release["rdfPacks"]:
                receipt["path"] = path_map[receipt["path"]]
        construction["releaseInventoryDigest"] = atlas_validate._construction_digest(
            construction["releases"]
        )
        construction["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
            {
                key: value
                for key, value in construction.items()
                if key != "canonicalPayloadDigest"
            },
            terminal_lf=False,
        )
        construction_bytes = atlas_validate.canonical_json_bytes(construction)
        construction_path.write_bytes(construction_bytes)
        construction_digest = _sha256(construction_bytes)

        proof_path = root / atlas_validate.PRODUCER_VALIDATION_FILE
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["assertedInventoryDigest"] = asserted_inventory
        proof["counts"] = dict(manifest["counts"])
        proof["constructionSummary"].update(
            {
                "digest": construction_digest,
                "releaseInventoryDigest": construction["releaseInventoryDigest"],
            }
        )
        proof_bytes = atlas_validate.canonical_json_bytes(proof)
        proof_path.write_bytes(proof_bytes)
        proof_digest = _sha256(proof_bytes)

        acceptance_path = root / "atlas-acceptance.json"
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        acceptance["inputs"]["atlasDigest"] = asserted_inventory
        acceptance["inputs"]["producerValidationDigest"] = proof_digest
        for gate in acceptance["gates"]:
            gate["evidenceDigest"] = atlas_validate.acceptance_gate_evidence_digest(
                gate["name"],
                inputs=acceptance["inputs"],
                validator=acceptance["validator"],
            )
        acceptance_bytes = atlas_validate.canonical_json_bytes(acceptance)
        acceptance_path.write_bytes(acceptance_bytes)
        for member in manifest["members"]:
            if member["role"] == "acceptance":
                member["byteLength"] = len(acceptance_bytes)
                member["digest"] = _sha256(acceptance_bytes)
            elif member["role"] == "producerValidation":
                member["byteLength"] = len(proof_bytes)
                member["digest"] = proof_digest
            elif member["role"] == "constructionSummary":
                member["byteLength"] = len(construction_bytes)
                member["digest"] = construction_digest
        manifest["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
            {
                key: value
                for key, value in manifest.items()
                if key != "canonicalPayloadDigest"
            },
            terminal_lf=False,
        )
        manifest_path.write_bytes(atlas_validate.canonical_json_bytes(manifest))
        return root
    raise AssertionError(f"{VALID_DISTRIBUTION} carries no {atlas_validate.CONSTRUCTION_SUMMARY_FILE} to repack")

def _write_distribution_json(
    distribution: Path,
    manifest: dict[str, Any],
    acceptance: dict[str, Any],
) -> None:
    for gate in acceptance["gates"]:
        gate["evidenceDigest"] = atlas_validate.acceptance_gate_evidence_digest(
            gate["name"],
            inputs=acceptance["inputs"],
            validator=acceptance["validator"],
        )
    acceptance_bytes = atlas_validate.canonical_json_bytes(acceptance)
    (distribution / "atlas-acceptance.json").write_bytes(acceptance_bytes)
    acceptance_member = next(
        member for member in manifest["members"] if member["role"] == "acceptance"
    )
    acceptance_member["byteLength"] = len(acceptance_bytes)
    acceptance_member["digest"] = _sha256(acceptance_bytes)
    manifest["canonicalPayloadDigest"] = atlas_validate.canonical_sha256(
        {
            key: value
            for key, value in manifest.items()
            if key != "canonicalPayloadDigest"
        },
        terminal_lf=False,
    )
    (distribution / "atlas-manifest.json").write_bytes(
        atlas_validate.canonical_json_bytes(manifest)
    )


def _install_producer_validation(
    distribution: Path,
    **overrides: Any,
) -> dict[str, Any]:
    manifest = json.loads(
        (distribution / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    acceptance = json.loads(
        (distribution / "atlas-acceptance.json").read_text(encoding="utf-8")
    )
    asserted_inventory_digest = next(
        row["inventoryDigest"]
        for row in manifest["graphs"]
        if row["role"] == "asserted"
    )
    accounting_digest = next(
        member["digest"]
        for member in manifest["members"]
        if member["role"] == "sourceAccounting"
    )
    accounting = json.loads(
        (distribution / "atlas-source-accounting.json").read_text(encoding="utf-8")
    )
    construction = json.loads(
        (distribution / atlas_validate.CONSTRUCTION_SUMMARY_FILE).read_text(
            encoding="utf-8"
        )
    )
    construction_digest = _sha256(
        (distribution / atlas_validate.CONSTRUCTION_SUMMARY_FILE).read_bytes()
    )
    proof: dict[str, Any] = {
        "assertedInventoryDigest": asserted_inventory_digest,
        "binding": dict(manifest["binding"]),
        "checks": ["unit-test compiled producer proof"],
        "constructionSummary": {
            "compactPackCount": construction["compactPackCount"],
            "compactPackInventoryDigest": construction[
                "compactPackInventoryDigest"
            ],
            "digest": construction_digest,
            "path": atlas_validate.CONSTRUCTION_SUMMARY_FILE,
            "profile": "atlas-3-authenticated-construction-summary-v1",
            "releaseCount": construction["releaseCount"],
            "releaseInventoryDigest": construction["releaseInventoryDigest"],
        },
        "constructorProfile": "atlas-3-source-and-evidence-backed-mapping-compiled-shacl-v1",
        "counts": dict(manifest["counts"]),
        "implementationDigest": _sha256(b"unit-test-producer-implementation"),
        "mode": "compiledSourceAndEvidenceBackedMappingProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "sourceAccountingDigest": accounting_digest,
        "sourceReleaseCount": accounting["totals"]["sourceReleases"],
        "status": "passed",
        "type": "AtlasProducerValidation",
        "version": "3.0",
    }
    proof.update(overrides)
    proof_bytes = atlas_validate.canonical_json_bytes(proof)
    proof_path = distribution / atlas_validate.PRODUCER_VALIDATION_FILE
    proof_path.write_bytes(proof_bytes)
    proof_digest = _sha256(proof_bytes)
    proof_member = next(
        member
        for member in manifest["members"]
        if member["role"] == "producerValidation"
    )
    proof_member.update(
        {
            "byteLength": len(proof_bytes),
            "digest": proof_digest,
            "mediaType": "application/json",
            "path": atlas_validate.PRODUCER_VALIDATION_FILE,
        }
    )
    acceptance["inputs"]["producerValidationDigest"] = proof_digest
    _write_distribution_json(distribution, manifest, acceptance)
    return proof


def _load_valid_graphs() -> tuple[Dataset, dict[str, Graph], Mapping[str, Any]]:
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    dataset, graphs = atlas_validate._parse_packed_dataset(
        VALID_DISTRIBUTION, manifest, graph_ids
    )
    return dataset, graphs, manifest


def _replace_object(graph: Graph, subject: URIRef, predicate: URIRef, replacement: URIRef) -> None:
    graph.remove((subject, predicate, None))
    graph.add((subject, predicate, replacement))


def _assert_shacl_rejects(graphs: Mapping[str, Graph], component: str) -> None:
    ontology, shapes = atlas_validate._parse_binding_graphs()
    with pytest.raises(atlas_validate.AtlasValidationError, match=component):
        atlas_validate._run_shacl(graphs, ontology, shapes)


def test_meta_conformance_is_proven_once_per_process_and_never_cached_as_a_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shape-graph proof is derived once, but a bad shape graph still fails.

    `_prove_shape_graph_conforms` is memoized because it asks about two
    immutable binding files rather than about the distribution under
    validation. This pins both halves: repeated validation must not re-derive
    it, and memoization must not be able to turn a non-conforming shape graph
    into a pass.
    """

    _, graphs, _ = _load_valid_graphs()
    ontology, shapes = atlas_validate._parse_binding_graphs()
    derivations: list[tuple[str, str]] = []
    underlying = atlas_validate._prove_shape_graph_conforms.__wrapped__

    def counted(ontology_digest: str, shapes_digest: str) -> None:
        derivations.append((ontology_digest, shapes_digest))
        return underlying(ontology_digest, shapes_digest)

    monkeypatch.setattr(
        atlas_validate,
        "_prove_shape_graph_conforms",
        lru_cache(maxsize=1)(counted),
    )

    atlas_validate._run_shacl(graphs, ontology, shapes)
    atlas_validate._run_shacl(graphs, ontology, shapes)
    assert len(derivations) == 1, "the binding proof must not be re-derived per distribution"

    # A shape graph that is not well-formed SHACL is still refused, and refused
    # again on every subsequent call -- lru_cache stores nothing for a raising
    # call, so the failure can never be memoized into a pass.
    broken = tmp_path / "atlas.shacl.ttl"
    broken.write_bytes(
        atlas_validate.SHAPES_PATH.read_bytes()
        + b'\n<urn:test:broken> a <http://www.w3.org/ns/shacl#NodeShape> ;\n'
        b'    <http://www.w3.org/ns/shacl#minCount> "not-an-integer" .\n'
    )
    monkeypatch.setattr(atlas_validate, "SHAPES_PATH", broken)
    for _ in range(2):
        with pytest.raises(atlas_validate.AtlasValidationError, match="shacl.meta"):
            atlas_validate._run_shacl(graphs, ontology, shapes)
    assert len(derivations) == 3, "a refused shape graph must be re-derived, never cached"


def _fresh_asserted_graph_without_assertions() -> Graph:
    asserted = atlas_fixtures._base_fixture().asserted
    node_types = (
        ATLAS.RelationAssertion,
        ATLAS.CrossRingRelationAssertion,
        ATLAS.MappingAssertion,
        ATLAS.NativeRelationAssertion,
        ATLAS.SourceAssignment,
        RKAF.EvidenceBinding,
    )
    nodes = {
        node
        for node_type in node_types
        for node in asserted.subjects(RDF.type, node_type)
    }
    for node in nodes:
        asserted.remove((node, None, None))
    return asserted


def _resource_rows(asserted: Graph, ring: URIRef) -> list[tuple[URIRef, URIRef, URIRef]]:
    rows: list[tuple[URIRef, URIRef, URIRef]] = []
    for resource in asserted.subjects(ATLAS.semanticRing, ring):
        if (resource, RDF.type, ATLAS.AtlasResource) not in asserted:
            continue
        release = next(asserted.objects(resource, ATLAS.inRelease))
        source_record = next(asserted.objects(resource, ATLAS.sourceRecord))
        assert isinstance(resource, URIRef)
        assert isinstance(release, URIRef)
        assert isinstance(source_record, URIRef)
        rows.append((resource, release, source_record))
    return sorted(rows, key=lambda row: tuple(map(str, row)))


def _allowed_predicate(ring: URIRef, assertion_type: URIRef) -> URIRef:
    predicates = atlas_validate._relation_policies()[ring][assertion_type]
    return min(predicates, key=str)


def test_membership_mode_admits_only_the_three_rulespec_values() -> None:
    """Rulespec's #ReferenceResourceMembershipMode is a closed three-value set.

    atlas:completeMembership no longer exists, so the old value is now just
    another term outside the set -- which is the point: the shape rejects a
    parallel Atlas term as firmly as it rejects nonsense.
    """

    for replacement in (ATLAS.completeMembership, RKAF.partialCompleteMembership):
        _dataset, graphs, _ = _load_valid_graphs()
        asserted = graphs["asserted"]
        release = next(asserted.subjects(RDF.type, ATLAS.AtlasRelease))
        _replace_object(asserted, release, RKAF.membershipMode, replacement)
        _assert_shacl_rejects(graphs, "InConstraintComponent")


def test_an_enumerating_membership_mode_requires_at_least_one_member() -> None:
    _dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    release = next(asserted.subjects(RDF.type, ATLAS.AtlasRelease))
    asserted.remove((release, PROV.hadMember, None))

    _assert_shacl_rejects(graphs, "XoneConstraintComponent")


def test_membership_not_enumerated_forbids_enumerating_the_members() -> None:
    """Upstream's third mode is not "complete with the list omitted"."""

    _dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    release = next(asserted.subjects(RDF.type, ATLAS.AtlasRelease))
    _replace_object(
        asserted,
        release,
        RKAF.membershipMode,
        RKAF.membershipNotEnumerated,
    )
    assert list(asserted.objects(release, PROV.hadMember))

    _assert_shacl_rejects(graphs, "XoneConstraintComponent")


def test_core_shacl_still_rejects_an_assertion_without_evidence() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    # Deleting a binding that some other binding adopts diagnoses the dangling
    # adoptedEvidence reference first, which is a different failure. Pick the
    # first mapping binding nothing adopts, in sorted order so the choice does
    # not move when evidence IRIs change.
    adopted = set(asserted.objects(None, RKAF.basedOnAttestation))
    binding = next(
        candidate
        for mapping in sorted(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        for candidate in sorted(asserted.subjects(RKAF.bindsAssertion, mapping))
        if candidate not in adopted
    )
    asserted.remove((binding, None, None))

    _assert_shacl_rejects(graphs, "MinCountConstraintComponent")
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_evidence_bindings(asserted)
    assert raised.value.code == "dataset.evidence"
    assert "no immutable evidence binding" in raised.value.detail
    assert dataset.store is asserted.store


@pytest.mark.parametrize(
    ("mutation", "expected_detail"),
    (
        ("release-profile", "profile differs"),
        ("resource-scheme", "scheme differs"),
        ("resource-profile", "profile differs"),
        ("resource-ring", "ring differs"),
    ),
)
def test_release_reconciliation_and_core_paths_reject_cross_record_mismatches(
    mutation: str,
    expected_detail: str,
) -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource = next(asserted.subjects(RDF.type, ATLAS.SubjectConcept))
    release = next(asserted.objects(resource, ATLAS.inRelease))

    if mutation == "release-profile":
        current = next(asserted.objects(release, ATLAS.resourceProfile))
        replacement = next(
            profile
            for profile in (ATLAS.codeScheme, ATLAS.identifierScheme, ATLAS.structureScheme)
            if profile != current
        )
        _replace_object(asserted, release, ATLAS.resourceProfile, replacement)
    elif mutation == "resource-scheme":
        current = next(asserted.objects(resource, ATLAS.inScheme))
        replacement = next(
            scheme
            for scheme in asserted.subjects(RDF.type, ATLAS.ResourceScheme)
            if scheme != current
        )
        _replace_object(asserted, resource, ATLAS.inScheme, replacement)
    elif mutation == "resource-profile":
        current = next(asserted.objects(resource, ATLAS.resourceProfile))
        replacement = next(
            profile
            for profile in (ATLAS.codeScheme, ATLAS.identifierScheme, ATLAS.structureScheme)
            if profile != current
        )
        _replace_object(asserted, resource, ATLAS.resourceProfile, replacement)
    else:
        current = next(asserted.objects(resource, ATLAS.semanticRing))
        replacement = next(ring for ring in (ATLAS.subject, ATLAS.entity, ATLAS.value) if ring != current)
        _replace_object(asserted, resource, ATLAS.semanticRing, replacement)

    _assert_shacl_rejects(graphs, "EqualsConstraintComponent")
    with pytest.raises(atlas_validate.AtlasValidationError, match=expected_detail):
        atlas_validate._check_release_membership(asserted)
    assert dataset.store is asserted.store


def _resource_with_preferred_label(asserted: Graph) -> tuple[URIRef, URIRef]:
    resource = next(asserted.subjects(SKOSXL.prefLabel, None))
    label = next(asserted.objects(resource, SKOSXL.prefLabel))
    assert isinstance(resource, URIRef)
    assert isinstance(label, URIRef)
    return resource, label


def test_label_integrity_rejects_a_label_from_another_release() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource, label = _resource_with_preferred_label(asserted)
    release = next(asserted.objects(resource, ATLAS.inRelease))
    wrong_release = next(
        candidate
        for candidate in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
        if candidate != release
    )
    _replace_object(asserted, label, ATLAS.inRelease, wrong_release)

    with pytest.raises(atlas_validate.AtlasValidationError, match="release differs from its resource"):
        atlas_validate._check_label_integrity(asserted)
    assert dataset.store is asserted.store


def test_label_integrity_rejects_an_unshared_source_record() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource, label = _resource_with_preferred_label(asserted)
    resource_records = set(asserted.objects(resource, ATLAS.sourceRecord))
    wrong_record = next(
        record
        for record in asserted.subjects(RDF.type, ATLAS.SourceRecord)
        if record not in resource_records
    )
    _replace_object(asserted, label, ATLAS.sourceRecord, wrong_record)

    with pytest.raises(atlas_validate.AtlasValidationError, match="shares no SourceRecord"):
        atlas_validate._check_label_integrity(asserted)
    assert dataset.store is asserted.store


def test_label_integrity_rejects_equal_literals_in_distinct_roles() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource, preferred = _resource_with_preferred_label(asserted)
    alternate = URIRef("urn:ref:atlas-test:label:alternate-with-preferred-literal")
    literal = next(asserted.objects(preferred, SKOSXL.literalForm))
    release = next(asserted.objects(preferred, ATLAS.inRelease))
    source_record = next(asserted.objects(preferred, ATLAS.sourceRecord))
    assert isinstance(literal, Literal)

    asserted.add((resource, SKOSXL.altLabel, alternate))
    asserted.add((alternate, SKOSXL.literalForm, literal))
    asserted.add((alternate, ATLAS.inRelease, release))
    asserted.add((alternate, ATLAS.sourceRecord, source_record))

    with pytest.raises(atlas_validate.AtlasValidationError, match="reuses a label node or literal"):
        atlas_validate._check_label_integrity(asserted)
    assert dataset.store is asserted.store


@pytest.mark.parametrize(
    "assertion_type",
    (ATLAS.MappingAssertion, ATLAS.NativeRelationAssertion, ATLAS.SourceAssignment),
    ids=("mapping", "native", "source-assignment"),
)
@pytest.mark.parametrize("mismatch", ("ring", "release"))
def test_core_paths_reject_assertion_endpoint_ring_and_release_mismatches(
    assertion_type: URIRef,
    mismatch: str,
) -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, assertion_type))

    if mismatch == "ring":
        current = next(asserted.objects(assertion, ATLAS.semanticRing))
        replacement = next(
            ring
            for ring in (ATLAS.subject, ATLAS.entity, ATLAS.value, ATLAS.legalIdentity)
            if ring != current
        )
        _replace_object(asserted, assertion, ATLAS.semanticRing, replacement)
    else:
        current = next(asserted.objects(assertion, ATLAS.targetRelease))
        replacement = next(
            release
            for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
            if release != current
        )
        _replace_object(asserted, assertion, ATLAS.targetRelease, replacement)

    _assert_shacl_rejects(graphs, "EqualsConstraintComponent")
    assert dataset.store is asserted.store


@pytest.mark.parametrize(
    ("case", "expected_code", "expected_detail"),
    (
        ("mapping-ring", "dataset.release", "endpoint ring differs"),
        ("mapping-release", "dataset.release", "target release does not contain"),
        ("native-ring", "dataset.release", "endpoint ring differs"),
        ("assignment-ring", "dataset.assignment", "target ring differs"),
        ("assignment-release", "dataset.assignment", "target release does not contain"),
    ),
)
def test_python_assertion_backstops_reject_ring_and_release_mismatches(
    case: str,
    expected_code: str,
    expected_detail: str,
) -> None:
    asserted = _fresh_asserted_graph_without_assertions()

    if case == "mapping-ring":
        source, source_release, evidence_record = _resource_rows(asserted, ATLAS.subject)[0]
        target, target_release, _ = next(
            row
            for row in _resource_rows(asserted, ATLAS.subject)
            if row[1] != source_release
        )
        assertion_type = ATLAS.MappingAssertion
        ring = ATLAS.entity
    elif case == "mapping-release":
        source, source_release, evidence_record = _resource_rows(asserted, ATLAS.subject)[0]
        target, actual_target_release, _ = next(
            row
            for row in _resource_rows(asserted, ATLAS.subject)
            if row[1] != source_release
        )
        target_release = next(
            release
            for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
            if release not in {source_release, actual_target_release}
        )
        assertion_type = ATLAS.MappingAssertion
        ring = ATLAS.subject
    elif case == "native-ring":
        source_row, target_row = next(
            (left, right)
            for left in _resource_rows(asserted, ATLAS.value)
            for right in _resource_rows(asserted, ATLAS.value)
            if left[0] != right[0] and left[1] == right[1]
        )
        source, source_release, evidence_record = source_row
        target, target_release, _ = target_row
        assertion_type = ATLAS.NativeRelationAssertion
        ring = ATLAS.subject
    else:
        target, actual_target_release, source = _resource_rows(asserted, ATLAS.entity)[0]
        source_release = next(asserted.objects(source, ATLAS.inSourceRelease))
        evidence_record = source
        assertion_type = ATLAS.SourceAssignment
        if case == "assignment-ring":
            ring = ATLAS.subject
            target_release = actual_target_release
        else:
            ring = ATLAS.entity
            target_release = next(
                release
                for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
                if release != actual_target_release
            )

    assert isinstance(source_release, URIRef)
    assert isinstance(target_release, URIRef)
    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=assertion_type,
        ring=ring,
        subject=source,
        predicate=_allowed_predicate(ring, assertion_type),
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name=f"python-backstop-{case}",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_assertions(asserted)

    assert raised.value.code == expected_code
    assert expected_detail in raised.value.detail


def test_publisher_native_relation_may_cross_exact_releases_in_one_ring() -> None:
    asserted = _fresh_asserted_graph_without_assertions()
    predicate = SKOS.related
    source, source_release, evidence_record = _resource_rows(asserted, ATLAS.subject)[0]
    target, target_release, _ = next(
        row
        for row in _resource_rows(asserted, ATLAS.subject)
        if row[1] != source_release
    )
    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=ATLAS.NativeRelationAssertion,
        ring=ATLAS.subject,
        subject=source,
        predicate=predicate,
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name="publisher-native-cross-release",
    )

    supported = atlas_validate._validate_assertions(asserted)

    assert (source, predicate, target) in supported


@pytest.mark.parametrize(
    ("case", "expected_detail"),
    (
        ("source-ring", "source endpoint ring differs"),
        ("target-release", "target release does not contain"),
    ),
)
def test_python_cross_ring_backstops_reject_endpoint_mismatches(
    case: str,
    expected_detail: str,
) -> None:
    asserted = _fresh_asserted_graph_without_assertions()
    source, source_release, evidence_record = _resource_rows(
        asserted, ATLAS.entity
    )[0]
    target, target_release, _ = _resource_rows(asserted, ATLAS.subject)[0]
    source_ring = ATLAS.entity
    if case == "source-ring":
        source_ring = ATLAS.legalIdentity
    else:
        target_release = next(
            release
            for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
            if release not in {source_release, target_release}
        )

    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=source_ring,
        target_ring=ATLAS.subject,
        subject=source,
        predicate=ATLAS.hasIndexedSubject,
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name=f"python-cross-ring-{case}",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_assertions(asserted)

    assert raised.value.code == "dataset.release"
    assert expected_detail in raised.value.detail


@pytest.mark.parametrize("case", ("pair", "predicate"))
def test_python_cross_ring_policy_rejects_disallowed_cells(case: str) -> None:
    asserted = _fresh_asserted_graph_without_assertions()
    source, source_release, evidence_record = _resource_rows(
        asserted, ATLAS.entity
    )[0]
    if case == "pair":
        target_ring = ATLAS.value
        predicate = ATLAS.hasIndexedSubject
    else:
        target_ring = ATLAS.legalIdentity
        predicate = ATLAS.hasIndexedSubject
    target, target_release, _ = _resource_rows(asserted, target_ring)[0]

    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=ATLAS.entity,
        target_ring=target_ring,
        subject=source,
        predicate=predicate,
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name=f"python-cross-ring-policy-{case}",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_assertions(asserted)

    assert raised.value.code == "dataset.relation"
    assert "is not allowed" in raised.value.detail


def test_python_cross_ring_policy_matrix_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = json.loads(atlas_validate.PROFILE_MAP_PATH.read_text(encoding="utf-8"))
    profile["crossRingRelationPolicies"][0]["predicates"] = [
        str(ATLAS.alternateCrossRingRelation)
    ]
    profile["profileDigest"] = atlas_validate.canonical_sha256(
        {key: value for key, value in profile.items() if key != "profileDigest"},
        terminal_lf=False,
    )
    changed_path = tmp_path / "registry-resource-profiles.json"
    changed_path.write_bytes(atlas_validate.canonical_json_bytes(profile))
    monkeypatch.setattr(atlas_validate, "PROFILE_MAP_PATH", changed_path)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._cross_ring_relation_policies()

    assert raised.value.code == "profile.policy"
    assert "closed Atlas 3.0 matrix" in raised.value.detail


@pytest.mark.parametrize("conflicting_target", (False, True))
def test_identifier_pair_maps_to_exactly_one_resource(
    conflicting_target: bool,
) -> None:
    asserted = atlas_fixtures._base_fixture().asserted
    identifier = next(asserted.subjects(RDF.type, ATLAS.Identifier))
    original_resource = next(asserted.objects(identifier, ATLAS.identifies))
    duplicate = URIRef("urn:ref:atlas-test:identifier:duplicate")
    asserted.add((duplicate, RDF.type, ATLAS.Identifier))
    asserted.add(
        (
            duplicate,
            ATLAS.identifierScheme,
            next(asserted.objects(identifier, ATLAS.identifierScheme)),
        )
    )
    asserted.add(
        (
            duplicate,
            ATLAS.identifierValue,
            next(asserted.objects(identifier, ATLAS.identifierValue)),
        )
    )
    target = original_resource
    if conflicting_target:
        target = next(
            resource
            for resource in asserted.subjects(RDF.type, ATLAS.AtlasResource)
            if resource != original_resource
        )
    asserted.add((duplicate, ATLAS.identifies, target))

    if not conflicting_target:
        atlas_validate._check_identifier_uniqueness(asserted)
        return

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_identifier_uniqueness(asserted)

    assert raised.value.code == "dataset.identifier-uniqueness"
    assert "AGENCY-001" in raised.value.detail
    assert "identifies multiple Atlas resources" in raised.value.detail


def _identifier_conflict_graph() -> tuple[Graph, URIRef, URIRef]:
    """The base fixture plus the second Identifier that disagrees with the first."""

    asserted = atlas_fixtures._base_fixture().asserted
    original = next(asserted.subjects(RDF.type, ATLAS.Identifier))
    duplicate = URIRef("urn:ref:atlas-test:identifier:duplicate")
    asserted.add((duplicate, RDF.type, ATLAS.Identifier))
    asserted.add(
        (
            duplicate,
            ATLAS.identifierScheme,
            next(asserted.objects(original, ATLAS.identifierScheme)),
        )
    )
    asserted.add(
        (
            duplicate,
            ATLAS.identifierValue,
            next(asserted.objects(original, ATLAS.identifierValue)),
        )
    )
    asserted.add(
        (
            duplicate,
            ATLAS.identifies,
            next(
                resource
                for resource in asserted.subjects(RDF.type, ATLAS.AtlasResource)
                if resource != next(asserted.objects(original, ATLAS.identifies))
            ),
        )
    )
    return asserted, original, duplicate


def _record_registry_conflict(asserted: Graph, *entries: URIRef) -> URIRef:
    record = URIRef("urn:ref:atlas-test:registry-conflict:agency")
    asserted.add((record, RDF.type, RKAF.RegistryConflict))
    for entry in entries:
        asserted.add((record, RKAF.conflictingEntries, entry))
    asserted.add((record, RKAF.severity, RKAF.operationalConflict))
    asserted.add(
        (
            record,
            RKAF.detectedAt,
            Literal("2026-08-05T12:00:00+00:00", datatype=XSD.dateTime),
        )
    )
    return record


def test_a_published_registry_conflict_licenses_exactly_the_entries_it_names() -> None:
    """The no-silent-collapse rule, both ways round.

    A contradiction may be published instead of refused, but only by a record
    that names the entries which actually disagree. The corpus proves the same
    three outcomes end to end (identifier-conflict-recorded,
    identifier-pair-conflict, registry-conflict-entries-mismatch); this proves
    them against the gate itself, in a second, so the rule cannot be widened or
    dropped without something breaking in under two minutes.
    """

    asserted, original, duplicate = _identifier_conflict_graph()
    _record_registry_conflict(asserted, original, duplicate)
    atlas_validate._check_identifier_uniqueness(asserted)

    asserted, original, _duplicate = _identifier_conflict_graph()
    bystander = URIRef("urn:ref:atlas-test:identifier:bystander")
    asserted.add((bystander, RDF.type, ATLAS.Identifier))
    asserted.add(
        (
            bystander,
            ATLAS.identifierScheme,
            next(asserted.objects(original, ATLAS.identifierScheme)),
        )
    )
    asserted.add((bystander, ATLAS.identifierValue, Literal("AGENCY-002")))
    asserted.add(
        (
            bystander,
            ATLAS.identifies,
            next(asserted.objects(original, ATLAS.identifies)),
        )
    )
    _record_registry_conflict(asserted, original, bystander)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_identifier_uniqueness(asserted)

    assert raised.value.code == "dataset.identifier-uniqueness"
    assert "do not disagree on one identifier pair" in raised.value.detail
    assert str(bystander) in raised.value.detail


def test_identifier_uniqueness_valid_path_does_not_sort_identifiers() -> None:
    class UnsortableIri(URIRef):
        def __lt__(self, other: object) -> bool:
            raise AssertionError(f"identifier validation must not sort {self} and {other}")

    asserted = Graph()
    identifiers = {
        UnsortableIri("urn:test:identifier:two"),
        UnsortableIri("urn:test:identifier:one"),
    }
    for ordinal, identifier in enumerate(identifiers):
        asserted.add((identifier, ATLAS.identifierScheme, URIRef("urn:test:scheme")))
        asserted.add((identifier, ATLAS.identifierValue, Literal(f"ID-{ordinal}")))
        asserted.add((identifier, ATLAS.identifies, URIRef(f"urn:test:resource:{ordinal}")))
    inventory = atlas_validate.SemanticInventory(
        asserted_by_carrier={ATLAS.Identifier: identifiers},
        derived_nodes=frozenset(),
        projection_nodes=frozenset(),
    )

    atlas_validate._check_identifier_uniqueness(asserted, inventory)


def test_serialized_nquads_profile_accepts_only_sorted_unique_lines(tmp_path: Path) -> None:
    first = b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
    second = b"<urn:b> <urn:p> <urn:o> <urn:g> .\n"
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(first + second)
    assert atlas_validate._check_serialized_nquads_profile(dataset_path) == 2

    for invalid in (first + first, second + first):
        dataset_path.write_bytes(invalid)
        with pytest.raises(atlas_validate.AtlasValidationError, match="sorted and unique"):
            atlas_validate._check_serialized_nquads_profile(dataset_path)


def test_serialized_nquads_profile_rejects_oversized_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    line = b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
    dataset_path.write_bytes(line)
    monkeypatch.setattr(atlas_validate, "NQUADS_MAX_LINE_BYTES", len(line) - 1)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_serialized_nquads_profile(dataset_path)

    assert raised.value.code == "rdf.resource-limit"


def test_canonical_term_comparison_rejects_an_equivalent_noncanonical_escape(tmp_path: Path) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(b'<urn:s> <urn:p> "\\u0061" <urn:g> .\n')
    manifest = {"graphs": [{"role": "asserted", "id": "urn:g", "quadCount": 1}]}

    with pytest.raises(atlas_validate.AtlasValidationError, match="canonical N-Quads term form"):
        atlas_validate._parse_dataset(dataset_path, manifest)


def test_parse_dataset_streams_without_path_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(b"<urn:s> <urn:p> <urn:o> <urn:g> .\n")
    manifest = {"graphs": [{"role": "asserted", "id": "urn:g", "quadCount": 1}]}

    def fail_whole_file_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("dataset parsing must not use a whole-file Path read")

    monkeypatch.setattr(Path, "read_bytes", fail_whole_file_read)
    monkeypatch.setattr(Path, "read_text", fail_whole_file_read)
    dataset, graphs = atlas_validate._parse_dataset(dataset_path, manifest)

    assert len(dataset) == 1
    assert graphs["asserted"].store is dataset.store


def test_file_digest_streams_without_using_path_read_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"stream this payload\n"
    path = tmp_path / "member.bin"
    path.write_bytes(payload)

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("file_sha256 must not materialize the complete member")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    assert atlas_validate.file_sha256(path) == "sha256:" + hashlib.sha256(payload).hexdigest()


def test_parsed_role_graphs_are_views_over_one_dataset_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = json.loads((VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8"))
    expected_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}

    def fail_graph_copy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("role graph views must not allocate independent Graph stores")

    monkeypatch.setattr(atlas_validate, "Graph", fail_graph_copy)
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    dataset, graphs = atlas_validate._parse_packed_dataset(
        VALID_DISTRIBUTION, manifest, graph_ids
    )

    assert {role: graph.identifier for role, graph in graphs.items()} == expected_ids
    assert all(graph.store is dataset.store for graph in graphs.values())


def test_shacl_uses_a_read_only_ontology_view_without_cloning_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyshacl.validator

    dataset, graphs, _ = _load_valid_graphs()
    ontology, shapes = atlas_validate._parse_binding_graphs()
    before = {role: len(graph) for role, graph in graphs.items()}

    def fail_clone(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("SHACL must not clone an Atlas role graph")

    monkeypatch.setattr(pyshacl.validator, "clone_graph", fail_clone)
    atlas_validate._run_shacl(graphs, ontology, shapes)

    assert {role: len(graph) for role, graph in graphs.items()} == before
    assert dataset.store is graphs["asserted"].store


def _shacl_conformance_pair(graphs: Mapping[str, Graph]) -> tuple[bool, bool]:
    ontology, shapes = atlas_validate._parse_binding_graphs()
    ontology_view = atlas_validate.inoculate(Graph(), ontology)
    view = atlas_validate._ShaclDataView([graphs["asserted"], ontology_view])
    plan = atlas_validate._batched_shacl_plan(shapes)
    original, _, _ = atlas_validate._validate_shacl_data(view, shapes)
    fast = atlas_validate._batched_shacl_prechecks(view, shapes, plan)
    if fast:
        fast, _, _ = atlas_validate._validate_shacl_data(view, plan.shapes)
    return original, fast


def test_batched_shacl_plan_keeps_normative_shapes_and_lifts_direct_properties() -> None:
    _, shapes = atlas_validate._parse_binding_graphs()
    normative_triples = set(shapes)
    property_shapes = set(shapes.objects(ATLAS.SourceRecordShape, SH.property))

    plan = atlas_validate._batched_shacl_plan(shapes)

    assert set(shapes) == normative_triples
    assert property_shapes
    assert not list(plan.shapes.objects(ATLAS.SourceRecordShape, SH.property))
    assert all(
        (property_shape, SH.targetClass, ATLAS.SourceRecord) in plan.shapes
        for property_shape in property_shapes
    )
    assert all(
        (property_shape, SH.node, ATLAS.DigestValueShape) not in plan.shapes
        for property_shape in property_shapes
    )
    assert ATLAS.SourceRecordShape in {
        closed.shape for closed in plan.closed_shapes
    }
    assert plan.checks_relation_ring_context


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("valid", True),
        ("closed-property", False),
        ("digest", False),
        ("evidence", False),
        ("ring-context", False),
    ),
)
def test_batched_shacl_conformance_matches_normative_shapes(
    mutation: str,
    expected: bool,
) -> None:
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    if mutation == "closed-property":
        resource = next(asserted.subjects(RDF.type, ATLAS.SubjectConcept))
        asserted.add((resource, URIRef("urn:test:unexpected"), Literal("extra")))
    elif mutation == "digest":
        record = next(asserted.subjects(RDF.type, ATLAS.SourceRecord))
        asserted.remove((record, ATLAS.contentDigest, None))
        asserted.add((record, ATLAS.contentDigest, Literal("not-a-digest")))
    elif mutation == "evidence":
        assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        binding = next(asserted.subjects(RKAF.bindsAssertion, assertion))
        asserted.remove((binding, None, None))
    elif mutation == "ring-context":
        assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
        asserted.add((assertion, ATLAS.sourceRing, ATLAS.subject))
        asserted.add((assertion, ATLAS.targetRing, ATLAS.entity))

    assert _shacl_conformance_pair(graphs) == (expected, expected)


def test_audit_mode_invalid_path_falls_back_to_exact_normative_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(atlas_validate.VALIDATION_MODE_ENV, atlas_validate.AUDIT_VALIDATION_MODE)
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
    binding = next(asserted.subjects(RKAF.bindsAssertion, assertion))
    asserted.remove((binding, None, None))
    ontology, shapes = atlas_validate._parse_binding_graphs()
    calls: list[Graph] = []
    original_validate = atlas_validate._validate_shacl_data

    def counted(data_graph: Graph, shape_graph: Graph) -> tuple[bool, Any, str]:
        calls.append(shape_graph)
        return original_validate(data_graph, shape_graph)

    monkeypatch.setattr(atlas_validate, "_validate_shacl_data", counted)
    with pytest.raises(atlas_validate.AtlasValidationError) as fast_error:
        atlas_validate._run_shacl(graphs, ontology, shapes)

    assert len(calls) == 2
    assert calls[0] is not shapes
    assert calls[1] is shapes

    calls.clear()
    monkeypatch.setattr(
        atlas_validate,
        "_batched_shacl_prechecks",
        lambda *_args: False,
    )
    with pytest.raises(atlas_validate.AtlasValidationError) as original_error:
        atlas_validate._run_shacl(graphs, ontology, shapes)

    assert calls == [shapes]
    assert str(fast_error.value) == str(original_error.value)


def _shacl_components(error: atlas_validate.AtlasValidationError) -> list[str]:
    match = re.search(r"does not conform \[([^\]]*)\]", error.detail)
    assert match is not None, error.detail
    return match.group(1).split(", ")


def test_red_path_reports_without_running_the_whole_graph_normative_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default red path never hands the whole graph to the normative engine.

    Measured on the 32M-quad build, that whole-graph run cost 94 minutes and
    produced nothing but the wording of a failure the fast path had already
    detected. So the report now comes from the focus nodes the fast path
    named -- and it must still name the same constraint components as the
    audit run, which is the only part of the message that is contractual.
    """

    monkeypatch.delenv(atlas_validate.VALIDATION_MODE_ENV, raising=False)
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
    binding = next(asserted.subjects(RKAF.bindsAssertion, assertion))
    asserted.remove((binding, None, None))
    ontology, shapes = atlas_validate._parse_binding_graphs()
    calls: list[Graph] = []
    original_validate = atlas_validate._validate_shacl_data

    def counted(data_graph: Graph, shape_graph: Graph) -> tuple[bool, Any, str]:
        calls.append(shape_graph)
        return original_validate(data_graph, shape_graph)

    monkeypatch.setattr(atlas_validate, "_validate_shacl_data", counted)
    with pytest.raises(atlas_validate.AtlasValidationError) as fast_error:
        atlas_validate._run_shacl(graphs, ontology, shapes)

    assert [call is shapes for call in calls] == [False]

    calls.clear()
    monkeypatch.setenv(atlas_validate.VALIDATION_MODE_ENV, atlas_validate.AUDIT_VALIDATION_MODE)
    with pytest.raises(atlas_validate.AtlasValidationError) as audit_error:
        atlas_validate._run_shacl(graphs, ontology, shapes)

    assert calls[-1] is shapes
    assert fast_error.value.code == audit_error.value.code == "shacl.data"
    assert _shacl_components(fast_error.value) == _shacl_components(audit_error.value)


@pytest.mark.parametrize(
    "case",
    (
        # One case per way the fast path can detect a miss: a lifted closed
        # shape, a lifted ring-context xone, an inlined value shape, a
        # value-side class constraint, and the derived role rather than the
        # asserted one.
        "assertion-extra-property",
        "mapping-subject-ring-dated",
        "mapping-period-start-not-datetime",
        "mapping-missing-evidence",
        "derived-is-authoritative",
        "evidence-warrant-unsanctioned",
    ),
)
def test_fail_fast_and_audit_name_the_same_constraint_components(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-fast is a report budget, never a different verdict.

    Every corpus case that fires `shacl.data` must fire it with the same code
    and the same sorted component list in both modes; the corpus pins the
    codes, and this pins the components the operator reads.
    """

    distribution = BINDING_ROOT / "fixtures" / "invalid" / case
    verdicts: dict[str, atlas_validate.AtlasValidationError] = {}
    for mode in (None, atlas_validate.AUDIT_VALIDATION_MODE):
        if mode is None:
            monkeypatch.delenv(atlas_validate.VALIDATION_MODE_ENV, raising=False)
        else:
            monkeypatch.setenv(atlas_validate.VALIDATION_MODE_ENV, mode)
        with pytest.raises(atlas_validate.AtlasValidationError) as error:
            atlas_validate.validate_distribution(distribution)
        verdicts[str(mode)] = error.value

    fast, audit = verdicts["None"], verdicts[atlas_validate.AUDIT_VALIDATION_MODE]
    assert fast.code == audit.code == "shacl.data"
    assert _shacl_components(fast) == _shacl_components(audit)
    assert _shacl_components(fast) == sorted(set(_shacl_components(fast)))


def test_focus_sample_names_one_node_per_violated_constraint() -> None:
    """2,003 identical violations must cost one re-validated node, not 2,003."""

    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    bindings = list(asserted.subjects(RDF.type, RKAF.EvidenceBinding))
    assert len(bindings) > 1
    for binding in bindings:
        asserted.remove((binding, RKAF.evidentiaryFunction, None))
        asserted.add((binding, RKAF.evidentiaryFunction, URIRef("urn:test:not-a-function")))
    ontology, shapes = atlas_validate._parse_binding_graphs()
    ontology_view = atlas_validate.inoculate(Graph(), ontology)
    view = atlas_validate._ShaclDataView([asserted, ontology_view])
    plan = atlas_validate._batched_shacl_plan(shapes)

    conforms, report, _ = atlas_validate._validate_shacl_data(view, plan.shapes)
    samples = atlas_validate._shacl_focus_samples((), report)

    assert not conforms
    assert samples is not None
    assert len(samples) == 1
    assert samples[0] in bindings
    groups = atlas_validate._root_shape_focus_groups(view, shapes, samples)
    assert groups is not None
    assert set(groups) == {ATLAS.EvidenceBindingShape}
    assert "InConstraintComponent" in (
        atlas_validate._focused_shacl_report(view, shapes, samples) or ""
    )


def test_smoke_check_is_a_sample_that_can_never_reach_the_receipt_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A smoke result is a sample, and it must be impossible to bank one.

    The receipt cache answers a later acceptance run from an earlier verdict,
    so a sampled result reaching it would turn "we looked at three packs" into
    "this distribution was accepted".
    """

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a smoke run must never touch the validation receipt cache")

    monkeypatch.setattr(atlas_validate, "_read_validation_receipt", refuse)
    monkeypatch.setattr(atlas_validate, "_write_validation_receipt", refuse)

    result = atlas_validate.smoke_check(VALID_DISTRIBUTION)
    smoke = result["smoke"]

    assert set(result) == {"smoke"}
    assert 0 < smoke["sampledPackCount"] <= smoke["packCount"]
    assert 0 < smoke["sampledQuadCount"] <= smoke["totalQuadCount"]
    assert "not acceptance" in smoke["warning"]
    assert {"unsampled-packs", "source-accounting", "adjudication", "compact-layer"} <= set(
        smoke["notChecked"]
    )
    assert not set(smoke["checked"]) & set(smoke["notChecked"])

    assert atlas_validate.main(["--smoke", str(VALID_DISTRIBUTION), "--quiet"]) == 0
    assert json.loads(capsys.readouterr().out)["smoke"] == smoke

    # The cache flag belongs to acceptance and is refused here rather than
    # quietly ignored, and the two questions cannot be asked at once.
    assert (
        atlas_validate.main(
            ["--smoke", str(VALID_DISTRIBUTION), "--cache-dir", str(tmp_path), "--quiet"]
        )
        == 1
    )
    assert "cache.path" in capsys.readouterr().err
    assert (
        atlas_validate.main(
            [
                "--smoke",
                str(VALID_DISTRIBUTION),
                "--distribution",
                str(VALID_DISTRIBUTION),
                "--quiet",
            ]
        )
        == 1
    )
    assert "smoke.mode" in capsys.readouterr().err


def test_smoke_check_shacl_refuses_a_sampled_defect() -> None:
    """The sampled SHACL pass is the real one, against the full shapes."""

    with pytest.raises(atlas_validate.AtlasValidationError) as error:
        atlas_validate.smoke_check(BINDING_ROOT / "fixtures" / "invalid" / "evidence-warrant-unsanctioned")

    assert error.value.code == "shacl.data"
    assert "XoneConstraintComponent" in error.value.detail


def test_smoke_sample_takes_every_pack_kind_within_its_budget() -> None:
    """Kind coverage first: a size-ordered sample skips every mapping pack."""

    manifest = json.loads((VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8"))
    kinds = {pack["kind"] for pack in manifest["packs"]}
    sample = atlas_validate._smoke_sample_packs(manifest)

    assert kinds
    assert {pack["kind"] for pack in sample} == kinds
    assert sum(pack["content"]["byteLength"] for pack in sample) <= (
        atlas_validate.SMOKE_SAMPLE_MAX_CONTENT_BYTES
    )
    # Dependencies come with the packs that declare them, or the sample would
    # report violations the distribution does not have.
    sampled_ids = {pack["packId"] for pack in sample}
    assert all(set(pack["dependencies"]) <= sampled_ids for pack in sample)


def test_batched_shacl_reduces_shape_dispatches_on_valid_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyshacl.shape import Shape

    _, graphs, _ = _load_valid_graphs()
    ontology, shapes = atlas_validate._parse_binding_graphs()
    ontology_view = atlas_validate.inoculate(Graph(), ontology)
    view = atlas_validate._ShaclDataView([graphs["asserted"], ontology_view])
    plan = atlas_validate._batched_shacl_plan(shapes)
    original_validate = Shape.validate
    active_counter: list[int] = []

    def counted(shape: Shape, *args: Any, **kwargs: Any) -> Any:
        active_counter[0] += 1
        return original_validate(shape, *args, **kwargs)

    monkeypatch.setattr(Shape, "validate", counted)
    counts: list[int] = []
    for shape_graph in (shapes, plan.shapes):
        active_counter[:] = [0]
        conforms, _, _ = atlas_validate._validate_shacl_data(view, shape_graph)
        assert conforms
        counts.append(active_counter[0])

    original_count, batched_count = counts
    # Batching still removes most dispatches. The margin was a factor of three
    # before the six-branch sh:xone that replaced atlas:reviewMethod: an xone
    # dispatches each branch in both modes, so it raises the batched floor
    # without raising the unbatched ceiling proportionally.
    assert batched_count * 2 < original_count


def test_distribution_member_digests_are_reused_after_required_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    calls: list[Path] = []
    original = atlas_validate.file_sha256

    def counted(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(atlas_validate, "file_sha256", counted)
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    construction_path = distribution / atlas_validate.CONSTRUCTION_SUMMARY_FILE
    construction = (
        atlas_validate._load_json(construction_path, require_canonical=True)
        if construction_path.exists()
        else None
    )
    member_digests = atlas_validate._check_distribution_files(
        distribution,
        manifest,
        construction,
    )
    accounting = atlas_validate._load_json(
        distribution / "atlas-source-accounting.json",
        require_canonical=True,
        expected_digest=member_digests["atlas-source-accounting.json"],
    )
    acceptance = atlas_validate._load_json(
        distribution / "atlas-acceptance.json",
        require_canonical=True,
        expected_digest=member_digests["atlas-acceptance.json"],
    )
    atlas_validate._parse_packed_dataset(distribution, manifest, graph_ids)
    atlas_validate._check_acceptance(manifest, accounting, acceptance, member_digests)

    assert calls == []


@pytest.mark.parametrize("compression", ("none", "zstd"))
def test_packed_distribution_validates_without_materializing_pack_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compression: str,
) -> None:
    distribution = _write_packed_distribution(
        tmp_path / "distribution",
        compression=compression,
    )

    def reject_writes(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("validation must not write an uncompressed pack copy")

    monkeypatch.setattr(Path, "write_bytes", reject_writes)
    result = atlas_validate.validate_distribution(distribution)

    assert result["quadCount"] == 1042
    assert result["inferredMappingCount"] == 7


def test_packed_distribution_accepts_bound_compiled_producer_proof(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    _install_producer_validation(distribution)

    result = atlas_validate.validate_distribution(distribution)

    assert result["quadCount"] == 1042


def test_publisher_only_compiled_producer_identity_is_rejected(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    _install_producer_validation(
        distribution,
        constructorProfile="atlas-3-source-and-publisher-mapping-compiled-shacl-v1",
        mode="compiledSourceAndPublisherMappingProducerValidation",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution)

    assert raised.value.code == "json.schema"


def test_compiled_producer_proof_digest_tampering_is_rejected(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    _install_producer_validation(distribution)
    proof_path = distribution / atlas_validate.PRODUCER_VALIDATION_FILE
    proof_path.write_bytes(proof_path.read_bytes().replace(b"unit-test", b"tamper___", 1))

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution)

    assert raised.value.code == "distribution.digest"


def test_compiled_producer_proof_inventory_tampering_is_rejected_when_resealed(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    _install_producer_validation(
        distribution,
        assertedInventoryDigest="sha256:" + "0" * 64,
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution)

    assert raised.value.code == "producer.validation"
    assert "asserted inventory" in raised.value.detail


def test_compiled_producer_acceptance_pin_without_member_is_rejected(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    manifest = json.loads(
        (distribution / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    acceptance = json.loads(
        (distribution / "atlas-acceptance.json").read_text(encoding="utf-8")
    )
    acceptance["inputs"]["producerValidationDigest"] = "sha256:" + "0" * 64
    _write_distribution_json(distribution, manifest, acceptance)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution)

    assert raised.value.code == "producer.validation"


def test_compiled_producer_member_without_acceptance_pin_is_rejected(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    _install_producer_validation(distribution)
    manifest = json.loads(
        (distribution / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    acceptance = json.loads(
        (distribution / "atlas-acceptance.json").read_text(encoding="utf-8")
    )
    del acceptance["inputs"]["producerValidationDigest"]
    _write_distribution_json(distribution, manifest, acceptance)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution)

    assert raised.value.code == "producer.validation"


def test_declared_compiled_producer_proof_length_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    (distribution / atlas_validate.PRODUCER_VALIDATION_FILE).write_bytes(b"{}\n")

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution)

    assert raised.value.code == "distribution.length"


def test_packed_distribution_allows_empty_optional_view_graphs(tmp_path: Path) -> None:
    distribution = _write_packed_distribution(
        tmp_path / "distribution",
        include_projection=False,
        include_derived=False,
    )

    result = atlas_validate.validate_distribution(distribution)

    assert result["counts"]["projectedRelations"] == 0
    assert result["counts"]["derivedRelations"] == 0
    assert result["quadCount"] == 919


def test_authenticated_cache_reuses_an_exact_complete_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution", compression="zstd")
    cache_dir = tmp_path / "validation-cache"
    expected = atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)

    def reject_graph_work(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("an exact cache hit must not parse or semantically rescan RDF")

    original_load_json = atlas_validate._load_json

    def reject_accounting_parse(path: Path, **kwargs: object) -> Any:
        if path.name == "atlas-source-accounting.json":
            raise AssertionError("an exact cache hit must not parse source accounting")
        return original_load_json(path, **kwargs)

    monkeypatch.setattr(atlas_validate, "_load_json", reject_accounting_parse)
    monkeypatch.setattr(atlas_validate, "_parse_packed_dataset", reject_graph_work)
    monkeypatch.setattr(atlas_validate, "_validate_semantic_graphs", reject_graph_work)

    assert atlas_validate.validate_distribution(distribution, cache_dir=cache_dir) == expected
    assert len(list((cache_dir / "receipts").glob("*.json"))) == 1


def test_cache_hit_rejects_same_length_source_accounting_tamper(
    tmp_path: Path,
) -> None:
    distribution = _write_packed_distribution(
        tmp_path / "distribution",
        compression="zstd",
    )
    cache_dir = tmp_path / "validation-cache"
    atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)
    accounting_path = distribution / "atlas-source-accounting.json"
    original = accounting_path.read_bytes()
    damaged = original.replace(b'"represented"', b'"representee"', 1)
    assert damaged != original
    assert len(damaged) == len(original)
    accounting_path.write_bytes(damaged)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)

    assert raised.value.code == "distribution.digest"


def test_cache_hit_still_hashes_every_exact_pack_transport(tmp_path: Path) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution", compression="zstd")
    cache_dir = tmp_path / "validation-cache"
    atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    pack_path = distribution / manifest["packs"][0]["path"]
    damaged = bytearray(pack_path.read_bytes())
    damaged[len(damaged) // 2] ^= 1
    pack_path.write_bytes(damaged)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)

    assert raised.value.code == "pack.transport"


def test_tampered_cache_receipt_falls_back_to_full_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    cache_dir = tmp_path / "validation-cache"
    expected = atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)
    receipt_path = next((cache_dir / "receipts").glob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["payload"]["result"]["inferredMappingCount"] += 1
    receipt_path.write_bytes(atlas_validate.canonical_json_bytes(receipt))
    original = atlas_validate._parse_packed_dataset
    parse_count = 0

    def counted(*args: object, **kwargs: object) -> Any:
        nonlocal parse_count
        parse_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(atlas_validate, "_parse_packed_dataset", counted)

    assert atlas_validate.validate_distribution(distribution, cache_dir=cache_dir) == expected
    assert parse_count == 1


def test_validation_cache_cannot_modify_the_closed_distribution(tmp_path: Path) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(
            distribution,
            cache_dir=distribution / ".cache",
        )

    assert raised.value.code == "cache.path"


def test_validation_cache_key_includes_binding_and_validator_identity(tmp_path: Path) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    original = atlas_validate._validation_cache_key(manifest)
    manifest["binding"]["bindingBundleDigest"] = "sha256:" + "0" * 64

    assert atlas_validate._validation_cache_key(manifest) != original


def _tool_copy_with_edited_validator(root: Path) -> Path:
    """Copy the four pinned tools, adding one byte to the validator."""

    root.mkdir(parents=True, exist_ok=True)
    for relative in atlas_validate.BINDING_TOOL_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(atlas_validate.BINDING_ROOT / relative, target)
    validator = root / "tools" / "validate.py"
    validator.write_bytes(validator.read_bytes() + b'\n_fail("dataset.new", "one more refusal")\n')
    return root


def test_a_validator_only_change_invalidates_the_validation_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new refusal must not be answered from the old validator's acceptance.

    `bindingBundleDigest` deliberately excludes the tools, because conformance
    identity must not move when a program changes. The cache key must not make
    the same exclusion: a hit returns before every procedural check runs, so an
    acceptance computed by a validator that lacked a refusal would still be
    served by the validator that has it.
    """

    distribution = _write_packed_distribution(tmp_path / "distribution")
    cache_dir = tmp_path / "validation-cache"
    expected = atlas_validate.validate_distribution(distribution, cache_dir=cache_dir)
    assert len(list((cache_dir / "receipts").glob("*.json"))) == 1

    changed = _tool_copy_with_edited_validator(tmp_path / "changed-tools")
    monkeypatch.setattr(
        atlas_validate,
        "_binding_tool_paths",
        lambda: tuple(changed / relative for relative in atlas_validate.BINDING_TOOL_PATHS),
    )
    original_parse = atlas_validate._parse_packed_dataset
    parses = 0

    def counted(*args: object, **kwargs: object) -> Any:
        nonlocal parses
        parses += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(atlas_validate, "_parse_packed_dataset", counted)

    assert atlas_validate.validate_distribution(distribution, cache_dir=cache_dir) == expected
    assert parses == 1, "the changed validator answered from the old validator's receipt"
    assert len(list((cache_dir / "receipts").glob("*.json"))) == 2

    # The contract did not move: the corpus stays valid under both validators.
    assert (
        atlas_validate._binding_digests()["bindingBundleDigest"]
        == json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))["binding"][
            "bindingBundleDigest"
        ]
    )


def test_the_validation_cache_key_covers_the_runtime_the_verdict_ran_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    original = atlas_validate._validation_cache_key(manifest)
    bumped = {**atlas_validate.binding_runtime(), "pyshacl": "0.0.0-not-this-one"}
    monkeypatch.setattr(atlas_validate, "binding_runtime", lambda: bumped)

    assert atlas_validate._validation_cache_key(manifest) != original


def test_the_fixture_receipt_and_the_cache_key_read_one_runtime_notion() -> None:
    """One notion, two readers -- not two inventories that can drift apart."""

    runtime = atlas_validate.binding_runtime()

    assert atlas_fixtures._current_receipt()["runtime"] == runtime
    assert set(runtime) == {"python", *atlas_validate._binding_runtime_distributions()}
    assert atlas_validate._validation_cache_identity(
        json.loads((VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8"))
    )["runtime"] == runtime


@pytest.mark.parametrize("compression", ("none", "zstd"))
@pytest.mark.parametrize(
    ("section", "field", "expected_code"),
    (
        ("transport", "digest", "pack.transport"),
        ("transport", "byteLength", "pack.transport"),
        ("content", "digest", "pack.content"),
        ("content", "byteLength", "pack.content"),
        ("content", "quadCount", "pack.content"),
    ),
)
def test_pack_receipts_are_verified_while_streaming(
    tmp_path: Path,
    compression: str,
    section: str,
    field: str,
    expected_code: str,
) -> None:
    distribution = _write_packed_distribution(
        tmp_path / "distribution",
        compression=compression,
    )
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    pack = manifest["packs"][0]
    if field == "digest":
        pack[section][field] = "sha256:" + "0" * 64
    else:
        pack[section][field] += 1

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._parse_pack_into_dataset(
            Dataset(),
            distribution,
            pack,
            graph_ids,
            {role: {} for role in graph_ids},
        )

    assert raised.value.code == expected_code


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("pack-order", "pack.manifest"),
        ("inventory", "pack.inventory"),
        ("dependency", "pack.dependency"),
    ),
)
def test_pack_manifest_reconciles_order_inventory_and_dependencies(
    tmp_path: Path,
    case: str,
    expected_code: str,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    if case == "pack-order":
        manifest["packs"].reverse()
    elif case == "inventory":
        manifest["graphs"][0]["inventoryDigest"] = "sha256:" + "0" * 64
    else:
        view_pack = next(pack for pack in manifest["packs"] if pack["kind"] == "view")
        view_pack["dependencies"] = []

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_pack_manifest(manifest)

    assert raised.value.code == expected_code


def test_distribution_file_set_is_recursively_closed(tmp_path: Path) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    extra = distribution / "packs" / "unlisted" / "extra.nq"
    extra.parent.mkdir()
    extra.write_bytes(b"unlisted\n")

    construction_path = distribution / atlas_validate.CONSTRUCTION_SUMMARY_FILE
    construction = (
        atlas_validate._load_json(construction_path, require_canonical=True)
        if construction_path.exists()
        else None
    )
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_distribution_files(
            distribution,
            manifest,
            construction,
        )

    assert raised.value.code == "distribution.members"


def test_one_subject_cannot_have_outgoing_facts_in_two_packs(tmp_path: Path) -> None:
    graph_ids = {
        "asserted": URIRef("urn:ref:atlas-test:graph:asserted"),
        "projection": URIRef("urn:ref:atlas-test:graph:projection"),
        "derived": URIRef("urn:ref:atlas-test:graph:derived"),
    }
    subject = URIRef("urn:ref:atlas-test:subject")
    owners: dict[str, dict[URIRef, str]] = {role: {} for role in graph_ids}

    def write_pack(name: str, predicate: str) -> dict[str, Any]:
        payload = (
            atlas_validate.nquads_line(
                subject,
                URIRef(predicate),
                URIRef("urn:ref:atlas-test:object"),
                graph_ids["asserted"],
            ).encode("utf-8")
            + b"\n"
        )
        relative = f"{name}.nq"
        (tmp_path / relative).write_bytes(payload)
        return {
            "content": {
                "byteLength": len(payload),
                "digest": _sha256(payload),
                "mediaType": "application/n-quads",
                "quadCount": 1,
            },
            "dependencies": [],
            "graphCounts": {"asserted": 1, "projection": 0, "derived": 0},
            "kind": "aggregate",
            "packId": f"urn:ref:atlas-test:pack:{name}",
            "path": relative,
            "rings": [],
            "sourceReleases": [],
            "transport": {
                "byteLength": len(payload),
                "compression": "none",
                "digest": _sha256(payload),
                "mediaType": "application/n-quads",
            },
        }

    dataset = Dataset()
    atlas_validate._parse_pack_into_dataset(
        dataset,
        tmp_path,
        write_pack("first", "urn:ref:atlas-test:predicate:first"),
        graph_ids,
        owners,
    )
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._parse_pack_into_dataset(
            dataset,
            tmp_path,
            write_pack("second", "urn:ref:atlas-test:predicate:second"),
            graph_ids,
            owners,
        )

    assert raised.value.code == "pack.co-location"


def test_asserted_cross_pack_dependencies_must_be_exact() -> None:
    asserted = Graph()
    first_subject = URIRef("urn:ref:atlas-test:subject:first")
    second_subject = URIRef("urn:ref:atlas-test:subject:second")
    first_pack = "urn:ref:atlas-test:pack:first"
    second_pack = "urn:ref:atlas-test:pack:second"
    asserted.add(
        (
            first_subject,
            URIRef("urn:ref:atlas-test:predicate"),
            second_subject,
        )
    )
    manifest = {
        "packs": [
            {
                "dependencies": [],
                "graphCounts": {"asserted": 1, "projection": 0, "derived": 0},
                "packId": first_pack,
            },
            {
                "dependencies": [],
                "graphCounts": {"asserted": 1, "projection": 0, "derived": 0},
                "packId": second_pack,
            },
        ]
    }
    owners = {first_subject: first_pack, second_subject: second_pack}

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_asserted_pack_dependencies(asserted, manifest, owners)
    assert raised.value.code == "pack.dependency"
    assert second_pack in raised.value.detail

    manifest["packs"][0]["dependencies"] = [second_pack]
    atlas_validate._check_asserted_pack_dependencies(asserted, manifest, owners)

    manifest["packs"][1]["dependencies"] = [first_pack]
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_asserted_pack_dependencies(asserted, manifest, owners)
    assert raised.value.code == "pack.dependency"
    assert first_pack in raised.value.detail


def test_canonical_renderer_caches_repeated_iri_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = atlas_validate._canonical_ntriples_term
    calls: list[URIRef] = []

    def counted(term: object) -> str:
        if isinstance(term, URIRef):
            calls.append(term)
        return original(term)

    atlas_validate._cached_iri_term.cache_clear()
    monkeypatch.setattr(atlas_validate, "_canonical_ntriples_term", counted)
    terms = (URIRef("urn:s"), URIRef("urn:p"), URIRef("urn:o"), URIRef("urn:g"))
    for _ in range(100):
        atlas_validate.nquads_line(*terms)

    assert calls == list(terms)
    atlas_validate._cached_iri_term.cache_clear()


def test_general_node_digest_pass_skips_records_verified_by_specialized_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graphs, _ = _load_valid_graphs()
    original = atlas_validate.rdf_node_digest

    def reject_duplicate_work(graph: Graph, node: URIRef) -> str:
        if (node, RDF.type, RKAF.EvidenceBinding) in graph or (
            node,
            RDF.type,
            ATLAS.ProjectedRelation,
        ) in graph:
            raise AssertionError(f"specialized check already verifies {node}")
        return original(graph, node)

    monkeypatch.setattr(atlas_validate, "rdf_node_digest", reject_duplicate_work)
    atlas_validate._check_node_digests(graphs)


def test_graph_role_pass_enforces_asserted_carrier_exclusivity() -> None:
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource = next(asserted.subjects(RDF.type, ATLAS.SubjectConcept))
    asserted.add((resource, RDF.type, ATLAS.Identifier))

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_graph_roles(graphs)

    assert raised.value.code == "dataset.graph-placement"
    assert "exactly one concrete Atlas carrier type" in raised.value.detail


def test_graph_role_pass_enforces_required_base_types() -> None:
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource = next(asserted.subjects(RDF.type, ATLAS.SubjectConcept))
    asserted.remove((resource, RDF.type, ATLAS.AtlasResource))

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_graph_roles(graphs)

    assert raised.value.code == "dataset.graph-placement"
    assert "type set differs from its concrete carrier" in raised.value.detail


def test_graph_role_pass_enforces_derived_type_exclusivity() -> None:
    _, graphs, _ = _load_valid_graphs()
    derived = graphs["derived"]
    relation = next(derived.subjects(RDF.type, ATLAS.DerivedRelation))
    derived.add((relation, RDF.type, ATLAS.RelationAssertion))

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_graph_roles(graphs)

    assert raised.value.code == "dataset.graph-placement"
    assert "derived subject" in raised.value.detail


def test_semantic_inventory_eliminates_repeated_carrier_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graphs, manifest = _load_valid_graphs()
    asserted = graphs["asserted"]
    accounting = json.loads(
        (VALID_DISTRIBUTION / "atlas-source-accounting.json").read_text(encoding="utf-8")
    )
    inventory = atlas_validate._check_graph_roles(graphs)
    original_subjects = Graph.subjects

    def reject_redundant_subject_scan(
        graph: Graph,
        predicate: URIRef | None = None,
        object: object | None = None,
        unique: bool = False,
    ) -> Any:
        if predicate == RDF.type and object in {
            *atlas_validate.ASSERTED_CARRIER_TYPES,
            ATLAS.DerivedRelation,
            ATLAS.ProjectedRelation,
        }:
            raise AssertionError("carrier nodes must come from the shared inventory")
        if predicate == ATLAS.sourceRecord and object is not None:
            raise AssertionError("source accounting must not rescan inverse links per record")
        return original_subjects(
            graph,
            predicate=predicate,
            object=object,
            unique=unique,
        )

    monkeypatch.setattr(Graph, "subjects", reject_redundant_subject_scan)
    atlas_validate._check_profile_conformance(asserted, inventory)
    atlas_validate._check_identifier_uniqueness(asserted, inventory)
    atlas_validate._check_release_membership(asserted, inventory)
    atlas_validate._check_label_integrity(asserted, inventory)
    atlas_validate._check_evidence_bindings(asserted, inventory)
    atlas_validate._validate_assertions(asserted, inventory)
    precomputed = atlas_validate._check_native_payloads(asserted, inventory)
    atlas_validate._check_node_digests(graphs, inventory, precomputed)
    atlas_validate._check_source_accounting(asserted, accounting, inventory)
    atlas_validate._check_counts(manifest, graphs, inventory)


def test_release_metadata_is_resolved_once_per_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    inventory = atlas_validate._check_graph_roles(graphs)
    releases = inventory.nodes(ATLAS.AtlasRelease)
    release_predicates = {
        ATLAS.semanticRing,
        ATLAS.resourceProfile,
        ATLAS.inScheme,
    }
    original_one = atlas_validate._one
    calls: dict[tuple[URIRef, URIRef], int] = {}

    def counted_one(
        graph: Graph,
        subject: URIRef,
        predicate: URIRef,
        *,
        code: str,
    ) -> Any:
        if subject in releases and predicate in release_predicates:
            key = (subject, predicate)
            calls[key] = calls.get(key, 0) + 1
        return original_one(graph, subject, predicate, code=code)

    monkeypatch.setattr(atlas_validate, "_one", counted_one)
    atlas_validate._check_release_membership(asserted, inventory)

    assert calls == {
        (release, predicate): 1
        for release in releases
        for predicate in release_predicates
    }


def test_general_node_digest_pass_does_not_globally_sort_carriers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    _, graphs, _ = _load_valid_graphs()
    inventory = atlas_validate._check_graph_roles(graphs)
    original_sorted = builtins.sorted

    def reject_node_set_sort(iterable: Any, *args: object, **kwargs: object) -> Any:
        if isinstance(iterable, (set, frozenset)):
            pytest.fail("node digest validation must not globally sort carrier sets")
        return original_sorted(iterable, *args, **kwargs)

    monkeypatch.setattr(atlas_validate, "sorted", reject_node_set_sort, raising=False)
    atlas_validate._check_node_digests(graphs, inventory)


def test_policy_digest_is_reused_by_general_node_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    inventory = atlas_validate._check_graph_roles(graphs)
    precomputed = atlas_validate._check_native_payloads(asserted, inventory)
    policies = inventory.nodes(ATLAS.EditorialPolicy)
    original = atlas_validate.rdf_node_digest

    def reject_policy_rehash(graph: Graph, node: URIRef) -> str:
        if node in policies:
            raise AssertionError("policy digest was already computed for identity validation")
        return original(graph, node)

    monkeypatch.setattr(atlas_validate, "rdf_node_digest", reject_policy_rehash)
    atlas_validate._check_node_digests(graphs, inventory, precomputed)


def test_empty_derived_graph_skips_assertion_indexes() -> None:
    class UnreadableAssertions(Mapping):
        def __getitem__(self, key: object) -> object:
            raise AssertionError(f"empty derived validation read assertion key {key}")

        def __iter__(self) -> Any:
            raise AssertionError("empty derived validation iterated assertions")

        def __len__(self) -> int:
            raise AssertionError("empty derived validation counted assertions")

    current = UnreadableAssertions()
    derived = Graph()
    empty_nodes: frozenset[URIRef] = frozenset()
    exact_index = atlas_validate.ExactMatchIndex(
        component_by_node={},
        component_sizes=(),
        directed_direct_counts=(),
        direct_triples=frozenset(),
    )

    atlas_validate._check_derived(
        Graph(),
        Graph(),
        derived,
        current,
        empty_nodes,
    )
    assert (
        atlas_validate._check_reasoning_isolation(
            derived,
            current,
            exact_index,
            empty_nodes,
        )
        == 0
    )


def test_assertion_validation_does_not_materialize_empty_successor_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    inventory = atlas_validate._check_graph_roles(graphs)
    original_defaultdict = atlas_validate.defaultdict
    created: list[Any] = []

    def tracked_defaultdict(*args: object, **kwargs: object) -> Any:
        result = original_defaultdict(*args, **kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(atlas_validate, "defaultdict", tracked_defaultdict)
    atlas_validate._validate_assertions(asserted, inventory)

    successors = created[0]
    expected_predecessors = set(asserted.objects(None, ATLAS.supersedes))
    assert set(successors) == expected_predecessors


def test_assertion_support_uses_compact_immutable_sequences() -> None:
    _, graphs, _ = _load_valid_graphs()
    inventory = atlas_validate._check_graph_roles(graphs)

    supported = atlas_validate._validate_assertions(graphs["asserted"], inventory)

    assert supported
    assert all(isinstance(assertions, tuple) for assertions in supported.values())


def test_skos_integrity_builds_exact_index_in_its_existing_pass() -> None:
    class OnePassCurrent(dict):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError("SKOS integrity rescanned the current-relation map")
            return super().__iter__()

    current = OnePassCurrent()

    exact_index = atlas_validate._check_skos_integrity(current)

    assert current.iterations == 1
    assert exact_index.inferred_count == 0


def test_validate_distribution_analyzes_assertions_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = _write_packed_distribution(tmp_path / "distribution")
    original = atlas_validate._validate_assertions
    analyses: list[Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]]] = []

    def counted(
        asserted: Graph,
        inventory: atlas_validate.SemanticInventory | None = None,
    ) -> Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]]:
        result = original(asserted, inventory)
        analyses.append(result)
        return result

    monkeypatch.setattr(atlas_validate, "_validate_assertions", counted)
    analysis_argument = {
        "_check_skos_integrity": 0,
        "_check_projection": 2,
        "_check_derived": 3,
        "_check_reasoning_isolation": 1,
    }
    for consumer_name, argument_index in analysis_argument.items():
        consumer = getattr(atlas_validate, consumer_name)

        def checked_consumer(
            *args: object,
            _consumer: Any = consumer,
            _argument_index: int = argument_index,
            **kwargs: object,
        ) -> Any:
            assert analyses
            assert args[_argument_index] is analyses[0]
            return _consumer(*args, **kwargs)

        monkeypatch.setattr(atlas_validate, consumer_name, checked_consumer)

    atlas_validate.validate_distribution(distribution)

    assert len(analyses) == 1


@pytest.mark.parametrize("case", ("exact", "missing", "substitution", "extra"))
def test_projection_comparison_uses_membership_and_preserves_rejection(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = (URIRef("urn:s:1"), URIRef("urn:p"), URIRef("urn:o:1"))
    second = (URIRef("urn:s:2"), URIRef("urn:p"), URIRef("urn:o:2"))
    extra = (URIRef("urn:s:3"), URIRef("urn:p"), URIRef("urn:o:3"))
    expected = (first, second)
    actual_by_case = {
        "exact": expected,
        "missing": (first,),
        "substitution": (first, extra),
        "extra": (*expected, extra),
    }

    class StreamingProjection:
        def __init__(self, triples: tuple[tuple[URIRef, URIRef, URIRef], ...]) -> None:
            self.triples = frozenset(triples)
            self.lookups: list[tuple[URIRef, URIRef, URIRef]] = []
            self.iterations = 0

        def __contains__(self, triple: object) -> bool:
            assert isinstance(triple, tuple)
            self.lookups.append(triple)
            return triple in self.triples

        def __iter__(self):
            self.iterations += 1
            return iter(self.triples)

    def fail_graph_allocation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("projection comparison must not allocate an expected Graph")

    probe = StreamingProjection(actual_by_case[case])
    supported = {first: frozenset(), second: frozenset()}
    monkeypatch.setattr(
        atlas_validate,
        "_expected_projection_triples",
        lambda *_args: iter(expected),
    )
    monkeypatch.setattr(atlas_validate, "Graph", fail_graph_allocation)
    if case == "exact":
        atlas_validate._check_projection(Graph(), probe, supported)  # type: ignore[arg-type]
    else:
        with pytest.raises(atlas_validate.AtlasValidationError) as raised:
            atlas_validate._check_projection(Graph(), probe, supported)  # type: ignore[arg-type]
        assert raised.value.code == "dataset.projection"

    assert probe.lookups == list(expected)
    assert probe.iterations == 1


def test_reasoning_isolation_sends_only_mapping_triples_to_owl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = URIRef("urn:ref:atlas-test:a")
    middle = URIRef("urn:ref:atlas-test:b")
    target = URIRef("urn:ref:atlas-test:c")
    first_mapping = (source, SKOS.exactMatch, middle)
    second_mapping = (middle, SKOS.exactMatch, target)
    inferred_mapping = (source, SKOS.exactMatch, target)
    native = (source, SKOS.related, target)
    cross_ring = (source, ATLAS.hasIndexedSubject, target)
    first_assertion = URIRef("urn:ref:atlas-test:assertion:mapping-1")
    second_assertion = URIRef("urn:ref:atlas-test:assertion:mapping-2")
    current = {
        first_mapping: frozenset({first_assertion}),
        second_mapping: frozenset({second_assertion}),
        native: frozenset({URIRef("urn:ref:atlas-test:assertion:native")}),
        cross_ring: frozenset(
            {URIRef("urn:ref:atlas-test:assertion:cross-ring")}
        ),
    }
    derived = Graph()
    derived_node = URIRef("urn:ref:atlas-test:derived")
    derived.add((derived_node, RDF.type, ATLAS.DerivedRelation))
    derived.add((derived_node, ATLAS.relationSubject, source))
    derived.add((derived_node, ATLAS.relationPredicate, SKOS.exactMatch))
    derived.add((derived_node, ATLAS.relationObject, target))
    derived.add((derived_node, ATLAS.derivedFromAssertion, first_assertion))
    derived.add((derived_node, ATLAS.derivedFromAssertion, second_assertion))
    captured: dict[str, Any] = {}

    class CapturingClosure:
        def __init__(self, semantics: object, **kwargs: object) -> None:
            captured["semantics"] = semantics
            captured["kwargs"] = kwargs

        def expand(self, graph: Graph) -> None:
            captured["input"] = set(graph)
            graph.add(inferred_mapping)

    monkeypatch.setattr(atlas_validate, "DeductiveClosure", CapturingClosure)
    assert atlas_validate._check_reasoning_isolation(derived, current) == 7
    assert captured["semantics"] is atlas_validate.OWLRL_Semantics
    assert captured["kwargs"] == {
        "axiomatic_triples": False,
        "datatype_axioms": False,
    }
    assert captured["input"] == {
        first_mapping,
        second_mapping,
        (SKOS.exactMatch, RDF.type, OWL.TransitiveProperty),
        (SKOS.exactMatch, RDF.type, OWL.SymmetricProperty),
    }


@pytest.mark.parametrize(
    ("edges", "expected"),
    (
        ((("a", "b"),), 3),
        ((("a", "b"), ("b", "a")), 2),
        ((("a", "b"), ("c", "d")), 6),
        ((("a", "b"), ("b", "c"), ("a", "c")), 6),
        ((("a", "a"),), 0),
    ),
)
def test_exact_match_inference_count_uses_component_arithmetic(
    edges: tuple[tuple[str, str], ...],
    expected: int,
) -> None:
    current = {
        (URIRef(f"urn:{subject}"), SKOS.exactMatch, URIRef(f"urn:{obj}")): frozenset(
            {URIRef(f"urn:assertion:{index}")}
        )
        for index, (subject, obj) in enumerate(edges)
    }

    assert atlas_validate._build_exact_match_index(current).inferred_count == expected
    assert atlas_validate._check_reasoning_isolation(Graph(), current) == expected


def test_exact_match_count_deduplicates_multiple_supporting_assertions() -> None:
    triple = (URIRef("urn:a"), SKOS.exactMatch, URIRef("urn:b"))
    current = {
        triple: frozenset({URIRef("urn:assertion:1"), URIRef("urn:assertion:2")})
    }

    assert atlas_validate._build_exact_match_index(current).inferred_count == 3


def test_hierarchy_queries_handle_deep_chain_without_recursion() -> None:
    nodes = [URIRef(f"urn:node:{index}") for index in range(2_000)]
    hierarchy = {
        node: {nodes[index + 1]}
        for index, node in enumerate(nodes[:-1])
    }
    pair = atlas_validate._canonical_pair(nodes[0], nodes[-1])

    assert atlas_validate._hierarchy_connected_pairs(hierarchy, {pair}) == {pair}


def test_hierarchy_reachability_matches_positive_path_reference() -> None:
    random = Random(7)
    for node_count in range(1, 25):
        nodes = [URIRef(f"urn:node:{index}") for index in range(node_count)]
        query_nodes = [*nodes, URIRef("urn:absent:a"), URIRef("urn:absent:b")]
        for _ in range(80):
            hierarchy: dict[URIRef, set[URIRef]] = {}
            for _ in range(random.randrange(node_count * 3 + 1)):
                source = random.choice(nodes)
                hierarchy.setdefault(source, set()).add(random.choice(nodes))
            pairs = {
                atlas_validate._canonical_pair(
                    random.choice(query_nodes),
                    random.choice(query_nodes),
                )
                for _ in range(20)
            }

            assert atlas_validate._hierarchy_connected_pairs(hierarchy, pairs) == (
                _reference_hierarchy_connected_pairs(hierarchy, pairs)
            )


def test_hierarchy_reachability_preserves_positive_cycle_semantics() -> None:
    a, b, c, self_loop, absent = (
        URIRef("urn:a"),
        URIRef("urn:b"),
        URIRef("urn:c"),
        URIRef("urn:self"),
        URIRef("urn:absent"),
    )
    hierarchy = {
        a: {b},
        b: {c},
        c: {a},
        self_loop: {self_loop},
    }
    pairs = {
        (a, c),
        (a, a),
        (self_loop, self_loop),
        (absent, absent),
        (c, absent),
    }

    assert atlas_validate._hierarchy_connected_pairs(hierarchy, pairs) == {
        atlas_validate._canonical_pair(a, c),
        (a, a),
        (self_loop, self_loop),
    }


def test_hierarchy_reachability_crosses_bitset_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = URIRef("urn:hub")
    sources = [URIRef(f"urn:source:{index}") for index in range(4)]
    targets = [URIRef(f"urn:target:{index}") for index in range(3)]
    hierarchy = {
        **{source: {hub} for source in sources},
        hub: set(targets),
    }
    pairs = {
        atlas_validate._canonical_pair(source, target)
        for source in sources
        for target in targets
    }
    monkeypatch.setattr(atlas_validate, "HIERARCHY_REACHABILITY_BATCH_BITS", 2)

    assert atlas_validate._hierarchy_connected_pairs(
        hierarchy,
        iter(sorted(pairs, reverse=True)),
    ) == pairs


def test_skos_hierarchy_conflict_diagnostic_keeps_sorted_pair_order() -> None:
    a, b, c, d = map(URIRef, ("urn:a", "urn:b", "urn:c", "urn:d"))
    current = {
        (c, SKOS.related, d): (),
        (c, SKOS.broader, d): (),
        (a, SKOS.related, b): (),
        (a, SKOS.broader, b): (),
    }

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_skos_integrity(current)

    assert raised.value.code == "dataset.skos-integrity"
    assert raised.value.detail == f"SKOS S27 transitive hierarchy conflict for {(a, b)}"


def test_thesaurus_related_diagnostic_keeps_sorted_pair_order() -> None:
    a, b, c, d, child, parent = map(
        URIRef,
        ("urn:a", "urn:b", "urn:c", "urn:d", "urn:child", "urn:parent"),
    )
    current = {
        (c, ATLAS.thesaurusRelated, d): (),
        (a, ATLAS.thesaurusRelated, b): (),
        (child, SKOS.broader, parent): (),
    }

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_skos_integrity(current)

    assert raised.value.code == "dataset.skos-integrity"
    assert raised.value.detail == (
        "atlas:thesaurusRelated is allowed only for an authored associative "
        f"link with a transitive hierarchy conflict: {(a, b)}"
    )


def test_parser_counts_graphs_without_rescanning_the_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(
        b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
        b"<urn:b> <urn:p> <urn:o> <urn:g> .\n"
    )
    manifest = {"graphs": [{"role": "asserted", "id": "urn:g", "quadCount": 2}]}

    def fail_rescan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("graph counts and canonical terms must be collected during parsing")

    monkeypatch.setattr(Dataset, "quads", fail_rescan)
    dataset, graphs = atlas_validate._parse_dataset(dataset_path, manifest)

    assert len(graphs["asserted"]) == 2
    assert graphs["asserted"].store is dataset.store


def test_dataset_digest_is_verified_during_the_required_line_scan(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    payload = b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
    dataset_path.write_bytes(payload)
    expected = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert atlas_validate._check_serialized_nquads_profile(
        dataset_path,
        expected_digest=expected,
    ) == 1

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_serialized_nquads_profile(
            dataset_path,
            expected_digest="sha256:" + "0" * 64,
        )

    assert raised.value.code == "distribution.digest"


def test_dataset_parser_preserves_typed_literal_lexical_form_without_global_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_text(
        '<urn:s> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> <urn:g> .\n',
        encoding="utf-8",
    )
    manifest = {
        "graphs": [
            {"role": "asserted", "id": "urn:g", "quadCount": 1},
        ]
    }

    monkeypatch.setattr(rdflib, "NORMALIZE_LITERALS", True)
    _, graphs = atlas_validate._parse_dataset(dataset_path, manifest)
    literal = next(graphs["asserted"].objects(URIRef("urn:s"), URIRef("urn:p")))

    assert isinstance(literal, Literal)
    assert str(literal) == "01"
    assert rdflib.NORMALIZE_LITERALS is True


def test_atlas_shapes_have_no_per_focus_sparql_constraints() -> None:
    shapes = Graph().parse(BINDING_ROOT / "shapes" / "atlas.shacl.ttl", format="turtle")
    shacl = Namespace("http://www.w3.org/ns/shacl#")

    assert not list(shapes.triples((None, shacl.sparql, None)))
    assert not list(shapes.triples((None, shacl.select, None)))


def test_cli_heap_freeze_happens_after_output_flush_and_not_inside_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    class FlushRecorder:
        def __init__(self, name: str) -> None:
            self.name = name

        def flush(self) -> None:
            calls.append(self.name)

    monkeypatch.setattr(atlas_validate, "validate_binding", lambda: {"ok": True})
    monkeypatch.setattr(atlas_validate.gc, "freeze", lambda: calls.append("freeze"))

    assert atlas_validate.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
    assert calls == []

    monkeypatch.setattr(atlas_validate.sys, "stdout", FlushRecorder("stdout"))
    monkeypatch.setattr(atlas_validate.sys, "stderr", FlushRecorder("stderr"))
    atlas_validate._prepare_cli_heap_for_exit()

    assert calls == ["stdout", "stderr", "freeze"]

    calls.clear()
    monkeypatch.setattr(
        atlas_validate,
        "main",
        lambda: calls.append("main") or 7,
    )
    monkeypatch.setattr(
        atlas_validate,
        "_prepare_cli_heap_for_exit",
        lambda: calls.append("prepare-exit"),
    )

    assert atlas_validate._run_cli() == 7
    assert calls == ["main", "prepare-exit"]


def test_the_binding_tools_import_nothing_from_the_refspec_package() -> None:
    """A consumer copies `bindings/atlas/3.0/` and validates a distribution offline.

    `rdf_canonical.ntriples_term` inlines the credentials refusal that
    `refspec.registry.infrastructure.identifier_validation.absolute_uri_issue`
    already implements, and the note beside it says why: this boundary. The
    note is only worth its space while something breaks when it is crossed.
    """

    import ast

    for name in ("validate.py", "build_fixtures.py", "rdf_canonical.py"):
        tree = ast.parse((BINDING_ROOT / "tools" / name).read_text(encoding="utf-8"))
        imported = {
            module.split(".", 1)[0]
            for node in ast.walk(tree)
            for module in (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
        }
        assert "refspec" not in imported, f"{name} imports the RefSpec package"


def test_the_binding_and_the_package_reject_the_same_credentialed_iris() -> None:
    """The inlined credentials refusal must stay term for term the package's.

    A copy with nothing checking that it still agrees is drift waiting to
    happen; this is that check.
    """

    from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue

    probes = (
        "https://example.org/x",
        "https://user:pass@example.org/x",
        "https://user@example.org/x",
        "https://:pass@example.org/x",
        "https://@example.org/x",
        "http://user:pass@example.org:8080/a?b=c#d",
        "ftp://anonymous:secret@ftp.example.org/pub",
        "urn:ref:atlas:pack:abc",
        "urn:ref:user:pass@example.org",
        "https://example.org/path@with-at",
        "https://example.org/x?q=a@b",
        "https://example.org/x#frag@ment",
        "https://[::1]/x",
        "https://user:pass@[::1]:9/x",
    )
    package = {probe: absolute_uri_issue(probe) == "credentials" for probe in probes}
    binding = {}
    for probe in probes:
        try:
            atlas_validate.ntriples_term(URIRef(probe))
        except atlas_validate.AtlasValidationError as exc:
            binding[probe] = exc.code == "rdf.term" and "credentials" in exc.detail
        else:
            binding[probe] = False

    assert binding == package
    assert any(package.values()) and not all(package.values())

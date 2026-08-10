from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from rdflib import Namespace

from refspec.atlas.compact_pack import CompactPackHeader, CompactRecordRole, write_compact_record_pack
from refspec.atlas.duckdb_view import AtlasDuckDBView, AtlasDuckDBViewError
from refspec.atlas.explorer import (
    atlas_explorer_facets,
    atlas_parquet_resource,
    build_atlas_explorer_model,
    build_atlas_explorer_static_shards,
    open_atlas_explorer,
    render_atlas_parquet_explorer,
    render_atlas_v3_explorer,
    search_atlas_parquet,
)

RKAF = Namespace("https://rulespec.org/ns/v1#")

from refspec.atlas.explorer_data import AtlasExplorerData
from refspec.atlas.explorer_frontend import render_atlas_explorer_frontend
from refspec.atlas.parquet_search_view import (
    AtlasParquetSearchViewError,
    build_atlas_parquet_search_view,
    verify_atlas_parquet_search_view,
)
from refspec.atlas.parquet_view import (
    AtlasParquetViewError,
    build_atlas_parquet_view,
    verify_atlas_parquet_view,
)
from refspec.atlas.registry_claim_input import (
    AtlasRegistryClaimInput,
    adapt_registry_claim_release,
    validate_atlas_parquet_registry_claims,
)
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.registry_claim_release import (
    RegistryClaim,
    RegistryRawInput,
    build_registry_claim_release,
)

_D1 = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64
_D3 = "sha256:" + "3" * 64
_D4 = "sha256:" + "4" * 64


def _payload_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)[:-1]).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> bytes:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _fixture_distribution(
    root: Path,
    *,
    source_native_payload: Mapping[str, object] | None = None,
    source_digest: str = _D3,
    include_alias: bool = False,
) -> str:
    release = "urn:test:atlas-release"
    source_record = "urn:ref:atlas-source-record:" + "5" * 64
    statement = "urn:ref:atlas-assertion:" + "3" * 64
    rows = {
        CompactRecordRole.RESOURCE: {
            "id": "urn:test:resource",
            "release": release,
            "scheme": "urn:test:scheme",
            "semanticRing": "subject",
            "resourceProfile": "conceptScheme",
            "sourceRecord": source_record,
            "definition": "A test resource.",
            "notes": ["A note."],
            "notations": ["T-1"],
            "recordStatus": "active",
            "contentDigest": _D1,
        },
        CompactRecordRole.LABEL: {
            "id": "urn:ref:atlas-label:" + "7" * 64,
            "resource": "urn:test:resource",
            "labelRole": "preferred",
            "value": "Test resource",
            "language": "en",
            "release": release,
            "sourceRecord": source_record,
            "contentDigest": _D2,
        },
        CompactRecordRole.STATEMENT: {
            "id": statement,
            "statementType": "NativeRelationAssertion",
            "subject": "urn:test:resource",
            "predicate": "http://www.w3.org/2004/02/skos/core#broader",
            "object": "urn:test:parent",
            "sourceRelease": release,
            "targetRelease": release,
            "policy": "urn:ref:atlas-policy:" + "6" * 64,
            "assertedAt": "2026-08-07T00:00:00+00:00",
            "assertionStatus": "current",
            "assertionIdentityDigest": _D3,
            "semanticRing": "subject",
            "contentDigest": _D4,
        },
        CompactRecordRole.EVIDENCE_BINDING: {
            "id": "urn:ref:atlas-evidence:" + "2" * 64,
            "statement": statement,
            "sourceRecord": source_record,
            "evidenceSourceDigest": _D1,
            "attestor": "urn:test:reviewer",
            "attestorKind": "urn:test:attestor-kind",
            "assertionOrigin": "urn:test:origin",
            "epistemicBasis": "urn:test:basis",
            "evidenceRole": "urn:test:role",
            "evidentiaryFunction": "urn:test:function",
            "decision": "urn:test:approved",
            "attestedAt": "2026-08-07T00:00:00+00:00",
            "contentDigest": _D2,
        },
        CompactRecordRole.SOURCE_RECORD: {
            "id": source_record,
            "sourceRelease": "urn:test:source-release",
            "sourceDigest": source_digest,
            "sourceLocator": "https://example.test/source",
            "nativePayload": (
                {"publisher": "Example", "values": [1, 2]}
                if source_native_payload is None
                else source_native_payload
            ),
            "representsResource": "urn:test:resource",
            "contentDigest": _D4,
        },
        CompactRecordRole.RELEASE: {
            "id": release,
            "releaseType": "AtlasRelease",
            "identifier": "test-release",
            "issued": "2026-08-07",
            "resourceProfile": "conceptScheme",
            "semanticRing": "subject",
            "scheme": "urn:test:scheme",
            "membershipMode": "complete",
            "contentDigest": _D1,
        },
        CompactRecordRole.IDENTIFIER: {
            "id": "urn:ref:atlas-identifier:" + "8" * 64,
            "identifierValue": "T-1",
            "identifierScheme": "urn:test:identifier-scheme",
            "identifies": "urn:test:resource",
            "sourceRecord": source_record,
            "contentDigest": _D2,
        },
        CompactRecordRole.LIFECYCLE_EVENT: {
            "id": "urn:test:event",
            "eventSubject": "urn:test:resource",
            "eventType": "urn:test:created",
            "eventAt": "2026-08-07T00:00:00+00:00",
            "sourceRecords": [source_record],
            "toRelease": release,
            "contentDigest": _D3,
        },
    }
    compact_packs = []
    for role, row in rows.items():
        records = [row]
        if include_alias and role is CompactRecordRole.LABEL:
            records.append(
                {
                    "id": "urn:ref:atlas-label:" + "9" * 64,
                    "resource": "urn:test:resource",
                    "labelRole": "alternate",
                    "value": "Fixture alias",
                    "language": "en",
                    "release": release,
                    "sourceRecord": source_record,
                    "contentDigest": _D3,
                }
            )
        inventory = write_compact_record_pack(
            root,
            CompactPackHeader(role=role.value, path=f"packs/compact/{role.value.casefold()}.jsonl.zst"),
            records,
            compression_level=1,
        )
        compact_packs.append(inventory.to_dict())
    compact_packs.sort(key=lambda row: row["path"])
    empty_inventory_digest = _payload_digest([])
    binding_digest = "sha256:" + "a" * 64
    summary: dict[str, object] = {
        "assertedInventoryDigest": empty_inventory_digest,
        "bindingBundleDigest": binding_digest,
        "compactPackCount": len(compact_packs),
        "compactPackInventoryDigest": sha256_digest(canonical_json_bytes(compact_packs)),
        "compactPacks": compact_packs,
        "distributionId": "urn:test:atlas-distribution",
        "type": "AtlasConstructionSummary",
        "version": "3.0",
    }
    summary["canonicalPayloadDigest"] = _payload_digest(summary)
    summary_raw = _write_json(root / "atlas-construction-summary.json", summary)
    member = {
        "byteLength": len(summary_raw),
        "digest": sha256_digest(summary_raw),
        "mediaType": "application/json",
        "path": "atlas-construction-summary.json",
        "role": "constructionSummary",
    }
    manifest: dict[str, object] = {
        "binding": {
            "bindingBundleDigest": binding_digest,
            "ontologyDigest": "sha256:" + "b" * 64,
        },
        "counts": {},
        "createdAt": "2026-08-07T00:00:00+00:00",
        "distributionId": "urn:test:atlas-distribution",
        "format": "refspec-atlas-packed-nquads-3.0",
        "graphs": [
            {
                "id": "urn:ref:atlas:graph:v3:asserted",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "asserted",
            },
            {
                "id": "urn:ref:atlas:graph:v3:projection",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "projection",
            },
            {
                "id": "urn:ref:atlas:graph:v3:derived",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "derived",
            },
        ],
        "members": [member],
        "packs": [],
        "schemaVersion": "3.0",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = _payload_digest(manifest)
    manifest_raw = _write_json(root / "atlas-manifest.json", manifest)
    return sha256_digest(manifest_raw)


def test_builds_and_verifies_typed_lossless_logical_view(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    output = tmp_path / "view"

    manifest = build_atlas_parquet_view(source, output, expected_manifest_digest=source_pin)

    assert set(manifest["counts"]) == {role.value for role in CompactRecordRole}
    assert set(manifest["counts"].values()) == {1}
    assert manifest["status"] == {
        "canonicalAtlas": False,
        "containsExactRdfTable": False,
        "derivedView": True,
        "expansion": "not_used",
        "logicalRecordsPreserved": True,
    }
    resources = pq.read_table(output / "tables/resources.parquet").to_pylist()
    assert resources[0]["id"] == "urn:test:resource"
    assert resources[0]["content_digest"] == bytes.fromhex("1" * 64)
    source_records = pq.read_table(output / "tables/source-records.parquet").to_pylist()
    assert source_records[0]["native_payload"] == b'{"publisher":"Example","values":[1,2]}'
    view_pin = sha256_digest((output / "view-manifest.json").read_bytes())
    assert verify_atlas_parquet_view(output, expected_manifest_digest=view_pin) == manifest


def test_registry_claim_bundle_round_trips_through_atlas_parquet(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "claim-source.ttl"
    raw.write_bytes(b"claim source\n")
    source_digest = sha256_digest(raw.read_bytes())
    release_id = "urn:test:registry-claim-release"
    recipe_id = "urn:test:registry-claim-recipe"
    claim = RegistryClaim(
        release_id=release_id,
        subject="https://example.test/concept",
        predicate="http://www.w3.org/2004/02/skos/core#prefLabel",
        object_kind="literal",
        lexical_value=" Exact label ",
        language="en",
        source_record_id="https://example.test/concept",
        source_locator="https://example.test/source",
        source_path="raw/source.ttl#claim=1",
        source_digest=source_digest,
        origin="observed",
        recipe_id=recipe_id,
    )
    bundle = build_registry_claim_release(
        tmp_path / "claim-release",
        release_id=release_id,
        release_key="claim-test",
        issued="2026-08-07",
        release_scope={"complete": True, "mode": "completeCapture"},
        language_scope={"included": ["en"], "mode": "englishOnly"},
        recipes=({"id": recipe_id},),
        claims=(claim,),
        raw_inputs=(
            RegistryRawInput(
                path=raw,
                logical_path="raw/source.ttl",
                source_locator="https://example.test/source",
            ),
        ),
    )
    input_ = AtlasRegistryClaimInput(
        path=bundle.root,
        expected_manifest_digest=bundle.manifest_digest,
    )
    payload = adapt_registry_claim_release(input_).records[0].native_payload
    source = tmp_path / "atlas"
    source.mkdir()
    atlas_pin = _fixture_distribution(
        source,
        source_native_payload=payload,
        source_digest=source_digest,
    )
    atlas_view = tmp_path / "atlas-parquet"
    manifest = build_atlas_parquet_view(
        source,
        atlas_view,
        expected_manifest_digest=atlas_pin,
    )
    view_pin = sha256_digest(
        (atlas_view / "view-manifest.json").read_bytes()
    )

    report = validate_atlas_parquet_registry_claims(
        input_,
        atlas_view,
        expected_atlas_view_manifest_digest=view_pin,
    )

    assert manifest["counts"]["SourceRecord"] == 1
    assert report.passed is True
    assert report.exact_count == 1


def test_rebuild_is_byte_stable(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    first = build_atlas_parquet_view(source, tmp_path / "first", expected_manifest_digest=source_pin)
    second = build_atlas_parquet_view(source, tmp_path / "second", expected_manifest_digest=source_pin)
    assert first == second
    assert [row["sha256"] for row in first["members"]] == [row["sha256"] for row in second["members"]]


def test_refuses_input_manifest_drift_and_output_tampering(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    with pytest.raises(AtlasParquetViewError, match="digest differs"):
        build_atlas_parquet_view(source, tmp_path / "wrong", expected_manifest_digest=_D1)

    output = tmp_path / "view"
    build_atlas_parquet_view(source, output, expected_manifest_digest=source_pin)
    view_pin = sha256_digest((output / "view-manifest.json").read_bytes())
    with (output / "tables/resources.parquet").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(AtlasParquetViewError, match="member bytes differ"):
        verify_atlas_parquet_view(output, expected_manifest_digest=view_pin)


def test_refuses_extra_input_or_view_member(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    (source / "extra.txt").write_text("extra")
    with pytest.raises(AtlasParquetViewError, match="membership is not closed"):
        build_atlas_parquet_view(source, tmp_path / "view", expected_manifest_digest=source_pin)

    source = tmp_path / "atlas-2"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    output = tmp_path / "view-2"
    build_atlas_parquet_view(source, output, expected_manifest_digest=source_pin)
    view_pin = sha256_digest((output / "view-manifest.json").read_bytes())
    (output / "extra.txt").write_text("extra")
    with pytest.raises(AtlasParquetViewError, match="membership is not closed"):
        verify_atlas_parquet_view(output, expected_manifest_digest=view_pin)


def test_compact_search_view_preserves_graph_and_omits_native_payload(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    build_atlas_parquet_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())

    compact = tmp_path / "compact"
    manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)

    assert "SourceRecord.nativePayload" in manifest["status"]["omittedFields"]
    assert manifest["status"]["graphFactsPreserved"] is True
    source_schema = pq.read_schema(compact / "tables/source-records.parquet")
    assert "native_payload" not in source_schema.names
    statement_row = pq.read_table(compact / "tables/statements.parquet").to_pylist()[0]
    assert statement_row["id"] == "urn:ref:atlas-assertion:" + "3" * 64
    assert statement_row["subject"] == "urn:test:resource"
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    assert verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin) == manifest


def test_compact_search_view_refuses_member_tampering(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    build_atlas_parquet_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    with (compact / "tables/statements.parquet").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(AtlasParquetSearchViewError, match="member bytes differ"):
        verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin)


def test_explorer_reads_compact_parquet_view_without_rdf(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, include_alias=True)
    full = tmp_path / "full"
    build_atlas_parquet_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    opened = open_atlas_explorer(compact, trusted_manifest_digest=compact_pin)
    assert isinstance(opened, AtlasExplorerData)
    assert isinstance(opened, AtlasDuckDBView)
    assert opened.database_path.parent != compact
    assert opened.table_name(CompactRecordRole.RESOURCE) == "atlas_resources"
    assert opened.query_rows("SELECT count(*) AS count FROM atlas_resources") == [{"count": 1}]
    assert opened.query_arrow("SELECT id FROM atlas_resources").to_pylist() == [
        {"id": "urn:test:resource"}
    ]
    bundle = build_atlas_explorer_static_shards(
        opened,
        tmp_path / "shards",
        url_prefix="shards",
    )
    model = build_atlas_explorer_model(opened, full_corpus=bundle)
    rendered = render_atlas_v3_explorer(model)

    assert model["distribution"]["manifestDigest"] == compact_pin
    assert model["summary"]["availableResources"] == 1
    assert model["resources"][0]["displayLabel"] == "Test resource"
    assert model["assertedRelations"][0]["predicateLabel"] == "broader"
    assert bundle["counts"]["resources"] == 1
    assert "Test resource" in rendered
    search_result = search_atlas_parquet(opened, "test")[0]
    assert search_result["id"] == "urn:test:resource"
    assert isinstance(search_result["score"], float)
    assert search_atlas_parquet(opened, "fixture alias")[0]["id"] == "urn:test:resource"
    assert search_atlas_parquet(opened, "T-1")[0]["id"] == "urn:test:resource"
    assert search_atlas_parquet(
        opened,
        "test",
        releases=("urn:test:atlas-release",),
    )[0]["id"] == "urn:test:resource"
    assert search_atlas_parquet(opened, "test", releases=("urn:test:other-release",)) == []
    assert search_atlas_parquet(opened, "test", offset=1) == []
    assert search_atlas_parquet(opened, "", offset=1) == []
    with pytest.raises(AtlasDuckDBViewError, match="offset"):
        search_atlas_parquet(opened, "test", offset=-1)
    assert atlas_explorer_facets(opened)["rings"] == [{"count": 1, "id": "subject"}]
    assert atlas_explorer_facets(opened)["graphs"] == [
        {
            "authority": "Verified Atlas relation records",
            "description": "All relations retained by the compact search view.",
            "relationCount": 1,
            "role": "asserted",
        }
    ]
    detail = atlas_parquet_resource(opened, "urn:test:resource")
    assert detail["relations"][0]["evidence_count"] == 1
    assert detail["relations"][0]["evidence"][0]["decision"] == "urn:test:approved"
    assert detail["relations"][0]["evidence"][0]["sourceLocator"] == "https://example.test/source"
    assert detail["relations"][0]["subject_label"] == "Test resource"
    assert detail["relations"][0]["object_label"] == "parent"
    assert atlas_explorer_facets(opened)["start"] == "urn:test:resource"
    database_path = opened.database_path
    opened.close()
    assert not database_path.exists()


def test_parquet_explorer_renders_graph_as_primary_workspace() -> None:
    rendered = render_atlas_parquet_explorer()

    assert rendered == render_atlas_explorer_frontend()
    assert 'id="graph-workspace"' in rendered
    assert "class GraphView" in rendered
    assert 'this.canvas=this.element.querySelector("canvas")' in rendered
    assert "this.nodes=new Map()" in rendered
    assert "async function addGraph(id)" in rendered
    assert "function removeGraph(id)" in rendered
    assert "layout(){" in rendered
    assert "drawnEdges(){" in rendered
    assert "lineTo(to.x,to.y)" in rendered
    assert "Browse every resource or narrow the list" in rendered
    assert 'id="more-results"' not in rendered
    assert "Show more" not in rendered
    assert 'id="search-status"' in rendered
    assert 'searchResults.addEventListener("scroll"' in rendered
    assert "app.searchHasMore" in rendered
    assert "offset:String(app.searchOffset)" in rendered
    assert 'input type="checkbox" data-resource=' in rendered
    assert 'input.checked?addGraph(input.dataset.resource):removeGraph(input.dataset.resource)' in rendered
    assert "await addGraph(app.startId)" not in rendered
    assert "[hidden]{display:none!important}" in rendered
    assert 'id="graph-catalog"' in rendered
    assert 'data-graph-role="${esc(row.role)}"' in rendered
    assert "Empty in this release" in rendered
    assert "Fit all views" in rendered
    assert 'id="clear-graphs"' in rendered
    assert 'aria-label="Remove ${esc(labelOf(this.root))} view"' in rendered
    assert "RefSpec vocabulary Atlas" in rendered
    assert "Explore the Atlas" in rendered
    assert "Concept inspector" in rendered
    assert "equivalent assertions" in rendered
    assert "Vocabulary relations" in rendered
    assert "Cross-vocabulary mappings" in rendered
    assert "Source assignments" in rendered
    assert "function relationMeaning(edge)" in rendered
    assert "function relationWhy(edge)" in rendered
    assert "controls-resizer" in rendered
    assert 'placeholder="Label, alias, notation, or IRI"' in rendered
    assert "Relation ID" in rendered
    assert "Property ID" in rendered
    assert "Federal Register topics" in rendered
    assert "compact Parquet" not in rendered
    assert ">NativeRelationAssertion<" not in rendered
    assert "<table" not in rendered

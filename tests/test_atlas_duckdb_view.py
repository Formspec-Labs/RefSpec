"""Unit tests for the Atlas DuckDB query view's status filtering, satellite
grouping, and agency-projection lookup -- the query surfaces the explorer
tidy added on top of :mod:`refspec.atlas.duckdb_view`.

These tests build tiny in-memory Arrow tables shaped exactly like the real
*compact search-view* Parquet tables (the schemas
:mod:`refspec.atlas.parquet_search_view` actually writes -- narrower than the
full-view schemas in :mod:`refspec.atlas.parquet_tables`) and register them
directly as the named DuckDB views :class:`~refspec.atlas.duckdb_view.AtlasDuckDBView`
expects, bypassing the digest-verified :meth:`AtlasDuckDBView.open`
classmethod entirely. That verification (member closure, manifest digests)
belongs to :mod:`refspec.atlas.parquet_search_view` and is exercised
elsewhere; these tests are about the SQL the query methods run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.duckdb_view import ATLAS_DUCKDB_TABLES, AtlasDuckDBView, AtlasDuckDBViewError
from refspec.atlas.parquet_tables import (
    AGENCY_PROJECTION_ROLE,
    AGENCY_PROJECTION_TABLE_NAMES,
    AGENCY_PROJECTION_TABLE_SCHEMAS,
    AGENCY_PROJECTION_UNRESOLVED_ROLE,
)

_SAME_ENTITY_AS = "https://refspec.org/ns/atlas/v3#sameEntityAs"
_B32 = pa.binary(32)

# The compact search-view schemas duckdb_view.py actually queries against --
# narrower than refspec.atlas.parquet_tables.TABLE_SCHEMAS, which shapes the
# pre-compaction full view. Mirrors refspec.atlas.parquet_search_view._SCHEMAS.
_COMPACT_SCHEMAS: dict[CompactRecordRole, pa.Schema] = {
    CompactRecordRole.RESOURCE: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("release", pa.string(), nullable=False),
            pa.field("scheme", pa.string(), nullable=False),
            pa.field("semantic_ring", pa.string(), nullable=False),
            pa.field("resource_profile", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            pa.field("definition", pa.string()),
            pa.field("notes", pa.list_(pa.string())),
            pa.field("notations", pa.list_(pa.string())),
            pa.field("record_status", pa.string()),
        ]
    ),
    CompactRecordRole.LABEL: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("resource", pa.string(), nullable=False),
            pa.field("label_role", pa.string(), nullable=False),
            pa.field("value", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("release", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
        ]
    ),
    CompactRecordRole.STATEMENT: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("statement_type", pa.string(), nullable=False),
            pa.field("subject", pa.string(), nullable=False),
            pa.field("predicate", pa.string(), nullable=False),
            pa.field("object", pa.string(), nullable=False),
            pa.field("source_release", pa.string(), nullable=False),
            pa.field("target_release", pa.string(), nullable=False),
            pa.field("policy", pa.string(), nullable=False),
            pa.field("asserted_at", pa.string(), nullable=False),
            pa.field("semantic_ring", pa.string()),
            pa.field("source_ring", pa.string()),
            pa.field("target_ring", pa.string()),
            pa.field("supersedes_assertion", pa.string()),
        ]
    ),
    CompactRecordRole.EVIDENCE_BINDING: pa.schema(
        [
            pa.field("evidence_id", _B32, nullable=False),
            pa.field("statement", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            pa.field("evidence_source_digest", _B32, nullable=False),
            pa.field("attestor", pa.string(), nullable=False),
            pa.field("evidence_role", pa.string(), nullable=False),
            pa.field("decision", pa.string(), nullable=False),
            pa.field("attested_at", pa.string(), nullable=False),
        ]
    ),
    CompactRecordRole.SOURCE_RECORD: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("source_release", pa.string(), nullable=False),
            pa.field("source_digest", _B32, nullable=False),
            pa.field("source_locator", pa.string(), nullable=False),
            pa.field("represents_resource", pa.string()),
        ]
    ),
    CompactRecordRole.RELEASE: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("release_type", pa.string(), nullable=False),
            pa.field("identifier", pa.string(), nullable=False),
            pa.field("issued", pa.string(), nullable=False),
            pa.field("source_digest", _B32),
            pa.field("source_locator", pa.string()),
            pa.field("resource_profile", pa.string()),
            pa.field("semantic_ring", pa.string()),
            pa.field("scheme", pa.string()),
            pa.field("membership_mode", pa.string()),
        ]
    ),
    CompactRecordRole.IDENTIFIER: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("identifier_value", pa.string(), nullable=False),
            pa.field("identifier_scheme", pa.string(), nullable=False),
            pa.field("identifies", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
        ]
    ),
    CompactRecordRole.LIFECYCLE_EVENT: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("applies_to", pa.string(), nullable=False),
            pa.field("lifecycle_event_kind", pa.string(), nullable=False),
            pa.field("effective_date", pa.string(), nullable=False),
            pa.field("source_records", pa.list_(pa.string()), nullable=False),
            pa.field("from_release", pa.string()),
            pa.field("to_release", pa.string()),
        ]
    ),
}


def _resource_row(
    resource_id: str,
    release: str,
    *,
    status: str | None = None,
    ring: str = "subject",
    profile: str = "conceptScheme",
    definition: str | None = None,
) -> dict[str, Any]:
    return {
        "id": resource_id,
        "release": release,
        "scheme": release,
        "semantic_ring": ring,
        "resource_profile": profile,
        "source_record": f"{resource_id}:source",
        "definition": definition,
        "notes": [],
        "notations": [],
        "record_status": status,
    }


def _release_row(
    release_id: str,
    identifier: str,
    *,
    ring: str = "subject",
    release_type: str = "AtlasRelease",
) -> dict[str, Any]:
    return {
        "id": release_id,
        "release_type": release_type,
        "identifier": identifier,
        "issued": "2026-08-15",
        "source_digest": None,
        "source_locator": None,
        "resource_profile": "conceptScheme",
        "semantic_ring": ring,
        "scheme": release_id,
        "membership_mode": "closed",
    }


def _statement_row(
    statement_id: str,
    *,
    statement_type: str,
    subject: str,
    predicate: str,
    obj: str,
    source_release: str,
    target_release: str,
) -> dict[str, Any]:
    return {
        "id": statement_id,
        "statement_type": statement_type,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "source_release": source_release,
        "target_release": target_release,
        "policy": "asserted",
        "asserted_at": "2026-08-15T00:00:00Z",
        "semantic_ring": "subject",
        "source_ring": "subject",
        "target_ring": "subject",
        "supersedes_assertion": None,
    }


def _make_view(
    root: Path,
    *,
    resources: list[dict[str, Any]] = (),
    statements: list[dict[str, Any]] = (),
    releases: list[dict[str, Any]] = (),
    labels: list[dict[str, Any]] = (),
    identifiers: list[dict[str, Any]] = (),
) -> AtlasDuckDBView:
    """Build a query-ready ``AtlasDuckDBView`` without the digest-verified open path."""

    connection = duckdb.connect(str(root / "test.duckdb"))
    rows_by_role: dict[CompactRecordRole, list[dict[str, Any]]] = {
        CompactRecordRole.RESOURCE: list(resources),
        CompactRecordRole.STATEMENT: list(statements),
        CompactRecordRole.RELEASE: list(releases),
        CompactRecordRole.LABEL: list(labels),
        CompactRecordRole.IDENTIFIER: list(identifiers),
        CompactRecordRole.EVIDENCE_BINDING: [],
        CompactRecordRole.SOURCE_RECORD: [],
        CompactRecordRole.LIFECYCLE_EVENT: [],
    }
    for role, rows in rows_by_role.items():
        schema = _COMPACT_SCHEMAS[role]
        table = pa.Table.from_pylist(rows, schema=schema) if rows else schema.empty_table()
        connection.from_arrow(table).create_view(ATLAS_DUCKDB_TABLES[role])
    temporary_directory = tempfile.TemporaryDirectory()
    return AtlasDuckDBView(
        root=root,
        manifest_digest="sha256:" + "0" * 64,
        manifest={"input": {"atlas": {}}, "counts": {}},
        tables={},
        temporary_directory=temporary_directory,
        database_path=root / "test.duckdb",
        connection=connection,
    )


# --------------------------------------------------------------------------
# Status filtering: search, resource, release_graph, overview.
# --------------------------------------------------------------------------


def test_search_hides_deprecated_status_by_default(tmp_path: Path) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:v", "vocab")],
        resources=[
            _resource_row("urn:res:active", "urn:r:v", status="active"),
            _resource_row("urn:res:capitalized", "urn:r:v", status="ACTIVE"),
            _resource_row("urn:res:no-status", "urn:r:v", status=None),
            _resource_row("urn:res:deprecated", "urn:r:v", status="deprecated"),
            _resource_row(
                "urn:res:deprecated-endpoint", "urn:r:v", status="deprecatedAlignmentEndpoint"
            ),
            _resource_row("urn:res:shout-deprecated", "urn:r:v", status="DEPRECATED"),
        ],
    )
    try:
        active_ids = {row["id"] for row in view.search()}
        assert active_ids == {"urn:res:active", "urn:res:capitalized", "urn:res:no-status"}

        all_ids = {row["id"] for row in view.search(status="all")}
        assert all_ids == {
            "urn:res:active",
            "urn:res:capitalized",
            "urn:res:no-status",
            "urn:res:deprecated",
            "urn:res:deprecated-endpoint",
            "urn:res:shout-deprecated",
        }
    finally:
        view.close()


def test_search_status_filter_applies_under_full_text_query_too(tmp_path: Path) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:v", "vocab")],
        resources=[
            _resource_row("urn:res:kept", "urn:r:v", status="active", definition="agriculture"),
            _resource_row(
                "urn:res:hidden", "urn:r:v", status="deprecated", definition="agriculture policy"
            ),
        ],
    )
    try:
        default_ids = {row["id"] for row in view.search("agriculture")}
        assert default_ids == {"urn:res:kept"}

        all_ids = {row["id"] for row in view.search("agriculture", status="all")}
        assert all_ids == {"urn:res:kept", "urn:res:hidden"}
    finally:
        view.close()


def test_search_rejects_unknown_status_value(tmp_path: Path) -> None:
    view = _make_view(tmp_path)
    try:
        with pytest.raises(AtlasDuckDBViewError):
            view.search(status="bogus")
    finally:
        view.close()


def test_resource_always_returns_itself_even_if_deprecated_but_hides_deprecated_relations(
    tmp_path: Path,
) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:v", "vocab")],
        resources=[
            _resource_row("urn:res:root", "urn:r:v", status="deprecated"),
            _resource_row("urn:res:active-neighbor", "urn:r:v", status="active"),
            _resource_row("urn:res:deprecated-neighbor", "urn:r:v", status="deprecated"),
        ],
        statements=[
            _statement_row(
                "urn:st:1",
                statement_type="NativeRelationAssertion",
                subject="urn:res:root",
                predicate="https://example/broader",
                obj="urn:res:active-neighbor",
                source_release="urn:r:v",
                target_release="urn:r:v",
            ),
            _statement_row(
                "urn:st:2",
                statement_type="NativeRelationAssertion",
                subject="urn:res:root",
                predicate="https://example/broader",
                obj="urn:res:deprecated-neighbor",
                source_release="urn:r:v",
                target_release="urn:r:v",
            ),
        ],
    )
    try:
        # The requested resource itself is always returned, deprecated or not.
        default_resource = view.resource("urn:res:root")
        assert default_resource["id"] == "urn:res:root"
        assert default_resource["status"] == "deprecated"
        assert {row["object"] for row in default_resource["relations"]} == {
            "urn:res:active-neighbor"
        }

        all_resource = view.resource("urn:res:root", status="all")
        assert {row["object"] for row in all_resource["relations"]} == {
            "urn:res:active-neighbor",
            "urn:res:deprecated-neighbor",
        }
    finally:
        view.close()


def test_release_graph_excludes_deprecated_members_by_default(tmp_path: Path) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:v", "vocab")],
        resources=[
            _resource_row("urn:res:a", "urn:r:v", status="active"),
            _resource_row("urn:res:b", "urn:r:v", status="deprecatedAlignmentEndpoint"),
        ],
    )
    try:
        default_graph = view.release_graph("urn:r:v")
        assert [node[0] for node in default_graph["nodes"]] == ["urn:res:a"]

        all_graph = view.release_graph("urn:r:v", status="all")
        assert {node[0] for node in all_graph["nodes"]} == {"urn:res:a", "urn:res:b"}
    finally:
        view.close()


def test_overview_excludes_relations_touching_deprecated_resources(tmp_path: Path) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:a", "vocab-a"), _release_row("urn:r:b", "vocab-b")],
        resources=[
            _resource_row("urn:res:a1", "urn:r:a", status="active"),
            _resource_row("urn:res:a2", "urn:r:a", status="deprecated"),
            _resource_row("urn:res:b1", "urn:r:b", status="active"),
        ],
        statements=[
            _statement_row(
                "urn:st:live",
                statement_type="MappingAssertion",
                subject="urn:res:a1",
                predicate=_SAME_ENTITY_AS,
                obj="urn:res:b1",
                source_release="urn:r:a",
                target_release="urn:r:b",
            ),
            _statement_row(
                "urn:st:touches-deprecated",
                statement_type="MappingAssertion",
                subject="urn:res:a2",
                predicate=_SAME_ENTITY_AS,
                obj="urn:res:b1",
                source_release="urn:r:a",
                target_release="urn:r:b",
            ),
        ],
    )
    try:
        default_overview = view.overview()
        nodes = {node["id"]: node for node in default_overview["nodes"]}
        assert nodes["urn:r:a"]["resources"] == 1
        assert len(default_overview["edges"]) == 1
        assert default_overview["edges"][0]["count"] == 1

        all_overview = view.overview(status="all")
        nodes_all = {node["id"]: node for node in all_overview["nodes"]}
        assert nodes_all["urn:r:a"]["resources"] == 2
        assert all_overview["edges"][0]["count"] == 2
    finally:
        view.close()


def test_overview_rejects_unknown_status_value(tmp_path: Path) -> None:
    view = _make_view(tmp_path)
    try:
        with pytest.raises(AtlasDuckDBViewError):
            view.overview(status="bogus")
    finally:
        view.close()


# --------------------------------------------------------------------------
# Satellite grouping.
# --------------------------------------------------------------------------


def test_overview_flags_majority_endpoint_status_release_as_satellite_with_mapping_partner(
    tmp_path: Path,
) -> None:
    view = _make_view(
        tmp_path,
        releases=[
            _release_row("urn:r:core", "core-vocab"),
            _release_row("urn:r:sat", "core-vocab-satellite-2026-08-15"),
        ],
        resources=[
            _resource_row("urn:res:core1", "urn:r:core", status="active"),
            _resource_row("urn:res:sat1", "urn:r:sat", status="alignmentEndpoint"),
            _resource_row("urn:res:sat2", "urn:r:sat", status="alignmentEndpoint"),
        ],
        statements=[
            # A small NativeRelationAssertion volume the satellite shares with
            # itself should not outrank a real MappingAssertion partner.
            _statement_row(
                "urn:st:mapping",
                statement_type="MappingAssertion",
                subject="urn:res:sat1",
                predicate=_SAME_ENTITY_AS,
                obj="urn:res:core1",
                source_release="urn:r:sat",
                target_release="urn:r:core",
            ),
        ],
    )
    try:
        overview = view.overview()
        nodes = {node["id"]: node for node in overview["nodes"]}
        assert nodes["urn:r:sat"]["satellite"] is True
        assert nodes["urn:r:sat"]["partner"] == "urn:r:core"
        assert nodes["urn:r:core"]["satellite"] is False
        assert nodes["urn:r:core"]["partner"] is None
    finally:
        view.close()


def test_overview_flags_satellite_by_endpoint_named_identifier_even_without_status_majority(
    tmp_path: Path,
) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:named", "lc-external-example-endpoints-2026-08-15")],
        resources=[_resource_row("urn:res:x", "urn:r:named", status="active")],
    )
    try:
        overview = view.overview()
        nodes = {node["id"]: node for node in overview["nodes"]}
        assert nodes["urn:r:named"]["satellite"] is True
    finally:
        view.close()


def test_overview_satellite_partner_falls_back_to_any_relation_type_without_mappings(
    tmp_path: Path,
) -> None:
    view = _make_view(
        tmp_path,
        releases=[
            _release_row("urn:r:core", "core-vocab"),
            _release_row("urn:r:sat", "core-vocab-endpoints-2026-08-15"),
        ],
        resources=[
            _resource_row("urn:res:core1", "urn:r:core", status="active"),
            _resource_row("urn:res:sat1", "urn:r:sat", status="alignmentEndpoint"),
        ],
        statements=[
            _statement_row(
                "urn:st:native",
                statement_type="NativeRelationAssertion",
                subject="urn:res:sat1",
                predicate="https://example/related",
                obj="urn:res:core1",
                source_release="urn:r:sat",
                target_release="urn:r:core",
            ),
        ],
    )
    try:
        overview = view.overview()
        nodes = {node["id"]: node for node in overview["nodes"]}
        assert nodes["urn:r:sat"]["satellite"] is True
        assert nodes["urn:r:sat"]["partner"] == "urn:r:core"
    finally:
        view.close()


def test_overview_satellite_with_no_cross_release_relations_has_no_partner(
    tmp_path: Path,
) -> None:
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:sat", "lonely-endpoints-2026-08-15")],
        resources=[_resource_row("urn:res:sat1", "urn:r:sat", status="alignmentEndpoint")],
    )
    try:
        overview = view.overview()
        nodes = {node["id"]: node for node in overview["nodes"]}
        assert nodes["urn:r:sat"]["satellite"] is True
        assert nodes["urn:r:sat"]["partner"] is None
    finally:
        view.close()


# --------------------------------------------------------------------------
# Agency projection lookup.
# --------------------------------------------------------------------------


def _write_agency_projection_fixture(
    root: Path,
    *,
    resolved: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> None:
    tables_dir = root / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(resolved, schema=AGENCY_PROJECTION_TABLE_SCHEMAS[AGENCY_PROJECTION_ROLE]),
        tables_dir / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_ROLE],
    )
    pq.write_table(
        pa.Table.from_pylist(
            unresolved, schema=AGENCY_PROJECTION_TABLE_SCHEMAS[AGENCY_PROJECTION_UNRESOLVED_ROLE]
        ),
        tables_dir / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_UNRESOLVED_ROLE],
    )


def _resolved_row(
    source_value: str,
    org: str,
    pref_label: str,
    *,
    abbreviations: list[str] = (),
    aliases: list[str] = (),
    parent_org: str | None = None,
) -> dict[str, Any]:
    return {
        "source_value_kind": "regulationsGovAgencyId",
        "source_value": source_value,
        "org": org,
        "pref_label": pref_label,
        "abbreviations": list(abbreviations),
        "aliases": list(aliases),
        "parent_org": parent_org,
        "relation": _SAME_ENTITY_AS,
        "evidence_tier": "E4",
        "warrant": "humanReview",
        "basis": "federalRegisterShortNameEqualsRegulationsGovAgencyId",
        "evidence_records": [],
    }


def _unresolved_row(source_value: str, pref_label: str, reason: str) -> dict[str, Any]:
    return {
        "source_value_kind": "regulationsGovAgencyId",
        "source_value": source_value,
        "source_org": f"urn:ref:regulations-gov-agency:{source_value}",
        "pref_label": pref_label,
        "source_parent_org": None,
        "reason": reason,
        "reasoning": f"No held roster contains {pref_label}.",
        "candidate_resources": [],
        "closest_non_adopted_candidate": None,
    }


def test_agency_projection_unavailable_when_tables_are_missing(tmp_path: Path) -> None:
    view = _make_view(tmp_path)
    try:
        assert view.agency_projection_available() is False
        result = view.agency_projection("EPA")
        assert result == {"available": False, "resolved": [], "unresolved": []}
    finally:
        view.close()


def test_agency_projection_unavailable_when_only_one_table_present(tmp_path: Path) -> None:
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [_resolved_row("EPA", "urn:ref:test-org:epa", "Environmental Protection Agency")],
            schema=AGENCY_PROJECTION_TABLE_SCHEMAS[AGENCY_PROJECTION_ROLE],
        ),
        tables_dir / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_ROLE],
    )
    view = _make_view(tmp_path)
    try:
        assert view.agency_projection_available() is False
        assert view.agency_projection("EPA")["available"] is False
    finally:
        view.close()


def test_agency_projection_lookup_filters_and_flags_known_org(tmp_path: Path) -> None:
    _write_agency_projection_fixture(
        tmp_path,
        resolved=[
            _resolved_row(
                "EPA",
                "urn:ref:test-org:epa",
                "Environmental Protection Agency",
                abbreviations=["EPA"],
                aliases=["Environmental Protection Agency"],
            ),
            _resolved_row(
                "ABMC",
                "urn:ref:test-org:abmc",
                "American Battle Monuments Commission",
                abbreviations=["ABMC"],
            ),
        ],
        unresolved=[
            _unresolved_row("ARCTICGAS", "Alaska Natural Gas office", "noCounterpartInHeldRosters"),
        ],
    )
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:org", "federal-orgs")],
        resources=[_resource_row("urn:ref:test-org:epa", "urn:r:org", status="active")],
    )
    try:
        assert view.agency_projection_available() is True

        by_source_value = view.agency_projection("EPA")
        assert by_source_value["available"] is True
        assert [row["source_value"] for row in by_source_value["resolved"]] == ["EPA"]
        assert by_source_value["resolved"][0]["org_known"] is True
        assert by_source_value["resolved"][0]["evidence_count"] == 0

        # ABMC's org isn't in this view's atlas_resources, so it's not "known".
        by_pref_label = view.agency_projection("battle monuments")
        assert [row["source_value"] for row in by_pref_label["resolved"]] == ["ABMC"]
        assert by_pref_label["resolved"][0]["org_known"] is False

        # Case-insensitive alias match.
        by_alias_upper = view.agency_projection("ENVIRONMENTAL PROTECTION")
        assert [row["source_value"] for row in by_alias_upper["resolved"]] == ["EPA"]

        by_unresolved_query = view.agency_projection("arcticgas")
        assert by_unresolved_query["resolved"] == []
        assert [row["source_value"] for row in by_unresolved_query["unresolved"]] == [
            "ARCTICGAS"
        ]

        empty_query = view.agency_projection("")
        assert {row["source_value"] for row in empty_query["resolved"]} == {"EPA", "ABMC"}
        assert {row["source_value"] for row in empty_query["unresolved"]} == {"ARCTICGAS"}

        no_match = view.agency_projection("no-such-agency-xyz")
        assert no_match["resolved"] == []
        assert no_match["unresolved"] == []
    finally:
        view.close()

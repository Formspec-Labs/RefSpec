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
    DERIVED_RELATION_TABLE_NAME,
    DERIVED_RELATION_TABLE_SCHEMA,
)

_SAME_ENTITY_AS = "https://refspec.org/ns/atlas/v3#sameEntityAs"
_B32 = pa.binary(32)

#: The newest sealed compact search view carrying REF-042's derived-relations
#: table. ``output/`` is git-ignored, so the one test that reads it skips
#: when it is absent -- the same posture ``tests/test_atlas_explorer_cli.py``
#: takes toward its own sealed view.
_SEALED_SEARCH_VIEW = (
    Path(__file__).resolve().parents[1] / "output" / "atlas-3.1-parquet-search-view-2026-08-21d"
)

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
        manifest={
            "input": {"atlas": {}},
            # facets() only reads the resource/statement counts; the rest are
            # left absent, matching every existing caller of this helper that
            # never touched .counts before facets() started reading it.
            "counts": {
                CompactRecordRole.RESOURCE.value: len(rows_by_role[CompactRecordRole.RESOURCE]),
                CompactRecordRole.STATEMENT.value: len(rows_by_role[CompactRecordRole.STATEMENT]),
            },
        },
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


# --------------------------------------------------------------------------
# Derived relations (REF-042): opt-in-hidden, schema discovered at runtime.
#
# The sibling table's real column names were not settled at the time this
# reader was written, so two fixture shapes are used below: a "canonical"
# shape (the column names duckdb_view.py's candidate lists check first) and
# an "alternate" shape using different names for the two genuinely uncertain
# columns (rule / derived-from-assertions) plus a schema that omits the
# cosmetic id/ring/digest columns entirely -- proving the runtime DESCRIBE-
# based discovery, not a hardcoded guess, is what makes both work.
# --------------------------------------------------------------------------


def _write_derived_relations_fixture(
    root: Path,
    rows: list[dict[str, Any]],
    schema: pa.Schema,
) -> None:
    tables_dir = root / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        tables_dir / "derived-relations.parquet",
    )


_CANONICAL_DERIVED_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string(), nullable=False),
        pa.field("subject", pa.string(), nullable=False),
        pa.field("predicate", pa.string(), nullable=False),
        pa.field("object", pa.string(), nullable=False),
        pa.field("semantic_ring", pa.string()),
        pa.field("content_digest", pa.string()),
        pa.field("rule_iri", pa.string()),
        pa.field("derived_from_assertions", pa.list_(pa.string())),
    ]
)

# Deliberately different names for the two genuinely unsettled columns, and
# no id/semantic_ring/content_digest columns at all -- the minimal schema
# duckdb_view.py must still be able to use.
_ALTERNATE_DERIVED_SCHEMA = pa.schema(
    [
        pa.field("subject", pa.string(), nullable=False),
        pa.field("predicate", pa.string(), nullable=False),
        pa.field("object", pa.string(), nullable=False),
        pa.field("rule", pa.string()),
        pa.field("evidence", pa.list_(pa.string())),
    ]
)


def _broader() -> str:
    return "http://www.w3.org/2004/02/skos/core#broader"


def test_derived_relations_unavailable_when_table_is_missing(tmp_path: Path) -> None:
    view = _make_view(tmp_path)
    try:
        assert view.derived_relations_available() is False
        assert view.facets()["derivedRelations"] == {"available": False, "count": 0}
        default_all = view.overview(relations="all")
        assert default_all == view.overview()
    finally:
        view.close()


def test_resource_hides_derived_relations_by_default_and_shows_them_opted_in(
    tmp_path: Path,
) -> None:
    _write_derived_relations_fixture(
        tmp_path,
        rows=[
            {
                "id": "urn:ref:atlas-derived-relation:1",
                "subject": "urn:mesh:child",
                "predicate": _broader(),
                "object": "urn:mesh:parent",
                "semantic_ring": "subject",
                "content_digest": "sha256:" + "a" * 64,
                "rule_iri": "urn:ref:rule:mesh-tree-number-broader",
                "derived_from_assertions": ["urn:st:asserted-1", "urn:st:asserted-2"],
            }
        ],
        schema=_CANONICAL_DERIVED_SCHEMA,
    )
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:mesh", "mesh")],
        resources=[
            _resource_row("urn:mesh:child", "urn:r:mesh", status="active"),
            _resource_row("urn:mesh:parent", "urn:r:mesh", status="active"),
        ],
        labels=[
            {
                "id": "urn:lbl:1",
                "resource": "urn:mesh:child",
                "label_role": "preferred",
                "value": "Child concept",
                "language": "en",
                "release": "urn:r:mesh",
                "source_record": "urn:mesh:child:source",
            },
            {
                "id": "urn:lbl:2",
                "resource": "urn:mesh:parent",
                "label_role": "preferred",
                "value": "Parent concept",
                "language": "en",
                "release": "urn:r:mesh",
                "source_record": "urn:mesh:parent:source",
            },
        ],
    )
    try:
        assert view.derived_relations_available() is True
        assert view.facets()["derivedRelations"] == {"available": True, "count": 1}

        hidden = view.resource("urn:mesh:child")
        assert hidden["relations"] == []

        shown = view.resource("urn:mesh:child", relations="all")
        assert len(shown["relations"]) == 1
        edge = shown["relations"][0]
        assert edge["statement_type"] == "DerivedRelation"
        assert edge["subject"] == "urn:mesh:child"
        assert edge["object"] == "urn:mesh:parent"
        assert edge["predicate"] == _broader()
        assert edge["derivation_rule"] == "urn:ref:rule:mesh-tree-number-broader"
        assert edge["derived_from_assertions"] == ["urn:st:asserted-1", "urn:st:asserted-2"]
        assert edge["content_digest"] == "sha256:" + "a" * 64
        assert edge["evidence"] == []
        assert edge["evidence_count"] == 0
        assert edge["subject_label"] == "Child concept"
        assert edge["object_label"] == "Parent concept"
        assert edge["source_release"] == "urn:r:mesh"
        assert edge["target_release"] == "urn:r:mesh"

        # Also reachable from the object side.
        from_parent = view.resource("urn:mesh:parent", relations="all")
        assert len(from_parent["relations"]) == 1
    finally:
        view.close()


def test_derived_relations_discovers_alternate_column_names_at_runtime(tmp_path: Path) -> None:
    _write_derived_relations_fixture(
        tmp_path,
        rows=[
            {
                "subject": "urn:mesh:child",
                "predicate": _broader(),
                "object": "urn:mesh:parent",
                "rule": "urn:ref:rule:gcmd-column-nesting-broader",
                "evidence": ["urn:src:record-1"],
            }
        ],
        schema=_ALTERNATE_DERIVED_SCHEMA,
    )
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:mesh", "mesh")],
        resources=[
            _resource_row("urn:mesh:child", "urn:r:mesh", status="active"),
            _resource_row("urn:mesh:parent", "urn:r:mesh", status="active"),
        ],
    )
    try:
        shown = view.resource("urn:mesh:child", relations="all")
        edge = shown["relations"][0]
        assert edge["derivation_rule"] == "urn:ref:rule:gcmd-column-nesting-broader"
        assert edge["derived_from_assertions"] == ["urn:src:record-1"]
        # No id column in this schema -- a stable synthetic id is minted instead.
        assert edge["id"] == "urn:ref:atlas-derived-relation:urn:mesh:child|" + _broader() + "|urn:mesh:parent"
        # No semantic_ring/content_digest columns in this schema.
        assert edge["semantic_ring"] is None
        assert edge["content_digest"] is None
    finally:
        view.close()


def test_derived_relations_reads_the_real_ref042_parquet_schema(tmp_path: Path) -> None:
    """Same as the canonical-shape test above, but against
    :data:`refspec.atlas.parquet_tables.DERIVED_RELATION_TABLE_SCHEMA` itself
    -- REF-042's actual writer schema, binary digest columns included -- so a
    future rename in that module fails this test loudly instead of silently
    drifting from what duckdb_view.py was written against.
    """

    content_digest = b"\xab" * 32
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": "urn:ref:atlas-derived:" + content_digest.hex(),
                    "subject": "urn:mesh:child",
                    "predicate": _broader(),
                    "object": "urn:mesh:parent",
                    "semantic_ring": "subject",
                    "derivation_rule": "urn:ref:rule:mesh-tree-number-broader",
                    "engine": "https://refspec.org/code/mesh-tree-broader",
                    "engine_version": "1",
                    "derived_from_assertions": ["urn:st:asserted-1"],
                    "input_digest": b"\xcd" * 32,
                    "generated_at": "2026-08-18T00:00:00+00:00",
                    "content_digest": content_digest,
                }
            ],
            schema=DERIVED_RELATION_TABLE_SCHEMA,
        ),
        tables_dir / DERIVED_RELATION_TABLE_NAME,
    )
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:mesh", "mesh")],
        resources=[
            _resource_row("urn:mesh:child", "urn:r:mesh", status="active"),
            _resource_row("urn:mesh:parent", "urn:r:mesh", status="active"),
        ],
    )
    try:
        assert view.derived_relations_available() is True
        edge = view.resource("urn:mesh:child", relations="all")["relations"][0]
        assert edge["id"] == "urn:ref:atlas-derived:" + content_digest.hex()
        assert edge["derivation_rule"] == "urn:ref:rule:mesh-tree-number-broader"
        assert edge["derived_from_assertions"] == ["urn:st:asserted-1"]
        assert edge["semantic_ring"] == "subject"
        assert edge["content_digest"] == "sha256:" + content_digest.hex()
    finally:
        view.close()


def test_resource_rejects_unknown_relations_value(tmp_path: Path) -> None:
    view = _make_view(tmp_path)
    try:
        with pytest.raises(AtlasDuckDBViewError, match="relations filter"):
            view.resource("urn:res:missing", relations="bogus")
    finally:
        view.close()


def test_release_graph_includes_derived_edges_only_within_the_release_when_opted_in(
    tmp_path: Path,
) -> None:
    _write_derived_relations_fixture(
        tmp_path,
        rows=[
            {
                "id": "urn:ref:atlas-derived-relation:in-release",
                "subject": "urn:mesh:child",
                "predicate": _broader(),
                "object": "urn:mesh:parent",
                "semantic_ring": "subject",
                "content_digest": None,
                "rule_iri": "urn:ref:rule:mesh-tree-number-broader",
                "derived_from_assertions": [],
            },
            {
                # object is outside this release's node set -- must be dropped,
                # exactly like an out-of-release asserted relation already is.
                "id": "urn:ref:atlas-derived-relation:outside",
                "subject": "urn:mesh:child",
                "predicate": _broader(),
                "object": "urn:other:concept",
                "semantic_ring": "subject",
                "content_digest": None,
                "rule_iri": "urn:ref:rule:mesh-tree-number-broader",
                "derived_from_assertions": [],
            },
        ],
        schema=_CANONICAL_DERIVED_SCHEMA,
    )
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:mesh", "mesh")],
        resources=[
            _resource_row("urn:mesh:child", "urn:r:mesh", status="active"),
            _resource_row("urn:mesh:parent", "urn:r:mesh", status="active"),
        ],
    )
    try:
        default_graph = view.release_graph("urn:r:mesh")
        assert default_graph["edges"] == []
        assert default_graph["types"] == []

        all_graph = view.release_graph("urn:r:mesh", relations="all")
        assert all_graph["types"] == ["DerivedRelation"]
        assert len(all_graph["edges"]) == 1
        subject_index, object_index, _predicate_index, type_index = all_graph["edges"][0]
        assert all_graph["nodes"][subject_index][0] == "urn:mesh:child"
        assert all_graph["nodes"][object_index][0] == "urn:mesh:parent"
        assert all_graph["types"][type_index] == "DerivedRelation"
    finally:
        view.close()


def test_overview_folds_derived_relations_into_internal_relations_when_opted_in(
    tmp_path: Path,
) -> None:
    _write_derived_relations_fixture(
        tmp_path,
        rows=[
            {
                "id": "urn:ref:atlas-derived-relation:1",
                "subject": "urn:mesh:child",
                "predicate": _broader(),
                "object": "urn:mesh:parent",
                "semantic_ring": "subject",
                "content_digest": None,
                "rule_iri": "urn:ref:rule:mesh-tree-number-broader",
                "derived_from_assertions": [],
            }
        ],
        schema=_CANONICAL_DERIVED_SCHEMA,
    )
    view = _make_view(
        tmp_path,
        releases=[_release_row("urn:r:mesh", "mesh")],
        resources=[
            _resource_row("urn:mesh:child", "urn:r:mesh", status="active"),
            _resource_row("urn:mesh:parent", "urn:r:mesh", status="active"),
        ],
    )
    try:
        default_overview = view.overview()
        nodes = {node["id"]: node for node in default_overview["nodes"]}
        assert nodes["urn:r:mesh"]["internalRelations"] == 0

        all_overview = view.overview(relations="all")
        nodes_all = {node["id"]: node for node in all_overview["nodes"]}
        assert nodes_all["urn:r:mesh"]["internalRelations"] == 1
        # A within-release derived relation is internal volume, never an edge.
        assert all_overview["edges"] == []
    finally:
        view.close()


def test_overview_draws_cross_release_derived_relations_as_edges_when_opted_in(
    tmp_path: Path,
) -> None:
    """Derivation rules cross releases, so ``overview()`` must too.

    Two of the five rules shipped today relate resources in *different*
    releases (Federal Register thesaurus -> Federal Register API topics,
    EuroVoc microthesauri -> EuroVoc domains). Folding every derived row
    into the subject release's ``internalRelations`` -- as this method used
    to -- drew no connection at all between the two releases on the overview
    map, while the resource inspector happily showed the same links.
    """

    _write_derived_relations_fixture(
        tmp_path,
        rows=[
            {
                # Crosses releases: an edge between the two vocabularies.
                "id": "urn:ref:atlas-derived-relation:cross-1",
                "subject": "urn:fr:thesaurus-term",
                "predicate": _broader(),
                "object": "urn:fr:api-topic",
                "semantic_ring": "subject",
                "content_digest": None,
                "rule_iri": "urn:ref:rule:fr-thesaurus-api-topic-label-equality",
                "derived_from_assertions": [],
            },
            {
                # Same pair the other way round: one undirected pair, count 2.
                "id": "urn:ref:atlas-derived-relation:cross-2",
                "subject": "urn:fr:api-topic",
                "predicate": _broader(),
                "object": "urn:fr:thesaurus-term-2",
                "semantic_ring": "subject",
                "content_digest": None,
                "rule_iri": "urn:ref:rule:fr-thesaurus-api-topic-label-equality",
                "derived_from_assertions": [],
            },
            {
                # Within one release: internal volume, not an edge.
                "id": "urn:ref:atlas-derived-relation:internal",
                "subject": "urn:fr:thesaurus-term",
                "predicate": _broader(),
                "object": "urn:fr:thesaurus-term-2",
                "semantic_ring": "subject",
                "content_digest": None,
                "rule_iri": "urn:ref:rule:fr-thesaurus-compound-head-broader",
                "derived_from_assertions": [],
            },
        ],
        schema=_CANONICAL_DERIVED_SCHEMA,
    )
    view = _make_view(
        tmp_path,
        releases=[
            _release_row("urn:r:fr-thesaurus", "federal-register-thesaurus-2025"),
            _release_row("urn:r:fr-topics", "federal-register-api-topics-2026-08-03"),
        ],
        resources=[
            _resource_row("urn:fr:thesaurus-term", "urn:r:fr-thesaurus", status="active"),
            _resource_row("urn:fr:thesaurus-term-2", "urn:r:fr-thesaurus", status="active"),
            _resource_row("urn:fr:api-topic", "urn:r:fr-topics", status="active"),
        ],
    )
    try:
        default_overview = view.overview()
        assert default_overview["edges"] == []
        assert all(node["internalRelations"] == 0 for node in default_overview["nodes"])

        all_overview = view.overview(relations="all")
        assert all_overview["edges"] == [
            {
                "source": "urn:r:fr-thesaurus",
                "target": "urn:r:fr-topics",
                "statement_type": "DerivedRelation",
                "count": 2,
            }
        ]
        nodes_all = {node["id"]: node for node in all_overview["nodes"]}
        assert nodes_all["urn:r:fr-thesaurus"]["internalRelations"] == 1
        assert nodes_all["urn:r:fr-topics"]["internalRelations"] == 0
    finally:
        view.close()


def test_overview_pins_the_sealed_views_cross_release_derived_edge_volume() -> None:
    """Pin the real cross-release derived volume the sealed view carries.

    Skipped when the (git-ignored) sealed search view is not present locally.
    Only ``resources`` and ``releases`` are read from it; the other compact
    tables are registered empty, which keeps the whole check under a second
    and leaves ``edges`` holding *nothing but* the derived cross-release
    volume this test is about -- the asserted mapping volume between the same
    releases is large, churns per build, and is pinned elsewhere.
    """

    sealed = _SEALED_SEARCH_VIEW
    if not (sealed / "tables" / DERIVED_RELATION_TABLE_NAME).is_file():
        pytest.skip(f"the sealed compact search view is not present locally: {sealed}")

    temporary_directory = tempfile.TemporaryDirectory()
    connection = duckdb.connect(str(Path(temporary_directory.name) / "pin.duckdb"))
    real_tables = {
        CompactRecordRole.RESOURCE: "resources.parquet",
        CompactRecordRole.RELEASE: "releases.parquet",
    }
    for role in CompactRecordRole:
        if role in real_tables:
            relation = connection.read_parquet(str(sealed / "tables" / real_tables[role]))
        else:
            relation = connection.from_arrow(_COMPACT_SCHEMAS[role].empty_table())
        relation.create_view(ATLAS_DUCKDB_TABLES[role])
    view = AtlasDuckDBView(
        root=sealed,
        manifest_digest="sha256:" + "0" * 64,
        manifest={"input": {"atlas": {}}, "counts": {}},
        tables={},
        temporary_directory=temporary_directory,
        database_path=Path(temporary_directory.name) / "pin.duckdb",
        connection=connection,
    )
    try:
        edges = view.overview(relations="all")["edges"]
        assert view.overview()["edges"] == []
        by_pair = {
            (edge["source"], edge["target"]): edge["count"]
            for edge in edges
            if edge["statement_type"] == "DerivedRelation"
        }
    finally:
        view.close()

    assert by_pair == {
        # urn:ref:rule:fr-thesaurus-api-topic-label-equality
        (
            "urn:ref:atlas-release:3:federal-register-thesaurus:2025-04-01",
            (
                "urn:ref:atlas-release:federal-register-api-topics-2026-08-03:"
                "9dd93c1e75b710b4f8f0e4e02d70ea34f43a2790dcbbe6b0e734a76f013aaed0"
            ),
        ): 698,
        # urn:ref:rule:eurovoc-microthesaurus-domain-notation-prefix
        (
            "urn:ref:atlas-release:3:eurovoc-domains:4.24",
            "urn:ref:atlas-release:3:eurovoc-microthesauri:4.24",
        ): 127,
    }
    assert sum(by_pair.values()) == 825

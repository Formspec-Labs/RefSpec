"""Query a verified Atlas compact Parquet view with DuckDB.

The Parquet artifact remains the authenticated input.  This module creates a
disposable DuckDB database outside that artifact, exposes stable SQL view names,
and builds a local full-text index only when text search is first requested.
"""

from __future__ import annotations

import re
import tempfile
import threading
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self, cast

import duckdb
import pyarrow as pa

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_artifact import normalize_sha256_prefix
from refspec.atlas.parquet_search_view import (
    AtlasParquetSearchViewError,
    verify_atlas_parquet_search_view,
)

ATLAS_DUCKDB_TABLES: Mapping[CompactRecordRole, str] = MappingProxyType(
    {
        CompactRecordRole.RESOURCE: "atlas_resources",
        CompactRecordRole.LABEL: "atlas_labels",
        CompactRecordRole.STATEMENT: "atlas_statements",
        CompactRecordRole.EVIDENCE_BINDING: "atlas_evidence_bindings",
        CompactRecordRole.SOURCE_RECORD: "atlas_source_records",
        CompactRecordRole.RELEASE: "atlas_releases",
        CompactRecordRole.IDENTIFIER: "atlas_identifiers",
        CompactRecordRole.LIFECYCLE_EVENT: "atlas_lifecycle_events",
    }
)
ATLAS_SEARCH_DOCUMENTS_TABLE = "atlas_search_documents"

_SEARCH_INDEX_SCHEMA = "fts_main_atlas_search_documents"
_SEARCH_LIMIT_MAXIMUM = 500

_STATUS_FILTERS = frozenset({"active", "all"})
_ENDPOINT_RELEASE_PATTERN = re.compile(r"endpoint", re.IGNORECASE)

_AGENCY_PROJECTION_TABLE_FILE = "agency-projection.parquet"
_AGENCY_PROJECTION_UNRESOLVED_TABLE_FILE = "agency-projection-unresolved.parquet"
_AGENCY_PROJECTION_VIEW = "atlas_agency_projection"
_AGENCY_PROJECTION_UNRESOLVED_VIEW = "atlas_agency_projection_unresolved"

#: The compact search view may carry REF-038's agency-projection tables as
#: manifest members alongside the eight closed compact record roles (see
#: refspec.atlas.parquet_search_view.PROJECTION_MEMBER_ROLES). They are not
#: one of ``CompactRecordRole`` and are never looked up through ``self.tables``
#: -- ``_agency_projection_paths`` finds them directly by their fixed
#: on-disk path -- so member construction below skips them rather than
#: failing to parse them as a compact record role.
_COMPACT_RECORD_ROLE_VALUES = frozenset(role.value for role in CompactRecordRole)


class AtlasDuckDBViewError(ValueError):
    """The verified Atlas query view cannot answer the requested query."""


class AtlasDuckDBView:
    """A disposable query session over one digest-pinned Atlas Parquet view.

    The named Atlas tables are DuckDB views over the verified Parquet members.
    ``query_rows`` and ``query_arrow`` make those views available to other local
    consumers without making the explorer their owner.
    """

    def __init__(
        self,
        *,
        root: Path,
        manifest_digest: str,
        manifest: Mapping[str, Any],
        tables: Mapping[CompactRecordRole, Path],
        temporary_directory: tempfile.TemporaryDirectory[str],
        database_path: Path,
        connection: duckdb.DuckDBPyConnection,
    ) -> None:
        self.root = root
        self.manifest_digest = manifest_digest
        self.manifest = manifest
        self.tables = tables
        self.database_path = database_path
        self._temporary_directory = temporary_directory
        self._connection = connection
        self._lock = threading.RLock()
        self._search_ready = False
        self._agency_projection_ready = False
        self._closed = False

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        trusted_manifest_digest: str,
    ) -> AtlasDuckDBView:
        """Verify a compact view and open a disposable DuckDB query session."""

        resolved = Path(root).resolve(strict=True)
        try:
            digest = normalize_sha256_prefix(trusted_manifest_digest)
            manifest = verify_atlas_parquet_search_view(
                resolved,
                expected_manifest_digest=digest,
            )
        except (AtlasParquetSearchViewError, ValueError) as error:
            raise AtlasDuckDBViewError(str(error)) from error
        tables = MappingProxyType(
            {
                CompactRecordRole(member["role"]): resolved / member["path"]
                for member in manifest["members"]
                if member["role"] in _COMPACT_RECORD_ROLE_VALUES
            }
        )
        temporary_directory = tempfile.TemporaryDirectory(prefix="refspec-atlas-duckdb-")
        database_path = Path(temporary_directory.name) / "atlas-query.duckdb"
        connection: duckdb.DuckDBPyConnection | None = None
        try:
            connection = duckdb.connect(str(database_path))
            for role, table_path in tables.items():
                connection.read_parquet(str(table_path)).create_view(
                    ATLAS_DUCKDB_TABLES[role]
                )
            return cls(
                root=resolved,
                manifest_digest=digest,
                manifest=manifest,
                tables=tables,
                temporary_directory=temporary_directory,
                database_path=database_path,
                connection=connection,
            )
        except BaseException:
            if connection is not None:
                connection.close()
            temporary_directory.cleanup()
            raise

    @property
    def atlas_input(self) -> Mapping[str, Any]:
        """Return the authenticated Atlas input pin from the Parquet manifest."""

        return cast(Mapping[str, Any], self.manifest["input"]["atlas"])

    @property
    def counts(self) -> Mapping[str, int]:
        """Return verified row counts by compact record role."""

        return cast(Mapping[str, int], self.manifest["counts"])

    @property
    def sql_tables(self) -> Mapping[CompactRecordRole, str]:
        """Return the stable DuckDB view name for each Atlas record role."""

        return ATLAS_DUCKDB_TABLES

    def table_name(self, role: CompactRecordRole | str) -> str:
        """Return the stable SQL view name for one compact record role."""

        try:
            normalized = role if isinstance(role, CompactRecordRole) else CompactRecordRole(role)
        except ValueError as error:
            raise AtlasDuckDBViewError(f"unsupported Atlas table role: {role}") from error
        return ATLAS_DUCKDB_TABLES[normalized]

    def query_rows(
        self,
        sql: str,
        parameters: Sequence[object] = (),
    ) -> list[dict[str, Any]]:
        """Run parameterized SQL against the disposable session and return rows."""

        with self._lock:
            self._require_open()
            result = self._connection.execute(sql, list(parameters))
            columns = [column[0] for column in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]

    def query_arrow(
        self,
        sql: str,
        parameters: Sequence[object] = (),
    ) -> pa.Table:
        """Run parameterized SQL and return an Arrow table."""

        with self._lock:
            self._require_open()
            return self._connection.execute(sql, list(parameters)).to_arrow_table()

    def facets(self) -> dict[str, Any]:
        """Return corpus counts and explorer filters."""

        releases = self.query_rows(
            """
            SELECT
                release.id,
                release.identifier,
                release.semantic_ring AS ring,
                count(resource.id) AS count
            FROM atlas_releases AS release
            LEFT JOIN atlas_resources AS resource ON resource.release = release.id
            WHERE release.release_type = 'AtlasRelease'
            GROUP BY release.id, release.identifier, release.semantic_ring
            ORDER BY lower(release.identifier), release.id
            """
        )
        rings = self.query_rows(
            """
            SELECT semantic_ring AS id, count(*) AS count
            FROM atlas_resources
            GROUP BY semantic_ring
            ORDER BY semantic_ring
            """
        )
        start_rows = self.query_rows(
            """
            WITH endpoints AS (
                SELECT subject AS id
                FROM atlas_statements
                WHERE statement_type != 'SourceAssignment'
                UNION ALL
                SELECT object AS id
                FROM atlas_statements
                WHERE statement_type != 'SourceAssignment'
            ), degrees AS (
                SELECT id, count(*) AS degree
                FROM endpoints
                GROUP BY id
            )
            SELECT id
            FROM degrees
            ORDER BY
                CASE WHEN degree BETWEEN 18 AND 48 THEN 0 ELSE 1 END,
                CASE
                    WHEN degree BETWEEN 18 AND 48
                         AND starts_with(id, 'http://eurovoc.europa.eu/')
                    THEN 0 ELSE 1
                END,
                degree DESC,
                id DESC
            LIMIT 1
            """
        )
        statement_count = self.counts[CompactRecordRole.STATEMENT.value]
        return {
            "counts": {
                "resources": self.counts[CompactRecordRole.RESOURCE.value],
                "statements": statement_count,
            },
            "graphs": [
                {
                    "authority": "Verified Atlas relation records",
                    "description": "All relations retained by the compact search view.",
                    "relationCount": statement_count,
                    "role": "asserted",
                }
            ],
            "releases": releases,
            "rings": rings,
            "start": start_rows[0]["id"] if start_rows else "",
        }

    def overview(self, *, status: str = "active") -> dict[str, Any]:
        """Return the whole-atlas map: every vocabulary and the relation volume between them.

        Deprecated-status resources (any ``record_status`` containing
        "deprecated", case-insensitively) are excluded by default; pass
        ``status="all"`` to include them. Releases whose members are
        predominantly alignment-endpoint-status, or whose identifier names
        them as an endpoint release, come back with ``satellite: true`` and a
        ``partner`` release id -- the release they share the most
        ``MappingAssertion`` volume with -- so the frontend can draw them as
        small satellites near that partner instead of as full peers.
        """

        _validate_status(status)
        nodes = self.query_rows(
            f"""
            WITH classification AS (
                SELECT
                    release,
                    count(*) AS total_members,
                    sum(
                        CASE WHEN lower(record_status) LIKE '%alignmentendpoint%' THEN 1 ELSE 0 END
                    ) AS endpoint_members
                FROM atlas_resources
                GROUP BY release
            )
            SELECT
                release.id,
                release.identifier,
                release.semantic_ring AS ring,
                count(resource.id) AS resources,
                coalesce(classification.total_members, 0) AS total_members,
                coalesce(classification.endpoint_members, 0) AS endpoint_members
            FROM atlas_releases AS release
            LEFT JOIN atlas_resources AS resource
                ON resource.release = release.id
               AND {_status_predicate("resource.record_status")}
            LEFT JOIN classification ON classification.release = release.id
            WHERE release.release_type = 'AtlasRelease'
            GROUP BY
                release.id, release.identifier, release.semantic_ring,
                classification.total_members, classification.endpoint_members
            ORDER BY lower(release.identifier), release.id
            """,
            (status,),
        )
        pairs = self.query_rows(
            f"""
            SELECT
                least(statement.source_release, statement.target_release) AS source,
                greatest(statement.source_release, statement.target_release) AS target,
                statement.statement_type,
                count(*) AS count
            FROM atlas_statements AS statement
            JOIN atlas_resources AS subject_resource ON subject_resource.id = statement.subject
            JOIN atlas_resources AS object_resource ON object_resource.id = statement.object
            WHERE {_status_predicate("subject_resource.record_status")}
              AND {_status_predicate("object_resource.record_status")}
            GROUP BY 1, 2, statement.statement_type
            ORDER BY 1, 2, statement.statement_type
            """,
            (status, status),
        )
        internal: dict[str, int] = {}
        edges: list[dict[str, Any]] = []
        for row in pairs:
            if row["source"] == row["target"]:
                internal[row["source"]] = internal.get(row["source"], 0) + row["count"]
            else:
                edges.append(row)
        for node in nodes:
            node["internalRelations"] = internal.get(node["id"], 0)
        _mark_satellites(nodes, edges)
        return {"edges": edges, "nodes": nodes}

    def release_graph(self, release_id: str, *, status: str = "active") -> dict[str, Any]:
        """Return one vocabulary's full graph: every resource and internal relation.

        Nodes are ``[id, label]`` pairs; edges are ``[subject, object, predicate,
        statementType]`` index tuples into ``nodes``, ``predicates``, and
        ``types``, so the payload stays compact for six-figure vocabularies.
        Deprecated-status resources are excluded by default; pass
        ``status="all"`` to include them.
        """

        _validate_status(status)
        release_rows = self.query_rows(
            """
            SELECT id, identifier, semantic_ring AS ring
            FROM atlas_releases
            WHERE id = ? AND release_type = 'AtlasRelease'
            """,
            (release_id,),
        )
        if len(release_rows) != 1:
            raise AtlasDuckDBViewError("release is not present in the Parquet view")
        node_rows = self.query_rows(
            f"""
            WITH ranked AS (
                SELECT
                    resource,
                    value,
                    row_number() OVER (
                        PARTITION BY resource
                        ORDER BY
                            CASE label_role
                                WHEN 'preferred' THEN 0
                                WHEN 'alternate' THEN 1
                                WHEN 'hidden' THEN 2
                                ELSE 99
                            END,
                            lower(value),
                            value
                    ) AS label_rank
                FROM atlas_labels
                WHERE lower(language) = 'en'
            )
            SELECT
                resource.id,
                coalesce(
                    ranked.value,
                    nullif(regexp_extract(resource.id, '([^#/:]+)[/#:]?$', 1), ''),
                    resource.id
                ) AS label
            FROM atlas_resources AS resource
            LEFT JOIN ranked ON ranked.resource = resource.id AND ranked.label_rank = 1
            WHERE resource.release = ?
              AND {_status_predicate("resource.record_status")}
            ORDER BY lower(label), label, resource.id
            """,
            (release_id, status),
        )
        edge_rows = self.query_rows(
            """
            SELECT subject, predicate, object, statement_type
            FROM atlas_statements
            WHERE source_release = ? AND target_release = ?
            ORDER BY id
            """,
            (release_id, release_id),
        )
        positions = {row["id"]: position for position, row in enumerate(node_rows)}
        predicates: list[str] = []
        predicate_positions: dict[str, int] = {}
        types: list[str] = []
        type_positions: dict[str, int] = {}
        edges: list[list[int]] = []
        dropped = 0
        for row in edge_rows:
            subject = positions.get(row["subject"])
            object_ = positions.get(row["object"])
            if subject is None or object_ is None:
                dropped += 1
                continue
            predicate = predicate_positions.setdefault(row["predicate"], len(predicates))
            if predicate == len(predicates):
                predicates.append(row["predicate"])
            statement_type = type_positions.setdefault(row["statement_type"], len(types))
            if statement_type == len(types):
                types.append(row["statement_type"])
            edges.append([subject, object_, predicate, statement_type])
        return {
            "counts": {
                "droppedRelations": dropped,
                "relations": len(edges),
                "resources": len(node_rows),
            },
            "edges": edges,
            "nodes": [[row["id"], row["label"]] for row in node_rows],
            "predicates": predicates,
            "release": release_rows[0],
            "types": types,
        }

    def search(
        self,
        query: str = "",
        *,
        release: str = "",
        releases: Sequence[str] = (),
        ring: str = "",
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search labels, aliases, notations, identifiers, definitions, and IRIs.

        Deprecated-status resources are excluded by default; pass
        ``status="all"`` to include them.
        """

        _validate_page(limit=limit, offset=offset)
        _validate_status(status)
        normalized = query.strip()
        release_filter = sorted({value for value in (*releases, release) if value})
        if not normalized:
            self._prepare_search_documents(full_text=False)
            return self.query_rows(
                f"""
                SELECT
                    resource.definition,
                    document.id,
                    document.label,
                    resource.notations,
                    resource.resource_profile AS profile,
                    resource.release,
                    resource.semantic_ring AS ring
                FROM atlas_search_documents AS document
                JOIN atlas_resources AS resource ON resource.id = document.id
                WHERE (? OR resource.release = ANY(?))
                  AND (? = '' OR resource.semantic_ring = ?)
                  AND {_status_predicate("resource.record_status")}
                ORDER BY lower(document.label), document.label, document.id
                LIMIT ? OFFSET ?
                """,
                (not release_filter, release_filter, ring, ring, status, limit, offset),
            )

        self._prepare_search_documents(full_text=True)
        return self.query_rows(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    label,
                    {_SEARCH_INDEX_SCHEMA}.match_bm25(id, ?) AS score
                FROM atlas_search_documents
            )
            SELECT
                resource.definition,
                ranked.id,
                ranked.label,
                resource.notations,
                resource.resource_profile AS profile,
                resource.release,
                resource.semantic_ring AS ring,
                ranked.score
            FROM ranked
            JOIN atlas_resources AS resource ON resource.id = ranked.id
            WHERE ranked.score IS NOT NULL
              AND (? OR resource.release = ANY(?))
              AND (? = '' OR resource.semantic_ring = ?)
              AND {_status_predicate("resource.record_status")}
            ORDER BY ranked.score DESC, lower(ranked.label), ranked.label, ranked.id
            LIMIT ? OFFSET ?
            """,
            (normalized, not release_filter, release_filter, ring, ring, status, limit, offset),
        )

    def resource(self, resource_id: str, *, status: str = "active") -> dict[str, Any]:
        """Return one resource, its immediate relations, and their evidence.

        The requested resource is always returned, even if it is itself
        deprecated -- it was asked for by id. Its relations to *other*
        deprecated-status resources are excluded by default; pass
        ``status="all"`` to include them.
        """

        _validate_status(status)
        resource_rows = self.query_rows(
            "SELECT * FROM atlas_resources WHERE id = ?",
            (resource_id,),
        )
        if len(resource_rows) != 1:
            raise AtlasDuckDBViewError("resource is not present in the Parquet view")
        resource = resource_rows[0]
        labels = self.query_rows(
            """
            SELECT language, label_role AS role, value
            FROM atlas_labels
            WHERE resource = ? AND lower(language) = 'en'
            ORDER BY
                CASE label_role
                    WHEN 'preferred' THEN 0
                    WHEN 'alternate' THEN 1
                    WHEN 'hidden' THEN 2
                    ELSE 99
                END,
                lower(value),
                value
            """,
            (resource_id,),
        )
        identifiers = self.query_rows(
            """
            SELECT identifier_scheme AS scheme, identifier_value AS value
            FROM atlas_identifiers
            WHERE identifies = ?
            ORDER BY lower(identifier_value), identifier_value, identifier_scheme
            """,
            (resource_id,),
        )
        relations = self.query_rows(
            f"""
            SELECT statement.*
            FROM atlas_statements AS statement
            LEFT JOIN atlas_resources AS subject_resource
                ON subject_resource.id = statement.subject
            LEFT JOIN atlas_resources AS object_resource
                ON object_resource.id = statement.object
            WHERE (statement.subject = ? OR statement.object = ?)
              AND (statement.subject = ? OR {_status_predicate("subject_resource.record_status")})
              AND (statement.object = ? OR {_status_predicate("object_resource.record_status")})
            ORDER BY statement.id
            """,
            (resource_id, resource_id, resource_id, status, resource_id, status),
        )
        relation_ids = [relation["id"] for relation in relations]
        evidence_rows = self.query_rows(
            """
            SELECT
                evidence.*,
                source.source_release,
                source.source_locator
            FROM atlas_evidence_bindings AS evidence
            LEFT JOIN atlas_source_records AS source ON source.id = evidence.source_record
            WHERE evidence.statement = ANY(?)
            ORDER BY evidence.statement, evidence.evidence_id
            """,
            (relation_ids,),
        )
        evidence_by_statement: dict[str, list[dict[str, Any]]] = {}
        for row in evidence_rows:
            evidence_by_statement.setdefault(row["statement"], []).append(
                {
                    "attestedAt": row["attested_at"],
                    "decision": row["decision"],
                    "id": f"urn:ref:atlas-evidence:{row['evidence_id'].hex()}",
                    "attestor": row["attestor"],
                    "evidenceRole": row["evidence_role"],
                    "sourceLocator": row["source_locator"],
                    "sourceRecord": row["source_record"],
                    "sourceRelease": row["source_release"],
                }
            )
        endpoint_rows = self.query_rows(
            """
            WITH endpoints AS (
                SELECT subject AS id
                FROM atlas_statements
                WHERE subject = ? OR object = ?
                UNION
                SELECT object AS id
                FROM atlas_statements
                WHERE subject = ? OR object = ?
            )
            SELECT
                endpoint.id,
                resource.release,
                resource.semantic_ring,
                resource.resource_profile,
                coalesce(
                    (
                        SELECT value
                        FROM atlas_labels
                        WHERE resource = endpoint.id AND lower(language) = 'en'
                        ORDER BY
                            CASE label_role
                                WHEN 'preferred' THEN 0
                                WHEN 'alternate' THEN 1
                                WHEN 'hidden' THEN 2
                                ELSE 99
                            END,
                            lower(value),
                            value
                        LIMIT 1
                    ),
                    regexp_extract(endpoint.id, '([^#/:]+)[/#:]?$', 1),
                    endpoint.id
                ) AS label
            FROM endpoints AS endpoint
            LEFT JOIN atlas_resources AS resource ON resource.id = endpoint.id
            """,
            (resource_id, resource_id, resource_id, resource_id),
        )
        endpoints = {row["id"]: row for row in endpoint_rows}
        for relation in relations:
            evidence = evidence_by_statement.get(relation["id"], [])
            relation["evidence"] = evidence
            relation["evidence_count"] = len(evidence)
            for endpoint in ("subject", "object"):
                endpoint_row = endpoints.get(relation[endpoint], {})
                relation[f"{endpoint}_label"] = endpoint_row.get("label") or _short(
                    relation[endpoint]
                )
                relation[f"{endpoint}_release"] = endpoint_row.get("release")
                relation[f"{endpoint}_ring"] = endpoint_row.get("semantic_ring")
                relation[f"{endpoint}_profile"] = endpoint_row.get("resource_profile")
        return {
            "definition": resource["definition"],
            "id": resource_id,
            "identifiers": identifiers,
            "labels": labels,
            "notations": resource["notations"] or [],
            "notes": resource["notes"] or [],
            "profile": resource["resource_profile"],
            "relations": relations,
            "release": resource["release"],
            "ring": resource["semantic_ring"],
            "scheme": resource["scheme"],
            "sourceRecord": resource["source_record"],
            "status": resource["record_status"],
        }

    def agency_projection_available(self) -> bool:
        """Report whether this view ships the REF-038 agency-projection tables.

        Older views built before REF-038, or before the source rosters the
        projection is built from existed, do not carry them; callers should
        degrade gracefully rather than error.
        """

        with self._lock:
            self._require_open()
            return self._agency_projection_paths() is not None

    def agency_projection(self, query: str = "") -> dict[str, Any]:
        """Return the REF-038 agency-projection lookup table for the explorer.

        ``resolved`` rows come from ``agency-projection.parquet``: one row per
        source value with its resolved org, mapping basis, evidence tier and
        warrant, parent org, and aliases. ``unresolved`` rows come from
        ``agency-projection-unresolved.parquet``: source values REF-038
        abstained on, with their abstention reason. Both are filtered by a
        case-insensitive substring match against the source value, resolved
        label, aliases, and abbreviations when ``query`` is non-empty.

        Returns ``{"available": False, ...}`` without error when this view
        does not carry the projection tables at all.
        """

        if not self._prepare_agency_projection():
            return {"available": False, "resolved": [], "unresolved": []}
        normalized = query.strip().lower()
        pattern = f"%{normalized}%"
        resolved = self.query_rows(
            f"""
            SELECT
                projection.source_value_kind,
                projection.source_value,
                projection.org,
                projection.pref_label,
                projection.abbreviations,
                projection.aliases,
                projection.parent_org,
                projection.basis,
                projection.evidence_tier,
                projection.warrant,
                len(projection.evidence_records) AS evidence_count,
                resource.id IS NOT NULL AS org_known
            FROM {_AGENCY_PROJECTION_VIEW} AS projection
            LEFT JOIN atlas_resources AS resource ON resource.id = projection.org
            WHERE ? = ''
               OR lower(projection.source_value) LIKE ?
               OR lower(projection.pref_label) LIKE ?
               OR lower(array_to_string(projection.aliases, ' ')) LIKE ?
               OR lower(array_to_string(projection.abbreviations, ' ')) LIKE ?
            ORDER BY lower(projection.source_value), projection.source_value
            """,
            (normalized, pattern, pattern, pattern, pattern),
        )
        unresolved = self.query_rows(
            f"""
            SELECT
                source_value_kind,
                source_value,
                source_org,
                pref_label,
                source_parent_org,
                reason,
                reasoning
            FROM {_AGENCY_PROJECTION_UNRESOLVED_VIEW}
            WHERE ? = ''
               OR lower(source_value) LIKE ?
               OR lower(pref_label) LIKE ?
            ORDER BY lower(source_value), source_value
            """,
            (normalized, pattern, pattern),
        )
        return {"available": True, "resolved": resolved, "unresolved": unresolved}

    def close(self) -> None:
        """Close the query session and remove its disposable database."""

        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True
            self._temporary_directory.cleanup()

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise AtlasDuckDBViewError("Atlas DuckDB query session is closed")

    def _prepare_search_documents(self, *, full_text: bool) -> None:
        with self._lock:
            self._require_open()
            if not self._table_exists(ATLAS_SEARCH_DOCUMENTS_TABLE):
                self._connection.execute(
                    """
                    CREATE TABLE atlas_search_documents AS
                    WITH label_groups AS (
                        SELECT
                            resource,
                            first(
                                value
                                ORDER BY
                                    CASE label_role
                                        WHEN 'preferred' THEN 0
                                        WHEN 'alternate' THEN 1
                                        WHEN 'hidden' THEN 2
                                        ELSE 99
                                    END,
                                    lower(value),
                                    value
                            ) AS display_label,
                            string_agg(value, ' ' ORDER BY lower(value), value) AS aliases
                        FROM atlas_labels
                        WHERE lower(language) = 'en'
                        GROUP BY resource
                    ), identifier_groups AS (
                        SELECT
                            identifies AS resource,
                            string_agg(
                                identifier_value,
                                ' '
                                ORDER BY lower(identifier_value), identifier_value
                            ) AS identifiers
                        FROM atlas_identifiers
                        GROUP BY identifies
                    )
                    SELECT
                        resource.id,
                        coalesce(
                            labels.display_label,
                            nullif(regexp_extract(resource.id, '([^#/:]+)[/#:]?$', 1), ''),
                            resource.id
                        ) AS label,
                        concat_ws(
                            ' ',
                            labels.aliases,
                            array_to_string(resource.notations, ' '),
                            identifiers.identifiers,
                            resource.id,
                            resource.definition
                        ) AS search_text
                    FROM atlas_resources AS resource
                    LEFT JOIN label_groups AS labels ON labels.resource = resource.id
                    LEFT JOIN identifier_groups AS identifiers ON identifiers.resource = resource.id
                    ORDER BY resource.id
                    """
                )
            if not full_text or self._search_ready:
                return
            try:
                try:
                    self._connection.execute("LOAD fts")
                except duckdb.Error:
                    self._connection.execute("INSTALL fts")
                    self._connection.execute("LOAD fts")
                self._connection.execute(
                    """
                    PRAGMA create_fts_index(
                        'atlas_search_documents',
                        'id',
                        'search_text',
                        stemmer = 'none',
                        stopwords = 'none',
                        ignore = '(\\.|[^a-z0-9])+'
                    )
                    """
                )
            except duckdb.Error as error:
                raise AtlasDuckDBViewError(
                    "DuckDB full-text search is unavailable; install the official fts "
                    "extension once while network access is available"
                ) from error
            self._search_ready = True

    def _agency_projection_paths(self) -> tuple[Path, Path] | None:
        resolved = self.root / "tables" / _AGENCY_PROJECTION_TABLE_FILE
        unresolved = self.root / "tables" / _AGENCY_PROJECTION_UNRESOLVED_TABLE_FILE
        if resolved.is_file() and unresolved.is_file():
            return resolved, unresolved
        return None

    def _prepare_agency_projection(self) -> bool:
        with self._lock:
            self._require_open()
            if self._agency_projection_ready:
                return True
            paths = self._agency_projection_paths()
            if paths is None:
                return False
            resolved_path, unresolved_path = paths
            if not self._table_exists(_AGENCY_PROJECTION_VIEW):
                self._connection.read_parquet(str(resolved_path)).create_view(
                    _AGENCY_PROJECTION_VIEW
                )
            if not self._table_exists(_AGENCY_PROJECTION_UNRESOLVED_VIEW):
                self._connection.read_parquet(str(unresolved_path)).create_view(
                    _AGENCY_PROJECTION_UNRESOLVED_VIEW
                )
            self._agency_projection_ready = True
            return True

    def _table_exists(self, table: str) -> bool:
        return bool(
            self._connection.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table],
            ).fetchone()
        )


def open_atlas_duckdb_view(
    root: str | Path,
    *,
    trusted_manifest_digest: str,
) -> AtlasDuckDBView:
    """Open a verified Atlas Parquet query view."""

    return AtlasDuckDBView.open(root, trusted_manifest_digest=trusted_manifest_digest)


def _validate_page(*, limit: int, offset: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _SEARCH_LIMIT_MAXIMUM:
        raise AtlasDuckDBViewError(f"search limit must be between 1 and {_SEARCH_LIMIT_MAXIMUM}")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise AtlasDuckDBViewError("search offset must be zero or greater")


def _validate_status(status: str) -> None:
    if status not in _STATUS_FILTERS:
        raise AtlasDuckDBViewError(
            f"status filter must be one of {sorted(_STATUS_FILTERS)}, got {status!r}"
        )


def _status_predicate(column: str) -> str:
    """Return a parameterized SQL predicate hiding deprecated-status rows.

    A ``record_status`` is deprecated when it contains "deprecated" anywhere,
    case-insensitively -- not a fixed enum of today's known status strings --
    so a newly introduced ``*deprecated*`` status is hidden automatically.
    The caller supplies the ``status`` value ("active" or "all") as the one
    query parameter this fragment consumes, in the position where it appears.
    """

    return f"(? = 'all' OR {column} IS NULL OR lower({column}) NOT LIKE '%deprecated%')"


def _mark_satellites(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Flag satellite (alignment-endpoint) releases and their strongest partner.

    A release is a satellite when at least half its members carry an
    alignment-endpoint-flavoured status (matched the same permissive way as
    deprecation: substring, case-insensitive, so new endpoint-status variants
    are covered automatically), or its identifier names it as an endpoint
    release. Its partner is the other release it shares the most
    ``MappingAssertion`` volume with; releases with no mapping relations of
    their own fall back to their strongest relation of any type.

    Mutates ``nodes`` in place: drops the classification-only fields and adds
    ``satellite`` and ``partner``.
    """

    mapping_neighbors: dict[str, dict[str, int]] = defaultdict(dict)
    any_neighbors: dict[str, dict[str, int]] = defaultdict(dict)
    for edge in edges:
        source, target, count = edge["source"], edge["target"], edge["count"]
        any_neighbors[source][target] = any_neighbors[source].get(target, 0) + count
        any_neighbors[target][source] = any_neighbors[target].get(source, 0) + count
        if edge["statement_type"] == "MappingAssertion":
            mapping_neighbors[source][target] = mapping_neighbors[source].get(target, 0) + count
            mapping_neighbors[target][source] = mapping_neighbors[target].get(source, 0) + count

    def best_partner(node_id: str) -> str | None:
        for neighbors in (mapping_neighbors.get(node_id), any_neighbors.get(node_id)):
            if neighbors:
                return max(neighbors.items(), key=lambda item: (item[1], item[0]))[0]
        return None

    for node in nodes:
        total = node.pop("total_members")
        endpoint = node.pop("endpoint_members")
        is_endpoint_named = bool(_ENDPOINT_RELEASE_PATTERN.search(node["identifier"] or ""))
        is_endpoint_majority = bool(total) and endpoint / total >= 0.5
        node["satellite"] = is_endpoint_majority or is_endpoint_named
        node["partner"] = best_partner(node["id"]) if node["satellite"] else None


def _short(value: str | None) -> str:
    if not value:
        return ""
    return value.rsplit("#", 1)[-1].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


__all__ = [
    "ATLAS_DUCKDB_TABLES",
    "ATLAS_SEARCH_DOCUMENTS_TABLE",
    "AtlasDuckDBView",
    "AtlasDuckDBViewError",
    "open_atlas_duckdb_view",
]

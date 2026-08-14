"""Query a verified Atlas compact Parquet view with DuckDB.

The Parquet artifact remains the authenticated input.  This module creates a
disposable DuckDB database outside that artifact, exposes stable SQL view names,
and builds a local full-text index only when text search is first requested.
"""

from __future__ import annotations

import tempfile
import threading
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

    def overview(self) -> dict[str, Any]:
        """Return the whole-atlas map: every vocabulary and the relation volume between them."""

        nodes = self.query_rows(
            """
            SELECT
                release.id,
                release.identifier,
                release.semantic_ring AS ring,
                count(resource.id) AS resources
            FROM atlas_releases AS release
            LEFT JOIN atlas_resources AS resource ON resource.release = release.id
            WHERE release.release_type = 'AtlasRelease'
            GROUP BY release.id, release.identifier, release.semantic_ring
            ORDER BY lower(release.identifier), release.id
            """
        )
        pairs = self.query_rows(
            """
            SELECT
                least(source_release, target_release) AS source,
                greatest(source_release, target_release) AS target,
                statement_type,
                count(*) AS count
            FROM atlas_statements
            GROUP BY 1, 2, statement_type
            ORDER BY 1, 2, statement_type
            """
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
        return {"edges": edges, "nodes": nodes}

    def release_graph(self, release_id: str) -> dict[str, Any]:
        """Return one vocabulary's full graph: every resource and internal relation.

        Nodes are ``[id, label]`` pairs; edges are ``[subject, object, predicate,
        statementType]`` index tuples into ``nodes``, ``predicates``, and
        ``types``, so the payload stays compact for six-figure vocabularies.
        """

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
            """
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
            ORDER BY lower(label), label, resource.id
            """,
            (release_id,),
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
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search labels, aliases, notations, identifiers, definitions, and IRIs."""

        _validate_page(limit=limit, offset=offset)
        normalized = query.strip()
        release_filter = sorted({value for value in (*releases, release) if value})
        if not normalized:
            self._prepare_search_documents(full_text=False)
            return self.query_rows(
                """
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
                ORDER BY lower(document.label), document.label, document.id
                LIMIT ? OFFSET ?
                """,
                (not release_filter, release_filter, ring, ring, limit, offset),
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
            ORDER BY ranked.score DESC, lower(ranked.label), ranked.label, ranked.id
            LIMIT ? OFFSET ?
            """,
            (normalized, not release_filter, release_filter, ring, ring, limit, offset),
        )

    def resource(self, resource_id: str) -> dict[str, Any]:
        """Return one resource, its immediate relations, and their evidence."""

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
            """
            SELECT *
            FROM atlas_statements
            WHERE subject = ? OR object = ?
            ORDER BY id
            """,
            (resource_id, resource_id),
        )
        evidence_rows = self.query_rows(
            """
            SELECT
                evidence.*,
                source.source_release,
                source.source_locator
            FROM atlas_evidence_bindings AS evidence
            LEFT JOIN atlas_source_records AS source ON source.id = evidence.source_record
            WHERE evidence.statement IN (
                SELECT id
                FROM atlas_statements
                WHERE subject = ? OR object = ?
            )
            ORDER BY evidence.statement, evidence.evidence_id
            """,
            (resource_id, resource_id),
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

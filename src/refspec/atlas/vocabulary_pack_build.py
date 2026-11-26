"""Offline DuckDB-to-SQLite compiler for sealed Atlas Vocabulary Packs (schema v3).

Split out of ``refspec.atlas.vocabulary_pack`` so the read-only serving runtime
stays strictly stdlib-only without touching DuckDB or Parquet build machinery.
Module top-level imports stay stdlib-only too (``duckdb`` and
``parquet_search_view`` are imported lazily inside ``build_vocabulary_pack``).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sqlite3
import sys
import tempfile
from array import array
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from refspec.atlas.vocabulary_protocols import (
    VocabularyInputError,
    VocabularyPackError,
    normalize_text,
)

PACK_RECORD_TYPE = "AtlasVocabularyPack"
PACK_SCHEMA_VERSION = "3"
SUPPORTED_PACK_SCHEMA_VERSIONS: frozenset[str] = frozenset({"2", "3"})
PACK_POLICY_VERSION = "3"

DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY: float = 0.07
DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY: float = 0.04
DEFAULT_STRUCTURAL_LONG_LABEL_CHARS: int = 80

_SKOS = "http://www.w3.org/2004/02/skos/core#"
_BROADER_URI = _SKOS + "broader"
_NARROWER_URI = _SKOS + "narrower"
NATIVE_RELATION_PREDICATES: tuple[str, ...] = (
    _BROADER_URI,
    _NARROWER_URI,
    _SKOS + "related",
)
MAPPING_RELATION_PREDICATES: tuple[str, ...] = (
    _SKOS + "exactMatch",
    _SKOS + "closeMatch",
    _SKOS + "broadMatch",
    _SKOS + "narrowMatch",
    _SKOS + "relatedMatch",
)
SYMMETRIC_MAPPING_PREDICATES: frozenset[str] = frozenset(
    {
        _SKOS + "exactMatch",
        _SKOS + "closeMatch",
        _SKOS + "relatedMatch",
    }
)
DERIVED_RELATION_PREDICATES: tuple[str, ...] = (
    _BROADER_URI,
    _NARROWER_URI,
    _SKOS + "related",
    _SKOS + "closeMatch",
    _SKOS + "exactMatch",
)

# REF-035: default-serving eligible evidence roles with approved decisions.
_REF035_DEFAULT_EVIDENCE_ROLES: tuple[str, ...] = (
    "https://rulespec.org/ns/v1#officialSourceMetadata",
    "https://rulespec.org/ns/v1#formalAdoptionEvent",
    "https://rulespec.org/ns/v1#structuralEvidence",
)
_REF035_APPROVED_DECISION = "https://rulespec.org/ns/v1#approved"

# Common high-frequency RefSpec URN prefixes compressed losslessly via uri_prefixes table.
_KNOWN_URI_PREFIXES: tuple[str, ...] = (
    "urn:ref:atlas-label:",
    "urn:ref:atlas-assertion:",
    "urn:ref:atlas-source-record:",
    "urn:ref:atlas-derived:",
    "urn:ref:derived:",
    "urn:ref:source-concept:",
)

_STMT_KIND_NATIVE = 0
_STMT_KIND_MAPPING = 1
_STMT_KIND_DERIVED = 2

_STREAM_BATCH_SIZE = 50_000
_PARQUET_VIEW_MANIFEST_FILE = "view-manifest.json"
_SEARCH_VIEW_MANIFEST_FILE = "search-view-manifest.json"
_DARWIN_SYSTEM_SYMLINKS = frozenset({"/var", "/tmp", "/etc"})

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


@dataclass(frozen=True, slots=True)
class VocabularyPackManifest:
    """Immutable metadata and integrity summary for a compiled Vocabulary Pack."""

    pack_path: Path
    pack_id: str
    pack_sha256: str
    size_bytes: int
    source_view_id: str
    source_manifest_digest: str
    schemes: tuple[str, ...]
    languages: tuple[str, ...]
    schema_version: str
    policy_version: str
    include_mappings: bool
    include_derived: bool
    resource_count: int
    labeled_resource_count: int
    label_count: int
    native_edge_count: int
    mapping_edge_count: int
    derived_edge_count: int
    vocab_term_count: int
    built_at: str
    broader_cycle_count: int = 0
    quarantined_cycle_edges: int = 0
    narrower_cycle_count: int = 0
    quarantined_narrower_cycle_edges: int = 0
    agency_change_event_count: int = 0
    agency_projection_count: int = 0
    source_view_kind: str = "parquet-search-view"

    def to_dict(self) -> dict[str, Any]:
        return {
            "recordType": PACK_RECORD_TYPE,
            "schemaVersion": self.schema_version,
            "policyVersion": self.policy_version,
            "packPath": str(self.pack_path),
            "packId": self.pack_id,
            "packSha256": self.pack_sha256,
            "sizeBytes": self.size_bytes,
            "sourceViewId": self.source_view_id,
            "sourceViewKind": self.source_view_kind,
            "sourceManifestDigest": self.source_manifest_digest,
            "schemes": list(self.schemes),
            "languages": list(self.languages),
            "includeMappings": self.include_mappings,
            "includeDerived": self.include_derived,
            "counts": {
                "resources": self.resource_count,
                "labeledResources": self.labeled_resource_count,
                "labels": self.label_count,
                "nativeEdges": self.native_edge_count,
                "mappingEdges": self.mapping_edge_count,
                "derivedEdges": self.derived_edge_count,
                "vocabTerms": self.vocab_term_count,
                "broaderCycles": self.broader_cycle_count,
                "narrowerCycles": self.narrower_cycle_count,
                "quarantinedCycleEdges": self.quarantined_cycle_edges,
                "quarantinedNarrowerCycleEdges": self.quarantined_narrower_cycle_edges,
                "agencyChangeEvents": self.agency_change_event_count,
                "agencyProjections": self.agency_projection_count,
            },
            "builtAt": self.built_at,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _compute_pack_id(parts: Mapping[str, Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"urn:ref:vocabulary-pack:{hashlib.sha256(payload).hexdigest()}"


def _normalize_digest(value: str, *, error_code: str = "invalid_digest") -> str:
    if not isinstance(value, str):
        raise VocabularyPackError(error_code, "digest must be a 64-character hex sha256 string")
    match = _SHA256_RE.fullmatch(value.strip().lower())
    if match is None:
        raise VocabularyPackError(error_code, "digest must be a 64-character hex sha256 string")
    return f"sha256:{match.group(1)}"


def _normalize_schemes(schemes: Iterable[str]) -> tuple[str, ...]:
    if isinstance(schemes, (str, bytes)):
        raise VocabularyInputError("invalid_schemes", "schemes must be a sequence of URIs")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in schemes:
        if not isinstance(item, str) or not _SCHEME_RE.fullmatch(item):
            raise VocabularyInputError("invalid_schemes", f"unsupported scheme identifier: {item!r}")
        if item not in seen:
            seen.add(item)
            cleaned.append(item)
    if not cleaned:
        raise VocabularyInputError("invalid_schemes", "at least one Atlas scheme is required")
    return tuple(sorted(cleaned))


def _normalize_languages(languages: Iterable[str]) -> tuple[str, ...]:
    if isinstance(languages, (str, bytes)):
        raise VocabularyInputError("invalid_languages", "languages must be a sequence of language tags")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in languages:
        if not isinstance(item, str) or not _LANGUAGE_RE.fullmatch(item.strip()):
            raise VocabularyInputError("invalid_languages", f"unsupported language tag: {item!r}")
        norm = item.strip().lower()
        if norm not in seen:
            seen.add(norm)
            cleaned.append(norm)
    if not cleaned:
        raise VocabularyInputError("invalid_languages", "at least one language tag is required")
    return tuple(cleaned)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def _split_uri_prefix(uri: str, prefix_to_id: Mapping[str, int]) -> tuple[int, str]:
    for prefix, pid in prefix_to_id.items():
        if prefix and uri.startswith(prefix):
            return pid, uri[len(prefix) :]
    return 0, uri


def _ensure_fts5(con: sqlite3.Connection) -> None:
    try:
        opts = {row[0] for row in con.execute("PRAGMA compile_options")}
    except sqlite3.Error as exc:
        raise VocabularyPackError("missing_fts5", f"SQLite connection failed capability probe: {exc}") from exc
    if "ENABLE_FTS5" not in opts:
        raise VocabularyPackError("missing_fts5", "SQLite runtime was compiled without FTS5 support")


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _reject_symlink_path(raw: Path, *, error_code: str, label: str) -> None:
    """Reject a symlink target or non-system symlinked parent component before calling ``.resolve()``."""

    if raw.is_symlink():
        raise VocabularyPackError(error_code, f"{label} must not be a symlink: {raw}")
    for parent in raw.parents:
        if sys.platform == "darwin" and str(parent) in _DARWIN_SYSTEM_SYMLINKS:
            continue
        if parent.is_symlink():
            raise VocabularyPackError(error_code, f"{label} traverses a symlinked parent directory: {parent}")


def _to_little_endian_bytes(arr: array) -> bytes:
    if sys.byteorder != "little":
        swapped = array(arr.typecode, arr)
        swapped.byteswap()
        return swapped.tobytes()
    return arr.tobytes()


def _iterative_tarjan_sccs(adj: Mapping[int, Sequence[int]]) -> list[list[int]]:
    """Strictly iterative Tarjan's SCC over directed integer graph; returns SCCs of size >= 2."""

    index_counter = 0
    index: dict[int, int] = {}
    lowlink: dict[int, int] = {}
    on_stack: set[int] = set()
    tarjan_stack: list[int] = []
    cycle_sccs: list[list[int]] = []

    for start in adj:
        if start in index:
            continue
        call_stack: list[list[int]] = [[start, 0]]
        index[start] = lowlink[start] = index_counter
        index_counter += 1
        tarjan_stack.append(start)
        on_stack.add(start)

        while call_stack:
            frame = call_stack[-1]
            v = frame[0]
            nbrs = adj.get(v)
            if nbrs is not None and frame[1] < len(nbrs):
                w = nbrs[frame[1]]
                frame[1] += 1
                if w not in index:
                    index[w] = lowlink[w] = index_counter
                    index_counter += 1
                    tarjan_stack.append(w)
                    on_stack.add(w)
                    call_stack.append([w, 0])
                elif w in on_stack and index[w] < lowlink[v]:
                    lowlink[v] = index[w]
            else:
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    if lowlink[v] < lowlink[parent]:
                        lowlink[parent] = lowlink[v]
                if lowlink[v] == index[v]:
                    scc: list[int] = []
                    while True:
                        w = tarjan_stack.pop()
                        on_stack.remove(w)
                        scc.append(w)
                        if w == v:
                            break
                    if len(scc) >= 2:
                        cycle_sccs.append(scc)
    return cycle_sccs


def _detect_and_quarantine_hierarchy_cycles(
    con_sql: sqlite3.Connection,
    pids: Sequence[int],
    *,
    quarantine: bool,
) -> tuple[int, int]:
    """Detect SCC cycles over one hierarchy predicate family and optionally quarantine intra-SCC edges."""

    if not pids:
        return 0, 0
    p_ph = ",".join("?" for _ in pids)
    adj: dict[int, list[int]] = defaultdict(list)
    for src_rid, dst_rid in con_sql.execute(
        f"SELECT src_rid, dst_rid FROM edges WHERE pid IN ({p_ph})",
        list(pids),
    ):
        adj[int(src_rid)].append(int(dst_rid))

    cycle_sccs = _iterative_tarjan_sccs(adj)
    del adj
    cycle_count = len(cycle_sccs)
    quarantined = 0
    if cycle_sccs and quarantine:
        node_to_scc: dict[int, int] = {}
        for scc_idx, scc_nodes in enumerate(cycle_sccs):
            for node in scc_nodes:
                node_to_scc[node] = scc_idx

        cycle_edge_keys: list[tuple[int, int, int, int, str, int]] = []
        for src_rid, stmt_kind, pid, spfx, ssuf, dst_rid in con_sql.execute(
            f"SELECT src_rid, stmt_kind, pid, stmt_pfx, stmt_suffix, dst_rid FROM edges WHERE pid IN ({p_ph})",
            list(pids),
        ):
            s_scc = node_to_scc.get(int(src_rid))
            if s_scc is not None and node_to_scc.get(int(dst_rid)) == s_scc:
                cycle_edge_keys.append(
                    (int(src_rid), int(stmt_kind), int(pid), int(spfx), str(ssuf), int(dst_rid))
                )
        if cycle_edge_keys:
            con_sql.executemany(
                """
                DELETE FROM edges
                WHERE src_rid = ? AND stmt_kind = ? AND pid = ?
                  AND stmt_pfx = ? AND stmt_suffix = ? AND dst_rid = ?
                """,
                cycle_edge_keys,
            )
            quarantined = len(cycle_edge_keys)
    return cycle_count, quarantined


def _build_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE pack_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE pack_meta_blobs (
            key TEXT PRIMARY KEY,
            payload BLOB NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE uri_prefixes (
            pfx_id INTEGER PRIMARY KEY,
            prefix TEXT NOT NULL UNIQUE
        );

        CREATE TABLE schemes (
            sid INTEGER PRIMARY KEY,
            uri TEXT NOT NULL UNIQUE
        );

        CREATE TABLE releases (
            rel_id INTEGER PRIMARY KEY,
            uri TEXT NOT NULL UNIQUE
        );

        CREATE TABLE predicates (
            pid INTEGER PRIMARY KEY,
            uri TEXT NOT NULL,
            stmt_type TEXT NOT NULL,
            symmetric INTEGER NOT NULL,
            UNIQUE(uri, stmt_type)
        );

        CREATE TABLE derivation_rules (
            rule_id INTEGER PRIMARY KEY,
            uri TEXT NOT NULL UNIQUE
        );

        CREATE TABLE resources (
            rid INTEGER PRIMARY KEY,
            id TEXT NOT NULL,
            sid INTEGER NOT NULL,
            rel_id INTEGER NOT NULL,
            definition TEXT,
            src_pfx INTEGER NOT NULL,
            src_suffix TEXT NOT NULL,
            notations_json TEXT,
            pref_label TEXT,
            label_count INTEGER NOT NULL,
            has_preferred INTEGER NOT NULL DEFAULT 1,
            UNIQUE(id, sid, rel_id)
        );

        CREATE TABLE labels (
            rid INTEGER NOT NULL,
            role_rank INTEGER NOT NULL,
            value_lower TEXT NOT NULL,
            value TEXT NOT NULL,
            lbl_pfx INTEGER NOT NULL,
            lbl_suffix TEXT NOT NULL,
            role TEXT NOT NULL,
            language TEXT NOT NULL,
            PRIMARY KEY (rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix)
        ) WITHOUT ROWID;

        CREATE TABLE label_exact (
            value_lower TEXT NOT NULL,
            role_rank INTEGER NOT NULL,
            rid INTEGER NOT NULL,
            PRIMARY KEY (value_lower, role_rank, rid)
        ) WITHOUT ROWID;

        CREATE TABLE edges (
            src_rid INTEGER NOT NULL,
            stmt_kind INTEGER NOT NULL,
            pid INTEGER NOT NULL,
            stmt_pfx INTEGER NOT NULL,
            stmt_suffix TEXT NOT NULL,
            dst_rid INTEGER NOT NULL,
            ref035_default INTEGER NOT NULL,
            rule_id INTEGER NOT NULL,
            PRIMARY KEY (src_rid, stmt_kind, pid, stmt_pfx, stmt_suffix, dst_rid)
        ) WITHOUT ROWID;

        CREATE TABLE edges_rev (
            dst_rid INTEGER NOT NULL,
            pid INTEGER NOT NULL,
            stmt_pfx INTEGER NOT NULL,
            stmt_suffix TEXT NOT NULL,
            src_rid INTEGER NOT NULL,
            ref035_default INTEGER NOT NULL,
            PRIMARY KEY (dst_rid, pid, stmt_pfx, stmt_suffix, src_rid)
        ) WITHOUT ROWID;

        CREATE TABLE vocab_terms (
            tid INTEGER PRIMARY KEY,
            term TEXT NOT NULL UNIQUE,
            doc_freq INTEGER NOT NULL
        );

        CREATE VIRTUAL TABLE concepts_bm25 USING fts5(
            pref_text,
            alt_text,
            def_text,
            content='',
            tokenize='unicode61 remove_diacritics 2',
            prefix='2 3'
        );

        CREATE VIRTUAL TABLE vocab_terms_trigram USING fts5(
            term,
            content='vocab_terms',
            content_rowid='tid',
            tokenize='trigram case_sensitive 0'
        );

        CREATE TABLE agency_change_events (
            event_id TEXT PRIMARY KEY,
            applies_to TEXT NOT NULL,
            event_kind TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            source_records_json TEXT NOT NULL,
            from_release TEXT,
            to_release TEXT
        ) WITHOUT ROWID;

        CREATE INDEX idx_agency_change_events_applies_to
            ON agency_change_events (applies_to, effective_date, event_id);

        CREATE TABLE agency_projections (
            source_value_kind TEXT NOT NULL,
            source_value TEXT NOT NULL,
            org TEXT NOT NULL,
            pref_label TEXT NOT NULL,
            abbreviations_json TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            parent_org TEXT,
            relation TEXT NOT NULL,
            evidence_tier TEXT NOT NULL,
            warrant TEXT NOT NULL,
            basis TEXT NOT NULL,
            evidence_record_count INTEGER NOT NULL,
            PRIMARY KEY (source_value_kind, source_value, org)
        ) WITHOUT ROWID;

        CREATE INDEX idx_agency_projections_org
            ON agency_projections (org, source_value_kind, source_value);
        """
    )


def _safe_view_member_path(resolved_view: Path, relative: object) -> Path:
    """Resolve one manifest-declared member path under `resolved_view`, refusing traversal and symlinks."""

    if not isinstance(relative, str) or not relative:
        raise VocabularyPackError("invalid_view", "view manifest member states no path")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise VocabularyPackError("invalid_view", f"view manifest member path is unsafe: {relative!r}")
    cursor = resolved_view
    for part in parsed.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise VocabularyPackError("invalid_view", f"view member must not be a symlink: {cursor}")
    if not cursor.is_file():
        raise VocabularyPackError("invalid_view", f"view member is missing or not a regular file: {cursor}")
    return cursor


def _discover_optional_search_view_roles(
    manifest_file: Path,
    *,
    candidate_roles: Sequence[str],
) -> list[str]:
    """Read optional member roles declared in `search-view-manifest.json` without trusting symlinks."""

    if manifest_file.is_symlink():
        raise VocabularyPackError("invalid_view", "search view manifest must not be a symlink")
    if not manifest_file.is_file():
        return []
    try:
        raw_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw_manifest, dict) or not isinstance(raw_manifest.get("members"), list):
        return []
    declared = {
        str(m["role"])
        for m in raw_manifest["members"]
        if isinstance(m, dict) and isinstance(m.get("role"), str)
    }
    return [role for role in candidate_roles if role in declared]


def build_vocabulary_pack(
    view_root: Path | str,
    output_path: Path | str,
    *,
    trusted_manifest_digest: str,
    schemes: Iterable[str] | None = None,
    languages: Iterable[str] = ("en",),
    include_mappings: bool = True,
    include_derived: bool = True,
    quarantine_broader_cycles: bool = True,
    include_agency_tables: bool | None = None,
    verify_all_view_members: bool = False,
    view_verifier: Callable[..., dict[str, Any]] | None = None,
) -> VocabularyPackManifest:
    """Compile a verified Atlas 3.1 Parquet view into a sealed SQLite pack (schema v3).

    Accepts EITHER a direct Atlas ``parquet-view`` directory (``view-manifest.json``,
    verified via ``refspec.atlas.parquet_view``) OR a legacy compact
    ``parquet-search-view`` directory (``search-view-manifest.json``, verified via
    ``refspec.atlas.parquet_search_view``). Streams DuckDB batches into normalized
    ``WITHOUT ROWID`` tables with lossless URI prefix compression, skips resources
    with zero labels in the selected languages, drops reflexive self-loops, runs
    strictly iterative Tarjan's SCC cycle detection over both ``skos:broader`` and
    ``skos:narrower``, persists neutral structural prior and ``sid_by_rid_u16`` blobs
    in ``pack_meta_blobs``, and ingests ``lifecycle-events.parquet`` and
    ``agency-projection.parquet`` when ``include_agency_tables`` is enabled (defaulting
    to ``True`` when ``schemes is None`` or any selected resource belongs to the
    ``entity`` ring, and ``False`` for strictly non-entity subject-only subsets).
    """

    import duckdb

    if include_agency_tables is not None and not isinstance(include_agency_tables, bool):
        raise VocabularyInputError("invalid_option", "include_agency_tables must be a bool or None")

    raw_view = Path(view_root)
    _reject_symlink_path(raw_view, error_code="invalid_view_root", label="Atlas view path")
    try:
        resolved_view = raw_view.resolve(strict=True)
    except OSError as exc:
        raise VocabularyPackError("invalid_view_root", f"Atlas view path does not exist: {view_root}") from exc
    if not resolved_view.is_dir():
        raise VocabularyPackError("invalid_view_root", f"Atlas view path is not a directory: {view_root}")

    raw_out = Path(output_path)
    _reject_symlink_path(raw_out, error_code="invalid_pack", label="output vocabulary pack path")

    norm_schemes = None if schemes is None else _normalize_schemes(schemes)
    norm_languages = _normalize_languages(languages)
    expected_digest = _normalize_digest(trusted_manifest_digest)

    parquet_manifest_file = resolved_view / _PARQUET_VIEW_MANIFEST_FILE
    search_manifest_file = resolved_view / _SEARCH_VIEW_MANIFEST_FILE
    if parquet_manifest_file.is_symlink():
        raise VocabularyPackError("invalid_view", "Parquet view manifest must not be a symlink")
    if search_manifest_file.is_symlink():
        raise VocabularyPackError("invalid_view", "search view manifest must not be a symlink")
    has_parquet_manifest = parquet_manifest_file.is_file()
    has_search_manifest = search_manifest_file.is_file()
    if has_parquet_manifest and has_search_manifest:
        raise VocabularyPackError(
            "invalid_view",
            f"ambiguous Atlas view directory holds both {_PARQUET_VIEW_MANIFEST_FILE} and {_SEARCH_VIEW_MANIFEST_FILE}",
        )

    # Discover optional member roles via manifest["members"] rather than hardcoding filenames.
    optional_candidates: list[str] = []
    if include_derived:
        optional_candidates.append("derivedRelations")
    if include_agency_tables is not False:
        optional_candidates.extend(["LifecycleEvent", "agencyProjection"])

    roles_to_verify: list[str] | None = None
    if not verify_all_view_members:
        roles_to_verify = ["Resource", "Label", "Statement"]
        if include_mappings:
            roles_to_verify.append("EvidenceBinding")
        if has_search_manifest and optional_candidates:
            roles_to_verify.extend(
                _discover_optional_search_view_roles(
                    search_manifest_file,
                    candidate_roles=optional_candidates,
                )
            )

    if view_verifier is not None:
        source_view_kind = "parquet-view" if has_parquet_manifest else "parquet-search-view"
        params = inspect.signature(view_verifier).parameters
        accepts_roles = "roles" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        try:
            if accepts_roles:
                manifest = view_verifier(
                    resolved_view,
                    expected_manifest_digest=expected_digest,
                    roles=roles_to_verify,
                )
            else:
                manifest = view_verifier(
                    resolved_view,
                    expected_manifest_digest=expected_digest,
                )
        except Exception as exc:
            if isinstance(exc, VocabularyPackError):
                raise
            raise VocabularyPackError("invalid_view", str(exc)) from exc
    elif has_parquet_manifest:
        from refspec.atlas.parquet_view import (
            AtlasParquetViewError,
            verify_atlas_parquet_view,
        )

        source_view_kind = "parquet-view"
        try:
            manifest = verify_atlas_parquet_view(
                resolved_view,
                expected_manifest_digest=expected_digest,
            )
        except AtlasParquetViewError as exc:
            raise VocabularyPackError("invalid_view", str(exc)) from exc
    elif has_search_manifest:
        from refspec.atlas.parquet_search_view import (
            AtlasParquetSearchViewError,
            verify_atlas_parquet_search_view,
        )

        source_view_kind = "parquet-search-view"
        try:
            manifest = verify_atlas_parquet_search_view(
                resolved_view,
                expected_manifest_digest=expected_digest,
                roles=roles_to_verify,
            )
        except AtlasParquetSearchViewError as exc:
            raise VocabularyPackError("invalid_view", str(exc)) from exc
    else:
        raise VocabularyPackError(
            "invalid_view",
            f"Atlas view directory lacks {_PARQUET_VIEW_MANIFEST_FILE} or {_SEARCH_VIEW_MANIFEST_FILE}: {resolved_view}",
        )

    manifest_members_by_role: dict[str, dict[str, Any]] = {
        str(member["role"]): member for member in manifest["members"]
    }
    required_roles = ("Resource", "Label", "Statement")
    missing_required = [role for role in required_roles if role not in manifest_members_by_role]
    if missing_required:
        raise VocabularyPackError("invalid_view", f"view manifest misses required member roles: {missing_required}")

    # Validate member paths ONLY for roles actually required by this build configuration.
    active_roles: list[str] = list(required_roles)
    if include_mappings and "EvidenceBinding" in manifest_members_by_role:
        active_roles.append("EvidenceBinding")
    if include_derived and "derivedRelations" in manifest_members_by_role:
        active_roles.append("derivedRelations")

    member_paths: dict[str, Path] = {
        role: _safe_view_member_path(resolved_view, manifest_members_by_role[role].get("path"))
        for role in active_roles
    }

    res_pq = _sql_quote(str(member_paths["Resource"]))
    lbl_pq = _sql_quote(str(member_paths["Label"]))
    stm_pq = _sql_quote(str(member_paths["Statement"]))
    evd_pq = _sql_quote(str(member_paths["EvidenceBinding"])) if "EvidenceBinding" in member_paths else None
    drv_pq = _sql_quote(str(member_paths["derivedRelations"])) if "derivedRelations" in member_paths else None

    out_path = raw_out.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{out_path.name}.", suffix=".tmp", dir=str(out_path.parent))
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    schemes_sql = ", ".join(_sql_quote(s) for s in norm_schemes) if norm_schemes is not None else None
    langs_sql = ", ".join(_sql_quote(lang) for lang in norm_languages)

    con_duck: Any = None
    con_sql: sqlite3.Connection | None = None
    try:
        con_duck = duckdb.connect(":memory:")
        con_sql = sqlite3.connect(str(tmp_path))
        _ensure_fts5(con_sql)
        con_sql.execute("PRAGMA page_size = 8192")
        con_sql.execute("PRAGMA journal_mode = OFF")
        con_sql.execute("PRAGMA synchronous = OFF")
        con_sql.execute("PRAGMA temp_store = MEMORY")
        con_sql.execute("PRAGMA cache_size = -131072")
        _build_schema(con_sql)

        # Populate lossless URI prefix table (pfx_id=0 means raw full string).
        prefix_to_id: dict[str, int] = {"": 0}
        for idx, pfx in enumerate(_KNOWN_URI_PREFIXES, start=1):
            prefix_to_id[pfx] = idx
        con_sql.executemany(
            "INSERT INTO uri_prefixes (pfx_id, prefix) VALUES (?, ?)",
            [(pid, pfx) for pfx, pid in prefix_to_id.items()],
        )

        # 1. Stream ONLY scoped resources that have >= 1 label in selected languages (skip label_count == 0).
        scheme_map: dict[str, int] = {}
        release_map: dict[str, int] = {}
        rid_by_id_rel: dict[tuple[str, str], int] = {}
        rids_by_id: dict[str, list[int]] = defaultdict(list)
        has_entity_ring = False

        res_scheme_where = f"WHERE r.scheme IN ({schemes_sql})" if schemes_sql is not None else ""
        res_cur = con_duck.execute(
            f"""
            SELECT r.id, r.scheme, r.release, r.definition, r.source_record, r.notations, r.semantic_ring
            FROM read_parquet({res_pq}) r
            SEMI JOIN (
                SELECT resource, release
                FROM read_parquet({lbl_pq})
                WHERE lower(language) IN ({langs_sql})
            ) l ON l.resource = r.id AND l.release = r.release
            {res_scheme_where}
            ORDER BY r.scheme, r.release, r.id
            """
        )
        rid_counter = 0
        while True:
            batch = res_cur.fetchmany(_STREAM_BATCH_SIZE)
            if not batch:
                break
            res_insert: list[tuple[int, str, int, int, str | None, int, str, str | None, None, int, int]] = []
            for res_id, scheme_uri, rel_uri, defn, src_rec, notations, sem_ring in batch:
                rid_counter += 1
                if sem_ring == "entity":
                    has_entity_ring = True
                sid = scheme_map.setdefault(scheme_uri, len(scheme_map) + 1)
                if sid > 0xFFFF:
                    raise VocabularyPackError("too_many_schemes", "pack supports at most 65535 distinct schemes")
                rel_id = release_map.setdefault(rel_uri, len(release_map) + 1)
                rid_by_id_rel[(res_id, rel_uri)] = rid_counter
                rids_by_id[res_id].append(rid_counter)
                src_pfx, src_suf = _split_uri_prefix(src_rec, prefix_to_id)
                not_json = (
                    json.dumps([str(n) for n in notations if n], separators=(",", ":"))
                    if notations
                    else None
                )
                res_insert.append(
                    (rid_counter, res_id, sid, rel_id, defn, src_pfx, src_suf, not_json, None, 0, 0)
                )
            con_sql.executemany("INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", res_insert)
        n_resources = rid_counter
        effective_schemes = norm_schemes if norm_schemes is not None else tuple(sorted(scheme_map))
        con_sql.executemany("INSERT INTO schemes (sid, uri) VALUES (?, ?)", [(v, k) for k, v in scheme_map.items()])
        con_sql.executemany(
            "INSERT INTO releases (rel_id, uri) VALUES (?, ?)", [(v, k) for k, v in release_map.items()]
        )

        # 2. Stream selected-language labels via DuckDB semi-join in canonical role/label order.
        lbl_scheme_where = f"WHERE scheme IN ({schemes_sql})" if schemes_sql is not None else ""
        lbl_cur = con_duck.execute(
            f"""
            SELECT l.resource, l.release, l.id, l.value, l.label_role, l.language,
                   CASE l.label_role WHEN 'preferred' THEN 0 WHEN 'alternate' THEN 1 ELSE 2 END AS role_rank
            FROM read_parquet({lbl_pq}) l
            SEMI JOIN (
                SELECT id, release FROM read_parquet({res_pq}) {lbl_scheme_where}
            ) r ON l.resource = r.id AND l.release = r.release
            WHERE lower(l.language) IN ({langs_sql})
            ORDER BY l.resource, l.release, role_rank, lower(l.value), l.value, l.id
            """
        )

        pref_by_rid: dict[int, str] = {}
        has_pref_rids: set[int] = set()
        pref_texts_by_rid: dict[int, list[str]] = defaultdict(list)
        alt_texts_by_rid: dict[int, list[str]] = defaultdict(list)
        label_counts: Counter[int] = Counter()
        term_doc_freq: Counter[str] = Counter()
        n_labels = 0
        # Because lbl_cur is ordered by (resource, release), track per-resource token set in O(1) RAM!
        cur_rid_for_toks: int | None = None
        cur_tok_set: set[str] = set()

        while True:
            batch = lbl_cur.fetchmany(_STREAM_BATCH_SIZE)
            if not batch:
                break
            lbl_insert: list[tuple[int, int, str, str, int, str, str, str]] = []
            exact_insert: list[tuple[str, int, int]] = []
            for res_id, rel_uri, label_id, value, role, lang, role_rank in batch:
                rid = rid_by_id_rel.get((res_id, rel_uri))
                if rid is None:
                    continue
                val_norm = normalize_text(value)
                lbl_pfx, lbl_suf = _split_uri_prefix(label_id, prefix_to_id)
                lbl_insert.append((rid, role_rank, val_norm, value, lbl_pfx, lbl_suf, role, lang))
                exact_insert.append((val_norm, role_rank, rid))
                label_counts[rid] += 1
                n_labels += 1
                if rid not in pref_by_rid:
                    pref_by_rid[rid] = value
                if role_rank == 0:
                    has_pref_rids.add(rid)
                    pref_texts_by_rid[rid].append(value)
                else:
                    alt_texts_by_rid[rid].append(value)

                if rid != cur_rid_for_toks:
                    cur_rid_for_toks = rid
                    cur_tok_set = set()
                for tok in _tokenize(val_norm):
                    if len(tok) >= 3 and tok not in cur_tok_set:
                        cur_tok_set.add(tok)
                        term_doc_freq[tok] += 1

            con_sql.executemany("INSERT OR IGNORE INTO labels VALUES (?, ?, ?, ?, ?, ?, ?, ?)", lbl_insert)
            con_sql.executemany(
                "INSERT OR IGNORE INTO label_exact (value_lower, role_rank, rid) VALUES (?, ?, ?)",
                exact_insert,
            )

        con_sql.executemany(
            "UPDATE resources SET pref_label = ?, label_count = ?, has_preferred = ? WHERE rid = ?",
            [
                (pref_by_rid[rid], label_counts[rid], 1 if rid in has_pref_rids else 0, rid)
                for rid in pref_by_rid
            ],
        )
        n_labeled = len(pref_by_rid)
        del label_counts, cur_tok_set, has_pref_rids

        # 3. Populate distinct dictionary terms + trigram spelling table.
        sorted_terms = sorted(term_doc_freq.items())
        con_sql.executemany(
            "INSERT INTO vocab_terms (tid, term, doc_freq) VALUES (?, ?, ?)",
            [(tid, term, df) for tid, (term, df) in enumerate(sorted_terms, start=1)],
        )
        con_sql.execute("INSERT INTO vocab_terms_trigram(vocab_terms_trigram) VALUES('rebuild')")
        n_vocab_terms = len(sorted_terms)
        del term_doc_freq, sorted_terms

        # 4. Stream contentless concepts_bm25 FTS5 index in batches.
        #    Alternate-only concepts (has_preferred == 0) write ONLY into alt_text, never duplicated into pref_text!
        res_bm25_cur = con_sql.execute(
            "SELECT rid, definition FROM resources WHERE pref_label IS NOT NULL"
        )
        while True:
            rows = res_bm25_cur.fetchmany(_STREAM_BATCH_SIZE)
            if not rows:
                break
            bm25_batch: list[tuple[int, str, str, str]] = []
            for rid, defn in rows:
                prefs = pref_texts_by_rid.pop(rid, None)
                pref_str = " ; ".join(prefs) if prefs else ""
                alts = alt_texts_by_rid.pop(rid, None)
                alt_str = " ; ".join(alts) if alts else ""
                bm25_batch.append((rid, pref_str, alt_str, defn or ""))
            con_sql.executemany(
                "INSERT INTO concepts_bm25(rowid, pref_text, alt_text, def_text) VALUES (?, ?, ?, ?)",
                bm25_batch,
            )
        del pref_texts_by_rid, alt_texts_by_rid

        # 5. Stream edges: NativeRelationAssertion + optional REF-035 MappingAssertion + optional DerivedRelation.
        #    Drop reflexive self-loops (s_rid == d_rid) across ALL edge families.
        #    Pre-populate pred_map in fixed deterministic sorted (stmt_type, pred_uri) order so pid order
        #    ALWAYS matches pred_uri order (keeping related_sync(limit=1) == related_sync(limit=10)[0]).
        canonical_predicates: list[tuple[str, str]] = sorted(
            {
                *((pred_uri, "NativeRelationAssertion") for pred_uri in NATIVE_RELATION_PREDICATES),
                *((pred_uri, "MappingAssertion") for pred_uri in MAPPING_RELATION_PREDICATES),
                *((pred_uri, "DerivedRelation") for pred_uri in DERIVED_RELATION_PREDICATES),
            },
            key=lambda item: (item[1], item[0]),
        )
        pred_map: dict[tuple[str, str], int] = {
            key: pid for pid, key in enumerate(canonical_predicates, start=1)
        }
        rule_map: dict[str, int] = {"": 0}
        con_sql.execute("INSERT INTO derivation_rules (rule_id, uri) VALUES (0, '')")

        def get_pid(pred_uri: str, stmt_type: str) -> int:
            key = (pred_uri, stmt_type)
            pid = pred_map.get(key)
            if pid is None:
                pid = len(pred_map) + 1
                pred_map[key] = pid
            return pid

        def get_rule_id(rule_uri: str) -> int:
            rid_rule = rule_map.get(rule_uri)
            if rid_rule is None:
                rid_rule = len(rule_map)
                rule_map[rule_uri] = rid_rule
            return rid_rule

        native_preds_sql = ", ".join(_sql_quote(p) for p in NATIVE_RELATION_PREDICATES)
        nat_cur = con_duck.execute(
            f"""
            SELECT s.subject, s.source_release, s.object, s.target_release, s.id, s.predicate
            FROM read_parquet({stm_pq}) s
            WHERE s.statement_type = 'NativeRelationAssertion'
              AND s.predicate IN ({native_preds_sql})
            """
        )
        while True:
            batch = nat_cur.fetchmany(_STREAM_BATCH_SIZE)
            if not batch:
                break
            edge_batch: list[tuple[int, int, int, int, str, int, int, int]] = []
            for subj, srel, obj, trel, stmt_id, pred in batch:
                s_rid = rid_by_id_rel.get((subj, srel))
                d_rid = rid_by_id_rel.get((obj, trel))
                if (
                    s_rid is None
                    or d_rid is None
                    or s_rid == d_rid
                    or s_rid not in pref_by_rid
                    or d_rid not in pref_by_rid
                ):
                    continue
                pid = get_pid(pred, "NativeRelationAssertion")
                spfx, ssuf = _split_uri_prefix(stmt_id, prefix_to_id)
                edge_batch.append((s_rid, _STMT_KIND_NATIVE, pid, spfx, ssuf, d_rid, 1, 0))
            if edge_batch:
                con_sql.executemany("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)", edge_batch)

        if include_mappings:
            map_preds_sql = ", ".join(_sql_quote(p) for p in MAPPING_RELATION_PREDICATES)
            roles_sql = ", ".join(_sql_quote(r) for r in _REF035_DEFAULT_EVIDENCE_ROLES)
            approved_sql = _sql_quote(_REF035_APPROVED_DECISION)
            if evd_pq is not None:
                map_sql = f"""
                    WITH ev AS (
                        SELECT statement,
                               max(CASE WHEN evidence_role IN ({roles_sql}) AND decision = {approved_sql}
                                        THEN 1 ELSE 0 END) AS is_default
                        FROM read_parquet({evd_pq})
                        GROUP BY statement
                    )
                    SELECT s.subject, s.source_release, s.object, s.target_release,
                           s.id, s.predicate, coalesce(ev.is_default, 0) AS ref035_default
                    FROM read_parquet({stm_pq}) s
                    LEFT JOIN ev ON ev.statement = s.id
                    WHERE s.statement_type = 'MappingAssertion'
                      AND s.predicate IN ({map_preds_sql})
                """
            else:
                map_sql = f"""
                    SELECT s.subject, s.source_release, s.object, s.target_release,
                           s.id, s.predicate, 0 AS ref035_default
                    FROM read_parquet({stm_pq}) s
                    WHERE s.statement_type = 'MappingAssertion'
                      AND s.predicate IN ({map_preds_sql})
                """
            map_cur = con_duck.execute(map_sql)
            while True:
                batch = map_cur.fetchmany(_STREAM_BATCH_SIZE)
                if not batch:
                    break
                edge_batch = []
                rev_batch: list[tuple[int, int, int, str, int, int]] = []
                for subj, srel, obj, trel, stmt_id, pred, is_default in batch:
                    s_rid = rid_by_id_rel.get((subj, srel))
                    d_rid = rid_by_id_rel.get((obj, trel))
                    if (
                        s_rid is None
                        or d_rid is None
                        or s_rid == d_rid
                        or s_rid not in pref_by_rid
                        or d_rid not in pref_by_rid
                    ):
                        continue
                    pid = get_pid(pred, "MappingAssertion")
                    spfx, ssuf = _split_uri_prefix(stmt_id, prefix_to_id)
                    default_flag = int(bool(is_default))
                    edge_batch.append((s_rid, _STMT_KIND_MAPPING, pid, spfx, ssuf, d_rid, default_flag, 0))
                    if pred in SYMMETRIC_MAPPING_PREDICATES:
                        rev_batch.append((d_rid, pid, spfx, ssuf, s_rid, default_flag))
                if edge_batch:
                    con_sql.executemany("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)", edge_batch)
                if rev_batch:
                    con_sql.executemany("INSERT OR IGNORE INTO edges_rev VALUES (?, ?, ?, ?, ?, ?)", rev_batch)

        if include_derived and drv_pq is not None:
            drv_preds_sql = ", ".join(_sql_quote(p) for p in DERIVED_RELATION_PREDICATES)
            drv_cur = con_duck.execute(
                f"""
                SELECT id, subject, predicate, object, derivation_rule
                FROM read_parquet({drv_pq})
                WHERE predicate IN ({drv_preds_sql})
                ORDER BY derivation_rule NULLS FIRST, id
                """
            )
            while True:
                batch = drv_cur.fetchmany(_STREAM_BATCH_SIZE)
                if not batch:
                    break
                edge_batch = []
                for drv_id, subj, pred, obj, rule_uri in batch:
                    s_rids = rids_by_id.get(subj)
                    d_rids = rids_by_id.get(obj)
                    if not s_rids or not d_rids:
                        continue
                    pid = get_pid(pred, "DerivedRelation")
                    r_id = get_rule_id(rule_uri or "")
                    spfx, ssuf = _split_uri_prefix(drv_id, prefix_to_id)
                    for s_rid in s_rids:
                        if s_rid not in pref_by_rid:
                            continue
                        for d_rid in d_rids:
                            if d_rid not in pref_by_rid or s_rid == d_rid:
                                continue
                            edge_batch.append((s_rid, _STMT_KIND_DERIVED, pid, spfx, ssuf, d_rid, 0, r_id))
                if edge_batch:
                    con_sql.executemany("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)", edge_batch)

        con_sql.executemany(
            "INSERT INTO predicates (pid, uri, stmt_type, symmetric) VALUES (?, ?, ?, ?)",
            [
                (
                    pid,
                    pred_uri,
                    stmt_type,
                    1 if (stmt_type == "MappingAssertion" and pred_uri in SYMMETRIC_MAPPING_PREDICATES) else 0,
                )
                for (pred_uri, stmt_type), pid in pred_map.items()
            ],
        )
        con_sql.executemany(
            "INSERT OR IGNORE INTO derivation_rules (rule_id, uri) VALUES (?, ?)",
            [(rid_rule, uri) for uri, rid_rule in sorted(rule_map.items(), key=lambda pair: pair[1]) if rid_rule > 0],
        )
        del rid_by_id_rel, rids_by_id, pref_by_rid

        # 5b. Strictly iterative Tarjan's SCC over BOTH skos:broader AND skos:narrower edges
        #     (quarantine intra-SCC cycle edges by default when quarantine_broader_cycles=True).
        broader_pids = sorted(pid for (pred_uri, _st), pid in pred_map.items() if pred_uri == _BROADER_URI)
        narrower_pids = sorted(pid for (pred_uri, _st), pid in pred_map.items() if pred_uri == _NARROWER_URI)
        broader_cycle_count, quarantined_broader_cycle_edges = _detect_and_quarantine_hierarchy_cycles(
            con_sql,
            broader_pids,
            quarantine=quarantine_broader_cycles,
        )
        narrower_cycle_count, quarantined_narrower_cycle_edges = _detect_and_quarantine_hierarchy_cycles(
            con_sql,
            narrower_pids,
            quarantine=quarantine_broader_cycles,
        )
        quarantined_cycle_edges = quarantined_broader_cycle_edges + quarantined_narrower_cycle_edges

        edge_counts_by_kind = dict(
            con_sql.execute("SELECT stmt_kind, count(*) FROM edges GROUP BY stmt_kind").fetchall()
        )
        n_native_edges = int(edge_counts_by_kind.get(_STMT_KIND_NATIVE, 0))
        n_mapping_edges = int(edge_counts_by_kind.get(_STMT_KIND_MAPPING, 0))
        n_derived_edges = int(edge_counts_by_kind.get(_STMT_KIND_DERIVED, 0))

        # 5c. Populate pack_meta_blobs: neutral structural_prior_f32 + sid_by_rid_u16 (ZERO hardcoded scheme bias!).
        max_rid_row = con_sql.execute("SELECT max(rid) FROM resources").fetchone()
        max_rid = int(max_rid_row[0]) if max_rid_row and max_rid_row[0] is not None else 0
        structural_priors = array("f", [0.0]) * (max_rid + 1)
        sid_by_rid = array("H", [0]) * (max_rid + 1)
        if max_rid > 0:
            for rid, sid, pref in con_sql.execute("SELECT rid, sid, pref_label FROM resources"):
                r_int = int(rid)
                if 0 <= r_int <= max_rid:
                    sid_by_rid[r_int] = int(sid)
                    if pref:
                        p = 0.0
                        depth = pref.count("--")
                        if depth > 0:
                            p -= DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY * depth
                        if len(pref) > DEFAULT_STRUCTURAL_LONG_LABEL_CHARS:
                            p -= DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY
                        structural_priors[r_int] = p

        con_sql.executemany(
            "INSERT INTO pack_meta_blobs (key, payload) VALUES (?, ?)",
            [
                ("structural_prior_f32", sqlite3.Binary(_to_little_endian_bytes(structural_priors))),
                ("sid_by_rid_u16", sqlite3.Binary(_to_little_endian_bytes(sid_by_rid))),
            ],
        )
        del structural_priors, sid_by_rid

        # 5d. Ingest optional lifecycle-events.parquet and agency-projection.parquet tables only when scoped in.
        #     - include_agency_tables=True (or None with schemes=None or entity-ring resources): ingest full
        #       lifecycle-events and agency-projection tables (including predecessor agency events).
        #     - include_agency_tables=None on strictly non-entity subject-only subsets: skip agency-projection
        #       completely (zero leaked federal agency projections) and retain only lifecycle events whose
        #       applies_to targets a selected resource in this pack.
        #     - include_agency_tables=False: skip both tables entirely.
        should_include_agency = (
            include_agency_tables
            if include_agency_tables is not None
            else (schemes is None or has_entity_ring)
        )
        lifecycle_pq: str | None = None
        agency_proj_pq: str | None = None
        lifecycle_filter_ids: set[str] | None = None
        if should_include_agency:
            if "LifecycleEvent" in manifest_members_by_role:
                lifecycle_pq = _sql_quote(
                    str(_safe_view_member_path(resolved_view, manifest_members_by_role["LifecycleEvent"].get("path")))
                )
            if "agencyProjection" in manifest_members_by_role:
                agency_proj_pq = _sql_quote(
                    str(_safe_view_member_path(resolved_view, manifest_members_by_role["agencyProjection"].get("path")))
                )
        elif include_agency_tables is None and "LifecycleEvent" in manifest_members_by_role:
            lifecycle_pq = _sql_quote(
                str(_safe_view_member_path(resolved_view, manifest_members_by_role["LifecycleEvent"].get("path")))
            )
            lifecycle_filter_ids = {str(row[0]) for row in con_sql.execute("SELECT id FROM resources")}

        n_change_events = 0
        if lifecycle_pq is not None:
            ev_cur = con_duck.execute(
                f"""
                SELECT id, applies_to, lifecycle_event_kind, effective_date,
                       source_records, from_release, to_release
                FROM read_parquet({lifecycle_pq})
                ORDER BY effective_date, id
                """
            )
            while True:
                batch = ev_cur.fetchmany(_STREAM_BATCH_SIZE)
                if not batch:
                    break
                ev_insert: list[tuple[str, str, str, str, str, str | None, str | None]] = []
                for ev_id, applies_to, ev_kind, eff_date, src_recs, from_rel, to_rel in batch:
                    applies_to_s = str(applies_to)
                    if lifecycle_filter_ids is not None and applies_to_s not in lifecycle_filter_ids:
                        continue
                    src_json = json.dumps(
                        [str(item) for item in (src_recs or ())],
                        separators=(",", ":"),
                    )
                    ev_insert.append(
                        (
                            str(ev_id),
                            applies_to_s,
                            str(ev_kind),
                            str(eff_date),
                            src_json,
                            None if from_rel is None else str(from_rel),
                            None if to_rel is None else str(to_rel),
                        )
                    )
                if ev_insert:
                    con_sql.executemany(
                        "INSERT OR IGNORE INTO agency_change_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ev_insert,
                    )
            n_change_events = int(con_sql.execute("SELECT count(*) FROM agency_change_events").fetchone()[0])

        n_agency_projections = 0
        if agency_proj_pq is not None:
            ap_cur = con_duck.execute(
                f"""
                SELECT source_value_kind, source_value, org, pref_label,
                       abbreviations, aliases, parent_org, relation,
                       evidence_tier, warrant, basis, len(evidence_records)
                FROM read_parquet({agency_proj_pq})
                ORDER BY source_value_kind, source_value, org
                """
            )
            while True:
                batch = ap_cur.fetchmany(_STREAM_BATCH_SIZE)
                if not batch:
                    break
                ap_insert: list[tuple[str, str, str, str, str, str, str | None, str, str, str, str, int]] = []
                for (
                    sv_kind,
                    sv_val,
                    org_iri,
                    pref_lbl,
                    abbrs,
                    aliases,
                    parent_org,
                    relation,
                    ev_tier,
                    warrant,
                    basis,
                    ev_count,
                ) in batch:
                    abbrs_json = json.dumps([str(item) for item in (abbrs or ())], separators=(",", ":"))
                    aliases_json = json.dumps([str(item) for item in (aliases or ())], separators=(",", ":"))
                    ap_insert.append(
                        (
                            str(sv_kind),
                            str(sv_val),
                            str(org_iri),
                            str(pref_lbl),
                            abbrs_json,
                            aliases_json,
                            None if parent_org is None else str(parent_org),
                            str(relation),
                            str(ev_tier),
                            str(warrant),
                            str(basis),
                            int(ev_count or 0),
                        )
                    )
                con_sql.executemany(
                    "INSERT OR IGNORE INTO agency_projections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ap_insert,
                )
            n_agency_projections = int(con_sql.execute("SELECT count(*) FROM agency_projections").fetchone()[0])

        # 6. Optimize FTS5 segments and write deterministic pack_meta including pack_id.
        con_sql.execute("INSERT INTO concepts_bm25(concepts_bm25) VALUES('optimize')")
        con_sql.execute("INSERT INTO vocab_terms_trigram(vocab_terms_trigram) VALUES('optimize')")
        con_sql.execute("ANALYZE")

        built_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        pack_id_parts: dict[str, Any] = {
            "source_manifest_digest": expected_digest,
            "schemes": list(effective_schemes),
            "languages": list(norm_languages),
            "schema_version": PACK_SCHEMA_VERSION,
            "policy_version": PACK_POLICY_VERSION,
            "include_mappings": include_mappings,
            "include_derived": include_derived,
            "quarantine_broader_cycles": quarantine_broader_cycles,
            "resources": n_resources,
            "labeled": n_labeled,
            "labels": n_labels,
            "native_edges": n_native_edges,
            "mapping_edges": n_mapping_edges,
            "derived_edges": n_derived_edges,
            "broader_cycles": broader_cycle_count,
            "quarantined_cycle_edges": quarantined_cycle_edges,
        }
        if narrower_cycle_count:
            pack_id_parts["narrower_cycles"] = narrower_cycle_count
        if quarantined_narrower_cycle_edges:
            pack_id_parts["quarantined_narrower_cycle_edges"] = quarantined_narrower_cycle_edges
        if n_change_events:
            pack_id_parts["agency_change_events"] = n_change_events
        if n_agency_projections:
            pack_id_parts["agency_projections"] = n_agency_projections
        pack_id = _compute_pack_id(pack_id_parts)
        meta_entries = {
            "record_type": PACK_RECORD_TYPE,
            "schema_version": PACK_SCHEMA_VERSION,
            "policy_version": PACK_POLICY_VERSION,
            "pack_id": pack_id,
            "source_view_id": str(manifest["viewId"]),
            "source_view_kind": source_view_kind,
            "source_manifest_digest": expected_digest,
            "schemes_json": json.dumps(list(effective_schemes), separators=(",", ":")),
            "languages_json": json.dumps(list(norm_languages), separators=(",", ":")),
            "include_mappings": "1" if include_mappings else "0",
            "include_derived": "1" if include_derived else "0",
            "resource_count": str(n_resources),
            "labeled_resource_count": str(n_labeled),
            "label_count": str(n_labels),
            "native_edge_count": str(n_native_edges),
            "mapping_edge_count": str(n_mapping_edges),
            "derived_edge_count": str(n_derived_edges),
            "vocab_term_count": str(n_vocab_terms),
            "broader_cycle_count": str(broader_cycle_count),
            "narrower_cycle_count": str(narrower_cycle_count),
            "quarantined_cycle_edges": str(quarantined_cycle_edges),
            "quarantined_narrower_cycle_edges": str(quarantined_narrower_cycle_edges),
            "agency_change_event_count": str(n_change_events),
            "agency_projection_count": str(n_agency_projections),
            "built_at": built_at,
        }
        con_sql.executemany("INSERT INTO pack_meta (key, value) VALUES (?, ?)", list(meta_entries.items()))
        con_sql.commit()
        con_sql.execute("VACUUM")
        con_sql.close()
        con_sql = None
        con_duck.close()
        con_duck = None

        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, out_path)
        pack_digest = _sha256_file(out_path)
        size_bytes = out_path.stat().st_size
        return VocabularyPackManifest(
            pack_path=out_path,
            pack_id=pack_id,
            pack_sha256=pack_digest,
            size_bytes=size_bytes,
            source_view_id=str(manifest["viewId"]),
            source_manifest_digest=expected_digest,
            schemes=effective_schemes,
            languages=norm_languages,
            schema_version=PACK_SCHEMA_VERSION,
            policy_version=PACK_POLICY_VERSION,
            include_mappings=include_mappings,
            include_derived=include_derived,
            resource_count=n_resources,
            labeled_resource_count=n_labeled,
            label_count=n_labels,
            native_edge_count=n_native_edges,
            mapping_edge_count=n_mapping_edges,
            derived_edge_count=n_derived_edges,
            vocab_term_count=n_vocab_terms,
            built_at=built_at,
            broader_cycle_count=broader_cycle_count,
            quarantined_cycle_edges=quarantined_cycle_edges,
            narrower_cycle_count=narrower_cycle_count,
            quarantined_narrower_cycle_edges=quarantined_narrower_cycle_edges,
            agency_change_event_count=n_change_events,
            agency_projection_count=n_agency_projections,
            source_view_kind=source_view_kind,
        )
    except BaseException:
        if con_sql is not None:
            con_sql.close()
        if con_duck is not None:
            con_duck.close()
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


__all__ = [
    "DEFAULT_STRUCTURAL_LONG_LABEL_CHARS",
    "DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY",
    "DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY",
    "DERIVED_RELATION_PREDICATES",
    "MAPPING_RELATION_PREDICATES",
    "NATIVE_RELATION_PREDICATES",
    "PACK_POLICY_VERSION",
    "PACK_RECORD_TYPE",
    "PACK_SCHEMA_VERSION",
    "SUPPORTED_PACK_SCHEMA_VERSIONS",
    "SYMMETRIC_MAPPING_PREDICATES",
    "VocabularyPackManifest",
    "build_vocabulary_pack",
]

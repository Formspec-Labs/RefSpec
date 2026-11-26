"""Engine-agnostic, sealed read-only SQLite Vocabulary Pack runtime for Atlas 3.1.

Serves a compiled immutable, memory-mapped SQLite Vocabulary Pack through a clean
Dependency Injection (DI) seam (``refspec.atlas.vocabulary_protocols``):

* Serving hot path imports ONLY the Python standard library (``sqlite3``) —
  zero ``numpy``, ``duckdb``, ``pyarrow``, or ``rdflib`` imports.
* Thread-safe via a bounded checkout/return read-only connection pool
  (``max_idle = 16``, zero FD/mmap leak across ephemeral request threads,
  race-free ``close()``).
* Optional Tier-1 semantic retrieval (``SemanticIndex``), query encoding
  (``QueryEncoder``), candidate fusion (``RankFusionPolicy``), post-hydration
  reranking (``CandidateReranker`` such as ``AuthorityReranker``), lookup tuning
  (``LookupPolicy``), and graph traversal defaults (``RelationPolicy``) are all
  injected via ``open(...)`` or ``with_dependencies(...)``.
* ``build_vocabulary_pack`` is implemented in ``refspec.atlas.vocabulary_pack_build``
  and re-exported here for full backward compatibility.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import math
import re
import sqlite3
import sys
import threading
from array import array
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from refspec.atlas.vocabulary_pack_build import (
    _BROADER_URI,
    _STMT_KIND_DERIVED,
    _STMT_KIND_MAPPING,
    _STMT_KIND_NATIVE,
    _TOKEN_RE,
    DEFAULT_STRUCTURAL_LONG_LABEL_CHARS,
    DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY,
    DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY,
    DERIVED_RELATION_PREDICATES,
    MAPPING_RELATION_PREDICATES,
    NATIVE_RELATION_PREDICATES,
    PACK_POLICY_VERSION,
    PACK_RECORD_TYPE,
    PACK_SCHEMA_VERSION,
    SUPPORTED_PACK_SCHEMA_VERSIONS,
    SYMMETRIC_MAPPING_PREDICATES,
    VocabularyPackManifest,
    _ensure_fts5,
    _normalize_digest,
    _normalize_schemes,
    _reject_symlink_path,
    _sha256_file,
    _to_little_endian_bytes,
    _tokenize,
    build_vocabulary_pack,
)
from refspec.atlas.vocabulary_protocols import (
    DEFAULT_CURATED_SCHEME_WEIGHTS,
    DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ,
    DEFAULT_MIN_COSINE,
    REGULATORY_BENCHMARK_SCHEME_PRESET,
    CandidateReranker,
    ExactPinnedRRF,
    LookupPolicy,
    QueryEncoder,
    RankFusionPolicy,
    RelationPolicy,
    SemanticIndex,
    VocabularyInputError,
    VocabularyPackError,
    group_by_identical_label,
    normalize_text,
)

_QUERY_LIMIT = 200
_EXTRACT_TEXT_LIMIT = 100_000
_REF_VALUE_LIMIT = 1000
_MAX_LOOKUP_LIMIT = 50
_MAX_RELATED_LIMIT = 50
_MAX_MASK_CACHE_ENTRIES = 64
_HYDRATE_CHUNK_SIZE = 400

_REFERENCE_KEYS = frozenset({"id", "scheme", "release"})
_SPAN_BREAK_RE = re.compile(r"[,;.:()\[\]\r\n]")

# Common English function words excluded from Tier-2 soft-OR queries and unigram prose extraction.
_COMMON_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "about",
        "above",
        "across",
        "after",
        "against",
        "all",
        "along",
        "also",
        "among",
        "and",
        "any",
        "are",
        "around",
        "because",
        "been",
        "before",
        "behind",
        "below",
        "between",
        "beyond",
        "both",
        "but",
        "can",
        "could",
        "did",
        "does",
        "during",
        "each",
        "either",
        "etc",
        "few",
        "for",
        "from",
        "had",
        "has",
        "have",
        "having",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "into",
        "its",
        "just",
        "may",
        "might",
        "more",
        "most",
        "must",
        "neither",
        "nor",
        "not",
        "now",
        "off",
        "only",
        "onto",
        "other",
        "our",
        "ours",
        "out",
        "over",
        "per",
        "same",
        "shall",
        "she",
        "should",
        "since",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "too",
        "under",
        "until",
        "upon",
        "very",
        "via",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "within",
        "without",
        "would",
        "yet",
        "you",
        "your",
        "yours",
    }
)


def _normalize_reference(reference: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(reference, Mapping) or set(reference) != _REFERENCE_KEYS:
        raise VocabularyInputError("invalid_reference", "concept reference must carry id, scheme, and release")
    out: dict[str, str] = {}
    for key in ("id", "scheme", "release"):
        val = reference.get(key)
        if not isinstance(val, str) or not 0 < len(val) <= _REF_VALUE_LIMIT or val != val.strip():
            raise VocabularyInputError("invalid_reference", f"invalid concept reference field {key!r}")
        out[key] = val
    return out


def _normalize_limit(limit: int, *, maximum: int, name: str) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise VocabularyInputError("invalid_limit", f"{name} must be an integer between 1 and {maximum}")
    return limit


def _from_little_endian_array(typecode: str, payload: bytes) -> array:
    arr = array(typecode)
    arr.frombytes(payload)
    if sys.byteorder != "little":
        arr.byteswap()
    return arr


def _damerau_levenshtein(a: str, b: str, max_dist: int) -> int:
    """Optimal string alignment (Damerau-Levenshtein) distance with early exit > max_dist."""

    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    if a == b:
        return 0
    prev2: list[int] | None = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        row_min = i
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cb = b[j - 1]
            cost = 0 if ca == cb else 1
            best = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and prev2 is not None and ca == b[j - 2] and a[i - 2] == cb:
                trans = prev2[j - 2] + 1
                if trans < best:
                    best = trans
            curr[j] = best
            if best < row_min:
                row_min = best
        if row_min > max_dist:
            return max_dist + 1
        prev2 = prev
        prev = curr
    return prev[lb]


def _trigram_dice(a: str, b: str) -> float:
    """Symmetric padded character-trigram Dice similarity in ``[0.0, 1.0]``."""

    pa = f"  {a}  "
    pb = f"  {b}  "
    sa = {pa[i : i + 3] for i in range(len(pa) - 2)}
    sb = {pb[i : i + 3] for i in range(len(pb) - 2)}
    denom = len(sa) + len(sb)
    if denom == 0:
        return 0.0
    return (2.0 * len(sa & sb)) / denom


@dataclass(frozen=True, slots=True)
class _SearchRidsCapabilities:
    supports_min_cosine: bool
    supports_nprobe: bool
    supports_allowed_rids: bool
    supports_rerank_top_r: bool


def _inspect_search_rids_capabilities(index: SemanticIndex | None) -> _SearchRidsCapabilities:
    if index is None:
        return _SearchRidsCapabilities(False, False, False, False)
    try:
        params = inspect.signature(index.search_rids).parameters
    except (TypeError, ValueError):
        return _SearchRidsCapabilities(False, False, False, False)
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    return _SearchRidsCapabilities(
        supports_min_cosine=has_var_kw or "min_cosine" in params,
        supports_nprobe=has_var_kw or "nprobe" in params,
        supports_allowed_rids=has_var_kw or "allowed_rids" in params,
        supports_rerank_top_r=has_var_kw or "rerank_top_r" in params,
    )


def _prepare_allowed_checker(allowed_rids: Any) -> Any:
    """Prepare an O(1) predicate ``(rid: int) -> bool`` for fallback post-filtering."""

    if allowed_rids is None:
        return None
    if isinstance(allowed_rids, (bytes, bytearray, memoryview)):
        mv = memoryview(allowed_rids)
        n = len(mv)
        return lambda rid: 0 <= rid < n and mv[rid] != 0
    if isinstance(allowed_rids, (set, frozenset)):
        return allowed_rids.__contains__
    # Handle generic Sequence[int] / iterable of ints (or 1D bool/uint8 buffer if passed by caller).
    allowed_set = {int(r) for r in allowed_rids}
    return allowed_set.__contains__


def _read_meta_blob(con: sqlite3.Connection, key: str) -> bytes | None:
    try:
        row = con.execute("SELECT payload FROM pack_meta_blobs WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or row[0] is None:
        return None
    return bytes(row[0])


def _is_short_acronym_label(text: str) -> bool:
    stripped = text.strip()
    return 0 < len(stripped) <= 4 and stripped.isupper()


class _ReadOnlyConnectionPool:
    """Bounded checkout/return pool of read-only immutable SQLite connections for one pack file.

    Callers check out a connection via ``with pool.borrow() as con:`` so concurrent
    threads never share a connection simultaneously while ephemeral threads (e.g.
    ``ThreadingHTTPServer`` workers) return connections back to the bounded idle
    deque instead of leaking one file descriptor and mmap per exited thread.
    ``close()`` closes all idle connections immediately and lets any active
    in-use connections finish cleanly and close upon returning from ``borrow()``.
    """

    def __init__(
        self,
        uri: str,
        *,
        mmap_bytes: int,
        cache_kib: int,
        initial_con: sqlite3.Connection,
        max_idle: int = 16,
    ) -> None:
        self._uri = uri
        self._mmap_bytes = mmap_bytes
        self._cache_kib = cache_kib
        self._max_idle = max(1, int(max_idle))
        self._lock = threading.Lock()
        self._idle: deque[sqlite3.Connection] = deque([initial_con])
        self._in_use: set[sqlite3.Connection] = set()
        self._closed = False

    def check_open(self) -> None:
        with self._lock:
            if self._closed:
                raise VocabularyPackError("pack_closed", "vocabulary pack has been closed")

    @contextlib.contextmanager
    def borrow(self) -> Iterator[sqlite3.Connection]:
        con: sqlite3.Connection | None = None
        with self._lock:
            if self._closed:
                raise VocabularyPackError("pack_closed", "vocabulary pack has been closed")
            if self._idle:
                con = self._idle.pop()
                self._in_use.add(con)
        if con is None:
            new_con: sqlite3.Connection | None = None
            try:
                new_con = sqlite3.connect(self._uri, uri=True, check_same_thread=False)
                if self._mmap_bytes > 0:
                    new_con.execute(f"PRAGMA mmap_size = {int(self._mmap_bytes)}")
                if self._cache_kib > 0:
                    new_con.execute(f"PRAGMA cache_size = -{int(self._cache_kib)}")
            except sqlite3.Error as exc:
                if new_con is not None:
                    with contextlib.suppress(sqlite3.Error):
                        new_con.close()
                raise VocabularyPackError("corrupt_pack", f"failed to open pack connection: {exc}") from exc
            with self._lock:
                if self._closed:
                    with contextlib.suppress(sqlite3.Error):
                        new_con.close()
                    raise VocabularyPackError("pack_closed", "vocabulary pack has been closed")
                con = new_con
                self._in_use.add(con)
        try:
            yield con
        finally:
            should_close = False
            with self._lock:
                self._in_use.discard(con)
                if self._closed or len(self._idle) >= self._max_idle:
                    should_close = True
                else:
                    self._idle.append(con)
            if should_close:
                with contextlib.suppress(sqlite3.Error):
                    con.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            idle_conns = list(self._idle)
            self._idle.clear()
        for con in idle_conns:
            with contextlib.suppress(sqlite3.Error):
                con.close()


def _validate_semantic_wiring(
    *,
    pack_path: Path,
    pack_id: str,
    pack_sha256: str | None,
    source_manifest_digest: str,
    semantic_index: SemanticIndex | None,
    query_encoder: QueryEncoder | None,
    verify_pack_digest: bool,
) -> str | None:
    """Validate identity, digest, and embedding-space alignment for injected semantic dependencies."""

    computed_sha = pack_sha256
    if semantic_index is not None:
        if semantic_index.source_manifest_digest != source_manifest_digest:
            raise VocabularyPackError(
                "sidecar_mismatch",
                "semantic index source manifest digest does not match vocabulary pack",
            )
        sidecar_pack_id = getattr(semantic_index, "pack_id", None)
        if sidecar_pack_id and pack_id and sidecar_pack_id != pack_id:
            raise VocabularyPackError(
                "sidecar_mismatch",
                "semantic index pack identity does not match vocabulary pack",
            )
        if verify_pack_digest or not sidecar_pack_id or not pack_id:
            if computed_sha is None:
                computed_sha = _sha256_file(pack_path)
            if semantic_index.pack_sha256 != computed_sha:
                raise VocabularyPackError(
                    "sidecar_mismatch",
                    "semantic index pack digest does not match vocabulary pack",
                )
        if query_encoder is not None:
            if query_encoder.dimensions != semantic_index.dimensions:
                raise VocabularyPackError(
                    "encoder_mismatch",
                    f"query encoder dimensions ({query_encoder.dimensions}) do not match "
                    f"semantic index dimensions ({semantic_index.dimensions})",
                )
            if query_encoder.model_id != semantic_index.model_id:
                raise VocabularyPackError(
                    "encoder_mismatch",
                    f"query encoder model ({query_encoder.model_id!r}) does not match "
                    f"semantic index model ({semantic_index.model_id!r})",
                )
    return computed_sha


class AtlasVocabularyPack:
    """Read-only, memory-mapped, thread-safe Atlas Vocabulary Pack with Dependency Injection.

    Implements ``VocabularyProvider`` and ``GraphExpander`` (both sync and async,
    ``requires_sql_executor = False``). Optional ``SemanticIndex``, ``QueryEncoder``,
    ``RankFusionPolicy``, ``CandidateReranker``, ``LookupPolicy``, and
    ``RelationPolicy`` are injected via ``open(...)`` or ``with_dependencies(...)``.
    """

    requires_sql_executor: bool = False

    def __init__(
        self,
        *,
        pack_path: Path,
        pool: _ReadOnlyConnectionPool,
        meta: dict[str, str],
        pack_sha256: str | None,
        semantic_index: SemanticIndex | None = None,
        query_encoder: QueryEncoder | None = None,
        rank_fusion: RankFusionPolicy | None = None,
        candidate_reranker: CandidateReranker | None = None,
        lookup_policy: LookupPolicy | None = None,
        relation_policy: RelationPolicy | None = None,
        owns_connection: bool = True,
        lookups_cache: tuple[
            dict[int, str],
            dict[str, int],
            dict[int, str],
            dict[str, int],
            dict[int, tuple[str, str, bool]],
            dict[int, str],
            dict[int, str],
            tuple[int, ...],
            array | None,
            bytes | None,
            int,
            bool,
            bool,
        ]
        | None = None,
    ) -> None:
        self._path = pack_path
        self._pool = pool
        self._meta = meta
        self._pack_sha256 = pack_sha256
        self._semantic_index = semantic_index
        self._sem_caps = _inspect_search_rids_capabilities(semantic_index)
        self._query_encoder = query_encoder
        self._rank_fusion: RankFusionPolicy = rank_fusion if rank_fusion is not None else ExactPinnedRRF()
        self._candidate_reranker: CandidateReranker | None = candidate_reranker
        self._lookup_policy: LookupPolicy = lookup_policy if lookup_policy is not None else LookupPolicy()
        self._relation_policy: RelationPolicy = relation_policy if relation_policy is not None else RelationPolicy()
        self._owns_connection = owns_connection
        self._cache_lock = threading.Lock()
        self._allowed_mask_cache: dict[frozenset[int], bytes] = {}

        self.pack_id: str = meta.get("pack_id", "")
        self.view_id: str = meta["source_view_id"]
        self.source_view_kind: str = meta.get("source_view_kind", "parquet-search-view")
        self.manifest_digest: str = meta["source_manifest_digest"]
        self.schemes: tuple[str, ...] = tuple(json.loads(meta["schemes_json"]))
        self.languages: tuple[str, ...] = tuple(json.loads(meta["languages_json"]))
        self.schema_version: str = meta["schema_version"]
        self.policy_version: str = meta["policy_version"]
        self.include_mappings: bool = meta.get("include_mappings") == "1"
        self.include_derived: bool = meta.get("include_derived") == "1"

        if lookups_cache is not None:
            (
                self._scheme_by_sid,
                self._sid_by_scheme,
                self._release_by_id,
                self._rel_id_by_release,
                self._pred_by_pid,
                self._rule_by_id,
                self._prefix_by_id,
                self._broader_pids,
                self._sid_by_rid,
                self._sid_by_rid_u8,
                self._max_rid,
                self._has_agency_change_events,
                self._has_agency_projections,
            ) = lookups_cache
        else:
            with self._pool.borrow() as con:
                self._scheme_by_sid = dict(con.execute("SELECT sid, uri FROM schemes"))
                self._sid_by_scheme = {uri: sid for sid, uri in self._scheme_by_sid.items()}
                self._release_by_id = dict(con.execute("SELECT rel_id, uri FROM releases"))
                self._rel_id_by_release = {uri: rel_id for rel_id, uri in self._release_by_id.items()}
                self._pred_by_pid = {
                    pid: (uri, stmt_type, bool(sym))
                    for pid, uri, stmt_type, sym in con.execute("SELECT pid, uri, stmt_type, symmetric FROM predicates")
                }
                self._rule_by_id = dict(con.execute("SELECT rule_id, uri FROM derivation_rules"))
                self._prefix_by_id = dict(con.execute("SELECT pfx_id, prefix FROM uri_prefixes"))
                self._broader_pids = tuple(
                    pid
                    for pid, (uri, stmt_type, _sym) in self._pred_by_pid.items()
                    if uri == _BROADER_URI and stmt_type in ("NativeRelationAssertion", "DerivedRelation")
                )
                max_row = con.execute("SELECT max(rid) FROM resources").fetchone()
                self._max_rid = int(max_row[0]) if max_row and max_row[0] is not None else 0
                self._sid_by_rid: array | None = None
                self._sid_by_rid_u8: bytes | None = None

                sid_blob = _read_meta_blob(con, "sid_by_rid_u16")
                if sid_blob is not None:
                    expected_bytes = (self._max_rid + 1) * 2
                    if len(sid_blob) != expected_bytes:
                        raise VocabularyPackError(
                            "corrupt_pack",
                            f"sid_by_rid_u16 blob length {len(sid_blob)} != expected {expected_bytes}",
                        )
                    self._sid_by_rid = _from_little_endian_array("H", sid_blob)
                    if max(self._scheme_by_sid, default=0) < 256:
                        self._sid_by_rid_u8 = sid_blob[::2]

                optional_tables = {
                    str(row[0])
                    for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' "
                        "AND name IN ('agency_change_events', 'agency_projections')"
                    ).fetchall()
                }
                self._has_agency_change_events = "agency_change_events" in optional_tables
                self._has_agency_projections = "agency_projections" in optional_tables

    @classmethod
    def open(
        cls,
        pack_path: Path | str,
        *,
        trusted_pack_digest: str | None = None,
        trusted_manifest_digest: str | None = None,
        verify_pack_digest: bool = True,
        mmap_bytes: int = 536_870_912,
        cache_kib: int = 32_768,
        semantic_index: SemanticIndex | None = None,
        query_encoder: QueryEncoder | None = None,
        rank_fusion: RankFusionPolicy | None = None,
        candidate_reranker: CandidateReranker | None = None,
        lookup_policy: LookupPolicy | None = None,
        relation_policy: RelationPolicy | None = None,
    ) -> AtlasVocabularyPack:
        """Open a compiled Vocabulary Pack in strict read-only immutable mmap mode.

        Set ``verify_pack_digest=False`` on pre-verified workers to skip re-hashing
        large packs on boot while still verifying ``pack_id`` and
        ``source_manifest_digest`` against any attached ``semantic_index``.
        """

        raw_path = Path(pack_path)
        _reject_symlink_path(raw_path, error_code="invalid_pack", label="vocabulary pack path")
        try:
            resolved = raw_path.resolve(strict=True)
        except OSError as exc:
            raise VocabularyPackError("missing_pack", f"vocabulary pack not found: {pack_path}") from exc
        if not resolved.is_file():
            raise VocabularyPackError("invalid_pack", f"vocabulary pack is not a regular file: {resolved}")

        computed_pack_digest: str | None = None
        if trusted_pack_digest is not None:
            expected_pack = _normalize_digest(trusted_pack_digest)
            computed_pack_digest = _sha256_file(resolved)
            if computed_pack_digest != expected_pack:
                raise VocabularyPackError("invalid_digest", "vocabulary pack digest differs from the external pin")

        uri = f"file:{quote(str(resolved))}?mode=ro&immutable=1"
        try:
            con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        except sqlite3.Error as exc:
            raise VocabularyPackError("corrupt_pack", f"failed to open vocabulary pack: {exc}") from exc

        pool: _ReadOnlyConnectionPool | None = None
        try:
            try:
                _ensure_fts5(con)
                if mmap_bytes > 0:
                    con.execute(f"PRAGMA mmap_size = {int(mmap_bytes)}")
                if cache_kib > 0:
                    con.execute(f"PRAGMA cache_size = -{int(cache_kib)}")
                meta = dict(con.execute("SELECT key, value FROM pack_meta").fetchall())
            except sqlite3.Error as exc:
                raise VocabularyPackError("corrupt_pack", f"vocabulary pack metadata is unreadable: {exc}") from exc

            if meta.get("record_type") != PACK_RECORD_TYPE or meta.get("schema_version") not in SUPPORTED_PACK_SCHEMA_VERSIONS:
                raise VocabularyPackError(
                    "unsupported_schema",
                    f"expected {PACK_RECORD_TYPE} schema version in {sorted(SUPPORTED_PACK_SCHEMA_VERSIONS)}",
                )

            required_meta = {
                "pack_id",
                "source_view_id",
                "source_manifest_digest",
                "schemes_json",
                "languages_json",
                "policy_version",
            }
            if not required_meta.issubset(meta) or not str(meta["pack_id"]).strip():
                raise VocabularyPackError("corrupt_pack", "vocabulary pack metadata is incomplete")

            if trusted_manifest_digest is not None:
                expected_manifest = _normalize_digest(trusted_manifest_digest)
                if meta["source_manifest_digest"] != expected_manifest:
                    raise VocabularyPackError(
                        "invalid_digest",
                        "vocabulary pack source manifest digest differs from the external pin",
                    )

            computed_pack_digest = _validate_semantic_wiring(
                pack_path=resolved,
                pack_id=meta["pack_id"],
                pack_sha256=computed_pack_digest,
                source_manifest_digest=meta["source_manifest_digest"],
                semantic_index=semantic_index,
                query_encoder=query_encoder,
                verify_pack_digest=verify_pack_digest,
            )

            pool = _ReadOnlyConnectionPool(uri, mmap_bytes=mmap_bytes, cache_kib=cache_kib, initial_con=con)
            try:
                return cls(
                    pack_path=resolved,
                    pool=pool,
                    meta=meta,
                    pack_sha256=computed_pack_digest,
                    semantic_index=semantic_index,
                    query_encoder=query_encoder,
                    rank_fusion=rank_fusion,
                    candidate_reranker=candidate_reranker,
                    lookup_policy=lookup_policy,
                    relation_policy=relation_policy,
                    owns_connection=True,
                )
            except VocabularyPackError:
                raise
            except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise VocabularyPackError("corrupt_pack", f"vocabulary pack tables are unreadable: {exc}") from exc
        except BaseException:
            if pool is not None:
                pool.close()
            else:
                con.close()
            raise

    def with_dependencies(
        self,
        *,
        semantic_index: SemanticIndex | None = ...,  # type: ignore[assignment]
        query_encoder: QueryEncoder | None = ...,  # type: ignore[assignment]
        rank_fusion: RankFusionPolicy | None = ...,  # type: ignore[assignment]
        candidate_reranker: CandidateReranker | None = ...,  # type: ignore[assignment]
        lookup_policy: LookupPolicy | None = ...,  # type: ignore[assignment]
        relation_policy: RelationPolicy | None = ...,  # type: ignore[assignment]
        verify_pack_digest: bool = True,
    ) -> AtlasVocabularyPack:
        """Return a lightweight DI-configured view sharing this pack's bounded connection pool."""

        new_sem = self._semantic_index if semantic_index is ... else semantic_index
        new_enc = self._query_encoder if query_encoder is ... else query_encoder
        new_fuse = self._rank_fusion if rank_fusion is ... else (rank_fusion or ExactPinnedRRF())
        new_rerank = self._candidate_reranker if candidate_reranker is ... else candidate_reranker
        new_lp = self._lookup_policy if lookup_policy is ... else (lookup_policy or LookupPolicy())
        new_rp = self._relation_policy if relation_policy is ... else (relation_policy or RelationPolicy())

        pack_sha = _validate_semantic_wiring(
            pack_path=self._path,
            pack_id=self.pack_id,
            pack_sha256=self._pack_sha256,
            source_manifest_digest=self.manifest_digest,
            semantic_index=new_sem,
            query_encoder=new_enc,
            verify_pack_digest=verify_pack_digest,
        )
        return AtlasVocabularyPack(
            pack_path=self._path,
            pool=self._pool,
            meta=self._meta,
            pack_sha256=pack_sha,
            semantic_index=new_sem,
            query_encoder=new_enc,
            rank_fusion=new_fuse,
            candidate_reranker=new_rerank,
            lookup_policy=new_lp,
            relation_policy=new_rp,
            owns_connection=False,
            lookups_cache=(
                self._scheme_by_sid,
                self._sid_by_scheme,
                self._release_by_id,
                self._rel_id_by_release,
                self._pred_by_pid,
                self._rule_by_id,
                self._prefix_by_id,
                self._broader_pids,
                self._sid_by_rid,
                self._sid_by_rid_u8,
                self._max_rid,
                self._has_agency_change_events,
                self._has_agency_projections,
            ),
        )

    @property
    def pack_path(self) -> Path:
        return self._path

    @property
    def has_semantic_index(self) -> bool:
        return self._semantic_index is not None

    @property
    def can_encode_queries(self) -> bool:
        return self._semantic_index is not None and self._query_encoder is not None

    def stats(self) -> dict[str, Any]:
        return {
            "packPath": str(self._path),
            "packId": self.pack_id,
            "schemaVersion": self.schema_version,
            "sizeBytes": self._path.stat().st_size,
            "sourceViewId": self.view_id,
            "sourceViewKind": self.source_view_kind,
            "sourceManifestDigest": self.manifest_digest,
            "schemes": list(self.schemes),
            "languages": list(self.languages),
            "includeMappings": self.include_mappings,
            "includeDerived": self.include_derived,
            "hasSemanticIndex": self.has_semantic_index,
            "canEncodeQueries": self.can_encode_queries,
            "hasCandidateReranker": self._candidate_reranker is not None,
            "counts": {
                "resources": int(self._meta.get("resource_count", "0")),
                "labeledResources": int(self._meta.get("labeled_resource_count", "0")),
                "labels": int(self._meta.get("label_count", "0")),
                "nativeEdges": int(self._meta.get("native_edge_count", "0")),
                "mappingEdges": int(self._meta.get("mapping_edge_count", "0")),
                "derivedEdges": int(self._meta.get("derived_edge_count", "0")),
                "vocabTerms": int(self._meta.get("vocab_term_count", "0")),
                "broaderCycles": int(self._meta.get("broader_cycle_count", "0")),
                "narrowerCycles": int(self._meta.get("narrower_cycle_count", "0")),
                "quarantinedCycleEdges": int(self._meta.get("quarantined_cycle_edges", "0")),
                "quarantinedNarrowerCycleEdges": int(self._meta.get("quarantined_narrower_cycle_edges", "0")),
                "agencyChangeEvents": int(self._meta.get("agency_change_event_count", "0")),
                "agencyProjections": int(self._meta.get("agency_projection_count", "0")),
            },
        }

    def close(self) -> None:
        if self._owns_connection:
            self._pool.close()

    def __enter__(self) -> AtlasVocabularyPack:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # In-Memory Scheme Mask & Semantic Dispatch Helpers
    # ------------------------------------------------------------------

    def _get_sid_by_rid(self, *, con: sqlite3.Connection | None = None) -> array:
        arr = self._sid_by_rid
        if arr is not None:
            return arr
        with self._cache_lock:
            if self._sid_by_rid is not None:
                return self._sid_by_rid
            built = array("H", [0]) * (self._max_rid + 1)
            if self._max_rid > 0:
                with contextlib.nullcontext(con) if con is not None else self._pool.borrow() as active_con:
                    for rid, sid in active_con.execute("SELECT rid, sid FROM resources"):
                        r_int = int(rid)
                        if 0 <= r_int <= self._max_rid:
                            built[r_int] = int(sid)
            self._sid_by_rid = built
            if max(self._scheme_by_sid, default=0) < 256:
                self._sid_by_rid_u8 = _to_little_endian_bytes(built)[::2]
            return built

    def _rid_matches_sids(
        self,
        rid: int,
        allowed_sids: set[int],
        *,
        con: sqlite3.Connection | None = None,
    ) -> bool:
        sid_arr = self._get_sid_by_rid(con=con)
        return 0 <= rid < len(sid_arr) and sid_arr[rid] in allowed_sids

    def _build_allowed_rids_mask(
        self,
        allowed_sids: set[int],
        *,
        con: sqlite3.Connection | None = None,
    ) -> bytes:
        key = frozenset(allowed_sids)
        with self._cache_lock:
            cached = self._allowed_mask_cache.get(key)
            if cached is not None:
                return cached

        sid_arr = self._get_sid_by_rid(con=con)
        sid_u8 = self._sid_by_rid_u8
        if sid_u8 is not None:
            table = bytearray(256)
            for sid in allowed_sids:
                if 0 <= sid < 256:
                    table[sid] = 1
            mask = sid_u8.translate(table)
        else:
            mask = bytes(1 if sid in allowed_sids else 0 for sid in sid_arr)

        with self._cache_lock:
            if len(self._allowed_mask_cache) >= _MAX_MASK_CACHE_ENTRIES:
                self._allowed_mask_cache.clear()
            self._allowed_mask_cache[key] = mask
        return mask

    def _effective_min_cosine(self, min_cosine: float | None) -> float:
        if min_cosine is not None:
            if (
                isinstance(min_cosine, bool)
                or not isinstance(min_cosine, (int, float))
                or not math.isfinite(float(min_cosine))
                or not -1.0 <= float(min_cosine) <= 1.0
            ):
                raise VocabularyInputError(
                    "invalid_min_cosine",
                    f"min_cosine must be a finite number in [-1.0, 1.0], got {min_cosine!r}",
                )
            return float(min_cosine)
        if self._lookup_policy.min_cosine is not None:
            return float(self._lookup_policy.min_cosine)
        if self._semantic_index is not None:
            rec = getattr(self._semantic_index, "recommended_min_cosine", None)
            if (
                rec is not None
                and not isinstance(rec, bool)
                and isinstance(rec, (int, float))
                and math.isfinite(float(rec))
            ):
                return float(rec)
        return DEFAULT_MIN_COSINE

    def _call_semantic_search(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        min_cosine: float,
        nprobe: int,
        allowed_rids: Any = None,
    ) -> list[tuple[int, float]]:
        assert self._semantic_index is not None
        caps = self._sem_caps
        kwargs: dict[str, Any] = {"top_k": top_k}
        if caps.supports_min_cosine:
            kwargs["min_cosine"] = min_cosine
        if caps.supports_nprobe:
            kwargs["nprobe"] = nprobe
        if allowed_rids is not None and caps.supports_allowed_rids:
            kwargs["allowed_rids"] = allowed_rids
        raw = self._semantic_index.search_rids(query_vector, **kwargs)
        if not caps.supports_min_cosine:
            raw = [(rid, sc) for rid, sc in raw if sc >= min_cosine]
        if allowed_rids is not None and not caps.supports_allowed_rids:
            checker = _prepare_allowed_checker(allowed_rids)
            if checker is not None:
                raw = [(rid, sc) for rid, sc in raw if checker(int(rid))]
        return raw

    # ------------------------------------------------------------------
    # Hydration, Context Breadcrumbs & Spelling Recovery Helpers
    # ------------------------------------------------------------------

    def _expand_uri(self, pfx_id: int, suffix: str) -> str:
        pfx = self._prefix_by_id.get(pfx_id, "")
        return pfx + suffix if pfx else suffix

    def _fetch_broader_labels(
        self,
        rids: Sequence[int],
        *,
        per_concept_limit: int = 3,
        con: sqlite3.Connection | None = None,
    ) -> dict[int, list[str]]:
        if not rids or not self._broader_pids:
            return {}
        unique_rids = list(dict.fromkeys(rids))
        p_ph = ",".join("?" for _ in self._broader_pids)
        out: dict[int, list[str]] = defaultdict(list)
        with contextlib.nullcontext(con) if con is not None else self._pool.borrow() as active_con:
            for start in range(0, len(unique_rids), _HYDRATE_CHUNK_SIZE):
                chunk = unique_rids[start : start + _HYDRATE_CHUNK_SIZE]
                r_ph = ",".join("?" for _ in chunk)
                for src_rid, pref_label in active_con.execute(
                    f"""
                    SELECT e.src_rid, r.pref_label
                    FROM edges e
                    JOIN resources r ON r.rid = e.dst_rid
                    WHERE e.src_rid IN ({r_ph})
                      AND e.pid IN ({p_ph})
                      AND r.pref_label IS NOT NULL
                    ORDER BY e.src_rid, e.stmt_kind, e.stmt_pfx, e.stmt_suffix
                    """,
                    [*chunk, *self._broader_pids],
                ):
                    bucket = out[int(src_rid)]
                    if len(bucket) < per_concept_limit and pref_label not in bucket:
                        bucket.append(pref_label)
        return out

    def _hydrate_pairs(
        self,
        rids_ordered: Sequence[int],
        *,
        include_context: bool = False,
        match_reasons: Mapping[int, str] | None = None,
        attach_internal_match_reason: bool = False,
        corrected_query: str | None = None,
        con: sqlite3.Connection | None = None,
    ) -> list[tuple[int, dict[str, Any]]]:
        if not rids_ordered:
            return []
        label_limit = self._lookup_policy.label_limit
        unique_rids = list(dict.fromkeys(rids_ordered))
        res_map: dict[int, tuple[str, int, int, str | None, int, str, str | None, int]] = {}
        lbl_map: dict[int, list[dict[str, str]]] = defaultdict(list)
        with contextlib.nullcontext(con) if con is not None else self._pool.borrow() as active_con:
            for start in range(0, len(unique_rids), _HYDRATE_CHUNK_SIZE):
                chunk = unique_rids[start : start + _HYDRATE_CHUNK_SIZE]
                ph = ",".join("?" for _ in chunk)
                for rid, res_id, sid, rel_id, defn, src_pfx, src_suf, not_json, total_lbls in active_con.execute(
                    f"""
                    SELECT rid, id, sid, rel_id, definition, src_pfx, src_suffix, notations_json, label_count
                    FROM resources WHERE rid IN ({ph})
                    """,
                    chunk,
                ):
                    res_map[rid] = (res_id, sid, rel_id, defn, src_pfx, src_suf, not_json, total_lbls)

                for rid, lbl_pfx, lbl_suf, val, role, lang in active_con.execute(
                    f"""
                    SELECT rid, lbl_pfx, lbl_suffix, value, role, language
                    FROM labels
                    WHERE rid IN ({ph})
                    ORDER BY rid, role_rank, value_lower, value, lbl_pfx, lbl_suffix
                    """,
                    chunk,
                ):
                    bucket = lbl_map[rid]
                    if len(bucket) < label_limit:
                        bucket.append(
                            {
                                "id": self._expand_uri(lbl_pfx, lbl_suf),
                                "text": val,
                                "role": role,
                                "language": lang,
                            }
                        )

            broader_map = self._fetch_broader_labels(unique_rids, con=active_con) if include_context else {}

        out: list[tuple[int, dict[str, Any]]] = []
        for rid in rids_ordered:
            row = res_map.get(rid)
            if row is None:
                continue
            res_id, sid, rel_id, defn, src_pfx, src_suf, not_json, total_lbls = row
            labels = lbl_map.get(rid, [])
            if not labels:
                raise VocabularyPackError("corrupt_pack", f"concept {res_id!r} has no labels in pack")
            concept: dict[str, Any] = {
                "id": res_id,
                "scheme": self._scheme_by_sid[sid],
                "release": self._release_by_id[rel_id],
                "label": labels[0]["text"],
                "definition": defn,
                "labels": labels,
                "sourceRecord": self._expand_uri(src_pfx, src_suf),
                "provenance": {
                    "viewId": self.view_id,
                    "manifestDigest": self.manifest_digest,
                },
            }
            if total_lbls > label_limit:
                concept["labelsTruncated"] = True
                concept["totalLabelCount"] = total_lbls
            if include_context:
                concept["notations"] = json.loads(not_json) if not_json else []
                concept["broaderLabels"] = broader_map.get(rid, [])
                if match_reasons and rid in match_reasons:
                    concept["matchReason"] = match_reasons[rid]
                if corrected_query is not None:
                    concept["correctedQuery"] = corrected_query
            elif attach_internal_match_reason and match_reasons and rid in match_reasons:
                concept["_matchReason"] = match_reasons[rid]
            out.append((rid, concept))
        return out

    def _hydrate(
        self,
        rids_ordered: Sequence[int],
        *,
        include_context: bool = False,
        match_reasons: Mapping[int, str] | None = None,
        attach_internal_match_reason: bool = False,
        corrected_query: str | None = None,
        con: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        return [
            concept
            for _, concept in self._hydrate_pairs(
                rids_ordered,
                include_context=include_context,
                match_reasons=match_reasons,
                attach_internal_match_reason=attach_internal_match_reason,
                corrected_query=corrected_query,
                con=con,
            )
        ]

    def _resolve_seed_rid(
        self,
        reference: Mapping[str, Any],
        *,
        con: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, str], int]:
        ref = _normalize_reference(reference)
        sid = self._sid_by_scheme.get(ref["scheme"])
        rel_id = self._rel_id_by_release.get(ref["release"])
        if sid is None or rel_id is None:
            raise VocabularyInputError("unknown_concept", "concept is absent at the selected scheme and release")
        with contextlib.nullcontext(con) if con is not None else self._pool.borrow() as active_con:
            row = active_con.execute(
                "SELECT rid, pref_label FROM resources WHERE id = ? AND sid = ? AND rel_id = ?",
                (ref["id"], sid, rel_id),
            ).fetchone()
        if row is None or row[1] is None:
            raise VocabularyInputError("unknown_concept", "concept is absent at the selected scheme and release")
        return ref, int(row[0])

    def _spell_correct_tokens(
        self,
        tokens: Sequence[str],
        *,
        con: sqlite3.Connection | None = None,
    ) -> list[str] | None:
        """Zero-ML spelling correction against real vocabulary words in ``vocab_terms_trigram``.

        Enforces ``len(tok) >= 6``, ``trigram_dice(tok, cand) >= 0.55``, and
        ``doc_freq >= 2 or (dist == 1 and dice >= 0.60)`` so short nonsense queries
        (``"qwert"``, ``"plonk"``, ``"snark"``, ``"grump"``) abstain cleanly.
        """

        if not tokens:
            return None
        corrected: list[str] = []
        changed = False
        with contextlib.nullcontext(con) if con is not None else self._pool.borrow() as active_con:
            for raw_tok in tokens:
                tok = normalize_text(raw_tok)
                if active_con.execute("SELECT 1 FROM vocab_terms WHERE term = ?", (tok,)).fetchone() is not None:
                    corrected.append(tok)
                    continue
                if len(tok) < 6:
                    return None
                max_dist = 1 if len(tok) <= 8 else 2
                q_tris = list(dict.fromkeys(tok[i : i + 3] for i in range(len(tok) - 2)))
                if not q_tris:
                    return None
                tri_expr = " OR ".join('"' + t.replace('"', '""') + '"' for t in q_tris[:12])
                cand_rows = active_con.execute(
                    """
                    SELECT v.term, v.doc_freq
                    FROM vocab_terms_trigram t
                    JOIN vocab_terms v ON v.tid = t.rowid
                    WHERE vocab_terms_trigram MATCH ?
                      AND length(v.term) BETWEEN ? AND ?
                    ORDER BY bm25(vocab_terms_trigram)
                    LIMIT 80
                    """,
                    (tri_expr, len(tok) - max_dist, len(tok) + max_dist),
                ).fetchall()

                best_term: str | None = None
                best_key: tuple[int, float, int, str] | None = None
                for cand_term, df in cand_rows:
                    cand_norm = normalize_text(str(cand_term))
                    dist = _damerau_levenshtein(tok, cand_norm, max_dist)
                    if dist > max_dist:
                        continue
                    dice = _trigram_dice(tok, cand_norm)
                    if dice < 0.55:
                        continue
                    df_int = int(df)
                    if df_int < 2 and not (dist == 1 and dice >= 0.60):
                        continue
                    key = (dist, -dice, -df_int, cand_norm)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_term = str(cand_term)
                if best_term is None:
                    return None
                corrected.append(best_term)
                changed = True
        return corrected if changed else None

    def _filter_min_token_coverage(
        self,
        rids: Sequence[int],
        tokens: Sequence[str],
        min_matches: int,
        *,
        con: sqlite3.Connection | None = None,
    ) -> list[int]:
        """Abstention gate: retain only concepts matching >= ``min_matches`` distinct normalized query tokens."""

        if not rids:
            return []
        unique_query_tokens = list(dict.fromkeys(normalize_text(t) for t in tokens if t))
        if len(unique_query_tokens) < min_matches:
            return []

        unique_rids = list(dict.fromkeys(rids))
        lbl_tokens: dict[int, set[str]] = defaultdict(set)
        with contextlib.nullcontext(con) if con is not None else self._pool.borrow() as active_con:
            for start in range(0, len(unique_rids), _HYDRATE_CHUNK_SIZE):
                chunk = unique_rids[start : start + _HYDRATE_CHUNK_SIZE]
                ph = ",".join("?" for _ in chunk)
                for rid, val_lower in active_con.execute(
                    f"SELECT rid, value_lower FROM labels WHERE rid IN ({ph})",
                    chunk,
                ):
                    lbl_tokens[rid].update(_tokenize(val_lower))
                for rid, defn in active_con.execute(
                    f"SELECT rid, definition FROM resources WHERE rid IN ({ph}) AND definition IS NOT NULL",
                    chunk,
                ):
                    lbl_tokens[rid].update(_tokenize(defn))

        kept: list[int] = []
        for rid in rids:
            bag = lbl_tokens.get(rid)
            if not bag:
                continue
            matched = 0
            for tok in unique_query_tokens:
                if tok in bag:
                    matched += 1
            if matched >= min_matches:
                kept.append(rid)
        return kept

    def _group_by_identical_label(self, concepts: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """Group duplicate normalized-label cards across schemes while preserving all source identities."""

        return group_by_identical_label(concepts, limit)

    # ------------------------------------------------------------------
    # Public Synchronous Query API
    # ------------------------------------------------------------------

    def lookup_with_meta_sync(
        self,
        query: str,
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        query_vector: Sequence[float] | None = None,
        group_identical_labels: bool | None = None,
        include_context: bool | None = None,
        min_cosine: float | None = None,
        nprobe: int | None = None,
    ) -> dict[str, Any]:
        """Lookup returning concepts alongside transparent ``correctedQuery`` and ``tier`` metadata."""

        if not isinstance(query, str) or not query.strip() or len(query) > _QUERY_LIMIT:
            raise VocabularyInputError("invalid_query", f"query must be non-empty text of at most {_QUERY_LIMIT} chars")
        limit = _normalize_limit(limit, maximum=_MAX_LOOKUP_LIMIT, name="limit")

        lp = self._lookup_policy
        use_grouping = lp.group_identical_labels if group_identical_labels is None else group_identical_labels
        use_context = lp.include_context if include_context is None else include_context
        eff_min_cosine = self._effective_min_cosine(min_cosine)
        eff_nprobe = lp.nprobe if nprobe is None else nprobe

        self._pool.check_open()

        allowed_sids: set[int] | None = None
        if schemes is not None:
            req_schemes = _normalize_schemes(schemes)
            allowed_sids = {self._sid_by_scheme[s] for s in req_schemes if s in self._sid_by_scheme}
            if not allowed_sids:
                return {"concepts": [], "query": query, "correctedQuery": None, "tier": "empty"}

        q_clean = query.strip()
        ql = normalize_text(q_clean)
        ql_legacy_raw = q_clean.lower()
        exact_keys: tuple[str, ...] = (
            (ql, ql_legacy_raw) if (self.schema_version == "2" and ql_legacy_raw != ql) else (ql,)
        )
        tokens = _tokenize(q_clean)
        unique_tokens = list(dict.fromkeys(tokens))

        # Fetch deeper candidate pool whenever reranker or label grouping will re-score/collapse hits!
        needs_rerank_pool = self._candidate_reranker is not None
        fetch_limit = (
            min(max(limit * 4, 48), 100) if needs_rerank_pool else (min(limit * 3, 60) if use_grouping else limit)
        )

        active_vec: Sequence[float] | None = query_vector
        if active_vec is None and self._semantic_index is not None and self._query_encoder is not None:
            try:
                active_vec = self._query_encoder.encode_query(q_clean)
            except Exception as exc:
                if not lp.fallback_on_encoder_error:
                    raise VocabularyPackError("encoder_failed", f"query encoder failed: {exc}") from exc
                active_vec = None
        will_use_semantic = active_vec is not None and self._semantic_index is not None

        sorted_sids = sorted(allowed_sids) if allowed_sids is not None else None
        s_ph = ",".join("?" for _ in sorted_sids) if sorted_sids is not None else ""

        def _exact_role_reason(role_rank: int) -> str:
            if role_rank == 0:
                return "exact_preferred"
            if role_rank == 1:
                return "exact_alternate"
            return "exact_hidden"

        match_reasons: dict[int, str] = {}
        corrected_query: str | None = None
        winning_tier = "empty"

        # Tier 0-2 lexical retrieval under one borrowed SQLite connection.
        exact_rids: list[int] = []
        exact_set: set[int] = set()
        bm25_rids: list[int] = []
        bm25_set: set[int] = set()
        allowed_mask: bytes | None = None

        with self._pool.borrow() as con:
            # Tier 0: Exact label match (preferred role before alternate, then canonical rid order).
            # Push scheme filter into SQL BEFORE LIMIT so earlier-alphabetical schemes never crowd out selected schemes!
            if len(exact_keys) == 1:
                if sorted_sids is not None:
                    exact_rows = con.execute(
                        f"""
                        SELECT le.rid, le.role_rank
                        FROM label_exact le
                        JOIN resources r ON r.rid = le.rid
                        WHERE le.value_lower = ? AND r.sid IN ({s_ph})
                        ORDER BY le.role_rank, le.rid
                        LIMIT ?
                        """,
                        [exact_keys[0], *sorted_sids, fetch_limit * 2],
                    )
                else:
                    exact_rows = con.execute(
                        """
                        SELECT rid, role_rank FROM label_exact
                        WHERE value_lower = ?
                        ORDER BY role_rank, rid
                        LIMIT ?
                        """,
                        (exact_keys[0], fetch_limit * 2),
                    )
            else:
                ek_ph = ",".join("?" for _ in exact_keys)
                if sorted_sids is not None:
                    exact_rows = con.execute(
                        f"""
                        SELECT le.rid, le.role_rank
                        FROM label_exact le
                        JOIN resources r ON r.rid = le.rid
                        WHERE le.value_lower IN ({ek_ph}) AND r.sid IN ({s_ph})
                        ORDER BY le.role_rank, le.rid
                        LIMIT ?
                        """,
                        [*exact_keys, *sorted_sids, fetch_limit * 2],
                    )
                else:
                    exact_rows = con.execute(
                        f"""
                        SELECT rid, role_rank FROM label_exact
                        WHERE value_lower IN ({ek_ph})
                        ORDER BY role_rank, rid
                        LIMIT ?
                        """,
                        [*exact_keys, fetch_limit * 2],
                    )
            for rid, role_rank in exact_rows:
                if rid not in exact_set:
                    exact_set.add(rid)
                    exact_rids.append(rid)
                    match_reasons[rid] = _exact_role_reason(int(role_rank))
                    if len(exact_rids) >= fetch_limit:
                        break
            if exact_rids:
                winning_tier = "exact"

            # Stage-0 hybrid & lexical short-circuit: when exact hits ALREADY fill fetch_limit
            # (== limit when not requesting a deeper rerank/grouping pool), skip the 41 ms FTS5 scan
            # completely while keeping exact hits pinned above RRF!
            need_bm25 = len(exact_rids) < fetch_limit
            if need_bm25 and tokens:
                bm25_cap = max(fetch_limit * 2, 30)
                bm25_sql_limit = max(fetch_limit * 3, 40)

                def _exec_bm25(expr: str, sql_limit: int) -> sqlite3.Cursor:
                    if sorted_sids is not None:
                        return con.execute(
                            f"""
                            SELECT concepts_bm25.rowid
                            FROM concepts_bm25
                            JOIN resources r ON r.rid = concepts_bm25.rowid
                            WHERE concepts_bm25 MATCH ? AND r.sid IN ({s_ph})
                            ORDER BY bm25(concepts_bm25, 10.0, 5.0, 1.0), concepts_bm25.rowid
                            LIMIT ?
                            """,
                            [expr, *sorted_sids, sql_limit],
                        )
                    return con.execute(
                        """
                        SELECT rowid FROM concepts_bm25
                        WHERE concepts_bm25 MATCH ?
                        ORDER BY bm25(concepts_bm25, 10.0, 5.0, 1.0), rowid
                        LIMIT ?
                        """,
                        (expr, sql_limit),
                    )

                # Step 1a: Exact-token AND first so common short words (e.g. "law") avoid scanning
                # 80k+ wildcard prefix postings and rank exact-token concepts ahead of prefix words.
                exact_tok_expr = " AND ".join(f'"{t}"' for t in unique_tokens)
                for (rid,) in _exec_bm25(exact_tok_expr, bm25_sql_limit):
                    if rid not in bm25_set:
                        bm25_set.add(rid)
                        bm25_rids.append(rid)
                        match_reasons.setdefault(rid, "bm25")
                        if len(bm25_rids) >= bm25_cap:
                            break

                # Step 1b: Wildcard prefix fallback ONLY when exact-token hits did not fill lexical_target
                # (pure lexical) or bm25_cap (semantic), preserving typeahead and plural headings ("veteran" -> "Veterans").
                lexical_target = fetch_limit if (use_grouping or needs_rerank_pool) else limit
                need_prefix = (
                    len(bm25_rids) < bm25_cap if will_use_semantic else len(exact_set | bm25_set) < lexical_target
                )
                if need_prefix and len(tokens[-1]) >= 3:
                    prefix_expr = " AND ".join(
                        f'"{t}"*' if i == len(tokens) - 1 else f'"{t}"' for i, t in enumerate(tokens)
                    )
                    for (rid,) in _exec_bm25(prefix_expr, bm25_sql_limit + len(bm25_set)):
                        if rid not in bm25_set:
                            bm25_set.add(rid)
                            bm25_rids.append(rid)
                            match_reasons.setdefault(rid, "bm25")
                            if len(bm25_rids) >= bm25_cap:
                                break
                # Step 1c: For 2-token queries with len(tokens[0]) >= 4 (e.g. "veteran benefits" -> "Veterans benefits"),
                # run a targeted AND-prefix query instead of a full OR posting scan.
                if (
                    len(unique_tokens) == 2
                    and len(tokens) == 2
                    and len(tokens[0]) >= 4
                    and (len(bm25_rids) < bm25_cap if will_use_semantic else len(exact_set | bm25_set) < lexical_target)
                ):
                    t1_part = f'"{tokens[1]}"*' if len(tokens[1]) >= 3 else f'"{tokens[1]}"'
                    both_prefix_expr = f'"{tokens[0]}"* AND {t1_part}'
                    for (rid,) in _exec_bm25(both_prefix_expr, bm25_sql_limit + len(bm25_set)):
                        if rid not in bm25_set:
                            bm25_set.add(rid)
                            bm25_rids.append(rid)
                            match_reasons.setdefault(rid, "bm25")
                            if len(bm25_rids) >= bm25_cap:
                                break
                if bm25_rids and winning_tier == "empty":
                    winning_tier = "bm25"

            # Tier 2: Abstention-gated soft OR BM25 for >=3 distinct tokens when AND yields fewer than lexical_target hits.
            # Filter out short/English function stopwords and drop `*` wildcards to eliminate 60-80 ms 0-hit cliffs!
            lexical_count = len(exact_set | bm25_set)
            lexical_target_or = fetch_limit if (use_grouping or needs_rerank_pool) else limit
            if lp.enable_soft_or_fallback and lexical_count < lexical_target_or and len(unique_tokens) >= 3:
                or_tokens = [t for t in unique_tokens if len(t) >= 3 and t not in _COMMON_FUNCTION_WORDS]
                if len(or_tokens) >= 2:
                    or_expr = " OR ".join(f'"{t}"' for t in or_tokens)
                    or_sql_limit = max(fetch_limit * 4, 60)
                    if sorted_sids is not None:
                        or_rows = con.execute(
                            f"""
                            SELECT concepts_bm25.rowid
                            FROM concepts_bm25
                            JOIN resources r ON r.rid = concepts_bm25.rowid
                            WHERE concepts_bm25 MATCH ? AND r.sid IN ({s_ph})
                            ORDER BY bm25(concepts_bm25, 10.0, 5.0, 1.0), concepts_bm25.rowid
                            LIMIT ?
                            """,
                            [or_expr, *sorted_sids, or_sql_limit],
                        )
                    else:
                        or_rows = con.execute(
                            """
                            SELECT rowid FROM concepts_bm25
                            WHERE concepts_bm25 MATCH ?
                            ORDER BY bm25(concepts_bm25, 10.0, 5.0, 1.0), rowid
                            LIMIT ?
                            """,
                            (or_expr, or_sql_limit),
                        )
                    or_cands = [row[0] for row in or_rows if row[0] not in exact_set and row[0] not in bm25_set]
                    min_match = max(2, math.ceil(len(or_tokens) / 2))
                    for rid in self._filter_min_token_coverage(or_cands, or_tokens, min_match, con=con):
                        bm25_set.add(rid)
                        bm25_rids.append(rid)
                        match_reasons.setdefault(rid, "bm25_or")
                        if len(exact_set | bm25_set) >= fetch_limit:
                            break
                    if bm25_rids and winning_tier == "empty":
                        winning_tier = "bm25_or"

            if will_use_semantic and allowed_sids is not None:
                allowed_mask = self._build_allowed_rids_mask(allowed_sids, con=con)

        # Optional Tier-1 Semantic Retrieval runs outside SQLite borrow BEFORE Tier-3 spelling so
        # cross-lingual queries (e.g. "embarazo" -> "Pregnancy", "carpeta" -> folder) are NEVER
        # hard-overridden by near-edit lexical false friends!
        dense_hits: list[tuple[int, float]] = []
        if will_use_semantic:
            assert active_vec is not None and self._semantic_index is not None
            dense_depth = max(fetch_limit * 3, 80) if needs_rerank_pool else max(fetch_limit * 3, 40)
            dense_raw = self._call_semantic_search(
                active_vec,
                top_k=dense_depth,
                min_cosine=eff_min_cosine,
                nprobe=eff_nprobe,
                allowed_rids=allowed_mask,
            )
            if allowed_sids is not None:
                dense_hits = [(rid, sc) for rid, sc in dense_raw if self._rid_matches_sids(rid, allowed_sids)]
            else:
                dense_hits = list(dense_raw)
            for rid, _sc in dense_hits:
                match_reasons.setdefault(rid, "semantic_hybrid")

        # Tier 3 spelling recovery & final hydration under one borrowed SQLite connection.
        with self._pool.borrow() as con:
            # Tier 3: Zero-ML Damerau-Levenshtein + trigram-Dice spelling correction when lexical
            # Tiers 0-2 yield 0 hits. When dense_hits is empty (pure lexical), keep exact spelling
            # matches in exact_rids. When dense_hits is non-empty (hybrid), place spelling hits in
            # bm25_rids (RRF lexical list) instead of exact_rids so genuine typos fuse cleanly via
            # RRF without a hard 100.0 override hijacking foreign false friends ("carpeta"->"carpet").
            if lp.enable_spelling_correction and not exact_rids and not bm25_rids and tokens:
                corrected = self._spell_correct_tokens(tokens, con=con)
                if corrected is not None:
                    corr_phrase = " ".join(corrected)
                    if sorted_sids is not None:
                        corr_exact_rows = con.execute(
                            f"""
                            SELECT le.rid
                            FROM label_exact le
                            JOIN resources r ON r.rid = le.rid
                            WHERE le.value_lower = ? AND r.sid IN ({s_ph})
                            ORDER BY le.role_rank, le.rid
                            LIMIT ?
                            """,
                            [corr_phrase, *sorted_sids, fetch_limit],
                        )
                    else:
                        corr_exact_rows = con.execute(
                            "SELECT rid FROM label_exact WHERE value_lower = ? ORDER BY role_rank, rid LIMIT ?",
                            (corr_phrase, fetch_limit),
                        )
                    for (rid,) in corr_exact_rows:
                        if not dense_hits:
                            if rid not in exact_set:
                                exact_set.add(rid)
                                exact_rids.append(rid)
                                match_reasons[rid] = "spelling_corrected"
                        elif rid not in bm25_set:
                            bm25_set.add(rid)
                            bm25_rids.append(rid)
                            match_reasons[rid] = "spelling_corrected"
                    if len(exact_rids) + len(bm25_rids) < fetch_limit:
                        corr_expr = " AND ".join(
                            f'"{t}"*' if i == len(corrected) - 1 and len(t) >= 3 else f'"{t}"'
                            for i, t in enumerate(corrected)
                        )
                        if sorted_sids is not None:
                            corr_bm25_rows = con.execute(
                                f"""
                                SELECT concepts_bm25.rowid
                                FROM concepts_bm25
                                JOIN resources r ON r.rid = concepts_bm25.rowid
                                WHERE concepts_bm25 MATCH ? AND r.sid IN ({s_ph})
                                ORDER BY bm25(concepts_bm25, 10.0, 5.0, 1.0), concepts_bm25.rowid
                                LIMIT ?
                                """,
                                [corr_expr, *sorted_sids, fetch_limit * 2],
                            )
                        else:
                            corr_bm25_rows = con.execute(
                                """
                                SELECT rowid FROM concepts_bm25
                                WHERE concepts_bm25 MATCH ?
                                ORDER BY bm25(concepts_bm25, 10.0, 5.0, 1.0), rowid
                                LIMIT ?
                                """,
                                (corr_expr, fetch_limit * 2),
                            )
                        for (rid,) in corr_bm25_rows:
                            if rid not in exact_set and rid not in bm25_set:
                                bm25_set.add(rid)
                                bm25_rids.append(rid)
                                match_reasons.setdefault(rid, "spelling_corrected")
                                if len(exact_rids) + len(bm25_rids) >= fetch_limit:
                                    break
                    if exact_rids or bm25_rids:
                        corrected_query = corr_phrase
                        winning_tier = "spelling_corrected"

            if will_use_semantic:
                final_rids = self._rank_fusion.fuse(
                    exact_rids=exact_rids,
                    lexical_rids=bm25_rids,
                    dense_hits=dense_hits,
                    limit=fetch_limit,
                )
                if final_rids and dense_hits and winning_tier in ("empty", "bm25", "bm25_or"):
                    winning_tier = "semantic_hybrid"
            else:
                final_rids = list(exact_rids)
                for rid in bm25_rids:
                    if rid not in exact_set:
                        final_rids.append(rid)
                        if len(final_rids) >= fetch_limit:
                            break
                final_rids = final_rids[:fetch_limit]

            hydrated = self._hydrate(
                final_rids,
                include_context=use_context,
                match_reasons=match_reasons if (use_context or needs_rerank_pool) else None,
                attach_internal_match_reason=needs_rerank_pool and not use_context,
                corrected_query=corrected_query,
                con=con,
            )

        # Optional injected CandidateReranker (e.g. AuthorityReranker or Pure-ANE cross-encoder).
        if self._candidate_reranker is not None and hydrated:
            rerank_limit = (
                min(limit * 3, 60)
                if (use_grouping and not getattr(self._candidate_reranker, "deduplicate_labels", False))
                else limit
            )
            reranked = self._candidate_reranker.rerank(
                query=corrected_query or q_clean,
                candidates=hydrated,
                limit=rerank_limit,
            )
            if not use_context:
                for card in reranked:
                    card.pop("_matchReason", None)
            hydrated = reranked

        if use_grouping and not (
            self._candidate_reranker is not None and getattr(self._candidate_reranker, "deduplicate_labels", False)
        ):
            concepts = self._group_by_identical_label(hydrated, limit)
        else:
            concepts = hydrated[:limit]

        return {
            "concepts": concepts,
            "query": query,
            "correctedQuery": corrected_query,
            "tier": winning_tier,
        }

    def lookup_sync(
        self,
        query: str,
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        query_vector: Sequence[float] | None = None,
        group_identical_labels: bool | None = None,
        include_context: bool | None = None,
        min_cosine: float | None = None,
        nprobe: int | None = None,
    ) -> list[dict[str, Any]]:
        """Tiered exact -> prefix/AND BM25 -> abstention-gated OR -> dense -> spelling correction."""

        return self.lookup_with_meta_sync(
            query,
            limit,
            schemes=schemes,
            query_vector=query_vector,
            group_identical_labels=group_identical_labels,
            include_context=include_context,
            min_cosine=min_cosine,
            nprobe=nprobe,
        )["concepts"]

    def resolve_sync(self, reference: Mapping[str, Any], *, include_context: bool = False) -> dict[str, Any]:
        """Resolve an exact (id, scheme, release) concept reference with full provenance."""

        with self._pool.borrow() as con:
            _ref, rid = self._resolve_seed_rid(reference, con=con)
            return self._hydrate([rid], include_context=include_context, con=con)[0]

    def related_sync(
        self,
        reference: Mapping[str, Any],
        limit: int = 20,
        *,
        include_mappings: bool | None = None,
        default_mappings_only: bool | None = None,
        include_symmetric_inverse: bool | None = None,
        include_derived: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded related concepts with exact assertion & REF-035/derived provenance."""

        limit = _normalize_limit(limit, maximum=_MAX_RELATED_LIMIT, name="limit")

        rp = self._relation_policy
        use_mappings = rp.include_mappings if include_mappings is None else include_mappings
        use_default_only = rp.default_mappings_only if default_mappings_only is None else default_mappings_only
        use_sym_inv = rp.include_symmetric_inverse if include_symmetric_inverse is None else include_symmetric_inverse
        use_derived = rp.include_derived if include_derived is None else include_derived

        raw_edges: list[tuple[int, str, int, int, str, int, int]] = []

        with self._pool.borrow() as con:
            ref, src_rid = self._resolve_seed_rid(reference, con=con)

            for pid, stmt_pfx, stmt_suf, dst_rid, is_def, rule_id in con.execute(
                """
                SELECT e.pid, e.stmt_pfx, e.stmt_suffix, e.dst_rid, e.ref035_default, e.rule_id
                FROM edges e
                LEFT JOIN uri_prefixes up ON up.pfx_id = e.stmt_pfx
                WHERE e.src_rid = ? AND e.stmt_kind = ?
                ORDER BY e.pid, (COALESCE(up.prefix, '') || e.stmt_suffix), e.dst_rid
                LIMIT ?
                """,
                (src_rid, _STMT_KIND_NATIVE, limit),
            ):
                pred_uri, _st, _sym = self._pred_by_pid[pid]
                stmt_id = self._expand_uri(stmt_pfx, stmt_suf)
                raw_edges.append((0, pred_uri, dst_rid, pid, stmt_id, is_def, rule_id))

            if use_mappings and len(raw_edges) < limit:
                remaining = limit - len(raw_edges)
                if use_default_only:
                    fwd_rows = con.execute(
                        """
                        SELECT e.pid, e.stmt_pfx, e.stmt_suffix, e.dst_rid, e.ref035_default
                        FROM edges e
                        LEFT JOIN uri_prefixes up ON up.pfx_id = e.stmt_pfx
                        WHERE e.src_rid = ? AND e.stmt_kind = ? AND e.ref035_default = 1
                        ORDER BY e.pid, (COALESCE(up.prefix, '') || e.stmt_suffix), e.dst_rid
                        LIMIT ?
                        """,
                        (src_rid, _STMT_KIND_MAPPING, remaining),
                    ).fetchall()
                else:
                    fwd_rows = con.execute(
                        """
                        SELECT e.pid, e.stmt_pfx, e.stmt_suffix, e.dst_rid, e.ref035_default
                        FROM edges e
                        LEFT JOIN uri_prefixes up ON up.pfx_id = e.stmt_pfx
                        WHERE e.src_rid = ? AND e.stmt_kind = ?
                        ORDER BY e.ref035_default DESC, e.pid, (COALESCE(up.prefix, '') || e.stmt_suffix), e.dst_rid
                        LIMIT ?
                        """,
                        (src_rid, _STMT_KIND_MAPPING, remaining),
                    ).fetchall()
                seen_stmt_dst: set[tuple[str, int]] = set()
                for pid, stmt_pfx, stmt_suf, dst_rid, is_def in fwd_rows:
                    pred_uri, _st, _sym = self._pred_by_pid[pid]
                    stmt_id = self._expand_uri(stmt_pfx, stmt_suf)
                    seen_stmt_dst.add((stmt_id, dst_rid))
                    raw_edges.append((1, pred_uri, dst_rid, pid, stmt_id, is_def, 0))

                if use_sym_inv and len(raw_edges) < limit:
                    rem2 = limit - len(raw_edges)
                    if use_default_only:
                        rev_rows = con.execute(
                            """
                            SELECT e.pid, e.stmt_pfx, e.stmt_suffix, e.src_rid, e.ref035_default
                            FROM edges_rev e
                            LEFT JOIN uri_prefixes up ON up.pfx_id = e.stmt_pfx
                            WHERE e.dst_rid = ? AND e.ref035_default = 1
                            ORDER BY e.pid, (COALESCE(up.prefix, '') || e.stmt_suffix), e.src_rid
                            LIMIT ?
                            """,
                            (src_rid, rem2 * 2),
                        ).fetchall()
                    else:
                        rev_rows = con.execute(
                            """
                            SELECT e.pid, e.stmt_pfx, e.stmt_suffix, e.src_rid, e.ref035_default
                            FROM edges_rev e
                            LEFT JOIN uri_prefixes up ON up.pfx_id = e.stmt_pfx
                            WHERE e.dst_rid = ?
                            ORDER BY e.ref035_default DESC, e.pid, (COALESCE(up.prefix, '') || e.stmt_suffix), e.src_rid
                            LIMIT ?
                            """,
                            (src_rid, rem2 * 2),
                        ).fetchall()
                    for pid, stmt_pfx, stmt_suf, other_rid, is_def in rev_rows:
                        stmt_id = self._expand_uri(stmt_pfx, stmt_suf)
                        if (stmt_id, other_rid) in seen_stmt_dst:
                            continue
                        pred_uri, _st, _sym = self._pred_by_pid[pid]
                        raw_edges.append((2, pred_uri, other_rid, pid, stmt_id, is_def, -1))
                        if len(raw_edges) >= limit:
                            break

            if use_derived and len(raw_edges) < limit:
                rem3 = limit - len(raw_edges)
                for pid, stmt_pfx, stmt_suf, dst_rid, is_def, rule_id in con.execute(
                    """
                    SELECT e.pid, e.stmt_pfx, e.stmt_suffix, e.dst_rid, e.ref035_default, e.rule_id
                    FROM edges e
                    LEFT JOIN uri_prefixes up ON up.pfx_id = e.stmt_pfx
                    WHERE e.src_rid = ? AND e.stmt_kind = ?
                    ORDER BY e.pid, (COALESCE(up.prefix, '') || e.stmt_suffix), e.dst_rid
                    LIMIT ?
                    """,
                    (src_rid, _STMT_KIND_DERIVED, rem3),
                ):
                    pred_uri, _st, _sym = self._pred_by_pid[pid]
                    stmt_id = self._expand_uri(stmt_pfx, stmt_suf)
                    raw_edges.append((3, pred_uri, dst_rid, pid, stmt_id, is_def, rule_id))

            if not raw_edges:
                return []

            unique_dst_rids = list(dict.fromkeys(edge[2] for edge in raw_edges))
            hydrated_by_rid: dict[int, dict[str, Any]] = dict(self._hydrate_pairs(unique_dst_rids, con=con))
            missing_rids = [rid for rid in unique_dst_rids if rid not in hydrated_by_rid]
            if missing_rids:
                raise VocabularyPackError(
                    "corrupt_pack",
                    f"related edge targets missing resource id(s) in pack: {missing_rids[:5]}",
                )

        raw_edges.sort(
            key=lambda e: (
                e[0],
                -e[5] if (e[0] in (1, 2) and not use_default_only) else 0,
                e[1],
                e[4],
                hydrated_by_rid[e[2]]["scheme"],
            )
        )

        results: list[dict[str, Any]] = []
        for priority, pred_uri, dst_rid, pid, stmt_id, is_def, rule_or_flag in raw_edges[:limit]:
            target_concept = hydrated_by_rid[dst_rid]
            target_ref = {
                "id": target_concept["id"],
                "scheme": target_concept["scheme"],
                "release": target_concept["release"],
            }
            _p_uri, stmt_type, _sym = self._pred_by_pid[pid]
            relation: dict[str, Any] = {
                "id": stmt_id,
                "type": pred_uri,
                "source": dict(ref),
                "target": target_ref,
            }
            if priority == 1:
                relation["statementType"] = stmt_type
                relation["direction"] = "forward"
                relation["evidenceDefaultEligible"] = bool(is_def)
            elif priority == 2:
                relation["statementType"] = stmt_type
                relation["direction"] = "inverse"
                relation["assertedSource"] = target_ref
                relation["assertedTarget"] = dict(ref)
                relation["evidenceDefaultEligible"] = bool(is_def)
            elif priority == 3:
                relation["statementType"] = stmt_type
                relation["asserted"] = False
                rule_uri = self._rule_by_id.get(rule_or_flag, "")
                if rule_uri:
                    relation["derivationRule"] = rule_uri

            results.append({"concept": target_concept, "relation": relation})
        return results

    def similar_sync(
        self,
        reference: Mapping[str, Any],
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        min_cosine: float | None = None,
        exclude_same_scheme: bool = False,
        nprobe: int | None = None,
        include_context: bool = False,
    ) -> list[dict[str, Any]]:
        """Offline concept-to-concept semantic similarity using stored sidecar vectors (zero query encoder!).

        Pushes scheme / ``exclude_same_scheme`` constraints as an ``allowed_rids``
        mask directly into ``SemanticIndex.search_rids`` (with O(1) in-memory
        ``sid_by_rid`` verification and zero N+1 SQL).
        """

        if self._semantic_index is None:
            raise VocabularyPackError(
                "missing_semantic_index",
                "similar() requires an injected SemanticIndex sidecar",
            )
        limit = _normalize_limit(limit, maximum=_MAX_LOOKUP_LIMIT, name="limit")
        eff_min_cos = self._effective_min_cosine(min_cosine)
        eff_nprobe = self._lookup_policy.nprobe if nprobe is None else nprobe

        allowed_sids: set[int] | None = None
        if schemes is not None:
            req_schemes = _normalize_schemes(schemes)
            allowed_sids = {self._sid_by_scheme[s] for s in req_schemes if s in self._sid_by_scheme}

        with self._pool.borrow() as con:
            ref, seed_rid = self._resolve_seed_rid(reference, con=con)
            if schemes is not None and not allowed_sids:
                return []
            seed_sid = self._sid_by_scheme[ref["scheme"]]
            effective_sids: set[int] | None = allowed_sids
            if exclude_same_scheme:
                base_sids = set(self._scheme_by_sid) if effective_sids is None else set(effective_sids)
                base_sids.discard(seed_sid)
                if not base_sids:
                    return []
                effective_sids = base_sids
            allowed_mask = (
                self._build_allowed_rids_mask(effective_sids, con=con) if effective_sids is not None else None
            )

        seed_vec = self._semantic_index.vector_for_rid(seed_rid)
        if seed_vec is None:
            return []

        raw_hits = self._call_semantic_search(
            seed_vec,
            top_k=max(limit * 4, 40) + 1,
            min_cosine=eff_min_cos,
            nprobe=eff_nprobe,
            allowed_rids=allowed_mask,
        )
        filtered_rids: list[int] = []
        score_by_rid: dict[int, float] = {}
        for rid, score in raw_hits:
            if rid == seed_rid:
                continue
            if effective_sids is not None and not self._rid_matches_sids(rid, effective_sids):
                continue
            filtered_rids.append(rid)
            score_by_rid[rid] = float(score)
            if len(filtered_rids) >= limit:
                break

        if not filtered_rids:
            return []
        hydrated_pairs = self._hydrate_pairs(filtered_rids, include_context=include_context)
        return [
            {
                "concept": concept,
                "semanticSimilarity": round(score_by_rid[rid], 6),
                "modelId": self._semantic_index.model_id,
                "asserted": False,
            }
            for rid, concept in hydrated_pairs
        ]

    def extract_concepts_sync(
        self,
        text: str,
        *,
        limit: int = 20,
        max_ngram: int = 5,
        schemes: Iterable[str] | None = None,
        deduplicate: bool = True,
        scheme_weights: Mapping[str, float] | None = DEFAULT_CURATED_SCHEME_WEIGHTS,
        max_unigram_doc_freq: int | None = DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ,
    ) -> list[dict[str, Any]]:
        """Zero-ML verbatim concept extraction from text via sliding 1..N-gram lookup on ``label_exact``.

        Rejects punctuation-crossing spans (``,``, ``;``, ``.``, ``:``, ``(``, ``)``,
        ``[``, ``]``, ``\\n``), requires exact uppercase matching for short (``<= 4``-char)
        all-caps acronyms in the vocabulary, suppresses common function words and
        high-DF unigrams by default, and batches ``matchedLabelId`` hydration into 1 SQL query.
        """

        if not isinstance(text, str) or len(text) > _EXTRACT_TEXT_LIMIT:
            raise VocabularyInputError(
                "invalid_text", f"text must be a string of at most {_EXTRACT_TEXT_LIMIT} characters"
            )
        limit = _normalize_limit(limit, maximum=_MAX_LOOKUP_LIMIT, name="limit")
        max_ngram = _normalize_limit(max_ngram, maximum=8, name="max_ngram")
        if max_unigram_doc_freq is not None and (
            isinstance(max_unigram_doc_freq, bool)
            or not isinstance(max_unigram_doc_freq, int)
            or max_unigram_doc_freq < 1
        ):
            raise VocabularyInputError(
                "invalid_limit",
                "max_unigram_doc_freq must be a positive integer",
            )
        if scheme_weights is not None and not isinstance(scheme_weights, Mapping):
            raise VocabularyInputError(
                "invalid_scheme_weights",
                "scheme_weights must be a mapping or None",
            )
        use_weights = bool(scheme_weights)
        validated_weights: dict[str, float] = {}
        if scheme_weights:
            for k, v in scheme_weights.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                    raise VocabularyInputError(
                        "invalid_scheme_weights",
                        f"scheme weight for {k!r} must be a finite number",
                    )
                validated_weights[str(k)] = float(v)

        if not text.strip():
            return []

        allowed_sids: set[int] | None = None
        if schemes is not None:
            req_schemes = _normalize_schemes(schemes)
            allowed_sids = {self._sid_by_scheme[s] for s in req_schemes if s in self._sid_by_scheme}
            if not allowed_sids:
                return []

        tok_matches = list(_TOKEN_RE.finditer(text))
        if not tok_matches:
            return []

        # Generate candidate 1..max_ngram windows that do NOT cross sentence/clause punctuation.
        # tuple: (tok_start, tok_end, char_start, char_end, norm_phrase, raw_surface)
        windows: list[tuple[int, int, int, int, str, str]] = []
        unique_phrases: set[str] = set()
        legacy_raw_to_norm: dict[str, str] = {}
        n_toks = len(tok_matches)
        for i in range(n_toks):
            max_j = min(n_toks, i + max_ngram)
            for j in range(i + 1, max_j + 1):
                if j > i + 1:
                    gap = text[tok_matches[j - 2].end() : tok_matches[j - 1].start()]
                    if _SPAN_BREAK_RE.search(gap) is not None:
                        break
                c_start = tok_matches[i].start()
                c_end = tok_matches[j - 1].end()
                raw_surface = text[c_start:c_end]
                if _SPAN_BREAK_RE.search(raw_surface) is not None:
                    break
                raw_stripped = raw_surface.strip()
                if j == i + 1 and len(raw_stripped) < 3:
                    continue
                if len(raw_stripped) > _QUERY_LIMIT:
                    continue
                norm = " ".join(normalize_text(raw_stripped).split())
                if not norm:
                    continue
                if j == i + 1 and norm in _COMMON_FUNCTION_WORDS and not _is_short_acronym_label(raw_stripped):
                    continue
                windows.append((i, j, c_start, c_end, norm, raw_stripped))
                unique_phrases.add(norm)
                if self.schema_version == "2":
                    raw_low = " ".join(raw_stripped.lower().split())
                    if raw_low != norm:
                        unique_phrases.add(raw_low)
                        legacy_raw_to_norm[raw_low] = norm

        self._pool.check_open()
        if not unique_phrases:
            return []

        weight_by_sid: dict[int, float] = (
            {sid: validated_weights.get(uri, 0.0) for sid, uri in self._scheme_by_sid.items()}
            if use_weights
            else {}
        )

        # Batch-query label_exact in chunks staying safely below SQLite's 999 parameter limit.
        # Keep the single best candidate for >4-char phrases, and all candidates for <=4-char phrases
        # so short all-caps acronym case checks can disambiguate cleanly before span selection.
        phrase_to_best: dict[str, tuple[int, float, int]] = {}  # norm -> (role_rank, -weight, rid)
        short_candidates: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
        seen_short_pair: set[tuple[str, int]] = set()
        phrase_list = list(unique_phrases)
        phrase_chunk = max(1, min(400, 900 - (len(allowed_sids) if allowed_sids is not None else 0)))

        def _record_cand(val_lower: str, role_rank: int, neg_weight: float, rid: int) -> None:
            canon = legacy_raw_to_norm.get(val_lower, val_lower)
            cand_key = (role_rank, neg_weight, rid)
            if len(canon) <= 4:
                pair = (canon, rid)
                if pair not in seen_short_pair:
                    seen_short_pair.add(pair)
                    short_candidates[canon].append(cand_key)
                else:
                    # Keep best role/weight tuple if duplicate rid matched in v2 fallback.
                    cands = short_candidates[canon]
                    for idx, prev in enumerate(cands):
                        if prev[2] == rid and cand_key < prev:
                            cands[idx] = cand_key
                            break
            else:
                prev = phrase_to_best.get(canon)
                if prev is None or cand_key < prev:
                    phrase_to_best[canon] = cand_key

        with self._pool.borrow() as con:
            for start in range(0, len(phrase_list), phrase_chunk):
                chunk = phrase_list[start : start + phrase_chunk]
                ph = ",".join("?" for _ in chunk)
                if allowed_sids is not None:
                    s_ph = ",".join("?" for _ in allowed_sids)
                    sql = f"""
                        SELECT le.value_lower, le.role_rank, le.rid, r.sid
                        FROM label_exact le
                        JOIN resources r ON r.rid = le.rid
                        WHERE le.value_lower IN ({ph}) AND r.sid IN ({s_ph})
                        ORDER BY le.value_lower, le.role_rank, le.rid
                    """
                    params: list[Any] = [*chunk, *sorted(allowed_sids)]
                    for val_lower, role_rank, rid, sid in con.execute(sql, params):
                        _record_cand(
                            str(val_lower),
                            int(role_rank),
                            -weight_by_sid.get(int(sid), 0.0) if use_weights else 0.0,
                            int(rid),
                        )
                elif use_weights:
                    sql = f"""
                        SELECT le.value_lower, le.role_rank, le.rid, r.sid
                        FROM label_exact le
                        JOIN resources r ON r.rid = le.rid
                        WHERE le.value_lower IN ({ph})
                        ORDER BY le.value_lower, le.role_rank, le.rid
                    """
                    for val_lower, role_rank, rid, sid in con.execute(sql, chunk):
                        _record_cand(str(val_lower), int(role_rank), -weight_by_sid.get(int(sid), 0.0), int(rid))
                else:
                    sql = f"""
                        SELECT value_lower, role_rank, rid
                        FROM label_exact
                        WHERE value_lower IN ({ph})
                        ORDER BY value_lower, role_rank, rid
                    """
                    for val_lower, role_rank, rid in con.execute(sql, chunk):
                        _record_cand(str(val_lower), int(role_rank), 0.0, int(rid))

            if not phrase_to_best and not short_candidates:
                return []

            # Inspect actual label casing for matched short (<=4-char) candidates in batched SQL so
            # vocabulary-only all-caps acronyms ("FOR", "EPA", "WHO") require exact uppercase match!
            short_non_acronym_ok: set[tuple[str, int]] = set()
            short_exact_acronyms: dict[tuple[str, int], set[str]] = defaultdict(set)
            if short_candidates:
                for cands in short_candidates.values():
                    cands.sort()
                short_rids = sorted({cand[2] for cands in short_candidates.values() for cand in cands})
                short_vals_set = set(short_candidates)
                if self.schema_version == "2":
                    for raw_low, canon in legacy_raw_to_norm.items():
                        if canon in short_candidates:
                            short_vals_set.add(raw_low)
                short_vals = sorted(short_vals_set)
                val_chunk_size = max(1, min(300, 900 - min(len(short_rids), 450)))
                for r_start in range(0, len(short_rids), 450):
                    r_chunk = short_rids[r_start : r_start + 450]
                    r_ph = ",".join("?" for _ in r_chunk)
                    for v_start in range(0, len(short_vals), val_chunk_size):
                        v_chunk = short_vals[v_start : v_start + val_chunk_size]
                        v_ph = ",".join("?" for _ in v_chunk)
                        for rid, val_lower, raw_val in con.execute(
                            f"SELECT rid, value_lower, value FROM labels WHERE rid IN ({r_ph}) AND value_lower IN ({v_ph})",
                            [*r_chunk, *v_chunk],
                        ):
                            canon = legacy_raw_to_norm.get(str(val_lower), str(val_lower))
                            key = (canon, int(rid))
                            stripped_val = str(raw_val).strip()
                            if _is_short_acronym_label(stripped_val):
                                short_exact_acronyms[key].add(stripped_val)
                            else:
                                short_non_acronym_ok.add(key)

            def _best_for_window(norm: str, raw_stripped: str) -> tuple[int, float, int] | None:
                if len(norm) > 4:
                    return phrase_to_best.get(norm)
                cands = short_candidates.get(norm)
                if not cands:
                    return None
                for cand in cands:
                    key = (norm, cand[2])
                    if key in short_non_acronym_ok or raw_stripped in short_exact_acronyms.get(key, ()):
                        return cand
                return None

            # Generic single-word guard: suppress high-DF unigrams via vocab_terms.doc_freq
            # while NEVER suppressing multi-word phrases (e.g. "Flood insurance", "computer crime").
            suppressed_unigrams: set[str] = set()
            if max_unigram_doc_freq is not None:
                matched_unigrams = sorted(
                    {
                        w[4]
                        for w in windows
                        if w[1] == w[0] + 1 and (w[4] in phrase_to_best or w[4] in short_candidates)
                    }
                )
                for start in range(0, len(matched_unigrams), 400):
                    chunk = matched_unigrams[start : start + 400]
                    ph = ",".join("?" for _ in chunk)
                    for term, doc_freq in con.execute(
                        f"SELECT term, doc_freq FROM vocab_terms WHERE term IN ({ph})",
                        chunk,
                    ):
                        if int(doc_freq) > max_unigram_doc_freq:
                            suppressed_unigrams.add(str(term))

            # Resolve per-window best match and run greedy longest non-overlapping span selection.
            matched_windows: list[tuple[int, int, int, int, str, str, int, int]] = []
            for t_start, t_end, c_start, c_end, norm, raw_stripped in windows:
                if t_end == t_start + 1 and norm in suppressed_unigrams:
                    continue
                best = _best_for_window(norm, raw_stripped)
                if best is None:
                    continue
                role_rank, _neg_weight, rid = best
                matched_windows.append((t_start, t_end, c_start, c_end, norm, raw_stripped, rid, role_rank))

            if not matched_windows:
                return []
            matched_windows.sort(key=lambda w: (-(w[1] - w[0]), w[2]))

            occupied_toks: set[int] = set()
            chosen: list[tuple[int, int, str, str, int, int]] = []  # (c_start, c_end, norm, raw_surface, rid, role_rank)
            seen_rids: set[int] = set()
            for t_start, t_end, c_start, c_end, norm, raw_stripped, rid, role_rank in matched_windows:
                if any(t in occupied_toks for t in range(t_start, t_end)):
                    continue
                if deduplicate and rid in seen_rids:
                    # Occupy the repeated longer phrase tokens so shorter sub-spans aren't spuriously extracted inside it.
                    occupied_toks.update(range(t_start, t_end))
                    continue
                occupied_toks.update(range(t_start, t_end))
                seen_rids.add(rid)
                chosen.append((c_start, c_end, norm, raw_stripped, rid, role_rank))
                if len(chosen) >= limit:
                    break

            if not chosen:
                return []

            # Return mentions in natural document reading order.
            chosen.sort(key=lambda item: item[0])
            chosen_rids = list(dict.fromkeys(item[4] for item in chosen))
            by_rid = dict(self._hydrate_pairs(chosen_rids, con=con))

            # Batch matchedLabelId hydration into ONE SQL IN (...) query (len(chosen) <= 50 -> <=100 params!).
            lookup_norms_set = {item[2] for item in chosen}
            if self.schema_version == "2":
                for raw_low, canon in legacy_raw_to_norm.items():
                    if canon in lookup_norms_set:
                        lookup_norms_set.add(raw_low)
            lookup_norms = list(lookup_norms_set)
            r_ph = ",".join("?" for _ in chosen_rids)
            n_ph = ",".join("?" for _ in lookup_norms)
            exact_surface_lbl: dict[tuple[int, str, str], tuple[str, str]] = {}
            default_lbl: dict[tuple[int, str], tuple[str, str]] = {}
            for rid, val_lower, raw_val, lbl_pfx, lbl_suf, role in con.execute(
                f"""
                SELECT rid, value_lower, value, lbl_pfx, lbl_suffix, role
                FROM labels
                WHERE rid IN ({r_ph}) AND value_lower IN ({n_ph})
                ORDER BY rid, value_lower, role_rank, value, lbl_pfx, lbl_suffix
                """,
                [*chosen_rids, *lookup_norms],
            ):
                canon = legacy_raw_to_norm.get(str(val_lower), str(val_lower))
                expanded = self._expand_uri(int(lbl_pfx), str(lbl_suf))
                role_s = str(role)
                r_int = int(rid)
                default_lbl.setdefault((r_int, canon), (expanded, role_s))
                exact_surface_lbl.setdefault((r_int, canon, str(raw_val).strip()), (expanded, role_s))

        results: list[dict[str, Any]] = []
        for c_start, c_end, norm, raw_stripped, rid, role_rank in chosen:
            concept = by_rid.get(rid)
            if concept is None:
                continue
            lbl_hit = exact_surface_lbl.get((rid, norm, raw_stripped)) or default_lbl.get((rid, norm))
            if lbl_hit is not None:
                matched_label_id, match_role = lbl_hit
            else:
                matched_label_id = concept["labels"][0]["id"]
                match_role = "preferred" if role_rank == 0 else ("alternate" if role_rank == 1 else "hidden")
            results.append(
                {
                    "span": [c_start, c_end],
                    "matchedText": text[c_start:c_end],
                    "matchedLabelId": matched_label_id,
                    "matchRole": match_role,
                    "concept": concept,
                }
            )
        return results

    def expand_sync(
        self,
        reference: Mapping[str, Any],
        *,
        predicates: Iterable[str] | None = None,
        max_depth: int = 3,
        max_nodes: int = 128,
        include_mappings: bool | None = None,
        include_symmetric_inverse: bool | None = None,
        include_derived: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Return a bounded, cycle-safe k-hop closure starting from ``reference`` (BFS by min depth)."""

        max_depth = _normalize_limit(max_depth, maximum=8, name="max_depth")
        max_nodes = _normalize_limit(max_nodes, maximum=1024, name="max_nodes")

        rp = self._relation_policy
        use_mappings = rp.include_mappings if include_mappings is None else include_mappings
        use_sym_inv = rp.include_symmetric_inverse if include_symmetric_inverse is None else include_symmetric_inverse
        use_derived = rp.include_derived if include_derived is None else include_derived

        pred_filter: set[str] | None = None
        if predicates is not None:
            if isinstance(predicates, (str, bytes)):
                raise VocabularyInputError("invalid_predicates", "predicates must be a sequence of URIs")
            pred_filter = {str(p) for p in predicates}
            if not pred_filter:
                raise VocabularyInputError("invalid_predicates", "predicates cannot be empty")

        allowed_kinds = [_STMT_KIND_NATIVE]
        if use_mappings:
            allowed_kinds.append(_STMT_KIND_MAPPING)
        if use_derived:
            allowed_kinds.append(_STMT_KIND_DERIVED)

        allowed_pids = [
            pid
            for pid, (uri, _st, _sym) in self._pred_by_pid.items()
            if pred_filter is None or uri in pred_filter
        ]

        kinds_ph = ",".join("?" for _ in allowed_kinds)
        pids_ph = ",".join("?" for _ in allowed_pids)
        def_only_flag = 1 if rp.default_mappings_only else 0

        with self._pool.borrow() as con:
            _ref, seed_rid = self._resolve_seed_rid(reference, con=con)
            if not allowed_pids:
                return []

            visited: set[int] = {seed_rid}
            frontier: list[int] = [seed_rid]
            discovered: list[tuple[int, int, str, str]] = []

            for depth in range(1, max_depth + 1):
                if not frontier or len(discovered) >= max_nodes:
                    break
                next_frontier: list[int] = []
                for start in range(0, len(frontier), 200):
                    batch = frontier[start : start + 200]
                    src_ph = ",".join("?" for _ in batch)
                    params: list[Any] = [*batch, *allowed_kinds, *allowed_pids, def_only_flag]
                    rows = con.execute(
                        f"""
                        SELECT dst_rid, pid, stmt_pfx, stmt_suffix
                        FROM edges
                        WHERE src_rid IN ({src_ph})
                          AND stmt_kind IN ({kinds_ph})
                          AND pid IN ({pids_ph})
                          AND (stmt_kind != {_STMT_KIND_MAPPING} OR ref035_default = 1 OR ? = 0)
                        ORDER BY src_rid, stmt_kind, pid, stmt_pfx, stmt_suffix, dst_rid
                        """,
                        params,
                    ).fetchall()
                    if use_mappings and use_sym_inv:
                        rev_rows = con.execute(
                            f"""
                            SELECT src_rid, pid, stmt_pfx, stmt_suffix
                            FROM edges_rev
                            WHERE dst_rid IN ({src_ph})
                              AND pid IN ({pids_ph})
                              AND (ref035_default = 1 OR ? = 0)
                            ORDER BY dst_rid, pid, stmt_pfx, stmt_suffix, src_rid
                            """,
                            [*batch, *allowed_pids, def_only_flag],
                        ).fetchall()
                        rows.extend(rev_rows)
                    for dst_rid, pid, stmt_pfx, stmt_suf in rows:
                        d_int = int(dst_rid)
                        if d_int in visited:
                            continue
                        visited.add(d_int)
                        pred_uri = self._pred_by_pid[int(pid)][0]
                        stmt_id = self._expand_uri(int(stmt_pfx), stmt_suf)
                        discovered.append((d_int, depth, pred_uri, stmt_id))
                        next_frontier.append(d_int)
                        if len(discovered) >= max_nodes:
                            break
                    if len(discovered) >= max_nodes:
                        break
                frontier = next_frontier

            if not discovered:
                return []
            by_rid = dict(self._hydrate_pairs([item[0] for item in discovered], con=con))
        return [
            {
                "concept": by_rid[rid],
                "depth": depth,
                "viaPredicate": via_pred,
                "viaStatementId": via_stmt,
            }
            for rid, depth, via_pred, via_stmt in discovered
            if rid in by_rid
        ]

    def agency_change_events_sync(
        self,
        *,
        applies_to: str | None = None,
        event_kind: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Read lifecycle / agency succession change events stored in the pack (empty on legacy packs)."""

        bounded_limit = _normalize_limit(limit, maximum=10_000, name="limit")
        clauses: list[str] = []
        params: list[Any] = []
        if applies_to is not None:
            if not isinstance(applies_to, str) or not applies_to.strip():
                raise VocabularyInputError("invalid_filter", "applies_to must be a non-empty URI string")
            clauses.append("applies_to = ?")
            params.append(applies_to.strip())
        if event_kind is not None:
            if not isinstance(event_kind, str) or not event_kind.strip():
                raise VocabularyInputError("invalid_filter", "event_kind must be a non-empty URI string")
            clauses.append("event_kind = ?")
            params.append(event_kind.strip())
        self._pool.check_open()
        if not self._has_agency_change_events:
            return []

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(bounded_limit)
        with self._pool.borrow() as con:
            rows = con.execute(
                f"""
                SELECT event_id, applies_to, event_kind, effective_date,
                       source_records_json, from_release, to_release
                FROM agency_change_events
                {where_sql}
                ORDER BY effective_date, event_id
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(event_id),
                "appliesTo": str(target),
                "eventKind": str(kind),
                "effectiveDate": str(eff_date),
                "sourceRecords": json.loads(str(src_json)),
                "fromRelease": from_rel,
                "toRelease": to_rel,
            }
            for event_id, target, kind, eff_date, src_json, from_rel, to_rel in rows
        ]

    def agency_projections_sync(
        self,
        *,
        source_value_kind: str | None = None,
        source_value: str | None = None,
        org: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Read REF-038 agency identity projections stored in the pack (empty on legacy packs)."""

        bounded_limit = _normalize_limit(limit, maximum=10_000, name="limit")
        clauses: list[str] = []
        params: list[Any] = []
        for col, raw, label in (
            ("source_value_kind", source_value_kind, "source_value_kind"),
            ("source_value", source_value, "source_value"),
            ("org", org, "org"),
        ):
            if raw is not None:
                if not isinstance(raw, str) or not raw.strip():
                    raise VocabularyInputError("invalid_filter", f"{label} must be a non-empty string")
                clauses.append(f"{col} = ?")
                params.append(raw.strip())
        self._pool.check_open()
        if not self._has_agency_projections:
            return []

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(bounded_limit)
        with self._pool.borrow() as con:
            rows = con.execute(
                f"""
                SELECT source_value_kind, source_value, org, pref_label,
                       abbreviations_json, aliases_json, parent_org, relation,
                       evidence_tier, warrant, basis, evidence_record_count
                FROM agency_projections
                {where_sql}
                ORDER BY source_value_kind, source_value, org
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "sourceValueKind": str(sv_kind),
                "sourceValue": str(sv_val),
                "org": str(org_iri),
                "prefLabel": str(pref_lbl),
                "abbreviations": json.loads(str(abbrs_json)),
                "aliases": json.loads(str(aliases_json)),
                "parentOrg": parent_org,
                "relation": str(relation),
                "evidenceTier": str(ev_tier),
                "warrant": str(warrant),
                "basis": str(basis),
                "evidenceRecordCount": int(ev_count),
            }
            for (
                sv_kind,
                sv_val,
                org_iri,
                pref_lbl,
                abbrs_json,
                aliases_json,
                parent_org,
                relation,
                ev_tier,
                warrant,
                basis,
                ev_count,
            ) in rows
        ]

    async def agency_change_events(
        self,
        run: Any = None,
        *,
        applies_to: str | None = None,
        event_kind: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        _ = run
        return self.agency_change_events_sync(
            applies_to=applies_to,
            event_kind=event_kind,
            limit=limit,
        )

    async def agency_projections(
        self,
        run: Any = None,
        *,
        source_value_kind: str | None = None,
        source_value: str | None = None,
        org: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        _ = run
        return self.agency_projections_sync(
            source_value_kind=source_value_kind,
            source_value=source_value,
            org=org,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Async VocabularyProvider & GraphExpander Compatibility (zero SQL executor required)
    # ------------------------------------------------------------------

    async def lookup(
        self,
        run: Any = None,
        query: str = "",
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        query_vector: Sequence[float] | None = None,
        group_identical_labels: bool | None = None,
        include_context: bool | None = None,
        min_cosine: float | None = None,
        nprobe: int | None = None,
    ) -> list[dict[str, Any]]:
        _ = run
        return self.lookup_sync(
            query,
            limit,
            schemes=schemes,
            query_vector=query_vector,
            group_identical_labels=group_identical_labels,
            include_context=include_context,
            min_cosine=min_cosine,
            nprobe=nprobe,
        )

    async def resolve(
        self,
        run: Any = None,
        reference: Mapping[str, Any] | None = None,
        *,
        include_context: bool = False,
    ) -> dict[str, Any]:
        _ = run
        if reference is None:
            raise VocabularyInputError("invalid_reference", "concept reference is required")
        return self.resolve_sync(reference, include_context=include_context)

    async def related(
        self,
        run: Any = None,
        reference: Mapping[str, Any] | None = None,
        limit: int = 20,
        *,
        include_mappings: bool | None = None,
        default_mappings_only: bool | None = None,
        include_symmetric_inverse: bool | None = None,
        include_derived: bool | None = None,
    ) -> list[dict[str, Any]]:
        _ = run
        if reference is None:
            raise VocabularyInputError("invalid_reference", "concept reference is required")
        return self.related_sync(
            reference,
            limit,
            include_mappings=include_mappings,
            default_mappings_only=default_mappings_only,
            include_symmetric_inverse=include_symmetric_inverse,
            include_derived=include_derived,
        )

    async def similar(
        self,
        run: Any = None,
        reference: Mapping[str, Any] | None = None,
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        min_cosine: float | None = None,
        exclude_same_scheme: bool = False,
        nprobe: int | None = None,
        include_context: bool = False,
    ) -> list[dict[str, Any]]:
        _ = run
        if reference is None:
            raise VocabularyInputError("invalid_reference", "concept reference is required")
        return self.similar_sync(
            reference,
            limit,
            schemes=schemes,
            min_cosine=min_cosine,
            exclude_same_scheme=exclude_same_scheme,
            nprobe=nprobe,
            include_context=include_context,
        )

    async def extract_concepts(
        self,
        run: Any = None,
        text: str = "",
        *,
        limit: int = 20,
        max_ngram: int = 5,
        schemes: Iterable[str] | None = None,
        deduplicate: bool = True,
        scheme_weights: Mapping[str, float] | None = DEFAULT_CURATED_SCHEME_WEIGHTS,
        max_unigram_doc_freq: int | None = DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ,
    ) -> list[dict[str, Any]]:
        _ = run
        return self.extract_concepts_sync(
            text,
            limit=limit,
            max_ngram=max_ngram,
            schemes=schemes,
            deduplicate=deduplicate,
            scheme_weights=scheme_weights,
            max_unigram_doc_freq=max_unigram_doc_freq,
        )

    async def expand(
        self,
        run: Any = None,
        reference: Mapping[str, Any] | None = None,
        *,
        predicates: Iterable[str] | None = None,
        max_depth: int = 3,
        max_nodes: int = 128,
        include_mappings: bool | None = None,
        include_symmetric_inverse: bool | None = None,
        include_derived: bool | None = None,
    ) -> list[dict[str, Any]]:
        _ = run
        if reference is None:
            raise VocabularyInputError("invalid_reference", "concept reference is required")
        return self.expand_sync(
            reference,
            predicates=predicates,
            max_depth=max_depth,
            max_nodes=max_nodes,
            include_mappings=include_mappings,
            include_symmetric_inverse=include_symmetric_inverse,
            include_derived=include_derived,
        )


class PriorGuidedSemanticIndex:
    """Portable stdlib DI wrapper applying neutral structural (plus optional scheme) priors at Stage-1.

    Loads precomputed ``structural_prior_f32`` and ``sid_by_rid_u16`` blobs from
    v3 packs in ``<2 ms`` without scanning ``resources``, strictly verifies
    cross-pack identity (``pack_id`` and ``source_manifest_digest``), forwards
    ``allowed_rids`` and ``rerank_top_r`` when supported by ``inner``, and
    preserves uncorrupted raw cosine scores in returned ``(rid, cosine)`` tuples.
    """

    def __init__(
        self,
        inner: SemanticIndex,
        priors_by_rid: array,
        *,
        sid_by_rid: array | None = None,
        scheme_bonus_by_sid: Mapping[int, float] | None = None,
        oversample_factor: int = 4,
        min_oversample: int = 512,
        owns_inner: bool = False,
    ) -> None:
        if isinstance(oversample_factor, bool) or not isinstance(oversample_factor, int) or oversample_factor < 1:
            raise VocabularyInputError("invalid_oversample", "oversample_factor must be a positive integer")
        if isinstance(min_oversample, bool) or not isinstance(min_oversample, int) or min_oversample < 1:
            raise VocabularyInputError("invalid_oversample", "min_oversample must be a positive integer")
        self._inner = inner
        self._inner_caps = _inspect_search_rids_capabilities(inner)
        self._priors = priors_by_rid
        self._sid_by_rid = sid_by_rid
        self._scheme_bonus_by_sid: dict[int, float] = (
            {int(k): float(v) for k, v in scheme_bonus_by_sid.items() if float(v) != 0.0}
            if scheme_bonus_by_sid
            else {}
        )
        self._oversample_factor = oversample_factor
        self._min_oversample = min_oversample
        self._owns_inner = bool(owns_inner)

    @classmethod
    def from_pack(
        cls,
        pack_path: Path | str,
        inner: SemanticIndex,
        *,
        scheme_weights: Mapping[str, float] | None = DEFAULT_CURATED_SCHEME_WEIGHTS,
        scheme_weight_scale: float = 0.5,
        subdivision_penalty: float = DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY,
        long_label_penalty: float = DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY,
        long_label_chars: int = DEFAULT_STRUCTURAL_LONG_LABEL_CHARS,
        oversample_factor: int = 4,
        min_oversample: int = 512,
        owns_inner: bool = False,
    ) -> PriorGuidedSemanticIndex:
        """Load per-``rid`` static priors directly from a compiled pack with strict cross-pack verification."""

        for name, val in (
            ("scheme_weight_scale", scheme_weight_scale),
            ("subdivision_penalty", subdivision_penalty),
            ("long_label_penalty", long_label_penalty),
        ):
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
                raise VocabularyInputError("invalid_prior", f"{name} must be a finite number")
        if isinstance(long_label_chars, bool) or not isinstance(long_label_chars, int) or long_label_chars < 1:
            raise VocabularyInputError("invalid_prior", "long_label_chars must be a positive integer")
        if scheme_weights is not None and not isinstance(scheme_weights, Mapping):
            raise VocabularyInputError("invalid_scheme_weights", "scheme_weights must be a mapping or None")
        validated_weights: dict[str, float] = {}
        if scheme_weights:
            for k, v in scheme_weights.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                    raise VocabularyInputError(
                        "invalid_scheme_weights", f"scheme weight for {k!r} must be a finite number"
                    )
                validated_weights[str(k)] = float(v)

        raw_path = Path(pack_path)
        _reject_symlink_path(raw_path, error_code="invalid_pack", label="vocabulary pack path")
        try:
            resolved = raw_path.resolve(strict=True)
        except OSError as exc:
            raise VocabularyPackError("missing_pack", f"vocabulary pack not found: {pack_path}") from exc
        if not resolved.is_file():
            raise VocabularyPackError("invalid_pack", f"vocabulary pack is not a regular file: {resolved}")

        uri = f"file:{quote(str(resolved))}?mode=ro&immutable=1"
        try:
            con = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise VocabularyPackError("corrupt_pack", f"failed to open vocabulary pack: {exc}") from exc

        try:
            meta = dict(con.execute("SELECT key, value FROM pack_meta").fetchall())
            if (
                meta.get("record_type") != PACK_RECORD_TYPE
                or meta.get("schema_version") not in SUPPORTED_PACK_SCHEMA_VERSIONS
            ):
                raise VocabularyPackError(
                    "unsupported_schema",
                    f"expected {PACK_RECORD_TYPE} schema version in {sorted(SUPPORTED_PACK_SCHEMA_VERSIONS)}",
                )
            pack_id = str(meta.get("pack_id", "")).strip()
            source_manifest_digest = str(meta.get("source_manifest_digest", "")).strip()
            if not pack_id or not source_manifest_digest:
                raise VocabularyPackError("corrupt_pack", "vocabulary pack metadata is incomplete")

            # Strict cross-pack identity binding (prevents silently pairing priors from pack A with sidecar B!).
            inner_manifest = getattr(inner, "source_manifest_digest", "")
            if inner_manifest != source_manifest_digest:
                raise VocabularyPackError(
                    "pack_mismatch",
                    "semantic index source manifest digest does not match vocabulary pack",
                )
            inner_pack_id = getattr(inner, "pack_id", "")
            if inner_pack_id:
                if inner_pack_id != pack_id:
                    raise VocabularyPackError(
                        "pack_mismatch",
                        "semantic index pack identity does not match vocabulary pack",
                    )
            elif inner.pack_sha256 != _sha256_file(resolved):
                raise VocabularyPackError(
                    "pack_mismatch",
                    "semantic index pack digest does not match vocabulary pack",
                )

            row = con.execute("SELECT max(rid) FROM resources").fetchone()
            max_rid = int(row[0]) if row and row[0] is not None else 0
            scheme_by_sid = dict(con.execute("SELECT sid, uri FROM schemes").fetchall())
            scale_f = float(scheme_weight_scale)
            scheme_bonus_by_sid: dict[int, float] = {
                int(sid): validated_weights[uri] * scale_f
                for sid, uri in scheme_by_sid.items()
                if uri in validated_weights and validated_weights[uri] * scale_f != 0.0
            }

            uses_default_structural = (
                math.isclose(float(subdivision_penalty), DEFAULT_STRUCTURAL_SUBDIVISION_PENALTY, rel_tol=0.0, abs_tol=1e-9)
                and math.isclose(float(long_label_penalty), DEFAULT_STRUCTURAL_LONG_LABEL_PENALTY, rel_tol=0.0, abs_tol=1e-9)
                and long_label_chars == DEFAULT_STRUCTURAL_LONG_LABEL_CHARS
            )

            priors_blob = _read_meta_blob(con, "structural_prior_f32") if uses_default_structural else None
            sid_blob = _read_meta_blob(con, "sid_by_rid_u16") if scheme_bonus_by_sid else None

            sid_by_rid_arr: array | None = None
            if sid_blob is not None:
                expected_sid_bytes = (max_rid + 1) * 2
                if len(sid_blob) != expected_sid_bytes:
                    raise VocabularyPackError(
                        "corrupt_pack",
                        f"sid_by_rid_u16 blob length {len(sid_blob)} != expected {expected_sid_bytes}",
                    )
                sid_by_rid_arr = _from_little_endian_array("H", sid_blob)

            if priors_blob is not None and (not scheme_bonus_by_sid or sid_by_rid_arr is not None):
                expected_prior_bytes = (max_rid + 1) * 4
                if len(priors_blob) != expected_prior_bytes:
                    raise VocabularyPackError(
                        "corrupt_pack",
                        f"structural_prior_f32 blob length {len(priors_blob)} != expected {expected_prior_bytes}",
                    )
                priors = _from_little_endian_array("f", priors_blob)
            else:
                # Legacy v2 pack fallback or caller-customized structural penalty parameters.
                priors = array("f", [0.0]) * (max_rid + 1)
                if max_rid > 0:
                    subdiv_f = float(subdivision_penalty)
                    long_f = float(long_label_penalty)
                    for rid, sid, pref in con.execute(
                        "SELECT rid, sid, pref_label FROM resources WHERE pref_label IS NOT NULL"
                    ):
                        r_int = int(rid)
                        if 0 <= r_int <= max_rid:
                            p = scheme_bonus_by_sid.get(int(sid), 0.0)
                            depth = pref.count("--")
                            if depth > 0:
                                p -= subdiv_f * depth
                            if len(pref) > long_label_chars:
                                p -= long_f
                            priors[r_int] = p
                # Scheme bonuses are already baked into priors in fallback scan mode.
                scheme_bonus_by_sid = {}
                sid_by_rid_arr = None
        except VocabularyPackError:
            raise
        except sqlite3.Error as exc:
            raise VocabularyPackError("corrupt_pack", f"failed to read pack priors: {exc}") from exc
        finally:
            con.close()

        return cls(
            inner,
            priors,
            sid_by_rid=sid_by_rid_arr,
            scheme_bonus_by_sid=scheme_bonus_by_sid,
            oversample_factor=oversample_factor,
            min_oversample=min_oversample,
            owns_inner=owns_inner,
        )

    @property
    def pack_sha256(self) -> str:
        return self._inner.pack_sha256

    @property
    def pack_id(self) -> str:
        return getattr(self._inner, "pack_id", "")

    @property
    def source_manifest_digest(self) -> str:
        return self._inner.source_manifest_digest

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    @property
    def recommended_min_cosine(self) -> float | None:
        return getattr(self._inner, "recommended_min_cosine", None)

    def vector_for_rid(self, rid: int) -> Any | None:
        return self._inner.vector_for_rid(rid)

    def search_rids(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int = 40,
        min_cosine: float = DEFAULT_MIN_COSINE,
        nprobe: int = 24,
        allowed_rids: Any = None,
        rerank_top_r: int | None = None,
    ) -> list[tuple[int, float]]:
        if top_k <= 0:
            return []
        req_k = max(top_k * self._oversample_factor, self._min_oversample)
        caps = self._inner_caps
        kwargs: dict[str, Any] = {"top_k": req_k}
        if caps.supports_min_cosine:
            kwargs["min_cosine"] = min_cosine
        if caps.supports_nprobe:
            kwargs["nprobe"] = nprobe
        if allowed_rids is not None and caps.supports_allowed_rids:
            kwargs["allowed_rids"] = allowed_rids
        if caps.supports_rerank_top_r:
            kwargs["rerank_top_r"] = max(req_k * 2, 1024) if rerank_top_r is None else int(rerank_top_r)

        raw = self._inner.search_rids(query_vector, **kwargs)
        if not raw:
            return []
        if not caps.supports_min_cosine:
            raw = [(rid, sc) for rid, sc in raw if sc >= min_cosine]
        if allowed_rids is not None and not caps.supports_allowed_rids:
            checker = _prepare_allowed_checker(allowed_rids)
            if checker is not None:
                raw = [(rid, sc) for rid, sc in raw if checker(int(rid))]
        if not raw:
            return []

        priors = self._priors
        n_priors = len(priors)
        sid_by_rid = self._sid_by_rid
        bonus_by_sid = self._scheme_bonus_by_sid
        if sid_by_rid is not None and bonus_by_sid:
            n_sids = len(sid_by_rid)
            scored = [
                (
                    float(sc)
                    + (priors[rid] if 0 <= rid < n_priors else 0.0)
                    + (bonus_by_sid.get(sid_by_rid[rid], 0.0) if 0 <= rid < n_sids else 0.0),
                    int(rid),
                    float(sc),
                )
                for rid, sc in raw
            ]
        else:
            scored = [
                (float(sc) + (priors[rid] if 0 <= rid < n_priors else 0.0), int(rid), float(sc))
                for rid, sc in raw
            ]
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [(rid, sc) for _, rid, sc in scored[:top_k]]

    def close(self) -> None:
        if self._owns_inner:
            close_fn = getattr(self._inner, "close", None)
            if callable(close_fn):
                close_fn()

    def __enter__(self) -> PriorGuidedSemanticIndex:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = [
    "DEFAULT_CURATED_SCHEME_WEIGHTS",
    "DERIVED_RELATION_PREDICATES",
    "MAPPING_RELATION_PREDICATES",
    "NATIVE_RELATION_PREDICATES",
    "PACK_POLICY_VERSION",
    "PACK_RECORD_TYPE",
    "PACK_SCHEMA_VERSION",
    "REGULATORY_BENCHMARK_SCHEME_PRESET",
    "SUPPORTED_PACK_SCHEMA_VERSIONS",
    "SYMMETRIC_MAPPING_PREDICATES",
    "AtlasVocabularyPack",
    "PriorGuidedSemanticIndex",
    "VocabularyInputError",
    "VocabularyPackError",
    "VocabularyPackManifest",
    "build_vocabulary_pack",
]

"""Dependency-injection protocols, immutable policies, and error classes for Atlas vocabulary serving.

This module intentionally imports ONLY the Python standard library so consumers,
test doubles, and alternative storage, vector, or Apple Silicon backends can
type-check and wire against RefSpec's vocabulary seams without pulling in
SQLite, DuckDB, PyArrow, NumPy, or platform-specific accelerators.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

#: Fallback minimum cosine similarity when neither ``LookupPolicy.min_cosine``
#: nor ``SemanticIndex.recommended_min_cosine`` specifies an abstention floor.
DEFAULT_MIN_COSINE: float = 0.55

#: Default Gaussian extreme-value multiplier ``c`` for unsupervised centered-covariance
#: OOD calibration: ``tau(N) = c * sigma_pair * sqrt(2 * ln(max(N, 64)))``.
DEFAULT_CALIBRATION_EVT_SIGMA: float = 1.5

#: Minimum effective eligible-vector floor inside extreme-value subset scaling so tiny
#: filtered schemes (``< 64`` concepts) retain a conservative abstention margin.
DEFAULT_CALIBRATION_MIN_ELIGIBLE: int = 64

#: Neutral default scheme weights (empty mapping: zero hardcoded scheme bias).
#: Consumers seeking domain-specific scheme preferences may pass explicit
#: ``scheme_weights`` (such as ``REGULATORY_BENCHMARK_SCHEME_PRESET``).
DEFAULT_CURATED_SCHEME_WEIGHTS: Mapping[str, float] = MappingProxyType({})

#: Explicit opt-in scheme weight preset for regulatory corpus benchmarks.
#: Never applied by default; pass explicitly to ``AuthorityReranker``,
#: ``PriorGuidedSemanticIndex.from_pack``, or ``extract_concepts_sync``.
REGULATORY_BENCHMARK_SCHEME_PRESET: Mapping[str, float] = MappingProxyType(
    {
        "urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025": 0.14,
        "urn:ref:atlas-resource-scheme:mesh-descriptors": 0.12,
        "urn:ref:atlas-resource-scheme:eurovoc": 0.11,
        "urn:ref:atlas-resource-scheme:gemet": 0.08,
        "urn:ref:atlas-resource-scheme:doe-osti-semantic-thesaurus-2020": 0.06,
        "urn:ref:atlas-resource-scheme:nasa-thesaurus": 0.06,
        "urn:ref:atlas-resource-scheme:icpsr-subject-thesaurus": 0.05,
        "urn:ref:atlas-resource-scheme:umthes": 0.05,
        "urn:ref:atlas-resource-scheme:lcsh-subjects": 0.02,
        "urn:ref:atlas-resource-scheme:fast-topical": 0.0,
        "urn:ref:atlas-resource-scheme:cfr-subject-index": -0.06,
    }
)

#: Default unigram document-frequency ceiling for ``extract_concepts_sync`` so
#: ubiquitous single words do not spam verbatim prose extraction. Pass ``None``
#: explicitly to disable the document-frequency cap.
DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ: int = 1000


def normalize_text(text: str) -> str:
    """Symmetric NFKC + casefold + NFKD diacritic-stripping normalization.

    Matches SQLite FTS5 ``unicode61 remove_diacritics 2`` analyzer behavior so
    ``"café"``, ``"cafe\\u0301"``, ``"CAFÉ"``, and ``"cafe"`` produce the exact
    same canonical key across ``label_exact``, ``vocab_terms``, query lookup,
    token-coverage filtering, and label grouping.
    """

    folded = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFKD", folded)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFKC", stripped)


class VocabularyInputError(ValueError):
    """Caller-side invalid query, reference, limit, or missing concept (maps to HTTP 400)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VocabularyPackError(RuntimeError):
    """Pack integrity, digest, schema, or runtime availability fault (maps to HTTP 503)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class SemanticIndex(Protocol):
    """Injectable Tier-1 dense vector retriever bound to a specific Vocabulary Pack."""

    @property
    def pack_id(self) -> str: ...

    @property
    def pack_sha256(self) -> str: ...

    @property
    def source_manifest_digest(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def recommended_min_cosine(self) -> float | None: ...

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
        """Return ``(rid, cosine_score)`` pairs sorted descending by cosine similarity.

        ``allowed_rids`` accepts ``None`` (unfiltered), a dense 0/1 byte mask
        (``bytes | bytearray | memoryview`` of length ``max_rid + 1``), or a
        ``Sequence[int]`` / ``Set[int]`` of permitted integer resource IDs.
        """
        ...

    def vector_for_rid(self, rid: int) -> Any | None:
        """Return the unit-normalized stored vector for ``rid``, or ``None`` if unindexed."""
        ...


@runtime_checkable
class QueryEncoder(Protocol):
    """Injectable query-text encoder producing L2-normalized dense query vectors."""

    @property
    def model_id(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def encode_query(self, text: str) -> Sequence[float]:
        """Encode one user query string into a vector matching ``dimensions``."""
        ...


@runtime_checkable
class RankFusionPolicy(Protocol):
    """Injectable candidate fusion strategy combining exact, lexical, and dense rankings."""

    def fuse(
        self,
        *,
        exact_rids: Sequence[int],
        lexical_rids: Sequence[int],
        dense_hits: Sequence[tuple[int, float]],
        limit: int,
    ) -> list[int]:
        """Return up to ``limit`` deduplicated resource IDs ordered best-first."""
        ...


@runtime_checkable
class CandidateReranker(Protocol):
    """Injectable post-hydration reranker over rich concept candidate dictionaries.

    Supports both portable heuristic authority rerankers (``AuthorityReranker``)
    and external cross-encoder rerankers (such as Apple Silicon Pure-ANE
    ``Laya-421M``) while keeping RefSpec free of accelerator dependencies.
    """

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[Mapping[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` re-ordered (and optionally deduplicated) concept dicts."""
        ...


@runtime_checkable
class GraphExpander(Protocol):
    """Injectable bounded k-hop graph/hierarchy closure provider.

    Enables both embedded packs (SQLite BFS) and downstream search engines
    (e.g., precomputing ``VARCHAR[]`` ancestor/descendant columns for in-walk
    filtered ANN or pushing bounded closures into SQL) to share one
    provenance-preserving traversal contract.
    """

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
    ) -> list[dict[str, Any]]: ...

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
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class AgencyHistoryProvider(Protocol):
    """Optional read contract for agency lifecycle events and REF-038 agency projections."""

    def agency_change_events_sync(
        self,
        *,
        applies_to: str | None = None,
        event_kind: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def agency_projections_sync(
        self,
        *,
        source_value_kind: str | None = None,
        source_value: str | None = None,
        org: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    async def agency_change_events(
        self,
        run: Any = None,
        *,
        applies_to: str | None = None,
        event_kind: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    async def agency_projections(
        self,
        run: Any = None,
        *,
        source_value_kind: str | None = None,
        source_value: str | None = None,
        org: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class VocabularyProvider(Protocol):
    """Engine-agnostic vocabulary read seam (sync and async) for downstream consumers."""

    requires_sql_executor: bool

    def lookup_sync(
        self,
        query: str,
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        query_vector: Sequence[float] | None = None,
        group_identical_labels: bool | None = None,
        include_context: bool | None = None,
    ) -> list[dict[str, Any]]: ...

    def resolve_sync(self, reference: Mapping[str, Any]) -> dict[str, Any]: ...

    def related_sync(
        self,
        reference: Mapping[str, Any],
        limit: int = 20,
        *,
        include_mappings: bool | None = None,
        default_mappings_only: bool | None = None,
        include_symmetric_inverse: bool | None = None,
        include_derived: bool | None = None,
    ) -> list[dict[str, Any]]: ...

    def similar_sync(
        self,
        reference: Mapping[str, Any],
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        min_cosine: float | None = None,
        exclude_same_scheme: bool = False,
    ) -> list[dict[str, Any]]: ...

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
    ) -> list[dict[str, Any]]: ...

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
    ) -> list[dict[str, Any]]: ...

    async def resolve(
        self,
        run: Any = None,
        reference: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...

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
    ) -> list[dict[str, Any]]: ...

    async def similar(
        self,
        run: Any = None,
        reference: Mapping[str, Any] | None = None,
        limit: int = 10,
        *,
        schemes: Iterable[str] | None = None,
        min_cosine: float | None = None,
        exclude_same_scheme: bool = False,
    ) -> list[dict[str, Any]]: ...

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
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class ExactPinnedRRF:
    """Default rank-fusion policy: pins Tier-0 exact matches strictly above weighted RRF.

    Pinning exact matches preserves 100% exact-control top-tier recall (preventing
    dense-only regressions on verbatim headings) while letting BM25 and dense
    candidates reinforce paraphrases, cross-lingual queries, and typos cleanly.
    """

    k: float = 60.0
    lexical_weight: float = 1.0
    dense_weight: float = 1.0
    min_cosine: float | None = None
    candidate_depth: int = 80

    def fuse(
        self,
        *,
        exact_rids: Sequence[int],
        lexical_rids: Sequence[int],
        dense_hits: Sequence[tuple[int, float]],
        limit: int,
    ) -> list[int]:
        if limit <= 0:
            return []
        unique_exact = list(dict.fromkeys(exact_rids))
        exact_set = set(unique_exact)
        rrf_scores: dict[int, float] = defaultdict(float)
        for rank, rid in enumerate(lexical_rids[: self.candidate_depth], start=1):
            rrf_scores[rid] += self.lexical_weight / (self.k + rank)
        dense_rank = 0
        dense_map: dict[int, float] = {}
        for rid, cosine in dense_hits:
            if self.min_cosine is not None and cosine < self.min_cosine:
                continue
            dense_rank += 1
            if dense_rank > self.candidate_depth:
                break
            dense_map[rid] = max(dense_map.get(rid, -math.inf), float(cosine))
            rrf_scores[rid] += self.dense_weight / (self.k + dense_rank)

        if len(unique_exact) >= limit:
            return unique_exact[:limit]

        # Preserve strict exact_rids precedence (e.g. exact_preferred strictly ahead of
        # exact_alternate regardless of dense/lexical RRF reinforcement) by separating
        # consecutive exact slots by >= 1.0 (strictly larger than any RRF contribution).
        max_abs_rrf = max((abs(v) for v in rrf_scores.values()), default=0.0)
        exact_step = max(1.0, max_abs_rrf + 1.0)
        scores: dict[int, float] = {
            rid: score for rid, score in rrf_scores.items() if rid not in exact_set
        }
        n_exact = len(unique_exact)
        for idx, rid in enumerate(unique_exact):
            scores[rid] = 1000.0 + (n_exact - idx) * exact_step
        ranked = sorted(
            scores.items(),
            key=lambda pair: (
                -pair[1],
                0 if pair[0] in dense_map else 1,
                -dense_map.get(pair[0], -math.inf),
                pair[0],
            ),
        )
        return [rid for rid, _ in ranked[:limit]]


def _copy_candidate_card(item: Mapping[str, Any]) -> dict[str, Any]:
    card = dict(item)
    existing_cp = card.get("counterparts")
    if isinstance(existing_cp, list):
        card["counterparts"] = [dict(c) if isinstance(c, Mapping) else c for c in existing_cp]
    return card


def group_by_identical_label(concepts: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Group duplicate normalized-label cards across schemes while preserving all source identities."""

    if limit <= 0 or not concepts:
        return []
    grouped: list[dict[str, Any]] = []
    by_label: dict[str, dict[str, Any]] = {}
    for item in concepts:
        key = normalize_text(str(item.get("label") or "").strip())
        existing = by_label.get(key)
        if existing is None:
            if len(grouped) >= limit:
                continue
            card = _copy_candidate_card(item)
            by_label[key] = card
            grouped.append(card)
        else:
            counterparts = existing.setdefault("counterparts", [])
            counterparts.append(
                {
                    "id": item.get("id"),
                    "scheme": item.get("scheme"),
                    "release": item.get("release"),
                    "label": item.get("label"),
                    "definition": item.get("definition"),
                    "sourceRecord": item.get("sourceRecord"),
                }
            )
    return grouped


@dataclass(frozen=True, slots=True)
class AuthorityReranker:
    """Portable DI reranker curing multi-scheme subdivision dilution on large packs.

    Promotes concise, non-subdivided headings over deep ``--`` bibliographic
    subdivision leaves (e.g. ``X -- Y -- Z``) and overly long titles using
    neutral structural priors by default (plus optional caller-supplied
    ``scheme_weights``), while strictly preserving exact-label matches at the
    top and optionally collapsing duplicate normalized labels into
    ``counterparts`` *before* truncating to ``limit``.
    """

    scheme_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_CURATED_SCHEME_WEIGHTS))
    subdivision_penalty: float = 0.22
    long_label_penalty: float = 0.12
    long_label_chars: int = 80
    deduplicate_labels: bool = True
    rank_decay: float = 0.03

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[Mapping[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or not candidates:
            return []
        q_norm = normalize_text(query.strip())
        has_semantic_candidates = any(
            (c.get("matchReason") or c.get("_matchReason")) == "semantic_hybrid" for c in candidates
        )
        is_single_token_query = len(q_norm.split()) == 1

        scored: list[tuple[bool, float, int, dict[str, Any]]] = []
        for idx, item in enumerate(candidates):
            cand = _copy_candidate_card(item)
            label = str(cand.get("label") or "")
            label_norm = normalize_text(label.strip())
            match_reason = cand.get("matchReason") or cand.get("_matchReason")
            is_single_token_hybrid_spelling = (
                match_reason == "spelling_corrected" and has_semantic_candidates and is_single_token_query
            )
            is_exact = match_reason in ("exact_preferred", "exact_alternate", "exact_hidden") or (
                not is_single_token_hybrid_spelling and bool(q_norm) and label_norm == q_norm
            )
            if not is_exact and q_norm and not is_single_token_hybrid_spelling:
                labels = cand.get("labels")
                if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)):
                    is_exact = any(
                        isinstance(lbl, Mapping) and normalize_text(str(lbl.get("text") or "").strip()) == q_norm
                        for lbl in labels
                    )

            base = 1.0 - idx * self.rank_decay
            base += float(self.scheme_weights.get(str(cand.get("scheme") or ""), 0.0))

            # Penalize bibliographic "--" subdivision leaves (e.g. "Veterans--Medical care--Accounting")
            subdiv_depth = label.count("--")
            if subdiv_depth > 0:
                base -= self.subdivision_penalty * subdiv_depth
            if len(label) > self.long_label_chars:
                base -= self.long_label_penalty
            scored.append((is_exact, base, idx, cand))

        scored.sort(key=lambda row: (-int(row[0]), -row[1], row[2]))
        ordered = [row[3] for row in scored]

        if not self.deduplicate_labels:
            return ordered[:limit]
        return group_by_identical_label(ordered, limit)


@dataclass(frozen=True, slots=True)
class LookupPolicy:
    """Immutable default lookup behavior injectable into ``AtlasVocabularyPack``."""

    group_identical_labels: bool = False
    include_context: bool = False
    enable_spelling_correction: bool = True
    enable_soft_or_fallback: bool = True
    min_cosine: float | None = None
    nprobe: int = 24
    fallback_on_encoder_error: bool = True
    label_limit: int = 32

    def __post_init__(self) -> None:
        if self.min_cosine is not None and (
            isinstance(self.min_cosine, bool)
            or not isinstance(self.min_cosine, (int, float))
            or not math.isfinite(float(self.min_cosine))
            or not -1.0 <= float(self.min_cosine) <= 1.0
        ):
            raise VocabularyInputError(
                "invalid_min_cosine",
                f"min_cosine must be a finite number in [-1.0, 1.0] or None, got {self.min_cosine!r}",
            )
        if isinstance(self.nprobe, bool) or not isinstance(self.nprobe, int) or self.nprobe < 1:
            raise VocabularyInputError(
                "invalid_nprobe",
                f"nprobe must be an integer >= 1, got {self.nprobe!r}",
            )
        if isinstance(self.label_limit, bool) or not isinstance(self.label_limit, int) or self.label_limit < 1:
            raise VocabularyInputError(
                "invalid_label_limit",
                f"label_limit must be an integer >= 1, got {self.label_limit!r}",
            )


@dataclass(frozen=True, slots=True)
class RelationPolicy:
    """Immutable default graph-traversal behavior injectable into ``AtlasVocabularyPack``."""

    include_mappings: bool = False
    default_mappings_only: bool = True
    include_symmetric_inverse: bool = True
    include_derived: bool = False


__all__ = [
    "DEFAULT_CALIBRATION_EVT_SIGMA",
    "DEFAULT_CALIBRATION_MIN_ELIGIBLE",
    "DEFAULT_CURATED_SCHEME_WEIGHTS",
    "DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ",
    "DEFAULT_MIN_COSINE",
    "REGULATORY_BENCHMARK_SCHEME_PRESET",
    "AgencyHistoryProvider",
    "AuthorityReranker",
    "CandidateReranker",
    "ExactPinnedRRF",
    "GraphExpander",
    "LookupPolicy",
    "QueryEncoder",
    "RankFusionPolicy",
    "RelationPolicy",
    "SemanticIndex",
    "VocabularyInputError",
    "VocabularyPackError",
    "VocabularyProvider",
    "group_by_identical_label",
    "normalize_text",
]

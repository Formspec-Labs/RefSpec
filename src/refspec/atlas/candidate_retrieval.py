"""Deterministic, dependency-free retrieval for cross-vocabulary candidates.

The qualification judge can classify only pairs that reach its sealed catalog.
This module therefore optimizes for inclusive discovery.  It supplies multiple
independent sparse views and graph expansion; callers union their results with
exact-label rules, dense-neighbor artifacts, and controls.

Scores are integer cosine approximations.  The implementation uses no process
hashes, floating-point comparisons, or input ordering, so the same concept
facts reproduce the same ranked pairs and evidence on every run.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import isqrt
from typing import Protocol
from urllib.parse import unquote, urlparse

from refspec.storage import canonical_json

SCORE_SCALE = 1_000_000_000
RARITY_SCALE = 1_024
TERM_FREQUENCY_CAP = 3


class ContextLike(Protocol):
    """The hierarchy fields used by the sparse views."""

    member: str
    pref_label: str
    alt_labels: tuple[str, ...]
    definition: str | None
    scope_note: str | None


class ConceptLike(ContextLike, Protocol):
    """The qualification concept surface consumed by this module."""

    broader: tuple[str, ...]
    parents: tuple[ContextLike, ...]
    children: tuple[ContextLike, ...]


@dataclass(frozen=True, slots=True)
class SparseView:
    """One independently ranked feature representation."""

    name: str
    preferred_weight: int
    alternate_weight: int = 0
    identifier_weight: int = 0
    definition_weight: int = 0
    scope_weight: int = 0
    parent_weight: int = 0
    child_weight: int = 0
    word_features: bool = True
    phrase_features: bool = True
    bigram_features: bool = True
    character_ngrams: tuple[int, ...] = ()


LABEL_SPARSE_VIEW = SparseView(
    name="labelSparseV1",
    preferred_weight=12,
    alternate_weight=9,
    identifier_weight=7,
)

CONTEXT_SPARSE_VIEW = SparseView(
    name="contextSparseV1",
    preferred_weight=12,
    alternate_weight=9,
    identifier_weight=7,
    definition_weight=2,
    scope_weight=3,
    parent_weight=5,
    child_weight=5,
)

CHARACTER_SPARSE_VIEW = SparseView(
    name="labelCharacterNgramV1",
    preferred_weight=5,
    alternate_weight=3,
    word_features=False,
    phrase_features=False,
    bigram_features=False,
    character_ngrams=(3, 4),
)

DEFAULT_SPARSE_VIEWS = (
    LABEL_SPARSE_VIEW,
    CONTEXT_SPARSE_VIEW,
    CHARACTER_SPARSE_VIEW,
)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """One pair retained by a deterministic retrieval arm."""

    source_member: str
    target_member: str
    method: str
    source_rank: int | None = None
    target_rank: int | None = None
    source_score: int | None = None
    target_score: int | None = None
    evidence: tuple[tuple[str, str | int], ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return self.source_member, self.target_member

    def as_evidence(self) -> dict[str, object]:
        result: dict[str, object] = {
            "method": self.method,
            "version": "1",
        }
        if self.source_rank is not None:
            result["sourceToTargetRank"] = self.source_rank
        if self.target_rank is not None:
            result["targetToSourceRank"] = self.target_rank
        if self.source_score is not None:
            result["sourceToTargetScore"] = self.source_score
        if self.target_score is not None:
            result["targetToSourceScore"] = self.target_score
        result.update(dict(self.evidence))
        return result


def _normalized_words(value: str) -> tuple[str, ...]:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", unicodedata.normalize("NFKC", value))
    return tuple(token for token in re.split(r"[^0-9a-z]+", value.casefold()) if token)


def _normalized_phrase(value: str) -> str:
    return " ".join(_normalized_words(value))


def identifier_labels(member: str) -> tuple[str, ...]:
    """Return stable, human-readable identifier tails for one member IRI."""

    parsed = urlparse(member)
    candidates = [unquote(parsed.fragment)] if parsed.fragment else []
    path_tail = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    if path_tail:
        candidates.append(path_tail)
    if parsed.scheme == "urn":
        candidates.append(unquote(member.rsplit(":", 1)[-1]))
    result = {
        phrase for value in candidates if (phrase := _normalized_phrase(value)) and len(phrase.replace(" ", "")) >= 3
    }
    return tuple(sorted(result))


def _add_text_features(
    features: Counter[str],
    value: str | None,
    *,
    weight: int,
    view: SparseView,
) -> None:
    if not value or weight <= 0:
        return
    words = _normalized_words(value)
    if not words:
        return
    phrase = " ".join(words)
    if view.word_features:
        for token, count in Counter(words).items():
            features[f"word:{token}"] += weight * min(count, TERM_FREQUENCY_CAP)
    if view.bigram_features:
        for left, right in pairwise(words):
            features[f"bigram:{left} {right}"] += weight
    if view.phrase_features:
        features[f"phrase:{phrase}"] += weight * 2
    padded = f"  {phrase}  "
    for size in view.character_ngrams:
        for ngram, count in Counter(
            padded[index : index + size] for index in range(max(0, len(padded) - size + 1))
        ).items():
            features[f"char{size}:{ngram}"] += weight * min(count, TERM_FREQUENCY_CAP)


def raw_features(concept: ConceptLike, view: SparseView) -> Counter[str]:
    """Build one field-aware feature vector before corpus rarity weighting."""

    result: Counter[str] = Counter()
    _add_text_features(result, concept.pref_label, weight=view.preferred_weight, view=view)
    for value in sorted(set(concept.alt_labels)):
        _add_text_features(result, value, weight=view.alternate_weight, view=view)
    for value in identifier_labels(concept.member):
        _add_text_features(result, value, weight=view.identifier_weight, view=view)
    _add_text_features(result, concept.definition, weight=view.definition_weight, view=view)
    _add_text_features(result, concept.scope_note, weight=view.scope_weight, view=view)
    for context in sorted(concept.parents, key=lambda item: item.member):
        _add_text_features(result, context.pref_label, weight=view.parent_weight, view=view)
        for value in sorted(set(context.alt_labels)):
            _add_text_features(result, value, weight=max(1, view.parent_weight // 2), view=view)
    for context in sorted(concept.children, key=lambda item: item.member):
        _add_text_features(result, context.pref_label, weight=view.child_weight, view=view)
        for value in sorted(set(context.alt_labels)):
            _add_text_features(result, value, weight=max(1, view.child_weight // 2), view=view)
    return result


def _weighted_vectors(
    concepts: Sequence[ConceptLike],
    other: Sequence[ConceptLike],
    view: SparseView,
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    ordered = sorted((*concepts, *other), key=lambda item: item.member)
    raw = {concept.member: raw_features(concept, view) for concept in ordered}
    document_frequency: Counter[str] = Counter(feature for vector in raw.values() for feature in vector)
    population = len(raw)
    weighted: dict[str, dict[str, int]] = {}
    norms: dict[str, int] = {}
    for member, vector in raw.items():
        values = {
            feature: value * max(1, ((population + 1) * RARITY_SCALE) // (frequency + 1))
            for feature, value in vector.items()
            if (frequency := document_frequency[feature])
        }
        weighted[member] = values
        norms[member] = sum(value * value for value in values.values())
    return weighted, norms


def _directional_neighbors(
    queries: Sequence[ConceptLike],
    documents: Sequence[ConceptLike],
    *,
    vectors: Mapping[str, Mapping[str, int]],
    norms: Mapping[str, int],
    top_k: int,
) -> dict[tuple[str, str], tuple[int, int]]:
    postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for document in sorted(documents, key=lambda item: item.member):
        for feature, value in vectors[document.member].items():
            postings[feature].append((document.member, value))
    result: dict[tuple[str, str], tuple[int, int]] = {}
    for query in sorted(queries, key=lambda item: item.member):
        dots: dict[str, int] = defaultdict(int)
        for feature, query_value in vectors[query.member].items():
            for member, document_value in postings.get(feature, ()):
                dots[member] += query_value * document_value
        scored = []
        for member, dot in dots.items():
            denominator = isqrt(norms[query.member] * norms[member])
            if denominator:
                scored.append((dot * SCORE_SCALE // denominator, member))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for rank, (score, member) in enumerate(scored[:top_k], start=1):
            result[(query.member, member)] = (rank, score)
    return result


def bidirectional_sparse_neighbors(
    source_concepts: Sequence[ConceptLike],
    target_concepts: Sequence[ConceptLike],
    *,
    view: SparseView,
    top_k: int,
) -> tuple[RetrievalHit, ...]:
    """Return the union of source-to-target and target-to-source top-k rows."""

    if top_k <= 0:
        return ()
    sources = tuple(sorted(source_concepts, key=lambda item: item.member))
    targets = tuple(sorted(target_concepts, key=lambda item: item.member))
    vectors, norms = _weighted_vectors(sources, targets, view)
    forward = _directional_neighbors(
        sources,
        targets,
        vectors=vectors,
        norms=norms,
        top_k=top_k,
    )
    reverse_raw = _directional_neighbors(
        targets,
        sources,
        vectors=vectors,
        norms=norms,
        top_k=top_k,
    )
    reverse = {(source, target): value for (target, source), value in reverse_raw.items()}
    return tuple(
        RetrievalHit(
            source_member=source,
            target_member=target,
            method=f"bidirectional-{view.name}",
            source_rank=forward.get((source, target), (None, None))[0],
            target_rank=reverse.get((source, target), (None, None))[0],
            source_score=forward.get((source, target), (None, None))[1],
            target_score=reverse.get((source, target), (None, None))[1],
            evidence=(("topK", top_k),),
        )
        for source, target in sorted(set(forward) | set(reverse))
    )


def exact_identifier_neighbors(
    source_concepts: Sequence[ConceptLike],
    target_concepts: Sequence[ConceptLike],
) -> tuple[RetrievalHit, ...]:
    """Match exact normalized local identifiers without assuming identity."""

    targets: dict[str, list[str]] = defaultdict(list)
    for concept in sorted(target_concepts, key=lambda item: item.member):
        for value in identifier_labels(concept.member):
            targets[value].append(concept.member)
    hits: dict[tuple[str, str], RetrievalHit] = {}
    for concept in sorted(source_concepts, key=lambda item: item.member):
        for value in identifier_labels(concept.member):
            for target in targets.get(value, ()):
                hits.setdefault(
                    (concept.member, target),
                    RetrievalHit(
                        concept.member,
                        target,
                        "normalized-local-identifier-equality",
                        evidence=(("normalizedIdentifier", value),),
                    ),
                )
    return tuple(hits[key] for key in sorted(hits))


def graph_neighborhood_neighbors(
    source_concepts: Sequence[ConceptLike],
    target_concepts: Sequence[ConceptLike],
    anchors: Iterable[tuple[str, str]],
) -> tuple[RetrievalHit, ...]:
    """Expand aligned anchors through one native hierarchy step on either side."""

    source_by_id = {concept.member: concept for concept in source_concepts}
    target_by_id = {concept.member: concept for concept in target_concepts}
    source_ids = set(source_by_id)
    target_ids = set(target_by_id)

    def parents(concept: ConceptLike, valid: set[str]) -> tuple[str, ...]:
        return tuple(sorted({*concept.broader, *(item.member for item in concept.parents)} & valid))

    def children(concept: ConceptLike, valid: set[str]) -> tuple[str, ...]:
        return tuple(sorted({item.member for item in concept.children} & valid))

    hits: dict[tuple[str, str], RetrievalHit] = {}

    def add(source: str, target: str, anchor: tuple[str, str], path: str) -> None:
        if (source, target) == anchor:
            return
        evidence = (("anchorSource", anchor[0]), ("anchorTarget", anchor[1]), ("path", path))
        candidate = RetrievalHit(source, target, "one-hop-aligned-graph-neighborhood", evidence=evidence)
        existing = hits.get(candidate.key)
        if existing is None or candidate.evidence < existing.evidence:
            hits[candidate.key] = candidate

    for anchor in sorted(set(anchors)):
        source = source_by_id.get(anchor[0])
        target = target_by_id.get(anchor[1])
        if source is None or target is None:
            continue
        source_parents = parents(source, source_ids)
        source_children = children(source, source_ids)
        target_parents = parents(target, target_ids)
        target_children = children(target, target_ids)
        for left in source_parents:
            add(left, target.member, anchor, "sourceParent-to-target")
            for right in target_parents:
                add(left, right, anchor, "sourceParent-to-targetParent")
        for left in source_children:
            add(left, target.member, anchor, "sourceChild-to-target")
            for right in target_children:
                add(left, right, anchor, "sourceChild-to-targetChild")
        for right in target_parents:
            add(source.member, right, anchor, "source-to-targetParent")
        for right in target_children:
            add(source.member, right, anchor, "source-to-targetChild")
    return tuple(hits[key] for key in sorted(hits))


def retrieval_digest(hits: Sequence[RetrievalHit]) -> str:
    """Digest the exact ordered rows for repeat and input-order checks."""

    rows = [
        {
            "source": hit.source_member,
            "target": hit.target_member,
            **hit.as_evidence(),
        }
        for hit in sorted(hits, key=lambda item: (item.method, item.key))
    ]
    return "sha256:" + hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()


__all__ = [
    "CHARACTER_SPARSE_VIEW",
    "CONTEXT_SPARSE_VIEW",
    "DEFAULT_SPARSE_VIEWS",
    "LABEL_SPARSE_VIEW",
    "RetrievalHit",
    "SparseView",
    "bidirectional_sparse_neighbors",
    "exact_identifier_neighbors",
    "graph_neighborhood_neighbors",
    "identifier_labels",
    "raw_features",
    "retrieval_digest",
]

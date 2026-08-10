"""Deterministic candidate generation and retrieval across two vocabularies.

Two halves of one job: turn a pair of exact concept releases into the set of
cross-release pairs worth a closer look, using nothing but the concept facts
themselves.

The *generator* is the six-class blocking recipe -- label equality, alternate
labels, two kinds of near miss, and two kinds of negative control.  It is
deterministic in the two concept sets alone: input order never reaches the
result, the draw is seeded, and the classes are disjoint by construction, so
the same releases reproduce the same population on every run.  Every pair
carries the rule that proposed it, which is what makes a measured result
attributable to a rule rather than to a run.

The *retrieval* half optimizes for inclusive discovery: multiple independent
sparse views and graph expansion, so callers can union its results with the
generator's exact-label rules and their own dense-neighbor artifacts.  Scores
are integer cosine approximations, using no process hashes, floating-point
comparisons, or input ordering.

Nothing here calls a provider or seals a record.  This module answers "which
pairs are worth asking about", never "what is the answer".
"""

from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as _replace
from itertools import pairwise
from math import isqrt
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from refspec.storage import canonical_json

SCORE_SCALE = 1_000_000_000
RARITY_SCALE = 1_024
TERM_FREQUENCY_CAP = 3


class CandidateGenerationError(ValueError):
    """Candidate generation cannot proceed with the concepts it was given."""


class ContextLike(Protocol):
    """The hierarchy fields used by the sparse views."""

    member: str
    pref_label: str
    alt_labels: tuple[str, ...]
    definition: str | None
    scope_note: str | None


class ConceptLike(ContextLike, Protocol):
    """The concept surface consumed by this module."""

    broader: tuple[str, ...]
    parents: tuple[ContextLike, ...]
    children: tuple[ContextLike, ...]


@dataclass(frozen=True, slots=True)
class AtlasConceptContext:
    """A non-recursive concept description used for bounded hierarchy context."""

    member: str
    pref_label: str
    alt_labels: tuple[str, ...] = ()
    definition: str | None = None
    scope_note: str | None = None


@dataclass(frozen=True, slots=True)
class AtlasConcept:
    """One release member reduced to what a crosswalk decision can use."""

    member: str
    release: str
    pref_label: str
    alt_labels: tuple[str, ...] = ()
    definition: str | None = None
    scope_note: str | None = None
    broader: tuple[str, ...] = ()
    vocabulary: str = ""
    parents: tuple[AtlasConceptContext, ...] = ()
    children: tuple[AtlasConceptContext, ...] = ()


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


# ---------------------------------------------------------------------------
# the pinned six-class generation policy
# ---------------------------------------------------------------------------

#: The generation rule, pinned.  It names the whole recipe below -- the classes,
#: their order, their caps, and the seeded draw -- so a result can say which
#: population its candidates came from.
CANDIDATE_GENERATION_POLICY = "atlas-crosswalk-candidate-generation-v1"

#: The release path evaluates every pair reached by the deterministic blocking
#: rules.  It deliberately has a different policy identifier from the capped
#: pilot so a capped slice cannot be mistaken for production coverage.
PRODUCTION_CANDIDATE_GENERATION_POLICY = "atlas-crosswalk-candidate-generation-production-v1"
PILOT_CANDIDATE_GENERATION_POLICY = CANDIDATE_GENERATION_POLICY

#: Seeded so the draw is reproducible from the two releases alone.
GENERATION_SEED = "refspec-atlas-crosswalk-2026-08-02"

#: Every class, in the order they are generated.  A pair is assigned to the
#: first class that claims it, so the classes are disjoint by construction.
GENERATION_CLASSES = (
    "normalizedLabelEquality",
    "alternateLabelEquality",
    "substringNearMiss",
    "editDistanceNearMiss",
    "siblingDistractor",
    "randomNegativeControl",
)

#: Pilot-slice caps.  Deliberately not "all equalities": a slice dominated by
#: the easy diagonal measures nothing, which is the whole reason the near-miss
#: and control classes exist.
DEFAULT_CLASS_LIMITS: Mapping[str, int] = {
    "normalizedLabelEquality": 110,
    "alternateLabelEquality": 55,
    "substringNearMiss": 55,
    "editDistanceNearMiss": 55,
    "siblingDistractor": 45,
    "randomNegativeControl": 45,
}

#: A production catalog has no caps on semantic blocking classes.  Random
#: controls are a measured arm rather than a discoverable population, so their
#: reproducible sample size remains explicit.
PRODUCTION_RANDOM_CONTROL_COUNT = 45
CONTROL_GENERATION_CLASSES = frozenset({"siblingDistractor", "randomNegativeControl"})

#: Direct parents and children carried on each side.  The bound is symmetrical
#: and member-IRI ordered, keeping payload size and identity stable.
HIERARCHY_CONTEXT_LIMIT = 5

#: Levenshtein bound for the near-miss class.  Two edits catches plural and
#: spelling variants; three starts catching unrelated short labels.
EDIT_DISTANCE_LIMIT = 2

#: Hard ceiling on the seeded search for random controls.
RANDOM_CONTROL_ATTEMPT_CEILING = 200_000

EVIDENCE_METHOD_VERSION = "1"


@dataclass(frozen=True, slots=True)
class CandidatePair:
    """One proposed cross-release pair and the rule that proposed it."""

    source: AtlasConcept
    target: AtlasConcept
    generation_class: str
    evidence: Mapping[str, Any]
    generation_policy: str = CANDIDATE_GENERATION_POLICY

    @property
    def key(self) -> tuple[str, str]:
        return (self.source.member, self.target.member)


def normalize_label(value: str) -> str:
    """Fold one label to the form the equality classes compare."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def normalized_tokens(value: str) -> tuple[str, ...]:
    """Split a label the way the equality classes compare it."""

    return tuple(token for token in re.split(r"[^0-9a-z]+", normalize_label(value)) if token)


def _bounded_edit_distance(left: str, right: str, limit: int) -> int:
    """Levenshtein distance, abandoned as soon as it exceeds ``limit``."""

    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for index, left_character in enumerate(left, start=1):
        current = [index]
        best = index
        for offset, right_character in enumerate(right, start=1):
            cost = 0 if left_character == right_character else 1
            value = min(
                previous[offset] + 1,
                current[offset - 1] + 1,
                previous[offset - 1] + cost,
            )
            current.append(value)
            best = min(best, value)
        if best > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _draw(pairs: Sequence[CandidatePair], limit: int, *, seed: str, label: str) -> list[CandidatePair]:
    """Take at most ``limit`` pairs by a seeded draw over a sorted population.

    Sorted first so the population never depends on dictionary or file order,
    then drawn rather than truncated so a capped class still spans the whole
    vocabulary instead of its alphabetical head.
    """

    ordered = sorted(pairs, key=lambda pair: pair.key)
    if limit >= len(ordered):
        return ordered
    if limit <= 0:
        return []
    chosen = random.Random(f"{seed}:{label}").sample(range(len(ordered)), limit)
    return [ordered[index] for index in sorted(chosen)]


def _contains_token_run(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    if not needle or len(needle) >= len(haystack):
        return False
    return any(
        tuple(haystack[index : index + len(needle)]) == tuple(needle)
        for index in range(len(haystack) - len(needle) + 1)
    )


def generate_candidate_pairs(
    source_concepts: Sequence[AtlasConcept],
    target_concepts: Sequence[AtlasConcept],
    *,
    limits: Mapping[str, int] | None = None,
    seed: str = GENERATION_SEED,
    production: bool = False,
) -> tuple[CandidatePair, ...]:
    """Return a deterministic pilot slice or the complete production catalog.

    Deterministic in the two concept sets alone -- input order never reaches
    the result -- because a candidate population that moves between runs cannot
    be the pinned input a measured result claims it is.
    """

    if production and limits is not None:
        raise CandidateGenerationError("production candidate generation does not accept pilot class limits")
    active_limits: Mapping[str, int | None]
    if production:
        active_limits = {
            **{name: None for name in GENERATION_CLASSES},
            "randomNegativeControl": PRODUCTION_RANDOM_CONTROL_COUNT,
        }
    else:
        active_limits = dict(DEFAULT_CLASS_LIMITS if limits is None else limits)
    generation_policy = (
        PRODUCTION_CANDIDATE_GENERATION_POLICY if production else PILOT_CANDIDATE_GENERATION_POLICY
    )

    sources = sorted(source_concepts, key=lambda concept: concept.member)
    targets = sorted(target_concepts, key=lambda concept: concept.member)
    if not sources or not targets:
        raise CandidateGenerationError("candidate generation needs concepts on both sides")
    source_releases = {concept.release for concept in sources}
    target_releases = {concept.release for concept in targets}
    if source_releases & target_releases:
        raise CandidateGenerationError("a crosswalk candidate must cross releases")

    target_by_pref: dict[str, list[AtlasConcept]] = {}
    target_by_any: dict[str, list[AtlasConcept]] = {}
    for concept in targets:
        target_by_pref.setdefault(normalize_label(concept.pref_label), []).append(concept)
        for label in (concept.pref_label, *concept.alt_labels):
            target_by_any.setdefault(normalize_label(label), []).append(concept)
    by_member = {concept.member: concept for concept in targets}
    children_of: dict[str, list[str]] = {}
    for concept in targets:
        for parent in concept.broader:
            children_of.setdefault(parent, []).append(concept.member)

    claimed: set[tuple[str, str]] = set()
    selected: list[CandidatePair] = []

    def _claim(pairs: Iterable[CandidatePair], label: str) -> list[CandidatePair]:
        # Deduplicate by pair, not just against earlier classes: one class can
        # reach the same pair twice (a target with a preferred and an alternate
        # spelling of one label; a sibling under two shared parents), and two
        # identical pairs are two identical candidates a downstream reader has
        # no way to tell apart.
        fresh: dict[tuple[str, str], CandidatePair] = {}
        for pair in pairs:
            if pair.key not in claimed:
                fresh.setdefault(pair.key, pair)
        limit = active_limits.get(label, 0)
        drawn = (
            sorted(fresh.values(), key=lambda pair: pair.key)
            if limit is None
            else _draw(tuple(fresh.values()), int(limit), seed=seed, label=label)
        )
        claimed.update(pair.key for pair in drawn)
        selected.extend(drawn)
        return drawn

    # 1. The easy diagonal: equal normalized preferred labels.
    equality: list[CandidatePair] = []
    for concept in sources:
        normalized = normalize_label(concept.pref_label)
        for match in target_by_pref.get(normalized, ()):
            equality.append(
                CandidatePair(
                    source=concept,
                    target=match,
                    generation_class="normalizedLabelEquality",
                    evidence={
                        "method": "normalized-preferred-label-equality",
                        "normalizedLabel": normalized,
                        "version": EVIDENCE_METHOD_VERSION,
                    },
                )
            )
    equal_keys = {pair.key for pair in equality}
    drawn_equality = _claim(equality, "normalizedLabelEquality")

    # 2. An alternate label on either side carries the equality instead.
    alternates: list[CandidatePair] = []
    for concept in sources:
        for label in (concept.pref_label, *concept.alt_labels):
            normalized = normalize_label(label)
            for match in target_by_any.get(normalized, ()):
                if (concept.member, match.member) in equal_keys:
                    continue
                alternates.append(
                    CandidatePair(
                        source=concept,
                        target=match,
                        generation_class="alternateLabelEquality",
                        evidence={
                            "method": "normalized-alternate-label-equality",
                            "normalizedLabel": normalized,
                            "version": EVIDENCE_METHOD_VERSION,
                        },
                    )
                )
    _claim(alternates, "alternateLabelEquality")

    # Normalize once. Both near-miss classes are |sources| x |targets|, which
    # is 2.4 million pairs on the real vocabularies; re-normalizing each label
    # inside the inner loop turns a fast scan into a slow one for no gain.
    normalized_targets = tuple(
        (concept, normalize_label(concept.pref_label), normalized_tokens(concept.pref_label))
        for concept in targets
    )

    # 3. One preferred label properly contains the other, on token boundaries.
    substrings: list[CandidatePair] = []
    for concept in sources:
        source_tokens = normalized_tokens(concept.pref_label)
        if not source_tokens:
            continue
        for candidate, _, target_tokens in normalized_targets:
            if not target_tokens or source_tokens == target_tokens:
                continue
            if _contains_token_run(target_tokens, source_tokens):
                direction = "sourceInsideTarget"
            elif _contains_token_run(source_tokens, target_tokens):
                direction = "targetInsideSource"
            else:
                continue
            substrings.append(
                CandidatePair(
                    source=concept,
                    target=candidate,
                    generation_class="substringNearMiss",
                    evidence={
                        "direction": direction,
                        "method": "normalized-preferred-label-token-containment",
                        "sharedTokens": " ".join(
                            source_tokens if direction == "sourceInsideTarget" else target_tokens
                        ),
                        "version": EVIDENCE_METHOD_VERSION,
                    },
                )
            )
    _claim(substrings, "substringNearMiss")

    # 4. Within a couple of edits: plurals, spellings, one-word differences.
    near: list[CandidatePair] = []
    for concept in sources:
        normalized = normalize_label(concept.pref_label)
        if not normalized:
            continue
        for candidate, other, _ in normalized_targets:
            if not other or other == normalized:
                continue
            distance = _bounded_edit_distance(normalized, other, EDIT_DISTANCE_LIMIT)
            if distance > EDIT_DISTANCE_LIMIT:
                continue
            near.append(
                CandidatePair(
                    source=concept,
                    target=candidate,
                    generation_class="editDistanceNearMiss",
                    evidence={
                        "editDistance": distance,
                        "method": "normalized-preferred-label-edit-distance",
                        "version": EVIDENCE_METHOD_VERSION,
                    },
                )
            )
    _claim(near, "editDistanceNearMiss")

    # 5. Hard negatives: a sibling of a concept that DID match by label. The
    #    labels differ, but the target sits one step from a true match, so a
    #    reader that pattern-matches on topic instead of identity says yes.
    siblings: list[CandidatePair] = []
    for pair in drawn_equality:
        for parent in by_member[pair.target.member].broader:
            for sibling_member in sorted(children_of.get(parent, ())):
                if sibling_member == pair.target.member:
                    continue
                sibling = by_member[sibling_member]
                siblings.append(
                    CandidatePair(
                        source=pair.source,
                        target=sibling,
                        generation_class="siblingDistractor",
                        evidence={
                            "method": "target-sibling-of-label-equal-match",
                            "sharedBroader": parent,
                            "siblingOf": pair.target.member,
                            "version": EVIDENCE_METHOD_VERSION,
                        },
                    )
                )
    _claim(siblings, "siblingDistractor")

    # 6. Random pairs with no shared token: the floor a gate must refuse.
    controls: list[CandidatePair] = []
    rng = random.Random(f"{seed}:randomNegativeControl:population")
    wanted = int(active_limits.get("randomNegativeControl", 0) or 0)
    attempts = 0
    # The control population is drawn, not enumerated, so it needs its own
    # ceiling: a caller who asks for more controls than the vocabularies can
    # supply must get a short class, never an unbounded search.
    attempt_ceiling = min(wanted * 400, RANDOM_CONTROL_ATTEMPT_CEILING)
    seen: set[tuple[str, str]] = set()
    while len(controls) < wanted * 3 and attempts < attempt_ceiling:
        attempts += 1
        concept = sources[rng.randrange(len(sources))]
        candidate = targets[rng.randrange(len(targets))]
        key = (concept.member, candidate.member)
        if key in claimed or key in seen:
            continue
        left = set(normalized_tokens(concept.pref_label))
        right = set(normalized_tokens(candidate.pref_label))
        if not left or not right or left & right:
            continue
        seen.add(key)
        controls.append(
            CandidatePair(
                source=concept,
                target=candidate,
                generation_class="randomNegativeControl",
                evidence={
                    "method": "seeded-random-disjoint-token-pair",
                    "seed": f"{seed}:randomNegativeControl",
                    "version": EVIDENCE_METHOD_VERSION,
                },
            )
        )
    _claim(controls, "randomNegativeControl")

    order = {name: index for index, name in enumerate(GENERATION_CLASSES)}
    return tuple(
        _replace(pair, generation_policy=generation_policy)
        for pair in sorted(selected, key=lambda pair: (order[pair.generation_class], pair.key))
    )


# ---------------------------------------------------------------------------
# release adapters
# ---------------------------------------------------------------------------

_PREF_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
_ALT_LABEL = "http://www.w3.org/2004/02/skos/core#altLabel"
_DEFINITION = "http://www.w3.org/2004/02/skos/core#definition"
_SCOPE_NOTE = "http://www.w3.org/2004/02/skos/core#scopeNote"
_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
_RETIRED_SOURCE_STATUSES = frozenset({"deprecated", "withdrawn", "superseded", "retired", "obsolete"})


def _hierarchy_context(
    member_ids: Iterable[str],
    *,
    preferred: Mapping[str, str],
    alternates: Mapping[str, Sequence[str]],
    definitions: Mapping[str, str],
    scope_notes: Mapping[str, str],
) -> tuple[AtlasConceptContext, ...]:
    """Return a stable, bounded, non-recursive description of neighbors."""

    return tuple(
        AtlasConceptContext(
            member=member_id,
            pref_label=preferred[member_id],
            alt_labels=tuple(sorted(alternates.get(member_id, ()))),
            definition=definitions.get(member_id),
            scope_note=scope_notes.get(member_id),
        )
        for member_id in sorted(set(member_ids))[:HIERARCHY_CONTEXT_LIMIT]
        if member_id in preferred
    )


def concepts_from_view(
    view: Any,
    *,
    language: str | None = "en",
    release_iri: str | None = None,
    vocabulary: str = "",
) -> tuple[AtlasConcept, ...]:
    """Project one verified managed-release view into crosswalk concepts.

    ``release_iri`` selects one reference release when a bundle carries several
    (ELSST ships R5 and R6 in one managed release), because a candidate names
    exactly one release per endpoint.
    """

    members = {
        member.member_iri: member
        for member in view.iter_members()
        if release_iri is None or member.release_iri == release_iri
    }
    preferred: dict[str, str] = {}
    alternates: dict[str, list[str]] = {}
    definitions: dict[str, str] = {}
    scope_notes: dict[str, str] = {}
    for expression in view.iter_expressions():
        if expression.member_iri not in members:
            continue
        if language is not None and expression.language_tag not in (None, language):
            continue
        # Only a status the source itself calls retired is dropped. Allow-listing
        # instead would silently empty a whole vocabulary: the Federal Register
        # package writes "active" and ELSST writes "notDeclared", so a list built
        # from one of them yields zero concepts from the other.
        if expression.source_status in _RETIRED_SOURCE_STATUSES:
            continue
        property_iri = expression.semantic_property_iri
        literal = expression.original_literal
        if property_iri == _PREF_LABEL and expression.label_role in (None, "preferred"):
            preferred.setdefault(expression.member_iri, literal)
        elif property_iri == _ALT_LABEL:
            values = alternates.setdefault(expression.member_iri, [])
            if literal not in values:
                values.append(literal)
        elif property_iri == _DEFINITION:
            definitions.setdefault(expression.member_iri, literal)
        elif property_iri == _SCOPE_NOTE:
            scope_notes.setdefault(expression.member_iri, literal)
    broader: dict[str, list[str]] = {}
    for relation in view.iter_relations():
        if relation.predicate_iri != _BROADER:
            continue
        if relation.subject_member_iri not in members or relation.object_member_iri not in members:
            continue
        broader.setdefault(relation.subject_member_iri, []).append(relation.object_member_iri)
    children: dict[str, list[str]] = {}
    for child, parents in broader.items():
        for parent in parents:
            children.setdefault(parent, []).append(child)
    return tuple(
        AtlasConcept(
            member=member_iri,
            release=member.release_iri,
            pref_label=preferred[member_iri],
            alt_labels=tuple(sorted(alternates.get(member_iri, ()))),
            definition=definitions.get(member_iri),
            scope_note=scope_notes.get(member_iri),
            broader=tuple(sorted(broader.get(member_iri, ()))),
            vocabulary=vocabulary,
            parents=_hierarchy_context(
                broader.get(member_iri, ()),
                preferred=preferred,
                alternates=alternates,
                definitions=definitions,
                scope_notes=scope_notes,
            ),
            children=_hierarchy_context(
                children.get(member_iri, ()),
                preferred=preferred,
                alternates=alternates,
                definitions=definitions,
                scope_notes=scope_notes,
            ),
        )
        for member_iri, member in sorted(members.items())
        if member_iri in preferred
    )


def concepts_from_source_release(
    view: Any,
    *,
    language: str | None = "en",
    vocabulary: str = "",
) -> tuple[AtlasConcept, ...]:
    """Project one exact ``SourceConceptRelease`` into crosswalk concepts.

    Source-scoped concept rows intentionally carry identity and provenance but
    no duplicated labels.  Labels, definitions, and scope notes are recovered
    from the exact source observations each row pins.  Only the subject ring is
    accepted; other rings need source-authoritative rules.
    """

    if getattr(view, "semantic_ring", None) != "subject":
        raise CandidateGenerationError("candidate generation accepts subject SourceConceptRelease inputs only")
    observations = {
        str(observation["id"]): observation for observation in view.source_bundle.observations
    }
    concepts: list[AtlasConcept] = []
    for row in sorted(view.concepts, key=lambda value: str(value["id"])):
        observation_id = str(row["sourceObservation"])
        observation = observations.get(observation_id)
        if observation is None:
            raise CandidateGenerationError(
                f"source concept {row['id']!r} cites an observation outside its exact source capture"
            )
        labels = [
            label
            for label in observation.get("labels", ())
            if isinstance(label, Mapping)
            and (language is None or label.get("language") in (None, language))
            and isinstance(label.get("value"), str)
            and str(label["value"]).strip()
        ]
        preferred = [str(label["value"]) for label in labels if label.get("role") == "preferred"]
        if len(preferred) != 1:
            raise CandidateGenerationError(
                f"source concept {row['id']!r} needs exactly one preferred label for language {language!r}"
            )
        alternates = tuple(
            sorted({str(label["value"]) for label in labels if label.get("role") == "alternate"})
        )
        definition = observation.get("definition")
        scope_note = observation.get("scopeNote")
        concepts.append(
            AtlasConcept(
                member=str(row["id"]),
                release=str(view.release_id),
                pref_label=preferred[0],
                alt_labels=alternates,
                definition=str(definition) if isinstance(definition, str) and definition else None,
                scope_note=str(scope_note) if isinstance(scope_note, str) and scope_note else None,
                vocabulary=vocabulary,
            )
        )
    return tuple(concepts)


__all__ = [
    "CANDIDATE_GENERATION_POLICY",
    "CHARACTER_SPARSE_VIEW",
    "CONTEXT_SPARSE_VIEW",
    "CONTROL_GENERATION_CLASSES",
    "DEFAULT_CLASS_LIMITS",
    "DEFAULT_SPARSE_VIEWS",
    "EDIT_DISTANCE_LIMIT",
    "EVIDENCE_METHOD_VERSION",
    "GENERATION_CLASSES",
    "GENERATION_SEED",
    "HIERARCHY_CONTEXT_LIMIT",
    "LABEL_SPARSE_VIEW",
    "PILOT_CANDIDATE_GENERATION_POLICY",
    "PRODUCTION_CANDIDATE_GENERATION_POLICY",
    "PRODUCTION_RANDOM_CONTROL_COUNT",
    "RANDOM_CONTROL_ATTEMPT_CEILING",
    "AtlasConcept",
    "AtlasConceptContext",
    "CandidateGenerationError",
    "CandidatePair",
    "RetrievalHit",
    "SparseView",
    "bidirectional_sparse_neighbors",
    "concepts_from_source_release",
    "concepts_from_view",
    "exact_identifier_neighbors",
    "generate_candidate_pairs",
    "graph_neighborhood_neighbors",
    "identifier_labels",
    "normalize_label",
    "normalized_tokens",
    "raw_features",
    "retrieval_digest",
]

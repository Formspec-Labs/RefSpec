"""Offline crosswalk qualification: generate candidates, ask two machines, seal.

This module is the producer side of a ``CrosswalkBundle``.  It never runs
inside an atlas build.  A build must be byte-reproducible from its pinned
inputs, and a provider call is not reproducible, so qualification is an offline
step whose *output* — one sealed, digest-pinned bundle file — becomes a pinned
build input.  That is the same idiom every other external fact in this
repository already uses, and the reason this module is deliberately absent from
``model._IMPLEMENTATION_SOURCE_PATHS``: an atlas identity must not move when
the offline runner changes.

Three properties this code owes its receipts:

* **The judge is blind to the generator's hypothesis.**  Candidate generation
  labels every pair with the rule that proposed it — label equality, a
  near-miss, a negative control — and none of that reaches the model input.  A
  judge told "this pair is a negative control" would agree with the generator
  rather than read the concepts, and the two-machine gate would measure the
  generator instead of the mapping.
* **A failed call is a failure.**  There is no retry-until-agree.  A transport
  error is retried exactly once because a dropped socket is not an answer;
  every other failure is receipted and the candidate simply keeps fewer than
  two validations, which leaves it ineligible.
* **No credential reaches an artifact.**  Only the credential-free request
  identity (its digest) and scrubbed headers are recorded.

The provider layer reimplements, under the file-only seam, the transport and
receipt discipline proven at scale in
``spicysearch/src/spicysearch/holdout_labeling.py`` (``UrllibTransport``,
``list_models``, ``resolve_judge_model``, ``SpendTracker``, ``judge_call``) and
the pinned-budget lesson from ``spicy-regs/tools/run_citation_bakeoff.py``: a
reasoning model spends output budget on thinking tokens before it answers, so
``reasoning_effort`` is pinned low and the token budget must cover both.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import random
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from refspec.storage import canonical_json

from .model import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
    VocabularyAtlasError,
    _normalize_label,
)


class QualificationError(VocabularyAtlasError):
    """The qualification runner cannot proceed with what it was given."""


class FamilyUnavailableError(QualificationError):
    """A validator family's pinned model is absent from its live model list."""

    def __init__(self, message: str, near_matches: Sequence[str]) -> None:
        super().__init__(message)
        self.near_matches = tuple(near_matches)


class SpendCapReached(RuntimeError):
    """The next call would carry realized spend past a hard cap."""


# ---------------------------------------------------------------------------
# pinned generation policy
# ---------------------------------------------------------------------------

#: The generation rule, pinned.  It names the whole recipe below — the classes,
#: their order, their caps, and the seeded draw — so a bundle can say which
#: population its candidates came from.
CANDIDATE_GENERATION_POLICY = "atlas-crosswalk-candidate-generation-v1"

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
#: the easy diagonal would rubber-stamp the two-machine gate instead of testing
#: it, which is the whole reason the near-miss and control classes exist.
DEFAULT_CLASS_LIMITS: Mapping[str, int] = {
    "normalizedLabelEquality": 110,
    "alternateLabelEquality": 55,
    "substringNearMiss": 55,
    "editDistanceNearMiss": 55,
    "siblingDistractor": 45,
    "randomNegativeControl": 45,
}

#: Uniform across every class, on purpose.  A relation chosen per class would
#: hand the judge the generator's hypothesis through the back door, and
#: ``closeMatch`` is exactly the claim the search-expansion question asks
#: about: near-same, not identical.
PROPOSED_RELATION = "http://www.w3.org/2004/02/skos/core#closeMatch"

#: Levenshtein bound for the near-miss class.  Two edits catches plural and
#: spelling variants; three starts catching unrelated short labels.
EDIT_DISTANCE_LIMIT = 2

#: Hard ceiling on the seeded search for random controls.
RANDOM_CONTROL_ATTEMPT_CEILING = 200_000

#: Qualification has one protocol.  A second name or an implicit fallback here
#: would let candidate generation and provider execution ask different
#: questions while producing superficially valid receipts.
PROTOCOL = "v2"
MODEL_INPUT_PROTOCOL = "refspec-atlas-crosswalk-model-input-v2"
VALIDATION_REQUEST_PROTOCOL = "refspec-atlas-machine-validation-v2"
EVIDENCE_METHOD_VERSION = "1"

GENERATOR_ACTOR = "urn:ref:actor:atlas-crosswalk-candidate-generator"
GENERATOR_PROVIDER = "urn:ref:provider:refspec-deterministic-generator"
GENERATOR_MODEL_ID = "refspec-atlas-crosswalk-candidate-generator"
GENERATOR_MODEL_VERSION = "1"
PROMPT_TEMPLATE_IRI = "urn:ref:atlas-crosswalk:prompt:search-expansion:v1"

#: The judge adjudicates the relation, not a yes/no.  Direction is
#: pinned in English — mapping predicates are asserted source -> target, so
#: ``target_is_broader`` emits ``skos:broadMatch``.  The five relation verdicts
#: are all "supports"; the gate then additionally requires the two machines'
#: relations to be compatible (see the agreement lattice in ``model``).
VERDICTS = (
    "same",
    "near_same",
    "target_is_broader",
    "target_is_narrower",
    "related",
    "unrelated",
    "insufficient_evidence",
)
VERDICT_OUTCOMES: Mapping[str, str] = {
    "same": "supports",
    "near_same": "supports",
    "target_is_broader": "supports",
    "target_is_narrower": "supports",
    "related": "supports",
    "unrelated": "rejects",
    "insufficient_evidence": "abstains",
}
INSTRUCTIONS = """\
You judge the relation between two controlled-vocabulary concepts, each \
published by a different thesaurus.

The decision has exactly one purpose: SEARCH EXPANSION over a document \
collection. Each concept is used to index documents. Decide whether documents \
indexed under one belong in the other's results, in each direction.

Verdicts:
  same                 - interchangeable for indexing; treating these as one \
concept could never mislead. Answer this only when identity is beyond doubt; \
when in doubt, answer near_same.
  near_same            - substitution is safe in BOTH directions, but the \
concepts are not claimed identical.
  target_is_broader    - the TARGET strictly contains the SOURCE. Searching \
the source may include target-indexed documents; the reverse over-reaches.
  target_is_narrower   - the SOURCE strictly contains the TARGET.
  related              - genuinely associated (an actor and its activity, a \
measure and its phenomenon, neighbouring topics) but neither contains the \
other and substitution misleads.
  unrelated            - different things, not usefully related.
  insufficient_evidence - the supplied labels and notes do not let you decide.

Rules:
  - Judge the concepts, not the strings. Identical labels can name different \
things in two thesauri, and different labels can name the same thing.
  - Case, number, and spelling variants are not evidence of difference.
  - Do not guess. insufficient_evidence is a real answer.
  - Echo task_id back exactly as given.

Return exactly one JSON object and nothing else. No prose, no explanation \
outside the object, no Markdown code fences. It must match this JSON Schema:

{schema}
"""

RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["task_id", "verdict", "reason"],
    "properties": {
        "task_id": {"type": "string"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
    },
}

def instructions_text() -> str:
    """The exact system text every family receives, schema included.

    The schema is rendered into the instructions rather than sent as a
    ``response_format`` parameter: the two endpoints disagree about which
    structured-output field they honour, and a parameter one of them silently
    ignores would make the receipt claim an enforcement that never happened.
    The local validator is the guarantee, and it is the same for both.
    """

    return INSTRUCTIONS.replace("{schema}", canonical_json(dict(RESPONSE_SCHEMA)))


def require_protocol_v2(protocol: str) -> str:
    """Refuse qualification data produced for any other verdict protocol."""

    if protocol != PROTOCOL:
        raise QualificationError(
            f"unsupported qualification protocol {protocol!r}; this greenfield implementation supports only {PROTOCOL!r}"
        )
    return protocol


# Descriptive aliases retained for callers that named the adopted protocol
# explicitly.  They refer to the only supported shapes; they are not a second
# compatibility path.
PROTOCOL_V2 = VALIDATION_REQUEST_PROTOCOL
MODEL_INPUT_PROTOCOL_V2 = MODEL_INPUT_PROTOCOL
VERDICTS_V2 = VERDICTS
VERDICT_OUTCOMES_V2 = VERDICT_OUTCOMES
RESPONSE_SCHEMA_V2 = RESPONSE_SCHEMA
INSTRUCTIONS_V2 = INSTRUCTIONS
instructions_text_v2 = instructions_text


# ---------------------------------------------------------------------------
# concepts and candidate pairs
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True, slots=True)
class CandidatePair:
    """One proposed cross-release pair and the rule that proposed it."""

    source: AtlasConcept
    target: AtlasConcept
    generation_class: str
    evidence: Mapping[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return (self.source.member, self.target.member)


def normalized_tokens(value: str) -> tuple[str, ...]:
    """Split a label the way the equality classes compare it."""

    return tuple(token for token in re.split(r"[^0-9a-z]+", _normalize_label(value)) if token)


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


def generate_candidate_pairs(
    source_concepts: Sequence[AtlasConcept],
    target_concepts: Sequence[AtlasConcept],
    *,
    limits: Mapping[str, int] = DEFAULT_CLASS_LIMITS,
    seed: str = GENERATION_SEED,
) -> tuple[CandidatePair, ...]:
    """Return the pilot slice: easy diagonal, near-misses, and controls.

    Deterministic in the two concept sets alone — input order never reaches the
    result — because a candidate population that moves between runs cannot be
    the pinned input a sealed bundle claims it is.
    """

    sources = sorted(source_concepts, key=lambda concept: concept.member)
    targets = sorted(target_concepts, key=lambda concept: concept.member)
    if not sources or not targets:
        raise QualificationError("candidate generation needs concepts on both sides")
    source_releases = {concept.release for concept in sources}
    target_releases = {concept.release for concept in targets}
    if source_releases & target_releases:
        raise QualificationError("a crosswalk candidate must cross releases")

    target_by_pref: dict[str, list[AtlasConcept]] = {}
    target_by_any: dict[str, list[AtlasConcept]] = {}
    for concept in targets:
        target_by_pref.setdefault(_normalize_label(concept.pref_label), []).append(concept)
        for label in (concept.pref_label, *concept.alt_labels):
            target_by_any.setdefault(_normalize_label(label), []).append(concept)
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
        # identical pairs would seal two identical candidates the bundle then
        # refuses as duplicates.
        fresh: dict[tuple[str, str], CandidatePair] = {}
        for pair in pairs:
            if pair.key not in claimed:
                fresh.setdefault(pair.key, pair)
        drawn = _draw(tuple(fresh.values()), int(limits.get(label, 0)), seed=seed, label=label)
        claimed.update(pair.key for pair in drawn)
        selected.extend(drawn)
        return drawn

    # 1. The easy diagonal: equal normalized preferred labels.
    equality: list[CandidatePair] = []
    for concept in sources:
        normalized = _normalize_label(concept.pref_label)
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
            normalized = _normalize_label(label)
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
        (concept, _normalize_label(concept.pref_label), normalized_tokens(concept.pref_label))
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
        normalized = _normalize_label(concept.pref_label)
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
    #    judge that pattern-matches on topic instead of identity says yes.
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

    # 6. Random pairs with no shared token: the floor the gate must refuse.
    controls: list[CandidatePair] = []
    rng = random.Random(f"{seed}:randomNegativeControl:population")
    wanted = int(limits.get("randomNegativeControl", 0))
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
    return tuple(sorted(selected, key=lambda pair: (order[pair.generation_class], pair.key)))


def stratified_subset(
    rows: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    class_key: str = "generationClass",
) -> list[Mapping[str, Any]]:
    """Take ``limit`` rows spread across classes, never the first ``limit``.

    ``candidates.json`` is written in class order, so a head slice of a
    partial run is pure label equality — exactly the rubber-stamped slice the
    six-class design exists to prevent.  A short run must still be able to
    refuse something, so the subset takes one row from each class in turn
    until it is full.
    """

    if limit < 0:
        raise QualificationError("a candidate subset needs a nonnegative limit")
    buckets: dict[str, list[Mapping[str, Any]]] = {name: [] for name in GENERATION_CLASSES}
    for row in rows:
        buckets.setdefault(str(row[class_key]), []).append(row)
    order = [name for name in GENERATION_CLASSES if buckets.get(name)]
    order += [name for name in sorted(buckets) if name not in GENERATION_CLASSES and buckets[name]]
    taken: list[Mapping[str, Any]] = []
    index = 0
    while len(taken) < limit and any(len(buckets[name]) > index for name in order):
        for name in order:
            if len(taken) >= limit:
                break
            if len(buckets[name]) > index:
                taken.append(buckets[name][index])
        index += 1
    return taken


def _contains_token_run(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    if not needle or len(needle) >= len(haystack):
        return False
    return any(
        tuple(haystack[index : index + len(needle)]) == tuple(needle)
        for index in range(len(haystack) - len(needle) + 1)
    )


# ---------------------------------------------------------------------------
# the sealed model input
# ---------------------------------------------------------------------------


def _concept_payload(concept: AtlasConcept) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "member": concept.member,
        "prefLabel": concept.pref_label,
        "release": concept.release,
    }
    if concept.alt_labels:
        payload["altLabels"] = list(concept.alt_labels)
    if concept.definition:
        payload["definition"] = concept.definition
    if concept.scope_note:
        payload["scopeNote"] = concept.scope_note
    if concept.vocabulary:
        payload["vocabulary"] = concept.vocabulary
    return payload


def task_id(pair: CandidatePair) -> str:
    """An opaque per-pair token the machine must echo back.

    Neither the candidate identifier nor ``inputContextDigest`` can serve here:
    both are derived from these very bytes, so putting either inside them is
    circular.  This token is derived from the two member IRIs alone, which is
    exactly the fact an echo needs to prove — that the answer is about *this*
    pair.  The pilot exists partly because one judge family has a receipted
    history of answering with transposed identifiers.
    """

    seed = pair.source.member + "|" + pair.target.member
    return "task-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def model_input_payload(pair: CandidatePair, *, protocol: str = PROTOCOL) -> dict[str, Any]:
    """Everything the machine sees about one pair.

    Note what is absent: the generation class, the evidence that proposed the
    pair, and any hint of which side the generator expects to win.  The judge
    reads two concepts.

    ``proposedRelation`` stays off the input.  The adopted protocol asks which
    relation holds, so showing the generator's ``closeMatch`` hypothesis would
    bias the one axis the qualification is meant to measure.  The sealed
    candidate still records that hypothesis.
    """

    require_protocol_v2(protocol)
    return {
        "source": _concept_payload(pair.source),
        "target": _concept_payload(pair.target),
        "taskId": task_id(pair),
    }


def model_input_texts(pair: CandidatePair, *, protocol: str = PROTOCOL) -> tuple[str, str]:
    """Return the exact ``(system, user)`` strings sent to every family."""

    require_protocol_v2(protocol)
    return instructions_text(), canonical_json(model_input_payload(pair, protocol=protocol))


def input_context_artifact(pair: CandidatePair, *, protocol: str = PROTOCOL) -> CrosswalkArtifact:
    """Seal the model-input bytes so the bundle's closure check can resolve them.

    These are the bytes the binding calls "the exact model input".  The
    protocol value is checked before any bytes are sealed.
    """

    system, _ = model_input_texts(pair, protocol=protocol)
    return CrosswalkArtifact.create(
        role="inputContext",
        media_type="application/json",
        content={
            "instructions": system,
            "payload": model_input_payload(pair, protocol=protocol),
            "protocol": MODEL_INPUT_PROTOCOL,
        },
    )


def evidence_artifact(pair: CandidatePair) -> CrosswalkArtifact:
    """Seal why the generator proposed this pair — never shown to the judge."""

    return CrosswalkArtifact.create(
        role="evidence",
        media_type="application/json",
        content={
            "generationClass": pair.generation_class,
            "generationPolicy": CANDIDATE_GENERATION_POLICY,
            **dict(pair.evidence),
        },
    )


def validation_request_artifact(
    candidate: MappingCandidate,
    input_digest: str,
    *,
    protocol: str = PROTOCOL,
) -> CrosswalkArtifact:
    """One request per candidate, shared by both families.

    The gate groups a candidate's validations by ``(sealed input, request)``
    before it looks for an independent pair, so two machines that answered
    different requests are two answers to two questions, not a corroboration.
    """

    require_protocol_v2(protocol)
    return CrosswalkArtifact.create(
        role="validationRequest",
        media_type="application/json",
        content={
            "candidate": candidate.reference(),
            "inputDigest": input_digest,
            "protocol": VALIDATION_REQUEST_PROTOCOL,
        },
    )


# ---------------------------------------------------------------------------
# validator families
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidatorFamily:
    """One independent machine family and its pinned wire configuration."""

    name: str
    vendor: str
    independence_group: str
    base_url: str
    api_key_env: str
    requested_model: str
    assumed_input_usd_per_mtok: float
    assumed_output_usd_per_mtok: float
    spend_cap_usd: float
    max_output_tokens_field: str
    supports_temperature: bool
    supports_seed: bool
    reasoning_effort: str | None = "low"
    max_output_tokens: int = 2000
    timeout_seconds: float = 180.0

    @property
    def validator_actor(self) -> str:
        return f"urn:ref:actor:atlas-crosswalk-validator:{self.name}"

    @property
    def independence_group_iri(self) -> str:
        return f"urn:ref:independence-group:{self.independence_group}"

    @property
    def provider_iri(self) -> str:
        return f"urn:ref:provider:{self.vendor}"


#: Prices are pinned assumptions, recorded in every receipt next to the exact
#: token counts the provider reported.  The counts are the durable fact; the
#: prices let a reader recompute the bill if a published price moves.
GEMINI_FAMILY = ValidatorFamily(
    name="gemini",
    vendor="google",
    independence_group="google-gemini",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key_env="GEMINI_API_KEY",
    requested_model="gemini-3.6-flash",
    assumed_input_usd_per_mtok=0.50,
    assumed_output_usd_per_mtok=3.00,
    spend_cap_usd=6.0,
    max_output_tokens_field="max_tokens",
    supports_temperature=True,
    supports_seed=False,
)

#: ``gpt-5.6-terra`` rejects ``temperature`` outright — receipted across the
#: whole search holdout exam — so it is never sent, and the seed carries
#: whatever determinism the provider offers instead.
OPENAI_FAMILY = ValidatorFamily(
    name="openai",
    vendor="openai",
    independence_group="openai",
    base_url="https://api.openai.com/v1/",
    api_key_env="OPENAI_API_KEY",
    requested_model="gpt-5.6-terra",
    assumed_input_usd_per_mtok=2.50,
    assumed_output_usd_per_mtok=10.00,
    spend_cap_usd=14.0,
    max_output_tokens_field="max_completion_tokens",
    supports_temperature=False,
    supports_seed=True,
)

VALIDATOR_FAMILIES: Mapping[str, ValidatorFamily] = {
    GEMINI_FAMILY.name: GEMINI_FAMILY,
    OPENAI_FAMILY.name: OPENAI_FAMILY,
}

#: Hard ceiling for one whole run, across both families.
TOTAL_SPEND_CAP_USD = 20.0

VALIDATION_CALL_SEED = 20260802


# ---------------------------------------------------------------------------
# transport, credentials, and spend
# ---------------------------------------------------------------------------


class HttpTransport(Protocol):
    """Injected transport: tests script it, the run uses urllib."""

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]: ...


class UrllibTransport:
    """Stdlib HTTPS transport; no new dependency enters RefSpec."""

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as error:
            return int(error.code), error.read()


def load_env_value(env_path: Path | str, name: str) -> str:
    """Read one value from a dotenv file without ever returning it empty."""

    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() != name:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            return cleaned
        break
    raise QualificationError(f"{name} is not set in {env_path}")


def scrubbed_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Redact credential-bearing headers; a receipt never carries a secret."""

    redacted = {"authorization", "x-goog-api-key", "api-key"}
    return {key: ("<redacted>" if key.lower() in redacted else value) for key, value in headers.items()}


@dataclass
class SpendTracker:
    """Enforce one family's hard cap against assumed pricing and exact tokens."""

    family: ValidatorFamily
    cap_usd: float | None = None
    calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    assumed_cost_usd: float = 0.0
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def cap(self) -> float:
        return self.family.spend_cap_usd if self.cap_usd is None else self.cap_usd

    def check_before_call(self, estimated_input_tokens: int, estimated_output_tokens: int) -> None:
        with self._lock:
            projected = self.assumed_cost_usd + self.cost(estimated_input_tokens, estimated_output_tokens)
            if projected > self.cap:
                raise SpendCapReached(
                    f"{self.family.name}: projected assumed spend ${projected:.4f} exceeds the "
                    f"${self.cap:.2f} cap after {self.calls} calls"
                )

    def record(self, input_tokens: int, output_tokens: int, *, failed: bool = False) -> None:
        with self._lock:
            self.calls += 1
            self.failed_calls += int(failed)
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.assumed_cost_usd += self.cost(input_tokens, output_tokens)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.family.assumed_input_usd_per_mtok
            + output_tokens * self.family.assumed_output_usd_per_mtok
        ) / 1_000_000

    def summary(self) -> dict[str, Any]:
        return {
            "assumed_cost_usd": round(self.assumed_cost_usd, 6),
            "assumed_pricing_usd_per_mtok": {
                "input": self.family.assumed_input_usd_per_mtok,
                "output": self.family.assumed_output_usd_per_mtok,
            },
            "calls": self.calls,
            "failed_calls": self.failed_calls,
            "family": self.family.name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "spend_cap_usd": self.cap,
        }


def _utcnow() -> str:
    return _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def list_models(
    transport: HttpTransport,
    family: ValidatorFamily,
    api_key: str,
) -> tuple[list[str], dict[str, Any]]:
    """Fetch the live model list; the receipt carries the response verbatim."""

    url = family.base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    started = _utcnow()
    status, body = transport.request("GET", url, headers, None, family.timeout_seconds)
    receipt: dict[str, Any] = {
        "family": family.name,
        "finished_at": _utcnow(),
        "kind": "models_list",
        "outcome": "completed" if status == 200 else "provider_error",
        "request_headers": scrubbed_headers(headers),
        "request_url": url,
        "response_status": status,
        "started_at": started,
        "vendor": family.vendor,
    }
    if status != 200:
        receipt["response_bytes"] = body.decode("utf-8", errors="replace")[:2000]
        return [], receipt
    try:
        payload = json.loads(body)
        ids = [str(item["id"]) for item in payload.get("data", []) if isinstance(item, Mapping) and "id" in item]
    except (json.JSONDecodeError, TypeError, AttributeError):
        receipt["outcome"] = "unparseable_models_list"
        return [], receipt
    receipt["model_count"] = len(ids)
    return ids, receipt


def resolve_validator_model(family: ValidatorFamily, model_ids: Sequence[str]) -> tuple[str, str]:
    """Resolve the pinned model against the live list, or refuse.

    Never substitutes silently.  "Which model ran" is the one fact a
    qualification receipt may not guess.
    """

    def _bare(model_id: str) -> str:
        return model_id.removeprefix("models/")

    requested = family.requested_model
    exact = [model_id for model_id in model_ids if _bare(model_id) == requested]
    if exact:
        return min(exact), "exact_match"
    dated = sorted(model_id for model_id in model_ids if _bare(model_id).startswith(requested + "-"))
    if dated:
        return dated[-1], "latest_dated_variant"
    stem = requested.split("-")[0]
    near = sorted(model_id for model_id in model_ids if stem in model_id or requested[:8] in model_id)
    raise FamilyUnavailableError(
        f"{family.name}: pinned model {requested!r} is absent from the live models list; near matches: {near[:20]}",
        near,
    )


# ---------------------------------------------------------------------------
# one call
# ---------------------------------------------------------------------------

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

#: A dropped socket is not an answer, so it is re-sent once. More than once
#: would start hiding a systematically failing endpoint behind a retry loop.
TRANSPORT_RETRY_LIMIT = 1

#: A 429 or 5xx is the provider declining to answer. Backed off and re-sent a
#: few times, because a rate limit says "later", not "no".
DECLINED_RETRY_LIMIT = 3


def _request_body(
    family: ValidatorFamily,
    model_id: str,
    system_text: str,
    user_text: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "messages": [
            {"content": system_text, "role": "system"},
            {"content": user_text, "role": "user"},
        ],
        "model": model_id,
        family.max_output_tokens_field: family.max_output_tokens,
    }
    if family.supports_temperature:
        body["temperature"] = 0
    if family.supports_seed:
        body["seed"] = VALIDATION_CALL_SEED
    if family.reasoning_effort is not None:
        body["reasoning_effort"] = family.reasoning_effort
    return body


def _parse_answer(content: str, *, protocol: str = PROTOCOL) -> dict[str, Any] | None:
    require_protocol_v2(protocol)
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if Draft202012Validator(dict(RESPONSE_SCHEMA)).is_valid(parsed):
        return parsed
    # A verdict the enum admits is still a usable machine answer; whatever else
    # is wrong with the object is what deterministicChecksPassed records.
    if isinstance(parsed.get("verdict"), str) and parsed["verdict"] in VERDICTS:
        return parsed
    return None


def validate_candidate(
    transport: HttpTransport,
    family: ValidatorFamily,
    api_key: str,
    model_id: str,
    *,
    pair: CandidatePair,
    candidate_id: str,
    input_digest: str,
    tracker: SpendTracker,
    retry_sleep: Callable[[float], None] = time.sleep,
    protocol: str = PROTOCOL,
) -> dict[str, Any]:
    """Ask one family about one candidate, once, and receipt whatever happens.

    The question is asked once.  Three things are not a second asking, and
    each is counted separately so a receipt says which happened:

    * a dropped socket is not an answer — retried once;
    * a 429 or 5xx is the provider declining to answer — retried with backoff;
    * a parameter the endpoint refuses (``gpt-5.6-terra`` rejects
      ``temperature``) is a request-shape correction — dropped and re-sent.

    An answer is never asked for again because the first one disagreed.
    """

    require_protocol_v2(protocol)
    system_text, user_text = model_input_texts(pair, protocol=protocol)
    body = _request_body(family, model_id, system_text, user_text)
    estimated_input = _estimate_tokens(system_text) + _estimate_tokens(user_text)
    tracker.check_before_call(estimated_input, family.max_output_tokens)
    url = family.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    receipt: dict[str, Any] = {
        "candidate_id": candidate_id,
        "family": family.name,
        "generation_class": pair.generation_class,
        "independence_group": family.independence_group,
        "input_digest": input_digest,
        "kind": "crosswalk_validation",
        "model_id": model_id,
        "protocol": protocol,
        "model_requested": family.requested_model,
        "request_headers": scrubbed_headers(headers),
        "request_url": url,
        "source_member": pair.source.member,
        "started_at": _utcnow(),
        "structured_mode": "prompted",
        "target_member": pair.target.member,
        "task_id": task_id(pair),
        "vendor": family.vendor,
    }
    attempts = 0
    transport_retries = 0
    declined_retries = 0
    dropped: list[str] = []
    while True:
        attempts += 1
        request_bytes = canonical_json(body).encode("utf-8")
        receipt["request_sha256"] = _sha256_text(canonical_json(body))
        try:
            status, response_bytes = transport.request("POST", url, headers, request_bytes, family.timeout_seconds)
        except Exception as error:  # noqa: BLE001 - a provider failure is data, not a crash
            if transport_retries < TRANSPORT_RETRY_LIMIT:
                transport_retries += 1
                retry_sleep(2.0)
                continue
            receipt.update(
                {
                    "attempts": attempts,
                    "declined_retries": declined_retries,
                    "dropped_parameters": dropped,
                    "error_code": type(error).__name__,
                    "finished_at": _utcnow(),
                    "outcome": "transport_error",
                    "response_status": None,
                    "transport_retries": transport_retries,
                }
            )
            tracker.record(0, 0, failed=True)
            return receipt
        response_text = response_bytes.decode("utf-8", errors="replace")
        if status == 400 and len(dropped) < 3:
            removed = _drop_refused_parameter(body, response_text)
            if removed is not None:
                dropped.append(removed)
                continue
        if status in _RETRYABLE_STATUSES and declined_retries < DECLINED_RETRY_LIMIT:
            declined_retries += 1
            retry_sleep(min(60.0, 10.0 * 2 ** (declined_retries - 1)))
            continue
        receipt.update(
            {
                "attempts": attempts,
                "declined_retries": declined_retries,
                "dropped_parameters": dropped,
                "finished_at": _utcnow(),
                "response_sha256": _sha256_text(response_text),
                "response_status": status,
                "transport_retries": transport_retries,
            }
        )
        if status != 200:
            receipt["outcome"] = "provider_error"
            receipt["response_bytes"] = response_text[:2000]
            tracker.record(0, 0, failed=True)
            return receipt
        try:
            payload = json.loads(response_text)
            content = str(payload["choices"][0]["message"]["content"])
            usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            receipt.update({"error_code": type(error).__name__, "outcome": "unparseable_response"})
            tracker.record(0, 0, failed=True)
            return receipt
        input_tokens = int((usage or {}).get("prompt_tokens") or 0)
        output_tokens = int((usage or {}).get("completion_tokens") or 0)
        tracker.record(input_tokens, output_tokens)
        receipt.update(
            {
                "assumed_cost_usd": round(tracker.cost(input_tokens, output_tokens), 6),
                "finish_reason": (payload["choices"][0] or {}).get("finish_reason"),
                "response_model": payload.get("model"),
                "usage": {"completion_tokens": output_tokens, "prompt_tokens": input_tokens},
            }
        )
        answer = _parse_answer(content, protocol=protocol)
        if answer is None:
            receipt.update({"answer_text": content[:1000], "outcome": "unusable_answer"})
            return receipt
        receipt.update({"answer": answer, "outcome": "completed"})
        return receipt


def _drop_refused_parameter(body: dict[str, Any], response_text: str) -> str | None:
    """Remove one parameter the endpoint named in its own refusal.

    The question is untouched; only a knob the endpoint will not accept goes
    away, and the receipt lists every knob dropped.
    """

    lowered = response_text.lower()
    for name in ("temperature", "reasoning_effort", "seed"):
        if name in body and name in lowered:
            body.pop(name)
            return name
    return None


# ---------------------------------------------------------------------------
# receipt -> validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationReading:
    """One machine's answer, reduced to what the format seals."""

    family: ValidatorFamily
    provider_model_id: str
    verdict: str
    deterministic_checks_passed: bool
    completed_at: str
    response_sha256: str
    reason: str = ""
    endpoint_host: str = ""
    protocol: str = PROTOCOL

    @property
    def outcome(self) -> str:
        return VERDICT_OUTCOMES[self.verdict]


def endpoint_host(url: str) -> str:
    """The host an answer actually came from, with no credential in it.

    A URL can carry userinfo, a query string, and a path; none of that belongs
    in a sealed artifact, and any of it could carry a key. Only the host is
    kept, and it is read from the call the receipt recorded rather than from
    the family configuration — a host copied out of a configuration literal
    would be one more cosmetic string, which is precisely the thing it exists
    to give a reader evidence against.
    """

    return (urlparse(url).hostname or "").lower()


def reading_from_receipt(
    receipt: Mapping[str, Any],
    family: ValidatorFamily,
    model_id: str,
) -> ValidationReading | None:
    """Turn one completed call into a validation, or nothing at all.

    A failed call yields nothing.  Recording it as an abstention would invent a
    machine opinion out of a dropped connection; the candidate simply keeps
    fewer than two validations and stays ineligible.
    """

    if receipt.get("outcome") != "completed":
        return None
    answer = receipt.get("answer")
    if not isinstance(answer, Mapping):
        return None
    protocol = str(receipt.get("protocol") or "")
    require_protocol_v2(protocol)
    verdict = str(answer.get("verdict", ""))
    if verdict not in VERDICTS:
        return None
    schema_valid = Draft202012Validator(dict(RESPONSE_SCHEMA)).is_valid(dict(answer))
    deterministic = schema_valid and str(answer.get("task_id")) == str(receipt.get("task_id"))
    return ValidationReading(
        family=family,
        provider_model_id=model_id,
        verdict=verdict,
        deterministic_checks_passed=bool(deterministic),
        completed_at=str(receipt.get("finished_at") or _utcnow()),
        response_sha256=str(receipt.get("response_sha256") or ""),
        reason=str(answer.get("reason", "")),
        endpoint_host=endpoint_host(str(receipt.get("request_url") or "")),
        protocol=protocol,
    )


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssembledCandidate:
    """One candidate with every artifact and validation the bundle needs."""

    pair: CandidatePair
    candidate: MappingCandidate
    artifacts: tuple[CrosswalkArtifact, ...]
    validations: tuple[MachineValidation, ...]


def assemble_candidate(
    pair: CandidatePair,
    *,
    generated_at: str,
    readings: Sequence[ValidationReading],
    protocol: str = PROTOCOL,
) -> AssembledCandidate:
    """Seal one candidate and whichever machine answers came back.

    At most one reading per family: k is 1 and the two families ARE the
    redundancy, so a second answer from one family is the same machine asked
    twice and must never look like corroboration.

    The adopted protocol seals the candidate's rubric and payload.  Supplying a
    different value is an error rather than a compatibility request.
    """

    groups = [reading.family.independence_group for reading in readings]
    if len(set(groups)) != len(groups):
        raise QualificationError("a candidate takes at most one validation per independence group")
    require_protocol_v2(protocol)
    protocols = {require_protocol_v2(reading.protocol) for reading in readings}
    if protocols and protocols != {protocol}:
        raise QualificationError("candidate protocol disagrees with its readings")

    context = input_context_artifact(pair, protocol=protocol)
    evidence = evidence_artifact(pair)
    candidate = MappingCandidate.create(
        source_member=pair.source.member,
        source_release=pair.source.release,
        target_member=pair.target.member,
        target_release=pair.target.release,
        proposed_relation=PROPOSED_RELATION,
        generator_kind="aiModel",
        generator_actor=GENERATOR_ACTOR,
        generator_provider=GENERATOR_PROVIDER,
        model_id=GENERATOR_MODEL_ID,
        model_version=GENERATOR_MODEL_VERSION,
        prompt_template=PROMPT_TEMPLATE_IRI,
        input_context_digest=context.content_digest,
        temperature="0",
        evidence=(evidence.reference(),),
        generated_at=generated_at,
    )
    request = validation_request_artifact(candidate, context.content_digest, protocol=protocol)
    artifacts: list[CrosswalkArtifact] = [context, evidence, request]
    validations: list[MachineValidation] = []
    for reading in readings:
        response = CrosswalkArtifact.create(
            role="validationResponse",
            media_type="application/json",
            content={
                "candidate": candidate.reference(),
                "deterministicChecksPassed": reading.deterministic_checks_passed,
                # Endpoint evidence, not enforcement. The gate's five identity
                # fields are all producer-declared strings, so a bundle alone
                # cannot otherwise tell two genuinely independent machines from
                # two labels on one. This is the observed host of the call that
                # produced this answer, so a reader can at least see when two
                # "independent" validators answered from the same endpoint.
                "endpointHost": reading.endpoint_host,
                "inputDigest": context.content_digest,
                "outcome": reading.outcome,
                "provider": reading.family.provider_iri,
                "providerModelId": reading.provider_model_id,
                "reason": reading.reason,
                "requestArtifact": request.reference(),
                "responseSha256": reading.response_sha256,
                "validatorActor": reading.family.validator_actor,
                "verdict": reading.verdict,
            },
        )
        validations.append(
            MachineValidation.create(
                candidate=candidate.reference(),
                validator_kind="aiModel",
                validator_actor=reading.family.validator_actor,
                independence_group=reading.family.independence_group_iri,
                provider=reading.family.provider_iri,
                provider_model_id=reading.provider_model_id,
                sealed_input_digest=context.content_digest,
                request_artifact=request.reference(),
                response_artifact=response.reference(),
                deterministic_checks_passed=reading.deterministic_checks_passed,
                outcome=reading.outcome,  # type: ignore[arg-type]
                completed_at=reading.completed_at,
                verdict_relation=reading.verdict,
            )
        )
        artifacts.append(response)
    return AssembledCandidate(
        pair=pair,
        candidate=candidate,
        artifacts=tuple(artifacts),
        validations=tuple(validations),
    )


def crosswalk_bundle(entries: Sequence[AssembledCandidate]) -> CrosswalkBundle:
    """Assemble one sealed bundle; ``create`` refuses anything that does not close."""

    artifacts: dict[str, CrosswalkArtifact] = {}
    for entry in entries:
        for artifact in entry.artifacts:
            artifacts.setdefault(artifact.identifier, artifact)
    return CrosswalkBundle.create(
        artifacts=tuple(artifacts[key] for key in sorted(artifacts)),
        mapping_candidates=tuple(entry.candidate for entry in entries),
        machine_validations=tuple(
            validation for entry in entries for validation in entry.validations
        ),
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
    exactly one release per endpoint and the atlas checks that it holds.
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
        )
        for member_iri, member in sorted(members.items())
        if member_iri in preferred
    )


def normalize_for_report(value: str) -> str:
    """Expose the atlas normalizer for reporting without re-deriving it."""

    return unicodedata.normalize("NFKC", value).casefold()


__all__ = [
    "CANDIDATE_GENERATION_POLICY",
    "DEFAULT_CLASS_LIMITS",
    "EDIT_DISTANCE_LIMIT",
    "GEMINI_FAMILY",
    "GENERATION_CLASSES",
    "GENERATION_SEED",
    "INSTRUCTIONS",
    "INSTRUCTIONS_V2",
    "MODEL_INPUT_PROTOCOL",
    "MODEL_INPUT_PROTOCOL_V2",
    "OPENAI_FAMILY",
    "PROPOSED_RELATION",
    "PROTOCOL",
    "PROTOCOL_V2",
    "RESPONSE_SCHEMA",
    "RESPONSE_SCHEMA_V2",
    "TOTAL_SPEND_CAP_USD",
    "VALIDATION_REQUEST_PROTOCOL",
    "VALIDATOR_FAMILIES",
    "VERDICTS",
    "VERDICTS_V2",
    "VERDICT_OUTCOMES",
    "VERDICT_OUTCOMES_V2",
    "AssembledCandidate",
    "AtlasConcept",
    "CandidatePair",
    "FamilyUnavailableError",
    "HttpTransport",
    "QualificationError",
    "SpendCapReached",
    "SpendTracker",
    "UrllibTransport",
    "ValidationReading",
    "ValidatorFamily",
    "assemble_candidate",
    "concepts_from_view",
    "crosswalk_bundle",
    "endpoint_host",
    "evidence_artifact",
    "generate_candidate_pairs",
    "input_context_artifact",
    "instructions_text",
    "list_models",
    "load_env_value",
    "model_input_payload",
    "model_input_texts",
    "normalized_tokens",
    "reading_from_receipt",
    "require_protocol_v2",
    "resolve_validator_model",
    "scrubbed_headers",
    "stratified_subset",
    "task_id",
    "validate_candidate",
    "validation_request_artifact",
]

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
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from refspec.storage import canonical_json

from .candidate_retrieval import (
    CANDIDATE_GENERATION_POLICY,
    CONTROL_GENERATION_CLASSES,
    DEFAULT_CLASS_LIMITS,
    EDIT_DISTANCE_LIMIT,
    GENERATION_CLASSES,
    GENERATION_SEED,
    HIERARCHY_CONTEXT_LIMIT,
    PILOT_CANDIDATE_GENERATION_POLICY,
    PRODUCTION_CANDIDATE_GENERATION_POLICY,
    PRODUCTION_RANDOM_CONTROL_COUNT,
    AtlasConcept,
    AtlasConceptContext,
    CandidatePair,
    concepts_from_source_release,
    concepts_from_view,
    generate_candidate_pairs,
    normalized_tokens,
)
from .model import (
    CrosswalkArtifact,
    CrosswalkBundle,
    MachineValidation,
    MappingCandidate,
    VocabularyAtlasError,
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


PILOT_COVERAGE_MODE = "pilotSlice"
PRODUCTION_COVERAGE_MODE = "completeProductionCatalog"
PRODUCTION_FLOOR = "allDeterministicallyGeneratedCandidates"

QUALIFICATION_RUN_RECEIPT_VERSION = "1.0"
QUALIFICATION_RUN_RECEIPT_TYPE = "AtlasQualificationRunReceipt"

SCORING_PROTOCOL = "refspec-atlas-crosswalk-scoring-v1"
SCORER_PRIORITY_POLICY = (
    "semanticPlausibilityDescEvidenceSufficiencyDescCandidateIdAscV1"
)
SCORER_PRIORITY_PROVENANCE_TYPE = "AtlasQualificationScorerPriority"
SCORER_PRIORITY_PROVENANCE_VERSION = "1.0"
SCORING_DIRECTIONS = (
    "same",
    "near_same",
    "target_is_broader",
    "target_is_narrower",
    "related",
    "unrelated",
    "insufficient_evidence",
)

#: Uniform across every class, on purpose.  A relation chosen per class would
#: hand the judge the generator's hypothesis through the back door, and
#: ``closeMatch`` is exactly the claim the search-expansion question asks
#: about: near-same, not identical.
PROPOSED_RELATION = "http://www.w3.org/2004/02/skos/core#closeMatch"
#: Qualification has one protocol.  A second name or an implicit fallback here
#: would let candidate generation and provider execution ask different
#: questions while producing superficially valid receipts.
PROTOCOL = "v2"
MODEL_INPUT_PROTOCOL = "refspec-atlas-crosswalk-model-input-v2"
VALIDATION_REQUEST_PROTOCOL = "refspec-atlas-machine-validation-v2"
SINGLE_PROVIDER_REQUEST_PROTOCOL = "refspec-atlas-crosswalk-provider-request-single-v1"
GROUPED_PROVIDER_REQUEST_PROTOCOL = "refspec-atlas-crosswalk-grouped-request-v1"

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

SCORING_INSTRUCTIONS = """\
You score the plausibility and evidence quality of a possible relation between \
two controlled-vocabulary concepts. The score prioritizes later blind review; \
it does not prove or admit a mapping.

Read both concepts' preferred and alternate labels, definitions, scope notes, \
and bounded native parents and children. Return integer scores from 0 through \
100 for semantic_plausibility and evidence_sufficiency. likely_relation is your \
best directional classification; use insufficient_evidence when the supplied \
facts do not support a direction. Echo task_id exactly.

Return exactly one JSON object and nothing else. It must match this JSON Schema:

{schema}
"""

SCORING_RESPONSE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "task_id",
        "semantic_plausibility",
        "evidence_sufficiency",
        "likely_relation",
        "reason",
    ],
    "properties": {
        "task_id": {"type": "string"},
        "semantic_plausibility": {"type": "integer", "minimum": 0, "maximum": 100},
        "evidence_sufficiency": {"type": "integer", "minimum": 0, "maximum": 100},
        "likely_relation": {"type": "string", "enum": list(SCORING_DIRECTIONS)},
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


def scoring_instructions_text() -> str:
    """The exact scorer system text, kept separate from blind judging."""

    return SCORING_INSTRUCTIONS.replace("{schema}", canonical_json(dict(SCORING_RESPONSE_SCHEMA)))


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


def candidate_pair_from_catalog_row(payload: Mapping[str, Any]) -> CandidatePair:
    """Reconstruct the exact candidate input represented by one catalog row."""

    def context(value: Mapping[str, Any]) -> AtlasConceptContext:
        return AtlasConceptContext(
            member=str(value["member"]),
            pref_label=str(value["prefLabel"]),
            alt_labels=tuple(value.get("altLabels", ())),
            definition=value.get("definition"),
            scope_note=value.get("scopeNote"),
        )

    def concept(value: Mapping[str, Any]) -> AtlasConcept:
        return AtlasConcept(
            member=str(value["member"]),
            release=str(value["release"]),
            pref_label=str(value["prefLabel"]),
            alt_labels=tuple(value.get("altLabels", ())),
            definition=value.get("definition"),
            scope_note=value.get("scopeNote"),
            broader=tuple(value.get("broader", ())),
            vocabulary=str(value.get("vocabulary", "")),
            parents=tuple(context(item) for item in value.get("parents", ())),
            children=tuple(context(item) for item in value.get("children", ())),
        )

    source = payload.get("source")
    target = payload.get("target")
    evidence = payload.get("evidence")
    if not isinstance(source, Mapping) or not isinstance(target, Mapping):
        raise QualificationError("candidate catalog row has invalid endpoint concepts")
    if not isinstance(evidence, Mapping):
        raise QualificationError("candidate catalog row has invalid generation evidence")
    return CandidatePair(
        source=concept(source),
        target=concept(target),
        generation_class=str(payload.get("generationClass") or ""),
        evidence=dict(evidence),
        generation_policy=str(
            payload.get("generationPolicy") or CANDIDATE_GENERATION_POLICY
        ),
    )


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


# ---------------------------------------------------------------------------
# the sealed model input
# ---------------------------------------------------------------------------


def _context_payload(concept: AtlasConceptContext) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "member": concept.member,
        "prefLabel": concept.pref_label,
    }
    if concept.alt_labels:
        payload["altLabels"] = list(concept.alt_labels)
    if concept.definition:
        payload["definition"] = concept.definition
    if concept.scope_note:
        payload["scopeNote"] = concept.scope_note
    return payload


def _concept_payload(
    concept: AtlasConcept,
    *,
    include_native_hierarchy: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "member": concept.member,
        "prefLabel": concept.pref_label,
        "release": concept.release,
    }
    if include_native_hierarchy:
        # Production questions always carry both arrays, including when a
        # source has no native hierarchy. This balanced shape gives direction
        # judgments the same evidence without naming the generator's rule.
        payload["nativeHierarchy"] = {
            "parents": [_context_payload(value) for value in concept.parents[:HIERARCHY_CONTEXT_LIMIT]],
            "children": [_context_payload(value) for value in concept.children[:HIERARCHY_CONTEXT_LIMIT]],
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


def scoring_task_id(pair: CandidatePair) -> str:
    """An opaque scorer echo token distinct from the blind judge token."""

    seed = "scoring|" + pair.source.member + "|" + pair.target.member
    return "score-task-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


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
    hierarchy_aware = pair.generation_policy == PRODUCTION_CANDIDATE_GENERATION_POLICY
    return {
        "source": _concept_payload(
            pair.source,
            include_native_hierarchy=hierarchy_aware,
        ),
        "target": _concept_payload(
            pair.target,
            include_native_hierarchy=hierarchy_aware,
        ),
        "taskId": task_id(pair),
    }


def model_input_texts(pair: CandidatePair, *, protocol: str = PROTOCOL) -> tuple[str, str]:
    """Return the exact ``(system, user)`` strings sent to every family."""

    require_protocol_v2(protocol)
    return instructions_text(), canonical_json(model_input_payload(pair, protocol=protocol))


def scoring_input_payload(pair: CandidatePair) -> dict[str, Any]:
    """Concept evidence shown to the scorer, without generator/control facts."""

    hierarchy_aware = pair.generation_policy == PRODUCTION_CANDIDATE_GENERATION_POLICY
    return {
        "source": _concept_payload(
            pair.source,
            include_native_hierarchy=hierarchy_aware,
        ),
        "target": _concept_payload(
            pair.target,
            include_native_hierarchy=hierarchy_aware,
        ),
        "taskId": scoring_task_id(pair),
    }


def scoring_input_texts(pair: CandidatePair) -> tuple[str, str]:
    """Return the exact scorer ``(system, user)`` strings."""

    return scoring_instructions_text(), canonical_json(scoring_input_payload(pair))


def scoring_input_digest(pair: CandidatePair) -> str:
    """Pin the exact scorer question independently from judge input bytes."""

    system, user = scoring_input_texts(pair)
    return _sha256_text(canonical_json({"instructions": system, "payload": json.loads(user), "protocol": SCORING_PROTOCOL}))


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
            "generationPolicy": pair.generation_policy,
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


#: Standard-list prices are pinned assumptions, recorded in every receipt next
#: to the exact token counts the provider reported.  The provider Batch API's
#: 50% factor is applied separately in ``qualification_batch``.  Counts are the
#: durable fact; keeping these numbers explicit makes later price drift
#: auditable instead of silently changing historical receipts.
GEMINI_FAMILY = ValidatorFamily(
    name="gemini",
    vendor="google",
    independence_group="google-gemini",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key_env="GEMINI_API_KEY",
    requested_model="gemini-3.6-flash",
    assumed_input_usd_per_mtok=1.50,
    assumed_output_usd_per_mtok=7.50,
    spend_cap_usd=6.0,
    max_output_tokens_field="max_tokens",
    supports_temperature=True,
    supports_seed=False,
)

#: ``gpt-5.6-terra`` rejects ``temperature`` outright — receipted across the
#: whole search holdout exam — so it is never sent, and the seed carries
#: whatever determinism the provider offers instead. After the Batch factor,
#: the pinned OpenAI assumptions become $1.25/M input and $7.50/M output.
#: ``qualification_batch.GROUP_INPUT_TOKEN_LIMIT`` keeps grouped inputs at
#: 60,000 tokens, so those assumptions conservatively cover the official
#: short-context Terra Batch cache-write rate ($1.25/M) and output rate ($6/M).
OPENAI_FAMILY = ValidatorFamily(
    name="openai",
    vendor="openai",
    independence_group="openai",
    base_url="https://api.openai.com/v1/",
    api_key_env="OPENAI_API_KEY",
    requested_model="gpt-5.6-terra",
    assumed_input_usd_per_mtok=2.50,
    assumed_output_usd_per_mtok=15.00,
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

#: Gemini 3.6 accepts the OpenAI-compatible message shape while managing its
#: own generation policy.  These legacy sampling knobs are removed before the
#: request is hashed, receipted, or uploaded.  Keeping the scrub at the common
#: request builder gives serial and Batch execution the same sealed bytes.
GEMINI_36_DEPRECATED_GENERATION_CONTROLS = frozenset(
    {"temperature", "top_p", "top_k"}
)


def _uses_gemini_36(family: ValidatorFamily, model_id: str) -> bool:
    return (
        family.vendor == "google"
        and model_id.removeprefix("models/").startswith("gemini-3.6")
    )


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
    if _uses_gemini_36(family, model_id):
        for parameter in GEMINI_36_DEPRECATED_GENERATION_CONTROLS:
            body.pop(parameter, None)
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


def _parse_scoring_answer(content: str) -> dict[str, Any] | None:
    """Parse one scorer answer against the sealed scoring schema."""

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
    return parsed if Draft202012Validator(dict(SCORING_RESPONSE_SCHEMA)).is_valid(parsed) else None


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


def score_candidate(
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
) -> dict[str, Any]:
    """Score one candidate once, using the validation path's call discipline."""

    system_text, user_text = scoring_input_texts(pair)
    body = _request_body(family, model_id, system_text, user_text)
    estimated_input = _estimate_tokens(system_text) + _estimate_tokens(user_text)
    tracker.check_before_call(estimated_input, family.max_output_tokens)
    url = family.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    receipt: dict[str, Any] = {
        "candidate_id": candidate_id,
        "family": family.name,
        "generation_class": pair.generation_class,
        "input_digest": input_digest,
        "kind": "crosswalk_scoring",
        "model_id": model_id,
        "protocol": SCORING_PROTOCOL,
        "model_requested": family.requested_model,
        "request_headers": scrubbed_headers(headers),
        "request_url": url,
        "source_member": pair.source.member,
        "started_at": _utcnow(),
        "structured_mode": "prompted",
        "target_member": pair.target.member,
        "task_id": scoring_task_id(pair),
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
            status, response_bytes = transport.request(
                "POST", url, headers, request_bytes, family.timeout_seconds
            )
        except Exception as error:  # noqa: BLE001 - provider failure is receipted evidence
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
        answer = _parse_scoring_answer(content)
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
    provider_request_kind: str = "serialEquivalent"
    provider_request_protocol: str = SINGLE_PROVIDER_REQUEST_PROTOCOL
    request_sha256: str = ""
    group_id: str = ""
    item_input_sha256: str = ""
    group_response_sha256: str = ""
    answer_sha256: str = ""

    @property
    def outcome(self) -> str:
        return VERDICT_OUTCOMES[self.verdict]


@dataclass(frozen=True, slots=True)
class ScoreReading:
    """One scorer answer reduced to the facts used for ranking and accounting."""

    family: ValidatorFamily
    provider_model_id: str
    semantic_plausibility: int
    evidence_sufficiency: int
    likely_relation: str
    deterministic_checks_passed: bool
    completed_at: str
    response_sha256: str
    reason: str = ""
    endpoint_host: str = ""
    protocol: str = SCORING_PROTOCOL
    provider_request_kind: str = "serialEquivalent"
    provider_request_protocol: str = SINGLE_PROVIDER_REQUEST_PROTOCOL
    request_sha256: str = ""
    group_id: str = ""
    item_input_sha256: str = ""
    group_response_sha256: str = ""
    answer_sha256: str = ""


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


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _provider_lineage(receipt: Mapping[str, Any], answer: Mapping[str, Any]) -> tuple[bool, dict[str, str]]:
    kind = str(receipt.get("batch_request_kind") or "serialEquivalent")
    protocol = str(
        receipt.get("provider_request_protocol")
        or (
            GROUPED_PROVIDER_REQUEST_PROTOCOL
            if kind == "grouped"
            else SINGLE_PROVIDER_REQUEST_PROTOCOL
        )
    )
    lineage = {
        "answer_sha256": str(receipt.get("answer_sha256") or ""),
        "group_id": str(receipt.get("group_id") or ""),
        "group_response_sha256": str(receipt.get("group_response_sha256") or ""),
        "item_input_sha256": str(receipt.get("item_input_sha256") or ""),
        "provider_request_kind": kind,
        "provider_request_protocol": protocol,
        "request_sha256": str(receipt.get("request_sha256") or ""),
    }
    valid = _is_sha256(lineage["request_sha256"])
    if kind == "grouped":
        valid = valid and (
            protocol == GROUPED_PROVIDER_REQUEST_PROTOCOL
            and bool(lineage["group_id"])
            and _is_sha256(lineage["item_input_sha256"])
            and _is_sha256(lineage["group_response_sha256"])
            and lineage["group_response_sha256"] == str(receipt.get("response_sha256") or "")
            and _is_sha256(lineage["answer_sha256"])
            and lineage["answer_sha256"] == _sha256_text(canonical_json(dict(answer)))
        )
    elif kind != "serialEquivalent" or protocol != SINGLE_PROVIDER_REQUEST_PROTOCOL:
        valid = False
    return bool(valid), lineage


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
    lineage_valid, lineage = _provider_lineage(receipt, answer)
    deterministic = (
        schema_valid
        and str(answer.get("task_id")) == str(receipt.get("task_id"))
        and lineage_valid
    )
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
        **lineage,
    )


def score_reading_from_receipt(
    receipt: Mapping[str, Any],
    family: ValidatorFamily,
    model_id: str,
) -> ScoreReading | None:
    """Turn one completed scoring receipt into verified score facts."""

    if receipt.get("outcome") != "completed" or receipt.get("kind") != "crosswalk_scoring":
        return None
    if receipt.get("protocol") != SCORING_PROTOCOL:
        raise QualificationError("scoring receipt uses an unsupported protocol")
    if receipt.get("family") != family.name or receipt.get("model_id") != model_id:
        raise QualificationError("scoring receipt family or model differs from its pinned scorer")
    answer = receipt.get("answer")
    if not isinstance(answer, Mapping):
        return None
    schema_valid = Draft202012Validator(dict(SCORING_RESPONSE_SCHEMA)).is_valid(dict(answer))
    if not schema_valid:
        return None
    lineage_valid, lineage = _provider_lineage(receipt, answer)
    deterministic = str(answer.get("task_id")) == str(receipt.get("task_id")) and lineage_valid
    return ScoreReading(
        family=family,
        provider_model_id=model_id,
        semantic_plausibility=int(answer["semantic_plausibility"]),
        evidence_sufficiency=int(answer["evidence_sufficiency"]),
        likely_relation=str(answer["likely_relation"]),
        deterministic_checks_passed=deterministic,
        completed_at=str(receipt.get("finished_at") or _utcnow()),
        response_sha256=str(receipt.get("response_sha256") or ""),
        reason=str(answer.get("reason", "")),
        endpoint_host=endpoint_host(str(receipt.get("request_url") or "")),
        **lineage,
    )


def scorer_priority_provenance(
    catalog: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    *,
    scorer_family: ValidatorFamily,
    scorer_model_id: str,
    candidate_catalog_file_digest: str,
    scoring_receipt_log_file_digest: str,
    scoring_sidecar_file_digest: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Reproduce the complete score-derived order used for blind judging.

    The returned record contains only digests and counts.  Score values stay in
    the sealed scorer receipt log and never enter a judge request or judge
    sidecar.  Ranking is descending semantic plausibility, then descending
    evidence sufficiency, with candidate identity as the stable tie-breaker.
    """

    for value, label in (
        (candidate_catalog_file_digest, "candidate catalog file digest"),
        (scoring_receipt_log_file_digest, "scoring receipt-log file digest"),
        (scoring_sidecar_file_digest, "scoring sidecar file digest"),
    ):
        if not _is_sha256(value):
            raise QualificationError(f"scorer priority {label} is invalid")
    if scorer_family.name not in VALIDATOR_FAMILIES:
        raise QualificationError("scorer priority names an unknown family")
    if not isinstance(scorer_model_id, str) or not scorer_model_id:
        raise QualificationError("scorer priority model id is invalid")
    raw_candidates = catalog.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(
        raw_candidates,
        (str, bytes),
    ):
        raise QualificationError("scorer priority requires candidate rows")
    candidates: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, Mapping):
            raise QualificationError(
                f"scorer priority candidate[{index}] must be an object"
            )
        candidate_id = raw.get("candidateId")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise QualificationError(
                f"scorer priority candidate[{index}] has no identity"
            )
        if candidate_id in candidates:
            raise QualificationError("scorer priority candidate catalog repeats an identity")
        candidates[candidate_id] = raw
    if catalog.get("total") != len(candidates) or not candidates:
        raise QualificationError("scorer priority candidate total is incomplete")

    readings: dict[str, ScoreReading] = {}
    vectors: list[dict[str, Any]] = []
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise QualificationError(
                f"scorer priority receipt[{index}] must be an object"
            )
        candidate_id = receipt.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in candidates:
            raise QualificationError("scorer priority receipt names an unknown candidate")
        if candidate_id in readings:
            raise QualificationError("scorer priority receipts repeat a candidate")
        row = candidates[candidate_id]
        pair = candidate_pair_from_catalog_row(row)
        expected_input_digest = str(
            row.get("scoringInputDigest") or scoring_input_digest(pair)
        )
        if (
            receipt.get("family") != scorer_family.name
            or receipt.get("model_id") != scorer_model_id
            or receipt.get("input_digest") != expected_input_digest
            or receipt.get("source_member") != pair.source.member
            or receipt.get("target_member") != pair.target.member
            or receipt.get("task_id") != scoring_task_id(pair)
        ):
            raise QualificationError(
                "scorer priority receipt differs from its exact candidate question"
            )
        reading = score_reading_from_receipt(
            receipt,
            scorer_family,
            scorer_model_id,
        )
        if reading is None or not reading.deterministic_checks_passed:
            raise QualificationError(
                "scorer priority requires one valid deterministic reading per candidate"
            )
        readings[candidate_id] = reading
        vectors.append(
            {
                "candidateId": candidate_id,
                "evidenceSufficiency": reading.evidence_sufficiency,
                "likelyRelation": reading.likely_relation,
                "semanticPlausibility": reading.semantic_plausibility,
            }
        )
    if set(readings) != set(candidates):
        missing = sorted(set(candidates) - set(readings))
        extra = sorted(set(readings) - set(candidates))
        raise QualificationError(
            "scorer priority requires complete exact coverage; "
            f"missing={missing[:5]!r}, extra={extra[:5]!r}"
        )
    ordered = tuple(
        sorted(
            readings,
            key=lambda candidate_id: (
                -readings[candidate_id].semantic_plausibility,
                -readings[candidate_id].evidence_sufficiency,
                candidate_id,
            ),
        )
    )
    vector_basis = sorted(vectors, key=lambda row: str(row["candidateId"]))
    basis = {
        "type": SCORER_PRIORITY_PROVENANCE_TYPE,
        "schemaVersion": SCORER_PRIORITY_PROVENANCE_VERSION,
        "policy": SCORER_PRIORITY_POLICY,
        "candidateCatalogFileDigest": candidate_catalog_file_digest,
        "candidateCount": len(candidates),
        "orderedCandidateIdsDigest": _sha256_text(canonical_json(list(ordered))),
        "scoreVectorDigest": _sha256_text(canonical_json(vector_basis)),
        "scorerFamily": scorer_family.name,
        "scorerModelId": scorer_model_id,
        "scoringProtocol": SCORING_PROTOCOL,
        "scoringReceiptCount": len(receipts),
        "scoringReceiptLogFileDigest": scoring_receipt_log_file_digest,
        "scoringSidecarFileDigest": scoring_sidecar_file_digest,
    }
    return (
        {
            **basis,
            "priorityDigest": _sha256_text(canonical_json(basis)),
        },
        ordered,
    )


def validate_scorer_priority_provenance(payload: object) -> dict[str, Any]:
    """Validate the compact, content-derived pin for score-prioritized judging."""

    if not isinstance(payload, Mapping):
        raise QualificationError("judging priority provenance must be an object")
    record = json.loads(canonical_json(dict(payload)))
    expected_fields = {
        "type",
        "schemaVersion",
        "policy",
        "candidateCatalogFileDigest",
        "candidateCount",
        "orderedCandidateIdsDigest",
        "priorityDigest",
        "scoreVectorDigest",
        "scorerFamily",
        "scorerModelId",
        "scoringProtocol",
        "scoringReceiptCount",
        "scoringReceiptLogFileDigest",
        "scoringSidecarFileDigest",
    }
    if set(record) != expected_fields:
        raise QualificationError("judging priority provenance fields differ")
    if (
        record.get("type") != SCORER_PRIORITY_PROVENANCE_TYPE
        or record.get("schemaVersion") != SCORER_PRIORITY_PROVENANCE_VERSION
        or record.get("policy") != SCORER_PRIORITY_POLICY
        or record.get("scoringProtocol") != SCORING_PROTOCOL
        or record.get("scorerFamily") not in VALIDATOR_FAMILIES
        or not isinstance(record.get("scorerModelId"), str)
        or not record["scorerModelId"]
        or isinstance(record.get("candidateCount"), bool)
        or not isinstance(record.get("candidateCount"), int)
        or int(record["candidateCount"]) <= 0
        or record.get("scoringReceiptCount") != record.get("candidateCount")
        or any(
            not _is_sha256(record.get(field))
            for field in (
                "candidateCatalogFileDigest",
                "orderedCandidateIdsDigest",
                "priorityDigest",
                "scoreVectorDigest",
                "scoringReceiptLogFileDigest",
                "scoringSidecarFileDigest",
            )
        )
    ):
        raise QualificationError("judging priority provenance is invalid")
    digest = record.pop("priorityDigest")
    if digest != _sha256_text(canonical_json(record)):
        raise QualificationError("judging priority provenance identity differs")
    return {**record, "priorityDigest": digest}


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
        provider_request: dict[str, Any] = {
            "kind": reading.provider_request_kind,
            "protocol": reading.provider_request_protocol,
            "requestSha256": reading.request_sha256,
            "responseSha256": reading.response_sha256,
        }
        if reading.provider_request_kind == "grouped":
            provider_request.update(
                {
                    "answerSha256": reading.answer_sha256,
                    "groupId": reading.group_id,
                    "groupResponseSha256": reading.group_response_sha256,
                    "itemInputSha256": reading.item_input_sha256,
                }
            )
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
                # ``inputDigest`` is the candidate's sealed logical question.
                # Grouped execution shows other independent rows to the model,
                # so the complete provider request is pinned separately rather
                # than calling this digest the whole prompt.
                **({"providerRequest": provider_request} if reading.request_sha256 else {}),
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
# canonical run accounting
# ---------------------------------------------------------------------------

_CANDIDATE_DISPOSITIONS = frozenset({"admitted", "controlled", "abstained", "rejected", "incomplete"})


def _run_accounting_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    identifiers: set[str] = set()
    counts = {
        "generated": len(rows),
        "scored": 0,
        "scorerReceipts": 0,
        "judgeReceipts": 0,
        "judged": 0,
        "abstained": 0,
        "rejected": 0,
        "controlled": 0,
        "admitted": 0,
        "incomplete": 0,
    }
    for index, row in enumerate(rows):
        identifier = row.get("candidateId")
        if not isinstance(identifier, str) or not identifier:
            raise QualificationError(f"candidateAccounting[{index}] has no candidateId")
        if identifier in identifiers:
            raise QualificationError("candidate accounting repeats a candidate")
        identifiers.add(identifier)
        generation_class = row.get("generationClass")
        if generation_class not in GENERATION_CLASSES:
            raise QualificationError(f"candidateAccounting[{index}] has an unsupported generation class")
        control = row.get("control")
        if control is not (generation_class in CONTROL_GENERATION_CLASSES):
            raise QualificationError(f"candidateAccounting[{index}] control status disagrees with its class")
        disposition = row.get("disposition")
        if disposition not in _CANDIDATE_DISPOSITIONS:
            raise QualificationError(f"candidateAccounting[{index}] has an unsupported disposition")
        if control is True and disposition != "controlled":
            raise QualificationError("a control candidate must remain controlled evidence")
        if control is False and disposition == "controlled":
            raise QualificationError("a non-control candidate cannot have the controlled disposition")
        relation = row.get("relation")
        if (disposition == "admitted") is not (isinstance(relation, str) and bool(relation)):
            raise QualificationError("exactly an admitted candidate must name its relation")
        receipts = row.get("judgeReceipts")
        if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
            raise QualificationError(f"candidateAccounting[{index}].judgeReceipts must be an array")
        if any(
            not isinstance(receipt, Mapping)
            or not isinstance(receipt.get("family"), str)
            or not isinstance(receipt.get("receiptDigest"), str)
            for receipt in receipts
        ):
            raise QualificationError(f"candidateAccounting[{index}] has an invalid judge receipt pin")
        if len({str(receipt["family"]) for receipt in receipts}) != len(receipts):
            raise QualificationError(f"candidateAccounting[{index}] repeats a judge family")
        scorer_receipts = row.get("scorerReceipts")
        if not isinstance(scorer_receipts, Sequence) or isinstance(scorer_receipts, (str, bytes)):
            raise QualificationError(f"candidateAccounting[{index}].scorerReceipts must be an array")
        if any(
            not isinstance(receipt, Mapping)
            or not isinstance(receipt.get("family"), str)
            or not isinstance(receipt.get("receiptDigest"), str)
            or not isinstance(receipt.get("deterministicChecksPassed"), bool)
            for receipt in scorer_receipts
        ):
            raise QualificationError(f"candidateAccounting[{index}] has an invalid scorer receipt pin")
        if len({str(receipt["family"]) for receipt in scorer_receipts}) != len(scorer_receipts):
            raise QualificationError(f"candidateAccounting[{index}] repeats a scorer family")
        scored = row.get("scored")
        judged = row.get("judged")
        if not isinstance(scored, bool) or not isinstance(judged, bool):
            raise QualificationError(f"candidateAccounting[{index}] scored and judged must be booleans")
        reproduced_scored = any(
            receipt.get("outcome") == "completed"
            and receipt.get("deterministicChecksPassed") is True
            for receipt in scorer_receipts
        )
        if scored is not reproduced_scored:
            raise QualificationError(f"candidateAccounting[{index}] scored status differs from scorer receipts")
        counts["scored"] += int(scored)
        counts["scorerReceipts"] += len(scorer_receipts)
        counts["judgeReceipts"] += len(receipts)
        counts["judged"] += int(judged)
        counts[str(disposition)] += 1
    return counts


def verify_candidate_accounting_catalog_lineage(
    candidate_accounting: object,
    catalog_candidates: object,
) -> None:
    """Tie every accounting classification to its exact candidate-catalog row."""

    def indexed(
        value: object,
        *,
        label: str,
    ) -> dict[str, Mapping[str, Any]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise QualificationError(f"{label} must be an array")
        result: dict[str, Mapping[str, Any]] = {}
        for index, raw in enumerate(value):
            if not isinstance(raw, Mapping):
                raise QualificationError(f"{label}[{index}] must be an object")
            candidate_id = raw.get("candidateId")
            generation_class = raw.get("generationClass")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise QualificationError(f"{label}[{index}] has no candidateId")
            if candidate_id in result:
                raise QualificationError(f"{label} repeats a candidate")
            if generation_class not in GENERATION_CLASSES:
                raise QualificationError(f"{label}[{index}] has an unsupported generation class")
            result[candidate_id] = raw
        return result

    accounting = indexed(candidate_accounting, label="candidate accounting")
    catalog = indexed(catalog_candidates, label="candidate catalog")
    if set(accounting) != set(catalog):
        raise QualificationError("candidate accounting and its exact catalog name different candidates")
    for candidate_id, row in accounting.items():
        generation_class = catalog[candidate_id]["generationClass"]
        if row.get("generationClass") != generation_class:
            raise QualificationError("candidate accounting generation class differs from its exact catalog row")
        expected_control = generation_class in CONTROL_GENERATION_CLASSES
        if row.get("control") is not expected_control:
            raise QualificationError("candidate accounting control status differs from its exact catalog row")
        if (row.get("disposition") == "controlled") is not expected_control:
            raise QualificationError("candidate accounting disposition differs from its exact catalog row")


def verify_production_qualification_reproduction(
    *,
    catalog: Mapping[str, Any],
    judge_receipts: Sequence[Mapping[str, Any]],
    scorer_receipts: Sequence[Mapping[str, Any]],
    bundle: CrosswalkBundle,
    candidate_accounting: Sequence[Mapping[str, Any]],
) -> None:
    """Rebuild the Crosswalk and every disposition from exact provider receipts."""

    raw_candidates = catalog.get("candidates")
    generated_at = catalog.get("generatedAt")
    protocol = catalog.get("protocol")
    if not isinstance(raw_candidates, Sequence) or isinstance(
        raw_candidates,
        (str, bytes),
    ):
        raise QualificationError("candidate catalog candidates must be an array")
    if not isinstance(generated_at, str) or not generated_at:
        raise QualificationError("candidate catalog generatedAt is invalid")
    if not isinstance(protocol, str):
        raise QualificationError("candidate catalog protocol is invalid")
    require_protocol_v2(protocol)

    candidates: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, Mapping):
            raise QualificationError(
                f"candidate catalog candidates[{index}] must be an object"
            )
        candidate_id = raw.get("candidateId")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise QualificationError(
                f"candidate catalog candidates[{index}] has no candidateId"
            )
        if candidate_id in candidates:
            raise QualificationError("candidate catalog repeats a candidate")
        candidates[candidate_id] = raw

    receipt_keys: set[tuple[str, str]] = set()
    readings_by_candidate: dict[str, list[ValidationReading]] = {
        candidate_id: [] for candidate_id in candidates
    }
    judge_pins_by_candidate: dict[str, list[dict[str, Any]]] = {
        candidate_id: [] for candidate_id in candidates
    }
    for index, receipt in enumerate(judge_receipts):
        if not isinstance(receipt, Mapping):
            raise QualificationError(f"judge receipt[{index}] must be an object")
        candidate_id = receipt.get("candidate_id")
        family_name = receipt.get("family")
        if candidate_id not in candidates or family_name not in VALIDATOR_FAMILIES:
            raise QualificationError(
                "judge receipt names an unknown candidate or validator family"
            )
        key = (str(candidate_id), str(family_name))
        if key in receipt_keys:
            raise QualificationError("judge receipts repeat a candidate and family")
        receipt_keys.add(key)
        family = VALIDATOR_FAMILIES[str(family_name)]
        reading = reading_from_receipt(
            receipt,
            family,
            str(receipt.get("model_id") or ""),
        )
        if reading is not None:
            readings_by_candidate[str(candidate_id)].append(reading)
        judge_pins_by_candidate[str(candidate_id)].append(
            {
                "family": str(family_name),
                "outcome": str(receipt.get("outcome")),
                "receiptDigest": _sha256_text(
                    canonical_json(dict(receipt)) + "\n"
                ),
            }
        )

    scorer_keys: set[tuple[str, str]] = set()
    scores_by_candidate: dict[str, list[ScoreReading]] = {
        candidate_id: [] for candidate_id in candidates
    }
    scorer_pins_by_candidate: dict[str, list[dict[str, Any]]] = {
        candidate_id: [] for candidate_id in candidates
    }
    for index, receipt in enumerate(scorer_receipts):
        if not isinstance(receipt, Mapping):
            raise QualificationError(f"scorer receipt[{index}] must be an object")
        candidate_id = receipt.get("candidate_id")
        family_name = receipt.get("family")
        if candidate_id not in candidates or family_name not in VALIDATOR_FAMILIES:
            raise QualificationError(
                "scorer receipt names an unknown candidate or validator family"
            )
        key = (str(candidate_id), str(family_name))
        if key in scorer_keys:
            raise QualificationError("scorer receipts repeat a candidate and family")
        scorer_keys.add(key)
        family = VALIDATOR_FAMILIES[str(family_name)]
        reading = score_reading_from_receipt(
            receipt,
            family,
            str(receipt.get("model_id") or ""),
        )
        if reading is not None:
            scores_by_candidate[str(candidate_id)].append(reading)
        scorer_pins_by_candidate[str(candidate_id)].append(
            {
                "family": str(family_name),
                "modelId": str(receipt.get("model_id") or ""),
                "endpoint": endpoint_host(str(receipt.get("request_url") or "")),
                "outcome": str(receipt.get("outcome")),
                "deterministicChecksPassed": bool(
                    reading is not None and reading.deterministic_checks_passed
                ),
                "requestSha256": str(receipt.get("request_sha256") or ""),
                "responseSha256": str(receipt.get("response_sha256") or ""),
                "receiptDigest": _sha256_text(
                    canonical_json(dict(receipt)) + "\n"
                ),
            }
        )

    entries: list[AssembledCandidate] = []
    for candidate_id in sorted(candidates):
        pair = candidate_pair_from_catalog_row(candidates[candidate_id])
        readings = tuple(
            sorted(
                readings_by_candidate[candidate_id],
                key=lambda reading: reading.family.name,
            )
        )
        entry = assemble_candidate(
            pair,
            generated_at=generated_at,
            readings=readings,
            protocol=protocol,
        )
        if entry.candidate.identifier != candidate_id:
            raise QualificationError(
                "candidate catalog identity does not reproduce from its exact row"
            )
        entries.append(entry)

    reproduced_bundle = crosswalk_bundle(entries)
    if reproduced_bundle.to_dict() != bundle.to_dict():
        raise QualificationError(
            "Crosswalk bundle does not reproduce from the exact catalog and judge receipts"
        )

    verify_candidate_accounting_catalog_lineage(
        candidate_accounting,
        raw_candidates,
    )
    accounting = {
        str(row["candidateId"]): row for row in candidate_accounting
    }
    relations = reproduced_bundle.adjudicated_relations()
    for candidate_id, catalog_row in candidates.items():
        generation_class = str(catalog_row["generationClass"])
        readings = readings_by_candidate[candidate_id]
        relation = relations.get(candidate_id)
        if generation_class in CONTROL_GENERATION_CLASSES:
            expected_disposition = "controlled"
        elif relation is not None:
            expected_disposition = "admitted"
        elif len(readings) < len(VALIDATOR_FAMILIES):
            expected_disposition = "incomplete"
        elif any(reading.outcome == "abstains" for reading in readings):
            expected_disposition = "abstained"
        else:
            expected_disposition = "rejected"
        row = accounting[candidate_id]
        expected_judge_pins = sorted(
            judge_pins_by_candidate[candidate_id],
            key=lambda pin: str(pin["family"]),
        )
        if row.get("judgeReceipts") != expected_judge_pins:
            raise QualificationError(
                "candidate accounting judge receipts do not reproduce from exact judge rows"
            )
        expected_judged = (
            len(readings) == len(VALIDATOR_FAMILIES)
            and all(reading.deterministic_checks_passed for reading in readings)
        )
        if row.get("judged") is not expected_judged:
            raise QualificationError(
                "candidate accounting judged status does not reproduce from exact judge rows"
            )
        expected_scorer_pins = sorted(
            scorer_pins_by_candidate[candidate_id],
            key=lambda pin: str(pin["family"]),
        )
        if row.get("scorerReceipts") != expected_scorer_pins:
            raise QualificationError(
                "candidate accounting scorer receipts do not reproduce from exact scorer rows"
            )
        expected_scored = any(
            score.deterministic_checks_passed
            for score in scores_by_candidate[candidate_id]
        )
        if row.get("scored") is not expected_scored:
            raise QualificationError(
                "candidate accounting scored status does not reproduce from exact scorer rows"
            )
        if row.get("disposition") != expected_disposition:
            raise QualificationError(
                "candidate accounting disposition does not reproduce from exact judge receipts"
            )
        if expected_disposition == "admitted" and row.get("relation") != relation:
            raise QualificationError(
                "candidate accounting relation does not reproduce from exact judge receipts"
            )


def seal_qualification_run_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Seal complete candidate-level accounting with a content-derived identity."""

    if "id" in payload or "contentDigest" in payload:
        raise QualificationError("qualification run receipt identity is content-derived")
    basis = json.loads(canonical_json(dict(payload)))
    if basis.get("type") != QUALIFICATION_RUN_RECEIPT_TYPE:
        raise QualificationError("qualification run receipt type is unsupported")
    if basis.get("schemaVersion") != QUALIFICATION_RUN_RECEIPT_VERSION:
        raise QualificationError("qualification run receipt version is unsupported")
    rows = basis.get("candidateAccounting")
    if not isinstance(rows, list):
        raise QualificationError("qualification run receipt candidateAccounting must be an array")
    expected_counts = _run_accounting_counts(rows)
    if basis.get("counts") != expected_counts:
        raise QualificationError("qualification run receipt counts do not reproduce from candidate accounting")
    catalog = basis.get("candidateCatalog")
    receipt_log = basis.get("receiptLog")
    if not isinstance(catalog, Mapping) or catalog.get("total") != expected_counts["generated"]:
        raise QualificationError("qualification candidate catalog total disagrees with its accounting")
    if not isinstance(receipt_log, Mapping) or receipt_log.get("total") != expected_counts["judgeReceipts"]:
        raise QualificationError("qualification receipt-log total disagrees with its accounting")
    scoring = basis.get("scoring")
    if not isinstance(scoring, Mapping):
        raise QualificationError("qualification run receipt scoring facts must be an object")
    scoring_log = scoring.get("receiptLog")
    if not isinstance(scoring_log, Mapping) or scoring_log.get("total") != expected_counts["scorerReceipts"]:
        raise QualificationError("scoring receipt-log total disagrees with candidate accounting")
    if expected_counts["scorerReceipts"] and not isinstance(scoring_log.get("fileDigest"), str):
        raise QualificationError("scoring receipt-log bytes must be pinned when scorer receipts exist")
    provider_batch_evidence = basis.get("providerBatchEvidence")
    if provider_batch_evidence is not None:
        if not isinstance(provider_batch_evidence, Mapping) or not provider_batch_evidence:
            raise QualificationError("provider batch evidence must be a nonempty object")
        if set(provider_batch_evidence) - {"judging", "scoring"}:
            raise QualificationError("provider batch evidence names an unsupported work kind")
        for name, raw_pin in provider_batch_evidence.items():
            if not isinstance(raw_pin, Mapping):
                raise QualificationError(f"provider batch evidence {name} must be an object")
            file_name = raw_pin.get("file")
            verification = raw_pin.get("verification")
            if (
                not isinstance(file_name, str)
                or Path(file_name).name != file_name
                or not _is_sha256(raw_pin.get("fileDigest"))
                or raw_pin.get("protocol") != "refspec-atlas-crosswalk-batch-v1"
                or not isinstance(verification, Mapping)
                or verification.get("workKind") != ("validation" if name == "judging" else "scoring")
                or any(
                    isinstance(verification.get(field), bool)
                    or not isinstance(verification.get(field), int)
                    or int(verification[field]) < 0
                    for field in ("candidateRequests", "jobs", "providerRequests")
                )
            ):
                raise QualificationError(f"provider batch evidence {name} is invalid")
    judging_priority = basis.get("judgingPriority")
    if judging_priority is not None:
        priority = validate_scorer_priority_provenance(judging_priority)
        scoring_evidence = (
            provider_batch_evidence.get("scoring")
            if isinstance(provider_batch_evidence, Mapping)
            else None
        )
        if (
            priority["candidateCount"] != expected_counts["generated"]
            or priority["scoringReceiptCount"] != expected_counts["scorerReceipts"]
            or priority["candidateCatalogFileDigest"] != catalog.get("fileDigest")
            or priority["scoringReceiptLogFileDigest"]
            != scoring_log.get("fileDigest")
            or not isinstance(scoring_evidence, Mapping)
            or priority["scoringSidecarFileDigest"]
            != scoring_evidence.get("fileDigest")
        ):
            raise QualificationError(
                "judging priority provenance differs from the run's pinned inputs"
            )
    spend_authority = basis.get("spendAuthority")
    if spend_authority is not None:
        expected_fields = {
            "approvedTotalSpendCapUsd",
            "authorityFile",
            "authorityFileDigest",
            "authorityId",
            "authorityRecordDigest",
            "batchPlanDigest",
            "batchPolicyDigest",
            "jobKey",
            "modelsByFamily",
            "runSpendCapUsd",
        }
        if not isinstance(spend_authority, Mapping) or set(spend_authority) != expected_fields:
            raise QualificationError("qualification run spend authority is invalid")
        authority_file = spend_authority.get("authorityFile")
        authority_path = PurePosixPath(str(authority_file))
        authority_digest = spend_authority.get("authorityRecordDigest")
        authority_id = spend_authority.get("authorityId")
        money = re.compile(r"^[0-9]+\.[0-9]{6}$")
        approved_total = spend_authority.get("approvedTotalSpendCapUsd")
        run_cap = spend_authority.get("runSpendCapUsd")
        models_by_family = spend_authority.get("modelsByFamily")
        if (
            not isinstance(authority_file, str)
            or authority_path.is_absolute()
            or not authority_path.parts
            or authority_path.as_posix() != authority_file
            or any(part in {"", ".", ".."} for part in authority_path.parts)
            or not _is_sha256(spend_authority.get("authorityFileDigest"))
            or not _is_sha256(authority_digest)
            or not _is_sha256(spend_authority.get("batchPlanDigest"))
            or not _is_sha256(spend_authority.get("batchPolicyDigest"))
            or not isinstance(authority_id, str)
            or authority_id
            != "urn:ref:vocabulary-atlas-v1-production-spend-authority:"
            + str(authority_digest).removeprefix("sha256:")
            or not isinstance(spend_authority.get("jobKey"), str)
            or not spend_authority["jobKey"]
            or not isinstance(models_by_family, Mapping)
            or set(models_by_family) != set(VALIDATOR_FAMILIES)
            or any(
                not isinstance(model_id, str)
                or not model_id
                or model_id != model_id.strip()
                for model_id in models_by_family.values()
            )
            or not isinstance(approved_total, str)
            or money.fullmatch(approved_total) is None
            or not isinstance(run_cap, str)
            or money.fullmatch(run_cap) is None
            or Decimal(run_cap) <= 0
            or Decimal(approved_total) < Decimal(run_cap)
        ):
            raise QualificationError("qualification run spend authority is invalid")
        if (
            basis.get("coverageMode") == PRODUCTION_COVERAGE_MODE
            and judging_priority is None
        ):
            raise QualificationError(
                "official qualification run must pin judging priority provenance"
            )
        if judging_priority is not None:
            priority = validate_scorer_priority_provenance(judging_priority)
            if (
                priority["scorerFamily"] not in models_by_family
                or priority["scorerModelId"]
                != models_by_family[priority["scorerFamily"]]
            ):
                raise QualificationError(
                    "judging priority scorer differs from the spend authority"
                )
    coverage_mode = basis.get("coverageMode")
    if coverage_mode not in {PILOT_COVERAGE_MODE, PRODUCTION_COVERAGE_MODE}:
        raise QualificationError("qualification run coverage mode is unsupported")
    if coverage_mode == PRODUCTION_COVERAGE_MODE:
        if basis.get("candidateGenerationPolicy") != PRODUCTION_CANDIDATE_GENERATION_POLICY:
            raise QualificationError("production accounting must name the production generation policy")
        if basis.get("productionFloor") != PRODUCTION_FLOOR:
            raise QualificationError("production accounting must name the complete deterministic floor")
    basis["productionReady"] = bool(
        coverage_mode == PRODUCTION_COVERAGE_MODE
        and expected_counts["scored"] == expected_counts["generated"]
        and expected_counts["judged"] == expected_counts["generated"]
        and expected_counts["incomplete"] == 0
    )
    digest = "sha256:" + hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()
    identifier = "urn:ref:atlas-qualification-run:" + digest.removeprefix("sha256:")
    return {**basis, "id": identifier, "contentDigest": digest}


def validate_qualification_run_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and reproduce one canonical qualification run receipt."""

    record = json.loads(canonical_json(dict(payload)))
    identifier = record.pop("id", None)
    digest = record.pop("contentDigest", None)
    # ``productionReady`` is derived by the sealer and therefore remains in
    # the digest basis, but a caller cannot choose a different value.
    expected_ready = record.pop("productionReady", None)
    resealed = seal_qualification_run_receipt(record)
    if identifier != resealed["id"] or digest != resealed["contentDigest"]:
        raise QualificationError("qualification run receipt identity differs from its canonical content")
    if expected_ready != resealed["productionReady"]:
        raise QualificationError("qualification run receipt productionReady differs from its accounting")
    return resealed


def normalize_for_report(value: str) -> str:
    """Expose the atlas normalizer for reporting without re-deriving it."""

    return unicodedata.normalize("NFKC", value).casefold()


__all__ = [
    "CANDIDATE_GENERATION_POLICY",
    "CONTROL_GENERATION_CLASSES",
    "DEFAULT_CLASS_LIMITS",
    "EDIT_DISTANCE_LIMIT",
    "GEMINI_FAMILY",
    "GENERATION_CLASSES",
    "GENERATION_SEED",
    "HIERARCHY_CONTEXT_LIMIT",
    "INSTRUCTIONS",
    "INSTRUCTIONS_V2",
    "MODEL_INPUT_PROTOCOL",
    "MODEL_INPUT_PROTOCOL_V2",
    "OPENAI_FAMILY",
    "PILOT_CANDIDATE_GENERATION_POLICY",
    "PILOT_COVERAGE_MODE",
    "PRODUCTION_CANDIDATE_GENERATION_POLICY",
    "PRODUCTION_COVERAGE_MODE",
    "PRODUCTION_FLOOR",
    "PRODUCTION_RANDOM_CONTROL_COUNT",
    "PROPOSED_RELATION",
    "PROTOCOL",
    "PROTOCOL_V2",
    "QUALIFICATION_RUN_RECEIPT_TYPE",
    "QUALIFICATION_RUN_RECEIPT_VERSION",
    "RESPONSE_SCHEMA",
    "RESPONSE_SCHEMA_V2",
    "SCORER_PRIORITY_POLICY",
    "SCORER_PRIORITY_PROVENANCE_TYPE",
    "SCORER_PRIORITY_PROVENANCE_VERSION",
    "SCORING_DIRECTIONS",
    "SCORING_INSTRUCTIONS",
    "SCORING_PROTOCOL",
    "SCORING_RESPONSE_SCHEMA",
    "TOTAL_SPEND_CAP_USD",
    "VALIDATION_REQUEST_PROTOCOL",
    "VALIDATOR_FAMILIES",
    "VERDICTS",
    "VERDICTS_V2",
    "VERDICT_OUTCOMES",
    "VERDICT_OUTCOMES_V2",
    "AssembledCandidate",
    "AtlasConcept",
    "AtlasConceptContext",
    "CandidatePair",
    "FamilyUnavailableError",
    "HttpTransport",
    "QualificationError",
    "ScoreReading",
    "SpendCapReached",
    "SpendTracker",
    "UrllibTransport",
    "ValidationReading",
    "ValidatorFamily",
    "assemble_candidate",
    "candidate_pair_from_catalog_row",
    "concepts_from_source_release",
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
    "score_candidate",
    "score_reading_from_receipt",
    "scorer_priority_provenance",
    "scoring_input_digest",
    "scoring_input_payload",
    "scoring_input_texts",
    "scoring_instructions_text",
    "scoring_task_id",
    "scrubbed_headers",
    "seal_qualification_run_receipt",
    "stratified_subset",
    "task_id",
    "validate_candidate",
    "validate_qualification_run_receipt",
    "validate_scorer_priority_provenance",
    "validation_request_artifact",
    "verify_candidate_accounting_catalog_lineage",
    "verify_production_qualification_reproduction",
]

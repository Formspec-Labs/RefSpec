"""The offline crosswalk qualification runner: generation, calls, and refusals.

Every test here runs offline.  The provider layer is exercised through an
injected transport, so the discipline that matters — receipts for failures,
independence across families, and a bundle that only qualifies what the gate
allows — is proven without spending anything.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from refspec.atlas import CrosswalkBundle, VocabularyAtlasError
from refspec.atlas import qualification as qual
from refspec.atlas.model import _IMPLEMENTATION_SOURCE_PATHS

GENERATED_AT = "2026-08-02T12:00:00Z"
SOURCE_RELEASE = "urn:ref:test:alpha:reference-resource-release"
TARGET_RELEASE = "urn:ref:test:beta:reference-resource-release"


def _source(member: str, label: str, **kwargs: Any) -> qual.AtlasConcept:
    return qual.AtlasConcept(member=member, release=SOURCE_RELEASE, pref_label=label, **kwargs)


def _target(member: str, label: str, **kwargs: Any) -> qual.AtlasConcept:
    return qual.AtlasConcept(member=member, release=TARGET_RELEASE, pref_label=label, **kwargs)


@pytest.fixture
def sources() -> tuple[qual.AtlasConcept, ...]:
    return (
        _source("urn:ref:test:alpha:1", "Energy policy"),
        _source("urn:ref:test:alpha:2", "Water pollution"),
        _source("urn:ref:test:alpha:3", "Labor unions", alt_labels=("Trade unions",)),
        _source("urn:ref:test:alpha:4", "Accountants"),
        _source("urn:ref:test:alpha:5", "Milk marketing orders"),
    )


@pytest.fixture
def targets() -> tuple[qual.AtlasConcept, ...]:
    return (
        _target("urn:ref:test:beta:1", "energy POLICY ", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:2", "Water pollution control", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:3", "Trade unions"),
        _target("urn:ref:test:beta:4", "Accountant"),
        _target("urn:ref:test:beta:5", "Volcanology"),
        _target("urn:ref:test:beta:6", "Air pollution control", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:9", "Pollution control"),
    )


# ---------------------------------------------------------------------------
# candidate generation
# ---------------------------------------------------------------------------


def test_generation_is_deterministic_and_order_independent(sources, targets) -> None:
    first = qual.generate_candidate_pairs(sources, targets)
    second = qual.generate_candidate_pairs(tuple(reversed(sources)), tuple(reversed(targets)))
    assert first == second
    assert first == qual.generate_candidate_pairs(sources, targets)


def test_generation_produces_every_declared_class(sources, targets) -> None:
    pairs = qual.generate_candidate_pairs(sources, targets)
    observed = {pair.generation_class for pair in pairs}
    assert observed == set(qual.GENERATION_CLASSES), sorted(observed)


def test_label_equality_uses_the_atlas_normalizer(sources, targets) -> None:
    pairs = qual.generate_candidate_pairs(sources, targets)
    equal = {
        (pair.source.member, pair.target.member)
        for pair in pairs
        if pair.generation_class == "normalizedLabelEquality"
    }
    # "Energy policy" and "energy POLICY " differ in case and trailing space.
    assert ("urn:ref:test:alpha:1", "urn:ref:test:beta:1") in equal


def test_alternate_label_equality_is_its_own_class(sources, targets) -> None:
    pairs = qual.generate_candidate_pairs(sources, targets)
    alternates = {
        (pair.source.member, pair.target.member)
        for pair in pairs
        if pair.generation_class == "alternateLabelEquality"
    }
    assert ("urn:ref:test:alpha:3", "urn:ref:test:beta:3") in alternates


def test_sibling_distractor_shares_a_parent_with_a_label_match(sources, targets) -> None:
    pairs = qual.generate_candidate_pairs(sources, targets)
    siblings = [pair for pair in pairs if pair.generation_class == "siblingDistractor"]
    assert siblings
    for pair in siblings:
        assert pair.evidence["siblingOf"] != pair.target.member


def test_negative_controls_share_no_label_token(sources, targets) -> None:
    pairs = qual.generate_candidate_pairs(sources, targets)
    controls = [pair for pair in pairs if pair.generation_class == "randomNegativeControl"]
    assert controls
    for pair in controls:
        left = set(qual.normalized_tokens(pair.source.pref_label))
        right = set(qual.normalized_tokens(pair.target.pref_label))
        assert not (left & right)


def test_no_pair_repeats_across_or_within_classes(sources, targets) -> None:
    """A repeated pair would seal two identical candidates the bundle refuses."""

    doubled = (
        *targets,
        # Same concept, reachable twice: its alternate spells its own label.
        _target("urn:ref:test:beta:10", "Accountants", alt_labels=("accountants", "ACCOUNTANTS")),
    )
    pairs = qual.generate_candidate_pairs(sources, doubled)
    keys = [(pair.source.member, pair.target.member) for pair in pairs]
    assert len(keys) == len(set(keys))
    qual.crosswalk_bundle(
        [qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=()) for pair in pairs]
    )


def test_class_limits_bound_each_class(sources, targets) -> None:
    limits = dict.fromkeys(qual.GENERATION_CLASSES, 1)
    pairs = qual.generate_candidate_pairs(sources, targets, limits=limits)
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.generation_class] = counts.get(pair.generation_class, 0) + 1
    assert max(counts.values()) == 1


def test_generation_refuses_a_source_and_target_in_one_release(sources) -> None:
    with pytest.raises(VocabularyAtlasError):
        qual.generate_candidate_pairs(sources, sources)


def test_a_short_run_still_spans_every_class(sources, targets) -> None:
    """A head slice of a class-ordered catalog is pure label equality.

    That is the rubber-stamped slice the six-class design exists to prevent:
    a run that only calls label-equal pairs cannot refuse anything.
    """

    # The real catalog's shape: every class contiguous, in class order.
    rows = [
        {"generationClass": name, "candidateId": f"{name}-{index}"}
        for name in qual.GENERATION_CLASSES
        for index in range(10)
    ]
    assert {row["generationClass"] for row in rows[:6]} == {"normalizedLabelEquality"}

    subset = qual.stratified_subset(rows, 6)
    assert len(subset) == 6
    assert {row["generationClass"] for row in subset} == set(qual.GENERATION_CLASSES)
    # Order inside a class is preserved, so a subset is still a prefix per class.
    assert [row["candidateId"] for row in qual.stratified_subset(rows, len(qual.GENERATION_CLASSES) * 2)][:2] == [
        "normalizedLabelEquality-0",
        "alternateLabelEquality-0",
    ]
    assert qual.stratified_subset(rows, 0) == []
    assert len(qual.stratified_subset(rows, 10_000)) == len(rows)
    with pytest.raises(VocabularyAtlasError):
        qual.stratified_subset(rows, -1)


# ---------------------------------------------------------------------------
# sealed input and the closure the bundle enforces
# ---------------------------------------------------------------------------


def _pair(sources, targets) -> qual.CandidatePair:
    return next(
        pair
        for pair in qual.generate_candidate_pairs(sources, targets)
        if pair.generation_class == "normalizedLabelEquality"
    )


def _reading(
    family: qual.ValidatorFamily,
    *,
    verdict: str = "near_same",
    deterministic: bool = True,
    protocol: str = qual.PROTOCOL,
) -> qual.ValidationReading:
    return qual.ValidationReading(
        family=family,
        provider_model_id=family.requested_model,
        verdict=verdict,
        deterministic_checks_passed=deterministic,
        completed_at="2026-08-02T12:05:00Z",
        response_sha256="sha256:" + "0" * 64,
        endpoint_host=qual.endpoint_host(family.base_url),
        protocol=protocol,
    )


def test_input_context_is_the_exact_model_input(sources, targets) -> None:
    pair = _pair(sources, targets)
    context = qual.input_context_artifact(pair)
    assert context.role == "inputContext"
    content = context.to_dict()["content"]
    assert content["instructions"] == qual.instructions_text()
    assert all(verdict in content["instructions"] for verdict in qual.VERDICTS)
    system_text, user_text = qual.model_input_texts(pair)
    assert system_text == content["instructions"]
    assert json.loads(user_text) == content["payload"]


def test_the_model_input_never_names_the_generation_hypothesis(sources, targets) -> None:
    """A judge told what the generator expects agrees with the generator."""

    for pair in qual.generate_candidate_pairs(sources, targets):
        system_text, user_text = qual.model_input_texts(pair)
        sealed = json.dumps(qual.input_context_artifact(pair).to_dict())
        for text in (system_text, user_text, sealed):
            assert pair.generation_class not in text
            for name in qual.GENERATION_CLASSES:
                assert name not in text
            for value in pair.evidence.values():
                if isinstance(value, str) and value not in {"1", pair.source.member, pair.target.member}:
                    assert f'"{value}"' not in user_text


def test_the_input_context_seals_the_v2_rubric(sources, targets) -> None:
    """The sealed input is the exact v2 model input."""

    pair = _pair(sources, targets)
    context = qual.input_context_artifact(pair)
    content = context.to_dict()["content"]

    assert content["protocol"] == qual.MODEL_INPUT_PROTOCOL
    assert content["instructions"] == qual.instructions_text()
    assert all(verdict in content["instructions"] for verdict in qual.VERDICTS)
    system_text, user_text = qual.model_input_texts(pair)
    assert system_text == content["instructions"]
    assert json.loads(user_text) == content["payload"]


def test_the_model_input_withholds_the_close_match_prior(sources, targets) -> None:
    """The relation question must not reveal the generator's hypothesis."""

    for pair in qual.generate_candidate_pairs(sources, targets):
        _, user = qual.model_input_texts(pair)
        assert "proposedRelation" not in json.loads(user)
        assert qual.PROPOSED_RELATION not in user
        assert qual.PROPOSED_RELATION not in json.dumps(qual.input_context_artifact(pair).to_dict())


def test_non_v2_protocol_is_not_a_supported_api_path(sources, targets) -> None:
    pair = _pair(sources, targets)
    with pytest.raises(qual.QualificationError, match="supports only 'v2'"):
        qual.model_input_texts(pair, protocol="v1")
    with pytest.raises(qual.QualificationError, match="supports only 'v2'"):
        qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=(), protocol="v1")


def test_a_candidate_refuses_a_non_v2_reading(sources, targets) -> None:
    pair = _pair(sources, targets)
    with pytest.raises(qual.QualificationError, match="supports only 'v2'"):
        qual.assemble_candidate(
            pair,
            generated_at=GENERATED_AT,
            readings=(
                _reading(qual.GEMINI_FAMILY, protocol="v1"),
                _reading(qual.OPENAI_FAMILY),
            ),
        )


def test_assembled_candidate_cites_the_bundled_input_context(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(
        pair,
        generated_at=GENERATED_AT,
        readings=(_reading(qual.GEMINI_FAMILY), _reading(qual.OPENAI_FAMILY)),
    )
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    assert entry.candidate.to_dict()["inputContextDigest"] == context.content_digest


def test_the_sealed_endpoint_host_comes_from_the_observed_call(sources, targets) -> None:
    """Endpoint evidence must be observed, not copied from configuration.

    The gate's five identity fields are all producer-declared strings, so a
    host taken from the family literal would be one more cosmetic string. This
    one is read from the URL the call actually went to.
    """

    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport([_chat_reply(_answer(pair))])
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
    )
    reading = qual.reading_from_receipt(receipt, qual.GEMINI_FAMILY, "models/gemini-3.6-flash")
    assert reading is not None
    assert reading.endpoint_host == "generativelanguage.googleapis.com"

    sealed = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=(reading,))
    response = next(item for item in sealed.artifacts if item.role == "validationResponse")
    assert response.to_dict()["content"]["endpointHost"] == "generativelanguage.googleapis.com"


def test_the_sealed_reason_preserves_the_complete_provider_answer(sources, targets) -> None:
    pair = _pair(sources, targets)
    reason = "The concepts differ because " + "supporting evidence; " * 40
    answer = {**_answer(pair), "reason": reason}
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    receipt = qual.validate_candidate(
        _StubTransport([_chat_reply(answer)]),
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
    )

    reading = qual.reading_from_receipt(receipt, qual.GEMINI_FAMILY, "models/gemini-3.6-flash")
    assert reading is not None
    assert len(reason) > 400
    assert reading.reason == reason

    sealed = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=(reading,))
    response = next(item for item in sealed.artifacts if item.role == "validationResponse")
    assert response.to_dict()["content"]["reason"] == reason


def test_the_endpoint_host_never_carries_a_credential() -> None:
    assert qual.endpoint_host("https://user:secret@api.example.com/v1/chat?key=abc") == "api.example.com"
    assert qual.endpoint_host("") == ""


def test_the_two_families_are_independent_five_ways(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(
        pair,
        generated_at=GENERATED_AT,
        readings=(_reading(qual.GEMINI_FAMILY), _reading(qual.OPENAI_FAMILY)),
    )
    first, second = (item.to_dict() for item in entry.validations)
    for field in ("validatorActor", "independenceGroup", "provider", "providerModelId", "responseArtifact"):
        assert first[field] != second[field], field


# ---------------------------------------------------------------------------
# the gate: what qualifies and what refuses
# ---------------------------------------------------------------------------


def _bundle(entries: Sequence[qual.AssembledCandidate]) -> CrosswalkBundle:
    return qual.crosswalk_bundle(entries)


def test_two_supporting_families_qualify_one_mapping(sources, targets) -> None:
    entry = qual.assemble_candidate(
        _pair(sources, targets),
        generated_at=GENERATED_AT,
        readings=(_reading(qual.GEMINI_FAMILY), _reading(qual.OPENAI_FAMILY)),
    )
    bundle = _bundle((entry,))
    assert set(bundle.qualified()) == {entry.candidate.identifier}


def test_a_single_validation_stays_not_eligible(sources, targets) -> None:
    entry = qual.assemble_candidate(
        _pair(sources, targets),
        generated_at=GENERATED_AT,
        readings=(_reading(qual.GEMINI_FAMILY),),
    )
    assert _bundle((entry,)).qualified() == {}


def test_disagreeing_families_do_not_qualify(sources, targets) -> None:
    entry = qual.assemble_candidate(
        _pair(sources, targets),
        generated_at=GENERATED_AT,
        readings=(
            _reading(qual.GEMINI_FAMILY),
            _reading(qual.OPENAI_FAMILY, verdict="unrelated"),
        ),
    )
    assert _bundle((entry,)).qualified() == {}


def test_a_failed_deterministic_check_does_not_qualify(sources, targets) -> None:
    entry = qual.assemble_candidate(
        _pair(sources, targets),
        generated_at=GENERATED_AT,
        readings=(
            _reading(qual.GEMINI_FAMILY),
            _reading(qual.OPENAI_FAMILY, deterministic=False),
        ),
    )
    bundle = _bundle((entry,))
    assert bundle.qualified() == {}
    outcomes = {item["deterministicChecksPassed"] for item in bundle.to_dict()["machineValidations"]}
    assert outcomes == {True, False}


def test_one_family_twice_never_qualifies(sources, targets) -> None:
    """Two calls to the same family are one machine, not two."""

    with pytest.raises(VocabularyAtlasError):
        qual.assemble_candidate(
            _pair(sources, targets),
            generated_at=GENERATED_AT,
            readings=(_reading(qual.GEMINI_FAMILY), _reading(qual.GEMINI_FAMILY)),
        )


def test_bundle_round_trips_through_open(tmp_path: Path, sources, targets) -> None:
    entries = [
        qual.assemble_candidate(
            pair,
            generated_at=GENERATED_AT,
            readings=(_reading(qual.GEMINI_FAMILY), _reading(qual.OPENAI_FAMILY)),
        )
        for pair in qual.generate_candidate_pairs(sources, targets)
    ]
    bundle = _bundle(entries)
    path = bundle.write(tmp_path / "crosswalk.json")
    pin = bundle.pin()
    reopened = CrosswalkBundle.open(
        path,
        expected_file_digest=pin["fileDigest"],
        expected_bundle_digest=pin["digest"],
    )
    assert reopened.to_dict() == bundle.to_dict()
    assert len(reopened.qualified()) == len(entries)


def test_abstention_is_recorded_and_does_not_qualify(sources, targets) -> None:
    entry = qual.assemble_candidate(
        _pair(sources, targets),
        generated_at=GENERATED_AT,
        readings=(
            _reading(qual.GEMINI_FAMILY, verdict="insufficient_evidence"),
            _reading(qual.OPENAI_FAMILY, verdict="insufficient_evidence"),
        ),
    )
    bundle = _bundle((entry,))
    assert bundle.qualified() == {}
    assert {item["outcome"] for item in bundle.to_dict()["machineValidations"]} == {"abstains"}


# ---------------------------------------------------------------------------
# provider layer
# ---------------------------------------------------------------------------


class _StubTransport:
    """Scripted transport: one queued reply per call, plus a call log."""

    def __init__(self, replies: Sequence[Any]) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _chat_reply(content: Mapping[str, Any], *, prompt: int = 500, completion: int = 120) -> tuple[int, bytes]:
    payload = {
        "model": "stub-model",
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }
    return 200, json.dumps(payload).encode("utf-8")


def _answer(pair: qual.CandidatePair, verdict: str = "near_same") -> dict[str, Any]:
    return {
        "task_id": qual.task_id(pair),
        "verdict": verdict,
        "reason": "the labels denote the same concept",
    }


def test_model_resolution_matches_the_live_list() -> None:
    model, rule = qual.resolve_validator_model(qual.GEMINI_FAMILY, ["models/gemini-3.6-flash", "models/other"])
    assert (model, rule) == ("models/gemini-3.6-flash", "exact_match")
    model, rule = qual.resolve_validator_model(qual.OPENAI_FAMILY, ["gpt-5.6-terra", "gpt-5.6-luna"])
    assert (model, rule) == ("gpt-5.6-terra", "exact_match")


def test_model_resolution_refuses_an_absent_model() -> None:
    with pytest.raises(qual.FamilyUnavailableError):
        qual.resolve_validator_model(qual.OPENAI_FAMILY, ["gpt-4o", "gpt-5.6-luna"])


def test_a_completed_call_receipts_both_digests(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    answer = _answer(pair)
    transport = _StubTransport([_chat_reply(answer)])
    tracker = qual.SpendTracker(qual.GEMINI_FAMILY)
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "SECRET-KEY-VALUE",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=tracker,
    )
    assert receipt["outcome"] == "completed"
    assert receipt["request_sha256"].startswith("sha256:")
    assert receipt["response_sha256"].startswith("sha256:")
    assert receipt["usage"] == {"prompt_tokens": 500, "completion_tokens": 120}
    assert receipt["assumed_cost_usd"] > 0
    assert tracker.calls == 1


def test_receipts_never_carry_the_credential(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport([_chat_reply(_answer(pair))])
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "SECRET-KEY-VALUE",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
    )
    assert "SECRET-KEY-VALUE" not in json.dumps(receipt)
    assert receipt["request_headers"]["Authorization"] == "<redacted>"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer SECRET-KEY-VALUE"


def test_a_transport_error_retries_exactly_once_and_receipts(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport([OSError("connection reset"), OSError("connection reset again")])
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
        retry_sleep=lambda _seconds: None,
    )
    assert receipt["outcome"] == "transport_error"
    assert receipt["transport_retries"] == 1
    assert len(transport.calls) == 2


def test_a_refused_parameter_is_dropped_and_the_question_is_unchanged(sources, targets) -> None:
    """``gpt-5.6-terra`` rejects ``temperature``; that is a shape fix, not a rerun."""

    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport(
        [
            (400, b'{"error":{"message":"Unsupported parameter: temperature"}}'),
            _chat_reply(_answer(pair)),
        ]
    )
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
        retry_sleep=lambda _seconds: None,
    )
    assert receipt["outcome"] == "completed"
    assert receipt["dropped_parameters"] == ["temperature"]
    first, second = (json.loads(call["body"]) for call in transport.calls)
    assert "temperature" in first
    assert "temperature" not in second
    assert first["messages"] == second["messages"]


def test_a_declined_call_backs_off_then_receipts(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport([(429, b"rate limited")] * (qual.DECLINED_RETRY_LIMIT + 1))
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
        retry_sleep=lambda _seconds: None,
    )
    assert receipt["outcome"] == "provider_error"
    assert receipt["declined_retries"] == qual.DECLINED_RETRY_LIMIT
    assert len(transport.calls) == qual.DECLINED_RETRY_LIMIT + 1


def test_a_provider_error_is_a_receipt_not_a_crash(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport([(403, b'{"error":"forbidden"}')])
    receipt = qual.validate_candidate(
        transport,
        qual.OPENAI_FAMILY,
        "key",
        "gpt-5.6-terra",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.OPENAI_FAMILY),
    )
    assert receipt["outcome"] == "provider_error"
    assert receipt["response_status"] == 403
    assert qual.reading_from_receipt(receipt, qual.OPENAI_FAMILY, "gpt-5.6-terra") is None


def test_an_unparseable_answer_yields_no_validation(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    transport = _StubTransport([_chat_reply({"nonsense": True})])
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
    )
    assert receipt["outcome"] == "unusable_answer"
    assert qual.reading_from_receipt(receipt, qual.GEMINI_FAMILY, "models/gemini-3.6-flash") is None


def test_a_transposed_candidate_id_fails_the_deterministic_check(sources, targets) -> None:
    pair = _pair(sources, targets)
    entry = qual.assemble_candidate(pair, generated_at=GENERATED_AT, readings=())
    context = next(item for item in entry.artifacts if item.role == "inputContext")
    answer = {**_answer(pair), "task_id": "task-" + "9" * 24}
    transport = _StubTransport([_chat_reply(answer)])
    receipt = qual.validate_candidate(
        transport,
        qual.GEMINI_FAMILY,
        "key",
        "models/gemini-3.6-flash",
        pair=pair,
        candidate_id=entry.candidate.identifier,
        input_digest=context.content_digest,
        tracker=qual.SpendTracker(qual.GEMINI_FAMILY),
    )
    reading = qual.reading_from_receipt(receipt, qual.GEMINI_FAMILY, "models/gemini-3.6-flash")
    assert reading is not None
    assert reading.deterministic_checks_passed is False


def test_the_spend_cap_refuses_before_the_call() -> None:
    tracker = qual.SpendTracker(qual.OPENAI_FAMILY, cap_usd=0.0001)
    with pytest.raises(qual.SpendCapReached):
        tracker.check_before_call(100_000, 100_000)


def test_env_reading_never_returns_an_empty_credential(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('GEMINI_API_KEY=""\nOPENAI_API_KEY=abc123\n', encoding="utf-8")
    assert qual.load_env_value(env, "OPENAI_API_KEY") == "abc123"
    with pytest.raises(qual.QualificationError):
        qual.load_env_value(env, "GEMINI_API_KEY")


# ---------------------------------------------------------------------------
# release adapter
# ---------------------------------------------------------------------------


class _StubExpression:
    def __init__(self, member: str, prop: str, literal: str, **kwargs: Any) -> None:
        self.member_iri = member
        self.semantic_property_iri = prop
        self.original_literal = literal
        self.language_tag = kwargs.get("language_tag", "en")
        self.label_role = kwargs.get("label_role")
        self.source_status = kwargs.get("source_status")


class _StubMember:
    def __init__(self, member: str, release: str) -> None:
        self.member_iri = member
        self.release_iri = release


class _StubRelation:
    def __init__(self, subject: str, predicate: str, obj: str) -> None:
        self.subject_member_iri = subject
        self.predicate_iri = predicate
        self.object_member_iri = obj


class _StubView:
    def __init__(self, members, expressions, relations=()) -> None:
        self._members = members
        self._expressions = expressions
        self._relations = relations

    def iter_members(self):
        return iter(self._members)

    def iter_expressions(self):
        return iter(self._expressions)

    def iter_relations(self):
        return iter(self._relations)


_PREF = "http://www.w3.org/2004/02/skos/core#prefLabel"
_ALT = "http://www.w3.org/2004/02/skos/core#altLabel"
_DEF = "http://www.w3.org/2004/02/skos/core#definition"


def test_the_adapter_keeps_both_source_status_spellings() -> None:
    """"active" and "notDeclared" are both live; only a retirement is dropped.

    The two real releases disagree: the Federal Register package writes
    "active" and ELSST writes "notDeclared".  An allow-list built from either
    one silently yields zero concepts from the other.
    """

    view = _StubView(
        members=[_StubMember("m:1", "r:1"), _StubMember("m:2", "r:1"), _StubMember("m:3", "r:1")],
        expressions=[
            _StubExpression("m:1", _PREF, "Active one", label_role="preferred", source_status="active"),
            _StubExpression("m:2", _PREF, "Undeclared one", label_role="preferred", source_status="notDeclared"),
            _StubExpression("m:3", _PREF, "Retired one", label_role="preferred", source_status="deprecated"),
        ],
    )
    assert {concept.member for concept in qual.concepts_from_view(view)} == {"m:1", "m:2"}


def test_the_adapter_selects_one_reference_release() -> None:
    view = _StubView(
        members=[_StubMember("m:5", "r:5"), _StubMember("m:6", "r:6")],
        expressions=[
            _StubExpression("m:5", _PREF, "Fifth", label_role="preferred"),
            _StubExpression("m:6", _PREF, "Sixth", label_role="preferred"),
        ],
        relations=[_StubRelation("m:6", "http://www.w3.org/2004/02/skos/core#broader", "m:5")],
    )
    selected = qual.concepts_from_view(view, release_iri="r:6")
    assert [concept.member for concept in selected] == ["m:6"]
    # The parent is in the other release, so the edge cannot follow the concept.
    assert selected[0].broader == ()


def test_the_adapter_carries_labels_definitions_and_language() -> None:
    view = _StubView(
        members=[_StubMember("m:1", "r:1")],
        expressions=[
            _StubExpression("m:1", _PREF, "PRIMARY", label_role="preferred"),
            _StubExpression("m:1", _PREF, "PRIMAIRE", label_role="preferred", language_tag="fr"),
            _StubExpression("m:1", _ALT, "Secondary", label_role="alternate"),
            _StubExpression("m:1", _DEF, "What it means."),
        ],
    )
    concept = qual.concepts_from_view(view, language="en")[0]
    assert concept.pref_label == "PRIMARY"
    assert concept.alt_labels == ("Secondary",)
    assert concept.definition == "What it means."


# ---------------------------------------------------------------------------
# the offline boundary
# ---------------------------------------------------------------------------


def test_the_runner_is_outside_the_pinned_atlas_build_closure() -> None:
    """Qualification never runs inside a build, so it never pins into one.

    The atlas manifest pins the digest of every module the build depends on.
    A qualification module listed there would make an atlas identity move
    whenever the offline runner changed, which is exactly the coupling the
    offline-tool idiom exists to prevent.
    """

    assert "atlas/qualification.py" not in _IMPLEMENTATION_SOURCE_PATHS

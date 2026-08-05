"""Exactness checks for the experimental candidate-option Batch cost planner."""

from __future__ import annotations

from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from tools import plan_atlas_candidate_batch_costs as planner


def _row(index: int, *, definition: str = "A definition.") -> qbatch.CandidateRow:
    source = qual.AtlasConcept(
        member=f"https://example.test/source/{index}",
        release="https://example.test/release/source",
        pref_label=f"Source {index}",
        definition=definition,
    )
    target = qual.AtlasConcept(
        member=f"https://example.test/target/{index}",
        release="https://example.test/release/target",
        pref_label=f"Target {index}",
        definition=definition,
    )
    pair = qual.CandidatePair(
        source,
        target,
        "experimentalRelationCandidate",
        {"method": "test"},
        qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
    )
    return qbatch.CandidateRow(f"proposal-{index:04d}", pair, f"sha256:{index:064x}")


def _assert_summary_matches_reference(rows: list[qbatch.CandidateRow], work_kind: str) -> None:
    family = qual.VALIDATOR_FAMILIES["openai"]
    protocol = qual.SCORING_PROTOCOL if work_kind == "scoring" else qual.PROTOCOL
    reference = qbatch.request_plan_summary(
        family,
        family.requested_model,
        rows,
        protocol=protocol,
        work_kind=work_kind,  # type: ignore[arg-type]
        group_size=25,
    )
    actual = planner.streaming_request_plan_summary(
        family,
        family.requested_model,
        rows,
        protocol=protocol,
        work_kind=work_kind,  # type: ignore[arg-type]
    )
    for key in (
        "candidateCount",
        "family",
        "groupSizeDistribution",
        "inputFileBytes",
        "modelId",
        "projectedInputTokens",
        "projectedOutputTokenAllowance",
        "projectedCostUsd",
        "providerJobCount",
        "providerRequestCount",
        "requestGroupSizeLimit",
        "workKind",
    ):
        assert actual[key] == reference[key]


def test_streaming_plan_matches_qbatch_for_scoring_and_judging() -> None:
    rows = [_row(index) for index in range(63)]
    _assert_summary_matches_reference(rows, "scoring")
    _assert_summary_matches_reference(rows, "validation")


def test_fast_groups_match_qbatch_when_byte_limit_splits_before_25(monkeypatch) -> None:
    rows = [_row(index, definition="x" * 2_000) for index in range(12)]
    monkeypatch.setattr(qbatch, "GROUP_INPUT_BYTE_LIMIT", 12_000)

    expected = qbatch.deterministic_groups(rows, group_size=25, work_kind="validation")
    actual = planner.deterministic_groups_fast(rows, work_kind="validation")

    assert [[row.candidate_id for row in group] for group in actual] == [
        [row.candidate_id for row in group] for group in expected
    ]
    _assert_summary_matches_reference(rows, "validation")

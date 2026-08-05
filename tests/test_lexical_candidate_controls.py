"""Direction and reproducibility checks for the optional lexical benchmark."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("rapidfuzz", reason="lexical benchmark uses the pinned optional RapidFuzz dependency")

from refspec.atlas.qualification import AtlasConcept
from tools import benchmark_lexical_candidate_controls as lexical


def _concept(side: str, identifier: str, label: str, **values: object) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=f"urn:test:{side}",
        pref_label=label,
        **values,
    )


def test_every_scorer_declares_and_obeys_its_ranking_direction() -> None:
    choices = ("conference paper", "conference papers", "marine zoology")

    for spec in lexical.SCORER_SPECS:
        matrix = lexical.score_matrix(("conference paper",), choices, spec=spec, workers=1)
        order = lexical.stable_top_indices(
            matrix[0],
            higher_is_better=spec.higher_is_better,
            top_k=len(choices),
        )

        assert order[0] == 0, spec.name
        assert order[-1] == 2, spec.name


def test_arm_output_is_identical_after_reversing_input_sequences() -> None:
    sources = (
        _concept("source", "b", "Paper acceptance"),
        _concept("source", "a", "Conference chair"),
    )
    targets = (
        _concept("target", "b", "Accepted paper"),
        _concept("target", "a", "Conference chairman"),
    )
    case_type = lexical.shared_benchmark.AlignmentCase
    first_case = case_type(
        "example",
        sources,
        targets,
        frozenset({(sources[0].member, targets[0].member), (sources[1].member, targets[1].member)}),
    )
    second_case = case_type(
        "example",
        tuple(reversed(sources)),
        tuple(reversed(targets)),
        first_case.gold,
    )
    spec = lexical.SCORER_BY_NAME["rapidfuzz-wratio"]

    def run(case: object) -> tuple[dict[str, object], dict[int, int], dict[int, frozenset[int]]]:
        codec = lexical.PairCodec.from_cases((case,))
        gold = lexical._gold_codes((case,), codec)
        return lexical.run_arm(
            (case,),
            spec=spec,
            top_ks=(1, 2),
            codec=codec,
            gold=gold,
            workers=1,
            block_size=1,
        )

    first_report, first_pairs, first_coverage = run(first_case)
    second_report, second_pairs, second_coverage = run(second_case)

    first_report.pop("elapsedSeconds")
    second_report.pop("elapsedSeconds")
    assert first_report == second_report
    assert first_pairs == second_pairs
    assert first_coverage == second_coverage


def test_equal_scores_break_ties_by_canonical_target_member() -> None:
    source = _concept("source", "only", "Conference")
    target_b = _concept("target", "b", "Meeting")
    target_a = _concept("target", "a", "Meeting")
    case = lexical.shared_benchmark.AlignmentCase(
        "tie",
        (source,),
        (target_b, target_a),
        frozenset({(source.member, target_a.member)}),
    )
    codec = lexical.PairCodec.from_cases((case,))
    gold = lexical._gold_codes((case,), codec)

    _report, pairs, _coverage = lexical.run_arm(
        (case,),
        spec=lexical.SCORER_BY_NAME["rapidfuzz-ratio"],
        top_ks=(1,),
        codec=codec,
        gold=gold,
        workers=1,
        block_size=1,
    )

    retained = [codec.decode(code) for code, rank in pairs.items() if rank == 1]
    assert ("tie", source.member, target_a.member) in retained


def test_retrieval_challenges_are_separate_from_mapping_relation_semantics() -> None:
    left = _concept("source", "paper", "Accepted paper")
    right = _concept("target", "paper", "Accepted paper")

    challenges, evidence = lexical.classify_challenges(left, right)

    assert challenges == ("lexical-exact",)
    assert "exact" not in challenges
    assert evidence["preferredRatio"] == 100.0
    assert "translation-cross-lingual" not in lexical.CHALLENGE_TAXONOMY


def test_atlas_mapping_semantics_come_from_typed_assertions(tmp_path) -> None:
    left = _concept("source", "paper", "Paper")
    right = _concept("target", "publication", "Publication")
    case = lexical.shared_benchmark.AlignmentCase(
        "example",
        (left,),
        (right,),
        frozenset({(left.member, right.member)}),
    )
    assertion_directory = tmp_path / "qualification-baseline" / case.name / "relation-assertions-v2"
    assertion_directory.mkdir(parents=True)
    (assertion_directory / "relation-assertions.json").write_text(
        json.dumps(
            {
                "mappingAssertions": [
                    {
                        "relation": "http://www.w3.org/2004/02/skos/core#broadMatch",
                        "sourceConcept": left.member,
                        "targetConcept": right.member,
                    }
                ]
            }
        )
    )

    relations = lexical._mapping_relations(tmp_path, (case,), "atlas")

    assert relations == {(case.name, left.member, right.member): "broad"}

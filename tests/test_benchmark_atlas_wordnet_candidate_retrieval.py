"""Focused checks for the bounded Atlas Open English WordNet benchmark."""

from __future__ import annotations

from refspec.atlas.qualification import AtlasConcept
from tools import benchmark_atlas_candidate_retrieval as shared
from tools import benchmark_atlas_wordnet_candidate_retrieval as benchmark
from tools import benchmark_beyond_equivalence_candidate_retrieval as wordnet
from tools import benchmark_lexical_candidate_controls as lexical


def _concept(side: str, identifier: str, label: str) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=f"urn:test:{side}",
        pref_label=label,
    )


def _fixture() -> tuple[shared.AlignmentCase, wordnet.WordNetIndex]:
    source = _concept("source", "alpha", "Alpha")
    targets = tuple(
        _concept("target", identifier, label)
        for identifier, label in (
            ("same", "Same"),
            ("one", "One"),
            ("two", "Two"),
            ("three", "Three"),
            ("four", "Four"),
            ("other", "Other"),
        )
    )
    case = shared.AlignmentCase(
        "fixture",
        (source,),
        targets,
        frozenset({(source.member, targets[0].member), (source.member, targets[4].member)}),
    )
    index = wordnet.WordNetIndex(
        forms={
            "alpha": frozenset({"s0"}),
            "same": frozenset({"s0"}),
            "one": frozenset({"s1"}),
            "two": frozenset({"s2"}),
            "three": frozenset({"s3"}),
            "four": frozenset({"s4"}),
            "other": frozenset({"other"}),
        },
        adjacency={
            "s0": frozenset({"s1"}),
            "s1": frozenset({"s0", "s2"}),
            "s2": frozenset({"s1", "s3"}),
            "s3": frozenset({"s2", "s4"}),
            "s4": frozenset({"s3"}),
        },
        stats={},
    )
    return case, index


def test_wordnet_frontier_finds_exact_minimum_distances_and_is_order_stable() -> None:
    case, index = _fixture()
    codec = lexical.PairCodec.from_cases((case,))

    distances, metadata = benchmark.wordnet_minimum_distances((case,), codec=codec, index=index, maximum_depth=4)
    reversed_case = shared.AlignmentCase(
        case.name,
        tuple(reversed(case.sources)),
        tuple(reversed(case.targets)),
        case.gold,
    )
    repeated, repeated_metadata = benchmark.wordnet_minimum_distances(
        (reversed_case,), codec=codec, index=index, maximum_depth=4
    )

    assert sorted(distances.values()) == [0, 1, 2, 3, 4]
    assert distances == repeated
    assert metadata["featureDigest"] == repeated_metadata["featureDigest"]
    assert metadata["evidenceDigest"] == repeated_metadata["evidenceDigest"]


def test_depth_summary_separates_wordnet_from_add_only_floor_contribution() -> None:
    case, index = _fixture()
    codec = lexical.PairCodec.from_cases((case,))
    distances, _metadata = benchmark.wordnet_minimum_distances((case,), codec=codec, index=index, maximum_depth=4)
    target_indexes = {member: index for index, member in enumerate(codec.targets[0])}
    same_member = next(target.member for target in case.targets if target.pref_label == "Same")
    four_member = next(target.member for target in case.targets if target.pref_label == "Four")
    same = codec.code(0, 0, target_indexes[same_member])
    four = codec.code(0, 0, target_indexes[four_member])
    gold = frozenset({same, four})
    floor = frozenset({same})
    gold_by_relation = {
        "exact": frozenset({same}),
        "close": frozenset(),
        "broad": frozenset(),
        "narrow": frozenset({four}),
        "related": frozenset(),
    }
    relation_by_code = {same: "exact", four: "narrow"}
    label_by_member = {(case.name, concept.member): concept.pref_label for concept in (*case.sources, *case.targets)}

    rows = benchmark.summarize_depths(
        distances,
        maximum_depth=4,
        floor=floor,
        gold=gold,
        gold_by_relation=gold_by_relation,
        relation_by_code=relation_by_code,
        label_by_member=label_by_member,
        codec=codec,
    )

    assert [row["candidates"] for row in rows] == [1, 2, 3, 4, 5]
    assert rows[0]["found"] == 1
    assert rows[4]["found"] == 2
    assert rows[4]["typedRecall"]["narrow"]["found"] == 1
    assert rows[4]["incrementalGoldRelations"] == [
        {
            "case": "fixture",
            "source": case.sources[0].member,
            "sourceLabel": "Alpha",
            "target": next(target.member for target in case.targets if target.pref_label == "Four"),
            "targetLabel": "Four",
            "relation": "narrow",
        }
    ]
    assert rows[4]["unionWithProductionFloor"]["uniqueWordNetCandidates"] == 4
    assert rows[4]["unionWithProductionFloor"]["uniqueWordNetGold"] == 1

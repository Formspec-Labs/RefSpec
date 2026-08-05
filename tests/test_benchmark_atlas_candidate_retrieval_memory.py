"""Memory-bounded exact retrieval and compact accounting checks."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from refspec.atlas.qualification import AtlasConcept

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import benchmark_atlas_candidate_retrieval as benchmark


def _concept(side: str, identifier: str, label: str) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=f"urn:test:{side}",
        pref_label=label,
    )


def _case(*, reverse: bool = False) -> benchmark.AlignmentCase:
    sources = (
        _concept("source", "b", "Conference paper"),
        _concept("source", "a", "Program chair"),
    )
    targets = (
        _concept("target", "b", "Submitted paper"),
        _concept("target", "a", "Conference chair"),
        _concept("target", "c", "Marine habitat"),
    )
    if reverse:
        sources = tuple(reversed(sources))
        targets = tuple(reversed(targets))
    return benchmark.AlignmentCase(
        "example",
        sources,
        targets,
        frozenset(
            {
                ("https://example.test/source/b", "https://example.test/target/b"),
                ("https://example.test/source/a", "https://example.test/target/a"),
            }
        ),
    )


def test_blocked_exact_ranking_matches_one_block_and_uses_member_ties() -> None:
    source_ids = ("https://example.test/source/z", "https://example.test/source/a")
    target_ids = ("https://example.test/target/z", "https://example.test/target/a")
    vectors = np.ones((2, 3), dtype=np.float32)

    blocked = benchmark._matrix_candidate_ranks(
        source_ids,
        target_ids,
        vectors,
        vectors,
        vectors,
        vectors,
        1,
        query_block_size=1,
    )
    one_block = benchmark._matrix_candidate_ranks(
        source_ids,
        target_ids,
        vectors,
        vectors,
        vectors,
        vectors,
        1,
        query_block_size=16,
    )

    np.testing.assert_array_equal(blocked, one_block)
    np.testing.assert_array_equal(blocked, np.asarray([[2, 1], [1, 1]], dtype=np.uint8))


def test_blocked_ranks_match_the_previous_full_matrix_semantics() -> None:
    random = np.random.default_rng(20260805)
    source_ids = tuple(f"source-{index:02d}" for index in range(7))
    target_ids = tuple(f"target-{index:02d}" for index in range(11))
    source_query = random.normal(size=(7, 5)).astype(np.float32)
    target_document = random.normal(size=(11, 5)).astype(np.float32)
    target_query = random.normal(size=(11, 5)).astype(np.float32)
    source_document = random.normal(size=(7, 5)).astype(np.float32)
    top_k = 3

    expected = np.full((7, 11), top_k + 1, dtype=np.uint8)
    for source_index, row in enumerate(source_query @ target_document.T):
        for rank, target_index in enumerate(np.argsort(-row, kind="stable")[:top_k], start=1):
            expected[source_index, target_index] = rank
    for target_index, row in enumerate(target_query @ source_document.T):
        for rank, source_index in enumerate(np.argsort(-row, kind="stable")[:top_k], start=1):
            expected[source_index, target_index] = min(expected[source_index, target_index], rank)

    for query_block_size in (1, 2, 5, 128):
        actual = benchmark._matrix_candidate_ranks(
            source_ids,
            target_ids,
            source_query,
            target_document,
            target_query,
            source_document,
            top_k,
            query_block_size=query_block_size,
        )
        np.testing.assert_array_equal(actual, expected)


def test_compact_union_summary_matches_legacy_pair_set_evidence() -> None:
    case = _case()
    paper = (case.name, case.sources[0].member, case.targets[0].member)
    chair = (case.name, case.sources[1].member, case.targets[1].member)
    distractor = (case.name, case.sources[0].member, case.targets[1].member)
    first = benchmark._compact_ranks_from_pairs(
        (case,),
        {paper: 1, chair: 2},
        2,
    )
    second = benchmark._compact_ranks_from_pairs(
        (case,),
        {distractor: 1},
        2,
    )
    gold = {(case.name, source, target) for source, target in case.gold}

    for top_k, expected_pairs in (
        (1, {paper, distractor}),
        (2, {paper, chair, distractor}),
    ):
        expected = benchmark._pair_set_summary(expected_pairs, gold, include_misses=True)
        actual = benchmark._compact_pair_summary(
            (first, second),
            top_k=top_k,
            include_misses=True,
        )
        assert actual == expected


def test_dense_report_and_vector_digest_do_not_depend_on_block_or_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTextEmbedding:
        def __init__(self, *, model_name: str) -> None:
            self.model_name = model_name

        @staticmethod
        def _embed(texts: list[str]) -> list[np.ndarray]:
            result = []
            for text in texts:
                encoded = text.encode()
                result.append(
                    np.asarray(
                        [
                            len(encoded),
                            sum(encoded) % 257,
                            sum((index + 1) * value for index, value in enumerate(encoded)) % 263,
                            encoded.count(b"a"),
                        ],
                        dtype=np.float32,
                    )
                )
            return result

        def query_embed(self, texts: list[str]) -> list[np.ndarray]:
            return self._embed(texts)

        def passage_embed(self, texts: list[str]) -> list[np.ndarray]:
            return self._embed(texts)

    fake_fastembed = types.ModuleType("fastembed")
    fake_fastembed.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)

    first_report, first_pairs = benchmark.dense_benchmark(
        (_case(),),
        model_name="test/fake",
        views=("label", "structured"),
        prefix_mode="symmetric",
        top_ks=(1, 2),
        query_block_size=1,
    )
    second_report, second_pairs = benchmark.dense_benchmark(
        (_case(reverse=True),),
        model_name="test/fake",
        views=("label", "structured"),
        prefix_mode="symmetric",
        top_ks=(1, 2),
        query_block_size=64,
    )

    first_report.pop("elapsedSeconds")
    second_report.pop("elapsedSeconds")
    assert first_report == second_report
    for top_k in (1, 2):
        assert benchmark._compact_pair_summary(
            (first_pairs,), top_k=top_k, include_misses=True
        ) == benchmark._compact_pair_summary((second_pairs,), top_k=top_k, include_misses=True)


def test_query_block_size_is_positive_and_configurable() -> None:
    args = benchmark.parse_args(
        [
            "--root",
            "/tmp/example",
            "--suite",
            "conference",
            "--query-block-size",
            "7",
        ]
    )
    assert args.query_block_size == 7
    with pytest.raises(SystemExit):
        benchmark.parse_args(
            [
                "--root",
                "/tmp/example",
                "--suite",
                "conference",
                "--query-block-size",
                "0",
            ]
        )


def test_obo_synonym_and_definition_reference_nodes_are_resolved(tmp_path: Path) -> None:
    ontology = tmp_path / "referenced-text.rdf"
    ontology.write_text(
        """\
<?xml version="1.0"?>
<rdf:RDF
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
  xmlns:owl="http://www.w3.org/2002/07/owl#"
  xmlns:obo="http://www.geneontology.org/formats/oboInOwl#">
  <owl:Class rdf:about="http://example.test/C1">
    <rdfs:label>Medulla Oblongata</rdfs:label>
    <obo:hasRelatedSynonym rdf:resource="http://example.test/synonym-1"/>
    <obo:hasDefinition rdf:resource="http://example.test/definition-1"/>
  </owl:Class>
  <rdf:Description rdf:about="http://example.test/synonym-1">
    <rdfs:label>Myelencephalon</rdfs:label>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.test/definition-1">
    <rdfs:label>The posterior part of the hindbrain.</rdfs:label>
  </rdf:Description>
</rdf:RDF>
""",
        encoding="utf-8",
    )

    (concept,) = benchmark._concepts_from_graph(ontology, release="urn:test:anatomy")

    assert concept.alt_labels == ("Myelencephalon",)
    assert concept.definition == "The posterior part of the hindbrain."
    assert not any("synonym-1" in value for value in concept.alt_labels)

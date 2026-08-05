"""Focused checks for the typed BeyondEquivalence discovery benchmark."""

from __future__ import annotations

import hashlib
import zipfile

import numpy as np
import pytest

from refspec.atlas.qualification import AtlasConcept
from tools import benchmark_beyond_equivalence_candidate_retrieval as benchmark


def _concept(side: str, identifier: str, label: str) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=f"urn:test:{side}",
        pref_label=label,
    )


def _reference_xml(markers: tuple[str, ...]) -> bytes:
    cells = []
    for index, marker in enumerate(markers):
        escaped = {"<": "&lt;", ">": "&gt;"}.get(marker, marker)
        cells.append(
            "<map><Cell>"
            f'<entity1 rdf:resource="https://example.test/source/{index}"/>'
            f'<entity2 rdf:resource="https://example.test/target/{index}"/>'
            f"<relation>{escaped}</relation>"
            "<measure>1.0</measure>"
            "</Cell></map>"
        )
    return (
        '<?xml version="1.0"?>'
        '<rdf:RDF xmlns="http://knowledgeweb.semanticweb.org/heterogeneity/alignment" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f"<Alignment>{''.join(cells)}</Alignment></rdf:RDF>"
    ).encode()


def _case(
    *,
    sources: tuple[AtlasConcept, ...],
    targets: tuple[AtlasConcept, ...],
    relations: tuple[benchmark.ReferenceRelation, ...],
) -> benchmark.TypedAlignmentCase:
    return benchmark.TypedAlignmentCase("fixture", sources, targets, relations)


def test_reference_parser_preserves_every_supported_raw_marker_and_family() -> None:
    markers = ("=", ">", "<", "Related", "~", "HasA", "PartOf", "!", "Disjoint")

    relations = benchmark.parse_reference(_reference_xml(markers), case_name="fixture")

    assert tuple(relation.marker for relation in relations) == markers
    assert tuple(relation.family for relation in relations) == (
        "equality",
        "sourceBroader",
        "sourceNarrower",
        "relatedOrOverlap",
        "relatedOrOverlap",
        "partOrHasA",
        "partOrHasA",
        "disjointOrRejection",
        "disjointOrRejection",
    )


def test_reference_parser_rejects_an_unknown_relation_marker() -> None:
    with pytest.raises(ValueError, match="unsupported reference relation marker 'Maybe'"):
        benchmark.parse_reference(_reference_xml(("Maybe",)), case_name="fixture")


def test_archive_loader_uses_iri_labels_and_includes_implicit_owl_thing(tmp_path: object) -> None:
    archive_path = tmp_path / "fixture.zip"
    source = b"""\
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="https://example.test/source/Alpha"><rdfs:label>Alpha</rdfs:label></owl:Class>
 <owl:Class rdf:about="https://example.test/source/Beta_Item">
   <rdfs:subClassOf rdf:resource="https://example.test/source/Alpha"/>
 </owl:Class>
</rdf:RDF>"""
    target = b"""\
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#">
 <owl:Class rdf:about="https://example.test/target/Beta"><rdfs:label>Beta</rdfs:label></owl:Class>
</rdf:RDF>"""
    reference = _reference_xml(("<",)).replace(b"source/0", b"source/Beta_Item").replace(b"target/0", b"target/Beta")
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("benchmark/fixture/source.rdf", source)
        archive.writestr("benchmark/fixture/target.rdf", target)
        archive.writestr("benchmark/fixture/reference.rdf", reference)

    loaded = benchmark.load_cases(archive_path, ("fixture",))[0]

    source_by_member = {concept.member: concept for concept in loaded.sources}
    assert source_by_member["https://example.test/source/Beta_Item"].pref_label == "Beta Item"
    assert "http://www.w3.org/2002/07/owl#Thing" in source_by_member
    assert loaded.relations[0].marker == "<"
    assert loaded.relations[0].family == "sourceNarrower"


def test_candidate_discovery_inputs_do_not_include_reference_markers() -> None:
    source = _concept("source", "alpha", "Alpha")
    target = _concept("target", "alpha", "Alpha")
    equality = _case(
        sources=(source,),
        targets=(target,),
        relations=(benchmark.ReferenceRelation(source.member, target.member, "=", "equality"),),
    )
    meronymy = _case(
        sources=(source,),
        targets=(target,),
        relations=(benchmark.ReferenceRelation(source.member, target.member, "HasA", "partOrHasA"),),
    )

    equality_pairs, _metadata, _classes = benchmark.production_floor((equality,))
    meronymy_pairs, _metadata, _classes = benchmark.production_floor((meronymy,))

    assert benchmark.candidate_input_digest((equality,)) == benchmark.candidate_input_digest((meronymy,))
    assert benchmark.reference_digest((equality,)) != benchmark.reference_digest((meronymy,))
    assert equality_pairs == meronymy_pairs


def test_summary_reports_relation_types_separately_and_keeps_zero_opportunities() -> None:
    source_a = _concept("source", "a", "A")
    source_b = _concept("source", "b", "B")
    target_a = _concept("target", "a", "A")
    target_b = _concept("target", "b", "B")
    case = _case(
        sources=(source_a, source_b),
        targets=(target_a, target_b),
        relations=(
            benchmark.ReferenceRelation(source_a.member, target_a.member, "=", "equality"),
            benchmark.ReferenceRelation(source_b.member, target_b.member, "HasA", "partOrHasA"),
        ),
    )
    ranks = {("fixture", source_a.member, target_a.member): 1}

    summary = benchmark.summarize_pairs(ranks, top_k=1, cases=(case,))

    assert summary["found"] == 1
    assert summary["possiblePairs"] == 4
    assert summary["candidateFraction"] == 0.25
    assert summary["byMarker"]["="] == {"total": 1, "found": 1, "recall": 1.0}
    assert summary["byMarker"]["HasA"] == {"total": 1, "found": 0, "recall": 0.0}
    assert summary["byFamily"]["partOrHasA"]["recall"] == 0.0
    assert summary["byFamily"]["disjointOrRejection"] == {"total": 0, "found": 0, "recall": None}


def test_rapidfuzz_ties_and_input_order_are_canonical() -> None:
    pytest.importorskip("rapidfuzz")
    source_a = _concept("source", "a", "Same")
    source_b = _concept("source", "b", "Same")
    target_a = _concept("target", "a", "Same")
    target_b = _concept("target", "b", "Same")
    target_c = _concept("target", "c", "Same")
    relation = benchmark.ReferenceRelation(source_a.member, target_a.member, "=", "equality")
    forward = _case(
        sources=(source_b, source_a),
        targets=(target_c, target_b, target_a),
        relations=(relation,),
    )
    reversed_case = _case(
        sources=tuple(reversed(forward.sources)),
        targets=tuple(reversed(forward.targets)),
        relations=(relation,),
    )
    spec = next(item for item in benchmark.RAPIDFUZZ_SPECS if item.name == "rapidfuzz-token-set-ratio")

    first, first_metadata = benchmark.run_rapidfuzz_arm((forward,), spec=spec, maximum=1, block_size=1, workers=1)
    second, second_metadata = benchmark.run_rapidfuzz_arm(
        (reversed_case,), spec=spec, maximum=1, block_size=2, workers=1
    )

    expected = {
        ("fixture", source_a.member, target_a.member),
        ("fixture", source_a.member, target_b.member),
        ("fixture", source_a.member, target_c.member),
        ("fixture", source_b.member, target_a.member),
    }
    assert set(first) == expected
    assert first == second
    assert first_metadata["featureDigest"] == second_metadata["featureDigest"]
    assert first_metadata["rankingDigest"] == second_metadata["rankingDigest"]


def test_pair_digest_is_stable_under_rank_map_order() -> None:
    pairs = {
        ("b", "s2", "t2"): 2,
        ("a", "s1", "t1"): 1,
    }

    assert benchmark._pair_set_digest(pairs) == benchmark._pair_set_digest(reversed(tuple(pairs)))


def test_dense_direction_is_identical_across_score_block_sizes() -> None:
    query_ids = ("source-a", "source-b", "source-c")
    document_ids = ("target-a", "target-b", "target-c")
    query_vectors = np.asarray(((1.0, 0.0), (1.0, 0.0), (0.0, 1.0)), dtype=np.float32)
    document_vectors = np.asarray(((1.0, 0.0), (1.0, 0.0), (0.0, 1.0)), dtype=np.float32)

    def run(block_size: int) -> tuple[dict[benchmark.PairKey, int], str]:
        ranks: dict[benchmark.PairKey, int] = {}
        hasher = hashlib.sha256()
        benchmark._dense_direction(
            case_name="fixture",
            query_ids=query_ids,
            document_ids=document_ids,
            query_vectors=query_vectors,
            document_vectors=document_vectors,
            maximum=2,
            block_size=block_size,
            reverse=False,
            ranks=ranks,
            ranking_hasher=hasher,
        )
        return ranks, hasher.hexdigest()

    assert run(1) == run(3)
    ranks, _digest = run(1)
    assert ranks[("fixture", "source-a", "target-a")] == 1
    assert ranks[("fixture", "source-a", "target-b")] == 2


def test_wordnet_head_and_depth_two_taxonomy_expansion_is_relation_blind() -> None:
    coach = _concept("source", "coach", "Basketball Coaches")
    bank = _concept("source", "bank", "Bank")
    person = _concept("target", "person", "Person")
    entity = _concept("target", "entity", "Entity")
    institution = _concept("target", "institution", "Financial Institution")
    table = _concept("target", "table", "Table")
    case = _case(
        sources=(bank, coach),
        targets=(table, entity, institution, person),
        relations=(benchmark.ReferenceRelation(coach.member, person.member, "<", "sourceNarrower"),),
    )
    index = benchmark.WordNetIndex(
        forms={
            "coach": frozenset({"coach-sense"}),
            "bank": frozenset({"river-bank-sense", "financial-bank-sense"}),
            "person": frozenset({"person-sense"}),
            "entity": frozenset({"entity-sense"}),
            "financial institution": frozenset({"institution-sense"}),
            "institution": frozenset({"institution-sense"}),
            "table": frozenset({"table-sense"}),
        },
        adjacency={
            "coach-sense": frozenset({"professional-sense"}),
            "professional-sense": frozenset({"coach-sense", "person-sense"}),
            "person-sense": frozenset({"professional-sense", "entity-sense"}),
            "entity-sense": frozenset({"person-sense"}),
            "financial-bank-sense": frozenset({"institution-sense"}),
            "institution-sense": frozenset({"financial-bank-sense"}),
        },
        stats={},
    )

    ranks, metadata = benchmark.run_wordnet_arm((case,), index=index)
    depth_three, depth_three_metadata = benchmark.run_wordnet_arm((case,), index=index, maximum_depth=3)

    assert "coach" in benchmark.noun_lookup_forms(coach.pref_label)
    assert benchmark.noun_lookup_forms("USPresident") == ("president", "us president")
    assert ("fixture", coach.member, person.member) in ranks
    assert ("fixture", bank.member, institution.member) in ranks
    assert ("fixture", coach.member, entity.member) not in ranks
    assert ("fixture", coach.member, entity.member) in depth_three
    assert ("fixture", coach.member, table.member) not in ranks
    assert metadata["generationClassCandidates"] == {
        "sharedSynset": 0,
        "oneHopTaxonomy": 1,
        "twoHopTaxonomy": 1,
    }
    assert depth_three_metadata["generationClassCandidates"]["threeHopTaxonomy"] == 1

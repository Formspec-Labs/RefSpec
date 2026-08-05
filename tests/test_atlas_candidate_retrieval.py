"""Recall-first deterministic retrieval before blind relation judging."""

from __future__ import annotations

from refspec.atlas import candidate_retrieval as retrieval
from refspec.atlas.qualification import AtlasConcept, AtlasConceptContext

SOURCE_RELEASE = "urn:ref:test:retrieval:source"
TARGET_RELEASE = "urn:ref:test:retrieval:target"


def _concept(
    side: str,
    identifier: str,
    label: str,
    **values: object,
) -> AtlasConcept:
    return AtlasConcept(
        member=f"https://example.test/{side}/{identifier}",
        release=SOURCE_RELEASE if side == "source" else TARGET_RELEASE,
        pref_label=label,
        **values,
    )


def _keys(hits: tuple[retrieval.RetrievalHit, ...]) -> set[tuple[str, str]]:
    return {hit.key for hit in hits}


def test_context_view_discovers_a_definition_only_relation() -> None:
    source = _concept(
        "source",
        "s1",
        "Carbon fixation",
        definition="Biological conversion of atmospheric carbon dioxide during photosynthesis",
    )
    target = _concept(
        "target",
        "t1",
        "Photosynthetic assimilation",
        definition="Photosynthesis process that converts atmospheric carbon dioxide",
    )
    distractor = _concept(
        "target",
        "t2",
        "Maritime tariffs",
        definition="Charges applied to cargo imported by sea",
    )

    context = retrieval.bidirectional_sparse_neighbors(
        (source,),
        (target, distractor),
        view=retrieval.CONTEXT_SPARSE_VIEW,
        top_k=1,
    )
    label = retrieval.bidirectional_sparse_neighbors(
        (source,),
        (target, distractor),
        view=retrieval.LABEL_SPARSE_VIEW,
        top_k=1,
    )

    assert (source.member, target.member) in _keys(context)
    assert (source.member, target.member) not in _keys(label)


def test_context_view_discovers_parent_and_child_signals() -> None:
    source = _concept(
        "source",
        "s2",
        "Household panel",
        parents=(AtlasConceptContext("urn:parent:a", "Longitudinal studies"),),
        children=(AtlasConceptContext("urn:child:a", "Family cohort"),),
    )
    target = _concept(
        "target",
        "t2",
        "Repeated family survey",
        parents=(AtlasConceptContext("urn:parent:b", "Longitudinal studies"),),
        children=(AtlasConceptContext("urn:child:b", "Family cohort"),),
    )
    distractor = _concept(
        "target",
        "t3",
        "Mineral extraction",
        parents=(AtlasConceptContext("urn:parent:c", "Industrial production"),),
    )

    hits = retrieval.bidirectional_sparse_neighbors(
        (source,),
        (target, distractor),
        view=retrieval.CONTEXT_SPARSE_VIEW,
        top_k=1,
    )

    assert (source.member, target.member) in _keys(hits)


def test_identifier_equality_is_a_candidate_signal_not_a_mapping() -> None:
    source = _concept("source", "ABC-104", "Coastal resilience")
    target = _concept("target", "ABC-104", "Shoreline adaptation")
    distractor = _concept("target", "XYZ-999", "Coastal resilience")

    hits = retrieval.exact_identifier_neighbors((source,), (target, distractor))

    assert [hit.key for hit in hits] == [(source.member, target.member)]
    assert hits[0].method == "normalized-local-identifier-equality"


def test_character_view_discovers_spelling_variants() -> None:
    source = _concept("source", "s4", "Paediatric cardiology")
    target = _concept("target", "t4", "Pediatric cardiology")
    distractor = _concept("target", "t5", "Agricultural exports")

    hits = retrieval.bidirectional_sparse_neighbors(
        (source,),
        (target, distractor),
        view=retrieval.CHARACTER_SPARSE_VIEW,
        top_k=1,
    )

    assert (source.member, target.member) in _keys(hits)


def test_graph_expansion_adds_directional_and_aligned_neighbors() -> None:
    source_parent = _concept("source", "parent", "Transport")
    source_child = _concept("source", "child", "Electric buses")
    source = _concept(
        "source",
        "anchor",
        "Public transit",
        broader=(source_parent.member,),
        parents=(AtlasConceptContext(source_parent.member, source_parent.pref_label),),
        children=(AtlasConceptContext(source_child.member, source_child.pref_label),),
    )
    target_parent = _concept("target", "parent", "Transportation")
    target_child = _concept("target", "child", "Battery buses")
    target = _concept(
        "target",
        "anchor",
        "Public transportation",
        broader=(target_parent.member,),
        parents=(AtlasConceptContext(target_parent.member, target_parent.pref_label),),
        children=(AtlasConceptContext(target_child.member, target_child.pref_label),),
    )

    hits = retrieval.graph_neighborhood_neighbors(
        (source, source_parent, source_child),
        (target, target_parent, target_child),
        ((source.member, target.member),),
    )
    keys = _keys(hits)

    assert (source_parent.member, target.member) in keys
    assert (source.member, target_parent.member) in keys
    assert (source_parent.member, target_parent.member) in keys
    assert (source_child.member, target_child.member) in keys


def test_sparse_retrieval_digest_is_input_order_independent() -> None:
    sources = (
        _concept("source", "a", "Labor unions", alt_labels=("Trade unions",)),
        _concept("source", "b", "Water quality", definition="Pollution in rivers and lakes"),
    )
    targets = (
        _concept("target", "a", "Trade unions"),
        _concept("target", "b", "Freshwater pollution", definition="Pollution in lakes and rivers"),
    )

    first = retrieval.bidirectional_sparse_neighbors(
        sources,
        targets,
        view=retrieval.CONTEXT_SPARSE_VIEW,
        top_k=2,
    )
    second = retrieval.bidirectional_sparse_neighbors(
        tuple(reversed(sources)),
        tuple(reversed(targets)),
        view=retrieval.CONTEXT_SPARSE_VIEW,
        top_k=2,
    )

    assert first == second
    assert retrieval.retrieval_digest(first) == retrieval.retrieval_digest(second)

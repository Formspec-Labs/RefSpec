"""Recall-first deterministic retrieval before blind relation judging."""

from __future__ import annotations

from typing import Any

import pytest

from refspec.atlas import candidate_retrieval as retrieval
from refspec.atlas.candidate_retrieval import AtlasConcept, AtlasConceptContext

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


# ---------------------------------------------------------------------------
# the pinned six-class candidate generator
# ---------------------------------------------------------------------------

GENERATION_SOURCE_RELEASE = "urn:ref:test:alpha:reference-resource-release"
GENERATION_TARGET_RELEASE = "urn:ref:test:beta:reference-resource-release"


def _source(member: str, label: str, **kwargs: Any) -> AtlasConcept:
    return AtlasConcept(
        member=member,
        release=GENERATION_SOURCE_RELEASE,
        pref_label=label,
        **kwargs,
    )


def _target(member: str, label: str, **kwargs: Any) -> AtlasConcept:
    return AtlasConcept(
        member=member,
        release=GENERATION_TARGET_RELEASE,
        pref_label=label,
        **kwargs,
    )


@pytest.fixture
def sources() -> tuple[AtlasConcept, ...]:
    return (
        _source("urn:ref:test:alpha:1", "Energy policy"),
        _source("urn:ref:test:alpha:2", "Water pollution"),
        _source("urn:ref:test:alpha:3", "Labor unions", alt_labels=("Trade unions",)),
        _source("urn:ref:test:alpha:4", "Accountants"),
        _source("urn:ref:test:alpha:5", "Milk marketing orders"),
    )


@pytest.fixture
def targets() -> tuple[AtlasConcept, ...]:
    return (
        _target("urn:ref:test:beta:1", "energy POLICY ", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:2", "Water pollution control", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:3", "Trade unions"),
        _target("urn:ref:test:beta:4", "Accountant"),
        _target("urn:ref:test:beta:5", "Volcanology"),
        _target("urn:ref:test:beta:6", "Air pollution control", broader=("urn:ref:test:beta:9",)),
        _target("urn:ref:test:beta:9", "Pollution control"),
    )


def test_generation_is_deterministic_and_order_independent(sources, targets) -> None:
    first = retrieval.generate_candidate_pairs(sources, targets)
    second = retrieval.generate_candidate_pairs(tuple(reversed(sources)), tuple(reversed(targets)))
    assert first == second
    assert first == retrieval.generate_candidate_pairs(sources, targets)


def test_generation_produces_every_declared_class(sources, targets) -> None:
    pairs = retrieval.generate_candidate_pairs(sources, targets)
    observed = {pair.generation_class for pair in pairs}
    assert observed == set(retrieval.GENERATION_CLASSES), sorted(observed)


def test_label_equality_uses_the_atlas_normalizer(sources, targets) -> None:
    pairs = retrieval.generate_candidate_pairs(sources, targets)
    equal = {
        (pair.source.member, pair.target.member)
        for pair in pairs
        if pair.generation_class == "normalizedLabelEquality"
    }
    # "Energy policy" and "energy POLICY " differ in case and trailing space.
    assert ("urn:ref:test:alpha:1", "urn:ref:test:beta:1") in equal


def test_alternate_label_equality_is_its_own_class(sources, targets) -> None:
    pairs = retrieval.generate_candidate_pairs(sources, targets)
    alternates = {
        (pair.source.member, pair.target.member)
        for pair in pairs
        if pair.generation_class == "alternateLabelEquality"
    }
    assert ("urn:ref:test:alpha:3", "urn:ref:test:beta:3") in alternates


def test_sibling_distractor_shares_a_parent_with_a_label_match(sources, targets) -> None:
    pairs = retrieval.generate_candidate_pairs(sources, targets)
    siblings = [pair for pair in pairs if pair.generation_class == "siblingDistractor"]
    assert siblings
    for pair in siblings:
        assert pair.evidence["siblingOf"] != pair.target.member


def test_negative_controls_share_no_label_token(sources, targets) -> None:
    pairs = retrieval.generate_candidate_pairs(sources, targets)
    controls = [pair for pair in pairs if pair.generation_class == "randomNegativeControl"]
    assert controls
    for pair in controls:
        left = set(retrieval.normalized_tokens(pair.source.pref_label))
        right = set(retrieval.normalized_tokens(pair.target.pref_label))
        assert not (left & right)


def test_no_pair_repeats_across_or_within_classes(sources, targets) -> None:
    """A repeated pair is two identical candidates a reader cannot tell apart."""

    doubled = (
        *targets,
        # Same concept, reachable twice: its alternate spells its own label.
        _target("urn:ref:test:beta:10", "Accountants", alt_labels=("accountants", "ACCOUNTANTS")),
    )
    pairs = retrieval.generate_candidate_pairs(sources, doubled)
    keys = [(pair.source.member, pair.target.member) for pair in pairs]
    assert len(keys) == len(set(keys))


def test_class_limits_bound_each_class(sources, targets) -> None:
    limits = dict.fromkeys(retrieval.GENERATION_CLASSES, 1)
    pairs = retrieval.generate_candidate_pairs(sources, targets, limits=limits)
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.generation_class] = counts.get(pair.generation_class, 0) + 1
    assert max(counts.values()) == 1


def test_production_generation_has_no_pilot_class_caps(sources, targets) -> None:
    production = retrieval.generate_candidate_pairs(sources, targets, production=True)
    pilot = retrieval.generate_candidate_pairs(
        sources,
        targets,
        limits=dict.fromkeys(retrieval.GENERATION_CLASSES, 1),
    )

    assert len(production) > len(pilot)
    assert {pair.generation_policy for pair in production} == {
        retrieval.PRODUCTION_CANDIDATE_GENERATION_POLICY
    }
    with pytest.raises(
        retrieval.CandidateGenerationError,
        match="does not accept pilot class limits",
    ):
        retrieval.generate_candidate_pairs(
            sources,
            targets,
            production=True,
            limits=retrieval.DEFAULT_CLASS_LIMITS,
        )


def test_generation_refuses_a_source_and_target_in_one_release(sources) -> None:
    with pytest.raises(retrieval.CandidateGenerationError, match="must cross releases"):
        retrieval.generate_candidate_pairs(sources, sources)

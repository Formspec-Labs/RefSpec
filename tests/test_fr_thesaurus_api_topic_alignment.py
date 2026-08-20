"""Derived skos:closeMatch edges between the two Federal Register vocabularies.

Atlas carries the Office of the Federal Register's 705-concept curated
thesaurus and its 1,044-term API topic list, and asserts nothing between
them -- every relation in either scheme is internal. This rule reads exact
case-folded preferred-label equality as a ``skos:closeMatch`` and puts it in
the derived graph, because RefSpec owns neither endpoint (REF-035 standing)
and the evidence is mechanical rather than adjudicated.

These tests prove the derivation over synthetic asserted facts -- including
the scope lesson applied to BOTH endpoints, since subject and object sit in
two different schemes -- the bijection refusal that keeps a many-to-one
collapse from shipping as a narrowed edge set, the symmetric-predicate
collision check that every prior rule got to skip, and the constant
agreement between this producer module and the binding's standalone
validator.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from refspec.atlas import derived_graph
from refspec.atlas.derived_graph import fr_thesaurus_api_topic_alignment as fta

BINDING_TOOLS = Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1" / "tools"

GRAPH = "<urn:ref:atlas:graph:v3:asserted>"
THES_SCHEME = fta.FR_THESAURUS_SCHEME_IRI
API_SCHEME = fta.FR_API_TOPICS_SCHEME_IRI
SUBJECT_RING = fta.ATLAS_SUBJECT_RING
OTHER_RING = "https://refspec.org/ns/atlas/v3#entity"


def _canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if terminal_lf:
        text += "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resource_lines(
    iri: str,
    *,
    label: str,
    scheme: str,
    ring: str = SUBJECT_RING,
    with_record: bool = True,
) -> list[str]:
    subject = f"<{iri}>"
    slug = iri.rsplit(":", 1)[-1]
    record = f"<urn:ref:atlas-test:source-record:{slug}>"
    label_node = f"<urn:ref:atlas-test:label:{slug}>"
    lines = [
        f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{scheme}> {GRAPH} .",
        f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{ring}> {GRAPH} .",
        f"{subject} {fta.SKOSXL_PREF_LABEL_TERM} {label_node} {GRAPH} .",
        f'{label_node} {fta.SKOSXL_LITERAL_FORM_TERM} "{label}" {GRAPH} .',
    ]
    if with_record:
        lines.append(f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .")
    return lines


def _term(iri: str, label: str, **kwargs: object) -> list[str]:
    return _resource_lines(iri, label=label, scheme=THES_SCHEME, **kwargs)  # type: ignore[arg-type]


def _topic(iri: str, label: str, **kwargs: object) -> list[str]:
    return _resource_lines(iri, label=label, scheme=API_SCHEME, **kwargs)  # type: ignore[arg-type]


def _context(
    lines: list[str],
    *,
    generated_at: str = "2026-01-01T00:00:00+00:00",
) -> tuple[derived_graph.DerivationContext, dict[str, str]]:
    facts = derived_graph.collect_asserted_fact_view(lines)
    labels = fta.collect_fr_alignment_preferred_labels(lines, facts)
    wanted = fta.fr_thesaurus_api_topic_evidence_nodes(facts, labels)
    node_digest = derived_graph.collect_node_digests(lines, wanted)
    context = derived_graph.DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=_canonical_sha256,
        generated_at=generated_at,
    )
    return context, labels


TERM = "urn:ref:atlas-test:fr:term-armed-forces"
TOPIC = "urn:ref:atlas-test:fr:topic-armed-forces"


def _pair_lines(term_label: str = "Armed Forces", topic_label: str = "Armed Forces") -> list[str]:
    return [*_term(TERM, term_label), *_topic(TOPIC, topic_label)]


def test_matching_labels_derive_one_close_match_edge() -> None:
    context, labels = _context(_pair_lines())
    outcome = fta.derive_fr_thesaurus_api_topic_rows(context, labels)
    assert len(outcome.rows) == 1
    (row,) = outcome.rows
    assert row.subject == TERM
    assert row.object == TOPIC
    assert row.predicate == fta.SKOS_CLOSE_MATCH
    assert row.ring == SUBJECT_RING


def test_edge_cites_the_two_exact_endpoint_records() -> None:
    context, labels = _context(_pair_lines())
    (row,) = fta.derive_fr_thesaurus_api_topic_rows(context, labels).rows
    assert set(row.evidence) == {
        "urn:ref:atlas-test:source-record:term-armed-forces",
        "urn:ref:atlas-test:source-record:topic-armed-forces",
    }


def test_case_drift_between_the_publishers_two_lists_still_matches() -> None:
    """The three real case-drift pairs are why folding is applied at all."""

    context, labels = _context(_pair_lines("Armed Forces", "Armed forces"))
    outcome = fta.derive_fr_thesaurus_api_topic_rows(context, labels)
    assert len(outcome.rows) == 1
    assert outcome.counts["caseFoldedOnly"] == 1


def test_identical_labels_are_not_counted_as_case_folded() -> None:
    context, labels = _context(_pair_lines("Armed Forces", "Armed Forces"))
    outcome = fta.derive_fr_thesaurus_api_topic_rows(context, labels)
    assert outcome.counts["caseFoldedOnly"] == 0


def test_scheme_scopes_the_rule_on_both_endpoints_not_label_shape() -> None:
    """A foreign-scheme resource carrying the identical label admits no edge.

    The MeSH rule shipped scheme-blind and an adversarial battery caught it
    proving parentage from notation shape alone (REF-043). This rule is
    scoped from birth, and scoped on BOTH sides because its endpoints sit in
    two different schemes.
    """

    decoy = "urn:ref:atlas-test:lcsh:armed-forces"
    lines = [
        *_pair_lines(),
        *_resource_lines(
            decoy,
            label="Armed Forces",
            scheme="urn:ref:atlas-resource-scheme:lcsh-subjects",
        ),
    ]
    context, labels = _context(lines)
    outcome = fta.derive_fr_thesaurus_api_topic_rows(context, labels)
    assert len(outcome.rows) == 1
    endpoints = {outcome.rows[0].subject, outcome.rows[0].object}
    assert decoy not in endpoints


def test_unmatched_terms_and_topics_are_counted_never_guessed() -> None:
    lines = [
        *_pair_lines(),
        *_term("urn:ref:atlas-test:fr:term-telemedicine", "Telemedicine"),
        *_topic("urn:ref:atlas-test:fr:topic-lawn-darts", "Lawn darts"),
    ]
    context, labels = _context(lines)
    outcome = fta.derive_fr_thesaurus_api_topic_rows(context, labels)
    assert len(outcome.rows) == 1
    assert outcome.counts["thesaurusUnmatched"] == 1
    assert outcome.counts["apiTopicUnmatched"] == 1


def test_ambiguous_folded_label_inside_one_scheme_fails_closed() -> None:
    """Two terms folding to one key is a finding about the list, not an edge."""

    lines = [
        *_pair_lines(),
        *_term("urn:ref:atlas-test:fr:term-armed-forces-2", "ARMED FORCES"),
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    labels = fta.collect_fr_alignment_preferred_labels(lines, facts)
    with pytest.raises(fta.FrThesaurusApiTopicDerivationError, match="folded preferred label"):
        fta.resolve_fr_thesaurus_api_topic_edges(facts, labels)


def test_a_resource_with_two_preferred_labels_fails_closed() -> None:
    extra_node = "<urn:ref:atlas-test:label:term-armed-forces-extra>"
    lines = [
        *_pair_lines(),
        f"<{TERM}> {fta.SKOSXL_PREF_LABEL_TERM} {extra_node} {GRAPH} .",
        f'{extra_node} {fta.SKOSXL_LITERAL_FORM_TERM} "Armed Services" {GRAPH} .',
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    with pytest.raises(fta.FrThesaurusApiTopicDerivationError, match="exactly one"):
        fta.collect_fr_alignment_preferred_labels(lines, facts)


def test_non_subject_ring_endpoint_raises() -> None:
    lines = [*_term(TERM, "Armed Forces"), *_topic(TOPIC, "Armed Forces", ring=OTHER_RING)]
    context, labels = _context(lines)
    with pytest.raises(fta.FrThesaurusApiTopicDerivationError, match="subject ring"):
        fta.derive_fr_thesaurus_api_topic_rows(context, labels)


def test_endpoint_without_a_source_record_fails_closed() -> None:
    lines = [*_term(TERM, "Armed Forces"), *_topic(TOPIC, "Armed Forces", with_record=False)]
    facts = derived_graph.collect_asserted_fact_view(lines)
    labels = fta.collect_fr_alignment_preferred_labels(lines, facts)
    with pytest.raises(fta.FrThesaurusApiTopicDerivationError, match="source record"):
        fta.fr_thesaurus_api_topic_evidence_nodes(facts, labels)


@pytest.mark.parametrize(
    "triple",
    [
        (TERM, fta.SKOS_CLOSE_MATCH, TOPIC),
        (TOPIC, fta.SKOS_CLOSE_MATCH, TERM),
        (TERM, fta.SKOS_EXACT_MATCH, TOPIC),
        (TOPIC, fta.SKOS_EXACT_MATCH, TERM),
    ],
)
def test_asserted_relation_collision_fails_closed_in_all_four_orientations(
    triple: tuple[str, str, str],
) -> None:
    """closeMatch is symmetric under SKOS S43, so both orientations collide.

    Every prior rule derives ``skos:broader`` and mirrors to ``narrower``, so
    each had two orientations to check. This one has four: the symmetric
    predicate in both directions, plus an already-asserted ``exactMatch``,
    which is stronger and must not be shadowed by a derived weaker edge.
    """

    context, labels = _context(_pair_lines())
    with pytest.raises(fta.FrThesaurusApiTopicDerivationError, match="duplicates an asserted relation"):
        fta.derive_fr_thesaurus_api_topic_rows(
            context, labels, asserted_relations=frozenset({triple})
        )


def test_derivation_is_reproducible_from_the_same_facts() -> None:
    lines = _pair_lines()
    first_context, first_labels = _context(lines)
    second_context, second_labels = _context(lines)
    first = fta.derive_fr_thesaurus_api_topic_rows(first_context, first_labels)
    second = fta.derive_fr_thesaurus_api_topic_rows(second_context, second_labels)
    assert [row.node_iri for row in first.rows] == [row.node_iri for row in second.rows]
    assert [row.content_digest for row in first.rows] == [row.content_digest for row in second.rows]


def test_fold_is_strip_then_casefold_and_nothing_else() -> None:
    assert fta.fold("  Armed Forces  ") == "armed forces"
    assert fta.fold("ARMED FORCES") == fta.fold("armed forces")
    # Punctuation is deliberately NOT stripped: every extra transform widens
    # the population on evidence the label texts do not carry.
    assert fta.fold("Indians--Claims") != fta.fold("Indians Claims")


def _binding():
    if str(BINDING_TOOLS) not in sys.path:
        sys.path.insert(0, str(BINDING_TOOLS))
    import validate  # type: ignore[import-not-found]

    return validate


def test_binding_carries_the_same_rule_identity() -> None:
    """The binding stays importable standalone, so the constants live twice.

    Neither module imports the other; this is what keeps them honest.
    """

    validate = _binding()
    assert str(validate.FR_THESAURUS_API_TOPIC_RULE) == fta.FR_THESAURUS_API_TOPIC_RULE_IRI
    assert str(validate.FR_THESAURUS_API_TOPIC_ENGINE) == fta.FR_THESAURUS_API_TOPIC_ENGINE_IRI
    assert (
        validate.FR_THESAURUS_API_TOPIC_ENGINE_VERSION
        == fta.FR_THESAURUS_API_TOPIC_ENGINE_VERSION
    )
    assert str(validate.FR_COMPOUND_HEADING_SCHEME) == fta.FR_THESAURUS_SCHEME_IRI
    assert str(validate.FR_API_TOPICS_SCHEME) == fta.FR_API_TOPICS_SCHEME_IRI


def test_binding_and_producer_fold_identically() -> None:
    validate = _binding()
    for text in ("  Armed Forces  ", "ARMED FORCES", "Diesel fuel", "Indians--Claims"):
        assert validate._fr_label_fold(text) == fta.fold(text)


def test_binding_admits_the_rule_with_a_symmetric_mirror() -> None:
    """mirror_predicate is closeMatch itself, not an inverse.

    Every prior admission mirrors broader to narrower. Getting this wrong
    would make the binding's mirror check vacuous rather than loud.
    """

    validate = _binding()
    key = (
        validate.FR_THESAURUS_API_TOPIC_RULE,
        validate.FR_THESAURUS_API_TOPIC_ENGINE,
        validate.FR_THESAURUS_API_TOPIC_ENGINE_VERSION,
    )
    admission = validate._DERIVED_RULE_ADMISSIONS[key]
    assert admission.admitted_predicates == frozenset({validate.SKOS.closeMatch})
    assert admission.mirror_predicate == validate.SKOS.closeMatch
    assert admission.admitted_rings == frozenset({validate.ATLAS.subject})
    assert admission.evidence_kind == validate._EVIDENCE_KIND_SOURCE_RECORD


def test_producer_and_binding_agree_the_predicate_is_close_match_not_exact() -> None:
    """SKOS S45 makes exactMatch transitive; one bad edge contaminates chains.

    Label equality between two vocabularies does not license that. This test
    exists so a future widening has to be deliberate rather than a typo.
    """

    validate = _binding()
    assert fta.SKOS_CLOSE_MATCH == str(validate.SKOS.closeMatch)
    assert fta.SKOS_EXACT_MATCH == str(validate.SKOS.exactMatch)
    key = (
        validate.FR_THESAURUS_API_TOPIC_RULE,
        validate.FR_THESAURUS_API_TOPIC_ENGINE,
        validate.FR_THESAURUS_API_TOPIC_ENGINE_VERSION,
    )
    assert validate.SKOS.exactMatch not in validate._DERIVED_RULE_ADMISSIONS[key].admitted_predicates


def test_bijection_guard_is_defensive_the_index_fires_first() -> None:
    """Pin the ordering the bijection assertion's docstring claims.

    `_index_by_fold` admits one resource per folded key per scheme, so the
    later bijection check cannot fire while that holds. This test exists so
    that if someone relaxes the index to first-wins, the bijection guard
    stops being unreachable and this test says so by failing.
    """

    facts = derived_graph.AssertedFactView()
    for iri, scheme in (
        ("t1", THES_SCHEME),
        ("t2", THES_SCHEME),
        ("a1", API_SCHEME),
        ("a2", API_SCHEME),
    ):
        facts.schemes[iri] = scheme
    labels = {"t1": "Armed Forces", "t2": "armed forces", "a1": "ARMED FORCES", "a2": "ARMED forces"}
    with pytest.raises(fta.FrThesaurusApiTopicDerivationError) as excinfo:
        fta.resolve_fr_thesaurus_api_topic_edges(facts, labels)
    assert "folded preferred label" in str(excinfo.value)
    assert "bijection" not in str(excinfo.value)

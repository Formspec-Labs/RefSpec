"""Derived skos:broader edges from Federal Register compound headings.

The judgment mirrors the MeSH tree-number rule's (REF-042 in
docs/decisions.md): OFR's own compound-heading convention
(``Grant programs-agriculture`` is a heading whose head segment is
itself an official term) is publisher structure RefSpec already
captures verbatim as preferred labels, but expressing it as
``skos:broader`` is RefSpec's act, so it lives only in the derived graph
(REF-035 tier E5). These tests prove the derivation over synthetic
asserted facts, the shared ``refspec.atlas.derived_graph`` machinery
over real canonical N-Quads line shapes, content-derived identity that
matches the binding's OTHER digest formula, and the real pinned 2025
release (705 terms, 56 hyphenated, 48 edges, 8 self-excluded -- the 8
pinned by name, with no denylist anywhere in the rule).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from refspec.atlas import derived_graph
from refspec.atlas.derived_graph import fr_compound_headings as frch
from refspec.atlas.v3_registry_vocabularies import DEFAULT_SOURCE_ROOT, load_federal_register_2025_release

BINDING_TOOLS = Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1" / "tools"

GRAPH = "<urn:ref:atlas:graph:v3:asserted>"
FR_SCHEME = frch.FR_THESAURUS_SCHEME_IRI
SUBJECT_RING = frch.ATLAS_SUBJECT_RING

OTHER_SCHEME = "urn:ref:atlas-resource-scheme:some-other-vocabulary"

SELF_EXCLUDED_2025 = (
    "Government-sponsored enterprises",
    "Human cells and tissue-based products",
    "Old-age, Survivors and Disability Insurance",
    "Over-the-counter drugs",
    "Rights-of-way",
    "Truth-in-lending",
    "Truth-in-savings",
    "X-rays",
)

# Frozen against the pinned 2025 release: every one of the 48 derived
# edges, as (compound label, head label) text pairs. Counts alone cannot
# catch a mutation that picks the wrong segment or the wrong head; this
# exact set can.
FROZEN_2025_EDGE_LABEL_PAIRS = frozenset(
    {
        ("Grant programs-Indians", "Grant programs"),
        ("Grant programs-National defense", "Grant programs"),
        ("Grant programs-agriculture", "Grant programs"),
        ("Grant programs-business", "Grant programs"),
        ("Grant programs-communications", "Grant programs"),
        ("Grant programs-education", "Grant programs"),
        ("Grant programs-energy", "Grant programs"),
        ("Grant programs-environmental protection", "Grant programs"),
        ("Grant programs-foreign relations", "Grant programs"),
        ("Grant programs-health", "Grant programs"),
        ("Grant programs-housing and community development", "Grant programs"),
        ("Grant programs-labor", "Grant programs"),
        ("Grant programs-law", "Grant programs"),
        ("Grant programs-natural resources", "Grant programs"),
        ("Grant programs-recreation", "Grant programs"),
        ("Grant programs-science and technology", "Grant programs"),
        ("Grant programs-social programs", "Grant programs"),
        ("Grant programs-transportation", "Grant programs"),
        ("Grant programs-veterans", "Grant programs"),
        ("Indians-arts and crafts", "Indians"),
        ("Indians-business and finance", "Indians"),
        ("Indians-claims", "Indians"),
        ("Indians-education", "Indians"),
        ("Indians-enrollment", "Indians"),
        ("Indians-judgment funds", "Indians"),
        ("Indians-lands", "Indians"),
        ("Indians-law", "Indians"),
        ("Indians-tribal government", "Indians"),
        ("Loan programs-Indians", "Loan programs"),
        ("Loan programs-National defense", "Loan programs"),
        ("Loan programs-agriculture", "Loan programs"),
        ("Loan programs-business", "Loan programs"),
        ("Loan programs-communications", "Loan programs"),
        ("Loan programs-education", "Loan programs"),
        ("Loan programs-energy", "Loan programs"),
        ("Loan programs-foreign relations", "Loan programs"),
        ("Loan programs-health", "Loan programs"),
        ("Loan programs-housing and community development", "Loan programs"),
        ("Loan programs-natural resources", "Loan programs"),
        ("Loan programs-social programs", "Loan programs"),
        ("Loan programs-transportation", "Loan programs"),
        ("Loan programs-veterans", "Loan programs"),
        ("Public lands-classification", "Public lands"),
        ("Public lands-grants", "Public lands"),
        ("Public lands-mineral resources", "Public lands"),
        ("Public lands-rights-of-way", "Public lands"),
        ("Public lands-sale", "Public lands"),
        ("Public lands-withdrawal", "Public lands"),
    }
)


def _canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if terminal_lf:
        text += "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _label_node(resource_iri: str, role: str, value: str) -> str:
    digest = hashlib.sha256(f"{resource_iri}|{role}|{value}".encode()).hexdigest()[:16]
    return f"urn:ref:atlas-test:label:{digest}"


def _resource_lines(
    iri: str,
    *,
    preferred: str,
    alternates: tuple[str, ...] = (),
    scheme: str = FR_SCHEME,
    ring: str = SUBJECT_RING,
    with_record: bool = True,
    extra_label_lines: tuple[str, ...] = (),
) -> list[str]:
    subject = f"<{iri}>"
    record = f"<urn:ref:atlas-test:source-record:{iri.rsplit(':', 1)[-1]}>"
    lines = [f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{ring}> {GRAPH} ."]
    lines.append(f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{scheme}> {GRAPH} .")
    escaped = preferred.replace("\\", "\\\\").replace('"', '\\"')
    preferred_node = f"<{_label_node(iri, 'preferred', preferred)}>"
    lines.append(f"{subject} {frch.SKOSXL_PREF_LABEL_TERM} {preferred_node} {GRAPH} .")
    lines.append(f'{preferred_node} {frch.SKOSXL_LITERAL_FORM_TERM} "{escaped}"@en {GRAPH} .')
    for value in alternates:
        escaped_alt = value.replace("\\", "\\\\").replace('"', '\\"')
        alt_node = f"<{_label_node(iri, 'alternate', value)}>"
        lines.append(f"{subject} {frch.SKOSXL_ALT_LABEL_TERM} {alt_node} {GRAPH} .")
        lines.append(f'{alt_node} {frch.SKOSXL_LITERAL_FORM_TERM} "{escaped_alt}"@en {GRAPH} .')
    lines.extend(extra_label_lines)
    if with_record:
        lines.append(f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .")
    return lines


def _facts_labels_and_digests(
    lines: list[str],
) -> tuple[derived_graph.AssertedFactView, dict[str, str], dict[str, str]]:
    facts = derived_graph.collect_asserted_fact_view(lines)
    labels = frch.collect_fr_preferred_labels(lines, facts)
    wanted = frch.fr_compound_heading_evidence_nodes(facts, labels)
    node_digest = derived_graph.collect_node_digests(lines, wanted)
    return facts, labels, node_digest


def _context(
    lines: list[str],
    *,
    generated_at: str = "2026-01-01T00:00:00+00:00",
) -> tuple[derived_graph.DerivationContext, dict[str, str]]:
    facts, labels, node_digest = _facts_labels_and_digests(lines)
    context = derived_graph.DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=_canonical_sha256,
        generated_at=generated_at,
    )
    return context, labels


GRANT_PAIR = [
    *_resource_lines("urn:ref:atlas-test:fr:grant-programs", preferred="Grant programs"),
    *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
]


def test_compound_heading_derives_one_edge() -> None:
    context, labels = _context(GRANT_PAIR)

    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert outcome.counts == {
        "edges": 1,
        "preferredTerms": 2,
        "hyphenatedTerms": 1,
        "selfExcluded": 0,
    }
    assert len(outcome.rows) == 1
    row = outcome.rows[0]
    assert row.subject == "urn:ref:atlas-test:fr:grant-agriculture"
    assert row.object == "urn:ref:atlas-test:fr:grant-programs"
    assert row.predicate == frch.SKOS_BROADER
    assert row.ring == SUBJECT_RING
    assert row.rule_iri == frch.FR_COMPOUND_HEADING_RULE_IRI
    assert row.engine_iri == frch.FR_COMPOUND_HEADING_ENGINE_IRI
    assert row.engine_version == frch.FR_COMPOUND_HEADING_ENGINE_VERSION
    assert row.generated_at == "2026-01-01T00:00:00+00:00"
    assert row.node_iri == "urn:ref:atlas-derived:" + row.content_digest.removeprefix("sha256:")
    # build_derived_row sorts cited evidence by node IRI; the compound's
    # synthetic record IRI sorts before the head's here.
    assert row.evidence == tuple(
        sorted(
            (
                f"urn:ref:atlas-test:source-record:{row.subject.rsplit(':', 1)[-1]}",
                f"urn:ref:atlas-test:source-record:{row.object.rsplit(':', 1)[-1]}",
            )
        )
    )


def test_head_extraction_stops_at_the_first_hyphen() -> None:
    # The head is the text before the FIRST hyphen only: "A-b-c" heads at
    # "A", never at "A-b", and nothing recurses toward deeper segments.
    lines = [
        *_resource_lines("urn:ref:atlas-test:fr:a", preferred="A"),
        *_resource_lines("urn:ref:atlas-test:fr:a-b", preferred="A-b"),
        *_resource_lines("urn:ref:atlas-test:fr:a-b-c", preferred="A-b-c"),
    ]
    context, labels = _context(lines)

    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert outcome.counts["edges"] == 2
    assert outcome.counts["hyphenatedTerms"] == 2
    pairs = {(row.subject, row.object) for row in outcome.rows}
    assert pairs == {
        ("urn:ref:atlas-test:fr:a-b", "urn:ref:atlas-test:fr:a"),
        ("urn:ref:atlas-test:fr:a-b-c", "urn:ref:atlas-test:fr:a"),
    }


@pytest.mark.parametrize("label", SELF_EXCLUDED_2025)
def test_the_eight_hyphenated_words_exclude_themselves(label: str) -> None:
    # Each of the real release's 8 hyphenated words, alone in the scheme:
    # no head term exists, so no edge -- and the rule carries no denylist,
    # so this must hold purely because the head is not a preferred term.
    lines = _resource_lines("urn:ref:atlas-test:fr:word", preferred=label)
    context, labels = _context(lines)

    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert outcome.counts == {
        "edges": 0,
        "preferredTerms": 1,
        "hyphenatedTerms": 1,
        "selfExcluded": 1,
    }
    assert outcome.rows == ()


@pytest.mark.parametrize(
    ("compound", "minted_head"),
    (
        ("X-rays", "X"),
        ("Truth-in-lending", "Truth"),
    ),
)
def test_no_denylist_a_minted_head_term_immediately_admits_the_edge(
    compound: str,
    minted_head: str,
) -> None:
    # The converse self-exclusion check: mint the head as a preferred
    # term and the very same hyphenated word derives its edge. A
    # hand-maintained denylist would refuse it; the rule has none.
    lines = [
        *_resource_lines("urn:ref:atlas-test:fr:minted", preferred=minted_head),
        *_resource_lines("urn:ref:atlas-test:fr:compound", preferred=compound),
    ]
    context, labels = _context(lines)

    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert len(outcome.rows) == 1
    assert outcome.rows[0].subject == "urn:ref:atlas-test:fr:compound"
    assert outcome.rows[0].object == "urn:ref:atlas-test:fr:minted"
    assert outcome.counts["selfExcluded"] == 0


def test_head_term_in_another_scheme_admits_no_edge() -> None:
    # The adversarial scope check: the head text exists as a preferred
    # label, but in a DIFFERENT vocabulary's scheme. Without the scheme
    # gate, unrelated concepts would become admissible heads (the exact
    # scheme-blind bug the MeSH rule shipped with).
    lines = [
        *_resource_lines(
            "urn:ref:atlas-test:other:grant-programs",
            preferred="Grant programs",
            scheme=OTHER_SCHEME,
        ),
        *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
    ]
    context, labels = _context(lines)

    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert outcome.counts == {
        "edges": 0,
        "preferredTerms": 1,
        "hyphenatedTerms": 1,
        "selfExcluded": 1,
    }
    assert outcome.rows == ()


def test_head_matching_only_an_alternate_label_admits_no_edge() -> None:
    # "Grant programs" exists only as another FR term's ALTERNATE label:
    # not an authorized preferred term, so no edge. Alternate labels ride
    # the same lines the collector reads and must not leak into the map.
    lines = [
        *_resource_lines(
            "urn:ref:atlas-test:fr:some-term",
            preferred="Some term",
            alternates=("Grant programs",),
        ),
        *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
    ]
    context, labels = _context(lines)

    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert outcome.counts["selfExcluded"] == 1
    assert outcome.rows == ()


def test_ambiguous_preferred_label_fails_closed() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:fr:grant-1", preferred="Grant programs"),
        *_resource_lines("urn:ref:atlas-test:fr:grant-2", preferred="Grant programs"),
        *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    labels = frch.collect_fr_preferred_labels(lines, facts)
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="ambiguous between two terms"):
        frch.resolve_fr_compound_heading_edges(facts, labels)


def test_term_with_two_preferred_labels_raises() -> None:
    lines = [
        *_resource_lines(
            "urn:ref:atlas-test:fr:grant",
            preferred="Grant programs",
            extra_label_lines=(
                (
                    f'<urn:ref:atlas-test:fr:grant> {frch.SKOSXL_PREF_LABEL_TERM} '
                    f'<urn:ref:atlas-test:label:second> {GRAPH} .'
                ),
            ),
        ),
        *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="exactly one preferred label"):
        frch.collect_fr_preferred_labels(lines, facts)


def test_preferred_label_without_literal_form_raises() -> None:
    node = "<urn:ref:atlas-test:label:formless>"
    subject = "<urn:ref:atlas-test:fr:grant>"
    lines = [
        f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .",
        f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{FR_SCHEME}> {GRAPH} .",
        f"{subject} {frch.SKOSXL_PREF_LABEL_TERM} {node} {GRAPH} .",
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="has no literal form"):
        frch.collect_fr_preferred_labels(lines, facts)


def test_untrimmed_label_text_raises() -> None:
    node = "<urn:ref:atlas-test:label:padded>"
    subject = "<urn:ref:atlas-test:fr:grant>"
    lines = [
        f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .",
        f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{FR_SCHEME}> {GRAPH} .",
        f"{subject} {frch.SKOSXL_PREF_LABEL_TERM} {node} {GRAPH} .",
        f'{node} {frch.SKOSXL_LITERAL_FORM_TERM} " Grant programs "@en {GRAPH} .',
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="non-empty trimmed text"):
        frch.collect_fr_preferred_labels(lines, facts)


def test_non_subject_ring_endpoint_raises() -> None:
    lines = [
        *_resource_lines(
            "urn:ref:atlas-test:fr:grant-programs",
            preferred="Grant programs",
            ring="https://refspec.org/ns/atlas/v3#value",
        ),
        *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
    ]
    context, labels = _context(lines)
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="not in the subject ring"):
        frch.derive_fr_compound_heading_broader_rows(context, labels)


def test_evidence_nodes_missing_source_record_raises() -> None:
    lines = [
        *_resource_lines(
            "urn:ref:atlas-test:fr:grant-programs",
            preferred="Grant programs",
            with_record=False,
        ),
        *_resource_lines("urn:ref:atlas-test:fr:grant-agriculture", preferred="Grant programs-agriculture"),
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    labels = frch.collect_fr_preferred_labels(lines, facts)
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="no source record"):
        frch.fr_compound_heading_evidence_nodes(facts, labels)


def test_asserted_relation_collision_fails_closed_in_both_directions() -> None:
    compound = "urn:ref:atlas-test:fr:grant-agriculture"
    head = "urn:ref:atlas-test:fr:grant-programs"
    context, labels = _context(GRANT_PAIR)

    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="duplicates an asserted"):
        frch.derive_fr_compound_heading_broader_rows(
            context,
            labels,
            asserted_relations=frozenset({(compound, frch.SKOS_BROADER, head)}),
        )
    with pytest.raises(frch.FrCompoundHeadingDerivationError, match="duplicates an asserted"):
        frch.derive_fr_compound_heading_broader_rows(
            context,
            labels,
            asserted_relations=frozenset({(head, frch.SKOS_NARROWER, compound)}),
        )
    unrelated = frch.derive_fr_compound_heading_broader_rows(
        context,
        labels,
        asserted_relations=frozenset({(compound, frch.SKOS_BROADER, "urn:ref:atlas-test:fr:other")}),
    )
    assert len(unrelated.rows) == 1


def test_associative_related_assertions_do_not_block_the_edge() -> None:
    # skos:related is associative, not hierarchical: the real release
    # asserts 1,451 of them and zero broader/narrower. A related
    # assertion between the same pair must not read as a collision.
    context, labels = _context(GRANT_PAIR)
    outcome = frch.derive_fr_compound_heading_broader_rows(
        context,
        labels,
        asserted_relations=frozenset(
            {
                (
                    "urn:ref:atlas-test:fr:grant-agriculture",
                    "http://www.w3.org/2004/02/skos/core#related",
                    "urn:ref:atlas-test:fr:grant-programs",
                )
            }
        ),
    )
    assert len(outcome.rows) == 1


def test_derivation_is_reproducible_from_the_same_facts() -> None:
    context, labels = _context(GRANT_PAIR)
    first = frch.derive_fr_compound_heading_broader_rows(context, labels)
    second = frch.derive_fr_compound_heading_broader_rows(context, labels)

    assert [row.node_iri for row in first.rows] == [row.node_iri for row in second.rows]
    assert first.rows == second.rows


def test_rule_registers_into_the_shared_registry() -> None:
    # The integrator's two registration lines (see the module report) do
    # exactly this; prove they work and stay side-effect-free.
    try:
        derived_graph.register_derivation_rule(frch.FR_COMPOUND_HEADING_BROADER_RULE)
        rules = {rule.rule_iri for rule in derived_graph.registered_derivation_rules()}
        assert frch.FR_COMPOUND_HEADING_RULE_IRI in rules
        # The shared collector must parse this rule's watched SKOS-XL
        # lines without error once they are watched.
        facts = derived_graph.collect_asserted_fact_view(GRANT_PAIR)
        assert facts.schemes["urn:ref:atlas-test:fr:grant-programs"] == FR_SCHEME
        # Re-registering the identical rule is a no-op, not an error.
        derived_graph.register_derivation_rule(frch.FR_COMPOUND_HEADING_BROADER_RULE)
    finally:
        derived_graph.reset_derivation_rule_registry()
    assert frch.FR_COMPOUND_HEADING_RULE_IRI not in {
        rule.rule_iri for rule in derived_graph.registered_derivation_rules()
    }


def test_content_digest_matches_an_actual_rdflib_render() -> None:
    """`build_derived_row`'s content digest must equal `rdf_node_digest`
    over the row's own rendered triples, computed independently with the
    binding's real rdflib-based canonical renderer -- not merely a formula
    this module asserts agrees with itself."""

    sys.path.insert(0, str(BINDING_TOOLS))
    try:
        import rdf_canonical
        from rdflib import RDF, Graph, Literal, Namespace, URIRef
    finally:
        sys.path.remove(str(BINDING_TOOLS))

    context, labels = _context(GRANT_PAIR)
    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels)
    row = outcome.rows[0]

    atlas = Namespace("https://refspec.org/ns/atlas/v3#")
    rkaf = Namespace("https://rulespec.org/ns/v1#")
    graph = Graph()
    node = URIRef("urn:ref:atlas-test:pending")
    graph.add((node, RDF.type, atlas.DerivedRelation))
    graph.add((node, atlas.relationSubject, URIRef(row.subject)))
    graph.add((node, atlas.relationPredicate, URIRef(row.predicate)))
    graph.add((node, atlas.relationObject, URIRef(row.object)))
    for evidence in row.evidence:
        graph.add((node, atlas.derivedFromAssertion, URIRef(evidence)))
    graph.add((node, atlas.semanticRing, URIRef(row.ring)))
    graph.add((node, atlas.derivationRule, URIRef(row.rule_iri)))
    graph.add((node, atlas.engine, URIRef(row.engine_iri)))
    graph.add((node, atlas.engineVersion, Literal(row.engine_version)))
    graph.add((node, rkaf.inputDigest, Literal(row.input_digest)))
    graph.add(
        (
            node,
            atlas.generatedAt,
            Literal(row.generated_at, datatype=rdf_canonical.URIRef("http://www.w3.org/2001/XMLSchema#dateTime")),
        )
    )
    self_digest_predicates = {atlas.contentDigest, rkaf.proofRecordDigest}
    rendered_rows = sorted(
        f"{rdf_canonical.ntriples_term(predicate)} {rdf_canonical.ntriples_term(obj)} ."
        for predicate, obj in graph.predicate_objects(node)
        if predicate not in self_digest_predicates
    )
    expected_digest = "sha256:" + hashlib.sha256(("\n".join(rendered_rows) + "\n").encode("utf-8")).hexdigest()

    assert row.content_digest == expected_digest
    assert row.node_iri == "urn:ref:atlas-derived:" + expected_digest.removeprefix("sha256:")


def test_binding_entry_when_present_names_the_same_rule_identity() -> None:
    """Once the integrator lands the binding-side admission entry, its
    constants must name the same rule this module registers -- the same
    producer/binding sync check the MeSH rule carries, dormant until the
    entry exists rather than blind to it."""

    sys.path.insert(0, str(BINDING_TOOLS))
    try:
        import validate as atlas_validate
    finally:
        sys.path.remove(str(BINDING_TOOLS))

    binding_rule = getattr(atlas_validate, "FR_COMPOUND_HEADING_BROADER_RULE", None)
    if binding_rule is None:
        pytest.skip("the binding has not landed its FR compound-heading admission entry yet")
    assert str(binding_rule) == frch.FR_COMPOUND_HEADING_RULE_IRI
    assert str(atlas_validate.FR_COMPOUND_HEADING_ENGINE) == frch.FR_COMPOUND_HEADING_ENGINE_IRI
    assert atlas_validate.FR_COMPOUND_HEADING_ENGINE_VERSION == (
        frch.FR_COMPOUND_HEADING_ENGINE_VERSION
    )


@pytest.mark.skipif(
    not (DEFAULT_SOURCE_ROOT / "federal-register-thesaurus-2025.pdf").is_file(),
    reason="exact cached Federal Register 2025 thesaurus PDF is not available",
)
def test_real_2025_release_derives_the_frozen_edge_set() -> None:
    release = load_federal_register_2025_release()
    lines = frch.build_fr_thesaurus_asserted_nquads_lines(release)
    context, labels = _context(lines)

    # The flat-vocabulary premise, from the release itself.
    assert len(release.resources) == frch.FR_2025_PREFERRED_TERM_COUNT
    assert {relation.predicate for relation in release.relations} == {
        "http://www.w3.org/2004/02/skos/core#related"
    }
    assert len(release.relations) == 1_451

    # Thread the release's own 1,451 related assertions through the
    # collision check, proving none of them collide with a derived edge.
    asserted_relations = frozenset(
        (relation.subject, relation.predicate, relation.object) for relation in release.relations
    )
    outcome = frch.derive_fr_compound_heading_broader_rows(context, labels, asserted_relations=asserted_relations)

    assert outcome.counts == {
        "edges": frch.FR_2025_COMPOUND_EDGE_COUNT,
        "preferredTerms": frch.FR_2025_PREFERRED_TERM_COUNT,
        "hyphenatedTerms": frch.FR_2025_HYPHENATED_TERM_COUNT,
        "selfExcluded": frch.FR_2025_SELF_EXCLUDED_TERM_COUNT,
    }
    assert len(outcome.rows) == frch.FR_2025_COMPOUND_EDGE_COUNT

    edge_label_pairs = {(labels[row.subject], labels[row.object]) for row in outcome.rows}
    assert edge_label_pairs == FROZEN_2025_EDGE_LABEL_PAIRS

    hyphenated_texts = {text for text in labels.values() if "-" in text}
    admitted_compounds = {labels[row.subject] for row in outcome.rows}
    assert hyphenated_texts - admitted_compounds == set(SELF_EXCLUDED_2025)
    assert len(SELF_EXCLUDED_2025) == frch.FR_2025_SELF_EXCLUDED_TERM_COUNT

    again = frch.derive_fr_compound_heading_broader_rows(context, labels)
    assert [row.node_iri for row in outcome.rows] == [row.node_iri for row in again.rows]

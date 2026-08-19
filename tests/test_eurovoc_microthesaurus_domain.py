"""Derived skos:broader edges from EuroVoc microthesaurus notation prefixes.

REF-045 (docs/decisions.md) found the Publications Office never asserts a
microthesaurus's domain; REF-046 promotes the notation-prefix link into the
derived graph's fifth registered rule and the module beside it into a real
Atlas release. These tests prove the derivation over synthetic asserted
facts -- including the scope lesson the MeSH rule shipped without, applied
here to BOTH endpoints since this is the first rule whose subject and
object sit in two different schemes -- content-derived identity that
matches the binding's ``rdf_node_digest`` formula, the constant agreement
between this producer module and the binding's standalone validator, and
-- when the pinned 4.24 release is cached -- that the asserted-graph path
reproduces the frozen 127-edge set.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from refspec.atlas import derived_graph
from refspec.atlas.derived_graph import eurovoc_microthesaurus_domain as emd
from refspec.atlas.v3_registry_vocabularies import (
    DEFAULT_SOURCE_ROOT,
    load_eurovoc_4_24_releases,
    load_eurovoc_microthesauri_4_24_release,
)

BINDING_TOOLS = Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1" / "tools"

GRAPH = "<urn:ref:atlas:graph:v3:asserted>"
MICRO_SCHEME = emd.EUROVOC_MICROTHESAURI_SCHEME_IRI
DOMAIN_SCHEME = emd.EUROVOC_DOMAINS_SCHEME_IRI
SUBJECT_RING = emd.ATLAS_SUBJECT_RING


def _canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if terminal_lf:
        text += "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resource_lines(
    iri: str,
    *,
    notation: str,
    scheme: str,
    ring: str = SUBJECT_RING,
) -> list[str]:
    subject = f"<{iri}>"
    record = f"<urn:ref:atlas-test:source-record:{iri.rsplit(':', 1)[-1]}>"
    return [
        f'{subject} {derived_graph.ATLAS_NOTATION_TERM} "{notation}" {GRAPH} .',
        f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{scheme}> {GRAPH} .",
        f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{ring}> {GRAPH} .",
        f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .",
    ]


def _facts_and_digests(lines: list[str]) -> tuple[derived_graph.AssertedFactView, dict[str, str]]:
    facts = derived_graph.collect_asserted_fact_view(lines)
    wanted = emd.eurovoc_microthesaurus_domain_evidence_nodes(facts)
    node_digest = derived_graph.collect_node_digests(lines, wanted)
    return facts, node_digest


def _context(
    lines: list[str],
    *,
    generated_at: str = "2026-01-01T00:00:00+00:00",
) -> derived_graph.DerivationContext:
    facts, node_digest = _facts_and_digests(lines)
    return derived_graph.DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=_canonical_sha256,
        generated_at=generated_at,
    )


MICRO_A = "urn:ref:atlas-test:eurovoc:micro-0406"
MICRO_B = "urn:ref:atlas-test:eurovoc:micro-0411"
DOMAIN = "urn:ref:atlas-test:eurovoc:domain-04"


def _micro(iri: str, notation: str, *, scheme: str = MICRO_SCHEME) -> list[str]:
    return _resource_lines(iri, notation=notation, scheme=scheme)


def _domain(iri: str, notation: str, *, scheme: str = DOMAIN_SCHEME) -> list[str]:
    return _resource_lines(iri, notation=notation, scheme=scheme)


def _pair_lines() -> list[str]:
    return [*_micro(MICRO_A, "0406"), *_domain(DOMAIN, "04")]


def test_simple_microthesaurus_and_domain_derives_one_edge() -> None:
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(_pair_lines()))

    assert outcome.counts == {
        "edges": 1,
        "microthesauri": 1,
        "missingDomain": 0,
        "ambiguousDomain": 0,
        "malformedNotation": 0,
    }
    assert len(outcome.rows) == 1
    row = outcome.rows[0]
    assert row.subject == MICRO_A
    assert row.object == DOMAIN
    assert row.predicate == emd.SKOS_BROADER
    assert row.ring == SUBJECT_RING
    assert row.rule_iri == emd.EUROVOC_MICROTHESAURUS_DOMAIN_RULE_IRI
    assert row.engine_iri == emd.EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_IRI
    assert row.engine_version == emd.EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_VERSION
    assert row.node_iri == "urn:ref:atlas-derived:" + row.content_digest.removeprefix("sha256:")


def test_each_edge_cites_the_two_exact_endpoint_records() -> None:
    facts, _digests = _facts_and_digests(_pair_lines())
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(_pair_lines()))

    micro_record = facts.records[MICRO_A]
    domain_record = facts.records[DOMAIN]
    assert outcome.rows[0].evidence == tuple(sorted((micro_record, domain_record)))


def test_two_microthesauri_share_one_domain() -> None:
    lines = [*_micro(MICRO_A, "0406"), *_micro(MICRO_B, "0411"), *_domain(DOMAIN, "04")]
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))

    assert outcome.counts["edges"] == 2
    assert {(row.subject, row.object) for row in outcome.rows} == {
        (MICRO_A, DOMAIN),
        (MICRO_B, DOMAIN),
    }


def test_scheme_scopes_the_rule_on_both_endpoints_not_notation_shape() -> None:
    # The MeSH rule shipped scheme-blind and proved parentage from notation
    # shape alone. This rule is scoped on BOTH sides: a foreign-scheme
    # resource carrying a perfectly microthesaurus-shaped notation admits
    # nothing, and neither does a foreign-scheme resource carrying a
    # perfectly domain-shaped notation -- while the real pair still does.
    lines = [
        *_pair_lines(),
        *_resource_lines(
            "urn:ref:atlas-test:other:lookalike-micro",
            notation="0499",
            scheme="urn:ref:atlas-resource-scheme:mesh-descriptors",
        ),
        *_resource_lines(
            "urn:ref:atlas-test:other:lookalike-domain",
            notation="04",
            scheme="urn:ref:atlas-resource-scheme:mesh-descriptors",
        ),
    ]
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))

    assert outcome.counts["edges"] == 1
    assert [(row.subject, row.object) for row in outcome.rows] == [(MICRO_A, DOMAIN)]


def test_release_nodes_in_scheme_without_a_record_are_not_candidates() -> None:
    lines = [
        *_pair_lines(),
        f"<urn:ref:atlas-release:3:eurovoc-microthesauri:4.24> {derived_graph.ATLAS_IN_SCHEME_TERM} <{MICRO_SCHEME}> {GRAPH} .",
        f"<urn:ref:atlas-release:3:eurovoc-domains:4.24> {derived_graph.ATLAS_IN_SCHEME_TERM} <{DOMAIN_SCHEME}> {GRAPH} .",
    ]
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))

    assert outcome.counts["edges"] == 1


def test_missing_domain_is_counted_never_guessed() -> None:
    lines = _micro(MICRO_A, "0406")  # no domain "04" resource at all
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))

    assert outcome.counts == {
        "edges": 0,
        "microthesauri": 1,
        "missingDomain": 1,
        "ambiguousDomain": 0,
        "malformedNotation": 0,
    }
    assert outcome.rows == ()


def test_ambiguous_domain_is_counted_never_guessed() -> None:
    lines = [
        *_micro(MICRO_A, "0406"),
        *_domain(DOMAIN, "04"),
        *_domain("urn:ref:atlas-test:eurovoc:domain-04-again", "04"),
    ]
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))

    assert outcome.counts == {
        "edges": 0,
        "microthesauri": 1,
        "missingDomain": 0,
        "ambiguousDomain": 1,
        "malformedNotation": 0,
    }


def test_malformed_microthesaurus_notation_is_counted_never_truncated() -> None:
    lines = [*_micro(MICRO_A, "not-four-digits"), *_domain(DOMAIN, "04")]
    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))

    assert outcome.counts == {
        "edges": 0,
        "microthesauri": 1,
        "missingDomain": 0,
        "ambiguousDomain": 0,
        "malformedNotation": 1,
    }


def test_domain_without_exactly_one_notation_fails_closed() -> None:
    lines = [
        *_micro(MICRO_A, "0406"),
        f"<{DOMAIN}> {derived_graph.ATLAS_IN_SCHEME_TERM} <{DOMAIN_SCHEME}> {GRAPH} .",
        f"<{DOMAIN}> {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .",
        f"<urn:ref:atlas-test:source-record:domain-04> {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} <{DOMAIN}> {GRAPH} .",
    ]
    with pytest.raises(emd.EuroVocMicrothesaurusDomainDerivationError, match="exactly one notation"):
        emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))


def test_non_subject_ring_endpoint_raises() -> None:
    lines = [
        *_resource_lines(MICRO_A, notation="0406", scheme=MICRO_SCHEME, ring="https://refspec.org/ns/atlas/v3#value"),
        *_domain(DOMAIN, "04"),
    ]
    with pytest.raises(emd.EuroVocMicrothesaurusDomainDerivationError, match="not in the subject ring"):
        emd.derive_eurovoc_microthesaurus_domain_rows(_context(lines))


def test_asserted_relation_collision_fails_closed_in_both_directions() -> None:
    context = _context(_pair_lines())

    with pytest.raises(emd.EuroVocMicrothesaurusDomainDerivationError, match="duplicates an asserted"):
        emd.derive_eurovoc_microthesaurus_domain_rows(
            context,
            asserted_relations=frozenset({(MICRO_A, emd.SKOS_BROADER, DOMAIN)}),
        )
    with pytest.raises(emd.EuroVocMicrothesaurusDomainDerivationError, match="duplicates an asserted"):
        emd.derive_eurovoc_microthesaurus_domain_rows(
            context,
            asserted_relations=frozenset({(DOMAIN, emd.SKOS_NARROWER, MICRO_A)}),
        )
    unrelated = emd.derive_eurovoc_microthesaurus_domain_rows(
        context,
        asserted_relations=frozenset({(MICRO_A, emd.SKOS_BROADER, "urn:ref:atlas-test:eurovoc:other")}),
    )
    assert len(unrelated.rows) == 1


def test_derivation_is_reproducible_from_the_same_facts() -> None:
    context = _context(_pair_lines())
    first = emd.derive_eurovoc_microthesaurus_domain_rows(context)
    second = emd.derive_eurovoc_microthesaurus_domain_rows(context)

    assert [row.node_iri for row in first.rows] == [row.node_iri for row in second.rows]
    assert first.rows == second.rows


def test_content_digest_matches_an_actual_rdflib_render() -> None:
    """`build_derived_row`'s digest must equal `rdf_node_digest` over the
    row's own rendered triples, computed with the binding's real renderer."""

    sys.path.insert(0, str(BINDING_TOOLS))
    try:
        import rdf_canonical
        from rdflib import RDF, Graph, Literal, Namespace, URIRef
    finally:
        sys.path.remove(str(BINDING_TOOLS))

    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(_context(_pair_lines()))
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


def test_binding_carries_the_same_rule_identity() -> None:
    """The producer-side constants and the binding's allowlist entry must
    name the same rule -- proven by comparing them directly, not by
    duplicating the literal strings in two places and hoping."""

    sys.path.insert(0, str(BINDING_TOOLS))
    try:
        import validate as atlas_validate
    finally:
        sys.path.remove(str(BINDING_TOOLS))

    assert str(atlas_validate.EUROVOC_MICROTHESAURUS_DOMAIN_RULE) == emd.EUROVOC_MICROTHESAURUS_DOMAIN_RULE_IRI
    assert str(atlas_validate.EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE) == emd.EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_IRI
    assert (
        atlas_validate.EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_VERSION
        == emd.EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_VERSION
    )
    assert str(atlas_validate.EUROVOC_MICROTHESAURI_SCHEME) == emd.EUROVOC_MICROTHESAURI_SCHEME_IRI
    assert str(atlas_validate.EUROVOC_DOMAINS_SCHEME) == emd.EUROVOC_DOMAINS_SCHEME_IRI
    assert atlas_validate.EUROVOC_MICROTHESAURUS_DOMAIN_RULE not in {
        atlas_validate.EXACT_MATCH_TRANSITIVITY_RULE,
        atlas_validate.MESH_TREE_NUMBER_BROADER_RULE,
        atlas_validate.GCMD_COLUMN_NESTING_RULE,
        atlas_validate.FR_COMPOUND_HEADING_BROADER_RULE,
    }


def test_validator_row_and_replay_are_scoped_to_both_eurovoc_schemes() -> None:
    """The binding-side scope check proven directly for this rule, on BOTH
    endpoints: a row whose subject sits outside the microthesauri scheme,
    or whose object sits outside the domains scheme, is refused even when
    its evidence and notation parentage are perfect, and the whole-of-rule
    replay never demands an edge for either foreign-scheme shape."""

    sys.path.insert(0, str(BINDING_TOOLS))
    try:
        import validate as atlas_validate
        from rdflib import RDF, Graph, Literal
        from rdflib import URIRef as BindingURIRef
        from rdflib.namespace import SKOS as BindingSKOS
    finally:
        sys.path.remove(str(BINDING_TOOLS))

    atlas = atlas_validate.ATLAS
    mesh_scheme = atlas_validate.MESH_TREE_NUMBER_SCHEME

    def endpoint_graph(
        subject_iri: str,
        record_iri: str,
        *,
        scheme: str,
        notation: str,
    ) -> tuple[list[tuple], BindingURIRef, BindingURIRef]:
        subject = BindingURIRef(subject_iri)
        record = BindingURIRef(record_iri)
        triples = [
            (subject, atlas.notation, Literal(notation)),
            (subject, atlas.inScheme, BindingURIRef(scheme)),
            (subject, atlas.semanticRing, atlas.subject),
            (record, atlas.representsResource, subject),
        ]
        return triples, subject, record

    def derived_row(node_iri: str, subject: BindingURIRef, obj: BindingURIRef, *evidence: BindingURIRef) -> Graph:
        derived = Graph()
        node = BindingURIRef(node_iri)
        derived.add((node, RDF.type, atlas.DerivedRelation))
        derived.add((node, atlas.relationSubject, subject))
        derived.add((node, atlas.relationPredicate, BindingSKOS.broader))
        derived.add((node, atlas.relationObject, obj))
        for record in evidence:
            derived.add((node, atlas.derivedFromAssertion, record))
        return derived

    # A foreign-scheme "microthesaurus" whose notation still nests
    # perfectly under a real domain: the row check must refuse it on the
    # subject's scheme alone.
    foreign_triples, foreign_micro, foreign_micro_record = endpoint_graph(
        "urn:ref:atlas-test:foreign:micro",
        "urn:ref:atlas-test:foreign:record:micro",
        scheme=str(mesh_scheme),
        notation="0406",
    )
    domain_triples, real_domain, real_domain_record = endpoint_graph(
        DOMAIN,
        "urn:ref:atlas-test:eurovoc:record:domain-04",
        scheme=DOMAIN_SCHEME,
        notation="04",
    )
    asserted = Graph()
    for triple in (*foreign_triples, *domain_triples):
        asserted.add(triple)

    row_context = atlas_validate._DerivedRowContext(
        node=BindingURIRef("urn:ref:atlas-test:foreign-micro:row"),
        subject=foreign_micro,
        predicate=BindingSKOS.broader,
        obj=real_domain,
        ring=atlas.subject,
        inputs=frozenset({foreign_micro_record, real_domain_record}),
        asserted=asserted,
    )
    with pytest.raises(atlas_validate.AtlasValidationError, match="not in the EuroVoc microthesauri scheme"):
        atlas_validate._validate_eurovoc_microthesaurus_domain_row(row_context)

    # A real microthesaurus paired against a foreign-scheme "domain": the
    # row check must refuse it on the object's scheme alone.
    micro_triples, real_micro, real_micro_record = endpoint_graph(
        MICRO_A,
        "urn:ref:atlas-test:eurovoc:record:micro-0406",
        scheme=MICRO_SCHEME,
        notation="0406",
    )
    foreign_domain_triples, foreign_domain, foreign_domain_record = endpoint_graph(
        "urn:ref:atlas-test:foreign:domain",
        "urn:ref:atlas-test:foreign:record:domain",
        scheme=str(mesh_scheme),
        notation="04",
    )
    for triple in (*micro_triples, *foreign_domain_triples):
        asserted.add(triple)
    row_context = atlas_validate._DerivedRowContext(
        node=BindingURIRef("urn:ref:atlas-test:foreign-domain:row"),
        subject=real_micro,
        predicate=BindingSKOS.broader,
        obj=foreign_domain,
        ring=atlas.subject,
        inputs=frozenset({real_micro_record, foreign_domain_record}),
        asserted=asserted,
    )
    with pytest.raises(atlas_validate.AtlasValidationError, match="not in the EuroVoc domains scheme"):
        atlas_validate._validate_eurovoc_microthesaurus_domain_row(row_context)

    # The real pair beside both foreign shapes: the replay regenerates
    # exactly the one in-scheme edge and never demands one for either
    # foreign endpoint -- the scope lesson applied to the whole-of-rule
    # proof, on both sides at once.
    derived = derived_row(
        "urn:ref:atlas-test:eurovoc:row",
        real_micro,
        real_domain,
        real_micro_record,
        real_domain_record,
    )
    atlas_validate._replay_eurovoc_microthesaurus_domain(
        {next(derived.subjects(RDF.type, atlas.DerivedRelation))},
        derived=derived,
        asserted=asserted,
    )


@pytest.mark.skipif(
    not (DEFAULT_SOURCE_ROOT / "eurovoc-4.24-skos-core.zip").is_file(),
    reason="exact cached EuroVoc 4.24 SKOS Core archive is not available",
)
def test_real_4_24_release_reproduces_the_frozen_edge_set() -> None:
    _concepts, domains = load_eurovoc_4_24_releases()
    microthesauri = load_eurovoc_microthesauri_4_24_release()
    lines = emd.build_eurovoc_microthesaurus_domain_asserted_nquads_lines(microthesauri, domains)
    context = _context(list(lines))

    outcome = emd.derive_eurovoc_microthesaurus_domain_rows(context)

    assert outcome.counts == {
        "edges": emd.EUROVOC_4_24_DERIVED_EDGE_COUNT,
        "microthesauri": emd.EUROVOC_4_24_MICROTHESAURUS_COUNT,
        "missingDomain": emd.EUROVOC_4_24_MISSING_DOMAIN_COUNT,
        "ambiguousDomain": emd.EUROVOC_4_24_AMBIGUOUS_DOMAIN_COUNT,
        "malformedNotation": emd.EUROVOC_4_24_MALFORMED_NOTATION_COUNT,
    }
    assert len(outcome.rows) == 127

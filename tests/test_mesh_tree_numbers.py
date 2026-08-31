"""Derived skos:broader edges from MeSH tree-number notation.

The judgment and its evidence are REF-042 in docs/decisions.md: NLM's own
tree-number convention (``C14.280.647`` sits under ``C14.280`` by
construction) is publisher hierarchy RefSpec already captures verbatim as
``atlas:notation``, but expressing it as ``skos:broader`` is RefSpec's act,
so it lives only in the derived graph (REF-035 tier E5). These tests prove
the derivation over synthetic asserted facts, the shared
``refspec.atlas.derived_graph`` machinery that reads real canonical N-Quads
spool lines, content-derived identity that matches the binding's OTHER
digest formula (``rdf_node_digest``, not a bespoke JSON payload), and the
real pinned 2026 release when it is cached locally.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from refspec.atlas import derived_graph
from refspec.atlas.derived_graph import mesh_tree_numbers as mtn
from refspec.atlas.v3_registry_vocabularies import DEFAULT_SOURCE_ROOT, load_mesh_2026_release

BINDING_TOOLS = Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1" / "tools"

GRAPH = "<urn:ref:atlas:graph:v3:asserted>"
MESH_SCHEME = mtn.MESH_SCHEME_IRI
SUBJECT_RING = mtn.ATLAS_SUBJECT_RING


def _canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if terminal_lf:
        text += "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resource_lines(iri: str, *, notations: tuple[str, ...]) -> list[str]:
    subject = f"<{iri}>"
    record = f"<urn:ref:atlas-test:source-record:{iri.rsplit(':', 1)[-1]}>"
    lines = [f'{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .']
    lines.append(f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{MESH_SCHEME}> {GRAPH} .")
    for notation in notations:
        lines.append(f'{subject} {derived_graph.ATLAS_NOTATION_TERM} "{notation}" {GRAPH} .')
    lines.append(f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .")
    return lines


def _facts_and_digests(lines: list[str]) -> tuple[derived_graph.AssertedFactView, dict[str, str]]:
    facts = derived_graph.collect_asserted_fact_view(lines)
    wanted = mtn.mesh_tree_number_evidence_nodes(facts)
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


def test_simple_parent_child_derives_one_edge() -> None:
    # "C14" has no dot -- a root, by NLM's own convention -- and "C14.280"
    # sits under it by construction.
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent", notations=("C14",)),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280",)),
    ]
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))

    assert outcome.counts == {
        "edges": 1,
        "roots": 1,
        "missingParent": 0,
        "ambiguousParent": 0,
        "duplicateTreeNumbers": 0,
    }
    assert len(outcome.rows) == 1
    row = outcome.rows[0]
    assert row.subject == "urn:ref:atlas-test:mesh:child"
    assert row.object == "urn:ref:atlas-test:mesh:parent"
    assert row.predicate == mtn.SKOS_BROADER
    assert row.ring == SUBJECT_RING
    assert row.rule_iri == mtn.MESH_TREE_NUMBER_RULE_IRI
    assert row.engine_iri == mtn.MESH_TREE_NUMBER_ENGINE_IRI
    assert row.engine_version == mtn.MESH_TREE_NUMBER_ENGINE_VERSION
    assert row.generated_at == "2026-01-01T00:00:00+00:00"
    assert row.node_iri == "urn:ref:atlas-derived:" + row.content_digest.removeprefix("sha256:")


def test_polyhierarchy_yields_one_edge_per_distinct_parent() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent-a", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:parent-b", notations=("D02.455",)),
        *_resource_lines(
            "urn:ref:atlas-test:mesh:child",
            notations=("C14.280.647", "D02.455.526"),
        ),
    ]
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))

    parents = {row.object for row in outcome.rows if row.subject == "urn:ref:atlas-test:mesh:child"}
    assert parents == {"urn:ref:atlas-test:mesh:parent-a", "urn:ref:atlas-test:mesh:parent-b"}
    assert outcome.counts["edges"] == 2


def test_two_tree_numbers_under_one_parent_yield_one_edge() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent", notations=("C14.280",)),
        *_resource_lines(
            "urn:ref:atlas-test:mesh:child",
            notations=("C14.280.647", "C14.280.648"),
        ),
    ]
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))

    assert outcome.counts["edges"] == 1
    assert len(outcome.rows) == 1


def test_missing_parent_is_counted_never_guessed() -> None:
    lines = _resource_lines("urn:ref:atlas-test:mesh:orphan", notations=("Z99.999",))
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))

    assert outcome.counts == {
        "edges": 0,
        "roots": 0,
        "missingParent": 1,
        "ambiguousParent": 0,
        "duplicateTreeNumbers": 0,
    }
    assert outcome.rows == ()


def test_ambiguous_parent_is_counted_never_guessed() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent-1", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:parent-2", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))

    assert outcome.counts["ambiguousParent"] == 1
    assert outcome.counts["duplicateTreeNumbers"] == 1
    assert outcome.counts["edges"] == 0
    assert outcome.rows == ()


def test_duplicate_tree_number_never_cited_as_a_parent_does_not_block_edges() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:twin-1", notations=("B03.300",)),
        *_resource_lines("urn:ref:atlas-test:mesh:twin-2", notations=("B03.300",)),
        *_resource_lines("urn:ref:atlas-test:mesh:parent", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))

    assert outcome.counts["duplicateTreeNumbers"] == 1
    assert outcome.counts["ambiguousParent"] == 0
    assert outcome.counts["edges"] == 1


def test_self_referential_tree_number_raises() -> None:
    lines = _resource_lines(
        "urn:ref:atlas-test:mesh:self",
        notations=("C14.280", "C14.280.647"),
    )
    with pytest.raises(mtn.MeshTreeNumberDerivationError, match="resolves its own parent to itself"):
        mtn.derive_mesh_tree_number_broader_rows(_context(lines))


def test_non_subject_ring_endpoint_raises() -> None:
    lines = [
        (
            f'<urn:ref:atlas-test:mesh:parent> {derived_graph.ATLAS_SEMANTIC_RING_TERM} '
            f'<https://refspec.org/ns/atlas/v3#value> {GRAPH} .'
        ),
        f'<urn:ref:atlas-test:mesh:parent> {derived_graph.ATLAS_IN_SCHEME_TERM} <{MESH_SCHEME}> {GRAPH} .',
        f'<urn:ref:atlas-test:mesh:parent> {derived_graph.ATLAS_NOTATION_TERM} "C14.280" {GRAPH} .',
        (
            f'<urn:ref:atlas-test:source-record:parent> {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} '
            f"<urn:ref:atlas-test:mesh:parent> {GRAPH} ."
        ),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    with pytest.raises(mtn.MeshTreeNumberDerivationError, match="not in the subject ring"):
        mtn.derive_mesh_tree_number_broader_rows(_context(lines))


def test_asserted_relation_collision_fails_closed_in_both_directions() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    context = _context(lines)

    with pytest.raises(mtn.MeshTreeNumberDerivationError, match="duplicates an asserted"):
        mtn.derive_mesh_tree_number_broader_rows(
            context,
            asserted_relations=frozenset(
                {("urn:ref:atlas-test:mesh:child", mtn.SKOS_BROADER, "urn:ref:atlas-test:mesh:parent")}
            ),
        )
    with pytest.raises(mtn.MeshTreeNumberDerivationError, match="duplicates an asserted"):
        mtn.derive_mesh_tree_number_broader_rows(
            context,
            asserted_relations=frozenset(
                {("urn:ref:atlas-test:mesh:parent", mtn.SKOS_NARROWER, "urn:ref:atlas-test:mesh:child")}
            ),
        )
    unrelated = mtn.derive_mesh_tree_number_broader_rows(
        context,
        asserted_relations=frozenset(
            {("urn:ref:atlas-test:mesh:child", mtn.SKOS_BROADER, "urn:ref:atlas-test:mesh:other")}
        ),
    )
    assert len(unrelated.rows) == 1


def test_evidence_nodes_missing_source_record_raises() -> None:
    lines = [
        f'<urn:ref:atlas-test:mesh:parent> {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .',
        f'<urn:ref:atlas-test:mesh:parent> {derived_graph.ATLAS_IN_SCHEME_TERM} <{MESH_SCHEME}> {GRAPH} .',
        f'<urn:ref:atlas-test:mesh:parent> {derived_graph.ATLAS_NOTATION_TERM} "C14.280" {GRAPH} .',
        # No atlas:representsResource for the parent -- no SourceRecord cites it.
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    facts = derived_graph.collect_asserted_fact_view(lines)
    with pytest.raises(mtn.MeshTreeNumberDerivationError, match="no source record"):
        mtn.mesh_tree_number_evidence_nodes(facts)


def test_derivation_is_reproducible_from_the_same_facts() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    context = _context(lines)
    first = mtn.derive_mesh_tree_number_broader_rows(context)
    second = mtn.derive_mesh_tree_number_broader_rows(context)

    assert [row.node_iri for row in first.rows] == [row.node_iri for row in second.rows]
    assert first.rows == second.rows


@pytest.mark.parametrize(
    "line",
    (
        '<http://a/s> <http://a/p> <http://a/o> <http://a/g> .',
        '<http://a/s> <http://a/p> "hello world" <http://a/g> .',
        '<http://a/s> <http://a/p> "hello\\"world" <http://a/g> .',
        '<http://a/s> <http://a/p> "2026"^^<http://www.w3.org/2001/XMLSchema#gYear> <http://a/g> .',
        '<http://a/s> <http://a/p> "bonjour"@fr <http://a/g> .',
        '<http://a/s> <http://a/p> "line one\\nline two" <http://a/g> .',
        '<http://a/s> <http://a/p> "back\\\\slash" <http://a/g> .',
    ),
)
def test_iter_nquads_terms_parses_every_canonical_shape(line: str) -> None:
    terms = derived_graph.iter_nquads_terms(line)
    assert terms is not None
    subject, predicate, obj, graph = terms
    assert subject == "<http://a/s>"
    assert predicate == "<http://a/p>"
    assert graph == "<http://a/g>"
    assert obj.startswith(("<", '"'))


@pytest.mark.parametrize(
    "line",
    (
        "",
        "<http://a/s> <http://a/p> <http://a/o> .",
        '<http://a/s> <http://a/p> <http://a/o> <http://a/g>',
        '<http://a/s> <http://a/p> "unterminated <http://a/g> .',
        "not-a-term <http://a/p> <http://a/o> <http://a/g> .",
    ),
)
def test_iter_nquads_terms_refuses_malformed_lines(line: str) -> None:
    assert derived_graph.iter_nquads_terms(line) is None


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

    lines = [
        *_resource_lines("urn:ref:atlas-test:mesh:parent", notations=("C14.280",)),
        *_resource_lines("urn:ref:atlas-test:mesh:child", notations=("C14.280.647",)),
    ]
    outcome = mtn.derive_mesh_tree_number_broader_rows(_context(lines))
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

    assert str(atlas_validate.MESH_TREE_NUMBER_BROADER_RULE) == mtn.MESH_TREE_NUMBER_RULE_IRI
    assert str(atlas_validate.MESH_TREE_NUMBER_ENGINE) == mtn.MESH_TREE_NUMBER_ENGINE_IRI
    assert atlas_validate.MESH_TREE_NUMBER_ENGINE_VERSION == mtn.MESH_TREE_NUMBER_ENGINE_VERSION
    assert atlas_validate.MESH_TREE_NUMBER_BROADER_RULE != atlas_validate.EXACT_MATCH_TRANSITIVITY_RULE


@pytest.mark.slow
@pytest.mark.skipif(
    not (DEFAULT_SOURCE_ROOT / "desc2026.xml").is_file(),
    reason="exact cached MeSH 2026 descriptor XML is not available",
)
def test_real_2026_release_derives_the_frozen_edge_set() -> None:
    release = load_mesh_2026_release()
    lines = mtn.build_mesh_descriptor_asserted_nquads_lines(release)
    context = _context(lines)

    outcome = mtn.derive_mesh_tree_number_broader_rows(context)

    assert len(release.resources) == 31_110
    assert outcome.counts == {
        "edges": mtn.MESH_2026_DERIVED_EDGE_COUNT,
        "roots": mtn.MESH_2026_ROOT_TREE_NUMBER_COUNT,
        "missingParent": mtn.MESH_2026_MISSING_PARENT_COUNT,
        "ambiguousParent": mtn.MESH_2026_AMBIGUOUS_PARENT_COUNT,
        "duplicateTreeNumbers": mtn.MESH_2026_DUPLICATE_TREE_NUMBER_COUNT,
    }
    assert len(outcome.rows) == mtn.MESH_2026_DERIVED_EDGE_COUNT
    again = mtn.derive_mesh_tree_number_broader_rows(context)
    assert [row.node_iri for row in outcome.rows] == [row.node_iri for row in again.rows]

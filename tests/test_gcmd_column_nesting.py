"""Derived skos:broader edges from GCMD Science Keywords column nesting.

The judgment is REF-041 in docs/decisions.md; the registration as the
derived graph's third rule is REF-043. These tests prove the derivation
over synthetic asserted facts (including the scheme scoping the MeSH rule
had to learn from an adversarial battery), content-derived identity that
matches the binding's ``rdf_node_digest`` formula, the constant agreement
between this producer module and the binding's standalone validator, and
-- when the pinned 24.4 CSV is cached -- that the asserted-payload path
reproduces the frozen edge set and agrees pair for pair with REF-041's
committed CSV-level oracle.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from refspec.atlas import derived_graph
from refspec.atlas.derived_graph import gcmd_column_nesting as gcn
from refspec.atlas.v3_registry_vocabularies import DEFAULT_SOURCE_ROOT, load_gcmd_24_4_release

BINDING_TOOLS = Path(__file__).resolve().parents[1] / "bindings" / "atlas" / "3.1" / "tools"

GRAPH = "<urn:ref:atlas:graph:v3:asserted>"
GCMD_SCHEME = gcn.GCMD_SCHEME_IRI
SUBJECT_RING = gcn.ATLAS_SUBJECT_RING


def _canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if terminal_lf:
        text += "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _payload_text(**columns: str | None) -> str:
    values: dict[str, str | None] = dict.fromkeys(gcn.GCMD_PAYLOAD_PATH_KEYS)
    values.update(columns)
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def _escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _resource_lines(
    iri: str,
    *,
    path: tuple[str, ...],
    scheme: str = GCMD_SCHEME,
    ring: str = SUBJECT_RING,
) -> list[str]:
    subject = f"<{iri}>"
    record = f"<urn:ref:atlas-test:source-record:{iri.rsplit(':', 1)[-1]}>"
    columns = dict(zip(gcn.GCMD_PAYLOAD_PATH_KEYS, [*path, *(None,) * (7 - len(path))], strict=True))
    payload = _payload_text(**columns)
    lines = [f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{ring}> {GRAPH} ."]
    lines.append(f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{scheme}> {GRAPH} .")
    lines.append(f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .")
    lines.append(f"{record} {derived_graph.ATLAS_NATIVE_PAYLOAD_TERM} \"{_escaped(payload)}\" {GRAPH} .")
    return lines


def _facts_and_digests(lines: list[str]) -> tuple[derived_graph.AssertedFactView, dict[str, str]]:
    facts = derived_graph.collect_asserted_fact_view(lines)
    wanted = gcn.gcmd_column_nesting_evidence_nodes(facts)
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


PARENT = "urn:ref:atlas-test:gcmd:earth-science"
CHILD = "urn:ref:atlas-test:gcmd:agriculture"


def _pair_lines() -> list[str]:
    return [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        *_resource_lines(CHILD, path=("EARTH SCIENCE", "AGRICULTURE")),
    ]


def test_simple_parent_child_derives_one_edge() -> None:
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(_pair_lines()))

    assert outcome.counts == {"edges": 1, "roots": 1, "homonymLabels": 0}
    assert len(outcome.rows) == 1
    row = outcome.rows[0]
    assert row.subject == CHILD
    assert row.object == PARENT
    assert row.predicate == gcn.SKOS_BROADER
    assert row.ring == SUBJECT_RING
    assert row.rule_iri == gcn.GCMD_COLUMN_NESTING_RULE_IRI
    assert row.engine_iri == gcn.GCMD_COLUMN_NESTING_ENGINE_IRI
    assert row.engine_version == gcn.GCMD_COLUMN_NESTING_ENGINE_VERSION
    assert row.generated_at == "2026-01-01T00:00:00+00:00"
    assert row.node_iri == "urn:ref:atlas-derived:" + row.content_digest.removeprefix("sha256:")


def test_each_edge_cites_the_two_exact_csv_rows_it_came_from() -> None:
    facts, _digests = _facts_and_digests(_pair_lines())
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(_pair_lines()))

    child_record = facts.records[CHILD]
    parent_record = facts.records[PARENT]
    assert outcome.rows[0].evidence == tuple(sorted((child_record, parent_record)))


def test_deeply_nested_path_derives_one_edge_per_level() -> None:
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        *_resource_lines(CHILD, path=("EARTH SCIENCE", "AGRICULTURE")),
        *_resource_lines(
            "urn:ref:atlas-test:gcmd:agricultural-aquatic-sciences",
            path=("EARTH SCIENCE", "AGRICULTURE", "AGRICULTURAL AQUATIC SCIENCES"),
        ),
    ]
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(lines))

    assert outcome.counts == {"edges": 2, "roots": 1, "homonymLabels": 0}
    assert {(row.subject, row.object) for row in outcome.rows} == {
        (CHILD, PARENT),
        ("urn:ref:atlas-test:gcmd:agricultural-aquatic-sciences", CHILD),
    }


def test_scheme_scopes_the_rule_not_the_payload_shape() -> None:
    # The MeSH rule shipped scheme-blind and proved parentage from notation
    # shape alone. The GCMD rule's scope is the scheme: a foreign-scheme
    # resource carrying a perfectly GCMD-shaped nesting payload is not a
    # keyword, contributes no path, and derives no edge -- while the real
    # GCMD pair inside the same asserted graph still does.
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        *_resource_lines(CHILD, path=("EARTH SCIENCE", "AGRICULTURE")),
        *_resource_lines(
            "urn:ref:atlas-test:other:lookalike-child",
            path=("SOME OTHER SCHEME", "TOPIC"),
            scheme="urn:ref:atlas-resource-scheme:mesh-descriptors",
        ),
        *_resource_lines(
            "urn:ref:atlas-test:other:lookalike-parent",
            path=("SOME OTHER SCHEME",),
            scheme="urn:ref:atlas-resource-scheme:mesh-descriptors",
        ),
    ]
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(lines))

    assert outcome.counts == {"edges": 1, "roots": 1, "homonymLabels": 0}
    assert [(row.subject, row.object) for row in outcome.rows] == [(CHILD, PARENT)]


def test_release_node_in_scheme_without_a_record_is_not_a_keyword() -> None:
    # The Atlas release node carries atlas:inScheme for its own scheme but
    # represents nothing; it must not be mistaken for a keyword row.
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        *_resource_lines(CHILD, path=("EARTH SCIENCE", "AGRICULTURE")),
        f'<urn:ref:atlas-release:3:gcmd-science-keywords:24.4> {derived_graph.ATLAS_IN_SCHEME_TERM} <{GCMD_SCHEME}> {GRAPH} .',
    ]
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(lines))

    assert outcome.counts["edges"] == 1


def test_homonym_labels_are_counted_never_merged() -> None:
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        *_resource_lines("urn:ref:atlas-test:gcmd:topic-a", path=("EARTH SCIENCE", "AGRICULTURE")),
        *_resource_lines("urn:ref:atlas-test:gcmd:term-a", path=("EARTH SCIENCE", "AGRICULTURE", "ANIMALS")),
        *_resource_lines("urn:ref:atlas-test:gcmd:topic-b", path=("EARTH SCIENCE", "BIOLOGICAL CLASSIFICATION")),
        # The same label ANIMALS under a second parent: a distinct publisher
        # concept that any label-keyed derivation would silently merge.
        *_resource_lines(
            "urn:ref:atlas-test:gcmd:term-b",
            path=("EARTH SCIENCE", "BIOLOGICAL CLASSIFICATION", "ANIMALS"),
        ),
    ]
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(lines))

    assert outcome.counts == {"edges": 4, "roots": 1, "homonymLabels": 1}
    subjects = {row.subject for row in outcome.rows}
    assert "urn:ref:atlas-test:gcmd:term-a" in subjects
    assert "urn:ref:atlas-test:gcmd:term-b" in subjects


def test_missing_parent_row_fails_closed() -> None:
    lines = [
        # A depth-2 keyword whose depth-1 prefix has no row of its own.
        *_resource_lines("urn:ref:atlas-test:gcmd:orphan", path=("EARTH SCIENCE", "NOT A TOPIC ROW")),
    ]
    with pytest.raises(gcn.GCMDColumnNestingError, match="no materialized parent row"):
        gcn.derive_gcmd_column_nesting_rows(_context(lines))


def test_repeated_path_with_a_fresh_resource_fails_closed() -> None:
    lines = [
        *_resource_lines("urn:ref:atlas-test:gcmd:twin-a", path=("EARTH SCIENCE", "AGRICULTURE")),
        *_resource_lines("urn:ref:atlas-test:gcmd:twin-b", path=("EARTH SCIENCE", "AGRICULTURE")),
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
    ]
    with pytest.raises(gcn.GCMDColumnNestingError, match="path repeats"):
        gcn.derive_gcmd_column_nesting_rows(_context(lines))


def test_payload_populating_a_level_after_a_blank_ancestor_fails_closed() -> None:
    payload = _payload_text(category="EARTH SCIENCE", term="A TERM WITHOUT A TOPIC")
    subject = f"<{CHILD}>"
    record = "<urn:ref:atlas-test:source-record:malformed>"
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .",
        f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{GCMD_SCHEME}> {GRAPH} .",
        f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .",
        f"{record} {derived_graph.ATLAS_NATIVE_PAYLOAD_TERM} \"{_escaped(payload)}\" {GRAPH} .",
    ]
    with pytest.raises(gcn.GCMDColumnNestingError, match="after a blank ancestor"):
        gcn.derive_gcmd_column_nesting_rows(_context(lines))


def test_represented_keyword_without_a_gcmd_payload_fails_closed() -> None:
    payload = json.dumps({"identifier": "not-a-gcmd-row", "label": "Something else"})
    subject = f"<{CHILD}>"
    record = "<urn:ref:atlas-test:source-record:foreign>"
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",)),
        f"{subject} {derived_graph.ATLAS_SEMANTIC_RING_TERM} <{SUBJECT_RING}> {GRAPH} .",
        f"{subject} {derived_graph.ATLAS_IN_SCHEME_TERM} <{GCMD_SCHEME}> {GRAPH} .",
        f"{record} {derived_graph.ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {GRAPH} .",
        f"{record} {derived_graph.ATLAS_NATIVE_PAYLOAD_TERM} \"{_escaped(payload)}\" {GRAPH} .",
    ]
    with pytest.raises(gcn.GCMDColumnNestingError, match="does not carry the GCMD nesting columns"):
        gcn.derive_gcmd_column_nesting_rows(_context(lines))


def test_non_subject_ring_endpoint_raises() -> None:
    lines = [
        *_resource_lines(PARENT, path=("EARTH SCIENCE",), ring="https://refspec.org/ns/atlas/v3#value"),
        *_resource_lines(CHILD, path=("EARTH SCIENCE", "AGRICULTURE")),
    ]
    with pytest.raises(gcn.GCMDColumnNestingError, match="not in the subject ring"):
        gcn.derive_gcmd_column_nesting_rows(_context(lines))


def test_asserted_relation_collision_fails_closed_in_both_directions() -> None:
    context = _context(_pair_lines())

    with pytest.raises(gcn.GCMDColumnNestingError, match="duplicates an asserted"):
        gcn.derive_gcmd_column_nesting_rows(
            context,
            asserted_relations=frozenset({(CHILD, gcn.SKOS_BROADER, PARENT)}),
        )
    with pytest.raises(gcn.GCMDColumnNestingError, match="duplicates an asserted"):
        gcn.derive_gcmd_column_nesting_rows(
            context,
            asserted_relations=frozenset({(PARENT, gcn.SKOS_NARROWER, CHILD)}),
        )
    unrelated = gcn.derive_gcmd_column_nesting_rows(
        context,
        asserted_relations=frozenset({(CHILD, gcn.SKOS_BROADER, "urn:ref:atlas-test:gcmd:other")}),
    )
    assert len(unrelated.rows) == 1


def test_derivation_is_reproducible_from_the_same_facts() -> None:
    context = _context(_pair_lines())
    first = gcn.derive_gcmd_column_nesting_rows(context)
    second = gcn.derive_gcmd_column_nesting_rows(context)

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

    outcome = gcn.derive_gcmd_column_nesting_rows(_context(_pair_lines()))
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

    assert str(atlas_validate.GCMD_COLUMN_NESTING_RULE) == gcn.GCMD_COLUMN_NESTING_RULE_IRI
    assert str(atlas_validate.GCMD_COLUMN_NESTING_ENGINE) == gcn.GCMD_COLUMN_NESTING_ENGINE_IRI
    assert atlas_validate.GCMD_COLUMN_NESTING_ENGINE_VERSION == gcn.GCMD_COLUMN_NESTING_ENGINE_VERSION
    assert str(atlas_validate.GCMD_COLUMN_NESTING_SCHEME) == gcn.GCMD_SCHEME_IRI
    assert tuple(atlas_validate.GCMD_PAYLOAD_PATH_KEYS) == gcn.GCMD_PAYLOAD_PATH_KEYS
    assert atlas_validate.GCMD_COLUMN_NESTING_RULE not in {
        atlas_validate.EXACT_MATCH_TRANSITIVITY_RULE,
        atlas_validate.MESH_TREE_NUMBER_BROADER_RULE,
    }


def test_validator_row_and_replay_are_scoped_to_the_gcmd_scheme() -> None:
    """The binding-side scope check the MeSH rule had to learn from an
    adversarial battery, proven directly for this rule: a row whose
    endpoints sit in a foreign scheme is refused even when its evidence
    and payload parentage are perfect, and the whole-of-rule replay
    ignores foreign-scheme column-shaped payloads instead of demanding
    edges for them."""

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

    def keyword_graph(
        subject_iri: str,
        record_iri: str,
        *,
        scheme: str,
        path: tuple[str, ...],
    ) -> tuple[list[tuple], BindingURIRef, BindingURIRef]:
        subject = BindingURIRef(subject_iri)
        record = BindingURIRef(record_iri)
        columns = dict(zip(gcn.GCMD_PAYLOAD_PATH_KEYS, [*path, *(None,) * (7 - len(path))], strict=True))
        payload = json.dumps(columns, sort_keys=True, separators=(",", ":"))
        triples = [
            (subject, atlas.inScheme, BindingURIRef(scheme)),
            (subject, atlas.semanticRing, atlas.subject),
            (record, atlas.representsResource, subject),
            (record, atlas.nativePayload, Literal(payload, datatype=RDF.JSON)),
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

    # A foreign-scheme pair whose payloads nest perfectly: the row check
    # must refuse it on scheme alone, and the replay must not count it.
    foreign_triples, foreign_child, foreign_child_record = keyword_graph(
        "urn:ref:atlas-test:foreign:child",
        "urn:ref:atlas-test:foreign:record:child",
        scheme=str(mesh_scheme),
        path=("EARTH SCIENCE", "AGRICULTURE"),
    )
    _foreign_parent_triples, foreign_parent, foreign_parent_record = keyword_graph(
        "urn:ref:atlas-test:foreign:parent",
        "urn:ref:atlas-test:foreign:record:parent",
        scheme=str(mesh_scheme),
        path=("EARTH SCIENCE",),
    )
    asserted = Graph()
    for triple in (*foreign_triples, *_foreign_parent_triples):
        asserted.add(triple)

    row_context = atlas_validate._DerivedRowContext(
        node=BindingURIRef("urn:ref:atlas-test:foreign:row"),
        subject=foreign_child,
        predicate=BindingSKOS.broader,
        obj=foreign_parent,
        ring=atlas.subject,
        inputs=frozenset({foreign_child_record, foreign_parent_record}),
        asserted=asserted,
    )
    with pytest.raises(atlas_validate.AtlasValidationError, match="not in the GCMD Science Keywords scheme"):
        atlas_validate._validate_gcmd_column_nesting_row(row_context)

    # The same foreign pair beside a real GCMD pair: the replay regenerates
    # exactly the one in-scheme edge and never demands one for the foreign
    # pair -- the scope lesson applied to the whole-of-rule proof.
    gcmd_triples, gcmd_child, gcmd_child_record = keyword_graph(
        "urn:ref:atlas-test:gcmd:child",
        "urn:ref:atlas-test:gcmd:record:child",
        scheme=gcn.GCMD_SCHEME_IRI,
        path=("EARTH SCIENCE", "AGRICULTURE"),
    )
    _gcmd_parent_triples, gcmd_parent, gcmd_parent_record = keyword_graph(
        "urn:ref:atlas-test:gcmd:parent",
        "urn:ref:atlas-test:gcmd:record:parent",
        scheme=gcn.GCMD_SCHEME_IRI,
        path=("EARTH SCIENCE",),
    )
    for triple in (*gcmd_triples, *_gcmd_parent_triples):
        asserted.add(triple)
    derived = derived_row(
        "urn:ref:atlas-test:gcmd:row",
        gcmd_child,
        gcmd_parent,
        gcmd_child_record,
        gcmd_parent_record,
    )
    atlas_validate._replay_gcmd_column_nesting(
        {next(derived.subjects(RDF.type, atlas.DerivedRelation))},
        derived=derived,
        asserted=asserted,
    )


@pytest.mark.skipif(
    not (DEFAULT_SOURCE_ROOT / "gcmd-science-keywords-24.4.csv").is_file(),
    reason="exact cached GCMD 24.4 Science Keywords CSV is not available",
)
def test_real_24_4_release_reproduces_the_frozen_edge_set(tmp_path: Path) -> None:
    release = load_gcmd_24_4_release()
    lines = gcn.build_gcmd_release_asserted_nquads_lines(release)
    context = _context(list(lines))

    outcome = gcn.derive_gcmd_column_nesting_rows(context)

    assert len(release.resources) == 3_774
    assert outcome.counts == {
        "edges": gcn.GCMD_24_4_DERIVED_EDGE_COUNT,
        "roots": gcn.GCMD_24_4_DERIVED_ROOT_COUNT,
        "homonymLabels": gcn.GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT,
    }
    assert len(outcome.rows) == gcn.GCMD_24_4_DERIVED_EDGE_COUNT


@pytest.mark.skipif(
    not (DEFAULT_SOURCE_ROOT / "gcmd-science-keywords-24.4.csv").is_file(),
    reason="exact cached GCMD 24.4 Science Keywords CSV is not available",
)
def test_real_24_4_edges_agree_pair_for_pair_with_the_ref041_oracle(tmp_path: Path) -> None:
    """REF-041's CSV-level derivation is the committed oracle: the same
    pinned bytes read through the asserted-payload path must derive the
    identical UUID pair set, not merely the same count."""

    from refspec.registry import gcmd_science_keywords as gcmd
    from refspec.registry.gcmd_science_keywords_hierarchy import derive_gcmd_science_keywords_hierarchy

    release = load_gcmd_24_4_release()
    uuid_by_resource = {resource.iri: resource.notations[0] for resource in release.resources}
    outcome = gcn.derive_gcmd_column_nesting_rows(_context(list(gcn.build_gcmd_release_asserted_nquads_lines(release))))
    derived_pairs = {
        (uuid_by_resource[row.subject], uuid_by_resource[row.object]) for row in outcome.rows
    }

    acquired = gcmd.acquire_gcmd_science_keywords(
        gcmd.GCMD_SCIENCE_KEYWORDS_24_4,
        tmp_path,
        source_path=DEFAULT_SOURCE_ROOT / "gcmd-science-keywords-24.4.csv",
    )
    oracle = derive_gcmd_science_keywords_hierarchy(gcmd.parse_gcmd_science_keywords_csv(acquired))
    oracle_pairs = {(edge.child_uuid, edge.parent_uuid) for edge in oracle.edges}

    assert derived_pairs == oracle_pairs

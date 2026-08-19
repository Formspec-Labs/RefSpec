"""Derived ``skos:broader`` edges for MeSH descriptors from tree numbers.

NLM's 2026 MeSH descriptor release (``mesh-descriptors-2026``, 31,110
descriptors) asserts zero ``skos:broader``/``skos:narrower`` relations, but
every descriptor already carries its publisher tree numbers verbatim as
``atlas:notation`` literals (``src/refspec/registry/mesh_descriptors.py``
parses ``TreeNumberList/TreeNumber``; ``v3_registry_vocabularies.py`` copies
them onto ``RegistryResource.notations`` unchanged). A MeSH tree number
*is* a hierarchy statement: ``C14.280.647`` sits under ``C14.280`` by NLM's
own numbering convention, and ``C14.280`` is itself another descriptor's
tree number in the same release. Reading a descriptor's parent as its tree
number with the last dot-segment removed is therefore a structural
projection of a publisher fact RefSpec already holds, not an invention --
but it is still RefSpec's act, not NLM's assertion of ``skos:broader``, so
under REF-035 tier E5 it belongs only in the derived graph and stays
opt-in (see REF-041's GCMD-shaped precedent, and REF-042 in
docs/decisions.md for the binding revision and producer wiring that let
this specific rule ship).

**Verified against the real pinned 2026 release**
(``sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba``,
312,952,703 bytes, 31,110 descriptors, 65,360 tree numbers):

* 115 tree numbers carry no dot and have no parent by construction.
* Every one of the 65,245 non-root tree numbers resolves to a parent tree
  number some descriptor in the release carries -- zero "missing parent"
  anomalies today. The rule still counts this class explicitly and never
  guesses, because a future annual release is not guaranteed to stay that
  clean.
* Three tree numbers (``B03.300.390.400.001``, ``B03.510.415.400.001``,
  ``B03.510.460.410.001``) are each carried by two descriptors at once
  (D047991 ``Acetoanaerobium sticklandii`` and D048013 ``Acetivibrio
  thermocellus``, a bacterial reclassification artifact). Neither
  descriptor's own tree numbers depend on those three as a parent, so this
  ambiguity never actually blocks an edge in the 2026 release, but the
  rule still refuses to guess an owner for an ambiguous parent tree number
  and counts it separately from a missing one.
* Collapsing 65,245 non-root tree numbers through parent resolution yields
  42,519 distinct (child descriptor, parent descriptor) pairs -- fewer
  than the tree-number count because one descriptor can carry two tree
  numbers whose parents are the same descriptor. One derived edge is
  emitted per distinct pair, not per tree number, so a descriptor with
  several tree numbers under one parent still yields exactly one edge to
  it; a descriptor whose tree numbers place it under N distinct parents
  (true MeSH polyhierarchy, 9,349 descriptors in the 2026 release) yields
  N edges.

This module works over the shared :mod:`refspec.atlas.derived_graph`
machinery: it reads the same ``atlas:notation``/``atlas:inScheme``/
``atlas:representsResource``/``atlas:semanticRing`` facts a real asserted
N-Quads spool carries, cites each edge's two descriptors' ``SourceRecord``
IRIs as evidence (``EVIDENCE_INPUT_SOURCE_RECORD`` -- a tree number is a
resource-level fact, not a relation assertion, so there is no assertion
node to cite), and mints the row through :func:`build_derived_row` so its
identity and input digest match the binding's formula exactly.

REF-042 wired this rule end to end: ``bindings/atlas/3.1/tools/validate.py``
admits ``urn:ref:rule:mesh-tree-number-broader`` as the second entry in
``_DERIVED_RULE_ADMISSIONS`` (its own row-shape check and whole-set replay,
alongside exactMatch transitivity's unchanged one), and
``tools/generate_atlas_v3_full.py``'s ``_derive_registered_relations`` calls
this module's ``derive_mesh_tree_number_broader_rows`` for real, over the
already-streamed ``mesh-descriptors-2026`` release, whenever that release is
part of the build. Verified against the real pinned release through both
the producer (a bounded ``--only-release mesh-descriptors-2026`` build) and
the independent validator (which accepted the resulting 42,519-row derived
graph and reproduced the identical edge set from the asserted graph's own
``atlas:notation`` facts).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from refspec.atlas.derived_graph import (
    ATLAS_IN_SCHEME_TERM,
    ATLAS_NOTATION_TERM,
    ATLAS_REPRESENTS_RESOURCE_TERM,
    ATLAS_SEMANTIC_RING_TERM,
    EVIDENCE_INPUT_SOURCE_RECORD,
    AssertedFactView,
    DerivationContext,
    DerivationRule,
    DerivedRelationRow,
    DerivedRuleOutcome,
    build_derived_row,
)

SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
SKOS_NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"

ATLAS_SUBJECT_RING = "https://refspec.org/ns/atlas/v3#subject"

MESH_SCHEME_IRI = "urn:ref:atlas-resource-scheme:mesh-descriptors"

MESH_TREE_NUMBER_RULE_IRI = "urn:ref:rule:mesh-tree-number-broader"
MESH_TREE_NUMBER_ENGINE_IRI = "https://refspec.org/code/atlas-v3-derived-mesh-tree-numbers"
MESH_TREE_NUMBER_ENGINE_VERSION = "1"

# Frozen against the pinned 2026 release
# (sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba,
# 31,110 descriptors, 65,360 tree numbers).
MESH_2026_TREE_NUMBER_COUNT = 65_360
MESH_2026_ROOT_TREE_NUMBER_COUNT = 115
MESH_2026_DERIVED_EDGE_COUNT = 42_519
MESH_2026_MISSING_PARENT_COUNT = 0
MESH_2026_AMBIGUOUS_PARENT_COUNT = 0
MESH_2026_DUPLICATE_TREE_NUMBER_COUNT = 3
MESH_2026_POLYHIERARCHY_DESCRIPTOR_COUNT = 9_349


class MeshTreeNumberDerivationError(ValueError):
    """A tree-number derivation premise the rule refuses to guess past."""


@dataclass(frozen=True, slots=True)
class MeshTreeNumberCounts:
    """The reconciling counters the real-data test pins exactly."""

    root_tree_numbers: int
    edges: int
    missing_parent: int
    ambiguous_parent: int
    duplicate_tree_numbers: int


def _mesh_resources(facts: AssertedFactView) -> frozenset[str]:
    return frozenset(resource for resource, scheme in facts.schemes.items() if scheme == MESH_SCHEME_IRI)


def resolve_tree_number_edges_from_notations(
    notations_by_resource: Mapping[str, Iterable[str]],
) -> tuple[tuple[tuple[str, str], ...], MeshTreeNumberCounts]:
    """Resolve every tree number to its parent resource, or count why not.

    The one algorithm both the asserted-fact-view path
    (:func:`_resolve_edge_pairs`, reading a real spooled N-Quads pass) and
    the producer's prebuild count (reading in-memory ``RegistryResource``
    objects before any spool exists) delegate to -- so the row count the
    prebuild receipt commits to and the row set the streamed build actually
    emits can never independently drift, because they run the same code.

    Returns the distinct, sorted ``(child, parent)`` resource-IRI pairs the
    tree numbers imply, plus the counters that reconcile every tree number
    against one of: a root (no parent), an edge, a missing parent, or an
    ambiguous parent. Never guesses an owner for an ambiguous parent tree
    number, and refuses outright on a self-edge, which tree-number
    arithmetic should never produce.
    """

    owners: dict[str, set[str]] = {}
    for resource, notations in notations_by_resource.items():
        for tree_number in notations:
            owners.setdefault(tree_number, set()).add(resource)
    duplicate_tree_numbers = sum(1 for resources in owners.values() if len(resources) > 1)

    roots = 0
    missing_parent = 0
    ambiguous_parent = 0
    pairs: set[tuple[str, str]] = set()
    for resource, notations in notations_by_resource.items():
        for tree_number in notations:
            if "." not in tree_number:
                roots += 1
                continue
            parent_tree_number = tree_number.rsplit(".", 1)[0]
            parent_owners = owners.get(parent_tree_number)
            if not parent_owners:
                missing_parent += 1
                continue
            if len(parent_owners) > 1:
                ambiguous_parent += 1
                continue
            (parent,) = parent_owners
            if parent == resource:
                raise MeshTreeNumberDerivationError(
                    f"tree number {tree_number!r} on {resource} resolves its own parent to itself"
                )
            pairs.add((resource, parent))

    counts = MeshTreeNumberCounts(
        root_tree_numbers=roots,
        edges=len(pairs),
        missing_parent=missing_parent,
        ambiguous_parent=ambiguous_parent,
        duplicate_tree_numbers=duplicate_tree_numbers,
    )
    return tuple(sorted(pairs)), counts


def _resolve_edge_pairs(
    facts: AssertedFactView,
) -> tuple[tuple[tuple[str, str], ...], MeshTreeNumberCounts]:
    """Resolve every MeSH tree number to its parent descriptor, or count why not."""

    mesh_resources = _mesh_resources(facts)
    notations_by_resource = {resource: facts.notations.get(resource, ()) for resource in mesh_resources}
    return resolve_tree_number_edges_from_notations(notations_by_resource)


def resolve_mesh_tree_number_edges(
    facts: AssertedFactView,
) -> tuple[tuple[tuple[str, str], ...], MeshTreeNumberCounts]:
    """Public entry point: the pure child/parent pair resolution plus counts."""

    return _resolve_edge_pairs(facts)


def mesh_tree_number_evidence_nodes(facts: AssertedFactView) -> frozenset[str]:
    """The source-record IRIs :func:`derive_mesh_tree_number_broader_rows` cites."""

    pairs, _counts = _resolve_edge_pairs(facts)
    resources: set[str] = set()
    for child, parent in pairs:
        resources.add(child)
        resources.add(parent)
    missing_records = [resource for resource in resources if resource not in facts.records]
    if missing_records:
        raise MeshTreeNumberDerivationError(
            f"MeSH descriptor {missing_records[0]} has no source record to cite as derivation evidence"
        )
    return frozenset(facts.records[resource] for resource in resources)


def derive_mesh_tree_number_broader_rows(
    context: DerivationContext,
    *,
    asserted_relations: frozenset[tuple[str, str, str]] = frozenset(),
) -> DerivedRuleOutcome:
    """Derive every MeSH tree-number ``skos:broader`` row from asserted facts.

    ``asserted_relations`` carries already-asserted (subject IRI, predicate
    IRI, object IRI) triples; a derived edge that would duplicate one -- or
    its ``skos:narrower`` inverse -- is refused, never silently dropped.
    ``mesh-descriptors-2026`` asserts zero relations today, so this is
    exercised by a synthetic collision in the tests, not by real data; the
    day this rule is wired into a live asserted-graph spool, the caller
    must thread the spool's own relation-assertion triples through here.
    """

    facts = context.facts
    pairs, counts = _resolve_edge_pairs(facts)
    rows: list[DerivedRelationRow] = []
    for child, parent in pairs:
        child_ring = facts.rings.get(child)
        parent_ring = facts.rings.get(parent)
        if child_ring != ATLAS_SUBJECT_RING or parent_ring != ATLAS_SUBJECT_RING:
            raise MeshTreeNumberDerivationError(
                f"MeSH tree-number edge endpoint is not in the subject ring: {child} -> {parent}"
            )
        if (child, SKOS_BROADER, parent) in asserted_relations or (
            parent,
            SKOS_NARROWER,
            child,
        ) in asserted_relations:
            raise MeshTreeNumberDerivationError(
                f"derived edge {child} -> {parent} duplicates an asserted relation (or its narrower inverse)"
            )
        child_record = facts.records.get(child)
        parent_record = facts.records.get(parent)
        if child_record is None or parent_record is None:
            raise MeshTreeNumberDerivationError(
                f"MeSH descriptor has no source record for derived edge {child} -> {parent}"
            )
        rows.append(
            build_derived_row(
                rule=MESH_TREE_NUMBER_BROADER_RULE,
                subject=child,
                predicate=SKOS_BROADER,
                obj=parent,
                ring=ATLAS_SUBJECT_RING,
                evidence=(child_record, parent_record),
                context=context,
            )
        )
    rows.sort(key=lambda row: row.node_iri)
    return DerivedRuleOutcome(
        rows=tuple(rows),
        counts={
            "edges": counts.edges,
            "roots": counts.root_tree_numbers,
            "missingParent": counts.missing_parent,
            "ambiguousParent": counts.ambiguous_parent,
            "duplicateTreeNumbers": counts.duplicate_tree_numbers,
        },
    )


MESH_TREE_NUMBER_BROADER_RULE = DerivationRule(
    rule_iri=MESH_TREE_NUMBER_RULE_IRI,
    engine_iri=MESH_TREE_NUMBER_ENGINE_IRI,
    engine_version=MESH_TREE_NUMBER_ENGINE_VERSION,
    evidence_input_kind=EVIDENCE_INPUT_SOURCE_RECORD,
    watch_predicates=frozenset(
        {
            ATLAS_NOTATION_TERM,
            ATLAS_IN_SCHEME_TERM,
            ATLAS_REPRESENTS_RESOURCE_TERM,
            ATLAS_SEMANTIC_RING_TERM,
        }
    ),
    evidence_nodes=mesh_tree_number_evidence_nodes,
    derive=derive_mesh_tree_number_broader_rows,
    label="MeSH tree-number broader",
)


def build_mesh_descriptor_asserted_nquads_lines(release: object) -> tuple[str, ...]:
    """Project one MeSH descriptor release into the asserted facts this rule reads.

    Emits exactly the four watched predicates per descriptor -- notation,
    scheme membership, semantic ring, and one synthetic ``SourceRecord``
    per descriptor -- using the same shape
    ``v3_registry_vocabularies._normalize_mesh`` gives real resources, so
    the real-data test below runs the rule over facts equivalent to what a
    real asserted spool would carry. The synthetic source-record IRI is
    not the producer's real content-derived minting formula (that needs a
    full native payload this projection does not build); it only needs to
    be a stable, unique node per descriptor for evidence citation.
    """

    graph_id = "<urn:ref:atlas:graph:v3:asserted>"
    lines: list[str] = []
    for resource in release.resources:  # type: ignore[attr-defined]
        subject = f"<{resource.iri}>"
        record = f"<urn:ref:atlas-source-record:mesh-tree-number-fixture:{resource.iri}>"
        for tree_number in resource.notations:
            escaped = tree_number.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{subject} <{ATLAS_NOTATION_TERM[1:-1]}> "{escaped}" {graph_id} .')
        lines.append(f"{subject} <{ATLAS_IN_SCHEME_TERM[1:-1]}> <{MESH_SCHEME_IRI}> {graph_id} .")
        lines.append(f"{subject} <{ATLAS_SEMANTIC_RING_TERM[1:-1]}> <{ATLAS_SUBJECT_RING}> {graph_id} .")
        lines.append(f"{record} <{ATLAS_REPRESENTS_RESOURCE_TERM[1:-1]}> {subject} {graph_id} .")
    return tuple(lines)


def main() -> None:
    """Print the derived row set over the real pinned MeSH 2026 release."""

    import hashlib
    import json

    from refspec.atlas.derived_graph import collect_asserted_fact_view, collect_node_digests
    from refspec.atlas.v3_registry_vocabularies import load_mesh_2026_release

    def canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if terminal_lf:
            text += "\n"
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    release = load_mesh_2026_release()
    lines = build_mesh_descriptor_asserted_nquads_lines(release)
    facts = collect_asserted_fact_view(lines)
    wanted = mesh_tree_number_evidence_nodes(facts)
    node_digest = collect_node_digests(lines, wanted)
    context = DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=canonical_sha256,
        generated_at="2026-01-01T00:00:00+00:00",
    )
    outcome = derive_mesh_tree_number_broader_rows(context)
    print(f"descriptors={len(release.resources)} lines={len(lines)}")
    print(f"counts={outcome.counts}")
    print(f"edges={len(outcome.rows)}")
    print(f"sample row={outcome.rows[0]}")


if __name__ == "__main__":
    main()


__all__ = [
    "ATLAS_SEMANTIC_RING_TERM",
    "ATLAS_SUBJECT_RING",
    "MESH_2026_AMBIGUOUS_PARENT_COUNT",
    "MESH_2026_DERIVED_EDGE_COUNT",
    "MESH_2026_DUPLICATE_TREE_NUMBER_COUNT",
    "MESH_2026_MISSING_PARENT_COUNT",
    "MESH_2026_POLYHIERARCHY_DESCRIPTOR_COUNT",
    "MESH_2026_ROOT_TREE_NUMBER_COUNT",
    "MESH_2026_TREE_NUMBER_COUNT",
    "MESH_SCHEME_IRI",
    "MESH_TREE_NUMBER_BROADER_RULE",
    "MESH_TREE_NUMBER_ENGINE_IRI",
    "MESH_TREE_NUMBER_ENGINE_VERSION",
    "MESH_TREE_NUMBER_RULE_IRI",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "MeshTreeNumberCounts",
    "MeshTreeNumberDerivationError",
    "build_mesh_descriptor_asserted_nquads_lines",
    "derive_mesh_tree_number_broader_rows",
    "mesh_tree_number_evidence_nodes",
    "resolve_mesh_tree_number_edges",
    "resolve_tree_number_edges_from_notations",
]

"""Derived ``skos:broader`` edges for GCMD Science Keywords from CSV column nesting.

REF-041 (docs/decisions.md) reached the judgment this rule executes: the
Science Keywords CSV export encodes the publisher's hierarchy positionally
(Category > Topic > Term > Variable_Level_1..3 > Detailed_Variable), every
ancestor prefix of every row is itself a row with its own publisher UUID,
and NASA's own RDF export of the same scheme asserts ``skos:broader``
between exactly the UUID pairs the nesting implies -- but the pinned CSV
carries no relation field, so expressing that structure as ``skos:broader``
is RefSpec's act under REF-035 tier E5: derived graph only, opt-in,
never asserted. REF-042 then built the derived-graph rule registry that
REF-041 said this rule required; REF-043 registers this module as its
third entry.

Unlike the MeSH tree-number rule -- whose premise (a tree number) is an
``atlas:notation`` literal on the resource itself -- the GCMD premise is
the *column path* of a CSV row, and the asserted graph carries that path
exactly once: as the canonical ``atlas:nativePayload`` JSON on the
keyword's own ``SourceRecord``, the same bytes
``v3_registry_vocabularies._normalize_gcmd`` writes from the pinned CSV
columns. This rule therefore reads each keyword's path out of its source
record's native payload -- the asserted-graph bytes the validator's replay
will later read back -- and cites the child's and parent's ``SourceRecord``
IRIs as each edge's evidence (``EVIDENCE_INPUT_SOURCE_RECORD``): a source
record IS the exact CSV row it receipts, so citing the two records is
citing the two rows the edge came from. UUID notations stay unused here;
identity is path-scoped, never label-scoped (512 same-label keywords sit
under more than one parent in the pinned export).

**Scope.** Both endpoints of every edge, and every path this rule reads,
must sit in the GCMD Science Keywords scheme
    (``urn:ref:atlas-resource-scheme:gcmd-science-keywords``).
The MeSH rule shipped scheme-blind and an adversarial battery caught it
proving parentage from notation shape alone; this rule requires the scheme
in its producer fact selection, in the binding's row check, and in the
binding's whole-set replay from the first line of each. A "keyword" for
this rule is precisely: a resource in that scheme that some ``SourceRecord``
represents. The release node also carries ``atlas:inScheme`` for the same
scheme but represents nothing and is excluded by that same definition --
which is why the scope is "in scheme AND represented by a record", not
"in scheme" alone.

**Verified against the real pinned 24.4 export**
(``sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2``,
504,190 bytes, 3,774 keyword rows):

* 2 roots (depth-1 paths: the two Categories), 3,772 derived
  ``skos:broader`` edges -- the identical edge count and UUID pair set
  ``refspec.registry.gcmd_science_keywords_hierarchy`` (REF-041's
  fail-closed CSV reader, the committed oracle for this judgment) derives
  from the same pinned bytes; the real-data test proves the two agree
  pair for pair rather than merely counting the same.
* zero missing ancestors, zero repeated paths, zero self-edges -- every
  premise violation raises (never silently drops), so a future export
  that breaks prefix-closure fails the build loudly.
* 512 (level, label) pairs appear under more than one parent -- counted
  (``homonymLabels``) as the standing reminder that any label-keyed
  derivation of this scheme would silently merge distinct concepts.

This module works over the shared :mod:`refspec.atlas.derived_graph`
machinery and mints its rows through :func:`build_derived_row`, so row
identity and input digests match the binding's formulas exactly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from refspec.atlas.derived_graph import (
    ATLAS_IN_SCHEME_TERM,
    ATLAS_NATIVE_PAYLOAD_TERM,
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
from refspec.registry.gcmd_science_keywords_hierarchy import (
    GCMD_24_4_DERIVED_EDGE_COUNT,
    GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT,
    GCMD_24_4_DERIVED_ROOT_COUNT,
    GCMD_COLUMN_NESTING_RULE,
    SKOS_BROADER,
    SKOS_NARROWER,
)

ATLAS_SUBJECT_RING = "https://refspec.org/ns/atlas/v3#subject"

GCMD_SCHEME_IRI = "urn:ref:atlas-resource-scheme:gcmd-science-keywords"

GCMD_COLUMN_NESTING_RULE_IRI = GCMD_COLUMN_NESTING_RULE
GCMD_COLUMN_NESTING_ENGINE_IRI = "https://refspec.org/code/atlas-v3-derived-gcmd-column-nesting"
GCMD_COLUMN_NESTING_ENGINE_VERSION = "1"

# The native-payload keys _normalize_gcmd writes from the CSV columns, in
# nesting order. The binding validator carries its own copy of this tuple
# (it does not import this package); tests compare the two.
GCMD_PAYLOAD_PATH_KEYS = (
    "category",
    "topic",
    "term",
    "variableLevel1",
    "variableLevel2",
    "variableLevel3",
    "detailedVariable",
)

class GCMDColumnNestingError(ValueError):
    """A column-nesting premise the rule refuses to guess past."""


@dataclass(frozen=True, slots=True)
class GCMDColumnNestingCounts:
    """The reconciling counters the real-data test pins exactly."""

    roots: int
    edges: int
    homonym_labels: int


def gcmd_path_from_payload(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Read one native payload's nesting path, fail-closed.

    A GCMD payload must carry the column keys; blanks may only trail (the
    pinned reader already refuses a populated level after a blank
    ancestor, so anything else here is a payload the reader never writes).
    """

    if not all(key in payload for key in GCMD_PAYLOAD_PATH_KEYS):
        raise GCMDColumnNestingError("native payload does not carry the GCMD nesting columns")
    path: list[str] = []
    for key in GCMD_PAYLOAD_PATH_KEYS:
        value = payload[key]
        if value is None or value == "":
            break
        if not isinstance(value, str):
            raise GCMDColumnNestingError(f"GCMD nesting column {key!r} is not a string")
        path.append(value)
    if not path:
        raise GCMDColumnNestingError("native payload carries an empty GCMD nesting path")
    trailing = tuple(payload[key] for key in GCMD_PAYLOAD_PATH_KEYS)[len(path) :]
    if any(value is not None and value != "" for value in trailing):
        raise GCMDColumnNestingError("native payload populates a GCMD level after a blank ancestor")
    return tuple(path)


def gcmd_path_from_payload_json(text: str) -> tuple[str, ...]:
    """Parse one ``atlas:nativePayload`` JSON text into a nesting path."""

    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise GCMDColumnNestingError("native payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise GCMDColumnNestingError("native payload is not a JSON object")
    return gcmd_path_from_payload(payload)


def resolve_gcmd_column_nesting_edges(
    paths_by_resource: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[tuple[str, str], ...], GCMDColumnNestingCounts]:
    """Resolve every keyword path to its parent resource, or refuse why not.

    The one algorithm the asserted-fact-view path and the producer's
    prebuild count delegate to, so the committed row count and the
    streamed row set can never drift. Fail-closed on every premise
    violation REF-041 recorded: a repeated path (even under a fresh
    resource), a missing ancestor-prefix row, or a self-edge raises; a
    depth-1 path is a root and is counted, never guessed past.
    """

    resource_by_path: dict[tuple[str, ...], str] = {}
    for resource, path in paths_by_resource.items():
        previous = resource_by_path.get(path)
        if previous is not None:
            raise GCMDColumnNestingError(
                f"Science Keywords path repeats: {path} on {previous} and {resource}"
            )
        resource_by_path[path] = resource

    roots = 0
    pairs: set[tuple[str, str]] = set()
    for resource, path in paths_by_resource.items():
        if len(path) < 2:
            roots += 1
            continue
        parent = resource_by_path.get(path[:-1])
        if parent is None:
            raise GCMDColumnNestingError(
                f"keyword {resource} has no materialized parent row for its {path[:-1]!r} prefix"
            )
        if parent == resource:
            raise GCMDColumnNestingError(f"keyword {resource} derives a self-edge")
        pairs.add((resource, parent))

    parents_by_label: dict[tuple[int, str], set[tuple[str, ...]]] = {}
    for path in resource_by_path:
        if len(path) < 2:
            continue
        parents_by_label.setdefault((len(path) - 1, path[-1]), set()).add(path[:-1])
    homonym_labels = sum(1 for parents in parents_by_label.values() if len(parents) > 1)

    counts = GCMDColumnNestingCounts(
        roots=roots,
        edges=len(pairs),
        homonym_labels=homonym_labels,
    )
    return tuple(sorted(pairs)), counts


def gcmd_keyword_paths(facts: AssertedFactView) -> dict[str, tuple[str, ...]]:
    """Every GCMD keyword's resource IRI and nesting path, scoped to the scheme.

    A keyword is a resource in the GCMD scheme that a source record
    represents; each such resource's record must carry a GCMD-shaped
    native payload or the premise is violated and this raises.
    """

    paths: dict[str, tuple[str, ...]] = {}
    for resource, scheme in facts.schemes.items():
        if scheme != GCMD_SCHEME_IRI:
            continue
        record = facts.records.get(resource)
        if record is None:
            # The release node sits in its own scheme but represents
            # nothing; it is not a keyword. A real keyword without a
            # source record has no CSV row to cite, which the evidence
            # check below refuses -- not silently skipped.
            continue
        payload = facts.payloads.get(record)
        if payload is None:
            raise GCMDColumnNestingError(f"GCMD keyword {resource} has no native payload on its source record")
        paths[resource] = gcmd_path_from_payload_json(payload)
    return paths


def _resolve_edge_pairs(facts: AssertedFactView) -> tuple[tuple[tuple[str, str], ...], GCMDColumnNestingCounts]:
    return resolve_gcmd_column_nesting_edges(gcmd_keyword_paths(facts))


def resolve_gcmd_column_nesting_edges_from_facts(
    facts: AssertedFactView,
) -> tuple[tuple[tuple[str, str], ...], GCMDColumnNestingCounts]:
    """Public entry point: the pure child/parent pair resolution plus counts."""

    return _resolve_edge_pairs(facts)


def gcmd_column_nesting_evidence_nodes(facts: AssertedFactView) -> frozenset[str]:
    """The source-record IRIs :func:`derive_gcmd_column_nesting_rows` cites.

    Every edge endpoint reached its path through its own source record
    (that is what makes it a keyword), so each endpoint always has a
    record to cite; this recomputes them for digest collection.
    """

    pairs, _counts = _resolve_edge_pairs(facts)
    resources = {child for child, _parent in pairs} | {parent for _child, parent in pairs}
    return frozenset(facts.records[resource] for resource in resources)


def derive_gcmd_column_nesting_rows(
    context: DerivationContext,
    *,
    asserted_relations: frozenset[tuple[str, str, str]] = frozenset(),
) -> DerivedRuleOutcome:
    """Derive every GCMD column-nesting ``skos:broader`` row from asserted facts.

    ``asserted_relations`` carries already-asserted (subject IRI, predicate
    IRI, object IRI) triples; a derived edge that would duplicate one -- or
    its ``skos:narrower`` inverse -- is refused, never silently dropped.
    ``gcmd-science-keywords-24-4`` asserts zero relations today, so this is
    exercised by a synthetic collision in the tests, not by real data.
    """

    facts = context.facts
    pairs, counts = _resolve_edge_pairs(facts)
    rows: list[DerivedRelationRow] = []
    for child, parent in pairs:
        child_ring = facts.rings.get(child)
        parent_ring = facts.rings.get(parent)
        if child_ring != ATLAS_SUBJECT_RING or parent_ring != ATLAS_SUBJECT_RING:
            raise GCMDColumnNestingError(
                f"GCMD column-nesting edge endpoint is not in the subject ring: {child} -> {parent}"
            )
        if (child, SKOS_BROADER, parent) in asserted_relations or (
            parent,
            SKOS_NARROWER,
            child,
        ) in asserted_relations:
            raise GCMDColumnNestingError(
                f"derived edge {child} -> {parent} duplicates an asserted relation (or its narrower inverse)"
            )
        child_record = facts.records.get(child)
        parent_record = facts.records.get(parent)
        if child_record is None or parent_record is None:
            raise GCMDColumnNestingError(
                f"GCMD keyword has no source record for derived edge {child} -> {parent}"
            )
        rows.append(
            build_derived_row(
                rule=GCMD_COLUMN_NESTING_DERIVATION_RULE,
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
            "roots": counts.roots,
            "homonymLabels": counts.homonym_labels,
        },
    )


GCMD_COLUMN_NESTING_DERIVATION_RULE = DerivationRule(
    rule_iri=GCMD_COLUMN_NESTING_RULE_IRI,
    engine_iri=GCMD_COLUMN_NESTING_ENGINE_IRI,
    engine_version=GCMD_COLUMN_NESTING_ENGINE_VERSION,
    evidence_input_kind=EVIDENCE_INPUT_SOURCE_RECORD,
    watch_predicates=frozenset(
        {
            ATLAS_IN_SCHEME_TERM,
            ATLAS_REPRESENTS_RESOURCE_TERM,
            ATLAS_SEMANTIC_RING_TERM,
            ATLAS_NATIVE_PAYLOAD_TERM,
        }
    ),
    evidence_nodes=gcmd_column_nesting_evidence_nodes,
    derive=derive_gcmd_column_nesting_rows,
    label="GCMD Science Keywords column-nesting broader",
)


def build_gcmd_release_asserted_nquads_lines(release: object) -> tuple[str, ...]:
    """Project one GCMD release into the asserted facts this rule reads.

    Emits the four watched predicates per keyword -- scheme membership,
    semantic ring, the ``SourceRecord`` that represents it, and that
    record's native payload (the CSV row's columns verbatim) -- using the
    same shapes a real asserted spool carries, so the real-data test runs
    the rule over facts equivalent to what the producer's spooled pass
    reads. The synthetic source-record IRI is not the producer's
    content-derived minting formula; it only needs to be stable and unique
    per keyword for evidence citation.
    """

    graph_id = "<urn:ref:atlas:graph:v3:asserted>"
    lines: list[str] = []
    for resource in release.resources:  # type: ignore[attr-defined]
        subject = f"<{resource.iri}>"
        record = f"<urn:ref:atlas-source-record:gcmd-column-nesting-fixture:{resource.iri}>"
        payload = json.dumps(dict(resource.native_payload), sort_keys=True, separators=(",", ":"))
        escaped = payload.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"{subject} {ATLAS_SEMANTIC_RING_TERM} <{ATLAS_SUBJECT_RING}> {graph_id} .")
        lines.append(f"{subject} {ATLAS_IN_SCHEME_TERM} <{GCMD_SCHEME_IRI}> {graph_id} .")
        lines.append(f"{record} {ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {graph_id} .")
        lines.append(f"{record} {ATLAS_NATIVE_PAYLOAD_TERM} \"{escaped}\" {graph_id} .")
    return tuple(lines)


def main() -> None:
    """Print the derived row set over the real pinned GCMD 24.4 release."""

    import hashlib

    from refspec.atlas.derived_graph import collect_asserted_fact_view, collect_node_digests
    from refspec.atlas.v3_registry_vocabularies import load_gcmd_24_4_release

    def canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if terminal_lf:
            text += "\n"
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    release = load_gcmd_24_4_release()
    lines = build_gcmd_release_asserted_nquads_lines(release)
    facts = collect_asserted_fact_view(lines)
    wanted = gcmd_column_nesting_evidence_nodes(facts)
    node_digest = collect_node_digests(lines, wanted)
    context = DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=canonical_sha256,
        generated_at="2026-01-01T00:00:00+00:00",
    )
    outcome = derive_gcmd_column_nesting_rows(context)
    print(f"keywords={len(release.resources)} lines={len(lines)}")
    print(f"counts={outcome.counts}")
    print(f"edges={len(outcome.rows)}")
    print(f"sample row={outcome.rows[0]}")


__all__ = [
    "ATLAS_SUBJECT_RING",
    "GCMD_24_4_DERIVED_EDGE_COUNT",
    "GCMD_24_4_DERIVED_HOMONYM_LABEL_COUNT",
    "GCMD_24_4_DERIVED_ROOT_COUNT",
    "GCMD_COLUMN_NESTING_DERIVATION_RULE",
    "GCMD_COLUMN_NESTING_ENGINE_IRI",
    "GCMD_COLUMN_NESTING_ENGINE_VERSION",
    "GCMD_COLUMN_NESTING_RULE_IRI",
    "GCMD_PAYLOAD_PATH_KEYS",
    "GCMD_SCHEME_IRI",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "GCMDColumnNestingCounts",
    "GCMDColumnNestingError",
    "build_gcmd_release_asserted_nquads_lines",
    "derive_gcmd_column_nesting_rows",
    "gcmd_column_nesting_evidence_nodes",
    "gcmd_keyword_paths",
    "gcmd_path_from_payload",
    "gcmd_path_from_payload_json",
    "resolve_gcmd_column_nesting_edges",
    "resolve_gcmd_column_nesting_edges_from_facts",
]

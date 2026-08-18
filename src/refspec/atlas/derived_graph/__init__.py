"""Derived-graph rule machinery for the Atlas 3 producer.

The Atlas asserted graph carries only what publishers assert. The derived
graph is the one place an inferred consequence may appear, and the 3.1
binding admits it only as an ``atlas:DerivedRelation`` record that names
its rule, engine, engine version, input evidence, and content-derived
identity, and never duplicates a directly asserted relation.

This package is the producer-side half of that machinery:

* a registry rules register themselves into
  (:func:`register_derivation_rule`);
* a fact view collected from the spooled asserted N-Quads lines
  (:class:`AssertedFactView`), so every rule reads the same asserted
  bytes the validator will later replay against;
* one derivation rule today: the MeSH tree-number hierarchy
  (:mod:`refspec.atlas.derived_graph.mesh_tree_numbers`), which derives
  ``skos:broader`` edges between MeSH descriptors from the tree numbers
  NLM published and RefSpec already captures as ``atlas:notation``.

**Extension point for additional rules.** A new rule is one module in
this package that builds a :class:`DerivationRule`, plus two deliberate
registration lines at the bottom of this ``__init__`` (see the mesh
registration below), plus one allowlist entry in the binding validator
(``bindings/atlas/3.1/tools/validate.py``, ``_DERIVED_RULES``) carrying
the same rule/engine/engine-version tuple and the rule's replay check.
Registration here is necessary but not sufficient: the producer only
populates rows for rules the binding's ``derived_rule_admission()``
admits, so a rule registered without its binding entry refuses loudly in
the generation receipt instead of shipping rows no validator will
accept.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

EVIDENCE_INPUT_ASSERTION = "assertion"
EVIDENCE_INPUT_SOURCE_RECORD = "sourceRecord"

ATLAS_NOTATION_TERM = "<https://refspec.org/ns/atlas/v3#notation>"
ATLAS_IN_SCHEME_TERM = "<https://refspec.org/ns/atlas/v3#inScheme>"
ATLAS_REPRESENTS_RESOURCE_TERM = "<https://refspec.org/ns/atlas/v3#representsResource>"
ATLAS_SEMANTIC_RING_TERM = "<https://refspec.org/ns/atlas/v3#semanticRing>"
_ATLAS_SELF_DIGEST_TERMS = frozenset(
    {
        "<https://refspec.org/ns/atlas/v3#contentDigest>",
        "<https://rulespec.org/ns/v1#proofRecordDigest>",
    }
)

_WATCHED_PREDICATES: set[str] = set()


@dataclass(frozen=True, slots=True)
class DerivedRelationRow:
    """One fully identified derived-relation record, pre-rendering.

    ``input_digest`` follows the binding's derived input digest formula
    (canonical REF JSON over the cited evidence rows, no terminal LF) and
    ``content_digest``/``node_iri`` pin the record's content-derived
    identity, so the row is reproducible from the asserted graph alone.
    """

    rule_iri: str
    engine_iri: str
    engine_version: str
    subject: str
    predicate: str
    object: str
    ring: str
    evidence: tuple[str, ...]
    input_digest: str
    content_digest: str
    node_iri: str


@dataclass(frozen=True, slots=True)
class DerivedRuleOutcome:
    """What one rule produced, plus the counters that reconcile it."""

    rows: tuple[DerivedRelationRow, ...]
    counts: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(slots=True)
class AssertedFactView:
    """Facts collected from the asserted graph's canonical N-Quads lines.

    Only the predicates some registered rule watches are collected, and
    only in the shapes the collector understands: notations per
    resource, the one scheme each resource sits in, the source record
    each resource is represented by, and the one semantic ring each
    resource declares. Anything a future rule needs becomes a new field
    here, fed by a new watched predicate, so collection stays one pass.
    """

    notations: dict[str, set[str]] = field(default_factory=dict)
    schemes: dict[str, str] = field(default_factory=dict)
    records: dict[str, str] = field(default_factory=dict)
    rings: dict[str, str] = field(default_factory=dict)
    scheme_conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivationContext:
    """Everything a rule needs to derive rows from asserted facts.

    ``node_digest`` maps evidence node IRI to the binding-formula
    content digest of that node's asserted facts; ``canonical_sha256``
    is the binding's canonical-JSON digest (no terminal LF) so row
    identities match what the validator recomputes.
    """

    facts: AssertedFactView
    node_digest: Mapping[str, str]
    canonical_sha256: Callable[[Any], str]


@dataclass(frozen=True, slots=True)
class DerivationRule:
    """One registered derivation rule and its producer-side contract."""

    rule_iri: str
    engine_iri: str
    engine_version: str
    evidence_input_kind: str
    watch_predicates: frozenset[str]
    evidence_nodes: Callable[[AssertedFactView], frozenset[str]]
    derive: Callable[[DerivationContext], DerivedRuleOutcome]
    label: str = ""


_RULES: dict[str, DerivationRule] = {}
_BUILTIN_RULES: tuple[DerivationRule, ...] = ()


def register_derivation_rule(rule: DerivationRule) -> None:
    """Register one rule; a repeated rule IRI is refused, not replaced."""

    if not rule.rule_iri or not rule.engine_iri or not rule.engine_version:
        raise ValueError("derivation rule must carry a rule IRI, engine IRI, and engine version")
    if rule.evidence_input_kind not in (EVIDENCE_INPUT_ASSERTION, EVIDENCE_INPUT_SOURCE_RECORD):
        raise ValueError(f"derivation rule {rule.rule_iri} declares an unknown evidence input kind")
    existing = _RULES.get(rule.rule_iri)
    if existing is not None:
        if existing == rule:
            return
        raise ValueError(f"derivation rule {rule.rule_iri} is already registered with a different contract")
    _RULES[rule.rule_iri] = rule
    _WATCHED_PREDICATES.update(rule.watch_predicates)


def registered_derivation_rules() -> tuple[DerivationRule, ...]:
    """Every registered rule, in rule-IRI order."""

    return tuple(_RULES[key] for key in sorted(_RULES))


def reset_derivation_rule_registry() -> None:
    """Test-only: drop every registration and restore the built-ins."""

    _RULES.clear()
    _WATCHED_PREDICATES.clear()
    for rule in _BUILTIN_RULES:
        register_derivation_rule(rule)


def build_derived_row(
    *,
    rule: DerivationRule,
    subject: str,
    predicate: str,
    obj: str,
    ring: str,
    evidence: Iterable[str],
    context: DerivationContext,
) -> DerivedRelationRow:
    """Identify one derived row exactly as the binding's checks expect.

    The input digest keeps the binding's wire formula (canonical REF
    JSON over ``{"assertions":[{"assertion":...,"contentDigest":...},...]}``
    with rows sorted by node IRI, no terminal LF) even where the cited
    evidence is a source record rather than a relation assertion: the
    formula is part of the derived-record contract, and widening what a
    row may cite does not change how the cited rows are hashed.
    """

    inputs = tuple(sorted(set(evidence)))
    if not inputs:
        raise ValueError(f"{rule.rule_iri} derived row {subject} cites no evidence rows")
    missing = [node for node in inputs if node not in context.node_digest]
    if missing:
        raise ValueError(
            f"{rule.rule_iri} derived row {subject} cites evidence with no retained digest: {missing[0]}"
        )
    input_digest = context.canonical_sha256(
        {
            "assertions": [
                {"assertion": node, "contentDigest": context.node_digest[node]} for node in inputs
            ]
        }
    )
    content_digest = context.canonical_sha256(
        {
            "engine": rule.engine_iri,
            "engineVersion": rule.engine_version,
            "inputs": list(inputs),
            "object": obj,
            "predicate": predicate,
            "ring": ring,
            "rule": rule.rule_iri,
            "subject": subject,
        }
    )
    return DerivedRelationRow(
        rule_iri=rule.rule_iri,
        engine_iri=rule.engine_iri,
        engine_version=rule.engine_version,
        subject=subject,
        predicate=predicate,
        object=obj,
        ring=ring,
        evidence=inputs,
        input_digest=input_digest,
        content_digest=content_digest,
        node_iri="urn:ref:atlas-derived:" + content_digest.removeprefix("sha256:"),
    )


def iter_nquads_terms(line: str) -> tuple[str, str, str, str] | None:
    """Split one canonical N-Quads line into four raw term texts.

    Returns the subject, predicate, object, and graph terms with their
    delimiters intact (``<...>``, ``"..."`` plus any datatype or
    language suffix), or ``None`` for a line that is not four terms
    plus a terminating dot. Terms are assumed canonical -- single
    spaces, no comments -- which is the only form the Atlas spools
    write.

    The terminating ``.`` is itself a fifth term the loop below must
    recognize explicitly: it is neither an IRI (``<...>``) nor a
    literal (``"..."``), so a parser that only branches on those two
    openers falls through to "unrecognized term" and refuses every
    line, including well-formed ones.
    """

    terms: list[str] = []
    position = 0
    length = len(line)
    while len(terms) < 5:
        while position < length and line[position] == " ":
            position += 1
        if position >= length:
            return None
        character = line[position]
        if character == "<":
            end = line.find(">", position + 1)
            if end < 0:
                return None
            terms.append(line[position : end + 1])
            position = end + 1
        elif character == '"':
            cursor = position + 1
            while cursor < length:
                if line[cursor] == "\\":
                    cursor += 2
                    continue
                if line[cursor] == '"':
                    break
                cursor += 1
            if cursor >= length:
                return None
            cursor += 1
            if cursor < length and line[cursor] == "^":
                end = line.find(">", cursor)
                if end < 0:
                    return None
                cursor = end + 1
            elif cursor < length and line[cursor] == "@":
                cursor += 1
                while cursor < length and line[cursor] not in (" ", "\t"):
                    cursor += 1
            terms.append(line[position:cursor])
            position = cursor
        elif character == ".":
            terms.append(".")
            position += 1
        else:
            return None
    if terms[4] != "." or line[position:].strip():
        return None
    return terms[0], terms[1], terms[2], terms[3]


def iri_value(term: str) -> str:
    """Decode one N-Triples IRI term to its IRI text."""

    if not (term.startswith("<") and term.endswith(">")):
        raise ValueError(f"term is not an IRI: {term[:60]}")
    return term[1:-1]


def literal_value(term: str) -> str:
    """Decode the lexical value of one N-Triples literal term."""

    if not term.startswith('"'):
        raise ValueError(f"term is not a literal: {term[:60]}")
    position = 1
    length = len(term)
    while position < length:
        if term[position] == "\\":
            position += 2
            continue
        if term[position] == '"':
            body = term[1:position]
            return (
                body.replace("\\\\", "\x00")
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t")
                .replace("\x00", "\\")
            )
        position += 1
    raise ValueError(f"literal term has no closing quote: {term[:60]}")


def collect_asserted_fact_view(lines: Iterable[str]) -> AssertedFactView:
    """Build the shared fact view from canonical asserted N-Quads lines.

    Watched predicates come from the registered rules. The collector
    rejects a line whose subject carries two schemes, because ring and
    scheme invariants elsewhere in the binding already refuse that shape
    and a derivation must not read an asserted graph that could never
    validate.
    """

    view = AssertedFactView()
    if not _WATCHED_PREDICATES:
        return view
    scheme_conflicts: set[str] = set()
    ring_conflicts: set[str] = set()
    for line in lines:
        if not any(predicate + " " in line for predicate in _WATCHED_PREDICATES):
            continue
        terms = iter_nquads_terms(line)
        if terms is None:
            raise ValueError(f"asserted spool line is not canonical N-Quads: {line[:120]}")
        subject, predicate, obj, _graph = terms
        if predicate not in _WATCHED_PREDICATES:
            continue
        resource = iri_value(subject)
        if predicate == ATLAS_NOTATION_TERM and obj.startswith('"'):
            view.notations.setdefault(resource, set()).add(literal_value(obj))
        elif predicate == ATLAS_IN_SCHEME_TERM:
            scheme = iri_value(obj)
            previous = view.schemes.get(resource)
            if previous is not None and previous != scheme:
                scheme_conflicts.add(resource)
            else:
                view.schemes[resource] = scheme
        elif predicate == ATLAS_REPRESENTS_RESOURCE_TERM:
            view.records[iri_value(obj)] = resource
        elif predicate == ATLAS_SEMANTIC_RING_TERM:
            ring = iri_value(obj)
            previous_ring = view.rings.get(resource)
            if previous_ring is not None and previous_ring != ring:
                ring_conflicts.add(resource)
            else:
                view.rings[resource] = ring
    if scheme_conflicts:
        raise ValueError(f"asserted graph gives one resource two schemes: {min(scheme_conflicts)}")
    if ring_conflicts:
        raise ValueError(f"asserted graph gives one resource two semantic rings: {min(ring_conflicts)}")
    view.scheme_conflicts = ()
    return view


def collect_node_digests(lines: Iterable[str], wanted: frozenset[str]) -> dict[str, str]:
    """Binding-formula content digests for the given asserted node IRIs.

    Reproduces exactly what the validator's byte-pass digest computes
    for a retained node: the node's outgoing canonical N-Triples rows
    minus the self-digest predicates, sorted, joined with terminal LF,
    hashed. Rows accumulate per node, so subject contiguity in the
    input stream is not required.

    The reject-before-parse fast path is a subject-term set lookup, not
    a substring scan: canonical N-Quads terms never contain a literal
    space (IRIs are percent-encoded, literal spaces sit inside a quoted
    term after the subject), so the text up to the line's first space is
    always exactly the subject term. A rule citing thousands of source
    records as evidence -- MeSH tree numbers, for one -- turns an
    ``any(term in line for term in wanted_terms)`` substring scan into a
    quadratic pass over the whole spool; a set lookup keeps this linear.
    """

    wanted_terms = {f"<{node}>" for node in wanted}
    rows_by_node: dict[str, list[str]] = {}
    for line in lines:
        subject_term = line[: line.find(" ")] if " " in line else line
        if subject_term not in wanted_terms:
            continue
        terms = iter_nquads_terms(line)
        if terms is None:
            raise ValueError(f"asserted spool line is not canonical N-Quads: {line[:120]}")
        subject, predicate, obj, _graph = terms
        if subject != subject_term:
            raise ValueError(f"asserted spool line subject term does not match its own prefix: {line[:120]}")
        if predicate in _ATLAS_SELF_DIGEST_TERMS:
            continue
        rows_by_node.setdefault(subject, []).append(f"{predicate} {obj} .")
    digests: dict[str, str] = {}
    for subject, rows in rows_by_node.items():
        rows.sort()
        digest = hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()
        digests[iri_value(subject)] = "sha256:" + digest
    return digests


from refspec.atlas.derived_graph.mesh_tree_numbers import (
    MESH_TREE_NUMBER_BROADER_RULE,
)

register_derivation_rule(MESH_TREE_NUMBER_BROADER_RULE)
_BUILTIN_RULES = (MESH_TREE_NUMBER_BROADER_RULE,)

__all__ = [
    "ATLAS_IN_SCHEME_TERM",
    "ATLAS_NOTATION_TERM",
    "ATLAS_REPRESENTS_RESOURCE_TERM",
    "ATLAS_SEMANTIC_RING_TERM",
    "EVIDENCE_INPUT_ASSERTION",
    "EVIDENCE_INPUT_SOURCE_RECORD",
    "AssertedFactView",
    "DerivationContext",
    "DerivationRule",
    "DerivedRelationRow",
    "DerivedRuleOutcome",
    "build_derived_row",
    "collect_asserted_fact_view",
    "collect_node_digests",
    "iri_value",
    "iter_nquads_terms",
    "literal_value",
    "register_derivation_rule",
    "registered_derivation_rules",
    "reset_derivation_rule_registry",
]

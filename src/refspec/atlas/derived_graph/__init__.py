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
  NLM published and RefSpec already captures as ``atlas:notation``. It is
  wired into the producer (``tools/generate_atlas_v3_full.py``,
  ``_derive_registered_relations``) and admitted by the binding
  (``bindings/atlas/3.1/tools/validate.py``,
  ``_DERIVED_RULE_ADMISSIONS``) as of REF-042 (``docs/decisions.md``).
* the GCMD Science Keywords column-nesting hierarchy
  (:mod:`refspec.atlas.derived_graph.gcmd_column_nesting`), which derives
  ``skos:broader`` edges from the CSV path columns each keyword's
  ``SourceRecord`` native payload carries verbatim (REF-041's judgment,
  registered as the third rule by REF-043).

**Extension point for additional rules.** A new rule is one module in
this package that builds a :class:`DerivationRule`, plus two deliberate
registration lines at the bottom of this ``__init__`` (see the mesh
registration below), plus one allowlist entry in the binding validator
(``bindings/atlas/3.1/tools/validate.py``, ``_DERIVED_RULE_ADMISSIONS``)
carrying the same rule/engine/engine-version tuple, its admitted ring(s)
and predicate(s), its evidence kind, and its own row-shape and replay
checks -- the binding does not import this package (it stays a portable,
standalone validator), so the two sides are kept in sync by tests that
compare the literal constants, not by a shared import. Registration here
is necessary but not sufficient: the producer only populates rows for
rules whose source release was actually part of the build AND that the
binding's own registry admits (`tools/generate_atlas_v3_full.py` does not
consult the binding either; a rule wired into the producer without its
binding allowlist entry would ship rows the validator refuses, which is
exactly the failure mode REF-042's corpus cases prove the registry
catches).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

EVIDENCE_INPUT_ASSERTION = "assertion"
EVIDENCE_INPUT_SOURCE_RECORD = "sourceRecord"

ATLAS_NOTATION_TERM = "<https://refspec.org/ns/atlas/v3#notation>"
ATLAS_IN_SCHEME_TERM = "<https://refspec.org/ns/atlas/v3#inScheme>"
ATLAS_REPRESENTS_RESOURCE_TERM = "<https://refspec.org/ns/atlas/v3#representsResource>"
ATLAS_SEMANTIC_RING_TERM = "<https://refspec.org/ns/atlas/v3#semanticRing>"
ATLAS_NATIVE_PAYLOAD_TERM = "<https://refspec.org/ns/atlas/v3#nativePayload>"

# The DerivedRelation record shape itself -- every predicate a derived row
# carries, in the same terms `rdf_node_digest` would render them in if the
# row were built as an actual rdflib graph. `build_derived_row` renders these
# directly as strings instead of constructing a Graph: every value that
# lands here is either an IRI already read off the asserted graph (so already
# proven free of characters the canonical profile forbids) or a digest/version
# string this module itself mints, so the escaping `ntriples_term` would apply
# is always the identity transform. `test_mesh_tree_numbers.py`
# (`test_content_digest_matches_an_actual_rdflib_render`) proves that
# equivalence against the real `rdf_canonical.ntriples_term`, not just by
# argument.
RDF_TYPE_TERM = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
ATLAS_DERIVED_RELATION_TERM = "<https://refspec.org/ns/atlas/v3#DerivedRelation>"
ATLAS_RELATION_SUBJECT_TERM = "<https://refspec.org/ns/atlas/v3#relationSubject>"
ATLAS_RELATION_PREDICATE_TERM = "<https://refspec.org/ns/atlas/v3#relationPredicate>"
ATLAS_RELATION_OBJECT_TERM = "<https://refspec.org/ns/atlas/v3#relationObject>"
ATLAS_DERIVED_FROM_ASSERTION_TERM = "<https://refspec.org/ns/atlas/v3#derivedFromAssertion>"
ATLAS_DERIVATION_RULE_TERM = "<https://refspec.org/ns/atlas/v3#derivationRule>"
ATLAS_ENGINE_TERM = "<https://refspec.org/ns/atlas/v3#engine>"
ATLAS_ENGINE_VERSION_TERM = "<https://refspec.org/ns/atlas/v3#engineVersion>"
ATLAS_GENERATED_AT_TERM = "<https://refspec.org/ns/atlas/v3#generatedAt>"
RKAF_INPUT_DIGEST_TERM = "<https://rulespec.org/ns/v1#inputDigest>"
XSD_DATETIME_IRI = "http://www.w3.org/2001/XMLSchema#dateTime"

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
    (canonical REF JSON over the cited evidence rows, no terminal LF).
    ``content_digest``/``node_iri`` follow the binding's OTHER identity
    formula instead: `rdf_node_digest` -- the sha256 of this row's own
    sorted, rendered ``predicate object .`` facts (every property below
    plus ``rdf:type atlas:DerivedRelation``, excluding the self-digest
    predicates), exactly as `build_fixtures.py` already mints the
    exactMatch-transitivity row's identity. A row that used a different
    formula would still satisfy every check the 3.1 validator runs today
    (it only checks that the IRI and the stored digest agree with each
    other, not that the digest is THE canonical one), but it would mint
    derived-relation identity two different ways for two different rules,
    which is the kind of unforced inconsistency this package exists to
    rule out. `test_content_digest_matches_an_actual_rdflib_render` in
    ``tests/test_mesh_tree_numbers.py`` proves the two formulas agree byte
    for byte against the real `rdf_canonical.ntriples_term` renderer.
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
    generated_at: str
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
    each resource is represented by, the one semantic ring each
    resource declares, and the canonical native-payload JSON text each
    source record carries. Anything a future rule needs becomes a new
    field here, fed by a new watched predicate, so collection stays one
    pass.
    """

    notations: dict[str, set[str]] = field(default_factory=dict)
    schemes: dict[str, str] = field(default_factory=dict)
    records: dict[str, str] = field(default_factory=dict)
    rings: dict[str, str] = field(default_factory=dict)
    payloads: dict[str, str] = field(default_factory=dict)
    scheme_conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivationContext:
    """Everything a rule needs to derive rows from asserted facts.

    ``node_digest`` maps evidence node IRI to the binding-formula
    content digest of that node's asserted facts; ``canonical_sha256``
    is the binding's canonical-JSON digest, called with ``terminal_lf``
    as a keyword so callers must accept it exactly as
    ``validate.canonical_sha256`` does. ``generated_at`` is
    one ISO 8601 timestamp with an explicit offset, shared by every row
    one derivation run produces -- `atlas:generatedAt` is a required,
    single-valued property of `atlas:DerivedRelation`
    (``shapes/atlas.shacl.ttl``), so a producer run mints exactly one and
    stamps every row it emits with it, the same way a single build stamps
    every resource it touches with one `atlas:AtlasRelease`.
    """

    facts: AssertedFactView
    node_digest: Mapping[str, str]
    canonical_sha256: Callable[..., str]
    generated_at: str


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


def _derived_row_content_digest(
    *,
    rule: DerivationRule,
    subject: str,
    predicate: str,
    obj: str,
    ring: str,
    inputs: tuple[str, ...],
    input_digest: str,
    generated_at: str,
) -> str:
    """The binding's OTHER identity formula: hash this row's own facts.

    Mirrors `rdf_node_digest` exactly -- sorted, rendered
    ``predicate object .`` rows over every fact this record would carry
    as an actual RDF node (including its own `rdf:type`), excluding the
    self-digest predicates -- without building an rdflib graph to get
    there. Every value substituted below is either an IRI already read
    off the asserted graph (so already proven free of characters the
    canonical profile forbids) or a digest/version/timestamp string this
    module mints itself in a form `ntriples_term` renders unchanged, so
    string-formatting the term text here and asking `rdf_canonical` to do
    it are the same operation.
    """

    facts = [
        (RDF_TYPE_TERM, ATLAS_DERIVED_RELATION_TERM),
        (ATLAS_RELATION_SUBJECT_TERM, f"<{subject}>"),
        (ATLAS_RELATION_PREDICATE_TERM, f"<{predicate}>"),
        (ATLAS_RELATION_OBJECT_TERM, f"<{obj}>"),
        (ATLAS_SEMANTIC_RING_TERM, f"<{ring}>"),
        (ATLAS_DERIVATION_RULE_TERM, f"<{rule.rule_iri}>"),
        (ATLAS_ENGINE_TERM, f"<{rule.engine_iri}>"),
        (ATLAS_ENGINE_VERSION_TERM, f'"{rule.engine_version}"'),
        (RKAF_INPUT_DIGEST_TERM, f'"{input_digest}"'),
        (ATLAS_GENERATED_AT_TERM, f'"{generated_at}"^^<{XSD_DATETIME_IRI}>'),
        *((ATLAS_DERIVED_FROM_ASSERTION_TERM, f"<{node}>") for node in inputs),
    ]
    rows = sorted(f"{predicate_term} {object_term} ." for predicate_term, object_term in facts)
    return "sha256:" + hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def _require_offset_datetime(value: str, *, label: str) -> None:
    """Refuse a timestamp `_rdf_datetime` would refuse: no naive datetimes."""

    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO 8601 datetime: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include an explicit timezone offset: {value!r}")


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

    The content digest -- and the node IRI minted from it -- follows the
    OTHER formula instead: see `_derived_row_content_digest`.
    """

    inputs = tuple(sorted(set(evidence)))
    if not inputs:
        raise ValueError(f"{rule.rule_iri} derived row {subject} cites no evidence rows")
    missing = [node for node in inputs if node not in context.node_digest]
    if missing:
        raise ValueError(
            f"{rule.rule_iri} derived row {subject} cites evidence with no retained digest: {missing[0]}"
        )
    _require_offset_datetime(context.generated_at, label=f"{rule.rule_iri} derived row {subject} generatedAt")
    input_digest = context.canonical_sha256(
        {
            "assertions": [
                {"assertion": node, "contentDigest": context.node_digest[node]} for node in inputs
            ]
        },
        terminal_lf=False,
    )
    content_digest = _derived_row_content_digest(
        rule=rule,
        subject=subject,
        predicate=predicate,
        obj=obj,
        ring=ring,
        inputs=inputs,
        input_digest=input_digest,
        generated_at=context.generated_at,
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
        generated_at=context.generated_at,
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
        elif predicate == ATLAS_NATIVE_PAYLOAD_TERM and obj.startswith('"'):
            # Keyed by the node carrying the payload -- a SourceRecord, not
            # the resource it represents (`records` maps that other way).
            view.payloads[resource] = literal_value(obj)
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


from refspec.atlas.derived_graph.gcmd_column_nesting import (
    GCMD_COLUMN_NESTING_DERIVATION_RULE,
)
from refspec.atlas.derived_graph.mesh_tree_numbers import (
    MESH_TREE_NUMBER_BROADER_RULE,
)

register_derivation_rule(MESH_TREE_NUMBER_BROADER_RULE)
register_derivation_rule(GCMD_COLUMN_NESTING_DERIVATION_RULE)
_BUILTIN_RULES = (MESH_TREE_NUMBER_BROADER_RULE, GCMD_COLUMN_NESTING_DERIVATION_RULE)

__all__ = [
    "ATLAS_DERIVATION_RULE_TERM",
    "ATLAS_DERIVED_FROM_ASSERTION_TERM",
    "ATLAS_DERIVED_RELATION_TERM",
    "ATLAS_ENGINE_TERM",
    "ATLAS_ENGINE_VERSION_TERM",
    "ATLAS_GENERATED_AT_TERM",
    "ATLAS_IN_SCHEME_TERM",
    "ATLAS_NATIVE_PAYLOAD_TERM",
    "ATLAS_NOTATION_TERM",
    "ATLAS_RELATION_OBJECT_TERM",
    "ATLAS_RELATION_PREDICATE_TERM",
    "ATLAS_RELATION_SUBJECT_TERM",
    "ATLAS_REPRESENTS_RESOURCE_TERM",
    "ATLAS_SEMANTIC_RING_TERM",
    "EVIDENCE_INPUT_ASSERTION",
    "EVIDENCE_INPUT_SOURCE_RECORD",
    "RDF_TYPE_TERM",
    "RKAF_INPUT_DIGEST_TERM",
    "XSD_DATETIME_IRI",
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

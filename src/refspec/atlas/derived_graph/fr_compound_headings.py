"""Derived ``skos:broader`` edges for Federal Register compound headings.

The Office of the Federal Register's 2025 thesaurus
(``federal-register-thesaurus-2025``, 705 official indexing terms) is a
deliberately flat vocabulary: it publishes 1,451 ``skos:related``
references and zero broader/narrower statements of any kind (the 2025
revision expressly removed the 1995 broad document categories; see
``refspec.registry.federal_register_thesaurus_2025``). But its own term
list is full of compound headings whose head segment -- the text before
the first hyphen -- is itself an official term of the same release:
``Grant programs-agriculture`` under ``Grant programs``,
``Loan programs-veterans`` under ``Loan programs``. Reading a compound
heading's broader term as its head segment, where that head is an
authorized preferred term of the same release, is a structural
projection of the publisher's own term list, not an invention -- but it
is still RefSpec's act, not OFR's assertion of ``skos:broader``, so
under REF-035 tier E5 it belongs only in the derived graph, admitted
per-rule by the binding's rule registry (REF-042 in
``docs/decisions.md``).

**Verified against the real pinned 2025 release**
(``sha256:66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f``,
1,051,423 bytes, 705 official terms, 1,451 resolved ``skos:related``
references; preferred-label texts re-verified byte-identical against the
real distribution pack's asserted N-Quads):

* 56 preferred labels contain a hyphen.
* 48 of those have a head segment that is itself one of the 705
  preferred labels (19 under ``Grant programs``, 9 under ``Indians``, 14
  under ``Loan programs``, 6 under ``Public lands``).
* The remaining 8 are hyphenated *words*, not compound subjects:
  ``X-rays``, ``Truth-in-lending``, ``Truth-in-savings``,
  ``Rights-of-way``, ``Over-the-counter drugs``,
  ``Government-sponsored enterprises``, ``Human cells and tissue-based
  products``, ``Old-age, Survivors and Disability Insurance``. Their
  head segments (``X``, ``Truth``, ``Old``, ...) are not preferred
  terms, so they exclude themselves: the rule admits an edge only where
  the head resolves to a preferred label in the same scheme, and there
  is no hand-maintained denylist anywhere. That self-exclusion is the
  running check -- the tests pin all 8 by name and prove the converse
  (mint a ``X`` term and ``X-rays`` immediately derives its edge).
* No head segment resolves only to an alternate label (``skos:altLabel``
  text never admits an edge), no admitted head is itself hyphenated,
  and no two resources share a preferred-label text in this release.

This module follows the :mod:`refspec.atlas.derived_graph` machinery
(REF-042's MeSH tree-number rule is the worked template): it reads the
same canonical asserted N-Quads lines the shared collectors read, cites
each edge's two terms' ``SourceRecord`` IRIs as evidence
(``EVIDENCE_INPUT_SOURCE_RECORD`` -- a preferred label is a
resource-level fact, not a relation assertion), and mints rows through
:func:`build_derived_row` so identity and input digests match the
binding's formulas exactly.

**Scope.** The MeSH rule shipped scheme-blind and an adversarial review
caught it; this rule is scoped from birth. The label collector keeps
only resources whose ``atlas:inScheme`` is the Federal Register
thesaurus scheme, and the head must resolve within that same map, so a
``Grant programs`` resource in any other vocabulary can never admit a
Federal Register compound. The binding's row validator and replay must
require the same scheme (see the copy-ready admission entry this
module's report carries).

**One contract deviation, deliberate.** The shared
``AssertedFactView`` collects notations, schemes, records, and rings --
not labels, which live behind SKOS-XL ``prefLabel``/``literalForm``
links. Rather than widen the shared collector for one rule, this module
collects its own label view
(:func:`collect_fr_preferred_labels`) over the same lines, and its
derivation entry points take that view as a second argument next to the
shared ``DerivationContext``. Nothing dispatches
``DerivationRule.derive``/``evidence_nodes`` generically today (the
producer wiring calls each rule's module functions directly, exactly as
it calls the MeSH rule's with its own extra ``asserted_relations``
argument); should label-shaped facts earn a shared field later, the
second argument collapses into the context and this note goes away.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from refspec.atlas.derived_graph import (
    ATLAS_IN_SCHEME_TERM,
    ATLAS_REPRESENTS_RESOURCE_TERM,
    ATLAS_SEMANTIC_RING_TERM,
    EVIDENCE_INPUT_SOURCE_RECORD,
    AssertedFactView,
    DerivationContext,
    DerivationRule,
    DerivedRelationRow,
    DerivedRuleOutcome,
    build_derived_row,
    iri_value,
    iter_nquads_terms,
    literal_value,
)

SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
SKOS_NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"

SKOSXL_PREF_LABEL_TERM = "<http://www.w3.org/2008/05/skos-xl#prefLabel>"
SKOSXL_ALT_LABEL_TERM = "<http://www.w3.org/2008/05/skos-xl#altLabel>"
SKOSXL_LITERAL_FORM_TERM = "<http://www.w3.org/2008/05/skos-xl#literalForm>"

ATLAS_SUBJECT_RING = "https://refspec.org/ns/atlas/v3#subject"

FR_THESAURUS_SCHEME_IRI = "urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025"

FR_COMPOUND_HEADING_RULE_IRI = "urn:ref:rule:fr-thesaurus-compound-head-broader"
FR_COMPOUND_HEADING_ENGINE_IRI = "https://refspec.org/code/atlas-v3-derived-fr-compound-headings"
FR_COMPOUND_HEADING_ENGINE_VERSION = "1"

# Frozen against the pinned 2025 release
# (sha256:66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f,
# 705 official terms, 1,451 resolved related references).
FR_2025_PREFERRED_TERM_COUNT = 705
FR_2025_HYPHENATED_TERM_COUNT = 56
FR_2025_COMPOUND_EDGE_COUNT = 48
FR_2025_SELF_EXCLUDED_TERM_COUNT = 8


class FrCompoundHeadingDerivationError(ValueError):
    """A compound-heading derivation premise the rule refuses to guess past."""


@dataclass(frozen=True, slots=True)
class FrCompoundHeadingCounts:
    """The reconciling counters the real-data test pins exactly."""

    preferred_terms: int
    hyphenated_terms: int
    edges: int
    self_excluded: int


def compound_head(label: str) -> str:
    """The text before the first hyphen -- a label with no hyphen is its own head."""

    return label.split("-", 1)[0]


def resolve_compound_heading_edges_from_labels(
    preferred_labels_by_resource: Mapping[str, str],
) -> tuple[tuple[tuple[str, str], ...], FrCompoundHeadingCounts]:
    """Resolve every compound heading to its head resource, or count why not.

    The one pure algorithm both the asserted-fact-view path
    (:func:`_resolve_edge_pairs`, reading a real spooled N-Quads pass)
    and the producer's prebuild count (reading in-memory release
    resources before any spool exists) delegate to, so the row count the
    prebuild receipt commits to and the row set the streamed build emits
    can never independently drift.

    An edge is admitted only where the compound's head segment is the
    preferred label of a *different* resource in the same mapping --
    which the caller has already scoped to one scheme. There is no
    denylist: a hyphenated label whose head is not a preferred term
    simply never resolves, and is counted as self-excluded. Refuses
    outright when two resources share one preferred-label text, because
    an ambiguous head must never be guessed an owner.
    """

    resource_by_text: dict[str, str] = {}
    for resource, text in preferred_labels_by_resource.items():
        previous = resource_by_text.setdefault(text, resource)
        if previous != resource:
            raise FrCompoundHeadingDerivationError(
                f"preferred label is ambiguous between two terms: {text!r}"
            )
    hyphenated = sum(1 for text in resource_by_text if "-" in text)
    pairs: set[tuple[str, str]] = set()
    self_excluded = 0
    for resource, text in preferred_labels_by_resource.items():
        if "-" not in text:
            continue
        head_resource = resource_by_text.get(compound_head(text))
        if head_resource is None or head_resource == resource:
            self_excluded += 1
            continue
        pairs.add((resource, head_resource))
    counts = FrCompoundHeadingCounts(
        preferred_terms=len(preferred_labels_by_resource),
        hyphenated_terms=hyphenated,
        edges=len(pairs),
        self_excluded=self_excluded,
    )
    return tuple(sorted(pairs)), counts


def collect_fr_preferred_labels(
    lines: Iterable[str],
    facts: AssertedFactView,
) -> dict[str, str]:
    """Read every Federal Register preferred label from asserted N-Quads lines.

    One pass over the same canonical lines the shared fact view read,
    keeping only ``skosxl:prefLabel`` links whose subject's
    ``atlas:inScheme`` is the Federal Register thesaurus scheme, and the
    ``skosxl:literalForm`` text of the label nodes they point at.
    Alternate labels are collected only to be ignored -- a head that
    resolves to nothing but an altLabel admits no edge. For every
    in-scheme resource that carries a preferred label, the label facts
    must be unambiguous: exactly one ``prefLabel`` link, exactly one
    literal form on its label node, non-empty trimmed text. A resource
    with no preferred label at all (the scheme's own AtlasRelease node,
    for one) is not this rule's population and passes through unheard.
    """

    literal_forms: dict[str, str] = {}
    label_links: dict[str, list[str]] = {}
    watched = (SKOSXL_PREF_LABEL_TERM, SKOSXL_LITERAL_FORM_TERM)
    for line in lines:
        if not any(predicate + " " in line for predicate in watched):
            continue
        terms = iter_nquads_terms(line)
        if terms is None:
            raise FrCompoundHeadingDerivationError(
                f"asserted spool line is not canonical N-Quads: {line[:120]}"
            )
        subject, predicate, obj, _graph = terms
        if predicate == SKOSXL_LITERAL_FORM_TERM:
            if not obj.startswith('"'):
                raise FrCompoundHeadingDerivationError(
                    f"label literal form is not a literal: {line[:120]}"
                )
            label_node = iri_value(subject)
            text = literal_value(obj)
            previous = literal_forms.setdefault(label_node, text)
            if previous != text:
                raise FrCompoundHeadingDerivationError(
                    f"label node carries two literal forms: {label_node}"
                )
        elif predicate == SKOSXL_PREF_LABEL_TERM:
            label_links.setdefault(iri_value(subject), []).append(iri_value(obj))
    preferred: dict[str, str] = {}
    for resource, links in label_links.items():
        if facts.schemes.get(resource) != FR_THESAURUS_SCHEME_IRI:
            continue
        if len(links) != 1:
            raise FrCompoundHeadingDerivationError(
                f"Federal Register term {resource} does not carry exactly one preferred label"
            )
        text = literal_forms.get(links[0])
        if text is None:
            raise FrCompoundHeadingDerivationError(
                f"preferred label of {resource} has no literal form: {links[0]}"
            )
        if not text or text != text.strip():
            raise FrCompoundHeadingDerivationError(
                f"preferred label of {resource} must be non-empty trimmed text: {text!r}"
            )
        preferred[resource] = text
    return preferred


def _resolve_edge_pairs(
    facts: AssertedFactView,
    preferred_labels: Mapping[str, str],
) -> tuple[tuple[tuple[str, str], ...], FrCompoundHeadingCounts]:
    """Resolve every Federal Register compound heading, or count why not."""

    scoped = {
        resource: text
        for resource, text in preferred_labels.items()
        if facts.schemes.get(resource) == FR_THESAURUS_SCHEME_IRI
    }
    return resolve_compound_heading_edges_from_labels(scoped)


def resolve_fr_compound_heading_edges(
    facts: AssertedFactView,
    preferred_labels: Mapping[str, str],
) -> tuple[tuple[tuple[str, str], ...], FrCompoundHeadingCounts]:
    """Public entry point: the pure compound/head pair resolution plus counts."""

    return _resolve_edge_pairs(facts, preferred_labels)


def fr_compound_heading_evidence_nodes(
    facts: AssertedFactView,
    preferred_labels: Mapping[str, str],
) -> frozenset[str]:
    """The source-record IRIs :func:`derive_fr_compound_heading_broader_rows` cites."""

    pairs, _counts = _resolve_edge_pairs(facts, preferred_labels)
    resources: set[str] = set()
    for compound, head in pairs:
        resources.add(compound)
        resources.add(head)
    missing_records = [resource for resource in resources if resource not in facts.records]
    if missing_records:
        raise FrCompoundHeadingDerivationError(
            f"Federal Register term {missing_records[0]} has no source record to cite as derivation evidence"
        )
    return frozenset(facts.records[resource] for resource in resources)


def derive_fr_compound_heading_broader_rows(
    context: DerivationContext,
    preferred_labels: Mapping[str, str],
    *,
    asserted_relations: frozenset[tuple[str, str, str]] = frozenset(),
) -> DerivedRuleOutcome:
    """Derive every Federal Register compound-heading ``skos:broader`` row.

    ``preferred_labels`` is this module's own label view
    (:func:`collect_fr_preferred_labels`) -- see the module docstring
    for why it travels beside the shared context rather than inside it.
    ``asserted_relations`` carries already-asserted (subject IRI,
    predicate IRI, object IRI) triples; a derived edge that would
    duplicate one -- or its ``skos:narrower`` inverse -- is refused,
    never silently dropped. ``federal-register-thesaurus-2025`` asserts
    zero hierarchical relations today, so a synthetic collision in the
    tests exercises this; the real-data test threads the release's own
    1,451 ``skos:related`` assertions through to prove none of them
    collide with the 48 derived edges.
    """

    facts = context.facts
    pairs, counts = _resolve_edge_pairs(facts, preferred_labels)
    rows: list[DerivedRelationRow] = []
    for compound, head in pairs:
        compound_ring = facts.rings.get(compound)
        head_ring = facts.rings.get(head)
        if compound_ring != ATLAS_SUBJECT_RING or head_ring != ATLAS_SUBJECT_RING:
            raise FrCompoundHeadingDerivationError(
                f"compound-heading edge endpoint is not in the subject ring: {compound} -> {head}"
            )
        if (compound, SKOS_BROADER, head) in asserted_relations or (
            head,
            SKOS_NARROWER,
            compound,
        ) in asserted_relations:
            raise FrCompoundHeadingDerivationError(
                f"derived edge {compound} -> {head} duplicates an asserted relation (or its narrower inverse)"
            )
        compound_record = facts.records.get(compound)
        head_record = facts.records.get(head)
        if compound_record is None or head_record is None:
            raise FrCompoundHeadingDerivationError(
                f"Federal Register term has no source record for derived edge {compound} -> {head}"
            )
        rows.append(
            build_derived_row(
                rule=FR_COMPOUND_HEADING_BROADER_RULE,
                subject=compound,
                predicate=SKOS_BROADER,
                obj=head,
                ring=ATLAS_SUBJECT_RING,
                evidence=(compound_record, head_record),
                context=context,
            )
        )
    rows.sort(key=lambda row: row.node_iri)
    return DerivedRuleOutcome(
        rows=tuple(rows),
        counts={
            "edges": counts.edges,
            "preferredTerms": counts.preferred_terms,
            "hyphenatedTerms": counts.hyphenated_terms,
            "selfExcluded": counts.self_excluded,
        },
    )


FR_COMPOUND_HEADING_BROADER_RULE = DerivationRule(
    rule_iri=FR_COMPOUND_HEADING_RULE_IRI,
    engine_iri=FR_COMPOUND_HEADING_ENGINE_IRI,
    engine_version=FR_COMPOUND_HEADING_ENGINE_VERSION,
    evidence_input_kind=EVIDENCE_INPUT_SOURCE_RECORD,
    watch_predicates=frozenset(
        {
            ATLAS_IN_SCHEME_TERM,
            ATLAS_REPRESENTS_RESOURCE_TERM,
            ATLAS_SEMANTIC_RING_TERM,
            SKOSXL_PREF_LABEL_TERM,
            SKOSXL_LITERAL_FORM_TERM,
        }
    ),
    # Both callables additionally require this module's label view as a
    # second argument (see the module docstring): the shared
    # AssertedFactView carries no labels, and nothing dispatches these
    # through the rule object generically -- the producer wiring and the
    # tests call the module functions directly, as they do the MeSH
    # rule's.
    evidence_nodes=fr_compound_heading_evidence_nodes,
    derive=derive_fr_compound_heading_broader_rows,
    label="Federal Register compound-heading broader",
)


def _escape_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_fr_thesaurus_asserted_nquads_lines(release: object) -> tuple[str, ...]:
    """Project one Federal Register thesaurus release into the asserted facts this rule reads.

    Emits scheme membership, semantic ring, one synthetic ``SourceRecord``
    per term, and SKOS-XL label nodes for every preferred and alternate
    label (alternates included on purpose: the rule must keep deriving
    exactly its 48 edges over a graph that carries all 433 of them),
    using the shapes a real asserted spool carries. Label-node IRIs are
    synthetic content-derived digests -- stable and unique per label,
    which is all evidence citation and joining need.
    """

    if release.scheme_iri != FR_THESAURUS_SCHEME_IRI:  # type: ignore[attr-defined]
        raise ValueError(f"release is not the Federal Register thesaurus scheme: {release.scheme_iri}")  # type: ignore[attr-defined]
    if release.ring != "subject":  # type: ignore[attr-defined]
        raise ValueError(f"release is not in the subject ring: {release.ring}")  # type: ignore[attr-defined]
    graph_id = "<urn:ref:atlas:graph:v3:asserted>"
    lines: list[str] = []
    for resource in release.resources:  # type: ignore[attr-defined]
        subject = f"<{resource.iri}>"  # type: ignore[attr-defined]
        record = f"<urn:ref:atlas-source-record:fr-compound-fixture:{resource.iri.rsplit(':', 1)[-1]}>"  # type: ignore[attr-defined]
        lines.append(f"{subject} {ATLAS_IN_SCHEME_TERM} <{FR_THESAURUS_SCHEME_IRI}> {graph_id} .")
        lines.append(f"{subject} {ATLAS_SEMANTIC_RING_TERM} <{ATLAS_SUBJECT_RING}> {graph_id} .")
        for label_row in resource.labels:  # type: ignore[attr-defined]
            digest = hashlib.sha256(
                f"{resource.iri}|{label_row.role}|{label_row.value}".encode()  # type: ignore[attr-defined]
            ).hexdigest()[:32]
            label = f"<urn:ref:atlas-label:fr-compound-fixture:{digest}>"
            role_term = (
                SKOSXL_PREF_LABEL_TERM if label_row.role == "preferred" else SKOSXL_ALT_LABEL_TERM  # type: ignore[attr-defined]
            )
            lines.append(f"{subject} {role_term} {label} {graph_id} .")
            lines.append(
                f'{label} {SKOSXL_LITERAL_FORM_TERM} "{_escape_literal(label_row.value)}"@en {graph_id} .'  # type: ignore[attr-defined]
            )
        lines.append(f"{record} {ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {graph_id} .")
    return tuple(lines)


def main() -> None:
    """Print the derived row set over the real pinned Federal Register 2025 release."""

    import json

    from refspec.atlas.derived_graph import collect_asserted_fact_view, collect_node_digests
    from refspec.atlas.v3_registry_vocabularies import load_federal_register_2025_release

    def canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if terminal_lf:
            text += "\n"
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    release = load_federal_register_2025_release()
    lines = build_fr_thesaurus_asserted_nquads_lines(release)
    facts = collect_asserted_fact_view(lines)
    preferred = collect_fr_preferred_labels(lines, facts)
    wanted = fr_compound_heading_evidence_nodes(facts, preferred)
    node_digest = collect_node_digests(lines, wanted)
    context = DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=canonical_sha256,
        generated_at="2026-01-01T00:00:00+00:00",
    )
    outcome = derive_fr_compound_heading_broader_rows(context, preferred)
    print(f"terms={len(release.resources)} lines={len(lines)}")
    print(f"counts={outcome.counts}")
    print(f"edges={len(outcome.rows)}")
    print(f"sample row={outcome.rows[0]}")


if __name__ == "__main__":
    main()


__all__ = [
    "ATLAS_SUBJECT_RING",
    "FR_2025_COMPOUND_EDGE_COUNT",
    "FR_2025_HYPHENATED_TERM_COUNT",
    "FR_2025_PREFERRED_TERM_COUNT",
    "FR_2025_SELF_EXCLUDED_TERM_COUNT",
    "FR_COMPOUND_HEADING_BROADER_RULE",
    "FR_COMPOUND_HEADING_ENGINE_IRI",
    "FR_COMPOUND_HEADING_ENGINE_VERSION",
    "FR_COMPOUND_HEADING_RULE_IRI",
    "FR_THESAURUS_SCHEME_IRI",
    "SKOSXL_ALT_LABEL_TERM",
    "SKOSXL_LITERAL_FORM_TERM",
    "SKOSXL_PREF_LABEL_TERM",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "FrCompoundHeadingCounts",
    "FrCompoundHeadingDerivationError",
    "build_fr_thesaurus_asserted_nquads_lines",
    "collect_fr_preferred_labels",
    "compound_head",
    "derive_fr_compound_heading_broader_rows",
    "fr_compound_heading_evidence_nodes",
    "resolve_compound_heading_edges_from_labels",
    "resolve_fr_compound_heading_edges",
]

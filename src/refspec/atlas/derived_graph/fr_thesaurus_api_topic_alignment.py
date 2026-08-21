"""Derived ``skos:closeMatch`` edges between the two Federal Register vocabularies.

Atlas carries two vocabularies published by the Office of the Federal
Register and asserts nothing between them. ``federal-register-thesaurus-2025``
is the 705-concept curated thesaurus; ``federal-register-api-topics`` is the
1,044-term list documents are actually indexed with. Their relation edges are
entirely internal -- 1,451 ``skos:related`` inside the thesaurus, 1,428 inside
the API topics -- and **zero** statements cross between them, in either
direction, in the asserted graph or the derived one. Two islands from one
publisher.

That gap has a concrete cost. Evaluating a tagger against real Federal
Register indexing means joining a predicted thesaurus concept to an observed
API topic, and today that join can only be made on **label string
coincidence**. This rule replaces the coincidence with a recorded, replayable
derivation.

**Why derived and not asserted.** Under REF-035 (``docs/decisions.md``)
standing asks whether the asserter owns either endpoint vocabulary. The
Office of the Federal Register owns both; RefSpec owns neither. A mapping
assertion from RefSpec is therefore E4 -- RefSpec's own adjudication, the
weakest tier, and the one REF-035 notes is outranked by E3 precisely because
it has no external comparand. But the evidence here is not an adjudication at
all: it is exact normalized equality between two label sets, mechanical and
reproducible by anyone holding the same two releases. Recording a mechanical
projection as if it were a judgement would overstate it. REF-035 tier E5 --
"an inferred edge is never an assertion; it belongs only in the derived graph
and remains opt-in" -- is the honest shape, admitted per-rule by the binding's
rule registry (REF-042).

**Why ``skos:closeMatch`` and never ``skos:exactMatch``.** SKOS S45 makes
``exactMatch`` transitive, so a single wrong edge contaminates every chain it
joins; the binding already runs a corpus-wide S46 preflight because a new
``exactMatch`` can merge components and invalidate a ``relatedMatch`` in a
release nobody edited. Label equality between two vocabularies does not
license that. It licenses ``closeMatch``, which SKOS S43 makes symmetric but
**not** transitive: "sufficiently similar that they can be used
interchangeably in some information retrieval applications" is exactly the
claim the evidence supports, and interchangeability in retrieval is exactly
what a tagging evaluation needs. The FAST/LCSH precedent in
``research/vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md`` is the
cautionary case: OCLC asserts ``schema:sameAs`` over 259,401 strictly 1:1
links and the Library of Congress reciprocates with ``closeMatch`` and
nothing meaning exact. 1:1 cardinality is topology, not semantics.

**The population is a strict bijection.** 698 thesaurus terms match 698 API
topics across 698 pairs -- no term reaches two topics and no topic is reached
by two terms. That falls out of per-scheme label uniqueness, which IS checked
and fails closed: two terms folding to one key inside either list is a finding
about that publisher's vocabulary rather than an edge to derive. The explicit
bijection assertion after the intersection is therefore defensive rather than
reachable, and is documented as such where it lives.

**Scheme-scoped in both directions.** Like the EuroVoc microthesaurus rule
and unlike the MeSH tree-number rule as first shipped, subject and object
must sit in the two named schemes -- a matching label on a resource in any
other scheme can never admit an edge. The MeSH rule shipped scheme-blind and
an adversarial battery caught it proving parentage from notation shape alone
(REF-043); every rule since is scoped from birth.

**Case folding is deliberate and is the only normalization applied.** The two
vocabularies drift in case on three terms the same publisher spells two ways
(``Armed Forces``/``Armed forces``, ``Armed Forces Reserves``/``Armed forces
reserves``, ``Diesel fuel``/``Diesel Fuel``). Verbatim equality yields 695
pairs; case-folded yields 698. Case drift within one publisher's own two
lists is not a semantic distinction. Nothing else is normalized -- no
punctuation stripping, no NFKC, no stemming -- because every additional
transform widens the population on evidence the label texts do not carry.

Labels live behind SKOS-XL ``prefLabel``/``literalForm`` and the shared
:class:`AssertedFactView` carries no labels, so this module collects its own
label view (:func:`collect_fr_alignment_preferred_labels`) over the same
lines, and passes it beside the context to both entry points -- the pattern
:mod:`refspec.atlas.derived_graph.fr_compound_headings` established. Should
label-shaped facts earn a shared field later, both modules move together.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from refspec.atlas.derived_graph import (
    ATLAS_IN_SCHEME_TERM,
    ATLAS_REPRESENTS_RESOURCE_TERM,
    ATLAS_SEMANTIC_RING_TERM,
    AssertedFactView,
    DerivationContext,
    DerivationRule,
    DerivedRelationRow,
    DerivedRuleOutcome,
    EVIDENCE_INPUT_SOURCE_RECORD,
    build_derived_row,
    iter_nquads_terms,
)

SKOS_CLOSE_MATCH = "http://www.w3.org/2004/02/skos/core#closeMatch"
SKOS_EXACT_MATCH = "http://www.w3.org/2004/02/skos/core#exactMatch"

SKOSXL_ALT_LABEL_TERM = "<http://www.w3.org/2008/05/skos-xl#altLabel>"
SKOSXL_PREF_LABEL_TERM = "<http://www.w3.org/2008/05/skos-xl#prefLabel>"
SKOSXL_LITERAL_FORM_TERM = "<http://www.w3.org/2008/05/skos-xl#literalForm>"

ATLAS_SUBJECT_RING = "https://refspec.org/ns/atlas/v3#subject"

FR_THESAURUS_SCHEME_IRI = "urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025"
FR_API_TOPICS_SCHEME_IRI = "urn:ref:atlas-resource-scheme:federal-register-api-topics"

FR_THESAURUS_API_TOPIC_RULE_IRI = "urn:ref:rule:fr-thesaurus-api-topic-label-equality"
FR_THESAURUS_API_TOPIC_ENGINE_IRI = (
    "https://refspec.org/code/atlas-v3-derived-fr-thesaurus-api-topic-alignment"
)
FR_THESAURUS_API_TOPIC_ENGINE_VERSION = "1"

#: Measured against the 2026-08-20 sealed distribution. A drift in any of
#: these is a change in one of the two publisher lists, not a code change,
#: and the real-data test states them so drift is visible rather than silent.
FR_ALIGNMENT_THESAURUS_TERM_COUNT = 705
FR_ALIGNMENT_API_TOPIC_COUNT = 1044
FR_ALIGNMENT_EDGE_COUNT = 698
FR_ALIGNMENT_VERBATIM_EDGE_COUNT = 695


class FrThesaurusApiTopicDerivationError(ValueError):
    """Raised when the two Federal Register label sets cannot admit a clean edge set."""


@dataclass(frozen=True, slots=True)
class FrThesaurusApiTopicCounts:
    """Counters that reconcile one derivation run against the two label sets."""

    edges: int
    thesaurus_terms: int
    api_topics: int
    thesaurus_unmatched: int
    api_topic_unmatched: int
    case_folded_only: int


def fold(label: str) -> str:
    """The one normalization this rule applies: strip, then casefold.

    Deliberately not NFKC, not punctuation-stripping, not stemming. See the
    module docstring: every additional transform widens the population on
    evidence the label texts do not carry.
    """

    return label.strip().casefold()


def collect_fr_alignment_preferred_labels(
    lines: Iterable[str],
    facts: AssertedFactView,
) -> dict[str, str]:
    """Read preferred labels for both Federal Register schemes from asserted N-Quads.

    One pass over the same canonical lines the shared fact view read,
    keeping ``skosxl:prefLabel`` links whose subject's ``atlas:inScheme`` is
    either Federal Register scheme, and the ``skosxl:literalForm`` text of
    the label nodes they point at. Label facts must be unambiguous for every
    in-scope resource that carries one: exactly one ``prefLabel`` link,
    exactly one literal form on its label node, non-empty trimmed text. A
    resource with no preferred label (each scheme's own release node, for
    one) is not this rule's population and passes through unheard.
    """

    literal_forms: dict[str, str] = {}
    label_links: dict[str, list[str]] = {}
    watched = (SKOSXL_PREF_LABEL_TERM, SKOSXL_LITERAL_FORM_TERM)
    in_scope = {FR_THESAURUS_SCHEME_IRI, FR_API_TOPICS_SCHEME_IRI}

    for line in lines:
        if not any(predicate + " " in line for predicate in watched):
            continue
        terms = iter_nquads_terms(line)
        if terms is None:
            raise FrThesaurusApiTopicDerivationError(
                f"asserted spool line is not canonical N-Quads: {line[:120]}"
            )
        subject, predicate, obj, _graph = terms
        if predicate == SKOSXL_LITERAL_FORM_TERM:
            if not obj.startswith('"'):
                raise FrThesaurusApiTopicDerivationError(
                    f"label literal form is not a literal: {line[:120]}"
                )
            node = subject.strip("<>")
            text = _literal_text(obj)
            if node in literal_forms and literal_forms[node] != text:
                raise FrThesaurusApiTopicDerivationError(
                    f"label node {node} carries two different literal forms"
                )
            literal_forms[node] = text
            continue
        resource = subject.strip("<>")
        if facts.schemes.get(resource) not in in_scope:
            continue
        label_links.setdefault(resource, []).append(obj.strip("<>"))

    labels: dict[str, str] = {}
    for resource, nodes in label_links.items():
        if len(nodes) != 1:
            raise FrThesaurusApiTopicDerivationError(
                f"Federal Register resource {resource} carries {len(nodes)} preferred labels; exactly one is required"
            )
        node = nodes[0]
        text = literal_forms.get(node)
        if text is None:
            raise FrThesaurusApiTopicDerivationError(
                f"preferred label node {node} for {resource} has no literal form"
            )
        if not text.strip():
            raise FrThesaurusApiTopicDerivationError(
                f"preferred label for {resource} is empty once trimmed"
            )
        labels[resource] = text
    return labels


def _literal_text(term: str) -> str:
    closing = term.rfind('"')
    if closing <= 0:
        raise FrThesaurusApiTopicDerivationError(f"malformed literal term: {term[:80]}")
    body = term[1:closing]
    return body.replace('\\"', '"').replace("\\\\", "\\")


def _scheme_labels(
    facts: AssertedFactView,
    preferred_labels: Mapping[str, str],
    scheme_iri: str,
) -> dict[str, str]:
    return {
        resource: label
        for resource, label in preferred_labels.items()
        if facts.schemes.get(resource) == scheme_iri
    }


def resolve_fr_thesaurus_api_topic_edges(
    facts: AssertedFactView,
    preferred_labels: Mapping[str, str],
) -> tuple[tuple[tuple[str, str], ...], FrThesaurusApiTopicCounts]:
    """Resolve every thesaurus-term to API-topic edge, and prove the match is 1:1.

    Returns ``((thesaurus_resource, api_topic_resource), ...)`` sorted by
    subject IRI, with the counters that reconcile it. Raises when a folded
    label is not unique inside its own scheme -- a finding about that
    publisher list rather than an edge to emit.

    The bijection assertion below is **defensive, not a live check**:
    :func:`_index_by_fold` already admits one resource per folded key per
    scheme, so intersecting two such indexes cannot produce a repeated
    subject or object. It is kept so that a future change to the index --
    admitting a first-wins winner, say, instead of raising -- cannot silently
    drop the bijection guarantee this rule's row and replay checks both
    assume. `test_bijection_guard_is_defensive_the_index_fires_first` pins
    that ordering so the claim stays true.
    """

    thesaurus = _scheme_labels(facts, preferred_labels, FR_THESAURUS_SCHEME_IRI)
    api_topics = _scheme_labels(facts, preferred_labels, FR_API_TOPICS_SCHEME_IRI)
    return resolve_fr_thesaurus_api_topic_edges_from_scheme_labels(thesaurus, api_topics)


def resolve_fr_thesaurus_api_topic_edges_from_scheme_labels(
    thesaurus: Mapping[str, str],
    api_topics: Mapping[str, str],
) -> tuple[tuple[tuple[str, str], ...], FrThesaurusApiTopicCounts]:
    """The matching core, over two already-scheme-scoped label maps.

    Split out so the producer's prebuild count and the streamed derivation
    share ONE implementation of the match. The streamed pass arrives here
    with labels read from asserted N-Quads; the prebuild arrives with the
    same labels read from in-memory release resources. Only the way the two
    maps are obtained differs -- the fold, the per-scheme index, the
    bijection guard and the counters are computed once, here, so the
    expected count and the emitted rows cannot drift apart.
    """

    thesaurus_by_fold = _index_by_fold(thesaurus, "federal-register-thesaurus-2025")
    api_by_fold = _index_by_fold(api_topics, "federal-register-api-topics")

    shared = sorted(set(thesaurus_by_fold) & set(api_by_fold))
    pairs = tuple(sorted((thesaurus_by_fold[key], api_by_fold[key]) for key in shared))

    subjects = {subject for subject, _ in pairs}
    objects = {obj for _, obj in pairs}
    if len(subjects) != len(pairs) or len(objects) != len(pairs):
        raise FrThesaurusApiTopicDerivationError(
            "Federal Register label match is not a bijection: "
            f"{len(pairs)} pairs over {len(subjects)} terms and {len(objects)} topics"
        )

    case_folded_only = sum(
        1
        for key in shared
        if thesaurus[thesaurus_by_fold[key]].strip() != api_topics[api_by_fold[key]].strip()
    )
    counts = FrThesaurusApiTopicCounts(
        edges=len(pairs),
        thesaurus_terms=len(thesaurus),
        api_topics=len(api_topics),
        thesaurus_unmatched=len(thesaurus) - len(pairs),
        api_topic_unmatched=len(api_topics) - len(pairs),
        case_folded_only=case_folded_only,
    )
    return pairs, counts


def _index_by_fold(labels: Mapping[str, str], scheme_name: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for resource, label in labels.items():
        key = fold(label)
        existing = index.get(key)
        if existing is not None and existing != resource:
            raise FrThesaurusApiTopicDerivationError(
                f"{scheme_name} has two resources sharing the folded preferred label {key!r}: "
                f"{existing} and {resource}"
            )
        index[key] = resource
    return index


def fr_thesaurus_api_topic_evidence_nodes(
    facts: AssertedFactView,
    preferred_labels: Mapping[str, str],
) -> frozenset[str]:
    """The source-record IRIs :func:`derive_fr_thesaurus_api_topic_rows` cites."""

    pairs, _counts = resolve_fr_thesaurus_api_topic_edges(facts, preferred_labels)
    resources: set[str] = set()
    for term, topic in pairs:
        resources.add(term)
        resources.add(topic)
    missing = [resource for resource in sorted(resources) if resource not in facts.records]
    if missing:
        raise FrThesaurusApiTopicDerivationError(
            f"Federal Register resource {missing[0]} has no source record to cite as derivation evidence"
        )
    return frozenset(facts.records[resource] for resource in resources)


def derive_fr_thesaurus_api_topic_rows(
    context: DerivationContext,
    preferred_labels: Mapping[str, str],
    *,
    asserted_relations: frozenset[tuple[str, str, str]] = frozenset(),
) -> DerivedRuleOutcome:
    """Derive every Federal Register thesaurus-to-API-topic ``skos:closeMatch`` row.

    ``preferred_labels`` is this module's own label view
    (:func:`collect_fr_alignment_preferred_labels`) -- see the module
    docstring for why it travels beside the shared context rather than inside
    it. ``asserted_relations`` carries already-asserted (subject, predicate,
    object) triples; a derived edge that would duplicate one is refused
    rather than silently dropped. ``skos:closeMatch`` is symmetric under SKOS
    S43, so both orientations are checked, and an existing ``exactMatch``
    between the same two resources is refused too -- deriving a weaker
    predicate over a stronger asserted one would be noise at best and a
    contradiction at worst.
    """

    pairs, counts = resolve_fr_thesaurus_api_topic_edges(context.facts, preferred_labels)
    rows: list[DerivedRelationRow] = []
    for term, topic in pairs:
        term_ring = context.facts.rings.get(term)
        topic_ring = context.facts.rings.get(topic)
        if term_ring != ATLAS_SUBJECT_RING or topic_ring != ATLAS_SUBJECT_RING:
            raise FrThesaurusApiTopicDerivationError(
                f"Federal Register alignment endpoint is not in the subject ring: {term} -> {topic}"
            )
        for subject, predicate, obj in (
            (term, SKOS_CLOSE_MATCH, topic),
            (topic, SKOS_CLOSE_MATCH, term),
            (term, SKOS_EXACT_MATCH, topic),
            (topic, SKOS_EXACT_MATCH, term),
        ):
            if (subject, predicate, obj) in asserted_relations:
                raise FrThesaurusApiTopicDerivationError(
                    f"derived edge {term} -> {topic} duplicates an asserted relation "
                    f"({subject} {predicate} {obj})"
                )
        term_record = context.facts.records.get(term)
        topic_record = context.facts.records.get(topic)
        if term_record is None or topic_record is None:
            raise FrThesaurusApiTopicDerivationError(
                f"Federal Register resource has no source record for derived edge {term} -> {topic}"
            )
        rows.append(
            build_derived_row(
                rule=FR_THESAURUS_API_TOPIC_RULE,
                subject=term,
                predicate=SKOS_CLOSE_MATCH,
                obj=topic,
                ring=ATLAS_SUBJECT_RING,
                evidence=(term_record, topic_record),
                context=context,
            )
        )
    rows.sort(key=lambda row: row.node_iri)
    return DerivedRuleOutcome(
        rows=tuple(rows),
        counts={
            "edges": counts.edges,
            "thesaurusTerms": counts.thesaurus_terms,
            "apiTopics": counts.api_topics,
            "thesaurusUnmatched": counts.thesaurus_unmatched,
            "apiTopicUnmatched": counts.api_topic_unmatched,
            "caseFoldedOnly": counts.case_folded_only,
        },
    )


FR_THESAURUS_API_TOPIC_RULE = DerivationRule(
    rule_iri=FR_THESAURUS_API_TOPIC_RULE_IRI,
    engine_iri=FR_THESAURUS_API_TOPIC_ENGINE_IRI,
    engine_version=FR_THESAURUS_API_TOPIC_ENGINE_VERSION,
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
    # second argument, exactly as the compound-heading rule's do: the shared
    # AssertedFactView carries no labels, and nothing dispatches these
    # through the rule object generically.
    evidence_nodes=fr_thesaurus_api_topic_evidence_nodes,
    derive=derive_fr_thesaurus_api_topic_rows,
    label="Federal Register thesaurus-to-API-topic label-equality closeMatch",
)


def _escape_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_fr_alignment_asserted_nquads_lines(
    thesaurus_release: object,
    topics_release: object,
) -> tuple[str, ...]:
    """Project the two Federal Register releases into the facts this rule reads.

    Emits scheme membership, semantic ring, one synthetic ``SourceRecord``
    per resource, and SKOS-XL label nodes for every preferred and alternate
    label. Alternates are included on purpose: the rule must keep deriving
    exactly its 698 preferred-label edges over a graph that also carries the
    thesaurus's 433 alternates, and must never match on one. Label-node IRIs
    are synthetic content-derived digests -- stable and unique per label,
    which is all evidence citation and joining need.
    """

    graph_id = "<urn:ref:atlas:graph:v3:asserted>"
    lines: list[str] = []
    for release, expected_scheme in (
        (thesaurus_release, FR_THESAURUS_SCHEME_IRI),
        (topics_release, FR_API_TOPICS_SCHEME_IRI),
    ):
        scheme_iri = release.scheme_iri  # type: ignore[attr-defined]
        if scheme_iri != expected_scheme:
            raise FrThesaurusApiTopicDerivationError(
                f"release is not the expected Federal Register scheme: {scheme_iri}"
            )
        if release.ring != "subject":  # type: ignore[attr-defined]
            raise FrThesaurusApiTopicDerivationError(
                f"release is not in the subject ring: {release.ring}"  # type: ignore[attr-defined]
            )
        for resource in release.resources:  # type: ignore[attr-defined]
            iri = resource.iri  # type: ignore[attr-defined]
            subject = f"<{iri}>"
            slug = iri.rsplit(":", 1)[-1]
            record = f"<urn:ref:atlas-source-record:fr-alignment-fixture:{slug}>"
            lines.append(f"{subject} {ATLAS_IN_SCHEME_TERM} <{scheme_iri}> {graph_id} .")
            lines.append(f"{subject} {ATLAS_SEMANTIC_RING_TERM} <{ATLAS_SUBJECT_RING}> {graph_id} .")
            for label_row in resource.labels:  # type: ignore[attr-defined]
                role = label_row.role  # type: ignore[attr-defined]
                value = label_row.value  # type: ignore[attr-defined]
                digest = hashlib.sha256(f"{iri}|{role}|{value}".encode()).hexdigest()[:32]
                label = f"<urn:ref:atlas-label:fr-alignment-fixture:{digest}>"
                role_term = SKOSXL_PREF_LABEL_TERM if role == "preferred" else SKOSXL_ALT_LABEL_TERM
                lines.append(f"{subject} {role_term} {label} {graph_id} .")
                lines.append(
                    f'{label} {SKOSXL_LITERAL_FORM_TERM} "{_escape_literal(value)}"@en {graph_id} .'
                )
            lines.append(f"{record} {ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {graph_id} .")
    return tuple(lines)

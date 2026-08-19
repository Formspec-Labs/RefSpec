"""Derived ``skos:broader`` edges from EuroVoc microthesaurus notations to domains.

REF-045 (docs/decisions.md) found that the Publications Office never asserts
the link between a EuroVoc microthesaurus and the domain it sits under
anywhere in the pinned SKOS Core distribution: the complete predicate
inventory on the 127 microthesauri is ``rdf:type``, ``skos:notation``, and
labels only, ``euvoc:domain`` appears nowhere in the graph, and nothing
points at the 21 domain concepts at all. The only linkage that exists is
notational: every microthesaurus's four-digit publisher notation carries a
two-digit prefix naming exactly one of the 21 domain codes. Reading that
prefix as the microthesaurus's domain is a structural projection of the
publisher's own numbering convention, not an invention -- but it is still
RefSpec's act, not the Publications Office's assertion of ``skos:broader``,
so under REF-035 tier E5 it belongs only in the derived graph, admitted
per-rule by the binding's rule registry (REF-042 in ``docs/decisions.md``).
REF-046 registers this module as the registry's fifth entry and promotes
the 127 microthesauri and their 7,902 concept memberships into a real
Atlas release alongside it.

**The measured trap this rule refuses to repeat.** EuroVoc *concept*
notations are opaque sequential ids, not hierarchical codes: ``1`` is "Arhus
(county)", ``10`` is "domestic trade", ``100`` is "racial conflict". Applying
a two-digit prefix rule at the concept level produces 1,730 confident
nonsense claims out of 7,506 (REF-045). The prefix relationship is real only
between a microthesaurus's own four-digit notation and a domain's two-digit
code -- this rule reads notations from resources in exactly those two
schemes and no others, never from bare notation shape alone.

**Cross-scheme, unlike every prior rule.** MeSH tree numbers, GCMD column
nesting, and the Federal Register compound heading all derive an edge
between two resources of the *same* scheme. This rule's subject (a
microthesaurus) and object (a domain) sit in two different, already-shipped
Atlas schemes (``urn:ref:atlas-resource-scheme:eurovoc:microthesauri`` and
``urn:ref:atlas-resource-scheme:eurovoc:domains``), so it is scheme-scoped
in BOTH directions rather than once: a microthesaurus-shaped four-digit
notation on a foreign-scheme resource can never admit an edge, and neither
can a domain-shaped two-digit notation on one. The MeSH rule shipped
scheme-blind and an adversarial battery caught it proving parentage from
notation shape alone; this rule does not repeat that bug.

**Verified against the pinned 4.24 release**
(``sha256:6c362f79ad03e325ba1b4818f1ca3a847bb6167c2a8f7167e2e4df91305b6620``,
the same ``eurovoc_in_skos_core_concepts.rdf`` member ``eurovoc-4.24`` and
``eurovoc-domains-4.24`` are already built from): all 127 microthesauri
resolve their two-digit notation prefix to exactly one of the 21 domains --
zero missing domains, zero ambiguous domains, zero malformed notations.
127 derived edges, one per microthesaurus; this is the identical count and
pair set the ``operator-derived-domain-candidates.jsonl`` sidecar layer
(``refspec.registry.eurovoc_organization_experiment``,
``generationMethod: microthesaurusNotationTwoDigitPrefix``) already carried
as a non-authoritative candidate.

This module works over the shared :mod:`refspec.atlas.derived_graph`
machinery and mints its rows through :func:`build_derived_row`, so row
identity and input digests match the binding's formulas exactly.
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

EUROVOC_MICROTHESAURI_SCHEME_IRI = "urn:ref:atlas-resource-scheme:eurovoc:microthesauri"
EUROVOC_DOMAINS_SCHEME_IRI = "urn:ref:atlas-resource-scheme:eurovoc:domains"

EUROVOC_MICROTHESAURUS_DOMAIN_RULE_IRI = "urn:ref:rule:eurovoc-microthesaurus-domain-notation-prefix"
EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_IRI = "https://refspec.org/code/atlas-v3-derived-eurovoc-microthesaurus-domain"
EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_VERSION = "1"

# Frozen against the pinned 4.24 release (sha256:6c362f79...5b6620, 127
# notated microthesaurus schemes, 21 domains).
EUROVOC_4_24_MICROTHESAURUS_COUNT = 127
EUROVOC_4_24_DOMAIN_COUNT = 21
EUROVOC_4_24_DERIVED_EDGE_COUNT = 127
EUROVOC_4_24_MISSING_DOMAIN_COUNT = 0
EUROVOC_4_24_AMBIGUOUS_DOMAIN_COUNT = 0
EUROVOC_4_24_MALFORMED_NOTATION_COUNT = 0


class EuroVocMicrothesaurusDomainDerivationError(ValueError):
    """A microthesaurus-domain derivation premise the rule refuses to guess past."""


@dataclass(frozen=True, slots=True)
class EuroVocMicrothesaurusDomainCounts:
    """The reconciling counters the real-data test pins exactly."""

    microthesauri: int
    edges: int
    missing_domain: int
    ambiguous_domain: int
    malformed_notation: int


def domain_prefix(microthesaurus_notation: str) -> str | None:
    """The two-digit domain code a four-digit microthesaurus notation names.

    ``None`` for anything that is not a well-formed four-digit numeric
    notation -- a shape this rule refuses to guess past rather than truncate.
    """

    if len(microthesaurus_notation) != 4 or not microthesaurus_notation.isdigit():
        return None
    return microthesaurus_notation[:2]


def resolve_microthesaurus_domain_edges(
    microthesaurus_notations_by_resource: Mapping[str, Iterable[str]],
    domain_notation_by_resource: Mapping[str, str],
) -> tuple[tuple[tuple[str, str], ...], EuroVocMicrothesaurusDomainCounts]:
    """Resolve every microthesaurus notation to its domain resource, or count why not.

    The one algorithm both the asserted-fact-view path
    (:func:`_resolve_edge_pairs`, reading a real spooled N-Quads pass) and
    the producer's prebuild count (reading in-memory release resources
    before any spool exists) delegate to, so the row count the prebuild
    receipt commits to and the row set the streamed build emits can never
    independently drift.

    Never guesses an owner for an ambiguous two-digit domain code (two
    domain resources sharing one notation), and never truncates a
    malformed microthesaurus notation into a prefix -- both are counted,
    not silently dropped.
    """

    domain_owners: dict[str, set[str]] = {}
    for resource, notation in domain_notation_by_resource.items():
        domain_owners.setdefault(notation, set()).add(resource)

    pairs: set[tuple[str, str]] = set()
    missing_domain = 0
    ambiguous_domain = 0
    malformed_notation = 0
    considered = 0
    for resource, notations in microthesaurus_notations_by_resource.items():
        considered += 1
        prefixes = {prefix for notation in notations if (prefix := domain_prefix(notation)) is not None}
        if not prefixes:
            malformed_notation += 1
            continue
        for prefix in prefixes:
            owners = domain_owners.get(prefix)
            if not owners:
                missing_domain += 1
                continue
            if len(owners) > 1:
                ambiguous_domain += 1
                continue
            (domain,) = owners
            if domain == resource:
                raise EuroVocMicrothesaurusDomainDerivationError(
                    f"microthesaurus notation prefix {prefix!r} on {resource} resolves its own domain to itself"
                )
            pairs.add((resource, domain))

    counts = EuroVocMicrothesaurusDomainCounts(
        microthesauri=considered,
        edges=len(pairs),
        missing_domain=missing_domain,
        ambiguous_domain=ambiguous_domain,
        malformed_notation=malformed_notation,
    )
    return tuple(sorted(pairs)), counts


def _microthesaurus_notations(facts: AssertedFactView) -> dict[str, tuple[str, ...]]:
    # The release node itself also carries `atlas:inScheme` pointing at this
    # same scheme (every `AtlasRelease` does) but represents nothing -- "in
    # scheme AND represented by a SourceRecord", not "in scheme" alone, is
    # what makes a resource a microthesaurus here, the same definition the
    # GCMD column-nesting rule uses for "keyword".
    return {
        resource: tuple(facts.notations.get(resource, ()))
        for resource, scheme in facts.schemes.items()
        if scheme == EUROVOC_MICROTHESAURI_SCHEME_IRI and resource in facts.records
    }


def _domain_notations(facts: AssertedFactView) -> dict[str, str]:
    result: dict[str, str] = {}
    for resource, scheme in facts.schemes.items():
        if scheme != EUROVOC_DOMAINS_SCHEME_IRI or resource not in facts.records:
            continue
        notations = facts.notations.get(resource, ())
        if len(notations) != 1:
            raise EuroVocMicrothesaurusDomainDerivationError(
                f"EuroVoc domain {resource} does not carry exactly one notation"
            )
        (result[resource],) = notations
    return result


def _resolve_edge_pairs(
    facts: AssertedFactView,
) -> tuple[tuple[tuple[str, str], ...], EuroVocMicrothesaurusDomainCounts]:
    """Resolve every EuroVoc microthesaurus notation to its domain, or count why not."""

    return resolve_microthesaurus_domain_edges(_microthesaurus_notations(facts), _domain_notations(facts))


def resolve_eurovoc_microthesaurus_domain_edges(
    facts: AssertedFactView,
) -> tuple[tuple[tuple[str, str], ...], EuroVocMicrothesaurusDomainCounts]:
    """Public entry point: the pure microthesaurus/domain pair resolution plus counts."""

    return _resolve_edge_pairs(facts)


def eurovoc_microthesaurus_domain_evidence_nodes(facts: AssertedFactView) -> frozenset[str]:
    """The source-record IRIs :func:`derive_eurovoc_microthesaurus_domain_rows` cites."""

    pairs, _counts = _resolve_edge_pairs(facts)
    resources: set[str] = set()
    for microthesaurus, domain in pairs:
        resources.add(microthesaurus)
        resources.add(domain)
    missing_records = [resource for resource in resources if resource not in facts.records]
    if missing_records:
        raise EuroVocMicrothesaurusDomainDerivationError(
            f"EuroVoc resource {missing_records[0]} has no source record to cite as derivation evidence"
        )
    return frozenset(facts.records[resource] for resource in resources)


def derive_eurovoc_microthesaurus_domain_rows(
    context: DerivationContext,
    *,
    asserted_relations: frozenset[tuple[str, str, str]] = frozenset(),
) -> DerivedRuleOutcome:
    """Derive every EuroVoc microthesaurus-domain ``skos:broader`` row from asserted facts.

    ``asserted_relations`` carries already-asserted (subject IRI, predicate
    IRI, object IRI) triples; a derived edge that would duplicate one -- or
    its ``skos:narrower`` inverse -- is refused, never silently dropped.
    Neither ``eurovoc-domains-4.24`` nor the EuroVoc microthesauri release
    asserts a ``skos:broader``/``skos:narrower`` relation today, so this is
    exercised by a synthetic collision in the tests, not by real data.
    """

    facts = context.facts
    pairs, counts = _resolve_edge_pairs(facts)
    rows: list[DerivedRelationRow] = []
    for microthesaurus, domain in pairs:
        microthesaurus_ring = facts.rings.get(microthesaurus)
        domain_ring = facts.rings.get(domain)
        if microthesaurus_ring != ATLAS_SUBJECT_RING or domain_ring != ATLAS_SUBJECT_RING:
            raise EuroVocMicrothesaurusDomainDerivationError(
                f"EuroVoc microthesaurus-domain edge endpoint is not in the subject ring: {microthesaurus} -> {domain}"
            )
        if (microthesaurus, SKOS_BROADER, domain) in asserted_relations or (
            domain,
            SKOS_NARROWER,
            microthesaurus,
        ) in asserted_relations:
            raise EuroVocMicrothesaurusDomainDerivationError(
                f"derived edge {microthesaurus} -> {domain} duplicates an asserted relation (or its narrower inverse)"
            )
        microthesaurus_record = facts.records.get(microthesaurus)
        domain_record = facts.records.get(domain)
        if microthesaurus_record is None or domain_record is None:
            raise EuroVocMicrothesaurusDomainDerivationError(
                f"EuroVoc resource has no source record for derived edge {microthesaurus} -> {domain}"
            )
        rows.append(
            build_derived_row(
                rule=EUROVOC_MICROTHESAURUS_DOMAIN_RULE,
                subject=microthesaurus,
                predicate=SKOS_BROADER,
                obj=domain,
                ring=ATLAS_SUBJECT_RING,
                evidence=(microthesaurus_record, domain_record),
                context=context,
            )
        )
    rows.sort(key=lambda row: row.node_iri)
    return DerivedRuleOutcome(
        rows=tuple(rows),
        counts={
            "edges": counts.edges,
            "microthesauri": counts.microthesauri,
            "missingDomain": counts.missing_domain,
            "ambiguousDomain": counts.ambiguous_domain,
            "malformedNotation": counts.malformed_notation,
        },
    )


EUROVOC_MICROTHESAURUS_DOMAIN_RULE = DerivationRule(
    rule_iri=EUROVOC_MICROTHESAURUS_DOMAIN_RULE_IRI,
    engine_iri=EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_IRI,
    engine_version=EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_VERSION,
    evidence_input_kind=EVIDENCE_INPUT_SOURCE_RECORD,
    watch_predicates=frozenset(
        {
            ATLAS_NOTATION_TERM,
            ATLAS_IN_SCHEME_TERM,
            ATLAS_REPRESENTS_RESOURCE_TERM,
            ATLAS_SEMANTIC_RING_TERM,
        }
    ),
    evidence_nodes=eurovoc_microthesaurus_domain_evidence_nodes,
    derive=derive_eurovoc_microthesaurus_domain_rows,
    label="EuroVoc microthesaurus-domain notation-prefix broader",
)


def build_eurovoc_microthesaurus_domain_asserted_nquads_lines(
    microthesaurus_release: object,
    domain_release: object,
) -> tuple[str, ...]:
    """Project one microthesauri release and one domains release into the facts this rule reads.

    Emits the four watched predicates per resource -- notation, scheme
    membership, semantic ring, and one synthetic ``SourceRecord`` -- for
    both the microthesaurus and domain sides, using the same shapes a real
    asserted spool carries.
    """

    graph_id = "<urn:ref:atlas:graph:v3:asserted>"
    lines: list[str] = []
    for release, scheme_iri, fixture_kind in (
        (microthesaurus_release, EUROVOC_MICROTHESAURI_SCHEME_IRI, "microthesaurus"),
        (domain_release, EUROVOC_DOMAINS_SCHEME_IRI, "domain"),
    ):
        for resource in release.resources:  # type: ignore[attr-defined]
            subject = f"<{resource.iri}>"  # type: ignore[attr-defined]
            record = f"<urn:ref:atlas-source-record:eurovoc-{fixture_kind}-fixture:{resource.iri}>"
            for notation in resource.notations:  # type: ignore[attr-defined]
                escaped = notation.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{subject} {ATLAS_NOTATION_TERM} "{escaped}" {graph_id} .')
            lines.append(f"{subject} {ATLAS_IN_SCHEME_TERM} <{scheme_iri}> {graph_id} .")
            lines.append(f"{subject} {ATLAS_SEMANTIC_RING_TERM} <{ATLAS_SUBJECT_RING}> {graph_id} .")
            lines.append(f"{record} {ATLAS_REPRESENTS_RESOURCE_TERM} {subject} {graph_id} .")
    return tuple(lines)


def main() -> None:
    """Print the derived row set over the real pinned EuroVoc 4.24 release."""

    import hashlib
    import json

    from refspec.atlas.derived_graph import collect_asserted_fact_view, collect_node_digests
    from refspec.atlas.v3_registry_vocabularies import (
        load_eurovoc_4_24_releases,
        load_eurovoc_microthesauri_4_24_release,
    )

    def canonical_sha256(payload: object, *, terminal_lf: bool = True) -> str:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if terminal_lf:
            text += "\n"
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    _concepts, domains = load_eurovoc_4_24_releases()
    microthesauri = load_eurovoc_microthesauri_4_24_release()
    lines = build_eurovoc_microthesaurus_domain_asserted_nquads_lines(microthesauri, domains)
    facts = collect_asserted_fact_view(lines)
    wanted = eurovoc_microthesaurus_domain_evidence_nodes(facts)
    node_digest = collect_node_digests(lines, wanted)
    context = DerivationContext(
        facts=facts,
        node_digest=node_digest,
        canonical_sha256=canonical_sha256,
        generated_at="2026-01-01T00:00:00+00:00",
    )
    outcome = derive_eurovoc_microthesaurus_domain_rows(context)
    print(f"microthesauri={len(microthesauri.resources)} domains={len(domains.resources)} lines={len(lines)}")
    print(f"counts={outcome.counts}")
    print(f"edges={len(outcome.rows)}")
    print(f"sample row={outcome.rows[0]}")


if __name__ == "__main__":
    main()


__all__ = [
    "ATLAS_SUBJECT_RING",
    "EUROVOC_4_24_AMBIGUOUS_DOMAIN_COUNT",
    "EUROVOC_4_24_DERIVED_EDGE_COUNT",
    "EUROVOC_4_24_DOMAIN_COUNT",
    "EUROVOC_4_24_MALFORMED_NOTATION_COUNT",
    "EUROVOC_4_24_MICROTHESAURUS_COUNT",
    "EUROVOC_4_24_MISSING_DOMAIN_COUNT",
    "EUROVOC_DOMAINS_SCHEME_IRI",
    "EUROVOC_MICROTHESAURI_SCHEME_IRI",
    "EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_IRI",
    "EUROVOC_MICROTHESAURUS_DOMAIN_ENGINE_VERSION",
    "EUROVOC_MICROTHESAURUS_DOMAIN_RULE",
    "EUROVOC_MICROTHESAURUS_DOMAIN_RULE_IRI",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "EuroVocMicrothesaurusDomainCounts",
    "EuroVocMicrothesaurusDomainDerivationError",
    "build_eurovoc_microthesaurus_domain_asserted_nquads_lines",
    "derive_eurovoc_microthesaurus_domain_rows",
    "domain_prefix",
    "eurovoc_microthesaurus_domain_evidence_nodes",
    "resolve_eurovoc_microthesaurus_domain_edges",
    "resolve_microthesaurus_domain_edges",
]

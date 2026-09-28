"""Frozen pre-simplification fact index for equivalence tests only."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rdflib import Graph, URIRef
from rdflib.namespace import RDF
from validate import ATLAS, PROV, RKAF, SKOSXL, _fail, _one

_INDEXED_ASSERTED_TYPES = frozenset({ATLAS.RelationAssertion, ATLAS.SkosMappingAssertion})

# Every asserted predicate whose objects a bucket-2 semantic gate reads back
# per carrier node, and nothing else. `_AssertedFacts` keeps exactly these as
# the packs are parsed, so the gates read a prepared index instead of asking
# the 29M-quad store one subject at a time. Adding a predicate here costs one
# retained reference per occurrence in the asserted graph, so the list is the
# read set, not the vocabulary: `atlas:nativePayload`, `atlas:notation` and the
# other bulk literals are deliberately absent because no folded gate reads them
# through this index. A gate asking for a predicate that is NOT here raises
# rather than silently answering from the store, so the list cannot drift out
# from under a check without failing loudly.
#
# Machine-adjudication records are structurally absent from the staging
# distribution. Keeping their complete read set separate makes that zero and
# its memory consequence measurable without weakening the shared allowlist.
_MACHINE_ADJUDICATION_INDEXED_PREDICATES = frozenset(
    {
        RKAF.hasArtifactIdentifier,
        RKAF.hasContentDigest,
        RKAF.proofRecordDigest,
        RKAF.proofIssuer,
        RKAF.hasAILineage,
        RKAF.proofComparisonContext,
        RKAF.proofEvaluatedAt,
        RKAF.adjudicationVerdict,
        RKAF.proofOutcome,
        RKAF.proofSnapshot,
        RKAF.sealedRequestDigest,
        RKAF.inputContextHash,
        RKAF.independenceGroup,
        RKAF.proofResolver,
        RKAF.modelId,
        RKAF.sealedResponseArtifact,
        RKAF.proofInput,
        RKAF.proofInputDigest,
        RKAF.comparisonExpectedAssertion,
        RKAF.comparisonOutcome,
        RKAF.comparisonSnapshot,
        RKAF.comparisonBaselineArtifact,
        RKAF.comparisonObservedArtifact,
        RKAF.comparisonProofRecord,
    }
)
_INDEXED_ASSERTED_PREDICATES = (
    frozenset(
        {
            RDF.subject,
            RDF.predicate,
            RDF.object,
            PROV.hadMember,
            SKOSXL.prefLabel,
            SKOSXL.altLabel,
            SKOSXL.hiddenLabel,
            SKOSXL.literalForm,
            ATLAS.inRelease,
            ATLAS.inSourceRelease,
            ATLAS.inScheme,
            ATLAS.semanticRing,
            ATLAS.sourceRing,
            ATLAS.targetRing,
            ATLAS.supportedRing,
            ATLAS.resourceProfile,
            ATLAS.sourceRecord,
            ATLAS.representsResource,
            ATLAS.identifierScheme,
            ATLAS.identifierValue,
            ATLAS.identifies,
            ATLAS.sourceRelease,
            ATLAS.targetRelease,
            ATLAS.governedByPolicy,
            ATLAS.assertionIdentityDigest,
            ATLAS.evidenceSourceRecord,
            ATLAS.evidenceSourceDigest,
            ATLAS.contentDigest,
            RKAF.assertedAt,
            RKAF.attestedAt,
            RKAF.attestor,
            RKAF.decision,
            RKAF.assertionOrigin,
            RKAF.epistemicBasis,
            RKAF.evidenceRole,
            RKAF.attestorKind,
            RKAF.evidentiaryFunction,
            RKAF.bindsAssertion,
            RKAF.basedOnAttestation,
            RKAF.supersedesAssertion,
            RKAF.appliesTo,
            RKAF.lifecycleEventKind,
            RKAF.conflictingEntries,
            ATLAS.originalOrganization,
            ATLAS.resultingOrganization,
        }
    )
    | _MACHINE_ADJUDICATION_INDEXED_PREDICATES
)

# `_AssertedFacts` distinguishes "this subject carries no such object" from a
# stored `None`, which no RDF term ever is; a module-level sentinel keeps the
# hot lookup to one `dict.get`.
_FACT_ABSENT: Any = object()
# Above this many objects for one (subject, predicate), `_AssertedFacts.contains`
# builds a set once instead of scanning the list on every call. One release's
# `prov:hadMember` is ~588K objects and every resource asks whether it is in
# there, so the linear scan is the difference between one pass and a quadratic
# one; below the threshold the list scan is cheaper than the set it would build.
_FACT_MEMBERSHIP_THRESHOLD = 8


class _AssertedFacts:
    """The asserted objects the semantic gates read back, indexed while parsing.

    The gates below are per-carrier loops: for every resource, label,
    assertion, evidence binding and source record, ask the store for the same
    handful of predicates. Measured on the 1M-quad staging distribution: 1.4M
    `Graph.triples` calls across four phases costing 5.8s, and the same loops
    at full scale run over 20-60x the carriers. The parser already holds every
    one of those objects as it builds the store, so they ride along into a
    columnar index (`predicate -> subject -> object`) and the gates read that.
    The original four phases then issued 150 store calls and cost 2.5s. After
    construction ownership and machine adjudication joined them, the 67-row
    allowlist retained the same 826,127 staging occurrences: its median parse
    RSS cost was 41 MiB (~1.16 GiB projected at 29M quads), because the 24 new
    machine predicates have no occurrences in that artifact.

    This is the `_AssertedPlacementObservation` pattern, applied to reads
    rather than to placement: nothing here fails, the gates still raise, in the
    same order, with the same codes and messages. Semantics are preserved by
    construction rather than by argument -- the index answers exactly "the
    objects of `predicate` on `subject` in the asserted graph", which is what
    `Graph.objects` answers, and the gates' control flow is untouched.

    Two modes, one API. The parser fills the index; `from_graph` recreates it
    for `validate_preparsed_distribution`, which has resident graphs but no
    parse observer. Bound directly to a graph (`for_graph`), it answers from
    the store for helper calls that have neither observation. `one` in graph
    mode is literally `_one`, so a caller counting `_one` still counts it.

    Duplicate objects are impossible on the indexed path and so are not
    filtered: canonical packs are strictly increasing (`_NQuadsProfileReader`),
    which forbids a repeated quad inside one pack, and `pack.co-location` --
    proved by `observe_subject`, which runs BEFORE this observer on the same
    line -- forbids one subject's outgoing facts from appearing in two packs.
    That is the same invariant `_AssertedNodeDigests` already stands on.
    """

    __slots__ = ("_graph", "_membership", "_reorder", "_rows", "_types", "graph_id")

    def __init__(
        self,
        graph_id: URIRef,
        *,
        graph: Graph | None = None,
        from_walk: bool = False,
    ) -> None:
        self.graph_id = graph_id
        self._graph = graph
        # Filled only when the index is built by walking a finished store: that
        # walk yields a context's triples in set order, so a subject carrying
        # two objects for one predicate can arrive in an order `Graph.objects`
        # would never produce -- and two folded gates iterate those objects and
        # raise on the first offender. Single-valued rows cannot disagree, so
        # only the transitions are remembered and only they are re-read.
        self._reorder: list[tuple[URIRef, URIRef]] | None = [] if from_walk else None
        self._rows: dict[URIRef, dict[URIRef, Any]] | None = (
            None if graph is not None else {predicate: {} for predicate in _INDEXED_ASSERTED_PREDICATES}
        )
        self._types: dict[URIRef, set[URIRef]] | None = (
            None if graph is not None else {asserted_type: set() for asserted_type in _INDEXED_ASSERTED_TYPES}
        )
        self._membership: dict[tuple[URIRef, URIRef], frozenset[Any]] = {}

    @classmethod
    def for_graph(cls, asserted: Graph) -> _AssertedFacts:
        """Answer from an already-parsed graph, for callers that did not parse here."""

        return cls(asserted.identifier, graph=asserted)

    @property
    def indexed(self) -> bool:
        return self._rows is not None

    def observe(self, subject: URIRef, predicate: URIRef, obj: Any) -> None:
        """Record one asserted quad's object, if any gate reads that predicate.

        One `dict.get` for every quad in the asserted graph, and nothing else
        for the ~30% of them no gate reads back. Only reachable on an indexed
        instance: a graph-backed one has nothing to observe.
        """

        rows = self._rows
        if rows is None:
            return
        row = rows.get(predicate)
        if row is None:
            if predicate == RDF.type:
                subjects = self._types.get(obj)  # type: ignore[union-attr]
                if subjects is not None:
                    subjects.add(subject)
            return
        existing = row.get(subject, _FACT_ABSENT)
        if existing is _FACT_ABSENT:
            row[subject] = obj
        elif type(existing) is list:
            existing.append(obj)
        else:
            row[subject] = [existing, obj]
            if self._reorder is not None:
                self._reorder.append((predicate, subject))

    def align_to_graph(self, asserted: Graph) -> None:
        """Put the multi-valued rows a store walk filled back in the store's order."""

        if not self._reorder:
            return
        for predicate, subject in self._reorder:
            self._rows[predicate][subject] = list(  # type: ignore[index]
                asserted.objects(subject, predicate)
            )
        self._reorder.clear()

    def _row(self, predicate: URIRef) -> dict[URIRef, Any]:
        row = self._rows.get(predicate)  # type: ignore[union-attr]
        if row is None:
            raise AssertionError(f"{predicate} is not an indexed asserted predicate")
        return row

    def objects(self, subject: URIRef, predicate: URIRef) -> tuple[Any, ...]:
        """Every object of `predicate` on `subject`, in the graph's own order."""

        if self._rows is None:
            return tuple(self._graph.objects(subject, predicate))  # type: ignore[union-attr]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            return ()
        if type(value) is list:
            return tuple(value)
        return (value,)

    def one(self, subject: URIRef, predicate: URIRef, *, code: str) -> Any:
        """`_one`, answered from the index; identical refusal either way."""

        if self._rows is None:
            return _one(self._graph, subject, predicate, code=code)  # type: ignore[arg-type]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            _fail(code, f"{subject} must have exactly one {predicate}; found 0")
        if type(value) is list:
            _fail(code, f"{subject} must have exactly one {predicate}; found {len(value)}")
        return value

    def value(self, subject: URIRef, predicate: URIRef) -> Any:
        """`Graph.value`: the first object, or None when there is none."""

        if self._rows is None:
            return self._graph.value(subject, predicate)  # type: ignore[union-attr]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            return None
        if type(value) is list:
            return value[0]
        return value

    def contains(self, subject: URIRef, predicate: URIRef, obj: Any) -> bool:
        """Whether the asserted graph carries this exact triple."""

        if self._rows is None:
            return (subject, predicate, obj) in self._graph  # type: ignore[operator]
        value = self._row(predicate).get(subject, _FACT_ABSENT)
        if value is _FACT_ABSENT:
            return False
        if type(value) is not list:
            return bool(value == obj)
        if len(value) < _FACT_MEMBERSHIP_THRESHOLD:
            return obj in value
        key = (subject, predicate)
        members = self._membership.get(key)
        if members is None:
            members = self._membership[key] = frozenset(value)
        return obj in members

    def subject_objects(self, predicate: URIRef) -> Iterable[tuple[URIRef, Any]]:
        """Every (subject, object) pair for one predicate across the asserted graph."""

        if self._rows is None:
            yield from self._graph.subject_objects(predicate)  # type: ignore[union-attr]
            return
        for subject, value in self._row(predicate).items():
            if type(value) is list:
                for obj in value:
                    yield subject, obj
            else:
                yield subject, value

    def has_type(self, subject: URIRef, asserted_type: URIRef) -> bool:
        """Whether `subject` declares one of the indexed abstract carrier types."""

        if self._types is None:
            return (subject, RDF.type, asserted_type) in self._graph  # type: ignore[operator]
        subjects = self._types.get(asserted_type)
        if subjects is None:
            raise AssertionError(f"{asserted_type} is not an indexed asserted type")
        return subject in subjects

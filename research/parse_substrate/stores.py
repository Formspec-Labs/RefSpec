"""Research-only rdflib stores and query instrumentation.

These stores are prototypes, not part of the Atlas binding.  They implement
the small, ordinary ``Store`` surface exercised by the validator and
pySHACL so the representation can be measured without changing either
consumer.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import Any

from rdflib import Graph, URIRef
from rdflib.plugins.stores.memory import Memory
from rdflib.store import Store

Triple = tuple[Any, Any, Any]
Pattern = tuple[Any | None, Any | None, Any | None]


def pattern_name(pattern: Pattern) -> str:
    """Return a stable S/P/O-bound mask for a triple pattern."""

    return "".join(letter if value is not None else "_" for letter, value in zip("SPO", pattern))


class QueryStatsMixin:
    """Count store calls and yielded triples by bound-position pattern."""

    query_calls: Counter[str]
    query_rows: Counter[str]

    def _init_query_stats(self) -> None:
        self.query_calls = Counter()
        self.query_rows = Counter()

    def triples(self, triple_pattern: Pattern, context: Graph | None = None):
        name = pattern_name(triple_pattern)
        self.query_calls[name] += 1
        for row in super().triples(triple_pattern, context=context):
            self.query_rows[name] += 1
            yield row

    def query_stats(self) -> dict[str, dict[str, int]]:
        names = sorted(self.query_calls.keys() | self.query_rows.keys())
        return {
            name: {
                "calls": self.query_calls[name],
                "rows": self.query_rows[name],
            }
            for name in names
        }


class ProfiledMemory(QueryStatsMixin, Memory):
    """The stock rdflib Memory store with read-pattern counters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._init_query_stats()


@dataclass(slots=True)
class _ContextIndex:
    """Two indexes for one graph context.

    ``spo`` serves subject-led reads. ``pos`` serves reverse and type-led
    reads.  The stock Memory store also keeps an object-led OSP index, a set
    of complete triples per context, and per-triple context metadata.
    """

    graph: Graph
    spo: dict[Any, dict[Any, set[Any]]] = field(default_factory=dict)
    pos: dict[Any, dict[Any, set[Any]]] = field(default_factory=dict)
    size: int = 0


class TwoIndexStore(Store):
    """A graph-aware in-memory store with only SPO and POS indexes.

    Atlas queries named graphs directly and stores each quad in one graph
    role.  This prototype therefore keeps separate indexes by graph and
    derives full iteration from SPO instead of retaining complete triples in
    additional context sets.  Object-only patterns fall back to an SPO scan;
    the benchmark call trace determines whether that trade is sound.
    """

    context_aware = True
    formula_aware = False
    graph_aware = True

    def __init__(self, configuration: str | None = None, identifier: Any = None) -> None:
        super().__init__(configuration)
        self.identifier = identifier
        self._contexts: dict[Any, _ContextIndex] = {}
        self._namespace: dict[str, URIRef] = {}
        self._prefix: dict[URIRef, str] = {}

    @staticmethod
    def _context_id(context: Graph | Any | None) -> Any:
        if context is None:
            return None
        return getattr(context, "identifier", context)

    def _index(self, context: Graph, *, create: bool = False) -> _ContextIndex | None:
        identifier = self._context_id(context)
        index = self._contexts.get(identifier)
        if index is None and create:
            index = _ContextIndex(context)
            self._contexts[identifier] = index
        return index

    def add(self, triple: Triple, context: Graph, quoted: bool = False) -> None:
        if quoted:
            raise ValueError("TwoIndexStore does not support quoted triples")
        super().add(triple, context, quoted=quoted)
        subject, predicate, obj = triple
        index = self._index(context, create=True)
        assert index is not None

        predicates = index.spo.setdefault(subject, {})
        objects = predicates.setdefault(predicate, set())
        if obj in objects:
            return
        objects.add(obj)
        index.pos.setdefault(predicate, {}).setdefault(obj, set()).add(subject)
        index.size += 1

    @staticmethod
    def _context_rows(index: _ContextIndex, pattern: Pattern) -> Generator[Triple, None, None]:
        subject, predicate, obj = pattern
        spo = index.spo
        pos = index.pos

        if subject is not None:
            predicates = spo.get(subject)
            if predicates is None:
                return
            if predicate is not None:
                objects = predicates.get(predicate)
                if objects is None:
                    return
                if obj is not None:
                    if obj in objects:
                        yield subject, predicate, obj
                    return
                for found_object in objects:
                    yield subject, predicate, found_object
                return
            for found_predicate, objects in predicates.items():
                if obj is not None:
                    if obj in objects:
                        yield subject, found_predicate, obj
                else:
                    for found_object in objects:
                        yield subject, found_predicate, found_object
            return

        if predicate is not None:
            objects = pos.get(predicate)
            if objects is None:
                return
            if obj is not None:
                for found_subject in objects.get(obj, ()):
                    yield found_subject, predicate, obj
                return
            for found_object, subjects in objects.items():
                for found_subject in subjects:
                    yield found_subject, predicate, found_object
            return

        if obj is not None:
            # The deliberately omitted OSP index makes this the only scan.
            for found_subject, predicates in spo.items():
                for found_predicate, objects in predicates.items():
                    if obj in objects:
                        yield found_subject, found_predicate, obj
            return

        for found_subject, predicates in spo.items():
            for found_predicate, objects in predicates.items():
                for found_object in objects:
                    yield found_subject, found_predicate, found_object

    @staticmethod
    def _contexts_for(index: _ContextIndex) -> Iterator[Graph]:
        yield index.graph

    def triples(self, triple_pattern: Pattern, context: Graph | None = None):
        if context is not None:
            index = self._index(context)
            if index is None:
                return
            for triple in self._context_rows(index, triple_pattern):
                yield triple, self._contexts_for(index)
            return

        # Store context=None is the non-quoted union. Preserve RDF set
        # semantics if a triple appears in more than one graph.
        seen: set[Triple] = set()
        for index in self._contexts.values():
            for triple in self._context_rows(index, triple_pattern):
                if triple not in seen:
                    seen.add(triple)
                    yield triple, self.contexts(triple)

    def __len__(self, context: Graph | None = None) -> int:
        if context is not None:
            index = self._index(context)
            return 0 if index is None else index.size
        return sum(1 for _triple, _contexts in self.triples((None, None, None)))

    def contexts(self, triple: Triple | None = None):
        if triple is None or triple == (None, None, None):
            return (index.graph for index in self._contexts.values())
        return (
            index.graph
            for index in self._contexts.values()
            if next(self._context_rows(index, triple), None) is not None
        )

    def add_graph(self, graph: Graph) -> None:
        self._index(graph, create=True)

    def remove_graph(self, graph: Graph) -> None:
        self._contexts.pop(self._context_id(graph), None)

    def remove(self, triple_pattern: Pattern, context: Graph | None = None) -> None:
        targets = [self._index(context)] if context is not None else list(self._contexts.values())
        for index in targets:
            if index is None:
                continue
            for subject, predicate, obj in list(self._context_rows(index, triple_pattern)):
                objects = index.spo[subject][predicate]
                objects.remove(obj)
                if not objects:
                    del index.spo[subject][predicate]
                if not index.spo[subject]:
                    del index.spo[subject]
                subjects = index.pos[predicate][obj]
                subjects.remove(subject)
                if not subjects:
                    del index.pos[predicate][obj]
                if not index.pos[predicate]:
                    del index.pos[predicate]
                index.size -= 1

    def bind(self, prefix: str, namespace: URIRef, override: bool = True) -> None:
        old_namespace = self._namespace.get(prefix)
        old_prefix = self._prefix.get(namespace)
        if not override and (old_namespace is not None or old_prefix is not None):
            return
        if old_namespace is not None:
            self._prefix.pop(old_namespace, None)
        if old_prefix is not None:
            self._namespace.pop(old_prefix, None)
        self._namespace[prefix] = namespace
        self._prefix[namespace] = prefix

    def namespace(self, prefix: str) -> URIRef | None:
        return self._namespace.get(prefix)

    def prefix(self, namespace: URIRef) -> str | None:
        return self._prefix.get(namespace)

    def namespaces(self):
        yield from self._namespace.items()


class ProfiledTwoIndexStore(QueryStatsMixin, TwoIndexStore):
    """The two-index prototype with read-pattern counters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._init_query_stats()


class TwoIndexListStore(TwoIndexStore):
    """Two indexes whose leaves are compact lists instead of hash sets.

    Canonical Atlas input is sorted and unique.  The store still checks SPO
    duplicates to preserve Graph set semantics, but POS can append after that
    single check.  Most Atlas SPO leaves contain one value; lists avoid a hash
    table per leaf while retaining ordinary term objects at the Graph API.
    """

    def add(self, triple: Triple, context: Graph, quoted: bool = False) -> None:
        if quoted:
            raise ValueError("TwoIndexListStore does not support quoted triples")
        Store.add(self, triple, context, quoted=quoted)
        subject, predicate, obj = triple
        index = self._index(context, create=True)
        assert index is not None

        predicates = index.spo.setdefault(subject, {})
        objects = predicates.setdefault(predicate, [])
        if obj in objects:
            return
        objects.append(obj)
        index.pos.setdefault(predicate, {}).setdefault(obj, []).append(subject)
        index.size += 1


class ProfiledTwoIndexListStore(QueryStatsMixin, TwoIndexListStore):
    """The list-leaf two-index prototype with read-pattern counters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._init_query_stats()

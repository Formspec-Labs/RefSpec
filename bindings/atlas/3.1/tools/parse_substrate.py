"""Memory-efficient RDF parse substrate for the standalone Atlas binding.

The validator's workload reads named graphs through subject-led and
predicate-led patterns.  ``TwoIndexStore`` therefore keeps SPO and POS indexes
and answers the two object-only patterns with a correct scan instead of an OSP
index.  ``TermPool`` reuses immutable RDF terms within one parsed dataset.

This module stays inside the binding so a copied binding remains independent
of the RefSpec package.
"""

from __future__ import annotations

import sys
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.store import Store

Triple = tuple[Any, Any, Any]
Pattern = tuple[Any | None, Any | None, Any | None]

RDF_STORE_ENV = "REFSPEC_ATLAS_RDF_STORE"
TWO_INDEX_STORE = "two-index"
MEMORY_STORE = "memory"


class _CachedLiteral(Literal):
    """A lexical-form-preserving literal whose immutable hash is cached."""

    __slots__ = ("_refspec_cached_hash",)

    def __new__(
        cls,
        lexical_or_value: Any,
        lang: str | None = None,
        datatype: str | URIRef | None = None,
        normalize: bool | None = None,
    ) -> _CachedLiteral:
        value = super().__new__(
            cls,
            lexical_or_value,
            lang=lang,
            datatype=datatype,
            normalize=normalize,
        )
        value._refspec_cached_hash = Literal.__hash__(value)
        return value

    def __hash__(self) -> int:
        return self._refspec_cached_hash


@dataclass(slots=True)
class TermPool:
    """Reuse URI and literal objects for one dataset parse."""

    iris: dict[str, URIRef] = field(default_factory=dict)
    literals: dict[tuple[str, str | None, URIRef | None], Literal] = field(
        default_factory=dict
    )

    def iri(self, lexical: str) -> URIRef:
        lexical = sys.intern(lexical)
        term = self.iris.get(lexical)
        if term is None:
            term = URIRef(lexical)
            self.iris[lexical] = term
        return term

    def literal(
        self,
        lexical: str,
        *,
        lang: str | None,
        datatype: URIRef | None,
    ) -> Literal:
        lexical = sys.intern(lexical)
        lang = sys.intern(lang) if lang else None
        key = (lexical, lang, datatype)
        term = self.literals.get(key)
        if term is None:
            term = _CachedLiteral(
                lexical,
                lang=lang,
                datatype=datatype,
                normalize=False,
            )
            self.literals[key] = term
        return term


@dataclass(slots=True)
class _ContextIndex:
    """The subject-led and predicate-led indexes for one graph context."""

    graph: Graph
    spo: dict[Any, dict[Any, dict[Any, None]]] = field(default_factory=dict)
    pos: dict[Any, dict[Any, dict[Any, None]]] = field(default_factory=dict)
    size: int = 0


class TwoIndexStore(Store):
    """A graph-aware in-memory RDF store with SPO and POS indexes.

    Object-only patterns remain correct through an SPO scan.  The Atlas 3.1
    validator and its normative SHACL shapes do not use those patterns; the
    focused store tests keep the fallback behavior equal to ``Memory``.
    """

    context_aware = True
    formula_aware = False
    graph_aware = True

    def __init__(
        self,
        configuration: str | None = None,
        identifier: Any = None,
    ) -> None:
        super().__init__(configuration)
        self.identifier = identifier
        self._contexts: dict[Any, _ContextIndex] = {}
        self._namespace: dict[str, URIRef] = {}
        self._prefix: dict[URIRef, str] = {}
        self.object_scan_count = 0

    @staticmethod
    def _context_id(context: Graph | Any | None) -> Any:
        if context is None:
            return None
        return getattr(context, "identifier", context)

    def _index(
        self,
        context: Graph,
        *,
        create: bool = False,
    ) -> _ContextIndex | None:
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

        objects = index.spo.setdefault(subject, {}).setdefault(predicate, {})
        if obj in objects:
            return
        objects[obj] = None
        index.pos.setdefault(predicate, {}).setdefault(obj, {})[subject] = None
        index.size += 1

    def _context_rows(
        self,
        index: _ContextIndex,
        pattern: Pattern,
    ) -> Generator[Triple, None, None]:
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
            self.object_scan_count += 1
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
        super().remove(triple_pattern, context)
        targets = (
            [self._index(context)]
            if context is not None
            else list(self._contexts.values())
        )
        for index in targets:
            if index is None:
                continue
            for subject, predicate, obj in list(
                self._context_rows(index, triple_pattern)
            ):
                objects = index.spo[subject][predicate]
                del objects[obj]
                if not objects:
                    del index.spo[subject][predicate]
                if not index.spo[subject]:
                    del index.spo[subject]
                subjects = index.pos[predicate][obj]
                del subjects[subject]
                if not subjects:
                    del index.pos[predicate][obj]
                if not index.pos[predicate]:
                    del index.pos[predicate]
                index.size -= 1

    def bind(self, prefix: str, namespace: URIRef, override: bool = True) -> None:
        bound_namespace = self._namespace.get(prefix)
        bound_prefix = self._prefix.get(namespace)
        if bound_prefix is None and bound_namespace is not None:
            bound_prefix = self._prefix.get(bound_namespace)
        if override:
            if bound_prefix is not None:
                self._namespace.pop(bound_prefix, None)
            if bound_namespace is not None:
                self._prefix.pop(bound_namespace, None)
            self._prefix[namespace] = prefix
            self._namespace[prefix] = namespace
            return
        selected_namespace = bound_namespace or namespace
        selected_prefix = bound_prefix or prefix
        self._prefix[selected_namespace] = selected_prefix
        self._namespace[selected_prefix] = selected_namespace

    def namespace(self, prefix: str) -> URIRef | None:
        return self._namespace.get(prefix)

    def prefix(self, namespace: URIRef) -> str | None:
        return self._prefix.get(namespace)

    def namespaces(self):
        yield from self._namespace.items()

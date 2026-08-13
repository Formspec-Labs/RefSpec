"""Research-only execution variants for the Atlas residual SHACL floor.

Nothing in this module changes the normative Atlas shapes or the release
validator.  The benchmark imports the current binding validator, builds an
in-memory execution graph, and tests three distinct ideas:

* answer pySHACL's direct object and type reads from facts already observed
  while parsing;
* name the anonymous batched property shapes so ``use_shapes`` and
  ``focus_nodes`` can dispatch one exact target group at a time; and
* replace the four two-step native-relation paths with private direct paths
  whose values are materialized from the original paths.

The mapping helper is an explicit counterfactual.  It computes the truth of
the current two-branch ``sh:xone`` before pySHACL runs.  That is the second
SHACL implementation the previous study warned about, retained here to price
the architectural boundary rather than propose it for production.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

from rdflib import BNode, Graph, URIRef
from rdflib.graph import ReadOnlyGraphAggregate
from rdflib.namespace import RDF, RDFS, SH

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tools" / "validate.py"

RESEARCH = "urn:refspec:research:shacl-floor:"
SEQUENCE_ALIASES: Mapping[tuple[URIRef, URIRef], URIRef] = {
    (
        RDF.subject,
        URIRef("https://refspec.org/ns/atlas/v3#semanticRing"),
    ): URIRef(f"{RESEARCH}subject-semantic-ring"),
    (
        RDF.object,
        URIRef("https://refspec.org/ns/atlas/v3#semanticRing"),
    ): URIRef(f"{RESEARCH}object-semantic-ring"),
    (
        RDF.subject,
        URIRef("https://refspec.org/ns/atlas/v3#inRelease"),
    ): URIRef(f"{RESEARCH}subject-release"),
    (
        RDF.object,
        URIRef("https://refspec.org/ns/atlas/v3#inRelease"),
    ): URIRef(f"{RESEARCH}object-release"),
}
MAPPING_HELPER_PATH = URIRef(f"{RESEARCH}mapping-xone")
MAPPING_HELPER_PASS = URIRef(f"{RESEARCH}pass")
MAPPING_HELPER_NEVER = URIRef(f"{RESEARCH}never")


@dataclass(frozen=True, slots=True)
class Variant:
    """One independently measurable execution change."""

    indexed_view: bool = False
    focus_hints: bool = False
    direct_equals: bool = False
    mapping_or: bool = False
    mapping_helper: bool = False


VARIANTS: Mapping[str, Variant] = {
    "baseline": Variant(),
    "indexed-view": Variant(indexed_view=True),
    "focus-hints": Variant(focus_hints=True),
    "indexed-focus-hints": Variant(indexed_view=True, focus_hints=True),
    "mapping-or": Variant(mapping_or=True),
    "direct-equals": Variant(direct_equals=True),
    "direct-equals-indexed": Variant(direct_equals=True, indexed_view=True),
    "semantic-helper-ceiling": Variant(mapping_helper=True, indexed_view=True),
    "combined-second-implementation": Variant(
        indexed_view=True,
        direct_equals=True,
        mapping_helper=True,
    ),
}


def load_validator(module_name: str = "refspec_atlas_v3_shacl_floor") -> ModuleType:
    """Import the standalone binding validator without importing RefSpec."""

    tools = str(VALIDATOR_PATH.parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location(module_name, VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the Atlas validator from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def invert_asserted_types(
    subject_types: Mapping[Any, Sequence[Any]],
) -> dict[Any, tuple[Any, ...]]:
    """Invert the parse-observed subject/type map once for target lookup."""

    subjects: dict[Any, list[Any]] = defaultdict(list)
    for subject, types in subject_types.items():
        for node_type in types:
            subjects[node_type].append(subject)
    return {node_type: tuple(nodes) for node_type, nodes in subjects.items()}


class IndexedShaclDataView(ReadOnlyGraphAggregate):
    """Data-plus-ontology view whose indexed reads reuse parse-observed facts."""

    def __init__(
        self,
        graphs: list[Graph],
        *,
        asserted: Graph,
        facts: Any,
        type_subjects: Mapping[Any, Sequence[Any]],
        indexed_predicates: frozenset[Any],
    ) -> None:
        super().__init__(graphs)
        self.asserted = asserted
        self.facts = facts
        self.type_subjects = type_subjects
        self.indexed_predicates = indexed_predicates
        self.other_graphs = tuple(graph for graph in graphs if graph is not asserted)
        self.indexed_object_calls = 0
        self.indexed_object_values = 0
        self.indexed_type_calls = 0
        self.indexed_type_values = 0

    def __hash__(self) -> int:
        return hash(self.identifier)

    def __bool__(self) -> bool:
        cached = getattr(self, "_atlas_has_triples", None)
        if cached is None:
            cached = any(next(graph.triples((None, None, None)), None) is not None for graph in self.graphs)
            self._atlas_has_triples = cached
        return cached

    @staticmethod
    def _yield_values(values: Iterable[Any], *, unique: bool) -> Iterator[Any]:
        if not unique:
            yield from values
            return
        seen: set[Any] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                yield value

    def objects(
        self,
        subject: Any = None,
        predicate: Any = None,
        unique: bool = False,
    ) -> Iterator[Any]:
        if subject is not None and not isinstance(subject, list) and predicate in self.indexed_predicates:
            self.indexed_object_calls += 1
            asserted_values = self.facts.objects(subject, predicate)
            self.indexed_object_values += len(asserted_values)
            values = (
                value
                for source in (
                    asserted_values,
                    *(graph.objects(subject, predicate) for graph in self.other_graphs),
                )
                for value in source
            )
            yield from self._yield_values(values, unique=unique)
            return
        yield from super().objects(subject, predicate, unique=unique)

    def subjects(
        self,
        predicate: Any = None,
        object: Any = None,
        unique: bool = False,
    ) -> Iterator[Any]:
        if predicate == RDF.type and object is not None and not isinstance(object, list):
            self.indexed_type_calls += 1
            asserted_subjects = self.type_subjects.get(object, ())
            self.indexed_type_values += len(asserted_subjects)
            values = (
                value
                for source in (
                    asserted_subjects,
                    *(graph.subjects(predicate, object) for graph in self.other_graphs),
                )
                for value in source
            )
            yield from self._yield_values(values, unique=unique)
            return
        yield from super().subjects(predicate, object, unique=unique)

    def with_extra_graph(self, graph: Graph) -> IndexedShaclDataView:
        """Return the same indexed view plus one private research graph."""

        view = IndexedShaclDataView(
            [*self.graphs, graph],
            asserted=self.asserted,
            facts=self.facts,
            type_subjects=self.type_subjects,
            indexed_predicates=self.indexed_predicates,
        )
        for prefix, namespace in self.namespaces():
            view.namespace_manager.bind(prefix, namespace)
        return view


class HelperShaclDataView(ReadOnlyGraphAggregate):
    """Expose private helper predicates without taxing ordinary graph reads."""

    def __init__(
        self,
        base: Graph,
        helpers: Graph,
        helper_predicates: frozenset[URIRef],
    ) -> None:
        super().__init__([base])
        self.base = base
        self.helpers = helpers
        self.helper_predicates = helper_predicates

    def __hash__(self) -> int:
        return hash(self.identifier)

    def __bool__(self) -> bool:
        return bool(self.base)

    def triples(self, triple: Any) -> Iterator[Any]:
        _subject, predicate, _obj = triple
        graph = self.helpers if predicate in self.helper_predicates else self.base
        yield from graph.triples(triple)

    def objects(
        self,
        subject: Any = None,
        predicate: Any = None,
        unique: bool = False,
    ) -> Iterator[Any]:
        graph = self.helpers if predicate in self.helper_predicates else self.base
        yield from graph.objects(subject, predicate, unique=unique)

    def subjects(
        self,
        predicate: Any = None,
        object: Any = None,
        unique: bool = False,
    ) -> Iterator[Any]:
        graph = self.helpers if predicate in self.helper_predicates else self.base
        yield from graph.subjects(predicate, object, unique=unique)

    def subject_objects(
        self,
        predicate: Any = None,
        unique: bool = False,
    ) -> Iterator[tuple[Any, Any]]:
        graph = self.helpers if predicate in self.helper_predicates else self.base
        yield from graph.subject_objects(predicate, unique=unique)


def _copy_graph(graph: Graph) -> Graph:
    copied = Graph(identifier=graph.identifier)
    for prefix, namespace in graph.namespaces():
        copied.bind(prefix, namespace)
    for triple in graph:
        copied.add(triple)
    return copied


def _copy_graph_with_names(graph: Graph, targeted: set[Any]) -> Graph:
    anonymous = sorted((shape for shape in targeted if isinstance(shape, BNode)), key=str)
    names = {
        shape: URIRef(f"{RESEARCH}named-shape-{position}")
        for position, shape in enumerate(anonymous, start=1)
    }
    copied = Graph(identifier=graph.identifier)
    for prefix, namespace in graph.namespaces():
        copied.bind(prefix, namespace)
    for subject, predicate, obj in graph:
        copied.add((names.get(subject, subject), predicate, names.get(obj, obj)))
    return copied


def _targeted_shapes(validate: ModuleType, shapes: Graph) -> set[Any]:
    return {
        shape
        for predicate in validate._SHACL_TARGET_PREDICATES
        for shape in shapes.subjects(predicate, None)
    }


def _replace_plan_shapes(validate: ModuleType, plan: Any, shapes: Graph) -> Any:
    return replace(plan, shapes=shapes)


def _copy_research_attributes(source: Graph, destination: Graph) -> None:
    for attribute in (
        "_research_sequence_aliases",
        "_research_mapping_or",
        "_research_mapping_helper",
        "_research_focus_hints",
    ):
        if hasattr(source, attribute):
            setattr(destination, attribute, getattr(source, attribute))


def _rewrite_native_equals(validate: ModuleType, plan: Any) -> Any:
    execution = _copy_graph(plan.shapes)
    _copy_research_attributes(plan.shapes, execution)
    rewritten: dict[URIRef, tuple[URIRef, URIRef]] = {}
    for property_shape in _targeted_shapes(validate, execution):
        targets_native = (
            property_shape,
            SH.targetClass,
            validate.ATLAS.NativeRelationAssertion,
        ) in execution
        equals = list(execution.objects(property_shape, SH.equals))
        paths = list(execution.objects(property_shape, SH.path))
        if not targets_native or len(equals) != 1 or len(paths) != 1:
            continue
        sequence = tuple(execution.items(paths[0]))
        alias = SEQUENCE_ALIASES.get(sequence)
        if alias is None:
            continue
        execution.remove((property_shape, SH.path, paths[0]))
        execution.add((property_shape, SH.path, alias))
        rewritten[alias] = sequence
    if rewritten != {alias: path for path, alias in SEQUENCE_ALIASES.items()}:
        raise RuntimeError("the four native-relation sequence equals shapes drifted")
    execution._research_sequence_aliases = rewritten
    return _replace_plan_shapes(validate, plan, execution)


def _rewrite_mapping_or(validate: ModuleType, plan: Any) -> Any:
    execution = _copy_graph(plan.shapes)
    _copy_research_attributes(plan.shapes, execution)
    heads = list(execution.objects(validate.ATLAS.MappingAssertionShape, SH.xone))
    if len(heads) != 1:
        raise RuntimeError("MappingAssertionShape does not carry exactly one sh:xone")
    execution.remove((validate.ATLAS.MappingAssertionShape, SH.xone, heads[0]))
    execution.add((validate.ATLAS.MappingAssertionShape, SH["or"], heads[0]))
    execution._research_mapping_or = True
    return _replace_plan_shapes(validate, plan, execution)


def _rewrite_mapping_helper(validate: ModuleType, plan: Any) -> Any:
    execution = _copy_graph(plan.shapes)
    _copy_research_attributes(plan.shapes, execution)
    heads = list(execution.objects(validate.ATLAS.MappingAssertionShape, SH.xone))
    if len(heads) != 1 or len(list(execution.items(heads[0]))) != 2:
        raise RuntimeError("MappingAssertionShape does not carry the expected two-branch sh:xone")
    execution.remove((validate.ATLAS.MappingAssertionShape, SH.xone, heads[0]))

    head = BNode()
    tail = BNode()
    passing_branch = BNode()
    never_branch = BNode()
    passing_property = BNode()
    never_property = BNode()
    execution.add((validate.ATLAS.MappingAssertionShape, SH.xone, head))
    execution.add((head, RDF.first, passing_branch))
    execution.add((head, RDF.rest, tail))
    execution.add((tail, RDF.first, never_branch))
    execution.add((tail, RDF.rest, RDF.nil))
    execution.add((passing_branch, SH.property, passing_property))
    execution.add((passing_property, SH.path, MAPPING_HELPER_PATH))
    execution.add((passing_property, SH.hasValue, MAPPING_HELPER_PASS))
    execution.add((never_branch, SH.property, never_property))
    execution.add((never_property, SH.path, MAPPING_HELPER_PATH))
    execution.add((never_property, SH.hasValue, MAPPING_HELPER_NEVER))
    execution._research_mapping_helper = True
    return _replace_plan_shapes(validate, plan, execution)


def _name_focus_shapes(validate: ModuleType, plan: Any) -> Any:
    targeted = _targeted_shapes(validate, plan.shapes)
    execution = _copy_graph_with_names(plan.shapes, targeted)
    _copy_research_attributes(plan.shapes, execution)
    execution._research_focus_hints = True
    return _replace_plan_shapes(validate, plan, execution)


def make_plan(validate: ModuleType, normative_shapes: Graph, variant: Variant) -> Any:
    """Create one research execution graph from the production batched plan."""

    plan = validate._batched_shacl_plan(normative_shapes)
    if variant.mapping_or:
        plan = _rewrite_mapping_or(validate, plan)
    if variant.mapping_helper:
        plan = _rewrite_mapping_helper(validate, plan)
    if variant.direct_equals:
        plan = _rewrite_native_equals(validate, plan)
    if variant.focus_hints:
        plan = _name_focus_shapes(validate, plan)
    return plan


def _target_class_nodes(data_graph: Graph, target_class: URIRef) -> set[Any]:
    targets = set(data_graph.subjects(RDF.type, target_class))
    for subclass in data_graph.transitive_subjects(RDFS.subClassOf, target_class):
        if subclass != target_class:
            targets.update(data_graph.subjects(RDF.type, subclass))
    return targets


def _path_values(data_graph: Graph, focus: Any, path: Sequence[URIRef]) -> set[Any]:
    values = {focus}
    for predicate in path:
        values = {obj for subject in values for obj in data_graph.objects(subject, predicate)}
    return values


def _new_alias_graph(validate: ModuleType) -> Graph:
    return Graph(store=validate.TwoIndexStore(), identifier=URIRef(f"{RESEARCH}data"))


def _assert_private_paths_absent(data_graph: Graph, predicates: Iterable[URIRef]) -> None:
    for predicate in predicates:
        if next(data_graph.triples((None, predicate, None)), None) is not None:
            raise RuntimeError(f"research helper predicate already exists in input: {predicate}")


def materialize_helpers(
    validate: ModuleType,
    data_graph: Graph,
    execution_shapes: Graph,
) -> tuple[Graph, int]:
    """Materialize only the private values requested by an execution graph."""

    sequence_aliases = getattr(execution_shapes, "_research_sequence_aliases", {})
    mapping_helper = bool(getattr(execution_shapes, "_research_mapping_helper", False))
    if not sequence_aliases and not mapping_helper:
        return data_graph, 0

    helper_predicates = set(sequence_aliases)
    if mapping_helper:
        helper_predicates.add(MAPPING_HELPER_PATH)
    _assert_private_paths_absent(data_graph, helper_predicates)
    aliases = _new_alias_graph(validate)

    if sequence_aliases:
        focuses = _target_class_nodes(data_graph, validate.ATLAS.NativeRelationAssertion)
        for focus in focuses:
            for alias, path in sequence_aliases.items():
                for value in _path_values(data_graph, focus, path):
                    aliases.add((focus, alias, value))

    if mapping_helper:
        temporal_rings = {validate.ATLAS.value, validate.ATLAS.legalIdentity}
        persistent_rings = {validate.ATLAS.subject, validate.ATLAS.entity}
        focuses = _target_class_nodes(data_graph, validate.ATLAS.MappingAssertion)
        for focus in focuses:
            rings = set(data_graph.objects(focus, validate.ATLAS.semanticRing))
            periods = set(data_graph.objects(focus, validate.RKAF.hasEffectivePeriod))
            temporal_branch = all(ring in temporal_rings for ring in rings) and len(periods) == 1
            persistent_branch = all(ring in persistent_rings for ring in rings) and not periods
            if temporal_branch != persistent_branch:
                aliases.add((focus, MAPPING_HELPER_PATH, MAPPING_HELPER_PASS))

    augmented = HelperShaclDataView(
        data_graph,
        aliases,
        frozenset(helper_predicates),
    )
    for prefix, namespace in data_graph.namespaces():
        augmented.namespace_manager.bind(prefix, namespace)
    return augmented, len(aliases)


def _target_groups(validate: ModuleType, shapes: Graph) -> list[tuple[tuple[Any, ...], tuple[URIRef, ...]]]:
    grouped: dict[tuple[Any, ...], list[URIRef]] = defaultdict(list)
    for shape in _targeted_shapes(validate, shapes):
        if not isinstance(shape, URIRef):
            raise RuntimeError("focus-hint execution requires every targeted shape to have an IRI")
        signature = tuple(
            sorted(
                (
                    (predicate, obj)
                    for predicate in validate._SHACL_TARGET_PREDICATES
                    for obj in shapes.objects(shape, predicate)
                ),
                key=lambda row: (str(row[0]), str(row[1])),
            )
        )
        grouped[signature].append(shape)
    return [
        (signature, tuple(sorted(members, key=str)))
        for signature, members in sorted(
            grouped.items(),
            key=lambda row: tuple((str(predicate), str(obj)) for predicate, obj in row[0]),
        )
    ]


def _targets_for_signature(validate: ModuleType, data_graph: Graph, signature: Sequence[tuple[Any, Any]]) -> set[Any]:
    target = BNode()
    target_graph = Graph()
    for predicate, obj in signature:
        target_graph.add((target, predicate, obj))
    return validate._core_shacl_targets(data_graph, target_graph, target)


def focused_validate(
    validate: ModuleType,
    data_graph: Graph,
    shapes: Graph,
) -> tuple[bool, Graph, str, dict[str, Any]]:
    """Validate exact target groups through pySHACL's public focus API."""

    conforms = True
    reports = Graph()
    report_texts: list[str] = []
    focus_seconds = 0.0
    dispatch_seconds = 0.0
    nonempty_groups = 0
    groups = _target_groups(validate, shapes)
    for signature, members in groups:
        started = time.perf_counter()
        focus_nodes = _targets_for_signature(validate, data_graph, signature)
        focus_seconds += time.perf_counter() - started
        if not focus_nodes:
            continue
        nonempty_groups += 1
        started = time.perf_counter()
        group_conforms, group_report, group_text = validate.shacl_validate(
            data_graph,
            shacl_graph=shapes,
            use_shapes=list(members),
            focus_nodes=list(focus_nodes),
            inference="none",
            inplace=True,
            advanced=False,
            abort_on_first=False,
            allow_infos=False,
            allow_warnings=False,
            meta_shacl=False,
        )
        dispatch_seconds += time.perf_counter() - started
        conforms = conforms and bool(group_conforms)
        if isinstance(group_report, Graph):
            for triple in group_report:
                reports.add(triple)
        report_texts.append(str(group_text))
    return (
        conforms,
        reports,
        "\n".join(report_texts),
        {
            "dispatchSeconds": dispatch_seconds,
            "focusHintSeconds": focus_seconds,
            "groupCount": len(groups),
            "nonemptyGroupCount": nonempty_groups,
        },
    )


def install_prototype(validate: ModuleType, variant: Variant) -> None:
    """Patch one fresh validator module for the corpus equivalence harness."""

    original_plan = validate._batched_shacl_plan
    original_validate = validate._validate_shacl_data

    def prototype_plan(shapes: Graph) -> Any:
        plan = original_plan(shapes)
        if variant.mapping_or:
            plan = _rewrite_mapping_or(validate, plan)
        if variant.mapping_helper:
            plan = _rewrite_mapping_helper(validate, plan)
        if variant.direct_equals:
            plan = _rewrite_native_equals(validate, plan)
        if variant.focus_hints:
            plan = _name_focus_shapes(validate, plan)
        return plan

    validate._batched_shacl_plan = prototype_plan

    if variant.indexed_view:

        class FixtureIndexedView(IndexedShaclDataView):
            def __init__(self, graphs: list[Graph]) -> None:
                asserted = graphs[0]
                observation = validate._AssertedPlacementObservation.from_graph(asserted)
                super().__init__(
                    graphs,
                    asserted=asserted,
                    facts=observation.facts,
                    type_subjects=invert_asserted_types(observation.types),
                    indexed_predicates=validate._INDEXED_ASSERTED_PREDICATES,
                )

        validate._ShaclDataView = FixtureIndexedView

    def prototype_validate(data_graph: Graph, shapes: Graph) -> tuple[bool, Any, str]:
        augmented, _helper_count = materialize_helpers(validate, data_graph, shapes)
        if getattr(shapes, "_research_focus_hints", False):
            conforms, report, report_text, _timing = focused_validate(validate, augmented, shapes)
            return conforms, report, report_text
        return original_validate(augmented, shapes)

    validate._validate_shacl_data = prototype_validate

"""Differential proof for the bounded SHACL red-path report, against the whole-graph fallback it replaced.

Until the change REF-072 records ("The red path's bounded fallback"), a red
build whose focused re-run fell short of what the fast path found took the
whole-graph normative report instead. The red path now reports from a sample
of the refused nodes and, when the sample falls short, re-validates every
refused node; neither touches the rest of the graph.

So the whole-graph fallback is reconstructed here as the ORACLE -- a copy of
its engine call and its report reading, not an import, because it is the
thing being replaced -- and `_run_shacl` itself is held to it, over the red
corpus and over a mutation battery that plants, on valid fixtures, a
violation inside each named value shape and each sample shape the old
`use_shapes` run could not take. One `_run_shacl` run per input, on its own
wiring: `_focused_report_is_complete` is spied, answers for the sample, and
is then forced false, so the fallback `_run_shacl` takes is the one compared.

* The sample is complete: the tripwire accepts it, and it names exactly the
  oracle's constraint components, for the role the oracle refuses.
* The fallback reports exactly the oracle's violations, node for node: the
  fast path refused every node the engine refuses, and `_run_shacl` handed
  every one of them on.
* Neither run resolves a target over the graph: the shapes graph a focused
  run is given carries `sh:targetNode` targets and no other, and no run is
  given the normative shapes.

No divergence is deliberate. `DELIBERATE_DIVERGENCES` is where one would be
recorded, with its reason, so that an unlisted divergence fails the suite
instead of becoming a diff nobody reads.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from pyshacl import validate as shacl_validate
from pyshacl.rdfutil import inoculate
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SH, SKOS, XSD

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
RKAF = Namespace("https://rulespec.org/ns/v1#")
ROLES = ("asserted", "derived")
RESOLVED_TARGETS = (SH.targetClass, SH.targetSubjectsOf, SH.targetObjectsOf)

# Input name -> why the bounded report may differ from the oracle there.
DELIBERATE_DIVERGENCES: dict[str, str] = {}

Violation = tuple[str, str, str]


def whole_graph_violations(graph: Graph, ontology: Graph, shapes: Graph) -> set[Violation]:
    """The replaced fallback: the normative engine over the whole role graph, every result read off the report graph."""

    view = atlas_validate._ShaclDataView([graph, inoculate(Graph(), ontology)])
    conforms, report, _ = shacl_validate(
        view,
        shacl_graph=shapes,
        inference="none",
        inplace=True,
        advanced=False,
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
    )
    violations = {
        (
            str(report.value(result, SH.focusNode)),
            str(report.value(result, SH.resultPath) or ""),
            str(report.value(result, SH.sourceConstraintComponent)).rpartition("#")[2],
        )
        for result in report.subjects(RDF.type, SH.ValidationResult)
    }
    assert conforms == (not violations)
    return violations


def assert_bounded_report_is_the_oracles(name: str, graphs: dict[str, Graph], monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold `_run_shacl`'s sample and its own fallback to the whole-graph oracle on one input."""

    ontology, shapes = atlas_validate._parse_binding_graphs()
    oracle: set[Violation] = set()
    refused_role = ""
    for refused_role in ROLES:
        oracle = whole_graph_violations(graphs[refused_role], ontology, shapes)
        if oracle:
            break
    assert oracle, f"{name}: the oracle refuses nothing"
    expected = sorted({component for *_, component in oracle})

    focused: list[set[Violation] | None] = []
    tripwire: list[bool] = []
    in_focused_run = False
    real_focused = atlas_validate._focused_shacl_report
    real_complete = atlas_validate._focused_report_is_complete
    real_validate = atlas_validate._validate_shacl_data

    def spy_focused(data_graph: Graph, shape_graph: Graph, focus_nodes: Any) -> Any:
        nonlocal in_focused_run
        in_focused_run = True
        try:
            result = real_focused(data_graph, shape_graph, focus_nodes)
        finally:
            in_focused_run = False
        focused.append(None if result is None else set(result[1]))
        return result

    def forced_incomplete(rows: Any, batched: Any, misses: Any) -> bool:
        tripwire.append(real_complete(rows, batched, misses))
        return False

    def bounded(data_graph: Graph, shape_graph: Graph) -> tuple[bool, Any, str]:
        assert shape_graph is not shapes, "the red path ran the whole-graph report"
        if in_focused_run:
            assert not any((None, target, None) in shape_graph for target in RESOLVED_TARGETS), (
                "a focused run resolves targets over the graph"
            )
        return real_validate(data_graph, shape_graph)

    with monkeypatch.context() as patch:
        patch.delenv(atlas_validate.VALIDATION_MODE_ENV, raising=False)
        patch.setattr(atlas_validate, "_focused_shacl_report", spy_focused)
        patch.setattr(atlas_validate, "_focused_report_is_complete", forced_incomplete)
        patch.setattr(atlas_validate, "_validate_shacl_data", bounded)
        try:
            atlas_validate._run_shacl(graphs, ontology, shapes)
        except atlas_validate.AtlasValidationError as error:
            match = re.match(r"(\w+) graph does not conform \[([^\]]*)\]", error.detail)
            assert error.code == "shacl.data" and match is not None, error.detail
            refused, components = match.group(1), match.group(2).split(", ")
        else:
            refused, components = "no role", []
    sample, every = [*focused, None, None][:2]
    sample_components = sorted({component for *_, component in sample or ()})

    observed = (refused, len(focused), tripwire, sample_components, every, components)
    diverged = observed != (refused_role, 2, [True], expected, oracle, expected)
    assert diverged == (name in DELIBERATE_DIVERGENCES), (
        f"{name}: refused {refused} {components}, oracle {refused_role} {expected}; {len(focused)} focused runs; "
        f"tripwire {tripwire}; sample {sample_components}; fallback-only {sorted((every or set()) - oracle)}, "
        f"oracle-only {sorted(oracle - (every or set()))}"
    )


def _load_graphs(distribution: Path) -> dict[str, Graph]:
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    _, graphs = atlas_validate._parse_packed_dataset(
        distribution, manifest, atlas_validate._check_pack_manifest(manifest)
    )
    return graphs


def _red_corpus() -> tuple[str, ...]:
    """Every corpus case whose first issue is `shacl.data`, derived from the corpus rather than listed."""

    corpus = json.loads((BINDING_ROOT / "fixtures" / "corpus.json").read_text(encoding="utf-8"))
    return tuple(
        sorted(
            case["id"]
            for case in corpus["cases"]
            if case["expected"] == "invalid" and case["firstIssue"] == "shacl.data"
        )
    )


@pytest.mark.parametrize("case", _red_corpus())
def test_the_bounded_report_is_the_whole_graph_report_on_the_red_corpus(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over real red distributions: the oracle's components from the sample, its violations from the fallback."""

    graphs = _load_graphs(BINDING_ROOT / "fixtures" / "invalid" / case)
    assert_bounded_report_is_the_oracles(case, graphs, monkeypatch)


# --------------------------------------------------------------------------
# The mutation battery: each plants one kind of violation on a valid fixture
# --------------------------------------------------------------------------


def _first(graph: Graph, predicate: URIRef) -> tuple[Any, Any]:
    """The least subject carrying `predicate`, with its value."""

    subject = min(graph.subjects(predicate, None))
    return subject, graph.value(subject, predicate)


def _set(graph: Graph, subject: Any, predicate: URIRef, value: Any) -> None:
    graph.remove((subject, predicate, None))
    graph.add((subject, predicate, value))


def _bad_digest(asserted: Graph) -> None:
    """atlas:DigestValueShape, inlined into the batched plan."""

    record, _ = _first(asserted, ATLAS.sourceDigest)
    _set(asserted, record, ATLAS.sourceDigest, Literal("not-a-digest"))


def _literal_ring(asserted: Graph) -> None:
    """atlas:SemanticRingValueShape, inlined."""

    resource, _ = _first(asserted, ATLAS.resourceProfile)
    _set(asserted, resource, ATLAS.semanticRing, Literal("subject"))


def _literal_profile(asserted: Graph) -> None:
    """atlas:ResourceProfileValueShape, inlined."""

    resource, _ = _first(asserted, ATLAS.resourceProfile)
    _set(asserted, resource, ATLAS.resourceProfile, Literal("concept"))


def _empty_notation(asserted: Graph) -> None:
    """atlas:NonEmptyStringValueShape, inlined."""

    resource, _ = _first(asserted, ATLAS.notation)
    _set(asserted, resource, ATLAS.notation, Literal(""))


def _undated_until(asserted: Graph) -> None:
    """atlas:DateTimeValueShape, inlined."""

    resource, _ = _first(asserted, ATLAS.validUntil)
    _set(asserted, resource, ATLAS.validUntil, Literal("2030-01-01"))


def _french_definition(asserted: Graph) -> None:
    """atlas:EnglishTextLiteralValueShape, which stays a named shape in the batched plan: the nested result's focus is a literal."""

    resource, value = _first(asserted, ATLAS.definition)
    _set(asserted, resource, ATLAS.definition, Literal(str(value), lang="fr"))


def _two_kinds_under_one_signature(asserted: Graph) -> None:
    """Two atlas:definition violations, one sh:node signature, different nested components: both must be sampled."""

    _french_definition(asserted)
    other = next(
        resource
        for resource in sorted(asserted.subjects(ATLAS.resourceProfile, None), reverse=True)
        if (resource, ATLAS.definition, None) not in asserted
    )
    asserted.add((other, ATLAS.definition, Literal("an untagged definition")))


def _literal_concept_scheme(asserted: Graph) -> None:
    """A literal focus node: atlas:ConceptHostingSchemeShape targets the objects of skos:inScheme."""

    concept, _ = _first(asserted, SKOS.inScheme)
    _set(asserted, concept, SKOS.inScheme, Literal("not a scheme"))


def _every_digest_bad(asserted: Graph) -> None:
    """Many identical violations: one sampled node reproduces them, the fallback re-validates them all."""

    for record in sorted(asserted.subjects(ATLAS.sourceDigest, None)):
        _set(asserted, record, ATLAS.sourceDigest, Literal("not-a-digest"))


def _effective_date_signature_collision(asserted: Graph) -> None:
    """One batched signature from two shapes that differ normatively: the sample must take a node of each.

    rkaf:effectiveDate loses its datatype on a change event, which reaches it
    through `sh:node` atlas:DateTimeValueShape (inlined in the batched plan;
    normatively Node plus the nested Datatype), and on a lifecycle event whose
    IRI sorts first, which states `sh:datatype` directly (Datatype alone).
    """

    event = min(asserted.subjects(RDF.type, ATLAS.OrganizationChangeEvent))
    lexical = str(asserted.value(event, RKAF.effectiveDate))
    _set(asserted, event, RKAF.effectiveDate, Literal(lexical, datatype=XSD.string))
    lifecycle = URIRef("urn:ref:atlas-agency-lifecycle:sorts-first")
    assert str(lifecycle) < str(event)
    asserted.add((lifecycle, RDF.type, RKAF.LifecycleEvent))
    asserted.add((lifecycle, RKAF.appliesTo, min(asserted.subjects(RDF.type, ATLAS.MappingAssertion))))
    asserted.add((lifecycle, RKAF.lifecycleEventKind, RKAF.rescission))
    asserted.add((lifecycle, RKAF.effectiveDate, Literal("2026-08-05T12:00:00+00:00", datatype=XSD.string)))


def _owner_binding(asserted: Graph) -> Any:
    event = min(asserted.subjects(RDF.type, ATLAS.OrganizationChangeEvent))
    return min(asserted.subjects(RKAF.bindsAssertion, event))


def _owner_review_origin(asserted: Graph) -> None:
    """atlas:OwnerHumanReviewShape beside the lifted warrant xone the same change breaks: F2's case."""

    _set(asserted, _owner_binding(asserted), RKAF.assertionOrigin, RKAF.aiSuggested)


def _owner_review_attestor(asserted: Graph) -> None:
    """atlas:OwnerHumanReviewShape alone: no warrant axis moves, so no precheck refuses anything."""

    _set(asserted, _owner_binding(asserted), RKAF.attestor, URIRef("urn:ref:reviewer:someone-else"))


def _no_public_record(asserted: Graph) -> None:
    """atlas:PublicRecordEvidenceShape, reached by sh:qualifiedValueShape: no binding of one event cites an https record."""

    event = min(asserted.subjects(RDF.type, ATLAS.OrganizationChangeEvent))
    for binding in list(asserted.subjects(RKAF.bindsAssertion, event)):
        for record in list(asserted.objects(binding, ATLAS.evidenceSourceRecord)):
            locator = asserted.value(record, ATLAS.sourceLocator)
            _set(asserted, record, ATLAS.sourceLocator, URIRef(str(locator).replace("https://", "http://", 1)))


def _named_shape_beside_another_root(asserted: Graph) -> None:
    """A violation inside a named shape beside another root's, the shape F2 first found the gap in."""

    _owner_review_attestor(asserted)
    _undated_until(asserted)


def _every_named_kind_at_once(asserted: Graph) -> None:
    """A violation inside every named shape at once, each at its own top-level node: the sample needs a node per kind."""

    resources = sorted(set(asserted.subjects(ATLAS.inScheme, None)))
    record, _ = _first(asserted, ATLAS.sourceDigest)
    _set(asserted, record, ATLAS.sourceDigest, Literal("not-a-digest"))
    _set(asserted, resources[0], ATLAS.semanticRing, Literal("entity"))
    _set(asserted, resources[1], ATLAS.resourceProfile, Literal("entity"))
    _set(asserted, resources[2], ATLAS.notation, Literal(""))
    _set(asserted, resources[3], ATLAS.validUntil, Literal("2030-01-01"))
    _set(asserted, resources[4], ATLAS.definition, Literal("une définition", lang="fr"))
    first_event, second_event = sorted(asserted.subjects(RDF.type, ATLAS.OrganizationChangeEvent))[:2]
    binding = min(asserted.subjects(RKAF.bindsAssertion, first_event))
    _set(asserted, binding, RKAF.attestor, URIRef("urn:ref:reviewer:someone-else"))
    for event_binding in list(asserted.subjects(RKAF.bindsAssertion, second_event)):
        for source in list(asserted.objects(event_binding, ATLAS.evidenceSourceRecord)):
            locator = asserted.value(source, ATLAS.sourceLocator)
            _set(asserted, source, ATLAS.sourceLocator, URIRef(str(locator).replace("https://", "http://", 1)))


def _three_warrants_broken(asserted: Graph) -> None:
    """One lifted constraint refusing three nodes: the fallback must re-validate every one, not only the least."""

    for binding in sorted(asserted.subjects(RDF.type, RKAF.EvidenceBinding))[:3]:
        _set(asserted, binding, RKAF.evidenceRole, RKAF.retrievalSignal)


def _targeted_through_a_subclass_only(asserted: Graph) -> None:
    """A node atlas:MappingAssertionShape reaches only through rdfs:subClassOf, refused by that shape alone.

    The producer states every supertype, so no fixture needs the subclass
    walk in `_root_shape_focus_groups`; the engine takes it, so a hostile
    distribution can. The SKOS mapping keeps only its subclass type, and its
    source release stops being its subject's release (an sh:equals of
    atlas:MappingAssertionShape).
    """

    mapping = min(asserted.subjects(RDF.type, ATLAS.SkosMappingAssertion))
    asserted.remove((mapping, RDF.type, ATLAS.MappingAssertion))
    releases = sorted(set(asserted.subjects(RDF.type, ATLAS.AtlasRelease)))
    current = asserted.value(mapping, ATLAS.sourceRelease)
    _set(asserted, mapping, ATLAS.sourceRelease, next(release for release in releases if release != current))


VALID = BINDING_ROOT / "fixtures" / "valid"
# Keyed by the named shape each plants a violation inside, where there is one.
MUTATIONS: dict[str, tuple[Path, Callable[[Graph], None]]] = {
    "DigestValueShape": (VALID / "all-resource-profiles", _bad_digest),
    "SemanticRingValueShape": (VALID / "all-resource-profiles", _literal_ring),
    "ResourceProfileValueShape": (VALID / "all-resource-profiles", _literal_profile),
    "NonEmptyStringValueShape": (VALID / "all-resource-profiles", _empty_notation),
    "DateTimeValueShape": (VALID / "all-resource-profiles", _undated_until),
    "EnglishTextLiteralValueShape": (VALID / "all-resource-profiles", _french_definition),
    "OwnerHumanReviewShape": (VALID / "organization-change-events", _owner_review_attestor),
    "PublicRecordEvidenceShape": (VALID / "organization-change-events", _no_public_record),
    "owner-review-beside-its-warrant": (VALID / "organization-change-events", _owner_review_origin),
    "named-shape-beside-another-root": (VALID / "organization-change-events", _named_shape_beside_another_root),
    "effective-date-signature-collision": (VALID / "organization-change-events", _effective_date_signature_collision),
    "two-nested-kinds-one-signature": (VALID / "all-resource-profiles", _two_kinds_under_one_signature),
    "literal-focus-node": (VALID / "all-resource-profiles", _literal_concept_scheme),
    "every-digest-bad": (VALID / "all-resource-profiles", _every_digest_bad),
    "every-named-kind-at-once": (VALID / "organization-change-events", _every_named_kind_at_once),
    "three-warrants-broken": (VALID / "all-resource-profiles", _three_warrants_broken),
    "targeted-through-a-subclass-only": (VALID / "organization-change-events", _targeted_through_a_subclass_only),
}


@cache
def _parsed(distribution: Path) -> dict[str, Graph]:
    return _load_graphs(distribution)


def _fresh(distribution: Path) -> dict[str, Graph]:
    """A mutable copy of a valid fixture, parsed once per worker rather than once per mutation."""

    copies: dict[str, Graph] = {}
    for role, graph in _parsed(distribution).items():
        copies[role] = Graph(identifier=graph.identifier)
        copies[role] += graph
    return copies


@pytest.mark.parametrize("name", MUTATIONS)
def test_the_bounded_report_is_the_whole_graph_report_on_the_mutation_battery(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over planted violations: each named value shape, and each sample shape the `use_shapes` run could not take."""

    distribution, mutate = MUTATIONS[name]
    graphs = _fresh(distribution)
    mutate(graphs["asserted"])
    assert_bounded_report_is_the_oracles(name, graphs, monkeypatch)


def test_the_battery_plants_a_violation_inside_every_named_shape() -> None:
    """Every named shape `sh:node` or `sh:qualifiedValueShape` reaches has its mutation, so a new one cannot join untested."""

    _, shapes = atlas_validate._parse_binding_graphs()
    named = {
        str(value).rpartition("#")[2]
        for predicate in (SH.node, SH.qualifiedValueShape)
        for value in shapes.objects(None, predicate)
        if isinstance(value, URIRef)
    }
    assert named <= set(MUTATIONS)

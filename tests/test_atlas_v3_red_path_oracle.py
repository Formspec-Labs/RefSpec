"""Differential proof for the bounded SHACL red-path report, against the whole-graph fallback it replaced.

When the fail-fast red path's focused re-run could not reproduce what the
fast path had found, `_run_shacl` used to fall back to the whole-graph
normative report -- the run measured at 94 minutes on a 32M-quad red build.
The focused re-run named its shapes through pySHACL's `use_shapes`, which
skips every named shape they reach through `sh:node` or
`sh:qualifiedValueShape`, so every red build with a violation inside one of
the binding's eight named value shapes paid it: ten of the 62 `shacl.data`
corpus cases did. The re-run now retargets a copy of the shapes onto the
sampled nodes, and when a sample still falls short the fallback re-validates
every node the fast path refused the same way; neither touches the rest of
the graph.

So the whole-graph fallback is reconstructed here as the ORACLE -- a copy of
its engine call and its report reading, not an import, because it is the
thing being replaced -- and the bounded report is held to it over the red
corpus and over a mutation battery that plants, on valid fixtures, a
violation inside each named value shape and each sample shape the `use_shapes`
run could not take. For every input, two equalities:

* the red path names exactly the oracle's constraint components, for the
  role the oracle refuses, in one focused run and without the whole graph;
* the fallback, the re-validation of every refused node, reports exactly the
  oracle's violations, node for node -- the fast path refused every node the
  engine refuses, and no other.

No divergence is deliberate. `DELIBERATE_DIVERGENCES` is where one would be
recorded, with its reason, so that an unlisted divergence fails the suite
instead of becoming a diff nobody reads.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
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


def every_refused_node_violations(graph: Graph, ontology: Graph, shapes: Graph) -> set[Violation]:
    """The bounded fallback, taken whether or not the sample needed it: every refused node, re-validated."""

    view = atlas_validate._ShaclDataView([graph, inoculate(Graph(), ontology)])
    plan = atlas_validate._batched_shacl_plan(shapes)
    refused = atlas_validate._batched_shacl_precheck_misses(view, shapes, plan, first_only=False)
    _, batched, _ = atlas_validate._validate_shacl_data(view, plan.shapes)
    focused = atlas_validate._focused_shacl_report(view, shapes, atlas_validate._refused_focus_nodes(refused, batched))
    assert focused is not None
    return set(focused[1])


def red_path(
    graphs: dict[str, Graph],
    ontology: Graph,
    shapes: Graph,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, list[str], int]:
    """Refuse the graphs on the default red path; return the role it refused, the components it named, and its focused runs."""

    focused_runs = 0
    real_focused = atlas_validate._focused_shacl_report
    real_validate = atlas_validate._validate_shacl_data

    def counted(data_graph: Graph, shape_graph: Graph, focus_nodes: Any) -> Any:
        nonlocal focused_runs
        focused_runs += 1
        return real_focused(data_graph, shape_graph, focus_nodes)

    def bounded(data_graph: Graph, shape_graph: Graph) -> tuple[bool, Any, str]:
        assert shape_graph is not shapes, "the red path ran the whole-graph report"
        return real_validate(data_graph, shape_graph)

    with monkeypatch.context() as patch:
        patch.delenv(atlas_validate.VALIDATION_MODE_ENV, raising=False)
        patch.setattr(atlas_validate, "_focused_shacl_report", counted)
        patch.setattr(atlas_validate, "_validate_shacl_data", bounded)
        with pytest.raises(atlas_validate.AtlasValidationError) as error:
            atlas_validate._run_shacl(graphs, ontology, shapes)
    match = re.match(r"(\w+) graph does not conform \[([^\]]*)\]", error.value.detail)
    assert error.value.code == "shacl.data" and match is not None, error.value.detail
    return match.group(1), match.group(2).split(", "), focused_runs


def assert_bounded_report_is_the_oracles(name: str, graphs: dict[str, Graph], monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold the red path and its fallback to the whole-graph oracle on one input."""

    ontology, shapes = atlas_validate._parse_binding_graphs()
    oracle = {role: whole_graph_violations(graphs[role], ontology, shapes) for role in ROLES}
    refused_role = next(role for role in ROLES if oracle[role])
    expected = sorted({component for *_, component in oracle[refused_role]})

    role, components, focused_runs = red_path(graphs, ontology, shapes, monkeypatch)
    every = every_refused_node_violations(graphs[refused_role], ontology, shapes)

    diverged = (role, components, focused_runs, every) != (refused_role, expected, 1, oracle[refused_role])
    assert diverged == (name in DELIBERATE_DIVERGENCES), (
        f"{name}: red path {role} {components} in {focused_runs} focused runs, oracle {refused_role} {expected}; "
        f"fallback-only {sorted(every - oracle[refused_role])}, oracle-only {sorted(oracle[refused_role] - every)}"
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
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_the_bounded_report_is_the_whole_graph_report_on_the_mutation_battery(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over planted violations: each named value shape, and each sample shape the `use_shapes` run could not take."""

    distribution, mutate = MUTATIONS[name]
    graphs = _load_graphs(distribution)
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

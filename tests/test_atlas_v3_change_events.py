"""REF-072's organization change events on the Atlas 3.1 wire: each negative fails for its own clause.

The sealed corpus pins every case's first issue and, for a SHACL refusal, its
constraint components. Two pairs of change-event negatives share a component
(a missing original and a missing result are both sh:minCount), so the corpus
alone cannot tell which clause refused them; this reads the result path each
refusal names. The change-event policy entry is loaded here too, against the
three ways it may not be written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, SH, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate

ATLAS = "https://refspec.org/ns/atlas/v3#"
ATLAS_NS = Namespace(ATLAS)
RKAF = Namespace("https://rulespec.org/ns/v1#")
ORG = Namespace("http://www.w3.org/ns/org#")
INVERSE_BINDING = "[ sh:inversePath rkaf:bindsAssertion ]"
ORIGINAL = URIRef("urn:ref:test:organization:original")
RESULT = URIRef("urn:ref:test:organization:result")
CANONICAL = URIRef("urn:ref:test:organization:canonical")
OTHER_CANONICAL = URIRef("urn:ref:test:organization:other-canonical")
SAME = ATLAS_NS.sameEntityAs


# The owner's four fixed review values, one negative each. Each also fails
# atlas:EvidenceBindingShape's warrant sh:xone, whose humanReview branch pins
# the same values, so the message cannot say which clause refused; the
# report graph can.
OWNER_REVIEW_CASES = {
    "change-event-owner-review-origin": RKAF.assertionOrigin,
    "change-event-owner-review-attestor-kind": RKAF.attestorKind,
    "change-event-owner-review-basis": RKAF.epistemicBasis,
    "change-event-owner-review-role": RKAF.evidenceRole,
}
# The owner attesting under publisherAssertion, a warrant the xone admits: only
# the four fixed values refuse it, and all four do.
OWNER_OTHER_WARRANT_CASE = "change-event-owner-attested-other-warrant"


def _event_graph(*, ring: URIRef = ATLAS_NS.entity) -> Graph:
    """One content-addressed event from ORIGINAL to RESULT, both entity resources, in the given ring."""

    graph = Graph()
    for organization in (ORIGINAL, RESULT):
        graph.add((organization, RDF.type, ATLAS_NS.EntityResource))
        graph.add((organization, ATLAS_NS.semanticRing, ATLAS_NS.entity))
    pending = URIRef("urn:ref:test:pending-event")
    graph.add((pending, RDF.type, ATLAS_NS.OrganizationChangeEvent))
    graph.add((pending, ATLAS_NS.semanticRing, ring))
    graph.add((pending, ATLAS_NS.originalOrganization, ORIGINAL))
    graph.add((pending, ATLAS_NS.resultingOrganization, RESULT))
    event = URIRef(
        atlas_validate.CHANGE_EVENT_IRI_PREFIX
        + atlas_validate.rdf_node_digest(graph, pending).removeprefix("sha256:")
    )
    for _, predicate, obj in list(graph.triples((pending, None, None))):
        graph.remove((pending, predicate, obj))
        graph.add((event, predicate, obj))
    return graph


@pytest.mark.parametrize(
    ("case", "components", "paths"),
    (
        ("change-event-two-dates", ["MaxCountConstraintComponent"], {"rkaf:effectiveDate"}),
        ("change-event-no-date", ["MinCountConstraintComponent"], {"rkaf:effectiveDate"}),
        ("change-event-date-not-midnight", ["PatternConstraintComponent"], {"rkaf:effectiveDate"}),
        ("change-event-no-original", ["MinCountConstraintComponent"], {"atlas:originalOrganization"}),
        ("change-event-no-result", ["MinCountConstraintComponent"], {"atlas:resultingOrganization"}),
        ("change-event-original-among-results", ["DisjointConstraintComponent"], {"atlas:originalOrganization"}),
        ("change-event-no-public-record", ["QualifiedMinCountConstraintComponent"], {INVERSE_BINDING}),
        (
            "change-event-not-owner-reviewed",
            ["HasValueConstraintComponent", "NodeConstraintComponent"],
            {INVERSE_BINDING},
        ),
        ("change-event-raw-org-predicate", ["ClosedConstraintComponent"], {"org:resultingOrganization"}),
        *(
            (case, ["HasValueConstraintComponent", "NodeConstraintComponent", "XoneConstraintComponent"], {INVERSE_BINDING})
            for case in OWNER_REVIEW_CASES
        ),
        (OWNER_OTHER_WARRANT_CASE, ["HasValueConstraintComponent", "NodeConstraintComponent"], {INVERSE_BINDING}),
    ),
)
def test_each_change_event_shape_clause_refuses_on_its_own_path(
    case: str,
    components: list[str],
    paths: set[str],
) -> None:
    """Pin the one clause each SHACL negative violates: its components, and the path each top-level result names.

    The paths come off the report graph, not the message: the message is
    capped, and which results fit under the cap moved with the hash seed.
    """

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(atlas_validate.FIXTURE_ROOT / "invalid" / case)

    assert raised.value.code == "shacl.data"
    assert atlas_validate.shacl_constraint_components(raised.value) == components
    report = _whole_graph_report(case)
    named = set()
    for result in report.objects(None, SH.result):
        path = report.value(result, SH.resultPath)
        if path is None:
            continue
        inverse = report.value(path, SH.inversePath)
        named.add(f"[ sh:inversePath {_curie(inverse)} ]" if inverse is not None else _curie(path))
    assert named == paths


def _curie(term: URIRef) -> str:
    """The shapes file's spelling of a path predicate."""

    for prefix, namespace in (("rkaf", RKAF), ("atlas", ATLAS_NS), ("org", ORG)):
        if str(term).startswith(str(namespace)):
            return f"{prefix}:{str(term)[len(str(namespace)):]}"
    return str(term)


def _whole_graph_report(case: str) -> Graph:
    """The normative engine's report graph over one invalid case's asserted graph."""

    distribution = atlas_validate.FIXTURE_ROOT / "invalid" / case
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    _, graphs = atlas_validate._parse_packed_dataset(
        distribution, manifest, atlas_validate._check_pack_manifest(manifest)
    )
    ontology, shapes = atlas_validate._parse_binding_graphs()
    view = atlas_validate._ShaclDataView([graphs["asserted"], atlas_validate.inoculate(Graph(), ontology)])
    conforms, report, _ = atlas_validate._validate_shacl_data(view, shapes)
    assert not conforms
    return report


@pytest.mark.parametrize(
    ("case", "axes"),
    (
        *((case, {axis}) for case, axis in OWNER_REVIEW_CASES.items()),
        (OWNER_OTHER_WARRANT_CASE, set(OWNER_REVIEW_CASES.values())),
    ),
)
def test_each_owner_review_negative_breaks_its_own_fixed_values(case: str, axes: set[URIRef]) -> None:
    """Pin, off the whole-graph report graph, which of the owner's fixed-value clauses each negative breaks."""

    violations = atlas_validate._report_violations(_whole_graph_report(case))
    owner_clauses = {path for _focus, path, component in violations if component == "HasValueConstraintComponent"}
    assert owner_clauses == {str(axis) for axis in axes}


@pytest.mark.parametrize(
    ("case", "code"),
    (
        ("change-event-result-outside-entity-ring", "dataset.change-event-policy"),
        ("change-event-identity-drift", "dataset.change-event-identity"),
        ("change-event-inverse-pair", "dataset.change-event-inverse"),
        ("change-event-cycle", "dataset.change-event-cycle"),
        ("change-event-same-entity", "dataset.change-event-same-entity"),
        ("change-event-same-entity-closure", "dataset.change-event-same-entity"),
    ),
)
def test_each_change_event_rule_refuses_its_own_negative(case: str, code: str) -> None:
    """Pin that each corpus-wide rule is the first to refuse the case built for it."""

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate.validate_distribution(atlas_validate.FIXTURE_ROOT / "invalid" / case)

    assert raised.value.code == code


def test_a_chain_of_events_is_valid_and_is_not_a_cycle() -> None:
    """Pin that a split followed by a rename of one of its results validates."""

    result = atlas_validate.validate_distribution(atlas_validate.FIXTURE_ROOT / "valid" / "organization-change-events")

    assert result["counts"]["evidenceBindings"] > 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("resultingPredicate", "http://www.w3.org/ns/org#resultingOrganization", "non-Atlas term"),
        ("resultingPredicate", ATLAS + "sameEntityAs", "no assertion cell admits"),
        ("resultingPredicate", ATLAS + "originalOrganization", "no assertion cell admits"),
        ("resourceClass", ATLAS + "SubjectConcept", "does not match its ring"),
    ),
)
def test_the_change_event_policy_admits_only_atlas_links_no_assertion_cell_uses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    message: str,
) -> None:
    """Pin that a raw ORG link, a link shared with an assertion cell, or a mismatched class is refused."""

    profile = json.loads(atlas_validate.PROFILE_MAP_PATH.read_text(encoding="utf-8"))
    profile["changeEventPolicies"][0][field] = value
    profile["profileDigest"] = atlas_validate.canonical_sha256(
        {key: row for key, row in profile.items() if key != "profileDigest"},
        terminal_lf=False,
    )
    changed = tmp_path / "registry-resource-profiles.json"
    changed.write_bytes(atlas_validate.canonical_json_bytes(profile))
    monkeypatch.setattr(atlas_validate, "PROFILE_MAP_PATH", changed)

    with pytest.raises(atlas_validate.AtlasValidationError, match=message) as raised:
        atlas_validate._change_event_policies()

    assert raised.value.code == "profile.policy"


@pytest.mark.parametrize(
    "identity",
    ((ORIGINAL, RESULT), (RESULT, ORIGINAL)),
    ids=("original-to-result", "result-to-original"),
)
def test_an_event_between_two_identified_records_is_refused_in_either_direction(
    identity: tuple[URIRef, URIRef],
) -> None:
    """Pin that a current atlas:sameEntityAs in either direction refuses an event across the same two records."""

    graph = _event_graph()
    atlas_validate._check_change_events(graph, {})
    subject, obj = identity
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_change_events(graph, {(subject, ATLAS_NS.sameEntityAs, obj): ()})
    assert raised.value.code == "dataset.change-event-same-entity"


@pytest.mark.parametrize(
    "identity",
    (
        ((ORIGINAL, CANONICAL), (RESULT, CANONICAL)),
        ((CANONICAL, ORIGINAL), (CANONICAL, RESULT)),
        ((ORIGINAL, CANONICAL), (OTHER_CANONICAL, CANONICAL), (RESULT, OTHER_CANONICAL)),
    ),
    ids=("both-bridged-to-one-record", "one-record-bridged-to-both", "a-longer-path"),
)
def test_an_event_between_records_identity_joins_only_through_others_is_refused(
    identity: tuple[tuple[URIRef, URIRef], ...],
) -> None:
    """Pin the closure: no direct link joins the original to its result, but identity does, so the event is refused."""

    current = {(subject, SAME, obj): () for subject, obj in identity}
    with pytest.raises(atlas_validate.AtlasValidationError, match="directly or through other records") as raised:
        atlas_validate._check_change_events(_event_graph(), current)
    assert raised.value.code == "dataset.change-event-same-entity"


@pytest.mark.parametrize(
    "current",
    (
        {(ORIGINAL, SAME, CANONICAL): (), (RESULT, SAME, OTHER_CANONICAL): ()},
        {(ORIGINAL, SAME, CANONICAL): ()},
        {(ORIGINAL, SAME, CANONICAL): (), (RESULT, SKOS.exactMatch, CANONICAL): ()},
    ),
    ids=("two-separate-identities", "one-side-identified", "joined-by-another-predicate"),
)
def test_an_event_between_records_identity_keeps_apart_is_admitted(
    current: dict[tuple[URIRef, URIRef, URIRef], tuple[()]],
) -> None:
    """The closure's positive control: identity that never joins the original to its result refuses nothing."""

    atlas_validate._check_change_events(_event_graph(), current)


def test_an_event_outside_its_policys_ring_is_refused() -> None:
    """Pin the event's own ring against the changeEventPolicies entry, apart from the organizations it names."""

    with pytest.raises(atlas_validate.AtlasValidationError, match="is not in the") as raised:
        atlas_validate._check_change_events(_event_graph(ring=ATLAS_NS.subject), {})
    assert raised.value.code == "dataset.change-event-policy"


class _Unread(dict):
    """A current-assertion map that fails if anything iterates it."""

    def __iter__(self):
        raise AssertionError("the identity pass ran over current assertions")


def test_a_distribution_without_events_never_reads_the_current_assertions() -> None:
    """Pin the scaling guard: the pass over every current assertion runs only when an event names a link."""

    atlas_validate._check_change_events(Graph(), _Unread())
    with pytest.raises(AssertionError, match="identity pass ran"):
        atlas_validate._check_change_events(_event_graph(), _Unread())


def test_the_served_view_identity_omits_change_event_bindings_only() -> None:
    """Pin B1's served identity: a binding naming an event is counted in the RDF but never served; others are."""

    rkaf = Namespace("https://rulespec.org/ns/v1#")
    graph = _event_graph()
    event = next(graph.subjects(RDF.type, ATLAS_NS.OrganizationChangeEvent))
    statement = URIRef("urn:ref:atlas-assertion:" + "3" * 64)
    event_binding = URIRef("urn:ref:atlas-evidence:" + "1" * 64)
    statement_binding = URIRef("urn:ref:atlas-evidence:" + "2" * 64)
    graph.add((statement, RDF.type, ATLAS_NS.RelationAssertion))
    for binding, claim in ((event_binding, event), (statement_binding, statement)):
        graph.add((binding, RDF.type, rkaf.EvidenceBinding))
        graph.add((binding, rkaf.bindsAssertion, claim))

    assert atlas_validate.binds_change_event(graph, event_binding)
    assert not atlas_validate.binds_change_event(graph, statement_binding)
    assert atlas_validate._rdf_record_ids_by_role(graph)["EvidenceBinding"] == {str(event_binding), str(statement_binding)}
    assert atlas_validate._served_record_ids_by_role(graph)["EvidenceBinding"] == {str(statement_binding)}

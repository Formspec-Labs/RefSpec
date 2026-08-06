from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import rdflib
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.0"
VALID_DISTRIBUTION = BINDING_ROOT / "fixtures" / "valid" / "all-resource-profiles"
ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import build_fixtures as atlas_fixtures
import validate as atlas_validate


def _load_valid_graphs() -> tuple[Dataset, dict[str, Graph], Mapping[str, Any]]:
    manifest = json.loads((VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8"))
    dataset, graphs = atlas_validate._parse_dataset(VALID_DISTRIBUTION / "atlas.nq", manifest)
    return dataset, graphs, manifest


def _replace_object(graph: Graph, subject: URIRef, predicate: URIRef, replacement: URIRef) -> None:
    graph.remove((subject, predicate, None))
    graph.add((subject, predicate, replacement))


def _assert_shacl_rejects(graphs: Mapping[str, Graph], component: str) -> None:
    ontology, shapes = atlas_validate._parse_binding_graphs()
    with pytest.raises(atlas_validate.AtlasValidationError, match=component):
        atlas_validate._run_shacl(graphs, ontology, shapes)


def _fresh_asserted_graph_without_assertions() -> Graph:
    asserted = atlas_fixtures._base_fixture().asserted
    node_types = (
        ATLAS.RelationAssertion,
        ATLAS.CrossRingRelationAssertion,
        ATLAS.MappingAssertion,
        ATLAS.NativeRelationAssertion,
        ATLAS.SourceAssignment,
        ATLAS.EvidenceBinding,
    )
    nodes = {
        node
        for node_type in node_types
        for node in asserted.subjects(RDF.type, node_type)
    }
    for node in nodes:
        asserted.remove((node, None, None))
    return asserted


def _resource_rows(asserted: Graph, ring: URIRef) -> list[tuple[URIRef, URIRef, URIRef]]:
    rows: list[tuple[URIRef, URIRef, URIRef]] = []
    for resource in asserted.subjects(ATLAS.semanticRing, ring):
        if (resource, RDF.type, ATLAS.AtlasResource) not in asserted:
            continue
        release = next(asserted.objects(resource, ATLAS.inRelease))
        source_record = next(asserted.objects(resource, ATLAS.sourceRecord))
        assert isinstance(resource, URIRef)
        assert isinstance(release, URIRef)
        assert isinstance(source_record, URIRef)
        rows.append((resource, release, source_record))
    return sorted(rows, key=lambda row: tuple(map(str, row)))


def _allowed_predicate(ring: URIRef, assertion_type: URIRef) -> URIRef:
    predicates = atlas_validate._relation_policies()[ring][assertion_type]
    return min(predicates, key=str)


def test_core_shacl_still_rejects_an_assertion_without_evidence() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
    binding = next(asserted.subjects(ATLAS.bindsAssertion, assertion))
    asserted.remove((binding, None, None))

    _assert_shacl_rejects(graphs, "MinCountConstraintComponent")
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_evidence_bindings(asserted)
    assert raised.value.code == "dataset.evidence"
    assert "no immutable evidence binding" in raised.value.detail
    assert dataset.store is asserted.store


@pytest.mark.parametrize(
    ("mutation", "expected_detail"),
    (
        ("release-profile", "profile differs"),
        ("resource-scheme", "scheme differs"),
        ("resource-profile", "profile differs"),
        ("resource-ring", "ring differs"),
    ),
)
def test_release_reconciliation_and_core_paths_reject_cross_record_mismatches(
    mutation: str,
    expected_detail: str,
) -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource = next(asserted.subjects(RDF.type, ATLAS.SubjectConcept))
    release = next(asserted.objects(resource, ATLAS.inRelease))

    if mutation == "release-profile":
        current = next(asserted.objects(release, ATLAS.resourceProfile))
        replacement = next(
            profile
            for profile in (ATLAS.codeScheme, ATLAS.identifierScheme, ATLAS.structureScheme)
            if profile != current
        )
        _replace_object(asserted, release, ATLAS.resourceProfile, replacement)
    elif mutation == "resource-scheme":
        current = next(asserted.objects(resource, ATLAS.inScheme))
        replacement = next(
            scheme
            for scheme in asserted.subjects(RDF.type, ATLAS.ResourceScheme)
            if scheme != current
        )
        _replace_object(asserted, resource, ATLAS.inScheme, replacement)
    elif mutation == "resource-profile":
        current = next(asserted.objects(resource, ATLAS.resourceProfile))
        replacement = next(
            profile
            for profile in (ATLAS.codeScheme, ATLAS.identifierScheme, ATLAS.structureScheme)
            if profile != current
        )
        _replace_object(asserted, resource, ATLAS.resourceProfile, replacement)
    else:
        current = next(asserted.objects(resource, ATLAS.semanticRing))
        replacement = next(ring for ring in (ATLAS.subject, ATLAS.entity, ATLAS.value) if ring != current)
        _replace_object(asserted, resource, ATLAS.semanticRing, replacement)

    _assert_shacl_rejects(graphs, "EqualsConstraintComponent")
    with pytest.raises(atlas_validate.AtlasValidationError, match=expected_detail):
        atlas_validate._check_release_membership(asserted)
    assert dataset.store is asserted.store


def _resource_with_preferred_label(asserted: Graph) -> tuple[URIRef, URIRef]:
    resource = next(asserted.subjects(SKOSXL.prefLabel, None))
    label = next(asserted.objects(resource, SKOSXL.prefLabel))
    assert isinstance(resource, URIRef)
    assert isinstance(label, URIRef)
    return resource, label


def test_label_integrity_rejects_a_label_from_another_release() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource, label = _resource_with_preferred_label(asserted)
    release = next(asserted.objects(resource, ATLAS.inRelease))
    wrong_release = next(
        candidate
        for candidate in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
        if candidate != release
    )
    _replace_object(asserted, label, ATLAS.inRelease, wrong_release)

    with pytest.raises(atlas_validate.AtlasValidationError, match="release differs from its resource"):
        atlas_validate._check_label_integrity(asserted)
    assert dataset.store is asserted.store


def test_label_integrity_rejects_an_unshared_source_record() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource, label = _resource_with_preferred_label(asserted)
    resource_records = set(asserted.objects(resource, ATLAS.sourceRecord))
    wrong_record = next(
        record
        for record in asserted.subjects(RDF.type, ATLAS.SourceRecord)
        if record not in resource_records
    )
    _replace_object(asserted, label, ATLAS.sourceRecord, wrong_record)

    with pytest.raises(atlas_validate.AtlasValidationError, match="shares no SourceRecord"):
        atlas_validate._check_label_integrity(asserted)
    assert dataset.store is asserted.store


def test_label_integrity_rejects_equal_literals_in_distinct_roles() -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    resource, preferred = _resource_with_preferred_label(asserted)
    alternate = URIRef("urn:ref:atlas-test:label:alternate-with-preferred-literal")
    literal = next(asserted.objects(preferred, SKOSXL.literalForm))
    release = next(asserted.objects(preferred, ATLAS.inRelease))
    source_record = next(asserted.objects(preferred, ATLAS.sourceRecord))
    assert isinstance(literal, Literal)

    asserted.add((resource, SKOSXL.altLabel, alternate))
    asserted.add((alternate, SKOSXL.literalForm, literal))
    asserted.add((alternate, ATLAS.inRelease, release))
    asserted.add((alternate, ATLAS.sourceRecord, source_record))

    with pytest.raises(atlas_validate.AtlasValidationError, match="reuses a label node or literal"):
        atlas_validate._check_label_integrity(asserted)
    assert dataset.store is asserted.store


@pytest.mark.parametrize(
    "assertion_type",
    (ATLAS.MappingAssertion, ATLAS.NativeRelationAssertion, ATLAS.SourceAssignment),
    ids=("mapping", "native", "source-assignment"),
)
@pytest.mark.parametrize("mismatch", ("ring", "release"))
def test_core_paths_reject_assertion_endpoint_ring_and_release_mismatches(
    assertion_type: URIRef,
    mismatch: str,
) -> None:
    dataset, graphs, _ = _load_valid_graphs()
    asserted = graphs["asserted"]
    assertion = next(asserted.subjects(RDF.type, assertion_type))

    if mismatch == "ring":
        current = next(asserted.objects(assertion, ATLAS.semanticRing))
        replacement = next(
            ring
            for ring in (ATLAS.subject, ATLAS.entity, ATLAS.value, ATLAS.legalIdentity)
            if ring != current
        )
        _replace_object(asserted, assertion, ATLAS.semanticRing, replacement)
    else:
        current = next(asserted.objects(assertion, ATLAS.targetRelease))
        replacement = next(
            release
            for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
            if release != current
        )
        _replace_object(asserted, assertion, ATLAS.targetRelease, replacement)

    _assert_shacl_rejects(graphs, "EqualsConstraintComponent")
    assert dataset.store is asserted.store


@pytest.mark.parametrize(
    ("case", "expected_code", "expected_detail"),
    (
        ("mapping-ring", "dataset.release", "endpoint ring differs"),
        ("mapping-release", "dataset.release", "target release does not contain"),
        ("native-ring", "dataset.release", "endpoint ring differs"),
        ("assignment-ring", "dataset.assignment", "target ring differs"),
        ("assignment-release", "dataset.assignment", "target release does not contain"),
    ),
)
def test_python_assertion_backstops_reject_ring_and_release_mismatches(
    case: str,
    expected_code: str,
    expected_detail: str,
) -> None:
    asserted = _fresh_asserted_graph_without_assertions()

    if case == "mapping-ring":
        source, source_release, evidence_record = _resource_rows(asserted, ATLAS.subject)[0]
        target, target_release, _ = next(
            row
            for row in _resource_rows(asserted, ATLAS.subject)
            if row[1] != source_release
        )
        assertion_type = ATLAS.MappingAssertion
        ring = ATLAS.entity
    elif case == "mapping-release":
        source, source_release, evidence_record = _resource_rows(asserted, ATLAS.subject)[0]
        target, actual_target_release, _ = next(
            row
            for row in _resource_rows(asserted, ATLAS.subject)
            if row[1] != source_release
        )
        target_release = next(
            release
            for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
            if release not in {source_release, actual_target_release}
        )
        assertion_type = ATLAS.MappingAssertion
        ring = ATLAS.subject
    elif case == "native-ring":
        source_row, target_row = next(
            (left, right)
            for left in _resource_rows(asserted, ATLAS.value)
            for right in _resource_rows(asserted, ATLAS.value)
            if left[0] != right[0] and left[1] == right[1]
        )
        source, source_release, evidence_record = source_row
        target, target_release, _ = target_row
        assertion_type = ATLAS.NativeRelationAssertion
        ring = ATLAS.subject
    else:
        target, actual_target_release, source = _resource_rows(asserted, ATLAS.entity)[0]
        source_release = next(asserted.objects(source, ATLAS.inSourceRelease))
        evidence_record = source
        assertion_type = ATLAS.SourceAssignment
        if case == "assignment-ring":
            ring = ATLAS.subject
            target_release = actual_target_release
        else:
            ring = ATLAS.entity
            target_release = next(
                release
                for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
                if release != actual_target_release
            )

    assert isinstance(source_release, URIRef)
    assert isinstance(target_release, URIRef)
    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=assertion_type,
        ring=ring,
        subject=source,
        predicate=_allowed_predicate(ring, assertion_type),
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name=f"python-backstop-{case}",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_assertions(asserted)

    assert raised.value.code == expected_code
    assert expected_detail in raised.value.detail


def test_publisher_native_relation_may_cross_exact_releases_in_one_ring() -> None:
    asserted = _fresh_asserted_graph_without_assertions()
    predicate = SKOS.related
    source, source_release, evidence_record = _resource_rows(asserted, ATLAS.subject)[0]
    target, target_release, _ = next(
        row
        for row in _resource_rows(asserted, ATLAS.subject)
        if row[1] != source_release
    )
    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=ATLAS.NativeRelationAssertion,
        ring=ATLAS.subject,
        subject=source,
        predicate=predicate,
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name="publisher-native-cross-release",
    )

    supported = atlas_validate._validate_assertions(asserted)

    assert (source, predicate, target) in supported


@pytest.mark.parametrize(
    ("case", "expected_detail"),
    (
        ("source-ring", "source endpoint ring differs"),
        ("target-release", "target release does not contain"),
    ),
)
def test_python_cross_ring_backstops_reject_endpoint_mismatches(
    case: str,
    expected_detail: str,
) -> None:
    asserted = _fresh_asserted_graph_without_assertions()
    source, source_release, evidence_record = _resource_rows(
        asserted, ATLAS.entity
    )[0]
    target, target_release, _ = _resource_rows(asserted, ATLAS.subject)[0]
    source_ring = ATLAS.entity
    if case == "source-ring":
        source_ring = ATLAS.legalIdentity
    else:
        target_release = next(
            release
            for release in asserted.subjects(RDF.type, ATLAS.AtlasRelease)
            if release not in {source_release, target_release}
        )

    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=source_ring,
        target_ring=ATLAS.subject,
        subject=source,
        predicate=ATLAS.hasIndexedSubject,
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name=f"python-cross-ring-{case}",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_assertions(asserted)

    assert raised.value.code == "dataset.release"
    assert expected_detail in raised.value.detail


@pytest.mark.parametrize("case", ("pair", "predicate"))
def test_python_cross_ring_policy_rejects_disallowed_cells(case: str) -> None:
    asserted = _fresh_asserted_graph_without_assertions()
    source, source_release, evidence_record = _resource_rows(
        asserted, ATLAS.entity
    )[0]
    if case == "pair":
        target_ring = ATLAS.value
        predicate = ATLAS.hasIndexedSubject
    else:
        target_ring = ATLAS.legalIdentity
        predicate = ATLAS.hasIndexedSubject
    target, target_release, _ = _resource_rows(asserted, target_ring)[0]

    atlas_fixtures._add_assertion(
        asserted,
        assertion_type=ATLAS.CrossRingRelationAssertion,
        ring=None,
        source_ring=ATLAS.entity,
        target_ring=target_ring,
        subject=source,
        predicate=predicate,
        obj=target,
        source_release=source_release,
        target_release=target_release,
        evidence_record=evidence_record,
        evidence_name=f"python-cross-ring-policy-{case}",
    )

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._validate_assertions(asserted)

    assert raised.value.code == "dataset.relation"
    assert "is not allowed" in raised.value.detail


def test_python_cross_ring_policy_matrix_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = json.loads(atlas_validate.PROFILE_MAP_PATH.read_text(encoding="utf-8"))
    profile["crossRingRelationPolicies"][0]["predicates"] = [
        str(ATLAS.alternateCrossRingRelation)
    ]
    profile["profileDigest"] = atlas_validate.canonical_sha256(
        {key: value for key, value in profile.items() if key != "profileDigest"},
        terminal_lf=False,
    )
    changed_path = tmp_path / "registry-resource-profiles.json"
    changed_path.write_bytes(atlas_validate.canonical_json_bytes(profile))
    monkeypatch.setattr(atlas_validate, "PROFILE_MAP_PATH", changed_path)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._cross_ring_relation_policies()

    assert raised.value.code == "profile.policy"
    assert "closed Atlas 3.0 matrix" in raised.value.detail


@pytest.mark.parametrize("conflicting_target", (False, True))
def test_identifier_pair_maps_to_exactly_one_resource(
    conflicting_target: bool,
) -> None:
    asserted = atlas_fixtures._base_fixture().asserted
    identifier = next(asserted.subjects(RDF.type, ATLAS.Identifier))
    original_resource = next(asserted.objects(identifier, ATLAS.identifies))
    duplicate = URIRef("urn:ref:atlas-test:identifier:duplicate")
    asserted.add((duplicate, RDF.type, ATLAS.Identifier))
    asserted.add(
        (
            duplicate,
            ATLAS.identifierScheme,
            next(asserted.objects(identifier, ATLAS.identifierScheme)),
        )
    )
    asserted.add(
        (
            duplicate,
            ATLAS.identifierValue,
            next(asserted.objects(identifier, ATLAS.identifierValue)),
        )
    )
    target = original_resource
    if conflicting_target:
        target = next(
            resource
            for resource in asserted.subjects(RDF.type, ATLAS.AtlasResource)
            if resource != original_resource
        )
    asserted.add((duplicate, ATLAS.identifies, target))

    if not conflicting_target:
        atlas_validate._check_identifier_uniqueness(asserted)
        return

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_identifier_uniqueness(asserted)

    assert raised.value.code == "dataset.identifier-uniqueness"
    assert "AGENCY-001" in raised.value.detail
    assert "identifies multiple Atlas resources" in raised.value.detail


def test_serialized_nquads_profile_accepts_only_sorted_unique_lines(tmp_path: Path) -> None:
    first = b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
    second = b"<urn:b> <urn:p> <urn:o> <urn:g> .\n"
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(first + second)
    assert atlas_validate._check_serialized_nquads_profile(dataset_path) == 2

    for invalid in (first + first, second + first):
        dataset_path.write_bytes(invalid)
        with pytest.raises(atlas_validate.AtlasValidationError, match="sorted and unique"):
            atlas_validate._check_serialized_nquads_profile(dataset_path)


def test_serialized_nquads_profile_rejects_oversized_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    line = b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
    dataset_path.write_bytes(line)
    monkeypatch.setattr(atlas_validate, "NQUADS_MAX_LINE_BYTES", len(line) - 1)

    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_serialized_nquads_profile(dataset_path)

    assert raised.value.code == "rdf.resource-limit"


def test_canonical_term_comparison_rejects_an_equivalent_noncanonical_escape(tmp_path: Path) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(b'<urn:s> <urn:p> "\\u0061" <urn:g> .\n')
    line_count = atlas_validate._check_serialized_nquads_profile(dataset_path)
    dataset = Dataset()
    dataset.parse(dataset_path, format="nquads")

    with pytest.raises(atlas_validate.AtlasValidationError, match="canonical N-Quads term form"):
        atlas_validate._check_canonical_dataset_terms(dataset_path, dataset, line_count=line_count)


def test_parse_dataset_streams_without_path_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(b"<urn:s> <urn:p> <urn:o> <urn:g> .\n")
    manifest = {"graphs": [{"role": "asserted", "id": "urn:g", "quadCount": 1}]}

    def fail_whole_file_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("dataset parsing must not use a whole-file Path read")

    monkeypatch.setattr(Path, "read_bytes", fail_whole_file_read)
    monkeypatch.setattr(Path, "read_text", fail_whole_file_read)
    dataset, graphs = atlas_validate._parse_dataset(dataset_path, manifest)

    assert len(dataset) == 1
    assert graphs["asserted"].store is dataset.store


def test_file_digest_streams_without_using_path_read_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"stream this payload\n"
    path = tmp_path / "member.bin"
    path.write_bytes(payload)

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("file_sha256 must not materialize the complete member")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    assert atlas_validate.file_sha256(path) == "sha256:" + hashlib.sha256(payload).hexdigest()


def test_parsed_role_graphs_are_views_over_one_dataset_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = json.loads((VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8"))
    expected_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}

    def fail_graph_copy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("role graph views must not allocate independent Graph stores")

    monkeypatch.setattr(atlas_validate, "Graph", fail_graph_copy)
    dataset, graphs = atlas_validate._parse_dataset(VALID_DISTRIBUTION / "atlas.nq", manifest)

    assert {role: graph.identifier for role, graph in graphs.items()} == expected_ids
    assert all(graph.store is dataset.store for graph in graphs.values())


def test_validate_distribution_analyzes_assertions_once(monkeypatch: pytest.MonkeyPatch) -> None:
    original = atlas_validate._validate_assertions
    analyses: list[Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]]] = []

    def counted(asserted: Graph) -> Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]]:
        result = original(asserted)
        analyses.append(result)
        return result

    monkeypatch.setattr(atlas_validate, "_validate_assertions", counted)
    analysis_argument = {
        "_check_skos_integrity": 0,
        "_check_projection": 2,
        "_check_derived": 3,
        "_check_reasoning_isolation": 1,
    }
    for consumer_name, argument_index in analysis_argument.items():
        consumer = getattr(atlas_validate, consumer_name)

        def checked_consumer(
            *args: object,
            _consumer: Any = consumer,
            _argument_index: int = argument_index,
            **kwargs: object,
        ) -> Any:
            assert analyses
            assert args[_argument_index] is analyses[0]
            return _consumer(*args, **kwargs)

        monkeypatch.setattr(atlas_validate, consumer_name, checked_consumer)

    atlas_validate.validate_distribution(VALID_DISTRIBUTION)

    assert len(analyses) == 1


@pytest.mark.parametrize("case", ("exact", "missing", "substitution", "extra"))
def test_projection_comparison_uses_membership_and_preserves_rejection(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = (URIRef("urn:s:1"), URIRef("urn:p"), URIRef("urn:o:1"))
    second = (URIRef("urn:s:2"), URIRef("urn:p"), URIRef("urn:o:2"))
    extra = (URIRef("urn:s:3"), URIRef("urn:p"), URIRef("urn:o:3"))
    expected = (first, second)
    actual_by_case = {
        "exact": expected,
        "missing": (first,),
        "substitution": (first, extra),
        "extra": (*expected, extra),
    }

    class StreamingProjection:
        def __init__(self, triples: tuple[tuple[URIRef, URIRef, URIRef], ...]) -> None:
            self.triples = frozenset(triples)
            self.lookups: list[tuple[URIRef, URIRef, URIRef]] = []
            self.iterations = 0

        def __contains__(self, triple: object) -> bool:
            assert isinstance(triple, tuple)
            self.lookups.append(triple)
            return triple in self.triples

        def __iter__(self):
            self.iterations += 1
            return iter(self.triples)

    def fail_graph_allocation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("projection comparison must not allocate an expected Graph")

    probe = StreamingProjection(actual_by_case[case])
    supported = {first: frozenset(), second: frozenset()}
    monkeypatch.setattr(
        atlas_validate,
        "_expected_projection_triples",
        lambda *_args: iter(expected),
    )
    monkeypatch.setattr(atlas_validate, "Graph", fail_graph_allocation)
    if case == "exact":
        atlas_validate._check_projection(Graph(), probe, supported)  # type: ignore[arg-type]
    else:
        with pytest.raises(atlas_validate.AtlasValidationError) as raised:
            atlas_validate._check_projection(Graph(), probe, supported)  # type: ignore[arg-type]
        assert raised.value.code == "dataset.projection"

    assert probe.lookups == list(expected)
    assert probe.iterations == 1


def test_reasoning_isolation_sends_only_mapping_triples_to_owl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = URIRef("urn:ref:atlas-test:a")
    middle = URIRef("urn:ref:atlas-test:b")
    target = URIRef("urn:ref:atlas-test:c")
    first_mapping = (source, SKOS.exactMatch, middle)
    second_mapping = (middle, SKOS.exactMatch, target)
    inferred_mapping = (source, SKOS.exactMatch, target)
    native = (source, SKOS.related, target)
    cross_ring = (source, ATLAS.hasIndexedSubject, target)
    first_assertion = URIRef("urn:ref:atlas-test:assertion:mapping-1")
    second_assertion = URIRef("urn:ref:atlas-test:assertion:mapping-2")
    current = {
        first_mapping: frozenset({first_assertion}),
        second_mapping: frozenset({second_assertion}),
        native: frozenset({URIRef("urn:ref:atlas-test:assertion:native")}),
        cross_ring: frozenset(
            {URIRef("urn:ref:atlas-test:assertion:cross-ring")}
        ),
    }
    derived = Graph()
    derived_node = URIRef("urn:ref:atlas-test:derived")
    derived.add((derived_node, RDF.type, ATLAS.DerivedRelation))
    derived.add((derived_node, ATLAS.relationSubject, source))
    derived.add((derived_node, ATLAS.relationPredicate, SKOS.exactMatch))
    derived.add((derived_node, ATLAS.relationObject, target))
    derived.add((derived_node, ATLAS.derivedFromAssertion, first_assertion))
    derived.add((derived_node, ATLAS.derivedFromAssertion, second_assertion))
    captured: dict[str, Any] = {}

    class CapturingClosure:
        def __init__(self, semantics: object, **kwargs: object) -> None:
            captured["semantics"] = semantics
            captured["kwargs"] = kwargs

        def expand(self, graph: Graph) -> None:
            captured["input"] = set(graph)
            graph.add(inferred_mapping)

    monkeypatch.setattr(atlas_validate, "DeductiveClosure", CapturingClosure)
    assert atlas_validate._check_reasoning_isolation(derived, current) == 7
    assert captured["semantics"] is atlas_validate.OWLRL_Semantics
    assert captured["kwargs"] == {
        "axiomatic_triples": False,
        "datatype_axioms": False,
    }
    assert captured["input"] == {
        first_mapping,
        second_mapping,
        (SKOS.exactMatch, RDF.type, OWL.TransitiveProperty),
        (SKOS.exactMatch, RDF.type, OWL.SymmetricProperty),
    }


@pytest.mark.parametrize(
    ("edges", "expected"),
    (
        ((("a", "b"),), 3),
        ((("a", "b"), ("b", "a")), 2),
        ((("a", "b"), ("c", "d")), 6),
        ((("a", "b"), ("b", "c"), ("a", "c")), 6),
        ((("a", "a"),), 0),
    ),
)
def test_exact_match_inference_count_uses_component_arithmetic(
    edges: tuple[tuple[str, str], ...],
    expected: int,
) -> None:
    current = {
        (URIRef(f"urn:{subject}"), SKOS.exactMatch, URIRef(f"urn:{obj}")): frozenset(
            {URIRef(f"urn:assertion:{index}")}
        )
        for index, (subject, obj) in enumerate(edges)
    }

    assert atlas_validate._build_exact_match_index(current).inferred_count == expected
    assert atlas_validate._check_reasoning_isolation(Graph(), current) == expected


def test_exact_match_count_deduplicates_multiple_supporting_assertions() -> None:
    triple = (URIRef("urn:a"), SKOS.exactMatch, URIRef("urn:b"))
    current = {
        triple: frozenset({URIRef("urn:assertion:1"), URIRef("urn:assertion:2")})
    }

    assert atlas_validate._build_exact_match_index(current).inferred_count == 3


def test_hierarchy_queries_discard_each_traversal_closure() -> None:
    nodes = [URIRef(f"urn:node:{index}") for index in range(2_000)]
    hierarchy = {
        node: {nodes[index + 1]}
        for index, node in enumerate(nodes[:-1])
    }
    pair = frozenset((nodes[0], nodes[-1]))

    assert atlas_validate._hierarchy_connected_pairs(hierarchy, {pair}) == {pair}


def test_external_merge_uses_bounded_fan_in_and_preserves_every_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = [f"{index:02d}\n".encode() for index in reversed(range(9))]
    chunks: list[Path] = []
    for index, line in enumerate(lines):
        chunk = tmp_path / f"chunk-{index:02d}.nq"
        chunk.write_bytes(line)
        chunks.append(chunk)
    group_sizes: list[int] = []
    original = atlas_validate._merge_sorted_nquads_chunks

    def bounded(inputs: list[Path], output: Path) -> None:
        group_sizes.append(len(inputs))
        original(inputs, output)

    monkeypatch.setattr(atlas_validate, "_merge_sorted_nquads_chunks", bounded)
    final_chunks = atlas_validate._bound_sorted_nquads_merge(
        chunks,
        tmp_path,
        fan_in=2,
    )
    observed = [
        line
        for chunk in final_chunks
        for line in chunk.read_bytes().splitlines(keepends=True)
    ]

    assert len(final_chunks) <= 2
    assert group_sizes and max(group_sizes) <= 2
    assert sorted(observed) == sorted(lines)


def test_canonical_sort_flushes_chunks_on_byte_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(
        b"<urn:a> <urn:p> <urn:o> <urn:g> .\n"
        b"<urn:b> <urn:p> <urn:o> <urn:g> .\n"
    )
    dataset = Dataset()
    atlas_validate._parse_nquads_preserving_lexical_forms(dataset, dataset_path)
    observed_chunk_counts: list[int] = []
    original = atlas_validate._bound_sorted_nquads_merge

    def capture(chunks: list[Path], temporary: Path, *, fan_in: int) -> list[Path]:
        observed_chunk_counts.append(len(chunks))
        return original(chunks, temporary, fan_in=fan_in)

    monkeypatch.setattr(atlas_validate, "NQUADS_SORT_CHUNK_BYTES", 1)
    monkeypatch.setattr(atlas_validate, "_bound_sorted_nquads_merge", capture)
    atlas_validate._check_canonical_dataset_terms(dataset_path, dataset, line_count=2)

    assert observed_chunk_counts == [2]


def test_canonical_sort_normalizes_io_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_bytes(b"<urn:a> <urn:p> <urn:o> <urn:g> .\n")
    dataset = Dataset()
    atlas_validate._parse_nquads_preserving_lexical_forms(dataset, dataset_path)

    def fail_merge(*_args: object, **_kwargs: object) -> list[Path]:
        raise OSError("simulated temporary-disk failure")

    monkeypatch.setattr(atlas_validate, "_bound_sorted_nquads_merge", fail_merge)
    with pytest.raises(atlas_validate.AtlasValidationError) as raised:
        atlas_validate._check_canonical_dataset_terms(dataset_path, dataset, line_count=1)

    assert raised.value.code == "rdf.resource-limit"
    assert "simulated temporary-disk failure" in raised.value.detail


def test_dataset_parser_preserves_typed_literal_lexical_form_without_global_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "atlas.nq"
    dataset_path.write_text(
        '<urn:s> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> <urn:g> .\n',
        encoding="utf-8",
    )
    manifest = {
        "graphs": [
            {"role": "asserted", "id": "urn:g", "quadCount": 1},
        ]
    }

    monkeypatch.setattr(rdflib, "NORMALIZE_LITERALS", True)
    _, graphs = atlas_validate._parse_dataset(dataset_path, manifest)
    literal = next(graphs["asserted"].objects(URIRef("urn:s"), URIRef("urn:p")))

    assert isinstance(literal, Literal)
    assert str(literal) == "01"
    assert rdflib.NORMALIZE_LITERALS is True


def test_atlas_shapes_have_no_per_focus_sparql_constraints() -> None:
    shapes = Graph().parse(BINDING_ROOT / "shapes" / "atlas.shacl.ttl", format="turtle")
    shacl = Namespace("http://www.w3.org/ns/shacl#")

    assert not list(shapes.triples((None, shacl.sparql, None)))
    assert not list(shapes.triples((None, shacl.select, None)))

"""REF-037 permits one preferred label per language, including on one resource.

The old resource-wide maximum is retained as a test-only oracle. Only a set of
preferred labels with distinct languages may change from rejected to accepted;
duplicate languages and role overlap remain refusals. The real specimen comes
from the publisher's retained UMTHES response, not the Atlas producer.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pyshacl
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import build_fixtures as fixtures
import validate as validator

ATLAS = validator.ATLAS
SKOSXL = validator.SKOSXL
RESOURCE = URIRef("urn:ref:atlas-fixture:resource:subject-c")
# Frozen copy of the replaced clause, independent of the current shape file.
OLD_MAXIMUM = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix skosxl: <http://www.w3.org/2008/05/skos-xl#> .
<urn:test:old-preferred-maximum> a sh:NodeShape ;
  sh:targetSubjectsOf skosxl:prefLabel ;
  sh:property [ sh:path skosxl:prefLabel ; sh:maxCount 1 ] .
"""


def _with_preferred_labels(literals: tuple[Literal, ...]) -> fixtures.Fixture:
    """Keep a complete valid resource and vary only its preferred literals."""

    fixture = fixtures._base_fixture()
    graph = fixture.asserted
    first = next(graph.objects(RESOURCE, SKOSXL.prefLabel))
    graph.set((first, SKOSXL.literalForm, literals[0]))
    for index, literal in enumerate(literals[1:], start=1):
        label = URIRef(f"urn:test:preferred-label:{index}")
        graph.add((RESOURCE, SKOSXL.prefLabel, label))
        graph.add((label, RDF.type, SKOSXL.Label))
        graph.add((label, SKOSXL.literalForm, literal))
        for predicate in (ATLAS.inRelease, ATLAS.sourceRecord):
            graph.add((label, predicate, next(graph.objects(RESOURCE, predicate))))
    fixture.projection = validator._expected_projection(graph)
    return fixture


def _accepted(fixture: fixtures.Fixture) -> bool:
    ontology, shapes = validator._parse_binding_graphs()
    try:
        validator._run_shacl(
            {"asserted": fixture.asserted, "projection": fixture.projection, "derived": fixture.derived},
            ontology,
            shapes,
        )
        validator._check_label_integrity(fixture.asserted)
    except validator.AtlasValidationError as error:
        assert error.code in {"shacl.data", "dataset.label-integrity"}
        if error.code == "shacl.data":
            assert validator.shacl_constraint_components(error) == ["UniqueLangConstraintComponent"]
        return False
    return True


@pytest.mark.parametrize(
    ("languages", "accepted", "old_accepted"),
    (
        (("en",), True, True),
        (("en", "de"), True, False),
        (("en", "de", "fr"), True, False),
        (("en", "en"), False, False),
        (("en", "de", "en"), False, False),
    ),
)
def test_only_distinct_preferred_languages_change_the_old_verdict(
    languages: tuple[str, ...], accepted: bool, old_accepted: bool,
) -> None:
    fixture = _with_preferred_labels(tuple(Literal(f"Label {i}", lang=lang) for i, lang in enumerate(languages)))
    old_result, _, _ = pyshacl.validate(fixture.asserted, shacl_graph=Graph().parse(data=OLD_MAXIMUM, format="turtle"))
    assert old_result is old_accepted
    assert _accepted(fixture) is accepted


def test_equal_literals_on_distinct_preferred_labels_remain_refused() -> None:
    # A SHACL property path sees a set of literals, so equal literals collapse.
    # The linear integrity check must count label identities before that loss.
    fixture = _with_preferred_labels((Literal("Label", lang="en"),) * 2)
    old_result, _, _ = pyshacl.validate(fixture.asserted, shacl_graph=Graph().parse(data=OLD_MAXIMUM, format="turtle"))
    assert not old_result
    assert not _accepted(fixture)


def test_the_retained_umthes_preferred_labels_validate() -> None:
    relative = "output/registry-real-data-sources/umthes-gemet-endpoints-2026-08-15.zip"
    pin = next(row for row in json.loads((ROOT / "tools/pinned_inputs.json").read_text())["inputs"] if row["path"] == relative)
    path = ROOT / relative
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"]
    with zipfile.ZipFile(path) as archive:
        source = Graph().parse(data=archive.read("records/_00000013.nt"), format="nt")
    literals = tuple(sorted(source.objects(URIRef("https://sns.uba.de/umthes/_00000013"), SKOS.prefLabel), key=str))
    assert set(literals) == {Literal("Abbau", lang="de"), Literal("degradation", lang="en")}
    fixture = _with_preferred_labels(literals)
    old_result, _, _ = pyshacl.validate(fixture.asserted, shacl_graph=Graph().parse(data=OLD_MAXIMUM, format="turtle"))
    assert not old_result
    assert _accepted(fixture)

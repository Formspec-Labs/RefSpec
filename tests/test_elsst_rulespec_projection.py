"""ELSST source-native projection through exact Rulespec release manifests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from rdflib import Graph

from refspec.registry.elsst import parse_elsst_file
from refspec.registry.elsst_acquisition import (
    ELSST_R5,
    ELSST_R6,
    ElsstReleaseSource,
)
from refspec.registry.elsst_rulespec_projection import (
    DCTERMS_ISSUED_IRI,
    ElsstRulespecProjectionError,
    build_elsst_rulespec_projection,
    require_valid_elsst_rulespec_projection,
    seal_elsst_rulespec_projection,
)
from refspec.release_graph import load_pinned_rulespec_validator

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESPEC_DIR = REFSPEC_ROOT.parents[1] / "rulespec"
FIXTURE_DIR = Path(__file__).parent / "fixtures"
R5_FIXTURE = FIXTURE_DIR / "elsst-projection-mini-r5.ttl"
R6_FIXTURE = FIXTURE_DIR / "elsst-projection-mini-r6.ttl"

R5_RETIRED = "https://elsst.cessda.eu/id/5/05fd5779-69ad-4872-ae25-a8c400b73e10"
R6_RETIRED = "https://elsst.cessda.eu/id/6/05fd5779-69ad-4872-ae25-a8c400b73e10"
R6_SUCCESSOR = "https://elsst.cessda.eu/id/6/4ae8f7d8-3ff9-4258-9dc8-7cf9c345dd6f"
TEST_R5_RELEASE_IRI = "urn:test:elsst:release:r5"
TEST_R6_RELEASE_IRI = "urn:test:elsst:release:r6"


@pytest.fixture
def rulespec_dir() -> Path:
    configured = os.environ.get("RULESPEC_DIR")
    path = Path(configured).resolve() if configured else DEFAULT_RULESPEC_DIR.resolve()
    if not (path / ".git").exists():
        pytest.skip(f"live Rulespec checkout is unavailable: {path}")
    return path


def _fixture_release(
    path: Path,
    *,
    version: str,
    release_iri: str,
    scheme_iri: str,
) -> ElsstReleaseSource:
    payload = path.read_bytes()
    return ElsstReleaseSource(
        version=version,
        release_iri=release_iri,
        concept_scheme_iri=scheme_iri,
        source_url=f"https://example.test/ELSST_R{version}.ttl",
        expected_sha256=("sha256:" + hashlib.sha256(payload).hexdigest()),
        expected_byte_length=len(payload),
        filename=path.name,
    )


def _fixture_pair():
    previous_release = _fixture_release(
        R5_FIXTURE,
        version="5",
        release_iri=TEST_R5_RELEASE_IRI,
        scheme_iri=ELSST_R5.concept_scheme_iri,
    )
    current_release = _fixture_release(
        R6_FIXTURE,
        version="6",
        release_iri=TEST_R6_RELEASE_IRI,
        scheme_iri=ELSST_R6.concept_scheme_iri,
    )
    previous = parse_elsst_file(
        R5_FIXTURE,
        source_url=previous_release.source_url,
        expected_sha256=previous_release.expected_sha256,
        expected_byte_length=previous_release.expected_byte_length,
    )
    current = parse_elsst_file(
        R6_FIXTURE,
        source_url=current_release.source_url,
        expected_sha256=current_release.expected_sha256,
        expected_byte_length=current_release.expected_byte_length,
    )
    return previous, current, previous_release, current_release


def test_source_native_projection_preserves_identity_and_derives_only_observed_transition(
    rulespec_dir: Path,
) -> None:
    previous, current, previous_release, current_release = _fixture_pair()
    validator = load_pinned_rulespec_validator(rulespec_dir)

    projection = build_elsst_rulespec_projection(
        previous,
        current,
        validator=validator,
        previous_release=previous_release,
        current_release=current_release,
    )

    nodes = {node["@id"]: node for node in projection.graph["@graph"]}
    assert nodes[ELSST_R5.concept_scheme_iri]["@type"] == ("skos:ConceptScheme")
    assert nodes[ELSST_R6.concept_scheme_iri]["@type"] == ("skos:ConceptScheme")
    assert nodes[ELSST_R5.concept_scheme_iri][
        "dcterms:identifier"
    ] == [
        {
            "@value": (
                "urn:ddi:int.cessda.elsst:"
                "00000000-0000-0000-0000-000000000001:5"
            ),
            "@language": "en",
        },
        {
            "@value": (
                "urn:ddi:int.cessda.elsst:"
                "00000000-0000-0000-0000-000000000001:5"
            ),
            "@language": "es",
        },
    ]
    assert nodes[ELSST_R6.concept_scheme_iri][
        "dcterms:identifier"
    ] == [
        {
            "@value": (
                "urn:ddi:int.cessda.elsst:"
                "00000000-0000-0000-0000-000000000001:6"
            ),
            "@language": "en",
        },
        {
            "@value": (
                "urn:ddi:int.cessda.elsst:"
                "00000000-0000-0000-0000-000000000001:6"
            ),
            "@language": "es",
        },
    ]
    assert nodes[R6_RETIRED]["@type"] == "skos:Concept"
    assert not [
        node
        for node in nodes.values()
        if node.get("@type")
        in {
            "rkaf:RegisteredConcept",
            "rkaf:LocalConcept",
        }
    ]
    assert nodes[R6_RETIRED]["owl:deprecated"] == "true"
    assert nodes[R6_RETIRED]["owl:priorVersion"] == [R5_RETIRED]
    assert nodes[R6_RETIRED]["dcterms:isVersionOf"] == [
        "https://elsst.cessda.eu/id/05fd5779-69ad-4872-ae25-a8c400b73e10"
    ]
    assert nodes[R6_RETIRED]["dcterms:isReplacedBy"] == [R6_SUCCESSOR]
    assert nodes[R6_SUCCESSOR]["skos:prefLabel"] == {
        "el": "ΑΡΧΗΓΟΣ ΝΟΙΚΟΚΥΡΙΟΥ",
        "en": "HEADS OF HOUSEHOLD",
        "es": "CABEZAS DE HOGAR",
    }

    r5_release = nodes[TEST_R5_RELEASE_IRI]
    r6_release = nodes[TEST_R6_RELEASE_IRI]
    assert len(r5_release["prov:hadMember"]) == 3
    assert len(r6_release["prov:hadMember"]) == 4
    assert "rkaf:referenceReleaseDigest" not in r5_release
    assert "rkaf:referenceReleaseDigest" not in r6_release

    assert len(projection.lifecycle_transitions) == 1
    transition = projection.lifecycle_transitions[0]
    assert transition.operation == "replacement"
    assert transition.source_status_concept_iri == R6_RETIRED
    assert transition.predecessor_concept_iris == (R5_RETIRED,)
    assert transition.successor_concept_iris == (R6_SUCCESSOR,)
    event = nodes[transition.event_iri]
    assert event["rkaf:appliesTo"] == [R5_RETIRED]
    assert event["rkaf:predecessorConceptRelease"] == (
        TEST_R5_RELEASE_IRI
    )
    assert event["rkaf:successorConceptRelease"] == (
        TEST_R6_RELEASE_IRI
    )
    assert event["rkaf:effectiveDate"] == "2025-09-23T00:00:00Z"
    assert projection.source_date_literals == (
        "2024-09-23",
        "2025-09-23",
    )
    assert projection.date_materialization_policy.startswith(
        "urn:ref:elsst:policy:source-date-start-of-day-utc:"
    )
    assert nodes[ELSST_R5.concept_scheme_iri][
        DCTERMS_ISSUED_IRI
    ] == {
        "@value": "2024-09-23",
        "@language": "en",
    }
    assert nodes[ELSST_R6.concept_scheme_iri][
        DCTERMS_ISSUED_IRI
    ] == {
        "@value": "2025-09-23",
        "@language": "en",
    }
    assert nodes[projection.date_materialization_policy][
        "@type"
    ] == "rkaf:Artifact"
    assert projection.date_materialization_policy in nodes[
        projection.projection_activity_iri
    ]["prov:used"]


def test_fixture_projection_seals_both_releases_and_passes_pinned_rulespec(
    rulespec_dir: Path,
) -> None:
    previous, current, previous_release, current_release = _fixture_pair()
    validator = load_pinned_rulespec_validator(rulespec_dir)
    projection = build_elsst_rulespec_projection(
        previous,
        current,
        validator=validator,
        previous_release=previous_release,
        current_release=current_release,
    )

    sealed = seal_elsst_rulespec_projection(
        projection,
        validator=validator,
    )
    require_valid_elsst_rulespec_projection(
        sealed,
        validator=validator,
    )

    nodes = {node["@id"]: node for node in sealed.graph["@graph"]}
    digests = dict(sealed.release_digests)
    assert set(digests) == {
        TEST_R5_RELEASE_IRI,
        TEST_R6_RELEASE_IRI,
    }
    assert len(set(digests.values())) == 2
    for release_iri, digest in digests.items():
        assert nodes[release_iri]["rkaf:referenceReleaseDigest"] == (digest)


def test_projection_rejects_a_semantic_relation_outside_exact_release(
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    previous, _current, previous_release, current_release = _fixture_pair()
    source = R6_FIXTURE.read_text(encoding="utf-8").replace(
        ("skos:broader <https://elsst.cessda.eu/id/6/8a80f878-851c-4f47-a451-a8fe75b81aad>"),
        ("skos:broader <https://elsst.cessda.eu/id/5/8a80f878-851c-4f47-a451-a8fe75b81aad>"),
        1,
    )
    path = tmp_path / "cross-release.ttl"
    path.write_text(source, encoding="utf-8")
    changed_release = _fixture_release(
        path,
        version="6",
        release_iri=current_release.release_iri,
        scheme_iri=current_release.concept_scheme_iri,
    )
    changed = parse_elsst_file(
        path,
        source_url=changed_release.source_url,
        expected_sha256=changed_release.expected_sha256,
        expected_byte_length=changed_release.expected_byte_length,
    )
    validator = load_pinned_rulespec_validator(rulespec_dir)

    with pytest.raises(
        ElsstRulespecProjectionError,
        match="relation endpoint is not a member",
    ):
        build_elsst_rulespec_projection(
            previous,
            changed,
            validator=validator,
            previous_release=previous_release,
            current_release=changed_release,
        )


@pytest.mark.parametrize(
    ("authored_status", "expected_lexical"),
    [
        ("false", "false"),
        ('"0"^^xsd:boolean', "0"),
    ],
)
def test_projection_preserves_native_false_deprecation_without_lifecycle(
    rulespec_dir: Path,
    tmp_path: Path,
    authored_status: str,
    expected_lexical: str,
) -> None:
    previous, _current, previous_release, current_release = (
        _fixture_pair()
    )
    source = R6_FIXTURE.read_text(encoding="utf-8").replace(
        "owl:deprecated true",
        f"owl:deprecated {authored_status}",
        1,
    )
    path = tmp_path / f"false-{expected_lexical}.ttl"
    path.write_text(source, encoding="utf-8")
    changed_release = _fixture_release(
        path,
        version="6",
        release_iri=current_release.release_iri,
        scheme_iri=current_release.concept_scheme_iri,
    )
    changed = parse_elsst_file(
        path,
        source_url=changed_release.source_url,
        expected_sha256=changed_release.expected_sha256,
        expected_byte_length=changed_release.expected_byte_length,
    )
    projection = build_elsst_rulespec_projection(
        previous,
        changed,
        validator=load_pinned_rulespec_validator(rulespec_dir),
        previous_release=previous_release,
        current_release=changed_release,
    )
    nodes = {
        node["@id"]: node for node in projection.graph["@graph"]
    }

    assert nodes[R6_RETIRED]["owl:deprecated"] == expected_lexical
    assert projection.lifecycle_transitions == ()


def test_projection_preserves_native_boolean_one_as_true(
    rulespec_dir: Path,
    tmp_path: Path,
) -> None:
    previous, _current, previous_release, current_release = (
        _fixture_pair()
    )
    source = R6_FIXTURE.read_text(encoding="utf-8").replace(
        "owl:deprecated true",
        'owl:deprecated "1"^^xsd:boolean',
        1,
    )
    path = tmp_path / "true-one.ttl"
    path.write_text(source, encoding="utf-8")
    changed_release = _fixture_release(
        path,
        version="6",
        release_iri=current_release.release_iri,
        scheme_iri=current_release.concept_scheme_iri,
    )
    changed = parse_elsst_file(
        path,
        source_url=changed_release.source_url,
        expected_sha256=changed_release.expected_sha256,
        expected_byte_length=changed_release.expected_byte_length,
    )
    projection = build_elsst_rulespec_projection(
        previous,
        changed,
        validator=load_pinned_rulespec_validator(rulespec_dir),
        previous_release=previous_release,
        current_release=changed_release,
    )
    nodes = {
        node["@id"]: node for node in projection.graph["@graph"]
    }

    assert nodes[R6_RETIRED]["owl:deprecated"] == "1"
    assert len(projection.lifecycle_transitions) == 1


@pytest.mark.parametrize(
    "authored_status",
    [
        '"yes"^^xsd:boolean',
        '"true"^^xsd:string',
    ],
)
def test_projection_rejects_malformed_or_wrongly_typed_deprecation(
    rulespec_dir: Path,
    tmp_path: Path,
    authored_status: str,
) -> None:
    previous, _current, previous_release, current_release = (
        _fixture_pair()
    )
    source = R6_FIXTURE.read_text(encoding="utf-8").replace(
        "owl:deprecated true",
        f"owl:deprecated {authored_status}",
        1,
    )
    path = tmp_path / "invalid-status.ttl"
    path.write_text(source, encoding="utf-8")
    changed_release = _fixture_release(
        path,
        version="6",
        release_iri=current_release.release_iri,
        scheme_iri=current_release.concept_scheme_iri,
    )
    changed = parse_elsst_file(
        path,
        source_url=changed_release.source_url,
        expected_sha256=changed_release.expected_sha256,
        expected_byte_length=changed_release.expected_byte_length,
    )

    with pytest.raises(
        ElsstRulespecProjectionError,
        match="unsupported deprecation literal",
    ):
        build_elsst_rulespec_projection(
            previous,
            changed,
            validator=load_pinned_rulespec_validator(rulespec_dir),
            previous_release=previous_release,
            current_release=changed_release,
        )


def test_opt_in_projection_fixtures_are_subsets_of_pinned_sources() -> None:
    r5_path = os.environ.get("REFSPEC_ELSST_R5_PATH")
    r6_path = os.environ.get("REFSPEC_ELSST_R6_PATH")
    if r5_path is None or r6_path is None:
        pytest.skip("set both REFSPEC_ELSST_R5_PATH and REFSPEC_ELSST_R6_PATH")
    for fixture, source_path in (
        (R5_FIXTURE, Path(r5_path)),
        (R6_FIXTURE, Path(r6_path)),
    ):
        fixture_graph = Graph().parse(fixture, format="turtle")
        source_graph = Graph().parse(source_path, format="turtle")
        assert set(fixture_graph).issubset(set(source_graph))


def test_opt_in_full_r5_r6_projection_passes_rulespec(
    rulespec_dir: Path,
) -> None:
    r5_path = os.environ.get("REFSPEC_ELSST_R5_PATH")
    r6_path = os.environ.get("REFSPEC_ELSST_R6_PATH")
    if r5_path is None or r6_path is None:
        pytest.skip("set both REFSPEC_ELSST_R5_PATH and REFSPEC_ELSST_R6_PATH")
    previous = parse_elsst_file(
        Path(r5_path),
        source_url=ELSST_R5.source_url,
        expected_sha256=ELSST_R5.expected_sha256,
        expected_byte_length=ELSST_R5.expected_byte_length,
    )
    current = parse_elsst_file(
        Path(r6_path),
        source_url=ELSST_R6.source_url,
        expected_sha256=ELSST_R6.expected_sha256,
        expected_byte_length=ELSST_R6.expected_byte_length,
    )
    validator = load_pinned_rulespec_validator(rulespec_dir)

    projection = build_elsst_rulespec_projection(
        previous,
        current,
        validator=validator,
    )
    sealed = seal_elsst_rulespec_projection(
        projection,
        validator=validator,
    )
    require_valid_elsst_rulespec_projection(
        sealed,
        validator=validator,
    )

    native_concepts = [node for node in sealed.graph["@graph"] if node.get("@type") == "skos:Concept"]
    assert len(native_concepts) == 3_435 + 3_470
    assert len(sealed.lifecycle_transitions) == 3
    assert {transition.operation for transition in sealed.lifecycle_transitions} == {"replacement"}

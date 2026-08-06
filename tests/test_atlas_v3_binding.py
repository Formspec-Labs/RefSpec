from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.0"
VALIDATOR_PATH = BINDING_ROOT / "tools" / "validate.py"
FIXTURE_BUILDER = BINDING_ROOT / "tools" / "build_fixtures.py"
VALID_DISTRIBUTION = BINDING_ROOT / "fixtures" / "valid" / "all-resource-profiles"
REQUIREMENTS = BINDING_ROOT / "requirements.txt"
ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate


def _standalone(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with-requirements",
            str(REQUIREMENTS),
            "python",
            str(VALIDATOR_PATH),
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_atlas_v3_binding_and_sealed_corpus_pass() -> None:
    completed = _standalone()
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "caseCount": 57,
        "invalidCount": 52,
        "registryDescriptorCount": 88,
        "registryDescriptorQuadCount": 640,
        "schemaCount": 8,
    }


def test_all_resource_profiles_fixture_has_synthetic_semantic_coverage() -> None:
    completed = _standalone("--distribution", str(VALID_DISTRIBUTION))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["counts"] == {
        "crossRingRelationAssertions": 3,
        "derivedRelations": 1,
        "identifiers": 1,
        "labels": 10,
        "mappingAssertions": 2,
        "nativeRelationAssertions": 2,
        "projectedRelations": 10,
        "relationAssertions": 10,
        "releases": 8,
        "resources": 10,
        "sourceAssignments": 3,
        "sourceRecords": 10,
    }
    assert result["quadCount"] == 713
    assert result["inferredMappingCount"] == 7


def test_cross_ring_assertions_project_with_both_ring_directions() -> None:
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    graph_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    dataset = Dataset()
    dataset.parse(VALID_DISTRIBUTION / "atlas.nq", format="nquads")
    graphs = {
        role: Graph(identifier=graph_id)
        for role, graph_id in graph_ids.items()
    }
    for role, graph in graphs.items():
        for subject, predicate, obj, _ in dataset.quads(
            (None, None, None, graph_ids[role])
        ):
            graph.add((subject, predicate, obj))
    asserted = graphs["asserted"]
    projection = graphs["projection"]
    assertions = set(
        asserted.subjects(RDF.type, ATLAS.CrossRingRelationAssertion)
    )

    assert len(assertions) == 3
    assert {
        (
            asserted.value(assertion, ATLAS.sourceRing),
            asserted.value(assertion, RDF.predicate),
            asserted.value(assertion, ATLAS.targetRing),
        )
        for assertion in assertions
    } == {
        (ATLAS.entity, ATLAS.hasIndexedSubject, ATLAS.subject),
        (ATLAS.legalIdentity, ATLAS.hasIndexedSubject, ATLAS.subject),
        (ATLAS.entity, ATLAS.referencesLegalIdentity, ATLAS.legalIdentity),
    }
    for assertion in assertions:
        assert asserted.value(assertion, ATLAS.semanticRing) is None
        triple = (
            asserted.value(assertion, RDF.subject),
            asserted.value(assertion, RDF.predicate),
            asserted.value(assertion, RDF.object),
        )
        assert triple in projection
        projected = list(projection.subjects(ATLAS.supportingAssertion, assertion))
        assert len(projected) == 1
        record = projected[0]
        assert projection.value(record, ATLAS.sourceRing) == asserted.value(
            assertion, ATLAS.sourceRing
        )
        assert projection.value(record, ATLAS.targetRing) == asserted.value(
            assertion, ATLAS.targetRing
        )
        assert projection.value(record, ATLAS.semanticRing) is None


def test_exact_match_entailment_does_not_become_an_editorial_assertion() -> None:
    manifest = json.loads((VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    dataset = Dataset()
    dataset.parse(VALID_DISTRIBUTION / "atlas.nq", format="nquads")
    graphs: dict[str, Graph] = {}
    for role, graph_id in graph_ids.items():
        graph = Graph(identifier=graph_id)
        for subject, predicate, obj, _ in dataset.quads((None, None, None, graph_id)):
            graph.add((subject, predicate, obj))
        graphs[role] = graph
    source = URIRef("urn:ref:atlas-fixture:resource:subject-a")
    target = URIRef("urn:ref:atlas-fixture:resource:subject-c")

    assert (source, SKOS.exactMatch, target) not in graphs["projection"]
    assert any(
        graphs["derived"].value(node, ATLAS.relationSubject) == source
        and graphs["derived"].value(node, ATLAS.relationPredicate) == SKOS.exactMatch
        and graphs["derived"].value(node, ATLAS.relationObject) == target
        and graphs["derived"].value(node, ATLAS.authorityStatus) == ATLAS.nonAuthoritative
        for node in graphs["derived"].subjects(RDF.type, ATLAS.DerivedRelation)
    )
    assert not any(
        graphs["asserted"].value(assertion, RDF.subject) == source
        and graphs["asserted"].value(assertion, RDF.predicate) == SKOS.exactMatch
        and graphs["asserted"].value(assertion, RDF.object) == target
        for assertion in graphs["asserted"].subjects(RDF.type, ATLAS.MappingAssertion)
    )


def test_ontology_uses_the_declared_safe_local_profile() -> None:
    graph = Graph().parse(BINDING_ROOT / "ontology" / "atlas.ttl", format="turtle")

    forbidden_types = {
        OWL.FunctionalProperty,
        OWL.InverseFunctionalProperty,
        OWL.TransitiveProperty,
        OWL.SymmetricProperty,
        OWL.Restriction,
    }
    assert not any(
        any(graph.triples((None, RDF.type, value))) for value in forbidden_types
    )
    assert not any(graph.triples((None, OWL.propertyChainAxiom, None)))
    assert not any(
        str(subject).startswith(str(SKOS)) or str(subject).startswith(str(SKOSXL))
        for subject in graph.subjects()
    )

    graph.add((ATLAS.injected, OWL.inverseOf, ATLAS.other))
    with pytest.raises(atlas_validate.AtlasValidationError, match="ontology.profile"):
        atlas_validate._lint_ontology(graph)


def test_review_methods_describe_warrant_basis_without_product_permission() -> None:
    graph = Graph().parse(BINDING_ROOT / "ontology" / "atlas.ttl", format="turtle")
    expected = {
        ATLAS.deterministicTransformation,
        ATLAS.humanReview,
        ATLAS.operatorAdoption,
        ATLAS.publisherAssertion,
        ATLAS.trustedPipelineReview,
        ATLAS.twoMachineAdjudication,
    }

    assert set(graph.subjects(RDF.type, ATLAS.ReviewMethod)) == expected
    assert atlas_validate.REVIEW_METHODS == expected
    assert not any(
        keyword in str(term).lower()
        for term in graph.all_nodes()
        for keyword in ("ceiling", "eligibility", "searchonly", "usagepermission")
    )


def test_canonical_rdf_renderer_escapes_terms_without_false_blank_nodes() -> None:
    literal = Literal('line one\nline\ttwo "quoted" — café _:not-a-node', lang="en")
    assert atlas_validate.ntriples_term(literal) == (
        '"line one\\nline\\ttwo \\"quoted\\" — café _:not-a-node"@en'
    )
    dataset_text = (VALID_DISTRIBUTION / "atlas.nq").read_text(encoding="utf-8")
    assert "\\nline\\ttwo" in dataset_text
    assert '\\"quoted\\"' in dataset_text
    assert "_:not-a-node" in dataset_text


def test_multi_ring_scheme_is_selected_by_ring_specific_releases() -> None:
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    asserted_id = URIRef(
        next(row["id"] for row in manifest["graphs"] if row["role"] == "asserted")
    )
    dataset = Dataset()
    dataset.parse(VALID_DISTRIBUTION / "atlas.nq", format="nquads")
    asserted = Graph(identifier=asserted_id)
    for subject, predicate, obj, _ in dataset.quads((None, None, None, asserted_id)):
        asserted.add((subject, predicate, obj))
    scheme = URIRef("urn:ref:atlas-fixture:scheme:mixed-code")

    assert set(asserted.objects(scheme, ATLAS.supportedRing)) == {
        ATLAS.subject,
        ATLAS.value,
    }
    assert not list(asserted.objects(scheme, ATLAS.semanticRing))
    assert (scheme, RDF.type, SKOS.ConceptScheme) in asserted
    release_rings = {
        asserted.value(release, ATLAS.semanticRing)
        for release in asserted.subjects(ATLAS.inScheme, scheme)
        if (release, RDF.type, ATLAS.AtlasRelease) in asserted
    }
    assert release_rings == {ATLAS.subject, ATLAS.value}


def test_supersession_projects_only_the_terminal_current_claim() -> None:
    distribution = (
        BINDING_ROOT / "fixtures" / "valid" / "superseded-policy-revision"
    )
    completed = _standalone("--distribution", str(distribution))
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    dataset = Dataset()
    dataset.parse(distribution / "atlas.nq", format="nquads")
    asserted = Graph(identifier=graph_ids["asserted"])
    projection = Graph(identifier=graph_ids["projection"])
    for role, graph in (("asserted", asserted), ("projection", projection)):
        for subject, predicate, obj, _ in dataset.quads(
            (None, None, None, graph_ids[role])
        ):
            graph.add((subject, predicate, obj))
    old = next(asserted.subjects(ATLAS.assertionStatus, ATLAS.superseded))
    successor = next(asserted.subjects(ATLAS.supersedes, old))

    assert (successor, ATLAS.assertionStatus, ATLAS.current) in asserted
    assert old not in set(projection.objects(None, ATLAS.supportingAssertion))
    assert successor in set(projection.objects(None, ATLAS.supportingAssertion))


def test_assertion_identity_independently_excludes_lifecycle_and_evidence() -> None:
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    asserted_id = URIRef(
        next(row["id"] for row in manifest["graphs"] if row["role"] == "asserted")
    )
    dataset = Dataset()
    dataset.parse(VALID_DISTRIBUTION / "atlas.nq", format="nquads")
    asserted = Graph(identifier=asserted_id)
    for subject, predicate, obj, _ in dataset.quads((None, None, None, asserted_id)):
        asserted.add((subject, predicate, obj))
    assertion = next(asserted.subjects(RDF.type, ATLAS.MappingAssertion))
    policy = asserted.value(assertion, ATLAS.governedByPolicy)
    basis = {
        "object": str(asserted.value(assertion, RDF.object)),
        "policy": str(policy),
        "policyContentDigest": str(asserted.value(policy, ATLAS.contentDigest)),
        "predicate": str(asserted.value(assertion, RDF.predicate)),
        "semanticRing": str(asserted.value(assertion, ATLAS.semanticRing)),
        "sourceRelease": str(asserted.value(assertion, ATLAS.sourceRelease)),
        "subject": str(asserted.value(assertion, RDF.subject)),
        "targetRelease": str(asserted.value(assertion, ATLAS.targetRelease)),
        "type": str(ATLAS.MappingAssertion),
    }
    payload = (
        json.dumps(
            basis,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    assert asserted.value(assertion, ATLAS.assertionIdentityDigest) == Literal(digest)
    assert str(assertion) == "urn:ref:atlas-assertion:" + digest.removeprefix("sha256:")
    assert not ({"assertedAt", "status", "supersedes", "evidence"} & basis.keys())


def test_cross_ring_assertion_identity_uses_both_directed_rings() -> None:
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    asserted_id = URIRef(
        next(row["id"] for row in manifest["graphs"] if row["role"] == "asserted")
    )
    dataset = Dataset()
    dataset.parse(VALID_DISTRIBUTION / "atlas.nq", format="nquads")
    asserted = Graph(identifier=asserted_id)
    for subject, predicate, obj, _ in dataset.quads((None, None, None, asserted_id)):
        asserted.add((subject, predicate, obj))
    assertion = next(
        asserted.subjects(RDF.type, ATLAS.CrossRingRelationAssertion)
    )
    policy = asserted.value(assertion, ATLAS.governedByPolicy)
    basis = {
        "object": str(asserted.value(assertion, RDF.object)),
        "policy": str(policy),
        "policyContentDigest": str(asserted.value(policy, ATLAS.contentDigest)),
        "predicate": str(asserted.value(assertion, RDF.predicate)),
        "sourceRelease": str(asserted.value(assertion, ATLAS.sourceRelease)),
        "sourceRing": str(asserted.value(assertion, ATLAS.sourceRing)),
        "subject": str(asserted.value(assertion, RDF.subject)),
        "targetRelease": str(asserted.value(assertion, ATLAS.targetRelease)),
        "targetRing": str(asserted.value(assertion, ATLAS.targetRing)),
        "type": str(ATLAS.CrossRingRelationAssertion),
    }
    payload = (
        json.dumps(
            basis,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    assert asserted.value(assertion, ATLAS.assertionIdentityDigest) == Literal(digest)
    assert str(assertion) == "urn:ref:atlas-assertion:" + digest.removeprefix("sha256:")
    assert "semanticRing" not in basis


def test_fixture_corpus_rebuild_is_exact() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with-requirements",
            str(REQUIREMENTS),
            "python",
            str(FIXTURE_BUILDER),
            "--check",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_portable_validator_does_not_import_refspec() -> None:
    source = VALIDATOR_PATH.read_text(encoding="utf-8")
    assert "import refspec" not in source
    assert "from refspec" not in source

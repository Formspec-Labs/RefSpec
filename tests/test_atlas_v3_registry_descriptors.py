from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from pyshacl import validate as shacl_validate
from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "generate_atlas_v3_registry_descriptors.py"
CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"
INDEX = ROOT / "portfolio" / "atlas-index-v0.json"
PROFILES = ROOT / "bindings" / "atlas" / "3.1" / "registry-resource-profiles.json"
DATASET_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tests" / "registry-descriptors.nq"
PROOF_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tests" / "registry-descriptors.json"
ONTOLOGY_PATH = ROOT / "bindings" / "atlas" / "3.1" / "ontology" / "atlas.ttl"
SHAPES_PATH = ROOT / "bindings" / "atlas" / "3.1" / "shapes" / "atlas.shacl.ttl"
sys.path.insert(0, str(ROOT / "bindings" / "atlas" / "3.1" / "tools"))
import validate as atlas_validate

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
GRAPH_IRI = URIRef("urn:ref:atlas-v3:registry-descriptors")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _file_sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _input_digest(document: dict, digest_field: str, identity_field: str | None) -> str:
    excluded = {digest_field}
    if identity_field is not None:
        excluded.add(identity_field)
    return _canonical_sha256({key: value for key, value in document.items() if key not in excluded})


def _node_digest(graph, node: URIRef) -> str:
    statements = sorted(
        f"{predicate.n3()} {obj.n3()} ."
        for predicate, obj in graph.predicate_objects(node)
        if predicate != ATLAS.contentDigest
    )
    return "sha256:" + hashlib.sha256(("\n".join(statements) + "\n").encode("utf-8")).hexdigest()


def test_descriptor_proof_pins_exact_registry_inputs_and_output() -> None:
    catalog = _load(CATALOG)
    index = _load(INDEX)
    profiles = _load(PROFILES)
    proof = _load(PROOF_PATH)
    dataset_bytes = DATASET_PATH.read_bytes()

    assert PROOF_PATH.read_bytes() == _canonical_json_bytes(proof) + b"\n"
    proof_basis = {key: value for key, value in proof.items() if key != "proofDigest"}
    assert proof["proofDigest"] == _canonical_sha256(proof_basis)
    assert proof["format"] == "refspec-atlas-registry-descriptors/3.1"
    assert proof["schemaVersion"] == "3.1"
    assert proof["graphIri"] == str(GRAPH_IRI)

    assert catalog["catalogDigest"] == _input_digest(catalog, "catalogDigest", "catalogId")
    assert index["indexDigest"] == _input_digest(index, "indexDigest", "indexId")
    assert profiles["profileDigest"] == _input_digest(profiles, "profileDigest", None)
    assert proof["inputs"] == {
        "atlasIndexDigest": index["indexDigest"],
        "registryResourceProfilesDigest": profiles["profileDigest"],
        "resourceCatalogDigest": catalog["catalogDigest"],
    }
    assert index["resourceCatalogDigest"] == catalog["catalogDigest"]

    assert proof["artifact"] == {
        "byteLength": len(dataset_bytes),
        "path": "registry-descriptors.nq",
        "sha256": _file_sha256(dataset_bytes),
    }
    resource_ids = sorted(resource["resourceId"] for resource in catalog["resources"])
    assert len(resource_ids) == len(set(resource_ids)) == 116
    assert len(index["rows"]) == 112
    assert proof["resourceIdSetDigest"] == _canonical_sha256(resource_ids)
    # REF-034: the retired AGROVOC and NALT rows and the closed EPA row left
    # the catalog (89 -> 87, three concept schemes with them); the GAO CRA
    # submission-form row joined; four index placements landed for the
    # documented successors. REF-035 through REF-037 add the mapping-only and
    # contentful endpoint descriptors recorded by the acquisition wave.
    # REF-047 adds the OFR CFR List of Subjects part index: one more registry
    # source, one more scheme, one more legal-identity index placement, and one
    # more member release.
    assert proof["counts"] == {
        "atlasIndexPlacementCount": 112,
        "conceptSchemeCount": 41,
        "memberDispositionCounts": {
            "assignmentEvidenceOnly": 4,
            "childReleaseOnly": 6,
            "definitionOnly": 1,
            "historicalEvidenceOnly": 2,
            "memberRelease": 87,
            "mappingAssertionsOnly": 11,
            "noPublisherRecord": 3,
            "resourceFamily": 1,
            "reviewWithheld": 1,
        },
        "quadCount": 1241,
        "registrySourceCount": 116,
        "resourceSchemeCount": 105,
        "supportedRingStatementCount": 95,
    }


def test_descriptor_canonicalization_inspects_terms_not_literal_text() -> None:
    text = (
        "<urn:ref:test:scheme> <https://refspec.org/ns/atlas/v3#descriptorPayload> "
        '"{\\"marker\\":\\"_:not-a-node\\"}"^^'
        "<http://www.w3.org/1999/02/22-rdf-syntax-ns#JSON> <urn:ref:test:graph> .\n"
    )
    dataset = Dataset()
    dataset.parse(data=text, format="nquads")

    assert (
        atlas_validate._canonical_dataset_lines(
            dataset,
            blank_node_code="test.blank-node",
            blank_node_detail="unexpected blank node",
        )
        == text.splitlines()
    )


def test_every_catalog_row_has_one_source_and_member_sources_have_schemes() -> None:
    catalog = _load(CATALOG)
    index = _load(INDEX)
    profiles = _load(PROFILES)
    proof = _load(PROOF_PATH)
    raw_dataset = DATASET_PATH.read_bytes()
    lines = raw_dataset.decode("utf-8").splitlines()

    assert raw_dataset.endswith(b"\n")
    assert lines == sorted(lines)
    assert len(lines) == len(set(lines)) == proof["counts"]["quadCount"]

    parsed = Dataset()
    parsed.parse(DATASET_PATH, format="nquads")
    nonempty_graphs = {graph.identifier for graph in parsed.graphs() if len(graph)}
    assert nonempty_graphs == {GRAPH_IRI}
    graph = parsed.graph(GRAPH_IRI)
    assert len(graph) == proof["counts"]["quadCount"]
    assert not any(isinstance(term, BNode) for subject, predicate, obj in graph for term in (subject, predicate, obj))

    profile_for_kind: dict[str, str] = {}
    supported_by_profile: dict[str, set[str]] = {}
    for profile in profiles["profiles"]:
        profile_name = profile["profile"]
        supported_by_profile[profile_name] = set(profile["applicableSemanticRings"])
        for resource_kind in profile["resourceKinds"]:
            assert resource_kind not in profile_for_kind
            profile_for_kind[resource_kind] = profile_name

    rings_by_resource: dict[str, set[str]] = defaultdict(set)
    for row in index["rows"]:
        rings_by_resource[row["resourceId"]].add(row["semanticRing"])
    assert sum(len(rings) for rings in rings_by_resource.values()) == 106

    resources = {resource["resourceId"]: resource for resource in catalog["resources"]}
    scheme_nodes = set(graph.subjects(RDF.type, ATLAS.ResourceScheme))
    source_nodes = set(graph.subjects(RDF.type, ATLAS.RegistrySource))
    assert len(scheme_nodes) == len(resources) - 11 == 105
    assert len(source_nodes) == len(resources) == 116
    for resource_id, resource in resources.items():
        node = URIRef("urn:ref:atlas-resource-scheme:" + quote(resource_id, safe="-._~"))
        source = URIRef("urn:ref:atlas-source-descriptor:" + quote(resource_id, safe="-._~"))
        assert source in source_nodes
        profile = profile_for_kind[resource["resourceKind"]]
        expected_rings = rings_by_resource.get(resource_id, set())
        assert expected_rings <= supported_by_profile[profile]

        if resource_id in {
            "eurovoc-gemet-alignment",
            "eurovoc-lcsh-alignment",
            "eurovoc-mesh-alignment",
            "fast-bulk-external-links-delta",
            "fast-lcsh-adopted-mapping",
            "gemet-alignments",
            "gemet-umthes-alignments",
            "lcsh-external-links-mapping",
            "northwestern-mesh-lcsh-mapping",
            "regulations-gov-agency-identity",
            "unified-agenda-gao-cra-priority-mapping",
        }:
            assert node not in scheme_nodes
        else:
            assert node in scheme_nodes

        if node in scheme_nodes:
            assert list(graph.objects(node, DCTERMS.identifier)) == [Literal(resource_id)]
            assert list(graph.objects(node, DCTERMS.title)) == [Literal(resource["title"])]
            assert list(graph.objects(node, ATLAS.resourceProfile)) == [ATLAS[profile]]
            assert list(graph.objects(node, ATLAS.sourceDescriptor)) == [source]
            assert set(graph.objects(node, ATLAS.supportedRing)) == {ATLAS[ring] for ring in expected_rings}

            types = set(graph.objects(node, RDF.type))
            assert ATLAS.ResourceScheme in types
            assert (SKOS.ConceptScheme in types) is (profile == "conceptScheme" or "subject" in expected_rings)

        assert not list(graph.objects(node, ATLAS.descriptorPayload))
        assert list(graph.objects(source, DCTERMS.identifier)) == [Literal(resource_id)]
        assert list(graph.objects(source, DCTERMS.title)) == [Literal(resource["title"])]
        disposition = {
            "eurovoc-gemet-alignment": "mappingAssertionsOnly",
            "eurovoc-lcsh-alignment": "mappingAssertionsOnly",
            "eurovoc-mesh-alignment": "mappingAssertionsOnly",
            "fast-bulk-external-links-delta": "mappingAssertionsOnly",
            "fast-lcsh-adopted-mapping": "mappingAssertionsOnly",
            "federal-register-thesaurus-1995": "historicalEvidenceOnly",
            "gao-thesaurus-historical": "historicalEvidenceOnly",
            "gemet-alignments": "mappingAssertionsOnly",
            "gemet-umthes-alignments": "mappingAssertionsOnly",
            "lcsh-external-links-mapping": "mappingAssertionsOnly",
            "northwestern-mesh-lcsh-mapping": "mappingAssertionsOnly",
            "regulations-gov-agency-identity": "mappingAssertionsOnly",
            "unified-agenda-gao-cra-priority-mapping": ("mappingAssertionsOnly"),
        }.get(resource_id)
        observed_dispositions = list(graph.objects(source, ATLAS.memberDisposition))
        assert len(observed_dispositions) == 1
        if disposition is not None:
            assert observed_dispositions == [Literal(disposition)]
        payloads = list(graph.objects(source, ATLAS.descriptorPayload))
        assert len(payloads) == 1
        payload = payloads[0]
        assert isinstance(payload, Literal)
        assert payload.datatype == RDF.JSON
        assert str(payload).encode("utf-8") == _canonical_json_bytes(resource)
        assert json.loads(str(payload)) == resource

        # `atlas:contentDigest` left the descriptor wire: neither a registry
        # source nor a resource scheme derives identity from it, so neither
        # publishes it and the closed shapes refuse it.
        assert list(graph.objects(node, ATLAS.contentDigest)) == []
        assert list(graph.objects(source, ATLAS.contentDigest)) == []

    assert len(set(graph.subjects(RDF.type, SKOS.ConceptScheme))) == 41
    assert len(list(graph.triples((None, ATLAS.supportedRing, None)))) == 95


def test_checked_descriptor_bytes_are_exactly_regenerable() -> None:
    spec = importlib.util.spec_from_file_location("generate_atlas_v3_registry_descriptors", TOOL)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    generated_dataset, generated_proof = generator.build_registry_descriptors(
        _load(CATALOG),
        _load(INDEX),
        _load(PROFILES),
    )
    assert generated_dataset == DATASET_PATH.read_bytes()
    assert generated_proof == PROOF_PATH.read_bytes()

    completed = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout == (
        "Atlas 3.1 registry descriptors are current: 105 schemes, 112 index placements, 1241 quads\n"
    )


def test_real_registry_descriptors_conform_to_atlas_shacl() -> None:
    dataset = Dataset()
    dataset.parse(DATASET_PATH, format="nquads")
    graph = Graph(identifier=GRAPH_IRI)
    for subject, predicate, obj, _ in dataset.quads((None, None, None, GRAPH_IRI)):
        graph.add((subject, predicate, obj))
    ontology = Graph().parse(ONTOLOGY_PATH, format="turtle")
    shapes = Graph().parse(SHAPES_PATH, format="turtle")

    conforms, _, report = shacl_validate(
        graph,
        shacl_graph=shapes,
        ont_graph=ontology,
        inference="none",
        advanced=True,
        meta_shacl=True,
    )

    assert conforms, report

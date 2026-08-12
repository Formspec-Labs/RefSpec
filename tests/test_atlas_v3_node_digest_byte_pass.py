"""Parity proof for the node digests taken off the canonical pack bytes.

`rdf_node_digest` renders a node's outgoing facts back into N-Triples from an
rdflib store and hashes the sorted lines. `_AssertedNodeDigests` accumulates the
same digest from the pack bytes as the profile reader validates them -- no
store, no term model -- which is only sound because the packs are sorted,
subject-contiguous, and already proved canonical line by line.

"Only sound because" is an argument, so this is the check. Every node the byte
pass retained is compared against the graph-rendered digest, and the retention
rule is held to what the distribution-scale gates actually consult: every
`atlas:SourceRecord` and every `rkaf:EvidenceBinding` in the fixture
distribution must be present, because those two are what the ~150s of the
acceptance run this replaces was spent on.

The substrate spike this ports measured the same comparison at 104,898/104,898
on real packs; what is committed here is the version that runs on every suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from rdflib import Namespace, URIRef
from rdflib.namespace import RDF

ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = ROOT / "bindings" / "atlas" / "3.1"
VALID_DISTRIBUTION = BINDING_ROOT / "fixtures" / "valid" / "all-resource-profiles"
ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
RKAF = Namespace("https://rulespec.org/ns/v1#")
sys.path.insert(0, str(BINDING_ROOT / "tools"))
import validate as atlas_validate


def _parse_with_byte_pass():
    if not (VALID_DISTRIBUTION / "atlas-manifest.json").is_file():
        pytest.skip("Atlas 3.1 fixtures are not materialized; run make atlas-v3-fixtures")
    manifest = json.loads(
        (VALID_DISTRIBUTION / "atlas-manifest.json").read_text(encoding="utf-8")
    )
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    digests = atlas_validate._AssertedNodeDigests(graph_ids["asserted"])
    dataset, graphs = atlas_validate._parse_packed_dataset(
        VALID_DISTRIBUTION,
        manifest,
        graph_ids,
        node_digests=digests,
    )
    return dataset, graphs["asserted"], digests


def test_byte_pass_node_digests_equal_the_graph_rendered_ones() -> None:
    dataset, asserted, digests = _parse_with_byte_pass()
    try:
        assert len(digests), "the byte pass retained no node at all"
        mismatched: list[tuple[str, str, str]] = []
        for node in sorted(set(asserted.subjects(unique=True)), key=str):
            observed = digests.get(node)
            if observed is None:
                continue
            expected = atlas_validate.rdf_node_digest(asserted, node)
            if observed != expected:
                mismatched.append((str(node), expected, observed))
        assert not mismatched, mismatched[:3]
    finally:
        del dataset


def test_byte_pass_retains_every_node_the_scale_gates_digest() -> None:
    """Missing entries are only slow, but they are what the port bought."""

    dataset, asserted, digests = _parse_with_byte_pass()
    try:
        for carrier in (ATLAS.SourceRecord, RKAF.EvidenceBinding):
            nodes = set(asserted.subjects(RDF.type, carrier))
            assert nodes, f"the fixture distribution carries no {carrier}"
            missing = sorted(str(node) for node in nodes if digests.get(node) is None)
            assert not missing, f"{carrier} nodes absent from the byte pass: {missing[:3]}"
    finally:
        del dataset


def test_a_node_the_byte_pass_did_not_retain_falls_back_to_the_graph() -> None:
    """The pass is an accelerator; the graph stays the authority behind it."""

    dataset, asserted, digests = _parse_with_byte_pass()
    try:
        unretained = next(
            node
            for node in sorted(set(asserted.subjects(unique=True)), key=str)
            if digests.get(node) is None
        )
        assert atlas_validate._node_digest(
            asserted, unretained, digests
        ) == atlas_validate.rdf_node_digest(asserted, unretained)
        absent = URIRef("urn:ref:atlas-test:not-in-this-distribution")
        assert digests.get(absent) is None
    finally:
        del dataset

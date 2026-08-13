from __future__ import annotations

import ast
import sys
from pathlib import Path

from rdflib import URIRef
from rdflib.namespace import RDF, SH

ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "bindings" / "atlas" / "3.1"
sys.path.insert(0, str(BINDING / "tools"))
import validate as atlas_validate

EXPECTED_SHAPES = {
    URIRef("https://rulespec.org/ns/v1#" + local)
    for local in (
        "MachineAdjudicationFiveAxisIndependenceShape",
        "MachineAdjudicationIssuedProofCitationShape",
        "MachineAdjudicationVerdictLatticeFoldShape",
        "MachineAdjudicationProofReplayShape",
    )
}


def test_binding_loads_the_four_compiler_emitted_shapes_as_local_data() -> None:
    atlas_validate._check_rulespec_shapes_lock()
    _, shapes = atlas_validate._parse_binding_graphs()
    observed = set(shapes.subjects(RDF.type, SH.NodeShape))
    assert EXPECTED_SHAPES <= observed


def test_rulespec_shape_data_and_lock_are_part_of_contract_identity() -> None:
    baseline = atlas_validate._binding_digests()["contractDigest"]
    for relative in (
        Path("shapes/rulespec-adjudication.shacl.ttl"),
        Path("shapes/rulespec-adjudication.lock.json"),
    ):
        changed = (BINDING / relative).read_bytes() + b"\n"
        assert (
            atlas_validate._binding_digests(content_overrides={relative: changed})[
                "contractDigest"
            ]
            != baseline
        )


def test_copy_and_run_validator_imports_no_rulespec_or_refspec_package() -> None:
    source = (BINDING / "tools" / "validate.py").read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "refspec" not in imported
    assert "rulespec_conformance" not in imported

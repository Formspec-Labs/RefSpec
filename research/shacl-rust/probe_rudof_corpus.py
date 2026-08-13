#!/usr/bin/env python3
"""Compare Rudof with the 48 SHACL-owned Atlas 3.1 corpus refusals."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pyshacl import validate as pyshacl_validate
from pyshacl.rdfutil import inoculate
from rdflib import RDF, Dataset, Graph, Literal, Namespace, URIRef

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # Python 3.10-3.13
    from backports import zstd


SH = Namespace("http://www.w3.org/ns/shacl#")
ROLE_ORDER = ("asserted", "derived")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_report(stdout: str) -> tuple[bool | None, list[str]]:
    try:
        report = Graph().parse(data=stdout, format="turtle")
    except Exception:  # noqa: BLE001 - a malformed candidate report is probe data
        return None, []
    report_node = next(report.subjects(RDF.type, SH.ValidationReport), None)
    conforms: bool | None = None
    if report_node is not None:
        value = next(report.objects(report_node, SH.conforms), None)
        if isinstance(value, Literal) and isinstance(value.value, bool):
            conforms = value.value
    components = sorted(
        {
            str(component).removeprefix(str(SH))
            for component in report.objects(None, SH.sourceConstraintComponent)
        }
    )
    return conforms, components


def _load_role_graphs(case_root: Path, manifest: dict[str, Any]) -> tuple[Dataset, dict[str, Graph]]:
    dataset = Dataset()
    for pack in manifest["packs"]:
        path = case_root / pack["path"]
        compression = pack["transport"]["compression"]
        if compression == "none":
            dataset.parse(path, format="nquads")
        elif compression == "zstd":
            dataset.parse(data=zstd.decompress(path.read_bytes()), format="nquads")
        else:
            raise ValueError(f"{case_root}: unsupported pack compression {compression!r}")
    graphs = {
        row["role"]: dataset.graph(URIRef(row["id"]))
        for row in manifest["graphs"]
    }
    for row in manifest["graphs"]:
        actual = len(graphs[row["role"]])
        if actual != row["quadCount"]:
            raise ValueError(
                f"{case_root}: {row['role']} has {actual} quads; manifest declares {row['quadCount']}"
            )
    return dataset, graphs


def _validation_view(role_graph: Graph, ontology_view: Graph) -> Graph:
    view = Graph()
    for triple in role_graph:
        view.add(triple)
    for triple in ontology_view:
        view.add(triple)
    return view


def _run_role(
    rudof: Path,
    shapes_path: Path,
    ontology_view: Graph,
    role_graph: Graph,
    role: str,
    directory: Path,
) -> dict[str, Any]:
    validation_view = _validation_view(role_graph, ontology_view)
    data_path = directory / f"{role}.nt"
    validation_view.serialize(destination=data_path, format="nt", encoding="utf-8")
    command = [
        str(rudof),
        "shacl-validate",
        "-t",
        "ntriples",
        "-s",
        str(shapes_path),
        "-f",
        "turtle",
        "-r",
        "turtle",
        "--sort_by",
        "component",
        str(data_path),
    ]
    started = time.monotonic()
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    conforms, components = _read_report(completed.stdout)
    return {
        "command": command,
        "components": components,
        "conforms": conforms,
        "elapsedSeconds": round(elapsed, 6),
        "ontologyViewTripleCount": len(ontology_view),
        "returnCode": completed.returncode,
        "role": role,
        "roleGraphTripleCount": len(role_graph),
        "stderr": completed.stderr,
        "stdout": completed.stdout,
        "validationViewTripleCount": len(validation_view),
    }


def _reference_report_structure(shapes: Graph, ontology_view: Graph, role_graph: Graph) -> dict[str, Any]:
    validation_view = _validation_view(role_graph, ontology_view)
    conforms, report, _ = pyshacl_validate(
        validation_view,
        shacl_graph=shapes,
        inference="none",
        inplace=True,
        advanced=False,
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
    )
    report_node = next(report.subjects(RDF.type, SH.ValidationReport), None)
    top_level = list(report.objects(report_node, SH.result)) if report_node is not None else []
    all_results = set(report.subjects(RDF.type, SH.ValidationResult))

    def components(nodes: Any) -> list[str]:
        return sorted(
            {
                str(component).removeprefix(str(SH))
                for node in nodes
                for component in report.objects(node, SH.sourceConstraintComponent)
            }
        )

    details = []
    for parent in top_level:
        children = list(report.objects(parent, SH.detail))
        if children:
            details.append(
                {
                    "detailComponents": components(children),
                    "parentComponents": components([parent]),
                }
            )
    return {
        "allResultComponents": components(all_results),
        "allResultCount": len(all_results),
        "conforms": bool(conforms),
        "detailLinks": details,
        "reportTurtle": report.serialize(format="turtle"),
        "topLevelComponents": components(top_level),
        "topLevelResultCount": len(top_level),
    }


def _probe_case(
    rudof: Path,
    binding_root: Path,
    ontology_view: Graph,
    shapes: Graph,
    atlas_validate: Any,
    case: dict[str, Any],
) -> dict[str, Any]:
    case_root = binding_root / "fixtures" / case["path"]
    manifest = json.loads((case_root / "atlas-manifest.json").read_bytes())
    dataset, graphs = _load_role_graphs(case_root, manifest)
    graph_ids = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    reference_dataset, reference_graphs = atlas_validate._parse_packed_dataset(
        case_root,
        manifest,
        graph_ids,
    )
    for role in ("asserted", "projection", "derived"):
        if set(graphs[role]) != set(reference_graphs[role]):
            raise ValueError(f"{case_root}: probe and production parsers differ for {role}")
    del reference_dataset
    role_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"rudof-corpus-{case['id']}-") as temporary:
        for role in ROLE_ORDER:
            result = _run_role(
                rudof,
                binding_root / "shapes" / "atlas.shacl.ttl",
                ontology_view,
                graphs[role],
                role,
                Path(temporary),
            )
            role_results.append(result)
            if result["returnCode"] != 0 or result["conforms"] is not True:
                break
    del dataset

    first = role_results[-1]
    candidate_error = first["returnCode"] != 0 or first["conforms"] is None
    actual_expected = "error" if candidate_error else ("valid" if first["conforms"] else "invalid")
    actual_components = first["components"] if actual_expected == "invalid" else []
    expected_components = case.get("shaclComponents", [])
    agreement = actual_expected == case["expected"] and actual_components == expected_components
    result = {
        "actual": {
            "expected": actual_expected,
            "firstIssue": "shacl.data" if actual_expected == "invalid" else None,
            "shaclComponents": actual_components,
        },
        "agreement": agreement,
        "expected": {
            "expected": case["expected"],
            "firstIssue": case.get("firstIssue"),
            "shaclComponents": expected_components,
        },
        "graphIds": {row["role"]: row["id"] for row in manifest["graphs"]},
        "id": case["id"],
        "path": case["path"],
        "projectionExcluded": True,
        "productionParserParity": True,
        "roleResults": role_results,
    }
    if not agreement and not candidate_error:
        result["referenceReportStructure"] = _reference_report_structure(
            shapes,
            ontology_view,
            graphs[first["role"]],
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rudof", type=Path, required=True)
    parser.add_argument("--binding-root", type=Path, default=Path("bindings/atlas/3.1"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rudof = args.rudof.resolve()
    binding_root = args.binding_root.resolve()
    sys.path.insert(0, str(binding_root / "tools"))
    atlas_validate = importlib.import_module("validate")
    corpus_path = binding_root / "fixtures" / "corpus.json"
    shapes_path = binding_root / "shapes" / "atlas.shacl.ttl"
    ontology_path = binding_root / "ontology" / "atlas.ttl"
    corpus = json.loads(corpus_path.read_bytes())
    shacl_cases = [case for case in corpus["cases"] if case.get("firstIssue") == "shacl.data"]
    valid_cases = [case for case in corpus["cases"] if case["expected"] == "valid"]
    if len(shacl_cases) != 48:
        raise ValueError(f"expected 48 SHACL-owned cases, found {len(shacl_cases)}")
    if len(valid_cases) != 13:
        raise ValueError(f"expected 13 valid controls, found {len(valid_cases)}")

    ontology = Graph().parse(ontology_path, format="turtle")
    ontology_view = inoculate(Graph(), ontology)
    shapes = Graph().parse(shapes_path, format="turtle")
    started = time.monotonic()
    results = [
        _probe_case(rudof, binding_root, ontology_view, shapes, atlas_validate, case)
        for case in shacl_cases
    ]
    valid_controls = [
        _probe_case(rudof, binding_root, ontology_view, shapes, atlas_validate, case)
        for case in valid_cases
    ]
    divergences = [result["id"] for result in results if not result["agreement"]]
    valid_control_failures = [result["id"] for result in valid_controls if not result["agreement"]]
    document = {
        "agreementCount": len(results) - len(divergences),
        "caseCount": len(results),
        "corpusSha256": _sha256(corpus_path),
        "divergenceCount": len(divergences),
        "divergenceIds": divergences,
        "elapsedSeconds": round(time.monotonic() - started, 6),
        "graphConstruction": {
            "description": (
                "Each case is split by the manifest's named graph IDs. Rudof validates asserted, "
                "then derived, each unioned with pyshacl.rdfutil.inoculate(Graph(), ontology). "
                "Projection is excluded; validation stops at the first nonconforming role."
            ),
            "ontologyInputTripleCount": len(ontology),
            "ontologyViewTripleCount": len(ontology_view),
            "productionParserComparisonCount": (len(results) + len(valid_controls)) * 3,
            "productionParserParity": all(
                result["productionParserParity"]
                for result in [*results, *valid_controls]
            ),
            "roleOrder": list(ROLE_ORDER),
        },
        "ontologySha256": _sha256(ontology_path),
        "results": results,
        "rudof": {
            "byteLength": rudof.stat().st_size,
            "path": str(rudof),
            "sha256": _sha256(rudof),
        },
        "shapesSha256": _sha256(shapes_path),
        "validControlCount": len(valid_controls),
        "validControlFailureCount": len(valid_control_failures),
        "validControlFailureIds": valid_control_failures,
        "validControls": valid_controls,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

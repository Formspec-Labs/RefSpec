#!/usr/bin/env python3
"""Exercise Rudof's Atlas SHACL feature floor with positive/negative data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from rdflib import RDF, Graph, Literal, Namespace

SH = Namespace("http://www.w3.org/ns/shacl#")
COMPONENT_PATTERN = re.compile(r"(?:https?://www\.w3\.org/ns/shacl#|sh:)([A-Za-z]+ConstraintComponent)")


def _report_summary(stdout: str) -> tuple[bool | None, list[str]]:
    try:
        report = Graph().parse(data=stdout, format="turtle")
    except Exception:  # noqa: BLE001 - a malformed candidate report is probe data
        return None, sorted(set(COMPONENT_PATTERN.findall(stdout)))
    conforms: bool | None = None
    report_node = next(report.subjects(RDF.type, SH.ValidationReport), None)
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


def _write_class_data(path: Path, *, focus_count: int, invalid: bool) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("<urn:class:Expected> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2000/01/rdf-schema#Class> .\n")
        stream.write("<urn:class:Focus> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2000/01/rdf-schema#Class> .\n")
        stream.write("<urn:class:value> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <urn:class:Expected> .\n")
        for index in range(focus_count):
            stream.write(f"<urn:class:focus:{index:06d}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <urn:class:Focus> .\n")
            value = "<urn:class:bad>" if invalid and index == focus_count - 1 else "<urn:class:value>"
            stream.write(f"<urn:class:focus:{index:06d}> <urn:class:p> {value} .\n")


def _run_probe(
    rudof: Path,
    directory: Path,
    *,
    name: str,
    shapes: str,
    data: str | None,
    data_writer: Any = None,
    expected_conforms: bool,
    expected_component: str | None,
) -> dict[str, Any]:
    shapes_path = directory / f"{name}.shapes.ttl"
    data_path = directory / f"{name}.data.nt"
    shapes_path.write_text(shapes, encoding="utf-8")
    if data_writer is not None:
        data_writer(data_path)
    else:
        data_path.write_text(data or "", encoding="utf-8")
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
    conforms, components = _report_summary(completed.stdout)
    passed = (
        completed.returncode == 0
        and not completed.stderr
        and conforms is expected_conforms
        and (expected_component is None or expected_component in components)
    )
    return {
        "command": command,
        "components": components,
        "conforms": conforms,
        "dataByteLength": data_path.stat().st_size,
        "elapsedSeconds": round(elapsed, 6),
        "expectedComponent": expected_component,
        "expectedConforms": expected_conforms,
        "name": name,
        "passed": passed,
        "returnCode": completed.returncode,
        "stderr": completed.stderr,
        "stdout": completed.stdout,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rudof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--large-class-count", type=int, default=590_000)
    args = parser.parse_args()

    rudof = args.rudof.resolve()
    common = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix ex: <urn:feature:> .
"""
    probes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rudof-feature-floor-") as temporary:
        directory = Path(temporary)

        xone_shapes = common + """
ex:Shape a sh:NodeShape ; sh:targetNode ex:focus ; sh:xone (
  [ sh:property [ sh:path ex:p ; sh:hasValue ex:a ] ]
  [ sh:property [ sh:path ex:p ; sh:hasValue ex:b ] ]
) .
"""
        probes.append(_run_probe(rudof, directory, name="xone-positive", shapes=xone_shapes,
                                 data="<urn:feature:focus> <urn:feature:p> <urn:feature:a> .\n",
                                 expected_conforms=True, expected_component=None))
        probes.append(_run_probe(rudof, directory, name="xone-negative", shapes=xone_shapes,
                                 data=("<urn:feature:focus> <urn:feature:p> <urn:feature:a> .\n"
                                       "<urn:feature:focus> <urn:feature:p> <urn:feature:b> .\n"),
                                 expected_conforms=False, expected_component="XoneConstraintComponent"))

        closed_shapes = common + """
ex:Shape a sh:NodeShape ; sh:targetNode ex:focus ; sh:closed true ;
  sh:ignoredProperties ( rdf:type ) ; sh:property [ sh:path ex:p ] .
"""
        probes.append(_run_probe(rudof, directory, name="closed-positive", shapes=closed_shapes,
                                 data="<urn:feature:focus> <urn:feature:p> <urn:feature:a> .\n",
                                 expected_conforms=True, expected_component=None))
        probes.append(_run_probe(rudof, directory, name="closed-negative", shapes=closed_shapes,
                                 data=("<urn:feature:focus> <urn:feature:p> <urn:feature:a> .\n"
                                       "<urn:feature:focus> <urn:feature:q> <urn:feature:b> .\n"),
                                 expected_conforms=False, expected_component="ClosedConstraintComponent"))

        class_shapes = common + """
@prefix cls: <urn:class:> .
cls:Shape a sh:NodeShape ; sh:targetClass cls:Focus ;
  sh:property [ sh:path cls:p ; sh:class cls:Expected ] .
"""
        for invalid in (False, True):
            polarity = "negative" if invalid else "positive"
            probes.append(_run_probe(
                rudof,
                directory,
                name=f"class-large-{polarity}",
                shapes=class_shapes,
                data=None,
                data_writer=lambda path, invalid=invalid: _write_class_data(
                    path, focus_count=args.large_class_count, invalid=invalid
                ),
                expected_conforms=not invalid,
                expected_component="ClassConstraintComponent" if invalid else None,
            ))

        in_shapes = common + """
ex:Shape a sh:NodeShape ; sh:targetNode ex:focus ;
  sh:property [ sh:path ex:p ; sh:in ( ex:a ex:b ) ] .
"""
        probes.append(_run_probe(rudof, directory, name="in-positive", shapes=in_shapes,
                                 data="<urn:feature:focus> <urn:feature:p> <urn:feature:a> .\n",
                                 expected_conforms=True, expected_component=None))
        probes.append(_run_probe(rudof, directory, name="in-negative", shapes=in_shapes,
                                 data="<urn:feature:focus> <urn:feature:p> <urn:feature:c> .\n",
                                 expected_conforms=False, expected_component="InConstraintComponent"))

        node_shapes = common + """
ex:Shape a sh:NodeShape ; sh:targetNode ex:focus ;
  sh:property [ sh:path ex:p ; sh:node ex:ValueShape ] .
ex:ValueShape a sh:NodeShape ; sh:property [ sh:path ex:q ; sh:minCount 1 ] .
"""
        probes.append(_run_probe(rudof, directory, name="node-positive", shapes=node_shapes,
                                 data=("<urn:feature:focus> <urn:feature:p> <urn:feature:value> .\n"
                                       "<urn:feature:value> <urn:feature:q> <urn:feature:present> .\n"),
                                 expected_conforms=True, expected_component=None))
        probes.append(_run_probe(rudof, directory, name="node-negative", shapes=node_shapes,
                                 data="<urn:feature:focus> <urn:feature:p> <urn:feature:value> .\n",
                                 expected_conforms=False, expected_component="NodeConstraintComponent"))

        equals_shapes = common + """
ex:Shape a sh:NodeShape ; sh:targetNode ex:focus ;
  sh:property [ sh:path ( ex:p ex:q ) ; sh:equals ex:r ] .
"""
        probes.append(_run_probe(rudof, directory, name="sequence-equals-positive", shapes=equals_shapes,
                                 data=("<urn:feature:focus> <urn:feature:p> <urn:feature:middle> .\n"
                                       "<urn:feature:middle> <urn:feature:q> <urn:feature:value> .\n"
                                       "<urn:feature:focus> <urn:feature:r> <urn:feature:value> .\n"),
                                 expected_conforms=True, expected_component=None))
        probes.append(_run_probe(rudof, directory, name="sequence-equals-negative", shapes=equals_shapes,
                                 data=("<urn:feature:focus> <urn:feature:p> <urn:feature:middle> .\n"
                                       "<urn:feature:middle> <urn:feature:q> <urn:feature:value> .\n"
                                       "<urn:feature:focus> <urn:feature:r> <urn:feature:other> .\n"),
                                 expected_conforms=False, expected_component="EqualsConstraintComponent"))

    document = {
        "allPassed": all(probe["passed"] for probe in probes),
        "largeClassFocusCount": args.large_class_count,
        "probeCount": len(probes),
        "probes": probes,
        "rudof": {
            "path": str(rudof),
            "byteLength": rudof.stat().st_size,
            "sha256": hashlib.sha256(rudof.read_bytes()).hexdigest(),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not document["allPassed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

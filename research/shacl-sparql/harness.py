"""Prepare data and run the SHACL-SPARQL prototype reproducibly.

The harness writes only paths supplied by the caller. Use a temporary
directory for generated fixture views, staging views, and per-shape files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SH

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "bindings/atlas/3.1/fixtures"
SHAPES = REPO / "research/shacl-sparql/shapes/adjudication.shacl.ttl"
PROTO = "urn:ref:research:shacl-sparql#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDF_PREDICATE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate"
ATLAS_MAPPING = "https://refspec.org/ns/atlas/v3#MappingAssertion"
RKAF = "https://rulespec.org/ns/v1#"
SKOS = "http://www.w3.org/2004/02/skos/core#"

SHAPE_NAMES = (
    "FiveAxisIndependenceShape",
    "CompleteSupportShape",
    "VerdictLatticeFoldShape",
    "ProofReplayRefusalShape",
)

INVALID_CASES = {
    "FiveAxisIndependenceShape": (
        "adjudication-single-proof",
        "adjudication-same-validator-actor",
        "adjudication-same-independence-group",
        "adjudication-same-provider",
        "adjudication-same-provider-model",
        "adjudication-same-response-artifact",
    ),
    "CompleteSupportShape": ("adjudication-discarded-support",),
    "VerdictLatticeFoldShape": (
        "adjudication-relation-not-licensed",
        "adjudication-verdicts-disagree",
    ),
    "ProofReplayRefusalShape": ("adjudication-foreign-comparison",),
}

VALID_CASES = (
    "all-resource-profiles",
    "qualified-three-machine-support",
    "qualified-lattice-branches",
    "adjudication-refused-comparison-record",
)


def _open_pack(path: Path, compression: str):
    if compression == "none":
        return path.open("rb")
    if compression != "zstd":
        raise SystemExit(f"unsupported pack compression: {compression}")
    try:
        import zstandard
    except ImportError as exc:
        raise SystemExit("zstandard is required to read compressed packs") from exc
    source = path.open("rb")
    reader = zstandard.ZstdDecompressor().stream_reader(source)

    class _Reader:
        def __enter__(self):
            return reader

        def __exit__(self, exc_type, exc, traceback):
            reader.close()
            source.close()

    return _Reader()


def prepare_distribution(distribution: Path, output: Path) -> dict[str, object]:
    manifest = json.loads((distribution / "atlas-manifest.json").read_bytes())
    asserted = next(row for row in manifest["graphs"] if row["role"] == "asserted")
    suffix = f" <{asserted['id']}> .\n".encode()
    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as destination:
        for pack in manifest["packs"]:
            if pack["graphCounts"]["asserted"] == 0:
                continue
            path = distribution / pack["path"]
            compression = pack["transport"]["compression"]
            with _open_pack(path, compression) as source:
                for line in source:
                    if not line.endswith(suffix):
                        raise SystemExit(
                            f"{path} contains a line outside asserted graph {asserted['id']}"
                        )
                    destination.write(line[: -len(suffix)] + b" .\n")
                    count += 1
    if count != asserted["quadCount"]:
        raise SystemExit(
            f"prepared {count} asserted triples; manifest declares {asserted['quadCount']}"
        )
    return {
        "distribution": str(distribution),
        "distribution_id": manifest["distributionId"],
        "triples": count,
        "bytes": output.stat().st_size,
    }


def _case_path(case_id: str) -> Path:
    corpus = json.loads((FIXTURES / "corpus.json").read_bytes())
    row = next((row for row in corpus["cases"] if row["id"] == case_id), None)
    if row is None:
        raise SystemExit(f"unknown fixture case: {case_id}")
    return FIXTURES / row["path"]


def extract_shape(shape_name: str, output: Path) -> None:
    if shape_name not in SHAPE_NAMES:
        raise SystemExit(f"unknown prototype shape: {shape_name}")
    keep = URIRef(PROTO + shape_name)
    graph = Graph().parse(SHAPES, format="turtle")
    target_predicates = (
        SH.targetClass,
        SH.targetNode,
        SH.targetSubjectsOf,
        SH.targetObjectsOf,
    )
    kept = 0
    for predicate in target_predicates:
        for subject, obj in list(graph.subject_objects(predicate)):
            if subject == keep:
                kept += 1
            else:
                graph.remove((subject, predicate, obj))
    if kept == 0:
        raise SystemExit(f"{shape_name} declares no target")
    output.write_bytes(graph.serialize(format="turtle", encoding="utf-8"))


def _iri(value: str) -> bytes:
    return f"<{value}>".encode()


def _triple(subject: str, predicate: str, obj: str, *, literal: bool = False) -> bytes:
    object_term = f'"{obj}"'.encode() if literal else _iri(obj)
    return b" ".join((_iri(subject), _iri(predicate), object_term)) + b" .\n"


def augment_staging(source: Path, output: Path) -> dict[str, object]:
    """Add two independent, lattice-consistent proofs per real mapping.

    The source bytes remain unchanged at the start of the output. Added nodes
    use a research-only URN namespace and depend only on each real mapping's
    sorted assertion IRI and stated SKOS predicate.
    """

    type_pattern = re.compile(
        rb"^<([^>]*)> <" + re.escape(RDF_TYPE.encode()) + rb"> <"
        + re.escape(ATLAS_MAPPING.encode()) + rb"> \.\n$"
    )
    predicate_pattern = re.compile(
        rb"^<([^>]*)> <" + re.escape(RDF_PREDICATE.encode()) + rb"> <([^>]*)> \.\n$"
    )
    mappings: set[str] = set()
    predicates: dict[str, str] = {}
    with source.open("rb") as stream:
        for line in stream:
            if match := type_pattern.match(line):
                mappings.add(match.group(1).decode())
            elif match := predicate_pattern.match(line):
                predicates[match.group(1).decode()] = match.group(2).decode()

    verdicts = {
        SKOS + "exactMatch": RKAF + "verdictSame",
        SKOS + "closeMatch": RKAF + "verdictNearSame",
        SKOS + "broadMatch": RKAF + "verdictTargetBroader",
        SKOS + "narrowMatch": RKAF + "verdictTargetNarrower",
        SKOS + "relatedMatch": RKAF + "verdictRelated",
    }
    missing = sorted(mapping for mapping in mappings if predicates.get(mapping) not in verdicts)
    if missing:
        raise SystemExit(f"{len(missing)} mappings lack a licensed SKOS predicate")

    added = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, output.open("wb") as destination:
        shutil.copyfileobj(input_stream, destination, length=1 << 22)
        for index, assertion in enumerate(sorted(mappings)):
            stem = f"urn:ref:shacl-sparql-benchmark:{index:04d}"
            comparison = stem + ":comparison"
            destination.write(_triple(comparison, RDF_TYPE, RKAF + "RelationComparisonContext"))
            destination.write(
                _triple(comparison, RKAF + "comparisonOutcome", RKAF + "comparisonSatisfied")
            )
            destination.write(
                _triple(comparison, RKAF + "comparisonExpectedAssertion", assertion)
            )
            added += 3
            for key in ("alpha", "beta"):
                proof = f"{stem}:proof:{key}"
                issuer = f"{stem}:issuer:{key}"
                lineage = f"{stem}:lineage:{key}"
                destination.write(
                    _triple(comparison, RKAF + "comparisonProofRecord", proof)
                )
                destination.write(_triple(proof, RDF_TYPE, RKAF + "ResolverProofRecord"))
                destination.write(_triple(proof, RKAF + "proofComparisonContext", comparison))
                destination.write(_triple(proof, RKAF + "proofIssuer", issuer))
                destination.write(
                    _triple(proof, RKAF + "independenceGroup", f"{stem}:group:{key}")
                )
                destination.write(_triple(proof, RKAF + "hasAILineage", lineage))
                destination.write(
                    _triple(proof, RKAF + "sealedResponseArtifact", f"{stem}:response:{key}")
                )
                destination.write(
                    _triple(proof, RKAF + "adjudicationVerdict", verdicts[predicates[assertion]])
                )
                destination.write(
                    _triple(issuer, RKAF + "proofResolver", f"{stem}:provider:{key}")
                )
                destination.write(
                    _triple(lineage, RKAF + "modelId", f"benchmark-model-{key}", literal=True)
                )
                added += 10

    with source.open("rb") as input_stream:
        base_triples = sum(1 for _ in input_stream)
    with output.open("rb") as output_stream:
        total_triples = sum(1 for _ in output_stream)
    return {
        "base_triples": base_triples,
        "mapping_assertions": len(mappings),
        "added_triples": added,
        "total_triples": total_triples,
        "bytes": output.stat().st_size,
    }


def _report_facts(graph: Graph) -> tuple[bool, int]:
    reports = list(graph.subjects(RDF.type, SH.ValidationReport))
    if len(reports) != 1:
        raise SystemExit(f"expected one SHACL report, found {len(reports)}")
    conforms = graph.value(reports[0], SH.conforms)
    results = len(set(graph.subjects(RDF.type, SH.ValidationResult)))
    return bool(conforms.toPython()), results


def pyshacl_validate(data_path: Path, shapes_path: Path) -> dict[str, object]:
    from pyshacl import validate as shacl_validate

    started = time.perf_counter()
    data = Graph()
    data.parse(data_path, format="nt")
    data_loaded = time.perf_counter()
    shapes = Graph()
    shapes.parse(shapes_path, format="turtle")
    shapes_loaded = time.perf_counter()
    conforms, report_graph, _ = shacl_validate(
        data,
        shacl_graph=shapes,
        inference="none",
        inplace=True,
        advanced=True,
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
    )
    finished = time.perf_counter()
    _, results = _report_facts(report_graph)
    return {
        "engine": "pyshacl",
        "conforms": bool(conforms),
        "results": results,
        "data_triples": len(data),
        "data_load_seconds": data_loaded - started,
        "shapes_load_seconds": shapes_loaded - data_loaded,
        "validation_seconds": finished - shapes_loaded,
        "inside_process_seconds": finished - started,
    }


def jena_validate(data_path: Path, shapes_path: Path, jena: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment["JVM_ARGS"] = "-Xmx4g"
    started = time.perf_counter()
    process = subprocess.run(
        [
            str(jena),
            "shacl",
            "validate",
            "--shapes",
            str(shapes_path),
            "--data",
            str(data_path),
        ],
        check=True,
        capture_output=True,
        env=environment,
    )
    elapsed = time.perf_counter() - started
    report = Graph().parse(data=process.stdout.decode(), format="turtle")
    conforms, results = _report_facts(report)
    return {
        "engine": "jena",
        "conforms": conforms,
        "results": results,
        "wall_seconds": elapsed,
    }


def fixture_matrix(jena: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="refspec-shacl-sparql-") as directory:
        root = Path(directory)
        for shape_name in SHAPE_NAMES:
            subset = root / f"{shape_name}.ttl"
            extract_shape(shape_name, subset)
            cases = [(case, False) for case in INVALID_CASES[shape_name]]
            cases.extend((case, True) for case in VALID_CASES)
            for case_id, expected_conforms in cases:
                data = root / f"{case_id}.nt"
                if not data.exists():
                    prepare_distribution(_case_path(case_id), data)
                pyshacl = pyshacl_validate(data, subset)
                jena_result = jena_validate(data, subset, jena)
                observed = bool(pyshacl["conforms"] and jena_result["conforms"])
                engines_agree = pyshacl["conforms"] == jena_result["conforms"]
                rows.append(
                    {
                        "shape": shape_name,
                        "fixture": case_id,
                        "expected_conforms": expected_conforms,
                        "pyshacl_conforms": pyshacl["conforms"],
                        "pyshacl_results": pyshacl["results"],
                        "jena_conforms": jena_result["conforms"],
                        "jena_results": jena_result["results"],
                        "pass": engines_agree and observed == expected_conforms,
                    }
                )
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("distribution", type=Path)
    prepare.add_argument("output", type=Path)

    case = subparsers.add_parser("prepare-case")
    case.add_argument("case_id")
    case.add_argument("output", type=Path)

    extract = subparsers.add_parser("extract-shape")
    extract.add_argument("shape", choices=SHAPE_NAMES)
    extract.add_argument("output", type=Path)

    augment = subparsers.add_parser("augment-staging")
    augment.add_argument("source", type=Path)
    augment.add_argument("output", type=Path)

    pyshacl = subparsers.add_parser("pyshacl")
    pyshacl.add_argument("data", type=Path)
    pyshacl.add_argument("shapes", type=Path)

    matrix = subparsers.add_parser("fixture-matrix")
    matrix.add_argument("--jena", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "prepare":
        result = prepare_distribution(args.distribution, args.output)
    elif args.command == "prepare-case":
        result = prepare_distribution(_case_path(args.case_id), args.output)
    elif args.command == "extract-shape":
        extract_shape(args.shape, args.output)
        result = {"shape": args.shape, "output": str(args.output)}
    elif args.command == "augment-staging":
        result = augment_staging(args.source, args.output)
    elif args.command == "pyshacl":
        result = pyshacl_validate(args.data, args.shapes)
    else:
        result = fixture_matrix(args.jena)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

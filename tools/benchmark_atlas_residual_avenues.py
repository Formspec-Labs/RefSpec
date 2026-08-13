"""Compare residual SHACL lift prototypes against one resident staging graph.

The parent parses the read-only distribution once, freezes that stable RDFLib
heap the same way acceptance does, and forks a fresh child for every timed
sample. Forking prevents one pySHACL run's garbage-collection state from
distorting the next avenue while keeping every sample on identical parsed
terms and indexes.

This is a research benchmark, not a release gate. It requires ``os.fork`` and
writes one JSON evidence file containing every raw sample and median summary.
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import resource
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tools" / "validate.py"


class _FastMembershipList(list[Any]):
    """Keep pySHACL's parameter order but make ``predicate in`` constant-time."""

    def __init__(self, values: list[Any]) -> None:
        super().__init__(values)
        self._members = frozenset(values)

    def __contains__(self, value: object) -> bool:
        return value in self._members


def _load_validator() -> ModuleType:
    if str(VALIDATOR_PATH.parent) not in sys.path:
        sys.path.insert(0, str(VALIDATOR_PATH.parent))
    spec = importlib.util.spec_from_file_location("refspec_atlas_v3_residual_benchmark", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the Atlas validator from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _distribution_root(named: Path) -> Path:
    return named if (named / "atlas-manifest.json").is_file() else named / "distribution"


def _maximum_rss_bytes() -> int:
    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum_rss if sys.platform == "darwin" else maximum_rss * 1024


def _measure_child(
    validate: ModuleType,
    graphs: dict[str, Any],
    ontology_view: Graph,
    normative_shapes: Graph,
    type_index: Any,
    components: Any,
    fast_parameter_membership: bool,
) -> dict[str, Any]:
    if fast_parameter_membership:
        import pyshacl.shape as shape_module
        from pyshacl.constraints import (
            ALL_CONSTRAINT_PARAMETERS,
            CONSTRAINT_PARAMETERS_MAP,
        )

        shape_module.CONSTRAINT_PARAMS = (
            _FastMembershipList(ALL_CONSTRAINT_PARAMETERS),
            CONSTRAINT_PARAMETERS_MAP,
        )
    plan = validate._batched_shacl_plan(normative_shapes, direct_constraints=components)
    roles: list[dict[str, Any]] = []
    for role in ("asserted", "derived"):
        view = validate._ShaclDataView([graphs[role], ontology_view])
        role_type_index = type_index if role == "asserted" else None
        precheck_started = time.perf_counter()
        prechecks = validate._batched_shacl_prechecks(
            view,
            normative_shapes,
            plan,
            type_index=role_type_index,
        )
        precheck_seconds = time.perf_counter() - precheck_started
        engine_started = time.perf_counter()
        conforms, _report_graph, _report_text = validate._validate_shacl_data(view, plan.shapes)
        engine_seconds = time.perf_counter() - engine_started
        roles.append(
            {
                "conforms": bool(prechecks and conforms),
                "engineSeconds": engine_seconds,
                "precheckSeconds": precheck_seconds,
                "role": role,
            }
        )
    return {
        "directPropertyShapes": sum(len(target.properties) for target in plan.direct_targets),
        "engineSeconds": sum(role["engineSeconds"] for role in roles),
        "maximumRssBytes": _maximum_rss_bytes(),
        "precheckSeconds": sum(role["precheckSeconds"] for role in roles),
        "roles": roles,
        "totalSeconds": sum(
            role["engineSeconds"] + role["precheckSeconds"] for role in roles
        ),
    }


def _fork_measurement(*args: Any) -> dict[str, Any]:
    read_descriptor, write_descriptor = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_descriptor)
        try:
            result = _measure_child(*args)
            payload = json.dumps(result, separators=(",", ":")).encode("utf-8")
            while payload:
                written = os.write(write_descriptor, payload)
                payload = payload[written:]
        except BaseException as exc:  # noqa: BLE001 - preserve child diagnostics
            payload = json.dumps({"childError": repr(exc)}).encode("utf-8")
            os.write(write_descriptor, payload)
        finally:
            os.close(write_descriptor)
        os._exit(0)

    os.close(write_descriptor)
    chunks: list[bytes] = []
    while chunk := os.read(read_descriptor, 65536):
        chunks.append(chunk)
    os.close(read_descriptor)
    _pid, status = os.waitpid(child, 0)
    if status != 0:
        raise RuntimeError(f"benchmark child {child} exited with wait status {status}")
    result = json.loads(b"".join(chunks))
    if "childError" in result:
        raise RuntimeError(result["childError"])
    return result


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    fields = ("engineSeconds", "precheckSeconds", "totalSeconds")
    summary: dict[str, Any] = {
        "directPropertyShapes": samples[0]["directPropertyShapes"],
        "maximumRssBytes": max(sample["maximumRssBytes"] for sample in samples),
        "sampleCount": len(samples),
    }
    for field in fields:
        values = [sample[field] for sample in samples]
        summary[field] = {
            "maximum": max(values),
            "median": statistics.median(values),
            "minimum": min(values),
        }
    return summary


def benchmark(
    distribution: Path,
    repetitions: int,
    selected_variants: list[str] | None = None,
) -> dict[str, Any]:
    if not hasattr(os, "fork"):
        raise RuntimeError("the residual avenue benchmark requires os.fork")
    validate = _load_validator()
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: validate.URIRef(row["id"]) for row in manifest["graphs"]}
    placement = validate._AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=validate._projection_only_predicates(),
    )
    parse_started = time.perf_counter()
    _dataset, graphs = validate._parse_packed_dataset(
        distribution,
        manifest,
        graph_ids,
        asserted_placement=placement,
    )
    ontology, normative_shapes = validate._parse_binding_graphs()
    parse_seconds = time.perf_counter() - parse_started

    proof_started = time.perf_counter()
    validate._prove_shape_graph_conforms(
        validate.file_sha256(validate.ONTOLOGY_PATH),
        validate.file_sha256(validate.SHAPES_PATH),
    )
    shape_graph_proof_seconds = time.perf_counter() - proof_started
    ontology_view = validate.inoculate(Graph(), ontology)
    ontology_types: dict[Any, list[Any]] = {}
    for subject, node_type in ontology_view.subject_objects(validate.RDF.type):
        ontology_types.setdefault(subject, []).append(node_type)
    type_index = validate._CombinedTypeIndex(placement.types, ontology_types)

    variants = {
        "baseline": (frozenset(), False),
        "cardinality-membership": (
            validate._DIRECT_CARDINALITY_MEMBERSHIP_CONSTRAINTS,
            False,
        ),
        "term": (validate._DIRECT_TERM_CONSTRAINTS, False),
        "class": (validate._DIRECT_CLASS_CONSTRAINTS, False),
        "all": (validate._DIRECT_PROPERTY_CONSTRAINTS, False),
        "constraint-parameter-set": (frozenset(), True),
    }
    if selected_variants is not None:
        unknown = set(selected_variants) - set(variants)
        if unknown:
            raise ValueError(f"unknown benchmark variants: {sorted(unknown)}")
        variants = {name: variants[name] for name in selected_variants}
    if "baseline" not in variants:
        variants = {"baseline": (frozenset(), False), **variants}
    raw: dict[str, list[dict[str, Any]]] = {name: [] for name in variants}
    gc.collect()
    gc.freeze()
    try:
        names = list(variants)
        for repetition in range(repetitions):
            rotated = names[repetition % len(names) :] + names[: repetition % len(names)]
            for name in rotated:
                sample = _fork_measurement(
                    validate,
                    graphs,
                    ontology_view,
                    normative_shapes,
                    type_index,
                    *variants[name],
                )
                sample["repetition"] = repetition + 1
                raw[name].append(sample)
                print(
                    f"{name} {repetition + 1}/{repetitions}: "
                    f"{sample['totalSeconds']:.3f}s "
                    f"(precheck {sample['precheckSeconds']:.3f}s, "
                    f"engine {sample['engineSeconds']:.3f}s)",
                    flush=True,
                )
    finally:
        gc.unfreeze()

    summaries = {name: _summary(samples) for name, samples in raw.items()}
    baseline = summaries["baseline"]["totalSeconds"]["median"]
    for summary in summaries.values():
        median = summary["totalSeconds"]["median"]
        summary["medianRatioToBaseline"] = median / baseline
        summary["medianSecondsRemoved"] = baseline - median
    return {
        "distribution": str(distribution),
        "distributionId": manifest["distributionId"],
        "environment": {
            "pyshacl": __import__("pyshacl").__version__,
            "python": sys.version.split()[0],
            "rdflib": __import__("rdflib").__version__,
        },
        "packCount": len(manifest["packs"]),
        "parseSeconds": parse_seconds,
        "quadCount": sum(pack["content"]["quadCount"] for pack in manifest["packs"]),
        "raw": raw,
        "recordedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "shapeGraphProofSeconds": shape_graph_proof_seconds,
        "summaries": summaries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--variants", nargs="+", help="avenues to run; baseline is always included")
    arguments = parser.parse_args(argv)
    if arguments.repetitions < 1:
        parser.error("--repetitions must be positive")
    distribution = _distribution_root(arguments.distribution)
    if not (distribution / "atlas-manifest.json").is_file():
        parser.error(f"no distribution found at {arguments.distribution}")
    try:
        result = benchmark(distribution, arguments.repetitions, arguments.variants)
    except ValueError as exc:
        parser.error(str(exc))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

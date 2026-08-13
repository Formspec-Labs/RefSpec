"""Attribute Atlas's residual pySHACL work at distribution scale.

This research tool leaves the distribution, binding, validator, and installed
pySHACL package unchanged. It times the lifted prechecks and the remaining
engine call separately, wraps pySHACL's constraint evaluators to attribute
inclusive wall time by source shape and constraint component, and records a
standard-library ``cProfile`` view of the same engine call.

The timings are diagnostic rather than a release gate. Instrumentation adds
overhead, so compare alternatives with the uninstrumented scale benchmark and
use this tool to decide what to prototype.
"""

from __future__ import annotations

import argparse
import cProfile
import importlib.util
import io
import json
import os
import pstats
import resource
import sys
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

from pyshacl.constraints.constraint_component import ConstraintComponent
from pyshacl.shape import Shape
from rdflib import Graph
from rdflib.namespace import SH

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tools" / "validate.py"


@dataclass(slots=True)
class Attribution:
    calls: int = 0
    focus_nodes: int = 0
    seconds: float = 0.0
    value_nodes: int = 0


def _load_validator() -> ModuleType:
    if str(VALIDATOR_PATH.parent) not in sys.path:
        sys.path.insert(0, str(VALIDATOR_PATH.parent))
    spec = importlib.util.spec_from_file_location("refspec_atlas_v3_profile_validate", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the Atlas validator from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _distribution_root(named: Path) -> Path:
    return named if (named / "atlas-manifest.json").is_file() else named / "distribution"


def _all_constraint_classes() -> Iterator[type[ConstraintComponent]]:
    pending = list(ConstraintComponent.__subclasses__())
    seen: set[type[ConstraintComponent]] = set()
    while pending:
        component = pending.pop()
        if component in seen:
            continue
        seen.add(component)
        pending.extend(component.__subclasses__())
        yield component


def _shape_label(shape: Any, normative_shapes: Graph) -> str:
    node = shape.node
    path = next(normative_shapes.objects(node, SH.path), None)
    parents = sorted(normative_shapes.subjects(SH.property, node), key=str)
    if parents:
        return f"{parents[0]} -> {path or node}"
    return str(node)


@contextmanager
def _instrument_pyshacl(normative_shapes: Graph) -> Iterator[
    tuple[dict[tuple[str, str], Attribution], dict[str, Attribution]]
]:
    constraints: dict[tuple[str, str], Attribution] = defaultdict(Attribution)
    shapes: dict[str, Attribution] = defaultdict(Attribution)
    originals: list[tuple[type[Any], str, Any]] = []

    for component_class in _all_constraint_classes():
        original = component_class.__dict__.get("evaluate")
        if original is None:
            continue

        @wraps(original)
        def measured_component(self: Any, *args: Any, __original: Any = original, **kwargs: Any) -> Any:
            focus_value_nodes = args[2] if len(args) >= 3 else kwargs["focus_value_nodes"]
            key = (_shape_label(self.shape, normative_shapes), self.constraint_name())
            row = constraints[key]
            row.calls += 1
            row.focus_nodes += len(focus_value_nodes)
            row.value_nodes += sum(len(values) for values in focus_value_nodes.values())
            started = time.perf_counter()
            try:
                return __original(self, *args, **kwargs)
            finally:
                row.seconds += time.perf_counter() - started

        originals.append((component_class, "evaluate", original))
        component_class.evaluate = measured_component

    original_shape_validate = Shape.validate

    @wraps(original_shape_validate)
    def measured_shape(self: Shape, *args: Any, **kwargs: Any) -> Any:
        row = shapes[_shape_label(self, normative_shapes)]
        row.calls += 1
        focus = args[2] if len(args) >= 3 else kwargs.get("focus")
        if focus is not None:
            if isinstance(focus, (str, bytes)):
                row.focus_nodes += 1
            else:
                try:
                    row.focus_nodes += len(focus)
                except TypeError:
                    row.focus_nodes += 1
        started = time.perf_counter()
        try:
            return original_shape_validate(self, *args, **kwargs)
        finally:
            row.seconds += time.perf_counter() - started

    originals.append((Shape, "validate", original_shape_validate))
    Shape.validate = measured_shape
    try:
        yield constraints, shapes
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


def _rows(attribution: dict[Any, Attribution], *, constraints: bool) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for key, value in attribution.items():
        row = asdict(value)
        row["seconds"] = round(row["seconds"], 6)
        if constraints:
            row["shape"], row["component"] = key
        else:
            row["shape"] = key
        output.append(row)
    return sorted(output, key=lambda row: (-row["seconds"], row["shape"], row.get("component", "")))


def _profile_text(profile: cProfile.Profile, limit: int) -> str:
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(limit)
    return stream.getvalue()


def measure(
    distribution: Path,
    *,
    direct_lift: bool,
    profile_limit: int,
) -> tuple[dict[str, Any], str]:
    validate = _load_validator()
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: validate.URIRef(row["id"]) for row in manifest["graphs"]}

    parse_started = time.perf_counter()
    placement = validate._AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=validate._projection_only_predicates(),
    )
    _dataset, graphs = validate._parse_packed_dataset(
        distribution,
        manifest,
        graph_ids,
        asserted_placement=placement,
    )
    ontology, normative_shapes = validate._parse_binding_graphs()
    parse_seconds = time.perf_counter() - parse_started

    proof_started = time.perf_counter()
    validate._prove_shape_graph_conforms(validate.file_sha256(validate.ONTOLOGY_PATH), validate.file_sha256(validate.SHAPES_PATH))
    proof_seconds = time.perf_counter() - proof_started

    inoculate_started = time.perf_counter()
    ontology_view = validate.inoculate(Graph(), ontology)
    ontology_types: dict[Any, list[Any]] = {}
    for subject, node_type in ontology_view.subject_objects(validate.RDF.type):
        ontology_types.setdefault(subject, []).append(node_type)
    type_index = validate._CombinedTypeIndex(placement.types, ontology_types)
    plan = validate._batched_shacl_plan(
        normative_shapes,
        direct_constraints=(validate._DIRECT_PROPERTY_CONSTRAINTS if direct_lift else frozenset()),
    )
    setup_seconds = time.perf_counter() - inoculate_started

    profile = cProfile.Profile()
    role_rows: list[dict[str, Any]] = []
    with _instrument_pyshacl(normative_shapes) as (constraint_times, shape_times):
        for role in ("asserted", "derived"):
            data_view = validate._ShaclDataView([graphs[role], ontology_view])
            role_type_index = type_index if role == "asserted" else None
            precheck_started = time.perf_counter()
            precheck_passed = validate._batched_shacl_prechecks(
                data_view,
                normative_shapes,
                plan,
                type_index=role_type_index,
            )
            precheck_seconds = time.perf_counter() - precheck_started

            engine_started = time.perf_counter()
            profile.enable()
            try:
                conforms, _report_graph, _report_text = validate._validate_shacl_data(data_view, plan.shapes)
            finally:
                profile.disable()
            engine_seconds = time.perf_counter() - engine_started
            role_rows.append(
                {
                    "conforms": bool(conforms and precheck_passed),
                    "engineSecondsInstrumented": round(engine_seconds, 6),
                    "precheckPassed": precheck_passed,
                    "precheckSeconds": round(precheck_seconds, 6),
                    "role": role,
                }
            )

    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        maximum_rss_bytes = maximum_rss
    else:
        maximum_rss_bytes = maximum_rss * 1024
    result = {
        "attribution": {
            "constraints": _rows(constraint_times, constraints=True),
            "shapes": _rows(shape_times, constraints=False),
        },
        "distribution": str(distribution),
        "distributionId": manifest["distributionId"],
        "directLift": direct_lift,
        "directPropertyShapes": sum(
            len(target.properties) for target in plan.direct_targets
        ),
        "environment": {
            "mode": os.environ.get(validate.VALIDATION_MODE_ENV, "default"),
            "pyshacl": __import__("pyshacl").__version__,
            "python": sys.version.split()[0],
            "rdflib": __import__("rdflib").__version__,
        },
        "maximumRssBytes": maximum_rss_bytes,
        "packCount": len(manifest["packs"]),
        "parseSeconds": round(parse_seconds, 6),
        "quadCount": sum(pack["content"]["quadCount"] for pack in manifest["packs"]),
        "recordedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "roles": role_rows,
        "shapeGraphProofSeconds": round(proof_seconds, 6),
        "setupSeconds": round(setup_seconds, 6),
    }
    return result, _profile_text(profile, profile_limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--profile-output", required=True, type=Path)
    parser.add_argument("--profile-limit", type=int, default=120)
    parser.add_argument("--direct-lift", action="store_true")
    arguments = parser.parse_args(argv)

    distribution = _distribution_root(arguments.distribution)
    if not (distribution / "atlas-manifest.json").is_file():
        parser.error(f"no distribution found at {arguments.distribution}")
    measurement, profile_text = measure(
        distribution,
        direct_lift=arguments.direct_lift,
        profile_limit=arguments.profile_limit,
    )
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.profile_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(json.dumps(measurement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    arguments.profile_output.write_text(profile_text, encoding="utf-8")
    print(
        f"profiled {measurement['quadCount']:,} quads; "
        f"asserted engine {measurement['roles'][0]['engineSecondsInstrumented']:.3f}s; "
        f"peak RSS {measurement['maximumRssBytes'] / (1024**3):.2f} GiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

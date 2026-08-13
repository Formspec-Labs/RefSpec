"""Measure focused discovery and shape-reformulation avenues at staging scale.

The parent parses the read-only Atlas distribution once and forks a fresh
child for every sample.  Each child starts from the same frozen RDF heap, so a
variant cannot benefit from another variant's pySHACL caches or garbage-
collection state.  The timed total includes plan construction, any type-index
inversion or helper materialization, the existing lifted prechecks, and the
residual pySHACL calls.  Parsing and the cached shape-graph proof are reported
separately because release acceptance also performs them separately.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any

from atlas_shacl_floor_prototypes import (
    VARIANTS,
    IndexedShaclDataView,
    Variant,
    focused_validate,
    invert_asserted_types,
    load_validator,
    make_plan,
    materialize_helpers,
)
from pyshacl.constraints.core.logical_constraints import XoneConstraintComponent
from pyshacl.constraints.core.property_pair_constraints import EqualsConstraintComponent
from pyshacl.shape import Shape
from rdflib import BNode, Graph, URIRef
from rdflib.namespace import RDF, SH


@dataclass(slots=True)
class Attribution:
    calls: int = 0
    focus_nodes: int = 0
    seconds: float = 0.0
    value_nodes: int = 0


def _distribution_root(named: Path) -> Path:
    return named if (named / "atlas-manifest.json").is_file() else named / "distribution"


def _maximum_rss_bytes() -> int:
    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum_rss if sys.platform == "darwin" else maximum_rss * 1024


def _short_term(validate: ModuleType, term: Any) -> str:
    text = str(term)
    for prefix, namespace in (
        ("atlas", validate.ATLAS),
        ("rkaf", validate.RKAF),
        ("rdf", RDF),
    ):
        if text.startswith(str(namespace)):
            return f"{prefix}:{text.removeprefix(str(namespace))}"
    return text


def _path_label(validate: ModuleType, shape: Shape) -> str:
    if not shape.is_property_shape:
        return "node"
    path = shape.path()
    if isinstance(path, URIRef):
        return _short_term(validate, path)
    if isinstance(path, BNode):
        items = list(shape.sg.graph.items(path))
        if items:
            return "/".join(_short_term(validate, item) for item in items)
    return str(path)


def _shape_label(validate: ModuleType, shape: Shape) -> str:
    targets = sorted(
        {
            _short_term(validate, target)
            for target in shape.sg.graph.objects(shape.node, SH.targetClass)
        }
    )
    target = ",".join(targets) if targets else _short_term(validate, shape.node)
    return f"{target} -> {_path_label(validate, shape)}"


def _attribution_rows(rows: dict[str, Attribution]) -> list[dict[str, Any]]:
    output = []
    for label, row in rows.items():
        values = asdict(row)
        values["label"] = label
        values["seconds"] = round(row.seconds, 6)
        output.append(values)
    return sorted(output, key=lambda row: (-row["seconds"], row["label"]))


@contextmanager
def _instrument_discovery(validate: ModuleType) -> Iterator[dict[str, dict[str, Attribution]]]:
    focus: dict[str, Attribution] = defaultdict(Attribution)
    values: dict[str, Attribution] = defaultdict(Attribution)
    constraints: dict[str, Attribution] = defaultdict(Attribution)
    original_focus = Shape.focus_nodes
    original_values = Shape.value_nodes
    original_equals = EqualsConstraintComponent.evaluate
    original_xone = XoneConstraintComponent.evaluate

    @wraps(original_focus)
    def measured_focus(self: Shape, *args: Any, **kwargs: Any) -> Any:
        row = focus[_shape_label(validate, self)]
        row.calls += 1
        started = time.perf_counter()
        result = original_focus(self, *args, **kwargs)
        row.seconds += time.perf_counter() - started
        row.focus_nodes += len(result)
        return result

    @wraps(original_values)
    def measured_values(self: Shape, *args: Any, **kwargs: Any) -> Any:
        row = values[_shape_label(validate, self)]
        row.calls += 1
        started = time.perf_counter()
        result = original_values(self, *args, **kwargs)
        row.seconds += time.perf_counter() - started
        row.focus_nodes += len(result)
        row.value_nodes += sum(len(nodes) for nodes in result.values())
        return result

    def measured_constraint(name: str, original: Any) -> Any:
        @wraps(original)
        def measured(self: Any, *args: Any, **kwargs: Any) -> Any:
            row = constraints[f"{name}: {_shape_label(validate, self.shape)}"]
            focus_value_nodes = args[2] if len(args) >= 3 else kwargs["focus_value_nodes"]
            row.calls += 1
            row.focus_nodes += len(focus_value_nodes)
            row.value_nodes += sum(len(nodes) for nodes in focus_value_nodes.values())
            started = time.perf_counter()
            try:
                return original(self, *args, **kwargs)
            finally:
                row.seconds += time.perf_counter() - started

        return measured

    Shape.focus_nodes = measured_focus
    Shape.value_nodes = measured_values
    EqualsConstraintComponent.evaluate = measured_constraint("equals", original_equals)
    XoneConstraintComponent.evaluate = measured_constraint("xone", original_xone)
    try:
        yield {"constraints": constraints, "focusNodes": focus, "valueNodes": values}
    finally:
        Shape.focus_nodes = original_focus
        Shape.value_nodes = original_values
        EqualsConstraintComponent.evaluate = original_equals
        XoneConstraintComponent.evaluate = original_xone


def _bind_namespaces(view: Graph, ontology: Graph) -> None:
    for prefix, namespace in ontology.namespaces():
        view.namespace_manager.bind(prefix, namespace)


def _measure_child(
    validate: ModuleType,
    graphs: dict[str, Graph],
    ontology_view: Graph,
    normative_shapes: Graph,
    placement: Any,
    variant: Variant,
    *,
    profile: bool,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    setup_started = time.perf_counter()
    plan = make_plan(validate, normative_shapes, variant)
    plan_seconds = time.perf_counter() - setup_started

    type_subjects: dict[Any, tuple[Any, ...]] = {}
    type_index_seconds = 0.0
    if variant.indexed_view:
        index_started = time.perf_counter()
        type_subjects = invert_asserted_types(placement.types)
        type_index_seconds = time.perf_counter() - index_started

    role_rows: list[dict[str, Any]] = []
    indexed_object_calls = 0
    indexed_object_values = 0
    indexed_type_calls = 0
    indexed_type_values = 0
    profile_rows: dict[str, Any] | None = None
    instrumentation = _instrument_discovery(validate) if profile else nullcontext(None)
    with instrumentation as attribution:
        for role in ("asserted", "derived"):
            if variant.indexed_view and role == "asserted":
                view: Graph = IndexedShaclDataView(
                    [graphs[role], ontology_view],
                    asserted=graphs[role],
                    facts=placement.facts,
                    type_subjects=type_subjects,
                    indexed_predicates=validate._INDEXED_ASSERTED_PREDICATES,
                )
            else:
                view = validate._ShaclDataView([graphs[role], ontology_view])
            _bind_namespaces(view, ontology_view)

            precheck_started = time.perf_counter()
            precheck_passed = validate._batched_shacl_prechecks(view, normative_shapes, plan)
            precheck_seconds = time.perf_counter() - precheck_started

            helper_started = time.perf_counter()
            execution_view, helper_triples = materialize_helpers(validate, view, plan.shapes)
            helper_seconds = time.perf_counter() - helper_started

            engine_started = time.perf_counter()
            if variant.focus_hints:
                conforms, _report, _text, focused = focused_validate(
                    validate,
                    execution_view,
                    plan.shapes,
                )
            else:
                conforms, _report, _text = validate._validate_shacl_data(execution_view, plan.shapes)
                focused = {
                    "dispatchSeconds": time.perf_counter() - engine_started,
                    "focusHintSeconds": 0.0,
                    "groupCount": 0,
                    "nonemptyGroupCount": 0,
                }
            engine_seconds = time.perf_counter() - engine_started
            if not precheck_passed or not conforms:
                raise RuntimeError(f"{role} graph did not conform under the research variant")

            if isinstance(view, IndexedShaclDataView):
                indexed_object_calls += view.indexed_object_calls
                indexed_object_values += view.indexed_object_values
                indexed_type_calls += view.indexed_type_calls
                indexed_type_values += view.indexed_type_values
                if isinstance(execution_view, IndexedShaclDataView) and execution_view is not view:
                    indexed_object_calls += execution_view.indexed_object_calls
                    indexed_object_values += execution_view.indexed_object_values
                    indexed_type_calls += execution_view.indexed_type_calls
                    indexed_type_values += execution_view.indexed_type_values

            role_rows.append(
                {
                    "dispatchSeconds": focused["dispatchSeconds"],
                    "engineSeconds": engine_seconds,
                    "focusHintSeconds": focused["focusHintSeconds"],
                    "groupCount": focused["groupCount"],
                    "helperSeconds": helper_seconds,
                    "helperTripleCount": helper_triples,
                    "nonemptyGroupCount": focused["nonemptyGroupCount"],
                    "precheckSeconds": precheck_seconds,
                    "role": role,
                }
            )
        if attribution is not None:
            profile_rows = {
                name: _attribution_rows(rows)
                for name, rows in attribution.items()
            }

    total_seconds = time.perf_counter() - total_started
    return {
        "conforms": True,
        "engineSeconds": sum(row["engineSeconds"] for row in role_rows),
        "helperSeconds": sum(row["helperSeconds"] for row in role_rows),
        "helperTripleCount": sum(row["helperTripleCount"] for row in role_rows),
        "indexedReads": {
            "objectCalls": indexed_object_calls,
            "objectValues": indexed_object_values,
            "typeCalls": indexed_type_calls,
            "typeValues": indexed_type_values,
        },
        "maximumRssBytes": _maximum_rss_bytes(),
        "planSeconds": plan_seconds,
        "precheckSeconds": sum(row["precheckSeconds"] for row in role_rows),
        "profile": profile_rows,
        "roles": role_rows,
        "totalSeconds": total_seconds,
        "typeIndexSeconds": type_index_seconds,
    }


def _fork_measurement(*args: Any, **kwargs: Any) -> dict[str, Any]:
    read_descriptor, write_descriptor = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_descriptor)
        try:
            payload = {"result": _measure_child(*args, **kwargs)}
        except BaseException as exc:  # noqa: BLE001 - preserve the child diagnostic
            payload = {"childError": repr(exc)}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        while raw:
            written = os.write(write_descriptor, raw)
            raw = raw[written:]
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
    payload = json.loads(b"".join(chunks))
    if "childError" in payload:
        raise RuntimeError(payload["childError"])
    return payload["result"]


def _range(values: Sequence[float]) -> dict[str, float]:
    return {
        "maximum": max(values),
        "median": statistics.median(values),
        "minimum": min(values),
    }


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "engineSeconds",
        "helperSeconds",
        "planSeconds",
        "precheckSeconds",
        "totalSeconds",
        "typeIndexSeconds",
    )
    return {
        **{field: _range([sample[field] for sample in samples]) for field in fields},
        "helperTripleCount": samples[0]["helperTripleCount"],
        "maximumRssBytes": max(sample["maximumRssBytes"] for sample in samples),
        "sampleCount": len(samples),
    }


def benchmark(
    distribution: Path,
    repetitions: int,
    selected_variants: Sequence[str],
    profile_variants: Sequence[str],
) -> dict[str, Any]:
    if not hasattr(os, "fork"):
        raise RuntimeError("the SHACL-floor benchmark requires os.fork")
    unknown = (set(selected_variants) | set(profile_variants)) - set(VARIANTS)
    if unknown:
        raise ValueError(f"unknown variants: {sorted(unknown)}")
    names = list(dict.fromkeys(("baseline", *selected_variants)))
    validate = load_validator()
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

    raw: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    profiles: dict[str, dict[str, Any]] = {}
    gc.collect()
    gc.freeze()
    try:
        for repetition in range(repetitions):
            rotated = names[repetition % len(names) :] + names[: repetition % len(names)]
            for name in rotated:
                sample = _fork_measurement(
                    validate,
                    graphs,
                    ontology_view,
                    normative_shapes,
                    placement,
                    VARIANTS[name],
                    profile=False,
                )
                sample["repetition"] = repetition + 1
                raw[name].append(sample)
                print(
                    f"{name} {repetition + 1}/{repetitions}: {sample['totalSeconds']:.3f}s "
                    f"(engine {sample['engineSeconds']:.3f}s, helpers {sample['helperSeconds']:.3f}s)",
                    flush=True,
                )
        for name in profile_variants:
            profiles[name] = _fork_measurement(
                validate,
                graphs,
                ontology_view,
                normative_shapes,
                placement,
                VARIANTS[name],
                profile=True,
            )
            print(f"profile {name}: {profiles[name]['totalSeconds']:.3f}s", flush=True)
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
        "profiles": profiles,
        "quadCount": sum(pack["content"]["quadCount"] for pack in manifest["packs"]),
        "raw": raw,
        "recordedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "shapeGraphProofSeconds": shape_graph_proof_seconds,
        "summaries": summaries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS))
    parser.add_argument("--profile-variants", nargs="*", default=[])
    arguments = parser.parse_args(argv)
    if arguments.repetitions < 1:
        parser.error("--repetitions must be positive")
    distribution = _distribution_root(arguments.distribution)
    if not (distribution / "atlas-manifest.json").is_file():
        parser.error(f"no distribution found at {arguments.distribution}")
    try:
        result = benchmark(
            distribution,
            arguments.repetitions,
            arguments.variants,
            arguments.profile_variants,
        )
    except ValueError as exc:
        parser.error(str(exc))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

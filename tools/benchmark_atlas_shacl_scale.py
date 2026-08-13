"""Time the SHACL phase against a built distribution and gate on regression.

Constraint-shape cost is emergent, not compositional. The Jena spike measured
every constraint in `SkosXlLabelShape` individually fast at 29.3M quads
(literalForm-only 42.3s, +closed 42.5s, sh:class over 590k instances 44.0s) and
the same shape whole at over 1,829s -- so no review of a shapes diff, however
careful, predicts what that diff costs at scale, and pySHACL has the same
exposure. The only instrument that answers is a clock on real data.

This is that clock. It parses one built distribution's packs the way the
validator does, then times `_run_shacl` alone -- not the parse, not the
semantic gates -- and compares the seconds against a recorded baseline
(`tools/atlas-shacl-scale-baseline.json`). Over `toleranceRatio` it fails.

Three honest non-failures, because a slow number is not always a regression:
no baseline for this scale class and mode yet; a baseline whose quad count is
more than `quadCountToleranceRatio` away from what was measured (a different
distribution is not a comparison); and `--write-baseline`, which records the
measurement instead of judging it. Each prints what to run to record a new
number. A machine change invalidates a baseline just as a shapes change does,
so `machine` and `recordedAt` travel with every entry.

Measure with the mode you intend to gate: `REFSPEC_ATLAS_VALIDATION_MODE` is
part of the baseline key, since audit mode and the default red path take
different routes through the same shapes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tools" / "validate.py"
DEFAULT_BASELINE = ROOT / "tools" / "atlas-shacl-scale-baseline.json"
VALIDATION_MODE_ENV = "REFSPEC_ATLAS_VALIDATION_MODE"


def _load_validator() -> ModuleType:
    """Import the binding validator as a module, exactly as the tests do."""

    # The validator imports its siblings (`rdf_canonical`) by bare name, the
    # way a consumer who copied the binding directory would run it.
    if str(VALIDATOR_PATH.parent) not in sys.path:
        sys.path.insert(0, str(VALIDATOR_PATH.parent))
    spec = importlib.util.spec_from_file_location("refspec_atlas_v3_validate", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the Atlas 3.1 validator from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _distribution_root(named: Path) -> Path:
    if (named / "atlas-manifest.json").is_file():
        return named
    return named / "distribution"


def _scale_class(distribution_id: str) -> str:
    """The stable half of a distributionId: `3.1-full-development` and friends.

    The trailing digest moves with every content change, so keying a timing
    baseline on the whole id would retire the baseline on every rebuild -- the
    moment it is most wanted.
    """

    parts = distribution_id.split(":")
    return parts[4] if len(parts) > 4 else distribution_id


def measure(distribution: Path) -> dict[str, Any]:
    """Parse the packs, then time `_run_shacl` over the parsed graphs."""

    validate = _load_validator()
    manifest = json.loads((distribution / "atlas-manifest.json").read_text(encoding="utf-8"))
    graph_ids = {row["role"]: validate.URIRef(row["id"]) for row in manifest["graphs"]}

    parse_started = time.perf_counter()
    _dataset, graphs = validate._parse_packed_dataset(distribution, manifest, graph_ids)
    ontology, shapes = validate._parse_binding_graphs()
    parse_seconds = time.perf_counter() - parse_started

    shacl_started = time.perf_counter()
    validate._run_shacl(graphs, ontology, shapes)
    shacl_seconds = time.perf_counter() - shacl_started

    return {
        "distributionId": manifest["distributionId"],
        "machine": f"{platform.system()}-{platform.machine()}-py{platform.python_version()}",
        "mode": os.environ.get(VALIDATION_MODE_ENV, "default"),
        "packCount": len(manifest["packs"]),
        "parseSeconds": round(parse_seconds, 3),
        "quadCount": sum(pack["content"]["quadCount"] for pack in manifest["packs"]),
        "recordedAt": datetime.now(tz=UTC).date().isoformat(),
        "scaleClass": _scale_class(manifest["distributionId"]),
        "shaclSeconds": round(shacl_seconds, 3),
    }


def _load_baseline(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"measurements": {}, "quadCountToleranceRatio": 1.25, "toleranceRatio": 3.0}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_baseline(path: Path, baseline: dict[str, Any]) -> None:
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution",
        required=True,
        type=Path,
        help="distribution root, or the directory holding it",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record this measurement as the baseline for its scale class and mode",
    )
    parser.add_argument("--note", default="", help="what this measurement is of, for the record")
    arguments = parser.parse_args(argv)

    distribution = _distribution_root(arguments.distribution)
    if not (distribution / "atlas-manifest.json").is_file():
        print(f"shapes scale benchmark: no distribution at {arguments.distribution}")
        return 1

    measurement = measure(distribution)
    key = f"{measurement['scaleClass']}/{measurement['mode']}"
    print(
        f"shapes scale benchmark: {key} -- SHACL {measurement['shaclSeconds']:.1f}s over "
        f"{measurement['quadCount']:,} quads in {measurement['packCount']} pack(s) "
        f"(parse {measurement['parseSeconds']:.1f}s, not gated)"
    )

    baseline = _load_baseline(arguments.baseline)
    recorded = baseline["measurements"].get(key)
    record_hint = (
        f"record it with: uv run python tools/benchmark_atlas_shacl_scale.py "
        f'--distribution {arguments.distribution} --write-baseline --note "..."'
    )

    if arguments.write_baseline:
        baseline["measurements"][key] = {**measurement, "note": arguments.note}
        _write_baseline(arguments.baseline, baseline)
        print(f"shapes scale benchmark: recorded {key} in {arguments.baseline}")
        return 0

    if recorded is None:
        print(f"shapes scale benchmark: no baseline for {key} in {arguments.baseline}; not a verdict")
        print(f"shapes scale benchmark: {record_hint}")
        return 0

    quad_ratio = measurement["quadCount"] / max(1, recorded["quadCount"])
    quad_tolerance = baseline["quadCountToleranceRatio"]
    if not 1 / quad_tolerance <= quad_ratio <= quad_tolerance:
        print(
            f"shapes scale benchmark: baseline {key} was measured over "
            f"{recorded['quadCount']:,} quads, this run over {measurement['quadCount']:,} "
            f"({quad_ratio:.2f}x) -- different scale, not a comparison; not a verdict"
        )
        print(f"shapes scale benchmark: {record_hint}")
        return 0

    tolerance = baseline["toleranceRatio"]
    ratio = measurement["shaclSeconds"] / max(1e-9, recorded["shaclSeconds"])
    summary = (
        f"{measurement['shaclSeconds']:.1f}s against a {recorded['shaclSeconds']:.1f}s baseline "
        f"recorded {recorded['recordedAt']} on {recorded['machine']} ({ratio:.2f}x, "
        f"tolerance {tolerance:.1f}x)"
    )
    if ratio > tolerance:
        print(f"shapes scale benchmark FAIL: {summary}")
        print(
            "shapes scale benchmark: either the shapes change that caused this is not worth its "
            f"cost, or the new cost is accepted and the baseline moves in the same commit -- {record_hint}"
        )
        return 1
    print(f"shapes scale benchmark PASS: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

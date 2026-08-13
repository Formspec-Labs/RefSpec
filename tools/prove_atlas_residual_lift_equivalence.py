"""Run the complete Atlas binding gate with and without the residual lift.

``validate_binding`` checks every corpus case against its committed verdict,
``firstIssue``, and ``shaclComponents`` list. This tool runs that gate in two
fresh child processes: the production batched plan, then the explicit
all-direct-constraints prototype. A pass therefore proves both routes retain
the corpus's operator-visible result, not merely that the green case conforms.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tools" / "validate.py"


def _load_validator() -> ModuleType:
    if str(VALIDATOR_PATH.parent) not in sys.path:
        sys.path.insert(0, str(VALIDATOR_PATH.parent))
    spec = importlib.util.spec_from_file_location("refspec_atlas_v3_equivalence", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the Atlas validator from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _maximum_rss_bytes() -> int:
    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum_rss if sys.platform == "darwin" else maximum_rss * 1024


def _child_gate(prototype: bool) -> dict[str, Any]:
    validate = _load_validator()
    if prototype:
        baseline_plan = validate._batched_shacl_plan

        def prototype_plan(shapes: Any) -> Any:
            return baseline_plan(
                shapes,
                direct_constraints=validate._DIRECT_PROPERTY_CONSTRAINTS,
            )

        validate._batched_shacl_plan = prototype_plan
    started = time.perf_counter()
    result = validate.validate_binding()
    return {
        "maximumRssBytes": _maximum_rss_bytes(),
        "result": result,
        "seconds": time.perf_counter() - started,
    }


def _fork_gate(prototype: bool) -> dict[str, Any]:
    read_descriptor, write_descriptor = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_descriptor)
        try:
            payload = {"gate": _child_gate(prototype)}
        except BaseException as exc:  # noqa: BLE001 - preserve gate failure
            payload = {"error": repr(exc)}
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
        raise RuntimeError(f"binding-gate child exited with wait status {status}")
    payload = json.loads(b"".join(chunks))
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["gate"]


def prove() -> dict[str, Any]:
    if not hasattr(os, "fork"):
        raise RuntimeError("the equivalence proof requires os.fork")
    corpus = json.loads(
        (ROOT / "bindings" / "atlas" / "3.1" / "fixtures" / "corpus.json").read_text(
            encoding="utf-8"
        )
    )
    baseline = _fork_gate(False)
    print(f"baseline gate PASS: {baseline['seconds']:.3f}s", flush=True)
    prototype = _fork_gate(True)
    print(f"prototype gate PASS: {prototype['seconds']:.3f}s", flush=True)
    if baseline["result"] != prototype["result"]:
        raise RuntimeError("baseline and prototype binding-gate summaries differ")
    return {
        "baseline": baseline,
        "caseCount": len(corpus["cases"]),
        "equivalent": True,
        "firstIssueCaseCount": sum("firstIssue" in case for case in corpus["cases"]),
        "prototype": prototype,
        "recordedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "shaclComponentCaseCount": sum(
            "shaclComponents" in case for case in corpus["cases"]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    result = prove()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

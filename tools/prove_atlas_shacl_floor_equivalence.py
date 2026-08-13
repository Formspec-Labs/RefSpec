"""Run the 130-case Atlas binding gate for SHACL-floor prototypes.

Each selected prototype runs in a fresh child process in both validator modes.
``validate_binding`` compares all 130 fixtures with their committed verdicts,
``firstIssue`` codes, and ``shaclComponents`` lists.  A recorded pass therefore
proves the operator-visible refusal behavior, not only green-data acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_shacl_floor_prototypes import ROOT, VARIANTS, install_prototype, load_validator


def _maximum_rss_bytes() -> int:
    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return maximum_rss if sys.platform == "darwin" else maximum_rss * 1024


def _child_gate(name: str, mode: str) -> dict[str, Any]:
    validate = load_validator(f"refspec_atlas_v3_shacl_floor_{name.replace('-', '_')}_{mode}")
    install_prototype(validate, VARIANTS[name])
    if mode == "default":
        os.environ.pop(validate.VALIDATION_MODE_ENV, None)
    else:
        os.environ[validate.VALIDATION_MODE_ENV] = validate.AUDIT_VALIDATION_MODE
    started = time.perf_counter()
    result = validate.validate_binding()
    return {
        "maximumRssBytes": _maximum_rss_bytes(),
        "mode": mode,
        "result": result,
        "seconds": time.perf_counter() - started,
    }


def _fork_gate(name: str, mode: str) -> dict[str, Any]:
    read_descriptor, write_descriptor = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_descriptor)
        try:
            payload = {"gate": _child_gate(name, mode)}
        except BaseException as exc:  # noqa: BLE001 - preserve the exact gate failure
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
        raise RuntimeError(f"equivalence child {child} exited with wait status {status}")
    payload = json.loads(b"".join(chunks))
    if "childError" in payload:
        raise RuntimeError(f"{name}/{mode}: {payload['childError']}")
    return payload["gate"]


def prove(selected_variants: list[str]) -> dict[str, Any]:
    if not hasattr(os, "fork"):
        raise RuntimeError("the SHACL-floor equivalence proof requires os.fork")
    unknown = set(selected_variants) - set(VARIANTS)
    if unknown:
        raise ValueError(f"unknown variants: {sorted(unknown)}")
    corpus = json.loads(
        (ROOT / "bindings" / "atlas" / "3.1" / "fixtures" / "corpus.json").read_text(
            encoding="utf-8"
        )
    )
    results: dict[str, Any] = {}
    for name in selected_variants:
        modes: dict[str, Any] = {}
        for mode in ("default", "audit"):
            modes[mode] = _fork_gate(name, mode)
            print(f"{name}/{mode} PASS: {modes[mode]['seconds']:.3f}s", flush=True)
        if modes["default"]["result"] != modes["audit"]["result"]:
            raise RuntimeError(f"{name} returned different binding summaries across modes")
        results[name] = {"equivalent": True, "modes": modes}
    return {
        "caseCount": len(corpus["cases"]),
        "firstIssueCaseCount": sum("firstIssue" in case for case in corpus["cases"]),
        "recordedAt": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "shaclComponentCaseCount": sum("shaclComponents" in case for case in corpus["cases"]),
        "variants": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS))
    arguments = parser.parse_args(argv)
    try:
        result = prove(arguments.variants)
    except ValueError as exc:
        parser.error(str(exc))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

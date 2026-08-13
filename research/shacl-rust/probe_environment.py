#!/usr/bin/env python3
"""Record the local Rust toolchain and candidate acquisition gate."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


CANDIDATE_PATTERNS = (
    "rudof-*",
    "shacl_ast-*",
    "shacl_ir-*",
    "shacl_rdf-*",
    "shacl_validation-*",
    "srdf-*",
    "shacl-rust-*",
    "oxirs-shacl-*",
)


def run(command: list[str], timeout: float = 15.0) -> dict[str, Any]:
    """Run a diagnostic command without raising on its expected failure."""

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "returnCode": completed.returncode,
            "stderr": completed.stderr,
            "stdout": completed.stdout,
            "timedOut": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returnCode": None,
            "stderr": exc.stderr or "",
            "stdout": exc.stdout or "",
            "timedOut": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    commands = {
        "cargo": run(["cargo", "--version"]),
        "candidateRegistryProbe": run(
            ["cargo", "search", "shacl-rust", "--limit", "1"]
        ),
        "rustc": run(["rustc", "--version", "--verbose"]),
        "vmStat": run(["vm_stat"]),
    }
    cargo_registry = Path.home() / ".cargo" / "registry" / "src"
    candidate_cache_paths = sorted(
        str(path)
        for registry_root in cargo_registry.glob("*")
        for pattern in CANDIDATE_PATTERNS
        for path in registry_root.glob(pattern)
    )
    result = {
        "candidateCache": {
            "patterns": list(CANDIDATE_PATTERNS),
            "paths": candidate_cache_paths,
            "registryRoot": str(cargo_registry),
        },
        "commands": commands,
        "executables": {
            name: shutil.which(name)
            for name in ("cargo", "rudof", "rustc", "shacl-validator")
        },
        "platform": platform.platform(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

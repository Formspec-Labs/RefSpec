#!/usr/bin/env python3
"""Run a bounded command and record its output, wall time, and peak RSS."""

from __future__ import annotations

import argparse
import json
import platform
import resource
import subprocess
import time
from pathlib import Path
from typing import Any


def peak_rss_bytes(usage: resource.struct_rusage) -> tuple[int, str]:
    """Normalize ru_maxrss to bytes and name the source unit."""

    if platform.system() == "Darwin":
        return int(usage.ru_maxrss), "bytes"
    return int(usage.ru_maxrss) * 1024, "kibibytes"


def measure(command: list[str], cwd: Path, timeout: float) -> dict[str, Any]:
    """Run one command with captured output and a hard wall-clock timeout."""

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        timed_out = False
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    elapsed = time.monotonic() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss_bytes, rss_source_unit = peak_rss_bytes(after)

    return {
        "command": command,
        "cwd": str(cwd),
        "elapsedSeconds": round(elapsed, 6),
        "measurement": {
            "peakRssBytes": rss_bytes,
            "peakRssMiB": round(rss_bytes / (1024 * 1024), 3),
            "ruMaxrssBefore": int(before.ru_maxrss),
            "ruMaxrssSourceUnit": rss_source_unit,
            "scope": "maximum resident set reported for child processes",
        },
        "platform": platform.platform(),
        "returnCode": return_code,
        "stderr": stderr,
        "stdout": stdout,
        "timedOut": timed_out,
        "timeoutSeconds": timeout,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    result = measure(command, args.cwd.resolve(), args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result["timedOut"]:
        raise SystemExit(124)
    raise SystemExit(result["returnCode"])


if __name__ == "__main__":
    main()

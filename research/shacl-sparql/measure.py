"""Run one benchmark command and report exact child wall time and peak RSS."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("a command is required after --")

    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    _, status, usage = os.wait4(process.pid, 0)
    finished = time.perf_counter()
    returncode = os.waitstatus_to_exitcode(status)

    if stdout:
        sys.stdout.write(stdout)
        if not stdout.endswith("\n"):
            sys.stdout.write("\n")
    if stderr:
        sys.stderr.write(stderr)
        if not stderr.endswith("\n"):
            sys.stderr.write("\n")
    print(
        json.dumps(
            {
                "command": command,
                "returncode": returncode,
                "wall_seconds": finished - started,
                # On macOS ru_maxrss is bytes. This experiment ran on macOS;
                # retain the native value so no cross-platform guess is hidden.
                "ru_maxrss_native": usage.ru_maxrss,
            },
            sort_keys=True,
        )
    )
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

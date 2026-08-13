#!/usr/bin/env python3
"""Run one probe with a deadline and emit machine-readable resource usage."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--stdout", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    process = subprocess.Popen(
        args.command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()

    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    # macOS reports bytes; Linux reports KiB.
    rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    if args.stdout:
        args.stdout.parent.mkdir(parents=True, exist_ok=True)
        args.stdout.write_bytes(stdout)

    record = {
        "name": args.name,
        "command": args.command,
        "timeout_seconds": args.timeout_seconds,
        "timed_out": timed_out,
        "exit_code": process.returncode,
        "wall_seconds": round(time.monotonic() - started, 3),
        "user_seconds": round(usage.ru_utime, 3),
        "system_seconds": round(usage.ru_stime, 3),
        "max_rss_bytes": rss_bytes,
        "stdout_utf8": stdout[:4096].decode("utf-8", errors="replace"),
        "stderr_utf8": stderr[:4096].decode("utf-8", errors="replace"),
    }
    print(json.dumps(record, sort_keys=True))
    return 124 if timed_out else process.returncode


if __name__ == "__main__":
    raise SystemExit(main())

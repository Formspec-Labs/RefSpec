#!/usr/bin/env python3
"""Run one 600-second-bounded command and sample its macOS RSS trajectory."""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import platform
import re
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


GIB = 1024**3
MIB = 1024**2


class RusageInfoV0(ctypes.Structure):
    """Darwin's public rusage_info_v0 structure from sys/resource.h."""

    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("--sample-seconds", type=float, default=5.0)
    parser.add_argument("--abort-rss-gib", type=float, default=11.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if len(args.command) < 3:
        parser.error("a command is required after --")
    if Path(args.command[0]).name != "timeout" or args.command[1] != "600":
        parser.error("the command must start with exactly: timeout 600")
    if args.sample_seconds <= 0:
        parser.error("--sample-seconds must be positive")
    if not 0 < args.abort_rss_gib < 12:
        parser.error("--abort-rss-gib must be positive and below 12")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def vm_stat() -> dict[str, int | str]:
    try:
        text = subprocess.check_output(["vm_stat"], text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as error:
        return {"error": str(error)}
    page_size_match = re.search(r"page size of (\d+) bytes", text)
    result: dict[str, int | str] = {
        "raw_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    if page_size_match:
        result["page_size_bytes"] = int(page_size_match.group(1))
    for line in text.splitlines():
        match = re.match(r'"?([^":]+)"?:\s+(\d+)\.?$', line)
        if match:
            key = re.sub(r"[^a-z0-9]+", "_", match.group(1).lower()).strip("_")
            result[key] = int(match.group(2))
    return result


def memory_free_percent() -> int | None:
    try:
        text = subprocess.check_output(
            ["memory_pressure"], text=True, stderr=subprocess.STDOUT
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", text)
    return int(match.group(1)) if match else None


def counter_delta(before: dict[str, int | str], after: dict[str, int | str], key: str) -> int | None:
    first = before.get(key)
    last = after.get(key)
    if isinstance(first, int) and isinstance(last, int):
        return last - first
    return None


def load_libproc() -> ctypes.CDLL:
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    library.proc_pid_rusage.restype = ctypes.c_int
    return library


def sample_process(library: ctypes.CDLL, pid: int, elapsed: float) -> dict[str, int | float]:
    info = RusageInfoV0()
    ctypes.set_errno(0)
    result = library.proc_pid_rusage(pid, 0, ctypes.byref(info))
    if result != 0:
        errno = ctypes.get_errno()
        raise ProcessLookupError(errno, os.strerror(errno), pid)
    return {
        "elapsed_seconds": round(elapsed, 3),
        "rss_bytes": info.ri_resident_size,
        "rss_mib": round(info.ri_resident_size / MIB, 3),
        "physical_footprint_bytes": info.ri_phys_footprint,
        "wired_bytes": info.ri_wired_size,
        "pageins": info.ri_pageins,
        "user_time_nanoseconds": info.ri_user_time,
        "system_time_nanoseconds": info.ri_system_time,
    }


def terminate_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    args = parse_args()
    if sys.platform != "darwin":
        raise SystemExit("run_with_rss.py currently requires macOS proc_pid_rusage")

    for path in (args.output, args.stdout, args.stderr):
        if path.exists():
            raise SystemExit(f"refusing to overwrite measurement output: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    helper = Path(__file__).with_name("exec_with_pid.sh").resolve()
    if not helper.is_file():
        raise SystemExit(f"missing PID helper: {helper}")
    pid_file = args.output.parent / f".{args.output.stem}.pid"
    if pid_file.exists():
        raise SystemExit(f"refusing stale PID file: {pid_file}")

    command = list(args.command)
    executed_command = command[:2] + [str(helper), str(pid_file)] + command[2:]
    before_vm = vm_stat()
    before_free = memory_free_percent()
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.monotonic()
    samples: list[dict[str, int | float]] = []
    sample_errors: list[dict[str, int | float | str]] = []
    memory_aborted = False
    target_pid: int | None = None
    library = load_libproc()

    with args.stdout.open("wb") as stdout, args.stderr.open("wb") as stderr:
        process = subprocess.Popen(
            executed_command,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        pid_deadline = time.monotonic() + 10
        while time.monotonic() < pid_deadline and process.poll() is None:
            if pid_file.exists():
                target_pid = int(pid_file.read_text().strip())
                break
            time.sleep(0.01)

        next_sample = time.monotonic()
        abort_bytes = int(args.abort_rss_gib * GIB)
        while process.poll() is None:
            now = time.monotonic()
            if target_pid is not None and now >= next_sample:
                try:
                    sample = sample_process(library, target_pid, now - started)
                    samples.append(sample)
                    if sample["rss_bytes"] >= abort_bytes:
                        memory_aborted = True
                        terminate_group(process)
                        break
                except ProcessLookupError as error:
                    sample_errors.append(
                        {
                            "elapsed_seconds": round(now - started, 3),
                            "error": str(error),
                        }
                    )
                next_sample += args.sample_seconds
            time.sleep(0.05)
        exit_code = process.wait()

    wall_seconds = time.monotonic() - started
    if target_pid is not None:
        try:
            final_sample = sample_process(library, target_pid, wall_seconds)
            if not samples or final_sample["elapsed_seconds"] != samples[-1]["elapsed_seconds"]:
                samples.append(final_sample)
        except ProcessLookupError:
            pass

    if pid_file.exists():
        pid_file.unlink()
    after_vm = vm_stat()
    after_free = memory_free_percent()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_max_rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    peak_sample = max(samples, key=lambda sample: sample["rss_bytes"], default=None)
    record = {
        "schema_version": 1,
        "name": args.name,
        "started_utc": started_utc,
        "host": platform.node(),
        "platform": platform.platform(),
        "logical_command": command,
        "executed_command": executed_command,
        "timeout_seconds": 600,
        "sample_interval_seconds": args.sample_seconds,
        "rss_source": "proc_pid_rusage RUSAGE_INFO_V0 ri_resident_size",
        "ps_sampling_unavailable": True,
        "ps_sampling_error": "managed sandbox returned Operation not permitted for ps on a direct child",
        "abort_rss_gib": args.abort_rss_gib,
        "timeout_pid": process.pid,
        "target_pid": target_pid,
        "exit_code": exit_code,
        "timed_out": exit_code == 124,
        "memory_aborted": memory_aborted,
        "wall_seconds": round(wall_seconds, 3),
        "child_user_seconds": round(usage.ru_utime, 3),
        "child_system_seconds": round(usage.ru_stime, 3),
        "child_max_rss_bytes": child_max_rss_bytes,
        "sampled_peak_rss_bytes": peak_sample["rss_bytes"] if peak_sample else None,
        "sampled_peak_rss_mib": peak_sample["rss_mib"] if peak_sample else None,
        "sampled_peak_elapsed_seconds": peak_sample["elapsed_seconds"] if peak_sample else None,
        "samples": samples,
        "sample_errors": sample_errors,
        "stdout": {
            "path": str(args.stdout),
            "bytes": args.stdout.stat().st_size,
            "sha256": sha256(args.stdout),
        },
        "stderr": {
            "path": str(args.stderr),
            "bytes": args.stderr.stat().st_size,
            "sha256": sha256(args.stderr),
        },
        "system_memory": {
            "free_percent_before": before_free,
            "free_percent_after": after_free,
            "vm_stat_before": before_vm,
            "vm_stat_after": after_vm,
            "pageins_delta": counter_delta(before_vm, after_vm, "pageins"),
            "pageouts_delta": counter_delta(before_vm, after_vm, "pageouts"),
            "swapins_delta": counter_delta(before_vm, after_vm, "swapins"),
            "swapouts_delta": counter_delta(before_vm, after_vm, "swapouts"),
        },
    }
    temporary_output = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temporary_output.replace(args.output)
    print(
        json.dumps(
            {
                "exit_code": exit_code,
                "memory_aborted": memory_aborted,
                "name": args.name,
                "output": str(args.output),
                "sampled_peak_rss_mib": record["sampled_peak_rss_mib"],
                "timed_out": record["timed_out"],
                "wall_seconds": record["wall_seconds"],
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

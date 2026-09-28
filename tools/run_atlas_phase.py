"""Run one exclusive Atlas phase with measured, enforced resource budgets.

macOS records physical footprint separately from RSS. Linux requires a delegated
cgroup v2 parent: memory.max covers descendants and memory.swap.max is explicit.
Receipts distinguish a capacity stop from a command's semantic failure.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

GIB = 1024**3
LOCK_PATH = Path(tempfile.gettempdir()) / f"refspec-atlas-heavy-{os.getuid()}.lock"
STOP_GRACE_SECONDS = 10


def _command_output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=15).strip()


def _process_group(pgid: int) -> list[tuple[int, int, str]]:
    rows = _command_output(["ps", "-axo", "pid=,pgid=,rss=,stat=,sess=,lstart="]).splitlines()
    return [
        (int(pid), int(rss) * 1024, session + "|" + started)
        for row in rows
        for pid, group, rss, state, session, started in [row.split(maxsplit=5)]
        if int(group) == pgid and not state.startswith("Z")
    ]


def _footprint(pids: list[int], scratch: Path) -> int:
    if not pids:
        return 0
    command = ["footprint", "--noCategories", "-j", str(scratch)]
    for pid in pids:
        command.extend(("-p", str(pid)))
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    data = json.loads(scratch.read_text())
    observed = {item["pid"]: item for item in data["processes"]}
    # A process can exit between ps and footprint; only complain about one
    # still in our live group when the measurement did not include it.
    missing = set(pids) - set(observed)
    for pid in missing:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise RuntimeError(f"physical footprint unavailable for live pid {pid}")
    return sum(item["footprint"] for item in observed.values())


def _host_state() -> dict[str, str]:
    commands = (
        {"swap": ["sysctl", "-n", "vm.swapusage"], "pressure": ["memory_pressure", "-Q"], "vm": ["vm_stat"]}
        if sys.platform == "darwin"
        else {"memory": ["cat", "/proc/meminfo"], "pressure": ["cat", "/proc/pressure/memory"]}
    )
    state = {}
    for key, command in commands.items():
        try:
            state[key] = _command_output(command)
        except (OSError, subprocess.SubprocessError):
            state[key] = "unavailable"
    return state


def _disk_bytes(root: Path | None) -> int | None:
    if root is None or not root.exists():
        return None
    return int(_command_output(["du", "-sk", str(root)]).split()[0]) * 1024


def _swap_bytes(state: dict[str, str]) -> int | None:
    match = re.search(r"used = ([\d.]+)([KMGTP])", state.get("swap", ""))
    return int(float(match[1]) * 1024 ** ("KMGTP".index(match[2]) + 1)) if match else None


@contextlib.contextmanager
def exclusive_phase():
    """One cooperative large Atlas job per user, including other worktrees."""
    with LOCK_PATH.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another guarded Atlas phase holds the exclusive resource window") from error
        yield


@contextlib.contextmanager
def _cgroup(parent: Path | None, memory: int, swap: int):
    if sys.platform != "linux":
        yield None
        return
    if parent is None:
        raise ValueError("Linux qualification requires --cgroup-parent (delegated cgroup v2)")
    try:
        filesystem = _command_output(["stat", "-f", "-c", "%T", "--", str(parent)])
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("cannot authenticate cgroup v2 filesystem") from error
    if filesystem != "cgroup2fs":
        raise ValueError("cgroup parent must reside on a cgroup v2 filesystem")
    if (
        not (parent / "cgroup.controllers").is_file()
        or "memory" not in (parent / "cgroup.subtree_control").read_text().split()
    ):
        raise ValueError("cgroup parent must be delegated cgroup v2 with its memory controller enabled")
    group = parent / f"atlas-{os.getpid()}-{time.time_ns()}"
    group.mkdir()
    try:
        (group / "memory.max").write_text(str(memory))
        (group / "memory.swap.max").write_text(str(swap))
        (group / "memory.oom.group").write_text("1")
        yield group
    finally:
        if (group / "cgroup.kill").exists():
            (group / "cgroup.kill").write_text("1")
        deadline = time.monotonic() + 5
        while True:
            try:
                group.rmdir()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)


def _stop_owned_group(process: subprocess.Popen, identities: dict[int, str]) -> None:
    # start_new_session makes this group exclusively ours. Never use a PID
    # retained from a prior invocation, and never signal the caller's group.
    live = _process_group(process.pid)
    if process.poll() is not None and not any(identities.get(pid) == started for pid, _, started in live):
        return
    sessions = {
        started.partition("|")[0] for pid, _, started in live if identities.get(pid) == started or pid == process.pid
    }
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline:
        live = _process_group(process.pid)
        if not live:
            break
        # Children forked during shutdown inherit the same session. Match that
        # live session identity before extending the set we are allowed to stop.
        identities.update({pid: started for pid, _, started in live if started.partition("|")[0] in sessions})
        time.sleep(0.05)
    else:
        live = _process_group(process.pid)
        identities.update({pid: started for pid, _, started in live if started.partition("|")[0] in sessions})
        if any(identities.get(pid) == started for pid, _, started in live):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def run_phase(
    command: list[str],
    *,
    name: str,
    report: Path,
    rss_limit: int,
    footprint_limit: int,
    timeout_seconds: float,
    disk_root: Path | None = None,
    cgroup_parent: Path | None = None,
    swap_limit: int = 0,
    env: dict[str, str] | None = None,
    interval: float = 5,
) -> dict[str, Any]:
    if min(rss_limit, footprint_limit, timeout_seconds, interval) <= 0 or swap_limit < 0:
        raise ValueError("resource/time limits must be positive; swap must be nonnegative")
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        raise ValueError(f"refusing to replace phase receipt: {report}")
    log = report.with_suffix(".log")
    samples = report.with_suffix(".samples.jsonl")
    started = time.time()
    started_clock = time.monotonic()
    cpu_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt: dict[str, Any] = {
        "phase": name,
        "command": command,
        "startedAtUnix": started,
        "status": "incomplete",
        "log": str(log),
        "samples": str(samples),
        "rssLimitBytes": rss_limit,
        "footprintLimitBytes": footprint_limit,
        "linuxSwapLimitBytes": swap_limit,
        "swapPolicy": "permitted within physical-footprint budget; host usage observed"
        if sys.platform == "darwin"
        else "cgroup memory.swap.max enforced",
        "physicalMetric": "physical-footprint" if sys.platform == "darwin" else "cgroup-memory-current",
        "peakRssBytes": 0,
        "peakFootprintBytes": 0,
        "peakDiskBytes": 0,
        "hostBefore": _host_state(),
    }
    process = None
    identities: dict[int, str] = {}
    try:
        with (
            exclusive_phase(),
            _cgroup(cgroup_parent, min(rss_limit, footprint_limit), swap_limit) as group,
            log.open("x") as output,
            samples.open("x") as sample_log,
            tempfile.TemporaryDirectory() as scratch,
        ):

            def enter_cgroup():
                if group is not None:
                    (group / "cgroup.procs").write_text(str(os.getpid()))

            process = subprocess.Popen(
                command,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
                preexec_fn=enter_cgroup if group is not None else None,
            )
            receipt["pid"] = process.pid
            last_disk_sample = 0.0
            while True:
                rows = _process_group(process.pid)
                identities.update({pid: started for pid, _, started in rows})
                now = time.monotonic()
                if now - started_clock >= timeout_seconds:
                    receipt["status"] = "timeout-stopped"
                    _stop_owned_group(process, identities)
                    break
                if process.poll() is not None:
                    remaining = _process_group(process.pid)
                    if time.monotonic() - started_clock >= timeout_seconds:
                        receipt["status"] = "timeout-stopped"
                        identities.update({pid: started for pid, _, started in remaining})
                        _stop_owned_group(process, identities)
                        break
                    if remaining or (group is not None and (group / "cgroup.procs").read_text().strip()):
                        identities.update({pid: started for pid, _, started in remaining})
                        receipt["status"] = "command-left-descendants"
                        if group is not None:
                            (group / "cgroup.kill").write_text("1")
                        _stop_owned_group(process, identities)
                    break
                rss = sum(size for _, size, _ in rows)
                try:
                    footprint = (
                        _footprint([pid for pid, _, _ in rows], Path(scratch) / "footprint.json")
                        if sys.platform == "darwin"
                        else int((group / "memory.current").read_text())
                    )
                except (OSError, subprocess.SubprocessError, RuntimeError):
                    if process.poll() is not None:
                        continue  # Recheck surviving children before accepting a short phase.
                    raise
                receipt["peakRssBytes"] = max(receipt["peakRssBytes"], rss)
                receipt["peakFootprintBytes"] = max(receipt["peakFootprintBytes"], footprint)
                sample = {"elapsedSeconds": now - started_clock, "rssBytes": rss, "footprintBytes": footprint}
                if now - last_disk_sample >= 30:
                    sample["diskBytes"] = _disk_bytes(disk_root)
                    sample["host"] = _host_state()
                    receipt["peakDiskBytes"] = max(receipt["peakDiskBytes"], sample["diskBytes"] or 0)
                    last_disk_sample = now
                sample_log.write(json.dumps(sample, sort_keys=True) + "\n")
                sample_log.flush()
                if rss > rss_limit or footprint > footprint_limit:
                    receipt["status"] = "capacity-stopped"
                    _stop_owned_group(process, identities)
                    break
                if time.monotonic() - started_clock >= timeout_seconds:
                    receipt["status"] = "timeout-stopped"
                    _stop_owned_group(process, identities)
                    break
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=min(interval, max(0, timeout_seconds - (time.monotonic() - started_clock))))
            receipt["exitCode"] = process.wait()
            if group is not None:
                events = dict(line.split() for line in (group / "memory.events").read_text().splitlines())
                receipt["cgroupMemoryEvents"] = events
                if int(events.get("oom_kill", "0")):
                    receipt["status"] = "capacity-stopped"
            if receipt["status"] == "incomplete":
                receipt["status"] = "passed" if receipt["exitCode"] == 0 else "command-failed"
    except BaseException as error:
        receipt["statusBeforeError"] = receipt["status"]
        receipt["status"] = "incomplete"
        receipt["error"] = f"{type(error).__name__}: {error}"
        if process is not None:
            _stop_owned_group(process, identities)
            receipt["exitCode"] = process.returncode
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        cpu_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt.update(
            elapsedSeconds=time.monotonic() - started_clock,
            childCpuSecondsIncludingProbeTools=(
                cpu_end.ru_utime + cpu_end.ru_stime - cpu_start.ru_utime - cpu_start.ru_stime
            ),
            hostAfter=_host_state(),
        )
        before_swap, after_swap = _swap_bytes(receipt["hostBefore"]), _swap_bytes(receipt["hostAfter"])
        receipt["hostSwapUsedDeltaBytes"] = (
            after_swap - before_swap if before_swap is not None and after_swap is not None else None
        )
        report.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rss-gib", type=float, required=True)
    parser.add_argument("--footprint-gib", type=float, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--disk-root", type=Path)
    parser.add_argument("--cgroup-parent", type=Path)
    parser.add_argument(
        "--swap-gib", type=float, default=0, help="Linux cgroup swap budget; macOS permits swap within footprint budget"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    receipt = run_phase(
        command,
        name=args.name,
        report=args.report,
        rss_limit=int(args.rss_gib * GIB),
        footprint_limit=int(args.footprint_gib * GIB),
        timeout_seconds=args.timeout_seconds,
        disk_root=args.disk_root,
        cgroup_parent=args.cgroup_parent,
        swap_limit=int(args.swap_gib * GIB),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

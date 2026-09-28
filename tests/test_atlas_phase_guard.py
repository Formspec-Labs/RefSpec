"""Guard outcomes are measured separately from the command's exit status."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys

import pytest

from tools import run_atlas_phase as guard


@pytest.fixture(autouse=True)
def isolated_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "LOCK_PATH", tmp_path / "test-phase.lock")


@pytest.fixture
def sampled_guard(monkeypatch):
    # Exercise real process/session ownership without requiring macOS probes
    # or a delegated cgroup on the machine that runs the fast test tier.
    monkeypatch.setattr(guard.sys, "platform", "darwin")
    monkeypatch.setattr(guard, "_host_state", dict)
    monkeypatch.setattr(guard, "_footprint", lambda *args: 1)


def _run(tmp_path, code, **overrides):
    options = {
        "name": "test",
        "report": tmp_path / "phase.json",
        "rss_limit": guard.GIB,
        "footprint_limit": guard.GIB,
        "timeout_seconds": 5,
        "interval": 0.02,
    }
    options.update(overrides)
    return guard.run_phase([sys.executable, "-c", code], **options)


@pytest.mark.parametrize(
    "code,expected", [("import time; time.sleep(.1)", "passed"), ("import sys; sys.exit(7)", "command-failed")]
)
def test_exit_status_is_retained(sampled_guard, tmp_path, code, expected):
    result = _run(tmp_path, code)
    assert result["status"] == expected
    assert json.loads((tmp_path / "phase.json").read_text()) == result


def test_footprint_stop_is_not_semantic_rejection(sampled_guard, monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "_footprint", lambda *args: 100)
    result = _run(tmp_path, "import time; time.sleep(60)", footprint_limit=10)
    assert result["status"] == "capacity-stopped"
    assert result["exitCode"] != 0


def test_timeout_stops_only_owned_group(sampled_guard, tmp_path):
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        result = _run(tmp_path, "import time; time.sleep(60)", timeout_seconds=0.05)
        assert result["status"] == "timeout-stopped"
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait()


def test_missing_linux_resource_scope_refuses_to_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.sys, "platform", "linux")
    monkeypatch.setattr(guard, "_host_state", dict)
    result = _run(tmp_path, 'raise AssertionError("must not run")')
    assert result["status"] == "incomplete"
    assert "cgroup-parent" in result["error"]
    assert "pid" not in result


def test_exclusive_window_rejects_second_phase(sampled_guard, tmp_path):
    with guard.exclusive_phase():
        result = _run(tmp_path, 'raise AssertionError("must not run")')
    assert result["status"] == "incomplete"
    assert "exclusive resource window" in result["error"]
    assert "pid" not in result


def test_parent_success_cannot_hide_live_child(sampled_guard, tmp_path):
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess, sys; from pathlib import Path; "
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
        f"Path({str(pid_file)!r}).write_text(str(p.pid))"
    )
    result = _run(tmp_path, code)
    assert result["status"] == "command-left-descendants"
    assert not guard._process_group(result["pid"])


def test_timeout_shorter_than_poll_interval_is_enforced(sampled_guard, monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "STOP_GRACE_SECONDS", 0.15)
    result = _run(tmp_path, "import time; time.sleep(2)", timeout_seconds=0.15, interval=5)
    assert result["status"] == "timeout-stopped"
    assert result["elapsedSeconds"] < 1
    assert not guard._process_group(result["pid"])


def test_shutdown_catches_child_forked_by_sigterm_handler(sampled_guard, monkeypatch, tmp_path):
    import os
    import signal
    import textwrap

    monkeypatch.setattr(guard, "STOP_GRACE_SECONDS", 0.2)
    child_file = tmp_path / "shutdown-child.pid"
    code = textwrap.dedent(f"""
        import os, signal, time
        from pathlib import Path
        def shutdown(signum, frame):
            child = os.fork()
            if child == 0:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                Path({str(child_file)!r}).write_text(str(os.getpid()))
                time.sleep(60)
                os._exit(0)
            os._exit(0)
        signal.signal(signal.SIGTERM, shutdown)
        time.sleep(60)
    """)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    result = None
    try:
        result = _run(tmp_path, code, timeout_seconds=0.3)
        assert child_file.is_file(), "the SIGTERM handler did not exercise its fork"
        assert result["status"] == "timeout-stopped"
        assert not guard._process_group(result["pid"])
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait()
        if result is not None:
            # Reap only the test-owned session if the regression leaves it live.
            for pid, _, _ in guard._process_group(result["pid"]):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)


def test_regular_directory_is_not_a_linux_resource_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.sys, "platform", "linux")
    monkeypatch.setattr(guard, "_host_state", dict)
    parent = tmp_path / "ordinary-directory"
    parent.mkdir()
    result = _run(tmp_path, 'raise AssertionError("must not launch")', cgroup_parent=parent)
    assert result["status"] == "incomplete"
    assert "pid" not in result
    assert list(parent.iterdir()) == []


def test_regular_files_cannot_impersonate_cgroup_controls(monkeypatch, tmp_path):
    monkeypatch.setattr(guard.sys, "platform", "linux")
    parent = tmp_path / "fake-cgroup"
    parent.mkdir()
    (parent / "cgroup.controllers").write_text("memory")
    (parent / "cgroup.subtree_control").write_text("memory")
    with pytest.raises(ValueError, match="cgroup"), guard._cgroup(parent, guard.GIB, 0) as group:
        # If validation wrongly enters, remove only its test-owned regular
        # files so this negative regression does not spend five seconds in cleanup.
        for child in group.iterdir():
            child.unlink()


def test_cleanup_error_cannot_preserve_passed_receipt(sampled_guard, monkeypatch, tmp_path):
    import contextlib

    @contextlib.contextmanager
    def broken_cleanup(*args):
        try:
            yield None
        finally:
            raise RuntimeError("deliberate resource cleanup failure")

    monkeypatch.setattr(guard, "_cgroup", broken_cleanup)
    result = _run(tmp_path, "pass")
    assert result["statusBeforeError"] == "passed"
    assert result["status"] == "incomplete"
    assert result["exitCode"] == 0
    assert "deliberate resource cleanup failure" in result["error"]
    assert json.loads((tmp_path / "phase.json").read_text()) == result


def test_child_first_seen_at_shutdown_deadline_is_still_owned(monkeypatch):
    import signal
    from types import SimpleNamespace

    # The tracked parent exits and forks a child between the last grace-period
    # snapshot and the final snapshot. Its session identity proves ownership.
    process = SimpleNamespace(pid=12345, poll=lambda: None, wait=lambda timeout: 0)
    snapshots = iter([[(12345, 1, "session-a|parent-start")], [(12346, 1, "session-a|child-start")]])
    ticks = iter([0.0, 1.0])
    signals = []
    monkeypatch.setattr(guard, "STOP_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(guard, "_process_group", lambda pgid: next(snapshots))
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(guard.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    guard._stop_owned_group(process, {12345: "session-a|parent-start"})
    assert signals == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]


def test_slow_process_probe_cannot_hide_elapsed_deadline(sampled_guard, monkeypatch, tmp_path):
    import time

    original = guard._process_group
    first = True

    def delayed(pgid):
        nonlocal first
        if first:
            first = False
            time.sleep(0.15)
        return original(pgid)

    monkeypatch.setattr(guard, "_process_group", delayed)
    result = _run(tmp_path, "pass", timeout_seconds=0.05)
    assert result["status"] == "timeout-stopped"

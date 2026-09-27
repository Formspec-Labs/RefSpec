"""A suite run inside another repository's git context leaves that repository alone.

``conftest._no_inherited_git_repository`` drops, for the whole session, the
variables that point git at a repository. These run two real tests that make
their own repositories -- one runs ``git -C <own> config`` and ``commit``, the
other commits with ``cwd=<own>`` -- in a pytest subprocess whose parent
environment points ``GIT_DIR`` at a throwaway "caller" repository under
``tmp_path``, never this checkout. The control runs the same two tests with
``--noconftest`` and requires the caller to CHANGE, so the comparison is shown
able to see the write it guards against.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The two tests that wrote into the caller's repository on 2026-09-27.
SUBJECTS = (
    "tests/test_hand_validated_interpretations.py::test_a_committed_unmodified_witness_loads",
    "tests/test_unified_agenda_parquet.py::test_commit_is_none_when_the_repository_does_not_track_this_module",
)


def _caller_git_dir(root: Path) -> Path:
    """A throwaway repository with one commit, standing in for whoever ran the suite."""

    root.mkdir()
    for arguments in (("init", "-q", "-b", "main"), ("commit", "-q", "--allow-empty", "-m", "the caller's commit")):
        subprocess.run(
            ["git", "-c", "user.email=caller@example.invalid", "-c", "user.name=caller", "-c", "commit.gpgsign=false", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
        )
    return root / ".git"


def _config_and_refs(git_dir: Path) -> dict[str, bytes]:
    """The caller's config, HEAD and every ref, byte for byte."""

    paths = [git_dir / "config", git_dir / "HEAD", git_dir / "packed-refs", *sorted((git_dir / "refs").rglob("*"))]
    return {path.relative_to(git_dir).as_posix(): path.read_bytes() for path in paths if path.is_file()}


def _run_subjects(tmp_path: Path, caller: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """Run SUBJECTS in a fresh pytest whose inherited environment names the caller's repository."""

    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "inner"), *options, *SUBJECTS],
        cwd=ROOT,
        env={**os.environ, "GIT_DIR": str(caller)},
        check=False,
        capture_output=True,
        text=True,
    )


def test_a_caller_git_dir_is_left_untouched_by_tests_that_commit(tmp_path: Path) -> None:
    caller = _caller_git_dir(tmp_path / "caller")
    before = _config_and_refs(caller)

    result = _run_subjects(tmp_path, caller)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout, result.stdout
    assert _config_and_refs(caller) == before


def test_without_the_conftest_the_same_tests_write_into_the_caller(tmp_path: Path) -> None:
    caller = _caller_git_dir(tmp_path / "caller")
    before = _config_and_refs(caller)

    _run_subjects(tmp_path, caller, "--noconftest")

    after = _config_and_refs(caller)
    assert after != before, "the hazard did not reproduce, so the test above proves nothing"
    assert after["config"] != before["config"] and after["refs/heads/main"] != before["refs/heads/main"]

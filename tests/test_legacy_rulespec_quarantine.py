"""The retired combined dependency remains runnable from linked worktrees."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def _git(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_legacy_guard_accepts_a_clean_linked_worktree(
    tmp_path: Path,
    legacy_checkout_guard: Callable[..., Path],
) -> None:
    source = tmp_path / "source"
    linked = tmp_path / "linked"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "refspec-tests@example.invalid")
    _git(source, "config", "user.name", "RefSpec tests")
    (source / "proof.txt").write_text("pinned\n", encoding="utf-8")
    _git(source, "add", "proof.txt")
    _git(source, "commit", "-m", "test fixture")
    revision = _git(source, "rev-parse", "HEAD")
    _git(source, "worktree", "add", "--detach", str(linked), revision)

    assert (linked / ".git").is_file()
    assert legacy_checkout_guard(
        linked,
        expected_revision=revision,
    ) == linked.resolve()

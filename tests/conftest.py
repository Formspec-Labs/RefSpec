"""Shared fixtures for RefSpec's current and historical dependency seams."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESPEC_DIR = REFSPEC_ROOT.parents[1] / "rulespec"
LEGACY_DEPENDENCY_MANIFEST = (
    REFSPEC_ROOT / "profiles" / "rulespec-dependency.json"
)


def _git(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )


def require_legacy_rulespec_checkout(
    path: Path,
    *,
    expected_revision: str | None = None,
) -> Path:
    """Require the clean checkout named by the historical combined pin."""

    selected = path.resolve()
    inside = _git(selected, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != "true":
        pytest.skip(
            f"legacy combined Rulespec checkout is unavailable: {selected}"
        )

    if expected_revision is None:
        manifest = json.loads(
            LEGACY_DEPENDENCY_MANIFEST.read_text(encoding="utf-8")
        )
        expected_revision = manifest["evidenceRevision"]

    head = _git(selected, "rev-parse", "HEAD")
    actual = head.stdout.strip()
    if head.returncode or actual != expected_revision:
        pytest.skip(
            "legacy combined RefSpec/Rulespec proof requires exact Rulespec "
            f"revision {expected_revision}; selected checkout is "
            f"{actual or 'unreadable'}"
        )

    status = _git(selected, "status", "--porcelain")
    if status.returncode or status.stdout.strip():
        pytest.skip(
            "legacy combined RefSpec/Rulespec proof requires a clean exact "
            "Rulespec checkout"
        )
    return selected


@pytest.fixture(scope="session")
def legacy_rulespec_checkout() -> Path:
    """Return the opt-in exact pre-split Rulespec checkout or skip."""

    configured = os.environ.get("RULESPEC_LEGACY_DIR") or os.environ.get(
        "RULESPEC_DIR"
    )
    selected = (
        Path(configured) if configured else DEFAULT_RULESPEC_DIR
    )
    return require_legacy_rulespec_checkout(selected)


@pytest.fixture
def legacy_checkout_guard() -> Callable[..., Path]:
    """Expose the linked-worktree-aware guard for its narrow regression."""

    return require_legacy_rulespec_checkout

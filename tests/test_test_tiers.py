"""The suite's tiers: every test lands in exactly one, CI runs the fast one, and the rest are local."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from conftest import TIERS, tier_of

ROOT = Path(__file__).resolve().parents[1]


class _Item:
    """Just enough of a pytest item for tier_of."""

    def __init__(self, *markers: str) -> None:
        self.markers = set(markers)

    def get_closest_marker(self, name: str):
        return name if name in self.markers else None


@pytest.mark.parametrize(
    ("markers", "tier"),
    [
        ((), "fast"),
        (("no_artifact",), "fast"),
        (("slow",), "slow"),
        (("release_tier",), "slow"),
        (("full_atlas",), "full-atlas"),
        (("full_atlas", "slow"), "full-atlas"),
        (("full_atlas", "release_tier"), "full-atlas"),
    ],
)
def test_each_marker_combination_lands_in_exactly_one_tier(markers: tuple[str, ...], tier: str) -> None:
    assert tier_of(_Item(*markers)) == tier
    assert tier in TIERS


def _tier_targets() -> dict[str, str]:
    """Map each Makefile target that runs ``--tier X`` to X."""

    targets: dict[str, str] = {}
    current = None
    for line in (ROOT / "Makefile").read_text(encoding="utf-8").splitlines():
        header = re.match(r"^([A-Za-z0-9_.-]+):", line)
        if header:
            current = header.group(1)
        found = re.search(r"--tier (\S+)", line)
        if found and current:
            targets[current] = found.group(1)
    return targets


def test_every_tier_has_one_make_target_and_only_the_fast_tier_runs_in_ci() -> None:
    """Every tier has one `make` target; CI runs the fast one on pushes and pull requests, and no other.

    The slow and full-Atlas tiers are local work (REF-071): an hour of
    real-data tests per commit on a 16 GB runner they outgrow buys little.
    This keeps a heavy tier from drifting back into CI unannounced, and keeps
    the fast tier from drifting out of it.
    """
    targets = _tier_targets()
    assert sorted(targets.values()) == sorted(TIERS), "each tier needs exactly one make target"

    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]  # PyYAML reads the key `on` as True
    jobs_by_tier: dict[str, list[str]] = {tier: [] for tier in TIERS}
    for name, job in workflow["jobs"].items():
        assert str(job.get("if", "")).strip() not in {"false", "${{ false }}"}, f"job {name} never runs"
        for step in job["steps"]:
            for target, tier in targets.items():
                if re.search(rf"\bmake {re.escape(target)}\b", step.get("run", "")):
                    jobs_by_tier[tier].append(name)
    assert len(jobs_by_tier["fast"]) == 1, jobs_by_tier
    assert jobs_by_tier["slow"] == [] and jobs_by_tier["full-atlas"] == [], "a heavy tier is running in CI"
    assert {"push", "pull_request"} <= set(triggers)
    assert "if" not in workflow["jobs"][jobs_by_tier["fast"][0]], "the fast tier must run on every push"

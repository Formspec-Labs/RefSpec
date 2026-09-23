"""The skip allowlist check: what it accepts, and what it refuses in both directions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import check_skips

ALLOWED_ID = "tests.test_a::test_allowed"


def _report(tmp_path: Path, cases: dict[str, str | None]) -> Path:
    """Write a JUnit report: each case id maps to None (passed), "skipped" or "xfail"."""

    body = []
    for case_id, outcome in cases.items():
        classname, name = case_id.split("::")
        inner = "" if outcome is None else f'<skipped type="pytest.{outcome}" message="{outcome}"/>'
        body.append(f'<testcase classname="{classname}" name="{name}">{inner}</testcase>')
    report = tmp_path / "report.xml"
    report.write_text(f"<testsuites><testsuite>{''.join(body)}</testsuite></testsuites>", encoding="utf-8")
    return report


def _allowlist(tmp_path: Path, allowed: dict[str, str]) -> Path:
    path = tmp_path / "allowed.json"
    path.write_text(json.dumps({"fast": allowed}), encoding="utf-8")
    return path


def _run(report: Path, allowlist: Path) -> int:
    return check_skips.main([str(report), "--tier", "fast", "--allowlist", str(allowlist)])


def test_a_listed_skip_and_a_listed_xfail_pass(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path, {ALLOWED_ID: "why", "tests.test_a::test_known": "why"})
    report = _report(
        tmp_path, {ALLOWED_ID: "skip", "tests.test_a::test_known": "xfail", "tests.test_a::test_ran": None}
    )
    assert _run(report, allowlist) == 0


def test_an_unlisted_skip_fails_even_when_the_count_is_unchanged(tmp_path: Path) -> None:
    """One skip swapped for another: a count would pass this, the list does not."""

    allowlist = _allowlist(tmp_path, {ALLOWED_ID: "why"})
    report = _report(tmp_path, {ALLOWED_ID: None, "tests.test_a::test_new_skip": "skip"})
    assert _run(report, allowlist) == 1


def test_a_listed_test_that_ran_is_stale_and_fails(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path, {ALLOWED_ID: "why"})
    assert _run(_report(tmp_path, {ALLOWED_ID: None}), allowlist) == 1


def test_a_symlinked_report_and_an_unknown_tier_are_refused(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path, {})
    report = _report(tmp_path, {ALLOWED_ID: None})
    link = tmp_path / "link.xml"
    link.symlink_to(report)
    with pytest.raises(SystemExit):
        _run(link, allowlist)
    with pytest.raises(SystemExit):
        check_skips.main([str(report), "--tier", "slow", "--allowlist", str(allowlist)])


def test_the_committed_allowlist_names_every_tier_with_a_reason() -> None:
    allowlists = json.loads(check_skips.ALLOWLIST.read_text(encoding="utf-8"))
    from conftest import TIERS

    assert set(allowlists) == set(TIERS)
    assert all(isinstance(reason, str) and reason.strip() for tier in allowlists.values() for reason in tier.values())

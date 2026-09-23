"""Fail a test run whose skipped or xfailed tests differ from the tier's frozen allowlist.

A green run reports the same word whether one test skipped or two hundred did,
and a deselection that quietly removes coverage looks exactly like a pass.
This used to be a skip budget, a count recorded in ``plans/atlas-3.0-lineage.md``
item 5; REF-071 replaced it with a list, because a count cannot see one skip
swapped for another, and because nothing skips for an absent input any more.

``tests/allowed_skips.json`` names, per tier (``conftest.TIERS``), each test that
may skip or xfail and why. This reads the JUnit XML ``pytest --junitxml`` writes
-- a structured record rather than a parse of the summary line, refusing a
missing or symlinked report -- and fails in both directions: a skip or xfail
the list does not name, and a listed test that ran, whose entry is then stale
and must leave the list in the same commit that earns it.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ALLOWLIST = Path(__file__).resolve().parents[1] / "tests" / "allowed_skips.json"


def skipped_test_ids(report: Path) -> list[str]:
    """Read the skipped and xfailed test identities out of one JUnit XML report."""

    root = ElementTree.parse(report).getroot()
    skipped = []
    for case in root.iter("testcase"):
        if case.find("skipped") is None:
            continue
        classname = case.get("classname", "")
        name = case.get("name", "")
        skipped.append(f"{classname}::{name}" if classname else name)
    return sorted(skipped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JUnit XML written by pytest --junitxml")
    parser.add_argument("--tier", required=True, help="the tier the report ran (conftest.TIERS)")
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    args = parser.parse_args(argv)

    if args.report.is_symlink() or not args.report.is_file():
        parser.error(f"test report is not a regular file: {args.report}")
    allowlists = json.loads(args.allowlist.read_text(encoding="utf-8"))
    if args.tier not in allowlists:
        parser.error(f"{args.allowlist} has no list for tier {args.tier!r}")
    allowed = allowlists[args.tier]

    skipped = set(skipped_test_ids(args.report))
    unlisted = sorted(skipped - set(allowed))
    stale = sorted(set(allowed) - skipped)
    for test_id in sorted(skipped & set(allowed)):
        print(f"allowed skip {test_id}: {allowed[test_id]}")
    for test_id in unlisted:
        print(f"unlisted skip {test_id}", file=sys.stderr)
    for test_id in stale:
        print(f"stale allowlist entry {test_id}: it ran; remove it from {args.allowlist.name}", file=sys.stderr)
    print(f"{args.tier}: {len(skipped)} skipped or xfailed, {len(allowed)} allowed")
    return 1 if unlisted or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())

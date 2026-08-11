"""Fail a test run whose skipped-test count exceeds the recorded budget.

Most skips in this suite name a pinned capture under the gitignored ``output/``
tree, so a clean clone legitimately skips a fixed set of tests. Nothing else
notices when that set grows: an unbudgeted green run reports the same word
whether one test skipped or two hundred did, and a deselection that quietly
removes coverage looks exactly like a pass.

The budget is the number of skips a clean clone produces, recorded in
``PLAN.md`` item 5 beside how it was measured. This script reads the JUnit XML
that ``pytest --junitxml`` writes -- a structured count rather than a parse of
the summary line -- and fails when the run skipped more tests than that.

Under budget is not a failure: it means coverage grew, and the budget should be
lowered in the same commit that earns it.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path


def skipped_test_ids(report: Path) -> list[str]:
    """Read the skipped test identities out of one JUnit XML report."""

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
    parser.add_argument(
        "--budget",
        type=int,
        required=True,
        help="the largest number of skipped tests this run may report",
    )
    args = parser.parse_args(argv)

    if args.budget < 0:
        parser.error("skip budget must not be negative")
    if args.report.is_symlink() or not args.report.is_file():
        parser.error(f"test report is not a regular file: {args.report}")

    skipped = skipped_test_ids(args.report)
    for test_id in skipped:
        print(f"skipped {test_id}")
    print(f"skipped {len(skipped)} of budget {args.budget}")
    if len(skipped) > args.budget:
        print(
            f"skip budget exceeded: {len(skipped)} skipped, {args.budget} budgeted",
            file=sys.stderr,
        )
        return 1
    if len(skipped) < args.budget:
        print(
            f"skip budget is now loose: {len(skipped)} skipped against a budget of "
            f"{args.budget}; lower the budget in PLAN.md item 5"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

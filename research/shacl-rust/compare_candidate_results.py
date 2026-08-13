#!/usr/bin/env python3
"""Compare candidate Atlas results with the sealed corpus case by case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FIELDS = ("expected", "firstIssue", "shaclComponents")


def cases_by_id(document: Any, source: Path) -> dict[str, dict[str, Any]]:
    """Normalize a document containing a cases list into a map keyed by ID."""

    cases = document.get("cases") if isinstance(document, dict) else document
    if not isinstance(cases, list):
        raise ValueError(f"{source}: expected a JSON object with 'cases' or a list")
    normalized: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError(f"{source}: every case must be an object with a string id")
        case_id = case["id"]
        if case_id in normalized:
            raise ValueError(f"{source}: duplicate case id {case_id!r}")
        normalized[case_id] = case
    return normalized


def comparable(case: dict[str, Any]) -> dict[str, Any]:
    """Select the fields consumers observe, preserving absent values as null."""

    return {field: case.get(field) for field in FIELDS}


def compare(expected_path: Path, actual_path: Path) -> dict[str, Any]:
    """Compare exact case verdicts and refusal identities."""

    expected = cases_by_id(json.loads(expected_path.read_bytes()), expected_path)
    actual = cases_by_id(json.loads(actual_path.read_bytes()), actual_path)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    mismatches = []
    for case_id in sorted(expected.keys() & actual.keys()):
        expected_values = comparable(expected[case_id])
        actual_values = comparable(actual[case_id])
        if expected_values != actual_values:
            mismatches.append(
                {
                    "actual": actual_values,
                    "expected": expected_values,
                    "id": case_id,
                }
            )
    agreement_count = len(expected) - len(missing) - len(mismatches)
    return {
        "actualCaseCount": len(actual),
        "agreementCount": agreement_count,
        "exactParity": not missing and not extra and not mismatches,
        "expectedCaseCount": len(expected),
        "extraCaseIds": extra,
        "fieldsCompared": list(FIELDS),
        "mismatchCount": len(mismatches),
        "mismatches": mismatches,
        "missingCaseIds": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = compare(args.expected.resolve(), args.actual.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not result["exactParity"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

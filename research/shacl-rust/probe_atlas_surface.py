#!/usr/bin/env python3
"""Record the Atlas 3.1 SHACL surface and sealed-corpus identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_TERMS = (
    "class",
    "closed",
    "datatype",
    "equals",
    "in",
    "minCount",
    "node",
    "pattern",
    "xone",
)


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(root: Path, *args: str) -> str:
    """Read one stable value from the local checkout."""

    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def atlas_surface(root: Path) -> dict[str, Any]:
    """Measure the checked-out Atlas shape graph and corpus manifest."""

    binding = root / "bindings" / "atlas" / "3.1"
    shapes_path = binding / "shapes" / "atlas.shacl.ttl"
    corpus_path = binding / "fixtures" / "corpus.json"
    ontology_path = binding / "ontology" / "atlas.ttl"
    requirements_path = binding / "requirements.txt"

    shapes = shapes_path.read_text(encoding="utf-8")
    corpus = json.loads(corpus_path.read_bytes())
    cases = corpus["cases"]
    expected_counts = Counter(case["expected"] for case in cases)
    issue_counts = Counter(case.get("firstIssue", "<none>") for case in cases)
    component_counts = Counter(
        component
        for case in cases
        for component in case.get("shaclComponents", ())
    )

    required_occurrences = {
        term: len(re.findall(rf"(?<![\w-])sh:{re.escape(term)}\b", shapes))
        for term in REQUIRED_TERMS
    }
    sequence_paths = len(re.findall(r"(?<![\w-])sh:path\s*\(", shapes))
    sequence_paths_with_equals = len(
        re.findall(r"sh:path\s*\([^)]*\)[^\]]*?sh:equals\b", shapes, re.DOTALL)
    )

    return {
        "binding": {
            "corpusVersion": corpus["version"],
            "gitCommit": git_value(root, "rev-parse", "HEAD"),
            "gitCommitDate": git_value(root, "show", "-s", "--format=%cI", "HEAD"),
        },
        "corpus": {
            "caseCount": len(cases),
            "expectedCounts": dict(sorted(expected_counts.items())),
            "firstIssueCounts": dict(sorted(issue_counts.items())),
            "shaclCaseCount": sum(case.get("firstIssue") == "shacl.data" for case in cases),
            "shaclComponentCaseCount": sum("shaclComponents" in case for case in cases),
            "shaclComponentCounts": dict(sorted(component_counts.items())),
            "uniqueShaclComponents": sorted(component_counts),
        },
        "files": {
            str(path.relative_to(root)): sha256(path)
            for path in (corpus_path, ontology_path, requirements_path, shapes_path)
        },
        "shapeGraph": {
            "nodeShapeCount": len(
                re.findall(r"\ba\s+sh:NodeShape\s*;", shapes)
            ),
            "propertyShapeCount": len(re.findall(r"\bsh:property\s*\[", shapes)),
            "requiredTermOccurrences": required_occurrences,
            "sequencePathCount": sequence_paths,
            "sequencePathsWithEqualsCount": sequence_paths_with_equals,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="RefSpec checkout to inspect",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()

    result = atlas_surface(args.root.resolve())
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()

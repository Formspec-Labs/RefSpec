#!/usr/bin/env python
"""Canonicalize two SHACL ValidationReports and diff them.

Implements the plan's canonicalization rule -- sort by focusNode / sourceShape /
path -- and reduces each result to the tuple a receipt could safely embed. Blank
-node source shapes are the interesting case: both engines emit an anonymous
`sh:sourceShape` for an inline `sh:property` shape, and the bnode label differs
per engine AND per run, so the raw report can never be digested. The tuple below
substitutes the shape's own (path, constraint-parameters) signature instead.

Usage: compare_reports.py <jena-report.ttl> <pyshacl-report.ttl>
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import BNode, Graph
from rdflib.namespace import SH


def shape_key(graph: Graph, shape: object) -> str:
    """A run-stable name for a source shape, including anonymous ones."""
    if not isinstance(shape, BNode):
        return str(shape)
    parts = sorted(f"{p}={o}" for p, o in graph.predicate_objects(shape))
    return "_:[" + ";".join(parts) + "]" if parts else "_:[opaque]"


def canonical(path: Path) -> list[tuple[str, ...]]:
    graph = Graph()
    graph.parse(path, format="turtle")
    rows = []
    for result in graph.subjects(None, SH.ValidationResult):
        rows.append(
            (
                str(next(graph.objects(result, SH.focusNode), "")),
                shape_key(graph, next(graph.objects(result, SH.sourceShape), None)),
                str(next(graph.objects(result, SH.resultPath), "")),
                str(next(graph.objects(result, SH.sourceConstraintComponent), "")),
                str(next(graph.objects(result, SH.value), "")),
                str(next(graph.objects(result, SH.resultSeverity), "")),
            )
        )
    return sorted(rows)


def main() -> None:
    left, right = canonical(Path(sys.argv[1])), canonical(Path(sys.argv[2]))
    print(f"jena results:    {len(left)}")
    print(f"pyshacl results: {len(right)}")
    for label, rows in (("JENA", left), ("PYSHACL", right)):
        for row in rows:
            print(f"{label}\tfocus={row[0]}\n\tshape={row[1]}\n\tpath={row[2]}\n\tcomponent={row[3]}\n\tvalue={row[4]}\n\tseverity={row[5]}")
    only_left = [r for r in left if r not in right]
    only_right = [r for r in right if r not in left]
    print(f"\nidentical after canonicalization: {left == right}")
    if only_left:
        print(f"jena-only: {only_left}")
    if only_right:
        print(f"pyshacl-only: {only_right}")
    # Same question, ignoring the source-shape identity (the one field whose
    # spelling is engine-specific for anonymous shapes).
    trim_left = sorted((r[0], r[2], r[3], r[4], r[5]) for r in left)
    trim_right = sorted((r[0], r[2], r[3], r[4], r[5]) for r in right)
    print(f"identical ignoring sourceShape identity: {trim_left == trim_right}")


if __name__ == "__main__":
    main()

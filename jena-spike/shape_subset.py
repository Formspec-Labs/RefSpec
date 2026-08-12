#!/usr/bin/env python
"""Emit the shapes graph with targets kept on exactly one node shape.

The full-scale Jena run is super-linear against staging, and the useful question
is which constraint carries it. Deleting every sh:target* triple except one
shape's leaves the graph otherwise byte-for-byte the same -- referenced value
shapes, sh:node links, prefixes -- so each run isolates one shape's cost over
the identical data without changing how that shape is evaluated.

Usage: shape_subset.py <shape-local-name> <out.ttl>
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import SH

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
SHAPES = REPO / "bindings/atlas/3.1/shapes/atlas.shacl.ttl"
ATLAS = "https://refspec.org/ns/atlas/v3#"

TARGET_PREDICATES = (SH.targetClass, SH.targetNode, SH.targetSubjectsOf, SH.targetObjectsOf)


def main() -> None:
    keep = URIRef(ATLAS + sys.argv[1])
    out = Path(sys.argv[2])
    graph = Graph()
    graph.parse(SHAPES, format="turtle")
    kept = 0
    for predicate in TARGET_PREDICATES:
        for subject, obj in list(graph.subject_objects(predicate)):
            if subject == keep:
                kept += 1
            else:
                graph.remove((subject, predicate, obj))
    if kept == 0:
        raise SystemExit(f"{keep} declares no targets")
    out.write_bytes(graph.serialize(format="turtle", encoding="utf-8"))
    print(f"kept {kept} target triples on {keep}")


if __name__ == "__main__":
    main()

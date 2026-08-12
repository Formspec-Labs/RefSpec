#!/usr/bin/env python
"""Run pySHACL over the same flat view file Jena gets, with validate.py's settings.

Mirrors `validate.py:_validate_shacl_data` exactly (inference="none",
inplace=True, advanced=False, abort_on_first=False, allow_infos=False,
allow_warnings=False, meta_shacl=False) and `_run_shacl`'s namespace binding.
The data graph is read from a flat N-Triples file that already contains the
data-plus-inoculated-ontology union, so both engines see byte-identical input.

Usage: pyshacl_run.py <view.nt> <report-out.ttl> [shapes.ttl]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import Graph

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
SHAPES = REPO / "bindings/atlas/3.1/shapes/atlas.shacl.ttl"
ONTOLOGY = REPO / "bindings/atlas/3.1/ontology/atlas.ttl"


def main() -> None:
    view_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    shapes_path = Path(sys.argv[3]) if len(sys.argv) > 3 else SHAPES

    t0 = time.perf_counter()
    shapes = Graph()
    shapes.parse(shapes_path, format="turtle")
    ontology = Graph()
    ontology.parse(ONTOLOGY, format="turtle")
    data = Graph()
    data.parse(view_path, format="nt")
    for prefix, namespace in ontology.namespaces():
        data.namespace_manager.bind(prefix, namespace)
    t1 = time.perf_counter()
    print(f"parse: {len(data)} triples in {t1 - t0:.2f}s", flush=True)

    conforms, results_graph, report = shacl_validate(
        data,
        shacl_graph=shapes,
        inference="none",
        inplace=True,
        # validate.py pins advanced=False; the synthetic SHACL-SPARQL benchmark
        # needs SHACL-AF, so that one run opts in via the environment.
        advanced=os.environ.get("SPIKE_PYSHACL_ADVANCED") == "1",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
    )
    t2 = time.perf_counter()
    print(f"validate: conforms={conforms} in {t2 - t1:.2f}s", flush=True)
    out_path.write_bytes(results_graph.serialize(format="turtle", encoding="utf-8"))
    Path(str(out_path) + ".text").write_text(str(report), encoding="utf-8")
    print(f"total: {time.perf_counter() - t0:.2f}s", flush=True)


if __name__ == "__main__":
    main()

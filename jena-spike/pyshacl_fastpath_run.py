#!/usr/bin/env python
"""Time HEAD's actual green path, not just the audit path.

`_run_shacl` in default mode runs `_batched_shacl_precheck_misses` plus
`_validate_shacl_data(view, plan.shapes)` -- the batched plan, with the closed
shapes, the relation ring context and the evidence warrant sh:xone lifted out of
the engine (`_batched_shacl_plan`). That is the number a subprocess engine would
have to beat on a green release, so it is measured here alongside the
whole-graph audit path.

The view is assembled exactly as validate.py assembles it: a `_ShaclDataView`
over [role graph, inoculate(Graph(), ontology)].

Usage: pyshacl_fastpath_run.py <data-triples.nt>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
sys.path.insert(0, str(REPO / "bindings/atlas/3.1/tools"))

from pyshacl.rdfutil import inoculate  # noqa: E402
from rdflib import Graph  # noqa: E402

import validate  # noqa: E402


def main() -> None:
    data_path = Path(sys.argv[1])

    t0 = time.perf_counter()
    ontology, shapes = validate._parse_binding_graphs()
    data = Graph()
    data.parse(data_path, format="nt")
    ontology_view = inoculate(Graph(), ontology)
    view = validate._ShaclDataView([data, ontology_view])
    for prefix, namespace in ontology.namespaces():
        view.namespace_manager.bind(prefix, namespace)
    t1 = time.perf_counter()
    print(f"parse: {len(data)} triples in {t1 - t0:.2f}s", flush=True)

    plan = validate._batched_shacl_plan(shapes)
    t2 = time.perf_counter()
    print(f"plan: built in {t2 - t1:.2f}s", flush=True)

    misses = validate._batched_shacl_precheck_misses(view, shapes, plan, first_only=False)
    t3 = time.perf_counter()
    print(f"prechecks: {len(misses)} misses in {t3 - t2:.2f}s", flush=True)

    conforms, _, _ = validate._validate_shacl_data(view, plan.shapes)
    t4 = time.perf_counter()
    print(f"batched shapes: conforms={conforms} in {t4 - t3:.2f}s", flush=True)
    print(f"fast path engine total (prechecks + batched): {t4 - t2:.2f}s", flush=True)
    print(f"total incl. parse: {t4 - t0:.2f}s", flush=True)


if __name__ == "__main__":
    main()

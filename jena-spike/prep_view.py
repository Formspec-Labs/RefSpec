#!/usr/bin/env python
"""Build the EXACT pySHACL validation view as a flat N-Triples file for Jena.

`validate.py:_run_shacl` validates, per role, a `_ShaclDataView` that is a
`ReadOnlyGraphAggregate` of two graphs:

    _ShaclDataView([graphs[role], inoculate(Graph(), ontology)])

with `inference="none"`, `advanced=False`, `meta_shacl=False`. So the data graph
Jena must see is exactly:

    (quads of the role's named graph, as triples)  UNION  (inoculate(ontology))

`inoculate` is NOT the whole ontology: it copies only the subjects typed with an
RDFS/OWL class and only the RDFS/OWL property statements (pyshacl/rdfutil/
inoculate.py). Reimplementing that in Java would be a parity hazard, so we run
the real function and serialize its output.

Usage:
    prep_view.py <graph-id> <asserted.nq> <out-dir>
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
sys.path.insert(0, str(REPO / "bindings/atlas/3.1/tools"))

from pyshacl.rdfutil import inoculate  # noqa: E402
from rdflib import Graph  # noqa: E402

ONTOLOGY = REPO / "bindings/atlas/3.1/ontology/atlas.ttl"


def strip_graph(nq_path: Path, graph_id: str, out: Path) -> int:
    """Drop the graph term. Fails loudly if any line is not in `graph_id`.

    The packs are canonical N-Quads (one statement per line, LF-terminated), so
    an exact suffix match is a total check, not a heuristic: if even one line
    does not carry this graph, we refuse rather than silently mangle a literal.
    """
    suffix = f" <{graph_id}> .\n".encode()
    written = 0
    with nq_path.open("rb") as src, out.open("wb") as dst:
        for lineno, line in enumerate(src, 1):
            if not line.endswith(suffix):
                raise SystemExit(f"line {lineno} is not in <{graph_id}>: {line[-120:]!r}")
            dst.write(line[: -len(suffix)] + b" .\n")
            written += 1
    return written


def main() -> None:
    graph_id, nq, outdir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    n = strip_graph(nq, graph_id, outdir / "data-triples.nt")
    t1 = time.perf_counter()
    print(f"strip_graph: {n} triples in {t1 - t0:.2f}s")

    ontology = Graph()
    ontology.parse(ONTOLOGY, format="turtle")
    view = inoculate(Graph(), ontology)
    (outdir / "ontology-inoculated.nt").write_bytes(view.serialize(format="nt", encoding="utf-8"))
    t2 = time.perf_counter()
    print(f"ontology: {len(ontology)} triples -> inoculated {len(view)} triples in {t2 - t1:.2f}s")

    # Streamed, not read_bytes(): the full-scale data half is ~5.7 GB.
    with (outdir / "view.nt").open("wb") as dst:
        for part in ("data-triples.nt", "ontology-inoculated.nt"):
            with (outdir / part).open("rb") as src:
                shutil.copyfileobj(src, dst, length=1 << 22)
    print(f"view.nt: {(outdir / 'view.nt').stat().st_size} bytes in {time.perf_counter() - t2:.2f}s")


if __name__ == "__main__":
    main()

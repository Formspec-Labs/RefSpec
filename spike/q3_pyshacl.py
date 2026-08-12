"""Q3 -- pySHACL 0.31.0 over an oxrdflib-backed data graph vs rdflib Memory.

Same shapes file, same call signature validate.py uses (`inference="none"`,
`advanced=False`, `inplace=True`, `abort_on_first=False`).

    .venv/bin/python spike/q3_pyshacl.py <native|oxrdflib>
"""

from __future__ import annotations

import gc
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402
import q2_shim  # noqa: E402

SHAPES = Path(__file__).parent / "pinned-binding-3.1" / "shapes" / "atlas.shacl.ttl"


def main() -> None:
    variant = sys.argv[1]
    n_packs = int(sys.argv[2]) if len(sys.argv) > 2 else None
    import validate as V
    from rdflib import Graph

    if n_packs is not None:
        all_paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)
        q2_shim._paths = lambda: all_paths[:n_packs]

    with common.Timer("load") as tl:
        ds = q2_shim.LOADERS["native" if variant == "native" else "oxrdflib-bulk"]()
    asserted = ds.graph(q2_shim._graph_ids()["asserted"])

    shapes = Graph()
    shapes.parse(SHAPES, format="turtle")

    gc.collect()
    err = None
    conforms = None
    report = ""
    with common.Timer("shacl") as ts:
        try:
            conforms, _results_graph, report = V._validate_shacl_data(asserted, shapes)
        except Exception as exc:  # noqa: BLE001 - the point is whether it survives
            err = f"{type(exc).__name__}: {exc}"
    common.emit(
        {
            "q": 3,
            "variant": variant,
            "packs": n_packs,
            "load_wall_s": round(tl.wall, 3),
            "shacl_wall_s": round(ts.wall, 3),
            "shacl_cpu_s": round(ts.cpu, 3),
            "conforms": conforms,
            "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest()[:16] if report else None,
            "report_chars": len(report),
            "error": err,
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )
    if err:
        print(err, file=sys.stderr)


if __name__ == "__main__":
    main()

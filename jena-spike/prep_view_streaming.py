#!/usr/bin/env python
"""One-pass prep: zstdcat -> strip graph term -> append inoculated ontology.

The two-step prep (prep_dist.py then prep_view.py) materializes both a 6.7 GB
N-Quads intermediate and a 5.7 GB N-Triples view at full scale. This does the
same work in one pass and writes only the view, which is what a release-tier
subprocess would actually run: 5.7 GB of scratch instead of 12.4 GB.

Usage: prep_view_streaming.py <distribution-root> <graph-id> <out.nt>
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
sys.path.insert(0, str(REPO / "bindings/atlas/3.1/tools"))

from pyshacl.rdfutil import inoculate  # noqa: E402
from rdflib import Graph  # noqa: E402

ONTOLOGY = REPO / "bindings/atlas/3.1/ontology/atlas.ttl"


def main() -> None:
    root, graph_id, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    manifest = json.loads((root / "atlas-manifest.json").read_text())
    packs = [str(root / pack["path"]) for pack in manifest["packs"]]
    suffix = f" <{graph_id}> .\n".encode()

    t0 = time.perf_counter()
    written = 0
    with out.open("wb") as dst:
        proc = subprocess.Popen(["zstdcat", *packs], stdout=subprocess.PIPE, bufsize=1 << 22)
        assert proc.stdout is not None
        for line in proc.stdout:
            if not line.endswith(suffix):
                raise SystemExit(f"quad {written + 1} is not in <{graph_id}>")
            dst.write(line[: -len(suffix)] + b" .\n")
            written += 1
        if proc.wait() != 0:
            raise SystemExit("zstdcat failed")
        ontology = Graph()
        ontology.parse(ONTOLOGY, format="turtle")
        dst.write(inoculate(Graph(), ontology).serialize(format="nt", encoding="utf-8"))
    elapsed = time.perf_counter() - t0
    print(f"triples={written} bytes={out.stat().st_size} seconds={elapsed:.2f}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Q1 counterpart: rdflib's N-Quads parse rate, measured two ways.

`plain` uses rdflib's stock NQuads parser. `atlas` uses validate.py's own
`_parse_nquads_preserving_lexical_forms`, which is what the acceptance run
actually pays -- the plan's ~21k quads/s baseline is that one, not the stock
parser, so both are reported rather than one being passed off as the other.

Usage: rdflib_parse_bench.py <plain|atlas> <file.nq>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
sys.path.insert(0, str(REPO / "bindings/atlas/3.1/tools"))

from rdflib import Dataset  # noqa: E402


def main() -> None:
    mode, path = sys.argv[1], Path(sys.argv[2])
    dataset = Dataset()
    t0 = time.perf_counter()
    if mode == "plain":
        dataset.parse(path, format="nquads")
        count = sum(1 for _ in dataset.quads((None, None, None, None)))
    else:
        import validate  # noqa: PLC0415 - imported only for the atlas mode

        counts = validate._parse_nquads_preserving_lexical_forms(dataset, path)
        count = sum(counts.values())
    elapsed = time.perf_counter() - t0
    print(f"mode={mode} quads={count} seconds={elapsed:.2f} quads_per_second={count / elapsed:,.0f}")


if __name__ == "__main__":
    main()

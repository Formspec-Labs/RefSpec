#!/usr/bin/env python
"""Data-prep step, timed: zstdcat every pack of a distribution into one N-Quads file.

This is the step the release-tier subprocess estimate must include -- the packs
ship as zstd N-Quads and neither engine reads zstd. Packs are concatenated in
manifest order so the output is reproducible.

Usage: prep_dist.py <distribution-root> <out.nq>
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    manifest = json.loads((root / "atlas-manifest.json").read_text())
    packs = [root / pack["path"] for pack in manifest["packs"]]

    t0 = time.perf_counter()
    with out.open("wb") as dst:
        proc = subprocess.Popen(
            ["zstdcat", *[str(p) for p in packs]], stdout=subprocess.PIPE
        )
        assert proc.stdout is not None
        shutil.copyfileobj(proc.stdout, dst, length=1 << 22)
        if proc.wait() != 0:
            raise SystemExit("zstdcat failed")
    elapsed = time.perf_counter() - t0
    size = out.stat().st_size
    print(f"packs={len(packs)} bytes={size} seconds={elapsed:.2f} MB/s={size / elapsed / 1e6:.1f}")


if __name__ == "__main__":
    main()

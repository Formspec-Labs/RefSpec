"""Q1b -- linearity probe on homogeneous data.

Slices the largest real pack (eurovoc-4-24, 856,733 quads / 193 MB) into
prefixes.  A prefix of a sorted N-Quads file is itself a valid, sorted,
canonical N-Quads file, so every point measures the same shape of data at a
different size -- which the cumulative-pack subsets do not.

    .venv/bin/python spike/q1_scale.py <variant> <n_lines>
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/Users/mikewolfd/Work/spicy-regs/RefSpec/bindings/atlas/3.1/tools")

import common  # noqa: E402
import q1_parse  # noqa: E402

SLICES = common.SCRATCH / "slices"


def slice_path(n: int) -> Path:
    SLICES.mkdir(parents=True, exist_ok=True)
    big = max(common.decompressed(), key=lambda p: p.stat().st_size)
    dst = SLICES / f"eurovoc-{n}.nq"
    if not dst.exists():
        written = 0
        with big.open("rb") as src, dst.open("wb") as sink:
            for line in src:
                if written >= n:
                    break
                sink.write(line)
                written += 1
    return dst


def main() -> None:
    variant, n = sys.argv[1], int(sys.argv[2])
    path = slice_path(n)
    gc.collect()
    with common.Timer(variant) as t:
        count = q1_parse.VARIANTS[variant]([path])
    common.emit(
        {
            "q": "1b",
            "variant": variant,
            "quads": n,
            "quads_seen": count,
            "bytes": path.stat().st_size,
            "wall_s": round(t.wall, 3),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


if __name__ == "__main__":
    main()

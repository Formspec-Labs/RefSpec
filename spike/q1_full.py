"""Q1c -- full-scale (29,283,283 quads / 6.68 GB) probes, read-only, streamed.

Packs are read straight from the zstd transports in the MAIN repo's output/ --
nothing is written there and nothing is staged on disk.

    .venv/bin/python spike/q1_full.py <variant>

variants:
  oxi-parse-count   constant-memory parse rate at full scale (safe, ~25 MB RSS)
  oxi-store         in-memory oxigraph Store at full scale (~12 GB projected)
  bytes-canonical   the byte-level canonicality layer alone at full scale
"""

from __future__ import annotations

import gc
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import common  # noqa: E402

FULL_ROOT = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12")


def _zstd():
    try:
        from compression import zstd
    except ImportError:
        from backports import zstd
    return zstd


def _packs() -> list[dict]:
    return json.loads((FULL_ROOT / "atlas-manifest.json").read_bytes())["packs"]


def oxi_parse_count() -> int:
    import pyoxigraph as ox

    zstd = _zstd()
    total = 0
    for pack in _packs():
        with zstd.open(FULL_ROOT / pack["path"], "rb") as fh:
            for _q in ox.parse(fh, format=ox.RdfFormat.N_QUADS):
                total += 1
    return total


def oxi_store() -> int:
    import pyoxigraph as ox

    zstd = _zstd()
    store = ox.Store()
    for pack in _packs():
        with zstd.open(FULL_ROOT / pack["path"], "rb") as fh:
            store.load(fh, format=ox.RdfFormat.N_QUADS)
    return len(store)


def bytes_canonical() -> int:
    """zstd + sha256 + the line-level canonical rules, no RDF term model at all."""

    zstd = _zstd()
    total = 0
    for pack in _packs():
        digest = hashlib.sha256()
        previous = b""
        n = 0
        with zstd.open(FULL_ROOT / pack["path"], "rb") as fh:
            for line in fh:
                digest.update(line)
                n += 1
                if b"\r" in line:
                    raise SystemExit("CR")
                content = line[:-1]
                if not content or content != content.strip():
                    raise SystemExit("padded")
                if line <= previous:
                    raise SystemExit("unsorted")
                previous = line
        if "sha256:" + digest.hexdigest() != pack["content"]["digest"]:
            raise SystemExit(f"digest mismatch on {pack['path']}")
        total += n
    return total


VARIANTS = {
    "oxi-parse-count": oxi_parse_count,
    "oxi-store": oxi_store,
    "bytes-canonical": bytes_canonical,
}


def main() -> None:
    variant = sys.argv[1]
    gc.collect()
    with common.Timer(variant) as t:
        count = VARIANTS[variant]()
    common.emit(
        {
            "q": "1c-full",
            "variant": variant,
            "quads_seen": count,
            "wall_s": round(t.wall, 2),
            "cpu_s": round(t.cpu, 2),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


if __name__ == "__main__":
    main()

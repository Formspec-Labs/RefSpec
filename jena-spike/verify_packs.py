#!/usr/bin/env python
"""Time the pack integrity check the prep step would otherwise duplicate.

By the time `_run_shacl` runs, `_parse_packed_dataset` has already streamed and
receipted every pack. A subprocess prep that re-reads the packs pays this again
unless it reuses what the parse already proved. Measuring it makes the honest
release-tier estimate possible either way.

Usage: verify_packs.py <distribution-root>
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1])
    manifest = json.loads((root / "atlas-manifest.json").read_text())
    t0 = time.perf_counter()
    total = 0
    bad = 0
    for pack in manifest["packs"]:
        digest = hashlib.sha256()
        path = root / pack["path"]
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 22):
                digest.update(chunk)
                total += len(chunk)
        if f"sha256:{digest.hexdigest()}" != pack["transport"]["digest"]:
            bad += 1
            print(f"MISMATCH {pack['path']}")
    elapsed = time.perf_counter() - t0
    print(
        f"packs={len(manifest['packs'])} mismatches={bad} transport_bytes={total} "
        f"seconds={elapsed:.2f} MB/s={total / elapsed / 1e6:.1f}"
    )


if __name__ == "__main__":
    main()

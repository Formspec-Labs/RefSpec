"""Shared helpers for the oxigraph substrate spike.

Nothing here is production code. It exists to make the measurements in
`spike/report-data/` reproducible.
"""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path

STAGING = Path(
    "/Users/mikewolfd/Work/spicy-regs/RefSpec/output/"
    "atlas-3.1-mapping-topology-staging/distribution"
)
FULL = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12/distribution")
SCRATCH = Path(
    os.environ.get(
        "SPIKE_SCRATCH",
        "/private/tmp/claude-501/-Users-mikewolfd-Work-spicy-regs-RefSpec/"
        "945a06dc-2461-4e02-bbcd-5b3dd6db603d/scratchpad/spike",
    )
)
SHAPES = Path(
    "/Users/mikewolfd/Work/spicy-regs/RefSpec/.claude/worktrees/"
    "agent-a9301012cdaa44814/bindings/atlas/3.1/shapes/atlas.shacl.ttl"
)

ATLAS = "https://ref.spec/atlas/3.1#"  # replaced at import time from the shapes file


def manifest(root: Path = STAGING) -> dict:
    return json.loads((root / "atlas-manifest.json").read_bytes())


def pack_paths(root: Path = STAGING) -> list[Path]:
    """Packs in manifest order, largest last is NOT guaranteed; keep declared order."""

    return [root / p["path"] for p in manifest(root)["packs"]]


def decompressed(root: Path = STAGING) -> list[Path]:
    """Decompress each pack once into SCRATCH; return the .nq paths (manifest order)."""

    try:
        from compression import zstd  # type: ignore[import-not-found]
    except ImportError:
        from backports import zstd  # type: ignore[import-not-found]

    out_dir = SCRATCH / root.parent.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for pack in manifest(root)["packs"]:
        src = root / pack["path"]
        dst = out_dir / (pack["path"].replace("/", "__").removesuffix(".zst"))
        if not dst.exists() or dst.stat().st_size != pack["content"]["byteLength"]:
            with zstd.open(src, "rb") as fh, dst.open("wb") as sink:
                while chunk := fh.read(8 << 20):
                    sink.write(chunk)
        out.append(dst)
    return out


def peak_rss_gb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":  # bytes on macOS, kilobytes on Linux
        return rss / (1 << 30)
    return rss / (1 << 20)


class Timer:
    def __init__(self, label: str) -> None:
        self.label = label

    def __enter__(self) -> Timer:
        self.t0 = time.perf_counter()
        self.c0 = time.process_time()
        return self

    def __exit__(self, *exc: object) -> None:
        self.wall = time.perf_counter() - self.t0
        self.cpu = time.process_time() - self.c0


def emit(record: dict) -> None:
    print("RESULT " + json.dumps(record, sort_keys=True), flush=True)

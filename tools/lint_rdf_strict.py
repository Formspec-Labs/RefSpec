"""Parse the published RDF bytes with a second, independent parser.

rdflib writes what this repository publishes and rdflib reads it back, so a
wire defect that rdflib is willing to round-trip is invisible to every gate
that only uses rdflib. The 2026-08-12 oxigraph spike found exactly that class
twice -- over-escaped IRIs (7,770 of them) and non-simple literal forms -- in
bytes that every rdflib-based check had already passed. This lint is the
permanent form of that sweep: a parser with no shared code with the producer,
in strict mode (``lenient=False``), asserting that what we ship is grammatical
N-Quads by somebody else's reading.

What it always parses: ``bindings/atlas/3.1/tests/registry-descriptors.nq``,
the one RDF artifact in git. That file is a sealed bundle member and a build
input pinned by digest, so it is the wire grammar's committed sentinel and the
only thing this lint can reach on a CI runner, where ``output/`` never exists.

What it parses when it is there: every pack of every distribution root named
by ``--distribution`` or by the ``ATLAS_RDF_STRICT_ROOTS`` environment
variable (``os.pathsep``-separated). A missing root is not an error -- the
distributions are gitignored, regenerable, and usually absent -- but a named
root that exists and cannot be parsed is.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - exercised on supported Python 3.12-3.13
    from backports import zstd

import pyoxigraph

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DESCRIPTORS = ROOT / "bindings" / "atlas" / "3.1" / "tests" / "registry-descriptors.nq"
ROOTS_ENV_VAR = "ATLAS_RDF_STRICT_ROOTS"


def _pack_paths(distribution: Path) -> list[Path]:
    """Every N-Quads pack under one distribution root, compressed or not."""

    packs = distribution / "packs"
    return sorted(
        path
        for path in packs.rglob("*")
        if path.is_file() and path.name.endswith((".nq", ".nq.zst"))
    )


def _open(path: Path) -> IO[bytes]:
    if path.name.endswith(".zst"):
        return zstd.open(path, "rb")
    return path.open("rb")


def _parse_strict(path: Path) -> int:
    """Return the quad count, or raise SyntaxError naming the file."""

    count = 0
    with _open(path) as stream:
        try:
            for _ in pyoxigraph.parse(
                input=stream,
                format=pyoxigraph.RdfFormat.N_QUADS,
                lenient=False,
            ):
                count += 1
        except SyntaxError as error:
            raise SyntaxError(f"{path}: {error}") from error
    return count


def _targets(roots: Iterable[Path]) -> Iterator[tuple[str, Path]]:
    yield "committed", REGISTRY_DESCRIPTORS
    for root in roots:
        distribution = root / "distribution" if (root / "distribution").is_dir() else root
        if not (distribution / "atlas-manifest.json").is_file():
            print(f"strict-parser lint: skipping {root} (no distribution there)", file=sys.stderr)
            continue
        for path in _pack_paths(distribution):
            yield "distribution", path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution",
        action="append",
        default=[],
        type=Path,
        help=(
            "distribution root (or its parent) whose packs to sweep as well; "
            f"repeatable, and also read from ${ROOTS_ENV_VAR}"
        ),
    )
    arguments = parser.parse_args(argv)

    roots = list(arguments.distribution)
    roots.extend(
        Path(entry)
        for entry in os.environ.get(ROOTS_ENV_VAR, "").split(os.pathsep)
        if entry.strip()
    )
    named = len(roots)
    roots = [root for root in roots if root.exists()]

    files = 0
    quads = 0
    for _, path in _targets(roots):
        quads += _parse_strict(path)
        files += 1

    print(
        f"strict-parser lint: pyoxigraph {pyoxigraph.__version__} accepted "
        f"{quads:,} quads across {files} file(s); "
        f"{len(roots)} of {named} named distribution root(s) present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

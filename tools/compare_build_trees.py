"""Compare two build trees byte for byte and name the first differences.

The determinism claim this repository makes is not "the manifest digest is
stable" -- it is that the same source bytes rebuild the same tree. A manifest
digest covers the distribution's declared members; it does not cover the
served Parquet view, the generation report, or anything a future builder adds
beside them. So this compares whole trees: every regular file under each root,
by relative path and content digest, and one whole-tree digest over that
listing so two runs can be quoted as a single number.

Used by `make determinism-atlas-federal-register-thesaurus`, which builds the
bounded Federal Register distribution twice into scratch roots and hands both
here. Byte-inequality is a failure: a build that cannot reproduce itself in
twelve seconds on one machine cannot be reproduced by a third party a year
later, which is the whole claim the weekly reproducible-rebuild control makes
(docs/seal-design.md section 4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPORT_LIMIT = 20
# Files a machine measures rather than the source determines (peak RSS, elapsed
# milliseconds). Each must exist in both trees with the same JSON shape, so
# dropping one or changing what it records still fails; only its values go
# uncompared. The generator writes the one entry beside its report
# (tools/generate_atlas_v3_full.py GENERATION_MEASUREMENTS_FILE, REF-071).
MEASURED_FILES = frozenset({"generation-measurements.json"})


def _shape(value: object) -> object:
    """A JSON value with every leaf replaced by its type name: what a measurement records, not what it measured."""

    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    return type(value).__name__


def _measured_digest(path: Path) -> str:
    shape = json.dumps(_shape(json.loads(path.read_bytes())), sort_keys=True)
    return "measured:" + hashlib.sha256(shape.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digests(root: Path) -> dict[str, str]:
    """Map every regular file under `root` to its sha256, by relative path; a measured file maps to its JSON shape."""

    return {
        str(path.relative_to(root)): _measured_digest(path) if path.name in MEASURED_FILES else _file_digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def whole_tree_digest(digests: dict[str, str]) -> str:
    """One digest over the sorted `path sha256` listing."""

    listing = "".join(f"{path} {digest}\n" for path, digest in sorted(digests.items()))
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    arguments = parser.parse_args(argv)

    for root in (arguments.first, arguments.second):
        if not root.is_dir():
            print(f"determinism gate: {root} is not a directory", flush=True)
            return 1

    first = tree_digests(arguments.first)
    second = tree_digests(arguments.second)
    first_digest = whole_tree_digest(first)
    second_digest = whole_tree_digest(second)

    print(f"{arguments.first}: {len(first)} files, whole-tree sha256 {first_digest}")
    print(f"{arguments.second}: {len(second)} files, whole-tree sha256 {second_digest}")
    if first_digest == second_digest:
        print("determinism gate PASS: the two builds are byte-identical")
        return 0

    missing = sorted(set(first) - set(second))
    added = sorted(set(second) - set(first))
    differing = sorted(path for path in set(first) & set(second) if first[path] != second[path])
    print("determinism gate FAIL: the two builds differ")
    for label, paths in (("only in the first", missing), ("only in the second", added)):
        for path in paths[:REPORT_LIMIT]:
            print(f"  {label}: {path}")
        if len(paths) > REPORT_LIMIT:
            print(f"  {label}: ... and {len(paths) - REPORT_LIMIT} more")
    for path in differing[:REPORT_LIMIT]:
        print(f"  differing content: {path} ({first[path]} != {second[path]})")
    if len(differing) > REPORT_LIMIT:
        print(f"  differing content: ... and {len(differing) - REPORT_LIMIT} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

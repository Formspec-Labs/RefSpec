#!/usr/bin/env python3
"""Decompress and verify Atlas packs without writing to the distribution."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("receipt", type=Path)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    distribution = args.distribution.resolve()
    output_directory = args.output_directory.resolve()
    receipt = args.receipt.resolve()
    if output_directory == distribution or distribution in output_directory.parents:
        raise SystemExit("output directory must be outside the read-only distribution")
    if receipt.exists():
        raise SystemExit(f"refusing to overwrite receipt: {receipt}")
    if output_directory.exists() and any(output_directory.iterdir()):
        raise SystemExit(f"output directory must be absent or empty: {output_directory}")
    output_directory.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = distribution / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    started = time.monotonic()
    pack_receipts = []
    for index, pack in enumerate(manifest["packs"]):
        source = distribution / pack["path"]
        destination = output_directory / f"{index:03d}.nq"
        partial = destination.with_suffix(".nq.partial")
        digest = hashlib.sha256()
        size = 0
        lines = 0
        pack_started = time.monotonic()
        with partial.open("wb") as output:
            process = subprocess.Popen(
                ["zstd", "--quiet", "--decompress", "--stdout", str(source)],
                stdout=subprocess.PIPE,
            )
            assert process.stdout is not None
            for block in iter(lambda: process.stdout.read(4 * 1024 * 1024), b""):
                output.write(block)
                digest.update(block)
                size += len(block)
                lines += block.count(b"\n")
            exit_code = process.wait()
        if exit_code != 0:
            raise SystemExit(f"zstd failed for {source} with exit {exit_code}; partial: {partial}")

        expected_digest = pack["content"]["digest"].removeprefix("sha256:")
        expected_size = pack["content"]["byteLength"]
        expected_lines = pack["content"]["quadCount"]
        actual_digest = digest.hexdigest()
        if (size, lines, actual_digest) != (expected_size, expected_lines, expected_digest):
            raise SystemExit(
                f"verification failed for {source}: "
                f"actual={(size, lines, actual_digest)} "
                f"expected={(expected_size, expected_lines, expected_digest)}; partial: {partial}"
            )
        partial.replace(destination)
        pack_receipts.append(
            {
                "index": index,
                "manifest_path": pack["path"],
                "scratch_path": str(destination),
                "bytes": size,
                "quads": lines,
                "sha256": actual_digest,
                "wall_seconds": round(time.monotonic() - pack_started, 3),
            }
        )

    record = {
        "schema_version": 1,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "distribution": str(distribution),
        "manifest_sha256": file_sha256(manifest_path),
        "output_directory": str(output_directory),
        "pack_count": len(pack_receipts),
        "quad_count": sum(pack["quads"] for pack in pack_receipts),
        "decompressed_bytes": sum(pack["bytes"] for pack in pack_receipts),
        "wall_seconds": round(time.monotonic() - started, 3),
        "packs": pack_receipts,
    }
    temporary_receipt = receipt.with_suffix(receipt.suffix + ".tmp")
    temporary_receipt.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temporary_receipt.replace(receipt)
    print(json.dumps({key: record[key] for key in ("pack_count", "quad_count", "decompressed_bytes", "wall_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()

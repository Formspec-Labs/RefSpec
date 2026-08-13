#!/usr/bin/env python3
"""Verify the bounded Atlas distribution and compare its binding identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_file(
    path: Path, expected_digest: str, expected_bytes: int
) -> dict[str, Any]:
    """Measure one file and compare it with the manifest entry."""

    actual_digest = sha256(path)
    actual_bytes = path.stat().st_size
    normalized_expected = expected_digest.removeprefix("sha256:")
    return {
        "actualByteLength": actual_bytes,
        "actualSha256": actual_digest,
        "byteLengthMatches": actual_bytes == expected_bytes,
        "expectedByteLength": expected_bytes,
        "expectedSha256": normalized_expected,
        "exists": path.is_file(),
        "path": str(path),
        "sha256Matches": actual_digest == normalized_expected,
    }


def probe(root: Path, distribution: Path) -> dict[str, Any]:
    """Return the distribution integrity and current-binding comparison."""

    manifest_path = distribution / "atlas-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    shapes_path = root / "bindings" / "atlas" / "3.1" / "shapes" / "atlas.shacl.ttl"
    current_shapes_digest = sha256(shapes_path)
    distribution_shapes_digest = manifest["binding"]["shapesDigest"].removeprefix(
        "sha256:"
    )

    packs = [
        checked_file(
            distribution / pack["path"],
            pack["transport"]["digest"],
            pack["transport"]["byteLength"],
        )
        for pack in manifest["packs"]
    ]
    members = [
        checked_file(
            distribution / member["path"],
            member["digest"],
            member["byteLength"],
        )
        for member in manifest["members"]
    ]

    return {
        "bindingIdentity": {
            "currentShapesPath": str(shapes_path),
            "currentShapesSha256": current_shapes_digest,
            "distributionShapesSha256": distribution_shapes_digest,
            "shapesMatch": current_shapes_digest == distribution_shapes_digest,
        },
        "distribution": {
            "assertedQuadCount": sum(
                graph["quadCount"]
                for graph in manifest["graphs"]
                if graph["role"] == "asserted"
            ),
            "contentByteLength": sum(
                pack["content"]["byteLength"] for pack in manifest["packs"]
            ),
            "manifestPath": str(manifest_path),
            "manifestSha256": sha256(manifest_path),
            "packCount": len(manifest["packs"]),
            "transportByteLength": sum(
                pack["transport"]["byteLength"] for pack in manifest["packs"]
            ),
        },
        "integrity": {
            "allMemberDigestsMatch": all(item["sha256Matches"] for item in members),
            "allPackTransportDigestsMatch": all(
                item["sha256Matches"] for item in packs
            ),
            "members": members,
            "packTransports": packs,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Current RefSpec checkout",
    )
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = probe(args.root.resolve(), args.distribution.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

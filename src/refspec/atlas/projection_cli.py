"""Build one Atlas 2.0 ring or subject-module projection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .model import VocabularyAtlasAsset
from .projection import (
    build_atlas_projection,
    module_projection_policy,
    ring_projection_policy,
)

_RINGS = ("subject", "entity", "value", "legalIdentity")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refspec-build-vocabulary-atlas-projection")
    parser.add_argument(
        "--atlas",
        type=Path,
        required=True,
        help="directory holding the canonical Atlas 2.0 three-file distribution",
    )
    parser.add_argument(
        "--atlas-manifest-digest",
        required=True,
        help="independently trusted sha256 digest of atlas-manifest.json",
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--ring",
        choices=_RINGS,
        help="retain one complete semantic ring",
    )
    selector.add_argument(
        "--subject-module",
        metavar="DOTTED.MODULE",
        help="retain one subject specialist module plus every subject-core release",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new directory for the two-file projection",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    policy = (
        ring_projection_policy(args.ring) if args.ring is not None else module_projection_policy(args.subject_module)
    )
    parent = VocabularyAtlasAsset.open(
        args.atlas,
        expected_manifest_digest=args.atlas_manifest_digest,
    )
    projection = build_atlas_projection(parent, policy=policy)
    output = projection.write(args.output)
    print(
        json.dumps(
            {
                "assetId": projection.manifest["id"],
                "derivedFrom": projection.parent_pin,
                "manifestDigest": projection.manifest_digest,
                "outputDigest": projection.output_digest,
                "outputDirectory": str(output.resolve()),
                "projectionPolicy": policy,
                "byteLength": projection.manifest["output"]["byteLength"],
                "counts": dict(projection.manifest["counts"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


__all__ = ["build_parser", "main"]

"""Build one static vocabulary atlas from exact published input files."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .model import (
    CrosswalkBundle,
    PinnedManagedRelease,
    PinnedRulespecCoreRelease,
    build_vocabulary_atlas,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refspec-build-vocabulary-atlas")
    parser.add_argument(
        "--managed-release",
        action="append",
        nargs=2,
        metavar=("MANIFEST", "SHA256"),
        required=True,
        help="managed-release manifest path and exact file digest; repeat for each release",
    )
    parser.add_argument("--rulespec-core", type=Path, required=True)
    parser.add_argument("--rulespec-core-file-digest", required=True)
    parser.add_argument("--rulespec-core-release-id", required=True)
    parser.add_argument("--rulespec-core-release-digest", required=True)
    parser.add_argument(
        "--crosswalk",
        nargs=3,
        metavar=("FILE", "FILE_SHA256", "BUNDLE_SHA256"),
        help="optional canonical crosswalk file and its exact file and root digests",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    releases = tuple(
        PinnedManagedRelease.open(path, expected_manifest_digest=digest) for path, digest in args.managed_release
    )
    core = PinnedRulespecCoreRelease.open(
        args.rulespec_core,
        expected_file_digest=args.rulespec_core_file_digest,
        expected_release_id=args.rulespec_core_release_id,
        expected_release_digest=args.rulespec_core_release_digest,
    )
    crosswalk = None
    if args.crosswalk is not None:
        path, file_digest, bundle_digest = args.crosswalk
        crosswalk = CrosswalkBundle.open(
            path,
            expected_file_digest=file_digest,
            expected_bundle_digest=bundle_digest,
        )
    asset = build_vocabulary_atlas(releases, rulespec_core=core, crosswalk=crosswalk)
    output = asset.write(args.output)
    print(
        json.dumps(
            {
                "assetId": asset.manifest["id"],
                "manifestDigest": asset.manifest_digest,
                "outputDigest": asset.output_digest,
                "outputDirectory": str(output.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


__all__ = ["build_parser", "main"]

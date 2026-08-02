"""Cut one verified atlas distribution down to a named projection policy.

Deliberately separate from :mod:`refspec.atlas.projection`: argument parsing
does not decide which quads survive, and the projection's implementation pin
covers only the modules that do. A CLI edit must not move a published
projection identifier.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .projection import CONSUMER_READ_CLOSURE_V1, build_atlas_projection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refspec-build-vocabulary-atlas-projection")
    parser.add_argument(
        "--atlas",
        type=Path,
        required=True,
        help="directory holding the parent atlas.nq and atlas-manifest.json",
    )
    parser.add_argument(
        "--atlas-manifest-digest",
        required=True,
        help="exact sha256 of the parent atlas-manifest.json",
    )
    parser.add_argument(
        "--atlas-output-digest",
        required=True,
        help="exact sha256 of the parent atlas.nq",
    )
    parser.add_argument(
        "--policy",
        default=str(CONSUMER_READ_CLOSURE_V1["id"]),
        help="projection policy id; only registered policies are accepted",
    )
    parser.add_argument(
        "--policy-version",
        default=str(CONSUMER_READ_CLOSURE_V1["version"]),
        help="exact version of the named projection policy",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # The policy body is not taken from the command line: a keep rule supplied
    # by an operator would be a policy this producer never implemented, and the
    # registry check would refuse it anyway. The flags select a registered one.
    policy = dict(CONSUMER_READ_CLOSURE_V1)
    policy["id"] = args.policy
    policy["version"] = args.policy_version
    projection = build_atlas_projection(
        args.atlas,
        expected_manifest_digest=args.atlas_manifest_digest,
        expected_output_digest=args.atlas_output_digest,
        policy=policy,
    )
    output = projection.write(args.output)
    print(
        json.dumps(
            {
                "assetId": projection.manifest["id"],
                "derivedFrom": projection.parent_pin,
                "manifestDigest": projection.manifest_digest,
                "outputDigest": projection.output_digest,
                "outputDirectory": str(output.resolve()),
                "byteLength": projection.manifest["output"]["byteLength"],
                "counts": dict(projection.manifest["counts"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


__all__ = ["build_parser", "main"]

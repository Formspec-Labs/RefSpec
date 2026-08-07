"""Command-line interface for the Atlas Parquet view feature."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from refspec.atlas.parquet_view import build_atlas_parquet_view, verify_atlas_parquet_view


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Parquet view directory")
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
        help="external SHA-256 pin for the input Atlas manifest or view manifest in verify-only mode",
    )
    parser.add_argument("--distribution", type=Path, help="Atlas 3.0 distribution to transform")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify --output using its externally pinned view manifest instead of building",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.verify_only:
        if args.distribution is not None:
            raise SystemExit("--verify-only does not accept --distribution")
        manifest = verify_atlas_parquet_view(
            args.output,
            expected_manifest_digest=args.expected_manifest_sha256,
        )
    else:
        if args.distribution is None:
            raise SystemExit("--distribution is required unless --verify-only is used")
        manifest = build_atlas_parquet_view(
            args.distribution,
            args.output,
            expected_manifest_digest=args.expected_manifest_sha256,
        )
    print(
        json.dumps(
            {
                "counts": manifest["counts"],
                "manifest": str(args.output / "view-manifest.json"),
                "status": "passed",
                "viewId": manifest["viewId"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

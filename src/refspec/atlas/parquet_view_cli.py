"""Command-line interface for verifying an Atlas Parquet view."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from refspec.atlas.parquet_view import MANIFEST_FILE, verify_atlas_parquet_view


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True, help="Atlas Parquet view directory")
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
        help=f"external SHA-256 pin for the view's {MANIFEST_FILE}",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    manifest = verify_atlas_parquet_view(
        args.view,
        expected_manifest_digest=args.expected_manifest_sha256,
    )
    print(
        json.dumps(
            {
                "counts": manifest["counts"],
                "manifest": str(args.view / MANIFEST_FILE),
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

"""Build or verify a compact Atlas Parquet search view."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from refspec.atlas.parquet_search_view import (
    build_atlas_parquet_search_view,
    verify_atlas_parquet_search_view,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--full-view", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.verify_only:
        if args.full_view is not None:
            raise SystemExit("--verify-only does not accept --full-view")
        manifest = verify_atlas_parquet_search_view(
            args.output,
            expected_manifest_digest=args.expected_manifest_sha256,
        )
    else:
        if args.full_view is None:
            raise SystemExit("--full-view is required unless --verify-only is used")
        manifest = build_atlas_parquet_search_view(
            args.full_view,
            args.output,
            expected_manifest_digest=args.expected_manifest_sha256,
        )
    print(
        json.dumps(
            {
                "counts": manifest["counts"],
                "manifest": str(args.output / "search-view-manifest.json"),
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

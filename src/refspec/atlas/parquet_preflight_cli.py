"""Run the fast authenticated Atlas Parquet development preflight."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from refspec.atlas.parquet_preflight import validate_atlas_parquet_preflight


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True, help="Atlas 3.1 distribution directory")
    parser.add_argument("--view", type=Path, required=True, help="derived Atlas Parquet view directory")
    parser.add_argument(
        "--distribution-manifest-digest",
        required=True,
        help="external SHA-256 pin for atlas-manifest.json",
    )
    parser.add_argument(
        "--view-manifest-digest",
        required=True,
        help="external SHA-256 pin for view-manifest.json",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = validate_atlas_parquet_preflight(
        args.distribution,
        args.view,
        expected_distribution_manifest_digest=args.distribution_manifest_digest,
        expected_view_manifest_digest=args.view_manifest_digest,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

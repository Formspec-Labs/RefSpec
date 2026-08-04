#!/usr/bin/env python3
"""Generate or verify RefSpec's experimental atlas planning index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

INPUT = ROOT / "portfolio" / "atlas-index-input-v0.json"
CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"
OUTPUT = ROOT / "portfolio" / "atlas-index-v0.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the checked index (default)")
    mode.add_argument("--write", action="store_true", help="write the checked index")
    return parser.parse_args()


def main() -> int:
    from refspec.atlas_index import AtlasIndexError, build_atlas_index
    from refspec.resource_catalog import load_json, render_json

    args = _arguments()
    try:
        index = build_atlas_index(
            load_json(INPUT),
            load_json(CATALOG),
            repository_root=ROOT,
        )
        generated = render_json(index)
        if args.write:
            OUTPUT.write_text(generated, encoding="utf-8")
            print(f"wrote {OUTPUT.relative_to(ROOT)}")
            return 0
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != generated:
            raise AtlasIndexError(
                "checked atlas index differs from generation; run tools/generate_atlas_index.py --write"
            )
        summary = index["summary"]
        print(
            "atlas index is current: "
            f"{summary['sourceModuleCount']} sources, {summary['rowCount']} placement rows, "
            f"{summary['exactReleaseCount']} exact releases"
        )
        return 0
    except (AtlasIndexError, OSError, ValueError) as error:
        print(f"atlas index error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

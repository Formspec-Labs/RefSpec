#!/usr/bin/env python3
"""Generate or verify RefSpec's experimental resource catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

INVENTORY = ROOT / "portfolio" / "resource-inventory-v0.json"
COMPLETED = ROOT / "portfolio" / "completed-controlled-resource-packages-v1.json"
DISTRIBUTIONS = ROOT / "portfolio" / "portable-resource-distributions-v0.json"
OUTPUT = ROOT / "portfolio" / "resource-catalog-v0.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the checked catalog (default)")
    mode.add_argument("--write", action="store_true", help="write the checked catalog")
    return parser.parse_args()


def main() -> int:
    from refspec.resource_catalog import (
        ResourceCatalogError,
        build_resource_catalog,
        load_json,
        render_json,
    )

    args = _arguments()
    try:
        catalog = build_resource_catalog(
            load_json(INVENTORY),
            load_json(COMPLETED),
            load_json(DISTRIBUTIONS),
            repository_root=ROOT,
        )
        generated = render_json(catalog)
        if args.write:
            OUTPUT.write_text(generated, encoding="utf-8")
            print(f"wrote {OUTPUT.relative_to(ROOT)}")
            return 0
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != generated:
            raise ResourceCatalogError(
                "checked resource catalog differs from generation; run tools/generate_resource_catalog.py --write"
            )
        summary = catalog["summary"]
        print(
            "resource catalog is current: "
            f"{summary['resourceCount']} known resources, "
            f"{summary['verifiedDistributionCount']} verified distributions"
        )
        return 0
    except (OSError, ResourceCatalogError, ValueError) as error:
        print(f"resource catalog error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

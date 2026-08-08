"""Export pinned EuroVoc and GEMET claim releases through one shared bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from refspec.registry.claim_release_exports import (
    export_eurovoc_4_24_claim_release,
    export_gemet_4_2_3_claim_release,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT / "output" / "registry-real-data-sources"
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "registry-claim-releases"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--only",
        action="append",
        choices=("eurovoc-4.24", "gemet-4.2.3"),
        help="Export only the named release; repeat for more than one.",
    )
    args = parser.parse_args()
    requested = set(args.only or ("eurovoc-4.24", "gemet-4.2.3"))
    exporters = {
        "eurovoc-4.24": export_eurovoc_4_24_claim_release,
        "gemet-4.2.3": export_gemet_4_2_3_claim_release,
    }
    results: list[dict[str, object]] = []
    for key in sorted(requested):
        view = exporters[key](args.source_root, args.output_root / key)
        results.append(
            {
                "claimCount": len(view.claims),
                "manifestSha256": view.manifest_digest,
                "path": str(view.root),
                "releaseKey": key,
            }
        )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

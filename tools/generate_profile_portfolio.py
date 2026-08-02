#!/usr/bin/env python3
"""Generate or verify the RefSpec active-profile resource atlas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec.profile_portfolio import (
    PortfolioInventoryError,
    build_portfolio_atlas,
    build_profile_snapshot,
    load_json,
    render_json,
    validate_profile_snapshot,
)

DEFAULT_SNAPSHOT = (
    ROOT / "portfolio" / "inputs" / "spicy-regs-source-profiles-v1.json"
)
DEFAULT_INPUT = (
    ROOT / "portfolio" / "inputs" / "active-profile-controlled-resources-v1.json"
)
DEFAULT_OUTPUT = (
    ROOT / "portfolio" / "active-profile-controlled-resource-atlas-v1.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify the checked-in atlas (the default)",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="replace the checked-in atlas with deterministic generation",
    )
    mode.add_argument(
        "--write-snapshot",
        metavar="REVISION",
        help=(
            "re-pin the Spicy Regs profile snapshot to the sibling checkout's "
            "current bytes at the given 40-character revision"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        snapshot = load_json(args.snapshot)
        portfolio_input = load_json(args.input)
        source_path = ROOT.parent / snapshot["source"]["path"]

        if args.write_snapshot:
            regenerated = build_profile_snapshot(
                source_path,
                repository=snapshot["source"]["repository"],
                revision=args.write_snapshot,
                path=snapshot["source"]["path"],
            )
            args.snapshot.write_text(render_json(regenerated), encoding="utf-8")
            print(f"wrote {args.snapshot.relative_to(ROOT)}")
            snapshot = regenerated

        validate_profile_snapshot(snapshot, source_path=source_path)
        generated = render_json(build_portfolio_atlas(snapshot, portfolio_input))

        # The atlas pins the snapshot digest, so re-pinning always rewrites it.
        if args.write or args.write_snapshot:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(generated, encoding="utf-8")
            print(f"wrote {args.output.relative_to(ROOT)}")
            return 0

        if not args.output.exists():
            raise PortfolioInventoryError(
                f"generated atlas is missing: {args.output.relative_to(ROOT)}"
            )
        if args.output.read_text(encoding="utf-8") != generated:
            raise PortfolioInventoryError(
                "checked-in atlas differs from deterministic generation; "
                "run tools/generate_profile_portfolio.py --write"
            )
        print(
            "profile portfolio is current: 16 active profiles, "
            "1 deferred profile"
        )
        return 0
    except (KeyError, OSError, PortfolioInventoryError) as error:
        print(f"profile portfolio error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

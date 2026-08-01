"""RefSpec release-builder command line interface."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .canonical import canonical_json_bytes
from .federal_register import build_federal_register_2025_first_slice


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the sealed April 1, 2025 Federal Register first-slice "
            "VocabularyRelease"
        )
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="path for canonical VocabularyRelease JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    release = build_federal_register_2025_first_slice()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(release))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

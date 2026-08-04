#!/usr/bin/env python3
"""Generate or verify the pinned regulatory source-native control capture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec.registry.regulatory_native_controls import (
    RegulatoryNativeControlError,
    capture_control_values_from_parquet,
    load_source_pins,
    parse_control_capture,
    render_control_capture,
)

EVIDENCE_ROOT = ROOT / "research" / "evidence" / "regulatory-native-controls-2026-08-03"
DEFAULT_PINS = EVIDENCE_ROOT / "source-pins.json"
DEFAULT_CAPTURE = EVIDENCE_ROOT / "source-native-control-capture.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--output", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument(
        "--source-directory",
        type=Path,
        help="directory containing the four pinned <table>.parquet inputs",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        pins = load_source_pins(args.pins)
        generated: bytes | None = None
        if args.source_directory is not None:
            capture = capture_control_values_from_parquet(
                pins,
                {source.table: (args.source_directory / f"{source.table}.parquet") for source in pins.sources},
            )
            generated = render_control_capture(capture)

        if args.write:
            if generated is None:
                raise RegulatoryNativeControlError("--write requires --source-directory")
            output_path = args.output.resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(generated)
            try:
                display_path = output_path.relative_to(ROOT)
            except ValueError:
                display_path = output_path
            print(f"wrote {display_path} ({len(generated)} bytes)")
            return 0

        payload = args.output.read_bytes()
        parsed = parse_control_capture(payload)
        if parsed.source_pins != pins:
            raise RegulatoryNativeControlError("capture source pins differ from source-pins.json")
        if generated is not None and payload != generated:
            raise RegulatoryNativeControlError("checked-in capture differs from pinned Parquet generation")
        print(f"regulatory native controls are current: {len(parsed.controls)} controls, {parsed.digest}")
        return 0
    except (OSError, RegulatoryNativeControlError) as error:
        print(f"regulatory native control error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

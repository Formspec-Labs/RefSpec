"""Build a self-contained visual preview from an Atlas 3.0 distribution."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from refspec.atlas.explorer import (
    build_atlas_v3_explorer_model,
    open_atlas_v3_explorer_distribution,
    render_atlas_v3_explorer,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest


def build_preview(
    distribution: Path,
    output: Path,
    *,
    manifest_digest: str | None = None,
) -> Path:
    """Verify the packed inputs and atomically write one bounded HTML preview."""

    distribution = distribution.resolve(strict=True)
    manifest_path = distribution / "atlas-manifest.json"
    trusted_digest = manifest_digest or sha256_digest(manifest_path.read_bytes())
    opened = open_atlas_v3_explorer_distribution(
        distribution,
        trusted_manifest_digest=trusted_digest,
    )
    preview = render_atlas_v3_explorer(build_atlas_v3_explorer_model(opened))
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(preview, encoding="utf-8", newline="")
    temporary.replace(output)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="HTML destination; defaults beside the distribution directory",
    )
    parser.add_argument(
        "--manifest-digest",
        help="trusted sha256:... manifest digest; omit only for a local visual review",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    distribution = args.distribution.resolve()
    output = args.output or distribution.parent / "atlas-explorer-preview.html"
    if args.manifest_digest is None:
        print(
            "Using the local manifest digest for visual review; this does not establish external trust.",
            file=sys.stderr,
        )
    print(
        build_preview(
            distribution,
            output,
            manifest_digest=args.manifest_digest,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

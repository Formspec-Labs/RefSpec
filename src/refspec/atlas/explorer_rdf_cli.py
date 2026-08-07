"""Legacy command for building the explorer from Atlas RDF packs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from refspec.atlas.explorer_rdf import (
    ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE,
    build_atlas_v3_explorer_model,
    build_atlas_v3_explorer_static_shards,
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
    """Write an HTTP full-corpus explorer with a self-contained file fallback."""

    distribution = distribution.resolve(strict=True)
    manifest_path = distribution / "atlas-manifest.json"
    trusted_digest = manifest_digest or sha256_digest(manifest_path.read_bytes())
    opened = open_atlas_v3_explorer_distribution(
        distribution,
        trusted_manifest_digest=trusted_digest,
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    shard_parent_name = f"{output.stem}.shards"
    manifest_key = trusted_digest.removeprefix("sha256:")
    shard_directory = (
        output.parent
        / shard_parent_name
        / manifest_key
        / ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE
    )
    shard_url_prefix = (
        f"{shard_parent_name}/{manifest_key}/"
        f"{ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE}"
    )
    full_corpus = build_atlas_v3_explorer_static_shards(
        opened,
        shard_directory,
        url_prefix=shard_url_prefix,
    )
    preview = render_atlas_v3_explorer(
        build_atlas_v3_explorer_model(opened, full_corpus=full_corpus)
    )
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

#!/usr/bin/env python3
"""Build the exact six-release Vocabulary Atlas v1 publication."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from refspec.atlas.v1_release import (
    VocabularyAtlasV1ReleaseError,
    build_vocabulary_atlas_v1_release,
    read_vocabulary_atlas_v1_release_definition,
)
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Build, reopen, publish, and accept one exact six-release Vocabulary Atlas v1.")
    )
    parser.add_argument(
        "--definition",
        type=Path,
        required=True,
        help="canonical tracked VocabularyAtlasV1ReleaseDefinition JSON",
    )
    parser.add_argument(
        "--definition-file-digest",
        required=True,
        help="independently trusted sha256 digest of the definition bytes",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
        help="root used to resolve every normalized path in the definition",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new directory that will receive the immutable release",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        definition = read_vocabulary_atlas_v1_release_definition(
            args.definition,
            expected_file_digest=args.definition_file_digest,
        )
        build = build_vocabulary_atlas_v1_release(
            definition,
            artifact_root=args.artifact_root,
            output_directory=args.output,
        )
    except (OSError, VocabularyAtlasV1ReleaseError, ValueError) as error:
        parser.exit(2, f"Vocabulary Atlas v1 build failed: {error}\n")
    sys.stdout.buffer.write(canonical_json_bytes(build.result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

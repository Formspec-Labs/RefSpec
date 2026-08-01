"""Command-line builder for the checked, static vocabulary-atlas asset."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .crosswalk import MappingCandidate, MappingFeedback, build_vocabulary_atlas
from .model import (
    VerifiedCrosswalkBundle,
    VerifiedVocabularyRelease,
    VocabularyAtlasError,
)


def _pinned_path(value: str) -> tuple[Path, str]:
    path, separator, digest = value.rpartition("=")
    if not separator or not path or not digest:
        raise argparse.ArgumentTypeError("expected PATH=sha256:<64 lowercase hex>")
    return Path(path), digest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic blank-node-free N-Quads from externally pinned "
            "RefSpec VocabularyRelease JSON files."
        )
    )
    parser.add_argument(
        "--release",
        action="append",
        required=True,
        type=_pinned_path,
        metavar="PATH=SHA256",
        help="repeat once per VocabularyRelease; the digest pins exact file bytes",
    )
    parser.add_argument(
        "--crosswalk-bundle",
        type=_pinned_path,
        metavar="PATH=SHA256",
        help="optional pinned candidate, machine-validation, and feedback bundle",
    )
    parser.add_argument(
        "--output-directory",
        required=True,
        type=Path,
        help="directory for atlas.nq and atlas-manifest.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        releases = [
            VerifiedVocabularyRelease.open(path, expected_file_digest=digest)
            for path, digest in args.release
        ]
        candidates: list[MappingCandidate] = []
        agents: list[dict[str, object]] = []
        baselines: list[dict[str, object]] = []
        feedback: list[MappingFeedback] = []
        bundle = None
        if args.crosswalk_bundle is not None:
            path, digest = args.crosswalk_bundle
            bundle = VerifiedCrosswalkBundle.open(path, expected_file_digest=digest)
            record = bundle.record()
            candidates = [
                MappingCandidate.from_dict(value)
                for value in record["mapping_candidates"]
            ]
            agents = [dict(value) for value in record["agent_validation_receipts"]]
            baselines = [
                dict(value) for value in record["baseline_validation_receipts"]
            ]
            feedback = [
                MappingFeedback.from_dict(value) for value in record["feedback"]
            ]
        asset = build_vocabulary_atlas(
            releases,
            mapping_candidates=candidates,
            agent_validation_receipts=agents,
            baseline_validation_receipts=baselines,
            feedback=feedback,
            crosswalk_bundle=bundle,
        )
        written = asset.write_to(args.output_directory)
    except (VocabularyAtlasError, FileExistsError, OSError) as error:
        parser.error(str(error))

    receipt = {
        "generationDigest": asset.generation_digest,
        "outputDirectory": str(args.output_directory),
        "files": {name: str(path) for name, path in sorted(written.items())},
        "manifest": asset.manifest(),
    }
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

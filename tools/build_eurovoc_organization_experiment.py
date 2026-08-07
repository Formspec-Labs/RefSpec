"""Build or independently recheck the local EuroVoc organization sidecar."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from refspec.registry.eurovoc_organization_experiment import (
    build_eurovoc_organization_artifact_from_paths,
    materialize_eurovoc_organization_artifact,
    verify_eurovoc_organization_directory,
)
from refspec.registry.eurovoc_thesaurus import EUROVOC_RELEASE_4_24

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "output" / "registry-real-data-sources"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "output" / "eurovoc-organization-experiment-4.24"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="directory containing the exact pinned EuroVoc ZIP and metadata",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="closed output directory",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="rebuild in memory and compare without changing output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    archive_path = args.source_root / "eurovoc-4.24-skos-core.zip"
    metadata_path = args.source_root / "eurovoc-4.24-metadata.ttl"
    try:
        artifact = build_eurovoc_organization_artifact_from_paths(
            EUROVOC_RELEASE_4_24,
            archive_path=archive_path,
            metadata_path=metadata_path,
        )
        if args.verify_only:
            verify_eurovoc_organization_directory(args.output, artifact)
            action = "verified"
        else:
            created = materialize_eurovoc_organization_artifact(args.output, artifact)
            action = "created" if created else "verified-existing"
    except (OSError, ValueError) as error:
        print(f"EuroVocOrganizationExperiment failed: {error}", file=sys.stderr)
        return 2

    summary = {
        "action": action,
        "artifactType": "EuroVocOrganizationExperiment",
        "canonicalPayloadDigest": artifact.manifest["canonicalPayloadDigest"],
        "manifestSha256": artifact.manifest_sha256,
        "output": str(args.output.resolve()),
        "status": artifact.manifest["status"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

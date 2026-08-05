#!/usr/bin/env python3
"""Verify and prepare the six Vocabulary Atlas v1 production catalogs.

This command performs local work only: it validates every pinned source
manifest, extracts the two exact releases for each selected job, and generates
the complete production candidate catalog.  Provider scoring and blind judging
are later stages named in the job manifest and are never invoked here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec.atlas.qualification_jobs import (
    VocabularyAtlasV1QualificationJobsError,
    prepare_vocabulary_atlas_v1_qualification_jobs,
    read_vocabulary_atlas_v1_qualification_jobs,
)
from refspec.storage import canonical_json

DEFAULT_MANIFEST = ROOT / "portfolio/vocabulary-atlas-v1-production-qualification-jobs.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prepare_vocabulary_atlas_v1_qualification",
        description=(
            "Verify exact source pins and run local extract plus complete production generation; "
            "provider scoring and judging remain later stages."
        ),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--job",
        action="append",
        dest="jobs",
        help="prepare one named job; repeat to prepare several (default: all six)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the canonical manifest and all five source digests without writing outputs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = read_vocabulary_atlas_v1_qualification_jobs(args.manifest)
        verified = manifest.verify_source_manifests(ROOT)
        if args.check:
            print(
                canonical_json(
                    {
                        "fileDigest": manifest.file_digest,
                        "id": manifest.identifier,
                        "jobCount": len(manifest.jobs),
                        "providerCalls": False,
                        "recordDigest": manifest.record_digest,
                        "sourceCount": len(verified),
                        "status": "verified",
                    }
                )
            )
            return 0
        result = prepare_vocabulary_atlas_v1_qualification_jobs(
            manifest,
            repository_root=ROOT,
            job_keys=args.jobs,
        )
    except VocabularyAtlasV1QualificationJobsError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

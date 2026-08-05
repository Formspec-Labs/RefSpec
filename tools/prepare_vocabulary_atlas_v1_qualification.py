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
    VocabularyAtlasV1QualificationJobs,
    VocabularyAtlasV1QualificationJobsError,
    prepare_vocabulary_atlas_v1_qualification_jobs,
    read_vocabulary_atlas_v1_qualification_jobs,
    verify_prepared_vocabulary_atlas_v1_qualification_jobs,
)
from refspec.atlas.qualification_spend import (
    VocabularyAtlasV1ProductionSpendAuthority,
    VocabularyAtlasV1ProductionSpendAuthorityError,
    read_vocabulary_atlas_v1_production_spend_authority,
    seal_vocabulary_atlas_v1_production_spend_authority,
)
from refspec.storage import canonical_json

DEFAULT_MANIFEST = ROOT / "portfolio/vocabulary-atlas-v1-production-qualification-jobs.json"
DEFAULT_SPEND_AUTHORITY = (
    ROOT
    / "output/vocabulary-atlas-v1-rc1/qualification-production/production-spend-authority.json"
)


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify the canonical manifest and all five source digests without writing outputs",
    )
    mode.add_argument(
        "--verify-prepared",
        action="store_true",
        help="verify all six existing extraction records and production catalogs without writing outputs",
    )
    mode.add_argument(
        "--prepare-spend-authority",
        action="store_true",
        help=(
            "seal one explicitly approved total into six fixed production-run caps; "
            "performs no provider calls"
        ),
    )
    parser.add_argument("--approved-by", help="absolute actor IRI for the explicit spend approval")
    parser.add_argument("--approved-at", help="timezone-aware explicit spend approval time")
    parser.add_argument(
        "--approved-total-cap",
        help="approved USD ceiling; must equal the fixed six-run allocation",
    )
    parser.add_argument(
        "--spend-authority-output",
        type=Path,
        default=DEFAULT_SPEND_AUTHORITY,
        help="canonical spend-authority output written only in approval mode",
    )
    return parser


def _safe_spend_authority_output(path: Path) -> Path:
    root = ROOT.resolve(strict=True)
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "spend authority output must stay inside the repository"
        ) from error
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "spend authority output must be a normalized repository path"
        )
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                "spend authority output must not traverse a symlink"
            )
    return candidate


def _prepare_spend_authority(
    args: argparse.Namespace,
    manifest: VocabularyAtlasV1QualificationJobs,
) -> VocabularyAtlasV1ProductionSpendAuthority:
    if not all((args.approved_by, args.approved_at, args.approved_total_cap)):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "--prepare-spend-authority requires --approved-by, --approved-at, and --approved-total-cap"
        )
    output = _safe_spend_authority_output(args.spend_authority_output)
    record = seal_vocabulary_atlas_v1_production_spend_authority(
        manifest,
        repository_root=ROOT,
        approved_by=args.approved_by,
        approved_at=args.approved_at,
        approved_total_spend_cap_usd=args.approved_total_cap,
    )
    payload = (canonical_json(record) + "\n").encode("utf-8")
    if output.exists() or output.is_symlink():
        if not output.is_file() or output.is_symlink():
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"spend authority output must be a regular file: {output}"
            )
        if output.read_bytes() != payload:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                "spend authority output already exists with different bytes"
            )
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    return read_vocabulary_atlas_v1_production_spend_authority(
        output,
        manifest=manifest,
        repository_root=ROOT,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.jobs and (args.check or args.verify_prepared or args.prepare_spend_authority):
        parser.error("--job applies only when preparing catalogs")
    approval_options = (args.approved_by, args.approved_at, args.approved_total_cap)
    if any(value is not None for value in approval_options) and not args.prepare_spend_authority:
        parser.error("spend approval options require --prepare-spend-authority")
    try:
        manifest = read_vocabulary_atlas_v1_qualification_jobs(args.manifest)
        if args.check:
            verified = manifest.verify_source_manifests(ROOT)
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
        if args.prepare_spend_authority:
            authority = _prepare_spend_authority(args, manifest)
            print(
                canonical_json(
                    {
                        "approvedTotalSpendCapUsd": authority.approved_total_spend_cap_usd,
                        "fileDigest": authority.file_digest,
                        "id": authority.identifier,
                        "jobCount": len(authority.jobs),
                        "providerCalls": False,
                        "recordDigest": authority.record_digest,
                        "status": "prepared",
                    }
                )
            )
            return 0
        if args.verify_prepared:
            result = verify_prepared_vocabulary_atlas_v1_qualification_jobs(
                manifest,
                repository_root=ROOT,
            )
        else:
            result = prepare_vocabulary_atlas_v1_qualification_jobs(
                manifest,
                repository_root=ROOT,
                job_keys=args.jobs,
            )
    except (
        VocabularyAtlasV1QualificationJobsError,
        VocabularyAtlasV1ProductionSpendAuthorityError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

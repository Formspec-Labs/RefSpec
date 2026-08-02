"""Build one static vocabulary atlas from exact published input files."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .federal_register import PinnedFederalRegisterThesaurus2025AtlasRelease
from .icpsr import (
    ICPSR_MANAGED_RELEASE_MANIFEST_TYPE,
    PinnedIcpsrSubjectAtlasRelease,
)
from .model import (
    CrosswalkBundle,
    PinnedManagedRelease,
    PinnedRulespecCoreRelease,
    VerifiedManagedReleaseSource,
    build_vocabulary_atlas,
)

AUTO_FORMAT = "auto"
MANAGED_BUNDLE_FORMAT = "managed-bundle"
FEDERAL_REGISTER_2025_FORMAT = "federal-register-thesaurus-2025"
ICPSR_SUBJECT_FORMAT = "icpsr-subject-thesaurus"
INPUT_FORMATS = (
    AUTO_FORMAT,
    MANAGED_BUNDLE_FORMAT,
    FEDERAL_REGISTER_2025_FORMAT,
    ICPSR_SUBJECT_FORMAT,
)

_FEDERAL_REGISTER_2025_MANIFEST_TYPE = "urn:ref:type:FederalRegisterThesaurus2025ManagedReleaseManifest"
_SPECIALIZED_FORMATS_BY_MANIFEST_TYPE = {
    _FEDERAL_REGISTER_2025_MANIFEST_TYPE: FEDERAL_REGISTER_2025_FORMAT,
    ICPSR_MANAGED_RELEASE_MANIFEST_TYPE: ICPSR_SUBJECT_FORMAT,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refspec-build-vocabulary-atlas")
    parser.add_argument(
        "--managed-release",
        action="append",
        nargs=2,
        metavar=("MANIFEST", "SHA256"),
        required=True,
        help="managed-release manifest path and exact file digest; repeat for each release",
    )
    parser.add_argument(
        "--input-format",
        choices=INPUT_FORMATS,
        default=AUTO_FORMAT,
        help=(
            "reader for every --managed-release input; 'auto' (the default) selects it from "
            "the declared manifest type"
        ),
    )
    parser.add_argument("--rulespec-core", type=Path, required=True)
    parser.add_argument("--rulespec-core-file-digest", required=True)
    parser.add_argument("--rulespec-core-release-id", required=True)
    parser.add_argument("--rulespec-core-release-digest", required=True)
    parser.add_argument(
        "--crosswalk",
        nargs=3,
        metavar=("FILE", "FILE_SHA256", "BUNDLE_SHA256"),
        help="optional canonical crosswalk file and its exact file and root digests",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _detected_input_format(manifest_path: str) -> str:
    """Name the reader that matches the declared manifest type.

    Only a specialized package declares its own manifest type.  Every other
    shape, and every unreadable file, routes to the generic managed-bundle
    reader so its own fail-closed checks report the error.  The caller has
    already pinned these bytes by digest, so the declared type cannot select a
    reader the operator did not pin.
    """

    try:
        manifest = json.loads(Path(manifest_path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return MANAGED_BUNDLE_FORMAT
    if not isinstance(manifest, dict):
        return MANAGED_BUNDLE_FORMAT
    return _SPECIALIZED_FORMATS_BY_MANIFEST_TYPE.get(manifest.get("type"), MANAGED_BUNDLE_FORMAT)


def open_release(
    manifest_path: str,
    digest: str,
    *,
    input_format: str = AUTO_FORMAT,
) -> VerifiedManagedReleaseSource:
    """Open one exact pinned input through the reader its shape requires."""

    selected = _detected_input_format(manifest_path) if input_format == AUTO_FORMAT else input_format
    if selected == FEDERAL_REGISTER_2025_FORMAT:
        return PinnedFederalRegisterThesaurus2025AtlasRelease.open(
            manifest_path,
            expected_manifest_digest=digest,
        )
    if selected == ICPSR_SUBJECT_FORMAT:
        return PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest=digest,
        )
    return PinnedManagedRelease.open(manifest_path, expected_manifest_digest=digest)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    releases = tuple(
        open_release(path, digest, input_format=args.input_format) for path, digest in args.managed_release
    )
    core = PinnedRulespecCoreRelease.open(
        args.rulespec_core,
        expected_file_digest=args.rulespec_core_file_digest,
        expected_release_id=args.rulespec_core_release_id,
        expected_release_digest=args.rulespec_core_release_digest,
    )
    crosswalk = None
    if args.crosswalk is not None:
        path, file_digest, bundle_digest = args.crosswalk
        crosswalk = CrosswalkBundle.open(
            path,
            expected_file_digest=file_digest,
            expected_bundle_digest=bundle_digest,
        )
    asset = build_vocabulary_atlas(releases, rulespec_core=core, crosswalk=crosswalk)
    output = asset.write(args.output)
    print(
        json.dumps(
            {
                "assetId": asset.manifest["id"],
                "manifestDigest": asset.manifest_digest,
                "outputDigest": asset.output_digest,
                "outputDirectory": str(output.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "AUTO_FORMAT",
    "FEDERAL_REGISTER_2025_FORMAT",
    "ICPSR_SUBJECT_FORMAT",
    "INPUT_FORMATS",
    "MANAGED_BUNDLE_FORMAT",
    "build_parser",
    "main",
    "open_release",
]

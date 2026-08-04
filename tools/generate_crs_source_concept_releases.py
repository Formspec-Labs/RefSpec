#!/usr/bin/env python3
"""Generate or verify the full CRS source-concept release evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_CAPTURE_ROOT = ROOT / "output" / "refspec-vocabulary-portfolio" / "crs" / "2026-07-30"
DEFAULT_OUTPUT = ROOT / "research" / "evidence" / "crs-source-concept-releases-2026-08-04"
EVIDENCE_FILE = "release-evidence.json"

_RELEASE_LAYOUT = (
    ("legislativeSubjects", "legislative-subjects", "subject"),
    ("legislativeEntities", "legislative-entities", "entity"),
    ("policyAreas", "policy-areas", "subject"),
)


class CRSSourceConceptGenerationError(ValueError):
    """The generated CRS evidence is absent, stale, or inconsistent."""


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    from refspec.storage import canonical_json

    return (canonical_json(_plain(value)) + "\n").encode("utf-8")


def _release_items(releases: Any) -> tuple[tuple[str, str, str, Any], ...]:
    return (
        (
            "legislativeSubjects",
            "legislative-subjects",
            "subject",
            releases.legislative_subjects,
        ),
        (
            "legislativeEntities",
            "legislative-entities",
            "entity",
            releases.legislative_entities,
        ),
        ("policyAreas", "policy-areas", "subject", releases.policy_areas),
    )


def _evidence(releases: Any) -> dict[str, Any]:
    rows = []
    for name, path, ring, release in _release_items(releases):
        source_scheme = release.release_manifest["sourceScheme"]
        rows.append(
            {
                "name": name,
                "path": path,
                "semanticRing": ring,
                "sourceScheme": source_scheme["id"],
                "conceptCount": len(release.concepts),
                "rightsRecordCount": release.release_manifest["rightsRecordCount"],
                "rightsSetDigest": release.release_manifest["rightsSetDigest"],
                "rightsStatuses": sorted({str(value["rightsStatus"]) for value in release.rights_metadata}),
                "releaseId": release.release_id,
                "releaseDigest": release.release_digest,
                "logicalDigest": release.logical_digest,
                "manifestDigest": release.manifest_digest,
                "sourceCapture": release.release_manifest["sourceCapture"],
            }
        )
    return {
        "schemaVersion": "1.0",
        "evidenceKind": "crsSourceConceptReleases",
        "captureDate": "2026-07-30",
        "generator": "tools/generate_crs_source_concept_releases.py",
        "summary": {
            "releaseCount": len(rows),
            "subjectReleaseCount": sum(row["semanticRing"] == "subject" for row in rows),
            "entityReleaseCount": sum(row["semanticRing"] == "entity" for row in rows),
            "conceptCount": sum(int(row["conceptCount"]) for row in rows),
        },
        "releases": rows,
    }


def generated_files(releases: Any) -> dict[str, bytes]:
    """Return every checked path and byte from three release bundles."""

    files: dict[str, bytes] = {}
    for _name, path, _ring, release in _release_items(releases):
        for relative, payload in release.artifact_bytes().items():
            files[f"{path}/{relative}"] = payload
    files[EVIDENCE_FILE] = _canonical_bytes(_evidence(releases))
    return dict(sorted(files.items()))


def _actual_files(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise CRSSourceConceptGenerationError(f"generated evidence directory is missing or unsafe: {root}")
    result: dict[str, bytes] = {}
    for item in root.rglob("*"):
        if item.is_symlink():
            raise CRSSourceConceptGenerationError(f"generated evidence contains a symlink: {item}")
        if item.is_file():
            result[item.relative_to(root).as_posix()] = item.read_bytes()
    return dict(sorted(result.items()))


def _compare_files(
    *,
    actual: Mapping[str, bytes],
    expected: Mapping[str, bytes],
    label: str,
) -> None:
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise CRSSourceConceptGenerationError(f"{label} file set differs; missing={missing!r}, extra={extra!r}")
    changed = [path for path in expected if actual[path] != expected[path]]
    if changed:
        raise CRSSourceConceptGenerationError(f"{label} bytes differ for {changed!r}")


def _read_evidence(root: Path) -> Mapping[str, Any]:
    path = root / EVIDENCE_FILE
    if path.is_symlink() or not path.is_file():
        raise CRSSourceConceptGenerationError(f"generated evidence lacks {EVIDENCE_FILE}")
    payload = path.read_bytes()
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CRSSourceConceptGenerationError(f"{EVIDENCE_FILE} must be valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise CRSSourceConceptGenerationError(f"{EVIDENCE_FILE} must contain one object")
    if _canonical_bytes(value) != payload:
        raise CRSSourceConceptGenerationError(f"{EVIDENCE_FILE} bytes are not canonical")
    required = {
        "schemaVersion",
        "evidenceKind",
        "captureDate",
        "generator",
        "summary",
        "releases",
    }
    if set(value) != required or value.get("schemaVersion") != "1.0":
        raise CRSSourceConceptGenerationError(f"{EVIDENCE_FILE} shape or version is unsupported")
    if (
        value.get("evidenceKind") != "crsSourceConceptReleases"
        or value.get("captureDate") != "2026-07-30"
        or value.get("generator") != "tools/generate_crs_source_concept_releases.py"
    ):
        raise CRSSourceConceptGenerationError(f"{EVIDENCE_FILE} names another evidence product")
    return value


def _open_materialized(root: Path) -> dict[str, Any]:
    from refspec.registry.infrastructure.source_concept_release import (
        SourceConceptReleaseView,
    )

    evidence = _read_evidence(root)
    rows = evidence.get("releases")
    if not isinstance(rows, list) or len(rows) != len(_RELEASE_LAYOUT):
        raise CRSSourceConceptGenerationError("release evidence must describe exactly three releases")
    views: dict[str, Any] = {}
    expected_row_fields = {
        "name",
        "path",
        "semanticRing",
        "sourceScheme",
        "conceptCount",
        "rightsRecordCount",
        "rightsSetDigest",
        "rightsStatuses",
        "releaseId",
        "releaseDigest",
        "logicalDigest",
        "manifestDigest",
        "sourceCapture",
    }
    for index, (row, layout) in enumerate(zip(rows, _RELEASE_LAYOUT, strict=True)):
        if not isinstance(row, Mapping) or set(row) != expected_row_fields:
            raise CRSSourceConceptGenerationError(f"release evidence row {index} has unsupported fields")
        name, relative, ring = layout
        if row.get("name") != name or row.get("path") != relative or row.get("semanticRing") != ring:
            raise CRSSourceConceptGenerationError(f"release evidence row {index} differs from the CRS release layout")
        manifest_digest = row.get("manifestDigest")
        if not isinstance(manifest_digest, str):
            raise CRSSourceConceptGenerationError(f"release evidence row {index} lacks an external manifest digest")
        view = SourceConceptReleaseView.open(
            root / relative / "bundle-manifest.json",
            expected_manifest_digest=manifest_digest,
        )
        source_scheme = view.release_manifest["sourceScheme"]
        actual = {
            "name": name,
            "path": relative,
            "semanticRing": view.semantic_ring,
            "sourceScheme": source_scheme["id"],
            "conceptCount": len(view.concepts),
            "rightsRecordCount": len(view.rights_metadata),
            "rightsSetDigest": view.release_manifest["rightsSetDigest"],
            "rightsStatuses": sorted({str(value["rightsStatus"]) for value in view.rights_metadata}),
            "releaseId": view.release_id,
            "releaseDigest": view.release_digest,
            "logicalDigest": view.logical_digest,
            "manifestDigest": view.manifest_digest,
            "sourceCapture": _plain(view.release_manifest["sourceCapture"]),
        }
        if dict(row) != actual:
            raise CRSSourceConceptGenerationError(f"release evidence row {index} differs from its verified package")
        views[name] = view
    expected_summary = {
        "releaseCount": 3,
        "subjectReleaseCount": 2,
        "entityReleaseCount": 1,
        "conceptCount": sum(len(view.concepts) for view in views.values()),
    }
    if evidence.get("summary") != expected_summary:
        raise CRSSourceConceptGenerationError("release evidence summary differs from its verified packages")
    if {item.name for item in root.iterdir()} != {
        EVIDENCE_FILE,
        *(relative for _name, relative, _ring in _RELEASE_LAYOUT),
    }:
        raise CRSSourceConceptGenerationError("generated evidence top-level entries differ")
    return views


def _packages_from_views(views: Mapping[str, Any]) -> Any:
    from refspec.registry.packages.crs_source_packages import (
        CRSResourceReconciliation,
        CRSSourcePackages,
    )

    subjects = views["legislativeSubjects"]
    entities = views["legislativeEntities"]
    policy = views["policyAreas"]
    if subjects.source_bundle.artifact_bytes() != entities.source_bundle.artifact_bytes():
        raise CRSSourceConceptGenerationError(
            "legislative subject and entity releases do not share one exact source capture"
        )
    if (
        subjects.reconciliation_record is None
        or entities.reconciliation_record is None
        or policy.reconciliation_record is None
    ):
        raise CRSSourceConceptGenerationError("each CRS release must bind its exact reconciliation record")
    if _plain(subjects.reconciliation_record) != _plain(entities.reconciliation_record):
        raise CRSSourceConceptGenerationError("legislative subject and entity reconciliation records differ")
    legislative_reconciliation = CRSResourceReconciliation.from_dict(_plain(subjects.reconciliation_record))
    policy_reconciliation = CRSResourceReconciliation.from_dict(_plain(policy.reconciliation_record))
    packages = CRSSourcePackages(
        legislative_subject_terms=subjects.source_bundle,
        policy_areas=policy.source_bundle,
        reconciliations=(legislative_reconciliation, policy_reconciliation),
    )
    packages.require_reconciled()
    return packages


def releases_from_materialized(root: Path) -> Any:
    """Rebuild current release objects from externally pinned checked evidence."""

    from refspec.registry.packages.crs_source_concept_releases import (
        build_crs_source_concept_releases,
    )

    return build_crs_source_concept_releases(_packages_from_views(_open_materialized(root)))


def releases_from_capture_root(capture_root: Path) -> Any:
    """Build current releases from the exact retained Congress.gov pages."""

    from refspec.registry.packages.crs_source_concept_releases import (
        build_crs_source_concept_releases,
    )
    from refspec.registry.packages.crs_source_packages import (
        build_crs_source_packages_from_capture_root,
    )

    if capture_root.is_symlink() or not capture_root.is_dir():
        raise CRSSourceConceptGenerationError(f"retained CRS capture root is missing or unsafe: {capture_root}")
    packages = build_crs_source_packages_from_capture_root(capture_root)
    packages.require_reconciled()
    return build_crs_source_concept_releases(packages)


def check_materialized(
    output: Path,
    *,
    source_releases: Any | None = None,
) -> Any:
    """Verify pins, reopen all packages, and reproduce every checked byte."""

    actual = _actual_files(output)
    rebuilt = releases_from_materialized(output)
    _compare_files(
        actual=actual,
        expected=generated_files(rebuilt),
        label="checked CRS source-concept evidence",
    )
    if source_releases is not None:
        _compare_files(
            actual=actual,
            expected=generated_files(source_releases),
            label="retained-capture CRS source-concept evidence",
        )
    return rebuilt


def _safe_output(path: Path) -> Path:
    absolute = path.absolute()
    if absolute == Path(absolute.anchor) or absolute.parent == absolute:
        raise CRSSourceConceptGenerationError("generated evidence output must not be a filesystem root")
    if absolute.is_symlink():
        raise CRSSourceConceptGenerationError("generated evidence output must not be a symlink")
    if absolute.exists() and not absolute.is_dir():
        raise CRSSourceConceptGenerationError("generated evidence output must be a directory path")
    return absolute


def write_materialized(output: Path, releases: Any) -> Path:
    """Atomically replace one generated evidence directory and verify it."""

    destination = _safe_output(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}-generate-",
            dir=destination.parent,
        )
    )
    staging = temporary_parent / "staging"
    staging.mkdir()
    backup_parent: Path | None = None
    try:
        for relative, payload in generated_files(releases).items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        check_materialized(staging, source_releases=releases)
        if destination.exists():
            backup_parent = Path(
                tempfile.mkdtemp(
                    prefix=f".{destination.name}-previous-",
                    dir=destination.parent,
                )
            )
            os.replace(destination, backup_parent / "previous")
        try:
            os.replace(staging, destination)
        except BaseException:
            if backup_parent is not None and (backup_parent / "previous").exists():
                os.replace(backup_parent / "previous", destination)
            raise
        if backup_parent is not None:
            shutil.rmtree(backup_parent)
            backup_parent = None
        check_materialized(destination, source_releases=releases)
        return destination
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)
        if backup_parent is not None:
            if not destination.exists() and (backup_parent / "previous").exists():
                os.replace(backup_parent / "previous", destination)
            shutil.rmtree(backup_parent, ignore_errors=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify the checked evidence (default)",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="write and then verify the evidence",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--capture-root",
        type=Path,
        help="exact retained 2026-07-30 CRS capture root",
    )
    source.add_argument(
        "--source-evidence",
        type=Path,
        help="rebuild from another externally pinned generated evidence directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="generated evidence directory",
    )
    return parser.parse_args()


def _selected_source(args: argparse.Namespace, *, for_write: bool) -> Any | None:
    if args.capture_root is not None:
        return releases_from_capture_root(args.capture_root)
    if args.source_evidence is not None:
        return releases_from_materialized(args.source_evidence)
    if DEFAULT_CAPTURE_ROOT.is_dir():
        return releases_from_capture_root(DEFAULT_CAPTURE_ROOT)
    if for_write:
        if args.output.is_dir():
            return releases_from_materialized(args.output)
        raise CRSSourceConceptGenerationError("--write needs the retained capture root or --source-evidence")
    return None


def _selection_line(releases: Any) -> str:
    return ", ".join(
        f"{name}={release.release_id} ({release.manifest_digest})"
        for name, _path, _ring, release in _release_items(releases)
    )


def main() -> int:
    args = _arguments()
    try:
        source = _selected_source(args, for_write=args.write)
        if args.write:
            assert source is not None
            output = write_materialized(args.output, source)
            print(f"wrote {output}")
            print(_selection_line(source))
            return 0
        checked = check_materialized(args.output, source_releases=source)
        print(f"CRS source-concept evidence is current: {_selection_line(checked)}")
        return 0
    except (OSError, ValueError) as error:
        print(f"CRS source-concept generation error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

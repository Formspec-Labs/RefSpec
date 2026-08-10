#!/usr/bin/env python3
"""Validate RefSpec's executable dependency on a Rulespec checkout."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BINDING_ROOT = Path(__file__).resolve().parent.parent
REFSPEC_ROOT = BINDING_ROOT.parents[2]
MANIFEST_PATH = BINDING_ROOT / "tests" / "requirement-to-test-manifest.json"
DEPENDENCY_MANIFEST_PATH = REFSPEC_ROOT / "profiles" / "rulespec-dependency.json"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def run(
    command: list[str],
    *,
    cwd: Path,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture,
    )


def load_dependency_manifest(
    path: Path = DEPENDENCY_MANIFEST_PATH,
) -> tuple[dict[str, object] | None, list[str]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"cannot read Rulespec dependency manifest: {exc}"]
    if not isinstance(manifest, dict):
        return None, ["Rulespec dependency manifest must be an object"]
    return manifest, []


def external_paths() -> list[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return sorted({relative for entry in manifest["coverage"] for relative in entry.get("externalRulespecPaths", [])})


def validate_paths(rulespec_dir: Path) -> list[str]:
    return [
        f"missing Rulespec gate input: {relative}"
        for relative in external_paths()
        if not (rulespec_dir / relative).is_file()
    ]


def validate_manifest_shape(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    version = manifest.get("rulespecVersion")
    contract_revision = manifest.get("contractRevision")
    evidence_revision = manifest.get("evidenceRevision")
    constraint_digest = manifest.get("constraintDigest")
    corpus_digest = manifest.get("conformanceCorpusDigest")
    if manifest.get("schemaVersion") != "1.0":
        errors.append("Rulespec dependency manifest must use schemaVersion '1.0'")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        errors.append("Rulespec dependency manifest has no exact semantic version")
    if not isinstance(contract_revision, str) or not REVISION_PATTERN.fullmatch(contract_revision):
        errors.append("Rulespec dependency manifest has no exact tested contract revision")
    if not isinstance(evidence_revision, str) or not REVISION_PATTERN.fullmatch(evidence_revision):
        errors.append("Rulespec dependency manifest has no exact evidence revision")
    if not isinstance(constraint_digest, str) or not DIGEST_PATTERN.fullmatch(constraint_digest):
        errors.append("Rulespec dependency manifest has no exact constraint digest")
    if not isinstance(corpus_digest, str) or not DIGEST_PATTERN.fullmatch(corpus_digest):
        errors.append("Rulespec dependency manifest has no exact conformance-corpus digest")
    if manifest.get("releaseAvailability") not in {"localUnpublished", "published"}:
        errors.append("Rulespec dependency manifest has an unknown releaseAvailability")
    if manifest.get("productionConformanceEligible") is not (manifest.get("releaseAvailability") == "published"):
        errors.append("productionConformanceEligible must be true exactly when releaseAvailability is published")
    if manifest.get("constraintDigestScope") != "globalRulespecContract":
        errors.append("constraintDigestScope must identify the global Rulespec contract")
    if not isinstance(manifest.get("adoptedConstraintSources"), list):
        errors.append("adoptedConstraintSources must be an array")
    validator = manifest.get("validator")
    if not isinstance(validator, dict):
        errors.append("validator must be an object")
    else:
        if not str(validator.get("identity") or "").strip():
            errors.append("validator.identity is required")
        source_revision = validator.get("sourceRevision")
        if not isinstance(source_revision, str) or not REVISION_PATTERN.fullmatch(source_revision):
            errors.append("validator.sourceRevision must be a full Git revision")
        receipt_digest = validator.get("selfCertificationSha256")
        if not isinstance(receipt_digest, str) or not SHA256_PATTERN.fullmatch(receipt_digest):
            errors.append("validator.selfCertificationSha256 must be a lowercase SHA-256 value")
        if validator.get("completeGateCommand") != "make test":
            errors.append("validator.completeGateCommand must be 'make test'")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rulespec-dir",
        type=Path,
        required=True,
        help="path to the Rulespec repository",
    )
    parser.add_argument(
        "--run-rulespec-gate",
        action="store_true",
        help="run Rulespec's complete make test gate after checking inputs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rulespec_dir = args.rulespec_dir.resolve()
    errors: list[str] = []

    manifest, manifest_errors = load_dependency_manifest()
    errors.extend(manifest_errors)
    if manifest is not None:
        errors.extend(validate_manifest_shape(manifest))

    repository_check = (
        run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=rulespec_dir,
            capture=True,
        )
        if rulespec_dir.is_dir()
        else None
    )
    if repository_check is None or repository_check.returncode or repository_check.stdout.strip() != "true":
        errors.append(f"not a Rulespec Git checkout: {rulespec_dir}")
    else:
        errors.extend(validate_paths(rulespec_dir))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if args.run_rulespec_gate:
        result = run(["make", "test"], cwd=rulespec_dir)
        if result.returncode:
            print("FAIL: Rulespec make test failed", file=sys.stderr)
            return result.returncode

    print(f"RefSpec/Rulespec gate: {len(external_paths())} upstream inputs found; manifest and working tree verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate RefSpec's executable dependency on a Rulespec checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BINDING_ROOT = Path(__file__).resolve().parent.parent
REFSPEC_ROOT = BINDING_ROOT.parents[2]
MANIFEST_PATH = BINDING_ROOT / "tests" / "requirement-to-test-manifest.json"
PROFILE_PATH = REFSPEC_ROOT / "profiles" / "rulespec-application-profile.md"
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


def metadata_value(profile: str, label: str) -> str | None:
    pattern = re.compile(
        rf"^>\s+\*\*{re.escape(label)}:\*\*\s+`([^`]+)`\s*$",
        re.MULTILINE,
    )
    match = pattern.search(profile)
    return match.group(1) if match else None


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


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def external_paths() -> list[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return sorted({relative for entry in manifest["coverage"] for relative in entry.get("externalRulespecPaths", [])})


def validate_paths(rulespec_dir: Path) -> list[str]:
    return [
        f"missing Rulespec gate input: {relative}"
        for relative in external_paths()
        if not (rulespec_dir / relative).is_file()
    ]


def current_contract_digest(rulespec_dir: Path) -> tuple[str | None, str | None]:
    result = run(
        [
            "uv",
            "run",
            "--python",
            "3.12",
            "--with-requirements",
            "requirements.txt",
            "python",
            "tools/l0_mapping_audit.py",
            "--print-contract-version",
        ],
        cwd=rulespec_dir,
        capture=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        return None, f"could not compute Rulespec constraint digest: {detail}"
    return result.stdout.strip(), None


def current_corpus_digest(rulespec_dir: Path) -> tuple[str | None, str | None]:
    result = run(
        [
            "uv",
            "run",
            "--python",
            "3.12",
            "--with-requirements",
            "requirements.txt",
            "python",
            "-c",
            (
                "import sys; "
                "sys.path.insert(0, 'tools'); "
                "from conformance_report import corpus_digest, walk_fixtures; "
                "print(corpus_digest(walk_fixtures()))"
            ),
        ],
        cwd=rulespec_dir,
        capture=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        return None, f"could not compute Rulespec conformance-corpus digest: {detail}"
    return result.stdout.strip(), None


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
    if not isinstance(manifest.get("pinTextFiles"), dict):
        errors.append("pinTextFiles must be an object")
    if manifest.get("generatedArtifactMode") != "regenerateAndVerify":
        errors.append("generatedArtifactMode must be regenerateAndVerify")
    generated = manifest.get("generatedArtifacts")
    if not isinstance(generated, dict) or not generated:
        errors.append("generatedArtifacts must be a non-empty object")
    elif any(
        not isinstance(path, str) or not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest)
        for path, digest in generated.items()
    ):
        errors.append("generatedArtifacts must map relative paths to lowercase SHA-256 values")
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


def validate_pin_text(
    manifest: dict[str, object],
    *,
    refspec_root: Path = REFSPEC_ROOT,
) -> list[str]:
    version = str(manifest["rulespecVersion"])
    contract_revision = str(manifest["contractRevision"])
    evidence_revision = str(manifest["evidenceRevision"])
    constraint_digest = str(manifest["constraintDigest"])
    base_version = version.split("-", 1)[0]
    version_pattern = re.compile(rf"\b{re.escape(base_version)}(?:-[0-9A-Za-z.-]+)?\b")
    errors: list[str] = []
    pin_files = manifest.get("pinTextFiles")
    assert isinstance(pin_files, dict)
    for relative, mode in pin_files.items():
        path = refspec_root / str(relative)
        if not path.is_file():
            errors.append(f"pin text file does not exist: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        versions = set(version_pattern.findall(text))
        if versions != {version}:
            errors.append(f"{relative} contains Rulespec versions {sorted(versions)!r}, expected only {version!r}")
        if mode == "complete":
            for label, expected in (
                ("tested contract revision", contract_revision),
                ("evidence revision", evidence_revision),
                ("constraint digest", constraint_digest),
            ):
                if expected not in text:
                    errors.append(f"{relative} omits the {label} {expected!r}")
        elif mode != "versionOnly":
            errors.append(f"{relative} has unknown pin-text mode {mode!r}")
    return errors


def validate_closure_pin(
    rulespec_dir: Path,
    *,
    dependency_manifest_path: Path = DEPENDENCY_MANIFEST_PATH,
    refspec_root: Path = REFSPEC_ROOT,
) -> list[str]:
    manifest, errors = load_dependency_manifest(dependency_manifest_path)
    if errors or manifest is None:
        return errors
    errors.extend(validate_manifest_shape(manifest))
    if errors:
        return errors

    profile = PROFILE_PATH.read_text(encoding="utf-8")
    version = str(manifest["rulespecVersion"])
    contract_revision = str(manifest["contractRevision"])
    evidence_revision = str(manifest["evidenceRevision"])
    digest = str(manifest["constraintDigest"])
    corpus_digest = str(manifest["conformanceCorpusDigest"])
    profile_values = {
        "Vocabulary-closure Rulespec version": version,
        "Vocabulary-closure revision": evidence_revision,
        "Vocabulary-closure constraint digest": digest,
        "Tested contract revision": contract_revision,
    }
    for label, expected in profile_values.items():
        if metadata_value(profile, label) != expected:
            errors.append(f"application profile {label!r} does not match dependency manifest")
    errors.extend(validate_pin_text(manifest, refspec_root=refspec_root))

    head = run(
        ["git", "rev-parse", "HEAD"],
        cwd=rulespec_dir,
        capture=True,
    ).stdout.strip()
    if head != evidence_revision:
        errors.append(f"Rulespec HEAD {head!r} does not match evidence revision {evidence_revision!r}")

    for label, revision in (
        ("contractRevision", contract_revision),
        ("evidenceRevision", evidence_revision),
    ):
        result = run(
            ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
            cwd=rulespec_dir,
            capture=True,
        )
        if result.returncode:
            errors.append(f"Rulespec {label} {revision!r} is not an available commit")
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", contract_revision, evidence_revision],
        cwd=rulespec_dir,
        capture=True,
    )
    if ancestry.returncode:
        errors.append("tested contract revision is not an ancestor of the evidence revision")

    dirty = run(
        ["git", "status", "--porcelain"],
        cwd=rulespec_dir,
        capture=True,
    ).stdout.strip()
    if dirty:
        errors.append("Rulespec checkout is dirty; an immutable closure pin cannot be verified")

    actual_digest, digest_error = current_contract_digest(rulespec_dir)
    if digest_error:
        errors.append(digest_error)
    elif actual_digest != digest:
        errors.append(f"Rulespec constraint digest {actual_digest!r} does not match {digest!r}")

    actual_corpus, corpus_error = current_corpus_digest(rulespec_dir)
    if corpus_error:
        errors.append(corpus_error)
    elif actual_corpus != corpus_digest:
        errors.append(f"Rulespec conformance-corpus digest {actual_corpus!r} does not match {corpus_digest!r}")

    version_path = rulespec_dir / "VERSION"
    actual_version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else None
    if actual_version != version:
        errors.append(f"Rulespec VERSION {actual_version!r} does not match {version!r}")

    for relative in manifest["adoptedConstraintSources"]:
        if not (rulespec_dir / str(relative)).exists():
            errors.append(f"missing adopted Rulespec constraint source: {relative}")

    validator = manifest["validator"]
    assert isinstance(validator, dict)
    if validator.get("sourceRevision") != contract_revision:
        errors.append("validator.sourceRevision must match contractRevision")
    certification_relative = str(validator["selfCertificationPath"])
    certification_path = rulespec_dir / certification_relative
    if not certification_path.is_file():
        errors.append(f"missing Rulespec self-certification: {certification_relative}")
    else:
        actual_receipt_digest = sha256_file(certification_path)
        expected_receipt_digest = str(validator["selfCertificationSha256"])
        if actual_receipt_digest != expected_receipt_digest:
            errors.append(
                f"Rulespec self-certification digest {actual_receipt_digest!r} "
                f"does not match {expected_receipt_digest!r}"
            )
        certification = certification_path.read_text(encoding="utf-8")
        for label, expected in (
            ("rulespec version", version),
            ("tested source revision", contract_revision),
            ("constraint digest", digest),
            ("conformance-corpus digest", corpus_digest),
        ):
            if expected not in certification:
                errors.append(f"Rulespec self-certification omits {label} {expected!r}")

    generated = manifest["generatedArtifacts"]
    assert isinstance(generated, dict)
    for relative, expected in generated.items():
        artifact_path = rulespec_dir / str(relative)
        if not artifact_path.is_file():
            errors.append(f"missing generated Rulespec artifact: {relative}")
            continue
        actual = sha256_file(artifact_path)
        if actual != expected:
            errors.append(f"generated Rulespec artifact {relative} has SHA-256 {actual!r}, expected {expected!r}")
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
    parser.add_argument(
        "--require-closure-pin",
        action="store_true",
        help="require the exact committed revision and constraint digest",
    )
    parser.add_argument(
        "--dependency-manifest",
        type=Path,
        default=DEPENDENCY_MANIFEST_PATH,
        help="Rulespec dependency manifest; defaults to RefSpec's authoritative pin",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rulespec_dir = args.rulespec_dir.resolve()
    errors: list[str] = []
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

    if args.require_closure_pin:
        errors.extend(
            validate_closure_pin(
                rulespec_dir,
                dependency_manifest_path=args.dependency_manifest,
            )
        )
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1

    qualifier = "immutable closure pin" if args.require_closure_pin else "working tree"
    print(f"RefSpec/Rulespec gate: {len(external_paths())} upstream inputs found; {qualifier} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

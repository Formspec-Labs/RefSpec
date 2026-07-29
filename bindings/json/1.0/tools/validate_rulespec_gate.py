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
PROFILE_PATH = REFSPEC_ROOT / "profiles" / "rulespec-application-profile.md"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def validate_closure_pin(rulespec_dir: Path) -> list[str]:
    profile = PROFILE_PATH.read_text(encoding="utf-8")
    version = metadata_value(profile, "Vocabulary-closure Rulespec version")
    revision = metadata_value(profile, "Vocabulary-closure revision")
    digest = metadata_value(profile, "Vocabulary-closure constraint digest")
    errors: list[str] = []

    if version is None or not VERSION_PATTERN.fullmatch(version):
        errors.append("application profile has no exact vocabulary-closure version")
    if revision is None or not REVISION_PATTERN.fullmatch(revision):
        errors.append("application profile has no exact vocabulary-closure revision")
    if digest is None or not DIGEST_PATTERN.fullmatch(digest):
        errors.append("application profile has no exact vocabulary-closure digest")
    if errors:
        return errors

    head = run(
        ["git", "rev-parse", "HEAD"],
        cwd=rulespec_dir,
        capture=True,
    ).stdout.strip()
    if head != revision:
        errors.append(f"Rulespec HEAD {head!r} does not match pinned revision {revision!r}")

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
        if args.require_closure_pin:
            errors.extend(validate_closure_pin(rulespec_dir))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if args.run_rulespec_gate:
        result = run(["make", "test"], cwd=rulespec_dir)
        if result.returncode:
            print("FAIL: Rulespec make test failed", file=sys.stderr)
            return result.returncode

    qualifier = "immutable closure pin" if args.require_closure_pin else "working tree"
    print(f"RefSpec/Rulespec gate: {len(external_paths())} upstream inputs found; {qualifier} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

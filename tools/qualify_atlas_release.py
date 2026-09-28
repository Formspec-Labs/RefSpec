"""Qualify one explicitly pinned, completed Atlas candidate in serial processes.

This does not build the RDF distribution, publish it, or alter its acceptance
receipt. It retains independent conformance, publisher fidelity and view checks
as separate results, linked by the exact input manifest digests.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from refspec.atlas.parquet_artifact import file_sha256, normalize_sha256_prefix

try:
    from tools.run_atlas_phase import GIB, run_phase
except ImportError:
    from run_atlas_phase import GIB, run_phase

ROOT = Path(__file__).resolve().parents[1]


def require_pin(path: Path, digest: str) -> str:
    expected = normalize_sha256_prefix(digest)
    if path.is_symlink() or not path.is_file() or file_sha256(path) != expected:
        raise ValueError(f"trusted input digest differs or file is unsafe: {path}")
    return expected


def _source_commit(root: Path) -> str:
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def _source_dirty(root: Path) -> bool:
    return bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip())


def _tree_digests(root: Path, *, exclude_fixtures: bool = False) -> dict[str, str]:
    """Pin code and runtime data, excluding documentation and generated fixtures."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"executable input tree is missing or unsafe: {root}")
    result = {}
    excluded = {"__pycache__"} | ({"valid", "invalid"} if exclude_fixtures else set())
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in excluded)
        for name in names:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f"executable input directory is a symlink: {Path(directory) / name}")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix in {".pyc", ".pyo", ".md", ".rst"}:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"executable input is unsafe: {path}")
            result[path.relative_to(root).as_posix()] = file_sha256(path)
    return result


def executable_inputs(root: Path, binding: Path | None = None) -> dict[str, str]:
    """Inventory membership as well as bytes so additions and deletions fail closed."""
    result = {}
    for relative in ("src/refspec", "tools", "bindings/atlas/3.1"):
        result.update(
            {
                f"{relative}/{key}": digest
                for key, digest in _tree_digests(
                    root / relative, exclude_fixtures=relative == "bindings/atlas/3.1"
                ).items()
            }
        )
    for relative in ("pyproject.toml", "uv.lock", ".python-version"):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"executable metadata is missing or unsafe: {path}")
        result[relative] = file_sha256(path)
    if binding is not None:
        result.update(
            {
                f"standalone-binding/{key}": digest
                for key, digest in _tree_digests(binding, exclude_fixtures=True).items()
            }
        )
    return result


def require_executable_inputs(root: Path, binding: Path | None, commit: str, expected: dict[str, str]) -> None:
    if _source_commit(root) != commit:
        raise ValueError("qualification source HEAD changed")
    actual = executable_inputs(root, binding)
    changed = sorted(key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key))
    if changed:
        raise ValueError(f"qualification executable inputs changed: {changed}")


def require_complete_fidelity(path: Path, manifest_digest: str) -> dict[str, Any]:
    receipt = json.loads(path.read_text())
    error = "publisher fidelity is failed, scoped, incomplete, or bound to another manifest"
    if not isinstance(receipt, dict):
        raise ValueError(error)
    coverage, scope, expectations = (receipt.get(key) for key in ("coverage", "scope", "expectations"))
    comparisons = receipt.get("comparisons")
    if (
        not all(isinstance(value, dict) for value in (coverage, scope, expectations))
        or not isinstance(comparisons, list)
        or not all(isinstance(row, dict) for row in comparisons)
    ):
        raise ValueError(error)
    units = coverage.get("constructionUnits")
    count = coverage.get("constructionUnitCount")
    if (
        not isinstance(units, list)
        or not all(isinstance(row, dict) and isinstance(row.get("key"), str) and row["key"] for row in units)
        or type(count) is not int
        or count < 1
    ):
        raise ValueError(error)
    agency_rows = [row for row in comparisons if row.get("kind") == "agency"]
    if len(agency_rows) != 1:
        raise ValueError(error)
    agency = agency_rows[0]
    claim = agency.get("claimScope")
    independent = claim.get("independentAgencyComparison") if isinstance(claim, dict) else None
    agency_key = "agency-registry-2026-09-26"
    if (
        not isinstance(independent, dict)
        or agency.get("name") != agency_key
        or agency.get("publisherReader") != "independent-agency"
        or agency.get("releaseKeys") != [agency_key]
        or agency.get("publisherLoaded") is not True
        or agency.get("atlasLoaded") is not True
        or agency.get("fidelityStatus") != "exact"
        or claim.get("status") != "exact"
        or independent.get("status") != "passed"
        or independent.get("failures") != []
        or agency_key not in {row["key"] for row in units}
        or receipt.get("passed") is not True
        or receipt.get("manifestDigest") != manifest_digest
        or scope.get("complete") is not True
        or scope.get("scopedOutUnits") != []
        or scope.get("scopedOutComparisons") != []
        or coverage.get("uncoveredUnits") != []
        or type(coverage.get("exactUnitCount")) is not int
        or coverage.get("exactUnitCount") != count
        or len(units) != count
        or len({row["key"] for row in units}) != len(units)
        or any(row.get("status") != "exact" for row in units)
        or any(
            expectations.get(key) is not True
            for key in ("requireCompleteCoverage", "requireInputPins", "requirePackPins")
        )
    ):
        raise ValueError(error)
    return receipt


def qualify(args, *, phase_runner=run_phase) -> dict[str, Any]:
    report_root = args.report_root.resolve()
    distribution, full = args.distribution.resolve(), args.full_view.resolve()
    compact = args.compact_view.resolve()
    agency_view = args.agency_view.resolve() if args.agency_view else report_root / "agency-view"
    for closed in (distribution, full, agency_view):
        if compact == closed or compact.is_relative_to(closed) or closed.is_relative_to(compact):
            raise ValueError("compact output must not overlap an input artifact")
    for closed in (distribution, full, compact, *([agency_view] if args.agency_view else [])):
        if report_root == closed or report_root.is_relative_to(closed):
            raise ValueError("qualification receipts must be outside closed artifacts")
    report_root.mkdir(parents=True, exist_ok=False)
    pins: dict[Path, str] = {}
    result: dict[str, Any] = {
        "type": "AtlasReleaseQualification",
        "status": "incomplete",
        "validationMode": "audit",
        "phases": [],
        "inputPins": {},
    }
    summary_path = report_root / "qualification.json"
    # One budget for every phase, so the sum of per-phase guards cannot outrun
    # a caller's own timeout and skip this receipt.
    deadline = time.monotonic() + args.total_timeout_seconds
    result["totalTimeoutSeconds"] = args.total_timeout_seconds
    env = dict(os.environ, REFSPEC_ATLAS_VALIDATION_MODE="audit")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    def pin(path, digest):
        pins[path] = require_pin(path, digest)
        result["inputPins"][str(path)] = pins[path]
        return pins[path]

    def phase(name, command):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{name}: the {args.total_timeout_seconds:g} s qualification budget is spent")
        require_executable_inputs(ROOT, binding, result["sourceCommit"], result["executableInputDigests"])
        for path, digest in pins.items():
            require_pin(path, digest)
        record = phase_runner(
            command,
            name=name,
            report=report_root / f"{name}.json",
            rss_limit=int(args.memory_gib * GIB),
            footprint_limit=int(args.memory_gib * GIB),
            timeout_seconds=min(args.phase_timeout_seconds, remaining),
            cgroup_parent=args.cgroup_parent,
            swap_limit=int(args.swap_gib * GIB),
            disk_root=distribution.parent,
            env=env,
        )
        result["phases"].append(record)
        require_executable_inputs(ROOT, binding, result["sourceCommit"], result["executableInputDigests"])
        if record["status"] != "passed":
            raise RuntimeError(f"{name}: {record['status']}; see {record.get('log')}")
        for path, digest in pins.items():
            require_pin(path, digest)

    try:
        result["sourceCommit"] = _source_commit(ROOT)
        result["executableInputDigests"] = executable_inputs(ROOT)
        result["sourceDirty"] = _source_dirty(ROOT)
        result["toolDigests"] = {
            key: digest for key, digest in result["executableInputDigests"].items() if key.startswith("tools/")
        }
        result["pythonVersion"] = sys.version
        result["versions"] = {
            name: importlib.metadata.version(name) for name in ("refspec", "rdflib", "pyarrow", "pyshacl")
        }
        distribution_pin = pin(distribution / "atlas-manifest.json", args.distribution_manifest_sha256)
        full_pin = pin(full / "view-manifest.json", args.full_view_manifest_sha256)
        full_manifest = json.loads((full / "view-manifest.json").read_text())
        if full_manifest.get("input", {}).get("manifestSha256") != distribution_pin:
            raise ValueError("full view names a different Atlas distribution")
        evidence = args.agency_audit_evidence_manifest.resolve()
        review = args.agency_review_receipt.resolve()
        evidence_pin = pin(evidence, args.agency_audit_evidence_sha256)
        review_pin = pin(review, args.agency_review_receipt_sha256)

        # The copied binding remains a standalone program with its own pinned
        # dependencies; no imports from this checkout answer its verdict.
        binding = report_root / "standalone-binding"
        shutil.copytree(
            ROOT / "bindings/atlas/3.1", binding, ignore=shutil.ignore_patterns("__pycache__", "valid", "invalid")
        )
        # Authenticate the copy against the original snapshot before extending
        # the same before/after-phase check to the standalone files.
        copied = _tree_digests(binding, exclude_fixtures=True)
        original = {
            key.removeprefix("bindings/atlas/3.1/"): digest
            for key, digest in result["executableInputDigests"].items()
            if key.startswith("bindings/atlas/3.1/")
        }
        if copied != original:
            raise ValueError("standalone binding copy differs from pinned executable inputs")
        result["executableInputDigests"].update({f"standalone-binding/{key}": digest for key, digest in copied.items()})
        inventory_code = """import importlib.util, sys
from pathlib import Path
from refspec.atlas.parquet_view import verify_atlas_parquet_source_metadata
root, digest, binding = sys.argv[1:]
sys.path.insert(0, str(Path(binding) / "tools"))
import validate as authority
verified = verify_atlas_parquet_source_metadata(Path(root), digest)
total = 0
for pack in verified.manifest["packs"]:
    content, transport = pack["content"]["byteLength"], pack["transport"]["byteLength"]
    if content > authority.NQUADS_MAX_CONTENT_BYTES or transport > authority.NQUADS_MAX_TRANSPORT_BYTES:
        raise ValueError("pack byte limit exceeded: " + pack["path"])
    total += content
if total > authority.NQUADS_DATASET_MAX_CONTENT_BYTES:
    raise ValueError("distribution content byte limit exceeded")
print("authenticated transport inventory; full audit checks decompressed bytes")
"""
        phase(
            "pack-inventory", [sys.executable, "-c", inventory_code, str(distribution), distribution_pin, str(binding)]
        )
        phase(
            "standalone-audit",
            [
                "uv",
                "run",
                "--no-project",
                "--with-requirements",
                str(binding / "requirements.txt"),
                "python",
                str(binding / "tools/validate.py"),
                "--distribution",
                str(distribution),
            ],
        )
        if args.agency_view is None:
            phase(
                "build-agency-view",
                [sys.executable, str(ROOT / "tools/build_agency_registry_view.py"), "--output", str(agency_view)],
            )
        agency_pin = pin(agency_view / "view-manifest.json", args.agency_view_manifest_sha256)
        phase(
            "verify-agency-view",
            [
                sys.executable,
                str(ROOT / "tools/build_agency_registry_view.py"),
                "--verify",
                str(agency_view),
                "--expected-manifest-sha256",
                agency_pin,
            ],
        )
        fidelity_path = report_root / "source-fidelity.json"
        phase(
            "publisher-fidelity",
            [
                sys.executable,
                str(ROOT / "tools/verify_atlas_source_fidelity.py"),
                "--distribution",
                str(distribution),
                "--source-root",
                str(args.source_root.resolve()),
                "--output",
                str(fidelity_path),
                "--agency-view",
                str(agency_view),
                "--agency-view-manifest-sha256",
                agency_pin,
                "--agency-audit-evidence-manifest",
                str(evidence),
                "--agency-audit-evidence-sha256",
                evidence_pin,
                "--agency-review-receipt",
                str(review),
                "--agency-review-receipt-sha256",
                review_pin,
            ],
        )
        require_complete_fidelity(fidelity_path, distribution_pin)
        result["fidelityReceiptDigest"] = file_sha256(fidelity_path)
        phase(
            "full-view",
            [
                sys.executable,
                "-m",
                "refspec.atlas.parquet_view_cli",
                "--view",
                str(full),
                "--expected-manifest-sha256",
                full_pin,
            ],
        )
        phase(
            "build-compact-view",
            [
                sys.executable,
                "-m",
                "refspec.atlas.parquet_search_view_cli",
                "--full-view",
                str(full),
                "--output",
                str(compact),
                "--expected-manifest-sha256",
                full_pin,
            ],
        )
        compact_pin = pin(compact / "search-view-manifest.json", file_sha256(compact / "search-view-manifest.json"))
        phase(
            "verify-compact-view",
            [
                sys.executable,
                "-m",
                "refspec.atlas.parquet_search_view_cli",
                "--verify-only",
                "--output",
                str(compact),
                "--expected-manifest-sha256",
                compact_pin,
            ],
        )
        result["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - retain failed phase evidence; never report qualification.
        result["error"] = f"{type(error).__name__}: {error}"
    except BaseException as error:  # An interrupt still leaves its receipt, then propagates.
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        result["inputPins"] = {str(path): digest for path, digest in pins.items()}
        summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _interrupted(signum, _frame):
    """Turn SIGTERM or SIGINT into an exception, so the phase and qualification receipts are still written.

    SIGINT is set explicitly: a shell starts a background job with SIGINT
    ignored, and Python then installs no KeyboardInterrupt handler of its own.
    """
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--distribution-manifest-sha256", required=True)
    parser.add_argument("--full-view", type=Path, required=True)
    parser.add_argument("--full-view-manifest-sha256", required=True)
    parser.add_argument("--compact-view", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT / "output/registry-real-data-sources")
    parser.add_argument("--agency-view", type=Path)
    parser.add_argument("--agency-view-manifest-sha256", required=True)
    parser.add_argument("--agency-audit-evidence-manifest", type=Path, required=True)
    parser.add_argument("--agency-audit-evidence-sha256", required=True)
    parser.add_argument("--agency-review-receipt", type=Path, required=True)
    parser.add_argument("--agency-review-receipt-sha256", required=True)
    parser.add_argument("--memory-gib", type=float, default=30)
    parser.add_argument(
        "--phase-timeout-seconds", type=float, default=7200, help="runaway guard, not a measured performance claim"
    )
    parser.add_argument(
        "--total-timeout-seconds",
        type=float,
        default=20700,
        help="budget for all phases together; keep it below any caller's own timeout",
    )
    parser.add_argument("--cgroup-parent", type=Path)
    parser.add_argument("--swap-gib", type=float, default=0)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _interrupted)
    signal.signal(signal.SIGINT, _interrupted)
    result = qualify(args)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

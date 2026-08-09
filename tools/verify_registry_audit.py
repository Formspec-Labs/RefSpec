#!/usr/bin/env python3
"""Verify and summarize a complete RefSpec registry audit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_MANIFEST = (
    REPOSITORY_ROOT / "research" / "evidence" / "registry-real-data-audit-2026-08-03" / "sources.json"
)
TEST_INPUT_ENVIRONMENT = {
    "courtlistenerJurisdictions": "REFSPEC_COURTLISTENER_JURISDICTIONS_PATH",
    "crsProductsPage20260803": "REFSPEC_CRS_PRODUCTS_PATH",
    "crsLegislativeSubjects20260730": "REFSPEC_CRS_LEGISLATIVE_SUBJECTS_PATH",
    "crsLegislativeGeographic20260730": "REFSPEC_CRS_LEGISLATIVE_GEOGRAPHIC_PATH",
    "crsLegislativeOrganizations20260730": "REFSPEC_CRS_LEGISLATIVE_ORGANIZATIONS_PATH",
    "crsPolicyAreas20260730": "REFSPEC_CRS_POLICY_AREAS_PATH",
    "doeOstiThesaurusV12020": "REFSPEC_DOE_OSTI_THESAURUS_PATH",
    "ecfrTitles": "REFSPEC_ECFR_TITLES_PATH",
    "ecfrAgencies": "REFSPEC_ECFR_AGENCIES_PATH",
    "ecfrTitle1Structure20260731": "REFSPEC_ECFR_TITLE_1_STRUCTURE_PATH",
    "ecfrTitle1Part18FullXml20260731": "REFSPEC_ECFR_TITLE_1_PART_18_XML_PATH",
    "federalRegisterDocument202615493": "REFSPEC_FR_DOCUMENT_2026_15493_PATH",
    "federalRegisterDocument9632865": "REFSPEC_FR_DOCUMENT_96_32865_PATH",
    "elsstR6": "REFSPEC_ELSST_R6_PATH",
    "federalRegister2025": "REFSPEC_FR_THESAURUS_2025_PATH",
    "gemet": "REFSPEC_GEMET_PATH",
    "meshDescriptors2026Xml": "REFSPEC_MESH_DESCRIPTORS_PATH",
    "nasaThesaurusSkos": "REFSPEC_NASA_THESAURUS_SKOS_PATH",
    "natureOfSuitOfficialPdf": "REFSPEC_NATURE_OF_SUIT_PDF_PATH",
    "naics2022Xlsx": "REFSPEC_NAICS_2022_XLSX_PATH",
    "pscApril2025Xlsx": "REFSPEC_PSC_APRIL_2025_XLSX_PATH",
    "opmEhriDataStandardsXlsx": "REFSPEC_OPM_EHRI_DATA_STANDARDS_PATH",
    "opmPlumAllDataCsv": "REFSPEC_OPM_PLUM_ALL_DATA_PATH",
    "ombA11OfficialPdf": "REFSPEC_OMB_A11_PDF_PATH",
    "comptoxBisphenolAPage": "REFSPEC_COMPTOX_BPA_PAGE_PATH",
    "fercClassTypes2025Pdf": "REFSPEC_FERC_CLASS_TYPES_2025_PDF_PATH",
    "fercDocketPrefix2025Pdf": "REFSPEC_FERC_DOCKET_PREFIX_2025_PDF_PATH",
    "fercGeneralSearchHelp": "REFSPEC_FERC_GENERAL_SEARCH_HELP_PATH",
    "fercAccessibilityTips": "REFSPEC_FERC_ACCESSIBILITY_TIPS_PATH",
    "federalRegisterTopics": "REFSPEC_FR_TOPICS_PATH",
    "fastTopicalNtZip": "REFSPEC_FAST_TOPICAL_NT_ZIP_PATH",
    "fastChanges20241027": "REFSPEC_FAST_CHANGES_2024_10_27_PATH",
    "fastChanges20241204": "REFSPEC_FAST_CHANGES_2024_12_04_PATH",
    "fastChanges20250501": "REFSPEC_FAST_CHANGES_2025_05_01_PATH",
    "fastChanges20260213": "REFSPEC_FAST_CHANGES_2026_02_13_PATH",
    "federalHierarchyDefaultPage": "REFSPEC_FH_ORGS_DEFAULT_PATH",
    "federalHierarchySubTierPage": "REFSPEC_FH_ORGS_SUB_TIER_PATH",
    "gcmdScienceKeywords244": "REFSPEC_GCMD_SCIENCE_KEYWORDS_PATH",
    "icpsrSubjectXml": "REFSPEC_ICPSR_SUBJECT_XML_PATH",
    "icpsrManagedIndexA": "REFSPEC_ICPSR_INDEX_PAGE_A_PATH",
    "samEntity3mPublic": "REFSPEC_SAM_ENTITY_PUBLIC_PATH",
    "regulatoryNativeDockets": "REFSPEC_REGULATORY_NATIVE_DOCKETS_PATH",
    "regulatoryNativeDocuments": "REFSPEC_REGULATORY_NATIVE_DOCUMENTS_PATH",
    "regulatoryNativeFederalRegister": "REFSPEC_REGULATORY_NATIVE_FEDERAL_REGISTER_PATH",
    "regulatoryNativeUnifiedAgenda": "REFSPEC_REGULATORY_NATIVE_UNIFIED_AGENDA_PATH",
}


class RegistryAuditError(ValueError):
    """The saved audit is incomplete or structurally invalid."""


def registry_modules(repository_root: Path) -> tuple[str, ...]:
    """Return every registry module path in deterministic order."""

    registry = repository_root / "src" / "refspec" / "registry"
    return tuple(
        sorted(
            path.relative_to(registry).as_posix()
            for path in registry.rglob("*.py")
            if path.name != "__init__.py"
        )
    )


def _qualified_module_name(module: str) -> str:
    return "refspec.registry." + module.removesuffix(".py").replace("/", ".")


def load_source_manifest(path: Path, repository_root: Path) -> dict[str, Any]:
    """Load the single source-link manifest and require every current module row."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("format") != "refspec-registry-source-links/v1":
        raise RegistryAuditError(f"{path} is not a registry source-link manifest")
    modules = payload.get("modules")
    if not isinstance(modules, list):
        raise RegistryAuditError(f"{path}.modules must be a list")
    expected = set(registry_modules(repository_root))
    actual = {row.get("module") for row in modules if isinstance(row, Mapping) and isinstance(row.get("module"), str)}
    if actual != expected or len(modules) != len(expected):
        raise RegistryAuditError("source-link manifest must name every registry module exactly once")
    return dict(payload)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _verify_test_input(payload: bytes, descriptor: Mapping[str, Any], label: str) -> None:
    expected_digest = descriptor.get("sha256")
    expected_length = descriptor.get("byteLength")
    if not isinstance(expected_digest, str) or not isinstance(expected_length, int):
        raise RegistryAuditError(f"{label} must declare sha256 and byteLength")
    if len(payload) != expected_length:
        raise RegistryAuditError(f"{label} byte length drift: expected {expected_length}, got {len(payload)}")
    actual_digest = _digest(payload)
    if actual_digest != expected_digest:
        raise RegistryAuditError(f"{label} digest drift: expected {expected_digest}, got {actual_digest}")


def _normalize_test_input(payload: bytes, descriptor: Mapping[str, Any]) -> bytes:
    normalization = descriptor.get("normalization")
    if normalization is None:
        return payload
    if normalization != "stripCompToxSentryTrace":
        raise RegistryAuditError(f"unknown test-input normalization {normalization!r}")
    normalized = re.sub(
        rb'content="[0-9a-f]{32}-[0-9a-f]{16}-1"',
        b'content="TRACE"',
        payload,
    )
    return re.sub(
        rb"sentry-trace_id=[0-9a-f]{32}",
        b"sentry-trace_id=TRACE",
        normalized,
    )


def materialize_test_inputs(
    repository_root: Path,
    source_manifest: Mapping[str, Any],
) -> dict[str, str]:
    """Resolve publisher artifacts from the JSON manifest for existing opt-in tests."""

    resolved: dict[str, str] = {}

    def resolve_path(descriptor: Mapping[str, Any], *, label: str) -> Path:
        relative_path = Path(str(descriptor["localPath"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RegistryAuditError(f"{label} must use a RefSpec-owned relative path")
        local_path = (repository_root / relative_path).resolve()
        try:
            local_path.relative_to(repository_root)
        except ValueError as error:
            raise RegistryAuditError(f"{label} escapes the RefSpec repository") from error
        return local_path

    def materialize_file(descriptor: Mapping[str, Any], *, label: str) -> Path:
        local_path = resolve_path(descriptor, label=label)
        if local_path.is_file():
            payload = _normalize_test_input(local_path.read_bytes(), descriptor)
        else:
            if descriptor.get("acquisition") == "browserExport":
                raise RegistryAuditError(
                    f"{label} requires the documented browser export at {local_path}"
                )
            source_url = descriptor.get("publisherUrl")
            if not isinstance(source_url, str):
                raise RegistryAuditError(f"{label} is absent and has no publisherUrl")
            request = Request(source_url, headers={"User-Agent": "RefSpec real-data audit/1"})
            try:
                with urlopen(request, timeout=120.0) as response:
                    downloaded = response.read()
            except OSError as error:
                raise RegistryAuditError(f"could not download {label}: {error}") from error
            expected_download_digest = descriptor.get("downloadSha256")
            if expected_download_digest is not None and _digest(downloaded) != expected_download_digest:
                raise RegistryAuditError(f"{label} compressed download digest drift")
            try:
                payload = gzip.decompress(downloaded) if descriptor.get("compression") == "gzip" else downloaded
            except gzip.BadGzipFile as error:
                raise RegistryAuditError(f"{label} is not the declared gzip stream") from error
            payload = _normalize_test_input(payload, descriptor)
            _verify_test_input(payload, descriptor, label)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(payload)
        _verify_test_input(payload, descriptor, label)
        return local_path

    for module in source_manifest["modules"]:
        for descriptor in module["testInputs"]:
            name = descriptor["name"]
            if descriptor.get("kind") == "sourceCollection":
                local_path = resolve_path(descriptor, label=f"source collection {name!r}")
                if not local_path.is_dir():
                    raise RegistryAuditError(
                        f"source collection {name!r} is not available at {local_path}"
                    )
                members = descriptor.get("members")
                if not isinstance(members, list) or len(members) != descriptor.get("memberCount"):
                    raise RegistryAuditError(f"source collection {name!r} has invalid members")
                for member in members:
                    materialize_file(
                        member,
                        label=f"source collection {name!r} member {member.get('name')!r}",
                    )
            else:
                local_path = materialize_file(descriptor, label=f"test input {name!r}")
            rendered_path = str(local_path)
            if name in resolved and resolved[name] != rendered_path:
                raise RegistryAuditError(
                    f"source-link manifest gives test input {name!r} conflicting paths"
                )
            resolved[name] = rendered_path
    missing = sorted(set(TEST_INPUT_ENVIRONMENT) - set(resolved))
    if missing:
        raise RegistryAuditError(f"source-link manifest omits required test inputs: {missing}")
    return resolved


def verify_inventory(repository_root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Require the audit to name every current module exactly once."""

    expected = set(registry_modules(repository_root))
    actual = {str(row["module"]) for row in rows}
    if missing := sorted(expected - actual):
        raise RegistryAuditError(f"audit omits registry modules: {missing}")
    if unknown := sorted(actual - expected):
        raise RegistryAuditError(f"audit names unknown registry modules: {unknown}")


def import_audited_modules(repository_root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Import every audited module to catch missing dependencies and import side effects."""

    source_root = str(repository_root / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    for row in rows:
        importlib.import_module(_qualified_module_name(str(row["module"])))


def direct_test_paths(repository_root: Path, rows: Sequence[Mapping[str, Any]]) -> tuple[Path, ...]:
    """Resolve at least one executable test file for every registry module."""

    selected: list[Path] = []
    missing: list[str] = []
    for row in rows:
        module = str(row["module"])
        test_name = module.rsplit("/", 1)[-1].removesuffix(".py")
        relative_paths = {
            "claim_release_exports.py": ("tests/test_registry_claim_exports.py",),
            "infrastructure/pinned_acquisition.py": ("tests/test_elsst_acquisition.py",),
            "infrastructure/rdf_claim_export.py": ("tests/test_registry_claim_exports.py",),
            "managed_releases/federal_register_thesaurus_2025_managed_release.py": (
                "tests/test_federal_register_thesaurus_2025.py",
            ),
        }.get(module, (f"tests/test_{test_name}.py",))
        paths = tuple(repository_root / relative_path for relative_path in relative_paths)
        if not paths or any(not path.is_file() for path in paths):
            missing.append(module)
        else:
            selected.extend(paths)
    if missing:
        raise RegistryAuditError(f"registry modules have no executable test path: {sorted(missing)}")
    return tuple(dict.fromkeys(selected))


def real_data_evidence_failures(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return declared publisher-source blockers from the checked-in manifest."""

    failures: list[str] = []
    for row in rows:
        module = str(row["module"])
        if row["auditRole"] == "support":
            continue
        if row["sourceStatus"] != "publisherBytes":
            blockers = row.get("blockers") or ["publisher-origin source evidence is unavailable"]
            failures.extend(f"{module}: {blocker}" for blocker in blockers)
    return tuple(failures)


def execution_receipt_failures(
    source_manifest: Mapping[str, Any],
    receipts: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate measurements emitted by the current direct-test process."""

    def has_structure_and_sample(execution: Mapping[str, Any]) -> bool:
        return bool(execution.get("shape")) and "sample" in execution

    def has_substantive_counts(execution: Mapping[str, Any]) -> bool:
        counts = execution.get("counts")
        if not isinstance(counts, Mapping):
            return False
        excluded_parts = {"blocker", "blockers", "gap", "gaps"}
        return any(
            isinstance(count, int)
            and count > 0
            and not excluded_parts.intersection(str(name).lower().split("."))
            for name, count in counts.items()
        )

    if receipts.get("format") != "refspec-registry-execution-receipts/v1":
        return ("execution receipt format is missing or unsupported",)
    receipt_rows = receipts.get("modules")
    if not isinstance(receipt_rows, list):
        return ("execution receipts contain no module rows",)
    by_module = {
        row.get("module"): row
        for row in receipt_rows
        if isinstance(row, Mapping) and isinstance(row.get("module"), str)
    }
    failures: list[str] = []
    for source_row in source_manifest["modules"]:
        module = source_row["module"]
        receipt = by_module.get(module)
        executions = receipt.get("executions", []) if isinstance(receipt, Mapping) else []
        role = source_row["auditRole"]
        if not executions:
            failures.append(f"{module}: current test process captured no successful production call")
            continue
        if not any(has_structure_and_sample(execution) for execution in executions):
            failures.append(f"{module}: current execution recorded no output structure and sample")
        if role in {"downstreamProjection", "networkHarness"}:
            covered_by = source_row["coveredBy"]
            missing_coverage = [
                dependency for dependency in covered_by if not by_module.get(dependency, {}).get("executions")
            ]
            if not covered_by or missing_coverage:
                failures.append(f"{module}: declared {role} coverage is incomplete: {missing_coverage}")
        elif role not in {"dataReader", "support"}:
            failures.append(f"{module}: unknown audit role {role!r}")
        if role == "support":
            continue
        needs_parsed_counts = role in {"dataReader", "downstreamProjection"}
        if needs_parsed_counts and not any(has_substantive_counts(execution) for execution in executions):
            failures.append(f"{module}: current execution measured no substantive output collection sizes")
        pinned_digests: set[str] = set()
        for descriptor in source_row["testInputs"]:
            if not isinstance(descriptor, Mapping) or not descriptor.get("receiptRequired", True):
                continue
            if descriptor.get("kind") == "sourceCollection":
                capture_digest = descriptor.get("captureDigest")
                if isinstance(capture_digest, str):
                    pinned_digests.add(capture_digest)
                pinned_digests.update(
                    member["sha256"]
                    for member in descriptor.get("members", ())
                    if isinstance(member, Mapping) and isinstance(member.get("sha256"), str)
                )
            elif isinstance(descriptor.get("sha256"), str):
                pinned_digests.add(descriptor["sha256"])
        if source_row["sourceStatus"] != "publisherBytes":
            continue
        if not pinned_digests:
            failures.append(f"{module}: publisherBytes status has no immutable publisher input pin")
            continue
        observed_digests = {
            digest for execution in executions for digest in execution.get("sourceEvidence", {}).get("digests", ())
        }
        if missing_pins := sorted(pinned_digests - observed_digests):
            failures.append(f"{module}: current execution did not consume pinned real-data inputs {missing_pins}")
        for pinned_digest in sorted(pinned_digests):
            matching_executions = [
                execution
                for execution in executions
                if pinned_digest in execution.get("sourceEvidence", {}).get("digests", ())
            ]
            if not matching_executions:
                continue
            substantive_executions = [
                execution
                for execution in matching_executions
                if has_structure_and_sample(execution)
                and (not needs_parsed_counts or has_substantive_counts(execution))
            ]
            if not substantive_executions:
                requirement = (
                    "substantive parsed counts, output structure, and sample"
                    if needs_parsed_counts
                    else "substantive output structure and sample"
                )
                failures.append(
                    f"{module}: pinned real-data input {pinned_digest} did not produce {requirement} "
                    "in the same execution"
                )
        if not any(
            execution.get("sourceEvidence", {}).get("digests")
            and (
                execution.get("sourceEvidence", {}).get("paths")
                or execution.get("sourceEvidence", {}).get("urls")
                or pinned_digests.intersection(execution.get("sourceEvidence", {}).get("digests", ()))
            )
            for execution in executions
        ):
            failures.append(f"{module}: current execution is not tied to a source digest and location")
    return tuple(failures)


def _test_input_environment(test_inputs: Mapping[str, str] | None) -> dict[str, str]:
    """Translate manifest input names into the opt-in test environment."""

    return {
        TEST_INPUT_ENVIRONMENT[name]: path
        for name, path in ({} if test_inputs is None else test_inputs).items()
        if name in TEST_INPUT_ENVIRONMENT
    }


def run_direct_tests(
    repository_root: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    test_inputs: Mapping[str, str] | None = None,
) -> tuple[dict[str, int | float], dict[str, Any]]:
    """Run each registry module's direct tests with execution receipts."""

    tests = direct_test_paths(repository_root, rows)
    selected = [str(path.relative_to(repository_root)) for path in tests]
    with tempfile.TemporaryDirectory(prefix="refspec-registry-audit-") as temporary_directory:
        report_path = Path(temporary_directory) / "pytest.xml"
        receipt_path = Path(temporary_directory) / "registry-receipts.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "tools.registry_real_data_pytest_plugin",
                f"--registry-receipt-output={receipt_path}",
                f"--junitxml={report_path}",
                *selected,
            ],
            cwd=repository_root,
            check=False,
            env={
                **os.environ,
                **_test_input_environment(test_inputs),
            },
        )
        if not report_path.is_file():
            raise RegistryAuditError("direct registry tests produced no JUnit report")
        if not receipt_path.is_file():
            raise RegistryAuditError("direct registry tests produced no execution receipts")
        root = ElementTree.parse(report_path).getroot()
        receipts = json.loads(receipt_path.read_text(encoding="utf-8"))
    if completed.returncode:
        raise RegistryAuditError(f"direct registry tests failed with exit code {completed.returncode}")
    suites = (root,) if root.tag == "testsuite" else tuple(root.findall("testsuite"))
    if not suites:
        raise RegistryAuditError("direct registry JUnit report contains no test suites")

    def total(attribute: str) -> int:
        return sum(int(suite.attrib.get(attribute, "0")) for suite in suites)

    test_count = total("tests")
    failures = total("failures")
    errors = total("errors")
    skipped = total("skipped")
    return (
        {
            "testFiles": len(tests),
            "tests": test_count,
            "passed": test_count - failures - errors - skipped,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "seconds": round(sum(float(suite.attrib.get("time", "0")) for suite in suites), 3),
        },
        receipts,
    )


def run_full_test_suite(
    repository_root: Path,
    *,
    test_inputs: Mapping[str, str] | None = None,
) -> dict[str, int | float]:
    """Run the complete suite without receipt instrumentation.

    Receipt collection belongs only on the focused registry qualification run.
    Attaching it to the complete suite repeatedly measured and serialized large
    publisher datasets, turning a normal suite into a multi-hour audit.
    """

    with tempfile.TemporaryDirectory(prefix="refspec-full-suite-") as temporary_directory:
        report_path = Path(temporary_directory) / "pytest.xml"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"--junitxml={report_path}",
            ],
            cwd=repository_root,
            check=False,
            env={
                **os.environ,
                **_test_input_environment(test_inputs),
            },
        )
        if not report_path.is_file():
            raise RegistryAuditError("complete repository tests produced no JUnit report")
        root = ElementTree.parse(report_path).getroot()
    if completed.returncode:
        raise RegistryAuditError(f"complete repository tests failed with exit code {completed.returncode}")
    suites = (root,) if root.tag == "testsuite" else tuple(root.findall("testsuite"))
    if not suites:
        raise RegistryAuditError("complete repository JUnit report contains no test suites")

    def total(attribute: str) -> int:
        return sum(int(suite.attrib.get(attribute, "0")) for suite in suites)

    test_count = total("tests")
    failures = total("failures")
    errors = total("errors")
    skipped = total("skipped")
    return {
        "testFiles": len(tuple((repository_root / "tests").glob("test_*.py"))),
        "tests": test_count,
        "passed": test_count - failures - errors - skipped,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "seconds": round(sum(float(suite.attrib.get("time", "0")) for suite in suites), 3),
    }


def audit_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    real_data_failures: Sequence[str] = (),
    gate_evaluated: bool = True,
    direct_test_result: Mapping[str, int | float] | None = None,
    full_suite_result: Mapping[str, int | float] | None = None,
    execution_receipts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic summary while retaining every source-specific row."""

    classifications = Counter(str(row["classification"]) for row in rows)
    source_statuses = Counter(str(row["sourceStatus"]) for row in rows)
    return {
        "format": "refspec-registry-audit-summary/v1",
        "moduleCount": len(rows),
        "execution": dict(direct_test_result) if direct_test_result is not None else None,
        "fullSuiteExecution": dict(full_suite_result) if full_suite_result is not None else None,
        "executionReceipts": dict(execution_receipts) if execution_receipts is not None else None,
        # Never report "passed" for a gate this run did not evaluate; an inventory-only
        # run says so explicitly rather than implying the evidence was checked.
        "realDataGate": {
            "status": ("failed" if real_data_failures else "passed") if gate_evaluated else "notEvaluated",
            "failures": list(real_data_failures),
        },
        "classifications": dict(sorted(classifications.items())),
        "sourceStatuses": dict(sorted(source_statuses.items())),
        "modules": list(rows),
    }


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--run-tests", action="store_true", help="run every available direct module test")
    parser.add_argument(
        "--run-all-tests",
        action="store_true",
        help="qualify registry sources once, then run the complete suite without receipt instrumentation",
    )
    parser.add_argument(
        "--require-real-data",
        action="store_true",
        help="reject constructed or synthetic evidence and require measured output",
    )
    parser.add_argument("--output", type=Path, help="optional path for the consolidated JSON summary")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        repository_root = args.repository_root.resolve(strict=True)
        source_manifest = load_source_manifest(args.source_manifest, repository_root)
        rows = tuple(source_manifest["modules"])
        verify_inventory(repository_root, rows)
        import_audited_modules(repository_root, rows)
        direct_test_paths(repository_root, rows)
        direct_test_result = None
        full_suite_result = None
        execution_receipts = None
        if args.run_tests or args.run_all_tests or args.require_real_data:
            test_inputs = materialize_test_inputs(repository_root, source_manifest)
            direct_test_result, execution_receipts = run_direct_tests(
                repository_root,
                rows,
                test_inputs=test_inputs,
            )
        evidence_failures = ()
        if args.require_real_data:
            evidence_failures = (
                *real_data_evidence_failures(rows),
                *execution_receipt_failures(source_manifest, execution_receipts or {}),
            )
        def render_summary() -> str:
            return (
                json.dumps(
                    audit_summary(
                        rows,
                        real_data_failures=evidence_failures,
                        gate_evaluated=args.require_real_data,
                        direct_test_result=direct_test_result,
                        full_suite_result=full_suite_result,
                        execution_receipts=execution_receipts,
                    ),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )

        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render_summary(), encoding="utf-8")
        if evidence_failures:
            details = "\n  - ".join(evidence_failures)
            raise RegistryAuditError(f"real-data gate failed:\n  - {details}")
        if args.run_all_tests:
            full_suite_result = run_full_test_suite(repository_root, test_inputs=test_inputs)
            if args.output is not None:
                args.output.write_text(render_summary(), encoding="utf-8")
        if args.output is None:
            print(render_summary(), end="")
        return 0
    except (OSError, json.JSONDecodeError, RegistryAuditError) as error:
        print(f"registry audit error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

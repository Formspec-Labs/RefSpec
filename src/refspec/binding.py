"""Validate REF JSON Binding 1.0 records and conformance fixtures."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

# The canonical-JSON primitives and CORE_FACETS moved to ``refspec.release_model``
# so the atlas build path can reach them without importing this module. Every
# alias below publishes a name at its historical spelling; most (SAFE_INTEGER,
# the canonical-JSON primitives) this module no longer uses itself, but
# CORE_FACETS is still consumed here too -- the alias keeps a single
# definition rather than a second copy.
from refspec.release_model import CORE_FACETS as CORE_FACETS
from refspec.release_model import SAFE_INTEGER as SAFE_INTEGER
from refspec.release_model import (
    DuplicateKeyError,
    canonical_payload_digest,
    digest_field,
    reject_duplicate_keys,
    reject_nonfinite_constant,
)
from refspec.release_model import canonical_json_bytes as canonical_json_bytes
from refspec.release_model import canonical_payload as canonical_payload
from refspec.release_model import canonical_sha256 as canonical_sha256
from refspec.release_model import validate_canonical_value as validate_canonical_value

REFSPEC_ROOT = Path(__file__).resolve().parents[2]
BINDING_ROOT = REFSPEC_ROOT / "bindings" / "json" / "1.0"
SCHEMA_ROOT = BINDING_ROOT / "schemas"
FIXTURE_ROOT = BINDING_ROOT / "fixtures"
CANONICALIZATION_ALGORITHM = "urn:ref:canonical-json:v1"

TYPE_SCHEMAS = {
    "rkaf:AccessScope": "access-scope.schema.json",
    "urn:ref:type:Capture": "capture.schema.json",
    "urn:ref:type:RightsAssessment": "rights-assessment.schema.json",
    "urn:ref:type:RunReceipt": "run-receipt.schema.json",
    "urn:ref:type:RegistryImportSnapshot": "registry-import-snapshot.schema.json",
    "urn:ref:type:PublicationReleaseManifest": "publication-release-manifest.schema.json",
    "urn:ref:type:ReleaseGraphValidationReceipt": "release-graph-validation-receipt.schema.json",
    "urn:ref:type:ConceptProposal": "concept-proposal.schema.json",
    "urn:ref:type:EnrichmentProfile": "enrichment-profile.schema.json",
    "urn:ref:type:OutputProfile": "output-profile.schema.json",
    "urn:ref:type:RegistryImportCoverageReport": "registry-import-coverage-report.schema.json",
    "urn:ref:type:IndexedVocabularyExpression": "indexed-vocabulary-expression.schema.json",
    "urn:ref:type:RegistryReconciliationReport": "registry-reconciliation-report.schema.json",
    "urn:ref:type:RegistryDeploymentDecision": "registry-deployment-decision.schema.json",
    "urn:ref:type:SealedGoldManifest": "sealed-gold-manifest.schema.json",
    "urn:ref:type:EnrichmentConfiguration": "enrichment-configuration.schema.json",
    "urn:ref:type:EnrichmentEvaluationResult": "enrichment-evaluation-result.schema.json",
    "urn:ref:type:EnrichmentDeploymentDecision": "enrichment-deployment-decision.schema.json",
    "urn:ref:type:SourceIdentifierSet": "source-identifier-set.schema.json",
}

TYPE_REQUIREMENTS = {
    "rkaf:AccessScope": "REF-SEC-008",
    "urn:ref:type:Capture": "REF-CAP-001",
    "urn:ref:type:RightsAssessment": "REF-RIGHTS-004",
    "urn:ref:type:RunReceipt": "REF-PROV-004",
    "urn:ref:type:RegistryImportSnapshot": "REF-VOC-016",
    "urn:ref:type:PublicationReleaseManifest": "REF-BIND-009",
    "urn:ref:type:ReleaseGraphValidationReceipt": "REF-BIND-018",
    "urn:ref:type:ConceptProposal": "REF-ENR-010",
    "urn:ref:type:EnrichmentProfile": "REF-ENR-015",
    "urn:ref:type:OutputProfile": "REF-ENR-016",
    "urn:ref:type:RegistryImportCoverageReport": "REF-VOC-021",
    "urn:ref:type:IndexedVocabularyExpression": "REF-CAND-009",
    "urn:ref:type:RegistryReconciliationReport": "REF-VOC-023",
    "urn:ref:type:RegistryDeploymentDecision": "REF-VOC-017",
    "urn:ref:type:SealedGoldManifest": "REF-EVAL-011",
    "urn:ref:type:EnrichmentConfiguration": "REF-ENR-019",
    "urn:ref:type:EnrichmentEvaluationResult": "REF-EVAL-015",
    "urn:ref:type:EnrichmentDeploymentDecision": "REF-ENR-020",
    "urn:ref:type:SourceIdentifierSet": "REF-VOC-040",
}

# rkaf's closed usage-eligibility lattice (usage-eligibility.cue). Order is
# normative -- it ascends from the lowest ceiling to the highest -- so this
# tuple, not just the set it also defines, is the shared source both the
# OutputProfile builder (vocabulary.py) and the accepted-output gate
# (accepted_output.py) import rather than re-declaring.
USAGE_ELIGIBILITY_ORDER = (
    "rkaf:notEligible",
    "rkaf:searchOnly",
    "rkaf:reviewQueueOnly",
    "rkaf:draftGenerationAllowed",
    "rkaf:localOperationalUse",
    "rkaf:publicationAllowed",
    "rkaf:officialUse",
)
USAGE_ELIGIBILITY_VALUES = frozenset(USAGE_ELIGIBILITY_ORDER)
USAGE_ELIGIBILITY_RANK = {
    value: rank for rank, value in enumerate(USAGE_ELIGIBILITY_ORDER)
}
# access-scope.cue's #AccessScopeKind and #RegulatoryClass closed enums are
# enforced only by the JSON Schema $defs in common.schema.json -- no runtime
# Python check consumes them (unlike usageEligibility, which the
# accepted-output gate ranks), so no matching Python constant is declared
# here; one would be unenforced structure.

COVERAGE_FEATURES = {
    "labels",
    "languages",
    "notation",
    "notes",
    "hierarchy",
    "associativeRelations",
    "mappings",
    "status",
    "replacements",
    "identifiers",
    "membership",
}

MAPPING_COVERAGE_FEATURES = {
    "mappings",
    "identifiers",
    "membership",
}

PARTITION_DIMENSIONS = {
    "conceptIdentity",
    "exactMatchCluster",
    "alias",
    "sourceIdentity",
    "artifactDigest",
    "textDigest",
    "nearDuplicateCluster",
}

PROHIBITED_GOLD_SEEDS = {
    "modelOutput",
    "candidateRank",
    "priorSystemDecision",
    "developerPreference",
}

_RESOLVED_RECONCILIATION_OUTCOMES = {
    "selectedInput",
    "reconciledReleaseAuthorized",
}

EVALUATION_GATE_DIMENSIONS = {
    "stage",
    "source",
    "subtype",
    "facet",
    "role",
    "predicate",
    "privacy",
    "risk",
    "latency",
    "cost",
    "product",
}

REQUIRED_MANIFEST_REQUIREMENTS = {
    "REF-BIND-001",
    "REF-BIND-004",
    "REF-BIND-009",
    "REF-BIND-018",
    "REF-CAP-001",
    "REF-CORE-005",
    "REF-ENR-011",
    "REF-ENR-013",
    "REF-ENR-010",
    "REF-ENR-015",
    "REF-ENR-016",
    "REF-ENR-017",
    "REF-ENR-018",
    "REF-ENR-019",
    "REF-ENR-020",
    "REF-CAND-009",
    "REF-PROV-004",
    "REF-RIGHTS-004",
    "REF-VOC-016",
    "REF-VOC-021",
    "REF-VOC-022",
    "REF-VOC-023",
    "REF-VOC-024",
    "REF-VOC-040",
    "REF-VOC-017",
    "REF-EVAL-011",
    "REF-EVAL-012",
    "REF-EVAL-013",
    "REF-EVAL-014",
    "REF-EVAL-015",
    "REF-EVAL-016",
    *{f"REF-ENR-PROFILE-{number:03d}" for number in range(1, 7)},
    *{f"REF-TEST-{number}" for number in range(150, 174)},
    "REF-TEST-185",
}


@dataclass(frozen=True)
class Diagnostic:
    requirement: str
    message: str

    def render(self) -> str:
        return f"{self.requirement}: {self.message}"


def _embedded_asset_relative_path(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(
            BINDING_ROOT.resolve()
        ).as_posix()
    except ValueError:
        return None


def _read_binding_asset(path: Path) -> bytes:
    if path.is_file():
        return path.read_bytes()
    relative = _embedded_asset_relative_path(path)
    if relative is None:
        raise FileNotFoundError(path)
    from refspec.generated_conformance_assets import (
        load_conformance_asset,
    )

    return load_conformance_asset(relative)


def _binding_asset_exists(path: Path) -> bool:
    if path.is_file():
        return True
    relative = _embedded_asset_relative_path(path)
    if relative is None:
        return False
    from refspec.generated_conformance_assets import (
        conformance_asset_paths,
    )

    return relative in conformance_asset_paths()


def _fixture_paths(kind: str) -> list[Path]:
    checkout_paths = sorted((FIXTURE_ROOT / kind).glob("*.json"))
    if checkout_paths:
        return checkout_paths
    from refspec.generated_conformance_assets import (
        conformance_asset_paths,
    )

    prefix = f"fixtures/{kind}/"
    return [
        BINDING_ROOT / relative
        for relative in conformance_asset_paths(prefix)
        if "/" not in relative.removeprefix(prefix)
    ]


def load_json(path: Path) -> Any:
    return json.loads(
        _read_binding_asset(path).decode("utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite_constant,
    )


def text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_alias_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def load_schemas() -> tuple[dict[str, dict[str, Any]], Registry]:
    schema_paths = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    if schema_paths:
        schemas = {
            path.name: load_json(path)
            for path in schema_paths
        }
    else:
        from refspec.generated_schemas import load_schema_bundle

        schemas = load_schema_bundle()
    registry = Registry()
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )
    return schemas, registry


def json_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


def schema_diagnostics(
    record: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
) -> list[Diagnostic]:
    record_type = record.get("type")
    schema_name = TYPE_SCHEMAS.get(record_type)
    if schema_name is None:
        return [
            Diagnostic(
                "REF-BIND-001",
                f"{record.get('id', '<unknown>')}: unsupported or missing REF type {record_type!r}",
            )
        ]
    validator = Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=FormatChecker(),
    )
    default_requirement = TYPE_REQUIREMENTS[record_type]
    diagnostics: list[Diagnostic] = []
    for error in sorted(validator.iter_errors(record), key=lambda item: list(item.path)):
        path = list(error.absolute_path)
        requirement = default_requirement
        if (
            record_type == "urn:ref:type:SealedGoldManifest"
            and path
            and path[0] == "draftingControl"
        ):
            requirement = "REF-EVAL-013"
        if (
            record_type
            == "urn:ref:type:EnrichmentDeploymentDecision"
            and record.get("selectionState") == "selected"
            and record.get("environment", {}).get("classification")
            == "production"
            and path
            and path[0]
            in {"rulespecAttestationRefs", "localAdoptionRefs"}
        ):
            requirement = "REF-TEST-160"
        diagnostics.append(
            Diagnostic(
                requirement,
                f"{record.get('id', '<unknown>')} {json_path(path)}: {error.message}",
            )
        )
    return diagnostics


def same_reference(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left == right


def references_record(reference: dict[str, Any], record: dict[str, Any]) -> bool:
    if reference.get("id") != record.get("id"):
        return False
    field = digest_field(record)
    if reference.get("digest") != record.get(field):
        return False
    return (
        "version" not in reference
        or reference.get("version") == record.get("version")
    )


def structural_key(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def mapping_coverage_releases(
    output_profile: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    mapping_snapshots = {
        structural_key(row.get("mappingSnapshot"))
        for row in output_profile.get("mappingPermissions", [])
        if row.get("candidateUse") is True
    }
    exact_profile_ref = {
        "id": output_profile.get("id"),
        "version": output_profile.get("version"),
        "digest": output_profile.get("contentDigest"),
    }
    return {
        structural_key(report.get("referenceResourceRelease"))
        for report in records_by_id.values()
        if report.get("type") == "urn:ref:type:RegistryImportCoverageReport"
        and report.get("reportStatus") == "pass"
        and report.get("outputProfile") == exact_profile_ref
        and structural_key(report.get("registryImportSnapshot"))
        in mapping_snapshots
    }


def record_digest_diagnostics(record: dict[str, Any]) -> list[Diagnostic]:
    field = digest_field(record)
    expected = canonical_payload_digest(record)
    if record.get(field) == expected:
        return []
    return [
        Diagnostic(
            "REF-BIND-004",
            f"{record.get('id', '<unknown>')}: {field} is {record.get(field)!r}; expected {expected}",
        )
    ]


def duplicate_id_diagnostics(records: list[dict[str, Any]]) -> list[Diagnostic]:
    seen: set[str] = set()
    diagnostics: list[Diagnostic] = []
    for record in records:
        record_id = record.get("id")
        if record_id in seen:
            diagnostics.append(
                Diagnostic("REF-CORE-005", f"duplicate durable record identifier {record_id}")
            )
        seen.add(record_id)
    return diagnostics


def digest_cycle_diagnostics(records: list[dict[str, Any]]) -> list[Diagnostic]:
    records_by_id = {
        record["id"]: record
        for record in records
        if isinstance(record.get("id"), str)
    }
    graph: dict[str, set[str]] = {record_id: set() for record_id in records_by_id}

    def collect_references(value: Any, owner: str, top_level: bool = False) -> None:
        if isinstance(value, dict):
            if not top_level and "id" in value and "digest" in value:
                target = value.get("id")
                if target in records_by_id:
                    graph[owner].add(target)
            for child in value.values():
                collect_references(child, owner)
        elif isinstance(value, list):
            for child in value:
                collect_references(child, owner)

    for record_id, record in records_by_id.items():
        collect_references(record, record_id, top_level=True)

    visiting: set[str] = set()
    visited: set[str] = set()
    diagnostics: list[Diagnostic] = []

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle_start = path.index(node)
            cycle = [*path[cycle_start:], node]
            diagnostics.append(
                Diagnostic(
                    "REF-BIND-004",
                    f"content-digest references form a cycle: {' -> '.join(cycle)}",
                )
            )
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for target in sorted(graph[node]):
            visit(target, path)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    return diagnostics


def validate_enrichment_profile(record: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    facets = record.get("facets", [])
    facet_ids = [facet.get("iri") for facet in facets]
    if len(facet_ids) != len(set(facet_ids)):
        diagnostics.append(Diagnostic("REF-ENR-015", "facet IRIs must be unique"))
    if (
        record.get("id") == "urn:ref:enrichment-profile:core:v1"
        and (
            set(facet_ids) != CORE_FACETS
            or len(facet_ids) != len(CORE_FACETS)
        )
    ):
        diagnostics.append(
            Diagnostic(
                "REF-ENR-015",
                "the core enrichment profile must contain each of the twelve core facet IRIs exactly once",
            )
        )
    return diagnostics


def permission_prerequisite_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    enrichment_profile_ref = record.get("enrichmentProfile", {})
    enrichment_profile = records_by_id.get(enrichment_profile_ref.get("id"))
    if (
        enrichment_profile is None
        or enrichment_profile.get("type") != "urn:ref:type:EnrichmentProfile"
        or not references_record(enrichment_profile_ref, enrichment_profile)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-ENR-016",
                f"{record['id']} cannot resolve its exact EnrichmentProfile",
            )
        )
        facets: dict[str, dict[str, Any]] = {}
    else:
        facets = {
            facet.get("iri"): facet
            for facet in enrichment_profile.get("facets", [])
        }
    coverage_reports = [
        candidate
        for candidate in records_by_id.values()
        if candidate.get("type")
        == "urn:ref:type:RegistryImportCoverageReport"
    ]

    for kind, collection in (
        ("release", "releasePermissions"),
        ("mapping", "mappingPermissions"),
        ("subjectAdmission", "subjectAdmissionPermissions"),
        ("openLabel", "openLabelPermissions"),
    ):
        selector_keys: set[str] = set()
        for index, row in enumerate(record.get(collection, [])):
            facet = facets.get(row.get("facet"))
            if (
                facet is None
                or row.get("assignmentRole")
                not in facet.get("compatibleAssignmentPredicates", [])
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-TEST-152",
                        f"{record['id']} {collection}[{index}] uses an unknown facet or incompatible assignment role",
                    )
                )
            if row.get("acceptedOutputUse") and not row.get("candidateUse"):
                diagnostics.append(
                    Diagnostic(
                        "REF-TEST-151",
                        f"{record['id']} {collection}[{index}] grants accepted output without candidate use",
                    )
                )
            if kind in {"release", "mapping"} and row.get("candidateUse"):
                snapshot_field = (
                    "registryImportSnapshot"
                    if kind == "release"
                    else "mappingSnapshot"
                )
                passing_coverage = [
                    report
                    for report in coverage_reports
                    if report.get("reportStatus") == "pass"
                    and report.get("outputProfile")
                    == {
                        "id": record.get("id"),
                        "version": record.get("version"),
                        "digest": record.get("contentDigest"),
                    }
                    and report.get("registryImportSnapshot")
                    == row.get(snapshot_field)
                    and (
                        kind == "mapping"
                        or report.get("referenceResourceRelease")
                        == row.get("referenceResourceRelease")
                    )
                ]
                if not passing_coverage:
                    diagnostics.append(
                        Diagnostic(
                            "REF-VOC-022",
                            f"{record['id']} {collection}[{index}] lacks a passing coverage report for its exact import snapshot and release when selected by the row",
                        )
                    )
            selector = {
                field: row.get(field)
                for field in permission_row_fields(kind)
            }
            selector_key = json.dumps(
                selector,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if selector_key in selector_keys:
                diagnostics.append(
                    Diagnostic(
                        "REF-ENR-017",
                        f"{record['id']} {collection} repeats a selector tuple with different use flags",
                    )
                )
            selector_keys.add(selector_key)
    return diagnostics


def permission_row_fields(kind: str) -> tuple[str, ...]:
    if kind == "release":
        return (
            "facet",
            "assignmentRole",
            "referenceResourceRelease",
            "registryImportSnapshot",
        )
    if kind == "mapping":
        return (
            "facet",
            "assignmentRole",
            "mappingSnapshot",
            "sourceRelease",
            "targetRelease",
            "relation",
            "direction",
        )
    if kind == "subjectAdmission":
        return (
            "facet",
            "assignmentRole",
            "subjectEmissionPolicy",
            "intendedProductUse",
        )
    if kind == "openLabel":
        return (
            "facet",
            "assignmentRole",
            "mode",
            "defaultLanguage",
        )
    raise ValueError(f"unknown permission kind {kind!r}")


def run_permission_check(
    check: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    profile = records_by_id.get(check.get("profile"))
    if profile is None or profile.get("type") != "urn:ref:type:OutputProfile":
        return [Diagnostic("REF-TEST-150", f"permission check cannot resolve {check.get('profile')}")]

    kind = check.get("kind")
    collection = {
        "release": "releasePermissions",
        "mapping": "mappingPermissions",
        "openLabel": "openLabelPermissions",
    }.get(kind)
    if collection is None:
        return [Diagnostic("REF-TEST-150", f"unknown permission-check kind {kind!r}")]

    request = check.get("tuple", {})
    enrichment_profile = records_by_id.get(profile.get("enrichmentProfile", {}).get("id"))
    if enrichment_profile is not None:
        facets = {
            facet.get("iri"): facet for facet in enrichment_profile.get("facets", [])
        }
        facet = facets.get(request.get("facet"))
        route = check.get("resourceRoute")
        if (
            facet is None
            or request.get("assignmentRole")
            not in facet.get("compatibleAssignmentPredicates", [])
            or (
                route is not None
                and route not in facet.get("compatibleResourceRoutes", [])
            )
        ):
            if check.get("claimedAuthorized") is True:
                return [
                    Diagnostic(
                        "REF-TEST-152",
                        f"permission claim {check.get('id', '<unnamed>')} uses an unknown or incompatible facet, role, or route",
                    )
                ]
            return []
    fields = permission_row_fields(kind)
    matching_rows = []
    for row in profile.get(collection, []):
        if all(row.get(field) == request.get(field) for field in fields):
            matching_rows.append(row)

    use = check.get("use")
    authorized = False
    if len(matching_rows) == 1:
        row = matching_rows[0]
        if use == "candidate":
            authorized = row.get("candidateUse") is True
        elif use == "acceptedOutput":
            authorized = (
                row.get("candidateUse") is True
                and row.get("acceptedOutputUse") is True
            )

    claimed = check.get("claimedAuthorized")
    if claimed == authorized:
        return []
    requirement = "REF-TEST-151" if use == "acceptedOutput" and matching_rows and not authorized else "REF-TEST-150"
    return [
        Diagnostic(
            requirement,
            f"permission claim {check.get('id', '<unnamed>')} was {claimed}; exact-row result is {authorized}",
        )
    ]


def coverage_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    output_profile_ref = record.get("outputProfile", {})
    output_profile = records_by_id.get(output_profile_ref.get("id"))
    if (
        output_profile is None
        or output_profile.get("type") != "urn:ref:type:OutputProfile"
        or not references_record(output_profile_ref, output_profile)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-021",
                "coverage report cannot resolve its exact OutputProfile",
            )
        )
        required_features: set[str] = set()
    else:
        matching_release_permissions = [
            row
            for row in output_profile.get("releasePermissions", [])
            if row.get("candidateUse") is True
            and row.get("referenceResourceRelease")
            == record.get("referenceResourceRelease")
            and row.get("registryImportSnapshot")
            == record.get("registryImportSnapshot")
        ]
        matching_mapping_permissions = [
            row
            for row in output_profile.get("mappingPermissions", [])
            if row.get("candidateUse") is True
            and row.get("mappingSnapshot")
            == record.get("registryImportSnapshot")
        ]
        required_features = {
            feature
            for permission in matching_release_permissions
            for feature in permission.get("requiredImportFeatures", [])
        }
        if matching_mapping_permissions:
            required_features.update(MAPPING_COVERAGE_FEATURES)
        if not matching_release_permissions and not matching_mapping_permissions:
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-021",
                    "coverage report does not match a candidate-enabled release or mapping permission",
                )
            )
    rows = record.get("features", [])
    names = [row.get("feature") for row in rows]
    if set(names) != COVERAGE_FEATURES or len(names) != len(COVERAGE_FEATURES):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-021",
                "coverage must contain each of the eleven required feature rows exactly once",
            )
        )
    for row in rows:
        name = row.get("feature", "<unknown>")
        exclusions = row.get("exclusions", [])
        failures = row.get("failures", [])
        excluded_count = sum(item.get("count", 0) for item in exclusions)
        failed_count = sum(item.get("count", 0) for item in failures)
        parse_excluded = sum(
            item.get("count", 0) for item in exclusions if item.get("stage") == "parsing"
        )
        index_excluded = sum(
            item.get("count", 0) for item in exclusions if item.get("stage") == "indexing"
        )
        parse_failed = sum(
            item.get("count", 0) for item in failures if item.get("stage") == "parsing"
        )
        index_failed = sum(
            item.get("count", 0) for item in failures if item.get("stage") == "indexing"
        )
        if row.get("excludedCount") != excluded_count:
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: excludedCount does not match itemized exclusions")
            )
        if row.get("failedCount") != failed_count:
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: failedCount does not match itemized failures")
            )
        if row.get("sourceObservedCount") != row.get("parsedCount", 0) + parse_excluded + parse_failed:
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: source-to-parsed counts are not fully accounted")
            )
        if row.get("parsedCount") != row.get("indexedCount", 0) + index_excluded + index_failed:
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: parsed-to-indexed counts are not fully accounted")
            )
        parse_differs = (
            row.get("sourceObservedCount") != row.get("parsedCount")
            or row.get("sourceObservedDigest") != row.get("parsedDigest")
        )
        index_differs = (
            row.get("parsedCount") != row.get("indexedCount")
            or row.get("parsedDigest") != row.get("indexedDigest")
        )
        if parse_differs and not row.get("parseDifferenceExplanation"):
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: source-to-parsed difference is unexplained")
            )
        if index_differs and not row.get("indexDifferenceExplanation"):
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: parsed-to-indexed difference is unexplained")
            )
        if record.get("reportStatus") == "pass" and failed_count:
            diagnostics.append(
                Diagnostic("REF-VOC-022", f"{name}: a passing coverage report contains failures")
            )
        if row.get("requiredForCandidateOrOutput") and failed_count:
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-022",
                    f"{name}: a candidate/output-required feature cannot contain failed items",
                )
            )
        if (
            row.get("requiredForCandidateOrOutput")
            and row.get("sourceObservedCount", 0) > 0
            and row.get("indexedCount") == 0
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-022",
                    f"{name}: a candidate/output-required source feature cannot be fully excluded",
                )
            )
        if row.get("requiredForCandidateOrOutput") is not (
            name in required_features
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-022",
                    f"{name}: requiredForCandidateOrOutput disagrees with the exact OutputProfile permission rows",
                )
            )
    return diagnostics


def indexed_expression_diagnostics(record: dict[str, Any]) -> list[Diagnostic]:
    if record.get("indexedTextDigest") == text_digest(record.get("indexedText", "")):
        return []
    return [
        Diagnostic(
            "REF-CAND-009",
            f"{record.get('id')}: indexedTextDigest does not match the UTF-8 indexed text",
        )
    ]


def reconciliation_diagnostics(record: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    input_ids = [item.get("id") for item in record.get("inputs", [])]
    if len(input_ids) != len(set(input_ids)):
        diagnostics.append(
            Diagnostic("REF-VOC-023", "reconciliation input identifiers must be unique")
        )
    exact_input_ids = set(input_ids)
    differences = record.get("differences", [])
    difference_ids = [item.get("id") for item in differences]
    if len(difference_ids) != len(set(difference_ids)):
        diagnostics.append(Diagnostic("REF-VOC-023", "difference identifiers must be unique"))
    for difference in differences:
        input_refs = set(difference.get("inputRefs", []))
        if not input_refs.issubset(exact_input_ids):
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-023",
                    f"{difference.get('id')}: inputRefs must identify exact reconciliation inputs",
                )
            )
    unresolved = {
        item.get("id") for item in differences if item.get("resolution") == "unresolved"
    }
    declared_unresolved = set(record.get("unresolvedItems", []))
    if unresolved != declared_unresolved:
        diagnostics.append(
            Diagnostic(
                "REF-VOC-023",
                "unresolvedItems must exactly name differences whose resolution is unresolved",
            )
        )
    outcome = record.get("outcome")
    input_releases = [
        item.get("referenceResourceRelease") for item in record.get("inputs", [])
    ]
    if outcome == "selectedInput":
        if not any(
            same_reference(record.get("selectedInputRelease", {}), release or {})
            for release in input_releases
        ):
            diagnostics.append(
                Diagnostic("REF-VOC-023", "selectedInputRelease must be one exact input release")
            )
    elif outcome == "reconciledReleaseAuthorized":
        reconciled = record.get("reconciledRelease", {})
        if any(same_reference(reconciled, release or {}) for release in input_releases):
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-023",
                    "a reconciled release must have an identity distinct from every input release",
                )
            )
    elif outcome == "unresolved" and record.get("synthesizedUnionAuthorized"):
        diagnostics.append(
            Diagnostic("REF-VOC-024", "an unresolved report cannot authorize a synthesized union")
        )
    if (
        outcome in _RESOLVED_RECONCILIATION_OUTCOMES
        and (
            not record.get("rulespecAuthorityRefs")
            or not record.get("attestationRefs")
            or not record.get("localAdoptionRefs")
        )
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-023",
                "resolved reconciliation requires authority, attestation, "
                "and local-adoption references for release-gate evaluation",
            )
        )
    return diagnostics


def registry_deployment_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    import_ref = record.get("registryImportSnapshot", {})
    import_snapshot = records_by_id.get(import_ref.get("id"))
    if (
        import_snapshot is None
        or import_snapshot.get("type")
        != "urn:ref:type:RegistryImportSnapshot"
        or not references_record(import_ref, import_snapshot)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-017",
                "registry deployment cannot resolve its exact import snapshot",
            )
        )
    elif (
        import_snapshot.get("rightsAssessment")
        != record.get("rightsAssessment")
        or import_snapshot.get("adoptedPolicyRefs")
        != record.get("adoptedPolicyRefs")
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-017",
                "registry deployment rights and adopted policies differ "
                "from its exact import snapshot",
            )
        )

    coverage_ref = record.get("coverageReport", {})
    coverage = records_by_id.get(coverage_ref.get("id"))
    output_ref = record.get("outputProfile", {})
    output = records_by_id.get(output_ref.get("id"))
    if (
        coverage is None
        or coverage.get("type")
        != "urn:ref:type:RegistryImportCoverageReport"
        or not references_record(coverage_ref, coverage)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-017",
                "registry deployment cannot resolve its exact coverage report",
            )
        )
    if (
        output is None
        or output.get("type") != "urn:ref:type:OutputProfile"
        or not references_record(output_ref, output)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-017",
                "registry deployment cannot resolve its exact OutputProfile",
            )
        )
    if coverage is not None and (
        coverage.get("registryImportSnapshot")
        != record.get("registryImportSnapshot")
        or coverage.get("referenceResourceRelease")
        != record.get("referenceResourceRelease")
        or coverage.get("outputProfile") != output_ref
    ):
        diagnostics.append(
            Diagnostic(
                "REF-VOC-017",
                "registry deployment pins differ from its coverage report",
            )
        )

    reconciliation_ref = record.get("reconciliationReport")
    reconciliation = None
    if reconciliation_ref is not None:
        reconciliation = records_by_id.get(reconciliation_ref.get("id"))
        if (
            reconciliation is None
            or reconciliation.get("type")
            != "urn:ref:type:RegistryReconciliationReport"
            or not references_record(reconciliation_ref, reconciliation)
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-017",
                    "registry deployment cannot resolve its exact reconciliation report",
                )
            )

    if record.get("selectionState") == "selected":
        if coverage is None or coverage.get("reportStatus") != "pass":
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-017",
                    "selected registry deployment requires passing import coverage",
                )
            )
        if reconciliation is not None:
            outcome = reconciliation.get("outcome")
            if outcome == "unresolved":
                diagnostics.append(
                    Diagnostic(
                        "REF-VOC-017",
                        "selected registry deployment cannot use unresolved reconciliation",
                    )
                )
            authorized_release = (
                reconciliation.get("selectedInputRelease")
                if outcome == "selectedInput"
                else reconciliation.get("reconciledRelease")
                if outcome == "reconciledReleaseAuthorized"
                else None
            )
            if authorized_release != record.get("referenceResourceRelease"):
                diagnostics.append(
                    Diagnostic(
                        "REF-VOC-017",
                        "selected registry release is not authorized by reconciliation",
                    )
                )
        if (
            record.get("environment", {}).get("classification")
            == "production"
            and (
                not record.get("rulespecAttestationRefs")
                or not record.get("localAdoptionRefs")
            )
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-VOC-017",
                    "selected production registry requires attestation and adoption references",
                )
            )
    return diagnostics


def sealed_gold_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    drafting = record.get("draftingControl", {})
    if (
        drafting.get("blindToEvaluatedOutput") is not True
        or set(drafting.get("prohibitedSeedSources", [])) != PROHIBITED_GOLD_SEEDS
    ):
        diagnostics.append(
            Diagnostic(
                "REF-EVAL-013",
                "gold drafting must be blind and prohibit all four output-derived seed sources",
            )
        )

    universe = record.get("vocabularyUniverse", {})
    universe_release_keys = {
        structural_key(value)
        for value in universe.get("referenceResourceReleases", [])
    }
    output_profile_ref = universe.get("outputProfile", {})
    output_profile = records_by_id.get(output_profile_ref.get("id"))
    if (
        output_profile is None
        or output_profile.get("type") != "urn:ref:type:OutputProfile"
        or not references_record(output_profile_ref, output_profile)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-EVAL-011",
                "sealed gold cannot resolve its exact OutputProfile",
            )
        )
    else:
        expected_releases = {
            structural_key(row[field])
            for row, fields in (
                *(
                    (row, ("referenceResourceRelease",))
                    for row in output_profile.get("releasePermissions", [])
                ),
                *(
                    (row, ("sourceRelease", "targetRelease"))
                    for row in output_profile.get("mappingPermissions", [])
                ),
            )
            for field in fields
        }
        expected_imports = {
            structural_key(row["registryImportSnapshot"])
            for row in output_profile.get("releasePermissions", [])
        }
        expected_mapping_snapshots = {
            structural_key(row["mappingSnapshot"])
            for row in output_profile.get("mappingPermissions", [])
        }
        expected_mapping_releases = mapping_coverage_releases(
            output_profile,
            records_by_id,
        )
        actual_releases = {
            structural_key(value)
            for value in universe.get("referenceResourceReleases", [])
        }
        actual_imports = {
            structural_key(value)
            for value in universe.get("registryImportSnapshots", [])
        }
        actual_mapping_snapshots = {
            structural_key(value)
            for value in universe.get("mappingSnapshots", [])
        }
        actual_mapping_releases = {
            structural_key(value)
            for value in universe.get("mappingReleases", [])
        }
        if (
            not expected_releases.issubset(actual_releases)
            or not expected_imports.issubset(actual_imports)
            or not expected_mapping_snapshots.issubset(
                actual_mapping_snapshots
            )
            or expected_mapping_releases != actual_mapping_releases
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-011",
                    "sealed-gold vocabulary universe omits an OutputProfile permission pin",
                )
            )

    items = record.get("items", [])
    items_by_id = {item.get("id"): item for item in items}
    item_ids = [item.get("id") for item in items]
    if len(item_ids) != len(set(item_ids)):
        diagnostics.append(Diagnostic("REF-EVAL-011", "gold item identifiers must be unique"))

    partitions = record.get("partitions", {})
    development = partitions.get("development", [])
    holdout = partitions.get("holdout", [])
    if set(development) & set(holdout):
        diagnostics.append(Diagnostic("REF-EVAL-012", "an item occurs in both partitions"))
    declared = development + holdout
    if len(declared) != len(set(declared)) or set(declared) != set(item_ids):
        diagnostics.append(
            Diagnostic(
                "REF-EVAL-011",
                "each gold item must occur exactly once in the declared development or holdout split",
            )
        )
    for item in items:
        if item.get("id") not in partitions.get(item.get("split"), []):
            diagnostics.append(
                Diagnostic("REF-EVAL-011", f"{item.get('id')}: item split disagrees with partitions")
            )

    group_splits: dict[str, set[str]] = {}
    for item in items:
        for group in item.get("linkedGroupIds", []):
            group_splits.setdefault(group, set()).add(item.get("split"))
    for group, splits in group_splits.items():
        if len(splits) > 1:
            diagnostics.append(
                Diagnostic("REF-EVAL-012", f"linked group {group} crosses partitions")
            )

    dimensions = record.get("partitionReport", {}).get("dimensions", [])
    dimension_names = [dimension.get("dimension") for dimension in dimensions]
    if set(dimension_names) != PARTITION_DIMENSIONS or len(dimension_names) != len(
        PARTITION_DIMENSIONS
    ):
        diagnostics.append(
            Diagnostic(
                "REF-EVAL-012",
                "partition report must contain each leakage dimension exactly once",
            )
        )
    partition_values: dict[str, dict[str, set[str]]] = {}
    for dimension in dimensions:
        name = dimension.get("dimension", "<unknown>")
        item_keys = dimension.get("itemKeys", [])
        key_item_ids = [item.get("item") for item in item_keys]
        if len(key_item_ids) != len(set(key_item_ids)) or set(key_item_ids) != set(item_ids):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{name}: partition keys must account for every item exactly once",
                )
            )
            continue
        values_by_split: dict[str, set[str]] = {
            "development": set(),
            "holdout": set(),
        }
        partition_values[name] = {}
        for entry in item_keys:
            item = items_by_id.get(entry.get("item"))
            values = set(entry.get("values", []))
            partition_values[name][entry.get("item")] = values
            if item is not None:
                comparable_values = (
                    {
                        normalized
                        for value in values
                        if (normalized := normalize_alias_key(value))
                    }
                    if name == "alias"
                    else values
                )
                values_by_split[item["split"]].update(comparable_values)
        crossing = values_by_split["development"] & values_by_split["holdout"]
        if crossing:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{name}: development and holdout share {sorted(crossing)!r}",
                )
            )

    report_input_digests = set(
        record.get("partitionReport", {}).get("inputDigests", [])
    )
    expression_corpus_digests = set(
        universe.get("indexedExpressionCorpusDigests", [])
    )
    for item in items:
        item_id = item.get("id")
        item_partition_keys = item.get("partitionKeys", {})
        for dimension in PARTITION_DIMENSIONS:
            authoritative_values = set(
                item_partition_keys.get(dimension, [])
            )
            reported_values = partition_values.get(dimension, {}).get(
                item_id, set()
            )
            if authoritative_values != reported_values:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-012",
                        f"{item_id}: partition report {dimension} keys differ from the sealed item keys",
                    )
                )
        source_values = set(
            item_partition_keys.get("sourceIdentity", [])
        )
        if source_values != {item.get("sourceResource")}:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: sourceIdentity keys must exactly match sourceResource",
                )
            )
        artifact_values = set(
            item_partition_keys.get("artifactDigest", [])
        )
        artifact_digest = item.get("renditionArtifact", {}).get("digest")
        if artifact_values != {artifact_digest}:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: artifactDigest keys must exactly match renditionArtifact.digest",
                )
            )
        evidence = item.get("partitionEvidence", {})
        text_values = set(item_partition_keys.get("textDigest", []))
        if text_values != {evidence.get("sourceTextDigest")}:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: textDigest keys must exactly match partition evidence",
                )
            )
        if not item_partition_keys.get("nearDuplicateCluster"):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: nearDuplicateCluster requires at least one computed key",
                )
            )
        evidence_inputs = {
            evidence.get("vocabularyExpressionCorpusDigest"),
            evidence.get("exactMatchGraphDigest"),
            evidence.get("nearDuplicateAnalysisDigest"),
        }
        if not evidence_inputs.issubset(report_input_digests):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: partition evidence digests must occur in partitionReport.inputDigests",
                )
            )
        if evidence.get(
            "vocabularyExpressionCorpusDigest"
        ) not in expression_corpus_digests:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: alias evidence corpus is outside the sealed vocabulary universe",
                )
            )

    reviewers = set(record.get("reviewers", []))
    expectation_items: set[str] = set()
    expectation_ids: set[str] = set()
    registered_concepts_by_item: dict[str, set[str]] = {
        item_id: set() for item_id in item_ids
    }
    open_labels_by_item: dict[str, set[str]] = {
        item_id: set() for item_id in item_ids
    }
    for expectation in record.get("expectations", []):
        expectation_id = expectation.get("id")
        if expectation_id in expectation_ids:
            diagnostics.append(
                Diagnostic("REF-EVAL-011", f"duplicate expectation identifier {expectation_id}")
            )
        expectation_ids.add(expectation_id)
        expectation_items.add(expectation.get("item"))
        minimum = expectation.get("minimumCardinality", 0)
        maximum = expectation.get("maximumCardinality", 0)
        if minimum > maximum:
            diagnostics.append(
                Diagnostic("REF-EVAL-011", f"{expectation_id}: minimum exceeds maximum cardinality")
            )
        if expectation.get("validZeroResult") != (minimum == 0):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-011",
                    f"{expectation_id}: validZeroResult must agree with zero minimum cardinality",
                )
            )

        judgments = expectation.get("reviewerJudgments", [])
        judgment_reviewers = [judgment.get("reviewer") for judgment in judgments]
        if len(judgment_reviewers) != len(set(judgment_reviewers)):
            diagnostics.append(
                Diagnostic("REF-EVAL-013", f"{expectation_id}: reviewers must be distinct")
            )
        if not set(judgment_reviewers).issubset(reviewers):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-013",
                    f"{expectation_id}: each judgment reviewer must appear in reviewers",
                )
            )
        if expectation.get("disagreement"):
            adjudication = expectation.get("adjudication")
            exclusion = expectation.get("exclusion")
            if not adjudication and not exclusion:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-013",
                        f"{expectation_id}: disagreement needs a third adjudicator or exclusion",
                    )
                )
            if adjudication:
                adjudicator = adjudication.get("adjudicator")
                if adjudicator in judgment_reviewers or adjudicator not in reviewers:
                    diagnostics.append(
                        Diagnostic(
                            "REF-EVAL-013",
                            f"{expectation_id}: adjudicator must be a third distinct listed reviewer",
                        )
                    )

        targets = expectation.get("registeredTargets", [])
        item_id = expectation.get("item")
        registered_concepts_by_item.setdefault(item_id, set()).update(
            target["target"] for target in targets if "target" in target
        )
        open_labels_by_item.setdefault(item_id, set()).update(
            label["value"] for label in expectation.get("acceptableOpenLabels", [])
        )
        not_represented = [target for target in targets if target.get("grade") == "notRepresented"]
        if not_represented:
            routed = (
                bool(expectation.get("acceptableOpenLabels"))
                or expectation.get("conceptProposalAllowed") is True
                or expectation.get("abstentionAllowed") is True
            )
            flags_match = (
                expectation.get("excludeFromReachableCandidateRecall") is True
                and expectation.get("includeInTargetAvailability") is True
                and expectation.get("includeInOpenSetMeasures") is True
            )
            if len(not_represented) != 1 or len(targets) != 1 or not routed or not flags_match:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"{expectation_id}: notRepresented must be the sole target and use an open-set route and measures",
                    )
                )
        else:
            if expectation.get("excludeFromReachableCandidateRecall") is not False:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"{expectation_id}: represented targets belong in reachable recall",
                    )
                )
        for target in targets:
            if (
                "release" in target
                and structural_key(target["release"])
                not in universe_release_keys
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-011",
                        f"{expectation_id}: registered target release is outside the sealed vocabulary universe",
                    )
                )
            grade = target.get("grade")
            adequate = target.get("adequate")
            reviewed = target.get("independentlyReviewed")
            if grade == "exact" and not adequate:
                diagnostics.append(
                    Diagnostic("REF-EVAL-014", f"{expectation_id}: exact target must be adequate")
                )
            elif grade == "close" and adequate and not reviewed:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"{expectation_id}: adequate close target needs independent review",
                    )
                )
            elif grade in {"wrong", "notRepresented"} and adequate:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"{expectation_id}: {grade} can never be an adequate registered target",
                    )
                )
            elif (
                grade
                in {
                    "targetBroaderThanGold",
                    "targetNarrowerThanGold",
                    "related",
                }
                and adequate
                and (not reviewed or "adequacyPolicy" not in target)
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"{expectation_id}: non-default adequacy needs an independently reviewed policy",
                    )
                )
    if expectation_items != set(item_ids):
        diagnostics.append(
            Diagnostic("REF-EVAL-011", "each gold item must have at least one facet-and-role expectation")
        )
    for item_id in item_ids:
        item_partition_keys = items_by_id.get(item_id, {}).get(
            "partitionKeys", {}
        )
        declared_concepts = set(
            item_partition_keys.get("conceptIdentity", [])
        )
        missing_concepts = registered_concepts_by_item.get(item_id, set()) - declared_concepts
        if missing_concepts:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: conceptIdentity keys omit registered targets {sorted(missing_concepts)!r}",
                )
            )
        declared_aliases = {
            normalized
            for value in item_partition_keys.get("alias", [])
            if (normalized := normalize_alias_key(value))
        }
        registered_aliases = {
            normalize_alias_key(expression.get("indexedText"))
            for expression in records_by_id.values()
            if expression.get("type")
            == "urn:ref:type:IndexedVocabularyExpression"
            and expression.get("member")
            in registered_concepts_by_item.get(item_id, set())
            and expression.get("semanticProperty")
            in {
                "http://www.w3.org/2004/02/skos/core#prefLabel",
                "http://www.w3.org/2004/02/skos/core#altLabel",
                "http://www.w3.org/2004/02/skos/core#hiddenLabel",
            }
            and normalize_alias_key(expression.get("indexedText"))
        }
        expected_aliases = {
            normalized
            for value in open_labels_by_item.get(item_id, set())
            if (normalized := normalize_alias_key(value))
        } | registered_aliases
        if declared_aliases != expected_aliases:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: alias keys must exactly match sealed registered aliases and acceptable open labels",
                )
            )
        if (
            registered_concepts_by_item.get(item_id)
            and not item_partition_keys.get("exactMatchCluster")
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-012",
                    f"{item_id}: represented concepts require an exact-match cluster key",
                )
            )
    return diagnostics


def configuration_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    known_expression_corpora = {
        structural_key(candidate["expressionCorpusSnapshot"])
        for candidate in records_by_id.values()
        if candidate.get("type")
        in {
            "urn:ref:type:RegistryImportCoverageReport",
            "urn:ref:type:IndexedVocabularyExpression",
        }
        and isinstance(candidate.get("expressionCorpusSnapshot"), dict)
    }
    for index, item in enumerate(record.get("indexes", [])):
        expression_corpus = item.get("expressionCorpusSnapshot", {})
        lookup_index = item.get("lookupIndexManifest", {})
        if (
            isinstance(expression_corpus, dict)
            and isinstance(lookup_index, dict)
            and expression_corpus.get("id") == lookup_index.get("id")
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-ENR-019",
                    f"indexes[{index}] conflates expressionCorpusSnapshot with lookupIndexManifest",
                )
            )
        if known_expression_corpora:
            if (
                isinstance(expression_corpus, dict)
                and structural_key(expression_corpus)
                not in known_expression_corpora
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-ENR-019",
                        f"indexes[{index}].expressionCorpusSnapshot does not "
                        "resolve to a logical corpus in the linked records",
                    )
                )
            if (
                isinstance(lookup_index, dict)
                and structural_key(lookup_index)
                in known_expression_corpora
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-ENR-019",
                        f"indexes[{index}].lookupIndexManifest reuses a "
                        "logical expression-corpus identity",
                    )
                )
    for field, expected_type in (
        ("enrichmentProfile", "urn:ref:type:EnrichmentProfile"),
        ("outputProfile", "urn:ref:type:OutputProfile"),
    ):
        reference = record.get(field, {})
        target = records_by_id.get(reference.get("id"))
        if target is None or (
            target.get("type") != expected_type
            or not references_record(reference, target)
        ):
            diagnostics.append(
                Diagnostic("REF-ENR-019", f"{field} does not match the exact referenced record")
            )
    output = records_by_id.get(record.get("outputProfile", {}).get("id"))
    if output is not None and output.get("enrichmentProfile") != record.get("enrichmentProfile"):
        diagnostics.append(
            Diagnostic(
                "REF-ENR-019",
                "configuration enrichmentProfile differs from the output profile's exact pin",
            )
        )
    if output is not None and output.get("type") == "urn:ref:type:OutputProfile":
        expected_releases = {
            structural_key(row[field])
            for row, fields in (
                *(
                    (row, ("referenceResourceRelease",))
                    for row in output.get("releasePermissions", [])
                ),
                *(
                    (row, ("sourceRelease", "targetRelease"))
                    for row in output.get("mappingPermissions", [])
                ),
            )
            for field in fields
        }
        expected_imports = {
            structural_key(row["registryImportSnapshot"])
            for row in output.get("releasePermissions", [])
        }
        expected_mapping_snapshots = {
            structural_key(row["mappingSnapshot"])
            for row in output.get("mappingPermissions", [])
        }
        expected_mapping_releases = mapping_coverage_releases(
            output,
            records_by_id,
        )
        vocabulary = record.get("vocabulary", {})
        actual_releases = {
            structural_key(value)
            for value in vocabulary.get("referenceResourceReleases", [])
        }
        actual_imports = {
            structural_key(value)
            for value in vocabulary.get("registryImportSnapshots", [])
        }
        actual_mapping_snapshots = {
            structural_key(value)
            for value in vocabulary.get("mappingSnapshots", [])
        }
        actual_mapping_releases = {
            structural_key(value)
            for value in vocabulary.get("mappingReleases", [])
        }
        if (
            not expected_releases.issubset(actual_releases)
            or not expected_imports.issubset(actual_imports)
            or not expected_mapping_snapshots.issubset(
                actual_mapping_snapshots
            )
            or expected_mapping_releases != actual_mapping_releases
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-ENR-019",
                    "configuration vocabulary omits an OutputProfile permission pin",
                )
            )
        deployment_snapshots: set[str] = set()
        for deployment_ref in vocabulary.get(
            "registryDeploymentDecisions", []
        ):
            deployment = records_by_id.get(deployment_ref.get("id"))
            if (
                deployment is None
                or deployment.get("type")
                != "urn:ref:type:RegistryDeploymentDecision"
                or not references_record(deployment_ref, deployment)
                or deployment.get("selectionState") != "selected"
                or deployment.get("outputProfile")
                != record.get("outputProfile")
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-ENR-019",
                        "configuration requires exact selected registry-deployment decisions for its OutputProfile",
                    )
                )
                continue
            deployment_snapshots.add(
                structural_key(
                    deployment.get("registryImportSnapshot")
                )
            )
        if actual_imports != deployment_snapshots:
            diagnostics.append(
                Diagnostic(
                    "REF-ENR-019",
                    "configuration registry imports and selected deployment decisions must agree exactly",
                )
            )
    return diagnostics


def parse_decimal(value: Any) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def evaluation_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    configuration = records_by_id.get(record.get("configuration", {}).get("id"))
    gold = records_by_id.get(record.get("sealedGoldManifest", {}).get("id"))
    if configuration is None or not references_record(record.get("configuration", {}), configuration):
        diagnostics.append(
            Diagnostic("REF-EVAL-016", "evaluation configuration identifier or digest does not match")
        )
    if gold is None or not references_record(record.get("sealedGoldManifest", {}), gold):
        diagnostics.append(
            Diagnostic("REF-EVAL-016", "evaluation sealed-gold identifier or digest does not match")
        )
    if configuration is not None and gold is not None:
        universe = gold.get("vocabularyUniverse", {})
        if configuration.get("outputProfile") != universe.get("outputProfile"):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-016",
                    "configuration and sealed gold use different output-profile pins",
                )
            )
        if configuration.get("enrichmentProfile") != universe.get(
            "enrichmentProfile"
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-016",
                    "configuration and sealed gold use different enrichment-profile pins",
                )
            )
        configuration_vocabulary = configuration.get("vocabulary", {})
        for field in (
            "referenceResourceReleases",
            "registryImportSnapshots",
            "mappingReleases",
            "mappingSnapshots",
        ):
            configured = {
                structural_key(value)
                for value in configuration_vocabulary.get(field, [])
            }
            sealed = {
                structural_key(value) for value in universe.get(field, [])
            }
            if configured != sealed:
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-016",
                        f"configuration and sealed gold use different {field}",
                    )
                )
        if configuration_vocabulary.get(
            "candidateTargetUniverseDigest"
        ) != universe.get("candidateTargetUniverseDigest"):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-016",
                    "configuration and sealed gold use different candidate target universes",
                )
            )
        normalization_policies = {
            structural_key(index.get("normalizationPolicy"))
            for index in configuration.get("indexes", [])
        }
        if normalization_policies != {
            structural_key(universe.get("normalizationPolicy"))
        }:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-016",
                    "configuration and sealed gold use different normalization policies",
                )
            )
        configured_expression_corpora = {
            index.get("indexedExpressionCorpusDigest")
            for index in configuration.get("indexes", [])
        }
        if configured_expression_corpora != set(
            universe.get("indexedExpressionCorpusDigests", [])
        ):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-016",
                    "configuration and sealed gold use different indexed-expression corpora",
                )
            )
        if gold.get("corpusDigest") not in {
            corpus.get("digest")
            for corpus in configuration.get("inputCorpora", [])
        }:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-016",
                    "configuration input corpora omit the sealed gold corpus digest",
                )
            )
        expectations = {
            expectation.get("id"): expectation
            for expectation in gold.get("expectations", [])
        }
        not_represented = {
            expectation_id
            for expectation_id, expectation in expectations.items()
            if any(
                target.get("grade") == "notRepresented"
                for target in expectation.get("registeredTargets", [])
            )
        }
        populations = {
            population.get("populationKind"): population
            for population in record.get("measurePopulations", [])
        }
        if set(populations) != {
            "reachableRegisteredCandidateRecall",
            "targetAvailability",
            "openSet",
        }:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-014",
                    "evaluation must report all three notRepresented measure populations",
                )
            )
        for kind, population in populations.items():
            included = set(population.get("includedExpectations", []))
            excluded = set(population.get("excludedExpectations", []))
            if included & excluded or included | excluded != set(expectations):
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"{kind}: included and excluded expectations must partition the sealed expectations",
                    )
                )
            if kind == "reachableRegisteredCandidateRecall":
                if not_represented & included or not not_represented.issubset(excluded):
                    diagnostics.append(
                        Diagnostic(
                            "REF-EVAL-014",
                            "notRepresented expectations must be excluded from reachable registered-candidate recall",
                        )
                    )
            elif not not_represented.issubset(included):
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-014",
                        f"notRepresented expectations must remain in {kind} measures",
                    )
                )

    predeclared = record.get("predeclaredMeasures", [])
    observed_rows = record.get("observedMeasures", [])
    threshold_rows = record.get("thresholds", [])
    observed_ids = [item.get("measure") for item in observed_rows]
    threshold_ids = [item.get("measure") for item in threshold_rows]
    if (
        len(predeclared) != len(set(predeclared))
        or len(observed_ids) != len(set(observed_ids))
        or len(threshold_ids) != len(set(threshold_ids))
        or set(predeclared) != set(observed_ids)
        or set(predeclared) != set(threshold_ids)
    ):
        diagnostics.append(
            Diagnostic(
                "REF-EVAL-015",
                "predeclared, observed, and threshold measures must be exact one-to-one sets",
            )
        )

    observed = {item.get("measure"): item for item in observed_rows}
    for item in observed_rows:
        value = parse_decimal(item.get("value"))
        lower = parse_decimal(item.get("uncertaintyLower"))
        upper = parse_decimal(item.get("uncertaintyUpper"))
        if value is None or lower is None or upper is None or not (lower <= value <= upper):
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-015",
                    f"{item.get('measure')}: uncertainty must be finite and contain the observed value",
                )
            )
    threshold_failures: list[str] = []
    for threshold in threshold_rows:
        measure = threshold.get("measure")
        observation = observed.get(measure)
        if observation is None:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-015",
                    f"threshold measure {measure} lacks an observation",
                )
            )
        threshold_value = parse_decimal(threshold.get("value"))
        if threshold_value is None:
            diagnostics.append(
                Diagnostic("REF-EVAL-015", "threshold values must be finite canonical decimals")
            )
        observed_value = (
            parse_decimal(observation.get("value"))
            if observation is not None
            else None
        )
        operator = threshold.get("operator")
        if threshold_value is not None and observed_value is not None and (
            (operator == "atLeast" and observed_value < threshold_value)
            or (operator == "atMost" and observed_value > threshold_value)
        ):
            threshold_failures.append(str(measure))

    if record.get("verdict") == "pass":
        if threshold_failures:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-015",
                    f"pass verdict misses thresholds for {sorted(threshold_failures)!r}",
                )
            )
        failed_gates = [gate.get("id") for gate in record.get("gates", []) if not gate.get("passed")]
        if failed_gates:
            diagnostics.append(
                Diagnostic("REF-EVAL-015", f"pass verdict has failed gates {failed_gates!r}")
            )
        dimensions = {gate.get("dimension") for gate in record.get("gates", [])}
        if dimensions != EVALUATION_GATE_DIMENSIONS:
            diagnostics.append(
                Diagnostic(
                    "REF-EVAL-015",
                    "pass verdict must report every core evaluation-gate dimension",
                )
            )
        for stratum in record.get("configuredStrata", []):
            if (
                stratum.get("passed") is not True
                or stratum.get("observedSampleSize", 0) < stratum.get("minimumSampleSize", 0)
            ):
                diagnostics.append(
                    Diagnostic(
                        "REF-EVAL-015",
                        f"pass verdict does not satisfy stratum {stratum.get('stratum')}",
                    )
                )
    return diagnostics


def deployment_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    configuration = records_by_id.get(record.get("configuration", {}).get("id"))
    evaluation = records_by_id.get(record.get("evaluationResult", {}).get("id"))
    output = records_by_id.get(record.get("outputProfile", {}).get("id"))
    for label, reference, target in (
        ("configuration", record.get("configuration", {}), configuration),
        ("evaluationResult", record.get("evaluationResult", {}), evaluation),
        ("outputProfile", record.get("outputProfile", {}), output),
    ):
        if target is None or not references_record(reference, target):
            diagnostics.append(
                Diagnostic("REF-ENR-020", f"deployment {label} identifier or digest does not match")
            )
    if configuration is not None and configuration.get("outputProfile") != record.get(
        "outputProfile"
    ):
        diagnostics.append(
            Diagnostic("REF-ENR-020", "deployment output profile differs from its configuration")
        )
    if evaluation is not None and evaluation.get("configuration") != record.get("configuration"):
        diagnostics.append(
            Diagnostic("REF-ENR-020", "deployment evaluation names a different configuration")
        )
    production_selected = (
        record.get("environment", {}).get("classification") == "production"
        and record.get("selectionState") == "selected"
    )
    if production_selected and (evaluation is None or evaluation.get("verdict") != "pass"):
        diagnostics.append(
            Diagnostic("REF-TEST-160", "selected production deployment requires a pass verdict")
        )
    if production_selected and (
        not record.get("rulespecAttestationRefs")
        or not record.get("localAdoptionRefs")
    ):
        diagnostics.append(
            Diagnostic(
                "REF-TEST-160",
                "selected production deployment requires attestation and "
                "local-adoption references for release-gate evaluation",
            )
        )
    return diagnostics


def capture_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    """Require every accessScopeRef to resolve to a real ``rkaf:AccessScope`` record.

    The type checked here, ``rkaf:AccessScope``, is the same string
    ``release_graph.py``'s ``RULESPEC_ACCESS_SCOPE`` already resolves
    ``accessScopeRefs/*`` against in the Rulespec release graph (compact form
    of ``https://rulespec.org/ns/v1#AccessScope``) -- this is a second,
    binding-local resolution against records co-resident in the same REF
    record set, not a REF-owned twin of that type.

    ``rightsExpressionRefs`` is deliberately left alone: no RefSpec record
    type or consumer exists for it yet, so a resolution rule here would be
    unenforceable structure (see REF-023 item 3).
    """

    diagnostics: list[Diagnostic] = []
    for ref in record.get("accessScopeRefs", []):
        target = records_by_id.get(ref) if isinstance(ref, str) else None
        if target is None or target.get("type") != "rkaf:AccessScope":
            diagnostics.append(
                Diagnostic(
                    "REF-SEC-008",
                    f"{record.get('id')} accessScopeRefs cannot resolve {ref!r} to an rkaf:AccessScope record",
                )
            )
    return diagnostics


def semantic_diagnostics(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[Diagnostic]:
    record_type = record.get("type")
    if record_type == "urn:ref:type:EnrichmentProfile":
        return validate_enrichment_profile(record)
    if record_type == "urn:ref:type:OutputProfile":
        return permission_prerequisite_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:Capture":
        return capture_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:RegistryImportCoverageReport":
        return coverage_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:IndexedVocabularyExpression":
        return indexed_expression_diagnostics(record)
    if record_type == "urn:ref:type:RegistryReconciliationReport":
        return reconciliation_diagnostics(record)
    if record_type == "urn:ref:type:RegistryDeploymentDecision":
        return registry_deployment_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:SealedGoldManifest":
        return sealed_gold_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:EnrichmentConfiguration":
        return configuration_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:EnrichmentEvaluationResult":
        return evaluation_diagnostics(record, records_by_id)
    if record_type == "urn:ref:type:EnrichmentDeploymentDecision":
        return deployment_diagnostics(record, records_by_id)
    return []


def language_tag_diagnostics(
    tests: list[dict[str, Any]],
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
) -> list[Diagnostic]:
    definition = schemas["common.schema.json"]["$defs"]["bcp47Language"]
    validator = Draft202012Validator(
        definition,
        registry=registry,
        format_checker=FormatChecker(),
    )
    diagnostics: list[Diagnostic] = []
    for test in tests:
        valid = not list(validator.iter_errors(test.get("tag")))
        if valid != test.get("claimedValid"):
            diagnostics.append(
                Diagnostic(
                    "REF-TEST-161",
                    f"language tag {test.get('tag')!r} validity is {valid}, not {test.get('claimedValid')}",
                )
            )
    return diagnostics


def validate_records(
    records: list[dict[str, Any]],
    permission_checks: list[dict[str, Any]],
    language_tag_tests: list[dict[str, Any]],
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
) -> list[Diagnostic]:
    diagnostics = duplicate_id_diagnostics(records)
    diagnostics.extend(digest_cycle_diagnostics(records))
    records_by_id = {
        record.get("id"): record for record in records if isinstance(record.get("id"), str)
    }
    for record in records:
        schema_errors = schema_diagnostics(record, schemas, registry)
        diagnostics.extend(schema_errors)
        try:
            diagnostics.extend(record_digest_diagnostics(record))
        except (TypeError, ValueError) as error:
            diagnostics.append(Diagnostic("REF-BIND-004", f"{record.get('id')}: {error}"))
        if not schema_errors:
            diagnostics.extend(semantic_diagnostics(record, records_by_id))
    for check in permission_checks:
        diagnostics.extend(run_permission_check(check, records_by_id))
    diagnostics.extend(language_tag_diagnostics(language_tag_tests, schemas, registry))
    return diagnostics


def validate(
    records: Iterable[dict[str, Any]],
    *,
    permission_checks: Iterable[dict[str, Any]] = (),
    language_tag_tests: Iterable[dict[str, Any]] = (),
) -> list[Diagnostic]:
    """Validate linked REF records with the schemas from this checkout."""

    schemas, registry = load_schemas()
    return validate_records(
        list(records),
        list(permission_checks),
        list(language_tag_tests),
        schemas,
        registry,
    )


class IndexedExpressionCorpusValidator:
    """Stateful, one-schema validator for a streamed expression corpus."""

    def __init__(self) -> None:
        schemas, registry = load_schemas()
        record_type = "urn:ref:type:IndexedVocabularyExpression"
        self._validator = Draft202012Validator(
            schemas[TYPE_SCHEMAS[record_type]],
            registry=registry,
            format_checker=FormatChecker(),
        )
        self._requirement = TYPE_REQUIREMENTS[record_type]
        self._seen: set[str] = set()
        self._index = 0

    def validate_record(
        self,
        record: dict[str, Any],
    ) -> list[Diagnostic]:
        """Validate one record and retain only duplicate-ID state."""

        diagnostics: list[Diagnostic] = []
        index = self._index
        self._index += 1
        identifier = record.get("id")
        if not isinstance(identifier, str):
            identifier = f"<expression-{index}>"
        elif identifier in self._seen:
            diagnostics.append(
                Diagnostic(
                    "REF-CORE-005",
                    f"duplicate durable record identifier {identifier}",
                )
            )
        else:
            self._seen.add(identifier)

        schema_errors = sorted(
            self._validator.iter_errors(record),
            key=lambda item: list(item.path),
        )
        diagnostics.extend(
            Diagnostic(
                self._requirement,
                f"{identifier} {json_path(error.absolute_path)}: "
                f"{error.message}",
            )
            for error in schema_errors
        )
        try:
            diagnostics.extend(record_digest_diagnostics(record))
        except (TypeError, ValueError) as error:
            diagnostics.append(
                Diagnostic("REF-BIND-004", f"{identifier}: {error}")
            )
        if not schema_errors:
            diagnostics.extend(indexed_expression_diagnostics(record))
        return diagnostics


def validate_indexed_expression_records(
    records: Iterable[dict[str, Any]],
) -> list[Diagnostic]:
    """Validate a corpus without constructing one linked-record graph.

    ``IndexedVocabularyExpression`` records have no cross-record semantic
    references. The validator compiles JSON Schema once and retains only the
    identifier set needed to reject duplicates.
    """

    validator = IndexedExpressionCorpusValidator()
    diagnostics: list[Diagnostic] = []
    for record in records:
        diagnostics.extend(validator.validate_record(record))
    return diagnostics


def pointer_parent(document: Any, pointer: str) -> tuple[Any, str]:
    parts = pointer.lstrip("/").split("/") if pointer else []
    if not parts:
        raise ValueError("mutation path cannot target the record root")
    current = document
    for raw in parts[:-1]:
        part = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current, parts[-1].replace("~1", "/").replace("~0", "~")


def apply_mutations(records: list[dict[str, Any]], mutations: list[dict[str, Any]]) -> None:
    for mutation in mutations:
        matches = [record for record in records if record.get("id") == mutation.get("recordId")]
        if len(matches) != 1:
            raise ValueError(f"mutation recordId {mutation.get('recordId')!r} is not unique")
        parent, key = pointer_parent(matches[0], mutation.get("path", ""))
        operation = mutation.get("operation", "replace")
        if isinstance(parent, list):
            index = int(key)
            if operation == "remove":
                del parent[index]
            elif operation == "add":
                parent.insert(index, mutation.get("value"))
            else:
                parent[index] = mutation.get("value")
        elif operation == "remove":
            del parent[key]
        else:
            parent[key] = mutation.get("value")


def refresh_record_digest(record: dict[str, Any]) -> None:
    if record.get("type") == "urn:ref:type:IndexedVocabularyExpression":
        record["indexedTextDigest"] = text_digest(record["indexedText"])
    record[digest_field(record)] = canonical_payload_digest(record)


def refresh_fixture(fixture: dict[str, Any]) -> None:
    records = fixture["records"]
    records_by_id = {record["id"]: record for record in records}
    for _ in range(len(records) + 2):
        changed = False
        for record in records:
            def update_references(value: Any, top_level: bool = False) -> None:
                nonlocal changed
                if isinstance(value, dict):
                    if not top_level and "id" in value and "digest" in value:
                        target = records_by_id.get(value["id"])
                        if target is not None:
                            target_digest = target.get(digest_field(target))
                            if target_digest and value.get("digest") != target_digest:
                                value["digest"] = target_digest
                                changed = True
                            if (
                                "version" in value
                                and target.get("version") is not None
                                and value["version"] != target["version"]
                            ):
                                value["version"] = target["version"]
                                changed = True
                    for child in value.values():
                        update_references(child)
                elif isinstance(value, list):
                    for child in value:
                        update_references(child)

            update_references(record, top_level=True)
            if record.get("type") == "urn:ref:type:IndexedVocabularyExpression":
                expected_text_digest = text_digest(record["indexedText"])
                if record.get("indexedTextDigest") != expected_text_digest:
                    record["indexedTextDigest"] = expected_text_digest
                    changed = True
            expected = canonical_payload_digest(record)
            field = digest_field(record)
            if record.get(field) != expected:
                record[field] = expected
                changed = True
        if not changed:
            return
    raise RuntimeError("fixture digest graph did not converge")


def load_fixture(path: Path) -> dict[str, Any]:
    fixture = load_json(path)
    if fixture.get("rawPayload"):
        raw_path = (path.parent / fixture["rawPayload"]).resolve()
        try:
            record = load_json(raw_path)
        except DuplicateKeyError as error:
            return {
                "records": [],
                "permissionChecks": [],
                "languageTagTests": [],
                "expectedRequirements": fixture.get("expectedRequirements", []),
                "parseDiagnostics": [Diagnostic("REF-BIND-001", str(error))],
            }
        except ValueError as error:
            return {
                "records": [],
                "permissionChecks": [],
                "languageTagTests": [],
                "expectedRequirements": fixture.get("expectedRequirements", []),
                "parseDiagnostics": [Diagnostic("REF-BIND-004", str(error))],
            }
        return {
            "records": [record],
            "permissionChecks": [],
            "languageTagTests": [],
            "expectedRequirements": fixture.get("expectedRequirements", []),
            "parseDiagnostics": [],
        }
    base_path = fixture.get("base")
    if base_path:
        base = load_fixture((path.parent / base_path).resolve())
        records = copy.deepcopy(base.get("records", []))
        permission_checks = copy.deepcopy(base.get("permissionChecks", []))
        language_tests = copy.deepcopy(base.get("languageTagTests", []))
    else:
        records = copy.deepcopy(fixture.get("records", []))
        permission_checks = []
        language_tests = []
    apply_mutations(records, fixture.get("mutations", []))
    records_by_id = {record.get("id"): record for record in records}
    for record_id in fixture.get("refreshDigests", []):
        record = records_by_id.get(record_id)
        if record is None:
            raise ValueError(f"refreshDigests cannot resolve {record_id!r}")
        refresh_record_digest(record)
    permission_checks.extend(copy.deepcopy(fixture.get("permissionChecks", [])))
    language_tests.extend(copy.deepcopy(fixture.get("languageTagTests", [])))
    return {
        "records": records,
        "permissionChecks": permission_checks,
        "languageTagTests": language_tests,
        "expectedRequirements": fixture.get("expectedRequirements", []),
        "parseDiagnostics": [],
    }


def run_fixture(
    path: Path,
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
    expect_valid: bool,
) -> tuple[bool, list[Diagnostic]]:
    fixture = load_fixture(path)
    diagnostics = fixture["parseDiagnostics"] or validate_records(
        fixture["records"],
        fixture["permissionChecks"],
        fixture["languageTagTests"],
        schemas,
        registry,
    )
    if expect_valid:
        return not diagnostics, diagnostics
    expected = set(fixture["expectedRequirements"])
    found = {diagnostic.requirement for diagnostic in diagnostics}
    missing = expected - found
    if not diagnostics:
        return False, [Diagnostic("REF-TEST-131", "invalid fixture was accepted")]
    if missing:
        return False, [
            *diagnostics,
            Diagnostic(
                "REF-TEST-131",
                f"invalid fixture did not produce expected requirements {sorted(missing)!r}",
            ),
        ]
    return True, diagnostics


def requirement_manifest_diagnostics() -> list[Diagnostic]:
    path = BINDING_ROOT / "tests" / "requirement-to-test-manifest.json"
    manifest = load_json(path)
    coverage = manifest.get("coverage", [])
    requirements = [entry.get("requirement") for entry in coverage]
    diagnostics: list[Diagnostic] = []
    if len(requirements) != len(set(requirements)):
        diagnostics.append(
            Diagnostic("REF-TEST-131", "requirement-to-test manifest repeats a requirement")
        )
    missing = REQUIRED_MANIFEST_REQUIREMENTS - set(requirements)
    if missing:
        diagnostics.append(
            Diagnostic(
                "REF-TEST-131",
                f"requirement-to-test manifest omits {sorted(missing)!r}",
            )
        )
    referenced_fixtures: set[str] = set()
    for entry in coverage:
        local = entry.get("localFixtures", [])
        external = (
            entry.get("externalGate")
            or entry.get("externalRulespecPaths")
            or entry.get("externalCommand")
        )
        checks = entry.get("validatorChecks", [])
        if not local and not external:
            diagnostics.append(
                Diagnostic(
                    "REF-TEST-131",
                    f"{entry.get('requirement')}: no local fixture or external gate",
                )
            )
        if local and not checks and not external:
            diagnostics.append(
                Diagnostic(
                    "REF-TEST-131",
                    f"{entry.get('requirement')}: local fixtures lack a named validator check",
                )
            )
        for relative in local:
            referenced_fixtures.add(relative)
            if not _binding_asset_exists(BINDING_ROOT / relative):
                diagnostics.append(
                    Diagnostic(
                        "REF-TEST-131",
                        f"{entry.get('requirement')}: fixture {relative} does not exist",
                    )
                )

    invalid = {
        str(path.relative_to(BINDING_ROOT))
        for path in _fixture_paths("invalid")
    }
    orphaned = invalid - referenced_fixtures
    if orphaned:
        diagnostics.append(
            Diagnostic(
                "REF-TEST-131",
                f"invalid fixtures are missing from the manifest: {sorted(orphaned)!r}",
            )
        )
    return diagnostics


def run_suite() -> int:
    schemas, registry = load_schemas()
    valid_paths = _fixture_paths("valid")
    invalid_paths = _fixture_paths("invalid")
    manifest_diagnostics = requirement_manifest_diagnostics()
    failures = 1 if manifest_diagnostics else 0
    if manifest_diagnostics:
        print("FAIL requirement-to-test manifest")
        for diagnostic in manifest_diagnostics:
            print(f"  {diagnostic.render()}")
    accepted = 0
    rejected = 0
    for path in valid_paths:
        passed, diagnostics = run_fixture(path, schemas, registry, expect_valid=True)
        if passed:
            accepted += 1
        else:
            failures += 1
            print(f"FAIL valid fixture {path.relative_to(BINDING_ROOT)}")
            for diagnostic in diagnostics:
                print(f"  {diagnostic.render()}")
    for path in invalid_paths:
        passed, diagnostics = run_fixture(path, schemas, registry, expect_valid=False)
        if passed:
            rejected += 1
        else:
            failures += 1
            print(f"FAIL invalid fixture {path.relative_to(BINDING_ROOT)}")
            for diagnostic in diagnostics:
                print(f"  {diagnostic.render()}")
    print(
        f"REF JSON Binding 1.0: {accepted} valid fixture(s) accepted; "
        f"{rejected} invalid fixture(s) rejected; {failures} failure(s)"
    )
    return 1 if failures else 0


def main(argv: Iterable[str] | None = None) -> int:
    """Run the REF JSON Binding validator command-line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="append",
        type=Path,
        help="validate one standalone REF record; repeat for linked records",
    )
    parser.add_argument(
        "--print-digest",
        type=Path,
        help=f"print a {CANONICALIZATION_ALGORITHM} digest for one record",
    )
    parser.add_argument(
        "--refresh-fixture",
        type=Path,
        help="mechanically refresh digests in one base fixture",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.refresh_fixture:
        fixture = load_json(args.refresh_fixture)
        if fixture.get("base"):
            parser.error("--refresh-fixture requires a self-contained base fixture")
        refresh_fixture(fixture)
        args.refresh_fixture.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0
    if args.print_digest:
        print(canonical_payload_digest(load_json(args.print_digest)))
        return 0
    if args.record:
        schemas, registry = load_schemas()
        records = [load_json(path) for path in args.record]
        diagnostics = validate_records(records, [], [], schemas, registry)
        for diagnostic in diagnostics:
            print(diagnostic.render())
        return 1 if diagnostics else 0
    return run_suite()


if __name__ == "__main__":
    raise SystemExit(main())

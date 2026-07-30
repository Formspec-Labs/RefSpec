"""Build and validate the active Spicy Regs controlled-resource portfolio.

The checked-in source-profile snapshot is extracted from Spicy Regs source
without importing Spicy Regs as a Python dependency. RefSpec then joins that
snapshot to its own controlled-resource decisions and emits a deterministic
atlas.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from refspec.binding import CORE_FACETS

PROFILE_SNAPSHOT_FORMAT = "urn:ref:portfolio:spicy-regs-source-profiles:v1"
PORTFOLIO_INPUT_FORMAT = "urn:ref:portfolio:active-profile-controlled-resources:v1"
PORTFOLIO_ATLAS_FORMAT = "urn:ref:portfolio:active-profile-controlled-resource-atlas:v1"

CONTROLLED_RESOURCE_USES = {
    "selectableSubject",
    "sourceAssignedEvidence",
    "mappingAndSearchExpansion",
    "navigation",
    "deterministicCodeOrClassification",
    "identifierAuthority",
    "structureOrInterchange",
}

RECORD_ROLES = {
    "document",
    "observation",
    "container",
    "entity",
    "participation",
}

RESOURCE_KINDS = {
    "subjectVocabulary",
    "sourceAssignedVocabulary",
    "mappingReference",
    "codeList",
    "classification",
    "identifierAuthority",
    "structuralSchema",
    "resourceFamily",
}

DISTRIBUTION_STATUSES = {
    "available",
    "availableButUnreconciled",
    "definitionOnly",
    "historicalOnly",
    "partial",
    "plannedFamily",
    "unresolvedIdentity",
}

SUBJECT_GAP_STATUSES = {
    "none",
    "documented",
    "notApplicable",
    "deferred",
}

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OBJECT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PortfolioInventoryError(ValueError):
    """Raised when a portfolio snapshot, input, or generated atlas is invalid."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PortfolioInventoryError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    """Load one portfolio JSON object while rejecting duplicate keys."""

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(value, dict):
        raise PortfolioInventoryError(f"{path} must contain one JSON object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the deterministic JSON bytes used to pin portfolio inputs."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Digest a JSON-compatible value using the portfolio canonical form."""

    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def render_json(value: Any) -> str:
    """Render deterministic, reviewable checked-in JSON."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _assignment(tree: ast.Module, name: str) -> ast.expr:
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return statement.value
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            return statement.value
    raise PortfolioInventoryError(f"Spicy Regs source does not assign {name}")


def _literal(node: ast.expr, names: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Name):
        try:
            return names[node.id]
        except KeyError:
            raise PortfolioInventoryError(
                f"unsupported name {node.id!r} in Spicy Regs profile declaration"
            ) from None
    if isinstance(node, ast.Tuple):
        return tuple(_literal(item, names) for item in node.elts)
    if isinstance(node, ast.List):
        return [_literal(item, names) for item in node.elts]
    if isinstance(node, ast.Set):
        return {_literal(item, names) for item in node.elts}
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as error:
        raise PortfolioInventoryError(
            f"unsupported expression in Spicy Regs profile declaration: {ast.dump(node)}"
        ) from error


def extract_spicy_regs_profiles(source_path: Path) -> list[dict[str, Any]]:
    """Extract profile declarations and the Step 4 active set using Python AST.

    This deliberately reads source instead of importing ``spicy_regs``. Importing
    the application here would reverse the intended dependency direction and
    could execute provider or environment setup merely to regenerate metadata.
    """

    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    all_schemes = _literal(_assignment(tree, "ALL_CONCEPT_SCHEMES"), {})
    names = {"ALL_CONCEPT_SCHEMES": all_schemes}
    profile_expression = _assignment(tree, "SOURCE_PROFILES")
    if not isinstance(profile_expression, (ast.Tuple, ast.List)):
        raise PortfolioInventoryError("SOURCE_PROFILES must be a tuple or list")

    profiles: list[dict[str, Any]] = []
    for item in profile_expression.elts:
        if not (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == "_profile"
            and len(item.args) == 7
            and not item.keywords
        ):
            raise PortfolioInventoryError(
                "SOURCE_PROFILES must contain seven-argument _profile calls"
            )
        values = [_literal(argument, names) for argument in item.args]
        profiles.append(
            {
                "profileId": values[0],
                "sourceTable": values[1],
                "subjectType": values[2],
                "idColumns": list(values[3]),
                "textColumns": list(values[4]),
                "runtimeAllowedSchemes": list(values[5]),
                "sourceMode": values[6],
            }
        )

    active_expression = _assignment(tree, "STEP4_ACTIVE_SOURCE_TABLES")
    if not (
        isinstance(active_expression, ast.BinOp)
        and isinstance(active_expression.op, ast.Sub)
        and isinstance(active_expression.left, ast.Call)
        and isinstance(active_expression.left.func, ast.Name)
        and active_expression.left.func.id == "frozenset"
        and len(active_expression.left.args) == 1
        and isinstance(active_expression.left.args[0], ast.Name)
        and active_expression.left.args[0].id == "_PROFILE_BY_TABLE"
    ):
        raise PortfolioInventoryError(
            "STEP4_ACTIVE_SOURCE_TABLES no longer has the supported "
            "frozenset(_PROFILE_BY_TABLE) - {...} form"
        )
    deferred_tables = set(_literal(active_expression.right, names))
    source_tables = {profile["sourceTable"] for profile in profiles}
    unknown_deferred = deferred_tables - source_tables
    if unknown_deferred:
        raise PortfolioInventoryError(
            f"Step 4 defers unknown source tables: {sorted(unknown_deferred)}"
        )

    return [
        {
            **profile,
            "activeInStep4": profile["sourceTable"] not in deferred_tables,
        }
        for profile in profiles
    ]


def _require_keys(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise PortfolioInventoryError(
            f"{location} keys differ; missing={missing}, extra={extra}"
        )


def _require_nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioInventoryError(f"{location} must be a non-empty string")
    return value


def _require_unique_strings(value: Any, location: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PortfolioInventoryError(f"{location} must be a non-empty string list")
    if not all(isinstance(item, str) and item for item in value):
        raise PortfolioInventoryError(f"{location} must contain only non-empty strings")
    if len(set(value)) != len(value):
        raise PortfolioInventoryError(f"{location} contains duplicate values")
    return value


def validate_profile_snapshot(
    snapshot: Mapping[str, Any],
    *,
    source_path: Path | None = None,
) -> None:
    """Validate the checked-in Spicy Regs profile snapshot.

    When ``source_path`` is supplied, validation also proves that the snapshot
    still matches the exact source bytes and AST declarations.
    """

    _require_keys(snapshot, {"format", "source", "profiles"}, "profile snapshot")
    if snapshot["format"] != PROFILE_SNAPSHOT_FORMAT:
        raise PortfolioInventoryError("unknown profile snapshot format")

    source = snapshot["source"]
    if not isinstance(source, Mapping):
        raise PortfolioInventoryError("profile snapshot source must be an object")
    _require_keys(
        source,
        {
            "repository",
            "revision",
            "path",
            "sha256",
            "gitBlob",
        },
        "profile snapshot source",
    )
    _require_nonempty_string(source["repository"], "source.repository")
    _require_nonempty_string(source["path"], "source.path")
    if not _GIT_OBJECT_PATTERN.fullmatch(str(source["revision"])):
        raise PortfolioInventoryError("source.revision must be a 40-character Git revision")
    if not _GIT_OBJECT_PATTERN.fullmatch(str(source["gitBlob"])):
        raise PortfolioInventoryError("source.gitBlob must be a 40-character Git object")
    if not _SHA256_PATTERN.fullmatch(str(source["sha256"])):
        raise PortfolioInventoryError("source.sha256 must be a sha256 digest")

    profiles = snapshot["profiles"]
    if not isinstance(profiles, list) or len(profiles) != 17:
        raise PortfolioInventoryError("profile snapshot must contain exactly 17 profiles")
    expected_profile_keys = {
        "profileId",
        "sourceTable",
        "subjectType",
        "idColumns",
        "textColumns",
        "runtimeAllowedSchemes",
        "sourceMode",
        "activeInStep4",
    }
    profile_ids: list[str] = []
    source_tables: list[str] = []
    for index, profile in enumerate(profiles):
        if not isinstance(profile, Mapping):
            raise PortfolioInventoryError(f"profiles[{index}] must be an object")
        _require_keys(profile, expected_profile_keys, f"profiles[{index}]")
        profile_ids.append(
            _require_nonempty_string(profile["profileId"], f"profiles[{index}].profileId")
        )
        source_tables.append(
            _require_nonempty_string(profile["sourceTable"], f"profiles[{index}].sourceTable")
        )
        _require_nonempty_string(profile["subjectType"], f"profiles[{index}].subjectType")
        _require_unique_strings(profile["idColumns"], f"profiles[{index}].idColumns")
        _require_unique_strings(profile["textColumns"], f"profiles[{index}].textColumns")
        _require_unique_strings(
            profile["runtimeAllowedSchemes"],
            f"profiles[{index}].runtimeAllowedSchemes",
        )
        if profile["sourceMode"] not in {
            "atomic-record",
            "structured-children",
            "hierarchical-document",
        }:
            raise PortfolioInventoryError(
                f"profiles[{index}].sourceMode is not a supported source mode"
            )
        if not isinstance(profile["activeInStep4"], bool):
            raise PortfolioInventoryError(
                f"profiles[{index}].activeInStep4 must be boolean"
            )

    if len(set(profile_ids)) != 17:
        raise PortfolioInventoryError("profile snapshot contains duplicate profile IDs")
    if len(set(source_tables)) != 17:
        raise PortfolioInventoryError("profile snapshot contains duplicate source tables")
    active_count = sum(bool(profile["activeInStep4"]) for profile in profiles)
    if active_count != 16:
        raise PortfolioInventoryError(
            f"profile snapshot must contain 16 Step 4 active profiles, found {active_count}"
        )
    deferred = [
        profile["profileId"] for profile in profiles if not profile["activeInStep4"]
    ]
    if deferred != ["regulations-comment-v1"]:
        raise PortfolioInventoryError(
            "regulations-comment-v1 must be the one deferred Step 4 profile"
        )

    if source_path is not None:
        source_bytes = source_path.read_bytes()
        actual_sha256 = f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"
        if actual_sha256 != source["sha256"]:
            raise PortfolioInventoryError(
                "Spicy Regs source digest differs from the checked-in profile snapshot"
            )
        git_blob_bytes = f"blob {len(source_bytes)}\0".encode() + source_bytes
        actual_git_blob = hashlib.sha1(git_blob_bytes).hexdigest()
        if actual_git_blob != source["gitBlob"]:
            raise PortfolioInventoryError(
                "Spicy Regs Git blob differs from the checked-in profile snapshot"
            )
        extracted = extract_spicy_regs_profiles(source_path)
        if extracted != profiles:
            raise PortfolioInventoryError(
                "Spicy Regs SOURCE_PROFILES or STEP4_ACTIVE_SOURCE_TABLES "
                "differ from the checked-in profile snapshot"
            )


def validate_portfolio_input(
    snapshot: Mapping[str, Any],
    portfolio_input: Mapping[str, Any],
) -> None:
    """Validate RefSpec's typed roles, resource uses, facets, and gaps."""

    validate_profile_snapshot(snapshot)
    _require_keys(
        portfolio_input,
        {
            "format",
            "plan",
            "facetVocabulary",
            "useVocabulary",
            "resources",
            "profiles",
        },
        "portfolio input",
    )
    if portfolio_input["format"] != PORTFOLIO_INPUT_FORMAT:
        raise PortfolioInventoryError("unknown portfolio input format")

    plan = portfolio_input["plan"]
    if not isinstance(plan, Mapping):
        raise PortfolioInventoryError("portfolio plan pin must be an object")
    _require_keys(plan, {"path", "date", "batch"}, "portfolio plan pin")
    _require_nonempty_string(plan["path"], "plan.path")
    _require_nonempty_string(plan["date"], "plan.date")
    if plan["batch"] != 0:
        raise PortfolioInventoryError("portfolio input must identify Batch 0")

    facets = set(_require_unique_strings(portfolio_input["facetVocabulary"], "facetVocabulary"))
    if facets != CORE_FACETS:
        raise PortfolioInventoryError(
            "portfolio facet vocabulary must equal the RefSpec core facet set"
        )
    uses = set(_require_unique_strings(portfolio_input["useVocabulary"], "useVocabulary"))
    if uses != CONTROLLED_RESOURCE_USES:
        raise PortfolioInventoryError(
            "portfolio use vocabulary must contain all and only the Batch 0 uses"
        )

    resources = portfolio_input["resources"]
    if not isinstance(resources, list) or not resources:
        raise PortfolioInventoryError("portfolio resources must be a non-empty list")
    resource_ids: list[str] = []
    resource_keys = {
        "resourceId",
        "title",
        "resourceKind",
        "distributionStatus",
        "officialLocator",
        "identifierRepresentation",
        "versionRepresentation",
        "accessOrReproducibilityGap",
    }
    for index, resource in enumerate(resources):
        if not isinstance(resource, Mapping):
            raise PortfolioInventoryError(f"resources[{index}] must be an object")
        _require_keys(resource, resource_keys, f"resources[{index}]")
        resource_id = _require_nonempty_string(
            resource["resourceId"], f"resources[{index}].resourceId"
        )
        resource_ids.append(resource_id)
        _require_nonempty_string(resource["title"], f"resources[{index}].title")
        if resource["resourceKind"] not in RESOURCE_KINDS:
            raise PortfolioInventoryError(
                f"resources[{index}].resourceKind is not recognized"
            )
        if resource["distributionStatus"] not in DISTRIBUTION_STATUSES:
            raise PortfolioInventoryError(
                f"resources[{index}].distributionStatus is not recognized"
            )
        for field in (
            "officialLocator",
            "identifierRepresentation",
            "versionRepresentation",
            "accessOrReproducibilityGap",
        ):
            _require_nonempty_string(resource[field], f"resources[{index}].{field}")
    if len(resource_ids) != len(set(resource_ids)):
        raise PortfolioInventoryError("portfolio resources contain duplicate IDs")
    known_resource_ids = set(resource_ids)

    snapshot_by_id = {
        profile["profileId"]: profile for profile in snapshot["profiles"]
    }
    profiles = portfolio_input["profiles"]
    if not isinstance(profiles, list):
        raise PortfolioInventoryError("portfolio profiles must be a list")
    profile_keys = {
        "profileId",
        "recordRole",
        "recordKind",
        "sourceNativeFields",
        "candidateFacets",
        "subjectPolicy",
        "controlledResourceUses",
    }
    input_by_id: dict[str, Mapping[str, Any]] = {}
    referenced_resources: set[str] = set()
    for index, profile in enumerate(profiles):
        if not isinstance(profile, Mapping):
            raise PortfolioInventoryError(f"profiles[{index}] must be an object")
        _require_keys(profile, profile_keys, f"portfolio profiles[{index}]")
        profile_id = _require_nonempty_string(
            profile["profileId"], f"portfolio profiles[{index}].profileId"
        )
        if profile_id in input_by_id:
            raise PortfolioInventoryError(
                f"portfolio input repeats profile {profile_id}"
            )
        input_by_id[profile_id] = profile
        if profile["recordRole"] not in RECORD_ROLES:
            raise PortfolioInventoryError(
                f"{profile_id} has unknown record role {profile['recordRole']!r}"
            )
        _require_nonempty_string(profile["recordKind"], f"{profile_id}.recordKind")
        _require_unique_strings(
            profile["sourceNativeFields"], f"{profile_id}.sourceNativeFields"
        )
        if not isinstance(profile["candidateFacets"], list):
            raise PortfolioInventoryError(
                f"{profile_id}.candidateFacets must be a string list"
            )
        candidate_facets = set(profile["candidateFacets"])
        if not all(
            isinstance(facet, str) and facet for facet in profile["candidateFacets"]
        ):
            raise PortfolioInventoryError(
                f"{profile_id}.candidateFacets must contain non-empty strings"
            )
        if len(candidate_facets) != len(profile["candidateFacets"]):
            raise PortfolioInventoryError(
                f"{profile_id}.candidateFacets contains duplicates"
            )
        if not candidate_facets <= CORE_FACETS:
            raise PortfolioInventoryError(
                f"{profile_id}.candidateFacets contains unknown RefSpec facets"
            )

        subject_policy = profile["subjectPolicy"]
        if not isinstance(subject_policy, Mapping):
            raise PortfolioInventoryError(
                f"{profile_id}.subjectPolicy must be an object"
            )
        _require_keys(
            subject_policy,
            {"eligible", "primaryResourceIds", "gapStatus", "gap"},
            f"{profile_id}.subjectPolicy",
        )
        if not isinstance(subject_policy["eligible"], bool):
            raise PortfolioInventoryError(
                f"{profile_id}.subjectPolicy.eligible must be boolean"
            )
        primary_resources = subject_policy["primaryResourceIds"]
        if not isinstance(primary_resources, list) or not all(
            isinstance(resource_id, str) for resource_id in primary_resources
        ):
            raise PortfolioInventoryError(
                f"{profile_id}.subjectPolicy.primaryResourceIds must be a string list"
            )
        if len(primary_resources) != len(set(primary_resources)):
            raise PortfolioInventoryError(
                f"{profile_id}.subjectPolicy.primaryResourceIds contains duplicates"
            )
        unknown_primary = set(primary_resources) - known_resource_ids
        if unknown_primary:
            raise PortfolioInventoryError(
                f"{profile_id} references unknown primary resources "
                f"{sorted(unknown_primary)}"
            )
        if subject_policy["eligible"] and not primary_resources:
            raise PortfolioInventoryError(
                f"{profile_id} is subject eligible but has no explicit primary path"
            )
        if not subject_policy["eligible"] and primary_resources:
            raise PortfolioInventoryError(
                f"{profile_id} is not subject eligible but declares a primary path"
            )
        if subject_policy["gapStatus"] not in SUBJECT_GAP_STATUSES:
            raise PortfolioInventoryError(
                f"{profile_id}.subjectPolicy.gapStatus is not recognized"
            )
        _require_nonempty_string(
            subject_policy["gap"], f"{profile_id}.subjectPolicy.gap"
        )

        controlled_uses = profile["controlledResourceUses"]
        if not isinstance(controlled_uses, list) or not controlled_uses:
            raise PortfolioInventoryError(
                f"{profile_id} must declare controlled-resource uses"
            )
        seen_use_rows: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
        selectable_resources: set[str] = set()
        for use_index, use in enumerate(controlled_uses):
            if not isinstance(use, Mapping):
                raise PortfolioInventoryError(
                    f"{profile_id}.controlledResourceUses[{use_index}] "
                    "must be an object"
                )
            _require_keys(
                use,
                {"resourceId", "uses", "facets"},
                f"{profile_id}.controlledResourceUses[{use_index}]",
            )
            resource_id = _require_nonempty_string(
                use["resourceId"],
                f"{profile_id}.controlledResourceUses[{use_index}].resourceId",
            )
            if resource_id not in known_resource_ids:
                raise PortfolioInventoryError(
                    f"{profile_id} references unknown resource {resource_id}"
                )
            row_uses = set(
                _require_unique_strings(
                    use["uses"],
                    f"{profile_id}.controlledResourceUses[{use_index}].uses",
                )
            )
            if not row_uses <= CONTROLLED_RESOURCE_USES:
                raise PortfolioInventoryError(
                    f"{profile_id} uses an unknown controlled-resource role"
                )
            if "selectableSubject" in row_uses:
                selectable_resources.add(resource_id)
            row_facets = set(
                _require_unique_strings(
                    use["facets"],
                    f"{profile_id}.controlledResourceUses[{use_index}].facets",
                )
            )
            if not row_facets <= CORE_FACETS:
                raise PortfolioInventoryError(
                    f"{profile_id} resource use contains an unknown facet"
                )
            row_key = (
                resource_id,
                tuple(sorted(row_uses)),
                tuple(sorted(row_facets)),
            )
            if row_key in seen_use_rows:
                raise PortfolioInventoryError(
                    f"{profile_id} repeats a controlled-resource use row"
                )
            seen_use_rows.add(row_key)
            referenced_resources.add(resource_id)
        if not set(primary_resources) <= selectable_resources:
            raise PortfolioInventoryError(
                f"{profile_id} primary subject resources must be declared "
                "with selectableSubject use"
            )

    if set(input_by_id) != set(snapshot_by_id):
        missing = sorted(set(snapshot_by_id) - set(input_by_id))
        extra = sorted(set(input_by_id) - set(snapshot_by_id))
        raise PortfolioInventoryError(
            f"portfolio profile coverage differs; missing={missing}, extra={extra}"
        )
    unreferenced = known_resource_ids - referenced_resources
    if unreferenced:
        raise PortfolioInventoryError(
            f"portfolio resources have no active or deferred profile use: "
            f"{sorted(unreferenced)}"
        )

    role_counts = Counter(
        profile["recordRole"]
        for profile_id, profile in input_by_id.items()
        if snapshot_by_id[profile_id]["activeInStep4"]
    )
    if role_counts != Counter(
        {"document": 9, "observation": 1, "container": 3, "entity": 3}
    ):
        raise PortfolioInventoryError(
            f"active profile role counts differ from Batch 0: {dict(role_counts)}"
        )
    deferred = [
        profile
        for profile_id, profile in input_by_id.items()
        if not snapshot_by_id[profile_id]["activeInStep4"]
    ]
    if len(deferred) != 1 or deferred[0]["recordRole"] != "participation":
        raise PortfolioInventoryError(
            "the one deferred profile must have the participation role"
        )
    active_subject_eligible_count = sum(
        profile["subjectPolicy"]["eligible"]
        for profile_id, profile in input_by_id.items()
        if snapshot_by_id[profile_id]["activeInStep4"]
    )
    if active_subject_eligible_count != 10:
        raise PortfolioInventoryError(
            "exactly the ten active document or observation profiles must have "
            "a subject path"
        )

    for profile_id, profile in input_by_id.items():
        source_profile = snapshot_by_id[profile_id]
        active = source_profile["activeInStep4"]
        role = profile["recordRole"]
        eligible = profile["subjectPolicy"]["eligible"]
        if active and role in {"document", "observation"} and not eligible:
            raise PortfolioInventoryError(
                f"active document-like profile {profile_id} lacks a subject path"
            )
        if active and role in {"container", "entity"} and eligible:
            raise PortfolioInventoryError(
                f"non-document profile {profile_id} cannot be subject eligible"
            )
        if not active and profile["subjectPolicy"]["gapStatus"] != "deferred":
            raise PortfolioInventoryError(
                f"deferred profile {profile_id} must record a deferred subject policy"
            )


def build_portfolio_atlas(
    snapshot: Mapping[str, Any],
    portfolio_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Join the exact Spicy Regs snapshot to RefSpec's portfolio decisions."""

    validate_portfolio_input(snapshot, portfolio_input)
    source_by_id = {
        profile["profileId"]: profile for profile in snapshot["profiles"]
    }
    annotations_by_id = {
        profile["profileId"]: profile for profile in portfolio_input["profiles"]
    }
    joined_profiles = []
    for profile_id in sorted(source_by_id):
        source_profile = source_by_id[profile_id]
        annotation = annotations_by_id[profile_id]
        joined_profiles.append(
            {
                **source_profile,
                **annotation,
                "portfolioStatus": (
                    "active" if source_profile["activeInStep4"] else "deferred"
                ),
            }
        )

    active_profiles = [profile for profile in joined_profiles if profile["activeInStep4"]]
    role_counts = Counter(profile["recordRole"] for profile in active_profiles)
    documented_subject_gaps = sorted(
        profile["profileId"]
        for profile in joined_profiles
        if profile["subjectPolicy"]["gapStatus"] == "documented"
    )
    return {
        "format": PORTFOLIO_ATLAS_FORMAT,
        "generatedFrom": {
            "spicyRegsProfileSnapshotSha256": canonical_sha256(snapshot),
            "refspecPortfolioInputSha256": canonical_sha256(portfolio_input),
            "spicyRegsSource": dict(snapshot["source"]),
            "plan": dict(portfolio_input["plan"]),
        },
        "summary": {
            "profileCount": len(joined_profiles),
            "activeProfileCount": len(active_profiles),
            "deferredProfileCount": len(joined_profiles) - len(active_profiles),
            "activeDocumentOrObservationCount": sum(
                role_counts[role] for role in ("document", "observation")
            ),
            "activeRoleCounts": {
                role: role_counts.get(role, 0)
                for role in ("document", "observation", "container", "entity")
            },
            "subjectEligibleProfileCount": sum(
                profile["subjectPolicy"]["eligible"] for profile in active_profiles
            ),
            "documentedSubjectGapProfiles": documented_subject_gaps,
            "resourceCount": len(portfolio_input["resources"]),
        },
        "facetVocabulary": sorted(portfolio_input["facetVocabulary"]),
        "useVocabulary": sorted(portfolio_input["useVocabulary"]),
        "resources": sorted(
            (dict(resource) for resource in portfolio_input["resources"]),
            key=lambda resource: resource["resourceId"],
        ),
        "profiles": joined_profiles,
    }


def validate_generated_atlas(
    atlas: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    portfolio_input: Mapping[str, Any],
) -> None:
    """Fail unless an atlas exactly matches deterministic regeneration."""

    expected = build_portfolio_atlas(snapshot, portfolio_input)
    if atlas != expected:
        raise PortfolioInventoryError(
            "checked-in controlled-resource atlas differs from deterministic generation"
        )

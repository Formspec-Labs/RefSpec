#!/usr/bin/env python3
"""Generate or verify compact Atlas 3.0 coverage of the RefSpec registry."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec.registry.infrastructure.semantic_foundation import SEMANTIC_RINGS

CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"
INDEX = ROOT / "portfolio" / "atlas-index-v0.json"
PROFILES = ROOT / "bindings" / "atlas" / "3.0" / "registry-resource-profiles.json"
OUTPUT = ROOT / "bindings" / "atlas" / "3.0" / "tests" / "registry-coverage.json"

PROFILE_FORMAT = "refspec-atlas-registry-resource-profiles/3.0"
COVERAGE_FORMAT = "refspec-atlas-registry-coverage/3.0"
ATLAS_NAMESPACE = "https://refspec.org/ns/atlas/v3#"
SKOS_NAMESPACE = "http://www.w3.org/2004/02/skos/core#"
SKOSXL_LABEL = "http://www.w3.org/2008/05/skos-xl#Label"

EXPECTED_PROFILE_KINDS = {
    "conceptScheme": frozenset(
        {
            "historicalVocabulary",
            "mappingReference",
            "sourceAssignedVocabulary",
            "subjectVocabulary",
        }
    ),
    "codeScheme": frozenset({"classification", "codeList"}),
    "identifierScheme": frozenset({"identifierAuthority"}),
    "structureScheme": frozenset({"structuralSchema"}),
    "resourceCollection": frozenset({"resourceFamily"}),
}
RELATION_POLICY_RINGS = tuple(sorted(SEMANTIC_RINGS))
RELATION_ASSERTION_TYPES = (
    "MappingAssertion",
    "NativeRelationAssertion",
    "SourceAssignment",
)
RING_ENTRY_CLASSES = {
    "entity": ATLAS_NAMESPACE + "EntityResource",
    "legalIdentity": ATLAS_NAMESPACE + "LegalIdentityResource",
    "subject": ATLAS_NAMESPACE + "SubjectConcept",
    "value": ATLAS_NAMESPACE + "ValueResource",
}
assert RING_ENTRY_CLASSES.keys() == SEMANTIC_RINGS, (
    "RING_ENTRY_CLASSES must cover exactly the canonical semantic rings"
)
ATLAS_ENTRY_CLASS_NAMES = frozenset(
    {
        "AtlasRelease",
        "AtlasResource",
        "CrossRingRelationAssertion",
        "DerivedRelation",
        "EntityResource",
        "Identifier",
        "LegalIdentityResource",
        "MappingAssertion",
        "NativeRelationAssertion",
        "ProjectedRelation",
        "RelationAssertion",
        "ResourceScheme",
        "SkosMappingAssertion",
        "SourceAssignment",
        "SourceRecord",
        "SubjectConcept",
        "ValueResource",
    }
)
ENTRY_CLASSES = frozenset({ATLAS_NAMESPACE + value for value in ATLAS_ENTRY_CLASS_NAMES} | {SKOSXL_LABEL})
DESCRIPTOR_BEHAVIORS = frozenset(
    {"alwaysDescriptorOnly", "descriptorOnlyUntilExactRelease"}
)
ALLOWED_SKOS_SUBJECT_PREDICATES = {
    "MappingAssertion": frozenset(
        {
            SKOS_NAMESPACE + "broadMatch",
            SKOS_NAMESPACE + "closeMatch",
            SKOS_NAMESPACE + "exactMatch",
            SKOS_NAMESPACE + "narrowMatch",
            SKOS_NAMESPACE + "relatedMatch",
        }
    ),
    "NativeRelationAssertion": frozenset(
        {
            SKOS_NAMESPACE + "broader",
            SKOS_NAMESPACE + "narrower",
            SKOS_NAMESPACE + "related",
        }
    ),
    "SourceAssignment": frozenset(),
}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


class RegistryCoverageError(ValueError):
    """Raised when the profile map or registry coverage is incomplete."""


def _require_keys(value: Mapping[str, Any], expected: set[str], location: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RegistryCoverageError(
            f"{location} keys differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RegistryCoverageError(f"{location} must be a non-empty trimmed string")
    return value


def _digest(value: Any, location: str) -> str:
    result = _string(value, location)
    if not _SHA256.fullmatch(result):
        raise RegistryCoverageError(f"{location} must be a lowercase SHA-256 digest")
    return result


def _sequence(value: Any, location: str, *, allow_empty: bool = False) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RegistryCoverageError(f"{location} must be a list")
    if not allow_empty and not value:
        raise RegistryCoverageError(f"{location} must not be empty")
    return value


def _unique_sorted_strings(value: Any, location: str, *, allow_empty: bool = False) -> list[str]:
    items = [
        _string(item, f"{location}[{index}]")
        for index, item in enumerate(_sequence(value, location, allow_empty=allow_empty))
    ]
    if len(items) != len(set(items)):
        raise RegistryCoverageError(f"{location} must not contain duplicates")
    if items != sorted(items):
        raise RegistryCoverageError(f"{location} must be sorted")
    return items


def _unique_sorted_iris(value: Any, location: str) -> list[str]:
    items = _unique_sorted_strings(value, location)
    for index, item in enumerate(items):
        if not _ABSOLUTE_IRI.fullmatch(item):
            raise RegistryCoverageError(f"{location}[{index}] must be an absolute IRI")
    return items


def _profile_digest(profile_map: Mapping[str, Any]) -> str:
    from refspec.binding import canonical_sha256

    return canonical_sha256({key: value for key, value in profile_map.items() if key != "profileDigest"})


def _validate_relation_policies(profile_map: Mapping[str, Any]) -> None:
    rows = _sequence(profile_map["relationPolicies"], "profile map.relationPolicies")
    policy_rings: list[str] = []
    predicate_locations: dict[str, str] = {}

    for position, value in enumerate(rows):
        location = f"profile map.relationPolicies[{position}]"
        if not isinstance(value, Mapping):
            raise RegistryCoverageError(f"{location} must be an object")
        _require_keys(
            value,
            {"assertionPredicates", "resourceClass", "semanticRing"},
            location,
        )

        ring = _string(value["semanticRing"], f"{location}.semanticRing")
        if ring not in SEMANTIC_RINGS:
            raise RegistryCoverageError(f"{location}.semanticRing is unsupported: {ring!r}")
        policy_rings.append(ring)

        resource_class = _string(value["resourceClass"], f"{location}.resourceClass")
        if not _ABSOLUTE_IRI.fullmatch(resource_class):
            raise RegistryCoverageError(f"{location}.resourceClass must be an absolute IRI")
        expected_resource_class = RING_ENTRY_CLASSES[ring]
        if resource_class != expected_resource_class:
            raise RegistryCoverageError(
                f"{location}.resourceClass must be {expected_resource_class!r} for ring {ring!r}"
            )

        assertion_predicates = value["assertionPredicates"]
        if not isinstance(assertion_predicates, Mapping):
            raise RegistryCoverageError(f"{location}.assertionPredicates must be an object")
        _require_keys(
            assertion_predicates,
            set(RELATION_ASSERTION_TYPES),
            f"{location}.assertionPredicates",
        )
        for assertion_type in RELATION_ASSERTION_TYPES:
            predicate_location = f"{location}.assertionPredicates.{assertion_type}"
            predicates = _unique_sorted_iris(
                assertion_predicates[assertion_type],
                predicate_location,
            )
            for predicate in predicates:
                atlas_predicate = predicate.startswith(ATLAS_NAMESPACE) and (
                    predicate != ATLAS_NAMESPACE
                )
                allowed_skos_predicate = (
                    ring == "subject"
                    and predicate in ALLOWED_SKOS_SUBJECT_PREDICATES[assertion_type]
                )
                if not atlas_predicate and not allowed_skos_predicate:
                    raise RegistryCoverageError(
                        f"{predicate_location} contains unsupported predicate {predicate!r}"
                    )
                prior_location = predicate_locations.get(predicate)
                if prior_location is not None:
                    raise RegistryCoverageError(
                        f"relation predicate {predicate!r} is duplicated in "
                        f"{prior_location} and {predicate_location}"
                    )
                predicate_locations[predicate] = predicate_location

    if policy_rings != list(RELATION_POLICY_RINGS):
        raise RegistryCoverageError(
            "profile map.relationPolicies must contain the four semantic rings once "
            f"in sorted order; expected={list(RELATION_POLICY_RINGS)}, actual={policy_rings}"
        )


def _validate_cross_ring_relation_policies(profile_map: Mapping[str, Any]) -> None:
    rows = _sequence(
        profile_map["crossRingRelationPolicies"],
        "profile map.crossRingRelationPolicies",
    )
    if len(rows) != 3:
        raise RegistryCoverageError(
            "profile map.crossRingRelationPolicies must contain exactly three rows"
        )
    expected = {
        ("entity", "legalIdentity"): frozenset(
            {ATLAS_NAMESPACE + "referencesLegalIdentity"}
        ),
        ("entity", "subject"): frozenset({ATLAS_NAMESPACE + "hasIndexedSubject"}),
        ("legalIdentity", "subject"): frozenset(
            {ATLAS_NAMESPACE + "hasIndexedSubject"}
        ),
    }
    observed: dict[tuple[str, str], frozenset[str]] = {}
    observed_order: list[tuple[str, str]] = []
    same_ring_predicates = {
        predicate
        for policy in profile_map["relationPolicies"]
        for predicates in policy["assertionPredicates"].values()
        for predicate in predicates
    }
    for position, value in enumerate(rows):
        location = f"profile map.crossRingRelationPolicies[{position}]"
        if not isinstance(value, Mapping):
            raise RegistryCoverageError(f"{location} must be an object")
        _require_keys(
            value,
            {
                "predicates",
                "sourceResourceClass",
                "sourceRing",
                "targetResourceClass",
                "targetRing",
            },
            location,
        )
        source_ring = _string(value["sourceRing"], f"{location}.sourceRing")
        target_ring = _string(value["targetRing"], f"{location}.targetRing")
        if source_ring not in SEMANTIC_RINGS or target_ring not in SEMANTIC_RINGS:
            raise RegistryCoverageError(f"{location} contains an unsupported ring")
        if source_ring == target_ring:
            raise RegistryCoverageError(f"{location} does not cross semantic rings")
        if value["sourceResourceClass"] != RING_ENTRY_CLASSES[source_ring]:
            raise RegistryCoverageError(
                f"{location}.sourceResourceClass does not match {source_ring!r}"
            )
        if value["targetResourceClass"] != RING_ENTRY_CLASSES[target_ring]:
            raise RegistryCoverageError(
                f"{location}.targetResourceClass does not match {target_ring!r}"
            )
        pair = (source_ring, target_ring)
        observed_order.append(pair)
        if pair in observed:
            raise RegistryCoverageError(f"duplicate cross-ring policy pair {pair!r}")
        predicates = frozenset(
            _unique_sorted_iris(value["predicates"], f"{location}.predicates")
        )
        if len(predicates) != 1:
            raise RegistryCoverageError(
                f"{location}.predicates must contain exactly one predicate"
            )
        if any(not predicate.startswith(ATLAS_NAMESPACE) for predicate in predicates):
            raise RegistryCoverageError(
                f"{location}.predicates must contain only Atlas predicates"
            )
        overlap = predicates & same_ring_predicates
        if overlap:
            raise RegistryCoverageError(
                f"{location}.predicates overlap a same-ring policy: {sorted(overlap)}"
            )
        observed[pair] = predicates
    if observed_order != sorted(observed_order) or observed != expected:
        raise RegistryCoverageError(
            "profile map.crossRingRelationPolicies differ from the closed Atlas 3.0 matrix"
        )


def validate_profile_map(
    profile_map: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Validate the closed five-profile map and return resource-kind lookup rows."""

    _require_keys(
        profile_map,
        {
            "crossRingRelationPolicies",
            "format",
            "namespace",
            "profileDigest",
            "profiles",
            "relationPolicies",
            "schemaVersion",
        },
        "profile map",
    )
    if profile_map["format"] != PROFILE_FORMAT:
        raise RegistryCoverageError(f"profile map format must be {PROFILE_FORMAT!r}")
    if profile_map["schemaVersion"] != "3.0":
        raise RegistryCoverageError("profile map schemaVersion must be '3.0'")
    if profile_map["namespace"] != ATLAS_NAMESPACE:
        raise RegistryCoverageError(f"profile map namespace must be {ATLAS_NAMESPACE!r}")
    claimed_digest = _digest(profile_map["profileDigest"], "profile map.profileDigest")
    actual_digest = _profile_digest(profile_map)
    if claimed_digest != actual_digest:
        raise RegistryCoverageError(
            f"profile map digest differs: claimed={claimed_digest}, actual={actual_digest}"
        )

    _validate_relation_policies(profile_map)
    _validate_cross_ring_relation_policies(profile_map)

    profile_rows = _sequence(profile_map["profiles"], "profile map.profiles")
    by_name: dict[str, Mapping[str, Any]] = {}
    by_kind: dict[str, Mapping[str, Any]] = {}
    profile_names: list[str] = []
    for position, value in enumerate(profile_rows):
        location = f"profile map.profiles[{position}]"
        if not isinstance(value, Mapping):
            raise RegistryCoverageError(f"{location} must be an object")
        _require_keys(
            value,
            {
                "applicableEntryClasses",
                "applicableSemanticRings",
                "descriptorBehavior",
                "profile",
                "resourceKinds",
            },
            location,
        )
        name = _string(value["profile"], f"{location}.profile")
        if name in by_name:
            raise RegistryCoverageError(f"duplicate profile {name!r}")
        if name not in EXPECTED_PROFILE_KINDS:
            raise RegistryCoverageError(f"unsupported profile {name!r}")
        profile_names.append(name)

        kinds = _unique_sorted_strings(value["resourceKinds"], f"{location}.resourceKinds")
        if set(kinds) != EXPECTED_PROFILE_KINDS[name]:
            raise RegistryCoverageError(
                f"{location}.resourceKinds differ for {name}; "
                f"expected={sorted(EXPECTED_PROFILE_KINDS[name])}, actual={kinds}"
            )
        for kind in kinds:
            if kind in by_kind:
                raise RegistryCoverageError(
                    f"duplicate resourceKind {kind!r} in profiles "
                    f"{by_kind[kind]['profile']!r} and {name!r}"
                )
            by_kind[kind] = value

        rings = _unique_sorted_strings(
            value["applicableSemanticRings"],
            f"{location}.applicableSemanticRings",
            allow_empty=True,
        )
        unsupported_rings = set(rings) - SEMANTIC_RINGS
        if unsupported_rings:
            raise RegistryCoverageError(
                f"{location}.applicableSemanticRings are unsupported: {sorted(unsupported_rings)}"
            )
        entry_classes = _unique_sorted_strings(
            value["applicableEntryClasses"],
            f"{location}.applicableEntryClasses",
        )
        unsupported_classes = set(entry_classes) - ENTRY_CLASSES
        if unsupported_classes:
            raise RegistryCoverageError(
                f"{location}.applicableEntryClasses are unsupported: {sorted(unsupported_classes)}"
            )
        missing_ring_classes = {RING_ENTRY_CLASSES[ring] for ring in rings} - set(entry_classes)
        if missing_ring_classes:
            raise RegistryCoverageError(
                f"{location}.applicableEntryClasses omit ring classes: {sorted(missing_ring_classes)}"
            )
        if ATLAS_NAMESPACE + "ResourceScheme" not in entry_classes:
            raise RegistryCoverageError(f"{location} must include the ResourceScheme entry class")

        behavior = _string(value["descriptorBehavior"], f"{location}.descriptorBehavior")
        if behavior not in DESCRIPTOR_BEHAVIORS:
            raise RegistryCoverageError(f"{location}.descriptorBehavior is unsupported: {behavior!r}")
        if name == "resourceCollection":
            if rings or behavior != "alwaysDescriptorOnly":
                raise RegistryCoverageError(
                    "resourceCollection must be ringless and alwaysDescriptorOnly"
                )
        elif behavior != "descriptorOnlyUntilExactRelease":
            raise RegistryCoverageError(
                f"{name} must be descriptorOnlyUntilExactRelease"
            )
        by_name[name] = value

    if profile_names != sorted(EXPECTED_PROFILE_KINDS):
        raise RegistryCoverageError(
            "profile map.profiles must contain the five profiles once in sorted order"
        )

    resources = _sequence(catalog.get("resources"), "resource catalog.resources")
    catalog_kinds: set[str] = set()
    for position, resource in enumerate(resources):
        if not isinstance(resource, Mapping):
            raise RegistryCoverageError(f"resource catalog.resources[{position}] must be an object")
        catalog_kinds.add(
            _string(resource.get("resourceKind"), f"resource catalog.resources[{position}].resourceKind")
        )
    mapped_kinds = set(by_kind)
    if catalog_kinds != mapped_kinds:
        raise RegistryCoverageError(
            "catalog resourceKind coverage differs; "
            f"unmapped={sorted(catalog_kinds - mapped_kinds)}, "
            f"stale={sorted(mapped_kinds - catalog_kinds)}"
        )
    return by_kind


def _registry_modules(repository_root: Path) -> set[str]:
    registry_root = repository_root / "src" / "refspec" / "registry"
    if not registry_root.is_dir():
        raise RegistryCoverageError(f"registry directory does not exist: {registry_root}")
    modules: set[str] = set()
    for path in registry_root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(repository_root / "src").with_suffix("")
        modules.add(".".join(relative.parts))
    return modules


def _set_digest(values: set[str] | list[str]) -> str:
    from refspec.binding import canonical_sha256

    return canonical_sha256(sorted(values))


def _counter(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def render_json(value: Any) -> str:
    """Render one canonical compact JSON document with a terminal newline."""

    from refspec.binding import canonical_json_bytes

    return canonical_json_bytes(value).decode("utf-8") + "\n"


def build_registry_coverage(
    catalog: Mapping[str, Any],
    index: Mapping[str, Any],
    profile_map: Mapping[str, Any],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Build a compact proof that the catalog, index, and live registry are covered."""

    from refspec.binding import canonical_sha256

    by_kind = validate_profile_map(profile_map, catalog)
    catalog_digest = _digest(catalog.get("catalogDigest"), "resource catalog.catalogDigest")
    index_digest = _digest(index.get("indexDigest"), "atlas index.indexDigest")
    if index.get("resourceCatalogDigest") != catalog_digest:
        raise RegistryCoverageError("atlas index does not pin the supplied resource catalog digest")

    resources = _sequence(catalog.get("resources"), "resource catalog.resources")
    resource_by_id: dict[str, Mapping[str, Any]] = {}
    resource_profile: dict[str, str] = {}
    resource_kinds: list[str] = []
    for position, resource in enumerate(resources):
        location = f"resource catalog.resources[{position}]"
        if not isinstance(resource, Mapping):
            raise RegistryCoverageError(f"{location} must be an object")
        resource_id = _string(resource.get("resourceId"), f"{location}.resourceId")
        if resource_id in resource_by_id:
            raise RegistryCoverageError(f"duplicate catalog resourceId {resource_id!r}")
        kind = _string(resource.get("resourceKind"), f"{location}.resourceKind")
        profile = by_kind.get(kind)
        if profile is None:
            raise RegistryCoverageError(f"unmapped catalog resourceKind {kind!r}")
        resource_by_id[resource_id] = resource
        resource_profile[resource_id] = str(profile["profile"])
        resource_kinds.append(kind)

    live_registry_modules = _registry_modules(repository_root)
    implementation_modules = set(
        _unique_sorted_strings(index.get("implementationModules"), "atlas index.implementationModules")
    )
    unknown_implementation_modules = implementation_modules - live_registry_modules
    if unknown_implementation_modules:
        raise RegistryCoverageError(
            "atlas index implementationModules do not name current registry modules: "
            f"{sorted(unknown_implementation_modules)}"
        )

    rows = _sequence(index.get("rows"), "atlas index.rows")
    source_modules: set[str] = set()
    indexed_resources: set[str] = set()
    indexed_rings: set[str] = set()
    release_ready_resources: set[str] = set()
    placement_identities: list[str] = []
    profile_rows: dict[str, list[Mapping[str, Any]]] = {
        name: [] for name in sorted(EXPECTED_PROFILE_KINDS)
    }
    for position, row in enumerate(rows):
        location = f"atlas index.rows[{position}]"
        if not isinstance(row, Mapping):
            raise RegistryCoverageError(f"{location} must be an object")
        resource_id = _string(row.get("resourceId"), f"{location}.resourceId")
        if resource_id not in resource_by_id:
            raise RegistryCoverageError(
                f"{location}.resourceId {resource_id!r} is not present in the resource catalog"
            )
        source_module = _string(row.get("sourceModule"), f"{location}.sourceModule")
        if source_module not in live_registry_modules:
            raise RegistryCoverageError(
                f"{location}.sourceModule {source_module!r} does not name a current registry module"
            )
        if source_module in implementation_modules:
            raise RegistryCoverageError(
                f"{location}.sourceModule {source_module!r} is also an implementation module"
            )
        ring = _string(row.get("semanticRing"), f"{location}.semanticRing")
        if ring not in SEMANTIC_RINGS:
            raise RegistryCoverageError(f"{location}.semanticRing is unsupported: {ring!r}")
        profile_name = resource_profile[resource_id]
        profile = next(
            value for value in profile_map["profiles"] if value["profile"] == profile_name
        )
        if ring not in profile["applicableSemanticRings"]:
            raise RegistryCoverageError(
                f"{location} ring {ring!r} is not covered by profile {profile_name!r}"
            )
        if RING_ENTRY_CLASSES[ring] not in profile["applicableEntryClasses"]:
            raise RegistryCoverageError(
                f"{location} ring entry class is not covered by profile {profile_name!r}"
            )

        row_id = _string(row.get("rowId"), f"{location}.rowId")
        placement_identities.append(
            f"{row_id}\u001f{resource_id}\u001f{source_module}\u001f{ring}"
        )
        source_modules.add(source_module)
        indexed_resources.add(resource_id)
        indexed_rings.add(ring)
        profile_rows[profile_name].append(row)
        if row.get("release") is not None:
            release_ready_resources.add(resource_id)

    overlap = source_modules & implementation_modules
    if overlap:
        raise RegistryCoverageError(
            f"registry modules are both source and implementation modules: {sorted(overlap)}"
        )
    indexed_module_inventory = source_modules | implementation_modules
    if indexed_module_inventory != live_registry_modules:
        raise RegistryCoverageError(
            "atlas index module coverage differs from the live registry; "
            f"uncovered={sorted(live_registry_modules - indexed_module_inventory)}, "
            f"unknown={sorted(indexed_module_inventory - live_registry_modules)}"
        )

    catalog_resources = set(resource_by_id)
    catalog_only_descriptors = catalog_resources - indexed_resources
    indexed_without_release = indexed_resources - release_ready_resources
    profile_summary: dict[str, dict[str, Any]] = {}
    for profile_name in sorted(EXPECTED_PROFILE_KINDS):
        profile_resource_ids = {
            resource_id
            for resource_id, assigned_profile in resource_profile.items()
            if assigned_profile == profile_name
        }
        profile_indexed = profile_resource_ids & indexed_resources
        rows_for_profile = profile_rows[profile_name]
        profile_summary[profile_name] = {
            "catalogOnlyDescriptorCount": len(profile_resource_ids & catalog_only_descriptors),
            "catalogResourceCount": len(profile_resource_ids),
            "indexedResourceCount": len(profile_indexed),
            "indexedRowCount": len(rows_for_profile),
            "indexedWithoutExactReleaseCount": len(profile_indexed & indexed_without_release),
            "releaseReadyIndexedResourceCount": len(profile_indexed & release_ready_resources),
            "semanticRingCounts": _counter([str(row["semanticRing"]) for row in rows_for_profile]),
        }

    report: dict[str, Any] = {
        "format": COVERAGE_FORMAT,
        "inputs": {
            "atlasIndexDigest": index_digest,
            "registryResourceProfilesDigest": _digest(
                profile_map.get("profileDigest"), "profile map.profileDigest"
            ),
            "resourceCatalogDigest": catalog_digest,
        },
        "profiles": profile_summary,
        "schemaVersion": "3.0",
        "setDigests": {
            "catalogOnlyDescriptorIds": _set_digest(catalog_only_descriptors),
            "catalogResourceIds": _set_digest(catalog_resources),
            "implementationModules": _set_digest(implementation_modules),
            "indexedPlacementIdentities": _set_digest(placement_identities),
            "indexedResourceIds": _set_digest(indexed_resources),
            "indexedSemanticRings": _set_digest(indexed_rings),
            "indexedWithoutExactReleaseIds": _set_digest(indexed_without_release),
            "registryModules": _set_digest(live_registry_modules),
            "releaseReadyIndexedResourceIds": _set_digest(release_ready_resources),
            "sourceModules": _set_digest(source_modules),
        },
        "summary": {
            "atlasIndexRowCount": len(rows),
            "catalogOnlyDescriptorCount": len(catalog_only_descriptors),
            "catalogResourceCount": len(catalog_resources),
            "implementationModuleCount": len(implementation_modules),
            "indexedResourceCount": len(indexed_resources),
            "indexedWithoutExactReleaseCount": len(indexed_without_release),
            "registryModuleCount": len(live_registry_modules),
            "releaseReadyIndexedResourceCount": len(release_ready_resources),
            "resourceKindCounts": _counter(resource_kinds),
            "sourceModuleCount": len(source_modules),
        },
        "unsupported": {
            "modules": [],
            "resourceKinds": [],
            "resources": [],
        },
    }
    report["coverageDigest"] = canonical_sha256(report)
    return report


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the checked report (default)")
    mode.add_argument("--write", action="store_true", help="write the generated report")
    return parser.parse_args()


def main() -> int:
    from refspec.resource_catalog import load_json

    args = _arguments()
    try:
        report = build_registry_coverage(
            load_json(CATALOG),
            load_json(INDEX),
            load_json(PROFILES),
            repository_root=ROOT,
        )
        generated = render_json(report)
        if args.write:
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT.write_text(generated, encoding="utf-8")
            print(f"wrote {OUTPUT.relative_to(ROOT)}")
            return 0
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != generated:
            raise RegistryCoverageError(
                "checked registry coverage differs from generation; run "
                "tools/generate_atlas_v3_registry_coverage.py --write"
            )
        summary = report["summary"]
        print(
            "Atlas 3.0 registry coverage is current: "
            f"{summary['catalogResourceCount']} resources, "
            f"{summary['registryModuleCount']} modules, "
            f"{summary['atlasIndexRowCount']} indexed placements"
        )
        return 0
    except (RegistryCoverageError, OSError, ValueError) as error:
        print(f"Atlas 3.0 registry coverage error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

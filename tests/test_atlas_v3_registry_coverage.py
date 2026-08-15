from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "generate_atlas_v3_registry_coverage.py"
CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"
INDEX = ROOT / "portfolio" / "atlas-index-v0.json"
PROFILES = ROOT / "bindings" / "atlas" / "3.1" / "registry-resource-profiles.json"
REPORT = ROOT / "bindings" / "atlas" / "3.1" / "tests" / "registry-coverage.json"

SPEC = importlib.util.spec_from_file_location("generate_atlas_v3_registry_coverage", TOOL)
assert SPEC is not None and SPEC.loader is not None
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


def _inputs() -> tuple[dict, dict, dict]:
    from refspec.resource_catalog import load_json

    return load_json(CATALOG), load_json(INDEX), load_json(PROFILES)


def _resign(profile_map: dict) -> None:
    profile_map["profileDigest"] = coverage._profile_digest(profile_map)


def test_checked_registry_coverage_is_exact_and_compact() -> None:
    from refspec.binding import canonical_json_bytes
    from refspec.resource_catalog import load_json

    catalog, index, profiles = _inputs()
    generated = coverage.build_registry_coverage(
        catalog,
        index,
        profiles,
        repository_root=ROOT,
    )

    assert REPORT.read_text(encoding="utf-8") == coverage.render_json(generated)
    assert PROFILES.read_bytes() == canonical_json_bytes(profiles) + b"\n"
    assert load_json(REPORT) == generated
    assert generated["summary"] == {
        "atlasIndexRowCount": 82,
        "catalogOnlyDescriptorCount": 18,
        "catalogResourceCount": 87,
        "implementationModuleCount": 25,
        "indexedResourceCount": 69,
        "indexedWithoutExactReleaseCount": 64,
        "registryModuleCount": 78,
        "releaseReadyIndexedResourceCount": 5,
        # REF-033 ring corrections move three catalog kinds: the LDA general
        # issue codes and the NASA technology taxonomy are code lists (the
        # readers' own text), and the GNIS file layout is publisher-written
        # structure, not an identifier authority. REF-034 retires the AGROVOC
        # and NALT rows and the closed EPA row (mappingReference 12 -> 10,
        # subjectVocabulary 7 -> 6) and adds the GAO Form 41217 code list
        # (codeList 25 -> 26); three registry modules land with index rows
        # (75 -> 78, source modules 50 -> 53).
        "resourceKindCounts": {
            "classification": 5,
            "codeList": 26,
            "historicalVocabulary": 1,
            "identifierAuthority": 20,
            "mappingReference": 10,
            "resourceFamily": 1,
            "sourceAssignedVocabulary": 8,
            "structuralSchema": 10,
            "subjectVocabulary": 6,
        },
        "sourceModuleCount": 53,
    }
    assert all(values == [] for values in generated["unsupported"].values())


def test_profile_map_rejects_an_unmapped_catalog_kind() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(catalog)
    changed["resources"][0]["resourceKind"] = "newRegistryShape"

    with pytest.raises(coverage.RegistryCoverageError, match="unmapped=.*newRegistryShape"):
        coverage.validate_profile_map(profiles, changed)


def test_coverage_rejects_an_unknown_indexed_resource() -> None:
    catalog, index, profiles = _inputs()
    changed = copy.deepcopy(index)
    changed["rows"][0]["resourceId"] = "not-in-the-resource-catalog"

    with pytest.raises(coverage.RegistryCoverageError, match="not present in the resource catalog"):
        coverage.build_registry_coverage(
            catalog,
            changed,
            profiles,
            repository_root=ROOT,
        )


def test_coverage_rejects_an_unknown_indexed_source_module() -> None:
    catalog, index, profiles = _inputs()
    changed = copy.deepcopy(index)
    changed["rows"][0]["sourceModule"] = "refspec.registry.not_a_real_module"

    with pytest.raises(coverage.RegistryCoverageError, match="does not name a current registry module"):
        coverage.build_registry_coverage(
            catalog,
            changed,
            profiles,
            repository_root=ROOT,
        )


def test_profile_map_rejects_duplicate_resource_kind_coverage() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["profiles"][1]["resourceKinds"].append("subjectVocabulary")
    changed["profileDigest"] = coverage._profile_digest(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="must not contain duplicates"):
        coverage.validate_profile_map(changed, catalog)


def test_profile_map_requires_relation_policies() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    del changed["relationPolicies"]

    with pytest.raises(coverage.RegistryCoverageError, match=r"missing=.*relationPolicies"):
        coverage.validate_profile_map(changed, catalog)


def test_cross_ring_relation_policy_is_the_closed_directed_matrix() -> None:
    catalog, _, profiles = _inputs()

    coverage.validate_profile_map(profiles, catalog)

    assert {
        (row["sourceRing"], row["targetRing"], tuple(row["predicates"]))
        for row in profiles["crossRingRelationPolicies"]
    } == {
        (
            "entity",
            "legalIdentity",
            (coverage.ATLAS_NAMESPACE + "referencesLegalIdentity",),
        ),
        (
            "entity",
            "subject",
            (coverage.ATLAS_NAMESPACE + "hasIndexedSubject",),
        ),
        (
            "legalIdentity",
            "subject",
            (coverage.ATLAS_NAMESPACE + "hasIndexedSubject",),
        ),
    }


def test_cross_ring_relation_policy_rejects_reversal_and_skos_predicates() -> None:
    catalog, _, profiles = _inputs()
    reversed_pair = copy.deepcopy(profiles)
    row = reversed_pair["crossRingRelationPolicies"][1]
    row["sourceRing"], row["targetRing"] = row["targetRing"], row["sourceRing"]
    row["sourceResourceClass"], row["targetResourceClass"] = (
        row["targetResourceClass"],
        row["sourceResourceClass"],
    )
    _resign(reversed_pair)

    with pytest.raises(coverage.RegistryCoverageError, match="closed Atlas 3.1 matrix"):
        coverage.validate_profile_map(reversed_pair, catalog)

    skos_predicate = copy.deepcopy(profiles)
    skos_predicate["crossRingRelationPolicies"][0]["predicates"] = [
        coverage.SKOS_NAMESPACE + "related"
    ]
    _resign(skos_predicate)

    with pytest.raises(coverage.RegistryCoverageError, match="only Atlas predicates"):
        coverage.validate_profile_map(skos_predicate, catalog)


def test_relation_policies_require_four_sorted_ring_rows() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0], changed["relationPolicies"][1] = (
        changed["relationPolicies"][1],
        changed["relationPolicies"][0],
    )
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="four semantic rings once"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_rows_have_closed_keys() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["unexpected"] = True
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match=r"extra=.*unexpected"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_assertion_predicates_have_closed_keys() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    del changed["relationPolicies"][0]["assertionPredicates"]["SourceAssignment"]
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match=r"missing=.*SourceAssignment"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_predicate_lists_must_not_be_empty() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["assertionPredicates"]["MappingAssertion"] = []
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="must not be empty"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_predicate_lists_must_be_unique_and_sorted() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    predicates = changed["relationPolicies"][0]["assertionPredicates"][
        "NativeRelationAssertion"
    ]
    predicates.append(predicates[0])
    predicates.sort()
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="must not contain duplicates"):
        coverage.validate_profile_map(changed, catalog)

    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["assertionPredicates"][
        "NativeRelationAssertion"
    ].reverse()
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="must be sorted"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_predicates_must_be_absolute_iris() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["assertionPredicates"]["MappingAssertion"] = [
        "sameEntityAs"
    ]
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="must be an absolute IRI"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_resource_class_must_match_its_ring() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["resourceClass"] = (
        coverage.ATLAS_NAMESPACE + "ValueResource"
    )
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="for ring 'entity'"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_rejects_predicates_outside_the_allowed_namespaces() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["assertionPredicates"]["MappingAssertion"] = [
        "https://example.org/sameEntityAs"
    ]
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="unsupported predicate"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_allows_skos_predicates_only_in_the_subject_cell() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    changed["relationPolicies"][0]["assertionPredicates"]["MappingAssertion"] = [
        coverage.SKOS_NAMESPACE + "exactMatch"
    ]
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="unsupported predicate"):
        coverage.validate_profile_map(changed, catalog)


def test_relation_policy_rejects_a_predicate_assigned_to_two_cells() -> None:
    catalog, _, profiles = _inputs()
    changed = copy.deepcopy(profiles)
    duplicate = changed["relationPolicies"][0]["assertionPredicates"]["MappingAssertion"][0]
    predicates = changed["relationPolicies"][0]["assertionPredicates"][
        "NativeRelationAssertion"
    ]
    predicates.append(duplicate)
    predicates.sort()
    _resign(changed)

    with pytest.raises(coverage.RegistryCoverageError, match="is duplicated in"):
        coverage.validate_profile_map(changed, catalog)

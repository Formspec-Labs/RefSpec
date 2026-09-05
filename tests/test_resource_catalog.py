from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from refspec.resource_catalog import (
    ResourceCatalogError,
    build_resource_catalog,
    load_json,
    render_json,
    validate_resource_catalog,
    verified_distribution_ids,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "portfolio" / "resource-inventory-v0.json"
COMPLETED = ROOT / "portfolio" / "completed-resource-packages-v2.json"
DISTRIBUTIONS = ROOT / "portfolio" / "portable-resource-distributions-v0.json"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    inventory = load_json(INVENTORY)
    completed = load_json(COMPLETED)
    distributions = load_json(DISTRIBUTIONS)
    return inventory, completed, distributions


def _resource_row(inventory: dict[str, object], resource_id: str) -> dict[str, Any]:
    return copy.deepcopy(
        next(row for row in inventory["resources"] if row["resourceId"] == resource_id)  # type: ignore[index,union-attr]
    )


def _completed_row(completed: dict[str, object], resource_id: str) -> dict[str, Any]:
    return copy.deepcopy(
        next(row for row in completed["resources"] if row["resourceId"] == resource_id)  # type: ignore[index,union-attr]
    )


def _distribution_row(distributions: dict[str, object], package_resource_id: str) -> dict[str, Any]:
    return copy.deepcopy(
        next(  # type: ignore[call-overload]
            row
            for row in distributions["distributions"]  # type: ignore[union-attr]
            if row["packageResourceId"] == package_resource_id
        )
    )


def _completed_subset(
    completed: dict[str, object],
    resource_ids: tuple[str, ...],
    repository_root: Path,
) -> dict[str, object]:
    rows = [_completed_row(completed, resource_id) for resource_id in resource_ids]
    evidence = repository_root / "evidence"
    evidence.mkdir()
    for row in rows:
        path = evidence / f"{row['resourceId']}.txt"
        path.write_text("test evidence\n", encoding="utf-8")
        row["evidencePath"] = path.relative_to(repository_root).as_posix()
    return {
        "recordedAt": completed["recordedAt"],
        "resources": rows,
        "schemaVersion": "2.0",
        "summary": {
            "managedConceptResourceCount": sum(row["packageClass"] == "managedConceptRelease" for row in rows),
            "recordOrObservationCount": sum(row["recordOrObservationCount"] for row in rows),
            "releaseOrSnapshotCount": sum(row["releaseOrSnapshotCount"] for row in rows),
            "resourceCount": len(rows),
            "sealedRegistryArtifactCount": sum(row["packageClass"] == "sealedRegistryArtifact" for row in rows),
            "sourceConceptReleaseCount": sum(row["packageClass"] == "sourceConceptRelease" for row in rows),
            "sourceControlledResourceCount": sum(row["packageClass"] == "sourceControlledResource" for row in rows),
        },
    }


def _portable_row_for_directory(
    template: dict[str, Any],
    package_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    manifest_name = Path(str(template["manifestPath"])).name
    result = copy.deepcopy(template)
    result["manifestPath"] = (package_root / manifest_name).relative_to(repository_root).as_posix()
    result["files"] = [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(package_root.rglob("*"))
        if path.is_file()
    ]
    return result


def test_checked_catalog_is_exact_and_two_tier() -> None:
    inventory, completed, distributions = _inputs()
    catalog = build_resource_catalog(
        inventory,
        completed,
        distributions,
        repository_root=ROOT,
    )

    validate_resource_catalog(
        catalog,
        inventory,
        completed,
        distributions,
        repository_root=ROOT,
    )

    # REF-034: the retired AGROVOC and NALT rows and the closed EPA row left
    # the inventory; the GAO Form 41217 submission-form row joined (89 -> 87).
    # REF-035 through REF-037 add the mapping research and acquisition-wave
    # sources without treating mapping-only rows as verified distributions.
    # REF-069 adds `usc-act-index` (116 -> 117). It lands at inventoryOnly on
    # purpose: the artifact is sealed and digest-pinned but written under
    # `output/`, which git does not carry, so it is not yet exchanged as an
    # immutable release and has no portable distribution to verify.
    # REF-069 publishes the act index as a sealed registry artifact, so it
    # leaves inventoryOnly for verifiedDistribution (107 -> 106, 5 -> 6, 3 -> 4).
    # That is the tier SpicySearch's decision 0008 condition 1 needs: owned AND
    # published through a product path rather than read out of a sibling's
    # gitignored output/ directory.
    assert catalog["summary"] == {
        "evidenceOnlyCount": 7,
        "inventoryOnlyCount": 106,
        "resourceCount": 117,
        "verifiedDistributionCount": 6,
        "verifiedResourceCount": 4,
    }
    assert verified_distribution_ids(catalog) == {
        "crs-legislative-subject-terms",
        "crs-policy-areas",
        "lda-native-controls",
        "usc-act-index",
    }


def test_source_catalog_input_excludes_atlas_outputs() -> None:
    distributions = load_json(DISTRIBUTIONS)

    atlas_rows = [
        row for row in distributions["distributions"] if row["distributionKind"].startswith("refspec-vocabulary-atlas-")
    ]

    # Atlas scopes pin the AtlasIndex, which pins this source catalog. Atlas
    # outputs belong in a downstream publication catalog, not back in this
    # source inventory where they would create a digest cycle.
    assert atlas_rows == []


def test_catalog_rejects_retired_atlas_2_distributions() -> None:
    inventory, completed, distributions = _inputs()
    changed = copy.deepcopy(distributions)
    changed["distributions"][0]["distributionKind"] = "refspec-vocabulary-atlas-nquads-2.0"  # type: ignore[index]

    with pytest.raises(ResourceCatalogError, match="distributionKind is unsupported"):
        build_resource_catalog(inventory, completed, changed, repository_root=ROOT)


def test_catalog_generation_is_relocatable(tmp_path: Path) -> None:
    inventory, completed, distributions = _inputs()
    generated = build_resource_catalog(
        inventory,
        completed,
        distributions,
        repository_root=ROOT,
    )

    output = tmp_path / "catalog.json"
    output.write_text(render_json(generated), encoding="utf-8")

    assert json.loads(output.read_bytes()) == generated


def test_duplicate_resource_ids_are_rejected() -> None:
    inventory, completed, distributions = _inputs()
    duplicate = copy.deepcopy(inventory)
    duplicate["resources"].append(copy.deepcopy(duplicate["resources"][0]))  # type: ignore[index,union-attr]

    with pytest.raises(ResourceCatalogError, match="duplicate resourceId"):
        build_resource_catalog(duplicate, completed, distributions, repository_root=ROOT)


def test_absolute_distribution_paths_are_rejected() -> None:
    inventory, completed, distributions = _inputs()
    unsafe = copy.deepcopy(distributions)
    unsafe["distributions"][0]["manifestPath"] = "/tmp/atlas-manifest.json"  # type: ignore[index]

    with pytest.raises(ResourceCatalogError, match="repository-relative"):
        build_resource_catalog(inventory, completed, unsafe, repository_root=ROOT)


def test_distribution_byte_drift_is_rejected() -> None:
    inventory, completed, distributions = _inputs()
    changed = copy.deepcopy(distributions)
    changed["distributions"][0]["files"][0]["sha256"] = "sha256:" + "0" * 64  # type: ignore[index]

    with pytest.raises(ResourceCatalogError, match="digest mismatch"):
        build_resource_catalog(inventory, completed, changed, repository_root=ROOT)


def test_source_controlled_distribution_requires_its_complete_file_inventory() -> None:
    inventory, completed, distributions = _inputs()
    incomplete = copy.deepcopy(distributions)
    row = next(  # type: ignore[call-overload]
        value
        for value in incomplete["distributions"]  # type: ignore[union-attr]
        if value["distributionKind"] == "refspec-source-controlled-resource-2.0"
    )
    row["files"] = [value for value in row["files"] if not value["path"].endswith("observations.jsonl")]

    with pytest.raises(ResourceCatalogError, match="file inventory differs from the closed package"):
        build_resource_catalog(inventory, completed, incomplete, repository_root=ROOT)


def test_source_controlled_distribution_binds_the_completed_logical_digest() -> None:
    inventory, completed, distributions = _inputs()
    stale = copy.deepcopy(completed)
    row = next(  # type: ignore[call-overload]
        value
        for value in stale["resources"]  # type: ignore[union-attr]
        if value["resourceId"] == "lda-filing-types"
    )
    row["packageDigest"] = "sha256:" + "0" * 64

    with pytest.raises(ResourceCatalogError, match="logical digest differs from completed evidence"):
        build_resource_catalog(inventory, stale, distributions, repository_root=ROOT)


def test_source_controlled_distribution_reader_rejects_a_reinventoried_extra_file(
    tmp_path: Path,
) -> None:
    inventory, completed, distributions = _inputs()
    package_root = tmp_path / "package"
    shutil.copytree(
        ROOT / "research/evidence/lda-controlled-lists-2026-07-30/filing-types",
        package_root,
    )
    (package_root / "undeclared.txt").write_text("not in the bundle manifest\n", encoding="utf-8")
    distribution = _portable_row_for_directory(
        _distribution_row(distributions, "lda-filing-types"),
        package_root,
        tmp_path,
    )
    minimal_inventory = {
        "format": inventory["format"],
        "recordedAt": inventory["recordedAt"],
        "resources": [_resource_row(inventory, "lda-native-controls")],
    }
    minimal_completed = _completed_subset(completed, ("lda-filing-types",), tmp_path)
    minimal_distributions = {
        "format": distributions["format"],
        "distributions": [distribution],
    }

    with pytest.raises(ResourceCatalogError, match="not a valid closed source-controlled resource"):
        build_resource_catalog(
            minimal_inventory,
            minimal_completed,
            minimal_distributions,
            repository_root=tmp_path,
        )


def test_source_concept_distribution_requires_its_complete_file_inventory() -> None:
    inventory, completed, distributions = _inputs()
    incomplete = copy.deepcopy(distributions)
    row = next(  # type: ignore[call-overload]
        value
        for value in incomplete["distributions"]  # type: ignore[union-attr]
        if value["distributionKind"] == "refspec-source-concept-release-1.0"
    )
    row["files"] = [value for value in row["files"] if not value["path"].endswith("concepts.jsonl")]

    with pytest.raises(ResourceCatalogError, match="file inventory differs from the closed package"):
        build_resource_catalog(inventory, completed, incomplete, repository_root=ROOT)


def test_source_concept_distribution_binds_the_completed_logical_digest() -> None:
    inventory, completed, distributions = _inputs()
    stale = copy.deepcopy(completed)
    row = next(  # type: ignore[call-overload]
        value
        for value in stale["resources"]  # type: ignore[union-attr]
        if value["packageClass"] == "sourceConceptRelease"
    )
    row["packageDigest"] = "sha256:" + "0" * 64

    with pytest.raises(ResourceCatalogError, match="logical digest differs from completed evidence"):
        build_resource_catalog(inventory, stale, distributions, repository_root=ROOT)


def test_source_concept_distribution_reader_rejects_reinventoried_payload_tampering(
    tmp_path: Path,
) -> None:
    inventory, completed, distributions = _inputs()
    package_id = "crs-legislative-subject-source-concepts"
    package_root = tmp_path / "release"
    shutil.copytree(
        ROOT / "research/evidence/crs-source-concept-releases-2026-08-04/legislative-subjects",
        package_root,
    )
    concepts = package_root / "concepts.jsonl"
    concepts.write_bytes(concepts.read_bytes() + b"\n")
    distribution = _portable_row_for_directory(
        _distribution_row(distributions, package_id),
        package_root,
        tmp_path,
    )
    minimal_inventory = {
        "format": inventory["format"],
        "recordedAt": inventory["recordedAt"],
        "resources": [_resource_row(inventory, "crs-legislative-subject-terms")],
    }
    minimal_completed = _completed_subset(completed, (package_id,), tmp_path)
    minimal_distributions = {
        "format": distributions["format"],
        "distributions": [distribution],
    }

    with pytest.raises(ResourceCatalogError, match="not a valid closed source-concept release"):
        build_resource_catalog(
            minimal_inventory,
            minimal_completed,
            minimal_distributions,
            repository_root=tmp_path,
        )


def _sealed_row(distributions: dict[str, Any]) -> dict[str, Any]:
    return next(
        value
        for value in distributions["distributions"]
        if value["distributionKind"] == "refspec-sealed-registry-artifact-1.0"
    )


def test_sealed_registry_distribution_refuses_a_table_its_receipt_never_sealed() -> None:
    """REF-069's negative fixture: a package may not carry what its seal disowns.

    The receipt's `outputs` block IS the declared member list, so the check runs
    in both directions. Dropping a table is the other half and has its own test
    below; this one adds a file the seal never saw, which is the shape that
    would let a package ship an unsealed table beside three sealed ones.
    """

    inventory, completed, distributions = _inputs()
    extra = copy.deepcopy(distributions)
    row = _sealed_row(extra)
    strays = [f for f in row["files"] if f["path"].endswith("usc-act-sections.parquet")]
    row["files"] = [*row["files"], {"path": strays[0]["path"] + ".bak", "sha256": strays[0]["sha256"]}]

    with pytest.raises(ResourceCatalogError):
        build_resource_catalog(inventory, completed, extra, repository_root=ROOT)


def test_sealed_registry_distribution_refuses_a_missing_sealed_table() -> None:
    """The receipt names four members; three is not a subset, it is a different artifact."""

    inventory, completed, distributions = _inputs()
    short = copy.deepcopy(distributions)
    row = _sealed_row(short)
    row["files"] = [f for f in row["files"] if not f["path"].endswith("quarantine.parquet")]

    with pytest.raises(ResourceCatalogError, match="file set differs from the receipt"):
        build_resource_catalog(inventory, completed, short, repository_root=ROOT)


def test_sealed_registry_distribution_binds_the_completed_receipt_digest() -> None:
    """The completed row's packageDigest is the receipt's, not a second opinion."""

    inventory, completed, distributions = _inputs()
    stale = copy.deepcopy(completed)
    row = next(value for value in stale["resources"] if value["resourceId"] == "usc-act-index")
    row["packageDigest"] = "sha256:" + "0" * 64

    with pytest.raises(ResourceCatalogError, match="receipt digest differs from completed evidence"):
        build_resource_catalog(inventory, stale, distributions, repository_root=ROOT)


def test_sealed_registry_distribution_refuses_a_wrong_package_class() -> None:
    """A sealed artifact filed as an observation package is the mislabel REF-069 exists to stop."""

    inventory, completed, distributions = _inputs()
    wrong = copy.deepcopy(completed)
    row = next(value for value in wrong["resources"] if value["resourceId"] == "usc-act-index")
    row["packageClass"] = "sourceControlledResource"

    with pytest.raises(ResourceCatalogError):
        build_resource_catalog(inventory, wrong, distributions, repository_root=ROOT)

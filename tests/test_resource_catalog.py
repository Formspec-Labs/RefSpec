from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import refspec.resource_catalog as resource_catalog_module
from refspec.atlas.model import VocabularyAtlasError
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


def _temporary_atlas_distribution(
    package_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    package_root.mkdir()
    (package_root / "atlas-manifest.json").write_text("{}\n", encoding="utf-8")
    (package_root / "atlas.nq").write_text(
        "<urn:test:s> <urn:test:p> <urn:test:o> <urn:test:g> .\n",
        encoding="utf-8",
    )
    (package_root / "atlas-scope.json").write_text("{}\n", encoding="utf-8")
    return _portable_row_for_directory(
        {
            "distributionKind": "refspec-vocabulary-atlas-nquads-2.0",
            "files": [],
            "manifestPath": "atlas-manifest.json",
            "packageResourceId": "federal-register-thesaurus-2025",
            "resourceId": "federal-register-thesaurus-2025",
        },
        package_root,
        repository_root,
    )


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

    assert catalog["summary"] == {
        "evidenceOnlyCount": 7,
        "inventoryOnlyCount": 79,
        "resourceCount": 89,
        "verifiedDistributionCount": 5,
        "verifiedResourceCount": 3,
    }
    assert verified_distribution_ids(catalog) == {
        "crs-legislative-subject-terms",
        "crs-policy-areas",
        "lda-native-controls",
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


def test_atlas_2_distribution_inventories_all_three_files_and_uses_one_trusted_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, completed, distributions = _inputs()
    package_root = tmp_path / "atlas"
    distribution = _temporary_atlas_distribution(package_root, tmp_path)
    minimal_inventory = {
        "format": inventory["format"],
        "recordedAt": inventory["recordedAt"],
        "resources": [_resource_row(inventory, "federal-register-thesaurus-2025")],
    }
    minimal_completed = _completed_subset(completed, ("federal-register-thesaurus-2025",), tmp_path)
    minimal_distributions = {
        "format": distributions["format"],
        "distributions": [distribution],
    }
    calls: list[tuple[Path, str]] = []

    def verified_open(
        directory: Path,
        *,
        expected_manifest_digest: str,
    ) -> object:
        calls.append((Path(directory), expected_manifest_digest))
        return object()

    monkeypatch.setattr(
        resource_catalog_module.VocabularyAtlasAsset,
        "open",
        staticmethod(verified_open),
    )

    catalog = build_resource_catalog(
        minimal_inventory,
        minimal_completed,
        minimal_distributions,
        repository_root=tmp_path,
    )

    atlas = catalog["resources"][0]["distributions"][0]
    assert atlas["distributionKind"] == "refspec-vocabulary-atlas-nquads-2.0"
    assert {Path(row["path"]).name for row in atlas["files"]} == {
        "atlas-manifest.json",
        "atlas.nq",
        "atlas-scope.json",
    }
    manifest_path = package_root / "atlas-manifest.json"
    assert calls == [(package_root, _file_digest(manifest_path))]


def test_atlas_2_distribution_requires_the_scope_file(tmp_path: Path) -> None:
    inventory, completed, distributions = _inputs()
    package_root = tmp_path / "atlas"
    distribution = _temporary_atlas_distribution(package_root, tmp_path)
    (package_root / "atlas-scope.json").unlink()
    distribution["files"] = [row for row in distribution["files"] if not row["path"].endswith("atlas-scope.json")]
    minimal_inventory = {
        "format": inventory["format"],
        "recordedAt": inventory["recordedAt"],
        "resources": [_resource_row(inventory, "federal-register-thesaurus-2025")],
    }
    minimal_completed = _completed_subset(completed, ("federal-register-thesaurus-2025",), tmp_path)
    minimal_distributions = {
        "format": distributions["format"],
        "distributions": [distribution],
    }

    with pytest.raises(ResourceCatalogError, match="must contain atlas-manifest.json, atlas.nq, and atlas-scope.json"):
        build_resource_catalog(
            minimal_inventory,
            minimal_completed,
            minimal_distributions,
            repository_root=tmp_path,
        )


def test_atlas_2_distribution_wraps_file_only_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, completed, distributions = _inputs()
    package_root = tmp_path / "atlas"
    distribution = _temporary_atlas_distribution(package_root, tmp_path)
    minimal_inventory = {
        "format": inventory["format"],
        "recordedAt": inventory["recordedAt"],
        "resources": [_resource_row(inventory, "federal-register-thesaurus-2025")],
    }
    minimal_completed = _completed_subset(completed, ("federal-register-thesaurus-2025",), tmp_path)
    minimal_distributions = {
        "format": distributions["format"],
        "distributions": [distribution],
    }

    def rejected_open(
        directory: Path,
        *,
        expected_manifest_digest: str,
    ) -> None:
        del directory, expected_manifest_digest
        raise VocabularyAtlasError("atlas output digest differs")

    monkeypatch.setattr(
        resource_catalog_module.VocabularyAtlasAsset,
        "open",
        staticmethod(rejected_open),
    )

    with pytest.raises(ResourceCatalogError, match="not a valid closed vocabulary atlas"):
        build_resource_catalog(
            minimal_inventory,
            minimal_completed,
            minimal_distributions,
            repository_root=tmp_path,
        )

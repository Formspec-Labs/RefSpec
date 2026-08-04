from __future__ import annotations

import copy
import json
from pathlib import Path

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
COMPLETED = ROOT / "portfolio" / "completed-controlled-resource-packages-v1.json"
DISTRIBUTIONS = ROOT / "portfolio" / "portable-resource-distributions-v0.json"
CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return load_json(INVENTORY), load_json(COMPLETED), load_json(DISTRIBUTIONS)


def test_checked_catalog_is_exact_and_two_tier() -> None:
    inventory, completed, distributions = _inputs()
    catalog = load_json(CATALOG)

    validate_resource_catalog(
        catalog,
        inventory,
        completed,
        distributions,
        repository_root=ROOT,
    )

    assert catalog["summary"] == {
        "evidenceOnlyCount": 8,
        "inventoryOnlyCount": 76,
        "resourceCount": 86,
        "verifiedDistributionCount": 3,
        "verifiedResourceCount": 2,
    }
    assert verified_distribution_ids(catalog) == {
        "federal-register-thesaurus-2025",
        "lda-native-controls",
    }


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

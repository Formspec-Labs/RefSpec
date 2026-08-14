"""The entity-registry object: registrant populations split out of the Atlas.

REF-030 moved SAM registrants, CAGE facilities, NPI providers, and CompTox
substances out of the sealed Atlas into this standalone object. These tests
are the running check on that boundary's artifact side: the object builds
deterministically from the pinned captures, carries the same URNs the Atlas
exemplars used, verifies against its manifest, and refuses tampering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry.entity_registry_release import (
    ENTITY_REGISTRY_PAYLOAD_FILE,
    EntityRegistryError,
    build_entity_registry_payload,
    load_comptox_registry_releases,
    load_nppes_registry_releases,
    load_sam_registry_releases,
    verify_entity_registry,
    write_entity_registry,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

_UNTRACKED_PINS = (
    REPO_ROOT / "output/registry-real-data-sources/sam-entity-3m-public.json",
    REPO_ROOT / "output/registry-real-data-sources/comptox-DTXSID7020182.normalized.html",
)
_pins_present = all(path.is_file() for path in _UNTRACKED_PINS)


def test_missing_pins_refuse_with_the_pin_path(tmp_path: Path) -> None:
    with pytest.raises(EntityRegistryError, match="pinned source is missing"):
        build_entity_registry_payload(tmp_path)


@pytest.mark.skipif(
    not _pins_present,
    reason="registry real-data captures are pinned outside git; build them locally first",
)
def test_entity_registry_builds_verifies_and_refuses_tampering(tmp_path: Path) -> None:
    sam = load_sam_registry_releases(REPO_ROOT)
    assert [release["key"] for release in sam] == [
        "sam-uei-bounded-public-entity-2026-08-03",
        "sam-cage-bounded-public-facility-2026-08-03",
    ]
    nppes = load_nppes_registry_releases(REPO_ROOT)
    assert [len(release["records"]) for release in nppes] == [3]
    comptox = load_comptox_registry_releases(REPO_ROOT)
    assert [len(release["records"]) for release in comptox] == [1]

    payload = build_entity_registry_payload(REPO_ROOT)

    assert payload["counts"]["releases"] == 4
    assert payload["counts"]["records"] == 6
    assert payload["counts"]["relations"] == 1
    keys = [release["key"] for release in payload["releases"]]
    assert keys == [
        "epa-comptox-substance-bounded-2026-08-03",
        "nppes-npi-provider-sample-2026-08-03",
        "sam-cage-bounded-public-facility-2026-08-03",
        "sam-uei-bounded-public-entity-2026-08-03",
    ]
    by_key = {release["key"]: release for release in payload["releases"]}
    uei = by_key["sam-uei-bounded-public-entity-2026-08-03"]["records"][0]
    assert uei["id"] == "urn:ref:sam-entity:uei:YLQMY5SGNE55"
    assert uei["label"] == "3M COMPANY"
    relation = by_key["sam-cage-bounded-public-facility-2026-08-03"]["relations"][0]
    assert relation["object"] == "urn:ref:sam-entity:uei:YLQMY5SGNE55"
    assert relation["predicate"].endswith("relatedEntity")

    target = tmp_path / "entity-registry"
    manifest = write_entity_registry(REPO_ROOT, target)
    assert verify_entity_registry(target) == manifest
    # Rewriting the same content is idempotent; a second build is byte-stable.
    assert write_entity_registry(REPO_ROOT, target) == manifest

    payload_path = target / ENTITY_REGISTRY_PAYLOAD_FILE
    tampered = payload_path.read_bytes().replace(b"3M COMPANY", b"4M COMPANY", 1)
    payload_path.write_bytes(tampered)
    with pytest.raises(EntityRegistryError, match="payload digest differs"):
        verify_entity_registry(target)
    with pytest.raises(EntityRegistryError, match="refusing to replace"):
        write_entity_registry(REPO_ROOT, target)

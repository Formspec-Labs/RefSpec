from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from refspec import (
    ReleaseValidationError,
    build_federal_register_2025_first_slice,
    validate_vocabulary_release,
)
from refspec.canonical import seal_vocabulary_release, stable_record
from refspec.reference_resource import reference_release_node


def _reseal_release(release: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in release.items()
        if key not in {"release_id", "release_digest"}
    }
    return seal_vocabulary_release(payload)


def _reseal_resolution(record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"resolution_id", "resolution_digest"}
    }
    return stable_record(
        payload,
        id_field="resolution_id",
        digest_field="resolution_digest",
        id_prefix="urn:refspec:source-term-resolution:",
    )


def test_missing_resolution_fails_closed() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    release["source_term_resolutions"].pop()
    with pytest.raises(ReleaseValidationError, match="exactly one"):
        validate_vocabulary_release(_reseal_release(release))


def test_wrong_complete_source_term_key_reference_fails() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    resolution = release["source_term_resolutions"][0]
    resolution["source_term_key_ref"] = {
        "id": "urn:refspec:source-term-key:does-not-exist",
        "digest": resolution["source_term_key_ref"]["digest"],
    }
    release["source_term_resolutions"][0] = _reseal_resolution(resolution)
    with pytest.raises(ReleaseValidationError, match="does not resolve"):
        validate_vocabulary_release(_reseal_release(release))


def test_status_specific_target_cardinality_fails() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    unresolved = next(
        item
        for item in release["source_term_resolutions"]
        if item["resolution_status"] == "unresolved"
    )
    targeted = next(
        item
        for item in release["source_term_resolutions"]
        if item["resolution_status"] == "officialTerm"
    )
    unresolved["target_concept_and_release"] = deepcopy(
        targeted["target_concept_and_release"]
    )
    index = release["source_term_resolutions"].index(unresolved)
    release["source_term_resolutions"][index] = _reseal_resolution(unresolved)
    with pytest.raises(ReleaseValidationError, match="forbids a concept target"):
        validate_vocabulary_release(_reseal_release(release))


def test_nested_digest_tampering_fails_even_with_new_outer_digest() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    release["concepts"][0]["preferred_label"] = "Tampered label"
    with pytest.raises(ReleaseValidationError, match="concept_digest"):
        validate_vocabulary_release(_reseal_release(release))


def test_missing_evidence_reference_fails_closure() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    resolution = release["source_term_resolutions"][0]
    resolution["evidence_refs"][0] = {
        "id": "urn:refspec:support-record:missing",
        "digest": resolution["evidence_refs"][0]["digest"],
    }
    release["source_term_resolutions"][0] = _reseal_resolution(resolution)
    with pytest.raises(ReleaseValidationError, match="does not resolve"):
        validate_vocabulary_release(_reseal_release(release))


def test_incomplete_reference_release_membership_fails() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    projection = release["reference_resource_release"]
    reference_release_node(projection)["prov:hadMember"].pop()
    with pytest.raises(ReleaseValidationError, match="exact concept set"):
        validate_vocabulary_release(_reseal_release(release))


def test_wrong_rulespec_core_fixture_pin_fails() -> None:
    release = deepcopy(build_federal_register_2025_first_slice())
    release["rulespec_core_fixture"]["rulespec_core_release_fixture_sha256"] = (
        "sha256:" + "0" * 64
    )
    with pytest.raises(ReleaseValidationError, match="wrong Rulespec Core"):
        validate_vocabulary_release(_reseal_release(release))

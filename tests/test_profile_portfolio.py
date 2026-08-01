from __future__ import annotations

import copy
from pathlib import Path

import pytest

from refspec import binding
from refspec.profile_portfolio import (
    PortfolioInventoryError,
    build_portfolio_atlas,
    canonical_sha256,
    extract_spicy_regs_profiles,
    load_json,
    render_json,
    validate_generated_atlas,
    validate_portfolio_input,
    validate_profile_snapshot,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
SPICY_REGS_ROOT = REFSPEC_ROOT.parent
SNAPSHOT_PATH = (
    REFSPEC_ROOT
    / "portfolio"
    / "inputs"
    / "spicy-regs-source-profiles-v1.json"
)
INPUT_PATH = (
    REFSPEC_ROOT
    / "portfolio"
    / "inputs"
    / "active-profile-controlled-resources-v1.json"
)
ATLAS_PATH = (
    REFSPEC_ROOT
    / "portfolio"
    / "active-profile-controlled-resource-atlas-v1.json"
)


def _inputs() -> tuple[dict[str, object], dict[str, object]]:
    return load_json(SNAPSHOT_PATH), load_json(INPUT_PATH)


def test_snapshot_matches_live_spicy_regs_source_without_importing_it() -> None:
    snapshot, _ = _inputs()
    source_path = SPICY_REGS_ROOT / snapshot["source"]["path"]  # type: ignore[index]

    validate_profile_snapshot(snapshot, source_path=source_path)

    assert extract_spicy_regs_profiles(source_path) == snapshot["profiles"]
    assert sum(profile["activeInStep4"] for profile in snapshot["profiles"]) == 16
    assert [
        profile["profileId"]
        for profile in snapshot["profiles"]
        if not profile["activeInStep4"]
    ] == ["regulations-comment-v1"]


def test_portfolio_closes_every_active_and_deferred_profile() -> None:
    snapshot, portfolio_input = _inputs()

    validate_portfolio_input(snapshot, portfolio_input)
    atlas = build_portfolio_atlas(snapshot, portfolio_input)

    assert atlas["summary"] == {
        "profileCount": 17,
        "activeProfileCount": 16,
        "deferredProfileCount": 1,
        "activeDocumentOrObservationCount": 10,
        "activeRoleCounts": {
            "document": 9,
            "observation": 1,
            "container": 3,
            "entity": 3,
        },
        "subjectEligibleProfileCount": 10,
        "documentedSubjectGapProfiles": [
            "cfr-section-v1",
            "court-opinion-v1",
            "crs-report-v1",
            "fcc-filing-v1",
            "gao-report-v1",
        ],
        "resourceCount": 33,
    }
    assert all(profile["recordRole"] for profile in atlas["profiles"])
    assert all(profile["sourceNativeFields"] for profile in atlas["profiles"])
    assert all(profile["controlledResourceUses"] for profile in atlas["profiles"])
    assert all(profile["subjectPolicy"]["gap"] for profile in atlas["profiles"])


def test_checked_in_atlas_is_exact_deterministic_generation() -> None:
    snapshot, portfolio_input = _inputs()
    atlas = load_json(ATLAS_PATH)

    validate_generated_atlas(atlas, snapshot, portfolio_input)


def test_profile_coverage_cannot_be_implicit() -> None:
    snapshot, portfolio_input = _inputs()
    incomplete = copy.deepcopy(portfolio_input)
    incomplete["profiles"].pop()

    with pytest.raises(PortfolioInventoryError, match="profile coverage differs"):
        validate_portfolio_input(snapshot, incomplete)


def test_primary_subject_path_must_be_explicitly_selectable() -> None:
    snapshot, portfolio_input = _inputs()
    implicit = copy.deepcopy(portfolio_input)
    profile = next(
        profile
        for profile in implicit["profiles"]
        if profile["profileId"] == "congress-bill-v1"
    )
    row = next(
        row
        for row in profile["controlledResourceUses"]
        if row["resourceId"] == "crs-legislative-subject-terms"
    )
    row["uses"].remove("selectableSubject")

    with pytest.raises(
        PortfolioInventoryError,
        match="primary subject resources must be declared",
    ):
        validate_portfolio_input(snapshot, implicit)


def test_resource_acquisition_gaps_and_versions_are_mandatory() -> None:
    snapshot, portfolio_input = _inputs()
    unpinned = copy.deepcopy(portfolio_input)
    unpinned["resources"][0]["versionRepresentation"] = ""

    with pytest.raises(
        PortfolioInventoryError,
        match=r"resources\[0\]\.versionRepresentation",
    ):
        validate_portfolio_input(snapshot, unpinned)


def test_one_canonical_digest_excludes_the_trailing_newline() -> None:
    """The portfolio pins the platform digest, not a portfolio-only variant."""

    assert canonical_sha256 is binding.canonical_sha256

    value = {"id": "urn:test:portfolio", "members": ["a", "b"]}
    assert binding.canonical_json_bytes(value) == b'{"id":"urn:test:portfolio","members":["a","b"]}'
    assert not binding.canonical_json_bytes(value).endswith(b"\n")
    assert canonical_sha256(value) == binding.canonical_payload_digest(value)


def test_the_trailing_newline_belongs_to_the_file_writer() -> None:
    """Checked-in JSON keeps its newline; the digested bytes never carry one."""

    value = {"id": "urn:test:portfolio", "members": ["a", "b"]}
    rendered = render_json(value)

    assert rendered.endswith("\n")
    assert not binding.canonical_json_bytes(value).endswith(b"\n")
    assert ATLAS_PATH.read_bytes().endswith(b"\n")


def test_checked_in_atlas_pins_the_consolidated_digest() -> None:
    snapshot, portfolio_input = _inputs()
    atlas = load_json(ATLAS_PATH)
    generated_from = atlas["generatedFrom"]

    assert generated_from["spicyRegsProfileSnapshotSha256"] == canonical_sha256(snapshot)
    assert generated_from["refspecPortfolioInputSha256"] == canonical_sha256(portfolio_input)

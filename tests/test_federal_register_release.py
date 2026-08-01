from __future__ import annotations

from pathlib import Path

from refspec import (
    build_federal_register_2025_first_slice,
    canonical_json_bytes,
    validate_vocabulary_release,
)
from refspec.cli import main
from refspec.reference_resource import (
    reference_release_node,
    validate_digest_implementation_against_rulespec_fixture,
)
from refspec.rulespec_core import (
    load_reference_resource_release_schema,
    load_rulespec_core_release_fixture,
)


RELEASE_FIXTURE = (
    Path(__file__).parents[1]
    / "release-records"
    / "fixtures"
    / "refspec-vocabulary-release-federal-register-2025-first-slice.json"
)


def test_release_is_deterministic_and_valid() -> None:
    first = build_federal_register_2025_first_slice()
    second = build_federal_register_2025_first_slice()
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first["release_id"].endswith(first["release_digest"].removeprefix("sha256:"))
    validate_vocabulary_release(first)


def test_reference_projection_is_exact_and_complete() -> None:
    release = build_federal_register_2025_first_slice()
    projection = release["reference_resource_release"]
    node = reference_release_node(projection)
    assert node["@type"] == "rkaf:ReferenceResourceRelease"
    assert node["rkaf:membershipMode"] == "rkaf:completeMembership"
    assert node["prov:hadMember"] == sorted(
        concept["concept_id"] for concept in release["concepts"]
    )
    assert set(release["rulespec_core_release"]) == {
        "release_id",
        "release_digest",
    }
    assert release["rulespec_core_release"]["release_id"].startswith(
        "urn:rulespec:core:"
    )


def test_package_contains_the_exact_rulespec_core_release_fixture() -> None:
    core = load_rulespec_core_release_fixture()
    assert set(core) == {
        "record_type",
        "release_id",
        "release_digest",
        "release_status",
        "version",
        "schema_artifacts",
        "validator_artifacts",
        "conformance_fixture_artifacts",
    }
    assert core["release_status"] == "fixture"
    digest_hex = core["release_digest"].removeprefix("sha256:")
    assert core["release_id"] == "urn:rulespec:core:" + digest_hex
    schema_names = {item["name"] for item in core["schema_artifacts"]}
    assert "compiled/json-schema/core/reference-resource-release.schema.json" in (
        schema_names
    )
    assert "$defs" in load_reference_resource_release_schema()
    validate_digest_implementation_against_rulespec_fixture()


def test_lists_of_subjects_cover_all_four_closed_states() -> None:
    release = build_federal_register_2025_first_slice()
    keys = {key["key_id"]: key for key in release["source_term_keys"]}
    resolutions = [
        item
        for item in release["source_term_resolutions"]
        if keys[item["source_term_key_ref"]["id"]]["observation_kind"]
        == "listsOfSubjects"
    ]
    by_status = {item["resolution_status"]: item for item in resolutions}
    assert set(by_status) == {
        "officialTerm",
        "recognizedVariant",
        "sourceLocalOpenTerm",
        "unresolved",
    }
    assert "target_concept_and_release" in by_status["officialTerm"]
    assert "target_concept_and_release" in by_status["recognizedVariant"]
    assert "target_concept_and_release" not in by_status["sourceLocalOpenTerm"]
    assert "target_concept_and_release" not in by_status["unresolved"]


def test_api_topic_is_only_an_input_key_and_fails_closed() -> None:
    release = build_federal_register_2025_first_slice()
    api_keys = [
        item
        for item in release["source_term_keys"]
        if item["observation_kind"] == "federalRegisterApiTopic"
    ]
    assert len(api_keys) == 1
    resolution = next(
        item
        for item in release["source_term_resolutions"]
        if item["source_term_key_ref"]["id"] == api_keys[0]["key_id"]
    )
    assert resolution["resolution_status"] == "unresolved"
    assert "target_concept_and_release" not in resolution
    record_types = {item["record_type"] for item in release["support_records"]}
    assert not record_types & {
        "SourceObservation",
        "SourceObservationCapture",
        "DocumentObservation",
        "SearchRecord",
        "SearchIndex",
    }


def test_retired_vocabulary_and_crosswalk_are_absent() -> None:
    rendered = (
        canonical_json_bytes(build_federal_register_2025_first_slice())
        .decode("utf-8")
        .lower()
    )
    assert "1995" not in rendered
    assert "crosswalk" not in rendered


def test_baseline_uses_two_independent_completed_agents() -> None:
    release = build_federal_register_2025_first_slice()
    agents = release["agent_validation_receipts"]
    assert len(agents) == 2
    assert {item["execution_status"] for item in agents} == {"completed"}
    assert len({item["independence_group"] for item in agents}) == 2
    assert release["baseline_validation_receipts"][0]["aggregate_result"] == (
        "usable_for_search"
    )
    assert release["resolution_policy"]["human_approval_required"] is False


def test_builder_command_writes_canonical_reproducible_bytes(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert main(["--output", str(first)]) == 0
    assert main(["--output", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == canonical_json_bytes(
        build_federal_register_2025_first_slice()
    )


def test_committed_release_fixture_matches_the_builder() -> None:
    assert RELEASE_FIXTURE.read_bytes() == canonical_json_bytes(
        build_federal_register_2025_first_slice()
    )

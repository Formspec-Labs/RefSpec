from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

import refspec
from refspec import binding

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
BINDING_ROOT = REFSPEC_ROOT / "bindings" / "json" / "1.0"
VALID_FIXTURE = BINDING_ROOT / "fixtures" / "valid" / "vocabulary-closure.json"
LEGACY_CLI = BINDING_ROOT / "tools" / "validate.py"


def test_public_package_version_matches_project_metadata() -> None:
    project_text = (REFSPEC_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"$', project_text)

    assert match is not None
    assert refspec.__version__ == match.group(1)


def test_retired_atlas_builder_is_not_a_packaged_command() -> None:
    project_text = (REFSPEC_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert (
        re.search(
            r"(?m)^refspec-build-vocabulary-atlas\s*=",
            project_text,
        )
        is None
    )
    assert not (REFSPEC_ROOT / "src" / "refspec" / "atlas" / "cli.py").exists()


def test_editable_checkout_resolves_binding_assets() -> None:
    assert binding.REFSPEC_ROOT == REFSPEC_ROOT
    assert binding.BINDING_ROOT == BINDING_ROOT
    assert binding.SCHEMA_ROOT.is_dir()
    assert binding.FIXTURE_ROOT.is_dir()


def test_public_validate_api_accepts_the_valid_fixture() -> None:
    fixture = binding.load_fixture(VALID_FIXTURE)

    diagnostics = binding.validate(
        fixture["records"],
        permission_checks=fixture["permissionChecks"],
        language_tag_tests=fixture["languageTagTests"],
    )

    assert fixture["parseDiagnostics"] == []
    assert diagnostics == []


@pytest.mark.parametrize(
    "placement",
    (
        {
            "status": "placed",
            "relation": "narrowerThan",
            "targetConcept": "urn:rulespec:concept:broader",
        },
        {
            "status": "placed",
            "relation": "broaderThan",
            "targetConcept": "urn:rulespec:concept:narrower",
        },
        {
            "status": "placed",
            "relation": "relatedTo",
            "targetConcept": "urn:rulespec:concept:related",
        },
        {"status": "facetLocated"},
        {"status": "unresolved", "reason": "No reviewed anchor exists yet."},
    ),
    ids=(
        "narrower-than",
        "broader-than",
        "related-to",
        "facet-located",
        "unresolved",
    ),
)
def test_concept_proposal_accepts_each_typed_placement(
    placement: dict[str, str],
) -> None:
    fixture = binding.load_fixture(BINDING_ROOT / "fixtures" / "valid" / "concept-proposal.json")
    record = fixture["records"][0]
    record["placement"] = placement
    record["canonicalPayloadDigest"] = binding.canonical_payload_digest(record)

    assert binding.validate(fixture["records"]) == []


def test_expression_corpus_validator_reuses_one_schema_without_weakening_checks() -> None:
    fixture = binding.load_fixture(VALID_FIXTURE)
    expressions = [
        record for record in fixture["records"] if record["type"] == "urn:ref:type:IndexedVocabularyExpression"
    ]

    assert binding.validate_indexed_expression_records(expressions) == []

    diagnostics = binding.validate_indexed_expression_records([*expressions, expressions[0]])
    assert any(
        item.requirement == "REF-CORE-005" and "duplicate durable record identifier" in item.message
        for item in diagnostics
    )


def test_installed_package_can_validate_from_embedded_schemas(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = binding.load_fixture(VALID_FIXTURE)
    monkeypatch.setattr(binding, "SCHEMA_ROOT", tmp_path / "no-checkout-schemas")

    diagnostics = binding.validate(
        fixture["records"],
        permission_checks=fixture["permissionChecks"],
        language_tag_tests=fixture["languageTagTests"],
    )

    assert diagnostics == []


def test_installed_package_can_run_embedded_conformance_suite(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    missing_binding_root = tmp_path / "no-checkout-binding"
    monkeypatch.setattr(binding, "BINDING_ROOT", missing_binding_root)
    monkeypatch.setattr(
        binding,
        "SCHEMA_ROOT",
        missing_binding_root / "schemas",
    )
    monkeypatch.setattr(
        binding,
        "FIXTURE_ROOT",
        missing_binding_root / "fixtures",
    )

    assert binding.run_suite() == 0
    assert re.search(
        r"REF JSON Binding 1\.0: \d+ valid fixture\(s\) accepted; "
        r"\d+ invalid fixture\(s\) rejected; 0 failure\(s\)",
        capsys.readouterr().out,
    )


def test_legacy_cli_delegates_to_package_cli(capsys) -> None:
    package_exit_code = binding.main(["--print-digest", str(VALID_FIXTURE)])
    package_output = capsys.readouterr().out

    legacy = subprocess.run(
        [sys.executable, str(LEGACY_CLI), "--print-digest", str(VALID_FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert package_exit_code == 0
    assert legacy.returncode == package_exit_code
    assert legacy.stdout == package_output
    assert legacy.stderr == ""


def test_every_ref_record_has_complete_executable_fixture_coverage() -> None:
    """Keep every public REF record behind the same acceptance matrix."""

    valid_by_type: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    for path in sorted((binding.FIXTURE_ROOT / "valid").glob("*.json")):
        fixture = binding.load_fixture(path)
        for record in fixture["records"]:
            record_type = record.get("type")
            if record_type in binding.TYPE_SCHEMAS:
                valid_by_type[record_type].append((path, record))

    invalid_by_type: dict[str, list[Path]] = defaultdict(list)
    for path in sorted((binding.FIXTURE_ROOT / "invalid").glob("*.json")):
        descriptor = binding.load_json(path)
        mutated_ids = {
            mutation.get("recordId") for mutation in descriptor.get("mutations", []) if isinstance(mutation, dict)
        }
        fixture = binding.load_fixture(path)
        for record in fixture["records"]:
            record_type = record.get("type")
            if record_type in binding.TYPE_SCHEMAS and record.get("id") in mutated_ids:
                invalid_by_type[record_type].append(path)

    manifest = binding.load_json(binding.BINDING_ROOT / "tests" / "requirement-to-test-manifest.json")
    manifest_by_requirement = {entry["requirement"]: entry for entry in manifest["coverage"]}

    for record_type, requirement in binding.TYPE_REQUIREMENTS.items():
        assert valid_by_type[record_type], f"{record_type} has no valid fixture"
        assert invalid_by_type[record_type], f"{record_type} has no type-specific invalid fixture"
        assert requirement in manifest_by_requirement, f"{record_type} requirement {requirement} is not linked"
        linked = set(
            manifest_by_requirement[requirement].get(
                "localFixtures",
                [],
            )
        )
        assert any(
            str(path.relative_to(binding.BINDING_ROOT)) in linked for path, _record in valid_by_type[record_type]
        ), f"{record_type} has no requirement-linked valid fixture"
        assert any(str(path.relative_to(binding.BINDING_ROOT)) in linked for path in invalid_by_type[record_type]), (
            f"{record_type} has no requirement-linked invalid fixture"
        )

        for _path, record in valid_by_type[record_type]:
            digest_name = binding.digest_field(record)
            assert record[digest_name] == binding.canonical_payload_digest(record)
            round_tripped = json.loads(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
            )
            assert round_tripped == record
            assert binding.canonical_payload_digest(round_tripped) == record[digest_name]


def test_structural_key_refuses_non_finite_numbers() -> None:
    """Structural comparison keys use the same canonical rules as digests."""

    snapshot = {"id": "urn:test:release", "members": ["a", "b"]}
    assert binding.structural_key(snapshot) == '{"id":"urn:test:release","members":["a","b"]}'

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="Out of range float"):
            binding.structural_key({"id": "urn:test:release", "score": value})

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry.regulatory_native_controls import (
    RegulatoryNativeControlError,
    SourcePinSet,
    capture_control_values,
    extract_identifier_observations,
    load_source_pins,
    parse_control_capture,
    render_control_capture,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REFSPEC_ROOT / "research" / "evidence" / "regulatory-native-controls-2026-07-30"
SOURCE_PINS_PATH = EVIDENCE_ROOT / "source-pins.json"
CAPTURE_PATH = EVIDENCE_ROOT / "source-native-control-capture.json"
IDENTIFIER_FIXTURE_PATH = REFSPEC_ROOT / "tests" / "fixtures" / "regulatory-native-identifiers-mini.json"
CAPTURE_SHA256 = "sha256:054444ea904b3c89cdf44eac6209f56b6a896aa59ed225bc616b2bce0b9f7ec9"
CAPTURE_BYTE_LENGTH = 183372


def _identifier_fixture() -> dict[str, object]:
    return json.loads(IDENTIFIER_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_current_capture_is_exact_and_keeps_controls_outside_subjects() -> None:
    payload = CAPTURE_PATH.read_bytes()
    capture = parse_control_capture(
        payload,
        expected_sha256=CAPTURE_SHA256,
        expected_byte_length=CAPTURE_BYTE_LENGTH,
    )

    assert render_control_capture(capture) == payload
    assert len(capture.controls) == 14
    assert capture.native_payload()["identifierPolicy"] == {
        "canonicalIdentifierSelected": False,
        "cardinality": "zeroOrMore",
        "duplicatesPreserved": True,
        "requiredFields": [
            "value",
            "kind",
            "authorityUri",
            "sourceUri",
            "observedAt",
        ],
    }
    assert all(
        control["conceptIdentityPolicy"] == "notAConcept" and control["subjectUse"] == "forbidden"
        for control in capture.native_payload()["controls"]
    )


def test_capture_records_current_type_process_and_agency_catalogs() -> None:
    capture = parse_control_capture(CAPTURE_PATH.read_bytes())
    controls = {control.spec.control_id: control for control in capture.controls}

    assert {value.value: value.count for value in controls["regulations-gov-docket-type"].values} == {
        "Nonrulemaking": 213858,
        "Rulemaking": 62468,
    }
    assert {value.value: value.count for value in controls["unified-agenda-rule-stage"].values} == {
        "Completed Actions": 628,
        "Final Rule Stage": 985,
        "Long-Term Actions": 808,
        "Prerule Stage": 96,
        "Proposed Rule Stage": 1437,
    }
    assert {value.value for value in controls["regulations-gov-attachment-format"].values} == {
        "docx",
        "html",
        "jpg",
        "pdf",
        "png",
        "tif",
        "txt",
        "wpd",
        "xlsm",
        "xlsx",
    }
    assert len(controls["federal-register-agency-slug"].values) == 399
    assert controls["federal-register-agency-slug"].unresolved_value_count == 22177
    assert len(controls["federal-register-unresolved-agency-name"].values) == 714


def test_capture_makes_current_published_schema_gaps_executable() -> None:
    pins = load_source_pins(SOURCE_PINS_PATH).by_table

    assert "topics_json" not in pins["federal_register"].columns
    assert "toc_subject" not in pins["federal_register"].columns
    assert "naics" not in pins["unified_agenda"].columns
    assert "attachment_subtype" not in pins["documents"].columns


def test_same_capture_logic_runs_on_normalized_current_field_shapes() -> None:
    fixture = _identifier_fixture()
    rows = fixture["rows"]
    source_pins = load_source_pins(SOURCE_PINS_PATH)
    mini_pins = SourcePinSet(
        captured_at=source_pins.captured_at,
        spicy_regs_revision=source_pins.spicy_regs_revision,
        sources=tuple(replace(source, row_count=len(rows[source.table])) for source in source_pins.sources),
    )

    capture = capture_control_values(mini_pins, rows)
    controls = {control.spec.control_id: control for control in capture.controls}

    assert [(value.value, value.count) for value in controls["regulations-gov-attachment-format"].values] == [
        ("html", 1),
        ("pdf", 1),
    ]
    assert [value.value for value in controls["federal-register-agency-slug"].values] == [
        "commerce-department",
        "executive-office-of-the-president",
        "fish-and-wildlife-service",
        "interior-department",
        "national-oceanic-and-atmospheric-administration",
    ]


def test_identifiers_are_zero_or_more_structured_observations() -> None:
    fixture = _identifier_fixture()
    observed_at = fixture["observedAt"]
    rows = fixture["rows"]

    docket = extract_identifier_observations(
        "dockets",
        rows["dockets"][0],
        observed_at=observed_at,
    )
    assert [(item.kind, item.value) for item in docket] == [
        ("regulationsGovDocketId", "DEA-2020-0031"),
        ("regulationsGovAgencyCode", "DEA"),
        ("regulationIdentifierNumber", "1117-AB55"),
    ]

    federal = extract_identifier_observations(
        "federal_register",
        rows["federal_register"][0],
        observed_at=observed_at,
    )
    assert len(federal) == 14
    assert [item.value for item in federal if item.kind == "regulationIdentifierNumber"] == ["0648-BN93", "1018-BI38"]
    document_number = next(item for item in federal if item.kind == "federalRegisterDocumentNumber")
    assert document_number.effective_at == "2026-09-14"
    assert all(
        {
            "value",
            "kind",
            "authorityUri",
            "sourceUri",
            "observedAt",
        }
        <= set(item.native_payload())
        and "canonical" not in item.native_payload()
        for item in federal
    )

    assert (
        extract_identifier_observations(
            "documents",
            {"document_id": None},
            observed_at=observed_at,
        )
        == ()
    )


def test_duplicate_and_multiple_legitimate_identifiers_are_preserved() -> None:
    fixture = _identifier_fixture()
    federal = extract_identifier_observations(
        "federal_register",
        fixture["rows"]["federal_register"][1],
        observed_at=fixture["observedAt"],
    )

    assert [item.value for item in federal if item.kind == "federalRegisterAgencyId"] == ["538", "538"]
    assert [item.source_ordinal for item in federal if item.kind == "federalRegisterAgencySlug"] == [0, 1]

    agenda = extract_identifier_observations(
        "unified_agenda",
        fixture["rows"]["unified_agenda"][0],
        observed_at=fixture["observedAt"],
    )
    agency = next(item for item in agenda if item.kind == "unifiedAgendaAgencyCode")
    assert agency.value == "CEQ"
    assert agency.label == "Council on Environmental Quality"


def test_malformed_nested_values_and_subject_promotion_fail_closed() -> None:
    fixture = _identifier_fixture()
    bad_document = dict(fixture["rows"]["documents"][0])
    bad_document["additional_rins"] = '{"not":"an array"}'
    with pytest.raises(
        RegulatoryNativeControlError,
        match="must contain a JSON array",
    ):
        extract_identifier_observations(
            "documents",
            bad_document,
            observed_at=fixture["observedAt"],
        )

    promoted = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
    promoted["controls"][0]["subjectUse"] = "allowed"
    with pytest.raises(
        RegulatoryNativeControlError,
        match="differs from its declared control",
    ):
        parse_control_capture(json.dumps(promoted, separators=(",", ":")).encode("utf-8"))

"""Unified Agenda documented option list and legal-authority citation-type
control tests. The pinned schema documents exactly twenty "One of the
following" option lists; the parse must capture all of them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import unified_agenda_codes as ua
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "unified_agenda_codes"
SCHEMA_FIXTURE = FIXTURES / "reginfo-rin-data-ver10262011.xsd"
PREAMBLE_FIXTURE = FIXTURES / "risc-preamble-202210.pdf"


def _acquire(
    tmp_path: Path,
    pin: ua.UASnapshotPin,
    source_path: Path,
) -> ua.AcquiredUADocument:
    return ua.acquire_unified_agenda_document(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> ua.UAControlPortfolio:
    schema = ua.parse_reginfo_schema(_acquire(tmp_path, ua.UA_REGINFO_SCHEMA_2026_08_03, SCHEMA_FIXTURE))
    preamble = ua.pin_risc_preamble_evidence(_acquire(tmp_path, ua.UA_RISC_PREAMBLE_2026_08_03, PREAMBLE_FIXTURE))
    return ua.assemble_unified_agenda_portfolio(schema, preamble)


def test_live_snapshot_pins_match_exact_official_bytes() -> None:
    schema = SCHEMA_FIXTURE.read_bytes()
    preamble = PREAMBLE_FIXTURE.read_bytes()

    assert len(schema) == 22_730
    assert ua.sha256_digest(schema) == ("sha256:94fdcf4b382830cc44b9956c00439dc20a9643de402c298cee71293a14153b24")
    assert len(preamble) == 148_467
    assert ua.sha256_digest(preamble) == ("sha256:b7372fec456cf0c346bd23528ae227913e37f546bb1c03689da19ee6a44cb2a5")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = ua.UA_REGINFO_SCHEMA_2026_08_03

    acquired = _acquire(tmp_path, pin, SCHEMA_FIXTURE)
    cached = ua.acquire_unified_agenda_document(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.document.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = PREAMBLE_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> ua.FetchedUADocument:
            calls.append((source_url, timeout_seconds))
            return ua.FetchedUADocument(
                body=payload,
                status_code=200,
                content_type="application/pdf",
                resolved_url=source_url,
            )

    acquired = ua.acquire_unified_agenda_document(
        ua.UA_RISC_PREAMBLE_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(ua.UA_RISC_PREAMBLE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_reginfo_schema_serves_no_content_type_and_is_still_accepted(
    tmp_path: Path,
) -> None:
    """The real reginfo.gov server sends no Content-Type header for the XSD."""

    payload = SCHEMA_FIXTURE.read_bytes()

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> ua.FetchedUADocument:
            del timeout_seconds
            return ua.FetchedUADocument(
                body=payload,
                status_code=200,
                content_type="",
                resolved_url=source_url,
            )

    acquired = ua.acquire_unified_agenda_document(
        ua.UA_REGINFO_SCHEMA_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
    )

    assert acquired.content_type == ""


def test_rule_stage_priority_and_timetable_action_are_deterministic_not_subjects(
    tmp_path: Path,
) -> None:
    schema = ua.parse_reginfo_schema(_acquire(tmp_path, ua.UA_REGINFO_SCHEMA_2026_08_03, SCHEMA_FIXTURE))

    assert schema.rule_stage.values == (
        "Prerule Stage",
        "Proposed Rule Stage",
        "Final Rule Stage",
        "Long-Term Actions",
        "Completed Actions",
        "No Stage",
    )
    assert schema.rule_stage.raw_observed_count == 6

    assert schema.priority_category.values == (
        "Economically Significant",
        "Other Significant",
        "Substantive, Nonsignificant",
        "Routine and Frequent",
        "Info./Admin./Other",
        "Not Major",
    )
    assert schema.priority_category.raw_observed_count == 7

    assert len(schema.timetable_action.values) == 34
    assert schema.timetable_action.raw_observed_count == 35
    assert "NPRM" in schema.timetable_action.values
    assert "Final Rule" in schema.timetable_action.values
    assert "Supplemental NPRM. FInal Action" in schema.timetable_action.values

    for field in (schema.rule_stage, schema.priority_category, schema.timetable_action):
        assert all(identifier.value != "" for identifier in field.identifiers)
    assert schema.rule_stage.by_value()["Prerule Stage"] == ControlledIdentifier(
        value="Prerule Stage",
        kind="ruleStageValue",
        authority_uri=ua.UA_IDENTIFIER_AUTHORITY_URI,
        source_uri=ua.UA_REGINFO_SCHEMA.source_url,
        observed_at=ua.UA_REGINFO_SCHEMA_2026_08_03.retrieved_at,
        effective_at=None,
        source_digest=ua.UA_REGINFO_SCHEMA_2026_08_03.expected_sha256,
    )


def test_schema_parse_is_a_complete_capture_of_all_twenty_documented_lists(
    tmp_path: Path,
) -> None:
    """The census of "One of the following" blocks is pinned at exactly 20 and
    the parse covers every one of them -- that is what makes the family's
    completeCapture claim checkable rather than asserted."""

    schema = ua.parse_reginfo_schema(_acquire(tmp_path, ua.UA_REGINFO_SCHEMA_2026_08_03, SCHEMA_FIXTURE))

    assert ua.UA_DOCUMENTED_OPTION_LIST_COUNT == 20
    assert schema.documented_option_list_count == 20
    assert len(schema.documented_fields) == 20
    # The raw fixture agrees with the parsed census.
    assert SCHEMA_FIXTURE.read_text(encoding="utf-8").count("One of the following") == 20

    by_name = schema.by_field_name()
    assert len(by_name) == 20
    counts = {name: len(field.values) for name, field in by_name.items()}
    assert counts == {
        "priorityCategory": 6,
        "rinStatus": 2,
        "ruleStage": 6,
        "major": 3,
        "unfundedMandate": 4,
        "eo13771Designation": 6,
        "rfaSection610Review": 4,
        "rplanEntry": 2,
        "rfaRequired": 3,
        "smallEntity": 6,
        "govtLevel": 6,
        "federalism": 3,
        "energyAffected": 3,
        "printPaper": 3,
        "internationalInterest": 3,
        "dlineType": 4,
        "dlineActionStage": 5,
        "timetableAction": 34,
        "rinRelation": 5,
        "agencyRelation": 2,
    }
    assert sum(counts.values()) == 110
    # The three named accessors are the same objects as their census entries.
    assert schema.rule_stage is by_name["ruleStage"]
    assert schema.priority_category is by_name["priorityCategory"]
    assert schema.timetable_action is by_name["timetableAction"]


def test_new_documented_lists_carry_the_publishers_exact_wording(
    tmp_path: Path,
) -> None:
    schema = ua.parse_reginfo_schema(_acquire(tmp_path, ua.UA_REGINFO_SCHEMA_2026_08_03, SCHEMA_FIXTURE))
    by_name = schema.by_field_name()

    # RIN_STATUS: the XSD's sentence-case wording, verbatim -- the live
    # export's casing drift is the publisher's issue, not ours to repair.
    assert by_name["rinStatus"].values == (
        "First time published in the Unified Agenda",
        "Previously published in the Unified Agenda",
    )
    assert by_name["major"].values == ("Yes", "No", "Undetermined")
    assert by_name["unfundedMandate"].values == (
        "State, local, or tribal governments",
        "Private Sector",
        "No",
        "Undetermined",
    )
    assert by_name["eo13771Designation"].values == (
        "Deregulatory",
        "Regulatory",
        "Fully or Partially Exempt",
        "Not subject to, not significant",
        "Other",
        "Independent agency",
    )
    assert by_name["rfaSection610Review"].values == (
        "Completion of a Section 610 Review",
        "Rulemaking Resulting From a Section 610 Review",
        "Section 610 Review",
        "No",
    )
    assert by_name["govtLevel"].values == ("State", "Local", "Tribal", "Federal", "None", "Undetermined")
    assert by_name["smallEntity"].values == (
        "Businesses",
        "Governmental Jurisdictions",
        "Tribal",
        "Organizations",
        "No",
        "Undetermined",
    )
    assert by_name["printPaper"].values == ("Yes", "No", "NA")
    assert by_name["internationalInterest"].values == ("Yes", "No", "Not Collected")
    assert by_name["dlineType"].values == ("Statutory", "Judicial", "Overall Description", "None")
    assert by_name["dlineActionStage"].values == ("Overall Description", "NPRM", "Final", "Other", "None")
    assert by_name["rinRelation"].values == (
        "Merge with",
        "Split from",
        "Previously reported as",
        "Duplicate of",
        "Related to",
    )
    assert by_name["agencyRelation"].values == ("Joint", "Common")
    assert by_name["rplanEntry"].values == ("Yes", "No")
    # RFA_REQUIRED's documentation opens with a description sentence; the
    # option list behind the pinned prefix still parses.
    assert by_name["rfaRequired"].values == ("Yes", "No", "Undetermined")
    for field in schema.documented_fields:
        assert len(field.identifiers) == len(field.values)
        assert {identifier.kind for identifier in field.identifiers} == {f"{field.field_name}Value"}


def test_documented_option_list_census_drift_is_refused(tmp_path: Path) -> None:
    """Removing a documented block -- or adding one -- must break the census,
    not silently narrow the family's completeCapture claim."""

    payload = SCHEMA_FIXTURE.read_bytes()
    changed = payload.replace(
        b'<xs:documentation>One of the following options: "Joint" and "Common".</xs:documentation>',
        b"<xs:documentation>A relation.</xs:documentation>",
    )
    assert changed != payload
    changed_pin = ua.UASnapshotPin(
        document=ua.UA_REGINFO_SCHEMA,
        retrieved_at="2026-08-03T19:15:15Z",
        expected_sha256=ua.sha256_digest(changed),
        expected_byte_length=len(changed),
    )
    changed_path = tmp_path / "census-drift.xsd"
    changed_path.write_bytes(changed)
    acquired = ua.acquire_unified_agenda_document(changed_pin, tmp_path / "store", source_path=changed_path)

    with pytest.raises(ua.UnifiedAgendaSourceDriftError, match="census drift"):
        ua.parse_reginfo_schema(acquired)


def test_documentation_prefix_drift_is_refused(tmp_path: Path) -> None:
    """Only RFA_REQUIRED's pinned prefix sentence is allowed; a new prefix on
    any field is publisher wording this module has not reviewed."""

    payload = SCHEMA_FIXTURE.read_bytes()
    changed = payload.replace(
        b"Regulatory Flexibility Analysis Required. One of the following",
        b"Regulatory Flexibility Analysis. One of the following",
    )
    assert changed != payload
    changed_pin = ua.UASnapshotPin(
        document=ua.UA_REGINFO_SCHEMA,
        retrieved_at="2026-08-03T19:15:15Z",
        expected_sha256=ua.sha256_digest(changed),
        expected_byte_length=len(changed),
    )
    changed_path = tmp_path / "prefix-drift.xsd"
    changed_path.write_bytes(changed)
    acquired = ua.acquire_unified_agenda_document(changed_pin, tmp_path / "store", source_path=changed_path)

    with pytest.raises(ua.UnifiedAgendaSourceDriftError, match="prefix drifted"):
        ua.parse_reginfo_schema(acquired)


def test_legal_authority_citation_types_come_from_the_preamble_not_the_schema(
    tmp_path: Path,
) -> None:
    evidence = ua.pin_risc_preamble_evidence(_acquire(tmp_path, ua.UA_RISC_PREAMBLE_2026_08_03, PREAMBLE_FIXTURE))

    assert evidence.legal_authority_citation_types == ("U.S.C.", "Pub. L.", "E.O.")
    assert len(evidence.legal_authority_citation_type_identifiers) == 3
    assert {i.kind for i in evidence.legal_authority_citation_type_identifiers} == {"legalAuthorityCitationType"}


def test_portfolio_records_schema_and_preamble_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("Not Major" in gap for gap in portfolio.gaps)
    assert any("period instead of a comma" in gap for gap in portfolio.gaps)
    assert any("No Stage" in gap for gap in portfolio.gaps)
    assert any("no XSD documentation or enumeration" in gap for gap in portfolio.gaps)


def test_current_rin_record_validates_without_becoming_a_subject(
    tmp_path: Path,
) -> None:
    rin = {
        "RULE_STAGE": "Proposed Rule Stage",
        "PRIORITY_CATEGORY": "Economically Significant",
        "TIMETABLE_LIST": [
            {"TTBL_ACTION": "NPRM", "TTBL_DATE": "12/00/2022"},
        ],
        "LEGAL_AUTHORITY_LIST": [
            "5 U.S.C. 301",
            "E.O. 13279, 67 FR 77141",
        ],
    }

    validated = ua.validate_rin_controlled_fields(rin, _portfolio(tmp_path))

    assert validated.rule_stage is not None
    assert validated.rule_stage.publisher_value == "Proposed Rule Stage"
    assert validated.rule_stage.is_general_subject_concept is False
    assert validated.priority_category is not None
    assert validated.priority_category.publisher_value == "Economically Significant"
    assert [action.publisher_value for action in validated.timetable_actions] == ["NPRM"]
    assert [citation.citation_type for citation in validated.legal_authorities] == ["U.S.C.", "E.O."]
    assert all(not citation.is_general_subject_concept for citation in validated.legal_authorities)


def test_legal_authority_free_text_without_a_documented_prefix_does_not_fail_closed(
    tmp_path: Path,
) -> None:
    rin = {
        "LEGAL_AUTHORITY_LIST": ["Reorg. Plan No. 3 of 1970"],
    }

    validated = ua.validate_rin_controlled_fields(rin, _portfolio(tmp_path))

    assert validated.legal_authorities[0].citation_type is None
    assert validated.legal_authorities[0].publisher_text == "Reorg. Plan No. 3 of 1970"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("RULE_STAGE", "Made Up Stage", "RULE_STAGE has unknown value"),
        ("PRIORITY_CATEGORY", "Extremely Significant", "PRIORITY_CATEGORY has unknown value"),
    ],
)
def test_unknown_rule_stage_or_priority_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    rin = {field: value}

    with pytest.raises(ua.UnifiedAgendaAssignmentError, match=message):
        ua.validate_rin_controlled_fields(rin, _portfolio(tmp_path))


def test_unknown_timetable_action_fails_closed(tmp_path: Path) -> None:
    rin = {"TIMETABLE_LIST": [{"TTBL_ACTION": "Invented Action"}]}

    with pytest.raises(ua.UnifiedAgendaAssignmentError, match="TTBL_ACTION has unknown value"):
        ua.validate_rin_controlled_fields(rin, _portfolio(tmp_path))


def test_digest_or_structure_drift_never_becomes_a_parsed_resource(
    tmp_path: Path,
) -> None:
    payload = SCHEMA_FIXTURE.read_bytes()
    changed = payload.replace(b"Prerule Stage", b"Preruld Stage")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> ua.FetchedUADocument:
            del timeout_seconds
            return ua.FetchedUADocument(
                body=changed,
                status_code=200,
                content_type="application/xml",
                resolved_url=source_url,
            )

    with pytest.raises(ua.UnifiedAgendaSourceDriftError, match="digest drift"):
        ua.acquire_unified_agenda_document(
            ua.UA_REGINFO_SCHEMA_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        b'<xs:complexType name="RIN_INFOType"><xs:sequence/></xs:complexType>'
        b"</xs:schema>"
    )
    mini_pin = ua.UASnapshotPin(
        document=ua.UA_REGINFO_SCHEMA,
        retrieved_at="2026-08-03T19:15:15Z",
        expected_sha256=ua.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.xsd"
    mini_path.write_bytes(mini_payload)
    acquired = ua.acquire_unified_agenda_document(
        mini_pin,
        tmp_path / "shape",
        source_path=mini_path,
    )
    # The documented-list census fires before any element lookup: a schema
    # with no documented option lists is structure drift at the census.
    with pytest.raises(ua.UnifiedAgendaSourceDriftError, match="census drift"):
        ua.parse_reginfo_schema(acquired)


def test_option_count_drift_is_refused(tmp_path: Path) -> None:
    payload = SCHEMA_FIXTURE.read_bytes()
    changed = payload.replace(b'"Prerule Stage", ', b"")
    assert len(changed) != len(payload)

    mini_pin = ua.UASnapshotPin(
        document=ua.UA_REGINFO_SCHEMA,
        retrieved_at="2026-08-03T19:15:15Z",
        expected_sha256=ua.sha256_digest(changed),
        expected_byte_length=len(changed),
    )
    changed_path = tmp_path / "changed.xsd"
    changed_path.write_bytes(changed)
    acquired = ua.acquire_unified_agenda_document(
        mini_pin,
        tmp_path / "store",
        source_path=changed_path,
    )
    with pytest.raises(ua.UnifiedAgendaSourceDriftError, match="RULE_STAGE option count drift"):
        ua.parse_reginfo_schema(acquired)


def test_non_pdf_bytes_for_the_preamble_pin_are_refused(tmp_path: Path) -> None:
    fake_payload = b"not actually a pdf" + (b"x" * (148_467 - 19))
    fake_pin = ua.UASnapshotPin(
        document=ua.UA_RISC_PREAMBLE,
        retrieved_at="2026-08-03T19:13:31Z",
        expected_sha256=ua.sha256_digest(fake_payload),
        expected_byte_length=len(fake_payload),
    )
    fake_path = tmp_path / "fake.pdf"
    fake_path.write_bytes(fake_payload)
    acquired = ua.acquire_unified_agenda_document(fake_pin, tmp_path / "store", source_path=fake_path)

    with pytest.raises(ua.UnifiedAgendaSourceDriftError, match="PDF header"):
        ua.pin_risc_preamble_evidence(acquired)


def test_source_document_rejects_non_reginfo_host() -> None:
    with pytest.raises(ua.UnifiedAgendaAcquisitionError):
        replace(ua.UA_REGINFO_SCHEMA, source_url="https://example.com/reginfo.xsd")


def test_naics_and_agency_sort_codes_are_not_modeled_as_controlled_values(
    tmp_path: Path,
) -> None:
    """Binding scope: the subject index uses Federal Register terms; agency sort
    codes and NAICS are not topics, so this module never packages them."""

    portfolio = _portfolio(tmp_path)

    field_names = {
        portfolio.rule_stage.field_name,
        portfolio.priority_category.field_name,
        portfolio.timetable_action.field_name,
    }
    assert field_names == {"ruleStage", "priorityCategory", "timetableAction"}
    assert not hasattr(portfolio, "naics")
    assert not hasattr(portfolio, "agency_sort_codes")

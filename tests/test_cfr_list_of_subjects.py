"""Real-source tests for Federal Register List of Subjects evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from refspec.registry import cfr_list_of_subjects as cfr
from refspec.storage import canonical_json


def _required_real_path(environment_name: str) -> Path:
    value = os.environ.get(environment_name)
    if value is None:
        pytest.skip(f"{environment_name} is materialized by the registry real-data gate")
    path = Path(value)
    assert path.is_file()
    return path


def _document_payload(**changes: object) -> bytes:
    value: dict[str, object] = {
        "document_number": "2026-TEST",
        "publication_date": "2026-08-03",
        "type": "Rule",
        "title": "Reviewed source-shape test",
        "json_url": "https://www.federalregister.gov/api/v1/documents/2026-TEST.json",
        "html_url": "https://www.federalregister.gov/documents/2026/08/03/2026-TEST/example",
        "topics": ["Administrative practice and procedure"],
        "cfr_references": [{"chapter": None, "citation_url": None, "part": "52", "title": 40}],
    }
    value.update(changes)
    return canonical_json(value).encode("utf-8")


def test_module_import_performs_no_network_access() -> None:
    assert callable(cfr.inspect_ecfr_part_sources)
    assert callable(cfr.parse_federal_register_document_assignments)


def test_real_ecfr_api_shapes_show_structure_and_requirement_not_assignments() -> None:
    structure_path = _required_real_path("REFSPEC_ECFR_TITLE_1_STRUCTURE_PATH")
    full_text_path = _required_real_path("REFSPEC_ECFR_TITLE_1_PART_18_XML_PATH")
    titles_path = _required_real_path("REFSPEC_ECFR_TITLES_PATH")
    agencies_path = _required_real_path("REFSPEC_ECFR_AGENCIES_PATH")

    inspected = cfr.inspect_ecfr_part_sources(
        structure_path.read_bytes(),
        full_text_path.read_bytes(),
        titles_path.read_bytes(),
        agencies_path.read_bytes(),
        cfr_title=1,
        cfr_part="18",
    )

    assert inspected.part_label == "Part 18—Preparation and Transmittal of Documents Generally"
    assert inspected.section_count == 16
    assert inspected.chapter == "I"
    assert inspected.catalog_date == "2026-07-31"
    assert inspected.title_name == "General Provisions"
    assert inspected.title_latest_issue_date == "2024-05-17"
    assert inspected.title_up_to_date_as_of == "2026-07-31"
    assert inspected.title_count == 50
    assert inspected.top_level_agency_count == 153
    assert inspected.total_agency_count == 316
    assert inspected.responsible_agencies == ("Administrative Committee of the Federal Register",)
    assert inspected.titles_source_byte_length == 8_033
    assert inspected.titles_source_sha256 == ("sha256:4a1eb3090dfc5a6b13a495d2ad7a5e92ab9c3816098566c637688cb94c871734")
    assert inspected.agencies_source_byte_length == 98_197
    assert inspected.agencies_source_sha256 == (
        "sha256:766685f466d62fa558a504cdeac23eef1d41f3ea24a2f5a3f78b38f2bcd5365e"
    )
    assert inspected.structure_source_byte_length == 94_089
    assert inspected.structure_source_sha256 == (
        "sha256:ac27352aff9ba6822ef2ec3081c5e55fd8bedc1b0a945bc8c53a0e4bda22b1c8"
    )
    assert inspected.full_text_source_byte_length == 15_270
    assert inspected.full_text_source_sha256 == (
        "sha256:32ec60511131ff9f3ac87d2bc6168b9b2dff1df5f177916e8df546f07ae86583"
    )
    assert inspected.list_requirement_present is True
    assert inspected.published_subject_assignment_count == 0
    assert inspected.assignment_source == "federalRegisterDocumentJson"


def test_real_current_document_shape_count_and_samples() -> None:
    source_path = _required_real_path("REFSPEC_FR_DOCUMENT_2026_15493_PATH")
    parsed = cfr.parse_federal_register_document_assignments(
        source_path.read_bytes(),
        expected_document_number="2026-15493",
    )

    assert parsed.source_byte_length == 4_320
    assert parsed.source_sha256 == ("sha256:1983a61f00d6556abe1c6e37d6a605a022471f6fa4e010690b718d5330067c67")
    assert parsed.publication_date == "2026-07-31"
    assert parsed.document_type == "Rule"
    assert parsed.assignment_count == 12
    assert parsed.cfr_references == (cfr.CFRReference(title=40, part="52", chapter=None, citation_url=None),)
    assert [item.official_label for item in parsed.terms[:3]] == [
        "Air pollution control",
        "Carbon monoxide",
        "Environmental protection",
    ]
    assert parsed.terms[-1].official_label == "Volatile organic compounds"
    assert parsed.terms[-3].official_label == "Reporting and recordkeeping requirements"
    assert [item.source_ordinal for item in parsed.terms] == list(range(1, 13))
    assert all(item.identity_status == "publisherIdentifierAbsent" for item in parsed.terms)
    assert len({item.record_iri for item in parsed.terms}) == 12


def test_real_part_18_document_preserves_empty_topics_and_multiple_cfr_references() -> None:
    source_path = _required_real_path("REFSPEC_FR_DOCUMENT_96_32865_PATH")
    parsed = cfr.parse_federal_register_document_assignments(
        source_path.read_bytes(),
        expected_document_number="96-32865",
    )

    assert parsed.source_byte_length == 2_928
    assert parsed.source_sha256 == ("sha256:da1d4e6af2e7e5680c382400034c900630048dc9f980b8b24de86c2cb88364e8")
    assert parsed.assignment_count == 0
    assert [item.citation for item in parsed.cfr_references] == [
        "1 CFR Part 5",
        "1 CFR Part 11",
        "1 CFR Part 18",
    ]
    assert parsed.readiness.source_term_count == 0


def test_real_assignment_evidence_is_document_scoped_and_deterministic() -> None:
    source_path = _required_real_path("REFSPEC_FR_DOCUMENT_2026_15493_PATH")
    parsed = cfr.parse_federal_register_document_assignments(source_path.read_bytes())

    evidence = cfr.cfr_list_of_subjects_assignment_evidence(parsed)
    encoded = cfr.cfr_list_of_subjects_assignment_evidence_bytes(parsed)

    assert evidence["evidenceKind"] == "federalRegisterDocumentListOfSubjects"
    assert evidence["role"] == "sourceAssignedFilingEvidence"
    assert evidence["documentNumber"] == "2026-15493"
    assert evidence["termCount"] == 12
    assert evidence["cfrReferences"] == [{"title": 40, "part": "52", "chapter": None, "citationUrl": None}]
    assert evidence["conceptIdentityClaimed"] is False
    assert "acceptedOutputUseAuthorized" not in evidence
    assert "document-level arrays" in evidence["scopeNote"]
    assert encoded == canonical_json(evidence).encode("utf-8") + b"\n"
    assert json.loads(encoded) == evidence


def test_multiple_cfr_references_do_not_multiply_document_topics() -> None:
    payload = _document_payload(
        topics=["Air pollution control", "Reporting and recordkeeping requirements"],
        cfr_references=[
            {"chapter": None, "citation_url": None, "part": 51, "title": 40},
            {"chapter": None, "citation_url": None, "part": "52", "title": 40},
        ],
    )
    parsed = cfr.parse_federal_register_document_assignments(payload)
    evidence = cfr.cfr_list_of_subjects_assignment_evidence(parsed)

    assert parsed.assignment_count == 2
    assert len(parsed.cfr_references) == 2
    assert evidence["termCount"] == 2


def test_empty_topics_are_valid_source_evidence_not_invented_terms() -> None:
    parsed = cfr.parse_federal_register_document_assignments(_document_payload(topics=[]))

    assert parsed.terms == ()
    assert parsed.assignment_count == 0
    assert parsed.readiness.ready is False


def test_promotion_is_refused() -> None:
    parsed = cfr.parse_federal_register_document_assignments(_document_payload())

    with pytest.raises(cfr.CFRPromotionError, match="filing evidence"):
        parsed.readiness.require_ready()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"topics": "Air pollution control"}, "topics must be an array"),
        ({"topics": ["Air pollution control", "Air pollution control"]}, "duplicate label"),
        ({"cfr_references": []}, "non-empty array"),
        ({"publication_date": "July 31, 2026"}, "YYYY-MM-DD"),
        ({"json_url": "https://example.test/document.json"}, "official HTTPS host"),
    ],
)
def test_document_source_shape_drift_fails_closed(changes: dict[str, object], message: str) -> None:
    with pytest.raises(cfr.CFRSourceDriftError, match=message):
        cfr.parse_federal_register_document_assignments(_document_payload(**changes))


def test_expected_document_number_mismatch_fails_closed() -> None:
    with pytest.raises(cfr.CFRSourceDriftError, match="expected document"):
        cfr.parse_federal_register_document_assignments(
            _document_payload(),
            expected_document_number="2026-OTHER",
        )


def test_ecfr_source_shape_drift_fails_closed() -> None:
    structure = canonical_json(
        {
            "type": "title",
            "identifier": "1",
            "children": [
                {
                    "type": "chapter",
                    "identifier": "I",
                    "children": [
                        {
                            "type": "part",
                            "identifier": "18",
                            "label": "Part 18—Example",
                            "children": [{"type": "section", "identifier": "18.1"}],
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")
    xml_without_requirement = b'<DIV5 TYPE="PART" N="18"><DIV8 N="18.1" /></DIV5>'
    titles = canonical_json(
        {
            "titles": [
                {
                    "number": 1,
                    "name": "General Provisions",
                    "latest_issue_date": "2024-05-17",
                    "up_to_date_as_of": "2026-07-31",
                }
            ],
            "meta": {"date": "2026-07-31", "import_in_progress": False},
        }
    ).encode("utf-8")
    agencies = canonical_json(
        {
            "agencies": [
                {
                    "name": "Administrative Committee of the Federal Register",
                    "slug": "federal-register-administrative-committee",
                    "children": [],
                    "cfr_references": [{"title": 1, "chapter": "I"}],
                }
            ]
        }
    ).encode("utf-8")

    with pytest.raises(cfr.CFRSourceDriftError, match="List of Subjects requirement"):
        cfr.inspect_ecfr_part_sources(
            structure,
            xml_without_requirement,
            titles,
            agencies,
            cfr_title=1,
            cfr_part="18",
        )

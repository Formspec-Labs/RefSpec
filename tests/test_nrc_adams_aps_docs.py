"""NRC ADAMS Public Search publisher-PDF reader coverage.

Both fixtures are byte-exact captures of the PDFs NRC publishes on the APS
host itself; every description asserted here is the publisher's verbatim
text, with PDF presentation forms folded per ``refspec.pdf_text``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.pdf_text import PDF_TEXT_FOLDS
from refspec.registry import nrc_adams_aps_docs as aps

ROOT = Path(__file__).resolve().parents[1]
MANUAL_PATH = ROOT / "tests/fixtures/nrc_adams_aps_docs/aps-user-manual-2026-08-15.pdf"
GUIDE_PATH = ROOT / "tests/fixtures/nrc_adams_aps_docs/aps-api-guide-v1-2026-08-15.pdf"


def test_user_manual_parses_all_22_documented_profile_properties() -> None:
    manual = aps.parse_aps_user_manual(MANUAL_PATH, pin=aps.APS_USER_MANUAL_2026_08_15)

    # The 22-property roster itself is enforced inside the parser by the
    # geometric name-column measurement (see
    # test_property_roster_is_measured_from_the_page_not_assumed); what this
    # test owns is the publisher's description content.
    by_name = {prop.name: prop for prop in manual.properties}
    # Verbatim publisher descriptions, including the ones that carry inline
    # bullets and publisher examples.
    assert by_name["Addressee Affiliation"].description == (
        "The name of the organization receiving the agency document(s)"
    )
    assert by_name["Document Type"].description == (
        "Indicates a specific document type: • NRC bulletin • contract • SECY paper"
    )
    assert by_name["Docket Number"].description.startswith(
        "An NRC-assigned number that uniquely identifies a facility, licensee, or activity."
    )
    assert "“(MV)” designates that this is a multivalued property" in by_name["Docket Number"].description
    assert by_name["Packages Filed In"].description == (
        "Indicates the accession number of the ADAMS package in which a document resides"
    )
    # The section is captured from the manual's own table pages, not the
    # table of contents, so no description is empty and none leaks the
    # Wildcards section that follows the table.
    for prop in manual.properties:
        assert prop.description
        assert "Wildcard" not in prop.description


def test_property_roster_is_measured_from_the_page_not_assumed() -> None:
    """The parser counts the table's name-column cells from page geometry and
    refuses any mismatch with the reviewed names -- a silently added, removed,
    or renamed row is drift, not text swallowed into a neighbour's description."""

    measured = aps._measured_property_name_column
    from pypdf import PdfReader

    reader = PdfReader(MANUAL_PATH)
    column = measured(reader)
    # The measurement agrees with the reviewed roster on the pinned bytes.
    aps._verify_measured_property_roster(column)

    # An added row (a 23rd name in the column) is refused.
    with pytest.raises(aps.NRCAPSSourceDriftError, match="added, removed, or renamed"):
        aps._verify_measured_property_roster(column + "LegacyLibrary")
    # A removed row is refused.
    with pytest.raises(aps.NRCAPSSourceDriftError, match="added, removed, or renamed"):
        aps._verify_measured_property_roster(column.replace("MicroformAddress", ""))
    # A renamed row is refused.
    with pytest.raises(aps.NRCAPSSourceDriftError, match="added, removed, or renamed"):
        aps._verify_measured_property_roster(column.replace("Keyword", "Keywords"))


def test_user_manual_descriptions_carry_no_pdf_presentation_forms() -> None:
    manual = aps.parse_aps_user_manual(MANUAL_PATH, pin=aps.APS_USER_MANUAL_2026_08_15)

    for prop in manual.properties:
        for artefact in PDF_TEXT_FOLDS:
            assert artefact not in prop.description
            assert artefact not in prop.name


def test_official_accession_number_definition_states_exactly_two_elements() -> None:
    manual = aps.parse_aps_user_manual(MANUAL_PATH, pin=aps.APS_USER_MANUAL_2026_08_15)
    accession = manual.accession_number

    assert accession.definition.startswith(
        "A system-generated identification number (ID) assigned when a document or "
        "package is first added to an ADAMS Library"
    )
    assert len(accession.elements) == 2
    assert accession.elements[0].text == (
        "two-character alphabetic code (e.g., “ML” to indicate the original library)"
    )
    assert accession.elements[1].text == "nine-character numeric code, known as the “ADAMS Item ID”"
    # The official definition documents no finer structure for the
    # nine-character ADAMS Item ID: the REF-032-refused MLYYDDDNNNN
    # decomposition appears nowhere in the publisher's text and the parser
    # never derives one.
    assert "YY" not in accession.definition
    assert "DDD" not in accession.definition


def test_user_manual_records_its_snapshot_and_succession_markers_verbatim() -> None:
    manual = aps.parse_aps_user_manual(MANUAL_PATH, pin=aps.APS_USER_MANUAL_2026_08_15)

    assert manual.wba_replacement_statement == (
        "This application will replace the previous Web-Based ADAMS search application."
    )
    # The manual prints no version statement; the PDF document-information
    # timestamps are the available revision markers, recorded verbatim.
    assert manual.document_information == {
        "Title": "ADAMS Public Search (APS)",
        "Subject": "User Manual",
        "CreationDate": "D:20260610121143-04'00'",
        "ModDate": "D:20260610121157-04'00'",
        "SourceModified": "D:20260610161102",
    }


def test_api_guide_parses_operators_dates_and_request_parameters() -> None:
    guide = aps.parse_aps_api_guide(GUIDE_PATH, pin=aps.APS_API_GUIDE_2026_08_15)

    assert guide.self_described_version == "Version 1.0"

    assert tuple(op.token for op in guide.text_operators) == aps.APS_TEXT_OPERATOR_TOKENS
    assert [op.label for op in guide.text_operators] == [
        "Contains",
        "Does Not Contain",
        "Starts With",
        "Does Not Start With",
        "Equals",
        "Does Not Equal",
    ]
    by_token = {op.token: op for op in guide.text_operators}
    assert by_token["contains"].description == "The field contains the search term"
    assert by_token["equals"].description == "exact match of the value for that field"
    # The publisher states no description sentence for the two Starts With
    # operators; nothing is invented for them.
    assert by_token["starts"].description is None
    assert by_token["notstarts"].description is None

    assert guide.date_property_names == ("DateAddedTimestamp", "DocumentDate")

    assert (
        tuple(parameter.name for parameter in guide.search_request_parameters)
        == aps.APS_SEARCH_REQUEST_PARAMETER_NAMES
    )
    by_name = {parameter.name: parameter for parameter in guide.search_request_parameters}
    assert by_name["q"].declared_type == "string"
    assert by_name["q"].description == "Search query text"
    assert by_name["legacyLibFilter"].declared_type == "boolean"
    assert by_name["legacyLibFilter"].description == "Include legacy library (pre-1999)"
    assert by_name["skip"].description.startswith("[Default =0] Number of items to skip")

    (get_parameter,) = guide.get_document_parameters
    assert get_parameter.name == "accessionNumber"
    assert get_parameter.declared_type == "location: path, required"
    assert get_parameter.description == "Unique NRC accession number (e.g., ML12345A678)."


def test_api_guide_appendix_a_document_properties_are_captured_not_lost() -> None:
    """Appendix A states thirteen API document-property names. They are
    captured and drift-checked -- no Atlas release emits them, and the
    releases record that boundary in notEmitted metadata -- so the appendix
    is an accounted-for decision rather than an unrecorded page."""

    guide = aps.parse_aps_api_guide(GUIDE_PATH, pin=aps.APS_API_GUIDE_2026_08_15)

    assert guide.appendix_document_property_names == (
        "AccessionNumber",
        "DocumentTitle",
        "AuthorName",
        "AuthorAffiliation",
        "AddresseeName",
        "AddresseeAffiliation",
        "DocumentDate",
        "DocumentType",
        "Keyword",
        "DocketNumber",
        "DateAddedTimestamp",
        "EstimatedPageCount",
        "Url",
    )
    assert len(guide.appendix_document_property_names) == 13


def test_get_document_second_parameter_is_roster_drift_not_swallowed_text() -> None:
    """A second documented Get Document parameter must surface as drift.

    The item pattern stops each description at the next ``- name (location:``
    bullet (the Search Document Library pattern's lookahead); without it the
    first description swallowed every following bullet and a new publisher
    parameter would have vanished into prose instead of refusing.
    """

    two_parameter_region = (
        "- accessionNumber (location: path, required): Unique NRC accession "
        "number (e.g., ML12345A678). "
        "- includeContent (location: query, required): Whether to include the "
        "indexed plain-text content."
    )
    matches = list(aps._API_GET_DOCUMENT_ITEM_RE.finditer(two_parameter_region))
    assert [match.group("name") for match in matches] == ["accessionNumber", "includeContent"]
    # The first description stops at the second bullet instead of swallowing it.
    assert matches[0].group("description").strip() == (
        "Unique NRC accession number (e.g., ML12345A678)."
    )

    with pytest.raises(aps.NRCAPSSourceDriftError, match="Get Document parameters drifted"):
        aps._parse_get_document_parameters(two_parameter_region)


def test_api_guide_records_the_sign_in_portal_statements_verbatim() -> None:
    guide = aps.parse_aps_api_guide(GUIDE_PATH, pin=aps.APS_API_GUIDE_2026_08_15)

    assert guide.developer_portal_statements == (
        (
            "The most current properties available for search are published via the "
            "ADAMS Public Search API Developer Portal for each of the endpoints "
            "discussed below in section 3."
        ),
        (
            "The API also has a Developer Portal is published at: "
            "https://adams-api-developer.nrc.gov/ for more direct access."
        ),
        "The Developer Portal will have the latest list of available properties.",
    )
    assert guide.document_information == {
        "CreationDate": "D:20251125135020-05'00'",
        "ModDate": "D:20251125135020-05'00'",
    }


def test_drifted_bytes_never_become_a_parsed_document(tmp_path: Path) -> None:
    payload = bytearray(MANUAL_PATH.read_bytes())
    payload[-1] ^= 0xFF
    tampered = tmp_path / "aps-user-manual-tampered.pdf"
    tampered.write_bytes(bytes(payload))
    with pytest.raises(aps.NRCAPSSourceDriftError, match="digest drift"):
        aps.parse_aps_user_manual(tampered, pin=aps.APS_USER_MANUAL_2026_08_15)

    truncated = tmp_path / "aps-api-guide-truncated.pdf"
    truncated.write_bytes(GUIDE_PATH.read_bytes()[:1000])
    with pytest.raises(aps.NRCAPSSourceDriftError, match="byte length drift"):
        aps.parse_aps_api_guide(truncated, pin=aps.APS_API_GUIDE_2026_08_15)

    missing = tmp_path / "not-there.pdf"
    with pytest.raises(aps.NRCAPSAcquisitionError, match="not a regular file"):
        aps.parse_aps_user_manual(missing, pin=aps.APS_USER_MANUAL_2026_08_15)


def test_pins_accept_only_the_official_host() -> None:
    with pytest.raises(aps.NRCAPSAcquisitionError, match="official HTTPS adams-search.nrc.gov"):
        aps.NRCAPSPdfPin(
            source_url="https://example.com/APS-User-Manual.pdf",
            retrieved_at="2026-08-15T13:56:07Z",
            expected_sha256=aps.APS_USER_MANUAL_2026_08_15.expected_sha256,
            expected_byte_length=1,
            expected_page_count=1,
        )
    with pytest.raises(aps.NRCAPSAcquisitionError, match="lowercase sha256"):
        aps.NRCAPSPdfPin(
            source_url=aps.APS_USER_MANUAL_URL,
            retrieved_at="2026-08-15T13:56:07Z",
            expected_sha256="sha256:notahash",
            expected_byte_length=1,
            expected_page_count=1,
        )

"""Tests for the NPPES NPI/CCN identifier-authority capture.

All fixtures are local files; no test opens a network connection.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView
from refspec.registry.nppes_npi_identifiers import (
    NPPES_CAPTURED_AT,
    NPPES_ENTITY_TYPE_CODES,
    NPPES_EXPECTED_FIELD_COUNT,
    NPPES_FILE_LAYOUT_RESOURCE_ID,
    NPPES_FILEHEADER_BYTE_LENGTH,
    NPPES_FILEHEADER_SHA256,
    NPPES_NPI_FILES_PAGE_URL,
    NPPES_SAMPLE_BYTE_LENGTH,
    NPPES_SAMPLE_SHA256,
    NUCC_PROVIDER_TAXONOMY_REFERENCE_URL,
    NppesIdentifierError,
    build_nppes_file_layout_bundle,
    npi_check_digit,
    parse_fileheader_columns,
    parse_npi_sample,
    validate_ccn,
    validate_npi,
)

FIXTURES = Path(__file__).parent / "fixtures" / "nppes_npi_identifiers"
FILEHEADER_PAYLOAD = (FIXTURES / "npidata_pfile_fileheader_v2.csv").read_bytes()
SAMPLE_PAYLOAD = (FIXTURES / "npidata_pfile_sample_v2.csv").read_bytes()

# Three real, publicly disseminated NPIs captured in the pinned sample excerpt.
REAL_NPIS = ("1851806699", "1699600866", "1669740403")


# --- Fixture integrity -------------------------------------------------


def test_fixtures_match_their_pinned_digests_and_lengths() -> None:
    assert len(FILEHEADER_PAYLOAD) == NPPES_FILEHEADER_BYTE_LENGTH
    assert len(SAMPLE_PAYLOAD) == NPPES_SAMPLE_BYTE_LENGTH


# --- NPI Luhn structure --------------------------------------------------


@pytest.mark.parametrize("npi", REAL_NPIS)
def test_validate_npi_accepts_real_captured_npis(npi: str) -> None:
    assert validate_npi(npi) == npi


@pytest.mark.parametrize("npi", REAL_NPIS)
def test_npi_check_digit_matches_the_tenth_digit_of_real_npis(npi: str) -> None:
    assert npi_check_digit(npi[:9]) == npi[9]


def test_validate_npi_rejects_a_wrong_check_digit() -> None:
    tampered = REAL_NPIS[0][:9] + str((int(REAL_NPIS[0][9]) + 1) % 10)
    with pytest.raises(NppesIdentifierError, match="Luhn"):
        validate_npi(tampered)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "123456789",  # 9 digits
        "12345678901",  # 11 digits
        "185180669A",  # non-digit
        "185-180-6699",  # punctuated
    ],
)
def test_validate_npi_rejects_malformed_shapes(value: str) -> None:
    with pytest.raises(NppesIdentifierError):
        validate_npi(value)


def test_npi_check_digit_rejects_a_base_of_the_wrong_length() -> None:
    with pytest.raises(NppesIdentifierError, match="9 ASCII digits"):
        npi_check_digit("12345")


# --- CCN shape -------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "010001",  # 6-char: numeric state + numeric sequence
        "05P000",  # 6-char OPO-style alpha marker in the suffix
        "36E123",  # 6-char emergency-hospital-style alpha marker
        "01Q1234567",  # 10-char HHA-branch-style suffix
        "13B0000001",  # 10-char Part B supplier-style suffix
    ],
)
def test_validate_ccn_accepts_documented_shapes(value: str) -> None:
    assert validate_ccn(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0100",  # too short
        "0100001",  # 7 characters: neither 6 nor 10
        "1A0001",  # alpha character in the state-code position
        "01000a",  # lowercase suffix
        "010001234567",  # too long
    ],
)
def test_validate_ccn_rejects_malformed_shapes(value: str) -> None:
    with pytest.raises(NppesIdentifierError):
        validate_ccn(value)


# --- NPPES file-header layout -----------------------------------------------


def test_parse_fileheader_columns_reads_the_real_captured_header() -> None:
    columns = parse_fileheader_columns(FILEHEADER_PAYLOAD)

    assert len(columns) == NPPES_EXPECTED_FIELD_COUNT
    assert len(set(columns)) == len(columns)
    assert columns[0] == "NPI"
    assert columns[1] == "Entity Type Code"
    assert "Healthcare Provider Taxonomy Code_1" in columns


def test_parse_fileheader_columns_verifies_its_pin() -> None:
    with pytest.raises(NppesIdentifierError, match="digest"):
        parse_fileheader_columns(FILEHEADER_PAYLOAD, expected_sha256="sha256:" + "0" * 64)
    with pytest.raises(NppesIdentifierError, match="byte length"):
        parse_fileheader_columns(FILEHEADER_PAYLOAD, expected_byte_length=1)

    columns = parse_fileheader_columns(
        FILEHEADER_PAYLOAD,
        expected_sha256=NPPES_FILEHEADER_SHA256,
        expected_byte_length=NPPES_FILEHEADER_BYTE_LENGTH,
    )
    assert len(columns) == NPPES_EXPECTED_FIELD_COUNT


def test_parse_fileheader_columns_rejects_empty_payload() -> None:
    with pytest.raises(NppesIdentifierError, match="non-empty"):
        parse_fileheader_columns(b"")


def test_parse_fileheader_columns_rejects_more_than_one_header_line() -> None:
    payload = b'"NPI","Entity Type Code"\n"1234567893","1"\n'
    with pytest.raises(NppesIdentifierError, match="exactly one"):
        parse_fileheader_columns(payload)


def test_parse_fileheader_columns_rejects_duplicate_columns() -> None:
    payload = b'"NPI","NPI","Entity Type Code"\n'
    with pytest.raises(NppesIdentifierError, match="unique"):
        parse_fileheader_columns(payload)


def test_parse_fileheader_columns_rejects_an_empty_column_name() -> None:
    payload = b'"NPI","","Entity Type Code"\n'
    with pytest.raises(NppesIdentifierError, match="non-empty"):
        parse_fileheader_columns(payload)


# --- NPPES file-layout bundle -----------------------------------------------


def test_file_layout_bundle_packages_every_field_as_deterministic_metadata() -> None:
    bundle = build_nppes_file_layout_bundle(FILEHEADER_PAYLOAD)

    assert bundle.resource_manifest["resourceId"] == NPPES_FILE_LAYOUT_RESOURCE_ID
    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["candidateUseAuthorized"] is False
    assert bundle.resource_manifest["observationCount"] == NPPES_EXPECTED_FIELD_COUNT
    assert len(bundle.observations) == NPPES_EXPECTED_FIELD_COUNT
    assert bundle.observations[0]["labels"][0]["value"] == "NPI"
    for observation in bundle.observations:
        assert observation["eligibleUses"] == ["deterministicMetadata"]
        assert observation["conceptIdentityClaimed"] is False


def test_file_layout_bundle_never_captures_a_nucc_taxonomy_code_value() -> None:
    bundle = build_nppes_file_layout_bundle(FILEHEADER_PAYLOAD)
    values = {observation["labels"][0]["value"] for observation in bundle.observations}

    # Every captured value is a human-readable field *name*; none of them is
    # shaped like an actual NUCC taxonomy code value (nine digits/letters
    # plus a literal "X", for example "207Q00000X").
    nucc_code_shape = re.compile(r"^[0-9A-Z]{9}X$")
    assert not any(nucc_code_shape.fullmatch(value) for value in values)
    assert "Healthcare Provider Taxonomy Code_1" in values
    assert "207Q00000X" not in values


def test_file_layout_bundle_is_deterministic() -> None:
    first = build_nppes_file_layout_bundle(FILEHEADER_PAYLOAD)
    second = build_nppes_file_layout_bundle(FILEHEADER_PAYLOAD)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest


def test_file_layout_bundle_round_trips_through_a_closed_package(tmp_path: Path) -> None:
    bundle = build_nppes_file_layout_bundle(FILEHEADER_PAYLOAD)
    package_path = bundle.write_to(tmp_path / "package")

    opened = SourceControlledResourceView.open(package_path)

    assert opened.logical_digest == bundle.logical_digest
    assert len(opened.observations) == NPPES_EXPECTED_FIELD_COUNT
    assert (
        opened.source_artifact_bytes("urn:ref:nppes:source:npi-file-header-v2:2026-07-27-2026-08-02")
        == FILEHEADER_PAYLOAD
    )


# --- Small pinned NPI sample -------------------------------------------------


def test_parse_npi_sample_validates_real_captured_rows() -> None:
    columns = parse_fileheader_columns(FILEHEADER_PAYLOAD)
    identifiers = parse_npi_sample(SAMPLE_PAYLOAD, columns)

    assert len(identifiers) == 3
    assert {identifier.value for identifier in identifiers} == set(REAL_NPIS)
    for identifier in identifiers:
        assert identifier.kind == "nationalProviderIdentifier"
        assert identifier.authority_uri == "https://nppes.cms.hhs.gov/"
        assert identifier.observed_at == NPPES_CAPTURED_AT
        assert identifier.source_digest == NPPES_SAMPLE_SHA256


def test_parse_npi_sample_verifies_its_pin() -> None:
    columns = parse_fileheader_columns(FILEHEADER_PAYLOAD)
    with pytest.raises(NppesIdentifierError, match="digest"):
        parse_npi_sample(SAMPLE_PAYLOAD, columns, expected_sha256="sha256:" + "0" * 64)


def test_parse_npi_sample_rejects_a_header_mismatched_with_the_pinned_layout() -> None:
    columns = ("NPI", "Entity Type Code")  # deliberately wrong/short layout
    with pytest.raises(NppesIdentifierError, match="does not match"):
        parse_npi_sample(SAMPLE_PAYLOAD, columns)


def test_parse_npi_sample_rejects_a_row_with_an_invalid_npi() -> None:
    columns = parse_fileheader_columns(FILEHEADER_PAYLOAD)
    header_line = ",".join(f'"{c}"' for c in columns)
    bad_row = ['"1234567890"'] + ['"1"'] + [""] * (len(columns) - 2)
    payload = (header_line + "\n" + ",".join(bad_row) + "\n").encode("utf-8")

    with pytest.raises(NppesIdentifierError):
        parse_npi_sample(payload, columns)


def test_parse_npi_sample_rejects_an_unrecognized_entity_type_code() -> None:
    columns = parse_fileheader_columns(FILEHEADER_PAYLOAD)
    header_line = ",".join(f'"{c}"' for c in columns)
    bad_row = ['"1234567893"'] + ['"9"'] + [""] * (len(columns) - 2)
    payload = (header_line + "\n" + ",".join(bad_row) + "\n").encode("utf-8")

    with pytest.raises(NppesIdentifierError, match="Entity Type Code"):
        parse_npi_sample(payload, columns)


def test_parse_npi_sample_requires_at_least_one_data_row() -> None:
    columns = parse_fileheader_columns(FILEHEADER_PAYLOAD)
    header_line = ",".join(f'"{c}"' for c in columns)
    payload = (header_line + "\n").encode("utf-8")

    with pytest.raises(NppesIdentifierError, match="at least one data row"):
        parse_npi_sample(payload, columns)


# --- NUCC exclusion ----------------------------------------------------------


def test_module_references_nucc_but_never_captures_its_codes() -> None:
    assert NUCC_PROVIDER_TAXONOMY_REFERENCE_URL.startswith("https://nucc.org/")
    import refspec.registry.nppes_npi_identifiers as module

    assert not hasattr(module, "parse_nucc_taxonomy")
    assert not hasattr(module, "NUCC_TAXONOMY_CODES")


def test_entity_type_codes_are_the_native_nppes_pair() -> None:
    assert NPPES_ENTITY_TYPE_CODES == frozenset({"1", "2"})


def test_page_url_matches_the_catalogued_source() -> None:
    assert NPPES_NPI_FILES_PAGE_URL == "https://download.cms.gov/nppes/NPI_Files.html"

"""Tests for EPA SRS/CompTox substance identifier shape and pinned samples.

Fixture-based only: every test parses bytes already on disk or built
in-process.  No test opens a network connection, and importing the module
under test must not either.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from refspec.registry.epa_srs_substances import (
    CAS_REGISTRY_AUTHORITY_URI,
    DTXCID_AUTHORITY_URI,
    DTXSID_AUTHORITY_URI,
    MAX_SUBSTANCE_SAMPLE_SIZE,
    EpaSrsSubstanceError,
    SubstanceIdentifierRecord,
    SubstanceSample,
    parse_comptox_detail_page,
    parse_substance_sample,
    validate_casrn,
    validate_dtxcid,
    validate_dtxsid,
)
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "epa_srs_substances" / "substance_sample.json"


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _fixture_mapping() -> dict:
    return json.loads(_fixture_bytes())


def _mutated_fixture(mutate) -> bytes:
    value = _fixture_mapping()
    mutate(value)
    return json.dumps(value).encode("utf-8")


# --- DTXSID shape -----------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "DTXSID7020182",  # Bisphenol A, confirmed against a live CompTox capture
        "DTXSID80999901",
        "DTXSID209999",
    ],
)
def test_validate_dtxsid_accepts_the_documented_shape(value: str) -> None:
    assert validate_dtxsid(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "DTXSID",
        "DTXSID12",
        "dtxsid7020182",
        "DTXSID702018X",
        "DTXCID30182",
        " DTXSID7020182",
    ],
)
def test_validate_dtxsid_rejects_malformed_values(value: str) -> None:
    with pytest.raises(EpaSrsSubstanceError, match="DTXSID"):
        validate_dtxsid(value)


def test_validate_dtxsid_rejects_a_dtxcid_shaped_value() -> None:
    """DTXSID (substance) and DTXCID (structure) never collide by construction."""

    with pytest.raises(EpaSrsSubstanceError):
        validate_dtxsid("DTXCID30182")


# --- DTXCID shape -------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "DTXCID30182",  # Bisphenol A structure identifier
        "DTXCID609999",
    ],
)
def test_validate_dtxcid_accepts_the_documented_shape(value: str) -> None:
    assert validate_dtxcid(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "DTXCID", "DTX30182", "dtxcid30182", "DTXCID3018X"],
)
def test_validate_dtxcid_rejects_malformed_values(value: str) -> None:
    with pytest.raises(EpaSrsSubstanceError, match="DTXCID"):
        validate_dtxcid(value)


def test_validate_dtxcid_rejects_a_dtxsid_shaped_value() -> None:
    with pytest.raises(EpaSrsSubstanceError):
        validate_dtxcid("DTXSID7020182")


# --- CASRN shape and public check digit ----------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "80-05-7",  # Bisphenol A
        "7732-18-5",  # water
        "58-08-2",  # caffeine
        "999995-90-3",  # synthetic fixture value with a valid check digit
    ],
)
def test_validate_casrn_accepts_a_valid_check_digit(value: str) -> None:
    assert validate_casrn(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "80-05-8",  # wrong check digit
        "80057",  # missing hyphens
        "80-5-7",  # second group must be two digits
        "80-05-77",  # check digit must be one digit
        "8O-05-7",  # non-digit character
    ],
)
def test_validate_casrn_rejects_malformed_or_invalid_values(value: str) -> None:
    with pytest.raises(EpaSrsSubstanceError, match="CASRN"):
        validate_casrn(value)


# --- Substance sample parsing -------------------------------------------


def test_parse_substance_sample_reads_the_pinned_fixture() -> None:
    sample = parse_substance_sample(_fixture_bytes())

    assert isinstance(sample, SubstanceSample)
    assert len(sample.records) == 3
    assert sample.captured_at == "2026-08-03T00:00:00Z"

    bpa = sample.records[0]
    assert isinstance(bpa, SubstanceIdentifierRecord)
    assert bpa.dtxsid == "DTXSID7020182"
    assert bpa.dtxcid == "DTXCID30182"
    assert bpa.casrn == "80-05-7"
    assert bpa.preferred_name == "Bisphenol A"
    assert bpa.tsca_inventory_status == "active"

    third = sample.records[2]
    assert third.dtxcid is None
    assert third.casrn is None
    assert third.tsca_inventory_status == "notListed"


def test_real_comptox_detail_page_shape_count_and_sample() -> None:
    source_path = os.environ.get("REFSPEC_COMPTOX_BPA_PAGE_PATH")
    if source_path is None:
        pytest.skip("normalized real CompTox detail page is not materialized")
    payload = Path(source_path).read_bytes()

    sample = parse_comptox_detail_page(
        payload,
        source_uri="https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182",
        captured_at="2026-08-03T20:00:00Z",
    )

    assert len(payload) == 334_109
    assert sample.source_digest == "sha256:96166f421b896b79f0f0273b26908a5d0dbbcc6ab484e6b15fa41d71ca082803"
    assert len(sample.records) == 1
    assert sample.records[0].native_payload() == {
        "dtxsid": "DTXSID7020182",
        "dtxcid": "DTXCID30182",
        "casrn": "80-05-7",
        "preferredName": "Bisphenol A",
        "tscaInventoryStatus": None,
        "sourceUri": "https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182",
    }


def test_parse_substance_sample_pins_the_source_digest() -> None:
    payload = _fixture_bytes()
    sample = parse_substance_sample(payload)

    import hashlib

    assert sample.source_digest == "sha256:" + hashlib.sha256(payload).hexdigest()


def test_parse_substance_sample_is_deterministic() -> None:
    first = parse_substance_sample(_fixture_bytes())
    second = parse_substance_sample(_fixture_bytes())

    assert first.native_payload() == second.native_payload()
    assert first.digest == second.digest


def test_parse_substance_sample_never_claims_concept_identity() -> None:
    sample = parse_substance_sample(_fixture_bytes())

    assert sample.native_payload()["conceptIdentityClaimed"] is False
    assert sample.native_payload()["maxSampleSize"] == MAX_SUBSTANCE_SAMPLE_SIZE


def test_substance_sample_identifiers_keep_dtxsid_and_dtxcid_distinct() -> None:
    sample = parse_substance_sample(_fixture_bytes())
    identifiers = sample.identifiers

    assert all(isinstance(item, ControlledIdentifier) for item in identifiers)
    kinds = {item.kind for item in identifiers}
    assert {"dtxsid", "dtxcid", "casrn"}.issubset(kinds)

    dtxsid_values = {item.value for item in identifiers if item.kind == "dtxsid"}
    dtxcid_values = {item.value for item in identifiers if item.kind == "dtxcid"}
    assert dtxsid_values.isdisjoint(dtxcid_values)
    assert len(dtxsid_values) == 3
    assert len(dtxcid_values) == 2  # the third record has no DTXCID

    for item in identifiers:
        if item.kind == "dtxsid":
            assert item.authority_uri == DTXSID_AUTHORITY_URI
        elif item.kind == "dtxcid":
            assert item.authority_uri == DTXCID_AUTHORITY_URI
        elif item.kind == "casrn":
            assert item.authority_uri == CAS_REGISTRY_AUTHORITY_URI


def test_substance_sample_identifiers_carry_the_source_digest() -> None:
    sample = parse_substance_sample(_fixture_bytes())

    assert all(item.source_digest == sample.source_digest for item in sample.identifiers)


# --- Refusal-style validation on the sample envelope ---------------------


def test_parse_substance_sample_rejects_empty_payload() -> None:
    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(b"")


def test_parse_substance_sample_rejects_malformed_json() -> None:
    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(b"{not json")


def test_parse_substance_sample_rejects_duplicate_json_keys() -> None:
    payload = b'{"format":"a","format":"b","capturedAt":"x","records":[]}'
    with pytest.raises(EpaSrsSubstanceError, match="duplicate"):
        parse_substance_sample(payload)


def test_parse_substance_sample_rejects_an_unknown_format() -> None:
    payload = _mutated_fixture(lambda value: value.__setitem__("format", "urn:ref:something-else:v1"))
    with pytest.raises(EpaSrsSubstanceError, match="format"):
        parse_substance_sample(payload)


def test_parse_substance_sample_rejects_an_unexpected_top_level_field() -> None:
    payload = _mutated_fixture(lambda value: value.__setitem__("extra", True))
    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(payload)


def test_parse_substance_sample_rejects_empty_records() -> None:
    payload = _mutated_fixture(lambda value: value.__setitem__("records", []))
    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(payload)


def test_parse_substance_sample_rejects_a_repeated_dtxsid() -> None:
    def mutate(value: dict) -> None:
        value["records"].append(dict(value["records"][0]))

    with pytest.raises(EpaSrsSubstanceError, match="DTXSID"):
        parse_substance_sample(_mutated_fixture(mutate))


def test_substance_sample_refuses_bulk_entity_data() -> None:
    record = parse_substance_sample(_fixture_bytes()).records[0]

    with pytest.raises(EpaSrsSubstanceError, match="refusing bulk substance data"):
        SubstanceSample(
            captured_at="2026-08-03T00:00:00Z",
            source_digest="sha256:" + "0" * 64,
            records=tuple(record for _ in range(MAX_SUBSTANCE_SAMPLE_SIZE + 1)),
        )


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("dtxsid", "not-a-dtxsid"),
        ("dtxcid", "not-a-dtxcid"),
        ("casrn", "12-34-9"),
        ("preferredName", ""),
        ("tscaInventoryStatus", "onceListedNowGone"),
        ("sourceUri", "not a uri"),
    ],
)
def test_parse_substance_sample_rejects_a_malformed_record_field(field: str, bad_value: object) -> None:
    def mutate(value: dict) -> None:
        value["records"][0][field] = bad_value

    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(_mutated_fixture(mutate))


def test_parse_substance_sample_rejects_a_record_missing_a_required_field() -> None:
    def mutate(value: dict) -> None:
        del value["records"][0]["casrn"]

    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(_mutated_fixture(mutate))


def test_parse_substance_sample_rejects_an_unknown_record_field() -> None:
    def mutate(value: dict) -> None:
        value["records"][0]["unexpectedField"] = "x"

    with pytest.raises(EpaSrsSubstanceError):
        parse_substance_sample(_mutated_fixture(mutate))

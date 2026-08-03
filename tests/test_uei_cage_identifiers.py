"""Offline tests for SAM.gov UEI and DLA CAGE identifier-authority capture.

No test opens a network connection. The single reproducible authority
document pin is checked against a fixture copy of the real bytes fetched
from ``https://sam.gov/entity-registration`` on 2026-08-03; the illustrative
identifier sample is a hand-built fixture, never a registry export.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import uei_cage_identifiers as uc
from refspec.registry.controlled_identifier import ControlledIdentifier, ControlledIdentifierError

FIXTURES = Path(__file__).parent / "fixtures" / "uei_cage_identifiers"
SAM_DOC_FIXTURE = FIXTURES / "sam-gov-entity-registration-2026-08-03.html"


def _uei_identifier(value: str = "SGVKKZK4NX79") -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=uc.SAM_UEI_KIND,
        authority_uri=uc.SAM_UEI_AUTHORITY_URI,
        source_uri=uc.SAM_UEI_AUTHORITY_URI,
        observed_at="2026-08-03T19:21:13Z",
        effective_at=None,
        source_digest=uc.SAM_UEI_DOCUMENTATION_PIN.sha256,
    )


def _cage_identifier(value: str = "1A2B3") -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=uc.DLA_CAGE_KIND,
        authority_uri=uc.DLA_CAGE_AUTHORITY_URI,
        source_uri=uc.DLA_CAGE_AUTHORITY_URI,
        observed_at="2026-08-03T19:21:13Z",
        effective_at=None,
        source_digest=None,
    )


def _uei_record(**changes: object) -> uc.UeiRecord:
    values: dict[str, object] = {
        "identifier": _uei_identifier(),
        "legal_business_name": "Example Registrant One",
        "registration_status": "active",
        "access_classification": "public",
        "immediate_parent_uei": None,
        "highest_level_owner_uei": None,
    }
    values.update(changes)
    return uc.UeiRecord(**values)  # type: ignore[arg-type]


def _cage_record(**changes: object) -> uc.CageRecord:
    values: dict[str, object] = {
        "identifier": _cage_identifier(),
        "facility_name": "Example Facility A",
        "cage_status": "active",
        "access_classification": "public",
        "associated_uei": None,
    }
    values.update(changes)
    return uc.CageRecord(**values)  # type: ignore[arg-type]


# --- identifier syntax ---------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["SGVKKZK4NX79", "AAAAAAAAAAAA", "123456789ABC", "ZZZZZZZZZZZZ"],
)
def test_uei_syntax_accepts_twelve_char_alphanumeric_without_i_or_o(value: str) -> None:
    assert uc.validate_uei_syntax(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "SGVKKZK4NX7",  # 11 chars
        "SGVKKZK4NX790",  # 13 chars
        "sgvkkzk4nx79",  # lowercase
        "SGVKKZKINX79",  # contains I
        "SGVKKZKONX79",  # contains O
        "SGVKKZK-NX79",  # punctuation
        "SGVKKZK NX79",  # space
    ],
)
def test_uei_syntax_rejects_malformed_values(value: str) -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="UEI"):
        uc.validate_uei_syntax(value)


@pytest.mark.parametrize("value", ["1A2B3", "ABCDE", "12345", "9ZZZ1"])
def test_cage_syntax_accepts_five_char_alphanumeric_without_i_or_o(value: str) -> None:
    assert uc.validate_cage_syntax(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1A2B",  # 4 chars
        "1A2B34",  # 6 chars
        "1a2b3",  # lowercase
        "1AIB3",  # contains I
        "1AOB3",  # contains O
        "1A-B3",  # punctuation
    ],
)
def test_cage_syntax_rejects_malformed_values(value: str) -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="CAGE"):
        uc.validate_cage_syntax(value)


# --- UeiRecord / CageRecord refusal-style validation ----------------------


def test_uei_record_accepts_a_well_formed_registration() -> None:
    record = _uei_record()

    assert record.identifier.value == "SGVKKZK4NX79"
    assert record.registration_status == "active"
    assert record.access_classification == "public"
    assert record.native_payload()["legalBusinessName"] == "Example Registrant One"


def test_uei_record_rejects_wrong_identifier_kind() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="kind"):
        _uei_record(identifier=_cage_identifier())


def test_uei_record_rejects_empty_legal_business_name() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="legal_business_name"):
        _uei_record(legal_business_name="   ")


def test_uei_record_rejects_unknown_registration_status() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="registration_status"):
        _uei_record(registration_status="lapsed")


def test_uei_record_rejects_unknown_access_classification() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="access_classification"):
        _uei_record(access_classification="secret")


def test_uei_record_rejects_a_malformed_parent_uei() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="immediate_parent_uei"):
        _uei_record(immediate_parent_uei="not-a-uei")


def test_uei_record_accepts_well_formed_parent_uei_references() -> None:
    record = _uei_record(
        immediate_parent_uei="ZZZZZZZZZZZZ",
        highest_level_owner_uei="AAAAAAAAAAAA",
    )

    assert record.native_payload()["immediateParentUei"] == "ZZZZZZZZZZZZ"
    assert record.native_payload()["highestLevelOwnerUei"] == "AAAAAAAAAAAA"


def test_cage_record_accepts_a_well_formed_facility() -> None:
    record = _cage_record()

    assert record.identifier.value == "1A2B3"
    assert record.cage_status == "active"
    assert record.native_payload()["facilityName"] == "Example Facility A"


def test_cage_record_rejects_wrong_identifier_kind() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="kind"):
        _cage_record(identifier=_uei_identifier())


def test_cage_record_rejects_empty_facility_name() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="facility_name"):
        _cage_record(facility_name="")


def test_cage_record_rejects_unknown_cage_status() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="cage_status"):
        _cage_record(cage_status="pending")


def test_cage_record_rejects_a_malformed_associated_uei() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="associated_uei"):
        _cage_record(associated_uei="also-not-a-uei")


def test_cage_record_accepts_a_well_formed_associated_uei() -> None:
    record = _cage_record(associated_uei="SGVKKZK4NX79")

    assert record.native_payload()["associatedUei"] == "SGVKKZK4NX79"


# --- sample-size and duplicate refusal (never bulk entity data) ----------


def test_sample_enforces_a_hard_ceiling_on_uei_records() -> None:
    ueis = tuple(
        _uei_record(identifier=_uei_identifier(f"{'A' * 11}{digit}")) for digit in "0123456789ABCDEFGHJKLMNPQR"
    )
    assert len(ueis) == uc.MAX_SAMPLE_SIZE + 1

    with pytest.raises(uc.UeiCageIdentifierError, match="MAX_SAMPLE_SIZE"):
        uc.UeiCageAuthoritySample(captured_at="2026-08-03", ueis=ueis, cages=())


def test_sample_enforces_a_hard_ceiling_on_cage_records() -> None:
    cages = tuple(
        _cage_record(identifier=_cage_identifier(f"{digit}AAA{digit}")) for digit in "0123456789ABCDEFGHJKLMNPQR"[:26]
    )
    assert len(cages) == uc.MAX_SAMPLE_SIZE + 1

    with pytest.raises(uc.UeiCageIdentifierError, match="MAX_SAMPLE_SIZE"):
        uc.UeiCageAuthoritySample(captured_at="2026-08-03", ueis=(), cages=cages)


def test_sample_rejects_a_repeated_uei_value() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="repeats"):
        uc.UeiCageAuthoritySample(
            captured_at="2026-08-03",
            ueis=(_uei_record(), _uei_record()),
            cages=(),
        )


def test_sample_rejects_a_repeated_cage_value() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="repeats"):
        uc.UeiCageAuthoritySample(
            captured_at="2026-08-03",
            ueis=(),
            cages=(_cage_record(), _cage_record()),
        )


def test_sample_validates_captured_at_is_iso() -> None:
    with pytest.raises(ControlledIdentifierError, match="ISO 8601"):
        uc.UeiCageAuthoritySample(captured_at="not-a-date", ueis=(), cages=())


# --- render/parse round trip ----------------------------------------------


def _sample() -> uc.UeiCageAuthoritySample:
    return uc.UeiCageAuthoritySample(
        captured_at="2026-08-03",
        ueis=(_uei_record(),),
        cages=(_cage_record(associated_uei="SGVKKZK4NX79"),),
    )


def test_render_capture_is_deterministic() -> None:
    sample = _sample()

    first = uc.render_capture(sample)
    second = uc.render_capture(sample)

    assert first == second
    assert first.endswith(b"\n")


def test_parse_capture_round_trips_a_rendered_sample() -> None:
    sample = _sample()
    payload = uc.render_capture(sample)

    parsed = uc.parse_capture(payload)

    assert parsed.captured_at == sample.captured_at
    assert [r.native_payload() for r in parsed.ueis] == [r.native_payload() for r in sample.ueis]
    assert [r.native_payload() for r in parsed.cages] == [r.native_payload() for r in sample.cages]
    assert parsed.digest == sample.digest


def test_parse_capture_reads_the_hand_authored_fixture() -> None:
    payload = (FIXTURES / "uei-cage-authority-sample.json").read_bytes()

    parsed = uc.parse_capture(payload)

    assert len(parsed.ueis) == 2
    assert len(parsed.cages) == 2
    by_value = {r.identifier.value: r for r in parsed.ueis}
    assert by_value["SGVKKZK4NX79"].legal_business_name == "Example Registrant One"
    assert by_value["SGVKKZK4NX79"].access_classification == "public"
    cage_by_value = {r.identifier.value: r for r in parsed.cages}
    assert cage_by_value["1A2B3"].associated_uei == "SGVKKZK4NX79"


def test_parse_capture_rejects_unknown_format() -> None:
    sample = _sample()
    payload = uc.render_capture(sample).replace(
        uc.SAMPLE_CAPTURE_FORMAT.encode("utf-8"),
        b"urn:ref:registry:something-else:v1",
    )

    with pytest.raises(uc.UeiCageIdentifierError, match="format"):
        uc.parse_capture(payload)


def test_parse_capture_rejects_a_field_that_drifted_from_the_schema() -> None:
    payload = uc.render_capture(_sample())
    mutated = payload.replace(b'"capturedAt"', b'"capturedOn"')

    with pytest.raises(uc.UeiCageIdentifierError, match="capture"):
        uc.parse_capture(mutated)


def test_parse_capture_rejects_a_sample_that_exceeds_the_ceiling() -> None:
    ueis = tuple(
        _uei_record(identifier=_uei_identifier(f"{'A' * 11}{digit}")) for digit in "0123456789ABCDEFGHJKLMNPQ"
    )
    assert len(ueis) == uc.MAX_SAMPLE_SIZE

    sample = uc.UeiCageAuthoritySample(captured_at="2026-08-03", ueis=ueis, cages=())
    payload = uc.render_capture(sample)
    # Hand-inflate maxSampleSize/list past the module ceiling to prove the
    # parser refuses bulk data even if a manifest claims a larger ceiling.
    inflated = payload.replace(
        f'"maxSampleSize": {uc.MAX_SAMPLE_SIZE}'.encode(),
        f'"maxSampleSize": {uc.MAX_SAMPLE_SIZE + 100}'.encode(),
    )

    with pytest.raises(uc.UeiCageIdentifierError, match="MAX_SAMPLE_SIZE"):
        uc.parse_capture(inflated)


def test_parse_capture_rejects_non_json_bytes() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="JSON"):
        uc.parse_capture(b"not json")


def test_parse_capture_rejects_empty_bytes() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="non-empty"):
        uc.parse_capture(b"")


# --- pinned authority document (source-faithful byte capture) ------------


def test_sam_uei_documentation_pin_matches_the_real_captured_fixture() -> None:
    payload = SAM_DOC_FIXTURE.read_bytes()

    uc.verify_authority_document(payload, uc.SAM_UEI_DOCUMENTATION_PIN)

    assert len(payload) == uc.SAM_UEI_DOCUMENTATION_PIN.byte_length


def test_verify_authority_document_rejects_a_single_byte_change() -> None:
    payload = bytearray(SAM_DOC_FIXTURE.read_bytes())
    payload[0] ^= 0xFF

    with pytest.raises(uc.UeiCageIdentifierError, match="does not match"):
        uc.verify_authority_document(bytes(payload), uc.SAM_UEI_DOCUMENTATION_PIN)


def test_acquire_authority_document_from_local_path(tmp_path: Path) -> None:
    local = tmp_path / "sam-doc.html"
    local.write_bytes(SAM_DOC_FIXTURE.read_bytes())

    payload = uc.acquire_authority_document(uc.SAM_UEI_DOCUMENTATION_PIN, source_path=local)

    assert len(payload) == uc.SAM_UEI_DOCUMENTATION_PIN.byte_length


def test_acquire_authority_document_rejects_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.html"
    real.write_bytes(SAM_DOC_FIXTURE.read_bytes())
    link = tmp_path / "linked.html"
    link.symlink_to(real)

    with pytest.raises(uc.UeiCageIdentifierError, match="not a regular file"):
        uc.acquire_authority_document(uc.SAM_UEI_DOCUMENTATION_PIN, source_path=link)


def test_acquire_authority_document_uses_an_injected_fetcher_not_a_live_call(
    tmp_path: Path,
) -> None:
    payload = SAM_DOC_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, url: str, *, timeout_seconds: float) -> uc.FetchedAuthorityDocument:
            calls.append((url, timeout_seconds))
            return uc.FetchedAuthorityDocument(
                body=payload,
                status_code=200,
                content_type="text/html",
                resolved_url=url,
            )

    result = uc.acquire_authority_document(
        uc.SAM_UEI_DOCUMENTATION_PIN,
        fetcher=Fetcher(),
        timeout_seconds=12.0,
    )

    assert calls == [(uc.SAM_UEI_AUTHORITY_URI, 12.0)]
    assert result == payload


def test_acquire_authority_document_rejects_a_non_200_fetch() -> None:
    class Fetcher:
        def fetch(self, url: str, *, timeout_seconds: float) -> uc.FetchedAuthorityDocument:
            return uc.FetchedAuthorityDocument(body=b"", status_code=404, content_type="text/html", resolved_url=url)

    with pytest.raises(uc.UeiCageIdentifierError, match="HTTP 404"):
        uc.acquire_authority_document(uc.SAM_UEI_DOCUMENTATION_PIN, fetcher=Fetcher())


def test_acquire_authority_document_rejects_a_fetch_that_does_not_match_the_pin() -> None:
    class Fetcher:
        def fetch(self, url: str, *, timeout_seconds: float) -> uc.FetchedAuthorityDocument:
            return uc.FetchedAuthorityDocument(
                body=b"drifted content",
                status_code=200,
                content_type="text/html",
                resolved_url=url,
            )

    with pytest.raises(uc.UeiCageIdentifierError, match="does not match"):
        uc.acquire_authority_document(uc.SAM_UEI_DOCUMENTATION_PIN, fetcher=Fetcher())


def test_acquire_authority_document_requires_source_path_or_fetcher() -> None:
    with pytest.raises(uc.UeiCageIdentifierError, match="source_path or"):
        uc.acquire_authority_document(uc.SAM_UEI_DOCUMENTATION_PIN)


def test_acquire_authority_document_rejects_both_source_path_and_fetcher(tmp_path: Path) -> None:
    local = tmp_path / "sam-doc.html"
    local.write_bytes(SAM_DOC_FIXTURE.read_bytes())

    class Fetcher:
        def fetch(self, url: str, *, timeout_seconds: float) -> uc.FetchedAuthorityDocument:
            raise AssertionError("fetcher must not be called when source_path is also given")

    with pytest.raises(uc.UeiCageIdentifierError, match="not both"):
        uc.acquire_authority_document(uc.SAM_UEI_DOCUMENTATION_PIN, source_path=local, fetcher=Fetcher())


def test_import_never_opens_a_network_connection() -> None:
    # The module only ever calls out through an injected fetcher supplied by
    # the caller; there is no built-in "go fetch the live site" entry point.
    assert not hasattr(uc, "requests")
    assert not hasattr(uc, "urlopen")


# --- no bulk entity data, ever ---------------------------------------------


def test_module_never_exposes_a_bulk_entity_query_surface() -> None:
    # These names would indicate the catalog-guidance boundary was crossed:
    # this module captures identifier shape and syntax, never a searchable
    # registry of real entities.
    forbidden = {"search_entities", "list_entities", "fetch_all_entities", "bulk_import"}
    assert not (forbidden & set(dir(uc)))

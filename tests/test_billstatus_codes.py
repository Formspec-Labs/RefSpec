"""Official BILLSTATUS code-set capture, parsing, and record-assignment tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import billstatus_codes as bs
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "billstatus_codes"
USER_GUIDE_FIXTURE = FIXTURES / "billstatus-xml-user-guide-2026-08-03.md"
README_FIXTURE = FIXTURES / "billstatus-readme-2026-08-03.html"


def _acquire(tmp_path: Path, source_path: Path = USER_GUIDE_FIXTURE) -> bs.AcquiredBillStatusSource:
    return bs.acquire_billstatus_source(bs.BILLSTATUS_USER_GUIDE_2026_08_03, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> bs.BillStatusControlPortfolio:
    return bs.parse_billstatus_code_sets(_acquire(tmp_path))


def test_live_snapshot_pin_matches_exact_official_bytes() -> None:
    payload = USER_GUIDE_FIXTURE.read_bytes()

    assert len(payload) == 38_802
    assert bs.sha256_digest(payload) == ("sha256:a10909696b2ed2244d75c76e75fa32bc3e4eb926deab7e4e00592a6a01c3ad3a")
    assert bs.BILLSTATUS_USER_GUIDE_2026_08_03.expected_sha256 == bs.sha256_digest(payload)

    readme_payload = README_FIXTURE.read_bytes()
    assert len(readme_payload) == bs.BILLSTATUS_README_2026_08_03_BYTE_LENGTH
    assert bs.sha256_digest(readme_payload) == bs.BILLSTATUS_README_2026_08_03_SHA256


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = bs.BILLSTATUS_USER_GUIDE_2026_08_03

    acquired = _acquire(tmp_path)
    cached = bs.acquire_billstatus_source(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = USER_GUIDE_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> bs.FetchedBillStatusResponse:
            calls.append((source_url, timeout_seconds))
            return bs.FetchedBillStatusResponse(
                body=payload,
                status_code=200,
                content_type="text/plain; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = bs.acquire_billstatus_source(
        bs.BILLSTATUS_USER_GUIDE_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(bs.BILLSTATUS_USER_GUIDE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_bill_types_are_a_closed_enumeration_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    resource = portfolio.bill_types

    assert resource.completeness == "closedEnumeration"
    assert resource.use == "deterministicMetadata"
    assert len(resource.codes) == 8
    by_code = resource.by_code()
    assert set(by_code) == {"H", "S", "HRES", "SRES", "HJRES", "SJRES", "HCONRES", "SCONRES"}
    assert by_code["HJRES"] == bs.BillStatusCode(
        resource_name="billTypes",
        use="deterministicMetadata",
        completeness="closedEnumeration",
        publisher_label="HJRES",
        source_url=bs.BILLSTATUS_USER_GUIDE.source_url,
        identifiers=(
            ControlledIdentifier(
                value="HJRES",
                kind="billTypeCode",
                authority_uri=bs.BILLSTATUS_IDENTIFIER_AUTHORITY_URI,
                source_uri=bs.BILLSTATUS_USER_GUIDE.source_url,
                observed_at=bs.BILLSTATUS_USER_GUIDE_2026_08_03.retrieved_at,
                effective_at=None,
                source_digest=bs.BILLSTATUS_USER_GUIDE_2026_08_03.expected_sha256,
            ),
        ),
    )
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_action_codes_are_an_open_courtesy_list_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    resource = portfolio.action_codes

    assert resource.completeness == "openCourtesyList"
    assert len(resource.codes) == 36
    by_code = resource.by_code()
    assert by_code["H12200"].publisher_label == "Committee reported"
    assert by_code["36000"].publisher_label == "Became Public Law"
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_summary_version_codes_disambiguate_by_chamber(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    resource = portfolio.summary_version_codes

    assert resource.completeness == "closedEnumeration"
    assert len(resource.codes) == 88
    by_pair = resource.by_code_and_chamber()
    assert by_pair[("00", "HOUSE")].publisher_label == "Introduced in House"
    assert by_pair[("00", "SENATE")].publisher_label == "Introduced in Senate"
    assert by_pair[("49", "BOTH")].publisher_label == "Public Law"

    with pytest.raises(bs.BillStatusSourceDriftError, match="not unique"):
        resource.by_code()


def test_portfolio_records_completeness_and_schema_version_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("does not exist" in gap for gap in portfolio.gaps)
    assert any("(HR)" in gap for gap in portfolio.gaps)
    assert any("schema/format version" in gap for gap in portfolio.gaps)


def test_current_billstatus_record_validates_without_becoming_subjects(
    tmp_path: Path,
) -> None:
    record = {
        "schema_version": "1.10.1",
        "bill_type": "HR",
        "actions": [
            {"action_code": "H12200"},
            {"action_code": "Z99999"},
        ],
        "summaries": [
            {"version_code": "00", "chamber": "HOUSE"},
        ],
    }

    with pytest.raises(bs.BillStatusAssignmentError, match="unknown BILLSTATUS bill_type"):
        bs.validate_billstatus_record_codes(record, _portfolio(tmp_path))

    record["bill_type"] = "H"
    validated = bs.validate_billstatus_record_codes(record, _portfolio(tmp_path))

    assert validated.schema_version == "1.10.1"
    assert validated.bill_type.matched is True
    assert validated.bill_type.identifiers[0].value == "H"
    assert [assignment.matched for assignment in validated.action_codes] == [True, False]
    assert validated.action_codes[1].raw_value == "Z99999"
    assert validated.action_codes[1].identifiers == ()
    assert validated.action_codes[1].publisher_label is None
    assert validated.summary_versions[0].matched is True
    assert validated.summary_versions[0].publisher_label == "Introduced in House"
    assert all(not assignment.is_general_subject_concept for assignment in validated.action_codes)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("bill_type", "HR", "unknown BILLSTATUS bill_type"),
    ],
)
def test_unknown_closed_bill_type_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    record = {
        "schema_version": "1.10.1",
        "bill_type": value,
        "actions": [],
        "summaries": [],
    }
    assert field == "bill_type"

    with pytest.raises(bs.BillStatusAssignmentError, match=message):
        bs.validate_billstatus_record_codes(record, _portfolio(tmp_path))


def test_unknown_summary_version_or_chamber_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    base = {"schema_version": "1.10.1", "bill_type": "H", "actions": []}

    with pytest.raises(bs.BillStatusAssignmentError, match="unknown BILLSTATUS summary"):
        bs.validate_billstatus_record_codes(
            {**base, "summaries": [{"version_code": "99", "chamber": "HOUSE"}]},
            portfolio,
        )
    with pytest.raises(bs.BillStatusAssignmentError, match="unknown BILLSTATUS summary"):
        bs.validate_billstatus_record_codes(
            {**base, "summaries": [{"version_code": "49", "chamber": "HOUSE"}]},
            portfolio,
        )


def test_missing_schema_version_fails_closed(tmp_path: Path) -> None:
    record = {"bill_type": "H", "actions": [], "summaries": []}

    with pytest.raises(bs.BillStatusAssignmentError, match="schema_version"):
        bs.validate_billstatus_record_codes(record, _portfolio(tmp_path))


def test_digest_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = USER_GUIDE_FIXTURE.read_bytes()
    changed = payload.replace(b"Signed by President", b"Signed by Presidwnt")
    assert len(changed) == len(payload)
    assert changed != payload

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> bs.FetchedBillStatusResponse:
            del timeout_seconds
            return bs.FetchedBillStatusResponse(
                body=changed,
                status_code=200,
                content_type="text/plain; charset=utf-8",
                resolved_url=source_url,
            )

    with pytest.raises(bs.BillStatusSourceDriftError, match="digest drift"):
        bs.acquire_billstatus_source(
            bs.BILLSTATUS_USER_GUIDE_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_missing_section_or_malformed_table_shape_fails_closed(tmp_path: Path) -> None:
    mini_payload = b"# Some Other Document\n\nNo BILLSTATUS tables here.\n"
    mini_pin = bs.BillStatusSnapshotPin(
        source=bs.BILLSTATUS_USER_GUIDE,
        retrieved_at="2026-08-03T19:29:08Z",
        expected_sha256=bs.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.md"
    mini_path.write_bytes(mini_payload)

    acquired = bs.acquire_billstatus_source(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(bs.BillStatusSourceDriftError, match="section header not found"):
        bs.parse_billstatus_code_sets(acquired)


def test_source_url_and_content_type_are_pinned_to_the_official_host(tmp_path: Path) -> None:
    with pytest.raises(bs.BillStatusAcquisitionError):
        bs.BillStatusDocumentSource(
            source_url="https://example.com/BILLSTATUS-XML_User_User-Guide.md",
            filename="billstatus-xml-user-guide.md",
        )

    payload = USER_GUIDE_FIXTURE.read_bytes()

    class WrongContentTypeFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> bs.FetchedBillStatusResponse:
            del timeout_seconds
            return bs.FetchedBillStatusResponse(
                body=payload,
                status_code=200,
                content_type="application/octet-stream",
                resolved_url=source_url,
            )

    with pytest.raises(bs.BillStatusSourceDriftError, match="content type"):
        bs.acquire_billstatus_source(
            bs.BILLSTATUS_USER_GUIDE_2026_08_03,
            tmp_path,
            fetcher=WrongContentTypeFetcher(),
        )

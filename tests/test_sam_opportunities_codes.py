"""Official SAM.gov Opportunities controlled-code capture, parsing, and package tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import sam_opportunities_codes as sam
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "sam_opportunities_codes"
DOC_FIXTURE = FIXTURES / "sam-get-opportunities-public-api-2026-08-03.html"


def _acquire(tmp_path: Path, source_path: Path = DOC_FIXTURE) -> sam.AcquiredSAMSource:
    return sam.acquire_sam_opportunities_doc(
        sam.SAM_OPPORTUNITIES_DOC_2026_08_03,
        tmp_path,
        source_path=source_path,
    )


def _portfolio(tmp_path: Path) -> sam.SAMOpportunitiesCodePortfolio:
    return sam.parse_sam_opportunities_codes(_acquire(tmp_path))


def test_live_snapshot_pin_matches_exact_official_html_bytes() -> None:
    payload = DOC_FIXTURE.read_bytes()

    assert len(payload) == 46_217
    assert sam.sha256_digest(payload) == ("sha256:448b85ab4a22e33d139295cb1d6a3a6384b685a936d8c645dd12e69ed938fa62")
    assert payload.startswith(b"<!doctype html>")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = sam.SAM_OPPORTUNITIES_DOC_2026_08_03

    acquired = _acquire(tmp_path)
    cached = sam.acquire_sam_opportunities_doc(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> sam.FetchedSAMResponse:
            calls.append((source_url, timeout_seconds))
            return sam.FetchedSAMResponse(
                body=payload,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = sam.acquire_sam_opportunities_doc(
        sam.SAM_OPPORTUNITIES_DOC_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(sam.SAM_OPPORTUNITIES_DOC_SOURCE.source_url, 17.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_notice_type_codes_preserve_retired_and_active_split(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert len(portfolio.notice_types) == 11
    active = [code for code in portfolio.notice_types if not code.retired]
    retired = [code for code in portfolio.notice_types if code.retired]
    assert len(active) == 9
    assert len(retired) == 2
    assert {code.identifiers[0].value for code in retired} == {"f", "l"}
    assert all(not code.is_general_subject_concept for code in portfolio.notice_types)


def test_notice_type_codes_exact_values(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.notice_types_by_code()

    assert by_code["o"].publisher_label == "Solicitation"
    assert by_code["o"].retired is False
    assert by_code["u"].publisher_label == "Justification (J&A)"
    assert by_code["k"].publisher_label == "Combined Synopsis/Solicitation"

    assert by_code["f"].publisher_label == "Foreign Government Standard"
    assert by_code["f"].retired is True
    assert by_code["l"].publisher_label == "Fair Opportunity / Limited Sources"
    assert by_code["l"].retired is True

    identifier = by_code["o"].identifiers[0]
    assert identifier.kind == "noticeTypeCode"
    assert identifier.value == "o"
    assert identifier.authority_uri == sam.SAM_IDENTIFIER_AUTHORITY_URI
    assert identifier.source_digest == sam.SAM_OPPORTUNITIES_DOC_2026_08_03.expected_sha256


def test_opportunity_status_values(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.opportunity_statuses_by_code()

    assert set(by_code) == {"active", "inactive", "archived", "cancelled", "deleted"}
    assert all(code.use == "deterministicMetadata" for code in portfolio.opportunity_statuses)
    assert all(not code.retired for code in portfolio.opportunity_statuses)
    assert all(not code.is_general_subject_concept for code in portfolio.opportunity_statuses)


def test_set_aside_codes_preserve_mixed_case_publisher_code(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.set_aside_codes_by_code()

    assert len(portfolio.set_aside_codes) == 18
    assert "BICiv" in by_code
    assert "BICIV" not in by_code
    assert "Buy Indian Set-Aside" in by_code["BICiv"].publisher_label
    assert by_code["SBA"].publisher_label == "Total Small Business Set-Aside (FAR 19.5)"
    assert by_code["WOSBSS"].publisher_label == ("Women-Owned Small Business (WOSB) Program Sole Source (FAR 19.15)")
    assert len({code.identifiers[0].value for code in portfolio.set_aside_codes}) == 18


def test_gaps_document_latest_active_version_and_missing_status_mapping(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("latest active version" in gap for gap in portfolio.gaps)
    assert any("Coming Soon" in gap for gap in portfolio.gaps)
    assert any("pre-v0.4" in gap for gap in portfolio.gaps)


def test_change_log_evidence_pins_latest_doc_version_and_status_history(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.publisher_doc_version == "v1.97"
    assert portfolio.publisher_doc_version_date == "06/11/2021"
    assert any("Added new request field for status" in entry for entry in portfolio.status_version_history)
    assert any("Added inactive in status" in entry for entry in portfolio.status_version_history)


def test_validate_notice_type_query_value_accepts_active_and_rejects_retired_and_unknown(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert sam.validate_notice_type_query_value("o", portfolio).publisher_label == "Solicitation"

    with pytest.raises(sam.SAMAssignmentError, match="retired"):
        sam.validate_notice_type_query_value("f", portfolio)

    with pytest.raises(sam.SAMAssignmentError, match="unknown"):
        sam.validate_notice_type_query_value("z", portfolio)


def test_validate_status_query_value_rejects_unknown(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert sam.validate_status_query_value("active", portfolio).publisher_label == "active"

    with pytest.raises(sam.SAMAssignmentError, match="unknown"):
        sam.validate_status_query_value("closed", portfolio)


def test_validate_set_aside_code_is_case_sensitive_for_biciv(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert sam.validate_set_aside_code("BICiv", portfolio).identifiers[0].value == "BICiv"

    with pytest.raises(sam.SAMAssignmentError, match="unknown"):
        sam.validate_set_aside_code("BICIV", portfolio)


def test_digest_drift_never_becomes_a_parsed_portfolio(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    changed = payload.replace(b"Solicitation", b"SolicitatioN", 1)
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> sam.FetchedSAMResponse:
            del timeout_seconds
            return sam.FetchedSAMResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(sam.SAMSourceDriftError, match="digest drift"):
        sam.acquire_sam_opportunities_doc(
            sam.SAM_OPPORTUNITIES_DOC_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_shape_drift_in_the_ptype_table_fails_loudly(tmp_path: Path) -> None:
    mini_html = (
        b"<!doctype html><html><body>"
        b'<h3 id="set-aside-values">Set-Aside Values</h3><table><tbody>'
        b"<tr><td>SBA</td><td>Total Small Business Set-Aside (FAR 19.5)</td></tr>"
        b"</tbody></table>"
        b"</body></html>"
    )
    mini_pin = sam.SAMSnapshotPin(
        source=sam.SAM_OPPORTUNITIES_DOC_SOURCE,
        retrieved_at="2026-08-03T19:18:48Z",
        expected_sha256=sam.sha256_digest(mini_html),
        expected_byte_length=len(mini_html),
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_html)

    acquired = sam.acquire_sam_opportunities_doc(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(sam.SAMSourceDriftError, match="ptype"):
        sam.parse_sam_opportunities_codes(acquired)


def test_package_round_trips_through_a_closed_source_controlled_resource(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path)
    portfolio = sam.parse_sam_opportunities_codes(acquired)

    bundle = sam.build_sam_opportunities_code_package("noticeTypes", portfolio, acquired)
    destination = tmp_path / "package"
    bundle.write_to(destination)

    reopened = SourceControlledResourceView.open(destination)
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["conceptIdentityClaimed"] is False
    assert reopened.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert len(reopened.observations) == 11

    retired_observations = [obs for obs in reopened.observations if obs["retired"] is True]
    assert len(retired_observations) == 2


def test_package_rejects_an_unknown_resource_family(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    portfolio = sam.parse_sam_opportunities_codes(acquired)

    with pytest.raises(sam.SAMPackageError, match="unknown"):
        sam.build_sam_opportunities_code_package("noticeStatuses", portfolio, acquired)

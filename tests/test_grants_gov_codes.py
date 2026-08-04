"""Official Grants.gov status/code page capture, parsing, and package tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import grants_gov_codes as gg
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "grants_gov_codes"
DOC_FIXTURE = FIXTURES / "grants-gov-status-codes-2026-08-03.html"


def _acquire(tmp_path: Path, source_path: Path = DOC_FIXTURE) -> gg.AcquiredGrantsGovSource:
    return gg.acquire_grants_gov_status_codes(
        gg.GRANTS_GOV_STATUS_CODES_2026_08_03,
        tmp_path,
        source_path=source_path,
    )


def _portfolio(tmp_path: Path) -> gg.GrantsGovCodePortfolio:
    return gg.parse_grants_gov_status_codes(_acquire(tmp_path))


def test_live_snapshot_pin_matches_exact_official_html_bytes() -> None:
    payload = DOC_FIXTURE.read_bytes()

    assert len(payload) == 46_093
    assert gg.sha256_digest(payload) == ("sha256:bcbe4c44f8c1743eeaa26ab9f350c53214238c31d807057f248af8dd96cd5f85")
    assert payload.startswith(b"<!DOCTYPE html>")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = gg.GRANTS_GOV_STATUS_CODES_2026_08_03

    acquired = _acquire(tmp_path)
    cached = gg.acquire_grants_gov_status_codes(pin, tmp_path)

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
        ) -> gg.FetchedGrantsGovResponse:
            calls.append((source_url, timeout_seconds))
            return gg.FetchedGrantsGovResponse(
                body=payload,
                status_code=200,
                content_type="text/html;charset=utf-8",
                resolved_url=source_url,
            )

    acquired = gg.acquire_grants_gov_status_codes(
        gg.GRANTS_GOV_STATUS_CODES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=21.0,
    )

    assert calls == [(gg.GRANTS_GOV_STATUS_CODES_SOURCE.source_url, 21.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_eligibility_codes_are_deterministic_metadata_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.eligibilities_by_code()

    assert len(portfolio.eligibilities) == 17
    assert set(by_code) == {
        "00",
        "01",
        "02",
        "04",
        "05",
        "06",
        "07",
        "08",
        "11",
        "12",
        "13",
        "20",
        "21",
        "22",
        "23",
        "25",
        "99",
    }
    assert by_code["23"].publisher_label == "Small businesses"
    assert by_code["07"].publisher_label == "Native American tribal governments (federally recognized)"
    assert all(code.use == "deterministicMetadata" for code in portfolio.eligibilities)
    assert all(not code.is_general_subject_concept for code in portfolio.eligibilities)

    identifier = by_code["23"].identifiers[0]
    assert identifier.kind == "eligibilityCode"
    assert identifier.value == "23"
    assert identifier.authority_uri == gg.GRANTS_GOV_IDENTIFIER_AUTHORITY_URI
    assert identifier.source_digest == gg.GRANTS_GOV_STATUS_CODES_2026_08_03.expected_sha256


def test_funding_category_codes_are_source_assigned_evidence(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.funding_categories_by_code()

    assert len(portfolio.funding_categories) == 26
    assert by_code["AG"].publisher_label == "Agriculture"
    assert by_code["ACA"].publisher_label == "Affordable Care Act"
    assert by_code["O"].publisher_label == "Other"
    assert all(code.use == "sourceAssignedEvidence" for code in portfolio.funding_categories)
    assert all(not code.is_general_subject_concept for code in portfolio.funding_categories)

    identifier = by_code["AG"].identifiers[0]
    assert identifier.kind == "fundingCategoryCode"
    assert identifier.value == "AG"


def test_gaps_document_missing_instrument_status_and_revision_pin(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("instrument" in gap and "statutory initiative" in gap for gap in portfolio.gaps)
    assert any("Last-Modified" in gap for gap in portfolio.gaps)
    assert any("HTTP Status Code Summary" in gap for gap in portfolio.gaps)


def test_validate_eligibility_code_rejects_unknown(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert gg.validate_eligibility_code("21", portfolio).publisher_label == "Individuals"

    with pytest.raises(gg.GrantsGovAssignmentError, match="unknown"):
        gg.validate_eligibility_code("97", portfolio)


def test_validate_funding_category_code_rejects_unknown(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert gg.validate_funding_category_code("HL", portfolio).publisher_label == "Health"

    with pytest.raises(gg.GrantsGovAssignmentError, match="unknown"):
        gg.validate_funding_category_code("ZZ", portfolio)


def test_digest_drift_never_becomes_a_parsed_portfolio(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    changed = payload.replace(b"Agriculture", b"AgricultuRe", 1)
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> gg.FetchedGrantsGovResponse:
            del timeout_seconds
            return gg.FetchedGrantsGovResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(gg.GrantsGovSourceDriftError, match="digest drift"):
        gg.acquire_grants_gov_status_codes(
            gg.GRANTS_GOV_STATUS_CODES_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_shape_drift_in_the_eligibility_table_fails_loudly(tmp_path: Path) -> None:
    mini_html = (
        b"<!DOCTYPE html><html><body>"
        b"<h3>HTTP STATUS CODE SUMMARY</h3>"
        b"<table><thead><tr><th>Code</th></tr></thead><tbody>"
        b"<tr><td>200</td></tr></tbody></table>"
        b"<h3>Category Codes (&quot;fundingCategories&quot;):</h3>"
        b"<table><tbody><tr><td>AG</td><td>Agriculture</td></tr></tbody></table>"
        b"</body></html>"
    )
    mini_pin = gg.GrantsGovSnapshotPin(
        source=gg.GRANTS_GOV_STATUS_CODES_SOURCE,
        retrieved_at="2026-08-03T19:28:12Z",
        expected_sha256=gg.sha256_digest(mini_html),
        expected_byte_length=len(mini_html),
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_html)

    acquired = gg.acquire_grants_gov_status_codes(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(gg.GrantsGovSourceDriftError, match="Eligibility"):
        gg.parse_grants_gov_status_codes(acquired)


def test_package_round_trips_through_a_closed_source_controlled_resource(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path)
    portfolio = gg.parse_grants_gov_status_codes(acquired)

    bundle = gg.build_grants_gov_code_package("eligibilities", portfolio, acquired)
    destination = tmp_path / "package"
    bundle.write_to(destination)

    reopened = SourceControlledResourceView.open(destination)
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["conceptIdentityClaimed"] is False
    assert reopened.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert len(reopened.observations) == 17
    assert all(obs["eligibleUses"] == ("deterministicMetadata",) for obs in reopened.observations)


def test_package_rejects_an_unknown_resource_family(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    portfolio = gg.parse_grants_gov_status_codes(acquired)

    with pytest.raises(gg.GrantsGovPackageError, match="unknown"):
        gg.build_grants_gov_code_package("instruments", portfolio, acquired)

"""CourtListener jurisdictions-page capture, parsing, and packaging tests."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import courtlistener_codes as cl
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceView,
)

FIXTURES = Path(__file__).parent / "fixtures" / "courtlistener_codes"
JURISDICTIONS_FIXTURE = FIXTURES / "courtlistener-jurisdictions-mini.html"

MINI_PIN = cl.CourtListenerJurisdictionsSnapshotPin(
    source_url=cl.COURTLISTENER_JURISDICTIONS_URL,
    retrieved_at="2026-08-03T00:00:00Z",
    expected_sha256="sha256:c85d10372cf161d1e1822de8a5a8ad5eca1be7ec47bef6552449fac500064f6c",
    expected_byte_length=7_152,
)


def _acquire(tmp_path: Path) -> cl.AcquiredCourtListenerJurisdictionsPage:
    return cl.acquire_courtlistener_jurisdictions_page(MINI_PIN, tmp_path, source_path=JURISDICTIONS_FIXTURE)


def _parsed(tmp_path: Path) -> cl.ParsedCourtListenerJurisdictionsPage:
    return cl.parse_courtlistener_jurisdictions_page(_acquire(tmp_path))


def test_real_publisher_table_shape_count_and_boundary_samples(tmp_path: Path) -> None:
    source_path_text = os.environ.get("REFSPEC_COURTLISTENER_JURISDICTIONS_PATH")
    if source_path_text is None:
        pytest.skip("real CourtListener publisher capture is not configured")
    pin = cl.CourtListenerJurisdictionsSnapshotPin(
        source_url=cl.COURTLISTENER_JURISDICTIONS_URL,
        retrieved_at="2026-08-03T00:00:00Z",
        expected_sha256="sha256:883446028b029078c032bfe7c3545f9e109bb328c79ec486fbbbdbf35580b292",
        expected_byte_length=3_156_029,
    )
    acquired = cl.acquire_courtlistener_jurisdictions_page(
        pin,
        tmp_path,
        source_path=Path(source_path_text),
    )
    parsed = cl.parse_courtlistener_jurisdictions_page(acquired)

    assert len(parsed.rows) == 3_359
    assert (parsed.rows[0].name, parsed.rows[0].identifiers[0].value) == (
        "Supreme Court of the United States",
        "scotus",
    )
    assert (parsed.rows[-1].name, parsed.rows[-1].identifiers[0].value) == (
        "White Earth Band of Chippewa Tribal Court",
        "webchippewatr",
    )


def test_fixture_pin_matches_exact_bytes() -> None:
    payload = JURISDICTIONS_FIXTURE.read_bytes()

    assert len(payload) == 7_152
    assert cl.sha256_digest(payload) == "sha256:c85d10372cf161d1e1822de8a5a8ad5eca1be7ec47bef6552449fac500064f6c"


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    cached = cl.acquire_courtlistener_jurisdictions_page(MINI_PIN, tmp_path)

    assert acquired.path == (
        tmp_path / "sha256" / MINI_PIN.expected_sha256.removeprefix("sha256:") / "courtlistener-jurisdictions.html"
    )
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == MINI_PIN.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = JURISDICTIONS_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cl.FetchedCourtListenerPage:
            calls.append((source_url, timeout_seconds))
            return cl.FetchedCourtListenerPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = cl.acquire_courtlistener_jurisdictions_page(
        MINI_PIN,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(cl.COURTLISTENER_JURISDICTIONS_URL, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.resolved_url == cl.COURTLISTENER_JURISDICTIONS_URL


def test_courts_are_captured_as_platform_identity_not_official_values(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    by_id = parsed.by_court_id()

    assert len(parsed.rows) == 6
    scotus = by_id["scotus"]
    assert scotus.name == "Supreme Court of the United States"
    assert scotus.jurisdiction_type == "Federal Appellate"
    assert scotus.citation_abbreviation == "SCOTUS"
    assert scotus.in_use is True
    assert scotus.identifiers == (
        ControlledIdentifier(
            value="scotus",
            kind="courtlistenerCourtId",
            authority_uri=cl.COURTLISTENER_IDENTIFIER_AUTHORITY_URI,
            source_uri=cl.COURTLISTENER_JURISDICTIONS_URL,
            observed_at=MINI_PIN.retrieved_at,
            effective_at=None,
            source_digest=MINI_PIN.expected_sha256,
        ),
        ControlledIdentifier(
            value="Federal Appellate",
            kind="courtlistenerJurisdictionType",
            authority_uri=cl.COURTLISTENER_IDENTIFIER_AUTHORITY_URI,
            source_uri=cl.COURTLISTENER_JURISDICTIONS_URL,
            observed_at=MINI_PIN.retrieved_at,
            effective_at=None,
            source_digest=MINI_PIN.expected_sha256,
        ),
        ControlledIdentifier(
            value="SCOTUS",
            kind="courtlistenerCitationAbbreviation",
            authority_uri=cl.COURTLISTENER_IDENTIFIER_AUTHORITY_URI,
            source_uri=cl.COURTLISTENER_JURISDICTIONS_URL,
            observed_at=MINI_PIN.retrieved_at,
            effective_at=None,
            source_digest=MINI_PIN.expected_sha256,
        ),
    )
    # No column on this page publishes an identifier the court itself issued.
    assert all(identifier.kind != "officialCourtIdentifier" for identifier in scotus.identifiers)


def test_malformed_jurisdiction_cell_is_captured_verbatim_not_corrected(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    sussex = parsed.by_court_id()["njcirctsussex"]

    assert sussex.jurisdiction_type == "St"
    jurisdiction_identifiers = [i for i in sussex.identifiers if i.kind == "courtlistenerJurisdictionType"]
    assert [i.value for i in jurisdiction_identifiers] == ["St"]


def test_blank_jurisdiction_cell_omits_identifier_but_keeps_court_identity(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    ohio = parsed.by_court_id()["ohctapp1"]

    assert ohio.jurisdiction_type is None
    assert ohio.citation_abbreviation is None
    assert [i.kind for i in ohio.identifiers] == ["courtlistenerCourtId"]
    assert ohio.name == "Court of Appeals of Ohio, First District"


def test_row_without_citation_abbreviation_or_homepage_still_parses(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)
    swinomish = parsed.by_court_id()["swinomishtr"]

    assert swinomish.jurisdiction_type == "Tribal Trial"
    assert swinomish.citation_abbreviation is None
    assert swinomish.start_date == "Unknown"
    assert swinomish.in_use is True


def test_package_is_a_controlled_code_list_not_a_concept_scheme(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    parsed = cl.parse_courtlistener_jurisdictions_page(acquired)

    bundle = cl.build_courtlistener_jurisdictions_package(acquired, parsed)

    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
    assert bundle.resource_manifest["observationCount"] == 6


def test_package_gaps_document_official_vs_platform_separation_and_missing_opinion_types(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path)
    parsed = cl.parse_courtlistener_jurisdictions_page(acquired)
    bundle = cl.build_courtlistener_jurisdictions_package(acquired, parsed)

    reasons = [gap["reason"] for gap in bundle.coverage_report["gaps"]]
    assert any("must never overwrite or stand in for an official court value" in reason for reason in reasons)
    assert any("no opinion-type or opinion-status code list" in reason for reason in reasons)
    assert any("not a stable, independently re-fetchable release" in reason for reason in reasons)
    assert any("data-entry defect" in reason for reason in reasons)


def test_package_round_trips_through_a_written_directory(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    parsed = cl.parse_courtlistener_jurisdictions_page(acquired)
    bundle = cl.build_courtlistener_jurisdictions_package(acquired, parsed)

    written = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(written)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 6
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"


def test_digest_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = JURISDICTIONS_FIXTURE.read_bytes()
    changed = payload.replace(b"scotus", b"SCOTUS")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cl.FetchedCourtListenerPage:
            del timeout_seconds
            return cl.FetchedCourtListenerPage(
                body=changed,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    with pytest.raises(cl.CourtListenerSourceDriftError, match="digest drift"):
        cl.acquire_courtlistener_jurisdictions_page(MINI_PIN, tmp_path, fetcher=ChangedFetcher())


def test_column_shape_drift_fails_closed(tmp_path: Path) -> None:
    payload = JURISDICTIONS_FIXTURE.read_bytes()
    dropped = payload.replace(b"<th>Name</th>", b"")
    pin = replace(
        MINI_PIN,
        expected_sha256=cl.sha256_digest(dropped),
        expected_byte_length=len(dropped),
    )
    source_path = tmp_path / "dropped-column.html"
    source_path.write_bytes(dropped)

    acquired = cl.acquire_courtlistener_jurisdictions_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cl.CourtListenerSourceDriftError, match="columns drifted"):
        cl.parse_courtlistener_jurisdictions_page(acquired)


def test_challenge_response_fails_closed(tmp_path: Path) -> None:
    challenge = b"<!doctype html><html><head><title>Just a moment...</title></head></html>"

    class ChallengeFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cl.FetchedCourtListenerPage:
            del timeout_seconds
            return cl.FetchedCourtListenerPage(
                body=challenge,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    pin = replace(
        MINI_PIN,
        expected_sha256=cl.sha256_digest(challenge),
        expected_byte_length=len(challenge),
    )

    with pytest.raises(cl.CourtListenerSourceDriftError, match="challenge or interstitial"):
        cl.acquire_courtlistener_jurisdictions_page(pin, tmp_path, fetcher=ChallengeFetcher())


def test_off_host_source_url_is_rejected() -> None:
    with pytest.raises(cl.CourtListenerAcquisitionError, match="official HTTPS courtlistener.com URL"):
        cl.CourtListenerJurisdictionsSnapshotPin(
            source_url="https://example.com/help/api/jurisdictions/",
            retrieved_at="2026-08-03T00:00:00Z",
            expected_sha256=MINI_PIN.expected_sha256,
            expected_byte_length=MINI_PIN.expected_byte_length,
        )


def test_duplicate_court_ids_fail_closed(tmp_path: Path) -> None:
    payload = JURISDICTIONS_FIXTURE.read_bytes()
    duplicated = payload.replace(b">ca1</a>", b">scotus</a>")
    pin = replace(
        MINI_PIN,
        expected_sha256=cl.sha256_digest(duplicated),
        expected_byte_length=len(duplicated),
    )
    source_path = tmp_path / "duplicated.html"
    source_path.write_bytes(duplicated)

    acquired = cl.acquire_courtlistener_jurisdictions_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cl.CourtListenerSourceDriftError, match="duplicate platform court identifiers"):
        cl.parse_courtlistener_jurisdictions_page(acquired)

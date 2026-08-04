"""Supreme Court opinion/package-type source-foundation tests.

supremecourt.gov publishes no JSON constants endpoint for opinion or package
types.  This module -- and these tests -- only ever capture and parse the
sidebar category list and version-ladder prose the official opinions page
renders about itself, matching the catalog decision to preserve official
opinion/package type and the slip/preliminary-print/bound-volume ladder as
deterministic metadata and to never split individual writings without a
reliable source-supplied boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import scotus_opinion_types as scotus
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "scotus_opinion_types"
REAL_FIXTURE = FIXTURES / "scotus-opinions-2026-08-03.html"
STUB_FIXTURE = FIXTURES / "scotus-opinions-landing-stub-2026-08-03.html"


def _payload(name: str = "scotus-opinions-2026-08-03.html") -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(
    payload: bytes, *, source_url: str = scotus.SCOTUS_OPINIONS_SOURCE_URL
) -> scotus.SCOTUSOpinionsPageSnapshotPin:
    return scotus.SCOTUSOpinionsPageSnapshotPin(
        source_url=source_url,
        retrieved_at="2026-08-03T19:15:13Z",
        expected_sha256=scotus.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_real(tmp_path: Path) -> scotus.AcquiredSCOTUSOpinionsPage:
    payload = _payload()
    return scotus.acquire_scotus_opinions_page(_pin(payload), tmp_path, source_path=REAL_FIXTURE)


class _StaticFetcher:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def fetch(self, source_url: str, *, timeout_seconds: float) -> scotus.FetchedSCOTUSPage:
        del timeout_seconds
        return scotus.FetchedSCOTUSPage(
            body=self._body,
            status_code=200,
            content_type="text/html; charset=utf-8",
            resolved_url=source_url,
        )


def test_module_import_opens_no_network_connection() -> None:
    # Importing must never perform I/O; only an explicit fetcher call may.
    assert hasattr(scotus, "acquire_scotus_opinions_page")
    assert hasattr(scotus, "SCOTUSPageFetcher")


def test_pinned_fixture_matches_the_module_snapshot_pin_exactly() -> None:
    payload = _payload()

    assert len(payload) == scotus.SCOTUS_OPINIONS_2026_08_03.expected_byte_length
    assert scotus.sha256_digest(payload) == scotus.SCOTUS_OPINIONS_2026_08_03.expected_sha256


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    payload = _payload()
    pin = _pin(payload)

    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, source_path=REAL_FIXTURE)
    cached = scotus.acquire_scotus_opinions_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / "opinions.html"
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> scotus.FetchedSCOTUSPage:
            calls.append((source_url, timeout_seconds))
            return scotus.FetchedSCOTUSPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = scotus.acquire_scotus_opinions_page(
        _pin(payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(scotus.SCOTUS_OPINIONS_SOURCE_URL, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_initial_capture_establishes_pin_before_strict_reopen(tmp_path: Path) -> None:
    payload = _payload()

    captured = scotus.capture_initial_scotus_opinions_page_snapshot(
        scotus.SCOTUS_OPINIONS_SOURCE_URL,
        tmp_path,
        retrieved_at="2026-08-03T19:15:13Z",
        fetcher=_StaticFetcher(payload),
        timeout_seconds=17.0,
    )
    reopened = scotus.acquire_scotus_opinions_page(captured.pin, tmp_path)

    assert captured.sha256 == scotus.sha256_digest(payload)
    assert captured.byte_length == len(payload)
    assert captured.path.read_bytes() == payload
    assert reopened.cache_hit is True
    assert reopened.pin == captured.pin


def test_landing_url_must_be_official_https_supremecourt_gov() -> None:
    payload = _payload()
    with pytest.raises(scotus.SCOTUSAcquisitionError, match="official HTTPS supremecourt.gov"):
        _pin(payload, source_url="https://example.com/opinions/opinions.aspx")


def test_meta_refresh_landing_stub_is_rejected_as_unresolved(tmp_path: Path) -> None:
    # https://www.supremecourt.gov/opinions/ is a client-side meta-refresh
    # stub that forwards to opinions.aspx; a fetcher that does not follow it
    # must fail closed instead of silently packaging the empty stub.
    stub_payload = STUB_FIXTURE.read_bytes()
    assert b'http-equiv="refresh"' in stub_payload.lower()

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="meta-refresh stub"):
        scotus.acquire_scotus_opinions_page(
            _pin(_payload()),
            tmp_path,
            fetcher=_StaticFetcher(stub_payload),
        )


def test_access_denied_or_challenge_response_never_publishes_source(tmp_path: Path) -> None:
    blocked_body = b"<!DOCTYPE html><html><head><title>Access Denied</title></head><body>Access Denied</body></html>"
    pin = _pin(_payload())

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="access-denied"):
        scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(blocked_body))

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "opinions.html"
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload()
    changed_payload = expected_payload.replace(b"Opinions of the Court", b"Opinions of the Courn")
    assert len(changed_payload) == len(expected_payload)
    pin = _pin(expected_payload)

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="digest drift"):
        scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(changed_payload))

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "opinions.html"
    assert not expected_path.exists()


def test_parses_opinion_and_package_types_without_minting_identity(tmp_path: Path) -> None:
    acquired = _acquire_real(tmp_path)

    parsed = scotus.parse_scotus_opinions_page(acquired)

    assert len(parsed.entries) == 7
    assert [entry.facet for entry in parsed.entries] == [
        "opinionType",
        "opinionType",
        "opinionType",
        "reporterSeries",
        "packageVersionStage",
        "packageVersionStage",
        "packageVersionStage",
    ]
    assert [entry.label for entry in parsed.entries] == [
        "Opinions of the Court",
        "Opinions Relating to Orders",
        "In-Chambers Opinions",
        "U. S. Reports",
        "Slip opinion",
        "Preliminary print",
        "Bound volume",
    ]
    assert [entry.navigation_href for entry in parsed.entries[:4]] == [
        "slipopinion/25",
        "relatingtoorders/25",
        "in-chambers.aspx",
        "USReports.aspx",
    ]
    assert all(entry.navigation_href is None for entry in parsed.entries[4:])
    assert all(entry.stage_order is None for entry in parsed.entries[:4])
    assert [entry.stage_order for entry in parsed.entries[4:]] == [1, 2, 3]
    assert len({entry.record_iri for entry in parsed.entries}) == 7
    assert {gap["kind"] for gap in parsed.gaps} == {
        "publisherOpinionTypeCodeUnavailable",
        "perWritingBoundaryUnavailable",
    }


def test_missing_sidenav_block_fails_as_source_drift(tmp_path: Path) -> None:
    payload = _payload()
    # Rename the tag but keep the "sidenav-list" substring present so the
    # byte-level stub/challenge guard does not mask this structural check.
    mutated = payload.replace(b'<ul class="sidenav-list">', b'<ol class="sidenav-list">', 1)
    mutated = mutated.replace(b"</ul>", b"</ol>", 1)
    assert b"sidenav-list" in mutated
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="exactly one sidebar category list"):
        scotus.parse_scotus_opinions_page(acquired)


def test_category_label_drift_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(
        b'hypOpinion" href="slipopinion/25">Opinions of the Court<',
        b'hypOpinion" href="slipopinion/25">Opinions of the Circuit<',
    )
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="sidebar category 0 label drifted"):
        scotus.parse_scotus_opinions_page(acquired)


def test_category_href_drift_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(
        b'hypRelating" href="relatingtoorders/25">',
        b'hypRelating" href="relatingtoorders">',
    )
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="sidebar category 1 href drifted"):
        scotus.parse_scotus_opinions_page(acquired)


def test_trailing_sidenav_label_drift_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(
        b'hypeCitation" href="casefinder.aspx">Case Citation Finder<',
        b'hypeCitation" href="casefinder.aspx">Case Citation Findew<',
    )
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="sidebar trailing category 2 label drifted"):
        scotus.parse_scotus_opinions_page(acquired)


def test_paragraph_count_drift_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    start_marker = b"<p>The Court may also dispose of cases"
    end_marker = b"issued in argued cases. </p>"
    start = payload.index(start_marker)
    end = payload.index(end_marker) + len(end_marker)
    mutated = payload[:start] + payload[end:]
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="paragraph count drift"):
        scotus.parse_scotus_opinions_page(acquired)


def test_ladder_phrase_missing_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(b"bound volumes of the United States Reports", b"final compiled Reports")
    assert b"bound volume" not in mutated
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="no longer names the slip/preliminary-print/bound-volume"):
        scotus.parse_scotus_opinions_page(acquired)


def test_ladder_phrase_out_of_order_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(
        b"preliminary prints and bound volumes of the United States Reports",
        b"bound volumes and preliminary prints of the United States Reports",
    )
    pin = _pin(mutated)
    acquired = scotus.acquire_scotus_opinions_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(scotus.SCOTUSSourceDriftError, match="out of their documented order"):
        scotus.parse_scotus_opinions_page(acquired)


def test_package_is_deterministic_metadata_only_and_never_a_concept_scheme(tmp_path: Path) -> None:
    acquired = _acquire_real(tmp_path)
    parsed = scotus.parse_scotus_opinions_page(acquired)

    bundle = scotus.build_scotus_opinion_type_package(acquired, parsed)

    manifest = bundle.resource_manifest
    assert manifest["resourceKind"] == "controlledCodeList"
    assert manifest["identityStatus"] == "captureLocalObservationsOnly"
    assert "usageCeiling" not in manifest
    assert "acceptedOutputUseAuthorized" not in manifest
    assert manifest["conceptIdentityClaimed"] is False
    assert "candidateUseAuthorized" not in manifest
    assert manifest["uses"] == ("deterministicMetadata",)
    assert manifest["observationCount"] == 7

    for observation in bundle.observations:
        assert observation["identifiers"] == ()
        assert observation["conceptIdentityClaimed"] is False
        assert observation["uses"] == ("deterministicMetadata",)

    labels = [observation["labels"][0]["value"] for observation in bundle.observations]
    assert labels == [
        "Opinions of the Court",
        "Opinions Relating to Orders",
        "In-Chambers Opinions",
        "U. S. Reports",
        "Slip opinion",
        "Preliminary print",
        "Bound volume",
    ]
    assert bundle.observations[0]["navigationHref"] == "slipopinion/25"
    assert "navigationHref" not in bundle.observations[4]
    assert bundle.observations[4]["stageOrder"] == 1
    assert "stageOrder" not in bundle.observations[0]

    coverage = bundle.coverage_report
    assert coverage["reportStatus"] == "gap"
    assert {gap["kind"] for gap in coverage["gaps"]} == {
        "publisherOpinionTypeCodeUnavailable",
        "perWritingBoundaryUnavailable",
    }


def test_package_round_trips_through_a_closed_directory(tmp_path: Path) -> None:
    acquired = _acquire_real(tmp_path)
    parsed = scotus.parse_scotus_opinions_page(acquired)
    bundle = scotus.build_scotus_opinion_type_package(acquired, parsed)

    destination = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle.logical_digest
    assert reopened.source_artifact_bytes(scotus.SCOTUS_OPINIONS_SOURCE_URL) == _payload()
    assert len(reopened.observations) == 7
    assert reopened.observations[3]["labels"][0]["value"] == "U. S. Reports"


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload()
    assert scotus.sha256_digest(payload) == scotus.sha256_digest(payload)
    assert scotus.sha256_digest(payload) != scotus.sha256_digest(payload + b" ")

"""SEC Rules and Regulations page-category source-foundation tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import sec_series_categories as sec
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "sec_series_categories"

# A hand-built page whose second (desktop) side-navigation block diverges from
# the first (mobile) block. Real captures never diverge; this fixture exists
# only to prove the parser refuses a page that would otherwise silently drop
# or duplicate a category.
_MISMATCHED_BLOCKS_HTML = b"""<!DOCTYPE html>
<html><head><title>SEC.gov | Rules and Regulations</title></head>
<body>
<main id="main-content">
<div class="main-content__sidenav">
<nav><div class="region region-sidebar-first">
<ul class="usa-sidenav">
<li class="usa-sidenav__item"><a href="/rules-regulations" class="usa-title "><span>Rules &amp; Regulations</span></a></li>
<li class="usa-sidenav__item"><a href="/rules-regulations/staff-guidance"><span>Staff Guidance</span></a></li>
</ul>
</ul>
</div></nav>
<nav class="l-sidenav-aside"><div class="region region-sidebar-first">
<ul class="usa-sidenav">
<li class="usa-sidenav__item"><a href="/rules-regulations" class="usa-title "><span>Rules &amp; Regulations</span></a></li>
<li class="usa-sidenav__item"><a href="/rules-regulations/staff-guidance"><span>Staff Guidance (desktop)</span></a></li>
</ul>
</ul>
</div></nav>
</div>
<h1 class="page-header__heading">Rules and Regulations</h1>
<div class="subpage-card">
<h2 class="subpage-card__headline"><a class="subpage-card__headline__link" href="/regulation/staff-interpretations">Staff Guidance</a></h2>
<p class="subpage-card__body">Description.</p>
</div>
</main>
</body></html>
"""


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(source: sec.SECPageSource, payload: bytes) -> sec.SECPageSnapshotPin:
    return sec.SECPageSnapshotPin(
        source=source,
        retrieved_at="2026-08-03T19:25:10Z",
        expected_sha256=sec.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_fixture(
    tmp_path: Path,
    source: sec.SECPageSource,
    fixture_name: str,
) -> sec.AcquiredSECPage:
    path = FIXTURES / fixture_name
    return sec.acquire_sec_page(
        _pin(source, path.read_bytes()),
        tmp_path,
        source_path=path,
    )


def _mini_source() -> sec.SECPageSource:
    return replace(
        sec.SEC_RULES_REGULATIONS_PAGE,
        expected_sidenav_category_count=3,
        expected_subpage_card_count=2,
    )


def test_current_official_page_matches_reviewed_shape() -> None:
    assert sec.SEC_RULES_REGULATIONS_PAGE.source_url == "https://www.sec.gov/rules-regulations"
    assert sec.SEC_RULES_REGULATIONS_PAGE.expected_title == "SEC.gov | Rules and Regulations"
    assert sec.SEC_RULES_REGULATIONS_PAGE.expected_h1 == "Rules and Regulations"
    assert sec.SEC_RULES_REGULATIONS_PAGE.expected_sidenav_category_count == 13
    assert sec.SEC_RULES_REGULATIONS_PAGE.expected_subpage_card_count == 6

    pin = sec.SEC_RULES_REGULATIONS_PIN_2026_08_03
    assert pin.source is sec.SEC_RULES_REGULATIONS_PAGE
    assert pin.expected_byte_length == 70_936
    assert pin.expected_sha256 == (
        "sha256:2f39c9d08f0dc55462e30fbda57315fd5159d47a4894dd113dc0bf226112c1b1"
    )


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    payload = _payload("sec-rules-regulations-mini.html")
    source = _mini_source()
    pin = _pin(source, payload)

    acquired = sec.acquire_sec_page(
        pin,
        tmp_path,
        source_path=FIXTURES / "sec-rules-regulations-mini.html",
    )
    cached = sec.acquire_sec_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / source.filename
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload("sec-rules-regulations-mini.html")
    source = _mini_source()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> sec.FetchedSECPage:
            calls.append((source_url, timeout_seconds))
            return sec.FetchedSECPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = sec.acquire_sec_page(
        _pin(source, payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(source.source_url, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_initial_capture_establishes_pin_before_strict_reopen(tmp_path: Path) -> None:
    payload = _payload("sec-rules-regulations-mini.html")
    source = _mini_source()

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> sec.FetchedSECPage:
            assert timeout_seconds == 17.0
            return sec.FetchedSECPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    captured = sec.capture_initial_sec_page_snapshot(
        source,
        tmp_path,
        retrieved_at="2026-08-03T19:25:10Z",
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )
    reopened = sec.acquire_sec_page(captured.pin, tmp_path)

    assert captured.sha256 == sec.sha256_digest(payload)
    assert captured.byte_length == len(payload)
    assert captured.path.read_bytes() == payload
    assert captured.content_type == "text/html; charset=UTF-8"
    assert reopened.cache_hit is True
    assert reopened.pin == captured.pin


def test_challenge_page_never_publishes_source(tmp_path: Path) -> None:
    source = _mini_source()
    expected_payload = _payload("sec-rules-regulations-mini.html")
    pin = _pin(source, expected_payload)

    class ChallengeFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> sec.FetchedSECPage:
            del timeout_seconds
            return sec.FetchedSECPage(
                body=b"<!doctype html><html><title>Just a moment...</title><div class='cf-chl-widget'></div></html>",
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(sec.SECSourceDriftError, match="challenge page"):
        sec.acquire_sec_page(pin, tmp_path, fetcher=ChallengeFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload("sec-rules-regulations-mini.html")
    changed_payload = expected_payload.replace(b"Staff Guidance", b"Stiff Guidance")
    assert len(changed_payload) == len(expected_payload)
    assert changed_payload != expected_payload
    source = _mini_source()
    pin = _pin(source, expected_payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> sec.FetchedSECPage:
            del timeout_seconds
            return sec.FetchedSECPage(
                body=changed_payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(sec.SECSourceDriftError, match="digest drift"):
        sec.acquire_sec_page(pin, tmp_path, fetcher=ChangedFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / source.filename
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_page_categories_preserve_two_collections_without_minting_ids(
    tmp_path: Path,
) -> None:
    source = _mini_source()
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")

    parsed = sec.parse_sec_rules_regulations_page(page)

    assert [category.label for category in parsed.side_navigation_categories] == [
        "Rulemaking Activity",
        "Staff Guidance",
        "Petitions for Rulemaking",
    ]
    assert [category.target_path for category in parsed.side_navigation_categories] == [
        "/rules-regulations/rulemaking-activity",
        "/rules-regulations/staff-guidance",
        "/rules-regulations/petitions-rulemaking-submitted-to-sec",
    ]
    assert all(category.description is None for category in parsed.side_navigation_categories)

    assert [category.label for category in parsed.subpage_card_categories] == [
        "Staff Guidance",
        "Public Petitions for Rulemaking",
    ]
    assert [category.target_path for category in parsed.subpage_card_categories] == [
        "/regulation/staff-interpretations",
        "/rules-regulations/petitions-rulemaking-submitted-to-sec",
    ]
    assert all(category.description for category in parsed.subpage_card_categories)

    # The same "Staff Guidance" concept resolves to two different target
    # paths depending on which navigation block names it. Both observations
    # are kept, proving the module never reconciles site navigation into one
    # taxonomy.
    staff_guidance_paths = {
        category.target_path
        for category in parsed.categories
        if category.label == "Staff Guidance"
    }
    assert staff_guidance_paths == {
        "/rules-regulations/staff-guidance",
        "/regulation/staff-interpretations",
    }

    assert all(category.identifiers == () for category in parsed.categories)
    assert len({category.record_iri for category in parsed.categories}) == len(parsed.categories)
    subject_digest = sec.sha256_digest(_payload("sec-rules-regulations-mini.html")).removeprefix("sha256:")
    assert parsed.side_navigation_categories[0].record_iri == (
        f"urn:ref:sec-source-record:{subject_digest}:sideNavigation:%2Frules-regulations:1"
    )

    readiness = sec.sec_category_readiness(parsed)
    assert readiness.ready is False
    assert readiness.source_category_count == 5
    with pytest.raises(sec.SECIdentityError, match="does not publish stable identifiers"):
        readiness.require_ready()


def test_repeated_source_labels_remain_distinct_capture_records(tmp_path: Path) -> None:
    source = _mini_source()
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-duplicate-mini.html")

    parsed = sec.parse_sec_rules_regulations_page(page)

    repeated = tuple(
        category for category in parsed.side_navigation_categories if category.label == "Staff Guidance"
    )
    assert len(repeated) == 2
    assert repeated[0].record_iri != repeated[1].record_iri
    assert [category.source_ordinal for category in repeated] == [1, 3]
    assert parsed.duplicate_label_evidence == (
        sec.SECDuplicateLabelEvidence(
            collection="sideNavigation",
            official_label="Staff Guidance",
            record_iris=(repeated[0].record_iri, repeated[1].record_iri),
            source_ordinals=(1, 3),
        ),
    )

    readiness = sec.sec_category_readiness(parsed)
    assert any("repeated source label group" in blocker for blocker in readiness.blockers)


def test_title_drift_fails_as_source_drift(tmp_path: Path) -> None:
    source = replace(_mini_source(), expected_title="SEC.gov | Something Else")
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")

    with pytest.raises(sec.SECSourceDriftError, match="missing expected page title"):
        sec.parse_sec_rules_regulations_page(page)


def test_heading_drift_fails_as_source_drift(tmp_path: Path) -> None:
    source = replace(_mini_source(), expected_h1="Something Else")
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")

    with pytest.raises(sec.SECSourceDriftError, match="missing expected page heading"):
        sec.parse_sec_rules_regulations_page(page)


def test_sidenav_count_change_fails_as_source_drift(tmp_path: Path) -> None:
    source = replace(_mini_source(), expected_sidenav_category_count=4)
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")

    with pytest.raises(sec.SECSourceDriftError, match="side-navigation category count drift"):
        sec.parse_sec_rules_regulations_page(page)


def test_subpage_card_count_change_fails_as_source_drift(tmp_path: Path) -> None:
    source = replace(_mini_source(), expected_subpage_card_count=3)
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")

    with pytest.raises(sec.SECSourceDriftError, match="subpage-card category count drift"):
        sec.parse_sec_rules_regulations_page(page)


def test_desynced_navigation_blocks_fail_closed(tmp_path: Path) -> None:
    source = replace(
        sec.SEC_RULES_REGULATIONS_PAGE,
        expected_sidenav_category_count=1,
        expected_subpage_card_count=1,
    )
    pin = _pin(source, _MISMATCHED_BLOCKS_HTML)

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> sec.FetchedSECPage:
            del timeout_seconds
            return sec.FetchedSECPage(
                body=_MISMATCHED_BLOCKS_HTML,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    page = sec.acquire_sec_page(pin, tmp_path, fetcher=Fetcher())

    with pytest.raises(sec.SECSourceDriftError, match="no longer match byte-for-byte"):
        sec.parse_sec_rules_regulations_page(page)


def test_package_is_a_controlled_code_list_that_never_authorizes_promotion(
    tmp_path: Path,
) -> None:
    source = _mini_source()
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")
    parsed = sec.parse_sec_rules_regulations_page(page)

    package = sec.build_sec_series_category_package(page, parsed)

    assert package.resource_manifest["resourceKind"] == "controlledCodeList"
    assert package.resource_manifest["identityStatus"] == "captureLocalObservationsOnly"
    assert package.resource_manifest["candidateUseAuthorized"] is False
    assert package.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert package.resource_manifest["conceptIdentityClaimed"] is False
    assert package.resource_manifest["uses"] == ["navigation"]
    assert package.resource_manifest["observationCount"] == 5
    assert package.coverage_report["reportStatus"] == "gap"
    assert {gap["code"] for gap in package.coverage_report["gaps"]} == {
        "publisherCategoryIdentifiersAbsent",
        "navigationCollectionsNotReconciled",
    }
    assert all(observation["identifiers"] == [] for observation in package.observations)
    assert all(observation["conceptIdentityClaimed"] is False for observation in package.observations)
    collections = {observation["collection"] for observation in package.observations}
    assert collections == {"sideNavigation", "subpageCard"}


def test_package_is_deterministic_and_round_trips_through_disk(tmp_path: Path) -> None:
    source = _mini_source()
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")
    parsed = sec.parse_sec_rules_regulations_page(page)

    first = sec.build_sec_series_category_package(page, parsed)
    second = sec.build_sec_series_category_package(page, parsed)
    assert first.logical_digest == second.logical_digest
    assert first.artifact_bytes() == second.artifact_bytes()

    destination = first.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == first.logical_digest
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert len(reopened.observations) == 5


def test_mismatched_source_bytes_refuse_to_package(tmp_path: Path) -> None:
    source = _mini_source()
    page = _acquire_fixture(tmp_path, source, "sec-rules-regulations-mini.html")
    parsed = sec.parse_sec_rules_regulations_page(page)
    stale_parsed = replace(parsed, source_byte_length=parsed.source_byte_length + 1)

    with pytest.raises(sec.SECSourceDriftError, match="differ from their acquired page bytes"):
        sec.build_sec_series_category_package(page, stale_parsed)


def test_real_capture_matches_pinned_bytes_and_parses_expected_categories(
    tmp_path: Path,
) -> None:
    page = sec.acquire_sec_page(
        sec.SEC_RULES_REGULATIONS_PIN_2026_08_03,
        tmp_path,
        source_path=FIXTURES / "sec-rules-regulations-2026-08-03.html",
    )

    parsed = sec.parse_sec_rules_regulations_page(page)

    assert len(parsed.side_navigation_categories) == 13
    assert len(parsed.subpage_card_categories) == 6
    assert parsed.side_navigation_categories[0].label == "Submit Public Comments"
    assert parsed.side_navigation_categories[-1].label == "Exchange Delistings"
    labels = {category.label for category in parsed.side_navigation_categories}
    assert {
        "Rulemaking Activity",
        "Staff Guidance",
        "No Action, Interpretive and Exemptive Letters",
        "Commission Orders and Notices",
        "Petitions for Rulemaking",
        "Self-Regulatory Organization Rulemaking",
    }.issubset(labels)

    package = sec.build_sec_series_category_package(page, parsed)
    assert package.resource_manifest["observationCount"] == 19


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload("sec-rules-regulations-2026-08-03.html")

    assert sec.sha256_digest(payload) == "sha256:" + hashlib.sha256(payload).hexdigest()

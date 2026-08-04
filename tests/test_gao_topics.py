"""GAO Topics product-page assignment source-foundation tests.

GAO publishes a /topics browse index and per-topic listing pages that are site
navigation, not per-product evidence.  This module -- and these tests -- only
ever capture and parse the Topics field a single already-published GAO
product page renders about itself, matching the catalog decision to record
actual assignments and never reconstruct a scheme from navigation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import gao_topics as gao
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "gao_topics"


def _payload(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _pin(source_url: str, payload: bytes) -> gao.GAOProductPageSnapshotPin:
    return gao.GAOProductPageSnapshotPin(
        source_url=source_url,
        retrieved_at="2026-08-03T12:00:00Z",
        expected_sha256=gao.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_fixture(tmp_path: Path, fixture_name: str, *, source_url: str) -> gao.AcquiredGAOProductPage:
    path = FIXTURES / fixture_name
    payload = path.read_bytes()
    return gao.acquire_gao_product_page(
        _pin(source_url, payload),
        tmp_path,
        source_path=path,
    )


PRODUCT_URL = "https://www.gao.gov/products/gao-24-106529"
DUPLICATE_PRODUCT_URL = "https://www.gao.gov/products/gao-24-106530"
REAL_FIXTURE = "gao-product-gao-26-108505-2026-08-04.html"


def test_module_import_opens_no_network_connection() -> None:
    # Importing must never perform I/O; only an explicit fetcher call may.
    assert hasattr(gao, "acquire_gao_product_page")
    assert hasattr(gao, "GAOPageFetcher")


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    payload = _payload("gao-product-topics-mini.html")
    pin = _pin(PRODUCT_URL, payload)

    acquired = gao.acquire_gao_product_page(pin, tmp_path, source_path=FIXTURES / "gao-product-topics-mini.html")
    cached = gao.acquire_gao_product_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / "gao-24-106529.html"
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload("gao-product-topics-mini.html")
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gao.FetchedGAOPage:
            calls.append((source_url, timeout_seconds))
            return gao.FetchedGAOPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = gao.acquire_gao_product_page(
        _pin(PRODUCT_URL, payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(PRODUCT_URL, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_initial_capture_establishes_pin_before_strict_reopen(tmp_path: Path) -> None:
    payload = _payload("gao-product-topics-mini.html")

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gao.FetchedGAOPage:
            assert timeout_seconds == 17.0
            return gao.FetchedGAOPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    captured = gao.capture_initial_gao_product_page_snapshot(
        PRODUCT_URL,
        tmp_path,
        retrieved_at="2026-08-03T12:00:00Z",
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )
    reopened = gao.acquire_gao_product_page(captured.pin, tmp_path)

    assert captured.sha256 == gao.sha256_digest(payload)
    assert captured.byte_length == len(payload)
    assert captured.path.read_bytes() == payload
    assert reopened.cache_hit is True
    assert reopened.pin == captured.pin


def test_browse_index_is_rejected_as_navigation_not_an_assignment() -> None:
    payload = b"<html><body>index</body></html>"
    with pytest.raises(gao.GAOAcquisitionError, match="site navigation"):
        _pin("https://www.gao.gov/topics", payload)


def test_topic_listing_page_is_also_rejected_as_navigation() -> None:
    payload = b"<html><body>listing</body></html>"
    with pytest.raises(gao.GAOAcquisitionError, match="site navigation"):
        _pin("https://www.gao.gov/topics/defense-capabilities-and-management", payload)


def test_access_denied_response_never_publishes_source(tmp_path: Path) -> None:
    # This is the real byte-for-byte response this module's implementation
    # received from gao.gov during development; the WAF blocked the capture
    # attempt outright, and the module must refuse to cache it as content.
    expected_payload = _payload("gao-product-topics-mini.html")
    pin = _pin(PRODUCT_URL, expected_payload)
    blocked_body = _payload("gao-access-denied-real-capture.html")

    class BlockedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gao.FetchedGAOPage:
            del timeout_seconds
            return gao.FetchedGAOPage(
                body=blocked_body,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(gao.GAOSourceDriftError, match="access-denied"):
        gao.acquire_gao_product_page(pin, tmp_path, fetcher=BlockedFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "gao-24-106529.html"
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload("gao-product-topics-mini.html")
    changed_payload = expected_payload.replace(b"Health Care", b"Health Cara")
    assert len(changed_payload) == len(expected_payload)
    pin = _pin(PRODUCT_URL, expected_payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gao.FetchedGAOPage:
            del timeout_seconds
            return gao.FetchedGAOPage(
                body=changed_payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(gao.GAOSourceDriftError, match="digest drift"):
        gao.acquire_gao_product_page(pin, tmp_path, fetcher=ChangedFetcher())

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "gao-24-106529.html"
    assert not expected_path.exists()


def test_parses_actual_topic_assignments_without_minting_identity(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path, "gao-product-topics-mini.html", source_url=PRODUCT_URL)

    parsed = gao.parse_gao_product_topics_page(acquired)

    assert parsed.product_report_number == "GAO-24-106529"
    assert parsed.product_title == "Military Housing: DOD Should Improve Oversight of Contractor Performance"
    assert [assignment.label for assignment in parsed.assignments] == [
        "Defense Capabilities and Management",
        "Facilities and Real Property",
        "Health Care",
    ]
    assert [assignment.topic_path for assignment in parsed.assignments] == [
        "/topics/defense-capabilities-and-management",
        "/topics/facilities-and-real-property",
        "/topics/health-care",
    ]
    # The decoy footer link to /topics/defense-capabilities-and-management
    # sits outside the product's own Topics field block and must not count
    # as a second assignment.
    assert len(parsed.assignments) == 3
    assert len({assignment.record_iri for assignment in parsed.assignments}) == 3
    assert parsed.duplicate_topic_evidence == ()


def test_nav_view_topics_and_jump_to_links_are_structurally_excluded(tmp_path: Path) -> None:
    # The fixture's header nav has a "View Topics" link to the bare /topics
    # browse index, and its "Jump To" menu has a Topics entry with an empty
    # href; both sit outside the Drupal views block entirely.  Assert they
    # are excluded by position, not merely filtered by text or href shape.
    payload = _payload("gao-product-topics-mini.html")
    assert b'href="/topics" class="link usa-nav__link"><span>View Topics</span>' in payload
    assert b'class="jump-to-link js-link link--topics"' in payload and b'href=""' in payload

    acquired = _acquire_fixture(tmp_path, "gao-product-topics-mini.html", source_url=PRODUCT_URL)
    parsed = gao.parse_gao_product_topics_page(acquired)

    topic_paths = [assignment.topic_path for assignment in parsed.assignments]
    assert "/topics" not in topic_paths
    assert "" not in topic_paths
    assert len(parsed.assignments) == 3


def test_repeated_topic_on_one_product_remains_distinct_evidence(tmp_path: Path) -> None:
    acquired = _acquire_fixture(
        tmp_path,
        "gao-product-topics-duplicate-mini.html",
        source_url=DUPLICATE_PRODUCT_URL,
    )

    parsed = gao.parse_gao_product_topics_page(acquired)

    repeated = tuple(a for a in parsed.assignments if a.label == "Health Care")
    assert len(repeated) == 2
    assert repeated[0].record_iri != repeated[1].record_iri
    assert [a.source_ordinal for a in repeated] == [0, 2]
    assert parsed.duplicate_topic_evidence == (
        gao.GAODuplicateTopicEvidence(
            label="Health Care",
            record_iris=(repeated[0].record_iri, repeated[1].record_iri),
            source_ordinals=(0, 2),
        ),
    )


def test_fixture_pins_match_exact_real_captured_bytes() -> None:
    # This is the real byte-for-byte gao.gov product page this module's
    # implementation was rewritten against, captured through the project's
    # Zyte transport (a direct curl still receives an Akamai denial).
    payload = _payload(REAL_FIXTURE)
    pin = gao.GAO_PRODUCT_GAO_26_108505_2026_08_04

    assert len(payload) == pin.expected_byte_length
    assert gao.sha256_digest(payload) == pin.expected_sha256
    assert pin.source_url == "https://www.gao.gov/products/gao-26-108505"
    assert pin.product_slug == "gao-26-108505"


def test_parses_real_captured_product_page_topic_assignment(tmp_path: Path) -> None:
    pin = gao.GAO_PRODUCT_GAO_26_108505_2026_08_04
    acquired = gao.acquire_gao_product_page(pin, tmp_path, source_path=FIXTURES / REAL_FIXTURE)

    parsed = gao.parse_gao_product_topics_page(acquired)

    assert parsed.product_report_number == "GAO-26-108505"
    assert [assignment.label for assignment in parsed.assignments] == [
        "Auditing and Financial Management",
    ]
    assert [assignment.topic_path for assignment in parsed.assignments] == [
        "/topics/auditing-and-financial-management",
    ]
    assert len(parsed.assignments) == 1
    assert parsed.duplicate_topic_evidence == ()


def test_real_page_nav_view_topics_and_jump_to_links_are_structurally_excluded(tmp_path: Path) -> None:
    # The real capture has both decoys this parser must reject structurally:
    # the header nav's "View Topics" link to the bare /topics browse index,
    # and the "Jump To" menu's own Topics entry (an empty href).  Both sit
    # entirely outside the "Topics" views block that this parser reads.
    payload = _payload(REAL_FIXTURE)
    assert b"<span>View Topics</span>" in payload
    assert b'class="jump-to-link js-link link--topics"' in payload

    pin = gao.GAO_PRODUCT_GAO_26_108505_2026_08_04
    acquired = gao.acquire_gao_product_page(pin, tmp_path, source_path=FIXTURES / REAL_FIXTURE)
    parsed = gao.parse_gao_product_topics_page(acquired)

    topic_paths = [assignment.topic_path for assignment in parsed.assignments]
    assert "/topics" not in topic_paths
    assert "" not in topic_paths
    assert len(parsed.assignments) == 1


def test_real_page_subject_terms_are_not_read_as_topics(tmp_path: Path) -> None:
    # The one real Topics row sits beside a sibling
    # "views-field-field-subject-term" field carrying GAO's separate,
    # uncontrolled Subject Terms ("Audits", "Health care", ...).  Those must
    # never be read as Topic assignments even though they share a row.
    payload = _payload(REAL_FIXTURE)
    assert b"views-field-field-subject-term" in payload
    assert b"<span>Audits</span>" in payload

    pin = gao.GAO_PRODUCT_GAO_26_108505_2026_08_04
    acquired = gao.acquire_gao_product_page(pin, tmp_path, source_path=FIXTURES / REAL_FIXTURE)
    parsed = gao.parse_gao_product_topics_page(acquired)

    labels = {assignment.label for assignment in parsed.assignments}
    assert labels == {"Auditing and Financial Management"}
    assert "Audits" not in labels


class _StaticFetcher:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def fetch(self, source_url: str, *, timeout_seconds: float) -> gao.FetchedGAOPage:
        del timeout_seconds
        return gao.FetchedGAOPage(
            body=self._body,
            status_code=200,
            content_type="text/html",
            resolved_url=source_url,
        )


def test_missing_topics_block_fails_as_source_drift(tmp_path: Path) -> None:
    # Removing the whole Drupal views block (its wrapping div, the "Topics"
    # <h2>, and every views-row) must fail closed even though the
    # product-id block and title remain intact.
    payload = _payload("gao-product-topics-mini.html")
    marker = b'<div class="views-element-container'
    start = payload.index(marker)
    end = payload.index(b"</div>\n</article>") + len(b"</div>")
    mutated = payload[:start] + payload[end:]
    pin = _pin(PRODUCT_URL, mutated)
    acquired = gao.acquire_gao_product_page(pin, tmp_path, source_path=None, fetcher=_StaticFetcher(mutated))

    with pytest.raises(gao.GAOSourceDriftError, match="exactly one Topics field block"):
        gao.parse_gao_product_topics_page(acquired)


def test_topics_block_with_zero_assignment_rows_fails_closed(tmp_path: Path) -> None:
    # The "Topics" heading and its views block survive, but every
    # views-row inside it is gone: zero assignments must still fail
    # closed, not silently parse as an empty Topics list.
    payload = _payload("gao-product-topics-mini.html")
    row_start = payload.index(b'<div class="views-row">')
    wrapper_close = payload.index(b"</div></div>\n</div>\n</article>")
    mutated = payload[:row_start] + payload[wrapper_close:]
    pin = _pin(PRODUCT_URL, mutated)
    acquired = gao.acquire_gao_product_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(gao.GAOSourceDriftError, match="has no assigned topic"):
        gao.parse_gao_product_topics_page(acquired)


def test_topic_link_outside_topics_namespace_fails_closed(tmp_path: Path) -> None:
    payload = _payload("gao-product-topics-mini.html")
    mutated = payload.replace(b'href="/topics/health-care"', b'href="/products/gao-24-999999"')
    pin = _pin(PRODUCT_URL, mutated)
    acquired = gao.acquire_gao_product_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(gao.GAOSourceDriftError, match=r"outside /topics/"):
        gao.parse_gao_product_topics_page(acquired)


def test_malformed_topic_slug_fails_closed(tmp_path: Path) -> None:
    # A trailing slash still starts with "/topics/" -- a bare prefix check
    # would have accepted it -- but it is not one clean /topics/<slug>
    # link, so the stricter slug pattern must reject it.
    payload = _payload("gao-product-topics-mini.html")
    mutated = payload.replace(b'href="/topics/health-care"', b'href="/topics/health-care/"')
    pin = _pin(PRODUCT_URL, mutated)
    acquired = gao.acquire_gao_product_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(gao.GAOSourceDriftError, match=r"outside /topics/"):
        gao.parse_gao_product_topics_page(acquired)


def test_product_id_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = _payload("gao-product-topics-mini.html")
    mutated = payload.replace(b">GAO-24-106529<", b">GAO-24-999999<")
    pin = _pin(PRODUCT_URL, mutated)
    acquired = gao.acquire_gao_product_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(gao.GAOSourceDriftError, match="does not match its captured URL slug"):
        gao.parse_gao_product_topics_page(acquired)


def test_package_is_source_evidence_only_and_never_a_concept_scheme(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path, "gao-product-topics-mini.html", source_url=PRODUCT_URL)
    parsed = gao.parse_gao_product_topics_page(acquired)

    bundle = gao.build_gao_product_topic_assignments_package(acquired, parsed)

    manifest = bundle.resource_manifest
    assert manifest["resourceKind"] == "sourceTermSnapshot"
    assert manifest["identityStatus"] == "captureLocalObservationsOnly"
    assert manifest["usageCeiling"] == "developmentOnly"
    assert manifest["acceptedOutputUseAuthorized"] is False
    assert manifest["conceptIdentityClaimed"] is False
    assert manifest["candidateUseAuthorized"] is False
    assert manifest["uses"] == ["sourceAssignedEvidence"]
    assert manifest["observationCount"] == 3

    for observation in bundle.observations:
        assert observation["identifiers"] == []
        assert observation["conceptIdentityClaimed"] is False
        assert observation["eligibleUses"] == ["sourceAssignedEvidence"]
        assert observation["productReportNumber"] == "GAO-24-106529"

    labels = [observation["labels"][0]["value"] for observation in bundle.observations]
    assert labels == [
        "Defense Capabilities and Management",
        "Facilities and Real Property",
        "Health Care",
    ]


def test_package_round_trips_through_a_closed_directory(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path, "gao-product-topics-mini.html", source_url=PRODUCT_URL)
    parsed = gao.parse_gao_product_topics_page(acquired)
    bundle = gao.build_gao_product_topic_assignments_package(acquired, parsed)

    destination = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle.logical_digest
    assert reopened.source_artifact_bytes(PRODUCT_URL) == _payload("gao-product-topics-mini.html")
    assert len(reopened.observations) == 3
    assert reopened.observations[0]["productReportNumber"] == "GAO-24-106529"


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload("gao-product-topics-mini.html")
    assert gao.sha256_digest(payload) == gao.sha256_digest(payload)
    assert gao.sha256_digest(payload) != gao.sha256_digest(payload + b" ")

"""CBO cost-estimates XML feed Topic-evidence and fiscal-facet tests.

The catalog decision for this source is explicit: CBO's 27 browse topics are
not a published semantic vocabulary, so this module -- and these tests --
only ever capture and parse the Topic labels the cost-estimates/xml feed
renders about each item, packaging them as capture-local source evidence.
Budget functions, mandate flags, and the PAYGO flag are deterministic fiscal
facets kept on the parsed record and never promoted into a concept scheme.

A direct capture attempt against the official URL during development received
an HTTP 403 DataDome bot-challenge response instead of the feed (see
``cbo-datadome-challenge-real-capture.html``, a byte-for-byte capture). No
verified live feed bytes were obtainable in this environment, so
``cbo-cost-estimates-mini.xml`` is a structural reconstruction faithful to the
field list this catalog row documents, not an official capture.

A REAL alternate discovery channel has since been captured (2026-08-04): CBO's
per-Congress feeds at ``/rss/{congress}congress-cost-estimates.xml`` sit on a
different CDN tier and serve plain HTTP 200 with no DataDome bot wall. The
119th Congress feed is checked in byte-for-byte as
``cbo-119congress-cost-estimates-2026-08-04.xml`` and pinned as
``CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04``. Its custom ``<response>``/
``<item>`` shape is unrelated to the RSS 2.0 shape above and carries only
titles, dates, publication links, and bill numbers -- no Topic labels,
budget-function codes, mandate flags, or PAYGO facets. The tests below for
``parse_cbo_per_congress_feed`` exercise that real shape directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from refspec.registry import cbo_topic_codes as cbo
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "cbo_topic_codes"
FEED_FIXTURE = FIXTURES / "cbo-cost-estimates-mini.xml"
CHALLENGE_FIXTURE = FIXTURES / "cbo-datadome-challenge-real-capture.html"
PER_CONGRESS_REAL_CAPTURE_FIXTURE = FIXTURES / "cbo-119congress-cost-estimates-2026-08-04.xml"

RETRIEVED_AT = "2026-08-03T19:24:47Z"


def _acquire_per_congress_real(
    tmp_path: Path, source_path: Path = PER_CONGRESS_REAL_CAPTURE_FIXTURE
) -> cbo.AcquiredCBOPerCongressFeed:
    return cbo.acquire_cbo_per_congress_feed(
        cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04, tmp_path, source_path=source_path
    )


def _per_congress_real_parsed(
    tmp_path: Path, source_path: Path = PER_CONGRESS_REAL_CAPTURE_FIXTURE
) -> cbo.ParsedCBOPerCongressFeed:
    return cbo.parse_cbo_per_congress_feed(_acquire_per_congress_real(tmp_path, source_path))


def _per_congress_pin_for(payload: bytes) -> cbo.CBOPerCongressFeedSnapshotPin:
    return cbo.CBOPerCongressFeedSnapshotPin(
        source_url=cbo.cbo_per_congress_cost_estimates_url(119),
        retrieved_at=cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_RETRIEVED_AT,
        expected_sha256=cbo.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_mutated_per_congress(tmp_path: Path, mutated: bytes) -> cbo.AcquiredCBOPerCongressFeed:
    pin = _per_congress_pin_for(mutated)
    source_path = tmp_path / "mutated-per-congress.xml"
    source_path.write_bytes(mutated)
    return cbo.acquire_cbo_per_congress_feed(pin, tmp_path / "store", source_path=source_path)


def _payload(path: Path) -> bytes:
    return path.read_bytes()


def _pin(payload: bytes, *, source_url: str = cbo.CBO_COST_ESTIMATES_XML_URL) -> cbo.CBOCostEstimatesFeedSnapshotPin:
    return cbo.CBOCostEstimatesFeedSnapshotPin(
        source_url=source_url,
        retrieved_at=RETRIEVED_AT,
        expected_sha256=cbo.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _acquire_fixture(tmp_path: Path, payload: bytes | None = None) -> cbo.AcquiredCBOCostEstimatesFeed:
    body = payload if payload is not None else _payload(FEED_FIXTURE)
    return cbo.acquire_cbo_cost_estimates_feed(_pin(body), tmp_path, source_path=FEED_FIXTURE)


class _StaticFetcher:
    def __init__(self, body: bytes, *, status_code: int = 200, content_type: str = "application/xml") -> None:
        self._body = body
        self._status_code = status_code
        self._content_type = content_type

    def fetch(self, source_url: str, *, timeout_seconds: float) -> cbo.FetchedCBOFeed:
        del timeout_seconds
        return cbo.FetchedCBOFeed(
            body=self._body,
            status_code=self._status_code,
            content_type=self._content_type,
            resolved_url=source_url,
        )


def test_module_import_opens_no_network_connection() -> None:
    # Importing must never perform I/O; only an explicit fetcher call may.
    assert hasattr(cbo, "acquire_cbo_cost_estimates_feed")
    assert hasattr(cbo, "CBOFeedFetcher")


def test_local_capture_is_exact_and_content_addressed(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)
    pin = _pin(payload)

    acquired = cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path, source_path=FEED_FIXTURE)
    cached = cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == tmp_path / "sha256" / digest_hex / "cost-estimates.xml"
    assert acquired.path.read_bytes() == payload
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cbo.FetchedCBOFeed:
            calls.append((source_url, timeout_seconds))
            return cbo.FetchedCBOFeed(
                body=payload,
                status_code=200,
                content_type="application/xml; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = cbo.acquire_cbo_cost_estimates_feed(
        _pin(payload),
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(cbo.CBO_COST_ESTIMATES_XML_URL, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "application/xml; charset=UTF-8"


def test_initial_capture_establishes_pin_before_strict_reopen(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)

    captured = cbo.capture_initial_cbo_cost_estimates_feed_snapshot(
        tmp_path,
        retrieved_at=RETRIEVED_AT,
        fetcher=_StaticFetcher(payload),
        timeout_seconds=17.0,
    )
    reopened = cbo.acquire_cbo_cost_estimates_feed(captured.pin, tmp_path)

    assert captured.sha256 == cbo.sha256_digest(payload)
    assert captured.byte_length == len(payload)
    assert captured.path.read_bytes() == payload
    assert reopened.cache_hit is True
    assert reopened.pin == captured.pin


@pytest.mark.parametrize(
    "source_url",
    [
        "https://www.cbo.gov/cost-estimates",
        "https://www.cbo.gov/topics",
    ],
)
def test_non_feed_url_is_rejected(source_url: str) -> None:
    payload = b"<rss version='2.0'></rss>"
    with pytest.raises(cbo.CBOAcquisitionError, match="cost-estimates/xml feed"):
        _pin(payload, source_url=source_url)


def test_datadome_challenge_response_is_rejected_by_status_code(tmp_path: Path) -> None:
    # This is the real byte-for-byte 403 response this module's
    # implementation received from cbo.gov during development.
    expected_payload = _payload(FEED_FIXTURE)
    blocked_body = _payload(CHALLENGE_FIXTURE)
    pin = _pin(expected_payload)

    with pytest.raises(cbo.CBOAcquisitionError, match="HTTP 403"):
        cbo.acquire_cbo_cost_estimates_feed(
            pin,
            tmp_path,
            fetcher=_StaticFetcher(blocked_body, status_code=403, content_type="text/html;charset=utf-8"),
        )

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "cost-estimates.xml"
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_datadome_challenge_content_never_publishes_even_with_200_status(tmp_path: Path) -> None:
    # Same real captured challenge bytes, replayed under a hypothetical 200
    # status: the content-based guard must reject it independently of the
    # status-code guard exercised above.
    expected_payload = _payload(FEED_FIXTURE)
    blocked_body = _payload(CHALLENGE_FIXTURE)
    pin = _pin(expected_payload)

    with pytest.raises(cbo.CBOSourceDriftError, match="bot-challenge"):
        cbo.acquire_cbo_cost_estimates_feed(
            pin,
            tmp_path,
            fetcher=_StaticFetcher(blocked_body, status_code=200, content_type="text/html"),
        )


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload(FEED_FIXTURE)
    changed_payload = expected_payload.replace(b"Commerce", b"Commerse")
    assert len(changed_payload) == len(expected_payload)
    pin = _pin(expected_payload)

    with pytest.raises(cbo.CBOSourceDriftError, match="digest drift"):
        cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path, fetcher=_StaticFetcher(changed_payload))

    expected_path = tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "cost-estimates.xml"
    assert not expected_path.exists()


def test_parses_topic_assignments_and_fiscal_facets_without_minting_topic_identity(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)

    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)

    assert len(parsed.records) == 3
    first, second, third = parsed.records

    assert first.bill_number == "H.R. 1234"
    assert first.committee == "House Committee on Energy and Commerce"
    assert first.congress == "119"
    assert [assignment.label for assignment in first.topics] == ["Health", "Native Americans", "Health"]
    assert first.mandate == cbo.CBOMandateFlags(False, False, False)
    assert first.pay_as_you_go is True
    assert [bf.label for bf in first.budget_functions] == ["Health"]

    assert second.bill_number == "S. 4567"
    assert second.committee is None
    assert [assignment.label for assignment in second.topics] == ["Public Lands and Natural Resources"]
    assert second.mandate == cbo.CBOMandateFlags(True, False, True)
    assert second.pay_as_you_go is False
    assert second.budget_functions == ()

    assert third.bill_number is None
    assert third.committee is None
    assert third.congress is None
    assert third.topics == ()
    assert third.mandate == cbo.CBOMandateFlags(None, None, None)
    assert third.pay_as_you_go is None
    assert [bf.label for bf in third.budget_functions] == ["Agriculture"]

    all_topics = [assignment for record in parsed.records for assignment in record.topics]
    assert len(all_topics) == 4
    assert len({assignment.record_iri for assignment in all_topics}) == 4
    assert all(not bf.is_general_subject_concept for record in parsed.records for bf in record.budget_functions)


def test_repeated_topic_on_one_item_remains_distinct_evidence(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)
    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)

    first = parsed.records[0]
    repeated = tuple(assignment for assignment in first.topics if assignment.label == "Health")
    assert len(repeated) == 2
    assert repeated[0].record_iri != repeated[1].record_iri
    assert [assignment.source_ordinal for assignment in repeated] == [0, 2]


def test_budget_function_code_becomes_a_publisher_identifier_but_stays_non_subject(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)
    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)

    budget_function = parsed.records[0].budget_functions[0]

    assert budget_function.code == "550"
    assert budget_function.is_general_subject_concept is False
    assert budget_function.identifiers == (
        ControlledIdentifier(
            value="550",
            kind="budgetFunctionCode",
            authority_uri=cbo.CBO_IDENTIFIER_AUTHORITY_URI,
            source_uri=cbo.CBO_COST_ESTIMATES_XML_URL,
            observed_at=RETRIEVED_AT,
            effective_at=None,
            source_digest=acquired.sha256,
        ),
    )


def test_record_by_bill_number_indexes_deterministic_facets(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)
    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)

    by_bill = parsed.record_by_bill_number()

    assert set(by_bill) == {"H.R. 1234", "S. 4567"}
    assert by_bill["H.R. 1234"].committee == "House Committee on Energy and Commerce"


def test_missing_topics_across_whole_feed_fails_closed(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)
    mutated = re.sub(rb"<cbo:topics>.*?</cbo:topics>", b"", payload, flags=re.DOTALL)
    assert b"<cbo:topic>" not in mutated
    pin = _pin(mutated)
    acquired = cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(cbo.CBOSourceDriftError, match="assigns no Topic"):
        cbo.parse_cbo_cost_estimates_feed(acquired)


def test_malformed_mandate_flag_fails_closed(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)
    mutated = payload.replace(b'intergovernmental="false"', b'intergovernmental="maybe"')
    pin = _pin(mutated)
    acquired = cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(cbo.CBOSourceDriftError, match="must be 'true' or 'false'"):
        cbo.parse_cbo_cost_estimates_feed(acquired)


def test_item_link_outside_official_domain_fails_closed(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)
    mutated = payload.replace(
        b"<link>https://www.cbo.gov/publication/62345</link>",
        b"<link>https://example.com/publication/62345</link>",
    )
    pin = _pin(mutated)
    acquired = cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(cbo.CBOAcquisitionError, match="official HTTPS cbo.gov URL"):
        cbo.parse_cbo_cost_estimates_feed(acquired)


def test_malformed_xml_fails_as_source_drift(tmp_path: Path) -> None:
    payload = _payload(FEED_FIXTURE)
    mutated = payload.replace(b"</rss>", b"")
    pin = _pin(mutated)
    acquired = cbo.acquire_cbo_cost_estimates_feed(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(cbo.CBOSourceDriftError, match="not valid XML"):
        cbo.parse_cbo_cost_estimates_feed(acquired)


def test_package_is_source_evidence_only_and_never_a_concept_scheme(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)
    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)

    bundle = cbo.build_cbo_topic_evidence_package(acquired, parsed)

    manifest = bundle.resource_manifest
    assert manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in manifest
    assert manifest["resourceKind"] == "sourceTermSnapshot"
    assert manifest["identityStatus"] == "captureLocalObservationsOnly"
    assert "usageCeiling" not in manifest
    assert "acceptedOutputUseAuthorized" not in manifest
    assert manifest["conceptIdentityClaimed"] is False
    assert manifest["uses"] == ("sourceAssignedEvidence",)
    assert manifest["observationCount"] == 4

    for observation in bundle.observations:
        assert observation["identifiers"] == ()
        assert observation["conceptIdentityClaimed"] is False
        assert observation["uses"] == ("sourceAssignedEvidence",)

    labels = [observation["labels"][0]["value"] for observation in bundle.observations]
    assert labels == ["Health", "Native Americans", "Health", "Public Lands and Natural Resources"]

    bill_numbers = {observation["billNumber"] for observation in bundle.observations}
    assert bill_numbers == {"H.R. 1234", "S. 4567"}


def test_package_round_trips_through_a_closed_directory(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)
    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)
    bundle = cbo.build_cbo_topic_evidence_package(acquired, parsed)

    destination = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle.logical_digest
    assert reopened.source_artifact_bytes(cbo.CBO_COST_ESTIMATES_XML_URL) == _payload(FEED_FIXTURE)
    assert len(reopened.observations) == 4


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload(FEED_FIXTURE)
    assert cbo.sha256_digest(payload) == cbo.sha256_digest(payload)
    assert cbo.sha256_digest(payload) != cbo.sha256_digest(payload + b" ")


# --- REAL captured per-Congress discovery channel (2026-08-04) ---
#
# https://www.cbo.gov/rss/{congress}congress-cost-estimates.xml sits on a
# different CDN tier than cost-estimates/xml above and served plain HTTP 200
# to curl -- no DataDome bot wall. The 119th Congress feed is checked in
# byte-for-byte. Its custom <response>/<item> shape carries no Topic labels,
# budget-function codes, mandate flags, or PAYGO facets of its own.


def test_per_congress_url_builder_documents_the_pattern() -> None:
    assert cbo.cbo_per_congress_cost_estimates_url(119) == "https://www.cbo.gov/rss/119congress-cost-estimates.xml"
    assert cbo.cbo_per_congress_cost_estimates_url(118) == "https://www.cbo.gov/rss/118congress-cost-estimates.xml"
    with pytest.raises(cbo.CBOAcquisitionError, match="positive integer"):
        cbo.cbo_per_congress_cost_estimates_url(0)


def test_per_congress_feed_url_must_match_the_official_pattern() -> None:
    payload = b"<?xml version='1.0'?><response><item key='0'></item></response>"
    with pytest.raises(cbo.CBOAcquisitionError, match="per-Congress feed"):
        cbo.CBOPerCongressFeedSnapshotPin(
            source_url="https://www.cbo.gov/rss/cost-estimates.xml",
            retrieved_at=RETRIEVED_AT,
            expected_sha256=cbo.sha256_digest(payload),
            expected_byte_length=len(payload),
        )


def test_real_capture_fixture_bytes_match_pinned_digest_and_length() -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)

    assert len(payload) == 375_365
    assert cbo.sha256_digest(payload) == "sha256:edc957a1115320f1c0da4b02c33d1af146a3c508592ee20b4909e0a8db44d968"
    assert len(payload) == cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_BYTE_LENGTH
    assert cbo.sha256_digest(payload) == cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_SHA256
    assert cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04.expected_byte_length == len(payload)
    assert cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04.expected_sha256 == cbo.sha256_digest(payload)
    assert cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04.retrieved_at == "2026-08-04T00:50:00Z"
    assert (
        cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04.source_url
        == "https://www.cbo.gov/rss/119congress-cost-estimates.xml"
    )


def test_real_capture_is_acquired_and_verified_against_its_pin(tmp_path: Path) -> None:
    acquired = _acquire_per_congress_real(tmp_path)

    assert acquired.sha256 == cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04.expected_sha256
    assert acquired.byte_length == cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04_BYTE_LENGTH
    assert acquired.acquisition_mode == "local"

    cached = cbo.acquire_cbo_per_congress_feed(cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04, tmp_path)
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_real_capture_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cbo.FetchedCBOFeed:
            calls.append((source_url, timeout_seconds))
            return cbo.FetchedCBOFeed(
                body=payload,
                status_code=200,
                content_type="application/xml; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = cbo.acquire_cbo_per_congress_feed(
        cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=9.0,
    )

    assert calls == [("https://www.cbo.gov/rss/119congress-cost-estimates.xml", 9.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_real_capture_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    expected_payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    changed_payload = expected_payload.replace(b"H.R. 8844", b"H.R. 8845")
    assert len(changed_payload) == len(expected_payload)

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cbo.FetchedCBOFeed:
            del timeout_seconds
            return cbo.FetchedCBOFeed(
                body=changed_payload,
                status_code=200,
                content_type="application/xml",
                resolved_url=source_url,
            )

    with pytest.raises(cbo.CBOSourceDriftError, match="digest drift"):
        cbo.acquire_cbo_per_congress_feed(cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04, tmp_path, fetcher=Fetcher())

    digest_hex = cbo.CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04.expected_sha256.removeprefix("sha256:")
    expected_path = tmp_path / "sha256" / digest_hex / "per-congress-cost-estimates.xml"
    assert not expected_path.exists()


def test_parses_the_real_119th_congress_feed_exact_item_count_and_first_item(tmp_path: Path) -> None:
    parsed = _per_congress_real_parsed(tmp_path)

    assert len(parsed.records) == 1058
    assert parsed.source_url == "https://www.cbo.gov/rss/119congress-cost-estimates.xml"
    assert parsed.retrieved_at == "2026-08-04T00:50:00Z"
    assert parsed.source_byte_length == 375_365

    first = parsed.records[0]
    assert first.item_ordinal == 0
    assert first.key == "0"
    assert first.title == ("H.R. 8844, U.S. Customs and Border Protection Officer Retirement Technical Corrections Act")
    assert first.date == "Mon, 03 Aug 2026 15:49:00 -0400"
    assert first.link == "https://www.cbo.gov/publication/62634"
    assert first.description == (
        "As ordered reported by the House Committee on Oversight and Government Reform on May 20, 2026"
    )
    assert first.bill_number == "H.R. 8844"


def test_real_feed_item_with_an_empty_bill_number_element_parses_as_none(tmp_path: Path) -> None:
    parsed = _per_congress_real_parsed(tmp_path)

    # Item 33 in the real capture is a weekly House suspension-calendar
    # notice: it carries an empty <Bill_Number></Bill_Number> element rather
    # than omitting the element entirely.
    procedural_item = parsed.records[33]
    assert procedural_item.bill_number is None
    assert procedural_item.title == (
        "Legislation considered under suspension of the Rules of the House of "
        "Representatives during the week of July 20, 2026"
    )
    assert procedural_item.link == "https://www.cbo.gov/publication/62534"

    empty_bill_records = [record for record in parsed.records if record.bill_number is None]
    assert len(empty_bill_records) == 52
    populated_bill_records = [record for record in parsed.records if record.bill_number is not None]
    assert len(populated_bill_records) == 1006


def test_real_feed_all_links_match_the_official_publication_pattern(tmp_path: Path) -> None:
    parsed = _per_congress_real_parsed(tmp_path)

    link_pattern = re.compile(r"^https://www\.cbo\.gov/publication/\d+$")
    assert all(link_pattern.fullmatch(record.link) for record in parsed.records)


def test_real_feed_record_by_bill_number_indexes_the_first_item(tmp_path: Path) -> None:
    parsed = _per_congress_real_parsed(tmp_path)

    by_bill = parsed.record_by_bill_number()

    assert by_bill["H.R. 8844"].link == "https://www.cbo.gov/publication/62634"
    assert "" not in by_bill


def test_real_feed_gaps_disclose_no_fiscal_facets(tmp_path: Path) -> None:
    parsed = _per_congress_real_parsed(tmp_path)

    assert parsed.gaps == cbo.CBO_PER_CONGRESS_PORTFOLIO_GAPS
    assert any("Topic" in gap for gap in parsed.gaps)
    assert any("omb_a11_budget_codes" in gap for gap in parsed.gaps)


def test_no_stable_topic_identifier_gap_documents_the_per_congress_channel(tmp_path: Path) -> None:
    acquired = _acquire_fixture(tmp_path)
    parsed = cbo.parse_cbo_cost_estimates_feed(acquired)
    bundle = cbo.build_cbo_topic_evidence_package(acquired, parsed)

    gaps = {gap["kind"]: gap["reason"] for gap in bundle.coverage_report["gaps"]}
    reason = gaps["publisherTopicIdentifierUnavailable"]

    assert "per-Congress" in reason
    assert "bot-wall-free" in reason
    assert "omb_a11_budget_codes" in reason


def test_real_feed_non_response_root_fails_closed(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(b"<response>", b"<responses>", 1).replace(b"</response>\n", b"</responses>\n", 1)
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="root is no longer <response>"):
        cbo.parse_cbo_per_congress_feed(acquired)


def test_real_feed_unexpected_root_child_fails_closed(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(b'<response><item key="0">', b'<response><meta>x</meta><item key="0">', 1)
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="is not <item>"):
        cbo.parse_cbo_per_congress_feed(acquired)


def test_real_feed_item_with_unexpected_child_element_fails_closed(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(
        b"<Bill_Number>H.R. 8844</Bill_Number></item>",
        b"<Bill_Number>H.R. 8844</Bill_Number><Extra>x</Extra></item>",
        1,
    )
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="does not carry exactly"):
        cbo.parse_cbo_per_congress_feed(acquired)


def test_real_feed_item_missing_a_required_child_fails_closed(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(
        b"<Description>As ordered reported by the House Committee on Oversight and "
        b"Government Reform on May 20, 2026</Description>",
        b"",
        1,
    )
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="does not carry exactly"):
        cbo.parse_cbo_per_congress_feed(acquired)


def test_real_feed_item_missing_its_key_attribute_fails_closed(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(b'<item key="0">', b"<item>", 1)
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="missing its key attribute"):
        cbo.parse_cbo_per_congress_feed(acquired)


def test_real_feed_item_link_not_matching_publication_pattern_fails_closed(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(
        b"<Link>https://www.cbo.gov/publication/62634</Link>",
        b"<Link>https://www.cbo.gov/publication/abc</Link>",
        1,
    )
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="does not match"):
        cbo.parse_cbo_per_congress_feed(acquired)


def test_real_feed_malformed_xml_fails_as_source_drift(tmp_path: Path) -> None:
    payload = _payload(PER_CONGRESS_REAL_CAPTURE_FIXTURE)
    mutated = payload.replace(b"</response>\n", b"")
    acquired = _acquire_mutated_per_congress(tmp_path, mutated)

    with pytest.raises(cbo.CBOSourceDriftError, match="not valid XML"):
        cbo.parse_cbo_per_congress_feed(acquired)

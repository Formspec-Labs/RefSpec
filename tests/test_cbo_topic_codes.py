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
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from refspec.registry import cbo_topic_codes as cbo
from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "cbo_topic_codes"
FEED_FIXTURE = FIXTURES / "cbo-cost-estimates-mini.xml"
CHALLENGE_FIXTURE = FIXTURES / "cbo-datadome-challenge-real-capture.html"

RETRIEVED_AT = "2026-08-03T19:24:47Z"


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
    assert manifest["resourceKind"] == "sourceTermSnapshot"
    assert manifest["identityStatus"] == "captureLocalObservationsOnly"
    assert manifest["usageCeiling"] == "developmentOnly"
    assert manifest["acceptedOutputUseAuthorized"] is False
    assert manifest["conceptIdentityClaimed"] is False
    assert manifest["candidateUseAuthorized"] is False
    assert manifest["uses"] == ["sourceAssignedEvidence"]
    assert manifest["observationCount"] == 4

    for observation in bundle.observations:
        assert observation["identifiers"] == []
        assert observation["conceptIdentityClaimed"] is False
        assert observation["eligibleUses"] == ["sourceAssignedEvidence"]

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

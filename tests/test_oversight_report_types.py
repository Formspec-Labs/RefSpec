"""Oversight.gov federal Report Type facet capture, parsing, and packaging tests.

oversight.gov publishes no JSON constants endpoint or subject/topic taxonomy
for federal reports. This module -- and these tests -- only ever capture and
parse the Report Type <select> filter embedded in the /reports/federal
listing page, matching the catalog decision that this source supplies
deterministic report-genre metadata (audit, inspection/evaluation,
investigation, review, peer review, semiannual, and other) and never a topic
vocabulary.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import oversight_report_types as oversight
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "oversight_report_types"
REPORTS_FEDERAL_FIXTURE = FIXTURES / "oversight-reports-federal-2026-08-03.html"

# The exact (value, label) pairs the live Report Type <select> published on
# 2026-08-03, in document order.
EXPECTED_OPTIONS = (
    ("3", "Audit"),
    ("4", "CIGIE Annual Report"),
    ("980", "Disaster Recovery Report"),
    ("984", "Inspection / Evaluation"),
    ("985", "Investigation"),
    ("975", "Other"),
    ("5", "Peer Review of OIG"),
    ("986", "Review"),
    ("6", "Semiannual Report"),
    ("987", "Top Management Challenges"),
)


def _payload() -> bytes:
    return REPORTS_FEDERAL_FIXTURE.read_bytes()


def _acquire(tmp_path: Path) -> oversight.AcquiredOversightReportTypesPage:
    return oversight.acquire_oversight_report_types_page(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        tmp_path,
        source_path=REPORTS_FEDERAL_FIXTURE,
    )


def _parsed(tmp_path: Path) -> oversight.ParsedOversightReportTypesPage:
    return oversight.parse_oversight_report_types_page(_acquire(tmp_path))


class _StaticFetcher:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def fetch(self, source_url: str, *, timeout_seconds: float) -> oversight.FetchedOversightPage:
        del timeout_seconds
        return oversight.FetchedOversightPage(
            body=self._body,
            status_code=200,
            content_type="text/html; charset=utf-8",
            resolved_url=source_url,
        )


def test_module_import_opens_no_network_connection() -> None:
    # Importing must never perform I/O; only an explicit fetcher call may.
    assert hasattr(oversight, "acquire_oversight_report_types_page")
    assert hasattr(oversight, "OversightPageFetcher")


def test_pinned_fixture_matches_the_module_snapshot_pin_exactly() -> None:
    payload = _payload()

    assert len(payload) == oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_byte_length
    assert oversight.sha256_digest(payload) == oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_sha256


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(tmp_path: Path) -> None:
    pin = oversight.OVERSIGHT_REPORT_TYPES_2026_08_03

    acquired = _acquire(tmp_path)
    cached = oversight.acquire_oversight_report_types_page(pin, tmp_path)

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    assert acquired.path == (tmp_path / "sha256" / digest_hex / "oversight-reports-federal.html")
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = _payload()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> oversight.FetchedOversightPage:
            calls.append((source_url, timeout_seconds))
            return oversight.FetchedOversightPage(
                body=payload,
                status_code=200,
                content_type="text/html; charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = oversight.acquire_oversight_report_types_page(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(oversight.OVERSIGHT_REPORT_TYPES_URL, 17.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.content_type == "text/html; charset=UTF-8"


def test_report_types_are_captured_as_deterministic_genre_metadata_with_publisher_ids(
    tmp_path: Path,
) -> None:
    parsed = _parsed(tmp_path)

    assert len(parsed.options) == 10
    assert [(option.identifiers[0].value, option.label) for option in parsed.options] == list(EXPECTED_OPTIONS)

    by_value = parsed.by_publisher_value()
    audit = by_value["3"]
    assert audit.label == "Audit"
    assert audit.identifiers == (
        ControlledIdentifier(
            value="3",
            kind="oversightReportTypeId",
            authority_uri=oversight.OVERSIGHT_IDENTIFIER_AUTHORITY_URI,
            source_uri=oversight.OVERSIGHT_REPORT_TYPES_URL,
            observed_at=oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.retrieved_at,
            effective_at=None,
            source_digest=oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_sha256,
        ),
    )
    inspection = by_value["984"]
    assert inspection.label == "Inspection / Evaluation"

    assert {gap["kind"] for gap in parsed.gaps} == {
        "publisherTopicTaxonomyUnavailable",
        "volatileWholePagePin",
    }


def test_select_shape_drift_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(
        b'data-drupal-selector="edit-field-report-type"',
        b'data-drupal-selector="edit-field-report-type-renamed"',
    )
    assert mutated != payload
    pin = replace(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        expected_sha256=oversight.sha256_digest(mutated),
        expected_byte_length=len(mutated),
    )
    acquired = oversight.acquire_oversight_report_types_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(oversight.OversightSourceDriftError, match="exactly one Report Type filter select"):
        oversight.parse_oversight_report_types_page(acquired)


def test_missing_multiple_attribute_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(
        b'multiple="multiple" name="field_report_type[]"',
        b'name="field_report_type[]"',
    )
    assert mutated != payload
    pin = replace(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        expected_sha256=oversight.sha256_digest(mutated),
        expected_byte_length=len(mutated),
    )
    acquired = oversight.acquire_oversight_report_types_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(oversight.OversightSourceDriftError, match="no longer a multiple-select control"):
        oversight.parse_oversight_report_types_page(acquired)


def test_duplicate_publisher_values_fail_closed(tmp_path: Path) -> None:
    payload = _payload()
    mutated = payload.replace(b'value="4">CIGIE Annual Report', b'value="3">CIGIE Annual Report')
    assert len(mutated) == len(payload)
    pin = replace(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        expected_sha256=oversight.sha256_digest(mutated),
    )
    acquired = oversight.acquire_oversight_report_types_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(oversight.OversightSourceDriftError, match="duplicate publisher values"):
        oversight.parse_oversight_report_types_page(acquired)


def test_no_options_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    start_marker = b'id="edit-field-report-type--2" class="form-select usa-select">'
    end_marker = b"</select>"
    start = payload.index(start_marker) + len(start_marker)
    end = payload.index(end_marker, start)
    mutated = payload[:start] + payload[end:]
    assert mutated != payload
    pin = replace(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        expected_sha256=oversight.sha256_digest(mutated),
        expected_byte_length=len(mutated),
    )
    acquired = oversight.acquire_oversight_report_types_page(pin, tmp_path, fetcher=_StaticFetcher(mutated))

    with pytest.raises(oversight.OversightSourceDriftError, match="published no options"):
        oversight.parse_oversight_report_types_page(acquired)


def test_digest_drift_never_publishes_source(tmp_path: Path) -> None:
    payload = _payload()
    changed = payload.replace(b">Audit<", b">Audlt<")
    assert len(changed) == len(payload)
    pin = oversight.OVERSIGHT_REPORT_TYPES_2026_08_03

    with pytest.raises(oversight.OversightSourceDriftError, match="digest drift"):
        oversight.acquire_oversight_report_types_page(pin, tmp_path, fetcher=_StaticFetcher(changed))

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    expected_path = tmp_path / "sha256" / digest_hex / "oversight-reports-federal.html"
    assert not expected_path.exists()
    assert not list(tmp_path.rglob(".acquire-*.tmp"))


def test_access_denied_or_challenge_response_never_publishes_source(tmp_path: Path) -> None:
    blocked_body = b"<!doctype html><html><head><title>Just a moment...</title></head><body></body></html>"
    pin = replace(
        oversight.OVERSIGHT_REPORT_TYPES_2026_08_03,
        expected_sha256=oversight.sha256_digest(blocked_body),
        expected_byte_length=len(blocked_body),
    )

    with pytest.raises(oversight.OversightSourceDriftError, match="access-denied or challenge"):
        oversight.acquire_oversight_report_types_page(pin, tmp_path, fetcher=_StaticFetcher(blocked_body))


def test_off_host_source_url_is_rejected() -> None:
    with pytest.raises(oversight.OversightAcquisitionError, match="official HTTPS oversight.gov URL"):
        oversight.OversightReportTypesSnapshotPin(
            source_url="https://example.com/reports/federal",
            retrieved_at="2026-08-03T19:25:24Z",
            expected_sha256=oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_sha256,
            expected_byte_length=oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_byte_length,
        )


def test_wrong_official_path_is_rejected() -> None:
    with pytest.raises(oversight.OversightAcquisitionError, match="official federal reports listing page"):
        oversight.OversightReportTypesSnapshotPin(
            source_url="https://www.oversight.gov/reports/state",
            retrieved_at="2026-08-03T19:25:24Z",
            expected_sha256=oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_sha256,
            expected_byte_length=oversight.OVERSIGHT_REPORT_TYPES_2026_08_03.expected_byte_length,
        )


def test_package_is_a_controlled_code_list_not_a_concept_scheme(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    parsed = oversight.parse_oversight_report_types_page(acquired)

    bundle = oversight.build_oversight_report_types_package(acquired, parsed)

    manifest = bundle.resource_manifest
    assert manifest["resourceKind"] == "controlledCodeList"
    assert manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert manifest["usageCeiling"] == "developmentOnly"
    assert manifest["acceptedOutputUseAuthorized"] is False
    assert manifest["conceptIdentityClaimed"] is False
    assert manifest["candidateUseAuthorized"] is True
    assert manifest["uses"] == ["deterministicMetadata"]
    assert manifest["observationCount"] == 10

    for observation in bundle.observations:
        assert observation["conceptIdentityClaimed"] is False
        assert observation["eligibleUses"] == ["deterministicMetadata"]
        assert len(observation["identifiers"]) == 1
        assert observation["identifiers"][0]["kind"] == "oversightReportTypeId"

    labels = [observation["labels"][0]["value"] for observation in bundle.observations]
    assert labels == [label for _value, label in EXPECTED_OPTIONS]


def test_package_gaps_document_missing_topic_taxonomy_and_volatile_page(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    parsed = oversight.parse_oversight_report_types_page(acquired)
    bundle = oversight.build_oversight_report_types_package(acquired, parsed)

    reasons = [gap["reason"] for gap in bundle.coverage_report["gaps"]]
    assert any("no subject/topic taxonomy" in reason for reason in reasons)
    assert any("not a stable, independently re-fetchable release" in reason for reason in reasons)


def test_package_round_trips_through_a_closed_directory(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    parsed = oversight.parse_oversight_report_types_page(acquired)
    bundle = oversight.build_oversight_report_types_package(acquired, parsed)

    destination = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle.logical_digest
    assert reopened.source_artifact_bytes(oversight.OVERSIGHT_REPORT_TYPES_URL) == _payload()
    assert len(reopened.observations) == 10
    assert reopened.observations[3]["labels"][0]["value"] == "Inspection / Evaluation"
    assert reopened.observations[3]["identifiers"][0]["value"] == "984"


def test_fixture_digest_is_derived_from_exact_bytes() -> None:
    payload = _payload()
    assert oversight.sha256_digest(payload) == oversight.sha256_digest(payload)
    assert oversight.sha256_digest(payload) != oversight.sha256_digest(payload + b" ")

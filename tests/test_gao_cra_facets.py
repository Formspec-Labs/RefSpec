"""GAO Congressional Review Act database facet capture, parsing, and packaging tests.

The live gao.gov CRA database page returned an Akamai access-denied response
(HTTP 403) when this module was first implemented (2026-08-03); that exact
real response body is retained as a fixture (``ACCESS_DENIED_FIXTURE``) and
used below only as historical negative evidence that the acquisition path
fails closed on a block page. Because that first attempt failed, the
original parsing fixture (``FACETS_FIXTURE``) is a hand-built HTML capture
faithful to a *hypothesized* Drupal exposed-filter ``<select>``/``<option>``
shape, not a verified live capture -- its strict parser and byte pin below
exist so a real future capture that drifts from that hypothesized shape
fails loudly instead of silently.

A REAL page has since been captured through the project's Zyte transport
(2026-08-04) and checked in as ``REAL_CAPTURE_FIXTURE``. It is confirmed to
be the live CRA database page, not a denial page -- and it falsifies the
hypothesis above: the real page renders zero ``<select>`` and zero
``<option>`` elements. The three facets are visible only as the
currently-echoed query parameters inside the page's drupal-settings JSON.
The tests below for ``parse_gao_cra_real_page_echoed_query`` exercise that
real shape directly, including its explicit refusal to enumerate any
facet's legal value list (that list is client-rendered and requires a
rendered-DOM capture this module does not perform).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.registry import gao_cra_facets as cra
from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "gao_cra_facets"
FACETS_FIXTURE = FIXTURES / "gao-cra-database-facets-2026-08-03.html"
ACCESS_DENIED_FIXTURE = FIXTURES / "gao-cra-access-denied-real-capture-2026-08-03.html"
REAL_CAPTURE_FIXTURE = FIXTURES / "gao-cra-database-real-capture-2026-08-04.html"


def _acquire(tmp_path: Path, source_path: Path = FACETS_FIXTURE) -> cra.AcquiredGAOCRAFacetPage:
    return cra.acquire_gao_cra_facets_page(cra.GAO_CRA_FACETS_2026_08_03, tmp_path, source_path=source_path)


def _parsed(tmp_path: Path, source_path: Path = FACETS_FIXTURE) -> cra.ParsedGAOCRAFacets:
    return cra.parse_gao_cra_facets(_acquire(tmp_path, source_path))


def _pin_for(payload: bytes) -> cra.GAOCRAFacetSnapshotPin:
    return cra.GAOCRAFacetSnapshotPin(
        source_url=cra.GAO_CRA_DATABASE_URL,
        retrieved_at="2026-08-03T00:00:00Z",
        expected_sha256=cra.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def _package(tmp_path: Path) -> object:
    acquired = _acquire(tmp_path)
    parsed = cra.parse_gao_cra_facets(acquired)
    return cra.build_gao_cra_facets_package(acquired, parsed)


def _acquire_real(tmp_path: Path, source_path: Path = REAL_CAPTURE_FIXTURE) -> cra.AcquiredGAOCRAFacetPage:
    return cra.acquire_gao_cra_facets_page(cra.GAO_CRA_REAL_CAPTURE_2026_08_04, tmp_path, source_path=source_path)


def _real_parsed(tmp_path: Path, source_path: Path = REAL_CAPTURE_FIXTURE) -> cra.ParsedGAOCRAEchoedFacetQuery:
    return cra.parse_gao_cra_real_page_echoed_query(_acquire_real(tmp_path, source_path))


def _real_pin_for(payload: bytes) -> cra.GAOCRAFacetSnapshotPin:
    return cra.GAOCRAFacetSnapshotPin(
        source_url=cra.GAO_CRA_DATABASE_URL,
        retrieved_at="2026-08-04T00:12:00Z",
        expected_sha256=cra.sha256_digest(payload),
        expected_byte_length=len(payload),
    )


def test_fixture_bytes_match_pinned_digest_and_length() -> None:
    payload = FACETS_FIXTURE.read_bytes()

    assert len(payload) == cra.GAO_CRA_FACETS_2026_08_03_BYTE_LENGTH
    assert cra.sha256_digest(payload) == cra.GAO_CRA_FACETS_2026_08_03_SHA256


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path)
    cached = cra.acquire_gao_cra_facets_page(cra.GAO_CRA_FACETS_2026_08_03, tmp_path)

    digest_hex = cra.GAO_CRA_FACETS_2026_08_03.expected_sha256.removeprefix("sha256:")
    assert acquired.path == (tmp_path / "sha256" / digest_hex / "congressional-review-act.html")
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == cra.GAO_CRA_FACETS_2026_08_03.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cra.FetchedGAOCRAPage:
            calls.append((source_url, timeout_seconds))
            return cra.FetchedGAOCRAPage(
                body=payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    acquired = cra.acquire_gao_cra_facets_page(
        cra.GAO_CRA_FACETS_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=11.0,
    )

    assert calls == [(cra.GAO_CRA_DATABASE_URL, 11.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_fetcher_http_error_status_is_rejected(tmp_path: Path) -> None:
    blocked_payload = ACCESS_DENIED_FIXTURE.read_bytes()

    class BlockedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cra.FetchedGAOCRAPage:
            del timeout_seconds
            return cra.FetchedGAOCRAPage(
                body=blocked_payload,
                status_code=403,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(cra.GAOCRAAcquisitionError, match="HTTP 403"):
        cra.acquire_gao_cra_facets_page(cra.GAO_CRA_FACETS_2026_08_03, tmp_path, fetcher=BlockedFetcher())


def test_fetcher_access_denied_body_with_200_status_fails_closed(tmp_path: Path) -> None:
    blocked_payload = ACCESS_DENIED_FIXTURE.read_bytes()

    class SneakyFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> cra.FetchedGAOCRAPage:
            del timeout_seconds
            return cra.FetchedGAOCRAPage(
                body=blocked_payload,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(cra.GAOCRASourceDriftError, match="access-denied|challenge"):
        cra.acquire_gao_cra_facets_page(cra.GAO_CRA_FACETS_2026_08_03, tmp_path, fetcher=SneakyFetcher())


def test_parses_three_facets_with_labels_defaults_and_identifiers(
    tmp_path: Path,
) -> None:
    parsed = _parsed(tmp_path)

    assert set(parsed.facets) == {"priority", "processed", "type"}
    assert [code.publisher_label for code in parsed.facets["priority"]] == [
        "- Any -",
        "Major",
        "Non-major",
    ]
    assert [code.publisher_label for code in parsed.facets["processed"]] == ["Yes", "No"]
    assert [code.publisher_label for code in parsed.facets["type"]] == [
        "- Any -",
        "Rule",
        "Report on Major Rule",
        "Legal Decision",
        "Disapproved by Joint Resolution",
    ]

    major = parsed.by_value("priority")["major"]
    assert major.publisher_label == "Major"
    assert major.use == "deterministicMetadata"
    assert major.is_default is False
    assert major.is_general_subject_concept is False
    assert major.identifiers == (
        ControlledIdentifier(
            value="major",
            kind="craPriorityFacetValue",
            authority_uri=cra.GAO_CRA_IDENTIFIER_AUTHORITY_URI,
            source_uri=cra.GAO_CRA_DATABASE_URL,
            observed_at=cra.GAO_CRA_FACETS_2026_08_03_RETRIEVED_AT,
            effective_at=None,
            source_digest=cra.GAO_CRA_FACETS_2026_08_03_SHA256,
        ),
    )
    assert parsed.by_value("priority")["all"].is_default is True
    assert parsed.by_value("type")["disapproved"].publisher_label == ("Disapproved by Joint Resolution")


def test_all_facet_codes_are_deterministic_metadata_never_subject_concepts(
    tmp_path: Path,
) -> None:
    parsed = _parsed(tmp_path)
    all_codes = [code for codes in parsed.facets.values() for code in codes]

    assert len(all_codes) == 10
    assert all(code.use == "deterministicMetadata" for code in all_codes)
    assert all(code.is_general_subject_concept is False for code in all_codes)


def test_parsed_facets_record_scope_and_source_gaps(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)

    assert any("stable bulk API" in gap for gap in parsed.gaps)
    assert any("review-window" in gap or "review window" in gap for gap in parsed.gaps)
    assert any("release date" in gap or "revision" in gap for gap in parsed.gaps)


def test_digest_or_byte_length_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes()
    changed = payload.replace(b"Major", b"Majot")
    assert len(changed) == len(payload)
    source_path = tmp_path / "changed.html"
    source_path.write_bytes(changed)

    with pytest.raises(cra.GAOCRASourceDriftError, match="digest drift"):
        cra.acquire_gao_cra_facets_page(
            cra.GAO_CRA_FACETS_2026_08_03,
            tmp_path / "store",
            source_path=source_path,
        )


def test_renamed_facet_fails_closed(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes().replace(b'name="priority"', b'name="priorityx"')
    pin = _pin_for(payload)
    source_path = tmp_path / "renamed.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="priority"):
        cra.parse_gao_cra_facets(acquired)


def test_duplicate_facet_select_fails_closed(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes()
    start = payload.index(b"<form")
    end = payload.index(b"</form>") + len(b"</form>")
    form_block = payload[start:end]
    duplicated = payload[:end] + form_block + payload[end:]
    pin = _pin_for(duplicated)
    source_path = tmp_path / "duplicated.html"
    source_path.write_bytes(duplicated)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="more than once"):
        cra.parse_gao_cra_facets(acquired)


def test_option_without_a_value_fails_closed(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes().replace(
        b'<option value="major">Major</option>',
        b"<option>Major</option>",
        1,
    )
    pin = _pin_for(payload)
    source_path = tmp_path / "novalue.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="without a value"):
        cra.parse_gao_cra_facets(acquired)


def test_empty_option_label_fails_closed(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes().replace(
        b'<option value="major">Major</option>',
        b'<option value="major"></option>',
        1,
    )
    pin = _pin_for(payload)
    source_path = tmp_path / "emptylabel.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="label"):
        cra.parse_gao_cra_facets(acquired)


def test_missing_facet_fails_closed(tmp_path: Path) -> None:
    payload = FACETS_FIXTURE.read_bytes()
    start = payload.index(b'<div class="js-form-item js-form-type-select js-form-item-type')
    end = payload.index(b"</div>", start) + len(b"</div>")
    without_type = payload[:start] + payload[end:]
    pin = _pin_for(without_type)
    source_path = tmp_path / "missing.html"
    source_path.write_bytes(without_type)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="type"):
        cra.parse_gao_cra_facets(acquired)


def test_validate_rule_submission_facets_accepts_known_codes_and_passthrough_dates(
    tmp_path: Path,
) -> None:
    parsed = _parsed(tmp_path)
    record = {
        "priority": "major",
        "processed": "1",
        "type": "rule",
        "receivedDate": "2026-01-15",
        "effectiveDate": "2026-03-16",
    }

    validated = cra.validate_cra_rule_submission_facets(record, parsed)

    assert validated.priority.publisher_label == "Major"
    assert validated.processed.publisher_label == "Yes"
    assert validated.rule_type.publisher_label == "Rule"
    assert validated.received_date == "2026-01-15"
    assert validated.effective_date == "2026-03-16"
    assert all(
        assignment.use == "deterministicMetadata"
        for assignment in (validated.priority, validated.processed, validated.rule_type)
    )
    assert all(
        assignment.is_general_subject_concept is False
        for assignment in (validated.priority, validated.processed, validated.rule_type)
    )


def test_validate_rule_submission_facets_allows_omitted_optional_dates(
    tmp_path: Path,
) -> None:
    parsed = _parsed(tmp_path)

    validated = cra.validate_cra_rule_submission_facets(
        {"priority": "non-major", "processed": "0", "type": "report"},
        parsed,
    )

    assert validated.received_date is None
    assert validated.effective_date is None
    assert validated.rule_type.publisher_label == "Report on Major Rule"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("priority", "super-major"),
        ("processed", "maybe"),
        ("type", "invented"),
    ],
)
def test_unknown_facet_code_fails_closed(tmp_path: Path, field: str, value: str) -> None:
    parsed = _parsed(tmp_path)
    record = {"priority": "major", "processed": "1", "type": "rule", field: value}

    with pytest.raises(cra.GAOCRAAssignmentError, match="unknown"):
        cra.validate_cra_rule_submission_facets(record, parsed)


def test_missing_required_facet_fails_closed(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)

    with pytest.raises(cra.GAOCRAAssignmentError, match="priority"):
        cra.validate_cra_rule_submission_facets({"processed": "1", "type": "rule"}, parsed)


def test_unsupported_field_fails_closed(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)

    with pytest.raises(cra.GAOCRAAssignmentError, match="unsupported"):
        cra.validate_cra_rule_submission_facets(
            {
                "priority": "major",
                "processed": "1",
                "type": "rule",
                "reportNumber": "B-123456",
            },
            parsed,
        )


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "reviewWindowEndDate",
        "calculatedDeadline",
        "legislativeDayCount",
        "projectReviewWindow",
    ],
)
def test_project_calculated_review_window_field_is_refused(
    tmp_path: Path,
    forbidden_field: str,
) -> None:
    parsed = _parsed(tmp_path)
    record = {
        "priority": "major",
        "processed": "1",
        "type": "rule",
        forbidden_field: "2026-04-01",
    }

    with pytest.raises(cra.GAOCRAScopeError, match="review window"):
        cra.validate_cra_rule_submission_facets(record, parsed)


def test_build_package_produces_a_controlled_code_list_never_a_concept_scheme(
    tmp_path: Path,
) -> None:
    bundle = _package(tmp_path)

    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["usageCeiling"] == "developmentOnly"
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["candidateUseAuthorized"] is False
    assert bundle.resource_manifest["uses"] == ["deterministicMetadata"]
    assert bundle.resource_manifest["observationCount"] == 10
    assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
    assert all(observation["eligibleUses"] == ["deterministicMetadata"] for observation in bundle.observations)


def test_package_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first = _package(tmp_path)
    second = _package(tmp_path)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest


def test_package_round_trips_through_write_to_and_open(tmp_path: Path) -> None:
    bundle = _package(tmp_path)
    package_path = bundle.write_to(tmp_path / "package")

    reopened = SourceControlledResourceView.open(package_path)

    assert reopened.logical_digest == bundle.logical_digest
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.source_artifact_bytes(cra.GAO_CRA_DATABASE_URL) == FACETS_FIXTURE.read_bytes()
    assert len(reopened.observations) == 10


def test_package_records_stable_bulk_api_and_unverified_capture_gaps(
    tmp_path: Path,
) -> None:
    bundle = _package(tmp_path)

    assert bundle.coverage_report["reportStatus"] == "gap"
    gap_kinds = {gap["kind"] for gap in bundle.coverage_report["gaps"]}
    assert "noStableBulkApi" in gap_kinds
    assert "liveCaptureUnverified" in gap_kinds


def test_package_records_facet_value_enumeration_gap(tmp_path: Path) -> None:
    """The constructed-fixture package now discloses it cannot claim real facet values."""

    bundle = _package(tmp_path)

    gap_kinds = {gap["kind"] for gap in bundle.coverage_report["gaps"]}
    assert "facetValueEnumerationRequiresRenderedDom" in gap_kinds


def test_parsed_facets_gaps_disclose_real_capture_and_rendered_dom_follow_up(
    tmp_path: Path,
) -> None:
    """The constructed-fixture parser's gaps honestly reframe it as an unconfirmed hypothesis."""

    parsed = _parsed(tmp_path)

    assert any("GAO_CRA_REAL_CAPTURE_2026_08_04" in gap for gap in parsed.gaps)
    assert any("rendered-DOM" in gap for gap in parsed.gaps)


# --- REAL captured page (2026-08-04, via the project's Zyte transport) ---
#
# This page contains ZERO <select> and ZERO <option> elements: the
# constructed-fixture parser's markup guess above is not what gao.gov
# actually serves. The three facets appear only as the echoed currentQuery
# inside the page's drupal-settings JSON.


def test_real_capture_fixture_bytes_match_pinned_digest_and_length() -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes()

    assert len(payload) == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH
    assert cra.sha256_digest(payload) == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256


def test_real_capture_renders_zero_select_and_option_elements() -> None:
    """Verifies the reality that falsifies the constructed fixture's markup hypothesis."""

    text = REAL_CAPTURE_FIXTURE.read_text(encoding="utf-8")

    assert text.lower().count("<select") == 0
    assert text.lower().count("<option") == 0


def test_real_capture_is_acquired_and_verified_against_its_pin(tmp_path: Path) -> None:
    acquired = _acquire_real(tmp_path)

    assert acquired.sha256 == cra.GAO_CRA_REAL_CAPTURE_2026_08_04.expected_sha256
    assert acquired.byte_length == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH


def test_parses_echoed_current_query_from_real_capture(tmp_path: Path) -> None:
    parsed = _real_parsed(tmp_path)

    assert dict(parsed.echoed_query) == {"priority": "all", "processed": "1", "type": "all"}
    assert set(parsed.echoed_query) == {"priority", "processed", "type"}
    assert parsed.source_url == cra.GAO_CRA_DATABASE_URL
    assert parsed.retrieved_at == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_RETRIEVED_AT
    assert parsed.source_sha256 == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256
    assert parsed.source_byte_length == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH


def test_real_page_echoed_query_gaps_record_rendered_dom_follow_up_not_unverified_capture(
    tmp_path: Path,
) -> None:
    parsed = _real_parsed(tmp_path)

    assert any("rendered-DOM" in gap for gap in parsed.gaps)
    assert not any("Akamai" in gap for gap in parsed.gaps)


@pytest.mark.parametrize("facet_name", ["priority", "processed", "type"])
def test_real_page_refuses_to_enumerate_facet_values(tmp_path: Path, facet_name: str) -> None:
    parsed = _real_parsed(tmp_path)

    with pytest.raises(cra.GAOCRAFacetEnumerationUnavailableError, match="rendered-DOM"):
        parsed.available_facet_values(facet_name)  # type: ignore[arg-type]


def test_real_page_available_facet_values_rejects_unknown_facet(tmp_path: Path) -> None:
    parsed = _real_parsed(tmp_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="unknown"):
        parsed.available_facet_values("bogus")  # type: ignore[arg-type]


def test_real_page_missing_title_identity_anchor_fails_closed(tmp_path: Path) -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes().replace(
        b"<title>Congressional Review Act | U.S. GAO</title>",
        b"<title>Some Unrelated GAO Page</title>",
    )
    pin = _real_pin_for(payload)
    source_path = tmp_path / "no-title.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="title"):
        cra.parse_gao_cra_real_page_echoed_query(acquired)


def test_real_page_missing_heading_identity_anchor_fails_closed(tmp_path: Path) -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes().replace(
        b'<h1 class="split-headings">\n                          Congressional Review Act\n                      </h1>',
        b'<h1 class="split-headings">Some Other Heading</h1>',
    )
    pin = _real_pin_for(payload)
    source_path = tmp_path / "no-heading.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="heading"):
        cra.parse_gao_cra_real_page_echoed_query(acquired)


def test_real_page_missing_drupal_settings_script_fails_closed(tmp_path: Path) -> None:
    text = REAL_CAPTURE_FIXTURE.read_bytes().decode("utf-8")
    start = text.index('<script type="application/json" data-drupal-selector="drupal-settings-json">')
    end = text.index("</script>", start) + len("</script>")
    mutated = (text[:start] + text[end:]).encode("utf-8")

    pin = _real_pin_for(mutated)
    source_path = tmp_path / "no-settings.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="drupal-settings"):
        cra.parse_gao_cra_real_page_echoed_query(acquired)


def test_real_page_missing_current_query_fails_closed(tmp_path: Path) -> None:
    text = REAL_CAPTURE_FIXTURE.read_bytes().decode("utf-8")
    tag = '<script type="application/json" data-drupal-selector="drupal-settings-json">'
    start = text.index(tag) + len(tag)
    end = text.index("</script>", start)
    settings = json.loads(text[start:end])
    del settings["path"]["currentQuery"]
    mutated = (text[:start] + json.dumps(settings) + text[end:]).encode("utf-8")

    pin = _real_pin_for(mutated)
    source_path = tmp_path / "no-current-query.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="currentQuery"):
        cra.parse_gao_cra_real_page_echoed_query(acquired)


def test_real_page_missing_one_echoed_facet_fails_closed(tmp_path: Path) -> None:
    text = REAL_CAPTURE_FIXTURE.read_bytes().decode("utf-8")
    tag = '<script type="application/json" data-drupal-selector="drupal-settings-json">'
    start = text.index(tag) + len(tag)
    end = text.index("</script>", start)
    settings = json.loads(text[start:end])
    del settings["path"]["currentQuery"]["priority"]
    mutated = (text[:start] + json.dumps(settings) + text[end:]).encode("utf-8")

    pin = _real_pin_for(mutated)
    source_path = tmp_path / "missing-priority.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="priority"):
        cra.parse_gao_cra_real_page_echoed_query(acquired)

"""GAO Congressional Review Act database facet capture and package tests.

``REAL_CAPTURE_FIXTURE`` is the actual server-rendered Search Database of
Rules page captured through Zyte. It publishes six radio values across the
``priority`` and ``type`` facets. ``FACETS_FIXTURE`` is the older hand-built
select hypothesis; tests retain its parser behavior as historical evidence,
but package generation must reject it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.registry import gao_cra_facets as cra
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "gao_cra_facets"
FACETS_FIXTURE = FIXTURES / "gao-cra-database-facets-2026-08-03.html"
ACCESS_DENIED_FIXTURE = FIXTURES / "gao-cra-access-denied-real-capture-2026-08-03.html"
REAL_CAPTURE_FIXTURE = FIXTURES / "gao-cra-database-real-capture-2026-08-04.html"
BLANK_FORM_FIXTURE = FIXTURES / "gao-cra-blank-form-2023-11-2026-08-04.pdf"
FEDRULES_167777_FIXTURE = FIXTURES / "gao-fedrules-167777-2026-08-04.html"


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
    acquired = _acquire_real(tmp_path)
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


def _acquire_fedrules(
    tmp_path: Path, source_path: Path = FEDRULES_167777_FIXTURE
) -> cra.AcquiredGAOFedRulesPage:
    return cra.acquire_gao_fedrules_page(cra.GAO_FEDRULES_167777, tmp_path, source_path=source_path)


def _fedrules_parsed(
    tmp_path: Path, source_path: Path = FEDRULES_167777_FIXTURE
) -> cra.ParsedGAOFedRulesPage:
    return cra.parse_gao_fedrules_page(_acquire_fedrules(tmp_path, source_path))


def _fedrules_pin_for(payload: bytes, *, control_number: str = "167777") -> cra.GAOFedRulesPageSnapshotPin:
    return cra.GAOFedRulesPageSnapshotPin(
        source_url=f"https://www.gao.gov/fedrules/{control_number}",
        control_number=control_number,
        retrieved_at=cra.GAO_FEDRULES_167777_RETRIEVED_AT,
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

    assert calls == [(cra.GAO_CRA_OVERVIEW_URL, 11.0)]
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
                source_uri=cra.GAO_CRA_OVERVIEW_URL,
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
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))
    record = {
        "priority": "Significant/Substantive",
        "type": "Major",
        "receivedDate": "2026-01-15",
        "effectiveDate": "2026-03-16",
    }

    validated = cra.validate_cra_rule_submission_facets(record, parsed)

    assert validated.priority.publisher_label == "Significant/Substantive"
    assert validated.rule_type.publisher_label == "Major"
    assert validated.received_date == "2026-01-15"
    assert validated.effective_date == "2026-03-16"
    assert all(
        assignment.use == "deterministicMetadata"
        for assignment in (validated.priority, validated.rule_type)
    )
    assert all(
        assignment.is_general_subject_concept is False
        for assignment in (validated.priority, validated.rule_type)
    )


def test_validate_rule_submission_facets_allows_omitted_optional_dates(
    tmp_path: Path,
) -> None:
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))

    validated = cra.validate_cra_rule_submission_facets(
        {"priority": "Routine/Info/Other", "type": "Non-Major"},
        parsed,
    )

    assert validated.received_date is None
    assert validated.effective_date is None
    assert validated.rule_type.publisher_label == "Non-Major"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("priority", "super-major"),
        ("type", "invented"),
    ],
)
def test_unknown_facet_code_fails_closed(tmp_path: Path, field: str, value: str) -> None:
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))
    record = {"priority": "Significant/Substantive", "type": "Major", field: value}

    with pytest.raises(cra.GAOCRAAssignmentError, match="unknown"):
        cra.validate_cra_rule_submission_facets(record, parsed)


def test_missing_required_facet_fails_closed(tmp_path: Path) -> None:
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))

    with pytest.raises(cra.GAOCRAAssignmentError, match="priority"):
        cra.validate_cra_rule_submission_facets({"type": "Major"}, parsed)


def test_unsupported_field_fails_closed(tmp_path: Path) -> None:
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))

    with pytest.raises(cra.GAOCRAAssignmentError, match="unsupported"):
        cra.validate_cra_rule_submission_facets(
            {
                "priority": "Significant/Substantive",
                "type": "Major",
                "reportNumber": "B-123456",
            },
            parsed,
        )


def test_internal_processed_query_parameter_is_not_a_public_facet(tmp_path: Path) -> None:
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))

    with pytest.raises(cra.GAOCRAAssignmentError, match="processed"):
        cra.validate_cra_rule_submission_facets(
            {"priority": "Significant/Substantive", "type": "Major", "processed": "1"},
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
    parsed = cra.parse_gao_cra_facets(_acquire_real(tmp_path))
    record = {
        "priority": "Significant/Substantive",
        "type": "Major",
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
    assert bundle.resource_manifest["observationCount"] == 6
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
    assert reopened.source_artifact_bytes(cra.GAO_CRA_DATABASE_URL) == REAL_CAPTURE_FIXTURE.read_bytes()
    assert len(reopened.observations) == 6


def test_package_records_stable_bulk_api_gap_but_not_unverified_capture(
    tmp_path: Path,
) -> None:
    bundle = _package(tmp_path)

    assert bundle.coverage_report["reportStatus"] == "gap"
    gap_kinds = {gap["kind"] for gap in bundle.coverage_report["gaps"]}
    assert "noStableBulkApi" in gap_kinds
    assert "liveCaptureUnverified" not in gap_kinds


def test_package_records_facet_value_enumeration_gap(tmp_path: Path) -> None:
    """The real server-rendered form closes the former enumeration gap."""

    bundle = _package(tmp_path)

    gap_kinds = {gap["kind"] for gap in bundle.coverage_report["gaps"]}
    assert "facetValueEnumerationRequiresRenderedDom" not in gap_kinds


def test_legacy_parsed_facets_disclose_real_search_page_replacement(
    tmp_path: Path,
) -> None:
    """The constructed-fixture parser's gaps honestly reframe it as an unconfirmed hypothesis."""

    parsed = _parsed(tmp_path)

    assert any("GAO_CRA_REAL_CAPTURE_2026_08_04" in gap for gap in parsed.gaps)
    assert any("Search Database of Rules" in gap for gap in parsed.gaps)


# --- REAL captured page (2026-08-04, via the project's Zyte transport) ---
#
# This is the actual Search Database of Rules page. It uses server-rendered
# radio groups for the public ``priority`` and ``type`` facets. The
# ``processed=1`` query value is echoed internally but is not a public facet.


def test_real_capture_fixture_bytes_match_pinned_digest_and_length() -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes()

    assert len(payload) == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH
    assert cra.sha256_digest(payload) == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256


def test_real_capture_renders_zero_select_and_option_elements() -> None:
    """The current publisher form uses radio inputs, not the old hypothesized selects."""

    text = REAL_CAPTURE_FIXTURE.read_text(encoding="utf-8")

    assert text.lower().count("<select") == 0
    assert text.lower().count("<option") == 0
    assert text.count('name="priority"') == 3
    assert text.count('name="type"') == 3


def test_real_search_page_enumerates_exact_publisher_facet_values(tmp_path: Path) -> None:
    """The package input must be GAO's real search form, not a constructed select fixture."""

    payload = REAL_CAPTURE_FIXTURE.read_bytes()
    pin = _real_pin_for(payload)
    source_path = tmp_path / "real-search.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    parsed = cra.parse_gao_cra_facets(acquired)

    assert {
        facet: [(code.identifiers[0].value, code.publisher_label) for code in codes]
        for facet, codes in parsed.facets.items()
    } == {
        "priority": [
            ("all", "All"),
            ("Significant/Substantive", "Significant/Substantive"),
            ("Routine/Info/Other", "Other"),
        ],
        "type": [
            ("all", "All"),
            ("Major", "Major"),
            ("Non-Major", "Non-Major"),
        ],
    }


def test_real_search_page_missing_public_facet_fails_closed(tmp_path: Path) -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes().replace(b'name="priority"', b'name="priorityx"')
    pin = _real_pin_for(payload)
    source_path = tmp_path / "missing-priority.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="priority"):
        cra.parse_gao_cra_facets(acquired)


def test_real_search_page_radio_without_matching_label_fails_closed(tmp_path: Path) -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes().replace(
        b'<label for="edit-priority-all"',
        b'<label for="edit-priority-unknown"',
        1,
    )
    pin = _real_pin_for(payload)
    source_path = tmp_path / "missing-label.html"
    source_path.write_bytes(payload)
    acquired = cra.acquire_gao_cra_facets_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="no matching label"):
        cra.parse_gao_cra_facets(acquired)


def test_constructed_legacy_fixture_cannot_be_packaged(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    parsed = cra.parse_gao_cra_facets(acquired)

    with pytest.raises(cra.GAOCRASourceDriftError, match="verified GAO Search Database"):
        cra.build_gao_cra_facets_package(acquired, parsed)


def test_real_capture_is_acquired_and_verified_against_its_pin(tmp_path: Path) -> None:
    acquired = _acquire_real(tmp_path)

    assert acquired.sha256 == cra.GAO_CRA_REAL_CAPTURE_2026_08_04.expected_sha256
    assert acquired.byte_length == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH


def test_parses_echoed_current_query_from_real_capture(tmp_path: Path) -> None:
    parsed = _real_parsed(tmp_path)

    assert dict(parsed.echoed_query) == {"priority": "all", "type": "all"}
    assert set(parsed.echoed_query) == {"priority", "type"}
    assert parsed.source_url == cra.GAO_CRA_DATABASE_URL
    assert parsed.retrieved_at == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_RETRIEVED_AT
    assert parsed.source_sha256 == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256
    assert parsed.source_byte_length == cra.GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH


def test_real_page_echoed_query_has_no_rendered_dom_or_unverified_capture_gap(
    tmp_path: Path,
) -> None:
    parsed = _real_parsed(tmp_path)

    assert not any("rendered-DOM" in gap for gap in parsed.gaps)
    assert not any("Akamai" in gap for gap in parsed.gaps)


def test_real_page_missing_title_identity_anchor_fails_closed(tmp_path: Path) -> None:
    payload = REAL_CAPTURE_FIXTURE.read_bytes().replace(
        b"<title>Search Database of Rules | U.S. GAO</title>",
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
        b'<h1 class="split-headings">\n                          Search Database of Rules\n                      </h1>',
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


# --- Artifact A: GAO's blank CRA submission form (2023-11 edition) ---
#
# Reference-only provenance: this PDF is never fetched through the
# acquisition pipeline and never parsed at runtime, the same way
# treasury_tas_fast_book.py pins its Component TAS-BETC flyer. It is the
# publisher-stated authority for CRA_RULE_TYPES and CRA_PRIORITY_LEVELS.


def test_blank_form_fixture_bytes_match_pinned_digest_and_length() -> None:
    payload = BLANK_FORM_FIXTURE.read_bytes()

    assert len(payload) == cra.GAO_CRA_BLANK_FORM_2023_11_BYTE_LENGTH
    assert cra.sha256_digest(payload) == cra.GAO_CRA_BLANK_FORM_2023_11_SHA256


def test_cra_rule_types_and_priority_levels_are_the_blank_forms_exact_wording() -> None:
    assert cra.CRA_RULE_TYPES == ("Major Rule", "Non-major Rule")
    assert cra.CRA_PRIORITY_LEVELS == (
        "Economically Significant",
        "Significant",
        "Substantive, Nonsignificant",
        "Routine and Frequent",
        "Informational/Administrative/Other",
    )


# --- Artifact B: a real fedrules per-rule detail page (control number 167777) ---
#
# Unlike the CRA database search page, gao.gov/fedrules/{control_number}
# pages are server-rendered: the rule type, priority, and control number are
# present directly in Drupal field markup.

_TYPE_FIELD_BLOCK = (
    '<div class="field field--name-field-type field--type-string field--label-above">\n'
    '    <h2 class="field__label">Type</h2>\n'
    '              <div class="field__item">Non-Major</div>\n'
    "          </div>"
)
_PRIORITY_FIELD_BLOCK = (
    '<div class="field field--name-field-priority field--type-entity-reference field--label-above">\n'
    '    <h2 class="field__label">Priority</h2>\n'
    '              <div class="field__item">Routine/Info/Other</div>\n'
    "          </div>"
)
_CONTROL_NUMBER_FIELD_BLOCK = (
    '<div class="field field--name-field-control-number field--type-integer field--label-above">\n'
    '    <h2 class="field__label">Control Number</h2>\n'
    '              <div class="field__item">167777</div>\n'
    "          </div>"
)


def test_fedrules_fixture_bytes_match_pinned_digest_and_length() -> None:
    payload = FEDRULES_167777_FIXTURE.read_bytes()

    assert len(payload) == cra.GAO_FEDRULES_167777_BYTE_LENGTH
    assert cra.sha256_digest(payload) == cra.GAO_FEDRULES_167777_SHA256


def test_fedrules_fixture_field_blocks_match_the_real_markup() -> None:
    """Guards the mutation tests below: fail loudly if the fixture's markup ever changes shape."""

    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")

    assert text.count(_TYPE_FIELD_BLOCK) == 1
    assert text.count(_PRIORITY_FIELD_BLOCK) == 1
    assert text.count(_CONTROL_NUMBER_FIELD_BLOCK) == 1


def test_fedrules_page_is_acquired_and_verified_against_its_pin(tmp_path: Path) -> None:
    acquired = _acquire_fedrules(tmp_path)

    assert acquired.sha256 == cra.GAO_FEDRULES_167777.expected_sha256
    assert acquired.byte_length == cra.GAO_FEDRULES_167777_BYTE_LENGTH
    assert acquired.acquisition_mode == "local"


def test_parses_fedrules_rule_type_priority_and_control_number(tmp_path: Path) -> None:
    parsed = _fedrules_parsed(tmp_path)

    assert parsed.control_number == "167777"
    assert parsed.rule_type == "Non-Major"
    assert parsed.priority == "Routine/Info/Other"
    assert parsed.source_url == cra.GAO_FEDRULES_167777_URL
    assert parsed.retrieved_at == cra.GAO_FEDRULES_167777_RETRIEVED_AT
    assert parsed.source_sha256 == cra.GAO_FEDRULES_167777_SHA256
    assert parsed.source_byte_length == cra.GAO_FEDRULES_167777_BYTE_LENGTH


def test_fedrules_gaps_disclose_priority_vocabulary_reconciliation_and_no_bulk_listing(
    tmp_path: Path,
) -> None:
    parsed = _fedrules_parsed(tmp_path)

    assert any("Routine/Info/Other" in gap for gap in parsed.gaps)
    assert any("CRA_PRIORITY_LEVELS" in gap for gap in parsed.gaps)
    assert any("bulk" in gap.lower() for gap in parsed.gaps)


def test_fedrules_missing_type_field_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated = text.replace(_TYPE_FIELD_BLOCK, "").encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "no-type.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="field--name-field-type"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_missing_priority_field_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated = text.replace(_PRIORITY_FIELD_BLOCK, "").encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "no-priority.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="field--name-field-priority"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_missing_control_number_field_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated = text.replace(_CONTROL_NUMBER_FIELD_BLOCK, "").encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "no-control-number.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="field--name-field-control-number"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_title_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated = text.replace(
        "<title>Federal Rules: MAJOR SYSTEM ACQUISITION; EARNED VALUE MANAGEMENT | U.S. GAO</title>",
        "<title>Some Unrelated GAO Page</title>",
    ).encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "no-title.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="title"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_canonical_link_mismatch_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated = text.replace(
        '<link rel="canonical" href="https://www.gao.gov/fedrules/167777" />',
        '<link rel="canonical" href="https://www.gao.gov/fedrules/999999" />',
    ).encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "wrong-canonical.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="canonical"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_missing_article_anchor_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated = text.replace(
        '<article class="node node--type-federal-rules node--view-mode-full">',
        '<article class="node node--type-other-page node--view-mode-full">',
    ).encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "no-article.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="article anchor"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_control_number_body_url_mismatch_fails_closed(tmp_path: Path) -> None:
    """The control-number field's own text must agree with its page's pinned URL."""

    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated_block = _CONTROL_NUMBER_FIELD_BLOCK.replace("167777", "999999")
    mutated = text.replace(_CONTROL_NUMBER_FIELD_BLOCK, mutated_block).encode("utf-8")

    # source_url/control_number stay at 167777 (matching the untouched canonical
    # link and title); only the control-number field's own body text changes.
    pin = _fedrules_pin_for(mutated, control_number="167777")
    source_path = tmp_path / "mismatched-control-number.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRASourceDriftError, match="does not match its pinned source_url"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_unknown_rule_type_value_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated_block = _TYPE_FIELD_BLOCK.replace("Non-Major", "Ultra-Major")
    mutated = text.replace(_TYPE_FIELD_BLOCK, mutated_block).encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "unknown-type.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRAVocabularyDriftError, match="rule-type vocabulary"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_unknown_priority_value_fails_closed(tmp_path: Path) -> None:
    text = FEDRULES_167777_FIXTURE.read_text(encoding="utf-8")
    mutated_block = _PRIORITY_FIELD_BLOCK.replace("Routine/Info/Other", "Ultra Rare Priority")
    mutated = text.replace(_PRIORITY_FIELD_BLOCK, mutated_block).encode("utf-8")

    pin = _fedrules_pin_for(mutated)
    source_path = tmp_path / "unknown-priority.html"
    source_path.write_bytes(mutated)
    acquired = cra.acquire_gao_fedrules_page(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(cra.GAOCRAVocabularyDriftError, match="priority vocabulary"):
        cra.parse_gao_fedrules_page(acquired)


def test_fedrules_vocabulary_drift_error_is_a_source_drift_error(tmp_path: Path) -> None:
    """GAOCRAVocabularyDriftError is a distinct, catchable subclass, not a bare GAOCRASourceDriftError."""

    assert issubclass(cra.GAOCRAVocabularyDriftError, cra.GAOCRASourceDriftError)

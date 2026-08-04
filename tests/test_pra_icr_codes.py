"""Official PRA ICR search controlled-value capture, parsing, and packaging tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import pra_icr_codes as pra
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "pra_icr_codes"
SEARCH_PAGE_FIXTURE = FIXTURES / "pra-search-2026-08-03.html"


def _acquire(tmp_path: Path, source_path: Path = SEARCH_PAGE_FIXTURE) -> pra.AcquiredPRASource:
    return pra.acquire_pra_search_page(pra.PRA_SEARCH_PAGE_2026_08_03, tmp_path, source_path=source_path)


def _resource(tmp_path: Path) -> pra.ParsedPRAResource:
    return pra.parse_pra_icr_controls(_acquire(tmp_path))


def test_live_snapshot_pin_matches_exact_official_html_bytes() -> None:
    payload = SEARCH_PAGE_FIXTURE.read_bytes()

    assert len(payload) == 174_551
    assert pra.sha256_digest(payload) == ("sha256:7f1e24bbe278c67171a71c9e85d50bf7c886646ae25c835194bda5a6e9d4fa4e")
    assert pra.PRA_SEARCH_PAGE_2026_08_03.expected_byte_length == len(payload)
    assert pra.PRA_SEARCH_PAGE_2026_08_03.expected_sha256 == pra.sha256_digest(payload)


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(tmp_path: Path) -> None:
    pin = pra.PRA_SEARCH_PAGE_2026_08_03

    acquired = _acquire(tmp_path)
    cached = pra.acquire_pra_search_page(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = SEARCH_PAGE_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> pra.FetchedPRAResponse:
            calls.append((source_url, timeout_seconds))
            return pra.FetchedPRAResponse(
                body=payload,
                status_code=200,
                content_type="text/html;charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = pra.acquire_pra_search_page(
        pra.PRA_SEARCH_PAGE_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(pra.PRA_SEARCH_PAGE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_request_types_are_deterministic_not_subject_concepts(tmp_path: Path) -> None:
    resource = _resource(tmp_path)

    assert len(resource.request_types) == 10
    codes = resource.by_request_type_code()
    assert codes["RN"].publisher_label == "New collection (Request for a new OMB Control Number)"
    assert codes["EX"].publisher_label == "Extension without change of a currently approved collection"
    assert all(code.resource_name == "requestTypes" for code in resource.request_types)
    assert all(not code.is_general_subject_concept for code in resource.request_types)
    assert codes["RN"].identifiers == (
        ControlledIdentifier(
            value="RN",
            kind="requestTypeCode",
            authority_uri=pra.PRA_IDENTIFIER_AUTHORITY_URI,
            source_uri=pra.PRA_SEARCH_URL,
            observed_at=resource.retrieved_at,
            effective_at=None,
            source_digest=resource.source_sha256,
        ),
    )


def test_icr_statuses_are_deterministic_not_subject_concepts(tmp_path: Path) -> None:
    resource = _resource(tmp_path)

    assert len(resource.icr_statuses) == 5
    codes = resource.by_icr_status_code()
    assert codes["AC"].publisher_label == "Active"
    assert codes["HA"].publisher_label == "Historical Active"
    assert all(code.resource_name == "icrStatuses" for code in resource.icr_statuses)
    assert all(not code.is_general_subject_concept for code in resource.icr_statuses)


def test_burden_measures_and_omb_control_number_shape_are_captured(tmp_path: Path) -> None:
    resource = _resource(tmp_path)

    assert len(resource.burden_measures) == 5
    labels = {code.publisher_label for code in resource.burden_measures}
    assert labels == {
        "Hours:",
        "Dollars:",
        "Responses:",
        "Respondents:",
        "Respondents-Small Entities:",
    }
    hours = next(code for code in resource.burden_measures if code.publisher_label == "Hours:")
    assert [identifier.kind for identifier in hours.identifiers] == [
        "burdenMeasureLowFieldId",
        "burdenMeasureHighFieldId",
    ]
    assert [identifier.value for identifier in hours.identifiers] == ["lowHour", "highHour"]

    shape = resource.omb_control_number_shape
    assert shape.resource_name == "ombControlNumberShape"
    assert pra.OMB_CONTROL_NUMBER_PATTERN.fullmatch("0938-1236") is not None
    assert pra.OMB_CONTROL_NUMBER_PATTERN.fullmatch("093-1236") is None
    assert any(
        identifier.kind == "ombControlNumberFieldId" and identifier.value == "ombControlNumber"
        for identifier in shape.identifiers
    )
    assert any(
        identifier.kind == "ombControlNumberMaxLength" and identifier.value == "9" for identifier in shape.identifiers
    )


def test_gaps_record_out_of_scope_controls_and_missing_release_id(tmp_path: Path) -> None:
    resource = _resource(tmp_path)

    assert any("Conclusion Action" in gap for gap in resource.gaps)
    assert any("JavaScript" in gap for gap in resource.gaps)
    assert any("no standalone code-list release" in gap for gap in resource.gaps)
    assert any("No separate Paperwork Reduction Act subject thesaurus" in gap for gap in resource.gaps)


def test_icr_record_validates_known_codes_without_becoming_subjects(tmp_path: Path) -> None:
    resource = _resource(tmp_path)
    record = {
        "omb_control_number": "0938-1236",
        "request_type": "RN",
        "request_type_display": "New collection (Request for a new OMB Control Number)",
        "icr_status": "AC",
        "icr_status_display": "Active",
    }

    validated = pra.validate_icr_record(record, resource)

    assert validated.omb_control_number == "0938-1236"
    assert validated.request_type is not None
    assert validated.request_type.publisher_label == "New collection (Request for a new OMB Control Number)"
    assert validated.request_type.is_general_subject_concept is False
    assert validated.icr_status is not None
    assert validated.icr_status.publisher_label == "Active"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("omb_control_number", "12345678", "malformed OMB Control Number"),
        ("omb_control_number", "ABCD-1234", "malformed OMB Control Number"),
        ("request_type", "ZZ", "unknown PRA request_type"),
        ("icr_status", "ZZ", "unknown PRA icr_status"),
    ],
)
def test_unknown_or_malformed_icr_control_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    resource = _resource(tmp_path)

    with pytest.raises(pra.PRAAssignmentError, match=message):
        pra.validate_icr_record({field: value}, resource)


def test_display_mismatch_fails_closed(tmp_path: Path) -> None:
    resource = _resource(tmp_path)

    with pytest.raises(pra.PRAAssignmentError, match="display mismatch"):
        pra.validate_icr_record(
            {"request_type": "RN", "request_type_display": "Something Else"},
            resource,
        )


def test_digest_or_shape_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = SEARCH_PAGE_FIXTURE.read_bytes()
    changed = payload.replace(b">Active<", b">ActivE<")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> pra.FetchedPRAResponse:
            del timeout_seconds
            return pra.FetchedPRAResponse(
                body=changed,
                status_code=200,
                content_type="text/html;charset=UTF-8",
                resolved_url=source_url,
            )

    with pytest.raises(pra.PRASourceDriftError, match="digest drift"):
        pra.acquire_pra_search_page(
            pra.PRA_SEARCH_PAGE_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    shrunk = payload.replace(b'<option value="PA">PreApproved</option>', b"")
    shrunk_pin = replace(
        pra.PRA_SEARCH_PAGE_2026_08_03,
        expected_sha256=pra.sha256_digest(shrunk),
        expected_byte_length=len(shrunk),
    )
    shrunk_path = tmp_path / "shrunk.html"
    shrunk_path.write_bytes(shrunk)
    acquired = pra.acquire_pra_search_page(shrunk_pin, tmp_path / "shrunk-store", source_path=shrunk_path)
    with pytest.raises(pra.PRASourceDriftError, match="icrStatuses count drift"):
        pra.parse_pra_icr_controls(acquired)


def test_build_pra_icr_controlled_value_package_produces_a_closed_deterministic_bundle(
    tmp_path: Path,
) -> None:
    bundle = pra.build_pra_icr_controlled_value_package(SEARCH_PAGE_FIXTURE)

    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["uses"] == ("deterministicMetadata",)
    assert "acceptedOutputUseAuthorized" not in bundle.resource_manifest
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["observationCount"] == 21
    assert len(bundle.observations) == 21
    assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
    assert all(observation["uses"] == ("deterministicMetadata",) for observation in bundle.observations)

    destination = tmp_path / "package"
    bundle.write_to(destination)
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 21

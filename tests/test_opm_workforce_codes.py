"""OPM workforce and PLUM controlled-code capture, parsing, and validation tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import opm_workforce_codes as opm
from refspec.registry.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "opm_workforce_codes"
PAY_PLAN_FIXTURE = FIXTURES / "opm-pay-plan-codes.json"
WORK_SCHEDULE_FIXTURE = FIXTURES / "opm-work-schedule-codes.json"
APPOINTMENT_TYPE_FIXTURE = FIXTURES / "opm-appointment-type-codes.json"
OCCUPATIONAL_SERIES_FIXTURE = FIXTURES / "opm-occupational-series-codes.json"
PLUM_FIXTURE = FIXTURES / "opm-plum-position-status-codes.json"


def _acquire(
    tmp_path: Path,
    pin: opm.OPMSnapshotPin,
    source_path: Path,
) -> opm.AcquiredOPMSource:
    return opm.acquire_opm_constants(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> opm.OPMControlPortfolio:
    resources = [
        opm.parse_opm_constants(_acquire(tmp_path, opm.OPM_PAY_PLAN_CODES_2026_08_03, PAY_PLAN_FIXTURE)),
        opm.parse_opm_constants(_acquire(tmp_path, opm.OPM_WORK_SCHEDULE_CODES_2026_08_03, WORK_SCHEDULE_FIXTURE)),
        opm.parse_opm_constants(
            _acquire(tmp_path, opm.OPM_APPOINTMENT_TYPE_CODES_2026_08_03, APPOINTMENT_TYPE_FIXTURE)
        ),
        opm.parse_opm_constants(
            _acquire(tmp_path, opm.OPM_OCCUPATIONAL_SERIES_CODES_2026_08_03, OCCUPATIONAL_SERIES_FIXTURE)
        ),
        opm.parse_opm_constants(_acquire(tmp_path, opm.OPM_PLUM_POSITION_STATUS_CODES_2026_08_03, PLUM_FIXTURE)),
    ]
    return opm.assemble_opm_control_portfolio(resources)


def test_pinned_fixture_bytes_match_exact_digests() -> None:
    pairs = (
        (PAY_PLAN_FIXTURE, opm.OPM_PAY_PLAN_CODES_2026_08_03),
        (WORK_SCHEDULE_FIXTURE, opm.OPM_WORK_SCHEDULE_CODES_2026_08_03),
        (APPOINTMENT_TYPE_FIXTURE, opm.OPM_APPOINTMENT_TYPE_CODES_2026_08_03),
        (OCCUPATIONAL_SERIES_FIXTURE, opm.OPM_OCCUPATIONAL_SERIES_CODES_2026_08_03),
        (PLUM_FIXTURE, opm.OPM_PLUM_POSITION_STATUS_CODES_2026_08_03),
    )
    for fixture, pin in pairs:
        payload = fixture.read_bytes()
        assert len(payload) == pin.expected_byte_length
        assert opm.sha256_digest(payload) == pin.expected_sha256


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = opm.OPM_PAY_PLAN_CODES_2026_08_03

    acquired = _acquire(tmp_path, pin, PAY_PLAN_FIXTURE)
    cached = opm.acquire_opm_constants(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = WORK_SCHEDULE_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> opm.FetchedOPMResponse:
            calls.append((source_url, timeout_seconds))
            return opm.FetchedOPMResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    acquired = opm.acquire_opm_constants(
        opm.OPM_WORK_SCHEDULE_CODES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(opm.OPM_WORK_SCHEDULE_CODES.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_fetcher_off_official_host_is_refused(tmp_path: Path) -> None:
    payload = WORK_SCHEDULE_FIXTURE.read_bytes()

    class RogueFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> opm.FetchedOPMResponse:
            del timeout_seconds
            return opm.FetchedOPMResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url="https://evil.example/opm-work-schedule-codes.json",
            )

    with pytest.raises(opm.OPMAcquisitionError, match="official HTTPS opm.gov host"):
        opm.acquire_opm_constants(
            opm.OPM_WORK_SCHEDULE_CODES_2026_08_03,
            tmp_path,
            fetcher=RogueFetcher(),
        )


def test_pay_plan_codes_are_deterministic_entity_metadata_not_subjects(
    tmp_path: Path,
) -> None:
    resource = opm.parse_opm_constants(_acquire(tmp_path, opm.OPM_PAY_PLAN_CODES_2026_08_03, PAY_PLAN_FIXTURE))

    assert len(resource.codes) == 6
    assert resource.release_vintage is None
    assert resource.requires_certification is False
    assert resource.by_code()["GS"] == opm.OPMCode(
        resource_name="payPlanCodes",
        category="payPlan",
        use="deterministicMetadata",
        publisher_label="General Schedule",
        source_url=opm.OPM_PAY_PLAN_CODES.source_url,
        identifiers=(
            ControlledIdentifier(
                value="GS",
                kind="opmPayPlanCode",
                authority_uri=opm.OPM_IDENTIFIER_AUTHORITY_URI,
                source_uri=opm.OPM_PAY_PLAN_CODES.source_url,
                observed_at="2026-08-03T00:00:00Z",
                effective_at=None,
                source_digest=opm.OPM_PAY_PLAN_CODES_2026_08_03.expected_sha256,
            ),
        ),
        is_general_subject_concept=False,
    )
    assert all(not code.is_general_subject_concept for code in resource.codes)
    assert all(code.use == "deterministicMetadata" for code in resource.codes)


def test_occupational_series_codes_validate_shape_only(tmp_path: Path) -> None:
    resource = opm.parse_opm_constants(
        _acquire(tmp_path, opm.OPM_OCCUPATIONAL_SERIES_CODES_2026_08_03, OCCUPATIONAL_SERIES_FIXTURE)
    )

    assert len(resource.codes) == 6
    assert resource.by_code()["2210"].publisher_label == "Information Technology Management"
    assert resource.source.is_closed_enumeration is False
    assert any("not exhaustive" in gap for gap in resource.gaps)


def test_plum_resource_carries_certification_and_vintage_pin(tmp_path: Path) -> None:
    resource = opm.parse_opm_constants(_acquire(tmp_path, opm.OPM_PLUM_POSITION_STATUS_CODES_2026_08_03, PLUM_FIXTURE))

    assert len(resource.codes) == 7
    assert resource.requires_certification is True
    assert resource.release_vintage == "2025"
    assert resource.by_code()["PAS"].publisher_label == ("Presidential Appointment with Senate Confirmation")
    assert resource.by_code()["VACANT"].category == "plumIncumbentStatusMarker"
    assert resource.by_code()["REDACTED"].category == "plumIncumbentStatusMarker"


def test_portfolio_requires_all_five_resources_and_keeps_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("not a stable per-resource" not in gap for gap in portfolio.gaps)
    assert any("not exhaustive" in gap for gap in portfolio.gaps)
    assert any("certification" in gap for gap in portfolio.gaps)

    incomplete = [portfolio.pay_plan_codes, portfolio.work_schedule_codes]
    with pytest.raises(opm.OPMSourceDriftError, match="exactly the five"):
        opm.assemble_opm_control_portfolio(incomplete)


def test_workforce_observation_validates_known_and_unsampled_codes(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    validated = opm.validate_workforce_observation_codes(
        {
            "pay_plan": "GS",
            "work_schedule": "F",
            "appointment_type": "10",
            "occupational_series": "2210",
        },
        portfolio,
    )
    assert validated.pay_plan.publisher_label == "General Schedule"
    assert validated.pay_plan.in_pinned_sample is True
    assert validated.occupational_series.publisher_label == ("Information Technology Management")
    assert validated.appointment_type is not None
    assert validated.appointment_type.in_pinned_sample is True

    # 0854 is shape-valid (four digits) but outside the small pinned sample.
    # It must be accepted, not rejected, because the series list is not
    # exhaustive.
    unsampled = opm.validate_workforce_observation_codes(
        {
            "pay_plan": "GS",
            "work_schedule": "F",
            "occupational_series": "0854",
        },
        portfolio,
    )
    assert unsampled.occupational_series.in_pinned_sample is False
    assert unsampled.occupational_series.publisher_label is None
    assert unsampled.occupational_series.identifiers[0].value == "0854"
    assert unsampled.appointment_type is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pay_plan", "General Schedule"),
        ("work_schedule", "FT"),
        ("occupational_series", "221"),
        ("occupational_series", "22100"),
    ],
)
def test_malformed_workforce_code_shape_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    portfolio = _portfolio(tmp_path)
    observation = {
        "pay_plan": "GS",
        "work_schedule": "F",
        "occupational_series": "2210",
        field: value,
    }

    with pytest.raises(opm.OPMAssignmentError, match="does not match the"):
        opm.validate_workforce_observation_codes(observation, portfolio)


def test_plum_record_requires_certification_and_matching_vintage(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    base = {
        "appointment_authority": "PAS",
        "incumbent_status": "named",
        "release_certified": True,
        "release_vintage": "2025",
    }

    validated = opm.validate_plum_position_codes(base, portfolio)
    assert validated.appointment_authority.publisher_label == ("Presidential Appointment with Senate Confirmation")
    assert validated.incumbent_status == "named"
    assert validated.incumbent_status_marker is None
    assert validated.redaction_reason is None
    assert validated.release_vintage == "2025"

    with pytest.raises(opm.OPMAssignmentError, match="release_certified"):
        opm.validate_plum_position_codes({**base, "release_certified": False}, portfolio)

    with pytest.raises(opm.OPMAssignmentError, match="release_vintage"):
        opm.validate_plum_position_codes({**base, "release_vintage": "2021"}, portfolio)


def test_plum_vacant_and_redacted_incumbent_status_preserve_redaction_rule(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    base = {
        "appointment_authority": "SC",
        "release_certified": True,
        "release_vintage": "2025",
    }

    vacant = opm.validate_plum_position_codes({**base, "incumbent_status": "vacant"}, portfolio)
    assert vacant.incumbent_status_marker is not None
    assert vacant.incumbent_status_marker.code == "VACANT"
    assert vacant.redaction_reason is None

    with pytest.raises(opm.OPMAssignmentError, match="redaction_reason"):
        opm.validate_plum_position_codes({**base, "incumbent_status": "redacted"}, portfolio)

    redacted = opm.validate_plum_position_codes(
        {
            **base,
            "incumbent_status": "redacted",
            "redaction_reason": "law enforcement sensitive position",
        },
        portfolio,
    )
    assert redacted.incumbent_status_marker is not None
    assert redacted.incumbent_status_marker.code == "REDACTED"
    assert redacted.redaction_reason == "law enforcement sensitive position"


def test_digest_or_unknown_shape_drift_never_becomes_a_parsed_resource(
    tmp_path: Path,
) -> None:
    payload = PAY_PLAN_FIXTURE.read_bytes()
    changed = payload.replace(b'"General Schedule"', b'"General Schedulr"')
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> opm.FetchedOPMResponse:
            del timeout_seconds
            return opm.FetchedOPMResponse(
                body=changed,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    with pytest.raises(opm.OPMSourceDriftError, match="digest drift"):
        opm.acquire_opm_constants(
            opm.OPM_PAY_PLAN_CODES_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = b'[{"code":"GS","label":"General Schedule","category":"payPlan","extra":"x"}]'
    mini_source = replace(opm.OPM_PAY_PLAN_CODES, expected_count=1)
    mini_pin = opm.OPMSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T00:00:00Z",
        expected_sha256=opm.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.json"
    mini_path.write_bytes(mini_payload)
    acquired = opm.acquire_opm_constants(
        mini_pin,
        tmp_path / "shape",
        source_path=mini_path,
    )
    with pytest.raises(opm.OPMSourceDriftError, match="fields drifted"):
        opm.parse_opm_constants(acquired)


def test_a_larger_real_capture_fails_the_pin_instead_of_silently_replacing_the_sample(
    tmp_path: Path,
) -> None:
    # Simulates what happens if a real, exhaustive OPM capture (many more
    # rows) is dropped in later: the byte-length pin catches it immediately,
    # rather than the parser silently accepting a differently sized list.
    bigger_payload = PAY_PLAN_FIXTURE.read_bytes().replace(
        b"]", b',{"code":"IR","label":"Insurance Rate","category":"payPlan"}]'
    )
    bigger_path = tmp_path / "bigger.json"
    bigger_path.write_bytes(bigger_payload)

    with pytest.raises(opm.OPMSourceDriftError, match="digest drift|byte length drift"):
        opm.acquire_opm_constants(
            opm.OPM_PAY_PLAN_CODES_2026_08_03,
            tmp_path,
            source_path=bigger_path,
        )


def test_package_build_is_byte_deterministic_and_carries_no_concept_identity(
    tmp_path: Path,
) -> None:
    first = opm.build_opm_controlled_list_package(opm.OPM_PLUM_POSITION_STATUS_CODE_PACKAGE, PLUM_FIXTURE)
    second = opm.build_opm_controlled_list_package(opm.OPM_PLUM_POSITION_STATUS_CODE_PACKAGE, PLUM_FIXTURE)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest
    assert first.resource_manifest["resourceKind"] == "controlledCodeList"
    assert first.resource_manifest["conceptIdentityClaimed"] is False
    assert first.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert all(observation["conceptIdentityClaimed"] is False for observation in first.observations)
    assert first.logical_digest == opm.OPM_PLUM_POSITION_STATUS_CODE_PACKAGE.expected_logical_digest


def test_package_round_trips_through_write_and_open(tmp_path: Path) -> None:
    built = opm.build_opm_controlled_list_package(opm.OPM_PAY_PLAN_CODE_PACKAGE, PAY_PLAN_FIXTURE)
    package_path = built.write_to(tmp_path / "opm-pay-plan-codes")

    view = opm.OPMControlledListView.open(package_path)

    assert view.spec is opm.OPM_PAY_PLAN_CODE_PACKAGE
    assert len(view.observations_by_code) == 6
    assert view.lookup_code("GS")["labels"][0]["value"] == "General Schedule"
    assert view.lookup_code("GS")["category"] == "payPlan"
    assert view.lookup_code("ZZ") is None


def test_reader_rejects_a_repackage_that_drops_the_external_pin(tmp_path: Path) -> None:
    original = opm.build_opm_controlled_list_package(opm.OPM_WORK_SCHEDULE_CODE_PACKAGE, WORK_SCHEDULE_FIXTURE)
    from refspec.registry.source_controlled_resource import (
        build_source_controlled_resource_bundle,
    )

    repackaged = build_source_controlled_resource_bundle(
        resource_id=opm.OPM_WORK_SCHEDULE_CODE_PACKAGE.resource_id,
        title=opm.OPM_WORK_SCHEDULE_CODE_PACKAGE.title,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=opm.OPM_WORK_SCHEDULE_CODE_PACKAGE.pin.retrieved_at,
        candidate_use_authorized=False,
        observations=original.observations,
        source_artifacts=original.source_artifacts,
        source_observed_count=5,
        gaps=opm.OPM_WORK_SCHEDULE_CODE_PACKAGE.known_gaps,
    )
    package_path = repackaged.write_to(tmp_path / "repackaged")

    with pytest.raises(opm.OPMControlledListPackageError, match="external pin"):
        opm.OPMControlledListView.open(package_path)

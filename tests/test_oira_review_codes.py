"""Official OIRA EO 12866 review/meeting field capture, parsing, and validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import oira_review_codes as oira
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "oira_review_codes"
ADVANCED_SEARCH_FIXTURE = FIXTURES / "eo-advanced-search-2026-08-03.html"
MEETING_SEARCH_FIXTURE = FIXTURES / "eo-meeting-search-2026-08-03.html"

_FIXTURE_BY_FIELD = {
    "reviewStatus": ADVANCED_SEARCH_FIXTURE,
    "ruleStage": ADVANCED_SEARCH_FIXTURE,
    "concludedAction": ADVANCED_SEARCH_FIXTURE,
    "meetingStatus": MEETING_SEARCH_FIXTURE,
}


def _acquire(tmp_path: Path, pin: oira.OIRAFieldSnapshotPin) -> oira.AcquiredOIRAField:
    return oira.acquire_oira_field(pin, tmp_path, source_path=_FIXTURE_BY_FIELD[pin.field.field_name])


def _portfolio(tmp_path: Path) -> oira.OIRAControlPortfolio:
    parsed = [oira.parse_oira_field(_acquire(tmp_path, pin)) for pin in oira.OIRA_FIELD_PINS_2026_08_03]
    return oira.assemble_oira_control_portfolio(parsed)


def test_live_snapshot_pins_match_exact_official_html_bytes(tmp_path: Path) -> None:
    for pin in oira.OIRA_FIELD_PINS_2026_08_03:
        acquired = _acquire(tmp_path, pin)
        assert acquired.byte_length == pin.expected_byte_length
        assert acquired.sha256 == pin.expected_sha256


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = oira.OIRA_REVIEW_STATUS_2026_08_03

    acquired = _acquire(tmp_path, pin)
    cached = oira.acquire_oira_field(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / "reviewStatus.html")
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    pin = oira.OIRA_MEETING_STATUS_2026_08_03
    payload = MEETING_SEARCH_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> oira.FetchedOIRAResponse:
            calls.append((source_url, timeout_seconds))
            return oira.FetchedOIRAResponse(
                body=payload,
                status_code=200,
                content_type="text/html;charset=UTF-8",
                resolved_url=source_url,
            )

    acquired = oira.acquire_oira_field(
        pin,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(oira.OIRA_MEETING_STATUS.page_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.sha256 == pin.expected_sha256


def test_review_status_is_source_evidence_not_a_general_subject_concept(
    tmp_path: Path,
) -> None:
    resource = oira.parse_oira_field(_acquire(tmp_path, oira.OIRA_REVIEW_STATUS_2026_08_03))

    assert len(resource.values) == 2
    assert resource.by_code()["PR"].publisher_label == "Pending Review"
    assert resource.by_code()["CD"] == oira.OIRAValue(
        field_name="reviewStatus",
        use="deterministicMetadata",
        publisher_label="Concluded",
        page_url=oira.OIRA_EO_ADVANCED_SEARCH_URL,
        identifiers=(
            ControlledIdentifier(
                value="CD",
                kind="reviewStatusCode",
                authority_uri=oira.OIRA_IDENTIFIER_AUTHORITY_URI,
                source_uri=oira.OIRA_REVIEW_STATUS.source_id,
                observed_at="2026-08-03T19:13:02Z",
                effective_at=None,
                source_digest=oira.OIRA_REVIEW_STATUS_2026_08_03.expected_sha256,
            ),
        ),
        is_general_subject_concept=False,
    )
    assert all(not value.is_general_subject_concept for value in resource.values)


def test_rule_stage_retains_six_codes_and_deterministic_use(tmp_path: Path) -> None:
    resource = oira.parse_oira_field(_acquire(tmp_path, oira.OIRA_RULE_STAGE_2026_08_03))

    assert len(resource.values) == 6
    assert resource.by_code()["1"].publisher_label == "Prerule"
    assert resource.by_code()["4"].publisher_label == "Final Rule"
    assert resource.by_code()["6"].publisher_label == "Notice"
    assert all(value.use == "deterministicMetadata" for value in resource.values)
    assert all(not value.is_general_subject_concept for value in resource.values)


def test_concluded_action_excludes_the_blank_placeholder_option(tmp_path: Path) -> None:
    resource = oira.parse_oira_field(_acquire(tmp_path, oira.OIRA_CONCLUDED_ACTION_2026_08_03))

    assert len(resource.values) == 9
    assert "" not in resource.by_code()
    assert resource.by_code()["CC"].publisher_label == "Consistent with Change"
    assert resource.by_code()["WD"].publisher_label == "Withdrawn"


def test_meeting_status_excludes_the_select_placeholder_option(tmp_path: Path) -> None:
    resource = oira.parse_oira_field(_acquire(tmp_path, oira.OIRA_MEETING_STATUS_2026_08_03))

    assert len(resource.values) == 3
    assert "" not in resource.by_code()
    assert resource.by_code()["C"].publisher_label == "Completed Meeting"
    assert resource.by_code()["S"].publisher_label == "Scheduled Meeting"
    assert resource.by_code()["N"].publisher_label == "No Show"


def test_portfolio_records_label_mismatch_and_release_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert set(portfolio.review_status.by_code()) == {"PR", "CD"}
    assert set(portfolio.rule_stage.by_code()) == {"1", "2", "3", "4", "5", "6"}
    assert len(portfolio.concluded_action.by_code()) == 9
    assert set(portfolio.meeting_status.by_code()) == {"C", "S", "N"}
    assert any("no release date" in gap for gap in portfolio.gaps)
    assert any("label the same" in gap for gap in portfolio.gaps)
    assert any("No subject exists on the review or meeting event" in gap for gap in portfolio.gaps)


def test_validated_record_codes_do_not_become_subjects(tmp_path: Path) -> None:
    record = {
        "review_status": "CD",
        "rule_stages": ["4", "5"],
        "concluded_action": "CW",
        "meeting_status": "C",
    }

    validated = oira.validate_oira_record_codes(record, _portfolio(tmp_path))

    assert validated.review_status.publisher_label == "Concluded"
    assert validated.review_status.use == "deterministicMetadata"
    assert [stage.publisher_label for stage in validated.rule_stages] == [
        "Final Rule",
        "Final Rule No Material Change",
    ]
    assert validated.concluded_action is not None
    assert validated.concluded_action.publisher_label == "Consistent without Change"
    assert validated.meeting_status is not None
    assert validated.meeting_status.publisher_label == "Completed Meeting"
    assert all(
        not assignment.is_general_subject_concept
        for assignment in (
            validated.review_status,
            *validated.rule_stages,
            validated.concluded_action,
            validated.meeting_status,
        )
    )


def test_validated_record_codes_allow_absent_optional_fields(tmp_path: Path) -> None:
    validated = oira.validate_oira_record_codes({"review_status": "PR"}, _portfolio(tmp_path))

    assert validated.review_status.publisher_label == "Pending Review"
    assert validated.rule_stages == ()
    assert validated.concluded_action is None
    assert validated.meeting_status is None


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"review_status": "XX"}, "unknown OIRA review_status"),
        ({"review_status": "PR", "rule_stages": ["9"]}, "unknown OIRA rule_stage"),
        ({"review_status": "CD", "concluded_action": "ZZ"}, "unknown OIRA concluded_action"),
        ({"review_status": "PR", "meeting_status": "X"}, "unknown OIRA meeting_status"),
        ({}, "must carry a string review_status"),
    ],
)
def test_unknown_or_missing_control_fails_closed(
    tmp_path: Path,
    record: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(oira.OIRAAssignmentError, match=message):
        oira.validate_oira_record_codes(record, _portfolio(tmp_path))


def test_digest_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = ADVANCED_SEARCH_FIXTURE.read_bytes()
    changed = payload.replace(b"Pending Review", b"Pending Reviewx")

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> oira.FetchedOIRAResponse:
            del timeout_seconds
            return oira.FetchedOIRAResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(oira.OIRASourceDriftError, match="byte length drift"):
        oira.acquire_oira_field(
            oira.OIRA_REVIEW_STATUS_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_ambiguous_or_missing_anchor_fails_closed(tmp_path: Path) -> None:
    duplicated = ADVANCED_SEARCH_FIXTURE.read_bytes()
    duplicated = duplicated + duplicated[duplicated.index(b'<label style="font-weight:100"><input id="eoStatusCode1"') :]
    duplicate_path = tmp_path / "duplicated.html"
    duplicate_path.write_bytes(duplicated)

    with pytest.raises(oira.OIRASourceDriftError, match="occurs 2 times"):
        oira.acquire_oira_field(
            oira.OIRA_REVIEW_STATUS_2026_08_03,
            tmp_path / "store-a",
            source_path=duplicate_path,
        )

    missing_end = ADVANCED_SEARCH_FIXTURE.read_bytes().replace(b"Concluded</label>", b"Concluded</labelx>")
    missing_path = tmp_path / "missing.html"
    missing_path.write_bytes(missing_end)

    with pytest.raises(oira.OIRASourceDriftError, match="end marker was not found"):
        oira.acquire_oira_field(
            oira.OIRA_REVIEW_STATUS_2026_08_03,
            tmp_path / "store-b",
            source_path=missing_path,
        )


def test_option_count_drift_fails_closed(tmp_path: Path) -> None:
    payload = ADVANCED_SEARCH_FIXTURE.read_bytes()
    dropped = payload.replace(
        b'<option value="WD">Withdrawn</option>',
        b"",
    )
    mini_pin = oira.OIRAFieldSnapshotPin(
        field=oira.OIRA_CONCLUDED_ACTION,
        retrieved_at="2026-08-03T19:13:02Z",
        expected_sha256=oira.sha256_digest(
            dropped[
                dropped.index(b'<select id="concludedActionCode" name="concludedActionCode">') : dropped.index(
                    b"</select>",
                    dropped.index(b'<select id="concludedActionCode" name="concludedActionCode">'),
                )
                + len(b"</select>")
            ]
        ),
        expected_byte_length=len(
            dropped[
                dropped.index(b'<select id="concludedActionCode" name="concludedActionCode">') : dropped.index(
                    b"</select>",
                    dropped.index(b'<select id="concludedActionCode" name="concludedActionCode">'),
                )
                + len(b"</select>")
            ]
        ),
    )
    dropped_path = tmp_path / "dropped.html"
    dropped_path.write_bytes(dropped)

    acquired = oira.acquire_oira_field(mini_pin, tmp_path / "store", source_path=dropped_path)
    with pytest.raises(oira.OIRASourceDriftError, match="count drift"):
        oira.parse_oira_field(acquired)


def test_build_oira_review_and_meeting_package_is_closed_and_reopens_cleanly(
    tmp_path: Path,
) -> None:
    acquired = {
        pin.field.field_name: _acquire(tmp_path / "acquire", pin) for pin in oira.OIRA_FIELD_PINS_2026_08_03
    }

    bundle = oira.build_oira_review_and_meeting_package(
        review_status=acquired["reviewStatus"],
        rule_stage=acquired["ruleStage"],
        concluded_action=acquired["concludedAction"],
        meeting_status=acquired["meetingStatus"],
    )

    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["uses"] == ["deterministicMetadata"]
    assert bundle.resource_manifest["observationCount"] == 20
    assert bundle.coverage_report["packagedCount"] == 20
    assert bundle.coverage_report["excludedCount"] == 2
    assert bundle.coverage_report["reportStatus"] == "gap"
    assert len({observation["id"] for observation in bundle.observations}) == 20
    assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
    assert all(observation["eligibleUses"] == ["deterministicMetadata"] for observation in bundle.observations)

    destination = tmp_path / "package"
    bundle.write_to(destination)
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 20

"""Official LDA code-list capture, parsing, and filing-assignment tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import lda_controlled_codes as lda
from refspec.registry.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures"
ISSUES_FIXTURE = FIXTURES / "lda-general-issue-codes-2026-07-30.json"
TYPES_FIXTURE = FIXTURES / "lda-filing-types-2026-07-30.json"


def _acquire(
    tmp_path: Path,
    pin: lda.LDASnapshotPin,
    source_path: Path,
) -> lda.AcquiredLDASource:
    return lda.acquire_lda_constants(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> lda.LDAControlPortfolio:
    issues = lda.parse_lda_constants(_acquire(tmp_path, lda.LDA_GENERAL_ISSUE_CODES_2026_07_30, ISSUES_FIXTURE))
    types = lda.parse_lda_constants(_acquire(tmp_path, lda.LDA_FILING_TYPES_2026_07_30, TYPES_FIXTURE))
    return lda.assemble_lda_control_portfolio((issues, types))


def test_live_snapshot_pins_match_exact_official_json_bytes() -> None:
    issues = ISSUES_FIXTURE.read_bytes()
    filing_types = TYPES_FIXTURE.read_bytes()

    assert len(issues) == 3_596
    assert lda.sha256_digest(issues) == ("sha256:e1820ef17f3e63048ae50e526c2f56e507b2cf60d720fc227c76ee7c3610d5bf")
    assert len(filing_types) == 2_803
    assert lda.sha256_digest(filing_types) == (
        "sha256:49fbd39383b0be63fb474878aa229d4e397880a30c2e0dac1a0905bc660a3149"
    )


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = lda.LDA_GENERAL_ISSUE_CODES_2026_07_30

    acquired = _acquire(tmp_path, pin, ISSUES_FIXTURE)
    cached = lda.acquire_lda_constants(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = TYPES_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> lda.FetchedLDAResponse:
            calls.append((source_url, timeout_seconds))
            return lda.FetchedLDAResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    acquired = lda.acquire_lda_constants(
        lda.LDA_FILING_TYPES_2026_07_30,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(lda.LDA_FILING_TYPES.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_general_issue_codes_are_source_evidence_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = lda.parse_lda_constants(_acquire(tmp_path, lda.LDA_GENERAL_ISSUE_CODES_2026_07_30, ISSUES_FIXTURE))

    assert len(resource.codes) == 79
    assert resource.api_interface_version == "1.0.0"
    assert resource.publisher_release is None
    assert resource.by_code()["TEC"] == lda.LDACode(
        resource_name="generalIssueCodes",
        use="sourceAssignedEvidence",
        publisher_label="Telecommunications",
        source_url=lda.LDA_GENERAL_ISSUE_CODES.source_url,
        identifiers=(
            ControlledIdentifier(
                value="TEC",
                kind="generalIssueCode",
                authority_uri=lda.LDA_IDENTIFIER_AUTHORITY_URI,
                source_uri=lda.LDA_GENERAL_ISSUE_CODES.source_url,
                observed_at="2026-07-30T12:45:14Z",
                effective_at=None,
                source_digest=lda.LDA_GENERAL_ISSUE_CODES_2026_07_30.expected_sha256,
            ),
        ),
        is_general_subject_concept=False,
    )
    assert resource.by_code()["BUD"].publisher_label == "Budget/Appropriations"
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_filing_types_remain_deterministic_codes(tmp_path: Path) -> None:
    resource = lda.parse_lda_constants(_acquire(tmp_path, lda.LDA_FILING_TYPES_2026_07_30, TYPES_FIXTURE))

    assert len(resource.codes) == 50
    assert resource.by_code()["Q1"].publisher_label == "1st Quarter - Report"
    assert resource.by_code()["1@Y"].publisher_label == ("1st Quarter - Termination Amendment (No Activity)")
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_portfolio_records_period_source_and_status_release_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.filing_period_values == (
        "first_quarter",
        "second_quarter",
        "third_quarter",
        "fourth_quarter",
        "mid_year",
        "year_end",
    )
    assert lda.LDA_OPENAPI_2026_07_30_SHA256.startswith("sha256:")
    assert lda.LDA_OPENAPI_2026_07_30_BYTE_LENGTH == 322_740
    assert any("no standalone filing-status" in gap for gap in portfolio.gaps)
    assert any("no independent period constants" in gap for gap in portfolio.gaps)
    assert any("do not publish a code-list release" in gap for gap in portfolio.gaps)


def test_current_spicy_regs_filing_codes_validate_without_becoming_subjects(
    tmp_path: Path,
) -> None:
    filing = {
        "filing_type": "Q1",
        "filing_period": "first_quarter",
        "lobbying_activities": [
            {
                "general_issue_code": "TEC",
                "general_issue_code_display": "Telecommunications",
            },
            {
                "general_issue_code": "BUD",
                "general_issue_code_display": "Budget/Appropriations",
            },
        ],
    }

    validated = lda.validate_lobbying_filing_codes(filing, _portfolio(tmp_path))

    assert [identifier.value for identifier in validated.filing_type.identifiers] == ["Q1"]
    assert validated.filing_type.use == "deterministicMetadata"
    assert validated.filing_period == "first_quarter"
    assert [issue.identifiers[0].value for issue in validated.general_issues] == ["TEC", "BUD"]
    assert all(issue.use == "sourceAssignedEvidence" for issue in validated.general_issues)
    assert all(not issue.is_general_subject_concept for issue in validated.general_issues)
    assert validated.filing_status is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("filing_type", "UNKNOWN", "unknown LDA filing_type"),
        ("filing_period", "monthly", "unknown LDA filing_period"),
    ],
)
def test_unknown_filing_control_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    filing = {
        "filing_type": "Q1",
        "filing_period": "first_quarter",
        "lobbying_activities": [],
        field: value,
    }

    with pytest.raises(lda.LDAAssignmentError, match=message):
        lda.validate_lobbying_filing_codes(filing, _portfolio(tmp_path))


def test_unknown_or_mislabeled_issue_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    base = {
        "filing_type": "Q1",
        "filing_period": "first_quarter",
    }

    with pytest.raises(lda.LDAAssignmentError, match="unknown general_issue_code"):
        lda.validate_lobbying_filing_codes(
            {
                **base,
                "lobbying_activities": [
                    {
                        "general_issue_code": "ZZZ",
                        "general_issue_code_display": "Invented",
                    }
                ],
            },
            portfolio,
        )
    with pytest.raises(lda.LDAAssignmentError, match="display mismatch"):
        lda.validate_lobbying_filing_codes(
            {
                **base,
                "lobbying_activities": [
                    {
                        "general_issue_code": "TEC",
                        "general_issue_code_display": "Technology",
                    }
                ],
            },
            portfolio,
        )


def test_digest_or_unknown_shape_drift_never_becomes_a_parsed_resource(
    tmp_path: Path,
) -> None:
    payload = ISSUES_FIXTURE.read_bytes()
    changed = payload.replace(b'"Accounting"', b'"Accountinh"')
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> lda.FetchedLDAResponse:
            del timeout_seconds
            return lda.FetchedLDAResponse(
                body=changed,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    with pytest.raises(lda.LDASourceDriftError, match="digest drift"):
        lda.acquire_lda_constants(
            lda.LDA_GENERAL_ISSUE_CODES_2026_07_30,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = b'[{"value":"TEC","name":"Telecommunications","slug":"telecommunications"}]'
    mini_source = replace(lda.LDA_GENERAL_ISSUE_CODES, expected_count=1)
    mini_pin = lda.LDASnapshotPin(
        source=mini_source,
        retrieved_at="2026-07-30T12:45:14Z",
        expected_sha256=lda.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.json"
    mini_path.write_bytes(mini_payload)
    acquired = lda.acquire_lda_constants(
        mini_pin,
        tmp_path / "shape",
        source_path=mini_path,
    )
    with pytest.raises(lda.LDASourceDriftError, match="fields drifted"):
        lda.parse_lda_constants(acquired)


def test_parser_retains_multiple_source_identifiers_as_structured_records(
    tmp_path: Path,
) -> None:
    payload = (
        b'[{"value":"TEC","name":"Telecommunications","id":42,'
        b'"identifier":"official-telecom","code":"legacy-tec",'
        b'"url":"https://lda.gov/api/v1/constants/filing/lobbyingactivityissues/42/"}]'
    )
    source = replace(lda.LDA_GENERAL_ISSUE_CODES, expected_count=1)
    pin = lda.LDASnapshotPin(
        source=source,
        retrieved_at="2026-07-30T12:45:14Z",
        expected_sha256=lda.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    source_path = tmp_path / "multiple-identifiers.json"
    source_path.write_bytes(payload)

    resource = lda.parse_lda_constants(
        lda.acquire_lda_constants(
            pin,
            tmp_path / "store",
            source_path=source_path,
        )
    )

    assert resource.codes[0].identifiers == (
        ControlledIdentifier(
            value="TEC",
            kind="generalIssueCode",
            authority_uri=lda.LDA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source.source_url,
            observed_at=pin.retrieved_at,
            effective_at=None,
            source_digest=pin.expected_sha256,
        ),
        ControlledIdentifier(
            value="42",
            kind="publisherRecordId",
            authority_uri=lda.LDA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source.source_url,
            observed_at=pin.retrieved_at,
            effective_at=None,
            source_digest=pin.expected_sha256,
        ),
        ControlledIdentifier(
            value="official-telecom",
            kind="publisherIdentifier",
            authority_uri=lda.LDA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source.source_url,
            observed_at=pin.retrieved_at,
            effective_at=None,
            source_digest=pin.expected_sha256,
        ),
        ControlledIdentifier(
            value="legacy-tec",
            kind="publisherCode",
            authority_uri=lda.LDA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source.source_url,
            observed_at=pin.retrieved_at,
            effective_at=None,
            source_digest=pin.expected_sha256,
        ),
        ControlledIdentifier(
            value="https://lda.gov/api/v1/constants/filing/lobbyingactivityissues/42/",
            kind="publisherTermURI",
            authority_uri=lda.LDA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source.source_url,
            observed_at=pin.retrieved_at,
            effective_at=None,
            source_digest=pin.expected_sha256,
        ),
    )

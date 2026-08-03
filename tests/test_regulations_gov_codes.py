"""Official Regulations.gov OpenAPI controlled-code capture and parsing tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import regulations_gov_codes as rgov
from refspec.registry.controlled_identifier import ControlledIdentifier

FIXTURES = Path(__file__).parent / "fixtures" / "regulations_gov_codes"
OPENAPI_FIXTURE = FIXTURES / "regulations-gov-openapi-v4-2026-08-03.yaml"


def _acquire(tmp_path: Path, source_path: Path = OPENAPI_FIXTURE) -> rgov.AcquiredRGovSource:
    return rgov.acquire_regulations_gov_openapi(rgov.RGOV_OPENAPI_2026_08_03, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> rgov.RegulationsGovControlPortfolio:
    acquired = _acquire(tmp_path)
    resources = [
        rgov.parse_regulations_gov_resource(acquired, name)
        for name in ("documentType", "docketType", "submitterType")
    ]
    return rgov.assemble_regulations_gov_control_portfolio(resources)


def test_live_snapshot_pin_matches_exact_official_yaml_bytes() -> None:
    payload = OPENAPI_FIXTURE.read_bytes()

    assert len(payload) == 60_826
    assert rgov.sha256_digest(payload) == (
        "sha256:be43c866f5ca424a456bde36ea03cb9326c454ef4e1894a13df80b6dc6e22488"
    )


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = rgov.RGOV_OPENAPI_2026_08_03

    acquired = _acquire(tmp_path)
    cached = rgov.acquire_regulations_gov_openapi(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = OPENAPI_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> rgov.FetchedRGovResponse:
            calls.append((source_url, timeout_seconds))
            return rgov.FetchedRGovResponse(
                body=payload,
                status_code=200,
                content_type="binary/octet-stream",
                resolved_url=source_url,
            )

    acquired = rgov.acquire_regulations_gov_openapi(
        rgov.RGOV_OPENAPI_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(rgov.RGOV_OPENAPI_SOURCE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_document_type_codes_are_deterministic_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = rgov.parse_regulations_gov_resource(_acquire(tmp_path), "documentType")

    assert len(resource.codes) == 5
    assert resource.api_spec_version == "4.0"
    assert resource.publisher_last_modified == "2026-07-02T21:13:41Z"
    assert [code.publisher_label for code in resource.codes] == [
        "Notice",
        "Rule",
        "Proposed Rule",
        "Supporting & Related Material",
        "Other",
    ]
    assert resource.by_code()["Rule"] == rgov.RGovCode(
        resource_name="documentType",
        use="deterministicMetadata",
        publisher_label="Rule",
        source_url=rgov.RGOV_OPENAPI_URL,
        identifiers=(
            ControlledIdentifier(
                value="Rule",
                kind="documentTypeCode",
                authority_uri=rgov.RGOV_IDENTIFIER_AUTHORITY_URI,
                source_uri=rgov.RGOV_OPENAPI_URL,
                observed_at="2026-08-03T19:13:12Z",
                effective_at=None,
                source_digest=rgov.RGOV_OPENAPI_2026_08_03.expected_sha256,
            ),
        ),
        is_general_subject_concept=False,
    )
    assert all(not code.is_general_subject_concept for code in resource.codes)
    assert all(code.use == "deterministicMetadata" for code in resource.codes)


def test_docket_type_codes_trim_the_source_trailing_whitespace_quirk(
    tmp_path: Path,
) -> None:
    resource = rgov.parse_regulations_gov_resource(_acquire(tmp_path), "docketType")

    assert len(resource.codes) == 2
    labels = [code.publisher_label for code in resource.codes]
    assert labels == ["Rulemaking", "Nonrulemaking"]
    # The pinned source spells the second value with a trailing space
    # (a YAML plain-scalar quirk); the parsed label must not carry it.
    assert labels[1] == "Nonrulemaking"
    assert not labels[1].endswith(" ")


def test_submitter_type_codes_remain_a_closed_deterministic_list(
    tmp_path: Path,
) -> None:
    resource = rgov.parse_regulations_gov_resource(_acquire(tmp_path), "submitterType")

    assert [code.publisher_label for code in resource.codes] == [
        "Anonymous",
        "Individual",
        "Organization",
    ]
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_portfolio_records_agency_configured_and_attachment_gaps(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.agency_configured_fields == (
        "subtype",
        "category",
        "organizationType",
        "govAgencyType",
        "restrictReasonType",
    )
    assert any("agency-configured free text" in gap for gap in portfolio.gaps)
    assert any("no fine-grained cross-agency attachment taxonomy" in gap for gap in portfolio.gaps)
    assert any("does not publish a code-list release number" in gap for gap in portfolio.gaps)
    assert any("outside this catalog's current scope" in gap for gap in portfolio.gaps)


def test_current_document_and_docket_records_validate_without_becoming_subjects(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    document = {
        "agencyId": "EPA",
        "documentType": "Supporting & Related Material",
        "docketId": "EPA-HQ-OAR-2003-0129",
        "subtype": "Office of Management and Budget (OMB)",
    }
    docket = {
        "agencyId": "EPA",
        "docketType": "Rulemaking",
    }

    document_assignment = rgov.validate_regulations_gov_document_type(document, portfolio)
    docket_assignment = rgov.validate_regulations_gov_docket_type(docket, portfolio)

    assert document_assignment.publisher_label == "Supporting & Related Material"
    assert document_assignment.use == "deterministicMetadata"
    assert document_assignment.is_general_subject_concept is False
    assert docket_assignment.publisher_label == "Rulemaking"
    assert docket_assignment.is_general_subject_concept is False


@pytest.mark.parametrize(
    ("validator_name", "field", "value", "message"),
    [
        ("validate_regulations_gov_document_type", "documentType", "Guidance", "unknown Regulations.gov documentType"),
        ("validate_regulations_gov_docket_type", "docketType", "Adjudication", "unknown Regulations.gov docketType"),
    ],
)
def test_unknown_type_fails_closed(
    tmp_path: Path,
    validator_name: str,
    field: str,
    value: str,
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)
    validator = getattr(rgov, validator_name)

    with pytest.raises(rgov.RegulationsGovAssignmentError, match=message):
        validator({field: value}, portfolio)


def test_missing_type_field_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    with pytest.raises(rgov.RegulationsGovAssignmentError, match="must carry a string documentType"):
        rgov.validate_regulations_gov_document_type({}, portfolio)
    with pytest.raises(rgov.RegulationsGovAssignmentError, match="must carry a string docketType"):
        rgov.validate_regulations_gov_docket_type({}, portfolio)


def test_digest_drift_never_becomes_an_acquired_source(tmp_path: Path) -> None:
    payload = OPENAPI_FIXTURE.read_bytes()
    changed = payload.replace(b"- Notice\n", b"- Noticx\n")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> rgov.FetchedRGovResponse:
            del timeout_seconds
            return rgov.FetchedRGovResponse(
                body=changed,
                status_code=200,
                content_type="binary/octet-stream",
                resolved_url=source_url,
            )

    with pytest.raises(rgov.RegulationsGovSourceDriftError, match="digest drift"):
        rgov.acquire_regulations_gov_openapi(
            rgov.RGOV_OPENAPI_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_structural_shape_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    # A byte-faithful but restructured document: DocumentType keeps only 4 of
    # its 5 members. The parser must reject the count drift rather than
    # silently returning a shorter list.
    mini_payload = (
        b'openapi: 3.0.0\ninfo:\n  version: "4.0"\ncomponents:\n  schemas:\n'
        b"    DocumentType:\n      type: string\n      description: type of document\n"
        b"      enum:\n        - Notice\n        - Rule\n        - Proposed Rule\n"
        b"        - Other\n"
    )
    mini_source = replace(rgov.RGOV_OPENAPI_SOURCE, filename="mini-openapi.yaml")
    mini_pin = rgov.RGovSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:13:12Z",
        expected_sha256=rgov.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.yaml"
    mini_path.write_bytes(mini_payload)
    acquired = rgov.acquire_regulations_gov_openapi(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(rgov.RegulationsGovSourceDriftError, match="count drift"):
        rgov.parse_regulations_gov_resource(acquired, "documentType")


def test_missing_enum_block_fails_closed(tmp_path: Path) -> None:
    mini_payload = b'openapi: 3.0.0\ninfo:\n  version: "4.0"\ncomponents:\n  schemas: {}\n'
    mini_source = replace(rgov.RGOV_OPENAPI_SOURCE, filename="no-enums.yaml")
    mini_pin = rgov.RGovSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:13:12Z",
        expected_sha256=rgov.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.yaml"
    mini_path.write_bytes(mini_payload)
    acquired = rgov.acquire_regulations_gov_openapi(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(rgov.RegulationsGovSourceDriftError, match="enum block .* was not found"):
        rgov.parse_regulations_gov_resource(acquired, "docketType")


def test_api_spec_version_drift_fails_closed(tmp_path: Path) -> None:
    mini_payload = b'openapi: 3.0.0\ninfo:\n  version: "5.0"\ncomponents:\n  schemas: {}\n'
    mini_source = replace(rgov.RGOV_OPENAPI_SOURCE, filename="future-version.yaml")
    mini_pin = rgov.RGovSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:13:12Z",
        expected_sha256=rgov.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.yaml"
    mini_path.write_bytes(mini_payload)

    with pytest.raises(rgov.RegulationsGovSourceDriftError, match="info.version drifted"):
        rgov.acquire_regulations_gov_openapi(mini_pin, tmp_path / "store", source_path=mini_path)


def test_portfolio_assembly_requires_all_three_resources(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    document_type = rgov.parse_regulations_gov_resource(acquired, "documentType")

    with pytest.raises(rgov.RegulationsGovSourceDriftError, match="requires exactly one"):
        rgov.assemble_regulations_gov_control_portfolio([document_type])

"""Official SAM.gov Assistance Listings controlled-code capture, parsing, and package tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import sam_assistance_listing_codes as sam
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "sam_assistance_listing_codes"
DOC_FIXTURE = FIXTURES / "sam-assistance-listings-api-2026-08-03.html"


def _acquire(tmp_path: Path, source_path: Path = DOC_FIXTURE) -> sam.AcquiredSAMAssistanceSource:
    return sam.acquire_sam_assistance_listing_doc(
        sam.SAM_ASSISTANCE_DOC_2026_08_03,
        tmp_path,
        source_path=source_path,
    )


def _portfolio(tmp_path: Path) -> sam.SAMAssistanceListingCodePortfolio:
    return sam.parse_sam_assistance_listing_codes(_acquire(tmp_path))


def test_live_snapshot_pin_matches_exact_official_html_bytes() -> None:
    payload = DOC_FIXTURE.read_bytes()

    assert len(payload) == 210_611
    assert sam.sha256_digest(payload) == ("sha256:6ea76d040e2190b02cad8192f50dbe00d39f01f5366f893cd24b6491dfdeeffd")
    assert payload.startswith(b"<!doctype html>")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = sam.SAM_ASSISTANCE_DOC_2026_08_03

    acquired = _acquire(tmp_path)
    cached = sam.acquire_sam_assistance_listing_doc(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> sam.FetchedSAMAssistanceResponse:
            calls.append((source_url, timeout_seconds))
            return sam.FetchedSAMAssistanceResponse(
                body=payload,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = sam.acquire_sam_assistance_listing_doc(
        sam.SAM_ASSISTANCE_DOC_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=21.0,
    )

    assert calls == [(sam.SAM_ASSISTANCE_DOC_SOURCE.source_url, 21.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_assistance_type_codes_combine_financial_and_non_financial(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.assistance_types_by_code()

    assert len(portfolio.assistance_types) == 17
    assert {code.category for code in portfolio.assistance_types} == {"financial", "nonFinancial"}
    assert by_code["F001"].publisher_label == "Grant"
    assert by_code["F001"].category == "financial"
    assert by_code["F010"].publisher_label == "Other Financial Assistance"
    assert by_code["N001"].publisher_label == "Use of Property, Facilities, and Equipment"
    assert by_code["N001"].category == "nonFinancial"
    assert by_code["N007"].publisher_label == "Other Non-Financial Assistance"
    assert all(code.use == "deterministicMetadata" for code in portfolio.assistance_types)
    assert all(not code.is_general_subject_concept for code in portfolio.assistance_types)

    identifier = by_code["F001"].identifiers[0]
    assert identifier.kind == "assistanceTypeCode"
    assert identifier.value == "F001"
    assert identifier.authority_uri == sam.SAM_ASSISTANCE_IDENTIFIER_AUTHORITY_URI
    assert identifier.source_digest == sam.SAM_ASSISTANCE_DOC_2026_08_03.expected_sha256


def test_eligible_applicant_types_are_deterministic_metadata(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.eligible_applicant_types_by_code()

    assert len(portfolio.eligible_applicant_types) == 44
    assert by_code["ET11010"].publisher_label == "Unrestricted by Entity Type"
    assert by_code["ET22010"].publisher_label == ("U.S. State Government (including the District of Columbia)")
    assert by_code["ET59999"].publisher_label == "Other"
    assert all(code.use == "deterministicMetadata" for code in portfolio.eligible_applicant_types)
    assert all(not code.is_general_subject_concept for code in portfolio.eligible_applicant_types)
    assert all(code.category is None for code in portfolio.eligible_applicant_types)


def test_eligible_beneficiary_types_are_a_larger_distinct_family(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    by_code = portfolio.eligible_beneficiary_types_by_code()

    assert len(portfolio.eligible_beneficiary_types) == 73
    assert by_code["ET12010"].publisher_label == "Specific Restrictions Determined at NOFO Level"
    assert by_code["ET53080"].publisher_label == "Trainee"
    # Same Entity Type Code, different publisher label than the applicant table;
    # RefSpec keeps the two families separately indexed rather than merging them.
    assert by_code["ET22010"].publisher_label == "U.S. State Government"
    assert all(code.use == "deterministicMetadata" for code in portfolio.eligible_beneficiary_types)
    assert all(not code.is_general_subject_concept for code in portfolio.eligible_beneficiary_types)


def test_identity_fields_preserve_documented_aln_field_names(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)
    paths = {field.field_path for field in portfolio.identity_fields}

    assert "assistanceListingsData[].assistanceListingId" in paths
    assert "assistanceListingsData[].title" in paths
    assert "assistanceListingsData[].version" in paths
    assert "assistanceListingsData[].status" in paths
    assert "assistanceListingsData[].fiscalYear" in paths
    assert "assistanceListingsData[].publishedDate" in paths
    id_field = next(field for field in portfolio.identity_fields if field.field_path.endswith("assistanceListingId"))
    assert id_field.description == "CFDA / Assistance Listing ID"
    assert id_field.data_specification_version == "All"
    assert portfolio.api_interface_version == "v1.0"


def test_gaps_document_undocumented_fields_and_swapped_eligibility_references(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("programId" in gap for gap in portfolio.gaps)
    assert any("assitanceTypes" in gap for gap in portfolio.gaps)
    assert any("beneficiaryTypes" in gap and "applicantTypes" in gap for gap in portfolio.gaps)
    assert any("assistanceRestriction" in gap for gap in portfolio.gaps)
    assert any("Mission Sub-Categories" in gap or "subjectTerms" in gap for gap in portfolio.gaps)
    assert any(code.identifiers for code in portfolio.assistance_types)


def test_validate_assistance_listing_record_accepts_a_current_spicy_regs_record(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "assistanceListingId": "10.080",
        "title": "Milk Income Loss Contract Program",
        "status": "Active",
        "financialInformation": {
            "obligations": [
                {"assistanceType": {"code": "F001", "name": "Grant"}},
                {"assistanceType": {"code": "N003", "name": "Advisory Services"}},
            ]
        },
        "criteriaForApplying": {
            "applicant": {"types": [{"code": "ET22010", "name": "U.S. State Government (including the District of Columbia)"}]},
            "beneficiary": {"types": [{"code": "ET59999", "name": "Other"}]},
        },
    }

    validated = sam.validate_assistance_listing_record(record, portfolio)

    assert validated.assistance_listing_id == "10.080"
    assert validated.title == "Milk Income Loss Contract Program"
    assert validated.status == "Active"
    assert [code.identifiers[0].value for code in validated.assistance_types] == ["F001", "N003"]
    assert [code.identifiers[0].value for code in validated.applicant_types] == ["ET22010"]
    assert [code.identifiers[0].value for code in validated.beneficiary_types] == ["ET59999"]
    assert all(not code.is_general_subject_concept for code in validated.assistance_types)


@pytest.mark.parametrize(
    ("aln", "message"),
    [
        ("10080", "assistanceListingId"),
        ("10.08", "assistanceListingId"),
        ("", "assistanceListingId"),
    ],
)
def test_validate_assistance_listing_record_rejects_malformed_aln(
    tmp_path: Path,
    aln: str,
    message: str,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {"assistanceListingId": aln, "title": "Test", "status": "Active"}

    with pytest.raises(sam.SAMAssistanceAssignmentError, match=message):
        sam.validate_assistance_listing_record(record, portfolio)


def test_validate_assistance_listing_record_fails_closed_on_unknown_codes(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    base = {"assistanceListingId": "10.080", "title": "Test", "status": "Active"}

    with pytest.raises(sam.SAMAssistanceAssignmentError, match="unknown"):
        sam.validate_assistance_listing_record(
            {
                **base,
                "financialInformation": {"obligations": [{"assistanceType": {"code": "Z999", "name": "Invented"}}]},
            },
            portfolio,
        )

    with pytest.raises(sam.SAMAssistanceAssignmentError, match="unknown"):
        sam.validate_assistance_listing_record(
            {
                **base,
                "criteriaForApplying": {"applicant": {"types": [{"code": "ET99999", "name": "Invented"}]}},
            },
            portfolio,
        )


def test_validate_assistance_listing_record_fails_closed_on_display_mismatch(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "assistanceListingId": "10.080",
        "title": "Test",
        "status": "Active",
        "financialInformation": {
            "obligations": [{"assistanceType": {"code": "F001", "name": "Cooperative Agreement"}}]
        },
    }

    with pytest.raises(sam.SAMAssistanceAssignmentError, match="display mismatch"):
        sam.validate_assistance_listing_record(record, portfolio)


def test_digest_drift_never_becomes_a_parsed_portfolio(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    changed = payload.replace(b">Grant<", b">Grznt<", 1)
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> sam.FetchedSAMAssistanceResponse:
            del timeout_seconds
            return sam.FetchedSAMAssistanceResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(sam.SAMAssistanceSourceDriftError, match="digest drift"):
        sam.acquire_sam_assistance_listing_doc(
            sam.SAM_ASSISTANCE_DOC_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_shape_drift_in_the_assistance_types_table_fails_loudly(tmp_path: Path) -> None:
    mini_html = (
        b"<!doctype html><html><body>"
        b'<h5 id="financial-assistance">Financial Assistance</h5><table><tbody>'
        b"<tr><td>F001</td><td>Grant</td></tr>"
        b"</tbody></table>"
        b"</body></html>"
    )
    mini_pin = sam.SAMAssistanceSnapshotPin(
        source=sam.SAM_ASSISTANCE_DOC_SOURCE,
        retrieved_at="2026-08-03T19:28:13Z",
        expected_sha256=sam.sha256_digest(mini_html),
        expected_byte_length=len(mini_html),
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_html)

    acquired = sam.acquire_sam_assistance_listing_doc(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(sam.SAMAssistanceSourceDriftError, match="non-financial-assistance"):
        sam.parse_sam_assistance_listing_codes(acquired)


def test_package_round_trips_through_a_closed_source_controlled_resource(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path)
    portfolio = sam.parse_sam_assistance_listing_codes(acquired)

    bundle = sam.build_sam_assistance_listing_code_package("assistanceTypes", portfolio, acquired)
    destination = tmp_path / "package"
    bundle.write_to(destination)

    reopened = SourceControlledResourceView.open(destination)
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["conceptIdentityClaimed"] is False
    assert reopened.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert len(reopened.observations) == 17
    assert {obs["category"] for obs in reopened.observations} == {"financial", "nonFinancial"}


def test_package_rejects_an_unknown_resource_family(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    portfolio = sam.parse_sam_assistance_listing_codes(acquired)

    with pytest.raises(sam.SAMAssistancePackageError, match="unknown"):
        sam.build_sam_assistance_listing_code_package("missionSubCategories", portfolio, acquired)

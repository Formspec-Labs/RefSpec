"""Official FEC committee-code capture, parsing, and package tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import fec_committee_codes as fec
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "fec_committee_codes"
MASTER_FILE_FIXTURE = FIXTURES / "fec-committee-master-file-description-2026-08-03.html"
COMMITTEE_TYPE_FIXTURE = FIXTURES / "fec-committee-type-code-descriptions-2026-08-03.html"
PARTY_FIXTURE = FIXTURES / "fec-party-code-descriptions-2026-08-03.html"


def _acquire(
    tmp_path: Path,
    pin: fec.FECSnapshotPin,
    source_path: Path,
    *,
    store: str = "store",
) -> fec.AcquiredFECSource:
    return fec.acquire_fec_doc(pin, tmp_path / store, source_path=source_path)


def _master_file(tmp_path: Path) -> fec.AcquiredFECSource:
    return _acquire(tmp_path, fec.FEC_COMMITTEE_MASTER_FILE_2026_08_03, MASTER_FILE_FIXTURE)


def _committee_type_doc(tmp_path: Path) -> fec.AcquiredFECSource:
    return _acquire(tmp_path, fec.FEC_COMMITTEE_TYPE_CODES_2026_08_03, COMMITTEE_TYPE_FIXTURE)


def _party_doc(tmp_path: Path) -> fec.AcquiredFECSource:
    return _acquire(tmp_path, fec.FEC_PARTY_CODES_2026_08_03, PARTY_FIXTURE)


def _portfolio(tmp_path: Path) -> fec.FECCommitteePortfolio:
    master = _master_file(tmp_path)
    resources = [
        fec.parse_committee_designation_codes(master),
        fec.parse_filing_frequency_codes(master),
        fec.parse_organization_type_codes(master),
        fec.parse_committee_type_codes(_committee_type_doc(tmp_path)),
        fec.parse_party_codes(_party_doc(tmp_path)),
    ]
    return fec.assemble_fec_committee_portfolio(resources)


def test_live_snapshot_pins_match_exact_official_html_bytes() -> None:
    master = MASTER_FILE_FIXTURE.read_bytes()
    committee_type = COMMITTEE_TYPE_FIXTURE.read_bytes()
    party = PARTY_FIXTURE.read_bytes()

    assert len(master) == 29_343
    assert fec.sha256_digest(master) == ("sha256:dda49be2e360d39bb1b7dcbc53239e627109a26fbaefe172688aca84abc4ff66")
    assert len(committee_type) == 28_121
    assert fec.sha256_digest(committee_type) == (
        "sha256:84e9f16628fd2475750cd89a3947f2c737a5f66c8ced04aea6b1118ac2aecaa4"
    )
    assert len(party) == 29_578
    assert fec.sha256_digest(party) == ("sha256:e17420381df0e5709449a8c9702600fde97503ea378ef357beef4c40ed6a6b09")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = fec.FEC_COMMITTEE_MASTER_FILE_2026_08_03

    acquired = fec.acquire_fec_doc(pin, tmp_path, source_path=MASTER_FILE_FIXTURE)
    cached = fec.acquire_fec_doc(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = PARTY_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> fec.FetchedFECResponse:
            calls.append((source_url, timeout_seconds))
            return fec.FetchedFECResponse(
                body=payload,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = fec.acquire_fec_doc(
        fec.FEC_PARTY_CODES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=11.0,
    )

    assert calls == [(fec.FEC_PARTY_CODES_DOC.source_url, 11.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_committee_designation_codes_are_inline_deterministic_metadata(
    tmp_path: Path,
) -> None:
    resource = fec.parse_committee_designation_codes(_master_file(tmp_path))

    assert len(resource.codes) == 6
    by_code = resource.by_code()
    assert by_code["P"].publisher_label == "Principal campaign committee of a candidate"
    assert by_code["U"].publisher_label == "Unauthorized"
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)
    assert by_code["A"].identifiers[0].kind == "committeeDesignationCode"
    assert by_code["A"].identifiers[0].authority_uri == fec.FEC_IDENTIFIER_AUTHORITY_URI


def test_filing_frequency_codes_are_inline_deterministic_metadata(
    tmp_path: Path,
) -> None:
    resource = fec.parse_filing_frequency_codes(_master_file(tmp_path))

    assert len(resource.codes) == 6
    by_code = resource.by_code()
    assert by_code["Q"].publisher_label == "Quarterly filer"
    assert by_code["W"].publisher_label == "Waived"
    assert all(code.use == "deterministicMetadata" for code in resource.codes)


def test_organization_type_codes_are_inline_deterministic_metadata(
    tmp_path: Path,
) -> None:
    resource = fec.parse_organization_type_codes(_master_file(tmp_path))

    assert len(resource.codes) == 6
    by_code = resource.by_code()
    assert by_code["C"].publisher_label == "Corporation"
    assert by_code["W"].publisher_label == "Corporation without capital stock"


def test_committee_type_codes_preserve_explanations_and_strip_markup(
    tmp_path: Path,
) -> None:
    resource = fec.parse_committee_type_codes(_committee_type_doc(tmp_path))

    assert len(resource.codes) == 16
    by_code = resource.by_code()
    assert by_code["H"].publisher_label == "House"
    assert by_code["U"].description == ""
    assert "AO 2010-09" in by_code["O"].description
    assert "<a" not in by_code["O"].description
    assert all(code.use == "deterministicMetadata" for code in resource.codes)
    assert all(not code.is_general_subject_concept for code in resource.codes)


def test_party_codes_preserve_case_sensitive_publisher_codes_and_notes(
    tmp_path: Path,
) -> None:
    resource = fec.parse_party_codes(_party_doc(tmp_path))

    assert len(resource.codes) == 95
    by_code = resource.by_code()
    assert by_code["DEM"].publisher_label == "Democratic Party"
    assert by_code["REP"].publisher_label == "Republican Party"
    assert by_code["D/C"].publisher_label == "Democratic/Conservative"
    assert by_code["LRU"].description == "Also see RUP"
    assert "N" in by_code
    assert "n" not in by_code


def test_portfolio_assembly_requires_all_five_resources(tmp_path: Path) -> None:
    designation = fec.parse_committee_designation_codes(_master_file(tmp_path))
    filing_freq = fec.parse_filing_frequency_codes(_master_file(tmp_path))

    with pytest.raises(fec.FECSourceDriftError, match="requires exactly"):
        fec.assemble_fec_committee_portfolio([designation, filing_freq])


def test_portfolio_records_report_type_and_cycle_gaps(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("report type" in gap.lower() for gap in portfolio.gaps)
    assert any("cycle" in gap.lower() or "effective" in gap.lower() for gap in portfolio.gaps)
    assert all(
        code.identifiers[0].effective_at is None
        for resource in (
            portfolio.committee_designation,
            portfolio.committee_type,
            portfolio.party,
            portfolio.filing_frequency,
            portfolio.organization_type,
        )
        for code in resource.codes
    )


def test_validate_committee_master_record_accepts_known_codes(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "cmte_dsgn": "P",
        "cmte_tp": "H",
        "cmte_pty_affiliation": "DEM",
        "cmte_filing_freq": "Q",
        "org_tp": None,
    }

    validated = fec.validate_committee_master_record(record, portfolio)

    assert validated.committee_designation is not None
    assert validated.committee_designation.publisher_label == "Principal campaign committee of a candidate"
    assert validated.committee_type is not None
    assert validated.committee_type.publisher_label == "House"
    assert validated.party is not None
    assert validated.party.publisher_label == "Democratic Party"
    assert validated.filing_frequency is not None
    assert validated.filing_frequency.publisher_label == "Quarterly filer"
    assert validated.organization_type is None


def test_validate_committee_master_record_fails_closed_on_unknown_codes(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)
    record = {
        "cmte_dsgn": None,
        "cmte_tp": "ZZ",
        "cmte_pty_affiliation": None,
        "cmte_filing_freq": None,
        "org_tp": None,
    }

    with pytest.raises(fec.FECAssignmentError, match="unknown FEC committee type"):
        fec.validate_committee_master_record(record, portfolio)


def test_digest_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = COMMITTEE_TYPE_FIXTURE.read_bytes()
    changed = payload.replace(b"House", b"HousE", 1)
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> fec.FetchedFECResponse:
            del timeout_seconds
            return fec.FetchedFECResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(fec.FECSourceDriftError, match="digest drift"):
        fec.acquire_fec_doc(
            fec.FEC_COMMITTEE_TYPE_CODES_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_shape_drift_in_the_committee_type_table_fails_loudly(tmp_path: Path) -> None:
    mini_html = b"<!DOCTYPE html><html><body><table><tr><td>only one column</td></tr></table></body></html>"
    mini_pin = fec.FECSnapshotPin(
        source=fec.FEC_COMMITTEE_TYPE_CODES_DOC,
        retrieved_at="2026-08-03T19:24:00Z",
        expected_sha256=fec.sha256_digest(mini_html),
        expected_byte_length=len(mini_html),
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_html)

    acquired = fec.acquire_fec_doc(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(fec.FECSourceDriftError, match="committee type"):
        fec.parse_committee_type_codes(acquired)


def test_shape_drift_when_inline_field_row_disappears_fails_loudly(
    tmp_path: Path,
) -> None:
    mini_html = (
        b"<!DOCTYPE html><html><body>"
        b'<a href="https://www.fec.gov/campaign-finance-data/committee-type-code-descriptions">t</a>'
        b'<a href="https://www.fec.gov/campaign-finance-data/party-code-descriptions">p</a>'
        b"<table><tr><td>irrelevant</td></tr></table></body></html>"
    )
    mini_pin = fec.FECSnapshotPin(
        source=fec.FEC_COMMITTEE_MASTER_FILE_DOC,
        retrieved_at="2026-08-03T19:24:00Z",
        expected_sha256=fec.sha256_digest(mini_html),
        expected_byte_length=len(mini_html),
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_html)

    acquired = fec.acquire_fec_doc(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(fec.FECSourceDriftError, match="CMTE_DSGN"):
        fec.parse_committee_designation_codes(acquired)


def test_committee_type_link_on_master_file_page_must_target_the_pinned_doc(
    tmp_path: Path,
) -> None:
    payload = MASTER_FILE_FIXTURE.read_bytes()
    changed = payload.replace(
        b"https://www.fec.gov/campaign-finance-data/committee-type-code-descriptions",
        b"https://www.fec.gov/campaign-finance-data/committee-type-code-descriptionz",
    )
    assert len(changed) == len(payload)
    mini_pin = fec.FECSnapshotPin(
        source=fec.FEC_COMMITTEE_MASTER_FILE_DOC,
        retrieved_at="2026-08-03T19:24:00Z",
        expected_sha256=fec.sha256_digest(changed),
        expected_byte_length=len(changed),
    )
    mini_path = tmp_path / "changed-master-file.html"
    mini_path.write_bytes(changed)
    acquired = fec.acquire_fec_doc(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(fec.FECSourceDriftError, match="committee-type-code-descriptions"):
        fec.parse_committee_designation_codes(acquired)


def test_package_round_trips_through_a_closed_source_controlled_resource(
    tmp_path: Path,
) -> None:
    acquired = _committee_type_doc(tmp_path)
    resource = fec.parse_committee_type_codes(acquired)

    bundle = fec.build_fec_committee_code_package("committeeType", resource, acquired)
    destination = tmp_path / "package"
    bundle.write_to(destination)

    reopened = SourceControlledResourceView.open(destination)
    assert reopened.resource_manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in reopened.resource_manifest
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["conceptIdentityClaimed"] is False
    assert "acceptedOutputUseAuthorized" not in reopened.resource_manifest
    assert len(reopened.observations) == 16


def test_package_rejects_an_unknown_resource_family(tmp_path: Path) -> None:
    acquired = _committee_type_doc(tmp_path)
    resource = fec.parse_committee_type_codes(acquired)

    with pytest.raises(fec.FECPackageError, match="unknown"):
        fec.build_fec_committee_code_package("reportTypes", resource, acquired)

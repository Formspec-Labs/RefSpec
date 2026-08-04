"""Official FAC data dictionary capture, parsing, and package tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import fac_dictionary as fac
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "fac_dictionary"
DOC_FIXTURE = FIXTURES / "fac-api-dictionary-2026-08-03.html"


def _acquire(tmp_path: Path, source_path: Path = DOC_FIXTURE) -> fac.AcquiredFACSource:
    return fac.acquire_fac_dictionary_doc(
        fac.FAC_DICTIONARY_DOC_2026_08_03,
        tmp_path,
        source_path=source_path,
    )


def _portfolio(tmp_path: Path) -> fac.FACDictionaryPortfolio:
    return fac.parse_fac_dictionary(_acquire(tmp_path))


def test_live_snapshot_pin_matches_exact_official_html_bytes() -> None:
    payload = DOC_FIXTURE.read_bytes()

    assert len(payload) == 74_851
    assert fac.sha256_digest(payload) == ("sha256:95799a6f28b2f9a4d48bb0a88a1429381f2bc6e0677a9ec3a6608aa46a5a369c")
    assert payload.startswith(b"<!DOCTYPE html>")


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = fac.FAC_DICTIONARY_DOC_2026_08_03

    acquired = _acquire(tmp_path)
    cached = fac.acquire_fac_dictionary_doc(pin, tmp_path)

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
        ) -> fac.FetchedFACResponse:
            calls.append((source_url, timeout_seconds))
            return fac.FetchedFACResponse(
                body=payload,
                status_code=200,
                content_type="text/html; charset=utf-8",
                resolved_url=source_url,
            )

    acquired = fac.acquire_fac_dictionary_doc(
        fac.FAC_DICTIONARY_DOC_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=21.0,
    )

    assert calls == [(fac.FAC_DICTIONARY_DOC_SOURCE.source_url, 21.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_endpoints_match_the_documented_dictionary_order_and_field_counts(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.endpoints == (
        "general",
        "federal_awards",
        "notes_to_sefa",
        "findings",
        "findings_text",
        "corrective_action_plans",
        "passthrough",
        "secondary_auditors",
        "additional_ueis",
        "additional_eins",
        "resubmission",
    )
    # 163 distinct (endpoint, field) rows; the general table repeats one row
    # (fac_accepted_date) identically, which collapses rather than erroring.
    assert len(portfolio.fields) == 163
    assert len(portfolio.fields_by_endpoint("general")) == 63
    assert len(portfolio.fields_by_endpoint("federal_awards")) == 22
    assert len(portfolio.fields_by_endpoint("findings")) == 15


def test_field_definitions_carry_legacy_census_mapping_and_data_type(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    report_id = portfolio.field("general", "report_id")
    assert report_id.legacy_census_field == "AUDITYEAR + DBKEY"
    assert report_id.data_type == "TEXT"
    assert report_id.formerly_endpoint == "gen"

    amount = portfolio.field("federal_awards", "amount_expended")
    assert amount.legacy_census_field == "AMOUNT"
    assert amount.data_type == "BIGINT"

    requirement = portfolio.field("findings", "type_requirement")
    assert requirement.legacy_census_field == "TYPEREQUIREMENT"
    assert requirement.data_type == "TEXT"

    finding_text = portfolio.field("findings_text", "finding_text")
    assert finding_text.legacy_census_field == "TEXT"
    assert finding_text.data_type == "TEXT"

    # resubmission is a GSA-only endpoint; every field lacks a legacy mapping.
    version = portfolio.field("resubmission", "version")
    assert version.legacy_census_field is None
    assert version.data_type == "BIGINT"

    compound = portfolio.field(
        "federal_awards",
        "federal_agency_prefix + federal_award_extension",
    )
    assert compound.legacy_census_field == "CFDA"


def test_fields_are_deterministic_metadata_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert all(field.use == "deterministicMetadata" for field in portfolio.fields)
    assert all(not field.is_general_subject_concept for field in portfolio.fields)

    identifier = portfolio.field("general", "entity_type").identifiers[0]
    assert identifier.kind == "facApiFieldName"
    assert identifier.value == "entity_type"
    assert identifier.authority_uri == fac.FAC_IDENTIFIER_AUTHORITY_URI
    assert identifier.source_digest == fac.FAC_DICTIONARY_DOC_2026_08_03.expected_sha256


def test_gaps_document_missing_requirement_code_values_and_field_only_scope(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert any("OMB Compliance Supplement" in gap for gap in portfolio.gaps)
    assert any("audit_year" in gap for gap in portfolio.gaps)
    assert any("does not publish" in gap for gap in portfolio.gaps)


def test_reference_finding_requirement_code_requires_and_records_audit_year(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    reference = fac.reference_finding_requirement_code(
        {"type_requirement": "A", "audit_year": "2024"},
        portfolio,
    )

    assert reference.code == "A"
    assert reference.audit_year == "2024"
    assert reference.field.gsa_field == "type_requirement"
    assert "2024 OMB Compliance Supplement" in reference.gap

    with pytest.raises(fac.FACAssignmentError, match="audit_year"):
        fac.reference_finding_requirement_code({"type_requirement": "A"}, portfolio)

    with pytest.raises(fac.FACAssignmentError, match="audit_year"):
        fac.reference_finding_requirement_code(
            {"type_requirement": "A", "audit_year": "24"},
            portfolio,
        )

    with pytest.raises(fac.FACAssignmentError, match="type_requirement"):
        fac.reference_finding_requirement_code({"audit_year": "2024"}, portfolio)


def test_validate_fac_field_reference_fails_closed_for_unknown_field(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    found = fac.validate_fac_field_reference("general", "auditee_name", portfolio)
    assert found.data_type == "TEXT"

    with pytest.raises(fac.FACAssignmentError, match="unknown FAC endpoint"):
        fac.validate_fac_field_reference("submissions", "auditee_name", portfolio)

    with pytest.raises(fac.FACAssignmentError, match="unknown FAC field"):
        fac.validate_fac_field_reference("general", "auditee_planet", portfolio)


def test_digest_drift_never_becomes_a_parsed_portfolio(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    changed = payload.replace(b"entity_type", b"entitY_type", 1)
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> fac.FetchedFACResponse:
            del timeout_seconds
            return fac.FetchedFACResponse(
                body=changed,
                status_code=200,
                content_type="text/html",
                resolved_url=source_url,
            )

    with pytest.raises(fac.FACSourceDriftError, match="digest drift"):
        fac.acquire_fac_dictionary_doc(
            fac.FAC_DICTIONARY_DOC_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )


def test_shape_drift_in_endpoint_list_fails_loudly(tmp_path: Path) -> None:
    mini_html = (
        b"<!DOCTYPE html><html><body>"
        b"<h2>Dictionary by endpoint</h2>"
        b'<ol><li><a href="#endpoint-general">general</a></li></ol>'
        b'<h3 id="endpoint-general">Endpoint: <code>general</code> (formerly <code>gen)</h3>'
        b'<table class="usa-table"><thead><tr><th scope="col">Census</th>'
        b'<th scope="col">GSA</th><th scope="col">Data type</th></tr></thead><tbody>'
        b'<tr><td>AUDITYEAR + DBKEY</td><th scope="row">report_id</th><td>TEXT</td></tr>'
        b"</tbody></table>"
        b"</body></html>"
    )
    mini_pin = fac.FACSnapshotPin(
        source=fac.FAC_DICTIONARY_DOC_SOURCE,
        retrieved_at="2026-08-03T19:25:31Z",
        expected_sha256=fac.sha256_digest(mini_html),
        expected_byte_length=len(mini_html),
    )
    mini_path = tmp_path / "mini.html"
    mini_path.write_bytes(mini_html)

    acquired = fac.acquire_fac_dictionary_doc(mini_pin, tmp_path / "store", source_path=mini_path)

    with pytest.raises(fac.FACSourceDriftError, match="endpoint"):
        fac.parse_fac_dictionary(acquired)


def test_conflicting_duplicate_field_row_fails_loudly(tmp_path: Path) -> None:
    payload = DOC_FIXTURE.read_bytes()
    # Corrupt the second (duplicate) fac_accepted_date row in the general
    # table so it disagrees with the first instead of repeating it exactly.
    changed = payload.replace(
        b'<td>FACACCEPTEDDATE</td>\n<th scope="row">fac_accepted_date</th>\n<td>DATE</td>',
        b'<td>FACACCEPTEDDATE</td>\n<th scope="row">fac_accepted_date</th>\n<td>TEXT</td>',
        1,
    )
    assert changed != payload
    assert len(changed) == len(payload)
    mini_pin = fac.FACSnapshotPin(
        source=fac.FAC_DICTIONARY_DOC_SOURCE,
        retrieved_at="2026-08-03T19:25:31Z",
        expected_sha256=fac.sha256_digest(changed),
        expected_byte_length=len(changed),
    )
    changed_path = tmp_path / "changed.html"
    changed_path.write_bytes(changed)

    acquired = fac.acquire_fac_dictionary_doc(mini_pin, tmp_path / "store", source_path=changed_path)

    with pytest.raises(fac.FACSourceDriftError, match="conflict"):
        fac.parse_fac_dictionary(acquired)


def test_package_round_trips_through_a_closed_source_controlled_resource(
    tmp_path: Path,
) -> None:
    acquired = _acquire(tmp_path)
    portfolio = _portfolio(tmp_path)

    bundle = fac.build_fac_dictionary_package("findings", portfolio, acquired)
    destination = tmp_path / "package"
    bundle.write_to(destination)

    reopened = SourceControlledResourceView.open(destination)
    assert reopened.resource_manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in reopened.resource_manifest
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["conceptIdentityClaimed"] is False
    assert "acceptedOutputUseAuthorized" not in reopened.resource_manifest
    assert len(reopened.observations) == 15

    requirement_observations = [
        observation for observation in reopened.observations if observation["gsaField"] == "type_requirement"
    ]
    assert len(requirement_observations) == 1
    assert requirement_observations[0]["dataType"] == "TEXT"


def test_package_rejects_an_unknown_endpoint(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    portfolio = _portfolio(tmp_path)

    with pytest.raises(fac.FACPackageError, match="unknown"):
        fac.build_fac_dictionary_package("submissions", portfolio, acquired)

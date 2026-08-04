"""Official GovInfo collection code and eCFR structural value capture tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import govinfo_collections as gc
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_collections"
COLLECTIONS_FIXTURE = FIXTURES / "govinfo-collections-2026-08-03.json"
TITLES_FIXTURE = FIXTURES / "ecfr-cfr-titles-2026-08-03.json"
PACKAGE_SUMMARY_FIXTURE = FIXTURES / "govinfo-package-summary-cfr-2023-title1-vol1-2026-08-03.json"
PACKAGE_PREMIS_FIXTURE = FIXTURES / "govinfo-premis-cfr-2023-title1-vol1-mini-2026-08-03.xml"


def _acquire(
    tmp_path: Path,
    pin: gc.GovInfoSnapshotPin,
    source_path: Path,
) -> gc.AcquiredGovInfoSource:
    return gc.acquire_govinfo_source(pin, tmp_path, source_path=source_path)


def _portfolio(tmp_path: Path) -> gc.GovInfoControlPortfolio:
    collections = gc.parse_govinfo_collections(
        _acquire(tmp_path, gc.GOVINFO_COLLECTIONS_2026_08_03, COLLECTIONS_FIXTURE)
    )
    titles = gc.parse_ecfr_cfr_titles(_acquire(tmp_path, gc.ECFR_CFR_TITLES_2026_08_03, TITLES_FIXTURE))
    summary = gc.parse_govinfo_cfr_package_summary(
        _acquire(tmp_path, gc.GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03, PACKAGE_SUMMARY_FIXTURE)
    )
    fixity = gc.parse_govinfo_cfr_package_fixity(
        _acquire(tmp_path, gc.GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03, PACKAGE_PREMIS_FIXTURE),
        expected_package_id=gc.GOVINFO_CFR_PACKAGE_ID,
    )
    return gc.assemble_govinfo_control_portfolio(collections, titles, summary, fixity)


def test_live_snapshot_pins_match_exact_captured_bytes() -> None:
    collections = COLLECTIONS_FIXTURE.read_bytes()
    titles = TITLES_FIXTURE.read_bytes()
    summary = PACKAGE_SUMMARY_FIXTURE.read_bytes()
    premis = PACKAGE_PREMIS_FIXTURE.read_bytes()

    assert len(collections) == 4_803
    assert gc.sha256_digest(collections) == gc.GOVINFO_COLLECTIONS_2026_08_03.expected_sha256
    assert len(titles) == 8_033
    assert gc.sha256_digest(titles) == gc.ECFR_CFR_TITLES_2026_08_03.expected_sha256
    assert len(summary) == 1_532
    assert gc.sha256_digest(summary) == gc.GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03.expected_sha256
    assert len(premis) == 4_268
    assert gc.sha256_digest(premis) == gc.GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03.expected_sha256


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = gc.GOVINFO_COLLECTIONS_2026_08_03

    acquired = _acquire(tmp_path, pin, COLLECTIONS_FIXTURE)
    cached = gc.acquire_govinfo_source(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = TITLES_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> gc.FetchedGovInfoResponse:
            calls.append((source_url, timeout_seconds))
            return gc.FetchedGovInfoResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    acquired = gc.acquire_govinfo_source(
        gc.ECFR_CFR_TITLES_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=11.0,
    )

    assert calls == [(gc.ECFR_CFR_TITLES.source_url, 11.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_fetcher_resolved_url_must_stay_on_the_official_host(tmp_path: Path) -> None:
    payload = COLLECTIONS_FIXTURE.read_bytes()

    class RedirectingFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> gc.FetchedGovInfoResponse:
            del timeout_seconds
            return gc.FetchedGovInfoResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url="https://example.com/collections",
            )

    with pytest.raises(gc.GovInfoAcquisitionError, match="official"):
        gc.acquire_govinfo_source(
            gc.GOVINFO_COLLECTIONS_2026_08_03,
            tmp_path,
            fetcher=RedirectingFetcher(),
        )


def test_govinfo_collection_codes_are_deterministic_metadata_not_general_subject_concepts(
    tmp_path: Path,
) -> None:
    resource = gc.parse_govinfo_collections(_acquire(tmp_path, gc.GOVINFO_COLLECTIONS_2026_08_03, COLLECTIONS_FIXTURE))

    assert len(resource.collections) == 42
    cfr = resource.by_code()["CFR"]
    assert cfr.collection_name == "Code of Federal Regulations"
    assert cfr.package_count == 6_629
    assert cfr.granule_count == 7_799_699
    assert cfr.is_general_subject_concept is False
    assert [identifier.value for identifier in cfr.identifiers] == ["CFR"]
    assert cfr.identifiers[0].kind == "govInfoCollectionCode"
    assert cfr.identifiers[0].authority_uri == gc.GOVINFO_IDENTIFIER_AUTHORITY_URI
    ecfr = resource.by_code()["ECFR"]
    assert ecfr.granule_count is None
    assert all(not entry.is_general_subject_concept for entry in resource.collections)


def test_ecfr_cfr_titles_retain_version_fields_and_reserved_flag_not_subjects(
    tmp_path: Path,
) -> None:
    resource = gc.parse_ecfr_cfr_titles(_acquire(tmp_path, gc.ECFR_CFR_TITLES_2026_08_03, TITLES_FIXTURE))

    assert len(resource.titles) == 50
    assert resource.as_of_date == "2026-07-30"
    assert resource.import_in_progress is False
    title_one = resource.by_number()[1]
    assert title_one.name == "General Provisions"
    assert title_one.reserved is False
    assert title_one.up_to_date_as_of == "2026-07-30"
    assert title_one.identifiers[0].value == "1"
    assert title_one.identifiers[0].kind == "ecfrCfrTitleNumber"
    reserved_title = resource.by_number()[35]
    assert reserved_title.reserved is True
    assert reserved_title.latest_amended_on is None
    assert reserved_title.latest_issue_date is None
    assert all(not title.is_general_subject_concept for title in resource.titles)


def test_govinfo_cfr_package_summary_retains_identity_and_version_fields(
    tmp_path: Path,
) -> None:
    summary = gc.parse_govinfo_cfr_package_summary(
        _acquire(tmp_path, gc.GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03, PACKAGE_SUMMARY_FIXTURE)
    )

    assert summary.package_id == "CFR-2023-title1-vol1"
    assert summary.collection_code == "CFR"
    assert summary.title_number == 1
    assert summary.date_issued == "2023-01-01"
    assert summary.last_modified == "2025-05-21T06:24:19Z"
    assert summary.doc_class == "CFR"
    assert summary.sudoc_class_number == "AE 2.106/3:1/"
    assert set(summary.download_links) == {
        "premisLink",
        "xmlLink",
        "txtLink",
        "zipLink",
        "modsLink",
        "pdfLink",
    }
    assert summary.download_links["premisLink"] == gc.GOVINFO_CFR_PACKAGE_PREMIS.source_url
    assert summary.is_general_subject_concept is False


def test_govinfo_cfr_package_fixity_retains_premis_sha256_digests(
    tmp_path: Path,
) -> None:
    fixity = gc.parse_govinfo_cfr_package_fixity(
        _acquire(tmp_path, gc.GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03, PACKAGE_PREMIS_FIXTURE),
        expected_package_id=gc.GOVINFO_CFR_PACKAGE_ID,
    )

    assert fixity.package_id == "CFR-2023-title1-vol1"
    assert len(fixity.records) == 2
    by_name = {record.original_name: record for record in fixity.records}
    html_record = by_name["CFR-2023-title1-vol1.htm"]
    assert html_record.algorithm == "SHA-256"
    assert html_record.digest == "7321767f07828dc822e81e9806a33280cb2860d4281ac91f1bc79439b1cfcb33"
    assert html_record.content_location_uri == (
        "https://www.govinfo.gov/content/pkg/CFR-2023-title1-vol1/html/CFR-2023-title1-vol1.htm"
    )
    assert html_record.identifiers[0].kind == "govInfoPremisSha256Fixity"
    assert html_record.identifiers[0].value == html_record.digest
    assert all(not record.is_general_subject_concept for record in fixity.records)


def test_portfolio_cross_validates_package_against_collections_and_titles(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio(tmp_path)

    assert portfolio.cfr_hierarchy_level_types == (
        "appendix",
        "chapter",
        "hed1",
        "part",
        "section",
        "subchapter",
        "subject_group",
        "subpart",
        "title",
    )
    assert portfolio.cfr_package_summary.collection_code in portfolio.collections.by_code()
    assert portfolio.cfr_package_summary.title_number in portfolio.cfr_titles.by_number()
    assert portfolio.cfr_package_fixity.package_id == portfolio.cfr_package_summary.package_id
    assert any("does not publish a standalone constants endpoint" in gap for gap in portfolio.gaps)
    assert any("only certifies" in gap for gap in portfolio.gaps)


def test_validators_resolve_known_codes_and_titles(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    collection = gc.validate_collection_code("CFR", portfolio)
    assert collection.collection_name == "Code of Federal Regulations"
    title = gc.validate_cfr_title_number(1, portfolio)
    assert title.name == "General Provisions"


def test_unknown_collection_or_title_reference_fails_closed(tmp_path: Path) -> None:
    portfolio = _portfolio(tmp_path)

    with pytest.raises(gc.GovInfoAssignmentError, match="unknown GovInfo collection code"):
        gc.validate_collection_code("NOTREAL", portfolio)
    with pytest.raises(gc.GovInfoAssignmentError, match="unknown eCFR title number"):
        gc.validate_cfr_title_number(999, portfolio)


def test_assembly_fails_closed_when_package_references_unknown_collection_or_title(
    tmp_path: Path,
) -> None:
    collections = gc.parse_govinfo_collections(
        _acquire(tmp_path, gc.GOVINFO_COLLECTIONS_2026_08_03, COLLECTIONS_FIXTURE)
    )
    titles = gc.parse_ecfr_cfr_titles(_acquire(tmp_path, gc.ECFR_CFR_TITLES_2026_08_03, TITLES_FIXTURE))
    summary = gc.parse_govinfo_cfr_package_summary(
        _acquire(tmp_path, gc.GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03, PACKAGE_SUMMARY_FIXTURE)
    )
    fixity = gc.parse_govinfo_cfr_package_fixity(
        _acquire(tmp_path, gc.GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03, PACKAGE_PREMIS_FIXTURE),
        expected_package_id=gc.GOVINFO_CFR_PACKAGE_ID,
    )

    with pytest.raises(gc.GovInfoAssignmentError, match="unknown GovInfo collection code"):
        gc.assemble_govinfo_control_portfolio(
            collections,
            titles,
            replace(summary, collection_code="NOTREAL"),
            fixity,
        )
    with pytest.raises(gc.GovInfoAssignmentError, match="unknown eCFR title number"):
        gc.assemble_govinfo_control_portfolio(
            collections,
            titles,
            replace(summary, title_number=999),
            fixity,
        )
    with pytest.raises(gc.GovInfoAssignmentError, match="package identity"):
        gc.assemble_govinfo_control_portfolio(
            collections,
            titles,
            summary,
            replace(fixity, package_id="CFR-2023-title2-vol1"),
        )


def test_digest_or_unknown_shape_drift_never_becomes_a_parsed_resource(
    tmp_path: Path,
) -> None:
    payload = COLLECTIONS_FIXTURE.read_bytes()
    changed = payload.replace(b'"Annual Reports"', b'"Annual Reportz"')
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(
            self,
            source_url: str,
            *,
            timeout_seconds: float,
        ) -> gc.FetchedGovInfoResponse:
            del timeout_seconds
            return gc.FetchedGovInfoResponse(
                body=changed,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    with pytest.raises(gc.GovInfoSourceDriftError, match="digest drift"):
        gc.acquire_govinfo_source(
            gc.GOVINFO_COLLECTIONS_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = b'{"collections":[{"collectionCode":"CFR","collectionName":"Code of Federal Regulations"}]}'
    mini_source = replace(gc.GOVINFO_COLLECTIONS, filename="mini-collections.json")
    mini_pin = gc.GovInfoSnapshotPin(
        source=mini_source,
        retrieved_at="2026-08-03T19:15:00Z",
        expected_sha256=gc.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
    )
    mini_path = tmp_path / "mini.json"
    mini_path.write_bytes(mini_payload)
    acquired = gc.acquire_govinfo_source(
        mini_pin,
        tmp_path / "shape",
        source_path=mini_path,
    )
    with pytest.raises(gc.GovInfoSourceDriftError, match="fields"):
        gc.parse_govinfo_collections(acquired)


def test_parser_rejects_malformed_collection_code_and_fixity_digest(
    tmp_path: Path,
) -> None:
    bad_code_payload = (
        b'{"collections":[{"collectionCode":"cfr","collectionName":"x","packageCount":1,"granuleCount":null}]}'
    )
    bad_code_source = replace(gc.GOVINFO_COLLECTIONS, filename="bad-code.json")
    bad_code_pin = gc.GovInfoSnapshotPin(
        source=bad_code_source,
        retrieved_at="2026-08-03T19:15:00Z",
        expected_sha256=gc.sha256_digest(bad_code_payload),
        expected_byte_length=len(bad_code_payload),
    )
    bad_code_path = tmp_path / "bad-code.json"
    bad_code_path.write_bytes(bad_code_payload)
    acquired = gc.acquire_govinfo_source(bad_code_pin, tmp_path / "store1", source_path=bad_code_path)
    with pytest.raises(gc.GovInfoSourceDriftError, match="collection code"):
        gc.parse_govinfo_collections(acquired)

    bad_fixity_xml = PACKAGE_PREMIS_FIXTURE.read_bytes().replace(
        b"7321767f07828dc822e81e9806a33280cb2860d4281ac91f1bc79439b1cfcb33",
        b"not-a-real-digest",
    )
    bad_fixity_source = replace(gc.GOVINFO_CFR_PACKAGE_PREMIS, filename="bad-fixity.xml")
    bad_fixity_pin = gc.GovInfoSnapshotPin(
        source=bad_fixity_source,
        retrieved_at="2026-08-03T19:15:00Z",
        expected_sha256=gc.sha256_digest(bad_fixity_xml),
        expected_byte_length=len(bad_fixity_xml),
    )
    bad_fixity_path = tmp_path / "bad-fixity.xml"
    bad_fixity_path.write_bytes(bad_fixity_xml)
    acquired_fixity = gc.acquire_govinfo_source(bad_fixity_pin, tmp_path / "store2", source_path=bad_fixity_path)
    with pytest.raises(gc.GovInfoSourceDriftError, match="digest"):
        gc.parse_govinfo_cfr_package_fixity(acquired_fixity, expected_package_id=gc.GOVINFO_CFR_PACKAGE_ID)


def test_collection_codes_bundle_builds_a_deterministic_closed_package(
    tmp_path: Path,
) -> None:
    bundle_one = gc.build_govinfo_collections_package(COLLECTIONS_FIXTURE)
    bundle_two = gc.build_govinfo_collections_package(COLLECTIONS_FIXTURE)

    assert bundle_one.artifact_bytes() == bundle_two.artifact_bytes()
    assert bundle_one.resource_manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in bundle_one.resource_manifest
    assert bundle_one.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle_one.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle_one.resource_manifest["observationCount"] == 42

    destination = tmp_path / "package"
    bundle_one.write_to(destination)
    reopened = SourceControlledResourceView.open(destination)

    assert reopened.logical_digest == bundle_one.logical_digest
    assert len(reopened.observations) == 42

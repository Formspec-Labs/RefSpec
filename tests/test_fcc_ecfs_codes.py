"""FCC ECFS filing-record code capture, parsing, and packaging tests.

The FCC ECFS public API (https://www.fcc.gov/ecfs/help/public_api) publishes
no dedicated code-list or constants endpoint. Filing-type, access-status, and
bureau values are observed only as fields embedded on live filing search
records, and proceeding identity is observed the same way. These tests use
one pinned, byte-exact filing search capture and never open a live network
connection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.registry import fcc_ecfs_codes as fcc

FIXTURES = Path(__file__).parent / "fixtures" / "fcc_ecfs_codes"
FILINGS_FIXTURE = FIXTURES / "fcc-ecfs-filings-2026-08-03.json"


def _acquire(tmp_path: Path, pin: fcc.FCCECFSSnapshotPin, source_path: Path) -> fcc.AcquiredFCCECFSSnapshot:
    return fcc.acquire_fcc_ecfs_snapshot(pin, tmp_path, source_path=source_path)


def _parsed(tmp_path: Path) -> fcc.ParsedFCCECFSSnapshot:
    return fcc.parse_fcc_ecfs_snapshot(_acquire(tmp_path, fcc.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03, FILINGS_FIXTURE))


def test_live_snapshot_pin_matches_exact_official_json_bytes() -> None:
    payload = FILINGS_FIXTURE.read_bytes()

    assert len(payload) == 51_284
    assert fcc.sha256_digest(payload) == ("sha256:4393e9c73ab5e12e25c79a707ca85856ba1d9cc1c3eccdfdfa235223f17773da")
    assert fcc.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03.expected_byte_length == 51_284
    assert fcc.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03.expected_filing_count == 25


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = fcc.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03

    acquired = _acquire(tmp_path, pin, FILINGS_FIXTURE)
    cached = fcc.acquire_fcc_ecfs_snapshot(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = FILINGS_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> fcc.FetchedFCCECFSResponse:
            calls.append((source_url, timeout_seconds))
            return fcc.FetchedFCCECFSResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    acquired = fcc.acquire_fcc_ecfs_snapshot(
        fcc.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=17.0,
    )

    assert calls == [(fcc.FCC_ECFS_FILINGS_SNAPSHOT.source_url, 17.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_filing_types_are_deterministic_metadata_not_subjects(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)

    assert len(parsed.filing_types) == 6
    by_code = parsed.by_primary_code("filingTypes")
    comment = by_code["CO"]
    assert comment.publisher_label == "COMMENT"
    assert comment.use == "deterministicMetadata"
    assert comment.is_general_subject_concept is False
    assert [identifier.kind for identifier in comment.identifiers] == [
        "filingTypeAbbreviation",
        "publisherRecordId",
    ]
    assert comment.identifiers[1].value == "7"
    assert by_code["NP"].publisher_label == "NOTICE OF PROPOSED RULEMAKING"
    assert all(not code.is_general_subject_concept for code in parsed.filing_types)


def test_access_statuses_bureaus_and_proceedings_are_captured(tmp_path: Path) -> None:
    parsed = _parsed(tmp_path)

    assert len(parsed.access_statuses) == 1
    unrestricted = parsed.by_primary_code("accessStatuses")["10"]
    assert unrestricted.publisher_label == "Unrestricted"
    assert unrestricted.use == "deterministicMetadata"

    assert len(parsed.bureaus) == 5
    pshsb = parsed.by_primary_code("bureaus")["PSHSB"]
    assert pshsb.publisher_label == "Public Safety & Homeland Security Bureau"

    assert len(parsed.proceedings) == 15
    proceeding = parsed.by_primary_code("proceedings")["26-189"]
    assert proceeding.publisher_label == (
        "Prohibiting the Importation and Marketing of Certain Foreign-Produced Military-Grade "
        "UAS and UAS Critical Components"
    )
    assert [identifier.kind for identifier in proceeding.identifiers] == [
        "proceedingNumber",
        "publisherRecordId",
        "bureauCode",
    ]
    assert proceeding.identifiers[2].value == "PSHSB"
    assert all(not code.is_general_subject_concept for code in (*parsed.bureaus, *parsed.proceedings))


def test_shape_drift_never_becomes_a_parsed_snapshot(tmp_path: Path) -> None:
    payload = FILINGS_FIXTURE.read_bytes()
    changed = payload.replace(b'"COMMENT"', b'"COMMENTS"', 1)
    assert len(changed) != len(payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> fcc.FetchedFCCECFSResponse:
            del timeout_seconds
            return fcc.FetchedFCCECFSResponse(
                body=changed,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    with pytest.raises(fcc.FCCECFSSourceDriftError, match="byte length drift"):
        fcc.acquire_fcc_ecfs_snapshot(
            fcc.FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03,
            tmp_path,
            fetcher=ChangedFetcher(),
        )

    mini_payload = (
        b'{"filing":[{"id_submission":"1","submissiontype":{"id":7,"description":"COMMENT",'
        b'"short":"COMMENT","slug":"comment"},"viewingstatus":{"id":10,"description":"Unrestricted"},'
        b'"proceedings":[]}],"aggregations":{}}'
    )
    mini_pin = fcc.FCCECFSSnapshotPin(
        source=fcc.FCC_ECFS_FILINGS_SNAPSHOT,
        retrieved_at="2026-08-03T19:20:00Z",
        expected_sha256=fcc.sha256_digest(mini_payload),
        expected_byte_length=len(mini_payload),
        expected_filing_count=1,
    )
    mini_path = tmp_path / "mini.json"
    mini_path.write_bytes(mini_payload)
    acquired = fcc.acquire_fcc_ecfs_snapshot(mini_pin, tmp_path / "shape", source_path=mini_path)
    with pytest.raises(fcc.FCCECFSSourceDriftError, match="fields drifted"):
        fcc.parse_fcc_ecfs_snapshot(acquired)


def test_conflicting_observations_of_the_same_code_fail_closed(tmp_path: Path) -> None:
    template = FILINGS_FIXTURE.read_text(encoding="utf-8")
    # "CO" (id 7) recurs across several filings; changing only its first
    # occurrence's description creates a genuine same-code conflict instead
    # of a harmless single-occurrence relabel.
    conflicting = template.replace(
        '"description":"COMMENT","short":"COMMENT","id":7,"abbreviation":"CO"',
        '"description":"COMMENTARY","short":"COMMENT","id":7,"abbreviation":"CO"',
        1,
    )
    payload = conflicting.encode("utf-8")
    assert payload != FILINGS_FIXTURE.read_bytes()

    pin = fcc.FCCECFSSnapshotPin(
        source=fcc.FCC_ECFS_FILINGS_SNAPSHOT,
        retrieved_at="2026-08-03T19:20:00Z",
        expected_sha256=fcc.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_filing_count=25,
    )
    source_path = tmp_path / "conflicting.json"
    source_path.write_bytes(payload)
    acquired = fcc.acquire_fcc_ecfs_snapshot(pin, tmp_path / "store", source_path=source_path)

    with pytest.raises(fcc.FCCECFSSourceDriftError, match="conflicting"):
        fcc.parse_fcc_ecfs_snapshot(acquired)


def test_builds_four_distinct_controlled_code_list_packages() -> None:
    filing_types = fcc.build_fcc_ecfs_filing_type_package(FILINGS_FIXTURE)
    access_statuses = fcc.build_fcc_ecfs_access_status_package(FILINGS_FIXTURE)
    bureaus = fcc.build_fcc_ecfs_bureau_package(FILINGS_FIXTURE)
    proceedings = fcc.build_fcc_ecfs_proceeding_package(FILINGS_FIXTURE)

    assert filing_types.resource_manifest["schemaVersion"] == "2.0"
    assert "candidateUseAuthorized" not in filing_types.resource_manifest
    assert filing_types.resource_manifest == {
        **filing_types.resource_manifest,
        "resourceId": "fcc-ecfs-filing-types-2026-08-03",
        "resourceKind": "controlledCodeList",
        "identityStatus": "publisherIdentifiersPreserved",
        "conceptIdentityClaimed": False,
        "uses": ("deterministicMetadata",),
        "observationCount": 6,
    }
    assert access_statuses.resource_manifest["observationCount"] == 1
    assert bureaus.resource_manifest["observationCount"] == 5
    assert proceedings.resource_manifest["observationCount"] == 15

    ids = {
        filing_types.resource_manifest["id"],
        access_statuses.resource_manifest["id"],
        bureaus.resource_manifest["id"],
        proceedings.resource_manifest["id"],
    }
    assert len(ids) == 4

    assert filing_types.logical_digest == fcc.FCC_ECFS_FILING_TYPE_PACKAGE.expected_logical_digest
    assert access_statuses.logical_digest == fcc.FCC_ECFS_ACCESS_STATUS_PACKAGE.expected_logical_digest
    assert bureaus.logical_digest == fcc.FCC_ECFS_BUREAU_PACKAGE.expected_logical_digest
    assert proceedings.logical_digest == fcc.FCC_ECFS_PROCEEDING_PACKAGE.expected_logical_digest


def test_coverage_report_records_excluded_duplicates_and_known_gaps() -> None:
    filing_types = fcc.build_fcc_ecfs_filing_type_package(FILINGS_FIXTURE)
    proceedings = fcc.build_fcc_ecfs_proceeding_package(FILINGS_FIXTURE)

    assert filing_types.coverage_report["sourceObservedCount"] == 25
    assert filing_types.coverage_report["packagedCount"] == 6
    assert filing_types.coverage_report["excludedCount"] == 19
    assert filing_types.coverage_report["failedCount"] == 0
    assert filing_types.coverage_report["reportStatus"] == "gap"

    assert proceedings.coverage_report["sourceObservedCount"] == 40
    assert proceedings.coverage_report["packagedCount"] == 15
    assert proceedings.coverage_report["excludedCount"] == 25

    gap_kinds = {gap["kind"] for gap in filing_types.coverage_report["gaps"]}
    assert gap_kinds == {"dedicatedCodeListEndpointUnavailable", "observedSetNotExhaustive"}


def test_generation_is_byte_deterministic() -> None:
    for builder in (
        fcc.build_fcc_ecfs_filing_type_package,
        fcc.build_fcc_ecfs_access_status_package,
        fcc.build_fcc_ecfs_bureau_package,
        fcc.build_fcc_ecfs_proceeding_package,
    ):
        first = builder(FILINGS_FIXTURE)
        second = builder(FILINGS_FIXTURE)

        assert first.artifact_bytes() == second.artifact_bytes()
        assert first.logical_digest == second.logical_digest


def test_package_reopens_and_supports_exact_code_lookup(tmp_path: Path) -> None:
    built = fcc.build_fcc_ecfs_bureau_package(FILINGS_FIXTURE)
    package_path = built.write_to(tmp_path / "bureaus")

    reopened = fcc.FCCECFSCodeListView.open(package_path)

    assert reopened.spec is fcc.FCC_ECFS_BUREAU_PACKAGE
    assert len(reopened.observations_by_code) == 5
    assert reopened.lookup_code("PSHSB")["labels"][0]["value"] == ("Public Safety & Homeland Security Bureau")
    assert reopened.lookup_code("ZZZZ") is None


def test_source_drift_cannot_produce_a_new_package(tmp_path: Path) -> None:
    payload = FILINGS_FIXTURE.read_bytes().replace(b'"Unrestricted"', b'"unrestricted"')
    assert len(payload) == len(FILINGS_FIXTURE.read_bytes())
    changed = tmp_path / "changed.json"
    changed.write_bytes(payload)

    with pytest.raises(fcc.FCCECFSSourceDriftError, match="digest drift"):
        fcc.build_fcc_ecfs_access_status_package(changed)


def test_reader_rejects_a_self_consistent_unpinned_repackage(tmp_path: Path) -> None:
    from refspec.registry.infrastructure.source_controlled_resource import (
        build_source_controlled_resource_bundle,
    )

    original = fcc.build_fcc_ecfs_access_status_package(FILINGS_FIXTURE)
    repackaged = build_source_controlled_resource_bundle(
        resource_id=fcc.FCC_ECFS_ACCESS_STATUS_PACKAGE.resource_id,
        title=fcc.FCC_ECFS_ACCESS_STATUS_PACKAGE.title + " (repackaged)",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=fcc.FCC_ECFS_ACCESS_STATUS_PACKAGE.uses,
        captured_at=fcc.FCC_ECFS_ACCESS_STATUS_PACKAGE.pin.retrieved_at,
        observations=original.observations,
        source_artifacts=original.source_artifacts,
        source_observed_count=25,
        excluded_count=24,
        gaps=fcc.FCC_ECFS_ACCESS_STATUS_PACKAGE.known_gaps,
    )
    package_path = repackaged.write_to(tmp_path / "repackaged")

    with pytest.raises(fcc.FCCECFSPackageError, match="external pin"):
        fcc.FCCECFSCodeListView.open(package_path)

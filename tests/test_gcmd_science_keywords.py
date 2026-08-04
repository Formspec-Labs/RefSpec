"""NASA GCMD Science Keywords CSV capture, parsing, and packaging tests."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import gcmd_science_keywords as gcmd
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

FIXTURES = Path(__file__).parent / "fixtures" / "gcmd_science_keywords"
MINI_CSV_FIXTURE = FIXTURES / "gcmd-science-keywords-24.4-mini.csv"
CONCEPT_VERSIONS_FIXTURE = FIXTURES / "concept-versions-published-2026-07-22.xml"


def _mini_pin() -> gcmd.GCMDSnapshotPin:
    payload = MINI_CSV_FIXTURE.read_bytes()
    return gcmd.GCMDSnapshotPin(
        source=gcmd.GCMD_SCIENCE_KEYWORDS_SOURCE,
        retrieved_at="2026-08-03T19:03:43Z",
        expected_sha256=gcmd.sha256_digest(payload),
        expected_byte_length=len(payload),
        expected_keyword_version="24.4",
        expected_revision="2026-07-22T11:07:16.739Z",
        expected_row_count=9,
    )


def _acquire(tmp_path: Path, pin: gcmd.GCMDSnapshotPin, source_path: Path) -> gcmd.AcquiredGCMDSource:
    return gcmd.acquire_gcmd_science_keywords(pin, tmp_path, source_path=source_path)


def _parsed(tmp_path: Path) -> gcmd.ParsedGCMDScienceKeywords:
    pin = _mini_pin()
    return gcmd.parse_gcmd_science_keywords_csv(_acquire(tmp_path, pin, MINI_CSV_FIXTURE))


def test_real_full_release_shape_count_and_boundary_samples(tmp_path: Path) -> None:
    source_path_text = os.environ.get("REFSPEC_GCMD_SCIENCE_KEYWORDS_PATH")
    if source_path_text is None:
        pytest.skip("real GCMD publisher distribution is not configured")
    acquired = _acquire(
        tmp_path,
        gcmd.GCMD_SCIENCE_KEYWORDS_24_4,
        Path(source_path_text),
    )
    parsed = gcmd.parse_gcmd_science_keywords_csv(acquired)

    assert len(parsed.rows) == 3_774
    assert (parsed.rows[0].preferred_label, parsed.rows[0].identifiers[0].value) == (
        "EARTH SCIENCE",
        "e9f67a66-e9fc-435c-b720-ae32a2c3d8f5",
    )
    assert (parsed.rows[-1].preferred_label, parsed.rows[-1].identifiers[0].value) == (
        "WEB PROCESSING SERVICES",
        "933bf0ab-11af-40df-a9d9-1b4a809edd87",
    )


def test_documented_live_pin_matches_the_exact_official_csv_bytes_observed() -> None:
    # This pins the full 24.4 export captured 2026-08-03; the fixture above is
    # a small, byte-faithful excerpt of that same real capture, not this file.
    assert gcmd.GCMD_SCIENCE_KEYWORDS_24_4_BYTE_LENGTH == 504_190
    assert gcmd.GCMD_SCIENCE_KEYWORDS_24_4_SHA256 == (
        "sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2"
    )
    assert gcmd.GCMD_SCIENCE_KEYWORDS_24_4_ROW_COUNT == 3_774
    assert gcmd.GCMD_SCIENCE_KEYWORDS_24_4.expected_sha256 == gcmd.GCMD_SCIENCE_KEYWORDS_24_4_SHA256
    assert gcmd.GCMD_SCIENCE_KEYWORDS_24_4.expected_keyword_version == "24.4"


def test_concept_versions_endpoint_corroborates_the_pinned_scheme_version() -> None:
    payload = CONCEPT_VERSIONS_FIXTURE.read_bytes()

    assert len(payload) == 230
    assert gcmd.sha256_digest(payload) == ("sha256:5e738feb2e3b8f1c68b9e9597ff5ad13b78f6647afc4177bc64a681f8035b614")
    assert b'type="published" creation_date="2026-07-22">24.4<' in payload


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(
    tmp_path: Path,
) -> None:
    pin = _mini_pin()

    acquired = _acquire(tmp_path, pin, MINI_CSV_FIXTURE)
    cached = gcmd.acquire_gcmd_science_keywords(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    pin = _mini_pin()
    payload = MINI_CSV_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gcmd.FetchedGCMDResponse:
            calls.append((source_url, timeout_seconds))
            return gcmd.FetchedGCMDResponse(
                body=payload,
                status_code=200,
                content_type="text/csv",
                resolved_url="https://cmr.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords?format=csv",
            )

    acquired = gcmd.acquire_gcmd_science_keywords(pin, tmp_path, fetcher=Fetcher(), timeout_seconds=13.0)

    assert calls == [(gcmd.GCMD_SCIENCE_KEYWORDS_SOURCE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"
    assert acquired.resolved_url == (
        "https://cmr.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords?format=csv"
    )


def test_fetcher_off_official_host_is_refused(tmp_path: Path) -> None:
    pin = _mini_pin()
    payload = MINI_CSV_FIXTURE.read_bytes()

    class RogueFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gcmd.FetchedGCMDResponse:
            del source_url, timeout_seconds
            return gcmd.FetchedGCMDResponse(
                body=payload,
                status_code=200,
                content_type="text/csv",
                resolved_url="https://evil.example.com/sciencekeywords.csv",
            )

    with pytest.raises(gcmd.GCMDAcquisitionError, match="official HTTPS"):
        gcmd.acquire_gcmd_science_keywords(pin, tmp_path, fetcher=RogueFetcher())


def test_rows_carry_publisher_uuid_identity_and_no_general_subject_promotion(
    tmp_path: Path,
) -> None:
    resource = _parsed(tmp_path)

    assert len(resource.rows) == 9
    assert resource.keyword_version == "24.4"
    assert resource.revision == "2026-07-22T11:07:16.739Z"
    by_uuid = resource.by_uuid()
    aquaculture = by_uuid["8916dafb-5ad5-45c6-ab64-3500ea1e9577"]
    assert aquaculture == gcmd.GCMDKeywordRow(
        category="EARTH SCIENCE",
        topic="AGRICULTURE",
        term="AGRICULTURAL AQUATIC SCIENCES",
        variable_level_1="AQUACULTURE",
        variable_level_2=None,
        variable_level_3=None,
        detailed_variable=None,
        preferred_label="AQUACULTURE",
        identifiers=(
            ControlledIdentifier(
                value="8916dafb-5ad5-45c6-ab64-3500ea1e9577",
                kind="gcmdConceptUUID",
                authority_uri=gcmd.GCMD_IDENTIFIER_AUTHORITY_URI,
                source_uri=gcmd.GCMD_SCIENCE_KEYWORDS_SOURCE.source_url,
                observed_at="2026-08-03T19:03:43Z",
                effective_at=None,
                source_digest=resource.source_sha256,
            ),
        ),
        source_path="csv:row[3]",
        source_ordinal=3,
        is_general_subject_concept=False,
    )
    riming = by_uuid["889253e1-e189-4f75-bdc7-7e612b19e3ae"]
    assert riming.preferred_label == "RIMING"
    assert riming.detailed_variable == "RIMING"
    assert all(not row.is_general_subject_concept for row in resource.rows)
    assert any("SKOS broader/narrower" in gap["reason"] for gap in resource.gaps)
    assert any("Instruments, Platforms" in gap["reason"] for gap in resource.gaps)
    assert any("document-subject value" in gap["reason"] for gap in resource.gaps)


def test_out_of_scope_category_fails_closed(tmp_path: Path) -> None:
    payload = MINI_CSV_FIXTURE.read_bytes().replace(b"EARTH SCIENCE SERVICES", b"INSTRUMENTS AND SENSOR")
    assert len(payload) == len(MINI_CSV_FIXTURE.read_bytes())
    changed = tmp_path / "changed.csv"
    changed.write_bytes(payload)
    pin = replace(
        _mini_pin(),
        expected_sha256=gcmd.sha256_digest(payload),
        expected_byte_length=len(payload),
    )

    with pytest.raises(gcmd.GCMDSourceDriftError, match="out-of-scope category"):
        gcmd.parse_gcmd_science_keywords_csv(_acquire(tmp_path, pin, changed))


def test_scheme_version_drift_fails_closed(tmp_path: Path) -> None:
    payload = MINI_CSV_FIXTURE.read_bytes().replace(b"Keyword Version: 24.4", b"Keyword Version: 24.5")
    assert len(payload) == len(MINI_CSV_FIXTURE.read_bytes())
    changed = tmp_path / "changed.csv"
    changed.write_bytes(payload)
    pin = replace(
        _mini_pin(),
        expected_sha256=gcmd.sha256_digest(payload),
        expected_byte_length=len(payload),
    )

    with pytest.raises(gcmd.GCMDSourceDriftError, match="version drift"):
        gcmd.parse_gcmd_science_keywords_csv(_acquire(tmp_path, pin, changed))


def test_digest_drift_never_becomes_a_parsed_resource(tmp_path: Path) -> None:
    payload = MINI_CSV_FIXTURE.read_bytes()
    changed = payload.replace(b"AQUACULTURE", b"AQUACULTURF")
    assert len(changed) == len(payload)

    class ChangedFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> gcmd.FetchedGCMDResponse:
            del timeout_seconds
            return gcmd.FetchedGCMDResponse(
                body=changed,
                status_code=200,
                content_type="text/csv",
                resolved_url=source_url,
            )

    with pytest.raises(gcmd.GCMDSourceDriftError, match="digest drift"):
        gcmd.acquire_gcmd_science_keywords(_mini_pin(), tmp_path, fetcher=ChangedFetcher())


def test_malformed_uuid_and_hierarchy_gap_fail_closed(tmp_path: Path) -> None:
    header = (
        '"Keyword Version: 24.4","Revision: 2026-07-22T11:07:16.739Z",'
        '"Timestamp: 2026-07-22 11:09:49","Terms Of Use: https://example.invalid/",'
        '"XML: https://example.invalid/"\n'
        '"Category","Topic","Term","Variable_Level_1","Variable_Level_2",'
        '"Variable_Level_3","Detailed_Variable","UUID"\n'
    )
    bad_uuid_payload = (header + '"EARTH SCIENCE","","","","","","","not-a-uuid"\n').encode("utf-8")
    hierarchy_gap_payload = (
        header
        + '"EARTH SCIENCE","","AGRICULTURAL AQUATIC SCIENCES","","","","","ca227ff0-4742-4e51-a763-4582fa28291c"\n'
    ).encode("utf-8")

    for label, payload in (("bad_uuid", bad_uuid_payload), ("gap", hierarchy_gap_payload)):
        source_path = tmp_path / f"{label}.csv"
        source_path.write_bytes(payload)
        pin = gcmd.GCMDSnapshotPin(
            source=gcmd.GCMD_SCIENCE_KEYWORDS_SOURCE,
            retrieved_at="2026-08-03T19:03:43Z",
            expected_sha256=gcmd.sha256_digest(payload),
            expected_byte_length=len(payload),
            expected_keyword_version="24.4",
            expected_revision="2026-07-22T11:07:16.739Z",
            expected_row_count=1,
        )
        acquired = gcmd.acquire_gcmd_science_keywords(pin, tmp_path / label, source_path=source_path)
        with pytest.raises(gcmd.GCMDSourceDriftError):
            gcmd.parse_gcmd_science_keywords_csv(acquired)


def test_builds_a_source_evidence_package_not_a_concept_scheme(tmp_path: Path) -> None:
    pin = _mini_pin()

    bundle = gcmd.build_gcmd_science_keywords_package(pin, MINI_CSV_FIXTURE)

    assert bundle.resource_manifest == {
        **bundle.resource_manifest,
        "resourceId": gcmd.GCMD_SCIENCE_KEYWORDS_RESOURCE_ID,
        "resourceKind": "controlledCodeList",
        "identityStatus": "publisherIdentifiersPreserved",
        "schemaVersion": "2.0",
        "conceptIdentityClaimed": False,
        "uses": ("deterministicMetadata", "mappingReference"),
        "observationCount": 9,
    }
    by_uuid = {observation["identifiers"][0]["value"]: observation for observation in bundle.observations}
    aquaculture = by_uuid["8916dafb-5ad5-45c6-ab64-3500ea1e9577"]
    assert aquaculture["labels"] == ({"value": "AQUACULTURE", "language": "en", "role": "preferred"},)
    assert aquaculture["identifiers"] == (
        {
            "value": "8916dafb-5ad5-45c6-ab64-3500ea1e9577",
            "kind": "gcmdConceptUUID",
            "authorityUri": gcmd.GCMD_IDENTIFIER_AUTHORITY_URI,
            "sourceUri": gcmd.GCMD_SCIENCE_KEYWORDS_SOURCE.source_url,
            "sourcePath": "csv:row[3].UUID",
            "observedAt": pin.retrieved_at,
            "sourceDigest": pin.expected_sha256,
        },
    )
    assert aquaculture["uses"] == ("deterministicMetadata", "mappingReference")
    assert aquaculture["conceptIdentityClaimed"] is False
    assert aquaculture["category"] == "EARTH SCIENCE"
    assert aquaculture["topic"] == "AGRICULTURE"
    assert aquaculture["term"] == "AGRICULTURAL AQUATIC SCIENCES"
    assert aquaculture["variableLevel1"] == "AQUACULTURE"
    assert aquaculture["variableLevel2"] is None
    assert bundle.coverage_report["reportStatus"] == "gap"
    assert bundle.coverage_report["packagedCount"] == 9
    assert bundle.coverage_report["excludedCount"] == 0
    assert bundle.coverage_report["failedCount"] == 0
    assert {gap["kind"] for gap in bundle.coverage_report["gaps"]} == {
        "skosRelationshipsUnavailable",
        "instrumentAndPlatformBranchesExcluded",
        "documentSubjectValueUnevaluated",
    }
    assert bundle.source_artifacts == {pin.source.source_url: MINI_CSV_FIXTURE.read_bytes()}


def test_package_generation_is_byte_deterministic(tmp_path: Path) -> None:
    pin = _mini_pin()

    first = gcmd.build_gcmd_science_keywords_package(pin, MINI_CSV_FIXTURE)
    second = gcmd.build_gcmd_science_keywords_package(pin, MINI_CSV_FIXTURE)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest


def test_closed_package_round_trips_through_disk(tmp_path: Path) -> None:
    pin = _mini_pin()
    bundle = gcmd.build_gcmd_science_keywords_package(pin, MINI_CSV_FIXTURE)

    written = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(written)

    assert reopened.logical_digest == bundle.logical_digest
    assert "candidateUseAuthorized" not in reopened.resource_manifest
    assert len(reopened.observations) == 9
    assert reopened.source_artifact_bytes(pin.source.source_url) == MINI_CSV_FIXTURE.read_bytes()


def test_source_drift_cannot_produce_a_new_package(tmp_path: Path) -> None:
    pin = _mini_pin()
    payload = MINI_CSV_FIXTURE.read_bytes().replace(b"AQUACULTURE", b"AQUACULTURF")
    assert len(payload) == len(MINI_CSV_FIXTURE.read_bytes())
    changed = tmp_path / "changed.csv"
    changed.write_bytes(payload)

    with pytest.raises(gcmd.GCMDSourceDriftError, match="digest drift"):
        gcmd.build_gcmd_science_keywords_package(pin, changed)

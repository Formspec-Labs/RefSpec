"""Tests for pinned SAM.gov Federal Hierarchy organization samples.

Every test acquires bytes from a local exact capture or an injected in-process
fetcher. No test opens a live network connection.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from refspec.registry import federal_hierarchy_orgs as fh
from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceError,
    build_source_controlled_resource_bundle,
)

FIXTURES = Path(__file__).parent / "fixtures" / "federal_hierarchy_orgs"
SAMPLE_FIXTURE = FIXTURES / "fh-orgs-sample-2026-08-03.json"
OPENAPI_ORG_FIXTURE = FIXTURES / "fh-public-org-2026-08-03.yml"
OPENAPI_HIERARCHY_FIXTURE = FIXTURES / "fh-public-hierarchy-2026-08-03.yml"
REAL_DATA_DIR = Path("output/registry-real-data-sources")


def _real_path(environment_name: str, filename: str) -> Path:
    configured = os.environ.get(environment_name)
    path = Path(configured) if configured else REAL_DATA_DIR / filename
    if not path.is_file():
        pytest.skip(f"real publisher capture is unavailable: {environment_name}")
    return path


def _acquire(tmp_path: Path, pin: fh.FHOrgsSnapshotPin, source_path: Path) -> fh.AcquiredFHOrgsSource:
    return fh.acquire_fh_orgs_sample(pin, tmp_path, source_path=source_path)


def _sample(tmp_path: Path) -> fh.ParsedFHOrgsSample:
    return fh.parse_fh_orgs_sample(_acquire(tmp_path, fh.FH_ORGS_SAMPLE_2026_08_03, SAMPLE_FIXTURE))


def test_real_openapi_interface_spec_bytes_are_pinned() -> None:
    org_spec = OPENAPI_ORG_FIXTURE.read_bytes()
    hierarchy_spec = OPENAPI_HIERARCHY_FIXTURE.read_bytes()

    assert len(org_spec) == fh.FH_ORGS_OPENAPI_ORG_BYTE_LENGTH == 3_351
    assert fh.sha256_digest(org_spec) == fh.FH_ORGS_OPENAPI_ORG_SHA256
    assert len(hierarchy_spec) == fh.FH_ORGS_OPENAPI_HIERARCHY_BYTE_LENGTH == 1_403
    assert fh.sha256_digest(hierarchy_spec) == fh.FH_ORGS_OPENAPI_HIERARCHY_SHA256
    # The official spec requires api_key on both endpoints -- proof that an
    # anonymous import cannot obtain one authenticated live capture.
    assert b"name: api_key" in org_spec
    assert b"required: true" in org_spec
    assert b"name: api_key" in hierarchy_spec


def test_pinned_sample_bytes_match_the_construction_digest() -> None:
    payload = SAMPLE_FIXTURE.read_bytes()

    assert len(payload) == fh.FH_ORGS_SAMPLE_2026_08_03.expected_byte_length == 3_623
    assert fh.sha256_digest(payload) == fh.FH_ORGS_SAMPLE_2026_08_03.expected_sha256


@pytest.mark.parametrize(
    ("environment_name", "filename", "pin", "expected_total", "expected_level", "first", "last"),
    [
        (
            "REFSPEC_FH_ORGS_DEFAULT_PATH",
            "fh-orgs-default-page.json",
            fh.FH_ORGS_DEFAULT_PAGE_2026_08_03,
            907,
            "Department/Ind. Agency",
            ("500174963", "400 YEARS OF AFRICAN AMERICAN HISTORY COMMISSION", "2471", "247"),
            (
                "100114157",
                "ARCHITECTURAL AND TRANSPORTATION BARRIERS COMPLIANCE BOARD",
                "9532",
                "310",
            ),
        ),
        (
            "REFSPEC_FH_ORGS_SUB_TIER_PATH",
            "fh-orgs-sub-tier-page.json",
            fh.FH_ORGS_SUB_TIER_PAGE_2026_08_03,
            738,
            "Sub-Tier",
            ("300000352", "ACADEMIC IMPROVEMENT AND TEACHER QUALITY PROGRAMS", "9147", "091"),
            ("300000117", "ADMINISTRATIVE OFFICE OF THE U.S. COURTS", "1027", "010"),
        ),
    ],
)
def test_authenticated_public_pages_match_real_shape_count_and_boundary_samples(
    tmp_path: Path,
    environment_name: str,
    filename: str,
    pin: fh.FHOrgsSnapshotPin,
    expected_total: int,
    expected_level: str,
    first: tuple[str, str, str, str],
    last: tuple[str, str, str, str],
) -> None:
    source_path = _real_path(environment_name, filename)
    payload = source_path.read_bytes()

    assert len(payload) == pin.expected_byte_length
    assert fh.sha256_digest(payload) == pin.expected_sha256
    assert b"api_key" not in payload.lower()

    acquired = _acquire(tmp_path, pin, source_path)
    sample = fh.parse_fh_orgs_sample(acquired)

    assert sample.total_records_reported == expected_total
    assert len(sample.records) == pin.source.expected_count == 10
    assert sample.hierarchy_levels() == (expected_level,)
    assert all(record.fhorgtype == expected_level for record in sample.records)
    for record, boundary in ((sample.records[0], first), (sample.records[-1], last)):
        expected_id, expected_name, expected_agency_code, expected_cgac = boundary
        assert (record.fhorgid, record.fhorgname) == (expected_id, expected_name)
        by_kind = {identifier.kind: identifier.value for identifier in record.identifiers}
        assert by_kind["fpdsAgencyCode"] == expected_agency_code
        assert by_kind["cgacCode"] == expected_cgac
        assert all(identifier.source_digest == pin.expected_sha256 for identifier in record.identifiers)


def test_real_sub_tier_page_preserves_rows_where_createddate_is_absent(tmp_path: Path) -> None:
    path = _real_path("REFSPEC_FH_ORGS_SUB_TIER_PATH", "fh-orgs-sub-tier-page.json")
    sample = fh.parse_fh_orgs_sample(
        _acquire(tmp_path, fh.FH_ORGS_SUB_TIER_PAGE_2026_08_03, path)
    )

    assert {record.fhorgid for record in sample.records} >= {
        "100525192",
        "100525875",
        "100525284",
    }


def test_local_capture_is_content_addressed_and_rechecked_on_cache_hit(tmp_path: Path) -> None:
    pin = fh.FH_ORGS_SAMPLE_2026_08_03

    acquired = _acquire(tmp_path, pin, SAMPLE_FIXTURE)
    cached = fh.acquire_fh_orgs_sample(pin, tmp_path)

    assert acquired.path == (tmp_path / "sha256" / pin.expected_sha256.removeprefix("sha256:") / pin.source.filename)
    assert acquired.acquisition_mode == "local"
    assert acquired.cache_hit is False
    assert cached.sha256 == pin.expected_sha256
    assert cached.acquisition_mode == "cache"
    assert cached.cache_hit is True


def test_injected_fetcher_is_the_only_live_transport_boundary(tmp_path: Path) -> None:
    payload = SAMPLE_FIXTURE.read_bytes()
    calls: list[tuple[str, float]] = []

    class Fetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> fh.FetchedFHOrgsResponse:
            calls.append((source_url, timeout_seconds))
            return fh.FetchedFHOrgsResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=source_url,
            )

    acquired = fh.acquire_fh_orgs_sample(
        fh.FH_ORGS_SAMPLE_2026_08_03,
        tmp_path,
        fetcher=Fetcher(),
        timeout_seconds=13.0,
    )

    assert calls == [(fh.FH_ORGS_SAMPLE_SOURCE.source_url, 13.0)]
    assert acquired.acquisition_mode == "fetcher"


def test_fetcher_resolved_url_must_stay_on_the_official_api_host(tmp_path: Path) -> None:
    payload = SAMPLE_FIXTURE.read_bytes()

    class RedirectingFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> fh.FetchedFHOrgsResponse:
            del source_url, timeout_seconds
            return fh.FetchedFHOrgsResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url="https://evil.example/orgs",
            )

    with pytest.raises(fh.FederalHierarchyAcquisitionError, match="official HTTPS api.sam.gov host"):
        fh.acquire_fh_orgs_sample(
            fh.FH_ORGS_SAMPLE_2026_08_03,
            tmp_path,
            fetcher=RedirectingFetcher(),
        )


def test_fetcher_resolved_url_must_not_retain_the_api_key(tmp_path: Path) -> None:
    payload = SAMPLE_FIXTURE.read_bytes()

    class CredentialLeakingFetcher:
        def fetch(self, source_url: str, *, timeout_seconds: float) -> fh.FetchedFHOrgsResponse:
            del timeout_seconds
            return fh.FetchedFHOrgsResponse(
                body=payload,
                status_code=200,
                content_type="application/json",
                resolved_url=f"{source_url}?api_key=must-not-survive",
            )

    with pytest.raises(fh.FederalHierarchyAcquisitionError, match="must not retain"):
        fh.acquire_fh_orgs_sample(
            fh.FH_ORGS_SAMPLE_2026_08_03,
            tmp_path,
            fetcher=CredentialLeakingFetcher(),
        )


def test_sample_captures_both_documented_hierarchy_levels(tmp_path: Path) -> None:
    sample = _sample(tmp_path)

    assert sample.hierarchy_levels() == ("Department/Ind. Agency", "Sub-Tier")
    assert len(sample.records) == 3
    assert sample.api_version == "v1.0"
    assert sample.publisher_release is None
    assert sample.total_records_reported == 3


def test_department_record_retains_fh_fpds_and_cgac_identifier_shapes(tmp_path: Path) -> None:
    gsa = _sample(tmp_path).by_org_id()["100006688"]

    assert gsa.fhorgname == "GENERAL SERVICES ADMINISTRATION"
    assert gsa.fhorgtype == "Department/Ind. Agency"
    assert gsa.status == "ACTIVE"
    assert gsa.parent_fhorgid == "100006688"
    assert gsa.parent_org_name == "GENERAL SERVICES ADMINISTRATION"
    assert gsa.full_parent_path_id == "100006688"
    assert gsa.full_parent_path_name == "GENERAL SERVICES ADMINISTRATION"
    assert gsa.identifiers == (
        ControlledIdentifier(
            value="100006688",
            kind="fhOrgId",
            authority_uri=fh.FH_ORGS_IDENTIFIER_AUTHORITY_FH,
            source_uri=fh.FH_ORGS_SAMPLE_SOURCE.source_url,
            observed_at=fh.FH_ORGS_SAMPLE_2026_08_03.retrieved_at,
            effective_at=None,
            source_digest=fh.FH_ORGS_SAMPLE_2026_08_03.expected_sha256,
        ),
        ControlledIdentifier(
            value="4700",
            kind="fpdsAgencyCode",
            authority_uri=fh.FH_ORGS_IDENTIFIER_AUTHORITY_FPDS,
            source_uri=fh.FH_ORGS_SAMPLE_SOURCE.source_url,
            observed_at=fh.FH_ORGS_SAMPLE_2026_08_03.retrieved_at,
            effective_at=None,
            source_digest=fh.FH_ORGS_SAMPLE_2026_08_03.expected_sha256,
        ),
        ControlledIdentifier(
            value="4700",
            kind="oldFpdsOfficeCode",
            authority_uri=fh.FH_ORGS_IDENTIFIER_AUTHORITY_FPDS,
            source_uri=fh.FH_ORGS_SAMPLE_SOURCE.source_url,
            observed_at=fh.FH_ORGS_SAMPLE_2026_08_03.retrieved_at,
            effective_at=None,
            source_digest=fh.FH_ORGS_SAMPLE_2026_08_03.expected_sha256,
        ),
        ControlledIdentifier(
            value="047",
            kind="cgacCode",
            authority_uri=fh.FH_ORGS_IDENTIFIER_AUTHORITY_CGAC,
            source_uri=fh.FH_ORGS_SAMPLE_SOURCE.source_url,
            observed_at=fh.FH_ORGS_SAMPLE_2026_08_03.retrieved_at,
            effective_at=None,
            source_digest=fh.FH_ORGS_SAMPLE_2026_08_03.expected_sha256,
        ),
        ControlledIdentifier(
            value="100006688",
            kind="fhFullParentPathId",
            authority_uri=fh.FH_ORGS_IDENTIFIER_AUTHORITY_FH,
            source_uri=fh.FH_ORGS_SAMPLE_SOURCE.source_url,
            observed_at=fh.FH_ORGS_SAMPLE_2026_08_03.retrieved_at,
            effective_at=None,
            source_digest=fh.FH_ORGS_SAMPLE_2026_08_03.expected_sha256,
        ),
    )


def test_subtier_record_omits_optional_fields_and_links_to_its_department(tmp_path: Path) -> None:
    subtier = _sample(tmp_path).by_org_id()["300000352"]

    assert subtier.fhorgname == "ACADEMIC IMPROVEMENT AND TEACHER QUALITY PROGRAMS"
    assert subtier.fhorgtype == "Sub-Tier"
    assert subtier.parent_fhorgid == "100001616"
    assert subtier.parent_org_name == "EDUCATION, DEPARTMENT OF"
    assert subtier.full_parent_path_id == "100001616.300000352"
    # No oldfpdsofficecode was published for this record, matching the
    # publisher's own documented example -- no identifier is fabricated.
    assert [identifier.kind for identifier in subtier.identifiers] == [
        "fhOrgId",
        "fpdsAgencyCode",
        "cgacCode",
        "fhFullParentPathId",
    ]


def test_children_of_resolves_only_within_the_pinned_sample(tmp_path: Path) -> None:
    sample = _sample(tmp_path)

    # children_of matches on parent_fhorgid alone; the Sub-Tier's declared
    # department parent (100001616) resolves even though that department was
    # not itself pinned as its own record in this small sample.
    assert [child.fhorgid for child in sample.children_of("100001616")] == ["300000352"]
    # A Department record is self-parented (fhdeptindagencyorgid == fhorgid),
    # so it is explicitly excluded from being its own child.
    assert sample.children_of("100006688") == ()

    two_level_payload = (
        b'{"totalrecords":2,"orglist":['
        b'{"fhorgid":100006688,"fhorgname":"GENERAL SERVICES ADMINISTRATION",'
        b'"fhorgtype":"Department/Ind. Agency","status":"ACTIVE","createddate":"2003-06-11 00:00",'
        b'"fhdeptindagencyorgid":100006688,"fhagencyorgname":"GENERAL SERVICES ADMINISTRATION",'
        b'"agencycode":"4700","cgaclist":[{"cgac":"047"}],'
        b'"fhorgnamehistory":[{"fhorgname":"GENERAL SERVICES ADMINISTRATION","effectivedate":null}],'
        b'"fhorgparenthistory":[{"fhfullparentpathid":"100006688",'
        b'"fhfullparentpathname":"GENERAL SERVICES ADMINISTRATION","effectivedate":null,'
        b'"codehierarchy":"4700","actiontype":"CREATE"}],'
        b'"links":[{"rel":"self","href":"https://api.sam.gov/prod/federalorganizations/v1/orgs?fhorgid=100006688"}]},'
        b'{"fhorgid":100006689,"fhorgname":"GSA REGIONAL OFFICE",'
        b'"fhorgtype":"Sub-Tier","status":"ACTIVE","createddate":"2003-06-11 00:00",'
        b'"fhdeptindagencyorgid":100006688,"fhagencyorgname":"GENERAL SERVICES ADMINISTRATION",'
        b'"agencycode":"4701","cgaclist":[{"cgac":"047"}],'
        b'"fhorgnamehistory":[{"fhorgname":"GSA REGIONAL OFFICE","effectivedate":null}],'
        b'"fhorgparenthistory":[{"fhfullparentpathid":"100006688.100006689",'
        b'"fhfullparentpathname":"GENERAL SERVICES ADMINISTRATION.GSA REGIONAL OFFICE","effectivedate":null,'
        b'"codehierarchy":"4701","actiontype":"CREATE"}],'
        b'"links":[{"rel":"self","href":"https://api.sam.gov/prod/federalorganizations/v1/orgs?fhorgid=100006689"}]}'
        b"]}"
    )
    source = replace(fh.FH_ORGS_SAMPLE_SOURCE, expected_count=2)
    pin = fh.FHOrgsSnapshotPin(
        source=source,
        retrieved_at="2026-08-03T15:22:00Z",
        expected_sha256=fh.sha256_digest(two_level_payload),
        expected_byte_length=len(two_level_payload),
    )
    source_path = tmp_path / "two-level.json"
    source_path.write_bytes(two_level_payload)

    two_level_sample = fh.parse_fh_orgs_sample(fh.acquire_fh_orgs_sample(pin, tmp_path / "store", source_path=source_path))

    children = two_level_sample.children_of("100006688")
    assert [child.fhorgid for child in children] == ["100006689"]


def test_digest_drift_never_produces_a_parsed_sample(tmp_path: Path) -> None:
    payload = SAMPLE_FIXTURE.read_bytes()
    changed = payload.replace(b"ADMINISTRATION", b"ADMONISTRATION")
    assert len(changed) == len(payload)
    changed_path = tmp_path / "changed.json"
    changed_path.write_bytes(changed)

    with pytest.raises(fh.FederalHierarchySourceDriftError, match="digest drift"):
        fh.acquire_fh_orgs_sample(fh.FH_ORGS_SAMPLE_2026_08_03, tmp_path / "store", source_path=changed_path)


def _pinned(tmp_path: Path, payload: bytes, *, expected_count: int = 1) -> fh.AcquiredFHOrgsSource:
    source = replace(fh.FH_ORGS_SAMPLE_SOURCE, expected_count=expected_count)
    pin = fh.FHOrgsSnapshotPin(
        source=source,
        retrieved_at="2026-08-03T15:22:00Z",
        expected_sha256=fh.sha256_digest(payload),
        expected_byte_length=len(payload),
    )
    source_path = tmp_path / "shape.json"
    source_path.write_bytes(payload)
    return fh.acquire_fh_orgs_sample(pin, tmp_path / "store", source_path=source_path)


def test_unknown_top_level_or_record_shape_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(fh.FederalHierarchySourceDriftError, match="top-level fields drifted"):
        fh.parse_fh_orgs_sample(_pinned(tmp_path, b'{"totalrecords":0,"orglist":[],"extra":1}', expected_count=1))

    minimal = SAMPLE_FIXTURE.read_bytes()
    # A record missing a required field must fail loudly rather than silently
    # dropping the field.
    mini_record = (
        b'{"totalrecords":1,"orglist":[{"fhorgid":100006688,"fhorgname":"X",'
        b'"fhorgtype":"Department/Ind. Agency","status":"ACTIVE","createddate":"2003-06-11 00:00",'
        b'"fhdeptindagencyorgid":100006688,"fhagencyorgname":"X","agencycode":"4700",'
        b'"cgaclist":[{"cgac":"047"}],"fhorgnamehistory":[{"fhorgname":"X","effectivedate":null}],'
        b'"links":[{"rel":"self","href":"https://api.sam.gov/prod/federalorganizations/v1/orgs?fhorgid=100006688"}]}]}'
    )
    del minimal
    with pytest.raises(fh.FederalHierarchySourceDriftError, match="fields drifted"):
        fh.parse_fh_orgs_sample(_pinned(tmp_path, mini_record))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fhorgtype", "Office", "unsupported level"),
        ("status", "Active", "status is unsupported"),
    ],
)
def test_unsupported_enum_values_fail_closed(tmp_path: Path, field: str, value: str, message: str) -> None:
    import json as _json

    record = _json.loads(SAMPLE_FIXTURE.read_bytes())
    record["orglist"][0][field] = value
    payload = _json.dumps(record).encode("utf-8")

    with pytest.raises(fh.FederalHierarchySourceDriftError, match=message):
        fh.parse_fh_orgs_sample(_pinned(tmp_path, payload, expected_count=3))


def test_multiple_cgac_values_are_refused_as_documented_drift(tmp_path: Path) -> None:
    import json as _json

    record = _json.loads(SAMPLE_FIXTURE.read_bytes())
    record["orglist"][0]["cgaclist"] = [{"cgac": "047"}, {"cgac": "048"}]
    payload = _json.dumps(record).encode("utf-8")

    with pytest.raises(fh.FederalHierarchySourceDriftError, match="single-CGAC"):
        fh.parse_fh_orgs_sample(_pinned(tmp_path, payload, expected_count=3))


def test_bulk_organization_capture_is_refused_regardless_of_pin(tmp_path: Path) -> None:
    def record(ordinal: int) -> dict[str, object]:
        org_id = 100000000 + ordinal
        return {
            "fhorgid": org_id,
            "fhorgname": f"SAMPLE ORG {ordinal}",
            "fhorgtype": "Sub-Tier",
            "status": "ACTIVE",
            "createddate": "2003-06-11 00:00",
            "fhdeptindagencyorgid": org_id,
            "fhagencyorgname": f"SAMPLE ORG {ordinal}",
            "agencycode": "4700",
            "cgaclist": [{"cgac": "047"}],
            "fhorgnamehistory": [{"fhorgname": f"SAMPLE ORG {ordinal}", "effectivedate": None}],
            "fhorgparenthistory": [
                {
                    "fhfullparentpathid": str(org_id),
                    "fhfullparentpathname": f"SAMPLE ORG {ordinal}",
                    "effectivedate": None,
                    "codehierarchy": "4700",
                    "actiontype": "CREATE",
                }
            ],
            "links": [{"rel": "self", "href": "https://api.sam.gov/prod/federalorganizations/v1/orgs"}],
        }

    import json as _json

    bulk_count = fh.MAX_SAMPLE_ORG_COUNT + 1
    payload = _json.dumps(
        {
            "totalrecords": bulk_count,
            "orglist": [record(ordinal) for ordinal in range(bulk_count)],
        }
    ).encode("utf-8")

    with pytest.raises(fh.FederalHierarchyBulkCaptureRefusedError, match="bulk organization dump"):
        fh.parse_fh_orgs_sample(_pinned(tmp_path, payload, expected_count=3))


def test_sample_source_definition_refuses_bulk_expected_counts() -> None:
    with pytest.raises(fh.FederalHierarchyAcquisitionError, match="small sample size"):
        replace(fh.FH_ORGS_SAMPLE_SOURCE, expected_count=fh.MAX_SAMPLE_ORG_COUNT + 1)


def test_package_builds_a_controlled_code_list_that_claims_no_concept_identity() -> None:
    source_path = _real_path("REFSPEC_FH_ORGS_DEFAULT_PATH", "fh-orgs-default-page.json")
    bundle = fh.build_federal_hierarchy_orgs_package(source_path)

    assert bundle.resource_manifest["resourceId"] == fh.FH_ORGS_RESOURCE_ID
    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert bundle.resource_manifest["usageCeiling"] == "developmentOnly"
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["uses"] == ["deterministicMetadata"]
    assert bundle.resource_manifest["observationCount"] == 10
    assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
    assert all(observation["eligibleUses"] == ["deterministicMetadata"] for observation in bundle.observations)
    labels = [observation["labels"][0]["value"] for observation in bundle.observations]
    assert labels[0] == "400 YEARS OF AFRICAN AMERICAN HISTORY COMMISSION"
    assert labels[-1] == "ARCHITECTURAL AND TRANSPORTATION BARRIERS COMPLIANCE BOARD"
    assert {gap["kind"] for gap in bundle.coverage_report["gaps"]} == {
        "samplePagesOnly",
        "defaultHierarchyDepthLimited",
        "moveOrMergeHistoryLargelyUnavailable",
        "singleCgacPerRecordOnly",
    }
    assert bundle.coverage_report["reportStatus"] == "gap"
    assert bundle.source_artifacts == {
        fh.FH_ORGS_DEFAULT_PAGE_SOURCE.source_url: source_path.read_bytes()
    }


def test_package_generation_is_byte_deterministic() -> None:
    source_path = _real_path("REFSPEC_FH_ORGS_DEFAULT_PATH", "fh-orgs-default-page.json")
    first = fh.build_federal_hierarchy_orgs_package(source_path)
    second = fh.build_federal_hierarchy_orgs_package(source_path)

    assert first.artifact_bytes() == second.artifact_bytes()
    assert first.logical_digest == second.logical_digest


def test_package_round_trips_through_write_and_reopen(tmp_path: Path) -> None:
    from refspec.registry.infrastructure.source_controlled_resource import SourceControlledResourceView

    source_path = _real_path("REFSPEC_FH_ORGS_DEFAULT_PATH", "fh-orgs-default-page.json")
    bundle = fh.build_federal_hierarchy_orgs_package(source_path)
    destination = bundle.write_to(tmp_path / "federal-hierarchy-orgs")

    reopened = SourceControlledResourceView.open(destination)

    assert reopened.resource_manifest["resourceId"] == fh.FH_ORGS_RESOURCE_ID
    assert len(reopened.observations) == 10


def test_package_source_path_must_be_a_regular_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"

    with pytest.raises(fh.FederalHierarchyOrgsError, match="regular file"):
        fh.build_federal_hierarchy_orgs_package(missing)


def test_bundle_still_enforces_its_own_shared_invariants(tmp_path: Path) -> None:
    # federal_hierarchy_orgs.py builds through the shared packaging module; a
    # tampered candidate_use_authorized still fails there, not just here.
    source_path = _real_path("REFSPEC_FH_ORGS_DEFAULT_PATH", "fh-orgs-default-page.json")
    bundle = fh.build_federal_hierarchy_orgs_package(source_path)
    with pytest.raises(SourceControlledResourceError):
        build_source_controlled_resource_bundle(
            resource_id=fh.FH_ORGS_RESOURCE_ID,
            title=fh.FH_ORGS_PACKAGE_TITLE,
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=fh.FH_ORGS_PACKAGE_USES,
            captured_at=fh.FH_ORGS_DEFAULT_PAGE_2026_08_03.retrieved_at,
            candidate_use_authorized=True,
            observations=bundle.observations,
            source_artifacts=bundle.source_artifacts,
            source_observed_count=0,
        )

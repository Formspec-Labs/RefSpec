"""Reproducibility checks for the dated REF-038 identifier census."""

from __future__ import annotations

from pathlib import Path

from tools import analyze_agency_roster_identifiers as census

ROOT = Path(__file__).resolve().parents[1]


def test_census_measures_all_identifier_kinds_and_cross_roster_equalities() -> None:
    report = census.build_census(census.load_five_agency_rosters(ROOT))

    assert report["method"]["nameSimilarityUsed"] is False
    assert [row["resourceCount"] for row in report["releases"]] == [472, 907, 798, 316, 331]
    assert [
        (
            row["identifierKind"],
            row["claimCount"],
            row["distinctValueCount"],
            row["collisionValueCount"],
        )
        for row in report["identifierKinds"]
    ] == [
        ("federalRegisterNumericId", 472, 472, 0),
        ("federalRegisterSlug", 472, 472, 0),
        ("federalRegisterShortName", 419, 409, 10),
        ("federalHierarchyOrganizationId", 907, 907, 0),
        ("fpdsAgencyCode", 906, 743, 162),
        ("cgacAgencyIdentifier", 908, 143, 141),
        ("legacyFpdsOfficeCode", 472, 463, 9),
        ("opmEhriAgencySubelementCode", 798, 798, 0),
        ("ecfrAgencySlug", 316, 316, 0),
        ("ecfrAgencyShortName", 242, 241, 1),
        ("regulationsGovAgencyId", 331, 331, 0),
    ]
    assert [
        (
            row["leftKind"],
            row["rightKind"],
            row["disposition"],
            row["sharedValueCount"],
            row["candidateEdgeCount"],
            row["unambiguousValueCount"],
            row["ambiguousValueCount"],
        )
        for row in report["identifierEqualityComparisons"]
    ] == [
        (
            "federalRegisterNumericId",
            "cgacAgencyIdentifier",
            "refusedDifferentIdentifierAuthorities",
            52,
            126,
            1,
            51,
        ),
        (
            "federalRegisterSlug",
            "ecfrAgencySlug",
            "refusedDifferentIdentifierAuthorities",
            252,
            252,
            252,
            0,
        ),
        (
            "federalRegisterShortName",
            "opmEhriAgencySubelementCode",
            "refusedDifferentIdentifierAuthorities",
            3,
            3,
            3,
            0,
        ),
        (
            "federalRegisterShortName",
            "ecfrAgencyShortName",
            "admissibleE4AcronymAdjudication",
            238,
            249,
            229,
            9,
        ),
        (
            "federalRegisterShortName",
            "regulationsGovAgencyId",
            "admissibleE4AcronymAdjudication",
            279,
            287,
            271,
            8,
        ),
        (
            "opmEhriAgencySubelementCode",
            "ecfrAgencyShortName",
            "refusedDifferentIdentifierAuthorities",
            3,
            3,
            3,
            0,
        ),
        (
            "opmEhriAgencySubelementCode",
            "regulationsGovAgencyId",
            "refusedDifferentIdentifierAuthorities",
            3,
            3,
            3,
            0,
        ),
        (
            "ecfrAgencyShortName",
            "regulationsGovAgencyId",
            "admissibleE4AcronymAdjudication",
            200,
            201,
            199,
            1,
        ),
    ]


def test_census_pins_the_regulations_gov_abstention_set() -> None:
    report = census.build_census(census.load_five_agency_rosters(ROOT))
    coverage = report["regulationsGovCoverage"]

    assert coverage["totalValueCount"] == 331
    assert coverage["resolvedValueCount"] == 279
    assert coverage["abstentionValueCount"] == 52
    assert [row["value"] for row in coverage["abstentions"]] == [
        "ACL",
        "ADF",
        "AID",
        "ARCTICGAS",
        "ASC",
        "ATR",
        "BSC",
        "CDFIF",
        "CISA",
        "CNCS",
        "COFA",
        "CORP",
        "CROMFS",
        "DBCRC",
        "DEPO",
        "EERE",
        "EIB",
        "EOA",
        "ESA",
        "FINCEN",
        "FIRSTNET",
        "FISCAL",
        "FPAC",
        "FPPO",
        "FR",
        "FS",
        "GAPFAC",
        "GCERC",
        "GEO",
        "HHSIG",
        "HPAC",
        "ICEB",
        "MCRMC",
        "MEXICO",
        "MKU",
        "MMA",
        "MPAC",
        "NCC",
        "NCRIRS",
        "NEO",
        "NRPC",
        "NSPC",
        "OIRA",
        "PCSCOTUS",
        "PRES",
        "RUF",
        "SS",
        "TRADE",
        "USC",
        "USDAIG",
        "USEIB",
        "WCPO",
    ]
    assert next(row for row in coverage["abstentions"] if row["value"] == "FS")[
        "reason"
    ] == "ambiguousAcronymEquality"


def test_second_pass_adjudication_layers_over_the_unchanged_census() -> None:
    report = census.build_census(census.load_five_agency_rosters(ROOT))
    adjudication = report["agencyIdentityAdjudication"]

    assert report["regulationsGovCoverage"]["resolvedValueCount"] == 279
    assert report["regulationsGovCoverage"]["abstentionValueCount"] == 52
    assert adjudication["label"] == "secondPassPerValueAdjudication"
    assert adjudication["residueValueCount"] == 52
    assert adjudication["adoptedResidueValueCount"] == 42
    assert adjudication["abstainedResidueValueCount"] == 10
    assert adjudication["finalResolvedValueCount"] == 321
    assert adjudication["finalAbstainedValueCount"] == 10
    assert adjudication["mappingEvidenceRecordCount"] == 642
    assert len(adjudication["decisions"]) == 52
    by_value = {row["sourceValue"]: row for row in adjudication["decisions"]}
    assert by_value["FS"]["decision"] == "adopted"
    assert by_value["FS"]["objectPublisherName"] == "Forest Service"
    assert by_value["MMA"]["decision"] == "abstained"
    assert by_value["MMA"]["reason"] == "noCounterpartInHeldRosters"
    assert by_value["MMA"]["closestNonAdoptedCandidate"]["publisherName"] == (
        "Minerals Management Service"
    )


def test_checked_census_artifacts_are_reproducible() -> None:
    report = census.build_census(census.load_five_agency_rosters(ROOT))

    census._write_or_check(ROOT, report, write=False)
    assert report["censusDigest"] == (
        "sha256:98ee78e352f019a4b33090f0397fdf145c6876d7f6033508172db144912d9420"
    )
    assert report["agencyIdentityAdjudication"]["adjudicationDigest"] == (
        "sha256:5730f79b86117f323efb8bc32317df6b1d8a09c16c8fdf56879179507ee00c55"
    )

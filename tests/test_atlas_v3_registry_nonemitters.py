"""Atlas 3 emission coverage for previously descriptor-only sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.atlas import v3_registry_nonemitters as adapters

ROOT = Path(__file__).resolve().parents[1]
REAL_DATA = ROOT / "output" / "registry-real-data-sources"

_GSDM_CAPTURES_PRESENT = (REAL_DATA / "gsdm-data-dictionary-2026-08-03.json").is_file() and (
    REAL_DATA / "gsdm-architecture-v1.0.1.pdf"
).is_file()
_EHRI_CAPTURE_PRESENT = (REAL_DATA / "EHRI-Data-Standards-20260804.xlsx").is_file()


def test_fac_emits_every_field_entry_and_counts_both_truths() -> None:
    # Boundary-audit repair: a member is one (endpoint, field) pair and the
    # same GSA field name recurs across endpoints, so the old
    # "distinctFieldCount" claim was false. Both counts are now stated.
    (release,) = adapters._fac_releases(ROOT)

    assert release.profile == "structureScheme"
    assert len(release.resources) == release.metadata["fieldEntryCount"] == 163
    assert release.metadata["distinctFieldNameCount"] == 122
    assert "distinctFieldCount" not in release.metadata
    assert release.metadata["endpointCount"] == 11


def test_govinfo_cfr_packages_are_not_a_nonemitter_group() -> None:
    # REF-031: GovInfo issues hundreds of CFR volumes a year, so the bounded
    # package exemplar left the Atlas for SpicyRegs. The GovInfo *collections*
    # list is a code release and stays in v3_registry_codes.
    group_names = {name for name, _ in adapters.REGISTRY_NONEMITTER_RELEASE_GROUPS}

    assert "govinfo-package" not in group_names
    assert not hasattr(adapters, "_govinfo_package_releases")
    assert "govinfo-cfr-package-bounded-2026-08-03" not in (
        adapters.REGISTRY_NONEMITTER_RELEASE_KEYS
    )


def test_nppes_emits_only_the_layout_structure() -> None:
    # The provider sample moved to the entity registry (REF-030); the layout
    # is structural reference and stays.
    (layout,) = adapters._nppes_releases(ROOT)

    assert layout.ring == "value"
    assert layout.profile == "structureScheme"
    assert len(layout.resources) == 330


def test_treasury_emits_every_unique_account_and_retains_the_duplicate_row() -> None:
    # REF-032: the fund-type release was a Counter over these same rows and
    # matched none of Treasury's three documented lists, so only the published
    # account symbols remain (the documented fund groups are a separate
    # release parsed from the workbook's own Intro sheets, below).
    accounts, _fund_groups = adapters._treasury_releases(ROOT)

    assert accounts.key == "treasury-fast-book-accounts-parts-ii-iii-2026-07"
    assert accounts.ring == "entity"
    assert len(accounts.resources) == 3_581
    assert sum(resource.native_payload["duplicatePublisherRowCount"] for resource in accounts.resources) == 1
    assert accounts.metadata["publisherRows"] == 3_582
    assert accounts.metadata["partIMissing"] is True


def test_treasury_fund_groups_are_the_documented_successor_of_the_fund_type_counter() -> None:
    # REF-032 deleted the observed fund-type unit: 11 distinct Fund Type
    # strings Counter-aggregated from the workbook's account rows, matching
    # none of Treasury's documented lists. The documented successor is the
    # workbook's own Intro Part II "EXPENDITURE ACCOUNT SYMBOLS BY FUND
    # GROUP" table plus Intro Part III's foreign currency row -- parsed from
    # the same pinned bytes, never transcribed from another page.
    _accounts, fund_groups = adapters._treasury_releases(ROOT)

    assert fund_groups.key == "treasury-fast-book-fund-groups-2026-07"
    assert fund_groups.resource_id == "treasury-fast-book"
    assert (fund_groups.profile, fund_groups.ring) == ("codeScheme", "value")
    assert fund_groups.scope == "completeCapture"
    # Clean scheme naming: the refused urn:ref:treasury-fast-book:fund-type:
    # namespace appears nowhere; the scheme names the documented list.
    assert fund_groups.scheme_iri == "urn:ref:atlas-resource-scheme:treasury-fast-book:fund-groups"
    assert len(fund_groups.resources) == 9
    assert fund_groups.metadata["fundGroupCount"] == 9
    assert fund_groups.metadata["partIIHeading"] == "EXPENDITURE ACCOUNT SYMBOLS BY FUND GROUP"
    assert fund_groups.metadata["semanticAnchorReference"] == "OMB Circular A-11 §20.11(b)"
    assert fund_groups.metadata["documentedSuccessorOfObservedFundTypes"] is True

    assert [resource.labels[0].value for resource in fund_groups.resources] == [
        "General Fund",
        "Management and Consolidated Working Funds",
        "Public Enterprise Revolving Fund",
        "Intra-Governmental Revolving Fund",
        "Special Fund",
        "Deposit Fund",
        "Trust Revolving Fund",
        "Trust Non-Revolving Fund",
        "Foreign Currency Expenditure (No associated receipts)",
    ]
    by_label = {resource.labels[0].value: resource for resource in fund_groups.resources}
    general = by_label["General Fund"]
    assert general.iri == "urn:ref:treasury-fast-book:fund-group:General%20Fund"
    assert general.notations == ("0000-3899",)
    assert [dict(item) for item in general.native_payload["symbolRanges"]] == [
        {"firstSymbol": "0000", "lastSymbol": "3899"}
    ]
    split = by_label["Trust Non-Revolving Fund"]
    assert split.notations == ("8000-8399", "8500-8999")
    assert split.native_payload["symbolRangeText"] == "8000-8399 and 8500-8999"
    foreign = by_label["Foreign Currency Expenditure (No associated receipts)"]
    assert foreign.native_payload["fastBookPart"] == "III"
    assert foreign.notations == ("7000-7999",)
    # No member re-mints the refused observation namespace and none carries
    # authority-scoped identifier rows.
    for resource in fund_groups.resources:
        assert not resource.iri.startswith("urn:ref:treasury-fast-book:fund-type:")
        assert resource.identifiers == ()


def test_nrc_releases_are_the_documented_successors_of_the_scraped_units() -> None:
    # REF-032 deleted 19 NRC ADAMS controls (12 regexed out of a minified
    # Angular bundle) and four identifier shapes (one inferred from two
    # examples). The documented successors are NRC's own published APS PDFs:
    # the User Manual's 22-property Properties in Profile table with
    # publisher descriptions, and the official accession-number definition.
    properties, accession = adapters._nrc_releases(ROOT)

    assert properties.key == "nrc-adams-documented-profile-properties-2026-08-15"
    assert properties.resource_id == "nrc-adams-native-controls"
    assert (properties.profile, properties.ring) == ("structureScheme", "value")
    assert properties.scope == "completeCapture"
    # Clean scheme naming: the REF-032-refused :observed-structure suffix is
    # gone; the documented suffix names the publisher's table.
    assert properties.scheme_iri == (
        "urn:ref:atlas-resource-scheme:nrc-adams-native-controls:documented-profile-properties"
    )
    assert len(properties.resources) == 22
    assert properties.metadata["propertyCount"] == 22
    assert [pin.role for pin in properties.inputs] == ["publisherUserManual", "publisherApiGuide"]

    by_label = {resource.labels[0].value: resource for resource in properties.resources}
    assert by_label["Addressee Affiliation"].definition == (
        "The name of the organization receiving the agency document(s)"
    )
    assert by_label["Docket Number"].native_payload["sourceMedium"] == "pdf"
    for resource in properties.resources:
        assert resource.definition  # every property carries a publisher description
        assert not resource.iri.startswith("urn:ref:nrc-adams-control:")
        assert resource.identifiers == ()

    # The API guide's documented enumerations travel verbatim as metadata.
    assert tuple(properties.metadata["apiGuideDatePropertyNames"]) == (
        "DateAddedTimestamp",
        "DocumentDate",
    )
    assert [item["token"] for item in properties.metadata["apiGuideTextOperators"]] == [
        "contains",
        "notcontains",
        "starts",
        "notstarts",
        "equals",
        "notequals",
    ]
    assert [item["name"] for item in properties.metadata["apiGuideSearchRequestParameters"]] == [
        "q",
        "filters",
        "anyFilters",
        "legacyLibFilter",
        "mainLibFilter",
        "sort",
        "sortDirection",
        "skip",
    ]
    assert properties.metadata["apiGuideVersionMarkers"]["printedVersionStatement"] == "Version 1.0"
    # The manual prints no version statement; the wire carries no nulls, so
    # the absence is stated by omission plus an explicit absence flag.
    assert "printedVersionStatement" not in properties.metadata["userManualVersionMarkers"]
    assert properties.metadata["userManualVersionMarkers"]["printedVersionStatementAbsent"] is True
    assert properties.metadata["wbaReplacementStatement"] == (
        "This application will replace the previous Web-Based ADAMS search application."
    )

    # The API guide's Appendix A (13 API document-property names) is captured
    # and recorded as notEmitted on both releases, and each release bounds
    # its completeCapture claim to exactly what it names.
    for release in (properties, accession):
        not_emitted = release.metadata["notEmitted"]
        assert not_emitted["apiGuideAppendixAHeading"] == "Appendix A: Document Properties"
        assert not_emitted["apiGuideAppendixADocumentPropertyCount"] == 13
        assert list(not_emitted["apiGuideAppendixADocumentPropertyNames"])[:2] == [
            "AccessionNumber",
            "DocumentTitle",
        ]
        assert len(not_emitted["apiGuideAppendixADocumentPropertyNames"]) == 13
    assert "Properties in Profile" in properties.metadata["completeCaptureOf"]
    assert "Appendix A" in properties.metadata["completeCaptureOf"]
    assert "accession-number definition" in accession.metadata["completeCaptureOf"]

    assert accession.key == "nrc-adams-documented-accession-number-2026-08-15"
    assert accession.resource_id == "nrc-adams-identifiers"
    assert (accession.profile, accession.ring) == ("structureScheme", "value")
    # Clean scheme naming: the REF-032-refused :identifier-shapes suffix is
    # gone; the documented suffix names the official definition.
    assert accession.scheme_iri == (
        "urn:ref:atlas-resource-scheme:nrc-adams-identifiers:documented-accession-number"
    )
    assert len(accession.resources) == 2
    first, second = accession.resources
    assert first.iri == "urn:ref:nrc-adams-accession-number:element-1"
    assert first.labels[0].value == "two-character alphabetic code"
    assert first.definition == (
        "two-character alphabetic code (e.g., “ML” to indicate the original library)"
    )
    assert second.labels[0].value == "nine-character numeric code"
    assert {label.value for label in second.labels if label.role == "alternate"} == {"ADAMS Item ID"}
    assert second.definition == "nine-character numeric code, known as the “ADAMS Item ID”"
    # NO identifier-authority rows, and no undocumented decomposition: the
    # publisher states exactly two elements and nothing finer for the
    # nine-character ADAMS Item ID (the inferred MLYYDDDNNNN shape left
    # under REF-032 and is not carried).
    for resource in accession.resources:
        assert resource.identifiers == ()
        assert not resource.iri.startswith("urn:ref:nrc-adams-identifier-shape:")
    assert accession.metadata["elementCount"] == 2
    assert accession.metadata["noUndocumentedDecomposition"] is True
    assert accession.metadata["identifierAuthorityRowsMinted"] is False
    assert "MLYYDDDNNNN" not in accession.metadata["officialDefinition"]


def test_documented_successor_releases_pass_all_three_atlas_refusal_guards() -> None:
    """REF-030/031/032's refusal guards must all accept the new units.

    The guards key on registrant-population schemes, document-population
    IRIs, observation substrate paths, observation scheme strings, and
    observation IRI namespaces. The documented successors deliberately land
    beside every one of those surfaces -- same resources, clean naming --
    so this test runs the generator's own refusal functions over each new
    release, exactly as ``load_releases`` would.
    """

    import importlib
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, str(ROOT / "tools"))
    try:
        generator = importlib.import_module("generate_atlas_v3_full")
    finally:
        sys.path.pop(0)

    releases = [
        *adapters._nrc_releases(ROOT),
        adapters._treasury_releases(ROOT)[1],
    ]
    assert [release.key for release in releases] == [
        "nrc-adams-documented-profile-properties-2026-08-15",
        "nrc-adams-documented-accession-number-2026-08-15",
        "treasury-fast-book-fund-groups-2026-07",
    ]
    for release in releases:
        shaped = SimpleNamespace(
            spec=SimpleNamespace(
                key=release.key,
                logical_path=release.inputs[0].logical_path,
                input_pins=tuple(release.inputs),
            ),
            scheme_iri=release.scheme_iri,
            resources=tuple(release.resources),
        )
        generator._refuse_registrant_population_release(shaped)
        generator._refuse_document_population_release(shaped)
        generator._refuse_observed_inventory_release(shaped)


@pytest.mark.skipif(
    not _GSDM_CAPTURES_PRESENT,
    reason="exact GSDM publisher captures are not present",
)
def test_gsdm_emits_all_dictionary_rows_and_every_published_domain_value() -> None:
    # Boundary-audit repair: the domain-value unit is no longer a hardcoded
    # 3-element "reviewed" tuple; it parses the publisher's own Domain Values
    # column across all 457 elements and emits every inline enumeration.
    structures, domains = adapters._gsdm_releases(ROOT)

    assert len(structures.resources) == 457
    assert structures.metadata["publisherHeaderCount"] == 17
    assert structures.metadata["publisherRowWidth"] == 18

    assert domains.key == "gsdm-data-dictionary-domain-values-2026-08-03"
    assert domains.scheme_iri.endswith(":domain-values")
    assert domains.scope == "captureSubset"
    assert len(domains.resources) == 1_009
    assert domains.metadata["domainValueCount"] == 1_009
    assert domains.metadata["describedValueCount"] == 599
    assert domains.metadata["enumeratedElementCount"] == 203
    assert domains.metadata["referenceOnlyElementCount"] == 86
    assert domains.metadata["emptyDomainValueElementCount"] == 168
    assert (
        domains.metadata["enumeratedElementCount"]
        + domains.metadata["referenceOnlyElementCount"]
        + domains.metadata["emptyDomainValueElementCount"]
        == domains.metadata["elementCount"]
        == 457
    )

    # The verified spot check from the boundary audit: 1862LandGrantCollege
    # publishes 'F = False\nT = True'.
    by_iri = {resource.iri: resource for resource in domains.resources}
    false_flag = by_iri["urn:ref:gsdm:domain-value:1862LandGrantCollege:default:F"]
    assert false_flag.labels[0].value == "False"
    assert false_flag.notations == ("F",)

    # Codeless publisher values ("N/A= sub-contract", bare value lists) carry
    # no notation and use the publisher's value text as identity.
    codeless = [resource for resource in domains.resources if not resource.notations]
    assert len(codeless) == 18
    assert "urn:ref:gsdm:domain-value:SubAwardType:default:sub-contract" in by_iri


@pytest.mark.skipif(
    not _EHRI_CAPTURE_PRESENT,
    reason="the exact EHRI data-standards workbook capture is not present",
)
def test_opm_agency_subelement_roster_is_an_entity_ring_release() -> None:
    # Boundary-audit repair: AGENCY/SUBELEMENT is not a code list, it is the
    # publisher's roster of federal agencies and subelements. It leaves the
    # value-ring EHRI release for the entity ring — complete over exactly the
    # element's current values, nothing wider (the Federal Hierarchy roster
    # is a separate release).
    (roster,) = adapters._opm_releases(ROOT)

    assert roster.ring == "entity"
    assert roster.scope == "completeCapture"
    assert roster.scheme_iri == ("urn:ref:atlas-resource-scheme:opm-ehri-workforce-codes:agency-subelement")
    assert len(roster.resources) == 798
    assert roster.metadata["rosterSize"] == 798
    assert roster.metadata["pastValueCount"] == 3_004
    assert roster.metadata["pastLifecycleAttachedCount"] == 1_748
    assert roster.metadata["pastOnlyIdentityCount"] == 723
    assert roster.metadata["pastValuesAreMembers"] is False
    assert roster.metadata["completeCurrentValueRosterOfElement"] == "AGENCY/SUBELEMENT"
    assert roster.metadata["element"]["name"] == "AGENCY/SUBELEMENT"
    assert roster.metadata["element"]["dataFormat"]

    by_iri = {resource.iri: resource for resource in roster.resources}
    conference = by_iri["urn:ref:opm-ehri-agency-subelement:AA00"]
    assert conference.labels[0].value == "ADMINISTRATIVE CONFERENCE OF THE UNITED STATES"
    assert conference.notations == ("AA00",)
    assert conference.status == "current"
    # pastLifecycle rows are camelCase like their payload siblings and do not
    # repeat the element name, which lives once at release level.
    for resource in roster.resources:
        for row in resource.native_payload["pastLifecycle"]:
            assert set(row) == {"code", "explanation", "fromDate", "throughDate"}
    codes = {resource.notations[0] for resource in roster.resources}
    assert len(codes) == 798


@pytest.mark.skipif(
    not _GSDM_CAPTURES_PRESENT or not _EHRI_CAPTURE_PRESENT,
    reason="all exact local publisher captures are required for the complete adapter set",
)
def test_complete_nonemitter_adapter_set_emits_6371_resources() -> None:
    # 6,338 across 6 releases after the boundary-audit repairs (GSDM domain
    # values completed at 1,009; the EHRI AGENCY/SUBELEMENT roster split out
    # at 798). The REF-032 documented successors move the pin again: the
    # Treasury fund groups (9), the NRC APS profile properties (22), and the
    # NRC accession-number structure (2) join as three more releases.
    releases = adapters.load_registry_nonemitter_releases(ROOT)

    assert len(releases) == 9
    assert sum(len(release.resources) for release in releases) == 6_371
    assert all(not release.key.startswith(("eurovoc-", "lcsh-")) for release in releases)


def test_release_metadata_carries_no_nulls() -> None:
    """The canonical wire grammar rejects nulls; absence is stated by omission.

    The build's json.null rejector runs 130 seconds in -- this is its
    two-second suite twin, added after apiGuideTextOperators shipped a
    publisher-undescribed operator as description: null.
    """

    from collections.abc import Mapping, Sequence

    def scan(value: object, path: str) -> None:
        assert value is not None, f"null at {path}"
        if isinstance(value, Mapping):
            for key, child in value.items():
                scan(child, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    for release in adapters.load_registry_nonemitter_releases(ROOT):
        scan(release.metadata, f"{release.key}.metadata")

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
    # account symbols remain.
    (accounts,) = adapters._treasury_releases(ROOT)

    assert accounts.ring == "entity"
    assert len(accounts.resources) == 3_581
    assert sum(resource.native_payload["duplicatePublisherRowCount"] for resource in accounts.resources) == 1
    assert accounts.metadata["publisherRows"] == 3_582
    assert accounts.metadata["partIMissing"] is True


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
def test_complete_nonemitter_adapter_set_emits_6338_resources() -> None:
    # 4,571 across 5 releases after REF-030/031/032. The boundary-audit
    # repairs move both pins: the GSDM domain-value unit grew from the
    # 3-element reviewed tuple (40 values) to every publisher-enumerated
    # domain value (1,009), and the EHRI AGENCY/SUBELEMENT roster joined as
    # a sixth release (798 entity-ring members).
    releases = adapters.load_registry_nonemitter_releases(ROOT)

    assert len(releases) == 6
    assert sum(len(release.resources) for release in releases) == 6_338
    assert all(not release.key.startswith(("eurovoc-", "lcsh-")) for release in releases)

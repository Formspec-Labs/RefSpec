"""Atlas 3 emission coverage for previously descriptor-only sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from refspec.atlas import v3_registry_nonemitters as adapters

ROOT = Path(__file__).resolve().parents[1]
REAL_DATA = ROOT / "output" / "registry-real-data-sources"


def test_fac_emits_every_distinct_field_as_structure() -> None:
    (release,) = adapters._fac_releases(ROOT)

    assert release.profile == "structureScheme"
    assert len(release.resources) == release.metadata["distinctFieldCount"] == 163
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
    not (REAL_DATA / "gsdm-data-dictionary-2026-08-03.json").is_file()
    or not (REAL_DATA / "gsdm-architecture-v1.0.1.pdf").is_file(),
    reason="exact GSDM publisher captures are not present",
)
def test_gsdm_emits_all_dictionary_rows_and_reviewed_domain_values() -> None:
    structures, domains = adapters._gsdm_releases(ROOT)

    assert len(structures.resources) == 457
    assert len(domains.resources) == 40
    assert structures.metadata["publisherHeaderCount"] == 17
    assert structures.metadata["publisherRowWidth"] == 18
    assert domains.metadata["allStructuralRowsEmitted"] is True


@pytest.mark.skipif(
    not (REAL_DATA / "gsdm-data-dictionary-2026-08-03.json").is_file()
    or not (REAL_DATA / "gsdm-architecture-v1.0.1.pdf").is_file(),
    reason="all exact local publisher captures are required for the complete adapter set",
)
def test_complete_nonemitter_adapter_set_emits_4571_resources() -> None:
    # 4,644 before REF-030; the six registrant-population records (one UEI,
    # one CAGE, three NPI providers, one substance) moved to the entity
    # registry, and their four releases left this adapter set. REF-031 took
    # the one bounded GovInfo CFR package with it, to SpicyRegs. REF-032 took
    # the eight observed inventories: AGROVOC's one sampled concept, EPA's
    # browse-export label tree, GAO's CRA search widgets, the first page of
    # the Federal Hierarchy roster, NALT's two sampled concepts, NRC ADAMS's
    # scraped controls and regexed shapes, and Treasury's fund-type Counter.
    releases = adapters.load_registry_nonemitter_releases(ROOT)

    assert len(releases) == 5
    assert sum(len(release.resources) for release in releases) == 4_571
    assert all(not release.key.startswith(("eurovoc-", "lcsh-")) for release in releases)

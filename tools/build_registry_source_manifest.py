#!/usr/bin/env python3
"""Build the single source-link manifest for the current registry audit."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from refspec.storage import canonical_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "research" / "evidence" / "registry-real-data-audit-2026-08-03" / "sources.json"
URL = re.compile(r"https?://[^\s\"'<>`]+")

ADDITIONAL_URLS = {
    "epa_srs_substances.py": ("https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182",),
    "ferc_elibrary_codes.py": (
        "https://www.ferc.gov/sites/default/files/2025-06/Document%20Class%20Types%20January%202025.pdf",
    ),
    "naics_psc_codes.py": (
        "https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx",
        "https://www.acquisition.gov/sites/default/files/manual/PSC%20April%202025.xlsx",
    ),
    "opm_workforce_codes.py": ("https://data.opm.gov/data-standards/ehri-data-standards",),
}

def _cfr_authority_note_test_inputs() -> dict[str, tuple[dict[str, Any], ...]]:
    """Describe the eCFR part authority notes as ONE response collection.

    The capture is the 49 non-reserved CFR titles' full XML reduced to the
    elements this reader consults -- the same shape ``umthes_content.py``'s
    endpoint archive has, and it takes the same
    ``publisherApiResponseCollection`` provenance. The pins are read from the
    reader's own constants rather than restated here, so a drifted cache fails
    the reader and generation together instead of being described by one and
    refused by the other.

    **One fetch day, 49 issue dates.** Each title was requested at its OWN
    ``latest_issue_date``, so the endpoint the reader states has a placeholder
    the module cannot fill in; the collection's scope says so rather than
    printing one date as if it were all of them.

    What the collection does NOT hold is the 810 MB of raw XML. Each record
    carries its own request URL and the ``raw_sha256`` and ``raw_bytes`` of the
    title document it was cut from, so a re-fetch is checkable byte-for-byte --
    stated in ``scope`` rather than left for a reader to discover, because a
    testInput that claims publisher bytes has to say which bytes it has.
    """

    from refspec.registry import cfr_authority_notes as notes

    return {
        "cfr_authority_notes.py": (
            {
                "name": "ecfrPartAuthorityNotes20260824",
                "localPath": notes.CFR_AUTHORITY_NOTES_ARTIFACT,
                "publisherUrl": "https://www.ecfr.gov/api/versioner/v1/",
                "sha256": notes.NOTES_SHA256,
                "byteLength": notes.NOTES_BYTE_LENGTH,
                "acquisition": "directPublisherDownload",
                "provenance": "publisherApiResponseCollection",
                "scope": (
                    f"{notes.NOTES_EXPECTED_RECORDS} authority notes -- every one the register "
                    f"publishes -- cut from 49 responses to {notes.NOTES_ENDPOINT}, fetched "
                    f"{notes.NOTES_FETCHED}, one per non-reserved CFR title at THAT TITLE's own "
                    "latest issue date (2024-05-17 to 2026-08-20, which is why the endpoint states "
                    "a date it cannot fill in); the publisher's authority-note and source-note text "
                    "with each record's own request URL, sha256 and byte length. The raw XML is not "
                    "retained (810 MB, re-fetchable and checkable against those per-record digests)"
                ),
            },
        ),
    }


def _usc_disposition_table_test_inputs() -> dict[str, tuple[dict[str, Any], ...]]:
    """Describe the printed volume each pinned recodification table was cut from.

    Unlike its two neighbours -- ``usc_act_index.py``, whose acquisition URL was
    never recorded, and ``usc_section_oracle.py``, whose 2.3 GB of publisher
    zips were deleted after extraction -- this reader's publisher bytes ARE
    retained here and reachable: govinfo's 1994 Title 49 volume is committed
    beside the derived table, 5,165,242 bytes, and the extractor re-checks the
    digest AND the byte length before it reads a page. So this is a testInput
    and not a blocker.

    One descriptor per row of ``RECODIFICATIONS``, with the pins and the URL
    read from that row rather than restated here: a second table is a directory
    and a row, and its descriptor should arrive with it rather than waiting for
    someone to remember. The local path is the artifact directory plus the
    URL's own basename, for the same reason -- the module states the URL, and
    the file is the file it names.
    """

    from refspec.registry import usc_disposition_tables as tables

    def named(recodification: Any) -> str:
        """``USCODE-1994-title49`` -> ``uscode1994Title49PrintedVolume``.

        The govinfo package id is what the volume IS, so the name is derived
        from it rather than invented; every other name in this manifest is
        camelCase alphanumerics, so the hyphens are folded rather than kept.
        """

        head, *tail = re.split(r"[^0-9A-Za-z]+", Path(urlsplit(recodification.source_url).path).stem)
        return head.lower() + "".join(part[:1].upper() + part[1:] for part in tail) + "PrintedVolume"

    return {
        "usc_disposition_tables.py": tuple(
            {
                "name": named(recodification),
                "localPath": (
                    f"{tables.USC_DISPOSITION_TABLES_ARTIFACT}/"
                    f"{Path(urlsplit(recodification.source_url).path).name}"
                ),
                "publisherUrl": recodification.source_url,
                "sha256": recodification.source_digest,
                "byteLength": recodification.source_bytes,
                "acquisition": "directPublisherDownload",
                "provenance": "publisherDistribution",
                "scope": (
                    f"the printed volume carrying the disposition table for the {recodification.name} "
                    f"recodification ({recodification.enacted_by}), fetched 2026-08-23; the committed "
                    f"extractor beside it re-checks this sha256 and byte length before reading a page, "
                    f"and writes {recodification.table} at {recodification.digest}"
                ),
            }
            for recodification in tables.RECODIFICATIONS
        ),
    }


def _acquisition_wave_test_inputs() -> dict[str, tuple[dict[str, Any], ...]]:
    """Describe the large publisher captures added by REF-037."""

    from refspec.registry import eurovoc_alignment_portfolio as eurovoc
    from refspec.registry import gemet_alignments as gemet
    from refspec.registry import lc_external_links as lc
    from refspec.registry import lcsh_mesh_mapping as mesh
    from refspec.registry import oclc_fast_external_links as fast
    from refspec.registry import umthes_content as umthes

    source_root = "output/registry-real-data-sources"
    rows: dict[str, tuple[dict[str, Any], ...]] = {
        "lc_external_links.py": (
            {
                "name": "lcshExternalLinks20260815",
                "localPath": f"{source_root}/{lc.LC_EXTERNAL_LINKS_FILENAME}",
                "publisherUrl": lc.LC_EXTERNAL_LINKS_URL,
                "sha256": lc.LC_EXTERNAL_LINKS_SHA256,
                "byteLength": lc.LC_EXTERNAL_LINKS_BYTE_LENGTH,
                "acquisition": "directPublisherDownload",
                "provenance": "publisherDistribution",
            },
        ),
        "oclc_fast_external_links.py": (
            {
                "name": "oclcFastTopicalExternalLinks20260727",
                "localPath": f"{source_root}/{fast.FAST_EXTERNAL_LINKS_FILENAME}",
                "publisherUrl": fast.FAST_EXTERNAL_LINKS_SOURCE_URL,
                "sha256": fast.FAST_EXTERNAL_LINKS_SHA256,
                "byteLength": fast.FAST_EXTERNAL_LINKS_BYTE_LENGTH,
                "acquisition": "inheritedPinnedPublisherDownload",
                "provenance": "publisherDistribution",
            },
        ),
        "gemet_alignments.py": (
            {
                "name": "gemetAlignments423",
                "localPath": f"{source_root}/{gemet.GEMET_ALIGNMENT_FILENAME}",
                "publisherUrl": gemet.GEMET_ALIGNMENT_SOURCE_URL,
                "sha256": gemet.GEMET_ALIGNMENT_SHA256,
                "byteLength": gemet.GEMET_ALIGNMENT_BYTE_LENGTH,
                "acquisition": "directPublisherDownload",
                "provenance": "publisherDistribution",
            },
        ),
        "lcsh_mesh_mapping.py": (
            {
                "name": "northwesternMeshLcshMARCXML20210325",
                "localPath": f"{source_root}/{mesh.LCSH_MESH_MAPPING_FILENAME}",
                "publisherUrl": mesh.LCSH_MESH_MAPPING_SOURCE_URL,
                "sha256": mesh.LCSH_MESH_MAPPING_SHA256,
                "byteLength": mesh.LCSH_MESH_MAPPING_BYTE_LENGTH,
                "acquisition": "directPublisherDownload",
                "provenance": "thirdPartyMappingDistribution",
            },
        ),
        "umthes_content.py": (
            {
                "name": "umthesGemetEndpoints20260815",
                "localPath": f"{source_root}/{umthes.UMTHES_CAPTURE_FILENAME}",
                "publisherUrl": umthes.UMTHES_CAPTURE_SOURCE_ROOT,
                "sha256": umthes.UMTHES_CAPTURE_SHA256,
                "byteLength": umthes.UMTHES_CAPTURE_BYTE_LENGTH,
                "acquisition": "deterministicPublisherResponseArchive",
                "provenance": "publisherApiResponseCollection",
            },
        ),
    }
    rows["eurovoc_alignment_portfolio.py"] = tuple(
        {
            "name": (
                f"eurovocAlignment{pin.key.title().replace('-', '')}"
                f"{pin.version.replace('-', '')}"
            ),
            "localPath": f"{source_root}/{pin.filename}",
            "publisherUrl": pin.source_url,
            "sha256": pin.expected_sha256,
            "byteLength": pin.expected_byte_length,
            "acquisition": "directPublisherDownload",
            "provenance": "publisherDistribution",
        }
        for pin in eurovoc.EUROVOC_ALIGNMENT_PINS
    )
    return rows


TEST_INPUTS: dict[str, tuple[dict[str, Any], ...]] = {
    **_acquisition_wave_test_inputs(),
    **_cfr_authority_note_test_inputs(),
    **_usc_disposition_table_test_inputs(),
    "unified_agenda_editions.py": (
        {
            "name": "unifiedAgendaEdition202510",
            "localPath": (
                "output/registry-real-data-sources/unified-agenda-editions/REGINFO_RIN_DATA_202510.xml"
            ),
            "publisherUrl": ("https://www.reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_202510.xml"),
            "sha256": ("sha256:4dc85fe08251eed1499dee5f2a2f7e3fcf4717baf468409c1f884dd68782b75f"),
            "byteLength": 17_624_465,
            "provenance": "publisherDistribution",
        },
    ),
    "courtlistener_codes.py": (
        {
            "name": "courtlistenerJurisdictions",
            "localPath": "output/registry-real-data-sources/courtlistener-jurisdictions-zyte.html",
            "publisherUrl": "https://www.courtlistener.com/help/api/jurisdictions/",
            "sha256": "sha256:883446028b029078c032bfe7c3545f9e109bb328c79ec486fbbbdbf35580b292",
            "byteLength": 3_156_029,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherPageResponse",
        },
    ),
    "crs_legislative_resources.py": (
        {
            "name": "crsLegislativeSubjects20260730",
            "localPath": "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1/legislative-subject-terms.html",
            "publisherUrl": "https://www.congress.gov/help/field-values/legislative-subject-terms",
            "sha256": "sha256:8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1",
            "byteLength": 410_454,
            "provenance": "publisherPageResponse",
        },
        {
            "name": "crsLegislativeGeographic20260730",
            "localPath": "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0/legislative-subject-geographic-entities.html",
            "publisherUrl": "https://www.congress.gov/help/field-values/legislative-subject-terms/geographic",
            "sha256": "sha256:7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0",
            "byteLength": 384_627,
            "provenance": "publisherPageResponse",
        },
        {
            "name": "crsLegislativeOrganizations20260730",
            "localPath": "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880/legislative-subject-organization-names.html",
            "publisherUrl": "https://www.congress.gov/help/field-values/legislative-subject-terms/organizations",
            "sha256": "sha256:fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880",
            "byteLength": 381_186,
            "provenance": "publisherPageResponse",
        },
        {
            "name": "crsPolicyAreas20260730",
            "localPath": "output/refspec-vocabulary-portfolio/crs/2026-07-30/sha256/16d806e4a07df391de776d0bd5fade9d0bce89fe33b564036c94e0749df91326/policy-areas.html",
            "publisherUrl": "https://www.congress.gov/help/field-values/policy-area",
            "sha256": "sha256:16d806e4a07df391de776d0bd5fade9d0bce89fe33b564036c94e0749df91326",
            "byteLength": 383_558,
            "provenance": "publisherPageResponse",
        },
    ),
    "crs_product_topics.py": (
        {
            "name": "crsProductsPage20260803",
            "localPath": "output/registry-real-data-sources/crs-products-zyte.html",
            "publisherUrl": "https://www.congress.gov/help/crs-products",
            "sha256": "sha256:91c478b93fe4a3588c48bf065d999a5830111f63f9888001bd60cf748ba060cc",
            "byteLength": 371_848,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherPageResponse",
        },
    ),
    "doe_osti_thesaurus.py": (
        {
            "name": "doeOstiThesaurusV12020",
            "localPath": "output/registry-real-data-sources/osti-semantic-thesaurus-2020.rdf",
            "publisherUrl": "https://www.osti.gov/servlets/purl/1668761",
            "sha256": "sha256:aeb9fb2d16caff675c7c9e12e0baff04ac4aded07488944acdf73ed859abe1d5",
            "byteLength": 18_087_998,
            "acquisition": "zyteAttemptThenDirectPublisherDownload",
            "provenance": "publisherDistribution",
        },
    ),
    "cfr_list_of_subjects.py": (
        {
            "name": "ecfrTitles",
            "localPath": "output/registry-real-data-sources/ecfr-titles-zyte.json",
            "publisherUrl": "https://www.ecfr.gov/api/versioner/v1/titles.json",
            "sha256": "sha256:4a1eb3090dfc5a6b13a495d2ad7a5e92ab9c3816098566c637688cb94c871734",
            "byteLength": 8_033,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "ecfrAgencies",
            "localPath": "output/registry-real-data-sources/ecfr-agencies-zyte.json",
            "publisherUrl": "https://www.ecfr.gov/api/admin/v1/agencies.json",
            "sha256": "sha256:766685f466d62fa558a504cdeac23eef1d41f3ea24a2f5a3f78b38f2bcd5365e",
            "byteLength": 98_197,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "ecfrTitle1Structure20260731",
            "localPath": "output/registry-real-data-sources/ecfr-title-1-structure-2026-07-31.json",
            "publisherUrl": "https://www.ecfr.gov/api/versioner/v1/structure/2026-07-31/title-1.json",
            "sha256": "sha256:ac27352aff9ba6822ef2ec3081c5e55fd8bedc1b0a945bc8c53a0e4bda22b1c8",
            "byteLength": 94_089,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "ecfrTitle1Part18FullXml20260731",
            "localPath": "output/registry-real-data-sources/ecfr-title-1-part-18-full-2026-07-31.xml",
            "publisherUrl": "https://www.ecfr.gov/api/versioner/v1/full/2026-07-31/title-1.xml?part=18",
            "sha256": "sha256:32ec60511131ff9f3ac87d2bc6168b9b2dff1df5f177916e8df546f07ae86583",
            "byteLength": 15_270,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "federalRegisterDocument202615493",
            "localPath": "output/registry-real-data-sources/federal-register-document-2026-15493-zyte.json",
            "publisherUrl": "https://www.federalregister.gov/api/v1/documents/2026-15493.json",
            "sha256": "sha256:1983a61f00d6556abe1c6e37d6a605a022471f6fa4e010690b718d5330067c67",
            "byteLength": 4_320,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "federalRegisterDocument9632865",
            "localPath": "output/registry-real-data-sources/federal-register-document-96-32865-zyte.json",
            "publisherUrl": "https://www.federalregister.gov/api/v1/documents/96-32865.json",
            "sha256": "sha256:da1d4e6af2e7e5680c382400034c900630048dc9f980b8b24de86c2cb88364e8",
            "byteLength": 2_928,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
    ),
    # The entity-registry builder (REF-030) consumes the same pinned registrant
    # captures its reader modules parse; it verifies each capture's digest and
    # byte length itself before delegating to the readers.
    "entity_registry_release.py": (
        {
            "name": "comptoxBisphenolAPage",
            "localPath": "output/registry-real-data-sources/comptox-DTXSID7020182.normalized.html",
            "publisherUrl": "https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182",
            "normalization": "stripCompToxSentryTrace",
            "sha256": "sha256:96166f421b896b79f0f0273b26908a5d0dbbcc6ab484e6b15fa41d71ca082803",
            "byteLength": 334_109,
            "provenance": "normalizedPublisherCapture",
        },
        {
            "name": "nppesWeeklyFileHeaderExcerpt",
            "localPath": "tests/fixtures/nppes_npi_identifiers/npidata_pfile_fileheader_v2.csv",
            "publisherUrl": "https://download.cms.gov/nppes/NPPES_Data_Dissemination_072726_080226_Weekly_V2.zip",
            "sha256": "sha256:1f781040d7dae44496be1729250e79114b6dd03f17c10d7d8965486052177679",
            "byteLength": 12_267,
            "provenance": "publisherArchiveEntryExcerpt",
            "scope": "exact file-header entry from the weekly ZIP",
        },
        {
            "name": "nppesWeeklyThreeRowExcerpt",
            "localPath": "tests/fixtures/nppes_npi_identifiers/npidata_pfile_sample_v2.csv",
            "publisherUrl": "https://download.cms.gov/nppes/NPPES_Data_Dissemination_072726_080226_Weekly_V2.zip",
            "sha256": "sha256:3735061e873e5db7cfb422aeaa7eea5514d0a5e8089765c94b82f0d43450a87d",
            "byteLength": 15_866,
            "provenance": "publisherArchiveEntryExcerpt",
            "scope": "three exact provider rows from the weekly ZIP; entity ingestion remains intentionally bounded",
        },
        {
            "name": "samEntity3mPublic",
            "localPath": "output/registry-real-data-sources/sam-entity-3m-public.json",
            "publisherUrl": "https://api.sam.gov/entity-information/v4/entities?ueiSAM=YLQMY5SGNE55&includeSections=entityRegistration",
            "sha256": "sha256:3d14996c9e6954af51a183f26168f9f835891f2ec5ef11e2dc6d3180ce6550a1",
            "byteLength": 1_076,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
    ),
    "epa_srs_substances.py": (
        {
            "name": "comptoxBisphenolAPage",
            "localPath": "output/registry-real-data-sources/comptox-DTXSID7020182.normalized.html",
            "publisherUrl": "https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182",
            "normalization": "stripCompToxSentryTrace",
            "sha256": "sha256:96166f421b896b79f0f0273b26908a5d0dbbcc6ab484e6b15fa41d71ca082803",
            "byteLength": 334_109,
            "provenance": "normalizedPublisherCapture",
        },
    ),
    "ferc_elibrary_codes.py": (
        {
            "name": "fercClassTypes2025Pdf",
            "localPath": "output/registry-real-data-sources/ferc-class-types-january-2025.pdf",
            "publisherUrl": "https://www.ferc.gov/sites/default/files/2025-06/Document%20Class%20Types%20January%202025.pdf",
            "sha256": "sha256:af632c9c6adbf0e7919d17e018b3a65078d0746bd1ab69a8d9fa65043720d688",
            "byteLength": 193_934,
            "provenance": "publisherDistribution",
        },
        {
            "name": "fercDocketPrefix2025Pdf",
            "localPath": "output/registry-real-data-sources/ferc-docket-prefix-june-2025.pdf",
            "publisherUrl": "https://elibrary.ferc.gov/eLibrary/assets/docket-prefix.pdf",
            "sha256": "sha256:c32efae9f51a70b6f955821d2fb3d3025995ef0e17e57bf2d32dfa16c2508dcb",
            "byteLength": 282_729,
            "provenance": "publisherDistribution",
        },
        {
            "name": "fercGeneralSearchHelp",
            "localPath": "output/registry-real-data-sources/ferc-general-search-help.html",
            "publisherUrl": "https://elibrary.ferc.gov/eLibraryhelp/General_Search.htm",
            "sha256": "sha256:1f4b2883879602530c59095cc3d33fedbbf50a2d630e7bdf0226785259dd2b45",
            "byteLength": 7_447,
            "provenance": "publisherDistribution",
        },
    ),
    # The three documented-roster readers (REF-032 follow-ups) consume pinned
    # captures checked in under tests/fixtures/; each reader verifies its
    # capture's digest and byte length itself before parsing.
    "fcc_bureaus_offices.py": (
        {
            "name": "fccOfficesBureausPage20260815",
            "localPath": "tests/fixtures/fcc_bureaus_offices/fcc-offices-bureaus-2026-08-15.html",
            "publisherUrl": "https://www.fcc.gov/offices-bureaus",
            "sha256": "sha256:2915ee13f3dc07081671b70720e26ed1c376e7964d60cffa2ca4c1d7cab41f55",
            "byteLength": 51_748,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherPageResponse",
        },
    ),
    "federal_hierarchy_complete.py": (
        {
            "name": "fhOrgsAllPage0",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-0.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset=0",
            "sha256": "sha256:b684a583f8775ee109cf113949fe1a1c59d1166d2db718b48583272274bca8ff",
            "byteLength": 183_892,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "fhOrgsAllPage1",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-1.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset=200",
            "sha256": "sha256:8043dd5bcc850b0036ed1c28c5f36a55d1bb44e4c0c934548c9f8086f21ad6e2",
            "byteLength": 179_237,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "fhOrgsAllPage2",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-2.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset=400",
            "sha256": "sha256:7dbb2ab10f480f08f661049cda4753d5618983d4ba0c95fca314348f53804c64",
            "byteLength": 181_649,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "fhOrgsAllPage3",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-3.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset=600",
            "sha256": "sha256:90be1eb4f7dafdea9e26e87596f2c17df8d09cdcc8b0a228758ef29a94af1e96",
            "byteLength": 182_189,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "fhOrgsAllPage4",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-all-page-4.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?limit=200&offset=800",
            "sha256": "sha256:bb78b6c039167ef158bea672275c86961be784e269f4db41a52e4b0cd09c277e",
            "byteLength": 100_030,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "fhOrgsTotalDeptWitness",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-total-dept.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?fhorgtype=Department%2FInd.%20Agency&limit=1&offset=0",
            "sha256": "sha256:e08d262428b48a2539c8db513982510e731978220461e7058c155d2a01ab35b6",
            "byteLength": 919,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "fhOrgsTotalSubtierWitness",
            "localPath": "tests/fixtures/federal_hierarchy_complete/fh-orgs-total-subtier.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?fhorgtype=Sub-Tier&limit=1&offset=0",
            "sha256": "sha256:9f23757566e92492e4eeb0bd272a677048a87985bba9db98930f354359431359",
            "byteLength": 898,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
    ),
    "federal_register_native_controls.py": (
        {
            "name": "frApiDocumentation20260815",
            "localPath": "tests/fixtures/federal_register_native_controls/fr-api-documentation-2026-08-15.json",
            "publisherUrl": "https://www.federalregister.gov/api/v1/documentation.json",
            "sha256": "sha256:9190df715f0227e62acb57ff924635fc7115732064a5d2c1fb15a57d80879a42",
            "byteLength": 229_776,
            "provenance": "publisherApiResponse",
        },
        {
            "name": "frDocumentTypeFacets20260815",
            "localPath": "tests/fixtures/federal_register_native_controls/fr-documents-facets-type-2026-08-15.json",
            "publisherUrl": "https://www.federalregister.gov/api/v1/documents/facets/type",
            "sha256": "sha256:fb6ab236d52938e112fa5ff5f36f6b9a6a7f34a4f8009bb7cc4ad9f507ee53f2",
            "byteLength": 187,
            "provenance": "publisherApiResponse",
        },
        {
            "name": "frAgenciesRoster20260815",
            "localPath": "tests/fixtures/federal_register_native_controls/fr-agencies-2026-08-15.json",
            "publisherUrl": "https://www.federalregister.gov/api/v1/agencies",
            "sha256": "sha256:70dd0e8fa373a22d5c9577ac1f70ea736542f0e564f816c3caf28014bd05a92b",
            "byteLength": 694_024,
            "provenance": "publisherApiResponse",
        },
    ),
    "federal_register_topics_api.py": (
        {
            "name": "federalRegisterTopics",
            "localPath": "output/registry-real-data-sources/federal-register-topics-zyte.json",
            "publisherUrl": "https://www.federalregister.gov/api/v1/topics.json",
            "sha256": "sha256:aba80a4dcacbffc7c9ec29eb88ea385ec313510fc8331d0f69078d940d1da35b",
            "byteLength": 920_705,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherApiResponse",
        },
    ),
    "fast_topical.py": (
        {
            "name": "fastTopicalNtZip",
            "localPath": "output/registry-real-data-sources/FASTTopical.nt.zip",
            "publisherUrl": "https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip",
            "archiveUrl": "https://web.archive.org/web/20250223102341id_/https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip",
            "sha256": "sha256:217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db",
            "byteLength": 55_099_212,
            "acquisition": "officialWaybackPublisherReplay",
            "provenance": "archivedPublisherDistribution",
        },
        {
            "name": "fastChanges20241027",
            "localPath": "output/registry-real-data-sources/FASTChanges2024-10-27.mrc",
            "publisherUrl": "https://fast.oclc.org/fastChanges/FASTChanges2024-10-27.mrc",
            "sha256": "sha256:f53c640767cb1c4c0bce85b85a69e382780a65772d4deae30ab3a1a8fa96419a",
            "byteLength": 2_726_812,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherChangeDistribution",
        },
        {
            "name": "fastChanges20241204",
            "localPath": "output/registry-real-data-sources/FASTChanges2024-12-04.mrc",
            "publisherUrl": "https://fast.oclc.org/fastChanges/FASTChanges2024-12-04.mrc",
            "sha256": "sha256:06ae6714240ac1d8126cfeff5392feb8004f6a1d16e2bb392c854ecf47a6a011",
            "byteLength": 1_797_706,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherChangeDistribution",
        },
        {
            "name": "fastChanges20250501",
            "localPath": "output/registry-real-data-sources/FASTChanges2025-05-01.mrc",
            "publisherUrl": "https://fast.oclc.org/fastChanges/FASTChanges2025-05-01.mrc",
            "sha256": "sha256:0d505664fe5de155d58bd1c178e65112ee4b42067044b6a4cb14f516ef03f116",
            "byteLength": 3_827_847,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherChangeDistribution",
        },
        {
            "name": "fastChanges20260213",
            "localPath": "output/registry-real-data-sources/FASTChanges2026-02-13.mrc",
            "publisherUrl": "https://fast.oclc.org/fastChanges/FASTChanges2026-02-13.mrc",
            "sha256": "sha256:98c965420836f0f21aed18599f0216cc61b2f3c2b7ca06cc10f6b9cc1ad374e3",
            "byteLength": 10_220_096,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherChangeDistribution",
        },
    ),
    "federal_hierarchy_orgs.py": (
        {
            "name": "federalHierarchyDefaultPage",
            "localPath": "output/registry-real-data-sources/fh-orgs-default-page.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs",
            "sha256": "sha256:582d409dd3743646dd6ec58acfa2bc8f346168f69b044cd6dd48e06f0c9cba49",
            "byteLength": 9_270,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
        {
            "name": "federalHierarchySubTierPage",
            "localPath": "output/registry-real-data-sources/fh-orgs-sub-tier-page.json",
            "publisherUrl": "https://api.sam.gov/prod/federalorganizations/v1/orgs?fhorgtype=Sub-Tier",
            "sha256": "sha256:601b9e7323cd4e6b1fbde3799533cbfb5c1f88d78039df84a24b6d60533eccd7",
            "byteLength": 9_476,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
    ),
    "gcmd_science_keywords.py": (
        {
            "name": "gcmdScienceKeywords244",
            "localPath": "output/registry-real-data-sources/gcmd-science-keywords-24.4.csv",
            "publisherUrl": "https://gcmd.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords?format=csv",
            "sha256": "sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2",
            "byteLength": 504_190,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherDistribution",
        },
    ),
    # REF-043 closed the gap the old SOURCE_BLOCKERS entry recorded: the
    # column-nesting reader's edges now ship as the derived graph's third
    # registered rule, and the reader is exercised through that rule's own
    # reproduction checks -- the CSV-level oracle here, plus the
    # asserted-payload derivation and its pair-for-pair oracle agreement in
    # tests/test_gcmd_column_nesting.py -- against the same pinned
    # publisher artifact the base reader pins.
    "gcmd_science_keywords_hierarchy.py": (
        {
            "name": "gcmdScienceKeywords244",
            "localPath": "output/registry-real-data-sources/gcmd-science-keywords-24.4.csv",
            "publisherUrl": "https://gcmd.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords?format=csv",
            "sha256": "sha256:f31d8137e860e4231ff312c89e4ffe59d12f636786a47dd2c41e28273a3f02e2",
            "byteLength": 504_190,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherDistribution",
        },
    ),
    "icpsr_subject.py": (
        {
            "name": "icpsrSubjectXml",
            "localPath": "output/registry-real-data-sources/icpsr-subject-6e2651e.xml",
            "publisherUrl": "https://raw.githubusercontent.com/ICPSR/metadata/6e2651e55fb42b119a167f34000ec728d1206865/projects/thesaurus/processed/subject.xml",
            "sha256": "sha256:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff",
            "byteLength": 1_244_558,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherGitRepositoryAtCommit",
        },
    ),
    "lcsh_topical.py": (
        {
            "name": "lcshTopicalPublisherExcerpt",
            "localPath": "tests/fixtures/lcsh_topical/lcsh-topical-mini.ndjson",
            "publisherUrl": "https://id.loc.gov/download/authorities/subjects.madsrdf.jsonld.gz",
            "sha256": "sha256:42b4ef9de8b905de05015c5154b5182307c7ed3b21b6058231c11e09ced0391f",
            "byteLength": 21_599,
            "provenance": "publisherDistributionByteRangeExcerpt",
            "scope": "six exact NDJSON records; not the full 140+ MB distribution",
        },
    ),
    "mesh_descriptors.py": (
        {
            "name": "meshDescriptors2026Xml",
            "localPath": "output/registry-real-data-sources/desc2026.xml",
            "publisherUrl": "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml",
            "sha256": "sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba",
            "byteLength": 312_952_703,
            "acquisition": "zyteAttemptThenDirectPublisherDownload",
            "provenance": "publisherDistribution",
        },
    ),
    "nppes_npi_identifiers.py": (
        {
            "name": "nppesWeeklyFileHeaderExcerpt",
            "localPath": "tests/fixtures/nppes_npi_identifiers/npidata_pfile_fileheader_v2.csv",
            "publisherUrl": "https://download.cms.gov/nppes/NPPES_Data_Dissemination_072726_080226_Weekly_V2.zip",
            "sha256": "sha256:1f781040d7dae44496be1729250e79114b6dd03f17c10d7d8965486052177679",
            "byteLength": 12_267,
            "provenance": "publisherArchiveEntryExcerpt",
            "scope": "exact file-header entry from the weekly ZIP",
        },
        {
            "name": "nppesWeeklyThreeRowExcerpt",
            "localPath": "tests/fixtures/nppes_npi_identifiers/npidata_pfile_sample_v2.csv",
            "publisherUrl": "https://download.cms.gov/nppes/NPPES_Data_Dissemination_072726_080226_Weekly_V2.zip",
            "sha256": "sha256:3735061e873e5db7cfb422aeaa7eea5514d0a5e8089765c94b82f0d43450a87d",
            "byteLength": 15_866,
            "provenance": "publisherArchiveEntryExcerpt",
            "scope": "three exact provider rows from the weekly ZIP; entity ingestion remains intentionally bounded",
        },
    ),
    "nature_of_suit_codes.py": (
        {
            "name": "natureOfSuitOfficialPdf",
            "localPath": "output/registry-real-data-sources/js_044_code_descriptions.pdf",
            "publisherUrl": "https://www.uscourts.gov/sites/default/files/js_044_code_descriptions.pdf",
            "sha256": "sha256:aeaff2476c8cc926191466ff571e91b0f0896858f4f00deed1117c1aa33daa95",
            "byteLength": 316_187,
            "acquisition": "zyteRawHttp",
            "provenance": "publisherDistribution",
            "receiptRequired": False,
        },
        {
            "name": "natureOfSuitPdfLayoutText",
            "localPath": "tests/fixtures/nature_of_suit_codes/js_044_code_descriptions.layout.txt",
            "publisherUrl": "https://www.uscourts.gov/sites/default/files/js_044_code_descriptions.pdf",
            "sha256": "sha256:dcb5ac0d1da85ad597d1e7ae07e91b6b8193e6eb19ae6403a050607eebfde1f2",
            "byteLength": 32_211,
            "provenance": "deterministicPublisherPdfTextExtraction",
            "derivedFromSha256": "sha256:aeaff2476c8cc926191466ff571e91b0f0896858f4f00deed1117c1aa33daa95",
            "extraction": "Poppler pdftotext -layout 26.06.0",
        },
    ),
    "oira_review_codes.py": (
        {
            "name": "oiraAdvancedSearchPage",
            "localPath": "tests/fixtures/oira_review_codes/eo-advanced-search-2026-08-03.html",
            "publisherUrl": "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD",
            "sha256": "sha256:c1f5959d04ed8d57103dffb5d015d926f5f9e4bba41d82426d8d43800b2b9178",
            "byteLength": 3_190,
            "provenance": "publisherPageControlExcerpt",
            "receiptRequired": False,
        },
        {
            "name": "oiraMeetingSearchPage",
            "localPath": "tests/fixtures/oira_review_codes/eo-meeting-search-2026-08-03.html",
            "publisherUrl": "https://www.reginfo.gov/public/do/eom12866Search",
            "sha256": "sha256:357200cde7f3b109db31f1536fd754f582ab41a1b0f51c24420584b53d67668d",
            "byteLength": 874,
            "provenance": "publisherPageControlExcerpt",
            "receiptRequired": False,
        },
        {
            "name": "oiraReviewStatusControl",
            "localPath": "output/registry-real-data-sources/oira-controls/sha256/bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76/reviewStatus.html",
            "publisherUrl": "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD",
            "sha256": "sha256:bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76",
            "byteLength": 405,
            "provenance": "exactPublisherPageControlSpan",
            "derivedFromSha256": "sha256:c1f5959d04ed8d57103dffb5d015d926f5f9e4bba41d82426d8d43800b2b9178",
        },
        {
            "name": "oiraRuleStageControl",
            "localPath": "output/registry-real-data-sources/oira-controls/sha256/90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a/ruleStage.html",
            "publisherUrl": "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD",
            "sha256": "sha256:90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a",
            "byteLength": 1_390,
            "provenance": "exactPublisherPageControlSpan",
            "derivedFromSha256": "sha256:c1f5959d04ed8d57103dffb5d015d926f5f9e4bba41d82426d8d43800b2b9178",
        },
        {
            "name": "oiraConcludedActionControl",
            "localPath": "output/registry-real-data-sources/oira-controls/sha256/a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef/concludedAction.html",
            "publisherUrl": "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD",
            "sha256": "sha256:a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef",
            "byteLength": 570,
            "provenance": "exactPublisherPageControlSpan",
            "derivedFromSha256": "sha256:c1f5959d04ed8d57103dffb5d015d926f5f9e4bba41d82426d8d43800b2b9178",
        },
        {
            "name": "oiraMeetingStatusControl",
            "localPath": "output/registry-real-data-sources/oira-controls/sha256/9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea/meetingStatus.html",
            "publisherUrl": "https://www.reginfo.gov/public/do/eom12866Search",
            "sha256": "sha256:9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea",
            "byteLength": 379,
            "provenance": "exactPublisherPageControlSpan",
            "derivedFromSha256": "sha256:357200cde7f3b109db31f1536fd754f582ab41a1b0f51c24420584b53d67668d",
        },
    ),
    "omb_a11_budget_codes.py": (
        {
            "name": "ombA11OfficialPdf",
            "localPath": "output/registry-real-data-sources/omb-a11-2025-wayback.pdf",
            "publisherUrl": "https://www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf",
            "archiveUrl": "https://web.archive.org/web/20251218202612id_/https://www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf",
            "archiveIndexUrl": "https://web.archive.org/cdx/search/cdx?url=www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf&output=json&filter=statuscode:200&collapse=digest",
            "sha256": "sha256:7b0e6a3b018f6beea1c4b55ff377821fbd16def96354df5b319b2642ecd604c1",
            "byteLength": 15_124_998,
            "acquisition": "zyteArchiveDiscoveryThenDirectReplay",
            "provenance": "archivedPublisherDistribution",
            "receiptRequired": False,
        },
        {
            "name": "ombA11Exhibit79AExtract",
            "localPath": "tests/fixtures/omb_a11_budget_codes/exhibit-79a-functional-classification-2025.txt",
            "publisherUrl": "https://www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf",
            "sha256": "sha256:0a8f141ffbbd83b4d9de7e099249ff6eb4eed53c688b14afbde3e9a2f0e496bb",
            "byteLength": 3_635,
            "provenance": "publisherPdfTableExtract",
            "derivedFromSha256": "sha256:7b0e6a3b018f6beea1c4b55ff377821fbd16def96354df5b319b2642ecd604c1",
        },
        {
            "name": "ombA11Exhibit83AExtract",
            "localPath": "tests/fixtures/omb_a11_budget_codes/exhibit-83a-object-classification-2025.txt",
            "publisherUrl": "https://www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf",
            "sha256": "sha256:3714b8b88982f87dc491061d316bc89dbc2151a97b3aa7b3add1726738b4b325",
            "byteLength": 1_886,
            "provenance": "publisherPdfTableExtract",
            "derivedFromSha256": "sha256:7b0e6a3b018f6beea1c4b55ff377821fbd16def96354df5b319b2642ecd604c1",
        },
        {
            "name": "ombA11Section12013Extract",
            "localPath": "tests/fixtures/omb_a11_budget_codes/section-120-13-apportionment-categories-2025.txt",
            "publisherUrl": "https://www.whitehouse.gov/wp-content/uploads/2025/08/a11.pdf",
            "sha256": "sha256:e0e4f4d718add1b21d5106f454e45e3c30a0a5896a964032b3dc249b1aeb871a",
            "byteLength": 3_377,
            "provenance": "publisherPdfSectionExtract",
            "derivedFromSha256": "sha256:7b0e6a3b018f6beea1c4b55ff377821fbd16def96354df5b319b2642ecd604c1",
        },
    ),
    "elsst.py": (
        {
            "name": "elsstR6",
            "localPath": "output/registry-real-data-sources/ELSST_R6.ttl",
            "publisherUrl": "https://storage.googleapis.com/cessda-elsst-datadump/2025/ELSST_R6.ttl",
            "sha256": "sha256:c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95",
            "byteLength": 19_915_491,
            "provenance": "publisherCapture",
        },
    ),
    "federal_register_thesaurus_2025.py": (
        {
            "name": "federalRegister2025",
            "localPath": "output/registry-real-data-sources/federal-register-thesaurus-2025.pdf",
            "publisherUrl": "https://www.archives.gov/files/federal-register/cfr/thesaurus-4-1-2025.pdf",
            "sha256": "sha256:66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f",
            "byteLength": 1_051_423,
            "provenance": "publisherCapture",
        },
    ),
    "gemet_thesaurus.py": (
        {
            "name": "gemet",
            "localPath": "output/registry-real-data-sources/gemet.rdf",
            "publisherUrl": "https://www.eionet.europa.eu/gemet/latest/gemet.rdf.gz",
            "compression": "gzip",
            "downloadSha256": "sha256:96002bb7cd1f89bccb05ee174fb834a04dd7342bdd1428f32105cd47fd6b73b6",
            "sha256": "sha256:1b784b1a6387b8ec6c0d75ea5f0543970933172fcb0428a52de2c8ca536d20f1",
            "byteLength": 33_332_557,
            "provenance": "publisherDistribution",
        },
    ),
    "eurovoc_thesaurus.py": (
        {
            "name": "eurovocDomainSample",
            "localPath": "tests/fixtures/eurovoc_thesaurus/eurovoc-domains-sample-2026-08-03.ttl",
            "publisherUrl": (
                "http://publications.europa.eu/webapi/rdf/sparql?query="
                "PREFIX+rdf%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F1999%2F02%2F22-rdf-syntax-ns%23%3E%0A"
                "PREFIX+skos%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F2004%2F02%2Fskos%2Fcore%23%3E%0A"
                "PREFIX+dc%3A+%3Chttp%3A%2F%2Fpurl.org%2Fdc%2Felements%2F1.1%2F%3E%0A"
                "PREFIX+dcterms%3A+%3Chttp%3A%2F%2Fpurl.org%2Fdc%2Fterms%2F%3E%0A"
                "PREFIX+owl%3A+%3Chttp%3A%2F%2Fwww.w3.org%2F2002%2F07%2Fowl%23%3E%0A"
                "PREFIX+euvoc%3A+%3Chttp%3A%2F%2Fpublications.europa.eu%2Fontology%2Feuvoc%23%3E%0A"
                "CONSTRUCT+%7B+%3Fs+%3Fp+%3Fo+.+%7D%0AWHERE+%7B%0A++VALUES+%3Fs+%7B%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100141%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2Fdomains%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100142%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100143%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100165%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100170%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F4157%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F4159%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F3313%3E%0A"
                "++++%3Chttp%3A%2F%2Feurovoc.europa.eu%2F2189%3E%0A++%7D%0A++%3Fs+%3Fp+%3Fo+.%0A++FILTER%28%0A"
                "++++%3Fp+IN+%28%0A++++++rdf%3Atype%2C+skos%3AinScheme%2C+skos%3AtopConceptOf%2C%0A"
                "++++++skos%3Abroader%2C+skos%3Anarrower%2C+skos%3Anotation%2C+dc%3Aidentifier%2C%0A"
                "++++++dcterms%3Aidentifier%2C+dcterms%3AisPartOf%2C+euvoc%3Adomain%2C+euvoc%3Astatus%2C%0A"
                "++++++owl%3AversionInfo%0A++++%29%0A"
                "++++%7C%7C+%28%3Fp+%3D+skos%3AhasTopConcept+%26%26+%3Fs+%21%3D+%3Chttp%3A%2F%2Feurovoc.europa.eu%2F100141%3E%29%0A"
                "++++%7C%7C+%28%3Fp+IN+%28skos%3AprefLabel%2C+skos%3AaltLabel%29+%26%26+lang%28%3Fo%29+IN+"
                "%28%22en%22%2C%22fr%22%2C%22de%22%2C%22es%22%2C%22el%22%29%29%0A++%29%0A%7D%0A"
            ),
            "sha256": "sha256:94e5a1999c4a67d057f57558452f473c98858ad7bf9a39add9f3a52135f3e390",
            "byteLength": 9_897,
            "provenance": "publisherCapture",
        },
    ),
    "eurovoc_lcsh_alignment.py": (
        {
            "name": "eurovocLcshAlignment",
            "localPath": "output/registry-real-data-sources/eurovoc-lcsh-alignment-20240711.rdf",
            "publisherUrl": (
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc_alignment_lcsh%2F20240711-0%2Frdf%2Fskos_core_alignment%2Falign_EuroVoc_LCSH.rdf&fileName=align_EuroVoc_LCSH.rdf"
            ),
            "sha256": "sha256:dbd6e610ff497c4a39a79924cf50dcf92d5f3e9ab316d58d83c460dba6fb4853",
            "byteLength": 332_124,
            "provenance": "publisherDistribution",
        },
    ),
    "claim_release_exports.py": (
        {
            "name": "eurovocSkosCore",
            "localPath": "output/registry-real-data-sources/eurovoc-4.24-skos-core.zip",
            "publisherUrl": (
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fzip%2Fskos_core%2Feurovoc_in_skos_core_concepts.zip&fileName=eurovoc_in_skos_core_concepts.zip"
            ),
            "sha256": "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
            "byteLength": 8_567_290,
            "provenance": "publisherDistribution",
        },
        {
            "name": "eurovocMetadata",
            "localPath": "output/registry-real-data-sources/eurovoc-4.24-metadata.ttl",
            "publisherUrl": (
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&fileName=eurovoc_metadata.ttl"
            ),
            "sha256": "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
            "byteLength": 36_011,
            "provenance": "publisherDistribution",
        },
        {
            "name": "gemet",
            "localPath": "output/registry-real-data-sources/gemet.rdf",
            "publisherUrl": (
                "https://www.eionet.europa.eu/gemet/latest/gemet.rdf.gz"
            ),
            "sha256": "sha256:1b784b1a6387b8ec6c0d75ea5f0543970933172fcb0428a52de2c8ca536d20f1",
            "byteLength": 33_332_557,
            "provenance": "publisherDistribution",
        },
    ),
    # REF-046 closed the gap the old SOURCE_BLOCKERS entry recorded: the
    # organization experiment's 127 microthesauri and 7,902 memberships
    # now ship as a real Atlas release (eurovoc-microthesauri-4.24) and the
    # microthesaurus-to-domain notation-prefix link now ships as the
    # derived graph's fifth registered rule, and the module is exercised
    # through a real-data test over the same pinned publisher artifact
    # `claim_release_exports.py` already pins -- one shared pin for one
    # shared artifact, not a second capture.
    "eurovoc_organization_experiment.py": (
        {
            "name": "eurovocSkosCore",
            "localPath": "output/registry-real-data-sources/eurovoc-4.24-skos-core.zip",
            "publisherUrl": (
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fzip%2Fskos_core%2Feurovoc_in_skos_core_concepts.zip&fileName=eurovoc_in_skos_core_concepts.zip"
            ),
            "sha256": "sha256:91bdb24e833ba431707f3980a19f475434ea8dcddb2b4d5e32e79e9fc1a0ca2f",
            "byteLength": 8_567_290,
            "provenance": "publisherDistribution",
        },
        {
            "name": "eurovocMetadata",
            "localPath": "output/registry-real-data-sources/eurovoc-4.24-metadata.ttl",
            "publisherUrl": (
                "https://op.europa.eu/o/opportal-service/euvoc-download-handler?cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2Feurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&fileName=eurovoc_metadata.ttl"
            ),
            "sha256": "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d",
            "byteLength": 36_011,
            "provenance": "publisherDistribution",
        },
    ),
    "nasa_thesaurus.py": (
        {
            "name": "nasaThesaurusSkos",
            "localPath": "output/registry-real-data-sources/thesaurus-SKOS.xml",
            "publisherUrl": "https://sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml",
            "sha256": "sha256:3cd92a0eb67c5656e4c740394abd2d27042ded79a4acf3e1286e73a7d863010f",
            "byteLength": 32_943_406,
            "provenance": "publisherDistribution",
        },
    ),
    "naics_psc_codes.py": (
        {
            "name": "naics2022Xlsx",
            "localPath": "output/registry-real-data-sources/2-6-digit_2022_Codes.xlsx",
            "publisherUrl": "https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx",
            "sha256": "sha256:be12ba41002803359f49181c9bf33a03fbd08578f4f4a4c0bbad7aadaaea0316",
            "byteLength": 82_460,
            "provenance": "publisherDistribution",
        },
        {
            "name": "pscApril2025Xlsx",
            "localPath": "output/registry-real-data-sources/PSC-April-2025-wayback.xlsx",
            "publisherUrl": "https://www.acquisition.gov/sites/default/files/manual/PSC%20April%202025.xlsx",
            "archiveUrl": "https://web.archive.org/web/20250422004751id_/https://www.acquisition.gov/sites/default/files/manual/PSC%20April%202025.xlsx",
            "archiveIndexUrl": "https://web.archive.org/cdx/search/cdx?url=www.acquisition.gov/sites/default/files/manual/PSC%20April%202025.xlsx&output=json&filter=statuscode:200",
            "sha256": "sha256:5ae8159d8dff645f24e5b397decc4914f7efebb25f7777cbea8e75ab7e8430f4",
            "byteLength": 462_762,
            "acquisition": "zyteArchiveDiscoveryThenDirectReplay",
            "provenance": "archivedPublisherDistribution",
        },
    ),
    "opm_workforce_codes.py": (
        {
            "name": "opmEhriDataStandardsXlsx",
            "localPath": "output/registry-real-data-sources/EHRI-Data-Standards-20260804.xlsx",
            "publisherUrl": "https://data.opm.gov/data-standards/ehri-data-standards",
            "acquisition": "browserExport",
            "sha256": "sha256:6978bd6d76158f029d468982737fcd68e6dd742c2aedaa9ab5dca151d2a84bfc",
            "byteLength": 1_154_183,
            "provenance": "publisherDistribution",
        },
    ),
    "regulations_gov_agencies.py": (
        {
            "name": "regulationsGovAgencies20260816",
            "localPath": (
                "tests/fixtures/regulations_gov_agencies/"
                "regulations-gov-agencies-2026-08-16.json"
            ),
            "publisherUrl": "https://api.regulations.gov/v4/agencies",
            "sha256": (
                "sha256:28ab9f5422dd27fc7906ddc696e8e7811"
                "b11056822f370bcee7ea18a28418fa2"
            ),
            "byteLength": 91_408,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
    ),
    "uei_cage_identifiers.py": (
        {
            "name": "samEntity3mPublic",
            "localPath": "output/registry-real-data-sources/sam-entity-3m-public.json",
            "publisherUrl": "https://api.sam.gov/entity-information/v4/entities?ueiSAM=YLQMY5SGNE55&includeSections=entityRegistration",
            "sha256": "sha256:3d14996c9e6954af51a183f26168f9f835891f2ec5ef11e2dc6d3180ce6550a1",
            "byteLength": 1_076,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
    ),
}

# These files are admitted only when the named module-level immutable pin
# matches their exact digest and length. This is an explicit allowlist, not
# fixture discovery: constructed mini fixtures are intentionally absent.
PINNED_FIXTURE_INPUTS: dict[str, tuple[dict[str, str], ...]] = {
    "billstatus_codes.py": (
        {
            "name": "billstatusUserGuide",
            "constant": "BILLSTATUS_USER_GUIDE_2026_08_03",
            "localPath": "tests/fixtures/billstatus_codes/billstatus-xml-user-guide-2026-08-03.md",
        },
    ),
    "cbo_topic_codes.py": (
        {
            "name": "cbo119CongressFeed",
            "constant": "CBO_119TH_CONGRESS_REAL_CAPTURE_2026_08_04",
            "localPath": "tests/fixtures/cbo_topic_codes/cbo-119congress-cost-estimates-2026-08-04.xml",
        },
    ),
    "census_geo_codes.py": (
        {
            "name": "gnisFileFormat",
            "constant": "GNIS_FILE_FORMAT_PIN_2026_08_03",
            "localPath": "tests/fixtures/census_geo_codes/gnis-file-format-2026-08-03.pdf",
        },
    ),
    "census_gov_finance_codes.py": (
        {
            "name": "censusFunctionItemCodes",
            "constant": "CENSUS_FUNCTION_ITEM_CODES_2026_08_03",
            "localPath": "tests/fixtures/census_gov_finance_codes/census-aspep-function-item-codes-2026-08-03.html",
        },
        {
            "name": "censusDataFlagCodes",
            "constant": "CENSUS_DATA_FLAG_CODES_2026_08_03",
            "localPath": "tests/fixtures/census_gov_finance_codes/census-aspep-data-flag-codes-2026-08-03.html",
        },
    ),
    "fac_dictionary.py": (
        {
            "name": "facDictionaryDocs",
            "constant": "FAC_DICTIONARY_DOC_2026_08_03",
            "localPath": "tests/fixtures/fac_dictionary/fac-api-dictionary-2026-08-03.html",
        },
    ),
    "fcc_ecfs_codes.py": (
        {
            "name": "fccEcfsFilings",
            "constant": "FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03",
            "localPath": "tests/fixtures/fcc_ecfs_codes/fcc-ecfs-filings-2026-08-03.json",
        },
    ),
    "fec_committee_codes.py": (
        {
            "name": "fecCommitteeMaster",
            "constant": "FEC_COMMITTEE_MASTER_FILE_2026_08_03",
            "localPath": "tests/fixtures/fec_committee_codes/fec-committee-master-file-description-2026-08-03.html",
        },
        {
            "name": "fecCommitteeTypes",
            "constant": "FEC_COMMITTEE_TYPE_CODES_2026_08_03",
            "localPath": "tests/fixtures/fec_committee_codes/fec-committee-type-code-descriptions-2026-08-03.html",
        },
        {
            "name": "fecPartyCodes",
            "constant": "FEC_PARTY_CODES_2026_08_03",
            "localPath": "tests/fixtures/fec_committee_codes/fec-party-code-descriptions-2026-08-03.html",
        },
    ),
    "gao_cra_form_codes.py": (
        # The current revision's publisher URL carries GAO's own "Sumission"
        # typo; the pin constant resolves it verbatim, never corrected.
        {
            "name": "gaoCraCurrentForm20260815",
            "constant": "GAO_CRA_CURRENT_FORM_2026_08_15",
            "localPath": "tests/fixtures/gao_cra_form_codes/gao-cra-submission-form-rev-12-24-2026-08-15.pdf",
        },
        {
            "name": "gaoCraRetiredForm20260815",
            "constant": "GAO_CRA_RETIRED_FORM_2026_08_15",
            "localPath": "tests/fixtures/gao_cra_form_codes/gao-cra-blank-form-rev-11-17-23-2026-08-15.pdf",
        },
        {
            "name": "gaoCraInstitutionalPriorityBridge20090420",
            "constant": "GAO_CRA_INSTITUTIONAL_BRIDGE_2026_08_15",
            "localPath": "tests/fixtures/gao_cra_form_codes/gao-09-205-2009-04-20-2026-08-15.pdf",
        },
    ),
    "gao_published_topics.py": (
        {
            "name": "gaoTopicsIndex20260815",
            "constant": "GAO_TOPICS_2026_08_15",
            "localPath": "tests/fixtures/gao_published_topics/gao-topics-2026-08-15.html",
        },
    ),
    "govinfo_collections.py": (
        {
            "name": "govinfoCollections",
            "constant": "GOVINFO_COLLECTIONS_2026_08_03",
            "localPath": "tests/fixtures/govinfo_collections/govinfo-collections-2026-08-03.json",
        },
        {
            "name": "govinfoEcfrTitles",
            "constant": "ECFR_CFR_TITLES_2026_08_03",
            "localPath": "tests/fixtures/govinfo_collections/ecfr-cfr-titles-2026-08-03.json",
        },
        {
            "name": "govinfoCfrSummary",
            "constant": "GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03",
            "localPath": "tests/fixtures/govinfo_collections/govinfo-package-summary-cfr-2023-title1-vol1-2026-08-03.json",
        },
        {
            "name": "govinfoCfrPremis",
            "constant": "GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03",
            "localPath": "tests/fixtures/govinfo_collections/govinfo-premis-cfr-2023-title1-vol1-mini-2026-08-03.xml",
        },
    ),
    "grants_gov_codes.py": (
        {
            "name": "grantsGovStatusCodes",
            "constant": "GRANTS_GOV_STATUS_CODES_2026_08_03",
            "localPath": "tests/fixtures/grants_gov_codes/grants-gov-status-codes-2026-08-03.html",
        },
    ),
    "lda_controlled_codes.py": (
        {
            "name": "ldaGeneralIssueCodes",
            "constant": "LDA_GENERAL_ISSUE_CODES_2026_07_30",
            "localPath": "tests/fixtures/lda-general-issue-codes-2026-07-30.json",
        },
        {
            "name": "ldaFilingTypes",
            "constant": "LDA_FILING_TYPES_2026_07_30",
            "localPath": "tests/fixtures/lda-filing-types-2026-07-30.json",
        },
    ),
    "nasa_technology_taxonomy.py": (
        {
            "name": "nasaTechnologyRoots",
            "constant": "NASA_TAXONOMY_ROOT_INDEX_2026_08_03",
            "localPath": "tests/fixtures/nasa_technology_taxonomy/techport-taxonomy-roots-2026-08-03.json",
        },
        {
            "name": "nasaTechnologyChildren",
            "constant": "NASA_TAXONOMY_ROOT_CHILDREN_2026_08_03",
            "localPath": "tests/fixtures/nasa_technology_taxonomy/techport-taxonomy-8817-children-2026-08-03.json",
        },
    ),
    "nrc_adams_aps_docs.py": (
        {
            "name": "nrcApsUserManual20260815",
            "constant": "APS_USER_MANUAL_2026_08_15",
            "localPath": "tests/fixtures/nrc_adams_aps_docs/aps-user-manual-2026-08-15.pdf",
        },
        {
            "name": "nrcApsApiGuide20260815",
            "constant": "APS_API_GUIDE_2026_08_15",
            "localPath": "tests/fixtures/nrc_adams_aps_docs/aps-api-guide-v1-2026-08-15.pdf",
        },
    ),
    "oversight_report_types.py": (
        {
            "name": "oversightReportTypes",
            "constant": "OVERSIGHT_REPORT_TYPES_2026_08_03",
            "localPath": "tests/fixtures/oversight_report_types/oversight-reports-federal-2026-08-03.html",
        },
    ),
    "pra_icr_codes.py": (
        {
            "name": "praSearchCodes",
            "constant": "PRA_SEARCH_PAGE_2026_08_03",
            "localPath": "tests/fixtures/pra_icr_codes/pra-search-2026-08-03.html",
        },
    ),
    "regulations_gov_codes.py": (
        {
            "name": "regulationsGovOpenApi",
            "constant": "RGOV_OPENAPI_2026_08_03",
            "localPath": "tests/fixtures/regulations_gov_codes/regulations-gov-openapi-v4-2026-08-03.yaml",
        },
    ),
    "sam_assistance_listing_codes.py": (
        {
            "name": "samAssistanceDocs",
            "constant": "SAM_ASSISTANCE_DOC_2026_08_03",
            "localPath": "tests/fixtures/sam_assistance_listing_codes/sam-assistance-listings-api-2026-08-03.html",
        },
    ),
    "sam_opportunities_codes.py": (
        {
            "name": "samOpportunitiesDocs",
            "constant": "SAM_OPPORTUNITIES_DOC_2026_08_03",
            "localPath": "tests/fixtures/sam_opportunities_codes/sam-get-opportunities-public-api-2026-08-03.html",
        },
    ),
    "treasury_tas_fast_book.py": (
        {
            "name": "treasuryTasFormat",
            "constant": "TAS_COMPONENT_FORMAT_2026_08_03",
            "localPath": "tests/fixtures/treasury_tas_fast_book/treasury-account-symbol-reporting-2026-08-03.html",
        },
        {
            "name": "treasuryFastBook",
            "constant": "FAST_BOOK_DESCRIPTION_2026_08_03",
            "localPath": "tests/fixtures/treasury_tas_fast_book/fast-book-description-of-contents-2026-08-03.html",
            "receiptRequired": False,
        },
        {
            "name": "treasuryFastBookPartIIIII",
            "constant": "FAST_BOOK_PART_II_III_2026_07_31",
            "localPath": "tests/fixtures/treasury_tas_fast_book/fast-book-part-ii-iii-2026-07-31.xlsx",
        },
    ),
    "usaspending_gsdm_codes.py": (
        {
            "name": "usaspendingAwardTypes",
            "constant": "USASPENDING_AWARD_TYPES_2026_08_03",
            "localPath": "tests/fixtures/usaspending_gsdm_codes/usaspending-award-types-2026-08-03.json",
        },
    ),
    "unified_agenda_codes.py": (
        {
            "name": "unifiedAgendaSchema",
            "constant": "UA_REGINFO_SCHEMA_2026_08_03",
            "localPath": "tests/fixtures/unified_agenda_codes/reginfo-rin-data-ver10262011.xsd",
        },
        {
            "name": "unifiedAgendaPreamble",
            "constant": "UA_RISC_PREAMBLE_2026_08_03",
            "localPath": "tests/fixtures/unified_agenda_codes/risc-preamble-202210.pdf",
        },
    ),
}


# REF-046 closed the last entry (eurovoc_organization_experiment.py): its
# 127 microthesauri and 7,902 memberships now ship as a real Atlas release
# and its notation-prefix link now ships as the derived graph's fifth
# registered rule, exercised through a real-data test over the pinned
# publisher artifact declared in TEST_INPUTS above.
#: Top-level modules that read strings, never publisher bytes. The nested
#: auto-support rule reasons that a module naming no publisher cannot be
#: reading one; these are the top-level modules that rule would cover, listed
#: by name rather than by broadening a heuristic, because a reader that stops
#: naming its publisher must still fail loudly.
STRING_GRAMMAR_MODULES: frozenset[str] = frozenset(
    {
        "citation_grammar.py",
        "identifier_shapes.py",
        # The minting layer spells identifiers for values callers supply,
        # wrapping the two grammars above; it reads no publisher bytes of its
        # own. Its census tests read the same pinned columns
        # identifier_shapes' tests read, under that module's coverage.
        "iri_minting.py",
    }
)

SOURCE_BLOCKERS: dict[str, list[str]] = {
    # The builder does read the pinned editions, but its tests read the built
    # artifact instead: parsing sixty publisher XML editions per test run buys
    # nothing the artifact digests do not already pin. The gap is real, so it
    # is named rather than claimed away -- the publisher-byte coverage for
    # these editions lives in unified_agenda_editions.py, which reads them.
    "unified_agenda_parquet.py": [(
        "tests verify the built Parquet artifact against its receipt, not the "
        "publisher editions it was built from; those bytes are covered by "
        "unified_agenda_editions.py"
    )],
    # The crosswalk carries the sealed 2026-08-02 build's mapping as curated
    # in-module rows. The sealed receipt and the three still-intact input
    # parquets came home 2026-08-31 to the repo's own output/
    # (docs/regeneration-inputs.md records the move); the fourth input was
    # overwritten in place before the salvage and its sealed bytes survive
    # nowhere, so the gap on it is permanent unless they resurface.
    "agency_crosswalk.py": [(
        "publisher bytes are not retained here: the module embeds the sealed "
        "agency-crosswalk-2026-08-02 mapping (316 codes, 914 ranked candidates) whose "
        "receipt and three intact input parquets live at "
        "output/registry-real-data-sources/rin-ontology-revision-candidate/ (came home "
        "2026-08-31) with sha256 pins restated in AGENCY_CROSSWALK_INPUT_DIGESTS; "
        "fr_docket_links.parquet was overwritten after sealing (893,766 rows vs the pinned "
        "715,080) and the sealed bytes survive nowhere, so the sealed tier histogram can be "
        "verified against the embedded rows but no longer exactly re-derived from the inputs"
    )],
    # Act resolution reads sha256-pinned artifacts built from the OLRC pages
    # elsewhere; this repository does not retain the publisher bytes. Named,
    # rather than dressed up as a publisher capture it does not hold.
    "act_resolution.py": [(
        "publisher bytes are not retained here: act resolution reads sha256-pinned "
        "artifacts (output/usc-act-index-2026-08-02, output/usc-source-credit-index-2026-08-02) "
        "whose receipt records https://uscode.house.gov/popularnames/popularnames.htm at "
        "sha256:50687ac0116114b1d16ce59460f6092539cb00977c0c428e574a874b81e018b4"
    )],
    # This reader DOES hold the publisher bytes -- OLRC's whole-of-Table-III
    # release, output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip,
    # 14,966,992 bytes at sha256:93e1f233e081e47fc3680c4b699151c6d66329988fe21
    # add3b6e9e62746aeea7, carrying fulldump@119-73.xml at 126,260,704 bytes --
    # and the module pins all four numbers and re-checks them on every build and
    # every --verify. What it cannot state is the URL those bytes arrived from:
    # the 2026-08-05 acquisition pass recorded "fetched by plain curl" and no
    # address (research/vocabulary-atlas-spine-and-rings-takeaways-2026-08-06.md),
    # and OLRC has since moved to release point 119-102 -- probed 2026-08-22,
    # /table3/, /download/releasepoints/us/pl/119/73/ and /classification/ all
    # answer the site's soft-404 page for fulldump@119-73 in either extension,
    # and neither download.shtml nor classification/tables.shtml links a bulk
    # Table III file at all. A testInput must carry a publisherUrl, so naming
    # the gap is the only honest entry: guessing a plausible OLRC path would
    # pin a digest to an address nobody verified.
    "usc_act_index.py": [
        (
            "the publisher bytes ARE retained and digest-pinned "
            "(output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip, 14966992 bytes, "
            "sha256:93e1f233e081e47fc3680c4b699151c6d66329988fe21add3b6e9e62746aeea7), but their "
            "acquisition URL was never recorded and OLRC no longer serves release point 119-73 at "
            "any probed path, so no publisherUrl can be stated without inventing one"
        )
    ],
    # The exact mirror of the entry above, and the reason it is a blocker
    # rather than a testInput. Here the ACQUISITION IS RECORDED -- release
    # point 119-102 and the 31 annual XHTML archives, both URLs stated in the
    # module docstring and therefore in declaredUrls, with a re-fetch sha256
    # and byte length for all 32 zips in
    # research/evidence/usc-section-oracle-2026-08-22/README.md, plus a
    # row-for-row reproduction check of all six derived tables from those
    # bytes. What is missing is the BYTES: ~2.3 GB of publisher zips were
    # deleted after extraction and are not retained in this repository, so
    # there is no localPath to pin them at. The six DERIVED tables are pinned
    # (_ORACLE_PINS, re-checked on every read, and asserted against the
    # README's Files table by test_every_oracle_table_is_the_one_the_artifact_readme_states),
    # but a derived Parquet is not a publisher byte and calling it one would
    # claim coverage this reader does not have.
    "usc_section_oracle.py": [
        (
            "the acquisition IS recorded and re-verified -- "
            "https://uscode.house.gov/download/releasepoints/us/pl/119/102/xml_uscAll@119-102.zip "
            "and the 31 annual XHTML archives, every zip carrying a re-fetch sha256, a matching "
            "byte length and a row-for-row reproduction check in "
            "research/evidence/usc-section-oracle-2026-08-22/README.md -- but the ~2.3 GB of "
            "publisher zips were deleted after extraction and are not retained here; this reader "
            "holds only the six DERIVED oracle tables, digest-pinned in the module and re-checked "
            "on every load"
        )
    ],
}

NESTED_MODULE_AUDIT: dict[str, dict[str, Any]] = {
    "adapters/concept_domain_bridge.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "adapters/crs_zyte.py": {
        "auditRole": "networkHarness",
        "coveredBy": ["crs_legislative_resources.py"],
        "inputRefs": [("crs_legislative_resources.py", "crsLegislativeSubjects20260730")],
    },
    "adapters/elsst_acquisition.py": {
        "auditRole": "networkHarness",
        "coveredBy": ["elsst.py"],
        "inputRefs": [("elsst.py", "elsstR6")],
    },
    "adapters/elsst_import_coverage.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["elsst.py"],
        "inputRefs": [("elsst.py", "elsstR6")],
    },
    "adapters/icpsr_zyte.py": {
        "auditRole": "networkHarness",
        "coveredBy": ["icpsr_subject.py"],
        "inputRefs": [],
    },
    "infrastructure/artifact_serialization.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "infrastructure/controlled_identifier.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "infrastructure/identifier_validation.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "infrastructure/managed_vocabulary_bundle.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "infrastructure/pinned_acquisition.py": {
        "auditRole": "networkHarness",
        "coveredBy": ["adapters/elsst_acquisition.py"],
        "inputRefs": [("elsst.py", "elsstR6")],
    },
    "infrastructure/semantic_foundation.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "infrastructure/source_controlled_resource.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["packages/federal_register_topics_package.py"],
        "inputRefs": [("federal_register_topics_api.py", "federalRegisterTopics")],
    },
    "infrastructure/source_concept_release.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["packages/crs_source_concept_releases.py"],
        "inputRefs": [
            ("crs_legislative_resources.py", "crsLegislativeSubjects20260730"),
            ("crs_legislative_resources.py", "crsLegislativeGeographic20260730"),
            ("crs_legislative_resources.py", "crsLegislativeOrganizations20260730"),
            ("crs_legislative_resources.py", "crsPolicyAreas20260730"),
        ],
    },
    "infrastructure/source_identity.py": {
        "auditRole": "support",
        "coveredBy": [],
        "inputRefs": [],
    },
    "infrastructure/zyte_transport.py": {
        "auditRole": "networkHarness",
        "coveredBy": ["adapters/crs_zyte.py", "adapters/icpsr_zyte.py"],
        "inputRefs": [
            ("crs_legislative_resources.py", "crsLegislativeSubjects20260730"),
            ("adapters/icpsr_zyte.py", "icpsrManagedIndexA"),
        ],
    },
    "managed_releases/federal_register_thesaurus_2025_managed_release.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["federal_register_thesaurus_2025.py"],
        "inputRefs": [("federal_register_thesaurus_2025.py", "federalRegister2025")],
    },
    "managed_releases/icpsr_managed_release.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["icpsr_subject.py"],
        "inputRefs": [],
    },
    "packages/crs_source_packages.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["crs_legislative_resources.py"],
        "inputRefs": [
            ("crs_legislative_resources.py", "crsLegislativeSubjects20260730"),
            ("crs_legislative_resources.py", "crsLegislativeGeographic20260730"),
            ("crs_legislative_resources.py", "crsLegislativeOrganizations20260730"),
            ("crs_legislative_resources.py", "crsPolicyAreas20260730"),
        ],
    },
    "packages/crs_source_concept_releases.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["packages/crs_source_packages.py"],
        "inputRefs": [
            ("crs_legislative_resources.py", "crsLegislativeSubjects20260730"),
            ("crs_legislative_resources.py", "crsLegislativeGeographic20260730"),
            ("crs_legislative_resources.py", "crsLegislativeOrganizations20260730"),
            ("crs_legislative_resources.py", "crsPolicyAreas20260730"),
        ],
    },
    "packages/federal_register_topics_package.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["federal_register_topics_api.py"],
        "inputRefs": [("federal_register_topics_api.py", "federalRegisterTopics")],
    },
    "packages/lda_controlled_list_resources.py": {
        "auditRole": "downstreamProjection",
        "coveredBy": ["lda_controlled_codes.py"],
        "inputRefs": [
            ("lda_controlled_codes.py", "ldaGeneralIssueCodes"),
            ("lda_controlled_codes.py", "ldaFilingTypes"),
        ],
    },
}


def _literal_urls(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    urls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for match in URL.findall(node.value):
            candidate = match.rstrip(".,);]}")
            try:
                parsed = urlsplit(candidate)
            except ValueError:
                continue
            if parsed.hostname and not parsed.hostname.endswith((".test", ".invalid")):
                urls.add(candidate)
    return tuple(sorted(urls))


def _classification(module: str) -> str:
    if "/" not in module:
        return "data-registry"
    return {
        "adapters": "registry-adapter",
        "infrastructure": "registry-infrastructure",
        "managed_releases": "registry-managed-release",
        "packages": "registry-source-package",
    }[module.split("/", 1)[0]]


def _pinned_fixture_test_inputs(module_filename: str, repository_root: Path) -> list[dict[str, Any]]:
    """Resolve explicitly approved publisher captures against module-owned pins."""

    specifications = PINNED_FIXTURE_INPUTS.get(module_filename, ())
    if not specifications:
        return []
    module = importlib.import_module("refspec.registry." + module_filename.removesuffix(".py").replace("/", "."))
    resolved: list[dict[str, Any]] = []
    for specification in specifications:
        pin_name = specification["constant"]
        pin = getattr(module, pin_name)
        source = getattr(pin, "source", None) or getattr(pin, "document", None) or pin
        expected_digest = getattr(pin, "expected_sha256", None) or getattr(source, "expected_sha256", None)
        expected_length = getattr(pin, "expected_byte_length", None)
        if expected_length is None:
            expected_length = getattr(source, "expected_byte_length", None)
        publisher_url = (
            getattr(pin, "source_url", None)
            or getattr(pin, "url", None)
            or getattr(source, "source_url", None)
            or getattr(source, "url", None)
        )
        if not isinstance(expected_digest, str) or not isinstance(expected_length, int):
            raise TypeError(f"{module_filename}.{pin_name} must declare expected_sha256 and expected_byte_length")
        if not isinstance(publisher_url, str) or not publisher_url.startswith(("http://", "https://")):
            raise ValueError(f"{module_filename}.{pin_name} has no publisher URL")

        relative_path = Path(specification["localPath"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"{module_filename}.{pin_name} must use a repository-relative path")
        local_path = (repository_root / relative_path).resolve(strict=True)
        try:
            local_path.relative_to(repository_root)
        except ValueError as error:
            raise ValueError(f"{module_filename}.{pin_name} escapes the repository") from error
        if not local_path.is_file() or local_path.is_symlink():
            raise ValueError(f"{module_filename}.{pin_name} is not a regular captured source file")

        payload = local_path.read_bytes()
        actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest or len(payload) != expected_length:
            raise ValueError(
                f"{module_filename}.{pin_name} does not match its immutable source pin: "
                f"expected {expected_digest}/{expected_length}, got {actual_digest}/{len(payload)}"
            )
        descriptor = {
            "name": specification["name"],
            "localPath": relative_path.as_posix(),
            "publisherUrl": publisher_url,
            "sha256": expected_digest,
            "byteLength": expected_length,
            "provenance": "pinnedPublisherCapture",
            "pinConstant": pin_name,
        }
        if "receiptRequired" in specification:
            descriptor["receiptRequired"] = specification["receiptRequired"]
        resolved.append(descriptor)
    return resolved


def _cfr_subject_index_test_inputs(repository_root: Path) -> list[dict[str, Any]]:
    """Describe the fifty pinned CFR List of Subjects pages as one collection.

    The Office of the Federal Register publishes the per-part index as fifty
    static pages, so the capture is one publisher artifact in fifty files
    rather than fifty unrelated sources. Each page's digest and byte length
    come from the reader's own pin tuple and are re-verified here against the
    tracked bytes, so a fixture edit fails generation instead of being
    described.
    """

    from refspec.registry import cfr_list_of_subjects as cfr

    fixture_root = Path("tests/fixtures/cfr_list_of_subjects/subject-index")
    members: list[dict[str, Any]] = []
    reserved: list[dict[str, Any]] = []
    for pin in cfr.CFR_SUBJECT_INDEX_2026_08_20:
        relative_path = fixture_root / f"subject-title-{pin.cfr_title:02d}.html"
        payload = (repository_root / relative_path).read_bytes()
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if digest != pin.expected_sha256 or len(payload) != pin.expected_byte_length:
            raise ValueError(
                f"{relative_path.as_posix()} does not match its immutable source pin: "
                f"expected {pin.expected_sha256}/{pin.expected_byte_length}, got {digest}/{len(payload)}"
            )
        descriptor: dict[str, Any] = {
            "name": f"subjectTitle{pin.cfr_title:02d}",
            "localPath": relative_path.as_posix(),
            "publisherUrl": pin.source_url,
            "sha256": pin.expected_sha256,
            "byteLength": pin.expected_byte_length,
            "acquisition": "directPublisherDownload",
            "provenance": "publisherPageResponse",
        }
        # CFR title 35 is reserved, so its page legitimately parses to zero
        # parts and can never produce the substantive counts the real-data
        # receipt gate asks of a publisher input. It stays pinned, tracked and
        # parsed -- `parse_cfr_subject_index` raises if it is ever non-empty --
        # but it is stated separately rather than sitting in the collection as
        # a member that looks unconsumed.
        if pin.cfr_title in cfr.CFR_RESERVED_TITLES:
            reserved.append(
                {
                    **descriptor,
                    "receiptRequired": False,
                    "scope": "reserved CFR title; a correct parse of this page yields zero parts",
                }
            )
            continue
        members.append(descriptor)
    if len(members) + len(reserved) != cfr.CFR_SUBJECT_INDEX_EXPECTED_PAGE_COUNT:
        raise ValueError("CFR subject index capture does not carry all fifty title pages")
    if len(reserved) != len(cfr.CFR_RESERVED_TITLES):
        raise ValueError("CFR subject index capture does not carry every reserved title page")
    # No captureDigest: the collection has no publisher-written manifest, and a
    # digest RefSpec computed over its own member list could never appear in an
    # execution receipt. The fifty member digests are what the real-data gate
    # checks, and each of them is a byte the parser actually reads.
    return [
        {
            "name": "cfrSubjectIndexCapture20260820",
            "kind": "sourceCollection",
            "localPath": fixture_root.as_posix(),
            "memberCount": len(members),
            "members": members,
            "provenance": "publisherCaptureCollection",
        },
        *reserved,
    ]


def _icpsr_managed_release_test_inputs(
    repository_root: Path,
) -> list[dict[str, Any]]:
    """Describe the multi-artifact publisher capture as one source collection."""

    # The capture collection lives under gitignored output/; the two files this
    # builder reads at generation time are pinned as byte-identical tracked
    # copies under tests/fixtures/ so `--check` holds from a clean clone.
    # localPath metadata keeps naming the capture location.
    capture_root = Path("output/refspec-vocabulary-portfolio/icpsr/2026-07-30")
    fixture_root = Path("tests/fixtures/icpsr_managed_release")
    manifest_path = repository_root / fixture_root / "capture-index-manifest-2026-07-30.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptors = [manifest["robots"], *manifest["pages"]]
    members: list[dict[str, Any]] = []
    for descriptor in descriptors:
        relative_source_path = Path(str(descriptor["path"]))
        if relative_source_path.is_absolute() or ".." in relative_source_path.parts:
            raise ValueError("ICPSR capture manifest contains an unsafe source path")
        letter = descriptor.get("letter")
        suffix = "Robots" if letter is None else ("Hash" if letter == "#" else str(letter).upper())
        members.append(
            {
                "name": f"index{suffix}",
                "localPath": (capture_root / "index" / relative_source_path).as_posix(),
                "publisherUrl": descriptor["url"],
                "sha256": descriptor["sha256"],
                "byteLength": descriptor["byteLength"],
                "acquisition": "zyteRawHttp",
                "provenance": "publisherPageResponse",
            }
        )
    xml_path = capture_root / "subject.xml"
    xml_payload = (repository_root / fixture_root / "subject-2026-07-30.xml").read_bytes()
    members.append(
        {
            "name": "subjectXml",
            "localPath": xml_path.as_posix(),
            "publisherUrl": (
                "https://raw.githubusercontent.com/ICPSR/metadata/"
                "6e2651e55fb42b119a167f34000ec728d1206865/"
                "projects/thesaurus/processed/subject.xml"
            ),
            "sha256": "sha256:" + hashlib.sha256(xml_payload).hexdigest(),
            "byteLength": len(xml_payload),
            "acquisition": "zyteRawHttp",
            "provenance": "publisherGitRepositoryAtCommit",
        }
    )
    return [
        {
            "name": "icpsrManagedReleaseCapture",
            "kind": "sourceCollection",
            "localPath": capture_root.as_posix(),
            "captureDigest": manifest["captureDigest"],
            "memberCount": len(members),
            "members": members,
            "provenance": "publisherCaptureCollection",
        }
    ]


def _icpsr_index_page_a_test_input(repository_root: Path) -> dict[str, Any]:
    collection = _icpsr_managed_release_test_inputs(repository_root)[0]
    page = next(member for member in collection["members"] if member["name"] == "indexA")
    return {**page, "name": "icpsrManagedIndexA"}


def _registry_module_paths(registry: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in registry.rglob("*.py") if path.name != "__init__.py"))


def build_manifest(repository_root: Path) -> dict[str, Any]:
    registry = repository_root / "src" / "refspec" / "registry"
    paths = _registry_module_paths(registry)
    module_ids = tuple(path.relative_to(registry).as_posix() for path in paths)
    nested_ids = {module for module in module_ids if "/" in module}
    configured_nested_ids = set(NESTED_MODULE_AUDIT)
    module_paths = dict(zip(module_ids, paths, strict=True))
    # A nested module that names no publisher URL cannot be reading publisher bytes,
    # so classify it as support rather than demanding hand-registration. Only
    # reader-shaped modules -- those that do name a publisher -- must be classified
    # deliberately, because their audit role changes what evidence the gate requires.
    unregistered_readers = sorted(
        module
        for module in nested_ids - configured_nested_ids
        if _literal_urls(module_paths[module]) or ADDITIONAL_URLS.get(module)
    )
    stale_entries = sorted(configured_nested_ids - nested_ids)
    if unregistered_readers or stale_entries:
        raise ValueError(
            "nested registry audit configuration drifted: "
            f"unclassified publisher readers={unregistered_readers}, "
            f"entries for modules that no longer exist={stale_entries}"
        )
    auto_support = (nested_ids - configured_nested_ids) - set(unregistered_readers)

    direct_inputs: dict[str, list[dict[str, Any]]] = {}
    for module, _path in zip(module_ids, paths, strict=True):
        inputs = [dict(configured) for configured in TEST_INPUTS.get(module, ())]
        inputs.extend(_pinned_fixture_test_inputs(module, repository_root))
        if module == "cfr_list_of_subjects.py":
            inputs.extend(_cfr_subject_index_test_inputs(repository_root))
        if module == "managed_releases/icpsr_managed_release.py":
            inputs.extend(_icpsr_managed_release_test_inputs(repository_root))
        if module == "adapters/icpsr_zyte.py":
            inputs.append(_icpsr_index_page_a_test_input(repository_root))
        direct_inputs[module] = inputs

    modules: list[dict[str, Any]] = []
    for module, path in zip(module_ids, paths, strict=True):
        declared_urls = set(_literal_urls(path))
        declared_urls.update(ADDITIONAL_URLS.get(module, ()))
        classification = _classification(module)
        default_role = "support" if module in auto_support or module in STRING_GRAMMAR_MODULES else "dataReader"
        config = NESTED_MODULE_AUDIT.get(
            module,
            {"auditRole": default_role, "coveredBy": [], "inputRefs": []},
        )
        test_inputs = [dict(item) for item in direct_inputs[module]]
        for source_module, input_name in config["inputRefs"]:
            matches = [descriptor for descriptor in direct_inputs[source_module] if descriptor["name"] == input_name]
            if len(matches) != 1:
                raise ValueError(f"{module} input reference {source_module}:{input_name} did not resolve exactly once")
            test_inputs.append(dict(matches[0]))
        for test_input in test_inputs:
            descriptors = (
                test_input.get("members", []) if test_input.get("kind") == "sourceCollection" else [test_input]
            )
            if any(
                not isinstance(descriptor.get("sha256"), str) or not isinstance(descriptor.get("byteLength"), int)
                for descriptor in descriptors
            ):
                raise ValueError(f"{module} audit inputs must carry immutable sha256 and byteLength pins")
            declared_urls.update(
                descriptor["publisherUrl"]
                for descriptor in descriptors
                if isinstance(descriptor.get("publisherUrl"), str)
            )
        role = config["auditRole"]
        blockers = list(SOURCE_BLOCKERS.get(module, ()))
        if role != "support" and not test_inputs and not blockers:
            blockers.append("No independently pinned publisher input is configured for this reader.")
        modules.append(
            {
                "module": module,
                "classification": classification,
                "auditRole": role,
                "coveredBy": list(config["coveredBy"]),
                "sourceStatus": (
                    "notApplicable" if role == "support" else ("blocked" if blockers else "publisherBytes")
                ),
                "blockers": blockers,
                "declaredUrls": sorted(declared_urls),
                "testInputs": test_inputs,
            }
        )
    return {
        "format": "refspec-registry-source-links/v1",
        "recordedAt": "2026-08-03",
        "moduleCount": len(modules),
        "modules": modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="verify the checked manifest (default: write it)")
    args = parser.parse_args()
    try:
        payload = build_manifest(args.repository_root.resolve())
        generated = canonical_json(payload) + "\n"
        if args.check:
            if not args.output.is_file() or args.output.read_text(encoding="utf-8") != generated:
                raise ValueError(
                    "checked registry source manifest differs from generation; "
                    "run tools/build_registry_source_manifest.py"
                )
            print(f"registry source manifest is current: {payload['moduleCount']} registry modules")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(generated, encoding="utf-8")
        return 0
    except (OSError, TypeError, ValueError) as error:
        print(f"registry source manifest error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

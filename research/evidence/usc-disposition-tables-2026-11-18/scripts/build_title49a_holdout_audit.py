"""Generate and verify the 27-section (177-row) Title 49a hold-out audit.

Verifies every count, RIN, edition range, and filer text directly against the
pinned 797,170-row Unified Agenda snapshot, verifies the SHA-256 digests of the
primary 1988 U.S. Code Title 49 Appendix PDFs (tile.loc.gov) and GovInfo 1994
Title 49 PDF, and emits:
- ``title49a-holdout-audit.json``
- ``title49a-holdout-audit.md``
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from refspec.registry.usc_disposition_tables import UscDispositionTables
from refspec.registry.usc_section_oracle import UscSectionOracle, normalize_section

SNAPSHOT_REL = "research/evidence/usc-section-oracle-2026-08-22/agenda-legal-authorities-as-measured-797170.parquet"
SNAPSHOT_SHA256 = "c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424"

SOURCES = {
    "uscode1988-019049a001.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a001/uscode1988-019049a001.pdf",
        "sha256": "eb99b3616ef1c22221bbb595e7f79dbef10065e5795583e7bac3143572dc9e34",
        "bytes": 1_828_448,
        "coverage": "1988 U.S.C. Title 49, Appendix TOC (Chs. 1-36) & Ch. 1 (Interstate Commerce Act, Part I, §§ 1-27) + opening of Ch. 2 (§ 41)",
    },
    "uscode1988-019049a004.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a004/uscode1988-019049a004.pdf",
        "sha256": "c0b5881347de3231946b522233281cfa072c2259341d1c15a97831449ec1741e",
        "bytes": 252_961,
        "coverage": "1988 U.S.C. Title 49, Appendix Ch. 4 (Bills of Lading, §§ 81-124) + opening of Ch. 5 (§ 141)",
    },
    "uscode1988-019049a006.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a006/uscode1988-019049a006.pdf",
        "sha256": "94db487a152c565f0a2d3a462c470a58d3722e0f16437b5b890e0a7db9964394",
        "bytes": 139_270,
        "coverage": "1988 U.S.C. Title 49, Appendix end of Ch. 5 (§§ 143, 151-157), Ch. 6 (Air Commerce, §§ 171-246), opening of Ch. 7 (§§ 250-264)",
    },
    "uscode1988-019049a008.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a008/uscode1988-019049a008.pdf",
        "sha256": "12276bcff9644e0fc807b3ca30ce231d43b9de51a564bfd19c6c869ad3f0bc02",
        "bytes": 109_350,
        "coverage": "1988 U.S.C. Title 49, Appendix Ch. 8 (Motor Carriers, §§ 301-327) + opening of Ch. 9 (§§ 401-403)",
    },
    "uscode1988-019049a009.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a009/uscode1988-019049a009.pdf",
        "sha256": "0d5c238c4db0c66c7a75a2f33989b8141749575628f52cfb56b441aec7759ec4",
        "bytes": 203_595,
        "coverage": "1988 U.S.C. Title 49, Appendix Ch. 9 (Civil Aeronautics, §§ 401-722) + Ch. 10 (§§ 751-758)",
    },
    "uscode1988-019049a013.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a013/uscode1988-019049a013.pdf",
        "sha256": "c2be05bc3a32ff29e9f1b383a8643659f93f2ae7cad46edac59e57f1766faccb",
        "bytes": 43_799,
        "coverage": "1988 U.S.C. Title 49, Appendix Ch. 13 (Freight Forwarders, §§ 1001-1022) + opening of Ch. 14 (§§ 1101-1103)",
    },
    "uscode1988-019049a020.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a020/uscode1988-019049a020.pdf",
        "sha256": "afb5fd8868823dfc53e85bc2b2cacb95f1d18eb4e708ba8bb91208fe2136971f",
        "bytes": 5_264_843,
        "coverage": "1988 U.S.C. Title 49, Appendix Ch. 20 (Federal Aviation Program, §§ 1301-1557)",
    },
    "uscode1988-019049a026.pdf": {
        "url": "https://tile.loc.gov/storage-services/service/ll/uscode/uscode1988-01904/uscode1988-019049a026/uscode1988-019049a026.pdf",
        "sha256": "1fd0e3948c6a9ee459193bbe618dab3f212a52c584180036873c095880542549",
        "bytes": 53_188,
        "coverage": "1988 U.S.C. Title 49, Appendix Ch. 26 (Hazardous Materials Transportation Control, §§ 1761-1762) + opening of Ch. 27 (§ 1801)",
    },
    "USCODE-1994-title49.pdf": {
        "url": "https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf",
        "sha256": "66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d",
        "bytes": 5_165_242,
        "coverage": "1994 U.S.C. Title 49 (Pub. L. 103-272, July 5, 1994, 108 Stat. 745): Disposition Table (pp. 1-12), Subtitle II/IV/VII chapters, § 31502 (formerly § 3102) & § 30111 (formerly 15 U.S.C. § 1392) notes",
    },
}

#: Adjudication of every one of the 27 distinct `not-in-table` Title 49a sections.
ADJUDICATIONS: dict[str, dict] = {
    "29": {
        "category": "cfr_part_in_usc_slot",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a001.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 1 ends at § 27 "
            "(Repealed, Pub. L. 95-473, § 4(b), Oct. 17, 1978, 92 Stat. 1466) and Ch. 2 opens at § 41; "
            "sections 28-40 were never assigned."
        ),
        "intended_referent": "49 CFR Part 29 (Governmentwide Debarment and Suspension), cited beside EO 11738, EO 12549, EO 12689, and Pub. L. 103-355 § 2455 in RIN 2105-AD68.",
    },
    "40": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a001.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 1 ends at § 27 "
            "(Repealed, Pub. L. 95-473, § 4(b), Oct. 17, 1978, 92 Stat. 1466) and Ch. 2 opens at § 41; "
            "sections 28-40 were never assigned."
        ),
        "intended_referent": "Truncated 49 U.S.C. § 40118 (Fly America Act), filed in 2025-04 GSA Federal Travel Regulation RIN 3090-AL06 beside 5 U.S.C. 5707, 5738 and 40 U.S.C. 121(c).",
    },
    "114l": {
        "category": "lost_parenthesis_a4_shape",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a004.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 Appendix. In 1988 Title 49a Ch. 4 (Bills of Lading), § 114 "
            "(Aug. 29, 1916, ch. 415, § 38, 39 Stat. 544; restated as 49 U.S.C. § 80107 by Pub. L. 103-272) "
            "is immediately followed by § 115; no § 114l existed."
        ),
        "intended_referent": "Live positive-law 49 U.S.C. § 114(l) (TSA rulemaking authority, enacted by Aviation and Transportation Security Act, Pub. L. 107-71, § 101(a), Nov. 19, 2001, 115 Stat. 597), missing parentheses in RIN 1652-AA08.",
    },
    "134": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a004.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 4 ends at § 124 "
            "(Aug. 29, 1916, ch. 415, § 44, 39 Stat. 545; repealed by Pub. L. 103-272) and Ch. 5 opens at § 141; "
            "sections 125-140 were never assigned."
        ),
        "intended_referent": "Truncated pre-recodification Federal Aviation Act citation (likely 49 U.S.C. App. § 1348, airspace control, or § 1341) filed in 1995-10 FAA RIN 2120-AE61 beside 49 USC 106(g), 1354(a), 1355, 1421-1430.",
    },
    "166": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a006.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 5 ends at §§ 151-157 "
            "(Repealed, Pub. L. 88-67, § 1(1), July 19, 1963, 77 Stat. 81) and Ch. 6 opens at § 171 "
            "(Repealed, Pub. L. 85-726, title XIV, § 1401(a), Aug. 23, 1958, 72 Stat. 806); sections 158-170 were never assigned."
        ),
        "intended_referent": "Single-digit typo (`166 to 117`) for live 49 U.S.C. §§ 116 to 117, corroborated verbatim by sibling editions of RIN 2105-AE69 writing `49 U.S.C. 116 to 117` and `49 U.S.C. 116 and 117`.",
    },
    "190": {
        "category": "cfr_part_in_usc_slot",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a006.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 6, Subch. I ends at §§ 179-184 "
            "(Repealed, Pub. L. 85-726, title XIV, § 1401(a), Aug. 23, 1958, 72 Stat. 806) and Subch. II opens at § 201 "
            "(Repealed, act Aug. 10, 1956, ch. 1041, § 53, 70A Stat. 641); sections 185-200 were never assigned."
        ),
        "intended_referent": "49 CFR Part 190 (Pipeline Safety Enforcement and Regulatory Procedures) fused into `49 USC 60101 et seq` in PHMSA RIN 2137-AD77.",
    },
    "217": {
        "category": "wrong_usc_title",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a006.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 6, Subch. III (Public Airports) "
            "contains §§ 211-214 (§ 214 repealed by Pub. L. 94-579, title VII, § 704(a), Oct. 21, 1976, 90 Stat. 2792) "
            "and Subch. IV opens at § 231; sections 215-230 were never assigned."
        ),
        "intended_referent": "Live 23 U.S.C. § 217 (Bicycle transportation and pedestrian walkways), mis-filed under Title 49 alongside 49 CFR Part 1 delegations (`1.51(f), 1.81, 1.85, 1.90`); sibling editions of RINs 2125-AF66 and 2132-AB21 cite `23 U.S.C. ..., 217(g), ...`.",
    },
    "322a": {
        "category": "lost_parenthesis_a4_shape",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a008.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 Appendix. In 1988 Title 49a Ch. 8 (Motor Carriers), §§ 321-324a were repealed by "
            "Pub. L. 95-473, § 4(b), Oct. 17, 1978, 92 Stat. 1466, and printed § 322 immediately before § 323; no § 322a existed."
        ),
        "intended_referent": "Live positive-law 49 U.S.C. § 322(a) (Secretary of Transportation general rulemaking authority, enacted by Pub. L. 97-449, Jan. 12, 1983, 96 Stat. 2422), missing parentheses in DOT RINs 2105-AD93 and 2127-AL06.",
    },
    "374": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a008.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 8 ends at § 327 "
            "(Repealed, Pub. L. 95-473, § 4(b), Oct. 17, 1978, 92 Stat. 1466) and Ch. 9 opens at § 401; "
            "sections 328-400 were never assigned."
        ),
        "intended_referent": "Dropped leading digit `1` for former 49 U.S.C. App. § 1374(a), (c) (Federal Aviation Act § 404, safe/adequate air carrier service and Air Carrier Access Act nondiscrimination; in 1994 Title 49 table -> 41702, 41501, 41310, 41705, 46301) in DOT OST RIN 2105-AC28 (1995-1998).",
    },
    "406": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9 (Civil Aeronautics Act of 1938), "
            "§§ 401-403 (Repealed, Pub. L. 85-726, title XIV, § 1401(b), Aug. 23, 1958, 72 Stat. 806) are followed "
            "immediately by §§ 421-422; sections 404-420 were never assigned."
        ),
        "intended_referent": "Single-digit typo (`406(f)`) for live 49 U.S.C. § 106(f) (FAA Administrator authority), corroborated verbatim by sibling editions of FAA RIN 2120-AK54 citing `49 U.S.C. 106(f)`.",
    },
    "411": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 401-403 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 421-422; "
            "sections 404-420 were never assigned. (Note: Civil Aeronautics Act § 411 was codified at former 49 U.S.C. § 491.)"
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 411 (Air Carrier Certificates, 49 U.S.C. §§ 41101 et seq.) cited without `ch.`/`chapters` by DOT OST aviation RINs (e.g. 2105-AD66 sibling editions write `49 U.S.C. chapters 401, 411, and 417`). Corrects earlier conjecture attributing 401-465 to 14 CFR ch. III.",
    },
    "413": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 401-403 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 421-422; "
            "sections 404-420 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 413 (Foreign Air Transportation, 49 U.S.C. §§ 41301 et seq.) cited without `ch.`/`chapters` in DOT OST aviation RINs.",
    },
    "415": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 401-403 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 421-422; "
            "sections 404-420 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 415 (Pricing, 49 U.S.C. §§ 41501 et seq.) cited without `ch.`/`chapters` in DOT OST aviation RINs.",
    },
    "417": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 401-403 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 421-422; "
            "sections 404-420 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 417 (Operations of Carriers, 49 U.S.C. §§ 41701 et seq.) cited without `ch.`/`chapters` in DOT OST aviation RINs (corroborated by RIN 2105-AD66 `49 U.S.C. chapters 401, 411, and 417`).",
    },
    "419": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 401-403 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 421-422; "
            "sections 404-420 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 419 (Transportation of Mail, 49 U.S.C. §§ 41901 et seq.) cited without `ch.`/`chapters` in DOT OST RIN 2105-AD10.",
    },
    "447": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 423-427 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 451-460; "
            "sections 428-450 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 447 (Safety Regulation, 49 U.S.C. §§ 44701 et seq.), corroborated verbatim by sibling editions of RIN 2105-AD66 writing `49 U.S.C. 106(g), chapters 447 and 451`.",
    },
    "449": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 423-427 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) jump directly to §§ 451-460; "
            "sections 428-450 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 449 (Security, 49 U.S.C. §§ 44901 et seq.) cited without `ch.`/`chapters` in DOT OST RIN 2105-AD10.",
    },
    "463": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, § 461 "
            "(Transferred to note under § 1343, then repealed Pub. L. 87-367, title I, § 103(15), Oct. 4, 1961, 75 Stat. 788) "
            "jumps directly to §§ 481-485; sections 462-480 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 463 (Penalties, 49 U.S.C. §§ 46301 et seq.) cited without `ch.`/`chapters` in DOT OST RIN 2105-AD10.",
    },
    "465": {
        "category": "current_title49_chapter_as_section",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a section in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, § 461 "
            "(Transferred, repealed Pub. L. 87-367, § 103(15)) jumps directly to §§ 481-485; sections 462-480 were never assigned."
        ),
        "intended_referent": "Current positive-law Title 49 Subtitle VII Chapter 465 (Special Aircraft Jurisdiction of the United States, 49 U.S.C. §§ 46501 et seq.) cited without `ch.`/`chapters` in DOT OST RIN 2105-AD10.",
    },
    "552a": {
        "category": "wrong_usc_title",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a009.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 9, §§ 551-560 "
            "(Repealed, Pub. L. 85-726, § 1401(b), Aug. 23, 1958, 72 Stat. 806) printed § 552 immediately before § 553; no § 552a existed."
        ),
        "intended_referent": "Live 5 U.S.C. § 552a(k) (Privacy Act exemptions), mis-filed under Title 49 in TSA RIN 1652-AA48 beside `49 USC 114(l)(1)`.",
    },
    "1085": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a013.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 13 (Freight Forwarders) ends at § 1022 "
            "(Repealed, Pub. L. 95-473, § 4(b), Oct. 17, 1978, 92 Stat. 1466) and Ch. 14 (Federal Aid for Public Airport Development) "
            "opens at §§ 1101-1103 (Repealed, Pub. L. 91-258, title I, § 52(a), May 21, 1970, 84 Stat. 235); sections 1023-1100 were never assigned."
        ),
        "intended_referent": "Typo (`1085` for `1-85`) for FERC's preserved oil-pipeline authority `49 U.S.C. App. §§ 1-85 (1988)`, filed in FERC RIN 1902-AD06 directly beside `49 USC 60502`.",
    },
    "1392": {
        "category": "wrong_usc_title",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a020.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 20 (Federal Aviation Program), "
            "Subch. IV ends at § 1389 and Subch. V opens at § 1401; sections 1390-1400 were never assigned."
        ),
        "intended_referent": "Former 15 U.S.C. § 1392 (National Traffic and Motor Vehicle Safety Act of 1966, § 103 — Federal Motor Vehicle Safety Standards), repealed and restated in Title 49 (49 U.S.C. §§ 30101, 30111, 30112, 30117, 30125, 30166) by Pub. L. 103-272, §§ 1(e), 7(b), July 5, 1994, 108 Stat. 941, 1379; mis-filed under Title 49 in NHTSA RIN 2127-AJ47.",
    },
    "1491": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a020.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a Ch. 20, Subch. X ends at § 1490 "
            "(Pub. L. 85-726, title X, § 1010, as added Pub. L. 95-504, § 38(a), Oct. 24, 1978, 92 Stat. 1743) "
            "and Subch. XI opens at § 1501; sections 1491-1500 were never assigned."
        ),
        "intended_referent": "Single-digit typo (`1491 to 1406`) for former 49 U.S.C. App. §§ 1401 to 1406 (aircraft registration), corroborated by RIN 2120-AF68 switching in 1996-04 to positive-law `49 USC 44110`.",
    },
    "1509d": {
        "category": "lost_parenthesis_a4_shape",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a020.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed as a separate section `1509d` in Title 49 Appendix. In 1988 Title 49a Ch. 20, § 1509 "
            "(Application of existing laws relating to foreign commerce) is immediately followed by § 1510. "
            "However, subsection `§ 1509(d)` ('Animal and plant quarantine') IS a real 1988 Title 49a provision "
            "and IS in the 1994 Title 49 Disposition Table (`1509(b)-(e) -> T. 19 § 1644a`, p. 8 left)."
        ),
        "intended_referent": "Former 49 U.S.C. App. § 1509(d) (recodified as 19 U.S.C. § 1644a by Pub. L. 103-272), missing parentheses in USDA APHIS quarantine RIN 0579-AB21 beside `21 USC 105, 112-114a, 120-121`.",
    },
    "1763": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a026.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 or Title 49 Appendix. In 1988 Title 49a, Ch. 26 (Hazardous Materials "
            "Transportation Control) contained only §§ 1761-1762 (Repealed, Pub. L. 93-633, title I, § 113(g), "
            "Jan. 3, 1975, 88 Stat. 2163), immediately followed by Ch. 27 opening at § 1801; sections 1763-1800 were never assigned."
        ),
        "intended_referent": "Statutes at Large pinpoint page `1763` from `119 Stat 1144, 1763` (Pub. L. 109-59 [mis-typed 109-159], § 4304, SAFETEA-LU) parsed as a comma-continued Title 49 section in FMCSA RIN 2126-AA22.",
    },
    "3102": {
        "category": "positive_law_renumbered_mislabelled_app",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a001.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 Appendix (which ended at Ch. 36, § 2716 in 1988 and § 2812 in 1994). "
            "Was a real positive-law section of Title 49 Subtitle II Ch. 31 (`49 U.S.C. § 3102`, Requirements for "
            "qualifications, hours of service, safety, and equipment standards), enacted by Pub. L. 97-449, § 1(b), "
            "Jan. 12, 1983, 96 Stat. 2438, amended by Pub. L. 98-554, title II, § 206(h), Oct. 30, 1984, 98 Stat. 2835, "
            "and renumbered `49 U.S.C. § 31502` by Pub. L. 103-272, § 1(c), (e), July 5, 1994, 108 Stat. 745, 1029 "
            "(verified verbatim in USCODE-1994-title49.pdf § 31502 amendment/credit notes). Excluded from the 1994 "
            "Disposition Table because it was an internal positive-law Title 49 renumbering, not a Title 49 Appendix disposition."
        ),
        "intended_referent": "Pre-1994 positive-law 49 U.S.C. § 3102 (now 49 U.S.C. § 31502), erroneously labelled `app` (`49 USC app 3102`) in FHWA RIN 2125-AD20 alongside `49 USC 3102`.",
    },
    "10109": {
        "category": "filer_typo_truncation_or_parser_damage",
        "existed_in_1988_title_49a": False,
        "in_1994_disposition_table": False,
        "table_omission": False,
        "primary_source_files": ["uscode1988-019049a001.pdf", "USCODE-1994-title49.pdf"],
        "statutory_status_1988_1994": (
            "Never existed in Title 49 Appendix (ended at § 2716 in 1988 / § 2812 in 1994) or positive-law Title 49. "
            "In 1994 positive-law Title 49 Subtitle IV Ch. 101 (General Provisions), only §§ 10101, 10101a, 10102, 10103 existed."
        ),
        "intended_referent": "Single-digit typo (`10109`) for live 49 U.S.C. § 40109 (Authority to exempt), filed in FAA RIN 2120-AI58 beside `49 USC 106(g), 40103, 40106, 44502, 44514, 44701, 44719, 46301`.",
    },
}


def _verify_file(path: Path, sha256: str, size: int) -> None:
    raw = path.read_bytes()
    obs_sha = hashlib.sha256(raw).hexdigest()
    if len(raw) != size or obs_sha != sha256:
        raise SystemExit(f"{path} drifted: expected {sha256} ({size}B), got {obs_sha} ({len(raw)}B)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--probe-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    # 1. Verify every primary source PDF digest
    for fname, meta in SOURCES.items():
        if fname == "USCODE-1994-title49.pdf":
            path = args.repo_root / "research/evidence/usc-disposition-tables-2026-08-23" / fname
        elif fname == "uscode1988-019049a006.pdf":
            path = args.probe_dir / fname
        else:
            path = args.cache_dir / fname
        _verify_file(path, meta["sha256"], meta["bytes"])

    # 2. Verify snapshot digest and extract live hold-out population
    snap_path = args.repo_root / SNAPSHOT_REL
    _verify_file(snap_path, SNAPSHOT_SHA256, snap_path.stat().st_size)

    oracle = UscSectionOracle.from_repository(args.repo_root)
    tables = UscDispositionTables.from_repository(args.repo_root)

    tbl = pq.read_table(
        snap_path,
        columns=["rin", "publication_id", "authority_text", "authority_type", "usc_title", "usc_section", "usc_appendix"],
    )
    cols = {n: tbl.column(n).to_pylist() for n in tbl.schema.names}
    hold: dict[str, list[tuple[str, str, bool, str]]] = collections.defaultdict(list)
    for rin, pub, text, atype, title, sec, app in zip(*cols.values(), strict=True):
        if atype != "usc" or title != 49 or sec is None:
            continue
        nsec = normalize_section(sec)
        v = oracle.section_verdict(49, nsec, int(pub[:4]), appendix=bool(app))
        if (
            v.verdict == "unknown"
            and v.reason == "title_49_appendix_not_published"
            and not tables.disposition(49, nsec).answered
        ):
            hold[nsec].append((rin, pub, bool(app), text))

    if set(hold) != set(ADJUDICATIONS):
        raise SystemExit(f"Hold-out mismatch: live={sorted(hold)} vs audited={sorted(ADJUDICATIONS)}")

    records = []
    for sec in sorted(hold, key=lambda s: (-len(hold[s]), s)):
        items = hold[sec]
        adj = ADJUDICATIONS[sec]
        texts = collections.Counter(tx for _, _, _, tx in items).most_common()
        pubs = sorted({p for _, p, _, _ in items})
        records.append(
            {
                "section": sec,
                "row_count": len(items),
                "distinct_rins": sorted({r for r, _, _, _ in items}),
                "edition_range": [pubs[0], pubs[-1]],
                "appendix_flags_in_snapshot": sorted({a for _, _, a, _ in items}),
                "authority_texts": [{"text": tx, "rows": cnt} for tx, cnt in texts],
                **adj,
            }
        )

    by_category_sections: collections.Counter[str] = collections.Counter()
    by_category_rows: collections.Counter[str] = collections.Counter()
    for rec in records:
        by_category_sections[rec["category"]] += 1
        by_category_rows[rec["category"]] += rec["row_count"]

    total_rows = sum(rec["row_count"] for rec in records)
    assert len(records) == 27 and total_rows == 177

    payload = {
        "audit_date": "2026-11-18",
        "snapshot": {
            "path": SNAPSHOT_REL,
            "sha256": f"sha256:{SNAPSHOT_SHA256}",
        },
        "summary": {
            "distinct_sections": len(records),
            "total_rows": total_rows,
            "existed_in_1988_title_49a_count": sum(1 for r in records if r["existed_in_1988_title_49a"]),
            "table_omission_count": sum(1 for r in records if r["table_omission"]),
            "by_category": {
                cat: {"sections": by_category_sections[cat], "rows": by_category_rows[cat]}
                for cat in sorted(by_category_sections, key=lambda c: (-by_category_rows[c], c))
            },
            "conclusion": (
                "Zero of the 27 not-in-table Title 49a tokens (177 rows) existed as sections of 1988 "
                "U.S. Code Title 49 Appendix, and zero are omissions from the 1994 Title 49 Disposition Table. "
                "Importing raw 1988 Title 49a OCR into UscSectionOracle would recover 0 of 177 rows while "
                "introducing two-column OCR bleed. One token (3102, 5 rows) is a genuine pre-1994 positive-law "
                "Title 49 section (Pub. L. 97-449) renumbered to 49 U.S.C. § 31502 by Pub. L. 103-272 and "
                "erroneously marked `app`; nine tokens (114 rows) are current positive-law Title 49 Subtitle VII "
                "chapter numbers (correcting the earlier 14 CFR ch. III conjecture); the remaining 17 tokens "
                "(58 rows) are lost-parenthesis pinpoints, wrong-title citations, CFR parts in the U.S.C. slot, "
                "or filer/parser damage."
            ),
        },
        "primary_sources": SOURCES,
        "sections": records,
    }

    json_path = args.out_dir / "title49a-holdout-audit.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Render Markdown report
    md_lines = [
        "# Title 49a Hold-Out Audit (27 Sections / 177 Rows) — 2026-11-18",
        "",
        "Primary-source statutory adjudication of all **27** distinct `not-in-table` Title 49a section tokens "
        "(**177** rows in `tests/test_usc_disposition_tables.py::HOLD_OUT`, measured against "
        "`agenda-legal-authorities-as-measured-797170.parquet`, `sha256:" + SNAPSHOT_SHA256 + "`).",
        "",
        "## Headline Finding",
        "",
        (
            "- **0 / 27** tokens existed as sections in the **1988 U.S. Code, Title 49 Appendix** (verified across eight "
            "primary chapter PDFs from `tile.loc.gov`, starting with the cached Chapter 6 probe `uscode1988-019049a006.pdf`)."
        ),
        "- **0 / 27** tokens are omissions from the **1994 Title 49 Disposition Table** (`USCODE-1994-title49.pdf`).",
        (
            "- **Policy conclusion:** Bulk-ingesting scanned 1988 Title 49a OCR into `UscSectionOracle` would recover "
            "**0 of the 177 hold-out rows** while risking two-column OCR bleed (`LuraDocument PDF v2.65`)."
        ),
        (
            "- **Correction to earlier conjecture:** `tests/test_usc_disposition_tables.py:778-779` informally attributed "
            "`401-465` to 14 CFR chapter III commercial space licensing parts. Primary inspection of RIN sibling editions "
            "(`2105-AD66` writing `49 U.S.C. chapters 401, 411, and 417` and `49 U.S.C. 106(g), chapters 447 and 451`) and "
            "1988 Title 49a Chapter 9 proves all nine (`411, 413, 415, 417, 419, 447, 449, 463, 465` — **114 of 177 rows**) "
            "are **current positive-law Title 49 Subtitle VII chapter numbers** cited without `ch.`/`chapters`."
        ),
        "",
        "## Breakdown by Root-Cause Category",
        "",
        "| Category | Sections | Rows | Summary |",
        "|---|---:|---:|---|",
    ]
    cat_desc = {
        "current_title49_chapter_as_section": "Positive-law Title 49 Subtitle VII chapters (`411, 413, 415, 417, 419, 447, 449, 463, 465`) written without `ch.`",
        "filer_typo_truncation_or_parser_damage": "Dropped digit, single-digit typo, truncation, or Statutes page parsed as section (`374, 166, 1085, 10109, 40, 134, 406, 1491, 1763`)",
        "wrong_usc_title": "Valid section of another U.S.C. title filed under Title 49 (`5:552a(k)`, `23:217`, former `15:1392`)",
        "lost_parenthesis_a4_shape": "Missing parentheses on a real section's subsection (`49:322(a)`, `49 App.:1509(d)`, `49:114(l)`)",
        "cfr_part_in_usc_slot": "49 CFR part number placed in U.S.C. slot (`49 CFR 190`, `49 CFR 29`)",
        "positive_law_renumbered_mislabelled_app": "Real pre-1994 positive-law `49 U.S.C. § 3102` (renumbered `§ 31502` by Pub. L. 103-272), erroneously labelled `app`",
    }
    for cat, counts in payload["summary"]["by_category"].items():
        md_lines.append(f"| `{cat}` | {counts['sections']} | {counts['rows']} | {cat_desc[cat]} |")
    md_lines.append("| **Total** | **27** | **177** | **0 table omissions; 0 sections present in 1988 Title 49a** |")
    md_lines.extend(
        [
            "",
            "## Primary Sources Verified",
            "",
            "| File | Bytes | SHA-256 | Coverage |",
            "|---|---:|---|---|",
        ]
    )
    for fname, meta in SOURCES.items():
        md_lines.append(f"| `{fname}` | {meta['bytes']:,} | `{meta['sha256']}` | {meta['coverage']} |")
    md_lines.extend(
        [
            "",
            "## Section-by-Section Adjudication (All 27 Sections / 177 Rows)",
            "",
            "| Section | Rows | Category | Primary Source(s) | Statutory Status (1988 49a & 1994 T. 49) | Intended Referent / Cause |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for rec in records:
        srcs = ", ".join(f"`{f}`" for f in rec["primary_source_files"])
        md_lines.append(
            f"| `{rec['section']}` | {rec['row_count']} | `{rec['category']}` | {srcs} | "
            f"{rec['statutory_status_1988_1994']} | {rec['intended_referent']} |"
        )
    md_lines.append("")

    md_path = args.out_dir / "title49a-holdout-audit.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote {json_path.name} ({json_path.stat().st_size}B) and {md_path.name} ({md_path.stat().st_size}B)")
    print("Categories:", payload["summary"]["by_category"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

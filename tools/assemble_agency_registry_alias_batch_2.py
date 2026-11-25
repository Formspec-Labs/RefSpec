"""Assemble agency registry alias batch 2 and its owner adjudication sheet (candidates, never assertions).

Batch 2 covers the remaining verifiable federal sub-units, institutes, regional
Federal Reserve Banks, NOAA line offices, military commands/reserves, OIGs, and
statutory FR-name variants identified by congressional-tech witness demand
(research/evidence/agency-alias-demand-2026-11-25/federal-misses.json), strictly
following REF-075 D4/D5 (verifiable statutory, Federal Register, congressional
hearing, or official agency-page citations retained locally and verified
verbatim in retained bytes; zero misspellings, zero guessed parents).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from refspec.atlas import agency_projection
from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from refspec.atlas.agency_projection import name_key
from refspec.atlas.v3_source_data import RegistryRelease, canonical_digest

try:
    from tools import analyze_agency_roster_identifiers as census
    from tools import assemble_agency_registry_alias_batch as batch_aliases
    from tools import assemble_agency_registry_batch_1 as batch1
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_agency_roster_identifiers as census
    import assemble_agency_registry_alias_batch as batch_aliases
    import assemble_agency_registry_batch_1 as batch1

SCHEMA_VERSION = batch_aliases.SCHEMA_VERSION
REPORT_JSON = Path("plans/agency-registry-alias-batch-2-candidates.json")
ADJUDICATION_MARKDOWN = Path("plans/agency-registry-alias-batch-2-adjudication.md")
DECISIONS_JSON = Path("plans/agency-registry-alias-batch-2-decisions.json")
DEMAND_JSON = Path("research/evidence/agency-alias-demand-2026-11-25/federal-misses.json")
RECORDS_DIR = Path("research/evidence/agency-alias-records-2026-11-25")
CANDIDATES_DIGEST_COVERS = entity_alignments.ALIAS_CANDIDATES_DIGEST_COVERS

_FH = batch_aliases._FH
_OPM = batch_aliases._OPM
_PART_WHY = batch_aliases._PART_WHY
_SAME_WHY = "A statutory or Federal Register official name variant of the FR record's organization."
_NO_FR_OPM_WHY = "Names the OPM record; no FR id."
_NO_FR_FH_WHY = "Names the Federal Hierarchy record; an FR-keyed consumer gets no FR id, which is the truth."

Record = batch_aliases.Record
Judgment = batch_aliases.Judgment


def _usc(title: int, section: str, passage: str) -> Record:
    return Record("statute", f"{title} U.S.C. {section}", f"raw/usc-{title}-{section}.htm", passage)


def _fr_doc(citation: str, doc_num: str, passage: str) -> Record:
    return Record("frDocument", citation, f"raw/fr-{doc_num}.txt", passage)


_NIH_HEADER = _usc(42, "281", "The following agencies of the National Institutes of Health are national research institutes or national centers:")
_NIH_INSTITUTES: tuple[tuple[str, str, str], ...] = (
    ("national cancer institute", "NCI", "(1) The National Cancer Institute."),
    ("national heart lung and blood institute", "NHLBI", "(2) The National Heart, Lung, and Blood Institute."),
    ("national institute of neurological disorders and stroke", "NINDS", "(10) The National Institute of Neurological Disorders and Stroke."),
    ("national institute on drug abuse", "NIDA", "(13) The National Institute on Drug Abuse."),
    ("national institute of mental health", "NIMH", "(14) The National Institute of Mental Health."),
    ("national institute of general medical sciences", "NIGMS", "(15) The National Institute of General Medical Sciences."),
)

_FRB_STATUTE = _usc(12, "222", "Sec. 222 - Federal reserve districts; membership of national banks")
_FRB_BOARD = _usc(12, "241", "BOARD OF GOVERNORS OF THE FEDERAL RESERVE SYSTEM")
_FRB_CITIES_06 = (
    ("boston", "Federal Reserve Bank of Boston, 600 Atlantic Avenue, Boston, MA 02210."),
    ("philadelphia", "Federal Reserve Bank of Philadelphia, 10 Independence Mall, Philadelphia, PA 19106."),
    ("atlanta", "Federal Reserve Bank of Atlanta, 1000 Peachtree Street, NE., Atlanta, GA 30309."),
    ("chicago", "Federal Reserve Bank of Chicago, 230 South LaSalle Street, Chicago, IL 60604."),
    ("st louis", "Federal Reserve Bank of St. Louis, P.O. Box 442, St. Louis, MO 63166-0442."),
    ("minneapolis", "Federal Reserve Bank of Minneapolis, 90 Hennepin Avenue, Minneapolis, MN 55401."),
    ("kansas city", "Federal Reserve Bank of Kansas City, 925 Grand Boulevard, Kansas City, MO 64198."),
    ("dallas", "Federal Reserve Bank of Dallas, 2200 North Pearl Street, Dallas, TX 75201."),
    ("san francisco", "Federal Reserve Bank of San Francisco, 101 Market Street, San Francisco, CA 94105."),
)
_FRB_CITIES_OTHER: tuple[tuple[str, str, str, str], ...] = (
    ("new york", "90 FR 50869 (2025-11-12), FR Doc 2025-19855, Federal Reserve System", "2025-19855", "Federal Reserve Bank of New York (Keith Goodwin, Head of Bank Applications)"),
    ("cleveland", "90 FR 50869 (2025-11-12), FR Doc 2025-19855, Federal Reserve System", "2025-19855", "Federal Reserve Bank of Cleveland (Jenni M. Frazer, Vice President)"),
    ("richmond", "72 FR 132 (2007-01-03), FR Doc E6-22472, Federal Reserve System", "E6-22472", "Federal Reserve Bank of Richmond (A. Linwood Gill, III, Vice President)"),
)

_DOD_COMMANDS = _usc(10, "111", "(9) The unified and specified combatant commands.")
_DOD_FOIA_COMPONENTS = _fr_doc(
    "82 FR 1192 (2017-01-05), FR Doc 2016-31686, 32 CFR 286.2",
    "2016-31686",
    "the Combatant Commands, the Office of the Inspector General of the Department of Defense, the Defense Agencies, the DoD Field Activities, and all other organizational entities within the DoD",
)
_DOD_FOIA_CMDS = _fr_doc(
    "82 FR 1192 (2017-01-05), FR Doc 2016-31686, 32 CFR part 286",
    "2016-31686",
    "United States Africa Command, United States Central Command, United States European Command, United States Northern Command, United States Pacific Command, United States Special Operations Command, United States Strategic Command, and United States Transportation Command.",
)
_USSTRATCOM_EO = _fr_doc(
    "82 FR 5325 (2017-01-17), FR Doc 2017-01169, Executive Order 13760",
    "2017-01169",
    "United States Strategic Command (USSTRATCOM) and all components, centers, or sub-unified commands currently assigned to USSTRATCOM",
)


def _fr_bank_rows() -> tuple[Judgment, ...]:
    rows = []
    for city, passage in _FRB_CITIES_06:
        rows.append(
            Judgment(
                f"federal reserve bank of {city}",
                None,
                188,
                "partOf",
                "unitWithinFrAgency",
                "Regional Federal Reserve Bank established within the Federal Reserve System (FR 188) under 12 U.S.C. 222.",
                "yes",
                _PART_WHY,
                (_FRB_STATUTE, _FRB_BOARD, _fr_doc("71 FR 11297 (2006-03-07), FR Doc 06-2124, Federal Reserve System, 12 CFR 227.2", "06-2124", passage)),
            )
        )
    for city, citation, doc_num, passage in _FRB_CITIES_OTHER:
        rows.append(
            Judgment(
                f"federal reserve bank of {city}",
                None,
                188,
                "partOf",
                "unitWithinFrAgency",
                "Regional Federal Reserve Bank established within the Federal Reserve System (FR 188) under 12 U.S.C. 222.",
                "yes",
                _PART_WHY,
                (_FRB_STATUTE, _FRB_BOARD, _fr_doc(citation, doc_num, passage)),
            )
        )
    return tuple(rows)


JUDGMENT: tuple[Judgment, ...] = (
    # --- Exact FR variants / statutory names ---
    Judgment(
        "government printing office",
        None,
        217,
        "same",
        "statutoryRename",
        "The statutory name of FR 217 ('Government Publishing Office') before Pub. L. 113-235 sec. 1301 (2014-12-16).",
        "yes",
        _SAME_WHY,
        (Record("publicLaw", "Pub. L. 113-235, Div. H, sec. 1301(a), 128 Stat. 2537 (2014-12-16)", "raw/plaw-113-235.htm",
                "The Government Printing Office is hereby redesignated the Government Publishing Office."),),
    ),
    Judgment(
        "chemical safety board",
        None,
        47,
        "same",
        "publisherNameVariant",
        "Short name used by the U.S. Chemical Safety and Hazard Investigation Board (FR 47) in its own notices.",
        "yes",
        _SAME_WHY,
        (_fr_doc("85 FR 4944 (2020-01-28), FR Doc 2020-01490, Chemical Safety and Hazard Investigation Board", "2020-01490",
                 "PLACE: U.S. Chemical Safety Board, 1750 Pennsylvania Ave. NW, Suite 910, Washington, DC 20006. STATUS: Open to the public. MATTERS TO BE CONSIDERED: The Chemical Safety and Hazard Investigation Board"),),
    ),
    Judgment(
        "commission on civil rights",
        None,
        52,
        "same",
        "publisherNameVariant",
        "Statutory and eCFR publisher name ('Commission on Civil Rights' / 'United States Commission on Civil Rights') of FR 52 ('Civil Rights Commission').",
        "yes",
        _SAME_WHY,
        (_usc(42, "1975", "There is established the United States Commission on Civil Rights"),),
    ),
    Judgment(
        "trade representative",
        None,
        491,
        "same",
        "publisherNameVariant",
        "FR 491 is 'Trade Representative, Office of United States'; 'United States Trade Representative' / 'Trade Representative' names the same office and statutory title.",
        "yes",
        _SAME_WHY,
        (_usc(19, "2171", "There is established within the Executive Office of the President the Office of the United States Trade Representative"),),
    ),
    Judgment(
        "americorps",
        None,
        91,
        "same",
        "publisherNameVariant",
        "Operating name adopted in 45 CFR Part 2500 by the Corporation for National and Community Service (FR 91).",
        "yes",
        _SAME_WHY,
        (_fr_doc("89 FR 6432 (2024-02-01), FR Doc 2024-01555, Corporation for National and Community Service, 45 CFR Part 2500", "2024-01555",
                 "AmeriCorps Statement of Organization AGENCY: Corporation for National and Community Service."),),
    ),
    Judgment(
        "white house office of science and technology policy",
        None,
        464,
        "same",
        "publisherNameVariant",
        "Official White House-prefixed title for the Office of Science and Technology Policy (FR 464, 42 U.S.C. 6611).",
        "yes",
        _SAME_WHY,
        (_usc(42, "6611", "Office of Science and Technology Policy"),
         _fr_doc("89 FR 48449 (2024-06-06), FR Doc 2024-12399, Office of Science and Technology Policy", "2024-12399",
                 "The White House Office of Science and Technology Policy (OSTP)")),
    ),
    Judgment(
        "morris k and stewart l udall foundation",
        None,
        296,
        "same",
        "publisherNameVariant",
        "Variant dropping the repeated surname in 'Morris K. Udall and Stewart L. Udall Foundation' (FR 296, 20 U.S.C. 5603).",
        "yes",
        _SAME_WHY,
        (_usc(20, "5603", "Establishment of Morris K. Udall and Stewart L. Udall Foundation"),
         _fr_doc("89 FR 84400 (2024-10-22), FR Doc 2024-24461, Morris K. Udall and Stewart L. Udall Foundation", "2024-24461",
                 "AGENCY: Morris K. Udall and Stewart L. Udall Foundation.")),
    ),
    Judgment(
        "director of national intelligence",
        None,
        354,
        "partOf",
        "unitWithinFrAgency",
        "Head of the Office of the Director of National Intelligence (FR 354, 50 U.S.C. 3023); appears as an abbreviated org string for ODNI.",
        "yes",
        _PART_WHY,
        (_usc(50, "3023", "There is a Director of National Intelligence"),
         _usc(50, "3033", "There is within the Office of the Director of National Intelligence")),
    ),

    # --- NIH Institutes (42 U.S.C. 281, FR 353) ---
    *(
        Judgment(
            nk,
            None,
            353,
            "partOf",
            "unitWithinFrAgency",
            f"{acr} is a statutory national research institute of the National Institutes of Health (FR 353).",
            "yes",
            _PART_WHY,
            (_NIH_HEADER, _usc(42, "281", quote)),
        )
        for nk, acr, quote in _NIH_INSTITUTES
    ),

    # --- Federal Reserve Board & 12 Regional Federal Reserve Banks (FR 188) ---
    Judgment(
        "federal reserve board",
        None,
        188,
        "partOf",
        "unitWithinFrAgency",
        "Statutory short title in 12 U.S.C. 241 for the Board of Governors of the Federal Reserve System (part of FR 188).",
        "yes",
        _PART_WHY,
        (_usc(12, "241", "Federal Reserve Board"), _FRB_BOARD),
    ),
    Judgment(
        "federal reserve board of governors",
        None,
        188,
        "partOf",
        "unitWithinFrAgency",
        "Reversed short-form name of the Board of Governors of the Federal Reserve System (FR 188, 12 U.S.C. 241).",
        "yes",
        _PART_WHY,
        (_FRB_BOARD,),
    ),
    *_fr_bank_rows(),

    # --- NOAA Line Offices (FR 361) ---
    Judgment(
        "national marine fisheries service",
        None,
        361,
        "partOf",
        "unitWithinFrAgency",
        "Line office of the National Oceanic and Atmospheric Administration (FR 361).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 72381 (2024-09-05), FR Doc 2024-19930, Department of Commerce / NOAA", "2024-19930",
                 "National Marine Fisheries Service, NOAA"),),
    ),
    Judgment(
        "noaa fisheries",
        None,
        361,
        "partOf",
        "unitWithinFrAgency",
        "Official operating name of NOAA's National Marine Fisheries Service (FR 361).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 42571 (2025-09-03), FR Doc 2025-16825, NOAA", "2025-16825",
                 "NOAA Fisheries Virtual Peer Review Workshop for the Fishing Effort Survey Calibration Model AGENCY: National Marine Fisheries Service (NMFS), National Oceanic and Atmospheric Administration (NOAA)"),),
    ),
    Judgment(
        "noaa pacific islands fisheries science center",
        None,
        361,
        "partOf",
        "unitWithinFrAgency",
        "Regional science center of NOAA's National Marine Fisheries Service (FR 361).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 16113 (2025-04-17), FR Doc 2025-06579, NMFS/NOAA", "2025-06579",
                 "permit has been issued to NMFS' Pacific Islands Fisheries Science Center"),
         _fr_doc("90 FR 42571 (2025-09-03), FR Doc 2025-16825, NOAA", "2025-16825",
                 "National Marine Fisheries Service (NMFS), National Oceanic and Atmospheric Administration (NOAA)")),
    ),
    Judgment(
        "noaa s national environmental satellite data and information service",
        None,
        361,
        "partOf",
        "unitWithinFrAgency",
        "NESDIS, a line office of NOAA (FR 361).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 55300 (2025-12-02), FR Doc 2025-21734, Department of Commerce", "2025-21734",
                 "National Environmental Satellite Data and Information Service (NOAA)"),),
    ),
    Judgment(
        "national ocean service",
        None,
        361,
        "partOf",
        "unitWithinFrAgency",
        "NOS, a line office of NOAA (FR 361).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 72381 (2024-09-05), FR Doc 2024-19930, Department of Commerce / NOAA", "2024-19930",
                 "National Ocean Service, NOAA"),),
    ),
    Judgment(
        "national weather service",
        None,
        361,
        "partOf",
        "unitWithinFrAgency",
        "NWS, a line office of NOAA (FR 361) and statutory Weather Service (15 U.S.C. 313).",
        "yes",
        _PART_WHY,
        (_usc(15, "313", "CHAPTER 9 - NATIONAL WEATHER SERVICE"),
         _fr_doc("89 FR 72381 (2024-09-05), FR Doc 2024-19930, Department of Commerce / NOAA", "2024-19930",
                 "National Weather Service, NOAA")),
    ),

    # --- National Guard & Armed Forces Reserve Components ---
    Judgment(
        "air national guard",
        _OPM + "AF34",
        13,
        "partOf",
        "militaryServiceOfDepartment",
        "Reserve component of the Air Force within the Department of the Air Force (FR 13, 10 U.S.C. 10111); OPM holds it as AF34.",
        "yes",
        _PART_WHY,
        (_usc(10, "10111", "The Air National Guard of the United States is the reserve component of the Air Force"),),
    ),
    Judgment(
        "army national guard",
        None,
        32,
        "partOf",
        "militaryServiceOfDepartment",
        "Reserve component of the Army within the Department of the Army (FR 32, 10 U.S.C. 10105).",
        "yes",
        _PART_WHY,
        (_usc(10, "10105", "The Army National Guard of the United States is the reserve component of the Army"),),
    ),
    Judgment(
        "air force reserve",
        None,
        13,
        "partOf",
        "militaryServiceOfDepartment",
        "Reserve component of the Air Force within the Department of the Air Force (FR 13, 10 U.S.C. 10110).",
        "yes",
        _PART_WHY,
        (_usc(10, "10110", "The Air Force Reserve is a reserve component of the Air Force"),),
    ),
    Judgment(
        "army reserve",
        None,
        32,
        "partOf",
        "militaryServiceOfDepartment",
        "Reserve component of the Army within the Department of the Army (FR 32, 10 U.S.C. 10104).",
        "yes",
        _PART_WHY,
        (_usc(10, "10104", "The Army Reserve includes all Reserves of the Army"),),
    ),
    Judgment(
        "army reserve command",
        _OPM + "ARHR",
        32,
        "partOf",
        "unitWithinFrAgency",
        "U.S. Army Reserve Command, a separate command of the Army (FR 32, 10 U.S.C. 10171); OPM holds it as ARHR.",
        "yes",
        _PART_WHY,
        (_usc(10, "10171", "The United States Army Reserve Command is a separate command of the Army commanded by the Chief of Army Reserve."),),
    ),

    # --- DoD Combatant Commands, Agencies & Statutory Offices (FR 103) ---
    Judgment(
        "northern command",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "U.S. Northern Command (USNORTHCOM), a unified combatant command of the Department of Defense (10 U.S.C. 111(b)(9), 82 FR 1192).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _DOD_FOIA_CMDS, _DOD_FOIA_COMPONENTS),
    ),
    Judgment(
        "pacific command",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "U.S. Pacific Command (USPACOM, redesignated U.S. Indo-Pacific Command by 10 U.S.C. 161 note), a unified combatant command of DoD (FR 103).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _DOD_FOIA_CMDS, _usc(10, "161", "United States Pacific Command")),
    ),
    Judgment(
        "indo pacific command",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "U.S. Indo-Pacific Command (USINDOPACOM, formerly USPACOM), a unified combatant command of DoD (FR 103, 10 U.S.C. 161 note).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _usc(10, "161", "The combatant command known as the United States Pacific Command shall be known as the 'United States Indo-Pacific Command'.")),
    ),
    Judgment(
        "southern command",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "U.S. Southern Command (USSOUTHCOM), a unified combatant command of DoD (10 U.S.C. 111(b)(9), 91 FR 67302).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _fr_doc("91 FR 67302 (2026-10-26), FR Doc 2026-21777, Department of Defense", "2026-21777", "United States Southern Command")),
    ),
    Judgment(
        "socom",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "Common official acronym for U.S. Special Operations Command (USSOCOM), a DoD unified combatant command (10 U.S.C. 167).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _usc(10, "167", "unified combatant command for special operations forces"),
         _fr_doc("89 FR 90678 (2024-11-18), FR Doc 2024-26843, Department of Defense", "2024-26843",
                 "U.S. Special Operations Command (SOCOM)")),
    ),
    Judgment(
        "defense threat reduction agency",
        _OPM + "DD61",
        103,
        "partOf",
        "unitWithinFrAgency",
        "DTRA is a Defense Agency of the Department of Defense (FR 103, 32 CFR 286.2); OPM holds it as DD61.",
        "yes",
        _PART_WHY,
        (_DOD_FOIA_COMPONENTS, _fr_doc("82 FR 1192 (2017-01-05), FR Doc 2016-31686, 32 CFR part 286", "2016-31686", "Defense Threat Reduction Agency")),
    ),
    Judgment(
        "defense security cooperation agency",
        _OPM + "DD06",
        103,
        "partOf",
        "unitWithinFrAgency",
        "DSCA is a Defense Agency of the Department of Defense (FR 103, 32 CFR 286.2); OPM holds it as DD06.",
        "yes",
        _PART_WHY,
        (_DOD_FOIA_COMPONENTS, _fr_doc("82 FR 1192 (2017-01-05), FR Doc 2016-31686, 32 CFR part 286", "2016-31686", "Defense Security Cooperation Agency")),
    ),
    Judgment(
        "federal voting assistance program",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "FVAP operates within the Department of Defense (FR 103) under the Under Secretary for Personnel and Readiness.",
        "yes",
        _PART_WHY,
        (_usc(52, "20301", "Department of Defense"),
         _fr_doc("91 FR 60944 (2026-09-25), FR Doc 2026-19607, Department of Defense", "2026-19607",
                 "Federal Voting Assistance Program, Defense Support Services Center/Personnel Readiness Management Agency")),
    ),
    Judgment(
        "test resource management center",
        _OPM + "DD68",
        103,
        "partOf",
        "unitWithinFrAgency",
        "Department of Defense Field Activity established under 10 U.S.C. 4173 (FR 103); OPM holds it as DD68.",
        "yes",
        _PART_WHY,
        (_usc(10, "4173", "Establishment as Department of Defense Field Activity"),),
    ),
    Judgment(
        "institute for national strategic studies",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "Research institute within DoD's National Defense University (FR 103, 81 FR 91143).",
        "yes",
        _PART_WHY,
        (_fr_doc("81 FR 91143 (2016-12-16), FR Doc 2016-30271, National Defense University, DoD", "2016-30271",
                 "AGENCY: National Defense University, DoD."),
         _fr_doc("81 FR 91143 (2016-12-16), FR Doc 2016-30271, National Defense University, DoD", "2016-30271",
                 "Institute for National Strategic Studies")),
    ),
    Judgment(
        "office of under secretary of defense for intelligence",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "Former statutory title of the Under Secretary of Defense for Intelligence and Security in DoD (FR 103, 10 U.S.C. 137).",
        "yes",
        _PART_WHY,
        (_usc(10, "137", "Under Secretary of Defense for Intelligence and Security"),
         _usc(10, "137", "Department of Defense")),
    ),
    Judgment(
        "office of under secretary of defense for intelligence and security",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "OUSD(I&S), statutory principal staff office in the Department of Defense (FR 103, 10 U.S.C. 137).",
        "yes",
        _PART_WHY,
        (_usc(10, "137", "There is an Under Secretary of Defense for Intelligence and Security"),
         _usc(10, "137", "Department of Defense")),
    ),
    Judgment(
        "office of assistant secretary of defense for health affairs",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "Principal staff office for medical and health readiness in the Department of Defense (FR 103, 10 U.S.C. 138).",
        "yes",
        _PART_WHY,
        (_usc(10, "138", "Assistant Secretary of Defense for Health Affairs"),
         _fr_doc("90 FR 17582 (2025-04-28), FR Doc 2025-07258, Department of Defense", "2025-07258",
                 "The Assistant Secretary of Defense for Health Affairs (ASD(HA))")),
    ),
    Judgment(
        "joint functional component command for space",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "Component command assigned to U.S. Strategic Command within DoD (10 U.S.C. 111(b)(9), EO 13760).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _USSTRATCOM_EO,
         _fr_doc("82 FR 5325 (2017-01-17), FR Doc 2017-01169, Executive Order 13760", "2017-01169",
                 "Joint Functional Component Command--Space (JFCC Space).")),
    ),
    Judgment(
        "joint functional component command for integrated missile defense",
        None,
        103,
        "partOf",
        "unitWithinFrAgency",
        "Component command assigned to U.S. Strategic Command within DoD (10 U.S.C. 111(b)(9), EO 13760).",
        "yes",
        _PART_WHY,
        (_DOD_COMMANDS, _USSTRATCOM_EO,
         _fr_doc("82 FR 5325 (2017-01-17), FR Doc 2017-01169, Executive Order 13760", "2017-01169",
                 "Joint Functional Component Command--Integrated Missile Defense (JFCC IMD).")),
    ),

    # --- Military Service Commands & Schools ---
    Judgment(
        "army futures command",
        _OPM + "ARAF",
        32,
        "partOf",
        "unitWithinFrAgency",
        "Major Army Command of the Department of the Army (FR 32); OPM holds it as ARAF.",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 13548 (2024-02-22), FR Doc 2024-03586, Department of Defense / Army", "2024-03586",
                 "Army Futures Command"),
         _fr_doc("89 FR 13548 (2024-02-22), FR Doc 2024-03586, Department of Defense / Army", "2024-03586",
                 "Department of the Army")),
    ),
    Judgment(
        "army forces command",
        _OPM + "ARFC",
        32,
        "partOf",
        "unitWithinFrAgency",
        "FORSCOM, major command of the Department of the Army (FR 32); OPM holds it as ARFC.",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 92662 (2024-11-22), FR Doc 2024-27459, Department of the Army, DoD", "2024-27459",
                 "AGENCY: Department of the Army, DoD."),
         _fr_doc("89 FR 92662 (2024-11-22), FR Doc 2024-27459, Department of the Army, DoD", "2024-27459",
                 "U.S. Army Forces Command")),
    ),
    Judgment(
        "army materiel command",
        None,
        32,
        "partOf",
        "unitWithinFrAgency",
        "AMC, major command of the Department of the Army (FR 32).",
        "yes",
        _PART_WHY,
        (_fr_doc("91 FR 67302 (2026-10-26), FR Doc 2026-21777, Department of Defense", "2026-21777",
                 "U.S. Army Materiel Command."),),
    ),
    Judgment(
        "army space and missile defense command",
        None,
        32,
        "partOf",
        "unitWithinFrAgency",
        "USASMDC, Army Service Component Command of the Department of the Army (FR 32).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 56739 (2025-12-08), FR Doc 2025-22150, Department of the Army", "2025-22150",
                 "U.S. Army Space and Missile Defense Command"),),
    ),
    Judgment(
        "installation management command",
        None,
        32,
        "partOf",
        "unitWithinFrAgency",
        "IMCOM, major subordinate command of the Department of the Army (FR 32).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 43147 (2025-09-08), FR Doc 2025-17223, FAA / DoD Army airspace", "2025-17223",
                 "United States (U.S.) Army Installation Management Command (IMCOM)"),),
    ),
    Judgment(
        "army aviation center of excellence and fort novosel",
        None,
        32,
        "partOf",
        "unitWithinFrAgency",
        "USAACE at Fort Novosel, Army Training and Doctrine Command center within the Department of the Army (FR 32).",
        "yes",
        _PART_WHY,
        (Record("congressionalHearing", "H.A.S.C. FY2024 Seapower and Tactical Air Forces Hearing (CHRG-118hhrg52384)",
                "raw/chrg-118hhrg52384.htm",
                "Commanding General, U.S. Army Aviation Center of Excellence and Fort Novosel"),
         _fr_doc("90 FR 21552 (2025-05-20), FR Doc 2025-08853, Department of Defense", "2025-08853",
                 "ARMY AVIATION CENTER OF EXCELLENCE")),
    ),
    Judgment(
        "office of assistant secretary of army",
        None,
        32,
        "partOf",
        "unitWithinFrAgency",
        "Secretariat office in the Department of the Army (FR 32, 10 U.S.C. 7016).",
        "yes",
        _PART_WHY,
        (_usc(10, "7016", "Assistant Secretary of the Army for Manpower and Reserve Affairs"),),
    ),
    Judgment(
        "air force global strike command",
        _OPM + "AFGS",
        13,
        "partOf",
        "unitWithinFrAgency",
        "AFGSC, major command of the Department of the Air Force (FR 13); OPM holds it as AFGS.",
        "yes",
        _PART_WHY,
        (_fr_doc("91 FR 64644 (2026-10-09), FR Doc 2026-20724, Department of the Air Force", "2026-20724",
                 "Department of the Air Force"),
         _fr_doc("91 FR 64644 (2026-10-09), FR Doc 2026-20724, Department of the Air Force", "2026-20724",
                 "Air Force Global Strike Command")),
    ),
    Judgment(
        "strategic systems programs",
        _OPM + "NV30",
        378,
        "partOf",
        "unitWithinFrAgency",
        "SSP, technical command within the Department of the Navy (FR 378, 80 FR 66889); OPM holds it as NV30.",
        "yes",
        _PART_WHY,
        (_fr_doc("80 FR 66889 (2015-10-30), FR Doc 2015-27713, Department of the Navy", "2015-27713",
                 "AGENCY: Department of the Navy, DoD."),
         _fr_doc("80 FR 66889 (2015-10-30), FR Doc 2015-27713, Department of the Navy", "2015-27713",
                 "Director, Strategic Systems Programs HQ")),
    ),
    Judgment(
        "naval surface warfare center",
        None,
        378,
        "partOf",
        "unitWithinFrAgency",
        "NSWC, warfare center command within the Department of the Navy (FR 378).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 74263 (2024-09-12), FR Doc 2024-20680, Department of the Navy", "2024-20680",
                 "Naval Surface Warfare Center Carderock"),),
    ),
    Judgment(
        "naval war college",
        None,
        378,
        "partOf",
        "unitWithinFrAgency",
        "Professional military education institution of the Department of the Navy (FR 378, 10 U.S.C. 8591).",
        "yes",
        _PART_WHY,
        (_usc(10, "8591", "Naval War College"),
         _fr_doc("91 FR 35969 (2026-06-15), FR Doc 2026-11925, Department of the Navy", "2026-11925",
                 "Naval War College (NWC)")),
    ),
    Judgment(
        "navy energy installations and environment",
        None,
        378,
        "partOf",
        "unitWithinFrAgency",
        "Secretariat portfolio of the Assistant Secretary of the Navy (Energy, Installations and Environment) in the Department of the Navy (FR 378, 10 U.S.C. 8016).",
        "yes",
        _PART_WHY,
        (_usc(10, "8016", "Assistant Secretaries of the Navy"),
         _fr_doc("90 FR 21552 (2025-05-20), FR Doc 2025-08853, Department of Defense", "2025-08853",
                 "ASSISTANT SECRETARY OF THE NAVY (ENERGY, INSTALLATIONS AND ENVIRONMENT)")),
    ),
    Judgment(
        "2nd marine division",
        None,
        378,
        "partOf",
        "unitWithinFrAgency",
        "Infantry division of the U.S. Marine Corps within the Department of the Navy (FR 378).",
        "yes",
        _PART_WHY,
        (Record("congressionalHearing", "H.A.S.C. FY2016 Military Construction & Readiness Hearing (CHRG-114hhrg97822)",
                "raw/chrg-114hhrg97822.htm",
                "Brian D. Beaudreault, USMC, Commanding General, 2nd Marine Division"),),
    ),

    # --- DOJ, DOI, HHS/CDC, VA, USGS, NASA, State/USAID, USDA, Smithsonian, OSTP, OIGs ---
    Judgment(
        "trustee program",
        _OPM + "DJ11",
        268,
        "partOf",
        "unitWithinFrAgency",
        "United States Trustee Program, component of the Department of Justice (FR 268, 28 U.S.C. 581); OPM holds it as DJ11.",
        "yes",
        _PART_WHY,
        (_usc(28, "581", "The Attorney General shall appoint one United States trustee"),),
    ),
    Judgment(
        "environment and natural resources division",
        None,
        268,
        "partOf",
        "unitWithinFrAgency",
        "Litigating division of the Department of Justice (FR 268, 89 FR 30392).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 30392 (2024-04-23), FR Doc 2024-07613, Department of Justice", "2024-07613",
                 "AGENCY: Environment and Natural Resources Division, United States Department of Justice."),),
    ),
    Judgment(
        "office of assistant secretary for indian affairs",
        None,
        253,
        "partOf",
        "unitWithinFrAgency",
        "Leadership office for Indian Affairs within the Department of the Interior (FR 253).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 44216 (2025-09-12), FR Doc 2025-17697, Department of the Interior", "2025-17697",
                 "DEPARTMENT OF THE INTERIOR"),
         _fr_doc("90 FR 44216 (2025-09-12), FR Doc 2025-17697, Department of the Interior", "2025-17697",
                 "The Assistant Secretary for Indian Affairs approves")),
    ),
    Judgment(
        "office of insular affairs",
        _FH + "100116252",
        253,
        "partOf",
        "unitWithinFrAgency",
        "OIA, office within the Department of the Interior (FR 253); Federal Hierarchy holds it as 100116252 ('INSULAR AFFAIRS').",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 101040 (2024-12-13), FR Doc 2024-29437, Department of the Interior", "2024-29437",
                 "DEPARTMENT OF THE INTERIOR Office of the Secretary"),
         _fr_doc("89 FR 101040 (2024-12-13), FR Doc 2024-29437, Department of the Interior", "2024-29437",
                 "Office of Insular Affairs")),
    ),
    Judgment(
        "department of interior s office of insular affairs",
        _FH + "100116252",
        253,
        "partOf",
        "unitWithinFrAgency",
        "Possessive parent-prefixed form of the Office of Insular Affairs within the Department of the Interior (FR 253).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 101040 (2024-12-13), FR Doc 2024-29437, Department of the Interior", "2024-29437",
                 "DEPARTMENT OF THE INTERIOR Office of the Secretary"),
         _fr_doc("89 FR 101040 (2024-12-13), FR Doc 2024-29437, Department of the Interior", "2024-29437",
                 "Office of Insular Affairs")),
    ),
    Judgment(
        "national center for injury prevention and control",
        None,
        44,
        "partOf",
        "unitWithinFrAgency",
        "NCIPC, national center of the Centers for Disease Control and Prevention (FR 44).",
        "yes",
        _PART_WHY,
        (_fr_doc("91 FR 10612 (2026-03-04), FR Doc 2026-04237, CDC / HHS", "2026-04237",
                 "National Center for Injury Prevention and Control; Notice of Charter Renewal AGENCY: Centers for Disease Control and Prevention (CDC)"),),
    ),
    Judgment(
        "assistant secretary for financial resources",
        None,
        221,
        "partOf",
        "unitWithinFrAgency",
        "ASFR, staff division within the Department of Health and Human Services (FR 221).",
        "yes",
        _PART_WHY,
        (_fr_doc("91 FR 12200 (2026-03-12), FR Doc 2026-04842, Department of Health and Human Services", "2026-04842",
                 "AGENCY: Office of the Assistant Secretary for Financial Resources (ASFR), Department of Health and Human Services (HHS)."),),
    ),
    Judgment(
        "office of accountability and whistleblower protection",
        _OPM + "VAAJ",
        520,
        "partOf",
        "unitWithinFrAgency",
        "Statutory office within the Department of Veterans Affairs (FR 520, 38 U.S.C. 323); OPM holds it as VAAJ.",
        "yes",
        _PART_WHY,
        (_usc(38, "323", "There is established in the Department an office to be known as the \"Office of Accountability and Whistleblower Protection\""),),
    ),
    Judgment(
        "geological survey water resources mission area",
        None,
        212,
        "partOf",
        "unitWithinFrAgency",
        "Mission area of the U.S. Geological Survey (FR 212).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 31678 (2025-07-15), FR Doc 2025-13203, U.S. Geological Survey, DOI", "2025-13203",
                 "DEPARTMENT OF THE INTERIOR Geological Survey"),
         _fr_doc("90 FR 31678 (2025-07-15), FR Doc 2025-13203, U.S. Geological Survey, DOI", "2025-13203",
                 "Water Resources Mission Area")),
    ),
    Judgment(
        "science mission directorate",
        None,
        301,
        "partOf",
        "unitWithinFrAgency",
        "Mission directorate of the National Aeronautics and Space Administration (FR 301).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 70210 (2024-08-29), FR Doc 2024-19473, NASA", "2024-19473",
                 "Science Mission Directorate, NASA Headquarters"),),
    ),
    Judgment(
        "nasa aeronautics research institute",
        None,
        301,
        "partOf",
        "unitWithinFrAgency",
        "NARI, aeronautics research institute of NASA (FR 301).",
        "yes",
        _PART_WHY,
        (Record("agencyPage", "NASA Aeronautics Research Institute (nari.arc.nasa.gov)", "raw/nasa-nari.html",
                "NARI - NASA Aeronautics Research Institute"),),
    ),
    Judgment(
        "national aeronautics and space administration office of inspector general",
        None,
        301,
        "partOf",
        "unitWithinFrAgency",
        "Office of Inspector General within NASA (FR 301).",
        "yes",
        _PART_WHY,
        (_fr_doc("91 FR 45829 (2026-07-21), FR Doc 2026-14603, NASA", "2026-14603",
                 "AGENCY: National Aeronautics and Space Administration (NASA)."),
         _fr_doc("91 FR 45829 (2026-07-21), FR Doc 2026-14603, NASA", "2026-14603",
                 "Office of Inspector General")),
    ),
    Judgment(
        "securities and exchange commission office of inspector general",
        None,
        466,
        "partOf",
        "unitWithinFrAgency",
        "Office of Inspector General within the Securities and Exchange Commission (FR 466).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 73764 (2024-09-11), FR Doc 2024-19819, SEC", "2024-19819",
                 "SEC Office of Inspector General"),),
    ),
    Judgment(
        "office of inspector general of intelligence community",
        None,
        354,
        "partOf",
        "unitWithinFrAgency",
        "Statutory Office of the Inspector General of the Intelligence Community within ODNI (FR 354, 50 U.S.C. 3033).",
        "yes",
        _PART_WHY,
        (_usc(50, "3033", "Office of the Director of National Intelligence an Office of the Inspector General of the Intelligence Community."),),
    ),
    Judgment(
        "office of inspector general americorps",
        None,
        91,
        "partOf",
        "unitWithinFrAgency",
        "Office of Inspector General of the Corporation for National and Community Service / AmeriCorps (FR 91).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 6432 (2024-02-01), FR Doc 2024-01555, Corporation for National and Community Service", "2024-01555",
                 "AmeriCorps Statement of Organization AGENCY: Corporation for National and Community Service."),
         _fr_doc("89 FR 6432 (2024-02-01), FR Doc 2024-01555, Corporation for National and Community Service", "2024-01555",
                 "Agency's Office of Inspector General")),
    ),
    Judgment(
        "office of inspector general for board of governors of federal reserve system and consumer financial protection bureau",
        None,
        188,
        "partOf",
        "unitWithinFrAgency",
        "Joint Office of Inspector General within the Federal Reserve System serving the Board and CFPB (FR 188, 90 FR 8124).",
        "yes",
        _PART_WHY,
        (_fr_doc("90 FR 8124 (2025-01-24), FR Doc 2025-01685, Federal Reserve System", "2025-01685",
                 "Office of Inspector General (OIG) in support of its inquiries, investigations, and reports relating to the programs and operations of the Board and the Consumer Financial Protection Bureau"),),
    ),
    Judgment(
        "benghazi accountability review board",
        None,
        476,
        "partOf",
        "unitWithinFrAgency",
        "Accountability Review Board convened by the Secretary of State under 22 U.S.C. 4831 (FR 476).",
        "yes",
        _PART_WHY,
        (_usc(22, "4831", "Secretary of State shall convene an Accountability Review Board"),
         _fr_doc("77 FR 66909 (2012-11-07), FR Doc 2012-27189, Department of State", "2012-27189",
                 "the Department of State announced the formation of the Benghazi Accountability Review Board (ARB)")),
    ),
    Judgment(
        "bureau for middle east",
        None,
        6,
        "partOf",
        "unitWithinFrAgency",
        "Regional bureau of the U.S. Agency for International Development (FR 6).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 85136 (2024-10-25), FR Doc 2024-24830, USAID", "2024-24830",
                 "Bureau for the Middle East, U.S. Agency for International Development."),),
    ),
    Judgment(
        "usaid bureau of conflict prevention and stabilization",
        None,
        6,
        "partOf",
        "unitWithinFrAgency",
        "Functional bureau (CPS) of the U.S. Agency for International Development (FR 6).",
        "yes",
        _PART_WHY,
        (_fr_doc("89 FR 37948 (2024-05-06), FR Doc 2024-09373, USAID", "2024-09373",
                 "Bureau for Conflict Prevention and Stabilization"),
         Record("congressionalHearing", "H.F.A.C. Hearing on Stabilization & Conflict Prevention (CHRG-117hhrg45602)",
                "raw/chrg-117hhrg45602.htm",
                "U.S. Agency for International Development, Bureau for Conflict Prevention and Stabilization")),
    ),
    Judgment(
        "marketing and regulatory programs",
        _FH + "100525723",
        12,
        "partOf",
        "unitWithinFrAgency",
        "MRP mission area of the Department of Agriculture (FR 12); Federal Hierarchy holds it as 100525723 ('ASSISTANT SECRETARY FOR MARKETING AND REGULATORY PROGRAMS').",
        "yes",
        _PART_WHY,
        (_fr_doc("91 FR 47212 (2026-07-28), FR Doc 2026-15156, USDA", "2026-15156",
                 "The Marketing and Regulatory Programs (MRP) mission area of USDA"),),
    ),
    Judgment(
        "smithsonian air and space museum",
        None,
        469,
        "partOf",
        "unitWithinFrAgency",
        "National Air and Space Museum, statutory bureau of the Smithsonian Institution (FR 469, 20 U.S.C. 77).",
        "yes",
        _PART_WHY,
        (_usc(20, "77", "established under the Smithsonian Institution a bureau to be known as a National Air and Space Museum"),
         _fr_doc("86 FR 72505 (2021-12-21), FR Doc 2021-27841, NASA", "2021-27841",
                 "Smithsonian National Air and Space Museum")),
    ),
    Judgment(
        "networking and information technology research and development program",
        None,
        464,
        "partOf",
        "unitWithinFrAgency",
        "NITRD Program coordinated under OSTP / National Coordination Office (FR 464, 15 U.S.C. 5511).",
        "yes",
        _PART_WHY,
        (_usc(15, "5511", "Sec. 5511 - Networking and Information Technology Research and Development Program"),
         _fr_doc("89 FR 106608 (2024-12-30), FR Doc 2024-31221, OSTP", "2024-31221",
                 "Networking and Information Technology Research and Development (NITRD) Program")),
    ),

    # --- Statutory federal / legislative / independent entities without FR record ---
    Judgment(
        "interagency council on homelessness",
        _OPM + "HW00",
        None,
        None,
        "noFrRecord",
        "United States Interagency Council on Homelessness (42 U.S.C. 11311); OPM holds it as HW00, FR does not.",
        "yes",
        _NO_FR_OPM_WHY,
        (_usc(42, "11311", "United States Interagency Council on Homelessness"),),
    ),
    Judgment(
        "medicaid and chip payment and access commission",
        _OPM + "RO00",
        None,
        None,
        "noFrRecord",
        "MACPAC, legislative-branch commission established under 42 U.S.C. 1396; OPM holds it as RO00, FR does not.",
        "yes",
        _NO_FR_OPM_WHY,
        (_usc(42, "1396", "There is hereby established the Medicaid and CHIP Payment and Access Commission (in this section referred to as \"MACPAC\")."),),
    ),
    Judgment(
        "open world leadership center",
        _FH + "300000111",
        None,
        None,
        "noFrRecord",
        "Legislative-branch center established by 2 U.S.C. 1151 (redesignated Congressional Office for International Leadership); Federal Hierarchy holds it as 300000111, FR does not.",
        "yes",
        _NO_FR_FH_WHY,
        (_usc(2, "1151", "Open World Leadership Center"),),
    ),
    Judgment(
        "national security commission on emerging biotechnology",
        _OPM + "LL08",
        None,
        None,
        "noFrRecord",
        "NSCEB, statutory legislative-branch commission; OPM holds it as LL08, FR does not.",
        "yes",
        _NO_FR_OPM_WHY,
        (Record("agencyPage", "National Security Commission on Emerging Biotechnology (biotech.senate.gov/about)",
                "raw/nsceb-about.html", "National Security Commission on Emerging Biotechnology"),),
    ),
)


def _records(root: Path, item: Judgment) -> list[dict[str, Any]]:
    manifest = {entry["file"]: entry for entry in json.loads((root / RECORDS_DIR / "manifest.json").read_text())}
    rows = []
    for record in item.records:
        entry = manifest.get(record.file)
        batch1._require(entry is not None, f"{item.key!r} cites {record.file}, which the records manifest does not hold")
        row = {
            "kind": record.kind,
            "citation": record.citation,
            "file": record.file,
            "records_dir": str(RECORDS_DIR),
            "url": entry["final_url"],
            "sha256": entry["sha256"],
            "passage": " ".join(record.passage.split()),
        }
        row["read"] = entity_alignments.alias_record_is_read(row, root)
        batch1._require(row["read"], f"{item.key!r}: the passage cited from {record.file} is not in its retained bytes")
        rows.append(row)
    return rows


def assemble(root: Path, releases: Sequence[RegistryRelease] | None = None) -> dict[str, Any]:
    """Assemble alias batch 2: every measured key accounted for once across rosters, records, and judgments."""

    releases = census.load_five_agency_rosters(root) if releases is None else releases
    index = batch_aliases._Index(releases)
    demand_doc = json.loads((root / DEMAND_JSON).read_text())
    demand = {row["key"]: row for row in demand_doc["demand"]}
    mechanical = index.mechanical()
    fr_names = index.fr_names()
    judged = {row.key: row for row in JUDGMENT}
    batch1._require(len(judged) == len(JUDGMENT), "a batch-2 judgment key is entered twice")
    for key in judged:
        batch1._require(key in demand, f"hand entry {key!r} is not a batch-2 demand key")

    b1_report = batch_aliases.assemble(root, releases)
    b1_keys = {row["name_key"] for row in b1_report["aliases"]}
    batch1._require(not (set(demand) & b1_keys), f"batch 2 repeats batch 1 alias keys: {sorted(set(demand) & b1_keys)}")

    aliases: list[dict[str, Any]] = []
    counts_by_id: dict[str, Any] = {}
    for key, row in demand.items():
        batch1._require(key == name_key(key), f"batch-2 key {key!r} is not a name_key fixpoint")
        batch1._require(key not in fr_names, f"{key!r} already resolves by an FR name")
        counts = {name: row[name] for name in ("federal_appearances", "all_appearances", "spellings")}
        bases = dict(mechanical.get(key, {}))
        targets = set().union(*bases.values()) if bases else set()
        if len(targets) == 1:
            batch1._require(key not in judged, f"{key!r} is mechanical; drop its hand entry")
            (target,) = targets
            record = index.record(target)
            alias: dict[str, Any] = {
                "alias_id": batch_aliases._alias_id(key),
                "name_key": key,
                "status": batch1.CANDIDATE_STATUS,
                "class": "mechanical",
                "basis": sorted(bases),
                "target": record,
                "fr": record["id"],
                "fr_record": record,
                "fr_relation": "same",
                "reasoning": "Derived from the pinned rosters by the stated rule; no hand input.",
                "records": [],
                "recommended": "yes",
                "why": "The FR record's own short name or name, or a reviewed identity's publisher name.",
                "answer_effects": batch_aliases._answer_effects("same", (), ()),
            }
        elif key in judged:
            item = judged[key]
            fr_iri = None if item.fr is None else f"{batch_aliases.IRI_PREFIXES[batch_aliases.FR]}{item.fr}"
            alias = {
                "alias_id": batch_aliases._alias_id(key),
                "name_key": key,
                "status": batch1.CANDIDATE_STATUS,
                "class": "judgment",
                "basis": [item.basis],
                "target": None if item.target is None else index.record(item.target),
                "fr": item.fr,
                "fr_record": None if fr_iri is None else index.record(fr_iri),
                "fr_relation": item.fr_relation,
                "reasoning": item.reasoning,
                "records": _records(root, item),
                "recommended": item.recommended,
                "why": item.why,
                "source_status": item.source_status,
                "source_finding": item.source_finding,
                "answer_effects": batch_aliases._answer_effects(item.fr_relation, item.options, ()),
            }
        else:
            raise ValueError(f"batch-2 demand key {key!r} is unaccounted: make it mechanical or judge it")
        alias["content_digest"] = batch1._digest(batch_aliases._content(alias))
        aliases.append(alias)
        counts_by_id[alias["alias_id"]] = counts

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": batch1.CANDIDATE_STATUS,
        "owner_reviewer_iri": batch1.OWNER_REVIEWER_IRI,
        "inputs": {
            "roster_releases": {release.key: release.source_release_digest for release in releases},
            "demand": {
                "path": str(DEMAND_JSON),
                "sha256": batch1._file_digest(root / DEMAND_JSON),
                **{key: demand_doc[key] for key in ("inputs", "thresholds", "federal")},
            },
            "records_manifest": {
                "path": str(RECORDS_DIR / "manifest.json"),
                "sha256": batch1._file_digest(root / RECORDS_DIR / "manifest.json"),
            },
        },
        "name_key": {
            "function": "refspec.atlas.agency_projection.name_key",
            "version": agency_projection.NAME_KEY_VERSION,
            "doc": " ".join(name_key.__doc__.split()),
        },
        "aliases": aliases,
        "demand": counts_by_id,
        "already_resolvable": [],
        "excluded": [],
        "candidates": [],
        "events": [],
        "non_emissions": [],
        "no_fr_bridge": [],
        "candidates_digest_covers": list(CANDIDATES_DIGEST_COVERS),
    }
    report["candidates_digest"] = canonical_digest({key: report[key] for key in CANDIDATES_DIGEST_COVERS})
    report["digest"] = batch1._digest(report)
    return report


def render_adjudication_sheet(report: Mapping[str, Any], decisions: entity_alignments.Decisions) -> str:
    """Render the owner adjudication sheet for alias batch 2 from the candidates JSON and decisions."""

    answers = entity_alignments.decision_answers(report)
    rows = [{**alias, "demand": report["demand"][alias["alias_id"]]} for alias in report["aliases"]]
    mechanical = [alias for alias in rows if alias["class"] == "mechanical"]
    judgment = [alias for alias in rows if alias["class"] == "judgment"]
    undecided = len(set(answers) - set(decisions.current))

    def decided(alias_id: str) -> str:
        if alias_id in decisions.current:
            d = decisions.current[alias_id]
            return f"**{d['answer']}** ({d['decided_on']}, {d['channel']})"
        return "stale: re-confirm" if alias_id in decisions.stale else "undecided"

    lines = [
        "<!-- markdownlint-disable MD013 -->",
        "",
        "# Agency registry alias batch 2 — owner adjudication sheet",
        "",
        (
            "Generated from [agency-registry-alias-batch-2-candidates.json](agency-registry-alias-batch-2-candidates.json) "
            "and [agency-registry-alias-batch-2-decisions.json](agency-registry-alias-batch-2-decisions.json) by "
            "`tools/assemble_agency_registry_alias_batch_2.py`; its default run fails if this sheet disagrees with either. "
            f"**Do not edit this sheet.** Reviewer `{report['owner_reviewer_iri']}` records answers in the decisions file."
        ),
        "",
        (
            f"Decisions recorded: {len(decisions.current)} current, {len(decisions.stale)} stale, {undecided} of "
            f"{len(answers)} undecided. Candidates digest `{report['candidates_digest']}`; demand evidence "
            f"`{report['inputs']['demand']['path']}` (`{report['inputs']['demand']['sha256']}`)."
        ),
        "",
        f"## Mechanical ({len(mechanical)})",
        "",
        *batch1._table(
            ("Id", "Spellings seen", "Demand", "Resolves to", "Basis", "Decision"),
            [
                (
                    f"`{a['alias_id']}`",
                    batch_aliases._spelled(a),
                    batch_aliases._demand(a),
                    batch_aliases._fr(a),
                    ", ".join(f"`{b}`" for b in a["basis"]),
                    decided(a["alias_id"]),
                )
                for a in mechanical
            ],
        ),
        "",
        f"## Judgment ({len(judgment)})",
        "",
        (
            "Every cited record is retained under `research/evidence/agency-alias-records-2026-11-25/` and verified "
            "verbatim against its retained bytes via `alias_record_is_read()`."
        ),
        "",
    ]
    for alias in judgment:
        records = "; ".join(
            f"[{r['citation']}]({r['url']}): \"{r['passage']}\"" + ("" if r["read"] else " (unread)")
            for r in alias["records"]
        )
        lines.extend(
            [
                f"### `{alias['alias_id']}` — {batch_aliases._spelled(alias)}",
                "",
                *batch1._table(
                    ("Field", "Value"),
                    (
                        ("Demand (federal / all)", batch_aliases._demand(alias)),
                        ("Names", batch_aliases._target(alias)),
                        ("FR-keyed consumers get", batch_aliases._fr(alias)),
                        ("Basis", f"`{alias['basis'][0]}`"),
                        ("Reasoning", alias["reasoning"]),
                        ("Records read", records),
                        ("Recommended", f"**{alias['recommended']}** — {alias['why']}"),
                        ("Owner decision / date", decided(alias["alias_id"])),
                    ),
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Decision keys",
            "",
            *batch1._table(
                ("Id", "Answers", "Recommended", "Content digest"),
                [
                    (
                        f"`{a['alias_id']}`",
                        " / ".join(f"`{x}`" for x in answers[a["alias_id"]]),
                        f"`{a['recommended']}`",
                        f"`{a['content_digest']}`",
                    )
                    for a in rows
                ],
            ),
            "",
        ]
    )
    if decisions.stale:
        lines.extend(
            [
                "## Stale decisions",
                "",
                *batch1._table(
                    ("Id", "Answer", "Decided on", "Decided on content digest"),
                    [
                        (f"`{key}`", d["answer"], d["decided_on"], f"`{d['content_digest']}`")
                        for key, d in decisions.stale.items()
                    ],
                ),
                "",
            ]
        )
    return "\n".join(lines)


def write_or_check(root: Path, *, write: bool, releases: Sequence[RegistryRelease] | None = None) -> list[str]:
    """Write the generated batch-2 plans/ artifacts, or return the ones missing or drifted."""

    report = assemble(root, releases)
    decisions_path = root / DECISIONS_JSON
    decisions = (
        entity_alignments.load_decisions(decisions_path, report)
        if decisions_path.is_file()
        else entity_alignments.Decisions(current={}, stale={})
    )
    problems = []
    outputs = {
        REPORT_JSON: batch1._canonical_json_bytes(report) + b"\n",
        ADJUDICATION_MARKDOWN: render_adjudication_sheet(report, decisions).encode("utf-8"),
    }
    for relative, payload in outputs.items():
        path = root / relative
        if write:
            path.write_bytes(payload)
        elif not path.is_file() or path.read_bytes() != payload:
            problems.append(f"{'drifted' if path.is_file() else 'missing'}: {relative}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the generated plans/ artifacts (default: check them)")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = write_or_check(args.repo_root.resolve(), write=args.write)
    if problems:
        raise SystemExit("alias batch 2 artifacts out of date: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

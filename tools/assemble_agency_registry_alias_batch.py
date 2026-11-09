"""Assemble the agency registry's alias batch and its owner adjudication sheet (candidates, never assertions).

An alias says "this free-text string names this organization": the strings
witnesses, filers and dockets write ("U.S. Army", "Veterans Health
Administration", "General Accounting Office") rather than any publisher's
identifier. The design note (plans/agency-registry-design.md section 1) plans
free-text resolution; this batch proposes the first aliases, chosen by measured
demand: congressional-tech's federal witness strings that the pinned Federal
Register roster misses (research/evidence/agency-alias-demand-2026-11-08/,
read by digest). Nothing here is an assertion until the owner decides, exactly
as for batch 1 and the succession batch.

Every demand key above the evidence's thresholds is accounted for, once:

- **already resolvable** -- the key equals a Federal Register name under
  ``name_key``; no alias is needed (the consumer's own normalizer missed it);
- **mechanical** -- derived from the pinned rosters by one stated rule, with no
  hand input: the key equals exactly one FR record's short name
  (``frShortNameEquality``), its name with the trailing organization word moved
  to the front ("Land Management Bureau" -> "bureau of land management",
  ``frNameWordOrder``), or the name of a regulations.gov record that REF-038's
  reviewed identity maps to exactly one FR record
  (``reviewedIdentityPublisherName``);
- **judgment** -- a hand-entered row (``JUDGMENT``) naming its target, the FR
  record a Federal-Register-keyed consumer resolves it to and how (the same
  organization, or a part of it), a basis, the public records behind it, and a
  recommended answer with its reason;
- **excluded** -- not a federal agency name at all (``EXCLUDED``), with a reason.

A key both mechanical and hand-entered, a hand entry for a key outside the
demand set, and a demand key left unaccounted are all refused. Each decidable
item carries a ``content_digest`` over what the owner decides on (key, target,
FR resolution, basis, records, question); the demand counts and spellings are
left out, so a re-measurement stales nothing. ``--write`` writes the JSON and
the sheet; the default re-derives both and fails on any drift. The owner
answers in plans/agency-registry-alias-batch-decisions.json, which this tool
only reads, through the decision contract batch 1 uses (``load_decisions``).
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from refspec.atlas import agency_projection
from refspec.atlas import v3_registry_alignments_entity as entity_alignments
from refspec.atlas.v3_source_data import RegistryRelease

try:
    from tools import analyze_agency_roster_identifiers as census
    from tools import assemble_agency_registry_batch_1 as batch1
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_agency_roster_identifiers as census
    import assemble_agency_registry_batch_1 as batch1

SCHEMA_VERSION = "refspec-agency-registry-alias-batch-candidates/1"
REPORT_JSON = Path("plans/agency-registry-alias-batch-candidates.json")
ADJUDICATION_MARKDOWN = Path("plans/agency-registry-alias-batch-adjudication.md")
DECISIONS_JSON = Path("plans/agency-registry-alias-batch-decisions.json")
DEMAND_JSON = Path("research/evidence/agency-alias-demand-2026-11-08/federal-misses.json")
CANDIDATES_DIGEST_COVERS = ("aliases",)

FR = agency_projection.FR_RELEASE_KEY
REGS = agency_projection.REGULATIONS_GOV_RELEASE_KEY
IRI_PREFIXES = {
    FR: "urn:ref:federal-register-agency:",
    agency_projection.FH_RELEASE_KEY: "urn:ref:federal-hierarchy-org:",
    agency_projection.OPM_RELEASE_KEY: "urn:ref:opm-ehri-agency-subelement:",
    agency_projection.ECFR_RELEASE_KEY: "urn:ref:ecfr-agency:",
    REGS: "urn:ref:regulations-gov-agency:",
}
ROSTER_LABELS = {
    FR: "FR",
    agency_projection.FH_RELEASE_KEY: "Federal Hierarchy",
    agency_projection.OPM_RELEASE_KEY: "OPM",
    agency_projection.ECFR_RELEASE_KEY: "eCFR",
    REGS: "regulations.gov",
}
# The organization words FR names put last ("Land Management Bureau"); frNameWordOrder moves one to the front.
ORGANIZATION_WORDS = (
    "administration", "agency", "board", "bureau", "center", "commission", "corps", "council", "department",
    "institute", "office", "service",
)
_WORD_ORDER = re.compile(rf"^(?P<head>.+) (?P<word>{'|'.join(ORGANIZATION_WORDS)})$")

FrRelation = Literal["same", "partOf"]
ExclusionReason = Literal[
    "notAFederalAgency", "congressOrCourt", "genericTitleOrFragment", "compoundWithParentName",
    "compoundOfTwoOrganizations", "segmentationArtifact", "truncated",
]


def name_key(text: str) -> str:
    """The match key every alias is published under: case-folded words, qualifiers and "the" dropped.

    NFKC and case-folded; "&" read as "and"; parentheticals dropped; every run
    of other characters one space; then the words "the", "u s", "us", "united
    states" and "of america" dropped wherever they stand. Two strings name the
    same alias exactly when their keys are equal, so a consumer applies this
    function to its own strings and looks the key up. It is congressional-tech's
    em-fedagency normalizer with one repair: runs collapse before the qualifier
    words are dropped, so "U. S. Fish and Wildlife Service" loses its "u s".
    """

    folded = unicodedata.normalize("NFKC", text).casefold().replace("&", " and ")
    folded = " ".join(re.sub(r"[^a-z0-9]+", " ", re.sub(r"\([^)]*\)", " ", folded)).split())
    return " ".join(re.sub(r"\b(the|u s|us|united states|of america)\b", " ", folded).split())


def word_order_key(name: str) -> str | None:
    """An FR name's key with its trailing organization word moved to the front, or None if it ends otherwise."""

    match = _WORD_ORDER.fullmatch(name_key(name))
    return None if match is None else f"{match['word']} of {match['head']}"


@dataclass(frozen=True, slots=True)
class Record:
    """One public record behind a judgment row; ``read`` is False until its bytes are retained and read."""

    kind: Literal["statute", "publicLaw", "executiveOrder"]
    citation: str
    url: str | None
    note: str
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "citation": self.citation, "url": self.url, "note": self.note, "read": self.read}


@dataclass(frozen=True, slots=True)
class Judgment:
    """A hand-entered alias candidate. ``target`` names the organization itself where a held roster has it.

    ``fr`` is the Federal Register id a FR-keyed consumer resolves the alias to:
    the organization itself (``same``) or the FR record it is part of
    (``partOf``); None where no FR record is either. ``options``, when given,
    replaces yes/no with numbered answers; ``recommended`` is one of the answers.
    """

    key: str
    target: str | None
    fr: int | None
    fr_relation: FrRelation | None
    basis: str
    reasoning: str
    recommended: str
    why: str
    records: tuple[Record, ...] = ()
    options: tuple[str, ...] = ()


def _usc(title: int, section: str, note: str) -> Record:
    return Record(
        "statute",
        f"{title} U.S.C. {section}",
        f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{title}-section{section}&num=0&edition=prelim",
        note,
    )


_FH, _OPM = "urn:ref:federal-hierarchy-org:", "urn:ref:opm-ehri-agency-subelement:"
_SERVICE_OPTIONS = (
    "Yes, as the same organization: the alias resolves to the FR department record with no qualifier.",
    (
        "Yes, as part of it: the alias resolves to the FR department record, marked part-of (the service is "
        "the department's uniformed component)."
    ),
    "No alias.",
)
_SERVICE_WHY = (
    "Option 2 gives the consumer the same FR id as option 1 without claiming the service and the department "
    "are one organization; the department also holds civilian offices the service is not."
)
_PART_WHY = "The unit has no FR record; a part-of row gives the FR id of the organization it sits in, and claims no identity."
_TYPO_WHY = "No publisher spells it so; a misspelling is the consumer's fuzzy matcher's job, not a reviewed alias."
_COMMAND_WHY = (
    "A combatant command is a Department of Defense component (10 U.S.C. 161) with no FR record; part-of DOD "
    "is the only FR resolution, and it claims no identity."
)


def _command(key: str, target: str | None = None, *, note: str) -> Judgment:
    return Judgment(key, target, 103, "partOf", "unitWithinFrAgency", note, "yes", _COMMAND_WHY,
                    (_usc(10, "161", "Combatant commands are established by the President through the Secretary of Defense."),))


def _misspelling(key: str, fr: int, name: str) -> Judgment:
    return Judgment(key, None, fr, "same", "misspelling", f"A misspelling of {name}.", "no", _TYPO_WHY)


# Hand-entered rows. Statute citations are the agent's reading of where each organization is
# established; none has been retained or read yet (``read=False``), and the release step refuses
# an adopted row until its records are read (plans/agency-registry-alias-plan.md section 4).
JUDGMENT: tuple[Judgment, ...] = (
    Judgment("veterans health administration", _OPM + "VATA", 520, "partOf", "unitWithinFrAgency",
             "VHA is an administration of the Department of Veterans Affairs; OPM holds it as VATA, the FR does not.",
             "yes", _PART_WHY, (_usc(38, "7301", "Establishes the Veterans Health Administration in the Department."),)),
    Judgment("veterans benefits administration", _OPM + "VALA", 520, "partOf", "unitWithinFrAgency",
             "VBA is an administration of the Department of Veterans Affairs; OPM holds it as VALA.",
             "yes", _PART_WHY, (_usc(38, "7701", "Establishes the Veterans Benefits Administration in the Department."),)),
    Judgment("national cemetery administration", _OPM + "VAPA", 520, "partOf", "unitWithinFrAgency",
             "NCA is an administration of the Department of Veterans Affairs; OPM holds it as VAPA.",
             "yes", _PART_WHY, (_usc(38, "2400", "Establishes the National Cemetery Administration in the Department."),)),
    Judgment("army", None, 32, "partOf", "militaryServiceOfDepartment",
             "The Army is the service the Department of the Army (FR 32, 'Army Department') organizes; OPM's AR is the "
             "department, not the service.",
             "2", _SERVICE_WHY, (_usc(10, "7062", "Composition of the Army."),), _SERVICE_OPTIONS),
    Judgment("navy", None, 378, "partOf", "militaryServiceOfDepartment",
             "The Navy is a service of the Department of the Navy (FR 378, 'Navy Department'), which also holds the Marine Corps.",
             "2", _SERVICE_WHY, (_usc(10, "8062", "Composition of the Navy."),), _SERVICE_OPTIONS),
    Judgment("air force", None, 13, "partOf", "militaryServiceOfDepartment",
             "The Air Force is a service of the Department of the Air Force (FR 13), which also holds the Space Force.",
             "2", _SERVICE_WHY, (_usc(10, "9062", "Composition of the Air Force."),), _SERVICE_OPTIONS),
    Judgment("marine corps", _OPM + "NV27", 378, "partOf", "militaryServiceOfDepartment",
             "The Marine Corps is a service within the Department of the Navy (FR 378); OPM holds it as NV27.",
             "yes", _PART_WHY, (_usc(10, "8063", "The Marine Corps, within the Department of the Navy."),)),
    Judgment("usmc", _OPM + "NV27", 378, "partOf", "militaryServiceOfDepartment",
             "USMC, the Marine Corps' own acronym; the same row as 'marine corps'.",
             "yes", _PART_WHY, (_usc(10, "8063", "The Marine Corps, within the Department of the Navy."),)),
    Judgment("space force", _OPM + "AF4G", 13, "partOf", "militaryServiceOfDepartment",
             "The Space Force is a service within the Department of the Air Force (FR 13); OPM holds it as AF4G.",
             "yes", _PART_WHY, (_usc(10, "9081", "Establishes the Space Force within the Department of the Air Force."),)),
    Judgment("office of secretary of defense", _OPM + "DD01", 103, "partOf", "unitWithinFrAgency",
             "OSD is the Secretary's principal staff element in the Department of Defense (FR 103); OPM holds it as DD01.",
             "yes", _PART_WHY, (_usc(10, "131", "Office of the Secretary of Defense."),)),
    Judgment("joint chiefs of staff", _OPM + "DD02", 103, "partOf", "unitWithinFrAgency",
             "The Joint Chiefs of Staff sit in the Department of Defense; OPM holds their organization as DD02.",
             "yes", _PART_WHY, (_usc(10, "151", "Joint Chiefs of Staff: composition; functions."),)),
    Judgment("joint staff", None, 103, "partOf", "unitWithinFrAgency",
             "The Joint Staff serves the Chairman of the Joint Chiefs of Staff in the Department of Defense; no held roster holds it alone.",
             "yes", _PART_WHY, (_usc(10, "155", "Joint Staff."),)),
    Judgment("national reconnaissance office", _FH + "500019037", 103, "partOf", "unitWithinFrAgency",
             "NRO is a Department of Defense agency; the Federal Hierarchy holds it as 500019037 ('NATIONAL RECONNAISSANCE OFFICE (NRO)').",
             "yes", _PART_WHY),
    Judgment("missile defense agency", _FH + "300000429", 103, "partOf", "unitWithinFrAgency",
             "MDA is a Department of Defense agency; the Federal Hierarchy holds it as 300000429.", "yes", _PART_WHY),
    Judgment("defense health agency", _FH + "300000422", 103, "partOf", "unitWithinFrAgency",
             "DHA is a Department of Defense agency; the Federal Hierarchy holds it as 300000422.", "yes", _PART_WHY),
    Judgment("defense innovation unit", None, 103, "partOf", "unitWithinFrAgency",
             "DIU is a Department of Defense organization no held roster holds.", "yes", _PART_WHY),
    Judgment("national guard bureau", None, 103, "partOf", "unitWithinFrAgency",
             "The National Guard Bureau is a joint activity of the Department of Defense; OPM holds only its chief's office (ARGB).",
             "yes", _PART_WHY, (_usc(10, "10501", "National Guard Bureau."),)),
    _command("cyber command", _FH + "300000421", note="U.S. Cyber Command; the Federal Hierarchy holds it as 300000421."),
    _command("special operations command", _FH + "300000430", note="U.S. Special Operations Command; the Federal Hierarchy holds it as 300000430."),
    _command("transportation command", _OPM + "DD76", note="U.S. Transportation Command; OPM holds it as DD76."),
    _command("strategic command", note="U.S. Strategic Command; no held roster holds the command itself."),
    _command("africa command", note="U.S. Africa Command; OPM's AF1R is an Air Force code, so not taken as the command."),
    _command("space command", note="U.S. Space Command; no held roster holds the command itself."),
    _command("central command", note="U.S. Central Command; no held roster holds the command itself."),
    _command("european command", note="U.S. European Command; no held roster holds the command itself."),
    _command("forces korea", note="U.S. Forces Korea, a subordinate unified command; no held roster holds it."),
    Judgment("office of chief of naval operations", None, 378, "partOf", "unitWithinFrAgency",
             "The Office of the Chief of Naval Operations is the Navy's headquarters staff in the Department of the Navy.",
             "yes", _PART_WHY),
    Judgment("headquarters marine corps", None, 378, "partOf", "unitWithinFrAgency",
             "Headquarters, Marine Corps sits in the Department of the Navy.", "yes", _PART_WHY),
    Judgment("headquarters air force", None, 13, "partOf", "unitWithinFrAgency",
             "Headquarters Air Force (the Secretariat and Air Staff) sits in the Department of the Air Force.", "yes", _PART_WHY),
    Judgment("air force space command", None, 13, "partOf", "unitWithinFrAgency",
             "Air Force Space Command, an Air Force major command until the Space Force took it in 2019-2020.",
             "yes", "Part-of the Department of the Air Force is true for the command's whole life, before and after the Space Force."),
    Judgment("congressional research service", None, 277, "partOf", "unitWithinFrAgency",
             "CRS is a department of the Library of Congress (FR 277); no held roster holds it.",
             "yes", _PART_WHY, (_usc(2, "166", "Congressional Research Service, in the Library of Congress."),)),
    Judgment("national counterterrorism center", None, 354, "partOf", "unitWithinFrAgency",
             "NCTC is a center of the Office of the Director of National Intelligence (FR 354). FR 334, the National "
             "Counterintelligence Center, carries the short name 'NCTC': an acronym collision, so the acronym is never an alias here.",
             "yes", _PART_WHY, (_usc(50, "3056", "National Counterterrorism Center, in the Office of the Director of National Intelligence."),)),
    Judgment("national science board", None, 366, "partOf", "unitWithinFrAgency",
             "The National Science Board is the governing board of the National Science Foundation (FR 366).",
             "yes", _PART_WHY, (_usc(42, "1863", "National Science Board."),)),
    Judgment("national institute of allergy and infectious diseases", None, 353, "partOf", "unitWithinFrAgency",
             "NIAID is an institute of the National Institutes of Health (FR 353).",
             "yes", _PART_WHY, (_usc(42, "285f", "National Institute of Allergy and Infectious Diseases."),)),
    Judgment("national forest system", None, 209, "partOf", "unitWithinFrAgency",
             "The National Forest System is the lands the Forest Service (FR 209) administers; as a witness's organization it "
             "names the Forest Service's National Forest System deputy area.",
             "yes", _PART_WHY, (_usc(16, "1609", "The National Forest System."),)),
    Judgment("bureau of near eastern affairs", None, 476, "partOf", "unitWithinFrAgency",
             "A regional bureau of the Department of State (FR 476).", "yes", _PART_WHY),
    Judgment("office of information and regulatory affairs", None, 280, "partOf", "unitWithinFrAgency",
             "OIRA is an office within the Office of Management and Budget (FR 280); regulations.gov lists it as its own "
             "agency code, but no reviewed REF-038 row maps that code to an FR record.",
             "yes", _PART_WHY, (_usc(44, "3503", "Office of Information and Regulatory Affairs, in the Office of Management and Budget."),)),
    Judgment("cybersecurity and infrastructure security agency", _FH + "500044551", 227, "partOf", "unitWithinFrAgency",
             "CISA is a Department of Homeland Security agency. REF-038 already maps regulations.gov 'CISA' to Federal "
             "Hierarchy 500044551, and batch 1 recorded that the held FR roster has no CISA record (noCounterpartInHeldFRRoster).",
             "yes", _PART_WHY),
    Judgment("national security agency", None, 367, "same", "publisherNameVariant",
             "FR 367 is 'National Security Agency/Central Security Service'; the Federal Hierarchy names the same agency "
             "'NATIONAL SECURITY AGENCY (NSA)' (300000420).",
             "yes", "Dropping the Central Security Service half of a dual-named agency names the same agency, as the Federal Hierarchy does."),
    Judgment("army corps of engineers", None, 142, "same", "publisherNameVariant",
             "FR 142 is 'Engineers Corps'; eCFR's short name for the same corps is 'Army Corps of Engineers'.",
             "yes", "Another publisher's name for the FR record's organization."),
    Judgment("office of comptroller of currency", None, 80, "same", "publisherNameVariant",
             "FR 80 is 'Comptroller of the Currency'; the statute names the agency the Office of the Comptroller of the "
             "Currency, as the Federal Hierarchy and OPM do.",
             "yes", "The FR names the office by its head; the statutory name is the same agency.",
             (_usc(12, "1", "Office of the Comptroller of the Currency."),)),
    Judgment("export import bank of", None, 151, "same", "publisherNameVariant",
             "'Export-Import Bank of the United States' is the statutory name of FR 151 ('Export-Import Bank').",
             "yes", "The statutory name of the FR record's organization. Batch 1's EIB/USEIB non-emission concerns an eCFR bridge, not this.",
             (_usc(12, "635", "Export-Import Bank of the United States."),)),
    Judgment("federal bureau of prisons", None, 437, "same", "publisherNameVariant",
             "FR 437 is 'Prisons Bureau'; the bureau calls itself the Federal Bureau of Prisons, and the Federal Hierarchy "
             "names it 'FEDERAL PRISON SYSTEM / BUREAU OF PRISONS'.",
             "yes", "The bureau's own name for the FR record's organization."),
    Judgment("usda office of inspector general", None, 244, "same", "publisherNameVariant",
             "FR 244 is 'Inspector General Office, Agriculture Department'; this is its name in natural order with the "
             "parent's acronym.",
             "yes", "The parent acronym makes an otherwise ambiguous 'Office of Inspector General' name exactly one FR record."),
    Judgment("health and human services", None, 221, "same", "publisherNameVariant",
             "FR 221 is 'Health and Human Services Department'; the name without 'Department'.",
             "yes", "Unambiguous: no other held organization is named Health and Human Services."),
    Judgment("labor", None, 271, "same", "publisherNameVariant",
             "'Labor' as a whole organization string; FR 271 is 'Labor Department'.",
             "no", "A single common word: in witness titles it is as often a portfolio ('Assistant Secretary for Labor') as the department."),
    Judgment("energy", None, 136, "same", "publisherNameVariant",
             "'Energy' as a whole organization string; FR 136 is 'Energy Department'.",
             "no", "A single common word; 'Energy and Commerce' and 'Energy and Environment' split to it."),
    Judgment("education", None, 126, "same", "publisherNameVariant",
             "'Education' as a whole organization string; FR 126 is 'Education Department'.",
             "no", "A single common word, as often a portfolio or a state agency as the department."),
    Judgment("board of governors of federal reserve system", None, 188, "partOf", "unitWithinFrAgency",
             "FR 188 is 'Federal Reserve System'; eCFR holds the Board of Governors and the System as two records.",
             "2", "Option 2 gives the same FR id without claiming the Board is the whole System, which eCFR keeps apart.",
             (_usc(12, "241", "Board of Governors of the Federal Reserve System."),),
             ("Yes, as the same organization as FR 188.", "Yes, as part of FR 188 (the System's governing board).", "No alias.")),
    Judgment("general accounting office", None, 213, "same", "statutoryRename",
             "The Government Accountability Office's name before 2004-07-07. OPM's pinned roster states it: LG00, 'WHOSE "
             "NAME, PRIOR TO JULY 7, 2004, HAD BEEN THE GENERAL ACCOUNTING OFFICE'. The FR holds one record, FR 213, so "
             "there is no succession to state (the rename rule: a stale name no roster holds as its own record is identity evidence).",
             "yes", "One organization renamed by statute; the old name appears in 214 unmatched appearances.",
             (Record("publicLaw", "Pub. L. 108-271, sec. 8(a), 118 Stat. 811 (2004-07-07), GAO Human Capital Reform Act of 2004",
                     "https://www.congress.gov/108/plaws/publ271/PLAW-108publ271.pdf",
                     "Renames the General Accounting Office the Government Accountability Office."),)),
    Judgment("department of war", None, 103, "same", "secondaryTitle",
             "The secondary title the President authorized for the Department of Defense (FR 103) in September 2025.",
             "yes", "An official title of the same department; adopt once the order is read.",
             (Record("executiveOrder", "Executive Order 14347 (2025-09-05), Restoring the United States Department of War", None,
                     "Authorizes 'Department of War' as a secondary title of the Department of Defense."),)),
    Judgment("capitol police", _FH + "500193110", None, None, "noFrRecord",
             "The United States Capitol Police, a legislative-branch agency; the Federal Hierarchy holds it (500193110), the FR does not.",
             "yes", "Names the Federal Hierarchy record; an FR-keyed consumer gets no FR id, which is the truth."),
    Judgment("office of congressional workplace rights", _OPM + "ZG00", None, None, "noFrRecord",
             "A legislative-branch office (the Office of Compliance until 2018); OPM holds it as ZG00, the FR does not.",
             "yes", "Names the OPM record; no FR id."),
    Judgment("commission on international religious freedom", _OPM + "ZP00", None, None, "noFrRecord",
             "USCIRF; OPM holds it as ZP00. The Federal Hierarchy holds two records of the same name (300000724, 300000894), "
             "so neither is taken.",
             "yes", "Names the one OPM record; no FR id."),
    _misspelling("federal bureau of investigations", 160, "the Federal Bureau of Investigation (FR 160)"),
    _misspelling("veterans benefit administration", 520, "the Veterans Benefits Administration"),
    _misspelling("federal energy regulatory commision", 167, "the Federal Energy Regulatory Commission (FR 167)"),
    _misspelling("national institute of health", 353, "the National Institutes of Health (FR 353)"),
)

_NGO = "notAFederalAgency"
EXCLUDED: Mapping[str, tuple[ExclusionReason, str]] = {
    **dict.fromkeys(("chamber of commerce", "disabled american veterans", "veterans of foreign wars", "american federation of government employees", "national congress of american indians", "national indian health board", "afl cio", "national council of urban indian health", "heritage foundation", "foundation for defense of democracies", "council on foreign relations", "american civil liberties union", "wounded warrior project", "information technology and innovation foundation", "airlines for america", "national center for missing and exploited children", "german marshall fund of"), (_NGO, "a private organization or union")),
    **dict.fromkeys(("navajo nation", "confederated tribes of colville reservation", "cherokee nation", "eastern band of cherokee indians", "quapaw nation", "miami tribe of oklahoma", "southern ute indian tribe"), (_NGO, "a tribal government")),
    **dict.fromkeys(("new york", "florida", "new jersey", "az", "district of columbia", "tucson", "state of florida"), (_NGO, "a state, city or place")),
    **dict.fromkeys(("idaho national laboratory", "oak ridge national laboratory", "pacific northwest national laboratory"), (_NGO, "a contractor-operated national laboratory, not an agency")),
    "united nations command": (_NGO, "a multinational command under a UN mandate"),
    **dict.fromkeys(("senate", "committee on ethics", "joint committee on taxation", "supreme court of"), ("congressOrCourt", "a chamber, committee or court, not an agency")),
    **dict.fromkeys(("director", "office of inspector general", "office of general counsel", "headquarters", "engineering", "installations and environment", "energy and environment", "environment", "chair", "partner", "commander", "ms"), ("genericTitleOrFragment", "a title or a fragment naming no one organization")),
    **dict.fromkeys(("veterans health administration department of veterans affairs", "veterans benefits administration department of veterans affairs", "usda forest service"), ("compoundWithParentName", "an alias followed or led by its parent's name; the consumer splits it off")),
    "northern command and north american aerospace defense command": (
        "compoundOfTwoOrganizations", "two commands under one commander (NORTHCOM and the binational NORAD)",
    ),
    **dict.fromkeys(("national commission on military", "national", "and public service"), ("segmentationArtifact", "a piece of 'National Commission on Military, National, and Public Service' (FR 594), which the consumer's comma split broke")),
    "department of veterans": ("truncated", "a truncated 'Department of Veterans Affairs'"),
}


class _Index:
    """The five pinned rosters, read for names, parents and the reviewed REF-038 identities."""

    def __init__(self, releases: Sequence[RegistryRelease]) -> None:
        self.releases = {release.key: release for release in releases}
        self.resources = {resource.iri: (release.key, resource) for release in releases for resource in release.resources}
        self.parents = {key: agency_projection.parent_by_subject(release) for key, release in self.releases.items()}
        identity = entity_alignments.load_regulations_gov_agency_identity_mapping_release(releases)
        projection = agency_projection.build_agency_projection(releases, identity)
        self.reviewed_fr = defaultdict(set)
        for row in projection.rows:
            if row.org.startswith(IRI_PREFIXES[FR]):
                self.reviewed_fr[IRI_PREFIXES[REGS] + row.source_value].add(row.org)

    def record(self, iri: str) -> dict[str, Any]:
        key, resource = self.resources[iri]
        field, name = entity_alignments.publisher_name(key, resource)
        record: dict[str, Any] = {"roster": ROSTER_LABELS[key], "release_key": key, "resource_iri": iri,
                                  "name_field": field, "publisher_name": name}
        if key == FR:
            record.update(id=int(resource.native_payload["id"]), short_name=resource.native_payload.get("short_name"))
        parent = self.parents[key].get(iri)
        record["parent"] = None if parent is None or parent not in self.resources else {
            "resource_iri": parent, "publisher_name": self.record(parent)["publisher_name"]}
        return record

    def mechanical(self) -> dict[str, dict[str, set[str]]]:
        """Each key a mechanical rule derives, by basis, with the FR records it reaches."""

        found: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for iri, (key, resource) in self.resources.items():
            if key == FR:
                if short := resource.native_payload.get("short_name"):
                    found[name_key(short)]["frShortNameEquality"].add(iri)
                if inverted := word_order_key(str(resource.native_payload["name"])):
                    found[inverted]["frNameWordOrder"].add(iri)
            elif key == REGS and len(self.reviewed_fr.get(iri, ())) == 1:
                for label in (entity_alignments.publisher_name(key, resource)[1], *(lab.value for lab in resource.labels)):
                    found[name_key(label)]["reviewedIdentityPublisherName"] |= self.reviewed_fr[iri]
        return found

    def fr_names(self) -> dict[str, set[str]]:
        names: dict[str, set[str]] = defaultdict(set)
        for iri, (key, resource) in self.resources.items():
            if key == FR:
                names[name_key(str(resource.native_payload["name"]))].add(iri)
        return names


def _alias_id(key: str) -> str:
    return "alias:" + key.replace(" ", "-")


def _content(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"content_digest", "demand"}}


def assemble(root: Path, releases: Sequence[RegistryRelease] | None = None) -> dict[str, Any]:
    """The batch's report: every demand key accounted for once, from the rosters, the evidence and the hand rows."""

    releases = census.load_five_agency_rosters(root) if releases is None else releases
    index = _Index(releases)
    demand_doc = json.loads((root / DEMAND_JSON).read_text())
    demand = {row["key"]: row for row in demand_doc["demand"]}
    mechanical = index.mechanical()
    fr_names = index.fr_names()
    judged = {row.key: row for row in JUDGMENT}
    batch1._require(len(judged) == len(JUDGMENT), "a judgment key is entered twice")
    for key in (*judged, *EXCLUDED):
        batch1._require(key in demand, f"hand entry {key!r} is not a demand key")
    batch1._require(not set(judged) & set(EXCLUDED), "a key is both judged and excluded")

    aliases: list[dict[str, Any]] = []
    resolvable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for key, row in demand.items():
        counts = {name: row[name] for name in ("federal_appearances", "all_appearances", "spellings")}
        if key in fr_names:
            batch1._require(key not in judged and key not in EXCLUDED, f"{key!r} already resolves by an FR name")
            resolvable.append({"key": key, "fr": [index.record(iri) for iri in sorted(fr_names[key])], "demand": counts})
            continue
        bases = dict(mechanical.get(key, {}))
        targets = set().union(*bases.values()) if bases else set()
        if len(targets) == 1:
            batch1._require(key not in judged and key not in EXCLUDED, f"{key!r} is mechanical; drop its hand entry")
            (target,) = targets
            alias = {
                "alias_id": _alias_id(key),
                "name_key": key,
                "status": batch1.CANDIDATE_STATUS,
                "class": "mechanical",
                "basis": sorted(bases),
                "target": index.record(target),
                "fr": index.record(target)["id"],
                "fr_relation": "same",
                "reasoning": "Derived from the pinned rosters by the stated rule; no hand input.",
                "records": [],
                "recommended": "yes",
                "why": "The FR record's own short name or name, or a reviewed identity's publisher name.",
            }
        elif key in judged:
            item = judged[key]
            batch1._require(item.recommended in (("yes", "no") if not item.options else
                            tuple(str(n) for n in range(1, len(item.options) + 1))), f"{key!r} recommends an answer it does not offer")
            batch1._require(item.target is None or item.target in index.resources, f"{key!r} targets no held roster record")
            batch1._require((item.fr is None) == (item.fr_relation is None), f"{key!r} states an FR id without a relation")
            fr_iri = None if item.fr is None else IRI_PREFIXES[FR] + str(item.fr)
            batch1._require(fr_iri is None or fr_iri in index.resources, f"{key!r} names no held FR record")
            alias = {
                "alias_id": _alias_id(key),
                "name_key": key,
                "status": batch1.CANDIDATE_STATUS,
                "class": "judgment",
                "basis": [item.basis],
                "target": None if item.target is None else index.record(item.target),
                "fr": item.fr,
                "fr_record": None if fr_iri is None else index.record(fr_iri),
                "fr_relation": item.fr_relation,
                "reasoning": item.reasoning,
                "records": [record.to_dict() for record in item.records],
                "recommended": item.recommended,
                "why": item.why,
            }
            if len(targets) > 1:
                alias["mechanical_collision"] = sorted(targets)
            if item.options:
                alias["owner_question"] = {"options": list(item.options)}
        elif key in EXCLUDED:
            reason, note = EXCLUDED[key]
            excluded.append({"key": key, "reason": reason, "note": note, "demand": counts})
            continue
        else:
            raise ValueError(f"demand key {key!r} is unaccounted: make it mechanical, judge it, or exclude it")
        alias["demand"] = counts
        alias["content_digest"] = batch1._digest(_content(alias))
        aliases.append(alias)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": batch1.CANDIDATE_STATUS,
        "owner_reviewer_iri": batch1.OWNER_REVIEWER_IRI,
        "inputs": {
            "roster_releases": {release.key: release.source_release_digest for release in releases},
            "demand": {"path": str(DEMAND_JSON), "sha256": batch1._file_digest(root / DEMAND_JSON),
                       **{key: demand_doc[key] for key in ("inputs", "thresholds", "federal")}},
        },
        "name_key": {"function": "tools/assemble_agency_registry_alias_batch.py name_key", "doc": " ".join(name_key.__doc__.split())},
        "aliases": aliases,
        "already_resolvable": resolvable,
        "excluded": excluded,
        # The decision contract reads these; an alias batch proposes no bridge, event or non-emission.
        "candidates": [],
        "events": [],
        "non_emissions": [],
        "no_fr_bridge": [],
        "candidates_digest_covers": list(CANDIDATES_DIGEST_COVERS),
    }
    report["candidates_digest"] = batch1._digest({"aliases": [_content(alias) for alias in aliases]})
    report["digest"] = batch1._digest(report)
    return report


# --- Rendering: every sentence below is generated from the report. ---


def _target(alias: Mapping[str, Any]) -> str:
    target = alias["target"]
    return "none held" if target is None else f"{target['roster']} `{target['resource_iri'].rsplit(':', 1)[1]}` {target['publisher_name']}"


def _fr(alias: Mapping[str, Any]) -> str:
    if alias["fr"] is None:
        return "no FR id"
    name = (alias.get("fr_record") or alias["target"])["publisher_name"]
    return f"FR {alias['fr']} {name}" + (" (part of)" if alias["fr_relation"] == "partOf" else "")


def _demand(alias: Mapping[str, Any]) -> str:
    demand = alias["demand"]
    return f"{demand['federal_appearances']} / {demand['all_appearances']}"


def _spelled(row: Mapping[str, Any]) -> str:
    return "; ".join(f"{text} ({n})" for text, n in row["demand"]["spellings"][:3])


def render_adjudication_sheet(report: Mapping[str, Any], decisions: entity_alignments.Decisions) -> str:
    """The owner's sheet, generated from the JSON and the decisions file; it adjudicates nothing."""

    answers = entity_alignments.decision_answers(report)
    mechanical = [alias for alias in report["aliases"] if alias["class"] == "mechanical"]
    judgment = [alias for alias in report["aliases"] if alias["class"] == "judgment"]
    federal = report["inputs"]["demand"]["federal"]
    undecided = len(set(answers) - set(decisions.current))

    def decided(alias_id: str) -> str:
        if alias_id in decisions.current:
            decision = decisions.current[alias_id]
            return f"**{decision['answer']}** ({decision['decided_on']}, {decision['channel']})"
        return "stale: re-confirm" if alias_id in decisions.stale else "undecided"

    lines = [
        "<!-- markdownlint-disable MD013 -->",
        "",
        "# Agency registry alias batch — owner adjudication sheet",
        "",
        (
            "Generated from [agency-registry-alias-batch-candidates.json](agency-registry-alias-batch-candidates.json) "
            "and [agency-registry-alias-batch-decisions.json](agency-registry-alias-batch-decisions.json) by "
            "`tools/assemble_agency_registry_alias_batch.py`; its default run fails if this sheet disagrees with either. "
            f"**Do not edit this sheet.** You (reviewer `{report['owner_reviewer_iri']}`) answer through the question "
            "tool or by editing the decisions file, exactly as for batch 1: each decision is keyed by the alias id and "
            "records the answer, the date, the channel and the item's `content_digest` (the Decision keys table). "
            "Every row is `candidate-pending-owner-adjudication`. The plan this batch serves is "
            "[agency-registry-alias-plan.md](agency-registry-alias-plan.md)."
        ),
        "",
        (
            f"Decisions recorded: {len(decisions.current)} current, {len(decisions.stale)} stale, {undecided} of "
            f"{len(answers)} undecided. Candidates digest `{report['candidates_digest']}`; demand evidence "
            f"`{report['inputs']['demand']['path']}` (`{report['inputs']['demand']['sha256']}`)."
        ),
        "",
        (
            f"**Demand.** congressional-tech's {federal['appearances']:,} federal-typed witness appearances: "
            f"{federal['matched']:,} already match a pinned FR name or short name, {federal['null_organization']:,} "
            f"name no organization, and the rest split into {federal['unmatched_segment_keys']} distinct unmatched "
            f"keys. {len(report['aliases']) + len(report['already_resolvable']) + len(report['excluded'])} keys pass "
            "the thresholds (3 federal appearances, or 25 of any witness type), and each is below exactly once: "
            f"{len(mechanical)} mechanical, {len(judgment)} judgment, {len(report['already_resolvable'])} already "
            f"resolvable, {len(report['excluded'])} excluded. Counts read federal / all."
        ),
        "",
        (
            "**How to answer fast.** Every row carries a recommended answer and its reason. Answering every row "
            "with its recommendation is one instruction (\"accept the recommendations\"), and any row can be "
            "answered otherwise by id. A part-of row resolves an FR-keyed consumer to the FR record the unit sits "
            "in and claims no identity; where same-or-part-of is unclear the sheet recommends part-of, because "
            "the FR id is the same and nothing is claimed."
        ),
        "",
        f"## Mechanical ({len(mechanical)}) — recommended: yes to all",
        "",
        (
            "Each follows from the pinned rosters by a stated rule and needs no hand input: `frShortNameEquality` (the "
            "FR record's short name), `frNameWordOrder` (its name with the trailing organization word moved to the "
            "front), `reviewedIdentityPublisherName` (the name of a regulations.gov record REF-038's reviewed identity "
            "maps to exactly this FR record)."
        ),
        "",
        *batch1._table(
            ("Id", "Spellings seen", "Demand", "Resolves to", "Basis", "Decision"),
            [(f"`{a['alias_id']}`", _spelled(a), _demand(a), _fr(a), ", ".join(f"`{b}`" for b in a["basis"]), decided(a["alias_id"]))
             for a in mechanical],
        ),
        "",
        f"## Judgment ({len(judgment)})",
        "",
        (
            "Records marked unread are cited, not yet retained; the release step refuses an adopted row until its "
            "records are read (plan section 4)."
        ),
        "",
    ]
    for alias in judgment:
        options = alias.get("owner_question", {}).get("options")
        answer_text = (
            " / ".join(f"`{n}` {text}" for n, text in enumerate(options, start=1)) if options else "`yes` / `no`"
        )
        records = "; ".join(
            f"[{r['citation']}]({r['url']})" if r["url"] else r["citation"] for r in alias["records"]
        ) or "the held roster records named"
        lines.extend(
            [
                f"### `{alias['alias_id']}` — {_spelled(alias)}",
                "",
                *batch1._table(
                    ("Field", "Value"),
                    (
                        ("Demand (federal / all)", _demand(alias)),
                        ("Names", _target(alias)),
                        ("FR-keyed consumers get", _fr(alias)),
                        ("Basis", f"`{alias['basis'][0]}`"),
                        ("Reasoning", alias["reasoning"]),
                        ("Records", records + ("" if all(r["read"] for r in alias["records"]) else " (unread)")),
                        ("Answers", answer_text),
                        ("Recommended", f"**{alias['recommended']}** — {alias['why']}"),
                        ("Owner decision / date", decided(alias["alias_id"])),
                    ),
                ),
                "",
            ]
        )
    lines.extend(
        [
            f"## Already resolvable ({len(report['already_resolvable'])}) — no alias needed",
            "",
            "The key equals an FR name under the published `name_key`; the consumer's own normalizer missed it.",
            "",
            *batch1._table(
                ("Key", "Spellings seen", "FR record"),
                [(f"`{r['key']}`", _spelled(r), "; ".join(f"FR {f['id']} {f['publisher_name']}" for f in r["fr"]))
                 for r in report["already_resolvable"]],
            ),
            "",
            f"## Excluded ({len(report['excluded'])}) — not federal agency names",
            "",
            "Listed so nothing is dropped silently; say so to move any into a later batch.",
            "",
            *batch1._table(
                ("Key", "Demand", "Reason", "Note"),
                [(f"`{r['key']}`", f"{r['demand']['federal_appearances']} / {r['demand']['all_appearances']}", f"`{r['reason']}`", r["note"])
                 for r in report["excluded"]],
            ),
            "",
            "## Decision keys",
            "",
            *batch1._table(
                ("Id", "Answers", "Recommended", "Content digest"),
                [(f"`{a['alias_id']}`", " / ".join(f"`{x}`" for x in answers[a["alias_id"]]), f"`{a['recommended']}`", f"`{a['content_digest']}`")
                 for a in report["aliases"]],
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
                    [(f"`{key}`", d["answer"], d["decided_on"], f"`{d['content_digest']}`") for key, d in decisions.stale.items()],
                ),
                "",
            ]
        )
    return "\n".join(lines)


def write_or_check(root: Path, *, write: bool, releases: Sequence[RegistryRelease] | None = None) -> list[str]:
    """Write the generated plans/ artifacts, or return the ones missing or drifted; the decisions file is only read."""

    report = assemble(root, releases)
    decisions = entity_alignments.load_decisions(root / DECISIONS_JSON, report)
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
        raise SystemExit("alias batch artifacts out of date: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

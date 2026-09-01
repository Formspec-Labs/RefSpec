"""Derive ``roster.csv`` from the 2026-08-23 initialism investigation.

The investigation left one file, ``initialisms.csv``, with a single ``status``
column that lumped every kind of evidence under the word "pinned" — a live
publisher quote and "the full name the investigator hypothesised resolves in
the index" sat in the same bucket. Those are not the same claim, and a rule
that treated them alike would be spending the second one's 15.25% wrong-survivor
rate on rows the first one earned honestly. This script splits them, keys every
row by the agency whose filings the evidence was gathered from, and checks each
act name against the pinned act index before it will write it.

    .venv/bin/python research/evidence/initialism-roster-2026-08-24/build_roster.py \
        [--remeasure <dir with unified_agenda_legal_authorities.parquet>]

Deterministic: no clock, no network, and **no artifact**. Running it writes
``roster.csv`` byte for byte, which is the property that makes the file a
receipt rather than a snapshot of whatever was on disk the day someone ran it.

``rows_observed``, the one column that used to be read out of a live build, is
pinned in :data:`_ROWS_OBSERVED` instead. What it counts, exactly:

* the rows of ``unified_agenda_legal_authorities.parquet`` that are
  ``authority_type='other'`` **and** ``parse_status='failed'`` -- the rows no
  grammar reads -- whose text names this token, at this agency prefix;
* **first recognized token wins**: :func:`observed` breaks out of a row after
  the first capitalised token the roster holds, so a row naming two roster
  tokens is credited to the leftmost one only. This is why MIPPA@0938 reads
  29 where a mention census reads 37 and an answerable-subset census reads 26.
  It is a census of ROWS THIS ROSTER ROW COULD SPEAK FIRST FOR, not of
  mentions;
* measured **when the roster was built**, 2026-08-24, against that day's
  artifact, and **self-invalidating by design**: retiering a row is what
  finally lets the builder read the very rows this column counts, so a later
  build measures fewer -- for the six tokens #62 Piece A retiers, an
  integrated rebuild of 2026-08-31 measured ARRA 0, MIPPA 3, MMA 0, NDAA-17 0,
  NEPA 0 and UMTRCA 0 where this table pins 14, 29, 6, 25, 14 and 10. A drop
  is the roster working, not the number rotting. The pinned value stays what
  it was, because it says how big the problem was when the row was minted.
  ``--remeasure`` against the pre-retiering artifact of the same day already
  shows 23 such drops from earlier waves (BBRA 40 -> 9, TEA-21@2126 19 -> 0),
  every one of them a shape or a name this builder learned to read.

``--remeasure`` runs the census against any built artifact and prints the
drift; it never writes it. The check that breaks is the drift report, not a
silently rewritten column.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from refspec.registry.act_resolution import ActIndex, resolve_act_name  # noqa: E402
from refspec.registry.citation_grammar import normalize_popular_name  # noqa: E402

SOURCE = REPO / "research/evidence/investigations-2026-08-23/inv-initialisms/initialisms.csv"
RAW = "research/evidence/investigations-2026-08-23/inv-initialisms/raw"
ACT_INDEX = REPO / "output/usc-act-index-2026-08-22"
#: The pinned act index is itself an in-repo, digest-carrying receipt, and it is
#: what every ``candidate-index-match`` row cites: the claim such a row makes is
#: exactly "this name is listed in that artifact", which the artifact settles.
ACT_INDEX_EVIDENCE = "output/usc-act-index-2026-08-22/usc-popular-names.parquet"

#: Piece A of #62 (2026-08-24): a live Federal Register document, fetched and
#: hashed under ``research/evidence/investigations-2026-08-24/inv-62/raw/``,
#: binds the token to this act AT THIS AGENCY -- a publisher's sentence, not
#: "the hypothesised name resolves in the index". Keyed by (token, agency)
#: because the claim is agency-specific: MMA also files at 0938, where CMS's
#: own roster already reaches three Medicare acts by these initials and this
#: entry must not touch that row (see ``AGENCY_KEYED["MMA"]["0938"]``); NEPA
#: and ARRA each file at several other agencies this investigation did not
#: check. INA@1205 was checked the same way (q8e_ina_eta_rules.json,
#: fr_INA_1205_2026-02131.xml) and no live quote binding the bare token was
#: found within budget, so it stays ``candidate-index-match`` -- an honest
#: negative, not an oversight.
_PIECE_A_PINNED_QUOTES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("MMA", "0917"): (
        "research/evidence/investigations-2026-08-24/inv-62/raw/fr_MMA_0917_07-2740.xml",
        "293056eb03cede284c3b35770ab5698e01d19c18182efd2ad8d3008cc119f7af",
        (
            "\"...establishing regulations required by section 506 of the Medicare Prescription Drug, "
            "Improvement, and Modernization Act of 2003 (MMA), (Pub. L. 108-173). Section 506 of the MMA "
            "amended section 1866 (a)(1) of the Social Security Act...\" -- FR doc. 07-2740, 2007-06-04, "
            "RIN 0917-AA02, Indian Health Service"
        ),
    ),
    ("NDAA-17", "0720"): (
        "research/evidence/investigations-2026-08-24/inv-62/raw/fr_NDAA17_0720_2019-02532.xml",
        "458606b571d5a82ad161e784f50b969cee4469ff52d121ff29e99290871652c8",
        (
            "\"This final rule implements the primary features of section 701 and partially implements "
            "several other sections of the National Defense Authorization Act for Fiscal Year 2017 "
            "(NDAA-17).\" -- FR doc. 2019-02532, 2019-02-15, RIN 0720-AB70, Office of the Assistant "
            "Secretary for Health Affairs (DoD)"
        ),
    ),
    ("MIPPA", "0938"): (
        "research/evidence/investigations-2026-08-24/inv-62/raw/q5d_mippa_sitewide.json",
        "7716757df67e335e32be625a0e5c9899c9f52d83f47519cb739b39b3445481a7",
        (
            "Title and abstract of FR doc. E9-863 (2009-01-16, RIN 0938-AP59, CMS): \"...Certain "
            "Provisions of the Medicare Improvements for Patients and Providers Act of 2008 (MIPPA)...\" "
            "-- repeated in E9-2839, E9-3491, Z9-2839, same RIN; not fetched as XML, title/abstract "
            "sufficed"
        ),
    ),
    ("NEPA", "0412"): (
        "research/evidence/investigations-2026-08-24/inv-62/raw/fr_NEPA_0412_2014-24828.xml",
        "1a9f6c5d574d7bd2282e57aca6d36cabf41d90b709a22853333e1158b74d3630",
        (
            "\"USAID proposes a rule to establish environmental compliance procedures pursuant to the "
            "National Environmental Policy Act (NEPA).\" -- FR doc. 2014-24828, 2014-10-20, RIN "
            "0412-AA64, Agency for International Development (USAID)"
        ),
    ),
    ("ARRA", "0412"): (
        "research/evidence/investigations-2026-08-24/inv-62/raw/fr_check_2026-10817.xml",
        "b4c8b8396ef4363996edc277076eaf9992d9d993037a0fdf4ebfac4ec5b2781b",
        (
            "\"...related to the American Recovery and Reinvestment Act of 2009 (ARRA). Part 176 was "
            "initially issued to govern the use of funds...\" -- FR doc. 2026-10817, 2026-05-29, RIN "
            "0412-AB19 (one of 40 co-filing RINs on a joint OMB-led rule), USAID"
        ),
    ),
    ("UMTRCA", "2060"): (
        "research/evidence/investigations-2026-08-24/inv-62/raw/q9_umtrca_epa.json",
        "2c8caa77275473891b98f0be85189fea4e38f97b0a08993c23e0ae408f72b5c4",
        (
            "Abstract of FR doc. 2017-00573 (2017-01-19, RIN 2060-AP43, EPA Office of Air and "
            "Radiation): \"...proposing new health and environmental protection standards under the "
            "Uranium Mill Tailings Radiation Control Act (UMTRCA) of 1978.\" -- companion final/"
            "withdrawal 2018-23583, same RIN, same language"
        ),
    ),
}

#: The ``rows_observed`` census as measured when this roster was built
#: (2026-08-24), keyed ``(TOKEN, agency prefix)``. Pinned rather than read
#: out of whatever build happens to be on disk, so this script reproduces
#: the committed file exactly; see the module docstring for what the number
#: counts, why the first recognized token wins, and why a later build
#: measures fewer. ``--remeasure`` compares this table against a live
#: artifact and prints the difference.
_ROWS_OBSERVED: dict[tuple[str, str], int] = {
    ("AML", "1506"): 0, ("ANILCA", "1024"): 2, ("APUSC", "1902"): 1, ("ARRA", "0412"): 14,
    ("ARRA", "1810"): 0, ("ARRA", "1855"): 1, ("ATRA", "0938"): 3, ("BA", "0938"): 0,
    ("BB", "0938"): 0, ("BB", "1210"): 0, ("BB", "1545"): 9, ("BB", "1615"): 0,
    ("BB", "1904"): 0, ("BB", "3206"): 0, ("BBA", "0936"): 0, ("BBA", "0938"): 15,
    ("BBA", "0960"): 0, ("BBRA", "0938"): 40, ("BIPA", "0938"): 23, ("CAA", "2009"): 6,
    ("CAA", "2012"): 0, ("CAA", "2020"): 0, ("CAA", "2050"): 0, ("CAA", "2060"): 29,
    ("CAA", "2070"): 1, ("CAA", "2090"): 0, ("CAAA", "2020"): 0, ("CAAA", "2050"): 0,
    ("CAAA", "2060"): 8, ("CADC", "3072"): 0, ("CEA", "3038"): 2, ("CMHS", "0930"): 0,
    ("CMVSA", "2126"): 0, ("CWA", "0710"): 0, ("CWA", "2009"): 5, ("CWA", "2020"): 2,
    ("CWA", "2030"): 0, ("CWA", "2040"): 4, ("CWA", "2050"): 0, ("CWA", "2060"): 0,
    ("DCR", "3225"): 12, ("DEL", "1902"): 0, ("DHS", "1601"): 9, ("DHS", "1625"): 8,
    ("DOE", "1901"): 0, ("DOE", "1902"): 3, ("DOJ", "1103"): 5, ("DOJ", "1105"): 0,
    ("EE", "0790"): 3, ("EE", "1513"): 0, ("EPA", "0596"): 7, ("EPA", "2030"): 2,
    ("EPCRA", "2020"): 0, ("EPCRA", "2025"): 10, ("EPCRA", "2070"): 0, ("ESSA", "1810"): 0,
    ("FAA", "2105"): 0, ("FAIR", "0563"): 0, ("FASA", "2030"): 1, ("FAST", "2125"): 0,
    ("FAST", "2126"): 0, ("FAST", "2130"): 0, ("FAST", "2132"): 0, ("FBI", "1105"): 2,
    ("FD&C", "0910"): 0, ("FDASIA", "0910"): 0, ("FEMA", "3067"): 1, ("FERC-2006", "1902"): 0,
    ("FIFRA", "2020"): 0, ("FIFRA", "2070"): 4, ("FIPS", "0790"): 9, ("FLPMA", "1004"): 0,
    ("FLSA", "1210"): 10, ("FLSA", "1215"): 14, ("FLSA", "1218"): 0, ("FMC", "3072"): 0,
    ("FOIA", "0348"): 0, ("FOIA", "0412"): 0, ("FOIA", "0605"): 0, ("FOIA", "0960"): 0,
    ("FOIA", "0991"): 0, ("FOIA", "1212"): 0, ("FOIA", "2105"): 0, ("FOIA", "3005"): 0,
    ("FOIA", "3037"): 0, ("FOIA", "3076"): 0, ("FOIA", "3137"): 0, ("FOIA", "3155"): 0,
    ("FOIA", "3219"): 0, ("FS", "0596"): 1, ("FSA", "0938"): 2, ("FSH", "0596"): 18,
    ("FY", "0348"): 0, ("FY", "0790"): 0, ("FY", "1205"): 0, ("FY", "1215"): 0,
    ("FY", "1240"): 0, ("FY", "1400"): 1, ("FY", "1601"): 0, ("FY", "2502"): 0,
    ("FY", "3206"): 0, ("HIPAA", "0938"): 5, ("HIPAA", "0945"): 0, ("HIPAA", "1210"): 0,
    ("HSIA", "0648"): 18, ("HTS", "0551"): 1, ("HTSUS", "1505"): 0, ("HTSUS", "1515"): 1,
    ("HTSUS", "1651"): 0, ("HTSUS", "1685"): 0, ("IEEPA", "0694"): 1, ("IEEPA", "1505"): 0,
    ("IIJA", "0348"): 0, ("IIJA", "2105"): 5, ("IIJA", "2132"): 23, ("INA", "1205"): 12,
    ("INA", "1400"): 1, ("INA", "1615"): 2, ("INA", "1651"): 0, ("INS", "1615"): 1,
    ("IRPS", "3133"): 1, ("LU", "2125"): 0, ("LU", "2126"): 0, ("LU", "2127"): 2,
    ("LU", "2132"): 0, ("MAP-21", "2125"): 0, ("MAP-21", "2126"): 1, ("MAP-21", "2130"): 0,
    ("MAP-21", "2132"): 1, ("MCA", "2126"): 3, ("MCSA", "2126"): 0, ("MIPPA", "0938"): 29,
    ("MMA", "0917"): 6, ("MMA", "0938"): 8, ("MMEA", "0938"): 1, ("MMPA", "0648"): 1,
    ("MMSEA", "0938"): 4, ("MSCFMA", "0648"): 1, ("NAFTA", "1400"): 7, ("NAFTA", "1615"): 2,
    ("NDAA", "0348"): 0, ("NDAA", "0720"): 8, ("NDAA", "0790"): 4, ("NDAA", "1400"): 0,
    ("NDAA", "1601"): 0, ("NDAA", "2133"): 0, ("NDAA", "3206"): 0, ("NDAA-17", "0720"): 25,
    ("NEPA", "0412"): 14, ("NEPA", "1090"): 0, ("NEPA", "2020"): 1, ("NEPA", "2127"): 0,
    ("NEPA", "2700"): 0, ("NEPA", "3084"): 0, ("NPHA", "0648"): 0, ("NPI", "0938"): 6,
    ("NPS", "0938"): 6, ("OBRA", "0938"): 2, ("OL", "0991"): 1, ("OSH", "1218"): 0,
    ("PHA", "0906"): 3, ("PHA", "0920"): 0, ("PHS", "0906"): 0, ("PHS", "0910"): 0,
    ("PHS", "0920"): 0, ("PHS", "0930"): 2, ("PHS", "0937"): 0, ("PHS", "0938"): 2,
    ("PHS", "0950"): 0, ("PHS", "1210"): 0, ("PHSA", "0906"): 4, ("PPA", "0348"): 0,
    ("PPA", "2025"): 0, ("PPA", "2070"): 0, ("PPAC", "0906"): 0, ("PPAC", "0917"): 0,
    ("PPAC", "0991"): 0, ("PPACA", "0938"): 0, ("PPRA", "0938"): 6, ("PRWORA", "0938"): 2,
    ("PRWORA", "1205"): 0, ("RCRA", "2050"): 2, ("RCRA", "2060"): 3, ("RCRA", "2070"): 0,
    ("RCRA", "2090"): 0, ("REAL", "1601"): 0, ("SAFE", "1515"): 0, ("SAFE", "3133"): 0,
    ("SAFTEA", "2126"): 6, ("SAPT", "0930"): 0, ("SCHIP", "0938"): 4, ("SDWA", "2020"): 0,
    ("SDWA", "2040"): 2, ("SDWA", "2070"): 0, ("SMART", "0938"): 6, ("SS", "0906"): 0,
    ("SS", "0936"): 1, ("SS", "0938"): 0, ("SSA", "0936"): 4, ("SSA", "0938"): 3,
    ("SSA", "0985"): 0, ("SSA", "0991"): 0, ("SSA", "2502"): 0, ("SSA", "2510"): 0,
    ("SUC", "2120"): 5, ("SWDA", "2040"): 0, ("SWDA", "2090"): 2, ("TD", "1512"): 1,
    ("TEA-21", "2105"): 1, ("TEA-21", "2126"): 19, ("TPTCC", "0938"): 1, ("TSCA", "2050"): 0,
    ("TSCA", "2060"): 1, ("TSCA", "2070"): 9, ("UCMJ", "0702"): 1, ("UDC", "2502"): 0,
    ("UMTRCA", "2060"): 10, ("USA", "1506"): 0, ("USA", "1902"): 1, ("USAC", "3235"): 1,
    ("USCC", "0960"): 0, ("USCG", "1625"): 0, ("USCU", "1513"): 1, ("USD", "0790"): 1,
    ("USDC", "2900"): 0, ("USE", "1018"): 0, ("USHA", "2577"): 4, ("USO", "0919"): 3,
    ("USPHSA", "0938"): 3, ("UUSC", "3206"): 0, ("VCDR", "1400"): 2, ("VGBA", "3041"): 1,
    ("WHA", "2900"): 1, ("WSARA", "0750"): 0, ("WSC", "3072"): 1, ("YSC", "0572"): 1,
}

#: Which committed receipt carries the quote a ``pinned-quote`` row cites. The
#: Federal Register bodies are stored verbatim under ``raw/``; the OLRC popular
#: names page is NOT (14 MB of HTML), so its two rows cite the fetch's own HTTP
#: response headers, which ARE committed, and repeat the digest the
#: investigation recorded for the body in ``SHA256SUMS.txt``.
QUOTE_RECEIPTS: dict[str, tuple[str, str]] = {
    "BBRA": (f"{RAW}/fr_BBRA_2000.json", "8cf0638c3a0f3db0fd8fa5954fd1a48c204b4b422784788b50994c9bee61eeee"),
    "FD&C": (f"{RAW}/fr_FDC_quote.json", "7f38ae523deb08e9d1372370bb37d93d4b9eeb136d2cc53b0eb01ea71773100d"),
    "HSIA": (f"{RAW}/fr_HSIA_2024-15790.xml", "b2cce2bb44de9b04a963a7f5ca2aade8a54e5db12e715783d8dd4b0ba99cd489"),
    "IIJA": (f"{RAW}/fr_IIJA_phrase.json", "f4aadd3e78385c0be8bb62a09338039d39a8657a451d2228de16c7af2f88b8ec"),
    "PHS": (f"{RAW}/fr_PHS_search.json", "f081cd2f42ce708f084c11aad45958e3147b9149714b318621212146bfdba746"),
    "SMART": (f"{RAW}/fr_SMART_named.json", "20af5dca25add9226869db113fb123e4987e9c879e1e8a46251ccdc21b7d9990"),
    "TEA-21": (f"{RAW}/fr_TEA21_1998.json", "d54746d6362138e1b2d88562d8ca7047b8242f4030613f4141c1b8f3641e82b0"),
    "LU": (f"{RAW}/popularnames.headers.txt", "7cbacdbcea8834be6591226dfc8c0f1714bbf7006a0b2dff300f3112f1c26489"),
    "SAFTEA": (f"{RAW}/popularnames.headers.txt", "7cbacdbcea8834be6591226dfc8c0f1714bbf7006a0b2dff300f3112f1c26489"),
}

#: A Public Law number written in the SAME authority text whose act's initials
#: are the token. The corpus states the law; the index states the law's name;
#: the two meet on the number, and nothing was hypothesised.
REVERSE_PL = {"FAA", "FAST", "FDASIA", "HIPAA", "PPAC", "PPACA", "PRWORA"}

#: The row itself spells the name beside the token — "Division B--REAL ID Act of
#: 2005", "North Pacific Halibut Act of 1982 (NPHA)". Testimony from the filer,
#: which is the posture ``_ACT_GLOSS`` already takes for "Name (ABBR)".
SELF_GLOSSING = {"ESSA", "IEEPA", "NPHA", "REAL", "USHA", "WSARA"}

#: Names the investigation wrote for a human that the index lists differently.
#: Each is verified below; none is a second reading of the evidence.
NAME_FIXES = {
    "FAST": "FAST Act",
    "HSIA": "Hydrographic Services Improvement Act of 1998",
    "LU": "Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users",
    "SAFTEA": "Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users",
    "MAP-21": "Moving Ahead for Progress in the 21st Century Act",
}

#: The eight tokens #45 keys by agency because the token means different things
#: at different filers. Written out rather than derived, because which agency
#: means which act is a finding, not a rule.
AGENCY_KEYED: dict[str, dict[str, tuple[str, str, str]]] = {
    # token -> agency -> (status, act name or "", note)
    "EPA": {
        "0596": ("candidate-index-match", "Energy Policy Act of 1992",
                 "the Forest Service writes 'EPA 1992'; the index lists the Energy Policy Act of 1992 at "
                 "102-486, and no document glossing 'EPA 1992' that way was found"),
        "2030": ("ambiguous", "",
                 "'EPA Acquisition Regulation sec 205' is the Environmental Protection Agency's own "
                 "procurement regulation — the agency, not an act"),
    },
    "MMA": {
        "0917": ("candidate-index-match", "Medicare Prescription Drug, Improvement, and Modernization Act of 2003",
                 "IHS writes 'MMA, sec 506'; one act survives at this agency"),
        "0938": ("candidate-index-match", "Medicare Prescription Drug, Improvement, and Modernization Act of 2003",
                 "CMS's own roster reaches three Medicare acts by these initials and the builder refuses "
                 "the row on that count — this entry never overrides that refusal"),
    },
    "SAFE": {
        "1515": ("self-glossing", "Security and Accountability for Every Port Act of 2006",
                 "CBP's own text writes 'Security and Accountability for Every (SAFE) Port Act of 2006'"),
        "3133": ("candidate-index-match", "Secure and Fair Enforcement for Mortgage Licensing Act of 2008",
                 "NCUA writes 'SAFE Mortgage Licensing Act', close to but not OLRC's wording; OLRC "
                 "carries a third, unrelated SAFE as well"),
    },
    "DHS": {
        "1601": ("not-an-act:agency", "", "OLRC lists 'DHS' as an also-known-as of the DART Act, which is "
                                          "exactly why this token must never resolve"),
        "1625": ("not-an-act:agency", "", "same"),
    },
    "USCG": {"1625": ("ambiguous", "", "'33 USCG 1231' is either 33 U.S.C. 1231 with a damaged label or the "
                                       "issuing agency's own initials, and the text cannot say which")},
    "INS": {"1615": ("ambiguous", "", "'INS secs. 208, 241, and 274A' are Immigration and Nationality Act "
                                      "section numbers, but INS is also the pre-2003 agency")},
    "NPS": {"0938": ("ambiguous", "", "'NPS System of Records' is a Privacy Act system of records, not an act")},
    "USA": {
        "1506": ("ambiguous", "", "'USA' here is part of 'USA PATRIOT Act'; the index's only literal '(USA)' "
                                  "is the Uninterrupted Scholars Act, a false match"),
        "1902": ("ambiguous", "", "'49 USA app 1 to 85' is the damaged-label family, task #31's, not a roster's"),
    },
}

#: NDAA is not agency-ambiguous, it is YEAR-ambiguous: every fiscal year is a
#: different act. The key is (token, year) and a row that states no year stays
#: refused. Two of the five are not listed in the pinned index at all, which is
#: recorded rather than papered over.
NDAA_YEARS = {
    "2009": ("National Defense Authorization Act for Fiscal Year 2009", "110-417"),
    "2013": ("National Defense Authorization Act for Fiscal Year 2013", "112-239"),
    "2017": ("National Defense Authorization Act for Fiscal Year 2017", "114-328"),
    "2021": ("National Defense Authorization Act for Fiscal Year 2021", "116-283"),
    "2023": ("National Defense Authorization Act for Fiscal Year 2023", "117-263"),
}
#: FOIA splits the same way: the base 1966 act is not a listed name, and which
#: amending act a row means depends on the year it states.
FOIA_YEARS = {
    "1996": "Electronic Freedom of Information Act Amendments of 1996",
    "2016": "FOIA Improvement Act of 2016",
}

FIELDS = (
    "token", "agency_prefix", "year_key", "status", "act_name", "table3_key",
    "evidence_path", "evidence_sha256", "evidence_quote", "rows_observed", "notes",
)


def tier(row: dict[str, str]) -> str:
    """Which evidence tier one investigation row actually stands on."""

    if row["status"].startswith("not-an-act") or row["status"] in {"ambiguous", "belief-only"}:
        return row["status"]
    if row["evidence_kind"] in {"federal-register-document", "olrc-popular-names-table"}:
        return "pinned-quote"
    if row["token"] in REVERSE_PL:
        return "reverse-pl-verified"
    if row["token"] in SELF_GLOSSING:
        return "self-glossing"
    return "candidate-index-match"


def observed(artifact: Path | None) -> dict[tuple[str, str], int]:
    """(token, agency prefix) -> unread rows this roster row could speak first for.

    Counts rows the builder still cannot read at all -- ``other``/``failed`` --
    whose text names the token, at the token's own agency prefix. **The first
    recognized token in a row wins** (the ``break``): a row naming two roster
    tokens is credited to the leftmost, which is what makes this a census of
    rows this row would be ASKED about rather than of mentions, and what
    separates MIPPA@0938's 29 from a mention count of 37.

    The token universe is the roster's, not just the source investigation's:
    OBRA is a row this script mints and ``initialisms.csv`` has never carried,
    and a census that read only the source file would silently answer 0 for
    every such row rather than counting it.
    """

    if artifact is None:
        return {}
    import pyarrow.parquet as pq

    table = pq.read_table(
        artifact / "unified_agenda_legal_authorities.parquet",
        columns=["rin", "authority_text", "authority_type", "parse_status"],
    )
    caps = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9&-]{1,7}(?![A-Za-z0-9])")
    tokens = {row["token"].upper() for row in csv.DictReader(SOURCE.open(encoding="utf-8"))}
    tokens |= {token for token, _ in _ROWS_OBSERVED}
    counts: dict[tuple[str, str], int] = {}
    for row in table.to_pylist():
        if row["authority_type"] != "other" or row["parse_status"] != "failed":
            continue
        for found in caps.findall(str(row["authority_text"] or "")):
            if found.upper() in tokens:
                counts[(found.upper(), row["rin"][:4])] = counts.get((found.upper(), row["rin"][:4]), 0) + 1
                break
    return counts


def report_drift(artifact: Path) -> None:
    """Print the pinned census against a live one. Writes nothing.

    Drift is expected and is not an error: every row this roster retiers is a
    row the builder can now read, which is exactly the population
    :func:`observed` counts. What the report is for is that the drift be SEEN
    and explainable, rather than a column quietly rewritten by whichever
    artifact was on disk.
    """

    live = observed(artifact)
    keys = sorted(set(_ROWS_OBSERVED) | set(live))
    moved = [(key, _ROWS_OBSERVED.get(key, 0), live.get(key, 0)) for key in keys]
    moved = [row for row in moved if row[1] != row[2]]
    print(f"rows_observed: {len(_ROWS_OBSERVED)} pinned, {len(moved)} differ against {artifact}")
    for (token, agency), pinned, now in moved:
        print(f"  {token}@{agency}: pinned {pinned} -> {now}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remeasure",
        type=Path,
        default=None,
        help="a built unified-agenda-parquet directory: print the rows_observed drift, write nothing",
    )
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "roster.csv")
    args = parser.parse_args()

    if args.remeasure is not None:
        report_drift(args.remeasure)
        return 0

    index = ActIndex.from_artifact(ACT_INDEX)
    counts = _ROWS_OBSERVED
    source_rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    out: list[dict[str, object]] = []
    unresolved: list[str] = []
    #: The census is per (token, agency); a token keyed by year has several rows
    #: at one such pair, and writing the count on each would report the same
    #: rows five times. It goes on the first row of the pair and nowhere else.
    counted: set[tuple[str, str]] = set()

    def emit(token, agency, year, status, name, quote, path, sha, note, table3=""):
        resolved = ""
        if name:
            normalized = normalize_popular_name(name)
            found = resolve_act_name(normalized, index)
            if found is None and status in {"pinned-quote", "reverse-pl-verified", "self-glossing",
                                            "candidate-index-match"}:
                # A resolving tier whose name the index does not list is not an
                # error -- SMART is real and unlisted -- but it MUST be visible.
                note = (note + "; " if note else "") + "not listed in the pinned act index"
                unresolved.append(f"{token}@{agency}: {normalized!r}")
            resolved = found or normalized
            table3 = index.table3_key_by_name.get(found, "") if found else table3
        rows_observed = ""
        if counts and (token.upper(), agency) not in counted:
            counted.add((token.upper(), agency))
            rows_observed = counts.get((token.upper(), agency), 0)
        out.append({
            "token": token, "agency_prefix": agency, "year_key": year, "status": status,
            "act_name": resolved, "table3_key": table3, "evidence_path": path,
            "evidence_sha256": f"sha256:{sha}" if sha else "",
            "evidence_quote": quote, "rows_observed": rows_observed,
            "notes": note,
        })

    for row in source_rows:
        token = row["token"]
        agencies = [a for a in row["agency_prefix_or_any"].split(",") if a]
        quote = row["evidence_quote"]
        note = row["notes"]
        if token == "NDAA":
            for agency in agencies:
                for year, (name, key) in NDAA_YEARS.items():
                    emit(token, agency, year, "candidate-index-match", name, quote,
                         ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE),
                         "the fiscal year names the act; a row stating none stays refused", key)
                emit(token, agency, "", "ambiguous", "", quote, "", "",
                     "bare 'NDAA' names no act: every fiscal year is a different one")
            continue
        if token == "FOIA":
            for agency in agencies:
                for year, name in FOIA_YEARS.items():
                    emit(token, agency, year, "candidate-index-match", name, quote,
                         ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE),
                         "which amending act depends on the year the row states")
                emit(token, agency, "", "ambiguous", "", quote, "", "",
                     "the 1966 act itself is not a listed name")
            continue
        if token in AGENCY_KEYED:
            for agency in agencies:
                status, name, note = AGENCY_KEYED[token][agency]
                path, sha = ("", "")
                if status in {"candidate-index-match", "self-glossing"}:
                    path, sha = ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE)
                row_quote = quote
                pinned = _PIECE_A_PINNED_QUOTES.get((token, agency))
                if pinned is not None:
                    status = "pinned-quote"
                    path, sha, row_quote = pinned
                    note = (
                        f"{note} -- retiered 2026-08-31 (inv-62 Piece A): a live FR document "
                        "binds the token at this agency"
                    )
                emit(token, agency, "", status, name, row_quote, path, sha, note)
            continue
        status = tier(row)
        name = NAME_FIXES.get(token, row["expansion"]) if status not in {
            "ambiguous", "belief-only"} and not status.startswith("not-an-act") else ""
        if status == "pinned-quote":
            path, sha = QUOTE_RECEIPTS[token]
        elif status in {"reverse-pl-verified", "self-glossing", "candidate-index-match"}:
            path, sha = ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE)
        else:
            path, sha = "", ""
        for agency in agencies:
            row_status, row_path, row_sha, row_quote, row_note = status, path, sha, quote, note
            pinned = _PIECE_A_PINNED_QUOTES.get((token, agency))
            if pinned is not None:
                row_status = "pinned-quote"
                row_path, row_sha, row_quote = pinned
                row_note = (
                    f"{note} -- retiered 2026-08-31 (inv-62 Piece A): a live FR document binds "
                    "the token at this agency" if note else
                    "retiered 2026-08-31 (inv-62 Piece A): a live FR document binds the token "
                    "at this agency"
                )
            emit(token, agency, "", row_status, name, row_quote, row_path, row_sha, row_note)

    # OBRA is year-ambiguous like NDAA and FOIA (1986/1987/1989/1990/1993 are
    # five different acts), but carries no bare-token source row at all --
    # nothing in this corpus glosses OBRA plus a full name. Only 1993 has a
    # citation this wave can act on ("Sec 13622 of OBRA '93", CMS/0938, #62
    # Piece B), so it is the only year this roster keys; a row stating a
    # different year, or none, stays refused exactly as bare NDAA does.
    emit(
        "OBRA", "0938", "1993", "candidate-index-match",
        "omnibus budget reconciliation act of 1993", "",
        ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE),
        "the year names the act; a row stating none, or a different year, stays refused -- OBRA "
        "is otherwise year-ambiguous (1986/1987/1989/1990/1993) and carries no bare row; "
        "rows_observed=2 is the two 'Sec 13622 of OBRA '93' rows (rin 0938-AM24, editions "
        "200210/200304), which read other/failed on the artifact this census was measured on and "
        "read act_relative once the apostrophe-year shape landed -- the column's own "
        "self-invalidation, spelled out in this script's docstring",
    )

    out.sort(key=lambda r: (r["token"].upper(), r["agency_prefix"], r["year_key"]))
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    print(f"{len(out)} roster rows -> {args.out}")
    if unresolved:
        print("names a resolving tier carries that the index does not list:")
        for line in unresolved:
            print(f"  {line}")
    return 0


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


if __name__ == "__main__":
    raise SystemExit(main())

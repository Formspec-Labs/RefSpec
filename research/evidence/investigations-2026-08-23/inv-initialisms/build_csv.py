"""Assemble initialisms.csv from everything gathered this session.

Merges: pop_b_per_token.json (row counts, roster/abstract signal),
act_index_query_results.json (direct-index literal-token check),
token_row_samples.json (rin prefixes, verbatim text), reverse_pl_lookup_verified.json
(auto-verified PL-number reverse lookups), and a hand-curated FINDINGS dict encoding
everything established this session (act-index full-name resolutions, fetched
publisher evidence with quotes, and not-an-act typings).
"""
import csv
import json
import sys
from pathlib import Path

EVID = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-initialisms")
RAW = EVID / "raw"

sys.path.insert(0, "/Users/mikewolfd/Work/RefSpec/src")
from refspec.registry.act_resolution import ActIndex, resolve_act_name  # noqa: E402

_ACT_INDEX = ActIndex.from_artifact("/Users/mikewolfd/Work/RefSpec/output/usc-act-index-2026-08-22")


def _lookup_table3_key(name):
    if not name:
        return None
    resolved = resolve_act_name(name, _ACT_INDEX)
    return _ACT_INDEX.table3_key_by_name.get(resolved) if resolved else None

pop_b = json.loads((Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-acts/pop_b_per_token.json")).read_text())["per_token"]
idx = json.loads((EVID / "act_index_query_results.json").read_text())
samp = json.loads((EVID / "token_row_samples.json").read_text())
sha = {}
for line in (EVID / "SHA256SUMS.txt").read_text().splitlines():
    digest, name = line.split("  ", 1)
    sha[name] = digest

def S(name):
    return "sha256:" + sha[name]

FR_API = "https://www.federalregister.gov/api/v1/documents.json"
OLRC_POPNAMES = "https://uscode.house.gov/popularnames/popularnames.htm"
OLRC_42_201 = "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section201&num=0&edition=prelim"
FETCHED_AUG23 = "2026-08-23"

# token -> dict of overrides. Anything not set falls back to sensible defaults.
FINDINGS = {
    # ---------------- TIER 1: fetched publisher evidence, exact quote -----
    "PHS": dict(expansion="Public Health Service Act", act_key="1944:373",
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/2024/12/09/2024-28748/notice-of-availability-of-draft-health-center-program-scope-policy-manual-guidance",
        evidence_sha256=S("fr_PHS_search.json"), fetched_at=FETCHED_AUG23,
        evidence_quote="HRSA requests public comments on the Draft Health Center Program Scope of Project Manual ... under the Public Health Service Act (PHS Act).",
        status="pinned"),
    "BBRA": dict(expansion="Medicare, Medicaid, and SCHIP Balanced Budget Refinement Act of 1999", act_key="106-113",
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/2000/04/10/00-8708/medicare-program-sustainable-growth-rate-for-the-year-2000",
        evidence_sha256=S("fr_BBRA_2000.json"), fetched_at=FETCHED_AUG23,
        evidence_quote="This final notice implements section 211(a)(2)(C) of ... the Medicare, Medicaid, and State Childrens Health Insurance Program Balanced Budget Refinement Act of 1999 (BBRA), that requires us to publish a notice...",
        status="pinned"),
    "IIJA": dict(expansion="Infrastructure Investment and Jobs Act", act_key="117-58",
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/2025/05/23/2025-09248/agency-information-collection-activities-requests-for-comments-clearance-of-a-renewed-approval-of",
        evidence_sha256=S("fr_IIJA_phrase.json"), fetched_at=FETCHED_AUG23,
        evidence_quote="...soliciting project information for the Infrastructure Investment and Jobs Act (IIJA) Airport Terminal, Tower and Airport Inf[rastructure]...",
        status="pinned"),
    "TEA-21": dict(expansion="Transportation Equity Act for the 21st Century", act_key="105-178",
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/1998/07/28/98-20119/tea-21-listening-sessions-and-one-dot-conferences",
        evidence_sha256=S("fr_TEA21_1998.json"), fetched_at=FETCHED_AUG23,
        evidence_quote="The Transportation Equity Act for the 21st Century (TEA-21) was signed into law on June 9, 1998.",
        status="pinned"),
    "HSIA": dict(expansion="Hydrographic Services Improvement Act of 1998, as amended", act_key="105-384",
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/2024/08/26/2024-15790/hydrographic-services-review-panel-meeting-september-24th-26th-2024",
        evidence_sha256=S("fr_HSIA_2024-15790.xml"), fetched_at=FETCHED_AUG23,
        evidence_quote="The Hydrographic Services Improvement Act of 1998, as amended (HSIA; 33 U.S.C. 892 et seq.), established the HSRP as a Federal Advisory Committee...",
        status="pinned"),
    "SMART": dict(expansion="Strengthening Medicare and Repaying Taxpayers Act of 2012", act_key=None,
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/2015/02/27/2015-04143/medicare-program-right-of-appeal-for-medicare-secondary-payer-determinations-relating-to-liability",
        evidence_sha256=S("fr_SMART_named.json"), fetched_at=FETCHED_AUG23,
        evidence_quote="This final rule implements provisions of the Strengthening Medicare and Repaying Taxpayers Act of 2012 (SMART Act) which require us to provide a right of appeal...",
        status="pinned", notes="Not found in the pinned act index under this or the alternate 'Medicare IVIG and Strengthening...' wording -- pinned by FR document alone."),
    "FD&C": dict(expansion="Federal Food, Drug, and Cosmetic Act", act_key="1938:675",
        evidence_kind="federal-register-document",
        evidence_url="https://www.federalregister.gov/documents/2026/04/23/2026-07910/harmful-and-potentially-harmful-constituents-in-tobacco-products-and-tobacco-smoke-establishing",
        evidence_sha256=S("fr_FDC_quote.json"), fetched_at=FETCHED_AUG23,
        evidence_quote="...as required by the Federal Food, Drug, and Cosmetic Act (the FD&C Act).",
        status="pinned"),
    "LU": dict(expansion="Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users (SAFETEA-LU)", act_key="109-59",
        evidence_kind="olrc-popular-names-table", evidence_url=OLRC_POPNAMES,
        evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="<p class='popular-name-information' content-type='also-known-as'>Also known as SAFETEA-LU</p> [under 'Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users', Pub. L. 109-59]",
        status="pinned"),
    "SAFTEA": dict(expansion="Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users (SAFETEA-LU)", act_key="109-59",
        evidence_kind="olrc-popular-names-table", evidence_url=OLRC_POPNAMES,
        evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="<p class='popular-name-information' content-type='also-known-as'>Also known as SAFETEA-LU</p> [under 'Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users', Pub. L. 109-59]",
        status="pinned"),

    # ------------- TIER 2: reverse-PL, exact-initials/anchored verified ----
    "FDASIA": dict(expansion="Food and Drug Administration Safety and Innovation Act", act_key="112-144",
        evidence_kind="act-index+corpus-pl-number", evidence_url=None, evidence_sha256=None, fetched_at="n/a",
        evidence_quote="corpus text 'secs 506C, ... of the FDA&C Act, as amended by title X (Drug Shortages) of FDASIA, PL 112-144, July 9, 2012' -- PL 112-144 resolves in the pinned index to exactly one act whose initials (F-D-A-S-I-A) match the token.",
        status="pinned"),
    "HIPAA": dict(expansion="Health Insurance Portability and Accountability Act of 1996", act_key="104-191",
        evidence_kind="act-index+corpus-pl-number", evidence_url=None, evidence_sha256=None, fetched_at="n/a",
        evidence_quote="corpus text 'HIPAA, PL 104-191' -- PL 104-191 resolves in the pinned index to exactly one act, exact-initials match.",
        status="pinned"),
    "PRWORA": dict(expansion="Personal Responsibility and Work Opportunity Reconciliation Act of 1996", act_key="104-193",
        evidence_kind="act-index+corpus-pl-number", evidence_url=None, evidence_sha256=None, fetched_at="n/a",
        evidence_quote="corpus text '8 U.S.C. 1601 et seq., Pub. L. 104-193, Personal Responsibility and Work Opportunity Reconciliation Act of 1996 (PRWORA)' -- self-glossing AND PL-verified.",
        status="pinned"),

    # ------------- TIER 3: act-index resolves the full name; no live quote -
    "ARRA": dict(expansion="American Recovery and Reinvestment Act of 2009", act_key="111-5",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text is bare 'ARRA 2009' / 'ARRA as amended by PL 112-10 and PL 112-74'; the pinned act index (sourced from this OLRC page) resolves 'American Recovery and Reinvestment Act of 2009' cleanly to table3_key 111-5, and no other 2009 act with initials ARRA competes. No live FR quote binding the bare token found within budget.",
        status="pinned"),
    "OSH": dict(expansion="Occupational Safety and Health Act of 1970", act_key="91-596",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'Section 6(b)(1) and 7(b) of the OSH Act'; act index resolves 'Occupational Safety and Health Act of 1970' to 91-596 (rin prefix 1218 = OSHA). FR full-text search for '(OSH Act)' returns 1,388 documents but none surfaced the gloss inside an abstract snippet within budget.",
        status="pinned"),
    "FAIR": dict(expansion="Federal Agriculture Improvement and Reform Act of 1996", act_key="104-127",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'FAIR Act of 1996, section 191, section 226 A(b)' (rin 0563); act index resolves 'Federal Agriculture Improvement and Reform Act of 1996' -- the 1996 'Freedom to Farm Act' -- to 104-127, year matches exactly.",
        status="pinned"),
    "MMSEA": dict(expansion="Medicare, Medicaid, and SCHIP Extension Act of 2007", act_key="110-173",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text is bare 'MMSEA' (rin 0938=CMS); act index resolves 'Medicare, Medicaid, and SCHIP Extension Act of 2007' (Section 111 MSP reporting) to 110-173, exact-initials match.",
        status="pinned"),
    "USHA": dict(expansion="United States Housing Act of 1937", act_key="1937:896",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'USHA of 1937' / 'Section 3(a)(2)(B) of the USHA of 1937' (rin 2577=HUD) is self-glossing with the year; act index confirms 'United States Housing Act of 1937' at 1937:896.",
        status="pinned"),
    "ATRA": dict(expansion="American Taxpayer Relief Act of 2012", act_key="112-240",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'ATRA sec 632(a)' (rin 0938=CMS); act index resolves 'American Taxpayer Relief Act of 2012' ('fiscal cliff' act) to 112-240, exact-initials match.",
        status="pinned"),
    "ANILCA": dict(expansion="Alaska National Interest Lands Conservation Act", act_key="96-487",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'ANILCA sec 203' / 'ANILCA sec 1313' (rin 1024=NPS/Interior); act index resolves 'Alaska National Interest Lands Conservation Act' to 96-487, exact-initials match.",
        status="pinned"),
    "FAA": dict(expansion="FAA Reauthorization Act of 2018", act_key="115-254",
        evidence_kind="act-index+corpus-pl-number", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'sec. 403 of the 2018 FAA Reauthorization Act' self-glosses the act's own popular name, which the act index carries verbatim at table3_key 115-254 (rin 2105=DOT/OST).",
        status="pinned", notes="Token 'FAA' also names the agency (Federal Aviation Administration) generally -- here it functions as a shortened form of the act's own title, not a bare agency reference."),
    "MMPA": dict(expansion="Marine Mammal Protection Act of 1972", act_key="92-522",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'MMPA 101(a)(5)(A)' / 'MMPA, 16 U.S.C. 1361 et seq.' (rin 0648=NOAA Fisheries); act index confirms 'Marine Mammal Protection Act of 1972' at 92-522, and 16 U.S.C. 1361 is that act's own codification start.",
        status="pinned"),
    "IEEPA": dict(expansion="International Emergency Economic Powers Act", act_key="95-223",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text '50 USC 1705 (IEEPA)' self-glosses via the parenthetical and cites 1705, inside IEEPA's own codification (50 U.S.C. ch. 35); act index confirms 'International Emergency Economic Powers Act' at 95-223.",
        status="pinned"),
    "REAL": dict(expansion="REAL ID Act of 2005", act_key="109-13",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'Division B--REAL ID Act of 2005' is self-glossing; act index confirms 'REAL ID Act of 2005' at 109-13 (Division B of Pub. L. 109-13, the FY2005 Emergency Supplemental Appropriations Act).",
        status="pinned"),
    "ESSA": dict(expansion="Every Student Succeeds Act", act_key="114-95",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'Every Student Succeeds Act (ESSA) of 2015' is self-glossing; act index carries the name as 'Every Student Succeeds Act' (no trailing year) at 114-95 -- the corpus's own 'of 2015' suffix is not how OLRC stores the name.",
        status="pinned"),
    "NPHA": dict(expansion="Northern Pacific Halibut Act of 1982", act_key="97-176",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'North Pacific Halibut Act of 1982 (NPHA)' is self-glossing; act index carries it as 'Northern Pacific Halibut Act of 1982' at 97-176 -- note the spelling difference ('Northern' vs the corpus's 'North').",
        status="pinned"),
    "FOIA": dict(expansion="Freedom of Information Act (the corpus's own rows split across the 'Electronic Freedom of Information Act Amendments of 1996' and the 'FOIA Improvement Act of 2016')", act_key="104-231 or 114-185 (year-dependent)",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text '5 USC 552 Electronic FOIA Amendments of 1996' resolves to 104-231; corpus text 'The FOIA Improvement Act of 2016 (Pub. L. 114-185)' resolves to 114-185 (also reverse-PL-verified). The bare base 'Freedom of Information Act' (1966) itself does not resolve in the pinned index.",
        status="pinned", notes="Year-qualified like NDAA: which FOIA-amending act is meant depends on which amendment year the record cites."),
    "MSCFMA": dict(expansion="Magnuson-Stevens Fishery Conservation and Management Act", act_key="94-265",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text is bare 'MSCFMA' (rin 0648=NOAA Fisheries, exactly the agency that administers this act). The act index confirms 'Magnuson-Stevens Fishery Conservation and Management Act' at 94-265, but the standard public abbreviation is MSFCMA/MSA -- 'MSCFMA' transposes two letters. No document was found using 'MSCFMA' literally, so the letter-for-letter identity is contextual, not quoted.",
        status="belief-only"),
    "WSARA": dict(expansion="Weapon Systems Acquisition Reform Act of 2009", act_key="111-23",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus abstract self-glosses '(WSARA)' next to 'Weapon System Reform Act of 2009' / 'Weapons System Acquisition Reform Act of 2009' -- neither exact wording is in the index. OLRC's own spelling is 'Weapon Systems Acquisition Reform Act of 2009' (Systems plural, Weapon singular), which resolves cleanly to 111-23. The earlier pop_b measurement's 'abstract_name_in_act_index: []' was a pure wording mismatch, not a real absence.",
        status="pinned"),
    "MMEA": dict(expansion="Medicare and Medicaid Extenders Act of 2010", act_key="111-309",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'MIPPA sec 153(c), MMEA' / 'MMEA, Sec 102' (rin 0938=CMS); act index confirms 'Medicare and Medicaid Extenders Act of 2010' at 111-309, exact-initials match, and it amends MIPPA sec. 153 in reality.",
        status="pinned"),
    "PPACA": dict(expansion="Patient Protection and Affordable Care Act", act_key="111-148",
        evidence_kind="act-index+corpus-pl-number", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'BBA, BA, BIPA, MMA, PL 111.148' names PL 111-148 (period-formatted) alongside 'PPACA' in the parallel row 'BBA, BA, BIPA, MMA, PPACA'; act index resolves 111-148 to 'Patient Protection and Affordable Care Act', exact-initials match (P-P-A-C-A).",
        status="pinned"),
    "PPAC": dict(expansion="Patient Protection and Affordable Care Act", act_key="111-148",
        evidence_kind="act-index+corpus-pl-number", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'IHCI Act as amended by PL 111-148, sec 10221 PPAC Act' names PL 111-148 directly beside 'PPAC Act'; index confirms 111-148 = Patient Protection and Affordable Care Act. 'PPAC' itself is missing the trailing 'A' of the standard PPACA initialism (the word 'Act' is written out separately after it).",
        status="pinned"),
    "SS": dict(expansion="Social Security Act", act_key="1935:531",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'sec 371 to 375, PHS Act, sec 1138, SS Act' -- 'SS Act' sits beside 'PHS Act' in the identical unglossed style ('sec 1138' is a real Social Security Act section); act index confirms 'Social Security Act' at 1935:531. No document found using 'SS Act' as a distinct citation form (SSA is the standard 3-letter form), so this is contextual, not quoted.",
        status="belief-only"),
    "EPA": dict(expansion="ambiguous: Environmental Protection Agency (rin 2030, self-referential 'EPA Acquisition Regulation') vs. Energy Policy Act of 1992 (rin 0596=Forest Service, 'EPA 1992')",
        act_key="102-486 (Energy Policy Act sense only)",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'EPA Acquisition Regulation sec 205' (rin 2030) is unambiguously the AGENCY (EPAAR, 48 CFR ch. 15, is the Environmental Protection Agency's own procurement regulation). corpus text 'EPA 1992' (rin 0596=Forest Service) most plausibly means the Energy Policy Act of 1992 -- the act index confirms that name resolves cleanly to 102-486 -- but no FR document glossing 'EPA 1992' as the Energy Policy Act was found within budget (an FR search restricted to Forest Service returned only 2 unrelated documents).",
        status="ambiguous"),
    "NDAA": dict(expansion="National Defense Authorization Act for Fiscal Year {YYYY} (year-qualified; the record must state or imply the fiscal year)",
        act_key="varies by year: e.g. 110-417 (FY2009), 112-239 (FY2013), 116-283 (FY2021), 117-263 (FY2023)",
        evidence_kind="act-index+corpus-pl-number", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'NDAA 2021, sec. 702' (rin 0720-AB87); act index confirms 'National Defense Authorization Act for Fiscal Year 2021' resolves to 116-283 (which is also aliased from the officially-named 'William M. (Mac) Thornberry National Defense Authorization Act for Fiscal Year 2021'). Bare 'NDAA' with no year does not resolve -- 'National Defense Authorization Act' alone is not a listed name (it is enacted anew, with a new Congress-assigned name, every fiscal year).",
        status="ambiguous", notes="Not agency-ambiguous, but YEAR-ambiguous: (initialism, agency) is not enough; the roster key must be (initialism, fiscal year)."),

    # ------------- typed as NOT AN ACT --------------------------------
    "FSH": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:directive",
        evidence_quote="corpus text 'FSH 2709.11' / 'FSH 1509.13' / 'FSH 6709.11' (rin 0596=USDA Forest Service) -- Forest Service Handbook, an internal agency directive numbering system, not a statute."),
    "FS": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text 'FS Handbooks' (rin 0596=USDA Forest Service) -- 'FS' = the Forest Service itself."),
    "DHS": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text 'DHS Delegation Number 0700' / 'DHS Del. No. 13001, Rev. 01' (rin 1601, 1625) -- Department of Homeland Security, issuing its own delegation orders."),
    "NAFTA": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:treaty",
        evidence_quote="corpus text 'North American Free Trade Agreement (NAFTA)' (rin 1400=State, 1615=USCIS) -- a trade agreement/treaty, not a U.S. statute with an OLRC popular-name entry (confirmed absent from the pinned act index, as expected for a treaty)."),
    "DCR": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:reporter",
        evidence_quote="corpus text 'D.C. Law 18-88, sec. 56 DCR 7413' (rin 3225) -- District of Columbia Register, the District's official gazette/reporter (cited '56 DCR 7413' the way a U.S.C. or Federal Register citation would be)."),
    "BB": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:division-letter",
        evidence_quote="corpus text 'Pub. L. 116-260, Division BB, title I' -- Division BB is one of many lettered divisions of the Consolidated Appropriations Act, 2021 (Pub. L. 116-260), not itself a named act."),
    "FIPS": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:standard",
        evidence_quote="corpus text 'FIPS 201-2' (rin 0790) -- Federal Information Processing Standard 201-2 (Personal Identity Verification), a NIST technical standard, not a statute."),
    "HTS": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:standard",
        evidence_quote="corpus text 'ch 4 of the HTS' (rin 0551) -- Harmonized Tariff Schedule of the United States, a tariff classification standard, not a statute."),
    "HTSUS": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:standard",
        evidence_quote="corpus text '19 USC 1202 (General Note 3(i), Harmonized Tariff Schedule of the United States)' (rin 1505,1515,1651,1685=Treasury/CBP) -- same standard as HTS, written in full."),
    "NPI": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text 'NPI final rule (01/23/2004)' (rin 0938=CMS) -- National Provider Identifier, a CMS-assigned identifier scheme (established by an HIPAA rule), not itself an act."),
    "NPS": dict(expansion=None, evidence_kind="not-applicable", status="ambiguous",
        evidence_quote="corpus text 'NPS System of Records (07/28/1998)' (rin 0938=CMS) -- a named Privacy Act system-of-records, not an act. Elsewhere in federal usage 'NPS' commonly means the National Park Service (an agency); the corpus's own occurrences are all the CMS system-of-records sense."),
    "DOJ": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text 'DOJ Ord 1735.1' / 'DOJ Order 2710.8A' (rin 1103,1105) -- Department of Justice, issuing its own numbered Orders (directives)."),
    "FBI": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text \"...'Delegation of Responsibilities Concerning FBI...'\" (rin 1105=DOJ) -- Federal Bureau of Investigation."),
    "FEMA": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text 'FEMA Reg 5 issued under sec. 602' (rin 3067) -- Federal Emergency Management Agency, issuing its own numbered regulations."),
    "TD": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:directive",
        evidence_quote="corpus text 'TD 120-01 (formerly TD 221)' (rin 1512=TTB/Treasury) -- Treasury Decision, a numbered Treasury/Customs directive series, not a statute."),
    "IRPS": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:directive",
        evidence_quote="corpus text 'IRPS 87-2' (rin 3133=NCUA) -- NCUA Interpretive Ruling and Policy Statement, a numbered agency-guidance series, not a statute."),
    "VCDR": dict(expansion="Vienna Convention on Diplomatic Relations", evidence_kind="corpus-context", status="not-an-act:treaty",
        evidence_quote="corpus text is the bare token 'VCDR' with no gloss (rin 1400=Department of State, the treaty-depositary-adjacent agency). Confirmed absent from the pinned act index (as expected for a treaty, like NAFTA); the expansion itself is contextual, not quoted."),
    "USDC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:reporter",
        evidence_quote="corpus text 'Nehmer v. U.S. Department of Veterans Affairs, No. C86-06160 WHA, USDC' (rin 2900=VA) -- 'USDC' = United States District Court, part of a litigation case citation, not a statute."),
    "WHA": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text 'Nehmer v. U.S. Department of Veterans Affairs, No. C86-06160 WHA, USDC' (rin 2900=VA) -- 'WHA' are a federal judge's initials embedded in the docket number (N.D. Cal. convention), not an initialism of any act."),
    "FMC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text 'WSC v. FMC, No. 24-1088 (CADC Sept. 23, 2025)' (rin 3072=FMC itself) -- Federal Maritime Commission, named as a litigation party."),
    "CADC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:reporter",
        evidence_quote="corpus text 'WSC v. FMC, No. 24-1088 (CADC Sept. 23, 2025)' -- 'CADC' is the standard case-citation abbreviation for the U.S. Court of Appeals for the D.C. Circuit."),
    "WSC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text 'WSC v. FMC, No. 24-1088 (CADC Sept. 23, 2025)' -- 'WSC' names a litigation party (World Shipping Council), not an act."),
    "OL": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text 'OL 111-148, sec 3301, sec 6402' (rin 0991=ONC/HHS) -- almost certainly a garbled 'PL' (Public Law): 111-148 is the Affordable Care Act's real public law number."),
    "DEL": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '...DOE Delegation Order No. S1-DEL-FERC-2006 (M...' (rin 1901,1902=DOE) -- 'DEL' is a fragment of the delegation-order identifier 'S1-DEL-FERC-2006', split apart by the token scanner, not a standalone initialism."),
    "FERC-2006": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text 'DOE Delegation Order No. S1-DEL-FERC-2006' (rin 1902=DOE) -- the same delegation-order identifier as DEL; 'FERC-2006' is its tail fragment, not 'Federal Energy Regulatory Commission' plus a year."),
    "FY": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text 'sec 823 of the National Defense Authorization Act for Fiscal Year 2009' -- 'FY' is a two-letter fragment the token scanner lifted out of ordinary prose ('for Fiscal Year'), not an abbreviation the source text intends as an initialism in its own right."),
    "APUSC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '49 APUSC 1 to 85' (rin 1902) -- reads as a garbled '49 App. U.S.C. 1 to 85' (a pre-recodification Title 49 Appendix citation, common for historic Interstate Commerce Act material)."),
    "USE": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '16 USE 715(i)' (rin 1018) -- reads as a garbled '16 U.S.C. 715(i)' (a real Migratory Bird Conservation Act section); part of a family of USC-citation OCR/typo artifacts in this corpus (USE, USO, USD, USAC, USCC, USCU, YSC, SUC, UUSC all show the same Title# + garbled-USC + Section# shape)."),
    "USO": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '42 USO 299b-12 to 299b-26' (rin 0919) -- reads as a garbled '42 U.S.C. 299b-12' (Patient Safety and Quality Improvement Act codification); same USC-citation-artifact family as USE."),
    "USD": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '38 USD ch 43' (rin 0790=DoD) -- reads as a garbled '38 U.S.C. ch. 43' (USERRA's own title/chapter); same USC-citation-artifact family."),
    "USAC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '15 USAC 80b-78w(a)' / '15 USAC 77s(a)' (rin 3235=SEC) -- reads as garbled '15 U.S.C. 80b-...' and '15 U.S.C. 77s(a)' (Investment Advisers Act / Securities Act sections); same USC-citation-artifact family."),
    "USCC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '42 USCC 1382' (rin 0960=SSA) -- reads as a garbled '42 U.S.C. 1382' (the SSI benefits section); same USC-citation-artifact family."),
    "USCU": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '26 USCU.S.C. 5061 to 5064' (rin 1513=TTB) -- the literal string shows the corruption in progress ('USC' immediately followed by 'U.S.C.'); same USC-citation-artifact family."),
    "YSC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '40 YSC 1480' (rin 0572) -- reads as a garbled '40 U.S.C. 1480'; same USC-citation-artifact family."),
    "SUC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '49 SUC 45102 to 45103' (rin 2120=FAA) -- 49 U.S.C. 45102-45103 (airport noise/aviation programs) is a real citation; 'SUC' is the same USC-citation-artifact family even though it does not begin with 'US' like the others."),
    "UUSC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '5 UUSC 1305' (rin 3206=OPM) -- reads as a garbled '5 U.S.C. 1305' (Hatch Act-adjacent Title 5 provision); same USC-citation-artifact family."),
    "USCG": dict(expansion=None, evidence_kind="not-applicable", status="ambiguous",
        evidence_quote="corpus text '33 USCG 1231' (rin 1625=U.S. Coast Guard) -- reads as the same 'Title# + garbled-USC + Section#' shape as the rest of the USC-citation-artifact family (33 U.S.C. 1231, Ports and Waterways Safety Act), but the letters also coincide exactly with the issuing agency's own initials (U.S. Coast Guard), which is genuinely issuing this RIN -- the roster cannot tell the two readings apart from this text alone."),
    "EE": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:directive",
        evidence_quote="corpus text 'EE.O.M Directive 715' / 'EE.O.M 715' (rin 0790,1513) -- reads as 'EEO[.M]' = Equal Employment Opportunity [Management] Directive 715, a standard EEOC directive number, not a statute."),
    "CMHS": dict(expansion="Community Mental Health Services Block Grant", evidence_kind="corpus-context", status="not-an-act:identifier",
        evidence_quote="corpus text 'Sections 1911 through 1956 of the PHS Act Authorize the Community Ment[al Health Services Block Grant]...' (rin 0930=SAMHSA) -- CMHS names a grant PROGRAM authorized by title XIX-B of the Public Health Service Act, not a separate act with its own popular name."),
    "SAPT": dict(expansion="Substance Abuse Prevention and Treatment Block Grant", evidence_kind="corpus-context", status="not-an-act:identifier",
        evidence_quote="Same box as CMHS (rin 0930=SAMHSA), 'Sections 1911 through 1956 of the ... PHS Act' -- SAPT names the companion block-grant program (PHS Act title XIX-B, part B), not a separate act."),
    "SCHIP": dict(expansion="State Children's Health Insurance Program", evidence_kind="corpus-context", status="not-an-act:identifier",
        evidence_quote="corpus text 'Sec 522 of the Medicare, Medicaid, and SCHIP Benefits Improvement and Protection Act of 2000' (rin 0938=CMS) -- SCHIP names the PROGRAM (Social Security Act title XXI), which appears as a word inside several amending acts' own titles (BIPA, BBRA, MMSEA) rather than having its own OLRC popular-name entry."),
    "INS": dict(expansion="Immigration and Naturalization Service (agency) -- or a mistyping of INA (Immigration and Nationality Act)",
        evidence_kind="corpus-context", status="ambiguous",
        evidence_quote="corpus text 'INS secs. 208, 241, and 274A' (rin 1615=USCIS) -- sections 208 (asylum), 241 (removal), and 274A (unlawful employment) are all real Immigration and Nationality Act (INA) section numbers, so 'INS' here plausibly stands in for 'INA' rather than for the pre-2003 Immigration and Naturalization Service; the roster cannot decide this from the text alone."),

    # ------------- fix the 3 auto DIRECT_INDEX rows' presentation --------
    "BIPA": dict(expansion="Medicare, Medicaid, and SCHIP Benefits Improvement and Protection Act of 2000", act_key="106-554",
        evidence_kind="act-index-direct", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="resolve_act_name('BIPA', index) succeeds directly off the bare token: ALIAS_YEAR_RULE supplies 'of 2000' because exactly one listed act's stem completes it, so the literal 3-letter token resolves with no external fetch needed at all.",
        status="pinned"),
    "MAP-21": dict(expansion="Moving Ahead for Progress in the 21st Century Act (MAP-21)", act_key="112-141",
        evidence_kind="act-index-direct", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="the pinned popular-names table lists 'MAP-21' as a literal, separate name row (content_type='cite', table3_key=112-141) as well as an 'also-known-as' cross-reference from 'Moving Ahead for Progress in the 21st Century Act' -- the bare token resolves with no external fetch needed.",
        status="pinned"),
    "USA": dict(
        expansion="ambiguous: the pinned index's ONLY literal '(USA)' parenthetical is 'Uninterrupted Scholars Act (USA)' (112-278), which is almost certainly NOT what this corpus intends -- the broader corpus scan finds 'USA' used both as part of 'USA PATRIOT Act' (rin 1506) and as a likely USC-citation artifact '49 USA app 1 to 85' (rin 1902, same 'Title# + garbled-USC' family as USE/USO/USD/etc.)",
        act_key="112-278 (Uninterrupted Scholars Act, likely a false match) / none (USC-citation-artifact reading) / see 107-56 for USA PATRIOT Act",
        evidence_kind="act-index-direct", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="popularnames.htm's only exact '(USA)' match is under 'Uninterrupted Scholars Act', an education/FERPA-adjacent 2013 act (Pub. L. 112-278) with no obvious fit to this corpus's agency mix; the token-level 'direct index hit' this session's automated scan reported is very likely a coincidental match, not the sense the row intends.",
        status="ambiguous"),

    # ------------- final 6 stragglers -----------------------------------
    "SAFE": dict(
        expansion="ambiguous: Security and Accountability for Every Port Act of 2006 (rin 1515=CBP/ICE) vs. Secure and Fair Enforcement for Mortgage Licensing Act of 2008 (rin 3133=NCUA)",
        act_key="109-347 or 110-289 (agency-dependent)",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'Security and Accountability for Every (SAFE) Port Act of 2006' (rin 1515) is self-glossing and resolves to 109-347. corpus text 'SAFE Mortgage Licensing Act' (rin 3133=NCUA) is close to, but not exactly, OLRC's own wording 'Secure and Fair Enforcement for Mortgage Licensing Act of 2008' (110-289). OLRC's popularnames.htm additionally carries a THIRD, unrelated 'SAFE' (the organized-retail-crime 'Strengthening and Focusing Enforcement...Act'), confirming this initialism is genuinely multi-way ambiguous and must be agency-scoped.",
        status="ambiguous"),
    "DOE": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:agency",
        evidence_quote="corpus text 'DOE Delegation Order No. 0204-111' / '...E.O. 12038...' (rin 1901,1902) -- Department of Energy, issuing its own delegation orders."),
    "UDC": dict(expansion=None, evidence_kind="not-applicable", status="not-an-act:identifier",
        evidence_quote="corpus text '12 UDC 1735(f)-14' (rin 2502=HUD) -- reads as a garbled '12 U.S.C. 1735f-14' (a real National Housing Act section); same USC-citation-artifact family as USE/USO/USD/etc."),
    "USPHSA": dict(expansion="Public Health Service Act", act_key="1944:373",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'USPHSA, sec 353' (rin 0938=CMS) -- 'USPHSA' spells out 'U.S. Public Health Service Act', same act as PHS/PHSA/PHA, index-confirmed at 1944:373 under the shorter 'Public Health Service Act'.",
        status="pinned"),
    "FAST": dict(expansion="FAST Act (Fixing America's Surface Transportation Act)", act_key="114-94",
        evidence_kind="act-index+corpus-pl-number", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'Section 5516 of the FAST Act (Pub. L. 114-94)' is self-glossing with the exact PL number; the act index carries 'FAST Act' itself as a listed name (not just 'Fixing America's Surface Transportation Act'), both at table3_key 114-94.",
        status="pinned"),
    "AML": dict(expansion="Anti-Money Laundering Act of 2020", act_key="116-283",
        evidence_kind="act-index", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="corpus text 'sec. 6103 of the AML Act' (rin 1506=FinCEN/Treasury); act index confirms 'Anti-Money Laundering Act of 2020' at table3_key 116-283 (enacted as Division F of the FY2021 NDAA, hence sharing that key with NDAA-FY2021).",
        status="pinned"),

    # ------------- belief-only / unresolved ----------------------------
    "PPRA": dict(expansion=None, evidence_kind="none", status="belief-only",
        evidence_quote="corpus text is the bare token 'PPRA' with zero surrounding context (rin 0938=CMS, RULE_TITLE 'Changes to the Hospital Outpatient Prospective Payment System... for CY 2009'). The only 'PPRA' the pinned act index resolves is the 'Protection of Pupil Rights Amendment' (90-247, an education/FERPA-family statute) -- an implausible match for a CMS hospital-payment rule. Multiple FR API searches (agency-restricted and broad) found no CMS document glossing a distinct 'PPRA'. Left unresolved."),
    "TPTCC": dict(expansion=None, evidence_kind="none", status="belief-only",
        evidence_quote="corpus text 'TPTCC, sec 302' (rin 0938=CMS) -- no hypothesis found; not in the pinned index under any name tried, and too obscure (1 row) to spend further fetch budget on."),
    "FSA": dict(expansion=None, evidence_kind="none", status="belief-only",
        evidence_quote="corpus text 'Sec. 303 of the FSA' (rin 0938=CMS) -- ambiguous between several real 'FSA' expansions (Family Support Act of 1988, Flexible Spending Arrangement, historic Federal Security Agency); none confirmed. Left unresolved (2 rows, no fetch spent)."),
    "UCMJ": dict(expansion="Uniform Code of Military Justice", evidence_kind="corpus-context", status="belief-only",
        evidence_quote="corpus text 'Articles 123a, 133, and 134, Uniform Code of Military Justice (UCMJ)' (rin 0702) is fully self-glossing and UCMJ is a real, universally-known statute (10 U.S.C. ch. 47) -- but it does not resolve in the pinned act index under any wording tried ('Uniform Code of Military Justice', '..., 1950', 'Act of May 5, 1950'), so it cannot be called index-pinned; kept belief-only on the evidence bar this roster uses even though the fact itself is not in doubt."),
}

# Ambiguity: MMA gets a note appended even though it is otherwise 'settled'
# via the existing roster (handled in the settled block below).

def default_for_settled(token, pb):
    """Tokens pop_b already showed resolving via roster/abstract -- report
    that pre-existing resolution rather than re-deriving it."""
    survivors = pb["in_roster_example_survivors"] or []
    abstract_hit = pb["abstract_name_in_act_index"]
    expansion = (abstract_hit[0] if abstract_hit else (survivors[0] if survivors else None))
    quote_bits = []
    if abstract_hit:
        quote_bits.append(f"abstract states an act name the pinned index carries verbatim: {abstract_hit[0]!r}")
    if survivors:
        quote_bits.append(f"roster resolves {pb['roster_resolvable_rows']}/{pb['row_count']} rows to: {', '.join(survivors)}")
    return dict(
        expansion=expansion, act_key=None,
        evidence_kind="act-index+existing-roster",
        evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"), fetched_at=FETCHED_AUG23,
        evidence_quote="; ".join(quote_bits),
        status="pinned",
    )

ALREADY_SETTLED = {t for t in pop_b if pop_b[t]["roster_resolvable_rows"] > 0 or pop_b[t]["abstract_name_in_act_index"]}
# BIPA and MAP-21 and USA resolve directly off the bare token via the index.
DIRECT_INDEX = {t for t in idx if idx[t]["any_index_hit"]}

MMA_NOTE = ("ambiguous nationally: at CMS/IHS (rin 0917, 0938) 'MMA' consistently means the "
            "Medicare Prescription Drug, Improvement, and Modernization Act of 2003 in this corpus "
            "(roster-resolved for 8/14 rows), but the same three letters commonly name other acts "
            "elsewhere (e.g. the Magnuson-Moss Warranty Act) -- the roster key should be (MMA, agency).")

rows = []
for token in sorted(pop_b.keys()):
    pb = pop_b[token]
    row_count = pb["row_count"]
    prefixes = ",".join(samp[token]["rin_prefixes"]) or "any"

    if token in FINDINGS:
        f = FINDINGS[token]
    elif token in DIRECT_INDEX:
        ix = idx[token]
        f = dict(
            expansion=ix["resolved_act_key"] or (ix["distinct_table3_keys_from_direct_hits"][0] if ix["distinct_table3_keys_from_direct_hits"] else None),
            act_key=ix["resolved_table3_key"] or (ix["distinct_table3_keys_from_direct_hits"][0] if ix["distinct_table3_keys_from_direct_hits"] else None),
            evidence_kind="act-index-direct", evidence_url=OLRC_POPNAMES, evidence_sha256=S("popularnames.htm"),
            fetched_at=FETCHED_AUG23,
            evidence_quote=f"bare token resolves directly off the pinned index (paren_hits={len(ix['paren_hits'])}, name_row_hits={len(ix['name_row_hits'])}, resolve_act_name={'hit' if ix['resolved_act_key'] else 'miss'})",
            status="pinned" if not ix["ambiguous"] else "ambiguous",
        )
    elif token in ALREADY_SETTLED:
        f = default_for_settled(token, pb)
    else:
        raise SystemExit(f"no findings for token {token!r} -- add it to FINDINGS")

    expansion = f.get("expansion")
    act_key = f.get("act_key")
    if act_key is None and expansion and f["status"] == "pinned":
        act_key = _lookup_table3_key(expansion)
    if token == "MMA" and "notes" not in f:
        f = {**f, "notes": MMA_NOTE}

    rows.append({
        "token": token,
        "rows": row_count,
        "agency_prefix_or_any": prefixes,
        "expansion": expansion or "",
        "act_key_in_index": act_key or "none",
        "evidence_kind": f["evidence_kind"],
        "evidence_url": f.get("evidence_url") or "",
        "evidence_sha256": f.get("evidence_sha256") or "",
        "evidence_quote": f.get("evidence_quote") or "",
        "fetched_at": f.get("fetched_at") or "",
        "status": f["status"],
        "notes": f.get("notes", ""),
    })

assert len(rows) == 118, len(rows)

out_path = EVID / "initialisms.csv"
with out_path.open("w", newline="", encoding="utf-8") as fh:
    fieldnames = ["token", "agency_prefix_or_any", "expansion", "act_key_in_index",
                  "evidence_kind", "evidence_url", "evidence_sha256", "evidence_quote",
                  "fetched_at", "status", "rows", "notes"]
    w = csv.DictWriter(fh, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)

# ---- final counts for the report ----
from collections import Counter
status_counts = Counter(r["status"] for r in rows)
nonact_types = Counter(r["status"].split(":", 1)[1] for r in rows if r["status"].startswith("not-an-act"))
print("wrote", out_path, "rows:", len(rows))
print("status counts:", dict(status_counts))
print("not-an-act subtypes:", dict(nonact_types))

# rows-weighted counts (sum of the 'rows' field, i.e. how many of the 752
# legal-authority rows each status ultimately covers)
rows_weighted = Counter()
for r in rows:
    rows_weighted[r["status"]] += r["rows"]
print("rows-weighted status counts (sum of per-token row_count):", dict(rows_weighted))
print("rows-weighted not-an-act subtypes:", {t: sum(r["rows"] for r in rows if r["status"] == f"not-an-act:{t}") for t in nonact_types})

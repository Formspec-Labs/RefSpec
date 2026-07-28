# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

## Verified inventory of US federal regulatory/legislative controlled vocabularies

### Headline finding: the coverage problem is structural, not a vocabulary-size problem

I measured the actual Federal Register corpus via the API (12,149 documents sampled across 2025, six months × 3 pages):

| Metric | Value |
|---|---|
| Docs with ≥1 FR Thesaurus topic | **13.1%** |
| Distinct FR topics actually used | **541** |
| Docs with `toc_subject` | **73.1%** |
| Distinct `toc_subject` values | **613** |

Coverage by document type (200-doc samples, 2025):

| Type | 2025 count | With `topics` | With `toc_subject` |
|---|---|---|---|
| Rule | 2,441 | 67% | 65% |
| Proposed Rule | 1,498 | 75% | 66% |
| **Notice** | 10,000+ | **0%** | **75%** |
| Presidential Doc | 471 | **0%** | — |

**Notices are ~81% of the corpus and carry zero Thesaurus topics.** This is by law, not neglect: [1 CFR 18.20](https://www.ecfr.gov/current/title-1/chapter-I/subchapter-E/part-18/section-18.20) requires index terms only for documents "published in the Rules and Regulations section or the Proposed Rules section," per CFR part affected. Notices have no CFR parts, so they get no terms. Independently confirmed in GovInfo MODS for FR-2024-01-02: RULE 8/11, PRORULE 2/5, NOTICE **0/47**, PRESDOCU 0/2.

Adding more concepts to the vocabulary cannot fix this. No vocabulary is applied to 87% of the corpus.

---

### Tier 1 — Purpose-built, machine-readable today

**1. Federal Register Thesaurus of Indexing Terms**
- Maintainer: Office of the Federal Register / NARA. Mandated by 1 CFR 18.20.
- **Size (verified via API): 1,044 thesaurus terms + 6,723 ad hoc = 7,767 total.** `{"meta":{"count":{"thesaurus":1044,"ad_hoc":6723,"total":7767}}}`
- Structure: flat with cross-refs. 535 of 1,044 have `see_also`. The 1995 file shows full BT/NT/UF (`sa`/`x`/`xx`) structure plus 2-digit category codes, but the **API exposes only `see_also` — the hierarchy is lost**.
- JSON API: https://www.federalregister.gov/api/v1/topics.json (verified 200)
- Current authoritative version is **PDF only**: https://www.archives.gov/files/federal-register/cfr/thesaurus-4-1-2025.pdf (178pp, updated 2025-04-01)
- Text version https://www.archives.gov/files/federal-register/cfr/thesaurus-alpha.txt is **dated November 16, 1995** — 4,853 lines, ~677 preferred terms, 375 `see` cross-refs. Stale by 30 years but the only machine-readable source with the full hierarchy.
- License: US Government work, public domain. Cadence: annual (Jan 1 CFR Index basis).
- ⚠️ The 6,723 "ad hoc" terms are **parsing garbage**: `"165 as follows:"`, `"17 CFR Parts 230"`, `"1200 Sixth Avenue"`, and 100-char rule titles. Use the 1,044 thesaurus set only.

**2. CFR List of Subjects (part → terms mapping)** — the most underrated asset here
- I scraped all 50 titles: **8,409 CFR parts, 37,220 (part, term) assignments, 1,196 distinct terms, avg 4.4 terms/part, 294 terms used once.**
- HTML, one page per title: https://www.archives.gov/federal-register/cfr/subject-title-01.html … `-50.html` (index: https://www.archives.gov/federal-register/cfr/subjects.html), current as of 2025-04-01.
- 1,196 distinct > 1,044 thesaurus because agencies add non-Thesaurus terms (permitted by 18.20).
- Top terms are extremely skewed and near-useless as topics: "Reporting and recordkeeping requirements" (3,378), "Administrative practice and procedure" (2,263), "Government procurement" (894).
- **This gives you a free propagation path**: any document with `cfr_references` inherits terms from its part — including notices that cite CFR parts.

**3. Federal Register `toc_subject`** — the notices answer
- Not a published vocabulary, but a de facto controlled action/genre taxonomy in the FR table of contents. **613 distinct values covering 73.1% of all documents including 75% of notices.** 378 used once → ~235 recurring.
- Top values: "Hearings, Meetings, Proceedings, etc." (1,484), "Agency Information Collection Activities…" (1,296), "Self-Regulatory Organizations; Proposed Rule Changes" (806), "Product Change" (322), "Antidumping or Countervailing Duty Investigations…" (309), "Airworthiness Directives" (271).
- Free in every FR API response. No download needed; harvest from the corpus.

**4. Congress.gov / CRS vocabularies**
- **33 Policy Area Terms** (exactly one per bill; span 1973–present) and **~1,000 Legislative Subject Terms** (issue, entity, and geographic). Verified from the GPO Bill Status XML User Guide: "There are 33 policy area terms"; "approximately 1,000 issue-oriented, entity, and geographic terms."
- Assigned by CRS legislative analysts.
- Machine-readable via **GovInfo BILLSTATUS bulk XML** (`<policyArea>`, `<legislativeSubjects>`): https://www.govinfo.gov/bulkdata/BILLSTATUS (verified 200, updates every 4 hours) and the Congress.gov API.
- Guide: https://github.com/usgpo/bill-status/blob/master/BILLSTATUS-XML_User_User-Guide.md
- ⚠️ congress.gov HTML pages return **403** to automated fetches — use bulk XML/API. The canonical term lists live at https://www.congress.gov/help/field-values/legislative-subject-terms and https://www.congress.gov/browse/legislative-subject-terms.
- **These are bill vocabularies, not regulatory ones.** No agency applies them to Federal Register documents.

**5. Legislative Indexing Vocabulary (LIV)** — RETIRED
- CRS thesaurus for LoC databases **1973–2008; discontinued 2008**. Legacy LIV terms remain searchable on Congress.gov for older material only. Do not build on it. (Size unverified — I could not fetch a term count.)

**6. Unified Agenda / RIN metadata (reginfo.gov)**
- Full per-RIN XML export, **55 elements**, verified by download: `RIN, RULE_TITLE, ABSTRACT, PRIORITY_CATEGORY, RULE_STAGE, RIN_STATUS, MAJOR, UNFUNDED_MANDATE, CFR_LIST/CFR, LEGAL_AUTHORITY_LIST, TIMETABLE_LIST, RFA_REQUIRED, SMALL_ENTITY_LIST, GOVT_LEVEL_LIST, FEDERALISM, ENERGY_AFFECTED, INTERNATIONAL_INTEREST, EO_13771_DESIGNATION, FR_CITATION, **NAICS_LIST/NAICS_CD/NAICS_DESC**, AGENCY_CONTACT_LIST…`
- URL pattern: `https://www.reginfo.gov/public/do/eAgendaViewRule?pubId=202504&RIN=2060-AW65&operation=OPERATION_EXPORT_XML`
- **It carries 6-digit NAICS.** Verified example (RIN 2060-AW65): `324199 All Other Petroleum and Coal Products Manufacturing; 331110 Iron and Steel Mills and Ferroalloy Manufacturing`.
- The online Unified Agenda "retains the Unified Agenda's subject index based on the Federal Register Thesaurus of Indexing Terms" ([Preamble](https://www.reginfo.gov/public/jsp/eAgenda/StaticContent/201510/Preamble_8888.html)).
- Priority values: Economically Significant / Other Significant / Substantive, Nonsignificant / Routine and Frequent / Informational-Administrative-Other. Stages: Prerule / Proposed Rule / Final Rule / Long-Term / Completed.
- ⚠️ NAICS is **optional** — population rate across all RINs is **unverified**; I confirmed the field exists and is populated on the record I checked, not its overall fill rate.
- Bulk XML list (EO 12866 reviews, agency list): https://www.reginfo.gov/public/do/XMLReportList. Note the EO review XML has only **13 elements and no subject field at all**: `AGENCY_CODE, RIN, TITLE, STAGE, ECONOMICALLY_SIGNIFICANT, DATE_RECEIVED, LEGAL_DEADLINE, PANDEMIC_RESPONSE, HEALTH_CARE_ACT, DODD_FRANK_ACT, INTERNATIONAL_IMPACTS, TCJA, REGACT`.

**7. CFR structure as de facto classification**
- **50 titles** (title 35 reserved), verified: https://www.ecfr.gov/api/versioner/v1/titles.json
- **8,409 parts** with subject lists (my count above).
- Agency → CFR mapping: https://www.ecfr.gov/api/admin/v1/agencies.json — **153 top-level agencies, 316 including children, 487 `cfr_references`** (title+chapter granularity).
- FR API agencies: **472** (225 with a parent) — https://www.federalregister.gov/api/v1/agencies
- FR document fields include `topics`, `toc_subject`, `toc_doc`, `cfr_references`, `agencies`, `regulation_id_numbers`, `docket_ids`, `significant`, `regulations_dot_gov_info`.

**8. NAICS (affected-industry axis)**
- Verified from the Census 2022 structure file: **17 sectors (2-digit), 99 (3), 309 (4), 689 (5), 1,012 (6-digit industries)**.
- https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx — public domain, revised every 5 years (2022; next 2027).

**9. RegData / QuantGov** — the one proven FR/CFR ↔ vocabulary mapping
- Mercatus Center (GWU). ML classifiers assign a **probability that a unit of regulatory text applies to a NAICS industry**. Restrictions counted by occurrences of *shall, must, may not, required, prohibited*.
- RegData 3.0+ covers **all NAICS levels 2–6 digit**; RegData US 6.0 ships 3-, 4-, 5-, 6-digit classifications. Trained using the Federal Register as the training corpus and the CFR as the analysis corpus.
- **CSV in ZIP, CC BY 4.0** — https://www.quantgov.org/data (includes a separate **"Federal Register 1.0" dataset, 1996–2017**). History/methodology: https://www.quantgov.org/history
- Python/R API clients: https://github.com/QuantGov/regcensus-api-python, https://github.com/QuantGov/regcensus-api-R
- This is the strongest precedent for the team's problem, and it deliberately avoids a topical thesaurus in favor of an industry axis.

**10. GovInfo / GPO metadata**
- MODS XML per package, e.g. https://www.govinfo.gov/metadata/pkg/FR-2024-01-02/mods.xml (verified, 389 KB, 74 element types).
- Carries `<subject><topic>` = the **same FR indexing terms** (no independent vocabulary), plus `<cfr>`, `<rin>`, `<agency>`, `<frDocNumber>`, `<granuleClass>`, `<tocSubject1>`, and `<classification>` holding **SuDoc** (`AE 2.7:`, `GS 4.107:`) and **LC call numbers** (`KF70.A2`).
- GovInfo adds no topical vocabulary of its own for FR/CFR. It is a mirror, not a second source.

---

### Tier 2 — Exists but not topical, or not applicable

**Regulations.gov — no subject tagging at all.** Confirmed against https://open.gsa.gov/api/regulationsgov/. The `category` field is **agency-configurable *commenter* categories** (e.g. "Academia - E0007"), retrieved via `/v4/agency-categories?filter[acronym]=FDA` — it classifies *who submitted a comment*, not what a document is about. `documentType` is only {Proposed Rule, Rule, Supporting & Related, Other}; `subtype` is agency-configurable and undocumented. **There is no topical vocabulary on regulations.gov.**

**EPA vocabularies — separate the registry from the taxonomy:**
- *EPA Web Taxonomy* — genuinely **faceted and topical**, the closest US federal analogue to what you want. Verified 16 facets at https://sor.epa.gov/sor_internet/registry/termreg/searchandretrieve/taxonomies/search.do: Tier 1 Web Taxonomy; Tier 2 = Audiences, Content Types, Coop & Assistance Topics, EPA Channel, EPA Operations Topics, Emergencies & Cleanup Topics, **Environmental Laws, Regulations & Treaties**, Environmental Media Topics, Functions, Geographic Locations, Health Topics, **Industries**, Pollution Prevention Topics, **Regulatory & Industrial Topics**, Research/Analysis & Technology Topics, Substances. Excel/XML/PDF/RTF export buttons exist but are **session-bound — my direct export attempt returned 0 bytes**. SKOS is advertised on https://catalog.data.gov/dataset/epa-web-taxonomy but that record shows **last updated 2014-01-01**. **Term count unverified.** License: https://edg.epa.gov/EPA_Data_License.html
- *Substance Registry Services / TSCA Inventory* — **entity registries, not topical vocabularies**. TSCA Inventory: **">86,000 chemicals," updated twice a year** (https://www.epa.gov/tsca-inventory/about-tsca-chemical-substance-inventory). Chemical identity ≠ subject. **The 14% TSCA slice of your fused vocabulary is categorically the wrong kind of object for document topic tagging.**

**FAST / LCSH — what you're currently using, and why it misfires**
- FAST: **~1.8 million authority records, 9 facets** (Personal/Corporate/Meeting names, Geographic, Events, Titles, Time periods, Topics, Form/Genre), derived from LCSH — https://www.oclc.org/research/areas/data-science/fast.html. Your 513k × 86% ≈ 441k is consistent with the FAST **Topical** facet alone.
- LCSH bulk downloads in **MADS/RDF and SKOS/RDF** (JSONLD/NT/TTL/XML), verified live and modified **2026-07-22**: https://id.loc.gov/download/authorities/subjects.skosrdf.nt.gz (index: https://id.loc.gov/download/)
- These are *library cataloging* vocabularies for books. Nothing in the federal regulatory pipeline emits them.

---

### Tier 3 — Agency thesauri (topical, but domain-siloed)

| Vocabulary | Size | Format | URL | Status |
|---|---|---|---|---|
| **NASA Thesaurus** | **22,622 skos:Concept, 22,622 prefLabel, 4,503 altLabel** (verified by downloading the 33 MB SKOS) | SKOS/RDF, OWL, ZThes, CSV, PDF | https://www.sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml · `-OWL.xml` · `-ZThes.xml` · `-CSV.txt` (all 200) | Live. Best-packaged US federal thesaurus I found. |
| **NAL Agricultural Thesaurus (NALT)** | **Core 14,196 concepts (4,396 taxa); Full 77,093; AWIC 881; Taxon 52,978** | SKOS (formats not fully verified) | https://lod.nal.usda.gov/ | Live; "NALT for the Machine Age" redesign |
| **EPA Web Taxonomy** | unverified | SKOS advertised; UI export session-bound | https://sor.epa.gov/sor_internet/registry/termreg/searchandretrieve/taxonomies/search.do | data.gov record stale (2014) |

**Not verified** (no budget remaining — treat as leads, not findings): Transportation Research Thesaurus (https://trt.trb.org/ is a JS SPA returning a 1 KB shell to fetchers; TRB-maintained, size unknown), ERIC Thesaurus (https://eric.ed.gov/?ti=all returns 200), DTIC/DoD Thesaurus, NTIS subject categories, GAO, DOE, NIOSH. **I did not verify any size, format, or license for these.**

**International comparison points:**
- **EuroVoc** — Publications Office of the EU, **version 4.24**, 24 EU languages + Albanian/Macedonian/Serbian, SKOS. https://op.europa.eu/en/web/eu-vocabularies/dataset/-/resource?uri=http://publications.europa.eu/resource/dataset/eurovoc — **concept/domain/microthesaurus counts unverified** (the page did not disclose them). Conceptually the closest analogue: a purpose-built multilingual *legislative* thesaurus actually applied to EUR-Lex at scale, and the standard benchmark for legal multi-label classification.
- **AGROVOC** — FAO, SKOS, ~37 languages, **continuous release since July 2025** (monthly releases discontinued). AgroPortal reports 34 classes / 1,344,147 individuals — that figure is the RDF individual count, **not** a concept count. https://agrovoc.fao.org/browse/agrovoc/en/
- **UNBIS Thesaurus** — not investigated.

---

### What this means for the team

1. **The problem is annotation coverage, not vocabulary size.** 513k concepts are being applied to a corpus where the native vocabulary reaches 13% of documents. A bigger vocabulary makes this worse, not better.
2. **~1,901 "regulatory" concepts isn't the shortfall — 541 is the real working set.** Only 541 distinct FR Thesaurus topics appear across 12,149 documents in a year. The other ~500 of the 1,044 are dormant. Meanwhile 86% of the vocabulary (FAST) has no federal emitter at all, and 14% (TSCA) is a chemical registry, not a subject scheme.
3. **Three free axes are already in the corpus and are being ignored**: `toc_subject` (613 values, 73% coverage, and it *works on notices*), `cfr_references` → CFR List of Subjects (8,409 parts → 1,196 terms, propagates topics to any doc citing a part), and `agencies` (472 FR / 316 eCFR, with 487 agency→CFR references).
4. **NAICS is the proven industry axis** — already in Unified Agenda records as a native field, and RegData demonstrates ML text→NAICS mapping over exactly this corpus under CC BY 4.0.
5. **Only PDF-locked artifact worth noting**: the current (2025-04-01) FR Thesaurus with its full BT/NT/UF hierarchy. The JSON API flattens it to `see_also` only, and the hierarchical text file is frozen at 1995. If hierarchy matters, that 178-page PDF must be parsed.

The temporary part-to-term map, topic dumps, and samples used during this snapshot were not preserved in this repository.

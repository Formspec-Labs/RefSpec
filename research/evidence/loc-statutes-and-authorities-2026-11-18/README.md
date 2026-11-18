# Library of Congress Pre-1951 Statutes at Large (Vols. 1–64) & `id.loc.gov` Corporate Name Authority Alignment

**Date:** 2026-11-18  
**Milestone:** Milestone 9 (`LOC-HANDOFF.md` lines 107–108, 125)  
**Production Modules:** `src/refspec/loc_statutes_at_large.py`, `src/refspec/loc_agency_authorities.py`  
**Offline Unit Tests:** `tests/test_loc_statutes_at_large.py`, `tests/test_loc_agency_authorities.py`

## Committed SHA-256-Pinned Evidence Manifests

| File | Bytes | SHA-256 | Contents |
|---|---:|---|---|
| `llsl-volumes-1-64-catalog.json` | `92,517` | `sha256:712b2b572eddaf0b95329576366a37e523717042090957096ccf602553fba351` | Complete 64-volume (`llsl-v1`..`llsl-v64`) catalogue from 4 paginated `?fo=json&c=25` captures (`82` collection items, `97` `llsl` PDFs, `69` `llsalvol` page objects) |
| `llsl-ocr-verification-manifest.json` | `50,833` | `sha256:2e4984c5c0790ae707786c06c6de821717e06aadcd1d338e68423aa4483f29fc` | 10 SHA-256-pinned `llsl` PDFs (`19,555` pages across Vols. 1–62), 2 `llsalvol` `.alto.xml` captures, and 16 pixel- and stream-verified statutory specimens |
| `lcnaf-federal-agencies-alignment.json` | `91,737` | `sha256:6fb107da6c70f37fc150866d9a82667c9fb8be5c4063546c5b67cd84d1a8380a` | 54 SHA-256-pinned `id.loc.gov` MADS/RDF corporate authority graphs (`47` `AGENCY_CROSSWALK` agencies + `7` historical predecessors), 8 negative/sensitivity probes, and `externallinks.nt.zip` cross-audit |

Raw multi-MB PDFs (`1.71 GB`) and raw HTTP JSON/ALTO captures are stored outside Git under `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-loc-statutes-20261118/` and regenerated deterministically via `scripts/build_evidence_manifests.py`. All network calls obeyed strict LoC etiquette (`>= 8.0s` spacing on `https://www.loc.gov/...?fo=json`, `>= 2.0s` spacing on `tile.loc.gov` and `id.loc.gov`, zero HTML requests on `www.loc.gov`, zero `webarchive.loc.gov` requests, zero `429`/`403`/`cf-mitigated` responses; `item/llsl-v18/?fo=json` returned an origin `503` timeout documented below).

---

## Part 1 — Pre-1951 Statutes at Large (Vols. 1–64, 1789–1950) Verification for `act_resolution.py`

### 1.1 Current Representation & Primary-Evidence Gaps in `RefSpec`

GovInfo's `STATUTE` collection starts at **Volume 65 (1951)**. Auditing `src/refspec/registry/act_resolution.py`, `src/refspec/registry/usc_act_index.py`, `src/refspec/registry/hand_validated_interpretations.py`, and the built `usc-act-index` parquets establishes the exact pre-1951 surface:

- **`usc-popular-names.parquet`:** `2,097` of `7,668` rows (`27.3%`) cite Volumes `1..64` (spanning `60` distinct volumes; missing Vols. `6` [Private Laws], `7` [Indian Treaties], `8` [European Treaties], and `51` [75th Cong., 2d Sess.]).
- **`usc-act-sections.parquet`:** `33,485` of `132,356` rows (`25.3%`) cite Volumes `1..64` (spanning `61` distinct volumes; missing only non-public-law Vols. `6, 7, 8`).
- **`usc-source-credits.parquet`:** **`0` rows** in Volumes `1..64` because `usc_act_index._PUBLIC_LAW_KEY = re.compile(r"^\d+-\d+$")` restricts public-law credit keys to post-1957 `Pub. L. {congress}-{law}` keys and excludes `YYYY:chapter` session-law keys (`_SESSION_LAW_KEY`).
- **`ActIndex` drops `statutes_at_large_volume` at load time:** `ActSection` in `act_resolution.py` keeps `(table3_key, act_section, statutes_at_large_page, division)` and omits `statutes_at_large_volume`, so resolving `(volume, page)` requires reading `usc-act-sections.parquet` / `usc-popular-names.parquet` directly.
- **Unscoped multi-title acts in `act_page_range`:** Pre-1951 omnibus statutes whose titles restart at `Sec. 1` without a populated `division` field cause `act_page_range()` to return `None` when section numbers decrease as `statutes_at_large_page` increases — e.g. `1933:25` (*Agricultural Adjustment Act* / *Emergency Farm Mortgage Act*, `48 Stat. 31`) and `1940:686` (*Investment Company Act* Title I at `54 Stat. 789` + *Investment Advisers Act* Title II `Sec. 201..221` at `54 Stat. 847`, plus `Sec. 3` cross-amendment).
- **`1,250` pre-1951 rows in `quarantine.parquet` (`record_without_act_section`):** Early single-paragraph statutes carry no printed `SECTION 1.` designator in the Statutes at Large (e.g. `1807:39`, *Insurrection Act*, `2 Stat. 443`), and pre-1874 acts codified through the Revised Statutes of 1874 carry `R.S. Sec ...` in OLRC Table III without chaining back to the original session-law section.
- **Two pixel-verified upstream OLRC `popularnames.htm` defects uncovered by LoC scan inspection:**
  1. **`"Alien Enemy Act"` (`1798:58`, `1 Stat. 570`) vs actual *Alien Enemies Act* (`1798:66`, `1 Stat. 577`):** Rendering `llsl-c5.pdf` p. 35 (`1 Stat. 570`) and p. 42 (`1 Stat. 577`) proves `1 Stat. 570` (`FIFTH CONGRESS. SESS. II. CH. 58. 1798`, June 25, 1798) is *An Act concerning Aliens* (the expired 2-year *Alien Friends Act*), whose editorial footnote `(a)` states *"This act having expired, the act respecting alien enemies, passed July 6, 1798, chap. 66, will be accompanied with tables of reference..."* The actual *An Act respecting Alien Enemies* (`50 U.S.C. 21–24` via `R.S. §§ 4067–4070`) is `1798:66` on `1 Stat. 577` (`CHAP. LXVI`, July 6, 1798).
  2. **`"Alien Contract Labor Law of 1895"` (`1885:164`, `23 Stat. 332`):** Rendering `llsl-c48.pdf` p. 350 (`23 Stat. 332`) confirms `FORTY-EIGHTH CONGRESS. SESS. II. CH. 164. 1885` (*Foran Act*, approved **Feb. 26, 1885**); `"1895"` in OLRC's popular-name string is a 10-year upstream typographical error.

### 1.2 LoC Collection Structure & Determinism of `(volume, page)` Lookup (`LOC-HANDOFF.md:125`)

Paginating `https://www.loc.gov/collections/united-states-statutes-at-large/?fo=json&c=25` (`sp=1..4`) yields **`82` records**: all **`64` volume items (`llsl-v1`..`llsl-v64`)** plus `18` collection-level essay/front-matter records. LoC never publishes per-chapter PDFs; every volume exposes two parallel digital representations:

| Resource Tier | Count (Vols. 1–64) | Lookup from `(volume, page)` | Exact Exceptions & Edge Cases |
|---|---:|---|---|
| Volume item (`https://www.loc.gov/item/llsl-v{vol}/`) | `64` items | **`64/64` (`100%`) arithmetic** from `volume` | `item/llsl-v18/?fo=json` returns HTTP `503` origin timeout while serializing Vol. 18's 5 `llsalvol` objects; PDF & `llsalvol` URLs remain available in the collection-level JSON (`llsl-volumes-1-64-catalog.json`). |
| Page-segmented object (`https://www.loc.gov/resource/llsalvol.llsal_{vol:03d}/`) | `69` objects | **`62/64` (`96.9%`) single-object arithmetic** from `volume`; page stem maps `stat_page` deterministically once METS/item segment list is read | **Vol. 18** splits into `llsal_018a`..`018e` (`5` objects: 43rd Cong. + Revised Statutes, D.C., Post Roads, Public Treaties, Index); **Vol. 44** splits into `llsal_044` (69th Cong.) and `llsal_044a` (1925 U.S. Code). Each segment's 8-char stem encodes `{scan_frame:04d}{printed_page:04d}` (e.g. `06940570.alto.xml` = frame `694`, `1 Stat. 570`, `?sp=693`), `{scan_frame:04d}r{roman:03d}` (`0041r045` = Roman `xlv`), or `{scan_frame:04d}0000` (unnumbered cover/spine). |
| Bulk PDF (`https://tile.loc.gov/storage-services/service/ll/llsl/.../*.pdf`) | `97` PDFs | **Requires 64-volume catalogue (`llsl-volumes-1-64-catalog.json`)**; **`52/64` (`81.25%`)** resolve uniquely from `volume` alone; **`12/64` (`18.75%`)** are multi-Congress/multi-part (`45` PDFs) | Multi-PDF volumes are `Vols. 1, 2, 3, 4, 5, 9, 10, 11, 12, 18, 20, 44` (`2` to `7` PDFs each). Published LoC URLs contain a literal double slash (`/service/ll/llsl//llsl-c5/llsl-c5.pdf`; both `//` and `/` return HTTP `200`). `YYYY:chapter` `table3_key` narrows unambiguously when the year lies in one Congress PDF (e.g. `1798:66` -> `llsl-c5.pdf`), but odd Congress-transition years (e.g. `1807` spanning `llsl-c9.pdf` [9th Cong. `1805/1807`] and `llsl-c10.pdf` [10th Cong. `1807/1809`]) remain 2-way candidates without Congress or exact month/day. Internal 1-based PDF page numbers shift by front-matter or multi-session offsets (`-535` on `llsl-c5.pdf`; `+5` to `+46` on single-volume PDFs). |

### 1.3 Embedded OCR Verdict: Dual Overlaid `3 Tr` Invisible OCR Architecture (`LOC-HANDOFF.md:125`)

**Verdict:** **10 out of 10 (`100%`)** sampled LoC `llsl` PDFs (`19,555` pages across all four eras: Vols. `1, 2, 23, 24, 38, 49, 51, 54, 60, 62`) contain embedded machine-searchable OCR text — specifically, **two overlaid `3 Tr` (invisible text rendering mode) OCR layers on every page**:

1. **Layer 1 — Legacy 2007/2014 Type 1 OCR (`Times-Roman`, `Times-Bold`, `Times-Italic`, `Helvetica`, `Courier`, `WinAnsiEncoding`):** Preserves running headers and small-caps section designators (`CHAP.`, `SECTION 1.`, `SEC. 2.`) without letter splitting (`12/12` strict section match), **but** merges marginal side-notes directly into adjacent body prose lines.
2. **Layer 2 — July 2021 Reprocessed Type 0 CID OCR (`/InvisibleOCR`, `Identity-H`, `Producer: Foxit FXPDFA 1.2`, `Creator: PDF Compressor 8.2.12.20`):** Matches the single-layer `llsalvol` `.alto.xml` text stream, cleanly zones marginal side-notes into separate blocks away from statutory prose, and captures running page numbers on `16/16` (`100%`) specimens (including `38 Stat. 717` where Layer 1 drops `"717"`), **but** systematically splits spaced small-caps initial capitals (`"S EC. 1."`, `"S ECTION 1."`, `"C HAP."`), dropping strict `SEC` regex recall to `4/12` (`33.3%`) unless normalized (`normalize_split_smallcaps_designators()` restores **`12/12 = 100%`**).

**Critical failure mode for naive PDF readers:** Spatial extractors (`pdftotext` default, `pdftotext -layout`, `pdftotext -bbox`) interleave tokens from Layer 1 and Layer 2 on the same `(x, y)` baseline (`7,914` collided chars vs `4,363` Layer 1 / `4,389` Layer 2 chars on `1 Stat. 570`):

```text
# Naive spatial pdftotext collision on 1 Stat. 570 (llsl-c5.pdf p. 35):
570 570 FIFTH CONGRESS. FIFTH CONGRESS. Sass. II. IL C. Cn. 58. SESS. 58. 1798. 1798.

# Font-separated via extract_llsl_pdf_ocr_layers():
Layer 1 (Type 1):        FIFTH CONGRESS. SESS. II. C. 58. 1798. ... SECTION 1. Be it enacted ...
Layer 2 (/InvisibleOCR): 570 FIFTH CONGRESS. Sass. IL Cn. 58. 1798. ... S ECTION 1. Be it enacted ...
```

### 1.4 Multi-Era Citation & Section Accuracy Across 16 Stratified Specimens

| Metric | Layer 1 (2007 Type 1) | Layer 2 (2021 `/InvisibleOCR`) | Font-Separated Union |
|---|---:|---:|---:|
| Printed `Stat.` page number exact (`16` specimens) | `15 / 16` (`93.8%`) | **`16 / 16` (`100.0%`)** | **`16 / 16` (`100.0%`)** |
| Chapter number exact (`16` specimens) | `15 / 16` (`93.8%`) | `15 / 16` (`93.8%`) | **`16 / 16` (`100.0%`)** |
| Printed section designator — strict `SEC(?:TION)?\.?\s*N` (`12` specimens*) | **`12 / 12` (`100.0%`)** | `4 / 12` (`33.3%`) | **`12 / 12` (`100.0%`)** |
| Printed section designator — small-caps split-tolerant (`12` specimens*) | **`12 / 12` (`100.0%`)** | **`12 / 12` (`100.0%`)** | **`12 / 12` (`100.0%`)** |

*\*Four of the 16 specimens (`2 Stat. 443` Insurrection Act `1807:39`, `24 Stat. 388` General Allotment/Dawes Act `1887:119`, `38 Stat. 717` FTC Act `1914:311` opening clause, and `49 Stat. 647` FPA Title II `1935:687` § 201 amendatory wrapper) have no printed `SEC. 1.` on that opening enacting clause in the original typography (verified by pixel inspection of rendered PNGs).*

Representative pixel-verified specimens across all four eras (full table & SHA-256s in `llsl-ocr-verification-manifest.json`):

- **Era 1 (`1–10 Stat.`):** `1 Stat. 570` (`llsl-c5.pdf` p. 35, offset `-535`, *Alien Friends Act* `1798:58`), `1 Stat. 577` (`llsl-c5.pdf` p. 42, offset `-535`, *Alien Enemies Act* `1798:66`), `2 Stat. 443` (`llsl-c9.pdf` p. 94, offset `-349`, *Insurrection Act* `1807:39` — single unnumbered enacting paragraph).
- **Era 2 (`16–25 Stat.`):** `23 Stat. 332` (`llsl-c48.pdf` p. 350, offset `+18`, *Foran Contract Labor Act of 1885* `1885:164`), `24 Stat. 379` (`llsl-c49.pdf` p. 397, offset `+18`, *Interstate Commerce Act* `1887:104`, `CHAP. 104` — Layer 2 misreads `104.` as `1047.` while Layer 1 reads `CHAP. 104.` cleanly), `24 Stat. 388` (`llsl-c49.pdf` p. 406, *Dawes Act* `1887:119`).
- **Era 3 (`30–49 Stat.`):** `38 Stat. 717` (`llsl-c63.pdf` p. 736, offset `+19`, *FTC Act* `1914:311` — Layer 1 drops page header `717` while Layer 2 reads `717` cleanly), `38 Stat. 730` (`llsl-c63.pdf` p. 749, *Clayton Act* `1914:323`), `49 Stat. 449` (`llsl-c74.pdf` p. 495, offset `+46`, *NLRA* `1935:372`), `49 Stat. 620` & `49 Stat. 647` (`llsl-c74.pdf` pp. 666, 693, *Social Security Act* `1935:531` & *Federal Power Act* Title II `1935:687` `SECTION 201`).
- **Era 4 (`50–64 Stat.`):** `51 Stat. 4` (`llsl-c75s2.pdf` p. 9, offset `+5`, `1937:2` — proves Vol. 51 is present in LoC despite `0` rows in `usc-popular-names.parquet`), `54 Stat. 847` (`llsl-c76s2-s3.pdf` p. 881, offset `+34`, *Investment Advisers Act* Title II `1940:686` `SEC. 201`), `60 Stat. 237` (`llsl-c79s2.pdf` p. 263, offset `+26`, *Administrative Procedure Act* `1946:324`), `60 Stat. 755` (`llsl-c79s2.pdf` p. 781, *Atomic Energy Act of 1946* `1946:724`), `62 Stat. 1155` (`llsl-c80s2.pdf` p. 1185, offset `+30`, *Clean Water Act predecessor* `1948:758` — referenced in `hand_validated_interpretations.py`).

---

## Part 2 — `id.loc.gov` Corporate Name Authorities (`LCNAF`) Alignment for Federal Agencies

### 2.1 Existing `RefSpec` External-Link Baselines Audited First

Before querying `id.loc.gov`, auditing `src/refspec/registry/lc_external_links.py`, `src/refspec/registry/oclc_fast_external_links.py`, and `src/refspec/registry/agency_crosswalk.py` revealed a major untapped local baseline:

1. **Pinned `lcsh-externallinks-2026-08-15.nt.zip` (`sha256:7d279d69c6920b41a579634a84a1b31ff73af764345fe51df3f7c480efeba9d1`) already contains `2,018,402` LCNAF external-link assertions:**
   - `lc_external_links.py` filters `external_links.nt` to `LCSH_SUBJECT_PREFIX = "http://id.loc.gov/authorities/subjects/"` (`802,592` assertions), skipping `2,018,402` assertions whose subject begins with `http://id.loc.gov/authorities/names/` (`1,418,942` to OCLC FAST, `425,540` to Wikidata, including `13,454` assertions targeting endpoints labeled `"United States"` / `"U.S."`).
   - **`54 / 54` (`100.0%`)** of the federal corporate LCCNs verified on `id.loc.gov` in this study are already present in that pinned archive (`50 / 54 = 92.6%` carry `closeExternalAuthority` Wikidata QIDs; `53 / 54 = 98.1%` carry OCLC FAST links; only `BOEM` `no2011188069`, `MMS` `n82104764`, `HCFA` `n77009797`, and `CAB` `n79046186` lack LC-curated Wikidata links).
2. **`oclc_fast_external_links.py` (`FASTTopical.nt.zip`) holds `0` corporate headings:** OCLC separates corporate headings into `FASTCorporate.nt.zip`, so `oclc_fast_external_links.py` covers topical facets only.
3. **`src/refspec/loc_agency_authorities.py::parse_lcnaf_external_links_statements` unlocks the `2.018M` LCNAF statements** directly from `external_links.nt` bytes while reusing `lc_external_links`'s exact unescaping, duplicate-claim refusal, and deterministic `"en"` endpoint-label attribution.

### 2.2 `id.loc.gov` `suggest2` Query Sensitivity & False-Friend Rates (`N = 54`)

We evaluated **`54` federal corporate entities** (`47` stratified agencies across `AGENCY_CROSSWALK` — all `15` Cabinet departments, `12` major sub-agencies/administrations, `13` independent commissions/boards, `5` `ambiguous`/`unmapped` codes [`DOC`, `DOI`, `TREAS`, `FMCS`, `EOIR`], and `2` defunct codes still marked `confident` [`MMS`, `OTS`] — plus `7` historical rename/split predecessors [`HEW`, `WAR`, `ICC`, `AEC`, `HCFA`, `INS`, `CAB`]) plus `8` negative/sensitivity probes against `https://id.loc.gov/authorities/names/suggest2/?q=...&rdftype=CorporateName` and `https://id.loc.gov/authorities/names/<lccn>.madsrdf.json`:

| Query Strategy on `suggest2` (`rdftype=CorporateName`) | Top-1 Exact Match | Zero-Hit Rate | False-Friend Rate at Rank 1 | Representative False Friends Returned by `id.loc.gov` |
|---|---:|---:|---:|---|
| Bare Federal Register inverted name (`"Energy Department"`, `"Management and Budget Office"`, `"Industry and Security Bureau"`) | **`0 / 3` (`0.0%`)** | `3 / 3` (`100%`) | `0 / 3` | Left-anchored `suggest2` returns `count: 0` on inverted FR names. |
| Bare acronym (`"EPA"`, `"DOT"`, `"FS"`, `"EAB"`) | **`0 / 4` (`0.0%` top-3)** | `0 / 4` | **`4 / 4` (`100%`)** | `"EPA"` -> `Eglise protestante africaine (Cameroon)` (`n2012004205`); `"DOT"` -> `Confederação Nacional da Indústria. Divisão de Documentação Técnica` (`n79086943`), `Democrats of Texas` (`n93016385`); `"FS"` -> `Fachverband für Strahlenschutz` (`n85285376`). |
| Bare natural name (`"Environmental Protection Agency"`, `"Securities and Exchange Commission"`, `"Department of Agriculture"`) | `13 / 54` (`24.1%`) | `14 / 54` (`25.9%`) | **`27 / 54` (`50.0%`)** | `"Environmental Protection Agency"` -> `Liberia. Environmental Protection Agency` (`no2009128816`); `"Securities and Exchange Commission"` -> `Bangladesh. Securities and Exchange Commission` (`no99081353`); `"Office of Management and Budget"` -> `Alaska. Office of Management and Budget` (`n83028922`); `"Department of Agriculture"` -> `Northern Ireland. Department of Agriculture and Rural Development` (`no2001053726`). |
| Rung 1: `"United States. <Natural Name>"` | `52 / 54` (`96.3%`) | `1 / 54` (`1.9%`) | `1 / 54` (`1.9%`) | Misses **(1)** `CMS`: `"United States. Centers for Medicare & Medicaid Services"` matches a 410 variant on **false friend** `Medicare Recovery Audit Contractor Program (U.S.)` (`n2013184550`), because `CMS` was cataloged post-RDA under direct entry `Centers for Medicare & Medicaid Services (U.S.)` (`no2001093385`); and **(2)** `EOIR`: `"United States. Executive Office for Immigration Review"` returns `0` hits because `EOIR` is cataloged subordinate to DOJ as `United States. Department of Justice. Executive Office for Immigration Review` (`n89643262`). |
| **4-Rung Corporate Ladder + Jurisdiction/Parent Verification (`build_lcnaf_corporate_queries` + `select_verified_lcnaf_hit`)** | **`54 / 54` (`100.0%`)** | **`0 / 54` (`0.0%`)** | **`0 / 54` (`0.0%`)** | Resolves all 4 LCNAF corporate heading patterns (`United States. <Body>`, `<Body> (U.S.)`, bare U.S. corporate body `Federal Deposit Insurance Corporation` `n81013186`, and `United States. <Dept>. <Sub-office>`) while rejecting foreign/state jurisdictions and subordinate-program variant traps. |

### 2.3 Crosswalk Sub-Agency Collapse & Historical-Rename / Split Hazards

1. **`AGENCY_CROSSWALK` parent-collapse & defunct-code hazards (`REF-038`):**
   - Because `agency_crosswalk.py` applies `SPECIFICITY_MARGIN = 0.05` over co-signing dockets, major sub-agencies resolve `primary_slug` to their **parent cabinet department**: `CDC` -> `health-and-human-services-department`, `CISA` -> `homeland-security-department`, `USCBP` -> `homeland-security-department`, `BOEM` -> `interior-department`. Joining LCNAF via `primary_slug` alone would attach `CDC`'s dockets to `HHS` (`n80102594`) instead of `Centers for Disease Control and Prevention (U.S.)` (`no93011529`).
   - Two abolished agencies remain `tier="confident"` in `AGENCY_CROSSWALK`: **`MMS`** (Minerals Management Service `n82104764`, abolished 2010–2011 -> `BOEMRE` `no2010108932` -> `BOEM` `no2011188069` / `BSEE`) and **`OTS`** (Office of Thrift Supervision `no89013654`, abolished July 21, 2011 under Dodd-Frank -> merged into `OCC`).
   - Companion MADS/RDF verification on ambiguous code **`PRC`** (`tier="ambiguous"`, top candidate `postal-regulatory-commission` score `0.9965` vs `presidio-trust`) likewise confirms successive entry between `United States. Postal Rate Commission` and `United States. Postal Regulatory Commission`.
2. **Heterogeneous MADS/RDF Succession Encoding Across Reorganizations (`REF-072`):**
   LCNAF uses **successive entry** (each corporate rename or split mints a distinct LCCN; an old LCCN is never reused for a renamed agency), but MADS/RDF encodes succession across **three incompatible patterns**:
   - **Mode A — Explicit `madsrdf:hasEarlierEstablishedForm` / `madsrdf:hasLaterEstablishedForm` (`1:1`, `1:N`, `N:1`):**
     - `AEC` (`n78034861`) -> `hasLaterEstablishedForm` -> `{NRC (n78034875), ERDA (n78034864)}` -> `DOE` (`n78034868`, `earlier=[n78034864, n78034871]` plus unlinked blank-node `United States. Federal Energy Office`).
     - `HCFA` (`n77009797`) <-> `CMS` (`no2001093385`).
     - `INS` (`n79053784`) -> `hasLaterEstablishedForm` -> `{no2003104838 (USCIS), no2003052379 (Bureau of Customs and Border Protection -> USCBP no2004040772), no2003065384 (ICE)}`.
     - `MMS` (`n82104764`) -> `BOEMRE` (`no2010108932`) -> `BOEM` (`no2011188069`).
     - `GAO`: `General Accounting Office` (`n80126064`) <-> `Government Accountability Office` (`no2004066329`).
   - **Mode B — Flattened into untyped `madsrdf:hasRelatedAuthority` alongside child offices:**
     - `HEW` (`n79006771`, `122` related) and `HHS` (`n80102594`, `156` related) have **empty** `hasEarlierEstablishedForm`/`hasLaterEstablishedForm`; `HEW` sits undifferentiated inside `HHS`'s untyped `hasRelatedAuthority` links alongside regional offices and subordinate administrations.
     - `War Department` (`n79084108`, `115` related) has `0` `hasLaterEstablishedForm` triples; `Department of the Army` (`n79063202`) and `Department of Defense` (`n79021946`, `earlier=[n87836258]` *National Military Establishment*) appear only in `War Department`'s untyped `hasRelatedAuthority` links.
     - `GPO`: `Government Publishing Office` (`no2015002503`) links to `Government Printing Office` via `hasRelatedAuthority` (`5` links), not `hasEarlierEstablishedForm`.
   - **Mode C — Unlinked in RDF (recorded only in cataloger prose `665`/`670` notes):**
     - `ICC` (`n80126245`, abolished Jan. 1, 1996, P.L. 104-88) and `Surface Transportation Board` (`no96011022`) share **zero RDF predicates** in either direction (`earlier=[]`, `later=[]`, `related=6` child bureaus).
     - `CAB` (`n79046186`, Civil Aeronautics Board, sunset Jan. 1, 1985) and `DOT` (`n79058419`) share **zero RDF predicates**.

   **Architectural Rule:** LCNAF identifiers must be attached as external authority cross-references (`madsrdf:Authority` / `LCNAF` LCCN + `externallinks.nt` Wikidata/FAST assertions) per established corporate stage — never equated across renames as `atlas:sameEntityAs`, and never treated as a standalone succession oracle without statutory change-event grounding (`REF-072`).

---

## Reproduction & Verification Commands

```bash
# Regenerate all 3 canonical manifests from cached raw responses (requires local .cache):
/Users/mikewolfd/Work/spicy-stack/RefSpec/.venv/bin/python \
  research/evidence/loc-statutes-and-authorities-2026-11-18/scripts/build_evidence_manifests.py

# Run fast-tier offline unit tests (zero network, zero .cache dependency):
PYTHONPATH=src /Users/mikewolfd/Work/spicy-stack/RefSpec/.venv/bin/python -m pytest \
  tests/test_loc_statutes_at_large.py \
  tests/test_loc_agency_authorities.py
```

# Library of Congress Pre-1951 Statutes at Large (Vols. 1–64) & `id.loc.gov` Corporate Name Authority Alignment

**Date:** 2026-11-18  
**Milestone:** Milestone 9 (`LOC-HANDOFF.md` lines 107–108, 125)  
**Production Modules:** `src/refspec/loc_statutes_at_large.py`, `src/refspec/loc_agency_authorities.py`  
**Offline Unit Tests:** `tests/test_loc_statutes_at_large.py`, `tests/test_loc_agency_authorities.py`

## Committed SHA-256-Pinned Evidence Manifests

| File | Bytes | SHA-256 | Contents |
|---|---:|---|---|
| `llsl-volumes-1-64-catalog.json` | `104,453` | `sha256:160b009b925adaa29fb93a2dfe8d43de56cf28727ddc5ec2ae143da171bb3268` | Complete 64-volume (`llsl-v1`..`llsl-v64`) catalogue from 4 paginated `?fo=json&c=25` captures (`82` collection items, `97` `llsl` PDFs with both verbatim caption years and constitutional Congress-term spans, `69` `llsalvol` page objects) |
| `llsl-ocr-verification-manifest.json` | `68,572` | `sha256:635e2377701e916c6ac738b9c0e165dd1ac2ecb15354816b030c3b968db15fc0` | 10 SHA-256-pinned `llsl` PDFs (`19,555` pages across Vols. 1–62), 2 `llsalvol` `.alto.xml` captures, 16 folio-and-act-scoped statutory specimens, and boundary/counterexample checks |
| `lcnaf-federal-agencies-alignment.json` | `112,061` | `sha256:0cf1dc0b3b7599d4c06363176a1c3f95e3e3b0f6fcd394d9b50511dcf69b5d6f` | 54 SHA-256-pinned `id.loc.gov` MADS/RDF corporate authority graphs (`47` `AGENCY_CROSSWALK` agencies + `7` historical predecessors), replayed via production selector & MARC `110` parser, plus 8 negative/sensitivity probes |

Raw multi-MB PDFs (`1.71 GB`) and raw HTTP JSON/ALTO captures are stored outside Git under `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-loc-statutes-20261118/` and regenerated deterministically via `scripts/build_evidence_manifests.py`, which imports and executes the production functions in `src/refspec/loc_statutes_at_large.py` and `src/refspec/loc_agency_authorities.py` directly over the raw cached files. `scripts/polite_loc_client.py` enforces `>= 8.5s` spacing on `https://www.loc.gov/...?fo=json` and `>= 2.2s` spacing on `tile.loc.gov` and `id.loc.gov` (with `fcntl.flock` lockfile coordination when a shared `state_file` is configured), rejects HTML and unlisted hosts (`webarchive.loc.gov`), validates `expect_kind`, and aborts on `429`/`403`/`cf-mitigated`/`Retry-After` headers before reading response bodies.

---

## Part 1 — Pre-1951 Statutes at Large (Vols. 1–64, 1789–1950) Verification for `act_resolution.py`

### 1.1 Current Representation & Primary-Evidence Gaps in `RefSpec`

GovInfo's `STATUTE` collection starts at **Volume 65 (1951)**. Auditing `src/refspec/registry/act_resolution.py`, `src/refspec/registry/usc_act_index.py`, `src/refspec/registry/hand_validated_interpretations.py`, and the built `usc-act-index` parquets establishes the exact pre-1951 surface:

- **`usc-popular-names.parquet`:** `2,097` of `7,668` rows (`27.3%`) cite Volumes `1..64` (spanning `60` distinct volumes; missing Vols. `6` [Private Laws], `7` [Indian Treaties], `8` [European Treaties], and `51` [75th Cong., 2d Sess.]).
- **`usc-act-sections.parquet`:** `33,485` of `132,356` rows (`25.3%`) cite Volumes `1..64` (spanning `61` distinct volumes; missing only non-public-law Vols. `6, 7, 8`).
- **`usc-source-credits.parquet`:** **`0` rows** in Volumes `1..64` because `usc_act_index._PUBLIC_LAW_KEY = re.compile(r"^\d+-\d+$")` restricts public-law credit keys to post-1957 `Pub. L. {congress}-{law}` keys and excludes `YYYY:chapter` session-law keys (`_SESSION_LAW_KEY`).
- **`ActIndex` drops `statutes_at_large_volume` at load time:** `ActSection` in `act_resolution.py` keeps `(table3_key, act_section, statutes_at_large_page, division)` and omits `statutes_at_large_volume`.
- **Unscoped multi-title acts in `act_page_range`:** Pre-1951 omnibus statutes whose titles restart at `Sec. 1` without a populated `division` field cause `act_page_range()` to return `None` when section numbers decrease as `statutes_at_large_page` increases — e.g. `1933:25` (*Agricultural Adjustment Act* / *Emergency Farm Mortgage Act*, `48 Stat. 31`) and `1940:686` (*Investment Company Act* Title I at `54 Stat. 789` + *Investment Advisers Act* Title II `Sec. 201..221` at `54 Stat. 847`).
- **`1,250` pre-1951 rows in `quarantine.parquet` (`record_without_act_section`):** Early single-paragraph statutes carry no printed `SECTION 1.` designator in the Statutes at Large (e.g. `1807:39`, *Insurrection Act*, `2 Stat. 443`, `llsl-c9.pdf` p. 96), and pre-1874 acts codified through the Revised Statutes of 1874 carry `R.S. Sec ...` in OLRC Table III without chaining back to the original session-law section.
- **Two pixel-verified upstream OLRC `popularnames.htm` defects uncovered by LoC scan inspection:**
  1. **`"Alien Enemy Act"` (`1798:58`, `1 Stat. 570`) vs actual *Alien Enemies Act* (`1798:66`, `1 Stat. 577`):** Rendering `llsl-c5.pdf` p. 35 (`1 Stat. 570`) and p. 42 (`1 Stat. 577`) proves `1 Stat. 570` (`FIFTH CONGRESS. SESS. II. CH. 58. 1798`, June 25, 1798) is *An Act concerning Aliens* (the expired 2-year *Alien Friends Act*), whose editorial footnote `(a)` states *"This act having expired, the act respecting alien enemies, passed July 6, 1798, chap. 66, will be accompanied with tables of reference..."* The actual *An Act respecting Alien Enemies* (`50 U.S.C. 21–24` via `R.S. §§ 4067–4070`) is `1798:66` on `1 Stat. 577` (`CHAP. LXVI`, July 6, 1798).
  2. **`"Alien Contract Labor Law of 1895"` (`1885:164`, `23 Stat. 332`):** Rendering `llsl-c48.pdf` p. **360** (`23 Stat. 332`, offset `+28`) confirms `FORTY-EIGHTH CONGRESS. SESS. II. CH. 161-164. 1885` (*Foran Act*, `CHAP. 164`, approved **Feb. 26, 1885**); `"1895"` in OLRC's popular-name string is a 10-year upstream typographical error.

### 1.2 LoC Collection Structure & Determinism of `(volume, page)` Lookup (`LOC-HANDOFF.md:125`)

Paginating `https://www.loc.gov/collections/united-states-statutes-at-large/?fo=json&c=25` (`sp=1..4`) yields **`82` records**: all **`64` volume items (`llsl-v1`..`llsl-v64`)** plus `18` collection-level essay/front-matter records. LoC never publishes per-chapter PDFs; every volume exposes two parallel digital representations:

| Resource Tier | Count (Vols. 1–64) | Lookup from `(volume, page)` | Exact Exceptions & Edge Cases |
|---|---:|---|---|
| Volume item (`https://www.loc.gov/item/llsl-v{vol}/`) | `64` items | **`64/64` (`100%`) arithmetic** from `volume` | `item/llsl-v18/?fo=json` returns HTTP `503` origin timeout while serializing Vol. 18's 5 `llsalvol` objects; PDF & `llsalvol` URLs remain available in `llsl-volumes-1-64-catalog.json`. |
| Page-segmented object (`https://www.loc.gov/resource/llsalvol.llsal_{vol:03d}/`) | `69` objects | **`62/64` (`96.9%`) single-object arithmetic** from `volume`; page stem maps `stat_page` deterministically once METS/item segment list is read | **Vol. 18** splits into `llsal_018a`..`018e` (`5` objects); **Vol. 44** splits into `llsal_044` (69th Cong.) and `llsal_044a` (1925 U.S. Code). 8-char stems encode `{scan_frame:04d}{printed_page:04d}` (`06940570.alto.xml` = frame `694`, `1 Stat. 570`, `?sp=693`), `{scan_frame:04d}r{roman:03d}` (`0041r045` = Roman `xlv`), or unnumbered `{scan_frame:04d}0000` / `{scan_frame:04d}r000` (e.g. `0043r000.alto.xml` on Vol. 52 seq 43 between `0042r047` and `00440003`). |
| Bulk PDF (`https://tile.loc.gov/storage-services/service/ll/llsl/.../*.pdf`) | `97` PDFs | **Requires 64-volume catalogue**; **`52/64` (`81.25%`)** resolve uniquely from `volume` alone; **`12/64` (`18.75%`)** are multi-Congress/multi-part (`45` PDFs) | Multi-PDF volumes are `Vols. 1, 2, 3, 4, 5, 9, 10, 11, 12, 18, 20, 44`. Published LoC URLs contain a literal `//` before the slug. **LoC PDF captions omit autumn opening session years** (e.g. `llsl-c5.pdf` is captioned `"5th Congress (1798/1799)"` even though PDF p. 1 is `1 Stat. 536`, `1797:1`, Dec. 15, 1797). `LlslPdfResource` therefore preserves `caption_year_start..end` verbatim while spanning `year_start..end` across the full constitutional Congress term (`1789 + 2*(c-1)..1789 + 2*c`), keeping `1797:1` (`llsl-c4.pdf` + `llsl-c5.pdf`) and `1807:39` (`llsl-c9.pdf` + `llsl-c10.pdf`) as 2-way candidates unless `congress` is supplied, and returning `unresolved_contradictory_filters` on contradictory inputs. Internal 1-based PDF page offsets range from `-535` (`llsl-c5.pdf`) to `+46` (`llsl-c74.pdf`). |

### 1.3 Embedded OCR Verdict: Dual Overlaid `3 Tr` Invisible OCR Architecture (`LOC-HANDOFF.md:125`)

**Verdict:** All **10 out of 10 (`100%`)** sampled LoC `llsl` PDFs (`19,555` total pages across Vols. `1, 2, 23, 24, 38, 49, 51, 54, 60, 62`) carry embedded machine-searchable OCR, and **all 16 verified statutory specimens** carry **two overlaid `3 Tr` (invisible text rendering mode) OCR passes on the same page** (while blank or un-reprocessed scan frames inside a PDF — such as `llsl-c48.pdf` p. 552 with `0` text in both passes and `llsl-c48.pdf` p. 292 with `1` legacy character `'4'` and no `/InvisibleOCR` stream — carry zero or one text stream):

1. **Layer 1 — Legacy 2007/2014 Type 1 OCR (`Times-Roman`/`Bold`/`Italic`, `Helvetica`, `Courier`, `WinAnsiEncoding`):** Preserves small-caps section designators without letter splitting when marginalia does not intrude (`9/12` strict heading-bound match; `23 Stat. 332` and `49 Stat. 620` inject lowercase marginalia directly ahead of `SEC.`, breaking heading-start boundaries), **and** merges marginal side-notes into body prose while occasionally dropping or truncating running headers (`717` missing on `38 Stat. 717`; `CH. 686` truncated to `CH. 68--` on `54 Stat. 847`).
2. **Layer 2 — July 2021 Reprocessed Type 0 CID OCR (`/InvisibleOCR`, `Identity-H`, `Producer: Foxit FXPDFA 1.2`, `Creator: PDF Compressor 8.2.12.20`):** Zones marginal side-notes into separate blocks away from statutory prose and captures the printed folio in the running header on **`16/16` (`100%`)** specimens, **but** splits spaced small-caps initial capitals (`"S EC. 1."`, `"S ECTION 1."`, `"C HAP."`) and occasionally corrupts bracketed chapter delimiters (`[CHAPTER 531.]` -> `[CHAPTER 5314` on `49 Stat. 620`; `[CHAPTER 686]` -> `[CHAPTER 6861` on `54 Stat. 789`). Comparing Layer 2 against `llsalvol` `.alto.xml` shows exact opening agreement on `1 Stat. 570` (`"570 FIFTH CONGRESS. Sass. IL Cn. 58. 1798."`), whereas on `1 Stat. 577` ALTO's running header reads `"FIFTH CONGRESS. SESS. II. CH. 66. 1798."` (omitting `577`) while PDF Layer 2 reads `"FIFTH CONGRESS . S ESS. H . C u. 66. 1798. 577"` — proving Foxit's July 2021 PDF pass is a separate OCR run rather than a copy of `llsalvol` ALTO XML.

**Spatial extractor collision:** Naive spatial extractors (`pdftotext` default, `-layout`, `-bbox`) interleave tokens from Layer 1 and Layer 2 on the same `(x, y)` baseline (`7,914` collided chars vs `4,363` Layer 1 / `4,389` Layer 2 chars on `1 Stat. 570`). `extract_llsl_pdf_ocr_layers()` separates them by font and extracts physical `(x, y)` running-header/footer bands.

### 1.4 Folio- and Act-Scoped Citation Accuracy Across 16 Stratified Specimens

`score_llsl_layer_citation()` binds every check to the printed structure: (a) **folio** is checked only in the physical top running-header band (or bottom folio band on session-opening title pages lacking a `CONG`/`STAT` header, so `"$4 per day"` on `51 Stat. 3` [`llsl-c75s2.pdf` p. 9] scores `False` when tested as `51 Stat. 4`); (b) **chapter** requires exact Arabic `expected_chapter` or `int_to_roman(expected_chapter)` (never wildcard `[IVXLCDM]+`); and (c) **section** slices `body_text` strictly from the target act's heading to the next act heading on the same page (so `ch. 163` tested for `Sec. 2` on `23 Stat. 332` scores `False` despite both `ch. 162` above it and `ch. 164` below it printing `SEC. 2.` on that page).

| Scoped Verification Metric | Layer 1 (Legacy Type 1) | Layer 2 (2021 `/InvisibleOCR`) | Font-Separated Union |
|---|---:|---:|---:|
| Printed `Stat.` folio in running header (`16` specimens) | `15 / 16` (`93.8%`) | **`16 / 16` (`100.0%`)** | **`16 / 16` (`100.0%`)** |
| Act chapter heading — strict (`16` specimens) | `14 / 16` (`87.5%`) | `11 / 16` (`68.8%`) | `15 / 16` (`93.8%`) |
| Act chapter heading — small-caps/bracket-tolerant (`16` specimens) | `15 / 16` (`93.8%`) | **`16 / 16` (`100.0%`)** | **`16 / 16` (`100.0%`)** |
| Section heading inside target act slice — strict (`12` specimens*) | `9 / 12` (`75.0%`) | `4 / 12` (`33.3%`) | `9 / 12` (`75.0%`) |
| Section heading inside target act slice — split-tolerant (`12` specimens*) | `9 / 12` (`75.0%`) | **`12 / 12` (`100.0%`)** | **`12 / 12` (`100.0%`)** |
| **Joint bound citation (folio + chapter + act section)** (`16` specimens; strict L1 vs normalized L2/union) | `12 / 16` (`75.0%`) | **`16 / 16` (`100.0%`)** | **`16 / 16` (`100.0%`)** |

*\*Four of the 16 specimens (`2 Stat. 443` Insurrection Act `1807:39` [PDF p. 96], `23 Stat. 31` Animal Industry Act `1884:60` [PDF p. 59], `38 Stat. 717` FTC Act `1914:311` [PDF p. 736], and `51 Stat. 4` Federal Credit Union Act amendment `1937:3` [PDF p. 10]) have no printed `SEC. 1.` on that opening enacting clause.*

Verified specimens across all four eras (exact excerpts & metrics in `llsl-ocr-verification-manifest.json`):

- **Era 1 (`1–10 Stat.`):** `1 Stat. 570` (`llsl-c5.pdf` p. 35, offset `-535`, *Alien Friends Act* `1798:58`), `1 Stat. 577` (`llsl-c5.pdf` p. 42, offset `-535`, *Alien Enemies Act* `1798:66`), `2 Stat. 443` (`llsl-c9.pdf` p. 96, offset `-347`, *Insurrection Act* `1807:39`).
- **Era 2 (`16–25 Stat.`):** `23 Stat. 31` (`llsl-c48.pdf` p. 59, offset `+28`, *Animal Industry Act* `1884:60`), `23 Stat. 332` (`llsl-c48.pdf` p. **360**, offset `+28`, *Foran Contract Labor Law of Feb. 26, 1885* `1885:164` `SEC. 2`), `24 Stat. 379` (`llsl-c49.pdf` p. 412, offset `+33`, *Interstate Commerce Act* `1887:104` `SEC. 2`).
- **Era 3 (`30–49 Stat.`):** `38 Stat. 251` (`llsl-c63.pdf` p. 270, offset `+19`, *Federal Reserve Act* `1913:6` `SEC. 2`), `38 Stat. 717` (`llsl-c63.pdf` p. 736, offset `+19`, *FTC Act* `1914:311`), `49 Stat. 620` (`llsl-c74.pdf` p. 666, offset `+46`, *Social Security Act* Title I `1935:531` `SECTION 1`), `49 Stat. 647` (`llsl-c74.pdf` p. 693, offset `+46`, **Social Security Act § 1102 `1935:531`**, `42 U.S.C. 1302`, continuation page).
- **Era 4 (`50–64 Stat.`):** `51 Stat. 4` (`llsl-c75s2.pdf` p. **10**, offset `+6`, *Federal Credit Union Act* amendment `1937:3`), `54 Stat. 789` & `54 Stat. 847` (`llsl-c76s2-s3.pdf` pp. 823 & 881, offset `+34`, *Investment Company Act* Title I `SEC. 1` & *Investment Advisers Act* Title II `SEC. 201`, `1940:686`), `60 Stat. 237` (`llsl-c79s2.pdf` p. 264, offset `+27`, *APA* `1946:324` `SEC. 1`), `60 Stat. 755` (`llsl-c79s2.pdf` p. 782, offset `+27`, *Atomic Energy Act* `1946:724` `SEC. 1`), `62 Stat. 1155` (`llsl-c80s2.pdf` p. 1185, offset `+30`, *Federal Water Pollution Control Act* `1948:758` `SEC. 2`).

---

## Part 2 — `id.loc.gov` Corporate Name Authorities (`LCNAF`) Alignment for Federal Agencies

### 2.1 Existing `RefSpec` External-Link Baselines Audited First

1. **Pinned August 2026 `lcsh-externallinks-2026-08-15.nt.zip` (`sha256:7d279d69c6920b41a579634a84a1b31ff73af764345fe51df3f7c480efeba9d1`) vs November 2026 `<lccn>.madsrdf.json` graphs:**
   - `lc_external_links.py` filters `external_links.nt` to `http://id.loc.gov/authorities/subjects/` (`802,592` assertions), leaving **`2,018,402` LCNAF assertions** (`1,418,942` to OCLC FAST, `425,540` to Wikidata, including `13,454` assertions targeting endpoints labeled `"United States"` / `"U.S."`) unread.
   - **`54 / 54` (`100.0%`)** of the verified federal corporate LCCNs in this study are already present in that pinned August 2026 ZIP: in that August snapshot **`53 / 54` (`98.1%`)** carry OCLC FAST links and **`23 / 54` (`42.6%`)** carry Wikidata links, whereas in the November 2026 `<lccn>.madsrdf.json` graphs **`50 / 54` (`92.6%`)** carry `closeExternalAuthority` Wikidata QIDs (and the same `53 / 54` carry FAST links; only `BOEM` `no2011188069`, `MMS` `n82104764`, `HCFA` `n77009797`, and `CAB` `n79046186` still lack LC-curated Wikidata QIDs).
2. **`oclc_fast_external_links.py` (`FASTTopical.nt.zip`) holds `0` corporate headings** (OCLC distributes corporate facets separately in `FASTCorporate.nt.zip`).
3. **Two-pass streaming reader (`load_lcnaf_external_links_from_archive` / `parse_lcnaf_external_links_statements`):** Reopens the 1.85 GB ZIP member in two streaming passes (`O(retained_assertions)` memory, matching `lc_external_links.py:513`) without materializing uncompressed lines.

### 2.2 `id.loc.gov` `suggest2` Query Sensitivity & False-Friend Rates (`N = 54`)

Replaying `select_verified_lcnaf_hit()` and `parse_lcnaf_madsrdf_graph()` (which enforces `madsrdf:CorporateName` + authorized MARC `110` headings) over the **54 federal corporate entities** (`47` `AGENCY_CROSSWALK` agencies + `7` historical predecessors) and `8` negative/sensitivity probes yields:

| Query Strategy on `suggest2` (`rdftype=CorporateName`) | Top-1 Exact Match | Zero-Hit Rate | False-Friend Rate at Rank 1 | Verified False Friends Returned by `id.loc.gov` |
|---|---:|---:|---:|---|
| Bare Federal Register inverted name (`"Energy Department"`, `"Management and Budget Office"`, `"Industry and Security Bureau"`) | **`0 / 3` (`0.0%`)** | `3 / 3` (`100%`) | `0 / 3` | Left-anchored `suggest2` returns `count: 0` on inverted FR names. |
| Bare acronym (`"EPA"`, `"DOT"`, `"FS"`, `"EAB"`) | **`0 / 4` (`0.0%` top-3)** | `0 / 4` | **`4 / 4` (`100%`)** | `"EPA"` -> `Eglise protestante africaine (Cameroon)` (`n2012004205`); `"DOT"` -> `Confederação Nacional da Indústria. Divisão de Documentação Técnica` (`n79086943`), `Democrats of Texas` (`n93016385`); `"FS"` -> `Fachverband für Strahlenschutz` (`n85285376`). |
| Bare natural name (`"Environmental Protection Agency"`, `"Securities and Exchange Commission"`, `"Department of Agriculture"`) | `13 / 54` (`24.1%`) | `14 / 54` (`25.9%`) | **`27 / 54` (`50.0%`)** | `"Environmental Protection Agency"` -> `Liberia. Environmental Protection Agency` (`no2025010917`); `"Securities and Exchange Commission"` -> `Bangladesh. Securities and Exchange Commission` (`no2001015215`); `"Office of Management and Budget"` -> `Alaska. Office of Management and Budget` (`n84065964`); `"Department of Agriculture"` -> `Northern Ireland. Department of Agriculture and Rural Development` (`no2002077088`). |
| Rung 1: `"United States. <Natural Name>"` | `52 / 54` (`96.3%`) | `1 / 54` (`1.9%`) | `1 / 54` (`1.9%`) | Misses **(1)** `CMS`: `"United States. Centers for Medicare & Medicaid Services"` hits false friend `Medicare Recovery Audit Contractor Program (U.S.)` (`n2009184264`), whereas `CMS` is cataloged under direct entry `Centers for Medicare & Medicaid Services (U.S.)` (`no2001093385`); and **(2)** `EOIR`: `"United States. Executive Office for Immigration Review"` returns `0` hits because `EOIR` is subordinate to DOJ (`United States. Department of Justice. Executive Office for Immigration Review`, `n89643262`). |
| **Corporate Query Ladder + Jurisdiction/Parent Selector (`build_lcnaf_corporate_queries` + `select_verified_lcnaf_hit`)** | **`54 / 54` (`100.0%`)** | **`0 / 54` (`0.0%`)** | **`0 / 54` (`0.0%`)** | Resolves all 4 LCNAF corporate heading patterns (`United States. <Body>`, `<Body> (U.S.)`, `"Federal ..."` statutory corporations like `Federal Deposit Insurance Corporation` `n81013186`, and `United States. <Dept>. <Sub-office>`) while rejecting unqualified labels and foreign/state/sub-program traps. |

### 2.3 Crosswalk Sub-Agency Collapse & Historical-Rename / Split Hazards

1. **Six parent-collapsed codes & two defunct `confident` codes in the 47-agency `AGENCY_CROSSWALK` sample (`REF-038`):**
   - Six non-cabinet codes resolve `AGENCY_CROSSWALK.primary_slug` to a parent cabinet department (`crosswalk_parent_collapsed=True`): **`CDC`** (`no93011529` -> `health-and-human-services-department`), **`CISA`** (`no2020061910` -> `homeland-security-department`), **`USCBP`** (`no2004040772` -> `homeland-security-department`), **`BOEM`** (`no2011188069` -> `interior-department`), plus the two abolished `confident` codes **`MMS`** (`n82104764` -> `interior-department`, `crosswalk_defunct_code=True`) and **`OTS`** (`no89013654` -> `treasury-department`, `crosswalk_defunct_code=True`).
2. **Heterogeneous MADS/RDF Succession Encoding Across Reorganizations (`REF-072`):**
   LCNAF uses **successive entry** (separate LCCNs per reorganization), encoded across **three distinct patterns**:
   - **Mode A — Explicit LCCN-linked `madsrdf:hasEarlierEstablishedForm` / `madsrdf:hasLaterEstablishedForm`:**
     - `AEC` (`n78034861`) -> `{NRC (n78034875), ERDA (n78034864)}` -> `DOE` (`n78034868`, `earlier_lccns=[n78034864, n78034871]` plus unlinked blank-node `United States. Dept. of Energy`).
     - `HCFA` (`n77009797`) <-> `CMS` (`no2001093385`).
     - `INS` (`n79053784`) -> `{no2003104838 (USCIS), no2003052379 (Bureau of Customs and Border Protection -> USCBP no2004040772), no2003065384 (ICE)}`.
     - `MMS` (`n82104764`) -> `BOEMRE` (`no2010108932`) -> `BOEM` (`no2011188069`).
     - `GAO`: `General Accounting Office` (`n80126064`) <-> `Government Accountability Office` (`no2004066329`).
   - **Mode B — Corporate succession flattened into untyped `madsrdf:hasRelatedAuthority`:**
     - `HEW` (`n79006771`, `122` related) and `HHS` (`n80102594`, `156` related) have `earlier_lccns=[]` and `later_lccns=[]` (each carries an **unlinked blank-node** `hasEarlierEstablishedForm` for its pre-AACR2 `"United States. Dept. of ..."` spelling, recorded in `earlier_unlinked_labels`), while the `HEW <-> HHS` corporate succession sits undifferentiated inside `hasRelatedAuthority`.
     - `War Department` (`n79084108`, `115` related; unlinked blank-node `United States. War Dept.`) links via `hasRelatedAuthority` to `Department of the Army` (`n79071257`; unlinked blank-node `United States. Dept. of the Army`), which in turn links via `hasRelatedAuthority` to `Department of Defense` (`n79021946`, which carries explicit `earlier_lccns=[n87836258]` *National Military Establishment*). `War Department` has no direct RDF link to `Department of Defense`.
     - `GPO`: `Government Publishing Office` (`no2015002503`) links to `Government Printing Office` only via `hasRelatedAuthority` (`5` links).
   - **Mode C — Unlinked in RDF predicates (succession described only in `670` source-citation prose):**
     - `ICC` (`n80126245`, `earlier_lccns=[]`, `later_lccns=[]`, `6` related child bureaus): a `670` citation note states `"law signed 12/30/95 terminating ICC as of 1/1/96; many functions transfered to new Surface Transportation Board in Transportation Dept."`, but zero RDF predicate connects `n80126245` to `STB` (`no96011022`).
     - `CAB` (`n79046186`, `earlier_lccns=[]`, `later_lccns=[]`, `3` related): a `670` citation note describes functions taken over by the `FAA` (`"the FAA increasing took over the functions of the Civil Aeronautics Board (CAB) during the 1960s and 1970s; the CAB ceased to exist in 1984"`), with zero RDF succession link to `FAA` or `DOT` (`n79058419`).

---

## Reproduction & Verification Commands

```bash
# Regenerate all 3 canonical manifests via production parsers/selectors (requires local .cache):
/Users/mikewolfd/Work/spicy-stack/RefSpec/.venv/bin/python \
  research/evidence/loc-statutes-and-authorities-2026-11-18/scripts/build_evidence_manifests.py

# Run fast-tier offline unit tests (zero network, zero .cache dependency):
PYTHONPATH=src /Users/mikewolfd/Work/spicy-stack/RefSpec/.venv/bin/python -m pytest \
  tests/test_loc_statutes_at_large.py \
  tests/test_loc_agency_authorities.py
```

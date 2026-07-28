<!-- markdownlint-disable MD013 -->

# Source and Document Type Matrix

> **Status:** Proposed reference; not adopted
>
> **Date:** 2026-07-28
>
> **Architecture:** [Concept Tagging Architecture Research Proposal](concept-tagging-architecture-proposal-2026-07-28.md)
>
> **Vocabulary catalog:** [Source Vocabulary, Ontology, and Authority Catalog](source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md)
>
> **Scope note:** This dated research snapshot evaluates one pre-publication
> implementation and a broader candidate-source roadmap. Product identifiers,
> private endpoints, and repository-local paths were removed for publication.

## Decision

A RefSpec implementation needs a source-aware classification model, not one
flat list of things called "documents."

The current system has 17 source profiles:

- 10 source-document families eligible for the general document evaluation;
- one public-participation family that remains outside version 1;
- three container or relationship families; and
- three entity-reference families.

The roadmap describes 30 source-family entries: 10 in Tier 1, 11 in Tier 2,
eight in Tier 3, and one time-sensitive legacy rescue. Some are new sources;
others expand a current view. Some produce documents. Others produce events,
observations, entities, or links. The tagging system must not force the latter
into topical document classification.

This matrix also identifies nine missing source families and five completion
gaps in the evaluated source portfolio. Those recommendations are research
inputs, not implementation commitments.

## How to read the matrix

The status terms have narrow meanings:

- **Published** — a remotely accessible Parquet view existed during the
  2026-07-28 check. The pre-publication endpoint is intentionally omitted.
- **Local** — the profile and build path exist in this checkout, but the public
  parquet view did not.
- **Roadmap** — the evaluated roadmap proposed the source; implementation had
  not been verified.
- **Gap** — this document recommends the source; the roadmap does not yet list
  it.
- **Join only** — an implementation should reference another system's output
  instead of ingesting it as a source corpus.

The role determines what the concept system may do:

| Role | Practical meaning | Concept treatment |
| --- | --- | --- |
| Document | A source-issued text artifact or a dated observation that stands on its own | Assign zero or more subjects and entities from text evidence; preserve legal and process fields separately |
| Participation | A comment or similar public submission | Keep outside version 1; apply separate privacy, sampling, and evaluation rules before enabling |
| Container | A docket, proceeding, or case record that groups artifacts | Extract identifiers, dates, agency, stage, and links; do not force document topics |
| Entity | A person, organization, facility, account, or committee reference row | Normalize entity identity and type; do not assign document subjects |
| Observation | A measurement, status, lifecycle event, or crosswalk | Preserve typed values and provenance; tag only a separately identified text artifact |
| External join | A referenced result maintained by another system | Store the external identifier, version, and provenance; do not copy it into the source corpus by default |

In every table below, **source subtype** means the value supplied by the source.
**Proposed class** means an implementation-defined grouping that still needs
validation.
Both must be stored when normalization is useful. An unknown value remains
unknown; it is never coerced to the nearest familiar class.

### File format is separate from document type

A Rule remains a Rule whether the source publishes it as HTML, XML, PDF, or
more than one rendition. The current document pipeline applies this order:

| Rendition or transport | Current treatment |
| --- | --- |
| Source-native JSON, API structure, HTML, or XML | Preserve and parse the source's own structure first |
| Existing plain text or PDF-derived text | Use as source text with its extraction provenance |
| Text-layer PDF | Extract embedded text with `pypdf`; preserve the PDF as the source rendition |
| Image-only or scanned PDF; PNG, JPEG, TIFF, or BMP | Recognized but not handled by the Office parser; OCR remains a coverage gap |
| DOCX, PPTX, or XLSX | Supported by the optional, isolated Docling Office adapter when no better source structure exists |
| Legacy DOC, PPT, or XLS and other unrecognized attachments | Unsupported until a separate adapter and acceptance tests establish behavior |
| CSV, bulk JSON, API response, or parquet | Usually a transport for observations or entities, not a narrative document; preserve the source file and model each semantic row explicitly |

Supporting a format does not prove that every source connector retrieves and
parses that rendition. The source rows below state the text actually available
in each current view.

## Current source profiles

The source list and evaluation roles came from the evaluated implementation's
source registry and acceptance policy. Row counts and observed subtype values
are from the remotely accessible Parquet snapshot checked on 2026-07-28.

| # | Source and profile | Semantic unit and source subtype | Role | Text available now | Concept treatment and primary joins | Availability |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | `dockets` — `regulations-docket-v2` | Regulations.gov docket; `Rulemaking` or `Nonrulemaking` | Container | Title and sometimes an abstract | Keep docket type, agency, Regulation Identifier Number (RIN), and dates as structured fields. Use `docket_id` to connect documents and comments. Do not evaluate the docket as document text. | Published; 276,326 rows |
| C02 | `documents` — `regulations-document-v2` | Docket document; six observed raw types, including rules, notices, supporting material, and public-submission stubs | Document | Title, attachment metadata, and extracted PDF text when extraction succeeds; no optical character recognition (OCR) for image-only PDFs | Apply subject and entity tagging to available text. Preserve `document_type` as genre, dates as process metadata, and `docket_id`, RIN, and Federal Register number as joins. | Published; 1,988,780 rows |
| C03 | `comments` — `regulations-comment-v1` | Public comment or submission; three observed raw types | Participation | Comment body and extracted attachment text when available; scanned attachments can remain empty | Outside concept-tagging version 1. Join through `docket_id`; retain privacy and aggregation safeguards before any later classifier or entity analysis. | Published; 25,342,748 rows |
| C04 | `federal_register` — `federal-register-document-v1` | Federal Register document; `Notice`, `Rule`, `Proposed Rule`, or `Presidential Document`, with presidential subtypes | Document | Title and abstract in the table; URLs to HTML, body HTML, and PDF, but body text is not materialized in the published view | Use official Federal Register topics as source-assigned evidence for Rules and Proposed Rules. If added, store Notice `toc_subject` values as action or genre metadata, not topical truth. Join by document number, docket ID, RIN, and Code of Federal Regulations (CFR) citation. | Published; 800,063 rows |
| C05 | `unified_agenda` — `unified-agenda-observation-v1` | One RIN in one agenda edition; five rule stages, two publication statuses, and five priority values observed | Document | Title, abstract, timetable, legal authority, CFR references, and process metadata | Tag the described regulatory action when the abstract supports it. Keep stage, priority, edition, timetable, RIN, CFR, and authority values deterministic. Join chiefly by RIN. | Published; 3,954 rows |
| C06 | `cfr_sections` — `cfr-section-v1` | GovInfo CFR structural record; five raw structure values observed | Document | Current published scope is metadata and citations, not full regulatory text | Treat CFR identity and hierarchy as legal metadata. When available, use the CFR List of Subjects only as candidate-ranking evidence. Full subject assignment requires source text. | Published; 265,774 rows |
| C07 | `congress_bills` — `congress-bill-v1` | One Congress.gov list record; eight standard bill or resolution types and one anomalous value observed | Document | Title and latest action only; no bill detail, version text, amendments, or summaries in the current list-level view | Prefer Congressional Research Service (CRS) subjects when text supports them. Keep Congress, chamber, bill type, action, and Public Law number structured. Join by `bill_id` and `pl_number`. | Published; 192,141 rows |
| C08 | `sam_entities` — `sam-entity-v1` | Active System for Award Management entity | Entity | Names, Unique Entity ID (UEI), registration, industry, location, and organization metadata; the published `entity_type_desc` is entirely null | Run entity resolution only. Join by UEI, Commercial and Government Entity code, name, North American Industry Classification System code, and geography. | Published; 885,266 rows |
| C09 | `lobbying_filings` — `lobbying-filing-v1` | Lobbying Disclosure Act registration, report, amendment, or termination; 34 raw codes observed | Document | Client, registrant, lobbying issue descriptions, government entities, and structured child records | Tag issue-description text; normalize client and registrant separately as entities. Keep filing type, period, and status as process metadata. | Published; 284,651 rows |
| C10 | `fec_committees` — `fec-committee-v1` | Federal Election Commission committee or noncommittee filer; 16 non-null human-readable types observed | Entity | Committee name, type, designation, party, sponsor organization type, and linked candidate IDs | Run entity normalization only. Join by committee ID, candidate ID, name, party, and state. | Published; 89,123 rows |
| C11 | `gao_reports` — `gao-report-v1` | Government Accountability Office product; current ingest assigns `Report` | Document | Title and feed abstract; the recent-products feed does not supply report body, structured agency tags, or topic tags | Tag the abstract with general subjects and entities, but record that evidence depth is limited. Join by report ID, agency after enrichment, and cited laws or programs after extraction. | Published; 50 rows |
| C12 | `crs_reports` — `crs-report-v1` | Congress.gov CRS product; five source categories observed | Document | List-level metadata only; no full report text or edition history in the current view | Use CRS concepts as a preferred legislative subject source only when supported by the artifact. Join by report ID and, after enrichment, bills and hearings. | Published; 13,981 rows |
| C13 | `court_opinions` — `court-opinion-v1` | One official Supreme Court PDF package; `official-opinion-package` | Document | Official PDF and embedded text extracted with `pypdf`; no OCR | Tag the package text. Preserve the package boundary: it may contain a lead opinion, concurrence, or dissent, but do not infer separate authored opinions from layout. Join by docket number, citation, case, and challenged action when evidence exists. | Local; public parquet returned 404 |
| C14 | `court_dockets` — `court-docket-v1` | CourtListener/RECAP case docket; all current rows are nature-of-suit 899 Administrative Procedure Act review or appeal, with spelling variants | Container | Case and party metadata; no pleading, brief, docket-entry, or opinion text in the current view | Canonicalize nature-of-suit spelling while preserving raw text. Use the docket as litigation context, not a document. Add explicit rule-to-case links only with evidence. | Published; 7,629 rows |
| C15 | `usaspending_recipients` — `usaspending-recipient-v1` | Federal-award recipient at parent, child, or standalone rollup level | Entity | Recipient identity and aggregate award amount; no award document text | Run entity resolution only. Join by UEI, legacy Data Universal Numbering System number, name, and recipient level. | Published; 101,184 rows |
| C16 | `fcc_proceedings` — `fcc-proceeding-v1` | Federal Communications Commission proceeding; rulemaking, docket, and one unresolved raw code are observed | Container | Proceeding description, bureau, status, and comment-window dates | Keep proceeding type and dates as process metadata. Join filings by proceeding number. Do not assign document topics to the container. | Published; 21,607 rows |
| C17 | `fcc_filings` — `fcc-filing-v1` | Electronic Comment Filing System submission; 54 raw submission descriptions observed | Document | Full inline text for express comments; attachment URLs and page counts for document filings, but no extracted attachment body in the base view | Separate public-participation filings from agency issuances and procedural filings before evaluation. Tag only available source text; normalize filers, authors, law firms, and bureaus separately. | Published; 53,640 rows |

### Exact current subtype catalog

This catalog records exact case and spelling from the public snapshot. Counts
show prevalence, not a stable vocabulary guarantee.

#### Regulations.gov

| View and field | Observed values |
| --- | --- |
| `dockets.docket_type` | `Nonrulemaking` (213,858); `Rulemaking` (62,468) |
| `documents.document_type` | `Other` (724,942); `Supporting & Related Material` (713,163); `Notice` (395,401); `Rule` (103,227); `Proposed Rule` (51,674); `Public Submission` (373) |
| `comments.document_type` | `Public Submission` (25,342,140); `Other` (493); `Supporting & Related Material` (115) |

`Other` and `Supporting & Related Material` account for 1,438,105 of
1,988,780 `documents` rows, or 72.3%. Those values are too broad to drive a
source-specific classifier. Preserve them, then add a separate normalized type
from attachment title, media type, agency metadata, and verified content.

#### Federal Register

| Field | Observed values |
| --- | --- |
| `document_type` | `Notice` (637,156); `Rule` (94,948); `Proposed Rule` (60,747); `Presidential Document` (7,212) |
| `subtype` | null (792,856); `Proclamation` (3,785); `Executive Order` (1,293); `Memorandum` (730); `Notice` (725); `Determination` (600); `Other` (58); `Presidential Order` (16) |

`document_type` is genre metadata. For Notices, subject concepts must come
from title, abstract, body, or other source evidence, not from an action-like
table-of-contents label.

#### Unified Agenda

| Field | Observed values |
| --- | --- |
| `rin_status` | `Previously Published in The Unified Agenda` (2,835); `First Time Published in The Unified Agenda` (1,119) |
| `rule_stage` | `Proposed Rule Stage` (1,437); `Final Rule Stage` (985); `Long-Term Actions` (808); `Completed Actions` (628); `Prerule Stage` (96) |
| `priority_category` | `Substantive, Nonsignificant` (2,190); `Other Significant` (1,275); `Economically Significant` (345); `Info./Admin./Other` (101); `Routine and Frequent` (41); null (2) |

These values describe process and priority. They are not subjects.

#### CFR structure

`cfr_sections.structure_level` contains `CONTENT` (215,231), `NODE` (38,497),
`TOC` (8,262), `APPENDIX` (3,771), and `INDEX` (13).

The table documentation gives semantic examples such as `SECTION`, `PART`, and
`APPENDIX`, while the live source exposes mostly transport-level values. The
semantic mapping is therefore unvalidated. Preserve `structure_level_raw` and
derive a separate legal level only from verified GovInfo hierarchy fields.

#### Congressional material

`congress_bills.bill_type` contains:

- `hr` (109,975), `s` (35,159), `hres` (17,455), and `sres` (8,965);
- `hjres` (9,201), `sjres` (1,987), `hconres` (7,389), and `sconres` (2,004);
- `cen_doc_h` (6), an anomalous value that must remain unclassified until its
  source meaning is verified.

The eight standard codes distinguish bills, joint resolutions, concurrent
resolutions, and simple resolutions by chamber. They do not identify bill
versions such as introduced, engrossed, or enrolled.

#### Lobbying Disclosure Act filings

The live table contains registration codes `RR` and `RA`, plus these
quarter-based families for quarter `n` from 1 through 4:

| Code form | Meaning |
| --- | --- |
| `Qn` | Quarterly activity report |
| `QnY` | Quarterly report with no activity |
| `nT` | Termination |
| `nTY` | Termination with no activity |
| `nA` | Amendment |
| `nAY` | Amendment with no activity |
| `n@` | Termination amendment |
| `n@Y` | Termination amendment with no activity |

All 34 observed codes are therefore:

`RR`, `RA`, `Q1`, `Q2`, `Q3`, `Q4`, `Q1Y`, `Q2Y`, `Q3Y`, `Q4Y`, `1T`,
`2T`, `3T`, `4T`, `1TY`, `2TY`, `3TY`, `4TY`, `1A`, `2A`, `3A`, `4A`,
`1AY`, `2AY`, `3AY`, `4AY`, `1@`, `2@`, `3@`, `4@`, `1@Y`, `2@Y`,
`3@Y`, and `4@Y`.

The official source vocabulary also defines mid-year forms (`MM`, `MMY`,
`MT`, `MTY`, `MA`, `MAY`, `M@`, `M@Y`) and year-end forms (`YY`, `YYY`,
`YT`, `YTY`, `YA`, `YAY`, `Y@`, `Y@Y`), none of which appeared in the
checked table. Source vocabulary and observed values must remain separate.

#### Federal Election Commission committees

`fec_committees.committee_type_full` contains these 16 non-null values:

- `House`; `Senate`; `Presidential`; `Delegate Committee`;
- `PAC - Nonqualified`; `PAC - Qualified`;
- `Super PAC (Independent Expenditure-Only)`;
- `Hybrid PAC (with Non-Contribution Account) - Nonqualified`;
- `Hybrid PAC (with Non-Contribution Account) - Qualified`;
- `Party - Nonqualified`; `Party - Qualified`;
- `National Party Nonfederal Account`;
- `Independent expenditure filer (not a committee)`;
- `Single Candidate Independent Expenditure`;
- `Communication Cost`; and
- `Electioneering Communication`.

There are also 31 null rows. Keep the source's code, full label, designation,
and organization type; do not collapse all political entities into "PAC."

#### Reports and judicial context

| View and field | Observed values |
| --- | --- |
| `gao_reports.report_type` | `Report` (50) |
| `crs_reports.report_type` | `Reports` (7,288); `Posts` (3,344); `Resources` (3,159); `Testimony` (96); `Infographics` (94) |
| `court_opinions.opinion_type` | Local builder value `official-opinion-package`; no public snapshot |

`Posts`, `Resources`, `Testimony`, and `Infographics` are distinct CRS products,
not report subtypes. The acceptance and evaluation sets should either admit
each product deliberately or exclude it explicitly.

All 13 `court_dockets.nature_of_suit` values refer to nature-of-suit 899,
Administrative Procedure Act review or appeal of an agency decision:

| Exact raw value | Rows |
| --- | ---: |
| `899 Other Statutes: Administrative Procedures Act/Review or Appeal of Agency Decision` | 4,133 |
| `899 Administrative procedure act / review or appeal of agency decision` | 1,725 |
| `899 Administrative Procedure Act/Review or Appeal of Agency Decision` | 1,428 |
| `899 Other Statutes: Administrative Procedure Act/Review or Appeal of Agency Decision` | 147 |
| `899 APA Review/Appeal` | 145 |
| `899 Administrative Procedure Act / Review or Appeal of Agency Decision` | 17 |
| `899 Other Statutes: Administrative Procedures Act/ Review or Appeal of Agency Decision` | 12 |
| `899 Other Statutes: Admin. Proc. Act/Review or Appeal of Agency Decision` | 9 |
| `899 Admin Proc Act/Rvw Ag Dec (Fed Qst.)` | 5 |
| `899 Admin Proc Act/Rvw Ag Dec (US Def.)` | 3 |
| `899 Admin Proc Act/Rvw Apl Ag dec (Fd Qs` | 3 |
| `899 Admin Proc Act/Rvw Apl Ag dec (US Df` | 1 |
| `899 Other Statutes: Administrative Procedures Act/Review or Appeal of Agency Decision Jurisdiction: U.S. Government Defendant` | 1 |

#### Spending and FCC

| View and field | Observed values |
| --- | --- |
| `usaspending_recipients.recipient_level` | `C` child (36,024); `P` parent (33,991); `R` standalone (31,169) |
| `fcc_proceedings.rulemaking_or_docket` | `D` docket (16,196); `R` rulemaking (5,349); null (39); `N` (23, source meaning unresolved) |

The FCC filing descriptions below are exact raw values. The category in the
left column is a proposed implementation class, not an FCC classification.

| Proposed class | Exact `fcc_filings.submission_type` values |
| --- | --- |
| Public participation | `COMMENT`; `REPLY TO COMMENTS`; `TESTIMONY`; `STATEMENT`; `STATEMENT FOR THE RECORD`; `SUBMISSION FOR THE RECORD`; `CONGRESSIONAL CORRESPONDENCE` |
| Ex parte or correspondence | `NOTICE OF EXPARTE`; `LETTER` |
| Application, request, or waiver | `APPLICATION`; `REQUEST`; `WAIVER`; `PETITION FOR WAIVER`; `REQUEST FOR EXTENSION OF TIME` |
| Petition, review, or appeal | `APPEAL`; `APPLICATION FOR REVIEW`; `PETITION`; `PETITION FOR REVIEW`; `PETITION FOR RECONSIDERATION` |
| Complaint, response, or opposition | `COMPLAINT`; `AMENDED COMPLAINT`; `SUPPLEMENTAL COMPLAINT`; `ANSWER`; `OPPOSITION`; `PARTIAL OPPOSITION`; `REPLY`; `OPPOSITION TO PETITION FOR RECONSIDERATION`; `REPLY TO OPPOSITION TO PETITION FOR RECONSIDERATION`; `OPPOSITION TO MOTION TO STRIKE`; `OPPOSITION TO MOTION FOR PRODUCTION OF DOCUMENTS` |
| Motion or procedure | `MOTION FOR EXTENSION OF TIME`; `MOTION TO COMPEL`; `MOTION TO ENLARGE ISSUE`; `MOTION TO DISMISS`; `WITHDRAWAL` |
| Agency issuance or rulemaking | `PUBLIC NOTICE`; `ORDER`; `REPORT AND ORDER`; `MEMORANDUM OPINION AND ORDER`; `DECLARATORY RULING`; `PROPOSED RULEMAKING`; `FURTHER NOTICE OF PROPOSED RULEMAKING`; `Compliance guide` |
| Supporting, correction, or evidence | `COMPLIANCE FILING`; `OTHER`; `REPORT`; `SUPPLEMENT`; `Public Draft`; `ERRATA, ERRATUM OR ADDENDUM`; `AMENDMENT`; `BRIEF`; `SUBMISSION OF REPORT`; `EXHIBIT`; `DIRECT CASES` |

The proposed grouping separates public submissions from agency issuances and
case-like procedural filings. Validate it against the ECFS source dictionary
and a stratified sample before storing it as `submission_class`.

### Ingested or derived tables that are not document types

`comments_index` is partition metadata, and `fr_docket_links` records
relationships between existing artifacts. The source-profile registry
explicitly excludes both.

Likewise, `proceedings`, `comment_periods`, `regulatory_agenda_items`,
`agenda_item_proceedings`, `rule_targets`, `authority_edges`, concept tables,
statistics, and rollups may be essential product views, but they are derived
identities, relationships, intervals, vocabularies, or aggregates. They do not
create another copy of a source document and should not enter the document
evaluation as one.

## Candidate source families

The next three matrices preserve all 30 source-family entries in the evaluated
roadmap. The subtypes use two labels:

- **Roadmap** repeats types named by the product document.
- **Proposed** adds a classification needed for ingestion or tagging.

### Tier 1 — high value and feasible now

| # | Source family and candidate views | Unit | Types and subtypes | Role | Concept treatment and joins |
| --- | --- | --- | --- | --- | --- |
| T1-01 | Office of Information and Regulatory Affairs review pipeline — `oira_reviews`, `oira_meetings`; reginfo.gov XML or pages | Executive Order 12866 review record or meeting record | **Roadmap:** rule under review; meeting log. **Proposed:** keep review lifecycle events and meeting materials separate | Observation; a linked meeting document can be a Document | Keep review status and dates deterministic. Tag a linked rule abstract or meeting material from its own text. Join by RIN, agency, and reviewed action |
| T1-02 | Federal Register public inspection desk — `public_inspection`; official Federal Register API | Prepublication Federal Register filing | **Roadmap:** filed but not yet published. **Proposed:** reuse Federal Register genre values when the API supplies them and preserve a prepublication status | Document | Apply the Federal Register treatment, but preserve filing, scheduled-publication, and replacement links so the prepublication artifact is not mistaken for the final edition |
| T1-03 | Medicaid waivers and State Plan Amendments — `medicaid_waivers`, `medicaid_spa`; Medicaid.gov pages and PDFs | Waiver action, amendment, renewal, State Plan Amendment, or comment notice | **Roadmap:** section 1115, 1915(b), and 1915(c); application, amendment, renewal, and comment window; State Plan Amendment | Document plus Observation for lifecycle and deadlines | Use health and social-service specialist subjects plus general subjects. Keep waiver authority, state, status, effective dates, expiration, and comment window deterministic |
| T1-04 | Sub-regulatory guidance — `agency_guidance`; Centers for Medicare & Medicaid Services, Administration for Children and Families, Social Security Administration, and Education Office for Civil Rights pages | Agency guidance artifact or changed page | **Roadmap:** State Medicaid Director letter, informational bulletin, FAQ, and manual update | Document | Tag the source text; keep issuer, program, effective date, revision, supersession, and withdrawal structured. Preserve page and file versions |
| T1-05 | State legislation — `state_bills`, `state_legislators`; Open States with LegiScan as a gap filler | State bill record, sponsor or legislator record, and hearing schedule | **Roadmap:** bills, sponsors, hearing schedules. **Proposed:** represent text versions and amendments as separate document artifacts when supplied | Document for bill text; Entity for people; Observation for schedules | Apply legislative subjects to bill text. Keep jurisdiction, session, chamber, bill type, sponsor, action, and hearing time structured. Decide feed-versus-parallel ingestion with Axiom before implementation |
| T1-06 | Grants and assistance lifecycle — `grant_opportunities`, `assistance_awards`; Grants.gov and USAspending APIs | Funding opportunity, opportunity change, or assistance award flow | **Roadmap:** Grants.gov opportunities and assistance-listing-level award flows, formerly identified by Catalog of Federal Domestic Assistance numbers | Document for opportunity notices; Observation for status and award flows | Tag opportunity narrative and eligibility text. Keep assistance listing, agency, amount, geography, opening, deadline, cancellation, and award values structured |
| T1-07 | Congressional hearings — `congress_hearings`; Congress.gov API | Hearing, markup, witness list, or related hearing artifact | **Roadmap:** scheduled hearing, markup, witness list | Container or Observation for schedule; Document for notice, testimony, transcript, or report | Tag each text artifact separately. Join by Congress, chamber, committee, bill, witness entity, and date |
| T1-08 | Inspector General reports — `oig_reports`; Oversight.gov API | Office of Inspector General product | **Roadmap:** all-agency Inspector General reports. **Proposed:** retain each source product type rather than normalizing everything to `Report` | Document | Apply general subjects and entities. Keep office, agency, product number, recommendations, status, and publication date structured |
| T1-09 | Apportionments and impoundment — `apportionments`, `impoundment_decisions`; Office of Management and Budget files and GAO legal decisions | Office of Management and Budget account file or version diff; GAO legal decision | **Roadmap:** account-level apportionment, change, and Impoundment Control Act decision | Observation for account data and diffs; Document for legal decisions | Tag legal decisions and any explanatory text. Keep account, agency, assistance listing, amount, period, withholding, and change values deterministic |
| T1-10 | Agency web change monitoring — `web_changes`; targeted agency pages, following Environmental Data and Governance Initiative practice | Versioned page snapshot and content diff | **Roadmap:** guidance index, eligibility manual, or data-portal page change | Observation linked to a Document when a page contains durable source text | Tag the changed source passage, not navigation or template text. Keep URL, retrieval time, content digest, change type, and predecessor deterministic |

### Tier 2 — high value with moderate effort

| # | Source family and candidate views | Unit | Types and subtypes | Role | Concept treatment and joins |
| --- | --- | --- | --- | --- | --- |
| T2-01 | District demographics — `district_demographics`, `geo_crosswalks`; Census API and static geography crosswalks | Census measure or geography mapping | **Roadmap:** American Community Survey district demographics; ZIP-to-district and county-to-district crosswalks | Observation | No topical document tags. Preserve measure, universe, estimate, margin of error, vintage, geography, and mapping method |
| T2-02 | Court opinions and litigation linkage — extension of `court_opinions` and `court_dockets`; official Supreme Court PDFs plus CourtListener/RECAP | Broader judicial opinion and evidence-backed rule-to-case link | **Roadmap:** broader opinions and a rule-to-case crosswalk. **Proposed:** split majority, plurality, concurrence, dissent, order, and judgment only when the source supplies those boundaries | Document plus Container links | Tag opinion text. Keep court, docket, citation, author, disposition, date, and challenged-action evidence structured |
| T2-03 | Paperwork Reduction Act and Information Collection Requests — `icr_actions`, `dataset_status`; dataindex.us and reginfo.gov | Information Collection Request action, comment opportunity, or dataset-loss signal | **Roadmap:** form, survey, or program-report change; survey open for comment; dataset-loss signal | Observation; Document for notices and supporting statements | Tag source notices and supporting documents. Keep Office of Management and Budget control number, agency, action, burden, deadline, and dataset status deterministic |
| T2-04 | Congressional Budget Office cost estimates — `cbo_estimates`; CBO site | Cost estimate | **Roadmap:** fiscal estimate linked to a bill | Document | Tag the estimate narrative. Keep bill ID, score window, spending, revenue, mandate, and estimate date structured |
| T2-05 | Centers for Medicare & Medicaid Services provider and facility data — `cms_facilities`, `cms_staffing`, `cms_ownership`; data.cms.gov bulk files | Facility, staffing observation, or ownership link | **Roadmap:** Care Compare facility; Payroll-Based Journal staffing; ownership chain | Entity and Observation | Normalize facilities and owners; do not force document subjects. Join by Centers for Medicare & Medicaid Services identifiers, ownership, address, county, state, and district |
| T2-06 | State Attorney General multistate actions — `ag_actions`; selected state office sites | Multistate suit, comment letter, or source announcement | **Roadmap:** suit and comment letter. **Proposed:** preserve press release as a source page but link the underlying complaint or letter as the primary artifact when available | Document | Tag complaint or letter text. Keep offices, states, target agency or entity, court or docket, action type, and date structured |
| T2-07 | State-side waiver notices — `state_waiver_notices`; state Medicaid agency sites | State notice and comment window for a Medicaid waiver action | **Roadmap:** section 1115 or 1915 state notice and participation period | Document plus Observation | Use the Medicaid treatment from T1-03. Link the state notice to the later federal waiver action without collapsing their separate comment periods |
| T2-08 | Federal workforce and vacancies — `agency_headcount`, `appointee_vacancies`; Office of Personnel Management FedScope and PLUM Act data | Workforce measure or position status | **Roadmap:** agency/component headcount; appointee or vacancy; acting versus confirmed status | Observation and Entity | No document-topic assignment. Keep agency hierarchy, position, incumbent, appointment type, status, effective period, workforce measure, and source vintage |
| T2-09 | Single audits — `single_audits`; Federal Audit Clearinghouse API | Audit submission, report, finding, or questioned-cost record | **Roadmap:** Federal Audit Clearinghouse grantee audit findings | Document for reports and findings; Observation for amounts and status | Tag finding narratives and entities. Keep auditee UEI, agency, assistance listing, program, finding type, amount, year, and resolution status structured |
| T2-10 | CRS full text and history — extension of `crs_reports`; EveryCRSReport plus the official CRS portal | CRS product edition | **Roadmap:** full text, machine-readable index, pre-2018 coverage, and report versions from EveryCRSReport, verified against the official portal | Document | Preserve the five current product categories and every source edition. Apply CRS subjects only to evidence from the matching edition |
| T2-11 | Legislator and committee reference — `legislators`, `committee_assignments`; `unitedstates/congress-legislators` and `openstates/people` | Federal or state legislator and dated committee assignment | **Roadmap:** roster, stable identifier, and committee assignment | Entity and Observation | No document-topic assignment. Join bills, hearings, sponsors, chamber, committee, jurisdiction, and effective dates |

### Tier 3 and time-sensitive legacy rescue

| # | Source family and candidate views | Unit | Types and subtypes | Role | Concept treatment and joins |
| --- | --- | --- | --- | --- | --- |
| T3-01 | State administrative registers — `state_regulations`; jurisdiction-specific register sites | State register issue or state regulatory artifact | **Roadmap:** administrative-register material. **Proposed:** notice, proposed rule, final rule, emergency rule, correction, and withdrawal when the source identifies them | Document | Apply the Federal Register-style separation of subject, genre, action, and process. Preserve state, agency, citation, authority, stage, dates, and participation window |
| T3-02 | State budgets — `state_budgets`; jurisdiction-specific budget sites | Budget document and extracted line item | **Roadmap:** state budget document with program line items | Document plus Observation | Tag budget narrative; keep fund, agency, program, fiscal year, amount, status, and geography structured |
| T3-03 | Modeled program-enrollment estimates — `district_program_estimates`; PolicyEngine or a documented local model | Published estimate and methodology version | **Roadmap:** district-level home- and community-based services, nutrition, and caregiver estimates | Observation | No source-document topic tags unless a separate methodology artifact is ingested. Keep model, assumptions, geography, measure, uncertainty, and version |
| T3-04 | Cross-corpus entity graph; current views plus ProPublica 990 and OpenFEC reference spines | Evidence-backed identity link across current sources | **Roadmap:** organization resolution across comments, lobbying, SAM, spending, nonprofit filings, and campaign finance | Entity and External join | Store identifiers, match method, evidence, confidence, and role. Consume ProPublica 990 and OpenFEC as reference spines rather than copying whole corpora |
| T3-05 | Home- and community-based services waitlists — `hcbs_waitlists`; KFF surveys, state pages, and attested contributions | Attested waitlist observation | **Roadmap:** annual survey value, state-agency page value, or verified field observation | Observation | Keep state, program, population, measure, period, method, source, and attribution. Tag only separately preserved narrative documents |
| T3-06 | Social Security Administration operations — `ssa_service_metrics`; source set not yet selected | Service-delivery measure or facility event | **Roadmap:** field-office closure, wait time, disability backlog | Observation | Keep office, geography, service, metric, period, and change structured. Link source notices as documents when available |
| T3-07 | Federal advisory committees — `faca_committees`; General Services Administration exports | Committee, charter, membership record, or meeting event | **Roadmap:** charter, membership, meeting cadence, purge, or disbandment signal | Entity, Document, and Observation | Tag charter and meeting documents; normalize members and committees; keep authorization, term, status, agency, and dates structured |
| T3-08 | State lobbying registrations — `state_lobbying`; jurisdiction-specific disclosure sites | State registration or disclosure filing | **Roadmap:** records from fragmented state disclosure regimes. **Proposed:** registration, periodic report, amendment, and termination where the state defines them | Document plus Entity | Reuse federal lobbying separation of filing, client, registrant, issue, government target, period, and status; preserve jurisdiction-specific raw codes |
| L-01 | Legacy dataset rescue — `legacy_program_reports`; the at-risk [AGing, Independence, and Disability (AGID) Program Data Portal](https://acl.gov/news-and-events/announcements/agid-has-new-name), ombudsman archives, and adult-maltreatment portals | Immutable snapshot of an at-risk report, file, portal export, or archive index | **Roadmap:** Older Americans Act reports, ombudsman archives, adult-maltreatment data | Document or Observation according to the source artifact | Snapshot bytes and source pages first. Preserve original format, retrieval time, digest, source URL, title, period, and any known custodian before modeling |

## Missing from the roadmap

### Completion gaps in current source families

These gaps do not require a new subject taxonomy. They require better source
text, versions, and source-native types.

| # | Gap | Missing types or content | Why it matters |
| --- | --- | --- | --- |
| E01 | Regulations.gov attachment normalization | Attachment title, media type, source subtype, primary-versus-supporting role, extracted Office-document text, and OCR for scanned files | Most `documents` rows use `Other` or `Supporting & Related Material`; title-only classification hides environmental reviews, analyses, transcripts, guidance, and forms |
| E02 | Federal Register body materialization | Native body HTML or XML, section structure, corrected or withdrawn versions, and prepublication-to-publication lineage | Rules and notices need their actual text for reliable evidence, not only title and abstract |
| E03 | CFR text and point-in-time history | Native eCFR XML, title/part/subpart/section/appendix hierarchy, effective intervals, amendment history, and a verified mapping from transport structure to legal level | CFR citations are central joins, but the current table is metadata-only and its live `structure_level` values do not match the documented semantic examples |
| E04 | Congressional document completeness | Bill text editions, summaries, amendments, committee reports, written testimony, votes, nominations, and enacted-law links | The current bill view is list-level. It cannot support provision-level subjects, legal change tracking, or a complete legislative history |
| E05 | Existing report, court, and FCC text | GAO report bodies, CRS editions and bodies, published court opinion packages, broader opinions, FCC attachment text, and OCR where allowed | Metadata and inline snippets create uneven evidence depth and systematically exclude document-only filings |

### New source and document families

| # | Recommended source family | Document types and subtypes | Role and treatment | Practical value |
| --- | --- | --- | --- | --- |
| G01 | Enacted statutes and codified law | Enrolled bill; Public Law; Private Law; Statutes at Large page or section; United States Code title, chapter, and section; amendment and repeal history | Document. Keep legal identity and effective history deterministic; tag source text. Use [GovInfo](https://www.govinfo.gov/developers) and official House or Senate law revision sources | Closes the gap between a bill, its enacted law, the authority cited by a rule, and current codified law |
| G02 | Federal dockets outside Regulations.gov and ECFS | Securities and Exchange Commission proposed and final rules, releases, comments, petitions, applications, orders, and self-regulatory-organization filings; Federal Energy Regulatory Commission notices, applications, interventions, comments, protests, orders, rehearing requests, and environmental documents; then audit Federal Reserve, Commodity Futures Trading Commission, and Nuclear Regulatory Commission systems | Container plus Document. Preserve each system's raw filing type; normalize only with a source-specific map | Major regulators use systems that the current docket universe does not cover. Start with [SEC rulemaking](https://www.sec.gov/rules-regulations) and [FERC eLibrary](https://www.ferc.gov/elibrary-frequently-asked-questions-faqs) |
| G03 | Agency adjudication and enforcement | Administrative complaint; charging document; answer; motion; brief; hearing transcript; administrative law judge decision; initial decision; final agency order; consent order or decree; settlement; civil penalty; compliance or termination order | Document plus Container. Separate allegation, argument, decision, and settlement genres before tagging | Regulations show general duties; adjudication and enforcement show how agencies apply them to specific facts |
| G04 | Litigation filings and docket events | Complaint or petition for review; answer; brief; motion; administrative record; stay or injunction; order; judgment; mandate; docket event | Document plus Container and Observation. Keep party role, court, stage, disposition, cited rule, and evidence-backed rule-to-case link | The current court docket metadata and Supreme Court package do not show the arguments, interim relief, or complete outcome |
| G05 | Congressional Review Act material | Agency rule submission; GAO major-rule report; GAO coverage decision; House and Senate receipt; review-window calculation; joint resolution of disapproval; presidential action | Document plus Observation. Keep statutory deadlines and rule identity deterministic | Connects final rules to congressional review, major-rule analysis, and possible nullification. GAO maintains an official [Congressional Review Act](https://www.gao.gov/legal/other-legal-work/congressional-review-act?priority=all&processed=1&type=all) surface |
| G06 | Federal procurement lifecycle | Presolicitation; solicitation; amendment; special notice; sources-sought notice; sole-source notice; award notice; contract; task or delivery order; modification; subcontract record | Document for notices and terms; Observation for lifecycle and amounts; Entity for vendors | Adds a second major path by which policy becomes implementation. Start with [SAM.gov opportunities](https://sam.gov/opportunities) and join awards through [USAspending](https://api.usaspending.gov/docs/endpoints) |
| G07 | Federal budget and appropriations documents | President's Budget; Budget Appendix; Analytical Perspectives; agency congressional budget justification; supplemental request; rescission; appropriations bill; committee report; explanatory statement; continuing resolution | Document plus Observation for accounts and amounts. Preserve fiscal year, account, agency, program, bill, status, and version | Explains the funding decisions upstream of apportionment, grants, staffing, and service changes. Use official [OMB budget](https://www.whitehouse.gov/omb/information-resources/budget/) and [supplemental request](https://www.whitehouse.gov/omb/information-resources/legislative/supplementals-amendments-and-releases/) collections |
| G08 | Complete congressional proceedings | Bill editions; floor and committee amendments; committee reports; hearing notices; written testimony; transcripts; roll-call and voice votes; nominations; treaties; enactment actions linked to G01 | Document plus Observation for actions and votes. Preserve Congress, chamber, committee, calendar, version, and related measure | Extends the roadmap's bill, hearing, and cost-estimate entries into a coherent legislative record. Use the official [Congress API](https://api.congress.gov/) and GovInfo |
| G09 | State executive and agency actions | Governor executive order; emergency directive; state agency guidance; bulletin; waiver; emergency order; enforcement order; state plan or manual update | Document. Preserve jurisdiction, issuing authority, legal basis, status, effective interval, and supersession | State policy often changes without a bill or administrative-register rule, especially during emergencies and program administration |

Recommended order: complete E01–E05 while adding Tier 1 roadmap sources, then
prioritize G01–G05 because they close the largest legal-history and
participation gaps. Run a source audit before choosing agencies within G02 or
states within G09.

## External joins, not ingestion corpora

| System | External artifact or result | Implementation action |
| --- | --- | --- |
| The Axiom Foundation | Conditional `axiom-corpus` named-release text; executable RuleSpec YAML; `axiom-bills` federal and state bill data; `rulespec-us` reverse index from provision paths to dependent rule encodings | Keep Axiom as an external join by default. Preserve the join design now; consume a pinned corpus or reverse index only after target-specific coverage, provenance, reproducibility, access, and license gates pass in the [Axiom ecosystem assessment](axiom-ecosystem-analysis-2026-07-28.md). Decide feed-versus-parallel ownership before building state bills. Send evidence-backed regulatory change triggers only through a validated citation-path crosswalk |
| PolicyEngine | Versioned tax and benefit rules, simulation results, and impact estimates by geography | Store the model, reform, version, geography, and result reference. Join from a rule or bill; do not present modeled output as source-document fact |
| Formspec-Labs `rulespec` | Content identity, provenance, warrant, use-permission, and supersession information | Emit or reference standing metadata for curated artifacts. Do not treat governance metadata as source text or a topical concept |

ProPublica nonprofit filings, OpenFEC reference data, EveryCRSReport, and
dataindex.us follow the same consume-and-join rule where the roadmap names
them as external spines or feeds. If an implementation preserves an official source
artifact that those services index, that artifact remains a source document;
the external index remains a reference.

## Cross-source rules

1. Preserve `source_type_raw` exactly. Store any normalized
   `document_class` separately with the mapping version and evidence.
2. Identify the semantic unit before tagging it. A docket, party, facility,
   status event, or estimate is not a document merely because it has text
   fields.
3. Keep general subjects, specialist subjects, regulated entities, legal
   metadata, process metadata, and action or genre values separate.
4. Treat each source-issued version as a distinct artifact linked to its
   predecessor. Multiple PDF, HTML, XML, and text renditions of the same
   source version are renditions, not separate semantic documents.
5. Split compound packages only when the source supplies reliable boundaries.
   Preserve a Supreme Court opinion package, omnibus report, or attachment
   bundle intact when page layout alone would require guessing.
6. Apply source-specific subtype maps before retrieval. Never use a single
   generic `Other` class to select a concept pool.
7. Require exact evidence for every assigned subject or entity. If the
   registry lacks a supported concept, preserve a local concept or abstain.
8. Keep public comments outside version 1. Any later inclusion needs its own
   privacy review, sampling design, subtype handling, and evaluation set.
9. Record source URL, retrieval time, content digest, parser, parser version,
   and extraction result for every text artifact.
10. Test each source family separately, then test cross-source product queries.
    A global score can hide a failure on a small but important document type.

## Completeness ledger

| Scope | Expected | Represented here |
| --- | ---: | ---: |
| Current `SOURCE_PROFILES` | 17 | 17 |
| Tier 1 roadmap families | 10 | 10 |
| Tier 2 roadmap families | 11 | 11 |
| Tier 3 roadmap families | 8 | 8 |
| Legacy rescue family | 1 | 1 |
| Adjacent named ecosystems | 3 | 3 |
| Recommended completion gaps | 5 | 5 |
| Recommended new source families | 9 | 9 |

This ledger checks inventory coverage, not implementation. Roadmap, gap, and
join-only rows remain proposals until a source profile, schema, provenance
receipt, tests, and a published dataset establish otherwise.

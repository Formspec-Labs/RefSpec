<!-- markdownlint-disable MD013 -->

# Source Vocabulary, Ontology, and Authority Catalog

> **Status:** Proposed research catalog; not adopted
>
> **Date:** 2026-07-28
>
> **Source scope:** [Source and Document Type Matrix](source-document-type-matrix-2026-07-28.md)
>
> **Architecture:** [Concept Tagging Architecture Proposal](concept-tagging-architecture-proposal-2026-07-28.md)
>
> **Adjacent-system assessment:** [Axiom ecosystem assessment](axiom-ecosystem-analysis-2026-07-28.md)
>
> **Evidence:** [Regulatory and legal](evidence/source-vocabulary-research-2026-07-28/01-regulatory-legal.md);
> [legislative and fiscal](evidence/source-vocabulary-research-2026-07-28/02-legislative-fiscal.md);
> [health, social services, and specialist domains](evidence/source-vocabulary-research-2026-07-28/03-health-domain.md);
> [roadmap feeds and reference spines](evidence/source-vocabulary-research-2026-07-28/04-roadmap-reference-feeds.md)

The first three evidence reports contain the original domain research. Report
04 is a later follow-up: an independent catalog review found that seven
provider feeds named in the source matrix lacked explicit authority, access,
licensing, and verification decisions. It records that provider due diligence
separately because the feeds support discovery, gap filling, or identity
matching rather than vocabulary selection.

The Axiom assessment supplies the repository-specific evidence and adoption
gates for the Axiom rows below. The domain reports do not treat Axiom's legal
paths, executable symbols, or rule categories as subject-vocabulary evidence.

## Decision

Use a small, governed general-subject core and add specialist subject modules
only when a document needs them. Keep source-assigned topics as evidence.
Keep identifiers, process codes, document types, and legal citations as
structured fields. Use ontologies and document schemas to describe
relationships and structure; do not put their class names into the subject
classifier by default.

The first pilot should use:

- the Federal Register Thesaurus and Congressional Research Service (CRS)
  Legislative Subject Terms as the general-subject candidate pool;
- CRS Policy Areas as broad navigation labels;
- the Code of Federal Regulations (CFR) List of Subjects as source-specific
  candidate-ranking evidence;
- Medical Subject Headings (MeSH), National Agricultural Library Thesaurus
  (NALT) Core, General Multilingual Environmental Thesaurus (GEMET), and a
  freshness-verified NASA Thesaurus as separately activated specialist-module
  pilots; and
- source-native identifiers and code lists for entities, geography, legal
  identity, fiscal accounts, programs, and process state.

This is a research recommendation, not an adoption claim. Each resource still
needs a versioned acquisition record, license review, source-family evaluation,
and an untouched product-level holdout before it can become a production
dependency.

## Resource kinds

The source matrix needs five different kinds of controlled resources. Treating
them as one list would mix topics with facts about documents and entities.

| Kind | What it controls | Examples | Implementation use |
| --- | --- | --- | --- |
| Subject thesaurus or taxonomy | Topics used to index or retrieve text | Federal Register Thesaurus, CRS Legislative Subject Terms, MeSH | Candidate generation, source-assigned evidence, navigation, and evaluated subject assignment |
| Ontology | Classes and named relationships in a data model | World Wide Web Consortium (W3C) Organization Ontology, W3C Provenance Ontology (PROV-O) | Represent organizations, roles, changes, sources, and derivation; not a default subject list |
| Identifier authority | Stable identity for a real entity or legal artifact | Regulation Identifier Number, Unique Entity ID, National Provider Identifier | Entity normalization and cross-source joins |
| Code list or classification | A bounded value set for a specific field | North American Industry Classification System, Federal Information Processing Standards state codes, budget functions | Deterministic metadata; optionally a retrieval signal, never automatic topical truth |
| Document or data schema | Structure and field meaning | United States Legislative Markup, Akoma Ntoso, Data Catalog Vocabulary | Preserve source structure and publish interoperable metadata; not candidate labels |

One resource can serve more than one technical purpose, but every stored value
must retain its source vocabulary, version, resource kind, and assignment
method. An identical label from two sources remains two concepts until an
explicit, reviewed mapping relates them.

## Shared representation and metadata standards

| Standard | Verified scope | Recommended use | Decision |
| --- | --- | --- | --- |
| [Simple Knowledge Organization System (SKOS)](https://www.w3.org/TR/skos-reference/) | World Wide Web Consortium (W3C) Recommendation for concept schemes, preferred and alternate labels, broader, narrower, related, and cross-scheme mappings | Canonical representation for thesauri and mappings; preserve source identifiers and scheme membership | Use |
| [PROV-O](https://www.w3.org/TR/prov-o/) | W3C Recommendation for interoperable provenance using entities, activities, agents, and derivation relationships | Represent retrieval, parsing, mapping, review, and supersession evidence | Use as a mapping target; keep the existing project receipt model authoritative |
| [Dublin Core Metadata Terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/) | Maintained metadata properties for title, creator, date, identifier, source, rights, subject, type, versions, and relationships | Crosswalk common artifact metadata for export | Use as an export crosswalk, not as the internal source schema |
| [Data Catalog Vocabulary 3 (DCAT 3)](https://www.w3.org/TR/vocab-dcat-3/) | 2024 W3C Recommendation for datasets, distributions, data services, catalogs, versions, access, and checksums | Describe published datasets and distributions | Use for catalog publication; it does not classify source documents |
| [W3C Organization Ontology](https://www.w3.org/TR/vocab-org/) | W3C model for organizations, units, memberships, posts, roles, sites, and change events | Crosswalk agency and organization relationships after identity resolution | Pilot; source-native organization identifiers remain authoritative |
| [United States Legislative Markup (USLM)](https://uscode.house.gov/download/resources/USLM-User-Guide.pdf) | Office of the Law Revision Counsel XML model for the United States Code, bills, resolutions, statutes, and related legislative material | Preserve official legislative structure when a source supplies USLM | Use source-native USLM; do not translate it merely to standardize names |
| [Akoma Ntoso 1.0](https://docs.oasis-open.org/legaldocml/akn-core/v1.0/akn-core-v1.0-part1-vocabulary.html) | OASIS XML standard for parliamentary, legislative, and judicial documents across jurisdictions | Structural comparison and export mapping where a partner requires it | Mapping only; do not replace official United States schemas |
| [European Legislation Identifier ontology](https://op.europa.eu/en/web/eu-vocabularies/eli) | European legal-resource, expression, format, lifecycle, amendment, and impact model | Compare and export legal identity/version relationships | Mapping only; United States source identifiers and version rules remain authoritative |
| [Schema.org `Legislation`](https://schema.org/Legislation) | Lightweight web-publishing type derived from the European Legislation Identifier model; the type remains in Schema.org's “new” area | Optional public-page JSON-LD | Defer as a canonical model; export only after validating each property |

SKOS is deliberately less formal than an ontology. It can represent a
thesaurus without pretending that every broader or related link is a logical
fact about the world. That distinction matches the proposed separation between
selectable subjects and the project's formal data model.

## Current registry baseline

The local `fused-concept-registry-v1` manifest records 513,236 rows:

| Scheme | Rows | Proper production role |
| --- | ---: | --- |
| General `subject` scheme | 936 | Diagnostic starting material for a governed general core |
| CRS Policy Areas | 33 | Broad navigation and grouping |
| CRS Legislative Subject Terms | 932 | Legislative subjects and general-core candidate source |
| Environmental Protection Agency non-confidential Toxic Substances Control Act inventory | 70,736 | Chemical entity normalization, not document subjects |
| Faceted Application of Subject Terminology (FAST) topical facet | 440,599 | Optional search expansion and cross-vocabulary mapping |

The manifest correctly preserves the five schemes and performs no
cross-scheme merge. The proposed architecture also rejects the combined
513,236-row pool as a production document classifier. Count and availability
alone do not establish that a resource supplies the right kind of label.

## Subject resources

### General regulatory and legislative subjects

| Resource | Verified scope and access | Recommended role | Decision and constraint |
| --- | --- | --- | --- |
| [Federal Register Thesaurus of Indexing Terms](https://www.archives.gov/files/federal-register/cfr/thesaurus.pdf) and [Federal Register Topics API](https://www.federalregister.gov/developers/documentation/api/v1#/federal-register-index-entries/get-topics) | The 2026-07-28 API snapshot returned 1,044 `thesaurus` and 6,723 `ad_hoc` topics. The public PDF yielded 702 preferred terms plus about 504 variants. The difference is unresolved. | General regulatory seed and source-assigned evidence for Rules and Proposed Rules | Pilot. Pin the PDF and API objects separately; exclude `ad_hoc` values from the governed core until reviewed. |
| [CFR List of Subjects](https://www.ecfr.gov/current/title-1/chapter-I/subchapter-A/part-18/section-18.20) | Official subject assignments connect affected CFR parts to Federal Register indexing terms. The research did not verify a separate current unique-term count. | Candidate-ranking and evaluation evidence for CFR-linked material | Use assignments with title and part provenance; do not create an unlabeled duplicate vocabulary. |
| [CRS Legislative Subject Terms](https://www.congress.gov/help/field-values/legislative-subject-terms) | Congress.gov listed 1,004 current terms. BILLSTATUS XML carries assigned terms on legislative records. | Legislative subject module and candidate source for the general core | Pilot. Preserve CRS identity and review mappings to Federal Register concepts. |
| [CRS Policy Areas](https://www.congress.gov/help/field-values/policy-area) | Congress.gov listed 32 current broad areas. Historical bulk data can include a 33rd `Commemorations` value. | Broad navigation, evaluation strata, and corpus balancing | Use with version provenance; too broad for detailed subject output. |
| [Library of Congress Subject Headings](https://id.loc.gov/authorities/subjects.html) | Large, maintained library subject authority available as linked data | Synonym and mapping reference where a human-reviewed crosswalk adds value | Mapping only. Its bibliographic scope and size make it unsuitable as the default candidate pool. |
| [Faceted Application of Subject Terminology (FAST)](https://www.oclc.org/research/areas/data-science/fast/download.html) | OCLC reports about 1.7 million headings across all facets; bulk files use the Open Data Commons Attribution License. The local topical extract has 440,599 rows. | Search expansion and reviewed cross-vocabulary mappings | Mapping only. Do not reserve classifier output slots for FAST or infer regulatory suitability from size. |
| [EuroVoc](https://op.europa.eu/en/web/eu-vocabularies/concept-scheme/-/resource?uri=http://eurovoc.europa.eu/100141) | More than 7,000 preferred concepts in 21 domains and 24 European Union languages, published in SKOS and other formats | Comparison model for governance, multilingual labels, and legal-policy classification | Benchmark and mapping reference only; do not import its European Union-centered scheme wholesale. |
| [GAO Thesaurus](https://www.gao.gov/products/oimc-99-1) | The 1998 fourth edition reports more than 2,500 terms; no current maintained edition was verified | Historical aid for Government Accountability Office archive search | Defer. Do not adopt as a current authority without a maintained successor and machine-readable source. |

Federal Register topics are useful source labels, not complete truth. A
computed 2023–2025 snapshot found topics on 10,246 of 14,076 Rules and Proposed
Rules, while a complete January 2025 check found none on Notices or
Presidential Documents. Federal Register `toc_subject` values describe
table-of-contents action or genre and remain outside the subject facet.

### Specialist subject modules

| Domain | Resource | Verified scope and access | Recommended role | Decision and constraint |
| --- | --- | --- | --- | --- |
| Health and biomedicine | [Medical Subject Headings (MeSH)](https://www.nlm.nih.gov/databases/download/mesh.html) | Official 2026 XML yielded 31,110 descriptors, 324,049 supplemental concepts, and 76 qualifiers; National Library of Medicine attribution is required | Health subject module; supplemental records can assist biomedical entity normalization | Pilot descriptors. Do not expose the full supplemental-concept set as general document subjects. |
| Agriculture, food, organisms, and rural policy | [National Agricultural Library Thesaurus (NALT)](https://lod.nal.usda.gov/nalt/en/) | NALT Core has about 14,000 concepts; the published NALT Full page reports 76,691 and its displayed facet subtotals differ from that total by 94 | NALT Core as an agriculture/food subject candidate; NALT Full mainly for mappings and typed organism, chemical, product, and place support | Pilot Core only after reconciling the exact release and conflicting CC BY 4.0 versus broader USDA public-domain/CC0 statements. |
| Agriculture and multilingual mapping | [AGROVOC](https://www.fao.org/agrovoc/) | Food and Agriculture Organization multilingual linked-data concept scheme | Crosswalk and multilingual expansion for NALT-backed subjects | Pilot as a mapping source; do not combine identifiers with NALT. |
| Environment | [EPA Enterprise Vocabulary](https://www.epa.gov/research/epa-enterprise-vocabulary) | EPA reports more than 100 topic tiers and publishes several export formats; exact current concept count and update cadence remain unverified | Environmental terminology research lead | Defer pilot inclusion until a current export, version record, maintenance evidence, and license are verified. |
| Environment | [GEMET 4.2.3](https://www.eionet.europa.eu/gemet/en/exports/rdf/latest) | European Environment Information and Observation Network multilingual environmental thesaurus in SKOS/RDF with REST services under CC BY 4.0 | Environmental subject-module candidate and crosswalk source | Pilot on United States regulatory text; require strong abstention and measure United States statutory-language gaps. |
| Energy and physical science | [DOE OSTI Semantic Thesaurus](https://www.osti.gov/dataexplorer/biblio/dataset/1668761) | Public 2020 Resource Description Framework/SKOS artifact; no newer public release or changelog was verified | Energy/science mapping research | Reject/defer canonical use until the owner provides a current, licensed, reproducible release. |
| Aerospace and space science | [NASA Thesaurus](https://sti.nasa.gov/nasa-thesaurus/) | NASA reports more than 18,400 terms, 4,300 definitions, and 4,500 USE references in SKOS, Web Ontology Language, ZThes, CSV, and PDF forms | Aerospace and space-science subject module | Candidate. Confirm the downloadable content date and attribution requirement. |
| Earth science and aerospace technology | [NASA GCMD Science Keywords](https://gcmd.earthdata.nasa.gov/KeywordViewer/scheme/sciencekeywords/27478148-b4b6-4c89-8829-08d2ee7bfe10/) and [NASA Technology Taxonomy](https://techport.nasa.gov/taxonomy) | Versioned source classifications for datasets, phenomena, instruments, platforms, projects, and technologies | Source evidence and crosswalks for NASA records | Mapping/deterministic metadata only until evaluation proves document-subject value; exclude instrument and platform branches from policy topics. |

Specialist activation must use document evidence, source, agency, or cited
legal structure as a ranking signal. It must not use those signals as a hard
filter: a Department of Agriculture document can discuss health, and a health
waiver can discuss housing or education.

## Operational authorities, codes, and schemas

These resources improve precision, joins, and explainability. They are not
additional general-subject vocabularies.

### Regulatory and legal controls

| Resource | Kind and primary use | Decision |
| --- | --- | --- |
| [Federal Register API categories, topics, agencies, and Table of Contents values](https://www.federalregister.gov/developers/documentation/api/v1) | Source document type, issuer identity, source-assigned topic, and action/genre evidence | Preserve raw values. Reconcile API topics to the editioned Federal Register Thesaurus; keep Notice `toc_subject` outside the topic facet. |
| [Regulations.gov API](https://open.gsa.gov/api/regulationsgov/) | Docket, document, comment, attachment, and agency-configured code lists | Deterministic source metadata. No maintained cross-agency topic or fine-grained attachment taxonomy was found. |
| [Unified Agenda](https://www.reginfo.gov/public/jsp/eAgenda/StaticContent/202210/RiscPreamble.pdf) and Regulation Identifier Number | Rule identity, stage, priority, timetable, legal authority, CFR, and related-rule fields | Deterministic metadata. The subject index uses Federal Register terms; agency sort codes and NAICS are not topics. |
| [OIRA Executive Order review and meeting searches](https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD) | Review status, rule stage, conclusion action, and meeting status | Deterministic process metadata. Obtain subjects from the linked rule text or source-assigned topic. |
| [Paperwork Reduction Act search](https://www.reginfo.gov/public/do/PRASearch) | Office of Management and Budget (OMB) Control Number, Information Collection Request identity, request type, burden, status, and conclusion | Deterministic metadata. No separate Paperwork Reduction Act subject thesaurus was found. |
| [eCFR API](https://www.ecfr.gov/developers/documentation/api/v1) and [GovInfo](https://www.govinfo.gov/developers) | CFR hierarchy, agencies, point-in-time text, packages, versions, preservation metadata, and fixity | Use source-native structure and edition status. Title, chapter, part, and section names do not become subjects. |
| [Supreme Court opinion indexes](https://www.supremecourt.gov/opinions/) | Official opinion/package type and slip, preliminary-print, and bound-volume version ladder | Deterministic metadata. Split writings only when the official source supplies reliable boundaries. |
| [U.S. Courts Nature of Suit codes](https://www.uscourts.gov/sites/default/files/js_044_code_descriptions.pdf), PACER, and [CourtListener](https://www.courtlistener.com/help/api/jurisdictions/) | Case-opening classification, court and case identity, and platform-normalized opinion types/statuses | Keep official and platform values separate. No maintained national pleading-event or court-topic taxonomy was found. |
| [FCC ECFS API](https://www.fcc.gov/ecfs/help/public_api) and [47 CFR part 1](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-1) | Proceeding, bureau, raw filing description, access status, and ex parte procedure | Deterministic source metadata. The proposed shared filing groups remain versioned implementation mappings; no FCC subject thesaurus was found. |
| [SEC Rules and Regulations](https://www.sec.gov/rules-regulations) | SEC series and page categories for rules, releases, orders, guidance, no-action letters, petitions, and self-regulatory-organization filings | Preserve SEC categories and release/file numbers; do not treat the site navigation as a universal taxonomy. |
| [FERC eLibrary class/type and docket-prefix lists](https://www.ferc.gov/media/elibrary-classtype-information) | Maintained FERC-specific document class, type, docket prefix, sector, accession, and security fields | Use as source-specific deterministic metadata. Do not apply FERC values to other agencies. |
| [NRC ADAMS](https://www.nrc.gov/reading-rm/adams) | NRC accession, docket/license, search facets, and public-release status | Preserve raw source metadata. Defer a normalized NRC type list until a source audit exports and defines the current values. |
| [GAO Congressional Review Act database](https://www.gao.gov/legal/other-legal-work/congressional-review-act?priority=all&processed=1&type=all) | Rule submission, major-rule report, coverage decision, receipt/effective dates, and disapproval events | Authoritative source records plus deterministic lifecycle fields. Keep project-calculated review windows versioned and auditable. |
| [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) | Portable text-quote and text-position evidence selectors | Mapping target for passage evidence. Always bind a selector to the exact rendition and digest. |
| [RFC 7089 Memento](https://www.rfc-editor.org/rfc/rfc7089.html) | Time-based links among web-resource versions | Use when a source/archive exposes it; it does not establish legal effect or semantic change. |
| [LegalRuleML 1.0](https://docs.oasis-open.org/legalruleml/legalruleml-core-spec/v1.0/os/legalruleml-core-spec-v1.0-os.html) | Formal legal-rule and norm representation | Reject/defer for this catalog. Rulespec/Formspec own formal rule representation, and LegalRuleML supplies neither subjects nor source genres. |

### Legislative, fiscal, oversight, and organization controls

| Resource | Kind and primary use | Decision |
| --- | --- | --- |
| [Congress.gov API](https://api.congress.gov/), [BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/resources/readme.html), and bill/action/version codes | Bills, amendments, committees, hearings, votes, laws, summaries, subjects, versions, and actions | Source-native deterministic metadata and transport schema. Pin schema versions; never infer a subject from an XML element name. |
| [CRS Product Topics and Product Types](https://www.congress.gov/help/crs-products) | Source topics and genres such as Report, In Focus, Insight, Legal Sidebar, Infographic, Testimony, and Appropriations Status Table | Preserve per product edition. Topics are source evidence and mapping inputs, not a separately governed reusable thesaurus. |
| [Lobbying Disclosure Act API constants](https://lda.gov/api/redoc/v1/) | General issue codes, filing types, periods, government targets, countries, and states | Filer-selected issue codes are source evidence; filing fields are deterministic. The government-target list contains obsolete/non-use values and is not an organization authority. |
| [FEC committee and filing code descriptions](https://www.fec.gov/campaign-finance-data/committee-master-file-description/) | Committee ID, type, designation, organization type, party, frequency, and report type | Entity normalization and deterministic metadata. Preserve cycle and effective dates; comply with statutory restrictions on uses of individual contact data. |
| [CBO Topics and Cost Estimates XML](https://www.cbo.gov/cost-estimates/xml) | CBO browse topics, budget functions, mandate and pay-as-you-go flags, bill and committee links | Topics are source evidence; all fiscal facets are deterministic. The 27 browse topics are not a published semantic vocabulary. |
| [GAO Topics](https://www.gao.gov/topics) | Current broad browse topics attached to GAO products | Capture only an actual GAO assignment. Do not reconstruct one from navigation, and do not replace it with the obsolete 1998 GAO Thesaurus. |
| [Oversight.gov Federal Report Types](https://www.oversight.gov/reports/federal) | Audit, inspection/evaluation, investigation, review, peer review, semiannual report, and other source genres | Deterministic genre metadata. No supported public topic taxonomy or API was found. |
| [Federal Audit Clearinghouse dictionary](https://www.fac.gov/api/dictionary/) and OMB Compliance Supplement | Submission, award, program, finding, requirement, amount, and auditee fields | Finding text can receive subjects; requirement codes and amounts remain deterministic and tied to the applicable audit-year guidance. |
| [Grants.gov status and code lists](https://www.grants.gov/api/status-codes) | Funding-activity category, eligibility, instrument, opportunity status, and statutory initiative values | Source evidence plus deterministic metadata. Tag the opportunity narrative for substantive topics. |
| [SAM.gov Assistance Listings API](https://open.gsa.gov/api/assistance-listings-api/) | Assistance Listing Number, program, agency, assistance type, eligibility, status, mission, and subject fields | Program identity and deterministic fields; mission/subject values are source evidence. Pin the API version because field names have drifted. |
| [USAspending API](https://api.usaspending.gov/docs/endpoints) and [Governmentwide Spending Data Model](https://fiscal.treasury.gov/files/data-transparency/gsdm-architecture-v1.0.1.pdf) | Award, recipient, account, agency, industry, product/service, and transaction fields | Deterministic metadata and schema crosswalk. Award descriptions receive subjects; operational codes do not. |
| [SAM.gov UEI](https://sam.gov/entity-registration) and [DLA CAGE](https://www.dla.mil/Working-With-DLA/Applications/Details/Article/2920893/cage-code-commercial-and-government-entity-code/) | Award-entity and facility/location identifiers | Entity normalization. Keep registration, facility, parent, validity, and public/controlled access distinctions. |
| [NAICS](https://www.census.gov/naics/) and [Product and Service Codes](https://www.acquisition.gov/psc-manual/all) | Industry and predominant procured product/service classifications | Deterministic facets and optional ranking signals. They do not state a document's policy topic. |
| [SAM.gov Opportunities API](https://open.gsa.gov/api/get-opportunities-public-api/) and [Federal Hierarchy API](https://open.gsa.gov/api/fh-public-api/) | Procurement notice type/status and operational funding/awarding organization hierarchy | Deterministic lifecycle and entity metadata. Preserve retired codes and versions; the public opportunities API returns only the latest active version. |
| [OMB Circular A-11](https://www.whitehouse.gov/omb/information-resources/guidance/circulars/), [Treasury Account Symbols](https://fiscal.treasury.gov/accounting/central-accounting-reporting-system-cars/treasury-account-symbol-reporting), and [Federal Account Symbols and Titles (FAST) Book](https://fiscal.treasury.gov/accounting/fast-book/description-of-contents) | Budget functions, object classes, apportionment categories, and account identifiers | Deterministic fiscal metadata and reviewed topic crosswalk signals. Use the applicable fiscal-year edition. |
| [Federal Workforce Data](https://data.opm.gov/explore-data/data/data-downloads) and [PLUM Act data](https://www.opm.gov/about-us/open-government/plum-reporting/plum-data/) | Agency, occupation, appointment, schedule/status, pay, position, incumbent, vacancy, and effective period | Entity and observation metadata only. Preserve redaction, certification, and release vintage. |
| [Census government-finance classifications](https://www.census.gov/programs-surveys/apes/technical-documentation/Class_Manual.html) and [NASBO State Expenditure Report](https://www.nasbo.org/mainsite/reports-data/state-expenditure-report) | Cross-state statistical functions, objects, fund sources, and program areas | Mapping only. They do not replace a state's enacted chart of accounts or legal program identity. |
| [FACA Database](https://catalog.data.gov/dataset/federal-advisory-committee-act-faca-database-complete-raw) | Committee, authority, status, member, meeting, report, cost, and interest-area values | Committee/entity normalization and deterministic metadata; interest areas are source evidence. Mark current-year data unverified until annual GSA review. |
| [BioGuide IDs and Congress committee codes](https://www.congress.gov/help/field-values/member-bioguide-ids) | Stable person and legislative-body identifiers | Entity normalization with chamber, Congress, parent, and effective dates. |
| [Global Legal Entity Identifier](https://www.gleif.org/en/about/open-data) | Legal-entity identity and reported parent relationships | Optional entity crosswalk, strongest in financial markets. Parent exceptions and gaps prevent universal use. |

### Health, social-service, geography, and specialist controls

| Resource | Kind and primary use | Decision |
| --- | --- | --- |
| [CMS State Waivers](https://www.medicaid.gov/medicaid/section-1115-demo/demonstration-and-waiver-list), [T-MSIS `WAIVER-TYPE`](https://www.medicaid.gov/tmsis/dataguide/v3/data-elements/cip002177/), and [HCBS Taxonomy](https://www.medicaid.gov/tmsis/dataguide/v3/appendices/) | Waiver authority, population, service, status, and effective dates | Deterministic/source evidence. These lists classify administrative authority and services, not every topic in a waiver. |
| [CMS State Plan Amendment register](https://www.medicaid.gov/medicaid/medicaid-state-plan-amendments) | State, transmittal, decision, status, and date | Deterministic/source evidence. No universal State Plan Amendment topic or action thesaurus was found. |
| [HHS Guidance Portal](https://www.hhs.gov/guidance/) | Issuer, date, status, portal topic, and artifact | Preserve portal labels as source evidence. Derive normalized guidance genre only from source-specific evidence; no cross-division genre list was found. |
| [CMS Data Element Library](https://www.cms.gov/newsroom/fact-sheets/cms-data-element-library-fact-sheet), [Provider Data Catalog](https://data.cms.gov/provider-data/about), [Restructured BETOS Classification System (RBCS)](https://data.cms.gov/provider-summary-by-type-of-service/provider-service-classifications), and [Value Set Authority Center (VSAC)](https://vsac.nlm.nih.gov/) | Versioned measures, response sets, provider datasets, service groups, and clinical-quality value sets. BETOS means Berenson-Eggers Type of Service. | Deterministic metadata and mappings. Preserve instrument, field, unit, universe, effective date, and every embedded terminology license. |
| [Unified Medical Language System (UMLS) 2026AA](https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/release/notes.html) | Cross-vocabulary biomedical concept and name integration | Mapping only under an individual UMLS license. Source-specific restrictions survive the UMLS mapping. |
| [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/docs/rxnormfiles.html) | Drug identity and relationships | Medication entity normalization and mapping, not subjects. Full content uses UMLS terms. |
| [SNOMED CT US Edition](https://www.nlm.nih.gov/healthit/snomedct/us_edition.html), [ICD-10-CM](https://www.cdc.gov/nchs/icd/icd-10-cm/files.html), and [HCPCS Level II](https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update) | Clinical findings/procedures, diagnoses, and products/services | Source code metadata and mappings only. Retain release and effective date; do not infer codes from broad textual similarity. |
| [CPT](https://www.ama-assn.org/practice-management/cpt/cpt-licensing-frequently-asked-questions-faqs) | American Medical Association procedure/service code set | Reject/defer registry ingestion and model training until an approved license covers the intended use. |
| [LOINC](https://loinc.org/downloads) | Observations, laboratory tests, surveys, panels, and clinical documents | Deterministic/mapping layer under LOINC attribution, notice, version, and third-party-content requirements; not a general subject module. |
| [National Plan and Provider Enumeration System (NPPES) National Provider Identifier (NPI) files](https://download.cms.gov/nppes/NPI_Files.html), [National Uniform Claim Committee (NUCC) Provider Taxonomy](https://nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40/csv-mainmenu-57), CMS Certification Number, and public Provider Enrollment, Chain, and Ownership System (PECOS) files with PECOS Associate Control (PAC) IDs | Provider and facility identity, enrollment, and type | Entity normalization. NUCC commercial use requires a license; no identifier alone proves ownership, licensure, or current operation. |
| [National Adult Maltreatment Reporting System (NAMRS)](https://namrs.acl.gov/home), [National Ombudsman Reporting System (NORS)](https://ltcombudsman.org/nors/), and [Older Americans Act reporting](https://acl.gov/programs/state-program-reports) | Collection-specific adult maltreatment, ombudsman complaint, client, service, expenditure, and performance codes | Deterministic/source evidence tied to collection year and version. No reusable Administration for Community Living subject thesaurus was found. |
| [WHO ICF](https://www.who.int/standards/classifications/international-classification-of-functioning-disability-and-health) | Functioning, disability, participation, and environmental-factor classification | Mapping only; the CC BY-ND 3.0 IGO “no derivatives” condition blocks a modified local hierarchy. |
| [Open Referral Human Services Data Specification (HSDS)](https://docs.openreferral.org/en/latest/hsds/overview.html) | Human-service organization, service, location, program, schedule, and eligibility data schema | Interchange schema, not a service taxonomy. Preserve each external scheme and concept ID. |
| [211HSIS](https://211hsis.org/taxonomy/what-is-taxonomy) | Large human-services taxonomy | Reject/defer for the open registry: definitions, API, reuse, redistribution, and database use require paid licensing. |
| [ACS variables](https://api.census.gov/data/2024/acs/acs1/spp/variables.html), [TIGER/Line](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/tiger-geo-line.html), relationship files, and [GNIS](https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data) | Measures, universes, estimates/margins of error, geography identity, boundaries, crosswalks, and place names | Deterministic observation/entity data. Record every product, vintage, universe, boundary, allocation method, and residual. |
| [IRS EO BMF/TEOS/Form 990](https://www.irs.gov/charities-non-profits/tax-exempt-organization-search-bulk-data-downloads), [OpenFEC](https://api.open.fec.gov/developers), and public FCC FRN | Nonprofit, campaign committee, and FCC-scoped entity identifiers | Typed entity normalization. Preserve legal scope, cycle/filing period, and source-specific restrictions. |
| [EPA Substance Registry Services (SRS)](https://sor.epa.gov/sor_internet/registry/sysofreg/sorservices/sorServices.html), [Computational Toxicology and Exposure/Distributed Structure-Searchable Toxicity (CompTox/DSSTox)](https://www.epa.gov/comptox-tools/computational-toxicology-and-exposure-apis), and [Toxic Substances Control Act (TSCA) Inventory](https://www.epa.gov/tsca-inventory/about-tsca-chemical-substance-inventory) | Substance identifiers, structures, synonyms, mappings, list membership, and regulatory status | Chemical entity and deterministic metadata layers. Keep the CompTox substance identifier (`DTXSID`) and structure identifier (`DTXCID`) distinct; inventory membership is not a subject. |
| [CAS REGISTRY](https://www.cas.org/cas-data/cas-registry) | Proprietary chemical identity registry | Reject/defer bulk use without a CAS license. A public CAS number does not make the compiled names/registry open. |
| [Open States](https://docs.openstates.org/api-v3/) and [NAAG Multistate Settlements](https://www.naag.org/news-resources/research-data/multistate-settlements-database/) | State process codes, state-supplied subjects, and reference issue/action labels | Source evidence and external joins. Neither supplies a complete national state-bill or attorney-general action thesaurus. |
| [KFF HCBS waitlist measures](https://www.kff.org/medicaid/a-look-at-waiting-lists-for-medicaid-home-and-community-based-services-from-2016-to-2025/) and [SSA Open Data](https://www.ssa.gov/data/) | Survey- and dataset-specific service, population, waitlist, workload, backlog, and processing-time measures | Deterministic observations with method, universe, time, and source. No national harmonized waitlist or SSA operations vocabulary was found. |
| [PolicyEngine](https://www.policyengine.org/us/model/data/pipeline) | Tax-benefit model variables, parameter paths, baseline/reform calculations, and estimates | External join and versioned run metadata, never source-document facts or subjects. |

## Source-family recommendation matrix

“Subject input” below identifies candidate subject evidence. It does not
authorize automatic assignment. “No document subjects” means the row is an
entity, container, observation, or external result; its structured values
remain essential.

### Current source profiles

| ID and source | Subject input | Non-subject controls and decision |
| --- | --- | --- |
| `C01` Regulations.gov dockets | None on the container; linked documents supply their own subjects | Preserve docket type, agency, docket ID, RIN, dates, and source values. No finer cross-agency docket taxonomy was found. |
| `C02` Regulations.gov documents | General core; Federal Register topic only when linked/source-assigned; activate specialist modules from text | Preserve document/subtype, docket, attachments, dates, Federal Register number, and evidence depth. Normalize attachment type source by source. |
| `C03` Regulations.gov comments | Outside version 1 | Preserve submission types and docket links under a separate privacy, sampling, and evaluation design. Agency commenter categories are not topics. |
| `C04` Federal Register | Federal Register topics as source evidence for Rules/Proposed Rules; general core; specialist modules from text | Keep category, presidential subtype, `toc_subject`, agency, RIN, docket, CFR, citation, dates, and version. `toc_subject` is action/genre metadata. |
| `C05` Unified Agenda | Federal Register-based source index plus general/specialist text assignments | RIN, agency, stage, priority, timetable, legal authority, CFR, related RIN, and NAICS remain deterministic. |
| `C06` CFR sections | General core from actual text; CFR List of Subjects ranks candidates | Use eCFR/GovInfo hierarchy, point-in-time date, edition status, agency, citation, and amendment/version links. No topic assignment from structure alone. |
| `C07` Congress bills | CRS Policy Areas and topical Legislative Subject Terms; preserve actual bill-level CRS assignments | Keep bill type, Congress, chamber, action/version, committee, sponsor, Public Law link, and USLM structure. Do not copy a bill-level subject to related artifacts. |
| `C08` SAM entities | No document subjects | UEI, CAGE, legal name, registration, NAICS, location, hierarchy, status, and public/controlled provenance support entity normalization. |
| `C09` lobbying filings | Filer-selected LDA issue codes as source evidence; map to the general/legislative core after review; tag specific-issue text | Filing type/period/status, client, registrant, government target, and amendment history remain separate. The LDA government-target list is not an organization authority. |
| `C10` FEC committees | No document subjects | FEC committee ID, type, designation, party, sponsor, candidate links, cycle, and effective dates support entity normalization. |
| `C11` GAO reports | General core from title/abstract/body; capture an actual GAO Topic as source evidence | Keep report ID, product type, date, agency, recommendations, and evidence depth. Reject the 1998 GAO Thesaurus as the current authority. |
| `C12` CRS reports | CRS Product Topic as edition-specific source evidence; general/legislative core from the matching text | Preserve product type, report ID, edition, status, bills/hearings, and retrieval date. No separately governed CRS Product Topic vocabulary was found. |
| `C13` Supreme Court opinions | General core and relevant specialist modules from official text | Preserve official package/type, court, docket, citation, author where sourced, disposition, and official version. No open court-assigned topic thesaurus was found. |
| `C14` CourtListener/RECAP dockets | No document subjects on the container | Normalize official court and Nature of Suit code; retain case, parties, platform IDs, source labels, dates, and access. No national pleading-event taxonomy was found. |
| `C15` USAspending recipients | No document subjects | Normalize UEI/CAGE and source recipient identity; retain NAICS, PSC, award rollup, hierarchy, status, and vintage as typed metadata. |
| `C16` FCC proceedings | None on the container; linked filings/documents supply subjects | Preserve ECFS proceeding number/flag, bureau, status, dates, and 47 CFR process class. No FCC topic thesaurus was found. |
| `C17` FCC filings | General/specialist core from available text; Federal Register topics only through an actual linked record | Preserve raw ECFS submission description, filer/author/FRN, bureau, filing/access status, attachment metadata, and the implementation-defined genre-map version. |

### Product roadmap families

| ID and source | Subject input | Non-subject controls and decision |
| --- | --- | --- |
| `T1-01` OIRA reviews and meetings | Linked rule text and source-assigned Federal Register/Agenda topics; no subjects on the review event itself | RIN, review status/stage/conclusion, meeting status, participants, dates, and links remain deterministic. |
| `T1-02` Federal Register public inspection | Same core and source evidence as `C04` | Preserve public-inspection status, filing time, scheduled publication, replacement/final-document link, category, and version. |
| `T1-03` Medicaid waivers and State Plan Amendments | General core plus MeSH and evaluated social-service mappings; CMS labels as source evidence | Waiver authority/type/population, HCBS service, state, action/status, approval/effective/expiration dates, and comment windows remain deterministic. |
| `T1-04` sub-regulatory guidance | General core plus source-relevant specialist module; portal topics as source evidence | Preserve issuer, raw genre, program, legal basis, effective interval, revision, supersession, withdrawal, page/file version, and capture receipt. No government-wide guidance-genre list exists. |
| `T1-05` state legislation | Legislative module; preserve each state's assigned bill subjects; LegiScan only as gap-filling evidence | Keep jurisdiction, session, chamber, bill/version/classification, action, sponsor, hearing, and source. No national state-bill subject thesaurus exists. |
| `T1-06` grants and assistance | General/legislative core from narrative; Grants.gov category and Assistance Listing subject/mission as source evidence | Assistance Listing Number, opportunity/instrument/status, agency, eligibility, amount, geography, dates, UEI, and award flow are deterministic. |
| `T1-07` congressional hearings | Legislative module on each notice, testimony, transcript, or report; CRS assignment only when attached to that artifact | Keep Congress, chamber, committee code, event ID, witness/BioGuide identity, related bill, schedule, and artifact version. |
| `T1-08` Inspector General reports | General core from text; preserve actual source topics if supplied | Oversight.gov product type, office, agency, number, date, recommendations, status, and evidence depth remain deterministic. No supported Oversight.gov topic taxonomy was found. |
| `T1-09` apportionments and impoundment | General/legislative core for legal decisions and explanatory documents; none for account observations | Use A-11 categories, TAS/account identity, fiscal year/period, amount, change, withholding, exact OMB file version, and GAO decision citation. |
| `T1-10` agency web changes | Apply general/specialist subjects only to the changed source passage | Use PROV-O/Web Annotation/Memento mappings for capture/version/evidence; preserve URL, time, digest, status, predecessor, and project change type. |
| `T2-01` district demographics and crosswalks | No document subjects | ACS variable, universe, estimate, margin of error, product/vintage, Census/GNIS geography, boundaries, relationship file, allocation method, and residual are deterministic. |
| `T2-02` broader court opinions and litigation linkage | General/specialist core from opinion text | Preserve official/platform opinion type separately, court, docket, citation, author, disposition, date, package/version, and evidence-backed rule-to-case link. |
| `T2-03` Information Collection Requests and dataset-loss signals | Federal Register/general subjects for source notices and supporting documents; none for status observations | OMB Control/ICR number, request/status/conclusion, agency, burden, deadline, affected public, dataset state, and source version remain deterministic. |
| `T2-04` CBO cost estimates | Legislative/general core from estimate narrative; CBO Topic as source evidence | Keep bill, committee, budget functions, mandate/PAYGO flags, score window, spending/revenue amounts, and estimate date. |
| `T2-05` CMS facilities, staffing, and ownership | No document subjects on entities/observations; separately ingested narrative documents may use MeSH/general subjects | Normalize CCN/NPI/public PECOS/PAC and owners; preserve dataset, measure, unit, period, staffing/quality/ownership fields, clinical code version, and license. |
| `T2-06` state Attorney General actions | General core plus relevant health/environment/specialist module from the complaint or letter; state/NAAG labels as source evidence | Preserve office/state, raw action/genre, target, court/docket, coalition, status, date, source artifact, and press-release relationship. No complete national AG taxonomy exists. |
| `T2-07` state waiver notices | Same subject treatment as `T1-03` | Preserve separate state notice/action/status and comment window, then link—without collapsing—to the later federal waiver artifact. |
| `T2-08` federal workforce and vacancies | No document subjects on observations/entities | Use FWD/EHRI and PLUM codes for agency, occupation, appointment, position, incumbent, acting/vacant status, period, certification, and redaction. |
| `T2-09` single audits | General/specialist core for finding narratives; program/source labels as evidence | FAC requirement/finding codes, UEI, Assistance Listing, program, amount, audit year, resolution, and applicable Compliance Supplement remain deterministic. |
| `T2-10` CRS full text and history | Legislative core and CRS Product Topic on the matching edition | Preserve every product type, edition, status, text, retrieval date, and historical LIV mapping. Never apply a current topic to another edition silently. |
| `T2-11` legislators and committees | No document subjects | BioGuide/Open States people IDs, committee codes, chamber, Congress/session, parent, role, membership, and effective dates; use W3C ORG only as a relationship crosswalk. |
| `T3-01` state administrative registers | General core plus specialist modules from text; preserve state-assigned subjects | Keep jurisdiction, agency, raw type, register/citation, legal authority, stage, dates, and participation window. Map one state at a time; federal labels do not prove equal legal effect. |
| `T3-02` state budgets | General/legislative core for narrative documents | Preserve state-native funds, accounts, agencies, programs, fiscal year, amounts, status, and version; Census/NASBO classifications are reviewed crosswalks only. |
| `T3-03` modeled program estimates | No subjects on estimates; a separately ingested methodology document can be tagged | Store PolicyEngine package/commit or API version, parameters, baseline/reform, inputs, model/data vintage, geography, measure, uncertainty, time, and receipt. |
| `T3-04` cross-corpus entity graph | No document subjects | Use typed source IDs—UEI, CAGE, EIN, FEC, FRN, NPI/CCN/PAC, BioGuide, federal hierarchy, LEI—with dates, match evidence, method, confidence, and provenance. |
| `T3-05` HCBS waitlists | Tag separately preserved narrative sources with general, MeSH, or evaluated social-service subjects | Preserve raw waiting/interest/referral measure, screening rule, program/population, state, period, method, deduplication, source, and CMS mappings. |
| `T3-06` SSA operations | Tag a separately preserved closure/guidance notice; no subjects on service measures | Preserve dataset-specific office, geography, service, metric, universe, period, backlog/outcome definition, update/correction policy, and source. |
| `T3-07` federal advisory committees | General/legislative core for charters and meeting documents; FACA interest areas as source evidence | Normalize committee/member identity; preserve authority, purpose, status, agency, meeting/report type, dates, cost, and annual-review verification state. |
| `T3-08` state lobbying | General/legislative core from issue text; preserve state-selected subjects and map cautiously to LDA | Keep jurisdiction, raw filing type, client, registrant, target, period, amendment/termination, form version, and source. No national list exists. |
| `L-01` legacy AGID, ombudsman, and adult-maltreatment data | General/MeSH/evaluated social-service subjects for preserved narrative artifacts; none for observations | Snapshot first. Keep NAMRS/NORS/OAAPS collection, code, measure, universe, year, suppression, dictionary, original bytes, digest, and custodian. |

### Completion gaps and proposed new source families

| ID and gap/source | Vocabulary decision |
| --- | --- |
| `E01` Regulations.gov attachments | No new subject vocabulary. Retrieve, type, and parse the artifact, preserve raw subtype/title/media/role, then apply the same general/specialist modules as `C02`. No universal attachment taxonomy was found. |
| `E02` Federal Register body | Use source-assigned Federal Register topics plus the general/specialist modules. Preserve native HTML/XML structure, category/action metadata, correction/withdrawal, and public-inspection lineage. |
| `E03` CFR text/history | Use CFR List of Subjects only to rank the general core. Preserve eCFR/GovInfo hierarchy, point-in-time text, official/unofficial status, amendment history, and USLM/Akoma Ntoso mappings separately. |
| `E04` congressional completeness | Use CRS Policy Areas/Legislative Subject Terms only on the artifact to which evidence applies. Preserve Congress.gov/BILLSTATUS codes, USLM structure, editions, amendments, reports, testimony, votes, nominations, and law links. |
| `E05` report, court, and FCC text | Adds evidence, not a new vocabulary. Apply each source's treatment from `C11-C14`, `C17`, `T2-02`, and preserve extraction/OCR, package, attachment, and access provenance. |
| `G01` enacted statutes and codified law | Legislative/general core from source text; USLM, GovInfo/eCFR, Public Law/USC identity, structure, version, amendment, repeal, and effective history are deterministic. Akoma Ntoso/ELI/Schema.org are export mappings only. |
| `G02` non-Regulations.gov federal dockets | General/specialist modules from text. Preserve SEC series, FERC class/type and docket prefix, NRC accession/facets, and every source's raw types. No government-wide docket taxonomy exists. |
| `G03` agency adjudication and enforcement | General/specialist modules from each complaint, brief, decision, order, or settlement. Preserve agency-native posture/genre; use the ACUS recommendation only to plan source audits. No cross-agency canonical list exists. |
| `G04` litigation filings and events | General/specialist modules from each text artifact. Preserve court, docket, party role, Nature of Suit, raw filing/event, stage, relief, disposition, citations, package/version, and rule-link evidence. |
| `G05` Congressional Review Act material | Federal Register/legislative core on actual documents. GAO/source types, rule/RIN identity, major flag, receipt/effective dates, report/decision, joint resolution, presidential action, and calculated windows remain deterministic. |
| `G06` federal procurement | General/legislative core from narrative and terms. Preserve SAM notice type/status/version, PSC, NAICS, UEI/CAGE, federal hierarchy, award/account/amount, dates, and set-aside values. |
| `G07` federal budget and appropriations | General/legislative core from narrative. Preserve A-11 functions/object classes, TAS/account, agency/program, fiscal year, amount, bill/status/version, CBO facets, and source file. |
| `G08` complete congressional proceedings | Legislative module with artifact-level evidence. Preserve Congress API/BILLSTATUS identifiers, types/actions/versions, USLM structure, BioGuide/committee codes, votes, nominations, treaties, and enacted-law links. |
| `G09` state executive and agency actions | General core plus specialist modules from text; preserve state-assigned topics. Normalize jurisdiction and map raw executive-order, emergency, guidance, waiver, enforcement, plan, and manual types one state at a time. |

### Roadmap feeds and reference spines

These seven providers are named in the source matrix, but they do not add
subject vocabularies. OpenFEC is the authoritative government source in this
group. Use the others for discovery, gap filling, or identity hints, then
verify material facts against the responsible government publisher.

| Provider and matrix use | Authority, access, and maintenance | Decision and gate |
| --- | --- | --- |
| [America's Data Index](https://dataindex.us/about-us) — `T2-03` | Active collaborative Information Collection Request aggregator with website and CSV access; code is GPLv3 and site content is CC BY-SA 4.0. RegInfo.gov remains authoritative. The legal owner, stable API, documented schema, and rights over every exported record were not verified. | Discovery and change alerts only. Pin each capture and verify accepted records, identifiers, and status against RegInfo.gov. |
| [EveryCRSReport](https://www.everycrsreport.com/download.html) — `T2-10` | American Governance Institute/community service, not the Congressional Research Service; active inventory with CSV, JSON, PDF, HTML, versions, and digests. Embedded third-party material can retain copyright. | Historical/full-text gap fill. Verify current edition and status against Congress.gov or the official Congressional Research Service portal; preserve source, version, and digest. |
| [`unitedstates/congress-legislators`](https://github.com/unitedstates/congress-legislators) — `T2-11` | Active community repository, not Congress; YAML/JSON/CSV under CC0 1.0. | Pin the commit. Use as an identifier/history crosswalk and verify current office, term, and committee membership against official sources. |
| [Open States people](https://github.com/openstates/people) — `T1-05`, `T2-11`, `T3-04` | Active Plural Open/community repository under CC0; API access follows Plural's terms. It is not an official state authority, and no refresh service level was verified. | Pin the snapshot, retain jurisdiction and upstream URLs, and verify current roles against state sources. Never merge people because names match. |
| [ProPublica Nonprofit Explorer](https://projects.propublica.org/nonprofits/api/) — `T3-04` | Monthly reference service over Internal Revenue Service and Federal Audit Clearinghouse data. Its terms require attribution and prohibit republishing the raw dataset as a standalone product. | External lookup only. Match by Employer Identification Number with evidence, verify material facts against the government source, and do not mirror the corpus. |
| [OpenFEC](https://api.open.fec.gov/developers/) — `C10`, `T3-04` | Authoritative Federal Election Commission API and bulk source with nightly updates. Statutory restrictions apply to sale and use of individual contributor information. | Use as the federal campaign-finance authority. Pin schema/response metadata, preserve cycle and effective dates, and enforce the individual-data use restriction. |
| [LegiScan](https://legiscan.com/legiscan/) — `T1-05`, `T2-11` | Commercial aggregator, not a legislature; API and weekly datasets. Public service data use CC BY 4.0, while paid tiers can differ and service terms also apply. | Gap fill only. Preserve provider and official URLs plus dataset version; verify text and status against the legislature; confirm the exact tier's redistribution terms. |

### External joins

| System | Vocabulary and model treatment |
| --- | --- |
| Axiom Foundation — `axiom-corpus` | Conditional derivative legal-text feed, not a vocabulary or legal-identifier authority. Reconsider a pinned named release only when it contains a needed source and passes the [Axiom source-adoption gate](axiom-ecosystem-analysis-2026-07-28.md#3-define-the-axiom-corpus-adoption-gate-now). Preserve the Axiom release, `citation_path`, source URL, source digest, and extraction evidence without replacing the official source artifact or implementation identifier. |
| Axiom Foundation — `rulespec-us` and runtime | External executable-logic results. Preserve RuleSpec identifiers, provision paths, source citations, schema version, and reverse-index evidence. Do not import RuleSpec element names, input/output symbols, or rule categories into the subject pool. Preserve the join design now; consume a pinned reverse index only after target-specific coverage passes. |
| Axiom Foundation — `axiom-bills` | Potential state-bill feed or parser reference. State bills remain outside the current MVP. Decide feed-versus-parallel ownership before implementation, and require release-quality completeness, official-source provenance, and explicit failures before replacing any existing reader. |
| PolicyEngine | Treat variables, parameter paths, reforms, model versions, and results as external run metadata. Never present a modeled label or estimate as a source-assigned subject or source-document fact. |
| Formspec-Labs `rulespec` | Use its content identity, provenance, warrant, permission, and supersession metadata at the governance seam. Map provenance to shared standards where useful; keep it out of the document text and subject registry. |

Any future Axiom mapping must retain the implementation identifier; Axiom release and
`citation_path`; RuleSpec module or concept identifier; official source URL and
digest; mapping method and evidence; schema and adapter versions; and
verification state and time. These values remain separate identities, not one
generic graph edge.

Axiom's `defines`, `delegates`, `implements`, `sets`, `amends`, `restates`, and
`cites` values describe external legal or provenance relationships. Never load
them as SKOS mappings, subject-hierarchy predicates, or subject assignments. A
later semantic crosswalk must preserve direction, source evidence, scope, and
confidence.

The Axiom `receipt` project is neither a vocabulary nor a source feed. It
remains a post-MVP reference for signing and append-chaining an already valid
implementation receipt; the project receipt and recomputation checks remain
authoritative.

## Negative findings

The research did not find a maintained, public, authoritative resource for any
of these scopes:

- one topic thesaurus applied across federal regulatory, legislative, judicial,
  oversight, budget, grants, procurement, and state material;
- a cross-agency Regulations.gov attachment or fine-grained document-type
  taxonomy;
- a government-wide guidance, administrative-adjudication, enforcement, or
  federal-docket genre taxonomy;
- an FCC subject thesaurus or authoritative mapping for ECFS filing
  descriptions;
- a national CM/ECF pleading- or docket-event taxonomy or an open
  court-assigned legal-topic thesaurus;
- a national state-bill, state-register, state-executive-action, state
  lobbying, state Attorney General, or state-budget chart of accounts;
- a supported Oversight.gov subject taxonomy or current machine-readable GAO
  thesaurus;
- a reusable CRS Product Topic vocabulary separate from the product pages;
- a current, openly versioned United States energy-policy thesaurus;
- an open nationwide human-services taxonomy comparable to licensed 211HSIS;
- a general Administration for Community Living topic vocabulary, a
  harmonized HCBS waitlist measure vocabulary, or a shared SSA operations
  vocabulary; or
- one organization identifier that spans government units, award recipients,
  facilities, nonprofits, campaign committees, lobbying parties, court
  parties, and public commenters.

These gaps call for source-specific raw values, small reviewed maps, typed
identifiers, and abstention. They do not justify importing the nearest
name-similar commercial taxonomy or inventing unsupported “official” labels.

## License and access gates

| Resource or service | Gate before use |
| --- | --- |
| CPT | Obtain an American Medical Association license that expressly covers storage, redistribution, product display, and any proposed model-training use. Until then, do not ingest labels. |
| 211HSIS | Obtain a subscription/API and redistribution agreement compatible with the product and registry. Until then, reject/defer. |
| CAS REGISTRY | Use only licensed content or lawfully source-supplied identifiers. Do not reconstruct or redistribute the bulk registry. |
| UMLS and SNOMED CT | Require individual UMLS/Affiliate access, source-by-source license checks, release pinning, and controls on derivative redistribution. |
| NUCC Provider Taxonomy | Complete the American Medical Association commercial-use licensing process before including it in a commercial product. |
| LOINC | Ship the required attribution/license notice, preserve identifiers with permitted display names and version, and filter or honor third-party content terms. |
| NALT | Resolve the conflict between the dataset's CC BY 4.0 notice and broader USDA public-domain/CC0 language against the exact downloaded release. |
| AGROVOC | Track language-specific contributor rights and CC BY 3.0 IGO attribution rather than assuming one license covers every language. |
| WHO ICF | Keep it mapping-only unless the no-derivatives condition is compatible with the exact use; do not publish a modified hierarchy. |
| Open Referral HSDS | Retain CC BY-SA 4.0 attribution, identify local modifications, and obtain a license decision on whether an adapted schema or crosswalk must use the same license. License every referenced external taxonomy separately. |
| Axiom Foundation | Verify the exact repository and release license, redistribution rights for normalized text and bundled material, hosted-service terms if used, and the rights attached to each retained upstream source. Pin the accepted release. No corpus, reverse index, or bill feed may enter production before its target-specific coverage and provenance gates pass. |
| PolicyEngine | Choose hosted or self-hosted operation explicitly. Record hosted API credentials and terms; for self-hosting, meet the GNU Affero General Public License source-offer duties. Review modeled-output redistribution separately. |
| FAST | Retain Open Data Commons Attribution 1.0 notices and use it as a mapping source, not a silent part of the canonical core. |
| PACER and CourtListener | Respect account, fee, membership, privacy, contributed-record, and dataset-specific terms; retain official and platform metadata separately. |
| SAM.gov | Apply API-key/rate limits, role-based fields, and Controlled Unclassified Information boundaries. Public access to one field does not authorize protected entity data. |
| FEC public records | Enforce statutory restrictions on commercial solicitation and uses of individual names and addresses. |
| LegiScan, NASBO, KFF, NAAG, and other nonfederal sources | Verify the exact API, attribution, bulk-download, and redistribution terms before copying data rather than linking to it. |

## Import and governance rules

Every imported resource needs a receipt that records:

1. the exact publisher, source URL, retrieval time, release or effective date,
   media type, byte digest, and access method;
2. the license or terms checked for that release, required attribution, access
   controls, and any limits on redistribution or commercial use;
3. the unmodified source identifier, preferred label, alternate labels,
   status, replacements, hierarchy, and source scheme;
4. the transformation code and version that created the implementation view;
5. validation failures, excluded records, and count reconciliations; and
6. the last successful refresh and the next expected refresh.

Store three assignment states separately:

| State | Meaning | Evidence requirement |
| --- | --- | --- |
| Source-assigned | The publisher attached the term or code to the artifact | Original field, source artifact, source version, and retrieval receipt |
| Machine-assigned | The implementation inferred the term from artifact evidence | Exact supporting passage, model and registry versions, score, and decision trace |
| Reviewed | A reviewer accepted, rejected, or mapped an assignment | Reviewer decision, timestamp, mapping relation, and evidence reference |

Never promote a machine-assigned term into source-assigned data. Never merge
concepts because their labels match. Cross-scheme mappings must identify the
relation—`exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch`, or
`relatedMatch`—and retain the reviewer and evidence.

### Adoption gates

A resource can move from this catalog into a production module only when all
of these checks pass:

- the maintainer, current release, machine-readable source, access method, and
  license are verified;
- the import is deterministic and a second run against the same bytes produces
  the same identifiers and relationships;
- source updates cannot silently delete, rename, or reuse an identifier;
- the module improves candidate recall or a product query on an untouched
  source-family holdout;
- precision, abstention, and cross-facet leakage remain within predeclared
  thresholds;
- a reviewer can trace every result to the source artifact and registry
  version; and
- the system still preserves supported local concepts when no registered term
  fits.

Do not adopt a vocabulary merely because it is comprehensive, machine-readable,
or commonly used in another field. The deciding evidence is whether it improves
the relevant implementation task without turning identifiers, entities, document
genres, or process codes into subjects.

## Recommended implementation order

1. Pin and reconcile the current Federal Register Thesaurus PDF, live API
   topics, and CFR part-to-subject assignments. Publish their differences
   rather than hiding them in one list.
2. Import Congress.gov Policy Areas and Legislative Subject Terms into their
   own schemes. Separate named entities and places from true topical terms
   before proposing a general-core crosswalk.
3. Implement the lossless SKOS-style scheme, relationship, mapping, version,
   license, and receipt model. Migrate no source until round-trip tests preserve
   all identifiers, labels, relationships, and provenance.
4. Capture high-value source-native code lists for current sources first:
   Regulations.gov, Federal Register, Unified Agenda, eCFR/GovInfo,
   Congress/BILLSTATUS, LDA, FEC, courts, USAspending/SAM, and FCC.
5. Run separate subject-module pilots for MeSH, NALT Core, GEMET, and the NASA
   Thesaurus. Do not concatenate their labels; measure activation, candidate
   recall, final precision, abstention, and product-query value per domain.
6. Add health, provider, chemical, fiscal, grant, procurement, workforce,
   geography, and entity code systems only at the source seams that use them.
   Complete each license gate before materializing labels.
7. Add mapping-only resources—FAST, LCSH, EuroVoc, AGROVOC, UMLS, ELI, Akoma
   Ntoso, ORG, and similar models—only when a tested query or export requires
   them.

## Completeness ledger

| Matrix scope | Expected | Represented in the source-family matrix |
| --- | ---: | ---: |
| Current source profiles (`C01-C17`) | 17 | 17 |
| Tier 1 roadmap (`T1-01` through `T1-10`) | 10 | 10 |
| Tier 2 roadmap (`T2-01` through `T2-11`) | 11 | 11 |
| Tier 3 roadmap (`T3-01` through `T3-08`) | 8 | 8 |
| Legacy rescue (`L-01`) | 1 | 1 |
| Current-source completion gaps (`E01-E05`) | 5 | 5 |
| Proposed new source families (`G01-G09`) | 9 | 9 |
| Named roadmap feeds and reference spines | 7 | 7 |
| Named adjacent external systems | 3 | 3 |

The four evidence reports provide the underlying maintainer, URL, format,
maintenance, access, license, role, risk, negative-finding, and per-ID
ledgers. This catalog resolves their overlaps into one recommendation. The
ledger proves research coverage, not implementation or adoption.

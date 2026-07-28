# Health, Social-Service, Geography, Entity, and Specialist Vocabulary Research

<!-- markdownlint-disable MD013 -->

- **Research date:** 2026-07-28
- **Status:** External-source evidence for the concept-tagging design; not an
  adoption decision
- **Assigned scope:** C08 and entity handling across current sources; T1-03;
  the health and social-service parts of T1-04; T2-01, T2-05 through T2-07;
  T3-03 through T3-06; L-01; PolicyEngine joins; and medicine,
  aging/disability/social services, chemicals/environment, agriculture, energy,
  and aerospace specialist modules.

## Decision

Four resources merit evaluation as subject modules:

| Module candidate | Proposed use | Decision gate |
| --- | --- | --- |
| [Medical Subject Headings (MeSH)](https://www.nlm.nih.gov/databases/download/mesh.html) | Medicine and public-health document subjects | Evaluate coverage on CMS, SSA, Medicaid, and health-related regulatory text |
| [National Agricultural Library Thesaurus (NALT) Core](https://lod.nal.usda.gov/nalt/en/) | Agriculture and food document subjects | Resolve conflicting USDA license statements and test regulatory coverage |
| [General Multilingual Environmental Thesaurus (GEMET)](https://www.eionet.europa.eu/gemet/en/exports/rdf/latest) | Environment and environmental-health subjects | Test United States terminology and regulation-specific gaps |
| [NASA Thesaurus](https://www.sti.nasa.gov/nasa-thesaurus/) | Aerospace subjects | Confirm the current release date and change history before ingest |

The remaining resources solve different problems:

- Codes such as ICD-10-CM, HCPCS, CPT, LOINC, RxNorm, and SNOMED CT describe
  diagnoses, services, observations, drugs, or clinical findings. They do not
  form a general document-topic vocabulary.
- NPI, CCN, UEI, CAGE, EIN, FEC committee ID, and FCC FRN identify entities.
  NAICS, NUCC Provider Taxonomy, FEC committee type, and similar lists describe
  an entity's type.
- CMS, ACL, Census, KFF, and SSA dictionaries define source measures and
  observations. They must remain versioned with the data they explain.
- Medicaid authority, status, action, and guidance labels describe legal or
  administrative process.
- UMLS and AGROVOC can map terms across vocabularies. They should not silently
  replace the preferred term in a source module.

Three resources require a license decision before use: CPT, 211HSIS, and bulk
CAS Registry content. Public ingestion should defer them.

## Classification boundary

| Resource kind | What goes in | What comes out | Allowed role |
| --- | --- | --- | --- |
| Subject thesaurus | Text that says what a document discusses | Preferred subject identifiers and evidence spans | **canonical subject module** or **source-assigned evidence** |
| Clinical or service code | A code explicitly present in a record or supported by a licensed mapping | The same code, label, system, and version | **deterministic metadata** or **crosswalk/mapping only** |
| Measure dictionary | A dataset field and its source version | Measure, unit, universe, method, and period | **deterministic metadata** |
| Entity authority | A source identifier or evidence-backed identity match | Normalized entity plus retained source IDs | **entity normalization** |
| Data schema | A structured resource record | Interoperable fields and relationships | **deterministic metadata**, never a subject vocabulary |
| Licensed or stale vocabulary | Candidate terms | No production assignment until the gate is met | **reject/defer** |

## Medicaid, HHS guidance, and CMS administrative standards

### M01 — CMS State Waivers List and managed-care authority values

- **Owner and authority:** Centers for Medicare & Medicaid Services (CMS);
  [State Waivers List](https://www.medicaid.gov/medicaid/section-1115-demo/demonstration-and-waiver-list)
  and [Managed Care Authorities](https://www.medicaid.gov/medicaid/managed-care/managed-care-authorities).
- **Kind and scope:** Official administrative register and code-like authority
  labels for section 1115 demonstrations and section 1915(b)/(c) waivers.
  Section 1915(b)(1) through (b)(4) distinguish freedom of choice, enrollment
  broker, use of savings for additional services, and selective contracting.
- **Representation and maintenance:** Searchable HTML records and linked
  documents. The live list exposes state, authority, status, approval/effective
  dates, and waiver identifiers. Current records include applications,
  amendments, extensions, approvals, withdrawals, monitoring reports, and
  evaluations.
- **Access and license:** Public federal website; no documented bulk API or
  versioned downloadable authority vocabulary was found.
- **Applies to:** T1-03, T2-07, and waiver links in T3-05.
- **Role:** **deterministic metadata** for authority, status, dates, and action;
  **source-assigned evidence** for labels on the source page.
- **Risks:** Artifact labels vary by page and over time. Preserve each raw label
  and source URL. Do not infer a national workflow state from a filename.

### M02 — T-MSIS Data Dictionary and `WAIVER-TYPE`

- **Owner and authority:** CMS; [T-MSIS Data Guide](https://www.medicaid.gov/tmsis/dataguide/data-elements)
  and [`WAIVER-TYPE`](https://www.medicaid.gov/tmsis/dataguide/v3/data-elements/cip002177/).
- **Kind and scope:** Official data dictionary and valid-value list for
  Medicaid/CHIP reporting. `WAIVER-TYPE` covers section 1115, section
  1915(b)(1) through (b)(4), and population-specific section 1915(c) categories
  such as aged, physical disability, intellectual/developmental disability,
  autism, brain injury, HIV/AIDS, and medically fragile populations.
- **Representation and maintenance:** Versioned web documentation; the
  research snapshot showed Data Guide 3.38.0 and effective dates on individual
  values. CMS also publishes [technical instructions](https://www.medicaid.gov/tmsis/dataguide/v4/technical-instructions/).
- **Access and license:** Public federal documentation.
- **Applies to:** T1-03, T2-07, T3-05.
- **Role:** **deterministic metadata** when T-MSIS or an authoritative waiver
  record supplies the value; **crosswalk/mapping only** for waiver population
  normalization.
- **Risks:** This is a claims and beneficiary reporting code list, not a
  document-subject thesaurus. Effective dates and Data Guide version are part
  of the meaning.

### M03 — CMS Home and Community-Based Services taxonomy

- **Owner and authority:** CMS; [T-MSIS appendices, including Appendix B,
  HCBS Taxonomy](https://www.medicaid.gov/tmsis/dataguide/v3/appendices/).
- **Kind and scope:** CMS-approved categories, subcategories, and minimum
  definitions for home and community-based services (HCBS), designed for
  section 1915(c) and 1915(i) reporting.
- **Representation and maintenance:** Appendix tables/PDF within the T-MSIS
  Data Guide. CMS approved the taxonomy in August 2012; the Data Guide is
  versioned separately.
- **Access and license:** Public federal documentation.
- **Applies to:** T1-03, T2-07, T3-05, and health/social topics in T1-04.
- **Role:** **source-assigned evidence** for an explicitly classified service;
  **deterministic metadata** for HCBS service codes; a candidate mapping into a
  broader social-service subject module.
- **Risks:** It classifies services, not every policy topic in a waiver.
  Preserve the Data Guide version and do not expand a minimum definition by
  semantic similarity alone.

### M04 — CMS State Plan Amendment register

- **Owner and authority:** CMS; [Medicaid State Plan Amendments](https://www.medicaid.gov/medicaid/medicaid-state-plan-amendments).
- **Kind and scope:** Official register of State Plan Amendment (SPA)
  transmittals and decisions, with state, transmittal number, date, and status.
- **Representation and maintenance:** Live searchable table and linked
  artifacts; more than 16,000 records were exposed at the research date.
- **Access and license:** Public federal site; no documented versioned public
  topic or action code list was found.
- **Applies to:** T1-03 and related T2-07 state notices.
- **Role:** **deterministic metadata** and **source-assigned evidence**.
- **Risks:** No maintained universal SPA-topic thesaurus surfaced. Preserve raw
  CMS/state labels. Treat application, amendment, renewal, withdrawal,
  approval, disapproval, and effective date as a proposed normalized workflow
  only after source-specific mapping and tests.

### M05 — HHS Guidance Portal metadata

- **Owner and authority:** Department of Health and Human Services (HHS);
  [HHS Guidance Portal](https://www.hhs.gov/guidance/) and
  [Guidance Documents and Practices](https://www.hhs.gov/regulations/guidance-documents.html).
- **Kind and scope:** Current guidance register spanning HHS operating
  divisions. HHS describes guidance as policy statements, manuals, FAQs, and
  other explanations of how it understands and applies existing law. The
  portal exposes issuer, issue date, guidance status, topics, and a downloadable
  artifact.
- **Representation and maintenance:** Searchable HTML records; 4,041 documents
  were listed during research, including July 2026 additions. No supported
  public API or versioned downloadable codelist for portal topics and genres
  was found.
- **Access and license:** Public federal site. The portal warns that guidance
  generally lacks the force and effect of law.
- **Applies to:** Health/social parts of T1-04.
- **Role:** **source-assigned evidence** for portal topic/genre labels and
  **deterministic metadata** for issuer, status, date, revision, supersession,
  and withdrawal.
- **Risks:** SMD letter, State Health Official letter, CMCS Informational
  Bulletin, FAQ, manual update, and transmittal often appear in title/body
  rather than a stable genre field. Preserve raw values and derive normalized
  genre with evidence; never infer legal force from “Final.”

### M06 — CMS Data Element Library and dataset dictionaries

- **Owner and authority:** CMS; [CMS Data Element Library](https://www.cms.gov/newsroom/fact-sheets/cms-data-element-library-fact-sheet),
  [current system record](https://security.cms.gov/pia/data-element-library),
  and [Provider Data Catalog](https://data.cms.gov/provider-data/about).
- **Kind and scope:** Data elements, questions, response options, and
  cross-setting mappings for post-acute care assessments, plus
  dataset-specific dictionaries for Care Compare, Payroll-Based Journal
  staffing, ownership, quality, and other CMS data.
- **Representation and maintenance:** Web application, downloadable files,
  catalog API, and per-dataset dictionaries. The library maps to LOINC and
  SNOMED CT where feasible. Current CMS assessment instruments, such as
  OASIS-E2, carry their own effective dates.
- **Access and license:** Public federal data. CMS requests attribution and
  disclaims endorsement; any embedded third-party terminology retains its own
  license.
- **Applies to:** T2-05, T3-05, L-01 mappings.
- **Role:** **deterministic metadata** and **crosswalk/mapping only**.
- **Risks:** A field label is not a stable concept without dataset, version,
  unit, response set, and effective date. Do not merge same-named measures
  across instruments without a published mapping.

### M07 — Restructured BETOS Classification System (RBCS)

- **Owner and authority:** CMS; [Provider Service Classifications](https://data.cms.gov/provider-summary-by-type-of-service/provider-service-classifications).
- **Kind and scope:** Hierarchical taxonomy that groups Medicare Part B HCPCS
  services into clinically meaningful categories, subcategories, and families.
- **Representation and maintenance:** Downloadable dataset and data dictionary.
  CMS says a technical expert panel updates it annually; the page was modified
  March 9, 2026.
- **Access and license:** Public federal data; CPT-bearing inputs remain subject
  to AMA terms.
- **Applies to:** T2-05 and modeled service analyses related to T3-03.
- **Role:** **crosswalk/mapping only** and **deterministic metadata** for
  Medicare service observations.
- **Risks:** RBCS groups paid Part B services. It is not a health-policy
  subject taxonomy and does not cover Medicaid-only or commercial-only codes.

### M08 — NLM Value Set Authority Center

- **Owner and authority:** National Library of Medicine (NLM);
  [Value Set Authority Center (VSAC)](https://vsac.nlm.nih.gov/) is the official
  repository for value sets used by CMS electronic and digital clinical
  quality measures.
- **Kind and scope:** Versioned sets of codes drawn from LOINC, SNOMED CT,
  RxNorm, ICD, CPT, and other systems for a stated measure or interoperability
  use.
- **Representation and maintenance:** Web search, downloadable XLSX/SVS XML,
  FHIR JSON, and APIs. The May 14, 2026 CMS release supports the 2027
  reporting/performance period.
- **Access and license:** A free UMLS account/license is required for most
  content. Every member code retains the source code system's license; VSAC
  access does not make CPT or another restricted terminology open.
- **Applies to:** T2-05 and quality-measure references in L-01.
- **Role:** **deterministic metadata** for an explicitly named measure release
  and **crosswalk/mapping only**.
- **Risks:** Value-set OID, definition version, expansion version, code-system
  version, and measure reporting period are all required. A value-set member
  is not a general document subject.

## Clinical vocabularies, codes, and licenses

| Candidate | Owner, kind, and scope | Representation and maintenance | Access/license | Applies and role | Main risk |
| --- | --- | --- | --- | --- | --- |
| [Medical Subject Headings (MeSH)](https://www.nlm.nih.gov/databases/download/mesh.html) | National Library of Medicine (NLM); hierarchical vocabulary built to index biomedical literature, with descriptors and supplemental concepts | XML, MARC, and RDF. NLM publishes an annual release; Supplemental Concept and RDF updates run on weekdays. The page exposes the 2026 production DTD; ASCII ended in January 2026 | Free with no NLM fee or royalty under [NLM terms](https://www.nlm.nih.gov/databases/download/terms_and_conditions.html); acknowledge NLM, avoid implied endorsement, and publish the current version or disclose that it is stale | T1-03, health T1-04, T2-06 health actions, T3-05, T3-06, L-01; **canonical subject module** | Biomedical literature coverage may miss program administration, benefits, civil rights, caregiving, and service-delivery language |
| [UMLS Metathesaurus, 2026AA](https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/release/notes.html) | NLM; integrates names and identifiers from 195 source vocabularies | RRF files and UTS services. Release 2026AA was posted May 4, 2026 with 3.53 million concepts and 18.06 million names | UMLS license/account required; each source vocabulary may add restrictions | All health/social mappings; **crosswalk/mapping only** | A UMLS concept does not erase source license or semantics; do not publish restricted source strings through an open registry |
| [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/docs/rxnormfiles.html) | NLM; normalized clinical drug names and relationships | RRF full monthly releases plus weekly updates; July 6, 2026 full release observed | Full content under UMLS terms; the current Prescribable Content subset is available without a UMLS license | Health documents and facility/service data; **entity normalization** for medications and **crosswalk/mapping only** | Drug identity is not a document topic. Distinguish ingredient, strength, dose form, branded drug, and package |
| [SNOMED CT United States Edition](https://www.nlm.nih.gov/healthit/snomedct/us_edition.html) | SNOMED International and NLM National Release Center; clinical findings, procedures, situations, organisms, and other clinical concepts | RF2 distribution; US Edition twice yearly. March 1, 2026 edition observed | Affiliate/UMLS license; US use is available without a fee under the license, with redistribution controls | T2-05, L-01 assessment mappings; **crosswalk/mapping only** | It encodes clinical meaning, not general policy subjects. International and derivative-use restrictions require license review |
| [ICD-10-CM files](https://www.cdc.gov/nchs/icd/icd-10-cm/files.html) | CDC National Center for Health Statistics; diagnosis classification for US morbidity coding | XML, text/PDF tables, guidelines, and addenda; April 1, 2026 FY 2026 release observed | Public US federal distribution; retain version and applicable WHO notices | T2-05, T3-05, T3-06; **deterministic metadata** when supplied and **crosswalk/mapping only** | A diagnosis code cannot be inferred merely because a document discusses a condition; fiscal-year versions and encounter rules matter |
| [HCPCS Level II quarterly files](https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update) | CMS; products, supplies, and services not represented by CPT Level I | Quarterly public-use files; July 2026 update posted June 17, 2026 | Public CMS Level II files; embedded CPT Level I text is not open | T2-05 and modeled utilization; **deterministic metadata** and **crosswalk/mapping only** | Procedure/product codes are not topics; retain code year, modifiers, and effective dates |
| [Current Procedural Terminology (CPT)](https://www.ama-assn.org/practice-management/cpt/cpt-licensing-frequently-asked-questions-faqs) | American Medical Association (AMA); Level I procedure/service codes | Licensed files and APIs; licensing FAQ updated July 14, 2026 | AMA copyright and product license required. AMA terms restrict electronic products and prohibit AI training uses | T2-05 only where a lawful source supplies codes; **reject/defer** for registry ingestion or training | Loading labels into an open concept registry or training corpus can violate the license |
| [LOINC 2.82](https://loinc.org/downloads) | Regenstrief Institute; observations, laboratory tests, surveys, panels, and clinical documents | CSV distribution, free-account download, and [FHIR R4 terminology service](https://loinc.org/fhir/). Version 2.82 released February 24, 2026 | Free commercial/noncommercial use under the [LOINC license](https://loinc.org/license), with attribution, version, and notice requirements; license updated July 21, 2026 | T2-05 and L-01 measures; **deterministic metadata** and **crosswalk/mapping only** | LOINC identifies an observation or instrument item; it is not a general subject vocabulary |

**Clinical boundary:** Of these resources, MeSH was designed for subject
indexing. UMLS maps vocabularies; RxNorm normalizes drugs; SNOMED CT represents
clinical meaning; ICD-10-CM classifies diagnoses; HCPCS/CPT classify billed
services; and LOINC identifies observations and documents.

## Provider and facility entity authorities

| Candidate | Owner, kind, and scope | Representation and maintenance | Access/license | Applies and role | Main risk |
| --- | --- | --- | --- | --- | --- |
| [NPPES NPI files](https://download.cms.gov/nppes/NPI_Files.html) | CMS; National Provider Identifier (NPI), names, addresses, endpoints, and enumerated provider data | Monthly full ZIP/CSV plus weekly increments; Version 2 monthly file dated July 13, 2026 and increment through July 26 observed | Public CMS download | T2-05; **entity normalization** | NPI enumeration does not prove current licensure, credentialing, specialty, or facility ownership |
| [NUCC Health Care Provider Taxonomy](https://nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40/csv-mainmenu-57) | National Uniform Claim Committee; provider type, classification, and specialization codes | CSV; Version 26.1 dated July 1, 2026 | AMA copyright; commercial use requires a license | T2-05; **deterministic metadata** for provider subtype and **entity normalization** | It classifies a provider, not the topic of a document; license terms prevent casual redistribution |
| [CMS Certification Number (CCN)](https://data.cms.gov/resources/medicare-inpatient-hospitals-by-provider-and-service-data-dictionary-0) | CMS; identifier for a Medicare-certified provider/facility, historically called OSCAR number | Present in CMS dataset dictionaries and records; dataset-specific downloads/API | Public CMS data | T2-05; **entity normalization** | A CCN is certification-program identity, not a universal organization ID; facilities can change certification and ownership |
| [Public Provider Enrollment files and methodology](https://data.cms.gov/resources/fee-for-service-public-provider-enrollment-methodology) | CMS/PECOS; public enrollment records using NPI, Provider Enrollment Chain and Ownership System Associate Control (PAC) ID, and enrollment ID | Quarterly public files; linked CSV/data dictionary. One PAC ID can have multiple enrollment IDs | Public subset of PECOS; nonpublic enrollment data remains protected | T2-05; **entity normalization** and ownership crosswalk | Do not treat enrollment ID as an organization ID or expose fields outside the public extract |
| [Care Compare / Provider Data Catalog](https://data.cms.gov/provider-data/about) | CMS; provider/facility profiles, ownership, quality, staffing, and program observations | Bulk CSV, API, and per-dataset dictionaries; rolling updates | Public federal data, attribution requested; no endorsement | T2-05; **entity normalization** plus **deterministic metadata** | Facility keys and measure definitions differ by setting and release. Preserve source dataset and vintage |

Recommended T2-05 identity order is: source facility key and CCN, NPI where
applicable, public PECOS/PAC crosswalk, exact legal name/address, and only then
an evidence-backed graph link. An ownership relationship is time-bounded; it
must not become permanent `sameAs`.

## Aging, disability, social services, and legacy data

### S01 — National Adult Maltreatment Reporting System (NAMRS)

- **Owner and authority:** Administration for Community Living (ACL);
  [NAMRS](https://namrs.acl.gov/home), including Agency, Key Indicators, and
  Case components.
- **Kind and scope:** Adult Protective Services measure definitions, code
  values, and case-reporting data specifications.
- **Representation and maintenance:** Portal, annual reports, PDF
  [code values and definitions](https://pfs2.acl.gov/strapib/2023_NAMRS_Code_Values_and_Definitions_EO_91f833e581.pdf),
  and [case specifications](https://pfs2.acl.gov/strapib/assets/Case_Component_Data_Specifications2024_629da55f7a.pdf).
  The portal was last modified March 19, 2026; documentation anticipates the
  2026 Office of Management and Budget renewal.
- **Access and license:** Public federal reports and documentation; individual
  case data are privacy-sensitive and not equivalent to public aggregates.
- **Applies to:** L-01.
- **Role:** **deterministic metadata** and **source-assigned evidence**.
- **Risks:** Codes change with collection years. Preserve component, reporting
  year, suppression, universe, and version. Never promote case codes to broad
  social-service subjects.

### S02 — National Ombudsman Reporting System (NORS)

- **Owner and authority:** ACL; [Long-Term Care Ombudsman Program](https://acl.gov/programs/Protecting-Rights-and-Preventing-Abuse/Long-term-Care-Ombudsman-Program)
  and the [NORS resource center](https://ltcombudsman.org/nors/).
- **Kind and scope:** Case, complaint, and program reporting tables. Table 2 is
  the controlled [Complaint Code list](https://acl.gov/sites/default/files/programs/2021-11/NORS%20Table%202%20Complaint%20Code%2010-31-2024.pdf).
- **Representation and maintenance:** PDF tables, training materials, and
  annual reporting resources. The current tables took effect October 1, 2021;
  the resource center showed a July 2025 update.
- **Access and license:** Public federal/program materials.
- **Applies to:** L-01 and ombudsman-related T1-04.
- **Role:** **deterministic metadata** and **source-assigned evidence**.
- **Risks:** Complaint codes describe reported issues in a specific program,
  not verified events or general topics. Preserve table version and reporting
  period.

### S03 — Older Americans Act reporting, OAAPS, and AGID outputs

- **Owner and authority:** ACL; [State Program Reports](https://acl.gov/programs/state-program-reports),
  [Older Americans Act Performance](https://acl.gov/programs/performance-older-americans-act-programs),
  and [Older Americans Act Performance System (OAAPS)](https://oaaps.acl.gov/about).
- **Kind and scope:** Program-specific measures for clients, demographics,
  services, expenditures, Title III/VI/VII activities, and performance.
- **Representation and maintenance:** OAAPS restricted-entry application,
  public reports, portal tables/downloads, and collection-specific
  instructions. ACL has renamed and transitioned the former AGing,
  Independence, and Disability (AGID) portal.
- **Access and license:** Public reports/aggregates; submission systems require
  accounts. No stable public AGID API, general controlled vocabulary, or
  versioned cross-program codelist was verified.
- **Applies to:** L-01 and T3-05.
- **Role:** **deterministic metadata**. Snapshot source bytes, dictionaries,
  filter state, and retrieval evidence before semantic normalization.
- **Risks:** Similar labels can have different populations, denominators, and
  collection years. Portal transition creates link-rot and reproducibility
  risk. This is a **negative finding** for a reusable ACL subject thesaurus.

### S04 — International Classification of Functioning, Disability and Health

- **Owner and authority:** World Health Organization (WHO);
  [ICF overview](https://www.who.int/standards/classifications/international-classification-of-functioning-disability-and-health)
  and [release browser](https://icd.who.int/browse/releases/icf/en).
- **Kind and scope:** Classification of body functions/structures, activities,
  participation, and environmental factors.
- **Representation and maintenance:** Online browser and
  [WHO classifications API](https://icd.who.int/docs/icd-api/APIDoc-Version2/);
  a January 2026 release was visible during research.
- **Access and license:** WHO [CC BY-ND 3.0 IGO terms](https://icd.who.int/en/docs/icd11-license.pdf);
  no adaptations under that license.
- **Applies to:** T3-05, T3-06, L-01.
- **Role:** **crosswalk/mapping only** for functioning/disability measures.
- **Risks:** “No derivatives” conflicts with editing or publishing a modified
  local hierarchy. ICF is a functioning classification, not a preferred
  person-language guide or a document-topic core.

### S05 — Open Referral Human Services Data Specification (HSDS)

- **Owner and authority:** Open Referral;
  [HSDS overview](https://docs.openreferral.org/en/latest/hsds/overview.html)
  and [specification repository](https://github.com/openreferral/specification).
- **Kind and scope:** Data-exchange schema for organizations, services,
  locations, programs, schedules, eligibility, and external classifications.
  It is not a service taxonomy.
- **Representation and maintenance:** Canonical JSON Schema, optional tabular
  data package, and OpenAPI interface. Repository release 3.2.3 was dated March
  18, 2026.
- **Access and license:** [CC BY-SA 4.0](https://docs.openreferral.org/en/latest/about/license.html).
- **Applies to:** Social-service entities connected to T1-04, T3-05, L-01.
- **Role:** **deterministic metadata** and entity/service interchange schema.
- **Risks:** HSDS `taxonomy` and `service_at_location` fields do not supply a
  common nationwide classification. Preserve external scheme and concept IDs.

### S06 — 211 Human Services Indexing System (211HSIS)

- **Owner and authority:** 211 LA; [211HSIS overview](https://211hsis.org/taxonomy/what-is-taxonomy).
- **Kind and scope:** More than 10,500 hierarchical service and target-
  population terms for health and human-service resource indexing.
- **Representation and maintenance:** Subscription website and authenticated
  [REST API](https://211hsis.org/docs/index.html). Editors update the working
  copy frequently and generally publish the database quarterly; detailed
  change history requires a subscription.
- **Access and license:** Basic search registration is free. Full definitions,
  filters, and API require a paid annual license. The
  [subscription agreement](https://211hsis.org/library/Subscription_Agreement.pdf)
  limits access, distribution, database use, and delivery; API access is a
  separate purchase.
- **Applies to:** T1-04, T3-05, L-01.
- **Role:** Potential social-service **canonical subject module** only under an
  approved license; current decision is **reject/defer**.
- **Risks:** Copyright and redistribution terms conflict with an open concept
  registry and unrestricted model training. No equally broad, current, open,
  nationwide human-service taxonomy was verified. HSDS is not a substitute.

### S07 — ACL terminology guidance

ACL person-centered and person-first/identity-first language resources provide
editorial guidance, not stable controlled concepts. Preference varies by
person and community. Use the source's exact language, preserve aliases for
retrieval, and do not encode one form as universally “correct.” This is a
**negative finding** for a canonical ACL terminology module.

## Geography and demographic measures

| Candidate | Owner, kind, and scope | Representation and maintenance | Access/license | Applies and role | Main risk |
| --- | --- | --- | --- | --- | --- |
| [American Community Survey API variables](https://api.census.gov/data/2024/acs/acs1/spp/variables.html) | US Census Bureau; dataset variables, groups, concepts, universes, estimates, annotations, and margins of error | JSON API and dataset metadata by year/product; Census API guidance updated May 12, 2026 | Public federal data; API key needed above anonymous limits | T2-01, T3-03, T3-05, T3-06; **deterministic metadata** | A variable ID only has meaning with product, table/group, universe, vintage, estimate/MOE pair, and geography |
| [TIGER/Line technical documentation](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/tiger-geo-line.html) | Census Bureau; legal/statistical area identifiers, boundaries, feature classes, and spatial relationships | Shapefiles/geodatabases and annual technical documentation; 2025 release documentation observed | Public federal data | T2-01 and all district joins; **deterministic metadata** and **entity normalization** for Census geographies | Boundaries and codes change. A ZIP Code is not a Census ZCTA; district allocations need a stated method |
| [Census geographic relationship files](https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.2020.html) | Census Bureau; cross-geography and over-time relationships | Downloadable text/CSV relationship files by vintage | Public federal data | `geo_crosswalks` in T2-01 and PolicyEngine joins; **crosswalk/mapping only** | A many-to-many overlap is not exact identity. Retain source/target vintages, overlap measure, allocation rule, and residual |
| [Geographic Names Information System (GNIS)](https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data) | US Geological Survey / US Board on Geographic Names; official geographic names, feature IDs, classes, and coordinates | CSV/TXT, GeoPackage, and web services; data updated every other month | Public domain US government data | T2-01 and entity places across all sources; **entity normalization** | GNIS names points/features; it does not supply administrative boundaries or district membership |

No topical tags should be assigned to T2-01 observations. The full join receipt
must contain the Census product/vintage, variable, geography, source boundary
vintage, relationship file, allocation method, estimate, margin of error, and
universe.

## Entity authorities and cross-corpus joins

### E01 — SAM.gov UEI, CAGE, and NAICS

- **Owner and authority:** General Services Administration (GSA)
  [Entity Management API](https://open.gsa.gov/api/entity-api/);
  GSA Unique Entity Identifier (UEI); Defense Logistics Agency
  [Commercial and Government Entity (CAGE) code](https://www.dla.mil/Working-With-DLA/Applications/Details/Article/2920893/cage-code-commercial-and-government-entity-code/);
  and Census Bureau [North American Industry Classification System
  (NAICS)](https://www.census.gov/naics/).
- **Kind and scope:** UEI identifies federal-award entities; CAGE identifies a
  specific facility/location doing business with the government; NAICS
  classifies economic activity.
- **Representation and maintenance:** SAM JSON API; current DLA CAGE bulk
  publication; downloadable NAICS tables. NAICS 2022 is current while the 2027
  revision is in progress.
- **Access and license:** SAM API key. The API separates public data from
  Controlled Unclassified Information (CUI); CUI is not authorized for public
  ingest. Public federal code lists are available without a proprietary
  vocabulary license.
- **Applies to:** C08 `sam_entities`, C15 `usaspending_recipients`, and T3-04.
- **Role:** **entity normalization**. NAICS is **deterministic metadata** for
  entity industry, never a document subject.
- **Risks:** UEI identifies a registration, CAGE a facility, and NAICS an
  industry; they are not interchangeable. Retain hierarchy, status, effective
  dates, and public/CUI provenance.

### E02 — IRS EIN, EO BMF, TEOS, Form 990, and NTEE

- **Owner and authority:** Internal Revenue Service (IRS);
  [Exempt Organizations Business Master File Extract (EO BMF)](https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract-eo-bmf),
  [Tax Exempt Organization Search (TEOS) bulk data](https://www.irs.gov/charities-non-profits/tax-exempt-organization-search-bulk-data-downloads),
  and [Form 990 XML downloads](https://www.irs.gov/charities-non-profits/form-990-series-downloads).
- **Kind and scope:** Employer Identification Number (EIN), organization
  status/type, National Taxonomy of Exempt Entities (NTEE) code, exemption
  status, and public tax filings.
- **Representation and maintenance:** EO BMF CSV by state/region, monthly TEOS
  text/XML, annual/monthly Form 990 XML and schemas. EO BMF posting dated July
  14, 2026 and Form 990 page reviewed July 17, 2026.
- **Access and license:** Public IRS data. Public-disclosure rules exclude some
  filing content; ingest only the released fields/files.
- **Applies to:** T3-04.
- **Role:** **entity normalization** using EIN; NTEE and subsection are
  **deterministic metadata** for nonprofit entity type.
- **Risks:** Headquarters state is not operational coverage. Chapters and
  parents can have distinct EINs; names and addresses change. Keep filing
  period and source extract. NTEE is an entity classification, not a document
  topic.

### E03 — ProPublica Nonprofit Explorer

- **Owner and authority:** ProPublica;
  [Nonprofit Explorer API v2](https://projects.propublica.org/nonprofits/api).
- **Kind and scope:** Search/reference interface over IRS organization,
  filing, and extracted financial data keyed by EIN.
- **Representation and maintenance:** Public JSON GET API; the API page showed
  a July 2026 update during research. The API warns that it is a work in
  progress and can change.
- **Access and license:** Use constitutes agreement to ProPublica Data Terms;
  rate limits apply to some documents.
- **Applies to:** T3-04 only as the proposed reference spine.
- **Role:** **external join** and **entity normalization**, not an ingestion
  corpus.
- **Risks:** IRS is the authority for EIN/filing data. Store ProPublica URL,
  response date, matched EIN, and match evidence; do not copy the entire
  ProPublica corpus or treat search ranking as identity proof.

### E04 — OpenFEC committee identifiers and classifications

- **Owner and authority:** Federal Election Commission (FEC);
  [OpenFEC API](https://api.open.fec.gov/developers) and
  [committee type code descriptions](https://www.fec.gov/campaign-finance-data/committee-type-code-descriptions/).
- **Kind and scope:** FEC committee/candidate IDs, committee type, designation,
  party, sponsor, filings, and financial records.
- **Representation and maintenance:** REST/Swagger API and bulk files; API data
  update nightly. Financial data are organized by `committee_id`.
- **Access and license:** API key/limits and terms of service. Contributor lists
  cannot be used for commercial solicitation and have statutory use
  restrictions.
- **Applies to:** C10 `fec_committees` and T3-04.
- **Role:** **entity normalization**; committee type is **deterministic
  metadata**.
- **Risks:** Committee characteristics and candidate relationships change by
  cycle. A sponsor or connected organization is not automatically the same
  legal entity as its committee.

### E05 — FCC Registration Number

- **Owner and authority:** Federal Communications Commission (FCC),
  Commission Registration System (CORES); FCC describes the FCC Registration
  Number (FRN) as a ten-digit identifier for a person or entity doing business
  with the Commission.
- **Kind and scope:** FCC-specific registrant identifier and self-selected
  entity type.
- **Representation and maintenance:** CORES account system; FRNs appear in
  public licensing and filing datasets where released.
- **Access and license:** Registration/account system; only public fields from
  each FCC source may be ingested. Taxpayer and personal data used to create
  an FRN are not public normalization inputs.
- **Applies to:** C16 `fcc_proceedings`, C17 `fcc_filings`, and T3-04 when a
  public filing supplies FRN.
- **Role:** **entity normalization**.
- **Risks:** Subsidiaries may have separate FRNs and people can also hold FRNs.
  FRN is FCC-scoped, not a universal organization ID.

### E06 — Entities without a dependable public authority

No dependable nationwide identifier was found for:

- C09 lobbying clients and registrants across filings and amendments;
- C14 court parties across courts and cases;
- C17 filer names, authors, and law firms when no public FRN appears;
- public commenters in C03; or
- targets and coalition organizations in T2-06 state AG actions.

For these sources, retain source IDs where available and use conservative
name/address/domain evidence. Record match method, evidence fields, confidence,
model/rule version, and reviewer outcome. Never assert `sameAs` from a fuzzy
name match. Public-comment privacy constraints take priority over graph
completion.

## Chemicals and environment

| Candidate | Owner, kind, and scope | Representation and maintenance | Access/license | Applies and role | Main risk |
| --- | --- | --- | --- | --- | --- |
| [EPA Substance Registry Services (SRS)](https://sor.epa.gov/sor_internet/registry/sysofreg/sorservices/sorServices.html) | Environmental Protection Agency (EPA); substances, synonyms, identifiers, EPA lists, and mappings among EPA systems | REST/JSON SRS services plus System of Registries terminology/code services; some Synaptica services require authentication | Public EPA APIs with endpoint-specific access | Environment/chemical documents in current and roadmap sources; **entity normalization** for substances and **crosswalk/mapping only** | Substance, mixture, and structure identity differ. An EPA list membership is legal/administrative metadata, not a topic |
| [CompTox Chemicals Dashboard / DSSTox](https://www.epa.gov/comptox-tools/computational-toxicology-and-exposure-apis) | EPA; curated chemical substances (DTXSID), structures/compounds (DTXCID), synonyms, properties, toxicity, and exposure data | Public APIs, dashboard batch search, and downloads; actively maintained | EPA states CompTox API data are public and free of copyright restrictions, including commercial use; upstream fields may retain source terms | Chemicals/environment module; DTXSID as **entity normalization**, DTXCID for structure, other IDs as **crosswalk/mapping only** | Do not collapse a salt, mixture, substance, and structure. Carry curation level and provenance for CAS numbers and synonyms |
| [Toxic Substances Control Act Chemical Substance Inventory](https://www.epa.gov/tsca-inventory/about-tsca-chemical-substance-inventory) | EPA; substances manufactured, processed, or imported under TSCA and regulatory status | Public inventory download updated twice yearly; June 10, 2026 update observed | Public version omits confidential identities | Chemical records; **deterministic metadata** for inventory/status | The public file is not conclusive for confidential substances; EPA's master inventory controls compliance. Membership is not a subject |
| [CAS REGISTRY](https://www.cas.org/cas-data/cas-registry) | Chemical Abstracts Service; proprietary chemical registry and CAS Registry Numbers | Licensed data/services; CAS updates the registry daily | CAS copyright/license. Public/commercial platforms must use CAS licensing or a verified partner | Only where lawfully supplied; **crosswalk/mapping only**, otherwise **reject/defer** | CAS numbers are ubiquitous but the compiled registry and names are not open. Do not bulk reproduce or use unlicensed content for training |
| [GEMET 4.2.3](https://www.eionet.europa.eu/gemet/en/exports/rdf/latest) | European Environment Information and Observation Network / European Environment Agency; multilingual environmental concepts | SKOS/RDF exports and [REST web services](https://www.eionet.europa.eu/gemet/en/webservices/); version 4.2.3 observed | CC BY 4.0 | Environmental documents across current/roadmap sources; **canonical subject module** candidate | European policy vocabulary and translations may not fit US statutory language; evaluate mappings and abstention behavior |
| [NASA GCMD Science Keywords](https://gcmd.earthdata.nasa.gov/KeywordViewer/scheme/sciencekeywords/27478148-b4b6-4c89-8829-08d2ee7bfe10/) | NASA Global Change Master Directory; Earth-science disciplines, phenomena, measurements, platforms, and instruments | RDF/JSON/XML/CSV [bulk files](https://gcmd.earthdata.nasa.gov/static/kms/); Science Keywords 23.8 dated April 30, 2026 | Public NASA distribution; retain version/attribution | Earth-science/environment and aerospace mapping; **crosswalk/mapping only** pending evaluation | Built for data discovery, not regulatory subjects; instrument/platform branches must not become policy topics |

## Agriculture

### A01 — National Agricultural Library Thesaurus

- **Owner and authority:** US Department of Agriculture National Agricultural
  Library; [NALT](https://lod.nal.usda.gov/nalt/en/).
- **Kind and scope:** Agricultural, food, biological, and related concepts.
  NALT Core has about 14,000 concepts; NALT Full has 76,691 English/Spanish
  concepts.
- **Representation and maintenance:** SKOS, RDF/XML, Turtle, and linked-data
  browser. The site identifies NALT 2024 and says the vocabulary updates
  annually; the page was last modified July 16, 2024.
- **Access and license:** USDA pages conflict: the NALT distribution page
  displays CC BY 4.0 while the NAL web-policy page describes NAL content as
  public domain/CC0. Capture the exact release notice and obtain owner
  confirmation before redistribution.
- **Applies to:** Agriculture specialist module across current and proposed
  document sources.
- **Role:** NALT Core is a **canonical subject module** candidate; NALT Full is
  mainly **crosswalk/mapping only** and entity support.
- **Risks:** Organisms, chemicals, commodities, products, and subjects occupy
  the same broad resource. Preserve concept type and do not assign entity-only
  branches as topics.

### A02 — AGROVOC

- **Owner and authority:** Food and Agriculture Organization of the United
  Nations (FAO); [AGROVOC](https://agrovoc.fao.org/).
- **Kind and scope:** Multilingual agriculture, food, forestry, fisheries, and
  environment thesaurus.
- **Representation and maintenance:** SKOS download, SPARQL, REST, and browser.
  The browser showed 41,628 concepts and a May 15, 2026 modification date.
- **Access and license:** [FAO language content is CC BY 3.0 IGO](https://aims.fao.org/standards/agrovoc/access-agrovoc);
  other-language content can carry contributor rights.
- **Applies to:** Agriculture module and multilingual search.
- **Role:** **crosswalk/mapping only** and multilingual expansion; evaluate as
  a canonical alternative only if international coverage is a product goal.
- **Risks:** Language-by-language rights and international policy terminology
  complicate redistribution. Do not merge AGROVOC and NALT identifiers merely
  because labels match.

## Energy and aerospace

| Candidate | Owner, kind, and scope | Representation and maintenance | Access/license | Applies and role | Main risk |
| --- | --- | --- | --- | --- | --- |
| [OSTI Semantic Thesaurus](https://www.osti.gov/dataexplorer/biblio/1668761) | Department of Energy Office of Scientific and Technical Information; energy-science subject terms and relationships | RDF/SKOS dataset published in 2020. OSTI search still references its thesaurus, but no newer public release or changelog was verified | Public OSTI dataset; confirm current distribution notice | Energy module; **crosswalk/mapping only**, canonical use **reject/defer** | Public artifact appears stale and version history is opaque |
| [INIS Multilingual Thesaurus](https://nkp.iaea.org/) | International Atomic Energy Agency; nuclear science and energy terminology in eight languages | Live INIS search thesaurus; latest public download found was an October 2019 PDF | No current machine-readable public download and license were verified | Energy/nuclear module; **source-assigned evidence** for INIS records, otherwise **reject/defer** | Stale download, unclear reuse rights, and no reproducible current export |
| [NASA Thesaurus](https://www.sti.nasa.gov/nasa-thesaurus/) | NASA Scientific and Technical Information Program; authorized aerospace and related subject terms, definitions, and USE references | More than 18,400 terms; RDF/SKOS, OWL, ZThes, and CSV. Site current in April 2026, but linked data-publication provenance dates to 2012 and no clear release date was exposed | US government public-use distribution; retain NASA attribution/release receipt | Aerospace module; gated **canonical subject module** candidate | Freshness and change history are unclear; audit removed/deprecated terms before adoption |
| [NASA Technology Taxonomy 2024](https://techport.nasa.gov/taxonomy) | NASA TechPort; 17 high-level technology areas with lower-level classifications | Browser/download plus [T-Rex/TechPort API](https://techport.nasa.gov/help/api); current taxonomy labeled 2024 | Public NASA API/data | NASA project/technology records; **source-assigned evidence** and **deterministic metadata** | Technology readiness classification is not a general aerospace subject thesaurus |

No clearly current, openly versioned, downloadable US energy-policy thesaurus
was found. GEMET can cover environmental and climate policy; technical energy
terms from OSTI/INIS should remain a deferred evaluation set until their owners
provide a current, licensed export.

## State actions, modeled estimates, waitlists, and SSA operations

### O01 — Open States classifications

- **Owner and authority:** Plural/Open States;
  [API v3](https://docs.openstates.org/api-v3/) and
  [categorization documentation](https://docs.openstates.org/data/categorization/).
- **Kind and scope:** Normalized bill, action, vote, organization, and person
  data. State-supplied bill subjects vary by legislature.
- **Representation and maintenance:** JSON API v3 with key; maintained
  documentation and source adapters.
- **Access and license:** Public API under [Plural terms](https://open.pluralpolicy.com/tos/)
  and usage limits.
- **Applies to:** Cross-links around T2-06, not as the state-AG source itself.
- **Role:** **deterministic metadata** for Open States process codes and
  **source-assigned evidence** for raw state subjects.
- **Risks:** State bill subjects are not a common cross-state thesaurus.
  Legislative action codes do not classify AG complaints or comment letters.

### O02 — National Association of Attorneys General data

- **Owner and authority:** National Association of Attorneys General (NAAG);
  [Multistate Settlements Database](https://www.naag.org/news-resources/research-data/multistate-settlements-database/)
  and [collection methods](https://www.naag.org/news-resources/research-data/multistate-settlements-database/multistate-data-collection-methods/).
- **Kind and scope:** Reference database for verified multistate settlements,
  with legal area, issue, company, participating states, money, and source
  records; separate antitrust litigation database and policy-letter pages.
- **Representation and maintenance:** Searchable web database updated on a
  rolling basis.
- **Access and license:** Public browse; no documented versioned vocabulary,
  bulk API, or open redistribution license was found.
- **Applies to:** T2-06.
- **Role:** **external join** and **source-assigned evidence** only.
- **Risks and negative finding:** The settlement database excludes informal
  investigations, most unresolved actions, criminal matters, and Medicaid
  fraud cases. NAAG issue labels are useful evidence but not a complete,
  versioned AG action/subject vocabulary. Preserve each state office's raw
  genre/action and prioritize the complaint, brief, or letter.

### O03 — KFF HCBS waitlist measures

- **Owner and authority:** KFF;
  [2025 waitlist analysis](https://www.kff.org/medicaid/a-look-at-waiting-lists-for-medicaid-home-and-community-based-services-from-2016-to-2025/)
  and [state indicator](https://www.kff.org/medicaid/state-indicator/number-of-people-waiting-for-hcbs-by-target-population-and-whether-states-screen-for-eligibility/).
- **Kind and scope:** Annual survey measures for people on waiting, interest,
  or referral lists by state and target population, plus whether a state
  screens for eligibility.
- **Representation and maintenance:** Interactive tables/downloads and annual
  survey methodology. The 2025 data came from the 23rd survey of all states and
  DC, conducted April through July 2025.
- **Access and license:** Public presentation; verify KFF terms before bulk
  republication. State source pages remain the authority for state-published
  values.
- **Applies to:** T3-05.
- **Role:** **deterministic metadata** and external observation source, not a
  subject vocabulary.
- **Risks and negative finding:** States use “waiting,” “interest,” and
  “referral” lists differently, do not all screen eligibility, and can
  double-count people across waivers. No maintained national waitlist measure
  vocabulary was found. Preserve wording, screening rule, target population,
  program, year, deduplication, source, and survey method.

### O04 — SSA Open Data dictionaries

- **Owner and authority:** Social Security Administration (SSA);
  [Open Data](https://www.ssa.gov/data/) and
  [State Agency Monthly Workload Data](https://www.ssa.gov/disability/data/ssa-sa-mowl.htm).
- **Kind and scope:** Dataset-specific measures for field-office/service
  activity, disability applications, state Disability Determination Services
  workloads, reconsiderations, backlogs, outcomes, and processing time.
- **Representation and maintenance:** CSV/XLS files with page-hosted data
  dictionaries and change histories. The monthly disability file has 71 data
  elements and data from October 2000 forward; SSA calls DIODS its definitive
  state-agency workload store. Other portal datasets have individual update
  dates.
- **Access and license:** Public federal aggregate data; SSA withholds
  sensitive records under privacy and tax laws.
- **Applies to:** T3-06 and SSA-related T1-04.
- **Role:** **deterministic metadata**.
- **Risks and negative finding:** No shared, maintained SSA operations
  vocabulary spanning office closure, wait time, and disability backlog was
  found. Each measure needs its dataset, definition, period type, geography,
  exclusions, update date, and correction policy. A “favorable
  determination” is not necessarily a benefit award.

### O05 — PolicyEngine variables and parameters

- **Owner and authority:** PolicyEngine;
  [US API](https://legacy.policyengine.org/us/api),
  [model data pipeline](https://www.policyengine.org/us/model/data/pipeline),
  and package repositories.
- **Kind and scope:** Tax-benefit model variables, policy parameter paths,
  baseline/reform calculations, calibrated microdata, and geography-specific
  outputs.
- **Representation and maintenance:** Authenticated calculation and metadata
  APIs plus versioned open-source Python packages. The hosted API and package
  releases can change independently.
- **Access and license:** Hosted API requires client credentials and terms;
  self-hosted PolicyEngine packages use AGPL licenses. Verify terms for output
  redistribution and service operation.
- **Applies to:** T3-03 and geographic joins to T2-01.
- **Role:** **external join** and **deterministic metadata**, never a RefSpec
  subject vocabulary.
- **Risks:** A modeled value is an estimate, not an observed fact. Store model
  package/commit, API version, parameter path and changes, baseline/reform,
  input assumptions, dataset/calibration vintage, output variable, geography,
  uncertainty, run time, and result receipt. Do not promote PolicyEngine labels
  to canonical concepts.

## Adoption and validation rules

1. Load subject candidates into separate named modules. Never create one merged
   hierarchy.
2. Store `scheme_id`, concept ID, preferred label, aliases, hierarchy,
   definition, release, license, retrieval URL/time, and digest.
3. Treat every mapping as its own assertion with source, target, relation
   (`exact`, `close`, `broad`, or `narrow`), method, evidence, and reviewer.
4. Preserve every source code and raw label even when a normalized value is
   added.
5. Do not infer clinical, entity, or process codes from broad text similarity.
   Require an explicit source value or code-specific evidence rule.
6. Keep source-assigned evidence separate from model-produced assignments.
7. Evaluate each subject module on held-out text for precision, coverage,
   hierarchy errors, and abstention. Review specialist assignments blind.
8. Run a license gate before materializing labels from UMLS sources, SNOMED CT,
   NUCC, CPT, 211HSIS, CAS, WHO ICF, or multilingual AGROVOC content.
9. Version geography and observation joins. A current label cannot repair an
   old boundary, denominator, or measure definition.
10. An external reference result is not identity proof. Keep the match evidence
    and allow links to be reversed.

## Coverage ledger

| Assigned scope | Finding | Coverage |
| --- | --- | --- |
| C08 `sam_entities` | UEI + CAGE + public SAM data for identity; NAICS as industry metadata; CUI excluded | Covered by E01 |
| Entity aspects across current sources | FEC ID, EIN, UEI, CAGE, CCN/NPI/PAC, and FCC FRN where source-supported; explicit no-authority rule for lobbying, court, comment, and filer names | Covered by E01–E06 and provider authority table |
| T1-03 Medicaid waivers/SPAs | CMS authority/status registers, T-MSIS `WAIVER-TYPE`, HCBS service taxonomy, SPA register; no universal waiver/SPA topic or action vocabulary | Covered by M01–M04 |
| Health/social T1-04 guidance | HHS portal metadata plus MeSH/social-service candidates; genres derived with evidence; no stable cross-division genre/topic codelist found | Covered by M05, clinical table, S05–S07 |
| T2-01 district demographics/crosswalks | ACS variables, TIGER geographies, relationship files, GNIS; all are measures/places, not topics | Covered by geography section |
| T2-05 CMS facilities/staffing/ownership | NPI, NUCC, CCN, public PECOS/PAC, Care Compare dictionaries, CMS DEL, LOINC/SNOMED mappings, RBCS, VSAC | Covered by M06–M08, clinical and provider tables |
| T2-06 state AG actions | Primary artifact + raw state action; NAAG/Open States only as external/source evidence; no complete national AG action or topic vocabulary | Covered by O01–O02 |
| T2-07 state waiver notices | Reuse federal authority/service mappings but preserve separate state notice, comment period, raw action/status, and later federal link | Covered by M01–M04; national state-notice vocabulary not found |
| T3-03 PolicyEngine estimates | Model variables/parameters and Census geography are run metadata, not topics or observations of fact | Covered by O05 and geography section |
| T3-04 cross-corpus entity graph | IRS/ProPublica EIN spine, OpenFEC committee spine, SAM/USASpending UEI, FCC FRN, provider IDs; conservative evidence for name-only sources | Covered by E01–E06 |
| T3-05 HCBS waitlists | KFF/state raw measures + CMS HCBS/waiver population mappings; no national harmonized waitlist measure vocabulary | Covered by M02–M03 and O03 |
| T3-06 SSA operations | SSA dataset dictionaries; no shared operations vocabulary across closures, wait times, and backlogs | Covered by O04 |
| L-01 AGID/OAA/NORS/NAMRS rescue | Snapshot first; preserve collection-specific codes, measures, and versions; no general ACL subject thesaurus | Covered by S01–S04 and S07 |
| Medicine module | MeSH candidate; UMLS mapping; clinical code systems kept out of the subject hierarchy | Covered by clinical section |
| Aging/disability/social-service module | 211HSIS is strongest taxonomy but license-gated; ICF is mapping only; ACL lists remain source-specific | Covered by S01–S07 |
| Chemicals/environment module | GEMET subject candidate; DTXSID primary open chemical identity; SRS/TSCA/CAS roles separated | Covered by chemicals/environment section |
| Agriculture module | NALT Core candidate with license clarification; AGROVOC mapping/multilingual option | Covered by agriculture section |
| Energy module | OSTI and INIS deferred because current reproducible releases/licenses were not verified; no open current US energy-policy thesaurus found | Covered by energy/aerospace section |
| Aerospace module | NASA Thesaurus candidate after freshness audit; Tech Taxonomy as source classification; GCMD as mapping | Covered by energy/aerospace and environment sections |
| PolicyEngine external-join implications | Full versioned run receipt required; output remains modeled estimate and external reference | Covered by O05 |

<!-- markdownlint-disable MD013 -->

# Regulatory and Legal Vocabulary Research

> **Status:** Evidence report for catalog design; not an adoption decision
>
> **Date checked:** 2026-07-28
>
> **Scope:** `C01-C06`, `C13-C14`, `C16-C17`, `T1-01`, `T1-02`, `T1-04`, `T1-10`, `T2-02`, `T2-03`, `T3-01`, `E01-E03`, `E05`, `G01-G05`, and `G09` in the [source and document type matrix](../../source-document-type-matrix-2026-07-28.md)
>
> **Architecture reference:** [Concept Tagging Architecture Research Proposal](../../concept-tagging-architecture-proposal-2026-07-28.md)

## Result

The evidence supports one official United States regulatory subject module: the **Federal Register Thesaurus of Indexing Terms**. It does not support one universal legal-document taxonomy.

A RefSpec implementation should use the other official resources in four
narrower ways:

1. Preserve source-assigned labels as evidence. Federal Register topics and agency-supplied Lists of Subjects belong here.
2. Preserve identifiers, stages, filing types, dispositions, and legal hierarchy as deterministic metadata. These values explain what a record is or where it sits in a process; they do not say what the text is about.
3. Use broad library and legal-document models only for crosswalks. FAST, Library of Congress Subject Headings, EuroVoc, Akoma Ntoso, and the European Legislation Identifier can improve interoperability, but none should replace United States source labels.
4. Keep project-owned normalized classes small, versioned, and reversible. Several source families have no maintained public vocabulary at all.

This conclusion matches the proposal's typed, source-aware design. It also prevents three common errors:

- treating a document genre such as `Notice` as a subject;
- treating a process state such as `Final Rule` or `Concluded` as a subject; and
- treating a platform-specific filing description as a government-wide legal class.

## Evidence standard and role meanings

This report records only artifacts that expose terms, codes, identifiers, or data-model elements relevant to the assigned source families. A resource's name alone did not qualify it.

The **role** values below use the catalog's required choices:

- **canonical subject module** — approved terms that can serve as first-class topical concepts;
- **source-assigned evidence** — labels supplied by the issuing or indexing source;
- **deterministic metadata** — identifiers, legal hierarchy, stages, genres, statuses, and dates copied or deterministically derived from authoritative data;
- **entity normalization** — authoritative organization or jurisdiction identifiers and names;
- **crosswalk/mapping only** — interoperability aid, never the source of a gold label by itself;
- **reject/defer** — out of scope, insufficiently maintained, proprietary, or aimed at a different problem.

“Checked 2026-07-28” means the artifact or live service was reachable during this research. It does not assert that the owner revised the vocabulary on that date.

## Candidate records

### R01 — Federal Register Thesaurus of Indexing Terms

- **Owner and authoritative URL:** Office of the Federal Register (OFR), National Archives and Records Administration; [current PDF](https://www.archives.gov/federal-register/cfr/thesaurus.pdf).
- **Resource kind and scope:** controlled subject thesaurus for Federal Register and Code of Federal Regulations indexing. The artifact contains preferred terms and “used for” references. It is a subject vocabulary, not a document-type list.
- **Representation and access:** PDF only at the authoritative location; no official Simple Knowledge Organization System (SKOS) file or public vocabulary API was found.
- **Maintenance evidence:** the [2024 CFR Subject and Agency Index](https://www.govinfo.gov/content/pkg/GPO-CFR-INDEX-2024/pdf/GPO-CFR-INDEX-2024-2.pdf) identifies a version revised January 1, 2024. [1 CFR § 18.20](https://www.govinfo.gov/content/pkg/CFR-2025-title1-vol1/pdf/CFR-2025-title1-vol1-chapI.pdf) requires agencies to use thesaurus terms for Rules and Proposed Rules and permits non-thesaurus terms when appropriate thesaurus terms are also supplied.
- **Access and license constraints:** the PDF is public. [1 CFR § 2.6](https://www.govinfo.gov/content/pkg/CFR-2025-title1-vol1/pdf/CFR-2025-title1-vol1-chapI.pdf) permits unrestricted reproduction of material in regular and special editions of the Federal Register. Store the edition date because terms can change.
- **Source families:** `C04`, `C05`, `C06`, `T1-02`, `E02`, `E03`; mapping support for `T1-04`, `T3-01`, and `G09`.
- **Recommended role:** **canonical subject module** for federal regulatory subjects; **source-assigned evidence** when a source record carries an actual term; **crosswalk/mapping only** outside its federal regulatory scope.
- **Use and risks:** ingest the authoritative PDF into a versioned project representation, preserve preferred/non-preferred relations, and retain the source edition. Agency-added List of Subjects terms are valid source evidence but are not automatically canonical thesaurus entries. CFR Lists of Subjects should rank candidates for `C06`; they should not become section-level gold labels without text evidence.

### R02 — Faceted Application of Subject Terminology (FAST)

- **Owner and authoritative URL:** OCLC Research; [dataset downloads](https://www.oclc.org/research/areas/data-science/fast/download.html) and [ODC-By license](https://www.oclc.org/research/areas/data-science/fast/odcby.html).
- **Resource kind and scope:** large faceted authority derived from Library of Congress Subject Headings. Facets include topical, geographic, form/genre, corporate name, personal name, event, and others.
- **Representation and access:** MARC XML, ISO MARC, and Resource Description Framework (RDF) N-Triples bulk files.
- **Maintenance evidence:** OCLC states that FAST was last updated October 10, 2024.
- **Access and license constraints:** Open Data Commons Attribution 1.0 requires attribution; the license governs the database and not necessarily every item of embedded content.
- **Source families:** cross-cutting support for `C02`, `C04-C06`, `C13`, `C17`, `T1-04`, `T2-02`, `T3-01`, `E02-E03`, `E05`, and `G01-G04`, `G09`.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** FAST can supply broader/narrower lookup targets and external identifiers after an implementation has established a source-supported concept. Its scale, mixed facets, library focus, and October 2024 update make it unsuitable as the core regulatory subject module.

### R03 — Library of Congress Subject Headings

- **Owner and authoritative URL:** Library of Congress; [free LCSH PDF files](https://www.loc.gov/aba/publications/FreeLCSH/freelcsh.html) and [Linked Data Service](https://id.loc.gov/authorities/subjects.html).
- **Resource kind and scope:** general-purpose bibliographic subject heading authority with preferred and variant labels, broader/narrower relationships, and pre-coordinated headings.
- **Representation and access:** current edition as PDFs; authority records through `id.loc.gov` in RDF and other linked-data representations. Classification Web Plus offers subscription functionality.
- **Maintenance evidence:** the 47th edition selected data in April 2026; the Library warns against using earlier editions for current cataloging.
- **Access and license constraints:** the PDFs and linked-data records are public; enhanced Classification Web access is subscription-based.
- **Source families:** the same broad set as R02, especially `C13-C14`, `T2-02`, `G01`, `G03-G04`, and state sources.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** use stable Library identifiers when an evaluated mapping exists. LCSH's cataloging rules and pre-coordination make direct document classification difficult and can hide which part of a heading the source text supports.

### R04 — EuroVoc

- **Owner and authoritative URL:** Publications Office of the European Union; [EuroVoc concept scheme](https://op.europa.eu/en/web/eu-vocabularies/concept-scheme/-/resource?uri=http%3A%2F%2Feurovoc.europa.eu%2F100141).
- **Resource kind and scope:** multilingual thesaurus for European Union activities and public policy.
- **Representation and access:** SKOS/RDF downloads and EU Vocabularies services.
- **Maintenance evidence:** EU Vocabularies exposed the current `4.24` scheme during the check.
- **Access and license constraints:** public download; EU reuse conditions and attribution requirements apply.
- **Source families:** optional mapping for `C04-C06`, `T1-04`, `T3-01`, `G01-G03`, and `G09`.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** useful for international interoperability, not as evidence that a United States source carries an EU policy concept. EU institutional and legal context can create false equivalence.

### R05 — Federal Register native document categories, topics, and agency list

- **Owner and authoritative URLs:** OFR/NARA; [Federal Register API documentation](https://www.federalregister.gov/developers/documentation/api/v1), live [agency list](https://www.federalregister.gov/api/v1/agencies.json), and the open-source [API core](https://github.com/usnationalarchives/federalregister-api-core). [1 CFR § 5.9](https://www.govinfo.gov/content/pkg/CFR-2025-title1-vol1/pdf/CFR-2025-title1-vol1-chapI.pdf) defines the publication categories.
- **Resource kind and scope:** source-native document categories (`The President`, `Rules and Regulations`, `Proposed Rules`, `Notices`), presidential subtypes, API topics, Table of Contents subjects, and agency identities.
- **Representation and access:** JSON API and GovInfo HTML/XML/PDF packages. The API core is available under AGPL-3.0; API output is public.
- **Maintenance evidence:** the live API and 2026 Federal Register data were current during the check. The API repository showed continuing public development, although code activity is not a guarantee that every list is curated on a fixed schedule.
- **Access and license constraints:** automated access is subject to service controls. Federal Register material is reproducible under 1 CFR § 2.6.
- **Source families:** `C04`, `T1-02`, `E02`; agency normalization for `C01-C06`, `T1-01`, `T2-03`, `G01-G03`, and `G05`.
- **Recommended role:** document categories and subtypes are **deterministic metadata**; API topics and agency-supplied Lists of Subjects are **source-assigned evidence**; agency records support **entity normalization**.
- **Use and risks:** store the raw API values and identifiers. Reconcile API `topics` with the editioned R01 vocabulary before treating them as canonical terms. A Notice `toc_subject` often describes an action such as a meeting, application, or investigation; keep it as genre/action metadata unless independent text supports a topical concept.

### R06 — Regulations.gov API code lists and agency-configured fields

- **Owner and authoritative URL:** General Services Administration and participating agencies; [Regulations.gov API documentation and OpenAPI link](https://open.gsa.gov/api/regulationsgov/).
- **Resource kind and scope:** source-native docket types (`Rulemaking`, `Nonrulemaking`), coarse document types, submitter types, comment fields, attachment metadata, and agency-specific category fields.
- **Representation and access:** REST/JSON API with OpenAPI description; API key through `api.data.gov`; documented rate limits.
- **Maintenance evidence:** the public API documentation and endpoints were live when checked. The documentation warns that agencies can change comment form fields.
- **Access and license constraints:** API key and rate limits apply. Public comments and attachments can contain personal information and third-party material; public availability does not remove privacy or copyright review.
- **Source families:** `C01-C03`, `E01`; joins into `C04-C05`.
- **Recommended role:** docket/document/comment types and attachment fields are **deterministic metadata**; source-supplied labels are **source-assigned evidence** only when the agency expressly assigns them.
- **Use and risks:** no maintained public cross-agency thesaurus for fine-grained Regulations.gov document, comment, or attachment types was found. `agency-categories` and configurable comment subtypes are not a universal subject taxonomy. Preserve raw values and create a versioned source-specific map only where multiple values have proven equivalent. Keep `C03` outside tagging version 1.

### R07 — Unified Agenda and Regulatory Information Number code lists

- **Owner and authoritative URLs:** Regulatory Information Service Center and Office of Information and Regulatory Affairs (OIRA); [Unified Agenda preamble and field definitions](https://www.reginfo.gov/public/jsp/eAgenda/StaticContent/202210/RiscPreamble.pdf), [Fall 2024 data-form instructions](https://www.reginfo.gov/public/jsp/regform/Regulatory_Information_Data_Form_Instructions_Fall_2024.pdf), and the live [Agenda rule view](https://www.reginfo.gov/public/do/eAgendaViewRule?RIN=0955-AA08&pubId=202510).
- **Resource kind and scope:** identifier authority for the Regulatory Information Number (RIN); five rulemaking stages; priority categories; legal authority, timetable, CFR citations, related-RIN relations, and other process fields. The Agenda subject index uses the Federal Register Thesaurus.
- **Representation and access:** public HTML and per-RIN XML download; editioned PDF instructions.
- **Maintenance evidence:** live Agenda records and XML were current in 2026. The clearest public definitions found are the 2022 preamble and 2024 instructions, so store the source edition with every normalized value.
- **Access and license constraints:** public web access; no separate bulk-data license or stable unauthenticated bulk API was identified in this check.
- **Source families:** `C05`; identifier and lifecycle joins for `C01-C04`, `T1-01`, `T2-03`, and `G05`.
- **Recommended role:** RIN, stage, priority, timetable, citations, and relationships are **deterministic metadata**; Agenda subject terms are **source-assigned evidence** backed by R01.
- **Use and risks:** agency sort codes were formerly called subject codes but now control local display order; do not treat them as subjects. Preserve historical priority labels and the Agenda edition because executive-order terminology changes over time.

### R08 — OIRA Executive Order review and meeting code lists

- **Owner and authoritative URLs:** OIRA; [Executive Order review search](https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD), [review-count search](https://www.reginfo.gov/public/do/eoCountsSearchInit?action=init), and [Executive Order 12866 meeting search](https://www.reginfo.gov/public/do/eom12866Search).
- **Resource kind and scope:** review status, rule stage, conclusion action, and meeting status codes. Live values include pending/concluded review states, six rule stages, conclusion actions such as `Consistent with Change`, `Withdrawn`, and `Returned for Reconsideration`, and meeting states such as scheduled, completed, and no-show.
- **Representation and access:** public HTML forms and result tables; no maintained subject vocabulary or documented public bulk API was found.
- **Maintenance evidence:** the forms returned current 2026 reviews and meetings during the check.
- **Access and license constraints:** public web access; form-driven retrieval and changing HTML create operational risk.
- **Source families:** `T1-01`; joins to `C04-C05`, `T2-03`, and `G05`.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** these values describe review and meeting process, not policy subjects. Use the linked RIN and Federal Register document for subjects. Preserve raw code, label, retrieval date, and source URL.

### R09 — Paperwork Reduction Act information-collection code lists

- **Owner and authoritative URLs:** OIRA; [Paperwork Reduction Act search](https://www.reginfo.gov/public/do/PRASearch) and a live [OMB control-number history](https://www.reginfo.gov/public/do/PRAOMBHistory?ombControlNumber=0607-1004).
- **Resource kind and scope:** OMB Control Number and Information Collection Request (ICR) Reference Number authorities; request type, ICR status, OIRA conclusion, review type, obligation to respond, burden source, and affected-public codes.
- **Representation and access:** public HTML forms and result pages. The live form exposes code/label pairs but no maintained public subject thesaurus or documented bulk API.
- **Maintenance evidence:** current 2026 control histories and active records were available during the check.
- **Access and license constraints:** public form access; preserve snapshots because HTML options and labels can change.
- **Source families:** `T2-03`; joins to `C04-C05`, `T1-01`, and `G05`.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** affected-public and burden codes describe the collection, not necessarily the subject of the notice. The proposed `dataset_status` value in the matrix is an implementation class, not an OIRA code. Version all code-list extracts.

### R10 — North American Industry Classification System

- **Owner and authoritative URL:** OMB Economic Classification Policy Committee with the United States Census Bureau; [NAICS site and reference files](https://www.census.gov/naics/).
- **Resource kind and scope:** hierarchical codes for business establishments and industries. The current production edition is 2022 NAICS.
- **Representation and access:** web search, PDF manual, XLSX structure, downloadable reference files, and concordances.
- **Maintenance evidence:** the site exposes the 2022 structure and a July 13, 2026 notice seeking comment on proposed 2027 updates.
- **Access and license constraints:** public federal reference files. Store the edition because codes and definitions change.
- **Source families:** `C05`; optional affected-industry support for `C04`, `T1-01`, `T2-03`, `G02`, and `G03`.
- **Recommended role:** **source-assigned evidence** for affected industry and **crosswalk/mapping only** for subjects.
- **Use and risks:** NAICS answers “which industry is affected,” not “what is this document about.” Do not make a NAICS code a topical gold label unless the tagging model explicitly defines an industry facet.

### R11 — eCFR and GovInfo structural and package metadata

- **Owner and authoritative URLs:** OFR/Government Publishing Office; [eCFR API documentation](https://www.ecfr.gov/developers/documentation/api/v1), live [eCFR agency list](https://www.ecfr.gov/api/admin/v1/agencies.json), and the [GovInfo Developer Hub](https://www.govinfo.gov/developers).
- **Resource kind and scope:** legal hierarchy and identifiers for title, subtitle, chapter, subchapter, part, subpart, section, and appendix; agency references; point-in-time versions; GovInfo package metadata and relationships.
- **Representation and access:** eCFR JSON/XML APIs; GovInfo REST API and bulk XML. GovInfo packages include MODS descriptive metadata, PREMIS preservation metadata, METS structure, and fixity information.
- **Maintenance evidence:** eCFR exposes current and historical versions; GovInfo listed current CFR, eCFR, Federal Register, Statutes at Large, and statute-compilation collections when checked.
- **Access and license constraints:** GovInfo API access uses an `api.data.gov` key; bulk data is public. The eCFR is authoritative but unofficial; annual printed CFR editions remain official.
- **Source families:** `C04-C06`, `E02-E03`, `G01`, `G05`; agency normalization across federal sources.
- **Recommended role:** hierarchy, citations, versions, package relationships, and fixity are **deterministic metadata**; agency lists support **entity normalization**.
- **Use and risks:** CFR title and chapter names are browse structure, not document subjects. Keep official-edition status and point-in-time date explicit. Do not collapse the eCFR's continuously updated text into an undated “current law” record.

### R12 — United States Legislative Markup

- **Owner and authoritative URLs:** Government Publishing Office and Office of the Law Revision Counsel; [USLM schema repository](https://github.com/usgpo/uslm) and [United States Code downloads](https://uscode.house.gov/download/download.shtml).
- **Resource kind and scope:** XML schema and naming conventions for United States legislative and statutory documents, including structural elements, identifiers, notes, and version metadata.
- **Representation and access:** XML Schema Definition files, examples, CSS, user guide, and United States Code XML/XHTML/PDF downloads.
- **Maintenance evidence:** the USLM repository listed approved versions through 2.1.0 and 2026 repository updates. The Office of the Law Revision Counsel site exposed a July 12, 2026 United States Code release.
- **Access and license constraints:** public federal schema and source files; preserve edition and release metadata.
- **Source families:** `G01`; structural mapping for `C06`, `E03`, `G05`, and state legislative references.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** USLM models source structure and legal identity. It is not a subject taxonomy and does not supply all amendment-effect semantics needed to reconstruct legal history.

### R13 — Supreme Court opinion categories and version ladder

- **Owner and authoritative URLs:** Supreme Court of the United States; [Opinions](https://www.supremecourt.gov/opinions/) and [Bound Volumes](https://www.supremecourt.gov/opinions/boundvolumes.aspx).
- **Resource kind and scope:** source-native opinion/package distinctions, including opinions of the Court, per curiam opinions, in-chambers opinions, opinions relating to orders, concurrences, and dissents; slip, preliminary-print, and bound-volume versions.
- **Representation and access:** official PDF packages and HTML indexes.
- **Maintenance evidence:** current-term opinions and bound-volume releases were present during the 2026 check.
- **Access and license constraints:** public access; Supreme Court opinions are federal works, but preserve the exact official package and version rather than relying on a republisher.
- **Source families:** `C13`, `E05`, `T2-02`, `G04`.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** the package can contain multiple judicial writings. Split only when the official package or reliable structure supports the boundary. Court posture and opinion type are not policy subjects.

### R14 — U.S. Courts Nature of Suit codes and PACER court/case metadata

- **Owner and authoritative URLs:** Administrative Office of the U.S. Courts; [Nature of Suit code descriptions](https://www.uscourts.gov/sites/default/files/js_044_code_descriptions.pdf), [2026 PACER User Manual](https://pacer.uscourts.gov/sites/default/files/files/PACER-User-Manual_2026.pdf), and [PACER Case Locator API documentation](https://pacer.uscourts.gov/sites/default/files/files/PCL-API-Document_0.pdf).
- **Resource kind and scope:** civil Nature of Suit codes, court identifiers, case types, case numbers, and selected party-role lists.
- **Representation and access:** PDF code lists/manuals and authenticated PACER interfaces/API.
- **Maintenance evidence:** the current manual is dated 2026. It links to the official Nature of Suit list and notes that some menu values vary by court.
- **Access and license constraints:** PACER account and fees can apply. Search results and filings have separate privacy and redistribution considerations.
- **Source families:** `C14`, `T2-02`, `G04`; join support for `C13`.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** map spelling variants such as the current code `899` label to the code, not to a guessed topic. Nature of Suit is a case-opening classification and can be broad or stale. No maintained national CM/ECF docket-entry or pleading-event taxonomy was found; local filing menus can differ by court.

### R15 — CourtListener court authority and opinion-type/status values

- **Owner and authoritative URLs:** Free Law Project; [jurisdiction/court data](https://www.courtlistener.com/help/api/jurisdictions/) and [advanced-search value definitions](https://wiki.free.law/c/courtlistener/help/search/advanced-search-and-query-techniques).
- **Resource kind and scope:** platform authority for courts and jurisdictions plus normalized opinion status/type values. Exposed types include combined, lead, plurality, concurrence, dissent, rehearing, and related values; statuses include published, unpublished, errata, in-chambers, and others.
- **Representation and access:** CourtListener API and bulk data; searchable web interface.
- **Maintenance evidence:** court records exposed modification dates into 2026. Free Law Project announced that API v4 access became a membership benefit in May 2026.
- **Access and license constraints:** current API access can require membership. Dataset-specific licenses apply; the platform combines public-domain opinions with Free Law Project metadata and contributed RECAP material.
- **Source families:** `C13-C14`, `E05`, `T2-02`, `G04`.
- **Recommended role:** CourtListener values are **deterministic metadata** for CourtListener records; court identifiers support **entity normalization**; mappings to official court packages are **crosswalk/mapping only**.
- **Use and risks:** these are maintained platform values, not court-issued national code lists. Do not treat CourtListener opinion types as authoritative package boundaries when the official source disagrees. RECAP's generic `PACER document`/`attachment` distinction does not solve pleading classification.

### R16 — FCC ECFS proceeding/filing values and 47 CFR procedural classes

- **Owner and authoritative URLs:** Federal Communications Commission; [ECFS search and retrieval API help](https://www.fcc.gov/ecfs/help/public_api), API base `https://publicapi.fcc.gov/ecfs`, and current [47 CFR part 1, subpart H](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-1/subpart-H).
- **Resource kind and scope:** ECFS proceeding flags, bureau codes/names, filing status, viewing status, and filing `submissiontype.description`; FCC rules define exempt, permit-but-disclose, and restricted proceedings and distinguish written/oral ex parte presentations.
- **Representation and access:** keyed REST/JSON API for `/proceedings` and `/filings`; eCFR HTML/XML/API for legal procedural terms.
- **Maintenance evidence:** a 2022 [FCC public notice](https://docs.fcc.gov/public/attachments/DA-22-348A1.pdf) states that the search-and-retrieval API remains available. The current matrix snapshot contains 2026 ECFS data, and 47 CFR title 47 was current through July 2026 during the check.
- **Access and license constraints:** API key through `api.data.gov`; ECFS can contain confidential/restricted and third-party submissions. Preserve viewing status and do not fetch or publish content that the source withholds.
- **Source families:** `C16-C17`, `E05`; FCC joins into `C04`, `G02-G04`.
- **Recommended role:** ECFS values and 47 CFR procedural classifications are **deterministic metadata**; bureau records support **entity normalization**.
- **Use and risks:** no FCC subject thesaurus or authoritative public crosswalk for the 54 observed filing descriptions was found. The matrix's public-participation, agency-issuance, procedural, and case-like groupings are proposed implementation classes, not FCC classes. Store the exact raw description and map only through a versioned, tested source-specific table.

### R17 — SEC rulemaking, order, guidance, and letter categories

- **Owner and authoritative URLs:** Securities and Exchange Commission; [Rules and Regulations](https://www.sec.gov/rules-regulations), [Rulemaking Activity](https://www.sec.gov/rules-regulations/rulemaking-activity), and [Commission Orders and Notices](https://www.sec.gov/rules-regulations/commission-orders-notices).
- **Resource kind and scope:** source navigation and series labels for proposed/final rules, concept releases, interpretive releases, self-regulatory-organization filings, regulatory orders/notices, policy statements, staff guidance, no-action letters, and petitions for rulemaking.
- **Representation and access:** HTML indexes, linked HTML/PDF releases, Federal Register/GovInfo records, and SEC data services where available.
- **Maintenance evidence:** current indexes and 2026 releases were available when checked; the Commission Orders and Notices page was last reviewed December 9, 2024.
- **Access and license constraints:** SEC automated-access policy and rate limits apply; clients must identify themselves. Comment files and exhibits can contain third-party content.
- **Source families:** `G02`, `G03`, `T1-04`; joins to `C04-C05`, `T1-01`, and `G04-G05`.
- **Recommended role:** source series and release/file numbers are **deterministic metadata**; issuer names support **entity normalization**.
- **Use and risks:** SEC site sections are useful source-native categories, not a published controlled vocabulary with stable identifiers and definitions. Do not infer equivalence between a staff bulletin, interpretive release, Commission order, and Federal Register rule from similar titles.

### R18 — FERC eLibrary document class/type and docket-prefix lists

- **Owner and authoritative URLs:** Federal Energy Regulatory Commission; [eLibrary FAQ](https://www.ferc.gov/elibrary-frequently-asked-questions-faqs), [Document Class/Type Information](https://www.ferc.gov/media/elibrary-classtype-information), and [Docket-Prefix Information](https://www.ferc.gov/media/elibrary-docket-prefix-information).
- **Resource kind and scope:** source-maintained document classes/types, docket prefixes, industry sector, category, security level, accession number, and FERC citation fields.
- **Representation and access:** public search interface plus PDF code lists. The FAQ states that eLibrary contains FERC-issued documents, regulated-entity submissions, and public comments from 1989 onward.
- **Maintenance evidence:** the class/type list is dated January 2025 and its page June 4, 2025; the docket-prefix list and page are dated June 9, 2025.
- **Access and license constraints:** some files are unavailable because of permissions, Freedom of Information Act restrictions, or Critical Energy Infrastructure Information controls. Microfilm and legacy image access remains incomplete.
- **Source families:** `G02`, `G03`, `E05`; joins to `C04`, `G04`, and `G05`.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** this is the strongest source-specific document-type authority found for a non-Regulations.gov docket. It is still FERC-specific. Preserve class and type separately and do not generalize its labels to SEC, FCC, or court filings without an evaluated mapping.

### R19 — NRC ADAMS source metadata

- **Owner and authoritative URL:** Nuclear Regulatory Commission; [ADAMS Public Documents](https://www.nrc.gov/reading-rm/adams) and [ADAMS Public Search](https://adams-search.nrc.gov/).
- **Resource kind and scope:** accession identifiers, document metadata, docket/license references, full-text public records, and source search filters.
- **Representation and access:** cloud search interface and PDF documents; legacy bibliographic and microfiche collections.
- **Maintenance evidence:** the NRC page was reviewed July 1, 2026, reports several hundred new public documents per day, and identifies ADAMS Public Search as the current interface.
- **Access and license constraints:** only publicly released records are available. Legacy records can lack full text; separate electronic hearing dockets and sensitive-information rules apply.
- **Source families:** source audit for `G02`; `G03`, `E05`, and `T1-04` if NRC is selected.
- **Recommended role:** accession, docket, and source filter values are **deterministic metadata**; **reject/defer** adoption of an NRC-wide document taxonomy until the source audit exports the current filter values and definitions.
- **Use and risks:** no maintained, downloadable ADAMS document-type vocabulary with stable definitions was found in the public documentation reviewed. Search-facet labels can still be preserved as raw source metadata, but they are insufficient to design the cross-agency normalization now.

### R20 — GAO Congressional Review Act database, report classes, and statutory events

- **Owner and authoritative URLs:** Government Accountability Office; [CRA database](https://www.gao.gov/legal/other-legal-work/congressional-review-act?priority=all&processed=1&type=all), [Reports on Major Rules](https://www.gao.gov/legal/congressional-review-act/reports-on-major-rules), [Legal Decisions](https://www.gao.gov/legal/congressional-review-act/legal-decisions), and [CRA FAQ](https://www.gao.gov/legal/congressional-review-act/faqs-on-the-congressional-review-act).
- **Resource kind and scope:** major/non-major rule classification, agency submission records, GAO major-rule reports, GAO legal decisions about CRA coverage, receipt/effective dates, and enacted joint resolutions of disapproval. The governing event definitions come from 5 U.S.C. chapter 8.
- **Representation and access:** searchable HTML result sets and linked report/decision pages and PDFs.
- **Maintenance evidence:** the legal-decision list and disapproval list contained 2026 records when checked.
- **Access and license constraints:** public federal records; the search UI is not a documented stable bulk API.
- **Source families:** `G05`; joins to `C04-C05`, `T1-01`, `T2-03`, and `G01`.
- **Recommended role:** **deterministic metadata**.
- **Use and risks:** GAO supplies authoritative source records for submitted rules, major-rule reports, and its legal decisions. It does not publish a complete machine-readable CRA lifecycle ontology. Review-window calculations and receipt reconciliation should remain project-owned, versioned rules with each input date and statutory basis retained.

### R21 — ACUS Recommendation 2017-1 adjudication material categories

- **Owner and authoritative URL:** Administrative Conference of the United States; [Recommendation 2017-1, Adjudication Materials on Agency Websites](https://www.acus.gov/sites/default/files/documents/Recommendation%202017-1%2C%20Adjudication%20Materials%20on%20Agency%20Websites_0.pdf).
- **Resource kind and scope:** government-wide best-practice recommendation describing adjudication decisions and supporting materials such as orders, opinions, pleadings, motions, briefs, and petitions.
- **Representation and access:** public PDF and Federal Register publication.
- **Maintenance evidence:** adopted June 16, 2017. It is a static recommendation, not a maintained code list. Its underlying research found no single comprehensive federal administrative-adjudication clearinghouse.
- **Access and license constraints:** public federal publication.
- **Source families:** `G03`; useful source-audit framing for `G02`, `G04`, and `T1-04`.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** use the categories to design agency audits, not as canonical labels. Agencies differ in proceeding types, naming, appellate layers, and publication practice. A project-owned genre model must distinguish allegations, party arguments, initial decisions, final agency action, and settlements.

### R22 — Census state and state-equivalent codes

- **Owner and authoritative URL:** United States Census Bureau; [ANSI, FIPS, and other geographic codes](https://www.census.gov/library/reference/code-lists/ansi.html).
- **Resource kind and scope:** state postal abbreviation, two-digit Federal Information Processing Standards code, National Standard code, and official state/state-equivalent name.
- **Representation and access:** downloadable text file and web table.
- **Maintenance evidence:** the page exposes 2020 Census state codes and was last revised May 1, 2023.
- **Access and license constraints:** public federal data.
- **Source families:** `T3-01`, `G09`; jurisdiction support for `T2-02` and `G04`.
- **Recommended role:** **entity normalization**.
- **Use and risks:** these codes normalize jurisdiction only. They say nothing about a state's agencies, administrative-register document types, executive-order series, or legal status. Preserve each state source's own identifiers alongside the state code.

### R23 — Akoma Ntoso Version 1.0

- **Owner and authoritative URL:** OASIS LegalDocumentML Technical Committee; [Part 1 XML Vocabulary](https://docs.oasis-open.org/legaldocml/akn-core/v1.0/akn-core-v1.0-part1-vocabulary.html).
- **Resource kind and scope:** legal-document XML vocabulary covering parliamentary, legislative, and judicial document structure, metadata, lifecycle, references, amendments, judgments, and generic document containers. The artifact includes XML schemas and examples and names concrete elements such as `section`, `paragraph`, `clause`, and legal-document types.
- **Representation and access:** normative XML schemas, HTML/PDF specification, and examples.
- **Maintenance evidence:** OASIS Standard approved August 29, 2018; the version URL remains the listed latest 1.0 location.
- **Access and license constraints:** OASIS copyright and RF-on-Limited-Terms intellectual-property mode apply; machine-readable normative files control if prose and schema differ.
- **Source families:** `G01`, `G03-G05`, `T2-02`, `T3-01`, and `G09`; structural mapping for `C13` and `E03`.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** use it to compare structural and lifecycle concepts across publishers. Do not replace USLM, eCFR, court, or agency-native identifiers and boundaries with jurisdiction-neutral Akoma Ntoso classes.

### R24 — European Legislation Identifier ontology

- **Owner and authoritative URL:** Publications Office of the European Union; [ELI ontology and tools](https://op.europa.eu/en/web/eu-vocabularies/eli).
- **Resource kind and scope:** legislation identifier and metadata model based on Functional Requirements for Bibliographic Records, including legal resources, expressions, formats, lifecycle relationships, amendments, and impacts.
- **Representation and access:** OWL reference ontology, metadata table, diagrams, release notes, version history, RDFa/JSON-LD publication, XML schema, and validator.
- **Maintenance evidence:** the site exposes a current ontology, release notes, version history, and later ELI-DL/ELI-Impact extensions.
- **Access and license constraints:** public EU specifications and tools; EU reuse and component-license terms apply.
- **Source families:** `G01`, `T3-01`, `G09`; mapping support for `C06`, `E03`, `G03-G05`, and `T2-02`.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** ELI is designed primarily for official European legal publishers. Its resource/expression/format and amendment concepts are useful comparison targets, but United States identifiers and source version rules remain authoritative.

### R25 — PROV-O

- **Owner and authoritative URL:** World Wide Web Consortium; [PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/).
- **Resource kind and scope:** provenance ontology with concrete classes `prov:Entity`, `prov:Activity`, and `prov:Agent`, and relations such as `prov:wasDerivedFrom`, `prov:wasRevisionOf`, generation, use, attribution, and time.
- **Representation and access:** normative OWL ontology and W3C Recommendation.
- **Maintenance evidence:** stable W3C Recommendation dated April 30, 2013, with an errata process and latest-version URL.
- **Access and license constraints:** W3C document-use and software-license terms apply.
- **Source families:** `T1-10`, `E02-E03`, `E05`; provenance support across all assigned source families.
- **Recommended role:** **deterministic metadata** for project provenance and **crosswalk/mapping only** for external exchange.
- **Use and risks:** specialize a small project-owned capture model rather than importing every PROV class. PROV records derivation; it does not classify a text change as substantive, formatting-only, withdrawal, or supersession.

### R26 — W3C Web Annotation Data Model

- **Owner and authoritative URL:** World Wide Web Consortium; [Web Annotation Data Model](https://www.w3.org/TR/annotation-model/).
- **Resource kind and scope:** interoperable annotation model with body, target, motivation, agent, time state, and selectors. `TextQuoteSelector` records exact text plus optional prefix/suffix; `TextPositionSelector` records character positions.
- **Representation and access:** W3C Recommendation with preferred JSON-LD serialization.
- **Maintenance evidence:** stable Recommendation published in 2017 with implementation report and latest-version URL.
- **Access and license constraints:** W3C document-use and software-license terms apply.
- **Source families:** `T1-10`, `E02-E03`, `E05`; evidence-span support for `C02`, `C04-C06`, `C13`, `C17`, `T1-04`, `T2-02`, and `G01-G04`, `G09`.
- **Recommended role:** **crosswalk/mapping only**.
- **Use and risks:** the selector model is useful for portable passage evidence. Store source digest and rendition/version because positions drift when text changes. Annotation motivations do not provide the needed regulatory subject or legal-genre taxonomy.

### R27 — RFC 7089 Memento

- **Owner and authoritative URL:** RFC Editor/IETF Trust; [RFC 7089, HTTP Framework for Time-Based Access to Resource States](https://www.rfc-editor.org/rfc/rfc7089.html).
- **Resource kind and scope:** time-based web-resource version model with Original Resource, Memento, TimeGate, TimeMap, `Memento-Datetime`, and link relations.
- **Representation and access:** informational RFC defining HTTP headers and link relations.
- **Maintenance evidence:** published December 2013; errata/current-status link maintained by the RFC Editor.
- **Access and license constraints:** IETF Trust Legal Provisions apply. It is informational, not an Internet Standards Track specification.
- **Source families:** `T1-10`; version-link support for `T1-04`, `E02-E03`, `G09`, and other web-published documents.
- **Recommended role:** **deterministic metadata** when a source or archive exposes Memento relations; otherwise **crosswalk/mapping only**.
- **Use and risks:** this model identifies prior representations. It does not prove that a captured page is legally effective, complete, or semantically changed. Capture digest, retrieval status, canonical URL, and source-specific version evidence separately.

### R28 — LegalRuleML Core Specification Version 1.0

- **Owner and authoritative URL:** OASIS LegalRuleML Technical Committee; [LegalRuleML Core Specification](https://docs.oasis-open.org/legalruleml/legalruleml-core-spec/v1.0/os/legalruleml-core-spec-v1.0-os.html).
- **Resource kind and scope:** formal representation of legal norms, rules, defeasibility, authority, jurisdiction, temporal characteristics, and rule relationships.
- **Representation and access:** OASIS Standard with XML schemas and normative specification.
- **Maintenance evidence:** OASIS Standard approved August 30, 2021.
- **Access and license constraints:** OASIS copyright and intellectual-property terms apply.
- **Source families:** superficially relevant to `C06`, `E03`, `G01`, `G03`, and `G05`.
- **Recommended role:** **reject/defer** for the concept-tagging catalog.
- **Use and risks:** LegalRuleML solves formal rule representation, not source-document subject or genre classification. Importing it here would duplicate formal rule work owned by Rulespec/Formspec and would not close any observed source-label gap.

## Source-native labels versus proposed normalized classes

The following boundary should become an acceptance rule for any catalog implementation.

| Source family | Source-native evidence to preserve | Proposed implementation normalization | Required safeguard |
| --- | --- | --- | --- |
| `C01-C03`, `E01` | Regulations.gov docket/document/comment types, agency categories, attachment metadata | optional project genre groups | never treat configurable agency fields as a global vocabulary; retain privacy boundary for comments |
| `C04`, `T1-02`, `E02` | Federal Register category, subtype, topics, Table of Contents subject, List of Subjects, agency ID | subject concepts from R01; narrow action/genre groups | store the raw term and vocabulary edition; keep Notice action labels outside topical gold |
| `C05` | RIN, stage, priority, timetable, legal authority, source subject index, NAICS | normalized lifecycle display labels | store Agenda edition; never convert agency sort codes or NAICS directly into general subjects |
| `T1-01` | OIRA status, stage, conclusion, meeting status | presentation-friendly status groups | keep raw code/label and linked RIN; no topic inference from review outcome |
| `T2-03` | OMB Control Number, ICR Reference Number, request/status/conclusion/burden codes | optional lifecycle groups; proposed `dataset_status` | mark every non-source class as project-owned and versioned |
| `C06`, `E03`, `G01` | CFR/USLM hierarchy, citation, edition, version, amendment references | shared citation and version relations | structure is not subject evidence; preserve official/unofficial status |
| `C13-C14`, `T2-02`, `G04` | official opinion/package type, PACER court/case/Nature of Suit values, CourtListener platform values | opinion-writing and filing-genre groups | do not claim a national pleading taxonomy; keep official and republisher values separate |
| `C16-C17` | ECFS proceeding flag, bureau, raw filing description, viewing/status values | participation, agency-issuance, procedural, and case-like groups | label the groups as implementation classes; map exact raw values with an editioned table |
| `G02` | SEC series, FERC class/type and docket prefix, NRC accession/facets | shared high-level filing roles only after source audits | never reuse one regulator's type list as another regulator's authority |
| `G03` | each agency's proceeding, pleading, decision, order, and settlement labels | allegation, argument, decision, settlement, and enforcement families | require legal/process review and retain procedural posture |
| `G05` | GAO database type, major/non-major flag, report/decision identity, source dates | calculated review events/windows | retain every input date, statutory rule version, and calculation receipt |
| `T3-01`, `G09` | each state's register/executive/agency labels and identifiers | state-aware shared genre groups | map one jurisdiction at a time; never assume federal labels have the same legal effect |
| `T1-04`, `T1-10` | agency page/file labels, URL, digest, retrieval time, source version clues | guidance genre and page-change classes | retain captures and evidence spans; project change classes are not source-assigned facts |

## Explicit negative findings

These are gaps, not invitations to adopt the nearest name-similar ontology.

| Finding | Affected IDs | Consequence |
| --- | --- | --- |
| No maintained public cross-agency Regulations.gov taxonomy covers fine-grained document, comment, and attachment types. | `C01-C03`, `E01` | preserve API values; create only tested source-specific mappings |
| No current government-wide controlled vocabulary covers guidance genres such as letters, bulletins, FAQs, manuals, waivers, and rescissions. | `T1-04`, `G09` | preserve each publisher's label and legal basis; use a small project genre list with explicit mappings |
| No FCC subject thesaurus or authoritative public mapping for ECFS filing descriptions was found. | `C16-C17` | keep filing descriptions as raw genre/process metadata; use R01 only when the associated Federal Register record supplies subjects |
| No government-wide taxonomy spans SEC, FERC, NRC, Federal Reserve, and CFTC docket filings. | `G02` | audit one source at a time; FERC's maintained class/type list cannot stand in for the others |
| No single federal administrative-adjudication clearinghouse or maintained cross-agency pleading/decision taxonomy exists. | `G03` | use ACUS to frame audits, not as a canonical vocabulary |
| No maintained national CM/ECF docket-entry or pleading-event taxonomy was found; filing menus can vary by court. | `C14`, `G04` | retain docket descriptions and court-specific codes; normalize only high-confidence genres |
| No maintained public federal legal-topic thesaurus is assigned across court opinions and dockets. | `C13-C14`, `T2-02`, `G04` | subjects must come from text evidence; FAST/LCSH remain mappings, not source truth |
| Westlaw Key Number System is proprietary and no authoritative open term artifact suitable for ingestion was found. | `C13-C14`, `T2-02`, `G04` | **reject/defer**; do not reconstruct proprietary classifications from secondary traces |
| GAO exposes authoritative CRA records but no complete machine-readable CRA lifecycle ontology. | `G05` | calculate events with versioned project logic and auditable inputs |
| No national controlled vocabulary standardizes state administrative-register, executive-order, emergency-action, and agency-guidance types. | `T3-01`, `G09` | normalize jurisdiction identity first; map document types per state |
| PROV-O, Web Annotation, and Memento model provenance, evidence spans, and prior representations, but none defines regulatory page-change meaning. | `T1-10` | maintain a project change list such as text-added, text-removed, metadata-only, moved, withdrawn, and unavailable, with evidence and abstention |
| The public OIRA/PRA surfaces expose process codes but not independent subject thesauri. | `T1-01`, `T2-03` | obtain subjects from linked RIN/Federal Register text; keep process fields separate |

## Proposed adoption order

1. Materialize R01 as an editioned, testable subject module. Record the authoritative PDF digest, extraction method, preferred terms, non-preferred terms, and source page.
2. Capture R05-R20 source-native lists and identifiers in source-specific tables. Every record should include owner, retrieval date, source URL, raw code, raw label, effective/edition date when known, and status.
3. Add explicit maps from raw values to the smallest useful project classes. Make unknown values fail open to `unknown`, never to the nearest familiar label.
4. Use R11-R15 and R22 for structure, versions, courts, agencies, and jurisdictions. Keep those fields outside the general subject score.
5. Add R25-R27 only at the provenance and evidence seams: capture lineage, source version, and exact passage targeting.
6. Add R02-R04 and R23-R24 only after evaluated crosswalks show a product need. A crosswalk must carry mapping relation, method, reviewer or test set, vocabulary edition, and confidence.
7. Defer R28 and proprietary court classifications. They do not solve the current catalog problem.

## Coverage ledger

Every assigned matrix ID has at least one supported candidate or an explicit no-vocabulary finding.

| ID | Finding(s) | Coverage result |
| --- | --- | --- |
| `C01` | R06; negative finding 1 | Regulations.gov docket type is deterministic metadata; no finer universal taxonomy found |
| `C02` | R01, R05, R06 | source document type stays genre; R01 supplies regulatory subjects when the source supports them |
| `C03` | R06; negative finding 1 | source comment fields preserved; participation remains outside version 1 |
| `C04` | R01, R05, R10 | official subject module plus native document/action metadata |
| `C05` | R01, R07, R10 | Agenda subjects, RIN/lifecycle, and affected-industry codes separated |
| `C06` | R01, R11 | legal hierarchy deterministic; List of Subjects ranks candidates only |
| `C13` | R03, R13, R15; negative findings 7-8 | official package/type metadata; no open court-assigned topic thesaurus |
| `C14` | R14, R15; negative findings 6-8 | Nature of Suit/court metadata; no national pleading-event or topic vocabulary |
| `C16` | R16; negative finding 3 | ECFS proceeding values are container/process metadata |
| `C17` | R16; negative finding 3 | raw filing descriptions retained; proposed groups remain project-owned |
| `T1-01` | R07, R08; negative finding 12 | OIRA review/meeting codes deterministic; subjects come from linked rule records |
| `T1-02` | R01, R05 | Federal Register native category and subject evidence; public-inspection state deterministic |
| `T1-04` | R01, R17; negative finding 2 | source labels and text evidence; no government-wide guidance-genre vocabulary |
| `T1-10` | R25-R27; negative finding 11 | standards cover provenance/version/evidence, not semantic change type |
| `T2-02` | R03, R13-R15, R23-R24; negative findings 7-8 | official/platform court metadata plus mappings; text-based subjects required |
| `T2-03` | R09; negative finding 12 | PRA identifiers and code lists deterministic; no subject vocabulary |
| `T3-01` | R22-R24; negative finding 10 | normalize jurisdiction and map each state source separately |
| `E01` | R06; negative finding 1 | attachment metadata preserved; no cross-agency attachment-type thesaurus |
| `E02` | R01, R05, R11, R25-R26 | source body/version/package metadata with passage provenance |
| `E03` | R01, R11-R12, R23-R27 | eCFR/USLM structure and version history; external models map only |
| `E05` | R13, R15-R16, R25-R26 | preserve source package/filing boundaries and extraction evidence |
| `G01` | R11-R12, R23-R24 | USLM/GovInfo structure authoritative; Akoma Ntoso/ELI map only |
| `G02` | R17-R19; negative finding 4 | source-specific SEC/FERC/NRC metadata; no shared docket taxonomy |
| `G03` | R17-R19, R21, R23; negative finding 5 | agency-native genres plus ACUS audit map; no canonical cross-agency list |
| `G04` | R13-R15, R23; negative findings 6-8 | court/case metadata and structural mapping; no national pleading taxonomy |
| `G05` | R07-R09, R20, R23-R24; negative finding 9 | GAO/statutory records authoritative; lifecycle calculation remains auditable project logic |
| `G09` | R22-R27; negative findings 2 and 10 | state identity, source-native types, and provenance; map one jurisdiction at a time |

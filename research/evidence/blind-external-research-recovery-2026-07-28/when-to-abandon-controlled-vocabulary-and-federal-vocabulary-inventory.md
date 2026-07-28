# When to abandon a controlled vocabulary, and what US federal policy vocabularies exist

> **Provenance**
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery status: **RECOVERED**
> - Recovery date: **2026-07-28**
> - Recovery note: The original investigation ended after source gathering. This reconstruction used its retained research artifacts, including the Federal Register thesaurus, GND task and system papers, EuroVoc paper, CRS/GPO guide, and NAICS workbooks. Important counts were then checked against primary sources or are marked as computed snapshots, paper-reported results, or unverified.

## Executive finding

Do not abandon controlled concepts as identifiers. Abandon the requirement that every document must match one concept in one flat, fixed vocabulary.

The strongest recent evidence supports a hybrid:

1. Generate concise, document-specific phrases without restricting generation to a registry.
2. Retrieve plausible concepts from the relevant subject vocabulary and any source-specific module.
3. Canonicalize only when the match is supported.
4. Abstain, retain a local open label, or submit a new-concept candidate when nothing fits.
5. Emit stable concept identifiers for accepted matches, with the source text and matching evidence retained for audit.

This pattern keeps the useful parts of controlled vocabularies—stable identifiers, browse facets, cross-corpus joins, aliases, and reviewable changes—without turning an ill-fitting registry into a forced-choice error generator.

For US federal regulatory material, a defensible general subject core is likely in the low thousands, not hundreds of thousands. The initial core should combine the Federal Register indexing vocabulary and Congressional Research Service (CRS) legislative subjects, with source provenance and mappings preserved. Code of Federal Regulations (CFR) structure, agency, document type, Regulatory Information Number (RIN), North American Industry Classification System (NAICS), legal authority, and named entities should remain separate facets. Specialist vocabularies such as the National Agricultural Library Thesaurus (NALT), Medical Subject Headings (MeSH), and Environmental Protection Agency (EPA) terminology should be activated only for relevant documents.

That size is a design hypothesis, not a measured optimum. A blind holdout must decide it.

## Evidence labels

- **Verified current**: checked against a primary source available on 2026-07-28.
- **Computed snapshot**: counted from a named primary data source and date range; the source can change.
- **Paper-reported**: copied from the primary research paper, not independently reproduced.
- **Interpretation**: a conclusion drawn from the evidence, not a fact claimed by a source.
- **Unverified**: the research found a lead but did not establish the claim from a current primary source.

## Part A — When is a controlled vocabulary the wrong tool?

### 1. The best measured comparison favors a hybrid, not a categorical replacement

The 2025 LLMs4Subjects shared task is the closest measured comparison found. It used German National Library (GND) subjects for multilingual library records:

- The broad `all-subjects` label space contained **204,739 subjects**. The task provided **81,937 training** and **13,666 development** records.
- The narrower `tib-core` label space contained **79,427 subjects**.
- Fourteen teams submitted results.
- On the automatic `all-subjects` evaluation, the Annif ensemble, which used established extreme multilabel classification methods augmented with language models, led with **precision@5 0.26, recall@5 0.49, precision@10 0.16, and recall@10 0.57**.
- Human subject specialists separately reviewed **122 records**. Under the strict judgment that counted only relevant labels, the German National Library’s open-keyword-then-map system ranked first with **precision@5 0.53 and recall@5 0.34**. Annif scored **0.46 and 0.30**, respectively.

These are **paper-reported** results from the task overview. They do not prove that free tagging always beats direct controlled classification. They show a more useful distinction:

- Direct classification performed better against existing catalog labels at scale.
- Open phrase generation followed by mapping performed better in the small, strict human assessment.
- The task’s gold labels reflected cataloging practice. A useful but differently phrased label could be penalized by the automatic evaluation.

The German National Library system generated free keywords using several language models, then mapped them to GND concepts with multilingual embeddings. It expanded the **mapping search space** from **200,035 subject concepts** with **109,382 named entities**, for **309,417 candidates**, while keeping subject prediction separate from named-entity lookup. The paper reports that missing named entities could cause a semantically nearby but wrong subject match and that a simple similarity threshold did not eliminate all false mappings.

That failure mode matters directly for regulatory data. A registry can be large and still lack the particular organization, chemical, place, program, technology, or emerging policy phrase present in the document. Forced nearest-neighbor selection converts “not represented” into a confident-looking error.

**Interpretation:** use a wider mapping space than the final output space, keep subjects and entities typed separately, and support abstention. Do not treat the nearest concept as correct merely because it is nearest.

Primary papers:

- LLMs4Subjects task overview: <https://aclanthology.org/2025.semeval-1.328/>
- German National Library system: <https://aclanthology.org/2025.semeval-1.148/>
- Annif system: <https://aclanthology.org/2025.semeval-1.316/>

### 2. Recent LCSH work also uses generation followed by canonicalization

A 2025 study of Library of Congress Subject Headings (LCSH) generates subject phrases and then resolves them to LCSH rather than asking a model to choose directly from the entire vocabulary. The paper reports that limiting and post-processing generated output improves the precision-recall balance. This is a **paper-reported direction**, not a result independently reproduced here.

A separate 2026 skill-based LCSH agent study reports that, for **10 books**, model-assigned concepts had conceptual overlap in more than half of cases and were comparable or more specific in **7 of 10**. Ten items are too few to support a production conclusion.

These papers support trying the hybrid architecture. They do not establish that an organization can discontinue human vocabulary governance.

- Hybrid LCSH assignment: <https://arxiv.org/abs/2507.22913>
- Skill-based cataloging agent: <https://arxiv.org/abs/2605.03537>

### 3. Full-text retrieval and embeddings reduce one benefit of headings, but do not replace identifiers

Full text and embeddings can retrieve language that an indexer did not anticipate. They are therefore strong tools for candidate generation, semantic search, and recall. They do not by themselves provide:

- a stable identifier that survives a label change;
- a known equivalence between abbreviations, synonyms, and translations;
- a controlled broader/narrower relationship for faceted navigation;
- a durable crosswalk between corpora;
- a reviewable history of concept additions, mergers, and deprecations; or
- a bounded output that a program manager can interpret consistently.

FAST—Faceted Application of Subject Terminology—illustrates the distinction. OCLC designed FAST as a simpler, faceted application of LCSH for lower-cost description and navigation. OCLC currently describes approximately **1.7 million headings across all facets**, distributed under the Open Data Commons Attribution License. Its last bulk-data update shown by OCLC was **2024-10-10**. The research did not verify a current count for FAST’s topical facet alone or a measured study showing that FAST performs well on Federal Register-style, non-bibliographic documents.

The fact that FAST is large does not make it a regulatory vocabulary. Its value depends on whether the active concepts express what users need to retrieve and compare.

- FAST overview: <https://www.oclc.org/en/fast.html>
- FAST bulk data and license: <https://www.oclc.org/research/areas/data-science/fast/download.html>
- FAST change history: <https://fast.oclc.org/fastChanges/>

### 4. No verified production replacement case was found

This research did **not** verify a documented 2023–2026 case in which an organization replaced a governed controlled vocabulary with LLM-generated tags, measured the production outcome, and published the result. Papers describe experiments and assisted cataloging. They do not establish a production migration with before-and-after quality, operating cost, and governance evidence.

This is an evidence gap, not evidence that no such case exists.

### 5. Defensible reasons to keep controlled concepts

The case for keeping a controlled layer is strongest when it serves a downstream decision:

| Need | What a controlled concept adds | What it does not guarantee |
|---|---|---|
| Cross-corpus joins | A stable identifier can connect a bill, proposed rule, final rule, docket, comment, and program even when their wording differs. | That the concept was assigned correctly. |
| Faceted browse | Known broader/narrower groupings make counts and drill-downs understandable. | That the hierarchy matches every user task. |
| Multilingual and synonym retrieval | One identifier can carry preferred and alternative labels. EuroVoc demonstrates this at EU scale. | Complete coverage of emerging language. |
| Audit and correction | A saved identifier, vocabulary version, source excerpt, model version, and score can be reviewed and corrected. | Legal defensibility from the identifier alone. |
| Stable analytics | Reports can aggregate by an identifier even when display labels change. | Stability if concepts are silently repurposed. |
| Human-machine coordination | Reviewers can approve a finite output and vocabulary editors can manage additions. | Low review cost when the candidate space is irrelevant. |

“Legal defensibility” should not be treated as an automatic property of a thesaurus. It comes from reproducible evidence: the source passage, assignment method, vocabulary snapshot, confidence, reviewer action, and correction history.

### 6. Practical stop rules

A controlled vocabulary is the wrong **primary assignment mechanism** when several of these conditions hold:

1. **Coverage failure:** relevant source concepts are absent, so the system repeatedly returns semantically adjacent substitutes.
2. **Domain mismatch:** most candidates come from vocabularies built for different material or tasks.
3. **Forced-choice behavior:** the system cannot say “no supported match.”
4. **Poor candidate recall:** the correct label seldom appears in the reranker’s candidate set.
5. **Low user value:** headings do not improve the retrieval, browse, joining, or reporting decisions users actually make.
6. **Governance lag:** new policy language appears faster than the vocabulary can add or map it.
7. **Maintenance cost:** adjudication and mapping effort exceed the demonstrated benefit.

The corresponding reasons to keep a controlled layer are verified cross-corpus joining, useful facets, stable reporting, and a manageable review process. The answer can differ by facet: CFR part and agency are excellent controlled fields; an emerging technology topic may need an open label until governance catches up.

## Part B — US federal regulatory and policy vocabulary inventory

### General and legislative sources

| Source | Verified size or scope | Machine-readable form | Rights / reuse finding | Fit for Federal Register-style content |
|---|---:|---|---|---|
| **Federal Register Thesaurus of Indexing Terms** | The current Topics API returned **1,044 `thesaurus` topics** and **6,723 `ad_hoc` topics**, **7,767 total**, on 2026-07-28. The public PDF yielded **702 preferred terms** after removing one heading parsed as a term, plus about **504 variants**. The API/PDF difference is unresolved. | Topics endpoint and document `topics` field in JSON; PDF and older text publication. | Public federal data; no dataset-specific license was located. | **Best general regulatory seed.** Under 1 CFR 18.20, agencies list subjects for each affected CFR part in rules and proposed rules and must use an official term, while more specific terms may be added. Do not silently equate the PDF list with the live API list. |
| **Federal Register document topics, measured use** | **Computed snapshot:** 14,076 Rules and Proposed Rules published 2023-01-01 through 2025-12-31; 10,246 had at least one topic, with 56,021 assignments and 734 distinct topics. Top 10 topics accounted for 40.4% of assignments; top 100, 78.8%; 213 topics occurred five times or fewer. | FederalRegister.gov document API. | Same as above. | Strong weak-label source for rules and proposed rules, not a complete gold standard. A complete January 2025 check found topics on 222/277 Rules and 101/150 Proposed Rules, but **0/1,835 Notices** and **0/91 Presidential Documents**. `toc_subject` is separate table-of-contents metadata and should not be treated as a topic label. |
| **CFR List of Subjects / Index and Finding Aids** | Official subject assignments are arranged by CFR title and part. A current unique-term count was not verified independently of the Federal Register Topics API. | HTML by title/part; annual GovInfo CFR Index publications. | Public federal publication; no separate vocabulary license located. | High-value evidence linking subjects to regulated CFR parts. Use the assignments and citations, not a second unlabeled copy of the subject strings. |
| **CRS Legislative Subject Terms** | **Verified current:** **1,004 terms** listed by Congress.gov. CRS replaced the older Legislative Indexing Vocabulary, which had about 5,500 terms. | Congress.gov pages, API/bulk BILLSTATUS XML fields. | No separate vocabulary license located; public legislative data terms apply. | Strong policy-language complement to Federal Register subjects. Bills and regulations are different genres, so preserve source provenance and validate crosswalks. |
| **CRS Policy Areas** | **32 current broad policy areas**. CRS assigns one primary area to each public bill or resolution and may assign multiple legislative subjects. Historical GPO material can show 33 because a historical `Commemorations` area appears in the longer corpus. | Congress.gov value list and BILLSTATUS XML. | Same as above. | Useful top-level navigation and evaluation strata; too broad as the only topic output. |
| **Regulations.gov** | No general subject vocabulary was verified. The API exposes documents, comments, and dockets. Agency-defined category fields describe comment/submission categories, not a national document-topic taxonomy. Docket data can include RIN. | Official REST API, JSON. | GSA API and site terms apply; no separate topic-data license found. | Essential source and linkage metadata, but not a replacement topic vocabulary. |
| **Unified Agenda / Reginfo.gov** | No independent topic vocabulary was found. The 2025 preamble says the online subject index uses Federal Register Thesaurus terms. Records include RIN, agency, rule stage, priority, CFR citation, legal authority, timetable, and other structured fields. | Individual and bulk XML reports; web search. | Public federal data; no separate dataset license located. | Excellent structured regulatory facets. Treat stage, priority, RIN, CFR, and legal authority as separate fields, not topics. |
| **NAICS 2022** | **Verified from Census workbooks:** 20 sectors, 96 subsectors, 308 industry groups, 689 five-digit industries, and 1,012 US six-digit industries—2,125 hierarchy rows across those levels. | Excel, CSV and manuals from Census. | No standalone license statement was verified; US definitions are federal data, while tri-national content may carry additional notices. | Useful economic-activity facet where a rule affects an industry. It is not a policy-topic vocabulary, and assignment may require evidence beyond document text. |
| **CFR structure** | **Computed snapshot for 2025-01-01:** 49 populated title structures among 50 numbered titles, 476 chapters, and 9,746 parts. Title 35 was reserved/empty in the API response. | eCFR API JSON/XML. | Public federal data; eCFR terms apply. | Excellent legal-location taxonomy and retrieval filter. It describes where law is codified, not every subject discussed. |
| **OMB budget functions** | **20 major functions**: 17 substantive national-need functions plus Net Interest, Allowances, and Undistributed Offsetting Receipts. | Budget tables in spreadsheet/CSV form; function and subfunction fields. | Public federal budget data; no vocabulary-specific license located. | Useful for fiscal-policy grouping. Too coarse and budget-specific for general regulatory tagging. |
| **Assistance Listings, formerly CFDA** | Current listing count was not verified. The authoritative listing system includes categories, subcategories, functions, and subfunctions; the new Federal Assistance Listings API was announced on 2026-02-02. | SAM.gov API and public data extracts. | SAM.gov terms apply; some SAM datasets include third-party restrictions. No simple vocabulary-specific license was verified. | Useful for joining rules to federal assistance programs. Category assignment is optional in some records and is not a general policy subject scheme. |
| **GovInfo / GPO / USA.gov** | No current, versioned national policy-topic vocabulary with a verifiable size was found. GovInfo provides collection/package metadata and publication-specific indexes. USA.gov exposes website navigation topics. | GovInfo API and bulk packages; USA.gov web navigation. | Site/API terms apply. | Useful source and navigation metadata, but no evidence supports treating these as a governed regulatory label space. |

Federal Register primary sources:

- Thesaurus landing page and PDF: <https://www.archives.gov/federal-register/cfr/thesaurus.html>, <https://www.archives.gov/files/federal-register/cfr/thesaurus.pdf>
- Live topics data: <https://www.federalregister.gov/api/v1/topics.json>
- API documentation: <https://www.federalregister.gov/developers/documentation/api/v1>
- Assignment rule, 1 CFR 18.20: <https://www.ecfr.gov/current/title-1/chapter-I/subchapter-E/part-18/section-18.20>
- CFR subjects by title and part: <https://www.archives.gov/federal-register/cfr/subjects.html>

Congressional and regulatory-system primary sources:

- CRS assignment explanation: <https://www.congress.gov/help/find-bills-by-subject>
- CRS subject values: <https://www.congress.gov/help/field-values/legislative-subject-terms>
- CRS policy-area values: <https://www.congress.gov/help/field-values/policy-area>
- GPO BILLSTATUS guide: <https://github.com/usgpo/bill-status/blob/main/BILLSTATUS-XML_User_User-Guide.md>
- Regulations.gov API: <https://open.gsa.gov/api/regulationsgov/>
- Unified Agenda XML reports: <https://www.reginfo.gov/public/do/eAgendaXmlReport>
- Unified Agenda 2025 preamble: <https://www.reginfo.gov/public/jsp/eAgenda/StaticContent/202504/RiscPreamble.pdf>
- Unified Agenda field instructions: <https://www.reginfo.gov/public/jsp/regform/Regulatory_Information_Data_Form_Instructions_Fall_2024.pdf>

Classification and program-data primary sources:

- NAICS: <https://www.census.gov/naics/>
- 2022 NAICS manual: <https://www.census.gov/naics/reference_files_tools/2022_NAICS_Manual.pdf>
- eCFR API: <https://www.ecfr.gov/developers/documentation/api/v1>
- Federal budget data: <https://www.govinfo.gov/help/budget>
- Federal Program Inventory data: <https://fpi.omb.gov/about/about-the-data>
- Assistance Listings: <https://sam.gov/assistance-listings>
- Assistance Listings API announcement: <https://sam.gov/announcements/gsa-releases-new-federal-assistance-listings-api>
- Assistance Listings extracts: <https://sam.gov/data-services/Assistance%20Listings/datagov?privacy=Public>
- SAM.gov terms: <https://sam.gov/about/terms-of-use>

### Library and international comparison sources

| Source | Verified size or scope | Machine-readable form | Rights / reuse finding | Fit |
|---|---:|---|---|---|
| **Library of Congress Subject Headings (LCSH)** | A current primary-source record count was not verified. A 2025 research paper reports about **318,500 headings**, which should not be used as a live operational count without counting a pinned bulk release. | LC Linked Data Service and bulk RDF/JSON data. | A clear vocabulary-specific license was not verified in this recovery. | Broad mapping/reference source. It was designed for bibliographic subject access, not federal regulatory classification. Use policy-relevant mappings only after measured benefit. |
| **FAST** | OCLC says approximately **1.7 million headings across all facets**. Current topical-facet count was not verified. | Bulk RDF/XML, MARC, and linked data. | Open Data Commons Attribution License 1.0. | Simpler faceted library vocabulary. Useful as a mapping source; no verified regulatory-content performance evidence. |
| **EuroVoc** | **7,000+ preferred concepts**, 21 domains, 127 microthesauri, 24 official EU languages, up to eight hierarchy levels, about 678,000 multilingual terms and more than 800,000 RDF triples. Updated three to four times per year. | SKOS/RDF, XML, TBX, MARC-XML, Excel, SPARQL/API. | Reuse is governed by the EU Publications Office legal notice; a dataset-specific license label was not independently verified. | Best comparison for governed, multilingual legal-policy classification. EU institutions assign descriptors to EUR-Lex material, with human cataloging and automated-classification research. It is EU-centered and should not be imported wholesale for US regulation. |

EuroVoc’s research record is substantial. The 2025 management paper reports that the JRC-Acquis corpus contains about **23,000 documents averaging six EuroVoc descriptors**, and describes EUR-Lex/EuroVoc multilabel classification tools including JEX, PyEuroVoc, and KEVLAR. The commonly used EURLEX57K benchmark contains about **57,000 documents and 4,271 labels**. Exact recent model performance figures found in secondary search results were not retained as verified findings.

- LCSH Linked Data Service: <https://id.loc.gov/authorities/subjects.html>
- FAST sources: <https://www.oclc.org/en/fast.html>, <https://www.oclc.org/research/areas/data-science/fast/download.html>
- EuroVoc management paper: <https://aclanthology.org/2025.ldk-1.34/>
- EU Vocabularies EuroVoc entry: <https://op.europa.eu/en/web/eu-vocabularies/concept-scheme/-/resource?uri=http://eurovoc.europa.eu/100141>
- EURLEX57K dataset paper: <https://aclanthology.org/D19-1049/>
- KEVLAR: <https://aclanthology.org/2024.clicit-1.9/>

### Agency and specialist vocabularies

| Source | Verified size or scope | Machine-readable form | Rights / reuse finding | Fit |
|---|---:|---|---|---|
| **GAO Thesaurus** | The 1998 fourth edition reports **more than 2,500 terms**. No current maintained edition was verified. | PDF. | Public GAO publication; no separate vocabulary license located. | Historically relevant to oversight and program evaluation, but too old and not operationally machine-ready without substantial work. |
| **CBO topics** | No governed vocabulary or stable count was verified; the website has topical navigation categories. | Web pages. | Not separately stated. | Navigation aid, not a candidate production vocabulary. |
| **NASA Thesaurus** | NASA’s current page reports **more than 18,400 subject terms**, **4,300 definitions**, and **more than 4,500 USE cross-references**. | SKOS, OWL, ZThes, CSV, and PDF. | NASA requests attribution; no vocabulary-specific open-data license was verified. | Strong aerospace/science module. The downloadable content’s substantive date appears older than the page update, so freshness needs checking before use. |
| **DOE OSTI Semantic Thesaurus** | Exact current concept count and maintenance cadence were not verified. A 2020 release exposes broader, narrower, related, and synonym relationships. | RDF/SKOS download. | Public OSTI record; no explicit vocabulary license verified. | Potential energy/science module. Pin and inspect the data before adoption. |
| **EPA Enterprise Vocabulary** | EPA reports **more than 100 topic tiers**; exact concept count was not stated. | Excel, XML, PDF, and RTF exports. | No dataset-specific license found. | Strong environmental and regulatory module, with uncertain current size and maintenance details. |
| **EPA Web Taxonomy** | A 2014 SKOS dataset exists; current size and maintenance were not verified. | SKOS/RDF through Data.gov/EPA resources. | The catalog record supplies a license URL; exact applicable terms require review. | Website taxonomy and apparently stale. Do not treat it as the current EPA subject authority. |
| **EPA Substance Registry Services (SRS)** | Exact current entity count was not verified. It covers chemicals, organisms, and other substances rather than general topics. | REST/JSON services. | EPA service terms; no separate vocabulary license verified. | Valuable typed entity registry. Keep it out of the subject-label facet. |
| **NALT Full** | The current page reports **76,691 concepts**: 14,521 Topic, 6,422 Chemical, 53,199 Organism, 1,684 Product, and 771 Geographic concepts. Those displayed facet counts sum to 76,597, a 94-concept discrepancy that remains unresolved. Page update: 2024-07-16. | SKOS RDF/XML and Turtle linked data. | Dataset page says **CC BY 4.0**. A broader National Agricultural Library policy mentions public domain/CC0, so the dataset-specific CC BY 4.0 notice is the safer operational rule. | Strong agriculture, food, environment, and organism module. Too specialized as the general policy core. |
| **MeSH 2026** | **Computed from official 2026 XML:** 31,110 Descriptor records, 324,049 Supplemental Concept Records, and 76 Qualifier records. | Annual XML descriptors/qualifiers, daily supplemental concepts and RDF; MARC annual. ASCII ended in January 2026. | NLM requires attribution; no fees or royalties. | Strong health/biomedical module. Supplemental concepts are mainly entities, not general regulatory topics. |

Agency primary sources:

- GAO thesaurus: <https://www.gao.gov/products/oimc-99-1>
- NASA thesaurus: <https://sti.nasa.gov/nasa-thesaurus/>
- DOE OSTI record: <https://www.osti.gov/dataexplorer/biblio/1668761>
- EPA Enterprise Vocabulary: <https://www.epa.gov/research/epa-enterprise-vocabulary>
- EPA terminology services: <https://sor.epa.gov/sor_internet/registry/termreg/searchandretrieve/home.do>
- EPA SRS: <https://cdxapps.epa.gov/oms-substance-registry-services/about-srs>
- EPA registry services: <https://sor.epa.gov/sor_internet/registry/sysofreg/sorservices/sorServices.html>
- NALT Full: <https://lod.nal.usda.gov/nalt/en/>
- NAL rights policy: <https://www.nal.usda.gov/web-policies-and-important-links>
- MeSH downloads: <https://www.nlm.nih.gov/databases/download/mesh.html>
- MeSH 2026 XML directory: <https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/>
- NLM data terms: <https://www.nlm.nih.gov/databases/download/terms_and_conditions.html>

### 2023–2026 US regulatory topic benchmarks

No purpose-built, labeled 2023–2026 benchmark for topic classification across Federal Register rules, notices, Regulations.gov dockets and comments, and Unified Agenda items was verified.

The Federal Register API supplies useful **silver labels** for Rules and Proposed Rules. It does not solve the benchmark problem:

- Notices and Presidential Documents in the January 2025 check had no `topics`.
- Official agency indexing is valuable but may be incomplete or optimized for the CFR index rather than a user retrieval task.
- Dockets, comments, and agenda records require cross-source linkage and separate annotation.
- Frequently used labels dominate the observed assignments, while the long tail remains hard to evaluate.

The German-language GND task and EuroVoc datasets are useful method comparisons, not substitutes for a US regulatory holdout.

## Opinionated label-space design

### Decision

Replace the single 513,236-concept output with a typed, source-aware system. Keep the large registries available for retrieval and mapping, but do not let their combined size define the product’s subject facet.

### Recommended layers

| Layer | What goes in | What comes out | Initial scope |
|---|---|---|---:|
| **General policy subjects** | Federal Register thesaurus/API concepts, CRS subjects, carefully reviewed mappings | Stable subject IDs with preferred labels and source provenance | Start around **1,000–3,000** distinct concepts; permit growth toward **2,000–8,000** only when evaluation and user need justify it |
| **Broad policy area** | CRS policy areas plus a small reviewed regulatory crosswalk | One or a few broad navigation categories | About **32**, possibly with a small regulatory extension |
| **Legal location** | CFR title/chapter/part citations and affected parts | CFR identifiers | Current CFR structure; do not flatten its roughly 9,746 parts into topics |
| **Regulatory process** | Document type, stage, RIN, priority, legal authority, dates | Typed structured values | Source-defined enumerations |
| **Organization and jurisdiction** | Agencies, subagencies, governments, places | Stable organization/geographic IDs | Separate entity registries |
| **Economic activity** | NAICS codes supported by document evidence | NAICS IDs | Activate only when applicable |
| **Specialist modules** | EPA, NALT, NASA, DOE, MeSH and similar concepts | Source-qualified domain concept IDs | Activate by agency, CFR citation, or document evidence |
| **Open candidates** | Source-grounded phrases that do not map safely | Local proposed concept with evidence, or abstention | Unbounded intake; governed promotion |

The **1,000–3,000 starting range is an interpretation**, not a count of a deduplicated vocabulary. It follows from three observations: the Federal Register API currently exposes 1,044 thesaurus topics; only 734 appeared in the three-year Rules/Proposed Rules snapshot; and CRS exposes 1,004 legislative subjects. Their union has overlaps and different meanings, so it must be mapped and reviewed rather than concatenated. The broader **2,000–8,000** range is a ceiling for a governed general subject layer, not a target to fill.

### Assignment flow

1. Extract grounded subject phrases and typed entities from the title, abstract, regulatory text, and source metadata.
2. Select relevant vocabulary modules from agency, CFR, document type, and detected domain.
3. Retrieve candidates separately for subjects, organizations, places, chemicals, programs, industries, and legal citations.
4. Rerank with source text and definitions. Preserve exact evidence spans.
5. Accept a canonical identifier only above a calibrated decision rule. A nearest neighbor is not enough.
6. Otherwise abstain or retain an open candidate. Repeated, useful open candidates enter a human promotion queue.
7. Store the vocabulary source, version/date, concept ID, label, method, confidence, evidence, and review status.

### Evaluation gate

Before adoption, compare at least these three methods on the same untouched holdout:

1. direct closed-vocabulary assignment;
2. open phrase generation followed by canonicalization and abstention; and
3. the proposed typed hybrid.

Build the holdout across Rules, Proposed Rules, Notices, dockets, comments, and Unified Agenda items, stratified by agency and policy area. Official Federal Register topics may seed labels, but blind reviewers must judge retrieval usefulness and factual support.

Measure:

- candidate recall before reranking;
- precision and recall at 5 and 10;
- unsupported-label rate;
- correct abstention rate when no vocabulary concept fits;
- entity/subject type-confusion rate;
- performance on rare and new topics;
- cross-source join success;
- reviewer time and disagreement;
- concept stability after a vocabulary update; and
- user task outcomes for search, facets, alerts, and corpus comparison.

No architecture should be declared better from development-set tuning alone. Freeze the vocabulary snapshots, prompts/models, mappings, and holdout before the final blind comparison.

## What could not be verified

1. A documented production organization that fully replaced a controlled vocabulary with LLM-generated tags and published before/after quality, cost, and governance results.
2. A current primary-source total record count for LCSH, and a current count for its policy-relevant subset.
3. A current FAST topical-facet count or a measured FAST evaluation on Federal Register-style non-bibliographic content.
4. A reconciliation between the **702 preferred terms parsed from the public Federal Register PDF** and the **1,044 `thesaurus` entries in the live Topics API**. They must be versioned as separate published objects until reconciled.
5. A unique current count for CFR List-of-Subjects terms independent of the Federal Register Topics API.
6. Exact current counts for Assistance Listings categories/subcategories and active assistance listings.
7. A governed, machine-readable, versioned policy taxonomy from USA.gov, GovInfo, GPO, or CBO suitable as a national regulatory subject vocabulary.
8. Exact current concept counts and maintenance cadence for the DOE OSTI Semantic Thesaurus, EPA Enterprise Vocabulary, EPA SRS, and EPA Web Taxonomy.
9. Whether the current NASA downloadable vocabulary content has been substantively refreshed to match the 2026 page update.
10. The cause of the 94-concept difference between NALT Full’s displayed total and its displayed facet counts.
11. A dataset-specific license for several public federal vocabularies. “Published by a federal agency” was not treated as a substitute for an explicit data license.
12. Exact recent EuroVoc model performance numbers from a current primary benchmark comparison. Corpus and vocabulary sizes were retained; secondary-result performance claims were not.
13. A purpose-built 2023–2026 gold benchmark covering US federal rules, notices, dockets, public comments, and Unified Agenda topic assignment.
14. The optimal regulatory subject-vocabulary size. The proposed ranges are testable design hypotheses.

## Recovered-source corrections

The early Federal Register sample was incomplete: its pagination stopped after three pages per document type and produced 13,810 documents. The recovery reran the full 2023–2025 Rules/Proposed Rules range and obtained the **14,076-document computed snapshot** reported above. The report therefore does not preserve the incomplete count.

The recovery also separates three values that the interrupted work risked conflating:

- **702** preferred terms parsed from the public PDF;
- **1,044** live API entries whose type is `thesaurus`; and
- **7,767** total live API topics, including 6,723 `ad_hoc` entries.

None should be called “the one canonical current size” without first resolving the publishing and version differences.

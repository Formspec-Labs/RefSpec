<!-- markdownlint-disable MD013 -->

# Active Spicy Regs controlled-resource import plan

> **Status:** Active child plan of the [managed vocabulary experiment roadmap](managed-vocabulary-experiment-roadmap.md)
>
> **Date:** 2026-07-30
>
> **Research inputs:** [source and document-type matrix](../research/source-document-type-matrix-2026-07-28.md), [vocabulary and ontology catalog](../research/source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md), and [concept-tagging architecture proposal](../research/concept-tagging-architecture-proposal-2026-07-28.md)
>
> **Deferred standards work:** [standards composition and graph extensibility plan](standards-composition-and-graph-extensibility-plan.md)

## Decision

Build a RefSpec-managed portfolio for every source profile in the current Spicy
Regs experiment before expanding the Spicy Regs lookup implementation.

The portfolio will include the controlled resource appropriate to each profile:

- subject thesauruses and taxonomies for topical document lookup;
- source-assigned topics as evidence, without silently promoting them into a
  shared subject scheme;
- code lists and classifications for document type, process, industry, and
  program values;
- identifier authorities for organizations, courts, committees, recipients,
  and filings; and
- structural schemas for parsing and stable joins.

RefSpec will import and describe these resources as distinct releases, then
produce a vocabulary atlas showing their contents, overlaps, gaps, and reviewed
relationships. It will not create one fused master vocabulary. Spicy Regs will
later consume the selected releases and mappings through profile-aware lookup.

This plan covers all 16 profiles active in the Step 4 source experiment. Ten
profiles contain documents or document-like observations, three are containers,
and three are entities. The inactive public-comment profile remains in the
coverage ledger but does not enter this import cycle.

## Product outcome

At the end of the RefSpec phase, we can answer four practical questions:

1. Which controlled resources apply to each active Spicy Regs profile?
2. What concepts, labels, languages, hierarchies, aliases, codes, and
   identifiers does each resource actually contain?
3. Where do resources overlap, disagree, or leave a gap?
4. Which exact releases and reviewed mappings should Spicy Regs use for
   profile-specific lookup and cross-source discovery?

The later Spicy Regs experiment should then be able to type a record first,
retrieve from the most relevant resources with higher weight, retain a global
fallback, and use reviewed cross-vocabulary mappings to connect related
regulatory, legislative, oversight, judicial, lobbying, and filing records.

## Execution status — 2026-07-30

The inventory and the first acquisition slices are complete. The remaining
work starts from these source-faithful records rather than the former fused
registry.

- **Batch 0 complete:** the generated atlas covers all 16 active profiles and
  the one deferred profile, with 32 controlled resources and explicit uses,
  gaps, and source status.
- **Identifier rule complete:** RefSpec records zero, one, or many identifiers
  as individually qualified values. Each retained identifier records its kind,
  issuing authority, source location, source capture, observation time, and
  effective dates when available. The importer does not select one canonical
  identifier or align parallel identifier arrays.
- **Batch 1 source-native slice complete:** exact Regulations.gov, Federal
  Register, and Unified Agenda controls are pinned. The current capture
  distinguishes 14 non-subject controls and retains source values that cannot
  be normalized safely.
- **Batch 2 acquisition complete, managed-release assembly pending:** the
  official ICPSR XML contains 3,765 records, while the current public term
  index contains 3,805 identities. Exactly 3,760 join; five XML records are
  absent from the current index and 45 current index entries are absent from
  the XML. The importer fails closed on those differences. The next increment
  will publish the URI-verified subset and its complete feature-coverage
  report, not guess the unmatched identities.
- **Batch 3 legislative and lobbying acquisition complete:** the exact
  Congress captures contain 1,043 Legislative Subject Terms and 32 Policy
  Areas. Congress does not publish stable term identifiers or a named release,
  so each source row keeps a capture-specific observation IRI plus every
  publisher identifier when present. The LDA import retains all 79 General
  Issue Codes and all 50 Filing Types as source-native controlled codes.
- **Batch 3 GAO work and reviewed mappings remain open.** Later batches for
  entity/classification, judicial/FCC, specialist vocabularies, and the final
  atlas remain planned.

The full native ICPSR and Congress captures remain in the content-addressed
experiment output rather than Git. Git contains the import logic, exact
source-derived test fixtures, source pins, and deterministic regulatory
control capture needed to reproduce and review the work.

## Boundaries

### RefSpec owns

- source acquisition and exact artifact pins;
- lossless parsing and source-feature coverage;
- managed release and expression-corpus production;
- imported code lists, classifications, identifier authorities, and mapping
  sets;
- vocabulary statistics, comparison, reconciliation, and mapping review; and
- the immutable handoff bundle consumed by lookup implementations.

### Rulespec owns

- the portable meaning of concept schemes, releases, concepts, mappings,
  lifecycle events, assignments, and permissions; and
- graph-wide semantic validation.

### Spicy Regs owns after the RefSpec phase

- document/profile routing;
- physical indexes;
- lexical, sparse, dense, hybrid, and reranking channels;
- profile-specific boosts and the global fallback;
- candidate fusion, user-facing lookup, and measured product value; and
- local concepts when no imported concept represents the document meaning.

DDI, RDF Data Cube, GSIM, XKOS, Neuchâtel, USLM, Akoma Ntoso, ELI, and similar
standards do not become subject vocabularies. Add one only when a real imported
source needs the structure or interchange behavior described in the deferred
standards plan. A full ICPSR thesaurus import does not, by itself, require DDI.

## Starting point

The current local baseline already proves important parts of the approach:

- the 1995 Federal Register thesaurus is a 629-member managed development
  release;
- the current Federal Register Topics API capture remains separate because its
  relationship to the historical publication is unresolved;
- ELSST Versions 5 and 6 are complete managed releases with 6,905 concepts,
  multilingual labels, hierarchy, notes, lifecycle history, and 308,639
  indexed expressions;
- the ICPSR experiment contains seven reviewed lookup bridges into the Federal
  Register release, but ICPSR is not yet a complete managed release;
- the fused registry is no longer an authority for the managed-release
  experiment; and
- Spicy Regs currently has managed-release builders for only Federal
  Register, Unified Agenda, and Congress bills, and its integrated adapter
  currently requests only the general-subject facet.

The imported releases and reviewed bridge are reusable RefSpec assets. The
Spicy Regs limitation is deliberately left for the later lookup phase.

### Minimum useful subject spine

The first useful graph does not require every researched thesaurus:

- Federal Register supplies the regulatory result vocabulary;
- CRS Legislative Subject Terms supplies the legislative result vocabulary;
- ICPSR supplies United States social-policy lookup anchors once its official
  identities can be imported safely;
- ELSST remains the multilingual comparison and mapping arm; and
- specialist schemes enter only after measured misses justify them.

This spine can cover the routing needs of all 10 document profiles while
keeping the result concept in the scheme suited to that document. It avoids
rebuilding the old fused registry.

## Resource roles

Every imported resource must declare one or more of these uses. A resource does
not become a selectable subject scheme merely because it contains labels.

| Use | Meaning | Examples |
| --- | --- | --- |
| Selectable subject | A concept may be proposed as a document subject in its exact source scheme | Federal Register thesaurus, CRS Legislative Subject Terms, MeSH descriptors |
| Source-assigned evidence | The publisher actually assigned the value to the source record | Federal Register topic, GAO Topic, CRS Product Topic, LDA General Issue Code |
| Mapping and search expansion | The resource supplies reviewed alternate paths but does not consume a normal output slot | ELSST, ICPSR, FAST, LCSH, EuroVoc, AGROVOC when used only as references |
| Navigation | Broad grouping or browsing, not a detailed subject assignment | CRS Policy Areas |
| Deterministic code or classification | A source value describes type, stage, industry, service, program, or process | Unified Agenda stage, NAICS, PSC, Nature of Suit |
| Identifier authority | A value identifies an entity or legal/source object | UEI, CAGE, FEC committee ID, FRN, court ID |
| Structure or interchange | A schema describes the record or document structure | Regulations.gov schema, BILLSTATUS, USLM, Governmentwide Spending Data Model |

The same published resource may support more than one use, but each use remains
explicit. Source-assigned evidence and search expansion never establish concept
identity by themselves.

## Active-profile coverage

This table is the completeness ledger for the current import cycle. “Subject
gap” means no maintained authoritative topic scheme was found for that source;
it is an explicit finding, not permission to invent one.

| Active Spicy Regs profile | Record kind | Subject and mapping resources | Other controlled resources to import or pin | Required treatment |
| --- | --- | --- | --- | --- |
| `regulations-docket-v2` | Container | None on the docket; linked documents supply subjects | Regulations.gov docket and document types, agency values, docket identifier, and RIN | Preserve the container and links. Do not assign a document subject to the docket. |
| `regulations-document-v2` | Document | General regulatory and legislative portfolio; linked Federal Register topic when actually assigned; applicable specialist modules | Regulations.gov document and attachment types, agency values, docket ID, Federal Register number, and dates | Tag the document text. Keep source type and attachment values outside the subject pool. |
| `federal-register-document-v1` | Document | Federal Register publication and API topics as distinct evidence sources; general portfolio; applicable specialist modules | Federal Register category, presidential subtype, `toc_subject`, agency, RIN, docket, CFR, citation, and version | Use topics only where the source assigns them. Treat `toc_subject` as action or genre, not a subject. |
| `unified-agenda-observation-v1` | Document-like observation | Federal Register-based source index plus general and specialist text candidates | RIN, agency, stage, priority, timetable, legal authority, CFR, related RIN, and NAICS | Tag the title and abstract. Keep process and industry values deterministic. |
| `cfr-section-v1` | Legal document | General portfolio; CFR List of Subjects as ranking and evaluation evidence | eCFR and GovInfo hierarchy, citation, edition, point-in-time status, and USLM structure when available | Tag the section text. Do not duplicate CFR List of Subjects as an unlabeled scheme. |
| `congress-bill-v1` | Legislative document | CRS Legislative Subject Terms; CRS Policy Areas for navigation; general portfolio; applicable specialist modules | Congress API and BILLSTATUS types, actions, versions, committees, BioGuide identities, and USLM structure | Preserve actual CRS assignments and release context. Keep policy areas broad. |
| `sam-entity-v1` | Entity | No document subjects | UEI, CAGE, NAICS, legal name, registration status, location, and Federal Hierarchy | Normalize entity and classification values. Do not route them through subject ranking. |
| `lobbying-filing-v1` | Document | LDA General Issue Codes as source evidence; reviewed mappings into CRS and the general portfolio; general and specialist candidates from specific-issue text | LDA filing type, period, status, client, registrant, government target, and amendment history | Tag specific-issue text. Keep filing codes and participants in their own facets. |
| `fec-committee-v1` | Entity | No document subjects | FEC committee ID, committee type, designation, organization type, party, sponsor and candidate links, cycle, and effective dates | Normalize the committee. Do not treat committee codes or party as subjects. |
| `gao-report-v1` | Document | General portfolio; actual GAO Topics as source evidence; applicable specialist modules | GAO report ID, product type, date, agency, recommendations, and evidence depth | Use only an actual topic assignment. Keep the obsolete GAO thesaurus historical and mapping-only unless a maintained successor appears. |
| `crs-report-v1` | Document | CRS Legislative Subject Terms and Policy Areas; matching-edition CRS Product Topics; general portfolio | CRS product type, edition, status, report number, dates, bill and committee joins | Never apply a current topic to a different report edition silently. |
| `court-opinion-v1` | Legal document | General portfolio and applicable specialist modules; LCSH or FAST only through reviewed mappings | Court authority, opinion type, version, citations, case and package identity | Record the legal-topic subject gap. Tag opinion text without manufacturing a national court thesaurus. |
| `court-docket-v1` | Container | None on the docket; opinions and filings supply subjects | Court authority, Nature of Suit, case identity, parties, CourtListener status, dates, and access | Preserve the container and links. Keep official and platform-normalized values distinct. |
| `usaspending-recipient-v1` | Entity | No document subjects | UEI, CAGE, recipient identity, NAICS, PSC, Federal Hierarchy, status, and vintage | Normalize entity and classification values. Subjects belong on award or program narratives, not the recipient. |
| `fcc-proceeding-v1` | Container | None on the proceeding; linked filings supply subjects | ECFS proceeding number and flag, bureau, status, dates, and 47 CFR procedure class | Record the FCC-topic subject gap. Preserve the proceeding and links. |
| `fcc-filing-v1` | Document | General portfolio and applicable specialist modules; linked Federal Register topics only when actually assigned | ECFS filing description, filer or author, FRN, bureau, filing and access status, attachment type, and local genre-map version | Tag available filing text. Keep raw source values and implementation genre mappings separate. |

### Deferred profile

`regulations-comment-v1` is registered but inactive in the Step 4 experiment.
It remains outside this cycle. When activated, it should use general and
specialist candidates from comment text while preserving submitter, attachment,
participation, and privacy behavior separately. Aggregate `comments_index` and
relationship-only `fr_docket_links` are not source profiles and do not enter the
ledger.

## Import sequence

The sequence favors useful comparison over source count. Each batch produces a
usable atlas increment before the next batch starts.

### Batch 0 — Freeze the portfolio inventory

1. Generate a machine-readable inventory from the exact Spicy Regs
   `SOURCE_PROFILES` and `STEP4_ACTIVE_SOURCE_TABLES`.
2. Record each profile as document, observation, container, entity, or deferred
   participation.
3. Record its permitted RefSpec facets, source-native values, candidate uses,
   and known subject gap.
4. Pin the research snapshot and code revision used to make the inventory.
5. For every proposed source, record whether an official distribution is
   currently obtainable, how its identifiers and version are represented, and
   what access or reproducibility gap must be solved before import.

**Exit:** all 16 active profiles and the one deferred profile have an explicit
row; no profile inherits a vocabulary by omission.

### Batch 1 — Regulatory base and source-native controls

1. Retain the completed historical Federal Register managed release.
2. Retain the current Federal Register API capture as a distinct, unresolved
   source; do not synthesize a union.
3. Import CFR part-to-subject assignments as evidence connected to exact CFR
   locations and Federal Register terms.
4. Capture Regulations.gov document, docket, comment, attachment, and agency
   values.
5. Capture Federal Register category, agency, and Table of Contents values.
6. Capture Unified Agenda stage, priority, agency, and related-rule values plus
   the RIN identifier grammar.
7. Pin eCFR and GovInfo structural and citation definitions needed by the
   current profiles.

**Exit:** the regulatory documents and containers have a complete source-native
base, while the two Federal Register publications remain visibly distinct.

### Batch 2 — Full social-policy comparison releases

1. Acquire and import the complete ICPSR Subject Thesaurus as its own managed
   release, preserving source identifiers, preferred and alternate terms,
   scope notes, hierarchy, relationships, and exact source revision.
2. Before producing a managed release, prove a deterministic join from every
   imported record to its official public ICPSR term URI or code. The current
   XML record number is source-local evidence, not permission to mint the
   concept IRI. Never derive an ICPSR identity from that number or from a label.
3. Represent descriptors as concepts. Represent authored `USE` and `UF`
   relationships as aliases only after their preferred concept resolves;
   preserve the original non-descriptor record and source locator as evidence.
4. If no complete official URI/code crosswalk or reproducible official term
   index can be acquired, stop the full import. Continue only with
   URI-verified concepts such as those in the current seven-record bridge and
   record the unresolved remainder.
5. Retain ELSST R5 and R6 as separate completed releases and select R6 only for
   current development candidates.
6. Replace the seven-record ICPSR lookup bridge as the primary source view with
   reviewed mapping-set records between exact full releases. Keep the small
   bridge as historical experiment evidence.
7. Generate ICPSR-to-ELSST and ICPSR/ELSST-to-Federal-Register mapping
   candidates. Review a useful sample before publishing any mapping.
8. Keep each scheme independently searchable; do not form a “general core”
   union.

**Exit:** RefSpec can compare three real general or social-policy concept
families at full-release scale and can explain every reviewed connection, or
it has a precise ICPSR identity-gap report and continues safely with the
verified subset.

### Batch 3 — Legislative, lobbying, CRS, and GAO resources

1. Import CRS Legislative Subject Terms and CRS Policy Areas as separate
   schemes.
2. Capture source assignments from current BILLSTATUS or Congress API records.
3. Capture CRS Product Topics and product types with exact report-edition
   provenance; do not claim a reusable independent scheme where the publisher
   does not provide one.
4. Import LDA General Issue Codes and filing code lists.
5. Capture actual GAO Topics and product types. Keep the 1998 GAO thesaurus as
   a historical reference, not a current output authority.
6. Generate reviewed mappings among Federal Register, CRS, ICPSR, ELSST, LDA,
   and GAO concepts where evidence supports them.

**Exit:** bills, lobbying filings, CRS reports, and GAO reports have their
source-native vocabularies plus documented paths into the wider policy graph.

### Batch 4 — Entity and classification backbone

1. Pin the UEI and CAGE identifier definitions and public resolution behavior.
2. Import exact NAICS and Product and Service Code releases used by the source
   data.
3. Capture the Federal Hierarchy used for agency and organization joins.
4. Import FEC committee, designation, organization, party, and filing codes
   with cycle or effective-date context.
5. Pin BioGuide, congressional committee, and FCC FRN identifier definitions
   where current records use them.
6. Add XKOS only if a real classification release or version correspondence
   needs its level and correspondence model.

**Exit:** entity profiles and deterministic classifications resolve through
typed authorities instead of entering the subject index.

### Batch 5 — Judicial and FCC controls

1. Import or pin Nature of Suit codes and official court identifiers.
2. Capture CourtListener-normalized opinion types and statuses separately from
   official court values.
3. Capture Supreme Court opinion type and version ladders where applicable.
4. Capture FCC ECFS proceeding, filing, bureau, access, and submission values.
5. Model the relevant 47 CFR procedure classes as legal/process values, not
   subjects.
6. Publish explicit gap records for the missing national court-topic, docket
   event, and FCC-topic thesauruses.

**Exit:** judicial and FCC profiles have usable type, identity, and process
resources without a fabricated topic authority.

### Batch 6 — Specialist subject modules

Import one module at a time:

1. MeSH descriptors for health and biomedicine;
2. NALT Core for agriculture, food, and rural policy;
3. GEMET for environmental concepts;
4. the NASA Thesaurus after confirming its downloadable release date; and
5. AGROVOC, FAST, LCSH, and EuroVoc only as mapping or search-expansion sources
   when a measured profile use needs them.

Do not concatenate module labels. Agency, document type, cited law, and source
metadata may raise a module's retrieval weight, but the later Spicy Regs router
must preserve a global candidate path.

**Exit:** each retained specialist module improves target availability or
search behavior for at least one named profile without unacceptable
cross-domain leakage.

### Batch 7 — Vocabulary atlas and reviewed graph

Generate both machine-readable and human-readable outputs:

```text
portfolio/
├── resource-inventory.json
├── profile-resource-matrix.json
├── releases/
│   └── <resource>/<release>/...
├── coverage/
│   └── <resource>-coverage.json
├── comparisons/
│   ├── vocabulary-atlas.json
│   ├── vocabulary-atlas.md
│   └── mapping-candidates.jsonl
└── mappings/
    └── <reviewed-mapping-set>/...
```

For every release, the atlas reports:

- concept and expression counts;
- preferred, alternate, and hidden label counts by language;
- notation, definition, note, status, and replacement coverage;
- hierarchy edge counts, multiple-parent frequency, and navigation depth where
  the source hierarchy supports it;
- source-assigned use by current Spicy Regs profile;
- normalized label overlap with other schemes;
- ambiguous reused labels, false friends, and near-duplicate candidates;
- publisher-authored mappings separately from project-reviewed mappings; and
- explicit profile, facet, and use eligibility.

Normalized label overlap is a review lead, never an identity rule. The atlas
must show identical labels in different schemes as separate concepts unless a
reviewed mapping connects them.

**Exit:** a reviewer can inspect what every vocabulary contains, how it differs
from the others, which mappings are supported, and which active profiles still
have gaps.

## Fast import loop

Stay in the experiment lane while building the portfolio. One adapter run
should generate the required RefSpec records and evidence instead of asking a
researcher to hand-author governance files.

Every import must:

1. pin exact source bytes or an explicit non-retrieved authority definition;
2. preserve source-issued identities and all semantically relevant source
   features;
3. report source-observed, parsed, indexed, excluded, and failed counts;
4. produce a deterministic managed release and expression-corpus digest;
5. retain a small source-derived fixture for ordinary offline tests;
6. keep full native distributions in the content-addressed experiment store,
   not Git; and
7. permit only `developmentOnly` candidate use.

The full promotion process begins only when another consumer depends on a
stable release, the team selects accepted output, or the team publishes a
conformance or accuracy claim.

## Rights and access

Record publisher, license, attribution, access terms, and uncertainty for every
resource. Licensing uncertainty does not filter, truncate, disable, or prevent
playground acquisition, indexing, comparison, model use, display, or lookup.

Privacy, access control, security, statutory data-use restrictions, API
credentials, and protected fields remain independent controls. Those controls
may limit acquisition or display when they apply; a generic licensing concern
does not.

## Mapping rules

1. Preserve exact, close, broad, narrow, and related mappings as different
   relationships.
2. Never create a mapping from label equality alone.
3. Keep source and target release pins on every mapping.
4. Keep publisher-authored and project-reviewed mappings distinguishable.
5. Start with one-hop candidate expansion. Measure longer paths separately.
6. Use high-level concepts as navigation and ranking signals, not automatic
   replacements for more specific concepts.
7. Discount labels reused broadly across unrelated vocabularies unless the
   document context or a reviewed mapping disambiguates them.
8. Keep aliases useful for retrieval but below exact preferred-label and
   source-assigned evidence in ranking.

## RefSpec acceptance checks

The RefSpec phase is complete when:

- all 16 active profiles have an explicit resource/use row;
- all 10 document profiles have a primary subject path or a documented subject
  gap plus open-label behavior;
- all three containers and all three entities use the correct non-subject
  controls;
- every imported release passes lossless feature coverage;
- conflicting official publications remain separate unless a reviewed
  reconciliation resolves them;
- the URI-verified ICPSR scope, ELSST, Federal Register, and CRS releases can be
  inspected together without merged identities;
- the atlas reports scale, languages, hierarchy, label reuse, overlap, gaps,
  and mappings;
- at least one reviewed path connects regulatory and legislative resources,
  and another connects a lobbying or oversight source;
- no active profile silently inherits an arbitrary vocabulary;
- no label-derived identity or fused-registry authority reappears; and
- the handoff bundle opens through RefSpec's public managed-release reader.

## Later Spicy Regs phase

After the atlas is reviewed, create a separate Spicy Regs execution plan from
the selected portfolio. That plan should:

1. add managed-release support for the remaining document profiles;
2. route each profile to its source-native, general, and specialist candidate
   lanes;
3. rank source-assigned values and preferred labels above generic aliases, use
   high-level concepts as routing priors, and retain specific exact concepts;
4. discount vocabulary labels with broad cross-scheme reuse;
5. expand through reviewed mappings without flattening source identities;
6. keep entity, legal-location, genre, process, and subject candidates in
   separate facets;
7. create a new profile-stratified development dataset instead of reviving the
   fused-registry targets;
8. keep the original 35 items permanently development-only as retrieval
   regressions; and
9. measure target availability, Recall@K, ranking, abstention, latency, cost,
   cross-facet leakage, and cross-profile search value separately.

The first Spicy Regs experiment should compare:

- one global vocabulary index;
- profile-specific indexes with a global fallback;
- profile-specific indexes plus source-assigned evidence;
- the same configuration plus reviewed one-hop mappings; and
- the same configuration with specialist-module activation.

Use a new 36-case development smoke test:

- three frozen cases for each of the 10 document profiles: one direct target,
  one mapping-only phrase, and one hard near miss or `notRepresented` meaning;
  and
- one case for each of the six container or entity profiles, requiring exact
  source identity or code behavior and forbidding subject output.

Freeze the releases and mappings before writing expected cases. Require direct
targets to remain in the top three, mapping-only phrases to improve without
foreign-anchor output, and all six non-document cases to produce zero subject
assignments. Treat these cases as a falsifiable development smoke test, not an
accuracy estimate.

This comparison will show whether document typing, scoped vocabularies, and
cross-vocabulary links improve search before the project commits to a product
architecture.

## Stop rules

Stop or defer a resource when:

- no exact maintained source or reproducible snapshot can be acquired;
- it is a schema, ontology, identifier list, or process code being mistaken for
  a subject thesaurus;
- it has no named use in an active profile;
- its import silently loses source features;
- its labels add volume but not target availability or useful search paths;
- a specialist hard filter removes relevant global candidates;
- mapping expansion produces unacceptable ambiguity or cross-facet leakage; or
- the only evidence for identity is spelling or normalized-label equality.

Record the gap and move to the next batch. Do not fill a missing authority with
an unsupported synthetic vocabulary.

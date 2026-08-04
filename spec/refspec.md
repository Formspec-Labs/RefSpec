<!-- markdownlint-disable MD013 -->

# RefSpec 1.0

## Editor's Draft, 29 July 2026

> **Full name:** Regulatory Evidence Framework
>
> **Technical abbreviation:** REF
>
> **This version:** [refspec.md](refspec.md)
>
> **Rulespec profile:** [RefSpec Rulespec Application Profile](../profiles/rulespec-application-profile.md)
>
> **Core enrichment profile:** [RefSpec Core Enrichment Profile](../profiles/enrichment-profile.md)
>
> **Experiment roadmap:** [Managed vocabulary experiment roadmap](../plans/managed-vocabulary-experiment-roadmap.md)
>
> **Historical implementation concept:** [Early RefSpec implementation plan](../plans/implementation-plan.md)
>
> **Status:** Rulespec-dependent Editor's Draft
>
> **Editors:** Formspec Labs
>
> **Feedback:** [Formspec-Labs/RefSpec issues](https://github.com/Formspec-Labs/RefSpec/issues)
>
> **Publication terms:** Pending; this public editor's draft grants no license

> **Historical:** This broad pipeline draft predates the four-product split and no longer
> controls RefSpec's scope. It is retained as design lineage and as the compatibility
> inventory referenced by the
> [product boundary and API disposition](../docs/product-boundary-and-api-disposition.md).
> The normative consumer contract is the
> [Vocabulary Atlas Distribution 1.0 binding](../bindings/atlas/1.0/README.md), which defines
> the published two-file boundary that other products verify. The
> [managed vocabulary release decision record](managed-vocabulary-release.md) records the
> retired standalone design behind REF-001…REF-006; it is not a specification and it is not
> implemented.

## Abstract

RefSpec, the Regulatory Evidence Framework (REF), defines an acquisition,
processing, and application profile for regulatory evidence systems. It preserves exact
source material, resolves source records into versions and renditions, creates
reproducible evidence addresses, runs deterministic and probabilistic
processing, governs registry import and deployment, and publishes auditable
query products.

REF depends normatively on Rulespec for portable semantic records. Rulespec is
the single source of truth for artifacts used as assertion evidence, source
fragments, evidence bindings, assertions, concept assignments, confidence, AI
lineage, attestations, local adoption, authority, lifecycle, access, retention,
reference-resource releases, and semantic conformance. REF does not redefine
those records. It specifies how an operational regulatory pipeline creates,
evaluates, and serves them.

The specification does not require a storage engine, graph database, search
engine, controlled vocabulary, embedding model, or language-model provider.

## Status of This Document

This document is a W3C-style project specification. It is not a W3C Standard,
has not undergone the W3C Process, and does not imply W3C endorsement.

This draft starts from the project's source inventories and recovered external
research. The dated row and resource universe in the two inventories below is
the minimum normative portfolio-coverage and stress-test baseline under
Section 2.6, not a closed list of what REF can process. Their proposed
architectures, classifications, priorities, and adoption recommendations
remain research inputs, not adopted design:

- [Source Vocabulary, Ontology, and Authority Catalog](../docs/research-inputs.md#normative-portfolio-baseline-for-this-editors-draft)
- [Source and Document Type Matrix](../docs/research-inputs.md#normative-portfolio-baseline-for-this-editors-draft)
- [Blind External Research Recovery](../docs/research-inputs.md#informative-research)
- [When to Abandon a Controlled Vocabulary, and What US Federal Policy Vocabularies Exist](../docs/research-inputs.md#informative-research)

RefSpec and Rulespec are maintained by Formspec Labs. This draft therefore
places reusable meaning in Rulespec even when an upstream change is required,
rather than defining a temporary REF substitute. Section 4 identifies the
binding and any upstream dependency that must be resolved before a conforming
release.

Requirements may change before version 1.0. Implementers should identify the
exact REF draft and immutable Rulespec release in conformance claims.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Conformance](#2-conformance)
3. [Terminology](#3-terminology)
4. [Rulespec dependency and conceptual model](#4-rulespec-dependency-and-conceptual-model)
5. [Operational information model](#5-operational-information-model)
6. [Identity, versions, and time](#6-identity-versions-and-time)
7. [Evidence addressing and operational provenance](#7-evidence-addressing-and-operational-provenance)
8. [Processing model](#8-processing-model)
9. [Semantic enrichment](#9-semantic-enrichment)
10. [Relationship discovery and publication](#10-relationship-discovery-and-publication)
11. [Policy threads](#11-policy-threads)
12. [Registry operations and concept governance](#12-registry-operations-and-concept-governance)
13. [Publication and query behavior](#13-publication-and-query-behavior)
14. [Privacy, security, rights, and safety](#14-privacy-security-rights-and-safety)
15. [Validation and evaluation](#15-validation-and-evaluation)
16. [Binding manifest and interoperability](#16-binding-manifest-and-interoperability)
17. [References](#17-references)
18. [Appendix A: Example operational and Rulespec records](#appendix-a-example-operational-and-rulespec-records)
19. [Appendix B: Relationship predicate ownership](#appendix-b-relationship-predicate-ownership)
20. [Appendix C: Requirement index](#appendix-c-requirement-index)

## 1. Introduction

### 1.1 Problem statement

Regulatory information arrives as records, web pages, XML, PDFs, attachments,
legal text, measurements, comments, dockets, cases, and external indexes. These
inputs do not share one identity model, version model, document taxonomy, or
subject vocabulary.

A document-first classifier hides those differences. It also makes generated
tags and links appear more authoritative than their evidence supports. REF
instead asks a narrower first question:

> What can the system preserve and verify before it interprets the material?

The answer creates a stable evidence layer. Search, classification, summaries,
entity resolution, relationship discovery, and future models remain replaceable
derived services.

### 1.2 Goals

REF has ten goals:

1. Preserve exact source content and retrieval context.
2. Distinguish captures, source-record revisions, source-issued versions, and
   renditions.
3. Type documents, participation records, containers, entities, observations,
   events, and external references before semantic enrichment.
4. Project accepted semantic results into Rulespec records bound to exact
   evidence or declared input assertions.
5. Keep processing state separate from Rulespec origin, attestation,
   authority, lifecycle, and product adoption.
6. Represent explicit and implicit relationships without collapsing
   similarity, dependency, identity, causation, or legal effect.
7. Support controlled concepts, grounded open labels, concept proposals, human
   governance, and abstention without redefining Rulespec concept semantics.
8. Publish historical and current views that users can audit and reproduce.
9. Account explicitly for every source and controlled resource in the dated
   portfolio baseline without requiring every one to be ingested or adopted.
10. Admit future source families, data products, controlled resources,
    executable models, standards, and external systems through governed
    extension profiles without coercing them into an inaccurate core route or
    redefining portable Rulespec semantics.

### 1.3 Non-goals

REF does not define:

- assertions, evidence bindings, confidence records, attestations, adoption,
  authority, lifecycle, access scopes, retention policies, concepts, concept
  assignments, concept mappings, or AI lineage;
- a universal regulatory topic vocabulary;
- the optimum number of concepts in a vocabulary;
- mandatory ingestion or adoption of every inventoried federal source;
- a legal reasoning or legal-advice method;
- a required database, graph engine, vector index, or queue;
- a required parser, optical character recognition system, embedding model,
  reranker, or language model;
- a single score that establishes truth or production readiness; or
- a rule that every artifact must receive a subject or relationship.

Topic tagging is an optional REF module. A conforming evidence implementation
may provide no automated subject assignments.

### 1.4 Design principles

REF follows these principles:

- **Preserve first.** Store source bytes and source-native values before
  normalization.
- **Type second.** Identify what a record represents before processing its
  text.
- **Link third.** Resolve official identifiers, citations, versions, and
  lifecycle structure before adding probabilistic links.
- **Enrich fourth.** Publish accepted semantic labels and inferred
  relationships as evidence-bound Rulespec assertions.
- **Append decisions.** Record review, adoption, and lifecycle through the
  applicable Rulespec records without erasing history.
- **Keep authority visible.** Rulespec attestations and local adoption do not
  convert an inference into a source statement or legal authority.
- **Allow no answer.** Abstention and explicit failure are valid outputs.
- **Rebuild derived views.** Search, vector, and graph indexes are disposable
  views, not the only record of truth.

## 2. Conformance

### 2.1 Normative language

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**,
**RECOMMENDED**, **MAY**, and **OPTIONAL** in this document are to be interpreted
as described in BCP 14 when, and only when, they appear in all capitals.

Normative requirements carry stable identifiers such as `REF-CORE-001`.
Examples, notes, diagrams, and appendices are informative unless they state
otherwise.

### 2.2 Conformance classes

**REF-CONF-011:** An implementation MAY claim one or more classes:

| Class | Required capability | Required classes |
| --- | --- | --- |
| `REF-Core-Producer` | Produces baseline-enumeration reports, inventory-coverage manifests, captures, source-record revisions, source-resource versions, rendition-processing records, selector-resolution records, run receipts, REF publication-release manifests, and their required Rulespec records. | None |
| `REF-Relationship-Producer` | Discovers and adjudicates relationship candidates and publishes accepted durable results as Rulespec records. | `REF-Core-Producer` |
| `REF-Enrichment-Producer` | Runs typed, open-set enrichment under immutable profiles and configurations, evaluates it against sealed gold, selects exact passing configurations, and publishes accepted results as Rulespec records. | `REF-Core-Producer` |
| `REF-Reference-Resource-Registry` | Imports, snapshots, proves feature coverage, reconciles conflicts, indexes expressions, validates, selects for deployment, and rolls back subject schemes, ontologies, identifier authorities, entity registries, code lists or classifications, schemas, and mapping sets whose portable release records conform to Rulespec. | `REF-Core-Producer` |
| `REF-Policy-Thread-Publisher` | Publishes versioned application views and Rulespec membership assertions under Section 11. | `REF-Core-Producer`, `REF-Relationship-Producer` |
| `REF-Query-Service` | Returns current, historical, evidence, and supported query-time association views under Section 13. | None; see `REF-CONF-010` |
| `REF-Participation-Processor` | Processes public participation under the additional controls in Section 14. | `REF-Core-Producer` |
| `REF-Validator` | Validates REF-owned operational records and behavior, invokes a pinned Rulespec validator for Rulespec records, and reports both result sets without merging them. | None |

A full capability-set implementation conforms to
`REF-Core-Producer`, `REF-Relationship-Producer`,
`REF-Enrichment-Producer`, `REF-Reference-Resource-Registry`, and
`REF-Query-Service`. The participation class remains optional and separately
governed. Complete portfolio accounting covers every row in the Section 2.6
minimum baseline and every additional item in the implementation's declared
portfolio; it is not a requirement to ingest or adopt every item. A claim that
the full-framework design can represent that complete portfolio additionally
requires `supported` representability for every coverage component.

### 2.3 Conformance claims

**REF-CONF-001:** A conformance claim MUST identify:

- the REF version and draft date;
- the immutable Rulespec release or commit, constraint-bundle digest,
  conformance level, adopted Rulespec profiles, validator version, and
  validator result;
- each claimed class;
- the serialization and media type;
- every implemented extension profile;
- each immutable registry, mapping, enrichment profile, output profile,
  configuration, sealed-gold, evaluation-result, deployment-decision, or other
  release assessed by the claim, identified by resource type, identifier,
  version when applicable, and content digest;
- the validator and test-suite version;
- the validation date and result;
- the immutable inventory-coverage manifest; minimum baseline inventory
  identifiers and digests; every additional declared inventory or item;
  extension profiles; and row, occurrence, component, and fixture-accounting
  results; and
- known limits or failed optional recommendations.

**REF-CONF-002:** An implementation MUST satisfy every MUST and MUST NOT
requirement applicable to each class it claims.

**REF-CONF-003:** A validator MUST report results by requirement identifier. It
MUST NOT replace failed class-specific results with one aggregate pass score.

**REF-CONF-004:** An implementation MUST use Rulespec's distinct records for
assertion origin, attestation, authority, confidence, lifecycle, and local
adoption. It MUST NOT mint REF fields or value sets that duplicate them.

### 2.4 Extensions

**REF-CONF-005:** Extensions MUST use stable, documented names and MUST NOT
change the meaning of REF-defined fields or Rulespec terms.

**REF-CONF-006:** A consumer SHOULD preserve unknown extension fields during a
lossless read-write round trip.

**REF-CONF-007:** A profile MAY add stricter requirements. It MUST identify
those requirements and MUST NOT weaken REF's operational requirements or the
pinned Rulespec requirements.

**REF-CONF-008:** A producer claiming a class MUST also claim and pass every
required class listed in the conformance table.

**REF-CONF-014:** The two dated inventories are a required minimum coverage
suite, not a closed-world type registry. A conforming implementation MAY add
sources, resources, standards, models, services, media, jurisdictions, and
other portfolio items through versioned extension profiles. Every added item
MUST pass the same enumeration, routing, representation, fixture, rights, and
release-accounting controls as a baseline item.

**REF-CONF-015:** An extension profile MUST use stable absolute IRIs for new
route or processing values, define their meaning and boundary from every
overlapping core value, identify their REF processing binding and portable
Rulespec or external-standard binding, and provide positive, negative, and
lossless round-trip fixtures. It MUST NOT use a new value merely to avoid an
applicable core route or upstream semantic requirement.

### 2.5 Requirement applicability and data bindings

Requirement applicability follows this table:

| Conformance claim or feature | Applicable requirement groups |
| --- | --- |
| Every producer and `REF-Query-Service` | `REF-CONF`, `REF-BIND`, `REF-PORT`, applicable `REF-SEC`, `REF-SAFE`, `REF-RIGHTS`, `REF-TEST`, and `REF-INT` |
| `REF-Core-Producer` | `REF-CAP`, `REF-SRC`, `REF-ART`, `REF-EVID`, `REF-TYPE`, `REF-ID`, `REF-VER`, `REF-TIME`, `REF-PROV`, and `REF-PIPE` |
| Semantic-reference candidate output | `REF-SEM` |
| `REF-Enrichment-Producer` | `REF-SEM`, `REF-ENR`, `REF-CAND`, `REF-ACC`, and `REF-ASSIGN` |
| Registered assignment output | `REF-ACC-008` and a passing `REF-Reference-Resource-Registry` manifest for the referenced Rulespec reference-resource release |
| `REF-Relationship-Producer` | `REF-REL`; plus `REF-SIM`, `REF-DEP`, `REF-PATH`, or `REF-ABS` when that feature is emitted |
| `REF-Reference-Resource-Registry` | `REF-VOC`; `REF-GOV` and Rulespec concept and mapping requirements apply only when those semantic payloads are present |
| `REF-Policy-Thread-Publisher` | `REF-THR` |
| `REF-Query-Service` | `REF-QRY` and `REF-EXP` |
| `REF-Participation-Processor` | `REF-PRIV` and every applicable `REF-SEC`, `REF-SAFE`, and `REF-RIGHTS` requirement |
| `REF-Validator` | `REF-CONF`, `REF-TEST`, `REF-BIND`, applicable `REF-SEC`, `REF-SAFE`, `REF-RIGHTS`, and the REF requirements named by its validator profile |
| Accepted automated output | `REF-EVAL` for its source, facet, predicate, and output profile |

**REF-CONF-009:** A conformance manifest MUST list every normative requirement
in the claimed class closure as `pass`, `fail`, or `notApplicable`, with test
evidence or a reason. An implementation MUST NOT mark a requirement not applicable
when the implementation emits the record type or feature that triggers it.

**REF-CONF-010:** A `REF-Query-Service` conformance claim MUST name the
producer classes, versioned REF profiles, and Rulespec binding represented in
the service's data.

**REF-CONF-012:** A `REF-Validator` conformance claim MUST name the REF version,
serialization bindings, classes, profiles, and requirement set it validates.
The validator MUST pass a published validator-conformance suite containing
valid and intentionally invalid REF fixtures for that declared scope, accept
every valid REF reference fixture, reject every invalid REF reference fixture,
and report the applicable requirement identifiers. It MUST invoke, not
reimplement, the pinned Rulespec validator for Rulespec records.

**REF-CONF-013:** A conformance claim MUST distinguish `portfolioAccounting`
from `fullFrameworkDesignCoverage`. The former requires exhaustive row and
component accounting. The latter additionally requires `supported`
representability for every component, including the concrete mappings and
passing component fixtures required by `REF-PORT-012`. Neither status implies
adapter or import implementation, release inclusion, or rights/use
authorization. Both claims cover the mandatory dated baseline plus the
implementation's complete declared portfolio and all active items under
`REF-PORT-013`; neither claim means that the two dated inventories are REF's
closed universe.

The REF abstract model is normative, but an exchange needs a concrete data
binding.

**REF-BIND-001:** A conforming REF serialization profile MUST define field names,
datatypes, cardinalities, identifier grammar, ordering and canonicalization
rules, null and absence behavior, extension handling, value-set bindings, and
the mapping from serialized values to REF-owned operational records.

**REF-BIND-002:** A conformance claim MUST identify and validate against one
serialization profile. It MUST NOT claim serialization interoperability from
the abstract model alone.

**REF-BIND-003:** Two REF serialization profiles MAY claim operational
interoperability only when a published round-trip test preserves every
applicable REF identifier, type, source-native value, evidence address, time
value, rights-policy reference, release decision, and supersession link.
Semantic interoperability is determined by the pinned Rulespec binding and
Rulespec conformance, not by a parallel REF semantic model.

**REF-BIND-004:** A serialization profile that supports deterministic
processing MUST define the canonical deterministic payload, its digest
algorithm, which run-instance provenance fields are excluded from that digest,
and how each run receipt links to the stable payload.

### 2.6 Portfolio coverage

The portfolio baseline consists of the row and resource universe in these
dated inputs:

- [Source and Document Type Matrix, 28 July 2026](../docs/research-inputs.md#normative-portfolio-baseline-for-this-editors-draft)
- [Source Vocabulary, Ontology, Thesaurus, and Authority Catalog, 28 July 2026](../docs/research-inputs.md#normative-portfolio-baseline-for-this-editors-draft)

The inventories are proposed research artifacts. This specification adopts
their enumerated universe as the minimum coverage corpus only. It does not adopt
their current architecture, proposed classifications, priorities, source
roles, vocabulary roles, or recommendations. Each implementation profile
independently validates route, type, authority, rights, permitted use, and
production suitability and preserves unknown or disputed values. Additional
versioned inventories and individual portfolio items may extend this corpus
under `REF-CONF-014`; they do not require a new REF version when existing core
routes fit.

An `InventoryCoverageManifest` is an immutable REF operational record. It
references each baseline row by a stable inventory-local key or locator rather
than copying the row. Each row account decomposes the row into one or more
coverage components. A component is one source role, controlled-resource role,
named feed, reference spine, external system, or other semantic unit that can
receive one unambiguous route. Every component declares exactly one route
family, `source` or `controlledResource`, before selecting a route from that
family. `source` covers evidence-producing or externally joined inputs;
`controlledResource` covers governed resources used to identify, structure,
interpret, map, validate, calculate, or constrain them. The named core routes
are not a closed list: a versioned extension profile may add an absolute-IRI
route within either family under `REF-CONF-015`. A compound row such as “Document plus
Observation” therefore has at least two components. Each source component also
has one acquisition mode: `captured` when REF obtains source material, or
`externalJoin` when REF retains an identifier-based join to the authoritative
external system. A mixed Entity plus External-join row is therefore an
`entity` component with `externalJoin` acquisition, not a combined semantic
type. Each component keeps four decisions independent:

1. whether the framework can represent the item;
2. whether an adapter or import path exists;
3. whether a named release or environment includes it; and
4. whether the intended acquisition, processing, model, display, and
   redistribution uses are authorized.

The manifest also pins a deterministic `BaselineEnumerationReport` by
identifier, version, and digest. The report classifies every data row in every
GitHub Flavored Markdown table in both baseline files as:

- `coverageRow`, which receives exactly one manifest row account;
- `constituentRow`, which names one `coverageRow` parent and whose distinct
  named constituents and roles become components under that account; or
- `definitionRow`, which defines explanatory structure and receives no
  manifest row account.

The report also enumerates, from table cells as well as prose and lists, every
occurrence of a named source, feed, reference spine, external system,
controlled resource, distinct subtype group, or separately stated semantic
role. Each occurrence has a row, cell, list-item, or source-span locator and is
classified as a `namedPortfolioItem` or `descriptiveMention`. Each named
portfolio item either resolves to an existing `coverageRow` and one or more
components under that account or receives its own stable manifest row account.
A descriptive mention remains visible with its locator and reason; it cannot
hide an item or role that the inventories propose to source, join, govern,
map, classify, or otherwise use. A definition row likewise remains visible
with its locator and reason. The report publishes raw table-row and occurrence
counts, counts by classification, and the exact parsing, item-discovery,
normalization, and review procedure used to derive them.

Route, semantic use, and delivery status are separate. In addition to its one
route, each component declares one or more applicable semantic/use modes:

| Mode | Meaning |
| --- | --- |
| `directAuthority` | The resource is an approved direct authority for a portable value or identity |
| `sourceEvidence` | The source supplies evidence that remains attributable to it |
| `deterministicControl` | The resource supplies identifiers, codes, structure, or other deterministic control values |
| `mappingOnly` | The resource is used only for translation, retrieval, or expansion, not as a direct output authority |
| `externalReference` | The system retains an identifier-based reference to the authoritative external resource |

Status values are constrained by dimension:

| Dimension | Meaning of `supported` | Allowed statuses |
| --- | --- | --- |
| Representability | The framework can represent the component without semantic loss | `supported`, `planned`, `deferred`, `unsupportedWithReason`, `notAssessed` |
| Adapter or import implementation | The adapter or import path is implemented | `supported`, `planned`, `deferred`, `unsupportedWithReason`, `notApplicable`, `notAssessed` |
| Release inclusion | The named release or environment includes the component | `supported`, `planned`, `deferred`, `unsupportedWithReason`, `notApplicable`, `notAssessed` |
| Rights/use authorization | Non-authoritative summary of whether the stated use is authorized | `supported`, `rightsBlocked`, `notApplicable`, `notAssessed` |

`supported` means the named dimension is implemented or approved for the
declared scope. For the rights/use dimension, it reports the outcome found in
the referenced authoritative records; it does not make that decision.
`planned` means approved work is scheduled but unavailable.
`deferred` means deliberately outside the current delivery sequence.
`unsupportedWithReason` records a concrete capability limit.
`notAssessed` means no evidence-backed decision exists yet.
`notApplicable` means the dimension does not apply to the declared component
and mode. Neither means supported. `externalJoin` is a source acquisition
mode, `mappingOnly` is a semantic/use mode, and `rightsBlocked` is only a
rights/use authorization summary. The manifest never authorizes use:
`RightsAssessment` plus the adopted Rulespec and external rights policy remain
authoritative.

`supported` in one dimension does not imply `supported` in another. For
example, an ontology may be representable and imported while production use
remains `rightsBlocked`.

**REF-PORT-001:** An inventory-coverage manifest MUST identify the exact two
baseline files, their dates, digest algorithms, and content digests and MUST
pin the exact `BaselineEnumerationReport` and its Rulespec audit attestation.
It MUST contain exactly one row
account for every `coverageRow` and every `namedPortfolioItem` that does not
resolve to an existing `coverageRow`. Each account MUST contain one or more
coverage components that exhaustively represent that row, its linked
`constituentRow` entries, every `namedPortfolioItem` resolved to it, and all of
their distinct named constituents and roles.
Repeated references to the same real resource MAY point to one shared
component identity, but no required row account, named portfolio item,
constituent, or role may disappear through deduplication.

**REF-PORT-002:** Every source coverage component MUST select exactly one route:
the core route `document`, `participation`, `container`, `entity`,
`observation`, or `event`, or one absolute-IRI source route registered by a
conforming extension profile.
It MUST also select exactly one acquisition mode: `captured` or
`externalJoin`. A row with more than one actual semantic role or acquisition
pattern MUST decompose into multiple components. Each route and acquisition
mode MUST be independently justified from the source's actual role and MUST
NOT be copied blindly from a proposed inventory classification.

**REF-PORT-003:** Every controlled-resource coverage component MUST select
exactly one route: the core route `subjectScheme`, `ontology`,
`identifierAuthority`, `entityRegistry`, `codeList`, `classification`,
`schema`, or `mappingSet`, or one absolute-IRI controlled-resource route
registered by a conforming extension profile. A
row that bundles multiple named resources or roles MUST decompose into multiple
components. The route MUST describe the resource's role in the named profile;
the same external resource MAY have a separately justified route in another
profile. These routes are REF coverage roles, not a closed Rulespec
`dcterms:type` value set.

**REF-PORT-004:** Every coverage component MUST record its semantic/use modes
and representability, adapter or import implementation, release inclusion,
and rights/use authorization as separate dimensions. Each dimension MUST use
only its allowed status and MUST include scope, evidence, owner, decision time,
and reason when the status is not `supported`. Rights/use status MUST be scoped
to the stated acquisition, processing, model, display, or redistribution use.
Both `supported` and `rightsBlocked` MUST reference the exact
`RightsAssessment` and applicable adopted Rulespec and external policy
evidence. A consumer MUST resolve authorization from those records, not from
the coverage-manifest summary.

**REF-PORT-005:** An `externalJoin` acquisition mode MUST identify the external
authority, join identifiers, and versioning strategy. A `mappingOnly` mode MUST
identify the mapping path and exact releases. `rightsBlocked` MUST identify
the blocked uses without exposing restricted terms. An
`unsupportedWithReason` status MUST describe the missing capability and the
condition for reconsideration.

**REF-PORT-006:** Complete portfolio accounting requires 100 percent of table
data rows and named portfolio items to be validly dispositioned in the pinned
`BaselineEnumerationReport`; exactly one valid, non-placeholder row account
for every `coverageRow` and otherwise unrepresented `namedPortfolioItem`;
exactly one valid parent for every `constituentRow`; no row account for a
`definitionRow`; and routed components for 100 percent of the distinct named
constituents and roles under the accounts. A component may expose a
representability gap. Full-framework design coverage additionally requires
representability status `supported` and the proof required by `REF-PORT-012`
for every component. Neither claim requires 100 percent adapter
implementation, ingestion, registry import, release inclusion, or rights
authorization.

**REF-PORT-007:** Each release report MUST publish the manifest identifier and
digest; the pinned `BaselineEnumerationReport` identifier and digest; raw row
and named-item counts; counts by `coverageRow`, `constituentRow`,
`definitionRow`, and `namedPortfolioItem`; expected and actual row-account and
component counts; counts by route family, route, acquisition mode,
semantic/use mode, and status within each dimension; changes from the prior
manifest; and stable keys for blocking entries. An unaccounted count applies
only to entries that require a row account or component under
`REF-PORT-001`; definition rows are reported, not unaccounted. A release MUST
NOT claim full-framework design coverage while any required row account,
named constituent, or role is missing or any component has an unspecified
route, applicable acquisition mode, semantic/use mode, or dimension, or a
representability status other than `supported`.

**REF-PORT-008:** A changed baseline inventory, row decomposition, component,
route family, route, acquisition mode, semantic/use mode, status dimension,
reason, scope, evidence, or ownership decision MUST create a new immutable
manifest version.
Historical `PublicationReleaseManifest` records MUST continue to resolve the exact
inventory-coverage manifest they used.

**REF-PORT-009:** The baseline enumeration MUST include, where present in the
two dated inventories, all current source rows, all roadmap tiers, `E01`–`E05`,
`G01`–`G09`, every named feed or reference spine, every adjacent external
system, every external-join row, and every table row or out-of-table item that
names a controlled resource or distinct constituent. Genuine definition and
completeness-ledger rows remain in the enumeration report but do not receive
coverage accounts solely because they are table rows. Coverage MUST NOT be
limited to `C`, `T`, or `L` identifier series.

**REF-PORT-010:** Every coverage component MUST select exactly one route
family, `source` or `controlledResource`, and then exactly one route allowed by
`REF-PORT-002` or `REF-PORT-003` for that family. A named feed, reference
spine, external system, adjacent resource, or other semantic unit MUST
decompose when necessary and classify by its actual role; it MUST NOT remain
outside both route families.

**REF-PORT-011:** The pinned baseline-enumeration report MUST assign a stable
locator and exactly one classification to every data row in every GitHub
Flavored Markdown table in both baseline files, excluding only the header and
delimiter rows defined by that syntax. A `constituentRow` MUST name exactly one
`coverageRow` parent. A row MAY be a `definitionRow` only when it defines a
role, status, format, code pattern, decision state, completeness total, or
other explanatory structure and does not itself name a source, feed, reference
spine, external system, controlled resource, or distinct constituent requiring
coverage. The report MUST also enumerate every occurrence of a named source,
feed, reference spine, external system, controlled resource, distinct subtype
group, or separately stated semantic role inside table cells and outside
tables. Each occurrence MUST have an exact source locator, be exactly one of
`namedPortfolioItem` or `descriptiveMention`, and state the account and
component resolution for a named portfolio item. A `descriptiveMention` MUST
state why the occurrence is not a proposed source, join, governed resource,
mapping, classification, or use. The accounting validator MUST independently
recompute the raw table-row universe, verify every occurrence locator and
expected constituent count, and reject a count mismatch, an unclassified or
multiply classified entry, an invalid parent or resolution, or a definition
or descriptive classification that hides a portfolio item or role. An
independent reviewer MUST audit source-text exhaustiveness and record the
result as a Rulespec attestation targeting the report; a full-framework
design-coverage claim requires a passing attestation.

**REF-PORT-012:** A representability status of `supported` MUST reference a
versioned, concrete, lossless representation mapping for that component. The
mapping MUST identify the applicable REF operational records and fields, the
pinned Rulespec or external types and predicates, the handling of every named
constituent and role, and any declared non-semantic source-native values. It
MUST also reference at least one passing positive fixture and one passing
round-trip fixture that exercise the component's actual structure. A
full-framework design-coverage claim MUST fail when any mapping or fixture is
missing, stale relative to the manifest or pinned specifications, lossy, or
does not cover every named constituent and role.

**REF-PORT-013:** Every additional inventory or individually onboarded
portfolio item declared by an implementation MUST be pinned by identifier,
version, and digest and incorporated into a new `BaselineEnumerationReport`
and `InventoryCoverageManifest` version. Complete accounting and
full-framework design coverage apply to the dated minimum baseline plus the
implementation's entire declared portfolio; an implementation MUST NOT keep
an active source or controlled resource outside that portfolio to preserve a
coverage claim.

**REF-PORT-014:** An extension route MUST belong to exactly one core route
family and MUST declare why the core routes in that family would lose or
misstate information. Its profile MUST define component boundaries,
acquisition-mode applicability, operational record and processing bindings,
source-native value preservation, portable Rulespec or external-standard
bindings, conformance requirements, and migration behavior. Generic labels
such as `other`, `miscellaneous`, or `custom` MUST NOT be registered as
extension routes.

## 3. Terminology

The terms `rkaf:Artifact`, `rkaf:SourceFragment`, `rkaf:EvidenceBinding`,
`rkaf:RelationshipAssertion`, `rkaf:ValueAssertion`,
`rkaf:ConceptAssignment`, `rkaf:ExtractionActivity`, `rkaf:AILineage`,
`rkaf:ConfidenceRecord`, `rkaf:Attestation`, `rkaf:LocalAdoption`,
`rkaf:Warrant`, `rkaf:Authority`, `rkaf:LifecycleEvent`,
`rkaf:AccessScope`, `rkaf:RetentionPolicy`, `rkaf:RegisteredConcept`,
`rkaf:LocalConcept`, `rkaf:ConceptMapping`, and
`rkaf:ReferenceResourceRelease` have exactly the meanings defined by the
pinned Rulespec release. REF does not define aliases for them.

REF defines the following operational terms.

**Baseline enumeration report**
: An immutable, content-digested REF operational record that deterministically
  enumerates and classifies every declared-portfolio table data row plus every
  source-located named-item, subtype-group, and role occurrence inside cells
  and outside tables. It is the auditable input to an inventory coverage
  manifest, not a replacement copy of the inventories.

**Capture**
: The exact bytes or canonical response obtained from a source during one
  retrieval activity.

**Concept proposal**
: A source-grounded proposal awaiting vocabulary governance. It is a workflow
  record, not an `rkaf:LocalConcept`, `rkaf:RegisteredConcept`, or permissible
  `rkaf:ConceptAssignment` value.

**Enrichment configuration**
: An immutable REF operational record that pins every behavior-changing input
  to one enrichment implementation, including its implementation and runtime,
  profiles and policies, reference-resource and mapping releases, imported and
  indexed vocabulary expressions, candidate channels, fusion and truncation,
  model and provider settings, prompt, schemas, budgets, and determinism
  declarations.

**Enrichment decision**
: A durable record of an attempted enrichment, including its target, profile,
  policy, candidates considered, outcome, and any abstention or failure reason.
  It records workflow state; any portable semantic result is a separate
  Rulespec record.

**Enrichment deployment decision**
: An append-only REF operational record that stages, selects, deselects, fails,
  or replaces an exact enrichment configuration and evaluation result for an
  environment. It does not duplicate Rulespec review or authorization.

**Enrichment evaluation result**
: An immutable REF operational record that evaluates one exact enrichment
  configuration against one exact sealed gold manifest and protocol. It records
  measures, uncertainty, gates, and a `pass`, `fail`, or `developmentOnly`
  verdict.

**Enrichment profile**
: An immutable, versioned REF policy that defines facet IRIs and their
  definitions, inclusion and exclusion cues, compatible REF resource routes,
  and compatible Rulespec assignment-role predicates.

**Deterministic payload**
: The canonical output content that a deterministic stage produces from fixed
  inputs and versions. It excludes declared run-instance provenance such as the
  new receipt identifier and execution time, while each run still preserves
  that provenance.

**Evidence address**
: An operational selector and rendition binding used to create or resolve an
  `rkaf:SourceFragment`. The address is not a second portable fragment type.

**Evidence-collection policy**
: A versioned rule that defines which sources, fragments, time range, retrieval
  methods, and materiality criteria a processor uses when collecting support,
  qualification, or contradiction for a candidate or assertion.

**Inventory coverage manifest**
: An immutable REF operational record that accounts for every coverage row,
  constituent row, and named portfolio item in the dated source and
  controlled-resource baseline through exhaustive routed components, while
  retaining definition rows in its pinned baseline-enumeration report and
  keeping route family, semantic route, acquisition mode, semantic/use mode,
  representability, adapter or import implementation, release inclusion, and
  rights/use authorization separate.

**Indexed vocabulary expression**
: An immutable REF operational record for one source-authored label, note,
  definition, notation, or other searchable expression as indexed. It binds the
  original Unicode literal and language or datatype to its exact reference
  resource, import, member, normalization policy, expression-corpus snapshot,
  and indexed text without making the literal a concept identifier.

**External reference**
: An operational `externalReference` record-kind value for a pointer to a
  source resource, semantic resource, observation, model result, or identifier
  maintained outside the captured source corpus. It carries
  references to applicable Rulespec authority, access, and provenance records
  and does not copy the external object into the source corpus.

**Open-label role**
: An REF workflow designation for a grounded phrase that is published as an
  `rkaf:ValueAssertion` under the predicate pinned by the application profile.
  REF does not define an `OpenLabel` class.

**Output profile**
: An immutable, versioned policy whose complete permission rows bind a facet
  and assignment role to one reference-resource release and import snapshot,
  one directed mapping path input, or one open-label mode. Candidate use and
  accepted-output use are separate permissions on each row. The profile also
  identifies its enrichment profile, acceptance policies, publication views,
  and other output choices.

**Participation record**
: The REF `participation` record-kind route for a public comment, testimony,
  petition signature, or similar submission. It requires a separate privacy
  profile and is not a portable semantic class.

**Policy thread**
: A versioned, scoped view that groups records concerning an evolving
  real-world matter. Durable membership is an
  `rkaf:RelationshipAssertion`.

**Publication release manifest**
: An immutable REF `PublicationReleaseManifest` that identifies one published
  output set, its operational profiles and receipts, and its exact Rulespec and
  inventory-coverage pins. It is distinct from a Rulespec
  `rkaf:ReferenceResourceRelease`.

**Query-time association**
: A transient relevance, similarity, co-occurrence, ranking, or clustering
  result produced for a request. It is not a durable assertion.

**Registry import snapshot**
: An immutable REF operational record that connects one controlled-resource
  import to its `Capture` or explicit external reference, transformation,
  exclusions, validation, rights assessment, and applicable Rulespec release
  and distribution artifacts. It does not own retrieved bytes or repeat any
  capture, release, or artifact identity or digest.

**Registry import coverage report**
: An immutable REF operational record that accounts, by semantic feature, for
  what a controlled-resource distribution contained and what the import parser
  and index preserved, explicitly excluded, or failed to process.

**Registry reconciliation report**
: An immutable REF operational record that describes conflicting official
  controlled-resource inputs, their exact differences, applicable mappings and
  precedence, unresolved items, attestations, and the decision whether one
  input or a newly published reconciled release may be used.

**Rendition**
: The REF application role played by one `rkaf:Artifact` that represents a
  concrete immutable form of a source-resource version, such as XML, HTML,
  PDF, image, Office file, or extracted text. `Rendition` is not an REF class
  or second durable record.

**Rendition processing record**
: An REF operational record about parsing, extraction, optical character
  recognition, or quality for one rendition-role `rkaf:Artifact`. It references
  that artifact and does not repeat its identity or content digest.

**Rights assessment**
: An append-only operational assessment of observed source or registry terms
  for specified uses. Its evidence, review, authorization, access, and
  retention are represented using Rulespec and the external rights vocabulary
  selected by the binding profile.

**Semantic reference candidate**
: A workflow candidate for a grounded definition, requirement, obligation,
  exception, threshold, regulated population, program, mechanism, outcome,
  dataset, standard, policy problem, or other referable resource. Acceptance
  creates an externally typed resource plus Rulespec assertions; it does not
  create a generic REF semantic-object class.

**Semantic digest**
: A digest computed over a canonical deterministic payload under the declared
  serialization profile, excluding only that profile's run-instance
  provenance fields.

**Sealed gold manifest**
: An immutable, independently adjudicated REF operational record that fixes an
  evaluation generation's corpus membership, vocabulary and mapping universe,
  per-facet and role expectations, adequacy grades, forbidden results,
  partition proof, reviewers, and digest before evaluated output exists.

**Source-record revision**
: One decoded state of a source-native API or feed record. A changed record does
  not necessarily create a new source-resource version.

**Source-precedence policy**
: A versioned operational policy that selects among source observations for a
  named jurisdiction, record kind, field, predicate, and time range. Rulespec
  represents the source's warrant or authority and any approval of the policy.

**Source-field locator**
: A source-native field path and value digest used to create a Rulespec
  `SourceFragment` when support comes from structured data rather than prose.

**Source resource**
: The REF operational identity for a bounded source-issued communicative work,
  such as a rule, notice, report, filing, opinion, guidance document, or legal
  provision. It is not an `rkaf:Artifact`.

**Source-resource version**
: One publisher-recognized edition, revision, correction, or point-in-time
  state of a source resource. It groups one or more renditions and is not an
  `rkaf:Artifact`.

## 4. Rulespec dependency and conceptual model

### 4.1 Four layers

REF separates four layers:

```text
Layer 4  REF application products
         search, timelines, similarity, policy threads, release views

Layer 3  Rulespec semantic records
         assertions, assignments, evidence, attestations, authority, concepts

Layer 2  REF processing records
         source revisions, version resolution, candidates, decisions, receipts

Layer 1  Source evidence
         captures, source-native records, source-resource versions, renditions
```

Each higher layer depends on lower-layer evidence. No higher layer may rewrite
the source evidence that supports it. Layer 3 is not an REF-owned semantic
layer; it is a Rulespec-conforming output of REF processing.

### 4.2 One owner for each reusable semantic record

REF owns operational facts about acquisition, processing, evaluation, and
publication. Rulespec owns portable meaning and trust.

| Concern | Canonical owner |
| --- | --- |
| Capture, source-record revision, completeness, source-resource and version resolution | REF |
| Rendition processing state, selector resolution, run receipt, candidate and adjudication workflow | REF |
| Baseline enumeration, inventory coverage, source/reference-resource onboarding, and release-inclusion status | REF |
| Registry import snapshot and coverage report, reconciliation, deployment selection, rollback, indexed vocabulary expressions, and expression corpus | REF |
| Physical lexical, sparse, dense, hybrid, or approximate-nearest-neighbor lookup index and its immutable manifest | Lookup consumer |
| Enrichment and output profiles, sealed gold, exact configuration, evaluation result, deployment selection, and publication packaging | REF |
| Search, query-time similarity, candidate retrieval, and ranking | Lookup consumer |
| Policy-thread view and product explanation | REF |
| Immutable evidence artifact | Rulespec `rkaf:Artifact` |
| Addressable source region | Rulespec `rkaf:SourceFragment` |
| Proposition or relationship | Rulespec `rkaf:ValueAssertion` or `rkaf:RelationshipAssertion` |
| Concept assignment | Rulespec `rkaf:ConceptAssignment` |
| Evidence binding, extraction provenance, model lineage, confidence | Rulespec |
| Review, approval, dispute, and rejection | Rulespec `rkaf:Attestation` |
| Product authorization | Rulespec `rkaf:LocalAdoption` and `rkaf:usageEligibility` |
| Warrant, legal or source authority, lifecycle, access, and retention | Rulespec |
| Concepts, concept schemes, mappings, and concept resolution | Rulespec and SKOS as incorporated by Rulespec |

**REF-BIND-005:** A producer MUST NOT serialize an REF-owned substitute for a
Rulespec-owned concern in this table.

**REF-BIND-006:** An REF workflow MAY retain internal candidate data in a
provider-neutral operational record. If it exchanges that candidate as a
portable semantic record, it MUST use the applicable Rulespec type and
eligibility state.

**REF-BIND-007:** A review interface MUST write `rkaf:Attestation` records.
Product approval that authorizes use MUST additionally use
`rkaf:LocalAdoption`. REF MUST NOT store a mutable `reviewStatus`,
`authorityScope`, or equivalent field on a semantic record.

**REF-BIND-008:** Assertion construction origin, evidence, confidence, AI
lineage, epistemic basis, authority, lifecycle, access, retention, and use
eligibility MUST be represented only by the applicable Rulespec records and
properties. `rkaf:assertionOrigin` and `rkaf:epistemicBasis` MUST remain
independent.

### 4.3 Normative Rulespec profile

The [RefSpec Rulespec Application Profile](../profiles/rulespec-application-profile.md)
is a normative dependency of this specification. It defines the concrete
projection from REF-owned records to Rulespec without restating Rulespec
definitions.

**REF-BIND-009:** Every REF `PublicationReleaseManifest` MUST pin:

- the REF version and operational serialization profile;
- the Rulespec semantic version;
- the immutable Rulespec release or Git commit identifier;
- the digest algorithm and digest of the exact Rulespec constraint bundle;
- every adopted Rulespec profile and claimed conformance level;
- the Rulespec validator and conformance-suite versions; and
- the machine-readable Rulespec validation result.

**REF-BIND-010:** A producer MUST validate Rulespec records with the pinned
Rulespec validator. An REF validator MAY invoke and report that validator; it
MUST NOT reimplement the Rulespec constraints as REF schemas.

**REF-BIND-011:** The rendition role MUST be played directly by one
`rkaf:Artifact`. REF MUST NOT create a parallel rendition object.
`SourceResource`, `SourceResourceVersion`, and
`RenditionProcessingRecord` remain REF operational records and MUST NOT also
be typed as `rkaf:Artifact`.

**REF-BIND-012:** A successfully published evidence address MUST create or
resolve one `rkaf:SourceFragment` whose `oa:hasSource` names the exact
rendition-role `rkaf:Artifact` and whose source and fragment digests satisfy the
pinned Rulespec profile. REF MUST NOT publish an `EvidenceFragment` class.

**REF-BIND-013:** An accepted durable relationship MUST be an
`rkaf:RelationshipAssertion`; an accepted literal proposition MUST be an
`rkaf:ValueAssertion`; and an accepted controlled-concept assignment MUST be
an `rkaf:ConceptAssignment`. Their review, adoption, evidence, lineage,
confidence, authority, and lifecycle MUST remain separate Rulespec records.

**REF-BIND-014:** REF processing and release records MAY point to Rulespec
records, and Rulespec provenance MAY point to REF run records. Neither side
MUST copy the other's canonical fields.

### 4.4 Upstream-first rule

The passing local development baseline for this draft is Rulespec
`0.2.0-pre.9`. The tested contract revision is
`0eb94257b70783688b55220e7a84dcc61bbd7507`; the later evidence revision is
`2c66a85daab30a4869db08d21cea13cfc865b3a0`; and the constraint digest is
`sha256:8feadf8f4037a60a18667c6f7ee920ff1285ccb05a72fe5352b6cd82b38a252c`.
The application profile and its machine-readable dependency manifest record
the authoritative sources, conformance corpus, validator, generated
artifacts, availability state, and pin-update gate. The candidate remains
local and unpublished, so an implementation MUST mark production conformance
pending.

**REF-BIND-015:** When REF needs reusable semantics that the pinned Rulespec
release cannot express, the project MUST add or clarify them in Rulespec or an
adopted external standard. It MUST NOT mint a competing REF primitive.

**REF-BIND-016:** Until an upstream requirement has landed and the binding
profile has a passing fixture, an REF `PublicationReleaseManifest` MUST retain
the fact as operational data, mark the semantic projection unsupported, and
exclude it from any conformance or product claim that depends on the missing
meaning.

**REF-BIND-017:** A Rulespec dependency pin MUST distinguish the revision whose
contract and runtime passed the recorded gate from any later revision that
changes only certification or evidence. It MUST identify the constraint
digest, conformance-corpus digest, validator identity, adopted profiles,
generated-artifact verification mode, and release availability. A Git
revision and constraint digest alone MUST NOT support a production conformance
claim.

**REF-BIND-018:** The combined REF and Rulespec release-graph gate MUST issue a
`ReleaseGraphValidationReceipt` only after the REF binding, exact pinned
Rulespec structural validator, pinned Rulespec L4 runtime, and cross-boundary
checks all pass in that execution. The receipt MUST bind the dependency
manifest, exact Rulespec graph, every validated REF record digest, structural
validator, L4 runtime, gate implementation, complete Rulespec identifier
coverage, explicit cross-reference digest, applicable authorization
evaluations, validation time, and separate pass verdicts. A caller-authored or
self-asserted receipt MUST NOT substitute for executing the gate.

**REF-BIND-019:** The combined gate MUST derive an authorization evaluation
for every selected `RegistryDeploymentDecision` or
`EnrichmentDeploymentDecision` and every resolved
`RegistryReconciliationReport`. For a deployment, the gate MUST use the
environment identifier as the evaluation scope and `effectiveAt` as the
evaluation time. For a resolved reconciliation, it MUST use the precedence
policy identifier as the scope and `recordedAt` as the time. The exact
Rulespec graph MUST contain one assertion jointly targeted by the record's
named attestations and local adoptions. A resolved reconciliation's assertion
MUST also name every declared Rulespec authority. Every named attestation MUST
approve that assertion and be effective at the evaluation time. Every named
local adoption MUST be active, target that assertion, use the derived scope,
derive from one of the named attestations, and grant at least
`rkaf:localOperationalUse`.

The gate MUST construct the `rkaf:UsageEligibilityReducer`
`rkaf:BehaviorTestCase`; its `rkaf:input` MUST be the exact release graph. The
gate, not the caller, supplies the permitted expected outputs and accepts only
an L4 result at or above `rkaf:localOperationalUse`. The receipt MUST bind the
governance-record digest, behavior-test digest, input-graph digest, subject assertion,
scope, time, required minimum, verified output and digest, exact L4 runtime,
and result. A caller-provided behavior test, expected output, validation
receipt, or `effective` Boolean has no authorization effect. The governance
record does not reference its receipt because that would create a digest
cycle; the gate-issued receipt binds the already sealed record.

## 5. Operational information model

### 5.1 Common record fields

**REF-CORE-008:** Every durable REF-owned operational record MUST contain:

| Field | Meaning |
| --- | --- |
| `id` | Stable identifier within a declared namespace |
| `type` | REF type or documented extension type |
| `recordedAt` | Time the REF record was first recorded |
| `recordedBy` | Agent or activity responsible for the record |
| `schemaVersion` | Version of the validating schema or profile |
| `operationalState` | Profile-defined processing or release state |

**REF-CORE-005:** Durable identifiers MUST NOT be reused for a different
record.

**REF-CORE-006:** A correction MUST create a new decision, version, or
superseding operational record. It MUST NOT silently replace historical state.

**REF-CORE-001:** REF operational state MUST describe workflow or publication
state only. It MUST NOT encode Rulespec assertion origin, attestation,
consumer lifecycle, authority, or use eligibility.

**REF-CORE-002:** An operational transition that affects a portable semantic
record MUST append the applicable Rulespec `Attestation`, `LocalAdoption`, or
`LifecycleEvent`; changing an REF workflow record is not a substitute.

**REF-CORE-003:** REF schemas MUST reference, not copy, the identifiers of
Rulespec semantic records used as inputs or outputs.

**REF-CORE-004:** REF implementation metadata MAY include provider-specific
details in access-controlled receipts. Rulespec records MUST remain
provider-neutral and use the pinned Rulespec provenance types.

**REF-CORE-007:** Processing status, publication status, registry deployment selection,
query-time persistence, and Rulespec consumer disposition MUST remain separate
dimensions.

### 5.2 Capture

A `Capture` records an acquisition attempt and its result.

Required fields are:

- source identifier;
- source locator, request method, and request parameters safe to retain;
- retrieval start and end time;
- response status;
- representation-relevant request and response headers, including content
  negotiation, ETag, and last-modified values when supplied;
- media type, when known;
- byte digest and digest algorithm, when bytes were obtained;
- byte length;
- storage reference or access-controlled inline content;
- acquisition activity and run receipt; and
- references to applicable Rulespec access and retention records and the
  external rights expression selected by the binding profile.

**REF-CAP-001:** A core producer MUST retain the exact obtained bytes or a
canonical response sufficient for byte-identical replay.

**REF-CAP-002:** A failed or partial acquisition MUST produce an explicit
failure or partial status. Empty content MUST NOT represent success.

**REF-CAP-003:** A capture digest MUST support fixity and duplicate detection.
It MUST NOT establish artifact identity by itself.

**REF-CAP-004:** A source connector MUST record pagination, cursor, window,
attachment, retry, exclusion, and completeness information applicable to the
source.

**REF-CAP-005:** A producer MUST preserve the obtained payload bytes before
decoding or normalization. When transport framing cannot be retained, the
capture MUST state that limit and preserve the exact application payload plus
the metadata needed to interpret it.

### 5.3 Source-record revision

A `SourceRecordRevision` contains one decoded source-native record and points to
the capture from which it came.

**REF-SRC-001:** A producer MUST preserve the source namespace, native
identifier, raw type, raw status, raw field names or a lossless raw payload,
and capture reference.

**REF-SRC-002:** Normalized values MUST appear beside source-native values and
MUST identify the mapping version.

**REF-SRC-003:** Unknown source values MUST remain unknown or enter an explicit
mapping queue. A producer MUST NOT coerce them to the nearest known value.

**REF-SRC-004:** A changed source-record revision MUST NOT automatically create
a new source-resource version.

**REF-SRC-005:** A source-precedence policy MUST govern conflicts among official
sources, mirrors, aggregators, and external indexes. A lower-authority record
MUST NOT silently overwrite a higher-authority source or erase the conflict.

**REF-SRC-006:** A `SourcePrecedencePolicy` MUST identify the source,
jurisdiction, record kinds, fields or predicates, precedence, effective
interval, rule, and version. The source's warrant or authority and the policy's
review and authorization for use MUST use Rulespec records.

**REF-SRC-007:** Each accepted source-aligned Rulespec assertion MUST link,
through the binding profile, to the applicable source-precedence policy or
state that no precedence policy exists.

**REF-SRC-008:** Selecting one of two conflicting Rulespec assertions for a current view
MUST preserve both Rulespec assertions, append the appropriate
`rkaf:Attestation` and, when authorized for product use,
`rkaf:LocalAdoption`, and identify the source-precedence policy used. The
losing assertion MUST remain available in history.

### 5.4 Source resource, source-resource version, and rendition

A `SourceResource` represents the operational source identity. A
`SourceResourceVersion` represents a source-issued state. One or more
`rkaf:Artifact` records play the rendition role for that version. REF does not
create a separate `Rendition` record.

**REF-ART-001:** A source resource MUST retain its source namespace and native
identifier. Cross-source identity MUST be represented as an
`rkaf:RelationshipAssertion`, not an overwrite.

**REF-ART-002:** A source-issued correction, edition, or point-in-time legal
state MUST remain a distinct source-resource version when the source treats it as
distinct.

**REF-ART-003:** XML, HTML, PDF, image, and extracted-text forms of one
source-resource version MUST be distinct `rkaf:Artifact` records in the
rendition role, not separate source-resource versions or parallel REF
rendition objects.

**REF-ART-004:** Each rendition-role artifact MUST record its immutable
identity, media type, digest, format relations, and applicable access and
retention references through Rulespec. REF MAY attach a
`RenditionProcessingRecord` containing source locator, byte length, extraction
state, parser version, and quality state; that record MUST reference the
artifact and MUST NOT copy its semantic identity or digest.

Core extraction states are:

- `fullNativeText`;
- `fullExtractedText`;
- `ocrText`;
- `abstractOnly`;
- `metadataOnly`;
- `unsupportedFormat`;
- `retrievalFailure`;
- `extractionFailure`; and
- `accessRestricted`.

**REF-ART-005:** A producer MUST expose extraction state through the
rendition-processing record. It MUST NOT make a metadata-only record appear
equivalent to full source text.

### 5.5 Evidence addressing and selector resolution

An `EvidenceAddress` is a transient REF operational input to Rulespec fragment
publication. A durable `SelectorResolution` records whether that address
resolved against one rendition-role `rkaf:Artifact` and whether a conforming
`rkaf:SourceFragment` was created or found.

The operational address and resolution record include:

- the rendition-role `rkaf:Artifact` identifier;
- selector type and selector value;
- extraction method and version;
- text or value digest;
- quoted text or source value when permitted; and
- resolution and quality status; and
- the resulting `rkaf:SourceFragment` identifier when successful.

The selector, quote, and digest values in an attempted address are processing
inputs, not a second portable source-fragment record.

**REF-EVID-005:** Selectors MAY use:

- a structured field path;
- source-native element or provision identifier;
- character offsets in a named text rendition;
- page and bounding region;
- table, row, column, and cell coordinates;
- media time range; or
- a documented compound selector.

**REF-EVID-001:** An evidence address MUST bind to one rendition-role
`rkaf:Artifact` and the selector resolution MUST verify that artifact's
Rulespec content digest.

**REF-EVID-002:** An extracted-text offset MUST NOT be presented as a source
PDF, image, HTML, or XML offset unless a verified mapping connects them.

**REF-EVID-003:** If an address no longer resolves, the producer MUST append an
unresolved or superseded selector-resolution record. It MUST NOT silently
retarget the address or its prior `rkaf:SourceFragment`.

**REF-EVID-004:** A compound package MUST remain intact unless the source
provides reliable component boundaries or a reviewed rule documents the split.

**REF-EVID-006:** On successful resolution, every overlapping selector,
coordinate, quote, source-artifact digest, and fragment digest in the REF
attempt MUST match the canonical `rkaf:SourceFragment`. After publication, the
Rulespec fragment is the only portable evidence address.

### 5.6 Source-processing record kinds

REF uses `recordKind` as an operational routing discriminator. These values are
not RDF classes and MUST NOT appear as portable semantic types:

| `recordKind` value | Examples | Processing default |
| --- | --- | --- |
| `container` | Docket, proceeding, case, hearing | No inherited subjects |
| `participation` | Comment, testimony, petition signature | Separate privacy profile |
| `entityRecord` | Agency, person, facility, program, chemical record | Entity-resolution route |
| `observationRecord` | Burden estimate, amount, status, measurement | Observation route |
| `eventRecord` | Publication, meeting, vote, decision, withdrawal | Event route |
| `externalReference` | External index, simulation, model result, identifier spine | Join or pointer, not captured source truth |

Portable objects use the applicable Rulespec profile, such as its US
rulemaking proceeding types, or an adopted external ontology.

An extension profile may add an absolute-IRI `recordKind` only when the core
processing paths would lose a material operational distinction. It must map
that value to the same common REF record requirements and to independently
selected portable semantics.

Inventory coverage routes map to processing as follows:

| Coverage route | REF processing route |
| --- | --- |
| `document` | `SourceResource` and `SourceResourceVersion`, with rendition-role artifacts |
| `participation` | `participation` |
| `container` | `container` |
| `entity` | `entityRecord` |
| `observation` | `observationRecord` |
| `event` | `eventRecord` |

Source acquisition modes map separately:

| Acquisition mode | REF processing |
| --- | --- |
| `captured` | `Capture` and the applicable decoded processing route |
| `externalJoin` | `externalReference`; a later retrieval requires a separate `Capture` |

**REF-TYPE-001:** A producer MUST determine the operational `recordKind`
before enrichment and MUST select a Rulespec or external semantic type
independently when it publishes a portable object.

**REF-TYPE-002:** A record MUST NOT become a source resource or Rulespec
artifact merely because it has a title, description, or text field.

**REF-TYPE-003:** A Rulespec concept assignment on one rendition artifact MUST
NOT propagate to its container, participants, entities, observations, later
source-resource versions, or related renditions without independent evidence
and an explicit derivation rule.

**REF-TYPE-004:** An `externalReference` operational record MUST identify the external system,
native identifier, version or observation time, authority, access and rights
state, and provenance. It MUST NOT be presented as a captured source resource
or imported result unless a separate capture records that material.

**REF-TYPE-005:** An implemented adapter MUST follow the route family,
semantic route, and acquisition mode declared by its inventory-coverage
component. A changed route family, route, or acquisition mode MUST create a
new coverage-manifest version and pass typing, rights, and regression review
before production use.

**REF-TYPE-006:** An extension route or `recordKind` MUST NOT bypass capture,
identity, version, evidence, provenance, rights, failure, publication, or
evaluation requirements that apply to its actual behavior. Its extension
profile MUST declare the applicable core requirements and any additional
requirements, and its validator MUST reject an instance whose declared
portable type or processing behavior conflicts with that profile.

### 5.7 Semantic-reference candidates

A `SemanticReferenceCandidate` lets a relationship workflow refer to a
possible definition, threshold, population, dataset, or policy mechanism
before the project decides how to type and publish that resource.

**REF-SEM-001:** A candidate MUST identify its proposed external type, wording,
originating source-resource version, evidence addresses, and generating
activity.

**REF-SEM-002:** A generated candidate MUST retain the generated wording and
the exact input evidence addresses.

**REF-SEM-003:** Two candidates MUST NOT be merged solely because their labels
or embeddings are similar.

**REF-SEM-004:** Acceptance MUST create an externally typed resource and the
applicable Rulespec assertions. REF MUST NOT publish a generic
`SemanticObject` class or duplicate a proposition in both an REF record and a
Rulespec assertion.

### 5.8 Rulespec semantic records

REF produces portable propositions only through the pinned Rulespec profile.

**REF-SEMOUT-001:** A durable derived semantic result MUST be the applicable
Rulespec assertion or assignment and MUST identify exact
`rkaf:SourceFragment` evidence or its Rulespec derivation inputs and
provenance.

**REF-SEMOUT-002:** An REF `EvidenceCollectionPolicy` MUST define the searched
evidence universe and materiality rules for an adjudication. The operational
decision MUST preserve every encountered conflicting or qualifying item that
meets the policy and link the resulting Rulespec records.

**REF-SEMOUT-003:** A numeric or categorical confidence attached to a semantic
result MUST use `rkaf:ConfidenceRecord`.

**REF-SEMOUT-004:** A source-aligned semantic result MUST identify the capture and
exact `rkaf:SourceFragment` in which the source expresses the proposition. It
MUST use Rulespec `rkaf:epistemicBasis: rkaf:sourceExplicit` independently of
the record's `rkaf:assertionOrigin`.

## 6. Identity, versions, and time

### 6.1 Identity

**REF-ID-001:** Source identity MUST begin with the source namespace and native
identifier, plus source-defined version information where required.

**REF-ID-002:** Shared text, title, RIN, docket number, citation, URL, or hash
MAY generate an identity candidate. None proves identity without the
applicable source rule or reviewed evidence.

**REF-ID-003:** A probabilistic identity match MUST remain a reversible
Rulespec relationship assertion or an operational candidate. It MUST NOT
replace either source record.

**REF-ID-004:** A system MAY publish a preferred display record. It MUST keep
all source identities, Rulespec assertions, attestations, and local adoptions
used to select that display record.

### 6.2 Version levels

REF distinguishes these version levels:

1. a new `Capture`;
2. a new `SourceRecordRevision`; and
3. a new `SourceResourceVersion`; and
4. a new immutable `rkaf:Artifact` in the rendition role.

**REF-VER-001:** Producers MUST represent these version levels separately.

**REF-VER-002:** A metadata refresh MUST NOT become a new legal or documentary
version unless source semantics support that conclusion.

**REF-VER-003:** Version, correction, replacement, withdrawal, amendment, and
supersession predicates MUST remain distinct.

### 6.3 Time

REF uses separate time dimensions:

| Time | Question answered | Canonical owner |
| --- | --- | --- |
| Publication or issuance time | When did the source issue this material? | Source-native metadata and adopted Rulespec domain profile |
| Valid time | When was an assertion or state valid in the represented world? | Rulespec applicability or adopted domain profile |
| Effective time | When did a legal or operational effect apply? | Rulespec effective period or adopted domain profile |
| Assertion or observation time | When did the source or asserting agent observe or assert the state? | Rulespec and PROV-O |
| Retrieval time | When did the framework obtain the source? | REF `Capture` |
| REF recorded time | When did the framework record the operational object? | REF operational record |

**REF-TIME-001:** A producer MUST NOT collapse these times into one generic
date when the source supplies more than one meaning, and REF MUST NOT duplicate
a Rulespec-owned time as independently authoritative operational state.

**REF-TIME-002:** Current views MUST be derived from retained history.

**REF-TIME-003:** An as-of query MUST declare whether it uses valid time,
effective time, observation time, retrieval time, framework-recorded time,
release-publication time, or a declared combination. The response MUST
distinguish "what was legally or operationally effective" from "what this
release knew or displayed."

**REF-TIME-004:** Deletion, disappearance, and access loss MUST create explicit
operational events or tombstones and the applicable Rulespec lifecycle and
access records. They MUST NOT erase earlier captures that retention and rights
policies permit the system to keep.

## 7. Evidence addressing and operational provenance

### 7.1 Evidence roles

Rulespec `rkaf:EvidenceBinding` owns both the evidence role and how that
evidence bears on an assertion. REF adjudication records may propose the
Rulespec evidentiary functions:

- `supports`;
- `qualifies`;
- `contradicts`;
- `definesScope`; and
- `providesContext`.

The accepted semantic result MUST publish those functions and the applicable
Rulespec evidence-role value on `rkaf:EvidenceBinding`; REF MUST NOT maintain a
parallel portable value set.

**REF-PROV-001:** Every accepted machine-generated assignment or durable
inferred relationship MUST cite at least one `rkaf:SourceFragment` or a
Rulespec-supported no-evidence reason.

**REF-PROV-002:** An adjudication record MUST retain qualifying or
contradicting evidence that met its declared evidence-collection policy at
decision time and link the resulting Rulespec evidence bindings.

**REF-PROV-003:** A producer MUST distinguish absent evidence from evidence of
absence.

### 7.2 Activities, agents, and receipts

Rulespec and PROV-O own portable activity and agent semantics. REF does not
define `Activity` or `Agent`. An REF run has an operational identifier and
links the applicable `prov:Activity`, `prov:Agent`, and
`rkaf:ExtractionActivity` records.

A `RunReceipt` contains:

- input captures, REF snapshots, and Rulespec release references;
- source and coverage window;
- references to the canonical Rulespec extraction activities, AI lineage,
  agents, reference-resource releases, and semantic outputs;
- provider-native request or response identifiers, retry history, cost,
  latency, and other operational details that Rulespec intentionally omits;
- environment or dependency lock reference;
- REF outputs and their digests;
- counts, exclusions, failures, and quarantined items;
- start and end times;
- reproducibility classification.

If a receipt snapshots a Rulespec value for audit convenience, that copy is
non-authoritative and MUST match the referenced Rulespec record.

**REF-PROV-004:** Every REF-derived durable operational record MUST identify
the activity and agent that produced it. Every portable semantic result MUST
use the applicable Rulespec extraction provenance and, when applicable,
`rkaf:AILineage`.

**REF-PROV-005:** A receipt MUST identify every nondeterministic stage.

**REF-PROV-006:** A receipt MUST NOT contain credentials, secrets, or protected
content unless it receives controls at least as strict as the source.

**REF-PROV-007:** A system MUST retain enough information to reproduce
deterministic stages from fixed inputs or to explain why replay is impossible.

### 7.3 Decision history

**REF-PROV-008:** Source-aligned extraction, deterministic processing,
model processing, human authorship, and review MUST remain distinguishable
through REF run records and the applicable Rulespec origin, extraction,
lineage, and attestation records.

**REF-PROV-009:** Rejection, dispute, correction, retraction, and supersession
of a semantic record MUST append the applicable Rulespec records.

**REF-PROV-010:** A consumer MUST be able to trace a current accepted semantic
result to its Rulespec assertion or assignment, source fragments, generating
activity, attestations, local adoption, lifecycle events, and earlier states.

## 8. Processing model

### 8.1 Required stage boundaries

**REF-PIPE-010:** A core producer MUST implement the following logical stages.
An implementation MAY combine physical services, but it MUST preserve each
stage's observable input and output.

```text
source registration
  → capture
  → decode and record typing
  → source-resource/version/rendition resolution
  → source-aligned parsing and Rulespec source fragments
  → deterministic identifiers, citations, and structure
  → optional semantic-reference and concept candidates
  → optional relation-specific adjudication
  → Rulespec validation
  → versioned REF publication
```

**REF-PIPE-001:** Each stage MUST append operational outputs or Rulespec
records. It MUST NOT overwrite source evidence or semantic history.

**REF-PIPE-002:** A failed stage MUST emit a typed failure, preserve usable
earlier outputs, and prevent incomplete results from appearing complete.

**REF-PIPE-003:** Deterministic stages MUST produce the same canonical payload,
stable payload identifier, and semantic digest for identical frozen inputs and
versions. Run receipts and run-instance records MAY differ in declared
provenance fields such as `recordedAt`, activity identifier, and execution time;
those fields MUST remain linked to the stable payload and MUST NOT enter its
semantic digest.

**REF-PIPE-004:** A nondeterministic stage MUST preserve its inputs, provider
and model identity, configuration, output, and execution time.

**REF-PIPE-005:** Materialization and publication MUST be separate decisions.
A completed processing run MUST NOT become a published release automatically.
Rulespec validation and required adoption MUST complete before semantic output
enters an accepted publication view.

### 8.2 Source registration

**REF-PIPE-011:** Before production acquisition, a source profile MUST define:

- responsible publisher and source authority;
- jurisdiction and coverage;
- access method and cadence;
- native identifiers and type values;
- source version, correction, deletion, and withdrawal semantics;
- pagination and completeness checks;
- body and attachment discovery;
- expected formats and parser policy;
- access, license, retention, and privacy rules; and
- source-specific validation fixtures.

**REF-PIPE-012:** Before its first production capture, a source profile MUST
have an immutable identifier, version, and digest; an approving decision and
agent represented through Rulespec attestation; and a `RightsAssessment` whose
adopted policy explicitly permits acquisition and storage for the declared
purpose.

**REF-PIPE-006:** A connector MUST fail visibly when schema drift, pagination,
access restrictions, or source limits prevent the declared coverage.

### 8.3 Publication

**REF-PIPE-007:** Publication MUST bind outputs to an immutable
`PublicationReleaseManifest` and run receipt. When semantic outputs are
included, the manifest MUST also carry the complete Rulespec pin and
conformance result required by `REF-BIND-009`.

**REF-PIPE-008:** Publication MUST be atomic or expose an explicit incomplete
release state that consumers cannot mistake for complete.

**REF-PIPE-009:** A publisher MUST support rollback to a previous release
without deleting the rejected release's history.

## 9. Semantic enrichment

### 9.1 Typed facets

REF separates semantic outputs by facet. The
[RefSpec Core Enrichment Profile](../profiles/enrichment-profile.md) supplies
the normative definition, inclusion and exclusion cues, compatible REF routes,
and compatible Rulespec assignment roles for each facet:

| Facet IRI | Short label | Examples |
| --- | --- | --- |
| `urn:ref:facet:general-subject` | General subject | Housing policy, air quality, workplace safety |
| `urn:ref:facet:specialist-subject` | Specialist subject | Clinical procedure, chemical process, aerospace technology |
| `urn:ref:facet:entity` | Entity | Organization, person, chemical, facility, program, place |
| `urn:ref:facet:legal-location` | Legal location | USC, Public Law, CFR, court citation |
| `urn:ref:facet:industry-classification` | Industry classification | NAICS industry |
| `urn:ref:facet:affected-population` | Affected population | Regulated facilities, benefit recipients |
| `urn:ref:facet:genre` | Genre | Rule, guidance, complaint, report |
| `urn:ref:facet:regulatory-action` | Regulatory action | Proposes, amends, withdraws, decides |
| `urn:ref:facet:administrative-process-stage` | Administrative process stage | Unified Agenda stage, OIRA review stage, comment period |
| `urn:ref:facet:code-list-value` | Code-list value | Source-native status or classification code |
| `urn:ref:facet:ontology-class` | Ontology class | Class membership in a named ontology |
| `urn:ref:facet:observation-measure` | Observation and measure | Amount, count, burden, modeled estimate |

**REF-ENR-001:** Subjects, entities, legal citations, industry
classifications, affected populations, genres, actions, process stages,
code-list values, ontology classes, and observations or measures MUST remain
distinct facets.

**REF-ENR-002:** A readable label on a code, identifier, schema element, or
ontology class MUST NOT make that value a subject concept.

**REF-ENR-003:** An enrichment profile MUST declare the facet IRIs, compatible
REF resource routes, and compatible Rulespec assignment roles it supports.
Exact concept schemes, entity registries, releases, imports, mappings, and
open-label modes belong in complete `OutputProfile` permission rows.

**REF-ENR-015:** An `EnrichmentProfile` MUST have a stable identifier,
immutable version, and content digest. For every facet it defines, it MUST
provide a stable absolute IRI, label, definition, inclusion and exclusion cues,
compatible REF resource routes, and compatible Rulespec assignment-role
predicate IRIs. A profile MUST NOT express facet separation as global OWL
disjointness. An implementation using the core profile MUST use the twelve
`urn:ref:facet:*` IRIs above exactly.

### 9.2 Open-set behavior

Valid enrichment results include:

- an accepted Rulespec concept assignment or entity assertion;
- an accepted grounded open-label value assertion;
- a review-required candidate;
- a local concept proposal awaiting governance;
- an abstention;
- a rejected candidate; or
- an unresolved conflict.

**REF-ENR-004:** A producer MUST support zero accepted assignments for a
rendition artifact or source fragment.

**REF-ENR-005:** A nearest or highest-scoring candidate MUST NOT be accepted
solely because it ranks first.

**REF-ENR-006:** A `ConceptProposal` MUST NOT be presented as an
`rkaf:LocalConcept`, `rkaf:RegisteredConcept`, accepted
`rkaf:ConceptAssignment`, or accepted open-label value assertion.

**REF-ENR-007:** An abstention MUST state one or more reasons:
`noCandidate`, `insufficientEvidence`, `belowPolicy`,
`conflictingEvidence`, `wrongFacet`, `outOfProfile`,
`licenseUnavailable`, `poorExtraction`, or `unsupportedRendition`.

**REF-ENR-008:** Every attempted combination of target, facet, and assignment
role MUST produce a durable `EnrichmentDecision`. The decision MUST record the
target, facet, assignment role, input snapshot, immutable output-profile
identifier, version, and digest, acceptance-policy release, candidate count,
outcome, result references, activity, and time.

Core decision outcomes are `accepted`, `reviewRequired`,
`localConceptProposed`, `abstained`, `failed`, and `cancelled`.

**REF-ENR-009:** A successful abstention, processing failure, cancelled run,
and unprocessed target MUST remain distinguishable. An empty assignment list
MUST NOT represent all four states.

**REF-ENR-010:** A `ConceptProposal` MUST have a stable operational identifier,
facet, wording, evidence addresses, generating activity, workflow state, and
supersession history. It MUST carry one explicit placement: `narrowerThan`,
`broaderThan`, or `relatedTo` a named Rulespec concept; located only in its
named facet; or unresolved with a reason. Wording or label similarity MUST NOT
establish identity or equivalence. Promotion MUST create a separate
`rkaf:LocalConcept` or `rkaf:RegisteredConcept`, the applicable
`rkaf:Attestation`, and explicit Rulespec provenance. REF MUST NOT copy
Rulespec concept lifecycle into the proposal record.

**REF-ENR-011:** An `OutputProfile` MUST have a stable identifier, immutable
version, and content digest. It MUST identify one immutable
`EnrichmentProfile`, its acceptance policies and publication views, and its
complete `releasePermissions`, `mappingPermissions`, and
`openLabelPermissions` rows.

**REF-ENR-016:** Every `OutputProfile` permission row MUST contain the following
fields. References MUST identify immutable records and exact versions or
digests where those record types require them.

| Row | Required fields |
| --- | --- |
| `releasePermissions` | `facet`, `assignmentRole`, `referenceResourceRelease`, `registryImportSnapshot`, `requiredImportFeatures`, `candidateUse`, and `acceptedOutputUse` |
| `mappingPermissions` | `facet`, `assignmentRole`, `mappingSnapshot`, `sourceRelease`, `targetRelease`, `relation`, `direction`, `candidateUse`, and `acceptedOutputUse` |
| `openLabelPermissions` | `facet`, `assignmentRole`, `mode`, `candidateUse`, and `acceptedOutputUse`; `defaultLanguage` is additionally required for `declaredDefaultLanguage` |

`mappingSnapshot` MUST identify a `RegistryImportSnapshot` whose controlled
resource route is `mappingSet`. `direction` MUST be `sourceToTarget` or
`targetToSource`; a profile authorizes both directions only by including two
rows. `mode` MUST be `explicitLanguage` or `declaredDefaultLanguage` as defined
by the selected enrichment profile. Both use fields are explicit booleans.
`requiredImportFeatures` MUST name every import-coverage feature needed for
candidate or accepted-output behavior under that release row; the matching
coverage report MUST derive its requirement flags from those rows.
For a mapping row, the matching mapping-set coverage report MUST mark
`mappings`, `identifiers`, and `membership` as required. The report's exact
`referenceResourceRelease` is the mapping release for the exact
`mappingSnapshot`; the configuration and sealed vocabulary universe MUST pin
that release and snapshot together.
Accepted-output permission on a mapping row authorizes that exact mapping
traversal to support an accepted target; it does not publish the mapping or
make either endpoint release generally output-eligible.

**REF-ENR-017:** Candidate and accepted-output authorization MUST be evaluated
against one complete permission row. A producer MUST NOT combine the facet or
role from one row with a release, snapshot, relation, direction, mode, or use
permission from another row. `acceptedOutputUse: true` requires
`candidateUse: true` in the same row. Candidate permission alone, including
permission for a diagnostic, decoy, or mapping-only resource, MUST NOT
authorize accepted output.

**REF-ENR-012:** An accepted open-label output MUST be an
`rkaf:ValueAssertion` whose predicate is `rkaf:openLabel`. The assertion MUST
carry `rkaf:openLabelFacet` and `rkaf:openLabelRole`, and its value MUST be a
BCP 47 language-tagged string. The Rulespec record MUST preserve its exact
wording and complete language tag, including any script subtag, as well as its
evidence and generating activity. Its linked REF
`EnrichmentDecision` MUST preserve the facet, stable local value identifier,
output profile, and workflow provenance. REF MAY retain detected language or
script as candidate-processing data, but that data MUST NOT be the only copy
of portable accepted meaning. When the permission mode is
`declaredDefaultLanguage`, the producer MUST materialize that declared
language tag into the final Rulespec value before validation. An untagged or
`@none` value is invalid; `und` is permitted only when the language is
genuinely unknown. The value assertion MUST NOT assert concept-scheme
membership.

**REF-ENR-018:** An open-label candidate or accepted output MUST match one
complete `openLabelPermissions` row for its facet, role, mode, and use. An
accepted assertion MUST also identify exact Rulespec evidence and provenance.
The facet and role on the Rulespec assertion, its REF
`EnrichmentDecision`, and the authorizing permission row MUST agree exactly.

**REF-ENR-013:** An `OutputProfile` is immutable. Any permission, acceptance
policy, or publication-view change MUST create a new profile version and
content digest. Operational selection for an environment MUST use an
`EnrichmentDeploymentDecision`; REF MUST NOT mutate the profile or use a
standalone output-profile state as deployment authority. Review and
authorization MUST remain linked Rulespec records.

**REF-ENR-014:** An `accepted` enrichment decision MUST reference one or more
resulting Rulespec assertion or assignment identifiers. A
`localConceptProposed` decision MUST reference one or more resulting
`ConceptProposal` identifiers. A
`reviewRequired` decision MUST reference its review candidates. An
`abstained`, `failed`, or `cancelled` decision MUST reference no accepted
assignment and MUST record its applicable reason.

### 9.3 Candidate generation

Candidate generation and acceptance are separate activities.

**REF-CAND-008:** A profile MAY use:

- exact aliases and source labels;
- lexical retrieval;
- dense retrieval;
- grounded open phrases;
- source-assigned concepts;
- specialist schemes;
- hierarchy or mapping neighbors; and
- source, agency, CFR, genre, or other metadata priors.

**REF-CAND-001:** An enrichment producer MUST preserve each candidate's
generating channel, rank, and indexed representation version. It MUST preserve
the raw score when the channel produces one and an explicit no-score state
otherwise. A registered candidate MUST identify its scheme and release; an
open-label candidate MUST identify its stable local namespace or generating
activity.

**REF-CAND-009:** Every source-authored vocabulary string used by a candidate
index MUST have an `IndexedVocabularyExpression` that identifies the exact
Rulespec reference-resource release, REF registry import snapshot,
distribution artifact, and member IRI; the absolute semantic property IRI
represented by the expression; exactly one exact source locator, either a
source property IRI or a source-native path; original Unicode literal; BCP 47
language tag, including its script subtag when supplied, or an absolute
datatype IRI when the source expression is typed, but never both or neither;
normalization-policy
identifier and digest; normalized indexed text and its digest; indexed
representation version; logical `expressionCorpusSnapshot`; generating
activity; and run receipt.
A candidate generated from the expression MUST reference that record.
Expressions with identical literals but different releases, schemes, members,
semantic properties, source locators, language tags, or datatypes MUST remain
distinct records. `semanticProperty` MUST identify the property whose meaning
the indexed expression preserves even when `sourcePath` records a
source-native location. `sourceProperty` and `sourcePath` identify where the
expression came from and MUST remain mutually exclusive.
Normalization MUST NOT create concept identity, discard the original
expression, or reduce text to ASCII as the only indexed representation.
`expressionCorpusSnapshot` identifies the REF-owned logical collection of
eligible expressions. It MUST NOT identify a physical lookup index.

**REF-CAND-002:** Candidate fusion and truncation MUST be deterministic for
fixed deterministic inputs and MUST be visible in the run receipt.

**REF-CAND-003:** Entity types and subjects MUST NOT compete in one
undifferentiated candidate ranking.

**REF-CAND-004:** Metadata conditioning MUST preserve a global candidate path
unless an evaluation has proved that a hard restriction preserves required
recall for the exact profile and release.

**REF-CAND-005:** A hierarchy prediction MUST NOT eliminate all descendants
without a measured recall-preserving fallback.

**REF-CAND-006:** A profile MUST treat shortlist size and channel quotas as
versioned policy, not framework constants.

**REF-CAND-007:** A generated phrase used for canonicalization MUST remain
available as evidence of what the generator proposed.

### 9.4 Acceptance policy

An `AcceptancePolicy` defines which candidates a producer may accept, which
require review, and which require abstention.

**REF-ACC-001:** Acceptance policy MUST be versioned independently of candidate
retrieval and adjudication models.

**REF-ACC-002:** Acceptance rules MUST be scoped by facet and output profile.
They SHOULD also account for source family, subtype, extraction quality, and
risk.

**REF-ACC-003:** A raw similarity score, reranker score, or model self-rating
MUST NOT be labeled a probability or calibrated confidence unless an identified
calibration method supports that interpretation.

**REF-ACC-004:** The acceptance policy MUST define which rejected and competing
candidates the decision record retains for explanation. The decision MUST
retain that set and the policy version.

**REF-ACC-005:** Machine agreement MUST NOT be represented as human review,
source assignment, or vocabulary promotion.

**REF-ACC-006:** A producer MUST NOT create new assignments to a deprecated
concept unless a declared historical profile permits them.

**REF-ACC-007:** Every accepted registered assignment MUST use a facet,
assignment-role predicate IRI, scheme or registry, Rulespec
reference-resource release, and any mapping-set `RegistryImportSnapshot`
selected together by one complete permission row in the output profile at the
decision time. The assignment-role predicate MUST be defined by the pinned
Rulespec profile; REF MUST NOT mint a parallel role value set. Every accepted
open-label assignment MUST use a facet, assignment-role predicate, language
mode, and any declared default language authorized together by one complete
permission row selected at that time. Mapping-only resources, unauthorized
releases, candidate-only rows, tuples assembled from separate rows, and
wrong-facet candidates MUST NOT enter the accepted view.

**REF-ACC-008:** A Rulespec concept assignment MUST use
`rkaf:assignedConceptRelease` to reference an
`rkaf:ReferenceResourceRelease` with a passing
`REF-Reference-Resource-Registry`
conformance manifest for the
applicable profile. The manifest's assessed resource identifier and version
MUST exactly match the referenced release, and its assessed content digest
MUST match that release's Rulespec `rkaf:referenceReleaseDigest`. The registry
MAY be operated by the enrichment producer or by an external conforming
registry. The referenced release MUST use `rkaf:completeMembership`; a partial
or non-enumerated release cannot prove that the assigned concept is a member.

### 9.5 Rulespec assignment publication

**REF-ASSIGN-004:** An accepted registered assignment MUST be an
`rkaf:ConceptAssignment`. An accepted open label MUST be an
`rkaf:ValueAssertion` under a predicate declared by the REF Rulespec
Application Profile. A concept assignment MUST target the exact member IRI in
the referenced `rkaf:ReferenceResourceRelease`, whose
`rkaf:membershipMode` MUST be `rkaf:completeMembership`. The REF
`EnrichmentDecision` MUST link the output to its output-profile version,
applicable registry import snapshots, acceptance-policy version,
candidate-generation activity, and run receipt; those workflow fields MUST NOT
be copied onto the Rulespec record.

**REF-ASSIGN-001:** Every accepted concept assignment's evidence MUST use
`rkaf:EvidenceBinding`. Each cited evidence reference MUST resolve to an
`rkaf:SourceFragment` bound to the exact rendition artifact and digest.

**REF-ASSIGN-002:** An assignment on one Rulespec artifact or source fragment
MUST NOT transfer to a related source resource, rendition, or later version
without independent evidence and a Rulespec-supported derivation.

**REF-ASSIGN-003:** A `ConceptProposal` MUST be represented by its enrichment
decision and governance workflow. It MUST NOT be used as the value of an
`rkaf:ConceptAssignment`.

### 9.6 Configuration, evaluation, and deployment

An enrichment run is reproducible only when its complete behavior is named as
one immutable configuration. Evaluation and deployment are separate records;
neither mutates the configuration.

**REF-ENR-019:** An `EnrichmentConfiguration` MUST identify:

- its implementation identifier, immutable revision, build, runtime, and
  dependency-lock digest;
- its `EnrichmentProfile`, `OutputProfile`, `AcceptancePolicy`, and applicable
  schema identifiers, versions, and digests;
- every Rulespec reference-resource release, REF registry import snapshot,
  mapping release, mapping-set import snapshot, and selected
  `RegistryDeploymentDecision` available to the run, plus the digest of the
  complete candidate target universe;
- every logical expression-corpus snapshot and digest, physical
  `lookupIndexManifest`, indexed representation version, and
  normalization-policy identifier and digest;
- every candidate channel and its retriever, query construction,
  ordering, fusion, deduplication, quota, truncation, and fallback policy;
- every model identifier and revision, provider and endpoint configuration
  that changes behavior, inference parameter, prompt or template identifier and
  digest, tool policy, and structured-output schema;
- every per-stage input, output, token, time, candidate, and cost budget;
- deterministic or nondeterministic status for each stage, including seeds and
  replay controls when applicable; and
- its canonical payload digest.

Changing a listed value or any other value that can change candidates,
decisions, accepted outputs, abstention, latency, or cost MUST create a new
configuration identifier and digest. Secrets MAY be represented by stable
secret-version references; their cleartext values MUST NOT enter a
configuration record.

Core `EnrichmentDeploymentDecision` states are `staged`, `selected`,
`deselected`, and `failed`.

**REF-ENR-020:** An `EnrichmentDeploymentDecision` MUST identify its target
environment; exact `EnrichmentConfiguration` identifier and digest; exact
`EnrichmentEvaluationResult` identifier and digest; exact `OutputProfile`
identifier, version, and digest; selection state; effective and recorded times;
reason; responsible activity; predecessor or superseding decision when
applicable; and the applicable Rulespec attestation and local-adoption
references. A selected decision becomes deployable only when a gate-issued
`ReleaseGraphValidationReceipt` binds its exact digest and the passing
authorization evaluation required by `REF-BIND-019`; caller-authored
validation objects and `effective` Booleans are non-authoritative. A selected
decision for production MUST reference an evaluation with verdict `pass`, and
the evaluation's configuration digest and the configuration's output-profile
digest MUST match the selected records exactly. Current selection MUST be
reduced from append-only deployment decisions. A failed or deselected decision
MUST NOT erase its configuration, evaluation, or predecessor.

## 10. Relationship discovery and publication

### 10.1 General model

REF separates operational candidates and query-time associations from accepted
durable semantic relationships. Only the latter are
`rkaf:RelationshipAssertion` records.

**REF-REL-015:** An accepted durable relationship MUST validate as an
`rkaf:RelationshipAssertion` under the pinned Rulespec release. Its evidence,
origin, extraction provenance, AI lineage, confidence, attestation, adoption,
authority, applicability, lifecycle, and access MUST use their canonical
Rulespec records. The REF candidate and adjudication decision MUST retain
method, snapshot, policy, outcome, and run-receipt details and link the
Rulespec result without copying those portable fields.

**REF-REL-001:** Every durable relationship MUST use a predicate from a
versioned predicate registry incorporated by the REF Rulespec Application
Profile or another adopted ontology.

**REF-REL-002:** A predicate definition MUST declare:

- subject and object types;
- direction;
- whether it is symmetric, asymmetric, transitive, or non-transitive;
- temporal meaning;
- material inverse, if any.

Those semantic traits MUST be defined by Rulespec or the adopted external
ontology. The REF publication policy for that predicate MUST separately
declare:

- evidence requirements;
- allowed Rulespec origins and required attestations or adoption;
- default persistence class;
- risk or review policy.

**REF-REL-003:** An implementation MUST NOT apply inverse, symmetric, or
transitive closure unless the predicate definition permits it.

**REF-REL-004:** A computed path or closure MUST remain query-time output unless
a new durable assertion independently meets its predicate's requirements.

### 10.2 Evidence, inference, and editorial families

Different processing routes produce different Rulespec origin, provenance,
attestation, and adoption records:

| Processing route | Portable representation |
| --- | --- |
| A source states a relation | Rulespec assertion plus source claimant, source fragment, evidence binding, and extraction provenance |
| A deterministic parser or join derives it | Rulespec deterministic origin plus extraction provenance and derivation inputs |
| A model proposes it | Rulespec AI-touched origin plus extraction activity and AI lineage |
| An analyst authors it | Rulespec human origin plus attestation |
| A team authorizes product use | Separate Rulespec local adoption |

**REF-REL-005:** A consumer MUST expose the Rulespec construction origin,
epistemic basis, evidence, attestations, and local adoption applicable to a
durable relationship.

**REF-REL-006:** Human review MAY attest to an inferred relationship, and a
local adoption MAY authorize product use. An implementation MUST NOT use
either record to rewrite the assertion's origin, epistemic basis, extraction
provenance, or AI lineage.

**REF-REL-007:** Shared identifiers, citations, timing, co-occurrence, and
similarity MAY propose relationships. They MUST NOT, without an applicable
source rule or further evidence, prove identity, dependency, causation,
amendment, supersession, or legal effect.

### 10.3 Similarity

Similarity is usually symmetric, continuous, dimension-specific, and
query-relative.

**REF-SIM-005:** A `SimilarityObservation` MUST identify:

- compared records, fragments, or query;
- comparison dimension;
- representation and input snapshot;
- algorithm or model and version;
- score, scale, and ranking context;
- evaluation time; and
- query or cache identifier.

Useful dimensions include subject, affected population, legal authority, legal
text, policy mechanism, intended outcome, procedure, operational dependency,
evidentiary role, contradiction, and temporal episode.

**REF-SIM-006:** A query MAY weight the declared similarity dimensions
differently for legal research, compliance, advocacy, program management, or
another declared task.

**REF-SIM-001:** A similarity observation MUST NOT satisfy a query for
dependency, identity, authority, amendment, supersession, causation, or legal
effect.

**REF-SIM-002:** General nearest-neighbor and topical-similarity results SHOULD
be computed at query time.

**REF-SIM-003:** Caching a similarity result MUST NOT change its persistence
class or authority.

**REF-SIM-004:** A system MAY promote a query-time result only by creating a
new `rkaf:RelationshipAssertion` with the evidence, provenance, attestation,
adoption, and predicate requirements of the pinned Rulespec and REF profiles.

### 10.4 Dependency

Dependency is directed and scoped. It states that one resource's
interpretation, validity, implementation, or operation materially relies on
another resource.

**REF-DEP-005:** An accepted dependency MUST be an
`rkaf:RelationshipAssertion` whose predicate identifies the dependency kind.
Its applicability identifies the affected scope, its Rulespec evidence
bindings preserve supporting and qualifying source fragments, and its
Rulespec temporal and provenance records preserve validity and construction.
When possible, its object SHOULD be the externally typed definition,
requirement, dataset, procedure, standard, or finding involved rather than a
whole-document proxy.

**REF-DEP-006:** Core dependency kinds MAY include:

- `dependsOnDefinition`;
- `dependsOnRequirement`;
- `dependsOnDataset`;
- `dependsOnProcedure`;
- `dependsOnStandard`;
- `dependsOnFinding`; and
- `operationallyImplements`.

**REF-DEP-001:** Dependency and similarity MUST be separate,
non-substitutable predicates.

**REF-DEP-002:** A confirmed document-level dependency MUST identify its scope
or point to the externally typed resource involved. A bare `dependsOn` edge is
insufficient.

**REF-DEP-003:** A dependency processor SHOULD apply this counterfactual test:
if the target changed, would the subject's interpretation, validity,
implementation, or operation materially change?

**REF-DEP-004:** A processor MUST ask a relation-specific question against
specific Rulespec source fragments. It MUST NOT confirm dependency from an
unconstrained "are these related?" judgment.

### 10.5 Candidate discovery and adjudication

**REF-REL-016:** Relationship candidate generation MAY use:

- shared official identifiers and citations;
- shared entities, programs, legal provisions, standards, datasets, or
  definitions;
- lexical passage retrieval;
- dense passage retrieval;
- extracted concepts or Rulespec assertions;
- source structure and lifecycle sequence; and
- temporal, agency, or jurisdictional priors.

**REF-REL-008:** Candidate generation MUST remain separate from relation
adjudication.

**REF-REL-009:** A relationship candidate MUST retain every generating channel
and the input snapshot.

**REF-REL-010:** Adjudication MUST evaluate one declared predicate or
predicate family at a time and return accepted, review-required, candidate,
rejected, disputed, or abstained.

**REF-REL-011:** An adjudicator MUST cite the exact
`rkaf:SourceFragment` used for each subject and object role. A structured
source field MUST first resolve to a conforming source fragment.

**REF-REL-012:** A model-generated relationship MUST be retractable and MUST
have a complete REF run receipt and Rulespec extraction and AI lineage. It MUST
be recomputable when its recorded
provider, model, configuration, inputs, and other required dependencies remain
available. Otherwise, the receipt MUST state the limitation and the producer
MUST NOT claim that the result can be regenerated.

### 10.6 Durable and query-time relationships

Good durable candidates include:

- source-explicit citations and lifecycle links;
- verified identity or equivalence;
- supported version lineage;
- scoped dependencies;
- accepted concept mappings;
- specified contradictions;
- uses of the same named dataset or standard; and
- approved policy-thread membership.

Good query-time candidates include:

- nearest neighbors;
- general topical similarity;
- weak co-occurrence;
- transient clusters;
- per-user relevance; and
- unreviewed heuristic associations.

**REF-REL-013:** Storage in a graph, index, cache, or table MUST NOT by itself
make a relationship durable.

**REF-REL-014:** A durable correction MUST use Rulespec supersession,
attestation, adoption, or lifecycle records as applicable. It MUST NOT rewrite
the earlier assertion in place.

### 10.7 Multi-hop reasoning

**REF-PATH-004:** A system MAY explain an indirect connection as a path, for
example:

```text
Artifact B → Program Y → Eligibility definition X ← Artifact A
```

**REF-PATH-001:** A derived path MUST identify every supporting Rulespec
assertion, predicate, attestation, adoption, and consumer lifecycle state.

**REF-PATH-002:** A path MUST NOT be presented as a direct relationship.

**REF-PATH-003:** A path evaluator MUST account for time, access controls,
retracted Rulespec assertions, predicate semantics, and maximum path length.

### 10.8 Absence and bounded negative search results

A missing edge can mean that no relationship exists, that the source omitted
it, that acquisition was incomplete, or that the processor failed to find it.
REF therefore represents negative search results as bounded operational
`AbsenceEvaluation` records, not assertions about the represented world.

**REF-ABS-004:** An `AbsenceEvaluation` MUST identify:

- the proposition or predicate not found;
- the searched corpus, source families, record kinds, and time range;
- the release and capture-completeness state;
- the search or derivation method and version;
- excluded, restricted, failed, and unprocessed material;
- the time of evaluation; and
- the evaluation activity and any Rulespec attestation of the evaluation.

**REF-ABS-001:** "No relationship found" MUST NOT be presented as "no
relationship exists" without a bounded absence evaluation and a completeness
rule that supports that conclusion.

**REF-ABS-002:** A later source acquisition, parser repair, registry release,
or method change MUST create a new absence evaluation. It MUST NOT silently
rewrite the earlier result.

**REF-ABS-003:** A query service MUST distinguish `notFound`,
`notApplicable`, `notProcessed`, `incompleteSource`, `restricted`, and
`processingFailed`.

## 11. Policy threads

A policy thread is an REF application view grouping source resources and
portable semantic records that concern a scoped, evolving matter. It avoids a
dense set of unsupported pairwise links and is not a new ontology class.

**REF-THR-007:** A durable `PolicyThread` MUST state:

- stable identifier;
- purpose and scope;
- supporting `rkaf:SourceFragment` identifiers;
- jurisdiction;
- temporal bounds;
- inclusion and exclusion rules;
- owner or responsible agent;
- version and operational state;
- membership method; and
- supersession history.

An ephemeral cluster is a query-time association, not a durable policy thread.
Review and approval of a durable thread use `rkaf:Attestation`; authorization
for product use uses `rkaf:LocalAdoption` over the thread's membership
assertions. Supersession uses Rulespec lifecycle records where applicable.

**REF-THR-001:** Each durable member MUST have a separate
`rkaf:RelationshipAssertion` using the profile's membership predicate, with
its own Rulespec provenance, evidence, applicability, attestation, and
adoption.

**REF-THR-002:** Membership MUST NOT imply identity, dependency, causation,
shared legal action, or agreement among all members.

**REF-THR-003:** A machine-generated cluster MUST remain a query-time
association until it has coherent scope, representative evidence, a Rulespec
attestation, and any required local adoption.

**REF-THR-004:** A record MAY belong to multiple competing or overlapping
threads.

**REF-THR-005:** Thread merge, split, retirement, and scope change MUST create
new thread versions and the applicable Rulespec attestations, relationship
assertions, and lifecycle events.

**REF-THR-006:** Each durable thread version MUST expose its supporting
Rulespec source fragments, membership assertions, attestations, local
adoptions, and supersession history. Approval MUST NOT rewrite the origin or
lineage of machine-generated membership.

## 12. Registry operations and concept governance

### 12.1 Resource kinds and scheme identity

REF distinguishes:

- subject thesauri and taxonomies;
- ontologies;
- identifier authorities;
- entity registries;
- code lists and classifications; and
- document or data schemas; and
- mapping sets.

The controlled-resource coverage routes are independently justified:

| Route | Distinguishing role |
| --- | --- |
| `subjectScheme` | Governed concepts intended for subject assignment or navigation |
| `ontology` | Formal classes, properties, axioms, or entailment rules |
| `identifierAuthority` | Governed identifiers whose primary role is resolving referents |
| `entityRegistry` | Governed entity records and attributes, not only identifier issuance |
| `codeList` | Enumerated operational values without broader classification meaning |
| `classification` | Codes that organize members into a governed classification |
| `schema` | Document, message, or data structure and validation rules |
| `mappingSet` | Governed cross-resource mapping statements |

Rulespec and SKOS own concept, scheme, status, and mapping meaning. Rulespec
owns portable release identity and membership for every managed reference
resource through `rkaf:ReferenceResourceRelease`; the release preserves its
version, resource kind, membership mode and any permitted membership claims,
distributions, and RDFC-1.0 semantic `rkaf:referenceReleaseDigest`.
`rkaf:completeMembership` and `rkaf:partialMembership` enumerate members;
`rkaf:membershipNotEnumerated` does not. Only complete membership can support
a concept-assignment or concept-mapping endpoint pin. Distribution
`rkaf:Artifact` records preserve their own byte digests. Rulespec keeps
`dcterms:type` open; these REF routes do not close or redefine its value set.
REF normalized label rows MAY carry the source's status token as opaque import
data. REF MUST NOT restrict that token to a copied Rulespec enumeration,
interpret it as portable lifecycle authority, or use it by itself to authorize
candidate or accepted-output use.

**REF-VOC-001:** Every Rulespec-owned `rkaf:LocalConcept`,
`rkaf:RegisteredConcept`, concept assignment, and concept mapping in a registry
payload MUST validate under the pinned Rulespec release. Native SKOS, OWL,
code-system, or schema distributions remain canonical for external resources;
their `rkaf:ReferenceResourceRelease` pins the distribution and declares its
membership mode. A complete-membership release pins its exact members, and
assignments target those member IRIs. REF MUST NOT define a
`ConceptVersion` or parallel semantic record. A `RegistryImportSnapshot`
records which immutable source snapshot contained the Rulespec or external
resource.

**REF-VOC-002:** The import and indexing pipeline MUST preserve distinct
Rulespec concept identifiers when labels are identical.

**REF-VOC-003:** A reference-resource import MUST preserve in its native
distribution all supplied notations or codes; preferred, alternate, and hidden
labels; language tags, including script subtags; definitions; scope,
editorial, and history
notes; status; every hierarchy edge including multiple broader parents;
replacements; source mappings; source identifiers; scheme membership; and
other source notes that affect meaning. A project-authored Rulespec concept
MUST use the multilingual label, note, typed-notation, multi-parent hierarchy,
registration, and lifecycle shapes required by the application profile. An
implementation MUST NOT claim that Rulespec `rkaf:LocalConcept` or
`rkaf:RegisteredConcept` constraints preserve those fields unless the exact
pinned Rulespec release supports them.

**REF-VOC-004:** An output profile MUST declare which schemes it may emit and
which schemes serve only retrieval, mapping, or search expansion.

**REF-VOC-005:** REF candidate generation MUST NOT treat a
Rulespec-incorporated SKOS broader or narrower link as a logical subclass
relation, legal fact, or automatic concept assignment.

### 12.2 Registry import and deployment

An REF `RegistryImportSnapshot` is the generic operational import record. It
connects the acquisition and transformation history for an external controlled
resource to its canonical release, but it does not own the acquired bytes or
the release. A retrieved input is one or more REF `Capture` records. A
non-retrieved input is an explicit external reference. Rulespec
`rkaf:ReferenceResourceRelease` owns the release identifier, version,
resource kind, membership mode and claims, distribution references, and
semantic `rkaf:referenceReleaseDigest` for each imported subject scheme, ontology,
identifier authority, entity registry, code list or classification, schema,
or mapping set. The release is the semantic manifest. Its distribution
`rkaf:Artifact` records retain their byte digests. REF does not mint a
competing release, version, digest, member list, or distribution description.

**REF-VOC-016:** A `RegistryImportSnapshot` MUST record:

- its inventory-coverage component and import profile;
- every REF `Capture` used for a retrieved input and every explicit external
  reference used for a non-retrieved input;
- the referenced `rkaf:ReferenceResourceRelease` and applicable distribution
  `rkaf:Artifact` records;
- import-time rights-assessment and adopted-policy references;
- transformation version;
- exclusions and failures;
- Rulespec and REF validation results;
- expected refresh cadence; and
- predecessor import snapshot, when applicable.

Source locator, retrieval time, obtained bytes, transport metadata, and
acquisition digest remain in `Capture`. Source identifiers, labels, and
semantic content remain in the native distribution and Rulespec release.
Observed license and permitted-use terms remain in `RightsAssessment` and the
adopted policy. The snapshot MUST NOT duplicate those values, the referenced
release's canonical identity, version, membership mode or claims,
distributions, or `rkaf:referenceReleaseDigest`, or the distribution
artifacts' canonical identities or byte digests, as independently
authoritative REF fields.

**REF-VOC-021:** Every `RegistryImportSnapshot` used for candidate generation
or accepted output MUST have an immutable `RegistryImportCoverageReport`. The
report MUST identify the import snapshot, exact Rulespec
`rkaf:ReferenceResourceRelease`, applicable distribution artifacts, import
profile, parser version, logical `expressionCorpusSnapshot`, exact
`OutputProfile`, activity, receipt, report status, and canonical payload
digest. The indexed stage in this report measures materialization into the
logical managed release; it does not describe a consumer's physical lookup
index. Literal assertions on release members MUST resolve to exact
`IndexedVocabularyExpression` records. Scheme metadata and structural, status,
replacement, identity, mapping, and membership assertions MUST resolve to the
applicable exact graph or normalized representation. Counting a source
assertion as indexed merely because the parser retained it is not sufficient.
Each feature row MUST state whether that feature is required for candidate or
accepted-output use under the named profile. The report MUST contain one
feature row for each applicable feature:

- members and scheme membership;
- preferred, alternate, and hidden labels;
- language tags, including script subtags;
- typed notations;
- definitions, examples, scope notes, editorial notes, history notes, change
  notes, and other source notes that affect meaning;
- broader and narrower hierarchy relations;
- scheme-internal associative relations;
- source and cross-scheme mappings;
- status and deprecation;
- replacements; and
- source and canonical identifiers.

Each feature row MUST contain source-observed, parsed, indexed, explicitly
excluded, and failed counts; digests for the source-observed, parsed, and
indexed stages; and references to itemized exclusions and failures. Every
exclusion MUST identify its policy and rationale. Counts and digests account
for the feature without copying its semantic content into the report.

**REF-VOC-022:** Import coverage MUST fail when a required feature has an
unexplained count or digest difference between source observation, parsing,
and indexing; when a source containing hierarchy, aliases, multilingual
labels, notation, notes, status, replacements, identifiers, membership, or
mappings reports zero of that feature after parsing without a complete
exclusion account; or when an excluded or failed item lacks a reason. A failed
coverage report MUST block registry deployment, candidate use, accepted-output
use, and an import-conformance claim. A source feature intentionally omitted
from an index MAY be fully accounted as excluded only when the selected
candidate and output profiles do not require it and its coverage row records
`requiredForCandidateOrOutput: false`.

**REF-VOC-023:** A `RegistryReconciliationReport` MUST identify every
conflicting official `rkaf:ReferenceResourceRelease`, distribution artifact,
and `RegistryImportSnapshot`. Each complete input tuple MUST have its own
identifier, and every difference MUST reference at least two of those exact
input identifiers. The report MUST identify the exact compared fields,
members, relations, and stage digests; every detected difference; applicable
`rkaf:ConceptMapping` records; the versioned source-precedence policy and its
Rulespec authority, attestation, and local-adoption references; every
unresolved item; responsible activity; recorded time; canonical payload
digest; and exactly one outcome: `selectedInput`,
`reconciledReleaseAuthorized`, or `unresolved`. A resolved report becomes
authoritative only when a gate-issued `ReleaseGraphValidationReceipt` binds
its exact digest, every authority, attestation, and adoption reference, and the
passing evaluation required by `REF-BIND-019`. Legacy
`authorizationValidations` values and their `effective` Booleans are
non-authoritative migration evidence. An unresolved report, a report absent
from that receipt, or an invalid governance reference MUST NOT authorize a
resolved outcome. A
`reconciledReleaseAuthorized` outcome MUST identify a new
`rkaf:ReferenceResourceRelease` with its own identity, complete membership,
distributions, provenance, and digest; it MUST NOT mutate any input release.

**REF-VOC-024:** Conflicting official publications MUST remain distinct until
a reconciliation report resolves their differences. An `unresolved` report,
an unattested report, or lexical equality alone MUST NOT authorize an
authoritative synthesized union. Candidate generation MAY expose the
conflicting inputs for review when a permission row allows it, but accepted
output MUST follow one exact authorized release or the separately published
reconciled release.

A `RegistryDeploymentDecision` records operational selection for a target
environment and output profile. Core states are `quarantined`, `staged`,
`selected`, `deselected`, and `failed`. Review and authority to use the release
are separate Rulespec attestations and local adoptions.

**REF-VOC-017:** A `RegistryDeploymentDecision` MUST identify the import
snapshot, its passing import-coverage report, any applicable reconciliation
report, target environment and output profile, selection state, effective and
recorded times, responsible activity, reason, applicable rights assessment and
adopted policy, every applicable Rulespec attestation and local-adoption
reference, and predecessor or superseding deployment decision when applicable.
A selected decision becomes deployable only when a gate-issued
`ReleaseGraphValidationReceipt` binds its exact digest and the passing
authorization evaluation required by `REF-BIND-019`. Legacy
`authorizationValidations` values are migration evidence only; their
`effective` Booleans and caller-named validators have no authorization effect.
A selected decision MUST NOT reference a failed coverage report, unvalidated
governance reference, or unresolved reconciliation as authority for a
synthesized release.

**REF-VOC-018:** A producer MUST compute current operational selection from
append-only `RegistryDeploymentDecision` records and permitted use from
applicable Rulespec access, retention, attestation, and local-adoption records
plus the adopted external rights expression. It MUST NOT mutate either the
import snapshot or Rulespec reference-resource release to represent deployment
or rights change.

**REF-VOC-006:** Each import MUST create an immutable import snapshot.

**REF-VOC-007:** A refresh MUST detect additions, removals, renames, hierarchy
changes, replacements, mapping changes, identifier reuse, publisher changes,
license changes, access changes, and permitted-use changes.

**REF-VOC-008:** Identifier reuse or unexplained deletion MUST fail closed.

**REF-VOC-009:** Historical `rkaf:ConceptAssignment` records MUST remain
resolvable against their referenced complete-membership
`rkaf:ReferenceResourceRelease`.

**REF-VOC-010:** A release MUST pass structural validation and declared
regression tests before deployment selection.

**REF-VOC-011:** Deployment selection MUST be atomic and rollback-capable. A
failed selection MUST leave the previous release logically selected. The producer
MAY continue using that Rulespec release only when its current adopted rights policy
permits the use. If those rights are revoked, conflicting, or unknown, the producer
MUST retain the release as restricted audit history and fail closed for the
affected use.

**REF-VOC-012:** Deployment selection MUST rebuild or invalidate every affected
candidate index, mapping view, acceptance cache, and export before the new
release enters an accepted view.

**REF-VOC-013:** A producer MUST retain import snapshots and receipts named by
quarantined and failed deployment decisions and MUST NOT expose their contents
as selected registry values.

**REF-VOC-014:** Ontologies, identifier authorities, entity registries, code
lists, classifications, schemas, and mapping imports MUST receive the same REF
snapshot, rights-assessment, refresh, historical-resolution, deployment, and
rollback controls as concept schemes. Each MUST reference its exact
`rkaf:ReferenceResourceRelease` and applicable distribution artifacts.
Concept assignments and mappings MUST use the Rulespec release-pin properties
defined for their roles and MUST pin only complete-membership releases. REF
MUST NOT copy the release version, membership mode or claims, distributions,
or semantic digest, or a distribution artifact's byte digest.

**REF-VOC-019:** A release for an identifier authority, schema authority, or
other resource whose members are not enumerated MUST use
`rkaf:membershipNotEnumerated` and pin the exact authoritative grammar,
resolver definition, or native content as a distribution and digest. It MUST
NOT assert `prov:hadMember`, support a concept assignment or mapping endpoint
pin, or serve as proof that an individual identifier was issued by that
authority.

**REF-VOC-020:** Every controlled-resource import, including a mapping set,
MUST use `RegistryImportSnapshot`. REF MUST NOT define or emit a separate
`MappingImportSnapshot` record or duplicate the generic snapshot's acquisition,
transformation, exclusion, validation, rights, or predecessor fields.

**REF-VOC-015:** A project-authored concept scheme MUST mint an immutable
scheme-native identifier when a concept proposal is promoted to a Rulespec
concept. It MUST NOT reuse the proposal identifier as a source-assigned
identifier from another scheme.

### 12.3 Cross-scheme mapping operations

Rulespec and SKOS own mapping relations and their semantic constraints. REF
uses the same `RegistryImportSnapshot` as every other controlled-resource
import, with resource route `mappingSet`. REF also owns deployment, indexing,
path recording, and rollback.

**REF-MAP-001:** Every published mapping MUST be an
`rkaf:ConceptMapping` that passes the pinned Rulespec validator. Its
mapping-set `RegistryImportSnapshot` MUST identify the exact source and target
`rkaf:ReferenceResourceRelease` records used to build that mapping payload.

**REF-MAP-002:** Lexical equality MUST NOT establish `exactMatch`.

**REF-MAP-003:** Mapping changes MUST follow the review, supersession, and
lifecycle rules in Rulespec and the REF immutable-snapshot and rollback
operations for registry changes.

**REF-MAP-004:** A mapping relation MUST NOT authorize inference by itself.
The output profile MUST declare which Rulespec relation, attestation decision,
local-adoption scope, and direction may support canonicalization or an accepted
assignment.
`closeMatch`, `broadMatch`, `narrowMatch`, and `relatedMatch` MUST NOT be
treated as `exactMatch`.

**REF-MAP-005:** An assignment produced through one or more mappings MUST
identify the mapping or ordered mapping path used. Every path element MUST
identify its `rkaf:ConceptMapping` identifier, relation, source and target
`rkaf:ReferenceResourceRelease` identifiers, and REF
mapping-set `RegistryImportSnapshot`.

**REF-MAP-006:** An REF query policy MAY define which Rulespec or SKOS mapping
relations it follows for candidate expansion, maximum path length, and
materialization. It MUST preserve the relation on every path element and MUST
NOT redefine SKOS inverse, symmetry, or entailment semantics. Operational path
expansion is not semantic transitive closure.

**REF-MAP-007:** Every imported `rkaf:ConceptMapping` MUST be traceable to one
immutable mapping-set `RegistryImportSnapshot`. Historical resolution MUST use
the exact mapping identifier and source and target Rulespec release pins
recorded by the REF enrichment decision, not the current mapping view.

### 12.4 Concept-proposal workflow

An REF registry workflow has concept proposals and published Rulespec concepts.
A concept proposal is not a semantic tier in the registry.

**REF-GOV-001:** Automated processing MUST NOT turn a concept proposal into an
`rkaf:LocalConcept` or `rkaf:RegisteredConcept`.

**REF-GOV-002:** Promotion MUST include:

- a definition;
- inclusion and exclusion cues;
- preferred and alternate labels;
- a proposed hierarchy position, top-concept declaration, nonhierarchical
  declaration, or documented not-applicable result;
- duplicate and mapping analysis;
- representative evidence that meets a versioned governance-policy rule;
- expected effect on existing assignments;
- rights review; and
- an `rkaf:Attestation` by the authorized concept-minting authority.

**REF-GOV-003:** Frequency MAY prioritize review. It MUST NOT establish meaning
or approval.

**REF-GOV-004:** Governance policy MUST name who may propose, map, approve,
deprecate, supersede, split, merge, and resolve disputes.

**REF-GOV-005:** A merge or split MUST preserve redirects, prior identifiers,
historical assignments, and an impact record.

**REF-GOV-006:** A promotion MUST NOT rewrite prior Rulespec assignment origin,
lineage, attestations, or adoption.

**REF-GOV-007:** Governance policy MUST define the evidence sufficiency for
promotion, including any exception for a new concept supported by one
authoritative rendition artifact. The framework MUST NOT infer sufficiency
from document count alone.

### 12.5 Managed releases and lookup consumers

A managed vocabulary release is an operational view, not a new semantic
record. It combines one exact Rulespec `rkaf:ReferenceResourceRelease` with
the REF import snapshot, coverage report, applicable reconciliation report,
registry deployment decision, and indexed expression corpus that REF selected
for one environment and output profile.

**REF-VOC-025:** REF is authoritative for its captures, imports, coverage,
reconciliation, expression corpus, deployment history, and operational
selection. The native publisher remains authoritative for an external source
distribution, and Rulespec remains authoritative for portable concept,
scheme, mapping, release, lifecycle, and resolution meaning. REF MUST NOT
present an imported or normalized representation as a replacement for the
publisher's native distribution.

**REF-VOC-026:** A managed release consumer MUST receive an immutable,
content-digested release manifest and read-only access to its selected
members, expressions, and relations. The consumer MUST NOT mutate an import
snapshot, coverage report, reconciliation report, deployment decision, or
Rulespec release. A correction or changed selection MUST create new
append-only REF records and any applicable Rulespec records.

**REF-VOC-027:** REF owns the language-preserving expression corpus and its
source and normalization lineage. A lookup consumer MAY build lexical, sparse,
dense, hybrid, or approximate-nearest-neighbor indexes from that corpus. A
changed concrete index, tokenizer, embedding, candidate channel, or ranking
policy MUST create a new `EnrichmentConfiguration`; it creates a new managed
vocabulary release only when the selected vocabulary content changes.
`expressionCorpusSnapshot` and `lookupIndexManifest` are separate exact digest
references: the former identifies the logical REF-owned corpus and the latter
identifies one physical consumer-built index. An `EnrichmentConfiguration` and
each registered candidate's lineage MUST pin both references, and MUST reject
a row that substitutes or reuses either reference as the other. A lookup-index
manifest MUST identify the exact expression-corpus snapshot from which the
index was built.

**REF-VOC-028:** Exact resolution of a release member by its identifier is a
managed-release access operation. Semantic retrieval, candidate generation,
ranking, and reranking are consumer operations. A candidate's presence, rank,
similarity, cache state, or index membership MUST NOT establish concept
identity, mapping equivalence, review, adoption, accepted-output permission,
or deployment authority.

**REF-VOC-029:** A lookup consumer MAY produce a correction or concept
proposal, but it MUST return that record to the REF governance workflow. It
MUST NOT mint an authoritative external identifier, rewrite a managed release
in place, reconcile official sources, or activate a release.

**REF-VOC-030:** A conforming managed-release implementation MUST retain large
native distributions and materialized indexes outside normative source files
when their size or rights make source control unsuitable. Every such artifact
MUST resolve through an immutable identifier, byte digest, media type, rights
record, and release or configuration manifest. A mutable path or object key
alone MUST NOT identify a release input or lookup index.

**REF-VOC-031:** A read-only managed-release consumer MUST require the exact
bundle-manifest byte digest supplied by its trusted release selection or
configuration. It MUST verify that digest before following any relative
artifact path, and MUST require the modeled gate-issued
`ReleaseGraphValidationReceipt` whose graph, REF records, validator, and
identifier coverage match the bundle. Internal self-digests alone do not
establish that the selected release is the authorized release. Normalized REF
tables MAY carry exact label-role, relation-predicate, lifecycle-operation,
participant-role, absolute concept-type IRI, assertion-origin, epistemic-basis,
evidence-role, and usage-eligibility values from that validated graph. The REF
runtime MUST preserve those values and verify their row-to-graph identity; it
MUST NOT maintain a second enumeration, range, hierarchy, lifecycle, or usage
rule for them.

**REF-VOC-032:** Before making a managed-release member or expression available
to candidate generation, or yielding a derived candidate row, a consumer MUST
authorize candidate access against exactly one `releasePermissions` row in the
exact selected `OutputProfile`.
That row MUST have `candidateUse: true`; its
`referenceResourceRelease` and `registryImportSnapshot` MUST match the managed
release; and its `facet` and `assignmentRole` MUST match the requested use.
The exact selected `EnrichmentProfile` MUST define that facet and list both the
assignment role and target resource route as compatible. The consumer MUST
reject absent selected profile or deployment evidence and any unknown,
incompatible, nonmatching, or ambiguous facet, role, route, release, snapshot,
or permission row before it yields any candidate.
A caller-supplied local label, alias, or default MUST NOT substitute for those
selected profile values. The consumer MAY record the authorized candidate
facet, role, and route as separate lookup lineage, but it MUST preserve every
release member, expression, relation, and release-carried semantic field
unchanged. It MUST NOT relabel managed-release rows.

**REF-VOC-033:** A managed-release expression backed by a normalized
`concept_labels` row MUST preserve that row's exact label role and any opaque
label-level source-status token. A source-native RDF status assertion MUST
remain a separate assertion with its exact subject, predicate, lexical value,
language or datatype, and release; an importer MUST NOT replace it with a
synthesized source token or Rulespec lifecycle event. Raw and evidence
expression access MUST retain every expression, including expressions for
concepts that are not eligible for a new current assignment.
Current-assignment candidate access MUST first pass `REF-VOC-032`, MUST
consider only expressions whose exact release and import references match that
permission, and MUST then exclude an exact Rulespec lifecycle predecessor for
deprecation, withdrawal, replacement, split, or merge under its pinned
complete-membership release. Promotion and demotion MUST NOT be treated as
retirement operations without a separate applicable rule.

A pinned import policy MAY interpret an exact source-status assertion or
opaque label token only to narrow candidate eligibility. The policy MUST name
the source predicate, permitted literal form, datatype or language, and
resulting exclusion classification. It MUST NOT present that classification as
source-authored data, portable Rulespec lifecycle meaning, or positive
candidate or output authority. The initial REF reference-runtime policy treats
a case-insensitive, surrounding-whitespace normalized `deprecated`,
`inactive`, or `withdrawn` label token as an exclusion. Its ELSST policy also
treats an exact `owl:deprecated` `xsd:boolean` value of `true` or `1` as an
exclusion; `false` or `0` does not exclude, and a malformed or differently
typed value MUST fail rather than be silently classified. More than one
distinct normalized label-level source-status token across a concept's label
rows is ambiguous and MUST fail closed for that concept's current-assignment
candidate access. An excluded concept MUST remain exactly resolvable by
identifier and available through raw historical expression access, but MUST
NOT be offered for a new current assignment.

**REF-VOC-034:** An external native SKOS member MAY remain a
`skos:Concept`; a projector MUST NOT recast it as an
`rkaf:RegisteredConcept` or `rkaf:LocalConcept` merely to satisfy a
project-authored shape. A normalized lifecycle-participant row MUST carry the
member's absolute RDF type IRI and MUST round-trip to that exact type in the
validated release graph. When a source supplies only a date but a Rulespec
lifecycle field requires `xsd:dateTime`, the import MUST retain the original
literal and source precision, pin the materialization policy, and identify the
materialized value as derived. It MUST NOT silently claim publisher-supplied
time precision or fabricate lifecycle events that predate the compared release
window.

**REF-VOC-035:** Every registry-import reference used by an indexed
expression, normalized row, coverage report, deployment decision, or output
permission MUST resolve to the exact packaged `RegistryImportSnapshot` record
and digest. A normalized label role MUST agree with its exact SKOS source
property. Lifecycle participant role-and-ordinal keys MUST be unique within
each event. A normalized relation's import snapshot and distribution artifact
MUST agree with the exact release lineage of both endpoints. Missing,
ambiguous, or inconsistent lineage MUST fail managed-release opening.

**REF-VOC-036:** A managed release that carries source-native
`dcterms:isVersionOf`, `owl:priorVersion`, `dcterms:isReplacedBy`, or
`dcterms:replaces` assertions on a member MUST preserve their exact subjects,
predicates, and objects and expose them through read-only identity and history
access. These assertions MUST remain distinct from Rulespec concept mappings
and lifecycle events and MUST NOT create an REF `ConceptVersion`. A consumer
MUST NOT infer a missing identity assertion from labels, identifier shape, or
URI structure.

**REF-VOC-037:** A closed managed release that carries a successful `Capture`
with `contentPreservation: exactBytes` MUST package or resolve one exact source
artifact whose identifier equals the capture's `storageReference`. Before
issuing the capture and again before opening the managed release, the
producer or consumer MUST verify that artifact's byte digest and byte length
against the capture. A parsed vocabulary object, expected digest, or
unresolved content-addressed name is not proof that the obtained bytes were
retained. Missing, changed, symlink-substituted, or multiply resolved source
bytes MUST fail.

**REF-VOC-038:** A managed release MAY bind a large
`IndexedVocabularyExpression` corpus as one content-addressed artifact instead
of listing every expression record in `ReleaseGraphValidationReceipt`.
The corpus descriptor MUST bind its exact artifact digest, logical
`expressionCorpusSnapshot`, record count, schema version, and a canonical
identity-set digest computed from the sorted expression identifiers. Each
identifier MUST itself be derived from the exact release, import, distribution,
scheme, member, semantic property, source property or path, original literal,
language or datatype, as required by `REF-CAND-009`. Physical JSON Lines order
MUST NOT change the logical identity-set digest. The
receipt MUST still bind the publication and every operational REF record
individually. Opening the release MUST verify the corpus artifact, validate
every expression against REF JSON Binding 1.0, reject duplicate identifiers,
recompute the count and canonical identity digest, and check every release,
import, distribution, scheme, member, semantic property, and source
reference. A corpus-level receipt MUST NOT weaken record validation or allow a
physical lookup index to become release authority.

**REF-VOC-039:** When a mutable distribution lacks a publisher-issued unique
row identifier, REF MUST identify each source observation only by its exact
`Capture`, collection or source-native path, and source ordinal, or by an
equivalently collision-free source locator bound to that capture. Mutable,
non-unique, or empty names, labels, and slugs MUST NOT become concept
identifiers or authoritative row identifiers. Changing the parsed or
normalized representation of those fields without changing the exact capture
and source locator MUST NOT change capture-local identity; changing the
capture, collection or path, or ordinal MUST change that identity. Two
observations in one capture MUST NOT share a locator, and an import MUST NOT
use a name or slug to disambiguate them. A capture-local identifier identifies
only the source observation: it MUST NOT assert cross-capture concept identity,
create an `rkaf:ConceptMapping`, select a reconciliation input, authorize a
synthesized union, or supply candidate or accepted-output authority.

**REF-VOC-040:** A source observation MUST preserve every identifier that the
source supplies. Identifiers are zero-or-more qualified values, not parallel
identifier and scheme arrays and not one selected canonical value. Each
qualified identifier MUST carry:

- the exact source value;
- whether the value is a code, IRI, registry identifier, citation, or other
  source-declared identifier;
- the issuing authority or identifier-scheme IRI when known;
- the exact source `Capture` and source-native path from which REF observed
  it; and
- the observation time plus any source-supplied effective start or end.

REF MUST retain distinct identifiers issued by the same or different
authorities. It MUST NOT reject them merely because their values differ,
silently choose one as canonical, or treat an identifier IRI as proof that two
source observations or concepts are identical. A source without a
publisher-issued identifier still uses the capture-local observation identity
defined by `REF-VOC-039`; that identity is a locator for the observed row, not
a publisher concept identifier.

## 13. Publication and query behavior

### 13.1 Required views

**REF-QRY-010:** A query service claiming REF conformance MUST provide:

- immutable release metadata;
- current accepted view;
- assertion history;
- source and derived provenance;
- evidence resolution;
- as-of query behavior; and
- filters by Rulespec assertion origin, attestation, local adoption, consumer
  lifecycle, and usage eligibility.

**REF-QRY-001:** A response MUST expose the Rulespec origin, epistemic basis,
extraction provenance, AI lineage, attestations, and local adoption needed to distinguish
source-aligned extraction, deterministic processing, model suggestions, human
assertion, and authorized product use. It MUST NOT derive that distinction
from an REF-only basis field.

**REF-QRY-002:** A current view MUST retain links to applicable Rulespec
attestations, adoptions, supersession, lifecycle, and prior assertions.

**REF-QRY-003:** An as-of response MUST state its time semantics and data
release.

**REF-QRY-004:** Query-time associations MUST be labeled as query-time and MUST
identify their method and snapshot.

### 13.2 User-facing explanation

**REF-QRY-011:** For each inferred or editorial connection, a consumer-facing
service SHOULD answer:

> Why am I seeing this?

**REF-QRY-005:** A displayed inferred relationship MUST show its predicate,
Rulespec origin and lineage, attestations, local adoption, applicability, and
supporting source fragments.

**REF-QRY-006:** A user MUST be able to filter or exclude inferred and
editorial relationships.

**REF-QRY-007:** A service SHOULD let authorized users report, dispute, or
correct a connection without deleting the original assertion.

**REF-QRY-008:** A confidence number MUST NOT substitute for an explanation,
evidence, or provenance.

**REF-QRY-009:** A response containing source-aligned or conflict-resolved
assertions MUST expose the applicable source-precedence policy, Rulespec
authority or warrant, attestations, local adoption, and any unresolved
conflicting assertions.

### 13.3 Export

**REF-EXP-001:** An export MUST identify its REF version, profile, release,
serialization, extension namespaces, and complete Rulespec pin from
`REF-BIND-009`.

**REF-EXP-002:** An export MUST preserve stable identifiers, source-native
identifiers, source-precedence policies, evidence addresses, time semantics,
rights-assessment references, and supersession history. It MUST preserve
Rulespec records losslessly rather than copying origin, review, authority,
lifecycle, access, retention, or use fields into REF records.

**REF-EXP-003:** A public export MUST enforce the access and use restrictions
of every included record and derived assertion.

## 14. Privacy, security, rights, and safety

### 14.1 Access and derived disclosure

**REF-SEC-001:** Access and use controls MUST apply at capture,
source-resource, source-resource-version, rendition artifact, source-fragment,
Rulespec semantic-record, policy-thread, embedding, and export levels.

**REF-SEC-002:** A derived object MUST NOT weaken restrictions that apply to
its source evidence.

**REF-SEC-003:** A producer MUST evaluate whether summaries, embeddings,
entity links, inferred attributes, relationship paths, or graph neighborhoods
disclose protected information even when source text is hidden.

**REF-SEC-004:** Access checks MUST apply before relationship traversal and
evidence expansion, not only before final rendering.

Portable access, retention, and use eligibility use `rkaf:AccessScope`,
`rkaf:RetentionPolicy`, and `rkaf:usageEligibility`. Rights not covered by
those Rulespec records, including acquisition, indexing, model use, display,
redistribution, attribution, and permitted purpose, use the external rights
vocabulary pinned by the REF Rulespec Application Profile. REF does not define
a `UsePolicy`.

**REF-SEC-005:** A derived record with multiple inputs MUST compute an
operational effective-use decision from the canonical Rulespec and external
policy records: a denial overrides an
allowance, permitted audiences and purposes narrow to their common authorized
set, every compatible retention constraint applies, and all compatible
attribution duties accumulate. If retention constraints cannot all be
satisfied, the policies conflict under `REF-SEC-006`.

**REF-SEC-006:** If policies conflict or a required permission is unknown, the
derived record MUST fail closed for that use and record the conflict. An
authorized policy decision MAY resolve the conflict prospectively; it MUST NOT
rewrite the earlier source policies.

**REF-SEC-007:** A security and derived-disclosure evaluation MUST identify its
threat model, tested record and derivative types, methods, results, and
unresolved risks. Approval and authorization MUST use Rulespec attestation and
local adoption.

### 14.2 Public participation

Public comments and similar participation records can contain names, contact
details, health information, sensitive narratives, duplicated campaigns, and
content submitted by third parties.

**REF-PRIV-001:** A participation processor MUST use a separately versioned
profile, approved and adopted through Rulespec, covering purpose, minimization,
personally identifiable information,
sensitive-attribute inference, retention, deletion, entity resolution,
aggregation, reviewer access, and public release.

**REF-PRIV-002:** Participation records MUST NOT enter the general document
pipeline or public graph by default.

**REF-PRIV-003:** A participation profile MUST define whether and how deletion
or redaction requests affect captures, derived objects, embeddings, caches, and
published releases.

**REF-PRIV-004:** A participation profile MUST state a specific collection and
processing purpose, limit processing to the minimum data needed for that
purpose, define a retention period, and link the authorized privacy attestation
and local adoption.

**REF-PRIV-005:** Sensitive-attribute inference, cross-context entity
resolution, model training, and public release are prohibited unless the
approved profile separately authorizes the exact use, evidence, audience,
retention, and review controls.

### 14.3 Untrusted content and model safety

**REF-SAFE-001:** Source text, markup, metadata, and attachments MUST be treated
as untrusted data, not executable instructions.

**REF-SAFE-002:** File processing MUST use media sniffing, size and
decompression limits, parser isolation, malware controls, and resource limits
appropriate to the risk.

**REF-SAFE-003:** Model output MUST be schema-validated. It MUST NOT directly
authorize publication, concept promotion, identity merge, access change, or
other durable high-impact action.

**REF-SAFE-004:** A producer MUST prevent untrusted content from altering
system prompts, tool permissions, acceptance rules, or provenance records.

### 14.4 Rights and permitted use

**REF-RIGHTS-001:** A source or vocabulary review MUST decide acquisition,
storage, indexing, model use, redistribution, and display rights separately.
Permission for one use MUST NOT imply permission for another.

**REF-RIGHTS-002:** Every release MUST identify applicable attribution,
license, access, retention, and redistribution conditions.

**REF-RIGHTS-003:** Rights uncertainty MUST be explicit and MUST NOT be
silently converted into permission. For a managed vocabulary, an adopted
project policy MAY nevertheless make a recorded determination that the
uncertainty does not block named uses, including acquisition, storage,
indexing, model use, display, retention, or experimental redistribution. That
determination MUST name each permitted use, its purpose and audience, the
evidence and assumptions relied upon, residual risk, attribution, and
effective time; it MUST NOT claim legal clearance. Without such an affirmative
determination, the producer MUST fail closed for the unclear use. Access,
privacy, security, and production-release controls remain independent and MAY
still block use.

**REF-RIGHTS-004:** A `RightsAssessment` MUST identify its target release or
source, the observed terms and supporting source fragments, proposed
acquisition, storage, indexing, model-use, display, redistribution, retention,
purpose, attribution, and audience permissions, effective and recorded times,
and any prior assessment. Its accepted policy MUST use the Rulespec and
external rights records named above; review and authorization MUST use
Rulespec attestation and local adoption. A rights change MUST append a new
assessment and policy records.

## 15. Validation and evaluation

### 15.1 Structural conformance

The REF validator tests operational records and cross-system references.
Rulespec's validator is the only validator of Rulespec semantic records.

**REF-TEST-002:** An REF validator MUST test:

- required fields and operational value sets;
- identifier stability;
- source-native value preservation;
- capture, source-record, source-resource-version, and rendition-role
  separation;
- evidence-address resolution to `rkaf:SourceFragment`;
- reference integrity between REF processing records and Rulespec records;
- run-receipt completeness;
- time semantics;
- registry and publication history;
- exact inventory-baseline digests, row accounting, coverage routes, and
  independent status dimensions;
- access-control enforcement;
- class-specific REF requirements; and
- presence and success of the exact pinned Rulespec validation report.

**REF-TEST-003:** Rulespec-owned field cardinalities, value sets, semantic
invariants, and behavior MUST be tested by the pinned Rulespec conformance
suite. REF fixtures MAY exercise them end to end but MUST NOT copy those
constraints into an REF schema.

### 15.2 Required negative tests

**REF-TEST-001:** A conformance suite MUST report each independently numbered
negative case below when its claimed classes or emitted features trigger that
case. It MUST mark every other case `notApplicable` under `REF-CONF-009`.

**REF-TEST-101:** Same-label concepts from different schemes MUST survive a
round trip as distinct concepts.

**REF-TEST-102:** A chemical entity MUST NOT silently become a policy subject.

**REF-TEST-103:** A label rename MUST NOT change concept identity.

**REF-TEST-104:** A deprecated concept MUST remain historically resolvable but
MUST receive no new assignment under a current profile.

**REF-TEST-105:** A no-fit passage MUST produce an abstention, an authorized
grounded open label, or a local concept proposal, not a forced nearest concept.

**REF-TEST-106:** An agency or CFR prior MUST NOT suppress the global
candidate path without a profile-specific recall gate.

**REF-TEST-107:** A concept assignment on one rendition artifact MUST NOT
propagate automatically to its source resource, docket, another rendition, or
a later source-resource version.

**REF-TEST-108:** A vocabulary refresh MUST NOT silently delete or reuse an
identifier.

**REF-TEST-109:** Source-aligned extraction, deterministic processing,
model-suggested output, human attestation, and local adoption MUST remain
distinguishable through REF and Rulespec records.

**REF-TEST-110:** Evidence MUST remain bound to its rendition digest.

**REF-TEST-111:** Similarity MUST NOT satisfy dependency or identity queries.

**REF-TEST-112:** Thread membership MUST NOT imply pairwise dependency.

**REF-TEST-113:** Caching MUST NOT promote a query-time association.

**REF-TEST-114:** Restricted evidence MUST NOT leak through a relationship
path or embedding.

**REF-TEST-115:** Replay MUST identify deterministic and nondeterministic
stages separately.

**REF-TEST-116:** Preferred labels with different BCP 47 language tags,
including distinct script subtags, MUST survive without collision.

**REF-TEST-117:** `closeMatch`, `broadMatch`, `narrowMatch`, or `relatedMatch`
MUST NOT act as `exactMatch` without an explicit profile rule that preserves
its real relation.

**REF-TEST-118:** A mapping-only scheme, unauthorized release, or wrong-facet
value MUST NOT enter an accepted assignment view.

**REF-TEST-119:** Abstention, processing failure, cancellation, and no
attempted processing MUST remain distinct.

**REF-TEST-120:** After a failed registry deployment selection, the prior release MUST
remain logically selected and historical assignments MUST remain resolvable.
The release MUST remain usable only when its current adopted Rulespec and
external rights records permit that use.

**REF-TEST-121:** An external reference MUST NOT appear as captured source
material without a capture.

**REF-TEST-122:** `notFound` MUST NOT appear as proof of absence without a
bounded absence evaluation.

**REF-TEST-123:** A lower-precedence source MUST NOT silently replace a
conflicting Rulespec assertion selected under a higher-precedence source
policy.

**REF-TEST-124:** A derived record MUST NOT widen the audience, purpose, or
permitted use of any input policy.

**REF-TEST-125:** Registry selection, deselection, failure, and rights changes
MUST append REF operational records and applicable Rulespec records and MUST
NOT mutate the immutable `rkaf:ReferenceResourceRelease`, its distribution
artifacts, or the REF import snapshot.

**REF-TEST-126:** A historical assignment that used a mapping path MUST resolve
every exact `rkaf:ConceptMapping`, source and target
`rkaf:ReferenceResourceRelease`, and REF mapping-set
`RegistryImportSnapshot` used at its decision time.

**REF-TEST-127:** A staged, deselected, or failed output
profile MUST NOT be selected for a new accepted pipeline result. A selected
profile still requires the applicable Rulespec attestation and local adoption.

**REF-TEST-128:** Each enrichment outcome MUST satisfy the result-reference
cardinality in `REF-ENR-014`.

**REF-TEST-129:** A registered assignment MUST NOT enter an accepted view
without a passing registry conformance manifest for its referenced release.

**REF-TEST-130:** A source adapter MUST NOT perform a production capture
without an approved source profile and explicit acquisition and storage rights.

**REF-TEST-131:** A validator MUST accept every valid reference fixture and
reject every intentionally invalid reference fixture in its declared scope
with the applicable requirement identifier.

**REF-TEST-132:** Two deterministic replays over fixed inputs and versions MUST
produce identical canonical payload identifiers and semantic digests while
preserving each run's distinct provenance in linked receipts.

**REF-TEST-133:** A native REF export round trip MUST preserve all REF
operational records, Rulespec records, source-precedence policies,
rights-assessment references, and the exact Rulespec pin without copying
Rulespec semantic state into REF fields.

**REF-TEST-134:** A registry conformance manifest whose assessed identifier,
version, or `rkaf:referenceReleaseDigest` differs from the referenced
reference-resource release MUST NOT authorize a registered assignment.

**REF-TEST-135:** An inventory-coverage manifest with a missing, duplicate,
placeholder, unclassified, or unknown enumeration entry, required row account,
named constituent, role, or component, or with an account for a
`definitionRow`, MUST NOT satisfy complete portfolio accounting or
full-framework design coverage.

**REF-TEST-136:** `supported` representability or adapter implementation MUST
NOT imply release inclusion or rights/use authorization. A coverage entry
that omits a route family, semantic route, applicable source acquisition mode,
semantic/use mode, or any of the four status dimensions MUST fail validation.

**REF-TEST-137:** A `rightsBlocked` source or controlled resource MUST NOT
enter a production use whose authorization remains blocked.

**REF-TEST-138:** A completely accounted component whose representability
status is `planned`, `deferred`, `unsupportedWithReason`, or `notAssessed` MAY
pass portfolio accounting but MUST prevent a full-framework design-coverage
claim.

**REF-TEST-139:** A concept assignment or mapping endpoint that pins a
`rkaf:partialMembership` or `rkaf:membershipNotEnumerated` release MUST fail
validation even when the target IRI appears in a native distribution or a
partial member list.

**REF-TEST-140:** A conforming `rkaf:membershipNotEnumerated` release with
an exact authoritative grammar, resolver definition, or native content
distribution and digest, and with no `prov:hadMember` claims, MUST be
representable as an identifier or schema authority without inventing member
IRIs.

**REF-TEST-141:** A `RegistryImportSnapshot` that copies source bytes,
transport metadata, or an acquisition digest from `Capture`, or copies a
distribution artifact's identity or byte digest as independently authoritative
snapshot fields, MUST fail validation.

**REF-TEST-142:** A mapping-set import represented by a distinct
`MappingImportSnapshot` rather than the generic `RegistryImportSnapshot` MUST
fail validation.

**REF-TEST-143:** An inventory-coverage component whose rights/use status is
`supported` or `rightsBlocked` without references to the exact
`RightsAssessment` and applicable adopted Rulespec and external policy
evidence MUST fail validation. The status alone MUST NOT authorize use.

**REF-TEST-144:** The invoked Rulespec conformance path MUST recompute every
`rkaf:ReferenceResourceRelease` semantic digest and reject a wrong but
lexically valid `rkaf:referenceReleaseDigest`. An REF checksum comparison
without that upstream verification MUST NOT satisfy combined conformance.

**REF-TEST-145:** The portfolio-accounting validator MUST reject a baseline
enumeration that omits any table data row or named portfolio item, leaves one
unclassified, or marks a row that names a source, feed, reference spine,
external system, controlled resource, or distinct constituent as an
explanatory definition.

**REF-TEST-146:** A component marked with `supported` representability MUST
fail validation when its concrete representation mapping, positive fixture, or
round-trip fixture is missing, stale, lossy, or does not exercise every named
constituent and role. Aggregate fixtures that do not identify the covered
component MUST NOT satisfy `REF-PORT-012`.

**REF-TEST-147:** The portfolio-accounting validator MUST reject a compound
row or cell whose named feed, resource, subtype group, or semantic role has no
source-located enumeration occurrence and resolved component. It MUST also
reject a full-framework design-coverage claim whose pinned
`BaselineEnumerationReport` lacks a passing independent Rulespec audit
attestation.

**REF-TEST-148:** A newly onboarded item outside the two dated inventories MUST
fail complete portfolio accounting when it is active in an implementation but
absent from the implementation's pinned enumeration report and coverage
manifest.

**REF-TEST-149:** An extension route or `recordKind` MUST fail validation when
it uses a non-IRI or generic catch-all value; lacks a versioned extension
profile, core-route non-fit rationale, operational and portable bindings, or
required fixtures; or weakens an applicable REF or Rulespec requirement.

**REF-TEST-150:** An accepted registered or mapping-derived result MUST fail
when no single `OutputProfile` permission row matches its facet, role, release,
import snapshot, relation, direction, and accepted-output permission. A tuple
assembled from fields in separate valid rows MUST fail.

**REF-TEST-151:** A candidate-only release, candidate-only mapping, diagnostic
resource, decoy resource, or mapping-only resource MUST be usable for candidate
generation only when its row permits that use and MUST fail if it enters
accepted output. A row with `acceptedOutputUse: true` and
`candidateUse: false` MUST fail validation.

**REF-TEST-152:** A candidate, gold expectation, permission row, decision, or
accepted result with an unknown facet, a wrong-facet value, an incompatible REF
resource route, or an assignment role not permitted for that facet and route
MUST fail the applicable validation or evaluation gate.

**REF-TEST-153:** An accepted open label MUST fail unless one complete
permission row authorizes its facet, role, language mode, candidate use, and
accepted-output use and its `rkaf:ValueAssertion` uses `rkaf:openLabel`, carries
matching `rkaf:openLabelFacet` and `rkaf:openLabelRole`, contains a valid
language-tagged value, carries the required extraction provenance and assertion
time, and has a fragment-backed supporting `rkaf:EvidenceBinding`. A declared
default language MUST appear on the final value; an untagged or `@none` value,
or a no-evidence reason without supporting evidence, MUST fail.

**REF-TEST-154:** A source distribution that contains hierarchy, alternate or
hidden labels, multilingual labels, typed notation, notes, status,
replacements, identifiers, membership, or mappings MUST fail import coverage
when any such feature becomes an unexplained zero or has an unexplained count
or digest difference at the parsed or indexed stage.

**REF-TEST-155:** Identical original or normalized literals from different
schemes, releases, members, semantic properties, source locators, languages,
or datatypes MUST survive as distinct `IndexedVocabularyExpression` records
and candidates. An expression whose exact source locator is a `sourcePath`
MUST retain its absolute `semanticProperty`; omitting or changing that
property MUST fail identity and semantic-use checks. A label-derived concept
identifier or ASCII-only original representation MUST fail.

**REF-TEST-156:** Conflicting official controlled-resource publications MUST
remain distinct. A synthesized authoritative union MUST fail unless a
`RegistryReconciliationReport` accounts for every input and difference, has no
unresolved item, carries the required Rulespec attestations and adoption, and
identifies a separately published reconciled release.

**REF-TEST-157:** A sealed holdout MUST fail when its development partition
shares any concept identity, exact-match cluster, current or deprecated alias,
source identity, artifact digest, text digest, or near-duplicate cluster. It
MUST also fail when linked versions or renditions cross the split.

**REF-TEST-158:** Gold and evaluation fixtures MUST preserve the directional
distinction among `targetBroaderThanGold`, `targetNarrowerThanGold`, `related`,
and `wrong`. A `notRepresented` item MUST route to open-label,
concept-proposal, or abstention evaluation and MUST remain in availability and
open-set measures while being excluded from reachable registered-candidate
recall.

**REF-TEST-159:** Changing any behavior-relevant implementation, runtime,
model, provider setting, prompt, schema, lookup-index manifest, expression
corpus, normalization, candidate channel, fusion or truncation rule, policy,
threshold, budget, registry, mapping, output profile, or permission tuple
while retaining the prior configuration identifier, digest, or evaluation
result MUST fail. A configuration or candidate lineage that conflates its
logical `expressionCorpusSnapshot` with its physical `lookupIndexManifest`
MUST fail.

**REF-TEST-160:** A production `EnrichmentDeploymentDecision` MUST fail when
its configuration, evaluation result, or output-profile identifier or digest
does not match exactly; when its result verdict is `fail` or
`developmentOnly`; or when required Rulespec approval or authorization is
absent.

**REF-TEST-161:** Project-authored Rulespec concepts with English, Spanish, and
`zh-Hant` labels MUST survive an end-to-end round trip. A malformed BCP 47 tag,
untagged label, `@none` entry, or `rkaf:RegisteredConcept` without
`rkaf:registeredAt` MUST fail the invoked Rulespec validation.

**REF-TEST-162:** A project-authored Rulespec concept with more than one
preferred label for one language, or with the same literal colliding across its
preferred, alternate, or hidden labels for one language, MUST fail the invoked
Rulespec validation.

**REF-TEST-163:** Typed notation and every supported `skos:definition`,
`skos:example`, `skos:note`, `skos:scopeNote`, `skos:editorialNote`,
`skos:historyNote`, and `skos:changeNote` property MUST survive every generated
Rulespec target and REF import/index accounting path without loss of lexical
form, datatype, language, or source property.

**REF-TEST-164:** Multiple scheme-internal `skos:broader` parents MUST survive
the Rulespec source, generated targets, REF import, index, and round trip. A
cross-scheme `skos:broader` edge MUST fail; the relationship MUST use a
Rulespec `rkaf:ConceptMapping`.

**REF-TEST-165:** Each Rulespec concept lifecycle operation MUST enforce its
predecessor-to-successor cardinality and exact complete-membership release
pins: 1-to-0 for deprecation and withdrawal, 1-to-1 for replacement,
promotion, and demotion, 1-to-2-or-more for split, and 2-or-more-to-1 for
merge. Retired standalone promotion or demotion event forms MUST fail.

**REF-TEST-166:** A Rulespec `rkaf:ConceptResolutionResult` MUST fail without
its required resolution method, cache status, or usage ceiling. A result whose
method depends on a concept mapping MUST fail without the exact
`rkaf:mappingAssertion`.

**REF-TEST-167:** For the Rulespec features invoked by this profile, source
generation MUST be idempotent; authoritative CUE and generated JSON Schema,
SHACL, TypeScript, and Rust verdicts MUST agree for the shared fixtures; and
the complete pinned Rulespec conformance gate MUST pass. The applicable REF
suite MUST then accept every valid fixture, reject every invalid fixture with
its requirement identifier, and pass lossless round trips.

**REF-TEST-168:** A consumer that attempts to mutate a managed release,
reconciliation result, deployment decision, or authoritative identifier MUST
fail. Submitting a separate correction or concept proposal to the REF
governance workflow MUST remain possible.

**REF-TEST-169:** Rebuilding a lookup index from unchanged managed vocabulary
content MUST retain the vocabulary release identifier and
`expressionCorpusSnapshot`, create a new `lookupIndexManifest`, and create a
new `EnrichmentConfiguration`. Changing selected members, expressions,
relations, or mappings MUST create a new release and expression-corpus
snapshot and invalidate configurations that pin the old content when policy
requires the new release.

**REF-TEST-170:** A candidate-only or read-only lookup consumer MUST fail if it
attempts to reconcile sources, select or activate a release, mint an
authoritative external identifier, or treat rank, similarity, or cache state
as accepted-output authority.

**REF-TEST-171:** Every external distribution and materialized lookup index
used by a managed release or evaluated configuration MUST resolve by immutable
identifier and digest. A mutable filesystem path, URL, or object key without
the pinned artifact and rights records MUST fail. A physical
`lookupIndexManifest` used where an `expressionCorpusSnapshot` is required, or
the reverse, MUST fail.

**REF-TEST-172:** The cross-repository gate MUST read one machine-readable
Rulespec dependency manifest, distinguish tested contract and evidence
revisions, recompute the constraint and conformance-corpus digests, verify
every named generated artifact, and reject stale or contradictory normative
pin text.

**REF-TEST-173:** The combined release-graph gate MUST refuse to issue a
`ReleaseGraphValidationReceipt` for any REF, Rulespec, or cross-boundary
failure. A managed-release consumer MUST reject an absent, caller-fabricated,
stale, digest-mismatched, incompletely covering, or failed receipt and any
bundle whose bytes do not match the externally selected manifest digest.

**REF-TEST-174:** A selected registry or enrichment deployment, and a resolved
reconciliation, MUST fail when its named governance records do not resolve to
one authorized assertion, do not apply to the record's exact derived scope and
time, or do not produce at least `rkaf:localOperationalUse` under the exact
pinned Rulespec L4 runtime. The gate MUST ignore caller-supplied behavior
tests, expected outputs, receipts, and `effective` Booleans. Changing the
graph, governance record, scope, time, behavior input, runtime, or verified
output MUST change the receipt or make it fail.

**REF-TEST-175:** The real-bundle managed-release consumer suite MUST include
one successful candidate-access scenario whose exact selected
`OutputProfile.releasePermissions` row and `EnrichmentProfile` authorize the
release, import snapshot, facet, assignment role, resource route, and candidate
use. A candidate-use request against a minimally valid bundle without selected
candidate-use deployment evidence MUST fail; the bundle may remain available
for exact inspection. The suite MUST also reject, before yielding any
candidate, caller-injected unknown and known-but-nonmatching facets, roles, and
routes; no-match and multiple-match permission selections; and any attempt to
relabel a release-carried row. The successful result MUST preserve the
bundle's exact member, expression, scheme, release, and semantic-field values.
An external lookup-consumer regression MUST prove the same fail-closed
boundary.

**REF-TEST-176:** The managed-release reference-runtime suite MUST prove that
normalized label role and opaque source status survive unchanged into raw
expression access. Exact candidate permission MUST remain necessary
regardless of status. Expressions from a different release or import MUST NOT
enter the candidate view or alter status eligibility for the matching
permission. Raw iteration and exact identifier resolution MUST
retain an expression and member whose pinned Rulespec lifecycle makes the
member a predecessor in deprecation, withdrawal, replacement, split, or
merge, while current-assignment candidate iteration excludes that member.
The suite MUST separately exercise the canonical `deprecated`, `inactive`,
and `withdrawn` source-token exclusions, a single unrecognized opaque token
that neither grants nor independently denies otherwise-authorized access, and
mixed source-status tokens that fail closed for the affected concept. It MUST
also prove that an excluded member remains historically accessible and cannot
receive a new current assignment through the candidate iterator.

**REF-TEST-177:** A source-derived ELSST R5/R6 fixture MUST remain native
`skos:Concept` data, preserve multilingual labels, hierarchy, exact stable and
prior-version links, source status, and replacement links, and pass two
independently sealed complete-membership releases plus the pinned Rulespec JSON
Schema and SHACL gates. Its observed R5-to-R6 replacement MUST carry exact R5
and R6 participant pins. A normalized participant whose absolute concept type
does not match the native graph MUST fail. The fixture MUST retain each
date-only source literal and name the policy used to materialize the required
Rulespec date-time.

**REF-TEST-178:** Managed-release opening MUST fail when an expression,
coverage report, deployment, permission, or normalized row names an absent or
nonmatching import snapshot; when a label role disagrees with its exact SKOS
property; when one lifecycle event repeats a participant role and ordinal; or
when a relation's import or distribution lineage disagrees with either exact
endpoint release.

**REF-TEST-179:** Read-only managed-release identity access MUST return exact
source-authored stable, prior-version, and replacement assertions without
turning them into mappings or lifecycle events. Changing labels MUST NOT alter
those links, and a release member without a source identity assertion MUST
remain explicitly unlinked rather than receiving a label- or URI-derived
identity.

**REF-TEST-180:** A successful exact-byte capture in a managed release MUST
round-trip the byte-identical source artifact through its
`storageReference`. Managed-release creation or opening MUST fail for absent,
changed, digest-mismatched, length-mismatched, symlink-substituted, or
ambiguously resolved source bytes. Two builds whose source, release,
governance, time, parser, policy, or profile identity differs MUST NOT reuse a
durable generated record identifier. A bounded source-derived fixture MUST use
test release identifiers and MUST NOT redefine an official complete-membership
release.

**REF-TEST-181:** A real ELSST R5/R6 managed-release gate MUST validate and
open the complete expression corpus through its aggregate descriptor without
placing every expression digest in the release-graph receipt. Changing,
removing, duplicating, or adding an expression while resealing only the file
descriptor MUST fail the recomputed count or canonical identity digest. The
real-source gate MUST record wall time and peak memory and remain within the
maintained scheduled-test limits.

**REF-TEST-182:** ELSST `owl:deprecated` assertions MUST round-trip with their
exact predicate, lexical form, and `xsd:boolean` datatype. Every true
deprecated member in the selected release MUST remain available by exact
identifier and raw expression access while being absent from
current-assignment candidates. A false value MUST remain eligible when no
other exclusion applies, and a malformed or differently typed value MUST fail
instead of becoming a synthesized `deprecated` token. Only the transitions
observed between the two exact releases may become Rulespec lifecycle events.

**REF-TEST-183:** A `RegistryDeploymentDecision` MUST fail when its applicable
rights-assessment identifier or digest does not match the selected import
snapshot, when it omits an import-adopted policy, or when either field is
absent. Recording a rights assessment elsewhere in the bundle MUST NOT satisfy
the deployment requirement.

**REF-TEST-184:** A mutable-source fixture without publisher-issued row
identifiers MUST include observations with the same name and slug and
observations with empty slugs and MUST prove that their capture-local
identifiers remain distinct. Replacing a parsed or normalized name, label, or
slug while retaining the same exact capture, collection or path, and ordinal
MUST preserve the capture-local observation identifier; changing the capture,
collection or path, or ordinal MUST change it. Duplicate capture-local
locators MUST fail rather than fall back to a name or slug. The fixture MUST
emit no `rkaf:ConceptMapping`, input selection, reconciled release,
synthesized-union authority, or accepted-output authority from those
identifiers or from lexical equality.

**REF-TEST-185:** A source-observation fixture MUST retain zero, one, and
multiple qualified identifiers. The multiple-identifier case MUST include two
different values from one authority and values from different authorities,
each with its own source path and observed or effective time. Reordering the
identifiers MUST NOT change their meaning. Dropping a value, combining values
from separate rows, losing issuer or source evidence, or silently selecting
one identifier as canonical MUST fail. A source IRI and a capture-local record
IRI MUST remain distinct and MUST NOT create concept identity or a
cross-source mapping by themselves.

### 15.3 Evaluation corpus

Evaluation is distinct from schema conformance.

**REF-EVAL-001:** Before automated assignments or inferred relationships enter
an accepted production view, the publisher MUST use a frozen evaluation corpus
with:

- a development set and an untouched holdout;
- time-separated examples;
- source-family and subtype strata;
- record-kind and evidence-depth strata;
- rare, new, cross-domain, and no-fit cases;
- linked versions and renditions kept in the same split;
- independent review;
- frozen source, vocabulary, mapping, model, prompt, and policy versions; and
- a separate privacy-approved sample for participation records, if used.

**REF-EVAL-002:** Source-assigned labels MAY serve as source evidence or silver
labels within their actual scope. They MUST NOT be treated as universal gold
labels.

**REF-EVAL-003:** The implementer of a probabilistic component SHOULD NOT be
the sole owner of its sealed holdout or release decision.

**REF-EVAL-011:** A `SealedGoldManifest` MUST identify:

- its evaluation generation, purpose, split, selection protocol, source,
  corpus, and selection digests, and exact item membership;
- every source-resource, rendition-artifact, source-fragment, source-family,
  subtype, and selection-stratum identifier used by an item, plus that item's
  authoritative seven-dimension partition keys and the source-text,
  indexed-expression-corpus, exact-match-graph, near-duplicate-analysis, and
  computation-receipt evidence used to derive them;
- the exact Rulespec reference-resource releases, REF registry import
  snapshots, mapping releases and snapshots, `EnrichmentProfile`,
  `OutputProfile`, normalization policy, and candidate target universe;
- for each item and applicable facet-and-role pair, the complete expected
  result set or adjudicated minimum and maximum cardinality, valid zero-result
  cases, each registered target and release, directional relationship grade,
  adequacy decision, acceptable open-label, concept-proposal, or abstention
  behavior, forbidden results and wrong-facet outcomes, and supporting
  evidence;
- each reviewer, independent judgment, disagreement, adjudication, exclusion,
  and partition-report reference;
- its sealing time, responsible sealing activity, schema version, and canonical
  payload digest.

The manifest MUST be immutable after sealing. A correction MUST create a new
generation and digest and MUST make affected results from the prior generation
ineligible as release evidence.

**REF-EVAL-012:** Before sealing, the development and holdout partitions MUST
be disjoint by:

- concept identity;
- reviewed `skos:exactMatch` cluster;
- every current or deprecated preferred, alternate, or hidden alias of an
  expected concept;
- source identity;
- artifact digest;
- extracted or normalized text digest; and
- versioned near-duplicate cluster.

Linked source-resource versions and renditions MUST remain in the same split.
The sealed item keys MUST derive from the exact corpus and vocabulary evidence
named by the manifest. The partition report MUST reproduce those keys exactly,
record how every boundary was computed, and include every evidence digest as
an input. A represented concept requires concept-identity and
exact-match-cluster keys; every item requires source, artifact, text, and
near-duplicate keys. Any crossing or missing key invalidates the holdout and
requires a new partition and sealed manifest; removing only the detected
duplicate after results are known does not repair that evaluation generation.
Each preferred, alternate, or hidden label expression for an expected concept
MUST contribute its normalized indexed-text identity to the alias keys,
including expressions retained for deprecated concepts. Acceptable open
labels MUST contribute the same kind of normalized identity. Alias comparison
MUST use the exact normalization policy pinned by the manifest, so Unicode,
case, and whitespace-equivalent forms cannot cross partitions under different
spellings.

**REF-EVAL-013:** Gold expectations MUST be drafted without access to output
from the tagger or configuration under evaluation. Each item MUST receive
judgments from two distinct independent reviewers. A disagreement MUST be
resolved by a third distinct independent adjudicator or the item MUST be
excluded with a recorded reason before sealing. A model output, candidate rank,
prior system decision, or developer preference MUST NOT seed or revise the
sealed target, adequacy, forbidden result, or cardinality fields.

**REF-EVAL-014:** Registered-target relationship grades MUST be exactly
`exact`, `close`, `targetBroaderThanGold`, `targetNarrowerThanGold`, `related`,
`wrong`, or `notRepresented`. The broader and narrower grades describe the
candidate target relative to the intended gold meaning. By default, only
`exact` and independently reviewed `close` targets are adequate; a stricter
profile MAY exclude `close`. Any broader acceptance rule MUST be
preregistered, facet-and-role specific, independently reviewed, and reported
separately from the default measure. `wrong` and `notRepresented` are never
adequate registered targets. A `notRepresented` expectation MUST route the item
to an authorized open label, concept proposal, or abstention and MUST be
excluded from reachable registered-candidate recall denominators while
remaining in target-availability and open-set measures.

### 15.4 Stage-specific measures

**REF-EVAL-010:** Evaluation MUST separate:

- capture and text coverage;
- extraction and optical character recognition quality;
- identity and deterministic-link precision and recall;
- registry coverage;
- candidate recall at declared shortlist sizes;
- final assignment precision and recall;
- target availability and adequacy by `exact`, `close`,
  `targetBroaderThanGold`, `targetNarrowerThanGold`, `related`, `wrong`, and
  `notRepresented`;
- unsupported-assignment rate;
- correct abstention and risk-versus-coverage;
- cross-facet confusion;
- rare, emerging, and time-shifted topics;
- inferred-relation precision by predicate;
- reviewer time, disagreement, and correction rate;
- vocabulary-update stability;
- per-source and per-subtype worst-case performance;
- latency and cost; and
- product outcomes for search, alerts, browse, comparison, timelines, and
  cross-source joins.

**REF-EVAL-004:** A global average or composite score MUST NOT waive a failed
source family, facet, predicate, privacy profile, or high-risk use case.

**REF-EVAL-005:** Candidate recall MUST be evaluated before reranker or
adjudicator quality. A later stage cannot recover a missing candidate.

**REF-EVAL-006:** Correct abstention MUST count as a measured result, not
missing output.

**REF-EVAL-015:** An `EnrichmentEvaluationResult` MUST identify the exact
`EnrichmentConfiguration` identifier and digest; exact `SealedGoldManifest`
identifier and digest; evaluation protocol identifier, version, and digest;
predeclared measures, thresholds, minimum sample sizes, strata, exclusions,
and uncertainty method; observed measures and uncertainty; every stage,
source, subtype, facet, role, predicate, privacy, risk, latency, cost, and
product gate; evaluator, activity, time, and output-artifact digests; and
exactly one verdict: `pass`, `fail`, or `developmentOnly`. A `pass` verdict
requires the predeclared, thresholded, and observed measure identifiers to
form the same one-to-one set; every threshold to pass; every applicable gate
to pass; and every configured stratum to meet its minimum. `atLeast` and
`atMost` compare the threshold with the observed point value. A profile that
gates on a conservative confidence bound MUST predeclare, observe, and
threshold that bound as its own measure. An aggregate score MUST NOT replace
those results.

**REF-EVAL-016:** An evaluation result applies only to the exact configuration
and gold digests it names. Its configuration and sealed gold MUST name the
same enrichment and output profiles, reference-resource releases, registry
import snapshots, mapping releases and snapshots, candidate target universe,
normalization policy, and gold input corpus. A changed implementation,
runtime, model, provider
configuration, prompt, schema, index, indexed label or note corpus,
normalization, candidate channel, fusion or truncation rule, policy, threshold,
budget, registry release, mapping, output profile, or permission tuple MUST
create a new `EnrichmentConfiguration` and a new passing
`EnrichmentEvaluationResult` before production selection. A `fail` or
`developmentOnly` result MUST NOT support a production
`EnrichmentDeploymentDecision`.

### 15.5 Research hypotheses

The following remain hypotheses until the product holdout proves them:

- a low-thousands general subject layer is optimal;
- Federal Register and CRS concepts form the best product core;
- one product overlay improves on serving source schemes separately;
- facet-separated retrieval improves final quality;
- lexical and dense fusion beats either method for every source;
- open phrase generation followed by mapping beats direct assignment;
- metadata priors improve ranking without harmful leakage;
- specialist-module activation improves precision without recall loss;
- hierarchy expansion, definitions, aliases, or generated label text improve a
  given scheme;
- a language model or cross-encoder adds enough value to justify its cost;
- corpus-induced concepts improve user outcomes; and
- controlled concepts improve search, alerts, navigation, joins, or reporting
  enough to justify governance cost.

**REF-EVAL-007:** A production profile MUST keep these choices replaceable and
testable. It MUST NOT present them as conformance facts.

**REF-EVAL-008:** Before evaluation, a production profile MUST publish metric
definitions, thresholds, target universes, minimum sample sizes, uncertainty
or confidence-interval treatment, source and predicate strata, exclusion
rules, and the consequence of failure.

**REF-EVAL-009:** Once holdout results are revealed, that holdout MUST become
audit-only. Any model, mapping, registry, threshold, prompt, policy, or scope
change informed by those results MUST use a newly sealed holdout before a new
independent release claim.

## 16. Binding manifest and interoperability

The REF operational abstract model is normative. Each REF publication release
uses a concrete operational serialization profile and is identified by a
`PublicationReleaseManifest`. Portable semantic records use the serialization
and standards composition defined by the pinned Rulespec release and
[RefSpec Rulespec Application Profile](../profiles/rulespec-application-profile.md).

**REF-INT-004:** REF implementations SHOULD preserve source-native standards
and use Rulespec's standards composition for portable semantics:

| Standard | Ownership |
| --- | --- |
| SKOS, PROV-O, Web Annotation, Dublin Core | Incorporated and constrained by Rulespec; REF does not remap them |
| DCAT 3 | Optional REF release-catalog export |
| W3C Organization Ontology | External organization typing when adopted by the Rulespec profile |
| USLM and Akoma Ntoso | Source-native legal-document structure |

**REF-INT-001:** The application profile MUST document each REF-to-Rulespec
projection, every operational field intentionally not projected, and every
blocked projection awaiting an upstream Rulespec change.

**REF-INT-002:** An export mapping MUST NOT collapse capture,
source-record-revision, source-resource, source-resource-version, and rendition
roles. It MUST preserve Rulespec records as Rulespec records without
re-encoding their origin, evidence, review, authority, lifecycle, access,
retention, or use semantics in REF.

**REF-INT-003:** Source-native structure SHOULD remain authoritative when an
official source supplies it. Interoperability mappings SHOULD supplement, not
replace, that structure.

## 17. References

### 17.1 Normative references

- [RFC 2119 — Key words for use in RFCs to Indicate Requirement Levels](https://www.rfc-editor.org/rfc/rfc2119)
- [RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words](https://www.rfc-editor.org/rfc/rfc8174)
- [RFC 5646 — Tags for Identifying Languages](https://www.rfc-editor.org/rfc/rfc5646)
- [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/)
- [Rulespec](https://github.com/Formspec-Labs/rulespec)
- [RefSpec Rulespec Application Profile](../profiles/rulespec-application-profile.md)
- [RefSpec Core Enrichment Profile](../profiles/enrichment-profile.md)
- [Source and Document Type Matrix, 28 July 2026](../docs/research-inputs.md#normative-portfolio-baseline-for-this-editors-draft), for its enumerated row universe only
- [Source Vocabulary, Ontology, Thesaurus, and Authority Catalog, 28 July 2026](../docs/research-inputs.md#normative-portfolio-baseline-for-this-editors-draft), for its enumerated resource universe only

### 17.2 Informative standards

- [SKOS Simple Knowledge Organization System Reference](https://www.w3.org/TR/skos-reference/)
- [PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/)
- [Web Annotation Data Model](https://www.w3.org/TR/annotation-model/)
- [Data Catalog Vocabulary 3](https://www.w3.org/TR/vocab-dcat-3/)
- [Dublin Core Metadata Terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/)
- [W3C Organization Ontology](https://www.w3.org/TR/vocab-org/)

### 17.3 Research evidence

- [Industry and LLM-era large-label-space tagging](../research/evidence/blind-external-research-recovery-2026-07-28/01-industry-and-llm-era-large-label-space-tagging.md)
- [Extreme multilabel classification](../research/evidence/blind-external-research-recovery-2026-07-28/02-extreme-multilabel-classification.md)
- [Taxonomy induction](../research/evidence/blind-external-research-recovery-2026-07-28/03-taxonomy-induction.md)
- [Label text and embedding geometry](../research/evidence/blind-external-research-recovery-2026-07-28/04-label-text-and-embedding-geometry.md)
- [Controlled-vocabulary scoping](../research/evidence/blind-external-research-recovery-2026-07-28/05-controlled-vocabulary-scoping.md)
- [Source partitioning and metadata priors](../research/evidence/blind-external-research-recovery-2026-07-28/06-source-partitioning-and-metadata-priors.md)
- [US federal controlled vocabularies](../research/evidence/blind-external-research-recovery-2026-07-28/07-us-federal-controlled-vocabularies.md)
- [Corpus-driven vocabulary development](../research/evidence/blind-external-research-recovery-2026-07-28/08-corpus-driven-vocabulary-development.md)
- [When to Abandon a Controlled Vocabulary](../research/evidence/blind-external-research-recovery-2026-07-28/when-to-abandon-controlled-vocabulary-and-federal-vocabulary-inventory.md)

## Appendix A: Example operational and Rulespec records

This informative outline shows the ownership split for an accepted inferred
dependency. Exact Rulespec shapes come only from the pinned release.

```text
REF RelationshipAdjudicationDecision
  id: urn:ref:adjudication:9b31
  candidate: urn:ref:relationship-candidate:9b31
  inputSnapshot: urn:ref:snapshot:2026-07-28
  evidenceCollectionPolicy: urn:ref:evidence-policy:dependency-v2
  outputProfile: urn:ref:output-profile:relationships:v3
  outcome: accepted
  result: urn:rkaf:assertion:9b31
  runReceipt: urn:ref:run:relationship-2026-07-28

Rulespec record set
  rkaf:RelationshipAssertion: urn:rkaf:assertion:9b31
  rkaf:Artifact:              urn:rkaf:artifact:guidance-b-html-sha256
  rkaf:SourceFragment:        urn:rkaf:fragment:guidance-b:p14
  rkaf:EvidenceBinding:       urn:rkaf:evidence-binding:9b31
  rkaf:ExtractionActivity:    urn:rkaf:extraction:9b31
  rkaf:AILineage:             urn:rkaf:ai-lineage:9b31
  rkaf:ConfidenceRecord:      urn:rkaf:confidence:9b31
  rkaf:Attestation:           urn:rkaf:attestation:9b31
  rkaf:LocalAdoption:         urn:rkaf:adoption:9b31
```

The REF record explains the run, policy, and outcome. The Rulespec records
carry the proposition, source regions, derivation, review, and authorization.
Neither record set copies the other's canonical fields.

## Appendix B: Relationship predicate ownership

Relationship predicate IRIs and their definitions, domains, ranges, direction,
inverse, symmetry, transitivity, and temporal meaning belong in the Rulespec
regulatory-evidence profile or an adopted external ontology. The
[RefSpec Rulespec Application Profile](../profiles/rulespec-application-profile.md)
only enumerates and pins the adopted predicates and defines REF candidate
persistence, materiality, review, evaluation, and publication policy. REF does
not duplicate the canonical predicate inventory.

## Appendix C: Requirement index

The requirement prefixes identify the area under test:

| Prefix | Area |
| --- | --- |
| `REF-CONF` | Conformance and extension behavior |
| `REF-BIND` | Rulespec dependency, pinning, and ownership boundary |
| `REF-PORT` | Full-inventory accounting and design coverage |
| `REF-CORE` | Common REF operational records and semantic-boundary rules |
| `REF-CAP` | Capture and completeness |
| `REF-SRC` | Source-record revision and normalization |
| `REF-ART` | Source resources, versions, rendition processing, and Rulespec artifact binding |
| `REF-EVID` | Evidence addressing and Rulespec source-fragment resolution |
| `REF-TYPE` | Operational record-kind routing |
| `REF-SEM` | Semantic-reference candidates |
| `REF-SEMOUT` | Rulespec semantic-result publication |
| `REF-ID`, `REF-VER`, `REF-TIME` | Identity, versions, and time |
| `REF-PROV` | Run receipts and Rulespec provenance linkage |
| `REF-PIPE` | Processing and publication |
| `REF-ENR`, `REF-CAND`, `REF-ACC`, `REF-ASSIGN` | Enrichment |
| `REF-REL`, `REF-SIM`, `REF-DEP`, `REF-PATH`, `REF-ABS` | Relationship workflow, query associations, and bounded absence |
| `REF-THR` | Policy threads |
| `REF-VOC`, `REF-MAP`, `REF-GOV` | Reference-resource import and deployment, mappings, and concept workflow |
| `REF-QRY`, `REF-EXP` | Queries and export |
| `REF-SEC`, `REF-PRIV`, `REF-SAFE`, `REF-RIGHTS` | Privacy, security, and rights |
| `REF-TEST`, `REF-EVAL` | Conformance tests and evaluation |
| `REF-INT` | Interoperability |

# Axiom ecosystem assessment for RefSpec implementations

- **Date:** 2026-07-28
- **Status:** Research assessment and recommendation; dated snapshot, not a permanent vendor assessment
- **Related governance:** The [source vocabulary, ontology, and authority catalog](source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md) keeps Axiom outside the subject pool and governs access, licensing, imports, and external mappings.
- **Decision at the time of assessment:** Adopt no Axiom component for the
  evaluated implementation's initial release. Reconsider
  `axiom-corpus` as a pinned upstream source when its coverage passes a
   source-specific gate. Evaluate `receipt` after the initial implementation
   as an outer signature and custody layer. Borrow narrow parser, verification,
   graph, and user-interface patterns without importing Axiom's application
   stack.
- **Publication note:** This public edition replaces product-specific names,
  identifiers, and source paths with neutral descriptions. The
  substantive Axiom findings and public citations are unchanged.

## Executive verdict

Axiom is relevant to a RefSpec implementation mainly as an adjacent **logic
layer** and as a source of implementation patterns. It does not replace the
regulatory identity, proceeding, lifecycle, evidence, semantic, publication,
or query responsibilities described by RefSpec.

The practical decision is:

1. **Adopt nothing now.**
2. **Watch two components:** `axiom-corpus` for source coverage and `receipt`
   for signing after the initial implementation.
3. **Reuse ideas, not systems:** exact source resolution, source-to-rule reverse
   indexes, proof checks, append-only histories, visible coverage, honest
   incomplete states, and explanation traces.
4. **Keep the text-to-logic seam joinable:** preserve a future mapping from a
   RefSpec regulatory identifier to an Axiom corpus provision and then to an
   executable Axiom RuleSpec concept.

This matches the staged boundary in the
[implementation plan](../plans/implementation-plan.md): source text to
segments, evidence-backed concept assignments, human-attested review, and
atomic Rulespec Level-0 publication over an initial corpus.

## Review scope and confidence

The original investigation divided the organization into three independent
tracks: source repositories, rule and verification repositories, and product
repositories. The review inventoried all **75** public repositories in the
GitHub organization on 2026-07-28:

- 29 were archived.
- 45 repository names began with `rulespec-`.
- Of those 45, 22 were active and 23 were archived.
- The 45 include country and state rule repositories **and** shared tools such
  as old validators, compilers, syntax packages, and the graph viewer. They are
  not 45 independent ontology implementations.

Decision-critical findings below were rechecked against the named repository
heads and, where relevant, Axiom's live public Supabase surface. Live service
and GitHub Actions observations can change; each such claim includes its
observation date.

## Ranked verdict

| Disposition | Repositories | Practical value and boundary |
| --- | --- | --- |
| **Reconsider later** | [`axiom-corpus`](https://github.com/TheAxiomFoundation/axiom-corpus) | Best potential upstream source for full statute, regulation, manual, policy, and guidance text. Its signed, immutable release design is strong. It does not replace RefSpec identities, regulatory-proceeding joins, semantic tables, or exact evidence model. Consume a pinned release through a small JSONL reader only after source-specific coverage and reproducibility gates pass. |
| **Watch after the initial implementation** | [`receipt`](https://github.com/TheAxiomFoundation/receipt) | Could sign, timestamp, and append-chain an already validated implementation run receipt. It cannot replace an implementation's domain-specific receipt or recomputation checks. The package remains incomplete and requires Python 3.11 or later. |
| **Learn from; selectively adapt** | [`axiom-scrapers`](https://github.com/TheAxiomFoundation/axiom-scrapers), [`axiom-bills`](https://github.com/TheAxiomFoundation/axiom-bills) | Useful state-source parsers, fixtures, compound bill identity, append-only action fingerprints, monotonic status handling, bill versions, and input hashes. Adopt individual techniques or a thin source adapter; do not adopt either runner unchanged. |
| **Learn from; do not import** | [`axiom-encode`](https://github.com/TheAxiomFoundation/axiom-encode), [`axiom-oracles`](https://github.com/TheAxiomFoundation/axiom-oracles), [`axiom-compose`](https://github.com/TheAxiomFoundation/axiom-compose), [`rulespec-us`](https://github.com/TheAxiomFoundation/rulespec-us) | Strong patterns for immutable source resolution, temporary validation checkouts, provision-to-rule reverse indexes, proof requirements, companion tests, precise comparison predicates, and shrink-only known-gap lists. Their code and data models depend on Axiom's executable-policy system. |
| **Not substitutes** | [`axiom-rules-engine`](https://github.com/TheAxiomFoundation/axiom-rules-engine) and the executable `rulespec-*` repositories | A separate executable YAML language and calculation system. It does not implement the Rulespec/RKAF vocabulary and validation stack profiled by RefSpec. |
| **User-interface references** | [`axiom-foundation.org`](https://github.com/TheAxiomFoundation/axiom-foundation.org), [`finbot-snap-demo`](https://github.com/TheAxiomFoundation/finbot-snap-demo), [`encodebench.org`](https://github.com/TheAxiomFoundation/encodebench.org), [`dashboard-builder`](https://github.com/TheAxiomFoundation/dashboard-builder) | Useful patterns include direct-citation-first results, visible evidence and coverage, honest incomplete states, output-first workflows, and limitation-forward evaluation reports. The applications themselves are young and tied to Axiom APIs and benefit calculations. |
| **No current replacement value** | [`axiom-mcp`](https://github.com/TheAxiomFoundation/axiom-mcp), [`axiom-local`](https://github.com/TheAxiomFoundation/axiom-local), [`rulespec-graph-viewer`](https://github.com/TheAxiomFoundation/rulespec-graph-viewer), [`axiom-microsim`](https://github.com/TheAxiomFoundation/axiom-microsim) | These components depend on Axiom's hosted API, executable legal IDs, WebAssembly packages, or benefit-engine data. The evaluated implementation already had an appropriate read-only DuckDB and FastMCP boundary for heterogeneous regulatory data. |
| **Ignore** | [`statute-graph`](https://github.com/TheAxiomFoundation/statute-graph), [`akomize`](https://github.com/TheAxiomFoundation/akomize), old compiler and validator repositories, and archived state repositories | Superseded or incomplete experiments. Useful ideas now appear in active repositories. |

## The fundamental mismatch

The two projects answer different questions.

| System | Primary question | Main objects |
| --- | --- | --- |
| **RefSpec** | What regulatory activity, authority, subject, and evidence connect to this rulemaking? | Artifacts, dockets, proceedings, agenda items and observations, comment periods, CFR and U.S.C. identifiers, concepts, assignments, assertions, confidence, and lineage |
| **Axiom corpus and reader** | What does this legal provision say, where does it sit in the source hierarchy, and what does it cite? | Provisions, parent and child paths, citation spans, source files, and provision references |
| **Axiom RuleSpec and runtime** | How do facts and legal parameters compute an outcome? | Executable modules, inputs, outputs, data relations, formulas, effective versions, calculation dependencies, traces, and certificates |
| **Rulespec/RKAF profiled by RefSpec** | What standing, authority, provenance, and permitted use does a claim have? | Vocabulary terms and validation rules for source identity, authority, lifecycle, evidence, assertions, and use |

Axiom RuleSpec and the Rulespec/RKAF work profiled by RefSpec share a name,
not a format or runtime:

- Axiom requires `format: rulespec/v1` YAML with parameters, derived rules,
  formulas, inputs, relations, and calculation traces.
- The sibling Rulespec project defines identifiers, CUE constraints, and
  JSON-LD-facing semantics. The evaluated implementation published its
  Level-0 mapping as flat Parquet rows that use those identifiers.
- The inspected Axiom rule repositories do not parse or validate the RefSpec
  application profile. They therefore do not qualify as an independent
  consumer of that Rulespec mapping.

## What Axiom's graph and ontology actually contain

Axiom has several linked graph-shaped models. It does not have one unified
ontology that powers the reader.

```text
official source
    |
    v
Provision tree -------------------- cites --------------------> Provision
    |                                                           or unresolved path
    | corpus_citation_path / generated reverse index
    v
Axiom RuleSpec module
    |
    +-- input concepts
    +-- parameter and derived output concepts
    +-- data and derived relations
    +-- source_relation records
    |
    v
Runtime dependency graph
    +-- rule dependency
    +-- input dependency
    +-- relation dependency
    +-- calculation trace and certification status
```

### 1. Legal-source tree

`axiom-corpus` normalizes statutes, regulations, policies, guidance, and other
source material into provisions. Each provision records its jurisdiction,
document class, `citation_path`, parent path and identity, heading, body text,
source metadata, and version. The reader uses a separate
[`navigation_nodes`](https://github.com/TheAxiomFoundation/axiom-corpus/blob/10142cb0f07403c2de4599c76bec01e96640fda9/supabase/migrations/20260505120000_corpus_navigation_nodes.sql)
index for fast parent and child navigation. The migration explicitly keeps
`corpus.provisions` as the legal-text source of truth.

This is a document hierarchy, not a semantic class hierarchy.

### 2. Citation graph

Axiom explicitly calls
[`corpus.provision_references`](https://github.com/TheAxiomFoundation/axiom-corpus/blob/10142cb0f07403c2de4599c76bec01e96640fda9/docs/rule-references.md)
its citation graph. Each edge records:

- source provision;
- target citation path and, when ingested, target provision;
- citation text;
- pattern type;
- character offsets in the source body; and
- confidence.

The reader uses these edges for inline links and incoming-reference panels.
Encoding tools use outgoing citations only as **candidate** RuleSpec imports.
The citation edge does not by itself prove a specific executable dependency.

### 3. Executable concept registry

The
[`axiom-corpus` concept registry](https://github.com/TheAxiomFoundation/axiom-corpus/blob/10142cb0f07403c2de4599c76bec01e96640fda9/docs/concept-registry.md)
is a generated, flat vocabulary of RuleSpec inputs and outputs. A stable concept
identifier combines the legal module path with a fragment:

```text
us:statutes/42/1396a/a/10#is_medicaid_eligible
us:statutes/7/2014/d#input.person_age
```

Output entries can record fields such as `entity`, `dtype`, `unit`, `period`,
defining modules, occurrence counts, and mappings to PolicyEngine or another
calculation engine. The registry documents important limits:

- it is read-only and not yet an enforcement boundary;
- it does not resolve canonical names or block synonyms;
- it does not infer most input types; and
- it does not identify equivalent concepts across jurisdictions.

This is closer to a compiler symbol table than to RefSpec's descriptive
concept model.

### 4. Runtime dependency graph

The interactive graph viewer consumes a
[`ProgramGraph`](https://github.com/TheAxiomFoundation/axiom-foundation.org/blob/2a6655823522d8053d655ab76a3229b2a99692e5/src/components/axiom/graph-viewer/types.ts)
containing `RuleNode`, `InputNode`, and `RelationNode` objects. Each rule lists
`ruleDeps`, `inputDeps`, and `relationDeps`, along with its formula, legal
source, certification status, and fields such as `entity`, `dtype`, `unit`, and
`period`.

The application obtains this graph from the Axiom runtime's compiled-package
subgraph endpoint or composes it on demand from mirrored encodings. It does not
render the Supabase citation graph as the calculation graph.

For example, the SNAP rule
`snap_standard_income_eligible` depends on separate gross- and net-income
eligibility rules. The graph shows that computation path and can attach values
to it during an execution trace.

### 5. Legal and provenance relations

The rules engine's
[`concept-naming` model](https://github.com/TheAxiomFoundation/axiom-rules-engine/blob/c4b62bdb740d4149f0872783964f917e74cffe42/docs/concept-naming.md)
also defines `source_relation` records with a small relation vocabulary:

```text
defines
delegates
implements
sets
amends
restates
cites
```

These records describe legal or provenance relationships. They are distinct
from runtime data relations such as `member_of_household`. A real
[`rulespec-us` module](https://github.com/TheAxiomFoundation/rulespec-us/blob/c13cdf7dda5948e7a86ff0c317872f93743a2084/us/regulations/7-cfr/273/9.yaml#L75-L81)
records that federal law delegates a utility-allowance choice to another
executable concept.

This relation vocabulary is worth studying. A RefSpec implementation should
adopt it only through an explicit semantic crosswalk that preserves source
evidence, direction, scope, and confidence.

### 6. How the reader joins these layers

The reader assembles a page from several sources:

1. provision rows and their descendant tree;
2. the navigation index;
3. outgoing and incoming citation edges;
4. the RuleSpec encoding linked to the provision;
5. generated provision-to-rule indexes;
6. runtime coverage and external-oracle results; and
7. a compiled or on-demand calculation graph.

The
[`section-page` assembler](https://github.com/TheAxiomFoundation/axiom-foundation.org/blob/2a6655823522d8053d655ab76a3229b2a99692e5/src/lib/axiom/section-page.ts#L238-L342)
maps executable rules to displayed subsections partly by parsing each rule's
`source` citation with regular expressions. It treats the repository file path
as authoritative when that parsing fails. This is a pragmatic reader join, not
ontology reasoning.

The approach suggests a useful pattern for RefSpec implementations:

> Keep legal text, citations, descriptive metadata, executable logic, and
> verification separate; join them through stable identifiers and show the
> status of each layer.

In practical terms:

> Axiom has a legal document index, citation graph, typed RuleSpec symbol table,
> and executable dependency graph. It is closer to a compiler model for law
> than a broad regulatory knowledge ontology.

This differs from the
[RefSpec framework](../spec/refspec.md), which models regulatory artifacts,
dockets, proceedings, agenda items, comment periods, authority, descriptive
concepts, assignments, evidence, confidence, and lineage. Axiom primarily
answers, “How does this provision compute an outcome?” RefSpec answers, “What
regulatory activity, authority, subject, and evidence connect to this record?”

A RefSpec implementation can borrow Axiom's provision reader, citation-span
model, stable legal identifiers, and calculation-graph patterns. It should not
substitute Axiom's model for the RefSpec evidence and semantic model.

## Detailed repository findings

### `axiom-corpus`: strongest future source candidate

**Potential use:** pinned upstream legal text.

The repository's
[`named-release-publication`](https://github.com/TheAxiomFoundation/axiom-corpus/blob/10142cb0f07403c2de4599c76bec01e96640fda9/docs/named-release-publication.md)
design is strong. A release binds exact scopes, source paths, bytes, SHA-256
digests, row counts, projection digests, a Git commit, immutable
content-addressed storage keys, readback evidence, and an Ed25519 signature.
Activation is a separate approved operation.

Three limits block adoption now:

1. **Target coverage is unproved.** On 2026-07-28, exact live
   `current_provisions` queries for `us/regulation/40/60` and
   `us/statute/42/7401` returned no rows. Indexed child lookups under both paths
   also returned no rows. Broader prefix scans timed out, so this observation
   does not prove that every descendant is absent; it proves that Axiom cannot
   yet satisfy the evaluation's two exact acceptance queries through the public reader
   boundary. The current
   [`provisions_to_rules` reverse index](https://github.com/TheAxiomFoundation/rulespec-us/blob/c13cdf7dda5948e7a86ff0c317872f93743a2084/.axiom/index/provisions_to_rules.json)
   contains 4,240 provision paths but no path beginning with either target.
2. **Historical retrieval remains incomplete.** The repository's
   [`historical-versioning`](https://github.com/TheAxiomFoundation/axiom-corpus/blob/10142cb0f07403c2de4599c76bec01e96640fda9/docs/historical-versioning.md)
   document says `as_of` works for eCFR but is ignored by other storage and
   source paths. Named immutable releases improve snapshot custody, but they do
   not establish complete point-in-time legal-text semantics for every source.
3. **Direct package adoption conflicted with the evaluated implementation's
   runtime.**
   [`pyproject.toml`](https://github.com/TheAxiomFoundation/axiom-corpus/blob/10142cb0f07403c2de4599c76bec01e96640fda9/pyproject.toml)
   requires exactly Python 3.14. The evaluated implementation supported
   Python 3.10.

If coverage later passes, use an isolated Axiom environment to resolve and
verify a named release. Feed its pinned JSONL into a small project-owned
reader. Preserve Axiom's release identity and source hashes in the
implementation receipt without replacing RefSpec identities or tables.

### `receipt`: useful outer custody layer after the initial implementation

**Potential use:** sign and chain a completed, independently validated
implementation receipt.

The repository has working primitives for canonical JSON, append-only release
chains, Ed25519 signatures, threshold keyrings, timestamp witnesses, and
workflow attestations. It cannot replace the evaluated pipeline's
domain-specific receipt, which records and rechecks inputs, work, outputs,
failures, and quality gates.

The package is not ready for current adoption:

- [`pyproject.toml`](https://github.com/TheAxiomFoundation/receipt/blob/d9f7e28170abf71ebfcc8ec468ee1b3edee575fc/pyproject.toml)
  requires Python 3.11 or later and still classifies the package as planning.
- The
  [`README`](https://github.com/TheAxiomFoundation/receipt/blob/d9f7e28170abf71ebfcc8ec468ee1b3edee575fc/README.md)
  lists a waiver ratchet, chronology tiers, and `receipt verify`.
- The package's
  [`__init__.py`](https://github.com/TheAxiomFoundation/receipt/blob/d9f7e28170abf71ebfcc8ec468ee1b3edee575fc/src/receipt/__init__.py#L3-L16)
  identifies those same capabilities as pending extraction.

Revisit after the initial implementation. Validate the domain run first, then
pass its immutable receipt to the outer signing layer. Test tampering,
truncation, key rotation, threshold changes, unavailable timestamp witnesses,
and offline verification.

### `axiom-scrapers`: parser reference, not runner

**Potential use:** individual state-source parsing research and fixtures.

The runner conflicts with the fail-closed and exact-source requirements used
in this assessment.
Its
[`_parse_and_write`](https://github.com/TheAxiomFoundation/axiom-scrapers/blob/da5d6517ffc948c0a0c34291deb5804aeada5e03/src/axiom_scrapers/_common/base.py#L226-L246)
method converts any parser exception into a warning and skipped count, then
continues. It writes rendered text and metadata rather than establishing a
general byte-for-byte source custody boundary.

Consult a source-specific parser when a RefSpec implementation adds that
jurisdiction. Port only the narrow parsing logic and fixtures behind the
implementation's own reader, source snapshot, explicit failure, and receipt
interfaces.

### `axiom-bills`: strong patterns, premature dependency

**Potential use:** state-bill adapter after the initial implementation.

The useful patterns are concrete:

- compound identity by jurisdiction, session, chamber, and bill number;
- append-only action rows keyed by SHA-256 fingerprints;
- a monotonic status order that prevents later out-of-order actions from
  reversing progress;
- distinct bill text versions;
- source-operation and source-text hashes for generated rule variants; and
- per-jurisdiction status vocabularies and tests.

The implementation remains a prototype. Its README simultaneously describes
many jurisdictions as fully implemented and later says only federal and New
York work end to end. On 2026-07-28, the three most recent completed state
refreshes had failed. The federal scraper also
[`returns no bill`](https://github.com/TheAxiomFoundation/axiom-bills/blob/e99ff437c66f6004b62b53aaf1dd858f911e1aad/packages/scrapers/src/axiom_bills/jurisdictions/us_federal/bill/scrape.py#L194-L205)
when detail retrieval raises and
[`omits text versions`](https://github.com/TheAxiomFoundation/axiom-bills/blob/e99ff437c66f6004b62b53aaf1dd858f911e1aad/packages/scrapers/src/axiom_bills/jurisdictions/us_federal/bill/scrape.py#L255-L271)
when that request raises. Those paths do not meet the explicit-completeness
standard used in this assessment.

For the evaluated implementation, retain its existing Congress.gov reader.
Before implementing state bills, decide whether Axiom can provide a
release-quality feed or whether the implementation should adapt selected state
parsers. State bills remain outside the initial implementation scope.

### Encoding, proof, and comparison repositories

`axiom-encode`, `axiom-oracles`, `axiom-compose`, and `rulespec-us` offer the
most reusable engineering ideas:

- resolve exact immutable source text before a model call;
- bind encodings to a corpus citation path and source hash;
- carry proof atoms with exact source excerpts;
- generate a reverse index from source provisions to dependent rules;
- validate in temporary checkouts before modifying the destination;
- keep companion tests beside executable rules;
- define success and comparison tolerances precisely; and
- make known-gap lists shrink-only.

These ideas fit RefSpec's evidence and receipt discipline. Their
implementations do not: they assume Axiom RuleSpec modules, legal IDs, formula
compilation, benefit-engine entities, and Axiom runtime packages.

### Product and user-interface repositories

The product repositories provide five immediate lessons:

1. **Show exact citations first.** Separate an exact identifier match from a
   broader text or semantic match.
2. **Show why a result appears.** Display the source span, relationship, and
   inclusion reason beside the result.
3. **Make coverage countable.** The Axiom reader shows encoded subsections over
   total subsections. It awards “verified” only for an external-oracle
   comparison, not for a self-authored expected value.
4. **Publish incomplete states honestly.** `finbot-snap-demo` exposes
   `acknowledged_incomplete` and refuses to invent a result for an unencoded
   program.
5. **Start from the desired output.** `dashboard-builder` lets a user select
   outputs and then the inputs needed to compute them.

Apply these ideas through an implementation's existing evidence and review
infrastructure. Do not add an Axiom database, API, graph service, or MCP server
solely to obtain them.

### MCP, local execution, graph viewer, and microsimulation

These repositories solve Axiom-specific delivery problems:

- `axiom-mcp` is explicitly a thin adapter over the hosted Axiom Rule API.
- `rulespec-graph-viewer` loads runtime-package graphs from that API.
- `axiom-local` vendors Axiom's WebAssembly engine and executable corpus.
- `axiom-microsim` projects population data into Axiom benefit programs.

Useful patterns include capability discovery, narrow permissions, structured
errors, pinned artifacts, local private computation, and trace displays. None
replaces the evaluated implementation's DuckDB queries, FastMCP resources,
source relationships, or regulatory model.

## Recommended next actions

### 1. Keep the evaluated initial implementation unchanged

Do not add Axiom dependencies, signed release chains, state bills, a graph
database, or new MCP tools to the evaluated initial implementation. Finish and
verify its source, segment, concept, review, and publication path.

### 2. Apply the reader lessons through existing infrastructure

When a conforming implementation can answer the 40 CFR 60 and 42 U.S.C. 7401
queries, render a small evidence-first result view that shows:

- exact identifier matches before broader matches;
- result type and inclusion reason;
- exact supporting evidence;
- source snapshot and query version; and
- complete, incomplete, blocked, or unverified status.

### 3. Define the `axiom-corpus` adoption gate now

Reopen the source decision only when an immutable named release contains a
source that a RefSpec implementation needs. Accept that release only when:

1. maintainer, release, access, license, and redistribution rights pass the
   [catalog's adoption gates](source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md#adoption-gates);
2. exact and descendant coverage passes for the named target;
3. every normalized row resolves to a retained official source artifact;
4. source bytes, hashes, release identity, and extraction metadata survive the
   adapter;
5. two isolated reads produce byte-identical implementation inputs;
6. failed, skipped, unresolved, and truncated records remain explicit;
7. existing RefSpec identifiers and joins remain unchanged; and
8. the implementation receipt records the Axiom release and adapter versions.

### 4. Evaluate `receipt` after the initial implementation

Keep the layers ordered:

```text
run conforming pipeline
    -> recompute and validate implementation receipt
        -> sign and append-chain that immutable result
            -> verify the outer chain offline
```

Do not let the outer signature turn a failed or incomplete domain receipt into
a successful one.

### 5. Preserve a future text-to-logic adapter

A useful later seam is:

```text
urn:rkaf:us:cfr:7:273.9
        |
        | identifier crosswalk
        v
us/regulation/7/273/9
        |
        | source verification through
        | corpus_citation_path / reverse index
        v
us:regulations/7-cfr/273/9#snap_standard_income_eligible
```

The adapter must preserve the difference between:

- a regulatory artifact or CFR subject in RefSpec;
- an Axiom source provision;
- a citation edge;
- an executable rule concept;
- a calculation dependency; and
- a verified or merely encoded result.

Do not collapse these into one generic graph edge.

## Final decision

Repository-name similarity overstates architectural compatibility. Axiom's
active stack is valuable because it models legal text, citations, executable
rules, dependency graphs, and calculation evidence with unusual discipline.
RefSpec models the surrounding regulatory record and its provenance.

The projects should meet through narrow, versioned adapters:

- Axiom may later supply verified source text.
- A RefSpec implementation may supply regulatory context and evidence-backed
  change signals.
- Axiom's reverse index may connect provisions to executable rules.
- A future outer receipt may sign an already valid implementation output.

For the initial implementation assessed here, **adopt nothing, monitor two
repositories, and borrow the best patterns**.

## Repository heads inspected

| Repository | Head inspected |
| --- | --- |
| `axiom-corpus` | [`10142cb`](https://github.com/TheAxiomFoundation/axiom-corpus/commit/10142cb0f07403c2de4599c76bec01e96640fda9) |
| `receipt` | [`d9f7e28`](https://github.com/TheAxiomFoundation/receipt/commit/d9f7e28170abf71ebfcc8ec468ee1b3edee575fc) |
| `axiom-scrapers` | [`da5d651`](https://github.com/TheAxiomFoundation/axiom-scrapers/commit/da5d6517ffc948c0a0c34291deb5804aeada5e03) |
| `axiom-bills` | [`e99ff43`](https://github.com/TheAxiomFoundation/axiom-bills/commit/e99ff437c66f6004b62b53aaf1dd858f911e1aad) |
| `axiom-encode` | [`6ef7c14`](https://github.com/TheAxiomFoundation/axiom-encode/commit/6ef7c14e6e233a4f5ad04172a2603c76813d029c) |
| `axiom-oracles` | [`1b57aff`](https://github.com/TheAxiomFoundation/axiom-oracles/commit/1b57affd55eeaf765ac33c18645df2253a51d3d8) |
| `axiom-compose` | [`9a514ac`](https://github.com/TheAxiomFoundation/axiom-compose/commit/9a514aca29c85a4a5f30a63f2275f9a362dd2b7a) |
| `rulespec-us` | [`c13cdf7`](https://github.com/TheAxiomFoundation/rulespec-us/commit/c13cdf7dda5948e7a86ff0c317872f93743a2084) |
| `axiom-rules-engine` | [`c4b62bd`](https://github.com/TheAxiomFoundation/axiom-rules-engine/commit/c4b62bdb740d4149f0872783964f917e74cffe42) |
| `axiom-foundation.org` | [`2a66558`](https://github.com/TheAxiomFoundation/axiom-foundation.org/commit/2a6655823522d8053d655ab76a3229b2a99692e5) |
| `finbot-snap-demo` | [`ba247bb`](https://github.com/TheAxiomFoundation/finbot-snap-demo/commit/ba247bb6b28a9390775f6e13df46229469652799) |
| `encodebench.org` | [`9b79301`](https://github.com/TheAxiomFoundation/encodebench.org/commit/9b7930180d356614208a1bf665f0e20ab3d0b22d) |
| `dashboard-builder` | [`8846112`](https://github.com/TheAxiomFoundation/dashboard-builder/commit/884611285b8becfb83f6c9a7902fe593fedfa719) |
| `axiom-mcp` | [`b1f6e7d`](https://github.com/TheAxiomFoundation/axiom-mcp/commit/b1f6e7d34b752334e55d3c79c4a25d2cdaf4ac1d) |
| `axiom-local` | [`3541784`](https://github.com/TheAxiomFoundation/axiom-local/commit/35417843bcdcefc98aafd33f11f2b23fb3dcb71a) |
| `rulespec-graph-viewer` | [`958b10a`](https://github.com/TheAxiomFoundation/rulespec-graph-viewer/commit/958b10ae8d4185ddde3030710ee9553a12b62ba1) |
| `axiom-microsim` | [`c1b6f9c`](https://github.com/TheAxiomFoundation/axiom-microsim/commit/c1b6f9c3d45f50d6b931134ada576ec2adb797ca) |

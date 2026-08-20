# Abandoned good ideas across the four repos

Survey date 2026-08-20. Six parallel sweeps (spicy-regs, spicysearch, RefSpec
prose, RefSpec code, cross-repo git history, rulespec + DocSpec) plus direct
measurement and verification.

Lens: not a bug hunt and not a TODO list. The question asked of every
candidate was *"someone was onto something here — what was it?"*

Every load-bearing claim below was verified independently: files opened,
commits inspected, greps re-run, tests and tools executed. Where a sweep's
claim did not survive checking, that is recorded.

## The pattern

Almost nothing found is *unfinished*. The recurring shape is **finished work
sitting one wire short of being used** — a complete vertical slice built
ahead of the thing that would exercise it, then parked and forgotten. Several
items are blocked on conditions that have since been satisfied without anyone
noticing.

---

## 1. The same idea, built four times, running zero times

Four separate repos independently concluded that *absent* and *checked, found
nothing* must not collapse into one state. All four implementations are inert.

| repo | artifact | state |
|---|---|---|
| RefSpec | concept-lifecycle system (rename/split/merge/retire) | build **asserts** it stays at 0 |
| RuleSpec | `rkaf-analysis` — 788-line spec, 6 generated Rust types | **0** runtime consumers |
| spicy-regs | `ClosureClaim` / longitudinal omission design | designed, **0** code |
| DocSpec | negative-evidence segmentation ledger | in an archive marked `runtimeAuthority: excluded` |

**RefSpec's half.** A complete rename/split/merge/retire event model —
per-event cardinality (rename 1→1, split 1→N, merge N→1, retire N→0),
mandatory `reviewedBy`/`reviewedAt`, evidence citations, a validator pass, a
Parquet role, and explorer UI distinguishing *superseded* (via a statement's
`supersedesAssertion`) from *rescinded* (via a `rkaf:rescission` event).
Schema → governance → validator → UI, the whole slice.

It has never fired. The only production call site never passes
`lifecycle_records`, and the build enforces this at
`tools/generate_atlas_v3_full.py:4207`:

```python
if actual["lifecycleEvents"]:
    raise ValueError("expected lifecycleEvents=0, declared=...")
```

Verified: `lifecycle-events.parquet` is 0 rows in the 2026-08-20 seal.

**RuleSpec's half** goes further. `spec/rkaf-analysis.md` (788 lines) plus six
generated types — `RelationChangeEvent`, `RelationComparisonContext`,
`RelationFinding`, `ResolverProofRecord`, `ClosureClaim`,
`MachineAdjudication` — already compiled to Rust, JSON Schema, SHACL and
TypeScript, round-trip tested. Verified: **zero** files under
`crates/rkaf-runtime/src/` reference any of the five.

Its argument is the one RefSpec's lifecycle system encodes:

> "Recording that as a denied assertion destroys the distinction between
> *this was never true* and *this stopped being true* — the distinction every
> later comparison depends on."

And it separates five comparison outcomes where most systems collapse to a
boolean: `satisfied`, `affirmedDeniedDiscrepancy`, `conflict`,
`notComparable` (a gate **failed**), `unknown` (a gate **could not decide**).

It also states REF-035's own discipline independently, in a different repo
and a different language: **`gateUnknown` never becomes `gateFail`** — the
same "no weaker predicate can be rewritten to a stronger one" rule.

**Why this matters now.** The current branch is
`atlas-v3-binding-and-relation-research`. That contract is an import away.

---

## 2. Blockers that already cleared, and nobody noticed

The most valuable category in the survey: work correctly parked on a stated
condition, where the condition has since been met.

### 2a. The ANN rejection's revisit trigger fired in the same commit that wrote it

`src/spicy_regs/ontology/ann_index.py` (433 lines) is a complete,
digest-pinned USearch/HNSW wrapper, rejected the day it was built for a
well-measured reason: the true top-50 nearest concepts for a real query sit
inside a **0.056-wide cosine band**, leaving HNSW's greedy descent almost no
gradient — structurally, regardless of library.

The rejection's own revisit trigger says it reopens only after a healthier
concept-embedding space lands. **Verified: commit `90a76fd` touches both**
`docs/evidence/usearch-ann-benchmark-2026-07-28.md` (+115) *and*
`src/spicy_regs/ontology/candidate_channels.py` (+265), which introduces
`CONCEPT_EMBEDDING_TEXT_V2 = "concept-embedding-text-v2-boilerplate-free"` —
the boilerplate-free embedding rule that was the stated precondition.

The condition was satisfied by the same commit that recorded the rejection.
The benchmark has never been re-run. **Cost: about an hour** — the harness
exists.

*(Aside: that commit's message is "strip fabricated citations and correct the
separation metric" — four fabricated citation blocks were removed from the
evidence file. This project catches fabrication in its own record repeatedly,
which is why its evidence is worth trusting.)*

### 2b. Two finished auditor readers for gaps the repo still declares open

`bindings/atlas/3.1/tests/registry-descriptors.nq` still carries
`"consumability":"inventoryOnly"` and an explicit `"gap"` field for
`opm-plum-position-status-codes` and `cbo-publication-identifiers` (115 gap
entries in total). Verified: `tools/verify_atlas_source_fidelity.py` on main
(1.0 MB, 56 readers) contains **zero** mentions of either.

Two unmerged commits already implement them:

| commit | adds | tests |
|---|---|---|
| `22edee5a` "audit tabular registry sources" | `_read_opm_plum_csv`, `_read_naics_psc_xlsx`, `_read_treasury_fast_book_xlsx`, `_read_nppes_csv`, `_read_opm_ehri_xlsx` | +514 lines |
| `aa113fe4` "compare pinned publisher row lists" | `_read_cbo_publication_source_list`, `_read_html_table_source_list`, `_read_markdown_source_list` | +138 lines |

Verified by direct count: 20 "plum" mentions in `22edee5a`, 14 "cbo" in
`aa113fe4`, **0 of either on main**. `plans/validation-cost-reset-plan.md`
already logs them as "wip, NOT resumed."

**Cost: hours.** The cheapest, lowest-risk win in the survey.

### 2c. A 3.5-second validation gate that was never wired in, and rotted

`src/refspec/atlas/parquet_preflight.py` (624 lines) re-expresses the
expensive SHACL/RDF validation as vectorized PyArrow checks. It ships a
console script (`refspec-validate-atlas-parquet`) and has a test — and
appears in **no Makefile target**.

Run against the sealed 2026-08-20 distribution it completes in **3.5
seconds**, then fails — on its own staleness:

```
expected=[EvidenceBinding, Identifier, Label, LifecycleEvent, Release,
          Resource, SourceRecord, Statement]
actual  =[... + agencyProjection, agencyProjectionUnresolved,
          derivedRelations]
```

It predates the three optional members. Patching the role set in scratch and
re-running surfaces the same root cause a second time in count
reconciliation. Never wiring it in did not merely leave it idle — it let it
fall behind the artifact it validates. **Cost: about an hour**, one concept.

---

## 3. Complete engines with no callers

- **`spicy_regs/docpipeline/retrieval.py`** — 5,479 lines: dense BGE +
  learned-sparse retrieval, RRF at k=60, fixed-depth cross-encoder reranking,
  checkpointed and resumable. Every sibling pipeline stage has production
  callers; this one has **zero non-test callers**. Meanwhile
  `corpora/segmentation_sparse_retrieval.py` re-derives RRF from scratch for
  one-off runs. Parked because "retrieval serving" was cut from MVP
  (`docs/decisions.md:129`), not because it failed.
- **`spicysearch/known_items.py`** (250 lines) — builds gold test cases with
  no human or LLM judge: draw a verbatim span from a row's own text, prove
  uniqueness by intersecting *interior*-token posting lists (never the mutable
  first/last token), emit three query forms, byte-reproducible from a seed.
  Verified orphan: referenced only by its own test.
  `validation/metadata_relevance.py`, which scores the shipping engine, never
  imports it.
- **`spicy_regs/enrichment/open_set.py`** (241 lines) — a genuine third tier
  between reject and accept: when a document mentions something the registry
  lacks, emit a source-grounded `rkaf:openLabel` with four digest checks and
  an offset-containment proof, tagged `searchOnly` / `accepted_output=False`.
  Zero non-test callers; blocked on a review that never happened.
- **`ManagedVocabularyBundle`** — exported as the standard packaging path,
  while the two real pipelines hand-roll their own
  `_json_bytes`/`_sha256_bytes`/`_seal`. Not merely underused — actively
  reinvented in parallel.

---

## 4. Designs worth more than their verdicts

- **`spicysearch/docs/ranking-v4-design.md`** — 73 KB, "**Not implemented**",
  no trace in `src/` (verified). Proves in closed form that the current
  ranking key encodes **rank, never margin**: RRF makes the rank-1→rank-2 step
  a fixed `0.08/62 = 0.00129` however much better rank 1 actually is. So a
  prior modifier's safe window (`w < 0.00129`) and useful window
  (`w ≳ 0.0071`) are **disjoint by 5.5×** — no constant can be both. The fix
  sorts into score-proximity *bands* before any modifier runs, with a one-line
  invariant guaranteeing no bounded modifier can move a document across a
  band: "a modifier may reorder documents whose evidence could not
  distinguish them, and never anything else."
- **The hyperbolic subsumption prototype** (`tools/prototype_hyperbolic_subsumption.py`,
  1,068 lines) — failed cleanly; every checkpoint lost to a trivial "always
  broader" predictor. What survives is the *apparatus*: a threshold-free
  direction probe separating "does the geometry know which concept is more
  general" from "does the calibrated threshold transfer"; a norm-gap-transfer
  diagnostic pinpointing *which term* in the scoring formula breaks on domain
  data (depth-gap collapses 7.47→1.33 vs WordNet while raw distance transfers
  fine); split-half calibration plus an oracle upper bound; and a hermetic
  `--self-test` needing no ML dependencies. A reusable template for evaluating
  any "replace an LLM judge with an embedding-geometry shortcut" claim.
- **Vocabulary induction** (`docs/decisions.md:614-682`) — deferred, not
  adopted, zero code. Argues the 513,236-row fused registry is 99.6%
  out-of-domain and should be *induced* from the corpus down to an auditable
  2–5K, with two existence proofs at comparable scale. The load-bearing line:
  *"a 2-5K vocabulary is auditable by a small team; 513,236 is not, and an
  unauditable vocabulary is a defect in a product whose north star is the join
  surface."*
- **The semantic lane** — passed a sealed two-judge-family holdout
  (nDCG@10 0.698→0.786) using *scoped fusion*: fuse dense retrieval only where
  the answer shape is unanchored ranked retrieval. Naive global fusion raises
  nDCG but **drops 14 passes**. Stranded, not dead: the verdict was earned on
  the old corpus and the corpus changed underneath it.

---

## 5. Conventions worth stealing

- **Declared gaps as structured data.** 28 of 64 RefSpec registry loaders
  attach their known limitations to every resource — *"so a reader never has
  to rediscover them from the raw CSV."* This is why GCMD's limitation was
  diagnosable in two minutes.
- **Append-only corrections on sealed records.** Never edit the sealed file:
  strike the wrong claim inline and append a dated, numbered correction block.
  One instance reverses a claim made in an immutable commit message —
  *"commits are immutable, so it is corrected here."* Used twice ad hoc,
  documented nowhere.
- **Never blend failure modes into one number.** `tools/discovery_scoring.py`
  reports set precision/recall, row-level predicate exactness and declared-count
  comparison separately, strips ambiguous ground truth from both sides rather
  than guessing, and *raises* instead of scoring when a forbidden near-miss
  overlaps the expected set.
- **Predecessor fingerprinting.** DocSpec normalizes source to syntax-only
  tokens, SHA-256s every 96-token sliding window, and pins against the
  pre-split monorepo commit to prove its rewrite isn't vendored. All four
  repos make that claim implicitly; one checks it mechanically.
- **Quote both denominators.** Every quality figure a campaign quoted
  (61/114 passes) described a request shape only the harness could build. A
  real user at a text box gets **9/114**; 54 of 114 jobs need a UI affordance
  no text box can express.

---

## 6. Data-level findings

Measured directly against the sealed 2026-08-20 distribution.

### The scope notes were left on the floor

The taxonomy research establishes that majority vote gets **every documented
false friend wrong, 3-to-1**, and that the scope note overrides the vote. But
only **1.85%** of Atlas concepts carry a definition and 0.38% carry notes:

| scheme | concepts | definitions |
|---|---:|---:|
| lcsh-subjects | 514,837 | 0 |
| fast-topical | 441,127 | 0 |
| mesh-descriptors | 31,110 | 0 |
| nasa-thesaurus | 22,622 | 0 |
| fr-thesaurus-2025 | 705 | 0 |
| crs-policy-areas | 32 | 32 |

The machinery works elsewhere — GEMET 5,134, OPM 16,465, EuroVoc 1,555.

**The MeSH case is one line.** `mesh_descriptors.py:202` already calls
`elem.findall("ConceptList/Concept/TermList/Term")`. `ScopeNote` is a
*sibling of TermList in the same element the function already holds*.
Verified against the repo's own fixture, which carries 6 ScopeNotes parsed
past and discarded today:

```
d.findtext('ConceptList/Concept/ScopeNote')
D000001 Calcimycin → "An ionophorous, polyether antibiotic from
                      Streptomyces chartreusensis…"
D000002 Temefos    → "An organothiophosphate insecticide."
```

31,110 definitions, one `findtext` away.

**GCMD is not the same bug.** `gcmd_science_keywords.py:98` explicitly
declares `skosRelationshipsUnavailable` — *"only the separate RDF export
publishes those relationships."* A documented source choice; fixing it needs
a different source, not a parser change.

### The derived graph is load-bearing, not optional

| | |
|---|---:|
| MeSH concepts isolated in the asserted graph | 18,408 of 31,110 (59%) |
| rescued by the derived graph | **18,406** |
| still isolated | **2** |

REF-042 correctly calls it non-authoritative and opt-in. A consumer reading
"opt-in" as "skippable" gets a MeSH that is 59% rubble.

Connectivity overall: 230,315 of 1,497,841 concepts (15.4%) have no relation
at all. Worst: gcmd 100% isolated, fast-bulk-see-also 75.5%, mesh 59.2%,
lcsh 25.3%, fast-topical 3.1%.

### A stale premise hiding the pair that matters

The research record states "zero CrossRingRelationAssertions currently ship."
The seal has **446** — every one `entity → legalIdentity`, 1 of 6 possible
ring pairs. The `subject` ring (1,463,064 concepts, the largest) participates
in **none**.

Which matters because the Federal Register topics answer key is not a pure
subject vocabulary: of the 346 topics the FR Thesaurus cannot express, 71 are
agencies and 54 are values. The subject↔entity routing a tagger needs is
already built, validated and shipping — just never pointed at that pair.

### GCMD is the weakest scheme in the distribution

100% isolated, zero definitions, and the worst within-scheme label ambiguity
measured (20.73%; NASA thesaurus 18.95% is second, everything else under
1.2%). Switching to the published RDF export would fix all three at once.

---

## 7. Cross-repo: what one repo has that another is missing

1. **The negative-evidence ledger** (DocSpec) — records the outcome of every
   segment including successful **zero-tag** results, so "is a low tag count a
   coverage gap or a content gap" is answerable without re-running. Designed
   for SpicySearch's exact job, sitting in a folder DocSpec marks excluded
   from runtime authority.
2. **Sealed-bundle verification, already packaged** (rulespec) —
   `rulespec-conformance` ships as an installable wheel with no-network
   verifiers for `DocumentRelease`/`SourceCatalogRelease`, CLI entry points,
   ~150 real callers.
3. **Predecessor fingerprinting** (DocSpec) — under a day to port.

**One unflagged regression:** DocSpec lost DOCX/PPTX/XLSX extraction in the
2026-08-05 rewrite. Current dispatch handles only html/xml/json/pdf/image/text
and raises `ExtractionError` otherwise; `docling` and `chonkie` are gone from
deps. The original deferral was reasoned; it becoming permanent through the
rewrite was not tracked. **Latent, not currently biting** — verified that no
Office files exist anywhere in the local corpora.

---

## 8. Things checked and withdrawn

- **The `identifiers` table** (3,581 rows, one scheme) is *not* a
  built-for-extension-never-extended gap. Source identifiers are carried in
  `notations` (MeSH 31,108/31,110, FAST 441,127/441,127, LCSH 468,006/514,837)
  and in the resource IRI itself. That table holds *parsed structured*
  identifiers. No gap.
- **The spicy-regs archive tags** hold nothing lost — byte-identical to main
  on every core file, with main strictly ahead.
- **The notebooks** are honestly-labelled hackathon demos. No technique there.
- **`spicysearch` has no divergent branches at all** — 374 commits, all
  ancestors of main.

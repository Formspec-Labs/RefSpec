# Cross-repo code trace — synthesis

**Date:** 2026-08-08
**Method:** three independent agents, one instruction each — *ignore every `.md` file;
trace entry points, imports, schemas and tests instead.*
**Why:** every ownership and boundary claim in this programme rested on prose — a product
boundary document, an unapproved plan, catalog descriptions. None of it had been traced.

| # | Repos | Report |
|---|---|---|
| 1 | SpicyRegs (~968 files, RefSpec excluded) | [01-spicyregs-trace.md](01-spicyregs-trace.md) |
| 2 | RuleSpec (~91) + DocSpec (~353) | [02-rulespec-docspec-trace.md](02-rulespec-docspec-trace.md) |
| 3 | SpicySearch (~184) + RefSpec (~566) | [03-spicysearch-refspec-trace.md](03-spicysearch-refspec-trace.md) |
| — | Visual diagnostic across all five | [data-flow.html](data-flow.html) |

> **2026-08-09 · superseded in parts.** Four extraction reviews and one ownership
> constraint have landed since. Read [§ The ownership seam](#ownership-seam)
> onward first — it reorganises everything above it, and corrects several figures
> in this document and in the three traces.

Each report is the agent's verbatim output. Two caveats on provenance:

- Each agent opened with a line implying knowledge of the others' work ("all four traces
  are in"). **That framing is wrong** — the agents ran independently and none saw
  another's output. The framing lines have been stripped; report bodies are unaltered.
- Report 2 flags an unresolved tool-output anomaly in its §9. It is preserved rather than
  smoothed over.

Two further agents (cross-repo overlap; retrieval and indexes) were reported running by
the harness but never returned results. **Nothing in this folder derives from them.**

---

## 1 · The ownership split I proposed was wrong in three of five rows

| Piece | Claimed owner | Traced verdict |
|---|---|---|
| USC identifier scheme, popular names, Table III | RefSpec | ❌ **document-shaped — stays in SpicyRegs** |
| 88,000 sections, marked-up `<ref href>` citations | SpicyRegs | ⚠️ **nothing reads `<ref>` at all, anywhere** |
| ~16,400 unmarked prose citations | RuleSpec | ❌ **no repo attempts them; the refusal is deliberate and written into code** |
| Traversal at query time | SpicySearch | ✅ **already implemented and live** — but never measured on real data |
| DocSpec as infrastructure, not an owner | — | ✅ **confirmed, more strongly than claimed** |

**USC is captured observations, not a vocabulary.** `usc-act-sections.parquet` holds
10,976 rows over 9,916 distinct `(table3_key, act_section)` pairs — 471 repeat, up to
26×, and two rows are byte-identical across all seven columns. A row's identity is "the
*n*-th `<tr>` on page X.htm". There is no lifecycle anywhere in the path: no deprecation,
supersession, `replaced_by`, `broader`, or preferred label. Versioning is per-directory,
not per-term. Coverage is 24 of ~8,400 acts, because the act set comes from
`acts_cited_by()` over whichever corpus happened to cite them.

**The unmarked-prose gap is a decision, not an oversight.** `citations.py:724` resolves
only act-relative citations, requiring a *known* OLRC popular name adjacent to the
section token. Its docstring: *"The index is the grammar […] inferring which acts those
abbreviate is precisely the guess the identity fence exists to stop."* The shape-based
alternative was measured and rejected — "capitalized words ending in Act" hit `U.S.C.`
108 times across 4,777 authority strings. SpicySearch states the same rule independently
at `identifiers.py:186-190`. Assigning this to RuleSpec would overturn a decision two
repos took deliberately.

**DocSpec does no tagging.** Grepping `tag|classif|taxonom|ontolog|label` across
`src/docspec/` returns only `label=` error-message kwargs. Its one processor counts
bytes, codepoints, lines and words, and its docstring says it works "without assigning
document meaning". No LLM, no HTTP client, no server. The role description "document
management, segmentation, tagging" is one word too long.

---

## 2 · Everything is built; almost nothing is connected

Both repos I suspected of being scaffolding execute: RuleSpec passes 157 Rust tests,
DocSpec passes 264 pytest against a sealed gate receipt, SpicySearch passes 1,567. The
problem is not missing machinery. It is that **four repos each hold a stale,
digest-pinned copy of a contract nobody re-verifies.**

| Consumer | Pins RefSpec at | RefSpec ships | Drift gate |
|---|---|---|---|
| SpicySearch | Atlas **1.0**, vendored byte-copy | 3.0 | skips — "UPSTREAM TORN" |
| RuleSpec | Atlas **1.0**, 7 of 21 conformance cases | 3.0 | skips — `REFSPEC_CHECKOUT` unset |

`output/atlas-3.0-full-2026-08-06/` exists at 2.6 GB. **Nothing reads it.** Neither
consumer's reader would accept `schemaVersion: 3.0`. RefSpec never published a 2.0
example, so SpicySearch's 2.0 reader has never run against real data.

### ⚠️ Superseded 2026-08-09 — Atlas 1.0 and 2.0 were retired

Commit `5c6d889` *"refactor(atlas): retire Atlas 1.0 and 2.0"* — **307 files, 20,711
deletions** — removed `bindings/atlas/2.0/` entirely and reduced `bindings/atlas/1.0/`
to a single `README.md`. `bindings/atlas/1.0/examples/` and `.../fixtures/` are gone, as
is `build_vocabulary_atlas` from `src/refspec/atlas/__init__.py`. HEAD is now `21b662a`.

Its message reads **"Greenfield, no consumers."** That is defensible for RefSpec's own
live code paths and false for the workspace: **SpicySearch and RuleSpec both vendored
byte-copies from those exact deleted paths and pin their digests.** Their local copies
survive, so nothing breaks at runtime — but **the upstream those pins point at no longer
exists, so they can no longer be re-derived.** A digest pin whose source has been deleted
is worse than a stale one: staleness is detectable, absence is not.

The version-skew row above therefore resolves not by the consumers catching up but by the
producer deleting the contract underneath them. Both consumers now hold copies of a
format with no upstream at all.

### The `REFSPEC_CHECKOUT` claim was wrong in both directions

Corrected 2026-08-09 by an independent check that actually **set the variable and ran the
tests**. My "one variable gates every cross-repo freshness check" oversimplified in one
direction and undersold in the other:

- **RuleSpec** `tools/test_refspec_atlas_cross_repository.py:24` — `skipUnless` gates the
  *whole TestCase class*, all three methods. Genuinely inert, and now **triply dead**:
  unset → skip; set → `FileNotFoundError` on the deleted
  `bindings/atlas/1.0/fixtures/corpus.json`; and even with fixtures restored it imports
  `build_vocabulary_atlas`, which no longer exists.
- **SpicySearch** `tests/search/test_refspec_atlas_cross_repository.py:20-21` — **not
  `skipUnless` at all.** Unset, it falls back to a vendored fixture and runs normally.
  The variable swaps the data source; it does not gate the test.
- **SpicySearch** `tests/search/test_policy_inputs_cross_repository.py` — bypasses the
  variable entirely, defaulting to sibling-checkout paths (`ROOT.parent/"spicy-regs"`).
  All three upstream targets exist on this machine, so it is **live right now**, doing a
  real cross-repo byte comparison. Not dormant.
- Same vendored-fallback pattern, also not gated:
  `tests/search/test_refspec_atlas_conformance.py`,
  `tests/search/test_sealed_fixture_results.py`, and the CLI
  `src/spicysearch/validation/cli_seal_fixtures.py`.

What survives the correction: **`REFSPEC_CHECKOUT` is set nowhere** — no Makefile, no
workflow, no `.env` or `.envrc`, in any of the four repos.

Separately and still standing: RefSpec's resource catalog grew 33 → 89 resources and the
test that should have caught it *skips* rather than fails, because an upstream policy
file still pins the old digest and the test classifies that state as torn.

### A previously uncatalogued edge, in the opposite direction

**RefSpec → RuleSpec, by subprocess.** `src/refspec/release_graph.py`
`load_pinned_rulespec_validator()`, called from `release_graph.py:1727` and
`tools/reseal_elsst_managed_release.py:494`, both behind a required `--rulespec-dir` flag
(never hardcoded). It verifies the RuleSpec checkout's `git rev-parse HEAD` against a
pinned evidence revision, requires a clean tree, then subprocess-runs RuleSpec's
`tools/ci_validate.py` and `tools/reference_release_digest.py` with `cwd=rulespec_dir`.

This is the **mirror image of DocSpec→SpicyRegs and materially healthier**: git-SHA
pinned, dirty-tree guarded, path supplied by an explicit flag — versus a hardcoded
absolute developer path invoking a private function. Two subprocess edges, one careful
and one not; the contrast is the useful part.

---

## 3 · Traversal exists and has never been measured on real data

`expand_within_vocabulary` runs on **every concept query** — one hop over `skos:related`,
1,451 edges over 705 concepts, with a test proving a document reachable *only* via that
hop is returned. A second, richer implementation (`ConceptExpander.expand`: BFS, depth
tracking, predicate allowlist, `maximum_hops`, `maximum_fan_out`) is fully built and
structurally dead — the only production constructor hardcodes `admitted_predicates=()`.

But the concept-lane measurements ran over a **synthesised** atlas whose edges mean "two
concepts are co-assigned to one document." The benchmark says so itself at
`search_quality_benchmark.py:543-547`: *"It is not, and cannot stand in for, a
RefSpec-generated managed-vocabulary atlas"*, and at `:112-116`, *"a measurement over
these derived edges says nothing about that vocabulary's own relatedness."*

**This is the single most answerable open question in the programme.** Both sides already
exist on disk: a live one-hop expander, and a real thesaurus it has never been pointed
at. Nothing needs to be built to run it.

---

## 4 · `_SUPPORTED_RINGS` is not a blocker

I called it one repeatedly. Traced: zero production callers (the only importers are a
re-export and two test files), zero artifacts ever produced (no `mappings.sssom.tsv`
under any of 49 `output/` directories), and zero consumers (`grep -ri sssom` across all
of SpicySearch returns nothing).

The detail that settles it: RefSpec's shipped `statements.parquet` holds **481
`entity`-ring statements and zero `value`-ring statements**. *The allowlist permits a ring
with no data and forbids one with data.* Adding `entity` and `legalIdentity` would break
nothing downstream — the module below the gate is ring-agnostic. The real risks are
semantic, not structural: RefSpec-minted predicates like `cites`/`amends` have no SSSOM
meaning, and CURIE compaction would degrade to opaque `ns1:`/`ns2:` prefixes.

SpicySearch already supports all four rings end-to-end. It has simply never received
four-ring data.

---

## 5 · The receipt failure mode, in two independent places

Three of six identifier-edge figures were read out of receipts whose inputs had since
been rebuilt:

| Figure | Quoted | Actual |
|---|---:|---:|
| `authority_edges` | 10,618 | **11,793** (13-column artifact vs 16-column current schema) |
| `fr_docket_links` | 715,080 | **893,766** (file rebuilt *after* two receipts pinned its digest) |
| citation parser false positives | 1 in 4,777 | **1 in 620** (only disagreement cells adjudicated) |

Verified unchanged: `rule_targets` 39,516; CFR references across 205,255 documents
(*Federal Register* documents, not the 1.99M `documents.parquet`); 34,612 CFR-part↔agency
rows — though only 9,284 are rank-1, and that artifact's quarantine of 35,662 rows is
larger than its output.

**Every figure that survived was recomputable from a file whose digest still matched.
Every figure that failed was read from a receipt whose input had been rebuilt underneath
it.** This is the same failure mode as the eleven Atlas acceptance gates that read only
the built artifact: *a receipt proves what was computed, never that its inputs still
exist in that form.*

The same pattern holds for retrieval. Every SpicySearch figure previously relayed was
wrong, and all failed in one direction — understating machinery, overstating measurement:

| Claim | Actual |
|---|---|
| 35 gold queries | **78 queries / 114 variants / 867 qrels** |
| dense-only nDCG@10 0.661 | `0.661` appears in **zero files**. Dense-only = **0.5002** |
| cross-encoder +0.001 | **No cross-encoder exists** |
| BM25 loses its ablation | **Inverted** — largest single win; removing it costs **−0.359** |
| tagging micro F1 0.085 | **No F1 implemented.** The only `0.085` is `"assumed_cost_usd": 0.085608` |
| `services/search/` has 0 files | No `services/` in either repo; it exists only on a lineage **not an ancestor of HEAD** |

And the headline 0.7644 is the `harness` arm, hand-fed structured identifiers no typed
question carries. The real product path scores **0.3589, 9 of 114 passing.** The indexed
corpus is **722 Federal Register documents, title + abstract only**, ~626 chars each. No
document bodies are indexed anywhere.

---

## 6 · What is already broken

- **The only real-corpus snapshot no longer opens.**
  `open_published_snapshot(snapshots/holdout-exam-2026-08-01)` raises `IntegrityError` —
  three schema fields were added after it was built. No test catches it, because no test
  reads `snapshots/`.
- **Two SpicyRegs tests fail at collection** — they import refspec modules that moved when
  `registry/` was reorganised into `registry/adapters/`. An editable install has no
  version boundary to trip on this.
- **Build identity is a hardcoded constant.** `generate_atlas_v3_full.py:116` pins
  `DISTRIBUTION_ID` with `2026-08-06` baked in, so the `…-2026-08-08` build directory
  carries the older build's identity. Directory naming is human convention, unenforced by
  code. *(Recorded, not edited — that file is under another session's refactor.)*
- **8,232,356 records already carry an incompatible coordinate system.** DocSpec emits
  `"utf8-byte-range"`, absent from RuleSpec's closed enum, so RuleSpec's validator would
  reject every one. And DocSpec counts bytes where SpicyRegs counts codepoints — the same
  span in non-ASCII text yields different integers.
- **Sixteen copies of the ring set** exist across the workspace — 14 inside RefSpec alone,
  re-declared rather than imported, plus one in SpicySearch and one hardcoded in SQL.
  That is the mechanical reason a ring change is *believed* expensive.
- **DocSpec's `tools/` shells into a hardcoded developer path**,
  `Path("/Users/mikewolfd/Work/spicy-regs")`, and calls the private `_draw_documents`. Its
  `src/` is genuinely clean (`dependencies = []`); the coupling is entirely in `tools/`
  and `conformance/`.

---

## 7 · Corrections to my own earlier statements

- **`tools/test_refspec_atlas.py` is RuleSpec's, not DocSpec's.** DocSpec never reads
  Atlas — a case-insensitive grep for `refspec|atlas` across its live `src/` and `tools/`
  returns zero files. Every hit is inside the quarantined archive.
- **`rulespec`/`RuleSpec` and `DocSpec`/`docspec` are one repo each** — inodes `257555276`
  and `280359625` on a case-insensitive filesystem. Also worth knowing: SpicyRegs is a
  different GitHub org (`civictechdc`) from RefSpec, RuleSpec and DocSpec
  (`Formspec-Labs`).
- **DocSpec's 353 source files** are 105 live and 248 quarantined, with the boundary
  enforced by three separate tests including one that inspects the built wheel.
- **RuleSpec's byte-offset evidence vocabulary is fully specified and entirely inert** —
  `TextPositionSelector`, `TextQuoteSelector`, `SourceFragment`, `ExtractionActivity` all
  defined, none produced or dereferenced. It is a provenance receipt for an extractor
  living in SpicyRegs (`docpipeline/rkaf_projection.py`, which verifies every offset by
  re-slicing stored text and SHA-256-comparing the region).

---

## 8 · What follows from this

Ranked by ratio of value to work, given that everything below needs no new machinery:

1. **Point the live one-hop expander at the real thesaurus and measure it.** Both halves
   exist. This is the only unanswered question that changes the product thesis.
2. **Decide whether Atlas 3.0 is meant to be consumed — this is now urgent.** With 1.0
   and 2.0 retired, the only format RefSpec publishes has **no reader anywhere**, and the
   only format its two consumers can read has **no producer anywhere**. That is not
   version skew any more; it is a severed contract. Either someone writes a 3.0 reader or
   the 2.6 GB build has no audience and should be labelled as such.
3. **Do *not* simply set `REFSPEC_CHECKOUT` in CI.** ~~One variable disables every
   cross-repo check~~ — corrected above. RuleSpec's gated tests would now *error* rather
   than pass, since the fixtures and the imported API are both gone. Either restore the
   1.0 fixtures, retarget those tests at 3.0, or delete them; leaving a test that can
   only skip or crash is the worst of the three.
4. **Fix the coordinate-system split before more than 8.2M records carry it.** Bytes
   versus codepoints is a silent corruption in non-ASCII text, not a naming disagreement.
5. **Re-derive, never re-quote.** Three of six figures failed because a receipt outlived
   its input. A digest that is not re-checked at read time is decoration.

**Leave alone:** the ring gate (guards an exporter nobody calls), the USC tables (they are
correctly shaped for what they are), and the unmarked-prose refusal (a considered decision
with measurements behind it).

---

<a id="ownership-seam"></a>

# Update · 2026-08-09 — the ownership seam

Everything above treats five repos as peers. They are not. **`spicy-regs` is
`civictechdc/spicy-regs`; the user can commit but does not own it.** RefSpec, RuleSpec and
DocSpec are `Formspec-Labs`, and **SpicySearch is owned too** (confirmed by its owner,
2026-08-09 — it could not be read from the tree, which has zero configured git remotes).
**Four owned, one not.** That line is the only boundary in this workspace that is
genuinely hard — everything else is a refactor.

That the sink sits inside the boundary matters: every SpicySearch → SpicyRegs edge is an
owned repo consuming a not-owned repo's *published artifacts* — vendored, digest-pinned,
never imported. That is the shape the import rule asks for, arrived at already. It also
means the collapse-to-one-repo question covers **four** repos, not three.

The rule that falls out: **nothing you own may import what you don't, and nothing you
don't own may import you.** Both directions are violated today — RefSpec is a submodule
*of* spicy-regs and spicy-regs imports it at runtime through an editable install.

## The divergence, and what a reset destroys

`origin/main` is at `f1fcb8c` (2026-07-31). Local `main` is **223 commits ahead: 648
files, +260,563 / −3,641 lines**, none pushed. Preserved on branch
`archive/local-work-2026-08-09` and tag `archive/pre-reset-2026-08-09`.

`f1fcb8c` is *exactly* the commit DocSpec's clean-room AST fingerprint pins, so the reset
does not invalidate that tripwire.

> **⚠️ The archive commit broke DocSpec's campaign seal, and the fix is one command.**
> DocSpec's 10k campaign pins spicy-regs at **`adbd5a2b`**. Creating
> `archive/local-work-2026-08-09` moved HEAD to `002d56c2`, so `prepare` and `run-all`
> now fail closed; only `run-tier` resumes. **`main` still points at `adbd5a2b`**, so
> `git checkout main` in spicy-regs restores the pinned state with the archive branch
> retaining the extra commit. The seal behaving this way is it working correctly.

**The reset-risk intuition is backwards.** `output/` is gitignored (`.gitignore:11`) and
survives untouched. `docs/evidence/` is fully tracked and **100% local-only — 0 files on
`origin/main`, 202 on the tag**. *The reset destroys the prose and leaves the data.*

Whole subsystems are net-new rather than modified. `origin/main` carries 92 files under
`src/spicy_regs/`; absent from it entirely are `ontology/` (21 files / 13,233 lines),
`docpipeline/` and `enrichment/` (together 29,867 insertions and **zero deletions**),
`corpora/{mirrulations_document_corpus,body_retrieval_corpus}.py`, all 202 evidence files,
and **both CI workflows that drive the pipeline** (`materialize-ontology.yml`,
`rollup-supreme-court-opinions.yml`).

**A runtime dependency hides in the docs.** `tools/project_document_to_rkaf.py:344`
resolves its default JSON-LD context from
`docs/evidence/single-document-rulespec-projection-2026-07-28/rkaf-context.jsonld`
(36,413 B, absent upstream). The same directory holds `build_projection.py`, the
hand-authored predecessor the projection generalizes and the only account of why it has
the shape it has. **If nothing else is rescued from `docs/evidence/`, rescue that
directory.**

## Three live defects, independently reproduced

**Fabricated citations reaching published tables.** `ontology/citations.py:657` —
`parse_cfr_citation("40 CFR 60 and 12 CFR 220")` returns `['40-60','12-220','40-1']`.
`40-1` is in no input. Backtracking defeats the negative lookahead: `\d+` matches `42`,
the lookahead fails, the engine retries with `4`, and the lookahead then inspects `2` and
passes. Minted parts are plausible, so nothing downstream rejects them — and the function
feeds `canonical_cfr_iri` at `transforms/build_rule_targets.py:213` and
`docpipeline/rkaf_projection.py:866`. Two prior commits already tried to close this class.

**Citations at sentence end are dropped whole.** Same file, `:32` — a greedy section class
swallows the trailing period, `_cfr_section` rejects it, and a fail-closed guard discards
the entire citation rather than degrading to part level. `"49 CFR 900.42."` → `[]`;
`"49 CFR 900.42;"` works. Sentence-final is the modal spelling in regulatory prose.

**A validator that claims to fail closed and does not.**
`corpora/body_retrieval_corpus.py:917` validates lock→disk and never disk→lock.
`output/scale-dr-10k-2026-08-05/cache-xml/` holds **6,408 documents and 6,408 receipts
under a lock declaring 3,333**; quarantine reports 1; validation passes. The lock and
every in-lock receipt stop at 07:53:19 while 3,075 orphans run to 09:06:10 — a stage-2
run died leaving a stale stage-1 seal. **DocSpec's sealed catalogs point at that exact
directory**, so a campaign resume propagates captures the producer's own seal does not
cover. One loop inside `validate_body_cache` fixes it.

## The extraction, sized

`rkaf_projection.py` is **3,124 lines**. ⚠️ **The line-count breakdown does not
reproduce and should not be quoted.** The reported 44/56 split — 1,361 portable against
1,723 scaffolding — sums to 3,084, matching neither the file nor the reported 2,153 code
lines (re-measurement gives 2,731), and the arithmetic error originated in an earlier
draft of *this document*. The "~350-line irreducible kernel" is unfalsifiable as stated
because no boundary was defined for it. Treat the ratio as an unverified estimate; if the
sizing matters to a go/no-go, measure it against a stated definition first.

**The mechanical claims all held exactly**, and they are the ones that decide cost: the
external dependency surface is **36 lines** (`text_digest`, 4;
`resolve_exact_evidence_offsets`, 32); the module never touches `artifact.coordinates`,
`regions`, or `SourceRegion`; and the `model is None` test passes on re-run.

The LLM layer is cleanly separated, proven rather than inferred: a passing test builds a
complete 11-type graph including `SourceFragment` and `TextPositionSelector` with
`model is None` and no `ConceptAssignment`.

**It has already been extracted once.** DocSpec's `archive/legacy-2026-08-05/` holds the
module at identical length; the diff is **48 lines, every one a `spicy_regs`→`docspec`
rename, zero semantic drift**. DocSpec was then rebuilt hexagonal from first principles
and none of it carried forward. `docs/migration/spicysearch-product-migration-manifest.json`
item 9 already assigns the file `disposition: "reimplement"`, splitting portable shapes to
Rulespec Core and extraction projections to **Rulespec Extrapolator**.

So mechanical code motion is a solved, cheap problem.

**Why the first attempt did not stick — answered 2026-08-09 by the person who ran it: the
agents ran out of tokens.** Not a design rejection, not a stall on a hard problem, and the
work is being resumed.

Two earlier readings in this document were wrong and are withdrawn. An earlier draft called
the stop "unexplained"; a later one inferred from the fenced archive and the redesigned
release that the old design had been "rejected on purpose". **Neither holds.** The
redesign was deliberate; the *stopping* was budget exhaustion, and it carries no verdict on
what remains unported.

What that reframes:

- **The fenced archive is the migration's source material, not its epitaph.**
  `archive/legacy-2026-08-05/` holds the complete pre-migration `docpipeline` (20,821
  lines) including the 48-line-rename copy of `rkaf_projection.py`. The package-boundary
  test excluding it from pytest and ruff is *scaffolding that keeps the un-migrated version
  from shipping accidentally* — exactly what you want mid-migration.
- **The new design is real and worth continuing into.** DocSpec's live
  `domain/release.py` is 246 lines: spicy-regs puts documents *inside* the release,
  DocSpec's is a thin manifest (1 MB cap) pointing at record layers, with a genuine commit
  protocol — `O_EXCL` lock, write-once blob, re-verify, atomic `os.replace`,
  `StaleBaseError` on a stale base — and identity recomputed in `__post_init__` so every
  construction path self-verifies.
- **The estimate goes back to "resume", not "re-litigate".** The mechanical port is
  provably cheap (48 lines, all namespace). The remaining work is porting capability into
  the hexagonal kernel, and the natural next piece is small: `rkaf_projection.py`'s kernel
  plus its **36-line** external dependency surface.

The concrete gap to close first is the one the corpora review identified: **DocSpec has no
discovery port.** `SourceCatalog` only reads an already-frozen distribution and
`_CompiledSelection` only filters a materialized catalog, so `build_draw` has nowhere to
land. A `SourceDiscovery`-style port emitting `Iterable[SourceItem]` unblocks both the draw
severance and anything downstream that needs to select rather than read.

## Extraction triage

| Component | Destination | Cost |
| --- | --- | --- |
| `ontology/citations.py` + `act_index.py` + `PopularNameIndex` | **RefSpec** | Pure stdlib, ~30 symbols to rewire; the whole `ontology/` package's outbound footprint into `spicy_regs` is **3 import statements**, all in `receipt.py` |
| `rkaf_projection.py` kernel + `assemble()` + `enrichment/connected_concepts.py` | **Rulespec Extrapolator** | ~350-line kernel + ~36 lines of symbols; ~382 of `enrichment/`'s ~1,400 lines travel |
| Edge tables, rollups, receipt/pipeline machinery, `sources/*` fixes | **stays upstream — civictechdc PR** | Five `source_inputs` all produced by `spicy_regs` crons; extracting means forking the ingestion tier |
| `corpora/` draw path (`build_draw`, not `_draw_documents`) | **DocSpec, but blocked** | ~150 lines, but DocSpec has no discovery port to receive it |
| `retrieval.py` (5,479), `relation_task.py` (2,102), `executor.py` (536), `adapters/codex_cli.py` (553); `ontology/{ann_index,candidate_channels,codex_cli,relation_findings}.py`; `enrichment/{managed_release,open_set,accepted_output}.py` | **delete** | Zero non-test importers, zero entrypoints; several say so in their own docstrings |

**The edge tables belong upstream, and the argument is not sentiment.** The local work is
a *correctness rescue*: the paired receipt (`inputs_match: true`) shows `rule_targets`
baseline carrying **247,229 invalid-docket-syntax and 47,222 docket-not-in-source** rows
against a candidate with all counters at **0**, and `proceedings` going from **305,807
self-predecessor edges** — roughly 90% of rows pointing at themselves — to 0. Upstream
ships that today. **Holding it back to keep a moat means the moat is their defect.** What
is genuinely the user's substrate is one layer down: the identity grammar.

Flag before opening the PR: `pyproject.toml:32` adds **pymupdf — AGPL-3.0 or commercial
Artifex** — to an **MIT** Civic Tech DC repo. Deliberate for a private tree; a governance
question upstream, especially for a hosted service.

## Amendments to figures in this document and the three traces

**Coordinates — the largest single correction.** They are **two different fields, not two
spellings of one**. `rkaf:coordinateSystem` is a JSON-LD selector with a **closed 6-value
enum** (`constraints/core/source-fragment.cue:19-21`); `coordinate_system` is a snake_case
tabular release field declared an **open string**
(`extrapolation-release.schema.json:1015-1017`). The **4,249,550** records (exact) spelling
`unicode-codepoints-half-open` are therefore **not non-conforming** — they fill a field the
standard leaves open, and rulespec already aliases that spelling at
`tools/rulespec_release.py:771-774`. Meanwhile **`rkaf:unicode-codepoint` has emitted only
6 records** — zero under `output/` — so the conforming producer has effectively never run
at volume. The live conforming producer is `rkaf_projection.py:202`;
`enrichment/open_set.py:217` is the *dead* one. **The risk ranking flips** —
codepoint-vs-codepoint spelling is cheap (though digest-load-bearing, so respelling changes
artifact IDs), while **DocSpec's `utf8-byte-range` is the real hazard**, an arithmetic
disagreement rather than a naming one, and a deliberate decision rather than drift.

Neither `concept_assignment.rs` nor `evidence-binding.cue` carries coordinate vocabulary at
all — `source-fragment.cue` is the sole authority. And there is a **third** field:
`derived_coordinate_system`, pinned `const "unicode-code-points"`.

### ⚠️ Amended again 2026-08-09 — "SpicyRegs counts codepoints" is true of one lineage only

This finding has now been revised four times; this is the version that survives
measurement. **spicy-regs ships two DocumentRelease lineages that share no code**, and
they disagree with each other about coordinates:

| Lineage | Coordinate | Verified |
| --- | --- | --- |
| v1/v2 — `document_release.py:43` | `unicode-codepoints-half-open` (Python `str` indices) | ✅ |
| **v3 — `document_release_v3*.py`** | **`urn:spicyregs:coordinate:rendition-utf8-byte-slice:1.0`** | ✅ |
| DocSpec — `processing/extraction.py:447` | `utf8-byte-range` | ✅ |

**So v3 already counts UTF-8 bytes, with codepoint-safe segmentation that backs up over
continuation bytes.** DocSpec agrees with v3 *on the axis*; what differs is the label and
the structure (`EvidenceCoordinate` with optional page/region, plus `EvidenceMapping`
declaring transformations, where only `identity-byte-slice` permits offset arithmetic).

That reclassifies the hazard. The RuleSpec-validator rejection is a **closed-enum
vocabulary mismatch, not an alien coordinate model**. The genuine *arithmetic* disagreement
is **v1/v2 against everything else** — and v1/v2 is the lineage SpicySearch actually
vendors today. Earlier drafts of this document framed the byte-vs-codepoint split as
DocSpec-against-SpicyRegs; it is really old-SpicyRegs against new-SpicyRegs, with DocSpec on
the new side.

**Receipts — and a correction to the correction.** An earlier draft of this section
claimed no verify path exists and that `fr_docket_links` row counts were never attested.
**Both are wrong**, caught on re-measurement:

- **Code does load receipts and re-check digests** — three modules do, one behind a real
  `verify` subcommand. Only `ontology/receipt.py` itself lacks the path, which is what the
  original observation actually saw.
- **`rows: 715080` is attested**, in `output/agency-crosswalk-2026-08-02/receipt.json` and
  `output/date-event-artifact-2026-08-01/receipt.json` — independently confirmed. And
  while `_file_record()` (`pipelines/materialized.py:64-67`) does not store `rows`, its
  caller at `:414-418` adds it for every generation output, so outputs *are* row-attested.

The surviving, accurate statement is the original one: **715,080 was attested, the file
was then rebuilt to 893,766, and no receipt attests the rebuilt state.** Re-hashing found
**9 of 9 generation artifacts still match** their receipts today. The mechanism is
`_sha256()` (`ontology/receipt.py:63-68`) → `_artifact_records()` (`:136`) →
`build_receipt()`.

**Other figures.**

- `authority_edges` 10,618 and 11,793 are **different corpora, not stale-vs-current**. The
  10,618 receipt digest matches disk today; 11,793 exists only in `output/discovery-slice-*`
  and no receipt records it.
- `rule_targets`: the meaningful pair is the paired receipt's **335,008 → 40,546**.
- Total is **1,024,593 rows across 9 present outputs**, not ~1.14 M. A 10th,
  `ontology_segment_ledger.parquet`, has never been generated.
- **`is_most_citing` is not misused, but it is not unconsumed either.**
  `spicysearch/src/spicysearch/agency_priors.py:77,90,162` reads both
  `cfr-part-agencies.parquet` and the flag, and enforces exactly-one-true. "Zero
  consumers" is true only when scoped to SpicyRegs — the consumer is across the repo
  boundary, which is the more interesting fact.
- The **quarantine-larger-than-output** observation was a category error: its 35,662 rows
  are upstream *source-record* defects (30,405 `agency_entry_missing_slug`, 5,225
  `cfr_reference_missing_part`, 32 not-in-FR), a different population from the output.
- **USC outputs are identity data, not "position on a page".** Rows are keyed by stable
  identifiers — popular name → Table III key, `(public law, division, act section)` → USC
  section. But the `refusal` semantics are the **inverse** of what an earlier draft said:
  **null means *resolved***, and absence-of-row is synthesised as `"absent"` at query time.
  The zero-importer finding holds for `src/` but is by design: fetchers are unreproducible
  as scripts and consumable as digest-pinned parquet, read by `ontology/act_index.py` —
  which digest-**stamps** but never digest-**verifies**.
- The **1,060 discarded rows** were a bug that got *fixed*, not one being papered over.
  Table III is keyed by enacting Public Law, so one act section legitimately has several
  classification rows; the mapping is tuple-valued so sort order cannot pick a winner.
- **`concepts.py`'s schema must not move to RefSpec** — RefSpec already superseded it.
  `refspec/vocabulary.py:57-64` lists those exact fields as `_LEGACY_FIELDS`.
- The DocSpec 10k run reached **106,943 files / 5.1 GiB** (not ~97,700 / 4.8 GB). Of its
  20 GB, **12.7 GB is five stale `-pre-*-fix` snapshots marked deletable**. ⚠️ **"Intentionally
  killed" is asserted, not established** — it rests solely on an *untracked* status file
  written three days later, against physical evidence of abrupt mid-transaction death: a
  stale SQLite journal, a missing `run-reference.json`, and an mtime cliff.
- **`enrichment/managed_release.py` is not dead** — it has live non-test importers. It is
  mid-migration legacy, not a deletion candidate.
- **SpicySearch is owned** (confirmed 2026-08-09). Its checkout still has **zero
  configured git remotes**, which is now a local hygiene gap rather than an open question
  — and one more repo whose work exists on a single disk.
- `docpipeline` + `enrichment` is **+29,168** insertions, not 29,867.
- **`_draw_documents` is a 15-line validator, not a selector.** The real selector is
  `build_draw`, already ports-shaped.

## ⚠️ Provenance caveat covering everything above

Commit `d165350` is **`docs: CONTAMINATION NOTICE — fabricated research relayed into the
ledger`**. **Evidence documents dated on or before 2026-07-28 are untrustworthy without
re-checking.** Several figures in this programme trace to that window. Preserving that
notice matters as much as preserving what it marks.

## A cost the target architecture has not priced

The stated target has **SpicySearch consuming DocSpec's ingestion pipeline**. But
SpicySearch's admission path **pins spicy-regs v2/v3 byte-for-byte**, and DocSpec's release
is a different format, a different URN namespace (`urn:docspec:document-release:v1:<hex>`
against `urn:spicyregs:document-release:v3:<hex>`), and a different coordinate vocabulary.
Nothing pinning a spicyregs URN can accept a docspec one.

**So that edge is not wiring — it is a consumer-side format migration**, closest in spirit
to v3 and furthest from the v1/v2 fixtures SpicySearch actually vendors today. It should be
costed as such before it is scheduled.

Also worth fixing before anything external pins it: **DocSpec's
`profiles/canonical-release-manifest-v1.json` declares `"formatVersion": "1.0"` while the
code emits and requires `"1.1"`** — verified. A profile that disagrees with its own
implementation is a trap for the first external consumer.

## Still unverified

- Whether DocSpec's deliberate rejection of the spicy-regs release design extends to
  `rkaf_projection.py` itself, or covers only the release format beside it.
- Whether the 893,766-row `fr_docket_links` rebuild is *semantically* better than the
  715,080 state; only the digest divergence and row arithmetic were confirmed.
- Whether 30,405 `agency_entry_missing_slug` quarantine rows are a real upstream coverage
  gap or duplicated entries — 85% of the quarantine is one reason code.
- All production row counts: the R2 catalog credentials are absent, so every
  production-scale figure in this programme remains asserted.

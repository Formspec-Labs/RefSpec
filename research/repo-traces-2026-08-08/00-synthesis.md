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

**One environment variable gates every cross-repo freshness check in the workspace, and
it is set nowhere** — not in either Makefile, not in CI. `REFSPEC_CHECKOUT` disables
RuleSpec's drift test and SpicySearch's live-atlas comparison simultaneously. Separately,
RefSpec's resource catalog grew 33 → 89 resources and the test that should have caught it
*skips* rather than fails, because an upstream policy file still pins the old digest and
the test classifies that state as torn.

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
2. **Set `REFSPEC_CHECKOUT` in both CIs.** One variable currently disables every
   cross-repo freshness check in the workspace.
3. **Decide whether Atlas 3.0 is meant to be consumed.** If yes, someone must write a
   reader; if no, the 2.6 GB build has no audience and should be labelled as such.
4. **Fix the coordinate-system split before more than 8.2M records carry it.** Bytes
   versus codepoints is a silent corruption in non-ASCII text, not a naming disagreement.
5. **Re-derive, never re-quote.** Three of six figures failed because a receipt outlived
   its input. A digest that is not re-checked at read time is decoration.

**Leave alone:** the ring gate (guards an exporter nobody calls), the USC tables (they are
correctly shaped for what they are), and the unmarked-prose refusal (a considered decision
with measurements behind it).

# SpicySearch and RefSpec — code trace

**Agent brief:** determine what SpicySearch actually does and where its boundary with
RefSpec really sits, by tracing code. **Ignore every `.md` file.** Read-only. Verify or
refute a supplied list of figures; establish whether traversal exists; trace what
`_SUPPORTED_RINGS` actually gates.

**Scope:** `/Users/mikewolfd/Work/spicysearch` (~184 source files),
`/Users/mikewolfd/Work/spicy-regs/RefSpec` (~566 source files).

**Date:** 2026-08-08 · **Status:** verbatim agent output

---

# What SpicySearch actually does

**It is a single-machine, digest-sealed lexical search engine over US Federal Register
documents, with a concept lane bolted alongside it.** From code: `cli.py build-snapshot`
ingests a pinned upstream document release and writes an immutable snapshot —
`search.duckdb` plus six parquet tables (`documents`, `chunks`, `passages`,
`assignments`, `links`, `observations`) — then `SearchEngine.search_documents`
(`src/spicysearch/engine.py`, 4,549 lines) answers requests carrying up to seven declared
intents (`records.py:88-98`: `exact_identifier`, `exact_phrase`, `connections`,
`concept_assignment_candidate`, `concept_candidate`, `lexical`, `semantic`). Ranking is
real BM25 (`engine.py:4110-4121`, k1=1.5, b=0.75; Lucene IDF at `:4033`) fused by
unweighted RRF (k=60) with a character-trigram channel, then ordered by
`(evidence_tier, -signal_accumulation, method_precedence, -normalized_channel_score,
document_id)` (`engine.py:466-480`). Everything is receipted and replayable. It is served
by a stdlib `ThreadingHTTPServer` (`api/server.py:16`) on four routes — `/v1/health`,
`/v1/snapshot`, `/v1/coverage`, `/v1/search` (`api/router.py:197-203`). 1,568 tests
collect; the suite passes (I ran it: exit 0; `1567 passed, 1 skipped, 2 deselected` in
371s).

The honest scope caveat is in its own data, not its docs: the only real corpus is **722
Federal Register documents** (483 Notices, 139 Rules, 97 Proposed Rules), indexed as
**title + abstract only** — `extraction_method_and_version =
"title-abstract-concatenation:1"`, ~626 chars/document. There are no document bodies in
any indexed corpus.

# The consumer seam

SpicySearch reads exactly **three** things from RefSpec, all vendored as byte-copies and
digest-pinned, never read live:

| What | RefSpec source | Vendored to | Pinning |
|---|---|---|---|
| Vocabulary atlas (FR Thesaurus 2025) | `bindings/atlas/1.0/examples/federal-register-thesaurus-2025/{atlas-manifest.json, atlas.nq}` | `fixtures/releases/vocabulary-atlas/…` | dual sha256 in `fixtures/releases/vocabulary-atlas-pin.json` |
| Same, second copy | as above | `fixtures/releases/refspec-vocabulary-atlas-v1/` | same |
| Resource catalog | `portfolio/resource-catalog-v0.json` | `fixtures/policy-inputs/refspec-resource-catalog.json` | `catalogDigest` |

I confirmed byte-identity by hashing both sides: `atlas-manifest.json` →
`sha256:956cab4f…f60f1`, `atlas.nq` → `sha256:8e1eaf22…e830a`, both matching the pin
file exactly. The RefSpec repo path is consulted **only** when `REFSPEC_CHECKOUT` is
exported (`tests/search/test_refspec_atlas_cross_repository.py:19-24`); the default is
the vendored copy.

**Reverse direction: nothing.** RefSpec reads no SpicySearch artifact. Its only mention
is a stale docstring at `src/refspec/atlas/qualification.py:29` citing
`spicysearch/src/spicysearch/holdout_labeling.py` — a path that does not exist (the file
is at `src/spicysearch/experiments/holdout_labeling.py`).

**The seam is broken right now, and failing silently.** RefSpec's catalog has grown **33
→ 89 resources** (56 added, none removed). The drift test
`test_vendored_policy_inputs_match_current_upstream_outputs` does not fail — it *skips*,
because `spicy-regs/policies/profile-resource-applicability-v0.json` still pins the old
digest and the test classifies that as "UPSTREAM TORN"
(`test_policy_inputs_cross_repository.py:38-64`). I verified the tear live: policy pins
`sha256:c0bcce73…`, RefSpec now states `sha256:a731fef9…`.

# Verified / refuted

### Q1 — "`services/search/` contains 0 files"

**Refuted as stated; true only of dead history.** No `services/` directory exists in
either repo. It existed in git — `62eccf2` extracted a Hono service, `fa24dd8` rewrote it
to FastAPI, `4d2e25c` retired it — but that commit is **not an ancestor of HEAD**
(verified with `git merge-base --is-ancestor`). The repo has three root commits; HEAD
descends from `c5fdb74` (2026-07-31, 276 commits). Retrieval lives in `src/spicysearch/`
and is working.

### Q2 — "Atlas 2.0, graph expansion disabled (`not_used`)"

**Both halves refuted.**

- The live engine consumes **Atlas 1.0** — `vocabulary_atlas.py:25`
  `ATLAS_FORMAT = "refspec-vocabulary-atlas-nquads-1.0"`, and every
  `atlas-manifest.json` on disk in spicysearch declares `schemaVersion: 1.0`. Zero
  non-`.md` references to `atlas-2.0` or `atlas-3.0` anywhere in the repo.
- An Atlas 2.0 reader exists (`vocabulary_atlas_v2.py:24`) and is imported by the whole
  snapshot subsystem — but **`atlas-scope.json` exists nowhere in spicysearch**, and that
  file is mandatory (`vocabulary_atlas_v2.py:27`), so `VocabularyAtlasV2.open()` has
  never run against real data. RefSpec's `bindings/atlas/2.0/` contains only schemas and
  a README — no examples were ever published.
- **Nothing reads `output/atlas-3.0-full-2026-08-06/`.** That directory exists (2.6 GB)
  and RefSpec's `tools/generate_atlas_v3_full.py:113` *writes* it. Neither SpicySearch
  reader would accept it (`schemaVersion: 3.0`, `format:
  refspec-atlas-packed-nquads-3.0`). **The version gap is two majors.**
- `not_used` is not one flag. It is a sentinel on ~8 independent knobs, and the claim
  conflates three: a snapshot pinning no atlas at all; a build-time cross-vocabulary
  policy; and the Atlas-2.0 BFS expander. **Most importantly, in
  `evaluation/experiments/2026-08-02-within-vocab-expansion-v1/metrics.json`,
  `vocabulary_atlas: "not_used"` is the label of the `off` control arm in an A/B** — the
  `resolver` arms carry a real pinned atlas and 98 assignments.

### Q4 — every figure refuted

| Claim | Verdict | Actual |
|---|---|---|
| 35 gold queries | **Refuted** | 78 queries / 114 scored variants / 867 qrels; separately 657 holdout queries, 37 capability cases. Tests assert 78 and 114 (`tests/validation/test_query_quality_dataset.py:45,47`). No fixture anywhere has 35 records. |
| dense-only nDCG@10 = 0.661 | **Refuted** | `0.661` appears in **zero** files. Dense-only (`dense_dev_alone`) = **0.5002**; scoped variant 0.4823. |
| cross-encoder adds +0.001 | **Not found** | No cross-encoder or neural reranker exists. The only −0.001-shaped delta is the concept lane: `resolver` 0.7815 → `resolver_expansion` 0.7804. |
| BM25 loses its ablation | **Refuted — inverted** | BM25 is the single largest win. `dense_dev_alone` 0.5002 → `engine` (BM25 spine) 0.7644 → `dense_lexical_weighted_rrf` **0.8592**. Removing BM25 costs −0.359 nDCG@10. |
| tagging micro F1 = 0.085 over 35 assignments | **Refuted** | No F1 is implemented anywhere in the repo. 98 assignments in the concept lane, 0 in the shipped snapshot. The only `0.085` on disk is `"assumed_cost_usd": 0.085608` in `evaluation/holdout-labeling/receipts/openai-receipts.jsonl` — a dollar cost. |

I extracted all of these from the artifacts myself rather than taking them second-hand.

**The number that matters more than any of these:** the published 0.7644 is the
`harness` arm, which hand-feeds structured identifiers and relation controls no typed
question carries. The actual product path is `front_door` — **nDCG@10 0.3589, 9/114
passes** (`2026-08-02-query-front-door-product-path-v1/metrics.json`, verified). That is
less than half the headline.

# Is traversal implemented?

**Three distinct paths — one live, one dead, one gated off.**

1. **`expand_within_vocabulary` — implemented, reachable, live, and measured.**
   `concept_resolution.py:114` ← called at `engine.py:2060` on every request carrying
   `concept_candidate`. One hop over `skos:related`, non-recursive. Real data: 1,451
   edges over 705 concepts. Results feed retrieval at `engine.py:2078-2093` at a
   deliberately weaker precedence. `tests/search/test_within_vocabulary_expansion.py:102-119`
   proves a document reachable *only* via the related hop is returned. **This alone
   refutes "expansion disabled".** It has no hop cap, no predicate allowlist, no fan-out
   cap — boundedness comes only from the shape of the code.
2. **`ConceptExpander.expand` — implemented, wired, structurally dead.** A genuine BFS
   with depth tracking, predicate allowlist, `maximum_hops`, `maximum_fan_out`
   (`concept_policy.py:361-416`). Locked shut twice over: the only production constructor
   is `ConceptPolicy.without_expansion` (`cli.py:333`) which hardcodes
   `expansion_policy_id="not_used"` and `admitted_predicates=()`, and
   `concept_policy.py:169-170` raises on any snapshot whose policy differs. Called only
   from tests.
3. **Build-time cross-vocabulary expansion** (`snapshot.py:1754`) — reachable in dev,
   `not_used` in production, and moot regardless: the vendored atlas has
   `searchOnlyMappings: 0`.

**Absent:** transitive closure, multi-hop. Multi-hop *document* traversal is explicitly
refused — `relation_scope="two_hop_any"` raises `invalid_relation_controls`
(`tests/search/test_relation_controls.py:137-144`).

**The critical caveat on the measurement.** The concept-lane numbers ran over a
**synthesised** atlas whose edges are "two concepts are related when the corpus assigns
both to one document". The code says so itself, at
`search_quality_benchmark.py:543-547` — *"It is not, and cannot stand in for, a
RefSpec-generated managed-vocabulary atlas"* — and at `:112-116`, *"a measurement over
these derived edges says nothing about that vocabulary's own relatedness."* Graph
expansion has never been measured against the real RefSpec thesaurus.

# What `_SUPPORTED_RINGS` actually gates

**Nothing that ships. It is an unused code path enforced only by its own unit tests.**

`relation_sssom.py:86` `_SUPPORTED_RINGS = frozenset({"subject", "value"})`, checked at
`:145` — a hard `raise`, at three entry points (`relation_sssom_text` `:337`,
`__post_init__` `:499`, `open` `:578`).

Traced to consumers:

- **Zero production callers.** The only importers are `refspec/atlas/__init__.py` (a
  re-export) and two test files. `tools/generate_atlas_v3_full.py` never invokes it — it
  merely loads the module as a side effect of importing `compact_pack`.
- **It has never produced an artifact.** No `mappings.sssom.tsv` exists under any of 49
  `output/` directories. The nine `.sssom.tsv` files on disk are from external SEMRA/OAK
  tool spikes.
- **No consumer exists.** `grep -ri sssom` across all of SpicySearch returns **zero
  hits**. Its reader wants `{atlas-manifest.json, atlas-scope.json, atlas.nq}`.
- Two deleted tests (`test_sssom_export.py`, `test_sssom_mapping_source.py`) survive only
  as `__pycache__` orphans, removed in `67d2d74`.

**If `entity`/`legalIdentity` were added, nothing downstream would break** — the module
below the gate is ring-agnostic, and no fixed-size arrays or exhaustive matches assume
two rings. The real risks are semantic: RefSpec-minted predicates like `cites`/`amends`
have no SSSOM meaning, and CURIE compaction would degrade to opaque `ns1:`/`ns2:`
prefixes.

**The sharpest detail:** RefSpec's shipped `statements.parquet` (560,429 rows, verified)
contains **481 `entity`-ring statements and zero `value`-ring statements**. So the
allowlist permits a ring with no data and forbids one with data. This is not a blocker —
it is a design assertion guarding an exporter nobody calls. The actual crosswalk (2,003
EuroVoc→LCSH mappings) ships fine through a completely separate pipeline, as N-Quads,
compact JSONL, and Parquet.

# RefSpec's real outputs

Digest-sealed at every layer. Current shape:
`distribution/{atlas-manifest.json, atlas-acceptance.json, atlas-producer-validation.json,
atlas-construction-summary.json, atlas-source-accounting.json, packs/}`, where `packs/`
holds zstd-framed canonical N-Quads (126 packs, ~31M asserted quads) plus a compact JSONL
mirror, alongside `parquet/tables/*.parquet` (8 tables). Packs carry **dual digests** —
content (uncompressed canonical) and transport (zstd) — computed in one pass
(`generate_atlas_v3_full.py:5662-5682`). Publication is atomic via candidate-dir rename.

One real weakness: the version+date is a **hardcoded constant**, not derived —
`DISTRIBUTION_ID = "urn:ref:atlas:distribution:3.0-full-development:2026-08-06"`
(`:116`). Every on-disk build directory, including `…-2026-08-08`, carries that same
`2026-08-06` identity. Directory naming is human convention, unenforced by code.

# Duplication

Real, and in four places:

1. **Label normalisation.** SpicySearch `concept_resolution.py:26-30` (NFKC + casefold +
   token join) vs RefSpec `atlas/model.py:320-322`, `binding.py:341`,
   `vocabulary.py:478`, `policies/federal_register_lists_of_subjects.py:47`,
   `registry/federal_register_thesaurus_2025.py:288-291` — the last of which normalises
   *the same vocabulary*.
2. **Sparse retrieval.** SpicySearch `lexical_postings.py` (BM25 + trigram, DuckDB) vs
   RefSpec `atlas/candidate_retrieval.py` — a full independent sparse engine with
   weighted views (`LABEL_SPARSE_VIEW`, `CONTEXT_SPARSE_VIEW`, `CHARACTER_SPARSE_VIEW`)
   and its own character-ngram features. Both invented character-gram matching
   separately.
3. **Graph expansion.** SpicySearch `expand_within_vocabulary` vs RefSpec
   `candidate_retrieval.graph_neighborhood_neighbors:335`
   ("one-hop-aligned-graph-neighborhood") and `queries.py` `ConceptNeighborhood` /
   `_native_hierarchy_closure`. Same idea, twice, no sharing.
4. **The ring set itself**, duplicated **14 times inside RefSpec alone** — canonical at
   `registry/infrastructure/semantic_foundation.py:26,55`, re-declared rather than
   imported in `atlas_index.py:34`, `v3_source_data.py:47`, `compact_pack.py:354`,
   `publication.py:146` and nine others — *plus* a 15th copy in SpicySearch at
   `vocabulary_atlas_v2.py:26` and a 16th hardcoded in SQL at `concept_index.py:323`.

Note SpicySearch already supports all four rings end-to-end (`vocabulary_atlas_v2.py:26`,
`search_snapshot_runtime.py:726-730` maps each to a filter field) — exercised only by
fabricated test fixtures, since no four-ring data has ever crossed the boundary.

# Where documentation and code diverge

You asked me to ignore `.md` files, so I did — which means I can only report the gap
between the **claims you gave me** (all doc-derived) and the code. Every one of the eight
is wrong, and they fail in a consistent direction: they understate the machinery and
overstate the measurement. The code is *more* honest than the claims about it. The two
most damaging inversions: BM25 is described as losing when it is the largest single win,
and expansion is described as disabled when it runs on every concept query.

Two in-code (not `.md`) staleness findings: RefSpec's `qualification.py:29` cites a moved
SpicySearch path, and `relation_sssom.py` is pinned by sha256 in 16 Atlas-1.0 fixture
manifests at a digest that **no longer matches** the file — decorative, since
`model.py:2253-2271` validates only shape, never re-hashes.

# What I could not determine

- **Where the five numbers came from.** They match no artifact. `0.085` resembles a cost
  field; `35` matches nothing (nearest is 37 capability cases). I can refute them but not
  source them.
- **Whether `services/search` referred to another checkout.** I only found it on an
  unreachable root lineage.
- **Whether Atlas 3.0 could be consumed if wired.** Neither reader accepts
  `schemaVersion: 3.0`; I did not attempt a conversion to see how deep the
  incompatibility runs.
- **RefSpec's own test suite** — I did not run it (I ran SpicySearch's).
- **Concurrency caveat:** RefSpec's working tree changed *during* this session (different
  modified files at the end than at the start), so RefSpec observations are as of the
  moment I read them. All my commands were read-only; I changed nothing.

One more finding worth flagging on its own: **the only real-corpus snapshot no longer
opens.** I ran it — `open_published_snapshot(snapshots/holdout-exam-2026-08-01)` raises
`IntegrityError: SearchSnapshot fields differ from the supported schema`. Three fields
were added to the schema after it was built on 2026-08-01. No test catches this, because
no test reads `snapshots/`.

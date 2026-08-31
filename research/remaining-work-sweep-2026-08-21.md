# Remaining-work sweep — 2026-08-21

Read-only archaeology across spicy-regs, spicy-regs-landing, DocSpec (+ its
legacy archive), rulespec, spicysearch, spicyregs-web, and RefSpec's own
branches and research record. Excludes everything absorbed into canonical
RefSpec today: the citation-grammar union, the Unified Agenda series +
Parquet, the CFR subject index, the FERC/RISC attestations, the EuroVoc
microthesauri work, **and the two ports that landed while this sweep ran**
(`63197925` identifier shapes, `2dd46198` act-name/OLRC resolution — both
verified on the local branch tip and therefore out of scope here).

Two prior surveys cover adjacent ground and were used as maps, then
re-verified rather than trusted: `research/dropped-gems-survey-2026-08-20.md`
and `research/cross-repo-branch-and-salvage-audit-2026-08-20.md`. Items below
marked *(carried)* originate there and were re-checked against today's main.

---

## 0. One operational hazard before any finding

**Canonical RefSpec's remote-tracking refs are fabricated.** The clone-out
copied the old checkout's `origin/*` refs, then the origin URL was re-pointed
to GitHub **without a fetch**. Consequence, verified against the live remote:

| ref | local `origin/*` says | GitHub actually has |
|---|---|---|
| `atlas-v3-binding-and-relation-research` | `3db57e5d` (today's WIP) | **`f251e3b4`** (2026-08-15 era) |
| `main` | — | `2a6e61a2` |

`git status` therefore reports the branch ~5 ahead when the true unpushed
count is **52** (`f251e3b4` is an ancestor of local HEAD; verified with
`merge-base --is-ancestor`). Also: GitHub holds **27 branches** — including
~19 `research/*` and `spike/*` heads the local clone's branch carrying missed
entirely. First action in canonical should be `git fetch origin` so every
ahead/behind number stops lying.

---

## 1. Ranked findings

### 1. A 993-document Federal Register corpus WITH FULL BODIES already exists
**Location:** `~/Work/corpora/_preserved-2026-08-10/body-retrieval-corpus-2026-08-02/`
(5.3G) and an identical copy at `~/Work/spicy-regs/output/body-retrieval-corpus-2026-08-02/`.
Producer: `spicy-regs/src/spicy_regs/corpora/body_retrieval_corpus.py` (1,514
lines, on main), four receipted stages (draw → fetch → validate →
v3-selection).

**What it is:** 993 FR documents (50 CFR 17, Endangered Species Act listings,
2005–2026), every one ≥12 pages (37,838 pages total), fetched as **both HTML
and XML bodies** (1,986 cached body files verified on disk), under a
deterministic draw manifest with digest lock and per-document receipts.
Deliberately drawn for vocabulary *competition* (median pairwise Jaccard
0.163) so retrieval/rank experiments mean something.

**Why it matters:** this session's peers concluded twice that "no corpus with
body text exists locally" and that the citation extractor could only be
measured on titles/abstracts — while 5.3G of receipted FR body text sat in a
directory named for retrieval. Everything gated on "we'd have to fetch
bodies" — measuring footnote-fusion-class extraction damage on real prose,
chunking, BM25-vs-dense, section-level citation joins — has its substrate
already on disk. The `_preserved` README states the copy discipline: same
machine, survives `git clean`, not a disk-failure backup.

**Absorption cost:** move/symlink to canonical `~/Work/RefSpec/output/` beside
the other source-tier data (the preservation README's own hazard list —
"pending spicy-regs reset keeps `git clean -fdx` a live hazard" — still
applies to the output/ copy); point the extraction-measurement work at it.
**If ignored:** every body-text experiment re-fetches ~1,000 documents from
the FR API for data already held, or worse, keeps being "blocked".

### 2. The verifier coverage campaign's unlanded remainder *(carried, re-verified)*
**Location:** GitHub-only branches `research/coverage-csv-pdf` (`22edea`),
`research/coverage-html-misc` (`aa113fe4`), `research/coverage-readers5`,
`research/coverage-patternrow` (24 ahead), `coverage-json`, `coverage-bulk`,
`coverage-dry`, plus `research/shacl-*`, `spike/*`.

**Re-verified today:** `_read_opm_plum_csv` / CBO publication readers — **0
mentions on main's verifier** (grep), 6+ on the branch tips; the descriptor
graph still declares `inventoryOnly` gaps for those units. My check that
branch SourceSpec *names* ⊆ main is consistent with the 08-20 audit's sharper
point: **~42 of the 45 branch-only specs audit registry sources that exist
only on those branches** (e.g. `scotus-opinion-types` — 0 hits on main's
`v3_registry_codes.py`, 3 on `coverage-readers5`). So the remainder is not
"port readers", it is "decide whether those *sources* come to main"; the
readers ride along.

**Delta since the 08-20 audit:** its "four uncovered units" are all closed as
of today — eurovoc-microthesauri by SourceSpec, the three raw-PDF units by
visual attestation (a different route than the branch's planned extracts; the
attestation supersedes the blocker but is weaker than a re-runnable reader,
which those branches still don't contain either).

**If ignored:** the campaign's tier-3 harnesses (`probe_rudof_*.py`,
`JenaBenchmark.java`, parse-substrate stores) stay verdicts-without-harnesses
— conclusions the record cannot re-run. Cost to absorb: per-branch triage, not
one merge; the 08-20 audit's tiering table is still the right map.

### 3. CFR-part → agency crosswalk: built, pinned, 34,612 rows, zero consumers
**Location:** `spicy-regs/output/agency-crosswalk-2026-08-02/` (4 parquet
files); tool `tools/build_agency_crosswalk_artifact.py` (32 tests); evidence
doc `docs/evidence/agency-crosswalk-2026-08-02.md` ("built locally,
digest-pinned, unpublished"; byte-reproducibility verified by double build).

**Verified:** `cfr-part-agencies.parquet` = **34,612 rows** with
`cfr_title, cfr_part, agency_slug, documents, part_documents`. Grep of
spicysearch src: **0 consumers** — the "spicysearch task 1c (CFR-part soft
priors)" it was built to unblock consumed something else or never ran against
it. It is the *agency* leg of exactly the join family built today (part →
subjects, part → RIN); the entity-ring complement, idle since 08-02.

**Absorption cost:** small — it is the same shape as the agenda parquet:
re-home beside canonical source-tier data with its digest pins, or rebuild
from pinned inputs via the existing tool. **If ignored:** the part→agency
question gets re-derived ad hoc (the peers' tagging pass already uses agency
priors — from FR metadata, not from this reconciled crosswalk with its
RULE-010 normalization corrections).

### 4. SCOTUS opinions: full source→transform→CI pipeline on main; data lives in R2, not locally
**Location:** `spicy-regs/src/spicy_regs/sources/supreme_court_opinions.py`,
`transforms/build_supreme_court_opinions.py`,
`.github/workflows/rollup-supreme-court-opinions.yml` (scheduled, uploads to
R2; `skip_upload` dry-run input verified in the workflow).

**Why it matters:** court opinions are the canonical "non-FR document that
cites U.S.C." — the exact document class the citation-transfer question needs
and that the local corpus sweep (correctly) found absent *locally*. The
pipeline exists and runs in CI; nobody this session checked the R2 bucket.
**Absorption cost:** one R2 listing to learn whether opinion text already
accumulates remotely; if yes, the "no non-FR corpus" wall has a door in it.
**If ignored:** the U.S.C.-route experiments keep treating opinion text as
unobtainable.

### 5. rulespec: the wheel RefSpec vendors is built from an unmerged branch
**Location:** `~/Work/rulespec`, branch `feat/rulespec-conformance-package` —
**19 commits ahead of main, 0 behind, never merged** (08-20 audit said the
same; still true). Verified: `dist/rulespec_conformance-0.2.0rc9-py3-none-any.whl`
is namelist-identical to RefSpec's vendored copy.

**Risk:** the source of a load-bearing vendored dependency exists only as a
local unmerged branch on one machine. Merge/push is mechanical. Related but
distinct *(carried, unchanged)*: the move-2 compiler patch
(`research/move2/rulespec-compiler.patch.gz` on RefSpec's `research/move2-compiler`)
references a rulespec state (`0.2.0-pre.10`, `shacl_sparql`) that exists in
**no rulespec ref** — a coherent diff never applied. And the Rust projector
TODO records two real gaps: JSON-LD and OpenAPI `validate()` both return
`Ok(())` unconditionally.

### 6. Orphan engines, still orphaned *(carried; spot-verified on disk today)*
All three re-confirmed present and unconsumed:
- `spicy_regs/docpipeline/retrieval.py` (5,479 lines; dense+sparse+RRF+rerank,
  resumable) — parked by MVP cut, not failure; siblings re-derive RRF ad hoc.
- `spicysearch/known_items.py` — judge-free gold-case builder;
  self-referential test only. Natural fit for the derived-tags pass's next
  validation round.
- `spicy_regs/enrichment/open_set.py` — the reject/accept third tier
  (`rkaf:openLabel`, searchOnly) — the designed answer to "what does the
  tagger do off-vocabulary", blocked only on a review that never happened.
Plus the four-times-built, zero-times-run absent-vs-checked lifecycle family
(RefSpec lifecycle events / rkaf-analysis types / ClosureClaim / negative
segmentation ledger) — unchanged since the gems survey; the build still pins
`lifecycleEvents=0`.

### 7. Small carried items still open, one line each
- **ANN revisit trigger** — precondition (boilerplate-free embeddings) landed
  in the same commit as the rejection; benchmark never re-run (~1 hr;
  `ann_index.py` verified on disk).
- **`parquet_preflight.py`** — 3.5-second vectorized gate, in no Makefile
  target, now stale by three optional members (~1 hr to revive; would have
  been the fast pre-build check this week's two 90-minute build failures
  argued for).
- **Scope notes left on the floor** (gems §6): descriptor scope-note text
  exists in pinned sources but is not carried — relevant to tagging-time
  disambiguation.
- **DocSpec current** is active and clean (sealed HTTPS acquisition → wire
  releases → DocumentRelease; wheel 0.2.0 in dist) — its lane, nothing
  stranded; `output/qualification` holds one FR-mirrulations qualification
  run.

---

## 2. Divergences where the wrong copy could win

- **Stale `origin/*` refs in canonical RefSpec** (§0) — the newest-*looking*
  remote refs are fabrications; the real remote is older. Fetch before
  trusting any ahead/behind.
- **spicy-regs `feat/rkaf-boundary-freeze`** — 632-file diff vs main is an
  *archived pre-reset snapshot* (its own commit `002d56c` says so), not newer
  work; every unique-looking module on it (mirrulations corpus, extraction
  bakeoff, SCOTUS workflow) verified present on main. Safe to treat as
  archive; do not "rescue" from it over main.
- **spicy-regs-landing** — HEAD `ca4f4b3` is an ancestor of spicy-regs'
  branch (246 behind). Its `source_catalog/` package looks unique but was
  deliberately deleted later on the live line; landing is a frozen older
  checkout, nothing to salvage beyond two logo assets.

## 3. Checked and found empty (so the next sweep can skip)

- **spicy-regs:** no stashes; no unreached wip commits (all wip-grep hits are
  on main or the archive branch); remote infra branches
  (`feat/document-ai-pipeline` 161-ahead, `feat/cf-container-scale` 22-ahead,
  `claude/*`) are pre-pivot GCP/CF deployment work, superseded by the current
  local-artifact architecture.
- **spicy-regs-landing:** nothing unique beyond §2; `.ruff_cache` noise and
  two Civic Tech DC logos.
- **DocSpec legacy archive:** tools set is a strict subset of spicy-regs'
  (verified with `comm`: zero legacy-only tools); `citations.py` is an older
  ancestor (993 vs 1,025 lines, pre-trailing-punctuation-fix) of the copy
  today's grammar was unified from; mcp-server is a single `_published.py`
  stub. The archive is fully superseded.
- **rulespec:** vendored wheel byte-set-identical to `dist/`; no stashes.
- **spicysearch:** clean tree, single branch, no stashes; post-08-19-prune
  state matches the audit's record. Active modules (query_parser,
  vocabulary_lookup, topic_tags, retrieval_lanes, date_events) are the live
  search lane, not strandings — the seam ("RefSpec owns what a citation *is*,
  spicysearch owns what a *query means*") stays as drawn.
- **spicyregs-web:** a static Astro hackathon landing site (3 TS files); no
  data or parsing work whatsoever.
- **RefSpec local branches:** `feat/parse-substrate` and the three local
  `research/*` heads are superseded development lines — parse substrate
  landed on main as `ae34392c` (branch tip adds no validate.py functions main
  lacks); all three coverage branches' SourceSpec names ⊆ main. Deletable
  after push, per the 08-20 tiering (which keeps the *GitHub* research heads
  for their harnesses).

## 4. What this sweep did not do

Did not open the R2 bucket (finding 4's one-step follow-up), did not read the
19 GitHub-only branch trees beyond targeted greps (the 08-20 audit's tiering
stands as their map), and did not row-count every `output/` directory —
receipts were preferred where present, and `output/` dir names were only
trusted after at least one interior check.

---

## Resolution of finding 2 (coverage-campaign remainder) — 2026-08-21, same day

Triaged to completion rather than ported. The full-tuple, runtime-level
comparison (main's verifier covers 127 release keys at runtime; text-level
extraction undercounts it by half because most specs are factory-built) leaves
**26 true branch-only spec keys**, and every one names a unit today's registry
does not hold:

- **Deleted by decision**, not unlanded: `scotus-opinion-types` ("four side-nav
  links plus three phrases regexed out of page prose" — REF-033's words),
  `sec-series-categories`, `nasbo-program-areas`, `census-acs-geography-identifiers`
  (same REF-033 batch); `cbo-119th-congress-publications`,
  `govinfo-cfr-package-bounded`, `fcc-ecfs-proceedings` (REF-031 document
  populations); `sam-cage`/`sam-uei`/`nppes-npi`/`epa-comptox` bounded samples
  (REF-030 registrant populations); the fcc-ecfs control lists (REF-032's own
  note: the published bureau roster is a named follow-up, the observed one
  left).
- **Superseded at different granularity**: `opm-plum-position-status-codes-2026-08-04`
  — the sweep's own "0 mentions on main" finding is true of the *standalone
  unit*, which main refolded into the OPM/EHRI family (REF-033), where it is
  covered; `nrc-adams-*-bounded` superseded by main's six-input NRC union;
  `agrovoc`/`nalt`/`epa-label-tree`/`federal-hierarchy` bounded captures
  superseded by the full units; `lcsh-eurovoc-alignment-endpoints` by the
  eurovoc-lcsh-alignment spec; `treasury-fast-book-fund-types` deleted while
  its sibling accounts unit survived and is covered.

So the campaign's portable remainder is **empty**: main's registry has 130
units, 127 carry runtime SourceSpecs, and the 3 without
(`ferc-docket-prefixes`, `ferc-document-class-types`,
`unified-agenda-legal-authority-citation-types`) are covered by the 08-21
visual attestations — a deliberate, weaker-but-recorded route. What the
branches still hold of value is exactly what the 08-20 tiering said: the
tier-3 harnesses (`probe_rudof_*.py`, `JenaBenchmark.java`, parse-substrate
stores), preserved on the now-fetched GitHub heads. Porting audits of deleted
units would have re-litigated four REF decisions by side door.

# RefSpec intake ledger — 2026-08-31

> **Superseded 2026-09-04.** Read
> [spicy-regs `docs/disposition.md`](https://github.com/civictechdc/spicy-regs/pull/193)
> instead. This page records what was PLANNED on 2026-08-31; it is no longer a
> record of what exists, and three of its claims are now false in a way that
> would cost a reader real work:
>
> - **§1's six ports all landed, on the day this was compiled.** `5b8f4d8b`
>   (the last two frozen USC artifacts get their builders back), `582461fe`
>   (the minting layer arrives, and the agency crosswalk beside it) and
>   `2b4960e1` (assert_acyclic is asserted, not narrated) — four of them before
>   this file's own last edit at 17:14. §1.1 in particular still says RefSpec
>   "mints USC only" and quotes `identifier_shapes.py`'s header as declaring
>   the gap; `iri_minting.py` has carried all seven minters since `582461fe`.
> - **§2.2 was ruled the same day** by REF-053 in
>   [the decision ledger](../docs/decisions.md) — open-vocabulary concept
>   lifecycle stays unported, no owner, no consumer, no check. It is not
>   awaiting a ruling.
> - **§5 item 3 is wrong.** SpicySearch has neither `ann_index` nor
>   `candidate_channels`; both greps return zero files under `src/`.
>
> **Two later intake items, ruled 2026-09-04** (spicy-regs PR #193), recorded
> here so the ledger stays the place intake questions are closed:
>
> - **`canonical_usc_chapter_iri` — RETIRED, not ported.** It is the one of
>   eight minters the 08-31 port left behind, and it stays behind: nothing in
>   RefSpec references it, it exists only in spicy-regs'
>   `ontology/citations.py`, and USC IRI minting already lives here in
>   `act_resolution.py:304` with the other seven covered by
>   `iri_minting.py`'s `mint_*` functions. Porting it would add an eighth
>   minter nothing calls, which this repository's own rule forbids: structure
>   arrives with the consumer that breaks without it.
> - **spicy-regs' `ontology/rulespec_release.py` publish gate — NOT ported,
>   and the reason is upstream of RefSpec.** Those 178 lines recompute the L0
>   contract digest from a tagged rulespec archive, which is the right design
>   and is currently *refusing rather than verifying*: spicy-regs'
>   declaration carries `rulespec_release: null` and fails publication closed
>   while the contract is an unreleased candidate. RefSpec says the same thing
>   in `profiles/rulespec-dependency.json` with `localUnpublished` and
>   `productionConformanceEligible: false`. Both are downstream of rulespec
>   having published exactly one tag, `v0.2.0-pre.7`, 114 commits behind its
>   own HEAD at `0.2.0-pre.18`, while RefSpec and SpicySearch both pin
>   `==0.2.0rc18` from hand-copied vendored wheels. Porting the gate before
>   there is a release to verify buys a more elaborate way of saying what the
>   profile already says honestly. Reopens if rulespec tags a release.
>
> Kept rather than deleted because the reasoning behind each intake decision is
> still worth reading, and because a plan that was executed is evidence of how
> the work was scoped. Every claim above was verified against this checkout
> before it was written here, not carried across from the report that raised
> them.

Everything that should be ported, salvaged, diverted, or merged **into RefSpec**,
from the corpora archives (`~/Work/corpora/`), the nugget extraction
(`~/Work/corpora/_nuggets-2026-08-27/`), spicy-regs, and SpicySearch. Compiled
2026-08-31; every "what RefSpec has today" claim below was verified against this
checkout's code on that date by running or reading it, not recalled from the
2026-08-27/28 archive sweep (several sweep claims were already stale — noted
where they were).

This ledger covers intake **from outside the repo**. Its in-repo companion is
[`research/investigations-mined-2026-08-31.md`](../research/investigations-mined-2026-08-31.md)
— the same-day mining of RefSpec's own investigation directories into a ranked
fix backlog. Both streams draw on the same engineering capacity and §6 sets
them against each other; neither is complete without the other.

Provenance for measurements: the nugget README and sweep appendix at
`~/Work/corpora/_nuggets-2026-08-27/README.md`, whose entries were established
by executing both implementations against real corpora. Ports follow the
platform rule: **reimplement, never copy** (DocSpec spec §4.4's rule generalized
platform-wide); the archived source is evidence and reference, not a payload.

---

## 0. Merge first — the fork (gates everything below)

> **RESOLVED 2026-08-31 by REF-051** (`docs/decisions.md`): the fork was
> history, not content — the archived line's unique content is superseded
> early drafts, and its five build commits are absorbed. **This checkout is
> canonical; every port lands here.**
>
> **Measurement erratum (validated 2026-08-31, six-agent retention audit +
> independent codex re-derivation; full record at
> `~/Work/corpora/_retained-2026-08-31-refspec-branches/`):** REF-051's
> recorded figures do not reproduce. Verified: ONE submodule-only path (the
> rc15 vendored wheel, superseded by rc16 — no content loss), not zero; and
> `git diff --numstat 64a55685 141fd671` gives 56 files / 2,869 archive-side
> lines (all paths), 35 / 721 under `src/ tests/ tools/ bindings/`
> (direction-sensitive: reverse is 56/2,867 and 35/724 — restatements must
> name their direction), not "63 files / 579 lines". The audit also confirmed
> the supersession itself at content level, including the one absent mechanism
> (`cfr_additional_parts`), which the archived branch itself superseded 9m29s
> after writing it. Disposition unchanged; amend the register's figures.
> Nothing deleted: the submodule line survives as
> `refs/snapshots/pre-consolidation-2026-08-28` (spicysearch side) and
> `refs/snapshots/submodule-line-2026-08-31` (this repo's object store).
> The spicysearch submodule repoint is a mechanical follow-up awaiting a clean
> worktree there. The gate below is kept for the record.

RefSpec existed as two diverged checkouts:

- `~/Work/spicysearch/RefSpec` (submodule) at `141fd671` — **54 commits not in
  the standalone checkout** (protected by snapshot ref
  `refs/snapshots/pre-consolidation-2026-08-28`);
- `~/Work/RefSpec` (standalone, this repo) at `3464bda2` (at compilation time)
  — **12 commits not in the submodule**.

`git merge-base --is-ancestor` confirms neither contains the other. Landing any
port before reconciling picks a side by accident. This is item 8 of the
2026-08-28 path-forward memo
(`spicysearch/docs/history/2026-08-28-path-forward-memo.md`), decision pending
with the product owner.

---

## 1. Ports — code to reimplement in RefSpec

### 1.1 The minting layer (7 IRI minters)

- **From:** `_nuggets .../source/src/spicy_regs/ontology/citations.py:384-604`
  (CFR, executive order, RIN, FR document, regulations.gov docket, public law,
  partner-defined).
- **RefSpec today:** mints USC only
  (`src/refspec/registry/act_resolution.py:304`, `urn:rkaf:us:usc:...`). The
  shapes/validators for everything else already live here
  (`registry/citation_grammar.py`, `registry/identifier_shapes.py`), and
  `identifier_shapes.py`'s own header declares the gap: *"IRI minting
  (`urn:rkaf:...`) stays with consumers until the minting layer is its own
  port."* No consumer mints either — zero `urn:rkaf` producers exist outside
  `act_resolution.py` anywhere on the platform.
- **Action:** implement the seven minters beside the USC one, wrapping the
  already-ported shapes. rulespec owns the IRI grammar normatively; a grammar
  is not a minter, so the executable minting belongs here.

### 1.2 Bare-legacy Federal Register document mint

- **Measurement:** **394,128 of 1,004,233 (39.2%)** real FR `document_number`
  values are the bare-numeric legacy shape (`09-19806` — no letter prefix,
  two-digit year; essentially every pre-2000 document).
- **RefSpec today:** invisible. `detect_identifier_shapes("09-19806")` returns
  `[]` even in `FR Doc. 09-19806` labeled context (verified by execution
  2026-08-31), `is_federal_register_document_number` refuses it, and — unlike
  the letter-opening forms — this class appears nowhere in the module's
  documented exclusion accounting.
- **Action:** mint it as a **column-reader** job, per the module's own
  two-readers doctrine ("the column is the license"): the value arrives from a
  trusted `document_number` field, so minting it requires no loosening of prose
  detection, which stays exactly as narrow as it is.
- **Why it is urgent now:** SpicySearch's text-ingest lane landed 2026-08-31
  and the pre-2000 FR bodies are salvaged and waiting
  (`_salvage-2026-08-28/spicysearch-output/`). Ingesting them today gives 39%
  of the historical corpus body text with no first-class identity — links and
  joins to those documents dead-end.

### 1.3 Popular-names parser (OLRC `popularnames.htm`)

- **From:** `_nuggets .../source/src/spicy_regs/sources/uscode_olrc.py`
  (Statutes-at-Large volume recovered from the `statviewer` query;
  cite/see/renamed/short-title-ref distinguished; ambiguous names refused).
- **RefSpec today:** `registry/usc_act_index.py` regenerates the **Table III
  half** of the act index from OLRC's bulk file in-repo (48,973 acts, 317,590
  classification records, no network) — the sweep's "no regeneration path"
  claim is half-stale. But `usc-popular-names.parquet` is **carried over
  byte-identically** from the prior artifact (`--popular-names-from`,
  `usc_act_index.py:428,532`); no code in this repo can re-derive it.
- **Action:** port the parser. Closes half of RefSpec's last dependency on
  abandoned code.

### 1.4 USC source-credit builder (USLM parsing)

- **From:** `_nuggets .../source/src/spicy_regs/sources/uscode_uslm.py` +
  `tools/build_usc_source_credit_artifact.py` (requires explicit "Added"/"as
  added" language; bounds the Statutes-at-Large lookup at the next citation).
- **RefSpec today:** consumes the frozen source-credit artifact
  (`act_resolution.py`); no builder exists in `src/` or `tools/`.
- **Input data:** already salvaged —
  `_salvage-2026-08-28/refspec-output/usc-annual-2026-08-24` (USC annual zips,
  2.1G, 73 files, per-file SHA-256 verified).
- **Note:** spicy-regs PR branch (d) `feat/uscode-uslm-source-credits` *offers*
  this parsing upstream; whether Eugene takes it is independent of RefSpec
  owning its own regeneration path. The other half of item 1.3's dependency.

### 1.5 Agency crosswalk rules (FR ↔ regulations.gov agencies)

- **From:** `_nuggets .../tools/build_agency_crosswalk_artifact.py` — no
  docket-prefix inference, decorated-ID normalization only when it resolves to
  a unique docket, 0.05-share sub-agency preference.
- **Receipt:** tier histogram `confident:124 / probable:29 / ambiguous:23 /
  unmapped:140` over 715,080 FR-docket-link rows; sealed artifact + receipt
  preserved at
  `_preserved-2026-08-27/spicy-regs-output-complete/agency-crosswalk-2026-08-02/`.
- **RefSpec today:** nothing comparable (verified: "crosswalk" grep hits are
  coincidental vocabulary files).
- **Action:** port as a registry module. It is curated reference data —
  RefSpec-shaped.

### 1.6 Acyclicity/append-only micro-invariants (nice-to-have)

- **From:** `_nuggets .../source/src/spicy_regs/ontology/invariants.py:14`
  (`assert_acyclic` and friends); sweep verdict "worth re-adding as-is."
- **RefSpec today:** the concept is enforced in one place
  (`registry/infrastructure/managed_vocabulary_bundle.py:105` refreshes "a
  closed acyclic set"), not available as a general assertion.
- **Priority:** low; take opportunistically with 1.1.

---

## 2. Decisions — documented questions awaiting a ruling (no code yet)

### 2.1 Letter-form FR widening (recall decision)

> **RULED 2026-08-31 by REF-052** ("The column is the license",
> `docs/decisions.md`): makes the call this section asked for and licenses
> the bare-legacy mint (§1.2). Kept below for the record.

`identifier_shapes.py` deliberately leaves **10,340 letter-opening FR document
numbers unread** (three-digit-and-shorter tails, two-digit prefixes, six-digit
tails, legacy-prefix-over-modern-body hybrids — each with a verified live
example) and states: *"Widening is a recall decision with its own
false-positive budget in running text, not a defect to be quietly patched; the
numbers are here so that decision can be made with them."* The decision has an
evidence base and no owner. Make the call; do not patch.

### 2.2 Open-vocabulary concept lifecycle — ownership

The nugget (`ontology/concepts.py:202-224,395-419` — candidate
minting/promotion/deprecation, multi-source quotas; plus `concepts.py:1223`
`merge_pass`, merges bounded to one facet and source vocabulary) has no home.
RefSpec owns vocabularies (managed bundles) but is closed-world by design;
SpicySearch is strictly closed-vocabulary, one scheme per build. **Rule
ownership before any port.** Until ruled, it stays a nugget-ledger row.

---

## 3. Divert — consolidation from SpicySearch

### 3.1 Retire the duplicate shape knowledge

`identifier_shapes.py` was ported *from* SpicySearch's `identifiers.py`, and
both copies are live: SpicySearch still runs its own query-side detector.
The RefSpec module's header calls the two spellings drifting apart "the defect
this module keeps producing." The query-*policy* ("is this string an identifier
lookup") stays in SpicySearch by explicit design — but the shapes themselves
should be read from RefSpec once, not maintained twice. Bundle with port 1.1.

---

## 4. Salvage — data that stays in corpora, named as RefSpec's inputs

> **SUPERSEDED 2026-08-31 by REF-055** (`docs/decisions.md`): the owner
> ruled corpora a temporary staging ground, and the come-home wave moved
> everything RefSpec-shaped into the repo's own `output/` and
> `research/evidence/` with the corpora copies retained as second copies.
> See `docs/regeneration-inputs.md` for the per-path state. Kept below for
> the record.

Nothing here moves into the repo. `~/Work/corpora/` is the durable home
precisely because gitignored in-repo output trees were destroyed repeatedly
(the platform's measured failure mode is loss, never tamper). The action is
that RefSpec's receipts and docs **name these paths** as regeneration inputs:

| Corpus path | Contents | RefSpec relationship |
| --- | --- | --- |
| `_salvage-2026-08-28/refspec-output/` | original 302k-row act index, ~120 dated Zyte/Wayback/bulk registry captures, GAO execution receipts, claim releases, view pins, vocabulary portfolio | outputs/pins with no or expensive regeneration |
| `_salvage-2026-08-28/refspec-output/ecfr-title-xml-2026-08-24` | 773M, 52 files, manifest + fetch log | refetchable but **not re-pinnable** |
| `_salvage-2026-08-28/refspec-output/usc-annual-2026-08-24` | USC annual zips, 2.1G | **feeds port 1.4** |
| `_salvage-2026-08-28/refspec-output/atlas-3.1-full-2026-08-21d` | 2.0G full atlas build | parent of the newest search view |
| `atlas-3.1-parquet-search-view-{2026-08-17,-20,-21c}` | Parquet search views | **pinned by exact path in SpicySearch tests** — do not move or delete without re-pointing them; `-21b` appears unpinned; several dirs share content via hardlinks (`du` under-reports them) |
| `_preserved-2026-08-27/vocabulary-atlas` | 8 atlas versions incl. hand-audited v5-audited | lineage evidence |
| `_preserved-2026-08-27/fused-concept-registry-v1` | 513,236-concept fusion incl. LLM-minted terms | lineage evidence, 15+ downstream citations |
| `refspec-registry-unified-agenda-parquet/` | receipted export of `registry/unified_agenda_parquet.py` | durable pin; regenerable; fine where it sits |

---

## 5. Explicitly NOT RefSpec's (closing the list)

- **SourceCatalog** — DocSpec owns it (REF-048); no RefSpec↔DocSpec direct
  edge exists (REF-022).
- **Exact document joins** (`fr_doc_num`, `docket_id` raw-value joins) —
  DocSpec, by design; never through minted IRIs.
- **SPLADE / cross-encoder reranking / ANN index / candidate channels /
  embedding batching** — SpicySearch's retained-value rows.
- **Source-domain drift gate, FR result-cap fix, Unified Agenda date fix, r2
  preflight** — upstream spicy-regs PR branches, already cut and CI-green.
- **SKOS one-hop expansion** — already recreated in SpicySearch
  (`related_topics.py`, "under newer policy" per sweep r10).
- **Loose docket join concept** — already absorbed: RefSpec's docket grammars
  (organization caps, office segments, licensed two-digit years, label rules)
  carry the measured lessons, and RefSpec won the join head-to-head
  (7,556 vs 96). Done.

---

## 6. In-repo intake — the mined investigations backlog (by reference)

[`research/investigations-mined-2026-08-31.md`](../research/investigations-mined-2026-08-31.md)
is the authoritative version of everything in this section; nothing below is
restated with enough precision to act on. It mined all sixteen
`research/evidence/investigations-2026-08-2{3,4}/` directories against shipped
code and the byte-verified rebuild-#12 artifact, re-measuring every population.
What it holds, and how it interacts with this ledger:

- **Nine silent-wrong-answer classes, ranked by blast radius** — values RefSpec
  publishes wrongly *today* with no refusal beside them. The top of the list:
  the B8 two-witness enlargement (1,101 net-new publishable readings), the
  case-sensitive annual-archive extractor (1,912 `exists`-but-unattested rows
  that are extractor holes, not history), reg-shaped citations truncating in
  the U.S.C. slot (77 affirmed-wrong rows), Statutes-at-Large pages fabricating
  U.S.C. citations (148, a new find), and the missing Executive Order existence
  oracle (2,876 rows passing an inadequate fence).
- **A "loud" additive tier** — roster retiers, the apostrophe-year shape,
  `usc_slot_reading`, the paren-suffix promotion, placeholder candidates —
  no wrong answer today, measured value waiting.
- **Five falsified-prose notes in digest-pinned modules** — each forces a
  rebuild if touched, so each is bound to ride the next unit that touches its
  module, never a drive-by.
- **A durability warning that belongs to §4's doctrine:** sixteen of the 32
  EO-gap numbers (1,173 corpus rows, EO 12866 among them) resolve **only**
  from Wayback captures whose bytes exist nowhere but the committed
  `inv-eo`/`inv-eo-gap` directories, sha256-manifested. Those directories are
  pinned publisher evidence, not prunable research — the in-repo counterpart
  of the corpora salvage rows above.
- **A landed-and-verified list** — do not re-litigate; the sweep-staleness
  lesson of this ledger applies to those READMEs too (several describe
  already-fixed defects in present tense).

**Priority interaction:** the backlog's ranked tier publishes wrong values
today; this ledger's ports add missing capability. By this repo's own
correctness-first posture, backlog items 1–5 outrank every port in §1 except
1.2 (bare-legacy FR mint), which is the same kind of defect — a silently
identity-less 39.2% — and can be scheduled with them. The promotion ceremony
the backlog file defines (dated evidence home, pinned bytes, reader, receipt
line, breaking test) is also the ceremony §1's ports should arrive through.

---

## Suggested packaging

1. **You:** merge ruling (§0), then the two one-sentence rulings (§2).
2. **Correctness lane (first):** §6 backlog items 1–5 plus port 1.2 — the
   things publishing wrong or identity-less answers today.
3. **"Identity" package:** 1.1 + 1.2 + 3.1 — one lane, ends with every FR
   document mintable and one copy of the shape knowledge.
4. **"USC regeneration" package:** 1.3 + 1.4 — ends RefSpec's dependency on
   abandoned code entirely. Note 1.3/1.4 and §6 item 2 (the extractor fix +
   re-pin) all touch the oracle/act-index artifact lineage — cheapest as one
   re-pin cycle, not three.
5. **Standalone:** 1.5 crosswalk; 1.6 rides along when convenient; §6's loud
   tier as capacity allows.

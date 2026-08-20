# Tagging assets across the SpicyRegs / SpicySearch / RefSpec repos

Survey date 2026-08-20. Six parallel repo surveys plus direct measurement
against the sealed Atlas 3.1 distribution
(`output/atlas-3.1-parquet-search-view-2026-08-20`, seal `79bfeb55…`).

Every claim below that is a number was measured by running the query shown
in this document's method notes, not taken from a subagent's report. Where a
subagent's claim mattered, it was checked: file existence, line counts, and
for the two engines, by running their test suites.

## 1. The headline

Two independent, working tagging engines already exist. Nothing needed to be
recovered from history, and nothing usable exists in the web repos.

| | **spicy-regs** `src/spicy_regs/ontology/` | **spicysearch** `label_match_*` |
|---|---|---|
| Method | LLM structured output + hybrid candidate generation | deterministic gazetteer, model-free |
| Channels | anchored lexical, char-3-gram, dense BGE, LLM keyword generation, BM25; fused by RRF k=60 with per-scheme quotas | longest-span exact label match |
| Vocabulary | `fused-concept-registry-v1`, 513,236 rows | **RefSpec Atlas directly** |
| On ambiguity | ranks and scores | **abstains** |
| Evidence | exact character offsets, validated and repaired | byte spans |
| Tests | 117 passing | 45 passing |

They are complementary rather than redundant: one is willing to guess, the
other refuses to. Both suites were run for this survey; all 162 pass.

### Correction to an earlier claim

It was previously recorded that no regulatory document had been tagged
against this corpus. That is wrong. Real tagging runs exist:

- `output/mixed-real-data-*/concept_assignments.parquet`
- `output/rulespec-realworld-iteration-{2,3}*/concept_assignments.parquet`
- `output/segmentation-tagging-*-v4/tagging_concepts.parquet` (969 rows)

The largest is 239 LLM assignments over ~69 subjects spanning nine subject
types (document 24, docket 24, then gao_report, fcc_filing, lobbying_filing,
comment, cfr_section, federal_register_document and
regulatory_agenda_observation at 3 each), `method='llm'`, with
`evidence_json` grounding.

What is true is narrower: nothing at corpus scale, and nothing against Atlas.
Every run tagged into the fused registry.

## 2. The answer key exists, at scale

`spicy-regs/output/rulespec-stabilization-candidate-final/federal_register.parquet`
(and eight identical siblings):

- 1,004,233 Federal Register documents, 1994-01-03 to 2026-07-23
- **114,220 carry publisher-assigned `topics_json`** (11.4%)
- 571,713 topic assignments, 900 distinct topics, **5.01 topics per document**
- 521 distinct agency combinations, 4 document types
- **all 114,220 carry a `body_html_url`**, so body text is fetchable

This is real Office of the Federal Register indexing, multi-label, not a
proxy. Example:

```
["Administrative practice and procedure", "Confidential business information",
 "Energy conservation", "Household appliances", "Imports",
 "Intergovernmental relations", "Reporting and recordkeeping requirements",
 "Small businesses"]
```

A parallel survey of `corpora/`, `spicysearch/` and `sample-data/` concluded
that publisher topics were empty everywhere and that evaluation should target
*agency* instead. That holds for regulations.gov — its `topics`, `category`,
`subType` and `sourceObservedTopics` fields are confirmed empty across all
1,993,040 catalog rows — but it did not scan `spicy-regs/output/`, where the
Federal Register answer key sits. Evaluate against topics.

## 3. Vocabulary coverage of the answer key

The recall ceiling that exists before any model runs. Type level counts
unique vocabulary terms; token level weights by how often documents actually
get labelled with them.

| | unique terms | actual assignments |
|---|---|---|
| FR Thesaurus 2025 (what the engine tags into today) | 66.9% | **89.9%** |
| All of Atlas | 90.8% | **93.6%** |

The type-level figure flatters Atlas badly. Weighted by real usage the FR
Thesaurus already reaches 89.9%, and Atlas buys **+3.7 points**, because the
346 terms the thesaurus misses are overwhelmingly rare long-tail commodities
— prunes, tangerines, pistachios, nectarines.

### 95% of Atlas's remaining gap is a single term

| topic Atlas cannot express | uses |
|---|---|
| **incorporation by reference** | **34,920** |
| customs duties and inspection | 739 |
| prunes | 99 |
| tangerines | 94 |

`incorporation by reference` alone is 6.1% of all 571,713 assignments;
Atlas's total uncovered share is 6.4%. Adding this one concept would move
Atlas from 93.6% to roughly 99.7%.

It is a regulatory term of art — the rule adopts an external standard by
citation — so it is a *document property*, not a subject. It belongs in a
value/property ring, not the subject ring.

## 4. The answer key is not a subject vocabulary

Of the 346 FR API topics the FR Thesaurus cannot express, Atlas covers them
across three different rings:

| covered by ring | topics |
|---|---|
| subject (LCSH / FAST / MeSH / …) | 230 |
| entity (agencies) | 71 |
| value | 54 |
| absent from Atlas entirely | 96 |

(Sums exceed 346: one string can sit in several rings.)

The key mixes subjects (`Heart diseases`), commodities (`Barley`,
`Asparagus`, `Blueberries`), chemicals (`Arsenic`), geographies
(`Nicaragua`) and agencies (`Customs and Border Protection Bureau`).
Tagging it well means routing a candidate to the correct ring — which is
what Atlas's ring structure is for, and which neither engine does today.

The residual 96 are mostly US-government named bodies and inverted agency
forms (`Immigration Review, Executive Office for`; `Vice President of the
U.S., Office of`), CPSC product categories (`Lawn darts`, `Swimming pool
slides`), and terms of art. Several would match Atlas's agency entity ring
after un-inverting the name — a cheap normalisation win. Data-quality note:
the source misspells `Millenium Challenge Corporation`.

## 5. The gazetteer must stay scheme-scoped

`VocabularyLookup.build(view, scheme_id=…)` is single-scheme by construction
and `suggest()` abstains whenever a normalised string reaches more than one
concept. Measured against Atlas's 1,375,960 distinct English label strings:

| | strings | share |
|---|---|---|
| resolve to exactly one concept | 769,577 | 55.9% |
| ambiguous **across schemes only** | 587,267 | 42.7% |
| ambiguous **within a scheme** | 19,116 | 1.4% |

Worst case: one string reaches 84 concepts.

**92.3% of the cross-scheme ambiguity (541,430 of 586,752) is confined to the
LCSH/FAST family** — and FAST is derived from LCSH, so those are the same
concept carried in two schemes, not homonyms. Sampling confirms it:
`contractual limitations`, `shi literature`, `israeli literature (hebrew)`
each appear in exactly `{lcsh-subjects, fast-topical}`.

Scoped to one scheme, abstention is nearly free:

| scheme | within-scheme abstention |
|---|---|
| gcmd-science-keywords | 20.73% |
| nasa-thesaurus | 18.95% |
| lcsh-subjects | 1.18% |
| fast-topical | 0.50% |
| eurovoc | 0.32% |
| mesh-descriptors | 0.00% |

So: run the gazetteer **once per scheme and reconcile across schemes
afterwards**. Do not build one pooled lookup — pooled, the same abstention
rule discards 42.7% of strings, and 92% of those discards are triggered by
two related authorities *agreeing*. GCMD and NASA need real within-scheme
disambiguation; nothing else does.

## 6. Two Federal Register vocabularies, unconnected

| scheme | concepts | role |
|---|---|---|
| `federal-register-thesaurus-2025` | 705 | what the engine tags into |
| `federal-register-api-topics` | 1,044 | what documents are labelled with |

They share 698 preferred labels verbatim, but Atlas asserts **zero** mappings
between them — FR-topics has 1,428 `skos:related` edges and FR-thesaurus
1,451, every one of them internal to its own scheme. Both are isolated
islands.

Evaluation therefore works today only by string coincidence, not by asserted
identity. That is worth closing: the two schemes come from the same
publisher, which bears directly on standing under REF-035.

The seven thesaurus terms absent from the API list are all newer policy
concepts: Alternative fuels, Federal Reserve System, Human trafficking,
Postal Service, Selective Service System, Telemedicine, Weapons of mass
destruction.

## 7. What Atlas would lose

`fused-concept-registry-v1` breaks down as fast-topical 440,599, **epa-tsca
70,736**, FR thesaurus 936, crs-subjects 932, crs-policy-areas 33.

Atlas contains everything there except **epa-tsca**, and adds LCSH (514,837),
MeSH (31,110), EuroVoc, GEMET, GCMD, NASA, DOE-OSTI, ICPSR, ELSST plus the
entity and value rings.

Atlas carries **no chemical inventory at all** — no TSCA scheme, zero CAS
identifiers. Those 70,736 substance names (`Benzoic acid, 3-methyl-, zinc
salt (2:1)`) are the one thing a swap to Atlas would lose, and they matter
for EPA rulemaking, which is the second-largest agency in the labelled set
at 19,248 documents.

## 8. Measured retrieval evidence already on record

`spicy-regs/docs/evidence/candidate-selector-ablation-2026-07-28/` — nine
configurations over the 513K registry against 35 frozen dev segments. The
best configuration surfaced only **5 of 8** exact-alias targets.

Two readings the committed README draws, plus one it does not:

1. Dense retrieval (channel C) **reorders rather than discovers** — `v2+C`
   scores the same 4/8 as `v2` while mean rank drops 5.25 → 2.0.
2. The per-scheme quota buys balance: `v2-noquota` reaches 5/8 but
   adequate-kept collapses 4/5 → 2/5 as fast-topical floods 75% of slots.
3. **Not in the README:** fusion loses what its own channels find. `D-alone`
   surfaces `fisheries management`, but `v2+D` does not — RRF plus quotas
   suppress a target that a constituent channel had already retrieved.
   `immigration law` is found by **none** of the nine configurations.

LLM free-keyword generation (channel D) is the only channel that finds
genuinely new terms: `D-alone` surfaces `fisheries management`, `free
speech` and `poultry inspection`, none of which the lexical channels reach.

## 9. Corpora: the join works, but the obvious corpus is degenerate

`fr-mirrulations-1k-v1` has full body text (avg 27.5 KB) for 1,000
documents. Joining `document_id` → `federal_register.document_number`
matches 641, of which **630 carry topics**.

That set is unusable as an evaluation corpus: those 630 documents use only
**5 distinct topics** from a single agency, and four of them
(`Safety`, `Air transportation`, `Aircraft`, `Aviation safety`) appear on
**all 630**. The upstream draw was 99.97% FAA airworthiness directives. A
constant predictor scores near 100% — precisely the failure mode
spicysearch's own benchmark already hit, where the real engine lost to
`constant_majority` on nDCG@10 (0.30 vs 0.49).

The join mechanism is sound; the sampling frame should be the full 114,220
labelled documents (521 agency combinations, 900 topics), with body text
fetched via `body_html_url`.

## 10. Confirmed absences

- **Archive refs hold nothing lost.** `archive/pre-reset-2026-08-09`,
  `archive/local-work-2026-08-09` and `origin/feat/document-ai-pipeline` are
  byte-identical to `main` on every core tagging file, verified blob by blob;
  `main` is strictly ahead (`ontology/llm.py` has 33 extra lines).
  `origin/claude/etl-extract-throughput` has zero delta. The only lost
  tagging-adjacent artifact is a hand-authored 7-bucket, ~40-keyword topic
  filter in `origin/feat/federal-register:frontend/src/lib/feedFilters.ts` —
  a browsing-UI convenience, an order of magnitude cruder than what exists.
- **The web repos hold no tagging code.** `spicyregs-web` is a five-commit,
  zero-JavaScript Astro landing page; the only relevant content is one line
  of marketing copy promising "the major themes in thousands of comments",
  with nothing behind it. `spicy-regs-landing`'s unique content is
  uncommitted metadata-provenance plumbing that explicitly leaves
  `observed_topics` empty.
- **Neither repo has** an sklearn/transformer classifier, KeyBERT/YAKE/RAKE,
  spaCy/NER, BERTopic/LDA, or a vector database. Dense retrieval is served
  from flat `.npz` files or USearch HNSW on disk.

## 11. What this implies

1. **Evaluate against FR topics, not agency** — 114,220 labelled documents,
   multi-label at 5.01 topics each, is a far stronger signal than agency.
2. **Draw a diverse evaluation set** from those 114,220 and fetch body text;
   do not reuse `fr-mirrulations-1k-v1`, which is degenerate for this.
3. **Add `incorporation by reference`** (and preferably the other 95) to
   Atlas — one concept moves coverage from 93.6% to ~99.7%.
4. **Assert the FR-thesaurus ↔ FR-api-topics mapping**, 698 labels agreeing
   verbatim, so evaluation stops depending on string coincidence.
5. **Keep the gazetteer scheme-scoped**; reconcile across schemes as a
   separate stage.
6. **Decide about TSCA** — swapping to Atlas drops 70,736 chemical
   substances that EPA rulemaking needs.
7. **Route candidates by ring.** The answer key is not a subject vocabulary;
   71 of its terms are agencies and 54 are values.

## 12. What RefSpec's own research already settled

RefSpec has never built a tagger, but it holds a worked architecture proposal
and a large external-method base aimed squarely at this problem.

**Governing constraint (REF-022, `docs/decisions.md:714`)** — this decides
*where* a tagger may live:

> "RefSpec owns vocabulary… DocSpec owns files at scale. SpicySearch is the
> only junction: it consumes Atlas releases from RefSpec and files from
> DocSpec, and **tagging executes there**… RefSpec and DocSpec share no direct
> edge, and no work may introduce one."

So the spicysearch gazetteer is not merely the more convenient of the two
engines — it is the one sitting in the architecturally sanctioned place.
The spicy-regs engine lives on the SpicyRegs side and produces candidates.

**REF-035 (`docs/decisions.md:2112`)** — a machine tag is an **E4** claim at
best: "assert the weakest predicate the evidence licenses, and keep it opt-in
until the adjudication record is satisfied." Note the non-obvious ordering:
**E3 outranks E4** — a pinned third-party artifact is externally checkable,
whereas RefSpec's own adjudication has no external comparand.

**Three-state assignment discipline** — every tag must be `Source-assigned`
(publisher's own, with receipt), `Machine-assigned` (with supporting passage,
model/registry versions, score, decision trace) or `Reviewed`. "Never promote
a machine-assigned term into source-assigned data. Never merge concepts
because their labels match."

### Method conclusions already on record

From `research/concept-tagging-architecture-proposal-2026-07-28.md` and the
nine external-research reports in
`research/evidence/blind-external-research-recovery-2026-07-28/`:

- **Mapping space ≠ output space.** A resource may help *retrieve* without
  being eligible to be *emitted* for a facet.
- **Candidate availability and assignment correctness are separate failure
  modes** needing separate measurement. Stop rule: "if candidate recall is
  poor, do not tune the adjudicator."
- **Lexical retrieval is a strong zero-shot baseline, not a fallback.**
  TF-IDF beats sentence-transformers and SPLADE on EURLex zero-shot
  (44.0 / 16.6 / 20.2 P@1); removing the lexical leg from a hybrid costs 33
  P@1 points. Independently consistent with this repo's own ablation.
- **Embedding checkpoint choice dominates everything**: SentBERT R@10 0.30%
  vs MPNet 20.64% on identical data — a 132× spread.
- **Metadata priors are soft signals, unioned never intersected.** Measured on
  the FR API: recall@12 42.2% global → 71.0% with an agency prior → 76.0%
  with a CFR-part prior. Roughly 90% of topic assignments land on terms used
  by two or more agencies, so hard-filtering by agency is wrong.
- **Union retrieval channels beat picking one.** Best single embedding arm
  reached ~88–90% recall@1 over 802 concepts; the union of five arms reached
  **95.74% recall@1 / 100% recall@20**. Best-rank-for-gold on OAEI Anatomy:
  rank ≤6 covers 90%, ≤18 covers 95%, ≤124 covers 99% — a fixed top-K always
  misses some genuine matches.
- **Label-text engineering is the highest-leverage lever, and not a free win.**
  Swapping bare labels for scraped descriptions took P@1 7.8→19.6 on one
  space but *hurt* others badly (MACLR EURLex 24.9→20.9). A/B per vocabulary.
- **A realistic ceiling**: SemEval-2025 / LLMs4Subjects, 204,739 concepts,
  best system R@5 ≈ 0.49 — and librarian-judged precision collapses 0.74
  → 0.53 because near-synonyms rank top. At ~515K labels, professional
  catalogers agree on the exact heading only **39.4%** of the time but on the
  *topic* **93.3%** of the time. **Score granularity disagreement separately
  from topic error.**
- **Never diagnose a tagger from raw cosine statistics without the correct
  null.** A prior "degenerate embedding space" finding was retracted: it
  compared concept↔concept instead of segment↔random-concept; the corrected
  margin was +0.2173, not 0.029.

### Two corrections to the record

1. A claim that a tagging pilot scored **micro F1 0.085** was **retracted** —
   a later cross-repo code trace found no F1 was ever implemented and that the
   only 0.085 in the artifacts is `"assumed_cost_usd": 0.085608`. The
   "graph search helps/hurts tagging" question is **unanswered**, not
   answered-and-negative.
2. `docs/concept-identity.md` is cited in several places but **has never
   existed in git history**. The source-scoped concept-identity doctrine it is
   cited for is not codified under any REF number.

### One correction to the research synthesis itself

The synthesis reported that derived-graph rows are "deliberately absent from
the compact/Parquet consumer view, visible only in the raw RDF derived pack."
That is wrong. `derived-relations.parquet` is a declared optional member of
the search view — 46,466 rows in the 2026-08-20 cut — and
`parquet_search_view.py:62-72` carries it explicitly. REF-035 says RefSpec
materializes closure rows "only when a named consumer states which rows it
needs," which is *opt-in*, not *absent*. A tagger can read the derived graph
straight from Parquet.

## 13. Per-scheme field coverage — do not assume completeness

A tagger that assumes altLabels or scope notes exist will silently
underperform on most schemes.

| scheme | concepts | altLabels | scope notes / definitions | hierarchy |
|---|---:|---|---|---|
| CRS Policy Areas | 32 | 0 | 32 (long inclusion/exclusion text) | 0 |
| CRS Legislative Subject Terms | 565 | 0 | 0 | 0 |
| **FR Thesaurus 2025** | 705 | 243 | **0** | **0** — deliberately flat: 1,451 `skos:related`, zero broader/narrower |
| ELSST R6 | 3,470 | 1,509 | 952 | 3,393 |
| ICPSR | 3,760 | 0 (alt sense only via `USE`/`UF`) | 730 (19%) | 1,759 + 14,360 related |
| EuroVoc 4.24 | ~7,600 | ~12,000 non-preferred | missing 1,557 EN definitions | 98.3% atomic |
| LCSH | ~514,000 | 803,437 outbound, only **1.56% exactMatch** | — | 301,442 broader; 45.9% compound |
| FAST Topical | 441,127 | 259,401 `sameAs`→LCSH (95.8% 1:1) | — | 60.1% compound |
| MeSH 2026 | 31,110 | — | — | 42,519 derived broader (tree numbers) |

Measured independently for this survey: across all of Atlas, **alternates
cover only 349,037 of 1,280,939 English-labelled concepts** — roughly 73% of
concepts have no synonym at all. That is a hard ceiling on pure gazetteer
recall, and it is the strongest argument for keeping a generative channel.

**The FR Thesaurus being deliberately flat matters**: there is no hierarchy to
expand along, so query expansion for FR tagging must use `skos:related` or
cross-scheme routing, not `broader`.

## 14. Mapping sparsity, and why it bites

Of a 7,985-concept three-vocabulary corpus, only **962 concepts (12.0%)** are
touched by any admitted cross-vocabulary mapping. Of the 353 equivalence pairs
behind them, **299 (84.7%) were found by identical normalized strings alone**,
and zero were found any other way — every genuinely semantic cross-vocabulary
match is, so far, undiscovered.

Publisher coverage varies wildly: EuroVoc 84.6% of concepts carry an external
`exactMatch`; LCSH only 1.56%; **ELSST publishes zero mapping predicates at
all**, exhaustively verified. REF-036 surveyed and rejected UMLS,
MeSH↔SNOMED, Wikidata, VIAF/ISNI, ICPSR, ELSST, GCMD, NASA, DOE-OSTI,
NAICS↔PSC and CRS↔LCSH as usable public crosswalks — E4 adjudication is the
only remaining path for most pairs.

This is the same finding as §6 at larger scale, and it is why the
FR-thesaurus ↔ FR-api-topics mapping (698 labels agreeing verbatim, one
publisher) is unusually cheap warrant by comparison.

### `exactMatch` transitivity is a live hazard

`exactMatch` is transitive under SKOS S45, so one bad edge contaminates every
chain. Documented near-misses:

- `CRS Health exactMatch GAO "Health Care" exactMatch Census Health` would
  formally equate an FDA food-labelling policy area with a Census payroll line
  that *excludes* hospital staff.
- FAST↔LCSH: OCLC asserts `schema:sameAs` (259,401 links, 95.8% 1:1); LC
  reciprocates with `closeMatch` (353,767) and **nothing meaning exact**.
  "1:1 cardinality is topology, not semantics." Neither publisher's assertion
  overrides the other's — this is undecided, not settled.

## 15. The trap list a tagger must be tested against

`research/parent-domain-taxonomy-2026-08-19.md` is a purpose-built
false-friend table, cross-validated by two blind taxonomy runs, an 8-labeler
grouping pass at 96.4% agreement, and a four-rater vote in which **majority
agreement gets every documented false friend wrong, 3-to-1**. It is a
ready-made test suite; a tagger that passes naive string matching will fail
most of these.

| trap | correct disposition |
|---|---|
| `Human Capital` (GAO) | federal workforce management → Government, **not** labour |
| `water` ×4 | CRS = Army Corps civil works → Transport; Census `Water Supply` = municipal payroll → Housing; GEMET = natural medium → Environment; `HYDROSPHERE` = a facet |
| `COMMERCE AND HOUSING CREDIT` (OMB) | mortgage credit, FHA, GSEs → Finance, **not** Housing |
| `Accounting` ×3 | LDA = profession regulation; EuroVoc = enterprise bookkeeping; GAO = government audit. First and third do **not** match |
| `Economic Development` ×5 | place-based grant programmes → Community Development, **not** macroeconomics |
| `Space` ×3 | GAO = NASA/national-security programmes; GEMET = outer space as physical environment |
| `Utilities` (LDA) vs Census's four | LDA = regulated *private* sector; Census = government-owned enterprises. Ownership is the whole point |
| Homeland Security vs Emergency Management | the 2003 reorganization fused these administratively; the vocabularies correctly never did |
| `chemistry` ×3 | EuroVoc/LDA = the chemical *industry*; GEMET = substances as environmental agents |
| `HEALTH` (OMB budget function) | **excludes Medicare** — merging with CRS/GAO `Health` silently moves ~$1T |
| `Atomic energy defense activities` | the nuclear *weapons* complex → National Defense, not Energy |
| `Public Welfare` (Census) | carries Medicaid vendor payments — folding moves tens of billions |
| `Postal` (LDA) vs `Postal Service` (OMB) | policy domain vs an entity's budget line filed under Commerce |

Four structural rules the same document establishes:

- **Statutes and funding vehicles are not subjects** — `Affordable Care Act`,
  `Recovery Act`, `IIJA`, `Opportunity Zone Benefits`: unanimous NONE across
  four blind raters.
- **Jurisdiction is a facet, not a subject** — on `10 EUROPEAN UNION` all four
  raters split 2-2 and *none* chose "no subject parent" when forced. Forcing
  single-parent assignment onto facet labels is a documented failure mode.
- **Populations are a facet** — a veterans' housing programme is
  Housing × Veterans; filing it under Veterans loses veterans' health and
  education.
- **Two publishers' `Other` are not the same `Other`.**

**Entity-linking traps** (`research/evidence/agency-identifier-census-2026-08-16/`):
51 of 52 shared values between `federalRegisterNumericId` and
`cgacAgencyIdentifier` are ambiguous — one CGAC code maps to up to ten FR
agency IDs. Short-name collisions: `DOE`, `DOL`, `EAB`, `FS`, `LOC`, `OFR`,
`PRC`. Never join agencies on string equality.

**Two more that generalize:**

- **`toc_subject` must never be treated as topical truth** — it answers "what
  kind of document," not "what is it about." It is nonetheless the only free
  native label reaching the ~81% of the corpus the Thesaurus cannot touch
  (73.1% coverage, including 75% of Notices).
- **The inverse problem**: `EPA` / `Environmental Protection Agency` /
  `United States. Environmental Protection Agency` / CGAC `068` are one entity
  across four unjoinable surfaces. And `TRUCKS`/`LORRIES` is a genuine
  cross-register synonym a string matcher simply misses.

## 16. Why the FR topic coverage numbers look the way they do

Measured live against the FR API by the external research, and consistent with
the 11.4% figure measured here on 1,004,233 documents:

| document type | share carrying ≥1 topic |
|---|---|
| Rule | ~67–80% |
| Proposed Rule | ~66–76% |
| **Notice** | **0%** |
| **Presidential Document** | **0%** |

Notices carry no topics **by law** — 1 CFR 18.20 mandates indexing only for
material with CFR parts. This is not a coverage gap to fix, and it explains
the 11.4% corpus-wide figure without implying the data is deficient. It also
means the 114,220 labelled documents are overwhelmingly Rules and Proposed
Rules, which should be stated in any evaluation's scope.

The CFR List of Subjects is the documented route to the rest: **8,409 CFR
parts, 37,220 (part, term) assignments, 1,196 distinct terms**, propagating to
any document citing a CFR part — including Notices.

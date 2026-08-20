# Atlas tagging and salvage survey

**2026-08-20.** Two sweeps of the SpicyRegs / SpicySearch / RefSpec / RuleSpec /
DocSpec repos, twelve parallel subagent surveys in total, plus direct
measurement against the sealed Atlas 3.1 distribution
(`output/atlas-3.1-parquet-search-view-2026-08-20`, seal `79bfeb55…`).

The first sweep asked **what already exists that we can use to tag documents
and metadata**. The second asked a different question of the same ground:
**what was left half-done, minimal, or forgotten but contains something worth
reviving** — a novel idea, an elegant abstraction, a piece of foresight.

## How to read this

- **Part I** — the tagging assets that exist today, and what the record already
  settled about how to use them.
- **Part II** — finished work sitting one wire short of being used.
- **Part III** — findings measured directly against the sealed distribution.
- **Part IV** — corrections, retractions, and claims that did not survive checking.
- **Part V** — what to do.

Every number in this document was produced by running a query or a tool, not
taken from a subagent's report. Where a subagent's claim was load-bearing it
was checked — files opened, commits inspected, greps re-run, test suites and
CLIs executed. Claims that failed checking are recorded in Part IV rather than
quietly dropped.

## Validation

This report was put through four adversarial opus validators, each instructed to
refute rather than confirm and to default to REFUTED when uncertain. They
re-derived the numbers independently, ran the tools, and inspected the commits.

**They found real errors, and the corrections are inline below rather than
quietly patched.** The most serious:

- **One quotation was fabricated.** The ranking-v4 invariant was rendered here
  as "a modifier may reorder documents whose evidence could not distinguish
  them, *and never anything else*." That phrase appears nowhere in the source,
  and it reverses the rule — the real sentence permits bounded intra-band
  movement ("may move a document at most one band's worth — and never out of
  its band"). It is the worst defect in the report. It is not, however, the only
  non-existent sentence: the cross-ring section had also quoted "zero
  CrossRingRelationAssertions currently ship" as the record's wording when it was
  a subagent's paraphrase. One was invented outright; one was a paraphrase
  promoted to a quotation.

- A retraction this report repeated — "tagging micro F1 0.085 was never
  implemented" — is **false**. `micro_f1 = 0.0851063829787234` is on disk and
  emitted by `tag_task.py:357`. The original retraction searched the wrong repo.
- The claim that the ANN revisit trigger "fired in the same commit that wrote the
  rejection" is **false**; the rejection was written two commits earlier. The
  underlying opportunity survives, and a validator confirmed it by measurement
  this report had not taken.
- A quoted sentence attributed to the research record — "zero
  CrossRingRelationAssertions currently ship" — **does not exist**; it was a
  subagent's paraphrase, and REF-037 already pins the figure at 446.
- "GCMD has the worst within-scheme ambiguity" is **false** (4th, behind naics,
  federal-hierarchy and treasury-account-symbols).
- The two-column coverage table **mixes denominators and matching rules**.
- Several cost estimates were optimistic by an order of magnitude.

A fourth validator re-derived every number against the sealed distribution, the
Federal Register parquet, and git history, and checked ~40 quotations and every
REF attribution. Its conclusion was that the failure mode here is "not mass fabrication" but one
rewritten quote plus miscounts and mis-sourced attributions. Every REF-### number
checks out. **Its further claim that "every `file:line` resolves" did not
survive a fifth pass** — `mesh_descriptors.py:202` is the enclosing `def`, not
the cited `findall` (that is `:219`), the ranking-v4 quotation ends at `:673`
rather than `:672`, and two bare `docs/decisions.md:` citations point at the
sibling spicy-regs repository rather than RefSpec.

What held: the entire answer-key section, the ring breakdown, the gazetteer
ambiguity split, "no chemical inventory / zero CAS identifiers", the derived-graph
rescue figures, the lifecycle-hold finding, `parquet_preflight`, and the orphan
claims — all re-derived exactly. The two `rkaf-analysis` quotes are verbatim.

---

# Part I — Tagging assets: what already exists


## Two working tagging engines, not zero

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

## The answer key exists, at scale

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

## Vocabulary coverage of the answer key

The recall ceiling that exists before any model runs. Type level counts
unique vocabulary terms; token level weights by how often documents actually
get labelled with them.

| | unique terms | actual assignments |
|---|---|---|
| FR Thesaurus 2025 (what the engine tags into today) | 66.9% | **89.9%** |
| Atlas **excluding `federal-register-api-topics`** | 90.8% | **93.6%** |
| Atlas including it | **100%** | **100%** |

**The exclusion is the whole story, and an earlier version of this table hid
it.** That row was labelled "All of Atlas", which was false: Atlas already
carries the complete 1,044-term `federal-register-api-topics` scheme — the
answer key's own vocabulary — so measuring Atlas against the answer key without
excluding it returns 100% trivially.

Excluding it is the right measurement *for the question that matters*: can a
tagger reach these topics through an **independent** vocabulary, rather than by
echoing the key back? But it must be stated, and the row must not be called
"all of Atlas."

**Read this table with two caveats, both found in validation.** The two
columns do not share a denominator: the type-level column measures against the
**1,044 published API topics**, while the token-level column measures against
the **571,713 assignments** drawn from the 900 topics actually used. Measured
against the answer key proper (900 used topics) the type-level figures are
**74.3%** and **96.0%**, not 66.9% and 90.8%. The columns also use different
matching rules — 66.9% counts preferred labels only, 89.9% counts preferred
plus alternate; on preferred-only the thesaurus token figure is **88.6%**.

The conclusion is unaffected: weighted by real usage the FR Thesaurus already
reaches ~89–90% and Atlas buys **+3.76 points**.

**But the earlier explanation of *why* was wrong.** This report previously said
the terms the thesaurus misses are "overwhelmingly rare long-tail commodities —
prunes, tangerines, pistachios, nectarines." Those are terms **Atlas does not
have either** — they appear in the Atlas gap table below. What Atlas actually
buys is criteria air pollutants and US territories:

| term Atlas adds over the FR Thesaurus | uses |
|---|---:|
| nitrogen dioxide | 5,705 |
| sulfur oxides | 3,758 |
| carbon monoxide | 2,984 |
| nitrogen oxides | 1,007 |
| puerto rico | 592 |
| virgin islands | 400 |

That is EPA air-quality vocabulary, which matters more than the commodity
story did: EPA is among the largest agencies in the labelled set.

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

## The answer key is not a subject vocabulary

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

## The gazetteer must stay scheme-scoped

`VocabularyLookup.build(view, scheme_id=…)` is single-scheme by construction
and `suggest()` abstains whenever a normalised string reaches more than one
concept. Measured against Atlas's 1,375,960 distinct English label strings:

| | strings | share |
|---|---|---|
| resolve to exactly one concept | 769,577 | 55.9% |
| ambiguous **across schemes only** | 587,267 | 42.7% |
| ambiguous **within a scheme** | 19,116 | 1.4% |

**Normalization caveat.** These reproduce under plain `lower(trim())`, *not*
under the engine's own `normalize_text` (NFKC + casefold + punctuation
stripping) — so they are not literally what `VocabularyLookup` sees. Under the
real normalizer: 1,364,499 keys, 753,110 unique, 592,270 cross-scheme-only,
19,119 within-scheme, and the LCSH/FAST family figure becomes 544,954 / 592,270
(92.0%). Every conclusion below is unchanged; the figures shift in the third
significant digit.

Worst case: one string reaches 84 concepts.

**92.2% of the cross-scheme ambiguity (541,168 of 587,267) is confined to the
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
two related authorities *agreeing*.

The six-row abstention table above is subject-ring only, and an earlier version
of this report drew a false superlative from it ("GCMD and NASA need real
within-scheme disambiguation; nothing else does"). Across all rings the three
worst schemes are **naics 41.76%, federal-hierarchy 25.92% and
treasury-account-symbol-structure 21.44%** — all above GCMD's 20.73% — and
fourteen schemes exceed 1.2%. Scheme-scoping remains right; the list of schemes
needing disambiguation is longer than stated.

## Two Federal Register vocabularies, unconnected

| scheme | concepts | role |
|---|---|---|
| `federal-register-thesaurus-2025` | 705 | what the engine tags into |
| `federal-register-api-topics` | 1,044 | what documents are labelled with |

They share **695** preferred labels verbatim (698 after case-folding — the
three case-only pairs are `Armed Forces`, `Armed Forces Reserves` and
`Diesel fuel`), but Atlas asserts **zero** mappings
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

## What Atlas would lose

`fused-concept-registry-v1` breaks down as fast-topical 440,599, **epa-tsca
70,736**, a scheme literally named `subject` at 936, crs-subjects 932,
crs-policy-areas 33. (That 936-row scheme is *not* the FR Thesaurus, which
has 705 concepts; 925 of its 936 rows match FR **API topics**.)

Atlas contains everything there except **epa-tsca**, and adds LCSH (514,837),
MeSH (31,110), EuroVoc, GEMET, GCMD, NASA, DOE-OSTI, ICPSR, ELSST plus the
entity and value rings.

Atlas carries **no chemical inventory at all** — no TSCA scheme, zero CAS
identifiers. Those 70,736 substance names (`Benzoic acid, 3-methyl-, zinc
salt (2:1)`) are the one thing a swap to Atlas would lose, and they matter
for EPA rulemaking, which is the second-largest agency in the labelled set
at 19,285 documents listing EPA (19,229 EPA-only) — third by individual
agency, behind transportation-department and the FAA.

## Measured retrieval evidence already on record

`spicy-regs/docs/evidence/candidate-selector-ablation-2026-07-28/` — nine
configurations over the 513K registry against 35 frozen dev segments. **Its own
README caps it: "Development-only … nothing here can support an adoption or
accuracy verdict."** Read the readings below as direction, not as measurement
that licenses a decision. The
best configuration surfaced only **5 of 8** exact-alias targets.

Two readings the committed README draws, plus one it does not:

1. Dense retrieval (channel C) **reorders rather than discovers** — `v2+C`
   scores the same 4/8 as `v2` while mean rank drops 5.25 → 2.0.
2. The per-scheme quota buys balance: `v2-noquota` reaches 5/8 but
   adequate-kept collapses 4/5 → 2/5 as fast-topical floods 75% of slots.
3. **Not in the README:** fusion loses what its own channels find. `D-alone`
   surfaces `fisheries management`, but `v2+D` does not. This report previously
   blamed quotas; the table's own `v2+C+D-noquota` row misses it too, so quotas
   are ruled out. Fusion
   suppress a target that a constituent channel had already retrieved.
   `immigration law` is found by **none** of the nine configurations.

LLM free-keyword generation (channel D) is the only channel that finds
genuinely new terms: `D-alone` surfaces `fisheries management`, `free
speech` and `poultry inspection` — but only `fisheries management` is
D-exclusive: `v2` (lexical only) reaches `poultry inspection` too.

## Corpora: the join works, but the obvious corpus is degenerate

`fr-mirrulations-1k-v1` has full body text (avg 27.5 KB) for 1,000
documents. Joining `document_id` → `federal_register.document_number`
matches 641, of which **630 carry topics**.

That set is unusable as an evaluation corpus: those 630 documents use only
**5 distinct topics** from a single agency, and four of them
(`Safety`, `Air transportation`, `Aircraft`, `Aviation safety`) appear on
**all 630**, from a single agency. (An earlier version said the upstream draw
was "99.97% FAA airworthiness directives" — that figure came from a subagent
and is not reproducible. The 1,000-document draw is **64.1%** airworthiness
directives by title; the 641 that join the Federal Register table are
**100%**.) A
constant predictor scores near 100% — precisely the failure mode
spicysearch's own benchmark already hit, where the real engine lost to
`constant_majority` on nDCG@10 (0.30 vs 0.49).

The join mechanism is sound; the sampling frame should be the full 114,220
labelled documents (521 agency combinations, 900 topics), with body text
fetched via `body_html_url`.

## Per-scheme field coverage — do not assume completeness

*(This is the field inventory the research record carries, and it does not
everywhere agree with the sealed distribution — the seal gives ELSST 903
definitions rather than 952, and ICPSR 3,810 concepts with 0 definitions rather
than 3,760/730. Where they differ, trust the seal. Part III measures
definition coverage directly against the sealed distribution and reaches the
same conclusion from the other direction.)*

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

## Mapping sparsity, and why it bites

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

This is the same finding as *Two Federal Register vocabularies, unconnected* above, at larger scale, and it is why the
FR-thesaurus ↔ FR-api-topics mapping (695 labels agreeing verbatim, 698 case-folded, one
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

## The trap list a tagger must be tested against

`research/parent-domain-taxonomy-2026-08-19.md` is a purpose-built
false-friend table, cross-validated by two blind taxonomy runs, a grouping pass with two blind assigners and eight adjudicated splits at
96.4% agreement, and a four-rater vote in which **majority
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

## Why the FR topic coverage numbers look the way they do

Measured live against the FR API by the external research, and consistent with
the 11.4% figure measured here on 1,004,233 documents:

| document type | share carrying ≥1 topic |
|---|---|
| Rule | ~67–80% |
| Proposed Rule | ~66–76% |
| **Notice** | ~0% (29 labelled documents exist) |
| **Presidential Document** | ~0% |

**Corrected:** an earlier version said Notices carry no topics "by law." That
overstates it twice. The parquet contains **29 labelled Notices**, so the rate
is near-zero rather than zero; and 1 CFR 18.20 *requires* indexing for material
with CFR parts — it does not *prohibit* indexing Notices. This is not a coverage gap to fix, and it explains
the 11.4% corpus-wide figure without implying the data is deficient. It also
means the 114,220 labelled documents are overwhelmingly Rules and Proposed
Rules, which should be stated in any evaluation's scope.

The CFR List of Subjects is the documented route to the rest: **8,409 CFR
parts, 37,220 (part, term) assignments, 1,196 distinct terms**, propagating to
any document citing a CFR part — including Notices.

## What RefSpec's own research already settled

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

**REF-035 (`docs/decisions.md:2112`)** — **scope caveat:** REF-035 governs
mapping assertions *between vocabulary resources*. It does not by itself
establish that a document-to-concept tag is an E4 claim; that is an extension
this report draws, not a rule REF-035 states. Read on that basis, its tiering
says a machine-made assertion is **E4** at best: "assert the weakest predicate the evidence licenses, and keep it opt-in
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
  vs MPNet 20.64% on identical data — a **68×** spread. (An earlier version
  said 132×; that is the *P@1* pair, 0.17 vs 22.46. 20.64 ÷ 0.30 = 68.8.)
- **Metadata priors are soft signals, unioned never intersected.** Measured on
  the FR API: recall@12 42.2% global → 71.0% with an agency prior → 76.0%
  with a CFR-part prior. Roughly 90% of topic assignments land on terms used
  by two or more agencies, so hard-filtering by agency is wrong.
- **Union retrieval channels beat picking one** — *this one is RefSpec's own
  sealed benchmark, not external literature*
  (`research/evidence/atlas-candidate-benchmark-sealed-2026-08-05/benchmark-report.md:23`).
  Best single embedding arm
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

## Confirmed absences

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


---

# Part II — Abandoned value: finished work one wire short


## The pattern

Almost nothing found is *unfinished*. The recurring shape is **finished work
sitting one wire short of being used** — a complete vertical slice built
ahead of the thing that would exercise it, then parked and forgotten. Several
items are blocked on conditions that have since been satisfied without anyone
noticing.

---

## The same idea, built four times, running zero times

Four separate repos independently concluded that *absent* and *checked, found
nothing* must not collapse into one state. All four implementations are inert.

| repo | artifact | state |
|---|---|---|
| RefSpec | concept-lifecycle system (rename/split/merge/retire) | build **asserts** it stays at 0 |
| RuleSpec | `rkaf-analysis` — 788-line spec, 6 generated Rust types | **0** runtime consumers |
| spicy-regs | `ClosureClaim` / longitudinal omission design | **deliberately disabled**, 0 code |
| DocSpec | negative-evidence segmentation ledger | **retired by a rewrite**, now in an excluded archive |

**Two of these four rows are decisions, not oversights** — a framing this report
originally got wrong. `ClosureClaim` is disabled by an executed, checked-off
decision: `spicy-regs/TODO-RULE.md:196` records "Keep ClosureClaim Experimental
and disabled. Done 2026-07-26 … four independent disablement mechanisms", and
`rkaf-core/src/lib.rs:242` states its only legal status is
`rkaf:closureClaimDisabled`. DocSpec's ledger is not code built ahead of its use
either — it *had* callers (`pipelines/ontology_dataset.py:161`,
`ontology/receipt.py:33`) and was discarded by the 2026-08-05 rewrite.

So the pattern is real but narrower than "four teams forgot the same idea": two
built it and shelved it deliberately, one disabled it by decision, one threw it
away in a rewrite. The open question is still worth asking — nobody is running
it anywhere — but it is a question about four decisions, not four oversights.

### Adopting it is a union with a real coverage question, not a swap

A parallel session established, and this session verified, that RuleSpec
already ships **hand-authored** adjudication shapes covering the same five-axis
independence test — so a compiler that generates them would be *retiring
working rules*, not filling a void. And neither set is a superset of the other:

| shape | source | target class |
|---|---|---|
| `MachineAdjudicationFiveAxisIndependenceShape` | generated | `RelationComparisonContext` |
| `MachineAdjudicationVerdictLatticeFoldShape` | generated | `RelationComparisonContext` |
| `MachineAdjudicationIssuedProofCitationShape` | generated | **`ResolverProofRecord`** |
| `MachineAdjudicationProofReplayShape` | generated | **`ResolverProofRecord`** |
| `MachineAdjudicationIndependentPairShape` | hand-authored | `RelationComparisonContext` + **`RelationFinding`** |
| `MachineAdjudicationCompleteSupportShape` | hand-authored | `RelationComparisonContext` |

Verified: `rkaf-shapes-analysis.ttl:319` targets `rkaf:RelationFinding`, and
`RelationFinding` appears **zero** times in the generated set. Conversely
`ResolverProofRecord` is covered only by the generated pair. Adopting the
generated shapes as a replacement would **drop independence enforcement on
`RelationFinding`**.

The hand-authored rules are also maintained code, not a stale first draft —
refined twice after authoring (`5429465` "close the fifth machine-adjudication
independence axis", `17eba7a` "cap sealedResponseArtifact at one value per
proof", both 2026-08-10). Reconciliation is the real blocker, ahead of
packaging.

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
`crates/rkaf-runtime/src/` reference any of the six.

**A note on how this was verified.** This report originally cited "zero files
under `crates/rkaf-runtime/src/` reference any of the six types." That check is
**vacuous** — `rkaf-runtime` has no `rkaf-core` dependency at all, so it could
not have failed. Re-run properly across all ten crates: the only crate depending
on `rkaf-core` is `rkaf-projector-json-ld`, which uses one unrelated symbol. The
six types appear only in their own definitions, `lib.rs` re-exports, one
round-trip fixture test, and spec prose. **Zero behavioural consumers — the
conclusion holds, but on evidence the original check did not gather.** (Also:
the type is `MachineAdjudicationProof`, and there are six of them, not five.)

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
`atlas-v3-binding-and-relation-research`. The *vocabulary* is an import away —
already compiled to Rust, JSON Schema, SHACL and TypeScript. Adopting the
*shapes* is not: see the reconciliation note below, which is the real blocker.

---

## Blockers that already cleared, and nobody noticed

The most valuable category in the survey: work correctly parked on a stated
condition, where the condition has since been met.

### The ANN rejection's embedding precondition has since been met

`src/spicy_regs/ontology/ann_index.py` (433 lines) is a complete,
digest-pinned USearch/HNSW wrapper, rejected the day it was built for a
well-measured reason: the true top-50 nearest concepts for a real query sit
inside a **0.056-wide cosine band**, leaving HNSW's greedy descent almost no
gradient — structurally, regardless of library.

**An earlier version of this section claimed the revisit trigger "fired in the
same commit that wrote the rejection." That was wrong.** The rejection was
recorded in `b893e7c` ("measure a USearch ANN index against the exact dense
channel"), which already contained the revisit list. `90a76fd` is the *third*
commit to touch that file, and its subject is "fix: strip fabricated citations and correct the separation metric". The
report also misdescribed the trigger's structure: the evidence file lists
**three** conditions under "Revisit when **any** of these becomes true" —
sufficiency, not necessity — and the decision entry's own trigger is a
*memory-budget* one, not the embedding one.

**What survives, and is now better evidenced than the report originally made
it.** The embedding condition is that the top-50 neighbourhood become less
flat. `90a76fd` introduced
`CONCEPT_EMBEDDING_TEXT_V2 = "concept-embedding-text-v2-boilerplate-free"`,
now the default, and the on-disk V2 index carries that version tag. Measured directly on both matrices by a validator (25 seeded queries, top-50
excluding self). *The seed and sampled concept IDs were not recorded, so this
particular sample is not independently reproducible from this document — treat
the direction as established and the exact figures as indicative:*

| space | mean top-50 cosine band |
|---|---:|
| V1 (with boilerplate) | 0.0737 |
| **V2 (boilerplate-free)** | **0.1064** |

The neighbourhood is **44% wider** — the precondition is satisfied in
substance, which nobody had checked. And the benchmark has never been re-run:
`tools/benchmark_usearch_index.py` and `ann_index.py` each have exactly one
commit in history, and no usearch output directory exists.

**Cost ~1 hour** (the V2 index is on disk, so no re-embed; `usearch` is a
pinned optional extra). **But this should not be ranked first.** The
rejection's *primary* ground was that there is no measured operational failure
to fix — 1.70 GB, 16 ms, on a 48 GB machine with no declared serving budget. A
recall re-run cannot touch that ground, so it cannot by itself reverse the
decision. The evidence file orders the work the other way: shrink the emit
vocabulary first, "and only then revisit retrieval."

*(Aside: `90a76fd`'s message is "strip fabricated citations and correct the
separation metric" — four fabricated citation blocks removed from an evidence
file. This project catches fabrication in its own record repeatedly, which is
why its evidence is worth trusting, and why this report was itself put through
adversarial validation.)*

### Two finished auditor readers for gaps the repo still declares open

`bindings/atlas/3.1/tests/registry-descriptors.nq` still carries
`"consumability":"inventoryOnly"` and an explicit `"gap"` field for
`opm-plum-position-status-codes` and `cbo-publication-identifiers` (115 gap
entries in total). Verified: `tools/verify_atlas_source_fidelity.py` on main
(1.0 MB, 56 readers) contains **zero** mentions of either.

Two unmerged commits already implement them:

| commit | adds | tests |
|---|---|---|
| `22edee5a` "feat(atlas): audit tabular registry sources" | `_read_opm_plum_csv`, `_read_naics_psc_xlsx`, `_read_treasury_fast_book_xlsx`, `_read_nppes_csv`, `_read_opm_ehri_xlsx` | +514 lines |
| `aa113fe4` "feat(audit): compare pinned publisher row lists" | `_read_cbo_publication_source_list`, `_read_html_table_source_list`, `_read_markdown_source_list` | +138 lines |

Verified by direct count: 20 "plum" mentions in `22edee5a`, 14 "cbo" in
`aa113fe4`, **0 of either on main**. `plans/validation-cost-reset-plan.md`
already logs them as "wip, NOT resumed."

**An earlier version called this "cost: hours — the cheapest, lowest-risk win
in the survey." Validation refuted both halves.** The two commits sit on
*different* branches (`research/coverage-csv-pdf`, `research/coverage-html-misc`),
neither an ancestor of the other or of main, both **62 commits behind**. Since
their common base, main's `verify_atlas_source_fidelity.py` has moved by
**+18,134 / −2,604 lines**. The repo's own ledger
(`plans/validation-cost-reset-plan.md:523`) records both as "wip, NOT resumed …
both need the same integration-first resume", and the sibling branch that *was*
merged needed "the memory refactor across 11 conflict regions."

**And the premise was wrong.** All 115 descriptors carry a `gap`; 105 are
`inventoryOnly`. These two are unremarkable members of that 105, both with
`"distributions":[]`, and **neither source ships among the 247 releases in the
seal**. A source-fidelity auditor compares publisher bytes against what Atlas
asserts — Atlas asserts nothing from these sources, so merging the readers would
not close either declared gap. Realistic cost: **days**, and it buys audit
coverage rather than gap closure.

### A 3.5-second validation gate that was never wired in, and rotted

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

## Complete engines with no callers

- **`spicy_regs/docpipeline/retrieval.py`** — 5,479 lines: dense BGE +
  learned-sparse retrieval, RRF at k=60, fixed-depth cross-encoder reranking,
  checkpointed and resumable, with **zero non-test callers**. (This report
  originally added "every sibling pipeline stage has production callers" —
  false: `docpipeline/relation_task.py` and `docpipeline/executor.py` are
  equally orphaned. Three of eight siblings, not one.) Meanwhile
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
- **`nrc-adams-multi-artifact-v1/1.0`** — a complete multi-artifact reader in
  `tools/verify_atlas_source_fidelity.py`: constant at `:2312`, admitted in the
  valid-reader list at `:2364`, reader `_read_nrc_adams_multi_artifact` at
  `:4325`, a dedicated `NrcAdamsMultiArtifactSelector` dataclass, dispatch entry
  at `:13031`, and two validation guards at `:19677-19679` — and **no
  `SourceSpec` assigns it**. Confirmed against the executed object, not just
  grep: `any(s.reader == NRC_ADAMS_MULTI_ARTIFACT_READER for s in SOURCES)` is
  `False` across all 112 specs. Built, wired, guarded, unused.
- **`ManagedVocabularyBundle`** — exported as the standard packaging path,
  while the two real pipelines hand-roll their own
  `_json_bytes`/`_sha256_bytes`/`_seal`. Not merely underused — actively
  reinvented in parallel.

---

## Designs worth more than their verdicts

- **`spicysearch/docs/ranking-v4-design.md`** — 73 KB, "**Not implemented**",
  no trace in `src/` (verified). Proves in closed form that the current
  ranking key encodes **rank, never margin**: RRF makes the rank-1→rank-2 step
  a fixed `0.08/62 = 0.00129` however much better rank 1 actually is. So a
  prior modifier's safe window (`w < 0.00129`) and useful window
  (`w ≳ 0.0071`) are **disjoint by 5.5×** — no constant can be both. The fix
  sorts into score-proximity *bands* before any modifier runs, with a one-line
  invariant guaranteeing no bounded modifier can move a document across a
  band. **The quotation given here in an earlier version — "a modifier may
  reorder documents whose evidence could not distinguish them, and never
  anything else" — was fabricated.** The phrase "never anything else" appears
  nowhere in the file, and it changes the rule. The actual sentence
  (`ranking-v4-design.md:672-673`) is: *"a modifier may reorder documents whose
  evidence could not distinguish them, and may move a document at most one
  band's worth — and never out of its band."* The source **permits** bounded
  intra-band movement; the invented version forbids it.
  **Caveat found in validation:** the arithmetic is exactly right, but it
  describes `engine.py`, which commit `47f108f` (2026-08-11) deleted. Current
  fusion in `search_application.py` is integer `RRF_WEIGHTS[lane] //
  (RRF_K + rank)` — no 0.08 authority, no `best_fusable` normalization. The
  constants `0.08/62`, `0.00129`, `0.0071` and the 5.5× gap are v3-specific.
  The *general* defect survives (`_rrf_score` is still rank-only and
  `similarity_micros` is carried but never scored), so the motivation stands
  while its measured numbers do not.
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

## Conventions worth stealing

- **Declared gaps as structured data.** 28 of 64 RefSpec registry loaders
  attach their known limitations to every resource — *"so a reader never has
  to rediscover them from the raw CSV."* This is why GCMD's limitation was
  diagnosable in two minutes.
- **Append-only corrections on sealed records.** Never edit the sealed file:
  strike the wrong claim inline and append a dated, numbered correction block.
  One instance reverses a claim made in an immutable commit message —
  *"commits are immutable, so it is corrected here"*
  (`spicysearch/evaluation/experiments/2026-08-02-within-vocab-expansion-v1/decision.md:148`).
  **Correction: this report said the convention was "documented nowhere."
  RefSpec already has the mechanism — `refs/notes/commits` carries two live
  notes doing exactly this.** One records that commit `8c1c3e02`, whose subject
  reads "refactor(registry): validate supersession at full scope", in fact *retires* full-closure
  supersession — the subject asserts the opposite of what the commit does. The
  other records a review challenge and a still-missing negative fixture.
  `git ls-remote origin 'refs/notes/*'` returns **empty**: they are unpushed
  single copies, invisible to `git log` by default. Adopting this as house
  style is therefore not "write a convention" but `git push origin
  refs/notes/commits` plus `notes.displayRef`.
- **Never blend failure modes into one number.** `tools/discovery_scoring.py`
  reports set precision/recall, row-level predicate exactness and declared-count
  comparison separately, strips ambiguous ground truth from both sides rather
  than guessing, and *raises* instead of scoring when a forbidden near-miss
  overlaps the expected set.
- **Audit the constructed object, not the source text.** `grep -c "SourceSpec("`
  on `verify_atlas_source_fidelity.py` returns **61**; importing the module and
  reading `len(SOURCES)` returns **112**. The gap is `*_PATTERN_ROW_SOURCES`
  splices. Anything assembled by splice, decorator or plugin registration is
  invisible to grep *in proportion to how cleanly it was built* — so the better
  the code, the worse the undercount. This is how the `nrc-adams` orphan above
  was confirmed properly:
  `any(s.reader == NRC_ADAMS_MULTI_ARTIFACT_READER for s in SOURCES)` is
  `False`, which is a fact about what runs rather than about what greps.
- **Predecessor fingerprinting.** DocSpec normalizes source to syntax-only
  tokens, SHA-256s every 96-token sliding window, and pins against the
  pre-split monorepo commit to prove its rewrite isn't vendored. All four
  repos make that claim implicitly; one checks it mechanically.
- **Quote both denominators.** Every quality figure a campaign quoted
  (61/114 passes) described a request shape only the harness could build. A
  real user at a text box gets **9/114**; 54 of 114 jobs need a UI affordance
  no text box can express.

---

## Cross-repo: what one repo has that another is missing

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


---

# Part III — Measured against the sealed distribution


## The scope notes were left on the floor

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

**The MeSH case is a small change in a well-placed spot** — though not the "one
line" an earlier version claimed; see Part V item 2 for the real delivery cost. `mesh_descriptors.py:202` already calls
`elem.findall("ConceptList/Concept/TermList/Term")`. `ScopeNote` is a
*sibling of TermList in the same element the function already holds*.
Verified against the repo's own fixture, which carries **3** ScopeNote elements
parsed past and discarded today (an earlier version said 6 — that is the count
of the *string* `ScopeNote`, i.e. open plus close tags):

```
d.findtext('ConceptList/Concept/ScopeNote')
D000001 Calcimycin → "An ionophorous, polyether antibiotic from
                      Streptomyces chartreusensis…"
D000002 Temefos    → "An organothiophosphate insecticide."
```

**30,960** descriptors carry a preferred-concept ScopeNote — not all 31,110 —
and a correct implementation must select `PreferredConceptYN="Y"`, because on 5
descriptors the preferred concept has none while a non-preferred one does, so
the naive path would attribute a synonym's definition to the descriptor. The
`findall` is at `mesh_descriptors.py:219`; `:202` is the enclosing `def`.

**GCMD is not the same bug.** `gcmd_science_keywords.py:98` explicitly
declares `skosRelationshipsUnavailable` — *"only the separate RDF export
publishes those relationships."* A documented source choice; fixing it needs
a different source, not a parser change.

## The derived graph is load-bearing, not optional

| | |
|---|---:|
| MeSH concepts isolated in the asserted graph | 18,408 of 31,110 (59%) |
| rescued by the derived graph | **18,406** |
| still isolated | **2** |

REF-042 correctly calls it non-authoritative and opt-in. A consumer reading
"opt-in" as "skippable" gets a MeSH that is 59% rubble.

Connectivity overall: 230,315 of 1,497,841 concepts (15.4%) have no **asserted**
relation. Counting the derived table too, **208,081 (13.89%)** have none at all —
the honest denominator for a consumer that reads both graphs. Worst: gcmd 100% isolated, fast-bulk-see-also 75.5%, mesh 59.2%,
lcsh 25.3%, fast-topical 3.1%.

## Cross-ring assertions: one pair ships, and the subject pair is blocked on warrant

**This section previously claimed the research record said "zero
CrossRingRelationAssertions currently ship" and that the 446 in the seal
corrected a stale premise. Both halves were wrong.** That sentence appears
nowhere in `docs/` or `research/` — it was a subagent's paraphrase of REF-032's
zero-state tripwire, which this report then quoted as if it were the record's
own wording. And the record is not stale: REF-037 (`docs/decisions.md:2424`)
already retired the tripwire and pins the carrier at **446** by name.

What is true, and re-derived here: the seal carries 446
`CrossRingRelationAssertion` rows, every one `entity → legalIdentity`, and the
`subject` ring (1,463,064 concepts, the largest) participates in none.

But the absence is a **governance decision, not unwired plumbing**. What ships
is `atlas:referencesLegalIdentity` (entity → CFR title) — a different predicate
with different semantics. REF-032 *rejected* the observed subject inventories
on evidentiary grounds ("one document's own page metadata read twice"), and the
REF-034 amendment records eCFR's agency→CFR-chapter assignments as structurally
blocked on that same cross-ring decision.

So the tagger-relevant point stands but changes shape: the answer key needs
subject↔entity routing (71 of the 346 unexpressible topics are agencies, 54 are
values), and what blocks it is **warrant, not wiring**. That is a decision to
revisit with better evidence, not an oversight to correct.

## GCMD is weak on three axes at once — but it is not the worst on any of them

GCMD is 100% isolated (zero relations), carries zero definitions, and has
20.73% within-scheme label ambiguity. Switching to the published RDF export
would improve all three at once.

**An earlier version of this section called it "the weakest scheme in the
distribution" and "the worst within-scheme label ambiguity measured." That
superlative was wrong** — it silently generalized a subject-ring measurement to
the whole distribution. Re-derived across all rings, GCMD is **fourth** when schemes are cut at >400
label strings, and **sixth** counting every scheme (the two additional ones
appear below the table). Either way, not first:

| scheme | within-scheme ambiguity |
|---|---:|
| naics | 41.76% |
| federal-hierarchy | 25.92% |
| treasury-account-symbol-structure | 21.44% |
| **gcmd-science-keywords** | **20.73%** |
| nasa-thesaurus | 18.95% |
| opm-ehri-workforce-codes | 8.31% |

(A validator using a lower row threshold also surfaced
`governmentwide-spending-data-model:domain-values` at 92.86% and
`sam-assistance-listing-controls` at 42.55%, putting GCMD sixth.) "Everything
else under 1.2%" was likewise false — fourteen schemes exceed it.

Nor is 100% isolation distinctive: six schemes are fully isolated, including
`opm-ehri-workforce-codes` at 16,465 concepts — 4.4× GCMD's size — while
`courtlistener-jurisdictions`, `psc` and `naics` are each 100% isolated *and*
zero-definition.

Each individual GCMD number is correct. The ranking claim built on them was not.

---


---

# Part IV — Corrections, retractions, and withdrawals


## Correction to an earlier claim

It was previously recorded that no regulatory document had been tagged
against this corpus. That is wrong. Real tagging runs exist:

- `output/mixed-real-data-*/concept_assignments.parquet`
- `output/rulespec-realworld-iteration-{2,3}*/concept_assignments.parquet`
- `output/segmentation-tagging-*-v4/tagging_concepts.parquet` (969 rows)

No single run holds 239 — that figure globs two runs (137 + 102). Their union
is 239 assignments over **89 subjects across 16 subject types** (document 24, docket 24, then gao_report, fcc_filing, lobbying_filing,
comment, cfr_section, federal_register_document and
regulatory_agenda_observation at 3 each), `method='llm'`, with
`evidence_json` grounding.

What is true is narrower: nothing at corpus scale, and nothing against Atlas.
Every run tagged into the fused registry.

## Two corrections to the record

1. ~~A claim that a tagging pilot scored **micro F1 0.085** was retracted — a
   later cross-repo code trace found no F1 was ever implemented and the only
   0.085 in the artifacts is `"assumed_cost_usd": 0.085608`.~~
   **[Corrected 2026-08-20] The retraction is false, and this report repeated
   it without checking.** The measurement is real and on disk:

   ```
   output/docpipeline-tag-diagnostic-gold-free-iteration-2-2026-07-26/metrics.json
     micro_f1        = 0.0851063829787234
     micro_precision = 0.06779661016949153
     micro_recall    = 0.11428571428571428
     novel_tag_rate  = 0.4868421052631579
     empty_tag_rate  = 0.30275229357798167
   ```

   Every digit of the original claim matches. `micro_f1` is emitted in code at
   `src/spicy_regs/docpipeline/tag_task.py:357` and written up with a full
   confusion matrix in `RULESPEC_FEEDBACK_ITERATION_2.md`. The retraction
   searched **spicysearch**; the pilot ran in **spicy-regs**.

   A real, dated, reproducible tagging measurement had been struck from the
   record on a false basis. The separate conclusion — that the *graph-search*
   question is unanswered — may still hold, because this pilot measured
   tagging rather than graph expansion, but it cannot rest on "no F1 exists."
2. `docs/concept-identity.md` is cited in several places but **has never
   existed in git history**. The source-scoped concept-identity doctrine it is
   cited for is not codified under any REF number.

## One correction to the research synthesis itself

A subagent reported that derived-graph rows are "deliberately absent from the
compact/Parquet consumer view, visible only in the raw RDF derived pack," and
this report called that wrong. **The retraction was itself mistaken on two
counts.** First, the sentence is not a subagent's synthesis — it is REF-042
(`docs/decisions.md:3315-3317`), an accepted decision. Second, in context it
describes the *streaming compact-role spool* (`_StreamingGraphSpool`,
`COMPACT_ROLES`), which genuinely carries no `DerivedRelation` role. The search
view is a different artifact and carries the table as a separately byte-copied
optional member. Both statements are true of different things.

What remains true and is the practically useful point: `derived-relations.parquet` is a declared optional member of
the search view — 46,466 rows in the 2026-08-20 cut — and
`parquet_search_view.py:62-72` carries it explicitly. REF-035 says RefSpec
materializes closure rows "only when a named consumer states which rows it
needs," which is *opt-in*, not *absent*. A tagger can read the derived graph
straight from Parquet.

## A reproducibility defect in this session's own audit commit

`research/evidence/registry-real-data-audit-2026-08-03/summary.json` re-dirties
on every run for a reason that defeats the point of digesting it. Comparing
commit `0604b4e2` against its parent across 153 members:

| | |
|---|---:|
| members compared | 153 |
| `byteLength` changed (real upstream drift) | 0 |
| **identical `byteLength`, changed `sha256`** | **4** |

`experiment-manifest.json`, `operator-derived-domain-candidates.jsonl`,
`publisher-organization-assertions.jsonl` and
`publisher-organization-objects.jsonl` each kept their exact width and changed
their hash — the signature of identifier churn, not content change. UUIDv7
`fetch_id`s regenerate with the same timestamp prefix and a fresh random tail,
and `experimentId` is content-addressed, so the digest can never answer "did
this change?"

**The fix is already in the repo and already honoured elsewhere.**
`src/refspec/registry/infrastructure/source_identity.py:72` documents the
contract explicitly — *"The caller records the returned value once. Rebuilds
receive that recorded value as input instead of calling this function again"* —
and `derive_uuid7(recorded_at, *, seed)` at `:83` is the repeatable form. The
Atlas v3 path honours it and publishes a `mintingRule`. `generate_uuid7` has
exactly two call sites, `fetch_id` (`:148`) and `registration_id` (`:185`) —
precisely the two field types that churn. The audit rebuild is calling it again
instead of reusing recorded values, violating its own documented contract.

Why it matters beyond tidiness: commit `0604b4e2` was recorded as "upstream
bytes drifted on two members." Real drift is currently indistinguishable from
UUID churn in this artifact — which is the exact failure a seal exists to
prevent. *(Found by a parallel session; verified here.)*

## Things checked and withdrawn

- **The `identifiers` table** — ~~not a gap; source identifiers are carried in
  `notations` and in the resource IRI.~~ **[Corrected 2026-08-20] The
  withdrawal was wrong on its stated ground, and there is a real gap.**
  The counts hold (MeSH 31,108/31,110, FAST 441,127/441,127,
  LCSH 468,006/514,837) but MeSH `notations` are **tree numbers**, not
  identifiers — `D000001` carries `[D02.355.291.933.125,
  D02.540.576.625.125, …]`, a classification path, many per concept. The
  DescriptorUI *is* built as a `ControlledIdentifier` upstream in
  `mesh_descriptors.py` and then dropped: `v3_registry_vocabularies.py`
  contains **zero** occurrences of `identifiers=`, so no vocabulary release
  ever populates `RegistryResource.identifiers`. That is why the table holds
  one scheme. The generalization also fails wherever notations are empty —
  nasa-thesaurus 0/22,622, doe-osti 0/23,626, icpsr 0/3,810, elsst 0/3,470,
  and every `lc-external-*` scheme at 0%. The right conclusion is not "no gap"
  but **"the gap is one unwired constructor argument"** — cheaper to close than
  most items in the Part V table.
- **The spicy-regs archive tags** hold nothing lost — byte-identical to main
  on every core file, with main strictly ahead.
- **The notebooks** are honestly-labelled hackathon demos. No technique there.
- **`spicysearch` has no divergent branches at all** — 374 commits, all
  ancestors of main.


---

# Part V — What to do

## For tagging

1. **Evaluate against FR topics, not agency** — 114,220 labelled documents,
   multi-label at 5.01 topics each, is a far stronger signal than agency.
2. **Draw a diverse evaluation set** from those 114,220 and fetch body text;
   do not reuse `fr-mirrulations-1k-v1`, which is degenerate for this.
3. ~~**Add `incorporation by reference`** to Atlas.~~ **Withdrawn** — it is
   already there, in `federal-register-api-topics`. The real question is whether
   a tagger may emit into the answer key's own scheme; if not, the 96 terms no
   independent vocabulary covers are the actual gap.
4. **Assert the FR-thesaurus ↔ FR-api-topics mapping** — 695 labels agree
   verbatim (698 case-folded), so evaluation stops depending on string
   coincidence.
5. **Keep the gazetteer scheme-scoped**; reconcile across schemes as a
   separate stage.
6. **Decide about TSCA** — swapping to Atlas drops 70,736 chemical
   substances that EPA rulemaking needs.
7. **Route candidates by ring.** The answer key is not a subject vocabulary;
   71 of its terms are agencies and 54 are values.

## For salvage

Ranked by value per hour. The top three are blocked on nothing.

*(Re-ranked after adversarial validation. Only item 1 was verified end to end.)*

| # | Do this | Cost | Why now |
|---|---|---|---|
| 1 | Teach `parquet_preflight` the three optional members, wire it into the Makefile | ~1 hour | **The only salvage item reproduced end to end by a validator** — 3.5 s run, exact failure text, and the second failure after patching. A fast gate in front of the authoritative pass. |
| 2 | Extract MeSH `ScopeNote` | ~6 source edits + a reseal | 30,960 descriptors carry one (not 31,110). Must select `PreferredConceptYN="Y"` — the naive path mis-attributes a synonym's definition on 5 descriptors. The `definition` field already exists; the cost is the fidelity-auditor version bump and the receipts/reseal cycle. |
| 3 | ~~Add `incorporation by reference` to Atlas~~ **Withdrawn** | — | **It is already in Atlas**, as a preferred label in `federal-register-api-topics`. The 93.6% → 99.7% figure only holds under the undisclosed exclusion of that scheme. What remains true: no *independent* Atlas vocabulary expresses it, so a tagger barred from emitting the answer key's own scheme still cannot reach it. That is a scope decision, not a missing concept. |
| 4 | Assert the FR-thesaurus ↔ FR-api-topics mapping | small | 695 labels agree verbatim (698 case-folded), one publisher. Stops evaluation resting on string coincidence. |
| 5 | Wire `RegistryResource.identifiers` | small | The DescriptorUI is already built as a `ControlledIdentifier` and then dropped: `v3_registry_vocabularies.py` has zero `identifiers=`. One unwired constructor argument. |
| 6 | Wire `known_items.py` into `metadata_relevance.py` | 1–2 days | Gold test cases with no human or LLM judge. Verified orphan — referenced only by its own test. |
| 7 | Re-run the USearch/ANN benchmark | ~1 hour of compute, but **low value** | The embedding precondition is genuinely met (top-50 band 0.0737 → 0.1064, 44% wider). But the rejection's *primary* ground was "no measured operational failure to fix", which a recall re-run cannot touch. Do the vocabulary work first, as the evidence file says. |
| 8 | Adopt RuleSpec's `rkaf-analysis` relation-change vocabulary | days | Compiled to Rust/JSON Schema/SHACL/TS, round-trip tested, zero behavioural consumers. **But see the shape-reconciliation note below — this is a union, not a swap.** |
| 9 | Give `docpipeline/retrieval.py` an entry point | days | 5,479 lines of working hybrid retrieval, no callers, while a simpler module re-derives RRF beside it. |
| 10 | Rebase the two auditor readers | **days, not hours** | 62 commits behind on branches whose shared file has moved +18,134/−2,604 since. And it buys audit coverage, not gap closure — neither source ships in the seal. |
| 11 | Switch GCMD to its published RDF export | days | Fixes isolation, definitions and ambiguity at once — though GCMD is 4th on ambiguity by the >400-row cut, 6th counting every scheme — not 1st. |

**Decisions that need a person, not an engineer:**

- **TSCA.** Moving to Atlas drops 70,736 chemical substances. EPA is the
  among the largest agencies in the labelled set (19,285 documents list EPA).
- **Vocabulary induction.** Deferred, never coded. *"A 2-5K vocabulary is
  auditable by a small team; 513,236 is not, and an unauditable vocabulary is
  a defect in a product whose north star is the join surface."*
- **The lifecycle hold.** RefSpec's lifecycle system, RuleSpec's
  `rkaf-analysis`, spicy-regs' `ClosureClaim` and DocSpec's negative-evidence
  ledger are four implementations of one idea, none running. Either commit to
  the idea once, in the repo that owns it, or stop rebuilding it.
- **DocSpec's Office formats.** Lost in the 2026-08-05 rewrite without a
  tracked follow-up. Latent today — no Office files exist in the local
  corpora — but it will bite the moment attachments flow through.

**Conventions to adopt as house style**, all already invented here: declared
gaps as structured data attached to every resource; append-only corrections on
sealed records; never blending failure modes into one score; quoting both the
benchmark and product-path denominators.

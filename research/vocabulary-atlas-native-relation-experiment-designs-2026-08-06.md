# Experiment designs against the native-relation Atlas dataset

**Date:** 2026-08-06
**Companion to:** `vocabulary-atlas-native-relation-experiments-2026-08-06.md`
**Dataset:** `research/evidence/atlas-v3-native-relation-testsets-2026-08-06/`

Concrete designs for every scenario in the catalogue, written against the data
already compiled. Each entry states what is held, what is varied, what number
comes out, and what threshold changes the production configuration.

## Scope check — which ring, and for whom

RefSpec is the knowledge graph powering **SpicyRegs** (metadata), **DocSpec**
(segmentation and tagging), **SpicySearch** (indexing and query) and **RuleSpec**
(rule extraction and core ontology). The Atlas carries four semantic rings, and
the split of work below is heavily uneven across them:

| Ring | Relations in committed evidence | Designs that serve it |
| --- | ---: | --- |
| `subject` | **582** | Parts 1–7 and E-V1…E-V8 — nearly this entire document |
| `entity` | **0** (478 concepts, no edges) | V-2, V-7, V-9, E-S20 |
| `value` | **0** | E-S20 |
| `legalIdentity` | **0** | V-2, V-7 |

Read Part 8 with that table in view. The "vertical approaches" are filed last and
described as longer-horizon, but V-2, V-7 and V-9 are the only designs here that
populate the rings carrying the product's stated traceability requirement — and
they are data plumbing rather than modelling research. Their position in this
document reflects the order they were thought of, not their value.

## Phase gate — knowledge-graph relations now, documents after

The current phase is **relations between vocabulary concepts**. Anything reading
document text or topic assignments is deferred, however cheap:

| Deferred to the document phase | In scope now |
| --- | --- |
| E-S11, E-S12–E-S18, E-S20 | E-S4a/b/c, E-S5–E-S10, E-S19 |
| V-1 (co-assignment PMI), V-2 (citations), V-3 (scope-note synthesis), V-9 (lineage) | V-4, V-5, V-7, V-8 |
| — | E-S7, E-S8, E-S9a, E-S21–E-S23, E-V1–E-V8 |

V-6 (orphan rescue) splits: its dense and generation signals are in scope, its
co-assignment and citation signals are not.

**The costliest consequence is V-2.** It was the cheapest route into the
`legalIdentity` ring and it is document-derived. **V-7 is not**, and in this
phase it is the only design that touches traceability at all — which moves it
from "longer-horizon vertical" to near the top of the runnable list.

## Assets available

| Asset | Contents | Reuse |
| --- | --- | --- |
| Three test-set JSONL files | 16,449 typed rows, publisher-asserted | Gold for every scoring experiment |
| Ablated corpus export | 7,985 concepts × label/aliases/definition/notes | Input to any encoder, no `refspec` import |
| 54 rank artifacts (`npz`) | `uint32` pair code + `uint8` rank, shared index | Union, frontier, reservoir, precision sampling. Promoted to `output/atlas-e3-rank-artifacts-2026-08-06/valid/` — durable but git-ignored; digests in the promotion manifest |
| Structure report | DAG confirmed, closure sets, degree | Entailment classification, orphan analysis |
| Pareto results | Non-dominated (pairs, recall) points | Budget selection |
| Sealed `/tmp` evidence | 34 promoted artifacts — blind samples, fixed decisions, audits, cost and frontier receipts, 7 digest-verified against the 2026-08-05 ledger | Reopenable provenance for every acceptance gate the ledger cites |
| Crosswalk archive | 1,095 cross-vocabulary candidates, 2 sealed judges, 582 admitted / 513 rejected, generation class per row | Precision, direction, agreement, calibration — **not recall** |
| Blind review | 1,095 independent verdicts + directness, sealed key withheld | Third-opinion agreement, lattice validation |
| Benchmark sets | 582 positives / 157 hard negatives / 270 controls / 86 disputed / 1,095 directness, each with `usableFor` + `notUsableFor` | Scoped evaluation; **`disputed` is the adjudication-policy benchmark and stays unresolved** |
| `relatedMatch` blind review | 95-row sealed sample, two independent passes, comparison; survival by stratum and variant class | E-V4 judged half; framing sensitivity; a third calibration reading |
| Admission replay | Five lattice variants scored over all 1,095 rows; the v2 rule reconstructed and reproduced exactly (582/582, 0 mismatches); relation share, variant hygiene, order independence | E-V1, E-V4, E-V5, E-V7 answered; any further lattice proposal drops straight in |

**Scoring convention held constant everywhere:** exact full-pairwise similarity,
blockwise, no approximate index; self-pairs excluded; a pair's rank is the better
of its two directions; stable tie-break on member-IRI order; retained at rank
≤ 100. Any experiment deviating from this must say so.

---

# Part 1 — Text and prompt structure

Called out separately because it cuts across every scenario and is the cheapest
lever available. All variants run on the same corpus, same models, same scoring.

## The variant grid

| ID | Variant | Example rendering |
| --- | --- | --- |
| V1 | Label only | `LOANS` |
| V2 | Label + aliases concatenated *(current)* | `LOANS \| BANK LOANS` |
| V3 | **Max over individual labels** | embed `LOANS` and `BANK LOANS` separately; pair score = max over all label-pair combinations |
| V4 | Lowercased label | `loans` |
| V5 | Scheme-qualified | `ELSST social science thesaurus — LOANS` |
| V6 | Typed instruction | `subject heading: LOANS` |
| V7 | Definition-first *(current)* | `Money lent at interest. LOANS` |
| V8 | Field-tagged structured *(current)* | `label: LOANS \| definition: ...` |
| V9 | Natural sentence *(current)* | `The concept LOANS. Also known as ...` |
| V10 | Definition only, no label | `Money lent at interest.` |
| V11 | Definition truncated to 200 chars | `Money lent at interest...` |

**E-T1 · Which rendering maximises product-relevant recall.**
Hold model (`bge-small`, `openai-3-large`, `opensearch`) and scoring fixed. Vary
V1–V11. Measure hierarchy + equivalence recall at K10 and K100, per source.
*Decides* the production view. Ship the variant that wins by >2 points on both
classes; if none does, ship V1 for cost.
*Cost:* local models free; ~$0.15 for one provider pass. *Status:* runnable now.

**E-T2 · Alias dilution, dense analogue.**
Hold everything fixed. Vary V2 against V3 only. Measure equivalence recall on
ICPSR's 485 `use` pairs and ELSST/FR associative.
*Rationale:* the lexical run lost `Family planning`↔`BIRTH CONTROL` at K100
because alias-bag concatenation dilutes an exact shared alias. V3 is the dense
equivalent of the max-over-individual-label anchor. *Decides* whether alias
handling should be max-pooled rather than concatenated across all arms.
*Prediction:* V3 wins on equivalence; if it does, it likely wins harder
cross-vocabulary, where alias overlap is the primary equivalence signal.

**E-T3 · Casing as a cross-vocabulary confound.**
Hold model fixed. Vary V1 against V4. Measure per-source recall.
*Rationale:* ELSST is uppercase, ICPSR lowercase, FR sentence case. If encoders
are casing-sensitive, cross-vocabulary matching carries a systematic penalty that
has nothing to do with meaning. *Decides* whether to normalise casing before
encoding. *Threshold:* any per-source delta >3 points means normalise.
*This is the cheapest experiment in the document and a live confound in the
production task.*

**E-T4 · Scheme qualification against polysemy.**
Hold model fixed. Vary V1 against V5. Measure recall **and** the precision proxy
from E-S1 — specifically whether `U.S. Government Manual`/`MANUAL WORKERS`-class
false pairs drop.
*Decides* whether vocabulary context should be injected. Expect flat or slightly
lower recall with better precision; for a traversed graph that trade is worth
taking.

**E-T5 · Do definitions carry meaning alone.**
Vary V1 / V10 / V11. Measure recall on ELSST only (903 definitions, 893 notes).
*Decides* how much definition text to include and whether truncation is safe.
*Note:* FR and ICPSR carry no definitions, so this is ELSST-only by construction
and doubles as a sensitivity check for E-S9.

---

# Part 2 — Graph quality

## S1 · Edge precision under traversal

**E-S1a · Classify the unmatched.**
Hold the arm fixed (`openai-3-large.label@10`). Take every retrieved pair not in
gold. Partition into (i) transitively entailed by the closure, (ii) sibling pairs
sharing a parent, (iii) neither. Measure the three-way split.
*Decides* how much apparent noise is actually entailment. Runnable now from the
structure report plus rank artifacts; no judging needed.

**E-S1b · Judge the residual.**
Take a stratified sample of 300 from bucket (iii). Send to two blind judges with
the same rubric the campaign will use. Measure per-edge error rate `p`.
*Decides* the admission threshold. Then compute compounded traversal error
`1-(1-p)^n` for n = 1,2,3 and set max traversal depth so compounded error stays
under whatever the product tolerates.
*Cost:* ~$1.60. **This is the single most important missing number** — the
product traverses the graph and nothing has measured edge precision.

**E-S1c · Precision by arm and depth.**
Repeat E-S1a per arm at K1, K10, K100. Measure the entailed / sibling / neither
split as a function of depth.
*Decides* the production cutoff on precision grounds rather than recall grounds.
*Hypothesis:* the "neither" fraction grows with depth, meaning deep retrieval
buys noise.

## S2 · Graph coverage and connectivity

**E-S2 · Reachability audit.**
Hold the admitted graph fixed. Compute, per source and for the union: zero-edge
concepts, weakly connected components, component size distribution, diameter,
degree distribution, and the fraction of concept pairs reachable in ≤ 2/3/4 hops.
*Decides* whether traversal works at all. *Known:* ICPSR hierarchy touches only
1,984 of 3,810 concepts. *Threshold:* an orphan rate above ~20% means the graph
cannot be the primary navigation structure for that vocabulary.
*Extend* `analyze_atlas_native_relation_structure.py`. Runnable now, minutes.

## S3 · Path explainability

**E-S3 · Path plausibility sample.**
Hold the graph fixed. Sample 100 (concept, concept) pairs reachable in 2–4 hops.
Render the path with predicates and intermediate labels. Have a reviewer mark
each path as *usable navigation* or *not*.
*Decides* the traversal depth exposed to users, and produces the UI copy for
"why this matched". Reuses the path-rendering logic from
`analyze_atlas_candidate_path_evidence.py`.

---

# Part 3 — Atlas construction

## S4 · Cross-vocabulary transfer — **the blocking experiment**

**E-S4a · Exhaustive small-pair gold.**
CRS Policy Areas × Federal Register = 32 × 705 = 22,560 pairs. Judge **all** of
them with two blind judges. Measure the complete typed relation set.
*Decides* nothing by itself — it *creates* the first cross-vocabulary gold.
*Cost:* ~$120–200. *Note:* this pair is small enough that "recall" is not
estimated but known, which no sampling can match.

**E-S4b · Does intra-vocabulary calibration transfer.**
Hold arms and configs fixed. Score every arm against E-S4a gold. Measure the
Spearman correlation between arm ordering here and arm ordering on the
intra-vocabulary sets.
*Decision rule:* ρ > 0.8 → intra-vocabulary calibration is reusable for free on
every future release, and the whole native-relation programme becomes a standing
harness. ρ < 0.5 → none of the current rankings configure production and the
arm selection must be redone cross-vocabulary.

**E-S4c · Text-poverty interaction.**
Within E-S4a, stratify by whether the FR endpoint has an alias. Measure recall
separately.
*Decides* whether the CRS/FR pairs underperform because of the vocabularies or
because of missing text — which routes directly to E-S9.

## S5 · Closure-scored recall

**E-S5 · Rerun every arm against closure gold.**
Hold arms, corpus, and scoring fixed. Vary the gold: asserted hierarchy (3,393 /
1,763) versus transitive closure (7,608 / 2,539). Measure recall under both, per
arm.
*Decides* how much of the reported miss is gold sparseness. *Watch for the
asymmetry:* a model that encodes taxonomy should gain more under closure than a
topical model. If arm ordering changes between the two golds, the asserted-gold
rankings in the companion document are wrong.
*Status:* runnable now — closure sets already computed. Free.

## S6 · Class mix by depth

**E-S6 · Retrieved-gold composition curve.**
Hold the arm fixed. Vary K over 1, 2, 3, 5, 10, 20, 50, 100. Measure the
proportion of retrieved gold that is equivalence / hierarchy / associative.
*Decision rule:* if the associative share rises monotonically with K while
hierarchy and equivalence saturate by K10, cut production depth at the saturation
point — deep retrieval is then buying candidates the directness rubric will
discard. Free, minutes.

## S7 · Directness calibration

**E-S7 · Rubric versus professional editors.**
Sample 300 rows stratified across the 10,808 publisher-asserted `related` edges
(FR 780 / ELSST 2,848 / ICPSR 7,180), plus the 204 one-way rows as a
sub-stratum. Apply the strict `directly_related` / `generic_thematic` /
`redundant_via_existing_path` rubric with both blind judge families.
Measure keep rate per source, and the one-way versus reciprocal difference.
*Decides* whether the bar is a defensible position or uncalibrated. *Also:* if
one-way edges are killed at a higher rate, publisher asymmetry is a usable weak
signal. *Cost:* ~$1.60.

## S8 · Judge direction accuracy

**E-S8 · Direction against publisher ground truth.**
Sample 400 from the 5,156 hierarchy rows, balanced across ELSST and ICPSR and
across depth-in-DAG. Present blind, **hierarchy text ablated**, ask for relation
and direction. Measure direction accuracy and the both-support-but-disagree rate.
*Decides* whether the conditional adjudication lane is sized correctly.
*Stratify by DAG depth* — if accuracy collapses near roots, that is a specific
fixable failure. *Cost:* ~$2.10.

## S9 · Text enrichment

**E-S9a · Upstream text audit.**
For FR and the three CRS releases, inspect the published source for scope notes,
hierarchy, or alternate labels the importer is not ingesting. Measure fields
available versus fields loaded. Read-only, free.

**E-S9b · Closed-loop enrichment test.**
Hold arms fixed. Vary the FR corpus: current versus enriched. Measure recovery of
FR's own 780 associative edges.
*Rationale:* FR's own relations test FR's own text — proving enrichment works
before spending it on cross-vocabulary. *Threshold:* the Anatomy analogue gave
+13 gold with 16,416 *fewer* candidates; anything approaching that ratio makes
enrichment the highest-return work available.

## S10 · Cross-predicate structural transfer

**E-S10 · Associative→hierarchy and hierarchy→associative.**
Seed candidates from exact-label and mutual-top-1 anchors, expand one hop through
the *associative* graph only, score against *hierarchy* gold. Then reverse.
Measure recall gain over text-only arms and unique rescues.
*Non-circular by construction* — the predicate used for expansion is never the
predicate scored. *Decides* whether publisher association predicts publisher
hierarchy, which is the graph-native analogue of the anchor-gated expansion arm
the ledger kept. Free.

---

# Part 4 — Tagging

## S11 · Document→concept gold

**E-S11 · Build tagging test sets.**
Extract `topicAssignments` cross-ring relations (GAO products, CBO topic codes)
from the v3 registry document loaders. Emit per-source test sets in the same row
shape as the native-relation sets. Measure count of labelled document→concept
pairs and concept coverage.
*Decides* whether tagging gets free gold. New tool, mirrors
`build_atlas_native_relation_testsets.py`.

## S12 · Asymmetric retrieval

**E-S12 · Query/document conventions.**
Hold models fixed. Vary the convention: symmetric (what ran) versus
`RETRIEVAL_QUERY` on the passage and `RETRIEVAL_DOCUMENT` on the concept; Nomic
`search_query:`/`search_document:`; Arctic query prefix on the passage only.
Measure tagging recall at 1/3/5/10 concepts per section.
*Decides* the encoder configuration for tagging and search. **The asymmetric half
of every model here is untested** — the symmetric-everywhere decision was correct
for Atlas construction and wrong for tagging.

## S13 · Tagging reranker

**E-S13 · Cross-encoder over passage/concept.**
Hold the candidate concepts fixed (top 50 per section from E-S12's best arm).
Score `(passage, concept)` with `cross-encoder/ms-marco-MiniLM-L6-v2`. Measure
precision at 1/3/5.
*Note:* cap the reservoir **by best cross-arm rank, not alphabetically** — the
Atlas-side reranker run was invalidated by exactly that mistake.
*Decides* whether reranking earns its cost. Better fit here than in Atlas
construction: MS MARCO trains query→passage relevance, which is this task's shape,
not concept↔concept semantic relation.

## S14 · Tag count calibration

**E-S14 · Tags per section.**
Vary the emitted tag count 1–10. Measure precision and recall against assigned
gold, and the resulting graph fan-out per document.
*Decides* the tagging threshold. *Connects to S1:* over-tagging is the upstream
cause of a noisy hyper-connected graph — every spurious tag is a false traversal
entry point.

---

# Part 5 — Search

## S15 · Query→tag triggering

**E-S15 · Trigger accuracy by query length.**
Generate queries from gold-tagged documents at 1, 2, 3, and 5+ words. Measure
whether the document's assigned tag fires in the top 1/3/5.
*Decides* the confidence threshold for using the graph versus falling through to
plain text search.

## S16 · Hybrid weighting

**E-S16 · Three-way weight sweep.**
Hold the corpus and query set fixed. Vary the weights on tag filter, dense text,
and BM25 over a coarse grid. Measure nDCG@10 against relevance derived from
E-S11 assignments.
*Decides* the ranking formula. Report the single-signal baselines too — if tags
add nothing over dense+BM25, the graph is not paying for itself in search
(it may still pay for itself in browse).

## S17 · Query-time expansion depth

**E-S17 · Expansion ablation.**
Vary expansion: exact tag / +equivalent / +narrower / +related / +2 hops. Measure
precision and recall of the returned document set.
*Decides* the traversal budget per query. **This is where S1's compounded error
becomes user-visible** — run E-S1b first so the error rate is known before
choosing a depth.

## S18 · Emerging-topic fallback

**E-S18 · Recency stress.**
Hold the vocabulary fixed. Issue queries on topics postdating each vocabulary
edition (PFAS, AI governance, COVID variants). Measure tag-trigger failure rate
and whether text fallback recovers the documents.
*Decides* the bypass rule and produces the shortlist of terms the vocabulary
needs.

---

# Part 6 — Longitudinal and structural

## S19 · Vocabulary version mapping

**E-S19 · ELSST R5→R6 as a cross-edition task.**
Hold arms and scoring fixed. Vary the pair: ELSST R5 × ELSST R6. The repo already
holds an R5/R6 managed release
(`output/elsst-r5-r6-managed-release-2026-07-29`). Measure recall of known
split / merge / retire / stable cases.
*Decides* whether documents tagged under an earlier edition stay findable — the
failure mode that silently rots a graph product over time. Structurally identical
to cross-vocabulary matching, so it also serves as a second transfer check
alongside E-S4b.

## S20 · Non-subject rings

**E-S20 · Query facet audit.**
Collect a realistic query sample for government documents. Classify each by the
facets it requires: subject, agency, statute, jurisdiction, date, document type,
status. Measure the fraction answerable by subject tags alone.
*Decides* how much of the search problem subject tagging can solve. *Expectation:*
well under half — `"EPA rules on PFAS since 2024"` is agency + subject + date +
doctype, and only one of those four is in scope today.

---

# Part 7 — Methodology hygiene

**E-S21 · Reproducibility gate.**
Encode the same corpus three times in fresh processes on the same host, then once
after a restart. Measure vector-digest stability per model.
*Blocks everything.* The ledger records an unexplained BGE digest change with
FastEmbed, ONNX Runtime, NumPy, model revision, and the optimized ONNX file all
pinned.

**E-S22 · Dimensionality control.**
Hold the model fixed. Vary output width across 256 / 384 / 768 / 1536 / native
where Matryoshka truncation permits. Measure recall.
*Decides* whether the current cross-model comparison is confounded — it is, since
models ran at 384 to 1536. Also decides the storage/quality trade for the
production concept index.

**E-S23 · Inter-annotator agreement.**
Have a second reviewer judge a fixed 100-row sample already judged once. Measure
agreement on support, relation type, and directness.
*Decides* whether the human baseline everything calibrates against is stable.
Every human judgment in the ledger is single-reviewer, and the directness
re-review flipped 52 of 65 of that same reviewer's prior positives.

---

# Part 8 — Vertical approaches

Everything in Parts 1–7 varies *how text is matched*. These vary **what signal is
used at all**, and most are specific to government documents rather than to
retrieval in general.

Wave 1 makes the case for them concrete. Retrieval fails hardest on the
token-disjoint half (36–44% recall), precision collapses with depth (92.8%
unexplained at K100) and compounds across hops, and 15–48% of concepts have no
edge of any kind. Those are three different holes, and none of them closes by
tuning a text matcher. What they need is evidence that is **orthogonal to label
text**.

## V-1 · Co-assignment PMI — usage evidence

Build a term × term co-occurrence matrix from document topic assignments, score
by pointwise mutual information, rank top-K per term. Score against native gold
and **report the token-disjoint slice separately**. Measure unique rescues over
`bge-small.label@10`.
*Why it should work:* a human indexer put two terms on one document because the
document is about both. That is a semantic link with no textual basis — exactly
the signal missing where retrieval fails.
*Decides* whether usage evidence beats text evidence in the disjoint half. If it
does, the architecture changes: the best relation signal comes from tagging
output, and the system becomes self-improving.
*Free.* Depends on E-S11. **Check assignment volume first** — PMI needs enough
documents to be stable.

## V-2 · Citation and cross-reference structure

Extract citations from Federal Register and CRS documents (authorising statute,
prior rules, docket, CFR parts). Measure whether co-cited documents share tags,
and whether citation co-occurrence predicts term relations.
*Why:* a rule citing 42 U.S.C. 7401 is about air quality whether or not its text
says so. This is a high-precision graph edge that needs no inference, in a
product whose thesis is graph strength — and it is unavailable to a generic
search engine.
*Highest ceiling on this list.* Cost is data plumbing, not compute.

## V-3 · Synthesised scope notes — enrichment for text-poor vocabularies

Generate a scope note per Federal Register term from its label plus documents it
is assigned to. Hold arms fixed, vary only the text, measure recovery of FR's own
780 associative edges.
*Why:* input text was the largest effect measured anywhere (+13 gold with 16,416
*fewer* candidates on Anatomy), and FR has **zero definitions across 705 terms**.
Closed-loop: FR's own relations prove the enrichment before it is spent
cross-vocabulary. This is E-S9b with a generation step where no upstream text
exists. **~$2.**

## V-4 · Generate-then-verify — escaping the retrieval ceiling

For 200 concepts, ask a model for broader / narrower / related terms, then
**verify each against the vocabulary** by exact and alias match. Measure
verification rate, recall of publisher hierarchy, and unique rescues over the
best dense arm.
*Why it differs in kind:* every other design uses the model to *judge* pairs
retrieval proposed, so retrieval is a hard ceiling. Generation escapes it, and
verification against a closed vocabulary contains hallucination deterministically.
**~$3.**

## V-5 · Order, box, or hyperbolic embeddings — the right geometry

Fit on 80% of the hierarchy, test on held-out. Measure direction accuracy,
transitive consistency, and recall against **closure** rather than asserted gold.
*Why:* cosine similarity is symmetric; hierarchy is antisymmetric and transitive.
Bidirectional min-rank is a patch over that mismatch, not a fix. Order and box
embeddings represent entailment as containment; hyperbolic space represents trees
with far lower distortion. Two concrete payoffs: **direction for free** (currently
an unmeasured judge decision) and native transitivity, which is exactly where
closure scoring showed the largest losses (96% on direct edges, 78–86% on distant
ancestors).

## V-6 · Orphan rescue — coverage, not recall

Take the 589 ICPSR and 139 FR concepts with no edge of any kind. Ask which
signals — dense, co-assignment, citation, generation — propose *any* plausible
edge. Measure the fraction made reachable.
*Why it is a different target:* recall measures whether known edges are found.
This measures whether the graph is navigable. A concept nobody can browse to is
invisible regardless of tagging quality, and no recall number detects that. Cheap.

## V-7 · Authoritative hierarchy anchoring

Map subject terms onto CFR title/part/section, USC titles, NAICS, and budget
function codes. Measure coverage and whether they supply hierarchy the
vocabularies lack.
*Why:* these are published, authoritative, already-hierarchical structures over
the same subject matter, and they give cross-vocabulary bridges via a shared
spine. The 2026-08-05 proposal lists publisher-crosswalk ingestion as deferred;
this is that work, with a measurement attached.

## V-8 · Domain-matched encoder

Swap in a legal or regulatory encoder (Legal-BERT class) and rerun the standard
arm comparison.
*Why:* general-purpose encoders were tested and a *biomedical* specialist was
explicitly rejected for the policy domain, but a domain-*matched* specialist was
never tried. Statutes and case law are far closer to this register than MS MARCO
web text. One cheap run, low expectations.

## V-9 · Docket and legislative lineage propagation

Propagate tags within rulemaking chains (NPRM → comments → final rule) and
legislative lineage (bill → law → rule). Measure precision of propagated tags
against assigned gold.
*Why:* documents in one chain share subject matter by construction. Free tag
propagation at near-perfect precision, no model involved.

---

# Part 9 — Validating the assumptions this session created

The crosswalk blind review produced four claims that now sit under decisions.
Each was measured once, by one method, and each deserves a check before it
configures anything.

## E-V1 · Does the class-conditioned lattice actually recover 85 mappings? — **run, answer is 37**

**Claim under test:** 86 rejections died on relation-type disagreement, and
collapsing `same`/`near_same`/granularity for label-equality candidates recovers
them without admitting anything false.

Hold the sealed judge verdicts fixed. Vary the admission rule: current v2 lattice
versus a class-conditioned variant that treats `same`, `near_same`, and a
one-step granularity shift as compatible **only** for `normalizedLabelEquality`
and `alternateLabelEquality` candidates. Replay all 1,095 rows.
*Measure* newly admitted count, and — critically — how many **controls** the
relaxed rule would now admit. A rule that recovers 85 mappings but lets in
sibling distractors is not a fix.
*Decision rule:* ship if control admissions stay at zero and newly admitted rows
survive a spot re-review. Free, replay only.

**Result (`replay_atlas_crosswalk_admission.py`).** The designed rule recovers
**37 rows, +6.4%** — not 85. It adds **zero** control admissions, and an
independent reviewer supports all 37, calls all 37 `direct_candidate`, and names
one of the two judges' relations in 35. Extending the collapse to every
generation class adds 3 more on no principle. Reaching 85 requires treating
`related` as compatible with a direction, which admits **four more sibling
distractors** and is weaker on every quality signal — disqualified by this
design's own bar.

**A better-motivated rule than the one designed.** Running E-V5 alongside this
produced **R4**: R1, plus edit-distance candidates whose labels differ only by
number agreement, diacritics, or a known US/UK spelling. The granularity collapse
is safe wherever two labels denote the same term, and an orthographic variant
qualifies as squarely as an alias does. R4 recovers **39 rows (+6.7%)**, still
zero controls, and the two extra rows are `BUSINESSES`/`business` and `Child
labor`/`CHILD LABOUR`.

*Be precise about what R4 buys.* R4 ⊂ R2 by construction, and they differ by a
single row — `ROAD TRAFFIC`/`traffic`. One row in 582 is 0.17%; this archive
cannot resolve a preference that small. R4 is the recommendation because it can
state a reason for every admission, not because it measures better. An earlier
draft claimed R2 got to 40 by admitting "two coincidences"; that was wrong — R2's
two extra edit-distance rows are R4's two principled variants — and is withdrawn.

*Independent support arrived later.* The E-V4 blind passes never rejected or
called orthographic a single `numberVariant` or `spellingVariant` (0 of 6 and 0
of 3, both passes), which is the eligibility test R4 turns on, judged by reviewers
who had never seen it.

Two amendments the run forced on the design itself:

- **The decision rule's premise was false.** Control admissions were never zero:
  69 controls clear the v2 lattice on judge verdicts alone. They are kept out by
  a **control-class exclusion that runs before the lattice**, which is how the
  rule reproduces 582/582. Read the bar as *no controls added relative to
  baseline*, and always measure with the class exclusion lifted.
- **The 86 rows are two populations, not one.** 40 are a granularity dispute (a
  lattice defect, recoverable); 40 are `related` versus a direction (a genuine
  associative-versus-hierarchical disagreement); 5 are equivalence versus
  `related`; 1 has the judges contradicting each other outright. Only the first
  group should ever be resolved by rule.

## E-V2 · Is the third reviewer trustworthy enough to have confirmed them? — **premise reversed**

**Claim under test:** 85/86 confirmation is meaningful.

The reviewers rejected only 68.9% / 67.8% / 85.6% of controls against the sealed
judges' 100%, with the loss concentrated in `siblingDistractor`. Hold the blind
sample fixed; vary the reviewer. Run a second independent pass with a different
model family, and a third with the control classes explicitly flagged as
adversarial in the prompt.
*Measure* control rejection rate per reviewer, and whether the 86 recoverable
rows still confirm.

**Result — the calibration half, free from recorded bytes.** The sealed judges'
100% was never measured; it was the control-class exclusion above. Measured
directly, the judges name a relation on **55.6%** and **57.0%** of sibling
distractors and the reviewer names one on **48.1%**; on random negatives it is
5.2% / 5.2% against **3.7%**. The reviewer is at or below both judges in every
per-crosswalk cell. It also discriminates — 99.3% support on admitted rows
against 15.9% on real rejected candidates and 3.7% on random pairs, a likelihood
ratio of 6.2× and 26.8×.

Sibling distractors are not clean negatives anyway: a sibling shares a broader
concept by construction, so `related` is often correct, and it is what the judges
said in 117 of their 152 supporting verdicts on that class.

**What survives.** The reviewer confirmed the wrong proposition. All 86 rows
already had two judges asserting a relation exists, so a third opinion on
existence was pre-answered and 85/86 is the expected result, not an informative
one. Type is the binding question and there the reviewer is a third opinion, not
a tiebreak.

**Result, second instalment (2026-08-06).** The adversarial-framing arm has now
run, on the sealed 95-row sample built for E-V4. Two findings.

*Calibration, third time of asking.* Neither new pass asserts a relation on a
single random negative (0/12 and 0/12, against the judges' 5.2% and the earlier
reviewer's 3.7%), and on sibling distractors they sit at 25.0% and 8.3% against
the judges' 55.6% and 57.0%. Three independent Opus reviewers have now been
measured on seeded negatives and all three sit below both sealed judges.

*Say only what the counts support.* On the earlier reviewer's full 135-row
classes the gap is not significant — Fisher exact gives p = 0.77 on random
negatives and p = 0.27 / 0.18 on siblings. The new passes are on 12 rows per
class and resolve less still. What survives is the negative claim, which is the
one that mattered: the reviewer did not fail a calibration the judges passed,
because the judges' 100% was a class exclusion and their measured rate is no
better than the reviewer's.

*Framing sensitivity, which is the number nobody had.* Identical bytes, one
neutral prompt and one adversarial: agreement is **89.5%** on whether a relation
exists, **86.3%** on which relation, **74.7%** on basis. Prompt framing alone
moves about a tenth of the existence judgments. Every single-pass judging figure
in this programme carries that much slack and none was reported with it.

**Still open, and now the binding limit:** a pass from a *different model family*.
Everything measured to date is Opus judging Opus-adjacent work, and the passes
agree with each other (85.3% / 80.0% exact relation with the earlier reviewer)
markedly more than any of them agrees with the sealed Gemini/OpenAI pair
(74.4–78.8%). That clustering is exactly what a family effect looks like, and no
amount of re-prompting inside one family can distinguish it from consensus.

**One design assumption failed.** Told only that plants existed, the adversarial
pass identified **23 of the 24 controls** without the key (95.8% recall, 69.7%
precision; 13/13 on its random-pairing tier). Seeded controls are not hidden from
a warned reviewer, so their calibration value collapses in exactly the setting
this experiment was built to create. Warn the reviewer or keep the controls
hidden — not both.

## E-V3 · Is the directness asymmetry real or a rubric artifact?

**Claim under test:** directness cuts 80% intra-vocabulary and only 5–7%
cross-vocabulary, because cross-vocabulary pairs are mostly equivalence and
hierarchy with little room for generic-thematic noise.

Hold the rubric and reviewer fixed. Vary only the population: the 65 sealed
intra-vocabulary re-review rows versus a matched cross-vocabulary sample
stratified to the same relation-class mix.
*Measure* keep rate in each.
*Decides* whether the strict directness machinery is worth applying to
cross-vocabulary admission at all. If the asymmetry survives class matching, the
rubric can be dropped from the cross-vocabulary path and its cost with it.

## E-V4 · Does `relatedMatch` absorb noise from every weak generator, or only edit distance? — **measurement half run**

**Claim under test:** `relatedMatch` is a sink — edit-distance candidates produce
it at seven times the base rate, with a plausible association attached after the
fact.

Hold the judge verdicts fixed. Vary the generation class. Measure `relatedMatch`
share of admissions per class, and have a reviewer mark each admitted
`relatedMatch` as *genuine association* or *post-hoc rationalisation of a string
coincidence*.
*Decides* whether `relatedMatch` needs a per-class admission bar, or whether
edit-distance candidates should simply be barred from producing it. Cheap.

**Result.** Confirmed and localised. Against a 6.0% base rate:
`normalizedLabelEquality` **0.0%** (never, not rarely), `alternateLabelEquality`
8.3%, `substringNearMiss` 9.2%, `editDistanceNearMiss` **43.3% — 7.2×**. Edit
distance supplies 13 of the archive's 35 `relatedMatch` admissions off 5% of the
admissions. E-V5 then narrows the owner further: it is the *unprincipled* portion
of edit distance, not the arm as a whole.

**Result, judged half.** Two blind passes over a sealed 95-row sample — all 35
`relatedMatch` admissions, 36 class-matched admissions carrying other relations,
24 unlabelled controls. A row *survives* if the reviewer asserts a relation and
says the connection runs through meaning rather than spelling.

| Stratum | n | Neutral | Adversarial | Both |
| --- | ---: | ---: | ---: | ---: |
| `relatedMatch` admissions | 35 | 85.7% | 71.4% | **71.4%** |
| Other admissions | 36 | **100%** | **100%** | **100%** |

All 36 non-`relatedMatch` admissions survive both framings; 10 of 35
`relatedMatch` fail at least one. So `relatedMatch` really is where the noise is,
and it is **28.6% of the class rather than all of it** — the 43.3% and 70.6%
label-share figures counted how often the label was awarded, not how often the
award was deserved.

**The failures land in one place:** 8 of the 10 are `editDistanceNearMiss` rows
the E-V5 classifier calls `unprincipled`. Neither pass ever rejected or called
orthographic a single `numberVariant` or `spellingVariant` — 0 of 6 and 0 of 3,
both passes. Reviewers who never saw the classifier partitioned the arm exactly
where it does.

*Decides:* `relatedMatch` does not need a blanket per-class bar. It needs the
E-V5 generator restriction, which removes the population producing the failures.

**Instrument defect, recorded not patched.** `basisOfAssociation` offered two
values and no third for *no association at all*; the two passes resolved that gap
in opposite directions, so on rejected rows the field carries convention rather
than signal. All figures above use the only well-posed denominator — rows where
the pass asserted a relation. A three-value instrument is the fix for the *next*
sample; re-asking this one after seeing its answers would turn a measurement into
a search.

## E-V5 · Restrict edit distance to principled variants — **run, and it becomes a rule**

**Claim under test:** edit distance ≤2 on short labels is noise generation, and
its genuine value is confined to number, diacritic, and US/UK variants.

Hold the corpus fixed. Vary the rule: raw Levenshtein ≤2 versus a variant-only
rule (number agreement, diacritic folding, a known US/UK spelling table).
*Measure* candidates generated, admitted, and the `relatedMatch` share of each.
*Decides* whether to keep the arm. *Known:* `Fees` is within two edits of `FEET`,
`NEWS`, `SEEDS`, and `BEER`; the class admits at 18.2% overall.

**Result.** The claim holds about as cleanly as a claim can:

| Variant class | Generated | Admitted | Rate | `relatedMatch` of admissions |
| --- | ---: | ---: | ---: | ---: |
| `numberVariant` | 11 | 9 | **81.8%** | 1/9 |
| `spellingVariant` | 5 | 4 | **80.0%** | 0/4 |
| `unprincipled` | 149 | 17 | **11.4%** | **12/17 (70.6%)** |

Under 10% of the arm carries 13 of its 30 admissions at an 81% rate; the other
149 admit at 11.4% and return `relatedMatch` seven times out of ten. **Ship the
variant rule** — and note it pays twice, because those same principled variants
are what make R4 admissible in E-V1.

*Classifier caveat:* orthographic, not statistical — case and diacritic folding,
an English pluralisation rule, a ten-entry US/UK rewrite table. It will not
generalise past English. `Traffic regulation`/`TRAFFIC REGULATIONS` is a
principled variant the judges nonetheless rejected, which looks like a judge
error rather than a classifier one.

**Classifier validated blind (2026-08-06).** All 165 pairs went to an independent
reviewer judging morphology with the classifier's verdict withheld: **98.8% exact
agreement, and 16/16 precision on the principled class — zero false promotions**
[95% CI 80.6–100%]. The two misses are punctuation rather than morphology —
`CYBERSECURITY`/`cyber security` and `STILL-BIRTH`/`stillbirths` — because `_fold`
normalises case and diacritics but not hyphens or whitespace. Both are already
admitted as `exactMatch` on unanimous judge verdicts, so the fix changes zero
admissions on this archive; fold punctuation when the generator restriction
ships, not before.

## E-V6 · Precision on candidates a semantic arm found

**Claim under test:** the archive's real hard negatives (157, once the sets were
partitioned — earlier drafts said 234) are usable as a
precision benchmark.

They are not, entirely — every one came from a string match, so they say nothing
about what dense retrieval proposes. Hold the judging rubric fixed. Vary the
candidate source: string-derived (archive) versus dense-only pairs that no string
arm would rank. Judge 200 of the latter.
*Measure* per-edge error rate in each population, then compound across hops.
*Decides* the traversal depth. **The archive lowers E-S1b's cost but does not
replace it** — the population it can never contain is exactly the one production
will rely on.

## E-V7 · Is admission order-dependent?

**Claim under test:** graph-minimality and redundancy checking must be a batch or
fixed-point rule, not incremental. Raised by an independent 2026-08-05 analysis
and not previously tested here.

Hold the candidate set and judge verdicts fixed. Vary only the **order** in which
candidates are considered for admission: canonical, reverse canonical, and three
seeded shuffles. Run the redundancy and graph-minimality checks incrementally in
each order.
*Measure* whether the admitted set is identical across all five orders, and name
every candidate whose disposition changes.
*Decision rule:* any difference at all is a defect — replace the incremental rule
with a fixed-point or batch evaluation and re-run until stable. In a system whose
discipline is content-addressed reproducibility, an admitted graph that depends
on iteration order cannot be sealed. Free, replay only.

**Result — no defect, and the reason matters more than the result.** Five orders,
one admitted set. Not luck: **the rule carries no cross-row state at all.** It
reads one row, inspects that row's generation class and its two verdicts, and
decides. The premise the analysis raised is about redundancy and graph-minimality
checking, and this archive's admission performed neither — which is why its 582
admitted candidates produced 582 assertions with nothing collapsed, confirmed
independently by the benchmark verifier.

So E-V7 is answered *for the rule that shipped* and stays live for any future one
that adds a minimality step. The check is now cheap to re-run: it is one call in
`replay_atlas_crosswalk_admission.py`, so any proposed rule can be tested for
order dependence the moment it exists.

## E-V8 · K10 versus K50 on a corrected cost basis

**Claim under test:** the independent analysis recommends deterministic floor +
BGE K10 + relation-specific rescue over K50, citing $1,762.95 against $8,292.56.

Both figures assume 400 output tokens per row against a median 61 observed, so
recompute the frontier under three allowances — 400 (current ceiling), 200
(compact-schema target), and the observed p95 of 185 — and against **closure**
gold rather than asserted, since asserted over-states hierarchy recall by 10–15
points and changes arm ordering.
*Measure* admitted mappings per thousand judged candidates for each retrieval
band, which is the economic unit the analysis correctly identified and this
document never computed.
*Decides* the production depth on yield rather than on a single tail observation.
*Note:* depth is not the binding constraint anyway — the lattice discards ~15% of
correct answers at any K — so run E-V1 first and treat this as a cost decision,
not a quality one.

---

# Sequencing

Wave 0 and Wave 1 are complete; results are recorded in the companion document.

| Wave | Experiments | Status | Cost |
| --- | --- | --- | ---: |
| 1 | E-S1a, E-S2, E-S5, E-S6, E-S10, E-T1–E-T4 | **done** — closure inverted the recall reading, arm ordering changed, `maxOverLabels` won, casing null | free |
| 2 | Crosswalk extraction + blind review | **done** — 86 recoverable rejections, 85 confirmed; typing is the bottleneck | free |
| 3 | **E-V1, E-V2** | **done** — the prize is 37 not 85, and the reviewer outperformed the judges it was doubted against | free |
| 4 | **E-S11** | Unblocks V-1, V-2, V-6, V-9 | free |
| 5 | **E-V4**, E-V5, **E-V7** | **done** — `relatedMatch` localised to unprincipled edit distance; variant rule drops 149 of 165 candidates; admission is order-independent and stateless | free |
| 5b | **E-V4 judged half, E-V2 framing arm** | **done** — 71.4% of `relatedMatch` survives blind review; failures are 8/10 unprincipled edit distance; framing moves ~10% of verdicts | free |
| 6a | E-V3, E-V2 cross-family pass | The two that still need judging; cross-family is now the binding limitation | ~$1 |
| 6 | E-S1b / E-V6, E-S8 | Edge precision on non-string candidates; direction accuracy | ~$4 |
| 7 | **V-1**, V-3, V-6 | Text-orthogonal signal and coverage | ~$2 |
| 8 | E-S4a, E-S4b, **E-V8** | Cross-vocabulary transfer, delta-judged; and depth on a corrected cost basis | ~$20–150 |
| 9 | V-2, V-4, V-9 | Citation, generation, lineage | ~$3 + plumbing |
| 10 | E-S12 → E-S14 | Tagging, once its gold exists | — |
| 11 | E-S15 → E-S18, V-5, V-7, V-8 | Search, geometry, anchoring, domain encoder | — |
| 12 | E-S19, E-S20, E-S21, E-S22, E-S23 | Longitudinal and hygiene | — |

**E-V1 and E-V2 went first, and both moved.** The prize is **37 mappings
(+6.4%)**, not 85 and +14.6%; the gap is 40 rows where the judges disagree about
associative versus hierarchical, which is a real question and not a rule defect.
The reviewer that was supposedly disqualified turned out to be more conservative
than both sealed judges on both control classes — the 100% baseline it failed
against was a control-class exclusion, not a judgment. Net effect: a smaller,
better-evidenced prize, and one fewer reason to distrust the blind review.

**E-V4, E-V5 and E-V7 followed, and two of them changed a rule.** `relatedMatch`
is a sink, but only for the *unprincipled* half of edit distance — 149 candidates
admitting at 11.4%, of which 70.6% come back `relatedMatch`; the 16 real
orthographic variants admit at 81% and produce almost none. That split is worth a
generator change on its own, and it also produced R4 in E-V1. Admission turned out
to be order-independent because it keeps no cross-row state, so E-V7's concern
belongs to future rules rather than to this one.

**What is left in this Part needs judging, not replay.** E-V3 (directness
asymmetry), E-V4's reviewer half (are the surviving 35 `relatedMatch` admissions
genuine?), E-V2's second and third passes, and E-V6 all require someone to look at
rows. Everything answerable from recorded bytes has now been answered.

**E-S7 and E-S23 are now partly answered.** Directness keeps 93–95% of admitted
cross-vocabulary mappings, against 80% cut intra-vocabulary — E-V3 tests whether
that asymmetry is real. Inter-annotator agreement is measured at 95–97% support
and 74–79% exact on 1,095 rows, and E-V2 has now settled the calibration half:
the remaining gap is that every row still carries one opinion, not three.

**E-S4 got cheaper and sharper.** Its precision half is free against the archive's
157 real hard negatives. Its recall half no longer needs 22,560 exhaustive pairs
— judge only what new arms find beyond the old generator, since that generator's
population provably contains no semantic-only pair. And the prediction is now
specific: exact and alias anchors are structurally dead intra-vocabulary and
admit at 91.5% cross-vocabulary, so "dense beats lexical by 20–40 points" should
shrink substantially.

# New tooling required

| Need | Extends | Effort | Status |
| --- | --- | --- | --- |
| Precision sampler (entailed / sibling / neither) | evidence analyzer | small | **built** |
| Reachability and cross-predicate transfer | graph analyzer | small | **built** |
| View/prompt variant runner | new | small | **built** |
| Closure-gold scoring mode | evidence + frontier | small | **built** |
| Class-mix-by-depth report | evidence analyzer | small | **built** |
| Crosswalk benchmark builder | new | medium | **built** |
| Independent benchmark verifier | new | medium | **built** |
| Tiered `/tmp` evidence promotion | new | small | **built** |
| Admission-lattice replay + calibration | new | small | **built** |
| Order-dependence replay harness | admission rule | small | **built** — folded into the lattice replay |
| Orthographic variant classifier | admission rule | small | **built** |
| Sealed blind-sample builder + comparer | new | medium | **built** |
| Variant-classifier blind audit + comparer | new | small | **built** |
| Wilson intervals + Fisher exact on every reported proportion | replay harness | small | **built** |
| Tagging gold builder | mirrors test-set builder | medium | needed |
| Co-assignment PMI arm | reads tagging gold, emits rank artifact | small | needed |
| Citation extractor | new | medium | needed |
| Scope-note generator | new, provider call | small | needed |
| Generate-then-verify arm | new, provider call | small | needed |
| Asymmetric encode path | dense + provider tools | medium | needed |
| Order/box embedding trainer | new | large | needed |
| Hybrid search harness | new | large | needed |

Anything that emits `uint32` pair code + `uint8` rank drops straight into the
frontier and evidence tools with no integration work. That contract is why V-1
and the citation arm are *small* rather than *large* — they are new signals, not
new pipelines.

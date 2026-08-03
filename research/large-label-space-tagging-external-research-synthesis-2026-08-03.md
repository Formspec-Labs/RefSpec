# Large label spaces: what the external research established

**Date:** 2026-08-03
**Sources:** The nine recovered blind research reports in
[`evidence/blind-external-research-recovery-2026-07-28/`](evidence/blind-external-research-recovery-2026-07-28/).
**Scope:** This report synthesizes what the external literature and the
researchers' own primary-source measurements established about tagging
documents against very large label spaces. It deliberately excludes the
recovered reports' evaluations of this project's registry and pipeline; those
judgments are out of scope and should not be cited from this document.

**Verification legend.** The original researchers tagged every number:

- **✓** — read directly in primary text (paper table, official document) or
  measured by the researcher against a live API.
- **~** — obtained only through an automated summarizer. The summarizer
  fabricated at least four results outright during this research (§14), so
  treat ~ items as leads, not evidence.

Corrected values supersede earlier drafts wherever a report issued a
correction; this synthesis carries only the corrected figures.

---

## 1. Production systems keep classification vocabularies small — deliberately

The clearest pattern in industry practice: **entity registries and
classification label spaces are different objects, and mature systems never
use one as the other.** They differ by six to seven orders of magnitude.

| System | Entity/registry scale | Classification scale | Source flag |
|---|---|---|---|
| Google Knowledge Graph | ~5 billion entities | — | ✓ (2020 blog) |
| Google Cloud NL categories V1 / V2 | — | 620 / 1,091 | ✓ |
| Google Topics API v1 / v2 | — | 349 / 469 | ✓ |
| Google Product Taxonomy | — | 5,595 | ✓ |
| IAB Content Taxonomy 3.0 | — | 672 | ✓ |
| YouTube topic IDs (post-Freebase) | millions (Freebase, retired) | ~60 curated | ~ |
| MeSH | >230,000 supplementary records | ~30,000 descriptors | ✓ |
| EuroVoc (all EU law) | — | 7,000+ concepts | ✓ |
| Pinterest Interest Taxonomy | 200B+ pins | ~11-level curated tree | ~ |

Google states the rationale on the record ✓: the Topics API taxonomy must be
"small enough that many users' browsers will be associated with each topic"
and is "restricted to a human curated taxonomy" partly so "people can learn
what is being said about them." Its training data is a manually curated
override list for 50,000 top sites ✓.

YouTube ran the borrow-a-giant-entity-vocabulary experiment and reversed it:
after Freebase's deprecation it replaced millions of exposed entity IDs with
roughly 60 curated topics ~.

When Google does retrieve over millions of entities (entity *linking*, not
topic classification), it is never zero-shot. Gillick et al. (CoNLL 2019) ✓
retrieved over 5.7M Wikipedia entities with a dual encoder trained on 112.7M
linked mentions and multiple rounds of hard-negative mining, reaching R@100 =
96.3 on TACKBP-2010 against a BM25 baseline of 68.9. The recipe is training
data plus hard negatives, not a bigger index.

Pinterest follows the same shape ~: candidate terms mined from the corpus, a
neural model proposes structure, **taxonomists manually review every predicted
parent**, and serving generates a generous candidate pool (up to 200, mean 70
per pin) ranked by a learned model.

## 2. Single-vector embedding retrieval has a proven capacity limit

Google DeepMind published a theoretical bound on exactly this architecture
(Weller et al., "On the Theoretical Limitations of Embedding-Based
Retrieval," ICLR'26) ✓:

- The number of top-k document subsets a single-vector embedding space can
  represent is bounded by embedding dimension. Best-case critical corpus
  sizes: **512 dims → ~500K items, 768 → ~1.7M, 1024 → ~4M, 3072 → ~107M** ✓.
- The authors' own caveat ✓: these are free-embedding optima; "a real
  embedding model cannot directly optimize the query and document vectors."
  Real models fail earlier.
- On their adversarial LIMIT benchmark (50K docs), Gemini Embedding at 768
  dims scored recall@100 = 7.6 while **BM25 scored 93.6** and a multi-vector
  model (GTE-ModernColBERT) 54.8 ✓.
- Relevance-pattern structure alone can collapse recall: E5-Mistral recall@100
  fell **31.5 → 3.1** when the qrel matrix went from random to dense ✓.
- A long-context LLM reranker (Gemini 2.5 Pro) solved 100% of LIMIT queries in
  one pass ✓ — capacity limits bind the retriever, not the judge.

Two implications the paper supports: label-space scale near the critical bound
is a structural risk for single-vector retrieval, and lexical or multi-vector
channels fail differently from dense ones, which is the argument for hybrids.

## 3. Measured performance at extreme label scale

### Zero-shot (no training data)

MACLR Table 2, LF-Wikipedia-500K (501,070 labels) ✓:

| Method | P@1 | R@10 | R@100 |
|---|---:|---:|---:|
| SentBERT | 0.17 | 0.30 | 1.29 |
| GloVe | 2.19 | 3.10 | 8.52 |
| SimCSE | 14.32 | 14.35 | 27.68 |
| ICT | 17.74 | 17.19 | 31.08 |
| TF-IDF | 20.30 | 20.31 | 38.16 |
| MPNet | 22.46 | 20.64 | 34.72 |
| MACLR (unlabeled-corpus pretraining) | 28.44 | 28.52 | 50.09 |

Three durable lessons:

1. **Encoder choice dominates everything else.** SentBERT vs MPNet is a 132×
   gap in P@1 on identical data ✓. No other intervention in the literature
   approaches this effect size.
2. **Lexical baselines are genuinely competitive zero-shot.** TF-IDF beats
   most neural encoders here ✓; on EURLex-4.3K (legal text) TF-IDF at P@1 =
   44.0 beats every neural retriever tested and ties the SOTA hybrid ✓
   (SemSup-XC Table 2). Removing lexical matching from SemSup-XC's hybrid
   costs 33 P@1 points on EURLex ✓.
3. **An off-the-shelf asymmetric dense retriever can be strong**: TAS-B
   reached R@10 = 36.5 on a 312K label space with zero training ✓ (ICXML),
   beating corpus-pretrained MACLR on that dataset.

### Supervised

Supervision roughly doubles achievable recall at 500K labels: R@100 rises
from ~50 (zero-shot best) to ~90 (RAE-XMC 90.24, DEXML 90.52) ✓. ELIAS on
Amazon-670K reaches R@10 = 50.3 with 490K training records ✓. Label-text dual
encoders beat pure-ID one-vs-all classifiers at this scale (86.5 vs 82.0 P@1)
✓, but generic dense retrievers (DPR, ANCE) trained the generic way score
far lower (63–65) — **XMC-specific training, not architecture, is what
matters** ✓.

ELIAS's ablation also bounds the cost of partition-based shortlisting:
learned-index retrieval beat fixed clustering by ~4 R@10 points, and brute
force scoring beat tree shortlists by a similar margin ✓. Partitioning is an
efficiency trade, not a quality tool.

### Domain-matched shared tasks (the realistic ceiling)

SemEval-2025 Task 5 (LLMs4Subjects) is the best public calibration: 204,739
GND subjects, 82K gold training records, 14 teams ✓:

- Best automatic scores: **R@10 = 0.57, F1@5 = 0.3432** (Annif — a
  traditional XMC toolkit; LLMs used only for translation and synthetic
  data) ✓.
- The Annif authors attribute the sub-0.35 F1@5 ceiling in part to
  **inconsistent gold-standard indexing**, noting consistently indexed
  datasets had exceeded 0.5 F1@5 ✓.
- LLM candidate reranking added **+0.009 F1@5** over a non-LLM ensemble at
  GermEval-2025 ✓ — a marginal gain, not a step change.
- LLM synthetic training data added ~+0.03 nDCG with diminishing returns ✓.

## 4. The architecture that works without training data: generate, then map, then rerank

Three groups independently converged on the same zero-shot pipeline: generate
free-text concepts with an LLM, map them into the vocabulary by embedding
nearest-neighbor, then rerank.

- **IReRa (Infer–Retrieve–Rank)** ✓ on ESCO (~13,900 concepts): naive
  document→label retrieval RP@10 = 36.76 → Infer–Retrieve 52.62 →
  full pipeline **65.76**, beating a retriever fine-tuned on 138K examples
  (55.95). Critical caveat ✓: the *unoptimized* program scores 30.69 — worse
  than naive retrieval. The ~50-example DSPy bootstrap does real work; the
  architecture alone is not enough.
- **DNB-AI (German National Library)** ✓: LLM ensemble generates free
  keywords → BGE-M3 nearest-neighbor into GND → aggregate → LLM rescore.
  No fine-tuning. 4th on automatic metrics, **1st in qualitative review by
  professional indexers**.
- **ICXML** ✓: generate-and-rerank wins P@1 but not R@10 against a plain
  dense retriever at 312K labels.

The routing insight generalizes: LLM-generated free text sits in the
document register; mapping it into the label space avoids asking an encoder
to bridge the register gap between long prose and short label strings
directly.

Two counterweights:

- Purely generative label decoding collapses on unseen labels (GROOV: P@1 =
  1.2 on EURLex zero-shot, 0.0 on AmazonCat) ✓. Generation must be grounded
  by mapping.
- LCSHBench cuts the other way on reference-matching metrics: free generation
  (F1 0.161 exact / 0.384 concept) beat selection over a retrieved pool
  (0.118 / 0.318) ✓. Generate-then-map wins human-judged quality; no clean,
  consistent win exists on gold-label matching. The two metric families
  disagree, and the disagreement is itself the finding.

**Constraining output count protects precision.** UNT Libraries ✓: precision
0.26 at 3.14 emitted terms per record vs 0.05 at 14.89. Mapping
hallucinated terms to the nearest valid vocabulary entry reliably buys ~9–12
recall points (0.43→0.52 zero-shot, 0.51→0.63 CoT) ✓.

## 5. Label text engineering: large effects, mixed sign

- **Descriptions can beat bare names by 2.5×** — SemSup-XC ✓: the same frozen
  sentence encoder went P@1 7.8 → 19.6 and R@10 13.3 → 22.5 on Wikipedia-1M
  when given scraped class descriptions instead of class names.
- **But descriptions are not a free win.** The same paper's tables ✓ show
  descriptions *hurting* other models badly: MACLR on AmazonCat 36.0 → 18.4;
  ZestXML 15.6 → 5.4. GPT-3-generated descriptions underperformed web-scraped
  ones (42.5 vs 44.7 on EURLex) ✓, and WordNet definitions underperformed
  both ✓. A practitioner writeup (Jina) reports +19% to +40% F1 on some
  datasets and **−10% to −31% on TREC** ~. Every use must be A/B-tested.
- **Register matters.** PromptBERT's 500 definition-derived templates topped
  out at 64.75 vs 73.44 for hand-written ones ✓ — dictionary-register text
  embeds differently from document-register text. DEPL's recipe (label name +
  top-20 document-mined discriminative keywords) targets the document
  register directly ~.
- **Wrapper boilerplate alone swings results massively.** PromptBERT ✓,
  identical content, different template, STS-B dev: `[X] [MASK].` scores
  39.34; `This sentence : "[X]" means [MASK].` scores 73.44 — a 34.10-point
  swing from the wrapper. Their fix — embed the template alone and subtract
  it — is cheap, but the authors caution it can delete meaning from very
  short strings ✓, and short labels are the worst case.
- **Instructions matter less than vendors imply for retrieval.** E5-Mistral's
  ablation ✓: a bare task-type prefix slightly beat full natural-language
  instructions on retrieval (52.7 vs 52.2); dropping instructions entirely
  cost 4.0.

## 6. Embedding geometry: which diagnostics mean something

The literature invalidates two intuitive pathology readings and validates one
cheap correction.

**Low effective dimensionality is not a defect.** IsoScore ✓ returns values
below 0.18 for *every* contextualized embedding model its authors tested;
GPT-family models do not isotropically use even one dimension ✓. Worse for
the pathology reading: isotropy is mathematically incompatible with
clustering (Mickus et al., ACL 2024) ✓, with measured correlations of
r = −0.808 to −0.978 between silhouette and IsoScore. **A well-clustered
label space should score low.** Anisotropy also fails to predict quality:
roberta-base at anisotropy 0.9554 beats bert-base at 0.4874 on STS ✓.

**Raw cosine margins are register artifacts unless the null is right.** Two
independent traps ✓:

1. Uncentered cosine similarities are dominated by the shared mean vector;
   rotating one point cloud moves average random cosine from 0.968 to 0.993
   with zero change to variance structure.
2. Cross-type similarity (document↔label) and within-type similarity
   (label↔label) live on different scales by construction — CLIP shows
   text↔text ≈ 0.75 vs image↔text ≈ 0.25 ~ with no relevance meaning. The
   only valid null for "is my best match good" is **query↔random-target**,
   same type pairing, and the informative statistic is the z-score against
   that null plus best-vs-runner-up margin.

The decisive diagnostic the literature supports: **report the rank of a
known-gold label among all labels.** Margins, isotropy, and effective
dimension are all secondary to whether the gold item ranks high.

**Hubness correction is free and usually worth points.** CSLS ✓ (short
surface-form retrieval, 200K targets, no training): +2.1 to +9.3 P@1 over
plain nearest neighbor. DBNorm ✓: +7.6 R@1 on MSCOCO/CLIP but ≈0 on
Flickr30k — cheap to test, not guaranteed.

**Dilution by irrelevant index content is real and large.** CoRECT ✓ holds
relevant items and 100 hard distractors fixed and varies only random filler:
recall@100 drops 30–46 absolute points as the pool grows from 10K to 100M
(e.g., E5 84.15 → 50.77). Caveat ✓: nDCG@10 stays far more stable because
random filler rarely cracks the top 10; **fluent, plausible off-domain labels
behave like hard distractors, the worse case.**

## 7. Big off-domain vocabularies: prune the output, not the index

The literature holds two findings in tension and resolves them cleanly:

- **Off-domain index content costs recall** (CoRECT, §6) and near-synonym
  crowding costs judged precision: in SemEval-2025's librarian review, P@5
  fell from 0.74 counting "technically correct" to 0.53 counting "actually
  correct," and the organizers name the cause — models ranked multiple
  semantically similar subjects at the top ✓. Judges pick defensible-but-wrong
  near-synonyms, and no gold-label metric that ignores the distinction can
  see it.
- **But deleting coverage creates a worse failure.** DNB-AI ✓ found that
  concepts absent from the vocabulary caused forced-choice ANN mapping to
  snap to unrelated terms — country names mapped onto arbitrary subjects —
  and a minimum-similarity threshold did not stop it. Their fix *grew* the
  mapping space from 200,035 to 309,417 by adding named entities, then
  filtered non-target concepts after mapping, and reported fewer false
  positives.

**Resolution: decouple the mapping space from the emit space.** Map into a
wide space so off-topic content lands somewhere harmless (absorbing decoys);
emit only from the curated in-domain set. This captures the dilution benefit
at emit time and the coverage benefit at map time simultaneously.

Honest limits ✓: no published XMC paper runs the direct ablation "delete the
off-domain fraction, measure recall on in-domain gold." The nearest natural
comparison (GND tib-core 79K vs all-subjects 205K) is confounded — record
sets differ too — and splits both ways (Annif got worse on the smaller
vocabulary, RUC got better) ✓. "Shrink the vocabulary" is well motivated by
adjacent evidence, not an established result.

## 8. The consistency ceiling: humans set it, not algorithms

At large vocabulary scale, gold labels themselves are unstable, and that
instability bounds every downstream metric.

- **LCSHBench** ✓ (~515K LCSH+LCGFT labels): across 465,187 works cataloged
  by Harvard, Columbia, and Princeton, **93.3% shared a concept-level heading
  but only 39.4% had identical heading sets**. A professional cataloger
  reproduces peer consensus exactly 86.9% of the time (93.0% at concept
  level). The authors diagnose the gap as disagreement about *granularity*,
  not topic.
- **Annif** ✓ attributes the SemEval F1@5 ≈ 0.35 ceiling partly to
  inconsistent gold indexing; consistently indexed datasets exceeded 0.5.
- **Concept extraction agreement**: three trained humans with shared written
  guidelines reached pairwise Jaccard 0.75–0.80 and "were not able to go
  higher"; ChatGPT–human agreement ≈ 0.5 ✓.
- **Taxonomy relevance judgments**: TnT-LLM's own authors reached only fair
  agreement (Fleiss κ = 0.379) on domain-label relevance ✓; GPT-4 agreed
  with the human consensus better than individual humans agreed with each
  other ✓.

Design consequences the sources draw: score topic-level agreement separately
from exact-string agreement or granularity disagreement will masquerade as
error; and expect any vocabulary large enough that trained professionals
cannot assign it consistently to cap system F1 regardless of method.

## 9. Source and venue metadata: soft prior yes, hard partition no

**No verified published system hard-partitions a vocabulary by source
metadata.** The closest candidates dissolve on inspection:

- **KenMeSH** ✓: its "journal mask" is the union `Mj ∪ Ma` where the journal
  set uses τ = 0.5 (a term qualifies only if it appears in more than half a
  journal's articles — a tiny near-universal set) and `Ma` is the union of
  gold labels from the 1,000 nearest training abstracts. The paper states
  the mask is guaranteed to contain all gold labels. The journal component is
  never ablated alone; there is no published number for what a journal prior
  buys by itself. The one hard mask in the literature was built with a
  recall-preserving escape hatch.
- **MATCH** ✓ — the cleanest isolation of venue metadata (soft embeddings,
  never a filter): all metadata together buys +0.15 P@1 (not significant),
  +1.0 P@3, +1.2 P@5 on PubMed/MeSH, and the authors state venues indicate
  *coarse* categories and help least on fine-grained ones.
- **NLM MTI** uses journal information to route *documents* (which journals
  to trust automation on — MTI First-Line), not to shrink the vocabulary;
  its journal-frequency signal is a soft confidence boost worth +4.44pp
  precision ✓ (recall cost unreported). The 2010 lesson: running at ~30%
  precision with long candidate lists destroyed indexer trust; rebalancing
  toward precision made the system usable.
- Library practice (Annif/Finto, DNB) partitions by *vocabulary and
  language*, never by collection or publisher ✓. No SemEval-2025 team
  partitioned the vocabulary by domain ✓.

**On the US federal corpus, the researchers measured why partitioning fails
and priors work** (their own computation, reproducible from the Federal
Register API): a frequency-weighted CFR-part prior lifted candidate recall@12
from 42.2% to 76.0% (agency prior: 71.0%), yet **90.0% of all topic
assignments land on terms shared by two or more agencies**. The label
*distribution* is source-conditioned; the label *set* is not
source-separable. A hard partition prunes the rarely used agency-exclusive
tail and keeps the genuinely ambiguous shared spine. Two supporting
measurements: true multi-department rulemaking is 1.3–1.6% once sub-agencies
collapse to parents (raw agency lists overstate it as 66.8%), and topic
concentration varies hugely by agency (top-10 topics cover ~89% of FAA's
assignments but only ~36% of USDA's), so uniform prior weights are wrong.

The supported design: estimate P(concept | fine metadata), back off to
coarser metadata, then to global; add it as a **soft score component**;
**union** prior-derived candidates with a global top-N, never intersect.
Expect the prior's value to shrink as text-side supervision grows (MATCH's
+1 point came with 898K training examples).

**Hierarchical two-stage routing is unevidenced.** The EuroVoc paper
routinely cited for it ✓ trains flat classifiers at three granularities
(F = 0.74 at 126 labels, 0.67 at 489, 0.58 at 3,563) — showing only that
coarse is easier than fine. No paper measures a domain→descriptor cascade
against a flat baseline. Learned label trees moved *away* from aggressive
partitioning (Parabel → Bonsai) because of error propagation on tail labels ✓.

**Facet decomposition (typed retrieval per concept kind) is an acknowledged
gap, not a validated technique.** The GND benchmark treats all entity types
the same, flags that "named entities are linguistically different from
subject headings," and names faceted decomposition as the obvious unexplored
improvement ✓. Mature registries do separate entities from subjects
structurally: MeSH keeps >230K supplementary concept records (mostly
entities) outside its ~30K descriptor tier ✓, and EPA runs its substance
registry separately from its terminology services ✓. Entity identity is not
a subject.

## 10. Building a vocabulary from a corpus: measured reality

### Extraction is unsolved

- TermEval 2020 best English F1: **46.7** ✓. 43% of gold terms are hapax, so
  frequency thresholds structurally cannot find most of a vocabulary ✓.
- Everything above ~50 F1 is supervised ✓ (ACTER survey: statistical methods
  14–41; supervised 55–70).
- LLM in-context ATE matches a fine-tuned RoBERTa on ACTER (60.2 vs 61.2) and
  loses clearly elsewhere ✓. **LLMs did not solve ATE.**

### Induction works at small scale and is unstable

- **TopicGPT** ✓ (32,661 US congressional bill summaries — the closest
  public analogue to regulatory prose): refined purity 0.57 vs LDA 0.52 —
  the LLM edge is thinnest on legislative text (+0.05, vs +0.10 on
  Wikipedia). Refinement (merge at cosine ≥ 0.5, drop topics generated <10
  times) cut 79 topics to 24 and cut human-judged misalignment from 70% to
  32% ✓. Instability is the headline risk: different samples and prompts
  produced 73 / 79 / 118 / 123 / 147 topics with only 0.67–0.70
  self-agreement ✓. New-topic discovery plateaued after ~600 documents;
  cost $88; generation required GPT-4 — no open model they tried could do
  it ✓.
- **TnT-LLM** ✓ (deployed in Bing Copilot): the taxonomy size was
  *prescribed* ("generate 10 intent and 25 domain categories"), not
  discovered.
- **AstroMLab 5** ✓ — the largest measured induction: 408,590 papers → ~10
  extracted concepts each → embed descriptions → K-means, k swept in log
  space (3,000 / 10,000 / 30,000), chose 10,000 → **the author team manually
  reviewed all 10,000 concepts**. The induction step is cheap; the >$50K
  cost was summarizing full papers.
- **OLLM** ✓: LLM-induced vocabularies are semantically adjacent but
  lexically disjoint from reference vocabularies — Literal F1 0.093
  (Wikipedia) / 0.040 (arXiv) against Fuzzy F1 0.915. Induction produces a
  *second* vocabulary plus a mapping problem, never a drop-in replacement.
- **Chain-of-Layer and TaxoLLaMA organize a *given* term list**; they do not
  discover concepts ✓. On genuine domain taxonomies the structuring SOTA is
  ~48–52 edge-F1, and the methods required sampling sub-taxonomies because
  they do not scale past a few hundred nodes ✓.
- **EvoTaxo's arbitration ablation** ✓ quantifies what a review gate buys:
  removing human arbitration took a taxonomy from 25 nodes to 70, *degraded*
  hierarchy validity (0.83 → 0.74), and barely improved coverage
  (unclassified 0.22 → 0.17). Don't cluster raw documents either: LLM-emitted
  normalized representations improved K-means silhouette from 0.07 to 0.45 ✓.
- **TaxonomyBuilder** ✓: augmentation *significantly reduced* coverage
  (ANOVA F = 40.81, p < 0.001, η² = 0.836); 22 of 28 best scores came at or
  above the 50th-percentile candidate filter; the weakest-filter taxonomies
  won zero judge categories. **Filtering hard beats augmenting.** Its induced
  concepts still scored 1.5–2.5/5 on distinctiveness — overlap is the
  characteristic induced-vocabulary defect.
- **Vocabulary pruning with LLMs is not a paved road.** Beyond WiKC
  (4.1M → 17K classes ~, no human validation, never verified in primary
  text), the category is empty; "vocabulary pruning" in current literature
  almost universally means tokenizer pruning ✓.

### The economics favor reviewing vocabularies, not assignments

Measured human-review throughput ✓:

| Study | Humans reviewed | Who |
|---|---|---|
| AstroMLab 5 | all 10,000 concepts (found 1 defect) | author team |
| TnT-LLM | 400 conversations | 4 of the authors |
| SemEval-2025 | 122 records over ~3 weeks | professional indexers |
| TopicGPT | 6 topic-list mappings | 3 annotators |
| TyDI/VegA | 65,529 candidates → 2,680 concepts | 2 people, 6 weeks |

**Reviewing a vocabulary is cheap and gets done exhaustively; reviewing
assignments is expensive and gets done on tiny samples.** A few-thousand-
concept vocabulary is a reviewable artifact; a half-million-concept one can
never be reviewed by anyone. TyDI's ~4% candidate-to-concept yield
(65,529 → 2,680, ~12 person-weeks) is the one honest cost accounting in the
literature, and its design is the most transferable: **borrow an established
ontology for the upper levels only; derive the leaves from the corpus.**

## 11. Governance in mature vocabularies: two tiers and a named reviewer

Every long-lived vocabulary the research examined runs the same machinery ✓:

- **MeSH**: >230K staged supplementary concept records (created daily) against
  ~30K registered descriptors (updated annually) — an 8:1 ratio, every staged
  record anchored to a descriptor. Promotion runs ~100–500/year as an
  editorial campaign. Of 6,915 descriptors added over 15 years, ~23% were
  promoted staged records and **~44% were finer splits of concepts already
  covered — a vocabulary that fits its corpus grows by splitting, not
  adding.**
- **EuroVoc**: candidates live in a dedicated scheme in VocBench with named
  reviewers, editorial notes, committee consensus, and translation gated
  behind approval. **No frequency threshold anywhere.**
- **LCSH/SACO**: proposal-driven, weekly review; the published guidance is an
  explicit cost/benefit judgment, not a numeric gate. FAST cannot mint its
  own headings — new terms route through LCSH.
- The only published *numeric* graduation gates are engineering heuristics:
  TopicGPT's merge-at-cosine ≥ 0.5 and drop-below-10-generations ✓, and one
  practitioner's "reject any category supported by a single document" ✓.

The pattern: **the graduation gate is a definition, a home in the hierarchy,
and a named human decision — usage evidence informs it but never fires it
automatically.**

## 12. Size anchors from vocabularies that work

| Vocabulary | Curated concepts | Domain scope | Flag |
|---|---:|---|---|
| Google Topics API v2 | 469 | all web content (ads) | ✓ |
| Google Cloud NL V2 | 1,091 | all text | ✓ |
| Federal Register Thesaurus | 1,044 (API) / 702 (PDF parse — unreconciled) | US rulemaking | ✓ |
| CRS Legislative Subject Terms | 1,004 | US legislation | ✓ |
| CRS Policy Areas | 32 | US legislation (one per bill) | ✓ |
| Unified Astronomy Thesaurus | 2,367 | astronomy | ~ |
| GAO Thesaurus (1998, stale) | >2,500 | government oversight | ✓ |
| Google Product Taxonomy | 5,595 | all commerce | ✓ |
| EuroVoc | 7,000+ | **all EU legislative/policy output** | ✓ |
| AstroMLab 5 (induced, fully reviewed) | 9,999 | astronomy literature | ✓ |
| NALT Core topical facet | 14,521 | agriculture | ✓ |
| NASA Thesaurus | 22,622 | aerospace/science | ✓ |
| MeSH descriptors | ~30–31K | all biomedicine | ✓ |
| LLM-era induced taxonomies (all papers) | 10–150 | single corpora | ✓ |

EuroVoc is the strongest single anchor for regulatory-policy text: the entire
legislative output of a 27-country union, indexed at scale in 24 languages,
with ~7,000 preferred concepts. Purpose-built subject vocabularies for entire
domains cluster in the **low thousands to low tens of thousands**; induced
per-corpus taxonomies cluster in the **tens to low hundreds**; entity
registries (FAST's 1.8M authority records, TSCA's >86K chemicals, MeSH's 230K
SCRs) are a different kind of object and no production system uses one as a
classification target.

## 13. The convergent design pattern

Stated as a synthesis of §§1–12, not as any single paper's claim. Where the
evidence converges, it converges on this shape:

1. **Two spaces, decoupled.** A wide mapping space (including entity
   registries and decoy content) so nothing is forced onto a wrong neighbor;
   a narrow, curated, reviewable emit space in the low thousands.
2. **Typed facets.** Subjects, entities (chemicals, organizations, places),
   genre/action, jurisdiction/structure, and industry are separate outputs
   with separate registries — never competitors in one similarity ranking.
   (Well motivated; not yet empirically validated anywhere — §9.)
3. **Hybrid first-stage retrieval.** Lexical (BM25/TF-IDF over labels,
   synonyms, and variants) plus dense, unioned; hubness correction applied;
   candidate pools generous (the R@10→R@200 gap at 500K labels is ~2×).
4. **Soft metadata priors**, frequency-weighted, backed off
   fine→coarse→global, unioned with global retrieval — never a filter.
5. **Generate-then-map for zero-shot assignment**, with a small optimization
   set (~50 labeled examples), constrained output counts, calibrated
   acceptance, and **abstention** — nearest neighbor is not evidence of
   correctness.
6. **A reranker above the retriever**, since judges recover ranking but not
   recall; shortlist size is the binding constraint no judge can fix.
7. **Two-tier vocabulary governance**: an unbounded staging tier anchored to
   the curated core; promotion by human review on usage evidence; the
   vocabulary frozen, versioned, and reviewed as a whole once — the review
   effort spent on the vocabulary, not on per-document assignments.
8. **Evaluation that separates concept agreement from string agreement**, and
   scores abstention and unsupported-label rates — otherwise granularity
   disagreement and near-synonym crowding are invisible.

## 14. What nobody has measured (verified gaps)

Each of these was searched for and not found; treat claims to the contrary
with suspicion ✓:

1. An ablation deleting the off-domain fraction of a label space and
   measuring recall on remaining in-domain gold.
2. Any benchmark of **long-document-as-query against short-label-as-corpus**
   — this orientation inverts the standard asymmetric convention and is
   unmeasured.
3. A controlled before/after replacing a borrowed vocabulary with a
   corpus-derived one on the same corpus (TaxonomyBuilder should have run it
   and explicitly did not).
4. A hierarchical domain→descriptor cascade measured against a flat baseline
   (the EuroVoc paper cited for this shows something else).
5. An explicit A/B of hard metadata filtering vs soft metadata reranking.
6. An isolated ablation of a journal/venue prior alone (KenMeSH conflates it
   with a 1000-NN mask); any independent reproduction of KenMeSH.
7. Any facet-separated retrieval experiment (acknowledged as a gap by the
   GND benchmark authors).
8. Embedding-dimension guidance conditioned on input length.
9. Hubness-reduction work targeting text (not cross-modal) dense retrieval,
   2023–2026.
10. A documented production migration from a governed controlled vocabulary
    to LLM-generated tags with published before/after quality, cost, and
    governance results.
11. Published LLM taxonomy/vocabulary induction on US federal regulatory
    corpora.

## 15. Reliability notes — read before citing

The research process itself produced a finding about automated research:
**the summarizing fetch layer fabricated results repeatedly.** Caught cases:
a fully invented TopicGPT results table; an invented NN/ISF/CSLS breakdown
attributed to Conneau et al.; fabricated TaxoGen/HiExpan figures; a MACLR
summary that silently dropped MPNet and would have inverted the central
recommendation; a PECOS table with P@5 > P@1; an RAE-XMC fetch with
R@100 < R@10. Every load-bearing number in this synthesis carries the
original ✓/~ flag for that reason.

Never verified — do not cite from this document or the underlying reports:
WiKC's 4.1M→17K pruning figure; ViXML/"LLMs Meet XMC" precision numbers;
PECOS benchmark tables; BLINK's R@64 = 82.06; DEPL's PSP figures;
Matryoshka-by-dimension tables; LCSHBench's recall@k table and its
"41% ceiling" (internally irreconcilable); the GND-204K benchmark numbers;
TartuNLP's "reranking nearly doubles recall"; MTI's exact precision
trajectory; C-value/NC-value original precision; KeyBERT/YAKE/RAKE
benchmarks; TaxoAdapt's baselines; AstroConcepts' F1 = 0.377; BLISS's
0.75-vs-0.25 offsets.

Coverage limits: every research thread exhausted its 200-call search budget
partway through; work postdating November 2025 in XMC, non-arXiv GLAM
venues, text-retrieval hubness, and several federal thesauri (Transportation
Research Thesaurus, ERIC, DTIC, NTIS, DOE, NIOSH, UNBIS) are under-covered
or uninvestigated.

## 16. Primary sources by theme

- **Industry practice**: Google Cloud NL categories; Topics API taxonomy
  (patcg-individual-drafts/topics); Google Product Taxonomy; Gillick et al.
  (aclanthology.org/K19-1049); Pinterest engineering blog (Interest
  Taxonomy, Pin2Interest).
- **Embedding limits**: arxiv.org/abs/2508.21038 (DeepMind LIMIT);
  arxiv.org/abs/2510.19340 (CoRECT).
- **XMC benchmarks**: arxiv.org/abs/2112.08652 (MACLR);
  arxiv.org/abs/2301.11309 (SemSup-XC); arxiv.org/abs/2401.12178 (IReRa);
  arxiv.org/abs/2311.09649 (ICXML); arxiv.org/abs/2210.08410 (ELIAS);
  arxiv.org/abs/2502.10615 (RAE-XMC); arxiv.org/abs/2010.05878 (PECOS).
- **Subject-indexing shared tasks**: arxiv.org/abs/2504.07199 (LLMs4Subjects
  overview); arxiv.org/abs/2504.19675 (Annif); arxiv.org/abs/2504.21589
  (DNB-AI); arxiv.org/abs/2508.15877 (Annif GermEval);
  arxiv.org/abs/2606.04382 (LCSHBench).
- **Geometry**: arxiv.org/abs/2108.07344 (IsoScore);
  aclanthology.org/2024.acl-short.7 (isotropy vs clustering);
  arxiv.org/abs/2201.04337 (PromptBERT); arxiv.org/abs/1710.04087 (CSLS);
  arxiv.org/abs/2310.11612 (DBNorm); arxiv.org/abs/2401.00368 (E5-Mistral).
- **Metadata priors**: aclanthology.org/2022.acl-long.210 (KenMeSH);
  arxiv.org/abs/2102.07349 (MATCH); pmc.ncbi.nlm.nih.gov/articles/PMC5324252
  (MTI); the CoopIS 2019 EuroVoc-hierarchy paper; arxiv.org/abs/1904.08249
  (Bonsai).
- **Vocabulary construction**: aclanthology.org/2020.computerm-1.12
  (TermEval); arxiv.org/abs/2301.06767 (ATE survey); arxiv.org/abs/2010.00860
  (TyDI); aclanthology.org/2024.naacl-long.164 (TopicGPT);
  arxiv.org/abs/2403.12173 (TnT-LLM); arxiv.org/abs/2511.12353 (AstroMLab 5);
  arxiv.org/abs/2410.23584 (OLLM); arxiv.org/abs/2603.19711 (EvoTaxo);
  arxiv.org/abs/2605.21029 (TaxonomyBuilder); arxiv.org/abs/2309.00642
  (annotator agreement).
- **Governance**: nlm.nih.gov/mesh/intro_record_types.html;
  arxiv.org/abs/2101.08293 (MeSH provenance); aclanthology.org/2025.ldk-1.34
  (EuroVoc management); loc.gov/aba/pcc/saco (SACO).

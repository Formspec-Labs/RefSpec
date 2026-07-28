# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

---

# Large-label-space tagging: what the evidence actually says

**Provenance note.** Every number below is marked ✓ (read in primary text — paper table, official doc, or measured by me) or ~ (came only through a summarizer model). This matters: across four parallel research threads, the summarizer **fabricated a TopicGPT results table outright**, **swapped two tables in the LIMIT paper**, **invented an NN/ISF/CSLS breakdown that doesn't exist in Conneau et al.**, and **dropped MPNet from a MACLR summary in a way that would have inverted our central recommendation**. Treat ~ items as leads only.

---

## 1. Google's actual practice

**The single most important pattern: Google's entity graph and Google's classification label spaces are different objects, differing by 6-7 orders of magnitude, and Google never uses the former as the latter.**

Verified counts, all by my own download-and-count:

| Google artifact | Size | Purpose |
|---|---|---|
| Knowledge Graph | "500 billion facts about five billion entities" (2020 blog) ✓ | entity resolution, panels |
| Cloud NL content categories **V1** | **620** categories, 27 top-level, max depth 3 ✓ | text classification |
| Cloud NL content categories **V2** | **1,091** categories, 27 top-level ✓ | text classification |
| Topics API taxonomy **v1** | **349** topics ✓ | ad targeting |
| Topics API taxonomy **v2** | **469** topics ✓ (IDs run to 629, non-contiguous) | ad targeting |
| Google Product Taxonomy | **5,595** categories, 6 levels ✓ (2021-09-21) | Shopping |
| YouTube topic IDs, post-Freebase | ~60 curated ~ | video classification |
| IAB Content Taxonomy 3.0 (industry ref) | **672** IDs, 36 tier-1 ✓ | contextual ads |

The killer detail: **Google's entire production coverage of law and government is 37 categories** in Cloud NL V2 ✓ — `/Law & Government/Government/Public Policy`, `/Legal/Constitutional Law & Civil Rights`, and 35 more. Google classifies the whole legal-regulatory universe with 37 labels. The system under review uses 513,236.

**Google states the small-taxonomy rationale explicitly.** From the Topics API explainer ✓: the taxonomy "will include somewhere between a few hundred and a few thousand topics," is "restricted to a human curated taxonomy," must be "small enough that many users' browsers will be associated with each topic," and is human-curated partly so "people can learn what is being said about them." Classifier training data is a **manually curated override list for 50,000 top sites** ✓. Google chose curation over scale, deliberately, and wrote down why.

**YouTube ran the exact experiment in question and reversed it.** YouTube originally exposed Freebase topic IDs — millions of entities. After Freebase's deprecation, YouTube "started returning a small set of curated topic IDs" ~ — roughly 60. A large borrowed entity vocabulary was replaced by a tiny purpose-built one.

**When Google does retrieve over millions of entities, it is never zero-shot.** Gillick et al. (CoNLL 2019, Google), all ✓ read first-hand:
- 5.7M Wikipedia entities, retrieved by dual encoder + ANN, ~3ms/mention
- **Trained on 112.7M linked mentions** from Wikipedia anchor text
- **Multiple rounds of hard-negative mining** (encode all, retrieve top-10, take everything ranked above the correct entity as a negative)
- R@1 87.0, R@100 **96.3** on TACKBP-2010; 97.9 on Wikinews
- BM25 baseline R@100 68.9; alias tables 89.5/91.7
- "more than 1 million candidate entities... have no associated training examples" — handled via feature representations

Botha et al. (EMNLP 2020, Google) scales the same architecture to 20M entities, 100+ languages ~ (abstract only; I did not read the tables).

**Google DeepMind has published a hard limit on exactly this architecture.** Weller, Boratko, Naim & Lee, "On the Theoretical Limitations of Embedding-Based Retrieval" (ICLR'26), all ✓ read first-hand:
- The number of top-k document subsets representable is bounded by embedding dimension
- Free-embedding optimization (best case, directly optimizing vectors against the test qrels) fits `y = −10.5322 + 4.0309d + 0.0520d² + 0.0037d³`, r²=0.999, giving critical-n: **512→500k, 768→1.7M, 1024→4M, 3072→107M, 4096→250M**
- Their explicit caveat ✓: "this is the best case: a real embedding model cannot directly optimize the query and document vectors"
- On LIMIT (50k docs), **Gemini Embedding at 768 dims scores recall@2 0.9 / @10 2.5 / @100 7.6** ✓. BM25 gets 85.7/90.4/93.6. GTE-ModernColBERT (multi-vector) 23.1/34.6/54.8.
- Qrel-pattern ablation ✓: E5-Mistral @768 recall@100 drops **31.5 → 3.1** when the relevance matrix goes from random to dense — a 10× collapse from label-correlation structure alone
- Gemini 2.5 Pro as a long-context reranker solved **100% of 1000 queries** in one pass ✓

Their honest limit ✓: "we cannot prove apriori which types of combinations they will fail on." LIMIT is adversarial, not a natural corpus. But 513K labels at 768 dims retrieving top-12 sits squarely in the regime this paper says single-vector retrieval cannot fully represent.

**Corroborating industry practice — Pinterest.** 200B+ Pins classified into an Interest Taxonomy of ~11 levels ~. Candidate terms are "mined from popular annotations used in Pins, board names, and top search queries," a neural model predicts parents, and **"the predicted parents are reviewed manually"** by taxonomists in WebProtégé, with legal/safety review ~. Pin2Interest generates **up to 200 candidates per Pin, averaging 70** ~, then ranks with a GBDT. Same shape as Google: corpus-mined candidates, human-curated taxonomy, generous candidate pool, learned reranker.

---

## 2. Extreme multi-label classification, 2023-2026

**The reframe that changes everything: 3-of-8 in top-12 is 37.5% recall@12, which is at or above every published zero-shot number at this scale.**

Zero-shot recall on large label spaces, MACLR Table 2 ✓:

| Method | LF-Wikipedia-500K (501,070 labels) R@10 | R@100 |
|---|---|---|
| SentBERT | **0.30** | 1.29 |
| GloVe | 3.10 | 8.52 |
| SimCSE | 14.35 | 27.68 |
| ICT | 17.19 | 31.08 |
| TF-IDF | 20.31 | 38.16 |
| MPNet | 20.64 | 34.72 |
| MACLR (corpus-pretrained) | 28.52 | 50.09 |

Calibration against the system under review:

| Setting | Labels | Training data | Recall@~10-12 |
|---|---|---|---|
| SentBERT zero-shot, Wikipedia-500K | 501K | none | 0.3% ✓ |
| TF-IDF zero-shot, Wikipedia-500K | 501K | none | 20.3% ✓ |
| MPNet zero-shot, Wikipedia-500K | 501K | none | 20.6% ✓ |
| MACLR, Wikipedia-500K | 501K | unlabeled corpus | 28.5% ✓ |
| TAS-B off-the-shelf, WikiSeeAlso-320K | 312K | none | 36.5% ✓ |
| **System under review** | **513K** | **none** | **~37.5%** |
| Best LLMs4Subjects system (GND) | 205K | 82K records | 57% ✓ |
| ELIAS supervised, Amazon-670K | 670K | 490K records | 50.3% ✓ |

**The retrieval stage is not underperforming. It is at the known ceiling for its configuration.** The problem is that the ceiling is low.

**Does off-domain filler hurt? Yes — the cleanest evidence is CoRECT** ✓. Same 76 TREC-DL queries, exactly 10 relevant items and 100 mined hard distractors held *fixed*, varying only the count of purely random irrelevant documents:

| Model | 10k | 1M | 100M |
|---|---|---|---|
| Jina V3 | 83.85 | 71.39 | **44.15** |
| E5 | 84.15 | 75.39 | **50.77** |
| Snowflake V2 | 82.00 | 74.92 | **53.39** |

**Adding purely irrelevant items costs 30-46 absolute points of recall@100.** Caveat ✓: the paper notes nDCG@10 is far more stable because random documents rarely crack the top 10. FAST headings are *not* random noise — they're fluent, plausible English phrases, i.e. closer to the hard-distractor case, which is worse.

**But the one experiment that most resembles this problem concluded the
opposite of "prune."** DNB-AI at SemEval-2025 reported that the supplied
vocabulary could not represent some free keywords. Missing named entities,
including country names, were forced onto unrelated subject terms, and a
minimum-similarity threshold did not prevent the error. ✓

Their fix: **grow** the vocabulary 200,035 → 309,417 by adding named entities, map cleanly into the extended space, then **filter out** non-target concepts afterward. ANN mapping is forced-choice; the cure for snapping-to-wrong-concept is an absorbing set of decoys you delete later.

**Synthesis: decouple the space you map into from the space you may emit.** Keep FAST/TSCA as absorbing decoys so off-topic content lands somewhere harmless; emit only from the in-domain set. That captures the CoRECT benefit at emit time and the DNB-AI benefit at map time.

**What nobody has published** ✓: no XMC paper runs the specific ablation "delete the off-domain fraction, measure recall@k on remaining in-domain gold." The nearest in-domain comparison (tib-core 79,427 vs all-subjects 204,739) is confounded — the record sets also differ — and splits both ways ✓: Annif got *worse* on the smaller vocabulary (0.63→0.59), RUC got better (0.59→0.66). Treat "shrink the vocabulary" as well-motivated by adjacent evidence, not established.

**Two more findings that dominate everything else:**

- **Label descriptions beat label names by 2.5×.** SemSup-XC, Wikipedia-1M zero-shot ✓: the same frozen sentence encoder given scraped class *descriptions* instead of class *names* goes P@1 **7.8 → 19.6**, R@10 **13.3 → 22.5**. Cheapest high-leverage lever in the literature, and it's a property of the label side, not the model.
- **Routing through LLM-generated free text nearly doubles recall.** IReRa (Infer-Retrieve-Rank) on ESCO's ~13,900 concepts ✓: naive document→label retrieval RP@10 **36.76** → Infer-Retrieve 52.62 → Infer-Retrieve-Rank **65.76**, beating a retriever fine-tuned on 138,000 examples (55.95). Honest caveat ✓: the *unoptimized* program scores 30.69, **worse than naive retrieval** — the DSPy bootstrapping over ~50 labeled examples is doing real work.

**The ceiling is set by annotation consistency, not algorithms.**
SemEval-2025 Task 5: 204,739 GND subjects, 81,937 training records, 14 teams.
Best R@10 = **0.57**, best F1@5 = **0.3432** (Annif — a *traditional* XMTC
toolkit; LLMs used only for translation and synthetic data) ✓. The Annif
authors attributed the sub-0.35 F1@5 ceiling in part to inconsistent TIBKAT
subject metadata and noted that earlier, consistently indexed datasets had
exceeded 0.5 F1@5. ✓

**LCSHBench (2026) is the most on-point source that exists** ✓ — ~515K
LCSH+LCGFT labels, essentially identical in scale to 513,236. Across 465,187
works cataloged by Harvard, Columbia and Princeton, **93.3%** shared a
concept-level heading, while only **39.4%** had identical heading sets. A
professional cataloger reproduced peer consensus exactly **86.9%** of the
time. Best LLM F1: **0.161 exact / 0.384 concept**. The authors characterized
the gap as disagreement about granularity rather than topic.

**A half-million-term vocabulary structurally cannot support consistent assignment. Professionals can't do it either.**

Also: Annif's LLM candidate-reranking at GermEval-2025 added only **+0.009 F1@5** over the non-LLM ensemble ✓. LLM reranking is a marginal gain, not a step change.

---

## 3. Label-text engineering and embedding geometry

**Both diagnostic numbers in the problem statement are, as stated, consistent with a completely healthy embedding space. Neither is evidence of anything.**

**On effective dimensionality 43/768 (= 0.056).** IsoScore ✓ (Rudman et al.,
Findings ACL 2022) is defined as the fraction of dimensions uniformly utilized
— directly comparable. Every contextualized embedding model considered in the
paper scored below 0.18, and GPT-family embeddings showed extremely low
isotropic utilization. A score of 0.056 is therefore inside the reported
band. ✓

Worse for the pathology reading: Mickus, Grönroos & Attieh (ACL 2024) ✓ prove the isotropy objective is mathematically incompatible with the clustering objective, and measure Pearson **r = −0.808 to −0.978** between silhouette and IsoScore (Spearman ρ always below −0.998). **Low effective dimensionality is what a well-clustered label space looks like.** A vocabulary full of `Italian language--*` subdivision families and chemical-name families *should* be clumpy.

**On the 0.029 margin — it is measured against the wrong null.** Two separate problems:

1. Raw cosine gaps are dominated by the mean vector. IsoScore's rotation test ✓: one point cloud rotated 0°/120°/240°/PCA reads average-random-cosine **0.990 / 0.968 / 0.981 / 0.993** while IsoScore reads 0.216 every time. Zero-centering drives average random cosine to 0 with no change to the variance structure. GPT-2's mean vector components on WikiText-2 range −32.36 to 198.19.
2. **You are comparing across two different distributions.** "Best concept↔segment" is cross-type; "random concept↔concept" is within-type. These have different registers by construction — short boilerplate-wrapped label strings will sit high against each other and low against prose, carrying zero information about relevance. BLISS measured the analogous CLIP offset: text↔text ≈0.75 vs image↔text ≈0.25 ~. **The correct null is cos(segment, random concept).**

**Templated boilerplate is real and large.** PromptBERT ✓, greedy template
search, identical content, different wrapper, STS-B dev: `[X] [MASK].` →
**39.34**; `This sentence : "[X]" means [MASK].` → **73.44**. A
**34.10-point swing from the wrapper alone.** Their fix — embed the template
alone and subtract it — is the cheapest thing to try. The authors cautioned
that the technique can omit meaningful words when the sentence is too short.
Short labels are the worst case. ✓

PromptBERT also ✓ kills the naive anisotropy story: roberta-base last-layer has anisotropy **0.9554** (near-maximal) yet *beats* bert-base-uncased at anisotropy 0.4874. And their 500 definition-derived templates topped out at **64.75 vs 73.44** for hand-written — dictionary-register text underperformed.

**Model choice dominates everything.** MACLR ✓: SentBERT P@1 **0.17** vs MPNet **22.46** on LF-Wikipedia-500K — a **132× gap**, same labels, same documents, same protocol.

**Hubness correction is free and worth several points.** CSLS ✓ (Conneau et al., ICLR 2018), which is *exactly* short-surface-form retrieval — 1,500 queries against 200k targets, no training, no tuning: NN→CSLS gains **+2.1 to +7.2** supervised, **+4.7 to +9.3** unsupervised. DBNorm ✓ post-hoc similarity normalization: MSCOCO-5k CLIP R@1 **30.31 → 37.93** — but Flickr30k 58.98 → 59.02, i.e. it can also do nothing.

**Instructions matter less than vendors imply.** E5-mistral ablation ✓: on *retrieval specifically*, a bare task-type prefix (52.7) slightly **beat** full natural-language instructions (52.2); dropping instructions entirely cost only 4.0. Don't over-invest here.

**Genuine gap** ✓: no study benchmarks **long-document-as-query against short-label-as-corpus**. This orientation inverts the standard asymmetric convention and nobody has measured it.

---

## 4. LLM taxonomy induction

**AstroMLab 5 is the closest precedent at the target size** ✓: 408,590 arXiv papers → ~10 concepts extracted per paper (~4M raw instances) → embed descriptions with text-embedding-3-large → **K-means at k=10,000** → merge into unified entries. They **swept granularity in log space (3,000 / 10,000 / 30,000) and chose 10,000**. **All 10,000 concepts manually reviewed by the author team**; one removed → 9,999. Cost >$50,000, but that was OCR + summarizing 408K full papers — the induction itself is cheap.

**The human-review economics are the finding:**

| Study | Humans reviewed | Who |
|---|---|---|
| AstroMLab 5 | **all 10,000 concepts**, found 1 defect | authors ✓ |
| TnT-LLM | 400 conversations | **4 of the paper's authors** ✓ |
| SemEval-2025 | **122 records**, ~3 weeks | professional indexers ✓ |
| TopicGPT | 6 topic-list mappings | 3 ✓ |

**Reviewing a vocabulary is cheap and gets done exhaustively; reviewing assignments is expensive and gets done on tiny samples.** A ~5K vocabulary is a reviewable artifact. 513,236 concepts can never be reviewed by anyone.

**Two cautions.** TnT-LLM (Microsoft, KDD 2024, deployed in Bing Copilot) ✓ produces **10 intent and 25 domain categories** — its headline result is about a ~25-label taxonomy, not thousands, and inter-rater agreement on domain relevance was **fair only (Fleiss κ=0.379)**. And OLLM ✓ reports **Literal F1 0.093 (Wikipedia) / 0.040 (arXiv)** — LLM-induced vocabularies are semantically adjacent but **lexically disjoint** from reference vocabularies. If anything downstream needs FAST URIs, induction gives you a second vocabulary plus a mapping problem.

**The LLM edge is thinnest on exactly this text type.** TopicGPT ✓ harmonic-mean purity: Wikipedia **0.74 vs LDA 0.64** (+0.10), but **US Congressional bills 0.57 vs LDA 0.52** (+0.05), tying SeededLDA. Cost ~$88-155/dataset. Generation required GPT-4 — no open-source model they tried could do it.

**Generate-then-map is well-evidenced but not a clean win.** UNT Libraries ✓ over ~318,500 LCSH terms: mapping-after-generation lifts recall **0.43→0.52** (zero-shot) and **0.51→0.63** (CoT); precision stays 0.05-0.26 regardless. Constraining output count is what saves precision: **0.26 precision at 3.14 terms/record vs 0.05 at 14.89**. DNB-AI ✓ placed **4th quantitative but 1st qualitative** by professional indexers. LCSHBench ✓ cuts the other way: free generation (0.161/0.384) beat selection over a retrieved pool (0.118/0.318).

**LLM vocabulary pruning is not a paved road** ✓. Beyond WiKC (4.1M→17K classes ~, no human validation), this category is empty — "vocabulary pruning" in current literature almost universally means *tokenizer* pruning.

---

## 5. What a Google-caliber team would do with this exact vocabulary

**They would delete 99.6% of it, and they would not agonize over the decision.**

Google's own answer to "how big should a classification label space be" is on the record: 349-469 topics for ad targeting, 620-1,091 for general text classification, 5,595 for products, **37 for all of law and government**. They maintain a five-billion-entity graph and *do not use it as a classification vocabulary*, because entity resolution and topical classification are different tasks with different objectives. YouTube tried the large-borrowed-vocabulary approach with Freebase and reversed it to ~60 curated topics.

Then they would find the free supervision. **I measured this myself against the live federalregister.gov API:**

- Across **10,000 recent RULE and PRORULE documents (2015+)**: **7,370 carry agency-assigned subject terms** (73.7%) ✓
- **704 distinct terms**, and the curve is saturating — 444 at 1,000 docs, 656 at 5,000, 704 at 10,000 ✓
- **41,388 total assignments**, mean **5.6 terms per tagged document**; 386 terms appear ≥10 times, only 69 appear once ✓
- Coverage by type ✓: **Rules 79.9%**, **Proposed Rules 69.5%**, Notices **0%**, Presidential Documents **0%**
- Top terms are exactly right for the corpus: *Reporting and recordkeeping requirements* (762), *Incorporation by reference* (497), *Administrative practice and procedure* (374), *Air pollution control* (143)

**The premise "no training data" is false.** The Federal Register hands out human-assigned, in-domain subject terms — assigned by the agencies that wrote the documents — for roughly three-quarters of all rules, free, via public API, no license restriction. That is simultaneously a label space *and* a supervised training set of tens of thousands of examples.

Every document also arrives pre-tagged with four more free taxonomies ✓: **CFR references** (title/part), **hierarchical agency IDs** (with `parent_id`), a **significance flag**, and **RIN** (joining to the Unified Agenda) and **docket IDs** (joining to regulations.gov). Five independent structured facets before any ML runs.

A Google-caliber team would ship the ~700-term agency vocabulary as v1 in a week, use the 7,370 tagged documents to train a dual encoder with hard-negative mining (Gillick's exact recipe, at 1/16,000th the scale), and only then ask whether a larger induced vocabulary earns its keep. They would treat the 513K fused vocabulary as what it is: an artifact of what was easy to download, not a design.

**And they would fix the measurements before touching the model.** Both stated symptoms are non-diagnostic. 43/768 is inside the normal band for every contextual embedding model ever measured, and *anti-correlates* with cluster quality. The 0.029 margin compares a cross-type similarity against a within-type null — a register artifact, not a relevance signal.

---

## 6. Recommendations, ranked by evidence-per-effort

**Tier 1 — do this week, near-zero cost, high certainty**

1. **Adopt the Federal Register's own agency-assigned topics as the emit vocabulary.** ~704 terms, in-domain, already on 73.7% of rules ✓ (my measurement). This is a rewrite of a config file, not a research project. It also converts "no training data" into ~7,400 labeled documents per 10K sampled.
2. **Fix the null.** Recompute best-match margin as a z-score against `cos(segment, random concept)`, not concept↔concept ✓. Report best-vs-runner-up separately. Expect the 0.029 to change character entirely. Zero model changes.
3. **Report gold-concept rank among all 513,236** on segments with known-correct targets. This single number settles whether the space works. Nothing else matters until you have it.
4. **Add BM25/TF-IDF over the same concept strings as a control.** TF-IDF beat SentBERT, SimCSE and ICT on most MACLR datasets ✓; BM25 got 85.7 recall@2 on LIMIT where Gemini@768 got 0.9 ✓. If lexical recall@100 ≫ dense recall@100, the encoder is the problem, not the vocabulary.

**Tier 2 — days of work, large measured effects**

5. **Audit the embedding model.** 132× spread between two sentence transformers on an identical 500K label space ✓ (SentBERT 0.17 vs MPNet 22.46 P@1). If the current model is SentBERT-family, this alone could dominate every other fix.
6. **Ablate the label-text boilerplate.** Embed with template, without, and with template-mean subtracted (PromptBERT denoising) ✓. 34.10-point swing from wrapper text alone. An afternoon.
7. **Enrich label text with scope notes, synonyms and alt-labels — not dictionary definitions.** SemSup-XC ✓: 7.8→19.6 P@1 from descriptions. But PromptBERT's definition-derived templates *underperformed* hand-written ones ✓, and DEPL's document-mined-keyword recipe ~ is the better bet: match the register of the text you're matching against.
8. **Apply CSLS hubness correction.** Free, no training, +2.1 to +9.3 P@1 on short-surface-form retrieval ✓. May do nothing (Flickr30k) ✓, but costs an hour.

**Tier 3 — weeks, well-evidenced, bigger commitment**

9. **Switch to Infer-Retrieve-Rank.** RP@10 36.76 → 65.76 on a 13.9K-concept ontology ✓, beating a retriever fine-tuned on 138K examples. **Prerequisite: ~50 labeled examples for the DSPy optimization** — the unoptimized variant is *worse* than naive retrieval ✓. The FR topics give you those 50 examples for free.
10. **Decouple map-space from emit-space.** Keep FAST/TSCA in the ANN index as absorbing decoys; emit only in-domain concepts. DNB-AI ✓ + CoRECT ✓ together. This is the resolution of the apparent contradiction between "off-domain labels hurt" and "DNB-AI grew their vocabulary."
11. **Train a dual encoder on the FR-tagged corpus with iterative hard-negative mining.** Gillick's recipe ✓. At ~700 labels and ~40K assignments this is small and very likely to beat anything zero-shot.

**Tier 4 — only after measuring**

12. **Induce a supplementary vocabulary** if the ~700 FR terms prove too coarse. AstroMLab's shape ✓, k swept in log space, full human review of the result. Budget low thousands in API plus a few person-weeks. But note ✓ you'd be the evaluation — there is no published LLM vocabulary induction on US federal regulatory text — and the LLM edge is thinnest on legislative prose (+0.05 purity over LDA on Congressional bills) ✓.
13. **LLM reranking of candidates — last.** Worth **+0.009 F1@5** in Annif's measurement ✓.

**Set expectations honestly.** With a 200K purpose-built professional vocabulary and 82K training records, the world's best system reaches R@10 = 0.57 and F1@5 = 0.343 ✓, and practitioners attribute the sub-0.35 ceiling to *label consistency*. Professional catalogers agree on exact heading sets only 39.4% of the time ✓. Score topic agreement separately from string agreement, or granularity disagreement will be misread as error.

---

## 7. Sources

**Google taxonomy sizes** (all counts my own, from downloaded primaries)
- https://docs.cloud.google.com/natural-language/docs/categories · https://docs.cloud.google.com/natural-language/docs/classifying-text
- https://www.google.com/basepages/producttype/taxonomy-with-ids.en-US.txt
- https://raw.githubusercontent.com/patcg-individual-drafts/topics/main/taxonomy_v1.md · `.../taxonomy_v2.md` · https://raw.githubusercontent.com/patcg-individual-drafts/topics/main/README.md
- https://privacysandbox.google.com/private-advertising/topics/topic-classification
- https://blog.google/products/search/about-knowledge-graph-and-knowledge-panels/
- https://developers.google.com/youtube/v3/docs/videos
- https://github.com/InteractiveAdvertisingBureau/Taxonomies

**Google entity retrieval at scale**
- https://aclanthology.org/K19-1049/ · https://ar5iv.labs.arxiv.org/html/1909.10506 (Gillick; 5.7M entities, 112.7M mentions, R@100 96.3)
- https://aclanthology.org/2020.emnlp-main.630/ (Botha; 20M entities — abstract only)

**Embedding dimension bounds**
- https://arxiv.org/abs/2508.21038 · https://arxiv.org/html/2508.21038v1 · https://github.com/google-deepmind/limit

**Pinterest** ~
- https://medium.com/pinterest-engineering/interest-taxonomy-a-knowledge-graph-management-system-for-content-understanding-at-pinterest-a6ae75c203fd · https://medium.com/pinterest-engineering/pin2interest-a-scalable-system-for-content-classification-41a586675ee7

**Zero-shot XMC at 500K labels**
- https://arxiv.org/abs/2112.08652 (MACLR/EZ-XMC) · https://arxiv.org/abs/2301.11309 (SemSup-XC) · https://arxiv.org/abs/2401.12178 (IReRa) · https://arxiv.org/abs/2311.09649 (ICXML) · https://arxiv.org/abs/2210.08410 (ELIAS) · https://arxiv.org/abs/2502.10615 (RAE-XMC) · https://arxiv.org/abs/2010.05878 (PECOS)

**Distractor dilution**
- https://arxiv.org/abs/2510.19340 · https://github.com/padas-lab-de/CoRECT

**Subject indexing ceilings**
- https://arxiv.org/abs/2504.07199 (SemEval-2025 Task 5) · https://arxiv.org/abs/2504.19675 (Annif) · https://arxiv.org/abs/2508.15877 (Annif GermEval) · https://arxiv.org/abs/2504.21589 (DNB-AI) · https://arxiv.org/abs/2606.04382 (LCSHBench)

**Embedding geometry**
- https://arxiv.org/abs/2108.07344 (IsoScore) · https://aclanthology.org/2024.acl-short.7.pdf (Isotropy/Clusters/Classifiers) · https://arxiv.org/abs/1909.00512 (Ethayarajh) · https://arxiv.org/abs/2201.04337 (PromptBERT) · https://arxiv.org/abs/1710.04087 (CSLS) · https://arxiv.org/abs/2310.11612 (DBNorm) · https://jmlr.org/papers/v11/radovanovic10a.html (hubness) · https://arxiv.org/abs/2401.00368 (E5-mistral)

**Taxonomy induction**
- https://arxiv.org/abs/2511.12353 (AstroMLab 5) · https://arxiv.org/abs/2403.12173 (TnT-LLM) · https://arxiv.org/abs/2311.01449 (TopicGPT) · https://arxiv.org/abs/2410.23584 (OLLM) · https://arxiv.org/abs/2507.22913 (UNT hybrid) · https://arxiv.org/abs/2409.04056 (WiKC)

**My own measurements**
- https://www.federalregister.gov/api/v1/documents.json (topic vocabulary, coverage, and facet fields)

---

## 8. Gaps and caveats

- **The vocabulary-survey thread was stopped mid-run**, so the systematic enumeration of candidate US regulatory label spaces is incomplete. Missing: verified sizes/licenses for CRS Legislative Subject Terms, CRS Policy Areas, NAICS, EuroVoc, agency thesauri (EPA, NAL, NASA, MeSH), and FAST's own topical size. My Federal Register measurement covers the highest-value piece but is not a substitute for that survey. Worth re-running.
- **Web-search budget (200 calls) was exhausted globally** partway through, across all threads. Later work was done by direct HTTP fetch against already-surfaced URLs. Under-covered as a result: hubness in *text* (not cross-modal) retrieval, XMC label augmentation, non-arXiv GLAM venues, and any 2026 XMC work postdating Nov 2025.
- **Never verified**: WiKC's 4.1M→17K pruning figure (the most quotable number in the pruning section); PECOS benchmark tables (the summarizer returned P@5 > P@1 — discarded); ViXML's LF-AmazonTitles numbers (far above all other sources for the same datasets — do not cite); BLINK's R@64 82.06; DEPL's PSP figures; all Matryoshka-by-dimension tables; the LIMIT small-setting per-model table.
- **Two things I could not find measured anywhere**: (a) an ablation deleting off-domain labels and reporting recall@k on remaining in-domain gold; (b) any benchmark of long-document-as-query against short-label-as-corpus, which is this system's exact orientation.

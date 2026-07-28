# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

The researcher downloaded the papers and read the tables directly. This exposed a RAE-XMC table with R@100 < R@10, a PECOS table with P@5 > P@1, and a SemSup-XC row pulled from the wrong block in an earlier automated summary. Numbers marked ✓ below were read directly from the paper source; anything not read directly is quarantined in section (d).

---

# (a) Per-source findings

## Q4 — Annif, Omikuji, and SemEval-2025 Task 5 (LLMs4Subjects)

**SemEval-2025 Task 5 task paper (D'Souza et al.)** ✓ read Table 3 directly.
Label space: **204,739 GND subjects** (all-subjects) and **79,427** (tib-core). 123,589 TIBKAT records; 81,937 train / 13,666 dev for all-subjects. Teams had training data.

Verified leaderboard, **all-subjects** (P@5 / R@5 / P@10 / **R@10** / avg R@k over k=5..50):

| Team | P@5 | R@5 | P@10 | **R@10** | Ov. R@k |
|---|---|---|---|---|---|
| Annif | 0.26 | 0.49 | 0.16 | **0.57** | 0.63 |
| DUTIR831 | 0.26 | 0.48 | 0.15 | **0.56** | 0.60 |
| RUC Team | 0.23 | 0.44 | 0.14 | **0.52** | 0.59 |
| DNB-AI | 0.25 | 0.47 | 0.15 | **0.54** | 0.56 |
| icip | 0.20 | 0.39 | 0.12 | 0.46 | 0.53 |
| TartuNLP | 0.13 | 0.27 | 0.08 | 0.33 | 0.38 |
| YNU-HPCC | 0.05 | 0.12 | 0.03 | 0.16 | 0.23 |
| TSOTSALAB | 0.02 | 0.04 | 0.01 | 0.05 | 0.07 |

**tib-core** (79,427 labels): RUC 0.25/0.48/0.16/0.57/0.66; Annif 0.23/0.48/0.14/0.54/0.59; LA2I2F 0.20/0.41/0.13/0.49/0.58; DUTIR831 0.23/0.49/0.13/0.54/0.56.

The GPT-4o Assistant-API baseline "ranked below participant submissions"; the paper reports no numeric score for it and notes JSON-reliability failures requiring repeated inference.

**This is the single most comparable benchmark to the target system.** A domain-matched 205K-concept vocabulary, with 82K training records, and the world's best system reaches **R@10 = 0.57**.

**Annif at SemEval-2025 (Suominen, Inkinen, Lehtinen)** ✓ read tables directly.
Vocabulary as stated in Annif's own paper: **200,035** all-subjects / **78,741** tib-core (note: differs slightly from the task paper's 204,739/79,427 — an unexplained discrepancy between the two papers).
Backends: **Omikuji Bonsai** (partitioned label trees, Parabel/Bonsai family), **MLLM** (Maui-like lexical matching), **XTransformer** (xlm-roberta-base, from PECOS). LLMs used only for *translation* and *synthetic training data*, not for label selection.
Final test: all-subjects **F1@5 0.3432, avg recall 0.6295, rank 1st**; tib-core **F1@5 0.3136, recall 0.5899, rank 2nd**. Competitors: DUTIR831 0.3346/0.6045; RUC 0.3015/0.5856; DNB-AI 0.3231/0.5631; icip 0.2618/0.5302.
Synthetic data lifted Bonsai nDCG by ~0.03.

Two statements matter more than the numbers. The Annif authors attributed the
sub-0.35 F1@5 ceiling in part to inconsistent TIBKAT subject metadata. They
also noted that prior, consistently indexed datasets had exceeded 0.5 F1@5.

So the ceiling in this task was set by gold-standard consistency, not algorithms.

**Annif at GermEval-2025 (Subtask 2)** ✓ read Table 2 directly.
GND 200,035 subjects. New component: an **LLM candidate-reranking ensemble** (prompt an LLM to score each candidate 0–100). Test: BM simple 0.3200 F1@5 / 0.5496 nDCG@20; BMX simple 0.3200/0.5507; BMX LLM Q4 0.3251/0.5631; **BMX LLM M24 0.3288/0.5697, rank 1st**. DNB-AI 0.2466/0.4180 (2nd); ubffm 0.0742/0.1465 (3rd).
**The LLM rerank added only +0.009 F1@5 / +0.019 nDCG@20 over the non-LLM ensemble.** LLM reranking of candidates is a marginal gain, not a step change.

**Annif backends, training requirement** (official wiki) ✓.
Omikuji: hierarchical balanced k-means over the label space, emulates Parabel
and Bonsai; **requires training data**. YAKE: **unsupervised, requires no
training**, extracts keywords then lexically matches lemmatised forms against
SKOS prefLabel/altLabel/hiddenLabel, but the official documentation reports
that other lexical backends perform better.
Practical consequence for a system with no training data: Omikuji/fastText/XTransformer are all unavailable; only the lexical/unsupervised backends apply.

**DNB-AI-Project at SemEval-2025** ✓ read verbatim.
Pipeline: **Complete** (8 LLMs × prompts, 8–12 few-shot examples, generate *free* keywords) → **Map** (BGE-M3 embeddings, HNSW nearest-neighbour into GND via Weaviate) → **Summarise** (sum similarity across model×prompt) → **Rank** (Llama-3.1-8B rates each term 0–10) → **Combine** (α=0.3). No fine-tuning. 4th quantitative, **1st qualitative**.

The most important finding in this body of research is that GND-Subjects-all
could not represent some generated free keywords. Missing named entities,
including country names, were forced onto unrelated subject terms, and a
minimum-similarity threshold did not prevent the error.

Their fix was to *extend* the vocabulary from 200,035 to **309,417** concepts
by adding 109,382 named entities, map cleanly into that wider space, and then
**filter out** concepts outside the target subject collection. The authors
reported fewer false positives with this map-wide, emit-narrow design.

This is a coverage-mismatch failure mode, and it is the mirror image of the target system's problem. Note carefully: their fix was to make the label space **bigger**, not smaller — because ANN mapping is *forced choice*, and the cure for snapping-to-wrong-concept is an absorbing set of decoys that you delete afterward.

---

## Q1 — How modern XMC generates candidates

**Label trees / hierarchical label clustering.** PECOS (Amazon) is the canonical three-stage design: semantic label indexing (PIFA label embeddings = aggregate of positive-instance features, then recursive balanced/spherical k-means into a B-ary tree) → matching (retrieve top clusters) → ranking, with beam search at inference for O(log L). XR-Linear and XR-Transformer are its instantiations. Parabel/Bonsai/Omikuji are the same family. **All require training data to build the label representations** — PIFA is literally defined from positive instances.

**Learned index instead of fixed clustering — ELIAS** ✓ read Tables 2 and 3 directly. Relaxes discrete cluster→label assignment into learnable soft parameters (a sparse weighted graph). Amazon-670K, single model, supervised:

| Method | P@1 | **R@10** | R@20 | R@100 |
|---|---|---|---|---|
| BERT-OvA (brute force, no shortlisting) | 48.50 | **49.53** | 56.60 | 67.90 |
| AttentionXML | 45.84 | **45.59** | 51.25 | 60.77 |
| XR-Transformer (dense) | 45.25 | **45.19** | 51.61 | 61.11 |
| LightXML | 47.29 | **47.34** | 53.26 | 62.03 |
| ELIAS | 48.68 | **50.33** | 57.67 | 68.95 |

Ablation: fixed-clustering index (Stage 1) R@10 46.08 → learned index (Stage 2) 50.33. Directly relevant: **partition-based shortlisting costs ~4 points of R@10 versus exhaustive scoring.** The target system already does exhaustive exact search, so its shortlist mechanism is not the bottleneck — the embedding is.

**Dense retrieval over label embeddings.** NGAME/DEXA/DEXML/RAE-XMC treat labels as documents and do MIPS/ANN. DNB-AI uses HNSW in Weaviate.

**Generative / label-id decoding.** GROOV (generate label strings) collapses in zero-shot: ✓ P@1 **1.2** on EURLex-4.3K ZS-XC, **0.0** on AmazonCat-13K ZS-XC, 6.0 on Wikipedia-1M ZS-XC — while scoring 84.1/87.4/31.4 in *generalized* zero-shot where seen labels dominate. Generation without grounding does not reach unseen labels.

**The dominant no-training-data pattern is generate-then-map-then-rerank**, independently arrived at by three groups: IReRa (Infer→Retrieve→Rank), DNB-AI (Complete→Map→Rank), ICXML (generate→shortlist→rerank).

**IReRa (D'Oosterlinck, Khattab et al., "In-Context Learning for Extreme Multi-Label Classification")** ✓ read Table 1 directly. ESCO ontology ≈13,900 concepts. Frozen retriever, frozen LMs, no fine-tuning, ~10 training + ~50 validation examples. Metric RP@K (= precision@K when K≤R_n, recall@K when K≥R_n).

| System | HOUSE RP@10 | TECH RP@10 | TECHWOLF RP@10 | BioDEX RP@10 |
|---|---|---|---|---|
| **naive-retrieve** (document → label dense retrieval) | **36.76** | **49.79** | **42.13** | **11.71** |
| Infer–Retrieve (no rerank) | 52.62 | 62.45 | 56.50 | 24.77 |
| **Infer–Retrieve–Rank** | **65.76** | **70.23** | **65.17** | **27.67** |
| − optimize Infer (unoptimized) | 30.69 | 33.42 | 29.69 | 15.76 |
| finetuned retrieve (≈138,000 train) | 55.95 | 66.24 | 62.55 | — |

**Routing through LLM-generated free-text terms nearly doubles RP@10 over direct document→label retrieval**, and beats a retriever fine-tuned on 138K examples. Honest caveat I verified: the *unoptimized* program (30.69) is **worse** than naive-retrieve (36.76) on HOUSE — the DSPy bootstrapping of ~50 examples is doing real work, not just the architecture.

**ICXML (Generate-and-Rerank)** ✓ read Tables 1 and 2 directly. LF-WikiSeeAlso-320K (312,330 labels), ✗ = no training data used:

| Method | train? | P@1 | R@5 | **R@10** |
|---|---|---|---|---|
| TF-IDF | ✗ | 0.107 | 0.165 | 0.216 |
| BM25 | ✗ | 0.185 | 0.210 | 0.254 |
| **TAS-B** (off-the-shelf dense) | ✗ | 0.237 | 0.292 | **0.365** |
| MACLR | ✓ | 0.163 | 0.254 | 0.321 |
| free generation (GPT-3.5) | ✗ | 0.246 | 0.271 | 0.327 |
| ICXML-label | ✗ | **0.278** | 0.290 | 0.356 |

Note: a plain off-the-shelf dense retriever (TAS-B) achieves R@10 = 0.365 with zero training on a 312K label space — **better than MACLR, which required corpus-specific pretraining**. The generative-and-rerank methods win on P@1 but not on R@10.

---

## Q2 — Label text vs label ID

**With training data, label-text dual encoders beat pure-ID one-vs-all.** RAE-XMC ✓ read Table 1 directly (columns: P@1, P@5, R@100, train hours):

**LF-Wikipedia-500K (501,070 labels), supervised:**

| Method | P@1 | P@5 | R@100 | Train h |
|---|---|---|---|---|
| OvA Classifier (pure ID) | 82.00 | 48.54 | — | — |
| XR-Transformer | 81.62 | 47.85 | — | 318.9 |
| NGAME (DE+OvA) | 84.01 | 49.97 | — | 54.9 |
| DEXA (DE+OvA) | 84.92 | 50.51 | — | 57.5 |
| OAK | 85.23 | 50.79 | — | — |
| DPR | 65.23 | 35.23 | — | 54.7 |
| ANCE | 63.33 | 33.12 | — | 75.1 |
| DEXML | 85.59 | 50.39 | **90.52** | 37.0 |
| **RAE-XMC** | **86.49** | **50.67** | 90.24 | 6.4 |

LF-AmazonTitles-131K: DEXML 42.24/20.47/R@100 68.81; RAE-XMC 45.10/21.95/**71.94**; DEXA(DE+OvA) 46.42/21.59.
LF-AmazonTitles-1.3M: DEXML 58.43/45.48/R@100 64.26; RAE-XMC 58.48/47.00/66.88.

Label-text dual encoders (85.6–86.5 P@1) beat the pure-ID OvA classifier (82.00) on Wikipedia-500K. But note DPR and ANCE — generic dense retrievers — score 63–65 P@1, i.e. **the encoder architecture is not what matters; the XMC-specific training is.**

**Without training data, label ID is not even an option, and label *description* beats label *name* decisively.** SemSup-XC ✓ read Tables 1 and 2 directly. Wikipedia-1M: 2.7M total labels, 495,107 seen / **776,612 unseen**. ZS-XC = evaluated only on unseen labels.

| Wikipedia-1M, ZS-XC | P@1 | **R@10** |
|---|---|---|
| TF-IDF (class **names**) | 14.5 | 18.3 |
| Sent. Transformer (class **names**) | **7.8** | **13.3** |
| Sent. Transformer (scraped class **descriptions**) | **19.6** | **22.5** |
| T5 (names) | 8.2 | 23.6 |
| MACLR | 29.8 | 41.7 |
| ZestXML | 15.8 | 20.8 |
| GROOV | 6.0 | 15.4 |
| SemSup-XC | 36.5 | 38.5 |

**Giving the same frozen sentence encoder a scraped description per label instead of just the label string takes P@1 from 7.8 → 19.6 (2.5×) and R@10 from 13.3 → 22.5.** This is the cheapest, highest-leverage lever in the entire literature for a no-training-data system, and it is a property of the *label side*, not the model.

**Lexical matching is a tough-to-beat zero-shot baseline.** MACLR paper, verbatim: "TF-IDF performs better than many BERT variants (e.g., SentBERT, SimCSE, ICT), which is aligned with the finding in recent zero-shot dense retrieval literature."

---

## Q3 (CRITICAL) — Does a large / off-domain label space hurt?

**Strongest evidence: CoRECT** ✓ read Table 2 and the construction section directly. This is a *clean controlled dilution experiment*: same 76 TREC-DL queries, each with **exactly 10 relevant items and exactly 100 mined hard distractors**, held fixed; the rest of the corpus is filled with **truly random irrelevant documents**. Only the count of irrelevant items varies.

**Recall@100 (%) as the irrelevant pool grows:**

| Model | Passages 10k | 1M | 100M | Docs 10k | 1M | 10M |
|---|---|---|---|---|---|---|
| Jina V3 | 83.85 | 71.39 | **44.15** | 72.91 | 47.64 | **26.91** |
| E5 | 84.15 | 75.39 | **50.77** | 76.00 | 47.64 | **31.64** |
| Snowflake V2 | 82.00 | 74.92 | **53.39** | 74.00 | 50.18 | **34.36** |
| Snowflake V1 | 80.31 | 71.69 | **50.92** | 74.00 | 50.36 | **36.73** |

**Adding purely irrelevant items to a dense index costs 30–46 absolute points of recall@100.** The relevant items and the hard distractors never changed. This is the cleanest published answer to "does off-domain filler hurt recall" and the answer is unambiguously yes. The paper also cites Reimers & Gurevych for "dense retrieval models struggle as corpus size increases."

One caveat I must flag: the paper notes nDCG@10 is far more stable than recall@100, because *random* documents rarely rank into the top 10. The target system's FAST headings are not random noise — they are fluent, semantically plausible English phrases, which is the *worse* case, closer to the 100 hard distractors than to the random filler.

**Label Space Reduction ("From Haystack to Needle")** ✓ read Table 1 directly. I have to substantially walk back what the abstract implies. Datasets have **11–102 classes**, single-label, and the method is iterative LLM + CatBoost re-ranking.

Llama-3.1-70B macro-F1 baseline → gain:

| | Massive Scen. | Massive Intent | Banking77 | Mtop Dom. | Mtop Int. | Crime | DBpedia | Avg gain |
|---|---|---|---|---|---|---|---|---|
| baseline | .719 | .778 | .670 | .945 | .633 | .765 | .555 | — |
| w/ CoT-SC | +.015 | +.020 | +.026 | +.011 | +.017 | +.002 | +.024 | +0.016 |
| **w/ LSR k=2.0** | +.050 | +.027 | **+.129** | +.014 | +.050 | +.077 | **+.142** | **+0.070** |
| **w/ LSR k=Full (ranking only, NO reduction)** | +.044 | +.028 | +.101 | +.017 | +.037 | +.061 | +.099 | **+0.055** |

**The honest decomposition: +0.055 of the +0.070 average gain comes from ranking alone with the label space left at full size. Actual reduction contributes only +0.015 (≈21%).** The paper's mechanism claim is attention dilution over long label lists in the LLM context — which applies to the *judge* stage, not to embedding retrieval, and at 11–102 classes, not 10^5.

**Calibration@k** ✓ read directly. "As the label size increases from 4K to 3M (millions), the ECE@k rises, indicating a decline in calibration performance." But the paper's own explanation is supervision density: "This trend is anticipated, as the average number of data points per label diminishes with larger label sizes." **This is a training-data-density effect and does NOT transfer to a zero-shot system.** I am not counting it as evidence.

**tib-core vs all-subjects is NOT a clean ablation and does not support label-space pruning.** ✓ Verified from the task paper: tib-core is a domain-filtered GND subset (14 TIB core disciplines, 79,427 vs 204,739), but the *record sets also differ* (41,902 vs 81,937 training records). Results split both ways — Annif 0.63→0.59 and DUTIR831 0.60→0.56 got **worse** on the smaller vocabulary; RUC 0.59→0.66 and LA2I2F 0.48→0.58 got **better**. Confounded, mixed, and cannot be used as evidence in either direction.

**Coverage mismatch, not size, is the documented failure mode** — DNB-AI (quoted in full above): missing concepts cause forced-choice ANN to snap to unrelated terms, and a similarity threshold does not fix it.

**What I looked for and did NOT find:** no XMC paper I located runs the specific ablation "delete the off-domain fraction of the label space and measure recall@k on the remaining in-domain gold labels." The XMC survey's taxonomy covers label-space *dimension reduction* (compressed sensing, embeddings) and tree-based partitioning — those are efficiency techniques, not relevance filtering. Head/tail and propensity-scored metrics (PSP@k, Jain et al.) address label *frequency* imbalance, not label *domain* mismatch. These are different problems and I will not conflate them.

---

## Q5 — Real recall numbers at scale

**Zero-shot / no training data (EZ-XMC), MACLR paper** ✓ read Table 2 in full. Label counts ✓ from Table 1.

**LF-Wikipedia-500K (501,070 labels), zero-shot:**

| Method | P@1 | P@5 | R@5 | **R@10** | R@100 |
|---|---|---|---|---|---|
| TF-IDF | 20.30 | 9.96 | 15.98 | **20.31** | 38.16 |
| XR-Linear | 10.67 | 7.61 | 12.11 | **19.80** | 31.02 |
| GloVe | 2.19 | 1.23 | 2.18 | **3.10** | 8.52 |
| **SentBERT** | 0.17 | 0.13 | 0.18 | **0.30** | 1.29 |
| MPNet | 22.46 | 9.49 | 16.76 | **20.64** | 34.72 |
| SimCSE | 14.32 | 4.55 | 11.26 | **14.35** | 27.68 |
| ICT | 17.74 | 7.06 | 13.84 | **17.19** | 31.08 |
| **MACLR** | **28.44** | **13.53** | **22.38** | **28.52** | **50.09** |

**LF-WikiSeeAlso-320K (312,330):** TF-IDF R@10 21.60; MPNet 28.11; MACLR 32.05 / R@100 53.83.
**LF-Amazon-131K (131,073):** TF-IDF R@10 29.32; MPNet 27.91; MACLR 37.28 / R@100 54.99.
**LF-Amazon-1M (960,106):** TF-IDF R@10 31.76; MPNet 29.35; MACLR 34.48 / R@100 55.23.

Note SentBERT's catastrophic 0.30 R@10 vs MPNet's 20.64 on the same 500K label space — a 68× spread between two sentence-transformer checkpoints. **Embedding model choice is worth more than everything else combined at this scale.**

**Supervised, for contrast:** LF-Wikipedia-500K R@100 = 90.24–90.52 (RAE-XMC / DEXML) vs 50.09 zero-shot. Amazon-670K supervised R@10 = 50.33 (ELIAS). LF-AmazonTitles-131K supervised R@100 = 71.94.

**Direct calibration against the target system's 3-of-8-in-top-12 (= 37.5% recall@12):**

| Setting | Labels | Training data | Recall@~10 |
|---|---|---|---|
| SentBERT zero-shot, LF-Wikipedia-500K | 501K | none | **0.3%** |
| MPNet zero-shot, LF-Wikipedia-500K | 501K | none | **20.6%** |
| TF-IDF zero-shot, LF-Wikipedia-500K | 501K | none | **20.3%** |
| MACLR (corpus-pretrained), LF-Wikipedia-500K | 501K | unlabeled corpus | **28.5%** |
| TAS-B off-the-shelf, LF-WikiSeeAlso-320K | 312K | none | **36.5%** |
| **Target system** | **513K** | **none** | **~37.5%** |
| Sent.Transf. + label *descriptions*, Wikipedia-1M ZS | 2.7M | none | 22.5% |
| SemSup-XC, Wikipedia-1M ZS | 2.7M | seen-label training | 38.5% |
| Best LLMs4Subjects system (GND) | 205K | 82K records | **57%** |
| ELIAS supervised, Amazon-670K | 670K | 490K records | **50.3%** |

---

# (b) Verdict: is the 500K mostly-off-domain label space a known-bad configuration?

**Partially — and the two halves of the answer point in opposite operational directions. Be careful here.**

**1. For the *retrieval* stage: yes, this is a known-bad configuration, and CoRECT is the direct evidence.** Holding the relevant items and hard distractors fixed and inflating the index with irrelevant material costs 30–46 points of recall@100. A 513K vocabulary in which ~511,000 concepts cannot possibly be correct for a US federal regulatory document is exactly that experiment, run in production. The literature supports the claim that recall@12 would rise if the off-domain fraction were excluded from the *retrieval index*.

**2. But no one has published the specific ablation, and I will not claim they have.** No XMC paper I found removes off-domain labels and reports recall@k going up. The nearest in-domain comparison (tib-core vs all-subjects) is confounded and splits both ways. Treat "shrink the vocabulary" as well-motivated by adjacent evidence, not as an established XMC result.

**3. The one experiment in this literature that most resembles the target problem concluded the opposite of "prune."** DNB-AI hit precisely the coverage-mismatch failure mode — plausible concepts absent from the vocabulary get "falsely mapped to unrelated subject terms," and thresholding did not help — and fixed it by **growing** the vocabulary 200K → 309K and filtering *after* the mapping. The lesson is not "fewer labels." It is **decouple the space you map into from the space you are allowed to emit.** For the target system: keep FAST/TSCA in the index as absorbing decoys so off-topic content has somewhere correct-ish to land, but only emit from the ~1,901 regulatory concepts (plus whatever else is genuinely in scope). That gets the CoRECT benefit at the emit stage and the DNB-AI benefit at the map stage simultaneously.

**4. The measured symptoms are not evidence of a broken system — they are the expected operating point.** At 37.5% recall@12 with no training data over 513K labels, the target is at or slightly above every published zero-shot number at comparable scale (MPNet 20.6%, TF-IDF 20.3%, MACLR 28.5%, TAS-B 36.5%). The 0.029 cosine margin and 43/768 effective dimensionality are consistent with well-known embedding anisotropy, but I could not verify any paper that quantifies margin shrinkage *as a function of label count* — do not attribute those two measurements to the label space without an experiment.

**5. The realistic ceiling is much lower than intuition suggests, and it is set by annotation consistency.** The best-resourced system in the world, on a domain-matched 205K vocabulary with 82K training records, reaches R@10 = 0.57 and F1@5 = 0.343 — and Annif attributes the sub-0.35 ceiling to gold-standard inconsistency, noting they exceed F1@5 0.5 on consistently-indexed data. If the target system's 8 known-correct targets come from human tagging of comparable consistency, a substantial share of the gap is irreducible.

**Ranked by evidence strength, the interventions the literature actually supports:**

1. **Enrich label text with descriptions/scope notes** — SemSup-XC: same frozen encoder, P@1 7.8 → 19.6, R@10 13.3 → 22.5 on a 2.7M-label zero-shot space. Largest verified gain available with no training data. FAST and CRS terms have scope notes and broader/narrower relations; use them.
2. **Switch/audit the embedding model** — 0.30 vs 20.64 R@10 between two sentence transformers on the same 500K space.
3. **Replace document→label retrieval with infer→retrieve→rank** — IReRa: RP@10 36.76 → 65.76 on 13.9K ESCO labels, beating a retriever fine-tuned on 138K examples. DNB-AI and ICXML independently converge on this. Requires ~50 labeled examples for the DSPy optimization, which is the one prerequisite the target system must satisfy — the unoptimized variant is *worse* than naive retrieval.
4. **Add lexical/BM25 hybrid** — TF-IDF beat most neural encoders zero-shot in MACLR; BM25 beat TF-IDF by 4 points R@10 in ICXML.
5. **Scope the emit vocabulary while keeping decoys in the index** — CoRECT + DNB-AI, as above.
6. **LLM reranking of candidates** — worth only +0.009 F1@5 in Annif's GermEval measurement. Do this last.

---

# (c) URLs grouped by claim

**LLMs4Subjects task, label space and leaderboard (R@10 = 0.57 best on 205K GND)**
- https://arxiv.org/abs/2504.07199 · https://arxiv.org/html/2504.07199v2 · https://aclanthology.org/2025.semeval-1.328/

**Annif system, backends, F1@5 0.3432 / 0.35 ceiling / >0.5 on consistent data**
- https://arxiv.org/abs/2504.19675 · https://arxiv.org/html/2504.19675v2 · https://aclanthology.org/2025.semeval-1.315/

**Annif GermEval-2025, LLM rerank worth +0.009 F1@5**
- https://arxiv.org/abs/2508.15877 · https://arxiv.org/html/2508.15877v1

**Annif backends: Omikuji requires training; YAKE is unsupervised**
- https://github.com/NatLibFi/Annif/wiki/Backend%3A-Omikuji · https://github.com/NatLibFi/Annif/wiki/Backend%3A-YAKE · https://github.com/NatLibFi/Annif · https://github.com/tomtung/omikuji

**DNB-AI: forced-choice mapping to unrelated terms; vocabulary extension 200K→309K; thresholding insufficient**
- https://arxiv.org/abs/2504.21589 · https://arxiv.org/html/2504.21589 · https://aclanthology.org/2025.semeval-1.148.pdf · https://github.com/deutsche-nationalbibliothek/semeval25_llmensemble

**Distractor dilution: Recall@100 82.00 → 53.39 (CoRECT)**
- https://arxiv.org/abs/2510.19340 · https://arxiv.org/html/2510.19340v3 · https://github.com/padas-lab-de/CoRECT · https://huggingface.co/datasets/PaDaS-Lab/CoRE

**Label space reduction for LLM classification (11–102 classes; reduction = 21% of gain)**
- https://arxiv.org/abs/2502.08436 · https://arxiv.org/html/2502.08436v1

**Zero-shot recall at 500K labels (MACLR / EZ-XMC)**
- https://arxiv.org/abs/2112.08652 · https://ar5iv.labs.arxiv.org/html/2112.08652 · https://aclanthology.org/2022.naacl-main.399/

**Label descriptions ≫ label names in zero-shot (SemSup-XC)**
- https://arxiv.org/abs/2301.11309 · https://ar5iv.labs.arxiv.org/html/2301.11309 · https://proceedings.mlr.press/v202/aggarwal23a/aggarwal23a.pdf

**Infer–Retrieve–Rank, no fine-tuning, ~50 examples**
- https://arxiv.org/abs/2401.12178 · https://ar5iv.labs.arxiv.org/html/2401.12178 · https://github.com/KarelDO/xmc.dspy

**Generate-and-rerank zero-shot (ICXML); TAS-B R@10 0.365 at 312K labels**
- https://arxiv.org/abs/2311.09649 · https://arxiv.org/html/2311.09649v2

**Shortlist recall vs brute force; learned index (ELIAS)**
- https://arxiv.org/abs/2210.08410 · https://ar5iv.labs.arxiv.org/html/2210.08410 · https://github.com/nilesh2797/ELIAS

**Supervised SOTA at 500K–1.3M labels; label-text DE vs pure-ID OvA (RAE-XMC, DEXML)**
- https://arxiv.org/abs/2502.10615 · https://arxiv.org/html/2502.10615v1 · https://arxiv.org/abs/2310.10636

**Label trees, PIFA, beam search (PECOS)**
- https://arxiv.org/abs/2010.05878 · https://www.jmlr.org/papers/volume23/21-0085/21-0085.pdf · https://github.com/amzn/pecos

**Calibration degrades with label count (supervision-density mechanism)**
- https://arxiv.org/abs/2411.04276 · https://arxiv.org/html/2411.04276v1

**XMC survey (taxonomy, propensity-scored metrics, tail labels)**
- https://arxiv.org/abs/2302.05971 · https://arxiv.org/abs/2210.03968

---

# (d) Could not verify

- **PECOS XR-Linear benchmark table.** The summarizer returned P@1 48.6 / P@5 73.1 for Wiki-500K — impossible (P@5 > P@1). **Discarded entirely.** I have no verified XR-Linear numbers.
- **RAE-XMC via PDF.** First fetch produced R@100 < R@10. Discarded; the HTML table above is the verified replacement.
- **DEXML's own reported figures** (P@1 85.78 on LF-Wikipedia-500K). Summarizer only. RAE-XMC's table independently reports 85.59 for DEXML — close, but the two are not identical and I did not read DEXML's paper directly.
- **ELMO (arXiv 2510.11168) Amazon-3M numbers** (Renee P@1 52.6, ELMO 53.4). Summarizer only. Not read directly. Also reports a new LF-Paper2Keywords-8.6M dataset (8.6M labels) — unverified.
- **ViXML / "LLMs Meet XMC" (arXiv 2511.13189)** — LF-AmazonTitles-131K P@1 52.47 text-only, R@100 82.21; LF-AmazonTitles-1.3M P@1 67.83. Summarizer only. These P@1 values are far above every other source for the same datasets (RAE-XMC reports 45.10 on LF-AmazonTitles-131K), so either the setup differs materially or the extraction is wrong. **Do not cite without reading the paper.**
- **Extreme Classification Repository** (manikvarma.org) — TLS certificate mismatch; web.archive.org blocked. No canonical leaderboard obtained.
- **DNB-AI's own per-metric numbers** (P@5 0.246, R@5 0.471, F1@5 0.323, R@50 0.579). Summarizer only. The task paper's verified Table 3 gives DNB-AI 0.25/0.47 — consistent, so I cited the task paper instead. The per-subject-area and per-record-type breakdowns (Architecture 0.502, Articles 0.157, etc.) are **unverified**.
- **"High-Dimensional Concentration and Retrieval Instability in Embedding Spaces" (arXiv 2606.28330).** Single author, synthetic experiments only, no venue. PDF unreadable via fetch. Thematically on-point for the 0.029-margin / 43-of-768 observations but I extracted **no numbers** and cannot vouch for it. Do not cite.
- **"Does Generative Retrieval Overcome the Limitations of Dense Retrieval?" (arXiv 2509.22116).** Directional claim only (generative retrieval degrades with corpus size); **no numbers extracted**.
- **Phenotype normalization, GPT-4o 62% → 85% with retriever** (PMC11913805, HPO 17,957 terms → 30,234 with synonyms, 20 candidates, accuracy plateaus at 20). Summarizer only, not read directly. Suggestive that ~12–20 candidates is a reasonable shortlist size, but unverified.
- **Vocabulary-free fine-grained visual recognition "label filtering" (arXiv 2505.01064).** No numbers obtainable; PDF extraction failed. Dropped.
- **Hubness literature.** Real and well-established (Radovanović et al. JMLR; 2024–2025 cross-modal hubness-reduction work), and mechanistically relevant to a 513K label index, but I obtained **no measurement tying hubness to XMC recall@k** and am not asserting one.
- **Annif's documented performance on YSO/Finto AI** (its production Finnish vocabulary, ~30K concepts). annif.org returned HTTP 403; no numbers obtained. This would have been the most useful "matched-domain, small-vocabulary" comparison point and remains an open gap.
- **SemEval winners RUC Team, DUTIR831, LA2I2F system papers.** Not read individually; their methods are described only via the task paper's summary (embedding retrieval with Arctic-Embed/Jina/E5, LoRA fine-tuning + DPO, Qwen2.5-72B / ChatGLM-4 130B). Their internal candidate-generation details are unverified.
- **Search budget exhausted** at 200 calls partway through; the last third of this research used direct HTTP fetches against URLs already surfaced. Relevant 2026 work may be missing; in particular, the research found no 2026-dated XMC paper that postdates the November 2025 LLM-XMC work.

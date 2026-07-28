# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

All four load-bearing sources were read first-hand, and verification caught two automated-summary errors worth flagging.

---

# Label-text engineering + embedding geometry: findings

Every number below is tagged **[V]** = I rendered the paper page and read the table myself, or **[2H]** = came only through WebFetch's summarizer model. Two **[2H]** claims turned out to be wrong on inspection; details in §D.

## A. Per-source findings

### A1. Effective dimensionality is not a pathology signal

**IsoScore (Rudman, Gillman, Rayne, Eickhoff; Findings ACL 2022)** **[V]**
- IsoScore ≈ *the fraction of dimensions uniformly utilized* (their Heuristic 4.1 / A.1). This makes it directly comparable to your 43/768 ≈ 0.056.
- Verbatim from §5.2: **"IsoScore returns values of less than 0.18 for every considered contextualized embedding model."** And: **"GPT and GPT-2 embeddings do not even isotropically utilize a single dimension in space."**
- The mean-agnosticism critique, which is the crux: on one point cloud rotated 0°/120°/240°/PCA, IsoScore reads **0.216, 0.216, 0.216, 0.216** while average-random-cosine reads **0.990, 0.968, 0.981, 0.993** and partition score reads **0.445, 0.673, 0.669, 0.446**. Zero-centering data drives average random cosine to 0 "without impacting the distribution of the variance." Raw cosine gaps are dominated by the shared mean vector. (GPT-2 on WikiText-2: mean vector components range −32.36 to 198.19.)
- Sampling warning: they use 250,000 pairs; Ethayarajh and Cai et al. used as few as 1,000. "The quantity of points sampled should be orders of magnitude larger than the dimension."
- They side with Biś et al. (2021) that contextual models **"do not necessarily occupy a 'narrow cone' in space"** — the cone framing is contested by the same paper that gave you the dimension-counting metric.

**Isotropy, Clusters, and Classifiers (Mickus, Grönroos, Attieh; ACL 2024 short, pp. 75–84)** **[V]**
- Proves the isotropy objective (maximize all pairwise distances) is mathematically incompatible with the silhouette objective (minimize intra-cluster distances) and with linear-classifier objectives. "Point clouds cannot both contain well-defined clusters and be isotropic."
- Empirically, as classification training proceeds silhouette rises and IsoScore falls, with Pearson **r = −0.808** (polarity), **−0.878** (SNLI), **−0.947** (POS), **−0.978** (supersense); "Spearman's ρ are always below −0.998."
- **Implication for you: low effective dimensionality is what a well-clustered label space looks like.** A 513K vocabulary with "Italian language--*" subdivision families and chemical-name families *should* be clumpy.

**Redundancy, Isotropy, and Intrinsic Dimensionality of Prompt-based Text Embeddings (Findings ACL 2025)** **[2H]** — reports IsoScore **0.0052–0.0405** for classification/clustering embeddings and **0.0332–0.2112** for retrieval/STS, across gte-Qwen2, E5-mistral, SFR-2, mE5-large-inst, Nomic, E5-large/small, unsup-SimCSE. Your 0.056 sits inside that range. Consistent with the [V] IsoScore result, but I did not read the table.

**Ethayarajh 2019** **[V]** — Figure 1: average cosine between *uniformly randomly sampled words*: GPT-2 ≈0.6 across layers 2–8 rising to ≈**0.97** at layer 12; BERT rises to ≈0.67 at layer 11 then ≈0.46 at 12; ELMo input layer ≈0.01. Also defines the anisotropy-baseline subtraction that everyone since has used: subtract E[cos(f(x),f(y))] over random pairs before interpreting any similarity. Under 5% of a word's contextual variance is explained by its first PC.

**On Isotropy Calibration of Transformer Models** **[2H]** — isotropy calibration methods "do not provide consistent improvements across models and tasks." A null result; I only saw the abstract.

### A2. Templated boilerplate: this is real and it is large

**PromptBERT (EMNLP 2022)** **[V]** — the most directly relevant evidence in the whole search.
- **Table 4**, greedy template search on bert-base-uncased, STS-B dev, *identical content, different wrapper*:

  | Template | STS-B dev |
  |---|---|
  | `[X] [MASK].` | 39.34 |
  | `[X] is [MASK].` | 47.26 |
  | `[X] mean [MASK].` | 53.94 |
  | `[X] means [MASK].` | 63.56 |
  | `This [X] means [MASK].` | 64.19 |
  | `This sentence of [X] means [MASK].` | 68.97 |
  | `This sentence of "[X]" means [MASK].` | 70.19 |
  | `This sentence : "[X]" means [MASK].` | 73.44 |

  **A 34.10-point swing from the boilerplate alone.** The paper states this explicitly.
- **Table 1** kills the naive anisotropy story: roberta-base last-layer has sentence anisotropy **0.9554** (near-maximal) yet scores 53.49 Spearman, *beating* bert-base-uncased last-layer at anisotropy 0.4874 / 52.57. Anisotropy does not predict quality.
- **Table 2**: average cosine among static token embeddings — bert-base-uncased 0.4445, bert-base-cased 0.1465, roberta-base **0.0235**. roberta is nearly isotropic here and still underperforms.
- **Table 3**: removing frequency/subword/case/punctuation biases lifts static-embedding Spearman from 56.93→66.05 (cased), 56.02→63.10 (uncased), 55.88→**67.64** (roberta).
- The authors caution that the method can omit meaningful words when the
  sentence is too short. Short label strings are the worst case for
  token-level debiasing.
- Their fix is *template denoising*: embed the template alone and subtract it. This is the cheapest thing you can try.
- Also relevant to Q1: they generated 500 templates from
  **word:definition** pairs. The best scored **64.75**, below the hand-written
  template's 73.44; the authors suggest that word definitions and sentence
  embeddings occupy different registers.

### A3. Dense retrieval over label text at extreme scale — the closest published analogue

**MACLR / Extreme Zero-Shot Learning for Extreme Text Classification (arXiv 2112.08652), Table 2** **[V]**

Label text truncated to 64 tokens, instances to 288, Siamese BERT-base → 512-dim. Label-space sizes: 131,073 / 312,330 / 501,070 / 960,106.

| Dataset | | TF-IDF | GloVe | SentBERT | MPNet | SimCSE | ICT | MACLR |
|---|---|---|---|---|---|---|---|---|
| LF-Amazon-131K | P@1 | 12.38 | 3.67 | 1.86 | **13.94** | 10.13 | 13.82 | 18.13 |
| | R@100 | 45.04 | 14.17 | 10.18 | 43.39 | 35.81 | 47.40 | 54.99 |
| LF-WikiSeeAlso-320K | P@1 | 10.71 | 3.86 | 1.71 | **13.75** | 9.03 | 10.76 | 16.31 |
| | R@100 | 42.55 | 15.33 | 10.76 | 45.91 | 30.11 | 39.77 | 53.83 |
| LF-Wikipedia-500K | P@1 | 20.30 | 2.19 | **0.17** | **22.46** | 14.32 | 17.74 | 28.44 |
| | R@100 | 38.16 | 8.52 | 1.29 | 34.72 | 27.68 | 31.08 | 50.09 |
| LF-Amazon-1M | P@1 | 7.68 | 4.05 | 2.82 | **8.29** | 3.33 | 8.66 | 9.58 |
| | R@100 | 51.79 | 21.18 | 14.22 | 46.15 | 18.54 | 48.42 | 55.23 |

Three things fall out, all first-hand:
1. **Model choice spans two orders of magnitude on identical data.** SentBERT P@1 **0.17** vs MPNet **22.46** on LF-Wikipedia-500K — a 132× gap, same labels, same documents, same protocol.
2. **TF-IDF is genuinely competitive.** Paper text: "TF-IDF remains a tough-to-beat unsupervised baseline. Specifically, TF-IDF performs better than many BERT variants (e.g., SentBERT, SimCSE, ICT)."
3. But MPNet — trained on large out-of-domain paraphrase supervision — beats TF-IDF on P@1 on **all four** datasets. So "dense on label text is hopeless" is *false*; "generic dense on label text is hopeless" is true.

**Related, [2H] only:** AstroConcepts (2026) — 21,702 astro abstracts × **2,367** Unified Astronomy Thesaurus concepts, 76% of concepts with <50 examples; best system F1 **0.377**, astroBERT 0.324, SciBERT 0.213; head-label F1 0.216–0.243 vs tail 0.081–0.198. UAT entries carry canonical designation + synonyms/acronyms + optional scope note. Useful scale anchor: at 2.4K concepts the ceiling is ~0.38 F1. You have 513K.

### A4. Hubness — large, cheap, and under-exploited

**CSLS, Conneau et al. ICLR 2018, Table 1** **[V]** — word translation P@1, 1,500 source queries against 200k targets. This *is* short-surface-form retrieval.

CSLS(Wxₛ,yₜ) = 2·cos(Wxₛ,yₜ) − rₜ(Wxₛ) − rₛ(yₜ), where r = mean similarity to K nearest neighbours (K=10; insensitive across K=5/10/50). No training, no tuning.

| | en-es | es-en | en-fr | fr-en | en-de | de-en | en-ru | ru-en | en-zh | zh-en |
|---|---|---|---|---|---|---|---|---|---|---|
| Procrustes-NN | 77.4 | 77.3 | 74.9 | 76.1 | 68.4 | 67.7 | 47.0 | 58.2 | 40.6 | 30.2 |
| Procrustes-ISF | 81.1 | 82.6 | 81.1 | 81.3 | 71.1 | 71.5 | 49.5 | 63.8 | 35.7 | 37.5 |
| Procrustes-CSLS | 81.4 | 82.9 | 81.1 | 82.4 | 73.5 | 72.4 | 51.7 | 63.7 | 42.7 | 36.7 |
| Adv-NN | 69.8 | 71.3 | 70.4 | 61.9 | 63.1 | 59.6 | 29.1 | 41.5 | 18.5 | 22.3 |
| Adv-CSLS | 75.7 | 79.7 | 77.8 | **71.2** | 70.1 | 66.4 | 37.2 | 48.1 | 23.4 | 28.3 |

NN→CSLS: **+2.1 to +7.2** supervised, **+4.7 to +9.3** unsupervised (fr-en 61.9→71.2). They also use *mutual* nearest neighbours under CSLS for dictionary induction.

**DBNorm / "Balance Act" (arXiv 2310.11612), Tables 1–5** **[V]** — post-hoc similarity normalization, zero retraining, R@1:

| Setting | base | +IS | +DualIS/DualDIS |
|---|---|---|---|
| MSCOCO-5k, CLIP | 30.31 | 35.15 | **37.93** |
| MSR-VTT full, CE+ | 12.62 | 13.31 | 14.88 |
| MSR-VTT full, TT-CE+ | 14.61 | 16.58 | 17.06 |
| MSR-VTT 1k, X-CLIP | 46.30 | 48.60 | 48.80 |
| MSCOCO-5k, Oscar | 52.50 | 52.77 | 53.91 |
| AudioCaps, AR-CE | 22.23 | 23.19 | 24.04 |
| Flickr30k, CLIP | 58.98 | 57.78 | 59.02 |

The **+7.6 R@1** case (MSCOCO CLIP) is precisely the zero-shot, asymmetric, distribution-mismatched setting. Flickr30k shows it can also do nothing. Cheap to test, not guaranteed.

**Canonical:** Radovanović, Nanopoulos, Ivanović, JMLR 2010 — k-occurrence skew grows with dimensionality; hubness is intrinsic to high-dimensional data, not a bug in any one model. **[2H]** abstract only.

**Adversarial Hubness (arXiv 2412.14113)** **[2H]** — useful natural baseline: over 25,000 queries, "the most common natural hub is the top-1 response to only 102 queries" (~0.4%). One adversarial hub reached >21,000. Also: natural-hubness mitigations do *not* stop concept-targeted adversarial hubs.

### A5. Asymmetric / instruction-tuned models

**E5-mistral, "Improving Text Embeddings with LLMs," Table 5** **[V]**:

| Instruction type | Class. | Clust. | PairClass. | Rerank | **Retr.** | STS | Summ. | Avg |
|---|---|---|---|---|---|---|---|---|
| natural-language instructions (default) | 78.3 | 49.9 | 87.1 | 59.5 | **52.2** | 81.2 | 32.7 | **64.5** |
| w/o instruction | 72.3 | 47.1 | 82.6 | 56.3 | **48.2** | 76.7 | 30.7 | 60.3 |
| w/ task-type prefix | 71.1 | 46.5 | 79.7 | 54.0 | **52.7** | 73.8 | 30.0 | 60.3 |

The headline "−4.2 average" is mostly STS/classification/pair-classification. **On retrieval specifically, a bare task-type prefix (52.7) slightly *beat* full natural-language instructions (52.2), and dropping instructions entirely cost only 4.0.** Don't over-invest in instruction-prompt engineering for a pure retrieval task.

**[2H]** model-card guidance, consistent across vendors: Qwen3-Embedding — instructions on the **query side only**, "not using an instruct on the query side can lead to a drop in retrieval performance by approximately 1% to 5%." BGE v1.5 — "For a retrieval task that uses short queries to find long related documents, it is recommended to add instructions for these short queries," but "No instruction only has a slight degradation"; documents never get the instruction. Nomic — `search_query:` / `search_document:` / `clustering:` / `classification:`.

**Symmetric vs asymmetric guidance** **[2H]** — the sentence-transformers docs treat this as a first-order model-selection decision ("it is critical that you choose the right model for your type of task"), with symmetric = comparable-length pairs and asymmetric = short query → long document. **Your setup is unusual and is neither**: short *label* ↔ long *segment*, where the short side is the corpus and the long side is the query. I found no paper that benchmarks that orientation directly. That is a genuine gap, not a thing I failed to find.

### A6. Matryoshka / dimension vs short text

**[2H]** Nomic MTEB by dimension: 768→62.28, 512→61.96, 256→61.04, 128→59.34, 64→56.10. EmbeddingGemma multilingual v2: 768→61.15, 512→60.71, 256→59.68, 128→58.23. BERT-whitening: STS-B 59.04 → 68.19 whitened → 67.51 at 256 dims.

I found **no** study measuring dimension-vs-performance *conditioned on input length*. Given your space already occupies ~43 effective dimensions, truncating to 256 is very unlikely to be your bottleneck. Deprioritize this axis.

### A7. Constructing label text

Mixed evidence, and worth measuring rather than assuming:

- **For:** BLINK represents each entity as `[CLS] title [ENT] description [SEP]` using the **first ten sentences** of the Wikipedia article, 128 tokens; ZESHEL bi-encoder R@64 **82.06** vs BM25 69.13 **[2H]**. Note this is a *document-length* description, not a gloss.
- **For:** DEPL builds label text as **label name + top-20 discriminative keywords mined from a BoW/SVM classifier**, truncated to 16–32 tokens; tail PSP@1 on Wiki10-31K 16.30 vs X-Transformer 13.52 **[2H]**. This is the recipe I'd try first — it expands the label with *document-register* vocabulary rather than dictionary-register.
- **Against:** PromptBERT's 500 definition-derived templates topped out at 64.75 vs 73.44 for hand-written **[V]**.
- **Against:** "naively using the label description for classification leads to poor performance on high cardinality tasks" — Banking77 (77 labels) naive 4.0 macro-F1 → restructured 73.4 **[2H]**.
- **Fragile:** Description Boosting (ACL Findings 2024) — "even a minor modification of descriptions can lead to a change in the decision boundary" **[2H]**.
- **Training on descriptions ≠ embedding descriptions:** LabelDescTraining reports 17–19% absolute over zero-shot **[2H]**, but that's finetuning on label-description data, a different intervention from concatenating a gloss at index time.

## B. Verdict

**Neither of your two numbers is diagnostic. As stated, both are consistent with a completely healthy embedding space.**

**On effective dim 43/768.** Rudman et al. measured IsoScore **< 0.18 for every contextual embedding model they tested** [V], and GPT-2 doesn't isotropically use even one dimension. 43/768 = 0.056 is inside the normal band. Worse for the pathology reading: Mickus et al. show IsoScore is *anti*-correlated with cluster quality at r = −0.808 to −0.978, ρ below −0.998 [V]. A 513K controlled vocabulary with dense subdivision families should be strongly clustered, and therefore should score low. **This number is close to uninformative.** (Caveat: unless you computed it as IsoScore specifically, the comparison is loose — IsoScore's own paper shows VarEx, MLE-intrinsic-dimension, and partition score each fail at least one basic invariance test.)

**On the 0.029 margin.** Two independent problems.

First, raw cosine gaps are dominated by the mean vector. IsoScore's rotation test [V] shows one point cloud reading 0.990/0.968/0.981/0.993 in average-random-cosine purely as a function of rotation, while the actual variance structure never changes; zero-centering drives average random cosine to 0 with no change to the variance distribution. An uncentered cosine gap is not a stable quantity.

Second — and this is the bigger issue — **you are comparing across two different distributions.** "Best concept↔segment" and "random concept↔concept" are cross-type and within-type similarities respectively. BLISS measured exactly this in CLIP: text↔text peaks around **0.75** while image↔text peaks around **0.25** [2H], a 3× offset that is pure representation-register, carrying zero information about relevance. If your concepts are short, boilerplate-wrapped strings and your segments are prose, concept↔concept will sit high and concept↔segment will sit low *by construction*. The correct null is **cos(segment, random concept)**, not cos(concept, concept).

**Which hypothesis do I actually favour?** Fixable text/model problem, roughly 70/30 — but that's a prior, not a measurement, and E2 below settles it. The reasons to lean that way are all first-hand: SentBERT vs MPNet differ by 132× on P@1 over a 501K-label space [V]; template wrapper alone swings STS by 34.10 points [V]; hubness correction is worth +2 to +9 P@1 on short-surface-form retrieval for free [V]. Those are three large, cheap, untested levers.

The honest counterweight: at 2,367 concepts the best published system on a comparable thesaurus-tagging task reaches F1 0.377 [2H]. You have 200× the vocabulary. **Even a fully correct system will show small absolute margins**, so your success metric should be recall@k feeding a reranker, not top-1 cosine separation.

### Experiments that distinguish the two

Ordered by decisiveness per unit effort.

**E2 (do this first — it is the whole question).** Take segments with human-assigned gold concepts. Report the **rank of the gold concept among all 513,236**. Nothing else you measure matters until you know this. Top-100 hit-rate materially above chance ⇒ the space works and you have a calibration/thresholding problem. Gold concepts ranked ~uniformly ⇒ the label space or the encoder is genuinely wrong. Requires zero model changes.

**E1 (fixes the broken statistic).** Recompute the null as cos(segment, *random concept*). Express the best match as a z-score against that null, and separately report best-vs-runner-up margin. I expect the 0.029 to change character entirely.

**E4 (lexical control).** BM25/TF-IDF over the same concept strings, same gold-rank protocol. MACLR precedent [V]: TF-IDF beat SentBERT, SimCSE and ICT on most datasets. If BM25 recall@100 ≫ dense recall@100, your vocabulary is fine and your encoder is the problem. This single control separates the hypotheses almost as cleanly as E2.

**E3 (boilerplate ablation).** Embed concepts with template, without template, and with the mean-concept-embedding subtracted (PromptBERT template denoising). Re-run E2 on each. Also report mean pairwise concept-concept cosine per variant. Given the 34.10-point template swing [V], this is high-expected-value and takes an afternoon.

**E5 (model swap).** Re-run E2 with an asymmetric instruction-tuned encoder, testing **both** orientations — segment-as-query/concept-as-passage and the reverse — since your setup inverts the usual short-query convention and nobody has benchmarked it. Budget for this being the largest single effect (132× spread in MACLR [V]).

**E6 (hubness).** Compute k-occurrence skewness on the concept side and the fraction of segments whose top-10 contains the same few concepts. Baseline for "normal": ~0.4% of queries per top hub [2H]. Then apply CSLS (K=10) and/or dual inverted softmax and re-run E2. Precedent +2.1 to +9.3 [V] and up to +7.6 [V].

**E7 (label-text enrichment, last).** On a sampled subset, compare surface form vs +synonyms/alt-labels vs +scope note vs +top-k document-mined keywords (the DEPL recipe). Evidence genuinely cuts both ways, so measure. My expectation, from the pattern across sources: **synonyms and document-mined keywords will beat dictionary-style definitions**, because they match the register of the segments you're matching against.

## C. URLs by claim

**Effective dimensionality / isotropy is not a pathology**
- IsoScore — https://arxiv.org/abs/2108.07344 · https://aclanthology.org/2022.findings-acl.262/
- Isotropy, Clusters, and Classifiers — https://aclanthology.org/2024.acl-short.7.pdf · https://arxiv.org/abs/2402.03191
- Ethayarajh 2019 — https://arxiv.org/abs/1909.00512 · https://aclanthology.org/D19-1006/
- Prompt-based embedding redundancy/ID — https://arxiv.org/abs/2506.01435
- On Isotropy Calibration — https://arxiv.org/abs/2109.13304
- Anisotropy Is Inherent to Self-Attention — https://arxiv.org/abs/2401.12143
- Anisotropy is *Not* Inherent to Transformers — https://aclanthology.org/2024.naacl-long.274/

**Templated boilerplate**
- PromptBERT — https://arxiv.org/abs/2201.04337 · https://aclanthology.org/2022.emnlp-main.603/
- BERT-whitening — https://arxiv.org/abs/2103.15316

**Dense retrieval over label text at scale**
- MACLR / EZ-XMC — https://arxiv.org/abs/2112.08652
- DEPL pseudo label descriptions — https://arxiv.org/abs/2204.00958
- AstroConcepts — https://arxiv.org/abs/2604.02156
- XMTC rank fusion — https://arxiv.org/abs/2507.03761
- LMTX — https://arxiv.org/abs/2406.09288

**Hubness**
- Radovanović et al. JMLR 2010 — https://jmlr.org/papers/v11/radovanovic10a.html
- CSLS / Conneau et al. — https://arxiv.org/abs/1710.04087
- DBNorm "Balance Act" — https://arxiv.org/abs/2310.11612
- Adversarial Hubness — https://arxiv.org/abs/2412.14113
- Reciprocal nearest neighbors for dense retrieval — https://arxiv.org/abs/2305.15720

**Instructions / asymmetry / dimensions**
- E5-mistral — https://arxiv.org/abs/2401.00368 · https://aclanthology.org/2024.acl-long.642.pdf
- E5 — https://arxiv.org/abs/2212.03533
- Qwen3-Embedding — https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- BGE v1.5 — https://huggingface.co/BAAI/bge-large-en-v1.5
- Nomic v1.5 — https://huggingface.co/nomic-ai/nomic-embed-text-v1.5
- EmbeddingGemma — https://huggingface.co/google/embeddinggemma-300m
- sbert symmetric vs asymmetric — https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html

**Label descriptions / glosses**
- BLINK — https://arxiv.org/abs/1911.03814 · https://aclanthology.org/2020.emnlp-main.519/
- MuVER — https://arxiv.org/abs/2109.05716
- LabelDescTraining — https://arxiv.org/abs/2305.02239
- Description Boosting — https://aclanthology.org/2024.findings-acl.562/
- Label Semantic Aware Pre-training — https://arxiv.org/abs/2204.07128
- Label interpretation learning for few-shot NER — https://arxiv.org/abs/2403.14222
- Retrieval Augmented Classification — https://arxiv.org/abs/2501.12332
- SapBERT — https://aclanthology.org/2021.naacl-main.334/
- BLISS similarity-bias correction — https://arxiv.org/abs/2407.17083

## D. Could not verify / corrections

**Two summarizer errors I caught by reading the primaries:**

1. **Fabricated table structure.** The summarizer reported Conneau et al. Table 2 as "Supervised Procrustes: NN 33.8, ISF 43.1, CSLS 44.9." That structure does not exist. Table 2's columns are P@1/P@5/P@10 for English↔Italian; 33.8 is Mikolov et al. 2013b, 43.1 is Smith et al. 2017, 44.9 is Procrustes-CSLS. It invented an NN/ISF/CSLS breakdown. (The Table 1 numbers it gave were real but silently drawn from the *unsupervised* Adv block while implying the supervised one.)
2. **Material omission.** Its MACLR summary dropped **MPNet** entirely and concluded "dense retrieval methods significantly underperform TF-IDF at extreme scale." With MPNet restored, the opposite is closer to true — MPNet beats TF-IDF on P@1 on all four datasets. Had I shipped that, the report's central recommendation would have been wrong.
3. **Misattribution** (noted earlier): "Anisotropy is Not Inherent to Transformers" is Machina & Mercer, not Rudman. Separately, "Isotropy, Clusters, and Classifiers" is Mickus, Grönroos & Attieh — also not Rudman, despite being a response to his metric.

**Unverified [2H] claims that carry weight** — treat as leads, not evidence: the prompt-based IsoScore range (0.0052–0.2112); BLINK's 82.06 R@64; DEPL's PSP numbers and 16–32-token construction; AstroConcepts' F1 0.377; BLISS's 0.75-vs-0.25 and AUROC deltas; all Matryoshka-by-dimension tables; Qwen3's 1–5%; the natural-hub 102/25,000 baseline; BERT-whitening's 59.04→68.19.

**Genuinely not found:**
- No study benchmarking **long-document-as-query against short-label-as-corpus**. Your orientation inverts the standard asymmetric convention and I could not find it measured.
- No measured guidance on **embedding dimension conditioned on input length**.
- No controlled ablation of **surface-form vs surface+definition** at index time in a dense retriever over a large controlled vocabulary. The closest is PromptBERT's definition-template result [V], which is suggestive but a different task. This is the specific gap E7 fills.
- No 2023–2026 hubness-reduction work targeting **text** dense retrieval specifically; everything current is cross-modal.

**Process limits:** The research tooling reached its search budget partway through, which cut short targeted searching for hubness in text retrieval, XMC label augmentation, and biomedical definition ablations.

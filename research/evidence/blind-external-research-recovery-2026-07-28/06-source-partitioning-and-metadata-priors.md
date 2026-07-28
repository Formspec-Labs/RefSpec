# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

## Bottom line

**No published system hard-partitions a large controlled vocabulary by source metadata.** The closest real analogue — the journal-MeSH mask — is not a journal filter. It is a *union* of a journal-derived set with a 1000-nearest-neighbor-derived set, constructed explicitly so that recall cannot be lost. Every other production or published system I could verify uses source metadata as a **soft feature**, or uses it to route *documents* rather than to restrict the *vocabulary*. The one place where restriction is standard (top-down hierarchical classifiers) is also the place where error propagation is the acknowledged failure mode.

Separately, the evaluated Federal Register corpus indicates that **agency scoping is contraindicated by the Federal Register's own index terms** (details in §5).

---

## 1. Journal-conditioned MeSH indexing — verified mechanism, and it is not what it's usually described as

### KenMeSH (ACL 2022) — verified from the published PDF
https://aclanthology.org/2022.acl-long.210/ · https://aclanthology.org/2022.acl-long.210.pdf · https://arxiv.org/abs/2203.06835

I extracted the PDF text rather than trusting a summary. What it actually does:

1. Journal set: `P(Li|Jj) = C(Li∩Jj)/C(Jj)`, then `Mj = {Lk | P(Lk|Jj) > τ}`, with **τ = 0.5**.
2. kNN set: documents embedded as IDF-weighted word-embedding sums; `Ma` = union of gold MeSH terms of the **K = 1000** nearest training abstracts.
3. **Final mask `M = Mj ∪ Ma`** (their Eq. 10) — a binary vector applied as `Hmasked = Hlabel ⊙ Mvec` inside label-wise attention.

The paper states verbatim: *"With τ = 0.5 and K = 1000, all of the gold-standard MeSH labels are guaranteed to be in the mask."*

**This is the single most important finding for you.** A τ of 0.5 means a MeSH term only enters the journal set if it appears in **more than half** of that journal's articles — that is a tiny set of near-universal terms. The recall is coming from the union of 1000 neighbours' gold labels, not from the journal. The journal prior is a garnish on a kNN candidate generator.

Verified results (Table 1) and ablation (Table 4):

| | MiF | MiP | MiR |
|---|---|---|---|
| MTI | 0.390 | 0.379 | 0.402 |
| DeepMeSH | 0.639 | 0.669 | 0.612 |
| BERTMeSH (Full) | 0.685 | 0.713 | 0.659 |
| **KenMeSH (full)** | **0.745** | **0.864** | **0.655** |
| KenMeSH ablation (d), no masked attention | 0.674 | 0.806 | 0.579 |

Removing masked attention costs MiF −0.071, MiP −0.058, MiR −0.076.

Caveats you should hold onto:
- **The journal component is never ablated separately.** Ablation (d) removes the entire masked-attention module, conflating the mask, the kNN set, the journal set, and label-wise attention. There is **no published number for what a journal prior alone buys.**
- Ablation (c), removing the label-feature (GCN hierarchy) module, is far more damaging (MiF 0.554) than removing the mask. Hierarchy > mask.
- KenMeSH's headline MiP of 0.864 vs BERTMeSH's 0.713 at essentially equal recall is a suspiciously large precision jump for a paper whose mask is guaranteed to contain all gold labels on the evaluated set. I found no independent reproduction. A follow-on MSc thesis from the same lab (https://uwo.scholaris.ca/server/api/core/bitstreams/ce5751d7-1a87-4619-a4dd-981cdc837810/content) reuses KenMeSH but does not audit the mask.

### NLM MTI — journal routes documents, not vocabulary
MTI's pipeline is MetaMap Indexing + PubMed Related Citations (kNN) + ML check-tag classifiers → clustering/ranking. "Journal Descriptor Indexing" maps text to **120 broad Journal Descriptors** manually assigned to MEDLINE journals, and is used for *subheading* and semantic-type disambiguation — not to restrict the ~30k main-heading space.

Where journal information *is* used operationally is **MTI First-Line (MTIFL)**: NLM designated ~230 journals where MTI output is good enough to be used as first-line indexing. Reported in "12 years on – Is the NLM medical text indexer still useful and relevant?" (https://pmc.ncbi.nlm.nih.gov/articles/PMC5324252/): MTI precision 0.3019 (2007) → 0.6003 (2014), F1 0.3810 → 0.5807; MTIFL 2014 F1 ≈ 0.7018. *(These figures are from a WebFetch summary of the article, not from extracted primary text — treat as indicative.)*

The pattern is: **journal is used to decide which documents to trust the automation on, not to shrink the vocabulary.** That is a much better-evidenced use of your agency field than candidate scoping.

### MATCH (WWW 2021) — the cleanest measurement of what venue metadata is worth
https://arxiv.org/abs/2102.07349 · https://keg.cs.tsinghua.edu.cn/yuxiao/papers/WWW21_Zhang_match.pdf

Verified from extracted PDF. Metadata (author, **venue**, references) is used as **soft embeddings pre-trained into the same space as text**, never as a filter. PubMed dataset: 898,546 docs, 17,693 MeSH labels, **150 venues**.

| PubMed | P@1 | P@3 | P@5 |
|---|---|---|---|
| MATCH-NoMetadata | 0.9153 | 0.7408 | 0.6080 |
| **MATCH (full)** | **0.9168** | **0.7511** | **0.6199** |

All metadata together buys **+0.15 points P@1 (not statistically significant), +1.0 P@3, +1.2 P@5** on MeSH. Venue is the most useful of the three, but the paper is explicit about *where*: venue helps most at k=1 because venues indicate **coarse** categories, and *"venues are less beneficial to the prediction of fine-grained categories… but authors and references may provide such signals."*

**This directly undercuts your hypothesis.** A 513k-concept vocabulary is overwhelmingly fine-grained. The one paper that isolates venue's contribution finds it helps exactly where you don't need it.

---

## 2. Per-collection vocabularies in library/government practice — yes, but split by *vocabulary and language*, not by source

**Annif / Finto AI (National Library of Finland)** — https://annif.org/, https://www.jlis.it/index.php/jlis/article/view/437 (PDF extracted and verified).

- Annif's unit of configuration is a **project = (indexing vocabulary, language, backend)**. Endpoint selection at inference is *"chosen based on the text language and the indexing vocabulary"* — language and vocabulary, **not collection or publisher**.
- Measured: mainly F1@5. Best scores 0.6–0.7 on Swedish JYU theses, but the authors themselves discount these as *"unrealistically good"* due to train/test document reuse. **Excluding those, "we have reached F1 scores ranging between 0.3 and 0.5."** That is the honest production number for a ~30k-concept vocabulary with clean library text.
- Yle (Finnish broadcaster) runs a **separate custom vocabulary and corpus**, retrained weekly — an organization-level vocabulary, not a metadata-conditioned partition of a shared one.

**German National Library (DNB)**: separate models per *target vocabulary* (Omikuji for DDC, MLLM+Omikuji ensemble for GND), not per collection. https://swib.org/swib21/slides/03-02-uhlmann.pdf

**SemEval-2025 Task 5 (LLMs4Subjects)**, GND over TIBKAT: https://arxiv.org/abs/2504.07199. The organizers offered `all-subjects` (204,739 subjects) and an optional `tib-core` (79,427 subjects, 14 technical domains). This is the closest thing to a curated collection-scoped subset in the wild — and note it is **curated once by librarians for a whole library**, not derived per-record from metadata. Reported: no participating system partitioned the vocabulary by domain; **no system trained per-domain models.** Top Recall@5 on all-subjects ≈ 0.49 (Annif). *(WebFetch summary; unverified against the primary tables.)*

**Verdict on §2: the honest answer is "no one does metadata-conditioned vocabulary partitioning."** Institutions split by vocabulary, language, and target scheme. Where a subset exists, it's a hand-curated core, not a routing function.

---

## 3. Hierarchical / two-stage routing

**EuroVoc.** The most-cited paper here (Exploiting EuroVoc's Hierarchical Structure, CoopIS 2019, https://penni.wu.ac.at/papers/Coopis%202019%20Exploiting%20EuroVoc's%20Hierarchical%20Structure%20for%20Classifying%20Legal%20Documents.pdf) is **routinely mis-cited as evidence for two-stage routing. It is not.** Verified from the extracted PDF: it re-labels the same documents at three granularities and trains flat classifiers at each.

JRC-Acquis, best model (fast.ai LSTM), P/R/F:

| Granularity | #labels | F |
|---|---|---|
| Full descriptors | 3,563 | 0.58 |
| Top terms | 489 | 0.67 |
| Microthesauri | 126 | 0.74 |

That only says coarse labels are easier to predict than fine ones. It contains **no** measurement of predicting the domain first and then restricting descriptors. I could not find a paper that measures the EuroVoc domain→descriptor cascade against a flat baseline. **If someone tells you EuroVoc proves two-stage routing works, ask for the citation — I could not find it.**

**Learned label partitions (the distinction you flagged is real and important).** Parabel (https://dl.acm.org/doi/fullHtml/10.1145/3178876.3185998) and Bonsai (https://arxiv.org/abs/1904.08249) partition the label space, but the partition is **learned from label co-occurrence in the training data**, and the acknowledged cost is *"error propagation in the tree cascade,"* worst on tail labels. Bonsai's entire contribution is to *weaken* the partitioning (fan-out ≥100, shallow, unbalanced) because Parabel's aggressive binary partitioning hurt.

**No paper I found shows a metadata-derived partition beating a learned one.** The field's trajectory is the opposite: away from hard, deep partitions toward shallow/soft ones. The HMTC survey (https://arxiv.org/abs/2307.16265) states plainly that in top-down local classifiers *"errors at higher levels propagate to lower levels, potentially amplifying misclassification rates"* — though it gives no quantified magnitude, which is itself telling.

---

## 4. Facet decomposition — essentially no evidence

I found no study that retrieves each facet in a separate embedding space and measures it.

- **LCSHBench** (2026, https://arxiv.org/abs/2606.04382, https://arxiv.org/html/2606.04382v1) reports composition by heading type (topical 65.9%, geographic 17.4%, name 14.3%, genre/form 2.2%) and slices *scores* by type, but **retrieves all facets jointly from one pool**.
- The **DNB GND-204K benchmark** (2026, https://arxiv.org/abs/2607.14882) has six entity types (94,362 subject headings, 44,998 persons, 22,806 corporate, 24,359 geographic, 16,282 works, 1,249 conferences) and explicitly says it *"makes the simplifying assumption to treat all entity types of the GND as the same"*, flagging this as a known limitation since *"named entities are linguistically different from subject headings."* **They identify faceted decomposition as an obvious unexplored improvement and do not do it.**

So: facet-split retrieval is an acknowledged gap, not a validated technique. If your 513k vocabulary mixes entity-like and topic-like concepts, splitting *those* is better motivated by this literature than splitting by agency — but it is unvalidated.

---

## 5. What breaks with agency scoping — I measured this on your actual corpus

I queried the Federal Register API directly (https://www.federalregister.gov/api/v1/documents.json).

**(a) Joint rulemaking is real but small.** 1,000 sampled 2025 final rules (of 2,441). Collapsing sub-agencies to their parent department:

| distinct top-level agencies | rules | share |
|---|---|---|
| 1 | 984 | 98.4% |
| ≥2 | 16 | **1.6%** |

The recurring joint clusters are exactly the ones you'd predict: Treasury/OCC/Fed/FDIC/CFPB, DoD/GSA/NASA/OMB (FAR Council), CFTC/SEC, DHS/DOJ, EPA/NOAA. Note that raw agency counts look like 66.8% multi-agency — that's an artifact of parent+sub-agency pairs (e.g. "Agriculture Department" + "Agricultural Marketing Service"). **If you scope by agency, collapse to the parent or you will fragment your own partition.**

**(b) Cross-cutting topics are the real killer.** 5,000 unique 2024–2025 final rules, 3,680 carrying the Federal Register's own CFR index terms, 669 distinct terms:

| distinct top-level agencies using the term | terms | share |
|---|---|---|
| 1 | 237 | 35.4% |
| 2 | 140 | 20.9% |
| 3 | 86 | 12.9% |
| 4 | 51 | 7.6% |
| 5 | 47 | 7.0% |
| ≥2 | **432** | **64.6%** |

**90.0% of all topic-term assignments land on terms shared by two or more agencies.**

Most cross-cutting terms: Administrative practice and procedure (60 agencies, 974 uses), Reporting and recordkeeping requirements (46 agencies, 1,851 uses), Penalties (38), Incorporation by reference (21 agencies, 1,288 uses), Intergovernmental relations (18 agencies, 463 uses), Individuals with disabilities (18).

The agency-exclusive third of the vocabulary carries only ~10% of the labeling volume. **Agency scoping would prune the part of the vocabulary that is almost never used and keep the part that is genuinely ambiguous.** This is the empirical case against your hypothesis, measured on the government's own controlled index terms.

**(c) Hard filter vs soft prior — what the literature prefers.** Every verified system uses soft: MATCH (metadata as embeddings, +1 point), MTI (journal routes documents), KenMeSH (hard mask, but unioned with kNN so it cannot lose gold labels). I did **not** find a paper that explicitly frames and A/B-tests "hard metadata filter vs soft metadata reranking" — that comparison appears not to exist in the literature. The strongest inference available is architectural: **the only hard mask in the literature was designed with a recall-preserving escape hatch.** If you do this, copy that design — union the agency-derived set with a global top-N dense/lexical retrieval, don't intersect.

---

## 6. Retrieval-side alternatives — this is where the evidence actually is

Your diagnostic (best concept only 0.029 cosine above the random-pair baseline) is a known, measured phenomenon, and the literature's answer is not partitioning.

**Dense retrieval genuinely fails on short label strings.** From SemSup-XC (ICML 2023, https://arxiv.org/abs/2301.11309), Table 2, verified from extracted PDF — zero-shot P@1 with bare class names:

| Method | EURLex-4.3K | AmazonCat-13K | Wikipedia-1M |
|---|---|---|---|
| **TF-IDF** | **44.0** | 18.7 | 14.5 |
| Sentence Transformer | 16.6 | 18.2 | 7.8 |
| SPLADE | 20.2 | 17.2 | 14.3 |
| MACLR | 24.9 | 36.0 | 29.8 |
| ZestXML | 24.7 | 15.6 | 15.8 |
| SemSup-XC | 44.7 | 48.2 | 36.5 |

On EURLex — the legal/regulatory-adjacent set — **plain TF-IDF beats every neural retriever, including SPLADE and sentence transformers, and ties the SOTA model.** Sentence-transformer zero-shot on the 1M-label set gets P@1 = 7.8. That is your degeneracy, measured.

SemSup-XC's own ablation: removing lexical matching from their hybrid costs **33 P@1 points on EURLex**. Removing the label hierarchy costs **26 P@1 points on AmazonCat** — more than removing descriptions (4 points).

**Label description generation: real, but NOT reliably positive.** This is the most important skeptical caveat in this section.

- SemSup-XC scrapes descriptions via DuckDuckGo ("what is \<class_name\>") plus heuristic spam filtering. It works *for them*.
- But feeding those same descriptions to other models **hurt badly** (same verified table): MACLR EURLex 24.9 → **20.9**; MACLR AmazonCat 36.0 → **18.4**; ZestXML AmazonCat 15.6 → **5.4**; GROOV AmazonCat 0.0 → 0.0. Only Wikipedia-1M improved (29.8 → 30.7).
- Their Table 5: **WordNet descriptions (42.8 EURLex / 47.2 AmazonCat) and GPT-3-generated descriptions (42.5 / 47.0) were both *worse* than web-scraped ones (44.7 / 48.2).** LLM-generated definitions were not the winner.
- Table 4: EDA augmentation helped EURLex (44.7 → 45.5) but hurt AmazonCat (48.2 → 47.8).
- Jina's practitioner writeup (https://jina.ai/news/rephrased-labels-improve-zero-shot-text-classification-30/) reports relative F1 gains from wrapping labels in sentences: AG News up to +19%, GoEmotions +35%, Twitter Eval +40% — but **TREC got −10% to −31%**, because its labels are opaque abbreviations whose semantics get "whitened out."

**Conclusion: label expansion is worth trying but must be A/B'd per vocabulary. It is not a free win, and the literature contains as many negative results as positive.**

**Reranking is the best-evidenced fix.** TartuNLP's SemEval-2025 system used bi-encoder retrieval + fine-tuned cross-encoder reranking and reported that this *"nearly doubles recall compared to using the bi-encoder alone"* over the 204k-subject GND. *(From a WebFetch summary of https://arxiv.org/html/2504.07199v2; I could not verify the exact figure against the primary system paper before the search budget ran out — treat the "nearly doubles" as directional.)*

**Calibrate your shortlist of 12 against LCSHBench.** ~515K LCSH+LCGFT labels — almost exactly your vocabulary size. Reported first-stage exact recall@k:

| retriever | R@10 | R@50 | R@200 |
|---|---|---|---|
| fine-tuned EmbeddingGemma-300M (LoRA r=16, MNRL) | 0.334 | 0.512 | 0.659 |
| text-embedding-3-large | 0.297 | 0.480 | 0.623 |
| text-embedding-3-small | 0.232 | 0.377 | 0.511 |
| stock EmbeddingGemma-300M | 0.166 | 0.283 | 0.407 |

*(WebFetch summary of https://arxiv.org/html/2606.04382v1; not verified from extracted primary text — and the paper also mentions an "exact-reachable ceiling of 41%" which I could not reconcile with a recall@200 of 0.659, so the denominator is ambiguous. Verify before quoting.)*

Even taken loosely: **at a 10-candidate shortlist over a ~515K vocabulary, a fine-tuned retriever recovers roughly a third of gold labels.** Your 12-candidate shortlist is very likely the binding constraint, and no amount of judge quality fixes a shortlist that doesn't contain the answer. Note also that their fine-tune **improved cross-lingual recall but degraded English recall@200 from 0.710 to 0.696** — a concrete instance of a prior helping in-distribution and hurting elsewhere.

**Supervised label partitioning still beats zero-shot retrieval at this scale.** The DNB GND-204K benchmark (https://arxiv.org/abs/2607.14882, July 2026; 951,104 training titles, 4,651 expert-annotated test docs) reports best F1* = 0.467 (XR-Transformer, titles) and 0.361 (DiSMEC++, fulltext); unsupervised embedding matching F1* 0.285/0.309; lexical MLLM AUCpr 0.148/0.268. LLM ensembles won on *graded* relevance (g-F1@5 0.576 vs 0.530) and on propensity-scored tail metrics, but cost 998 ms/record vs <1 ms, which the authors call *"infeasible for processing large amounts of data in daily library processes."* *(WebFetch summary; unverified against primary tables.)*

---

## Verification status

**Verified by extracting primary PDF text myself:** KenMeSH mechanism/τ/K/union/guarantee sentence and Tables 1 & 4; MATCH Tables 1–3 and the venue-ablation prose; SemSup-XC Tables 2/4/5 and ablation prose; EuroVoc CoopIS Tables 1–4; Annif/Finto JLIS F1 range and project-definition text.

**My own computation, reproducible:** all Federal Register agency and topic-term statistics (§5), from the public API, 2024–2025 final rules.

**WebFetch summaries only — not verified against primary tables, flag before quoting:** LCSHBench recall@k; DNB GND-204K numbers; SemEval LLMs4Subjects scores and the TartuNLP "nearly doubles recall" claim; MTI "12 years on" precision/recall/MTIFL figures; Jina rephrasing percentages.

**Could not find, despite looking:** any paper measuring a EuroVoc domain→descriptor two-stage cascade against a flat baseline; any explicit A/B of hard metadata filtering vs soft metadata reranking of candidate labels; any isolated ablation of a journal prior alone; any independent reproduction of KenMeSH; any facet-separated retrieval experiment.

**A note on method:** the research tooling reached its search budget partway through, so later sources were reached via the arXiv API, Europe PMC, and direct URL fetches. Two threads are consequently thinner than intended: practitioner/grey literature on hard-versus-soft candidate filtering, and FAST-specific facet work.

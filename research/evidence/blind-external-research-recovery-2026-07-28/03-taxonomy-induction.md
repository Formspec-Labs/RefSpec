# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

All load-bearing numbers were checked against primary text.

---

## Methodological note first

You were right to push. My first pass ran everything through WebFetch, which summarizes via a small model. That model **fabricated a TopicGPT results table** — it produced confident numbers (P=0.713, ARI=0.689, NMI=0.821 for Wikipedia; SeededLDA 0.621) that contradict the paper's own abstract. I caught it only because the abstract said something different. I then re-did the work: pulled the actual PDFs/HTML and read the tables myself. **Everything below marked "verified" I read in primary text.** Items I could not get to primary text are flagged explicitly in section (d). Assume the fabrication rate on unverified summarizer output is non-trivial.

---

# (a) Per-source findings

## 1. Taxonomy induction from a corpus with LLMs

**TnT-LLM (Microsoft, KDD 2024)** — *verified in primary text*
Two phases: LLM generates+refines a taxonomy zero-shot over minibatches; LLM then pseudo-labels data to train a lightweight classifier. Applied to Bing Copilot.
- Corpus: 9,592 conversations (Phase 1), 48,160 (Phase 2), after privacy/content filtering.
- **Taxonomy size: 10 intent categories and 25 domain categories.** This is the single most important caveat — TnT-LLM's headline result is about a ~10–25 label taxonomy, not thousands. Baselines (ada2/Instructor-XL + K-means) were forced to the same k.
- Coverage of generated taxonomies >99.5%.
- Human eval: **four of the authors** labeled 400 English conversations; each item by three annotators, majority vote, fourth as tie-breaker. Inter-rater agreement moderate (κ>0.4) on intent accuracy, domain accuracy, intent relevance; **fair only (Fleiss κ=0.379) on domain relevance**.
- So: the evaluators were the authors, the taxonomy was tiny, and agreement on "is this label relevant" was fair-to-moderate. It is a real, deployed, useful result — but it is not evidence that LLMs induce large vocabularies well.

**TopicGPT (NAACL 2024)** — *verified in primary text, after catching a hallucinated table*
Iteratively prompts GPT-4 to generate topics given document samples + previously generated topics, then refines (merges/drops), then GPT-3.5-turbo assigns.
- Datasets: Wiki (14,290 docs), **Bills (32,661 US Congressional bill summaries)**.
- Post-refinement harmonic mean purity P₁ was **0.74 on Wiki and 0.57 on
  Bills**, compared with 0.64/0.52 for LDA, 0.58/0.39 for BERTopic, and
  0.62/0.52 for SeededLDA.
- **This is the most decision-relevant number in the whole review.** On Wikipedia, TopicGPT beats LDA by +0.10. On Congressional bills — the closest public analogue to your corpus — it beats LDA by **+0.05 (0.57 vs 0.52)**, and ties SeededLDA. Legislative/regulatory text is where the LLM advantage largely evaporates.
- Semantic alignment (3 annotators mapping generated topics to ground-truth classes): misaligned topics **62.4% for LDA vs 38.7% unrefined / 30.3% refined TopicGPT**. Refinement helps, but ~30% of generated topics are still out-of-scope, missing, or duplicated.
- Cost: **$88 (Bills), $155 (Wiki)** — roughly $100/dataset.
- **Topic generation was too complex for every open-source LLM they tried except GPT-4.** Assignment worked with Mistral-7B at ≈6 points purity loss. Generation is the expensive part and it needs a frontier model.

**OLLM (NeurIPS 2024) — end-to-end ontology learning from a corpus** — *verified in primary text*
Closest thing to "build the taxonomic backbone from scratch." Fine-tunes an LLM to emit the relevant subgraph per document, sums and prunes.
- Wikipedia: 13,886 concepts / 28,375 relations / 362,067 docs. arXiv: 161 concepts / 166 relations / 126,001 docs.
- Table 1, Wikipedia: **Literal F1 — Memorisation 0.134, OLLM 0.093, Finetune 0.124, Zero-shot 0.007.** Fuzzy F1 — OLLM 0.915 (best). Cont. F1 — OLLM 0.500 (best). Graph F1 — OLLM 0.644 (best).
- arXiv: **Literal F1 — OLLM 0.040, One-shot 0.072, Memorisation 0.000.** Fuzzy F1 OLLM 0.570 (best).
- **The headline finding for you: Literal F1 is 0.09 and 0.04.** LLM-induced taxonomies essentially never reproduce a reference vocabulary at the string level. They produce a *semantically adjacent but lexically different* vocabulary. That is fine if you're minting a new vocabulary; it is fatal if you need to match an existing one.
- OLLM requires document→concept annotations to fine-tune. **You have no training data**, so OLLM as published is not directly available to you.
- Their related-work review says prior prompt-based ontology construction
  considered at most 1,000 concepts and relied on manual qualitative
  evaluation.

**Chain-of-Layer (CIKM 2024)** — *abstract verified; numbers not*
Important scoping correction: it induces a taxonomy from an already supplied
entity set. It is not corpus→taxonomy. It organizes that entity list top-down
with an Ensemble-based Ranking Filter to suppress hallucination. SOTA on four
benchmarks. **This solves the structuring problem, not the vocabulary-discovery
problem.**

**TaxoLLaMA (ACL 2024)** — *abstract verified*
LLaMA-2-7b + LoRA + 4-bit, instruction-tuned on WordNet hypernymy. 11 SOTA / 4 top-2 out of 16 tasks across Taxonomy Enrichment, Hypernym Discovery, Taxonomy Construction, Lexical Entailment. Again: operates over **given term pairs/lists**, not corpora. It is a hypernymy engine, useful for imposing hierarchy on a vocabulary you already have.

**TaxoAdapt (ACL 2025)** — *abstract verified*
Adapts an LLM-generated taxonomy to a corpus via iterative hierarchical
classification, expanding width and depth by the corpus's topical
distribution — the "LLM prior, corpus-corrected" pattern. The abstract reports
26.51% better granularity preservation and 50.41% better coherence than its
strongest baselines, but uses LLM judges and reports no human evaluation.
Discount accordingly.

**EvoTaxo (2026)** — *verified in primary text*
Builds/evolves taxonomy from Reddit streams. One genuinely transferable measured result: K-means silhouette on **raw posts 0.07 vs 0.45 on LLM-generated "action representations."** Don't cluster raw documents — have the LLM emit a normalized structured representation first, then cluster that. Sixfold clusterability improvement.

**Iterative Topic Taxonomy Induction / electoral advertising (2025)** — *via summarizer*
80.5M Meta political ads → filtered to 4,510 ads in 72 clusters → 14 topics. Human eval was **2 annotators × 10 ads**, Cohen's κ=0.66. Their method scored **2.8/5**, TopicGPT-style 2.7, BERTopic 1.2. Note 2.8/5 is a weak absolute score, and the eval is far too small to lean on. Ran on a local Llama-3.2-3B without GPU.

## 2 & 3. Open-vocabulary tagging → clustering/canonicalization, and "generate then map"

**This is the best-evidenced pattern in the review, and the evidence is genuinely encouraging — with one sharp caveat.**

**DNB-AI-Project (German National Library), SemEval-2025 Task 5** — *verified in primary text*
The canonical generate-then-map system. Because the LLMs do not know the
target vocabulary, the system first generates free keywords and then maps them
with a smaller embedding model.
Pipeline: **complete → map → summarise → rank → combine**. Ensemble of off-the-shelf LLMs × prompts with 8–12 few-shot examples generates free keywords; BGE-M3 embeddings nearest-neighbour map each keyword to a GND term; similarities summed and normalized across model×prompt combos; Llama-3.1-8B-Instruct rescores relevance 0–10; weighted combine. **No fine-tuning.**
- Result: **4th in quantitative all-subjects ranking, but 1st in the qualitative ranking by professional subject-indexing experts.**
- **This is your head-to-head answer.** Generate-then-map loses on reproducing the existing librarian labels and wins on what experts actually judge to be good indexing. The two metrics disagree, and the disagreement is the finding.

**AstroMLab 5 (2025) — open-vocab extraction → cluster → canonical ~10K vocabulary** — *verified in primary text*
The single closest precedent to what you are considering, at your exact target size.
- 408,590 arXiv astro-ph papers → structured summaries → **~10 concepts extracted per paper** (≈4M raw concept instances).
- Consolidation: concept + summary → detailed description → **text-embedding-3-large** → **K-means, k=10,000, cosine space** → merged into unified entries with synthesized descriptions.
- **They swept granularity in log space: 3,000 / 10,000 / 30,000 concepts, and chose 10,000 as the best balance.**
- **All 10,000 concepts manually reviewed by the author team**; one null concept removed → final **9,999**. 3.8M paper-concept associations; each concept appears in an average of 383 papers.
- Cost: **>$50,000 in API costs** for summarization of 408K papers, plus ~6,000 V100 GPU-hours of OCR. Note the vocabulary induction itself is a small fraction of this — the money went to summarizing 408K full papers. Your Federal Register corpus is smaller and already clean text.
- Honest limitation they state: they prioritized full-vocabulary review over paper-by-paper evaluation, and tell users to scrutinize.

**Hybrid framework, UNT Libraries (ASIS&T 2025) — generate-then-map, measured** — *verified in primary text*
LCSH vocabulary of **~318,500 unique terms** (MARC 650$a), all-mpnet-base-v2 embeddings; Llama-3.1-8b generates, then hallucinated terms are replaced by nearest valid LCSH term; a regression model predicts how many labels to emit.
- Llama-3.1-8b zero-shot, before → after vocabulary mapping: **recall 0.43 → 0.52**, precision 0.08 → 0.09, F1 0.135 → 0.155.
- CoT, before → after: **recall 0.51 → 0.63**, precision 0.04 → 0.05.
- Their summary: *"the recall increased from 43% (zero-shot baseline) to 63% (CoT with post-processing), and the precision improved from 8% ... to 0.26 (limit n with post-processing)."*
- **Constraining output count is what saves precision**: "Limit N" gives precision 0.26 / recall 0.29 at 3.14 terms per record, versus 14.89 terms unconstrained.
- Takeaway: **mapping-after-generation reliably buys ~9–12 recall points**, but precision against a 318K-term vocabulary stays in the 0.05–0.26 range no matter what. The vocabulary is the bottleneck, not the LLM.

**EDC — Extract, Define, Canonicalize (EMNLP 2024)** — *via summarizer, unverified numbers*
Three phases: open IE → schema definition → post-hoc canonicalization, with a trained Schema Retriever. Explicitly supports **self-canonicalization when no target schema exists**. Reported benchmarks WebNLG/REBEL/Wiki-NRE. This is the right architectural template for "let it generate freely, then canonicalize," but I did not verify its numbers.

## 4. LLM-assisted vocabulary pruning

**Thin literature. One strong datapoint, and a real gap.**

**WiKC — Refining Wikidata Taxonomy using LLMs (CIKM 2024)** — *via summarizer, key numbers unverified*
Zero-shot Mixtral-8x7B-Instruct (temp 0) applied in six operations: cut irrelevant links, resolve reversed links, reduce transitive links, merge equivalent classes, rewire, filter non-informative/rare classes.
- Reported: **4.1M classes → 17,000** (~99.6% reduction); links 4.8M → 20,000. Entity typing macro-average accuracy 70% vs 43% baseline.
- **Reported to have no human validation component.** Treat the magnitude as directional.

**Beyond WiKC, this category is close to empty.** I searched arXiv for ontology/vocabulary pruning with LLMs; the term "vocabulary pruning" in 2024–2026 is almost entirely **tokenizer** vocabulary pruning for speculative decoding and early-exit inference (EvoSpec, NanoSpec, Dynamic Vocabulary Pruning) — a completely different problem. **There is no established, well-measured method for LLM-shrinking a controlled vocabulary to a domain subset.** If you do it, you are not following a paved road.

**Ontology matching / OAEI**: the OAEI does not have a headline "LLM track" per se; LLM systems compete within existing tracks. "LLMs as Oracles for Ontology Alignment" (EACL 2026) uses LLMs only to adjudicate **high-uncertainty correspondences** with a human in the loop, and reports **top-2 overall in the OAEI 2025 bio-ml track**. The design lesson is the transferable part: use the LLM as a selective adjudicator on the uncertain slice, not as a bulk matcher. LLMs4OL 2025 concluded hybrid pipelines (commercial LLM + domain-tuned embeddings + fine-tuning) performed best; I could not extract per-task scores.

## 5. Human-in-the-loop: what review actually looks like

Concrete, verified throughput figures across the literature — these are strikingly small:

| Study | What humans reviewed | Who |
|---|---|---|
| AstroMLab 5 | **All 10,000 concepts** (full vocabulary), found 1 defect | Author team |
| TopicGPT | 6 topic-list mappings each (lists of ~31–123 topics) | 3 (1 author + 2 unpaid external) |
| TnT-LLM | 400 conversations, 3 annotators each | **4 of the paper's authors** |
| SemEval-2025 Task 5 | **122 records**, top-20 predictions each, labeled Y/I/N, over ~3 weeks | Professional subject specialists |
| Electoral ads | 10 ads each | 2 graduate students/faculty |

**The consistent pattern: reviewing a *vocabulary* is cheap and is done exhaustively; reviewing *assignments* is expensive and is done on tiny samples.** AstroMLab reviewed 100% of a 9,999-concept vocabulary and considered that the higher-value use of human time than per-document checking. That is directly encouraging for your plan — a ~5K vocabulary is a reviewable artifact for a small team; 513,236 concepts is not.

Also verified, from the LC-adjacent literature: the Chow/Kao/Li ChatGPT LCSH experiment cost **~$0.25 and 3 minutes of AI processing for 30 documents**, and their framing is the operative one — refining an imperfect AI suggestion is *"less daunting than constructing new subject headings from scratch."*

## 6. Library/GLAM and government-information communities

This is the community that has actually run your experiment at your scale, and the results are sobering.

**SemEval-2025 Task 5 / LLMs4Subjects** — *verified in primary text*
TIB (German National Library of Science and Technology) open-access catalog. **GND vocabulary: 204,739 subjects (all-subjects), 79,427 (tib-core).** 123,589 records; 81,937 train / 13,666 dev. 33 teams registered, 14 submitted. Qualitative evaluation on **122 records** by subject specialists labeling Y (correct) / I (irrelevant but technically valid) / N (incorrect).
- **Winner of the quantitative all-subjects track was Annif — a traditional XMTC toolkit** (Omikuji Bonsai, MLLM, XTransformer), with LLMs used only for translation and synthetic training data. Verified scores: Annif F1@5 **0.3432**, avg recall 0.6295 (1st); DUTIR831 0.3346 / 0.6045 (2nd); RUC Team 0.3015 / 0.5856 (3rd).
- LLM synthetic data contributed only **~+0.03 nDCG**, with diminishing returns after the first synthetic set. Omikuji Bonsai carried 47–87% of ensemble weight.
- **The most important finding in this review:** the Annif authors attributed
  the sub-0.35 F1@5 ceiling in part to inconsistent TIBKAT subject metadata.
  They also noted that consistently indexed datasets in prior experiments had
  exceeded 0.5 F1@5.
- Read that again in your context: with a 200K-term professionally-maintained vocabulary and 82K training records, **nobody broke F1@5 = 0.35**, and the practitioners attribute the ceiling to *label consistency*, not method.

**LCSHBench (2026)** — *verified in primary text*
The single most on-point source: **~515K LCSH+LCGFT labels — essentially identical in scale to your 513,236.** 22,346 books, 15 languages, Harvard/Columbia/Princeton.
- Concordance over **465,187 works** cataloged by all three: **93.3%** shared
  a concept-level heading, but only **39.4%** had identical heading sets.
- Human agreement reference: **a cataloger reproduces 86.9% of peer-consensus headings exactly and 93.0% at concept level.**
- **Open-vocabulary generation (Task A): best LLM F1 = 0.161 exact, 0.384 concept. Selection over a retrieved pool: 0.118 exact, 0.318 concept.** Retrieval recall@200: fine-tuned EmbeddingGemma-300M 0.659 vs text-embedding-3-large 0.623.
- The authors diagnose the exact-vs-concept gap as disagreement about
  granularity rather than topic. The models find the right subject and the
  wrong string.
- **Note this cuts against generate-then-map on this benchmark**: free generation (0.161/0.384) scored *higher* than selection over a retrieved pool (0.118/0.318). Combined with DNB-AI's split result, the honest read is that generate-then-map wins on human-judged quality but there is no clean, consistent win on reference-matching metrics.

**Tang & Jiang, "Better Recommendations" (2025)** — *verified: this is a review/position paper with NO original evaluation.* I checked; it reports no experiment of its own. Its proposed three-stage LOC-ID-validation solution is a **proposal, not a measured result.** Its secondary citations: 26–35% alignment between AI-generated and human-assigned LCSH; only ~half of ChatGPT-generated headings were both valid LCSH and sufficiently specific (Chow/Kao/Li); LC's own ML trial reached **~35% F1** for LCSH assignment and *"no single model hit the desired 95% accuracy threshold."* Expanding training to ~100,000 records improved accuracy — "fine-tuning needs very large, representative samples to capture a vocabulary as extensive as LCSH." Notably, **Chow has a RAG-based experiment specifically for recommending FAST** — directly relevant given FAST is 85.8% of your vocabulary.

**A Skill-Based Agentic Pipeline for LC Subject Indexing (2026)** — *via summarizer*
Decomposes indexing into conceptual analysis → quantitative filtering (20% Rule, Rule of Three) → authority validation → MARC synthesis. Claims "conceptual overlap on over half of all heading comparisons" — **but the evaluation corpus is 10 titles and it reports no precision/recall/F1.** Effectively an anecdote; I would not cite it as evidence.

---

# (b) Verdict

**Inducing a fresh ~2–10K concept vocabulary from your regulatory corpus with an LLM is a well-supported move in 2026 — and it is better supported than the alternative you're currently running.** But the support comes from a different place than the taxonomy-induction papers, and three of your framing assumptions need correcting.

**Why it's the right call:**

1. **Your real problem is measured, and it's the vocabulary, not the tagger.** SemEval-2025 is the closest analogue that exists: 200K-term professional vocabulary, 82K training records, 14 teams, and **nobody exceeded F1@5 = 0.35** — with the practitioners explicitly attributing the ceiling to label inconsistency. LCSHBench, at 515K labels (your exact scale), shows professional catalogers agree on the *exact heading set* only **39.4%** of the time while agreeing on the *topic* **93.3%** of the time. A half-million-term vocabulary is intrinsically unable to support consistent assignment. You cannot engineer your way past this with a better retriever. And your vocabulary is worse than theirs: theirs was purpose-built and professionally maintained; yours is 85.8% library subject headings and 13.8% chemical names pointed at rulemaking documents, with 0.37% actually designed for the domain.

2. **The target size is empirically validated.** AstroMLab 5 swept 3,000 / 10,000 / 30,000 and landed on 10,000 for a 408K-document corpus. Your 2–10K instinct is right in the middle of the only published granularity sweep I found.

3. **The human review cost is the part everyone gets wrong, and it favors you.** A ~5K vocabulary is a *reviewable artifact* — AstroMLab's author team reviewed all 10,000 concepts and treated that as the highest-value use of human time. 513,236 concepts can never be reviewed by anyone. For a small team with no training data, moving the human effort from "audit per-document assignments forever" to "audit the vocabulary once" is the single highest-leverage restructuring available.

4. **No training data is a reason to induce, not a reason not to.** TnT-LLM, TopicGPT, and the DNB-AI system all run without fine-tuning. Conversely, the fine-tuning path is closed to you: LC's experience is that capturing an LCSH-scale vocabulary needs ~100K representative records you don't have.

**What to correct in your framing:**

- **Don't expect to keep string-compatibility with FAST.** OLLM's Literal F1 of **0.093 (Wikipedia) / 0.040 (arXiv)** is the clearest signal in the review: LLM-induced vocabularies are semantically adjacent and lexically disjoint from reference vocabularies. If any downstream consumer requires FAST URIs, induction gives you a *second* vocabulary plus a mapping problem, not a replacement. Decide this before you start.
- **Most "taxonomy induction" papers don't do what you need.** Chain-of-Layer and TaxoLLaMA take a **given entity set** and impose hierarchy. They are the right tools for *step 2* (organizing your induced concepts), not step 1. Only OLLM, TaxoAdapt, EvoTaxo and the AstroMLab-style pipelines go corpus→vocabulary, and OLLM needs training data.
- **Temper the expected gain.** TopicGPT beats LDA by +0.10 purity on Wikipedia but only **+0.05 on Congressional bills** (0.57 vs 0.52), tying SeededLDA. Legislative/regulatory prose is precisely where the LLM edge is thinnest. Your win will come from vocabulary *fit*, not from LLM magic.

**The architecture the evidence actually supports** (not the taxonomy-induction papers — the pipeline papers):

AstroMLab's shape, with EvoTaxo's representation trick and DNB-AI's serving path:
1. LLM emits ~10 free-text concepts per document (AstroMLab). Emit a *normalized structured representation* rather than raw text before clustering — EvoTaxo measured silhouette 0.07 → 0.45 from exactly this.
2. Embed concept **descriptions** (not bare labels) and K-means at your target k. Sweep k in log space; 3K/10K/30K was the published sweep.
3. Human-review the entire induced vocabulary once. This is tractable and is what the one successful precedent did.
4. Serve with generate-then-map (DNB-AI): LLM ensemble generates free keywords → embedding nearest-neighbour into your canonical set → aggregate → LLM reranker. **Constrain the number of emitted labels** — the UNT result shows precision 0.26 at 3.14 terms/record versus 0.05 at 14.89.

**Cost, concretely.** TopicGPT: ~$100/dataset for 14K–33K documents, GPT-4 for generation (no open-source model they tried could do generation) and a cheap model for assignment. AstroMLab: >$50K, but that was summarizing 408K full papers with OCR — your corpus is smaller and already clean text; the clustering/canonicalization step is cheap. Realistically budget **low thousands of dollars in API for induction over a Federal Register-scale corpus**, plus **the dominant cost: one focused human pass over ~5K concepts.** Call that a few person-weeks. That is a genuinely small price against a vocabulary that structurally cannot exceed F1@5 ≈ 0.35.

**The honest risk.** There is no published case of LLM vocabulary induction on US federal regulatory text — I searched and found none. The strongest domain-adjacent evidence (TopicGPT on Congressional bills) is also the weakest LLM-vs-baseline margin in the paper. And the one measured precedent at your target size (AstroMLab) reports *no* extrinsic quality evaluation of the vocabulary — only that it gives denser coverage than ADS keywords. **You would be the evaluation.** Build the induced vocabulary alongside the existing one and measure both on a held-out set you label yourself; LCSHBench's exact-vs-concept split (0.161 vs 0.384) is the right metric design to copy — score topic agreement separately from string agreement, or you will mistake granularity disagreement for error.

---

# (c) URLs grouped by claim

**Vocabulary scale is the binding constraint; no system exceeded F1@5 0.35 on a 200K vocabulary**
- https://arxiv.org/abs/2504.07199 · https://aclanthology.org/2025.semeval-1.328/ (task overview: GND 204,739 / 79,427; 123,589 records; 122 qualitatively evaluated)
- https://arxiv.org/abs/2504.19675 · https://arxiv.org/html/2504.19675v2 (Annif; F1@5 0.3432 / avg recall 0.6295; the "none above 0.35" quote and the >0.5 footnote)
- https://arxiv.org/abs/2508.15877 (Annif at GermEval-2025)

**Professional catalogers themselves disagree at 515K-vocabulary scale**
- https://arxiv.org/abs/2606.04382 · https://arxiv.org/html/2606.04382v1 (LCSHBench: 93.3% concept / 39.4% exact heading sets over 465,187 works; 86.9%/93.0% human reproduction; generation F1 0.161/0.384; recall@200 0.659 vs 0.623)

**LLM-induced taxonomies are lexically disjoint from reference vocabularies**
- https://arxiv.org/abs/2410.23584 (OLLM; Literal F1 0.093 Wikipedia / 0.040 arXiv; Fuzzy F1 0.915/0.570)

**LLM advantage shrinks on legislative/regulatory text**
- https://arxiv.org/abs/2311.01449 · https://aclanthology.org/2024.naacl-long.164/ (TopicGPT; P₁ 0.74/0.57 vs LDA 0.64/0.52; misalignment 30.3% vs 62.4%; cost $88/$155)

**Corpus→taxonomy induction at deployed scale, small taxonomies**
- https://arxiv.org/abs/2403.12173 · https://dl.acm.org/doi/10.1145/3637528.3671647 · https://www.microsoft.com/en-us/research/publication/tnt-llm-text-mining-at-scale-with-large-language-models/ (TnT-LLM; 10 intent / 25 domain; 9,592 + 48,160 conversations; coverage >99.5%; Fleiss κ 0.379–0.48)
- https://arxiv.org/abs/2309.13063 (Bing user-intent taxonomy, LLM + human-in-the-loop; 5 categories)
- https://arxiv.org/abs/2506.10737 (TaxoAdapt; +26.51% granularity / +50.41% coherence, LLM-judged)
- https://arxiv.org/abs/2603.19711 (EvoTaxo; silhouette 0.07 → 0.45)
- https://arxiv.org/abs/2510.15125 (electoral advertising; 2.8/5, κ=0.66, n=10)

**Structuring a given term list (not corpus induction)**
- https://arxiv.org/abs/2402.07386 · https://dl.acm.org/doi/10.1145/3627673.3679608 (Chain-of-Layer)
- https://arxiv.org/abs/2403.09207 · https://aclanthology.org/2024.acl-long.127/ (TaxoLLaMA)

**Open-vocab extraction → cluster → canonical ~10K vocabulary (closest precedent)**
- https://arxiv.org/abs/2511.12353 · https://arxiv.org/html/2511.12353v1 (AstroMLab 5; 408,590 papers; k=10,000; 3K/10K/30K sweep; full 10,000-concept manual review; >$50K API)

**Generate-then-map**
- https://arxiv.org/abs/2504.07199 §DNB-AI-Project + https://github.com/deutsche-nationalbibliothek/semeval25_llmensemble (complete→map→summarise→rank→combine; 4th quantitative, 1st qualitative)
- https://arxiv.org/abs/2507.22913 · https://arxiv.org/html/2507.22913v1 (UNT hybrid; ~318,500 LCSH terms; recall 0.43→0.52 and 0.51→0.63 from mapping; Limit N precision 0.26 @ 3.14 terms)
- https://arxiv.org/abs/2404.03868 · https://aclanthology.org/2024.emnlp-main.548/ · https://github.com/clear-nus/edc (EDC self-canonicalization)

**Vocabulary pruning**
- https://arxiv.org/abs/2409.04056 · https://dl.acm.org/doi/10.1145/3627673.3679156 (WiKC; 4.1M→17K claimed)

**Ontology matching with LLMs**
- https://arxiv.org/abs/2508.08500 (LLMs as Oracles; top-2 OAEI 2025 bio-ml)
- https://www.tib-op.org/ojs/index.php/ocp/article/view/2913 (LLMs4OL 2025)
- https://arxiv.org/abs/2409.14038 · https://arxiv.org/abs/2503.21813 (OAEI-LLM hallucination benchmarks)
- https://ceur-ws.org/Vol-4144/om2025-LTpaper3.pdf (GenOM)

**Library/GLAM position and review**
- https://arxiv.org/abs/2508.00867 (Tang & Jiang — review/proposal, no original evaluation; cites 26–35% alignment, ~half valid LCSH, LC ~35% F1, no model at 95%, Chow's FAST RAG experiment, $0.25/3min per 30 docs)
- https://arxiv.org/html/2605.03537v1 (skill-based LC indexing pipeline; n=10 titles)
- https://blogs.loc.gov/thesignal/2024/11/could-artificial-intelligence-help-catalog-thousands-of-digital-library-books-an-interview-with-abigail-potter-and-caroline-saccucci/
- https://www.loc.gov/librarians/controlled-vocabularies/

---

# (d) Could not verify

**Fabricated by the summarizer and corrected — flagging so it isn't reintroduced:** an initial WebFetch of the TopicGPT PDF returned a fully invented results table (Wikipedia P 0.713 / ARI 0.689 / NMI 0.821; LDA 0.412/0.289/0.521; SeededLDA 0.621/0.502/0.724; datasets "11,169" and "8,237" documents; costs "$12.47/$9.83"). **None of that is real.** The correct values are in section (a).

**Read only through the summarizer, not primary text — treat as directional:**
- **WiKC**: 4.1M→17,000 classes, 4.8M→20,000 links, entity typing 70% vs 43%, "no human validation." Never reached primary text (arXiv HTML 404s; ACM/ar5iv blocked or summarizer-only). The ~99.6% pruning figure is the single most quotable number in the pruning section and I could not confirm it.
- **EDC**: all F1 figures (WebNLG 0.794, REBEL 0.559, Wiki-NRE 0.693), schema sizes, and the Schema Retriever ablation (~0.04–0.06 F1). ar5iv-summarizer only.
- **Chain-of-Layer**: the four benchmark names and all scores. Abstract verified; results not.
- **SemEval-2025 leaderboard beyond Annif's own paper**: the per-team R@5/R@10 values and the qualitative Case-1/Case-2 P@5/R@5 figures. The overview PDF's tables extract as column-flattened numeric runs I could not reliably re-associate with team names. Annif's own reported scores (0.3432 / 0.6295) and the DUTIR831 / RUC values in Annif's table are verified.
- **LLMs4OL 2025**: no per-task scores or participant counts obtained.
- **"LLMs as Oracles"**: the top-2 bio-ml claim comes from the abstract; no F1/precision/recall figures obtained.
- **Skill-based LC pipeline**: "conceptual overlap on over half of all heading comparisons" — summarizer-only, and the paper reportedly gives no precision/recall/F1 at all. n=10 titles.
- **TaxoLLaMA**: which specific tasks were SOTA and the Taxonomy Construction F1 values. Only the 11/16 + 4/16 headline is confirmed.

**Claims I specifically retracted after checking primary text:**
- A summarizer told me the UNT paper reported LLMs generating out-of-LCSH terms **"approximately 92% of the time in zero-shot settings."** I searched the primary text; the "92" match was a bibliography page number. **I could not find that claim in the paper and am not asserting it.**
- The same summarizer reported UNT F1 dropping to 0.091 for "CoT + post-processing." The paper's own table shows CoT F1 (before) 0.074; I did not confirm 0.091.

**Searched for and did not find:**
- Any published LLM taxonomy/vocabulary induction work on **US federal regulatory corpora** (Federal Register, regulations.gov, Unified Agenda, public comments). The nearest analogues are TopicGPT's Congressional Bills and EuroVoc legal-document classification. If this exists, it isn't on arXiv under regulatory+taxonomy+LLM.
- Any **head-to-head controlled comparison of generate-then-map vs retrieve-then-judge** on the same corpus and vocabulary with the same base model. DNB-AI (4th quantitative / 1st qualitative) and LCSHBench (generation 0.161 > pool-selection 0.118) are the two closest, and they are not the same experiment and point in different directions.
- Any established method for **LLM-pruning a controlled vocabulary to a domain subset** beyond WiKC. The phrase "vocabulary pruning" in current literature almost universally means tokenizer pruning.

**Search budget note:** The research tooling reached its 200-call limit partway through, and the remainder used direct arXiv API queries and PDF extraction. Areas likely under-covered as a result: the DNB-AI system paper's own ablations, GermEval-2025 LLMs4Subjects, and non-arXiv GLAM venues (JLIS, ITAL, Code4Lib) where more LLM-plus-controlled-vocabulary position papers probably exist.

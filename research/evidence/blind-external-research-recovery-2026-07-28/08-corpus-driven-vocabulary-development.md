# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Recovered report

# Building a Controlled Vocabulary Bottom-Up From a Corpus: Research Findings

## Headline

The honest answer to "how do practitioners build a vocabulary bottom-up" is: **they extract candidates automatically, then throw away 90–95% of them by hand, and the surviving registry is one to two orders of magnitude smaller than a borrowed library vocabulary.** Nobody in the published literature has an automated pipeline that produces a usable registry without a human review queue. Every measured system tops out around 50–70 F1 on the extraction step and around 50% agreement on the "is this actually a concept?" step — including among humans.

---

## 1. Automatic Term Extraction (ATE): what the numbers actually are

### TermEval 2020 / ACTER shared task — the cleanest benchmark
**https://aclanthology.org/2020.computerm-1.12/** (verified, extracted from PDF)

Purpose-built gold standard: 119,455 term/NE annotations over 596,058 words → **19,002 unique annotations**, four domains, three languages. Heart-failure domain held out as test.

Best F1 across five participating teams:

| Track | Best team | P | R | F1 |
|---|---|---|---|---|
| English | TALN-LS2N (BERT binary classifier) | 34.8 | 70.9 | **46.7** |
| French | TALN-LS2N | 45.2 | 51.5 | **48.1** |
| Dutch | NLPLab UQAM | 18.9 | 18.6 | **18.7** |

Critical secondary findings:
- **43% of English gold terms are hapax** (appear once); another 15% appear twice. Only 6% appear >25 times. **Frequency-based methods structurally cannot find most of the vocabulary.** e-Terminology used a frequency threshold of 2 and therefore had 0% recall on hapax terms.
- 45% of gold terms are single-word; recall degrades sharply past 3 tokens.
- Paper's own conclusion: "there remains a lot of room for improvement in the field of ATE."
- On inter-annotator agreement: "*inter-annotator agreement is notoriously low and there is no consensus about an annotation protocol*."

### ATE survey (ACM Computing Surveys / arXiv)
**https://arxiv.org/abs/2301.06767** | **https://dl.acm.org/doi/10.1145/3787584** (Table 3 verified from PDF)

F1 on the ACTER heart-failure test set (EN/FR/NL, with named entities):

| Method | Type | EN | FR | NL |
|---|---|---|---|---|
| e-Terminology | statistical | 20.1 | 19.7 | 14.4 |
| NMF | statistical | 33.7 | 30.7 | 30.3 |
| RACAI | non-neural | 41.3 | — | — |
| **HAMLET** | feature-based supervised ML | **55.4** | **60.8** | **66.0** |
| XLM-R Token Classifier | supervised neural | 58.3 | 57.6 | 69.8 |
| XLM-R Token Classifier (cross-lingual) | supervised neural | **58.0** | **61.1** | **68.3** |
| Vanilla biLSTM-CRF | neural, no pretraining | 8.17 | 6.53 | 7.50 |

**Everything above ~50 F1 is supervised and needs annotated training data.** Purely statistical/unsupervised methods sit in the 14–41 range. This directly bites a team with no training data.

### LLM-based ATE (2025)
**https://aclanthology.org/2025.findings-acl.516/** | **https://arxiv.org/abs/2506.21222** (verified from PDF)

In-context LLM ATE with syntactic-similarity retrieval of demonstrations:

| Dataset | Best LLM ICL (Gemma-2 + FastKASSIM) | Fine-tuned RoBERTa-large |
|---|---|---|
| ACTER | F1 **60.2** | F1 **61.2** |
| ACL-RD-TEC 2.0 | F1 80.7 | F1 87.4 |
| BCGM | F1 53.8 (Mistral) | F1 88.5 |

So: LLM in-context ATE roughly matches a fine-tuned encoder on ACTER and is clearly worse elsewhere. **LLMs did not solve ATE.**

### What "is a term" even means — the agreement ceiling
**https://arxiv.org/abs/2309.00642** — de Paiva et al., "Extracting Mathematical Concepts with LLMs" (verified from PDF)

100 sentences from a category-theory corpus, 3 human annotators + ChatGPT, working from **shared written guidelines**:
- 327 concepts extracted in union; only **120 agreed on by all four = 37% full agreement** (~40% after filtering plurals/noise).
- Per-annotator counts: 206 / 199 / 194 (humans), 235 (ChatGPT pre-filter).
- **Human–human pairwise Jaccard: 0.75–0.80, and "they were not able to go higher."**
- **ChatGPT–human Jaccard: ~0.5 even after filtering.**
- ChatGPT missed 40 concepts all three humans agreed on (~12%), and produced junk like *approach, consequence, motivation, previous work, prove, result*.
- Authors' conclusion: LLMs "cannot at this time surpass human performance."

This is the most important number in the whole report: **the target itself is only ~78% reproducible between trained humans.** Any vocabulary-construction pipeline is building on that foundation.

### Human curation cost — the one real accounting I found
**https://arxiv.org/abs/2010.00860** — "Building Large Lexicalized Ontologies from Text: a Use Case in Automatic Indexing of Biotechnology Patents" (TyDI / VegA project) (verified from PDF)

- Corpus: **21,039 EPO patent documents** (title, abstract, claims)
- YaTeA extracted **65,529 term candidates**
- Team: **one plant-biology domain expert + one knowledge engineer**, working remotely in a shared tool
- Duration: **6 weeks** (described as "very short compared to our comparable previous developments" using spreadsheets + Protégé)
- Outcome: **21,960 (37%) terms validated, 10,603 (18%) deleted**, and **5,967 (10%) terms grouped into 2,680 synonym classes linked to 2,680 concepts**

**Net yield: 65,529 candidates → 2,680 concepts (~4%), for ~12 person-weeks.** Also note the hybrid pattern: they used **MeSH and AGROVOC only to structure the *highest levels*** of the hierarchy, deriving everything below from the corpus. That is the single most transferable design in this report.

Their described bottom-up workflow, in order:
1. Shallow non-semantic filtering (merge morphological variants → −11%, 7,403 terms; sort alphabetically to catch bad segmentation starting with `% [ "`; kill genre/rhetorical terms like *in addition, claim, main objectives*; kill over-general terms like *intensity, product, concentration*; sort by frequency and mass-invalidate hapax from bad POS tagging)
2. Topic-based exploration
3. Term validation + local modeling (topic-centered)
4. Global modeling / concept formalization (top-down)

### C-value/NC-value, TermSuite, TBX — status
- **C-value/NC-value** (Frantzi, Ananiadou & Mima) remains the canonical statistical multiword-term method: **https://link.springer.com/chapter/10.1007/3-540-49653-X_35**. ⚠️ **I could not verify its original reported precision figures** — the only figure surfaced was a search-snippet claim of "<2.5% recall decrease vs raw frequency," which I did not confirm in the source. Do not cite that. What *is* verified is that in the ACTER benchmark above, methods of this family land in the 14–41 F1 band.
- **TermSuite** (https://termsuite.github.io/): verified — spotting → morpho/syntactic/graphic/semantic/derivational variant detection → ranking by Weirdness Ratio and frequency; 6 languages (fr/en/ru/it/de/es); CLI, GUI, Java API. Latest version 3.0.10, copyright "University of Nantes 2015-2017." **No evaluation numbers published on the site, and it appears unmaintained.**
- **TBX** (TermBase eXchange, ISO 30042): ⚠️ **This research gathered nothing verifiable on it.** It appeared only as an export format in the EuroVoc paper. Treat as an interchange format question, not a methods question.
- **KeyBERT / YAKE / RAKE**: ⚠️ **I could not verify any benchmark numbers.** A search snippet cited F1@10 of 0.309 (YAKE) vs 0.319 (SBERT) on a social-media keyphrase task (https://arxiv.org/abs/2301.11508), but the PDF would not extract and **I am flagging this as unverified — do not cite it.** The general shape reported (RAKE/YAKE fast but weaker; embedding/POS-pattern methods like PatternRank better — https://arxiv.org/abs/2210.05245) is directionally consistent but unquantified here.

---

## 2. Taxonomy induction / ontology learning, including LLM era

### Chain-of-Layer (CIKM 2024)
**https://arxiv.org/abs/2402.07386** | **https://dl.acm.org/doi/10.1145/3627673.3679608** (verified from PDF — ⚠️ note: my first automated read of this paper produced a *hallucinated* results table; the numbers below are from direct PDF text extraction)

**Crucial caveat that is easy to miss: Chain-of-Layer does not build a vocabulary. It takes a *given entity set* and arranges it into a hierarchy.** The concept-discovery problem is assumed solved.

Dataset scale (avg sampled sub-taxonomy / full taxonomy):

| Dataset | #Concepts | #Edges | Depth |
|---|---|---|---|
| WordNet | 20.5 / 20.5 | 19.5 / 19.5 | 3.0 |
| Wiki | 102.6 / 252.0 | 101.8 / 255.0 | 2.2 / 3.0 |
| DBLP | 90.8 / 176.0 | 89.8 / 175.0 | 2.8 / 4.0 |
| SemEval-Sci | 114.0 / 429.0 | 113.0 / 451.0 | 7.2 / 8.0 |

Edge-F1, best method (CoL GPT-4, 5-shot):

| | Wiki | DBLP | SemEval-Sci |
|---|---|---|---|
| CoL (GPT-4) 5-shot | **96.43** | **47.96** | 51.59 |
| CoL-zero (GPT-4) | 91.15 | 37.81 | **52.44** |
| TaxonomyGPT (5-shot) | 87.98 | 25.97 | 38.01 |
| Graph2Taxo (supervised) | 36.52 | 35.37 | 46.87 |

Read this carefully: **Wiki scores 96 because Wikipedia's category graph is in the pretraining data. On genuine domain taxonomies (DBLP, SemEval-Sci) the state of the art is ~48–52 edge-F1.** And the authors explicitly had to sample 5 sub-taxonomies per dataset because of "scalability challenges" — **these methods do not run on a full taxonomy of even a few hundred nodes.**

### TaxoGen / HiExpan
⚠️ **I could not verify any numbers for these.** They are the canonical pre-LLM corpus-driven methods (TaxoGen: adaptive spherical clustering on term embeddings; HiExpan: task-guided hierarchical tree expansion, KDD 2018) and appear as baselines in later work, but an automated read produced fabricated figures which I discarded. Do not quote numbers for them from this report.

### OLLM — end-to-end ontology learning
**https://arxiv.org/abs/2410.23584** (verified from PDF)

Datasets built by the authors: **Wikipedia = 13,886 concepts / 28,375 taxonomic relations / 362,067 documents; arXiv taxonomy = 161 concepts / 166 relations / 126,001 documents.**

| Wikipedia | Literal F1 | Fuzzy F1 | Cont. F1 | Graph F1 |
|---|---|---|---|---|
| Hearst patterns | **0.003** | 0.538 | 0.350 | 0.544 |
| REBEL | 0.004 | 0.624 | 0.356 | 0.072 |
| Zero-shot prompt | 0.007 | 0.871 | 0.455 | 0.639 |
| Three-shot prompt | 0.031 | 0.880 | 0.475 | 0.622 |
| **OLLM** | **0.093** | **0.915** | **0.500** | **0.644** |

**Literal F1 = exact concept-label match. The best system gets 0.093.** Fuzzy/semantic F1 of 0.915 looks great and means almost nothing operationally: the induced labels are *about* the right things but are not *the same strings* as any target vocabulary. If your goal is a registry with stable IDs and stable labels, that gap is the whole problem.

Also: **OLLM requires document→concept annotations to train.** A team with no training data cannot use it. Cost was modest (12 A100-hours train + 7 inference).

### TaxonomyBuilder — corpus-derived taxonomy of AI skills (May 2026)
**https://arxiv.org/abs/2605.21029** (verified from PDF) — the closest published analogue to the team's situation

Pipeline: 590 curated domain keywords → keyword search over **~30M NLx job postings + 1.5M USAJOBS federal postings** → **5.58M candidate sentences** → filter to postings with ≥3 keyword hits → **251k (NLx) / 19k (USAJOBS) candidates** → 3-model embedding ensemble scores class-relatedness → percentile filtering → HDBSCAN (min cluster size 5) → LLM labels each cluster → recurse upward until <10 labels or depth 5.

Results across 12 configurations × 2 datasets:
- Best **domain coverage macro-F1 ≈ 0.67–0.70** (at τ=0.7), i.e. the taxonomy fails to cover ~1/3 of sentences an LLM judge calls AI-related.
- **LLM-as-judge Orthogonality (distinctiveness / non-overlap) scores 1.5–2.5 out of 5** across every configuration. The induced concepts overlap badly. This is the single most relevant failure mode for a retrieve-then-judge tagger.
- **"Less is more," statistically significant:** data augmentation *severely reduces* strict coverage (ANOVA F=40.81, p<0.001, η²=0.836) and label utilization (F=13.48, p=0.008). Stricter percentile filtering improves cluster fit, orthogonality, and label utilization. 22 of 28 best scores came at or above the 50th-percentile filter.
- Taxonomies built with the weakest (25th-percentile) filter **won zero LLM-judge categories.**

**Translation for the team: aggressively filtering the candidate pool beats enlarging it. This is the opposite of the instinct that produced a 513k borrowed vocabulary.**

### OntoLearner (July 2026) — the most damning meta-finding
**https://arxiv.org/abs/2607.01977** (verified from abstract fetch)

180 machine-readable ontologies across 22 domains, benchmarked with 22
retrieval models and 12 LLMs across term typing, taxonomy discovery, and
non-taxonomic relation extraction. The authors conclude that failure grows
with ontology complexity rather than model scale or architecture, and that
the main bottleneck is a mismatch between model representations and ontology
structure.

**Waiting for a better model will not fix this.**

### Others (abstract-level only — flagged)
- **OntoAxiom** (https://arxiv.org/abs/2512.05594): 17,118 triples / 2,771 axioms, 12 LLMs; subclass-axiom F1 ranges **0.218 (music ontology) to 0.642 (FOAF)**. ⚠️ abstract-level, not verified in full text.
- **TaxoAdapt** (https://arxiv.org/abs/2506.10737): claims **+26.51% path granularity, +50.41% coherence** over LLM-only and corpus-only baselines. ⚠️ **I could not verify what the baselines were or extract the results tables.** Treat the percentages as unanchored.
- **"Prompting or Fine-tuning?"** (https://arxiv.org/abs/2309.01715): reports prompting beats fine-tuning for taxonomy construction, **particularly with small training datasets** — relevant given no training data. ⚠️ abstract-level.

---

## 3. Free tagging first, then consolidation: how a candidate graduates

This is where the *real*, battle-tested answers are — and they are all **two-tier registries with an explicit staging area and a human queue.**

### MeSH — the two-tier model, quantified
**https://www.nlm.nih.gov/mesh/intro_record_types.html** | **https://arxiv.org/abs/2101.08293** (both verified)

- **Staging tier: >230,000 Supplementary Concept Records covering >505,000 SCR terms.** SCRs are created **daily** and distributed nightly Mon–Thu. Each SCR is linked to one or more Descriptors via the *Heading Mapped To* field — i.e. an SCR is a free-ish concept that is always *anchored* to a registered descriptor.
- **Registered tier: ~30,000 Descriptors (22,997 in 2005) + 77 Qualifiers.** Updated **annually**.
- Ratio: roughly **8 staged concepts per registered concept.**

Growth and provenance, 2006–2020 (Nentidis et al., verified):
- **6,915 new descriptors over 15 years** (~460/year) on a 2005 base of 22,997 = 30% growth; 23% of all current descriptors were introduced in that window.
- Provenance breakdown of those 6,915:
  - **~25% "Emersion"** — genuinely new concepts with no prior host
  - **~23% promoted Supplementary Concept Records** → Descriptors (this is literally the SCR→Descriptor graduation path, and it is *the largest explicit-promotion category*)
  - **~8%** promoted subordinate concepts of existing descriptors
  - **~44%** concepts previously covered *implicitly* by an existing descriptor — i.e. splitting an existing concept finer
- The 2006 spike of >900 new descriptors was "almost exclusively attributed to promoted SCRs," in a year NLM actively encouraged promotion. **Promotion is a deliberate, campaign-driven editorial act, not a threshold that fires automatically.**
- Recent cadence: **MeSH 2026 added 160 new descriptors and changed 42** (https://www.nlm.nih.gov/pubs/techbull/jf26/jf26_NLM_Classification_2026_WinterEd.html, verified).

**Design lesson: NLM lets the long tail live in a cheap, high-volume, daily-updated staging tier that is always anchored to the curated core, and promotes only ~100–200/year after editorial review. Three quarters of promotions are refinements of things already in the registry, not new territory.**

### EuroVoc — the closest peer to a regulatory-policy vocabulary
**https://aclanthology.org/2025.ldk-1.34/** (verified from PDF) | **https://op.europa.eu/en/web/eu-vocabularies**

| Feature | Quantity |
|---|---|
| Hierarchical levels | 8 |
| Domains | 21 |
| Micro-thesauri | 127 |
| **Preferred terms (concepts)** | **7,000+** |
| Non-preferred terms | 12,000 |
| Languages | 24 |
| Total terms (all languages) | 678,000 |
| Terms per language | ~24,000 |
| Hierarchical relations | 10,000 |
| Associative relations | 5,000 |
| Updates/year | 3–4 |

**EuroVoc indexes the entire legislative and policy output of the European Union with roughly 7,000 concepts.** Set that against a 513k borrowed vocabulary for US federal regulatory documents.

Graduation workflow (verified, and directly reusable):
1. Anyone may propose via a public CONTRIBUTE form or by emailing the Reference Data Team.
2. Reference Data Team compiles **candidates** — assigning each a domain, a micro-thesaurus, and an ISO-conformant definition.
3. Candidates live in a **dedicated "candidate scheme" in VocBench**, visible to all working-group members, who attach **editorial notes** (internal, never published) to argue for/against.
4. The Reference Data Team **convenes meetings** to evaluate each candidate and its properties. **On consensus** → forward to the inter-institutional committee. **Without consensus** → postponed for clarification, or rejected as irrelevant.
5. Inter-institutional committee (Council, Parliament, Court of Justice, et al.) gives final approval.
6. Only *then* does translation into 23 languages happen — the expensive step is deliberately gated behind approval.

**No frequency threshold anywhere.** The gate is a definition, a home in the hierarchy, and consensus among named reviewers.

### LCSH / FAST — literary warrant and cooperative proposal
- **SACO** (Subject Authority Cooperative Program): member institutions commit to an annual goal of **10–12 proposals each**; proposals are routed through LC's Regional and Cooperative Cataloging Division and **reviewed weekly** by the policy office. https://www.loc.gov/aba/pcc/saco/ (⚠️ loc.gov returned 403 to direct fetch; these details come from search results plus the Princeton SACO guidance page below.)
- Guidance on *when* to propose: https://static-prod.lib.princeton.edu/cams/katmandu/pcc/sacwhen.html (verified) — propose when the work "represents a new subject"; explicitly a **cost/benefit judgment**: "Decide on the usefulness of your heading and try to weigh it against the amount of time it will take you to establish it." **No numeric threshold. No "N documents required."**
- **FAST cannot mint its own headings.** New FAST terms must go via LCSH; LC publishes proposals for comment and the cycle takes ~1 month. The FAST user community has asked for more flexibility, but the shared LCSH vocabulary is treated as the point of the exercise. https://www.oclc.org/research/areas/data-science/fast.html, https://en.wikipedia.org/wiki/Faceted_Application_of_Subject_Terminology
- ⚠️ **I could not verify total LCSH heading counts or SACO approval rates** — loc.gov blocked every fetch.

**Relevant to the team specifically: FAST inherits LCSH's *library* literary warrant — established because books were cataloged about a topic. That warrant has nothing to do with what appears in Federal Register rules or docket comments. That is the mechanical reason a borrowed FAST vocabulary mismatches a regulatory corpus.**

### TopicGPT — the only paper with an explicit, published graduation threshold
**https://aclanthology.org/2024.naacl-long.164/** | **https://arxiv.org/abs/2311.01449** | code: **https://github.com/chtmp223/topicGPT** (verified from PDF)

Directly relevant because one of its two datasets is **Bills: 32,661 US congressional bill summaries** (110th–114th Congress), 21 high-level + 114 low-level human labels — a near-neighbour of the team's corpus.

The refinement step — this *is* the answer to "when does a free-text tag graduate":
1. **Merge:** SentenceTransformer embeddings; take all topic pairs with **cosine similarity ≥ 0.5**; feed the LLM five such pairs at a time and instruct it to merge near-duplicates where appropriate.
2. **Frequency floor:** track how often each topic was *generated*; drop any topic below a **removal threshold — set to 10 for Bills, 5 for Wiki.** The paper's own footnote: *"We recommend trying different thresholds to make sure that important topics are not removed."*

Effect of refinement on Bills: **79 topics → 24 topics.**

Quality (harmonic purity P1 / ARI / NMI, evaluated on 15,242 held-out Bills docs):

| Bills | P1 | ARI | NMI |
|---|---|---|---|
| TopicGPT refined (k=24) | **0.57** | 0.40 | 0.49 |
| LDA (k=24) | 0.52 | 0.32 | 0.46 |
| SeededLDA | 0.52 | 0.31 | 0.45 |
| BERTopic | 0.39 | 0.12 | 0.34 |

Human audit of topic misalignment (3 annotators, % of topics out-of-scope / missing / repeated):

| Bills | Out-of-scope | Missing | Repeated | **Total** |
|---|---|---|---|---|
| LDA (k=79) | 56.1 | 2.1 | 22.0 | **80.2** |
| TopicGPT unrefined (k=79) | 65.0 | 1.3 | 3.8 | **70.1** |
| **TopicGPT refined (k=24)** | 27.8 | 4.2 | 0.0 | **31.9** |

**Refinement cut misaligned topics from 70% to 32% and eliminated duplicates entirely.** It cost one missing topic ("Culture," present in only 23 of 32,661 documents).

Stability — and this is the part to be skeptical about:

| Bills setting | k | P1 vs ground truth | P1 vs its own default run |
|---|---|---|---|
| Default | 79 | 0.57 | — |
| **Different generation sample** | **73** | 0.57 | **0.67** |
| **Shuffled generation sample** | **118** | 0.55 | 0.70 |
| **Additional example topics** | **123** | 0.50 | 0.69 |
| **Out-of-domain prompts** | **147** | 0.55 | 0.69 |
| Re-running pipeline twice (identical) | 79 | — | 0.95 |

**Change the document sample and you get 73 vs 79 topics that agree with each other only 0.67. Change the prompt exemplars and you get 147. The induced vocabulary is a function of the prompt and the sample, not just the corpus.**

Other operational facts: generation used 1,000 sampled Bills documents; **new-topic discovery plateaued after ~600 documents.** Total cost: **$88 (Bills) / $155 (Wiki)** with GPT-4 generation + GPT-3.5 assignment. Notably, at the time, **"topic generation is too complex for all LLMs we tried other than GPT-4"** — assignment worked with Mistral-7B at ~6 points lower purity, but generation did not.

### EvoTaxo — streaming taxonomy with an explicit arbitration gate (March 2026)
**https://arxiv.org/abs/2603.19711** (verified from PDF)

Processes posts chronologically, converts each post into a *draft action* (`add_child`, `add_path`, `update_cmb`, …) rather than clustering raw posts, holds candidate edits in a pool, clusters them time-aware, and runs an **arbitration** step before any structural change lands. Each node carries a "concept memory bank" (definition + exclusion cues) to keep boundaries stable.

The ablation is the money table — it quantifies exactly what the review queue buys you:

| /r/opiates 2015–2024 | Nodes | Leaves | Leaf-assign entropy ↓ | Unclassified ↓ | NLI validity ↑ |
|---|---|---|---|---|---|
| **EvoTaxo (with arbitration)** | **25** | **19** | **0.79** | 0.22 | **0.83** |
| **— w/o arbitration** | **70** | **54** | **0.92** | 0.17 | 0.74 |

**Removing the gate nearly triples the vocabulary, degrades hierarchy validity, and muddies every leaf — while only marginally improving coverage (0.22 → 0.17 unclassified).** That is the borrowed-513k-vocabulary failure mode in miniature.

Comparative taxonomy sizes on the same corpora — note how small everything is: EvoTaxo 25–32 nodes, TnT-LLM 10–25, Chain-of-Layer 33–43, TaxoAdapt 71–73, from corpora of 8,582–18,394 posts. Token spend: 18–38M (EvoTaxo) vs 92–166M (TaxoAdapt).

LLM-judge reliability check against humans (n=30 each): exact agreement 0.67 / 0.70 / 0.57 for path granularity, sibling coherence, sibling separability; ±1 agreement 0.90 / 0.87 / 0.83. **LLM-as-judge for taxonomy quality is roughly two-thirds reliable at the exact level.**

### data.blog (Automattic) — a small but real practitioner writeup
**https://data.blog/2025/03/21/organizing-data-blog-content-via-nlp-and-llm/** (verified)

- Corpus: **100 blog posts**, ten years of organically-grown taxonomy
- **Reduced 150 tags → 50, and 20 categories → 10**
- Method: manual inspection for redundancy → SBERT embeddings for semantic similarity → Claude 3.5 Sonnet via Haystack with JSON-schema-validated output
- **Human curation: they reviewed every LLM suggestion and overruled Claude when it proposed a category supported by only a single post** — i.e. an ad-hoc document-frequency floor of >1, applied by a human
- Cost anecdote: $1 for 23 post-pair internal link suggestions
- **Measured outcomes: none yet.** They planned to track recirculation rate post-launch.

### Folksonomy → controlled vocabulary
Verified only at the level of well-established qualitative findings: tag frequency follows a **power law** — a handful of tags used constantly, the vast majority used once by one person; consolidation work (Guy & Tonkin 2006) is mostly mechanical normalization of singular/plural and spelling variants; tag clusters notoriously fail to gather all terms for a concept because different user groups use different vocabularies. See https://jodi-ojs-tdl.tdl.org/jodi/article/download/269/278 and https://arxiv.org/abs/cs/0701072. ⚠️ **No specific frequency threshold from this literature was verified.** The power-law shape is the operationally useful part: a document-frequency floor will remove most candidates and very little coverage.

---

## 4. LLM-as-labeler for open-set tagging, then clustering/canonicalization

### TnT-LLM (Microsoft, KDD 2024) — the production case
**https://arxiv.org/abs/2403.12173** (verified from PDF)

Production setting: **user intent and conversational domain labeling for Bing Consumer Copilot.** 10 weeks of conversations (Aug–Oct 2023). After privacy and content filtering: **9,592 conversations for Phase 1** (taxonomy generation, 60/20/20 split), **48,160 for Phase 2** (labeling).

Method — "zero-shot multi-stage reasoning, inspired by stochastic gradient descent": summarize a **minibatch of 200** conversations → propose/update the label taxonomy → review → repeat. Then Phase 2 uses the LLM as a **data augmentor** producing pseudo-labels that train a lightweight classifier for full-corpus deployment.

**Two facts that matter enormously:**
1. **The taxonomy size was prescribed, not discovered: "we instruct our LLMs to generate 10 intent categories and 25 domain categories."** Microsoft did not ask the LLM how many concepts exist. They told it.
2. **Human agreement on whether a generated label is even correct is only moderate:**

| Metric | Use case | Human overall (Fleiss κ) | Human avg pairwise (Cohen κ) | GPT-3.5 vs human | GPT-4 vs human |
|---|---|---|---|---|---|
| Accuracy | Intent | 0.476 | 0.477 | 0.376 | 0.558 |
| Accuracy | Domain | 0.478 | 0.484 | 0.260 | 0.578 |
| Relevance | Intent | 0.466 | 0.481 | 0.333 | 0.520 |
| Relevance | Domain | 0.379 | 0.399 | 0.177 | 0.288 |

GPT-4 agrees with the human consensus **better than individual humans agree with each other** on accuracy. Also: "all the taxonomies evaluated in this section are fully automatic and do not involve any human intervention."

### SemEval-2025 Task 5 / LLMs4Subjects — the closest analogue to the team's exact architecture
**https://arxiv.org/abs/2504.07199** | **https://sites.google.com/view/llms4subjects/** (verified from PDF)

This is retrieve-then-judge tagging against a large borrowed controlled vocabulary, with expert gold labels, run as a competitive shared task. **Read it as the ceiling for the team's current architecture.**

Setup: **GND subject vocabulary — 204,739 subjects** (all-subjects track) or **79,427** (tib-core track). Corpus: TIBKAT technical library records, **123,589 English+German records** (81,937 train / 13,666 dev for all-subjects; 6,980 dev for tib-core). **Average 3–7 gold subjects per record.** 12 teams; nearly all used embedding retrieval → candidate shortlist → LLM/cross-encoder selection.

Quantitative, against librarian gold labels:

| all-subjects | P@5 | R@5 | P@10 | R@10 | Avg R@k (5–50) |
|---|---|---|---|---|---|
| Annif (1st) | 0.26 | 0.49 | 0.16 | 0.57 | **0.63** |
| DUTIR831 | 0.26 | 0.48 | 0.15 | 0.56 | 0.60 |
| RUC Team | 0.23 | 0.44 | 0.14 | 0.52 | 0.59 |
| DNB-AI | 0.25 | 0.47 | 0.15 | 0.54 | 0.56 |

Qualitative — **TIB subject librarians manually reviewed 122 test records**, labeling each of the top-20 predicted GND codes **Y (correct), I (irrelevant but technically correct), or N (incorrect)**:

| | Case 1 (Y+I correct) P@5 | Case 2 (only Y) P@5 |
|---|---|---|
| DNB-AI (1st) | **0.74** | **0.53** |
| DUTIR831 | 0.70 | 0.49 |
| RUC Team | 0.71 | 0.48 |
| Annif | 0.66 | 0.46 |

**Three things to take from this:**
- With a huge, professionally-maintained vocabulary and **82k gold-labeled training records**, the best system reaches R@5 ≈ 0.49 and librarian-judged P@5 ≈ 0.53.
- **The 0.74 → 0.53 collapse between "technically correct" and "actually correct" is exactly what an oversized vocabulary does to you.** The organizers name the cause: "models predicted multiple semantically similar subjects as top-ranked." When the vocabulary contains many near-synonymous concepts, the judge picks a defensible-but-wrong one.
- The paper notes a structural precision ceiling: with ~5 true subjects per record, **P@10 cannot exceed 0.5 by construction.** Any P@k reporting must account for this.

The winning system, **Annif** (https://arxiv.org/abs/2504.19675, https://arxiv.org/abs/2508.15877), is the Finnish National Library's open-source production subject-indexing toolkit — it won by combining LLM *synthetic data generation* with conventional XMTC classifiers, not by using an LLM as the judge.

### TopicGPT
Covered in §3 — it is also the best-documented published example of "LLM generates open-vocabulary labels, then merge-by-similarity + frequency-floor consolidates them," with the frequency floor (10 / 5) stated outright.

### BERTopic + LLM labeling
⚠️ **Abstract-level only; I verified none of these in full text.** For the record: https://arxiv.org/abs/2502.18469 (LLM labeling of BERTopic topics + a novel label-representativeness metric); https://arxiv.org/abs/2505.08439 (Italian Supreme Court judgments; reports Claude Sonnet BERTScore F1 0.8119 for labeling, 0.9130 for summarization — note BERTScore against a reference summary is a weak proxy for concept quality); https://arxiv.org/abs/2503.10658 (LimTopic). **Do not treat these numbers as load-bearing.**

---

## 5. "Anyone who documented replacing a borrowed vocabulary with a corpus-derived one, and what happened to quality"

**Honest answer: essentially nobody publishes this, and I want to be explicit about it.** I found no paper or engineering writeup that ran a controlled before/after comparison of tagging quality using a borrowed vocabulary versus a corpus-derived replacement on the same corpus. That experiment appears not to exist in the literature.

What does exist, closest first:

1. **TyDI / VegA biotech patents** (https://arxiv.org/abs/2010.00860) — built from scratch off 21,039 patents, **but used MeSH and AGROVOC to structure the highest levels only**. Reported "high quality of the resource" via a downstream IR evaluation but **the actual numbers are in a separate cited reference I did not retrieve** — flag as unquantified. This is the only documented hybrid: **borrow the upper ontology, derive the leaves from your corpus.**

2. **TaxonomyBuilder / AI skills** (https://arxiv.org/abs/2605.21029) — explicitly motivated by the inadequacy of O*NET and ESCO for emerging AI skills, and builds bottom-up instead. **But it never reports a head-to-head against O*NET or ESCO.** The gap is acknowledged in their limitations section (they only studied their own pipeline's design factors). **This is the paper that should have answered your question and doesn't.**

3. **data.blog** (https://data.blog/2025/03/21/organizing-data-blog-content-via-nlp-and-llm/) — a genuine 3× taxonomy reduction with full human review, but n=100 posts and **no measured outcome.**

4. **TnT-LLM** (https://arxiv.org/abs/2403.12173) — replaced a manual expert-curation process with LLM generation *in production at Microsoft*, and reported human-eval numbers. But it replaced *a process*, not *a borrowed vocabulary*, and it prescribed the target size.

5. **MeSH provenance study** (https://arxiv.org/abs/2101.08293) — the closest thing to longitudinal evidence about vocabulary fit: **75% of new descriptors over 15 years were refinements of concepts already in the vocabulary, not new territory.** A vocabulary that fits its corpus grows mostly by *splitting*, not by *adding*.

---

## What the evidence actually supports

Stated plainly, and flagged as my synthesis rather than any single source's claim:

1. **Size**: EuroVoc covers all EU legislative and policy output with **7,000+ concepts**. MeSH's curated tier is **~30,000**. Every LLM-era corpus-derived taxonomy in this report landed at **10–150 concepts** from corpora of 8k–33k documents. A 513k vocabulary for US federal regulatory documents is off by roughly two orders of magnitude, and the LLMs4Subjects results show precisely what that costs: near-synonymous candidates in the shortlist drive judged precision from 0.74 down to 0.53.

2. **Two tiers, always.** MeSH runs 230k staged SCRs against 30k registered Descriptors — an 8:1 ratio, with every SCR *anchored* to a Descriptor. EuroVoc runs a "candidate scheme" in VocBench. Both promote on the order of 100–500/year, by committee. **The staging tier is where the long tail belongs.**

3. **The graduation gate is a definition and a reviewer, not a count.** No real thesaurus uses a bare frequency threshold. The only published numeric thresholds are engineering heuristics: TopicGPT's removal threshold of **10 (Bills) / 5 (Wiki)**, merge at **cosine ≥ 0.5**; data.blog's human rule of **"reject if only one document supports it."** MeSH's *actual* dominant promotion path is "this SCR has accumulated enough indexing traffic that it deserves its own descriptor" — a usage signal, adjudicated by a human, run as an annual campaign.

4. **Filter hard, don't augment.** The AI-skills study found augmentation *significantly reduced* coverage (η²=0.836) and label utilization; EvoTaxo's arbitration ablation showed the ungated version tripling node count while *degrading* hierarchy validity. Both point the same direction.

5. **Instability is the real risk, and it is measurable.** TopicGPT produced 73 vs 79 vs 118 vs 123 vs 147 topics depending on sample and prompt, with only ~0.67–0.70 self-agreement. **A vocabulary is supposed to be stable across time and across annotators; an LLM-induced one is not, unless you freeze it, register it, and version it.** The published fix is boring: generate once on a sampled subset (new topics plateaued after ~600 documents in TopicGPT), refine, freeze into a registry with IDs, then only ever *add* through a review queue.

6. **Budget the humans.** The one honest accounting is TyDI: **65,529 candidates → 2,680 concepts over 6 weeks with 2 people.** ~4% yield. Half the candidates were never even reviewed. For a small team, that is the realistic shape — and the reason to spend the filtering effort *before* a human ever sees a list.

---

## Full source list

**ATE / terminology extraction**
- TermEval 2020 / ACTER: https://aclanthology.org/2020.computerm-1.12/ · https://termeval.ugent.be/ · dataset: https://lt3.ugent.be/resources/acter/
- ATE survey (ACM CSUR / arXiv): https://arxiv.org/abs/2301.06767 · https://dl.acm.org/doi/10.1145/3787584
- LLM ATE via syntactic retrieval (ACL Findings 2025): https://aclanthology.org/2025.findings-acl.516/ · https://arxiv.org/abs/2506.21222
- Math concept extraction / annotator agreement: https://arxiv.org/abs/2309.00642
- TyDI / biotech patents human-curation case: https://arxiv.org/abs/2010.00860
- C-value/NC-value (canonical, numbers unverified): https://link.springer.com/chapter/10.1007/3-540-49653-X_35
- TermSuite: https://termsuite.github.io/
- PatternRank (unsupervised keyphrase, numbers unverified): https://arxiv.org/abs/2210.05245
- Theme-driven keyphrase extraction (⚠️ numbers unverified): https://arxiv.org/abs/2301.11508

**Taxonomy induction / ontology learning**
- Chain-of-Layer: https://arxiv.org/abs/2402.07386 · https://dl.acm.org/doi/10.1145/3627673.3679608
- OLLM: https://arxiv.org/abs/2410.23584
- OntoLearner: https://arxiv.org/abs/2607.01977
- TaxoAdapt (⚠️ baselines unverified): https://arxiv.org/abs/2506.10737
- OntoAxiom (⚠️ abstract only): https://arxiv.org/abs/2512.05594
- TaxonomyBuilder / AI skills from job postings: https://arxiv.org/abs/2605.21029
- Prompting vs fine-tuning for taxonomy construction (⚠️ abstract only): https://arxiv.org/abs/2309.01715
- LLMs4OL challenge: https://arxiv.org/abs/2409.10146

**Vocabulary maintenance / graduation**
- MeSH record types & SCR counts: https://www.nlm.nih.gov/mesh/intro_record_types.html
- MeSH SCR module: https://www.nlm.nih.gov/tsd/cataloging/trainingcourses/mesh/mod2_150.html
- MeSH new-descriptor provenance: https://arxiv.org/abs/2101.08293
- MeSH 2026 counts: https://www.nlm.nih.gov/pubs/techbull/jf26/jf26_NLM_Classification_2026_WinterEd.html
- MeSH annual processing: https://www.nlm.nih.gov/pubs/techbull/nd24/nd24_annual_mesh_processing.html
- EuroVoc management (LDK 2025): https://aclanthology.org/2025.ldk-1.34/
- EuroVoc Handbook: http://publications.europa.eu/resource/cellar/a2723a83-574f-11eb-b59f-01aa75ed71a1.0001.01/DOC_1
- EuroVoc portal: https://op.europa.eu/en/web/eu-vocabularies
- SACO program: https://www.loc.gov/aba/pcc/saco/ (⚠️ 403 on fetch) · when to propose: https://static-prod.lib.princeton.edu/cams/katmandu/pcc/sacwhen.html · SHM H 200: https://www.loc.gov/aba/publications/FreeSHM/H0200.pdf (⚠️ 403)
- FAST: https://www.oclc.org/research/areas/data-science/fast.html · https://en.wikipedia.org/wiki/Faceted_Application_of_Subject_Terminology
- Folksonomy reviews: https://jodi-ojs-tdl.tdl.org/jodi/article/download/269/278 · https://arxiv.org/abs/cs/0701072

**LLM open-vocabulary tagging + consolidation**
- TopicGPT: https://aclanthology.org/2024.naacl-long.164/ · https://arxiv.org/abs/2311.01449 · https://github.com/chtmp223/topicGPT
- TnT-LLM: https://arxiv.org/abs/2403.12173
- SemEval-2025 Task 5 / LLMs4Subjects: https://arxiv.org/abs/2504.07199 · https://sites.google.com/view/llms4subjects/ · https://github.com/jd-coderepos/llms4subjects
- Annif (winning system): https://arxiv.org/abs/2504.19675 · https://arxiv.org/abs/2508.15877 · https://annif.org (⚠️ 403 on fetch)
- EvoTaxo: https://arxiv.org/abs/2603.19711
- data.blog taxonomy rebuild: https://data.blog/2025/03/21/organizing-data-blog-content-via-nlp-and-llm/

**Explicitly unverified — do not cite from this report:** C-value/NC-value original precision figures; TaxoGen and HiExpan performance numbers (an automated read produced fabricated values, which I discarded); KeyBERT/YAKE/RAKE F1 benchmarks; TaxoAdapt's baseline identities; total LCSH heading counts and SACO approval rates; TBX anything; BERTopic+LLM labeling numbers beyond abstract level; the downstream IR evaluation numbers for the TyDI termino-ontology.

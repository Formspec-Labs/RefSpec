# Recovered blind external research report

> Provenance
>
> - Recovery source: Private pre-publication research transcript; not published
> - Recovery date: **2026-07-28**
> - Extraction status: **COMPLETE**
> - Verification note: Claims retain the original report's verification flags. This archive does not silently repair or rewrite research claims.

## Consolidated final report

This consolidated report includes three places where later findings **correct** the earlier draft.

## Corrections to my earlier draft

1. **Federal Register Thesaurus size: 1,044 terms, not ~701.** Verified via `https://www.federalregister.gov/api/v1/topics.json`, which returns `{"count":{"thesaurus":1044,"ad_hoc":6723,"total":7767}}`. My PDF regex undercounted. Note the 6,723 "ad hoc" entries are parsing garbage (`"165 as follows:"`, `"1200 Sixth Avenue"`) — use the 1,044 only. This also resolves your 936 figure as a stale or differently-scoped extraction.

2. **My "75% of your corpus is already labeled" claim was scoped too narrowly and reads as over-optimistic.** Correct picture: 75% of *Rules and Proposed Rules* carry topics, but **Notices are ~81% of the Federal Register and carry zero — by law.** 1 CFR 18.20 requires index terms only for documents in the Rules and Proposed Rules sections, per CFR part affected; Notices have no CFR parts. Independently confirmed in GovInfo MODS for FR-2024-01-02: RULE 8/11, PRORULE 2/5, NOTICE **0/47**, PRESDOCU 0/2. Corpus-wide topic coverage is **13.1%**.

3. **My "generate a scope note per concept" recommendation was too confident.** See §5 below — the primary evidence is genuinely mixed and includes large negative results.

---

## Per-source findings

### The agency/source-prior evidence, now properly dissected

**KenMeSH — the mechanism is not what it's usually described as.** Verified from the PDF ([ACL 2022](https://aclanthology.org/2022.acl-long.210.pdf)): journal set `Mj = {L | P(L|J) > τ}` with **τ = 0.5** — a term only enters if it appears in *more than half* that journal's articles, so `Mj` is a tiny set of near-universal terms. The kNN set `Ma` is the union of gold labels from the **K = 1000** nearest training abstracts. The applied mask is the **union `M = Mj ∪ Ma`**, and the paper states outright that with these settings *all gold labels are guaranteed to be in the mask*. Ablation removing masked attention costs MiF −0.071 (0.745 → 0.674) — but that ablation removes the mask, the kNN set, the journal set, and label-wise attention together. **There is no published number for what a journal prior alone buys.** No independent reproduction exists.

**MATCH (WWW 2021) — the cleanest isolation of venue metadata, and it is deflating.** [Paper](https://arxiv.org/abs/2102.07349). PubMed: 898,546 docs, 17,693 MeSH labels, 150 venues. Metadata as soft embeddings, never a filter. All metadata together buys **+0.15 P@1 (not significant), +1.0 P@3, +1.2 P@5**. The authors are explicit that *venues indicate coarse categories and are less beneficial for fine-grained ones.*

**MTI's journal vocabulary density** ([Frontiers 2023](https://www.frontiersin.org/journals/research-metrics-and-analytics/articles/10.3389/frma.2023.1250930/full)): journals used on average **999 of 27,149** MeSH headings. Used as a **soft confidence boost** — if a journal indexed a term for a high share of articles (*Cryobiology* → "Cryopreservation", 88.95%), MTI suggests it even absent textual evidence. **+4.44 percentage points precision**, statistically significant; recall cost not reported.

**MTIFL — journal routes *documents*, not vocabulary.** NLM designated ~14 journals (2011) → 230 (2014) where MTI was good enough for first-line indexing. MTI precision 0.3019 (2007) → 0.8646 (2022). The 2010 rebalancing matters: MTI ran at ~30% precision by optimizing recall with long candidate lists and *indexers stopped trusting it*.

**Journal Descriptor Indexing** — NLM's coarse **122-descriptor** discipline layer learned from journal metadata, used for disambiguation and routing, not for restricting the ~30k main-heading space. No published accuracy numbers.

**Nobody hard-partitions a vocabulary by source metadata.** Annif's unit of configuration is (vocabulary, language, backend) — never collection or publisher. DNB splits by target vocabulary. The one curated subset in the wild (TIB's 79,427-concept `tib-core` from 204,739 GND) was hand-curated once by librarians for a whole library, and **no SemEval participant partitioned by domain or trained per-domain models.**

### Vocabulary size vs quality — the strongest single result

**SemEval-2025 Task 5 / LLMs4Subjects** ([task paper](https://arxiv.org/abs/2504.07199)) is your architecture, run competitively, with 82k gold-labeled training records against a 204,739-concept vocabulary. Best system: R@5 ≈ 0.49. Then TIB subject librarians manually reviewed 122 test records, grading each prediction Y (correct) / I (irrelevant but technically correct) / N (incorrect):

| system | P@5 counting Y+I | P@5 counting only Y |
|---|---|---|
| DNB-AI | **0.74** | **0.53** |
| DUTIR831 | 0.70 | 0.49 |
| Annif | 0.66 | 0.46 |

**That 0.74 → 0.53 collapse is what an oversized vocabulary does to a retrieve-then-judge system.** The organizers name the cause: *models predicted multiple semantically similar subjects as top-ranked*. Your judge will pick a defensible-but-wrong near-synonym. This is the mechanism by which 513k concepts hurts you, and it is invisible to any metric that doesn't distinguish "technically correct" from "correct."

**Size anchors from vocabularies that actually work:** EuroVoc covers the **entire legislative and policy output of the European Union with 7,000+ concepts** (21 domains, 127 microthesauri, 12,000 non-preferred terms). MeSH's curated tier is ~30,194 Descriptors. Every LLM-era corpus-derived taxonomy in the literature lands at 10–150 concepts.

**Two-stage routing is not actually evidenced.** The most-cited EuroVoc paper ([CoopIS 2019](https://penni.wu.ac.at/papers/Coopis%202019%20Exploiting%20EuroVoc's%20Hierarchical%20Structure%20for%20Classifying%20Legal%20Documents.pdf)) is routinely mis-cited for this. It trains *flat* classifiers at three granularities: F = 0.74 at 126 microthesauri, 0.67 at 489 top terms, 0.58 at 3,563 descriptors. That only says coarse is easier than fine. **No paper measuring a domain→descriptor cascade against a flat baseline could be found.** Meanwhile learned label partitions (Parabel → [Bonsai](https://arxiv.org/abs/1904.08249)) have moved *away* from aggressive partitioning because of error propagation on tail labels.

### Retrieval, not partitioning, is where the evidence is

**SemSup-XC** ([ICML 2023](https://arxiv.org/abs/2301.11309)), zero-shot P@1 with bare class names:

| method | EURLex-4.3K | AmazonCat-13K | Wikipedia-1M |
|---|---|---|---|
| **TF-IDF** | **44.0** | 18.7 | 14.5 |
| Sentence Transformer | 16.6 | 18.2 | **7.8** |
| SPLADE | 20.2 | 17.2 | 14.3 |
| SemSup-XC | 44.7 | 48.2 | 36.5 |

**On EURLex — the legal/regulatory-adjacent set — plain TF-IDF beats every neural retriever and ties SOTA.** Sentence-transformer zero-shot on the 1M-label set gets 7.8. That is your 0.029 degeneracy, measured by someone else. Removing lexical matching from SemSup-XC's hybrid costs **33 P@1 points on EURLex**.

**Label-description expansion is NOT a reliable win** — this is the correction to my earlier recommendation. Same paper's table: feeding descriptions to other models *hurt badly* — MACLR EURLex 24.9 → **20.9**; MACLR AmazonCat 36.0 → **18.4**; ZestXML AmazonCat 15.6 → **5.4**. And **GPT-3-generated descriptions (42.5 EURLex) were worse than web-scraped ones (44.7)**. Jina's practitioner writeup reports +19% to +40% F1 on some datasets but **−10% to −31% on TREC**, where opaque label names get "whitened out." Try it; A/B it; do not assume it.

**Calibration at your exact scale:** LCSHBench (~515K LCSH labels, almost exactly your vocabulary size) reports fine-tuned retriever R@10 = 0.334, R@50 = 0.512, R@200 = 0.659; stock embeddings R@10 = 0.166. *(Flagged unverified against primary tables; the paper also mentions a 41% ceiling I couldn't reconcile with R@200 = 0.659.)* Directionally: **at a 12-candidate shortlist over a 515K vocabulary, a third of gold labels is roughly the state of the art. Your shortlist is the binding constraint, and no judge quality fixes it.**

### Chemicals and the entity/topic split

**MeSH is a two-tier registry with an 8:1 ratio**: **>230,000 Supplementary Concept Records (>505,000 terms)**, created daily and distributed nightly, each *anchored* to a Descriptor via "Heading Mapped To" — against **~30,194 curated Descriptors**, updated annually. Over 2006–2020, 6,915 new descriptors were added (~460/yr), of which **~23% were promoted SCRs** and **~44% were finer splits of concepts already covered**. A vocabulary that fits its corpus grows by *splitting*, not by *adding*.

**EPA's own architecture makes the same split**: Substance Registry Services is an entity registry (CAS numbers, taxonomic serial numbers); Terminology Services manages vocabularies for indexing information assets. The TSCA Inventory is ">86,000 chemicals," updated twice yearly. **Chemical identity is not a subject.**

**But don't just delete entity coverage.** DNB-AI ([arXiv 2504.21589](https://arxiv.org/html/2504.21589v1)) had to *extend* their vocabulary from 200,035 topical terms to 309,417 by adding 109,382 named entities, because their absence caused country names to be *falsely mapped to unrelated subject terms*. The DNB GND-204K benchmark explicitly flags treating all entity types as the same as a known limitation, since *"named entities are linguistically different from subject headings"* — and identifies faceted decomposition as an obvious unexplored improvement they did not attempt. **Facet-split retrieval is an acknowledged gap, not a validated technique.**

### Corpus-driven vocabulary construction — sobering

- **ATE has not been solved.** TermEval 2020 best English F1 = **46.7**. 43% of gold terms are hapax, so frequency thresholds structurally cannot find most of the vocabulary. Everything above ~50 F1 is supervised. LLM in-context ATE reaches F1 60.2 on ACTER — matching, not beating, a fine-tuned RoBERTa.
- **The target itself is only ~78% reproducible.** Three trained humans with shared guidelines on math-concept extraction: pairwise Jaccard 0.75–0.80, *"not able to go higher"*; ChatGPT–human ~0.5.
- **Human curation cost, the one honest accounting:** TyDI/VegA, 21,039 biotech patents → 65,529 term candidates → **2,680 concepts** (~4% yield), 6 weeks, 2 people. Critically, they **borrowed MeSH and AGROVOC for the upper levels only and derived the leaves from the corpus** — the most transferable design I found.
- **Induced taxonomies are unstable.** [TopicGPT](https://aclanthology.org/2024.naacl-long.164/) — evaluated on **32,661 US congressional bill summaries**, a near-neighbor of your corpus — produced **73 / 79 / 118 / 123 / 147 topics** depending on sample and prompt, self-agreeing only 0.67–0.70. Its refinement step (merge at cosine ≥ 0.5, drop topics generated fewer than **10** times) cut 79 topics → **24** and cut human-judged misalignment from **70% → 32%**, eliminating duplicates entirely. New-topic discovery plateaued after ~600 documents. Total cost: $88.
- **Filtering beats augmenting, with statistics.** [TaxonomyBuilder](https://arxiv.org/abs/2605.21029) (AI skills from 30M job postings): augmentation *significantly reduced* strict coverage (ANOVA F=40.81, p<0.001, η²=0.836); 22 of 28 best scores came at or above the 50th-percentile filter; weakest-filter taxonomies won zero judge categories. [EvoTaxo](https://arxiv.org/abs/2603.19711)'s ablation: removing the human-arbitration gate took a taxonomy from **25 nodes → 70**, degrading hierarchy validity (0.83 → 0.74) while barely improving coverage.
- **No one has published the experiment you'd most want.** No controlled before/after of borrowed-vocabulary vs corpus-derived-vocabulary tagging quality on the same corpus exists. TaxonomyBuilder is explicitly motivated by O\*NET/ESCO's inadequacy and never runs the head-to-head.

### Three assets already in your corpus that you are not using

Verified by direct scraping:

1. **`toc_subject`** — a de facto controlled action/genre taxonomy in the FR table of contents. **613 distinct values, 73.1% coverage of all documents including 75% of Notices** (378 used once → ~235 recurring). Top values: "Hearings, Meetings, Proceedings, etc." (1,484), "Agency Information Collection Activities…" (1,296), "Self-Regulatory Organizations; Proposed Rule Changes" (806), "Airworthiness Directives" (271). **This is your answer for the 81% of the corpus that has no Thesaurus topics.** Free in every API response.
2. **CFR List of Subjects** — scraped across all 50 titles: **8,409 CFR parts, 37,220 (part, term) assignments, 1,196 distinct terms, avg 4.4 terms/part.** Any document with `cfr_references` — *including notices* — can inherit terms from its part. https://www.archives.gov/federal-register/cfr/subject-title-01.html … `-50.html`
3. **Unified Agenda RIN XML** — 55 elements including **`NAICS_LIST/NAICS_CD/NAICS_DESC`** (verified populated on RIN 2060-AW65: `324199`, `331110`), plus PRIORITY_CATEGORY, RULE_STAGE, CFR_LIST, LEGAL_AUTHORITY_LIST, ENERGY_AFFECTED, FEDERALISM. Overall NAICS fill rate unverified. `https://www.reginfo.gov/public/do/eAgendaViewRule?pubId=202504&RIN=...&operation=OPERATION_EXPORT_XML`

**Regulations.gov has no topical vocabulary at all.** Its `category` field is agency-configurable *commenter* categories ("Academia - E0007") — it classifies who submitted a comment, not what a document is about.

---

## Verdict on the agency-scoping hypothesis

**Partially supported — and the two independent measurements we ran look contradictory until you separate two different operations.**

My measurement (2,220 labeled docs, 70/30 split, top-k candidate generation):

| method | recall@12 | docs fully covered |
|---|---|---|
| global top-12, no conditioning | 42.2% | 29.6% |
| naive lexical, title+abstract | 26.2% | 6.8% |
| **agency prior** | **71.0%** | 58.4% |
| **CFR part prior** | **76.0%** | **68.3%** |

The independent measurement (3,680 docs carrying index terms, 669 distinct terms): **64.6% of terms are used by ≥2 top-level agencies, and 90.0% of all assignments land on shared terms.** Most cross-cutting: *Administrative practice and procedure* (60 agencies), *Reporting and recordkeeping requirements* (46 agencies, 1,851 uses), *Incorporation by reference* (21 agencies, 1,288 uses).

**These reconcile cleanly.** The agency prior works because it *re-weights a frequency distribution*, not because it partitions a vocabulary. The cross-cutting spine is frequent everywhere, so the prior keeps it; agency-specific terms are what the prior *adds*. A hard partition does the reverse: it prunes the agency-exclusive third that carries only ~10% of labeling volume and keeps the genuinely ambiguous part. That is why the hard-filter leave-one-out ceiling is **94.9% (agency) / 93.2% (CFR part)**, and the losses are precisely *State and local governments, Penalties, Privacy, Incorporation by reference, Imports/Exports*.

**The strongest version of the idea, stated precisely:**
> Estimate P(concept | CFR part), backing off to P(concept | parent agency), backing off to global. Add it as a **score component** to a lexical+dense retriever. **Union** the prior-derived candidates with a global top-N — never intersect. Weight the prior by that part/agency's measured concentration.

Four things to hold onto:

- **CFR part beats agency** (76.0% vs 71.0% recall@12). Not a coincidence: 1 CFR 18.20 attaches the List of Subjects to *each CFR part affected*. Agency is a lossy proxy.
- **Collapse sub-agencies to parents.** Raw agency counts make 66.8% of rules look multi-agency; that is a parent+child artifact. True multi-department rulemaking is **1.3–1.6%** (both of us measured it independently), essentially the FAR Council and the banking regulators. The joint-rulemaking objection is real but small.
- **Broad-remit agencies are the real failure mode, and it's measurable.** Top-10 topics cover 89.8% of FAA's assignments and 88.3% of Coast Guard's — but only 42.4% of Treasury's and 36.2% of USDA's. Don't apply uniform prior weight.
- **Be honest about the ceiling.** MATCH shows venue metadata is worth ~1 point when you have 898k supervised training examples. The prior's value is *inversely proportional to how much supervision your text model has* — which is exactly why it's worth 29 points to you now (71% vs 42%) and will shrink as your text side improves. It is a bridge, not a destination.

**And copy KenMeSH's safety design, not its reputation.** The only hard mask in the literature was built with a recall-preserving escape hatch — τ=0.5 makes the journal set trivially small, and the union with 1000-NN gold labels guarantees no gold label is excluded. If you mask, mask like that.

---

## Ranked recommendations

**1. Delete 99.6% of the vocabulary. Keep ~1,100–2,100 concepts.** *(Highest value, lowest effort.)*
Drop all 440,599 FAST topical terms and all 70,736 TSCA names from the topical candidate pool. Keep: Federal Register Thesaurus (**1,044 API-verified terms**, plus the ~504 non-preferred variants as a synonym ring), CRS Legislative Subject Terms (~1,000), CRS Policy Areas (33). Evidence: EuroVoc indexes all EU legislative output with 7,000+; 686 FR topics are exercised across 7,000 rules; 300 cover 95% of assignments; LLMs4Subjects shows near-synonym crowding driving judged precision 0.74 → 0.53. Expect your 0.029 similarity gap to widen on arithmetic alone — you are removing ~270 competing near-neighbors per true match.

**2. Build the evaluation set before changing anything else.** *(~1 day.)*
~5,000 Rules and Proposed Rules per year carry government-assigned topics, ~6 labels each, 75% coverage. That is a free gold set, a free prior-estimation set, and free training data. **Scope the claim honestly: this covers ~19% of the Federal Register.** You currently cannot tell whether any change helps.

**3. Solve Notices separately — they are 81% of your corpus and have no topics by law.** *(~2 days.)*
Two paths, both already in your data: (a) `toc_subject`, 613 values at 73.1% coverage including 75% of Notices; (b) propagate CFR List of Subjects terms via `cfr_references` (8,409 parts → 1,196 terms). Do not try to fix this by enlarging the vocabulary — no vocabulary is applied to this part of the corpus at all.

**4. Add CFR-part priors as a soft score component.** *(~half a day, biggest measured lift.)*
P(concept | CFR part) → P(concept | parent agency) → global. Additive score, weighted by measured concentration. Union with global top-N, never intersect. Took recall@12 from 42% to 76% in my benchmark.

**5. Add proper lexical retrieval — this is more important than I said earlier.** *(~half a day.)*
TF-IDF beats every neural retriever on EURLex zero-shot (44.0 vs 16.6). SemSup-XC loses 33 P@1 points on EURLex without lexical matching. The FR Thesaurus ships ~504 non-preferred variants mapping to official terms — a free synonym dictionary. My crude 26.2% lexical baseline understates this badly; use real BM25 over full text.

**6. Split chemicals onto a separate axis — but keep them.** *(~2 days.)*
Mirror MeSH's Descriptor/SCR two-tier design and EPA's own Terminology-Services/SRS split. Substance mentions become NER + normalization against CAS/SRS identifiers, emitted as a *different facet*, not competing in the same similarity ranking. Do not simply delete: DNB had to *add* 109,382 named entities because their absence caused false mappings. Note that facet-separated retrieval is an acknowledged gap in the literature, not a validated technique — measure it.

**7. Add a cross-encoder reranker.** *(~2 days.)*
Best-evidenced fix for degenerate first-stage retrieval. Also raise k: at 515K labels, R@10 ≈ 0.33 vs R@50 ≈ 0.51 vs R@200 ≈ 0.66. After step 1 your pool is ~1,500, so a larger shortlist is nearly free.

**8. Try label-description expansion, but A/B it. Do not assume it.** *(~1 hour + measurement.)*
"Incorporation by reference" as a bare string is nearly unembeddable. But the primary evidence is mixed: descriptions cost MACLR 17.6 points on AmazonCat and ZestXML 10.2; GPT-3-generated descriptions underperformed web-scraped ones; Jina reports −31% on TREC. Cheap to test at 1,500 concepts; treat a positive result as a finding, not a default.

**9. Scope your automation, not just your vocabulary.** *(Ongoing.)*
Follow MTIFL: measure per-CFR-part and per-agency performance, fully automate only where it clears a threshold, route the rest to review. NLM went 14 journals → 230 → 100% over eleven years. And heed the 2010 lesson — MTI at 30% precision with long candidate lists destroyed indexer trust; rebalancing toward precision was what made it usable.

**10. If you later add corpus-derived concepts, use the two-tier pattern and expect to throw away 96%.** *(Weeks, not days — do this last.)*
Borrow the upper levels (FR Thesaurus + CRS Policy Areas), derive leaves from your corpus, and stage them in an SCR-style tier anchored to registered concepts. Use TopicGPT's published gates: merge at cosine ≥ 0.5, drop candidates generated fewer than 10 times, human-review the survivors. Budget by TyDI's real numbers: 65,529 candidates → 2,680 concepts, 6 weeks, 2 people. And freeze the result — TopicGPT produced 73/79/118/123/147 topics depending on prompt and sample, self-agreeing only ~0.67.

**What not to do:** don't hard-filter by agency (costs 5–7% recall concentrated in your most frequent labels); don't expect vocabulary reduction alone to fix quality (SemEval cut 61% with no clean gain — pruning helps because it removes *wrong-domain* terms, not because it removes terms); don't chase automated taxonomy induction as a primary strategy (best literal concept-label F1 in the literature is 0.093, and OntoLearner's 180-ontology benchmark concludes the bottleneck is *"a structural mismatch between how models encode knowledge and how ontologies organize it,"* not model capability); and calibrate expectations — with a matched vocabulary and 82k training records, the best of 12 competing teams reached librarian-judged P@5 of 0.53.

---

## Sources by claim

**Source-conditioned priors:** [KenMeSH ACL 2022](https://aclanthology.org/2022.acl-long.210.pdf) · [MATCH WWW 2021](https://arxiv.org/abs/2102.07349) · [MTI/MEDLINE 10-year survey](https://www.frontiersin.org/journals/research-metrics-and-analytics/articles/10.3389/frma.2023.1250930/full) · [12 years on MTI](https://pmc.ncbi.nlm.nih.gov/articles/PMC5324252/) · [JDI methodology](https://lhncbc.nlm.nih.gov/LSG/Projects/Tc/web/jdiMethodology.html)

**Vocabulary size vs quality:** [SemEval-2025 Task 5](https://arxiv.org/abs/2504.07199) · [Annif system](https://arxiv.org/abs/2504.19675) · [DNB-AI system](https://arxiv.org/abs/2504.21589) · [EuroVoc management, LDK 2025](https://aclanthology.org/2025.ldk-1.34/) · [EuroVoc hierarchy, CoopIS 2019](https://penni.wu.ac.at/papers/Coopis%202019%20Exploiting%20EuroVoc's%20Hierarchical%20Structure%20for%20Classifying%20Legal%20Documents.pdf) · [Bonsai](https://arxiv.org/abs/1904.08249) · [CAP codebook](https://www.comparativeagendas.net/pages/master-codebook)

**Retrieval:** [SemSup-XC ICML 2023](https://arxiv.org/abs/2301.11309) · [LCSHBench](https://arxiv.org/abs/2606.04382) · [GND-204K benchmark](https://arxiv.org/abs/2607.14882) · [Isotropic representation](https://arxiv.org/pdf/2209.00218) · [Jina rephrasing](https://jina.ai/news/rephrased-labels-improve-zero-shot-text-classification-30/)

**Vocabulary construction / graduation:** [TermEval 2020](https://aclanthology.org/2020.computerm-1.12/) · [ATE survey](https://arxiv.org/abs/2301.06767) · [TyDI biotech curation](https://arxiv.org/abs/2010.00860) · [Annotator agreement](https://arxiv.org/abs/2309.00642) · [TopicGPT](https://aclanthology.org/2024.naacl-long.164/) · [TnT-LLM](https://arxiv.org/abs/2403.12173) · [EvoTaxo](https://arxiv.org/abs/2603.19711) · [TaxonomyBuilder](https://arxiv.org/abs/2605.21029) · [OLLM](https://arxiv.org/abs/2410.23584) · [OntoLearner](https://arxiv.org/abs/2607.01977) · [MeSH provenance](https://arxiv.org/abs/2101.08293) · [MeSH record types](https://www.nlm.nih.gov/mesh/intro_record_types.html)

**Federal vocabularies:** [FR topics API](https://www.federalregister.gov/api/v1/topics.json) · [FR Thesaurus PDF 2025](https://www.archives.gov/files/federal-register/cfr/thesaurus-4-1-2025.pdf) · [CFR List of Subjects](https://www.archives.gov/federal-register/cfr/subjects.html) · [1 CFR 18.20](https://www.ecfr.gov/current/title-1/chapter-I/subchapter-E/part-18/section-18.20) · [eCFR agencies API](https://www.ecfr.gov/api/admin/v1/agencies.json) · [GovInfo BILLSTATUS bulk](https://www.govinfo.gov/bulkdata/BILLSTATUS) · [regulations.gov API](https://open.gsa.gov/api/regulationsgov/) · [QuantGov/RegData, CC BY 4.0](https://www.quantgov.org/data) · [NASA Thesaurus SKOS](https://www.sti.nasa.gov/docs/thesaurus/thesaurus-SKOS.xml) (22,622 concepts, verified) · [NALT](https://lod.nal.usda.gov/) · [EPA Web Taxonomy](https://sor.epa.gov/sor_internet/registry/termreg/searchandretrieve/taxonomies/search.do) · [TSCA Inventory](https://www.epa.gov/tsca-inventory/about-tsca-chemical-substance-inventory) · [FAST](https://www.oclc.org/research/areas/data-science/fast.html)

**Flagged unverified — do not quote without checking:** LCSHBench and GND-204K recall figures (fetch summaries, not primary tables; LCSHBench's 41% ceiling contradicts its own R@200); the TartuNLP "reranking nearly doubles recall" claim; MTI "12 years on" precision figures; C-value/NC-value original precision; TaxoGen and HiExpan numbers (an automated read fabricated values, discarded); KeyBERT/YAKE/RAKE benchmarks; EPA Web Taxonomy term count (export is session-bound; its data.gov SKOS record last updated 2014); Unified Agenda NAICS overall fill rate; EuroVoc concept counts from op.europa.eu (the LDK paper's 7,000+ is the verified figure). **Not investigated at all:** Transportation Research Thesaurus, ERIC, DTIC, NTIS, GAO, DOE, NIOSH, UNBIS.

## Appendix: Late correction

You're right, and I was wrong to publish before they landed. All three returned, and they materially change three of my conclusions. Corrections below.

## Correction 1: my coverage number was conditioned, and the unconditioned one is much worse

I reported "74.9% of your corpus carries government-assigned topics." That was 74.9% **of Rules and Proposed Rules only**. Measured across the whole Federal Register (12,149 documents sampled across 2025), it is **13.1%**. Notices are ~81% of the corpus and carry **zero** Thesaurus topics — by law, not neglect: 1 CFR 18.20 requires index terms only for documents in the Rules and Proposed Rules sections, per CFR part affected. Notices have no CFR parts. Independently confirmed in GovInfo MODS for FR-2024-01-02: RULE 8/11, PRORULE 2/5, NOTICE **0/47**, PRESDOCU 0/2.

My "your gold labels already exist" recommendation stands, but only as an evaluation and prior-estimation asset for rulemaking documents. It does not solve tagging for the majority of your corpus.

**The fix I missed:** `toc_subject`, the Federal Register table-of-contents field — **613 distinct values covering 73.1% of all documents, including 75% of notices**, free in every API response. Top values: "Hearings, Meetings, Proceedings, etc." (1,484), "Agency Information Collection Activities" (1,296), "Self-Regulatory Organizations; Proposed Rule Changes" (806), "Airworthiness Directives" (271). It is a genre/action taxonomy rather than a subject one, but it is the only native label that reaches notices.

## Correction 2: my cross-cutting analysis was unweighted, and the weighted version cuts against me

I reported 51.6% of topics used by exactly one root agency, and framed that as "half the vocabulary is agency-specific." The weighted measurement, on a larger sample (5,000 unique 2024–2025 final rules, 3,680 with index terms, 669 distinct terms):

| distinct top-level agencies using the term | terms | share |
|---|---|---|
| 1 | 237 | 35.4% |
| ≥2 | 432 | **64.6%** |

**90.0% of all topic-term assignments land on terms shared by two or more agencies.** The agency-exclusive third of the vocabulary carries roughly 10% of labeling volume. Agency partitioning would prune the rarely-used part and keep the genuinely ambiguous part.

This does *not* contradict my benchmark (agency prior 71% vs global 42% recall@12) — and the reconciliation is the whole point. My benchmark measured a **frequency-weighted ranking prior**, not a partition. The prior works precisely *because* it reweights shared terms by how much each agency uses them. The label *set* is not agency-separable; the label *distribution* is. Soft prior yes, partition no.

## Correction 3: the journal-MeSH mask does not do what it is usually said to do

I cited KenMeSH as unverified. It is now verified from the PDF, and the mechanism undercuts the story. The mask is `M = Mj ∪ Ma` where the journal set `Mj` uses threshold **τ = 0.5** — a MeSH term only qualifies if it appears in **more than half** that journal's articles — and `Ma` is the union of gold labels from the **K = 1000** nearest training abstracts. The paper states verbatim that with τ=0.5 and K=1000, *all* gold labels are guaranteed to be in the mask.

So the journal prior is a garnish on a 1000-NN candidate generator, and **the journal component is never ablated separately** — there is no published number for what a journal prior alone buys in KenMeSH. Removing the whole masked-attention module costs MiF −0.071; removing the label-hierarchy module costs far more (MiF 0.745 → 0.554). Hierarchy beats mask.

Worse for the hypothesis: **MATCH** (WWW 2021), the one paper that cleanly isolates venue metadata, finds it buys **+0.15 P@1 (not significant), +1.0 P@3, +1.2 P@5** on PubMed/MeSH, and says explicitly that venues indicate *coarse* categories and are *less* beneficial for fine-grained ones. Your vocabulary is overwhelmingly fine-grained.

The MTI +4.44pp precision result still stands as the best real evidence, and it is a soft boost. But the literature is thinner on source-conditioned priors than my first report implied.

## Revised verdict on agency scoping

**Partially supported, and materially weaker than I first said.** The empirical case:

- **For**: my measured 71% (agency) / 76% (CFR part) recall@12 from metadata alone vs 42% unconditioned; MTI's +4.44pp; MTIFL's per-source automation gating.
- **Against**: 90% of label assignments go to cross-agency terms; MATCH measures venue metadata at ~+1 point and only at coarse granularity; KenMeSH's journal prior is unmeasured and structurally minor.
- **Reconciliation**: use it as a **frequency-weighted ranking prior unioned with a global retriever**. Never as a filter, never as a partition. Copy KenMeSH's design intent — its one hard mask was built with a recall-preserving escape hatch.
- **Key correction to my earlier claim**: CFR part still beats agency (76% vs 71%), and if you do use agency, **collapse sub-agencies to the parent department** — raw agency counts show 66.8% "multi-agency" documents, which is an artifact of parent+child pairs. True joint rulemakings are 1.3–1.6%.

## What the other threads add that changes the recommendations

**Vocabulary target size, anchored.** EuroVoc indexes the **entire legislative and policy output of the European Union with 7,000+ concepts** (21 domains, 127 micro-thesauri, 12,000 non-preferred terms). MeSH's curated tier is ~30,000. The Federal Register Thesaurus, verified via the FR API, is **1,044 terms** (not my ~701 PDF parse, not your 936 — worth reconciling; the API is authoritative). Every LLM-era corpus-derived taxonomy in the literature lands at 10–150 concepts. 513,236 is off by two orders of magnitude.

**The measured cost of an oversized vocabulary, from your exact architecture.** SemEval-2025 LLMs4Subjects is retrieve-then-judge over a 204,739-concept vocabulary with 82k gold-labeled training records. Librarians hand-reviewed 122 test records: precision@5 was **0.74 counting "technically correct"** but **0.53 counting "actually correct."** The organizers name the cause — models predicted multiple semantically similar subjects as top-ranked. That 21-point collapse is what near-synonymous concepts do to a judge, and it is the single best quantification of your problem.

**A major asset I missed: the CFR List of Subjects.** Scraped across all 50 titles: **8,409 CFR parts, 37,220 (part, term) assignments, 1,196 distinct terms, avg 4.4 terms/part.** This is a ready-made part→topic mapping that propagates to *any* document citing a CFR part — including notices. Available as HTML per title at `archives.gov/federal-register/cfr/subject-title-NN.html`.

**Lexical retrieval should rank higher than I put it.** SemSup-XC (ICML 2023), Table 2, zero-shot P@1 on EURLex-4.3K — the legal/regulatory-adjacent benchmark: **TF-IDF 44.0, SPLADE 20.2, sentence transformers 16.6**, SOTA 44.7. Plain TF-IDF beats every neural retriever and ties the state of the art. Removing lexical matching from their hybrid costs **33 P@1 points**. Your 0.029 cosine gap is exactly this, measured.

**Label-description generation is not a free win — downgrade my #5.** Same verified table: feeding generated descriptions to other models *hurt badly* (MACLR on AmazonCat 36.0 → **18.4**; ZestXML 15.6 → **5.4**). And GPT-3-generated descriptions (42.5 EURLex) were *worse* than web-scraped ones (44.7). Jina's practitioner data shows +19% to +40% on some datasets but **−10% to −31% on TREC**. Try it, but A/B it per vocabulary; do not assume it helps.

**The graduation gate you'll need, with real thresholds.** MeSH runs a two-tier registry: **>230,000 staged Supplementary Concept Records against ~30,000 registered Descriptors** (8:1), every SCR anchored to a Descriptor, promoting ~100–500/year by editorial campaign. Over 15 years, 6,915 new descriptors: ~23% promoted SCRs, ~44% refinements of concepts already covered — **a vocabulary that fits its corpus grows by splitting, not adding**. EuroVoc uses a candidate scheme in VocBench with named reviewers and committee consensus; **no frequency threshold anywhere**. The only published numeric gates are engineering heuristics: TopicGPT merges at **cosine ≥ 0.5** and drops topics generated fewer than **10 times** (on US congressional bills), taking 79 topics → 24 and cutting human-judged misaligned topics from **70% to 32%**.

**Budget the humans honestly.** The one real accounting: TyDI/VegA, 21,039 biotech patents → 65,529 extracted candidates → **2,680 concepts**, by one domain expert plus one knowledge engineer in **6 weeks**. ~4% yield. And their design is the most transferable thing in the whole report: **borrow the upper ontology (they used MeSH/AGROVOC for top levels only) and derive the leaves from your corpus.**

## Revised recommendation order

1. **Delete FAST and TSCA from the candidate pool.** Unchanged, still first. Target ~1,000–2,000 concepts, anchored on EuroVoc's 7,000-for-all-EU-law and the FR Thesaurus's 1,044.
2. **Harvest the CFR List of Subjects (8,409 parts → 1,196 terms) and FR `topics`.** Bigger than I said: the part→term map propagates to documents that have no `topics` of their own.
3. **Add `toc_subject` as a second axis for notices.** 613 values, 73% coverage, the only native label reaching the 81% of your corpus that rules-based indexing cannot touch.
4. **Metadata priors on CFR part, backing off to parent agency, unioned with a global retriever.** Soft, frequency-weighted, never a filter.
5. **Add TF-IDF/BM25 alongside dense — promoted from #6.** On the closest published benchmark it beats every neural retriever outright. The Thesaurus ships ~504 non-preferred variants as a free synonym ring.
6. **Widen the shortlist past 12 and add a cross-encoder reranker.** At ~515K labels (LCSHBench, almost exactly your size) a fine-tuned retriever gets R@10 ≈ 0.33, R@200 ≈ 0.66. Your judge cannot recover what the shortlist omits.
7. **Two-tier registry with an explicit review queue** — MeSH's model. Long tail stages, anchored to a registered core; promote on usage evidence plus human review.
8. **Label-description generation — demoted from #5 to optional, A/B required.**

## Honest negatives worth stating

- **No paper measures a EuroVoc domain→descriptor two-stage cascade against a flat baseline.** The CoopIS paper routinely cited for this only shows coarse labels are easier to predict than fine ones (F 0.74 at 126 labels, 0.67 at 489, 0.58 at 3,563). If someone claims EuroVoc proves two-stage routing, ask for the citation.
- **No published A/B of hard metadata filtering vs soft metadata reranking exists.** The comparison appears not to have been run.
- **No one published a controlled before/after of a borrowed vocabulary replaced by a corpus-derived one.** The paper that should have answered this (TaxonomyBuilder, AI skills from job postings) explicitly declines to benchmark against O*NET/ESCO.
- **Faceted retrieval is an acknowledged gap, not a validated technique.** The DNB GND-204K benchmark explicitly says it treats all entity types the same, flags that "named entities are linguistically different from subject headings," and does not split them. Your chemicals/topics separation is well-motivated by that admission but is not empirically validated anywhere.
- **LLM-induced vocabularies are unstable.** TopicGPT produced 73/79/118/123/147 topics depending on sample and prompt, with ~0.67–0.70 self-agreement. If you induce a vocabulary, generate once on a sample (new-topic discovery plateaued after ~600 documents), refine, then freeze it into a versioned registry.

Two flags on sourcing: the LCSHBench recall figures, the DNB GND-204K numbers, and a "reranking nearly doubles recall" claim from TartuNLP came from fetch summaries rather than extracted primary tables — verify before quoting. And LCSHBench's own "exact-reachable ceiling of 41%" could not be reconciled with its reported R@200 of 0.659, so the denominator is ambiguous.

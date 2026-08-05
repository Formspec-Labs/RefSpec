# Vocabulary Atlas relation candidate matching context

Date: 2026-08-05

Status: experiment phase complete; the production-integration proposal is
ready for review. A bounded $0.046897820 provider embedding experiment,
including one OpenAI asynchronous Batch smoke row, ran with prior
authorization. No paid LLM scorer or judge call has run, and no production
catalog, qualification policy, mapping assertion, or release artifact changed.

Scope decision: Atlas v1 candidate retrieval and judging cover English only.
Translation, transliteration, cross-lingual retrieval, and multilingual model
advantages are outside the production policy, cost estimate, and acceptance
gate. Earlier multilingual-model observations remain research history only.

## Decision frame

The mapping pipeline has two independent quality gates:

1. A local, deterministic finder builds an inclusive set of plausible direct
   cross-vocabulary mapping candidates.
2. Two blind model families judge the relation for every retained pair.

The first gate optimizes recall over the desired direct, nonredundant graph.
False positives are acceptable because the judges can reject them, while
generic thematic shortcuts and already-expressed paths are noise rather than
missing mappings. Candidate volume still matters because every retained
production candidate reaches both judges; the proposal removes the full-pool
paid scorer. The launch criterion is therefore: retain every defensible direct
mapping signal, measure known-relation coverage, test graph minimality, and
report the resulting provider cost before approval.

The release plan requires normalized labels, alternate labels, definitions,
identifiers, lexical near-misses, native hierarchy, and graph neighborhoods.
See `research/vocabulary-atlas-release-definition-and-cross-vocabulary-mapping-plan-2026-08-04.md`, section 7.1.

## Candidate distinctions and coverage model

Two independent classifications matter. They should not be collapsed into one
label.

The **mapping relation** is the output the blind judges decide: `exactMatch`,
`closeMatch`, target-is-broader (`broadMatch`), target-is-narrower
(`narrowMatch`), `relatedMatch`, or no relation. This is the semantic claim the
release publishes.

The **retrieval challenge** explains why a potential pair is discoverable.
These labels may overlap; for example, an acronym can also be a close synonym
whose target is broader.

| Retrieval challenge | Primary signals and candidate arms to test |
| --- | --- |
| Stable identity or code | Normalized local identifiers, source-provided crosswalks, code patterns, exact lookup |
| Exact lexical variation | Unicode/case/punctuation normalization, singularization, token order, Levenshtein and character n-grams |
| Alias or synonym | Alternate labels, token-set matching, lexical resources, sparse and dense semantic retrieval |
| Acronym or abbreviation | Initialism expansion, acronym token sets, parenthetical aliases, domain abbreviation tables |
| English regional or institutional wording | English alternate labels, thesauri, lexical resources, and semantic retrieval across registers such as `TRUCKS` / `LORRIES` |
| Definition or semantic paraphrase | Definition/scope-note sparse retrieval, field-specific dense views, late interaction |
| Hierarchy or aligned neighborhood | Parent/child labels, anchored graph expansion, structural alignment and ontology matchers |
| Broader/narrower or granularity shift | Directional hierarchy features, definition inclusion, ancestor/descendant context, judge direction |
| Associative `relatedMatch` | Native associative links, definitions, graph neighborhoods and semantic retrieval; keep non-traversable by default |
| Directional role or inverse wording | Verb/role templates, domain/range and inverse-property context, cross-encoder rescue |
| Compound or compositional concept | Head/modifier decomposition, phrase containment, definition and hierarchy context |
| Polysemy or sparse metadata | Vocabulary/domain context, neighboring concepts, conservative wide rescue arms |

These challenges do not each require a separate production model. They require
independent evidence channels and per-kind recall measurements. Cheap exact and
lexical channels should carry their natural cases. Sparse, dense, graph,
English lexical-resource, and reranker arms should add the cases those channels
miss. The production union remains inclusive for plausible direct mappings;
the judges determine relation and direction without seeing which arm proposed
the pair.

OAEI Conference is useful for lexical, synonym, semantic, and directional
property wording. OAEI Anatomy stresses biomedical synonyms and identifiers.
The 582 Atlas assertions provide real `exact`, `close`, `broad`, `narrow`, and
`related` regression cases. A separate labeled challenge pool is still needed
for abbreviation, isolated hierarchy, and sparse-metadata cases that those
benchmarks do not expose in balanced numbers.

## Verified implementation baseline

`src/refspec/atlas/qualification.py` currently generates six disjoint classes:

- normalized preferred-label equality;
- alternate-label equality;
- preferred-label token containment;
- preferred-label edit distance at most two;
- target siblings of a preferred-label match; and
- seeded random negative controls.

The implementation is deterministic and input-order independent. It does not
use definitions, scope notes, identifiers, source hierarchy, or general graph
neighborhoods to discover a pair. Scoring ranks the sealed candidate catalog;
it cannot recover a relation omitted by candidate generation.

The six prepared production catalogs contain 12,313 candidates. The 582
previously admitted Atlas mappings all occur in those catalogs. This is a
useful regression check, but not an independent recall estimate: those
mappings came from an earlier label-oriented candidate run.

## Independent reference benchmarks

### OAEI Conference

The 2024 Ontology Alignment Evaluation Initiative (OAEI) Conference track has
21 reference alignments among seven independently developed conference
ontologies. The original crisp reference contains 305 equivalence relations.
The benchmark page describes the reference and its evaluation use:
https://oaei.ontologymatching.org/2024/conference/index.html

Downloaded inputs:

| Artifact | SHA-256 |
| --- | --- |
| `conference.zip` | `78688cda05857b594be188db6831abc5d890d2e38d6602e0cd8d3c82ecb24546` |
| `reference-alignment.zip` | `782e0175253d817288e1f7ed29f738a7fa9e57a8b9c77bb3b11c12b80405d4bf` |

The benchmark adapter treats OWL classes and properties as concepts. It uses
`rdfs:label` when present, otherwise a split local identifier, `rdfs:comment`
as definition text, and `rdfs:subClassOf` as native hierarchy.

Results:

| Finder | Gold found | Recall | Candidate rows | Cartesian reduction |
| --- | ---: | ---: | ---: | ---: |
| Current production semantic rules | 196 / 305 | 64.26% | 1,645 | 99.39% |
| Bidirectional label TF-IDF, top 10 | 239 / 305 | 78.36% | 5,979 | 97.79% |
| Bidirectional full-context TF-IDF, top 10 | 257 / 305 | 84.26% | 13,775 | 94.91% |
| Bidirectional label character trigrams, top 10 | 262 / 305 | 85.90% | 28,466 | 89.49% |
| Union of the three sparse methods, top 10 | 278 / 305 | 91.15% | 35,758 | 86.79% |
| `BAAI/bge-small-en-v1.5`, bidirectional top 5, plus current rules | 285 / 305 | 93.44% | 20,343 | 92.49% |
| `BAAI/bge-small-en-v1.5`, bidirectional top 10, plus current rules | 291 / 305 | 95.41% | 39,061 | 85.57% |
| `BAAI/bge-small-en-v1.5`, bidirectional top 20, plus current rules | 297 / 305 | 97.38% | 74,984 | 72.31% |

The current rules miss clear synonyms and role variants such as `Subject Area`
↔ `Topic`, `Trip` ↔ `Excursion`, `Participant` ↔ `Attendee`, `Place` ↔
`Location`, and `Conference Dinner` ↔ `Conference Banquet`.

### OAEI Anatomy

The OAEI Anatomy track matches 2,744 Adult Mouse Anatomy classes with 3,304
National Cancer Institute Thesaurus classes. Its reference contains 1,516
relations. OAEI reports normalized string equality at 62.2% recall in 2024 and
uses `recall+` to measure nontrivial relations whose normalized labels differ:
https://oaei.ontologymatching.org/2024/results/anatomy/index.html

The MELT repository describes the official track coordinates:
https://dwslab.github.io/melt/track-repository

Downloaded inputs:

| Artifact | SHA-256 |
| --- | --- |
| source ontology | `93756393d6306c8f332c884401aa447cc4b2557f0a6be3e0efd988a943cb68f8` |
| target ontology | `5c1ca432d9845f1abb36ecfce313df46d8c56d2fb4137d0590ec4e4a6a9b05bf` |
| reference alignment | `b6a6b12f3e7a786e5b58c4898024f0f483426e9036bdc3939aa61b046dbc26c4` |

The current adapter includes labels, local identifiers, and direct
`rdfs:subClassOf` parents and children. It recognizes OBO synonym and
definition predicates, but this Anatomy serialization points them to `genid`
resources whose human text is stored in the referenced node's `rdfs:label`.
The adapter currently records those node IRIs rather than dereferencing their
labels. Existing Anatomy runs therefore measure a conservative, text-poor
view. A separately versioned adapter correction and before/after comparison
are required before using Anatomy to judge alternate-label or definition
coverage. Direct evaluation of the current semantic rules finds 1,099 of
1,516 gold relations, or 72.49%.

Exact and alternate-label anchors plus one-hop parent/child cross-products
produce 27,390 candidates and find 1,055 gold relations. The graph method adds
structural reach but does not replace semantic retrieval.

The first structured `BAAI/bge-small-en-v1.5` run uses preferred label,
alternate labels, local identifier, definition, parents, and children in one
field-labeled text. It unions bidirectional embedding neighbors, graph
expansion, and current-rule gold hits:

| Embedding depth per direction | Embedding recall | Hybrid recall | Embedding + graph rows before full lexical union |
| ---: | ---: | ---: | ---: |
| 5 | 89.18% | 95.32% | 48,712 |
| 10 | 92.88% | 96.90% | 70,975 |
| 20 | 95.51% | 98.22% | 116,451 |
| 50 | 97.63% | 98.75% | 252,399 |
| 100 | 98.94% | 99.14% | 477,936 |

The best bidirectional rank for a gold relation is at most 6 for 90% of the
reference, 18 for 95%, 60 for 98%, and 124 for 99%. One hard relation ranks
1,051, which shows why one embedding view cannot define the complete floor.

Together, Conference and Anatomy provide 1,821 expert reference relations.
They independently show that exact and fuzzy labels form a strong seed but not
an adequate high-recall candidate finder.

### OAEI BeyondEquivalence

Conference and Anatomy mainly evaluate equivalence discovery. The 2025 OAEI
BeyondEquivalence track provides an independent check for generalization,
specialization, overlap, and disjointness in addition to equivalence:
https://oaei.ontologymatching.org/2025/beyondequivalence/index.html

The public Zenodo record is CC BY 4.0 and supplies the benchmark as one ZIP:
https://zenodo.org/records/17091043

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `benchmark.zip` | 11,552,662 bytes | `04cc6dd2a2f8d173ddcc19822428fa9f505e3855840f06b19072306233d240eb` |

The smaller STROMA/TaSeR cases—especially text, groceries, and literature—are
the next independent relation-type pool. Their reference files preserve the
relation marker for every pair, so candidate recall can be reported separately
for equivalence, source-broader, source-narrower, and associative/overlap
cases. Disjoint pairs remain a useful rejection control; they are not positive
SKOS mapping candidates. This benchmark was chosen to test whether hierarchy,
composition, and semantic arms cover typed relations that equivalence-only
benchmarks cannot expose. The completed result appears later in this ledger.

## Atlas signal availability

### Domain guardrail

The production Atlas is not a general scientific-terminology matcher. Its six
releases describe regulatory, legislative, public-policy, and social-science
subjects:

- 32 CRS Policy Areas use broad policy labels plus long inclusion/exclusion
  definitions, such as `Finance and Financial Sector` and `Environmental
  Protection`;
- 565 CRS Legislative Subject Terms are concise topical phrases such as
  `Trade restrictions`, `Service animals`, and `Food supply, safety, and
  labeling`, usually without definitions or aliases;
- 705 Federal Register thesaurus terms use administrative and regulated-domain
  language, with useful alternate labels but no definitions or native
  hierarchy in this release; and
- ELSST and ICPSR use social-science thesaurus language with uneven aliases,
  definitions, and hierarchy, including cross-register pairs such as `TRUCKS`
  / `LORRIES` and specialized topics such as `absentee ballots`.

All six releases and the v1 matching task are English-language. English
regional and institutional variants remain in scope; translation,
transliteration, cross-lingual matching, and multilingual-only model value do
not enter production selection or acceptance.

The primary production challenges are policy synonyms across institutional
registers, acronyms and program names, compound topic phrases, sparse source
text, and directional differences in topic granularity. Alternate labels,
definitions, token/character retrieval, general semantic retrieval, and typed
hierarchy therefore transfer directly. Conference property inverses,
biomedical Anatomy synonyms, and retail meronymy remain useful stress cases,
but they do not choose the production model or cutoff. A biomedical specialist
must demonstrate unique value on the actual Atlas before entering its floor.

The real Atlas concepts provide the following fields:

| Pair | Source / target concepts | Alternate labels | Definition or scope | Parent or child context |
| --- | ---: | ---: | ---: | ---: |
| CRS policy ↔ Federal Register | 32 / 705 | 0 / 243 | 32 / 0 | 0 / 0 |
| CRS subjects ↔ Federal Register | 565 / 705 | 0 / 243 | 0 / 0 | 0 / 0 |
| CRS subjects ↔ CRS policy | 565 / 32 | 0 / 0 | 0 / 32 | 0 / 0 |
| ELSST ↔ ICPSR | 3,470 / 3,280 | 1,509 / 0 | 952 / 729 | 3,393 / 1,979 |
| Federal Register ↔ ELSST | 705 / 3,470 | 243 / 1,509 | 0 / 952 | 0 / 3,393 |
| Federal Register ↔ ICPSR | 705 / 3,280 | 243 / 0 | 0 / 729 | 0 / 1,979 |

No current pair shares an exact terminal local identifier. Identifier matching
must remain in the policy because future releases may carry shared codes.

A separate dependency-free sparse prototype used weighted labels,
definitions, scope notes, identifiers, parents, children, phrases, and
bigrams. Reciprocal top 2 added 1,325 rows to the six catalogs. Of those rows,
941, or 71.0%, depended on non-label context. This result remains a
corroborating prototype until the primary benchmark harness reproduces it.

## Initial representation and model matrix

This was the initial benchmark plan. The completed results appear in the
experiment logs below and compare each retrieval family on the same gold sets
and the 582 typed Atlas relations.

Text structures:

1. preferred label only;
2. preferred and alternate labels;
3. one structured text with field names;
4. definition-first structured text;
5. hierarchy-path text with separate parent and child sections;
6. separate vectors for labels, definitions, and hierarchy, followed by rank
   fusion;
7. asymmetric query/document text; and
8. symmetric concept-to-concept text.

Local Hugging Face models:

- `BAAI/bge-small-en-v1.5` with and without the documented retrieval prefix;
- `sentence-transformers/all-MiniLM-L6-v2` as a compact symmetric baseline;
- `snowflake/snowflake-arctic-embed-s` with its documented query prefix;
- `jinaai/jina-embeddings-v2-small-en` for long structured context; and
- `nomic-ai/nomic-embed-text-v1.5-Q` with `search_query:` and
  `search_document:` prefixes.

Model-card evidence:

- BGE recommends relative ranking and documents the retrieval instruction:
  https://huggingface.co/BAAI/bge-small-en-v1.5
- Snowflake documents a query-only retrieval prefix:
  https://huggingface.co/Snowflake/snowflake-arctic-embed-s
- Jina supports 8,192-token inputs and symmetric semantic-text use:
  https://huggingface.co/jinaai/jina-embeddings-v2-small-en
- Nomic requires task prefixes and distinguishes query from document text:
  https://huggingface.co/nomic-ai/nomic-embed-text-v1.5

The plan called for a pinned local cross-encoder or late-interaction model on
the wide union. The completed reranking logs below preserve the same add-only
boundary: a reranker may rescue low-ranked pairs but cannot remove a pair
admitted by another production rule.

## Initial candidate policy tested

The experiment tested an inclusive union of:

1. exact preferred labels, alternate labels, and local identifiers;
2. token containment, character n-grams, and bounded edit distance;
3. sparse full-context retrieval over labels, definitions, scope notes,
   identifiers, parents, and children;
4. multiple local embedding views with bidirectional neighbor retrieval;
5. one-hop graph expansion around strong anchors and semantic neighbors; and
6. reranker rescue from a wider embedding and sparse pool.

Each candidate must record the rules that found it, ranks in both directions,
model and revision pins where applicable, input-field digests, and stable
tie-breaking evidence. Production must regenerate the same pair set and digest
from reordered inputs.

### Proposed production integration boundary — not implemented

After the experiments and proposal are reviewed, the selected finder can enter
qualification as a versioned **retrieval snapshot**, separate from the scorer
and judges. This preserves four useful properties:

1. The current production-v1 policy remains reopenable for earlier sealed
   evidence. A new English-only policy receives a new identifier.
2. Every retrieval arm contributes additively. One canonical source-target row
   records all signals that found it, while a stable primary class supports
   accounting. No reranker or later arm deletes an earlier candidate.
3. The snapshot pins the two exact concept inputs, language (`en`), arm names
   and cutoffs, model and tokenizer revisions where applicable, ordered pair
   rows, pair-set digest, and content-derived identity. Local neural inference
   also retains its vector/rank receipt because model output alone is not
   portable across arbitrary runtimes.
4. Qualification verifies every endpoint and digest, adds control rows only
   after the semantic union is complete, and copies the full retrieval evidence
   into the sealed catalog. Scorer and judge payloads continue to hide the
   generation class, ranks, proposed relation, and retrieval method.

This seam lets local lexical, sparse, English WordNet, embedding, graph, and
reranker tools evolve independently while the paid workflow consumes one exact
candidate population. It also prevents a missing model cache, changed cutoff,
or partial generation run from silently becoming release coverage.

## Acceptance tests

Before provider launch, the deterministic finder must pass:

- complete coverage of all 582 previously admitted Atlas relations;
- measured recall on all 1,821 OAEI Conference and Anatomy references;
- separate recall for trivial and nontrivial references when available;
- signal-isolation tests for preferred labels, alternates, definitions,
  identifiers, parents, children, and graph-neighborhood discovery;
- input-order, process-repeat, and serialized-digest reproducibility;
- per-release candidate counts, candidate-source mix, runtime, and memory;
- manual inspection of new candidates from each rule and vocabulary pair; and
- a recomputed scoring and judging cost before spend authority is sealed.

Interim verdict at this point in the log: continue expansion. The existing
deterministic finder was a sound lexical seed and reproducible control
mechanism; the subsequent logs complete the contextual, semantic, and graph
experiments before any paid six-run campaign.

## Experiment log — candidate-model research (Kierkegaard)

Recorded: 2026-08-05 06:36:18 EDT.

### Result and boundary

The next candidate expansion should combine signals that fail differently:
fielded lexical retrieval, lexical knowledge, neural sparse expansion,
token-level late interaction, biomedical synonym retrieval, ontology
matchers, and typed graph propagation. A later reranker may add rescue
candidates from a deliberately wide reservoir, but it must not remove a pair
found by another rule.

Only the complete Cartesian product can literally guarantee every potential
pair. The six configured Atlas vocabulary pairs contain 16,579,315 directed
source-target combinations. Every smaller candidate set is an empirically
validated approximation. The high-recall policy therefore uses an inclusive
union, exact rather than approximate retrieval at this scale, and a measured
false-negative audit of rejected pairs.

### Model and technique inventory

| Order | Candidate source | Exact artifact and license | Expected candidate role and why |
| ---: | --- | --- | --- |
| 1 | Fielded sparse retrieval and lexical variants | Local implementation; RapidFuzz is MIT: https://github.com/rapidfuzz/RapidFuzz | Add BM25F over separate preferred-label, alternate-label, identifier, definition, parent, and child fields; word and character n-grams; Damerau-Levenshtein; Jaro-Winkler; token subsets; acronyms; numeric normalization; and morphology. These are cheap, inspectable signals that rescue spelling, token-order, abbreviation, and partial-label relations before any neural model runs. |
| 1 | Open English WordNet | CC BY 4.0, `2025-edition` commit `dc343f2683279ecbb13fab4e2fd778d7b162d287`: https://github.com/globalwordnet/english-wordnet | Propose pairs whose labels or alternates share a synset, derivational form, or direct/depth-two hypernym or hyponym. Polysemy will add false positives, which the judge can reject. It is a cheap likely rescue for Conference synonyms and role variants. |
| 2 | `BAAI/bge-m3` | MIT; Hugging Face revision `5617a9f61b028005a4858fdac845db406aefb181`: https://huggingface.co/BAAI/bge-m3 ; primary paper: https://aclanthology.org/2024.findings-acl.137/ | Treat dense, learned-sparse, and ColBERT token-vector outputs as three independent generators. Union each head's candidates before testing score fusion. The model repository is about 4.59 GB and the PyTorch weights about 2.27 GB, which is feasible on the 48 GiB Apple Silicon host in float32 CPU mode. Its sparse head weights tokens present in the input; it is not SPLADE-style vocabulary expansion. |
| 3 | OpenSearch neural sparse v2 | Apache 2.0; `opensearch-project/opensearch-neural-sparse-encoding-v2-distill` revision `269e6638b2c4f648996691f6d751495285d8f330`: https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-v2-distill | A permissive neural sparse bi-encoder that supplies learned lexical expansion distinct from dense similarity. Run exact bidirectional retrieval for the same structured views as the dense models. |
| 3 | OpenSearch neural sparse v3 | Apache 2.0; `opensearch-project/opensearch-neural-sparse-encoding-doc-v3-gte` revision `1646fef40807937e8e130c66d327a26421c408d5`: https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-doc-v3-gte | This is an asymmetric document-expansion model with IDF-weighted query tokens. Encode each vocabulary as the document side in turn and union both directions. The model is about 550 MB and is practical on CPU. Pin both model and remote-code revisions if `trust_remote_code` is used. |
| 4 | SapBERT | Model Apache 2.0 at revision `090663c3ae57bf35ffe4d0d468a2a88d03051a4d`: https://huggingface.co/cambridgeltl/SapBERT-from-PubMedBERT-fulltext ; code MIT: https://github.com/cambridgeltl/sapbert ; paper: https://aclanthology.org/2021.naacl-main.334/ | Anatomy-specific synonym retrieval. Score preferred and alternate names separately and aggregate ranks; long concatenated definitions do not match its entity-name training objective. Use Conference and Atlas as negative controls for domain specificity. Published weights were trained from UMLS terminology, so product use or redistribution needs review against UMLS source terms: https://www.nlm.nih.gov/research/umls/index.html |
| 4 | BioSyn method | Code MIT: https://github.com/dmis-lab/BioSyn ; paper: https://aclanthology.org/2020.acl-main.335/ | Its sparse morphology plus dense biomedical retrieval is a useful Anatomy challenger and design pattern. Prefer reproducing the hybrid method with pinned inputs over assuming that an unlicensed task-specific checkpoint is suitable. |
| 5 | LogMap | LGPL 3.0; pin `logmap-matcher-july-2021` commit `2f139a5a0bcc9377dd5744155af39d85d6dec205`: https://www.cs.ox.ac.uk/isg/tools/LogMap/ and https://github.com/ernestojimenezruiz/logmap-matcher | Export stable OWL classes, labels, aliases, comments, and `rdfs:subClassOf`; union all returned pairs. LogMap adds lexical anchors, iterative hierarchy discovery, and logical repair. Its precision-oriented final alignment is an extra candidate source, not a recall floor. |
| 5 | AgreementMakerLight | Apache 2.0; pin v3.2 commit `d54a6650818d3474fe36090c2bc7dfe5bf4dfcb6`: https://github.com/AgreementMakerLight/AML-Project | Adds weighted lexicons, synonym/background resources, structural matching, and repair. Its documented Java compatibility predates the installed OpenJDK 17, so require a local smoke test and three-run output digest before accepting it. |
| 5 | MELT | MIT; pin `melt-3.3` dereferenced commit `f2256efd5f2ebf86c2648382ef9b3f7c217cbc72`: https://dwslab.github.io/melt/ and https://github.com/dwslab/melt | MELT is the evaluation and component harness, not one independent matcher. Use it to load the official OAEI tracks, run pinned Java matchers, and optionally test its baseline string, synonym, bounded-path, and PARIS components. Official track coordinates are documented at https://dwslab.github.io/melt/track-repository |
| 6 | ColBERT late interaction | MIT: https://github.com/stanford-futuredata/ColBERT ; paper: https://aclanthology.org/2022.naacl-main.272/ | Contextual token vectors with MaxSim can recover partial phrase and role matches lost by one-vector pooling. The reference indexing stack expects a GPU; for vocabulary scale, compute exact MaxSim only over a wide sparse/dense reservoir or use BGE-M3's built-in ColBERT vectors. |
| 6 | MiniLM cross-encoder rescue | Apache 2.0; `cross-encoder/ms-marco-MiniLM-L6-v2` revision `c5ee24cb16019beea0893ab7796b1df96625c6b8`; pin the 90,870,598-byte safetensors file: https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2 | First reranker because it is small enough for broad CPU experiments. Score a wide reservoir both source-to-target and target-to-source, then add top 10, 20, and 50 per source and target. MS MARCO relevance may favor topical over equivalent concepts; that is acceptable for candidate discovery but not semantic admission. |
| 6 | BGE reranker v2 M3 | Apache 2.0; revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`: https://huggingface.co/BAAI/bge-reranker-v2-m3 | Run only if MiniLM leaves unique benchmark misses worth its 2.27 GB weights and slower CPU scoring. Cross-encoders score predefined pairs and cannot recover a pair absent from their input: https://www.sbert.net/examples/cross_encoder/applications/README.html |
| 7 | Typed anchor expansion and Similarity Flooding | Primary Similarity Flooding paper: https://dbs.uni-leipzig.de/files/research/publications/2002-1/pdf/icde2002-sf.pdf | Seed with the complete lexical and neural union. Add parent-parent, child-child, parent-child, and child-parent combinations within one and two hops, preserving edge type and direction. If misses remain structural, test deterministic fixpoint propagation over the typed pairwise graph. Cross-direction expansion is deliberately included to capture broader/narrower pairs. |
| 8 | Static semantic pivots | fastText code MIT, published vectors CC BY-SA 3.0: https://fasttext.cc/docs/en/pretrained-vectors ; ConceptNet data CC BY-SA 4.0: https://conceptnet.io/ | Lower-priority challengers. fastText subword vectors may rescue unusual morphology and out-of-vocabulary strings. A pinned local ConceptNet snapshot can propose concepts sharing an external node or neighbor, but size, ambiguity, share-alike terms, and snapshot drift reduce its priority after WordNet and modern models. |

Naver SPLADE is a technically strong research challenger because masked
language-model vocabulary expansion can match concepts with no original token
overlap. Its official implementation is CC BY-NC-SA 4.0, so it is research
only unless legal review approves production use:
https://github.com/naver/splade

### Representation and retrieval matrix

Each applicable model should run against four separately measured concept
views:

1. preferred label only;
2. preferred label plus each alternate as a separate record, aggregated by
   maximum score and rank fusion;
3. tagged fields for `label`, `definition`, `identifier`, `broader`, and
   `narrower`; and
4. natural-language context such as `Concept: ... Definition: ... Broader
   concepts: ...`.

Do not depend on one long concatenated text. BGE-M3 does not require a query
instruction, so preprompting remains an experimental alternate view rather
than an assumed improvement. OpenSearch v3 is intentionally asymmetric and
must run in both vocabulary directions.

For every signal, view, and direction:

- compute exact blockwise scores instead of approximate nearest-neighbor
  search; the largest Atlas matrix is only about 11.4 million scalar scores;
- evaluate tie-inclusive `k={1,2,5,10,20,50,100,200}` per source and per
  target;
- union per-signal top-k before adding reciprocal-rank fusion as another
  candidate source;
- record pair, provenance, view, direction, score, rank, artifact revision,
  file hashes, and input-field digest; and
- measure candidate recall, nontrivial recall, candidate rows, Cartesian
  percentage, unique gold rescued, candidates per rescued relation, runtime,
  peak memory, and source/target coverage.

The evaluation order is:

1. current production rules as the fixed floor;
2. lexical variants, BM25F, character n-grams, and WordNet;
3. the three independent BGE-M3 heads;
4. OpenSearch v2 and bidirectional v3 neural sparse retrieval;
5. SapBERT and BioSyn on Anatomy, with Conference and Atlas negative controls;
6. LogMap and AgreementMakerLight over canonical OWL exports;
7. MiniLM reranker rescue, followed by BGE reranker only when it adds unique
   gold; and
8. typed Similarity Flooding only if remaining misses show structural rather
   than textual evidence.

This order measures marginal recall per added candidate and spends compute on
the methods most likely to fail differently. No stage may delete candidates
from an earlier stage.

### Benchmarks and stop rule

Use the existing OAEI Conference 305-pair and Anatomy 1,516-pair references,
including Anatomy `recall+`, plus all 582 Atlas mappings broken down by
relation and vocabulary pair. The Atlas counts are 121 exact, 232 close, 75
broad, 119 narrow, and 35 related.

Conference and Anatomy primarily test equivalence-pair discovery. Add an open,
license-compatible subset of the OAEI BeyondEquivalence track to test
superclass, subclass, overlap, and disjoint candidates:
https://oaei.ontologymatching.org/2025/beyondequivalence/index.html

The proposed pre-provider target is:

- 100% coverage of the 582 Atlas regression mappings;
- at least 99.5% candidate recall on each independent OAEI benchmark, or a
  documented examination of every remaining miss and why its source data
  provides no usable signal;
- deterministic pair-set and catalog digests under repeated and reordered
  inputs; and
- a cost frontier showing the marginal gold rescued and candidate rows added
  by every signal.

A generator is removable only after it contributes zero unique gold across
the independent benchmarks and adds no useful candidate class in stratified
Atlas inspection. Because the 582 relations helped shape the current rules,
they are a regression set rather than independent proof of completeness.

Judge a deterministic stratified sample from outside the final union,
especially score bands immediately below every cutoff and pairs with graph
evidence but weak text evidence. A true relation in this rejected sample is
evidence to lower thresholds, widen retrieval, or add a new signal. Sampling
can estimate residual risk but cannot prove complete recall; only judging all
16,579,315 pairs can do that.

### Determinism and semantic boundary

Neural inference is reproducible only within a pinned execution environment,
not bit-identical across arbitrary platforms. Pin the model and tokenizer
commit, every downloaded file SHA-256, Python, PyTorch or ONNX Runtime,
tokenizer library, BLAS, operating system, architecture, thread count, and
normalization version. Use evaluation mode, inference mode, float32 CPU,
deterministic algorithms, canonical inputs, stable sorting, and all boundary
ties. Disable network access during benchmark runs and retain score receipts
or quantized scores so a release can explain its cutoff decisions.

Run every generator in fresh processes at least three times, then repeat after
shuffling concepts, alternates, and OWL triples. Compare canonical pair-set
digests. A Java matcher that changes output under canonical inputs must be
fixed, pinned to a stable configuration, or rejected from the deterministic
production floor.

All of these systems find candidate pairs only. Their scores, WordNet paths,
matcher relation guesses, and graph directions are evidence for discovery,
not admitted Atlas semantics. Preserve that provenance outside the judging
prompt. The LLM judge should receive the two concepts and their source
context, without the generator's proposed relation type, and make the final
typed relation decision independently.

## Experiment log — local infrastructure audit (Mill)

Recorded: 2026-08-05 06:36:06 EDT.

Scope: read-only audit of RefSpec, SpicyRegs, SpicySearch, and Rulespec for
existing local candidate retrieval, embedding, learned-sparse retrieval,
reranking, vector search, ontology matching, tests, and retained real-run
evidence. The audit made no provider calls, inspected no secret values, and
downloaded no models.

### What is already implemented

- RefSpec's current production generator remains label-centric. The declared
  classes are normalized preferred-label equality, alternate-label equality,
  preferred-label token containment, preferred-label edit distance, sibling
  distractors, and random negative controls
  (`src/refspec/atlas/qualification.py:89-125,471-717`). `AtlasConcept` already
  carries definitions, scope notes, broader identifiers, and bounded parents
  and children (`qualification.py:338-363`), but the generator does not use
  those fields to discover pairs. Its tests establish determinism, class
  coverage, deduplication, limits, and uncapped production behavior rather than
  semantic recall (`tests/test_atlas_qualification.py:63-167`).
- SpicyRegs has the strongest reusable candidate-generation surface.
  `ConceptMapper.rank(queries, depth)` provides one common query-to-ranked-ID
  API (`../src/spicy_regs/ontology/candidate_channels.py:150-160`). The module
  implements a versioned, digest-addressed exact dense concept index and cache
  (`candidate_channels.py:422-682`), exact full-index cosine search
  (`candidate_channels.py:685-729`), deterministic full-vocabulary BM25 over
  preferred and alternate labels (`candidate_channels.py:732-813`), and a
  character-trigram mapper (`candidate_channels.py:816-857`). These methods
  widen the pair catalog when each source concept queries the complete target
  index; they do not merely reorder an existing candidate list.
- The older anchored selector supplies useful lexical primitives: normalized
  alias conditioning, ambiguity and inverse-document-frequency statistics,
  word-boundary phrase matching, character 3-gram TF-IDF, and reciprocal-rank
  fusion (`../src/spicy_regs/ontology/concepts.py:338-425,428-650`). Its
  source-vocabulary quotas and final prompt-size trim
  (`concepts.py:653-715,734-796`) serve document tagging, not a recall-first
  Atlas production floor, and should not be carried into relation discovery.
- SpicyRegs also has pinned local dense, learned-sparse, and cross-encoder
  adapters. The pins are `BAAI/bge-base-en-v1.5` at
  `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`,
  `tomaarsen/splade-modernbert-base-miriad` at
  `c640ce28f7c4f4593ddba1b3855988f03a3d9cdc`, and
  `BAAI/bge-reranker-v2-m3` at
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`
  (`../src/spicy_regs/docpipeline/adapters/sentence_transformers.py:29-51`).
  SPLADE exposes distinct document and query encoders and can widen discovery
  when the complete target vocabulary is indexed
  (`sentence_transformers.py:431-554`). The cross-encoder explicitly scores a
  fixed supplied list and cannot widen it by itself
  (`sentence_transformers.py:557-568,668-745`).
- Two additional local oMLX paths are implemented behind loopback-only HTTP
  adapters: 1,024-dimensional `mlx-community/bge-m3-mlx-8bit` embeddings with
  an 8,192-token limit
  (`../src/spicy_regs/corpora/segmentation_experiment.py:64-73,853-940`) and
  `mlx-community/Qwen3-Reranker-4B-mxfp8`
  (`../src/spicy_regs/corpora/segmentation_rerank.py:44-63,414-560`). These are
  useful non-`SentenceTransformer` execution paths. The audit verified their
  adapter tests but found no retained real Atlas comparison for either, so they
  remain experiment candidates rather than validated Atlas choices.
- The generic legacy embedding script lists BGE small/base/large, MiniLM, and
  Nomic presets and performs normalized batched encoding
  (`../src/spicy_regs/vectordb/embed.py:35-63,82-154`). It does not pin model
  revisions or emit the complete receipts needed for production, so it is a
  model-loading reference rather than the production foundation.
- SpicySearch has exact full-target dense ranking with complete zero-overlap
  windows and deterministic ties
  (`../../spicysearch/src/spicysearch/dense_retrieval.py:373-462`). Its serving
  index can search every indexed item when `candidate_ids` is absent and keeps
  an exact coarse scan until a measured scale trigger
  (`../../spicysearch/src/spicysearch/semantic_serving.py:1022-1147`). The
  current baseline concept tier explicitly rejects `concept-vector-index`,
  however (`../../spicysearch/src/spicysearch/concept_snapshot.py:95-116`), so
  this is reusable search machinery rather than an already-published concept
  index.
- Rulespec has no candidate retrieval or model infrastructure. Its Python
  requirements contain validation and RDF packages only
  (`../../rulespec/requirements.txt:1-18`), and its constraints correctly state
  that embedding score or retrieval rank cannot prove an assertion
  (`../../rulespec/constraints/core/artifact.cue:36-47`).

### Measured evidence and limits

- The retained 35-item managed-vocabulary experiment compared lexical, BM25,
  character n-gram, exact dense, and fused channels. At candidate depth 12,
  dense found 25/32 represented meanings and 10/12 exact-or-close targets;
  lexical plus dense found 28/32 and 11/12
  (`plans/managed-vocabulary-experiment-roadmap.md:271-338`). Complete
  fieldwise dense windows improved dense-only coverage to 27/32 and 12/12,
  while equal-weight fusion worsened the combined result
  (`managed-vocabulary-experiment-roadmap.md:340-395`). This demonstrates that
  text representation, discovery recall, and fusion must be evaluated as
  separate variables.
- The reusable ablation harness asks the right pre-judge question: which
  channels put the correct release-member IRI in front of a judge? It reports
  represented-item Recall@K, exact/close coverage, rank, and complete candidate
  lineage (`../tools/ablate_candidate_selectors.py:1-49,173-205,255-303`). Its
  method can be adapted to the OAEI references and the 582 known Atlas mappings.
- Learned-sparse plus dense reciprocal-rank fusion improved real candidate
  recall at 10 and 50 while lowering early-ranking metrics, supporting SPLADE
  as an independent discovery arm rather than a final ordering policy
  (`../docs/evidence/document-segmentation-fair-comparison-2026-07-24.md:92-100,138-149`).
- The pinned BGE cross-encoder improved corpus Recall@10 from 0.5429 to 0.7143,
  MRR from 0.2934 to 0.4639, and nDCG@10 from 0.3395 to 0.5198 while Recall@50
  stayed 0.8000 (`document-segmentation-fair-comparison-2026-07-24.md:156-175`).
  This is direct evidence that a reranker improves order but cannot recover a
  pair absent from its input pool.
- Exact dense search should remain the baseline for the current Atlas scale.
  The optional USearch HNSW implementation has a compatible mapper and an exact
  recall comparator (`../src/spicy_regs/ontology/ann_index.py:370-433`), but its
  513,236-concept benchmark rejected approximate search: configurations with
  meaningful memory savings lost 21%-74% of exact top-12 neighbors, while the
  high-recall configuration saved only 4.7% resident memory
  (`../docs/evidence/usearch-ann-benchmark-2026-07-28.md:1-15,105-129`).

### Local verification

All selected hermetic tests passed:

- `uv run pytest -q tests/test_candidate_channels.py tests/test_docpipeline_adapter_sentence_transformers.py tests/test_ontology_ann_index.py` in SpicyRegs: **119 passed** in 1.07 seconds.
- `uv run pytest -q tests/search/test_dense_retrieval.py tests/search/test_semantic_serving.py` in SpicySearch: **70 passed**; only existing RDFLib deprecation warnings were reported.
- `uv run pytest -q tests/test_segmentation_rerank.py tests/test_segmentation_evaluation.py` in SpicyRegs: **27 passed** in 90.62 seconds, including injected-client oMLX adapter coverage.

### Recommended integration

Use the existing algorithms and provider-neutral protocols, while preserving
the product boundary: RefSpec owns exact release inputs and sealed mapping
evidence; the roadmap assigns durable lexical, BM25, exact-dense, and hybrid
indexes to SpicySearch
(`plans/managed-vocabulary-experiment-roadmap.md:194-205,263-269`). Avoid a new
RefSpec runtime dependency on the legacy SpicyRegs package.

The deterministic finder should query every source concept against complete
target indexes in both directions and union: exact and alternate labels,
identifiers, BM25, character n-grams, multiple dense text views, SPLADE, and
one-hop graph expansion around lexical and semantic anchors. Keep label,
definition/scope, identifier, parent, and child views separate before fusion so
one long or boilerplate field cannot hide another signal. Record every finding
channel, direction, rank, score, text-view digest, model/revision pin, and stable
tie-breaker. Use BGE and Qwen rerankers only as rescue or work-priority arms over
a deliberately wide union; a reranker may add a low-ranked pair to the retained
floor but must never remove a pair admitted by another production rule. This
structure maximizes pre-judge recall, keeps cost measurable, and lets the paid
judges perform classification rather than discovery.

## Experiment log — deterministic sparse, graph, and dense views (Codex)

Recorded: 2026-08-05 06:47:37 EDT. Status: active; provider embeddings,
learned-sparse retrieval, reranking, and additional local dense families are
still running.

### Reproducible harness and signal-isolation checks

This run added a dependency-free candidate retrieval module at
`src/refspec/atlas/candidate_retrieval.py`, a reusable OAEI/Atlas benchmark at
`tools/benchmark_atlas_candidate_retrieval.py`, and six focused tests at
`tests/test_atlas_candidate_retrieval.py`. The implementation keeps three
independent integer-scored views:

- preferred/alternate labels and local identifiers;
- labels plus definitions, scope notes, parents, and children; and
- label character trigrams and four-grams.

It performs exact bidirectional retrieval with canonical member ordering,
integer rarity weights, integer cosine approximation, and stable member-IRI
tie-breaking. A separate graph step expands explicit anchors through source
and target parents and children. Candidate digests do not depend on process
hashes or floating-point comparisons.

The six tests prove definition-only, hierarchy-only, identifier-only, and
spelling-variant discovery; aligned graph expansion; and identical rows and
digests after reversing both input vocabularies. All six pass. Ruff lint and
format checks pass. This is experimental implementation evidence; it has not
yet replaced the sealed production-v1 generator.

A fresh Conference process then regenerated every sparse ranking digest and
all eight mutual-graph pair-set digests exactly. This process-repeat check is
separate from the in-process reversed-input unit test and confirms that the
real benchmark output is stable apart from measured runtime.

The OAEI adapter uses the seven ontologies named by the 21 Conference
references and parses the alignment XML independently from RDFLib. It produced
305 gold pairs with corpus digest
`sha256:8fdba504058d3011dcc2219e1b9277c5f8c1ef331fad4482e4a86059daec1df1`
and gold digest
`sha256:63c2feb19ed1352ccaae8efe897e3f5a3c917db07b7b21324d9f97936282177e`.
The Anatomy adapter produced 1,516 pairs with corpus digest
`sha256:7932c29b4bd0a9a834a9b60d13e5ce8c688eb13fd542c912627a4c699dd97185`
and gold digest
`sha256:06e799bc6e35df5eef97bfdc8ec9fcc3f60a0a375503b01085bda5c5df13bd03`.

### Sparse and graph trials

On Conference, the three sparse views alone found 278/305 at bidirectional
top 10 and 281/305 at top 50. Expanding exact-label plus mutually ranked top-1
anchors through one hierarchy step raised these to 279/305 and 282/305. The
top-10 union retained 43,117 pairs; top 50 retained 95,231. The sparse ranking
digests are:

- label: `sha256:5f50e69e69c5497620a94ce59271632e738eef2fc9cbdb4fd09574f55bc477c2`;
- context: `sha256:4b22db9c8729973d36f3fbeff17b23453c991f630a8964538af34a15c8fa33bd`;
  and
- character n-gram:
  `sha256:083a87073c49011253ace76e029a0afe74f8e6667b0f6dbd0ed8dff058fd10a9`.

An intentionally permissive graph trial expanded every sparse top-10 anchor.
On Anatomy it found 1,513/1,516, or 99.80%, but retained 3,465,817 pairs at
top 100. This is valuable boundary evidence and an inefficient production
policy: graph propagation can provide recall, while weak semantic anchors
multiply candidate cost. The revised harness therefore reports exact-label
and mutual-top-1 anchor policies separately. The original permissive output is
retained at
`/tmp/refspec-candidate-benchmark.ANhNrc/anatomy-sparse-refspec-v1.json`,
SHA-256 `c39be2df04afcb0553da9c546fd0a1a9142a4a6ea987d175543f3f905f9d5573`.

### BGE representation and context-injection trial

`BAAI/bge-small-en-v1.5` ran over five separate representations: labels;
field-tagged structured context; natural-language context; definition-first
context; and hierarchy-first context. Each representation queried in both
vocabulary directions, and the run unioned candidates rather than averaging
their vectors.

The separate views fail differently. At top 10, label recall was 94.10%,
structured 95.41%, natural context 95.08%, definition-first 90.82%, and
hierarchy-first 96.07%. Their union reached 297/305, or 97.38%, with 82,052
pairs. At top 20 it reached 302/305, or 99.02%, with 139,396 pairs. At top 50
it reached 305/305, or 100%, with 231,826 pairs. The vector digest is
`sha256:15da5889af3db4dae9cc802d2bd2824cae849796ee42d3bdc41b491b1b885531`.

The documented BGE retrieval instruction was then prepended on the query side
for the same five views. It did not improve this symmetric concept-matching
task: the union found 295/305 at top 10 versus 297/305 without the instruction;
both found 302/305 at top 20 and 305/305 at top 50. Several individual views
also lost early recall. The experiment therefore keeps the instruction as an
evaluated alternate arm, not the default. Its vector digest is
`sha256:f585baab82eef46acbfac3a96d532d4e96afcfaae3342e7cb08edb4e791bf88e`;
the output is
`/tmp/refspec-candidate-benchmark.ANhNrc/conference-bge-small-views-bge-prefix-v2.json`,
SHA-256 `0abf014964aa95356cf9283d220cb123f111095cb077351151c1364c53bc0e46`.

A more explicit relation-discovery prompt was also injected into both sides of
the same five views. It reduced early recall further: 295/305 at top 10,
300/305 at top 20, 303/305 at top 50, and 305/305 only at top 100. The plain
symmetric representation remains the stronger BGE arm for this benchmark.
This result matters because extra instructions are not automatically extra
signal; each prompt needs a measured ablation. The relation-prompt vector
digest is
`sha256:098cd73ec51fb2410da68e8c94e312fc4a405f6a7a4228ade869115564f2ad66`;
the output is
`/tmp/refspec-candidate-benchmark.ANhNrc/conference-bge-small-views-relation-prompt-v2.json`,
SHA-256 `0c401b8b4eaec19d5fe23a4739a142022564868ebbfb2adee345cedacf593afe`.

Unioning BGE with deterministic sparse and mutual-top-1 graph retrieval reached
298/305 at top 10 with 102,625 candidates, 302/305 at top 20 with 164,325,
and 305/305 at top 50 with 244,027. The three top-20 misses were:

- CMT `assignedTo` ↔ EKAW `hasReviewer`;
- CMT `hasBeenAssigned` ↔ EKAW `reviewerOfPaper`; and
- Conference `Active_conference_participant` ↔ IASTED `Speaker`.

The complete hybrid output is
`/tmp/refspec-candidate-benchmark.ANhNrc/conference-hybrid-refspec-v2.json`,
SHA-256 `70fc3b7c25b031a21a1a1ee2c99b236666780188d572af5fb579e238426f3fe5`.

### Local dense model-family trial

Four additional local model families ran over the same five separate views.
Each row reports gold found and retained pairs for the union of that model's
five bidirectional views.

| Model and input convention | Top 1 | Top 5 | Top 10 | Top 20 | Top 50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MiniLM, symmetric | 271 / 11,449 | 295 / 50,031 | 301 / 89,426 | 302 / 150,946 | 305 / 239,351 |
| Snowflake Arctic small, query instruction | 269 / 12,233 | 293 / 51,045 | 300 / 89,439 | 302 / 148,822 | 305 / 237,049 |
| Jina v2 small, symmetric | 268 / 10,982 | 293 / 47,692 | 300 / 85,471 | 303 / 144,617 | 305 / 236,286 |
| Nomic v1.5 quantized, query/document prefixes | 275 / 11,212 | 296 / 47,173 | 301 / 84,119 | 304 / 142,065 | 305 / 234,683 |

Nomic supplied the strongest local top-20 result, missing only CMT
`hasBeenAssigned` ↔ EKAW `reviewerOfPaper`. Arctic retrieved that relation at
top 20 and missed a different set, so their top-20 gold union is complete.
The exact pair count for that cross-model union still needs measurement before
it can be compared fairly with provider and sparse unions. This result supports
complementary model families as rescue arms; it does not support simply adding
every model to the production queue.

The evidence outputs, vector digests, and SHA-256 file digests are:

- MiniLM: vector
  `sha256:c71bf767609af8a1b53a57cfed8d957242e5f4957f4855ebd714bcce862ec517`,
  file `7db6605c5de736963a441ca45fc17a80fb832e080654e92d810cf00b4c680844`;
- Arctic: vector
  `sha256:6ca8dcd5a56fd7939361e621030b9880ba2abd296bd21d0e981bc73692809326`,
  file `f3083ccd397340cf22f05584a4b4bc0e4851c1ef0a839df6e3b2aaa1b2bd341e`;
- Jina: vector
  `sha256:8dbafb9148dcde4a2285ae1160a73c800eea3a858df03a8c045c6f4774387d0a`,
  file `30b635998bc1a764bd51cd3fd8f62ac378e9b473854f07c900d7d1293975c89f`;
- Nomic: vector
  `sha256:53ffe746ac7eab05a066bfc3f4d7efba36dc813b9597cb7422716724cc32de5c`,
  file `6d9b653d840290e72c81977b503d928ad9529811f8e337e4ea016369927b8294`.

FastEmbed resolved current model artifacts during this exploratory run. The
vector and result digests seal what ran, while a production policy must also
pin the exact model and tokenizer revisions and their artifact hashes.

### Six-pair Atlas regression and cost frontier

The same dependency-free sparse and mutually anchored graph policy ran against
all six prepared Atlas vocabulary pairs. It evaluated the 582 previously
admitted relations as a regression set while counting candidates for the three
new CRS pairs as well. The corpus digest is
`sha256:20bbceaec514f8681f3a07146e6a30ed5fd731857c586d327ac916d4a523317e`;
the admitted-pair digest is
`sha256:d347a551e205d973d39141ba01548bce35b7f59d0caafccab60a353607bc662d`.

| Bidirectional depth per sparse view | Candidates across six pairs | Known mappings found | Regression recall |
| ---: | ---: | ---: | ---: |
| 5 | 129,614 | 572 / 582 | 98.28% |
| 10 | 236,635 | 578 / 582 | 99.31% |
| 20 | 431,901 | 579 / 582 | 99.48% |
| 50 | 939,860 | 581 / 582 | 99.83% |
| 100 | 1,691,463 | 582 / 582 | 100% |

At top 10, the four misses are one ELSST–ICPSR pair, two Federal Register–ELSST
pairs, and one Federal Register–ICPSR pair. At top 20, three remain; top 50
leaves one Federal Register–ELSST pair. This is a strong improvement over the
12,313-row label-oriented catalog, and it is still too large to judge blindly
at the 100-deep regression guarantee. Additional candidate arms should rescue
the four top-10 misses rather than simply widening every source to 100.

The full result is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-sparse-refspec-v2.json`, SHA-256
`2ccff03704e2f7d2da8d56b1523afdcfef1cc1060287aa58ce6685beba2e628a`.

### Anatomy sparse and BGE stress trial

The fixed sparse plus mutually anchored graph policy was rerun on all 1,516
Anatomy reference relations. It reached 1,468/1,516 at top 10, 1,481/1,516 at
top 20, 1,497/1,516 at top 50, and 1,499/1,516 at top 100. Candidate counts
were 126,062, 210,350, 459,123, and 846,312 respectively. This is the
cost-bounded graph result; the earlier permissive graph trial's higher recall
came from retaining millions of pairs.

The sparse output is
`/tmp/refspec-candidate-benchmark.ANhNrc/anatomy-sparse-refspec-v2.json`,
SHA-256 `5dd84a5e391a515d6d1d1f20eae920ce982258d429915967c42803f070803bc9`.

Five symmetric BGE views then ran in exact bidirectional mode. The dense-only
view union and its add-only union with sparse and graph were:

| Depth | BGE views found / candidates | Combined found / candidates |
| ---: | ---: | ---: |
| 1 | 1,424 / 12,899 | 1,450 / 61,889 |
| 5 | 1,492 / 62,853 | 1,500 / 127,783 |
| 10 | 1,500 / 122,818 | 1,504 / 210,384 |
| 20 | 1,507 / 238,712 | 1,509 / 373,016 |
| 50 | 1,510 / 558,536 | 1,511 / 825,852 |
| 100 | 1,513 / 1,036,952 | 1,514 / 1,499,006 |

The combined top-100 union misses only `myelencephalon` ↔
`Medulla Oblongata` and `penis foreskin` ↔ `Male Prepuce`. They are biomedical
synonym cases with weak lexical overlap, making them appropriate tests for
SapBERT, ontology synonym resources, and learned-sparse rescue rather than
just a deeper general-purpose BGE cutoff.

This run used the original set-based harness and took 1,203.275 seconds. Its
observed resident memory exceeded 10 GiB while it retained duplicate
view/depth candidate sets. A concurrently started Nomic Anatomy run was killed
with exit status 137 before producing output. The experiment therefore changed
the engineering direction: Anatomy-scale model runs must be sequential, use
fixed query blocks, and retain compact minimum ranks rather than Python string
tuples at every depth. The later exact-memory experiment records the completed
memory-bounded regression.

The BGE vector digest is
`sha256:1494267c6b5174d0542777ac965376831cc1ee6dfe2819f24859bd1d6e00d3ca`.
The full output is
`/tmp/refspec-candidate-benchmark.ANhNrc/anatomy-bge-hybrid-v2.json`, SHA-256
`3d3709afa20ab126117873c45478b11dfbaadfc9ff614b983c1043cf02c4055e`.

#### Corrected OBO text resolution and before/after result

Inspection of the remaining synonym misses found a benchmark-adapter issue,
not a retrieval failure. Anatomy represents many OBO synonyms and definitions
as URI references to `genid` description nodes; the human text is the
referenced node's `rdfs:label`. The original adapter embedded the node IRI.
Adapter revision
`e87be005dcb2e2a3287ecee1ecf864c869310c3b623b472a2866da9610437628`
now resolves that label and never treats the provenance IRI as concept text.
A focused RDF fixture plus all retrieval tests pass, 12/12.

This intentionally creates a new corpus digest,
`sha256:f679f82140e5c0de18a63765505ebb28fc540d4a63b0abd5fe53d7d624715f00`;
the gold digest remains
`sha256:06e799bc6e35df5eef97bfdc8ec9fcc3f60a0a375503b01085bda5c5df13bd03`.
All earlier results remain sealed under their text-poor corpus digest and are
reported as the before case. No aggregate mixes the two input versions.

Sparse plus mutually anchored graph retrieval improved while retaining fewer
pairs:

| Depth | Text-poor found / candidates | Resolved-text found / candidates |
| ---: | ---: | ---: |
| 5 | 1,438 / 84,635 | 1,486 / 80,402 |
| 10 | 1,468 / 126,062 | 1,503 / 117,009 |
| 20 | 1,481 / 210,350 | 1,510 / 190,468 |
| 50 | 1,497 / 459,123 | 1,511 / 396,667 |
| 100 | 1,499 / 846,312 | 1,513 / 698,684 |

The corrected sparse top-20 result is 99.60%, clearing the independent 99.5%
target. It also retrieves both previously highlighted biomedical synonym
pairs. Its result file is
`/tmp/refspec-candidate-benchmark.ANhNrc/anatomy-sparse-refspec-v3-resolved-obo-text.json`,
SHA-256 `b5253490147706bd380871af1a9358bc46e04bd28e04887d45a7a51bd1f71641`.

The five BGE views were then regenerated over exactly the corrected corpus.
The combined add-only union reached 1,513/1,516 at top 10 with 183,989 pairs,
1,515/1,516 at top 20 with 321,874, and 1,516/1,516 at top 50 with 712,254.
The one top-20 miss is Mouse Anatomy `MA_0001246` ↔ NCI `C32454`; top 50 has
none. Dense-only BGE also reached all 1,516 at top 50.

The corrected vector digest is
`sha256:975d57e80b03c1cf99a3b8a0d47e18beed420071ae1e3277875f3e0dca1121ed`.
The full output is
`/tmp/refspec-candidate-benchmark.ANhNrc/anatomy-bge-hybrid-v3-resolved-obo-text.json`,
SHA-256 `bb01b76b6742769645e63e1d4c8b02df16e7b153673d11125874fa3cb724d428`.
The compact-rank harness reduced elapsed time from 1,203.275 to 690.692
seconds for this five-view Anatomy run. FastEmbed still held roughly 11 GiB
resident during the run, so future multi-view model processes remain
sequential even though candidate accounting is compact.

### Interpretation and next decision

Multiple representations materially improve recall and justify field-specific
candidate arms. They also show why a fixed top-50 union is not yet an
acceptable production answer: it covers Conference completely by retaining
about 90% of that track's Cartesian pairs. The next experiments seek the same
coverage with fewer candidates by adding provider embeddings, learned sparse
expansion, WordNet/ontology matchers, and reranker rescue, then measuring each
arm's unique gold and candidates per rescued relation. Graph expansion will
remain anchor-quality gated. No paid LLM scoring or judging starts until that
frontier and the six real Atlas pair costs are recorded.

## Experiment log — Google and OpenAI embeddings (Euler)

Recorded: 2026-08-05 06:50:16 EDT. Status: complete for the five declared
provider arms and the small OpenAI asynchronous Batch API check.

### Pinned inputs and method

This run independently regenerated the declared OAEI Conference adapter before
calling either provider. It parsed OWL classes, object properties, and datatype
properties from `cmt`, `confOf`, `conference`, `edas`, `ekaw`, `iasted`, and
`sigkdd`. Each of the 802 concepts used this fixed text order: preferred label,
alternate labels, local identifier, definition, parents, and children. The 21
reference files supplied 305 unique gold pairs. Every arm evaluated exact
cosine search in both ontology directions and counted a gold pair when either
direction retrieved it at depth K.

- Conference archive SHA-256:
  `78688cda05857b594be188db6831abc5d890d2e38d6602e0cd8d3c82ecb24546`.
- Reference-alignment archive SHA-256:
  `782e0175253d817288e1f7ed29f738a7fa9e57a8b9c77bb3b11c12b80405d4bf`.
- Canonical corpus SHA-256:
  `3e4474e490673b2c25c28b27bdf5a6b0dafb74e711d2ab00c1df7554958f86e4`.
- Canonical gold SHA-256:
  `43d476e4414a95998f26659ee6cc2853239f38a7e5222879675fdc7ca6ebc0ef`.
- Shared output dimension: 768. Synchronous calls used multi-input chunks of
  50, which produced 17 requests for a symmetric pass and 34 for distinct
  query and document passes.

The five arms were:

- OpenAI `text-embedding-3-small` and `text-embedding-3-large`, each with the
  same structured concept text on both sides;
- Google `gemini-embedding-001` with `SEMANTIC_SIMILARITY` on both sides;
- Google `gemini-embedding-001` with `RETRIEVAL_QUERY` and
  `RETRIEVAL_DOCUMENT`; and
- Google `gemini-embedding-2` with its documented retrieval instructions in
  the text (`task: search result | query: ...` and
  `title: ... | text: ...`). This model does not take the earlier model's
  `taskType` field.

The model-list checks, exact redacted requests, raw responses, matrix shapes,
normalized vector files, full gold ranks, and pair-set digests are retained in
`/tmp/refspec-candidate-benchmark.ANhNrc/evidence`. Provider aliases were
available at execution time; the retained output and matrix digests pin this
specific run even where an alias is not a dated model revision.

### Recall and candidate counts

Each cell reports `gold found / retained candidate pairs (recall)`.

| Arm | @1 | @2 | @3 | @5 | @10 | @20 | @50 | @100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Google 001 retrieval | 271 / 4,265 (88.85%) | 289 / 8,256 (94.75%) | 294 / 12,123 (96.39%) | 299 / 19,692 (98.03%) | 300 / 37,906 (98.36%) | 300 / 72,343 (98.36%) | 305 / 164,413 (100%) | 305 / 256,790 (100%) |
| Google 001 semantic similarity | 270 / 4,241 (88.52%) | 284 / 8,282 (93.11%) | 290 / 12,187 (95.08%) | 295 / 19,755 (96.72%) | 298 / 38,325 (97.70%) | 301 / 74,039 (98.69%) | 303 / 168,524 (99.34%) | 305 / 257,788 (100%) |
| Google 2 retrieval instruction | 276 / 4,229 (90.49%) | 289 / 8,228 (94.75%) | 292 / 12,099 (95.74%) | 299 / 19,582 (98.03%) | 299 / 37,669 (98.03%) | 303 / 71,833 (99.34%) | 305 / 164,463 (100%) | 305 / 256,382 (100%) |
| OpenAI large | 258 / 4,244 (84.59%) | 284 / 8,224 (93.11%) | 289 / 12,004 (94.75%) | 291 / 19,352 (95.41%) | 296 / 36,894 (97.05%) | 301 / 70,001 (98.69%) | 305 / 161,555 (100%) | 305 / 255,783 (100%) |
| OpenAI small | 254 / 4,319 (83.28%) | 273 / 8,388 (89.51%) | 285 / 12,328 (93.44%) | 288 / 19,908 (94.43%) | 291 / 38,153 (95.41%) | 297 / 72,618 (97.38%) | 304 / 165,322 (99.67%) | 305 / 257,151 (100%) |
| Five-arm union | 292 / 9,633 (95.74%) | 296 / 18,190 (97.05%) | 299 / 26,177 (98.03%) | 300 / 41,011 (98.36%) | 300 / 74,032 (98.36%) | 305 / 128,606 (100%) | 305 / 229,041 (100%) | 305 / 269,110 (100%) |

### Token usage, batching, and cost

| Arm | Requests | Input tokens | Token evidence | Published list-price cost |
| --- | ---: | ---: | --- | ---: |
| Google 001 retrieval | 34 | 124,910 | conservative UTF-8 bytes / 2; responses omitted usage metadata | $0.018736500 |
| Google 001 semantic similarity | 17 | 62,455 | conservative UTF-8 bytes / 2; responses omitted usage metadata | $0.009368250 |
| Google 2 retrieval instruction | 34 | 72,567 | provider-reported usage metadata | $0.014513400 |
| OpenAI large | 17 | 28,527 | provider-reported prompt tokens | $0.003708510 |
| OpenAI small | 17 | 28,527 | provider-reported prompt tokens | $0.000570540 |

The five benchmark arms cost **$0.046897200** at published standard prices.
The pre-call plan estimated $0.066366400 for one pass through every arm and
reserved $0.132732800 for a retry of every call, safely within the $0.25
ceiling. Actual execution completed without retries or provider errors.

A separate OpenAI Batch API smoke check placed two structured texts in one
JSONL request line. `text-embedding-3-small` completed one of one request with
zero failed rows, returned a `[2, 768]` matrix, reported 62 input tokens, and
cost **$0.000000620** at the published Batch price. The combined run cost was
**$0.046897820**. The first validation attempt used a one-hour input-file
lifetime; OpenAI's validator required the file to remain available for at
least the 24-hour completion window and processed zero rows. The successful
submission used a 48-hour lifetime. Future Batch preflight can enforce that
minimum before upload.

### Evidence and integrity

- Benchmark result:
  `/tmp/refspec-candidate-benchmark.ANhNrc/benchmark-result.json`, SHA-256
  `4cf714671d7a72435ec06183c518eef5ced72cf25effb5ca7351686e115db0aa`.
- Human-readable benchmark report:
  `/tmp/refspec-candidate-benchmark.ANhNrc/benchmark-report.md`, SHA-256
  `58daf262d1cd202b32bba67e76f5bdb9169d5ddf3fb757bc2c9167b630db1f95`.
- Evidence-file SHA-256 index:
  `/tmp/refspec-candidate-benchmark.ANhNrc/evidence-sha256.txt`, SHA-256
  `28f983165355217e108660850f2b9adffabc9b92ae7c453454479341de17b18e`.
- Successful asynchronous Batch result:
  `/tmp/refspec-candidate-benchmark.ANhNrc/evidence/openai-text-embedding-3-small-async-batch-smoke/result.json`,
  SHA-256
  `cf146d009904d06d3f6cf8ff57d8c0f019528d6d8acf82b0f3f605a5023200b2`.
- Recovered Batch validation evidence:
  `/tmp/refspec-candidate-benchmark.ANhNrc/evidence/openai-text-embedding-3-small-async-batch-smoke-attempt-1-invalid-expiration/polls/0013.json`,
  SHA-256
  `1d93f7d7ea38a53ea026b879583df47c8f0369efee42102d7a853b2362bc5279`.

The evidence index covers 448 request, response, vector, rank, model-discovery,
Batch lifecycle, and result files. Final secret scanning checked those files
plus nine benchmark artifacts: 457 files produced zero exact-key matches and
zero API-key-format matches in text. API keys remain solely in the external
`.env` file.

### Interpretation and next decision

Google 2 provided the strongest single-arm first position at 276/305, or
90.49%, and reached 303/305 by top 20. Google 001 retrieval led the single arms
at top 3 with 294/305 and reached 299/305 at top 5. Their different miss sets
make multiple semantic views useful: the five-arm union found 292/305 at top 1,
300/305 at top 5, and all 305 at top 20.

The union supplies a complete Conference discovery set at 128,606 candidate
pairs. The next decision is to combine these provider views with the existing
deterministic sparse, graph, and BGE arms, measure each arm's unique rescues,
and promote a staged policy: compact high-confidence depths first, followed by
targeted rescue depths for the remaining concepts. This converts the observed
complementarity into a smaller judging queue while retaining the complete
top-20 union as a measurable safety floor. The same policy can then run on the
six Atlas vocabulary pairs and Anatomy to select a release-ready frontier.

## Experiment log — reranker and late-interaction trial (Mill)

Recorded: 2026-08-05 07:01:32 EDT. Status: complete for the bounded OAEI
Conference development trial. The run used pinned local models on Apple MPS.
It made no provider inference calls and incurred no provider cost; network use
was limited to downloading the pinned public Hugging Face model snapshots.

### Question and fixed inputs

This experiment tested two separate uses of a learned scorer after candidate
generation:

1. **Prioritization within the reservoir:** retain only each scorer's
   bidirectional top K. This measures ordering quality but may discard another
   candidate arm.
2. **Add-only rescue:** union each scorer's bidirectional top K with the fixed
   baseline. This measures newly recovered gold while preserving every
   deterministic and dense arm. This is the production-safe mode.

The canonical 802-concept, 21-pair Conference corpus contains 305 gold
relations. Corpus SHA-256 is
`3e4474e490673b2c25c28b27bdf5a6b0dafb74e711d2ab00c1df7554958f86e4`;
gold SHA-256 is
`43d476e4414a95998f26659ee6cc2853239f38a7e5222879675fdc7ca6ebc0ef`.

The fixed baseline unions all current lexical arms—normalized preferred-label
equality, alternate-label equality, preferred-label token containment, and
preferred-label edit distance at most two—with bidirectional top 10 from three
exact sparse views and bidirectional top 20 from BGE structured text. The
sparse views are label word TF-IDF with word one- and two-grams, structured
context word TF-IDF with word one- and two-grams, and label character TF-IDF
with `char_wb` three- through five-grams. The baseline retained 125,228 unique
pairs and found 299/305 gold, or 98.03%.

The deliberately wide reservoir unions all lexical arms with bidirectional top
100 from every sparse view and BGE. It retained 270,727 pairs and contained all
305 gold relations. A second independent build produced the same reservoir
SHA-256,
`21bd0cb5d6da6d17b9baf55c8a54046e9e98d8fd0681e7bd2196eea5a1bf55a3`.
The build took 6.32 seconds and peaked at 1,399,160,832 bytes, about 1.30 GiB.

This reservoir is intentionally a recall testbed rather than a deployable
frontier. Conference's ontologies are small enough that top 100 covers
270,727/270,760, or 99.9878%, of the pairwise Cartesian space. The scorers
therefore demonstrated ranking and add-only rescue from a complete reservoir;
they did not demonstrate economical candidate discovery. Each model scored
4,812 directional query jobs containing 535,389 query-candidate pairs.

The reservoir used `BAAI/bge-base-en-v1.5` revision
`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`, snapshot SHA-256
`f03adc534aa7e3e3a2e163748e56f2bc0205dc7c23ae3e17cb7bf23372dfad78`.
For reference, its standalone bidirectional structured-text arm found 290/305
at top 10 with 39,922 pairs, 297/305 at top 20 with 76,333, 303/305 at top 50
with 171,651, and 305/305 at top 100 with 258,366.

### Pinned learned scorers

- Cross-encoder: `cross-encoder/ms-marco-MiniLM-L6-v2`, revision
  `c5ee24cb16019beea0893ab7796b1df96625c6b8`, seven-file snapshot SHA-256
  `b6fe76adc6691141d07f0f8c81b950504884d8d91c9714ac2fd5482250416f3c`.
  It scored 535,389 pairs in 370.810 seconds and peaked at 957,399,040 bytes,
  about 913 MiB.
- Late interaction: `answerdotai/answerai-colbert-small-v1`, revision
  `c72aa89bc61afdd85373643f3a1a75b2aad6e0fe`, nine-file snapshot SHA-256
  `16af20c6b9bb90eb597522369a51bf6b0247428274dd041ce85565d261ae62c0`.
  `rerankers==0.10.0` cached each document's 96-dimensional token embeddings
  once, then applied ColBERT maximum-similarity scoring. Its implementation
  source SHA-256 is
  `45aeb84b5b7987887d9b5ef6c7a17bba94ceed5080f9451328b2957cb73fb0ae`.
  It scored the same 535,389 pairs in 21.848 seconds. Internal peak RSS was
  1,485,471,744 bytes, about 1.38 GiB; the conservative external measurement
  was 1,590,542,336 bytes, about 1.48 GiB.

The cross-encoder was about 17 times slower in this implementation, while the
cached late-interaction scorer used more peak memory. These are local benchmark
measurements, not general model-family guarantees.

### Prioritization and add-only rescue results

Each row reports `candidates / gold found`. “Rescued” counts gold relations
missing from the 125,228-pair baseline. Every add-only result records
`baselinePreserved: true`; neither scorer removes a lexical, sparse, graph, or
dense arm.

| Model | K | Prioritization only | Baseline plus scorer top K | Unique gold rescued |
| --- | ---: | ---: | ---: | ---: |
| MiniLM cross-encoder | 1 | 4,355 / 229 | 125,493 / 299 | 0 |
| MiniLM cross-encoder | 5 | 20,142 / 281 | 127,777 / 299 | 0 |
| MiniLM cross-encoder | 10 | 38,695 / 288 | 132,640 / 299 | 0 |
| MiniLM cross-encoder | 20 | 74,136 / 295 | 146,455 / 302 | 3 |
| MiniLM cross-encoder | 25 | 91,367 / 299 | 154,558 / 305 | 6 |
| MiniLM cross-encoder | 50 | 171,525 / 303 | 200,800 / 305 | 6 |
| AnswerAI ColBERT | 1 | 4,381 / 231 | 125,524 / 299 | 0 |
| AnswerAI ColBERT | 5 | 20,241 / 282 | 128,243 / 299 | 0 |
| AnswerAI ColBERT | 10 | 38,796 / 290 | 133,489 / 299 | 0 |
| AnswerAI ColBERT | 20 | 73,792 / 292 | 148,058 / 299 | 0 |
| AnswerAI ColBERT | 25 | 90,416 / 298 | 156,454 / 301 | 2 |
| AnswerAI ColBERT | 50 | 167,462 / 304 | 200,764 / 305 | 6 |

ColBERT gave slightly stronger low-depth prioritization, including 290/305 at
top 10 versus MiniLM's 288/305, and completed much faster with cached document
tokens. MiniLM provided the better moderate-depth rescue frontier: it recovered
all six baseline misses by bidirectional top 25, adding 29,330 candidates.
ColBERT needed top 50 and 75,536 added candidates to recover the same six. No
scorer recovered a baseline miss at top 10.

### Candidate-kind findings

These findings classify only the six baseline misses, not all 305 gold
relations. Zero opportunities mean this development set cannot establish the
model's ability for that kind.

| Candidate kind | Opportunities among six misses | Defensible result |
| --- | ---: | --- |
| Lexical or alternate-label | 0 | The baseline already carried preferred-label equality, alternate-label equality, containment, edit distance, and three sparse views. No remaining miss had a useful alternate label. |
| Shared identifier | 0 | No hard pair shared a normalized terminal identifier. |
| Abbreviation | 0 | No hard pair was an acronym-expansion relation. |
| Definition or semantic | 1 semantic; 0 useful-definition | `Passive conference participant` ↔ `Listener` has no definition text on either endpoint. MiniLM rescued the semantic pair at K=25; ColBERT rescued it at K=50. |
| Hierarchy or graph | 0 isolated | The semantic pair has parents `Conference participant` and `Delegate`, but no matched cross-vocabulary hierarchy anchor. The rescue cannot be attributed to graph evidence. |
| Broader, narrower, or granularity | 1 wording-granularity case | The same role pair differs in wording granularity, but the OAEI reference declares equality. It is not an independently typed broader/narrower test. |
| Inverse or directional property wording | 5 | MiniLM rescued 3/5 at K=20 and 5/5 at K=25. ColBERT rescued 0/5 at K=20, 2/5 at K=25, and 5/5 at K=50. “Directional” describes label morphology; the OAEI reference declares equality and does not prove an inverse predicate. |
| Translation | 0 | Out of scope for the English-only production task; retained here only as historical benchmark metadata. |

The exact bidirectional ranks make the difference visible:

| Gold relation | Kind | MiniLM forward / reverse / best | ColBERT forward / reverse / best |
| --- | --- | ---: | ---: |
| `hasAuthor` ↔ `writtenBy` | directional property wording | 21 / 22 / 21 | 21 / 31 / 21 |
| `hasBeenAssigned` ↔ `reviewes` | directional property wording | 25 / 74 / 25 | 47 / 44 / 44 |
| `assignedTo` ↔ `isReviewedBy` | directional property wording | 11 / 45 / 11 | 63 / 41 / 41 |
| `hasAuthor` ↔ `isWrittenBy` | directional property wording | 30 / 19 / 19 | 32 / 25 / 25 |
| `hasBeenAssigned` ↔ `reviewerOfPaper` | directional property wording | 11 / 63 / 11 | 49 / 68 / 49 |
| `Passive conference participant` ↔ `Listener` | semantic and wording granularity | 43 / 25 / 25 | 75 / 28 / 28 |

### Evidence, resource behavior, and decision

All experiment outputs remain under
`/tmp/refspec-candidate-benchmark.ANhNrc/rerank-trial`; no repository code was
edited for this trial. This ledger entry is the only repository file changed
by this experiment.

- Reproducible experiment script SHA-256:
  `7a1597b97ae7d9f33dcf7943556745f609e8505989721ba0ae122153e1219e70`.
- Reservoir result SHA-256:
  `3380fbf4c4d3bd09042855de5007d71c40d35a27dd54d5e1a45aaf912536c664`.
- Cross-encoder result and ranking SHA-256:
  `2b6dc1762950154612f017ebbd14f1aebc2374a2d1067da203bf91e9680e4a3a`
  and
  `1ca8b8941f40a8413761db6091695355acddd93c092c1e25ad251581dabd5e58`.
- ColBERT result and ranking SHA-256:
  `c0c226575b3d7de4681ad1441e93cd8a1d6d7b2500b0bbc21c1ff980398fbb47`
  and
  `e344d914beecf0277f26382188173d5dac5afa19d49792daeab1dac997218448`.
- Combined machine-readable result SHA-256:
  `7b2a442a63b2389e7623b9040a4d08bbc343b3f2b019435935efc82dd7efb1f8`;
  report SHA-256:
  `bcd5ab759c4574a26b45ce9b4bb46685cae4062d5d4c54759b80db676f6aa43a`;
  relation-kind analysis SHA-256:
  `2a51f7920bb22d1b1193341faf47909c3030b8cc7cce5beba960f573e909f00b`.

At append time, a separate exact Anatomy BGE run was using about 6.4 GB and
high CPU, and a concurrent Nomic Anatomy run had been terminated by the
operating system for memory pressure. This task therefore started no additional
Anatomy dense or reranking run. The completed Conference evidence remained
available without loading either learned scorer again.

The positive implementation direction is an **add-only rescue arm**. For this
development set, MiniLM at bidirectional K=25 is the strongest measured
moderate-depth option; cached ColBERT is a fast prioritization or complementary
option, with complete rescue at K=50. This is evidence to carry into the next
benchmark, not yet a release threshold. Conference's near-Cartesian reservoir
and lack of typed broader/narrower, abbreviation, shared-identifier,
and isolated hierarchy cases require confirmation on Anatomy and the six real
Atlas vocabulary pairs before adoption. Rerankers continue to prioritize or
add potential relations only. The paid judging stage still classifies every
retained pair and determines relation type and direction.

## Experiment log — lexical controls and candidate-kind coverage (Euler)

Recorded: 2026-08-05 07:11:56 EDT. Status: complete for the full OAEI
Conference lexical-control matrix and its 305-relation candidate-kind pool.
This local run made no provider calls and incurred no provider cost. Anatomy
and the six Atlas pairs remain queued behind the active Anatomy model run so
the workstation can complete each large experiment with bounded memory.

### Fixed method and implementation

The new standalone tool,
`tools/benchmark_lexical_candidate_controls.py`, imports the existing OAEI and
Atlas input adapters without editing their shared benchmark. It checks the
adapter's SHA-256 before and after each run and refuses a run whose adapter
changes in flight. The Conference input contains 802 concepts, 21 ontology
pairs, and 305 expert gold relations. Its adapter corpus SHA-256 is
`8fdba504058d3011dcc2219e1b9277c5f8c1ef331fad4482e4a86059daec1df1`;
its gold SHA-256 is
`63c2feb19ed1352ccaae8efe897e3f5a3c917db07b7b21324d9f97936282177e`.

Every arm performs exact top-K retrieval in both directions and unions the
two directions. Each scorer declares whether larger or smaller values rank
first. Canonical member-IRI order breaks score ties. RapidFuzz 3.14.3 converts
similarities to deterministic integer scores. The tool processes 128 query
rows at a time, so Anatomy and Atlas runs need no full Cartesian score matrix.
Each arm records its feature-vector digest, ranking digest, runtime, and
candidate pair-set digest at K = 1, 2, 3, 5, 10, 20, 50, and 100.

The 17 arms cover raw Levenshtein distance, normalized Levenshtein similarity,
RapidFuzz `ratio`, `partial_ratio`, `token_sort_ratio`, `token_set_ratio`,
`WRatio`, and `QRatio`, Jaro, Jaro-Winkler, compact-label Jaro-Winkler,
pre-sorted token QRatio, preferred-plus-alternate-label token-set and WRatio,
local-identifier QRatio, acronym token-set ratio, and boundary-padded character
trigram token-set ratio. Four small unions keep edit, RapidFuzz label,
field-variant, and all-control evidence separate.

Four focused tests prove ascending distance, descending similarity, canonical
tie-breaking, and identical rankings and digests after reversing source and
target input sequences. They passed in 0.69 seconds. Ruff and Python compilation
also pass.

### Complete Conference controls

Each cell reports `gold found / retained candidate pairs`. The machine result
contains the omitted K = 2, 3, and 5 rows for every arm.

| Arm | @1 | @10 | @20 | @50 | @100 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Levenshtein distance | 193 / 4,321 | 256 / 40,453 | 269 / 78,806 | 294 / 178,014 | 303 / 260,841 |
| Normalized Levenshtein | 207 / 4,100 | 257 / 33,866 | 262 / 64,303 | 280 / 152,094 | 303 / 252,580 |
| RapidFuzz ratio | 215 / 4,095 | 260 / 33,961 | 266 / 64,807 | 282 / 153,931 | 299 / 253,510 |
| RapidFuzz partial ratio | 196 / 4,302 | 262 / 34,635 | 268 / 65,051 | 283 / 151,575 | 301 / 252,328 |
| RapidFuzz token-sort ratio | 217 / 4,063 | 260 / 33,732 | 270 / 64,670 | 282 / 154,232 | 299 / 253,635 |
| RapidFuzz token-set ratio | 202 / 4,235 | 263 / 34,223 | 270 / 65,018 | 283 / 154,138 | 299 / 253,627 |
| RapidFuzz WRatio | 220 / 4,271 | 261 / 34,748 | 268 / 64,902 | 285 / 152,040 | 300 / 252,529 |
| RapidFuzz QRatio | 215 / 4,095 | 260 / 33,961 | 266 / 64,807 | 282 / 153,931 | 299 / 253,510 |
| Jaro | 190 / 4,065 | 222 / 33,265 | 234 / 64,281 | 262 / 152,656 | 303 / 252,890 |
| Jaro-Winkler | 190 / 4,070 | 222 / 33,268 | 234 / 64,281 | 262 / 152,656 | 303 / 252,890 |
| Compact Jaro-Winkler | 193 / 4,064 | 224 / 33,239 | 233 / 63,961 | 269 / 152,156 | 301 / 252,529 |
| Token-sorted QRatio | 217 / 4,063 | 260 / 33,732 | 270 / 64,670 | 282 / 154,232 | 299 / 253,635 |
| Alias-bag token-set ratio | 202 / 4,235 | 263 / 34,223 | 270 / 65,018 | 283 / 154,138 | 299 / 253,627 |
| Alias-bag WRatio | 220 / 4,271 | 261 / 34,748 | 268 / 64,902 | 285 / 152,040 | 300 / 252,529 |
| Identifier QRatio | 215 / 4,095 | 260 / 33,961 | 266 / 64,807 | 282 / 153,931 | 299 / 253,510 |
| Acronym token-set ratio | 136 / 4,133 | 198 / 35,775 | 242 / 67,140 | 285 / 160,507 | 304 / 256,488 |
| Character-trigram token-set ratio | 225 / 4,208 | 261 / 34,210 | 268 / 65,213 | 287 / 154,244 | 302 / 253,954 |

Character trigrams provided the strongest single-arm first position: 225/305,
or 73.77%. Token-set ratio provided the strongest single-arm top-10 result:
263/305, or 86.23%. Its alias-bag arm produced the same result because these
Conference files supplied no alternate labels. The identifier arm likewise
repeated QRatio because the adapter derives labels from the same local
identifiers when explicit labels are absent.

| Union | @1 | @2 | @3 | @5 | @10 | @20 | @50 | @100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Edit controls | 224 / 8,479 | 240 / 15,630 | 253 / 22,444 | 258 / 35,506 | 264 / 66,053 | 279 / 119,644 | 299 / 226,672 | 305 / 268,996 |
| RapidFuzz labels | 244 / 9,387 | 258 / 17,103 | 260 / 24,058 | 262 / 36,444 | 267 / 63,675 | 276 / 109,969 | 289 / 203,960 | 301 / 263,604 |
| Field variants | 240 / 12,399 | 260 / 22,847 | 263 / 32,584 | 263 / 50,243 | 272 / 87,498 | 281 / 145,175 | 300 / 239,605 | 305 / 269,583 |
| All lexical controls | 251 / 17,081 | 262 / 30,592 | 263 / 42,909 | 265 / 64,799 | 274 / 109,604 | 288 / 173,444 | 304 / 255,612 | 305 / 270,538 |

At top 10, the acronym arm uniquely rescued three relations:
`Participant` ↔ `Attendee`, `Event` ↔ `Activity`, and `Conference www` ↔
`Web Site`. Raw edit distance uniquely rescued `Scholar` ↔ `Student`;
normalized Levenshtein uniquely rescued `assignedTo` ↔ `isReviewedBy`.
These five rescues show that low aggregate accuracy can still add useful
coverage to a union.

The lexical union reaches 274/305 at top 10 and 288/305 at top 20. It reaches
304/305 at top 50; the remaining relation is `Conference proceedings` ↔
`Publication`. Top 100 finds all 305 by retaining 270,538 pairs, a nearly
Cartesian result. Lexical scoring therefore supplies strong, cheap controls
and distinct rescue evidence. Semantic and graph arms remain essential for an
economical complete frontier.

Jaro and Jaro-Winkler supplied the weakest top-10 ordering at 222/305. Compact
normalization raised that result only to 224/305. Plain QRatio repeated ordinary
ratio; token-sorted QRatio repeated token-sort ratio. Conference's absent
alternate labels, label-derived local identifiers, and English-only content
also prevented the alias and identifier-code variants from demonstrating
independent value. Translation is outside the English-only Atlas v1 production
scope; its historical zero-opportunity row below does not enter selection,
cost, or acceptance. These controlled repetitions define a useful pruning
baseline rather than a release configuration.

### Candidate-kind pool and coverage

The run rule-labeled all 305 expert gold relations. This is a multi-label
retrieval-diagnostics pool, not a second mapping judgment. Each row keeps the
OAEI mapping relation in `mappingRelationSemantic` and surface retrieval
challenges in `retrievalChallenges`. All 305 Conference mappings assert exact
equivalence; the broader, narrower, granularity, and directional challenge
labels describe wording or retrieval difficulty rather than changing that
expert relation.

The classifier uses only reproducible observations: normalized preferred and
alternate labels, local identifiers, acronym keys, edit and token scores,
definition-token overlap, and parent/child label scores. Categories may
overlap. `semantic-gap` means the declared fields provide weak observable
evidence; it does not claim that text embeddings alone can prove the relation.

| Retrieval challenge | Relations | Best single arm @10 | All-control union @10 | All-control union @20 |
| --- | ---: | ---: | ---: | ---: |
| Lexical exact | 140 | 140 / 140 | 140 / 140 | 140 / 140 |
| Lexical near | 26 | 26 / 26 | 26 / 26 | 26 / 26 |
| Alias or synonym | 0 | untested | untested | untested |
| Identifier or code | 0 | untested | untested | untested |
| Abbreviation | 21 | 21 / 21, acronym token-set | 21 / 21 | 21 / 21 |
| Definition or semantic | 0 | untested | untested | untested |
| Hierarchy or graph | 40 | 27 / 40, token-set | 32 / 40 | 34 / 40 |
| Broader, narrower, or granularity wording | 58 | 58 / 58, token-set | 58 / 58 | 58 / 58 |
| Inverse or directional property wording | 10 | 8 / 10, partial ratio | 8 / 10 | 8 / 10 |
| Translation or cross-lingual | 0 | out of scope | out of scope | out of scope |
| Compound or compositional | 58 | 58 / 58, token-set | 58 / 58 | 58 / 58 |
| Token reordered | 3 | 3 / 3, acronym token-set | 3 / 3 | 3 / 3 |
| Substring or fragment | 57 | 57 / 57, token-set | 57 / 57 | 57 / 57 |
| Semantic gap | 64 | 35 / 64, token-set | 41 / 64 | 53 / 64 |

The zero-opportunity rows reflect this dataset's observable fields. The
translation row is historical benchmark metadata and outside Atlas v1. The
remaining rule labels support repeatable slice analysis and targeted manual
review without changing the expert gold mapping relations.

### Evidence and next decision

The final run completed in 16.741 seconds; an independent repeat completed in
15.293 seconds. After removing runtime fields, both runs produced deterministic
result SHA-256
`c35a038ea786cb2efd7ba8ad4a98071494c8aef7829e47ca339f7e71eb32523d`.
The two labeled-pool files are byte-identical.

- Benchmark tool SHA-256:
  `30b466c517ab11df9a31314ffa3aa0299898670057f910bc1a0ea8b153737d25`.
- Focused test SHA-256:
  `5483531870140cbed14bf8443c0e11a6cd762972faab6c38cfa5a9693c911cb2`.
- Main result:
  `/tmp/refspec-candidate-benchmark.ANhNrc/lexical-controls-conference.json`,
  SHA-256
  `98b2a94cc93b4fa2e9e233fa30edea90bfeed884d101ae4facb39ff2b20940f3`.
- Repeat result:
  `/tmp/refspec-candidate-benchmark.ANhNrc/lexical-controls-conference-repeat.json`,
  SHA-256
  `78fae3796b10f8ccd150a7397e01bbe55557dce0a1e7db4c8eace14fa03d8dce`.
- Candidate-kind pool:
  `/tmp/refspec-candidate-benchmark.ANhNrc/candidate-kind-pool-conference.json`,
  file SHA-256
  `14ef9b59b02edc8b7c0d7663893ba81006dd56353299851740618352e4a933c8`;
  canonical relation-pool SHA-256
  `cdf70157f1201c64d9a11db901262b622b51e3dcb6964547de47dfab9a62e129`.
- All-control candidate pair-set SHA-256 values: top 10
  `d21e54833c9544ca5f478904b616b7f2eeaaa0677201c05de1cc189665bd4a8b`,
  top 20
  `9e7a8a65764aa81927943da8e92546260dbde6add35bf69a2e348a31fcffa85e`,
  top 50
  `b380795825186c4e9ec9d4505ceb54fb624fb7e2669899dcf4d012b7400e3f46`,
  and top 100
  `1dd94dd380fea20187a0728c9a4e74449c93784fce4e60c5e5c1155198e1e3ac`.

The next decision is to preserve character trigrams, token-set/partial-ratio
controls, direct edit distance, normalized Levenshtein, and the acronym rescue
arm as independently measured inputs to an add-only candidate union. The
duplicate QRatio, alias, identifier, and token-sorted variants can remain
diagnostic controls until a dataset supplies independent field evidence. After
the active Anatomy model run releases memory, the bounded scorer subset will
measure Anatomy and all six Atlas pairs. Those results will show which lexical
controls rescue real Atlas mappings, populate the currently untested challenge
kinds, and reduce the semantic judging queue.

## Experiment log — memory-bounded exact retrieval harness (Mill)

Recorded: 2026-08-05 07:26:03 EDT. Status: implemented and verified on the
sealed OAEI Conference regression. No provider API or hosted inference call was
made. The already-running Anatomy process had loaded the previous script before
this edit; this work neither changed nor interrupted that process. The separate
Anatomy RDF-node dereferencing correction remains outside this version so the
memory comparison keeps identical benchmark inputs.

### Implementation decision

`tools/benchmark_atlas_candidate_retrieval.py` now performs exact dense scoring
in fixed query blocks instead of allocating complete query-by-document score
matrices. `--query-block-size` exposes the bound and defaults to 128. Ranking
still evaluates every source against every target in both directions. It sorts
equal scores by canonical member IRI, so changing query block size or input
sequence cannot change a tie.

The harness now stores one minimum-rank matrix per alignment case and model
arm. It selects the smallest unsigned integer type that can represent the
requested depths plus a sentinel; the standard maximum K of 100 uses one byte
per possible pair. Per-view candidate and gold counts accumulate while each
view is active, then that view's matrix is released. A model retains only its
cross-view minimum ranks. Multiple model arms therefore retain one compact
matrix apiece rather than Cartesian Python string tuples.

Sparse and graph results now retain one pair-to-minimum-depth dictionary rather
than a duplicate tuple set for every K. A mixed sparse-plus-dense run converts
that dictionary once into the same compact layout, then releases it before
dense models run. Combined-union candidate counts, missed gold, and SHA-256
pair-set receipts stream in canonical case/source/target order from the compact
matrices. The JSON result structure remains schema version `1.0`; the new block
size is a runtime control and does not add or remove a result field.

### Focused verification

The new file `tests/test_benchmark_atlas_candidate_retrieval_memory.py` adds
five focused checks:

- query blocks of 1, 2, 5, and 128 reproduce the previous full-matrix ranks on
  fixed random vectors;
- equal scores choose canonical member IRIs even when source and target inputs
  arrive in reverse order;
- compact multi-arm summaries reproduce legacy candidate counts, recall,
  missed-gold rows, and pair-set digests exactly;
- a deterministic fake dense model produces identical reports, vector digests,
  and pair receipts across different block sizes and reversed inputs; and
- the command-line interface accepts a positive block size and rejects zero.

The five new checks plus the six existing candidate-retrieval tests pass: **11
passed in 0.46 seconds**. Ruff check and format verification pass for the tool
and new test file.

### Sealed Conference comparison

The regression repeated the original five-view symmetric
`BAAI/bge-small-en-v1.5` run with sparse and mutual-top-1 graph retrieval at K =
1, 2, 3, 5, 10, 20, 50, and 100. The sealed before file is
`/tmp/refspec-candidate-benchmark.ANhNrc/conference-hybrid-refspec-v2.json`,
SHA-256 `70fc3b7c25b031a21a1a1ee2c99b236666780188d572af5fb579e238426f3fe5`.
The bounded after file is
`/tmp/refspec-candidate-benchmark.ANhNrc/memory-bounded-conference-hybrid.json`,
SHA-256 `67069db9dd465a18adf86818ee8fd2b17e11589f461151aaf255cab2a21f5ebe`.

All input fields, sparse ranking receipts, dense per-view counts and recall,
dense view-union counts and recall, combined candidate counts, combined recall,
missed-gold rows, and pair-set digests are identical. After removing only the
two measured runtime fields and the separately discussed regenerated vector
digest, both complete JSON documents have canonical SHA-256
`bb4a9e179c4d8012bbc8f01dd296dafc6a539a4522c0632f23c8865bb2ee5583`.

| K | Combined candidates | Gold found | Pair-set SHA-256 |
| ---: | ---: | ---: | --- |
| 1 | 16,693 | 284 / 305 | `a9851d6cc13b898ff02f5bd35383383e8bf0b6a2fc9569327f359f14c53134ea` |
| 10 | 102,625 | 298 / 305 | `5b114555dc2d88a21a011530fbc6ddd4ed8cfd59dc0c12d379a61c0297924c16` |
| 20 | 164,325 | 302 / 305 | `15c530646e530bc7e3367867a3c6fd2d29c227871a26bfabcda5fe169517f0f6` |
| 50 | 244,027 | 305 / 305 | `7301f9b95ec8d6e8d04fb7772ff2dc4c18c35156972388761394ab7a8489227a` |
| 100 | 269,362 | 305 / 305 | `a12eed8ba34658bcd75b64b5fb83ffa5833d5c40baad0af21f2901b816a28b75` |

The prior vector digest
`sha256:15da5889af3db4dae9cc802d2bd2824cae849796ee42d3bdc41b491b1b885531`
did not reproduce. The new run and an independent repeat both produced
`sha256:2ce7d2d86a331462893c5d7b0725ed0369e4c8169e14bbb2f776c56f17bb6440`.
A temporary replay of the pre-refactor embedding-cache and hashing sequence in
the same current environment also produced the new digest, before any blocked
ranking code ran. The retrieval refactor therefore did not alter the encoded
text or vector hashing path. The older receipt did not record enough runtime
and artifact detail to distinguish an earlier numerical-runtime setting. The
new receipt truthfully records the regenerated bytes rather than copying the
old value.

The current replay used FastEmbed 0.8.0, ONNX Runtime 1.28.0, and NumPy 2.5.1.
FastEmbed resolved `qdrant/bge-small-en-v1.5-onnx-q` revision
`52398278842ec682c6f32300af41344b1c0b0bb2`; its `model_optimized.onnx` SHA-256
is `51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431`.
This finding supports recording package, model revision, and artifact digests
in a future explicitly versioned evidence schema.

### Runtime and memory evidence

The sealed before report recorded 106.754 seconds for the dense stage. It did
not retain an external peak-memory measurement. During the subsequently loaded
old-script Anatomy run, the process was directly observed at 11,820,784 KiB,
about 11.27 GiB resident, before completion. That observation explains the
need for bounded storage, but it is a different suite and is not presented as
a matched Anatomy before/after benchmark.

The bounded Conference hybrid completed in 25.09 seconds wall time; its dense
stage reported 17.500 seconds. `/usr/bin/time -l` measured a maximum resident
set of 1,652,129,792 bytes, about 1.54 GiB. An independent dense-only repeat
completed in 23.68 seconds wall time, reported 20.301 dense seconds, and peaked
at 1,574,273,024 bytes, about 1.47 GiB. The repeat's dense evidence is identical
after removing runtime, canonical SHA-256
`3bd8d06b9467f684ca9a6add6f88805cc765974620b0d0b800f8f5d747a2356b`.

### Evidence and next direction

- Updated harness SHA-256:
  `cfbac12d336aa5d03d430510632b83dce49a829ca16dbd2a29ea90e3be2bf135`.
- New focused test SHA-256:
  `5f63497b57d6b938ef6d27df976534344ae3db89b360c14f42bcd4c7e61d5ba4`.
- Independent dense-only repeat:
  `/tmp/refspec-candidate-benchmark.ANhNrc/memory-bounded-conference-dense-repeat.json`,
  file SHA-256
  `09816044e8fd76d804e806713c414ec8f96203e8a1024fbb9e3013d5f11af653`.

The harness is ready to run exact Anatomy and multi-model Atlas experiments
with a fixed score-block bound and compact arm storage. The separately
versioned Anatomy loader correction should land first so new Anatomy evidence
clearly distinguishes input improvement from memory improvement. A following
benchmark can then report matched old/new Anatomy memory if still useful and
exercise several dense arms in one process without retaining string-tuple
candidate sets. Candidate discovery and paid judging remain separate: this
change preserves the complete potential-relation pool and only changes how the
benchmark computes and accounts for it.

## Experiment log — bounded Anatomy and Atlas lexical follow-up (Euler)

Recorded: 2026-08-05 07:40:22 EDT. Status: the practical lexical profile ran
against Anatomy before and after the OBO-in-OWL text correction, then ran
against all six Atlas pairs. This section continues **Experiment log — lexical
controls and candidate-kind coverage (Euler)**. It preserves each input
version as a separate receipt. No provider API, embedding model, or paid
judging call was used.

### Fixed follow-up profile

The profile retained seven independently measured controls: raw Levenshtein
distance, normalized Levenshtein similarity, RapidFuzz token-set ratio,
RapidFuzz WRatio, compact Jaro-Winkler, alias-bag WRatio, and local-identifier
QRatio. Each arm performed exact bidirectional ranking in 128-row score blocks
at K = 1, 2, 3, 5, 10, 20, 50, and 100. Canonical case and member order supplied
the tie-break. RapidFuzz remained pinned at 3.14.3.

The lexical harness records the shared input-adapter SHA-256 before and after
each run. One preliminary Anatomy attempt detected an adapter change and
stopped without publishing a mixed-version result. The complete receipts below
each use one stable adapter version.

### Anatomy input correction and measured effect

The first Anatomy receipt used shared adapter SHA-256
`cfbac12d336aa5d03d430510632b83dce49a829ca16dbd2a29ea90e3be2bf135`.
Its corpus SHA-256 was
`7932c29b4bd0a9a834a9b60d13e5ce8c688eb13fd542c912627a4c699dd97185`.
The corrected receipt used adapter SHA-256
`e87be005dcb2e2a3287ecee1ecf864c869310c3b623b472a2866da9610437628`
and corpus SHA-256
`f679f82140e5c0de18a63765505ebb28fc540d4a63b0abd5fe53d7d624715f00`.
Both use the same 1,516 expert relations, gold SHA-256
`06e799bc6e35df5eef97bfdc8ec9fcc3f60a0a375503b01085bda5c5df13bd03`.

The correction resolves referenced OBO synonym and definition nodes to their
human-readable labels. It replaces node identifiers with useful text while
preserving labels, concept identities, and expert gold.

| K | Text-poor input: found / candidates | Corrected input: found / candidates | Change in found | Change in candidates |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1,328 / 22,287 | 1,345 / 20,471 | +17 | -1,816 |
| 2 | 1,375 / 45,093 | 1,394 / 41,285 | +19 | -3,808 |
| 3 | 1,400 / 67,923 | 1,418 / 62,331 | +18 | -5,592 |
| 5 | 1,428 / 113,545 | 1,444 / 104,937 | +16 | -8,608 |
| 10 | 1,460 / 225,722 | 1,473 / 209,306 | +13 | -16,416 |
| 20 | 1,474 / 433,200 | 1,486 / 401,475 | +12 | -31,725 |
| 50 | 1,494 / 1,010,363 | 1,505 / 939,769 | +11 | -70,594 |
| 100 | 1,502 / 1,854,753 | 1,510 / 1,731,354 | +8 | -123,399 |

The corrected text raises top-10 recall from 96.31% to 97.16% while retaining
16,416 fewer pairs. Alias WRatio rises from 998 to 1,247 gold relations at top
10. It now supplies 15 unique top-10 rescues, compared with two on the
text-poor input. Token-set ratio supplies 27 unique rescues, normalized
Levenshtein four, WRatio six, and compact Jaro-Winkler two. These results show
that resolving source text improves both recall and focus before any learned
model runs.

The corrected main run completed in 37.816 seconds and peaked at 679,100,416
bytes, about 648 MiB resident. Its repeat completed in 36.157 seconds. Both
produce deterministic result SHA-256
`cacf3302683b504ac3a6bc2fc3f82b0083396afe76fad1633e93a5c2fa8088e6`.
The text-poor main and repeat completed in 30.446 and 29.960 seconds and share
deterministic result SHA-256
`bd2584581016874c1cd97ffafb38ab09435d8cb58ac08d8a6becc804eb530de0`.

Corrected all-control pair-set SHA-256 values are top 10
`de32305a8d7f02147142419282cd5b9111cd301227b753e38a19ac603805d14a`,
top 20
`fd6d95c540e6374a735e08887e0eed03f87ff2084816bcf9dc715cc5c4a9f1be`,
top 50
`8f0a118064ea7d2928d9aed848c28054133989fd078f4221f74ca50440eb41b6`,
and top 100
`3df3f84cf7a16a343d72c42b86b0e16012299e2b4a01f9c722d02bef6e1920a8`.

### Six-pair Atlas result

The Atlas run covers 6,042 source concepts, 11,472 target concepts, and all 582
admitted mappings. The initial lexical receipt read the candidate bundle's
search-expansion `proposedRelation`, which defaults to `closeMatch`; that field
is not the admitted mapping assertion. The sealed relation-assertion files type
the 582 mappings as 121 exact, 232 close, 75 broad, 119 narrow, and 35 related.
The lexical parser now reads those final assertions while keeping mapping
meaning separate from retrieval challenges. Alias WRatio is the strongest
single control: 461/582 at top 1, 521/582 at top 10, 536/582 at top 20, and
558/582 at top 100. It uniquely rescues 43 mappings at top 10. Preferred-label
token-set ratio finds 517 at top 10. Identifier QRatio finds 5 at top 10 because
the vocabularies use different code systems.

| K | Lexical-union candidates | Gold found | Recall | Pair-set SHA-256 |
| ---: | ---: | ---: | ---: | --- |
| 1 | 65,599 | 543 / 582 | 93.30% | `b6b6c403102462ccb1a3347f14d11a87c44c005b670846ce02864805e740577f` |
| 2 | 129,496 | 560 / 582 | 96.22% | `77c0da00d74d42ae6b26580e0ace58c297c123d38c0bb6139fdadd7c0cb26a95` |
| 3 | 191,347 | 567 / 582 | 97.42% | `026ef2f17bcafd73b020384d71cbc2b59dc97426230eecbb1dfe4c6b6174ee02` |
| 5 | 311,222 | 568 / 582 | 97.59% | `9d0acb1986bede38af25973adf8c5a905cd4b8089e21f064a7167f2a672d6d1b` |
| 10 | 594,659 | 573 / 582 | 98.45% | `4ca5bc522d16131f0fbc01ffa15db451323f192c382e3055eaee66737246a369` |
| 20 | 1,126,477 | 578 / 582 | 99.31% | `bc2b7bcc3ba09141fa4e950b1027d1240d87ba7d7f7177ec1012aa43d46df478` |
| 50 | 2,560,788 | 579 / 582 | 99.48% | `b97fd3b05c87ff69848fa737ffc65b891753d4c875108c1311c9d21c84e51de7` |
| 100 | 4,547,458 | 580 / 582 | 99.66% | `cce990aeddaa27d264ad858bebfc04a5a2467cb5a447748fd0135e02d4ef0ba0` |

The Atlas corpus SHA-256 remains
`20bbceaec514f8681f3a07146e6a30ed5fd731857c586d327ac916d4a523317e`
and gold SHA-256 remains
`d347a551e205d973d39141ba01548bce35b7f59d0caafccab60a353607bc662d`
across the adapter correction. Candidate counts, found gold, missed-gold rows,
feature digests, ranking digests, and pair-set digests are identical. The
current 128-row compatibility run completed in 78.847 seconds and peaked at
1,307,918,336 bytes, about 1.22 GiB resident. Its versioned deterministic
result SHA-256 is
`2fda97cf7c69bcfd13faa26c8618db2e44c3905d1ec2f3dfa6664ab9f676ddea`.
The earlier main and repeat share deterministic result SHA-256
`59b073aaa443502071807e14ae2959caae73b90eae5f66b4397cb65d1fc7b9fa`.

### Complement with sparse and graph controls

The lexical union and the existing sparse-plus-mutual-graph union rescue
different Atlas mappings. Their missed-gold sets have one shared pair at top
2 and no shared pair from top 3 onward. Therefore their add-only union has
exact gold recall 582/582 at top 3. The existing receipts retain pair-set
digests rather than pair rows, so the table reports a safe candidate upper
bound: the sum of both candidate counts. The exact union can only be smaller.
The exact frontier below supersedes these upper bounds for cost decisions.

| K | Lexical candidates | Sparse + graph candidates | Candidate upper bound | Combined gold |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 65,599 | 35,337 | 100,936 | 573 / 582 |
| 2 | 129,496 | 59,662 | 189,158 | 581 / 582 |
| 3 | 191,347 | 83,616 | 274,963 | 582 / 582 |
| 5 | 311,222 | 129,614 | 440,836 | 582 / 582 |
| 10 | 594,659 | 236,635 | 831,294 | 582 / 582 |

This complement supports a five-part add-only discovery design: normalized
exact and edit anchors, token-set and WRatio retrieval, explicit alternate-label
evidence, sparse full-text retrieval, and hierarchy or graph retrieval. Learned
semantic scorers can prioritize that complete pool without deleting any
candidate kind.

Two lexical top-100 misses also identify a precise refinement. `Family
planning` ↔ `BIRTH CONTROL` shares the normalized alternate label `birth
control`; `Motor vehicles` ↔ `CARS` shares `automobiles`. Concatenating every
alias into one bag can dilute that exact evidence. A deterministic exact-alias
anchor, followed by max-over-individual-label scoring, is a focused next
control. The existing sparse exact-label anchor already helps explain why the
combined pool is complete at shallow depth.

### Follow-up evidence

- Corrected Anatomy main:
  `/tmp/refspec-candidate-benchmark.ANhNrc/lexical-controls-anatomy-obonodes-block128.json`,
  file SHA-256
  `6a64570f4eb17b9df5424c92bfcd0ae92759cf325922d568d6411f9c4d241ec5`.
- Corrected Anatomy repeat:
  `/tmp/refspec-candidate-benchmark.ANhNrc/lexical-controls-anatomy-obonodes-block128-repeat.json`,
  file SHA-256
  `68374a895f3248398e7f718e4362d12562202152e8f4021e81759407fb841400`.
- Current Atlas compatibility run:
  `/tmp/refspec-candidate-benchmark.ANhNrc/lexical-controls-atlas-obonodes-block128.json`,
  file SHA-256
  `59d00fedd1ebb789b0dac2c69c33ae68a1a207fb3bf1a17d57ae8414bb3f332d`.
- Atlas lexical-plus-sparse gold reconciliation:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-obonodes-lexical-sparse-gold-reconciliation.json`,
  file SHA-256
  `0f55618b1f9261b4c08f5780a35c6407fc776b331ad97da1c09bbe656f3d1175`.

These bounded runs complete the lexical-control evidence on Conference,
Anatomy, and all six Atlas pairs. They support candidate-kind-specific
discovery and add-only unions while keeping expert mapping semantics in their
separate field.

### Exact Atlas sparse-plus-lexical cost frontier

Recorded: 2026-08-05 07:56:39 EDT. Status: exact candidate volume measured for
all 25 asymmetric combinations of lexical K and sparse-plus-mutual-graph K in
1, 2, 3, 5, and 10. This is the primary production-domain evidence. Conference
property alignments and Anatomy biomedical synonyms remain stress tests. The
receipt records the production language scope as English; translation and
multilingual candidate kinds do not enter these costs or gates.

The frontier tool reconstructed the seven distinct practical lexical ranks and
the sparse-plus-mutual-graph ranks from the pinned Atlas catalogs. It reproduced
the candidate count, gold count, and pair-set SHA-256 in both earlier receipts
at every depth before combining them. It retained compact integer sets and
streamed canonical case, source, and target rows into SHA-256; it did not write
a full candidate-pair file. No provider call was made.

The typed relation source is the sealed `relation-assertions-v2` output, not the
candidate generator's `proposedRelation`. The shared alignment adapter carries
gold pairs without their predicates, so the frontier joins each gold pair back
to its final mapping assertion. The typed totals are 121 exact, 232 close, 75
broad, 119 narrow, and 35 related.

#### Exact equal-depth unions

Candidate overlap is material. Exact union counts are 11,507 to 106,383 below
the earlier summed upper bounds.

| Lexical K | Sparse + graph K | Exact candidates | Gold found | Exact pair-set SHA-256 |
| ---: | ---: | ---: | ---: | --- |
| 1 | 1 | 89,429 | 573 / 582 | `fa9dfcd65afdb325e77719c66f2417193ad0e48b62835155b7538e122c83038c` |
| 2 | 2 | 166,871 | 581 / 582 | `a789fc6007586e0bda1a1b6203564e7b902b3008dae00572e02fa91a73337cbe` |
| 3 | 3 | 241,692 | 582 / 582 | `43d1052cb125eaa324492b21dc5279a32bd1fd8cd8820108cd43df736ce3dbe4` |
| 5 | 5 | 386,024 | 582 / 582 | `d7a0752917c87264f485da0305969134f223188e4ebcd5696e68b6e22856d9b4` |
| 10 | 10 | 724,911 | 582 / 582 | `7029426a3ee3913203c53bed7bfce4bdffdd4072b4fa0c45a22be3560ee75c16` |

#### Asymmetric Pareto search and pre-access-term floor

Fifteen of the 25 combinations find all 582 mappings. Every complete point has
lexical K of at least 3. Lexical K = 3 plus sparse-plus-graph K = 1 dominates
the other complete points in both retained depth and exact candidate count. It
is the only Pareto-optimal complete combination.

| Lexical K | Sparse + graph K | Exact candidates | Gold found |
| ---: | ---: | ---: | ---: |
| 1 | 1 | 89,429 | 573 / 582 |
| 1 | 2 | 109,246 | 575 / 582 |
| 1 | 3 | 130,103 | 576 / 582 |
| 2 | 1 | 150,080 | 581 / 582 |
| **3** | **1** | **210,197** | **582 / 582** |

The pre-access-term floor pair-set SHA-256 is
`24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9`.
It retains 31,495 fewer pairs than the equal-K = 3 union. If one judging request
scores 25 spreadsheet-like rows, this floor is 8,408 sub-batches and saves
about 1,260 sub-batches relative to equal K = 3.

At this pre-projection floor, lexical K = 3 contributes 191,347 candidates and finds
567 gold mappings. Sparse-plus-graph K = 1 contributes 35,337 candidates and
finds 523. They overlap on 16,487 candidates and 508 gold mappings. Lexical adds
174,860 unique candidates and 59 unique gold mappings over sparse-plus-graph;
sparse-plus-graph adds 18,850 unique candidates and 15 unique gold mappings over
lexical. The lexical-only pair-set SHA-256 is
`37719a1b6ae8fa7cbb1aca075cca3e22aadb9d3446a1b5fcd58b1a6066c0e4f9`;
the sparse-plus-graph-only SHA-256 is
`d54dfd31ec32476b18bf235cec27cc8cc3909c69aed9574a2dffc658915f70ca`.

#### Six-pair pre-projection breakdown

The first three released Atlas pairs currently have no admitted reference
mappings, but their candidates remain part of the real judging cost. They
account for 29,772 pairs, or 14.2% of the selected floor.

| Vocabulary pair | Gold | Exact union candidates / found | Lexical-only candidates / gold | Sparse + graph-only candidates / gold | Overlap candidates / gold |
| --- | ---: | ---: | ---: | ---: | ---: |
| CRS policy ↔ Federal Register | 0 | 8,638 / 0 | 6,932 / 0 | 752 / 0 | 954 / 0 |
| CRS subjects ↔ Federal Register | 0 | 14,616 / 0 | 13,043 / 0 | 589 / 0 | 984 / 0 |
| CRS subjects ↔ CRS policy | 0 | 6,518 / 0 | 5,339 / 0 | 424 / 0 | 755 / 0 |
| ELSST ↔ ICPSR | 191 | 77,400 / 191 | 60,638 / 23 | 9,625 / 3 | 7,137 / 165 |
| Federal Register ↔ ELSST | 190 | 55,074 / 190 | 47,385 / 20 | 4,443 / 8 | 3,246 / 162 |
| Federal Register ↔ ICPSR | 201 | 47,951 / 201 | 41,523 / 16 | 3,017 / 4 | 3,411 / 181 |

#### Typed-relation coverage at the pre-projection floor

Unjudged candidate rows do not yet have a final mapping type. The table
therefore slices the 582 sealed reference mappings by their admitted relation;
it does not assign types to the remaining candidate queue.

| Final mapping relation | Gold | Lexical found / unique | Sparse + graph found / unique | Exact union found |
| --- | ---: | ---: | ---: | ---: |
| `exactMatch` | 121 | 121 / 0 | 121 / 0 | 121 / 121 |
| `closeMatch` | 232 | 230 / 2 | 230 / 2 | 232 / 232 |
| `broadMatch` | 75 | 75 / 25 | 50 / 0 | 75 / 75 |
| `narrowMatch` | 119 | 107 / 15 | 104 / 12 | 119 / 119 |
| `relatedMatch` | 35 | 34 / 17 | 18 / 1 | 35 / 35 |

The complement matters most for directional and associative mappings. Lexical
retrieval supplies 25 unique broad, 15 unique narrow, and 17 unique related
mappings. Sparse and graph retrieval supplies 12 unique narrow mappings plus
the remaining close and related mappings. Both families find every exact
mapping at the selected depths.

#### Frontier evidence and verification

- Exact frontier result:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-sparse-lexical-exact-frontier-english.json`,
  file SHA-256
  `b951a20b7c978c55d01f061be72d40a0489ef39766671c661659bc20c153bcde`;
  deterministic result SHA-256
  `b3cf4733b6ad784d76d66ca04f07725576cc943e5d9e39feeb367ce55dacdaff`.
- Frontier tool SHA-256:
  `cf3c3cbe42d04c4c2be13af2965c633c9674cc88bc09aa164f52049f039b9eb7`.
- Corrected lexical-control tool SHA-256:
  `e051038a5ca24c5952077010b42709fc38848280a1912ccc81abb573f95ed6b9`.
- Focused frontier and lexical tests: **7 passed in 0.20 seconds**. Test file
  SHA-256 values are
  `d3a7b2d8bda7e6802f645fd4ebee65388c2d9deb2182f9d7eb542e703a0eac19`
  and
  `4cc7c0521323c2af9271eb57cce8a0d4ee8246f3732ed6f1ffaccc7433492d59`.
- Ruff check, format verification, and Python compilation pass for both tools
  and both focused test files.

The exact run completed in 79.263 seconds and peaked at 666,828,800 bytes,
about 636 MiB resident. This experiment selected lexical K = 3 plus
sparse-plus-mutual-graph K = 1 before access-term projection, with all six pair
costs and all five final relation classes retained as separate evidence
slices. The later ICPSR experiment supersedes its exact count and digest while
preserving the same K3/K1 configuration.

## Experiment log — learned-sparse retrieval (Kierkegaard)

Recorded: 2026-08-05 07:41:35 EDT. Status: three local learned-sparse model
families executed with exact bidirectional ranking on all 21 OAEI Conference
alignments and the full OAEI Anatomy alignment. No provider API or hosted
inference call was made.

### Result and practical decision

Learned sparse retrieval is a useful add-only discovery arm, but it does not
replace deterministic lexical, sparse, or graph retrieval. On Conference, the
three-model, two-view union finds all 305 expert mappings by K = 50. More
important for judging cost, deterministic sparse plus graph at K = 20 combined
with only `MiniCOIL structured` and `SPLADE++ label` at K = 20 finds all
305/305. Those two learned arms retain 110,571 candidate pairs, compared with
165,067 for all six learned arms at the same depth.

On sealed Anatomy input, all six learned arms find 1,508/1,516 mappings at
K = 100 but add no mapping beyond the reconstructed sparse-plus-graph union at
that depth. They do add mappings at shallow cutoffs. Against the existing
pair-accounted BGE-plus-deterministic hybrid, SPLADE++ label at rank 14 rescues
`MA_0001744` ↔ `NCI_C33049`. Adding learned sparse to that hybrid raises K =
100 coverage from 1,514/1,516 to 1,515/1,516. The remaining miss is
`MA_0000205` ↔ `NCI_C12442`.

This supports a layered candidate finder: deterministic anchors and graph
expansion first, diverse lexical and learned retrieval arms second, and
rerankers or large language models only after the add-only candidate union.
Negative or low scores from one arm must not delete candidates found by
another arm.

### Inputs and exact scoring rule

Conference contains 21 alignment cases, 4,812 concept occurrences, 802 unique
concept identifiers, and 305 gold mappings. Its corpus digest is
`sha256:8fdba504058d3011dcc2219e1b9277c5f8c1ef331fad4482e4a86059daec1df1`;
its gold digest is
`sha256:63c2feb19ed1352ccaae8efe897e3f5a3c917db07b7b21324d9f97936282177e`.

Anatomy contains 2,747 source concepts, 3,306 target concepts, 6,046 unique
identifiers, and 1,516 gold mappings. All three learned-model processes loaded
the same sealed adapter, SHA-256
`cfbac12d336aa5d03d430510632b83dce49a829ca16dbd2a29ea90e3be2bf135`.
Their Anatomy corpus digest is
`sha256:7932c29b4bd0a9a834a9b60d13e5ce8c688eb13fd542c912627a4c699dd97185`;
their gold digest is
`sha256:06e799bc6e35df5eef97bfdc8ec9fcc3f60a0a375503b01085bda5c5df13bd03`.

Each model received two separately ranked text views:

- `label`: preferred label followed by alternate labels;
- `structured`: named fields for preferred label, alternate labels, local
  identifier, definition, broader concepts, and narrower concepts.

For every case and view, the scorer built the exact sparse inverted index and
ranked source-to-target and target-to-source dot products. A pair's retained
rank is the smaller directional rank. Cutoffs are K = 1, 2, 3, 5, 10, 20, 50,
and 100. Equal scores sort by canonical member IRI. A pair with no shared
expanded term is absent rather than receiving an arbitrary zero-score rank.
The benchmark keeps label-only, structured-only, per-model view union, and
cross-model union receipts.

MiniCOIL is asymmetric. The run generated query and document vectors
separately and applied its required collection-level BM25 inverse document
frequency in each alignment direction:
`ln(1 + (N - df + 0.5) / (df + 0.5))`, with FastEmbed defaults `k = 1.2`,
`b = 0.75`, and `avg_len = 150`.

The runtime was Python 3.12.9 on arm64 macOS with four inference threads and
batch size 32. FastEmbed was 0.8.0, SentenceTransformers was 5.6.1, and NumPy
was 2.5.1.

### Models, revisions, artifacts, and licenses

| Model arm | Local backend and behavior | Pinned revision | Main weight receipt | Declared license |
| --- | --- | --- | --- | --- |
| `prithivida/Splade_PP_en_v1` | FastEmbed ONNX; symmetric SPLADE++ token expansion. FastEmbed resolves this name to `Qdrant/Splade_PP_en_v1`. | `efcd182bc7eb351e81a9445752d4388c2bab500b` | `model.onnx`, 532,091,260 bytes, SHA-256 `65adbad0d7e1bc882c867d534821d52e60d6f666a91662be3f58457d08d25bf3`; complete local bundle SHA-256 `fc3030fba543e6d455fb6cd21d10b82bb271d53636b04eed297de17eb30c55fd` | Qdrant and prithivida model cards: Apache-2.0 |
| `Qdrant/minicoil-v1` | FastEmbed ONNX; asymmetric query/document vectors plus collection IDF | `4a7b05822a7a246d25778508593fff58fe574dfe` | `minicoil.triplet.model.npy` SHA-256 `882db5d3bdc993ac6a58a51742da744e22b33111d215e5de029300bce21f7459`; `onnx/model.onnx` SHA-256 `8daf59cab0f24c7e0231a1e3ff9c348a97f6662e9a763dd4f15d2ca2f1614e05`; complete bundle SHA-256 `67fb8f1633f01da8c31aa4e1316335dcca1ad5aaf5b5b64dd4cea81af8cc6991` | Apache-2.0 |
| `opensearch-project/opensearch-neural-sparse-encoding-v2-distill` | SentenceTransformers `SparseEncoder`; symmetric PyTorch sparse vectors | `269e6638b2c4f648996691f6d751495285d8f330` | `model.safetensors`, 267,954,840 bytes, SHA-256 `39e39459d7cb60c49cda2aa9861f77c2db8cd03c7ebd50c70d483ff6e5731597`; complete bundle SHA-256 `1746a84e6f9469c7990a62c9eb84feadd28c76d2b9466b11c8613136c181ea7b` | Apache-2.0 |

Primary sources are the
[Qdrant SPLADE++ model card](https://huggingface.co/Qdrant/Splade_PP_en_v1),
[prithivida SPLADE++ model card](https://huggingface.co/prithivida/Splade_PP_en_v1),
[MiniCOIL model card](https://huggingface.co/Qdrant/minicoil-v1), and
[OpenSearch v2-distill model card](https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-v2-distill).

There is a license-lineage caveat for SPLADE++. The executed artifacts come
from the independently published prithivida/Qdrant model path whose cards
declare Apache-2.0. The
[Naver reference SPLADE repository](https://github.com/naver/splade/blob/main/LICENSE)
uses CC BY-NC-SA 4.0 and was not executed. The naming and lineage are close
enough that production use still needs a legal review; the benchmark does not
resolve that question.

### Conference retrieval results

The following table reports the exact union of all three models and both text
views. `Sparse+graph union` uses the experiment's pair-level reconstruction of
the existing aggregate deterministic baseline. `BGE hybrid` uses exact missed
gold rows from the sealed BGE-plus-deterministic receipt on the same corpus.

| K | Learned candidates | Learned gold | New over sparse+graph | Sparse+graph union | New over BGE hybrid | BGE hybrid + learned |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 12,845 | 266 / 305 | 11 | 288 / 305 | 1 | 285 / 305 |
| 2 | 23,788 | 277 / 305 | 9 | 291 / 305 | 2 | 292 / 305 |
| 3 | 34,684 | 281 / 305 | 8 | 293 / 305 | 0 | 294 / 305 |
| 5 | 55,347 | 291 / 305 | 11 | 297 / 305 | 3 | 299 / 305 |
| 10 | 100,149 | 301 / 305 | 17 | 303 / 305 | 4 | 302 / 305 |
| 20 | 165,067 | 303 / 305 | 17 | **305 / 305** | 2 | 304 / 305 |
| 50 | 250,116 | **305 / 305** | 17 | **305 / 305** | 0 | **305 / 305** |
| 100 | 269,931 | **305 / 305** | 17 | **305 / 305** | 0 | **305 / 305** |

The six arms are complementary before saturation. At K = 10, MiniCOIL has
four gold mappings that neither other model finds, OpenSearch has three, and
SPLADE++ has two. Exhaustive enumeration of the 63 non-empty model/view
subsets found the lower-cost complete configuration at K = 20:

- deterministic sparse plus graph at K = 20;
- MiniCOIL `structured` at K = 20;
- SPLADE++ `label` at K = 20.

The two learned arms retain 110,571 candidate pairs, find 303/305 gold
mappings, and contribute all 17 mappings absent from the reconstructed
deterministic baseline. Their candidate-set digest is
`sha256:b295d2bd2e54a23a14545e73f2dca5f1d321c946c47670998a203d6b1446293a`.
This is the smallest same-K learned candidate set among the tested six-arm
subsets that closes the deterministic Conference gaps. It does not include
cross-K or differently thresholded arm combinations.

At K = 20, the learned union covers every observed lexical/alias,
identifier, abbreviation, broader/narrower wording, and inverse/directional
property challenge. It covers 116/118 definition/semantic challenges and
243/245 hierarchy/graph challenges; the deterministic union supplies the two
remaining mappings.

| Retrieval challenge, overlapping labels | Gold | Learned union K = 20 | Learned union K = 100 | New over sparse+graph at K = 20 |
| --- | ---: | ---: | ---: | ---: |
| Lexical or alias | 140 | 140 | 140 | 0 |
| Shared identifier surface | 140 | 140 | 140 | 0 |
| Abbreviation | 47 | 47 | 47 | 0 |
| Definition or semantic gap | 118 | 116 | 118 | 17 |
| Hierarchy or graph | 245 | 243 | 245 | 0 |
| Broader, narrower, or granularity wording | 58 | 58 | 58 | 0 |
| Inverse or directional property wording | 45 | 45 | 45 | 11 |
| Translation | 0 | out of scope | out of scope | out of scope |

The category counts overlap. For example, directional-property rescues are a
subset of the 17 total semantic-gap rescues; they must not be summed.

### Anatomy retrieval results

The Anatomy table uses the same sealed text-poor adapter for every learned
model and both comparison receipts.

| K | Learned candidates | Learned gold | New over reconstructed sparse+graph | Sparse+graph union | New over existing BGE hybrid | BGE hybrid + learned |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16,357 | 1,415 / 1,516 | 3 | 1,508 / 1,516 | 17 | 1,467 / 1,516 |
| 2 | 32,529 | 1,464 / 1,516 | 4 | 1,510 / 1,516 | 16 | 1,489 / 1,516 |
| 3 | 48,127 | 1,475 / 1,516 | 4 | 1,510 / 1,516 | 9 | 1,495 / 1,516 |
| 5 | 79,862 | 1,488 / 1,516 | 3 | 1,510 / 1,516 | 4 | 1,504 / 1,516 |
| 10 | 158,690 | 1,491 / 1,516 | 0 | 1,510 / 1,516 | 1 | 1,505 / 1,516 |
| 20 | 317,021 | 1,500 / 1,516 | 2 | 1,512 / 1,516 | 2 | 1,511 / 1,516 |
| 50 | 748,371 | 1,504 / 1,516 | 0 | 1,513 / 1,516 | 1 | 1,512 / 1,516 |
| 100 | 1,353,872 | 1,508 / 1,516 | 0 | 1,513 / 1,516 | **1** | **1,515 / 1,516** |

The reconstructed sparse-plus-graph baseline and the existing BGE hybrid are
separate candidate configurations, so their columns must not be treated as
the same baseline. The BGE comparison is stronger evidence for pair identity:
its receipt records exact missed-gold rows. At K = 100, SPLADE++ label alone
supplies the one unique hybrid rescue, `MA_0001744` ↔ `NCI_C33049`, at rank
14. Neither MiniCOIL nor OpenSearch retained that pair by K = 100.

Individual K = 100 results were:

| Model view union | Candidates | Gold | Recall | Gold unique within the learned three-model union |
| --- | ---: | ---: | ---: | ---: |
| MiniCOIL | 690,250 | 1,473 / 1,516 | 97.16% | 0 |
| OpenSearch v2-distill | 806,865 | 1,507 / 1,516 | 99.41% | 5 |
| SPLADE++ | 805,540 | 1,502 / 1,516 | 99.08% | 1 |

OpenSearch was the strongest single learned-sparse Anatomy model. On the
sealed challenge slices at K = 100, it finds 55/55 abbreviations, 516/525
definition/semantic gaps, 1,497/1,503 hierarchy/graph cases, 198/198
broader/narrower wording cases, and 936/936 lexical/alias cases. Anatomy
contains no observed shared-identifier or inverse-property case under this
classifier. Translation is outside the English-only production scope.

The three mappings still missed by the K = 100 reconstructed sparse-plus-graph
union are:

- `MA_0001067` ↔ `NCI_C33377`;
- `MA_0001068` ↔ `NCI_C32105`;
- `MA_0001320` ↔ `NCI_C33178`.

The learned models retrieve none of those three at K = 100. This is direct
evidence that another discovery signal remains necessary; increasing the
judging model's intelligence cannot recover pairs that candidate generation
never presents.

### Runtime, memory, and repeatability

| Model | Conference first / repeat seconds | Conference peak RSS | Anatomy seconds | Anatomy peak RSS | Anatomy dominant work |
| --- | ---: | ---: | ---: | ---: | --- |
| MiniCOIL | 11.392 / 8.599 | 0.943 GB | 1,129.130 | 21.935 GB | structured query and document encoding, 967.024 seconds |
| OpenSearch v2-distill | 18.019 / 14.196 | 2.760 GB | 294.584 | 8.717 GB | exact ranking, 223.257 seconds |
| SPLADE++ | 51.532 / 17.792 | 7.435 GB maximum across repeats | 235.006 | 7.994 GB | label plus structured encoding, 179.549 seconds |

The first SPLADE++ Conference run also built the cached pair-level
sparse-plus-graph baseline; its warm repeat is the fairer steady-state model
time. Every Conference model was executed twice. Each repeat reproduced the
exact vector digest, both directional-ranking digests, every per-view and
union result, and the compressed rank rows. Warm caches changed only runtime
and measured peak memory. Anatomy models were each executed once because the
three runs consumed about 27.6 wall-clock minutes and the input adapter changed
after they had loaded. Their rank receipts were independently re-read to build
the guarded cross-model aggregate.

MiniCOIL's Anatomy profile is a material deployment warning. Its asymmetric
four-pass encoding reached 21.935 GB peak resident memory and took 18.8
minutes. OpenSearch and SPLADE++ supplied higher recall with less time and
memory on this corpus. MiniCOIL remains valuable in the smaller Conference
cost frontier, but should not be enabled by default for large vocabularies
without batching, persistent indexing, and explicit resource limits.

### Adapter version boundary

At 07:28:51 EDT, after all three learned Anatomy processes had loaded their
inputs, the shared ontology adapter changed from SHA-256 `cfbac12d...` to
`e87be005dcb2e2a3287ecee1ecf864c869310c3b623b472a2866da9610437628`.
The correction dereferences OBO synonym and definition resources to their
`rdfs:label` text instead of embedding generated-node IRIs. It changes the
parsed Anatomy corpus digest to
`sha256:f679f82140e5c0de18a63765505ebb28fc540d4a63b0abd5fe53d7d624715f00`
while preserving the gold digest. Conference is unchanged.

The initially generated Anatomy aggregate was rejected because it combined
old rank rows with new challenge classification. The replacement aggregate
pins the original corpus and adapter, verifies all three model receipts share
them, verifies the current gold digest is unchanged, and omits aggregate
per-challenge metrics rather than mixing input versions. The individual
Anatomy receipts retain valid per-model challenge metrics from their sealed
input.

These Anatomy measurements are therefore a conservative text-poor-adapter
experiment, not a result for the corrected text. A later targeted corrected
run should start with OpenSearch or SPLADE++, whose recall and resource profile
show plausible marginal value. Repeating MiniCOIL first is not justified by
this evidence.

### Relation-kind coverage and limits

`retrieval-challenge-v1` is a multi-label surface-difficulty classifier, not a
semantic mapping judge. OAEI Conference and Anatomy gold rows assert
equivalence. Labels such as broader/narrower wording or inverse/directional
property identify why retrieval is difficult; they do not relabel the expert
relation. The corpora do not directly validate typed broader, narrower,
related, or inverse mappings. Translation is outside the English-only
production scope; the adapter retains English or untagged literals.

Learned sparse expansion also cannot score a pair when its expanded token
vectors have no overlap. It therefore cannot guarantee a complete potential
relation pool by itself. Dense embeddings, exact aliases and identifiers,
character/token controls, graph neighborhoods, and domain-specific rules must
remain separate add-only arms. A reranker can reorder the resulting pool for
cost control, but must not become a hard discovery gate.

The BGE comparison uses exact missed-gold identities from the same-corpus
hybrid receipts. Those receipts do not retain every candidate row, so this
experiment can prove unique gold rescues and resulting recall, but cannot
compute exact non-gold candidate overlap or the final judging-queue size for a
learned-plus-BGE union.

### Reproducibility receipts

- Temporary benchmark program:
  `/tmp/refspec-candidate-benchmark.ANhNrc/learned-sparse/learned_sparse_benchmark.py`,
  SHA-256
  `07f6faa13c51109e2e182a5436112e9a0745c1dbb2fdbb5b85ae7ae7f8cdf2b3`.
- Guarded aggregate program:
  `/tmp/refspec-candidate-benchmark.ANhNrc/learned-sparse/aggregate_learned_sparse.py`,
  SHA-256
  `ced48294f9d8f1ba2c9b22b90d5af5ad829745a818ce981a4965616dd7bf7dce`.
- Model/view subset search:
  `/tmp/refspec-candidate-benchmark.ANhNrc/learned-sparse/search_arm_subsets.py`,
  SHA-256
  `fd130f24d2b7a7e9bcf35bd209bbaf69b8f9c4deaa2ca67fde8becbf84e7e05a`.
- Conference aggregate: `conference-model-union.json`, SHA-256
  `76d61fc6890a34ba8f384450179c6f42faae97cd84a65c2889d97842b155fb14`;
  subset search SHA-256
  `e4cf9921c213782c5ac750b4ce4144392e5549a8011e9b04e911d4b70af10041`.
- Anatomy guarded aggregate: `anatomy-model-union.json`, SHA-256
  `91cb2454d5174f749aaf113b2ace75ab5bcf9d74700dbc2202066d152b0dcfb4`;
  subset search SHA-256
  `3d2d82f0bfcade14812c5aa7d1844dfe146e35593808d366e752cdef68e3cd2a`.
- Existing same-corpus hybrid receipts: Conference SHA-256
  `70fc3b7c25b031a21a1a1ee2c99b236666780188d572af5fb579e238426f3fe5`;
  Anatomy SHA-256
  `3d3709afa20ab126117873c45478b11dfbaadfc9ff614b983c1043cf02c4055e`.

Per-model JSON receipt SHA-256 values are Conference: MiniCOIL
`7552173847eef3d42e3aa8ee1ed402cf4fbbc7114f0f1284f90f44e8f880ccab`,
OpenSearch
`9d9e62435a34863bf763c7d31aad31214e48200f8850f16e7fbd7c8b6d15a0f4`,
and SPLADE++
`46bed80ea03f40d5d8b728098b10099e713c96a45106ae2a0701e7daddd2a812`;
Anatomy: MiniCOIL
`bc7d6290d4b2cc8fad5e91c1baac12cbdf061d6f6c8b040b32927e62d5c5d694`,
OpenSearch
`d174368a530f8427cd6cb4dcfe43994424de80c91b01d58bb2a4417df5336338`,
and SPLADE++
`844ea1af0d226bb7ae1a70b58dcb6aa226e795e39f8c9fa42a3a1d2d1c7ec8cf`.

Compressed rank receipts retain case, source, target, label rank, and
structured rank for every pair reached by K = 100:

| Suite and model | Rows | Gzip SHA-256 |
| --- | ---: | --- |
| Conference MiniCOIL | 259,211 | `1394de3da4c2a528a59d3fda84d110d7214a13f795678695c0673b8255f24e23` |
| Conference OpenSearch | 266,766 | `10dc320eb7cecb315843f95bc853ecfc5566c45ae956d5a4d53dbc73e0ba0ec5` |
| Conference SPLADE++ | 264,872 | `41ddc89ac137b1ffdddd15054b0b226de667bf31877b073878affec46082d957` |
| Anatomy MiniCOIL | 690,250 | `09e3c5277c00c05cbcf02d1d2f8230a07bf210e63dd61d29906584c466103c7b` |
| Anatomy OpenSearch | 806,865 | `639f01b02392f6b391c2ba47cdefae936a4a20aef8a8fd694269278d2ab590d0` |
| Anatomy SPLADE++ | 805,540 | `ac94fd5d293d6850750f4e39020adcf70df81be756fad8eed2b843e3174a9d82` |

All model downloads, executable environments, rank rows, and result receipts
remain under `/tmp/refspec-candidate-benchmark.ANhNrc/learned-sparse`. No
learned-sparse implementation was added to the repository in this experiment;
the durable repository change is this evidence log.

## Experiment log — proposed retrieval snapshot seam (Euler)

Recorded: 2026-08-05 08:01:06 EDT. Status: proposal only. No retrieval-snapshot
module, production-policy switch, qualification-job change, or release-manifest
change was made. The active v1 workflow remains unchanged. This section defines
a future shared artifact that lexical, sparse, dense, graph, and English
WordNet generators could write after a separate implementation decision.

### Proposed artifact boundary

The artifact would be one immutable bundle with a small canonical JSON manifest
and one canonical JSON Lines candidate file. Under the corrected ICPSR
projection, the deterministic floor contains 214,271 rows; the exact BGE union
remains pending regeneration. The split keeps either approved candidate pool
streamable while treating the manifest and rows as one content-derived
artifact. It would carry discovery evidence only. It would not classify a
mapping, authorize judging, admit an assertion, or grant product use.

The format would seal these manifest fields:

| Field | Required meaning |
| --- | --- |
| `type` | Literal `VocabularyAtlasRetrievalSnapshot`. |
| `schemaVersion` | Exact supported snapshot-format version. |
| `languageScope` | Literal `en`. No other value qualifies for Atlas v1. |
| `semanticRing` | Literal `subject` for the current Atlas task. |
| `sourceInput` and `targetInput` | Exact concept-input pins described below. |
| `arms` | Ordered, non-empty generator metadata array. |
| `pairCount` | Number of canonical candidate rows. |
| `pairSetDigest` | SHA-256 over ordered source/target identity rows only. |
| `candidateRowsDigest` | SHA-256 over the complete canonical JSON Lines bytes, including evidence. |
| `id` | Content-derived IRI using the full snapshot basis digest. |
| `contentDigest` | SHA-256 over the complete manifest basis plus `candidateRowsDigest`; excludes only `id` and `contentDigest` to avoid a digest cycle. |

Each `sourceInput` and `targetInput` pin would contain `releaseId`,
`conceptCount`, `conceptInputDigest`, and `memberSetDigest`. The concept-input
digest would cover the complete ordered rows supplied to retrieval, including
labels, alternate labels, definitions, scope notes, hierarchy context, and
identifiers. The member-set digest would independently cover canonical member
IRIs. This distinguishes a label or context change from an endpoint-membership
change.

Each arm would declare:

- contiguous `ordinal`, starting at zero;
- absolute `armId` and non-empty `family` such as `lexical`, `sparse`, `dense`,
  `graph`, or `wordnet`;
- exact `version`;
- `implementationDigest` and `configurationDigest`;
- `scoreDirection` as `higherFirst`, `lowerFirst`, or `notScored`; and
- an integer `scoreScale` when the arm records scores.

The array order would be part of the snapshot identity. A generator could not
silently reorder arms or reuse an `armId` with different metadata.

Each candidate row would contain exactly `sourceMember`, `targetMember`, and a
non-empty `signals` array. One row may carry evidence from several arms. Each
signal would name its `armOrdinal`, declare `direction` as `sourceToTarget`,
`targetToSource`, `bidirectional`, or `undirected`, and record the applicable
positive integer `rank`, scaled integer `score`, `evidenceKind`, and
`evidenceDigest`. Optional values would be absent rather than JSON `null`.
Floating-point scores would not enter canonical bytes.

An add-only merge would require identical language, ring, source input, target
input, and arm metadata. It would union rows by `(sourceMember, targetMember)`
and union distinct signals within each row. It would preserve existing signals;
a repeated signal key with different evidence would be a conflict. This lets a
later dense or WordNet run add evidence without deleting a lexical or graph
candidate.

### Proposed fail-closed validation

A future reader would accept only canonical UTF-8 JSON and JSON Lines with
duplicate-key and non-finite-number rejection. It would reopen the exact source
and target concept inputs, recompute both input digests and both member-set
digests, and then apply all of these gates:

1. Exact top-level, input-pin, arm, pair, and signal fields match the supported
   schema version.
2. `languageScope` is exactly `en`; translation, transliteration, cross-lingual
   arms, and multilingual-only evidence are outside this artifact.
3. Input concept rows are canonical, member IRIs are unique, counts match, and
   all four recorded input digests reproduce.
4. Arm ordinals are contiguous and match array position; arm identifiers are
   unique; versions and digests are present; score metadata is internally
   consistent.
5. Pair rows are strictly ordered by source IRI and then target IRI. Duplicate
   pairs, reversed duplicates, and rows outside canonical order fail.
6. Every source endpoint belongs to the pinned source member set and every
   target endpoint belongs to the pinned target member set. Unknown or
   side-swapped endpoints fail.
7. Signals are strictly ordered by arm ordinal, direction, rank, and evidence
   digest. Every signal references a declared arm, respects its score metadata,
   and is unique within its pair.
8. `pairCount`, `pairSetDigest`, `candidateRowsDigest`, `contentDigest`, and the
   content-derived `id` all reproduce from the exact bytes.
9. A second read of the manifest, row file, and concept inputs yields the same
   paths, file types, and bytes, so a concurrent file change fails verification.

These gates would reject duplicate or unknown endpoints, unsorted rows,
noncanonical signals, digest drift, unknown arms, changed inputs, and any
language scope other than English.

### Proposed conformance checks

A future implementation would earn readiness through focused tests that show:

- two generators given the same facts in different in-memory order write
  byte-identical canonical artifacts;
- the corrected English deterministic floor reopens with exactly 214,271 pairs
  and pair-set SHA-256
  `dd1390495706da7115f59915f496ac9e766eb928c9edf1d3d60702c9680475fd`;
- one pair retains several independent signals through an add-only merge;
- changing a label, alternate label, definition, hierarchy row, arm setting,
  rank, score, or evidence digest changes snapshot identity;
- duplicate pairs, duplicate signals, unknown endpoints, unknown arm ordinals,
  reordered arms, reordered pairs, reordered signals, malformed digests,
  modified JSON Lines bytes, and non-English scope each fail with a specific
  validation error; and
- reopening from exact files reproduces the manifest, candidate bytes, all
  digests, and the content-derived identifier.

### V1 reopening decision

This proposal does not reopen v1. Adopting the seam would require an explicit
release-authority decision before any integration work. That decision would:

1. approve a versioned snapshot schema and trusted reader;
2. pin the exact six-pair English concept inputs and generator implementations;
3. regenerate the complete candidate snapshot and remeasure its exact judging
   cost;
4. rerun blind qualification, typed-relation checks, proof generation, and
   release acceptance for every affected candidate and mapping;
5. publish a new release candidate or successor with explicit supersession; and
6. update a job or release manifest only after every new digest and acceptance
   receipt closes.

A published v1 artifact would remain immutable. The snapshot seam would enter a
new versioned release path rather than rewrite v1 in place. Until that decision,
the exact frontier JSON remains experiment evidence, and current jobs continue
to use their existing inputs and manifests.

## Experiment log — five-view BGE on all six Atlas pairs (Codex)

Recorded: 2026-08-05 08:03:36 EDT. Status: complete for the fixed local BGE
arm against the real English Atlas inputs. No provider call ran, and no
production integration changed.

`BAAI/bge-small-en-v1.5` encoded five separately ranked views: labels,
field-tagged structured context, natural-language context, definition-first
context, and hierarchy context. Both directions used the same concept-to-
concept representation. Exact blockwise scores, canonical IRI tie-breaking,
and bidirectional minimum ranks matched the earlier Conference and corrected
Anatomy method.

| K | BGE-only candidates / gold | Sparse + mutual-graph + BGE candidates / gold |
| ---: | ---: | ---: |
| 1 | 35,478 / 528 | 59,518 / 548 |
| 2 | 69,437 / 555 | 108,679 / 567 |
| 3 | 102,381 / 563 | 156,826 / 569 |
| 5 | 166,517 / 569 | 250,365 / 578 |
| 10 | 321,366 / 576 | 473,037 / 582 |
| 20 | 619,278 / 580 | 896,738 / 582 |
| 50 | 1,460,455 / 581 | 2,087,665 / 582 |

The semantic arm closes the sparse-plus-graph regression set by K = 10, while
the then-current pre-projection lexical-plus-sparse floor closes it with
210,197 rows.
The next experiment computes the exact three-family overlap and reviews actual
BGE-only Atlas rows. That comparison will distinguish known-mapping efficiency
from added discovery breadth; regression completeness alone does not decide the
proposal.

The run used the unchanged Atlas corpus digest
`sha256:20bbceaec514f8681f3a07146e6a30ed5fd731857c586d327ac916d4a523317e`
and 582-pair gold digest
`sha256:d347a551e205d973d39141ba01548bce35b7f59d0caafccab60a353607bc662d`.
Its BGE vector digest is
`sha256:7856180875e5054512267b6de206ba8ed1574e96336fe098f883a96c84fde90b`.
The output is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-bge-hybrid-five-view-english.json`,
file SHA-256
`ebc1009a95114de65861e6c25222bf560cc523a5c21d1460196d3101c75d90c8`.
The complete process took 257.73 seconds, with 217.283 seconds in dense work,
and peaked at 3,620,536,320 bytes resident.

## Experiment log — exact three-family Atlas frontier and blind sample (Euler)

Recorded: 2026-08-05 08:21:05 EDT. Status: complete as experimental evidence
for the six real English Atlas pairs. The run used the local model cache with
network access disabled, made zero provider calls, and changed no production
integration.

The experiment reproduced the practical lexical family, the sparse-plus-
mutual-graph family, and the same five-view
`BAAI/bge-small-en-v1.5` arm. It retained BGE ranks through K = 50 in canonical
case, source-member, and target-member order. Before accepting the new result,
the harness reproduced the earlier lexical receipt at every practical depth,
the sparse receipt through K = 50, the BGE vector digest, and every earlier
sparse-plus-BGE pair-set digest through K = 50.

### Exact three-family frontier

The grid contains all 150 combinations of lexical and sparse depths
`1, 2, 3, 5, 10` with BGE depths `1, 2, 3, 5, 10, 20`. Of these, 109 contain
all 582 typed gold assertions. The exact depth-Pareto complete rows are:

| Lexical K | Sparse + graph K | BGE K | Candidates / gold | Batches of 25 | Pair-set SHA-256 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 3 | 1 | 1 | 228,393 / 582 | 9,136 | `1ac9933934a4febaef6a4b14d36e55746f369047e57533d2e9b4e163c3aab8bc` |
| 2 | 1 | 5 | 279,714 / 582 | 11,189 | `8ef3d2ff541441a86e7c253786dd2a8996428e25635828e0b4ed4534c3193db2` |
| 1 | 10 | 5 | 377,597 / 582 | 15,104 | `44efb4ba3e73197e26b67456a834913a9c700c773168a1d3145cbe4550c504c3` |
| 1 | 5 | 20 | 710,213 / 582 | 28,409 | `b1cb0517b670f98c497e83162ae731ccabd9454b8fe247b6581c494ca8b3dc9e` |

The first row is the lowest-cost complete three-family choice. In this
pre-access-term experiment, lexical K3 plus sparse K1 is the most efficient
known-gold choice at 210,197 candidates, 8,408 batches of 25, and pair-set SHA-256
`24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9`.
Adding BGE K1 contributes 18,196 new rows and 728 batches. This result gives
the two choices clear roles: the lean floor covers the regression set at the
lowest measured cost, while BGE supplies a separately receipted discovery
population for potential mappings beyond that set.

The 582 typed assertions remain 121 exact, 232 close, 75 broad, 119 narrow,
and 35 related. Every complete frontier row contains all five totals.

### Exact BGE additions over the lean floor

Because the lean floor already contains every typed gold assertion, all BGE-
only gold counts are exactly zero. The new rows are therefore a clean blind
population for measuring discovery value rather than duplicate regression
coverage.

| BGE K | BGE-only rows / typed gold | Added batches of 25 | Lean + BGE rows | Union pair-set SHA-256 |
| ---: | ---: | ---: | ---: | --- |
| 1 | 18,196 / 0 | 728 | 228,393 | `1ac9933934a4febaef6a4b14d36e55746f369047e57533d2e9b4e163c3aab8bc` |
| 2 | 42,823 / 0 | 1,713 | 253,020 | `a14a1c0e85edf4bcc343da3bf2f015aa79d339d1177810b91189d67328c7a581` |
| 3 | 69,331 / 0 | 2,774 | 279,528 | `08649fb88717b392bb98798125198977048b8f0c3c6f9c8fa2d50a5f7c2ed3a6` |
| 5 | 124,122 / 0 | 4,965 | 334,319 | `e0ecb81f02ca3fd4067c9975c5bb2f765529046ec8c137eb82516db5d7c72858` |
| 10 | 264,363 / 0 | 10,575 | 474,560 | `b904b0ebb5ebb8879db76959be0f4c20c994c0476c5f1458e5c010ceb6b9966c` |
| 20 | 546,669 / 0 | 21,867 | 756,866 | `198cec37330b11875bc956248d6dc0b011d2451777cde84eaf48b1539e4bd50c` |

The frontier JSON records every combination's exact candidate count, typed
gold count, batches of 25, and canonical pair-set digest. It also records each
BGE marginal by vocabulary pair and mapping-relation type.

### Compact ranks and blind review population

The deterministic BGE rank artifact is a 16,579,315-byte `uint8` file. Ranks
1–50 retain candidate membership, and sentinel 51 marks every other pair. Its
SHA-256 is
`95aecce7fd6fff3700f11e5aa0cb5e24926c6ab1f5db41c4e17ce29e020cf824`.
The canonical manifest records six matrix layouts, member-set digests, offsets,
lengths, and per-matrix digests; its file SHA-256 is
`f0a2223d9339e428016b57a01bcfaae02d51856a3d9335a5fd81589140ac99d9`.

The blind review sample contains exactly 120 actual pairs, balanced at 20 per
vocabulary pair:

- 72 BGE-only rows: two per vocabulary pair in each of six inside-cutoff rank
  bands from rank 1 through rank 20;
- 36 three-family-overlap rows: one per vocabulary pair in each inside-cutoff
  rank band; and
- 12 rows immediately outside the cutoff at ranks 21–25: two per vocabulary
  pair.

Each row includes preferred and alternate labels, definitions, scope notes,
parent and child context, the five exact BGE view strings, the retained BGE
rank, and explicit lexical K3, sparse K1, and BGE K20 membership flags. Stable
canonical pair SHA-256 ordering selects rows within every stratum. The sample
uses no reference answer during selection and emits no expert disposition or
mapping-relation label, so a later reviewer can classify it independently.
There were no short strata. Its sample digest is
`sha256:6be93190ae877e736cb0ee9ade720b5718ac258078bf7c97c224998ab855f2a8`,
and its file SHA-256 is
`300417f73210043c010be64389d60a672a59faf7c0b48d79fd0ad6a150a6a716`.

### Receipts and checks

The input corpus digest remains
`sha256:20bbceaec514f8681f3a07146e6a30ed5fd731857c586d327ac916d4a523317e`,
the gold digest remains
`sha256:d347a551e205d973d39141ba01548bce35b7f59d0caafccab60a353607bc662d`,
and the reproduced BGE vector digest is
`sha256:7856180875e5054512267b6de206ba8ed1574e96336fe098f883a96c84fde90b`.

Artifacts:

- exact frontier:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-three-family-exact-frontier-english.json`,
  file SHA-256
  `726d35f96e4c2534a877d3d4273f741f1c9f1dac618cf3ef4d404f0079fb67a3`,
  deterministic result digest
  `sha256:3dc07f9635bd8e0773109e41fd1863a21ba22aef5a90958515f22f0d1ca737e8`;
- blind review sample:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-three-family-blind-review-sample.json`;
- compact BGE ranks:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-bge-five-view-ranks.u8`; and
- compact rank manifest:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-bge-five-view-ranks-manifest.json`.

The experiment harness SHA-256 is
`34bf268a22e11c2182d77c573340bebb30d42bde27b46f23a282ab53d4e17fd0`,
and its focused test SHA-256 is
`81e40f65e93c0f770fe6a96044b5c32fa7bfa74e7706a0c2b64b9e903c4ac6af`.
Ruff, formatting, compilation, and 12 focused frontier and compact-rank tests
pass. The complete experiment took 350.58 seconds, including 221.776 seconds
for dense work, and peaked at 3,500,457,984 bytes resident.

## Experiment log — BeyondEquivalence typed-relation benchmark (Mill)

Recorded: 2026-08-05 08:20:29 EDT. Status: complete for the typed stress
benchmark and the bounded six-pair English Atlas transfer check. No provider
call ran, and no production candidate policy, qualification job, or release
artifact changed.

### What this experiment tested

This experiment kept the two critical decisions separate:

1. relation-blind candidate finding used labels, alternate labels, identifiers,
   sparse text, graph context, local dense vectors, and Open English WordNet
   (OEWN) without seeing a reference relation; and
2. evaluation joined the hidden reference relation only after retrieval, so the
   report could measure equality, broader, narrower, associative, and
   part/has-a coverage independently.

The external typed challenge is the official OAEI 2025 BeyondEquivalence
benchmark from
<https://oaei.ontologymatching.org/2025/beyondequivalence/index.html> and
Zenodo record 17091043. The selected STROMA/TaSeR g3-g7 cases contain 1,292
reference rows: 134 `=`, 560 `>`, 564 `<`, 12 `Related`, 21 `HasA`, and one
`PartOf`. The official archive contains no disjoint reference marker, so this
run records zero disjoint opportunities and creates no substitute gold rows.
The archive SHA-256 is
`04cc6dd2a2f8d173ddcc19822428fa9f505e3855840f06b19072306233d240eb`.

OEWN is the pinned `2025-edition` release at commit
`dc343f2683279ecbb13fab4e2fd778d7b162d287`. The release asset SHA-256 is
`9ca6d1dcb75f822fdd66617f7d9da48142ace38dd544d6ad5e2feca1674ad3fe`.
The noun-only index contains 97,419 normalized lemma forms, 98,220 lexical
entries, 124,202 senses, 71,864 synsets, and 74,224 undirected taxonomy edges.
The experiment retains every noun sense and treats shared synsets plus bounded
hypernym/hyponym paths as discovery evidence. A semantic judge remains
responsible for the mapping decision.

### Typed challenge result and bounded depth completion

At bidirectional K = 100, four of the five challenge cases exhaust their
smaller vocabulary side. The all-family result therefore serves as a typed
rescue and saturation diagnostic, not as an Atlas cost target.

| OEWN depth | OEWN-only candidates / typed gold | All-family candidates / typed gold | Increment over the prior all-family depth |
| ---: | ---: | ---: | ---: |
| 4 | 32,480 / 861 | 116,871 / 1,290 | baseline for the final depth check |
| 5 | 48,063 / 1,010 | 117,777 / 1,291 | +906 candidates / +1 gold |
| 6 | 61,850 / 1,078 | 118,548 / 1,292 | +771 candidates / +1 gold |

Within the staged deterministic pipeline, depth 5 adds 1,721 candidates and 16
reference relations over depth 4; depth 6 adds another 1,368 candidates and two
reference relations. Depth 5 reaches `ComicBookEditor` -> `Person`. Depth 6
reaches `CricketUmpire` -> `Person`, completing all 1,292 typed rows. The final
all-family pool covers 118,548 of 122,639 possible pairs, or 96.664%. This
completion validates OEWN as a strong challenge rescue and diagnostic arm while
making the saturation cost explicit.

The final challenge artifact is
`/tmp/refspec-candidate-benchmark.ANhNrc/beyond-equivalence-typed-wordnet-depth4-6-final.json`,
file SHA-256
`6c741cc7cd37ff524ee6dc7bdef800a2f265b0d85606bb4ecfb54922b26f88e4`,
and deterministic result SHA-256
`993f30090111af2ef8b9809b0f4134387b7488c179ee117a452c122e2d6b2c84`.
The run took 20.606 seconds and used a maximum resident-set measurement of
3,131,244,544 bytes on macOS.

### Six-pair English Atlas transfer check

The production-domain check covers 6,042 source concepts, 11,472 target
concepts, 16,579,315 possible pairs, and the sealed 582 typed Atlas mappings:
121 exact, 232 close, 75 broad, 119 narrow, and 35 related. It reproduced the
corpus digest
`20bbceaec514f8681f3a07146e6a30ed5fd731857c586d327ac916d4a523317e`,
gold digest
`d347a551e205d973d39141ba01548bce35b7f59d0caafccab60a353607bc662d`,
and current shared-adapter digest
`e87be005dcb2e2a3287ecee1ecf864c869310c3b623b472a2866da9610437628`.

Before measuring OEWN, the tool independently rebuilt lexical K = 3 plus
sparse-and-mutual-graph K = 1. The result matched the pre-projection floor exactly:
210,197 candidates, 582/582 gold, and pair-set SHA-256
`24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9`.
This fail-closed gate makes every OEWN contribution an exact add-only
comparison with the approved English floor.

| OEWN depth | OEWN candidates / gold | Exact-depth candidates / new gold | Union with floor | Unique OEWN rows over floor / unique gold |
| ---: | ---: | ---: | ---: | ---: |
| 0, shared synset | 53,145 / 516 | 53,145 / 516 | 243,383 / 582 | 33,186 / 0 |
| 1 | 203,953 / 521 | 150,808 / 5 | 390,309 / 582 | 180,112 / 0 |
| 2 | 723,307 / 525 | 519,354 / 4 | 901,426 / 582 | 691,229 / 0 |
| 3 | 1,751,528 / 528 | 1,028,221 / 3 | 1,915,424 / 582 | 1,705,227 / 0 |
| 4 | 3,272,819 / 531 | 1,521,291 / 3 | 3,418,243 / 582 | 3,208,046 / 0 |

Depth 4 adds 1,502,819 rows to the floor union beyond depth 3. The final union
contains 20.618% of the complete Cartesian space, compared with 1.268% for the
pre-projection 210,197-row floor. That floor already covers every sealed mapping, so
OEWN contributes zero unique typed gold over it at every depth. That is the
production stop gate: Atlas retains OEWN as a typed challenge rescue and
diagnostic arm, while the lexical-plus-sparse floor remains the economical
default candidate set.

#### Typed OEWN-only recall

| Depth | Exact | Close | Broad | Narrow | Related | Total |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 120 / 121 | 222 / 232 | 59 / 75 | 101 / 119 | 14 / 35 | 516 / 582 |
| 1 | 120 / 121 | 222 / 232 | 62 / 75 | 102 / 119 | 15 / 35 | 521 / 582 |
| 2 | 120 / 121 | 222 / 232 | 63 / 75 | 103 / 119 | 17 / 35 | 525 / 582 |
| 3 | 120 / 121 | 222 / 232 | 64 / 75 | 104 / 119 | 18 / 35 | 528 / 582 |
| 4 | 120 / 121 | 222 / 232 | 65 / 75 | 105 / 119 | 19 / 35 | 531 / 582 |

The three mappings first reached at depth 4 are:

- `AGE GROUPS` -> `age` (`broadMatch`);
- `Bonds` -> `BANKS` (`relatedMatch`); and
- `Information` -> `information literacy` (`narrowMatch`).

The 51 mappings outside the depth-4 OEWN set retain their actual labels and
types below. They remain covered by the pre-projection 210,197-row floor.

- Broad (10): `WORKING WOMEN` -> `women`; `WORKERS BY PROFESSION` ->
  `workers`; `Aged` -> `age`; `Foreign investments in U.S.` -> `investments`;
  `Grant programs-foreign relations` -> `programs`; `Grant programs-National
  defense` -> `programs`; `Grant programs-science and technology` ->
  `programs`; `Grant programs-veterans` -> `programs`; `Loan programs-health`
  -> `programs`; `Marketing quotas` -> `marketing`.
- Close (10): `SINGLE OCCUPANCY HOUSEHOLDS` -> `living alone`; `TUTORING` ->
  `tutoring`; `Buses` -> `BUSES`; `Human trafficking` -> `HUMAN TRAFFICKING`;
  `Seamen` -> `SEAMEN`; `Small businesses` -> `SMALL BUSINESSES`; `Women` ->
  `WOMEN`; `Carpools` -> `carpools`; `Small businesses` -> `small businesses`;
  `Women` -> `women`.
- Exact (1): `WORKING WOMEN` -> `working women`.
- Narrow (14): `FACILITIES` -> `correctional facilities (adults)`; `ELECTIONS`
  -> `congressional elections (US House)`; `Energy` -> `ENERGY CONSUMPTION`;
  `Energy` -> `ELECTRICAL ENERGY CONSUMPTION`; `Information` -> `INFORMATION
  TECHNOLOGY TRAINING`; `Women` -> `MARRIED WOMEN`; `Bankruptcy` ->
  `bankruptcy reorganization`; `Health` -> `health education`; `Health` ->
  `health transitions`; `Immigration` -> `immigration status`; `Infants and
  children` -> `children`; `Labor` -> `labor law`; `Licensing and registration`
  -> `licensing`; `Women` -> `battered women`.
- Related (16): `NATIONALITY` -> `nationalism`; `PEACE AND CONFLICT STUDIES` ->
  `conflict`; `ECONOMISTS` -> `economics`; `FASCISM` -> `racism`; `SMALL
  BUSINESSES` -> `family businesses`; `LEARNING` -> `learning disabilities`;
  `BAIL` -> `jails`; `TERRORISM` -> `terrorists`; `LANGUAGE` -> `language
  policy`; `Blood` -> `BLOOD DONATION`; `Fees` -> `FINES`; `Income taxes` ->
  `INCOME`; `Vocational education` -> `VOCATIONAL EDUCATION CERTIFICATES`;
  `Gasoline` -> `gasoline prices`; `Information` -> `information users`;
  `Prisoners` -> `prisons`.

### Reproducibility and bounded decision

The primary and repeat Atlas artifacts are:

- `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-wordnet-depth0-4-english.json`,
  file SHA-256
  `af40de9069f4390c4b3c618c3e651fd7cb84451b876aa3bfb904d7f19d8593d5`;
  and
- `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-wordnet-depth0-4-english-repeat.json`,
  file SHA-256
  `4cd5b813a82d898e11b9315cbe1ded3498d41047e70e6b6897584f371b66433a`.

Wall-clock fields differ, while both runs reproduce deterministic result
SHA-256
`c9144d5c87a261d65146dbad4871308e44518d16f61d5333521f1a1a86bf2a23`,
OEWN evidence SHA-256
`87f4510b3e9c983bbbb6dc12a306d05837974b75a706cd8681648cb868b77f69`,
and the exact floor receipt. The primary run took 104.325 seconds, including
79.157 seconds to independently rebuild the floor and 9.360 seconds for the
bounded OEWN search. Its macOS maximum resident-set measurement was
1,728,512,000 bytes. The repeat took 84.351 seconds.

The Atlas OEWN benchmark tool SHA-256 is
`0f3ee701291270173dbc77928433c84421fe2ae32698295f84516b962e8317a5`;
its focused test file SHA-256 is
`78952f7995c7cb9cb4049bc62a39f9c61b7c89a570c7f7416173c4974ac39e50`.
The new focused checks plus the typed challenge checks report 10 passed and one
optional-dependency skip; Ruff reports clean. A conditional depth-5/6 Atlas
process was stopped during the independent floor rebuild and produced no
artifact. The zero-unique-gold gate and 3,208,046-row marginal at depth 4 close
the Atlas WordNet scope with an evidence-backed default decision.

## Experiment log — cross-arm candidate Pareto frontier (Kierkegaard)

Recorded: 2026-08-05 08:42 EDT. Status: exact complete-recall Pareto fronts
proved for the sealed 305-relation Conference corpus. The run normalized 26
existing candidate-discovery arms into one canonical pair universe, replayed
every retained receipt before admission, made no provider call, and added no
new model family. English is the production language scope. Multilingual,
cross-lingual, and translation-specialized retrieval is excluded from this
frontier and from the production recommendation.

### What the optimizer measures

`tools/optimize_relation_candidate_pareto.py` consumes a compressed rank
bundle. Each row is one independently selectable arm, each column is one
canonical `case/source/target` pair, zero means absent at the largest measured
depth, and a positive integer is the pair's minimum bidirectional rank. Fixed
candidate sets use rank one. The bundle contains 270,760 possible Conference
pairs, all 305 gold pairs, 26 arms, and 192 measured depth choices. Its pair
memberships compress to 268,584 distinct signatures.

The objective is the exact size of the selected pair-set union, not the sum of
per-arm counts. The search enforces at most one depth per arm and 305/305 gold
coverage. For every complete point it recomputes the canonical pair-set
SHA-256, per-arm exclusive candidates, unique gold rescues, candidates per
unique rescue, and all retrieval-challenge slices.

The first exact mixed-integer formulation was operationally unsuitable. It was
terminated without a result after 339.57 seconds at 3,813,031,936 bytes peak
resident memory. It was not rerun. The replacement uses exact Python-integer
bitsets over all 270,760 pairs. A deterministic greedy pass supplies only an
upper bound; exhaustive branch-and-bound partitions complete solutions by the
rarest uncovered gold pair and proves the optimum. The four fronts completed
in 5.25 seconds at 213,893,120 bytes peak resident memory.

Six focused tests compare the bounded solver with independent exhaustive
enumeration on a synthetic bundle, cover the provider and reranker exclusions,
check graph and reservoir failures, and repeat digests. The focused optimizer
tests pass 6/6. The optimizer plus related lexical and retrieval checks pass
18 tests with one optional-dependency skip; Ruff passes.

### Arms and fail-closed dependencies

The bundle contains:

- the existing production semantic rules;
- seven nonduplicate lexical controls: raw and normalized Levenshtein,
  partial ratio, token-set ratio, WRatio, acronym matching, and character
  trigrams;
- independent deterministic label, context, and character sparse views;
- the graph-only addition generated from exact normalized-label anchors plus
  mutual top-1 anchors across all three declared sparse views;
- symmetric five-view BGE, prefixed five-view Nomic, and prefixed five-view
  Arctic local dense arms;
- three Google and two OpenAI arms replayed from their sealed normalized
  float32 vectors;
- separate MiniCOIL label and structured ranks plus separate SPLADE++ label
  and structured ranks; and
- MiniLM cross-encoder and ColBERT late-interaction add-only ranks.

Every dense replay reproduced its sealed candidate and gold counts at all
eight measured depths. Both learned-sparse rank files and both reranker files
reproduced every reported depth before bundle admission.

The graph arm must retain its declared anchor-policy SHA-256
`7fce7f8c07ffa68458a65412a58e951ee20ec07def08dab250b51264c0a1b9de`.
The optimizer rejects a graph arm without that policy. Both rerankers are
validated as strict subsets of the same 270,727-pair K=100 reservoir. Each had
to score 4,812 directional jobs and 535,389 directional query-candidate pairs.
The optimizer rejects any reranker rank outside the reservoir. These
dependencies are evidence that a reranker can prioritize only what another
finder already supplied; it cannot discover an absent pair.

### Exact complete Conference fronts

The Pareto objectives are candidate count and active-arm count. “No provider”
removes the saved Google and OpenAI arms. “No reranker” removes MiniLM and
ColBERT. Every row finds 305/305 gold relations.

| Scenario | Active arms | Exact candidates | Selected depths | Pair-set SHA-256 |
| --- | ---: | ---: | --- | --- |
| Unrestricted | 1 | 161,555 | OpenAI `text-embedding-3-large` K50 | `b017edfbc353e7063ef332e6ca82c6754c59588c0f079090452ac66247763945` |
| Unrestricted | 2 | 80,160 | Google `gemini-embedding-2` K5 + MiniCOIL structured K20 | `c5db1cdbf88f182d5d0c2c17d6c9cdba68ed42e7b3e8c52a912eef95baf652d6` |
| Unrestricted | 3 | 80,158 | label sparse K1 + Google `gemini-embedding-001` retrieval K5 + MiniCOIL structured K20 | `90078bdbe4789a4d3d8a83c2ecb742e14608fd516a279acf26b2a4e34a5a0db5` |
| **Unrestricted minimum** | **4** | **76,087** | label sparse K3 + Google `gemini-embedding-001` retrieval K1 + OpenAI `text-embedding-3-large` K1 + MiniCOIL structured K20 | `22dea124106d2cf729b3077d576dcf572f101e0b6c70f81a6778ddcd32d9a8cc` |
| No provider | 1 | 231,826 | BGE five-view K50 | `72b46beb46121b465e79b8f4b2a78cf7a1057219e5851129c41a6cd9e9070ae8` |
| **No-provider minimum** | **2** | **116,909** | Nomic five-view K10 + MiniCOIL structured K20 | `449bdec30ecdd2c0da78b3e569354b3c087ffae746c3e295f3f02eb119343125` |

The no-reranker frontier is byte-for-byte identical to the unrestricted
frontier. The no-provider-no-reranker frontier is byte-for-byte identical to
the no-provider frontier. Neither learned reranker appears on any exact
complete frontier. This closes the reranker question for Conference candidate
finding: the saved rerankers may order a reservoir for judging, but they do not
reduce the minimum add-only discovery union.

All ten observed English retrieval-challenge slices reach 100% on every
complete point: 21/21 abbreviation, 58/58 broader/narrower granularity, 58/58
compound/compositional, 40/40 hierarchy/graph, 10/10 inverse-directional
property, 140/140 lexical exact, 26/26 lexical near, 64/64 semantic gap, 57/57
substring fragment, and 3/3 token reordered. These are overlapping retrieval
labels, not mapping-relation judgments.

### Minimum-union marginal evidence

The 76,087-row minimum is much smaller than the sum of its four standalone
arms because overlap is material.

| Arm | Standalone candidates / gold | Exclusive candidates | Unique gold rescues | Exclusive candidates per unique rescue |
| --- | ---: | ---: | ---: | ---: |
| Label sparse K3 | 5,571 / 233 | 875 | 2 | 437.5 |
| Google `gemini-embedding-001` retrieval K1 | 4,265 / 271 | 507 | 6 | 84.5 |
| OpenAI `text-embedding-3-large` K1 | 4,244 / 258 | 434 | 2 | 217.0 |
| MiniCOIL structured K20 | 73,958 / 289 | 66,403 | 18 | 3,689.06 |

The no-provider 116,909-row minimum has a different cost shape. Nomic K10 has
42,951 exclusive candidates and 16 unique gold rescues, or 2,684.44 per
rescue. MiniCOIL structured K20 has 32,790 exclusive candidates and four
unique rescues, or 8,197.5 per rescue. This is useful Conference evidence for
complementarity, but it is not enough to make MiniCOIL the production default:
its earlier Anatomy run used 21.935 GB and 18.8 minutes, and it was measured on
the superseded text-poor Anatomy adapter.

### Production decision across the evidence sets

Conference proves that heterogeneous, shallow arms can reduce a complete
candidate union. It does not define the production floor. Conference contains
directional conference-ontology properties and only equality references.
Corrected Anatomy contains biomedical synonyms and is a stress test. The six
real Atlas pairs contain English regulatory, legislative, public-policy, and
social-science terms plus sealed exact, close, broad, narrow, and related
mappings; that is the primary production evidence.

At this pre-access-term point, the real-Atlas floor was lexical K3 plus
deterministic sparse and mutual-anchor graph K1: 210,197 candidates,
582/582 typed mappings, and pair-set SHA-256
`24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9`.
It covers 121/121 exact, 232/232 close, 75/75 broad, 119/119 narrow, and 35/35
related mappings. It requires no provider and no biomedical specialist model.
The later ICPSR endpoint experiment preserves K3/K1 while superseding this
exact count and digest with 214,271 rows and `dd139049...`.

The supporting boundaries are:

- Corrected Anatomy resolves OBO synonym nodes before retrieval. Sparse plus
  gated graph reaches 1,510/1,516 at K20; adding general-purpose BGE reaches
  1,516/1,516 at K50 with 712,254 candidates. This supports text correction,
  additive semantic retrieval, and resource bounds; it does not justify a
  biomedical-only production dependency for the policy domain.
- Adding BGE K1 to the complete Atlas floor contributes 18,196 blind rows and
  zero additional known typed mappings. Keep it as a separately measured blind
  discovery population until judging shows enough new policy relations to pay
  for it.
- Nomic's general-English five-view behavior and the provider embeddings
  plausibly transfer to policy and social-science language, but their exact
  Conference front is not an Atlas transfer result. They are proposal arms,
  not release-floor arms, until evaluated against the same six Atlas inputs and
  blind judging population.
- MiniCOIL supplies essential Conference rescues but has an unfavorable
  Anatomy resource profile. SPLADE++ has a licensing-lineage caveat. Neither
  belongs in the default large-vocabulary floor on current evidence.
- Open English WordNet completes the BeyondEquivalence typed challenge at
  depth 6, but adds zero unique typed gold over the Atlas floor and millions of
  Atlas rows. Keep it as a typed challenge diagnostic, not the default policy
  candidate generator.
- A reranker or language model may prioritize and judge the additive union. It
  must never delete candidates or act as the only finder. False positives are
  acceptable discovery input; candidate count still controls judging cost.

The next proposal should preserve this lean English Atlas floor, keep graph
expansion anchor-gated, and attach optional discovery arms as separately
receipted add-only populations. Promote an optional arm only after blind Atlas
judging demonstrates unique policy/social-science relations and reports the
added candidates per accepted relation. Do not make Conference completeness,
Anatomy biomedical specialization, or BeyondEquivalence saturation a release
gate for a production domain they do not represent.

### Reproducibility receipts

- Compact Conference bundle:
  `/tmp/refspec-candidate-benchmark.ANhNrc/pareto/conference-candidate-pareto-bundle.npz`,
  file SHA-256
  `1ec0654dd054fb65fcece0672c08dcdd521c8174786d5568ce6fc81f8284d092`,
  metadata digest
  `sha256:6412877fdb4ab88c38b79a21d73c1bc2f1c487abe5cf05e52e7e6bf8831b72de`,
  and rank-array digest
  `sha256:8c59b1cfe16ffe634bfc2b110e9dd842117dd47bb150b800101b2f1773b864aa`.
- Exact result:
  `/tmp/refspec-candidate-benchmark.ANhNrc/pareto/conference-candidate-pareto-result.json`,
  file SHA-256
  `06318591d678539a75e1f0ed81bf9077a09fce80bcf3fcd80174f6522547c30a`
  and deterministic result digest
  `sha256:e05df06a1b730c32522781e538cde61f60a96c184ffbcc7c616306283254f8e8`.
- Two-search repeat:
  `/tmp/refspec-candidate-benchmark.ANhNrc/pareto/conference-candidate-pareto-repeat.json`,
  file SHA-256
  `295199d1ef122f5d512cf964b3843a7a841b2bd7ccca9964485215b394d246f2`;
  it reproduces the same deterministic result digest.
- Independent replay of all 12 selected frontier unions:
  `/tmp/refspec-candidate-benchmark.ANhNrc/pareto/conference-candidate-pareto-independent-replay.json`,
  file SHA-256
  `d8795ccb1a8bad2fc6496e55fd11c714f03852a5b2f692a4bea2068f2dc6cf2f`.
  It rebuilds candidate count, 305/305 coverage, and pair-set SHA-256 directly
  from the rank matrix without using the optimizer's compressed objective.
- Bundle builder SHA-256:
  `abc33b7286c7d7f6ddbccefd11b0c5e263cdd9f79a9bba82a19f101ca78b50d2`.
- Optimizer SHA-256:
  `e73e101e122eb33c7a3ae18990ab8744bfc26e91a9f4f933aba6d957db380a62`.
- Focused test SHA-256:
  `c19749a89f768183a1b0328ae94bc0d4bf7d4dddbdc7b8c31340555e2a6214f5`.

## Experiment log — independent historical-judge concordance audit (Codex)

Recorded: 2026-08-05. Status: bounded read-only comparison complete. This
experiment made no provider call, changed no manual verdict, and changed no
qualification or production artifact. It measures concordance with the two
historical judge families; it does not establish objective semantic accuracy.

### Chain of custody and comparison definitions

The independent 108-row verdict table remained byte-for-byte at raw SHA-256
`2a485ea70be6b579f74735a721f57ba86d0455437ea16fa964ff5651bb8b7d9c`
before the key was compared. Its 108 audit IDs exactly match the blind sample
in order, the key IDs exactly match them, and every one of the 18
pair-by-generation-class strata contains six rows. The blind sample's
canonical SHA-256 is
`20eb9b423284f10dd4a99e003c93101c34a0fd6bc24583951ac4ba85eafed1ff`,
which is the digest pinned by the key. The raw blind file includes the writer's
terminal newline and has SHA-256
`b646468d1685608933629fe7bbb5aae6ce05e18f615a4a6871abc4794099485b`.
The sealed key has raw SHA-256
`5320b9bc9e1c4f756c44bbff4272b0d743d512672a058a9e8e81714896f39c59`
and canonical SHA-256
`dfdf157fa098435146518f55e271ddf364d8d05368a13bdfc82ee4017bd2cd68`.

Three measures remain separate:

1. **Exact verdict** requires the same seven-way verdict.
2. **Support versus no support** groups `same`, `near_same`, both hierarchy
   directions, and `related` as support; it groups `unrelated` and
   `insufficient_evidence` as no support. The latter binary grouping does not
   erase the stored reject-versus-abstain distinction.
3. **Compatible relation and direction** applies the production v2 agreement
   lattice only when both reviewers support a relation. Identical directed
   relations are compatible, as are `same` plus `near_same` at
   `skos:closeMatch`; other relation mixtures are incompatible.

### Exact concordance results

| Comparison | Exact verdict | Support/no support | Compatible relation/direction when both support |
| --- | ---: | ---: | ---: |
| Independent reviewer vs Gemini | 89/108 (82.41%) | 105/108 (97.22%) | 57/69 (82.61%) |
| Independent reviewer vs OpenAI | 76/108 (70.37%) | 101/108 (93.52%) | 54/66 (81.82%) |
| Gemini vs OpenAI | 74/108 (68.52%) | 102/108 (94.44%) | 51/67 (76.12%) |
| Independent reviewer matches both providers | 67/108 (62.04%) | 100/108 (92.59%) | 45/65 (69.23%) across all-three-support rows |

The independent reviewer recorded 70 support verdicts and 38 `unrelated`
verdicts. Gemini and the reviewer disagreed on the binary support boundary in
3/108 rows; OpenAI and the reviewer disagreed in 7/108. The much larger drop
from binary to relation-compatible agreement localizes the harder judgment to
relation kind and hierarchy direction, not whether a potentially useful
cross-vocabulary association exists.

### Admission, controls, and generation classes

For the 72 non-control rows, all 41 historically admitted candidates received
independent support. Adding the independent reviewer to the same v2 lattice
would preserve the exact admitted relation for 37/41 (90.24%) and would reject
four otherwise admitted rows because the reviewer chose a different supported
relation. Those four were `Day care` to `CHILD CARE`, `Information` to
`ACCESS TO INFORMATION`, `Credit` to `DEBTS`, and `Safety` to `accidents`.
This is concordance evidence about plausible granularity choices, not an
objective error label for either answer.

Of 26 historical rejections, the independent reviewer found support in 16 and
no support in 10. Fifteen of those 16 supported rejections had two supporting
provider answers that disagreed on relation kind or direction; one had a
provider support/no-support split. Of five historical abstentions, the
reviewer found support in three and no support in two. If this reviewer had
been imposed as a mandatory third machine without a new policy, the sample's
non-control admissions would fall from 41 to 37; that counterfactual is an
audit measurement, not a proposed production change.

| Historical generation class | Reviewer support | Historical dispositions | Gemini exact | OpenAI exact | Provider-pair exact | Provider-pair compatible when both support |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Alternate-label equality | 18/18 | 9 admitted; 9 rejected | 10/18 | 11/18 | 9/18 | 9/18 |
| Edit-distance near miss | 6/18 | 4 admitted; 2 abstained; 12 rejected | 17/18 | 12/18 | 11/18 | 4/5 |
| Normalized-label equality | 18/18 | 13 admitted; 3 abstained; 2 rejected | 14/18 | 5/18 | 6/18 | 13/15 |
| Substring near miss | 18/18 | 15 admitted; 3 rejected | 14/18 | 17/18 | 15/18 | 15/18 |
| Random negative control | 2/18 | 18 controlled | 18/18 | 17/18 | 17/18 | 1/1 |
| Sibling distractor | 8/18 | 18 controlled | 16/18 | 14/18 | 16/18 | 9/10 |

The controls are audit populations, not gold negatives for every relation.
The reviewer found no support for 16/18 random controls and 10/18 sibling
distractors. Siblings can have a valid `related` association, and a seeded
random pair can occasionally land on a real relation. Treating either class as
an objective all-negative accuracy denominator would therefore misstate the
task.

### Proposal implication and reproducibility

The evidence supports keeping blind independent families and the existing
relation-aware lattice. It also supports a cost-bounded adjudication lane for
the small subset where both families find support but disagree on relation or
direction. Such adjudication should receive the original concept facts and
the competing verdicts only after both blind answers are sealed; it should not
turn a no-support result into an admission by default. This concentrates any
extra judgment cost on the demonstrated uncertainty and preserves candidate
recall for later review. It remains a proposal input, not production
integration.

The reproducible read-only comparator is
`tools/compare_atlas_judgment_manual_audit.py`; its focused tests are
`tests/test_compare_atlas_judgment_manual_audit.py`. The focused suite reports
2 passed, and Ruff plus format checks pass. The generated report is
`/tmp/refspec-candidate-benchmark.ANhNrc/judge-audit-manual-concordance-108.json`,
file SHA-256
`1035557c191ea4c7b30a0c6c79cba88ccc9f52343c33e09585ded0cac580be10`.

## Experiment log — fixed-decision real-label retrieval yield (Codex)

Recorded: 2026-08-05. Status: bounded read-only join complete. This experiment
made no provider call, changed no reviewer decision, and changed no
qualification or production artifact. It measures potential-relation yield in
a deterministic, relation-blind review sample; it does not establish mapping
ground truth or estimate whole-population precision.

### Chain of custody and population

The 120 decisions remained byte-for-byte at raw SHA-256
`4dc6a07fe2f0798254e0a0ef02dd497125ac98a3f5c9cf830596a8fc3f5256f7`.
The analyzer verified exactly one supported verdict for ordered rows 1–120 and
produced decision digest
`sha256:aefd2e4d384d87017b5a62bf94759dbbd816c9c8e7995ca894cb42f91fdd4932`.
It also reopened the 120-row sample at raw SHA-256
`300417f73210043c010be64389d60a672a59faf7c0b48d79fd0ad6a150a6a716`,
reproduced its internal row digest
`sha256:6be93190ae877e736cb0ee9ade720b5718ac258078bf7c97c224998ab855f2a8`,
and verified every selection digest, rank band, cutoff membership, and retrieval
category before joining by row number. The joined-row digest is
`sha256:eb129d8b470471ea37eb71b544f623953ea26e68edd029abef1d72a3dbb53e3d`.

The sample contains 20 rows per real Atlas pair. Within each pair it has two
BGE-only rows and one all-three-family row in each of six bands from rank 1
through rank 20, plus two rows from ranks 21–25. Selection used the lowest
canonical pair SHA-256 within each stratum. Those quotas make comparisons
repeatable and balanced, but they deliberately differ from each stratum's
population size. Percentages below are sample yield, not candidate-pool
precision estimates.

### Exact discovery-yield results

Every verdict except `unrelated` or `insufficient_evidence` counts as a
potential relation worth blind judging. The reviewer found 53/120 (44.17%): 44
`related`, four `target_is_broader`, and five `target_is_narrower`. The other
67 were `unrelated`; the reviewer did not use `insufficient_evidence`.

| Retrieval slice | Potential relations | Sample yield |
| --- | ---: | ---: |
| BGE-only inside K20 | 34/72 | 47.22% |
| Three-family overlap inside K20 | 17/36 | 47.22% |
| All rows inside K20 | 51/108 | 47.22% |
| Just outside K20, ranks 21–25 | 2/12 | 16.67% |

The identical BGE-only and all-three overlap yield is useful independence
evidence: in this balanced sample, the semantic arm adds plausible candidates
at the same rate as rows already corroborated by lexical and sparse retrieval.
It is not evidence that both underlying populations have identical precision.

| Atlas pair | Potential relations | Sample yield |
| --- | ---: | ---: |
| CRS policy areas ↔ Federal Register | 7/20 | 35% |
| CRS subjects ↔ Federal Register | 8/20 | 40% |
| CRS subjects ↔ CRS policy areas | 6/20 | 30% |
| ELSST ↔ ICPSR | 12/20 | 60% |
| Federal Register ↔ ELSST | 11/20 | 55% |
| Federal Register ↔ ICPSR | 9/20 | 45% |

| BGE rank band | Potential relations | Sample yield |
| --- | ---: | ---: |
| Rank 1 | 16/18 | 88.89% |
| Ranks 2–3 | 8/18 | 44.44% |
| Ranks 4–5 | 12/18 | 66.67% |
| Ranks 6–10 | 7/18 | 38.89% |
| Ranks 11–15 | 6/18 | 33.33% |
| Ranks 16–20 | 2/18 | 11.11% |
| Ranks 21–25 | 2/12 | 16.67% |

The rank-4–5 rebound over ranks 2–3 shows why these small deterministic strata
must not be treated as a calibrated probability curve. The broad direction is
still clear: the highest ranks carry the strongest yield, while the tail
contains fewer but still real possibilities.

### What the labels reveal

Representative BGE-only additions include `Land use and conservation` →
`Range management` (`target_is_narrower`, rank 1), `Evidence and witnesses` →
`Law` (`target_is_broader`, rank 1), `Customs enforcement` →
`Countervailing duties` (`target_is_narrower`, rank 3), `Housing supply and
affordability` ↔ `Manufactured homes` (`related`, rank 5), `Bilingual
education` ↔ `LANGUAGE DEVELOPMENT` (`related`, rank 1), and `Suicide` ↔
`loneliness` (`related`, rank 1). These examples span hierarchy, policy
specialization, and associative search links that surface forms alone need not
find.

The two potential rows just outside K20 are `Scholarships and fellowships` ↔
`HUMANITIES AND ARTS EDUCATION` and `Grant programs-health` ↔ `MALNUTRITION`,
both `related` at rank 22. They show that K20 is a cost boundary, not a semantic
boundary.

Observed failure modes are suitable judge inputs rather than reasons to remove
the arm: thematic co-occurrence without a usable relation (`Palestinians` ↔
`Hostages`, rank 1); shared-domain drift (`MILITARY EDUCATION` ↔ `military base
closures`, rank 2); ambiguous generic words (`Waste treatment and disposal` ↔
`treatment`, all-three overlap at rank 15); lexical polysemy (`U.S. Government
Manual` ↔ `MANUAL WORKERS`, all-three overlap at rank 17); and broad contextual
association (`Government-sponsored enterprises` ↔ `automobile insurance`,
rank 17). The all-three false positives confirm that signal agreement is a
priority cue, not an automatic mapping decision.

### Proposal implication and reproducibility

The evidence supports an add-only English BGE discovery arm and blind LLM
judging of its unique rows. It also supports reporting K20 and K25 as explicit
cost/recall choices: K20 contains 51/53 potential rows in this sample, while a
small audited tail preserves visibility into what the cutoff leaves behind.
Production monitoring should retain a deterministic outside-cutoff sample so
future evidence can move that boundary. This is proposal input only; no
production policy has been selected or integrated.

The reproducible analyzer is
`tools/analyze_atlas_candidate_manual_audit.py`, SHA-256
`18a9606c8316f822a8d5f7217caeafcf642b9494cec2a88319924e92efb3d56c`;
its focused tests are `tests/test_analyze_atlas_candidate_manual_audit.py`,
SHA-256
`61e5815d4ccf0aae02c00ddc01692f217beae3cedd7fcae692807a8b17b65645`.
The focused suite reports 3 passed, and Ruff plus format checks pass. The full
joined report is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-candidate-manual-audit-analysis.json`,
file SHA-256
`bcf3fe57c3abedc4610dafa78623db6f51f397487cb37b9aa80c7f41998bbb76`
and deterministic analysis digest
`sha256:adb67ddcfbb7223fa7c759421c556bd615023b7673900a94c41600ceb4db3c2a`.

## Experiment log — exact pre-access-term grouped Batch cost frontier (Codex)

Recorded: 2026-08-05. Status: complete as proposal-only evidence. Provider
calls: zero. Production integration: unchanged and on hold.

This experiment reopened the exact six English Atlas concept pairs, rebuilt
the verified lexical K3 plus sparse/mutual-graph K1 floor, and combined it with
the retained five-view BGE rank bytes. It built `CandidateRow` values carrying
the full production hierarchy-aware source and target context. Retrieval
class, rank, and evidence remain absent from both scorer and blind-judge input.

The local planner uses the current approved configuration: one OpenAI scorer,
one Gemini judge, one OpenAI judge, 25 rows per request, a 400-token output
allowance per row, the 0.5 Batch pricing factor, `gpt-5.6-terra`, and
`models/gemini-3.6-flash`. Every value below comes from rendered request bytes;
none is an average-cost extrapolation.

Candidate identifiers use the fixed proposal-only policy
`atlas-relation-candidate-proposal-cost-plan-v1`, derived from the case and two
member IRIs. This makes packing and its small per-request rounding effects
reproducible without selecting the future production catalog format. A later
approved integration must rerun this receipt after it seals production
candidate identities.

### Exact campaign frontier

| Option | Candidates | Requests | Jobs | Input tokens | Output allowance | Cost | Pair-set SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Lexical K3 + sparse/graph K1 | 210,197 | 25,230 | 256 | 246,916,397 | 252,241,200 | $1,843.745645 | `24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9` |
| Floor + BGE K1 | 228,393 | 27,417 | 275 | 266,874,311 | 274,071,600 | $2,001.784630 | `1ac9933934a4febaef6a4b14d36e55746f369047e57533d2e9b4e163c3aab8bc` |
| Floor + BGE K3 | 279,528 | 33,552 | 332 | 323,804,109 | 335,433,600 | $2,446.909140 | `08649fb88717b392bb98798125198977048b8f0c3c6f9c8fa2d50a5f7c2ed3a6` |
| Floor + BGE K5 | 334,319 | 40,128 | 397 | 385,187,770 | 401,185,200 | $2,924.289266 | `e0ecb81f02ca3fd4067c9975c5bb2f765529046ec8c137eb82516db5d7c72858` |
| Floor + BGE K10 | 474,560 | 56,955 | 554 | 542,378,165 | 569,476,800 | $4,146.231540 | `b904b0ebb5ebb8879db76959be0f4c20c994c0476c5f1458e5c010ceb6b9966c` |
| Floor + BGE K15 | 616,329 | 73,968 | 714 | 700,922,840 | 739,594,800 | $5,381.054027 | `8b333d186df553e362ada7913208fdc07bf2f861be26d4427cc14cca69a4e922` |
| Floor + BGE K20 | 756,866 | 90,834 | 872 | 857,757,806 | 908,239,200 | $6,604.815817 | `198cec37330b11875bc956248d6dc0b011d2451777cde84eaf48b1539e4bd50c` |
| Floor + BGE K25 | 895,840 | 107,511 | 1,027 | 1,012,657,146 | 1,075,014,000 | $7,814.797632 | `4e952b9353f6a19cd69bbe225061a6990453645a4671ed57a1c89c9ce3191b9f` |
| Floor + BGE K50 | 1,578,319 | 189,408 | 1,793 | 1,773,034,279 | 1,893,985,200 | $13,756.282989 | `7170fea7d540b118f40420d687310137008148cc3ac7b63c996bce1021052275` |

The request total counts all three independent jobs. For example, the lean
option has 8,410 scorer requests, 8,410 Gemini judge requests, and 8,410
OpenAI judge requests. Its costs divide into $732.152124 for scoring,
$377.412530 for Gemini judging, and $734.180991 for OpenAI judging. The full
receipt retains this work/family breakdown for every option and pair.

The exact decision-relevant split is:

| Option | OpenAI scorer | Two blind judges | Three-pass total | Scorer share |
| --- | ---: | ---: | ---: | ---: |
| Lean floor | $732.152124 | $1,111.593521 | $1,843.745645 | 39.71% |
| Floor + BGE K1 | $794.928223 | $1,206.856407 | $2,001.784630 | 39.71% |
| Floor + BGE K3 | $971.729898 | $1,475.179242 | $2,446.909140 | 39.71% |
| Floor + BGE K5 | $1,161.338068 | $1,762.951198 | $2,924.289266 | 39.71% |
| Floor + BGE K10 | $1,646.674313 | $2,499.557227 | $4,146.231540 | 39.71% |
| Floor + BGE K15 | $2,137.130766 | $3,243.923261 | $5,381.054027 | 39.72% |
| Floor + BGE K20 | $2,623.198736 | $3,981.617081 | $6,604.815817 | 39.72% |
| Floor + BGE K25 | $3,103.796008 | $4,711.001624 | $7,814.797632 | 39.72% |
| Floor + BGE K50 | $5,463.721848 | $8,292.561141 | $13,756.282989 | 39.72% |

Because the current release design judges every selected candidate, removing
the paid scorer while retaining both blind judges removes about 39.7% of this
conservative ceiling without changing candidate or judgment coverage. This is
a proposal decision; the current historical scorer receipts remain valid.

### Exact per-pair totals

Each row below totals the scorer and both judges.

| Option | Pair | Candidates | Requests | Jobs | Input tokens | Output allowance | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Lean | CRS policy–FR | 8,638 | 1,038 | 12 | 10,854,848 | 10,365,600 | $76.533937 |
| Lean | CRS subjects–FR | 14,616 | 1,755 | 15 | 13,357,770 | 17,539,200 | $124.073197 |
| Lean | CRS subjects–policy | 6,518 | 783 | 9 | 8,751,804 | 7,821,600 | $58.358215 |
| Lean | ELSST–ICPSR | 77,400 | 9,288 | 105 | 103,731,494 | 92,880,000 | $692.782064 |
| Lean | FR–ELSST | 55,074 | 6,609 | 65 | 62,614,492 | 66,088,800 | $480.820661 |
| Lean | FR–ICPSR | 47,951 | 5,757 | 50 | 47,605,989 | 57,546,000 | $411.177571 |
| BGE K1 | CRS policy–FR | 9,336 | 1,122 | 12 | 11,732,365 | 11,203,200 | $82.718734 |
| BGE K1 | CRS subjects–FR | 15,505 | 1,863 | 15 | 14,156,892 | 18,606,000 | $131.605329 |
| BGE K1 | CRS subjects–policy | 6,937 | 834 | 12 | 9,310,248 | 8,324,400 | $62.105182 |
| BGE K1 | ELSST–ICPSR | 83,446 | 10,014 | 113 | 111,090,209 | 100,135,200 | $746.091665 |
| BGE K1 | FR–ELSST | 60,207 | 7,227 | 69 | 68,104,389 | 72,248,400 | $525.259318 |
| BGE K1 | FR–ICPSR | 52,962 | 6,357 | 54 | 52,480,208 | 63,554,400 | $454.004402 |
| BGE K3 | CRS policy–FR | 11,184 | 1,344 | 15 | 14,046,818 | 13,420,800 | $99.083817 |
| BGE K3 | CRS subjects–FR | 18,558 | 2,229 | 18 | 16,904,382 | 22,269,600 | $157.475577 |
| BGE K3 | CRS subjects–policy | 8,467 | 1,017 | 12 | 11,354,711 | 10,160,400 | $75.793167 |
| BGE K3 | ELSST–ICPSR | 101,115 | 12,135 | 135 | 133,095,431 | 121,338,000 | $902.426739 |
| BGE K3 | FR–ELSST | 73,915 | 8,871 | 84 | 82,963,753 | 88,698,000 | $644.150369 |
| BGE K3 | FR–ICPSR | 66,289 | 7,956 | 68 | 65,439,014 | 79,546,800 | $567.979471 |
| BGE K5 | CRS policy–FR | 12,979 | 1,560 | 18 | 16,294,787 | 15,576,000 | $114.986935 |
| BGE K5 | CRS subjects–FR | 21,745 | 2,610 | 21 | 19,773,833 | 26,094,000 | $184.482815 |
| BGE K5 | CRS subjects–policy | 10,040 | 1,206 | 15 | 13,459,957 | 12,048,000 | $89.869446 |
| BGE K5 | ELSST–ICPSR | 120,741 | 14,490 | 161 | 157,658,016 | 144,889,200 | $1,076.207456 |
| BGE K5 | FR–ELSST | 88,329 | 10,602 | 101 | 98,741,952 | 105,996,000 | $769.338453 |
| BGE K5 | FR–ICPSR | 80,485 | 9,660 | 81 | 79,259,225 | 96,582,000 | $689.404161 |
| BGE K10 | CRS policy–FR | 16,794 | 2,016 | 23 | 21,084,385 | 20,152,800 | $148.776073 |
| BGE K10 | CRS subjects–FR | 30,062 | 3,609 | 29 | 27,271,704 | 36,074,400 | $254.972925 |
| BGE K10 | CRS subjects–policy | 13,317 | 1,599 | 20 | 17,854,723 | 15,980,400 | $119.203978 |
| BGE K10 | ELSST–ICPSR | 172,048 | 20,646 | 224 | 222,043,516 | 206,457,600 | $1,530.698780 |
| BGE K10 | FR–ELSST | 125,463 | 15,057 | 142 | 139,399,217 | 150,555,600 | $1,091.836336 |
| BGE K10 | FR–ICPSR | 116,876 | 14,028 | 116 | 114,724,620 | 140,256,000 | $1,000.743448 |
| BGE K15 | CRS policy–FR | 19,581 | 2,352 | 27 | 24,601,644 | 23,497,200 | $173.485537 |
| BGE K15 | CRS subjects–FR | 38,722 | 4,647 | 36 | 35,074,357 | 46,466,400 | $328.365314 |
| BGE K15 | CRS subjects–policy | 15,636 | 1,878 | 23 | 20,976,319 | 18,763,200 | $139.975391 |
| BGE K15 | ELSST–ICPSR | 224,586 | 26,952 | 292 | 287,978,068 | 269,503,200 | $1,996.099205 |
| BGE K15 | FR–ELSST | 163,523 | 19,623 | 184 | 181,218,391 | 196,227,600 | $1,422.544393 |
| BGE K15 | FR–ICPSR | 154,281 | 18,516 | 152 | 151,074,061 | 185,137,200 | $1,320.584187 |
| BGE K20 | CRS policy–FR | 21,456 | 2,577 | 29 | 26,970,385 | 25,747,200 | $190.111898 |
| BGE K20 | CRS subjects–FR | 47,316 | 5,679 | 45 | 42,820,673 | 56,779,200 | $401.201741 |
| BGE K20 | CRS subjects–policy | 17,219 | 2,067 | 24 | 23,120,621 | 20,662,800 | $154.168978 |
| BGE K20 | ELSST–ICPSR | 277,606 | 33,315 | 358 | 354,361,533 | 333,127,200 | $2,465.600418 |
| BGE K20 | FR–ELSST | 201,737 | 24,210 | 226 | 223,234,747 | 242,084,400 | $1,754.620795 |
| BGE K20 | FR–ICPSR | 191,532 | 22,986 | 190 | 187,249,847 | 229,838,400 | $1,639.111987 |
| BGE K25 | CRS policy–FR | 22,309 | 2,679 | 30 | 28,060,111 | 26,770,800 | $197.688904 |
| BGE K25 | CRS subjects–FR | 56,019 | 6,723 | 53 | 50,664,487 | 67,222,800 | $474.961165 |
| BGE K25 | CRS subjects–policy | 17,904 | 2,151 | 26 | 24,061,833 | 21,486,000 | $160.332771 |
| BGE K25 | ELSST–ICPSR | 330,670 | 39,681 | 424 | 420,781,333 | 396,804,000 | $2,935.470948 |
| BGE K25 | FR–ELSST | 240,026 | 28,806 | 268 | 265,444,532 | 288,036,000 | $2,087.499179 |
| BGE K25 | FR–ICPSR | 228,912 | 27,471 | 226 | 223,644,850 | 274,694,400 | $1,958.844665 |
| BGE K50 | CRS policy–FR | 22,560 | 2,709 | 30 | 28,385,897 | 27,072,000 | $199.924048 |
| BGE K50 | CRS subjects–FR | 98,318 | 11,799 | 92 | 88,825,645 | 117,981,600 | $833.493707 |
| BGE K50 | CRS subjects–policy | 18,080 | 2,172 | 27 | 24,307,397 | 21,696,000 | $161.911086 |
| BGE K50 | ELSST–ICPSR | 598,728 | 71,850 | 760 | 754,970,853 | 718,476,000 | $5,307.634915 |
| BGE K50 | FR–ELSST | 429,213 | 51,507 | 479 | 474,956,390 | 515,055,600 | $3,733.113752 |
| BGE K50 | FR–ICPSR | 411,420 | 49,371 | 405 | 401,588,097 | 493,704,000 | $3,520.205481 |

### Cost/yield interpretation

The blind audit makes K15 an empirical knee worth carrying into the proposal:
the K11–15 sample contained 6/18 potential relations, while K16–20 contained
2/18. Moving from K10 to K15 adds 141,769 candidates and $1,234.822487; moving
from K15 to K20 adds 140,537 candidates and $1,223.761790. K25 remains the
explicit high-recall option because two rank-22 potential relations appeared
in the audit; it adds 138,974 candidates and $1,209.981815 over K20.

These are proposal choices rather than production selections. The evidence
supports presenting K15 as the balanced semantic depth, K25 as the broader
high-recall depth, and the lean floor as the lowest-cost empirically complete
regression floor.

The sealed ranks-26-through-50 blind audit found potential relations through
ranks 46–50, so K50 is also decision-relevant rather than a merely mechanical
ceiling. It adds 682,479 candidates and $5,941.485357 over K25. Under a
two-judge design without the paid scorer, K50's conservative ceiling is
$8,292.561141.

### Reproducibility

The initial full run and an independent replay from the compact lean-pair
receipt produced the same normalized receipt digest:
`sha256:7a7292c2b0168133060eb8b80d1ca147d03b5a6b5c09f590e9365418d21e067f`.
All 144 option/pair/work-family request-line digests matched. Focused tests
compare the streaming planner with `qualification_batch.request_plan_summary`
for scoring, judging, normal groups, and a forced byte-limit split: 2 passed;
Ruff and format checks pass.

The bounded K50-only pass and its independent replay both produced
`sha256:ea7f1c45a7f359dc0cd5cfb580e5852aae2f248b3141ce2c2d4cdb00fd45feaf`.
Their normalized receipts and all 18 K50 pair/work-family request-line digests
matched.

- Tool: `tools/plan_atlas_candidate_batch_costs.py`, SHA-256
  `aa0ea66a87b59b9e2b73cd68ce11fe6977438c734c0cabd021d3a41a7db91cc7`.
- Tests: `tests/test_plan_atlas_candidate_batch_costs.py`, SHA-256
  `b7499ce6a9f856baba03fa72935cf75e2bddd1982ce376dfb5bd435d9b4fb4b3`.
- Replay receipt:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-candidate-option-grouped-batch-costs-english-repeat.json`,
  file SHA-256
  `8cfabf33019f8f6779e72cde850f0661917de9732ef9d0b7376c3557f6a98bec`.
- Lean pair-code receipt:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-lean-lexical-k3-sparse-k1-pairs.u64`,
  file SHA-256
  `d24c3ca15766f80d09a370cc34b32d879d9fdf39baaa5e5e0240a4141e06ec79`.
- K50 replay receipt:
  `/tmp/refspec-candidate-benchmark.ANhNrc/atlas-candidate-option-k50-grouped-batch-costs-english-repeat.json`,
  file SHA-256
  `168aaae262510c99575394a768a57f0196096977f340ba62c9ef8ff215ae518b`.

No candidate catalog, qualification job manifest, spend authority, release
manifest, release bundle, or provider state changed.

## Experiment log — fixed-decision BGE tail yield and cutoff coverage (Codex)

Recorded: 2026-08-05. Status: bounded read-only join complete. This experiment
made no provider call, changed no reviewer decision, and changed no
qualification or production artifact. It measures potential-relation yield in
deterministic, relation-blind strata; it does not establish mapping ground
truth or estimate whole-population precision.

### Chain of custody

The 60-decision record remained byte-for-byte at raw SHA-256
`4490ddfde032ddbce4d8612a6dfa981066505ea8f3e7967036c60b918252cd6f`.
The analyzer found exactly one supported verdict for each ordered row 1–60 and
produced decision digest
`sha256:645a1d97039dccb6aff2fcc35aae29e6cf3a2966fada38a075c500ddda1e7840`.
The decision record pins and the analyzer reopened:

- the blind sample at raw SHA-256
  `40ccb74a5b16893e06b9deb13946a69996e820020789e77cfdb424fab902651a`
  and internal ordered-row digest
  `sha256:9961c0796940c4eb0d4bdf920763543a8418df02c09363a26e5a09ce632073cd`;
- the context-only rendering at raw SHA-256
  `c64a3cf47c5285d6081cd71e7f3fa480b7ee300a70b336f975378520c8a80543`;
- the earlier ranks-1-through-25 joined analysis at raw SHA-256
  `bcf3fe57c3abedc4610dafa78623db6f51f397487cb37b9aa80c7f41998bbb76`
  and analysis digest
  `sha256:adb67ddcfbb7223fa7c759421c556bd615023b7673900a94c41600ceb4db3c2a`.

It reproduced the sample digest, every pair-selection digest, all 30 declared
strata, two rows per stratum, ten rows per pair, BGE-retained membership, the
outside-lean-floor boundary, all five views on both concepts, and the
rendering's 60-row order before joining. No verdict, gold relation, or mapping
answer appeared in the sample. The joined-row digest is
`sha256:e551434e3fcd398c4a3c95cdfadd0cfc8f1b9f3a85b05720d8446e99000c41f0`.

### Exact tail yield

Every verdict except `unrelated` or `insufficient_evidence` counts as a
potential relation worth blind judging. The reviewer found 12/60 (20%): 11
`related`, one `target_is_narrower`, and 48 `unrelated`.

| Atlas pair | Potential relations | Tail sample yield |
| --- | ---: | ---: |
| CRS policy areas ↔ Federal Register | 0/10 | 0% |
| CRS subjects ↔ Federal Register | 1/10 | 10% |
| CRS subjects ↔ CRS policy areas | 0/10 | 0% |
| ELSST ↔ ICPSR | 5/10 | 50% |
| Federal Register ↔ ELSST | 4/10 | 40% |
| Federal Register ↔ ICPSR | 2/10 | 20% |

The two cases with a 32-concept side cannot have a minimum bidirectional BGE
rank above 32. Their topology-aware strata produced no potential relation in
20 reviewed rows. The four larger cases retained the requested five-rank
bands, and every band contained at least one potential relation.

| Actual rank stratum | Cases represented | Potential relations | Sample yield |
| --- | ---: | ---: | ---: |
| Rank 26 | 2 adapted cases | 0/4 | 0% |
| Ranks 27–28 | 2 adapted cases | 0/4 | 0% |
| Rank 29 | 2 adapted cases | 0/4 | 0% |
| Rank 30 | 2 adapted cases | 0/4 | 0% |
| Ranks 31–32 | 2 adapted cases | 0/4 | 0% |
| Ranks 26–30 | 4 standard cases | 3/8 | 37.5% |
| Ranks 31–35 | 4 standard cases | 3/8 | 37.5% |
| Ranks 36–40 | 4 standard cases | 3/8 | 37.5% |
| Ranks 41–45 | 4 standard cases | 1/8 | 12.5% |
| Ranks 46–50 | 4 standard cases | 2/8 | 25% |

The potential tail rows occur at actual ranks 29, 30, 30, 31, 31, 35, 37,
39, 39, 42, 46, and 50. The rank-50 row is the sole directional tail verdict:
`STATE AID` has the narrower target `small business tax credit`.

### Cumulative cutoff coverage

Three denominators remain explicit:

1. **Tail only** is the 12 potential relations in these 60 rows above K25.
2. **BGE-unique reviewed** is 48 potential relations in 143 reviewed rows that
   are outside the lean lexical-K3 plus sparse-K1 floor. This is the most
   relevant manual cutoff comparison for the add-only BGE arm.
3. **All reviewed** is 65 potential relations across the earlier 120 rows and
   this 60-row tail, including rows already present in the lean floor.

| Cutoff | Tail potential covered | BGE-unique reviewed potential covered | All reviewed potential covered |
| --- | ---: | ---: | ---: |
| K25 | 0/12 (0%) | 36/48 (75%) | 53/65 (81.54%) |
| K30 | 3/12 (25%) | 39/48 (81.25%) | 56/65 (86.15%) |
| K35 | 6/12 (50%) | 42/48 (87.5%) | 59/65 (90.77%) |
| K40 | 9/12 (75%) | 45/48 (93.75%) | 62/65 (95.38%) |
| K45 | 10/12 (83.33%) | 46/48 (95.83%) | 63/65 (96.92%) |
| K50 | 12/12 (100%) | 48/48 (100%) | 65/65 (100%) |

These are exact counts within balanced deterministic strata, not
population-weighted precision or a claim about unsampled rows. They establish
that K25 is an explicit cost boundary rather than a semantic ceiling. K40
retains 45/48 BGE-unique potential relations observed across both audits; K50
adds three observed possibilities beyond K40, including one hierarchy
relation. The proposal can therefore present K40 and K50 as measured
recall choices, calculate their exact candidate and batch costs, and pair them
with a deterministic outside-cutoff audit.

### Reproducibility

The reproducible analyzer is
`tools/analyze_atlas_candidate_tail_manual_audit.py`, SHA-256
`2e8cd3fefc49a52322604295234955805bac558996aac1b14b43bc7e624fe0bc`;
its focused tests are
`tests/test_analyze_atlas_candidate_tail_manual_audit.py`, SHA-256
`f9548c0636f43b3715d505260ab7f2557f9040b1b8d622a74095fdf379c7d295`.
The combined base-and-tail focused suite reports 7 passed, and Ruff plus
format checks pass.

The full joined report is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-candidate-tail-manual-audit-analysis.json`,
file SHA-256
`8b0b78ebaf27516a3f9d43b54c1ebe1df5f7be89253d22294f4da67ab8aaee25`
and deterministic analysis digest
`sha256:bab5c8474029776b0168a54f9086a2ab11e499765688e6eed94e7e4004880488`.
An independent repeat is byte-identical at the same file SHA-256.

## Experiment synthesis — direct/nonredundant re-review (Codex)

Recorded: 2026-08-05. Status: synthesis of the completed candidate-discovery
work; the final ledger state appears after the parallel experiment logs below.
This synthesis changes no earlier manual verdict, mapping assertion,
qualification artifact, provider job, or release file.

### Refined graph objective

The finder should cover plausible **direct** cross-vocabulary mappings, not
every pair with a thematic connection. The graph itself can supply broader
navigation. For example, `teacher -> school -> education` is preferable to an
extra generic `teacher relatedMatch education` shortcut. This refinement keeps
the high-recall finder and the blind judges separate while giving both stages a
clear target:

- the finder retains plausible direct exact, close, hierarchy, and
  indispensable associative candidates;
- the judges decide semantic support and relation direction without seeing
  retrieval metadata;
- a typed path check supplies separate redundancy evidence after the blind
  semantic decision; and
- generic thematic and path-redundant rows remain evidence but do not become
  graph edges.

A missing short path does not prove that a pair deserves a direct edge. A weak
close or associative path also does not erase a stronger direct exact or
hierarchical mapping. Directness and redundancy are separate decisions.

### Fixed re-review result

The 65 rows previously marked as possible relations under the broad rubric
were re-reviewed against the direct, useful, nonredundant rule:

| Population | Direct candidate | Generic thematic | Redundant through typed path |
| --- | ---: | ---: | ---: |
| Ranks 1–25 earlier positives | 11 | 41 | 1 |
| Ranks 26–50 earlier positives | 1 | 11 | 0 |
| **Combined** | **12** | **52** | **1** |

The 12 direct candidates occur at pre-access-term BGE ranks 1, 1, 1, 1, 1, 1,
2, 3, 5, 6, 8, and 50. Eleven occur by K8. The only retained tail candidate is
`STATE AID` -> `small business tax credit` at exact rank 50, with the target
plausibly narrower. It remains a candidate for blind judgment, not an asserted
mapping.

The one path-redundant row is Federal Register `Water resources` -> ELSST
`NATURAL RESOURCES`. The current graph already supplies:

```text
Federal Register Water resources
  -- baseline skos:closeMatch -->
ELSST WATER RESOURCES
  -- native skos:broader -->
ELSST NATURAL RESOURCES
```

The remaining 52 rows are generic thematic associations. Their original broad
verdicts remain sealed as evidence of what the old rubric measured; the strict
disposition governs the proposal.

The fixed re-review is
`research/vocabulary-atlas-direct-nonredundant-candidate-rereview-2026-08-05.md`,
raw SHA-256
`44e12e50e1102eca6e9867ec062a7360129c386d33d8e84bc8ec935e69d2f4fd`.
A read-only join against both sealed analysis reports reproduced 11 + 1 direct
candidates, 41 + 11 generic thematic rows, the single row-94 path disposition,
and the exact rank sequence above.

This is a fixed expert review of deterministic stratified samples. It is not
objective truth, population precision, or a direct-relation recall estimate.
It adds the graph-minimality evidence that the earlier broad rubric lacked.

### Final candidate proposal

The experiment supports this bounded architecture for the next implementation
stage:

1. Keep exactly 3,280 preferred ICPSR descriptors as mapping endpoints. Fold
   478 verified access terms onto 387 preferred endpoints through the native
   `use` graph; preserve the two exceptional records explicitly and fail
   closed.
2. Use the corrected deterministic floor: lexical K3 plus fielded sparse and
   mutual-anchor graph K1, 214,271 pairs, 582/582 historical mappings, pair-set
   digest
   `sha256:dd1390495706da7115f59915f496ac9e766eb928c9edf1d3d60702c9680475fd`.
3. Use plain symmetric five-view `BAAI/bge-small-en-v1.5` through K50 as the
   proposed add-only dense configuration. Because access-term projection
   changes ICPSR text, regenerate its vectors, ranks, exact union, and cost
   receipt on the corrected corpus before integration. The old K50 receipt is
   comparison evidence, not final snapshot authority.
4. Preserve every generating signal and rank. No arm or reranker may delete a
   row found by another arm before judgment.
5. Send every selected semantic row to two blind model families in deterministic
   groups of at most 25 through provider Batch endpoints. Remove the paid
   full-pool scorer and use retrieval evidence only for queue order.
6. Adjudicate only when both blind judges support a direct relation but disagree
   on compatible type or direction. Apply the governed path check to every
   supported result before admission; treat it as evidence rather than an
   automatic veto on a stronger direct mapping.

The K50 choice is a proposed measured configuration, not a semantic-saturation
claim. The pre-projection direct sample contains one needed row at rank 50. The
outside-K50 sentinel contains one tentative broad association in 60 fixed rows.
On final graph-minimal review, `Critical infrastructure` with `MANUFACTURING
INDUSTRIES` depends on the intermediate idea of critical manufacturing, so the
proposal keeps it as a borderline generic-thematic control rather than a
required edge or cutoff miss. The corrected-corpus reproduction is the
acceptance point that confirms K50 or supplies evidence for a revision.

### Experiment inventory preserved

The proposal reconciles every completed family rather than retaining only the
winning configuration:

- existing label-oriented production rules;
- Levenshtein, RapidFuzz variants, Jaro/Jaro-Winkler, compact-string, alias,
  identifier, acronym, and character controls;
- fielded word/character sparse retrieval and anchor-gated graph expansion;
- five BGE text structures plus prompt, prefix, and context variants;
- MiniLM, Arctic, Jina, Nomic, Google, and OpenAI embedding comparisons;
- MiniLM and ColBERT reranking;
- MiniCOIL, OpenSearch sparse encoding, and SPLADE resource experiments;
- OAEI Conference, corrected Anatomy, BeyondEquivalence, and Open English
  WordNet tests;
- exact cross-arm Pareto search and exact-memory/approximation checks;
- the 120-row real-label review, 60-row K26–K50 review, 60-row outside-K50
  sentinel, 65-row typed path audit, and 65-row strict re-review;
- the 108-row historical two-judge audit; and
- exact 25-row Batch packing and cost planning.

No local judgment-model experiment completed. A partial local model download
was stopped on user direction before any inference and contributes no evidence.
No further provider or local-model experiment is part of this synthesis.

### Boundary before production integration

The final proposal intentionally leaves these implementation gates for
approval:

1. regenerate corrected-corpus BGE ranks and the exact K50 union;
2. promote selected `/tmp` receipts into durable content-addressed evidence;
3. implement the versioned retrieval snapshot, preferred-endpoint projection,
   no-scorer judgment policy, and directness/path disposition;
4. run the separately authorized 25-row protocol-acceptance pilot;
5. recompute exact catalogs, requests, shards, controls, conditional
   adjudication, recovery reserve, and all-in spend ceiling; and
6. request a separate decision before any full Batch campaign or public release
   uses the new mappings.

The 12,313-row catalogs, $112 planning authority, 582 baseline assertions, 69
controls, and all earlier evidence remain interpretable. No production job was
run during candidate experimentation.

## Experiment log — ICPSR preferred-endpoint access-term projection (Codex)

Recorded: 2026-08-05. Status: experiment complete; production integration
remains intentionally unchanged. This run used the English Atlas corpus, made
no provider or local-model call, and changed no qualification code, candidate
catalog, or admitted mapping.

### Decision and source check

The managed ICPSR release contains exactly 3,760 unique term-URI members:
3,280 with `officialLabelRole=preferred` and 480 with
`officialLabelRole=alternate`. The current Atlas endpoint axes already contain
exactly the same 3,280 preferred term URIs, but their concept records contain no
alternate labels. The release manifest and concept artifact were verified at
raw SHA-256
`f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a`
and
`b5cfb10139086cf0eee2dd95dba94f1d310ec496f3a8b38e17068e8cb308132c`,
respectively.

The experiment treats identity and access as separate concerns. Each
alternate member is a source-published access term. Its directed `use` path is
followed only when every alternate node has one URI-verified outgoing target,
the path has no cycle, every node belongs to the release, and the path ends at
a preferred member. The preferred sink remains the sole mapping endpoint, and
each originating access-term label becomes retrieval text on that endpoint.
A missing path, branch, cycle, target-label mismatch, out-of-release target, or
normalized alias assigned to two endpoints is excluded. This graph-reachability
rule preserves source evidence while preventing access terms from becoming
false mapping identities.

The verified graph has:

- 478 alternate members reaching preferred endpoints: 477 in one hop and one
  in two hops;
- 478 access labels attached to 387 preferred endpoints;
- zero normalized aliases assigned to more than one endpoint; and
- two alternates excluded by the fail-closed rule because they have no valid
  `use` path: `slaves` (term 32422) and `sexual preference` (term 32502).

The one two-hop path is `illegal aliens` -> `illegal immigrants` ->
`undocumented immigrants`. The resulting endpoint axis remains exactly 3,280
members and byte-identical in order and identity to the present Atlas codec.
The projection digest is
`sha256:3502d60574f051f9842383eb587d4a9de4016130bf7f8b7e90f820648da02e56`;
the projected corpus digest is
`sha256:0fca193b64aef157958f529dbb914b4962f3cedd01b84bdecbd813a4f2a7e1a5`.

### Exact lexical and sparse result

The existing English Atlas benchmark was rerun across all seven lexical arms
and the three sparse views at depths 1, 2, 3, 5, and 10. The minimum complete
frontier remains lexical K3 plus sparse/mutual-graph K1:

| Measure | Existing floor | Access-term projection | Change |
| --- | ---: | ---: | ---: |
| Candidate pairs | 210,197 | 214,271 | +4,074 (+1.94%) |
| Known relations found | 582/582 | 582/582 | unchanged |
| Exact set additions | — | 7,617 | — |
| Exact set removals | — | 3,543 | — |
| Added or removed known relations | — | 0 / 0 | — |

Only the two cases with ICPSR endpoints change. ELSST-ICPSR moves from 77,400
to 80,303 pairs (+5,400/-2,497, net +2,903), and Federal Register-ICPSR moves
from 47,951 to 49,122 (+2,217/-1,046, net +1,171). The other four cases are
exactly unchanged.

At the corrected K3/K1 point, lexical retrieval contributes 195,245 pairs and
561/582 known relations; sparse/mutual-graph retrieval contributes 35,184 and
524/582. Their 16,158-pair overlap leaves 179,087 lexical-only and 19,026
sparse-only pairs. The union retains every typed relation: 121 exact, 232
close, 75 broad, 119 narrow, and 35 related. Its pair-set digest is
`sha256:dd1390495706da7115f59915f496ac9e766eb928c9edf1d3d60702c9680475fd`.

Alias enrichment changes top-K ranks rather than simply appending pairs. At a
fixed depth, 7,617 pairs enter and 3,543 leave; lexical K3 alone moves from
567 to 561 known relations, while sparse K1 moves from 523 to 524. The combined
families remain complete. Production acceptance should therefore compare exact
pair sets and union recall, not assume that adding retrieval text makes each
individual top-K set monotonic.

### Scope and reproducibility

No fresh BGE embedding or reranking run was made. The retained BGE rank bytes
belong to the prior concept-text digest and cannot be reused as evidence for
this projected corpus; a later model experiment must regenerate vectors and
ranks from the projection. No LLM judge or provider endpoint was called.

The experiment tool is
`tools/benchmark_icpsr_endpoint_alias_projection.py`, SHA-256
`0a72715b56766dbf0628dd50a7da4574882d386788ee8dc5333b692ee3b88d65`.
Its focused tests are `tests/test_icpsr_endpoint_alias_projection.py`, SHA-256
`19e8497d9d623fcb068aba06c6a5399718942c1ef06439aa7fdb27e90e3dc9ce`;
all three pass, including multi-hop folding, fail-closed ambiguity and cycle
handling, endpoint filtering, and hierarchy-context alias injection. Ruff
format and lint checks pass.

The result is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-icpsr-preferred-endpoint-alias-frontier-english.json`,
raw SHA-256
`2cc642460e650108f134f1867547200ea024743b9a5582e71787118a2c514ae3`,
with deterministic result digest
`sha256:a7954369a45217e3d2f63d4200f7a141e04363fb95589d7eab6d5933f873e864`.
The baseline compact pair receipt was verified at raw SHA-256
`d24c3ca15766f80d09a370cc34b32d879d9fdf39baaa5e5e0240a4141e06ec79`.

## Experiment log — typed path evidence for the 65 earlier potential rows (Codex)

Recorded: 2026-08-05. Status: bounded read-only graph analysis complete. This
experiment made no provider or local-model call, changed no manual verdict, and
changed no qualification or production artifact. It reopens the canonical
six-release Atlas containing 32,684 native relation claims and the 582 admitted
baseline mappings, then asks whether a short, semantically usable path already
connects each of the 65 rows marked as a potential relation in the earlier
ranks-1-through-25 and ranks-26-through-50 audits.

### Path policy

The analyzer searches to four edges and preserves predicate direction. Exact
matches and source-declared thesaurus aliases are neutral steps. It accepts a
consistently broader-only or narrower-only hierarchy, a single close match with
neutral steps, one close match that attenuates an otherwise consistent
hierarchy, or a single associative step with neutral steps. An associative path
is inspection-only because `relatedMatch` grants no default traversal.

The analyzer deliberately rejects arbitrary undirected connectivity, mixed
broader/narrower chains, two close matches, two associative edges, and mixtures
of associative and hierarchy edges. Those graph walks may show that two terms
share a large connected component; they do not preserve a relation that can
support a directness decision.

### Exact result

One of the 65 reviewed potential rows has a qualifying path of at most four
edges. The other 64 do not:

| Review population | Earlier potential rows | Typed path found | No typed path |
| --- | ---: | ---: | ---: |
| Ranks 1–25 | 53 | 1 | 52 |
| Ranks 26–50 | 12 | 0 | 12 |
| **Combined** | **65** | **1** | **64** |

The one path is ranks-1-through-25 row 94, whose earlier verdict was
`target_is_broader`:

```text
Water resources (Federal Register)
  -- skos:closeMatch, admitted baseline mapping -->
WATER RESOURCES (ELSST)
  -- skos:broader, native -->
NATURAL RESOURCES (ELSST)
```

This two-edge, close-attenuated broader path has the same relation direction as
the earlier verdict. It is directness evidence for the re-review: the proposed
Federal Register `Water resources` → ELSST `NATURAL RESOURCES` edge may repeat
navigation already supplied by one admitted cross-vocabulary mapping and one
publisher-native hierarchy edge.

All 55 earlier `related` rows lack a qualifying typed path under this policy.
So do the other three `target_is_broader` rows and all six
`target_is_narrower` rows. This does not make those 64 rows direct mappings.
Generic thematic associations can remain noise even when no typed path exists;
the result isolates path redundancy from the separate human directness review.

### Chain of custody and limits

The analyzer reopened canonical Atlas generation digest
`sha256:2c98b2c89eabe27388da2b67ce9c0f6121266a0a0993d1f4ac99456665a4cc55`,
Atlas file SHA-256
`3f223d720938ee0fa74e35efd9be58dc68e602d78e9b196410152609f82d3d83`,
9,010 concepts, all 32,684 native relation claims, and exactly 582 mapping
assertions. It also reopens the two sample and decision-file digests recorded by
the earlier audits. Every output row retains the audit name, original row,
selection digest, unchanged verdict, endpoint identities and labels, and either
the shortest path with predicates and intermediate labels or an explicit
no-path result.

A path is evidence, not automatic proof that a direct assertion is redundant.
In particular, the accepted close-plus-hierarchy composition is a cautious,
attenuated search path rather than a formal SKOS entailment. The four-edge
bound measures short usable navigation; it does not establish that longer paths
do or do not exist. The graph is the current 582-baseline Atlas and therefore
cannot measure paths that would emerge only after new mappings are admitted.

### Reproducibility

The analyzer is `tools/analyze_atlas_candidate_path_evidence.py`, SHA-256
`da7069d024506a2e6bd923691f4d4bf578c1b1bc293451ba2562e5d3f64e4578`;
its focused tests are
`tests/test_analyze_atlas_candidate_path_evidence.py`, SHA-256
`59bf874a2fe621452dca05319d438adf875c040678a1aba1ddcbeb0b392e8dc6`.
The path, base-audit, tail-audit, and residual-audit focused suite reports 16
passed. Ruff and format checks pass.

The complete row report is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-candidate-path-evidence-65.json`,
file SHA-256
`faf57dd27df4b0a10aa292dbd1ebb4aeb5872c56fdbdbc5e459159bdb9edee92`,
analysis digest
`sha256:1025f71316ed086832fe46ab6e62bd9fb138dfffb6003109d02e8a07d5fb2a0f`,
and row digest
`sha256:11af99fb9bed0d9f392b63ba51ffd0572631acc14f225717072bc7e659f1ad3b`.
An independent repeat is byte-identical at the same file SHA-256.

## Experiment log — fixed-decision outside-BGE-K50 residual sentinel (Codex)

Recorded: 2026-08-05. Status: bounded read-only join complete. This experiment
made no provider or local-model call, preserved every fixed decision, and
changed no candidate catalog, qualification job, spend authority, or production
artifact.

### Chain of custody and final decision rule

The final 60-decision record remained byte-for-byte at raw SHA-256
`844ce6ee42cbac8073ce1ac405b608317db01962e44822bee8ef0277b0873e26`.
The analyzer found exactly one allowed verdict for every ordered row 1–60 and
produced decision digest
`sha256:7921d8d7985ca53bc556bcc2534d7f39d685973982bd8bb65027e78165c05538`.
It reopened and verified:

- the blind residual sample at raw SHA-256
  `6286e56044f2fdb1a1a82430291f5bc2c34996c9852042c2bb312591d03ce5b6`
  and ordered-row digest
  `sha256:70ad88877e7a01f3ac78a6958b053f5db69b29dd3197d2a48812f59002f4eda2`;
- the population evidence digest
  `sha256:e4adb7510edc7c8c838cb5dacea598abeeb39d44059ee019884ebbb20f730222`;
- the context-only rendering at raw SHA-256
  `153bb22fb2402ad192ab6c414a182e2dc46717a052614eba5e42f8f0533a90e4`;
  and
- the lean pair codes, retained BGE ranks, and rank manifest at their embedded
  source-artifact digests.

The decision record was refined before this join to apply the requested
directness and nonredundancy test. A candidate belongs in this audit when it is
a plausible direct cross-vocabulary mapping. A thematic association that is
already expressed more precisely through native or qualified graph paths does
not require a direct `relatedMatch`. Under that rule, six initially plausible
thematic associations were fixed as `unrelated`; only row 33 remained
`related`. The analyzer reread this final record, and no earlier seven-row
interpretation enters the report.

The sample builder and analyzer kept selection and judgment separate. The
fixed SHA-256 rule selected 15 rows from each nonempty residual case without a
relation answer. The human rendering supplied balanced source and target facts
and all five BGE view texts while withholding selection digests, ranks,
retrieval metadata, known mappings, and verdicts.

### Exact residual observation

The final review found 1/60 potential direct relation (1.67%): one `related`
and 59 `unrelated`. The observed row is `Critical infrastructure` ↔
`MANUFACTURING INDUSTRIES` in the Federal Register–ELSST pair. It is a useful
direct public-policy association because critical manufacturing is an
infrastructure sector; the displayed concepts do not support strict hierarchy
in either direction.

This paragraph preserves the fixed residual review. The final graph-minimal
proposal applies the later elegance clarification: the relation depends on the
intermediate idea of `critical manufacturing`, so the row becomes a borderline
generic-thematic control rather than a required edge or cutoff miss. The
original `related` verdict and digest remain historical evidence; they do not
govern admission.

| Atlas pair | Exact residual population | Fixed review | Observed sample yield |
| --- | ---: | ---: | ---: |
| CRS subjects ↔ Federal Register | 300,007 | 0/15 | 0% |
| ELSST ↔ ICPSR | 10,782,872 | 0/15 | 0% |
| Federal Register ↔ ELSST | 2,017,137 | 1/15 | 6.67% |
| Federal Register ↔ ICPSR | 1,900,980 | 0/15 | 0% |
| **Four nonempty residual cases** | **15,000,996** | **1/60** | **1.67% unweighted** |

The other two cases have no outside-K50 residual population. Minimum
bidirectional BGE rank covers their full Cartesian spaces because one side has
32 concepts:

| Fully covered Atlas pair | Cartesian pairs | BGE K50 pairs | Outside both |
| --- | ---: | ---: | ---: |
| CRS policy areas ↔ Federal Register | 22,560 | 22,560 | 0 |
| CRS subjects ↔ CRS policy areas | 18,080 | 18,080 | 0 |

Across all six pairs, the Cartesian space contains 16,579,315 rows. The lean
floor plus BGE K50 contains 1,578,319 rows (9.52%), and the four residual
populations contain 15,000,996 rows (90.48%). Under the fixed residual rubric,
the observation flags one potential relation outside the declared K50 union.
The final graph-minimal synthesis keeps that row as a borderline thematic
control, so it does not become a required cutoff miss. K50 remains a
reproducible bounded retrieval choice rather than a semantic-saturation claim.

### Interpretation limits

The exact 1/60 count describes this sealed sentinel. It is not a population
prevalence estimate:

- equal allocation gives every nonempty pair 15 rows even though their
  residual population shares are 2.00%, 71.88%, 13.45%, and 12.67%; the raw
  sample yield is therefore not population weighted;
- 15 rows represent between one in 20,000 and one in 718,858 residual pairs,
  so a zero observation in three cases does not establish absence;
- all residual rows use the retained sentinel beyond K50. They carry no deeper
  rank, so this audit cannot choose K60, K100, or another extension; and
- the verdicts are human judgments of potential direct mappings under the
  stated rubric. They are neither admitted assertions nor objective ground
  truth and do not establish K50 recall or a missed-relation total.

The earlier ranks-1-through-50 audits used a broader associative rubric. Their
53/120 and 12/60 counts should not be numerically combined with this fixed 1/60
result unless the same directness and nonredundancy rule is applied to every
row. The residual result supports K50 as the widest measured and costed
boundary while preserving a borderline thematic control beyond it. It cannot
support a claim that K50 captures every conceivable association.

### Reproducibility

The analyzer is `tools/analyze_atlas_residual_manual_audit.py`, SHA-256
`676b37f4ca7a960500c1ece37e01dd507f5333432b5e8e3939136498ee361756`;
its focused tests are `tests/test_analyze_atlas_residual_manual_audit.py`,
SHA-256
`dedb6eae674313b9b975bad17a0354e2709e672ec1b9f21098d8127b7c3993aa`.
The combined base, tail, and residual audit suite reports 12 passed. Ruff,
format checks, and compilation pass.

The full joined report is
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-outside-bge-k50-residual-manual-audit-analysis.json`,
file SHA-256
`4d99a383c650037ebfb2622a2ed9ab79a81914b53a6550bf05c68586f90cbca0`
and deterministic analysis digest
`sha256:3a66d012e7896b925f0860ee5d3e284511c5f0685598fe58cf791bf6969ce2c6`.
Its joined-row digest is
`sha256:0d314adda79f590811af23903920db9d798c0f6e6e7e5e98e044b5008f3b56e1`.
An independent repeat is byte-identical at the same file SHA-256.

## Final ledger state — experiment freeze and handoff (Codex)

Recorded: 2026-08-05. The ICPSR projection, typed-path analysis, and residual
join immediately above were completed in parallel before this freeze. The
experiment phase is complete, and
`research/vocabulary-atlas-relation-candidate-and-judgment-proposal-2026-08-05.md`
is ready for review before production integration.

The final policy interpretation is:

- retain plausible direct, useful, nonredundant mappings rather than every
  thematic association;
- use the corrected 214,271-row deterministic K3/K1 floor and 3,280 preferred
  ICPSR endpoints enriched by 478 verified access terms reaching 387 preferred
  descriptors;
- use plain symmetric five-view BGE K50 as the proposed dense configuration,
  with corrected-corpus vectors, ranks, exact union, and cost receipt required
  before integration;
- preserve the strict 65-row result of 12 direct candidates, 52 generic
  thematic rows, and one path-redundant row;
- treat the fixed residual row `Critical infrastructure` ↔ `MANUFACTURING
  INDUSTRIES` as a borderline generic-thematic control in the final proposal,
  while preserving its earlier sealed `related` verdict as historical evidence;
- run a typed-path disposition for every supported mapping, using the path as
  evidence rather than an automatic veto on stronger direct semantics; and
- use two blind judge families in deterministic groups of at most 25, no
  full-pool paid scorer, and targeted adjudication only for supported
  type/direction conflicts.

Final local verification reports 65 passed experiment tests in an isolated
environment containing the optional RapidFuzz dependency. All 32 untracked
experimental Python files pass Ruff lint and formatting checks and Python
compilation. The strict directness table was independently joined to its two
sealed analysis reports and reproduced the exact 12/52/1 counts and ranks.

No paid scorer or LLM judge ran. No candidate catalog, qualification policy,
mapping assertion, spend authority, provider campaign, or release artifact
changed. The bounded $0.046897820 Google/OpenAI embedding comparison and one
OpenAI embedding Batch smoke row remain the only provider work in this
experiment. A partial local judgment-model download was stopped before
inference and contributes no evidence.

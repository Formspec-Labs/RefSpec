# Atlas Vocabulary Pack

`refspec.atlas.vocabulary_pack_build` compiles either a digest-pinned Atlas 3.1
`parquet-view` (`view-manifest.json`, directly without an intermediate
`parquet-search-view`) or a legacy compact `parquet-search-view`
(`search-view-manifest.json`) into a single, immutable, read-only SQLite
artifact (`AtlasVocabularyPack`, schema `v3`, backward-compatible with `v2`)
that serves interactive concept lookup, exact concept resolution,
provenance-preserving graph navigation, agency succession/projection queries,
offline semantic similarity, and zero-ML text concept extraction without a
separate vocabulary server or vendor-specific database DDL ([REF-078](decisions.md)).

## Dependency-Injection Architecture

All serving seams live in
[`refspec.atlas.vocabulary_protocols`](../src/refspec/atlas/vocabulary_protocols.py)
(Python stdlib only — zero runtime dependencies):

| Protocol / Policy | Responsibility | Default Implementation |
| --- | --- | --- |
| `VocabularyProvider` | Consumer read contract (`lookup`, `resolve`, `related`, `similar`, `extract_concepts`, sync & async, `requires_sql_executor = False`) | `AtlasVocabularyPack` |
| `AgencyHistoryProvider` | Optional agency lifecycle/succession contract (`agency_change_events`, `agency_projections`, sync & async) | `AtlasVocabularyPack` |
| `GraphExpander` | Bounded, cycle-safe `k`-hop closure (`expand_sync` / `expand`, including `include_symmetric_inverse`) for hierarchy precomputation & graph navigation | `AtlasVocabularyPack` |
| `SemanticIndex` | Optional Tier-1 dense vector retriever (`search_rids(..., allowed_rids=..., rerank_top_r=...)`, `O(1)` `vector_for_rid`, `recommended_min_cosine`) bound by `pack_id`, `pack_sha256`, & `source_manifest_digest` | `AtlasSemanticSidecar` (`flat_f16` `<=50k`, `binary_i8` auto `>50k`, or `ivf_i8`) + `PriorGuidedSemanticIndex` |
| `QueryEncoder` | Optional caller-supplied text-to-vector encoder (`model_id`, `dimensions`) | Caller-injected (or `None` for pure Tier-0) |
| `RankFusionPolicy` | Combines exact, lexical, and dense candidate lists | `ExactPinnedRRF` (exact matches pinned strictly in order above RRF) |
| `CandidateReranker` | Optional post-hydration reranker over rich concept cards (receives `corrected_query or query`) | `AuthorityReranker` (neutral structural priors by default; opt-in `REGULATORY_BENCHMARK_SCHEME_PRESET`) or external cross-encoder |
| `LookupPolicy` | Controls grouping, disambiguation context (`include_context`), spelling recovery, abstention floors (`min_cosine: float \| None = None`, honoring `SemanticIndex.recommended_min_cosine` when `None`, else `DEFAULT_MIN_COSINE = 0.55`), `nprobe`, label cap | `LookupPolicy()` |
| `RelationPolicy` | Controls opt-in `REF-035` mappings, symmetric inverse reads, and derived edges | `RelationPolicy()` |

Serving a compiled Tier-0 pack imports **only Python stdlib `sqlite3`** (zero
`numpy`, `duckdb`, `pyarrow`, or `rdflib`). Optional `.vpack` vector sidecar
support (`AtlasSemanticSidecar`) is packaged behind the optional
`refspec[vectors]` extra (`numpy`), and `refspec.atlas` lazy-loads vector
symbols via PEP 562 `__getattr__`. `duckdb` and `pyarrow` are imported lazily
only during offline compilation (`refspec.atlas.vocabulary_pack_build`).
Platform-specific accelerators plug in purely via structural DI protocols
without adding OS-specific dependencies to RefSpec.

## Build Once, Seal, Serve Everywhere

```python
from pathlib import Path
from refspec.atlas import (
    AtlasSemanticSidecar,
    AtlasVocabularyPack,
    AuthorityReranker,
    ExactPinnedRRF,
    LookupPolicy,
    RelationPolicy,
    build_semantic_sidecar,
    build_vocabulary_pack,
)

# Accepts either a verified parquet-view (view-manifest.json) or legacy parquet-search-view
manifest = build_vocabulary_pack(
    Path("output/parquet-view"),
    Path("output/vocab-op1.sqlite"),
    trusted_manifest_digest="sha256:...",
    schemes=(
        "urn:ref:atlas-resource-scheme:eurovoc",
        "urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025",
    ),
    languages=("en",),
    include_mappings=True,
    include_derived=True,
)

# Optional Tier-1 semantic sidecar (flat_f16 <=50k, binary_i8 auto >50k, or ivf_i8; requires refspec[vectors])
vmanifest = build_semantic_sidecar(
    manifest.pack_path,
    Path("output/atlas-bge-m3-fp16-2026-11-14"),
    Path("output/vocab-op1.vpack"),
    model_id="BAAI/bge-m3",
)

# Open read-only with DI wiring (pass verify_pack_digest=False on pre-verified workers for <2 ms open)
sidecar = AtlasSemanticSidecar.open(
    vmanifest.sidecar_path,
    trusted_sidecar_digest=vmanifest.sidecar_sha256,
)
pack = AtlasVocabularyPack.open(
    manifest.pack_path,
    trusted_pack_digest=manifest.pack_sha256,
    trusted_manifest_digest=manifest.source_manifest_digest,
    semantic_index=sidecar,
    query_encoder=my_query_encoder,       # optional QueryEncoder
    rank_fusion=ExactPinnedRRF(k=60.0),
    candidate_reranker=AuthorityReranker(),
    lookup_policy=LookupPolicy(include_context=True),
    relation_policy=RelationPolicy(include_mappings=True, include_derived=True),
)

# Transparent lookup with spelling correction metadata & disambiguation breadcrumbs
resp = pack.lookup_with_meta_sync("medciare", limit=5)

# Offline concept-to-concept similarity (uses stored .vpack vectors; zero query encoder needed!)
sim = pack.similar_sync(resp["concepts"][0], limit=5, exclude_same_scheme=True)

# Zero-ML verbatim concept extraction from document text (<1 ms)
# Uses neutral default structural tie-breaking (pass scheme_weights=REGULATORY_BENCHMARK_SCHEME_PRESET to opt in).
mentions = pack.extract_concepts_sync(
    "Medicare and Flood insurance protect against cybercrime.",
    max_unigram_doc_freq=250,
)
```

### CLI

```bash
refspec-build-vocabulary-pack build \
  --view-root output/parquet-view \
  --manifest-digest sha256:... \
  --output output/vocab-op1.sqlite \
  --scheme urn:ref:atlas-resource-scheme:eurovoc \
  --scheme urn:ref:atlas-resource-scheme:federal-register-thesaurus-2025

refspec-build-vocabulary-pack build-vectors \
  --pack output/vocab-op1.sqlite \
  --embeddings-dir output/atlas-bge-m3-fp16-2026-11-14 \
  --output output/vocab-op1.vpack \
  --mode auto \
  --recommended-min-cosine 0.62

refspec-build-vocabulary-pack verify --pack output/vocab-op1.sqlite --sidecar output/vocab-op1.vpack
refspec-build-vocabulary-pack query --pack output/vocab-op1.sqlite --text "medciare" --context --authority-rerank
refspec-build-vocabulary-pack extract \
  --pack output/vocab-op1.sqlite \
  --text "Medicare and cybercrime" \
  --max-unigram-doc-freq 250 \
  --scheme-preset none
```

(`extract` accepts `--max-unigram-doc-freq 0` to disable the unigram DF cap, `--max-unigram-df` as a shorthand alias, and `--scheme-preset {none,regulatory-benchmark}`.)

## Retrieval, Provenance, Sealing & Release Profiles

- **Schema `v3` & Fast-Open Neutral Priors (`REF-078`):** `v3` packs store
  precomputed neutral `structural_prior_f32` and `sid_by_rid_u16` blobs in
  `pack_meta_blobs` plus `resources.has_preferred` (eliminating duplicate
  alternate-only `pref_text` indexing) and optional `agency_change_events` /
  `agency_projections` tables when `lifecycle-events.parquet` or
  `agency-projection.parquet` are present in the verified view.
  `build_vocabulary_pack(..., include_agency_tables=None)` defaults to `True`
  when `schemes is None` or any selected resource belongs to the `entity` ring,
  and `False` for strictly non-entity subject-only subsets (callers may pass
  `include_agency_tables=True` or `False` explicitly).
  `DEFAULT_CURATED_SCHEME_WEIGHTS` is empty/neutral by default; curated
  regulatory weights are opt-in via `REGULATORY_BENCHMARK_SCHEME_PRESET` and
  `PriorGuidedSemanticIndex.from_pack(...)` (`<2 ms` open, strict `pack_id` +
  `source_manifest_digest` verification).
- **Pre-Filtered Semantic Search & Tiered Lookup:** Shared Unicode
  normalization (`NFKC` + casefold + `NFKD` diacritic strip) guarantees
  index/query symmetry. `AtlasVocabularyPack` pushes cached `bytes` 0/1
  `allowed_rids` masks directly into `SemanticIndex.search_rids` (preventing
  `<1%` scheme-filter starvation) and verifies scheme membership in `O(1)` RAM.
  Tier 0 exact label (`label_exact`, preferred strictly ahead of alternate;
  short-circuits FTS5 when exact matches fill `fetch_limit`) → Tier 1 two-step
  exact-token `AND` BM25 (`pref=10`, `alt=5`, `def=1`) with wildcard `*` prefix
  fallback only when slots remain → Tier 2 stopword- and wildcard-free soft
  `OR` with deduplicated minimum token coverage → Tier 3 gated
  Damerau-Levenshtein spelling recovery over distinct dictionary terms
  (`vocab_terms_trigram`, `len >= 6`, `Dice >= 0.55`, frequency-gated to
  recover real typos while abstaining on nonsense/cross-lingual inputs; pinned
  in `exact_rids` for pure lexical queries, and fused via RRF `lexical_rids`
  when dense hits are present so foreign false friends never hard-override
  semantic matches). Any injected `CandidateReranker` receives
  `corrected_query or query`.
- **Build Hygiene & Thread Safety:** Offline builds reject symlinks prior to
  `.resolve()`, validate only member roles required by the build flags, drop
  unlabeled resources and reflexive self-loops, pre-populate deterministic
  sorted `predicates` / `derivation_rules` IDs, quarantine both
  `skos:broader` and `skos:narrower` cycles via iterative Tarjan's SCC, and
  compress `urn:ref:atlas-derived:` prefixes. Serving uses a bounded
  checkout/return read-only connection pool (`max_idle=16`, zero FD/mmap leak
  across ephemeral request threads, race-free `close()`), chunks SQLite `IN`
  binds at `<=400` parameters, and hardens `extract_concepts_sync`
  (punctuation-boundary guard, uppercase acronym check for `<=4`-char acronyms,
  default stopword / document-frequency guard).
- **Disambiguation & Canonical Identity (`REF-025`):** Retains verbatim
  `Label.id` (compressed losslessly via `uri_prefixes`), caps hydration
  deterministically at `label_limit` (default 32) with `labelsTruncated` and
  `totalLabelCount`, and optionally attaches `notations`, `broaderLabels`,
  `matchReason`, and `correctedQuery`.
- **Cross-Scheme, Derived & Offline Semantic Edges (`REF-035`, `REF-042`–`REF-049`):**
  Default `related()` returns forward `NativeRelationAssertion` edges strictly
  between selected-language-labeled concepts. Enabling `include_mappings=True`
  serves `REF-035` evidence-computed `MappingAssertion` crosswalks with
  bidirectional symmetric traversal (`direction: "inverse"`, `assertedSource`,
  `assertedTarget`). Enabling `include_derived=True` adds `derived-relations`
  (`asserted: false`, `derivationRule`). `similar_sync()` exposes offline vector
  neighbors strictly separated with `asserted: false` and `semanticSimilarity`.
- **Sealing (`refspec-distribution-seal-3`) & Two-Layer Release Profiles:**
  `refspec.seal.create_seal(..., vocabulary_pack=..., semantic_sidecar=...)`
  cryptographically binds `vocabularyPackSha256` and optional
  `semanticSidecarSha256` with bi-directional `source_manifest_digest`
  verification and optional anti-rollback guards while remaining backward-compatible
  with `refspec-distribution-seal-2`. Note that `refspec-distribution-seal-3`
  requires packs compiled directly from a sealed `parquet-view`
  (`view-manifest.json`), not a legacy `parquet-search-view`, because sealing
  verifies `pack_meta.source_manifest_digest` against the distribution manifest
  and sealed `parquet-view` manifest digests. `tools/generate_atlas_v3_full.py`
  supports declarative two-layer profiles (`portfolio/atlas-release-profiles.json`):
  `--profile core-regulatory`, `--profile bibliographic-crosswalk`, and
  `--profile full`.
- **Error Classes:** Caller input and unknown-concept faults raise
  `VocabularyInputError(ValueError)` (HTTP 400); pack corruption, digest
  mismatch, sidecar/encoder mismatch, or missing FTS5 raise
  `VocabularyPackError(RuntimeError)` (HTTP 503).

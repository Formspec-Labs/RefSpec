# RuleSpec and DocSpec — code trace

**Agent brief:** determine what RuleSpec and DocSpec actually do by tracing code.
**Ignore every `.md` file.** Read-only. Answer, specifically: are the case-variant
paths one repo or two; does anything resolve unmarked prose citations; what does
DocSpec's `tools/test_refspec_atlas.py` read.

**Scope:** `/Users/mikewolfd/Work/rulespec` (~91 source files),
`/Users/mikewolfd/Work/DocSpec` (~353 source files).

**Date:** 2026-08-08 · **Status:** verbatim agent output

> Section numbering follows the order of the original brief's questions, which the
> agent answered out of order. The agent flags one self-correction inline (§8) and
> one unresolved tool-output anomaly (§9).

---

I traced both repos by code, ignoring all `.md` files except where I checked them
against code. One correction is flagged inline: I earlier called DocSpec
cross-repo-isolated, and that was wrong.

## 4. Case-sensitivity: same repo, both times

Both pairs share inodes — **one repo each**, on a case-insensitive filesystem:

- `rulespec` and `RuleSpec` → inode `257555276`
- `DocSpec` and `docspec` → inode `280359625`

Remotes: `Formspec-Labs/rulespec` (152 commits) and `Formspec-Labs/DocSpec` (5
commits). For context, `spicy-regs` is a **different GitHub org** —
`civictechdc/spicy-regs` (633 commits) — while `RefSpec` is `Formspec-Labs/RefSpec`
(277 commits) and is a genuine git submodule of spicy-regs (`.gitmodules`).
`/Users/mikewolfd/Work/RefSpec` does not exist; the only checkout is
`spicy-regs/RefSpec`.

## 1. What each repo does

**RuleSpec** is a schema-compilation and conformance-testing system for a
policy-assertion vocabulary (RKAF). `tools/constraints_compile.py` (~3,800 lines)
parses 60 `.cue` files in `constraints/` and emits six coordinated targets — JSON
Schema, Rust, TypeScript, SHACL, Rego, CUE — driven by `tools/compile_all.sh`. The
Rust workspace consumes the generated types and holds the only real runtime logic:
`crates/rkaf-runtime/src/reducer.rs:11-19` defines a 7-level total-order eligibility
lattice (`notEligible < searchOnly < reviewQueueOnly < draftGenerationAllowed <
localOperationalUse < publicationAllowed < officialUse`), and
`reduce_for_scope_traced:243-324` runs a numbered pipeline over it — applicability
gate, lifecycle-stale floor with point-in-time exceptions, local-adoption broadening,
attestation-freshness narrowing, consumer capability cap. `bridge.rs` adds 10 numbered
accept/reject rules; `graph.rs` builds an `@id`/`@type` index with inverse-edge
traversal; `cascade.rs` does backward transitive closure over SKOS mapping edges.
`runtime.rs:15-51` is explicitly stateless — one JSON-LD `BehaviorTestCase` in,
dispatch to one of five contract modules, diff against the fixture's declared expected
output. Nothing persists.

**DocSpec** is a working, fully deterministic bulk document acquisition and
segmentation platform, built ports-and-adapters. `docspec run start` composes a run
(re-deriving every profile pin from `profiles/` and aborting if the plan disagrees —
`src/docspec/cli.py:751-758`), plans stores against a source catalog through a SQLite
spill workspace, seals an `ExecutionHandoff` with a `task_set_digest`, executes
per-store (fetch → media-type-dispatched extraction → segmentation → one statistics
processor), delivers JSONL record layers, reconciles into a `RunReceipt`, and commits a
`DocumentRelease` via content-addressed storage. Segmentation is four deterministic
segmenters in `src/docspec/processing/segmentation.py`: paragraph
(`ParagraphSegmenter:84`, id `docspec.paragraph/v1`, splitting on the single regex
`_PARAGRAPH_GAP:31` = `(?:\r?\n)[ \t]*(?:\r?\n)`), PDF page (`:116`), JSON record
(`:150`), whole image (`:184`). Every segment carries exact UTF-8 byte offsets plus an
`EvidenceCoordinate` with a `sourceDigest`, and each segmenter's `policy_digest` is
baked into segment identity — change the algorithm and every downstream ID changes.

## 2. Executable versus declared

**Both run.** Neither is scaffolding.

**RuleSpec:** `cargo test --manifest-path crates/Cargo.toml --workspace` → **157
passed, 0 failed, 0 ignored**. Prebuilt binaries already sit in `crates/target/debug/`
(`rkaf-validate`, `rkaf-behavior-validate`, `projector-harness`), which is independent
evidence it was built before. Census: 79 Rust source files, 34 Python tools, 60 CUE
constraints, 522 fixtures (511 JSON-LD; 128 positive, 300 negative) — against 76
markdown files (13 in `spec/`, 24 in `thoughts/`). Of 34 tools, 10 are tests; of the 22
real tools, **13 are audits/validators and 9 are producers**, and every producer emits
schemas, fixtures, digests, or copies — never extracted content. Three CLIs exist but
only `projector-harness` has subcommands; the other two take positional paths and write
to stdout.

One hollow test: `crates/rkaf-validate/tests/fixture_validation.rs:118-129` computes
`let _ = result;` and asserts nothing. This is disclosed at `:5-6` (negatives are
enforced Python-side by `tools/validate_negatives.py`), but on the Rust side it is a
no-op.

**DocSpec:** the "353 source files" figure is misleading. Exact decomposition:
`67 live src + 34 tests + 4 tools + 248 archive = 353`. **70% is quarantined dead
code**, and the quarantine is test-enforced — `tests/test_package_boundary.py:110`
fails if production imports archive, `:134` verifies the archive manifest, `:217`
asserts the built wheel contains no `archive` path component. Live surface is 105
files / 22,916 LOC. `pytest -q` → **264 passed, 1 deselected in 32.9s** (the
deselection is the only `@pytest.mark.integration` test,
`tests/test_dagster_adapter.py:509`). That reproduces the sealed gate receipt at
`verification/gate-receipt.json` (`verdict: "passed"`, 264/0/0, 730 evidence files
digested, 6/6 required gates). `ownership/modules.json` self-reports 64/67
implemented, 3 partial, **no stubs**, and all 16 ports have at least one adapter.

DocSpec has really run: `output/qualification/fr-mirrulations-10k-v1/` is 7.4 GB of
content-addressed data over 10,000 documents / 13,592 files — 6,408 Federal Register
XML and 3,592 Mirrulations (regulations.gov) JSON+HTML from the public `mirrulations`
S3 bucket. Smoke (100 docs) and intermediate (1,000 docs) completed end-to-end
including release commit. **The full 10k tier did not finish**: 431 planned stores, 244
delivery receipts (~57%), no run receipt, never reconciled, never committed.

## 3. Identity: mint or carry through?

**RuleSpec: both, explicitly.** It mints `urn:rkaf:*` for its own fixtures and
**carries through** RefSpec's.
`release-records/fixtures/m2-extrapolation-release-positive.json` pins
`vocabulary_atlas_asset: {asset_id: "urn:ref:vocabulary-atlas:9069a26d…",
manifest_digest: "sha256:956cab4f…", distribution_digest: "sha256:8e1eaf22…"}` — a
RefSpec-minted identity verified by digest at read time (`tools/rulespec_release.py:2151`,
`tools/extrapolation_release_v2.py:2334`). RefSpec is the vocabulary authority; a scan
of its `src/` shows it minting `urn:ref:*` broadly (179 `urn:ref:type`, plus
`atlas-release`, `source-concept`, `relation`, `registry`).

**DocSpec: both, and never randomly.** There is **zero** use of `uuid`, `random`,
`secrets`, or `token_hex` in `src/docspec/`. Three mechanisms:

- **Carried through:** `sourceItemId` enters verbatim from the publisher — real values
  `urn:docspec:qualification:federal-register:05-1806` and
  `urn:docspec:qualification:mirrulations:SEC-2020-0001-0001`, wrapping the upstream FR
  document number and regulations.gov ID. Built by campaign tooling
  (`tools/fr_mirrulations_support.py:573,725`), not the library.
- **Content-addressed:** blob keys are *observed*, not chosen.
  `src/docspec/adapters/storage.py:347-395` streams bytes through `hashlib.sha256` and
  the resulting digest becomes the path `objects/sha256/{hex[:2]}/{hex}`;
  catalog-declared digests are only *checked* (`:381-384`).
- **Minted deterministically:** every DocSpec-issued ID is `stable_urn(kind, value)` =
  `urn:docspec:{kind}:v1:{sha256(canonical_json(value))}`
  (`src/docspec/domain/identity.py:184-191`), 86 call sites, floats forbidden
  (`:64-66`). These are **self-verifying** — `__post_init__` recomputes the URN and
  raises on mismatch (`domain/plans.py:135`, `domain/release.py:64`,
  `domain/receipts.py:347`). You cannot forge one.

So DocSpec is **infrastructure, not an authority**: it adds no semantic judgment. There
is no tagging, classification, taxonomy, or labelling anywhere — grepping
`tag|classif|taxonom|ontolog|label` in `src/docspec/` returns only `label=`
error-message kwargs. Its single processor, `ContentStatisticsProcessor`
(`processing/processors.py:26`), emits byte/codepoint/line/word counts and its own
docstring says it works "without assigning document meaning". No LLM, no HTTP client —
"openai" appears exactly once, as a secret-redaction regex in `domain/security.py:14`.
No server, API, or MCP endpoint in the live tree.

## 5. The unmarked-prose-citation answer

**Neither RuleSpec nor DocSpec resolves them, because neither reads document text at
all.**

**RuleSpec has no extractor.** Five independent proofs:

1. `crates/Cargo.toml:22-33` — no HTML/XML/PDF parser; **it does not even depend on
   `regex`**.
2. No `bs4`, `lxml`, `pypdf`, `nltk`, `spacy`, or `tokenizers` in `tools/`.
3. Zero network calls anywhere — no `requests`, `urllib`, `httpx`, `reqwest`.
4. A repo-wide search for `*.html`/`*.xml`/`*.pdf`/`*.txt` returns **exactly one file:
   `requirements.txt`**. Not one byte of statute or CFR text is on disk.
5. All 15 `fs::read` sites in Rust are immediately followed by `serde_json::from_slice`
   or `serde_yaml`.

The repo says so itself, in code, at `tools/build_rulespec_release_fixtures.py:180-188`:
"Production Rulespec therefore has **no segment producer** […] There is **no policy, no
tokenizer, no window, and no size budget**." A test
(`test_rulespec_releases.py::FixtureOnlySegmentationTests`) enforces it.

Its evidence vocabulary is rich and **entirely inert**.
`crates/rkaf-core/src/generated/source_fragment.rs:113-132` defines
`TextPositionSelector` with `oa:start: i64`, `oa:end: i64`, `rkaf:coordinateSystem`;
`:86-105` defines `TextQuoteSelector` with `oa:exact`/`oa:prefix`/`oa:suffix`;
`:140-180` defines `SourceFragment` with `rkaf:sourceArtifactDigest`. **No code produces
or dereferences any of it** — every reference outside `src/generated/` is schema-shape
validation. `Assertion` has *no* span field; offsets sit two hops away via
`SourceClaimant.rkaf:attributedInFragment`. `extraction_activity.rs:31-77` records
`rkaf:extractionMethod`, `rkaf:extractorVersion`, `rkaf:inputDigest` — a provenance
receipt **for an extractor that lives elsewhere**. The `ai-extraction/` fixture
directory holds three files, all tiny negative schema tests; one in full:
`{"@id": "urn:rkaf:fixture:cswm-neg:c1", "@type": "rkaf:ConfidenceRecord", "rkaf:score": 0.92}`.

**DocSpec** segments but never interprets — no citation parsing of any kind in
`src/docspec/`.

**Answering the question properly requires looking one repo over, and the answer is a
deliberate, documented refusal.**

- `spicy-regs/src/spicy_regs/ontology/citations.py:724`
  `find_act_relative_citations(text, *, act_names)` **does** resolve unmarked prose
  citations — but only the *act-relative* subclass. It finds a `sec. 111` token, then
  requires a **known** OLRC popular name (13,627 in production) immediately adjacent.
  Its docstring: "**The index is the grammar** […] An act this index does not name is
  not read. The corpus writes 'INA sec. 103(a)(1)' […] and inferring which acts those
  abbreviate is precisely the guess the identity fence exists to stop." The shape-based
  alternative was *measured* and rejected — matching "capitalized words ending in Act"
  hit "U.S.C." 108 times across 4,777 sealed authority strings.
- `spicysearch/src/spicysearch/identifiers.py:186-190` states the same rule for the
  other spelling: a bare "section 553" without an "of title" tail "**stays undetected
  rather than guessed**." And this runs over *query* text (`query_planner.py:283`,
  `engine.py:808`), not documents.

**On USC Title 26 specifically, neither side of the framing is touched.**
`spicy-regs/src/spicy_regs/sources/uscode_uslm.py:205-207` parses only `<section>`
identifiers and `<sourceCredit>` elements — it never reads `<ref>` cross-reference
elements and never reads section body prose. So the 539 marked-up operative
cross-references are **not consumed**, and the 16,400 unmarked prose mentions are **not
attempted**. Both figures appear in **no code in any of the four repos**; they are
claims made elsewhere.

What *has* been measured is adjacent, not the same thing:
`spicy-regs/output/citation-bakeoff-2026-08-02/` holds a real executed bakeoff over
**4,777 Federal Register authority strings** against CiteURL, with 620 LLM-adjudicated
disagreements ($0.24 spend). Four-cell: `both 4157, citeurl_only 108, current_only 233,
neither 279`; false positives `citeurl 0, current_text_grammars 1`. Its own
`verdict.json` scope line: `"detection evaluation only; nothing here retires a regex or
changes identity"`. That is citation *detection in a structured metadata field*, not
resolution of cross-references in statute body text.

The one place documents genuinely become RuleSpec objects is
`spicy-regs/src/spicy_regs/docpipeline/rkaf_projection.py` — it emits
`rkaf:ConceptAssignment` (`:1686`) bound via `rkaf:bindsSourceFragment` with
`rkaf:evidenceRole: "rkaf:textualEvidence"` (`:1589,1707`),
`oa:start`/`oa:end`/`rkaf:coordinateSystem` at `:1421-1423`, and verifies every offset
by re-slicing the stored text and SHA-256-comparing the region against the digest in
the fragment URN. Its LLM layer (`docpipeline/adapters/{anthropic,openai,codex_cli}.py`)
"supplies judgments only"; unverifiable values go to `extraction/tag-rejections.parquet`,
"never repaired."

## 6. `tools/test_refspec_atlas.py` — the premise is wrong

**That file does not exist in DocSpec. It is in RuleSpec.** DocSpec's live `tools/`
contains exactly three files: `fr_mirrulations_qualification.py`,
`fr_mirrulations_support.py`, `predecessor_code_fingerprints.py`. A case-insensitive
grep for `refspec` or `atlas` across DocSpec's `src/` and `tools/` returns **0 files**.
Every such hit is inside dead `archive/legacy-2026-08-05/`. **DocSpec does not read
Atlas in any way.**

RuleSpec's `tools/test_refspec_atlas.py` (265 lines) is a **hermetic unit test with no
repo file reads**: it builds synthetic atlases into `tempfile.TemporaryDirectory()` via
a local `_write_atlas` helper (`:102`, `:189-192`) and asserts fail-closed behaviour —
`test_reads_exact_reference_release_membership:194`,
`test_rejects_distribution_tampering:236`,
`test_analysis_membership_must_match_authoritative_release_facts:243`,
`test_recomputes_generation_identity_from_exact_inputs:251`. It exercises
`tools/refspec_atlas.py`, which is the real reader:
`RefSpecVocabularyAtlas.open(directory, expected_manifest_digest, expected_output_digest)`
(`:333-365`) validates a RefSpec manifest plus an immutable two-graph N-Quads
distribution, format `refspec-vocabulary-atlas-nquads-1.0` (`:28`), namespace
`https://refspec.org/ns/vocabulary-atlas/v1#` (`:29`), raising `AtlasIntegrityError` on
any mismatch.

That reader is **not test-only** — it is imported by three production tools:
`rulespec_release.py:2151`, `extrapolation_release_v2.py:2334`, and
`build_rulespec_release_fixtures.py:83,803`.

## 7. Duplication found

**(a) DocSpec is a fork of spicy-regs.** Its initial commit imported **591 files /
259,613 insertions** on 2026-08-05. `ontology/citations.py` (993 lines) exists in
`spicy-regs/src/spicy_regs/` and `DocSpec/archive/legacy-2026-08-05/src/docspec/` and
differs by **exactly 2 lines**, both `spicy_regs`→`docspec` renames in docstrings.
`tools/run_citation_bakeoff.py` (1,207 lines) likewise (36 bytes apart). Of 40 sampled
archive files, 26 have same-named spicy-regs counterparts; a broader hash sweep found 13
still byte-identical. **Mitigated:** DocSpec's copy is quarantined dead code.

**(b) Three incompatible evidence-coordinate vocabularies, differing on the *unit*, not
just the name.**

| Repo | Shape | Value | Unit |
|---|---|---|---|
| RuleSpec `source_fragment.rs:50-69` | closed Rust enum, 1 field | `rkaf:utf8-byte`, `rkaf:unicode-codepoint` | either |
| DocSpec `domain/content.py:384-390` | free-form `str`, 1 field | `"utf8-byte-range"` | UTF-8 bytes |
| spicy-regs `docpipeline/source.py:132-133` | 2 fields, strictly validated at `:423-426` | `"unicode-codepoints"` + `"half-open"` | codepoints |

DocSpec has emitted **8,232,356** records carrying
`"coordinateSystem":"utf8-byte-range"` — a string absent from RuleSpec's closed enum, so
RuleSpec's validator would reject every one. And because DocSpec counts bytes while
spicy-regs counts codepoints, the same span in non-ASCII text yields different integers.
Only `spicy-regs/docpipeline/rkaf_projection.py:202` speaks RuleSpec's vocabulary
correctly (`_COORDINATE_SYSTEM = "rkaf:unicode-codepoint"`).

**(c) Three citation parsers.** `spicy-regs/src/spicy_regs/ontology/citations.py` (993
L, live); its near-identical twin in DocSpec's archive (dead); and
`spicysearch/src/spicysearch/identifiers.py` (602 L), a *deliberate* re-implementation
whose comments cite the original by name (`:138` "citations.py `_CFR_STANDARD`", `:170`
"citations.py `_USC_STANDARD`"). Notably **spicysearch fixed two bugs that remain live in
spicy-regs' copy** — `identifiers.py:141` ("Without them `040 CFR 060` matches at offset
1 and reports `40 CFR 60`") and `:146-149` ("A greedy `[A-Za-z0-9.-]*` read
`49 CFR 900.42.` as section `900.42.`"). spicy-regs lacks the `_LEFT`/`_RIGHT` boundary
guards. Their RIN grammars also accept different sets: `citations.py:398` requires a
digits-only tail (`\d{4}-[A-Z]{2}\d{2}$`), `identifiers.py:89` accepts alphanumeric.

**(d) Two segmenters.** DocSpec's `processing/segmentation.py` (283 L) splits on a
blank-line regex, format-blind, no token budget. spicy-regs' `docpipeline/segments.py`
(1,163 L) over `source.py` (3,593 L) is structure-aware (`legis-body`, `section`,
`part`, `header`), token-budgeted, with backward overlap, an evidence-slice proof
function (`check_segment_slices:1016`), and a frozen baseline of 1,302 segments pinned
by `requires-python = ">=3.12,<3.13"` because `html.parser` changes move boundaries. Not
interchangeable; no shared code. DocSpec's archive contains spicy-regs' version, so
DocSpec **replaced** rather than reused it.

**(e) Four independent readers of `spicyregs-document-release` v3** —
`spicy-regs/src/spicy_regs/document_release_v3.py` (owner),
`spicysearch/src/spicysearch/document_release_v3.py` ("does not import SpicyRegs"),
`rulespec/tools/extrapolation_release_v2.py:1105-1140` ("intentionally a consumer-side
reader"), and DocSpec's dead archive copy. All four independently recompute
`urn:spicyregs:document-release:v3:<canonical_sha256>`.

**(f) Six canonical-JSON implementations** across four repos:
`rulespec/tools/extrapolation_release_v2.py:212` and `rulespec/tools/rulespec_release.py:83`;
`DocSpec/src/docspec/domain/identity.py:91` and `DocSpec/tools/predecessor_code_fingerprints.py:37`;
`RefSpec/src/refspec/binding.py:302`; `spicysearch/src/spicysearch/canonical.py:213` and
`artifact_protocol.py:153`. RuleSpec also pins the real thing (`rfc8785==0.1.4`), giving
it three.

**(g) 69 byte-identical file hashes span repo boundaries** (41 rulespec+spicysearch, 19
three-way, 9 spicy-regs+spicysearch). Example triple, all sha256 `06adfaf4d3ee…`:
`rulespec/release-records/fixtures/rulespec-core-release-m2.json`,
`spicy-regs/src/spicy_regs/fixtures/rulespec-core-release-v1.json`,
`spicysearch/fixtures/releases/rulespec-core-release.json`. spicysearch documents this in
`fixtures/releases/manifest.json` (`"schema": "urn:spicysearch:copied-release-manifest:1"`,
`copied_from` absolute paths at lines 5, 35, 43, 51). **No `.py` file is byte-identical
across live repo boundaries** — code was re-implemented, not copy-pasted.

## 8. Cross-repo imports and file reads — **including a correction to my earlier claim**

**I earlier said DocSpec had no cross-repo dependency in either direction. That was
wrong.** I grepped DocSpec's `src/` and `tools/` for `refspec|atlas`, correctly got
zero, then over-generalized. DocSpec's coupling is to **spicy-regs**, not RefSpec, and it
is substantial.

| Direction | Mechanism | Evidence |
|---|---|---|
| spicy-regs → RefSpec | **Python import**, uv editable path dep on the submodule | `spicy-regs/pyproject.toml:12` (`refspec==0.1.0.dev0`), `:147` (`[tool.uv.sources] refspec = {path="RefSpec", editable=true}`), `uv.lock:2331`; 25 `from refspec` sites, 8 in production |
| spicy-regs → RefSpec | **File read** into the submodule | `tools/generate_source_profile_artifacts.py:24`, `tools/ablate_candidate_selectors.py:244` |
| RefSpec → RuleSpec | **Vendored + digest-pinned manifest** (no import) | `RefSpec/tools/generate_model.py:25,287` (`RULESPEC_DEPENDENCY_SHA256`) |
| **DocSpec → spicy-regs** | **Hardcoded absolute path + subprocess execution of another repo's code** | `DocSpec/tools/fr_mirrulations_qualification.py:55-58,95-96,148,159,164,168` |
| **DocSpec → spicy-regs** | **Sealed AST fingerprint of the other repo's source tree** | `DocSpec/conformance/predecessor-code-fingerprints-v1.json`, enforced by `tests/test_boundary_code.py` |
| RuleSpec → RefSpec | Vendored digest-pinned conformance corpus | `tools/vendor_refspec_atlas_conformance.py:27` |
| RuleSpec → RefSpec | Release records pin `urn:ref:vocabulary-atlas:…` + digests, read at validation | `tools/rulespec_release.py:2151`, `extrapolation_release_v2.py:2334` |
| spicysearch → spicy-regs / RuleSpec / RefSpec | Copied fixture artifacts; format contracts, re-implemented readers | `spicysearch/fixtures/releases/manifest.json:5,35,43,51` |
| spicy-regs → RuleSpec | Mints into RuleSpec's URN space | `citations.py:362-380` → `urn:rkaf:us:cfr:…`, `urn:rkaf:us:usc:…` |

**No repo imports another's Python package except spicy-regs → RefSpec.** No
`Path(__file__).parents[...]` walk escapes any repo; no `os.environ` repo-root lookups
exist.

**The worst coupling is DocSpec → spicy-regs.** Verbatim from
`DocSpec/tools/fr_mirrulations_qualification.py`:

```
55: DEFAULT_SPICYREGS = Path("/Users/mikewolfd/Work/spicy-regs")
58: BUILDER_RELATIVE = Path("src/spicy_regs/corpora/mirrulations_document_corpus.py")
```

It runs `uv run python -m spicy_regs.corpora.mirrulations_document_corpus draw` with
`cwd=spicyregs`, then calls a **private** function via
`uv run python -c "from spicy_regs.corpora.mirrulations_document_corpus import _draw_documents; …"`.
It seals the result with `git rev-parse HEAD` plus a sha256 of the builder file
(`fr_mirrulations_support.py:908-911,1027`). The default is a hardcoded
developer-machine absolute path, overridable via `--spicyregs`. Separately,
`DocSpec/conformance/predecessor-code-fingerprints-v1.json` pins spicy-regs at
`commitSha f1fcb8c9c8838071e9c45462799db788971baca4` / `treeSha bc87ead2…`, 91 files,
538,561 bytes, with per-file AST-token-window fingerprints — a code-similarity tripwire,
i.e. DocSpec explicitly guarding against re-deriving spicy-regs. **I verified that commit
exists** in spicy-regs (`f1fcb8c`, 2026-07-31).

**Important scoping:** `src/docspec/` itself has **zero** references to spicy-regs — the
library is genuinely clean and stdlib-only (`dependencies = []`). The coupling lives
entirely in `tools/` and `conformance/`.

**The RuleSpec↔RefSpec pin is stale and its drift detector is switched off.** RefSpec's
live 1.0 corpus has **21 cases**; RuleSpec's vendored copy has **7** — missing 15,
including all hierarchy and relation-adjudication cases, plus 4 amendments. Worse,
RefSpec has shipped `bindings/atlas/2.0` and `3.0` and is actively developing v3, while
RuleSpec hard-codes `1.0` at all five call sites (`refspec_atlas.py:28-29`,
`vendor_refspec_atlas_conformance.py:27`, `test_refspec_atlas_cross_repository.py:33,49`)
and **never references v2 or v3**. The test that would catch this,
`test_refspec_atlas_cross_repository.py:23-26`, is `skipUnless(REFSPEC_CHECKOUT)` — and
`REFSPEC_CHECKOUT` is set **nowhere**: not in the Makefile, not in
`.github/workflows/constraints-parity.yml`. CI invokes the module and it silently skips
every time.

## 9. What I could not determine

- **Why DocSpec's full 10k run stopped.** No failure receipt, no partial run receipt, no
  log survives. Interrupted vs OOM vs deliberate halt is unrecoverable from the artifacts.
- **Whether RuleSpec's 1.0 pin is intentional.** Frozen-contract vs plain drift — the
  code carries no statement either way, and I did not read the `.md` files that might
  say.
- **Whether DocSpec is meant to replace spicy-regs' docpipeline or coexist.** Nothing in
  either codebase references the other's future.
- **Whether spicysearch's copied fixtures are stale.** `manifest.json` records
  `copied_from` paths and hashes, but spicysearch has **no `.github/` directory at all**,
  so nothing verifies them.
- **A tool-output anomaly I want flagged rather than smoothed over.** One late `rg`
  invocation returned `DocSpec/tools/fr_mirrulations_qualification.py` with every
  occurrence of `spicy-regs`/`spicy_regs` rendered as `il` (e.g.
  `Path("/Users/mikewolfd/Work/il")`). That contradicts my own earlier verbatim `sed`
  read of lines 53–60 of the same file, which showed `spicy-regs`. I am citing the
  earlier direct read as authoritative and treating the later output as a display
  artifact — but I did not diagnose the cause, so treat the exact bytes of that one file
  as verified-once rather than verified-twice.
- **DocSpec's fingerprint gate coverage.** `tests/test_boundary_code.py` references the
  fingerprint artifact, so it is exercised by the 264-test suite, but I did not confirm
  the gate would actually *fail* on a similarity violation versus merely parsing the
  file.
- I did not attribute RuleSpec's 157 tests to individual binaries, and I did not
  determine what consumes the 128 `.parquet` fixtures beyond `extrapolation_release_v2.py`.
- **Where docs contradict code:** RuleSpec's `README.md:14` says "The rules live in
  PDFs" — it has never opened one and has no dependency capable of it; though
  `README.md:21` is honest ("Not the text of the rule"). DocSpec has **no README at
  all**; its only two live markdown files are a plan and a spec. Both repos' `.md` claims
  I checked were framing overreach rather than factual contradiction.
- One unrelated inconsistency noticed in passing: `spicy-regs/citations.py:392` emits
  `urn:spicy-regs:usc-chapter:` (hyphenated) while the rest of the repo uses
  `urn:spicyregs:` (unhyphenated).

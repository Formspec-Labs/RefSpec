# Atlas English scope and annotation carry

**Branch:** `research/fidelity-langbugs`  
**Worktree:** `codex-fidelity-langbugs`  
**Date:** 2026-08-13  
**Status:** implemented and verified in bounded builds; not merged, published, or released

## Result

This change makes Atlas's English-only product scope explicit and applies one
BCP 47-aware selection rule throughout the production adapters. Atlas now
selects `en` and its language-tag family, including `en-US` and `en-GB`, while
still normalizing selected text to `en` on the Atlas wire.

The same change carries the requested English `skos:definition` and
`skos:scopeNote` content. EuroVoc adds 1,884 quads and the bounded NALT source
adds one. The other six vocabulary audit sources need no new wire claims:
OSTI, ELSST, and GEMET already carry their usable English definition and scope
note text, and the admitted AGROVOC, NASA, and EuroVoc-domain scopes contain no
qualifying standard-SKOS text.

The independent auditor remains red by design. It still treats every publisher
language as required and the auditor-owned `DeclaredClaimExclusion` mechanism
cannot yet exclude selected language-and-predicate claims on otherwise admitted
concepts. This report specifies the fail-closed auditor addition and provides
its exact count payload in
[`REPORT2-language-exclusions.json`](REPORT2-language-exclusions.json).
This makes the owner's measured 97.68% non-English share of audit differences
an explicit, checked product choice instead of leaving it implicit in adapters.

No full Atlas build ran.

## One English-family predicate

[`is_english_language_tag`](src/refspec/vocabulary.py#L234) is now the single
production predicate. It first requires a syntactically valid BCP 47 tag, then
compares the case-folded primary language subtag with `en`. It accepts `en`,
`EN`, `en-US`, `en-GB`, and `en-Latn`; rejects tags such as `fr`, `eng`, and
`en_US`; and accepts an untagged value only when a caller explicitly passes
`untagged_is_english=True` for a source model that defines that behavior.
Untagged text never reaches the Atlas wire.

Exact `language == "en"` checks remain only where exact base English has a
different role from an English variant: base-label precedence, twin collapse,
variant preferred-to-alternate conversion, and normalized-wire validation.
They do not decide whether publisher content belongs to the English family.

### Production call sites

The shared predicate replaced every production English eligibility check in
this work:

| Production area | Call sites now using the predicate | Behavior replaced |
| --- | --- | --- |
| Generic registry claims | `registry_claim_input._compatibility_labels`; `_compatibility_text_values` | Exact-`en` claim filtering; definitions and notes now use the same rule as labels. |
| Vocabulary adapters | `v3_registry_vocabularies._literal_payload`; `_normalize_english_label_candidates`; annotation selection in `_normalize_doe`, `_normalize_elsst`, `_normalize_eurovoc`, `_normalize_gemet`, and `_normalize_nasa` | The adapter-local `_english()` helper and direct exact-tag tests. The helper also gives base `en` deterministic precedence and collapses identical regional-tag twins. |
| Alignment endpoints | `v3_registry_alignments._english_labels`; the LCSH dropped-label count in `load_lcsh_alignment_endpoint_release` | Exact-`en` preferred and variant label selection. |
| Code-list adapter | `v3_registry_codes._bundle_items` | Exact-`en` preferred-label selection. |
| Bounded/nonemitter adapters | `v3_registry_nonemitters._normalized_english_labels`; `_nalt_english_definitions` | Inline `{None, "en"}` label tests and exact-tag filtering. |
| RDF claim extraction | `rdf_claim_export.extract_rdf_claims` | The local `_is_english()` helper. |
| Full generator | `_normalize_english_language_content`; `_audit_english_language_content` | Exact-`en` filtering of explicit tags and language maps. Selected language-map values are combined under wire key `en`. |

Focused tests cover valid family variants, case folding, malformed tags,
non-English tags, explicit untagged handling, regional-label twin collapse,
and regional preferred-label conversion to an alternate when base English is
also present.

### GEMET and LCSH measured effect

GEMET publishes 5,244 `en-US` preferred labels. Of these, 5,000 are byte-identical
to an `en` value and collapse. The remaining 244 differ in spelling. One is a
GEMET group outside the admitted Atlas concept scope, so the product can carry
243 of them: 12 were already present as exact-`en` alternate labels and 231 are
new. The bounded GEMET label count therefore rises from 5,645 to 5,876, and the
scoped auditor reports the expected `+231` Atlas-label delta.

The LCSH EuroVoc-alignment endpoint source adds 86 `en-Latn` labels, taking its
bounded label count from 7,522 to 7,608.

## Explicit build language scope

The normative statement is in
[`bindings/atlas/3.1/README.md`](bindings/atlas/3.1/README.md#L399):

> Atlas carries English-language content; publisher content in other languages
> is deliberately not represented.

The paragraph also states that the build selects the BCP 47 `en` family,
normalizes selected text to wire tag `en`, and forbids untagged and non-English
wire text.

The machine-readable statement lives in `atlas-construction-summary.json`,
because it records how a distribution was built rather than adding an Atlas
ontology term:

```json
"languageScope": {
  "includedLanguageFamilies": ["en"],
  "selectionRule": "bcp47-primary-language-subtag",
  "unselectedPublisherContent": "notRepresented",
  "wireLanguageTag": "en"
}
```

### Schema and identity delta

[`atlas-construction-summary.schema.json`](bindings/atlas/3.1/schemas/atlas-construction-summary.schema.json#L102)
adds a closed, required `languageScope` object with the four exact values above.
The generator writes it, the producer validator checks the exact value, and the
base release and catalog build keys include it. It is therefore sealed,
wire-visible build provenance: changing it changes construction identity. It is
not a new RDF term, vocabulary promise, or source claim.

The fixture corpus adds a negative `construction-language-scope-missing` case.
The fixture reseals dependent digests after removing the field, so it fails on
`json.schema` rather than an earlier digest mismatch. The contract also now
requires `atlas:definition` and `atlas:note` values to be English `rdf:langString`
literals and includes a `non-english-definition` negative fixture.

## English definitions and scope notes

The ontology's existing exact names are `atlas:definition` and `atlas:note`.
No RDF term, compact-record field, Parquet column, or search-view field was
added. `RegistryResource.definition`, `RegistryResource.notes`, the RDF writer,
the full Resource table, and the compact search Resource table already carry
these values.

The generic claim adapter now accepts `definition_predicates` and
`note_predicates`. EuroVoc configures these as `skos:definition` and
`skos:scopeNote` in both its claim-release path and parser-backed fallback. It
sorts qualifying text, puts the first definition in `atlas:definition`, and
puts additional definitions plus scope notes in `atlas:note`. This preserves
the compact format's one-definition field without dropping a publisher value.

NALT represents `skos:definition` as an IRI to a definition node. The adapter
now resolves that exact link only when the target supplies both a non-empty
English-family `rdf:value` and a `dcterms:source`. One bounded relation resolves;
one is textless and remains unresolved. Release metadata records
`englishDefinitionRelationCount: 1` and
`unresolvedDefinitionRelationCount: 1`.

### Per-source qualifying claims

These counts use the auditor's eight vocabulary `SourceSpec` selections. They
count usable English definition and scope-note publisher claims, including
already-carried claims.

| Audit source | English definitions | English scope notes | Result |
| --- | ---: | ---: | --- |
| AGROVOC bounded | 0 | 0 | No wire change. |
| DOE OSTI | 1,638 | 152 | All 1,790 were already carried. |
| ELSST | 903 | 183 | All 1,086 were already carried. |
| EuroVoc 4.24 | 1,557 | 327 | Newly carried as 1,555 definitions and 329 notes; two second definitions become notes. |
| EuroVoc domains | 0 | 0 | No wire change. |
| GEMET | 5,134 | 102 | All 5,236 non-empty claims were already carried; four empty English definitions still emit no empty quad. |
| NALT bounded | 1 resolved | 0 | One new definition; a second IRI-valued relation has no resolvable text. |
| NASA thesaurus | 0 | 0 | No standard-SKOS change; detached proprietary notes remain a separate source-model issue. |
| **Total** | **9,233** | **764** | **9,997 qualifying claims: 8,112 already present and 1,885 newly carried.** |

`skos:historyNote` is out of scope. It is neither `skos:definition` nor
`skos:scopeNote`, and this change adds no history-note mapping. Non-English
history notes belong in the language-scope declaration below; any decision to
carry English history notes is a separate product-role change.

## Measured growth and re-mint radius

The research prototype measured the new lines in isolation as 460,928 canonical
N-Quads bytes and 81,661 bytes when those incremental lines were compressed
separately with Zstandard level 19. The bounded rebuild provides the
authoritative whole-pack deltas:

| Pack | Before quads | After quads | Quad delta | Canonical byte delta | Whole-pack compressed delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| EuroVoc | 856,733 | 858,617 | +1,884 | +460,552 | +212,653 |
| NALT | 177 | 178 | +1 | +347 | +162 |
| **Total** | **856,910** | **858,795** | **+1,885** | **+460,899** | **+212,815** |

The whole-pack compressed delta is intentionally not the 81,661-byte isolated
estimate: sorted packs were recompressed in full, and compressed byte deltas are
not additive.

Definitions and notes enter the Resource node digest. The rebuild adds
annotation quads to 1,735 distinct EuroVoc resources and one NALT resource, so
**1,736 Resource `content_digest` values change** in the Parquet view. Publisher
resource IRIs do not change.

Source-record identity remains stable because this change does not alter native
publisher payloads. EuroVoc has 7,515 source-record links before and after;
NALT has two before and after; the sorted source-record link sets have zero
differences. The source-pack digests, construction keys, release inventory,
manifest/distribution identity, receipts, Parquet members, compact search view,
and seal must be rebuilt.

## Auditor declaration required from the owning line

The proposed literal payload is
[`REPORT2-language-exclusions.json`](REPORT2-language-exclusions.json), SHA-256
`8c7ffd458cef9b182d86b1b3e9626cc0d38d5db6eb0d8ba1ef59e63e024082bb`.
It was measured after applying each auditor `SourceSpec`'s exact publisher
subset. Its count unit is one unique semantic literal claim. It excludes only a
claim with an explicit language tag whose BCP 47 primary language subtag is not
`en`.

### Exact declaration content

The JSON records:

- `schemaVersion: "1.0"` and `exclusionType: "languageFamily"`;
- the same `includedLanguageFamilies` and `selectionRule` as the construction
  summary;
- semantic predicate families and their exact source predicates, including
  SKOS-XL label flattening;
- exact counts keyed by auditor source name, publisher language tag, and
  semantic predicate family; and
- `totalExcludedClaims: 871823`.

The source totals are:

| Auditor source | Explicit non-English claims | Languages |
| --- | ---: | ---: |
| AGROVOC bounded | 40 | 31 |
| DOE OSTI | 0 | 0 |
| ELSST | 192,292 | 14 |
| EuroVoc 4.24 | 445,531 | 29 |
| EuroVoc domains | 546 | 26 |
| GEMET | 233,407 | 35 |
| NALT bounded | 7 | 1 |
| NASA thesaurus | 0 | 0 |
| **Total** | **871,823** | — |

The required families are preferred, alternate, and hidden labels;
definitions; notes; member-metadata literals; and source-scheme literals. The
per-source family totals are:

| Source | Predicate-family counts |
| --- | --- |
| AGROVOC | preferred labels 31; alternate labels 9 |
| ELSST | preferred 48,378; alternate 34,301; definitions 8,204; notes 4,898; member metadata 96,469; source scheme 42 |
| EuroVoc 4.24 | preferred 193,933; alternate 206,547; definitions 29,064; notes 12,658; source scheme 3,329 |
| EuroVoc domains | preferred 546 |
| GEMET | preferred 184,617; alternate 5,537; definitions 41,223; notes 2,030 |
| NALT | preferred 2; alternate 3; hidden 1; source scheme 1 |
| DOE OSTI and NASA | zero |

The companion JSON is the authority for the exact per-language breakdown and
predicate IRIs; the summary tables above must not be substituted for it.

### Required `DeclaredClaimExclusion` behavior

The existing mechanism excludes whole subjects by type or IRI prefix. It cannot
express this decision because the omitted non-English claims share concept
subjects with English labels, relations, and other claims Atlas does carry. The
auditor-owned change needs a claim-scoped language-family mode, either as an
extension of `DeclaredClaimExclusion` or as a sibling declaration consumed by
the same receipt path.

For each `SourceSpec`, that mode must:

1. Apply the existing source subset first; never count the raw publisher graph
   outside the admitted source scope.
2. Resolve each source predicate to one declared semantic family, including
   SKOS-XL label nodes flattened to their concept and role.
3. Normalize only the language tag for comparison, then select literals with a
   present tag whose BCP 47 primary subtag is not `en`.
4. Compare actual counts exactly with the JSON's source × language × family
   cells. A new language, unknown predicate family, missing cell, or count drift
   must fail the audit.
5. Exclude only those selected claims. Other claims on the same concept remain
   in their existing comparisons.
6. Check the Atlas side independently: the construction summary must contain
   the exact `languageScope` object and Atlas must contain zero non-English or
   untagged definition, note, and label literals.
7. Emit the declaration schema version, payload digest, expected and actual
   per-cell counts, total excluded source claims, and paired Atlas claim count
   in the audit receipt.
8. Add negative fixtures for a count drift, a newly observed language, an
   undeclared predicate family, an omitted construction statement, and one
   non-English Atlas literal.

This is deliberately stronger than a waiver. It freezes what is absent, proves
that the absence matches the declared language policy, and fails when publisher
or product behavior changes.

## Scoped audit: before and after

Both runs used repeated `--only` arguments for `eurovoc-4.24`, `gemet-4.2.3`,
and `nalt-core-bounded-concepts-2026-08-03`. The baseline was the existing
2026-08-13 full artifact; the after run used the four-release bounded artifact
at `output/fidelity-langbugs-report2`.

| Audit measure | Before | After | Meaning |
| --- | ---: | ---: | --- |
| Atlas definitions and notes compared | 8,787 | 10,672 | +1,885 requested annotation quads flow. |
| Annotation-fidelity failures | 106,000 | 104,159 | Net reduction of 1,841; all-language and NALT source-shape differences remain. |
| EuroVoc definitions | 0 | 1,555 | Requested definitions flow. |
| EuroVoc notes | 0 | 329 | 327 scope notes plus two second definitions flow. |
| NALT definitions | 0 | 1 | The one source-attributed English value flows. |
| Atlas labels compared | 23,095 | 23,326 | +231 newly admitted GEMET regional variants. |
| GEMET alternate labels | 60 | 291 | The expected +231 concept-scoped values flow. |

The after auditor exit remains `1` (`passed: false`). That is expected until the
auditor-owned language declaration is implemented. It also continues to report
NALT's two IRI-valued publisher `skos:definition` relations as source claims;
one is faithfully represented by resolved text, but the source relation itself
is not a literal claim.

Receipts:

- before SHA-256:
  `867ea4b4001f4e761ee3d4bd30656def29e2cf5caa5046266b98e42707f4ec7f`;
- after SHA-256:
  `532fd9ee29a7bf5d451bb4bdafe7ad4ef498ce454ff816d77444016b93e9f6cb`.

The receipts are temporary measurement output under `/tmp`; the repository
handoff is this report plus the exact exclusion-count JSON.

## Verification

The bounded build selected only these releases:

```text
eurovoc-4.24
nalt-core-bounded-concepts-2026-08-03
gemet-4.2.3
lcsh-eurovoc-alignment-endpoints-2026-08-06
```

It completed in 69.3 seconds, passed producer validation, and passed graph-to-
Parquet parity. The result is `output/fidelity-langbugs-report2`; its
construction summary contains the exact `languageScope` object above. Relevant
pack content digests are:

- EuroVoc: `sha256:87167148e47c09db1fd76fc4fc483c64f723b155fc9024eb9a6cd70bc71dc1fe`;
- NALT: `sha256:3db70e7b9b86c19d0bbb1a9ce5b448b5f265dc912c852209093c06ed406913d1`;
- GEMET: `sha256:b23d2f33fe26b0ebfa145ab9e385fa1b600bba4c513fe9373cfcbd6a50efc80c`;
- LCSH endpoints: `sha256:e1e790cc8f4782bea1df819d5607566711591026fe9827671cb0b86f73ff4b70`.

Checks completed:

- adapter, parser, generator, and language tests: **184 passed, 5 skipped** in
  89.06 seconds;
- `make lint`: passed;
- `make contract-dev`: passed, including a current 132-case fixture corpus
  with 119 invalid cases and a bounded Federal Register build/verification;
- `git diff --check`: passed;
- scoped source-fidelity auditor: ran in both directions for the three affected
  comparisons and produced the measured deltas above.

The host's global `uv` cache and network were unavailable, so the exact Make
targets ran through the repository's existing `.venv` using a temporary wrapper
under `/tmp`. No repository dependency files changed.

## Main-tree merge needs

Merge the implementation in three reviewable groups:

1. Shared BCP 47 family selection and all adapter/generator call sites,
   including `tests/test_language_tags.py` and the adapter tests.
2. Construction-summary `languageScope`, build-key/validator changes, README,
   SHACL English-text enforcement, and regenerated contract fixtures.
3. EuroVoc/NALT annotation carry, parser and claim-adapter changes, tests,
   `REPORT2.md`, and `REPORT2-language-exclusions.json`.

Then rebuild the affected bounded artifact and rerun the checks above. A release
build must regenerate all sealed distribution and view artifacts because the
construction identity and 1,736 Resource digests changed. The auditor owner must
implement and test the claim-scoped declaration described above before treating
the all-language fidelity result as green. Do not copy a subject-wide exclusion
for these concept claims.

`tools/verify_atlas_source_fidelity.py` was read and run but not edited, as
required.

### Commit boundary

This managed worktree allows source-file writes but denies writes to the linked
Git worktree metadata outside the writable root. A scoped `git add`/`git commit`
therefore fails while creating the linked-worktree `index.lock`. The source
changes and reports are complete but remain uncommitted in this worktree; the
main-tree owner must create the three scoped commits above from an environment
that can write the repository Git metadata. Unrelated `PROMPT*.txt` and
`CODEX_LOG.txt` files are not part of this change.

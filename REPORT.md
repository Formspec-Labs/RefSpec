# JSON/API-capture coverage report

## Result

This branch now has executable, independently parsed coverage for all 18 units in the JSON/API-capture batch: 1,436 Atlas records. Fifteen units use the API-capture JSON reader recovered from `31c5457a`; the remaining three CRS units use a new managed-release JSON reader. No batch unit remains impossible.

Every unit loaded after the merge, authenticated the construction inputs and pack transport, traced the expected resource set, and compared the source claims the reader declares. A `differences-found` status is intentional: it means the adapter ran and reported a real difference or an authenticated claim outside the Atlas member representation. It does not mean the reader failed to load.

## Merge resolution

Merge commit: `b4700b9d Merge commit '857a44be' into research/coverage-json`

The merge had 11 conflict regions in `tools/verify_atlas_source_fidelity.py`, including the large shared comparison path. I resolved them on the required rule: main's bounded-memory machinery wins; this branch's readers and specs survive.

Main-side result:

- Kept the `/13` receipt version, gzip and streaming readers, scalar per-resource digest values, compact normalized-claim mode, native-payload digest checks, and the mutable-then-frozen indexes.
- Kept main's removal of duplicate high-cardinality claim, type, payload, and set-of-one digest indexes. No removed global index was restored.
- Kept cross-spec publisher caching for readers whose authenticated bytes have one meaning.

JSON/API-side result:

- Preserved the 15 recovered API-capture specs, their reader, and their faithful-pair plus mutation tests.
- Keyed the API-capture cache by spec name because four FCC specs and two SAM specs share bytes but deliberately select different record families.
- Kept the source-record target as the identity join for JSON resources that are not SKOS concepts.
- Re-verified every recovered spec against the integrated implementation.

The three CRS readers required only local, bounded state: one observation map of at most 1,043 small JSON rows and one selected set of at most 565 rows. Artifact payloads are authenticated one at a time; raw payload bytes are not accumulated. The reader did not need any index removed by main, and no comparison was weakened because of the refactor.

## Coverage accounting

Measured against the requested new campaign baseline, this batch adds **18 units and 1,436 records**: **31/110 -> 49/110** (about 44.5%).

There is a verified integration discrepancy. The supplied `857a44be` has 28 executable `SourceSpec` declarations after tuple expansion, not 31. It does not contain the prior-art specs for `mesh-descriptors-2026`, `federal-register-api-topics-2026-08-03`, or `gcmd-science-keywords-24-4`. Consequently:

- Campaign accounting, assuming those three landed elsewhere: 49/110.
- Executable total in this worktree after this batch: 46/110 (about 41.8%).
- The final batch-scoped receipt correctly reports 18 evaluated units and 28 other declared comparisons as scoped out; it does not call the scoped-out units covered.

## Per-unit results

| Unit | Source kind | Records | Spec status | What the independent reader compares | Differences found |
|---|---|---:|---|---|---|
| `lda-general-issue-codes` | JSON code array | 79 | differences-found | Source-local identities, exact English labels, issue-code notations, full native payload | All 79 Atlas record digests differ from the single pinned capture digest; Atlas also adds issued date and release identifier |
| `lda-filing-types` | JSON code array | 50 | differences-found | Source-local identities, labels, filing-type notations, identifiers, full native payload | 21 of 50 record digests use a value other than the pinned capture digest; Atlas adds issued date and release identifier |
| `ecfr-cfr-titles` | REST JSON capture | 50 | differences-found | Title identities, labels, title notations, exact per-title payload | Authenticated response-level metadata is not represented; Atlas adds issued date and release identifier |
| `govinfo-collections` | REST JSON capture | 42 | differences-found | Collection identities, labels, codes, exact collection payload | Package and granule counts are not represented; Atlas adds issued date and release identifier |
| `usaspending-award-types` | REST JSON capture | 33 | differences-found | Award-type identities, labels, codes, exact payload | Member comparison is exact; Atlas adds issued date and release identifier |
| `gsdm-reviewed-domain-values-2026-08-03` | Managed JSON dictionary | 40 | differences-found | Reviewed row identities, labels, notations, definitions, exact payload | The other 454 authenticated dictionary rows are outside this reviewed release; Atlas adds issued date and release identifier |
| `nasa-technology-taxonomy-8817` | Nested JSON taxonomy | 17 | differences-found | Derived source identities, labels, definitions, parent relations, full node payload | Root release metadata is authenticated but not represented per node; Atlas adds issued date and release identifier |
| `fcc-ecfs-filing-types` | REST JSON capture | 6 | differences-found | Filing-type identities, labels, codes, exact selected payload | Other filing fields are not represented; Atlas adds issued date and release identifier |
| `fcc-ecfs-access-statuses` | REST JSON capture | 1 | differences-found | Access-status identity, label, code, exact selected payload | Other filing fields are not represented; Atlas adds issued date and release identifier |
| `fcc-ecfs-bureaus` | REST JSON capture | 5 | differences-found | Bureau identities, labels, codes, exact selected payload | Other filing fields are not represented; Atlas adds issued date and release identifier |
| `fcc-ecfs-proceedings` | REST JSON capture | 15 | differences-found | Proceeding identities, labels, identifiers, exact selected payload | One publisher label ends in U+00A0 and Atlas silently trims it; label-set count reconciliation therefore also fails; other filing fields are not represented; Atlas adds issued date and release identifier |
| `federal-hierarchy-orgs-bounded-2026-08-03` | Two paged JSON captures | 20 | differences-found | Organization identities, labels, status/type fields, parent relations, full rows | The bounded pages return 10 rows each while declaring totals of 907 and 738; Atlas adds issued date and release identifier |
| `govinfo-cfr-package-bounded-2026-08-03` | JSON summary plus PREMIS XML | 1 | differences-found | Package identity and label, summary fields, file SHA-256 fixity, location | Other summary and PREMIS fields are authenticated but not represented; Atlas adds issued date and release identifier |
| `sam-uei-bounded-public-entity-2026-08-03` | REST JSON capture | 1 | differences-found | UEI-derived identity, legal name, ownership relations, status, full bounded payload | Registration lifecycle and paging fields are outside the bounded record; Atlas adds issued date and release identifier |
| `sam-cage-bounded-public-facility-2026-08-03` | REST JSON capture | 1 | differences-found | CAGE-derived identity, facility name, related UEI, status, full bounded payload | Registration lifecycle and paging fields are outside the bounded record; Atlas adds issued date and release identifier |
| `crs-legislative-entities` | Closed managed JSON release | 478 | differences-found | Every artifact pin, nested source bundle, selected observation digest, source-scoped identity, 478 labels, exact native payload and payload digest | 565 authenticated observations belong to the sibling subject selection; observation digests and native-payload digests are distinct verified layers; raw captures and release administration are not reparsed as member claims; Atlas adds an issued date absent from the release |
| `crs-legislative-subjects` | Closed managed JSON release | 565 | differences-found | Every artifact pin, nested source bundle, selected observation digest, source-scoped identity, 565 labels, exact native payload and payload digest | 478 authenticated observations belong to the sibling entity selection; the same two digest layers and managed-release metadata boundary apply; Atlas adds an issued date absent from the release |
| `crs-policy-areas` | Closed managed JSON release | 32 | differences-found | Every artifact pin, nested source bundle, selected observation digest, source-scoped identity, all 32 labels and definitions, exact native payload and payload digest | The same two digest layers and managed-release metadata boundary apply; Atlas adds an issued date absent from the release; its individual run is below the 200-label sampling floor |

The LDA digest finding is one systematic class: the comparison expects the authenticated publisher-document digest, while affected Atlas source records contain distinct record-level digests. Field-by-field native payload comparison still runs and is exact; digest disagreement is not used as a substitute for content comparison.

All 18 source releases add `dcterms:issued`; the publisher inputs do not assert that date. The 15 API-capture inputs also do not assert Atlas's `dcterms:identifier`. The CRS release manifests do assert their release IDs, and the new reader now compares those identity claims exactly.

## Impossible units

None. The three CRS bundles initially looked unsuitable because the top-level input is a managed release rather than raw publisher JSON. Main's ICPSR reader established the acceptable pattern: independently authenticate the closed bundle, parse its sealed JSON records without importing the production reader, and explicitly report raw publisher artifacts that are authenticated transitively but not reparsed. Applying that pattern produced honest comparisons for all three CRS units.

## Verification and gates

No unscoped full audit was run. Every source-fidelity invocation used one or more `--only` arguments. The final combined scope contains only this batch's 18 units and 1,436 records.

Required gate commands, verbatim:

```text
make lint
uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q
```

Results:

- `make lint`: passed (`All checks passed!`). The first attempt could not fetch the build-system dependency in the offline sandbox; rerunning the same target with the existing project environment and `uv` synchronization disabled executed the declared Ruff gate successfully.
- `uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q`: `220 passed in 3.63s` after the final reader changes.
- Reader fault gate: the faithful synthetic CRS bundle passes; changing a transitively pinned raw source artifact fails with `artifact pin differs`.
- Merge commit: `b4700b9d`.
- Coverage commits: `20844543` and `b433fdb9`.

Scoped verification output for every spec is in `/tmp/cov-json-<unit>.json`; the final all-batch receipt is `/tmp/cov-json-all-18.json`. The final combined output was:

```text
PASS  load-errors                   0 source, inventory, or pack loading errors collected
FAIL  distribution-coverage         18/110 construction units have an independent comparison; 28 not evaluated (scoped out)
PASS  publisher-input-pins          17 distinct publisher inputs authenticated; 21/21 construction input rows matched exactly
PASS  graph-structure               18 manifest-discovered packs checked for transport and source-evidence structure
FAIL  rdf-provenance-fidelity       1436 RDF source records checked against publisher bytes
PASS  concept-traceability          1436 asserted concepts traced to a publisher record across 18 sources
PASS  identifier-retention          1436 concept identities checked against declared source identity policies
FAIL  label-fidelity                1436 Atlas labels compared byte-for-byte against publisher literals
PASS  annotation-fidelity           46 Atlas definitions and notes compared as exact RDF literals in every language
FAIL  count-reconciliation          305 source claim categories reconciled exactly
FAIL  source-release-metadata       36 Atlas release claims compared against publisher release descriptions
FAIL  source-claim-coverage         25 publisher or Atlas source claims remain outside executable comparisons
```

Those failures are the differences itemized above, the still-uncovered construction units, and claims explicitly reported outside the member representation. There were no reader load errors, input-pin errors, pack errors, unknown identities, missing concepts, or manufactured relations in this batch.

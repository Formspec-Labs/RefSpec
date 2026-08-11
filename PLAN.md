# RefSpec plan

Written 2026-08-11. This file is the owning plan for RefSpec work.

Boundaries are stated once in [the decision ledger](docs/decisions.md).
REF-024 carries the cross-product ownership rows, the artifact-and-package
exchange rule, and the payload rule for unowned upstreams. REF-025 carries
canonical `Label.id` in the next search view. Cite them by identifier; this
file does not restate them.

The cut test, applied to every item below:

> Keep a capability only if the target needs it. Preserve any durable
> conclusion outside the implementation. Delete the old path.

Verification is one operation per boundary crossing. Admission and open are
two crossings, so an artifact is verified at each — never once per artifact
lifetime. Each operation covers the root manifest and every declared member
and retains the membership, schema, relative-path, containment, and
symlink-safety rules. What goes is ambient receipts and redundant re-hashing,
not the checks.

The DocSpec seam is `SourceCatalogRelease -> DocumentRelease`. An internal
port implements that boundary; it does not replace it.

Owners and exit gates are recorded for the two blocking artifact items below.
Small repository edits carry neither.

## 1. Search view carrying `Label.id`

Search view 1.1 carries canonical `Label.id` (REF-025).

`src/refspec/atlas/parquet_search_view.py:35,38` sets
`SEARCH_VIEW_SCHEMA_VERSION = "1.1"` and
`SEARCH_VIEW_IMPLEMENTATION_VERSION = "1.1"`. The LABEL Arrow schema at
`:126-136` carries `id` ahead of `resource`, `label_role`, `value`, `language`,
`release`, and `source_record`. The builder copies `id` from the full view's
`tables/labels.parquet`, whose LABEL schema at `parquet_view.py:163` carries
the same canonical `Label.id` the compact packs carry as `LabelRecord.id`
(`compact_pack.py:163`); nothing in the search view mints a label identifier.
`Label.id` is gone from `status.omittedFields`, so a 1.0 manifest and a 1.1
manifest differ in that list as well as in `schemaVersion`.

Verification requires the field. `verify_atlas_parquet_search_view` refuses a
LABEL member whose Arrow schema has no `id` with a message naming REF-025 and
version 1.1, before the generic schema comparison; the manifest check names the
expected schema version; and `_transform` refuses a full-view label row without
`id` during a build. `AtlasDuckDBView.open` verifies before it opens, so it
carries the same refusal.

`tests/test_atlas_parquet_view.py::test_search_view_refuses_a_label_member_without_canonical_label_id`
rewrites a built view's Label member without the column and reseals the
manifest around it, so the byte length, member digest, schema digest, row count
and file-membership checks all pass; `verify_atlas_parquet_search_view` and
`AtlasDuckDBView.open` both raise on the absent field.
`test_compact_search_view_preserves_graph_and_omits_native_payload` pins
`schemaVersion` 1.1 and the label row's `id` against the full view's.

Built from real data on 2026-08-11:
`output/atlas-3.0-parquet-search-view-2026-08-11`, from the full view
`output/atlas-3.0-parquet-view-2026-08-10` pinned at
`cd712aacc0308594e6cad77be327b482779a3fb4cc93dacd7d0c6bb04d1d5207`. Manifest
SHA-256 `cf645ad8316875b43735561ec2910cf42fd05cf90961dcde2c59c0fdce59759d`,
view id
`urn:ref:atlas-parquet-search-view:6e2489f0124ffa7e0c1f508452a449057e05de376b4e02b88778581d59786446`,
3,288,830 role rows of which 984,114 are labels, 224,874,647 bytes in nine
files. Its Label columns are `id`, `resource`, `label_role`, `value`,
`language`, `release`, `source_record`, and the first label identifier is
`urn:ref:atlas-label:3b03086ebc31340c3c348d57ee2b20f0a99b053e451db0767262165efab4bc61`.
`refspec-build-atlas-search-view --verify-only` passes on that directory and,
on the 1.0 view built from the same full view, exits with `compact view type or
version is unsupported: expected schema version 1.1`. The identifier costs
30,887,361 bytes there: 74,779,216 against 43,891,855 for the Label member.

Both directories are under the gitignored `output/`, so the tracked proof is
the test, not the bytes. Item 2 is where a bounded distribution and a search
view over it get published from a pinned source rather than from the
multi-scheme development Atlas.

- Owner: RefSpec.
- Exit gate: a published search view whose LABEL member carries the canonical
  `Label.id`, whose manifest `schemaVersion` names the new version, and whose
  verifier fails when the field is absent.

## 2. Bounded Atlas 3.0 distribution for the Federal Register Thesaurus

Publish one bounded Atlas 3.0 distribution for the April 1, 2025 Federal
Register Thesaurus scheme:

- release `urn:ref:atlas-release:3:federal-register-thesaurus:2025-04-01`
- source SHA-256
  `66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f`
- 1,051,423 bytes
- 705 concepts, 1,138 labels, 1,451 resolved relation rows

The requirement is inherited from SpicySearch. RefSpec verifies the
distribution before publication rather than accepting the numbers on the
consumer's word.

- Owner: RefSpec.
- Exit gate: the source digest matches before the build runs, producer-side
  semantic verification reproduces the four counts, and publication is atomic.

## 3. Content-derived distribution identity

Derive distribution identity from content and exclude timestamps.

`tools/generate_atlas_v3_full.py:122-123` hardcodes
`CREATED_AT = "2026-08-06T08:45:00+00:00"` and
`DISTRIBUTION_ID = "urn:ref:atlas:distribution:3.0-full-development:2026-08-06"`.
Four distinct builds on disk carry byte-identical identity.

## 4. Production input resolver

`src/refspec` resolves roughly 71 build inputs relative to a checkout root.
`src/refspec/atlas/v3_registry_codes.py:1389` reads
`research/evidence/regulatory-native-controls-2026-08-03/source-native-control-capture.json`
off a `repo_root` parameter. An installed package therefore works only from a
checkout.

The resolver maps a logical path plus an expected digest to bytes. It is
scheduled here, explicitly, in this plan — not named as an unscheduled
prerequisite somewhere else.

## 5. Ordinary continuous integration

Small deterministic fixtures, generator drift checks, import and build checks,
and a skip budget. Bounded inputs only.

Generator drift, as of this writing: `tools/build_registry_source_manifest.py`
accepts `--check` at `:1381`, and `Makefile:28` runs it inside
`check-generated`. `make check-generated` exits 0 and reports
`registry source manifest is current: 80 registry modules`.

The hazard that check carried — `_icpsr_managed_release_test_inputs()` read
two files under the gitignored `output/` directory unconditionally, so a
clean clone failed the step with a missing-file error rather than drift — is
closed as of 2026-08-11. The two build inputs are pinned as byte-identical
tracked copies under `tests/fixtures/icpsr_managed_release/`:

- `capture-index-manifest-2026-07-30.json`, sha256
  `67b90a239de8ba7cb70a4e9d81c5c7bf30198800cf1aa0ecdc96246b30f94fea`;
- `subject-2026-07-30.xml`, sha256
  `1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff`.

The generator reads the fixtures; `localPath` metadata keeps naming the
capture location under `output/`, so the generated manifest and the tracked
`sources.json` are byte-identical to before. The full `check-generated`
target passes with the ICPSR capture directory absent from `output/`.

Skip budget: 16 of 143 test modules skip when the gitignored `output/` is
absent. An unbudgeted green repeats a known deselection failure, so the budget
is a number the job asserts against.

## 6. Release job, separate from continuous integration

The bounded single-scheme Atlas build of item 2 and its semantic verification
run in the release job only. The multi-scheme full-Atlas generator stays out
of both gates: it reads gitignored inputs and builds schemes the MVP cuts.

## 7. Package only production code

Package the production roster. Research tools stay in `research/`; test
coverage does not promote a tool into the package surface. The roster is
`research/repo-traces-2026-08-08/RESEARCH.md` §2.

Atomic publication by rename and content-addressed identifiers are preserved
as they stand.

## Historical corrections that prevent a wrong action

- An exact version pin failed to catch symbol removal. `spicy-regs`
  `pyproject.toml:12` declares `refspec==0.1.0.dev0`, and RefSpec's
  `pyproject.toml` carries one
  `+version` line in its entire history, while
  `refspec.registry.elsst_acquisition` moved and two modules were deleted.
  Installed-wheel consumer conformance is what catches removal; a version
  bound is not.
- The DocSpec blob gate still runs. `DocSpec/tests/test_boundary_code.py:135`
  is always-on under the default `addopts`; only `:157` carries
  `@pytest.mark.integration`.
- The stat re-read at `verified_member_ledger.py:38` is the warm-reuse
  cache-invalidation key, not hostile-input paranoia. Deleting it changes the
  ledger's correctness.
- A `formatVersion` 1.0 to 1.1 bump would be a regression. `formatVersion 1.0`
  is each profile document's own version. The stale field is
  `logicalSchemas: docspec-document-release/1.0`, in
  `canonical-release-manifest-v1.json` and `local-document-catalog-v1.json`.

## Deferred by decision

Roughly 22 GB of regenerable output is deferred by decision, not overlooked;
the measurements are in `research/repo-traces-2026-08-08/RESEARCH.md` §12.

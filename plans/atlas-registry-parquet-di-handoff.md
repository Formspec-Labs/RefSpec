# Atlas registry Parquet dependency-injection handoff

Implement a vertical slice of artifact-level dependency injection between
RefSpec registries and Atlas.

## Goal

Define one shared, lossless registry-release artifact that registry readers
export and Atlas consumes without importing source-specific registry parsers.
Prove the boundary using real EuroVoc and GEMET releases, then compare Atlas
back to those artifacts with one generic fidelity validator.

## Read first

- `AGENTS.md`
- `README.md`
- `ATLAS_US_EU_COMPARISON.md`
- `docs/decisions.md`, especially REF-015 and REF-020
- `docs/atlas-source-fidelity-issues.md`
- `src/refspec/atlas/v3_source_data.py`
- `src/refspec/registry/infrastructure/source_concept_release.py`
- `tools/verify_atlas_source_fidelity.py`
- The current Atlas implementation and worktree. Another person is building a
  new Atlas version, so find the active seam before editing and preserve
  unrelated work.

## Required design

Create a shared registry-release bundle, not a bespoke Parquet schema per
registry and not a serialization of the current lossy `RegistryRelease`.

The minimum bundle is:

- `release-manifest.json`
- One logical `claims.parquet` table, sharded only when necessary
- Exact pins or closed references to the raw captures
- Digests, schemas, row counts, release scope, language scope, and derivation
  recipes

A claim must preserve enough information to compare source-visible data without
source-specific Atlas logic:

- release ID
- subject
- predicate
- IRI or literal object
- lexical value, language, and datatype
- source record ID, locator, path, and digest
- origin: observed, scraped, normalized, inferred, or extrapolated
- versioned extraction or derivation recipe
- optional confidence and declared limitations

## Product policy

- English completeness is required; non-English content is not a release
  blocker. Declare English-only scope in the manifest.
- Official files are preferable but not required.
- Scraped, sampled, reconstructed, repaired, or extrapolated data is acceptable
  when the release preserves its raw evidence and explicitly records the
  method, scope, assumptions, date, and derived status.
- Silent repair and silent omission fail.
- Atlas-only rings, profiles, releases, governed schemes, class assignments,
  and graph placement are outside source fidelity.
- Publisher-native schemes, memberships, collections, relations, annotations,
  and provenance are in scope.

## Implementation boundary

- Put source-specific parsing and derivation before the registry-release
  artifact.
- Put no EuroVoc-, GEMET-, or other registry-specific interpretation after that
  boundary.
- Atlas must receive artifact paths and expected manifest digests as injected
  inputs.
- Reuse the closed-manifest, digest, immutable-write, and verified-view patterns
  from `SourceConceptReleaseBundle`.
- Reuse shared Parquet utilities where appropriate.
- Do not use the existing Atlas-derived Parquet view as the input; that would
  compare Atlas with itself.
- Do not remove the current construction path until parity is demonstrated.

## Vertical slice

1. Define and validate the shared bundle and Parquet schema.
2. Add deterministic central writer and verified reader code.
3. Export real EuroVoc and GEMET registry releases through it.
4. Ensure the bundles retain the source structures previously lost:
   - EuroVoc scheme identities, memberships, English definitions and notes;
   - GEMET collections, group memberships, subgroup relations, hierarchy roots,
     relations, English content, and literal datatypes.
5. Add an Atlas input adapter that consumes these bundles without importing
   their registry parsers.
6. Add a generic validator that converts Atlas source-visible assertions back
   into claim rows and performs an exact multiset comparison.
7. Continue after individual errors and report all added, missing, and changed
   claims.
8. Leave a precise migration inventory for releases not converted in this goal.

## Acceptance criteria

- Adding a bundle does not require source-specific Atlas code.
- The Atlas-side reader imports no EuroVoc or GEMET parser.
- Bundle generation is byte-stable.
- Manifests close and authenticate every member.
- Raw input drift, manifest drift, schema drift, row mutation, missing claims,
  added claims, datatype changes, direction changes, and undeclared
  normalization all fail.
- Declared English-only selection, scraping, repair, and extrapolation pass with
  complete evidence.
- EuroVoc's 15,438 memberships round-trip exactly.
- GEMET collections and the 9,658 currently missing relations enter the
  comparison as first-class rows.
- The generic comparison lists every error rather than stopping at the first.
- Fault-injection tests prove the validator detects representative mutations.
- Existing targeted Atlas and registry tests continue to pass.
- Run Ruff and `git diff --check`.
- Do not claim full Atlas migration or source fidelity; report the exact
  converted and unconverted boundary.

## Deliverable

Working code, schemas, tests, generated development bundles or fixtures, and a
short architecture note covering:

- what was reused;
- the artifact contract;
- dependency direction before and after;
- how observed versus derived claims are represented;
- real EuroVoc and GEMET parity results;
- known failures;
- remaining migration inventory; and
- local, committed, pushed, and published status separately.

Do not push, publish, deploy, or overwrite unrelated work unless explicitly
authorized.

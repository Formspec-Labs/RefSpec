# Atlas registry claim-release boundary

## Decision

Keep `RegistryRelease` as the normalized Atlas compatibility view during the
migration. Do not turn it into the registry artifact. Registry producers now
export a separate, lossless `RegistryClaimRelease` bundle. Atlas can inject the
bundle beside the compatibility view using only its path and an expected
manifest digest.

This split prevents a lossy model from defining the source-fidelity boundary.
It also lets the current Atlas build continue while each registry proves
parity.

## Data flow

What goes in: a registry-specific reader parses pinned publisher files and
finishes any declared scraping, normalization, inference, repair, or
extrapolation. Repair uses the `normalized` origin and a versioned recipe.

What happens: the central writer creates an immutable directory containing:

- `release-manifest.json`;
- `claims.parquet`, using one shared claim schema;
- the exact raw files, including pinned ZIP members where applicable; and
- authenticated JSON Schemas for the manifest and claim records.

Each claim retains its RDF direction, IRI or literal object, exact lexical
form, language or datatype, source record, locator, path, digest, origin,
recipe, optional confidence, and declared limitations. Every claim digest must
resolve to a raw-file or archive-member pin in the same closed bundle.

What comes out: `AtlasRegistryClaimInput` verifies the external manifest pin,
all members, schemas, row counts, logical row digest, evidence pins, and closed
file set. The generic adapter groups exact claims into Atlas `SourceRecord`
native payloads. It imports no EuroVoc or GEMET parser. The current normalized
resources and relations remain in place; exact claim records are supplemental
source evidence during parity work.

How we check it: the generic validator converts Atlas source records, including
records read from the authenticated Atlas Parquet view, back into claim rows.
It performs an exact multiset comparison and reports every added, missing, and
changed claim in one result.

## Dependency direction

Before this change, Atlas imported each registry parser and adapted its
publisher model directly into `RegistryRelease`. That path remains the
compatibility path.

The new direction is:

`publisher files -> registry parser -> RegistryClaimRelease -> generic Atlas adapter`

`load_releases(..., registry_claim_inputs={key: input})` is the production
injection seam. The caller supplies the bundle path and trusted manifest
digest. Code after the artifact boundary contains no publisher-specific
interpretation.

## Reused controls

The bundle reuses the `SourceConceptReleaseBundle` approach: canonical JSON,
external manifest authentication, member digests and lengths, closed file
membership, immutable temporary writes followed by rename, deterministic
Parquet settings, and a verified read view. The claim comparator and Atlas
adapter are shared across registries.

## Observed and derived claims

`origin` distinguishes `observed`, `scraped`, `normalized`, `inferred`, and
`extrapolated` claims. A derived claim is valid only when its recipe is declared
and versioned, its limitations are declared, and its source digest resolves to
raw evidence retained in the bundle. The writer rejects undeclared recipes,
limitations, and evidence. It never trims or rewrites lexical values silently.

## Real vertical-slice results

The results below use the pinned files under
`output/registry-real-data-sources/` and the generated development bundles
under `output/registry-claim-releases/`.

| Release | Exact claim rows | Required structures | Generic comparison | Manifest digest |
| --- | ---: | --- | --- | --- |
| EuroVoc 4.24 | 78,713 | 15,438 `skos:inScheme` memberships; English definitions and notes; scheme and metadata claims | 78,713 exact, 0 differences | `sha256:20f93d631aa7e5e6dfe86cec4bd6fcd32e307836b78a6c7d1018aa570d319ee4` |
| GEMET 4.2.3 | 86,932 | 16,178 collection memberships; 5,651 group and concept scheme memberships; 9,658 mapping relations; 32 subgroup relations; English literals and datatypes | 86,932 exact, 0 differences | `sha256:a9f2b06ba37ee4fc54b3021a232c595696003263fbc71de878cee7a96eecd4bb` |

The production loader also verified both real injected bundles and all input
pins. It retained 7,771 EuroVoc and 5,739 GEMET supplemental source records
beside the existing normalized releases. A focused fixture additionally passed
the complete bundle-to-Atlas-compact-to-Atlas-Parquet-to-comparator path.

The full cold build then injected both bundles through the production command
line. The compiled-producer gate passed against Atlas 3 binding bundle digest
`sha256:533e2490a7b9f96e6b85e3468c91d87904c0c0490be45f8ab96ceaac331b5313`.
The resulting local distribution contains 604,071 source records, 588,409
resources, 560,429 relation assertions, and 30,970,068 asserted RDF quads. Its
authenticated manifest digest is
`sha256:26aa0ddbe132c0d1a68f4ed6df4d353e892264bf8e058608b09916b176bf780f`.

The derived Atlas Parquet view also passed its build and verification gates.
Its manifest digest is
`sha256:a8747e8c4d350573c478ec36846d39b5c2cb8bae8b26ff46fcd6c8a74f3daace`.
The generic streaming reader recovered both injected releases in one scan of
the 604,071 source records. The exact comparisons found 78,713 of 78,713
EuroVoc claims and 86,932 of 86,932 GEMET claims, with no added, missing, or
changed rows.

The independent Atlas 3 validator then passed the complete distribution. It
checked all 30,970,068 asserted RDF quads, every semantic gate, and compact-RDF
parity for all 3,302,340 compact records. Its final resource, source-record,
label, relation, mapping, assignment, identifier, and release counts matched
the producer output.

## Failure coverage

Tests fail on raw-member drift, external manifest drift, closed-set drift,
Parquet schema drift, resealed row mutation, missing or unpinned evidence,
missing claims, added claims, datatype changes, direction changes, and
undeclared whitespace normalization. A separate fixture proves that declared
English-only selection and declared scraped, normalized repair, inferred, and
extrapolated claims pass with retained evidence.

## Known boundary and migration inventory

This is not a full Atlas migration or a full source-fidelity result.

- Only `eurovoc-4.24` and `gemet-4.2.3` have claim-release exporters and real
  parity results.
- When the EuroVoc claim bundle is injected, `eurovoc-domains-4.24` now derives
  its 21 normalized resources from declarative claim rules without calling the
  EuroVoc parser. An exact parity test matches the previous parser-built
  compatibility release except for the physical location of identical pinned
  input bytes.
- The other 109 normalized construction units still use their existing source
  parsers, including the main `eurovoc-4.24` and `gemet-4.2.3` compatibility
  releases. Their claim bundles remain supplemental source evidence.
- The real bundles passed the generic adapter, production loader, full cold
  distribution build, compiled-producer gate, independent Atlas validator,
  derived Parquet build, and exact Parquet comparison. These results prove the
  new path for the two injected releases; they do not establish parity for the
  remaining construction units.
- The full distribution result above predates the artifact-derived EuroVoc
  domains compatibility view. Focused parity, selective-loader, and generator
  tests cover that follow-on change; a new full distribution has not yet been
  built from it.
- Existing normalized construction must remain until each registry passes the
  same artifact-to-Atlas comparison and the full distribution gates pass.

## Delivery status

- Local: implementation, schemas, tests, architecture note, and ignored
  development bundles, full distribution, and Parquet view exist in this
  worktree. The full build is under
  `output/atlas-3.0-registry-claim-proof-2026-08-07/`.
- Committed: no.
- Pushed: no.
- Published or deployed: no.

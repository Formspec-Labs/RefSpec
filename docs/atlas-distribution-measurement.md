# Atlas distribution measurement, 2026-08-02

> **Three things below were superseded by execution the same day.** See
> [`elsst-r6-only-atlas-2026-08-02`](../research/evidence/elsst-r6-only-atlas-2026-08-02/README.md).
> The R6-only numbers here are derived from a two-edition build; a real R6-only
> managed release now exists, and the atlas built on it is **45,066,321 bytes**
> with all 365 candidates and all 121 mappings intact and the qualified set
> identical. A projection now has its own identity, so "a projection and its
> parent share one asset identifier" describes the old format and not the
> current one. And finding 1 has been fixed on the consumer side: the vendored
> reader at `sha256:0b396888…` opens a hierarchy-bearing atlas that the reader
> at `sha256:5f96c241…` refused. Everything else stands as measured.

None of the atlas work reaches search until SpicySearch can consume an atlas
that contains it. SpicySearch consumes by **vendoring the asset into its own
repository** — today a 1,469,637-byte Federal-Register-only distribution under
`fixtures/releases/vocabulary-atlas/` — and it has no remote-read path at all.
The full three-vocabulary atlas with its qualified mappings is 276,681,774
bytes. So the question "vendor a projection, publish a pointer, or fetch a
release artifact" is open.

This document does not answer it. It converts each option into a number.

The short version: **the smallest distribution that satisfies every read
SpicySearch performs is 61,900,562 bytes (3,497,671 gzipped) — 22.4% of the
full atlas — and it returns byte-identical results from every consumer
accessor.** Dropping ELSST's second edition takes the full atlas to 58,492,923
and the projection to 36,712,651. The projection is admissible today; the full
atlas is not, for a reason that has nothing to do with its size.

Everything below was measured by execution against real distributions built
from the pinned bundles. Two findings turned up before the size question and
they change its shape, so they come first.

## Finding 1 — today's atlas is already refused by the vendored reader

Not because it is large. Because of one manifest field.

The hierarchy amendment (`04363fc`) made the producer declare `hierarchyEdges`
in `counts` exactly when the release facts state a hierarchy
(`src/refspec/atlas/model.py:1759-1763`, enforced on open at `:2370-2412`).
SpicySearch's reader pins the count field set exactly:
`_COUNT_FIELDS` (`spicysearch/src/spicysearch/vocabulary_atlas.py:43-52`) has
eight names and `hierarchyEdges` is not one of them, and `:414` refuses any
manifest whose count key set differs.

Executed against both real distributions — FR + ELSST + crosswalk, and
FR + ELSST + ICPSR + crosswalk:

```
VocabularyAtlas.open(...) -> IntegrityError: atlas counts must be nonnegative integers
```

(The message is the field-set branch borrowing the value branch's text at
`:414-415`; the cause is the unexpected key, not a bad value.)

Remove that one field from the manifest and the same bytes open. The asset
identifier does not move, because `generationDigest` is a digest of
`{format, inputs, implementation, policies}` only (`model.py:2286-2297`,
mirrored at `vocabulary_atlas.py:438-450`) — `counts` is not part of identity.

**Consequence.** Federal Register 2025 states no hierarchy, so the vendored
FR-only atlas is admissible. ELSST and ICPSR both state one. **There is no
distribution containing either vocabulary's hierarchy that both sides accept
today** — declare `hierarchyEdges` and the consumer refuses; omit it and the
producer refuses (`atlas declared counts differ`, executed both ways). This is
a one-field consumer amendment, not a format redesign, but nothing ships until
someone makes it.

## Finding 2 — a projection and its parent share one identity

A consumer-shaped projection was built (below) and opened with both readers:

| | asset id | bytes | opens under `VocabularyAtlas.open` (consumer) | opens under `VocabularyAtlasAsset.open` (producer) |
|---|---|---:|---|---|
| full FR + ELSST + ICPSR + crosswalk | `urn:ref:vocabulary-atlas:d1f0d786…82a6` | 276,681,774 | no (finding 1) | yes |
| consumer projection of it | `urn:ref:vocabulary-atlas:d1f0d786…82a6` | 61,900,562 | **yes** | **yes** |

Same identifier. Same two named graph IRIs (they are derived from it,
`model.py:2301-2304`). Payloads 4.5× apart. Both admitted by the producer's own
validator, executed. The FR + ELSST + crosswalk pair behaves identically
(`urn:ref:vocabulary-atlas:70f4ecbe…f893a`, 263,620,491 against 54,378,005).

This is not a defect in the projection; it is what the format says. Identity is
a function of generation inputs, and a projection has the same generation
inputs. But it means **binding 1.0 cannot express "this is a derived subset of
that generation"** — a projection is currently indistinguishable from the
generation it came from except by the digests a consumer happens to pin.

The saving grace is that SpicySearch's pin is three-part —
`{asset_id, manifest_digest, distribution_digest}`
(`spicysearch/src/spicysearch/snapshot.py:406-417`) — so a consumer that pinned
the full atlas will refuse a projection substituted underneath it. Anything
pinning `asset_id` alone would not.

## What the consumer actually reads

Every citation below is `spicysearch/src/spicysearch/`. The reader is 846 lines
and file-only; it imports nothing from RefSpec.

### Manifest, at `VocabularyAtlas.open`

Field set `_ROOT_FIELDS` (`vocabulary_atlas.py:22-35`, checked `:284`);
`schemaVersion`/`format`/`type` (`:286-289`); `canonicalPayloadDigest`
recomputed (`:296-301`); `implementation` pin including every source module
path and digest (`:303-330`); `inputs` — managed releases, exactly one Rulespec
Core, at most one crosswalk (`:332-359`); `graphs` — exactly two, roles
`releaseFacts` and `analysis`, each `quadCount` a **positive** integer
(`:361-376`); `output` — `path` must be `atlas.nq`, media type
`application/n-quads`, digest equal to the consumer's own pin (`:378-385`);
`counts` (`:413-434`); `policies` equal to `_POLICIES` (`:36-42`, `:435-437`);
`generationDigest` recomputed and the asset id derived from it (`:438-456`).

### Distribution, at `VocabularyAtlas.open`

The whole file is parsed (`:396-400`), **re-serialized canonically and
byte-compared** (`:401`, `_canonical_nquads` at `:192-199`, which also refuses
blank nodes), the non-empty named-graph set is compared to the manifest
(`:403-406`), total and per-graph quad counts are checked (`:407-412`), and
every declared count is re-derived from the graph (`:417-434`):
`labelClusters` from `rdf:type atlas:LabelCluster`, `mappingCandidates` from
`atlas:MappingCandidate`, `searchOnlyMappings` from `rkaf:ConceptMapping` with
`rkaf:usageEligibility rkaf:searchOnly`, `machineValidations` from
`atlas:MachineValidation`, `feedback` from `atlas:MappingFeedback`.

`open` then runs three fail-closed passes before returning (`:468-470`):
`_validate_authoritative_membership` (`:501-509`), `label_clusters` (`:610-634`)
and `search_only_mappings` (`:636-823`).

### The predicates, by accessor

| Accessor | Graph | Predicates read | Called from |
|---|---|---|---|
| `pin` `:477`, `rulespec_core_pin` `:486` | — | manifest only | `snapshot.py:1172`, `:1183`, `:1419`, `:1472`, `:1516` |
| `reference_release_pin` `:526` | releaseFacts | `rdf:type rkaf:ReferenceResourceRelease`, `rkaf:referenceReleaseDigest` (`:832-837`) | `snapshot.py:1191`, `:1265` |
| `contains_member` `:536` | analysis + releaseFacts | `atlas:memberOfRelease`; `prov:hadMember`; the two above | `snapshot.py:1312` |
| `concept_labels` `:555` | releaseFacts | `skos:prefLabel`, `skos:altLabel` (`:566`), filtered to subjects that are `prov:hadMember` objects (`:570`) | `concept_resolution.py:155` ← `engine.py:1819` |
| `related` `:577` | releaseFacts | `skos:related`, both stated directions (`:588`, `:592`) | `concept_resolution.py:134` ← `engine.py:1223` |
| `search_only_mappings` `:636` | analysis + releaseFacts | the full mapping closure, below | `snapshot.py:1441` |
| `label_clusters` `:610` | analysis | `rdf:type atlas:LabelCluster`, `atlas:normalizedLabel`, `atlas:member`, `atlas:memberRelease`, cross-checked against `atlas:memberOfRelease` (`:615-625`) | **nothing** — `open` only (`:469`) |
| `member_ids` `:511`, `require_member` `:548`, `related_pairs` `:599` | | | **no product caller** |

The mapping closure, all in the analysis graph unless marked: mapping node
`rdf:type rkaf:ConceptMapping` (`:642`), `rkaf:usageEligibility` (`:643`),
`rkaf:assertionOrigin` / `rkaf:epistemicBasis` / `atlas:verificationStatus`
(`:645-651`), `rkaf:assertsSubject|assertsPredicate|assertsObject`
(`:652-656`), `rkaf:sourceConceptRelease` / `rkaf:targetConceptRelease`
(`:657-658`), `atlas:qualifiedFrom` (`:659`), `atlas:qualifiedBy` (`:660`);
candidate `rdf:type atlas:MappingCandidate` (`:663`), `atlas:candidateDigest`
(`:666`), the five endpoint predicates (`:669-675`), `rkaf:usageEligibility`
(`:684`), `atlas:evidence` (`:686`), `atlas:inputContextDigest` (`:705`);
every named artifact's `rdf:type atlas:CrosswalkArtifact`, `atlas:artifactRole`
and `atlas:artifactDigest` (`:689-704`, `:730-741`); each validation's
`rdf:type atlas:MachineValidation` (`:711`), `atlas:validates` (`:713`),
`atlas:deterministicChecksPassed` (`:717`), `atlas:outcome` (`:719`),
`atlas:validationDigest` (`:722`), `atlas:sealedInputDigest` (`:725`),
`atlas:requestArtifact` / `atlas:responseArtifact` (`:728-729`),
`atlas:providerModelId` (`:743`), `atlas:validatorActor` (`:750`),
`atlas:independenceGroup` (`:751`), `atlas:provider` (`:752`); and in
**releaseFacts**, `prov:hadMember` for both endpoints (`:763-767`),
`rdf:type rkaf:ReferenceResourceRelease` (`:777-786`) and
`rkaf:referenceReleaseDigest` (`:787-800`).

### Today, versus the two policy flips

**Today** the engine reads exactly two things from the graph:
`concept_labels()` for `atlas-normalized-label-v1` and `related()` for
`within-vocabulary-related-v1` (`engine.py:1217-1223`). The build reads
`contains_member` and `reference_release_pin`. Nothing else is consulted.

**And the file is carried three times over.** The build copies both atlas files
verbatim into the snapshot (`snapshot.py:2139-2140`), the sealed snapshot
manifest requires both paths to be present
(`inputs/vocabulary-atlas/atlas.nq`, `snapshot.py:3208-3214`), and the engine
reopens the copy — full parse, full canonical re-serialization — on the first
concept query of each engine instance (`engine.py:1831-1836`). Whatever is
vendored is paid for in the repository, in every published snapshot, and in
engine start-up.

**When the expansion policy flips** to `atlas-search-only-directed-v1`
(`snapshot.py:1440-1441`), the whole mapping closure above becomes a build-time
read. It is not a new read at open — `open` already walks it — but it becomes
load-bearing for output rather than only for admission.

**When hierarchy expansion lands** there is no accessor to extend: the reader
has **no** `broader`/`narrower` method, and the string `broader` does not occur
anywhere in `spicysearch/src/`. Hierarchy needs a new accessor *and* the
`_COUNT_FIELDS` amendment from finding 1.

**Never read, at any point**: `skos:definition`, `skos:scopeNote`,
`skos:historyNote`, `skos:changeNote`, `skos:inScheme`, `skos:hasTopConcept`,
`skos:topConceptOf`, `skos:notation`, `skos:broader`, `skos:narrower`,
`owl:priorVersion`, `owl:deprecated`, every `dcterms:` predicate,
`xkos:additionalContentNote`, `dcat:*`, `prov:used`, ICPSR's
`atlas:thesaurusUse` / `atlas:thesaurusUsedFor`, every release-node `rkaf:`
lifecycle statement, `atlas:inputContextArtifact`, `atlas:contentDigest`,
`atlas:selectionPolicy`, and — outside `open`'s own validation — every label
cluster.

## Measured distributions

Built from the pinned bundles recorded in
[`docs/icpsr-atlas-bridge.md`](icpsr-atlas-bridge.md); the crosswalk is the
2026-08-02 qualification bundle
(`sha256:d9a905a0d96bdf22ed829bfb7c5afc54b2084b1ebbcf3dbd88aebab0350d35d2`,
121 qualified mappings). `gzip -9`.

The target distribution — all three vocabularies plus the qualified mappings
that make cross-vocabulary expansion live — is **276,681,774 bytes** and
**17,496,208 gzipped**. The 2026-08-02 three-vocabulary figure of 270,130,849
was the same build without a crosswalk; the qualification closure costs
6,550,925 bytes.

| Distribution | `atlas.nq` | gzip -9 | quads | label clusters |
|---|---:|---:|---:|---:|
| Federal Register 2025 only — **vendored today** | 1,469,637 | 35,569 | 5,426 | 0 |
| … its consumer projection | 1,086,877 | 28,958 | 4,001 | 0 |
| ICPSR only | 12,008,709 | 308,614 | 42,064 | 0 |
| … its consumer projection | 7,522,557 | 155,467 | 25,642 | 0 |
| FR + ICPSR, no ELSST | 13,960,251 | 364,499 | 48,959 | 245 |
| … its consumer projection | 8,609,434 | 185,110 | 29,643 | 0 |
| FR + ELSST + crosswalk | 263,620,491 | 17,038,083 | 884,214 | 96,867 |
| **FR + ELSST + ICPSR + crosswalk** | **276,681,774** | **17,496,208** | **929,327** | **96,958** |
| … minus label clusters | 92,295,636 | 6,504,143 | 340,471 | 0 |
| … `releaseFacts` graph only — *inadmissible, see below* | 82,461,672 | 5,916,836 | 309,166 | 0 |
| … **consumer projection** | **61,900,562** | **3,497,671** | **239,316** | 0 |
| … consumer projection + `skos:broader` | 64,369,332 | 3,747,738 | 247,829 | 0 |
| … consumer projection + `broader` + `narrower` | 66,846,615 | 3,971,446 | 256,342 | 0 |
| … ELSST R6 only, derived | 58,492,923 | 3,849,189 | 210,931 | 1,461 |
| … ELSST R6 only + consumer projection, derived | 36,712,651 | 1,948,253 | 139,053 | 0 |

**`releaseFacts`-only is not a distribution.** Both readers require exactly two
declared named graphs, each with a **positive** `quadCount`
(`vocabulary_atlas.py:361-376`, `model.py:2306-2320`), and require the file's
non-empty named-graph set to equal the declared one
(`vocabulary_atlas.py:403-406`). Dropping the analysis graph refuses on both
sides. Its 82.5 MB is listed because it bounds the release-facts half, not
because it can ship. It would also drop `atlas:memberOfRelease`, which every
`contains_member` call needs.

The graph split on the full three-vocabulary build: analysis 620,161 quads /
194,220,102 bytes (70.2%), releaseFacts 309,166 quads / 82,461,672 bytes
(29.8%).

### The consumer projection, and what it drops

`consumer-projection` is the smallest distribution satisfying every read
enumerated above. Its keep rule, in full:

- **releaseFacts**: `prov:hadMember`; `rkaf:referenceReleaseDigest`;
  `skos:related`; `rdf:type` **only** where the object is
  `rkaf:ReferenceResourceRelease`; `skos:prefLabel` and `skos:altLabel` **only**
  on subjects that are release members.
- **analysis**: `atlas:memberOfRelease`; every quad whose subject is in the
  closure of a qualified mapping (the mapping, its candidate, its two
  validations, and every artifact any of them names).

Kept — 239,316 quads, 61,900,562 bytes:

| Graph | Predicate | Quads | Bytes |
|---|---|---:|---:|
| releaseFacts | `skos:prefLabel` | 107,246 | 26,659,577 |
| releaseFacts | `skos:altLabel` | 74,316 | 18,444,611 |
| releaseFacts | `skos:related` | 27,147 | 7,852,316 |
| analysis | `atlas:memberOfRelease` | 11,370 | 3,281,710 |
| releaseFacts | `prov:hadMember` | 11,370 | 3,077,050 |
| analysis | `rdf:type` (mapping closure) | 1,087 | 346,999 |
| analysis | the 35 remaining mapping/candidate/validation/artifact predicates | 6,772 | 2,235,947 |
| releaseFacts | `rdf:type rkaf:ReferenceResourceRelease` (4) + `rkaf:referenceReleaseDigest` (4) | 8 | 2,352 |

Dropped — 690,011 quads, 214,781,212 bytes (77.6% of the file):

| Graph | Predicate | Quads | Bytes | Why |
|---|---|---:|---:|---|
| analysis | `atlas:member` | 199,493 | 65,630,642 | label clusters — validated at open, read by nothing |
| analysis | `atlas:memberRelease` | 195,447 | 58,549,818 | same |
| analysis | `rdf:type` | 98,790 | 31,323,254 | 96,958 cluster typings plus the refused candidates' own |
| analysis | `atlas:normalizedLabel` | 96,958 | 29,469,992 | same |
| releaseFacts | `skos:definition` | 17,642 | 6,324,147 | never read |
| releaseFacts | `rdf:type` (concepts, schemes) | 11,397 | 3,100,126 | never read |
| releaseFacts | `skos:inScheme` | 11,370 | 3,000,870 | never read |
| releaseFacts | `skos:narrower` | 8,513 | 2,477,283 | no accessor exists |
| releaseFacts | `skos:broader` | 8,513 | 2,468,770 | no accessor exists |
| releaseFacts | `skos:historyNote` | 7,702 | 2,268,060 | never read |
| releaseFacts | `owl:priorVersion` | 6,846 | 1,978,350 | never read |
| releaseFacts | `dcterms:isVersionOf` | 6,876 | 1,931,888 | never read |
| releaseFacts | `skos:scopeNote` | 4,035 | 1,335,139 | never read |
| releaseFacts | `skos:notation` | 3,760 | 868,560 | never read (ICPSR publisher codes) |
| analysis | the refused candidates' own artifacts and validations | 10,244 | 3,381,740 | 244 of 365 candidates did not qualify; the consumer reads only the 121 that did |
| releaseFacts | 68 further predicates — `atlas:thesaurusUse`/`UsedFor`, `skos:hasTopConcept`/`topConceptOf`, `xkos:`, `owl:deprecated`, every release-node `rkaf:` lifecycle statement | 2,425 | 672,573 | never read |

**Proven read-equivalent, not argued.** The real
`spicysearch/vocabulary_atlas.py` (copied unmodified,
`sha256:5f96c2419d2bcfd4759aa6fa30ea1af088e6989621ab348146f69550c7683d22`) was
run against the full three-vocabulary distribution and against its projection.
Every consumer-visible result is identical:

| | full | consumer projection |
|---|---|---|
| `concept_labels()` rows / digest | 181,562 / `f31f8ab6a093ae00` | 181,562 / `f31f8ab6a093ae00` |
| `related_pairs()` rows / digest | 27,147 / `d19f0fda97cbbd4d` | 27,147 / `d19f0fda97cbbd4d` |
| `search_only_mappings()` rows / digest | 121 / `31e7f007b6af2239` | 121 / `31e7f007b6af2239` |
| `member_ids()` FR / ELSST R6 | 705 / 3,470 | 705 / 3,470 |
| `rulespec_core_pin()` | identical | identical |
| `label_clusters()` | 96,958 | 0 |
| open wall time / peak RSS | 28.8 s / 4.48 GB | 6.7 s / 1.03 GB |

The FR + ELSST + crosswalk pair gives the same answer: 177,802 /
`450447ae7201fd57`, 12,787 / `b8194a2425b887bb`, 121 / `31e7f007b6af2239` on
both sides, 28.1 s / 4.29 GB against 6.3 s / 907 MB.

The only difference is the one thing no product code reads. (The 31 dropped
`skos:prefLabel` quads are concept schemes labelling themselves, which
`concept_labels()` already filters at `:570` — hence the identical digest.)

The open cost matters on its own: the engine opens the pinned atlas per engine
instance on the first concept query (`engine.py:1831-1836`), and every snapshot
build and re-verify opens it too. 4.48 GB of resident memory to answer a label
lookup is a product constraint, not a storage one.

## The ELSST double-edition question

**The 121 qualified mappings reference R6 only.** All 365 candidates in the
crosswalk bundle name `sourceRelease`
`urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1`
and `targetRelease` `https://elsst.cessda.eu/id/6`; every `targetMember` IRI is
under `https://elsst.cessda.eu/id/6/`. R5 is named by zero candidates, zero
validations and zero mappings. The pilot was FR × ELSST R6 and the bundle says
so.

R5's cost, measured as a derived projection over the built distribution —
drop every quad naming `https://elsst.cessda.eu/id/5` or a concept beneath it,
then drop label clusters that no longer cross two releases:

| | full three-vocabulary | ELSST R6 only (derived) | change |
|---|---:|---:|---:|
| `atlas.nq` bytes | 276,681,774 | 58,492,923 | **−78.9%** |
| gzip -9 | 17,496,208 | 3,849,189 | −78.0% |
| quads | 929,327 | 210,931 | −77.3% |
| **label clusters** | **96,958** | **1,461** | **−98.5%** |
| members | 11,370 | 7,935 | −3,435 |
| qualified mappings | 121 | 121 | unchanged |
| consumer projection of it | 61,900,562 | 36,712,651 | −40.7% |

334,390 of 929,327 quads name R5 or a concept beneath it. Removing them kills
95,497 of the 96,958 label clusters — **the two-edition bundle is the single
largest cost in the whole distribution, larger than any vocabulary.** The 1,461
that survive are the genuinely cross-vocabulary ones: FR ∪ ELSST R6 ∪ ICPSR
sharing a normalized label. The corresponding FR + ELSST-R6 + crosswalk figure,
without ICPSR, is 279 clusters — so ICPSR contributes 1,182 of the 1,461 real
cross-vocabulary clusters, against the 91 it appeared to contribute when R5's
self-clusters dominated the count.

**Is R6-only lossless for current consumers?** For every read enumerated above,
yes, with one qualification and one caveat.

- Nothing a consumer reads needs R5. `contains_member` and
  `reference_release_pin` are called with the release the ExtrapolationRelease
  pins (`snapshot.py:1188-1196`, `:1261-1267`) — the Federal Register release.
  `search_only_mappings` returns R6 targets. `concept_labels` and `related`
  are vocabulary-wide, so **R5's labels and related-edges do disappear from
  the query-side index** — but nothing routes to them: FR is the only source
  vocabulary any assignment uses, and no mapping reaches R5.
- The qualification: R6's 3,423 `owl:priorVersion` statements point at R5
  concepts, so an R6-only distribution states a prior version it does not
  describe. That is already the normal case — R5's own 3,423 point at ELSST
  **R4**, which no atlas has ever contained. No consumer reads the predicate at
  all; a future edition-aware one would be reading a dangling edge either way.
- The caveat, **since closed**: when this was written no R6-only ELSST bundle
  existed — `elsst-r5-r6-final-gate/test_opt_in_full_r5_r6_managed{0,current}`
  are the same directory, the second being a symlink to the first, so the
  "two byte-identical bundles" were one bundle. The numbers above were what an
  R6-only build would contain, computed from the two-edition build. One now
  exists: bundle manifest `sha256:e20928a6…`, built in RefSpec by the ELSST
  importer from the R6 distribution alone, 3,470 members over one release, its
  own combined Rulespec receipt. The atlas over it is 45,066,321 bytes with 365
  candidates, 121 qualified mappings and an identical qualified set. It was not
  SpicyRegs-side work: the importer lives here and only ever needed the source
  bytes.

## Integrity consequences, per option

A projection is a derived artifact. What can a consumer still prove?

**What survives in every option.** The consumer's three-part pin
(`snapshot.py:406-417`), the manifest's `canonicalPayloadDigest`, the
`output.digest`/`byteLength` self-description, the canonical-N-Quads byte
comparison (`vocabulary_atlas.py:401`), the count re-derivation, the
membership/cluster/mapping fail-closed passes, and the generation-digest→asset-id
derivation. A consumer can still prove it received exactly the bytes whose
digest it pinned, and that those bytes are internally closed.

**What does not survive, and this is the load-bearing part.** A consumer cannot
prove the bytes are *what the producer generated*, because nothing in the
manifest distinguishes a projection from a full generation. `generationDigest`
covers inputs, implementation and policies — all identical between a generation
and any subset of it. There is no `derivedFrom`, no parent digest, no
projection-policy field. Executed: both files open under the producer's own
validator with the same asset id.

**`reproduce_from_inputs` breaks. Executed, not argued.** `model.py:2424-2460`
reopens the distribution, rebuilds it from the pinned managed releases and
compares `rebuilt.payload != opened.payload`. Run against a freshly built
Federal-Register-only atlas and against its consumer projection, from the same
pinned bundle and Rulespec Core:

```
fr-fresh              -> reproduce_from_inputs: PASSES
projection-fr-fresh   -> VocabularyAtlasError: atlas files do not reproduce from the exact pinned inputs
```

The projection fails with the message reserved for a corrupted atlas. Nothing
in SpicySearch calls it, but it is RefSpec's own guarantee that an atlas is a
pure function of its inputs, and a projection is outside it. That is the
property a projection format has to restore, not a check to relax.

**Manifest counts.** They do not break — they are re-derived from the payload
on both sides, so a projection whose counts describe the projection is
consistent. But they then describe the projection rather than the generation:
`labelClusters: 0` is a true statement about a file that came from a generation
with 96,958. Nothing records the difference.

**Conformance fixtures.** The nine generator-built fixtures, since removed with the
Atlas 1.0 binding, were produced by
`tools/generate_atlas_conformance_fixtures.py` and pin the generator's own
source modules; a projection is not generated by that path, so no existing case
covers one and none breaks. A projection format would need its own cases —
minimally: a projection that drops a fact the consumer reads must refuse, and a
projection claiming an unrelated parent must refuse.

**Is a projection expressible under binding 1.0?** As bytes, yes — proven, it
opens. As a *distinguishable artifact*, no. Making it one is an amendment, and
the smallest honest shape is three fields:

1. a `derivedFrom` block naming the parent asset id, manifest digest and
   distribution digest — so the projection's identity is a function of the
   parent's identity rather than a copy of it;
2. a `projection` policy naming the exact keep rule and its version — so
   "what was dropped" is a pinned, testable statement rather than a diff;
3. an asset id derived from `{generationDigest, projectionPolicy, derivedFrom}`
   so a projection can never collide with its parent.

Plus, on the consumer side and independent of any of this, the one-field
`_COUNT_FIELDS` amendment from finding 1. Without it no atlas containing
hierarchy is consumable at all.

**What each of the three options needs.**

| Option | Format work | Integrity a consumer keeps | Integrity a consumer loses |
|---|---|---|---|
| Vendor a projection | none to *ship* a hierarchy-free one; the `derivedFrom`/`projection`/id amendment to make it honest; `_COUNT_FIELDS` for hierarchy | byte-exact pin, internal closure, re-derived counts, every accessor result | provable "this is what the producer generated"; `reproduce_from_inputs` |
| Publish a pointer | none to the atlas format; a pointer contract, plus the retention/readback/GC gaps recorded in the handoff; `_COUNT_FIELDS` before any hierarchy-bearing atlas resolves | everything the full asset has, if the fetched bytes match the pinned digests | nothing, once the fetch is digest-verified — the exposure moves to fetch-time availability and to the flip |
| Fetch a release artifact | same as pointer, plus a fetch path SpicySearch does not have | same as pointer | same as pointer, plus the first network dependency in a repository that has none |

Neither pointer publishing nor artifact fetching touches the atlas format.
Both require SpicySearch to grow a remote read path it does not have, and both
still need `_COUNT_FIELDS` before they can resolve anything carrying hierarchy.
Vendoring a projection requires no network at all, ships today in its
hierarchy-free form, and buys a 4.5× reduction — at the cost of shipping a
derived artifact the format cannot yet name as one.

**One option is dominated, and it is worth saying so.** Vendoring the *full*
three-vocabulary atlas is strictly worse than vendoring its consumer projection
on every axis measured: same asset id, identical accessor results, **4.47× the
bytes** (276,681,774 against 61,900,562), **5.00× gzipped**, **4.3× the open
time** (28.8 s against 6.7 s), **4.3× the resident memory** (4.48 GB against
1.03 GB) — and it does not open at all, while the projection does. The one
thing the full file carries that the projection does not is 96,958 label
clusters, which the consumer validates and never reads. That is a measurement,
not a recommendation — it says nothing about projection-versus-pointer, and
pointer publishing can ship either file.

**And a hierarchy-free projection needs no amendment to ship.** Because it
carries no `skos:broader`, it declares no `hierarchyEdges`, so finding 1 never
fires: the three-vocabulary consumer projection was **admitted by both readers,
executed** — `VocabularyAtlas.open` and `VocabularyAtlasAsset.open`. What it
needs an amendment for is *honesty about being a projection*, not admission.
Hierarchy is the opposite case: it cannot ship in any shape until
`_COUNT_FIELDS` moves.

## Reproducing

The builds are machine-local under `output/atlas-scratch/` (gitignored) and
rebuild from the pinned digests in
[`research/evidence/atlas-distribution-2026-08-02/`](../research/evidence/atlas-distribution-2026-08-02/README.md),
which also carries the structured measurements. The projection and measurement
scripts are scratch tooling, not products; the evidence record states exactly
what each one did.

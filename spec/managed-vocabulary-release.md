<!-- markdownlint-disable MD013 -->

# RefSpec Managed Vocabulary Release Decision Record

- **Status:** Decision record — retired design, superseded in place
- **Version:** 0.1.0-draft, imported unchanged
- **Date:** 2026-07-31
- **Release status:** Unreleased; never published

> **What this document is.** It is imported verbatim from the retired standalone RefSpec
> checkout at commit `210d671` and is retained as the recorded reasoning behind decisions
> [REF-001 through REF-006](../docs/decisions.md). **It is not a normative specification and
> it does not describe the implemented release model.**
>
> **The implemented model is `ManagedVocabularyBundle` plus `VocabularyAtlasAsset`.** The
> active consumer format is the
> [Vocabulary Atlas Distribution 2.0 binding](../bindings/atlas/2.0/README.md). The
> implementation is [`src/refspec/atlas/`](../src/refspec/atlas) and
> [`src/refspec/managed_release.py`](../src/refspec/managed_release.py).
>
> **What was retired.** The compact `VocabularyRelease` object, the release digest taken over
> that object, the `urn:refspec:vocabulary-release:<hex>` identifier, the required root-section
> shape in section 4, and the `SourceTermResolution`, `AgentValidationReceipt`, and
> `BaselineValidationReceipt` records were retired by the
> [product-boundary and atlas reconciliation plan](../plans/2026-07-31-refspec-product-boundary-and-atlas-reconciliation-plan.md).
> Nothing in this repository implements any of them. Sections 3, 4, 5, 6, 9, and 10 carry
> their own historical banners; sections 7 and 8 record what survived and what changed.
>
> Nothing is deleted. The boundary, source-identity, atlas, and Federal Register reasoning
> below is the context in which REF-001…REF-006 were decided.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**,
**RECOMMENDED**, **MAY**, and **OPTIONAL** express requirement levels as
defined by BCP 14 when they appear in capitals.

This independent project draft is not a W3C standard and does not imply W3C
endorsement. The repository has no selected license.

## 1. Purpose

> **The boundary below is current; the record name is not.** Sections 1 and 2 state the
> product boundary REF-001 decided, and that boundary still holds. Read `VocabularyRelease`
> here as "the managed vocabulary release": the implemented release unit is the
> `ManagedVocabularyBundle`, not the compact object section 4 defines.

RefSpec publishes evidence-backed, managed ontology and vocabulary releases
and deterministic cross-vocabulary atlas assets. It gives downstream products
exact concept sets, stable identifiers, source coverage, explicit source-term
resolutions, qualified mapping candidates, and validation receipts.

RefSpec owns the operational `VocabularyRelease` and `VocabularyAtlasAsset`.
Rulespec Core owns the portable `ReferenceResourceRelease` shape and the
meaning of its complete membership. External publishers remain authoritative
for their distributions and native semantics.

## 2. Product boundary

RefSpec accepts vocabulary distributions, source-specific term keys, mapping
evidence, and a pinned Rulespec Core fixture. It captures or imports vocabulary
content, applies a versioned resolution policy, validates the resulting graph,
and publishes an immutable release.

RefSpec publishes:

- managed concepts, labels, hierarchy, mappings, and redirects;
- one exact and complete Rulespec Core reference release;
- source-term resolutions and their evidence;
- baseline-validation receipts and supporting records; and
- vocabulary coverage and known exclusions; and
- deterministic, query-ready cross-vocabulary atlas assets.

RefSpec excludes:

- document acquisition, document versions, passages, and observation capture;
- a general evidence framework or a redefinition of Rulespec Core;
- extrapolation execution and derived document assertions; and
- document candidate generation, live search indexes, ranking, and result
  serving.

API Topics from the Federal Register enter RefSpec only through a complete
`SourceTermKey`. SpicyRegs owns the corresponding source observation and its
capture history. A resolution never converts that observation into a concept
or a Rulespec assignment.

## 3. Canonical JSON and identity

> **Historical — retired shape.** The `VocabularyRelease.release_digest` rule and the
> `urn:refspec:vocabulary-release:<hex>` identifier below have no implementation. The
> implemented canonical profile lives in [`src/refspec/storage.py`](../src/refspec/storage.py)
> and [`src/refspec/binding.py`](../src/refspec/binding.py) and is stricter than the four
> settings below: REF canonical JSON also rejects `null`, floating-point numbers, duplicate
> keys, and integers outside the interoperable range. The published identifier is
> `urn:ref:vocabulary-atlas:<generation hex>`.

Implementations MUST serialize canonical JSON as UTF-8 with these settings:

```text
sort_keys = true
separators = (",", ":")
ensure_ascii = false
allow_nan = false
```

The `VocabularyRelease.release_digest` is the SHA-256 digest of the canonical
release object after omitting only the root `release_id` and `release_digest`.
The identifier is:

```text
urn:refspec:vocabulary-release:<release-digest-hex>
```

Other immutable operational records hash their identity-defining fields with
the same canonical JSON profile. Their identifiers append the digest hex to
the record-type prefix. Validation MUST recompute each nested digest and
identifier; recomputing only the outer release digest cannot legitimize a
tampered nested record.

## 4. VocabularyRelease

> **Historical — retired shape.** No code constructs, validates, or reads a
> `VocabularyRelease`. The implemented release unit is the closed multi-file managed bundle
> opened by `ManagedReleaseView.open`, and the atlas builds from those bundles. Subsections
> 4.1 and 4.2 are kept as the Rulespec Core projection and coverage reasoning behind REF-002
> and REF-004; the complete-membership and coverage rules they state are implemented against
> the managed bundle, not against the object below.

A release contains these required sections:

```text
VocabularyRelease
  schema_version
  release_id
  release_digest
  vocabulary
  source_fixture_pin
  rulespec_core_fixture
  rulespec_core_release
  reference_resource_release
  concepts[]
  labels[]
  hierarchy[]
  mappings[]
  redirects[]
  source_term_keys[]
  source_term_resolutions[]
  support_records[]
  agent_validation_receipts[]
  baseline_validation_receipts[]
  resolution_policy
  coverage
```

The release MUST pin its source fixture and Rulespec Core fixture by digest.
It MUST also expose a top-level `rulespec_core_release` object containing
exactly `release_id` and `release_digest`. A build MUST use the local fixtures.
It MUST NOT depend on another repository checkout or a mutable database.

### 4.1 Rulespec Core projection

Every `VocabularyRelease` MUST expose one `ReferenceResourceRelease` that
conforms exactly to the pinned Rulespec Core fixture. Its
`rkaf:membershipMode` MUST equal `rkaf:completeMembership`.
`prov:hadMember` MUST contain every published `concept_id` exactly once and no
other identifier. The projection identifies the managed scheme and version,
pins one immutable vocabulary-content distribution, and carries the required
`rkaf:referenceReleaseDigest`. RefSpec computes that digest over the closed
manifest as Rulespec specifies: RDFC-1.0 canonical N-Quads followed by SHA-256.

RefSpec copies the portable shape; it does not redefine it. Consumers can
therefore validate a concept assignment against the Rulespec release without
loading RefSpec's operational manifest.

The package contains an exact copy of `rulespec-core-release-m2.json` with
release identifier
`urn:rulespec:core:5ac6ba59929eca874ec603cab0e90f7b15ab1a008b394cec5aefebdafe22564b`.
It also contains exact copies of that release's `ReferenceResourceRelease`
schema and positive digest vector. Its declared status is `fixture`. A
published Rulespec Core release must replace this conformance artifact before
production publication.

### 4.2 VocabularyCoverage

`VocabularyCoverage` records the complete source concept count, the published
concept count, source locators included in the managed release, source-term
resolution counts, and excluded scope. A partial fixture MUST say that it is
partial. Complete Rulespec membership means complete membership in that
managed release, not complete publication of every concept in the external
source.

## 5. Source-term identity and resolution

> **Historical — retired shape.** `SourceTermResolution` has no implementation, and no record
> in this repository carries a `resolution_digest`. The `SourceTermKey` identity rule and the
> fail-closed "a missing resolution fails closed" rule remain the recorded reasoning for
> REF-003. The packaged Federal Register release expresses the same distinction through its
> own recognized-variant and open-term-pattern records.

RefSpec resolves an exact source key:

```text
SourceTermKey
  key_id
  key_digest
  source_system_and_profile_version
  observation_kind
  source_native_path
  raw_value
  language
  source_context_discriminator?
```

Changing the source profile, field, path, raw value, language, or declared
context creates a different key. Label normalization does not change this
identity.

Every key in a release MUST have exactly one `SourceTermResolution`:

```text
SourceTermResolution
  resolution_id
  resolution_digest
  source_term_key_ref
  resolution_status
  policy_and_version
  reason
  target_concept_and_release?
  evidence_refs[]
  baseline_validation_receipt_ref
  optional_review_refs[]
```

The status controls target cardinality:

| Status | Target | Meaning |
| --- | --- | --- |
| `officialTerm` | Exactly one concept in the pinned release | The value is an official source term. |
| `recognizedVariant` | Exactly one concept in the pinned release | Publisher evidence supports the value as a variant. |
| `sourceLocalOpenTerm` | None | Preserve the source-authored open term without minting a concept. |
| `unresolved` | None | Evidence cannot support one target. |

A missing resolution fails closed. Label equality, normalization, embedding
similarity, or graph proximity cannot mint a concept, mapping, or resolution.

## 6. Validation receipts

> **Historical — retired shape.** `AgentValidationReceipt` and `BaselineValidationReceipt`
> have no implementation. The implemented qualification record is the pair of independent
> atlas `MachineValidation` records that can support a typed machine-proof adapter;
> the active distribution rules are in the
> [Atlas 2.0 binding](../bindings/atlas/2.0/README.md). This section is the recorded reasoning
> for REF-005: machine-first qualification with no human approval gate.

An `AgentValidationReceipt` records one immutable validator attempt. It pins
the target, sealed input manifest, request, model or agent identity, response
or failure artifact, per-check outcomes, evidence, timestamps, and independence
group.

A completed attempt requires a response artifact and an overall
recommendation. A failed attempt requires a failure reason and forbids both a
response artifact and recommendation. A retry creates a new attempt.

A `BaselineValidationReceipt` reduces deterministic checks and independent
agent attempts for one exact target. A baseline marked usable requires at least
two completed attempts from distinct independence groups. The aggregate result
is one of:

- `usable_for_search`;
- `usable_with_nonblocking_limits`;
- `deferred`; or
- `failed`.

These receipts qualify a release for candidate use under the named policy.
They do not establish semantic truth, approve each downstream assignment, or
require human approval. Optional human review remains a separate referenced
record.

## 7. Vocabulary atlas static asset

> **Implemented by Atlas 2.0.** `VocabularyAtlasAsset` consumes one exact
> `PinnedVocabularyAtlasScope` over source or managed concept releases and typed relation
> bundles. The active three-file rules are the
> [Vocabulary Atlas Distribution 2.0 binding](../bindings/atlas/2.0/README.md); where this
> historical section and that binding disagree, the binding governs.

A `VocabularyAtlasAsset` is a separate immutable publication from each input
`VocabularyRelease`. It is a crosswalk and deterministic lookup representation;
it is not another source vocabulary, a mutable graph database, or a document
search service.

An atlas manifest MUST pin:

- every input vocabulary release by `release_id`, canonical release digest,
  and source-file byte digest;
- the exact mapping-candidate input and its byte digest;
- the candidate-selection policy and version;
- the generator implementation files and their byte digests; and
- every data distribution by media type, byte length, and SHA-256 digest.

The canonical atlas identifier is content-derived:

```text
urn:refspec:vocabulary-atlas:<atlas-digest-hex>
```

The canonical manifest itself MUST be pinned externally by SHA-256 when copied
to a consumer. A reader MUST verify that pin, the canonical manifest bytes, the
asset and graph identities, the static distribution digest and length, graph
and semantic counts, input-pin statements, and exactly two named graphs before
exposing lookup queries.

The atlas MUST publish canonical JSON for its manifest and deterministic,
blank-node-free N-Quads containing exactly two named graphs: one graph for
facts copied from the pinned vocabulary releases and one graph for replaceable
cross-vocabulary mapping candidates. Rebuilding from identical pinned inputs,
policy, and implementation MUST produce identical bytes, counts, digests, and
identifiers.

A mapping candidate MUST name concepts in the pinned input releases and MUST
carry its origin, model and prompt lineage, verification state, disposition,
evidence, policy, and validation receipt. Any emitted Rulespec
`ConceptMapping` and `AILineage` MUST conform to the pinned Rulespec Core
shapes and point to the nested complete `ReferenceResourceRelease` identifiers,
not the outer operational RefSpec release identifiers. Label equality,
normalization, embedding similarity, or graph proximity MAY seed a candidate
but MUST NOT mint `skos:exactMatch`, an official source term, or
publisher-authored truth.

A model- or agent-generated candidate MAY receive `searchOnly` disposition
when its exact evidence and endpoint releases pass a pinned baseline validation
whose aggregate result is usable. It remains model-derived and unverified.
Human approval is not a prerequisite. Optional human feedback is append-only
input to a later atlas build; it MUST NOT mutate a published atlas or silently
change a candidate's eligibility.

RefSpec MAY expose read-only crosswalk and label lookup over the static asset.
It MUST NOT accept document queries, rank documents, or serve mutable atlas
state. A consumer such as SpicySearch MUST pin and verify the asset before use
and owns its own document-query planning and ranking.

Validation MUST fail closed when an input pin, implementation pin, output
digest, graph count, mapping endpoint, qualification record, or declared count
does not match the canonical asset.

## 8. Federal Register profile

> **Partly historical.** The default-candidate decision (REF-004) holds and is implemented.
> The last paragraph is not: the five-concept conformance fixture and its two agent receipts
> belong to the retired standalone line. This repository packages the complete 705-concept
> April 1, 2025 release. A canonical Atlas 2.0 publication selects it through an exact scope;
> the repository does not treat a checked Atlas output as a source-catalog input.

The April 1, 2025 Federal Register Thesaurus is the default candidate
vocabulary for the `federal-register-document-v1` profile. It is not RefSpec's
root ontology and does not become the default for unrelated sources.

The active profile excludes the 1995 vocabulary and any 1995-to-2025
crosswalk. Historical broad categories do not become `skos:broader`
relationships. Federal Register API Topics remain mutable source metadata;
the first-slice fixture represents one API Topic as an unresolved
`SourceTermKey` and publishes no document observation record.

The conformance fixture publishes five concepts from a 705-concept source and
includes positive Lists of Subjects examples for every resolution status. The
fixture's two independent agent receipts demonstrate the record and reduction
rules. They do not assert that a production release has passed validation.

## 9. Fail-closed validation

> **Historical — retired shape.** These conditions describe the retired `VocabularyRelease`
> validator, which does not exist here. The implemented fail-closed checks are the
> managed-bundle reader in [`src/refspec/managed_release.py`](../src/refspec/managed_release.py)
> and the atlas producer and reader in [`src/refspec/atlas/`](../src/refspec/atlas). The
> conditions that survived — nested digest recomputation, complete membership, closed
> reference resolution, and count agreement — are enforced there against the managed bundle
> and the atlas distribution.

A validator MUST reject a release when any of these conditions occurs:

- the outer or nested digest does not match canonical content;
- a content-derived identifier does not match its digest;
- the Rulespec Core fixture pin differs from the package-local pin;
- complete membership differs from the published concept set;
- a reference identifier or digest does not resolve inside the release;
- a source key has zero or multiple resolutions;
- a resolution uses an unknown status or invalid target cardinality;
- coverage counts differ from release contents;
- a usable baseline lacks two completed independent attempts; or
- the release contains document observation capture or search records.

## 10. Reproducible conformance build

> **Historical — these commands do not run in this repository.** They reproduce the retired
> standalone build and are kept only as its record. `refspec-build-federal-register-2025` is
> not a console script here, and there is no `release-records/` directory. The Atlas 1.0
> producer command is also retired. In this repository run `make test` and
> `make test-cross-repository`; Atlas 2.0 construction is programmatic through
> `build_vocabulary_atlas(pinned_scope)` until a pinned build-input file records the paths
> and trusted readers needed to reopen its inputs. Atlas 2.0 schemas live under
> [`bindings/atlas/2.0/`](../bindings/atlas/2.0/); generated source and index checks run through
> `make check-generated`.

Install the locked development environment, run the focused tests, and build
both canonical conformance publications:

```sh
uv sync --all-groups
uv run pytest -q
uv run refspec-build-federal-register-2025 \
  --output build/federal-register-2025-first-slice.json
uv run refspec-build-vocabulary-atlas \
  --release release-records/fixtures/refspec-vocabulary-release-federal-register-2025-first-slice.json=sha256:78f3937141f0a2152225a05ee4018c4ce92f49e77c1d97a6f07064754231bee8 \
  --output-directory build/vocabulary-atlas
```

Each command validates its publication before writing it. Identical pinned
inputs produce identical bytes, digests, and identifiers.

The repository pins the generated release and atlas under
`release-records/fixtures/`. Tests compare both publications byte-for-byte with
fresh builds.

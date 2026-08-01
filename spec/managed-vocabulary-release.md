<!-- markdownlint-disable MD013 -->

# RefSpec Managed Vocabulary Release Specification

- **Status:** Editor's draft with an implemented conformance slice
- **Version:** 0.1.0-draft
- **Date:** 2026-07-31
- **Release status:** Unreleased

> **Provenance:** This document is imported verbatim from the retired standalone RefSpec
> checkout at commit `210d671`. It is the current normative specification for RefSpec's
> managed-vocabulary product. Section 10's reproduction commands describe that retired
> build; in this repository use `make test` and `make test-cross-repository`, and build the
> atlas with `refspec-build-vocabulary-atlas`. Its release-record paths under
> `release-records/fixtures/` do not exist here.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**,
**RECOMMENDED**, **MAY**, and **OPTIONAL** express requirement levels as
defined by BCP 14 when they appear in capitals.

This independent project draft is not a W3C standard and does not imply W3C
endorsement. The repository has no selected license.

## 1. Purpose

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

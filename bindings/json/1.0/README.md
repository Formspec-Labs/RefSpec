<!-- markdownlint-disable MD013 -->

# REF JSON Binding 1.0

This binding serializes the REF-owned vocabulary-management, enrichment, and
evaluation records defined by RefSpec 1.0. It uses generated JSON Schema Draft
2020-12 for local record structure and one validator for cross-row,
cross-record, accounting, partition, and digest rules.

Rulespec records remain references. This binding does not copy the shape of a
Rulespec release, artifact, concept, mapping, assertion, attestation,
authority, evidence record, or adoption.

## Record schemas

The dispatch schema is
[`schemas/ref-record.schema.json`](schemas/ref-record.schema.json). It selects
one closed schema for each record:

- `Capture`;
- `RightsAssessment`;
- `RunReceipt`;
- `RegistryImportSnapshot`;
- `PublicationReleaseManifest`;
- `ConceptProposal`;
- `EnrichmentProfile`;
- `OutputProfile`;
- `RegistryImportCoverageReport`;
- `IndexedVocabularyExpression`;
- `RegistryReconciliationReport`;
- `RegistryDeploymentDecision`;
- `SealedGoldManifest`;
- `EnrichmentConfiguration`;
- `EnrichmentEvaluationResult`; and
- `EnrichmentDeploymentDecision`.

Every durable record carries the common `id`, `type`, `recordedAt`,
`recordedBy`, `schemaVersion`, and `operationalState` fields from
`REF-CORE-008`. Unknown fields fail validation. Optional fields are absent;
this binding forbids JSON `null`.

An identifier or semantic reference is an absolute IRI. An exact reference
adds the immutable version and/or digest required by the referenced record.
Those fields pin a Rulespec record; they do not duplicate its semantic shape.

## Canonical payload and digest

The algorithm identifier is `urn:ref:canonical-json:v1`. It matches the
reusable Spicy Regs canonical JSON function and applies these rules:

1. Parse UTF-8 JSON. Reject duplicate object keys, `NaN`, positive or negative
   infinity, and invalid UTF-8.
2. Reject `null`, floating-point JSON numbers, and integers outside
   `-9007199254740991` through `9007199254740991`. Fields that need a decimal
   use the canonical decimal-string grammar in `common.schema.json`.
3. Omit exactly one top-level digest field while hashing:
   `contentDigest` for `EnrichmentProfile` and `OutputProfile`, or
   `canonicalPayloadDigest` for every other record. A field with the same name
   below the top level remains in the payload.
4. Serialize with `ensure_ascii=false`, object keys sorted by Unicode code
   point, and separators `,` and `:` with no added whitespace. Preserve array
   order. Preserve Unicode code points exactly; do not normalize, case-fold,
   transliterate, or reduce text to ASCII.
5. Hash the resulting UTF-8 bytes with SHA-256 and encode the result as
   `sha256:` followed by 64 lowercase hexadecimal digits.

Array order is payload state even when an abstract field represents a set.
Producers must choose and preserve a stable order. Reordering an array changes
the digest.

Exact in-bundle digest references form a directed acyclic graph. A cycle could
not reach a stable set of content-addressed digests, so the validator rejects
one. The valid closure fixture uses this order: `EnrichmentProfile` →
`OutputProfile` → coverage and reconciliation → registry deployment →
configuration and sealed gold → evaluation → enrichment deployment.

## Executable rules

JSON Schema validates names, types, required fields, formats, conditional
fields, closed objects, and local cardinalities. The validator also:

- executes `format: uri` and `format: date-time` checks with a
  `FormatChecker`;
- verifies every record digest and indexed-text digest;
- requires one complete `OutputProfile` row to match, rejects duplicate
  selector tuples or accepted-output use without candidate use, and checks
  facet, role, route, release, and feature requirements against the exact
  enrichment and output profiles;
- balances source, parsed, indexed, excluded, and failed coverage counts and
  requires every coverage feature exactly once; a failed or incompatible
  report cannot authorize release or mapping use or registry selection;
- binds reconciliation differences to exact inputs and requires validated
  authority, attestation, and adoption before a resolved outcome;
- proves development and holdout separation for every item and all seven
  leakage dimensions using sealed item keys and evidence digests; alias keys
  include preferred, alternate, and hidden labels and compare after Unicode
  NFKC normalization, case folding, and whitespace collapse;
- enforces blind gold drafting, independent review, directional grades, and
  `notRepresented` routing;
- checks exact configuration, vocabulary universe, gold, evaluation,
  output-profile, registry-deployment, and enrichment-deployment digest pins,
  including validated governance references; and
- requires every gate and configured stratum to pass before a production
  selection can use a `pass` verdict.

`fixtures/valid/vocabulary-closure.json` contains the complete enrichment
closure example. The other positive fixtures cover the operational managed
release chain and concept-proposal workflow. Files under `fixtures/invalid/`
apply one named invalid mutation or permission claim. The
[`requirement-to-test manifest`](tests/requirement-to-test-manifest.json)
connects the new RefSpec requirements and `REF-TEST-150` through
`REF-TEST-184` to local fixtures, real-bundle consumer checks, and the
Rulespec checks that remain upstream. The current binding corpus contains 5
valid fixtures and 90 intentionally invalid conformance fixtures. Two
additional raw parser inputs exercise duplicate-key and non-finite-number
rejection; together with the requirement manifest, the installed package
embeds 98 conformance assets.

The authoritative structures live in
[`model/ref-records.cue`](../../../model/ref-records.cue). Run `make generate`
after changing that source. `make check-generated` rejects a hand-edited or
stale schema or Python type.

## Run the gate

From the RefSpec repository root:

```sh
make test-json-binding
```

To check every named upstream fixture and run the complete Rulespec gate
against a sibling working tree:

```sh
make test-rulespec-working-tree
```

That command proves the current trees agree, but it does not create or imply
an immutable dependency pin. A release candidate must use:

```sh
make test-cross-repository
```

The release gate also requires an exact vocabulary-closure version, committed
Rulespec revision, and recomputed constraint digest in the application
profile. It rejects a dirty Rulespec checkout or a missing, stale, or
placeholder pin.

The command uses `uv` with the exact dependency versions in
`requirements.txt`. To validate linked standalone records:

```sh
uv run --no-project \
  --with-requirements bindings/json/1.0/requirements.txt \
  python bindings/json/1.0/tools/validate.py \
  --record first.json --record second.json
```

To inspect one record's computed digest:

```sh
uv run --no-project \
  --with-requirements bindings/json/1.0/requirements.txt \
  python bindings/json/1.0/tools/validate.py --print-digest record.json
```

An installed editable package exposes the same validator as
`refspec-validate`. `refspec-release-graph-gate` validates a supplied REF
record set and exact Rulespec graph with their independently pinned validators,
then checks graph digests, receipts, covered identifiers, and cross-links.
With no arguments, `refspec-validate` runs the exact generated conformance
fixtures and requirement-to-test manifest embedded in the installed package;
it does not depend on checkout-relative files.

`--refresh-fixture` is a maintainer command for the self-contained valid
fixture. It follows the acyclic reference graph, updates indexed-text and
record digests, and rewrites that fixture. It must never be used to make an
intentionally invalid fixture pass.

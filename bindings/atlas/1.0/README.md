# RefSpec Vocabulary Atlas Distribution 1.0

This document defines the portable file boundary for
`refspec-vocabulary-atlas-nquads-1.0`. The Python publisher is one
implementation. The two files and the rules below are the consumer interface.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

## Distribution

A distribution contains exactly these required files:

- `atlas-manifest.json`, validated by
  [`schemas/vocabulary-atlas-manifest.schema.json`](schemas/vocabulary-atlas-manifest.schema.json); and
- `atlas.nq`, an N-Quads dataset with media type `application/n-quads`.

A consumer MUST receive independent `sha256:<64 lowercase hex>` pins for both
files. It MUST verify those pins before using any graph fact. The manifest is
canonical REF JSON: UTF-8, no duplicate keys, no `null`, no floating-point
numbers, integers within the interoperable JSON range, sorted object keys,
compact separators, and one terminal LF.

`canonicalPayloadDigest` is SHA-256 over the same canonical JSON object with
that field removed and without a terminal LF. `generationDigest` is SHA-256
over canonical JSON containing exactly `format`, `inputs`, `implementation`,
and `policies`. The atlas identifier is
`urn:ref:vocabulary-atlas:<generation hex>`.

Implementation provenance is producer-neutral. `sourceModules` names the exact
generator artifacts, and `runtime` is a non-empty map of producer-defined names
to exact version strings. Consumers MUST verify the declared shape and digests;
they MUST NOT require Python, RefSpec module paths, or this publisher's runtime
key names.

## N-Quads byte profile

`atlas.nq` MUST:

1. be valid UTF-8 N-Quads;
2. contain no default-graph statement and no blank node in any position;
3. use one statement per line, LF line endings, no blank lines or surrounding
   whitespace, lexicographically sorted statement lines, and one terminal LF;
4. contain exactly the two non-empty named graphs declared by the manifest;
   and
5. match every declared file, graph, and semantic count.

Because blank nodes are forbidden, consumers do not need an RDF dataset
canonicalization algorithm to compare identities. The exact published bytes,
not a parse-and-reserialize result, carry the external digest.

## Named graphs

The `releaseFacts` graph identifier MUST be `<atlas id>:release-facts`. It
contains only facts copied from verified managed releases. A member used by a
mapping MUST be the object of that release's `prov:hadMember` statement. Its
release MUST be an `rkaf:ReferenceResourceRelease` with exactly one lowercase
SHA-256 `rkaf:referenceReleaseDigest`. Every analysis
`atlas:memberOfRelease` statement MUST agree with that authoritative
release-to-member statement.

The `analysis` graph identifier MUST be `<atlas id>:analysis`. It MAY contain
replaceable label clusters, mapping candidates, machine validations, qualified
`searchOnly` mappings, and later feedback. An equal label is only a discovery
hint; it MUST NOT create a concept mapping by itself.

## `searchOnly` proof

Before exposing an `rkaf:ConceptMapping` whose eligibility is
`rkaf:searchOnly`, a consumer MUST verify all of these facts in the analysis
graph:

- exactly one source, relation, target, source release, target release, and
  qualifying candidate, plus exactly one eligibility value equal to
  `rkaf:searchOnly`;
- the mapping endpoints and relation exactly match that candidate;
- both endpoints belong to the claimed releases and occur in release facts;
- the relation is a supported SKOS mapping relation;
- origin is `rkaf:aiSuggested`, epistemic basis is
  `rkaf:statisticalInference`, and verification status is
  `atlas:machineQualifiedForSearch`;
- the candidate has at least one evidence artifact and the declared sealed
  input digest;
- the candidate names exactly one `atlas:inputContextArtifact`; that artifact
  is a crosswalk artifact whose `atlas:artifactRole` is `inputContext`, and its
  `atlas:contentDigest` equals the candidate's `atlas:inputContextDigest`; and
- exactly two supporting machine validations use that input and candidate,
  pass deterministic checks, resolve request and response artifacts, and have
  different validator actors, independence groups, providers, provider model
  identifiers, and response artifacts. Each machine validation and its sealed
  response MUST include the same non-empty `providerModelId`.

The input-context rule is what makes the rest of the proof about a mapping
rather than about a string. Every other check compares the candidate, the two
validations, and their sealed request and response to one another; all four
records can agree on an `inputContextDigest` whose bytes exist nowhere. A
producer MUST therefore place the exact model input in the bundle as an
`inputContext` artifact, and `inputContextDigest` MUST be SHA-256 over that
artifact's canonical `content` alone — not over the artifact record, which also
covers its role and media type.

These graph checks prove the integrity of the published projection. Publisher
reproduction is the stronger check: it also opens every managed release, the
Rulespec Core release, and the optional closed crosswalk bundle, then rebuilds
both files byte for byte. A producer MUST refuse to build a distribution whose
candidate input context does not resolve to exactly one bundled artifact.

### Amendment 2026-08-02: resolvable input context

`inputContext` joins `evidence`, `validationRequest`, and `validationResponse`
as an artifact role, and the two rules above are new. This amends 1.0 in place
rather than opening 1.1, matching how this binding has carried its other
refusal corrections. The amendment is compatible in the direction that matters:
no distribution the previous rules accepted *and* that carried a resolvable
model input becomes invalid, and every valid fixture published before this date
is byte-identical because none contained a mapping candidate. A distribution
that qualified a mapping while citing unobtainable input bytes was never
serving a consumer, and is now refused.

The specialized Federal Register producer computes the Core-defined closed
`ReferenceResourceRelease` preimage locally. That preimage permits only named
nodes, so its RDFC-1.0 form is canonical N-Quads line order. The producer pins
the calculation's source modules, Python version, and `rdflib` version in the
atlas identity; it does not execute an unrecorded Rulespec checkout.

## Conformance corpus

[`fixtures/corpus.json`](fixtures/corpus.json) lists portable valid and invalid
two-file distributions. A conforming reader MUST accept every valid case and
reject every invalid case without accessing a RefSpec checkout, producer
inputs, or a mutable service.

The corpus MUST contain at least one valid distribution that exercises the
`searchOnly` proof end to end; a corpus of refusals alone cannot distinguish a
correct reader from one that rejects everything.
`valid/qualified-search-only` is that case. It carries two mapping candidates,
three machine validations, one label cluster, and one qualified mapping: the
first candidate is qualified by two independent machines, and the second stays
`rkaf:notEligible` because a single machine validated it. The three
distributions derived from it — `invalid/missing-input-context`,
`invalid/tampered-input-context`, and `invalid/same-provider-model` — each
forge exactly one fact of that proof, so a reader that accepts any of them has
a locatable defect.

## Complete Federal Register example

[`examples/federal-register-thesaurus-2025/`](examples/federal-register-thesaurus-2025/)
contains a producer-generated distribution from the source-complete April 1,
2025 managed package. It contains 705 concepts and excludes the source PDF. The
example proves this format can publish the specialized package without creating
a second release foundation.

Its independent pins are:

- manifest:
  `sha256:956cab4f20477933ef015c2c87647ebb9cc40c4c68247a93b10dab8b113f60f1`;
- N-Quads:
  `sha256:8e1eaf2265874863981fe9322e0a0e286c01c43e598b091736b556ea424e830a`;
  and
- `ReferenceResourceRelease`:
  `urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1`
  with RDFC-1.0 digest
  `sha256:30742a82b3e268942aec713a02c5ae4264eadea36aa61b564ffc93eeecfd5fe6`.

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
- the mapping endpoints exactly match that candidate, and the mapping relation
  exactly matches the candidate's `atlas:adjudicatedRelation` when it states one
  and its `atlas:proposedRelation` otherwise (see the relation-adjudication
  amendment below);
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
  response MUST include the same non-empty `providerModelId`; and
- both of those validations resolve the **same** `atlas:requestArtifact`. Two
  machines that answered different requests are two answers to two questions,
  not a corroboration of one.

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

Machine-readable marker: `fixtures/corpus.json` carries `"amendments":
["2026-08-02"]`. A consumer holding pinned case digests from before this date
reads no such entry, which is how pre- and post-amendment 1.0 are told apart.
The digests of `invalid/same-provider-model` changed here, because its
candidate cited an input digest no bytes could produce and nothing short of
rebuilding it could exercise independence again.

`inputContext` joins `evidence`, `validationRequest`, and `validationResponse`
as an artifact role, and the two rules above are new. This amends 1.0 in place
rather than opening 1.1, matching how this binding has carried its other
refusal corrections. The precedent is
[`4021af1`](../../../docs/decisions.md), which bounded manifest integers in
place. (The commit introducing this amendment also cited `d48dd9e`; that is an
error preserved here rather than rewritten — `d48dd9e` corrected
`src/refspec/binding.py` and never touched `bindings/`, so it carries no
binding-amendment precedent.) The amendment is compatible in the direction
that matters:
no distribution the previous rules accepted *and* that carried a resolvable
model input becomes invalid, and every valid fixture published before this date
is byte-identical because none contained a mapping candidate. A distribution
that qualified a mapping while citing unobtainable input bytes was never
serving a consumer, and is now refused.

A specialized producer computes the Core-defined closed
`ReferenceResourceRelease` preimage locally. That preimage permits only named
nodes, so its RDFC-1.0 form is canonical N-Quads line order. The producer pins
the calculation's source modules, Python version, and `rdflib` version in the
atlas identity; it does not execute an unrecorded Rulespec checkout. There are
two such producers — the Federal Register 2025 package and the ICPSR subject
thesaurus — and they call one shared implementation, so two adapters cannot
drift into two answers for the same closed shape.

**Producer provenance is not a rule.** `sourceModules` names the generator's
own artifacts, so the generator-built fixture digests move whenever that list
does — including when a new specialized reader joins it, as the ICPSR reader
did on 2026-08-02. No rule in this document changed then, so `amendments`
gained no entry: a distribution valid under the current rules stays valid, and
the checked-in Federal Register example below is byte-identical because it is
opened rather than reproduced. A consumer pinning fixture digests re-fetches
them; a consumer validating against the rules does nothing.

### Amendment 2026-08-02-hierarchy: intra-scheme hierarchy

Machine-readable marker: `fixtures/corpus.json` carries `"2026-08-02-hierarchy"`
in `amendments`. Two amendments landed on the same day, so this one is named as
well as dated; a bare date could not tell a consumer which of the two a pinned
corpus predates. This amendment is **widening**: every distribution the
previous rules accepted is still valid, and the new count is declared only when
there is a hierarchy to count, so nothing gains a field for a hierarchy it does
not have. The four generator-built cases — `valid/qualified-search-only`,
`invalid/missing-input-context`, `invalid/tampered-input-context`, and
`invalid/same-provider-model` — still change digests, because an atlas
identifier pins the generator's source modules and this amendment edits them.
The six statically published cases and the complete Federal Register example
are byte-identical, and the example keeps the exact pins named above.

A source vocabulary's own hierarchy is a layer-1 release fact, not analysis, so
it rides in the `releaseFacts` graph with everything else copied from the
managed release. An edge runs from the narrower concept to the broader one as
`skos:broader`. A distribution MUST satisfy all of these:

- every `skos:broader` and `skos:narrower` statement in `releaseFacts` connects
  two IRIs;
- if `releaseFacts` states any `skos:narrower`, the two directions agree
  exactly: every `skos:broader` has its inverse `skos:narrower` and every
  `skos:narrower` has its inverse `skos:broader`;
- both endpoints of every `skos:broader` are members of one common release,
  proven by that release's `prov:hadMember` statements. A broader edge between
  releases is refused: that claim is what a qualified `searchOnly` mapping
  carries, and it MUST earn two independent machine validations rather than
  ride in as a copied fact; and
- no statement joins a concept to itself, and the edges contain no cycle.

**Both directions are retained.** A thesaurus asserts BT and NT deliberately —
ISO 25964 treats both as first-class, and SKOS declares them `owl:inverseOf`
rather than asking a reader to infer one from the other — and `releaseFacts` is
a copy, so nothing is dropped. What the rules above buy is that an edge is
*projected* from the broader direction alone, so a consumer's broader and
narrower reads cannot disagree with one another. The agreement check is what
makes that projection sound: the property is proven against the source rather
than assumed. ELSST is the case that matters — 6,754 broader and 6,754
narrower statements across R5 and R6, perfectly reciprocal, zero asymmetric
edges in either edition.

> **Trap.** A reader that answers "narrower" as `broader ∪ inverse(narrower)`
> *without* the agreement check silently absorbs whichever half the other
> direction denies. The agreement check is mandatory under any rule a future
> amendment might adopt, including one that admits narrower-only sources.

Cycles are refused rather than admitted and marked. SKOS permits them, but a
thesaurus that emits one has a defect rather than a meaning — nothing is
genuinely broader than itself — and the published data settles it: ELSST R5
(3,361 edges) and R6 (3,393 edges) are both strictly acyclic. Refusal also
makes every transitive read finite by construction.

Polyhierarchy is not refused and MUST NOT be assumed away. A concept MAY have
any number of broader concepts; ELSST R6 places 162 of its concepts under more
than one, and its deepest branch is 8 levels.

`counts.hierarchyEdges` is the number of `skos:broader` statements in
`releaseFacts`. It MUST be present and equal to that number when the graph
states a hierarchy, and MUST be absent when it states none. Absent and zero are
the same fact, so exactly one of them is a legal encoding.

### What `copiedManagedReleaseFactsOnly` actually permits

The `releaseFacts` policy says copied, and a reader is entitled to know exactly
which transformations a producer may apply between a managed release and the
published graph. There are two, and both repair the *value type* of a statement
the release already makes:

1. `prov:hadMember` values are written as IRIs. A compact source context leaves
   them as literals on a generic parse, and the verified view has already
   checked those exact release-to-member pairs.
2. `skos:broader` and `skos:narrower` values are written as IRIs on the same
   grounds, using the release's normalized `concept_relations` rows — which are
   the verified, byte-pinned form of exactly those edges.

Nothing else changes, and in particular **a normalized relation row cannot
introduce an edge**. If a row names an edge the release graph states nowhere, a
producer MUST refuse rather than add it: an edge no statement makes is an
assertion, not a copy. A row repairs how an existing statement writes its
object and does nothing else.

Note what this does *not* say. Admission of a `skos:broader` statement is
decided by the rules above — value type, common-release membership, agreement,
acyclicity — and **not** by finding a matching `concept_relations` row. The
release graph is the authority; a resource-valued broader statement the graph
makes is admitted whether or not a normalized row also covers it. The rows are
consulted only for the repair in (2).

### Amendment 2026-08-03-relation-adjudication: the adjudicated relation

Machine-readable marker: `fixtures/corpus.json` carries
`"2026-08-03-relation-adjudication"` in `amendments`. Every generated case
digest changed here, because the rule below changes what the analysis graph
carries and the implementation pin moves with it.

Until this amendment a machine validation answered one question — is
`skos:closeMatch` safe in both directions — so the candidate's
`atlas:proposedRelation` was both the hypothesis under test and the adjudicated
answer, and anchoring a mapping to it was exact. A validation may now instead
answer *which* relation holds. Two facts are new, both optional:

- `atlas:verdictRelation` on an `atlas:MachineValidation`, a literal drawn from
  `same`, `near_same`, `target_is_broader`, `target_is_narrower`, `related`,
  `unrelated`, `insufficient_evidence`; and
- `atlas:adjudicatedRelation` on an `atlas:MappingCandidate`, one IRI drawn from
  the supported SKOS mapping relations.

This amendment also states one rule that is **not** new to v2 and applies to
every `searchOnly` mapping: the qualifying validations MUST resolve the same
`atlas:requestArtifact` (added to the proof list above). It was always implied by
"multiple answers to one question" and is now written down, so a reader that
previously accepted a mapping whose validations answered different requests now
refuses it. No distribution this binding has published is affected.

A consumer MUST verify, for **every** mapping candidate:

- every supporting machine validation of that candidate either carries
  `atlas:verdictRelation` or none does — a distribution may not mix the two;
- where they carry one, those validations resolve the same
  `atlas:requestArtifact`, and their distinct verdicts agree under the lattice:
  `{same}` adjudicates
  `skos:exactMatch`; any subset of `{same, near_same}` adjudicates
  `skos:closeMatch`; `{target_is_broader}` adjudicates `skos:broadMatch`;
  `{target_is_narrower}` adjudicates `skos:narrowMatch`; `{related}` adjudicates
  `skos:relatedMatch`; every other set is a disagreement and adjudicates
  nothing;
- the candidate's `atlas:adjudicatedRelation` equals that adjudicated relation.
  A candidate whose verdicts adjudicate a relation and which states none MUST be
  refused — the check is owed by the *verdicts*, not by the producer choosing to
  publish an adjudication. Were it otherwise, omitting one statement would drop
  a mapping back onto the uniform `atlas:proposedRelation` and publish a
  `broadMatch` finding as a `closeMatch`;
- where the verdicts adjudicate nothing — a real disagreement — the candidate
  states no adjudicated relation and qualifies no mapping; and
- a candidate adjudicated `skos:relatedMatch` carries `rkaf:notEligible` and
  qualifies no `rkaf:ConceptMapping`. Two machines agreeing that a pair is
  associated is not a licence to substitute one for the other in search, so the
  relation is stated and the mapping withheld.

The lattice is universal, not existential: it folds *every* supporting verdict
on one question, so a third machine can never outvote a direction disagreement,
and a set that mixes `near_same` with a directional verdict qualifies nothing.
The mapping is emitted at the weakest claim any machine made, which is why
`same` together with `near_same` yields `closeMatch` — one machine declined to
claim identity, and `skos:exactMatch` is the only mapping relation whose
transitivity a consumer may rely on.

`atlas:proposedRelation` keeps its meaning unchanged and stays on every
candidate: it is the hypothesis the judge was tested against, held uniform so a
generator's per-class expectation never reaches the judge. It is no longer the
mapping's anchor when an adjudicated relation is present. The amendment is
compatible in the direction that matters: a distribution carrying neither new
fact is read exactly as before, and every previously valid distribution stays
valid, because none of them adjudicated a relation.

### Amendment 2026-08-04-complete-machine-support: retain the whole proof set

Machine-readable marker: `fixtures/corpus.json` carries
`"2026-08-04-complete-machine-support"` in `amendments`.

Qualification requires at least one independent pair, not exactly two
validations. The relation gate already folds every deterministic supporting
validation that answered the selected sealed question. A mapping MUST therefore
cite that complete support set through `atlas:qualifiedBy`; publishing only the
first independent pair would discard evidence that helped determine the
relation. The reader MUST reject missing, extra, untyped, or differently
questioned validation references.

`valid/qualified-three-machine-support` proves the widening rule with three
same-question supports. The former invalid fixture that rejected a third
validation has been retired.

### `atlas:reason` is an unverified convenience copy

An `atlas:MachineValidation` MAY carry `atlas:reason`, a literal holding the free
text the machine wrote, copied from its sealed `validationResponse` artifact and
truncated to 400 characters. It exists so a reader can see *why* a mapping
qualified or a candidate was refused without opening the crosswalk bundle.

It is **not** part of any proof and a consumer MUST NOT treat it as evidence.
Nothing in the distribution ties the literal to the response artifact it quotes;
only a producer reproducing the atlas from its exact inputs re-derives it. The
analysis graph is replaceable machine analysis by policy
(`policies.analysis = replaceableMachineAnalysis`), and this field is squarely
inside that. A consumer that needs the authoritative text MUST read the sealed
response artifact in the bundle.

The manifest's `policies.mappingEligibility` deliberately stays
`twoIndependentMachinesSearchOnly`. That field set is closed on both sides and
changing a value is a binding version bump, not an in-place amendment; the two
admission rules are told apart by the presence of these facts, and a producer's
own run receipt records which protocol it ran.

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
not implemented the binding and has a locatable defect.
`valid/qualified-three-machine-support` adds a third deterministic support to
the qualifying question and requires the mapping to retain all three validation
IRIs.

The same guard applies to hierarchy: four refusals prove nothing about a reader
that rejects every hierarchy. `valid/hierarchy` is the case that must pass. It
states four edges over four concepts in **both directions**, so the happy path
exercises the agreement check rather than only the absence of NT. Its shape is
one root, a two-step chain, and one concept under two parents, so a reader that
assumes a tree fails it while passing every other check.

`invalid/cross-scheme-broader`, `invalid/cyclic-broader`, and
`invalid/dangling-broader` each move exactly one edge, rewriting its
`skos:broader` and reciprocal `skos:narrower` together so the two directions
still agree and the rule under test is the only fact forged.
`invalid/disagreeing-narrower` is the one case that touches a single direction,
because a broken inverse is exactly what it forges. All four keep
`hierarchyEdges` at four on purpose: a forgery that added or dropped a broader
statement would fail on the declared count before a reader reached any
hierarchy rule at all.

## Sibling kind: `refspec-vocabulary-atlas-projection-nquads-1.0`

**This is not an amendment.** No rule above changes, `fixtures/corpus.json`
gains no `amendments` entry, and every distribution valid under the rules above
stays valid and byte-identical. A projection is a **different kind of file**
that happens to carry an atlas payload, and it is described here so a consumer
holding both can tell them apart.

A projection is a subset of exactly one generated atlas, chosen by a named
policy. Its manifest is
[`schemas/vocabulary-atlas-projection-manifest.schema.json`](schemas/vocabulary-atlas-projection-manifest.schema.json),
its `type` is `urn:ref:type:VocabularyAtlasProjectionManifest`, and its
identifier is `urn:ref:vocabulary-atlas-projection:<projection hex>` where
`projectionDigest` is SHA-256 over canonical JSON containing exactly `format`,
`derivedFrom`, `implementation`, and `projectionPolicy`. It uses the same two
file names and the same N-Quads byte profile.

Why a separate kind rather than three optional fields on the manifest above:

1. **The reproduction contract differs.** An atlas is a pure function of its
   managed releases, its Rulespec Core release and its optional crosswalk. A
   projection is a pure function of its parent distribution and its keep rule.
   One `type` cannot carry both answers to "prove these bytes are what the
   producer made" without one of them being false.
2. **This manifest's field set is closed on both sides.** A producer and a
   consumer each compare the key set for exact equality, so an *optional*
   `derivedFrom` does not exist. An amendment would have to mean "one of two
   field sets", which is a second kind wearing the first kind's name.
3. **Nothing published moves.** Because a projection is its own format with its
   own identity function, adding it changes no atlas identifier, no fixture
   digest, and no byte of the example below.

The defect this kind fixes, stated plainly: identity above is a digest of
`{format, inputs, implementation, policies}`, and a subset of a generation has
the *same* inputs, implementation and policies. So a projection and its parent
carried **one identifier**, both opened under the same reader, and publisher
reproduction refused the projection with the message reserved for a corrupted
atlas. A projection manifest states the relationship instead:

- `derivedFrom` names the parent's `assetId` and **both** of its file digests,
  so the relationship is published rather than inferred from whichever digest a
  consumer happened to pin;
- `projectionPolicy` carries the named keep rule and its version in full, so
  "what was dropped" is a pinned, testable statement rather than a diff; and
- the identifier is derived from all three, so a projection can never collide
  with its parent or with a projection of it under another policy.

A projection's two named graph IRIs are the **parent's**
(`<parent asset id>:release-facts` and `:analysis`), because its quads are the
parent's quads. A consumer MUST check that the declared graph IRIs are derived
from `derivedFrom.assetId`. Every declared count is re-derived from the
projection's own payload — `referenceReleases` replaces `managedReleases`,
because a projection has no `inputs` block to count and the number of
`rkaf:ReferenceResourceRelease` nodes is checkable from the bytes.

The published policy is
`urn:ref:policy:vocabulary-atlas-projection:consumer-read-closure` version `1`.
It keeps, in `releaseFacts`: `prov:hadMember`, `rkaf:referenceReleaseDigest`,
`skos:related`, `skos:broader`, `rdf:type` where the object is
`rkaf:ReferenceResourceRelease`, and `skos:prefLabel`/`skos:altLabel` on release
members. In `analysis`: `atlas:memberOfRelease`, and every statement whose
subject is in the closure of a qualified `searchOnly` mapping — the mapping, its
candidate, its two validations, and every artifact any of them names. A consumer
MUST refuse a projection naming a policy it does not implement, because a policy
it cannot read makes "what was dropped" unanswerable.

`skos:narrower` is dropped while `skos:broader` is kept. That is sound under
the hierarchy amendment above and only under it: an edge is projected from the
broader direction alone and a source stating both must have them agree, so the
surviving half is the whole fact.

## Sibling publication: relation-assertion SSSOM 1.0

The `relationAssertionSssomDistribution` package kind publishes a verified
relation-assertion bundle as `mappings.sssom.tsv`, `mapping-evidence.jsonl`, and
a manifest that seals both files to the exact bundle. This is a separate
publication from the N-Quads binding above. Its current scope is **subject and
value relations only**.

The publisher MUST refuse entity and `legalIdentity` bundles. Entity identity
links need merge-safe identity semantics, and legal-identity edges need their
own point-in-time edge profile; flattening either into the current SSSOM mapping
shape would discard meaning. The shared relation-assertion foundation still
accepts all four rings. This restriction applies only to the SSSOM publication.

For an accepted subject or value bundle, SSSOM rows are interoperability data,
not use permission. The evidence sidecar retains exact release pins, typed
evidence, mapping-assertion identity, machine-proof facts, and value-ring time
context. Product use still requires that sidecar and an exact product policy.

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

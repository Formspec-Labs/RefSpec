# Multidimensional vocabulary atlas experiment

Date: 2026-07-31

Status: Historical evidence for the pre-split v5 experiment. The current
RefSpec implementation retains only the vocabulary crosswalk and deterministic
static query asset. SpicyRegs remains responsible for source observations, and
SpicySearch remains responsible for document retrieval and related-document
ranking.

## Decision

Build one vocabulary atlas with two named graphs:

1. The asserted graph contains source-backed vocabulary releases, concepts,
   within-scheme relations, document metadata observations, explicit
   Lists-of-Subjects resolutions, accepted assignments, reviewed mappings, and
   explicit document links.
2. The analysis graph contains replaceable mapping candidates, tagging
   candidates, observation-to-concept comparisons, and candidate-relatedness
   policy.

The split marks authority, not data type. Metadata does not need its own graph.
The vocabulary scheme is not the root of every dimension.

The label itself is not multidimensional. A concept keeps its source identity,
release, scheme, labels, notes, and source hierarchy. Dimensions such as
subject, entity, genre, and legal location belong to the route, decision, or
source observation that uses the value.

## What goes in

- April 1, 2025 Federal Register Thesaurus as the strong-priority Federal
  Register candidate vocabulary.
- Current ICPSR and ELSST managed releases.
- Current CRS subject and policy-area observations.
- Current Federal Register API Topics.
- Current Lobbying Disclosure Act filing types and general issue codes.
- A sealed 24-document Federal Register evaluation slice and its exact
  Regulations.gov cross-posts.

The active atlas does not load the 1995 Federal Register vocabulary.

Every input has an externally selected SHA-256 digest. The atlas also retains
the normalized projection configuration and pins the projector implementation.

## What happens

### Vocabulary concepts

Each managed concept remains in exactly one selected release and source scheme.
`skos:broader`, `skos:narrower`, and `skos:related` remain source-internal
relations. Equal labels across schemes create analysis candidates, never
`skos:exactMatch`.

Neither a concept, release, nor scheme has an intrinsic semantic facet. A
`CandidateRoute` states that one release may propose one facet-role-resource
combination. A reviewed enrichment decision supplies the facet and role for an
accepted document assignment.

### Source metadata

Agency, document type, and Code of Federal Regulations references remain exact
`SourceControlObservation` records. Federal Register API Topics remain
`SourceTermObservation` records. They are filterable, but they do not become
SKOS concepts or accepted assignments.

Lists of Subjects use a separate explicit resolution record. Every List term
must resolve as one of:

- `officialTerm`
- `recognizedVariant`
- `sourceLocalOpenTerm`
- `unresolved`

Every resolution states its policy, reason, and `conceptMinted false`.
Official-term and recognized-variant results may create review-only assignment
candidates. The candidate links the exact resolution that authorized it.

### Mapping candidates

The experiments show that equal labels are useful for finding pairs but cannot
decide their relation. A mapping candidate therefore records both concepts,
both releases, the proposed relation, the generation method, and its validation
state. In the historical v5 graph, only a human editorial mapping entered the
asserted graph. The current RefSpec boundary does not make human review a search
gate: a model- or agent-generated mapping may qualify for `searchOnly` use after
deterministic checks and independent baseline validation. Later human feedback
is optional, append-only input to a future asset generation.

Embeddings should add ranking signals to this review queue, not create graph
truth. Use small, separate inputs:

- preferred and alternate label keywords;
- immediate parent keywords;
- immediate child keywords;
- definition or scope-note keywords when present.

Do not add scheme names, provenance prose, or serialized RDF to the embedding
text. Compare the signal scores separately so reviewers can see whether a pair
matches by label, local hierarchy, definition, or several signals.

### Document relatedness

Related-document results have three distinct meanings:

- `Linked`: an explicit cross-post or shared explicitly linked container;
- `LikelySameMatter`: at least two independent identity-signal families;
- `TopicallyRelated`: shared discriminative subject evidence.

Mutable API Topics may produce only candidate topical results. The query
returns the policy IRI and digest, effective threshold and source kinds,
generation digest, document population, term document count, frequency ratio,
and suppression decision.

In the sealed slice:

- `Meat inspection` occurs on 2 of 24 documents and connects Federal Register
  documents `2026-03227` and `2026-03228` as a candidate.
- `Reporting and recordkeeping requirements` occurs on 14 of 24 documents and
  is suppressed as non-discriminative.
- A one-hop `skos:related` edge is reserved for a future ranker. No current
  ranker consumes it, and it is not sufficient evidence for `TopicallyRelated`.

The `0.2` frequency cutoff is an interim candidate-generation setting. It is
not ontology truth and must pass a time- and matter-separated holdout before
production use.

## What comes out

- Deterministic, blank-node-free N-Quads.
- Exactly one asserted graph and one analysis graph.
- A manifest with graph counts, input pins, output digest, and reasoning
  disabled.
- The exact normalized projection configuration.
- Query surfaces for accepted tags, review-only candidates, exact source
  controls, exact mutable source terms, cross-vocabulary mappings, and related
  documents.

The graph contains no `owl:sameAs`, performs no RDF inference, and does not
materialize candidate document pairs as permanent ontology facts.

## How to check it

The acceptance gates are:

1. Recompute every input, configuration, projector, and output digest.
2. Confirm that only the two declared graph IRIs contain statements.
3. Reject facets on managed concepts, releases, and schemes.
4. Reject API Topic resolutions or assignments.
5. Require exactly one complete resolution for every Lists-of-Subjects
   observation.
6. Require complete enrichment-decision and asserted-graph evidence records
   before an assignment can query as accepted.
7. In historical v5 only, require complete editorial authority before labeling
   a mapping `reviewed`; this did not govern current `searchOnly` eligibility.
8. Verify the exact agency + genre + CFR filter and the exact API Topic filter
   on the real document slice.
9. Verify the positive `Meat inspection` candidate and the generic-topic hard
   negative.
10. Load and query the N-Quads in a disk-backed RDF store with inference and
    `owl:sameAs` disabled.

## Verified v5 artifact

The complete local v5 audited build in
`output/vocabulary-atlas/v5-audited/` produced:

- generation:
  `sha256:98be18402dae5d2f5bf4e1ef10abc0bfc7da65bd596994b56eda278e828459a3`;
- N-Quads:
  `217,984,426` bytes,
  `sha256:262aa72d724fd1c443f01b434b7963381a8f403453b6041d8386275ea8a204b1`;
- asserted graph: `613,202` statements;
- analysis graph: `41,212` statements;
- managed concepts: `7,935`;
- indexed vocabulary expressions: `17,204`;
- source observations: `9,114`;
- exact source controls: `102`;
- Lists-of-Subjects resolutions: `36`;
- review-only document assignments: `26`;
- accepted document assignments: `0`;
- equal-label mapping candidates: `1,151`;
- reviewed mappings: `0`;
- explicit Federal Register/Regulations.gov links: `24`.

The normalized projection configuration is `1,254` bytes with digest
`sha256:586d02ede7cf9a9fb836e3d6aff0967cc6395213e1478411f39b479cff9c69fc`.
The relatedness policy has its own canonical digest:
`sha256:0ab6828b2128c9e9d94d2650327e63abf1b8ba337de69c3a3a3615e44c4810ad`.

A disk-backed Oxigraph load reproduced both graph counts and answered the
source-control, API Topic, Lists-resolution, cross-post, and policy queries.
It found zero vocabulary-level facets, zero API Topic resolutions, and zero API
Topic assignments, including zero Topic nodes dual-typed as assignments. It
also found zero assignments from source-local Lists terms and zero resolution
nodes typed as SKOS concepts.

This proves standards-compatible RDF storage and SPARQL behavior. It does not
prove repository creation in Ontotext GraphDB itself: the available GraphDB
container requires a license. The GraphDB repository configuration parses and
sets an empty ruleset with `owl:sameAs` disabled; a licensed runtime smoke test
remains an operational gate.

## Production holdout

Freeze a multi-month Federal Register corpus. Put earlier months in calibration
and the next month in holdout, keeping each docket, RIN, and cross-post family
in only one split. Adjudicate at least 200 calibration and 200 holdout pairs
across rare exact terms, frequent terms, source-relation hops,
cross-vocabulary candidates, and hard negatives that share agency or CFR
metadata.

Compare:

- exact terms with frequency suppression;
- source-relation hops that require a second independent signal;
- reviewed cross-vocabulary mappings;
- sparse keyword embeddings over the small inputs above.

Lock thresholds before opening the holdout. Do not present a machine-generated
mapping as source or editorial truth. Baseline-qualified mappings may support
`searchOnly` use without human approval; broader use requires a separate,
explicit later decision.

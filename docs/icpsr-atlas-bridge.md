# ICPSR at the atlas door, 2026-08-02

The ICPSR subject thesaurus was the last vocabulary RefSpec could read but not
publish. This records what was measured, what the projection carries, what it
refuses to carry, and what the resulting bytes cost.

## The gap was a missing bridge, not missing data

ICPSR's reader has been production-grade since 2026-07-30:
[`src/refspec/registry/managed_releases/icpsr_managed_release.py`](../src/refspec/registry/managed_releases/icpsr_managed_release.py),
686 lines, 25 tests, sealed, digest-verified, `PARSER_VERSION =
"refspec-icpsr-managed-release-v1"`. What it emits is its own shape —
`MANAGED_RELEASE_VERSION = "icpsr-uri-verified-development-v1"`, self-marked
`operationalState: developmentOnly` — and `PinnedManagedRelease.open` requires
`bundleVersion: "1.0"`. The two share no manifest field, so every ICPSR concept
was refused at the door.

ELSST remains an independent source reader. RefSpec does not convert it into a
Rulespec release or publish it through the atlas. ICPSR uses a separate adapter
because its verified source package is an atlas input. The 1.0 bundle was never
the requirement: the atlas consumes `VerifiedManagedReleaseSource`, and
[`atlas/federal_register.py`](../src/refspec/atlas/federal_register.py) already
satisfies it from a package that declares its own manifest type and never
builds a 1.0 bundle at all. That adapter, not ELSST's 3,000 lines, is the
template. [`atlas/icpsr.py`](../src/refspec/atlas/icpsr.py) is the ICPSR
analogue, and the reader is untouched.

## What ICPSR actually states

Measured from the exact 2026-07-30 capture
(`output/refspec-vocabulary-portfolio/icpsr/2026-07-30/managed-release`,
manifest file digest
`sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a`)
before anything was designed. The capture joins 3,765 XML terms to 3,805 public
index terms and keeps the 3,760 whose term URIs verify in both.

| Fact | Count | Projected as |
|---|---:|---|
| concepts (URI-verified members) | 3,760 | `prov:hadMember` |
| preferred label role (public index) | 3,280 | `skos:prefLabel` |
| alternate label role (public index) | 480 | `skos:altLabel` |
| publisher code | 3,760 | `skos:notation` |
| scope notes | 730 | `skos:scopeNote` |
| definitions | **0** | — nothing to project |
| broader (BT), resolved | 1,759 | `skos:broader` |
| narrower (NT), resolved | 1,759 | `skos:narrower` |
| related (RT), resolved | 14,360 | `skos:related` |
| USE, resolved | 479 | `atlas:thesaurusUse` |
| UF, resolved | 394 | `atlas:thesaurusUsedFor` |
| unresolved relations | 5 | **not projected** (no endpoint) |
| label-role conflicts between the two source views | 4 | index role wins |

Shape of the hierarchy, measured the same way: **zero cycles**, 1,695 concepts
with at least one parent, 2,065 roots, 64 concepts under more than one parent,
deepest branch 5. Scope notes are one per concept where present — 730 notes
across 730 concepts, never two on one.

`skos:related` is fully symmetric in the source (every RT is stated on both
records), so the 14,360 statements are 7,180 reciprocal pairs. Both halves are
kept, because release facts are copied.

## Hierarchy: the agreement rule is satisfied, not excused

The 2026-08-02-hierarchy amendment requires that when a release states any
`skos:narrower`, the two directions agree exactly. ICPSR's do: inverting the
1,759 resolved NT statements yields exactly the 1,759 BT statements, with zero
edges on either side alone. The projection therefore emits both directions
unchanged and the atlas admits them under the ordinary rule.

The four unresolved NT statements point at labels the verified subset does not
contain, so they have no endpoint and no inverse. The bundle already records
each one as an explicit gap.

Two things worth naming about that check, because neither is obvious from the
rule. First, it runs over the **union** of every release in a build, not one
release at a time — so a vocabulary that states both directions can only be
combined with one that states both or none. ICPSR plus the Federal Register is
safe because the 2025 edition states no hierarchy at all; ICPSR plus ELSST is
safe because ELSST is reciprocal too, and the three-vocabulary build below is
what proves it rather than assumes it. Second, ICPSR's own agreement is a
property of this capture, not of the projection: the projection drops
unresolved rows in each direction independently, so a future capture that
resolves a BT whose reciprocal NT does not resolve would fail the build. That
is the correct failure — it names a real asymmetry in the source — but it is a
failure a recapture can produce.

## The development marker: carried, and required

**Decision: carry it forward and fail closed on its absence.**

`PinnedIcpsrSubjectAtlasRelease.open` refuses any bundle whose manifest or
coverage does not say `operationalState: developmentOnly` with
`acceptedOutputAllowed: false` and `candidateLookupAllowed: true`. The
projection then republishes all three on the release node in `releaseFacts`:

```
<urn:ref:icpsr:release:development:…> <https://refspec.org/ns/vocabulary-atlas/v1#operationalState>       "developmentOnly" .
<urn:ref:icpsr:release:development:…> <https://refspec.org/ns/vocabulary-atlas/v1#candidateLookupAllowed> "true"^^xsd:boolean .
<urn:ref:icpsr:release:development:…> <https://refspec.org/ns/vocabulary-atlas/v1#acceptedOutputAllowed>  "false"^^xsd:boolean .
```

Refusing outright was considered and rejected. The repo's own discipline is
that *every* atlas input is candidate-only: `ManagedReleaseView.usage_ceiling`
is `candidateUseOnly`, and the Federal Register adapter — reading the
source-complete 2025 package, not a development one — already requires that
package's coverage to declare `candidateLookupAllowed: true` and
`acceptedOutputAllowed: false` before it will open. Nothing in an atlas is
production output. A development marker is therefore a fact to carry, not a
reason to drop 3,760 concepts.

The marker rides in `releaseFacts` rather than the manifest because the atlas
manifest field set is closed at schema 1.0 — `VocabularyAtlasAsset.open`
refuses any manifest whose key set differs — so a new top-level field would
need a binding version bump. The release node is where the release's own
declarations already live.

`rkaf:membershipMode` is `rkaf:partialMembership`, not complete.
`dcterms:isVersionOf` names the whole ICPSR thesaurus, and this release omits
the 45 index-only terms and 5 XML-only labels the two source views disagree
about. The bundle itself never claimed the vocabulary was complete
(`sourceVocabularyComplete: false`); the projection does not claim it either.

## What the format could not express

Named here rather than dropped silently.

**ISO 25964 USE/UF between two concept URIs.** ICPSR mints a public term URI
for every DESCRIPTOR *and* NON-DESCRIPTOR record. SKOS's answer to a
non-preferred term is `skos:altLabel` on the preferred concept, which discards
the URI ICPSR assigned and fuses two published identities into one. `iso-thes`
does not fill the gap either: its non-preferred model links a concept to a
SKOS-XL *label* resource, and ICPSR's non-preferred entries are not labels,
they are terms with concept-shaped URIs. A SKOS mapping predicate is worse
still — the atlas requires those to earn two independent machine validations,
which is precisely the wrong bar for a fact the publisher stated outright.

So USE and UF are carried between the two concept URIs under RefSpec-owned
predicates, `atlas:thesaurusUse` and `atlas:thesaurusUsedFor`, and neither is
collapsed into a label. The source settles the question: 479 USE against 394
UF. They are not reciprocal, so either collapse would invent one side of a pair
the publisher never made. The cost to a consumer is real and worth stating: an
alternate ICPSR label is reached through an edge, not through the descriptor's
`skos:altLabel`, so a label-only reader sees 480 concepts whose only label is
an `skos:altLabel` on themselves.

**Per-concept timestamps.** Every ICPSR concept carries `inputTimestamp` and
`updateTimestamp`, written as `2023-03-06 10:09:43.0`. That is not
`xsd:dateTime`. Projecting them as typed dates requires a materialization
policy of the kind ELSST needed for its own dates
(`ELSST_DATE_MATERIALIZATION_POLICY_IRI`); projecting them untyped adds 7,520
statements of text no consumer can compare. Not projected.

**Identifier provenance rows.** Each concept carries an `identifiers` array
with the publisher code and term URI, each with its `sourceUri` and
`sourceDigest`. Both values are already in the graph as `skos:notation` and the
concept IRI; the provenance is in the bundle, which the atlas pins by digest.
Not projected.

**Five unresolved relations.** Four NT and one UF naming labels outside the
verified subset. They have no endpoint to point at. Not projected; already
recorded as gaps in the bundle's coverage report.

**Disagreement between the two source views about one term's role.** Every
concept carries both an `officialLabelRole` (from the public index) and an
`xmlLabelRole` (from the snapshot), and for **four** terms they disagree about
DESCRIPTOR versus NON-DESCRIPTOR. The bundle keeps such a term as a member and
records the conflict; the atlas states the public-index role, because that is
the role the release's own indexed expressions use, and the format has no way
to say "two source views disagree about this." Four terms out of 3,760, named
here because the graph shows no trace of it.

**A label for the concept scheme.** Neither source view states one. The scheme
node carries a type and nothing else. Writing "ICPSR Subject Thesaurus" there
would be this projection's assertion in a graph whose whole policy is
`copiedManagedReleaseFactsOnly`, so it is not written. The Federal Register
adapter does state a scheme label, and that is not the same case: its string is
the source document's own title.

**A lifecycle status.** ICPSR declares none for any term, so every projected
expression carries `source_status = "notDeclared"` — what ELSST writes, and
outside the retired set consumers filter on. The Federal Register adapter says
`"active"`; for ICPSR that would be a claim the source does not make.

## Retired Atlas 1.0 build measurements

The measurements below came from the retired Atlas 1.0 command and two-graph
format. Treat them as evidence about the verified ICPSR capture and its size,
not as current build instructions. The later Atlas 2.0 path accepted an opened
`PinnedVocabularyAtlasScope` through the programmatic API. Current producers
target the [Atlas 3.0 binding](../bindings/atlas/3.0/README.md).

**ICPSR alone**, from the real capture:

| | |
|---|---:|
| `releaseFacts` quads | 38,302 |
| `analysisFacts` quads | 3,762 |
| `hierarchyEdges` | 1,759 |
| `labelClusters` | 0 |
| `atlas.nq` | 12,008,709 B (11.5 MiB) |
| `atlas.nq`, gzip -9 | 308,623 B (301 KiB) |

Label clusters are zero because a cluster needs members from two releases, and
this build has one.

The projection hands the atlas all 4,490 of the release's own indexed
expressions, including the 730 scope notes, because that is what the release
indexed and release facts are copied. The atlas uses expressions only to build
label clusters, so the question is whether a scope note can masquerade as a
label. Measured: the shortest ICPSR note normalizes to 17 characters (`Do not
hyphenate.`), the median to 103, and **zero** of the 730 normalize to any ICPSR
label. A cluster would need another vocabulary to state that exact sentence as
a label, and a cluster is a discovery hint that cannot create a mapping by
itself.

The retired `VocabularyAtlasAsset.reproduce_from_inputs` path rebuilt this
distribution byte for byte from the pinned bundle and Rulespec Core release.
That result establishes the historical measurement. The later Atlas 2.0
producer used `VocabularyAtlasAsset.reproduce_from_scope` with the exact
path-backed scope; neither path defines current Atlas 3 construction.

**All three vocabularies**, the acid test: Federal Register 2025 + ELSST R5/R6
+ ICPSR, one retired build, no crosswalk.

| | |
|---|---:|
| `managedReleases` | **3** |
| members (`prov:hadMember`) | 11,370 |
| `releaseFacts` quads | 309,166 |
| `analysisFacts` quads | 600,230 |
| `hierarchyEdges` | **8,513** (6,754 ELSST + 1,759 ICPSR) |
| `labelClusters` | 96,958 |
| `atlas.nq` | 270,130,849 B (257.6 MiB) |
| `atlas.nq`, gzip -9 | 16,992,570 B (16.2 MiB) |

The manifest reports all three managed releases with ICPSR's real concept count
and its real hierarchy: `releaseFacts` grows by exactly 38,302 over the
FR+ELSST build, which is the ICPSR-only total, and `hierarchyEdges` is the sum
of the two vocabularies that have one. The direction-agreement check passes
over the union, which is the combination the rule had never actually been run
on — ELSST and ICPSR both state BT and NT, and both are reciprocal.

The scratch atlas is not committed. It is 257 MiB and rebuilds from the three
pinned bundle digests.

<!-- THREE-VOCABULARY-RESULTS -->

## Size, and why it is a distribution problem

The numbers below are what a pointer-publishing decision needs. This document
does not propose one.

| Distribution | `atlas.nq` | gzip -9 | label clusters |
|---|---:|---:|---:|
| Federal Register 2025 only (vendored today) | 1,469,637 B | 35,578 B | 0 |
| ICPSR only | 12,008,709 B | 308,623 B | 0 |
| FR + ELSST + crosswalk (the earlier 251 MB run) | 263,620,491 B | 17,038,092 B | 96,867 |
| **FR + ELSST + ICPSR** | **270,130,849 B** | **16,992,570 B** | 96,958 |

**ICPSR is not what makes these files large.** Counting every line that
mentions an ICPSR term URI or its release: **44,741 lines, 12,943,261 bytes —
4.8%** of the three-vocabulary distribution. Adding a whole third vocabulary,
3,760 concepts and 1,759 hierarchy edges, added **91 label clusters**.

**Label clusters are what makes them large.** In the three-vocabulary build,
`releaseFacts` is 82.5 MB (30.5%) and `analysis` is 187.7 MB (**69.5%**), and
label clusters are essentially the whole of analysis:

| Predicate | Statements | Bytes | Share of file |
|---|---:|---:|---:|
| `atlas:member` | 199,493 | 65,630,642 | 24.3% |
| `atlas:memberRelease` | 195,447 | 58,549,818 | 21.7% |
| `rdf:type` (analysis) | 96,959 | 30,736,005 | 11.4% |
| `atlas:normalizedLabel` | 96,958 | 29,469,992 | 10.9% |
| **label clusters, total** | | **187.7 MB** | **69.5%** |
| `skos:prefLabel` (release facts) | 107,277 | 26,666,123 | 9.9% |
| `skos:altLabel` (release facts) | 74,316 | 18,444,611 | 6.8% |
| `skos:related` (release facts) | 27,147 | 7,852,316 | 2.9% |
| `skos:definition` (release facts) | 17,642 | 6,324,147 | 2.3% |
| `skos:broader` + `skos:narrower` | 17,026 | 4,946,053 | 1.8% |

96,958 clusters over three managed releases — but the count barely moved when
ICPSR joined, because the clusters were never about having several
vocabularies. The ELSST bundle carries R5 *and* R6 as two releases inside one
bundle, so nearly every ELSST concept clusters with its own prior-version self.
Cluster growth is combinatorial in the number of *releases* sharing a
normalized label; release facts grow linearly in concepts.

Within ICPSR's own release facts the shape is different again — one predicate
dominates:

| Predicate | Statements | Bytes | Share of the ICPSR-only file |
|---|---:|---:|---:|
| `skos:related` | 14,360 | 4,164,400 | 34.7% |
| `atlas:memberOfRelease` (analysis) | 3,760 | 1,252,080 | 10.4% |
| `prov:hadMember` | 3,760 | 1,184,400 | 9.9% |
| `skos:inScheme` | 3,760 | 1,049,040 | 8.7% |
| `rdf:type` | 3,765 | 1,027,974 | 8.6% |
| `skos:notation` | 3,760 | 868,560 | 7.2% |
| `skos:prefLabel` | 3,280 | 804,485 | 6.7% |
| `skos:narrower` | 1,759 | 511,869 | 4.3% |
| `skos:broader` | 1,759 | 510,110 | 4.2% |
| `skos:scopeNote` | 730 | 248,299 | 2.1% |
| `atlas:thesaurusUse` / `UsedFor` | 873 | 265,222 | 2.2% |
| `skos:altLabel` | 480 | 116,544 | 1.0% |

`rdf:type` counts the scheme, both distributions, the release, and the analysis
root alongside the 3,760 concepts. `skos:prefLabel` counts only concepts: the
scheme node states no label, because neither ICPSR source view gives the
thesaurus one to copy.

ICPSR's symmetric `skos:related` alone is a third of its bytes. Every line
carries a ~110-character ICPSR term URI twice and an ~80-character graph IRI,
so N-Quads line overhead — not the vocabulary content — is most of the volume.
That is also why gzip is so effective: 39:1 on the ICPSR file, 15:1 on the
251 MB one.

**What this means for vendoring.** SpicySearch vendors the 1.5 MB FR-only asset
directly. Three vocabularies do not fit that pattern at 257 MiB, and 16.2 MiB
compressed is not obviously a vendored file either. Four facts a decision
should start from:

1. The growth is in the **analysis** graph — 69.5% — which the format itself
   calls `replaceableMachineAnalysis`. Release facts for all three vocabularies
   are 82.5 MB, and 30.5 MB of that is the two label predicates.
2. It is driven by **releases**, not vocabularies. ELSST ships two inside one
   bundle and that alone produces ~97k clusters; the third vocabulary added 91.
3. **ICPSR costs 4.8%.** FR + ICPSR without ELSST would be roughly 13.5 MB
   uncompressed with zero clusters between them measured here.
4. N-Quads line overhead, not vocabulary content, is most of the volume — every
   line repeats a ~110-character term URI and an ~80-character graph IRI. That
   is why gzip returns 16:1 on the big files and 39:1 on ICPSR alone.

Whether the answer is pointer publishing, an analysis-free distribution
profile, a per-vocabulary split, or a different compressed serialization is a
product decision. This document does not propose one.

## Provenance

The nine generator-built conformance fixtures, since removed with the Atlas 1.0
binding, changed digests at the time, because `atlas/icpsr.py`,
`registry/managed_releases/icpsr_managed_release.py`, and `registry/icpsr_subject.py` joined
`_IMPLEMENTATION_SOURCE_PATHS` — for the same reason the Federal Register
modules are already there. A specialized producer computes the closed release
digest locally, so a reader whose bytes could change without changing the atlas
identifier would leave that calculation unpinned. No rule in the binding
changed, so `fixtures/corpus.json` gained no amendment marker, and the
checked-in Federal Register example is byte-identical because it is opened
rather than reproduced.

The closed `ReferenceResourceRelease` digest calculation moved from
`atlas/federal_register.py` into `atlas/model.py` unchanged except for a label
parameter, so the two specialized producers cannot drift into two answers. The
Federal Register example's pinned release digest
`sha256:30742a82b3e268942aec713a02c5ae4264eadea36aa61b564ffc93eeecfd5fe6` is
unchanged after the move.

The structured result is in
[`research/evidence/icpsr-vocabulary-atlas-2026-08-02/`](../research/evidence/icpsr-vocabulary-atlas-2026-08-02/README.md).

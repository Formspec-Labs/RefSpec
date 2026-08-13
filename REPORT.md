# Atlas 3.1 residual SHACL floor

## Decision

**DON'T TAKE a production change from this study.**

The previous study's architectural conclusion was too broad: a second SHACL
implementation is not required to make this path faster. Reusing facts that
the Atlas parser already collected reduced the staging residual validation
median from **13.097 s to 11.652 s**, a **1.444 s (11.03%)** saving. The
prototype changes the graph view beneath pySHACL; it does not replace SHACL
semantics.

That result does not clear the release-level bar. Applying the staging ratio
only to the previous study's 430 s full-scale residual SHACL anchor projects a
**35.7 s** saving in the **18.5 min** unattended release run, or about **3.2% of
end-to-end time**. This is an extrapolation, not a full-scale measurement. The
required reverse type index also raised staging peak resident memory by
18.9 MiB, and its full-scale memory cost remains unmeasured.

Focus-node hints were slower. Neither equivalent SHACL rewrite was faster.
The explicit second-implementation ceiling saved only another 0.019 s beyond
the indexed view, well inside the sample ranges. Keep the harness and evidence;
do not add production code or change the normative shapes on this evidence.

## Scope and method

This study started from commit `ae34392c` and read the preceding
`research/residual-shacl` report before designing prototypes. It tested the
read-only distribution at:

`/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-mapping-topology-staging/distribution`

The distribution contains 1,013,723 quads in five packs. Its identifier is
`urn:ref:atlas:distribution:3.1-bounded-development:198a41c398de4a8f2240430ef648ecafe2519537d1739b3d6f52123c66386a56`.
The benchmark did not write to it.

The parent process parsed the distribution once, then forked a clean child for
each sample. Each reported total includes prototype setup, reverse type-index
construction or helper materialization when applicable, the validator's
existing lifted prechecks, and residual pySHACL validation. It excludes the
one-time 15.483 s parse and 1.701 s cached shape-graph proof, which the release
path performs separately. Every staging result is the median of three samples;
ranges below expose the run-to-run spread.

Environment: Python 3.12.9, RDFLib 7.6.0, and pySHACL 0.31.0. The benchmark
pinned RDFLib 7.6.0 because that is the binding requirement; the repository's
general virtual environment currently resolves RDFLib 7.5.0.

Instrumentation wrapped pySHACL's `Shape.focus_nodes`, `Shape.value_nodes`,
`EqualsConstraintComponent.evaluate`, and `XoneConstraintComponent.evaluate`.
Those measurements are inclusive and can overlap; they explain hot paths but
must not be added to reconstruct wall time.

Peak resident memory stayed below 448 MiB for every variant, far below the
8 GiB limit. No full-scale validation ran.

## What the remaining shapes mean

The normative definitions remain in
`bindings/atlas/3.1/shapes/atlas.shacl.ttl`; the binding explanation remains in
`bindings/atlas/3.1/README.md`.

`atlas:MappingAssertionShape` makes each mapping's endpoints agree with the
mapping record:

- subject and object resources must have the mapping's `atlas:semanticRing`;
- each endpoint's `atlas:inRelease` must equal the corresponding exact source
  or target release; and
- value and legal-identity mappings must have exactly one
  `rkaf:hasEffectivePeriod`, while subject and entity mappings must have none.
  An unknown future ring fails rather than inheriting either rule.

The last rule is the two-branch `sh:xone` under study.

`atlas:NativeRelationAssertionShape` uses four `sh:equals` checks over
two-step sequence paths. They require both endpoint resources to have the
assertion's semantic ring and require their exact releases to equal the
assertion's source and target releases. These are equality-of-value-set rules,
not merely presence checks.

## Angle 1: discovery versus constraint evaluation

### Profile

One instrumented baseline run took 13.360 s. Across all active shapes,
pySHACL spent 0.726 s in focus-node discovery and 6.510 s in value-node
discovery. For the named floor specifically:

| Work | Inclusive time | Focus nodes |
| --- | ---: | ---: |
| Mapping `sh:xone` evaluation | 0.568 s | 2,003 |
| Four native sequence-path value lookups | 1.838 s | 4 x 27,362 |
| Four native `sh:equals` evaluations | 0.303 s | 4 x 27,362 |

The sequence-path discovery costs about six times the four corresponding
`sh:equals` evaluators. Discovery is therefore a material part of this floor,
but the total engine performs much more value lookup than these four paths.

### Reusing parse-built indexes

`_AssertedFacts` already holds subject/predicate/object facts for every direct
predicate used by the target shapes. `placement.types` already records every
asserted subject type. The `indexed-view` prototype:

- answers direct object lookups for indexed predicates from `_AssertedFacts`;
- inverts `placement.types` once to answer `rdf:type` target lookups; and
- still unions ontology facts through the ordinary read-only graph view.

It does not pre-decide conformance, materialize endpoint answers, or replace a
SHACL constraint.

The indexed profile reduced focus discovery from 0.726 s to 0.219 s and value
discovery from 6.510 s to 5.741 s. It served 1,798,187 direct object calls and
662 type-target calls from parse-built indexes. The repeated results comprised
1,608,519 object values and 3,340,934 target values. Building the reverse type
index took 0.032 s at staging scale.

Measured result:

| Variant | Median | Range | Change from baseline | Peak RSS |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 13.097 s | 12.711–13.111 s | — | 390.0 MiB |
| Indexed view | **11.652 s** | 11.464–11.925 s | **1.444 s faster (11.03%)** | 408.9 MiB |

This answers the first question: discovery and repeated graph reads are
costly, and the existing parse results can reduce them without implementing
SHACL again.

### Explicit focus-node hints

pySHACL bypasses target discovery only when callers supply both `use_shapes`
and `focus_nodes`. The validator's batched plan normally targets anonymous
property shapes, which are not stable API identifiers. The prototype gives
them temporary internal names, groups shapes with the same targets, and makes
31 focused calls for the asserted graph; 15 groups are nonempty. Preparing
the focus lists took 0.061 s in the instrumented run.

| Variant | Median | Range | Change from baseline |
| --- | ---: | ---: | ---: |
| Focus hints | 13.195 s | 12.777–13.538 s | 0.098 s slower |
| Indexed view + focus hints | 11.809 s | 11.725–12.537 s | 1.287 s faster |

Focus hints removed the instrumented `Shape.focus_nodes` work, but repeated
pySHACL dispatch erased the saving. Adding hints made the indexed view 0.157 s
slower. **Do not take focus-node hinting.**

## Angle 2: equivalent shape formulations

The research harness tested four counterfactual formulations. Private helper
terms exist only in the transient data view; they do not enter the input
distribution or output artifacts.

| Variant | Meaning | Median | Range | Change from baseline |
| --- | --- | ---: | ---: | ---: |
| Mapping `sh:or` | Replace `sh:xone` with the same two disjoint, explicit ring branches | 13.139 s | 13.071–14.362 s | 0.042 s slower |
| Direct `sh:equals` | Materialize the four two-step results under private direct predicates, retain `sh:equals` | 13.388 s | 13.240–15.859 s | 0.292 s slower |
| Direct `sh:equals` + indexes | Same rewrite atop the indexed view | 12.229 s | 12.111–12.450 s | 0.868 s faster overall, 0.577 s slower than indexed view |
| Mapping semantic helper | Compute the current xone truth explicitly, then make SHACL check a helper marker; includes indexed view | 12.092 s | 12.075–12.256 s | 1.005 s faster overall, 0.439 s slower than indexed view |
| Combined second implementation | Indexes + direct endpoint values + mapping helper | 11.634 s | 11.433–12.438 s | 1.463 s faster overall |

The direct-path rewrite materialized 109,448 helper triples and cost 0.681 s
without indexes. The mapping helper materialized 2,003 facts and cost 0.018 s.
The combined version created 111,451 helper triples; its engine fell to
8.761 s, but 0.603 s of helper work erased nearly all of that advantage.

The combined median beat the ordinary indexed view by **0.019 s (0.16%)**,
while their ranges overlap widely. This prices the prior report's warning:
duplicating the constraint semantics does not buy a practical improvement.

### Refusal-equivalence proof

Every non-baseline variant ran through `validate_binding()` in both default
and audit modes in a fresh child process. That gate compares the committed
expectation for every fixture, including verdict, `firstIssue`, and the full
ordered `shaclComponents` list where specified.

All eight variants passed:

| Check | Result in default mode | Result in audit mode |
| --- | ---: | ---: |
| Corpus cases | 130/130 | 130/130 |
| Expected invalid cases and `firstIssue` | 117/117 | 117/117 |
| Cases with exact `shaclComponents` lists | 47/47 | 47/47 |
| Registry descriptors / quads / schemas | 88 / 994 / 10 | 88 / 994 / 10 |

This is the requested corpus equivalence proof: all represented refusals keep
the same operator-visible codes and SHACL components in both modes. It is not
a formal proof over every possible RDF graph. The rewrites retain the same
outer SHACL component types, and the exact component-list comparison proves
that the research helpers did not change the reported components in this
corpus.

The cheap `sh:or` substitution is logically safe for the current four
explicit, disjoint rings and passed the corpus, but it was not faster. The
helper formulations cross the second-implementation boundary and also failed
the performance test. **Do not take any shape reformulation.**

## Angle 3: the honest pySHACL floor

With pySHACL retained and constraint semantics not duplicated, the best
measured staging result is the 11.652 s indexed view:

| Component | Indexed-view median |
| --- | ---: |
| Reverse type index | 0.032 s |
| Existing lifted prechecks | 2.154 s |
| Residual pySHACL engine | 9.449 s |
| Plan construction | 0.016 s |
| Total, including minor view setup | **11.652 s** |

Inside one instrumented indexed run, focus-node discovery was 0.219 s and all
value-node discovery was 5.741 s. The four native sequence paths accounted for
1.695 s, their `sh:equals` evaluators for 0.226 s, and the mapping `sh:xone`
for 0.584 s. These inclusive timers overlap with constraint evaluation; they
locate work but are not additive components of the 9.449 s engine median.

The measured lower bound after explicitly duplicating both named semantics is
11.634 s. Its engine is faster, but helper construction cancels the saving.
Within this design and engine, the useful floor is therefore approximately
**11.65 s on the staging graph**, not because every remaining constraint is
intrinsically expensive, but because producing cheaper inputs or splitting
engine calls costs about as much as it saves.

### Full-release projection

The previous report measured 17.380 s on staging and used 430 s as the
full-scale residual SHACL anchor. The current branch contains the later
parse-built fact index and two-index store, so 17.380 s versus 13.097 s is
context only, not a controlled before/after result.

To avoid running the prohibited full validation, this report scales only the
430 s residual anchor by the controlled current staging ratios:

- projected current baseline residual:
  `430 x 13.096662 / 17.380 = 324.0 s`;
- projected indexed-view residual:
  `430 x 11.652330 / 17.380 = 288.3 s`;
- projected saving: **35.7 s**;
- projected end-to-end release: **17.90 min**, down from 18.50 min, if all
  non-SHACL phases remain unchanged.

The assumption is that the staging-to-full shape mix and relative graph-store
cost carry over. The reverse type index may scale differently. Scaling the
11.03% ratio over all 18.5 minutes would overstate the result because most of
that run is outside this residual path.

The combined second implementation projects only another 0.5 s of full-scale
residual saving over the indexed view. That does not justify duplicate
semantics.

## Release recommendation

**DON'T TAKE.** The indexed view is the only credible avenue, and it disproves
the claim that improvement necessarily requires a second SHACL implementation.
It still offers only a projected 36-second, 3.2% end-to-end release saving,
with unmeasured full-scale memory growth and no full-scale timing. This job
runs once per release and unattended, so the added production surface and
permanent parity obligation outweigh that projected gain.

Reopen the indexed-view approach if release validation becomes frequent, or
if an authorized full-scale trace shows at least a one-minute end-to-end
saving while remaining under the memory limit. Do not revisit focus hints,
`sh:or`, sequence aliases, or semantic helpers without a changed pySHACL cost
model; their measured outcomes already close those paths.

## Verification and evidence

The production validator and normative SHACL files are unchanged. The branch
adds only research tools, recorded evidence, and this report.

Required gates passed:

- `make lint`: passed;
- `make test-atlas-v3`: passed with 130 cases, 117 expected invalid cases,
  88 registry descriptors, 994 registry descriptor quads, and 10 schemas;
- `REFSPEC_RELEASE_TIER=1 pytest -q -k corpus_wide`: 47 passed, 1 skipped,
  2,599 deselected in 31.98 s; and
- fixture rebuild under pinned RDFLib 7.6.0: 2,084 files identical.

The two evidence files are immutable review inputs for this branch:

- `research/evidence/shacl-floor-2026-08-13/avenue-matrix-v1.json`
  (`sha256:44acb091e3576b6b3a625be08f8786fa6c81f40e21211b3a656edb37473a930b`);
- `research/evidence/shacl-floor-2026-08-13/corpus-equivalence-v1.json`
  (`sha256:1932e828f480697cbfffe73976722c901e36e3f52b2381f5b27729bff1d726bf`).

The prototypes are in `tools/atlas_shacl_floor_prototypes.py`. The staging
driver is `tools/benchmark_atlas_shacl_floor.py`; the corpus proof is
`tools/prove_atlas_shacl_floor_equivalence.py`. The JSON evidence preserves
the exact sample records, profiles, environment, artifact identity, and peak
resident memory used for this decision.

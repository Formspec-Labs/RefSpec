# Residual pySHACL performance research

Date: 2026-08-13  
Branch: `research/residual-shacl`  
Decision: **Do not take another SHACL lift into the release validator.**

The residual green-path cost is mainly RDF graph traversal inside pySHACL,
not shape parsing or Python dispatch. The broad prototype removed 353 of 615
targeted constraint-parameter occurrences from pySHACL and cut measured engine
time from 14.17 s to 6.61 s at staging scale. Its table checks cost more than
the engine work they replaced: total time rose from 17.38 s to 17.72 s
(+2.0%). The best isolated avenue, `sh:class`, saved 0.16 s (0.9%). None meets
the once-per-release bar.

The remaining pySHACL work has a distinct floor. `sh:xone` on
`atlas:MappingAssertionShape`, four sequence-path `sh:equals` shapes on
`atlas:NativeRelationAssertionShape`, and their value-node and focus-node
discovery dominate it. Lifting those constraints would require a second SHACL
implementation, not another small direct-path table. The measured direct lift
covers 65% of targeted property shapes and 57% of targeted constraint
occurrences, not 90%; it does not yet replace the engine. Going materially
further would.

## Scope and measurement method

The input was the read-only staging distribution at
`/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-mapping-topology-staging/distribution`:
1,013,723 quads in five packs, distribution ID
`urn:ref:atlas:distribution:3.1-bounded-development:198a41c398de4a8f2240430ef648ecafe2519537d1739b3d6f52123c66386a56`.
The environment used Python 3.12.9, rdflib 7.5.0, and pySHACL 0.31.0. All
measurements ran in this disposable worktree. No command wrote to the source
distribution or the main repository.

The measurement path answered four questions:

1. **What goes in?** The staging packs, the pinned Atlas 3.1 ontology, and the
   normative Atlas 3.1 shapes.
2. **What happens?** The harness parses the distribution once, freezes the
   stable heap, then forks a fresh child for each sample. Each child times the
   existing prechecks and pySHACL separately. The profiler also wraps
   pySHACL's `Shape.validate` and constraint evaluators and runs `cProfile`.
3. **What comes out?** Three uninstrumented samples per avenue, internal shape
   and component attribution, peak resident memory, and full corpus results.
4. **How is it checked?** The full binding gate compares every fixture with
   its committed expected result. A mutation battery separately forces every
   lifted component to fail and confirms the normative component name.

Profiling instrumentation almost doubles wall time, so the profile locates
work but does not price an avenue. The uninstrumented forked medians price the
avenues. Peak resident set size (RSS) was 1.16 GiB for the baseline, 1.19 GiB
for the broad lift, and 1.37 GiB under the heavier profiler—well below 8 GiB.

## Baseline

The controlled staging baseline is 17.38 s for the residual SHACL phase after
the existing closed-shape, ring-context `sh:xone`, and warrant `sh:xone`
lifts. Parsing the 1,013,723-quads distribution took 20.82 s and the cold
shape-graph proof took 1.66 s; both sit outside this residual timing.

| Work | Median | Observed range |
|---|---:|---:|
| Existing table prechecks, asserted + derived | 3.213 s | 3.205–3.294 s |
| Residual pySHACL engine, asserted + derived | 14.174 s | 13.908–14.241 s |
| Residual SHACL total | **17.380 s** | **17.202–17.454 s** |

The asserted graph accounts for almost all of this cost. In the median sample,
it used 3.173 s of prechecks and 13.882 s of engine time. The empty derived
role used 0.033 s and 0.292 s.

## What pySHACL is doing

The baseline `cProfile` run made 195,320,051 calls in 39.46 instrumented
seconds. Cumulative times overlap and therefore do not add to 100%.

| pySHACL or rdflib work | Instrumented cumulative time | Share of instrumented engine |
|---|---:|---:|
| `Shape.value_nodes` and path evaluation | 20.647 s | 52.3% |
| `Shape.focus_nodes` | 6.426 s | 16.3% |
| `ClassConstraintComponent` evaluation | 5.363 s | 13.6% |
| rdflib `Identifier.__eq__` | 4.365 s / 15.0M calls | 11.1% |
| `XoneConstraintComponent` | 1.894 s | 4.8% |
| `EqualsConstraintComponent` | 1.771 s | 4.5% |
| nested property-shape dispatch | 1.635 s | 4.1% |

Graph traversal sits under most rows: 11.3 million `Graph.triples` calls and
6.1 million `Graph.objects` calls feed path, focus, and constraint evaluation.
This explains why replacing a constraint evaluator alone gives back less wall
time than its component attribution suggests.

The internal shape trace identifies three cost centers:

* Four sequence-path property shapes under
  `atlas:NativeRelationAssertionShape` each consume 1.83–1.86 s inclusive.
  Their individual `EqualsConstraintComponent` evaluations cost about 0.295 s;
  path value construction accounts for most of the rest.
* `atlas:MappingAssertionShape` consumes 1.84 s inclusive. Its remaining
  `XoneConstraintComponent` costs 1.83 s across 2,003 focus nodes, including
  nested property checks.
* Direct `sh:class` checks over 27,362–29,365 values are the largest
  mechanically liftable group. The three largest individual checks cost
  0.55–0.58 s in the instrumented trace.

## Direct-path lift prototypes

The prototype applies the existing lift discipline. It reads constraints from
the shapes graph, accepts only a single direct IRI path, and keeps the original
property shape in pySHACL when the path or constraint form is unsupported.
It supports `sh:hasValue`, `sh:in`, `sh:minCount`, `sh:maxCount`,
`sh:datatype`, `sh:nodeKind`, and `sh:class`. The class check uses the type
index already built while parsing asserted quads plus ontology types.

The production default selects no new direct constraints. Benchmarks opt in
through `_batched_shacl_plan(..., direct_constraints=...)`; the default
validator therefore retains its current behavior and does not build the
prototype's supplemental type index.

| Avenue | Property shapes lifted | Median precheck | Median engine | Median total | Change from baseline | 430 s projection |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 0 | 3.213 s | 14.174 s | **17.380 s** | — | 430.0 s |
| `minCount`/`maxCount`/`in`/`hasValue` | 23 | 4.249 s | 13.103 s | 17.353 s | −0.027 s (−0.16%) | 429.3 s |
| `datatype`/`nodeKind` | 1 | 3.214 s | 14.042 s | 17.244 s | −0.136 s (−0.78%) | 426.6 s |
| `class` | 19 | 4.295 s | 12.924 s | **17.220 s** | **−0.160 s (−0.92%)** | **426.0 s** |
| All supported direct constraints | 133 | 11.095 s | 6.614 s | **17.721 s** | **+0.341 s (+1.96%)** | **438.4 s** |

The full lift changes the work location, not the acceptance cost. It removes
7.56 s from pySHACL but adds 7.88 s to the precheck. The direct table walks
the same RDF values, builds counters and sets, and then pySHACL still performs
focus and path work for the shapes that remain.

The shapes inventory makes the boundary concrete:

| Inventory | Existing fast path | Broad direct prototype |
|---|---:|---:|
| Targeted shapes in execution graph | 236 | 103 |
| Targeted property shapes | 205 | 72 |
| Targeted constraint-parameter occurrences | 615 | 262 |
| Direct checks outside pySHACL | 0 | 353 checks in 133 property shapes / 29 target groups |

Thus the prototype evaluates 64.9% of targeted property shapes and 57.4% of
targeted constraint occurrences outside pySHACL. It leaves 262 occurrences,
including the costly non-direct and logical constraints, in the engine.

## Engine-level avenues

| Avenue | Measurement | Decision |
|---|---:|---|
| Cache ontology and shape parsing | `_parse_binding_graphs()` median 0.0217 s over 10 calls | **DON'T TAKE.** Negligible beside 17.38 s; the release path calls it once per distribution. |
| Cache pySHACL's shape-node discovery | `_build_node_shape_cache` used 0.014 instrumented seconds across both role invocations | **DON'T TAKE.** No material opportunity. |
| Reuse the shape-graph conformance proof | Cold proof 1.66 s; `_prove_shape_graph_conforms` already has an LRU cache | **KEEP current cache.** It already removes repeats within the 130-case binding gate. |
| Skip pySHACL for the empty derived role | Median upper bound 0.322 s including current precheck | **DON'T TAKE.** It needs a new proof that shape, ontology, and role drift cannot add targets, for less than 2% staging benefit. |
| Replace repeated `CONSTRAINT_PARAMETERS` list membership with a cached set | 16.727 s → 16.614 s median; 0.113 s (0.68%) saved, with one 22.33 s outlier | **DON'T TAKE.** It patches pySHACL internals for a projected 2.9 s once per release. |
| Reduce rdflib node equality churn | 15.0M `Identifier.__eq__` calls / 4.365 instrumented seconds | **No local take.** This is graph-store and path traversal work. A safe fix belongs in rdflib or pySHACL and needs upstream-scale proof. |

Invocation and dispatch setup is therefore measured in milliseconds. The
remaining seconds arise after dispatch, while pySHACL discovers focus and
value nodes through rdflib.

## Equivalence proof

The fixture materializer reported:

```text
Atlas 3.1 fixtures rebuilt and compared: 2084 files identical
```

The fixture payload digest remained
`sha256:d492f15ab78167794784fbd24684f99cce1fc9516c62359ecbd024479be304e5`.
The one-line receipt update changes only its input evidence: it pins the
prototype's new `validate.py` digest and the requested rdflib 7.5 runtime.

Both the default plan and the broad prototype then passed the full
`validate_binding()` gate. Each checked 130 cases, including 117 invalid
cases, all 117 recorded `firstIssue` values, and all 47 recorded
`shaclComponents` lists. Both produced the same summary:

```json
{
  "caseCount": 130,
  "invalidCount": 117,
  "registryDescriptorCount": 88,
  "registryDescriptorQuadCount": 994,
  "schemaCount": 10
}
```

The latest proof took 29.141 s for the default and 28.312 s for the prototype.
The timing is incidental; the result comparison is the proof.

The negative tests mutate each lifted component—`MinCount`, `MaxCount`, `In`,
`HasValue`, `Datatype`, `NodeKind`, and `Class`. For each mutation, normative
pySHACL rejects the graph with the expected component and the prototype
precheck rejects it too. A separate drift test changes a direct path into an
RDF sequence; the planner refuses the lift and leaves `sh:hasValue` and the
target in pySHACL. Existing mutation tests continue to cover closed shapes and
the lifted ring and warrant `sh:xone` checks.

Verification results:

```text
ruff: all checks passed
pytest tests/test_atlas_v3_validator_regressions.py:
166 passed, 47 skipped in 21.69s
```

## Honest floor and full-scale projection

The projections use the user's current 430 s full-scale residual measurement
as the anchor and multiply it by each staging median divided by the 17.380 s
staging baseline. This assumes full-scale data has the same shape mix,
focus-node mix, and relative graph-store cost as staging. It does not assume
linear cost per quad: the observed staging ratio supplies the multiplier.
These are planning estimates, not full-scale measurements.

The best measured result projects to 426.0 s, about 4.0 s saved. The broad
lift projects to 438.4 s, about 8.4 s slower. The private membership patch
projects to 427.1 s, about 2.9 s saved, but its separate sample set included a
large outlier.

After the broad lift, pySHACL itself costs 6.614 s at staging scale, equivalent
to about 164 s under the same ratio. That is the measured floor for this
direct-path lift family unless
the implementation also takes over `MappingAssertionShape`'s `sh:xone`, the
four sequence-path `sh:equals` checks, and the remaining pair, logical, and
string constraints. Acceptance still costs 17.721 s because all prechecks now
consume 11.095 s.

An intentionally optimistic counterfactual illustrates the ceiling: if all
new direct checks were free and only the existing 3.213 s of prechecks plus
the 6.614 s residual engine remained, staging would take 9.828 s and the
430 s anchor would project to 243 s. No prototype achieved this. Realizing it
would require folding checks into a data structure already computed for
another required phase, with no second RDF walk. The current type index only
does that for `sh:class`, which is why class is the sole avenue with a small
measured win.

The lift pattern effectively replaces pySHACL when most shapes—including
logical and non-direct paths—are evaluated in project-owned tables and the
engine merely confirms a residue. This prototype has not crossed the 90% mark,
but the next expensive constraints would cross the architectural boundary.
Keep pySHACL as the semantic engine and accept its roughly 430 s once-per-
release cost unless release frequency or the budget changes enough to reopen
kill-list item 5's already approved subprocess-engine evaluation.

## Implementation cost and take decisions

The default-disabled prototype adds 431 lines and removes 12 lines in
`validate.py`, plus 116 regression-test lines. The three research tools add
739 lines. Productionizing the broad lift would retain most of that code:
strict shape parsing, datatype and node-kind semantics, type-index composition,
grouped table execution, drift fallback, and permanent negative tests. A
0.9% best-case saving does not justify that second implementation.

* **TAKE:** keep the profiler, benchmark harness, proof harness, raw evidence,
  and this report on the research branch. They make the result reproducible.
* **KEEP:** the current closed-shape, ring-context, and warrant-`sh:xone`
  lifts. Their measured gains remain qualitatively different from the residual
  avenues.
* **DON'T TAKE:** the direct cardinality/membership, term, or class lifts in
  the release path.
* **DON'T TAKE:** the private pySHACL membership patch, extra shape-parse
  caching, or empty-derived-role skip.
* **DON'T EXTEND:** lifting the remaining `sh:xone` and sequence-path
  `sh:equals` constraints without an explicit decision to replace the green
  path's semantic engine.

## Reproduction and evidence

Raw results live in `research/evidence/residual-shacl-2026-08-13/`:

* `avenue-matrix-v1.json` — three uninstrumented samples for each direct lift;
* `profile-baseline.json` and `.txt` — baseline internal attribution and
  `cProfile`;
* `profile-all-direct.json` and `.txt` — residual attribution after the broad
  lift;
* `engine-parameter-membership.json` and `engine-overheads.json` — engine-level
  avenues;
* `corpus-equivalence.json` — latest two-plan binding-gate proof.

Commands, using the repository's pinned environment:

```bash
PYTHON=/Users/mikewolfd/Work/spicy-regs/RefSpec/.venv/bin/python
STAGING=/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-mapping-topology-staging/distribution

$PYTHON tools/profile_atlas_residual_shacl.py "$STAGING" \
  --json-output research/evidence/residual-shacl-2026-08-13/profile-baseline.json \
  --profile-output research/evidence/residual-shacl-2026-08-13/profile-baseline.txt
$PYTHON tools/profile_atlas_residual_shacl.py "$STAGING" --direct-lift \
  --json-output research/evidence/residual-shacl-2026-08-13/profile-all-direct.json \
  --profile-output research/evidence/residual-shacl-2026-08-13/profile-all-direct.txt
$PYTHON tools/benchmark_atlas_residual_avenues.py "$STAGING" --repetitions 3 \
  --output research/evidence/residual-shacl-2026-08-13/avenue-matrix-v1.json
$PYTHON bindings/atlas/3.1/tools/build_fixtures.py --check
$PYTHON tools/prove_atlas_residual_lift_equivalence.py \
  --output research/evidence/residual-shacl-2026-08-13/corpus-equivalence.json
$PYTHON -m pytest -q tests/test_atlas_v3_validator_regressions.py
```

## Delivery boundary

The worktree contains the report, prototypes, tests, and measurements. The
environment permits writes here but denies writes to the worktree's Git index,
which lives at
`/Users/mikewolfd/Work/spicy-regs/.git/modules/RefSpec/worktrees/codex-residual-shacl/index`.
The attempted commit failed with `Operation not permitted`. No commit was
created; committing remains the only incomplete delivery step.

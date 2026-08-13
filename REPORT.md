# Parse-observer campaign: graph-residual report

## Result

The campaign removed the two requested per-record graph-query loops without changing validation results.
On the 1,013,723-quad mapping-topology staging distribution:

- `check-construction-record-ownership` fell from 192,822 `Graph.triples` calls to 16 and from 0.622 s to 0.305 s.
- `check-machine-adjudication` fell from 117,460 calls to zero and from 0.358 s to 0.146 s.
- Together they fell from 310,282 calls to 16, a 99.995% reduction, and from 0.980 s to 0.451 s, a 54.0% reduction.
- The full staging run made 310,266 fewer graph calls. Its single-run wall time moved from 38.431 s to 37.692 s. SHACL variance makes the 0.739 s whole-run difference directional, not a stable benchmark.

The `atlas:sourceRecord` sweep remains on the graph. The index has the same 34,476 pairs but not the graph store's predicate-object-subject order; the first pair differs. Because the gate raises on the first unreconciled pair, replacing the sweep would change a contractual `firstIssue`. Keeping the current one-call sweep is cheaper and safer than maintaining a second index coupled to an RDF store's internal iteration order.

No larger, previously unnamed graph-query loop appeared. The largest remaining graph-call consumer outside SHACL and parsing is the native-payload and node-digest gate at 23,192 calls. The 2.017 s evidence-and-assertions phase is the largest remaining semantic wall-time item, but the prior read-fold campaign already reduced it to 149 graph calls; its residual cost is computation rather than an undiscovered store-query loop.

## Scope and method

The before revision is `ae34392c`; the implementation revision is `b01946bc`. Both profiles used Python 3.12.9, `rdflib 7.5.0`, `pyshacl 0.31.0`, and the default `two-index` store on the same read-only distribution. This is the project environment used by the producer path and gives an apples-to-apples comparison. The standalone binding gates also passed under the binding's pinned `rdflib 7.6.0` environment.

The profiler wraps `Graph.triples`, attributes every call and predicate to the active validation phase, records phase wall time, and reads process peak resident set size (RSS). Full-path wall times are one sample before and one after. They are suitable for ranking large costs and measuring call elimination, not for sub-second confidence intervals. Parse-only RSS uses three fresh-process samples per configuration.

The staging artifact is fixed by manifest SHA-256 `53f5b233b95618074612c8331ff2b47cd696e75c5ab4731ced3d5caa95b9cd2f`. The raw observations are in:

- `research/graph-residual/measurements/baseline-ae34392c.json`
- `research/graph-residual/measurements/after-b01946bc.json`
- `research/graph-residual/measure_validation.py`

## Phase decisions

| Phase | Decision | Reason and coverage |
|---|---|---|
| Construction record ownership | Folded | Forward ownership reads now use `_AssertedFacts`. One pass over indexed `rkaf:bindsAssertion` builds the reverse statement-to-binding lookup. The old role and record iteration remain in place, preserving which failing record is named first. Staging exercises resources, labels, releases, source records, statements, and evidence bindings. Its zero identifiers and lifecycle events leave those two ownership branches fixture-exercised only. |
| Machine adjudication | Folded | The four warrant-axis reads and the complete machine-record read set use `_AssertedFacts`. Parsed node digests are reused when present. The parser records facts but never decides validity; the existing gate still raises the same code and message in the same control flow. Staging exercises 29,365 evidence-binding warrant scans but contains no machine proof, comparison, lineage, issuer, or artifact records. The full machine protocol is corpus-exercised only. |
| Source-record reconciliation | Left on graph | The graph's predicate-object-subject iteration and the observer's subject-major order have identical members but different order from item zero. Sorting the observer would define a new order, not reproduce either supported store's internal order. Preserving the old order would require retaining a second reverse index or reaching into store internals to save 0.17-0.19 s and one `Graph.triples` call. That is not a favorable trade. |

The staging distribution also has zero cross-ring assertions, projections, derived relations, and source assignments. Those branches are validated by the sealed conformance corpus, not by this real-data measurement.

## Observer extension

What goes in: each asserted quad already seen by the canonical pack parser.

What happens: `_AssertedFacts` retains objects only for an allowlist of predicates read later by folded gates. This change adds 24 machine-adjudication predicates, taking the allowlist from 43 to 67 predicates. It does not add a second copy of the RDF graph, and it records no validation verdict. Construction ownership reuses predicates that were already indexed. The machine gate receives the same facts through the semantic inventory and reuses parsed node digests. A missing allowlist entry fails loudly rather than silently querying the graph.

What comes out: the gates receive the same ordered object sequences they previously got from `Graph.objects`. The production parse path uses the observer-built index. `validate_preparsed_distribution`, whose graphs are already resident and which has no packs to observe, reconstructs the observation with `_AssertedPlacementObservation.from_graph`. Direct helper calls retain `_AssertedFacts.for_graph` as a graph-backed fallback.

How it is checked: the regression oracle compares the index with raw `Graph.objects` for every indexed predicate, subject, value, membership query, and multi-valued order. Another regression rejects any bounded graph lookup for an indexed predicate while it runs all folded gates. A producer-path regression proves that preparsed validation constructs the fallback exactly once. The 130-case sealed corpus, including 117 invalid cases and the machine-adjudication mutation set, freezes codes, components, and `firstIssue` observations.

## Staging measurements

The complete phase table follows. Calls are `Graph.triples` invocations, not yielded triples. The source-record row therefore shows one call even though it streams 34,476 pairs.

| Phase | Before calls | After calls | Before s | After s |
|---|---:|---:|---:|---:|
| Load manifest | 0 | 0 | 0.084 | 0.083 |
| Closed distribution | 0 | 0 | 0.007 | 0.007 |
| Source-accounting files | 0 | 0 | 0.948 | 0.954 |
| Parse RDF packs | 1 | 1 | 15.989 | 16.026 |
| Load binding graphs | 155 | 155 | 0.032 | 0.029 |
| SHACL | 6,146,362 | 6,146,362 | 17.122 | 16.963 |
| Graph roles | 2,154 | 2,154 | 0.357 | 0.352 |
| Profile and identifiers | 0 | 0 | 0.031 | 0.030 |
| Releases and labels | 0 | 0 | 0.185 | 0.173 |
| Evidence and assertions | 149 | 149 | 2.099 | 2.017 |
| Machine adjudication | 117,460 | 0 | 0.358 | 0.146 |
| SKOS semantics | 0 | 0 | 0.180 | 0.171 |
| Derived graph | 0 | 0 | <0.001 | <0.001 |
| Payload and node digests | 23,192 | 23,192 | 0.241 | 0.240 |
| Accounting and counts, including source-record sweep | 1 | 1 | 0.170 | 0.193 |
| Reasoning isolation | 0 | 0 | <0.001 | <0.001 |
| Acceptance | 0 | 0 | 0.005 | 0.005 |
| Construction ownership | 192,822 | 16 | 0.622 | 0.305 |
| **Whole run** | **6,482,296** | **6,172,030** | **38.431** | **37.692** |

Each whole-path column is one sample. Peak RSS was 599.750 MiB before and 636.734 MiB after, but those single full-process high-water marks include allocator history and SHACL. The controlled parse-only measurements below isolate the index cost.

### Remaining graph-call ranking

After excluding SHACL and the parser, the largest remaining consumers are:

| Rank | Phase | Calls | Wall s | Interpretation |
|---:|---|---:|---:|---|
| 1 | Payload and node digests | 23,192 | 0.240 | Two reads per 11,505 source records; a possible next read fold, but smaller than either campaign target. |
| 2 | Graph roles | 2,154 | 0.352 | Placement observation already removed the dominant graph-role work; these are residual type/shape reads. |
| 3 | Load binding graphs | 155 | 0.029 | Small ontology and shape setup, not a carrier loop. |
| 4 | Evidence and assertions | 149 | 2.017 | Known from the prior read-fold wave; remaining time is hashing and semantic work. |
| 5 | Construction ownership | 16 | 0.305 | Residual `rdf:type` role enumeration is retained to preserve record failure order. |
| 6 | Accounting and counts | 1 | 0.193 | The deliberately retained source-record sweep; 34,476 yielded pairs. |

## Failure-order observation for `atlas:sourceRecord`

The staging comparison found 34,476 pairs in both paths and no membership difference. Order differs at index zero:

- Graph store first: resource `urn:ref:atlas-label:7d9d7e89d2a608936a2dcd1bf966d231984b61acc4f67015487e3a9c247d4dcf` with source record `urn:ref:atlas-source-record:11ed65be63fef68beec42c11153286169e208b0106e279fedf7afd25a85a542f`.
- Observer first: resource `http://id.loc.gov/authorities/subjects/sh00001050` with the same source record.

If both resources were unreconciled, the current gate would name the graph-store resource while an index walk would name the other. Sorting would create a third order and re-record a golden observation without a product benefit. The constraint is therefore real, and the retained graph sweep is the measured choice.

## Memory accounting

| Parse configuration | Indexed predicates | Indexed occurrences | Peak RSS samples, MiB | Median MiB |
|---|---:|---:|---|---:|
| No fact index | 0 | 0 | 561.859, 559.703, 559.781 | 559.781 |
| Prior read-fold index | 43 | 826,127 | 622.062, 603.844, 601.797 | 603.844 |
| Extended index | 67 | 826,127 | 600.969, 600.469, 603.859 | 600.969 |

The extended index costs 41.188 MiB at staging by median RSS difference from no index. The 24 added machine predicates retain zero occurrences in this artifact, so their incremental cost is below allocator noise; construction uses facts already retained. Predicate count alone does not consume meaningful memory. Occurrence count does.

The total-index full-scale estimate is 1.162 GiB:

`41.188 MiB × (29,283,283 full quads / 1,013,723 staging quads) = 1,189.8 MiB = 1.162 GiB`

This is a projection, not a full-scale measurement. It assumes the indexed-predicate occurrence density and Python object-sharing behavior remain constant. The new machine predicates have structural zero coverage at staging, so no honest incremental full-scale memory estimate is possible from this sample. If they are also absent at full scale, they add only empty dictionaries. Otherwise, budget approximately one retained object reference per occurrence plus subject-row overhead.

All measured runs stayed below 0.65 GiB RSS, well under the 8 GiB limit.

## Full-scale projection

No full-scale validation was run. I read only the existing full artifact's manifest and construction summary. They report 29,283,283 quads, 560,429 evidence bindings and statements, 590,561 source records, 588,409 resources, 984,114 labels, 4,669 identifiers, 219 releases, and zero lifecycle events. The manifest SHA-256 is `18fdcd01947821b54c6eb520925219f0a00e1e5a357477cdc68653e772c4b8d6`; the construction-summary SHA-256 is `3a8075485231d564d00d559d0b406ca7d55eef742de159de66d289c8503512bd`.

The projection separates work that remains from graph-query work that was removed:

- Construction loop work scales by the full/staging logical-record ratio, 31.4065. Removed graph-query work scales by the gate's derived lookup count ratio, 4,974,567 / 192,806 = 25.8009. That gives 17.75 s before, 9.57 s after, and 8.18 s saved.
- Machine adjudication scales by the evidence-binding ratio, 560,429 / 29,365 = 19.0849. That gives 6.84 s before, 2.79 s after, and 4.05 s saved. This assumes the full artifact resembles staging and has no material machine-protocol population; staging cannot measure that branch.
- Combined projected saving: 12.23 s.

Subtracting 12.23 s from the previously measured 18.5-minute `ae34392c` full-validation reference gives approximately 18.3 minutes. This model holds every other phase constant, including SHACL, parsing, storage density, and machine-record prevalence. It is useful for estimating this patch's contribution, not predicting the separate SHACL campaign or total future validation time.

## Verification

| Gate | Result |
|---|---|
| `make lint` | Passed with pinned Ruff 0.16.0. |
| `make test-atlas-v3` | Passed: 130 cases, 117 invalid cases, 88 registry descriptors, 994 descriptor quads, 10 schemas. |
| `REFSPEC_RELEASE_TIER=1 pytest -k corpus_wide` | Passed: 47 selected, 2,600 deselected, 1 skipped. |
| `pytest tests/test_atlas_v3_validator_regressions.py tests/test_atlas_v3_binding.py -q` | Passed after the sandbox-safe dependency adapter was placed on subprocess `PATH`. |
| `make contract-dev` | Passed with the read-only reference source root supplied. It rebuilt and smoke-validated 53,507 quads, then produced a `status: passed` publisher-evidence receipt. Manifest SHA-256: `b795363f24f426a5f654e92583279ff312ee01b90512b5318678eeab7f0ab11a`; Parquet view SHA-256: `e66eb3078f601fef05bcab532d08f21c45568304297f657d778663142449e413`. |

The sandbox could read the shared package cache but could not let `uv` traverse one cache-internal Git directory. The gates therefore used a temporary local `uv run` adapter that dispatched to the already cached, lockfile-pinned packages. It preserved the repository's deliberate split: project commands used `rdflib 7.5.0`, binding commands used `rdflib 7.6.0`, and lint used Ruff 0.16.0. The adapter is not part of the deliverable.

## What remains

The source-record sweep remains deliberately graph-backed. The next measurable store-read candidate is native payload and source digest lookup at 23,192 calls and 0.240 s on staging. Graph roles retain 2,154 calls and 0.352 s. Neither approaches the removed call volume. Evidence and assertions remains the largest semantic wall-time phase at 2.017 s, but further work there should profile hashing and computation rather than assume graph-store overhead.

This work does not change `_run_shacl`, the batched SHACL plan, parsing, public schemas, validation codes, messages, or golden observations.

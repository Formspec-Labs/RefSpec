# RDF parse substrate performance study

## Decision

**DONT-TAKE for the release validator now.** The winning prototype is real and substantial: on the 1,013,723-quad staging distribution, a two-index `rdflib.Store` plus pooled RDF terms cut parse-and-store time from 20.71 seconds to 14.78 seconds (28.6%) and peak resident set size (RSS) from 1,380 MiB to 567 MiB (58.9%). The complete graph-dependent validation path fell from a 49.21-second median to 33.71 seconds (31.5%) and from 1,434 MiB to 617 MiB (57.0%). It produced the same result as `rdflib` Memory on the real Atlas shapes and the full 130-case binding fixture corpus.

That gain does not clear the operating bar for a validator that runs once per release without an operator waiting. A conservative full-scale projection reduces the measured 1,373-second parse phase to about 980 seconds: 6.6 minutes saved per release. Taking the design would make RefSpec responsible for a custom RDF store and custom term-construction path. I estimate 8–12 engineering days to harden and integrate it. Preserve this prototype and reopen the decision if release duration or runner memory becomes a practical constraint.

The recommendation is about production ownership, not technical feasibility. The measurements show that `rdflib` Memory representation costs are a large part of the residual phase.

## Results at staging scale

All runs used the same five RDF packs and 1,013,723 asserted quads. Each reported sample ran in a fresh process on an Apple M4 Pro with 48 GB RAM, Python 3.12.9, `rdflib` 7.5.0, and pySHACL 0.31.0. The machine was shared, so the tables retain sample counts and use medians for three-sample comparisons. Two-sample avenue isolations use means. RSS is the process's peak resident memory, not retained heap.

The “semantic path” includes parse and store, the real [`atlas.shacl.ttl`](bindings/atlas/3.1/shapes/atlas.shacl.ttl), every graph-dependent semantic check, and compact-record ownership. It excludes only outer JSON admission. The benchmark calls the production parser and semantic functions directly; it does not replace pySHACL.

| Design | Parse + store | Peak RSS after parse | Complete semantic path | Peak semantic RSS | Conservative full parse projection | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Stock `rdflib` Memory | 20.71 s median, 3 runs | 1,380 MiB | 49.21 s median, 3 runs | 1,434 MiB | 22.9 min measured | Baseline |
| Memory + pooled terms | 16.74 s mean, 2 runs | Not isolated | 40.48 s mean, 2 runs | 1,078 MiB | 18.6 min | 17.7% path reduction |
| Two indexes + stock terms | 16.84 s mean, 2 runs | Not isolated | 38.14 s mean, 2 runs | 963 MiB | 18.7 min | 22.5% path reduction |
| Two indexes + pooled terms | 14.78 s median, 3 runs | 567 MiB | 33.71 s median, 3 runs | 617 MiB | 16.3 min | Winner; 31.5% path reduction |
| Two indexes with list leaves | 19.21 s, 1 run | 713 MiB | 50.18 s, 1 run | 767 MiB | 21.2 min, rough | Reject: memory improved, time did not |
| Two-worker sharded parse | 48.35 s parse + merge, 1 run | 2,042 MiB bounded peak | 118.93 s, 1 run | 2,042 MiB bounded peak | No defensible projection | Reject: slower and larger |

“Not isolated” means the parse timing came from inside the complete-path process, whose final RSS includes later validation allocations. Comparing its final RSS with the matching Memory process still shows the effect: pooled terms reduced peak path RSS by 24.8%, and the two-index store alone reduced it by 32.8%.

The raw samples, artifact digests, environment, query counts, and projection formulas are in [`measurements.json`](research/parse_substrate/measurements.json). The benchmark entry points are [`benchmark.py`](research/parse_substrate/benchmark.py) and [`parallel_benchmark.py`](research/parse_substrate/parallel_benchmark.py).

## Why two indexes are enough for this workload

`rdflib` Memory maintains subject-predicate-object (SPO), predicate-object-subject (POS), and object-subject-predicate (OSP) indexes, plus context bookkeeping. I instrumented every `Store.triples()` call made by the complete staging semantic path before choosing an index to remove.

| Triple pattern | Calls | Rows returned | Index used by the prototype |
| --- | ---: | ---: | --- |
| SPO | 91,252 | 63,887 | SPO |
| SP_ | 4,197,322 | 3,925,047 | SPO |
| S__ | 134,265 | 1,072,457 | SPO |
| _PO | 82,455 | 3,543,249 | POS |
| _P_ | 3 | 43,978 | POS |
| ___ | 8 | 1,013,724 | SPO iteration |
| S_O or __O | 0 | 0 | Fallback SPO scan, never reached |

The trace gives the design a narrow basis: SPO and POS are load-bearing for the current validator and real shapes; OSP is not. The prototype stores separate SPO and POS dictionaries for each named graph, derives complete iteration from SPO, and scans SPO if a future consumer makes an object-only query. It preserves set behavior, named contexts, namespace bindings, removal, and the `rdflib` Graph API surface exercised here. See [`TwoIndexStore`](research/parse_substrate/stores.py) and its parity tests in [`test_stores.py`](research/parse_substrate/test_stores.py).

This is a workload-specific result. It does not establish that OSP is unnecessary for arbitrary `rdflib` or pySHACL workloads. A new Atlas shape or graph check could change the query mix; production use would need a query-profile regression guard or a correct, measured fallback policy.

## Term pooling result

The parser prototype pools `URIRef` and `Literal` objects for each run, interns their lexical strings with `sys.intern`, and uses a slotted `Literal` subclass with a cached hash. `URIRef` already inherits Python `str.__hash__`, whose string object caches the computed hash; adding another URI subclass would duplicate that mechanism. The prototype leaves the parser grammar, normalization setting, and RDF term equality visible to consumers unchanged.

This avenue moved the result on its own: the complete path fell from 49.21 seconds to 40.48 seconds and from 1,434 MiB to 1,078 MiB. The paired parse measurements fell from about 20.61 seconds to 16.74 seconds. The gain confirms that repeated term construction, string storage, equality, and hashing materially contribute to the residual cost. It also shows why string interning alone would be an incomplete experiment: the measured prototype removes duplicate RDF term objects and caches literal hashes as one combined term-construction design.

The two-index store and term pool compound well. Together they remove more memory than either alone and reduce the complete path by 31.5%, compared with 17.7% for pooled terms alone and 22.5% for the store alone.

## Parallel pack parsing result

The five packs are badly imbalanced: the largest contains 856,733 quads, or 84.5% of the staging distribution. Even with zero worker and merge overhead, pack-level parallelism could improve this staging parse by at most about 1.18 times.

The measured bounded design used two subprocesses, one shard graph per process, a serialized store handoff, parent reload, and a read-only aggregate for validation. It completed the parse-and-merge portion in 48.35 seconds and the semantic path in 118.93 seconds. Peak RSS across the parent and live workers was 2,042 MiB. The worker outputs were 187.9 MB and 38.4 MB. Serialization, reload, aggregate query overhead, and pack skew outweighed concurrent parsing.

**Reject this design.** It is slower than stock Memory, uses more memory, adds failure and cleanup paths, and does not offer a defensible full-scale speed projection. Different full-scale pack proportions could improve balance, but they cannot remove serialization and aggregate-query costs demonstrated here.

## Other measured designs

Two additional ideas failed quickly:

- Replacing set leaves with lists reduced memory, but the complete path rose to 50.18 seconds. Repeated membership and traversal costs erased the storage gain.
- Caching `Dataset.get_context()` by a tuple key raised parse time to 48.80 seconds with 1,367 MiB RSS. Per-quad cache work cost more than creating the lightweight graph view.

The earlier Oxigraph route remains closed. The prior measured `oxrdflib` shim was 4.2 times slower and changed data; it cannot serve as a transparent pySHACL store. The current study therefore keeps the required `rdflib` Graph API and changes only its in-memory representation. The source findings are recorded in the [validation cost reset plan](plans/validation-cost-reset-plan.md#inside-the-phases-trace).

## Compatibility proof

The candidate passed three layers of checks:

1. The real 1,013,723-quad staging distribution ran through the production semantic path and the real Atlas SHACL shapes. Memory and the candidate returned the same acceptance result, including `quadCount=1013723` and `inferredMappingCount=5939`.
2. Both stores independently passed the full 130-case binding corpus: 13 valid cases, 117 invalid cases, and all 46 SHACL data cases with their pinned SHACL components. This is the mutation and negative-fixture oracle, not only a clean-data test.
3. Focused Graph API parity tests compare all eight bound/unbound triple patterns, named contexts, union behavior, duplicates, namespace bindings, removal, and graph removal against Memory. They pass under the measured dependency versions.

The proof covers the current validator, real shapes, and checked mutation corpus. It does not prove arbitrary `rdflib.Store` compatibility. Before production adoption, retain Memory as a copied test oracle and run both implementations over a full release artifact and the mutation corpus, as the repository guidance requires. Any deliberate difference must be a frozen, reviewed list rather than an ignored diff.

## Full-scale projection

The requested full-scale target is 29,283,283 quads. The prior full run measured 1,373 seconds for the stock parse-and-store phase. Staging data alone cannot establish the candidate's full-heap behavior, so I use a range:

- **Conservative: 980 seconds, or 16.3 minutes.** Apply the observed staging ratio, 14.78 / 20.71, to the measured 1,373-second full phase. This preserves all full-scale superlinearity in the baseline. It saves 393 seconds, or 6.6 minutes.
- **Optimistic: 641 seconds, or 10.7 minutes.** Scale the candidate staging time by quad count and apply the prior 1.5-times large-heap penalty. This assumes the candidate's smaller representation avoids any additional Memory-specific heap penalty. It saves 12.2 minutes against the supplied baseline.

The staging RSS ratio projects the 20 GB baseline to about 8.2 GB. Treat **8–10 GB as a planning estimate, not a result**. Full-scale term uniqueness, allocator behavior, and pySHACL working data can change the ratio. The next decision-quality experiment would be one full-scale paired run on an otherwise idle host, with phase-level RSS and exact output comparison.

I do not project the 31.5% staging semantic-path gain onto the whole validator. JSON admission, byte-level checks, hashing, and other phases do not use this store. The defensible benefit is the parse-phase range above; any additional graph-query saving remains upside until measured at full scale.

## Implementation cost and operational trade

Turning the prototype into supported code would take about 8–12 engineering days:

- 2–3 days to complete the `Store` behavior surface, event behavior, edge cases, and conformance tests;
- 2–3 days to integrate pooled term construction and test identity, equality, hashing, parsing errors, and serialization;
- 2 days for idle-host full-scale A/B runs, profiles, and result comparison;
- 1–2 days to add the Memory oracle, mutation gates, query-profile guard, documentation, and failure diagnostics.

The estimate excludes later maintenance when `rdflib`, pySHACL, or Atlas shapes change. The store is small, but it sits below every semantic verdict, so its testing burden is larger than its line count suggests.

For an unattended once-per-release task, a conservative 6.6-minute saving does not repay that ownership cost. Keep the prototype as measured evidence. Reconsider it if the full validation misses a release-service objective, the roughly 20 GB baseline blocks the intended runner, or validations become frequent enough for the saved time to accumulate.

## Measurement boundary and reproduction

The supplied output directory, `/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-mapping-topology-staging/distribution`, is shared read-only state. Another process rebuilt its outer metadata during this study. The distribution ID and all five RDF pack transport digests remained exact, but the rebuilt binding metadata came from a different revision and the current worktree correctly rejected that outer JSON before parsing. I copied the stable read-only packs to `/tmp/refspec-parse-substrate-staging` and ran later measurements through the complete graph-dependent path. An earlier unmodified stock acceptance run, before the rebuild, completed successfully in 48.79 seconds. No benchmark wrote to the main repository or its `output/` tree.

Representative commands, run from this worktree with the pinned Python environment on `PYTHONPATH`, are:

```sh
python research/parse_substrate/benchmark.py \
  --distribution /tmp/refspec-parse-substrate-staging \
  --phase parse --store memory-plain --terms stock

python research/parse_substrate/benchmark.py \
  --distribution /tmp/refspec-parse-substrate-staging \
  --phase semantic --store two-index-plain --terms interned

python research/parse_substrate/benchmark.py \
  --phase binding --store two-index-plain --terms interned

python -m pytest -q research/parse_substrate/test_stores.py
```

The prototypes are research code only. They do not modify [`validate.py`](bindings/atlas/3.1/tools/validate.py), the Atlas shapes, or production behavior.

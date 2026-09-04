<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/shacl-sparql` at `1c5f1d12`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# SHACL-SPARQL adjudication decision package

Date: 2026-08-13  
Repository baseline: `dae346da46706083b695cf232901b24e2d87cad5`  
Prototype: `research/shacl-sparql/shapes/adjudication.shacl.ttl`  
Raw results: `research/shacl-sparql/measurements.json`

## Decision

The four requested cross-record rules can be expressed as portable SHACL-SPARQL, and Apache Jena SHACL 6.2.0 and pySHACL 0.31.0 produced the same verdict on all 26 fixture checks. On a deterministic target-loaded version of the 1,013,723-triple mapping-topology staging view, Jena validated all four rules in a measured median 0.669 seconds, while pySHACL took 167.515 seconds: Jena was 250.4 times faster inside the validation call. Fresh-process wall time was 2.383 seconds for Jena and 194.312 seconds for pySHACL, an 81.6-times difference.

The earlier “about 100 times” result therefore survives as an order-of-magnitude finding, but not as one constant ratio: individual rules ranged from 37.5 to 228.5 times faster in Jena. More importantly, pySHACL's measured end-to-end time was 3.24 minutes at the specified staging scale. That is viable for a once-per-release check if this bounded mapping-topology artifact is the release input. Emitting these four queries does **not**, by itself, force immediate Jena adoption at that scale.

The implication changes for the 32-million-quad full Atlas release. The current plan records a measured 18.3 GB resident set size (RSS) during `rdflib` parsing and about 94 minutes for one bare pySHACL pass (`plans/validation-cost-reset-plan.md:266-273`). That path violates this study's 8 GB cap before these queries run. A simple size-proportional extrapolation from the target-loaded staging view is about 90 minutes of fresh-process wall time for these four queries alone; that is an estimate, not a benchmark, and SPARQL performance is not guaranteed to scale linearly. At full release scale, move 2 needs Jena or a smaller, proven validation graph before it can replace the Python checks.

## Findings

1. **Correctness passed at fixture scale on both engines.** Every requested invalid case failed its corresponding query. Four valid adjudication cases passed every query. Jena and pySHACL agreed on all 26 checks.
2. **The current staging artifact does not contain the records these queries target.** It has 2,003 `atlas:MappingAssertion` records, but zero `rkaf:RelationComparisonContext` and zero `rkaf:ResolverProofRecord` records. Its 2,003 mapping evidence bindings use `rkaf:formalAdoptionEvent`, not the machine-adjudication warrant. Timing the queries on the untouched artifact therefore measures parsing and target discovery, not their cost over real adjudication records.
3. **A target-loaded benchmark confirms a large but uneven Jena advantage.** The derived view preserved all staging triples and added one satisfied comparison plus two independent, lattice-consistent proofs per real mapping assertion. It contained 2,003 comparisons and 4,006 proofs. On that input, Jena's per-rule validation advantage ranged from 37.5 to 228.5 times; the four-rule median-run advantage was 250.4 times inside validation and 81.6 times end to end.
4. **The proposed “about 900 lines” deletion is not supported by the current source.** The entire contiguous adjudication block is 516 physical lines (`validate.py:4715-5230`), including artifact integrity, digest, release, endpoint, snapshot, and refusal checks that these four queries do not replace. The four rules account for an estimated 128 Python lines. The prototype is 164 physical lines, including 115 lines of SPARQL. This move is code-neutral at first; its value is single-source generation and shared engine execution, not an immediate 900-line reduction.

## What the prototype checks

The prototype uses the upstream `rkaf:` namespace (`https://rulespec.org/ns/v1#`) and only SPARQL 1.1 plus SHACL's pre-bound `$this`. It adds no RefSpec vocabulary.

| Shape | Target | Failure condition | Python behavior preserved |
| --- | --- | --- | --- |
| `FiveAxisIndependenceShape` | `rkaf:RelationComparisonContext` | A satisfied comparison has no cited proof pair that differs on issuer actor, independence group, issuer's resolver provider, lineage model ID, and sealed response artifact. | The all-five-axes pair search at `validate.py:4850-4877` and `validate.py:5184-5217`. |
| `CompleteSupportShape` | `rkaf:ResolverProofRecord` | The comparison named by `rkaf:proofComparisonContext` does not cite the proof through `rkaf:comparisonProofRecord`. | The issued-versus-cited equality check at `validate.py:5162-5171`. |
| `VerdictLatticeFoldShape` | `rkaf:RelationComparisonContext` | A satisfied comparison's complete cited verdict set does not fold to the expected assertion's stated SKOS relation. | `_adjudicated_relation` at `validate.py:4715-4745` and its comparison at `validate.py:5173-5182`. |
| `ProofReplayRefusalShape` | `rkaf:ResolverProofRecord` | Two distinct comparisons cite the same proof. | The proof replay refusal at `validate.py:5083-5089`. |

The lattice remains universal rather than a vote. `{verdictSame}` licenses `skos:exactMatch`; a nonempty subset of `{verdictSame, verdictNearSame}` containing `verdictNearSame` licenses `skos:closeMatch`; and the three directional/related branches require one homogeneous verdict value. Mixed directions, unlicensed relations, and empty support license nothing.

The queries deliberately rely on the binding's existing structural SHACL for required values, cardinalities, node kinds, classes, and closed shapes (`atlas.shacl.ttl:1294-1428` and `atlas.shacl.ttl:1514-1625`). Running these queries without those structural shapes would weaken the combined validator. The existing six-branch evidence-warrant closure remains the `sh:xone` at `atlas.shacl.ttl:1070-1135`; this prototype does not duplicate it.

These four rules are not the whole adjudication protocol. They do not replace, among other checks:

- one comparison per assertion (`validate.py:4993-4999`);
- machine-warrant licensing (`validate.py:5007-5016`);
- artifact, snapshot, endpoint, input digest, and sealed request consistency (`validate.py:5017-5159`);
- passed proof outcomes for a licensing comparison (`validate.py:5090-5095`); or
- the evidence-warrant refusal when no comparison licenses a claimed assertion (`validate.py:5219-5230`).

## Correctness evidence

The fixture corpus was regenerated with `bindings/atlas/3.1/tools/build_fixtures.py --check`; 2,084 files matched the committed receipt. Each fixture distribution was reduced to its asserted graph, then the relevant single prototype shape was run with pySHACL `advanced=True` and Jena. The measurements below are verdict observations, not estimates.

| Shape | Invalid fixtures caught by both engines | Valid fixtures passed by both engines |
| --- | --- | --- |
| Five-axis independence | `adjudication-single-proof`; `adjudication-same-validator-actor`; `adjudication-same-independence-group`; `adjudication-same-provider`; `adjudication-same-provider-model`; `adjudication-same-response-artifact` | `all-resource-profiles`; `qualified-three-machine-support`; `qualified-lattice-branches`; `adjudication-refused-comparison-record` |
| Complete support | `adjudication-discarded-support` | Same four valid fixtures |
| Verdict-lattice fold | `adjudication-relation-not-licensed`; `adjudication-verdicts-disagree` | Same four valid fixtures |
| Proof replay refusal | `adjudication-foreign-comparison` | Same four valid fixtures |

Result: **26 measured checks, zero failures, zero engine disagreements**. Each targeted invalid fixture produced one validation result in each engine. `adjudication-mismatched-sealed-request` was not assigned to these shapes because it exercises the separate “one sealed question” rule, which remains in Python.

This is a fixture-scale equivalence result, not authority to delete the Python oracle. Project guidance requires any replacement to keep a copied old implementation as a test-only oracle and prove agreement over real data plus a mutation battery (`AGENTS.md:20-31`). The current staging artifact cannot supply real positive adjudication records, so production deletion remains blocked on a target-bearing release artifact and a differential mutation suite.

## Benchmark input and provenance

The requested source path was read only. Before it disappeared during the study, its manifest reported:

- distribution ID `urn:ref:atlas:distribution:3.1-bounded-development:198a41c398de4a8f2240430ef648ecafe2519537d1739b3d6f52123c66386a56`;
- 1,013,723 asserted quads in five packs; and
- 2,003 mapping assertions.

Another process removed the source distribution after inspection. The benchmark therefore used the previous Jena spike's preserved flattened asserted view, which matches the captured manifest count: 1,013,723 N-Triples, 198,000,163 bytes, SHA-256 `08336c44b2945621b11f8dc999f6efdf331d64708104afc795186e8b1d4387c2`. Because the original pack files were no longer available, this study could not re-derive and byte-compare that view after measurement. The digest makes the exact benchmark input identifiable.

Two views were measured:

- **Untouched staging view:** the preserved 1,013,723 triples. It has no target instances for these shapes.
- **Target-loaded view:** a deterministic derivative made by appending 46,069 triples. It contains all original triples plus 2,003 satisfied comparisons and 4,006 proof records, two per real mapping. Each generated pair differs on all five axes, every proof is cited exactly once, and its verdict is selected from the mapping's real SKOS predicate. Total: 1,059,792 triples, 204,815,161 bytes, SHA-256 `a3fc6d669301ee37fd5bc1661ad4559e6d3405b1535ef27b33b756b4a6b394ba`.

The target-loaded view is artificial workload data. It measures the real queries over the real mapping topology with a transparent target count; it is not evidence that the staging artifact already contains conforming adjudication records. Both engines reported that all four shapes conform on this derived view.

## Timing results

Environment: Apple M4 Pro (14 cores), 48 GB RAM, macOS 26.6 arm64, Python 3.12.9, pySHACL 0.31.0, RDFLib 7.5.0, Temurin JDK 21.0.12+8, Apache Jena 6.2.0, and `-Xmx4g`. Child-process peak RSS came from `wait4`, not sampling. The largest measured peak was 1.775 GB, below the 8 GB limit.

### Untouched staging view

These are measured single runs. The view has zero query targets, so the sub-millisecond validation values do not describe adjudication-query scale.

| Shape | Jena validation (s) | Jena wall (s) | pySHACL validation (s) | pySHACL wall (s) |
| --- | ---: | ---: | ---: | ---: |
| Five-axis independence | 0.002 | 1.696 | 0.000 | 12.849 |
| Complete support | 0.002 | 1.621 | 0.000 | 12.843 |
| Verdict-lattice fold | 0.002 | 1.618 | 0.000 | 13.014 |
| Proof replay refusal | 0.002 | 1.645 | 0.000 | 12.933 |
| All four | 0.003 | 1.648 | 0.000 | 12.961 |

Jena used 547 MB peak RSS and pySHACL used 1,372 MB for the all-shapes process. No performance ratio from this table is meaningful for the four constraints because none ran against a focus node.

### Target-loaded staging view, one shape at a time

These are measured single runs. “Validation ratio” divides pySHACL validation time by Jena validation time. Wall time includes process startup, parsing, shape loading, validation, and teardown.

| Shape | Jena validation (s) | Jena wall (s) | pySHACL validation (s) | pySHACL wall (s) | Validation ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Five-axis independence | 0.311 | 1.990 | 27.345 | 41.226 | 87.9× |
| Complete support | 0.245 | 1.989 | 9.201 | 23.274 | 37.5× |
| Verdict-lattice fold | 0.268 | 1.925 | 61.224 | 75.054 | 228.5× |
| Proof replay refusal | 0.275 | 1.922 | 11.153 | 25.043 | 40.6× |

The result is shape-dependent. The verdict lattice dominates pySHACL time, while complete support and proof replay produce a smaller, still substantial Jena advantage.

### Target-loaded staging view, all four shapes

Jena ran five times and pySHACL ran three times. The table reports measured medians; run-level observations and ranges are in `measurements.json`.

| Measure | Jena | pySHACL | pySHACL / Jena |
| --- | ---: | ---: | ---: |
| Validation call | 0.669 s | 167.515 s | 250.4× |
| Inside process: parse + shapes + validation | 2.334 s | 192.655 s | 82.5× |
| Fresh-process wall, startup included | 2.383 s | 194.312 s | 81.6× |
| Peak RSS | 692 MB | 1,770 MB | 2.6× |

The pySHACL wall-time runs were 130.152, 195.136, and 194.312 seconds. The variation means the median is a better decision value than the fastest observation.

JVM startup can be reported three useful ways:

- **Included:** fresh-process Jena wall time was a measured median 2.383 seconds.
- **Strict Java launcher excluded:** the timer inside `main` was a measured median 2.334 seconds. This still includes Jena data and shapes parsing.
- **Fixed empty-process cost removed:** an empty-data process with all four shapes had a measured median wall time of 0.360 seconds, making the adjusted target-loaded wall time 2.022 seconds. This last number is derived from two measurements and removes Jena initialization, shape loading, an empty validation, and process overhead; it is broader than JVM startup alone.

Jena's pure validation phase after data and shape loading was 0.669 seconds. No comparable persistent-process server was introduced, so all primary wall-time comparisons retain the cost a release command would actually pay.

## Engine implication

At the specified 1.06-million-triple target load, pySHACL's measured median is **3.24 minutes per release** end to end, versus **2.38 seconds** for Jena. A three-minute release gate is operationally viable when releases are infrequent and the current Python process already brings RDFLib into memory. Jena nevertheless provides much more headroom and lower measured memory.

At the current 32-million-quad full-release tier, pySHACL is not viable under the stated 8 GB limit: the plan's existing run measured 18.3 GB during RDFLib ingest before these rules could finish. The size-proportional **estimate** for these four queries is about 89.5 minutes wall or 77.1 minutes inside validation, based on a 27.6-times increase from the target-loaded view to the 29,283,283-line asserted view. This estimate is only a planning bound; query joins and RDFLib allocation can scale nonlinearly. Combined with the recorded 94-minute bare-SHACL pass, it supports this practical rule:

- Move 2 may emit the portable queries without Jena only for a bounded validation view whose target-bearing release benchmark stays within an agreed time and memory budget.
- Move 2 may not make the full RDF release graph the pySHACL input under the current budget. For that path, selecting Jena—or proving an equivalently bounded input—is a pre-commit requirement.

This is narrower and better supported than “emitting any `sh:sparql` is choosing Jena.” Engine choice follows the release input and service level, not syntax alone.

## Compiler and maintenance implications

The 164-line Turtle file is readable as a prototype but should not become hand-maintained normative source. The verdict lattice is especially easy to drift because a valid branch combines a stated relation, a closed set of allowed verdicts, and, for `skos:closeMatch`, a required weaker verdict. A Rulespec compiler can maintain it if its intermediate model represents these semantics directly rather than accepting arbitrary SPARQL strings.

The compiler needs to emit:

1. a target class and outcome guard for rules that apply only to licensing comparisons;
2. dereferenced paths for the five proof axes, including issuer-to-resolver and lineage-to-model hops;
3. an existential pair with simultaneous inequality on every axis;
4. reverse-reference completeness and at-most-one-citing-comparison rules;
5. a closed verdict-set fold with exact, weakest-claim branch semantics;
6. stable shape IRIs, messages, and error identities; and
7. one negative fixture per independence axis and per lattice branch, plus engine-parity tests.

The vendored Rulespec package is the current source of truth (`vendor/README.md:14-24`, pinned at `pyproject.toml:18,29-34`). Its compiled SHACL `analysis/machine-adjudication.ttl` contains only prefixes and a generated-file header marked “Pattern C only”; it emits none of these cross-record rules. Therefore this work identifies a real compiler capability gap, not a new RefSpec-owned vocabulary layer.

Recommended generated-artifact checks are a byte-pinned compiler fixture, SHACL syntax validation, this two-engine fixture matrix, and differential agreement against a copied Python oracle over target-bearing real data plus mutations. If Jena becomes authoritative, pin the engine and version inside `bindingBundleDigest`, as the recorded spike already requires (`plans/validation-cost-reset-plan.md:963-967`).

### Deletion accounting

Measured source sizes:

- `_adjudicated_relation`: 31 physical lines;
- `_machine_adjudication_artifact_facts`: 24 physical lines;
- `_machine_adjudication_proof_facts`: 110 physical lines;
- `_check_machine_adjudication`: 345 physical lines;
- contiguous block from the fold through the checker: 516 physical lines; and
- prototype: 164 physical lines, of which 115 are inside SPARQL query strings.

The four rules' direct Python footprint is an **estimated 128 lines**, based on the fold, axis extraction/names, complete-support check, replay check, independence search, and lattice comparison. Deleting the whole 516-line block would also delete rules the prototype does not implement. No current 900-line deletion boundary was found. A future compiler could remove more Python only after it emits the rest of the protocol and the required oracle suite proves agreement.

## Architecture verdict

The input is an asserted RDF graph that has already passed the structural Atlas shapes. Each query follows `rkaf:` references across comparisons, proofs, issuers, lineage, and expected assertions. The output is an ordinary SHACL validation report. The fixture matrix checks meaning; the target-loaded benchmark checks cost.

The four required invariants are expressible without an engine extension, and both engines agree on the available mutation cases. The user-visible value is a release that cannot license a mapping from correlated proof runs, omitted proof evidence, an inconsistent verdict set, or a replayed proof.

The counterfactual matters: keeping these rules in Python avoids SPARQL engine dependence today, but preserves two independently maintained descriptions of the same upstream adjudication protocol. Generating the shapes from Rulespec removes that drift point only when the generated artifact, structural shapes, engine pin, and copied-oracle tests move together.

**Verdict:** proceed with compiler work for these portable constraints, but do not delete the Python implementation yet. Do not select Jena solely because the artifact contains `sh:sparql`; select it for the full-release path because current pySHACL memory already exceeds the limit and the target-loaded staging measurement shows an 81.6-times end-to-end advantage. For a bounded once-per-release mapping view, pySHACL remains technically viable at a measured 3.24 minutes.

## Reproduction

The harness writes only caller-supplied output paths. It reuses the prior spike's JDK and Jena launcher; it does not install either engine.

```bash
PY=/Users/mikewolfd/Work/spicy-regs/RefSpec/.venv/bin/python
JENA=/Users/mikewolfd/Work/spicy-regs/RefSpec/.claude/worktrees/agent-a7937c98dc15549c2/jena-spike/bin/jena

$PY bindings/atlas/3.1/tools/build_fixtures.py --check
$PY research/shacl-sparql/harness.py fixture-matrix --jena "$JENA"
```

To rebuild a flat view while the distribution exists, use `harness.py prepare DISTRIBUTION OUTPUT.nt`. To construct the measured target load, use `harness.py augment-staging BASE.nt TARGET.nt`. `measure.py` records exact process wall time and peak child RSS; `JenaBenchmark.java` separates Jena load, shape-load, and validation phases. The raw result file records input digests, every repeated all-shapes run, single-shape runs, and tool versions.

## Delivery boundary

This worktree contains the report, prototype, reusable harness, Jena timing helper, measurement wrapper, and raw measurements. It does not change runtime validation or the main repository. The disposable worktree's Git index lives under the parent repository's `.git/modules/...` directory, which this sandbox exposes read-only. As a result, the files could not be staged or committed from this session even though the checked-out branch is `research/shacl-sparql`. `CODEX_LOG.txt` and `PROMPT.txt` were pre-existing untracked files and remain untouched.

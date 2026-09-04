<!-- markdownlint-disable MD013 -->

# Branch report harvest, 2026-09-04

Twenty-one findings written between 2026-08-13 and 2026-08-31 that existed only as
`REPORT.md` at the root of a research branch, invisible to anyone reading `main`.
They are copied here verbatim, each with a header naming the branch and commit it
came from. No branch was deleted and no code was cherry-picked.

Why: these are answers to expensive questions, and most of them are *negative* —
engines evaluated and rejected. The cost of losing them is not lost code, it is
someone re-running a week-long evaluation because the verdict was unfindable.

**None of this is normative.** Each report states its own scope; several say
explicitly that they change no production reader, release, or requirement.

## The reports

| Report | From branch | Verdict as the report states it |
| --- | --- | --- |
| [Atlas source-fidelity auditor: NASA note kinds and E](research-auditor-language-scope.md) | `research/auditor-language-scope` | This branch delivers both requested auditor changes. |
| [Bulk vocabulary source-fidelity coverage report](research-coverage-bulk.md) | `research/coverage-bulk` | This batch adds independent source-fidelity comparisons for all four bulk |
| [Source-fidelity coverage design](research-coverage-dry.md) | `research/coverage-dry` | The current auditor covers 49 of the distribution's 110 construction units. |
| [JSON/API-capture coverage report](research-coverage-json.md) | `research/coverage-json` | This branch now has executable, independently parsed coverage for all 18 units in the JSON/API-capture batch: 1,436 Atlas records. Fifteen units use t |
| [`pattern-row-v2` source-fidelity coverage](research-coverage-patternrow.md) | `research/coverage-patternrow` | `pattern-row-v2/2.0` now covers all 42 construction units assigned to the |
| [Remaining source-fidelity readers](research-coverage-readers5.md) | `research/coverage-readers5` | This branch adds the five assigned reader kinds and 15 declarative source |
| [Full-scale TopBraid/TDB2 memory result](research-engine-fullscale.md) | `research/engine-fullscale` | The owner's fixed-JVM-cost explanation is insufficient. TDB2's stopped load |
| [SourceSpec fidelity coverage expansion](research-fidelity-coverage.md) | `research/fidelity-coverage` | This work raises declared construction-unit coverage from **24/110 to 27/110**. |
| [Fidelity coverage integration](research-fidelity-coverage--report2.md) | `research/fidelity-coverage` | Commit `f1b90b18` integrates the three missing SourceSpecs on the live primary |
| [Definition fidelity decision package](research-fidelity-definitions.md) | `research/fidelity-definitions` | advice only; no builder, auditor, binding, or release was changed |
| [Language-tag bug-class report](research-fidelity-langbugs.md) | `research/fidelity-langbugs` | The fix admits the full English BCP-47 family at source boundaries and emits |
| [Atlas English scope and annotation carry](research-fidelity-langbugs--report2.md) | `research/fidelity-langbugs` | This change makes Atlas's English-only product scope explicit and applies one |
| [Parse-observer campaign: graph-residual report](research-graph-residual.md) | `research/graph-residual` | The campaign removed the two requested per-record graph-query loops without changing validation results. |
| [ICPSR provenance walk](research-icpsr-provenance.md) | `research/icpsr-provenance` | All 112 ICPSR provenance findings were auditor defects. None was an Atlas |
| [Move 2: compiler-emitted adjudication checks](research-move2-compiler.md) | `research/move2-compiler` | Proceed with option **(b)**: keep each relational SPARQL query as an annotated |
| [RDF parse substrate performance study](research-parse-substrate.md) | `research/parse-substrate` | DONT-TAKE for the release validator now.** The winning prototype is real and substantial: on the 1,013,723-quad staging distribution, a two-index `rdf |
| [Residual pySHACL performance research](research-residual-shacl.md) | `research/residual-shacl` | Do not take another SHACL lift into the release validator. |
| [SHACL engine survey](research-shacl-engine-survey.md) | `research/shacl-engine-survey` | The wall stands.** No surveyed engine proves that it can evaluate the real |
| [Atlas 3.1 residual SHACL floor](research-shacl-floor.md) | `research/shacl-floor` | DON'T TAKE a production change from this study. |
| [Rust SHACL engine decision for Atlas 3.1](research-shacl-rust.md) | `research/shacl-rust` | Do not replace pySHACL with Rudof 0.3.8. |
| [SHACL-SPARQL adjudication decision package](research-shacl-sparql.md) | `research/shacl-sparql` | The four requested cross-record rules can be expressed as portable SHACL-SPARQL, and Apache Jena SHACL 6.2.0 and pySHACL 0.31.0 produced the same verd |

## Branches with no findings to harvest

Three were killed mid-run and carry only a prompt and a log, no report:
`research/coverage-csv-pdf`, `research/coverage-html-misc`,
`spike/oxigraph-substrate`. `spike/jena-shacl` carries a benchmark harness and
old `bindings/atlas/1.0` fixtures rather than a findings document; its verdict
is inside `research/shacl-engine-survey` above.

## What was deliberately NOT taken

The code on these branches stays on them. `spike/jena-shacl`'s bulk is a
superseded binding version (`bindings/atlas/1.0`; `main` carries 3.1 only). The
engine probes are single-use harnesses for engines the reports reject. Both
`archive/*` branches' only unique file is a `rulespec-conformance` wheel two
releases behind what `main` vendors.

One item was judged to have real engineering value and still not taken:
`research/move2-compiler` carries a digest-pinned generator for RuleSpec-owned
adjudication shapes in the *current* 3.1 binding, plus a test. It is not taken
because the adjudication gap it addresses was closed by another route (see the
decision ledger's adjudication-vocabulary rows), so it is a better maintenance
mechanism rather than a new capability, and it is three weeks stale against a
binding that has moved. Its report is harvested above; the code is not.


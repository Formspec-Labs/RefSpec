# Rust SHACL engine decision for Atlas 3.1

**Decision date:** 2026-08-13

**Binding tested:** RefSpec commit `b2b36bee80be7d2918e419ab63975ca680a3f9d6`

**Decision:** Do not replace pySHACL with a Rust engine from the evidence available
in this study.

This is a gate result, not a claim that Rust cannot solve the underlying problem.
All three engine candidates have source code corresponding to Atlas's minimum
SHACL features. None could be acquired and executed in this worktree, so none
passed the required runtime feature test. Consequently, none was eligible for
the exact corpus-parity or staging-cost tests. The one published example that
claims to combine Rudof with Oxigraph copies the graph through a large text
buffer instead of validating directly over the store.

## Candidate verdicts

| Candidate | Version and date | Status | Reason |
| --- | --- | --- | --- |
| [Rudof](https://github.com/rudof-project/rudof/releases/tag/0.3.8) | 0.3.8, released 2026-08-13, commit `cad3840` | **Documented-only** | Tagged source and W3C test entries cover the feature families, but no binary or cached source was present and the engine could not be run. Its test harness is meaningful, but no aggregate W3C result is published with the audited source. |
| [`shacl-rust`](https://docs.rs/crate/shacl-rust/0.2.11/source/Cargo.toml) | 0.2.11, dated 2026-07-31, source commit `590a9aa40d4d6f66fca58f707715d15a760d707e` | **Documented-only** | Published source covers the feature families and includes a native `IndexedGraph`; neither behavior nor W3C suite results could be run or verified. |
| [`oxirs-shacl`](https://docs.rs/crate/oxirs-shacl/0.3.1) | Published crate 0.3.1, 2026-06-06; repository tag [0.4.1](https://github.com/cool-japan/oxirs/releases/tag/v0.4.1), 2026-07-28, commit `8a32274` | **Documented-only** | Source covers the feature families, but no artifact was available to run. The 0.4.1 W3C integration test does not fail when suite cases fail, skip, or error. |
| [`oxigraph-cloud` Rudof pairing](https://github.com/chapeaux/oxigraph-cloud/blob/95d0613a9467d810b5d615930968d757b36669a8/crates/oxigraph-shacl/src/validator.rs) | Commit `95d0613a9467d810b5d615930968d757b36669a8`, 2026-04-06 | **Rejected** | It serializes every Oxigraph quad into one in-memory N-Triples `String`, drops graph names, and reparses the text into Rudof `RdfData`. It is not the direct Rust-engine-over-Rust-store path this study needs. |

No candidate was marked **tested**. The local toolchain was Rust 1.89.0 and Cargo
1.89.0 on Apple silicon. `cargo search shacl-rust` failed because the environment
could not resolve `crates.io`; no candidate executable, crate source, or usable
registry cache was present. The in-app browser was also unavailable. No candidate
artifact was downloaded, so there was no candidate archive to hash or build.
The raw acquisition record is
[`environment.json`](research/shacl-rust/raw/environment.json), and the dated
source audit is
[`candidate-source-audit.json`](research/shacl-rust/raw/candidate-source-audit.json).

## Gate 1: feature floor

The current Atlas shapes contain 37 `sh:NodeShape` declarations, 262 property
shapes, 20 sequence paths, and 19 sequence paths used with `sh:equals`. The
sealed corpus exercises 15 distinct SHACL constraint components. These values
come from
[`atlas-surface.json`](research/shacl-rust/raw/atlas-surface.json); its shapes
SHA-256 is
`af85315e9f6918d166ed24a0cef6d98820c4430c936178842382a3a1279c1abf`.

In the matrix, **source found** means that an implementation or a specific test
entry exists in the audited version. It does not mean the feature produced a
correct verdict. The required runtime half of every cell remains **not run**.

| Candidate | `sh:xone` | `sh:closed` | `sh:class` at scale | sequence path + `sh:equals` | `sh:in` | `sh:node` | datatype, pattern, minCount | Gate result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Rudof 0.3.8 | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | **Did not pass** |
| `shacl-rust` 0.2.11 | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | **Did not pass** |
| `oxirs-shacl` 0.4.1 tag | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | source found; not run | **Did not pass** |

The source evidence is specific:

- Rudof's tagged [node](https://github.com/rudof-project/rudof/blob/0.3.8/shacl/tests/core/node.rs), [property](https://github.com/rudof-project/rudof/blob/0.3.8/shacl/tests/core/property.rs), and [path](https://github.com/rudof-project/rudof/blob/0.3.8/shacl/tests/core/path.rs) tests name the required families. Its [W3C harness](https://github.com/rudof-project/rudof/blob/0.3.8/shacl/tests/shacl_testsuite.rs) returns an error on a produced-versus-expected report mismatch. I found the harness, not a published pass count for its pinned suite.
- `shacl-rust` has separate [constraint modules](https://docs.rs/crate/shacl-rust/0.2.11/source/src/validation/constraints/) and [sequence-path traversal](https://docs.rs/crate/shacl-rust/0.2.11/source/src/core/path.rs). Its experimental [native index](https://docs.rs/crate/shacl-rust/0.2.11/source/src/indexed_graph.rs) interns RDF terms and stores integer triple indexes, which addresses the Python object layout in principle. Source shape is not semantic or cost evidence.
- OxiRS has tagged [constraint](https://github.com/cool-japan/oxirs/tree/v0.4.1/engine/oxirs-shacl/src/constraints) and [path](https://github.com/cool-japan/oxirs/tree/v0.4.1/engine/oxirs-shacl/src/paths) modules. Its [W3C integration test](https://github.com/cool-japan/oxirs/blob/v0.4.1/engine/oxirs-shacl/tests/w3c_test_suite_integration.rs) asserts only that tests were discovered and categorized; it does not assert zero failures, skips, or errors. The 0.4.1 release notes also say fabricated W3C conformance results were removed.

The feature gate therefore stops the study. Source inspection rules out an
obvious missing module; only execution can establish property-path behavior,
logical-constraint semantics, report identities, and the roughly 590,000-instance
`sh:class` case.

## Gate 2: exact corpus parity

**Candidate result: not run, 0 of 132 cases evaluated for every candidate.**
No candidate can claim parity for `expected`, `firstIssue`, or
`shaclComponents`.

The task brief says the corpus contains 117 invalid cases. The authoritative
checkout contains **132 cases: 119 invalid and 13 valid**. The current reference
validator reproduced those counts exactly. Of the 119 refusals, 48 have
`firstIssue: shacl.data`, and every one records a sorted `shaclComponents` list.
The remaining refusals come from non-SHACL gates. A candidate integration must
therefore preserve the current validator around the engine and emit the exact
Atlas refusal identities; an engine merely finding similar violations is not
enough.

The normal `make test-atlas-v3` entry point could not read a sandboxed `uv` cache.
Using the reference checkout's existing virtual environment without modifying
that checkout, fixture materialization and the binding-local validator completed:

| Control measurement | Wall time | Peak child RSS | Result |
| --- | ---: | ---: | --- |
| Fixture build and receipt check | 16.978517 s | 109.516 MiB | 2,116 files matched |
| Full 132-case reference corpus | 30.738376 s | 79.672 MiB | 132 cases, 119 invalid |

These controls include fixture and full-validator work; they are not SHACL-only
engine benchmarks. Raw records are
[`reference-corpus-run.json`](research/shacl-rust/raw/reference-corpus-run.json),
[`reference-fixture-build.json`](research/shacl-rust/raw/reference-fixture-build.json),
and
[`reference-corpus-direct.json`](research/shacl-rust/raw/reference-corpus-direct.json).
[`compare_candidate_results.py`](research/shacl-rust/compare_candidate_results.py)
provides the exact case-by-case comparator for a future candidate adapter. Its
self-check compared the corpus with itself and reported 132 of 132 exact matches
in
[`parity-comparator-self-test.json`](research/shacl-rust/raw/parity-comparator-self-test.json).

## Gate 3: cost

**Not run, by design.** The study required both earlier gates to pass before a
candidate could consume the staging distribution. No candidate passed gate 1,
so no release build or staging validation was attempted. Peak RSS remained well
below the 6 GiB safety bound, and no full-scale work ran.

The supplied staging directory contains five compressed packs and 1,013,723
asserted quads. I hashed all pack transports and all four manifest members; every
stored-byte digest and byte length matches the manifest. The manifest itself is
SHA-256
`53f5b233b95618074612c8331ff2b47cd696e75c5ab4731ced3d5caa95b9cd2f`.
However, its binding records shapes digest
`724aefcf349c51b74af75387c638365502db2f4638e27aa16e5f241090c8d48c`,
which differs from this checkout's shapes digest. The artifact is internally
intact but not a current-binding staging input. A future like-for-like cost test
needs a staging artifact pinned to the candidate's exact binding. See
[`staging-distribution.json`](research/shacl-rust/raw/staging-distribution.json)
and the reproducer
[`probe_distribution.py`](research/shacl-rust/probe_distribution.py).

The 13.097 s residual-SHACL baseline, 11.652 s indexed baseline, and roughly
598 MiB whole-path peak in the task brief are supplied comparison values; this
study did not remeasure them and produced no candidate number to compare with
them.

## Honest cutover price

A passing Rust engine would still require a product change, not a one-line
engine swap.

The binding-local validator promises that a consumer can copy
`bindings/atlas/3.1/`, install its `requirements.txt`, and validate offline. A
compiled dependency changes that premise unless the binding also supplies a
trusted artifact for every supported Python version, operating system, and CPU.
A Rust-backed Python wheel can preserve the command-line experience, but offline
installation requires those wheels to be copied and pinned with the binding.
A separate executable adds process startup, path discovery, input/output,
failure, and version rules. Either approach adds platform builds, digest and
signature verification, license and software-bill-of-materials review, security
updates, and a policy for unsupported platforms. Requiring a local Rust toolchain
or a network build would destroy the copy-and-run consumer promise.

Before production deletion, the current pySHACL behavior must survive as copied
test-only oracle code rather than an import of the path being replaced. The new
adapter must prove exact verdict agreement on:

1. all 132 sealed cases, including `firstIssue` and sorted
   `shaclComponents`;
2. a current-binding real staging distribution; and
3. a mutation battery covering every required constraint and property-path
   family, with deliberate divergences frozen so a new one fails the suite.

That differential proof is required before the production path is removed. It
also needs native-storage evidence: peak RSS and time must cover load, shape
compilation, validation, report construction, and teardown, with no serialized
copy or Python RDF-term graph hidden outside the measured process.

## What would change the decision

The decision changes only when one candidate does all four:

1. runs every feature-floor probe successfully, including the large-target
   `sh:class` and sequence-path-plus-`sh:equals` cases;
2. reproduces all 132 corpus verdicts, exact `firstIssue` values, and exact
   `shaclComponents` lists through an Atlas adapter;
3. demonstrates staging time and peak RSS consistent with a native store, on an
   artifact pinned to the same binding, with all work included; and
4. ships verified offline artifacts without weakening the binding's copy-and-run
   consumer promise.

**A Rust engine does not yet break the Atlas wall; that changes only when a native engine passes the feature and exact 132-case gates, stays native at staging scale, and ships without weakening copy-and-run offline verification.**

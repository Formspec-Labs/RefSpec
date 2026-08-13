# SHACL engine survey

Survey date: 2026-08-13

Checkout: `b2b36bee80be7d2918e419ab63975ca680a3f9d6`

Branch: `research/shacl-engine-survey`

## Decision

**The wall stands.** No surveyed engine proves that it can evaluate the real
Atlas shapes with identical Atlas verdicts while beating the current 18.5
minute, 14.31 GiB acceptance run.

TopBraid SHACL 1.5.0 is the closest result. It finished the complete real shapes
at staging scale in 10.31 seconds over an in-memory Jena graph and 14.82 seconds
over TDB2, Jena's disk-backed store. It did not reproduce Jena SHACL's shape-
combination stall at that scale. Four injected-defect reports also agreed with
pySHACL on the result fields Atlas uses. That is enough to make TopBraid a real
candidate, not enough to replace pySHACL: it has not run the 132-case Atlas
corpus, and its TDB2 memory profile did not show the required native-storage
advantage.

The Jena 5.6 Core engine code did not reveal a regression in Jena 6.2. It was
11% slower than Jena 6.2 on the complete staging shapes and 10% slower on the
bounded label stress case. Neither version reproduced the pathology at bounded
scale. The prior Jena 6.2 result shows that the trigger depends on the full
graph, where the combined label shape exceeded 1,829 seconds while every
constituent stayed below 45 seconds. This survey did not repeat that prohibited
full-scale run, so it found no evidence that Jena 5.x clears the real failure.

The current landscape contains promising storage designs, especially
`shacl-rust`'s integer-ID graph, goRDFlib's Badger and SQLite stores, and rudof's
QLever backend. Those findings are documentation and source review, not Atlas
measurements. None passes the cutover bar.

## The result that would change this decision

A candidate must satisfy all three conditions in one reproducible study:

1. It finishes the unmodified `atlas.shacl.ttl` against the prepared real Atlas
   validation view at bounded scale.
2. It agrees with the current validator on all 132 sealed corpus cases,
   including the exact `firstIssue` and sorted `shaclComponents` values.
3. A multi-point resident-memory profile shows that validation uses compact or
   disk-backed native storage rather than retaining one language-level object
   per RDF term or rebuilding an equivalent working set.

Only then should the program authorize a full acceptance comparison against
18.5 minutes and 14.31 GiB. A fast conforming run, a W3C test-suite claim, a
small native database, or four matching defects satisfies only part of this
test.

| Candidate | Real shapes, bounded | 132-case Atlas parity | Native-memory profile | Decision gate |
| --- | --- | --- | --- | --- |
| TopBraid 1.5.0 + Jena memory | Yes | No; four defects only | No; object graph | Fails 2 and 3 |
| TopBraid 1.5.0 + TDB2 | Yes | No; four defects only | Tested, but not favorable | Fails 2 and 3 |
| Jena 5.6 Core overlay | Yes | No | No; Jena graph | Fails 2 and 3; no full-pathology evidence |
| Every other surveyed engine | Not run on Atlas | No | Documented at best | Fails at least 1 and 2 |

## Scope and evidence grades

This was a bounded survey. It made no production-code or normative-shape
changes. It did not run the roughly 25-minute build or a full-scale acceptance
run. Every child process used a 240-second process-group deadline and `-Xmx4g`;
the largest measured process stayed below 1.51 GiB resident set size (RSS).

The report uses three evidence labels:

- **Tested** means this worktree ran the named engine on the pinned input and
  saved wall time, process maximum RSS, exit status, and compact engine output.
- **Documented-only** means an official release, documentation, or tagged source
  supports the statement, but this worktree did not run Atlas through it.
- **Rejected** means the candidate lacks a required feature or storage path, or
  existing measurements already disqualify it. Rejection does not imply poor
  general-purpose SHACL quality.

The source inventory and links are preserved in
[`measurements/landscape-sources-2026-08-13.tsv`](measurements/landscape-sources-2026-08-13.tsv).

## Inputs and measurement method

The existing Jena spike supplied the data preparation, JDK, Jena distribution,
control shapes, and four defect fixtures. This survey did not write to the main
RefSpec checkout or its `output/` directory.

| Input | Measurement identity |
| --- | --- |
| Staging distribution | 1,013,723 quads, supplied by the existing spike |
| Prepared validation view | 1,014,090 triples; staging data plus 367 ontology-inoculation triples; SHA-256 `67b09829823ff2b3d6ca85041ff0f6f663ac12c4df9b90fc987ca54635dbdfcb` |
| Real shapes | 1,600 triples; SHA-256 `af85315e9f6918d166ed24a0cef6d98820c4430c936178842382a3a1279c1abf` |
| Label stress | 109,401 to 808,673 triples and 24,974 to 199,792 label focus nodes |
| Java | Temurin 21.0.12+8, already vendored in the Jena spike |
| Jena base | Verified Apache Jena 6.2.0 distribution, already vendored |

[`measurements/inputs.sha256`](measurements/inputs.sha256) records all shared
input hashes. [`probes/run_bounded.py`](probes/run_bounded.py) starts each probe
in a new process group, enforces the deadline, and records `ru_maxrss`. On macOS
that value is bytes and includes the process's heap, native allocations, and
resident mapped pages. It is the relevant process-level pressure, though it
does not separate those categories.

The timings are single bounded observations, not claims of low-variance
benchmarks. Their purpose is to detect termination, large pathologies, and
orders of magnitude. Full-scale extrapolation is deliberately absent because
the Jena failure is nonlinear.

## Named cell 1: TopQuadrant TopBraid SHACL

### Provenance

The tested engine source is the tagged [TopBraid SHACL API 1.5.0
release](https://github.com/TopQuadrant/shacl/releases/tag/v1.5.0), dated
2026-03-23 at commit `8811f78129a3f3fe0f586610324b60d834944f16`.
All 279 fetched source files matched their Git blob SHA-1. The release declares
Jena 6.0.0; this survey compiled the exact TopBraid source against the already
verified Jena 6.2.0 libraries. The optional Jelly-based tools package was not
available, so the probe used `ValidationUtil.validateModel`, the Java API behind
the engine, rather than the CLI wrapper. These qualifications are recorded in
[`measurements/topbraid-source-verification.txt`](measurements/topbraid-source-verification.txt).

### Does the combination pathology reproduce?

No, not at staging scale.

| Shapes | Validation seconds | Wall seconds | Peak RSS MiB | Verdict |
| --- | ---: | ---: | ---: | --- |
| `literalForm` only | 0.331 | 2.883 | 658.9 | Conforms |
| `sh:closed` only | 0.265 | 2.376 | 708.4 | Conforms |
| `sh:class` to the large instance set | 0.234 | 2.312 | 697.8 | Conforms |
| Verbatim combined label shape | 0.471 | 3.219 | 763.4 | Conforms |
| Complete real Atlas shapes | 8.068 | 10.309 | 1,504.2 | Conforms |

The combined shape remained in the same range as its constituents; the complete
shape file finished inside the bound. Raw records are in
[`measurements/topbraid-staging.jsonl`](measurements/topbraid-staging.jsonl).

This resolves the never-tested TopBraid cell at bounded scale: **tested, and the
Jena combination pathology did not reproduce**.

### Does a native store preserve that result?

Yes for termination and conformance, no for the required memory result.
TopBraid evaluated the same complete shapes directly over a fresh TDB2 model:

| Store | Load seconds | Validation seconds | Wall seconds | Peak RSS MiB | Store size MiB | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Jena memory | 2.178 | 8.068 | 10.309 | 1,504.2 | — | Conforms |
| TDB2 | 5.637 | 9.029 | 14.818 | 1,134.0 | 317.0 | Conforms |

TDB2 reduced RSS by 24.6% against TopBraid's in-memory run, but cost 43.7% wall
time. More importantly, it still used 1.89 times the current pySHACL staging
peak of 598.5 MiB. One staging point could hide a large fixed JVM cost, so the
survey also varied the number of label focus nodes while keeping the combined
shape unchanged:

| Triples | Focus nodes | Memory-model wall / RSS MiB | TDB2 wall / RSS MiB | TDB2 disk MiB |
| ---: | ---: | ---: | ---: | ---: |
| 109,401 | 24,974 | 0.97 s / 247.4 | 3.01 s / 699.4 | 196.7 |
| 209,297 | 49,948 | 1.37 s / 320.7 | 3.92 s / 735.4 | 222.7 |
| 409,089 | 99,896 | 2.20 s / 502.3 | 5.94 s / 797.9 | 250.7 |
| 808,673 | 199,792 | 3.94 s / 774.7 | 15.36 s / 1,356.0 | 308.2 |

The TDB2 file growth is modest across these points, but the validating process
does not stay near a fixed native-store baseline. At the largest point it used
75% more RSS and 3.9
times the wall time of TopBraid's memory model. This does not prove what a
29.3-million-quad run would do, but it fails the required positive test: there
is no measured basis to claim that TopBraid over TDB2 would beat 14.31 GiB.

Raw records and fixture identities are in
[`measurements/topbraid-tdb2-staging.jsonl`](measurements/topbraid-tdb2-staging.jsonl),
[`measurements/topbraid-label-storage-scaling.jsonl`](measurements/topbraid-label-storage-scaling.jsonl),
and [`measurements/label-storage-scaling-fixtures.txt`](measurements/label-storage-scaling-fixtures.txt).

### What verdict agreement was checked?

The four existing defect probes produced the same constraint component, focus
node, path, value, severity, and result count as pySHACL:

- `sh:xone`: one result; canonical reports identical.
- cardinality: one result; only the generated blank `sourceShape` identity
  differed.
- `sh:closed`: one result; canonical reports identical.
- combined defect: two results; only a blank `sourceShape` identity differed.

Atlas records `shaclComponents`, not blank shape-node identifiers. This is useful
evidence, but four defects are not the 132-case oracle. See
[`measurements/topbraid-defect-comparison.txt`](measurements/topbraid-defect-comparison.txt)
and [`measurements/topbraid-defects.jsonl`](measurements/topbraid-defects.jsonl).

**TopBraid verdict: Tested; retained as the only measured follow-up candidate,
but not qualified for cutover.**

## Named cell 2: Jena 5.x regression check

### Provenance and limitation

[Jena 5.6.0](https://github.com/apache/jena/releases/tag/jena-5.6.0) is the last
5.x release, dated 2025-10-10 at commit
`99267df18097141bd2ac27e2b14edc96226f0895`. No 5.x binary existed locally.
Shell DNS, the in-app browser download path, and Docker were unavailable, so the
survey did not claim an exact Jena 5.6 distribution run. It recorded Apache's
published SHA-512 but did not fetch the archive.

Instead, the probe fetched and verified the exact 5.6 `jena-shacl` tagged source
and compiled its Core engine, parser, paths, and report classes over the verified
6.2 base. It excluded compact syntax, `Imports.java`, and two SHACL-SPARQL files
whose Jena 5 ARQ builder API was removed in Jena 6. None is reachable from the
Atlas SHACL Core shapes. The exact qualification is in
[`measurements/jena-5.6-source-verification.txt`](measurements/jena-5.6-source-verification.txt),
and the build is reproducible with
[`probes/compile_jena5_engine_overlay.sh`](probes/compile_jena5_engine_overlay.sh).

### Measurements

| Engine | Input and shapes | Validation seconds | Wall seconds | Peak RSS MiB | Verdict |
| --- | --- | ---: | ---: | ---: | --- |
| Jena 6.2 exact | Staging, complete real shapes | 5.383 | 7.063 | 838.3 | Conforms |
| Jena 5.6 Core overlay | Staging, complete real shapes | 6.112 | 7.838 | 856.6 | Conforms |
| Jena 6.2 exact | Staging, combined label shape | 0.640 | 2.402 | 546.3 | Conforms |
| Jena 5.6 Core overlay | Staging, combined label shape | 0.691 | 2.552 | 574.2 | Conforms |
| Jena 6.2 exact | 199,792-focus stress, combined label | 0.637 | 2.391 | 799.8 | Conforms |
| Jena 5.6 Core overlay | 199,792-focus stress, combined label | 0.677 | 2.620 | 753.4 | Conforms |

The 5.6 overlay was 11.0% slower by wall time and 13.5% slower in validation on
the complete staging shapes. It was 9.6% slower by wall time on the label stress
case. Individual `literalForm`, `sh:closed`, and `sh:class` controls also
finished in 2.08–2.35 seconds under both engines.

Raw records are in
[`measurements/jena-6.2-staging.jsonl`](measurements/jena-6.2-staging.jsonl),
[`measurements/jena-5.6-engine-overlay-staging.jsonl`](measurements/jena-5.6-engine-overlay-staging.jsonl),
[`measurements/jena-6.2-label-stress.jsonl`](measurements/jena-6.2-label-stress.jsonl),
and [`measurements/jena-5.6-engine-overlay-label-stress.jsonl`](measurements/jena-5.6-engine-overlay-label-stress.jsonl).

The bounded answer is clear: no combination pathology and no Jena 5 advantage.
The full-trigger answer remains deliberately untested. Because Jena 6.2 already
passed these same bounded controls before failing nonlinearly at full scale, a
bounded Jena 5 pass cannot overturn that failure.

**Jena 5.x verdict: Tested as a qualified Core-engine regression; rejected as a
solution because it showed no bounded improvement and supplied no evidence on
the known full-scale trigger.**

## Current implementation landscape

Versions and dates below were checked on 2026-08-13. “Atlas Core” means the
needed `sh:xone`, `sh:closed`, `sh:class`, sequence-path `sh:equals`, `sh:in`,
and `sh:node`, not merely a package named SHACL.

TopBraid, Jena, pySHACL, RDF4J, Oxigraph, rudof, `shacl-rust`, OxiRS,
goRDFlib, and dotNetRDF all issued releases in 2026. `rdf-ext/shacl-engine` had
repository activity on 2026-08-09 but no numbered GitHub release;
`rdf-validate-shacl` last released 0.6.5 on 2025-05-30 and still had repository
activity in April 2026. Trav-SHACL last released in May 2025, while Corese's
latest numbered release was in December 2023. Maintenance therefore did not
eliminate the leading candidates; capability and storage evidence did. This
inventory also checks every non-pySHACL implementation named in the W3C Data
Shapes Working Group's [2024 charter](https://w3c.github.io/charter-drafts/2024/data-shapes.html).

| Candidate | Evidence | Atlas Core and N-Quads | Storage path | Survey verdict |
| --- | --- | --- | --- | --- |
| TopBraid SHACL API 1.5.0, 2026-03-23 | **Tested** | Real shapes parsed and conformed | Jena memory and TDB2 both tested | Closest candidate; corpus and memory gates fail |
| Apache Jena SHACL 6.2.0, 2026-07-27 | **Tested** | Core and N-Triples view tested | Jena memory; TDB is available | **Rejected:** prior full combination pathology |
| Apache Jena SHACL 5.6.0, 2025-10-10 | **Tested with qualification** | Core overlay tested | Jena memory | **Rejected:** no improvement; exact distribution/full trigger unproved |
| pySHACL 0.40.1, 2026-07-28; Atlas pins 0.31.0 | **Tested baseline; current release documented-only** | Required Core works and Atlas verdicts are authoritative | RDFLib Python object graph | **Rejected as the escape:** this is the measured wall; the newer release documents no new native-store path |
| Eclipse RDF4J 6.0.0, 2026-08-10 | **Documented-only** | Reads RDF formats and supports sequence paths, `sh:class`, `sh:in`, and `sh:node`; its official supported list omits required `sh:xone`, `sh:closed`, and `sh:equals` | `NativeStore` supports disk-backed bulk validation | **Rejected:** required Core coverage is absent. See [RDF4J SHACL documentation](https://rdf4j.org/documentation/programming/shacl/) |
| Oxigraph 0.5.9, 2026-06-18 | **Documented-only here; prior adapter tested** | N-Quads and SPARQL, but no native SHACL engine appears in the [project feature inventory](https://github.com/oxigraph/oxigraph) or tagged source | Excellent native store | **Rejected:** storage only. The prior oxrdflib adapter was 8.1x to at least 142x slower and diverged on verdicts |
| rudof 0.3.8, 2026-08-13 | **Documented-only** | Source represents all named Atlas components and sequence paths; CLI accepts N-Quads | Default eagerly loads `oxrdf::Graph`; optional QLever builds a compact on-disk index and validates through SPARQL-over-HTTP | Plausible follow-up only. The [QLever backend](https://raw.githubusercontent.com/rudof-project/rudof/0.3.8/docs/src/cli_usage/backend.md) requires a roughly 1 GB Docker image and has no Atlas evidence |
| `shacl-rust` 0.2.8, 2026-07-23 | **Documented-only** | Tagged source implements the named Core constraints and property paths; CLI is built on Oxigraph 0.5.5 | Default Oxigraph graph; experimental `IndexedGraph` interns terms and stores integer triple indexes in memory | Promising design, not a result. No Atlas run, persistent-store proof, or mature operating history. See [crate record](https://docs.rs/crate/shacl-rust/0.2.8) |
| OxiRS SHACL 0.4.1, 2026-07-28 | **Documented-only** | [Documentation claims all 27 Core components and full paths](https://docs.rs/oxirs-shacl/0.4.1/oxirs_shacl/) | Engine accepts a store interface, but the published CLI materializes parsed quads before validation | **Rejected pending independent proof:** the 0.4.1 release itself says fabricated SHACL conformance results were removed |
| goRDFlib 0.1.15, 2026-08-05 | **Documented-only** | Tagged source and README cover all named components, sequence paths, and N-Quads; project claims 98/98 W3C Core tests | Common store interface with memory, Badger, SQLite, and remote SPARQL implementations | Serious follow-up candidate, but explicitly active-development and unmeasured. Required dependencies were not cached locally, so no bounded run was claimed. See [release](https://github.com/tggo/goRDFlib/releases/tag/v0.1.15) |
| Trav-SHACL 1.9.0, 2025-05-06 | **Documented-only** | SPARQL-endpoint validator, but its [feature list](https://sdm-tib.github.io/Trav-SHACL/feature.html) explicitly omits `sh:node`, `sh:datatype`, `sh:hasValue`, and other Core constraints Atlas uses | Leaves RDF in a SPARQL endpoint and retrieves selected bindings | **Rejected:** the storage design could break the object wall, but the documented constraint subset cannot run Atlas's shapes |
| Corese 4.5.0, 2023-12-14 | **Documented-only** | Documents a SHACL validator and RDF parsers, but the public API pages do not establish complete Atlas Core coverage | Offers Jena TDB and RDF4J storage adapters; no evidence found that the SHACL evaluation path stays native | **Rejected pending new evidence:** older release, incomplete component documentation, and no Atlas or native-path measurement. See [release](https://github.com/Wimmics/corese/releases/tag/release-4.5.0) and [API overview](https://wimmics.github.io/corese/apis.html) |
| `rdf-ext/shacl-engine` main and `rdf-validate-shacl` 0.6.5 | **Documented-only** | JavaScript engines advertise Core over RDF/JS | `DatasetCore` returns RDF/JS quad and term objects; examples eagerly build the dataset | **Rejected:** no measured native-storage path and the object interface preserves the wall's basic shape |
| dotNetRDF 3.5.2, 2026-07-03 | **Documented-only** | Maintained SHACL API; N-Quads parsers exist | [`ShapesGraph.Validate` accepts an `IGraph`](https://dotnetrdf.org/api/html/M_VDS_RDF_Shacl_ShapesGraph_Validate.htm); persistent-store connectors do not give that validator a demonstrated native graph path | **Rejected:** no native-storage validation evidence |

Commercial database servers were not promoted as separate candidates. A remote
server with a SHACL feature is not an embeddable, reproducible replacement by
itself, and GraphDB's documented SHACL path is RDF4J's `ShaclSail`, which already
fails the required-feature screen. A future server candidate would still need a
pinned offline artifact, complete Core coverage, an N-Quads load path, and the
same Atlas proof.

## Honest cutover arithmetic

### The engine cannot express the complete Atlas verdict

The current sealed corpus contains 132 cases: 119 invalid and 13 valid. Forty-
eight cases have `firstIssue == "shacl.data"`; together they pin 15 distinct
`shaclComponents`. The rest prove JSON, canonical RDF, pack integrity, graph
placement, dataset relationships, reasoning, lifecycle, registry, and other
Atlas rules.

A generic SHACL report can provide `sh:sourceConstraintComponent`, which an
adapter can normalize to values such as `XoneConstraintComponent` and
`EqualsConstraintComponent`. It cannot emit Atlas refusal identities such as
`rdf.canonical`, `pack.content`, or `dataset.relation`, and it does not decide
which validation gate gets to be `firstIssue`. Those identities and the gate
order remain owned by the Atlas validator. Replacing pySHACL therefore means
replacing one internal engine and report decoder, not replacing the validation
pipeline.

This is why “both engines say nonconforming” is insufficient. The candidate
adapter must preserve:

- the exact first failing Atlas gate;
- the sorted, de-duplicated component list for every `shacl.data` case;
- literal equality and simple-literal versus `xsd:string` behavior;
- ontology inoculation and class-instance discovery;
- sequence-path value-node discovery;
- fail-fast versus whole-report equivalence; and
- report normalization where blank `sourceShape` identifiers legitimately
  differ.

The corpus counts above come directly from
[`bindings/atlas/3.1/fixtures/corpus.json`](bindings/atlas/3.1/fixtures/corpus.json).
The release-tier parity test in
[`tests/test_atlas_v3_validator_regressions.py`](tests/test_atlas_v3_validator_regressions.py)
already defines the component-level comparison. REF-029 in the
[`decision ledger`](docs/decisions.md#ref-029-contract-identity-and-proof-identity-are-two-different-digests)
explains why the corpus identifies the proof event rather than the rules.

### The old implementation remains part of the proof

Repository policy requires a replacement to keep the old implementation as a
test-only oracle, copied into the test rather than imported from the production
path. The new and old checks must agree on real data and a deliberate mutation
battery before production deletion. Any accepted difference becomes a frozen
list so another divergence fails the suite. The working example is
[`tests/test_atlas_v3_canonical_line_grammar.py`](tests/test_atlas_v3_canonical_line_grammar.py),
where 29,283,283 clean lines did not expose a rejection difference but mutations
did.

For a SHACL replacement, the mutation battery must cover every used component
and the interactions that already proved dangerous: `sh:xone`, `sh:closed`,
large `sh:class` targets, sequence-path `sh:equals`, `sh:in`, nested `sh:node`,
literal forms, multiple simultaneous failures, focus-node discovery, and value-
node discovery. The four TopBraid defects are the start of that battery, not its
completion.

### Estimated engineering cost

These are engineering-day estimates, not measured runtime. They assume no
normative shape change and exclude review queue time. A Rust, Go, or QLever
candidate has a wider range because no Atlas adapter exists and its report and
store behavior are unmeasured.

| Required work | TopBraid/TDB2 | New Rust, Go, or QLever path |
| --- | ---: | ---: |
| Pin and verify distributable artifacts, licenses, JDK/runtime, and offline build | 1–2 days | 2–4 days |
| Build the project-owned engine adapter, native load path, ontology inoculation, deadline, and cleanup | 3–5 days | 6–10 days |
| Normalize reports into Atlas component identities and preserve gate ordering | 2–4 days | 3–6 days |
| Run and repair exact parity over all 132 corpus cases | 2–4 days | 4–7 days |
| Build the real-data mutation battery and freeze reviewed divergences | 3–5 days | 5–9 days |
| Repeat bounded time/RSS scaling and package the receipts | 2–3 days | 2–4 days |
| Add CI/release-tier oracle operation, failure diagnostics, and rollback | 2–3 days | 3–5 days |
| **Before full-scale authorization** | **15–26 days** | **25–45 days** |

After those gates pass, a separate controlled full acceptance comparison and
review would cost another one to two engineering days plus the reserved machine
window. During the proof period the program pays both implementations: the old
engine remains the oracle and no current path can be deleted. This is a real
switching cost, not cleanup that can be deferred until after cutover.

TopBraid is cheaper to investigate because it already passes the bounded real-
shape gate and produces familiar SHACL reports. It is not currently justified:
the missing corpus proof is material, and its measured TDB2 resident set grows
with the validation workload instead of demonstrating the sought memory model.

## Reproduction map

- [`probes/TopBraidValidate.java`](probes/TopBraidValidate.java) runs the
  in-memory TopBraid API.
- [`probes/TopBraidValidateTdb.java`](probes/TopBraidValidateTdb.java) runs the
  same engine over a fresh TDB2 model.
- [`probes/compile_topbraid.sh`](probes/compile_topbraid.sh) compiles the verified
  release source and both runners against the vendored Jena distribution.
- [`probes/JenaValidate.java`](probes/JenaValidate.java) holds the common Jena
  API runner used for both generations.
- [`probes/compile_jena5_engine_overlay.sh`](probes/compile_jena5_engine_overlay.sh)
  rebuilds the qualified Jena 5.6 overlay.
- [`probes/amplify_label_fixture.py`](probes/amplify_label_fixture.py) creates the
  bounded focus-node stress data from the pinned staging view.
- [`probes/run_bounded.py`](probes/run_bounded.py) supplies the timeout and
  process resource receipt.

No downloaded engine source, compiled classes, prepared data, or TDB directory
is committed. They remain ignored scratch under `build/shacl-engine-survey/`.
The committed source-verification receipts and input digests make clear what was
used and what was not.

## What must change before this question is worth reopening

Reopen the engine survey only when at least one of these events occurs:

- Oxigraph or another compact native RDF store ships a maintained native SHACL
  Core engine with the Atlas-required components, avoiding an RDFLib-style term
  reconstruction adapter.
- TopBraid or Jena ships and identifies a fix for the combined-shape pathology,
  and its native-store path shows bounded resident memory across increasing
  Atlas focus-node counts.
- One of `shacl-rust`, goRDFlib, rudof/QLever, or OxiRS publishes independent
  conformance evidence and a direct compact-store validation path mature enough
  to pin and reproduce offline.
- pySHACL/RDFLib gains an integer-ID or encoded-store execution interface that
  batches discovery without rebuilding Python terms for fine-grained lookups.

A version bump, a faster toy benchmark, or W3C-suite conformance alone is not a
reason to repeat the survey. The new fact must address native storage, the Atlas
shape combination, or exact Atlas verdict identity; then the three-part test at
the top of this report applies unchanged.

**The wall stands.**

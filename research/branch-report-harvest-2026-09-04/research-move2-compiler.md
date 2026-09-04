<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/move2-compiler` at `aa6b9030`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# Move 2: compiler-emitted adjudication checks

Date: 2026-08-13

RefSpec branch: `research/move2-compiler`

RefSpec baseline: `ed4d5f9a5f0f513d7238e8ea52ffa0adc8a3a8fd`

RuleSpec baseline: `c584a1d9fcb89fb8c4253b5bb6879741b0e24c1c`

RuleSpec prototype commit: `28b37d7be3b28c3fd944188c3857699012074a14`

Raw oracle results: `research/move2/measurements.json`

## Decision

Proceed with option **(b)**: keep each relational SPARQL query as an annotated
multiline string in the RuleSpec CUE file that defines the records, and make
the compiler generate the SHACL node and constraint scaffolding. The generated
files ship through the existing `rulespec-conformance` wheel. RefSpec copies
those files into its standalone binding as digest-pinned data and executes
them with its existing SHACL engine.

Do **not** delete the Python oracle yet. The prototype proves compiler output,
wheel delivery, copy-and-run consumption, the 130-case binding corpus, and a
20-case mutation battery. It does not satisfy the required real-data half of
the replacement policy because no measured artifact contains real
`rkaf:RelationComparisonContext` and `rkaf:ResolverProofRecord` records.

The practical result is that move 2 is technically viable and bounded. The
remaining work is a production cutover, not a compiler research project.

This design preserves the accepted boundaries in REF-026 through REF-029:
RuleSpec owns the generic meaning, RefSpec ships an independent binding,
generated rule bytes change contract identity, and the corpus records proof
identity separately.

## Findings

1. **CUE record structure cannot mechanically generate these four relational
   queries.** The current compiler model describes one JSON-LD record at a
   time. The four rules need reverse references, joins through issuers and AI
   lineage, an existential pair with five simultaneous inequalities, and a
   set-wide verdict fold. None of those meanings exist in the current CUE
   structure. Inferring them from field names would create hidden semantics in
   compiler code rather than a source of truth.
2. **Annotated query text is viable.** RuleSpec CUE now owns the stable shape
   name, target class, message, and SPARQL `SELECT`; the compiler validates the
   annotation and emits Turtle scaffolding. The two source files emit four
   parseable shapes and add no Atlas term upstream.
3. **The wheel path works.** A scratch virtual environment installed only the
   locally built `rulespec-conformance` 0.2.0-pre.10 wheel. The installed
   resource API found two SHACL-SPARQL files and the package self-check found
   all 58 JSON Schemas, 58 structural SHACL files, 2 relational SHACL files,
   8 hand-authored shape files, 78 enums, and 859 terms.
4. **RefSpec remains copy-and-run.** Its validator imports neither
   `rulespec_conformance` nor RefSpec package code. A development-only refresh
   tool reads the installed wheel and writes plain Turtle plus a canonical
   lock file into the binding. The runtime reads only those local files.
5. **The differential mutation obligation passes at fixture scale.** The
   copied Python oracle and each generated shape agreed on 14 corpus graphs
   and 20 purpose-built mutations: 136 rule comparisons, zero disagreements.
6. **The deletion is still about 128 Python lines, not 900.** The four queries
   replace only independence, issued-proof citation completeness, proof replay,
   and verdict folding. Artifact integrity, sealed-request consistency,
   digests, snapshots, endpoints, proof outcomes, and refusal rules remain in
   Python. The immediate benefit is one authored rule and elimination of the
   Python-versus-RuleSpec drift class, not a large net line reduction.
7. **Existing RuleSpec relational shapes need a deliberate migration.** The
   hand-authored RuleSpec suite already contains related independence,
   comparison-binding, and complete-support rules. Their scope and queries are
   not identical to the four RefSpec rules. The generated output is therefore
   packaged separately and is not loaded into RuleSpec's own gate yet. The
   prototype also uses distinct shape IRIs, avoiding accidental RDF graph
   merging. Production cutover must reconcile and retire the overlaps under
   the same differential policy.

## Evidence map

| Evidence | Location |
| --- | --- |
| Reproducible RuleSpec compiler commit | [`research/move2/rulespec-compiler.patch.gz`](research/move2/rulespec-compiler.patch.gz) |
| Generated consumer data | [`bindings/atlas/3.1/shapes/rulespec-adjudication.shacl.ttl`](bindings/atlas/3.1/shapes/rulespec-adjudication.shacl.ttl) |
| Package and byte pins | [`bindings/atlas/3.1/shapes/rulespec-adjudication.lock.json`](bindings/atlas/3.1/shapes/rulespec-adjudication.lock.json) |
| Development refresh and currency check | [`bindings/atlas/3.1/tools/refresh_rulespec_adjudication_shapes.py`](bindings/atlas/3.1/tools/refresh_rulespec_adjudication_shapes.py) |
| Standalone consumer integration | [`bindings/atlas/3.1/tools/validate.py`](bindings/atlas/3.1/tools/validate.py) |
| Copied oracle and mutation battery | [`research/move2/oracle_harness.py`](research/move2/oracle_harness.py) |
| Machine-readable results | [`research/move2/measurements.json`](research/move2/measurements.json) |

## Option assessment

| Option | Verdict | Reason |
| --- | --- | --- |
| (a) Generate the full query from ordinary CUE structure | Not viable for these rules without first designing a relational constraint language | The compiler sees fields and local cardinalities; it has no representation for reverse edges, graph joins, existential pairs, or verdict-set folds. A special-case generator would merely move a second hand-written implementation into Python. |
| (b) Carry SPARQL as annotated CUE strings and generate scaffolding | **Chosen and prototyped** | The query remains beside the generic RuleSpec definitions, the compiler owns stable output, the wheel can publish it, and consumers execute the same bytes. |
| (c) Author relational rules beside CUE and enforce currency | Viable fallback, not chosen | It can work, but it preserves two source locations and requires the kind of cross-file currency check move 2 is intended to eliminate. It adds no benefit for these portable SPARQL 1.1 rules. |

Option (b) is not presented as “full generation.” The compiler does not derive
the query or parse its semantics. It rejects malformed annotation headers,
duplicate names, missing targets/messages, queries that do not select `$this`,
and unsafe Turtle long-string terminators. RDF parsing, fixture execution, and
the differential suite check the emitted result. A future relational CUE
language could replace the strings, but it is not required for move 2.

## Compiler output

The RuleSpec changes add a `shacl-sparql` compiler target. CUE definitions
whose names end in `ShapeSparql` contain:

```text
targetClass: rkaf:RelationComparisonContext
message: Human-readable failure
---
SELECT $this WHERE { ... }
```

`tools/compile_all.sh` detects those annotations and writes only their source
files to `compiled/shacl-sparql/<family>/<name>.ttl`. The four emitted shapes
are:

- `rkaf:MachineAdjudicationFiveAxisIndependenceShape`
- `rkaf:MachineAdjudicationIssuedProofCitationShape`
- `rkaf:MachineAdjudicationVerdictLatticeFoldShape`
- `rkaf:MachineAdjudicationProofReplayShape`

The compiler source is generic: the queries use only `rdf:`, `skos:`, and
`rkaf:`. No `atlas:` term or RefSpec path entered RuleSpec.

The generated output stays separate from structural SHACL. That separation is
intentional until the older hand-authored relational rules complete their own
oracle-backed migration. It prevents a package consumer from unknowingly
running both old and new formulations during this prototype.

## Packaging proof

The package resource API now exposes:

```python
resources.shacl_sparql(name, family="analysis")
resources.shacl_sparql_names(family="analysis")
```

`pyproject.toml` already force-includes the complete `compiled/` tree, so the
new target needed no second package-data mechanism. RuleSpec version
0.2.0-pre.10 produced:

- wheel: `rulespec_conformance-0.2.0rc10-py3-none-any.whl`
- SHA-256: `0d72e88d465bd6d0da77272f153f482580ca4c30174f7d8576967107c93b7775`
- installed-wheel result: PASS from an empty scratch virtual environment
- packaged relational files: 2

The exact `make test-package` wrapper was not usable because this sandbox
cannot read part of the global `uv` cache. The equivalent package boundary was
run directly: build the wheel, create a scratch environment outside either
checkout, install the wheel with no dependencies, change into that scratch
directory, and run `python -m rulespec_conformance.contract`. That proves the
accessors resolve installed package data rather than falling back to a source
tree.

## RefSpec consumer design

The data path is:

```text
RuleSpec CUE annotations
    -> constraints_compile.py / compile_all.sh
    -> compiled/shacl-sparql/*.ttl
    -> rulespec-conformance wheel resource API
    -> refresh_rulespec_adjudication_shapes.py
    -> local Turtle + lock in bindings/atlas/3.1/shapes/
    -> standalone validate.py SHACL graph
```

The digest pin lives at
`bindings/atlas/3.1/shapes/rulespec-adjudication.lock.json`. It records the
RuleSpec package version, each source resource accessor, byte length and
SHA-256 digest, and the combined local Turtle path, byte length and digest.
For this prototype the combined output digest is
`sha256:aba05d35d0f09955628694305e8a79eed965b4462566b6abcea048caede9901b`.

Both the Turtle and lock participate in the binding's `contractDigest`. The
Atlas shape file and generated RuleSpec shape file together determine
`shapesDigest`. The validator verifies the canonical lock before parsing the
two Turtle files into one graph. A stale or edited generated file therefore
fails locally and also changes the binding identity.

The package dependency is needed only while refreshing the binding. The
binding directory remains independently distributable: `validate.py` reads
the generated bytes but imports no package. An AST test makes that independence
an executable requirement.

### What the Python code becomes

Nothing is deleted in this prototype because the replacement policy requires
the old code as an oracle until real-data and mutation agreement both exist.
At production cutover:

- the five-axis pair search becomes
  `MachineAdjudicationFiveAxisIndependenceShape`;
- the check that every issued proof is cited by its named comparison becomes
  `MachineAdjudicationIssuedProofCitationShape`;
- replay refusal becomes `MachineAdjudicationProofReplayShape`;
- `_adjudicated_relation` and its comparison to the stated SKOS relation
  become `MachineAdjudicationVerdictLatticeFoldShape`; and
- the copied reductions remain only in the test oracle, never imported from
  the runtime code being replaced.

The fixture builder now records the ten targeted invalid cases as first
failing at `shacl.data`; the Python gate remains responsible for every other
adjudication case, including mismatched sealed requests.

## Differential oracle

`research/move2/oracle_harness.py` copies and reduces the old Python behavior.
It imports neither `validate.py` nor RuleSpec compiler code, so agreement is
not circular. It executes each generated shape independently and compares its
named failures with both the Python result and an explicit expected set.

Measured result with pySHACL 0.31.0:

| Input | Cases | Four-rule comparisons | Result |
| --- | ---: | ---: | --- |
| Existing fixture corpus | 14 | 56 | PASS |
| Deliberate mutation battery | 20 | 80 | PASS |
| Total | 34 | 136 | PASS, zero disagreements |

The mutations cover every independence axis; one proof; discarded support;
proof replay; exact/close disagreement; close without a near verdict; valid
and invalid broad, narrow, and related branches; an unsupported relation; and
the refused-comparison guard. Measured wall time was 2.686 seconds and peak RSS
was 58.8 MiB.

The complete binding corpus also passed on the current generated bytes:
130 cases, 117 invalid cases, 35.278 seconds, and 88.1 MiB peak child RSS. The
fixture builder wrote 2,084 files and its 24-input receipt passed `--check`.
All bounded runs remained far below the 6 GB limit.

### What “real data” must mean

The prior SHACL-SPARQL study found zero
`rkaf:RelationComparisonContext` and zero `rkaf:ResolverProofRecord` targets in
the measured staging artifact. Its derived target-loaded view was useful for
performance, but its generated proof records were artificial. The fixture
corpus and this mutation battery are also synthetic by design.

A qualifying real-data artifact is the next sealed Atlas 3.1 release candidate
built from actual resolver executions under the machine-adjudication warrant,
with real comparison records, proof records, request/response artifacts,
lineage, issuers, and observed verdicts in its asserted graph. In repository
terms, that would be an `output/atlas-3.1-full-<release>/` artifact whose
producer actually emits those targets—not a derived target-loaded benchmark.
No artifact measured for this work meets that definition. Until one does, the
old Python implementation remains production code and test oracle.

## Cost and value

The remaining software work is approximately **3–5 engineering days**:

1. review and land the RuleSpec compiler/package change;
2. reconcile the existing hand-authored RuleSpec relational shapes, retaining
   copied oracles until mutation and real-data parity pass;
3. publish or otherwise pin 0.2.0-pre.10 and refresh RefSpec from that exact
   package;
4. run the cross-engine fixture matrix from `research/shacl-sparql` against the
   final generated bytes; and
5. run the differential harness on a qualifying target-bearing release, then
   delete only the four proven Python portions.

Producing real machine-adjudication records is the schedule uncertainty. If
the resolver execution and sealing path already exists, qualifying one release
should fit inside those days. If that producer path must be built, allow
**one to two additional weeks**; that is data-production work, not compiler
work.

The roughly 128-line deletion buys:

- one RuleSpec-authored query per rule;
- identical generated bytes for every consumer;
- package version and byte-level provenance;
- removal of the 4-versus-5-axis and Python-versus-SHACL drift class; and
- a smaller downstream responsibility: load data, run the engine, report the
  result.

This remains code-neutral at first: the generated Turtle is 168 physical
lines, before counting compiler, package, refresh, and oracle code. The value
comes from deleting independent implementations after the oracle obligation
passes, not from reducing the prototype's line count.

It does not buy faster validation by itself. The previous branch measured the
four queries at about 3.24 minutes in pySHACL over a 1.06-million-triple
target-loaded staging view, which is viable once per release. It also showed
that the 32-million-quad full RDF path exceeds the memory budget before these
queries finish. Production must therefore retain the bounded validation view
or select the already-measured Jena path for full-release execution.

## Production blockers

1. **No real target-bearing release evidence.** This blocks deletion under the
   binding oracle policy.
2. **Existing RuleSpec hand-authored overlaps are not migrated.** Loading all
   generated and hand-authored relational shapes together is not yet the
   supported RuleSpec gate.
3. **The package version is not published or pinned by RefSpec.** This branch
   proves an installed local wheel and commits the generated data; it does not
   publish a package.
4. **The final engine/input pairing is not selected for the full release.** A
   bounded once-per-release pySHACL run is measured viable; the full RDF graph
   needs Jena or another proven bounded view.
5. **The real RuleSpec Git metadata was not writable in this sandbox.** The
   requested linked worktree could not create its branch or worktree
   administrative directory under `/Users/mikewolfd/Work/rulespec/.git`.
   The main checkout remained untouched. The same baseline was cloned into a
   local Git mirror, committed there on `research/move2-compiler` as
   `28b37d7be3b28c3fd944188c3857699012074a14`, and exported as
   `research/move2/rulespec-compiler.patch.gz` (SHA-256
   `6c8c95796084d246e1c52010c67ffdf155c5148d55f05c44646d4d9bbdf34a6d`).
   Running `gzip -dc rulespec-compiler.patch.gz | git am` in a real RuleSpec
   worktree reproduces the compiler commit; it is not the same as having
   landed the upstream branch.

## Verification record

- RuleSpec CUE vet, both package invocations: PASS.
- RuleSpec focused compiler and package-resource tests: 9 PASS.
- RuleSpec version synchronization and `git diff --check`: PASS.
- Installed-wheel package check from scratch: PASS.
- RefSpec generated-data currency check from the installed wheel: PASS.
- RefSpec focused load, digest identity, and import-independence tests: 4 PASS.
- RefSpec lint on every changed Python file: PASS.
- Fixture materialization and direct `--check`: PASS, 2,084 files / 24 inputs.
- Differential corpus plus mutation harness: PASS, 136 comparisons.
- Standalone 130-case Atlas binding validation: PASS.
- One pytest wrapper around the fixture check could not start `uv` because the
  sandbox denied access to `/Users/mikewolfd/.cache/uv/sdists-v9/.git`; the
  same builder `--check` passed directly in the pinned project environment.

## Delivery boundary

This RefSpec branch contains the consumer prototype, generated binding data,
currency lock, updated fixture receipt/corpus, differential harness and raw
measurements, the exportable RuleSpec patch, and this report. It does not
publish RuleSpec, delete the Python runtime checks, activate a production
release path, push either repository, or claim real-data parity. The main
RefSpec and RuleSpec checkouts were read only. Pre-existing untracked
`CODEX_LOG.txt` and `PROMPT.txt` remain untouched.

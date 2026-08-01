# LadybugDB vocabulary-atlas spike — 2026-07-31

This report preserves the pre-split v5 experiment. Its document-oriented tables
are historical. RefSpec now owns the vocabulary-only static atlas and lookup
projection; SpicySearch owns document retrieval and ranking.

## Result

LadybugDB is technically viable as a disposable read model for the audited
vocabulary atlas. The spike built one 50,057,216-byte database from the sealed
N-Quads, reopened it read-only, and matched the RDF baseline for all four
representative query families.

Do not replace the canonical RDF artifact yet. Adopt Ladybug only behind the
existing query boundary, pin the runtime, rebuild it once per atlas generation,
and retain RDF parity tests. Ladybug 0.19.0 returned an incorrect path for the
documented `is_acyclic(path)` filter in this dataset. The inline
`BROADER* ACYCLIC 1..N` form returned the correct result and is the required
workaround.

This is one physical graph database, not a second ontology. The atlas manifest
and N-Quads remain the authority; the Ladybug file is an indexed serving copy.

## What went in

- Audited atlas: `output/vocabulary-atlas/v5-audited/atlas-manifest.json`
- Atlas generation:
  `sha256:98be18402dae5d2f5bf4e1ef10abc0bfc7da65bd596994b56eda278e828459a3`
- N-Quads: 613,202 asserted statements plus 41,212 analysis statements
- Vocabulary releases: Federal Register 2025, ICPSR, and ELSST R6
- Runtime: Python 3.12.9, Ladybug 0.19.0, PyArrow 23.0.0, and
  PyOxigraph 0.5.9 on Apple Silicon

Ladybug 0.19.0 was the current release at the time of the run. The package is
published as `ladybug`, supplies a native macOS ARM wheel, and requires Python
3.10 through 3.14. See the [Ladybug package page](https://pypi.org/project/ladybug/)
and [installation guide](https://docs.ladybugdb.com/installation/).

## What the projection does

The script verifies the manifest against an explicit digest pin, verifies the
N-Quads digest and graph counts recorded by that manifest, loads the N-Quads
into PyOxigraph, writes deterministic typed Parquet tables, copies those tables
into Ladybug, closes the writable database, and reopens it read-only for the
checks.

The property graph uses 23 node tables and 43 relationship tables. The table
count is deliberate typing inside one database, not 66 independent graphs.
Each table is marked `asserted`, `analysis`, or `derived-index` in the generated
manifest, so consumers do not have to infer authority from its name.
The main shape is:

```text
ManagedRelease -> ConceptScheme
      ^
      |
   Concept -> VocabularyExpression -> LabelKey
      ^                                  ^
      |                                  |
candidate/reviewed mappings       SourceTermObservation -> Document
                                         |
                                  SourceTermResolution

Document <- SourceControlObservation
Document -> Docket
Document -> Document              explicit, qualified source link
```

`LabelKey` is the cross-vocabulary cluster point. It contains only normalized
preferred, alternate, hidden, or source labels. It excludes scheme names,
scope notes, and embedding boilerplate. A key explicitly claims no concept
identity, so three concepts with the label `statistics` cluster together
without becoming `skos:exactMatch`.

Authority uses table types rather than a status field:

- `CandidateAssignment` is separate from `AcceptedAssignment`.
- `ConceptMappingCandidate` is separate from `ReviewedConceptMapping`.
- Federal Register API Topics remain `SourceTermObservation` nodes.
- Lists of Subjects retain an explicit `SourceTermResolution` before any
  candidate assignment.
- The Federal Register release retains `strongSourceNative` priority for
  Federal Register document lookup, while `root_ontology=false` and
  `accepted_output_allowed=false` remain explicit.
- `BROADER`, `NARROWER`, `RELATED`, `REDIRECTS_TO`, and `REDIRECTED_FROM` are
  distinct relationship types. The Federal Register release contributes no
  invented hierarchy.

Generation-wide metadata stays in `projection-manifest.json`; it is not copied
onto every node and edge. Raw source JSON and other metadata that no tested
serving query needs remain available in the canonical RDF instead of bloating
the property graph.

## Checks and observed results

| Check | RDF and Ladybug result |
| --- | --- |
| FSIS + Proposed Rule + 9 CFR 381 | only Federal Register document `2026-03227` |
| API Topic `meat inspection` | Federal Register documents `2026-03227` and `2026-03228` |
| Lists of Subjects | 26 `officialTerm`; 10 `sourceLocalOpenTerm` |
| Explicit cross-post from `2026-03227` | Regulations.gov document `FSIS-2025-0012-0003` |
| Assignments | 0 accepted; 26 candidates; no overlap |
| Mappings | 0 reviewed; 1,151 unresolved candidates; no overlap |
| API Topic authority | 107 observations; 0 resolutions; 0 assignments |
| Federal Register priority | its `statistics` concept ranks first for a Federal Register lookup; all three concepts remain |
| Generic-topic gate | `meat inspection` 2/24 and retained; reporting term 14/24 and suppressed |
| Civil-rights hierarchy | Federal Register has no parent; ICPSR parent is `human rights` |
| Read-only serving | write attempt rejected |
| Adversarial inputs | wrong manifest pin, generation mismatch, observation/concept dual type, and source-local concept target all rejected before output |

Observed warm-query medians over 40 repetitions were 0.370 ms for the explicit
link, 0.905 ms for the API Topic lookup, 1.18 ms for the three-control document
filter, and 2.11 ms for the three-vocabulary `statistics` cluster. Schema
creation and Parquet copy took 2.07 seconds. These are local proof timings, not
a capacity benchmark.

The audited generation contains no accepted assignments and no reviewed
mappings. The spike proves that their tables stay isolated, but it does not
prove positive-result retrieval for either class. Add a sealed positive fixture
and project its decision evidence before using Ladybug for accepted output.
The corpus likewise contains no `recognizedVariant` or `unresolved` Lists
resolution. Those two supported states need positive fixtures before claiming
all four resolution paths have been exercised.

Ladybug uses walk semantics for recursive matches, so recursive queries need an
upper bound and explicit cycle semantics. The current documentation describes
both `is_acyclic(path)` and inline `ACYCLIC` behavior in
[recursive relationship functions](https://docs.ladybugdb.com/cypher/expressions/recursive-rel-functions/)
and [MATCH semantics](https://docs.ladybugdb.com/cypher/query-clauses/match/).
On 0.19.0, this exact probe returned:

```text
BROADER* ACYCLIC 1..3 -> human rights, 1 hop       correct; matches SPARQL
is_acyclic(path)      -> term 24667, 0 hops        incorrect
```

Keep the regression check and use the inline form until a later pinned release
passes both forms.

## Reproduce

The dependencies remain isolated from the application environment:

```bash
uv venv --python 3.12 /tmp/refspec-ladybug-019
uv pip install \
  --python /tmp/refspec-ladybug-019/bin/python \
  -r research/evidence/ladybug-vocabulary-atlas-spike-2026-07-31/requirements.txt

/tmp/refspec-ladybug-019/bin/python \
  research/evidence/ladybug-vocabulary-atlas-spike-2026-07-31/run_spike.py \
  --atlas-manifest output/vocabulary-atlas/v5-audited/atlas-manifest.json \
  --atlas-manifest-sha256 \
    sha256:4d18adb1d52e6ccaa7df36d91048c95679c28b40f98faa27a9aaa2a49bee6bac \
  --output-directory output/vocabulary-atlas/ladybug-spike-v1-reproduction
```

The script refuses to overwrite an existing output. A successful run writes:

- `atlas.lbug`, the serving database proven through a read-only reopen;
- `tables/*.parquet`, the inspectable projection input;
- `projection-manifest.json`, with table counts and digests; and
- `spike-results.json`, with RDF parity, authority, path, and timing evidence.

The checked-in [`results-summary.json`](results-summary.json) records the run
used for this decision. Generated databases and Parquet files stay under the
ignored `output/` directory.

## Recommendation

Proceed to a narrow application adapter if Ladybug traversal is useful enough
to justify a second runtime. This feasibility result does not overturn the
existing DuckDB carrier decision: it does not compare a real consumer query
against DuckDB or prove that the existing path is inadequate. Keep these
adoption gates:

1. The N-Quads and atlas manifest remain authoritative.
2. A build fails on any digest, count, endpoint, or RDF-result mismatch.
3. The application opens a completed generation read-only.
4. Candidate and asserted tables never share a query path by default.
5. Every recursive query uses bounded inline `ACYCLIC` semantics and has an RDF
   parity test.
6. Before making Ladybug the default, repeat the spike on CI and the deployment
   platform and resolve or accept the 0.19.0 path-filter defect.
7. Add positive accepted-assignment and reviewed-mapping fixtures; the current
   atlas has no real rows for those paths.
8. Exercise `recognizedVariant` and `unresolved` Lists fixtures.
9. Compare the actual consuming query with the current DuckDB path before
   adopting a second runtime.

This supports cross-vocabulary exploration without turning the Federal Register
thesaurus, a mutable source topic, or a lexical match into a global ontology
root.

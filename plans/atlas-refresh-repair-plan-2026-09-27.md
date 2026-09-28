# Atlas refresh repair proposal

Status: proposed, not implemented or ratified. Reviewed against commit
`ac72b203` of `lane/atlas-refresh-20260927`, including the label correction
(`9855dff5` here) and the
[independent investigation](../research/atlas-refresh-2026-09-27/README.md).
This document covers every finding from that investigation and the concrete
performance risks found while tracing its repair paths. It does not authorize
publication, change agency decisions, or replace the frozen evidence reports.
Independent subagent reviews covered configuration and coverage, provenance,
and build/validation capacity; their corrections are incorporated below.

**Recommendation: keep the Atlas model; repair the verifier and finish the
bounded construction design.** The data checks support the existing source
representations, with one explicitly retained PDF reading exception. The
failures lie in incomplete independent comparisons, divergent digest meanings,
and retained data structures that exceed the measured operating budget.

The desired result is a completed full distribution whose exact bytes pass
independent validation and source comparison, with a separately verified search
view. A producer test pass, a self-consistent payload, or an available URL does
not establish that result.

## Decision frame and lineage

This is proof infrastructure and build tooling, with a delivery follow-through.
It benefits consumers that need reliable identifiers, multilingual labels,
agency history, and reproducible search inputs.

| Existing authority | What this proposal preserves or changes |
| --- | --- |
| [Binding: authority and distribution](../bindings/atlas/3.1/README.md#what-is-authoritative) | RDF remains authoritative; Parquet remains a separately pinned view. |
| [Binding: source accounting and acceptance](../bindings/atlas/3.1/README.md#source-accounting-and-acceptance) | Preserve exact membership and assertion links. Keep internal conformance separate from publisher fidelity. |
| [REF-024 / REF-048](../docs/decisions.md#ref-024-record-the-cross-product-ownership-boundary-once) | RefSpec owns Atlas; products exchange installed packages and immutable artifacts. No sibling-source imports. |
| [REF-037 and its label amendment](../docs/decisions.md#ref-037-the-publisher-alignment-acquisition-wave-lands-seven-mapping-releases-and-the-first-current-cross-ring-carrier) | Keep one preferred label per language and all existing duplicate-language refusals. |
| [REF-039](../docs/decisions.md#ref-039-two-retained-validation-structures-remain-acceptable-only-at-the-measured-corpus-scale), lines 2747–2782 | Implement its compact accounting and batched mapping checks; retire the measured-scale mitigation. |
| [REF-027](../docs/decisions.md#ref-027-the-deletion-campaign--reuse-rdf-explorer-governance-workflow-fixture-corpus) | Do not resurrect the removed incremental/reuse framework merely to salvage this failed run. |
| [REF-072](../docs/decisions.md#ref-072-an-organizations-succession-is-a-dated-event-never-an-identity) | Succession stays an event; identity, non-emissions and owner-selected dates keep their distinct meanings. |
| [Repository doctrine](../AGENTS.md) | Replace checks only with a frozen old oracle, real data, mutation tests and an explicit divergence list. |

REF-039 anticipated both corpus-wide release retention and rebuilding the full
mapping graph. Its historical threshold used a measured RSS baseline. The new
31.45 GiB physical-footprint observation is a different metric; it does not
prove that the old 24 GiB RSS threshold was crossed. The actual guarded failure
is sufficient reason to retire the mitigation. The precise Python function
active at termination remains unproven.

| Component | Owner and dependency direction |
| --- | --- |
| Construction, compact accounting and pack writing | RefSpec producer tools; consume pinned source models and binding wire primitives. |
| Publisher reconstruction and fidelity verdicts | Independent verifier; consume authenticated captures and emitted artifacts, never producer semantic adapters. |
| Offline conformance | Copied Atlas binding; imports no RefSpec package code. |
| Full and compact Parquet views | RefSpec view modules; consume trusted manifests, preserve identity and scope. |
| Public explorer and upload verification | Deployment project; consume the qualified search view and explicit target configuration. |
| Downstream topic use and search policy | Consumer products; pin the release and apply their own policy. |

## Findings and concrete repairs

### F1 — Keep the corrected preferred-label rule

**Disposition: keep; already fixed.** Retain `9855dff5`, the per-language shape,
label-identity counting before literal deduplication, and the old cardinality
clause as a test oracle. Do not discard a publisher language to satisfy the old
shape. Evidence and changed binding pins are in the
[label investigation](../research/atlas-refresh-2026-09-27/README.md#label-policy-and-source-evidence).

Acceptance: multilingual preferred labels pass; two preferred records in the
same language fail even if their text is identical; mixed-case language tags
retain their separate semantic and canonical-wire checks. Re-run these checks
when integrating the final binding, then issue a new package version.

### F2 — Correct declarations and separate LC parsing from selection

**Disposition: reshape; qualification blocker.** In
`tools/verify_atlas_source_fidelity.py:19044,19086`, replace `publisher-key`
with the existing `source-key-derived` policy. The raw roster IDs already prove
that meaning. Adding another policy alias would preserve unnecessary ambiguity.

Replace the grouped LC endpoint declaration at `:17932` with one declaration
per non-FAST vocabulary generated from the existing vocabulary table. Keep the
one-unit rule at `:20868`. In the reader at `:10737` and `build_context` at
`:20566`, parse the shared authenticated ZIP in its existing two passes once,
index endpoint observations by vocabulary, and select each unit afterward.
Retain the LCSH-subject, admitted-predicate and linked-endpoint filters: detached
labels and LC name-authority links cannot create selected endpoints.

Use a run-local parsed-capture cache keyed by reader and exact input pins. A
selected-view key must also contain the vocabulary selection and every
selection-affecting policy. Do not introduce a persistent cache or a new cache
version system for this repair. Split cache scope from publisher-concept
classification: `SPEC_SCOPED_RECORD_READERS` currently controls both at `:20571`
and `:23721`. Give those two decisions separate named predicates, preserving
existing reader behavior. Merely adding LC to that set is not a safe repair.

Acceptance: AGROVOC and Getty match their separate reads when combined in
either declaration order; partitions have exact expected membership; their
union matches the frozen grouped reader over the real ZIP. Mutations of input
pins, vocabulary selection, source IDs, detached labels and name-authority links
fail appropriately. Instrument the reader to prove that adding selected
vocabularies does not add ZIP parses.

### F3 — Make digest meanings explicit and check each independently

**Disposition: reshape; qualification blocker.** Preserve the existing producer
wire rule and SourceRecord identities: `atlas:sourceDigest` hashes the complete
canonical `nativePayload`. The independent binding enforces this at
`bindings/atlas/3.1/tools/validate.py:6936–6966`. Original publisher-byte digests,
archive-member locators and transformation evidence remain inside the expected
payload and input pins; they are different comparisons.

Restructure `_rdf_provenance_failures` (`tools/verify_atlas_source_fidelity.py:21196`)
into three verifier-owned operations:

1. Check canonical payload bytes and their stored digest.
2. Reconstruct expected publisher fields, upstream digests and locators from
   authenticated inputs; compare the complete required field set.
3. Compare the independently expected representation or transformation with
   emitted facts; pair this verdict with the standalone binding's structural
   evidence checks against the same manifest.

The minimal model addition is
`PublisherView.expected_native_payload_digests`, keyed by the independently
reconstructed resource identity. Populate it in `_api_capture_view` and
`_stock_vocabulary_view` while each expected payload is available; keeping the
whole payload remains optional. Retain `resource_input_digests` for callers
that need original input identity, including `_agency_identity_resource_digest`.
Retire the overloaded `resource_input_digest_values` and the two digest-policy
booleans only after their callers migrate. In `ExpectedMappingEvidence`, rename
the upstream `source_digest` field to `input_digest`; derive the expected outer
SourceRecord digest from its independently reconstructed `native_payload`.
Use counters keyed by locator and expected payload digest where multiplicity
matters, preserving multiple evidence records per assertion.

In `read_atlas_source`, compute observed internal payload-hash checks once for
both compact and full paths and retain mismatch evidence. Compact retention
requires complete expected-digest coverage, not a boolean assertion. Keep the
three meanings explicit: SourceRelease input/release identity, SourceRecord
canonical payload hash without terminal LF, and EvidenceBinding's referenced
SourceRecord **content** digest. They are not interchangeable hashes.

The digest map alone does not prove SourceRecord minting or add all evidence
joins to `AtlasView`. Keep structural record ownership and binding-digest checks
with the independent binding validator and require its paired receipt. Preserve
existing reader identity comparisons and the independently reconstructed
UMTHES identity fixture. A general new SourceRecord minting check would require
explicit expected preimages and observed source-release joins; do not claim it
from this smaller repair. The unchanged producer preimage includes the original
upstream digest, payload digest, locator and source release (`generator:3533–3538`),
not two copies of the stored outer digest.

Remove digest-meaning switches after their readers migrate. Do not flip every
`source_digest_is_native_payload_digest` flag or treat a self-hash as publisher
evidence. A reader must provide an exact expected payload or an explicit
exhaustive field comparison; an unevaluated field remains a failure. Migrate
the reproduced cases first—UMTHES, Federal Register API topics, GCMD, GovInfo,
GAO and EuroVoc/MeSH—then enumerate every remaining reader declaration. Retain
BILLSTATUS as the counterexample proving a false flag alone was not a defect.

Clarify `bindings/atlas/3.1/README.md:388–392`: it currently conflates the external
digest with the payload digest and describes an English-only native view too
broadly. State the actual language-scope rule. Prefer this documentation repair
over changing ontology assets just to add comments: ontology changes move the
binding digest. This repair changes verifier verdicts, not publisher identities.
Update the same stale explanation in the verifier introduction and
`wiki/atlas_source_fidelity_audit.md:245` rather than leaving a second meaning
in user-facing documentation.

Acceptance: all independently reconstructed real payloads pass; changing any
upstream digest, locator, native field or payload hash fails. Existing identity
oracles and unchanged-output comparisons continue to protect identity stability.
Record the exact intentional old/new verdict differences. No blanket exception
for a reader family is permitted.

### F4 — Close transformed-relation tamper gaps and duplicate work

**Disposition: reshape; qualification blocker.** Populate UMTHES
`expected_relation_payloads` from raw relations and independently reconstructed
hierarchy paths, including the complete `editorialTransformation`, original
predicate, reason, target predicate, upstream digest and relation locator. The
retained independent reconstruction already matches the actual transformed
records. Replace the fallback branch that checks an inner hash and then exits
without comparing those fields. Reuse the verifier's existing exact-payload
comparison mechanism; do not import the producer's transformation function.

Evaluate provenance once per immutable source pair and pass the resulting
structured comparison to both `rdf-provenance-fidelity` and claim-scope. They
currently invoke the same work independently at `:21656` and `:25662`. Keep the
result local to the audit invocation so an edited payload cannot receive a stale
process-global memoized answer.

Do not copy ICPSR's full ancestor-set cache (`:13455–13471`) into another reader.
For requested related pairs, group queries by start node, traverse once per
queried start with one temporary visited set, record only requested answers,
then release that set. Share this small graph-query helper within the verifier
after old/new verdict equivalence. Preserve exact directed reachability and
cycle handling; no depth cutoff, approximate membership or new editorial rule.

Acceptance: change `responseDigest` or the transformation reason, recompute
every inner/outer hash and locator, and still get a provenance failure. Also
mutate object, direction, hierarchy edge, extra field and missing field. Compare
whole failure sets, not just exit codes against an already-red baseline.
Require exact transformed-record populations and preserve evidence multiplicity:
missing, unexpected and duplicate evidence records fail. Remove the fallback
entirely so a changed inner digest cannot select a weaker comparison. Include
one bounded artifact-level mutation with internally consistent dependent IDs,
digests and valid transport pins; fidelity, rather than broken packaging, must
cause its rejection.

### F5 — Install complete, executable coverage for the missing units

**Disposition: reshape; qualification blocker.** Add real independent adapters
for `ferc-docket-prefixes`, `ferc-document-class-types`,
`unified-agenda-legal-authority-citation-types` and
`agency-registry-2026-09-26`. Use the retained independent scripts as frozen test
oracles and evidence, not imports from a dated research directory.

The vocabulary adapters should use independent positioned PDF extraction
(Poppler, with stock XML parsing of its word-coordinate output). Reuse the
verifier's authentication and field-comparison
primitives. For PDFs, sort words into row bands once per page and sweep those
bands; do not repeatedly scan every page word for each row. Retain exact input
pins, page/row locations, continuation handling, native fields and identity
preimages. The selected Unified Agenda glossary entries remain a capture
subset, not a claim to enumerate every legal citation type. Independently delimit
the glossary definitions of `U.S.C.`, `Pub. L.` and `E.O.`; do not import the
producer's transcribed text. Preserve FERC class row ordinals: equal display
labels need not identify the same row.

For FERC docket prefixes, compare the normalized emitted `atlas:recordStatus`
as well as the native status field. The generic exclusions at verifier
`:222–230` omit that predicate, while the producer emits publisher status at
`src/refspec/atlas/v3_registry_codes.py:759–764`. Add a narrow source-declared
comparison; do not remove a valid generic exclusion for unrelated derived
lifecycle states. A mutation changing only RDF status must fail.

Add a cheap fast-tier test that validates all declarations and compares their
unique owned keys with `_declared_construction_unit_keys` at generator `:2304`.
It may import producer topology metadata, never its semantic readers. Require
an implemented registered comparison as well as a declaration. Keep the runtime
fail-closed artifact coverage check at verifier `:20991`; use its existing
keyed inventory instead of repeatedly scanning all units for each declaration.
Registration proves that a check exists, not that it evaluates the source.
The bounded source/artifact fixtures and field mutations are the semantic
coverage proof; a no-op callable must not satisfy them.

Acceptance: exact populations and native fields on real data; dropped/extra
rows, wrong status, identity, continuation, and source-pin mutations all fail.
Adding an unowned producer key, duplicate ownership, invalid policy, grouped
declaration or placeholder reader fails fast without a large artifact build.

### F6 — Resolve the FERC PDF discrepancy without changing identity

**Disposition: keep the rendered reading; narrow and document its evidence.**
The visible `Hinshaw Pipe` ending was independently inspected again and is
already pinned by `tests/test_ferc_pdf_attestation.py:108–120`. Preserve the
emitted text and resulting resource identity. Retain the conflicting Poppler
`lines` observation explicitly in the fidelity receipt.

Implement a source-reading exception keyed by exact PDF digest, page, row,
field and reviewed reading. It must accept only this observed difference,
not suppress all differences on that row. A changed PDF digest, another word,
another field or another location requires review and fails the frozen rule.
Remove speculative wording such as “almost certainly Pipelines” from the old
attestation/test commentary; the evidence establishes the visible reading,
not the publisher's intended missing word. This is a reading policy backed by
pixels, not a confirmed producer corruption.

### F7 — Verify agency events, decisions and non-emissions in production

**Disposition: reshape; qualification blocker.** Keep the agency unit a mapping
unit. Reuse independent roster readers, `ExpectedMappingEvidence` and mapping
evidence checks. Add one small verifier-owned agency comparison module and one
named check in `_CHECKS` (`tools/verify_atlas_source_fidelity.py:24996`). Its
inputs are authenticated candidate/decision JSON, independently read rosters,
actual RDF facts and the dedicated agency-view manifest. It must not import
`agency_registry_outcomes`, producer digest helpers or the agency view builder.

Index candidate IDs and event members once. Independently recompute item,
event/result and aggregate digests, then compare each decision's
`content_digest`, using
[the documented rules](agency-registry-design.md), sections containing lines
175–195. Preserve `effect_note`'s exclusion from individual decisions and its
inclusion in the aggregate. Compare exact bridges, endpoint names/parents,
reasons, original/result sets, dates and date bases, result-specific functions,
public citations, reviewers, evidence links, and every non-emission. Prove that
rejected identity pairs emit no assertion. Missing, stale or unknown decisions
fail. Succession cannot be replaced by identity to simplify the comparison.

Generic Parquet intentionally omits organization-change events (REF-072,
`docs/decisions.md:6005–6010`). Compare non-emission and event tables against the
dedicated agency view, authenticated by its own trusted manifest digest. If
that required evidence is absent, report unevaluated, not passed. Keep RDF,
generic view and dedicated view pins distinct.

Add a small audit-evidence manifest for the acquired primary documents and
reviewed claim locations. Externally pin that manifest and its review receipt,
binding reviewed claims to source hashes and the candidate aggregate; a mutable
self-declared manifest is insufficient. Authenticate retained originals offline;
acquisition is a separate step. Do not append these bytes to frozen producer construction
pins: verifier `check_publisher_input_pins` at `:21061–21120` requires exact
construction-input equality. The automated claim is faithful representation of
the recorded decisions and source review, not automated legal adjudication.
Preserve the CMS order-date policy, Treasury roster-date policy and postal
identity/succession judgment. The uncited FARRA section 1601 plan remains outside
the present evidence scope unless a stronger historical claim requires it.

Acceptance: retain all existing agency mutations and add normalized-output
mutations for dates, function allocations, originals/results, parents, URLs,
reviewers, rejected bridges and missing non-emissions. Changed reviewed source
bytes invalidate their review; they cannot silently refresh the same approval.

### F8 — Remove corpus-wide expanded mapping graphs and retained releases

**Disposition: reshape; build blocker.** Implement REF-039 in
`_stream_construct_graphs`, `_mapping_accounting_expectations` and
`_validate_compiled_source_accounting`
(`tools/generate_atlas_v3_full.py:7320,4100,4998`). Reuse the already bounded
exact comparison at `_validate_streamed_evidence_batch:6684` and local source
accounting reconciliation at `:7015`. The current deep prebuild already calls
the streamed constructor (`:10315`); the older whole compiled-output validator
is used by bounded tests/oracles. Do not add a second deep-comparison pipeline.

Build compact expected memberships from the incoming source models before
emission. Validate each completed accounting row while its source release is
still available; retain only exact IDs, global uniqueness indexes and totals
needed for final reconciliation. Remove `all_source_releases` and
`all_mapping_releases` as lifetime owners. Give derivation the compact release
facts it actually needs and the existing spools, not whole normalized payloads.
Replace its materialized `list(_spooled_release_lines(...))` at `:7279` with a
fresh iterator for each existing collector pass. This trades a fixed number of
sequential rereads for the retained line list; required fact maps and derived
rows still occupy memory.

Reuse `_stream_batches` and the expected graph already constructed for each
bounded exact-evidence check. Fold its exact record-to-assertion/event identities,
with all evidence bindings, into compact accounting expectations before releasing
the graph. Keep the copied whole-graph accounting implementation as a bounded
test-only oracle. Expected membership must come from inputs, never from the
emitted spool being tested. Policies
shared across batches need exact deduplication; cross-batch duplicate records
and wrong ownership must still fail.

This removes the extra full mapping RDF graph and releases payloads as work
finishes. It does **not** make the whole build constant-memory: loading,
prebuild, the accounting JSON, resource-owner indexes and compact identity sets
still scale with the corpus. The borrowed-input deep API also retains the
caller's normalized release models (`:10283` and its callers); preserve that
API and report its `O(normalized corpus + batch)` bound. Removing aliases in
the owning build path does not free another caller's references. Do not add
DuckDB, SQLite or a new graph engine to this repair unless measurements show
those compact structures exceed the
budget after the expanded graph is removed.

Acceptance: old/new accounting bytes, exact fact sets, verdicts and deterministic
output agree on bounded real FAST/LC mappings, multi-evidence mappings and
agency events. Mutate missing/extra assertions, duplicated evidence, wrong
source release, cross-batch duplicates, events and ledger links. Instrument the
largest simultaneously live mapping graph and prove it is batch-bounded.
Include shared records across batches, changed locators/payloads/policies,
ledger totals and the zero-mapping/event boundary. Compare all verdicts with
the old oracle, including valid multiple-evidence cases.

### F9 — Stop repeated whole-heap collection and bound sorting bytes

**Disposition: reshape; measured overhead plus static capacity risk.** After
F8 removes the retaining aliases, remove the per-release full `gc.collect()`
calls at generator `:7375,7396`. Close temporary graphs deterministically and
let ordinary reference counting and automatic collection run. Measure before
considering a deliberate collection at a major phase boundary; do not freeze
the growing builder heap. Replace `list.pop(0)` with a deque or reverse-once/pop
when the remaining queue consumer permits it, preserving processing order.

In `_write_sorted_lines` (`:5855–5893`), add a serialized UTF-8 byte cap alongside
the existing line-count cap. Flush before exceeding either bound and use
`writelines` instead of joining the whole chunk into a second string. Keep the
existing bounded merge fan-in of 64. A single oversized line must fail the
binding's line limit. A byte cap is not a Python-footprint guarantee; measure
list, string and encoder overhead too.

Acceptance: identical sorted bytes and duplicate handling across different
chunk bounds, long multibyte lines, exact boundaries, empty input and many
merge runs. Re-run real writer equivalence. Confirm that tiny releases no
longer trigger full-heap scans and that memory stays within the same budget.

### F10 — Enforce pack limits from actual bytes

**Disposition: reshape; final qualification blocker.** Preserve the binding's
limits at `bindings/atlas/3.1/tools/validate.py:336–338`: 4 GiB uncompressed and
1 GiB transport per pack, 32 GiB uncompressed per distribution. The record-count
threshold and fixed hash-prefix buckets are planning hints, not proof of those
limits.

Keep the current 16-bucket strategy for the next measured candidate. Add early
spool-content size checks and count compressed bytes while writing, stopping
at the transport limit. Check actual canonical/compressed receipts and
aggregate content before promotion. No completed current artifact has proved
that more buckets are needed. On overflow, fail with the exact unit, bucket,
byte length and limit; never drop facts or split a subject to pass.

If those actual measurements require finer partitioning, implement one
deterministic additional-prefix split for oversized source/mapping buckets,
regenerate receipts and update exact dependencies/ownership. Keep every
subject's outgoing facts together per graph role. Refuse both an indivisible
oversized subject and exhaustion of the manifest's maximum eight hex-prefix
characters, even if no individual subject is oversized. Account for repeated
sorting, compression and dependency recomputation, not just the split scan.
Keep atomic final promotion. This adaptive writer is conditional work, not a
prerequisite to discovering the actual pack sizes.

Use one existing pack writer and receipt type for both construction paths.
Any expanded prefix-depth support must be accepted by the manifest, partition
validator and dependency resolver together; do not emit an undocumented wire
variant. Acceptance uses deliberately skewed buckets and long payloads, not
only evenly distributed small records, and includes transport-only overflow,
duplicate quads, dependency closure and cross-pack ownership mutations.

### F11 — Make resource admission and phase measurements honest

**Disposition: reshape; operational blocker.** Run full build, deep producer
tests, standalone validation and the fidelity audit serially in an exclusive
resource window. Preserve worker parallelism only for measured bounded tests.
The earlier eight-GiB fast-tier stop and the full-build interruption are capacity
outcomes; increasing a timeout or process count is not a correctness repair.

Extend the existing run harness, not each algorithm, to record phase start/end,
wall and CPU time, process-tree RSS, physical footprint where available, host
pressure, swap deltas and temporary-disk high-water marks. On macOS use the
native footprint measurement; on a Linux release runner use a job-level memory
limit including descendants. Define clearly whether swap is allowed. Preserve
the current 18 GiB build budget as an initial proposed **physical-footprint**
qualification target; this is a new acceptance target, not an achieved result.

Add explicit status boundaries around derivation, accounting construction,
accounting validation, sorting, compression and view checks. The current
`derive-registered-relations` label spans several of those operations. Stop
only the owned process tree when the budget is exceeded and retain a failed
receipt. Do not reuse a stale PID or stop unrelated jobs.

Do not carry the workflow's historical “32 GB is enough” and 30-minute build
claims into this release (`.github/workflows/release.yml:57–79,119`). Set actual
runner capacity and timeout budgets from the isolated post-repair measurement.
Runner purchase/selection remains an operational choice; it is not required to
implement the code repairs.

### F12 — Close full-artifact validation and capacity gaps separately

**Disposition: verify after the build repairs.** The current full artifact has
no completed manifest. Its partial spools are evidence, not resumable output:
keep them until a separate cleanup decision. Do not build a recovery subsystem
for this one interruption. If repeated failures later justify checkpoints,
require authenticated input/code/binding pins, completed-stage counters and
cold-versus-recovered byte equivalence before reuse; file existence is inadequate.

After a completed build, run the copied standalone binding cold against the
actual full distribution with `REFSPEC_ATLAS_VALIDATION_MODE=audit`, preserving
the release workflow's existing mode. Propose a first local ceiling of 30 GiB
for both process-tree RSS and physical footprint; a capacity interruption is
incomplete qualification, not semantic rejection. It retains the full parsed
dataset in `TwoIndexStore` and is a separate memory consumer (`validate.py:10325–10480` and
`tools/parse_substrate.py`). A smaller historical pass cannot qualify its present
capacity. Profile parsing, semantic checks and ownership separately. If the
available host cannot carry the measured working set with headroom, use an
adequately provisioned exclusive runner; do not silently substitute smoke mode,
trust the producer receipt, raise pack limits or remove semantic checks.

The generic fidelity verifier also retains source bytes and publisher/Atlas
views across its complete context (`build_context:20514–20724`). First measure
it independently. If it exceeds its declared budget, execute one shared-input
family at a time with an authenticated global manifest inventory, retain compact
results, and release the family's large views. Preserve global coverage,
uniqueness and language checks; run the whole-pack language scan once. A loop
of separate `--only` subprocesses that repeats the global scan is not the fix.
Freeze existing aggregate receipts and verdicts as the execution-model oracle.

Keep the existing compact-view writer and its mandatory input pin. As a small
performance improvement, read only the columns required by `_transform`, plus
its identity-check columns (`src/refspec/atlas/parquet_search_view.py:277–343`).
For SourceRecord this avoids decoding discarded native payloads. Input-file
authentication still reads every stored byte; the optimization reduces column
decoding and Python objects, not that integrity check. Preserve table order,
row groups, manifests and byte-for-byte output where the writer version allows.

### F13 — Make the release workflow prove what its name claims

**Disposition: reshape; delivery blocker.** Keep fast CI bounded. Keep
`test-full-atlas` explicitly named/documented as producer prebuild tests. Add a
single release-qualification target reused by the local runbook and
`.github/workflows/release.yml`; avoid separate command lists that drift.

The target requires a completed distribution and runs, serially: actual pack
bounds and pins; standalone full validation in release `audit` mode; unscoped
source fidelity with complete executable coverage and required agency evidence; full-view
verification; compact-view construction and verification. Record exact
distribution/view digests, source revision, tool versions, scope, result and
resource measurements. Stop before qualification on any failure or unevaluated
required comparison. Upload the fidelity receipt with the other receipts; the
current workflow has full validation but omits this publisher comparison.
Build and verify the dedicated agency view explicitly before the agency check,
or require its separately supplied trusted digest. The full generator does not
create this view, so qualification must not assume it appears automatically.

Reuse the existing commands and receipt formats. A thin run record may link
them, but do not change `atlas-acceptance.json` to imply source fidelity or
reintroduce an unused permission framework. Signing, where later enabled, must
be reachable only after the required checks; a signature alone remains an
identity/integrity claim with the existing documented scope.

### F14 — Pin package adoption and verify public bytes

**Disposition: reshape delivery checks; preserve existing release scope.**
Package changed source under the next unused version, never new bytes called
dev21. Retain the wheel hash and source commit, update explicit consumer pins,
and run consumer import/query checks against the same qualified artifact. A
package release and an Atlas data release are different outputs.

For deployment, require the trusted search-view digest in
`deploy/cloudflare-explorer/build/precompute.py:332–344`; self-hashing the local
manifest is useful for development but cannot authenticate release input.
Create one digest-bearing inventory of precomputed outputs linked to that
trusted input. Keep cheap presence/length/range probes, but add a publication
check that streams each served object and compares its actual bytes with that
inventory. Freeze and pin that inventory before upload, and bind the served
inventory/object set to the reported Worker version. Use an immutable candidate
prefix or equivalent verify-before-promotion step when existing keys would
otherwise expose a mixed release. Reuse one check implementation from upload
and verification paths. Same-size corruption, truncated responses and an
inventory from a different artifact must fail.
The current scripts at `upload-verified.sh:48–61` and `verify-all.sh:65–90`
cannot detect same-size altered bytes. Distinguish transport errors, missing
objects and digest mismatches.

The publication receipt must identify the account, Worker version, public URL,
source commit and artifact digests, followed by representative search, detail,
agency and range-request checks. Resolve the actual target account/domain,
runner/store arrangement and signing-key custody before publication. The
observed missing Worker in one account does not prove global absence. No
deployment or new agency policy is implied by implementing these checks.

## Performance and Big O audit

Notation: `R` is releases; `N` source records/resources; `M` mapping assertions;
`E` evidence bindings; `T` RDF statements; `Ubytes` retained RDF-term bytes; `B` bytes
processed; `I` compact identity entries; `b` records in one construction batch;
`Bg` all bytes/objects associated with that batch's triples, evidence and
payloads; `C` a serialized sort-chunk byte budget; `f` merge fan-in; `p` output packs.
For graph queries, `Vh`, `Eh` and `s` mean hierarchy vertices, edges and queried
start nodes. Dictionary/set bounds below are expected-case. Sorting costs count
comparisons; comparing or hashing strings also costs their byte length.

| Path | Present cost or risk | Proposed cost and remaining limit |
| --- | --- | --- |
| Mapping accounting | Extra resident graph `O(Tm + term/payload bytes)` plus release models and `O(I)` expected IDs; `Tm` is mapping/evidence RDF. | Temporary graph `O(Bg)`, compact `O(I)` state; expected-fact work remains `O(Tm + bytes)` plus canonical sorting. With fixed schema `Tm = Θ(M + E)`: this removes costly representation/lifetime, not all linear growth. A record-count batch alone does not bound variable payload bytes. |
| Whole build | Preloaded queues, ledger and ownership indexes remain corpus-sized. | Still at least `O(N + M + E)` identifiers/model state at some phases. No end-to-end `O(b)` claim. Measure the maximum of phase working sets. |
| Forced full GC | `O(Σ H_i)` heap visits across releases, up to `O(R·H)`; if retained heap grows evenly, this can behave quadratically in releases. | Remove the forced repeated traversal after fixing lifetimes; normal GC still has a measured cost. No unproven automatic-GC complexity promise. |
| Queue draining | `list.pop(0)` moves remaining entries: `O(R²)` queue operations. | Deque/reverse-pop: `O(R)`. Small next to RDF work; do not present it as the memory fix. |
| External sort | Count-bounded chunks can hold huge strings and a second joined copy. | `O(C + f·Lmax)` serialized working data plus Python overhead and `O(r)` run-path metadata; existing bounded merge. For `q` lines in `r` runs: `O(q log q)` comparison-scale work, byte I/O `O(B·(1 + log_f r))`; actual string comparisons depend on prefixes. |
| Pack sizing | Record counts do not bound encoded or compressed bytes. | Immediate guards inspect `O(p)` receipts and reuse byte counters from existing `O(B)` writes. If adaptive splitting is needed: `O(B·d)` split scans plus repeated sort/compression and dependency recomputation for `d ≤ 8` prefix depths. Skew, an oversized subject or depth exhaustion fails explicitly. |
| LC endpoints | Naïve split rescans `k` vocabularies: `O(kB)` parse work. | Shared parse/partition `O(B + rows)`, plus required deterministic sorting; retain one parsed family, not `k` full copies. |
| Payload proof | Canonical hashing, publisher comparison and unconditional record/evidence sorting; provenance invoked twice. | One comparison per pair. Keep current deterministic sorts unless separately proven removable: `O(B + Σ k_i log k_i + N log N + E log E)` work, plus sorting reported failures. Reuse the comparison result; expected fields still take space. |
| Hierarchy evidence | Full ancestor cache can retain `O(Vh²)` reachability entries. | Including graph/query construction: `O(Vh + Eh + Q + s·(Vh + Eh))` worst-case time, `O(Vh + Eh + Q)` memory for requested pairs `Q`; release each visited set. Exact reachability, not an approximate shortcut. |
| Agency checks | Scratch scripts repeatedly select event members and rehash files. | Index once: expected `O(candidates + events + RDF facts + B)`, plus canonical ordering; state proportional to the compared agency slice. |
| PDF row extraction | Scanning all words for every row: `O(rows·words)`. | Sort once per page and sweep row bands: `O(words log words + rows)`, page-bounded working state plus retained expected rows. |
| Coverage | Repeated unit scans can be `O(declarations·units)`. | Keyed metadata inventory: `O(declarations + units)` time/space. |
| Standalone validator | Dataset indexes retain `O(T + Ubytes)`; global graph checks have their own costs. | Keep and measure. Its hierarchy check (`validate.py:6419`) traverses the DAG for each batch of up to 2,048 queried endpoints: traversal term `O(ceil(q/2048)·(Vh+Eh)·wb)`, where `wb` is words per bounded bitset, in addition to graph construction, query tests and sorting. This is distinct from F4's source-verifier traversal. The complete validator has no established linear-time bound; no backend rewrite is justified solely by the builder failure. |
| Full fidelity audit | Current context retains all authenticated bytes and views. | Family execution, if required: peak largest family plus global compact results/indexes; total input work stays linear in bytes except declared graph/sort costs. Cross-family checks remain global. |
| Compact view | Batched full-column decoding then field removal. | Keep bounded batches; decode selected columns and required identity fields. Still `O(all stored bytes)` authentication; transformation work tracks selected column bytes. |
| Public verification | Length probes cost little but prove little about content. | One publication-time `O(served bytes)` streaming digest pass, bounded buffers; no added per-query hashing. |

Use existing primitives first: `collections.deque`, `hashlib`, `heapq.merge`,
the current bounded RDF batches/sorter, PyArrow batches and the existing
standalone binding. [PyArrow documents both batching and column selection](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html#pyarrow.parquet.ParquetFile.iter_batches).
The default Python [`gc.collect()` scans all generations](https://docs.python.org/3.12/library/gc.html#gc.collect),
which matches the measured repeated-collection concern. DuckDB is already a
dependency and can support a future spill-backed relational comparison, but
its [spill support has operator limitations](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads#larger-than-memory-workloads-out-of-core-processing);
adding it does not itself prove a memory bound. It is not needed for the first
compact-accounting repair.

## DRY and KISS audit

DRY means “do not repeat the same knowledge”; KISS means choosing the simplest
design that still meets the required behavior.

| Area | Verdict |
| --- | --- |
| Producer and verifier publisher semantics | **Keep deliberate independence.** Shared producer extraction would make the audit confirm its own mistake. Share wire parsing/hashing mechanics only where an independent parser/oracle still protects their meaning. |
| Digest switches and duplicated provenance calls | **Remove duplication.** One format rule, independent expected fields, one per-pair comparison result; no source-by-source boolean patch list. |
| LC source parsing | **Share parsed evidence, separate selection.** A cache must model the facts its result depends on; unrelated concept-classification policy must not hitchhike on cache flags. |
| Builder comparison and output writers | **Reuse existing batches, facts, sort and receipt mechanics.** Keep independent comparands from incoming models; do not read expected truth from emitted output. |
| Missing source adapters | **Small source-family adapters.** Share page geometry, authentication and generic comparison mechanics inside the verifier. Keep source-specific semantics explicit. |
| Agency comparisons | **One narrow module with typed expectations.** Reuse roster/mapping checks; do not add a new ontology ring, event framework or automatic legal-reasoning service. |
| Large tool modules | **Extract touched responsibilities only.** The producer, verifier and validator are large, but splitting by line count is not a repair. Move cohesive code only with a named caller and tests; do not turn this into a package-wide reorganization. |
| Performance infrastructure | **One run harness and phase reporting.** Do not embed platform process control in semantic checks or build a distributed scheduler. |
| Partial-output recovery | **Defer a new feature.** Preserve evidence and run a fresh qualified build after fixes. The removed reuse subsystem is not a sunk-cost reason to recreate it. |
| Release/deploy checks | **One reusable qualification sequence and one output inventory.** Keep signing, source qualification and product authorization distinct; do not invent another policy database. |

## Acceptance, delivery order and counterfactuals

Implement each repair with its tests as one reviewable change. These groups are
ordered by dependency, not partial exemptions from a finding:

1. Declaration/cache corrections and fast global configuration checks.
2. Universal payload format checks, independent provenance/transformation
   expectations, agency/vocabulary adapters and the exact PDF reading policy.
   Add the topology/registration coverage tripwire with the adapters: write the
   failing regression first, but deliver them together without a temporary
   allowlist or a knowingly failing intermediate merge.
3. Compact accounting that reuses bounded exact mapping checks, then measured
   GC and sort-byte repairs; preserve the deep API's borrowed-input semantics.
4. Actual-byte pack guards, resource-aware run harness and phase metrics;
   finer partitioning only if measured pack overflow requires it.
5. One isolated full build; cold standalone validation; complete source audit;
   verified full/compact views; exact comparison with the retained August
   artifact. Attribute every changed unit, count and identity to changed inputs,
   policy or binding. An input declaration alone cannot stand in for this diff.
6. New package version and consumer qualification; then publication checks for
   the selected target, when publication is authorized.

Before the next full run, use 1×/2×/4× fixed-shape synthetic inputs along both
record-count and release-count axes, plus bounded real subsets, to record phase
time, physical footprint, temporary disk, parse counts, live graph size and
comparison counts. Separate scaling from absolute
hardware budgets. Measure cold runs under the same interpreter/dependencies on
a quiet host; retain exact inputs and logs. An apparent speedup achieved by
omitting evidence, language, rejected rows or negative fixtures fails acceptance.
Do not extrapolate the 29-million-quad validator result into a claimed pass at
the present full size.

For replacements, copy the old implementation into test-only oracles before
changing it. Compare complete facts, canonical bytes or complete verdict sets,
as appropriate. Freeze intended divergences: multilingual preferred-label
acceptance; corrected digest meanings; newly detected altered provenance;
newly enforced missing-unit coverage; explicitly reviewed PDF reading. Unlisted
differences fail. Pure performance changes permit no semantic divergence.

The proposal is falsified if removing the full mapping graph leaves the same
dominant peak elsewhere, if exact oracle agreement cannot be achieved, or if
the full validator cannot complete on the declared release capacity. Respond to
the measured phase: repair that retained structure, provision the actual
validator working set, or reopen a backend decision with a bounded parity
experiment. Do not weaken checks or describe a smoke test as qualification.

Rejected alternatives: raising every cap; assuming hash buckets are balanced;
adding cache flags without separating semantics; flipping all digest flags;
sharing producer transformations with the verifier; replacing the RDF engine
before measuring its own failure; inferring missing PDF text; treating agency
owner choices as automatically re-adjudicable; trusting same-size uploaded
objects; and restoring an unneeded incremental-build framework.

**Audit verdict: RECONSIDER the current release path, retain the data model.**
The user value is supported: these repairs make the artifact's claimed evidence
and operating bounds checkable. The current implementation diverges from that
intent at the verifier and memory-lifetime boundaries. The proposed changes
pay down duplicated interpretation and retained representations while preserving
source independence. Confidence is high for the correctness fixes; full-scale
time and capacity remain acceptance measurements, not promised results.

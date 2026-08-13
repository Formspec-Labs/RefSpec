# Barebones reset — build, prove once, sign, serve

## CONTINUATION — read this first (2026-08-12, session handoff)

Written for a blind agent resuming with zero session context. The history
below this section is the evidence record; THIS section is the state.

**JENA FINAL DELTA (agent's last report, 2026-08-12, supersedes the
"strong lead" caveat):** the full-scale slowness is a constraint
COMBINATION inside a single node shape, not any constraint alone — every
probe individually fast at 29.3M quads (literalForm-only 42.3s; +closed
42.5s; sh:class→590k-instance 44.0s) but the verbatim SkosXlLabelShape
standalone >1,829s aborted, and HEAD's own batched-plan shapes as a
shapes file ALSO slow (>1,844s) — so the cheap decomposition fix does
not exist. Minimal repro preserved:
`.claude/worktrees/agent-a7937c98dc15549c2/jena-spike/shapes/only-label-standalone.ttl`
(~40 lines; `bin/reproduce` end-to-end; staging data kept, full-scale
intermediates regenerate in ~12s). The last bisection (sh:closed +
sh:class together, the untested pair) started but did not finish —
lead, not measurement. Three bounded follow-ups, <1h each, worth ONE
session only because move 2 depends on the answer: (a) finish that
bisection and file it upstream as the minimal repro, (b) try Jena 5.x
on the already-present JDK 17 (regression check), (c) try TopQuadrant
SHACL (the never-tested half of kill-5's comparison cell). Dev-loop
integration is actively negative without a long-lived JVM driver
(0.24-0.41s startup × 115 fixtures vs pySHACL's 0.07s/case). Verdict
unchanged: no-go today, parity asset banked, ~100× SHACL-SPARQL stands
as move 2's pre-commit blocker.

**State of the tree (REWRITTEN 2026-08-13 — the block that used to sit here
described a dirty mid-wave tree from 08-12 and was badly stale).** HEAD is on
branch `atlas-v3-binding-and-relation-research`; nothing is pushed and there is
no upstream. **The working tree is CLEAN and every gate is green**: `make lint`,
`make check-generated`, `make test-atlas-v3` (132 cases, 119 invalid), and
`pytest -q -n auto` at 2,604 passed / 87 skipped. `make contract-dev` reproduces
its pinned digests and the FR release verifies against the Makefile pins. There
is no half-finished edit to recover — start from whatever the sections below
say is next, not from an archaeology exercise.

**Artifact of record: `output/atlas-3.1-full-2026-08-13b/`**, built on the
language-scope producer, acceptance-passed at 18.3 min / 13.83 GiB peak over
29,286,753 quads. Its predecessor `output/atlas-3.1-full-2026-08-13/` and that
one's seal remain valid and untouched — **verified, not assumed**: after the
13b build, `verify-distribution-seal` against the 08-13 tree and the shared
`output/parquet-view` still passes under the production signer
atlas-release@refspec (4 members, 126 packs, 8 Parquet tables, 941,467,710
bytes), which is what building 13b into its own `/distribution` and
`/parquet-view` bought. Note for whoever builds next: a bare `--output` would
have written the new view over `output/parquet-view` and broken that seal, as
already happened once to 08-12c; 13b is unsealed only because the signer
key is offline (see the seal block below — it is now one make target).

**Sole in-flight work at the time of writing:** `research/coverage-patternrow`,
implementing the `pattern-row-v2` reader that the coverage-dry design says
covers 42 of the 61 remaining fidelity units. Everything else this session
either merged or reached a recorded verdict.

**What is DONE and committed (27 commits, cd769d44..b9545930).** The
entire reset through the 3.1 atomic wire replacement: seal (format 2,
view-covered, proven end-to-end on the FR artifact with an ephemeral
key), red-path fail-fast + 92s smoke tier, xone lift + gc.freeze +
roles-fold (staging −42%), governance archive, RDF explorer deletion,
fixture corpus un-commit, reuse-subsystem deletion, rulespec-as-package
(vendored wheel), warrant model fixed (option a1), wire hygiene (RFC-3987
IRIs, simple-form literals, byte-grammar canonicality — pyoxigraph
accepts published bytes with zero refusals). Ledger: REF-026/027/028 +
supersessions of REF-015/018/019/020/021. Artifact of record:
`output/atlas-3.1-full-2026-08-12b` (built clean post-hygiene, 13 gates
passed, smoked). FR pins in the Makefile verify today.

**What is NEXT (REWRITTEN 2026-08-13 — the numbered wave list that used to
sit here was entirely DONE and read as though it were pending; the historical
detail survives in the sections below).** In order:

1. **Merge `research/coverage-patternrow`** when it reports — the
   `pattern-row-v2` reader for 42 of the 61 open fidelity units. Gate with
   `make lint` + `pytest tests/test_verify_atlas_source_fidelity.py -q` (238
   pass today; additions must raise it, never lower it), and verify structurally
   with `ast` rather than by eye if any merge conflicts (that trap has bitten
   twice in this file).
2. **The remaining five reader kinds** from the coverage-dry design:
   `xml-record-selector-v1` (4 units), `csv-record-selector-v2` (3),
   `ooxml-relational-v1` (5), `nrc-adams-multi-artifact-v1` (2),
   `json-record-selector-v2` (1). Five of the six generalise a reader that
   already exists; none is a research question any more.
3. **Seal 13b** — owner's step, one command, see the seal block above.
4. **Nothing else is open in this repository.** The performance program, the
   SHACL-engine question, the language-scope wave, and the fidelity auditor's
   structural gaps all have recorded verdicts. Do not reopen the engine question
   without one of the four triggers listed below; do not re-derive the memory or
   time floors, which are measured.


**CONTRACT-VELOCITY WAVE LANDED (521ed20c) + REF-029 ratified:** the
repin tax is deleted (derived-and-recorded binding digests), contract
identity (contractDigest, rules only, checked) split from proof identity
(corpusDigest in the receipt, recorded) — test growth no longer
invalidates artifacts; `make contract-dev` = 39.8s inner loop;
determinism PASS on derived pins. **NEW ARTIFACT OF RECORD:
`output/atlas-3.1-full-2026-08-13` + its seal (941,467,710 bytes
verified). The 08-12c seal is superseded — its parquet view was
overwritten by the 08-13 build; the old seal file no longer fully
verifies and the 08-13 seal is the live one.** Fidelity batch-1 landed
at dae346da (uncovered 32,648→140, receipt −99.7%); batch 2 (the
679k-label diagnosis + honest release-metadata comparison) in flight.
Three codex research tracks (parse substrate, residual SHACL,
SHACL-SPARQL evidence) running in research/* worktree branches.

**OWNER DECISIONS 2026-08-13 (the four closing questions):** (1) FIRST
SEAL MINTED — key ceremony done (offline ed25519, public key pinned at
docs/seal-allowed-signers, both workflow secrets set — the release
workflow's seal step is ARMED pending only its `if:` flip and a runner);
`output/atlas-3.1-full-2026-08-12c-seal.json` verifies: 4 members, 126
packs, 8 tables, 941,467,636 bytes, signer atlas-release@refspec. Reader
cutover / SpicySearch admission UNBLOCKED. (2) Runner + artifact store:
DEFERRED until release cadence binds (workflow ready; arming is
one line). (3) Fidelity campaign: STARTED with the bulk-SKOS batch
(covered-but-differing units toward exact + specs for the biggest
uncovered; long tail deferred). (4) Standing practices: the four
adopted (strict-parser lint + FR determinism gate in CI now; shapes
scale benchmark + differential-oracle policy at release tier,
armed-idle until the runner).

**PERFORMANCE CAMPAIGN — WHERE IT ACTUALLY LANDED (2026-08-13).**
Acceptance went from **75.7 min / 23.6 GB to 18.5 min / 14.31 GiB
measured** at full scale (29,283,283 quads), on the four owner-visible
moves: the xone lift + gc.freeze + roles-fold, the byte-pass node
digests, the two-index store with pooled terms (ae34392c — the −57% RSS
that took the ">=32 GB self-hosted" runner spec off the release
workflow), and the parse-observer read-folds, whose last two phases
landed at 15b468c8 (310,282 `Graph.triples` calls → 16, artifact-invisible:
`contract-dev` reproduces the pinned manifest and Parquet-view digests).
**The store-query campaign is CLOSED and its residue is named:** the
largest remaining non-SHACL cost is computation, not an undiscovered
query loop, and the `atlas:sourceRecord` sweep stays on the graph by
decision (the index holds the same 34,476 pairs in a different order,
and the gate names the first unreconciled pair — folding it would move a
contractual `firstIssue` to save 0.17s and one call). What remains is
SHACL itself, ~78% of the run — and that floor is now MEASURED AND
CLOSED. `research/residual-shacl` proved the generic lift pattern
exhausted (lifting more made it WORSE, 17.38s → 17.72s).
`research/shacl-floor` then attacked the named remainder and returned a
**DON'T-TAKE with one correction**: a second SHACL implementation is NOT
required, as the prior study claimed. The discovery hypothesis was right
— the four sequence-path value lookups cost 1.838s against just 0.303s
for the `sh:equals` evaluations themselves, 6× — but cashing it in is
worth only 13.097s → 11.652s at staging (11.03%), and the explicit
second-implementation ceiling buys **0.019s more than that**, inside the
sample noise. Neither equivalent shape rewrite helped (`sh:or` for
`sh:xone`: 0.042s SLOWER; materialized direct predicates: 0.292s
slower), and focus-node hints were slower still. The honest floor:
**9.449s of the 11.652s is pySHACL engine work**, with 2.154s in the
lifts we already have. Projected to release scale the whole opportunity
is ~35.7s of an 18.5-min run (~3.2%), extrapolated not measured, against
an unmeasured full-scale memory cost for the required reverse type
index. Verdict: keep the harness and evidence, add no production code,
change no normative shapes. **The performance program is therefore
DONE** — further gains need a different engine, which is the Jena/move-2
door, already measured no-go.

**OPEN — the machine-adjudication archive question, now MEASURED (owner
call, not mine).** Evidence gathered 2026-08-13 against the artifact of
record `output/atlas-3.1-full-2026-08-13`: a full streamed scan of all
126 packs (29,283,283 lines read — the count proves the scan was
complete) found **zero** occurrences of `rkaf:ResolverProofRecord`,
`rkaf:comparisonProofRecord`, `rkaf:AILineage`,
`rkaf:RelationComparisonContext`, `rkaf:ResolverProofIssuer`,
`rkaf:comparisonOutcome`, or `rkaf:gatePass`. What enforces that empty
set: ~390 validator lines (`_check_machine_adjudication`,
validate.py:5459-5848), 7 shape mentions, and — as of 15b468c8 — **24 of
the fact index's 67 allowlisted predicates**, added solely to fold a gate
that has never once had a record to judge. The protocol is
corpus-fixture-exercised only; its runtime was retired in 5ed56db5.
Weighing against deletion, honestly: every term is UPSTREAM rkaf
vocabulary, not Atlas-minted, so this is Atlas refusing malformed
records a rulespec producer *could* emit — deleting it removes a
consumer-visible refusal class rather than merely deleting Atlas's own
scaffolding. That is the trade to decide; the measurement is no longer
the unknown half.

**LANGUAGE-SCOPE WAVE COMPLETE — REBUILT AND PROVEN (2026-08-13).** New
artifact `output/atlas-3.1-full-2026-08-13b/` (built to `/distribution` with
its view at `/parquet-view`, deliberately NOT overwriting 08-13 or its seal —
the 08-13 build had put its view at the shared `output/parquet-view`, so a bare
--output would have invalidated the live seal a second time). distributionId
`urn:ref:atlas:distribution:3.1-full-development:ff86e377…f88b3c`, manifest
sha256 `656e4cc7…7bd3db` (was `18fdcd01…c4b8d6` — definitions re-mint node
digests, by design), releaseCount 110, 29,286,753 quads (+3,470). Smoke passed
over 8 sampled packs. **The gate the rebuild existed for is GREEN:**
observedConstructionStatement == expectedConstructionStatement exactly, and the
whole-distribution scan returns atlasNonEnglishLiteralClaimCount 0,
atlasNoncanonicalSemanticLiteralClaimCount 0, atlasScanFailures []. **ACCEPTANCE PASSED
2026-08-13**: the full 13-gate validate_distribution completed in 1,098.77s
(18.3 min) at a 13.83 GiB peak — 29,286,753 quads, 588,409 resources, 984,431
labels, 560,429 relation assertions (553,540 native, 2,003 mapping, 1
cross-ring), 590,561 source records, 4,669 identifiers, 109 releases, 5,939
inferred mappings. So the acceptance cost is confirmed on the NEW producer, not
just the old artifact: 18.3 min / 13.83 GiB against the previously recorded
18.5 min / 14.31 GiB. **ACCEPTANCE AND THE DECLARATION ARE BOTH PROVEN ON 13b.** Acceptance:
1,098.77s (18.3 min) at 13.83 GiB peak, all gates, 29,286,753 quads / 588,409
resources / 984,431 labels / 560,429 relation assertions / 590,561 source
records / 109 releases / 5,939 inferred mappings. Publisher-side declaration:
a `--only eurovoc-domains-4.24` audit consumed the declaration and reported
declaredPublisherClaimCount 546 — exactly the count itemised for that source in
`language-scope-exclusions.json` — with sourceDeclarationCount 1,
atlasNonEnglishLiteralClaimCount 0, zero scan failures, and the construction
statement matching. ONLY ONE THING REMAINS ON THIS ARTIFACT: minting its seal,
which needs the offline signer key and is therefore the owner's step. All seal
inputs are staged — manifest sha256 `656e4cc79923398ce3f1546cc321e2c40d871bc8d0297c053ba59218877bd3db`,
parquet view manifest sha256 `22a23316cdb16fb01f93bcc3a9bdfaddecaa0f871bf3d8d3f914445b786540c5`,
acceptance receipt written by the run above (`19ca43a5…`). **The step is now one
command** (c4871635 — previously it meant hand-writing a snippet against
`create_seal`):

    make seal-distribution SEAL_ROOT=output/atlas-3.1-full-2026-08-13b SEAL_KEY=<offline key>
    make verify-distribution-seal SEAL_ROOT=output/atlas-3.1-full-2026-08-13b

**All four verbs are now proven on 13b**: BUILD (110 releases, 126 packs),
PROVE (acceptance, 18.3 min / 13.83 GiB, all gates), SIGN (below), SERVE (8
Parquet tables readable by stock pyarrow; `evidence-bindings.parquet` carries
560,429 rows, matching acceptance's relation-assertion count exactly, and
verify_seal independently walked the same 8 tables). Both seal paths were
proven end-to-end on 13b with an ephemeral key that was then destroyed: mint bound all three digests; verify walked 4 members, 126 packs, 8
Parquet tables, 941,856,313 bytes. Minting refuses a distribution with no
acceptance receipt. `docs/seal-allowed-signers` already pins
atlas-release@refspec, and that key is NOT on this machine — checked; no local
key matches the pin — which is the ceremony working as designed.

**ENGINE QUESTION CLOSED WITH REOPEN CRITERIA (2026-08-13,
research/shacl-engine-survey + research/shacl-rust).** The two cells the plan
named as never tested are now resolved. **TopBraid SHACL 1.5.0 is the closest
any engine has come**: it finished the real `atlas.shacl.ttl` at staging in
10.31s in-memory Jena / 14.82s TDB2, did NOT reproduce Jena 6.2's shape-
combination stall at that scale, and agreed with pySHACL on the result fields
Atlas uses across four injected-defect reports. It still fails the bar — it has
not run the 132-case corpus, and its TDB2 profile showed no native-storage
memory advantage. **Jena 5.6 is a dead end**: 11% SLOWER than 6.2 on the
complete staging shapes, no regression to exploit; neither version reproduces
the pathology at bounded scale, which needs the full graph.

**THE ARGUMENT THAT ACTUALLY SETTLES IT, independent of any benchmark:** the
engine is not the validator. Of the sealed corpus's 132 cases (119 invalid, 13
valid), only **48 carry `firstIssue: shacl.data`**, pinning 15 distinct
shaclComponents; the other 84 prove JSON, canonical RDF, pack integrity, graph
placement, dataset relationships, reasoning, lifecycle and registry rules. A
generic SHACL report yields `sh:sourceConstraintComponent`, which an adapter can
normalize — but it cannot emit Atlas refusal identities like `rdf.canonical`,
`pack.content` or `dataset.relation`, and it cannot decide which gate becomes
`firstIssue`. Any engine swap therefore keeps the whole Atlas verdict machinery
and buys at most the SHACL share of 48 cases.

Rust was tested too, not merely surveyed: rudof_cli 0.3.8 (published 2026-08-13)
PARSES the real shapes (376 IR entries, including the sequence-path
`(rdf:object / atlas:inRelease)` carrying `Equals: atlas:targetRelease`) and
emits real SHACL reports, with an oxrdf-backed default backend. **It was then
actually run against the corpus and came far closer than expected: it passes
the executable feature floor, returns the correct INVALID verdict for all 48
SHACL-owned refusals, passes all 13 valid controls, and reproduces the exact
`shaclComponents` set for 45 of 48.** The three misses are not errors — for
`sh:node`, pySHACL includes the inner result while rudof reports only the outer
`NodeConstraintComponent`; both comply with SHACL Core, but only pySHACL matches
Atlas's contractual component lists, so the exact-parity gate fails and the
study stopped before staging cost. Binary tested: rudof_cli 0.3.8, macOS arm64,
sha256 `a1ebe0120fd7b270e4cb452678394fbfa69f0ed8c8be50e7872599875ae6d3be`. Note
what this means: the gap is REPORTING GRANULARITY ON ONE COMPONENT, not
capability — if Atlas ever normalised shaclComponents across the sh:node
boundary, this candidate would clear the gate. Two candidate claims were also
debunked:
`oxigraph-cloud`'s advertised rudof-over-Oxigraph pairing actually serializes
every quad into one in-memory N-Triples string and DROPS GRAPH NAMES (fatal for
a quad-based Atlas), and `oxirs-shacl`'s W3C integration test does not fail when
suite cases fail, skip, or error.

**REOPEN ONLY IF** one of these becomes true — a version bump, a faster toy
benchmark, or W3C conformance alone is NOT sufficient: (a) a compact native
store ships a maintained native SHACL Core engine with Atlas's components and no
term-reconstruction adapter; (b) TopBraid or Jena ships an identified fix for
the combined-shape pathology AND its native-store path shows bounded resident
memory as Atlas focus-node counts grow; (c) shacl-rust, goRDFlib, rudof/QLever
or OxiRS publishes independent conformance evidence plus a direct compact-store
validation path that can be pinned and reproduced offline; (d) pySHACL/RDFLib
gains an integer-ID or encoded-store execution interface that batches discovery
without rebuilding Python terms per lookup.

**THE REMAINING 61 UNITS COST SIX READERS, NOT 61 (research/coverage-dry,
2026-08-13).** Authoritative inventory derived by ast-parsing the SOURCES tuple,
expanding the 14 generated `NATIVE_CONTROL_SOURCES` rows, and subtracting from
the sealed construction summary: 49 of 110 covered, 61 open. (My own regex-based
count of 35/75 was wrong precisely because the 14 `regulatory-native-*` units
are generated, not literal — they were already covered.) The minimum reader set,
with five of six generalising a reader that already exists:
`pattern-row-v2` 42-46 units | `xml-record-selector-v1` 4 |
`json-record-selector-v2` 1 | `csv-record-selector-v2` 3 |
`ooxml-relational-v1` 5 | `nrc-adams-multi-artifact-v1` 2. Six is argued as a
lower bound: pattern rows cannot safely parse structured XML/JSON/CSV/OOXML, and
NRC's six-input semantic union cannot be expressed in the single-input
pattern-row algorithm without inventing a workflow language in configuration.
PROVEN AND LANDED: the FEC HTML family first (4982c0be, 54/110), then the whole
`pattern-row-v2` family — **all 42 units from that one reader, merged at
8e5cb6e0, taking coverage from 54 to 91 of 110**. The reader carries no
`spec.name` dispatch and imports no registry or ETL module, so adding a unit is
adding configuration rather than code; each of the 37 new units got its own
`--only` run against 13b, reached field-level comparison, and reported honest
differences rather than passes. The last five kinds LANDED at 0e85d2a0 —
xml-record-selector-v1, csv-record-selector-v2, ooxml-relational-v1,
nrc-adams-multi-artifact-v1 and json-record-selector-v2, 15 units, **coverage
91 → 106 of 110**, with the JSON kind also deleting the API-capture reader's
spec-name dispatch. The residual 4 units are the raw-PDF ones: BLOCKED rather
than bespoke — an authenticated PDF pin compares no publisher rows, so each
needs a reviewed text or JSON extract added to the construction inputs, after
which a declarative entry covers it. Adding an auditor-side extract or
importing the production PDF ETL would break the independence rule.

**FULL-SCALE ENGINE TEST — THE STAGING OBJECTION IS ANSWERED, AND THE ANSWER
IS NO (research/engine-fullscale, 2026-08-13).** The owner's objection was fair
and the prior survey had conceded it: every engine comparison had run at 1M
staging quads, where a fixed JVM cost could hide a native store's advantage. So
TDB2 was loaded with the real 29,286,753-quad artifact under a hard 600s
timeout, a 6 GiB max heap and an 11 GiB RSS abort guard. **It never reached the
timeout — the memory guard killed it at 96.7 seconds.** Sampled RSS climbed
1,953.6 MiB at 5s → 12,038.5 MiB at 95s: not bounded, steeply growing. At the
stop it had read all 29,286,753 tuples (53.5s), completed the GSPO→GPOS,GOSP
replay (24.0s), and reached 20,000,000 of 29,286,753 items (68.29%) of the
second replay, leaving a 9.157 GiB INVALID store. So **11.756 GiB is a LOWER
BOUND on TDB2's load alone**, against pySHACL's 13.83 GiB for the ENTIRE
13-gate acceptance run including SHACL. The disk-backed native store could not
finish LOADING inside a budget close to what the Python path uses to load AND
validate AND pass. The crossover does not exist in the direction hoped for;
full scale makes the JVM candidates look worse, not better. Trigger (b) below
stands unchanged and is now backed by full-scale evidence rather than a staging
extrapolation.

**DEFECT FOUND BY MANUAL PDF REVIEW — TYPOGRAPHIC LIGATURES ON THE WIRE
(2026-08-13, owner-requested visual check).** The four PDF-pinned units are
blocked for the auditor — an authenticated PDF pin compares no publisher rows —
so they were reviewed against the source document by a HYBRID method whose
halves must not be confused: the pages were rendered and read visually, which
is how the three-table structure, the four-column layout, the repeated
mid-table headers and the source's own truncations were seen; every DEFECT
below came instead from byte inspection of Atlas's output, because a ligature
and a U+2010 hyphen render identically to their ASCII forms and are invisible
to the eye by construction. Neither channel alone would have produced this
result. `ferc-docket-prefixes` carries
**54 Unicode presentation-form ligatures** copied out of the PDF's text layer:
U+FB01 (ﬁ) ×30, U+FB00 (ﬀ) ×21, U+FB03 (ﬃ) ×3. A full sweep of all 126 packs
(29,286,753 quads) finds exactly 54 — every one in this pack, none anywhere
else, so the blast radius is one source. Live examples: "Staﬀ Adjustments under
Section 502 of NGPA", "Certiﬁcates for Interstate Natural Gas Pipeline
Companies", "Exemption Notiﬁcation", "Audits other than ﬁnancial audits".
ATTRIBUTION, CORRECTED — this is NOT Atlas corrupting text. The PDF's OWN text
layer carries the ligatures: an independent pypdf extraction finds U+FB01 x11,
U+FB00 x7, U+FB03 x1 (e.g. "General Tariﬀ Changes for Inters..."), and the ~19
source occurrences become 54 on the wire because each string is emitted three
times — label literalForm, atlas:definition, and nativePayload. Atlas is
byte-faithful to its source. So the item is a NORMALIZATION DECISION, not a
fidelity defect.
WHY IT STILL MATTERS: these are valid Unicode and therefore pass the canonical
byte grammar and the strict-parser lint — nothing in the pipeline is broken, but
a consumer searching "Staff" or "Certificates" does not match. A consumer searching "Certificates" or "Staff"
does not match, which for a vocabulary product is the failure that matters.
FIX: fold presentation forms on the PDF-extraction path (NFKC on that path, or
a targeted ligature map — NFKC applied globally is more aggressive than this
needs and would touch other sources). Wire-visible; re-mints the affected label
and definition nodes.
WHAT ELSE THE SAME REVIEW CONFIRMED, and it is genuinely good: all 95 prefixes
present with ZERO set difference against the PDF; the three source tables are
not flattened — 77 active (Table 1's 73 + Table 2's 4) and 18 discontinued
(Table 3) exactly; every spot-checked definition matches verbatim including the
en-dash in IC; and the third column survives in nativePayload with multi-value
cells intact ("E, G, H, O" for ZZ, "E, G, O, H, Gen" for CE and PA).

**DECIDED — do not re-litigate** (owners' calls, recorded below with
evidence): warrant = option a1 (landed); key custody = offline SSH,
ceremony DEFERRED (mechanism proven; minting is one decision away);
rulespec = package-only, no monorepo; 3.1 replaced 3.0 atomically;
ordering freeze is permanent (golden-observation framing);
Jena = measured no-go (re-open ONLY if sh:class scaling is solved or
move 2 commits to SHACL-SPARQL, which IS the Jena decision, ~100×
measured); oxigraph = only behind the Jena door; P2-as-convention and
kill-7 = dropped from the path; fidelity coverage 23→110 units is the
NAMED SUCCESSOR PROJECT (leg 2 of the pipeline is 21% verified — the
product's weakest true claim).

**PARKED (external owners):** SpicySearch: adopt seal-2 citing
REF-026/028 + the finding-(g) 1.2 decision (both delivered to their
session). Reader/seal admission waits on the owner's key ceremony.
Release-workflow runner + artifact store: infrastructure, unblocks the
weekly reproducible-rebuild job (whose remaining blockers after the
recipeDigest deletion are exactly those two).

**STANDING PRACTICES — adopted from the spikes, DEFERRED (owner: "we'll
do that later"), do when the waves are done:**
- Strict-parser lint step: ~10-line pyoxigraph.parse sweep over the
  packs in the release workflow — permanent "any parser accepts this"
  guarantee (the sweep that found findings (h)/(i)).
- Shapes-change scale benchmark: constraint-shape performance is
  emergent, not compositional (Jena's combination pathology; pySHACL has
  the same exposure) — a staging-scale SHACL timing gate at release
  tier, failing on ~3× regression.
- Differential-oracle pattern as standing policy for any check
  replacement: keep the old implementation as a test-only oracle, prove
  verdict agreement over real data + mutations (caught the silent
  escaped-UCHAR divergence).
- FR double-build determinism gate (~12s) as a release-workflow step —
  the miniature of the weekly reproducible-rebuild job, runnable now.
- Recorded constraints: the sh:class + inoculated-union-view coupling is
  load-bearing (58,730 false violations without it — any engine work
  replicates the view first); instrument-then-optimize is the proven
  loop (bench_phases harness + /usr/bin/sample technique live on the
  spike branches).

**RESEARCH FLEET — ELEVEN BRANCHES, all committed (2026-08-13).** Every
codex 5.6-sol xhigh agent's work survives on its own branch; several were
killed mid-run by an orchestration error (sibling agents suspended under
memory pressure took their harness wrappers down) and carry a final `wip`
commit marking exactly where they stopped. Resume from the wip, do not
restart from scratch.
| branch | state | what it holds |
|---|---|---|
| research/parse-substrate | complete | DON'T-TAKE study + prototype; the −57% RSS finding |
| research/residual-shacl | complete | DON'T-TAKE; the lift pattern's measured floor |
| research/shacl-sparql | complete | portable sh:sparql prototype, 26/26 cross-engine |
| research/move2-compiler | complete, VERIFIED | option (b) proven. The cited rulespec commit 28b37d7b is absent upstream for a disclosed reason, not a fabricated one: the codex sandbox could not write `~/Work/rulespec/.git` (the same workspace-write limitation that blocked RefSpec's submodule commits), so it committed to a local mirror and exported `research/move2/rulespec-compiler.patch.gz` — digest `6c8c9579…4a6d` re-verified by hand, `git am` in a real worktree reproduces it. Its own report says so. Fix for next time: add the rulespec git dir to `sandbox_workspace_write.writable_roots`. |
| research/fidelity-coverage | INTEGRATING | the inventory + payoff order (consumed by four batches) AND three unlanded SourceSpecs — mesh-descriptors, federal-register-api-topics, gcmd-science-keywords. I wrongly recorded this branch as code-free; cov-json caught it reconciling 28 declared specs against an assumed 31. An agent is integrating them onto current main. |
| research/fidelity-definitions | complete | the carry/declare decision package |
| research/fidelity-langbugs | MERGED e3fd49f1 | one BCP-47 predicate + English definitions/scope notes carried; cherry-picked (its base predates the substrate). Integration found a real defect: it stripped annotation whitespace on the parser path while asserting the claims path preserved it, and the reconciling test skipped in its worktree for want of a generated output/ tree. Both paths strip now — definitions enter node digests, so a stray publisher newline would have made node identity depend on which path built the release. |
| feat/parse-substrate | MERGED ae34392c | parse_substrate.py + validator wiring; corpus 130/130 identical; seam is REFSPEC_ATLAS_RDF_STORE=two-index|memory |
| research/graph-residual | MERGED 15b468c8 | the observer campaign's last two folds; 310,282 store calls → 16 |
| research/shacl-engine-survey | complete, research-only | TopBraid 1.5.0 + Jena 5.6 measured; measurements/ holds the raw jsonl; no production code |
| research/shacl-rust | in flight (round 2) | rudof_cli 0.3.8 runs the real shapes; corpus parity pending |
| research/coverage-dry | in flight | authoritative 49/110 inventory; declarative FEC HTML family proven |
| research/shacl-floor | complete | DON'T-TAKE; the SHACL floor measured (9.449s of 11.652s is engine); corrects residual-shacl's "needs a second implementation" |
| research/coverage-bulk | MERGED 18283ce5 | four bulk-vocabulary readers; campaign coverage 27/110 → 31/110 |
| research/auditor-language-scope | MERGED 7a9d75c7 | NASA note-kind fix (19,312 false failure rows → 0) + a checked English scope declaration proving the distribution asserts no non-English literal anywhere. RED BY DESIGN against the 08-13 artifact, which predates the producer change; goes green only on a distribution rebuilt at e3fd49f1 or later. |
| research/coverage-bulk | MERGED 18283ce5 | four bulk-vocabulary readers, 446,906 records; FAST verification 11.803 → 7.879 GiB, receipts byte-identical |
| research/coverage-json | MERGED fa7839f4 | all 18 JSON/API-capture units; resolved the memory refactor across 11 conflict regions without weakening a comparison |
| research/coverage-{csv-pdf,html-misc} | wip, NOT resumed | ~2,000 lines each, committed; both need the same integration-first resume |

**WORKTREES ARE DISPOSABLE; THE BRANCHES ARE THE RECORD.** `.claude/worktrees/`
holds ~13 GB across ~18 checkouts. Every one is safe to `git worktree remove` —
each branch, its commits, its REPORT.md and its committed measurements survive
independently, and the ledger above says what each branch holds. Verified
2026-08-13: the merged coverage/substrate worktrees are clean and main is ahead
of all of them. Two are expensive to recreate but still regenerable by
digest-verified download rather than irreplaceable:
`agent-a7937c98dc15549c2` (2.0 GB, vendored Temurin JDK + Jena; `bin/clean-data`
drops its intermediates) and `agent-a9301012cdaa44814` (795 MB, pinned
pyoxigraph venv). Left in place deliberately — disk is not scarce (268 GB free)
and deleting them buys nothing the ledger does not already record.

**ORCHESTRATION LESSONS (recorded so they are not relearned):** never
SIGSTOP a codex agent — its harness wrapper exits and the agent dies;
size the fleet to the machine (six xhigh agents plus a 14 GB validation
on a 48 GB box drove 8.7 GB of swap and killed everything); wait-loops
must match child PIDs, not name patterns (a codex prompt containing a
path makes pgrep match forever); and RSS measured under swap pressure
UNDERSTATES demand, so memory numbers require a quiet machine.

**Spike evidence — COMMITTED AS BRANCHES (2026-08-12):**
`spike/oxigraph-substrate` (f81b3749) and `spike/jena-shacl` (028dd63b).
The worktrees under .claude/worktrees/ hold the same branches checked out
plus the gitignored heavy assets (pinned-binding copy; JDK/Jena
downloads; regenerable data — bin/reproduce re-fetches by verified
digest). The branches survive worktree cleanup; the notes below describe
what each carries:
- Oxigraph: `.claude/worktrees/agent-a9301012cdaa44814/spike/` —
  scripts q1_parse.py..q7_bytes_are_enough.py, the IRI-escape ETL,
  `measurements.jsonl` (all raw numbers), pinned venv (pyoxigraph 0.5.9,
  oxrdflib 0.5.0). Source of: the byte-pass parity proofs (3.29M node
  digests exact), the 7,770-IRI and literal-form defect discoveries, the
  full-scale parse-count technique (54.5s/29.3M quads, constant memory).
- Jena: `.claude/worktrees/agent-a7937c98dc15549c2/jena-spike/` —
  `bin/reproduce` end-to-end, prep/inject/compare scripts, vendored
  Temurin JDK 21 + Jena 6.2.0 tarballs (digest-verified), `out/`
  reports; `bin/clean-data` drops the ~13 GB intermediates. Source of:
  the parity PASS, the sh:class scaling lead, the ~100× SHACL-SPARQL
  number, the report-canonicalization rules.

**Stale-entry corrections for the sections below** (kept for history, do
not act on them): the "Open items" REF-026 entry is DONE (cce6f0ce); the
warrant BLOCKER is RESOLVED (a64eee58); "fresh full build" now means
08-12b, not 08-11; kill-8's ordering-unfreeze clause is superseded by
wire-wave decision 2.

---

2026-08-11, v3. v1 pulled punches; v2 cut to barebones; v3 incorporates an
independent adversarial review (run with the repo's culture files quarantined,
arguing from industry practice only) that verified the evidence, endorsed the
thesis, and found four defects that would have made v2 fail on contact. The
review's verdicts: 8 of 10 kills AGREE/AGREE-WITH-AMENDMENT, one DISAGREE as
sequenced (SHACL fast path), SSSOM agreed with amendments.

## The system, defined

Four verbs: **build** a vocabulary distribution → **prove** semantic
conformance, once, at build → **sign** the result → **serve** it (parquet →
SpicySearch). Anything not one of these four verbs is overhead and is guilty
until a running consumer is named — enforced as version-gated deprecation for
anything wire-visible, immediate for internal code.

## Measured evidence (2026-08-11, this machine; independently re-verified)

- `make test`: claimed ~60s, measured **111.6s** — drifted 1.9× unnoticed.
- Sealed-corpus run: claimed ~33s, measured 40.8s, single-core.
- Production scale: `atlas-3.0-full-2026-08-10` = **32.0M N-Quads, 7.3 GB
  decompressed**, 126 packs + 486 MB compact JSONL; `validate_distribution`
  ≈ **one hour on one core, ~5 GB RSS**; source-accounting alone 47.7s.
- Layer inventory: ~37,400 lines bespoke validation, +14,200 declarative,
  +16,000 validator-tests, +4,819-line fixture factory. `src/refspec` =
  102,660 lines (exact).
- Verified drift: `explorer_rdf.py:57` required 11 acceptance gates,
  `validate.py:764` requires 13 (missing `explorer-reachability`,
  `machine-adjudication`). [RESOLVED: patched in cd769d44, then the whole
  RDF explorer deleted in 83bf5d01 — the drift class is gone with its
  carrier.] Eligibility lattice ×3 + currency test confirmed [RESOLVED:
  one packaged import, 3d98985a].
  (A claimed five-axis-rule code duplication was NOT confirmed: one
  definition at `validate.py:471`; the generator imports it. The ledger's
  duplication note may refer to ontology prose — verify before citing.)
- `projectedRelations: 0` **and** `derivedRelations: 0` in the 08-10
  manifest — parity checkers guard empty layers.
- Makefile `ATLAS_V3_AUDIT_ROOT` default points at the 08-07 distribution
  whose `constructorProfile` HEAD's binding refuses (`validate.py:7207`).
- **CI exists as of 2026-08-11 17:03** (`.github/workflows/ci.yml`): lint,
  check-generated, registry audit, JSON binding, packaged suite —
  `timeout-minutes: 20`, and runners never have `output/`. Consequence: the
  acceptance tier does NOT fit existing CI; a separate release workflow with
  a larger/self-hosted runner and artifact store is required. Until it
  exists, the laptop IS the acceptance environment — stated honestly.
- `sssom>=0.4` is in dev deps and imported nowhere — the SSSOM row below is
  aspiration, not integration, until the migration executes.
- `atlas.shacl.ttl` (1,802 lines) contains **zero** `sh:sparql` today —
  folding Python checks into shapes is new work, budgeted as such.
- **Per-phase timing, landed (instrumented run, 2026-08-11): total 7,222s
  (~2h), failed at the SHACL gate.** `run-shacl` 5,639s (**78.1%**);
  `parse-rdf-packs` 1,534s (**21.2%**, 18.3 GB RSS); source-accounting
  47.7s; closed-distribution digest walk 0.25s; all later phases never ran.
  Implications: (a) transport-integrity was never the wall — rdflib ingest +
  pySHACL are; (b) the kill-5 measurement exists: bare pySHACL at 32M quads
  ≈ 94 min for one asserted-graph pass — the batched fast path is
  load-bearing and stays; (c) **the 08-10 distribution fails HEAD's shapes**
  — all 2,003 evidence bindings violate `atlas:EvidenceBindingShape`'s
  warrant `sh:xone` (the branch's evidence-model change), so combined with
  the 08-07 `constructorProfile` refusal, **no full multi-scheme
  distribution on disk validates under HEAD; a fresh full build precedes
  the first full sealed release.** Scope correction (2026-08-11, from the
  reconciliation session, digest-verified here): one HEAD-conforming
  distribution DOES exist —
  `output/atlas-3.0-federal-register-thesaurus-2025-04-01/distribution`,
  the bounded FR Thesaurus built today under HEAD's binding
  (producer-validated, 57,686 quads, manifest sha256 `d5c198b8…04f1e4`,
  byte-identical across three rebuilds). It is the engine-parity and
  dev-iteration artifact of record.

## Diagnosis, one paragraph

The culture's only rule — no structure without a check — has no counterweight,
so the ratchet only tightens: every defect got a detector, duplication got
currency tests instead of deletion, consumers re-derive two million digests
they already hold, and the integrity half of the validator is a single-core
Python reimplementation of git's object model that never trusts its own
Merkle root. The governance half models an approval bureaucracy for an
institution that does not exist. Review's structural note, adopted: the cuts
must stand on engineering grounds (YAGNI, test-pyramid economics,
single-source-of-truth, supply-chain norms), not on the repo's internal
culture rules — citing the culture to correct the culture is circular.

## Seal design (PRECONDITION — no seal ships before this section is real)

1. **What the signature attests.** A detached signature over the canonical
   manifest digest attests provenance only. The signed manifest MUST embed
   the digest of the acceptance receipt (gate names, results, tool digests),
   so verifying the seal transitively verifies that acceptance ran, with
   which gates, on these bytes. Without this, the consumer story attests
   provenance while claiming correctness. **Normative: `verify_seal` =
   signature check + root digest + member-digest walk** — not signature
   alone. SpicySearch's admission gate (and the DocSpec port pattern)
   recomputes member digests at admission and open; a signature-only
   `verify_seal` would be refused at that seam. The SpicySearch plan is the
   named coordinating party for `verify_seal`'s interface and for the
   wire-format cuts (step 9). Coordination state (2026-08-11): SpicySearch's
   plan deliberately stays silent on `verify_seal` until REF-026 exists
   (ecosystem rule: cite decisions by identifier), then cites it in its
   artifact-flow section — **REF-026 is the identifier that closes this
   seam.** Until then, the live seam contracts a `verify_seal` prototype
   must be tested against are:
   `spicysearch/src/spicysearch/snapshot_distribution.py` (admission/open,
   closed membership, per-member digests) and
   `DocSpec/src/docspec/adapters/source_catalog.py:268-297` (digest
   recomputed over raw bytes before parsing, at both admit and open).
2. **Key custody.** Offline or hardware-backed minisign / `ssh-keygen -Y`
   key; signing happens only in a dedicated release workflow, never beside
   ad-hoc builds. Prefer Sigstore keyless + Rekor transparency log if GitHub
   OIDC is acceptable — eliminates custody and adds an audit log for free.
   Public key pinned in ≥2 independent places (this repo + consumer repo).
   Rotation: key-list file with IDs and expiry; written revocation format.
3. **Freshness/rollback.** Detached signatures have no freshness semantics.
   Stance: distributions are immutable and versioned; consumers pin
   `distributionId` and enforce version monotonicity. (Full TUF is overkill
   today; this paragraph is the deliberate residue of that decision.)
4. **The real independent control.** In a single-maintainer topology the
   producer, validator author, signer, and consumer operator are one person;
   no signature fixes that. The independent assurance is **reproducible
   rebuild**: a scheduled clean-environment job rebuilds the distribution,
   compares the canonical manifest digest, and re-runs the full validator
   against a shipped artifact. This keeps re-derivation alive as a practiced
   capability and is what makes the public-sector story honest.

## KILL LIST (v3 — review verdicts applied)

1. **Governance suite → extract, then archive [AGREE-WITH-AMENDMENT].**
   The workflow machinery (attestations, adoptions, sealed-gold
   adjudication, eligibility gating — `binding.py` 2,665, `release_graph.py`
   1,688, `managed_release.py` 3,086, `vocabulary.py` 4,842,
   `accepted_output.py` 554, REF JSON schemas 4,266, tests ~4,000) has no
   operating institution; unexercised compliance machinery is an audit
   liability, not an asset. **BUT the build imports parts of it** —
   `generate_atlas_v3_full.py` uses `binding.canonical_sha256` and
   `managed_release.ManagedReleaseGraphFactsView`; `atlas/{model,
   federal_register,icpsr,concept_release}.py` and
   `managed_vocabulary_bundle.py` import `ManagedRelease*` classes,
   `rulespec_graph_digest`, and `vocabulary.py` column constants.
   **Extraction first**: move the load-bearing data model into a small
   `refspec/release_model.py`, re-point the five importers, then archive the
   workflow. Budget: days, not hours. Archiving preserves *design
   knowledge*, not runnable code: record branch name, commit, and a
   two-paragraph summary in the ledger; do not promise revival.

   **v3.5 — extraction EXECUTED (2026-08-11), and it corrects this item's
   scope.** `release_model.py` landed (259 lines moved verbatim, canonical
   primitives + ManagedRelease* data classes + rulespec_graph_digest +
   column constants; one-way dependency verified; 371 targeted tests
   green). Findings that revise the archive scope: (a)
   `ManagedReleaseGraphFactsView` is NOT extractable — it is the
   managed-release bundle READER (~1,220 lines transitively requiring
   binding.py's full JSON-Schema stack and release_graph.py's gate pins,
   one of which hashes release_graph.py's own source bytes). So
   `managed_release.py` is ~90% build-path reader / ~10% governance: the
   archive line becomes a SPLIT — archive `require_candidate_use` +
   `ManagedReleaseCandidatePermission` (+ `accepted_output.py` wholesale);
   `binding.py` and `release_graph.py` are likewise NOT archivable as whole
   files. (b) The importer list was incomplete: ~8 more one-line re-points
   remain (atlas_index, resource_catalog, source_concept_release,
   federal_register_thesaurus_2025_managed_release, concept_domain_bridge,
   generate_atlas_v3_registry_coverage; plus moving CORE_FACETS,
   canonical_text_digest/normalize_unicode_text, require_language_tag). (c)
   `refspec/__init__.py` eagerly imports governance modules — import-time
   decoupling requires trimming it. [DONE 2026-08-11: PEP 562 lazy
   __getattr__, __all__ preserved, identity verified.] (c2) The mechanical
   re-points are DONE except one principled hold: `require_language_tag`
   stays in `vocabulary.py` — its closure (`ReferenceRuntimeError`,
   `_require_text`; 283/63 uses) IS the governance record model, so
   `vocabulary.py` joins `managed_release.py`/`binding.py`/
   `release_graph.py` as split-not-archive. (d) Re-pointing
   `generate_atlas_v3_full.py` required its sanctioned `--repin`
   (2cd5756a→952a4d87); PLAN.md:332 still records the old digest and needs
   annotation.
2. **Stored per-node `contentDigest` [AGREE-WITH-AMENDMENT].** Grounds:
   ~7% payload with zero consumers — not the pin syllogism (which would
   condemn every legitimate denormalization). Note: content-derived IRIs do
   NOT substitute (identity hash ≠ content hash — verified on label nodes).
   Mechanics: stop read-time verification now; remove from the wire at the
   next distribution version with a deprecation note; **retain the digest as
   a Parquet column** (nearly free, keeps record-level citation buildable).
3. **Compact JSONL layer [AGREE-WITH-AMENDMENT].** It is not a redundant
   copy — it is currently the Parquet feed (`parquet_view.py:26` reads
   compact packs). Replacement derivation, decided: **emit Parquet directly
   from the builder's in-memory model at build time** (Parquet becomes the
   compact layer), with one RDF↔Parquet parity check at build. Re-parsing
   32M N-Quads to build Parquet is explicitly rejected. Wire removal is
   version-gated.
4. **Validation receipt cache (HMAC subsystem) [AGREE].** Frequency change
   makes the cached computation non-repeated; caches of validation results
   are a known false-trust hazard (the recorded cache-key defect is the
   canonical failure).
5. **Batched SHACL fast path [RESOLVED: KEEP].** The measurement landed
   2026-08-11: bare pySHACL over the 32M-quad asserted graph ≈ **94
   minutes** for a single pass (78% of a 2h run). The batched path is the
   acceptance gate's load-bearing floor and stays. A build-side subprocess
   engine remains the pre-approved contingency — still the only door engine
   talk enters through, and still build-side only. **Contingency evaluation
   protocol** (with the reconciliation session, 2026-08-11): two roles
   priced separately — (a) full-pass fallback if the batched path ever
   fails a conforming-build budget, and (b) the v3.3 red-path role, where a
   subprocess engine re-validating only failing focus nodes could collapse
   the 94-minute report-phrasing cost to minutes (possibly the more
   valuable role). Rules: parity first on the HEAD-conforming FR Thesaurus
   artifact (violation sets must both be empty), never benchmark on the
   non-conforming full distributions (that times the failure path and
   diffs the evidence-model change, not engine semantics); pin owl:imports
   and entailment settings identically before any differential run; the
   comparison cell is TopQuadrant SHACL / Jena (oxigraph has no mature
   SHACL); JVM confined to the release workflow — consumers and runtime
   bundles never see it; violation reports must be canonicalized (sort by
   focusNode/sourceShape/path) in the gate module regardless of engine,
   because receipts embed in the signed manifest and report-order flap
   would flap receipt digests; kill-8's per-failure-code fixtures are
   designed to double as the permanent engine-parity corpus; and a
   synthetic `sh:sparql` shape is benchmarked at scale BEFORE
   boundary-collapse move 2 commits to compiler-emitted SHACL-SPARQL,
   since that is the one factor where Jena is first-class and pySHACL is
   weak.
6. **Read-time canonicality enforcement [AGREE].** Canonical form is a
   producer invariant (schema-on-write): enforced at the single write site
   plus one streaming check at build. Consumers never re-lex 32M lines.
7. **Registry audit machinery [AGREE-WITH-AMENDMENT].** Accurately: three
   tools (verify 651 + manifest builder 1,403 + pytest plugin 352). The
   AST-scraping and receipt-capture meta-machinery — testing the tests —
   collapses to "every registry module has a test file" (~50 lines). **Keep
   the hermetic source-manifest `--check`**: input pinning is supply-chain
   hygiene, not meta-testing.
8. **Fixture factory [AGREE-WITH-AMENDMENT].** 4,819 generator lines /
   8,340 files / 73 MB for ~115 failure codes is fixture obesity. Replace
   with minimal per-failure-code fixtures (a fixture small enough to BE the
   documentation of its failure mode) **plus a small shared builder-helper
   module** so hand-written doesn't mean copy-pasted. Error codes stay
   contractual; error ordering unfreezes.
9. **Reader-side re-verification → `verify_seal` [AGREE-WITH-AMENDMENT].**
   Matches apt/TUF/Sigstore norms — consumers do not re-run the producer's
   test suite — and the verified 11-vs-13 gate drift proves independent
   re-implementation *reduces* assurance over time. Preconditions: the seal
   design section above (receipt binding, key custody), and the full
   validator keeps **one scheduled invocation** against a shipped artifact
   (the reproducible-rebuild job) so re-derivation stays alive.
10. **Copy-plus-currency-test → one import [AGREE].** A currency test pays
    maintenance to preserve duplication instead of deleting it; one imported
    definition removes the drift class structurally.

## The rulespec boundary, collapsed (v3.2)

Constraint update: **rulespec is ours.** Any upstream change is in scope if
it reduces code, improves DX/dev speed, and adds no future architectural
debt. Three moves, in order of (payoff ÷ risk):

1. **Ship rulespec as a versioned package, not a sibling checkout.** One
   `rulespec` (or `rkaf`) package carrying: compiled JSON Schemas, compiled
   SHACL, JSON-LD context, generated Python types, and the lattices/enums
   **as importable data**. RefSpec takes it via `uv add` like any
   dependency. Deletes in RefSpec: checkout discovery
   (`REFSPEC_RULESPEC_CHECKOUT`), `validate_rulespec_gate.py` (150),
   `test_rulespec_vocabulary_currency.py` (297 — an unknown rkaf term
   becomes an ImportError at build: fix-by-construction replaces text
   scanning), `test_usage_eligibility_lattice_currency.py` (199 — the three
   lattice copies become `from rkaf import USAGE_ELIGIBILITY`), the
   dependency-manifest self-certification ceremony, and the subprocess
   pinning of Rust CLIs on RefSpec's path (Rust validators remain for
   rulespec's own CI and any external consumer). Also ends the
   worktree/uv-cache cross-repo build pain. Contract bumps become lockfile
   bumps. **Working precedent as of 2026-08-11:** rulespec-conformance
   already ships as a wheel verified from an installed package with no
   checkout (`make test-package`), and spicy-regs PLAN.md §6 schedules the
   editable-install deletion on its side — this move extends an existing
   pattern, not a new bet.
2. **One implementation per rule: the CUE compiler emits the check;
   consumers execute, never re-implement.** The adjudication protocol's
   constraints (five-axis independence, warrant closure, verdict lattice)
   compile from CUE into the published SHACL (`sh:sparql` where shapes
   can't express them) plus, where SPARQL genuinely can't say it, a small
   Python gate module *inside the rulespec package*, tested once upstream.
   RefSpec's ~900 protocol lines shrink to invocations. The 4-vs-5-axis
   defect class (shipped SHACL disagreeing with prose and runtime) dies
   structurally: there is nothing downstream left to disagree.
3. **Decide the monorepo deliberately.** The 2026-08-04 deferral of
   shared-foundation unification predates this measurement of what the
   boundary costs. If no third party consumes rulespec releases today, a uv
   workspace monorepo makes contract + consumer + fixtures one atomic
   commit and deletes inter-repo versioning permanently; packages still
   publish separately from a workspace, so the portability story survives.
   If the answer is no, move 1 alone captures most of the value.

Guardrails (the debt this section must not create): rulespec stays generic —
no Atlas-specific terms or checks migrate upstream (boundary inversion is
the one way this collapse rots); rkaf remains the single ontology; RefSpec
never re-grows a local copy of anything the package exports.

## What the 2h instrumented run changes (v3.3)

1. **Red builds must be fast — the failure path is 20× the success path,
   which is backwards for development.** The 94 SHACL minutes were the
   *fallback*: the batched prechecks detected a miss in seconds-to-minutes,
   then the full normative engine ran solely to phrase the report. You
   iterate on red builds; today a red build costs ~2h to say "evidence
   bindings are wrong." Change: dev-mode validation reports from the fast
   path's own miss detection (it knows which lifted constraint failed on
   which nodes) or re-validates only the failing focus nodes
   (`abort_on_first` / targeted shapes); the full normative report becomes
   release/audit-mode only.
2. **Sample-first smoke tier.** All 2,003 violations were the same defect;
   one evidence binding validated at fixture scale (~50ms) would have
   caught it. Dev builds shape-check a bounded sample per pack (seconds);
   the full pass runs only in the release workflow. Test-pyramid economics
   applied to data, not just code.
3. **Release-runner spec is now measurable:** ≥32 GB RAM (18.3 GB RSS at
   parse alone), ~1h wall budget, single beefy core beats many small ones
   (the pipeline is serial and memory-bound; naive multiprocess parsing
   multiplies the 18 GB, it does not divide the wall).
4. **The phase table is COMPLETE (2026-08-12, conforming 08-12 build —
   the first full multi-scheme distribution to pass HEAD's binding
   independently; 32,011,869 quads, 4,539.8s ≈ 75.7 min, 23.6 GB peak).**
   Split: SHACL fast-path green 1,957s (43.1%); parse 1,373s (30.2%);
   graph-roles 570s (12.6%); compact sample 209s + node digests 131s +
   evidence/assertions 145s + accounting 87s ≈ 12%; SKOS integrity 5.2s;
   adjudication 9.5s; reasoning isolation/derived/projection ~0 (empty
   layers). Verdict: the integrity phases the reset's diagnosis blamed are
   ~7.5% of acceptance — the wall is the SHACL engine + rdflib parse,
   which is where kill-5's engine contingency already points and which
   runs once per release. The wire cuts stand on no-consumer grounds, as
   stated. The hand-written SKOS bitset machinery is measured at 0.1% —
   structure that earned its keep.

   **Inside-the-phases trace (fable, live-sampled + staging-profiled,
   2026-08-12, 3.1 run ≈62 min):** ~67% of the SHACL phase (~21 min of the
   hour) is the warrant `sh:xone` evaluated by engine trial — ~3.5M branch
   validations, five of six failing by design, each minting a discarded
   pretty-printed report. The guarantee is a six-entry frozenset; the lift
   pattern exists in-code (`_can_lift_relation_ring_context`), A/B measured
   151× at staging. Parse = 60% rdflib substrate + 28% canonicality proof
   (KEEP — it carries the consumer's identity digests) + 12% bookkeeping.
   graph-roles' 500s is CPU-bound store iteration; half folds into the
   parse observer. Sanctioned optimizations (kill-5 pattern, no new
   decision): xone lift (−~21 min), gc.freeze after parse (−1-2 min),
   graph-roles sweep fold (−~4 min) → **62 → ~37 min**; the residual floor
   is rdflib, and only the pre-approved kill-5 subprocess engine goes
   below it — not needed at once-per-release frequency.
   **IMPLEMENTED and measured at staging (2026-08-12): total 91→53s
   (−42%), SHACL −68% (xone lifted by parsing the branch table off the
   wire — semantics never restated; a drifted shape refuses the lift
   loudly and falls back to the engine; the pinned signature must move
   WITH any future warrant-model amendment), graph-roles −79% (parse
   observer, same codes/messages, failure order now deterministic),
   peak RSS −37%. Corpus byte-unchanged; all 47 shacl.data cases agree
   across fail-fast/audit/published components. Projected full scale:
   ~32–36 min. Engine-door spikes (oxigraph substrate, Jena SHACL) are
   measuring the rungs below in parallel worktrees.**

## Target architecture: minimum required, by industry standard

| Actual feature | Standard carrier | Bespoke remainder |
|---|---|---|
| Vocabulary releases | SKOS/SKOS-XL, versioned distributions | publisher ETL adapters |
| Mapping statements | SKOS `skos:*Match` triples (projection) | — |
| Mapping evidence + adjudication | rkaf (upstream contract — no standard substitute) | ~900 lines at acceptance |
| Mapping interchange | SSSOM + SEMAPV — **deferred** until a consumer names itself | derived TSV view, then |
| Semantic conformance | SHACL (pySHACL or measured fallback) | shapes + one gate module |
| Canonical bytes | RDFC-1.0 / sorted skolemized N-Quads at write | none — serializer property |
| Integrity & trust | detached signature per Seal design | ~100-line `verify_seal` |
| Independent assurance | reproducible rebuild (SLSA/reproducible-builds practice) | scheduled job |
| Serving | Parquet + DuckDB, fed directly from the builder | view builder |
| Provenance | W3C PROV (via rkaf) | none |
| Transcription fidelity | no standard exists | the auditor — the differentiator |

**SSSOM, re-scoped (v3.1): deferred derived view, not carrier.** SSSOM
covers the mapping statement + curation provenance (justification, author,
confidence, tool, versions). It does NOT carry what rulespec provides:
evidence bindings pinning sealed source-record digests, the adjudication
proof chain, lifecycle/supersession temporal records, or the contract
relationship itself (rkaf = CUE-authored constraints with upstream
validators; SSSOM = column conventions). A carrier swap would need an
upstream RuleSpec decision and an evidence-model redesign to migrate 2,003
assertions whose ~900 lines of checks run at acceptance, where cost is
already irrelevant. Resolution: **rkaf remains the mapping carrier** (one
ontology, upstream-validated, cheap at acceptance frequency); the plan
becomes fully RefSpec-local with no cross-repo dependency. **Keep the
`skos:*Match` projection triples in the RDF** — ~2k triples, the
W3C-standard publication form; deferring them saves nothing.

**Prior art — SSSOM was tried and retired, and the difference matters.**
`3e975876` (2026-08-03) built a real SSSOM TSV exporter (deterministic,
edition-scoped prefixes because Bioregistry's `elsst` record expands to
edition 3 and would rewrite R6 IRIs; per-row `urn:` mapping_source; sssom-py
round-trip oracle). `5ed56db5` deleted it with the crosswalk runtime;
`546c4940` (2026-08-10) deleted the last README promise because the exporter
had no production writer and no consumer — SSSOM as a *bolt-on second view*
died, correctly. This plan proposes SSSOM as the *primary carrier replacing*
the bespoke reification: the build is the writer, sssom-py the validator,
deletion economics the justification — which satisfies `546c4940`'s own
revival clause ("a real producer and consumer appear"). v3.1 resolution:
that clause is the standing trigger. SSSOM returns only as a build-derived
TSV view when a real external consumer names itself (curation workflow, OAK
tooling, a mapping partner); the build is then the writer, sssom-py the
gate, and the exporter's lessons (edition-scoped prefixes, `urn:`
mapping_source, oracle round-trip) are recovered from `5ed56db5^` rather
than re-learned. Building it before the trigger fires repeats the mistake
retired on 08-10. The orphaned `sssom` dev dependency is removed until then.

Entitled bespoke code: (1) publisher adapters, (2) shapes + one gate module,
(3) the fidelity auditor, (4) the seal, (5) the reproducible-rebuild job.

Check regime: **build** = SHACL + sssom-py + manifest JSON Schema + semantic
gates + canonicality/reproducibility pass + sign-with-receipt. **read** =
verify seal. **audit** (scheduled) = fidelity auditor + reproducible rebuild
+ full validator on a shipped artifact. **dev loop** = lint + parquet
preflight, with `make test` under a 60s budget (warn >60s; hard FAIL at
240s as a runaway guard — the 120s line re-arms once the suite is next
measured under 60s; see the budget re-spec open item).

## Order of execution (v3 — dependencies corrected)

1. Moratorium on new checks/receipts/currency tests (now).
2. **Seal design section made real** (key custody, receipt binding,
   freshness stance). One page. Blocks everything seal-shaped.
3. **Fresh distribution build under HEAD's binding** (nothing on disk
   validates at HEAD; blocks seal minting and end-to-end reader cutover).
   Runs in parallel with seal design. Re-run the instrumented pass on it to
   complete the phase table.
4. Seal + `verify_seal`, minted only with an embedded acceptance receipt.
5. Readers cut over to the seal; drifted copies and currency tests deleted.
   Red-path fail-fast + sample smoke tier (v3.3 items 1–2) land with the
   same change to `validate.py`'s SHACL section.
6. **Release workflow** stood up (self-hosted/large runner, ≥32 GB RAM,
   ~1h budget, + artifact store) — the acceptance tier's real home;
   existing 20-min CI keeps the dev tiers. Reproducible-rebuild job
   scheduled.
7. **Rulespec packaging** (boundary-collapse move 1): publish the package,
   `uv add` it, delete the checkout gate + both currency tests + the copies
   they policed. Monorepo decision (move 3) taken here, deliberately, and
   recorded. Compiler-emits-the-check (move 2) proceeds as rulespec work in
   parallel.
8. Governance extraction (`release_model.py`), importer re-pointing, then
   archive branch + ledger entry.
9. Wire-format cuts (node digests → Parquet column; JSONL retired once
   Parquet derives from the builder) at the next distribution version, with
   deprecation notes. SKOS `skos:*Match` projection triples land here.
10. Corpus unfreeze (codes contractual, order not) + fixture-factory
    retirement behind the shared helper.
11. SSSOM: nothing, until the 546c4940 trigger fires (a named external
    consumer). Then: derived TSV view from the build, exporter lessons
    recovered from `5ed56db5^`. Drop the unused `sssom` dev dependency now.

**ENGINE-FLOOR RESEARCH CLOSED (2026-08-13, three codex 5.6-sol xhigh
tracks; branches research/parse-substrate e4bce197,
research/residual-shacl 3154b751, research/shacl-sparql 1c5f1d12).**
1. *Residual SHACL — DON'T-TAKE, the lift pattern has reached its floor.*
   The broad lift removed 353 of 615 constraint-parameter occurrences and
   cut engine time 14.17s→6.61s at staging, but TOTAL time ROSE
   17.38s→17.72s (+2.0%): the table checks cost more than the engine work
   they replaced. Best isolated avenue (sh:class) saved 0.9%. What
   remains is RDF traversal inside pySHACL — sh:xone on
   MappingAssertionShape plus four sequence-path sh:equals shapes —
   liftable only by writing a second SHACL implementation.
2. *Parse substrate — DON'T-TAKE now, prototype PRESERVED.* Two-index
   store + pooled terms: parse+store 20.71s→14.78s (−28.6%), peak RSS
   1,380→567 MiB (−58.9%); complete semantic path 49.21s→33.71s
   (−31.5%), RSS 1,434→617 MiB (−57.0%); identical verdicts on the real
   shapes and all 130 corpus cases; index choice instrumented (OSP never
   queried by this workload). Rejected on OWNERSHIP (8–12 days to own a
   custom RDF store for ~6.6 min/release), not feasibility. Sharded
   parallel parse rejected on measurement (slower AND larger).
   **ORCHESTRATOR NOTE — the memory half may matter before the time
   half:** peak RSS is what forces the ≥32 GB self-hosted runner in the
   release-workflow spec; at these ratios full acceptance would fit in
   ~9 GB, i.e. a standard hosted runner. Re-open this the day CI is
   meant to own acceptance.
3. *SHACL-SPARQL — portable, and the blocker's premises corrected.* All
   four adjudication rules expressed as portable SPARQL 1.1 (164 lines,
   115 of SPARQL); 26/26 fixture checks agree across pySHACL and Jena.
   Jena is 250× inside validation / 82× end-to-end, but pySHACL's
   ABSOLUTE time at bounded staging scale is 3.24 min — viable
   once-per-release, so sh:sparql emission does NOT by itself force Jena
   at bounded scale (it does at 32M quads: ~90 min estimated for these
   four queries alone). Two corrections: the "~900 lines deleted" figure
   is wrong (the adjudication block is 516 lines; these four rules are
   ~128 — move 2 is CODE-NEUTRAL at first, its value is single-source
   generation), and the staging artifact contains ZERO adjudication
   records, so timings used a derived target-loaded view and production
   deletion stays blocked on a target-bearing artifact plus the
   AGENTS.md differential-oracle battery.

**READ-FOLD LANDED (5feb5458):** `_AssertedFacts` extends the parse
observer from placement to reads — Graph.triples calls across the four
read-heavy gates 1,403,653→150 (−99.99%), those phases 5.76s→2.52s at
staging, projected 236s→~63–103s at full scale, for +45 MB measured
(~1.2 GB projected, ~5–6% of peak). No corpus observation moved. The
source-record sweep deliberately stays on the graph (failure ORDER is
observable). **Acceptance now projects to roughly 20 minutes** from the
75.7 measured at the program's start.

**FIDELITY BATCH 2 LANDED (ed4d5f9a) + THREE OWNER DECISIONS
(2026-08-13):** uncovered claims 140→**0** (source-claim-coverage
PASSES; 21,549 declared with per-predicate counts and Atlas-side zero
proofs); a new source-release-metadata check found a previously
invisible direction — Atlas asserting 18 dcterms:issued/identifier
claims no publisher made; the 889,115 differences classified: **97.68%
is one undeclared product scope** (publishers ship 40+ languages, Atlas
keeps English), **zero fabrication anywhere** (every difference is an
omission), 9,656 were an AUDITOR double-count (zthes:termNote is a
kind-marker already compared by reification-fidelity), and the real
builder findings are small and named (GEMET en-US 5,212 rows → 244 real
lost synonyms; ELSST 181 timestamps). **Decisions: (1) DECLARE
English-only** — scope stated normatively in the binding README and
machine-readably in the build receipt, auditor declaration spec'd for
the file's owner; **(2) CARRY English definitions + scope notes** —
measured at +1,885 quads / ~82 KB compressed because the wire, compact,
Parquet and search-view fields ALREADY EXIST (note: the famous 43,837 is
30,621 definitions + 8,233 scope notes + 4,983 history notes across ALL
languages; English is 1,884 claims, so the declaration must cover the
remaining 41,953, history notes included — **DONE 2026-08-13**: the
checked declaration at `language-scope-exclusions.json` itemises 871,823
excluded claims across 8 sources by language and predicate family
(eurovoc-4.24 445,531; gemet-4.2.3 233,407; elsst-r6 192,292;
eurovoc-domains 546; agrovoc 40; nalt 7; doe-osti and nasa 0), which
subsumes the 41,953); **(3) PURSUE move 2** on its
own merits (single-source generation, killing the producer-vs-contract
drift class), with Jena required only at full scale. Coverage 24→27/110
(+42,651 records) with a systematic sourceDigest mismatch found across
all three new sources — a real builder finding.

## Verification-gap proposals — validated verdicts (v3.8, 2026-08-12)

Adversarial opus validation of the six P-proposals; full report in session.
**P1 GO** (fidelity auditor RUNS on the 3.1 wire — proven differentially,
zero parse failures over 1.07M quads; port cost = 1 stale default line;
plus two real gaps: rkaf-namespace blind spot ~24k false-uncovered claims,
and no SourceSpec owns the FR release; needs an --only scope flag).
**P2 GO-REPRICED** (the convention is true for 1 of 80 modules;
`declaredMemberCount` is a self-count masquerading as a publisher
declaration — the honest rename rides the next wire rebuild; the
per-module campaign is weeks and waits on a spec'd "publisher declares
nothing" disposition). **P3 GO, stronger** (negative-space statements
exist but are stale/wrong: ATLAS_US_EU says 11 gates where there are 13 —
the drift class REF-026 declared dead, alive in mandated prose; seal-design's
schema section still documents seal-1/4-field). **P4 NO-GO upstream /
RESHAPED in-binding** (the table is 100% rkaf vocabulary but 6-of-1,800
is Atlas policy; upstream's generator refuses shapes as sources; the fix
is promoting the existing shapes-parsed branch table to BE the table,
deleting EVIDENCE_WARRANTS as a copy, resolving attestorKind toward
SHACL — verified 1/6 not 2/6, zero verdict changes). **P5a NO-GO new
target / GO arm-the-existing-job**, gated on the FATAL determinism
finding: the Makefile and release-workflow build invocations run
different rdflib (7.6 vs 7.5) and recipeDigest hashes observed library
versions + python patch + unidata — same tree, different entry point,
different manifest digest (proven by digest reconstruction of both real
artifacts). Fix: one invocation, .python-version, delete the runtime
block from the recipe digest (uv.lock already pins declaratively).
**P5b GO-RETARGETED** (C1-C3 + meta-test are ceremony ≈ −700 lines; C4's
exception map, C5-C7's receipt correlation, and C9 — sole producer of the
45 REFSPEC_*_PATH vars 31 test files consume — are load-bearing and
STAY). **P6 GO** (zero re-mints proven over 1.02M tagged literals — all
@en; one grammar line + mint guard + 7-file blast radius incl. one frozen
differential-suite invariant; refuse-never-coerce).
Misses adopted: corpus-case additions invalidate all on-disk
distributions (cluster all wire changes into ONE rebuild); the audit tier
has no running leg; `make generate` lacks the manifest-builder line; no
seal minted yet so all seal-facing wording is free.
**v3.9 — the pipeline frame (validator's third pass, self-corrected
against code; supersedes the wave plan above).** Three legs: (1)
publisher bytes → intermediate, proven by NOTHING (digests prove
identity of the capture, not completeness); (2) intermediate → atlas,
proven by the fidelity auditor at 23 of 110 units; (3) atlas → sealed,
proven by the 13 gates + verify_seal — DONE, stop investing. P1 and P2
consolidate: the auditor IS the capture-quality mechanism
(check_count_reconciliation is publisher-derived, both directions, from
bytes — verified at :5697-5723); P2-as-convention would rebuild it 53
times weaker. DROPPED: P2 convention, kill-7 (neither moves A→B; kill-7
stays scoped in REF-027 as deferred cleanup). Execution: Wave 0+A
(running — hygiene + docs + the stale auditor default) → Wave B (ONE
rebuild: delete recipeDigest / EVIDENCE_WARRANTS / declaredMemberCount,
langtag rule + corpus case, seal sentences naming legs 1-2 as exactly
what the signature does NOT cover) → Wave C (auditor minimum set: rkaf
namespace fix ~5 lines clearing 96% of the false-uncovered gap, --only
scope flag, a SourceSpec for federal-register-thesaurus-2025 — without
which the artifact of record is structurally unauditable) → run the
audit. THE SUCCESSOR PROJECT, named: fidelity coverage 23 → 110 units —
leg 2 is 21% verified and that number, not the seal, is now the
product's weakest true claim.

## Wire-wave decisions (v3.7 — fable+opus advisory consensus, unanimous, 2026-08-12)

1. **Parquet is lossless per logical record: all five warrant fields become
   columns** (4 axes + nullable based_on_attestation; correction: evidence_role
   was already carried; based_on_attestation is fixture-only today but omitting
   it prices REF-016's chain link as a future 3.2 bump). Measured cost on the
   real 560k-row table: **+99 KB / +0.12%** (pessimistic +1.5%). Named
   consumers: the whole-record parity check (a projection comparison is
   structurally blind to the exact bug class that produced the warrant
   defect) and the `logicalRecordsPreserved: True` manifest claim, which is
   FALSE today (third instance of the sealed-false-claim class) and becomes
   true. `native_payload` pins as the RDF literal's exact lexical bytes
   (canonical_native_json_bytes; code-point key ordering, not JCS; SAFE_INTEGER
   bounds; no trailing newline) so parity is two byte comparisons; the
   duplicate encoder at `parquet_view.py:326` is deleted (kill-10). The
   full-view schema bump (1.0→2.0) rides the same 3.1 gate. Kill-2
   consequence adopted: once the contentDigest triple leaves the RDF, the
   validator RECOMPUTES node digests to check the retained column — the
   column never becomes comparand-less.
2. **The ordering unfreeze is REJECTED; frozen first-issue is permanent.**
   Collect-all would rewrite 539 NoReturn sites to buy a weaker partial-order
   pin; measured lifetime cost of the freeze is 29 line-edits; the
   alternates-array form is refused outright (monotonic loosening).
   Reframing: `firstIssue` is a golden observation, not a consumer promise —
   stated in the 3.1 README (which also drops "MUST fail closed in this
   order" as external contract); authors reorder freely and re-record the
   observation in the same reviewed commit. STRENGTHENING adopted instead:
   per-case `shaclComponents` arrays in corpus.json, asserted in both
   validation modes at release tier — closes findings item (a), delivers
   kill-5's engine-parity corpus as data, and converts the 46 vacuous
   `shacl.data` pins into real ones. (The in-flight test-based parity gate
   serves until the 3.1 corpus schema lands.) This supersedes kill-8's
   "error ordering unfreezes" clause.
3. **3.1 replaces 3.0 atomically** (precedent 5c6d889a: "git history is the
   archive"; no external consumer of the distribution format exists;
   SpicySearch is insulated by the search view's own 1.1 pin). Conditions:
   the fixtures un-commit lands FIRST (else the bump is an 8,340-file
   diff); 3.1 is staged on the FR Thesaurus artifact before the ~1h full
   build; the two IRI-bearing digests the search view derives identity from
   (evidence content digest, assertion_identity_digest) survive the cut —
   verified in implementation or the atomic story acquires a second repo.
   **Deliberate re-ordering of the plan's own steps, recorded:** wire cuts
   → fresh 3.1 build → THAT is the first sealed artifact → reader cutover.
   Sealing a 3.0 build first would mint the format's only external consumer
   the moment before deleting the format.

## Open items

- [x] Per-phase table landed (see Measured evidence): 78% SHACL, 21% parse,
      integrity phases negligible; kill-5 resolved KEEP; no distribution on
      disk validates at HEAD.
- [x] REF-026 in `docs/decisions.md`: four verbs, seal design, kill-list (landed cce6f0ce; 4 references in the ledger — verified 2026-08-13)
      with engineering grounds, budget rule, and the rulespec boundary
      collapse. OWNER DECISION 2026-08-11: drafted AFTER the warrant-model
      decision so the entry records it; the SpicySearch seam stays open
      until then, knowingly.
- [x] **Key custody DECIDED (owner, 2026-08-11): offline SSH key** per
      docs/seal-design.md §2 (ed25519, `ssh-keygen -Y`, allowed_signers
      with expiry, public key pinned in this repo + SpicySearch; Sigstore
      remains the documented upgrade path). The release workflow's seal
      step arms when the operator runs the doc's key ceremony and sets
      `ATLAS_SEAL_PRIVATE_KEY` + `ATLAS_SEAL_SIGNER_IDENTITY` secrets.
      **CEREMONY DEFERRED (owner decision, relayed via the reconciliation
      session 2026-08-12): the first full seal waits; the bounded
      ephemeral-key round-trip (seal-2 over the FR artifact, cb10a8e8)
      stands as the mechanism proof. Nothing seal-shaped blocks on this —
      the workflow stub, the format, and verify_seal are done; minting is
      a decision away, whenever taken.**
- [x] **Rulespec boundary DECIDED (owner, 2026-08-11): package-only
      (move 1)** — no monorepo; rulespec ships as a versioned package,
      RefSpec consumes via uv, checkout gate + currency tests + lattice
      copies delete on cutover. Move 3 is answered; move 2 proceeds as
      rulespec-side work.
- [x] Fresh full build under HEAD's binding EXISTS
      (`output/atlas-3.0-full-2026-08-11`, 32M quads, producer validation
      "passed") — but see next item.
- [x] [RESOLVED a64eee58 — option a1 landed, and the first seal has since been minted] **BLOCKER for the first seal — warrant-model decision (semantic,
      owner's call).** The fresh build violates HEAD's
      `atlas:EvidenceBindingShape` warrant `sh:xone` exactly as 08-10 did:
      bindings with `epistemicBasis=editorialAssertion`,
      `evidenceRole=formalAdoptionEvent`, `assertionOrigin=imported`, and
      no `rkaf:basedOnAttestation` match no sanctioned branch. HEAD's
      builder emits what HEAD's shapes reject while the producer's
      compiled proof passes — a live instance of the producer-vs-shapes
      drift class that boundary-collapse move 2 kills. Fix is either the
      builder's warrant emission or an amended sanctioned-branch table;
      that is a semantic decision on the in-flight evidence-model change,
      not an orchestration call. OWNER DECISION 2026-08-11: diagnose
      first — a read-only branch-match matrix (under- vs over-match per
      binding, each fix priced with blast radius incl. required negative
      corpus cases) is being produced as the decision packet.
- [x] Red-path fail-fast + smoke tier LANDED (2026-08-11): focused
      re-validation via pySHACL focus_nodes+use_shapes (unmodified shapes,
      full data graph, named focus nodes only); cross-mode equivalence 0
      mismatches over all 115 invalid corpus cases; audit mode preserved
      via REFSPEC_ATLAS_VALIDATION_MODE=audit. Measured at real scale:
      `--smoke` = 92s wall on the 32M-quad build (8/126 packs,
      kind-covering sample — found the warrant defect); fail-fast SHACL
      67.7s vs audit 173.1s at 1.09M-quad sample scale. Round-2 review
      APPROVED all three W3 deltas; its residue, closed 2026-08-11: the
      red-path focus selection is now canonicalized (lexicographic-min
      node per constraint/signature — the kill-5 report-determinism rule),
      the shapes-file target-form invariant is documented at
      `_root_shape_focus_groups`, and the fail-fast rejection message
      names the audit env var. **Accepted risk, recorded:** in default
      mode the fast path is the sole arbiter of a rejection (previously
      the whole-graph engine always re-arbitrated); mitigations are the
      pinned fast-path/normative equivalence test, the 46-case cross-mode
      component-list proof (0 mismatches), and audit mode. Still
      unmeasured: red-path wall time at full 32M-quad scale (needs a
      deliberate defect injection or the next real red build) — folded
      into the phase-table completion item.
- [x] Stale `ATLAS_V3_AUDIT_ROOT` default retired (W1-A: no default;
      fail-fast with explanation when unset).
- [x] Budget gate re-spec IMPLEMENTED (cd769d44 + follow-up): warn >60s,
      hard FAIL 240s runaway guard; 120s re-arms when the suite is next
      measured under 60s.
- [REGISTER — not a task; entries carry their own status] **Findings register (v3.6, owner-visible):**
      (a) The 46-case cross-mode SHACL parity breadth is UNPROTECTED — the
      committed test covers 6 mechanism cases; kill-5's protocol needs the
      full shacl.data set as the standing engine-parity corpus. Fix: a
      corpus-wide cross-mode component-list test, tiered OUTSIDE the dev
      budget (release-workflow/audit tier) — lands with builder wave 1.
      (b) Warrant-shape companions, deferred as separate decisions: four
      `rkaf:evidenceRole` sh:in values reachable by no branch (dead
      vocabulary); `attestorKind` pinned by 2/6 SHACL branches vs 6/6
      Python table rows (same drift class, smaller). Each fix needs its
      negative case per the corpus rule.
      (c) `_check_evidence_bindings`' "cites unknown evidence binding" is
      unreachable as a first issue (defensive depth behind sh:class) —
      candidate for deletion or documentation at the next validator pass.
      (d) Cross-repo copy: `SEARCH_VIEW_OMITTED_FIELDS` is byte-identical
      in spicysearch and refspec (kill-10 instance across repos) — fold
      into the package boundary or the SpicySearch REF-026 adoption.
      (e) rdflib 7.6→7.5 downgrade forced by rdfcanon==1.0.0's exact pin
      inside the rulespec wheel — relax upstream when rdfcanon permits;
      until then the pin is load-bearing.
      (f) The fixture factory mints the same falsified
      `shaclDataProof: compiledAgainstPinnedOntologyAndShapes` claim as
      the production builder — both framings die in the version-gated
      wire wave (builder wave 2 / 3.1 bump), fixture side rides the
      fixtures-reframe wave only if wire-invisible.
      (g) CROSS-REPO (stage-A finding, peer notified 2026-08-12): search
      view 1.1's `graphFactsPreserved: True` drops the five warrant
      fields without declaring them in `_OMITTED_FIELDS` — the sealed
      false-claim class one layer out. Fix (declare or carry) moves the
      search-view manifest → 1.2 bump → SpicySearch's exact-match
      admission pin. SpicySearch's decision; RefSpec side ready either
      way (full view 2.0 carries the columns).
      (h) WIRE DEFECT (oxigraph spike, measured 2026-08-12): 7,770 quads
      in 2 packs carry `sourceLocator` IRIs with raw `[`/`]` — RFC 3987
      violations rdflib and `ABSOLUTE_IRI_RE` both accept but every
      strict parser (oxigraph, Jena, most Java/Rust tooling) refuses.
      Interoperability bug in a distribution whose story is
      consumability. Builder-side fix (mint conformant IRIs) re-mints
      7,770 nodes; nothing 3.1 is published yet, so a pre-publication
      amendment is free by the plan's own no-consumer logic. DECIDED
      (owner, 2026-08-12): fix now, builder-side, in the pre-publication
      window — with strict-IRI refusal added to the canonical profile so
      the class cannot recur, and its negative corpus case per the rule.
      (i) WIRE DEFECT (same spike): the node-digest scheme is not
      invariant under RDF 1.1 term equality — `"x"` vs `"x"^^xsd:string`
      (2.27M vs 1.52M occurrences, pack-correlated by adapter) are the
      same term with different digests, and the canonical profile
      diverges from W3C canonical N-Triples (simple form mandated).
      Normalizing to the simple form fixes the digest scheme, aligns the
      profile with the standard, and is the precondition for any future
      strict-substrate round-trip. DECIDED (owner, 2026-08-12): normalize
      the wire to the SIMPLE form (W3C canonical N-Triples direction) in
      the same pre-publication amendment — builder mints plain literals,
      the canonical profile refuses explicit `^^xsd:string`, negative
      corpus case added. This is also the engine-parity precondition.
      (j) BANKED WIN (same spike, measured): the canonicality proof
      re-expressed on raw bytes = 49.07s full-scale vs ~287s in the
      parser subclass, zero rejections over 29.3M real lines, no new
      dependency — and it moves the enforcement to where kill-6 says it
      belongs. Implementation waits only on (h)/(i)'s resolution, since
      the byte grammar encodes the profile.
      **Oxigraph verdict (measured; REVISED from no-go to SEQUENCED
      after the spike falsified its own port-cost claim):** the shim
      rung stays dead (oxrdflib is 4.2× slower and silently rewrites
      literals — 99% of digests change, 89 spurious violations, never
      finishes at 61k+ quads; and those spurious violations are an
      RDFLIB term-identity artifact, not oxigraph's). But the "60–65%
      won't port" claim was WRONG: the sorted canonical packs ARE an
      index, so node digests (3,289,015 in 25.4s vs 131s+parse,
      104,898/104,898 parity), native-payload checks (590,561 in 19.2s),
      and canonicality (49.1s) all compute from raw bytes with no store
      and no term model — which also dissolves the literal-form blocker
      for digests. Revised sequence: (1) NOW, no decision needed —
      bucket-1 byte passes (~days, lands ≈33 min and decouples digests
      from any term model); (2) THEN the engine question stands alone:
      if Jena enters it REPLACES pySHACL (two engines = kill-10's
      duplication anti-pattern at engine level; dropping pySHACL frees
      rdflib from the acceptance path, making the oxigraph substrate
      real), priced with the dev-loop JVM cost (single-invocation /
      long-lived-process mitigations) and gated on wire normalization
      (h)/(i) FIRST — on today's dual-form wire the two engines can
      legitimately disagree and parity would diff a term-identity bug.
      Revised full ladder: ~12–13 min at 3–5 weeks (was 7–11). [The
      spike's dead-code claim about `_check_explorer_reachability` was
      FALSIFIED by the wire-hygiene wave: it is the live Parquet
      reachability comparand, called from
      `_check_parquet_view_against_graph` and pinned by test — retained.]
      **Wire-hygiene wave LANDED (2026-08-12): (h) fixed at mint (7,770
      IRIs percent-encoded at their two adapter sites; the class made
      unmintable by refusal in ntriples_term + identifier_validation;
      16,966 identities re-minted inside the two affected packs), (i)
      normalized (1,519,235 typed literals across exactly 3 mint sites →
      plain; emission guard refuses recurrence; evidence digests proven
      byte-identical), (j) byte grammar replacing the render-and-compare
      (27-class differential suite against a copied oracle — which
      caught one silent divergence, escaped-UCHAR-in-IRI; parse −17.6%
      at staging; parser stays lexical deliberately: rdflib
      normalization would move rdf:JSON/dateTime digests). Corpus 127 →
      129 (two rdf.canonical negatives). PROOF: pyoxigraph accepts the
      rebuilt packs' published bytes with zero refusals and no ETL.
      Deliberate residue: language-tag case not normalized (all 998,215
      tags are @en already; W3C canonical mandates lowercase; zero
      re-mints; unsanctioned — candidate follow-up).**
      **Jena spike COMPLETED (2026-08-12) — measured NO-GO today, door
      stays open, one flip condition promoted to blocker.** Parity PASSED
      (conforming + 4 injected defect classes + a SHACL-SPARQL shape,
      identical verdicts after canonicalization; the sh:closed and
      literal-identity suspects both tested clean). riot parses at
      800–900k quads/s (43×) and warns-not-refuses the bracket IRIs. BUT:
      full-scale Jena did not finish in 51 min against the 31 it would
      replace — cost concentrates in sh:class over 590k-instance extents
      (not memory, not parse; strong lead, cleanly isolating it was
      interrupted) — and the honest post-xone-lift staging ratio is only
      3.1×. Verdict: keep pySHACL; re-open only if sh:class scaling is
      resolved on a dedicated runner OR boundary-collapse move 2 commits
      to compiler-emitted SHACL-SPARQL — where Jena measured **~100×**
      (3.3s vs 332s for one shape at staging), making that commitment a
      PRE-COMMIT BLOCKER on move 2: emitting sh:sparql IS choosing Jena.
      Engine-neutral improvements to land regardless (queued behind the
      wire-hygiene wave; same validate.py region): derive violation
      components from the report graph's sh:sourceConstraintComponent
      instead of the regex over pySHACL's text rendering (a hidden engine
      coupling), and adopt the report-canonicalization rules (sort by
      focusNode/resultPath/component — never sourceShape, which Jena
      leaves anonymous; drop resultMessage; never digest a report graph).
      Integration notes preserved in the spike worktree
      (agent-a7937c98dc15549c2/jena-spike/, reproducible end-to-end):
      Jena exits 0 with violations (read sh:conforms), the assembled
      union view is not byte-stable (digest packs + pins, never the
      view), and an engine pin belongs inside bindingBundleDigest.
- [x] Reconciled 2026-08-13: there is NO duplication. One definition at
      `bindings/atlas/3.1/tools/validate.py:473`, carrying an explicit
      "nothing below restates it", read by the single accessor
      `evidence_warrant_axis_values()`. The ledger's note referred to
      ontology prose, not code; do not cite it as a code defect.
- [x] **Next campaign SCOPED (v3.6, 2026-08-12; full map in the session's
      scoping report).** Ranked by payoff÷risk, sequenced 1→4 because each
      shrinks the next: (1) **Fixtures reframed** — kill-8 as written is
      REJECTED: the corpus spans 31 first-issue codes not 115, the ≥46
      shacl.data cases ARE the engine-parity corpus kill-5 requires, and
      the "small helper" floors at ~1,000 lines. Instead: delete the
      one-line self-seal (`build_fixtures.py` hashes its own source into
      every receipt — the cause of 512-file diffs per edit), stop
      committing the 8,340-file/73 MB tree (corpus.json + receipt stay;
      `--check` proves reproducibility over 2 files), ordering-unfreeze
      only together with audit-mode collect-all. (2) **Builder waves 1–2**:
      the incremental/reuse subsystem is provably dead (zero incremental
      builds ever; the recipe cache key hashes 12 modules + its own source
      and always misses) → −3,450 lines incl. tests, kills the --repin tax;
      the "compiledProducerValidation proof" framing is FALSIFIED (passed
      while shapes rejected 2,003 bindings) → delete ~180 lines of false
      assurance; REF-019/020 supersessions required. (3) **Explorer**: the
      RDF explorer was already replaced by explorer.py (shipped CLI,
      rebound names); delete the RDF path whole → −5,100 lines, leaving a
      ~1,545-line explorer_render.py; REF-018/021 supersessions required.
      (4) **Wire cuts**: kill-3 is a serializer swap (compact records
      already derive from the in-memory graph; Parquet already carries
      content_digest columns), kill-2 rides behind it; needs
      bindings/atlas/3.1, 14 SHACL edits, REF-015 SUPERSESSION (a real
      reversal — compact-as-source-of-truth dies), and the parity check's
      comparand MUST stay in validate.py or it degenerates to tautology.
      Two evidence/derived digests are IRI-bearing and are NOT cut. Plan
      corrections found while scoping: the 11-vs-13 gate drift is fixed at
      HEAD, and the release workflow exists (ee89f513).

# Barebones reset — build, prove once, sign, serve

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
- Verified drift: `explorer_rdf.py:57` requires 11 acceptance gates,
  `validate.py:764` requires 13 (missing `explorer-reachability`,
  `machine-adjudication`). Eligibility lattice ×3 + currency test confirmed.
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
4. **The phase table is incomplete and should be finished on a conforming
   build.** Every phase after SHACL — node digests, projection, SKOS,
   adjudication, reasoning isolation — never ran; their costs remain
   estimates. After the fresh build, re-run the instrumented pass once to
   complete the split. Informational, not blocking: the wire-format kills
   stand on no-consumer grounds, not on cost.

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

## Open items

- [x] Per-phase table landed (see Measured evidence): 78% SHACL, 21% parse,
      integrity phases negligible; kill-5 resolved KEEP; no distribution on
      disk validates at HEAD.
- [ ] REF-026 in `docs/decisions.md`: four verbs, seal design, kill-list
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
- [x] **Rulespec boundary DECIDED (owner, 2026-08-11): package-only
      (move 1)** — no monorepo; rulespec ships as a versioned package,
      RefSpec consumes via uv, checkout gate + currency tests + lattice
      copies delete on cutover. Move 3 is answered; move 2 proceeds as
      rulespec-side work.
- [x] Fresh full build under HEAD's binding EXISTS
      (`output/atlas-3.0-full-2026-08-11`, 32M quads, producer validation
      "passed") — but see next item.
- [ ] **BLOCKER for the first seal — warrant-model decision (semantic,
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
- [ ] Budget gate re-spec (W2 finding: 112–140s straddles the 120s line —
      `make test` flipped red on an identical tree). Decision: warn >60s
      stays; hard FAIL moves to 240s as a runaway guard; the 120s FAIL arms
      only when the suite is measured under 60s after the deletion campaign
      shrinks it.
- [ ] Reconcile the ledger's five-axis "duplication in model.py" note with
      the code (one definition found; generator imports it).
- [ ] **Next candidates for the same treatment** (review: "too timid"):
      `tools/generate_atlas_v3_full.py` (10,644 lines — largest file in the
      repo) and `explorer_rdf.py` (~6,200 lines beyond its verify stack).

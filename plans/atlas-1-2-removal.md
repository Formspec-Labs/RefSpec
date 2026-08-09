# Remove Atlas 1.0 and 2.0

Delete the Atlas 1.0 and 2.0 producer code, then remove the 1.0/2.0 concepts
still embedded in modules shared with Atlas 3.0. Scope is this repository only.
Downstream consumers are out of scope for this plan and must not shape its
decisions.

Read `plans/refspec-on-rulespec.md` alongside this. The two are one sequence:
that plan decides *what replaces* each retired capability — rkaf contracts,
each landing with a validator and a negative fixture — while this one tracks
*what is removed and in what order*. Its governing rule applies throughout:

> A structure may be added or retained only if a running validator or a real
> consumer breaks when it is violated. If nothing breaks, it is prose: delete
> it or don't merge it.

Where this plan says "keep", read it as "keep until the enforcement that
replaces it is green", not as permanent preservation.

## Why now

Atlas 1.0 and 2.0 are already declared historical in `README.md`, and Atlas 3.0
is the only format new producers and consumers target. The legacy code was not
merely unused; it was failing. All 55 test failures on this branch sat in the
legacy publication and release tests, and they failed because the legacy
publication path calls the Atlas 3.0 explorer, which rejects the legacy model
(`Atlas3ExplorerError: Atlas 3.0 explorer distribution must be an object`,
raised at `src/refspec/atlas/explorer_rdf.py:5190`).

Outcome after Tier 1: the suite reports **2,993 passed, 44 skipped, zero
failures**.

Verified before writing this plan: `tools/generate_atlas_v3_full.py` imports
exactly one module from the atlas package, `refspec.atlas.registry_claim_input`.
No Atlas 3.0 entry point depends on any file in Tier 1.

## Tier 1 — the dead producer path

13 files, 14,263 lines. Deleting these removes every current test failure.

Delete:

| File | Lines |
| --- | ---: |
| `src/refspec/atlas/v1_release.py` | 3,348 |
| `src/refspec/atlas/publication.py` | 2,013 |
| `src/refspec/atlas/publication_decision.py` | 1,121 |
| `tools/build_vocabulary_atlas_v1.py` | 69 |
| `tools/prepare_vocabulary_atlas_v1_baseline_release.py` | 1,074 |
| `tools/prepare_vocabulary_atlas_v1_public_release.py` | 1,080 |
| `tools/build_elsst_atlas2_bench.py` | 650 |
| `tests/test_atlas_v1_release.py` | 1,587 |
| `tests/test_atlas_publication.py` | 1,490 |
| `tests/test_atlas_publication_decision.py` | 632 |
| `tests/test_prepare_vocabulary_atlas_v1_baseline_release.py` | 130 |
| `tests/test_prepare_vocabulary_atlas_v1_public_release.py` | 765 |
| `tests/test_atlas_release_acceptance.py` | 304 |

`tools/prepare_vocabulary_atlas_v1_qualification.py` (214 lines) is excluded
from this deletion: its library, `src/refspec/atlas/qualification_jobs.py` and
`src/refspec/atlas/qualification.py`, sits on the Tier 3 preserve-list, and the
capability must retire as a unit — port first, then retire, never the reverse.

Then repair the references that survive the deletion:

- `pyproject.toml:26` — drop the `refspec-publish-vocabulary-atlas` console
  script, which points at `refspec.atlas.publication:main`.
- `src/refspec/atlas/__init__.py` — remove the `from .publication import (...)`
  block at line 80 and the `from .publication_decision import (...)` block at
  line 87, plus their `__all__` entries near lines 286-298.

`release_acceptance.py` was an open question when this plan was written, and the
code settled it: the module imports from `publication_decision`, so it could not
survive that deletion. It was removed along with the public surface built on it
— the lazy `__getattr__`/`__dir__` loader in `src/refspec/__init__.py`, the
`__all__` entries in both packages, and the lazy-load test and its constant in
`tests/test_binding_package.py`.

Two further files went with it, bringing Tier 1 to 16 deleted rather than 13:
`src/refspec/atlas/explorer_acceptance.py` and
`tests/test_atlas_explorer_acceptance.py`.

Record the reason accurately, because the first one given was wrong.
`explorer_acceptance.py` did **not** import `publication_decision`; its imports
were `refspec.binding`, `refspec.immutable`,
`refspec.registry.infrastructure.*`, `.explorer`, `.model`, and `.queries`, all
of which survive, so it would still import cleanly today. The real grounds are:
nothing imported it; its only producer, `build_explorer_model`, lived in the
deleted `publication.py`, and its entry point consumes a legacy asset plus a
legacy explorer model that nothing can now produce; and its test was already
inert, carrying `pytest.mark.skip(reason="retired Atlas 1/2 explorer acceptance
suite")` at `tests/test_atlas_explorer_acceptance.py:31` while importing
`refspec.atlas.publication`. It was never among the 55 failures because it never
ran.

Two consequences follow from that deletion. Record them; do not reverse it.

- **Capability gap.** `bindings/atlas/3.0/tools/validate.py:507` defines
  `REQUIRED_GATES` with no explorer or search-reachability gate. The deleted
  module counted every advertised filter value, proved every assertion
  reachable through its endpoints and filters, and executed a reviewed search
  corpus. Atlas 3.0 has no equivalent. This is the same shape as the Tier 3
  preserve-list rule, and it was retired before it was ported.
- **Orphaned evidence.**
  `research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json` (type
  `VocabularyAtlasExplorerSearchCorpus`, committed `62ced6c`) is now readable by
  no code in the repository, and nothing references it by name. Keep it as
  evidence, and treat it as the input a ported Atlas 3.0 reachability gate
  should consume.

Verify: `uv run pytest -q` reports zero failures, and `make test` fails only if
something outside this scope regresses.

### Follow-ups surfaced during Tier 1

Measure these once Tier 1 has landed, rather than assuming them now:

- `portfolio/vocabulary-atlas-v1-production-qualification-jobs.json` is
  v1-named but still an active input, read by `tools/run_atlas_qualification.py`,
  `src/refspec/atlas/qualification_jobs.py`,
  `tests/test_atlas_v1_qualification_jobs.py`, and
  `tests/test_atlas_v1_qualification_spend.py`. It belongs under dated research
  evidence rather than `portfolio/`, but moving it means repointing those four
  first. This is coupled to the `qualification.py` entry in the Tier 3
  preserve-list; do them together.
- `queries.py`, `projection.py`, and `projection_cli.py` lose their legacy
  callers when Tier 1 lands. Re-run the importer check afterwards to see what
  actually remains rather than deleting on the strength of their names.
- `tests/test_federal_register_thesaurus_2025.py` and
  `tests/test_icpsr_managed_release.py` each mix legacy-snapshot cases with
  current behaviour. Trim only the old-snapshot portions; do not delete either
  file.

## Tier 2 — reversed: keep the bindings, strengthen the freeze

**Do not delete `bindings/atlas/1.0/` or `bindings/atlas/2.0/.`** The original
plan called for removing them. That was wrong, and the repository already says
so in a test.

`tests/test_versioned_atlas_bindings.py` exists for exactly this. Its module
docstring reads "Published Atlas binding versions remain available to pinned
consumers", and its single test is named
`test_atlas_1_0_remains_available_for_pinned_consumers` with the docstring
"Publishing a successor version must not delete the 1.0 surface." It asserts
the presence of the 1.0 `README.md`, both schemas, the worked example, and
every conformance fixture named in `fixtures/corpus.json`. Deleting the 1.0
binding does not merely break a test; it violates a commitment this repository
wrote down and gated.

Freeze both bindings for now, but not forever. `plans/refspec-on-rulespec.md`
sets the criterion that governs when they go: **an artifact may be deleted once
every capability it uniquely specifies is enforced elsewhere by a running
check, and the deletion commit names those checks.** Git history is the
archive. So the freeze below is the interim guard, and step 5 of that plan's
sequence retires it once the P0 adjudication and P1 temporal enforcement land.

The work in this tier is therefore additive:

- Extend `tests/test_versioned_atlas_bindings.py` to pin the Atlas 2.0 surface
  as well. It currently pins only 1.0, so the 2.0 `README.md` and its three
  schemas are unprotected.
- Keep `docs/atlas-publication.md` and `spec/managed-vocabulary-release.md`.
  `README.md:18-19` already labels both as historical, which is now the correct
  description rather than a deletion candidate.

A second argument was raised for preserving 1.0 — that the machine-proof
semantics behind `atlas:twoMachineAdjudication` are specified only in
`bindings/atlas/1.0/README.md`. Verified, and it is partly true rather than
wholly true:

| File | `twoMachineAdjudication` | narrative proof semantics |
| --- | ---: | ---: |
| `bindings/atlas/1.0/README.md` | 0 | 2 |
| `bindings/atlas/3.0/ontology/atlas.ttl` | 1 | 1 |
| `bindings/atlas/3.0/README.md` | 0 | 0 |

The term is carried by the 3.0 ontology (`atlas.ttl:252`), its shapes
(`atlas.shacl.ttl:852`), and the validator (`tools/validate.py:362`). What 3.0
lacks is the prose that says what the proof *means* — independent machines,
sealed identical requests, distinct providers, the verdict lattice, and
complete support closure. The 1.0 README carries the fullest statement of it
and the 3.0 README carries none. So migrating those semantics into the 3.0
binding is worthwhile work in its own right, but the binding freeze does not
depend on it.

Verify: `uv run pytest -q tests/test_versioned_atlas_bindings.py` passes and
covers both versions.

## Tier 3 — untangle the shared modules

This is a refactor, not a deletion, and it is the only tier with real unknowns.

These modules serve both generations and cannot simply be removed:
`model.py`, `projection.py`, `queries.py`, `federal_register.py`, and the
`explorer*.py` family. The dependency is not one-directional — the legacy
publication path calls `render_atlas_v3_explorer`, so Atlas 3.0 code is reached
*through* legacy code today.

The atlas package holds 53 modules. A dependency closure seeded from the known
Atlas 3.0 entry points reached only 9 of them, which means the wiring is partly
registry-driven or dynamic and a static import graph will not settle the
boundary on its own. Establishing that boundary is the first task, not an
assumption to carry in.

### Preserve-list

These modules look retirable by name and are not. Each carries a capability
Atlas 3.0 has not absorbed yet, so removing it deletes the only implementation.
Port first, then retire — never the reverse.

| Module | Why it must stay |
| --- | --- |
| `machine_evidence.py`, `relation_proof.py` | Proof closure. Keep until Atlas 3.0 has proof-closure validation and negative fixtures. |
| `relation_sssom.py` | `bindings/atlas/3.0/README.md:641-649` promises an SSSOM view, but the exporter accepts only legacy `RelationAssertionBundle`. Port it onto v3 mapping packs first. |
| `frontier.py`, `concept_release.py` | `source_concept_release.py:409-512` still supports `policyFrontier`, with a lazy import at `:466`. Decide the frontier's future explicitly rather than by deletion. |
| `qualification.py` | Its deterministic six-class candidate generator backs five research benchmarks. Fold it into `candidate_retrieval.py` first. |
| `atlas_index.py` and its JSON | Still required by `generate_atlas_v3_full.py:2487-2635`, `generate_atlas_v3_registry_descriptors.py:171-398`, and `generate_atlas_v3_registry_coverage.py:17-20`. Replace with the validated v3 release inventory before removal. |
| `model.py` (ring temporal context) | Atlas 2.0's ring-specific temporal fields — `sourceEdition`, `targetEdition`, and effective dates for value mappings, `effectiveAt` for legal identity (`semantic_foundation.py:278`) — have no v3 equivalent. Do not retire the model carrying them until v3 identity, SHACL, and pack forms grow those fields. |

### Ports owed to Atlas 3.0

Distinct from the preserve-list: these are capabilities the retired generations
had and Atlas 3.0 does not. The first was already retired before it was ported,
which is the mistake this list exists to stop repeating.

1. **Explorer and search reachability gate.** `REQUIRED_GATES` at
   `bindings/atlas/3.0/tools/validate.py:507` has no equivalent of what
   `explorer_acceptance.py` enforced. Its reviewed corpus survives at
   `research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json` and
   should be the port's input.
2. **Machine-proof semantics.** `atlas:twoMachineAdjudication` is carried by the
   3.0 ontology, shapes, and validator, but what the proof *means* — independent
   machines, sealed identical requests, distinct providers, the verdict lattice,
   complete support closure — is written down only in
   `bindings/atlas/1.0/README.md` (see `:91`, `:184`). Per
   `plans/refspec-on-rulespec.md` this should land as an rkaf `attestation.cue`
   shape with a `validate.py` closure check and a negative fixture per
   condition, not as a transcription of the v1 prose.

   **Do not delete the 1.0 binding before that check is green.** It was
   suggested that the protocol is already specified in rulespec's
   `spec/rkaf-refspec.md`, which would make the v1 README redundant. That is
   true of the current rulespec, and false of anything RefSpec can see.

   Resolved account. The rule does exist upstream, added in rulespec commit
   `939b93c` on 2026-08-02. RefSpec's tracked pin,
   `profiles/rulespec-dependency.json`, sits at `contractRevision`
   `0eb94257b70783688b55220e7a84dcc61bbd7507` from 2026-07-29 — an ancestor of
   that commit, so the pin predates the rule by four days. The materialized
   copy at `output/rulespec-pinned/spec/rkaf-refspec.md` correspondingly does
   not contain it: 142 lines, §1 "Purpose and ownership", no occurrence of
   adjudication, attestor, two-machine, verdict, independence group, or
   provider. Until RefSpec re-pins, the only in-repo carrier of this protocol
   is `bindings/atlas/1.0/README.md:91,184` — which is also where rulespec
   took it from.

   **The pin gap is the real finding, and it gates this work.** Verified here:
   `pinTextFiles` covers exactly `spec/refspec.md`,
   `profiles/rulespec-application-profile.md`, and
   `plans/implementation-plan.md`. It does **not** cover `spec/rkaf-refspec.md`
   or `spec/rkaf-core.md`, the two files the rkaf adoption depends on, and
   `output/` is gitignored. Those specs are therefore materialized but
   digest-covered by nothing, so upstream drift in them is invisible to any
   check — which fails this plan's own rule that structure must be enforced by
   something that breaks. Re-pinning at or past `939b93c` is step 0 of
   `plans/refspec-on-rulespec.md`. No adoption step may cite unpinned rulespec
   text. Verify protocol content on re-pin, not the line anchors above, which
   will move.

   **Three corrections to how step 0 should be built.** It proposes extending
   "the tracked pin (`pinTextFiles` or digest coverage) to the two spec files".
   Measured against the code, that mechanism does not do what the step needs:

   - `pinTextFiles` does not pin upstream text. All three entries —
     `spec/refspec.md`, `profiles/rulespec-application-profile.md`,
     `plans/implementation-plan.md` — are **RefSpec-side** files, and none
     exists under `output/rulespec-pinned/`. The gate resolves them against
     `REFSPEC_ROOT` and checks that RefSpec's own documents do not quote a
     stale rulespec version. Adding `spec/rkaf-refspec.md` would gate the wrong
     thing, against a path RefSpec does not have.
   - `output/rulespec-pinned/` is wired to nothing. Searching `src/`, `tools/`,
     `tests/`, and the `Makefile` for `rulespec-pinned` returns no hits. The
     materialized copy the adoption depends on is produced outside the
     repository and consumed by no check inside it.
   - The closure-pin gate never sees a real checkout.
     `validate_closure_pin(rulespec_dir, ...)` at
     `bindings/json/1.0/tools/validate_rulespec_gate.py:219` is genuine — it
     shells git into `rulespec_dir` for contract and corpus digests. But its
     only caller is `tests/test_rulespec_dependency_gate.py`, whose
     `rulespec_dir` fixture at `:35-47` fabricates a `tmp_path` tree of
     `"test input\n"` files. The gate is exercised only against synthetic
     inputs and has never compared RefSpec's pin against real rulespec. That is
     why a pin four days stale went unnoticed.

   This is the third gate in this repository disabled by a missing input, after
   `REFSPEC_CHECKOUT` and `REFSPEC_REGISTRY_CLAIM_REAL_DATA`. Step 0 needs a
   digest manifest over the materialized files and a check that runs against a
   real checkout — not an addition to `pinTextFiles`.

Suggested order:

1. Delete Tier 1 first. Several shared modules may fall out of use entirely once
   their only remaining callers are gone; measure again after Tier 1 lands
   rather than reasoning about the graph as it stands now.
2. For each surviving module, find the Atlas 1.0/2.0 concepts by grepping for
   `nquads-1.0`, `atlas-2.0`, and `refspec-vocabulary-atlas`. Known carriers:
   `src/refspec/atlas/projection.py` and `src/refspec/atlas/model.py`.
3. Remove one module's legacy concepts at a time, with the suite green between
   each. Do not batch these.

Do not begin Tier 3 until Tiers 1 and 2 are committed and the suite is green,
because a green baseline is the only way to attribute a new failure to the
refactor.

## Verification

Run after each tier, not only at the end:

```sh
make check-generated
make audit-registry-inventory
make test-json-binding
make test-atlas-v3
uv run pytest -q
uv run ruff check src tools tests
```

Baseline before this plan: 55 failures, all in the Tier 1 tests. Tier 1 should
reach zero. Tiers 2 and 3 must not introduce any.

Regenerate derived artifacts with `make generate` if any deletion changes a
digest input, and commit the regenerated chain with the change that caused it.

## Rollback

Each tier is one commit. Nothing here is published, so `git revert` on a tier
commit restores that tier completely.

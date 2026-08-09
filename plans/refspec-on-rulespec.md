# Proposal: RefSpec relies on RuleSpec directly

Date: 2026-08-09. Status: proposed, user-directed. Supersedes the
compatibility-view boundary in `docs/decisions.md` ("Atlas does not claim
Rulespec conformance until that exact compatibility view exists and
validates") and the dual-ontology architecture it implies.

## Decision

RefSpec adopts RuleSpec's rkaf contracts as its record shapes wherever both
describe the same idea. No compatibility view. No parallel `atlas:` terms for
rkaf-covered semantics. The `atlas:` namespace remains only for Atlas's actual
domain: releases, packs, digests, semantic rings, resource profiles.

The dependency is one-way — RefSpec → RuleSpec, pinned. The mechanism already
exists: `output/rulespec-pinned/` plus the verbatim-transcription-with-commit-pin
pattern used by `spicy_regs/ontology/attestations.py`.

rkaf is itself AI-authored and over-general. Adopt the smallest subset that a
running validator needs; a contract enters RefSpec only attached to a validator
and a negative fixture.

## The rule

A structure — term, spec section, layer, boundary — may be added or retained
only if a running validator or a real consumer breaks when it is violated.
If nothing breaks, it is prose: delete it or don't merge it.

Deletion criterion for legacy artifacts: an artifact may be deleted once every
capability it uniquely specifies is enforced elsewhere by a running check. The
deletion commit names those checks.

## Adoption map

| Gap / current shape | rkaf contract | Enforcement that must land with it |
| --- | --- | --- |
| P0 adjudication: `atlas:reviewMethod=twoMachineAdjudication` bare enum; `machine_evidence.py` | `attestation.cue` + the two-validator protocol at rulespec `939b93c` (`spec/rkaf-refspec.md:36-41`, landed 2026-08-02). **Not** in RefSpec's pinned copy — `contractRevision` `0eb9425` (2026-07-29) predates it; the in-repo carrier of this language remains `bindings/atlas/1.0/README.md:91,184` until step 0 re-pins. Sealed request digests via `evidence-binding.cue` | `validate.py` closure: ≥2 effective `rkaf:aiModel` attestations, distinct providers and model IDs, equal sealed-input digests, complete support closure — with negative fixtures for each condition |
| P1 temporal context (missing in v3) | `effective-period.cue` on value/legal assertions | SHACL + `validate.py` reject value/legal mappings lacking edition + effective context |
| P1 rights/scope (loose JSON) | `usage-eligibility.cue` + `access-scope.cue` | schema-validated closed enums; invalid fixture |
| Lost no-silent-collapse rule | `registry-conflict.cue` | build fails when contradictory claims collapse without a conflict record |
| Lost refusal-inspection gates | `finding.cue` | refusal fixtures in v3 acceptance tests |
| `atlas:confidence` bare literal | `confidence-record.cue` | typed record, or delete the field |
| Ad-hoc `engine`/`engineVersion`/`reviewedBy`/`reviewMethod` | `ai-lineage.cue` + rkaf-core §2.4 provenance roles | pinned-transcription check |
| Mapping export | SSSOM (public standard; rkaf already positions it as the derived view) | round-trip fixture on a v3 mapping pack |

Not adopted, because no validator needs them yet: workspaces, warrants (unless
P0 closure validation demands a distinct node type), `bridge-*` contracts
(until a second real consumer exists), retention-policy (until retention runs
anywhere). This list grows only when a validator demands it.

## Sequence

0. Re-pin rulespec at or past `939b93c` and gate the spec text this plan
   relies on. Corrected mechanism (measured in `plans/atlas-1-2-removal.md`,
   commit `e9c171d` — the original `pinTextFiles` idea cannot work:
   `pinTextFiles` pins RefSpec-side documents, `output/rulespec-pinned/` is
   consumed by no check, and the closure-pin gate only ever runs against
   synthetic fixtures, which is why a four-day-stale pin went unnoticed):
   a digest manifest over the materialized spec files (`spec/rkaf-core.md`,
   `spec/rkaf-refspec.md`) plus a check that runs against a real rulespec
   checkout. No adoption step may cite unpinned rulespec text.
   (Tier 1 of `plans/atlas-1-2-removal.md` is committed; suite green.)
1. P0 adjudication per the map. When its negative fixtures are green,
   `machine_evidence.py` and `relation_proof.py` become deletable.
2. P1 temporal context. Then the v2 temporal model becomes deletable.
3. P1 rights/scope.
4. Opportunistic, one module at a time with the suite green between each:
   conflict, finding, confidence, lineage.
5. Delete `bindings/atlas/1.0/` and `2.0/` and the remaining legacy modules
   once steps 1–2 are enforced. This revises the earlier "keep as frozen
   evidence" guidance: git history is the archive; the deletion commit cites
   the enforcing checks that superseded each binding's unique content.
6. Ledger entry superseding the compatibility-view decision; AGENTS.md
   addition below.

## AGENTS.md addition (applied 2026-08-09)

Applied directly by the proposing session on user direction, ahead of the
step-6 slot, so the rule governs steps 0–5 rather than arriving after them.
Left uncommitted; committing is the user's call.

> Structure must earn its keep. Add a term, spec section, layer, or boundary
> only together with the validator or consumer that breaks when it is
> violated, including a negative fixture. Prefer deleting structure to
> documenting it. RefSpec depends on RuleSpec (rkaf) directly: never mint a
> parallel term for a concept rkaf already defines, and never add a
> compatibility layer between components with a single owner.

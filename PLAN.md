# RefSpec plan

**Read first:** [AGENTS.md](AGENTS.md) for working doctrine, the
[decision ledger](docs/decisions.md) for why anything is the way it is.
Longer-running plan detail is in [plans/](plans/) — start with
[validation-cost-reset-plan.md](plans/validation-cost-reset-plan.md) and read
its CONTINUATION header.

## Atlas refresh (2026-09-27, fixed 2026-09-28)

`lane/atlas-refresh-fixed` carries the refresh as reviewed, rewritten commits
over dev22 (`2b30e432`): the per-language preferred-label shape,
source-fidelity verifier 16 (independent payload, transformation, PDF and
agency comparisons), bounded accounting and sorting, the phase guard and one
qualification target shared with the release job, served-byte checks for
explorer candidates, and the audit refactor. The slow tier builds everything
it reads (`make build-derived`) from pinned inputs, including the agency
review's 20 primary sources. It merged as `380308ee` and ships in dev23
(below).

Release stays blocked: no candidate has completed qualification (the
standalone audit stops at its 30 GiB guard), and `make
stage-atlas-mapping-topology` exits 2 on `main` and on the branch. See the
[refresh record](research/atlas-refresh-2026-09-27/README.md) for findings,
measurements, retained evidence, known costs and these blockers, and the
[repair proposal](plans/atlas-refresh-repair-plan-2026-09-27.md) for the
acceptance criteria. Nothing was published; the August artifact is intact.

## State as of 2026-09-17 (historical)

Branch `main`, tree clean, at `0.1.0.dev11` pinning the vendored SpicyDocs
0.20.0 wheel. dev8→dev11 (2026-09-14→16) completed the shared-reader
adoption: U.S. Code/USLM (`1bc39535`, `1ffeb5ba`), Unified Agenda
(`5d71a26c`), CFR metadata (`cf0f3e7b`), GovInfo/PREMIS (`6cf579bf`),
publisher tables (`7f0d5614`), PDF/XML sharing (`4fe282c1`, `bd045e8f`),
BILLSTATUS publication through shared storage (`2c84fe0b`), and archive
readers for acquisition and builds (`daa59e25`, re-pinned `d4a22979`).
Unified Agenda rebuild #16 (`fd22acdf`) ran on those readers with every delta
attributed shape-by-shape in the updated pins. The 2026-09-07 gate note is
superseded; run `make test` rather than trusting either line.

**Pushes need the owner's own words.** On 2026-09-17, on Mike's words, `main`
(dev11 and rebuild #16) was pushed to origin. Until the next such instruction,
commits sit unpushed deliberately — do not push them because they are here;
ask. For the count, ask git
rather than this file — `git rev-list --count origin/main..HEAD` — because a
number written here goes stale on the next commit, including the commit that
updates this line.

## SpicyDocs 0.31.0 repin (in progress, 2026-09-24)

Step 1, on `wt/repin-0.31.0`: the pin (dev15), B14 (the Zyte transport from
`spicy_docs.sources.zyte`) and B21 (readers SpicyDocs already ships, adopted
only where agreement was measured). Step 2 needs the Unified Agenda rebuild:
import the grammar, shapes and minters from SpicyDocs, keeping RefSpec's
modules as test oracles; three expectations move and seven Unified Agenda
count pins re-adjudicate. Sequence and measurements: SpicyDocs
`docs/research/consolidation-path-2026-09-22.md`, rows B14 and B21.

The pin moved to SpicyDocs 0.36.0 (dev16), 0.39.2 (dev17), 0.42.0 (dev18),
0.44.0 (dev20), 0.46.0 (dev21) and 0.50.0 (dev22, 2026-09-28), which changes
nothing RefSpec imports or reads (vendor/README.md); SpicyRegs pins 0.50.0 too,
and a consumer still on 0.46.0 (DocSpec, SpicySearch, Engine) and RefSpec do
not resolve one SpicyDocs until that consumer moves. Step 2's
moves were measured against 0.31.0, and `identifier_shapes`, `citation_grammar`
and `iri_minting` changed since, so they need measuring again before the switch.

REF-024 amended 2026-09-24 (the minters live in SpicyDocs): step 2 also adds a test holding `_FR_COLLISION_TABLE`'s verdicts equal to SpicyDocs' `_FR_COLLISION_VERDICTS` and points `test_the_minted_spaces_are_the_contract_verbatim` at SpicyDocs' `IDENTIFIER_SPACES`.

Not switched in step 1, each with why (B21 moved only the PDF page reads):

- eCFR titles: real bytes agree 50/50, but SpicyDocs' `parse_ecfr_titles` accepts three of the four mutations RefSpec refuses (extra top-level field, reserved title with dates, active title without); waits for SpicyDocs to take those refusals and a new wheel.
- CBO feed: 1,058/1,058 items agree, but the refusals are disjoint (RefSpec alone refuses reordered children, an empty description, a missing bill number; SpicyDocs alone a duplicate item and a key off its position); waits for SpicyDocs to refuse the union.
- Source-domain parsers: `xsd_documented_options` refuses 2 of the 20 Unified Agenda lists RefSpec reads (RFA_REQUIRED, TTBL_ACTION), and `openapi_schema_enum` agrees on the 3 real enums but differs on all 5 mutations tried (it accepts a blank member); waits for SpicyDocs.
- HTML and XML: the registry's `HTMLParser` subclasses and `ElementTree` parses call the stdlib parsers SpicyDocs wraps; `read_html_events` and `parse_xml` return events and trees of another shape, so each is a parser port with its own oracle and mutation battery, not a re-point.
- PDF: the Federal Register thesaurus (positioned, font-tagged text) and the NRC APS guides (document-information dates) need pypdf features the shared reader does not expose; `tools/verify_atlas_source_fidelity.py` keeps its own reads as the independent verifier.
- Unified Agenda projection: collapses whitespace where RefSpec strips (4,748 records differ, scout 2026-09-24); waits for the step-2 rebuild.
- OLRC Table III and popular names: independent parsers (B15), switched at the step-2 rebuild; SpicyDocs 0.40.0 removed `iter_table3_chain` and reads an act's absence from the bulk file (`read_table3_bulk_archive`).

## REF-038 reverse lookup (dev19, 2026-09-26)

`reverse_agency_projection()` reads the agency projection backwards for
spicy-regs decision 56, under an amendment to REF-038: an organization resolves
only where one code selects it. 311 of the 321 codes reverse; five
organizations are ambiguous, two codes each. It asserts nothing, so no Atlas
build or view changes; nothing is open here.

## RefSpec 0.1.0.dev21 (2026-09-27)

dev21 carries agency registry batch 1 (REF-072): the owner's 26 decisions as
the `agency-registry-2026-09-26` release (13 bridges, 9 change events, 4
recorded non-emissions), its own sealed view and `current_agency_successors()`;
`build_agency_projection()` still reads REF-038 alone. With it: the slow tier
compares the whole-graph ledger after its writer stamps it (`19b348be`); the
Federal Register thesaurus pins, re-recorded and verified by `make test-package`
(`4108e8b8`); a suite that ignores an inherited git repository, and a fixture
case tree rebuilt whenever it is not the receipt's; SpicyDocs 0.46.0. Open:
batch 2 (register-only agencies) and the later succession batch, which as built
cannot be an events-only release ([design, section 7](plans/agency-registry-design.md)).

## RefSpec 0.1.0.dev22 (2026-09-28)

dev22 carries the owner's contract-digest decision (REF-073): the atlas
index's digest covers placement, not the bytes of the modules and tests it
cites (those have their own `evidenceDigest`), so a registry code edit no
longer moves the Atlas contract or the Federal Register thesaurus pins; the
pins moved once for the change and were re-recorded. With it: SpicyDocs
0.50.0, which changes nothing RefSpec imports or reads. The slow and
full-Atlas tiers are left to the operator on this commit, the slow tier now
including the end-to-end pin test REF-073 adds.

## RefSpec 0.1.0.dev23 (2026-09-29)

dev23 carries the three branches merged since dev22. The atlas-refresh fix
round (`380308ee`, above): source-fidelity verifier 16 with the S27
relation-record provenance check, bounded accounting, one qualification
budget that writes its receipts when the budget ends or a signal arrives,
evidence pruned to what the checks read, and the 20 primary agency sources
pinned; the contract pair moved to `5344028b...`/`c792a2f9...` for the
preferred-label shapes and the new conformance cases. The registry
follow-ups F1-F7 (`cd78e476`): same-entity closure through `sameEntityAs`
chains, change-event negatives with a fail-fast fallback, an agency registry
view that states its release's evidence and a verifier that compares the two
both ways, the parent map derived once per roster, and `original_parents` in
view schema 1.1 (manifest `c7dc9310...`); the pair moved to
`1c14dc75...`/`e6c5d30b...`. The bounded red-path SHACL fallback
(`ef6fc361`): one engine run on `sh:targetNode`-retargeted shapes replaces
the whole-graph fallback, which stays as the test oracle (the agency red
path went from 255 s to 34 s in the merge review), the fast tier loads LCSH
once, and REF-072 records the pass decision, its risk and the audit-mode
bound. The version bump moves neither the contract pair nor the view
manifest. SpicyDocs stays 0.50.0; the next re-vendor takes 0.53.0 with the
rest of the stack. The slow tier passed on this source tree (`dcd24ce2`);
the owner skipped the full-Atlas tier.

## Merged, and the one parked item

The Unified Agenda receipt rebuild (move five of the SpicySearch v14 batch)
is merged: the artifact was rebuilt in place per
[the runbook](docs/unified-agenda-rebuild-runbook.md) with all four tables
byte-identical and only the receipt's producer block moved, and the strict
xfail that named the stale receipt is gone. `git log --grep 'stale receipt'`
on main finds the commit and its digests.

`test_registry_audit_snapshot_is_current_and_honest_about_open_gaps` stays a
STRICT xfail: it fails the moment the thing it documents is fixed, forcing its
own deletion in the same commit. It is not a bug. The registry audit summary
is behind the source manifest (`term_explanation` joined the registry). It is
PARKED, not forgotten: no consumer build needs it, regenerating it rewrites a
tracked evidence artifact (an action needing the owner's own words to whoever
performs it), and the run is the direct module tests, serial, under the shared
measurement lock (`compositions/measurement.lock` in the SpicySearch checkout,
whose AGENTS.md states the rule), so it runs in any quiet window in which no
lane needs that lock. The marker carries the exact command, what is predictable
about the result, and three traps for whoever runs it; read the marker first.

## The one live next action, which is not this lane's

**Capture FERC's docket-prefix PDF.** ~~It is the highest-value unblock this
repository found: 51,015 distinct docket strings, 6.5% of all references in
the Federal Register's docket field, and today a person handed
"Docket No. CP26-20-000" gets nothing. The exact URL, digest, byte count, row
count and field shape — plus the reason the page that returned 403 is the
WRONG page — are in REF-070. It is acquisition work, and the router it feeds
is already written.~~ — **The capture landed (bytes pinned 2026-08-03, digest
`c32efae9…` in `ferc_elibrary_codes.py`; page-by-page attestation in
`research/evidence/ferc-pdf-attestation-2026-08-21/`; parsed into the atlas
with a 95-row count guard). What remains open is the other half of REF-070's
premise: a person handed "Docket No. CP26-20-000" still gets nothing, because
the routing verdict said DO NOT extend while acquisition was pending. The
acquisition landed, so that extension is unblocked — an owner decision, not a
capture.**

**Do not extend `term_explanation` to a fifth identifier shape before an
acquisition lands.** The reasoning is in that module's own docstring, under a
heading addressed to whoever is about to: a family is answerable only where we
hold a directory of INSTANCES, and every unanswered family is blocked upstream
of routing. Surveyed 2026-09-07, verdict DO NOT BUILD, and the survey
overturned its own proposer. *(The condition named here is now met for FERC
docket prefixes: the 95-row directory is captured and parsed; the survey's
blocker was the acquisition, not the shape. An extension is an owner decision,
not a rebuild of this verdict.)*

## Lineage

The Atlas 3.0 bounded-build plan that used to occupy this file is at
[plans/atlas-3.0-lineage.md](plans/atlas-3.0-lineage.md), superseded
2026-08-12 (REF-026/027/028) and moved 2026-09-07 — a superseded document
should not hold the name every "read the plan first" instruction resolves to.

## SpicyDocs 0.53.0 adoption (local, 2026-09-30)

The recovery branch prepares RefSpec dev24 on the released SpicyDocs 0.53.0
wheel so DocSpec, Search and Engine can resolve one provider version. The
loaded-provider comparison and exact module diff are retained under
`~/Work/corpora/claude-recovery-20260930/`. The standard `make test-package`
gate and lint passed; see `refspec-package-gate.log` and `refspec-lint.log`
in that evidence directory. The existing registry-audit expected failure is
listed in `tests/allowed_skips.json`. Slow and full-Atlas qualification were
not rerun. No binding, sealed artifact, publication or remote branch has moved.

## FNS → FNA succession (dev25, 2026-10-04)

`review/fna-succession-dev25` prepares RefSpec dev25 with the four commits of
`chaos/2026-10-03-fns-fna-succession`, cherry-picked onto dev24 (`0d928093`),
which was already their base: the trees are identical. The owner accepted
`event:fr200` on 2026-10-03: FR 200 (Food and Nutrition Service) became FR 625
(Food and Nutrition Administration) effective 2026-06-24, 91 FR 37779. The
decision binds to the event's content digest `3e163e87...`. The
`agency-registry-2026-09-26` release reads batch 1, then the succession batch:
27 = 13 bridges + 10 events + 4 non-emissions, `sourceReleaseDigest`
`dc639b30...`. The agency registry view is schema 1.2 with the derived
current-successors table (manifest `0b39812d...`); see
[the design, section 8](plans/agency-registry-design.md). The version bump
moves no digest. The bounded gates, the slow tier (446 passed, three workers)
and its skip check pass on this tree; the full-Atlas tier did not run. Nothing
is released or published.

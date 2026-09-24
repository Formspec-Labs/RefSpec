# RefSpec plan

**Read first:** [AGENTS.md](AGENTS.md) for working doctrine, the
[decision ledger](docs/decisions.md) for why anything is the way it is.
Longer-running plan detail is in [plans/](plans/) — start with
[validation-cost-reset-plan.md](plans/validation-cost-reset-plan.md) and read
its CONTINUATION header.

## State as of 2026-09-17

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

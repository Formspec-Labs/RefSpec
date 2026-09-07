# RefSpec plan

**Read first:** [AGENTS.md](AGENTS.md) for working doctrine, the
[decision ledger](docs/decisions.md) for why anything is the way it is.
Longer-running plan detail is in [plans/](plans/) — start with
[validation-cost-reset-plan.md](plans/validation-cost-reset-plan.md) and read
its CONTINUATION header.

## State as of 2026-09-07

Branch `main`, tree clean, gate green (`make test`; the two pytest tiers were
last run at `-n 6` rather than `-n auto` because other work held the machine —
worker count is the only deviation).

**Commits sit unpushed here and that is deliberate, not a backlog.** RefSpec's
public origin is pushed only on the owner's own words to the session doing the
pushing. Do not push them because they are here; ask. For the count, ask git
rather than this file — `git rev-list --count origin/main..HEAD` — because a
number written here goes stale on the next commit, including the commit that
updates this line.

## The one parked item, and what unblocks it

`test_registry_audit_snapshot_is_current_and_honest_about_open_gaps` is a
STRICT xfail: it fails the moment the thing it documents is fixed, forcing its
own deletion in the same commit. It is not a bug. The registry audit summary
is behind the source manifest (`term_explanation` joined the registry), its
module list shifted rather than merely short.

Regenerating it is `make audit-registry-real-data`, which rewrites a tracked
evidence artifact -- an action needing the owner's own words to whoever
performs it -- and runs the complete suite serially (the direct module tests
alone recorded 1,194 s in the committed summary, and the complete suite follows
them) under the shared SpicySearch measurement lock, so it runs in the first
window in which no lane needs that lock, never mid-batch. The marker carries the two
traps for whoever runs it; read them first, particularly the one about
`verify_registry_audit.py` silently destroying the honestly named gaps. The
expected result is derivable before running: the gate stays `failed` and
gains exactly one gap, term_explanation's, which has no publisher input of its
own by design.

## The one live next action, which is not this lane's

**Capture FERC's docket-prefix PDF.** It is the highest-value unblock this
repository found: 51,015 distinct docket strings, 6.5% of all references in
the Federal Register's docket field, and today a person handed
"Docket No. CP26-20-000" gets nothing. The exact URL, digest, byte count, row
count and field shape — plus the reason the page that returned 403 is the
WRONG page — are in REF-070. It is acquisition work, and the router it feeds
is already written.

**Do not extend `term_explanation` to a fifth identifier shape before an
acquisition lands.** The reasoning is in that module's own docstring, under a
heading addressed to whoever is about to: a family is answerable only where we
hold a directory of INSTANCES, and every unanswered family is blocked upstream
of routing. Surveyed 2026-09-07, verdict DO NOT BUILD, and the survey
overturned its own proposer.

## Lineage

The Atlas 3.0 bounded-build plan that used to occupy this file is at
[plans/atlas-3.0-lineage.md](plans/atlas-3.0-lineage.md), superseded
2026-08-12 (REF-026/027/028) and moved 2026-09-07 — a superseded document
should not hold the name every "read the plan first" instruction resolves to.

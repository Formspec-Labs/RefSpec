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

**Seven commits are unpushed and that is deliberate.** RefSpec's public origin
is pushed only on the owner's own words to the session doing the pushing, and
that word has not been given for these. Do not push them because they are
here; ask.

## The two parked items, and what unblocks them

Both are STRICT xfails, so each fails the moment the thing it documents is
fixed, forcing its own deletion in the same commit. Neither is a bug.

- `test_the_receipt_names_the_code_that_wrote_it` — `cfr_authority_notes`
  gained `part_head` (the CFR part's NAME, which it read and threw away), so
  the sealed Unified Agenda receipt names code the tree no longer holds.
- `test_registry_audit_snapshot_is_current_and_honest_about_open_gaps` — the
  registry audit summary is at 100 modules against a manifest at 101, its
  module list shifted rather than merely short.

**Both want one rebuild rather than one each, and both rewrite SEALED
artifacts** — an action needing the owner's own words to whoever performs it.
As of 2026-09-07 that rebuild has three conflicting readings of who owns it
and no one holding it; the gap is with the owner, not with this lane. Each
marker carries the traps in its own reason — read them before running
anything, particularly the one about `verify_registry_audit.py` silently
destroying eleven honestly named gaps.

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

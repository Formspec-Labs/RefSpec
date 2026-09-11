# Preserve competing act-name identities through lookup

The existing popular-name builder already retained multiple laws for a name;
`ActIndex.from_artifact` discarded them through first-row selections. The runtime
now reuses that builder's `PopularNameRecord`, keeps paired law/division source
records, and returns each compatible lookup through the existing `ActResolution`.
An ambiguous parent selects no USC target, while useful candidate targets remain
available. Explicit division context can narrow compatible records. Duplicate rows
and page-only differences do not invent a different law/division identity.

The pinned table has 34 normalized multi-law names and 41 names with competing
law/division identities. The existing builder reproduces all 20,865 normalized
rows from its captured publisher HTML. Raw Detainee Treatment Act, adult education,
CARES and other entries were read with their surrounding source text.

Reversing source-row order changed 889 of 1,056 old diagnostic results, including
335 selected identifiers. The new results are order-invariant, retain every
previously selected USC target among the candidates, and reproduce from installed
wheels. Of 8,174 prior policy queries, 26 change original fields, all for competing
name identities. These selected populations overlap; this is not an accuracy rate.

The calendar consumer now supplies a year only when every candidate law has the
same known year. Three multi-law names keep their common year; eight conflicting
names no longer take the first law's year. The copied prior loader, resolver and
calendar check remain test-only oracles. Historical publication receipts were not
rewritten to claim that this code produced them; new caller controls cover the
added `act_name_ambiguous` refusal.

448 upstream tests, 42 selected callers and 497 source/installed Rulespec tests
pass. The [full comparison and package receipts](/Users/mikewolfd/Work/rulespec/thoughts/experiments/2026-09-11-act-name-multiplicity/README.md)
retain the raw rows, publisher context, deliberate differences, original failures,
CLI results and remaining limits. The changes are local and installed, not
committed or published. No model calls or source artifact rebuilds were needed.

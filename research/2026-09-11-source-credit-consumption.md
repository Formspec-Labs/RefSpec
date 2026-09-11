# Source-credit evidence and indexed year-first act names

The Rulespec consumer now retains useful information already held by RefSpec:
all `SourceCreditTarget` records behind a multiple-target answer and both
source-labeled identifiers behind `sources_disagree`. Empty added fields remain
empty; the evidence change deliberately preserves the existing resolution policy.

The actual published authority field `sec. 103 of the 2020 PIPES Act` was missed
by occurrence recognition although the existing name index and source credits
could resolve it. `act_name_with_trailing_year` now shares the exact year-first
operation formerly repeated in Unified Agenda prose recovery. The occurrence
reader only accepts its candidate if the supplied name index contains it; raw
source spelling and offsets remain intact, and an exact indexed name wins.

Raw popular-name, classification and source-credit rows were inspected for the
three selected Unified Agenda fields. PIPES section 103 maps to USC 49:60303,
SECURE section 303 maps to USC 29:1153, and SECURE section 127 retains four
possible USC 29 targets without selecting one. These index mappings do not
establish legal applicability, matching historical editions or target bodies.

Copied prior occurrence/resolution checks remain test-only oracles. All original
resolution fields agreed across 608 existing derived act/section pairs. The census
found no real conflicting answers or single accepted table answers accompanied by
multiple source-credit targets; those behaviors have constructed controls only.
Wrong years/names, exact-name precedence, paragraph boundaries, absent indexes,
agreement, disagreement, multiple targets and explicit division mismatch are tested.
The owner selection passed 367 tests; 40 selected Unified Agenda caller tests passed.

The rebuilt RefSpec wheel and Rulespec consumer were verified outside their
checkouts and installed in the working application environment. Rulespec also
fixed an independent discovery failure when inserted separators overlapped source
evidence. Source and installed application suites each passed 495 tests.

Two policy questions remain: a lone classification row outside the named act's
division is not excluded by the current multiple-row check; and existing policy
can accept a single Table III answer alongside multiple source-credit targets.
SECURE section 127 supplies a real specimen for the first question. Do not treat
preserved policy or constructed controls as proof of correctness.

The [experiment and receipts](/Users/mikewolfd/Work/rulespec/thoughts/experiments/2026-09-11-source-credit-consumption/README.md)
retain the exact fields, raw rows, original failures, source/wheel comparisons,
package hashes and limits. The [canonical task list](/Users/mikewolfd/Work/rulespec/thoughts/plans/2026-09-10-reference-integration-task-list.md)
tracks the open policy checks under R13. Changes are local, uncommitted and unpublished.

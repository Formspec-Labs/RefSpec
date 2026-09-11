# Apply existing act-resolution rules to complete source evidence

The two Rulespec consumer questions are settled by separate comparisons followed
by their composition. RefSpec now applies division exclusion to one or many
classifications, only when every page is complete and outside the conservative
division bounds. It consumes the existing pinned quarantine data to identify
shortened page spellings and refuses mixed classification/quarantine artifacts.
Unknown pages cannot establish exclusion; in-range pages do not select a winner.

Multiple source-credit targets now prevent selecting a lone Table III answer.
The native result uses existing `act_section_ambiguous`, retains existing credit
targets, and adds optional `table3_candidate_iri` for the table's unselected
identifier. A candidate is not a chosen answer. Both policy identifiers moved to
version 2; input schemas and sealed artifacts remain unchanged.

The comparison covered 8,174 source-derived lookup pairs under explicit bounds.
Twenty-nine formerly selected plural answers represent seven distinct
law/division/section keys. The page change removes 22; the multiplicity change
removes the remaining seven. No selected identifier changes across the 608
publication-derived pairs; SECURE section 127 gets a more accurate refusal reason.
All prior source-credit candidate lists survive. These counts describe native
lookup behavior, not general document accuracy.

The raw PL 104-201 XML shows section 1416 classified to USC 50:2316, with child
classifications also present. Pinned USLM credits identify 1416(a)(1) for USC
10:282 and 1416(c)(1)(A) for USC 18:175a. Both facts matter: the table candidate
is real and is not unique. Raw Energy Act and SECURE rows establish the separate
outside-division examples. The retained page records include compound spellings
as well as ranges, so no new page parser was introduced.

The existing copied resolver is the prior oracle. Every original field is checked
before the intervention; all changed results are enumerated. Owner tests passed
391 checks, selected Unified Agenda/term-explanation callers passed 42, and
Rulespec's source and installed suites each passed 496. Rebuilt-wheel results
match all 8,174 direct-source results. The consumer hashes the newly read file
and uses its existing sparse result/evidence path.

[Full evidence, limits and package receipts](/Users/mikewolfd/Work/rulespec/thoughts/experiments/2026-09-11-act-resolution-policy/README.md)
include the raw XML/credit context, narrowed-page controls, original failures,
independent arms and installed command checks. No model calls, corpus rebuild,
commit or publication occurred. Further named-act spelling/range/name-identity
questions remain separate from this delivered policy fix.

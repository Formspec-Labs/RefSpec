# Source-grounded subpart occurrences

The `find_cfr_citations` consumer in Rulespec needs complete cited destinations.
The old callback ended Ohio's `49 CFR Part 172 subpart E (labeling) or subpart F
(placarding)` at the part number. The surrounding paragraph names alternative
hazard-marking methods, so neither the second subpart nor the connector can be
discarded. The fix extends that callback, leaving `parse_cfr_citations` unchanged.

`CfrCitationOccurrence` adds optional `subpart`, `subpart_end`, `appendix` and
`qualifier_status`. Each written list member retains exact source coordinates and
the existing context coordinates. Ranges retain stated endpoints only. Multiple
parts followed by a subpart list are flagged `ambiguous_part_scope`; the Rulespec
consumer preserves them as refused candidates instead of inventing a pairing.
The shared paragraph-boundary check now serves act and CFR occurrences.

The fixed inputs include six paragraphs selected independently of parser success
from pinned title 21/40/49 XML. Full original sections, per-title dates and matching
file hashes are saved in the Rulespec experiment. FDA's 21 CFR 2.125(a) distinguishes
appendix A/B to subpart A. EPA's 40 CFR 2.401(b)(3) places an employee-testimony
qualification in parentheses after subpart E; that source is preserved as text,
not treated as an extra label. DOT's 49 CFR 11.104(d)(4)(iii) names two parts and two
subparts without sufficient syntax to establish each pairing.

The old callback was copied into `tests/cfr_parser_oracle.py` before replacement.
`test_cfr_subparts.py` freezes all deliberate changes, compares unrelated readings
exactly, and includes sentence/prose/paragraph, malformed suffix, plural, range,
Unicode, repeat and native-refusal controls. Final owner checks: 338 parser/resolver
tests; 40 selected Unified Agenda caller tests also passed before the one-line
plural-continuation refinement. The unchanged identity API has explicit parity
checks. No registry/corpus rebuild or published schema change occurred.

The callback scans anchored suffixes and list members once, with constant-size
work per matched label and source slice. It does not rescan every document prefix
or search for normalized text to recover positions. Existing parser complexity
outside this changed callback is unchanged.

Evidence, original failures, field mapping and source/wheel/consumer verification:
[Rulespec comparison](/Users/mikewolfd/Work/rulespec/thoughts/experiments/2026-09-11-cfr-subparts/README.md).
These selected inputs demonstrate representation improvement, not general semantic
accuracy or existence of any destination in a particular edition.

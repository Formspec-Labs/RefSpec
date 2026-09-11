# Act occurrences preserve source positions and citation context

The Rulespec consumer needed exact occurrences before it could reuse the existing
act index/resolver. The owner now exports `ActRelativeCitationOccurrence` and
`find_act_relative_occurrences`; `find_act_relative_citations` remains the
deduplicated identity view over that same matcher.

Evidence and full captures:
[Rulespec experiment](/Users/mikewolfd/Work/rulespec/thoughts/experiments/2026-09-11-act-index-reuse/README.md).
The eight selected source fields come from the pinned Unified Agenda artifact.
For example, the full authority box `Sec 508 (b)(7)(A) Federal Crop Insurance
Reform Act of 1994` establishes that a known act name can immediately follow
the subsection chain without `of` or a comma. Both spaced and unspaced variants
are retained in the fixture with RIN and publication identifiers.

Declared identity-reader changes are the adjacent-name additions and refusal to
borrow division/name context from separate sentences or paragraphs. Explicit
`division B of the [known act]` remains supported, including uppercase `Division`.
Short qualifiers still permit identity recognition, but years and `as amended`
are not labeled as subsection pinpoints. No identity is guessed for an unknown
acronym. No codified subsection correspondence is inferred from an act pinpoint.

`tests/act_parser_oracle.py` freezes the previous matcher. Real-field and mutation
comparisons preserve its other checked results. Validation: 304 parser/resolver
tests and 40 selected Unified Agenda caller tests passed. The rebuilt wheel and
Rulespec consumer produce identical selected scans; all prior CFR/five-family
occurrences are unchanged. These selected checks are not a full artifact rebuild
or a general accuracy estimate. Existing sealed artifacts were not modified or
republished; a future producer run must identify its changed parser normally.

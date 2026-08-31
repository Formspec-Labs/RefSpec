# RefSpec agent guidance

Use [README.md](README.md) for the repository overview and current document
index. Before making Atlas strategy, positioning, source-selection, or public
delivery claims, read [Atlas in the United States and Europe](ATLAS_US_EU_COMPARISON.md).

Treat the comparison as strategic context. The
[Atlas 3.0 binding](bindings/atlas/3.1/README.md), current code, and
[decision ledger](docs/decisions.md) establish implementation authority.

Structure must earn its keep. Add a term, spec section, layer, or boundary
only together with the validator or consumer that breaks when it is violated,
including a negative fixture. Prefer deleting structure to documenting it.
RefSpec depends on RuleSpec (rkaf) directly: never mint a parallel term for a
concept rkaf already defines, and never add a compatibility layer between
components with a single owner. See REF-023 in [the decision ledger](docs/decisions.md).
The cross-product ownership rows and the artifact-and-package exchange rule
are REF-024 in that ledger; cite it rather than restating a boundary.

Replacing a check keeps the old one as an oracle. Any replacement of a running
check keeps the old implementation as a test-only oracle -- copied into the
test, not imported, since importing the thing under replacement makes the
comparison circular -- and proves verdict agreement over real data AND a
mutation battery before the production path is deleted. Passing on real data
alone proves only that the new check accepts what is valid; what it rejects is
unproven until something mutates the data on purpose. Record the deliberate
divergences as a frozen list, so an unlisted one fails the suite instead of
becoming a diff nobody reads. The pattern to copy is
[tests/test_atlas_v3_canonical_line_grammar.py](tests/test_atlas_v3_canonical_line_grammar.py),
where 29,283,283 clean real lines said nothing and the mutation battery found
a silent escaped-UCHAR divergence.

The raw source is read around the match, or the pattern is not traced. A grep
locates; it never validates. Before any pattern is admitted to a grammar, any
extracted value is trusted, or any moved number is re-pinned, open the actual
source bytes and read the text AROUND the datum — the surrounding fields,
lines, or page — because the context is where a match turns out to be a Stat.
page list resuming a U.S.C. list, a docket that is really a report number, or
a "fused" token that the printed page itself welded. When the source is a
rendered format (a PDF, a printed page), view it as pixels, not a text layer:
the E5-2394Filed attestation found the text layer agreeing with the render
only AFTER the render was read at 600 dpi against a spaced control colophon
on the same page. This applies to every agent working this repository, and a
report that traces a pattern shows at least one specimen WITH its
surrounding raw context and says what the context ruled in or out. The day's
proof of the rule: one manual raw pass over an already twice-reviewed
backlog killed one item, re-scoped another 623-fold, and broke a proposed
fix before anyone built it (research/backlog-validation-2026-08-31.md).

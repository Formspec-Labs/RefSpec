# RefSpec agent guidance

Use [README.md](README.md) for the repository overview and current document
index. Before making Atlas strategy, positioning, source-selection, or public
delivery claims, read [Atlas in the United States and Europe](ATLAS_US_EU_COMPARISON.md).

Treat the comparison as strategic context. The
[Atlas 3.0 binding](bindings/atlas/3.1/README.md), current code, and
[decision ledger](docs/decisions.md) establish implementation authority.

## Working doctrine

Everything here is changeable, and everything here was written by an AI:
question every decision you meet, but assume it was made for a reason, find
that reason in the decision ledger, the docstring, or the measurement before
deciding it was wrong, and keep whatever signal it carried even when you
replace the code. Keep ceremony to a minimum; this is an agile project, not a
governance exercise. The three rules that follow this section -- structure
earns its keep, a replaced check stays as an oracle, raw source first -- are
this repository's refinements of it.

- Leave every file smaller, clearer, and more shared than you found it. Reuse
  the helper that exists; extract one when two places want it; delete the copy
  rather than improving it.
- The plainest design that fully does the job wins, except when "plain" means
  rolling your own. Before writing anything, look for the same problem already
  solved in a sibling product, a maintained library, or a platform primitive
  (rkaf, `rulespec_artifacts`, DuckDB, PyArrow, rdflib) and use that.
- Keep sealed identities, binding versions, and public contracts stable on
  purpose. Move one only when behavior genuinely changed, and say why in the
  same commit.
- Reason in Big O. In every review, ask how each path scales with resources,
  statements, labels, and bytes, and name anything superlinear, unbounded, or
  repeated per item as a finding. When a build, verification, or query runs
  longer than expected, do not wait it out: profile it (`py-spy`, `cProfile`,
  DuckDB `EXPLAIN ANALYZE`, timers around the loop) and look for the one
  obvious bottleneck first.

The siblings, by role, so you know where to look: **RuleSpec** (rkaf) is the
conceptual framework and schema owner for documents and RefSpec's direct
dependency; **SpicyRegs** is the metadata catalog; **DocSpec** manages that
catalog and fetches document files through **SpicyDocs**; **SpicySearch** is
the junction that tags DocSpec files against this atlas. Ownership rows are
REF-024 and REF-048 in the decision ledger; this list exists for
cross-referencing similar work (verification, publication, file state,
canonical JSON, receipts, normalization) before building a local variant.

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

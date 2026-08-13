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

# RefSpec agent guidance

Use [README.md](README.md) for the repository overview and current document
index. Before making Atlas strategy, positioning, source-selection, or public
delivery claims, read [Atlas in the United States and Europe](ATLAS_US_EU_COMPARISON.md).

Treat the comparison as strategic context. The
[Atlas 3.0 binding](bindings/atlas/3.0/README.md), current code, and
[decision ledger](docs/decisions.md) establish implementation authority.

Structure must earn its keep. Add a term, spec section, layer, or boundary
only together with the validator or consumer that breaks when it is violated,
including a negative fixture. Prefer deleting structure to documenting it.
RefSpec depends on RuleSpec (rkaf) directly: never mint a parallel term for a
concept rkaf already defines, and never add a compatibility layer between
components with a single owner. See REF-023 in [the decision ledger](docs/decisions.md).
The cross-product ownership rows and the artifact-and-package exchange rule
are REF-024 in that ledger; cite it rather than restating a boundary.

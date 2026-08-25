# Vendored dependency: rulespec-conformance

`rulespec_conformance-0.2.0rc13-py3-none-any.whl` is vendored into this repo
because CI runners have no `~/Work/rulespec` checkout and `ci.yml` runs
`uv sync --frozen`: a path source outside the repository cannot resolve
there. Vendoring the wheel keeps `uv lock`/`uv sync` hermetic and lets
`[tool.uv.sources]` point at a file that is always present.

This is interim, not a design choice: it lasts until a package index (a
private index or an internal registry) exists for `rulespec-conformance`,
at which point the vendored file and the `[tool.uv.sources]` entry in
`pyproject.toml` should be deleted in favor of a normal version constraint.

**Source of truth**: the wheel is built from the rulespec repository's
`feat/rulespec-conformance-package` branch at `d85df96`. In addition to the
existing Rulespec bindings, it carries the shared platform artifact protocol
and source-catalog schema used by SpicyRegs, DocSpec, and SpicySearch. Its
SHA-256 digest is
`38674800fc9f374dc27885b5ad4217268bb57b36f4de78a586ee0125b27c49dc`.

**Bumping the contract**: when rulespec ships a new contract revision,
replace this wheel file with the new build, update the version in this
file's name and in `pyproject.toml`'s `[tool.uv.sources]` entry, then run
`uv lock` to re-resolve. Do not hand-edit `uv.lock`.

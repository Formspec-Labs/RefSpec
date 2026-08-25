# Vendored dependency: rulespec-conformance

`rulespec_conformance-0.2.0rc15-py3-none-any.whl` is vendored into this repo
because CI runners have no `~/Work/rulespec` checkout and `ci.yml` runs
`uv sync --frozen`: a path source outside the repository cannot resolve
there. Vendoring the wheel keeps `uv lock`/`uv sync` hermetic and lets
`[tool.uv.sources]` point at a file that is always present.

This is interim, not a design choice: it lasts until a package index (a
private index or an internal registry) exists for `rulespec-conformance`,
at which point the vendored file and the `[tool.uv.sources]` entry in
`pyproject.toml` should be deleted in favor of a normal version constraint.

**Source of truth**: the wheel is built from the rulespec repository's
`feat/rulespec-conformance-package` branch at `53a3e76`. It carries the one
shared platform artifact protocol, its common fixtures, and the source-item
schema used by SpicyRegs, DocSpec, and SpicySearch. Its
SHA-256 digest is
`37cf3f866bd4fe429137eccf876693193eb8ca3de62bf335101d992661c68681`.

**Bumping the contract**: when rulespec ships a new contract revision,
replace this wheel file with the new build, update the version in this
file's name and in `pyproject.toml`'s `[tool.uv.sources]` entry, then run
`uv lock` to re-resolve. Do not hand-edit `uv.lock`.

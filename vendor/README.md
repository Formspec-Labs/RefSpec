# Vendored dependencies: rulespec-conformance and rulespec-artifacts

`rulespec_conformance-0.2.0rc16-py3-none-any.whl` is vendored into this repo
because CI runners have no `~/Work/rulespec` checkout and `ci.yml` runs
`uv sync --frozen`: a path source outside the repository cannot resolve
there. Vendoring the wheel keeps `uv lock`/`uv sync` hermetic and lets
`[tool.uv.sources]` point at a file that is always present.

This is interim, not a design choice: it lasts until a package index (a
private index or an internal registry) exists for `rulespec-conformance`,
at which point the vendored files and the `[tool.uv.sources]` entries in
`pyproject.toml` should be deleted in favor of normal version constraints.

**Source of truth**: the wheel is built from the rulespec repository's
`feat/widen-frdoc-and-cfr-lexical-spaces` branch at `961de3c`, which
descends from `feat/rulespec-conformance-package` at `ae9ebc7` with no
divergence. It carries the one shared platform artifact protocol, its common
fixtures, and the source-item schema used by SpicyRegs, DocSpec, and
SpicySearch. Its SHA-256 digest is
`f66be5e7613a0d8e1dbfe88885a1b694309fe0144431c3a1e3f3adf105f2382b`.

**Why a second wheel.** `rulespec_artifacts-1.0.9-py3-none-any.whl` is
vendored alongside it because rc16 declares `rulespec-artifacts==1.0.9` as a
hard dependency and rc15 did not. That dependency arrived with the shared
platform-artifact protocol, not with any contract change; nothing in RefSpec
imports it, and `rulespec_conformance` itself reaches for it only lazily,
inside three platform-artifact helpers this repo never calls. But a declared
dependency still has to resolve, and `rulespec-artifacts` is on no index
either, so it is vendored on the same interim terms and should be deleted at
the same time. Its SHA-256 digest is
`67cb33bf63c11bc6812ad0e8f0a8b73e89501fa6d4242acf75a7cc6612f5d6c6`, byte
identical to the copy SpicySearch already vendors.

**What rc16 changed in the contract.** Two US lexical spaces widened, both
strict supersets, so no previously valid identifier changed meaning:
`rkaf:us-frdoc` accepts a three- to five-digit sequence (was five exactly),
and a `rkaf:us-cfr` part may carry a single lowercase letter or a
hyphen-number suffix (was digits only). `rkaf:us-rin` is unchanged. See
REF-054 in `docs/decisions.md`.

**Bumping the contract**: when rulespec ships a new contract revision,
replace the wheel file with the new build, update the version in this
file's name and in `pyproject.toml`'s `[tool.uv.sources]` entry, then run
`uv lock` to re-resolve. Do not hand-edit `uv.lock`. Check the new wheel's
`Requires-Dist` against the previous one before locking: an added dependency
that is on no index has to be vendored too, which is how the second wheel
above arrived.

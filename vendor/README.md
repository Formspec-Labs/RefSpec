# Vendored dependencies: rulespec-conformance and rulespec-artifacts

`rulespec_conformance-0.2.0rc18-py3-none-any.whl` is vendored into this repo
because CI runners have no `~/Work/rulespec` checkout and `ci.yml` runs
`uv sync --frozen`: a path source outside the repository cannot resolve
there. Vendoring the wheel keeps `uv lock`/`uv sync` hermetic and lets
`[tool.uv.sources]` point at a file that is always present.

This is interim, not a design choice: it lasts until a package index (a
private index or an internal registry) exists for `rulespec-conformance`,
at which point the vendored files and the `[tool.uv.sources]` entries in
`pyproject.toml` should be deleted in favor of normal version constraints.

**Source of truth**: rc18 is built from the rulespec repository's
`feat/us-frdoc-x-space` branch at `3e439a3`, in the `~/Work/rulespec-x`
worktree. That branch is based on `feat/us-frdoc-legacy-space` (`850c204`),
so rc18 carries BOTH new spaces and rc17 was never vendored beyond an
afternoon. It carries the one shared
platform artifact protocol, its common fixtures, and the source-item schema
used by SpicyRegs, DocSpec, and SpicySearch. Its SHA-256 digest is
`bd4816dac509ed0a9686fc94104d8463d6e05c53b8e2ce74e9d1ea9a67b76977`.

**rc18 IS A PROVISIONAL PIN.** That branch is local and unmerged as of
2026-09-02, so this wheel is not built from anything published: if the branch
moves before it merges, this wheel must be rebuilt and re-vendored, because
the digest above IS the pin and a moved branch silently invalidates it.
The predecessor rc16 came from `feat/widen-frdoc-and-cfr-lexical-spaces` at
`961de3c` (digest
`f66be5e7613a0d8e1dbfe88885a1b694309fe0144431c3a1e3f3adf105f2382b`),
descending from `feat/rulespec-conformance-package` at `ae9ebc7` with no
divergence.

**Why a second wheel.** `rulespec_artifacts-1.0.9-py3-none-any.whl` is
vendored alongside it because rc16 declared `rulespec-artifacts==1.0.9` as a
hard dependency and rc15 did not (rc17 declares the same pin, so no second
bump was needed -- checked against its `Requires-Dist` before locking, exactly
as the bump procedure below says to). That dependency arrived with the shared
platform-artifact protocol, not with any contract change; nothing in RefSpec
imports it, and `rulespec_conformance` itself reaches for it only lazily,
inside three platform-artifact helpers this repo never calls. But a declared
dependency still has to resolve, and `rulespec-artifacts` is on no index
either, so it is vendored on the same interim terms and should be deleted at
the same time. Its SHA-256 digest is
`67cb33bf63c11bc6812ad0e8f0a8b73e89501fa6d4242acf75a7cc6612f5d6c6`, byte
identical to the copy SpicySearch already vendors.

**What rc17 and rc18 changed in the contract.** Two additions, no widening of
an existing space, so nothing previously valid changed meaning.

rc17 added `rkaf:us-frdoc-legacy` for pre-2010 Federal Register document
numbers, spelled `urn:rkaf:us:frdoc-legacy:{NN-N..N}:{YYYY-MM-DD}`. It is
DATE-QUALIFIED by construction, because the bare number does not identify a
document on its own -- `00-111` names two -- so the publication date is part
of the identity rather than metadata beside it.

rc18 added `rkaf:us-frdoc-x` for the X family, spelled
`urn:rkaf:us:frdoc-x:X{YY}-{seq}{MMDD}` and taking NO date qualifier, because
that form encodes its own publication date: read right-anchored, the last four
digits are the month and day and the remainder is the sequence, and it agrees
with `publication_date` on 4,400 of 4,400 corpus rows. The `{5,7}` tail is
capacity rather than data fit -- a fixed-width `{5}` would have refused
`X09-101207` on day one, one of 206 six-digit numbers a five-digit shape
silently filtered out of its own census. See REF-064 and REF-065 in
`docs/decisions.md`.

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

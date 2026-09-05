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

**Source of truth**: rc18 is built from the rulespec repository's annotated
tag `v0.2.0-pre.18` (tag object `b942529e`, commit `a519d06b`), pushed to
`github.com/Formspec-Labs/rulespec`. Its SHA-256 digest is
`ed11ab4a4709fd36b36ad445dd17ac0e14c10ec0d1f605f662f1a68a6ab662fb`, byte
identical to the copy SpicySearch vendors. It carries the one shared
platform artifact protocol, its common fixtures, and the source-item schema
used by SpicyRegs, DocSpec, and SpicySearch.

**rc18 was re-cut and the version string did not move.** Until 2026-09-04
the vendored rc18 was built from the local unmerged branch
`feat/us-frdoc-x-space` at `3e439a3`, digest
`bd4816dac509ed0a9686fc94104d8463d6e05c53b8e2ce74e9d1ea9a67b76977`, and this
file called it a provisional pin for exactly that reason: a branch moves
under its own name. The tag released that work, so the wheel was rebuilt
from the tag -- SAME version string, DIFFERENT bytes. `0.2.0rc18` therefore
does not identify these bytes; the digest does, and `uv.lock` records it.
The superseded digest must not come back. A tag is immutable, so the pin is
no longer provisional; what would make it provisional again is vendoring
from a branch, a worktree, or any other ref that can be repointed.

**Built from a published tag is not the same as a published package.**
`rulespec-conformance` is on no index. These bytes were built here, from
that tag, and committed. That is what
`profiles/rulespec-dependency.json` means by
`releaseAvailability: localUnpublished`, and why
`publication-release-manifest.schema.json` holds such a release to
`deploymentClass: developmentOnly`: a consumer cannot obtain this dependency
from a publisher, only rebuild it from source. The tag changed where the
bytes come from, not whether anyone else can get them, so that field stays
`localUnpublished` until an index exists -- the same event that deletes this
directory.

**Why a second wheel.** `rulespec_artifacts-1.0.11-py3-none-any.whl` is
vendored alongside it because rc18 declares a `rulespec-artifacts>=1.0.11`
floor where rc16 and rc17 declared a hard `==1.0.9`, so 1.0.9 no longer
satisfies it. That dependency arrived with the shared platform-artifact
protocol, not with any contract change; nothing in RefSpec imports it, and
`rulespec_conformance` itself reaches for it only lazily, inside three
platform-artifact helpers this repo never calls. But a declared dependency
still has to resolve, and `rulespec-artifacts` is on no index either, so it
is vendored on the same interim terms and should be deleted at the same
time. Its SHA-256 digest is
`bedd8ee4799d9633963272714a30258f505404155732480ad5cb1dde2d7cbf4f`, byte
identical to the copies DocSpec and SpicySearch vendor -- all three compared
2026-09-05. `pyproject.toml` carries the measured 1.0.9 -> 1.0.11 diff
beside the pin rather than repeating it here.

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
replace the wheel file with the new build, update the version in this file's
name and in `pyproject.toml`'s `[tool.uv.sources]` entry, then run `uv lock`
to re-resolve; do not hand-edit `uv.lock`. Update the digests above in the
same commit -- `tests/test_rulespec_dependency_pin_drift.py` compares them
against the bytes actually in this directory, so a stale one fails the suite
rather than sitting here for days, which is how the 2026-09-04 re-cut was
found. Check the new wheel's `Requires-Dist` against the previous one before
locking: an added dependency that is on no index has to be vendored too,
which is how the second wheel above arrived.

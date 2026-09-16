# Vendored dependencies

`spicy_docs-0.19.0-py3-none-any.whl` supplies shared source readers and
bounded U.S. Code acquisition with validated archive member delivery.
SHA-256: `8ec1ee8d604f09e4e451876a03ec71e394867b88b0711375f724c0c1ce69cf41`.
Provider source: SpicyDocs `dfe3a0c735aa5255373f27743f684b224c51e7a2` on `codex/govinfo-premis`.
RefSpec 0.1.0.dev10 retains snapshot acceptance, normalization and interpretation.
Its title cache records original HTTP facts; its corpus and annual tools process
validated members without reopening ZIPs. See [U.S. Code inputs](../docs/uscode-acquisition.md).

Python 3.12, PyArrow 25.0.1 and DuckDB 1.5.5 or later remain unchanged. Existing
sealed artifacts are unchanged; comparing a new writer to older Parquet bytes
requires a row comparison. This RefSpec wheel is qualified with SpicyDocs 0.19.
The current DocSpec 0.6/Search 0.2/Engine 0.4 stack pins SpicyDocs 0.17 and cannot
share this environment until a coordinated adoption. Search's optional identity
comparison group still uses the separately qualified RefSpec dev9; its runtime
does not depend on RefSpec. SpicyRegs 0.1.6 remains qualified with SpicyDocs 0.18.

The `acquisition` extra supplies explicit Topics and U.S. Code HTTP routes.
Imports remain offline. The `pdf-pypdf` extra supplies shared GAO page reading.
USLM/eCFR formatting, Unicode positions and section interpretation stay here.

PAR07 compares the complete CFR preservation record and its three accepted
file digests against the frozen reader. Thirty files without fixity remain
available upstream. Source pins, first-path field selection and identifier
values stay unchanged; bounded XML rejects DTDs and excessive depth. The
separate SpicyDocs byte comparer checks selected file consistency, not authenticity.

This wheel is vendored for reproducible installation and is not published to
an index. Earlier qualification covers all 7,767 FR topic rows and 241,726
Agenda records. Sealed data remains unchanged. Topics runs now retain separate producer receipts,
and source-credit receipts include installed reader hashes. The `pdf-pypdf` extra
shares raw GAO PDF page reading while RefSpec retains folding and interpretation.

Prior U.S. Code structure corrections remain unadopted candidates. CFR authority
observations retain actual scope; the existing authority cache is unchanged.

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

**Why a second wheel.** `rulespec_artifacts-1.0.12-py3-none-any.whl` is
vendored alongside it because rc18 declares a `rulespec-artifacts>=1.0.11`
floor where rc16 and rc17 declared a hard `==1.0.9`, so 1.0.9 no longer
satisfies it. That dependency arrived with the shared platform-artifact
protocol. RefSpec now uses its bounded local blob writer for BILLSTATUS
captures. The package is also required by rulespec-conformance, and `rulespec-artifacts` is on no index either, so it
is vendored on the same interim terms and should be deleted at the same
time. Its SHA-256 digest is
`3f6c946c60ff2ddbe854fce7f74f4358ddb21e3ba3f6ad10caa8a0d8d59fd0a5`, copied
from SpicyDocs' qualified wheel on 2026-09-14. Rulespec commit `bf59d63`
adds a bounded local blob writer and public exports; the existing artifact
encoder/verifier module and dependency closure are unchanged from 1.0.11.
This storage adoption does not regenerate sealed data artifacts.

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

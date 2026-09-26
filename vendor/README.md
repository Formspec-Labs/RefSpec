# Vendored dependencies

`spicy_docs-0.39.2-py3-none-any.whl` supplies shared source readers and
bounded U.S. Code acquisition with validated archive member delivery.
SHA-256: `254fbecb17a01067843167512b7a6b34750735f526c9e968b359723e08641e6d`.
Provider source: SpicyDocs `d6b700324595afa23818d126fa68e01f8977292f` (the 0.39.2
release commit on `main`), with Rulespec Artifacts 1.1.2; the same bytes SpicyRegs
vendors, and a rebuild from a clean archive of that commit reproduces them.
RefSpec 0.1.0.dev10 retains snapshot acceptance, normalization and interpretation.
Its title cache records original HTTP facts; its corpus and annual tools process
validated members without reopening ZIPs. See [U.S. Code inputs](../docs/uscode-acquisition.md).

Python 3.12, PyArrow 25.0.1 and DuckDB 1.5.5 or later remain unchanged. Existing
sealed artifacts are unchanged; comparing a new writer to older Parquet bytes
requires a row comparison. RefSpec 0.1.0.dev17 is qualified with SpicyDocs 0.39.2
and Rulespec Artifacts 1.1.2. Sibling pins move on their own schedule, so read
each repository's `pyproject.toml` rather than a list here; SpicySearch vendors
RefSpec in optional groups only, and its runtime does not depend on RefSpec.

**What 0.31.0 adds for RefSpec.** The canonical citation grammar, identifier
shapes and `urn:rkaf` minting (`spicy_docs.interpretation.citation_grammar`,
`identifier_shapes` with `normalize_docket_references`, and `iri_minting`),
ported from RefSpec's own modules, and the Unified Agenda field-path projection
(`spicy_docs.sources.unified_agenda.projection`), moved from
`unified_agenda_editions`. RefSpec does not import these yet: the switch moves
expectations and Unified Agenda counts, so it waits for a rebuild (see
[PLAN.md](../PLAN.md)). The only new `Requires-Dist` against 0.26.6 is the
unused `courtlistener-local` extra.

**What 0.36.0 changes for RefSpec.** Its `Requires-Dist` equals 0.31.0's. Of
the modules RefSpec imports, four changed: `sources.uscode` now ships OLRC
Table III's `iter_table3_chain`, and an act without a Table III page is a
retried transport failure that keeps the dropped body rather than a refusal;
`sources.zyte` moved its shared provider rules into `transport.provider_api`,
with the names RefSpec imports unchanged; `transport.credentials` makes `CREDENTIAL_PARAMETERS`
public and lets `scrub_credential` take several keys; `reading.zip_archive`
gains an optional per-member observer. The Unified Agenda and Federal Register
Topics receipts hash unchanged modules, so their producer blocks do not move;
a rebuilt U.S. Code source-credit receipt records new digests for
`sources.uscode` and `reading.zip_archive`. Since 0.31.0 the grammar, shapes and
minters RefSpec has not yet imported changed too (`identifier_shapes` most),
and the table contracts gained cross-table references; RefSpec imports neither
`spicy_docs.interpretation` nor `spicy_docs.schemas`.

**What 0.39.2 changes for RefSpec.** Nothing it imports. Since 0.36.0
SpicyDocs changed bill families, citations, SAM extracts, bill-version codes and
three bill-table descriptions; 0.39.2 is 0.39.1's code requiring Rulespec
Artifacts 1.1.2 exactly, its only `Requires-Dist` change.

The `acquisition` extra supplies explicit Topics and U.S. Code HTTP routes.
Imports remain offline. The `pdf-pypdf` extra supplies shared PDF page reading
(`refspec.pdf_text.pdf_page_texts`: the GAO, GNIS, FERC and RISC captures).
USLM/eCFR formatting, Unicode positions and section interpretation stay here.

PAR07 compares the complete CFR preservation record and its three accepted
file digests against the frozen reader. Thirty files without fixity remain
available upstream. Source pins, first-path field selection and identifier
values stay unchanged; bounded XML rejects DTDs and excessive depth. The
separate SpicyDocs byte comparer checks selected file consistency, not authenticity.

This wheel is vendored for reproducible installation and is not published to
an index. Earlier qualification covers all 7,767 FR topic rows and 241,726
Agenda records. Sealed data remains unchanged. Topics runs now retain separate producer receipts,
and source-credit receipts include installed reader hashes. RefSpec retains PDF
text folding and interpretation.

Prior U.S. Code structure corrections remain unadopted candidates. CFR authority
observations retain actual scope; the existing authority cache is unchanged.

`rulespec_conformance-0.2.0rc19-py3-none-any.whl` is vendored into this repo
because CI runners have no `~/Work/rulespec` checkout and `ci.yml` runs
`uv sync --frozen`: a path source outside the repository cannot resolve
there. Vendoring the wheel keeps `uv lock`/`uv sync` hermetic and lets
`[tool.uv.sources]` point at a file that is always present.

This is interim, not a design choice: it lasts until a package index (a
private index or an internal registry) exists for `rulespec-conformance`,
at which point the vendored files and the `[tool.uv.sources]` entries in
`pyproject.toml` should be deleted in favor of normal version constraints.

**Source of truth**: rc19 is built from the rulespec repository's annotated
tag `v0.2.0-pre.19` (tag object `e04a297c`, commit `52d80cc1`), pushed to
`github.com/Formspec-Labs/rulespec`. Its SHA-256 digest is
`bb1e2fd674b8863be8022b2bafe4093279194c8dde7aa2c6ce0a6a28ec48e218`, byte
identical to the copy SpicySearch vendors. rc18 came from tag `v0.2.0-pre.18`
(commit `a519d06b`, digest `ed11ab4a…`). It carries the one shared
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

**Why a second wheel.** `rulespec_artifacts-1.1.2-py3-none-any.whl` is
vendored alongside it because rc19, like rc18, declares a `rulespec-artifacts>=1.0.11`
floor where rc16 and rc17 declared a hard `==1.0.9`, so 1.0.9 no longer
satisfies it. That dependency arrived with the shared platform-artifact
protocol. RefSpec now uses its bounded local blob writer for BILLSTATUS
captures. The package is also required by rulespec-conformance, and `rulespec-artifacts` is on no index either, so it
is vendored on the same interim terms and should be deleted at the same
time. Version 1.1.2 is the exact dependency of SpicyDocs 0.39.2, built in
`packages/rulespec-artifacts` from Rulespec's release commit
`23d5f2d98973b2a7f1bf7ce4c9c7a786a4f369ab` and shared by the whole stack; the same
procedure reproduces 1.1.1 from `a3acb04`. Its SHA-256 digest is
`7d547cd432b1d533b93dcfd3802e4a0e179de6e89301fd6faa8bb917b99830ef`.
It adds opt-in DocumentCapture v2 and v1 checker fixes after 1.0.14; 1.1.2 changes
only its version and ships platform fixtures that name it, where 1.1.1's named
1.1.0. The bounded local blob writer and public exports remain.

**What rc19 changed in the contract.** The context declares `oa:XPathSelector`,
already a bound Core selector class, and the release version; no space widened.
Its m2 release fixtures are re-stamped for the recompiled `source-fragment` and
`ai-lineage` schemas, and its platform fixtures name `rulespec-artifacts` 1.1.0.

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

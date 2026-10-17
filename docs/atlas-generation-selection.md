# Select a complete local Atlas generation

The full Atlas builder finishes a distribution, its optional Parquet view, and
its generation report together before selecting them. A failed build leaves
the previous selection available. Readers pin the selection once and then
use those concrete sibling paths for all validation, signing, and reads.

`--output` names a local selection symlink. For example:

```text
release/
├── distribution -> .distribution.generations/<id>/distribution
└── .distribution.generations/
    ├── <previous-id>/
    └── <id>/
        ├── distribution/        # unchanged closed Atlas membership
        ├── parquet-view/        # omitted with --no-parquet-view
        ├── generation-report.json
        ├── generation-measurements.json  # optional, written after selection
        └── distribution-seal.json        # added by a later signing operation
```

The generation ID names a unique local directory; it does not change the
content-derived Atlas distribution ID or any published artifact identity.
Sibling selectors use separate stores derived from their own names.

## Build and consume

Use a fresh selection path when a real distribution directory already exists.
The builder refuses to replace or migrate existing real directories. Keep old
sealed outputs as historical evidence. Selection commands require a builder generation pointer.

```sh
uv run --frozen python tools/generate_atlas_v3_full.py --output scratch/release/distribution
selected=$(uv run --frozen python -m refspec.atlas.generation scratch/release/distribution)
# Keep $selected for the entire operation, including view and seal reads.
uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
  python bindings/atlas/3.1/tools/validate.py --distribution "$selected/distribution"
```

Python callers use the same selection once:

```python
from refspec.atlas.generation import select_atlas_generation

selected = select_atlas_generation("scratch/release/distribution")
# Pass selected.distribution, selected.parquet_view, selected.report and
# selected.seal to their existing independent consumers.
```

The seal CLI requires `--selection` and derives the view and detached seal
from that one generation. Separate distribution, view, output and seal path
arguments are unsupported. The audit target requires an explicit selector
(`ATLAS_V3_AUDIT_ROOT`) and the benchmark target defaults to the Federal
Register release selector (`ATLAS_SHACL_BENCH_ROOT`); neither infers a
distribution from a parent directory. The seal Make targets require
`SEAL_ROOT`, a release root whose `distribution` is a selector. The standalone
binding validator continues to reject symlink roots; callers supply the
concrete selected distribution. Copy or transfer the selected artifacts
together, preserving their sibling layout, and retain existing external
manifest pins.

Releases built before selection, with a real `distribution/` directory, remain
historical evidence. The seal CLI and Make targets refuse them; verify one by
passing its concrete paths to `refspec.seal.verify_seal`.

The selection helper reads one symlink and checks a fixed set of path metadata.
It does not read RDF packs, parse a generation report, establish acceptance,
or authenticate bytes. Existing manifest, view, signature, closed-membership,
and independent semantic checks still apply. A producer-written success value
never substitutes for those checks.

## Failure and concurrency rules

The builder stages in its own temporary directory, retains a complete
uniquely named generation, and replaces the selection with one POSIX rename.
Only the last step changes what new readers select. Concurrent writers own
separate staging paths and temporary symlinks; the last selection replacement
wins. That rule provides coherence, not version monotonicity or freshness.

Distribution, view and report bytes remain unchanged after selection under
trusted local owner custody. Diagnostics and a detached seal may be added
beside them later. A diagnostic write error reports that selection succeeded
and does not roll it back. Signing and independent release qualification
remain separate operations.

Old generations, their seals, and completed but unselected generations stay
available. Process termination can leave staging directories or a temporary
selection symlink; restart uses fresh names and leaves those files untouched.
There is no automatic cleanup or reuse of interrupted candidates. Retention
therefore consumes storage over successive builds; cleanup is a separate
explicit operation that must preserve pinned readers and required evidence.

The one exception is the disposable gate inputs that `make test` rebuilds on
every run (the Federal Register release, UMTHES and agency roots). Their Make
targets clear only the root's builder-owned selection (the selector symlink,
its generation store and stale temporary links) before a cold rebuild, so
repeated runs retain no prior generations and use constant disk. They never
delete a root wholesale: a real `distribution/` directory is left for the
builder to refuse, so a pre-selection release at a gate root must be moved
aside once by its owner. Release roots (`output/atlas-3.1-full-<suffix>`) are
unique per run and keep every generation.

These guarantees cover process failures on a trusted local POSIX filesystem.
They do not claim power-loss durability, protection from an owner editing
retained files, or distributed/network-filesystem rename semantics.

## Bounded verification

`tests/test_atlas_generation_selection.py` injects view, report, retention,
and pointer failures; kills fresh child interpreters at publication
transitions; restarts after interruption; and exercises concurrent readers,
concurrent writers, sibling selectors, no-view output, retained seals and
post-selection diagnostic failure. Its marker files isolate filesystem
behavior and make no semantic conformance claim. The tiny synthetic Atlas
build in `tests/test_generate_atlas_v3_full.py` and the independent seal tests
retain the actual artifact checks.

The deterministic comparator requires two selector paths and pins each generation
once and compares its contents, excluding random directory IDs and history.
It still includes the distribution, view and report and compares optional
measurements by their existing JSON-shape rule.

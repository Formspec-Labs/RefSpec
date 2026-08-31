# spicy-regs nuggets — committed evidence home (2026-08-27 extraction)

Committed home for the "nuggets" evidence that RefSpec's reimplemented
ontology/registry modules and `plans/2026-08-31-refspec-intake-ledger.md` cite
by file and line. It replaces the staging path
`~/Work/corpora/_nuggets-2026-08-27/`, which is temporary corpora scratch, not
a durable citation target. This follows the same doctrine that put the
Wayback EO capture bytes in-repo: **evidence cited by shipped code lives in
the repo that cites it.**

This directory is **reference, never payload**. Nothing here is imported,
built from, or shipped by RefSpec. It exists so that a citation like
`ontology/citations.py:384-604` in a module docstring, a decision record, or
the intake ledger can be resolved to real bytes by a future reader, forever —
even after `~/Work/corpora/` is pruned or reorganized. The platform rule is
**reimplement, never copy** (DocSpec spec §4.4, generalized platform-wide):
every RefSpec module built from this evidence is an independent
reimplementation, checked against RefSpec's own tests, not a port of this
code.

## What's here

| Path | What it is |
| --- | --- |
| `source-snapshots/` | The four digest-pinned archives of the `spicy-regs` / `spicy-regs-landing` source trees that the twelve-agent archive-surface sweep reviewed on 2026-08-27, plus the sweep's own `README.md` and `SHA256SUMS` for them. |
| `sweep-receipts/` | The sweep's own audit trail: root `README.md`, `MANIFEST.tsv`, `SHA256SUMS`, the `closure/` disposition ledger (272 findings, one preservation disposition each, plus `AUDIT.md`), and the twelve distilled `reports/*.md` (one per review area). |
| `NUGGETS-README.md` | Verbatim copy of `_nuggets-2026-08-27/README.md` — the ranked nugget index (Rank 1 absent-from-all-repos, Rank 2 superseded-but-partially-lost, Rank 3 paused) that `plans/2026-08-31-refspec-intake-ledger.md` names as its measurement provenance. Renamed only to avoid clashing with this file. |
| `invariants.py` | `spicy_regs/ontology/invariants.py` (`assert_acyclic` and friends), copied separately — see below. |
| `MANIFEST-sha256.csv` | sha256 + byte count for every file in this directory (this file and itself excluded). |

Total footprint is ~23 MB, almost all of it the four archives (22.7 MB); well
under GitHub's per-file and repo-bloat thresholds.

### What was deliberately left out

- `~/Work/corpora/_nuggets-2026-08-27/receipts/` (top level: a candidate-selector
  BM25 ablation and a segmentation/rerank experiment, with parquet payloads).
  Nothing in RefSpec or the intake ledger cites these paths — they document a
  retrieval-ranking experiment, not the ontology/registry source this evidence
  home backs. Left in corpora; not this citation chain.
- `sweeps/2026-08-27-archive-surface/raw/out{1..12}.txt` (~24 MB of raw agent
  session transcripts). These are the unprocessed traces the sweep's
  `reports/*.md` were distilled from — process record, not cited evidence.
  `sweep-receipts/MANIFEST.tsv` still records each trace's scope, session ID,
  and sha256 for anyone who needs to go back to `~/Work/corpora/` for the raw
  transcript.
- The `_preserved-2026-08-27/` output-tree preservation (11+ GB of ignored
  `spicy-regs/output/`, landing output, etc.), named in `sweep-receipts/README.md`
  and `closure/README.md` but never in scope here — a separate, much larger
  preservation effort that nothing in RefSpec cites by path.

Nothing in `~/Work/corpora/` was deleted or modified to produce this
directory.

## How the tarballs relate to the retired loose `source/` tree

`~/Work/corpora/_nuggets-2026-08-27/source/` is a **curated, unmanifested
26-file excerpt** — not a full mirror. Its own README states the origin
precisely: `~/Work/spicy-regs`, branch `integrate/payload-prereqs` @ `c00df53`
plus uncommitted working-tree edits, with paths under `source/` mirroring
their original repo paths. It carries no manifest and no digest, which is
exactly why it was staging, not evidence.

`source-snapshots/spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` is a
**complete tracked-tree export** (930 files) of the same branch at a later
commit, `a6ab98aa35825ce993023ad9b237a28d04bb153e` — the point at which those
same uncommitted edits had been committed. Verified directly (byte-for-byte
`diff`) for every file checked: `ontology/citations.py`, `ontology/concepts.py`,
and `ontology/invariants.py` are identical between whichever copy of each
file exists and the tarball member of the same relative path. Where the loose
tree has a file, it is redundant with the tarball. **It does not have every
file the tarball has** — see the `invariants.py` note below — so "redundant"
undersells it: the loose tree is a subset, and an incomplete one is why one
citation broke.

`source-snapshots/spicy-regs-landing-main-31a4bfe.tar.gz` is the separate,
complete tracked tree of `spicy-regs-landing` @ `31a4bfe488c16e154fd98d7303e20cb7c033c764`
— the predecessor catalog (`source_catalog/`, metadata-complete universe,
schema-compatibility rule) that the `integrate/payload-prereqs` tree
superseded. Citations about the *landing* source-catalog package (report
`01-source-catalog.md`, `02-metadata-complete-diff.md`) resolve here, not in
the `-a6ab98a` archive.

The two `.bundle` files are re-clonable Git history, not source snapshots:
`spicy-regs-local-history-2026-08-27.bundle` carries both heads above plus
`refs/snapshots/pre-strip-2026-08-26`; `spicy-regs-legacy-branches-2026-08-27.bundle`
carries `backup/pre-marker-fix` and `feat/rkaf-boundary-freeze`, the two local
branches unreachable from the first bundle. Use these only if a citation
needs history (a commit message, a prior version of a file) rather than the
tracked-tree state at one commit.

## `invariants.py` provenance — the ledger's wrong-path item

`plans/2026-08-31-refspec-intake-ledger.md` §1.6 cites this file as
`_nuggets .../source/src/spicy_regs/ontology/invariants.py:14`. **That path
never resolved.** The loose `source/` tree's `ontology/` subdirectory holds
only `citations.py`, `concepts.py`, `relation_findings.py`, `ann_index.py`,
and `codex_cli.py` — `invariants.py` was never one of the 26 files copied out
before the branch was archived. The citation was built by assuming every
`ontology/*.py` file mirrored into `source/`; this one didn't.

The file does exist, byte-identical, in two other places:

1. `src/spicy_regs/ontology/invariants.py` inside
   `source-snapshots/spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` —
   the authoritative tracked-tree copy.
2. `~/Work/corpora/_salvage-2026-08-28/dead-session-scratch/dfe597f2-citation-bridge/greenfield-review/pkg/spicy_regs/ontology/invariants.py`
   — a scratch copy from an earlier greenfield-review session.

Both were diffed byte-for-byte against each other (clean, no output) before
either was trusted. The salvage copy is the one committed here as
`invariants.py`, so the reopen path in intake-ledger §1.6 now points at
committed bytes directly, with no tarball extraction required; the tarball
member above is the second, independently-verified copy of the same content.
`assert_acyclic` begins at line 14 in both, confirming the cited line number
still applies.

## Citation-translation rule

A module docstring, decision record, or the intake ledger citing a path under
`_nuggets-2026-08-27/source/...` (or the bare `spicy_regs/...` shorthand used
in `NUGGETS-README.md`'s appendix) now resolves as follows. Line numbers are
unchanged — the bytes are identical wherever both a source and a tarball copy
exist.

| Old corpora citation | Resolves to |
| --- | --- |
| `_nuggets-2026-08-27/source/src/spicy_regs/ontology/citations.py:384-604` | `src/spicy_regs/ontology/citations.py:384-604` inside `source-snapshots/spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` |
| `_nuggets-2026-08-27/source/src/spicy_regs/ontology/concepts.py:202-224,395-419,1223` | same member path inside `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` |
| `_nuggets .../source/src/spicy_regs/ontology/invariants.py:14` | committed directly at `invariants.py` (this directory); second copy at `src/spicy_regs/ontology/invariants.py` inside `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` |
| `_nuggets .../source/src/spicy_regs/sources/uscode_olrc.py`, `uscode_uslm.py` | `src/spicy_regs/sources/uscode_olrc.py` / `uscode_uslm.py` inside `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` |
| `_nuggets .../source/tools/build_agency_crosswalk_artifact.py`, `build_usc_act_index_artifact.py`, `build_usc_source_credit_artifact.py` | `tools/<same name>` inside `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` |
| Landing's `source_catalog/` package, `metadata-complete` universe, or schema-compatibility findings (`reports/01-source-catalog.md`, `reports/02-metadata-complete-diff.md`) | `src/spicy_regs/source_catalog/*.py`, `tools/build_source_catalog_universe.py`, `tools/publish_source_catalog_release.py` inside `source-snapshots/spicy-regs-landing-main-31a4bfe.tar.gz` — **not** the `-a6ab98a` archive |
| Any other `ontology/`, `docpipeline/`, `enrichment/`, `corpora/`, `vectordb/`, `transforms/`, `adapters/` path named in `NUGGETS-README.md` | same relative path inside `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` (it is the complete tracked tree for source-native, document-processing, ontology, evaluation, workflow, fixture, and tool findings, per `source-snapshots/README.md`) |
| A finding's disposition, evidence pointer, or the raw session it came from | `sweep-receipts/closure/dispositions*.tsv` (disposition + evidence path), `sweep-receipts/reports/NN-*.md` (distilled write-up), `sweep-receipts/MANIFEST.tsv` (session ID + sha256 of the excluded raw transcript) |

To read a cited member: `tar -xzf source-snapshots/spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz <member-path>` (no top-level directory prefix — members extract flat as `src/...`, `tests/...`, `tools/...`). The two `.bundle` files need `git clone` / `git bundle unbundle` instead of `tar`.

## Verification

Every archive's sha256 was checked against the sweep's own `SHA256SUMS`
**before** copying into this repo and **again after**, using the same digest
pins the sweep recorded on 2026-08-27 — nothing here was re-derived or
re-signed:

| Archive | sha256 | Verified before copy | Verified after copy |
| --- | --- | --- | --- |
| `spicy-regs-integrate-payload-prereqs-a6ab98a.tar.gz` | `b9cba0deae4e3e797e6b9da434603b7e479516fab11dabecee5c976f85887be8` | OK | OK |
| `spicy-regs-landing-main-31a4bfe.tar.gz` | `3880c88f5eb4c8f491810738b920cc749c92679c52cce712442d07dd6b359699` | OK | OK |
| `spicy-regs-legacy-branches-2026-08-27.bundle` | `2c329d97a18732e421080c0264bfdc5299c3d5538ed677f2c3518bc89e92fca4` | OK | OK |
| `spicy-regs-local-history-2026-08-27.bundle` | `58c8ff261a391b3dfff49387c0d1f71b8f9256cc02ce3d1c1209d7c245378e51` | OK | OK |

`sweep-receipts/SHA256SUMS` (the sweep's own root manifest, preserved
verbatim) itself hashes to `70c1b0adb2ae3a48526b10bbb8203dbc392154a8face23fe52b6d4048efb6dc6`,
matching the digest `sweep-receipts/README.md` records for it — confirmed by
re-hashing the copy in this directory. That manifest will not `shasum -c`
clean as a whole from inside `sweep-receipts/`: of its 36 entries, 18 verify
OK and 18 fail, and every failure is accounted for. 12 are the excluded
`raw/out{1..12}.txt` transcripts (see "What was deliberately left out"
above). The other 6 are its `source-snapshots/*` entries: at sweep time that
directory sat inside the sweep root, but in this home it is a sibling — all
6 files verify OK against the same pinned digests at `../source-snapshots/`
(re-checked 2026-08-31). The manifest is preserved as the sweep's own
historical record, not as a checklist over this subset;
`MANIFEST-sha256.csv` in this directory is the actual manifest for what is
committed here.

The same verbatim-preservation rule leaves some links in the copied records
pointing at their original homes: the twelve `reports/*.md` cite live
checkouts by absolute `/Users/.../<file>:<line>` path (the sweep's citation
style — machine- and time-specific by nature), `sweep-receipts/README.md`
still says `source-snapshots/` (now `../source-snapshots/`) and names the
`_preserved-2026-08-27/` corpora tree that was never in scope here, and
`NUGGETS-README.md` links its old `sweeps/2026-08-27-archive-surface/`
neighbor. None of these was rewritten — editing a preserved record would
break its recorded digests — so resolve them through the
citation-translation rule above instead of following them literally.

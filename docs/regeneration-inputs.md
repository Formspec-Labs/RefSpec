<!-- markdownlint-disable MD013 -->

# Regeneration inputs that live outside the repository

This register names the corpora paths RefSpec's builders and pins depend on
but that deliberately do **not** move into the repository. `~/Work/corpora/`
is the durable home because gitignored in-repo output trees were destroyed
repeatedly; the platform's measured failure mode is loss, never tamper. The
intake ruling behind this page is §4 of
[`plans/2026-08-31-refspec-intake-ledger.md`](../plans/2026-08-31-refspec-intake-ledger.md).

This is not the [research-input register](research-inputs.md), which pins the
editor's-draft portfolio baseline. This page is operational: what a rebuild
reads, and what is lost if a path below is moved or deleted.

## The register

| Corpus path (under `~/Work/corpora/`) | Contents | RefSpec relationship |
| --- | --- | --- |
| `_salvage-2026-08-28/refspec-output/` | original 302k-row act index, ~120 dated Zyte/Wayback/bulk registry captures, GAO execution receipts, claim releases, view pins, vocabulary portfolio | outputs and pins with no or expensive regeneration |
| `_salvage-2026-08-28/refspec-output/ecfr-title-xml-2026-08-24` | 773M, 52 files, manifest + fetch log | refetchable but **not re-pinnable**: a refetch is a different capture day |
| `_salvage-2026-08-28/refspec-output/usc-annual-2026-08-24` | 2.1G, 73 files — 32 zips per the fetch log (31 annual XHTML editions 1994–2024, which carry no USLM, plus the one USLM member); the rest are listings, oracle parquets and fetch scripts; all 32 zips re-hashed clean 2026-08-31 | the one USLM member, `xml_uscAll_119-102.zip` (108MB, sha256 `55c8d195…`, the same bytes the frozen artifact's receipt pins), feeds `tools/build_usc_source_credits.py` (intake ledger §1.4; the ledger's "2.1G feeds the parser" claim measured wrong 2026-08-31) |
| `_salvage-2026-08-28/refspec-output/atlas-3.1-full-2026-08-21d` | 2.0G full atlas build | parent of the newest search view |
| `atlas-3.1-parquet-search-view-{2026-08-17,-20,-21b,-21c}` | Parquet search views | **pinned by exact path in SpicySearch tests** (`-2026-08-17`, `-20`, `-21b`, `-21c` — verified 2026-08-31; the earlier "`-21b` appears unpinned" was backwards: **`-21d` is the unpinned one**) — do not move or delete without re-pointing them. Sharper hazard, measured: `-21b`, `-21c` and `-21d` carry distinct viewIds over **the same eleven inodes** (hardlinks), so an in-place write through any path mutates all three at once, two of them test-pinned |
| `_preserved-2026-08-27/vocabulary-atlas` | 8 atlas versions incl. hand-audited v5-audited | lineage evidence |
| `_preserved-2026-08-27/fused-concept-registry-v1` | 513,236-concept fusion incl. LLM-minted terms | lineage evidence, 15+ downstream citations |
| `_preserved-2026-08-27/spicy-regs-output-complete/agency-crosswalk-2026-08-02/` | sealed agency-crosswalk artifact + receipt (tier histogram over 715,080 FR-docket-link rows) | reference data behind `registry/agency_crosswalk` (intake ledger §1.5) |
| `_preserved-2026-08-27/rin-ontology-revision-candidate/` | the sealed crosswalk's four input parquets | **already partially lost, and worse than first recorded** (full sweep 2026-08-31): `fr_docket_links.parquet` was overwritten after the 2026-08-02 build (893,766 rows vs the pinned 715,080), the original bytes were found **nowhere under ~/Work** (all twenty copies hashed across both output trees carry the overwritten digest; 36 manifests pin a digest no file satisfies), the correct pin sat unread the whole time in `ontology-dataset-manifest.json`'s `.inputs.sources` block in the same directory, and the 2026-08-27 tree-wide SHA256SUMS **ratified** the corrupted digest as truth. Recorded in `agency_crosswalk.AGENCY_CROSSWALK_REGENERATION_STATUS` |
| `_nuggets-2026-08-27/` | archived spicy-regs source + sweep receipts | evidence and reference for every reimplemented port — never a payload |
| `refspec-registry-unified-agenda-parquet/` | receipted export of `registry/unified_agenda_parquet.py` | durable pin; regenerable; fine where it sits |

## The in-repo counterpart

The same doctrine covers evidence already inside the repository: sixteen of
the 32 Executive Order gap numbers (1,173 corpus rows, EO 12866 among them)
resolve **only** from Wayback captures whose bytes exist nowhere but the
committed `research/evidence/investigations-2026-08-24/inv-eo`/`inv-eo-gap`
directories, sha256-manifested. Those directories are pinned publisher
evidence, not prunable research
(see [`research/investigations-mined-2026-08-31.md`](../research/investigations-mined-2026-08-31.md)).

## What the 2026-08-31 durability sweep established

Every register path was re-hashed against its own manifests the same day
this page was written (2,354 entries, ~14 GB): **one true mismatch** (the
`fr_docket_links` row above), zero other losses — every other absence
resolves to a build-time `/tmp` path, a remote-snapshot record, or three
in-repo research files manifested but never committed
(`inv-frvol/analysis.duckdb`, `inv-frvol/raw/govinfo_fr_2020-12-31.pdf`,
`inv-initialisms/raw/popularnames.htm`). The structural findings that
outlive the sweep:

- `vocabulary-atlas`, `fused-concept-registry-v1` and
  `rin-ontology-revision-candidate` have **no manifest under their own
  registered path**; they verify only by proxy against an undeclared
  duplicate copy under `spicy-regs-output-complete/` (different inodes,
  ~9.4 GB duplicated). The register's durability there depends on a
  manifest that names a different directory.
- The two 1.6 GB dense-index `.npz` files in `fused-concept-registry-v1`
  and the 69-file Ladybug projection carry **no digest in any manifest**.
- The overwrite lesson, stated as a rule: verification must read
  `.inputs.sources` blocks, not just `.artifacts`; a tree-wide manifest
  must **refuse to record a digest another manifest already pins
  differently** (that is how a detectable regression became a ratified
  one); and this sweep should re-run on a schedule, not once.

## The rule

A path in this register is an input, not an archive. Before moving, renaming,
or pruning one: find every receipt, test, or builder flag that names it (the
SpicySearch search-view pins above are the known sharpest edge), re-point
them first, and record the move here in the same change.

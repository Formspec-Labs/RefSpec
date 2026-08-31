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
| `_salvage-2026-08-28/refspec-output/usc-annual-2026-08-24` | 2.1G, 73 files, per-file SHA-256 — but 72 are `annualhistoricalarchives` **XHTML** editions (1994–2024), which carry no USLM | the one USLM member, `xml_uscAll_119-102.zip` (108MB, sha256 `55c8d195…`, the same bytes the frozen artifact's receipt pins), feeds `tools/build_usc_source_credits.py` (intake ledger §1.4; the ledger's "2.1G feeds the parser" claim measured wrong 2026-08-31) |
| `_salvage-2026-08-28/refspec-output/atlas-3.1-full-2026-08-21d` | 2.0G full atlas build | parent of the newest search view |
| `atlas-3.1-parquet-search-view-{2026-08-17,-20,-21c}` | Parquet search views | **pinned by exact path in SpicySearch tests** — do not move or delete without re-pointing them; `-21b` appears unpinned; several dirs share content via hardlinks, so `du` under-reports them |
| `_preserved-2026-08-27/vocabulary-atlas` | 8 atlas versions incl. hand-audited v5-audited | lineage evidence |
| `_preserved-2026-08-27/fused-concept-registry-v1` | 513,236-concept fusion incl. LLM-minted terms | lineage evidence, 15+ downstream citations |
| `_preserved-2026-08-27/spicy-regs-output-complete/agency-crosswalk-2026-08-02/` | sealed agency-crosswalk artifact + receipt (tier histogram over 715,080 FR-docket-link rows) | reference data behind `registry/agency_crosswalk` (intake ledger §1.5) |
| `_preserved-2026-08-27/rin-ontology-revision-candidate/` | the sealed crosswalk's four input parquets | **already partially lost**: `fr_docket_links.parquet` was overwritten in place after the 2026-08-02 build (893,766 rows now vs the pinned 715,080), so the sealed crosswalk can no longer be exactly re-derived — measured 2026-08-31, recorded in `agency_crosswalk.AGENCY_CROSSWALK_REGENERATION_STATUS`. The failure mode this register exists for, caught in the act |
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

## The rule

A path in this register is an input, not an archive. Before moving, renaming,
or pruning one: find every receipt, test, or builder flag that names it (the
SpicySearch search-view pins above are the known sharpest edge), re-point
them first, and record the move here in the same change.

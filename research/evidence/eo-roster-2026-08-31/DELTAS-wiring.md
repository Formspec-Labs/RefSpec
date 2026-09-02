# EO fence wiring — declared receipt deltas

EO-fence-wiring lane, correctness wave 2026-09-01. Mission: apply
`WIRING-SPEC.md` in this directory to `src/refspec/registry/unified_agenda_parquet.py`
— upgrade `_SeriesCalendar.eo_in_known_series` from a bare range check to
range-check-first + `EoRosterOracle` refinement. This file is the DECLARED
set of receipt-key moves the integrator's next combined rebuild should
attribute to this lane. Every number below is measured against a real
artifact in `output/registry-real-data-sources/unified-agenda-parquet/` —
each measurement says WHICH one and when, because the tree carried the
pre-wiring artifact when this was written and the wave's post-wiring
intermediate rebuild minutes later — either by re-running the evidence
home's own `measure.py` (reads the roster through the shipped oracle,
against the investigation's committed `cited-eo-census.csv`) or by querying
the artifact directly with DuckDB — never by copying WIRING-SPEC.md's own
numbers uninspected.

## What shipped

`src/refspec/registry/unified_agenda_parquet.py` — all seven diffs from
`WIRING-SPEC.md`, applied at their current (drifted) sites, located by
content per the spec's own instruction rather than by its stale line numbers:

- **Diff 1** — `from refspec.registry.eo_roster import EO_ROSTER_ARTIFACT, EoRosterOracle`.
  Placed between the `citation_grammar` and `unified_agenda_editions` import
  blocks, not literally "after `usc_section_oracle`" as the spec's stale
  line reference said — this file's `from refspec.registry.*` imports are
  alphabetical by module (`act_resolution`, `cfr_authority_notes`,
  `citation_grammar`, `unified_agenda_editions`, `usc_disposition_tables`,
  `usc_section_oracle`) and ruff's `I` (isort) rule is selected in
  `pyproject.toml`, so alphabetical placement is the only one that is both
  ruff-clean and consistent with the file's own convention. Only
  `EO_ROSTER_ARTIFACT` and `EoRosterOracle` are imported, per the spec's own
  warning: `eo_roster` defines its own `VERDICTS`/`UNKNOWN_REASONS`, already
  bound in this module to `usc_section_oracle`'s constants of the same name.
- **Diff 2** — `_EO_ROSTER_DIR` constant and `_eo_roster_oracle()` loader.
  The constant is placed after `_INITIALISM_ROSTER_FIELDS` (end of the
  directory/file-constant group), matching the sequential "Nth oracle found
  relative to this file" numbering the surrounding comments already use
  (CFR authority notes = fourth, initialism roster = fifth) — the spec's own
  comment text calls this one "the sixth oracle", which only reads true
  planted there. The loader function is placed directly after
  `_usc_section_oracle()`, exactly as the spec asked (no drift in that
  slot's ordering rationale — these loaders are ordered by dependency, not
  by oracle number, and `_eo_roster_oracle()` has no dependents in this
  module to order around).
- **Diff 3** — `_SeriesCalendar` gained an `eo_oracle: EoRosterOracle | None = None`
  field, appended AFTER the existing `pl_approved_in` field (a field this
  class already carries that the spec's draft predates — the class now has
  five fields, not four). `build()` gained a keyword-only `eo_oracle`
  parameter threaded into both return paths. `eo_in_known_series` converted
  from `@staticmethod` to an instance method: the range check
  (`1 <= n <= EO_HIGHEST_KNOWN`) still runs first and alone decides every
  out-of-range number; only an in-range number is hedged to
  `self.eo_oracle.verdict(number)`, mapping `exists -> True`,
  `absent -> False`, `unknown -> None`. Absent an oracle, `True` for every
  in-range number, unchanged from before this wiring.
- **Diff 4** — the sole `_SeriesCalendar.build(pl_roster)` call site (inside
  `build_unified_agenda_parquet`, now at the point where `calendar` is
  constructed) threads `eo_oracle=_eo_roster_oracle()`.
- **Diff 5** — `eoUnknownRows` receipt key added beside `eoOutOfSeriesRows`,
  counting rows where `eo_in_known_series is None and executive_order is not None`.
- **Diff 6** — `_EO_ROSTER_DIR` added to `main`'s missing-oracle build
  refusal list (the `is_dir()` group alongside `_USC_SECTION_ORACLE_DIR`,
  `_USC_DISPOSITION_TABLES_DIR`, `_USC_SOURCE_CREDIT_DIR`). Not skipped —
  the spec is explicit this is the diff that keeps the wiring from failing
  open, and its own README records the 2026-08-22 precedent of a build that
  silently answered from a missing oracle and passed `--verify`.
- **Diff 7** — `"eo_roster"` added to `_PRODUCER_MODULES`;
  `"eo-roster-2026-08-31/derived/roster.csv": digest(_EO_ROSTER_DIR / "derived/roster.csv")`
  added to `_producer_block()`'s `"oracles"` map.

`tests/test_unified_agenda_parquet.py` — two new tests, additive only, no
existing literal re-pinned:

- `test_eo_in_known_series_consults_the_roster_oracle_after_the_range_check` —
  binds the real pinned oracle and holds three properties, each one a
  regression this test would catch: an out-of-range number (`999999`) reads
  `False` even though the oracle itself calls it `unknown` (the range check
  runs first and the oracle is never consulted for it); an oracle-affirmed
  in-range number (EO 12866, `exists`) still reads `True`; an in-range,
  real, famous number the sparse NARA codification window does not
  enumerate (EO 9397, `unknown`) reads `None` — silently `True` before this
  wiring.
- `test_a_build_refuses_without_the_eo_roster_directory` — mirrors the
  existing `test_a_build_refuses_without_its_pinned_oracles` pattern:
  monkeypatches `_EO_ROSTER_DIR` to a path that does not exist and asserts
  `main()` exits 2, names that path in stderr, and writes nothing.

`tests/test_eo_roster.py` — untouched by this lane. It already anticipated
the conversion (`_SeriesCalendar.build(None).eo_in_known_series(str(number))`,
not a class-level call) and already carries
`test_measured_against_the_cited_eo_census`, which reproduces the
corpus-wide numbers below directly from the shipped module.

`research/evidence/eo-roster-2026-08-31/MANIFEST-sha256.csv` — an entry for
this very file added (`DELTAS-wiring.md`, its own byte count and sha256,
alphabetically ordered before `README.md`; not restated in this prose,
which would go stale the moment this file is edited again — read the
manifest row itself). Not optional: this directory is sealed with a
two-way inventory test
(`test_the_evidence_home_manifest_is_a_two_way_inventory`) that fails on any
unlisted file on disk, and dropping this deliverable in without manifesting
it broke that test on first run — caught before this report was written,
not after.

## Declared receipt deltas

Measured three ways, in agreement (the third added 2026-09-01 when the
wave's intermediate rebuild landed a post-wiring artifact to read):

**1. `research/evidence/eo-roster-2026-08-31/measure.py`** (reads the roster
through the shipped `EoRosterOracle`, against the investigation's
digest-bound `cited-eo-census.csv`, 391 numbers / 19,011 rows):

```
COVERED (verdict=exists): 378 numbers / 18954 rows
UNCOVERED: 13 numbers / 57 rows
  'nara_window_miss': 10 numbers / 50 rows -> [1197, 1205, 1220, 1223, 1293, 1327, 1338, 3019, 3891, 7419]
  'outside_known_windows': 3 numbers / 7 rows -> [20450, 21600, 23891]
measured (this script): {'numbers_covered': 378, 'rows_covered': 18954, 'numbers_unknown': 10}
```

**2. The pre-wiring BASELINE, measured by direct DuckDB query**
(`output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet`
**as of 2026-09-01 ~21:15**, when this report was written — the artifact then
in the tree was built by the pre-wiring code, so it still reflected the bare
range check. It has since been rebuilt; see the confirmation below, which is
why this block is dated rather than re-run):

```sql
select count(*) from L where executive_order is not null;                    -- 19011
select count(*) from L where eo_in_known_series = true;                      -- 19004
select count(*) from L where eo_in_known_series = false;                     -- 7
select count(distinct executive_order) from L where eo_in_known_series = true;  -- 388
select count(distinct executive_order) from L where eo_in_known_series = false; -- 3 ([20450, 21600, 23891])
```

388 numbers / 19,004 rows read `True` on that baseline. This wiring moves 10
of those 388 numbers (50 of those 19,004 rows) to `None`: 388 − 10 = 378 and
19,004 − 50 = 18,954, matching `measure.py` exactly. The 3 numbers / 7 rows
already `False` are untouched (no `absent` verdict exists on this roster,
so `eoOutOfSeriesRows` cannot move either).

**3. Confirmed against a post-wiring artifact.** The wave's intermediate
rebuild landed at **2026-09-01 21:18:58** (`receipt.json` mtime; the four
Parquet files carry 21:18:39–21:18:50), three minutes after the baseline
above, and it carries the wiring. Re-queried against that artifact:

```sql
select count(*) from L where executive_order is not null;                       -- 19011
select count(*) from L where eo_in_known_series = true;                         -- 18954  (378 numbers)
select count(*) from L where eo_in_known_series = false;                        -- 7      (3 numbers)
select count(*) from L where eo_in_known_series is null
                         and executive_order is not null;                       -- 50     (10 numbers)
-- receipt.json contract.declaredClassifications:
--   "eoOutOfSeriesRows": 7,  "eoUnknownRows": 50
```

Every predicted number arrived exactly: `eoUnknownRows` now EXISTS in the
receipt at 50, `eoOutOfSeriesRows` did not move, and the 19,011-row EO
population splits 18,954 / 7 / 50 with no `True -> False` flip. The
authoritative receipt is still the wave's FINAL integration rebuild — this
intermediate one predates the other lanes' merges — but the prediction below
is no longer a prediction awaiting a build; it has been observed once, and
the final rebuild is now a re-confirmation rather than a first measurement.

| Metric | Predicted (WIRING-SPEC.md) | Measured (this lane) | Match |
|---|---|---|---|
| `eoOutOfSeriesRows` | 7 (unchanged) | 7 | yes |
| `eoUnknownRows` (new) | 50 rows / 10 numbers | 50 rows / 10 numbers | yes |
| `True -> False` flips | 0 | 0 | yes |
| `True -> True` (unchanged) | 378 numbers / 18,954 rows | 378 numbers / 18,954 rows | yes |

No reconciliation needed — the spec's own predicted table held exactly, three
ways: the census-based measurement, the arithmetic against the pre-wiring
baseline, and the post-wiring artifact of 2026-09-01 21:18:58, which declares
the two receipt keys at 7 and 50.

## Deliberate divergences from the spec's literal text

- **Import placement** (Diff 1): alphabetical, not "after `usc_section_oracle`"
  — see above. Same imported names, same exclusion of `eo_roster`'s own
  `VERDICTS`/`UNKNOWN_REASONS`.
- **Constant placement** (Diff 2): `_EO_ROSTER_DIR` sits after
  `_INITIALISM_ROSTER_FIELDS`, not "after `_USC_SECTION_ORACLE_DIR`" — the
  spec's own explanatory comment ("the sixth oracle") only makes sense read
  at the end of the five-oracle sequence the surrounding comments already
  count through.
- **`_SeriesCalendar` field count**: the spec's Diff 3 was written against a
  three-field class (`congress_by_year`, `volume_by_year`,
  `usc_title_from_year`); this checkout's class already carries a fourth,
  `pl_approved_in` (`field(default_factory=dict)`), predating this lane.
  `eo_oracle` is the fifth field, appended after `pl_approved_in`, and both
  `build()` return paths pass it by keyword (`eo_oracle=eo_oracle`) rather
  than positionally, so the insertion cannot silently shift `pl_approved_in`
  into the wrong slot.
- **`main`'s `calendar = _SeriesCalendar.build(pl_roster)` call site**: at a
  different line than the spec's stale reference (inside
  `build_unified_agenda_parquet`, not "line 7526"), located by content
  (`grep -n "_SeriesCalendar.build("`) rather than by line number, per the
  brief.

No divergence changes behavior from what the spec specifies; every one is a
placement choice forced by drift since the spec was written, resolved in
favor of this file's own pre-existing conventions (alphabetical imports,
oracle-count-ordered comments, keyword-safe dataclass construction).

## What this lane deliberately did not touch

- `citation_grammar.py`'s `EO_HIGHEST_KNOWN` — untouched, exactly as the
  spec directs; the range check still reads it directly.
- `eo_roster.py` itself, `usc_section_oracle.py`, `cfr_authority_notes.py`,
  `tools/`, `docs/decisions.md` — forbidden to this lane, untouched.
- The shared rebuild. `output/` is untouched by this lane (`git status
  --porcelain output/` is empty); every number above is either a read-only
  replay of the evidence home's own `measure.py` or a read-only DuckDB
  query against the artifact this checkout already carries.
- `tests/test_eo_roster.py` — already correct for the post-conversion
  instance-method shape; no edit needed or made.

## Reproduction

```
.venv/bin/python research/evidence/eo-roster-2026-08-31/measure.py
.venv/bin/python -m pytest tests/test_eo_roster.py tests/test_unified_agenda_parquet.py -q
.venv/bin/python -m ruff check src/refspec/registry/unified_agenda_parquet.py tests/test_unified_agenda_parquet.py
```

Test run at the time of this writing (2026-09-01 ~21:15, pre-rebuild): 177
passed, 1 failed (`test_the_receipt_names_the_code_that_wrote_it` — the
wave-wide, pending-combined-rebuild failure the brief names as not this
lane's to fix; this lane's own `"eo_roster"` addition to `_PRODUCER_MODULES`
is one more frozen-set mismatch stacked on the B8 lane's pre-existing one,
both closed by the same integrator rebuild). Ruff clean on both files this
lane owns.

**Re-run after review (2026-09-01, post-intermediate-rebuild):**
`tests/test_eo_roster.py` 38 passed. `tests/test_unified_agenda_parquet.py`
128 passed / 12 failed, and every one of the 12 is a count another lane owns,
re-measured against the 21:18 artifact rather than anything this lane wrote:
the table is 800,567 rows against a pinned 800,573, the U.S.C. note-verdict
census moved (`present` 476,021 -> 475,998), `statedActRowsStatingSomething`
reads 922 against a pinned 915, and the producer-digest test is still red
until the final rebuild. The identical 12 fail with this lane's own test
additions removed, so none of them is this lane's; they close with the
integrator's rebuild and the owning lanes' re-pins. Every EO test and the
receipt census pass.

## Caveat for the integrator

Read the two artifact measurements above for what each one is. The first is a
**dated baseline** (2026-09-01 ~21:15): the pre-wiring artifact this checkout
carried when this report was written, describing what `eo_in_known_series`
said BEFORE the wiring, which is the thing the deltas are deltas from. It is
deliberately not re-run, because the artifact underneath it has moved.

The second is the wave's **intermediate rebuild** (2026-09-01 21:18:58),
which does run `_eo_roster_oracle()` for real and does carry `eoUnknownRows`
in `receipt.json`, at the predicted 50 rows / 10 numbers with
`eoOutOfSeriesRows` unmoved at 7. That retires the "will not exist until the
rebuild" caveat this section used to carry.

What remains for the integrator is smaller but still real: the intermediate
rebuild predates the other lanes' merges, so the **final integration rebuild
is the authoritative receipt**. Re-run `measure.py` against it and diff the
output against this file's table — a sibling lane's change to authority
parsing could in principle move which rows carry an `executive_order` at all,
which would move both counts without any EO logic changing. The census
assertion in `test_the_receipt_census_agrees_with_the_table_it_describes`
recomputes `eoUnknownRows` from the table on every run, so that drift arrives
as a named test failure rather than as a silently restated number.

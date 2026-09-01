# Wiring spec: upgrade the EO fence to `eo_roster.EoRosterOracle`

**Not applied by this lane.** Ground rule for this wave: `citation_grammar.py`
and `unified_agenda_parquet.py` are owned by another lane. This is the exact
diff a follow-up unit should apply, with predicted verdict-count deltas
measured against the current build's own census
(`research/evidence/investigations-2026-08-24/inv-eo/derived/
cited-eo-census.csv`, 391 numbers / 19,011 rows — the same population
`measure.py` and `tests/test_eo_roster.py` reproduce). All line numbers are
current as of this commit.

## Design: the cheap range check stays, the oracle only refines

`eo_in_known_series` today is a bare `1 <= n <= EO_HIGHEST_KNOWN` range check.
That check should **stay in place, first, unchanged** — it is what protects
against a five/six-digit typo (`20450`, `21600`, `23891`) cheaply and without
depending on the roster at all. Only a number that PASSES the range check is
handed to the oracle for a finer answer:

* oracle `exists` → `True` (same value the range check alone already gave —
  no behavior change for the 378 covered numbers / 18,954 rows);
* oracle `absent` → `False` (a genuine, measured absence — inside the dense
  FR-API window only; **0 rows** in the current cited population hit this
  branch, and in fact no roster that loads can reach it at all today, because
  the density guard that licenses `absent` is the same fact that leaves the
  window no misses — see README.md);
* oracle `unknown` → `None` (honest — was silently `True` before; **50 rows /
  10 numbers** in the current cited population move here).

`eo_in_known_series`'s field type is already `bool | None`
(`pa.field("eo_in_known_series", pa.bool_(), nullable=True)`, line 576) — no
schema change is needed.

## Diff 1 — import `EoRosterOracle`

**File:** `src/refspec/registry/unified_agenda_parquet.py`, after the existing
`usc_section_oracle` import block (lines 109–118).

```python
 from refspec.registry.usc_section_oracle import (
     CORRECTION_RULES,
     UNKNOWN_REASONS,
     USC_SECTION_ORACLE_ARTIFACT,
     VERDICTS,
     ActSectionClaim,
     SectionVerdict,
     UscSectionOracle,
     normalize_section,
 )
+from refspec.registry.eo_roster import EO_ROSTER_ARTIFACT, EoRosterOracle
```

`VERDICTS` and `UNKNOWN_REASONS` are already bound to `usc_section_oracle`'s
constants in this module — `eo_roster` defines its own same-named constants,
so import ONLY `EO_ROSTER_ARTIFACT` and `EoRosterOracle` here, not the
constants, to avoid a silent rebind.

## Diff 2 — the loader, mirroring `_usc_section_oracle()`

**File:** same, after `_USC_SECTION_ORACLE_DIR` (line 1221) and after
`_usc_section_oracle()` (lines 1258–1269).

```python
 _USC_SECTION_ORACLE_DIR = Path(__file__).resolve().parents[3] / USC_SECTION_ORACLE_ARTIFACT
+#: The sixth oracle found relative to this file, with the same sharp edge as
+#: the other five: absent, `eo_in_known_series` silently falls back to the
+#: bare range check and `eoUnknownRows` reads 0 on an artifact that never
+#: consulted a roster. Diff 6 adds it to `main`'s refusal for that reason.
+_EO_ROSTER_DIR = Path(__file__).resolve().parents[3] / EO_ROSTER_ARTIFACT
```

```python
 def _usc_section_oracle() -> UscSectionOracle | None:
     """..."""
     if not _USC_SECTION_ORACLE_DIR.is_dir():
         return None
     return UscSectionOracle.from_directory(_USC_SECTION_ORACLE_DIR, dispositions=_usc_disposition_tables())


+def _eo_roster_oracle() -> EoRosterOracle | None:
+    """The pinned EO existence roster, or None where this tree lacks it.
+
+    Optional by the same convention as every other oracle in this module --
+    and, like them, not optional for a BUILD: `main` refuses to build without
+    the directory, because a build that silently answers with the bare range
+    check writes an artifact whose `eo_in_known_series` column means something
+    different from the one beside it.
+    """
+
+    if not _EO_ROSTER_DIR.is_dir():
+        return None
+    return EoRosterOracle.from_directory(_EO_ROSTER_DIR)
+
+
 def _cfr_authority_notes() -> CfrAuthorityNotes | None:
```

## Diff 3 — `_SeriesCalendar`: carry the oracle, consult it

**File:** same, lines 1424–1440 (fields + `build`) and lines 1527–1533
(`eo_in_known_series`).

```python
     #: year -> the highest congress that had enacted a law by the end of it.
     congress_by_year: Mapping[int, int]
     #: year -> the highest Statutes at Large volume published by the end of it.
     volume_by_year: Mapping[int, int]
     #: U.S.C. title -> the first year it existed.
     usc_title_from_year: Mapping[int, int]
+    #: The EO existence oracle, where this tree carries it. Optional and
+    #: undated, like the rest of this field's undated-on-purpose EO story
+    #: (see the class docstring) -- it refines `eo_in_known_series` beyond
+    #: the bare range check without adding a dependency this calendar's
+    #: OTHER methods need. Defaulted so every existing construction of this
+    #: dataclass keeps working unchanged.
+    eo_oracle: EoRosterOracle | None = None

     @classmethod
-    def build(cls, roster) -> _SeriesCalendar:
+    def build(cls, roster, *, eo_oracle: EoRosterOracle | None = None) -> _SeriesCalendar:
         if roster is None:
-            return cls({}, {}, {})
+            return cls({}, {}, {}, eo_oracle)
         dates, volumes = roster
         ...
-        return cls(cls._cumulative(congress_by_year), cls._cumulative(volume_by_year), titles)
+        return cls(cls._cumulative(congress_by_year), cls._cumulative(volume_by_year), titles, eo_oracle)
```

```python
-    @staticmethod
-    def eo_in_known_series(executive_order: str | None) -> bool | None:
-        """Undated on purpose — see the class docstring's measured zero."""
-
-        if executive_order is None:
-            return None
-        return 1 <= int(executive_order) <= EO_HIGHEST_KNOWN
+    def eo_in_known_series(self, executive_order: str | None) -> bool | None:
+        """Undated on purpose — see the class docstring's measured zero.
+
+        The range check runs FIRST and alone decides every number outside
+        [1, EO_HIGHEST_KNOWN]: a five/six-digit typo must read False exactly
+        as it does today, whatever the oracle would say (it says `unknown`
+        for anything outside its own windows, which must never soften a typo
+        into `None`). Only a number that passes the range check is handed to
+        the oracle, where one is bound, for a finer answer than "in range":
+        `exists` -> True, `absent` -> False, `unknown` -> None (honest, not a
+        guessed True). Absent an oracle, behavior is unchanged.
+        """
+
+        if executive_order is None:
+            return None
+        number = int(executive_order)
+        if not 1 <= number <= EO_HIGHEST_KNOWN:
+            return False
+        if self.eo_oracle is None:
+            return True
+        verdict = self.eo_oracle.verdict(number)
+        if verdict.verdict == "unknown":
+            return None
+        return verdict.verdict == "exists"
```

### Call sites: two are fine, and one is NOT

The two production call sites already read `calendar.eo_in_known_series(...)`
on a bound instance (lines 4887 and 7991), so the `@staticmethod` → instance
conversion is transparent to them. **The test suite is a different story**, and
an earlier draft of this spec asserted "no caller needs to change" without
checking it:

* `tests/test_unified_agenda_parquet.py:3066-3067` calls it on a `calendar`
  instance — fine.
* `tests/test_eo_roster.py` called it on the CLASS
  (`_SeriesCalendar.eo_in_known_series(str(number))`). Under this diff that
  binds `str` to `self` and raises `TypeError`. **Already fixed in this
  lane**: that test now reads
  `_SeriesCalendar.build(None).eo_in_known_series(str(number))`, which is
  correct both before and after the conversion, so the follow-up unit inherits
  no breakage from this file.

Before applying, re-run `grep -rn "_SeriesCalendar\.eo_in_known_series" src
tests` — a class-level call is the one shape this conversion breaks, and it
breaks loudly rather than silently.

## Diff 4 — thread the oracle into the one `build()` call site

**File:** same, line 7526.

```python
-    calendar = _SeriesCalendar.build(pl_roster)
+    calendar = _SeriesCalendar.build(pl_roster, eo_oracle=_eo_roster_oracle())
```

## Diff 5 — receipt: a new key beside `eoOutOfSeriesRows`

**File:** same, line 8962.

```python
             "eoOutOfSeriesRows": sum(1 for r in authorities if r["eo_in_known_series"] is False),
+            #: New with the eo_roster oracle wiring: rows that cite an
+            #: in-range EO number (passes EO_HIGHEST_KNOWN) the oracle can
+            #: neither affirm nor deny -- previously silently True. See
+            #: eo_roster.UNKNOWN_REASONS; predicted 50 rows / 10 numbers on
+            #: the pinned build (research/evidence/eo-roster-2026-08-31/measure.py).
+            #: A build with no roster directory would report 0 here while
+            #: meaning "never asked" -- which is why Diff 6 refuses to build.
+            "eoUnknownRows": sum(
+                1 for r in authorities if r["eo_in_known_series"] is None and r["executive_order"] is not None
+            ),
```

`eoOutOfSeriesRows`'s own value and meaning are UNCHANGED by this wiring: it
still counts only rows that fail the bare range check (today: 3 numbers / 7
rows — `20450`, `21600`, `23891`). It does NOT absorb the oracle's `absent`
verdict; an oracle-`absent` row is `eo_in_known_series is False` too, so a
future genuine absence WOULD raise this count, which is correct — the
`eoUnknownRows` split exists precisely so a reviewer can tell "definitely
impossible or measured absent" apart from "honestly don't know", a distinction
the bare range check could never make.

## Diff 6 — the build gate: refuse rather than regress to range-only

**File:** same, `main`'s missing-oracle refusal, lines 9146–9160.

This is the diff the earlier draft of this spec **omitted**, and omitting it
is what makes the wiring fail open. Every loader in this module answers `None`
to a caller with no oracle, which is right for a reader and wrong for a build:
a build from a tree without `research/evidence/eo-roster-2026-08-31/` would
write `eo_in_known_series` from the bare range check, report `eoUnknownRows: 0`
— indistinguishable from "the oracle was consulted and doubted nothing" — and
pass `--verify`. The module's own comment there records that this exact thing
happened on 2026-08-22 with two other oracles.

```python
     missing += [
         path
         for path in (
             _USC_SECTION_ORACLE_DIR,
             _USC_DISPOSITION_TABLES_DIR,
             _USC_SOURCE_CREDIT_DIR,
+            _EO_ROSTER_DIR,
             args.act_index,
         )
         if not path.is_dir()
     ]
```

## Diff 7 — the producer block: hash the module and the roster

**File:** same, `_PRODUCER_MODULES` (lines 1310–1330) and `_producer_block`
(lines 1333–1353). Also omitted by the earlier draft: without these, a receipt
cannot tell an artifact built against this roster from one built against a
re-pinned one, and `describe_producer_drift` stays silent when either moves.

```python
     "usc_disposition_tables",
+    #: The EO existence oracle's own module. Its roster's sha256 is a literal
+    #: string in it and its loader refuses on drift, so hashing the module
+    #: pins the roster's identity too -- and the file is listed under
+    #: "oracles" below as well, because that one IS the publisher-derived
+    #: bytes, the same argument as cfr_authority_notes.
+    "eo_roster",
 )
```

```python
         "oracles": {
             "public-law-roster.csv": digest(_PL_ROSTER_CSV),
             "part-subjects.csv": digest(_OFR_INDEX_CSV),
             "ecfr-authority-notes-2026-08-24/notes.jsonl": digest(_CFR_AUTHORITY_NOTES_JSONL),
             "unified-agenda-fr-document-roster/documents.csv": digest(_FR_DOCUMENT_ROSTER_CSV),
             "initialism-roster-2026-08-24/roster.csv": digest(_INITIALISM_ROSTER_CSV),
+            "eo-roster-2026-08-31/derived/roster.csv": digest(_EO_ROSTER_DIR / "derived/roster.csv"),
         },
```

## Predicted verdict-count deltas (`eo_in_known_series`)

Measured against the current build's cited-EO census (391 numbers, 19,011
rows — see `measure.py`, reproduced as a test in
`tests/test_eo_roster.py::test_measured_against_the_cited_eo_census`):

| Today | After wiring | Numbers | Rows | Why |
|---|---|---|---|---|
| `True` | `True` (unchanged) | 378 | 18,954 | oracle `exists` |
| `True` | **`None` (new)** | **10** | **50** | oracle `unknown` — sparse-window miss (9 pre-1929, plus `7419`) |
| `True` | `False` (new) | 0 | 0 | oracle `absent` — unreachable on today's roster (README.md) |
| `False` | `False` (unchanged) | 3 | 7 | exceeds `EO_HIGHEST_KNOWN` (`20450`, `21600`, `23891`) — range check alone |
| `None` | `None` (unchanged) | — | — | `executive_order is None` — different code path, untouched |

Net: **`eoOutOfSeriesRows` stays 7. New `eoUnknownRows` starts at 50.**
50 rows that read `eo_in_known_series=True` today — indistinguishable from a
genuinely fine citation — become an honest `None`. Zero rows flip to `False`.

**Note for whoever applies this:** these counts are one number better than the
first draft of this spec predicted (377/18,951 and 53 rows / 11 numbers). The
difference is EO 8284, which that draft wrongly believed did not exist. If the
counts you measure do not match the table above, re-run `measure.py` before
adjusting anything — it prints the delta against the mined expectation on
purpose.

This wiring intentionally does **not** touch:

* `citation_grammar.py`'s `EO_HIGHEST_KNOWN` constant (no edit proposed —
  `eo_roster` no longer reads it at all; the range check above still does);
* the `eo_compilation_start` / `eo_compilation_page` fields — a
  "3 CFR, 19XX Comp., p. NNN" locator names a compilation page, not a bare EO
  number, and is a different citation shape;
* the note-census EO population (16,684 rows, the second-largest unjudged
  family per `research/investigations-mined-2026-08-31.md` item 5) — that
  population lives outside `LEGAL_AUTHORITIES_SCHEMA` entirely and needs its
  own wiring review; this spec only re-derives the fence already wired to
  `executive_order`.

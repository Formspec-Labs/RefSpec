# Read-only review, 2026-08-23: the two new registry modules and grammar wave 6

Reviewed in the dark at HEAD `e8b4c2c1`, read-only, with every claim checked
against the digest-pinned oracle parquets
(`research/evidence/usc-section-oracle-2026-08-22/`), the two act-index
artifacts, the 126 MB Table III member, and the as-measured 797,170-row
snapshot. `ruff` clean; 199 tests green across the three suites. Findings are
ranked; the fixes are being applied by file owner (builder, oracle, grammar,
act index) and committed one per finding. This note is the record of what was
found and, as importantly, what was verified correct and must not be "fixed".

## Findings (ranked)

1. **Three of wave 6's four new fences are computed and dropped.**
   `cfr_part_is_plausible`, `statute_volume_matches_public_law` and the
   magnitude fence live on `AuthorityCitation`; no column carries them. The
   Statutes fence is `False` on 14 values / 100 rows — class A1 to the row —
   and every verdict is discarded at projection. Fix: three columns and a
   per-build ceiling (builder).
2. **`c3_proposal` guesses.** Alphabetical first suffix among up to six
   affirmed readings (15 U.S.C. 78 → "78a" over 78b/c/g/h/i; 303 of 343
   rows), contradicting exactly-one-survivor; `80(a)-23` → "80a-1". Fix:
   candidates, `proposal=None` when more than one survives (oracle).
3. **Five predicates unreachable, three duplicated inline** in
   `classify_section_miss` (C3, C8b, C10, C11, C12). Fix: delete or call (oracle).
4. **Stale evidence string** — "the 24-act index lacks" after the default
   index became the 15,189-law one, which holds 15 U.S.C. 80b-11. Fix: name
   what was consulted; tie prose to `USC_ACT_INDEX_ARTIFACT` (oracle).
5. **Grammar tests pin corpus counts against the live artifact**, undigested,
   while the artifact moved three times in a day. Fix: digest-gated snapshot
   (grammar tests).
6. **Lettered Statutes page reader leaves the new verdict NULL** (30 values /
   369 rows; 24 / 328 answerable). Fix: one closure, both readers (grammar).
7. **Five of 68 abbreviated spans expand into phantom ranges typed `ok`**
   (`16 USC 4601-31` is 460l-31: 8 of 31 members real). Fix: a named span
   rule, `partial` where an endpoint is absent (grammar + builder column).
8. **20,809 spans narrated, 20,371 tested**; the 438 sit in already-refused
   records. Fix: count both (act index).
9. **`popular_name_index_table3_keys = 8,391` depends on parquet row order**
   (34 names map to two keys). Fix: order-free count or explicit tie-break.
10. **49 volume-spanning keys ≠ 49 congress-spanning keys** (6 each way);
    `87-845`, `93-107`, `98-47`, `98-53` carry two volumes for one key.
11. **Three row counts for one `cfr_section` recovery** (4,126 / 4,186 /
    measured 4,363 rows, 309 values). Fix: one pinned number.
12. **C8c covers two mechanisms** — 64 of 113 pairs are abbreviated spans
    the grammar now reads. Fix: split C8c / C8d (oracle).
13. **Two refusals name a byte count, not a specimen**; four attribute reads
    raise bare `KeyError` (act index).
14. **Oracle digests verified lazily per table**, not all six on load.

## Verified correct — leave alone

- The two-regime Statutes-volume formula: 0 of the observed (congress,
  volume) pairs 57–119 rejected; `{C−25}` for 57–73, `{2C−99, 2C−98}` from
  74, with the 75th at {50,51,52} and the 93rd at {87,88,89} as the two named
  overruns; **zero remaining margin** on each side.
- Title 27 stops at 228 (39 enumerated sections, top `219a`, highest range
  221–228) — the CITES repair is bought.
- The three `_abbreviated_span` guards: survivors are exactly
  42 U.S.C. 5714-21…-25 and -41, inert on all 42,642 values.
- `_ZERO_PADDED_SECTION`: no real section begins with 0; no real `-0N` leaf;
  `49 USC 20701-03` stays a span; `15 USC 80a-06` becomes `80a-6`.
- The `780 → 78o` repair does not generalise: 30 real compound stems end in
  the digit 0 (16 U.S.C. 760-1…760-12 among them).
- The 13,274-pair "an act index is not a roster" measurement reproduces
  (the union includes the popular-name table).
- Oracle: `_DASHES`; range stubs judge, never propose; C2's
  not-itself-a-section clause keeps `5 USC 552a` / `42 USC 2139a` out;
  `parse-as-filed` as a competing survivor; the unforgeable
  repealed-before-1994 caveat; `subsection_verdict` unknown for non-current
  sections (all 8,405 stubs carry zero subsection rows); C4 alive at zero.
- Act index: `TABLE3_KEY_RULE` (one disagreement in 48,973 acts:
  `1956-03-02:78-80`); record accounting exact (302,156 + 15,434 = 317,590;
  15,189 + 7,958 = 23,147; `pages_unreadable` 0); the 35 reached keys outside
  the shape are all Public Resolutions; the checked split; `verify_artifact`
  naming a drifted file then declining to read it; the narrowed-page
  quarantine preserving the span text.

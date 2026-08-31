# The xhigh review of the branch, and what it caught — 2026-08-31

An xhigh-effort multi-agent review (15 finder angles, 5 batched verifiers,
one gap sweep) ran over the whole branch after the intake-ledger wave landed:
~31.5k diff lines across 18 commits — the 2026-08-31 identity wave AND the
whole silent-misreads campaign before it. Verdicts: 30 CONFIRMED, 8
PLAUSIBLE, 1 REFUTED. This note is the durable ledger of every confirmed
finding and what happened to it, in three buckets: fixed the same night,
sealed-lineage (each fix changes a receipted artifact and rides the
rebuild + re-pin + audit ceremony), and operational (no pins involved;
ordinary commits whenever picked up).

## Fixed the same night (in the review-follow-up commit)

- **`agency_crosswalk` decoration pattern half-stripped two common forms.**
  `Docket Nos. FDA-…` → `NOS.FDA-…`, `Docket No.CDC-…` → `NO.CDC-…`, both
  then `not_found` against dockets present in the table. The archived
  reference builder carries the IDENTICAL pattern, so this was a defect in
  the sealed rules faithfully ported. Fixed as a recorded deliberate
  divergence: strictly additive, the zero-collision claim re-verified over
  the byte-identical 276,326 dockets, guards pinned (`DOC-2005-0010`,
  `DOCKET-2020-0001`, and the National Ocean Service's own `NOS-…`).
- **`build_usc_popular_names` receipt crash on a repo-relative `--output`.**
  Guarded on the resolved path, called `relative_to` on the unresolved one;
  the module's own usage spelling sealed both tables then died before
  `receipt.json` existed. Fixed (resolve once), regression test added.
- **`build_usc_source_credits` publishes one wrong Stat. page — pinned, not
  repaired.** 22 U.S.C. 283z-11's credit chains through a division-less
  `Pub. L. 110-5`, invisible to the `div.`-requiring ENACTMENT bound, so
  `121 Stat. 25` is attributed to the 2006 enactment. The frozen artifact
  carries the identical row (verified byte-for-byte), so the builder keeps
  reproducing it and `KNOWN_WRONG_PAGE_ROWS_ON_119_102` + a pinned test make
  the fix a deliberate reseal, never a silent divergence.

Two more were caught and fixed during integration, before the review:
`mint_partner_iri`'s false anti-shadow claim (comments corrected, the
deliberate kind-reuse pinned positively) and two term-currency-violating
fixture spellings in `test_iri_minting.py`.

## Sealed-lineage findings — each is an artifact-changing unit

These publish wrong values in receipted artifacts today. Every fix moves
digest-pinned numbers, so each belongs to a rebuild + re-pin + audit cycle,
joining the ranked backlog in
[`investigations-mined-2026-08-31.md`](investigations-mined-2026-08-31.md)
(same ceremony, same do-not-drive-by rule). Ranked by shipped blast radius:

1. **`cfr_authority_notes.read_note_citations` dedups on (family, identity)
   without `span_end`** — a bare `44701` offered before the span
   `44701-44702` swallows the range; **101 sealed rows publish near-miss
   where the part's own note names the section in a range** (92 of them
   49 U.S.C. 44702 under 14 CFR 121).
2. **`act_resolution` act-section case mismatch** — the index keys keep
   OLRC's `1818A` while the grammar lower-cases to `1818a`; 1,812 index
   keys unreachable, **112 sealed rows wrongly `act_section_not_classified`**
   (SSA 1818A/1115A/1128A, CAA 169A, Head Start 641A…). `from_artifact`
   normalizes the name side one line above the miss.
3. **Three agenda list-emission sites strip subsections without dedup** —
   `sec. 4(i), 4(j), 4(o)` becomes three identical rows; **121 phantom
   duplicate rows** in the sealed legal-authorities parquet, each made
   "unique" by `citation_ordinal`.
4. **`citation_grammar._CITED_DIVISION` is case-blind the wrong way** —
   lowercase marker, no IGNORECASE, uppercase capture required: `Division A`
   and `Div. A` never match. **630 of 723 division-stating values
   invisible**; the strongest act discriminator can never force a refusal.
5. **`citation_grammar._STATED_SECTION`'s leading `\b` kills the `§` arm**
   (no word boundary before a non-word char) — `stated_section('§ 203 of X')`
   is None; **119 of 126 §-bearing unreadable authorities lose their one
   diagnostic column**.
6. **`usc_section_oracle` appendix citations past 2024 return a factual
   `False` from zero evidence** (`not appendix and …` twice) where the
   contract's no-evidence value is None; 38 shipped rows accidentally right,
   every new edition widens the exposure.
7. **`usc_act_index` "stated but not carried" counters never check
   `element.attrib`** — every figure is just the element count (e.g.
   `record/@print-in-supplement` claimed on all 317,590 records; the bulk
   XML states it on 32,749 — ~9.7×). A constant wearing a measurement's
   name, in a sealed receipt.
8. **The source-credits ENACTMENT bound is blind to division-less
   intervening citations** (the class behind the pinned wrong row above);
   fix the pattern at the next reseal and move the pin with it.
9. **The agenda receipt counts 185 roster refusals; 169 rows carry the
   note** (below-cap finding, unverified split — measure first).

## Operational findings — no pins, ordinary commits, deliberately not tonight

Out of the intake-ledger goal's scope; recorded so they are picked up on
purpose. Cheapest-and-loudest first:

- **Hosted explorer: every resource lookup is dead.** `data-layer.js:317`
  selects the DuckDB reserved word `offset` unquoted — parser error on every
  result/node click. One-line quote fix (`reshard.py` already quotes it);
  sits under the derived-relations toggle work, which is **also dead
  end-to-end** (no `DerivedRelation` checkbox exists so `refresh()` drops
  every derived edge; `precompute.py` never passes `relations="all"` and
  omits `source_release` on derived detail rows).
- **Both R2 verification scripts cannot gate anything** —
  `upload-verified.sh` (no `-e`, unconditional trailing echo) and
  `verify-all.sh` exit 0 after printing FAILED/MISSING; plus full-GET
  before the "cheap" range check and key corruption on absolute/`./`
  TARGET paths. `faithful_agenda_build.sh` lacks `set -u`.
- **`make test` no longer runs the sealed Atlas corpus or any slow-marked
  test** — nothing invokes `test-slow`, and the aggregate-guard test now
  enforces the absence on a false premise. A policy call (local speed vs.
  local coverage) for the owner, not a drive-by.
- **`verify_atlas_source_fidelity` will report false infidelity on correct
  output** — the gemet-4.2.3 spec still declares no Group/SuperGroup/Theme
  subjects while the producer now emits 76; the CFR census pins 8,425 parts
  vs the producer's 8,424; the `record_digest_is_native_payload_digest`
  rewrite is self-referential for 7 specs and carries a latent `len(None)`.
- **`agenda_value_diff.py` is blind to 45 of 91 schema columns**, including
  the join/carry family the campaign added; `reshard.py` writes `-small`
  paths nothing reads and dropped the stale-shard unlink.
- **Reuse tier:** five copies of digest/parquet writers, three edit-distance
  implementations, three `_section_order` copies held together by policing
  tests, 50 hand-written SourcePins; GEMET Theme labels bypass
  `_sorted_labels` (all 40 themes already carry both `en`/`en-US` tags);
  `iri_minting`'s partner hatch mints case-fragmented FR IRIs by design
  (documented, pinned) and has no consumer yet.

One finding was REFUTED by the verifiers and is deliberately not listed.

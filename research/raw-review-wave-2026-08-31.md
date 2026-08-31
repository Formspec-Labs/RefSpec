# The raw-review wave: five ground-truth audits, same day, before the next build

Five parallel audits ran 2026-08-31, each reading raw bytes rather than
believing ledgers — the follow-through on the backlog validation's lesson
that every silent failure found that day was upstream data changing or
lying while pins pointed elsewhere. Full worksheets live in the session
scratch; everything decision-bearing is restated here or folded into the
documents it corrects. Per-lane verdicts:

## 1. Durability sweep — one true loss, and a tripwire architecture that let it stand

2,354 manifest entries re-hashed (~14 GB) across every register row, the
committed Wayback evidence, and the SpicySearch pinned paths. One mismatch:
`fr_docket_links.parquet` — and the sweep deepened it three ways now
recorded in [`docs/regeneration-inputs.md`](../docs/regeneration-inputs.md):
the original bytes were found nowhere under ~/Work (twenty copies
hashed across both output trees, all overwritten; 36
manifests pin an unsatisfiable digest), the correct pin sat unread in the
same directory's `.inputs.sources` block, and a later tree manifest
ratified the corruption. Register corrections landed: `-21b` IS test-pinned
and `-21d` is the unpinned view (the register had it backwards); three
search views share one set of inodes; the annual dir is 32 zips, all clean.
Three in-repo research files are manifested but were never committed
(`inv-frvol/analysis.duckdb`, its 2020 PDF, and
`inv-initialisms/raw/popularnames.htm`).

## 2. eCFR staleness — ten adversarial parts unchanged; wave B may re-pin against 2026-08-24

Ten adversarially-chosen parts (the three wave-B specimens first) diffed
character-level against the live publisher: all ten UNCHANGED, with a
byte-identical route-constant control eliminating the one confound
(per-part API responses spell `§` as numeric entities; compare after
unescape or every note false-positives). The three wave-B premises are
intact verbatim: `44701-44702` in 14 CFR 121, `101 Stat. 1568, 1638` in
12 CFR 611, the `App. U.S.C.` stem in 46 CFR 382. Bonus datum: 24 of 49
titles moved their issue date since capture with zero sampled note changes
— title-date motion is not note staleness.

## 3. Initialism roster hand-audit — 296 rows, zero residue, eight corrections

The MIPPA three-number mystery closed exactly: **29 is correct under the
column's own definition** (first-token-wins census over `other/failed`
rows); 26 is the answerable subset (name AND shape); 37 the unfiltered
count. The 136-row census drift decomposes with zero remainder — 112 rows
are **the roster itself working** (tier-by-tier equal to the artifact's
corroboration counts), 22 grammar wins, 2 first-token shadowing. Verdicts:
253 HOLD, 20 count-drift (all explained), 14 ambiguous, 9 witness-broken.
Corrections C1–C8 ride the roster's next rebuild unit, the sharpest being:
C1 five rows cite the headers file's path with the popularnames body's
digest (a mechanical `sha256(path)==digest` check fails on exactly those
five); C2 `reverse-pl-verified` is assigned per token but is a per-row
property, wrong at four agencies; C3 FAA@2105 co-cites three different FAA
acts and needs a human year-keying decision; C7 `rows_observed` is a
first-match census, not a mention census, and the README should say so.

## 4. Pre-2000 salvage census — "the corpus" is Rules only, and the rest is one fetch campaign away

The store is exactly Rules + Proposed Rules 1994–1999: **99.996% and 100%
coverage of those** (40k bodies) but 20.4% of the era's documents; the
124,727 Notices were never attempted, and 24 of 24 sampled unfetched
documents retrieve on the first attempt (~18 hours at the store's own politeness interval would attempt the
rest; 24/24 sampled is strong but sampled). The presidential store is secretly
**complete across all eras 1994–2026**. Exactly one document resisted every route on 2026-08-31
(`95-8641`: dead on direct + Zyte + Wayback + govinfo that day), and its
content survives byte-identical under its fused twin `95-8641-Filed`.
Caveats that matter: the 1994 denominator hides ~7,600 untyped rules (96.7%
of 1994 is "Uncategorized"); the campaign's original fetch ledgers were
overwritten by a 2-document rescan; and the census re-derived our
394,128 bare-legacy figure precisely — its 395,498 measurement minus the
1,370 short-tail refusals equals 394,128 exactly.

## 5. Pilot attestation — the ceremony works, and its first act was overruling its own commission

The founding row of the hand-validation registry lives in
[`research/evidence/hand-attestations-2026-08-31/`](evidence/hand-attestations-2026-08-31/)
with six witnesses and one viewing aid. The print PDF (70 FR 25814, read at 600 dpi against a
properly-spaced control colophon on the same page) proved the commissioned
premise wrong: `E5-2394Filed` is a **composition defect on the printed
page**, not a digitization loss — the `kind` field was corrected against
instruction, with the correction recorded. The row shape's load-bearing
inventions: per-claim witnessed-vs-inferred strength ("one document" is
witnessed; "the number is E5-2394" is inferred from the template and
dereferences nowhere), `reverse_substitution: forbidden` (the
canonical-looking spelling is the dead one), and witnesses counted as
sources, not copies of one defect. Per-value-never-per-pattern is now
grounded, not asserted: the fusion did not even apply uniformly within one
printed page.

## What changes downstream

Wave B re-pins against the standing eCFR capture. The roster's C1–C8 ride
its next rebuild. The durability rules (read `.inputs.sources`; refuse
ratifying tree manifests; re-run on a schedule) are in the register. The
Notices fetch campaign is a sized, deliberate decision (~18 h) rather than
an unknown. And the attestation registry has a founding row and a second
named specimen (`95-8641`/`95-8641-Filed`) waiting.

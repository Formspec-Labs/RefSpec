# What the Federal Register's own bytes state that the platform does not yet capture

Compiled 2026-08-31 from raw publisher source examined that day: the 39,789
salvaged pre-2000 rule bodies and 7,212 presidential bodies under
`~/Work/corpora/_salvage-2026-08-28/spicysearch-output/` (see
[`docs/regeneration-inputs.md`](../docs/regeneration-inputs.md)), plus one
live publisher fetch for the six-digit bare-legacy family. One specimen per
identifier family was read end to end (97-1017, E6-15292, C1-2009-31418,
Z9-26408, R1-2016-03141, 95-170007); every claim below is anchored to what
those bytes literally say.

An incidental finding worth keeping: the Z prefix, which the minting layer
admits without asserting a meaning, turned out to be **a second correction
series** — Z9-26408 reads "Correction / In Presidential document E9-26408
... make the following correction", the same construction as the C family.
The raw source taught us the meaning; asserting it platform-wide would be an
evidence-bound assertion whose witness is that paragraph.

## Captured today (mostly publisher-API metadata, not text parsing)

| Signal | Where it lives |
| --- | --- |
| Document number (all six families) | `document_number` column; minted per REF-052/REF-054 (480,566 first-class, 511,420 house IDs, 98.8% identified) |
| EO number, signing date, title | `executive_order_number`, `signing_date`, `title` columns; EO prose citations read by `citation_grammar`; minted as `rkaf:us-eo` |
| Agency | `agencies_json`/`agency_slugs`; hierarchy rosters; `registry/agency_crosswalk` |
| Volume / page | `volume`, `start_page`, `end_page` columns |
| Dockets, RINs, CFR references | the shape layer and minting layer; the Agenda parquet lineage |

## Recognized and deliberately parked

- **FERC docket numbers** (`TM95-5-28-000` in the 95-170007 specimen):
  `identifier_shapes` names the family, counts it (24,548 of the
  `CP26-20-000` form), and refuses to mint it as a docket because it belongs
  to FERC's own registry, for which rkaf has no family. A counted refusal,
  not an oversight; the reopen path is a future FERC identifier family in
  the rkaf contract (deliberately not spelled as a term here — the
  term-currency sweep rightly refuses claims to families that do not exist).

## On the table — the body-text layer, per signal

Ranked by product value; owner per REF-022/REF-024/REF-048.

1. **Document-to-document edges** — the highest-value uncaptured signal.
   `Executive Order 13516—Amending Executive Order 13462` (an *amends* edge
   between EOs); `In Presidential document E9-31418 ... make the following
   correction` (a *corrects* edge stated in the first sentence of every C/Z
   correction); the R family's *republishes*. We detect the shapes and mint
   the identifiers; nothing asserts the edges. **Owner: DocSpec** (document
   identity, versions, and exact document joins are its charter; its
   implementation is REF-048's acknowledged open half), riding Rulespec's
   assertion-with-evidence model. Two consumers already dead-end without it:
   the EO existence oracle backlog item (2,876 rows — amend/revoke chains
   explain the gaps) and any document-versions story. The correction edge is
   the cheapest first bite because the publisher states target and change in
   the correcting document's opening line.
2. **FR citations in running prose** (`60 FR 35903` as a cite, not a
   column). UNVERIFIED whether `citation_grammar` has this family — verify
   before acting; if absent it is RefSpec-shaped (a citation grammar) and
   enables page-level cross-referencing.
3. **Filed timestamps** (`Filed 9-12-06; 8:45 am` in the colophon). Filing
   precedes publication and occasionally matters legally; we carry only the
   API's `publication_date`. Document-level fact → DocSpec. Low value today.
4. **Billing codes** (`BILLING CODE 3410-FA-P`). A cheap agency
   corroborator. Uncaptured; marginal.
5. **Signers** (`Kenneth D. Ackerman, Manager, Federal Crop Insurance
   Corporation`). Person + role entities; people are deliberately outside
   the entity ring today. No owner; a scope decision before any capture.

## The refused census, read against the publisher's own bytes

The 12,247 refused `document_number` values were sampled per shape family the
same day, each against GPO's raw text. Every sampled value is the
**publisher's own system-of-record spelling**, which strengthens the refusal
doctrine (repairing would diverge from the source of record) and reframes
what hand-validation would assert:

- 10,230 letter-prefix short tails (`C0-126`) and 1,656 bare short tails
  (`00-10`, an FAA airworthiness rule) — real documents held out by the
  recorded recall decisions; the frontier for any future widening.
- 228 `-2`-suffixed values (`94-10196-2`) — number-reuse collisions,
  confirmed by reading three full pairs against the salvaged bodies: each
  pair is two genuinely different regulatory actions stamped with one
  number. `95-13256` is BOTH a FAR environmentally-preferable-products rule
  (RIN 9000-AG40, FAR Case 92-54) AND a FAR ozone rule (RIN 9000-AG42, FAR
  Case 93-307) on contiguous pages; `96-32845` is a Delaware River
  fireworks regulation AND a Corson Inlet drawbridge NPRM 24 pages apart,
  different dockets and signers; `96-18188` is two same-minute NMFS
  closures (rockfish vs sablefish, I.D.s 071296C/B). The suffix is the
  aggregator's and it is load-bearing — without it a join conflates two
  RINs into one document. The disambiguation witness is printed inside each
  half (its own RIN, docket, CFR parts), so the 228-pair hand-validation
  worklist has a mechanical, re-checkable witness per row. The family
  concentrates in 1994–97, a batch-filing collision at GPO that stopped.
- 100 modern correction short forms (`C1-2010-1863`) — publisher's own
  spelling, verified in its colophon.
- ~27 fused-colophon values (`E5-2394Filed`, `2014-04654s`) — CORRECTED
  by the pilot attestation's print witness: the fusion is a **composition
  defect on the printed page itself** (the 600-dpi read of 70 FR 25814
  shows `[FR Doc. E5–2394Filed` welded in print, while the same page's
  column 1 carries a properly spaced control colophon), with the recovery-by-whitespace-splitting an inference consistent with
  every witness, observed by none. Not digitization, not aggregator damage —
  the printed page. Only THIS value is attested; the other ~26 family
  members are per-value pending, and the same page's spaced control proves
  the defect was not uniform, so nothing generalizes. The unfused `E5-2394` dereferenced
  nowhere probed on 2026-08-31 (404 at both publishers, headers saved;
  neighbours 200), so reverse substitution
  is forbidden: the fused spelling is the only live identifier. The
  founding attestation row with seven witnesses lives in
  `research/evidence/hand-attestations-2026-08-31/`. The salvage census
  found a second specimen of the family resolved the other way:
  `95-8641` was dead on all four routes (direct, Zyte, Wayback, govinfo) on 2026-08-31 whose content survives under its
  fused twin `95-8641-Filed`, byte-identical to the live copy.
- `C0-6263A` — not damage: the publisher filed it with the trailing letter
  (`[FR Doc. C0-6263A Filed 4-5-00]`). A real micro-family no shape admits
  yet.
- `granule293` — the Reader Aids section, which has no FR Doc number, served
  with GPO's internal granule id as a placeholder. The pile's only
  non-document, and even it is the publisher's.

## The rule for picking any of this up

Mine the body-text layer when a consumer dead-ends, not speculatively — the
doctrine that already governs the backlog. The identifiers are done; the
edges between documents are the next frontier; they are DocSpec-shaped; and
the correction edge is the cheapest because the publisher states it
outright. SpicySearch's text-ingest lane is the machinery any extraction
would actually run on, and the hand-validated-interpretation slot (a
per-value, evidence-bound assertion registry — designed, deliberately not
built; see the census's 12,247 refused values) is the same ceremony these
edges would use.

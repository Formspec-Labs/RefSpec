# The modern Federal Register document-number collision census, 2026-09-02

`mint_federal_register_document_iri` mints `rkaf:us-frdoc` from the document
number alone — rulespec's modern space (`[0-9]{4}-[0-9]{3,5}`) carries no
date qualifier, unlike the legacy space REF-064 added. That premise holds
only if one modern document number never names two different documents. A
full crawl of the federalregister.gov API, run 2026-09-02 and brought home
here as `fr-full-collision-census.json` (112,263 bytes,
`sha256:427a68272f87225e45c7bc25376c73c2761e07a613c7d87a8a6cdaa73c73356c`),
found **seven** that do.

## What the receipt measures, and what it does not

The receipt's own `coverage` block states its scope and limit, quoted
verbatim because it bounds every claim below:

> "this census describes the crawled Federal Register (1994 onward, the
> API's own coverage) and is not evidence about the printed Register before
> that"

Concretely: `coverage.distinctNumberCount` is 1,007,156 over
`coverage.queryScope` `1994-01-01` through `2026-09-02`. That is a *larger*
and *fresher* crawl than the 1,004,233-distinct pinned parquet
`tests/test_iri_minting.py` reads elsewhere in this repository (REF-052's
own measurement, taken 2026-08-22 and re-measured 2026-08-31) — the two are
independent snapshots of the same publisher, not the same file, and nothing
here assumes they agree row for row. `collisionCountingBasis` states the
count is taken "over unnormalized document numbers, no prefix or case
folding applied", and `modernFormCollisionsBasis` states that membership is
the number's *form* (fullmatches `[0-9]{4}-[0-9]{3,5}`), not the year its
dates fall in — legacy `NN-` numbers run 1994 through 2009, modern `YYYY-`
numbers start 2010-01-06, so a modern-form collision can only ever pair
dates from 2010 onward.

The receipt's `modernFormCollisionCount` is **7**, out of a broader
`sameNumberDifferentDateCount` of **474** across the *whole* crawled corpus
(`totals.records` 1,007,156, `totals.multiObservationIds` 474) — the other
467 are legacy-form numbers, which already needed `publication_date` to
identify at all (REF-064) and are not this census's news. The seven modern
ones are the news, because until this census they were assumed unique by
number alone.

## The seven, and the adjudication

`modernFormCollisions` names each `recordId` and its two `dates`. Knowing
*that* two dates exist for one number says nothing about *why* — a
correction can legitimately republish a notice under its own document
number weeks later, and a database anomaly can just as easily hand two
unrelated notices the same number. Telling the two apart needed the actual
documents, not the census row, so every one of the fourteen dated
appearances was fetched from `federalregister.gov`'s own full-text HTML
(`specimens/`, `{recordId}__{date}.html` plus a matching
`.headers.txt` capturing the response) and read for its agency and subject
— raw source, not the API's summary metadata, for the reason the next
section gives.

| recordId | dates | verdict | why |
|---|---|---|---|
| `2010-31094` | 2010-01-06, 2010-12-10 | **REFUSE** | EPA pesticide-meeting notice (`EPA-HQ-OPP-2009-0879`) vs. a DOT/FAA airport-safety NPRM extension (`FAA-2010-0997`) |
| `2010-31384` | 2010-01-06, 2010-12-16 | **REFUSE** | Commerce/NTIA spectrum-committee notice vs. a DOT/FAA Boeing 777 airworthiness directive (`FAA-2009-0430`) |
| `2010-31396` | 2010-01-06, 2010-12-15 | **REFUSE** | EPA pesticide-cancellation notice (`EPA-HQ-OPP-2009-0977`) vs. a DOT/Maritime Administration information-collection notice (`MARAD 2010 0109`) |
| `2010-31415` | 2010-01-06, 2010-12-15 | **REFUSE** | Postal Regulatory Commission docket notice (`CP2010-19`) vs. a DOE/FERC hydropower preliminary-permit notice |
| `2010-517` | 2010-01-14, 2010-01-28 | **REFUSE** | DOE/FERC gas-pipeline-abandonment notice (`CP10-33-000`) vs. a DHS/Coast Guard "Correction" — but the correction is of a *different* document, `E8-11863`, not of `2010-517` itself |
| `2015-17759` | 2015-07-21, 2015-08-05 | **MINT NORMALLY** | SEC notice (Release No. 34-75460, File No. SR-NYSEMKT-2015-48), corrected in place: "In notice document 2015-17759 … make the following correction" |
| `2015-25354` | 2015-10-06, 2015-10-13 | **MINT NORMALLY** | Dept. of Education notice (Docket ED-2015-ICCD-0118), corrected in place: "In notice document 2015-25354 … make the following correction" |

Five name genuinely different documents — different agencies, different
subjects, no textual relationship between the two appearances. Minting one
`rkaf:us-frdoc` identifier for either pair would silently merge two
unrelated regulatory actions under one IRI. Two name one matter republished
under its own number: the second appearance is explicitly, textually a
correction *of the first, by its own document number* — "one matter,
published twice" is the correct reading, and a single identifier for both is
what a reader of either document would expect it to resolve to. These two
are recorded as `consulted` rows in
`src/refspec/registry/hand_validated_interpretations.py` rather than left
unmentioned, so the record shows they were examined and deliberately left to
mint, not overlooked.

## Why raw text, not the API's `correction_of` field

The federalregister.gov document API carries a `correction_of` field built
for exactly this relationship, and it would have made this an easy lookup —
except it does not populate it here. Fetched directly:

```
$ curl .../api/v1/documents/2015-17759.json?fields[]=correction_of&fields[]=corrections
{"correction_of":null,"corrections":[]}
```

Both `2015-17759` and `2015-25354` answer `correction_of: null` — the same
answer every one of the five REFUSE numbers gives, because the API's
correction-linking machinery is built for a *different* document number
correcting an earlier one, not for a correction notice republished *under
its predecessor's own number*. Metadata alone cannot tell a `consulted` row
from a `REFUSE` row here; only the document body can. That is also why
`2010-517` is the specimen worth reading closest: its second appearance
(2010-01-28) is captioned "Correction" exactly like the two genuine
self-corrections, from a Federal Register perspective indistinguishable by
shape from the pattern that mints normally — until its text is read and
turns out to correct `E8-11863`, an unrelated Coast Guard rule, while the
first appearance (2010-01-14) is an unrelated FERC gas-pipeline filing from
a different department entirely. Three of the seven — `2010-517` and the two
genuine corrections — carry the same surface word "Correction"; only reading
which document each one actually corrects, and who issued it, separates
them.

## Files here

- `fr-full-collision-census.json` — the census receipt, byte-identical to
  the copy at `~/Work/corpora/supply-2026-09-02/receipts/` this evidence
  home was brought home from. Pinned by
  `hand_validated_interpretations._FR_COLLISION_CENSUS_PIN`; the reader
  refuses to load if these bytes drift.
- `specimens/*.html` — the fourteen raw full-text captures (one per
  `recordId` × `date`), fetched 2026-09-02 from
  `https://www.federalregister.gov/documents/full_text/html/{yyyy}/{mm}/{dd}/{recordId}.html`.
- `specimens/*.headers.txt` — the matching response headers, carrying each
  capture's `date` (retrieved-at) and `content-length`.
- `MANIFEST-sha256.csv` — every file above, its byte length, and its sha256,
  in the same shape as `research/evidence/eo-roster-2026-08-31/MANIFEST-sha256.csv`.

## Where the adjudication lives

`src/refspec/registry/hand_validated_interpretations.py` restates this
table's seven verdicts as typed `Interpretation` rows — five
`refusal-to-interpret`, two `consulted` — each witnessed by its own two
`specimens/` files, not by this README or the census file (a witness cited
by seven different rows with seven different `shows` texts would defeat the
anchor check that holds each row's prose to its own bytes). Consulted from
`src/refspec/registry/iri_minting.py`'s `mint_federal_register_document_iri`,
which refuses (`None`) for the five and mints normally for the two. See
REF-066 in `docs/decisions.md`.

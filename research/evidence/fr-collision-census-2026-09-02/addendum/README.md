# Addendum, 2026-09-03: what causes the seven, measured rather than inferred

The 2026-09-02 census counted **seven** modern-form Federal Register document
numbers that name two documents. It did not ask *why*, and a claim about the
why was then carried into a peer's decision record as though it were a
measurement. It was not. This addendum retracts that claim and replaces it
with one taken from the publisher's own bytes.

## The retracted claim

Four of the seven share the first date `2010-01-06`, and this session wrote
that the four were therefore "one publisher event reusing a block of numbers,
not four independent collisions." Two things were wrong with that. The word
*block* does not describe the numbers — 31094, 31384, 31396 and 31415 are
spread across roughly 320 values. And the whole statement was a story told
about a correlation between four dates; nothing in the census measured a
mechanism. DocSpec's session caught both and was right to.

## What the raw source says

The retained pulls are the federalregister.gov API's full document list for
each date, no filtering (`addendum/day-*.documents.json`).

**2010-01-06 is the first day the modern `YYYY-NNNNN` form exists at all**
(the census states this in `modernFormCollisionsBasis`). That day's issue
carries 60 documents in *three* spellings at once:

| spelling | count | tails |
|---|---|---|
| `E9-` | 52 | 30292 … 31421 |
| `E10-` | 1 | 31397 |
| `2010-` | 7 | 8, 20, 38, **31094, 31384, 31396, 31415** |

Three of the seven modern numbers that day (`2010-8`, `2010-20`, `2010-38`)
are the fresh year-sequence starting from one. **The other four are the
collision members, and none of them can have come from that sequence** — the
fresh counter stood at 8, 20, 38, so no document published 2010-01-06 can
legitimately carry a fresh-counter value of 31094. They fall inside the day's
legacy tail range instead (30292 … 31430), and none of the four appears among
the day's legacy numbers itself.

That counter-position contradiction is the load-bearing argument, and it holds
for all four identically. A second, weaker signal corroborates three of them:
they sit in gaps of the dense contiguous legacy run.

| collision member | nearest legacy below | nearest legacy above | gap |
|---|---|---|---|
| `2010-31384` | `E9-31381` | `E9-31385` | 4 |
| `2010-31396` | `E9-31395` | `E9-31397` | 2 |
| `2010-31415` | `E9-31414` | `E9-31416` | 2 |
| `2010-31094` | `E9-31004` | `E9-31150` | **146** |

    E9-31380  E9-31381  [2010-31384]  E9-31385  E9-31386  E9-31389  E9-31390
    E9-31393  E9-31394  E9-31395  [2010-31396]  E10-31397  E9-31399
    E9-31410  E9-31412  E9-31413  E9-31414  [2010-31415]  E9-31416  E9-31417

For the first three the gap-filling reading is nearly forced. **`2010-31094` is
not in that run** — it sits in the sparse straggler tail at the bottom of the
day's range, where a 146-wide window is not evidence of much on its own. It is
explained by the counter position like the others, not by gap-filling, and this
addendum says so rather than letting one diagram imply four.

So these four are the documents that would otherwise have been `E9-31094`,
`E9-31384`, `E9-31396` and `E9-31415`: the year prefix on the legacy counter's
value.

The December halves are the fresh modern counter legitimately arriving at the
same values. On `2010-12-15` the day's modern tails run **30527 … 31645**, so
31396 and 31415 are ordinary members of that day's range.

**The mechanism, therefore: two counters shared one namespace for one year.**
The legacy E-family tail counter (at ~31,000 in January 2010) and the fresh
`2010-` sequence (starting at 1 that same day) both emitted the same four
values. This is structurally confined to the transition year — after 2010
there is no second counter, so it cannot recur.

## The remaining three are different, and genuine

`2010-517` is a real reuse inside the single modern sequence. Both halves are
sequence-plausible: the modern tails published `2010-01-14` run 39 … 736, and
517 is the *minimum* tail published `2010-01-28` — an ordinary filing-to-
publication straggler. The two documents are unrelated (FERC, CenterPoint
Energy gas transmission notice; Coast Guard, Charleston security zone).

`2015-17759` and `2015-25354` are one matter published twice — same title,
same agency, `correction_of` null on both halves.

## Consequence for the reopen trigger

Neither a **count** trigger nor the **shared-first-date** trigger this session
proposed is right. A count moving from seven to eight because someone
re-crawled 2010 is not signal; a shared-date rule would let three genuinely
new collisions pass if each shared a date with something old.

The trigger the measurement supports: **reopen when a collision appears whose
two observations are both explainable by the single modern counter.** The four
transition collisions fail it loudly — their January observation is off by
~31,000 from that day's modern range of 8 … 38. `2010-517` and the two 2015
pairs pass it, which is why they are the three that are actually interesting.

## Consequence for the collapse

For the four transition collisions the discarded observation is the
*transitional spelling* of a document the E-family run also accounts for, not
a distinct rule lost. For `2010-517` the discarded observation is a different
agency's different document, and that is a real loss. The seven are not
seven of a kind, and a proportionality argument over them should say which.

## Reproduce

    for d in 2010-01-06 2010-01-14 2010-01-28 2010-12-15; do
      curl -sS -G 'https://www.federalregister.gov/api/v1/documents.json' \
        --data-urlencode "conditions[publication_date][is]=$d" \
        --data-urlencode 'fields[]=document_number' \
        --data-urlencode 'fields[]=citation' \
        --data-urlencode 'per_page=1000' -o "day-$d.documents.json"
    done

REF-066's refusal set is unchanged by this addendum: a number that names two
documents is refused whether the second name arrived from a second counter or
from reuse within one.

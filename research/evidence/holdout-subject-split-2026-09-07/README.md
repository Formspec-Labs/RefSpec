<!-- markdownlint-disable MD013 -->

# The +0.0072 splits 27 to 1 between lookup and non-lookup queries

**Read the two conditions before quoting any number here. They are not
caveats; they are the terms on which this reading exists.**

**One. This is a DECOMPOSITION of a terminal verdict, not a new verdict.**
SpicySearch's August holdout campaign is closed and its adoption verdict
computed. That verdict already reports per-job nDCG; this is the same family
one level finer, which is reading. The moment someone wants to decide
something with it, it stops being reading and needs its own instrument.

**Two. These queries are ANCHOR-DERIVED, not a person's words.** The 66 are
built from the target document's own printed List of Subjects block — a
controlled-vocabulary subject query plus an agency name. That is not natural
language and this must not be sold as natural-language evaluation.

## What was computed

`search_by_subject` is published at nDCG@10 0.8345 -> 0.8417, +0.0072, and read
as noise. It is 219 queries of two templates that were never reported apart.

| template | n | spine | candidate | delta | P@5 spine | P@5 cand |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `subject-title-fragment-v1` | 153 | 0.9592 | 0.9600 | +0.0008 | 0.403 | 0.405 |
| `subject-topics-v1` | 66 | 0.5455 | 0.5675 | **+0.0220** | 0.191 | 0.203 |

The 153 paste the document's whole title in and swap "Find the document titled"
for "Find documents concerning" — string lookup, already at 0.96, no headroom
for any candidate to win. The 66 carry no title text at all. The published
figure averages a near-zero over two thirds with a 27x larger gain on the
third that is not a lookup.

**Control, because a split that cannot be validated is worth nothing.** The
same implementation reproduces all three published per-job numbers exactly —
`find_changes_and_dates` 1.0000 -> 1.0000, `find_known_document` 0.2596 ->
0.5175, `search_by_subject` 0.8345 -> 0.8417 — before splitting anything.
Grades `X` (forbidden, 440) and `U` (1) are treated as 0 for ranking, which is
how the published numbers reproduce.

## The 66 are not compromised the way the third job was

That job scores 1.0000 on all arms because every judged item in its pools is
relevant, so there is nothing to rank. Checked here and absent: **0.0% of the
66's pools are all-relevant** (against 5.2% of the title fragments), 26.3
judged items per query, 11.3% of pooled items graded >= 2. There are negatives.

## One observation about the instrument, which is a hypothesis and not a finding

Each of the 66 was matched against the corpus's own published topics — 900
controlled terms over 114,220 tagged Federal Register documents, longest-match
because a term may itself contain "and" (`Administrative practice and
procedure` is ONE term; splitting on "and" gets the numbers wrong, which the
first pass did).

Documents carrying the query's rarest controlled term: min 16, **median 833**,
p75 2,237, max 34,920. Thirty of 66 exceed 1,000 documents; eight exceed 5,000.
The widest asks for `Incorporation by reference` from the Transportation
Department, a term on 34,920 documents, judged on a pool of 26.

So thousands of documents carry the exact printed terms these queries were
built from, and only 11.3% of pooled items were graded relevant. Either
retrieval is largely not surfacing term-carrying documents, or the judges are
not rewarding "carries the printed subject term" — **the criterion the query
was constructed from.** These two cannot be separated from RefSpec: pooled item
ids are `urn:spicyregs:document-version:` and this corpus is keyed by Federal
Register document number, so grade cannot be joined against term-carriage here.
Whoever holds that join settles it in one pass.

Minor: three of the 66 are duplicates (`Air pollution control` +
`Environmental protection` / EPA appears at least twice at 13,715), so n=66
slightly overstates the distinct query count.

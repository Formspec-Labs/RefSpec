# Visual attestation: the two FERC eLibrary PDFs

**2026-08-21.** Neither `ferc-docket-prefixes` nor `ferc-document-class-types`
had an independent publisher adapter, so neither could be covered by
`verify_atlas_source_fidelity`. Writing a second PDF extractor for each is the
expensive path. This is the cheaper one that still satisfies the constraint the
verifier exists to enforce: **the check must not be the producer's own code.**

Both PDFs were read page by page as rendered images — not through the
producer's parser, not through any text-extraction library — and the producer's
output was compared against what the pages show. What follows is what was seen,
what matched, and what diverged.

## `ferc-docket-prefix-june-2025.pdf` — 6 pages, 95 rows

The document is three tables. Counted from the rendered pages:

| table | pages | prefixes |
|---|---|---:|
| Table 1 — Active: Standard Docket Format | 1–4 | 73 |
| Table 2 — Active: Non-Standard Docket Format | 5 | 4 |
| Table 3 — Discontinued Prefixes | 6 | 18 |
| | | **95** |

The producer emits 95 rows, **77 active / 18 discontinued**. 77 = Table 1 (73) +
Table 2 (4), and the discontinued 18 are exactly Table 3. Every prefix matched in
order, including the three whose codes end in a hyphen — `E-`, `G-`, `R-` — which
a whitespace-splitting reader would be likely to mangle.

Hard cells checked individually, all faithful:

- `CD` — `Conduit Determination (< than 5 MW Facility)`; the bare `<` is not escaped or dropped.
- `PH` — `(FERC-65A [Exemption Notification] and FERC- 65B [Waiver Notification])`; the publisher's stray space inside `FERC- 65B` is preserved rather than tidied.
- `IC`, `QM`, `TM`, `DA` — multi-line cells joined into one string with no lost words.
- `RT`, `DA`, `IC` — en dashes (`–`) preserved as en dashes.
- `IC` — the apostrophe in `Commission's` survives.

**One divergence.** The PDF renders `PL`'s library as `Gen,  RM` with two spaces;
the producer emits `Gen, RM` with one. Whitespace is collapsed. This is benign
and is the only difference found, but it means the extraction is *normalised*,
not byte-exact, and no claim of byte-exactness should be made for it.

## `ferc-class-types-january-2025.pdf` — 7 pages, 235 rows

A single four-column table (Category, Library, Classification, Type Description)
spanning seven pages, with `Issuance` rows first and `Submittal` rows after.

The producer emits 235 rows: **54 Issuance, 181 Submittal**. Counting the
Issuance rows off the rendered pages gives 51 on page 1 and 3 on page 2 — 54,
matching exactly. First and last rows match the first row of page 1 and the last
row of page 7 verbatim.

**The defect this document invites, and the producer avoids.** The blue
`Category | Library | Classification | Type Description` header band **repeats
mid-page** on pages 4, 5, 6 and 7 — Excel print headers reflowed into the body —
and several blank spacer rows appear between groups. A reader that took every
table row would ingest four header rows and several empty ones as data.

  rows whose any cell equals a header label: **0**
  rows with an empty type description: **0**

Both were checked directly against the producer's output. It excludes them.

Publisher defects preserved rather than repaired, each confirmed against the page:

- `H, O, G,` — trailing comma, on the Issuance `Certification of Generation for Tax Credit` row. The Submittal row for the same description reads `H, O, G` without it. Both kept as written.
- `H, E and RM` — prose `and` instead of a comma, not normalised.
- `Form 549D-Quarterly Transportation & Storage Report for Intrastate Natural Gas and Hinshaw Pipe` — the publisher's text stops at `Pipe`, almost certainly a cut-off `Pipelines`. Preserved.

## What this attestation is and is not

It **is** an independent comparison: the pages were read directly, and the
producer's code was not consulted while reading them.

It is **not** a `SourceSpec`. It does not run in CI, it does not re-execute on a
new capture, and it proves nothing about the *next* revision of either PDF —
both are dated documents (`June 2025`, `January 2025`) that FERC reissues. The
tests beside this file pin the facts checked here so a producer change breaks
them, but a *publisher* change would need this reading done again.

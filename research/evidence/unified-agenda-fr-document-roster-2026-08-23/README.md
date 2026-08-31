# Federal Register document roster — the publisher metadata behind eight damaged timetable citations

**2026-08-23.** Six Federal Register documents, captured verbatim from the
Register's own API, pinned by digest, and read at build time by
`src/refspec/registry/unified_agenda_parquet.py` so that eight
`unified_agenda_timetables.parquet` rows whose citation text nothing could read
are corroborated against the publisher instead of guessed at.

Five of the six are the documents the damaged rows meant. The sixth is in here
because it is the reading that has to LOSE, and a roster that does not hold the
competing reading cannot be said to have refused it.

`../ledger-2026-08-22/timetable-citations.md` is the census this roster acts on.
It read all twenty-one rows that failed that day against the publisher XML, the
Register and govinfo; thirteen of the twenty-one have since been answered from
the text by named grammars, and these eight are the residue no text can reach.
Every finding it records for these eight — the documents, the dates, the FCC
dockets, and the `1022091` tie — is reproduced here against pinned bytes.

## Provenance

| what | how |
| --- | --- |
| document metadata | `https://www.federalregister.gov/api/v1/documents/<document_number>.json` |
| the issue listing | `https://www.federalregister.gov/api/v1/documents.json?conditions[publication_date][is]=2024-12-17&fields[]=…` — the JSON records its own query as `"Documents published on 12/17/2024"` |
| the RIN searches | `https://www.federalregister.gov/api/v1/documents.json?conditions[term]=<rin>&fields[]=…` — each records `"Documents matching '<rin>'"` |
| fetched | 2026-08-23, read-only investigation, **no network at build time** |

Every response is stored under `receipts/` exactly as it arrived, and
`documents.csv` carries each row's `source_sha256` so the CSV and the bytes it
came from cannot drift apart. `scripts/build_documents_csv.py` rebuilds the CSV
from those receipts and nothing else.

```
e183c16d3d33d57c92ed6c4e869db154304dacb570fa696ff1e653f0efeca479  receipts/2016-23432.json
5a3a701f698e1d5436c5ddf9d3b2b43e39c178828383207b8194713ee0e78984  receipts/2020-09815.json
e924db7d3531763bfd0da514e02153173cb01495c6c66149e0715dd5d671c5ff  receipts/2020-21071.json
e12dc7eb6a3ef159d62b96f3948f1965e56ecafc1f2cb5e26a1b77f7f62334ba  receipts/2020-24486.json
ed714dda3b8ebbedd8918daf8b15f3b592ea9195ec3e6d46221b0a54dec6fe0d  receipts/2024-29238.json
6aea3e4921da3af46a8dd898f7ef29253f58476df2237ab26e1ed4b63ec6d698  receipts/issue-2024-12-17.json
34ac14a7dc13cdb099c2a44b91043819c907dfa61ee2f584365d325c88fd23dd  receipts/rinsearch-0648-BK86.json
06ea173b199703fbd077b378f9cf3f62fcfc2ffa00573a8b140de4aa3a87b7dc  receipts/rinsearch-1625-AC52.json
bcca78baad55c261e79bfa8288b2bf21365173eb9eff6f6d234b270da0d2e3c1  receipts/rinsearch-2040-AF62.json
1565f8e33d0e4f1f21135cf9d181b44657e1e05536e54f88857a025da86d7348  receipts/rinsearch-3060-AJ58.json
2c758b7307b7dcc8fcdff1fc14c4c0729710076a79fdc90d45e9eb3669684559  receipts/rinsearch-3060-AL15.json
77a1bcd59e99ff4ba102ffa4599b90f92b1553125b54b040f17ce40178d132e6  documents.csv
```

The builder pins `documents.csv` into every receipt it writes
(`producer.oracles`) and refuses to build without it, exactly as it does for the
congress.gov Public Law roster and the OFR subject index.

## The eight rows

`unified_agenda_timetables.parquet` carried 671,959 rows, of which exactly eight
said `parse_status = 'failed'`: the citation column held text and no grammar
could read it. They are damage to five real documents, and three of the five are
cited twice or three times because a rule's timetable is reprinted in every
later edition.

| RIN | edition | ordinal | action | date_text | `fr_citation_text` | → document | damage operator |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0648-BK86 | 202504 | 2 | NPRM | 12/17/2024 | `89 FR 1022091` | 2024-29238 (89 FR 102091) | page-doubled-digit |
| 0648-BK86 | 202510 | 2 | NPRM | 12/17/2024 | `89 FR 1022091` | 2024-29238 (89 FR 102091) | page-doubled-digit |
| 1625-AC52 | 202010 | 0 | NPRM | 10/05/2020 | `85 FSR 62651` | 2020-21071 (85 FR 62651) | label-insertion-medial-letter |
| 2040-AF62 | 201610 | 0 | ANPRM | 09/29/2016 | `81 NFR 66900` | 2016-23432 (81 FR 66900) | label-insertion-leading-letter |
| 3060-AJ58 | 202304 | 20 | NPRM and Order | 06/05/2020 | `85 DR 34525` | 2020-09815 (85 FR 34525) | label-substitution-adjacent-key |
| 3060-AL15 | 202204 | 1 | Final Action | 11/25/2020 | `85 FR 75770x` | 2020-24486 (85 FR 75770) | page-trailing-character |
| 3060-AL15 | 202210 | 1 | Final Action | 11/25/2020 | `85 FR 75770x` | 2020-24486 (85 FR 75770) | page-trailing-character |
| 3060-AL15 | 202304 | 1 | Final Action | 11/25/2020 | `85 FR 75770x` | 2020-24486 (85 FR 75770) | page-trailing-character |

Each operator is one named single-character edit, and a repair may spend only
one: either the LABEL is damaged and the page is read as the filer wrote it
(`NFR`, `FSR`, `DR`), or the label is a clean `FR` and the PAGE is damaged
(`1022091`, `75770x`). Nothing here composes two edits.

`D` for `F` is `label-substitution-adjacent-key` and not merely "a letter": the
two keys are neighbours on the QWERTY row the filer was typing on. `85 XR 34525`
would be refused — the name has to stay true, so the operator checks adjacency.

## The rule, and why the operator alone is never the corroboration

A repair is published only where **exactly one** candidate reading survives all
of:

1. the reading's `(volume, page)` equals a roster document's
   `(volume, start_page)` — the Register cites a document by the page it opens
   on, so a page that is merely INSIDE a document is not that document's
   citation;
2. the row's own `date_text` equals that document's `publication_date`;
3. a witness ties the filer to the document — the row's RIN is among the
   document's `regulation_id_numbers`, or, where the document lists none, the
   RIN's four-digit OMB agency code is one the roster records for it.

Two survivors would mean the roster contradicts itself, and the loader refuses a
roster holding two documents at one `(volume, start_page)` before any row is
read. A candidate that meets no roster document, or meets one on the wrong date,
or meets one that witnesses nothing about any filer, is not published: the row
stays `failed` and the citation text stays exactly as the filer wrote it.

## The `1022091` tie, which is what fixed the rule's shape

`89 FR 1022091` has **two** real single-digit-deletion readings in volume 89:

* delete one of the doubled `2`s → **102091**, which is
  **2024-29238**'s start page — NOAA, published 2024-12-17, and its
  `regulation_id_numbers` is `["0648-BK86"]`, the citing rule's own RIN.
* delete the last digit → **102209**, which is also a real page in volume 89: it
  sits inside **2024-29633**, `89 FR 102207–102211`, an SEC notice of a Nasdaq BX
  fee filing published the same day — visible in `receipts/issue-2024-12-17.json`,
  the whole 234-document issue for 2024-12-17.

So the damage operator alone decides nothing: both readings are one edit, both
land on a real page, both land on the right day. The builder generates BOTH —
`page-doubled-digit` for the first, `page-digit-dropped` for the second, and the
receipt counts the second at **zero rows** so its silence is measured rather than
assumed — and 102209 loses twice over:

* 102209 is not a start page. 2024-29633 begins at 102207, and the roster is
  keyed on start pages because that is what an FR citation names.
* 2024-29633 lists no RIN and the roster records no agency prefix for it, so it
  could witness nothing about RIN 0648-BK86 even if a reading did land on 102207.

That is why 2024-29633 is a roster row and not a footnote. The refusal is
executed, not narrated.

## The two FCC rows, whose documents name no RIN at all

`2020-09815` and `2020-24486` both carry `"regulation_id_numbers": []`. This is
not a gap in the capture — it is how the FCC files. The RIN searches pinned here
say so with numbers:

| search | documents | with a RIN listed |
| --- | --- | --- |
| `0648-BK86` | 2 | 2 |
| `1625-AC52` | 2 | 2 |
| `2040-AF62` | 7 | 3 |
| **`3060-AJ58`** | **20** | **0** |
| **`3060-AL15`** | **7** | **0** |

Every one of the 27 Federal Register documents that mentions either FCC RIN
lists an empty RIN field, and neither 2020-09815 nor 2020-24486 is even among
them — the RIN string appears nowhere in their text. The exact-RIN witness is
therefore unavailable in both directions, and what the research note records in
its place, and what `rin_agency_prefixes` carries into the roster, is:

* **the date** — 06/05/2020 and 11/25/2020, matching each document's
  `publication_date` exactly;
* **the agency** — RIN prefix `3060` is the FCC's OMB agency code, and both
  documents are `FEDERAL COMMUNICATIONS COMMISSION`;
* **the docket** — both name `GN Docket No. 20-32`, the 5G Fund proceeding, and
  both rules' titles are its NPRM-and-Order (`85 FR 34525`, "Establishing a 5G
  Fund for Rural America; Universal Service Reform-Mobility Fund") and its final
  Report and Order (`85 FR 75770`, "Establishing a 5G Fund for Rural America") —
  which is exactly the pair of actions RIN 3060-AJ58 and RIN 3060-AL15 file.

The docket is the one witness the code cannot check, because a timetable row has
no docket field; it is recorded here and it is why the agency prefix was accepted
as a stand-in rather than the rule being widened for everyone. The evidence
string on those three rows says which witnesses closed it —
`…-witnessed-by-date-and-rin-agency`, never `…-witnessed-by-date-and-rin`.

## Columns

| column | meaning |
| --- | --- |
| `document_number` | the Register's own identifier, and this roster's key |
| `volume`, `start_page`, `end_page` | the printed extent; `(volume, start_page)` is the join a citation makes |
| `publication_date` | ISO; the timetable's `date_text` is MM/DD/YYYY and is converted before comparison |
| `citation` | the publisher's own spelling of the citation the damaged text meant |
| `type`, `title` | what the document is, for a reader checking the repair by eye |
| `regulation_id_numbers` | `;`-joined; the exact-RIN witness where it is non-empty |
| `agencies` | `;`-joined `raw_name`s |
| `docket_ids` | `;`-joined; recorded, never machine-checked (a timetable row has no docket) |
| `rin_agency_prefixes` | `;`-joined OMB agency codes, written ONLY where `regulation_id_numbers` is empty and the note above verified the agency |
| `html_url` | the human page for the document |
| `fetched_at`, `source_sha256` | when the receipt was captured, and its digest |

`2024-29633` is the only row sourced from the issue listing rather than a
document response, and the listing carries no volume, publication date, agency
or URL: its volume is read off its own `citation`, its date is the issue the
listing names, and `agencies`, `docket_ids`, `rin_agency_prefixes` and
`html_url` are empty — which is also, and correctly, what makes it unable to
corroborate anything.

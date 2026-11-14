# Congress.gov legislative glossary reference

RefSpec can read the complete retained [Glossary of Legislative Terms](https://www.congress.gov/help/legislative-glossary)
as a pinned, offline reference. The reader preserves the literal terms,
definition HTML, readable definitions, authored links, order, and real page
anchors. It rejects byte or source-shape drift before producing a reference.

The reviewed capture contains 117 entries across the publisher's 21 alphabetic
sections. Its page title identifies Congress.gov and the Library of Congress.
The content does not identify a glossary author or a dated publisher edition;
the reference records both as `null`. CRS appears in definitions about CRS and
bill summaries. Those references do not establish CRS authorship of this page.
The existing CRS Legislative Subject Terms and Policy Areas readers retain
their separate attribution and scope.

## Selected source

| Fact | Pin |
| --- | --- |
| Official URL | `https://www.congress.gov/help/legislative-glossary` |
| Observation | `2026-11-14T18:34:36.547332Z` |
| SHA-256 | `501fab7f243c13cd402a5fa7c30a5e8e53f9f524b019cdf47c40774fa32d631e` |
| Body length | 418,089 bytes |
| Acquisition | One `ZyteHttpFetcher` request, `httpResponseBody`, HTTP 200, `text/html; charset=UTF-8` |
| Raw custody | `CaptureEvidence` / `CentralRawArchiveStore`; object `objects/sha256/50/501fab7f243c13cd402a5fa7c30a5e8e53f9f524b019cdf47c40774fa32d631e` |
| Reviewed source shape | Alternating `dt`/`dd` entries in `dl.cdg-dl-alpha` inside `div#help-content` |

The observation date identifies this captured response. It is not a publisher
edition date. Page fragments such as `#glossary_adjourn` are publisher-authored
locators within that response; they do not establish stable concept identifiers.
The reader preserves `glossary_partionednomination` exactly, including its spelling.
All 143 definition links are retained; every local definition fragment resolves
within the selected original. Link presence does not establish a semantic mapping.

The [raw visual review](../research/evidence/congress-legislative-glossary-2026-11-14/README.md)
binds representative source specimens and rendered images to this digest.
The maintained source-link manifest declares the complete original separately
from the small test excerpts. Set `REFSPEC_CONGRESS_LEGISLATIVE_GLOSSARY_PATH`
to the original to run its complete-source test without copying the raw object.

## Read and check

```sh
uv run --frozen python tools/read_congress_legislative_glossary.py \
  --source /path/to/raw/objects/sha256/50/501fab7f243c13cd402a5fa7c30a5e8e53f9f524b019cdf47c40774fa32d631e \
  --output output/congress-legislative-glossary-reference.json

REFSPEC_CONGRESS_LEGISLATIVE_GLOSSARY_PATH=/path/to/retained-original \
  uv run --frozen pytest tests/test_congress_legislative_glossary.py
```

The command creates a new JSON file and refuses to overwrite an existing file.
It reads at most 2 MiB plus one refusal byte and verifies the source digest and
length. The reader then checks the title, canonical URL, complete content region,
alphabetic sections, term/definition pairing, anchors, markup, and record count.
Readable text collapses layout whitespace and retains paragraph breaks; the HTML
fields preserve exact source slices, including italics and inline links.

The complete-source test independently compares every term, definition HTML,
and link with literal slices from the original. Negative fixtures and mutations
check lost definitions, duplicate anchors, changed headings, malformed or
unreviewed markup, empty definitions, challenge pages, changed pins, and the
byte bound. A new source capture requires its own source review and deliberate
pin update. This reference does not select or publish an Atlas generation or
connect a downstream consumer.

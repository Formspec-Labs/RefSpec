<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/coverage-readers5` at `d4b3d35b`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# Remaining source-fidelity readers

Date: 2026-08-13

## Result

This branch adds the five assigned reader kinds and 15 declarative source
comparisons. Together with the previously merged `pattern-row-v2` family, the
auditor now has an independent comparison for 106 of 110 construction units.
This branch started at 91 of 110 and added all 15 units assigned here.

Every assigned unit completed its own scoped run against the acceptance-passed
`atlas-3.1-full-2026-08-13b` distribution. All 15 runs authenticated the declared
publisher inputs, loaded the owned Atlas pack, reconstructed a nonempty record
set, and compared that set with Atlas. None ended in a reader or load error.
The runs report expected differences; they do not convert differences into
passes.

The four remaining uncovered units are unchanged:

- `ferc-docket-prefixes`
- `ferc-document-class-types`
- `unified-agenda-legal-authority-citation-types`
- `usgs-gnis-identifiers`

Their construction inputs contain only raw PDF bytes. They need an independently
reviewed text or JSON extract before a stock reader can compare source rows.

## Implemented reader parameters

All five readers use stock Python parsers. They do not import the production
registry or Extract, Transform, Load (ETL) code that built the distribution.

### `xml-record-selector-v1/1.0`

The XML reader takes an input role, namespace map, record XPath, field
declarations, optional exact record tags, optional regex captures, field
normalizers, optional row expansion and deduplication, row key, identity mode
and template, source-path and locator templates, claim map, native-payload JSON
template and fields, expected raw and projected counts, optional identity token
and observation time, SKOS-concept flag, and declared residue.

It uses `xml.etree.ElementTree`. The same reader handles the CBO feed and all
three Unified Agenda XML Schema Definition (XSD) lists through configuration
alone.

### `json-record-selector-v2/2.0`

The JSON reader takes an input role, record path, positional field map, exact
root and parent fields, optional header path and expected header values,
optional count path, row width and count, row key, identity mode and template,
source-path and locator templates, claim map, native-payload JSON template and
fields, SKOS-concept flag, and declared residue.

It uses `json` with duplicate-key rejection. The implementation removes the old
`API_CAPTURE_JSON_READER` construction-unit dispatch. Existing heterogeneous
JSON captures now select explicit source-shape readers, and GSDM uses this
declarative selector. No JSON reader branches on `spec.name`.

### `csv-record-selector-v2/2.0`

The CSV reader takes input and optional header roles, encoding, delimiter,
quote character, exact header, maximum and exact data-row counts, one or more
direct or distinct projections, projection constants, nonempty rules, label
discriminator and label-column rules, field validators, row key, identity mode
and template, optional identity token and observation time, source-path and
locator templates, claim map, native-payload JSON template and fields,
projected count, SKOS-concept flag, and declared residue.

It uses `csv`. The same reader handles a header-as-record list, full 330-column
provider records, and distinct values from a bulk personnel file.

### `ooxml-relational-v1/1.0`

The Office Open XML (OOXML) reader takes an input role, exact workbook sheet
list, named table declarations, sheet and header-row pins, exact headers, typed
cell projections, table constants, derived fields and validators, exact table
row counts, primary and union tables, result filters and sort keys, group keys,
declared joins and cardinality, aggregates, result derived fields, row key,
identity mode and template, optional identity token and observation time,
source-path and locator templates, claim map, native-payload JSON template and
fields, result count, SKOS-concept flag, and declared residue.

It uses `zipfile` and `xml.etree.ElementTree` to read workbook relationships,
shared strings, styles, and worksheet cells. Its fixed relational operations
cover all five workbooks; no source-specific workbook reader remains.

### `nrc-adams-multi-artifact-v1/1.0`

The NRC reader takes exactly six named inputs with paths, official source URLs,
and observation times; an ordered pattern list; optional named regions; row
patterns and exact match counts; whole, comma-joined, or selected coverage;
per-match or single-record projection; constants; structured row templates and
all-match collections; fixed template and SHA-256 derivations; row key;
identity and source templates; claim map; native-payload JSON template and
fields; result count; and declared residue.

It decodes UTF-8, applies `re`, and uses the common JSON template and identity
functions. One reader reconstructs both NRC projections from the same six
authenticated HTML and JavaScript inputs. The reader contains no per-unit
branch.

## Scoped results

Every row below also compares the exact construction input pins, pack
transport, record set and count, resource identity, source locator and digest,
and declared native payload. Every unit reports the already characterized
release-metadata class: Atlas adds `dcterms:issued` and `dcterms:identifier`
claims that the publisher bytes do not assert. The “Additional differences”
column records findings beyond that shared class. “Sample floor” means the
reader compared every record, but the global 200-label minimum correctly kept
the label check red for a small source.

| Construction unit | Reader | What was compared | Additional differences found |
| --- | --- | --- | --- |
| `cbo-119th-congress-publications` | XML | 1,058 publication IRIs, labels, dates, descriptions, bill numbers, and selected record payloads | None |
| `unified-agenda-priority-category` | XML | 6 documented values, labels, schema paths, identities, and payloads | Sample floor; XSD declarations outside the selected list are declared residue |
| `unified-agenda-rule-stage` | XML | 6 documented values, labels, schema paths, identities, and payloads | Sample floor; XSD declarations outside the selected list are declared residue |
| `unified-agenda-timetable-action` | XML | 34 documented values, labels, schema paths, identities, and payloads | Sample floor; XSD declarations outside the selected list are declared residue |
| `gsdm-online-data-dictionary-2026-08-03` | JSON | 457 element keys and names, all 18 mapped cells, labels, definitions, identities, count, and payloads | Architecture PDF context, document sections, display headers, and metadata beyond `total_rows` are declared residue |
| `nppes-data-dissemination-layout-v2-2026-08-03` | CSV | 330 columns, ordinals, labels, layout identifiers, and payloads | None |
| `nppes-npi-provider-sample-2026-08-03` | CSV | 3 NPIs, entity labels, all 330 source cells per row, header agreement, and payloads | Sample floor |
| `opm-plum-position-status-codes-2026-08-04` | CSV | 27 distinct nonempty status values from 15,777 rows, identities, labels, notations, and payloads | Sample floor; other columns, bulk rows, and empty cells are declared residue |
| `naics-2022` | OOXML | 2,125 codes, level-derived facets, labels, notations, identities, and payloads | None |
| `psc-april-2025` | OOXML | 2,344 active codes selected from 6,108 rows, labels, notations, identities, and payloads | Inactive rows, descriptive columns, and the Category Managers sheet are declared residue |
| `treasury-fast-book-accounts-parts-ii-iii-2026-07` | OOXML | 3,581 Part II/III account rows, Treasury Account Symbol keys, labels, identities, joined fields, and payloads | Intro/Changes sheets and publisher convenience-cell inconsistencies are declared residue |
| `treasury-fast-book-fund-types-parts-ii-iii-2026-07` | OOXML | 11 grouped fund types, labels, identities, account evidence, and payloads | Sample floor; Intro/Changes sheets are declared residue |
| `opm-ehri-data-standards-2026-08-04` | OOXML | 17,263 current field/code rows after declared joins, labels, notations, identities, and payloads | Field definitions without current values and past-only rows are declared lifecycle residue |
| `nrc-adams-native-controls-bounded-2026-08-03` | NRC | 19 ordered controls: 12 result fields, 2 library facets, and 5 help links; labels, identifier arrays, identities, and payloads | Sample floor; unused page prose and uncaptured parent JavaScript bytes are declared residue |
| `nrc-adams-identifier-shapes-2026-08-03` | NRC | 4 identifier shapes, labels, regex notations, definitions, samples, notes, identities, and payloads | Sample floor; HTML outside the selected statements and sibling control inputs are declared residue |

No assigned unit produced a new unexplained row-level mismatch. In particular,
all labels, notations, definitions, identities, locators, digests, and native
payloads named above matched exactly. The report cites rather than re-derives
the existing LDA class: LDA compares record-level publisher digests with Atlas
document-level digests. No LDA unit was part of this assignment.

## Coverage and tests

| Measure | Before this branch | After this branch |
| --- | ---: | ---: |
| Construction units with an independent comparison | 91/110 | 106/110 |
| Assigned units covered | 0/15 | 15/15 |
| Focused verifier test cases | 239 | 249 |
| Reader-kind faithful/fault test pairs added | 0 | 5 |

The earlier dry design began at 49 of 110. The merged 42-unit pattern family
raised that count to 91; this branch supplies the remaining 15 independently
parseable units. Each new reader kind has one parameterized test: the faithful
pair passes all checks, and a rewritten Atlas label makes label fidelity fail.

Verification used only the requested scoped commands. I did not run the
unscoped audit or the full build. All scoped processes completed without a
request for more memory or visible memory pressure; I did not collect an
operating-system peak-RSS measurement and therefore do not report a measured
maximum.

Required gates:

- `UV_NO_SYNC=1 make lint` — passed.
- `uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q` —
  249 passed in 5.32 seconds.

The first lint attempt let `uv` try to resolve the build backend and failed
because the sandbox has no network. Setting `UV_NO_SYNC=1` exercised the same
`make lint` target against the existing locked environment; it passed.

## Salvage from parked branches

I inspected `research/coverage-csv-pdf` at `22edee5a`/`70f3e706` and
`research/coverage-html-misc` at `aa113fe4`/`ba19c7fd` without merging either
branch.

Kept as source analysis:

- exact CSV encodings, roles, headers, source row counts, and NPPES row width;
- exact workbook sheet names, header rows, headers, typed cell shapes, join
  keys, row counts, active-row rules, Treasury grouping, and EHRI lifecycle
  distinctions;
- GSDM's JSON path, 18-cell row shape, count, and authenticated PDF context;
- CBO publication-link and XML-field behavior;
- Unified Agenda XSD containers, elements, documented option counts, and
  quoted versus plain expansion rules.

Discarded deliberately:

- per-source and per-construction-unit reader functions;
- every `spec.name` dispatch and configuration table keyed by a unit name;
- `openpyxl`, because the assigned reader requires stock ZIP/XML transport;
- old cache and loading code that predates the bounded-memory refactor;
- parked-branch tests tied to those discarded readers;
- PDF extract experiments outside these 15 units.

Neither parked branch contained a usable NRC semantic-union reader. I derived
that declaration from the six current pins and source shapes, then verified it
against both Atlas packs.

## Bespoke assessment

None of the 15 assigned units is genuinely bespoke. XML, JSON, CSV, and OOXML
each form a real declarative family. NRC needs its own reader kind because no
other reader performs an ordered semantic union across six HTML and JavaScript
inputs, but both NRC projections use that one reader without member-specific
code.

The four remaining PDF-only units are blocked by missing row-bearing inputs,
not by a need for four bespoke readers. Once checked extracts enter their
construction input lists, the existing pattern-row family can consume them.

## Commits

- `dfd43928` — XML, JSON, and CSV readers; seven declarations; JSON dispatch
  removal; three reader-kind fault pairs.
- `3008bfe3` — stock OOXML relational reader; five declarations; one
  reader-kind fault pair.
- `8421e777` — NRC multi-artifact reader; two declarations; one reader-kind
  fault pair.


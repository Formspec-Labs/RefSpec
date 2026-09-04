<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/coverage-patternrow` at `bb1a5bb4`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# `pattern-row-v2` source-fidelity coverage

Date: 2026-08-13

## Result

`pattern-row-v2/2.0` now covers all 42 construction units assigned to the
pattern-row family. The auditor covers 91 of the distribution's 110
construction units, up from the specified 54/110 baseline. This branch added
37 units; the five FEC units were already counted in the baseline and now use
the generalized reader.

One reader serves every member. Each member supplies declarative input,
region, row, normalization, identity, claim, payload, count, and residue data.
The reader contains no `spec.name` dispatch and imports no production registry
or ETL module.

Every added unit received a separate `--only` run against
`atlas-3.1-full-2026-08-13b/distribution`. Each run loaded at least one
publisher row and reached field-level comparisons. None ended in a load,
configuration, pin, pack, identity, count, or payload error. The receipts
reported honest differences rather than converting them into passes.

## Implemented parameter set

`SourceSpec.pattern_row` points to a `PatternRowSelector`. Its implemented
parameters are:

- `patterns`: one or more `PatternRowPattern` declarations. Each declares an
  exact `input_pattern`, named `region_pattern`, named-field `row_pattern`,
  expected input/region/row counts, constants, normalizers, row filters,
  optional per-pattern derived fields, and an optional per-pattern native
  payload template.
- `row_key`: a rendered key that must be non-empty and unique across the unit.
- `identity_mode` and `identity_template`: `publisher-iri`,
  `source-key-derived`, or `source-local-record` identity. Source-local records
  reproduce the independently implemented UUIDv7 seed.
- `source_locator_template`: the exact publisher locator retained by Atlas.
- `claim_map`: preferred and alternate labels, definitions, notations,
  observation time, identity hint, and source path. The reader requires one
  preferred label and one source path; source-local records also require an
  observation time.
- `native_payload_template_json` and `native_payload_fields`: a typed JSON
  template and its exact declared field set. Whole-field substitutions retain
  strings, integers, booleans, nulls, arrays, and objects.
- `expected_count`: the exact total row count across all patterns.
- `declared_unevaluated_fields`: explicit authenticated residue. An unused
  captured field that is absent from this list fails the read.
- `derived_fields`: source-independent template, canonical JSON SHA-256,
  URI-component, UUIDv7, source-local resource IRI, and fixed-width layout
  operations.

Built-in normalizers cover empty/sentinel nulls, presence and explicit boolean
values, whitespace, selected trailing characters, visible HTML text, HTML
entities and `sup` removal, Markdown bold text, case folding, and integers.
The fixed-width layout operation takes the captured header and declared page
metadata patterns; it reconstructs wrapped title or description columns and
fails on unknown indentation. This supports U.S. Courts without a
source-specific parser branch.

The reader validates exact input selection, UTF-8 decoding, region counts,
row counts, total counts, duplicate constants, duplicate captures, unknown
template fields, native-payload field declarations, supported claims,
supported identities, unique keys, and explicit disposition of every captured
field. It uses only Python standard-library text, HTML-fragment, JSON, hashing,
UUID, and URL operations.

## Scoped unit results

The differences column uses three codes:

- **M** — Atlas adds the already-characterized release metadata
  `dcterms:issued` and `dcterms:identifier`; the publisher bytes do not assert
  them.
- **F** — the selected unit has fewer than the audit's 200-label aggregate
  floor. The stated positive number of labels was still compared exactly.
- **R** — authenticated source content outside the selected row claims remains
  explicit residue; the parenthetical text names it.

Every scoped receipt also reports that the deliberately scoped registry is
globally incomplete. That is a property of `--only`, not a difference in the
selected unit. Except for M, F, and the stated R, all applicable identity,
label, notation, definition, locator, digest, native-payload, and count checks
passed.

| Unit | Publisher family | What was compared | Differences found |
| --- | --- | --- | --- |
| `billstatus-action-codes` | BILLSTATUS Markdown | 36 codes, labels, identifiers, payloads, identities, locators, counts | M; F; R (Markdown outside table) |
| `billstatus-bill-types` | BILLSTATUS Markdown | 8 codes, labels, chamber/type data, payloads, identities, locators, counts | M; F; R (Markdown outside table) |
| `billstatus-summary-version-codes` | BILLSTATUS Markdown | 88 codes, two notation forms, labels, descriptions, payloads, identities, locators, counts | M; F; R (Markdown outside table) |
| `fec-committee-designation` | FEC HTML | 6 codes, labels, definitions, identifiers, observation payloads, identities, locators, counts | M; F; R (surrounding HTML) |
| `fec-committee-type` | FEC HTML | 16 codes and labels, 15 definitions, identifiers, payloads, identities, locators, counts | M; F; R (surrounding HTML) |
| `fec-filing-frequency` | FEC HTML | 6 codes, labels, definitions, identifiers, payloads, identities, locators, counts | M; F; R (surrounding HTML) |
| `fec-organization-type` | FEC HTML | 6 codes, labels, definitions, identifiers, payloads, identities, locators, counts | M; F; R (surrounding HTML) |
| `fec-party` | FEC HTML | 95 codes and labels, 7 definitions, identifiers, payloads, identities, locators, counts | M; F; R (surrounding HTML) |
| `regulations-gov-docket-type` | Regulations.gov YAML | 2 enum values, labels, schema paths, payloads, identities, locators, counts | M; F; R (YAML outside enum) |
| `regulations-gov-document-type` | Regulations.gov YAML | 5 enum values, labels, schema paths, payloads, identities, locators, counts | M; F; R (YAML outside enum) |
| `regulations-gov-submitter-type` | Regulations.gov YAML | 3 enum values, labels, schema paths, payloads, identities, locators, counts | M; F; R (YAML outside enum) |
| `sam-assistance-assistance-types` | SAM Assistance HTML | 17 codes, labels, categories, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside tables) |
| `sam-assistance-eligible-applicant-types` | SAM Assistance HTML | 44 codes, labels, categories, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside tables) |
| `sam-assistance-eligible-beneficiary-types` | SAM Assistance HTML | 73 codes, labels, categories, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside tables) |
| `sam-opportunities-notice-types` | SAM Opportunities HTML | 11 codes, labels, retirement state, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside rows) |
| `sam-opportunities-opportunity-statuses` | SAM Opportunities HTML | 5 codes, labels, retirement state, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside rows) |
| `sam-opportunities-set-aside-codes` | SAM Opportunities HTML | 18 codes, labels, retirement state, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside rows) |
| `ferc-sectors` | FERC HTML | 6 option values, labels, payloads, order, identities, locators, counts | M; F; R (HTML outside control) |
| `ferc-security-levels` | FERC HTML | 4 option values, labels, payloads, order, identities, locators, counts | M; F; R (HTML outside control) |
| `ferc-accession-number-formats` | FERC HTML | 2 labels, formats/examples, payloads, identities, locators, counts | M; F; R (HTML outside control) |
| `grants-gov-eligibilities` | Grants.gov HTML | 17 codes, labels, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside table) |
| `grants-gov-funding-categories` | Grants.gov HTML | 26 codes, labels, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside table) |
| `oira-review-controls` | OIRA HTML | 20 rows across four controls: resource, code, label, payload, identity, locator, count | M; F; R (control markup/placeholders) |
| `oversight-report-types` | Oversight.gov HTML | 10 values, labels, identifiers, payloads, order, identities, locators, counts | M; F; R (HTML outside select) |
| `sec-series-categories` | SEC HTML | 19 category identities, labels, definitions, links, locators, counts | M; F; R (duplicate navigation and surrounding HTML) |
| `scotus-opinion-types` | Supreme Court HTML | 7 opinion-type identities, labels, order, locators, counts | M; F; R (navigation/version text outside rows) |
| `census-function-items` | Census finance HTML | 33 codes, labels, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside rows) |
| `census-data-flags` | Census finance HTML | 16 codes, labels, sections, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside rows) |
| `nasbo-program-areas` | NASBO HTML | 7 publisher titles, order, payloads, identities, locators, counts; no code invented | M; F; R (HTML outside chapter titles) |
| `pra-icr-controls` | PRA HTML | 21 control values, labels, groups, two-identifier rows, payloads, identities, locators, counts | M; F; R (HTML outside controls) |
| `epa-comptox-substance-bounded-2026-08-03` | EPA CompTox HTML | 1 DTXSID identity and preferred label; DTXSID, DTXCID, CASRN, TSCA state, source URI, and payload | M; F; R (HTML outside identifiers) |
| `fac-api-field-dictionary-2026-08-03` | FAC HTML | 163 endpoint/field keys, labels, definitions, types, legacy names, identifiers, payloads, locators, counts | M; F; R (one duplicate accepted-date row and HTML outside tables) |
| `census-acs-geography-identifiers` | Census ACS HTML | 7 names, labels, identifier authority data, required/type/group fields, span digests, payloads, identities, locators, counts | M; F; R (attributes, excluded rows, full page, limit) |
| `census-tiger-geoid-structure` | Census TIGER HTML | 14 structure/example rows, digit structures, names, example GEOIDs, span digests, payloads, identities, locators, counts | M; F; R (header, footnotes, full page) |
| `gao-cra-database-facets-2026-08-04` | GAO CRA HTML | 6 facet values, labels, default state, identifiers, payloads, identities, locators, counts | M; F; R (HTML outside facets) |
| `gao-report-gao-26-108505` | GAO product HTML | 1 publication IRI, number, title, date, topic assignment, payload, locator, count | M; F; R (HTML outside product/topic claims) |
| `gao-topics-observed-on-gao-26-108505` | GAO product HTML | 1 observed topic label/path, report association, payload, source-local identity, locator, count | M; F; R (product fields outside topic observation) |
| `courtlistener-jurisdictions-2026-08-03` | CourtListener HTML | 3,359 IDs, names, citation abbreviations, jurisdiction types, dates, in-use states, ordinals, null shapes, payloads, identities, locators, counts | M; R (volatile count, homepage, homepage attributes) |
| `omb-a11-functional-classification` | OMB checked PDF text | 98 function/subfunction codes, labels, categories, identifiers, payloads, source-local identities, locators, counts; PDF and text pins | M; F; R (page headings/grouping/narrative) |
| `omb-a11-object-classification` | OMB checked PDF text | 38 Schedule O and appendix code pairs, labels, identifiers, payloads, identities, locators, counts; PDF and text pins | M; F; R (page headings/grouping/narrative) |
| `omb-a11-apportionment-categories` | OMB checked PDF text | 8 category/range or non-apportioned codes, labels, identifiers, payloads, identities, locators, counts; PDF and text pins | M; F; R (page headings/grouping/narrative) |
| `uscourts-nature-of-suit` | U.S. Courts checked layout text | 93 codes, wrapped titles/descriptions, definitions, section IDs, observation IDs, payloads, source-local identities, locators, counts; PDF and text pins | M; F; R (page metadata, headings, document note) |

The M class is cited from the sibling design report; this branch does not
re-derive it. The same report cites the separate LDA record-level versus
document-level digest class. No digest difference here substitutes for an
identity, claim, payload, locator, or count comparison. See
`../codex-coverage-dry/REPORT.md`, especially “Scoped results” and its cited
JSON campaign report.

## Coverage arithmetic

| Measure | Before | Added here | After |
| --- | ---: | ---: | ---: |
| Construction units with executable publisher comparison | 54 | 37 | 91 |
| Intended `pattern-row-v2` units covered | 5 | 37 | 42 of 42 |
| Uncovered construction units | 56 | -37 | 19 |

The 19 remaining units stay in their assigned reader families:

- XML records: `cbo-119th-congress-publications`,
  `unified-agenda-priority-category`, `unified-agenda-rule-stage`, and
  `unified-agenda-timetable-action`.
- JSON records: `gsdm-online-data-dictionary-2026-08-03`.
- CSV records: `nppes-data-dissemination-layout-v2-2026-08-03`,
  `nppes-npi-provider-sample-2026-08-03`, and
  `opm-plum-position-status-codes-2026-08-04`.
- OOXML relational tables: `naics-2022`, `psc-april-2025`,
  `treasury-fast-book-accounts-parts-ii-iii-2026-07`,
  `treasury-fast-book-fund-types-parts-ii-iii-2026-07`, and
  `opm-ehri-data-standards-2026-08-04`.
- NRC multi-artifact records: `nrc-adams-identifier-shapes-2026-08-03` and
  `nrc-adams-native-controls-bounded-2026-08-03`.
- Raw-PDF blocked rows: `ferc-docket-prefixes`,
  `ferc-document-class-types`,
  `unified-agenda-legal-authority-citation-types`, and
  `usgs-gnis-identifiers`.

## Salvage from parked branches

I inspected both parked branches with `git show`; I did not merge or cherry-pick
them.

`research/coverage-html-misc` supplied useful source analysis: exact pins,
publisher regions, row shapes, expected counts, identity hints, and source
quirks for BILLSTATUS, Census, CourtListener, EPA, FAC, FERC HTML, GAO,
Grants.gov, NASBO, OIRA, Oversight, PRA, Regulations.gov, SAM, SCOTUS, and SEC.
That analysis shortened source discovery and exposed dead ends such as
volatile CourtListener fields and duplicate FAC rows.

`research/coverage-csv-pdf` supplied the OMB and U.S. Courts PDF/text pins,
checked-extract provenance, expected counts, and row-shape analysis. It also
confirmed that the two FERC PDF tables, Unified Agenda legal-authority types,
and USGS GNIS descriptions have only raw PDFs in the current construction
inputs.

I discarded both branches' implementation code. It targets the old
pre-bounded-memory auditor, predates language-scope work, dispatches through
source-specific readers, and uses per-unit checked semantic extracts. Merging
it would restore the code shape this task was meant to remove. I re-expressed
only sound source facts as declarative `pattern-row-v2` entries and compared
them against the current distribution.

## Bespoke and blocked findings

None of the 42 target units is bespoke. Every target uses the same reader with
configuration alone.

The two NRC units remain the one genuinely source-specific reader kind. Six
HTML and JavaScript artifacts contribute different semantic rows, so treating
them as one input/region/row stream would require a workflow language in the
configuration. They should share one bounded NRC reader, not receive two
per-unit readers.

The four raw-PDF units are blocked, not bespoke. An authenticated PDF pin
compares no publisher rows. Each needs a reviewed text or JSON extract added
to the construction inputs; after that, a declarative `pattern-row-v2` entry
can cover it. Adding an auditor-only semantic extract or importing the
production PDF ETL would break the independence rule.

The CBO, NPPES, OPM, Treasury, NAICS, PSC, GSDM, and three Unified Agenda XSD
units need their already assigned generic structured readers. They may require
complex declarations, but they do not justify source-specific reader code.

## Verification and delivery

I ran one scoped command for every target unit using:

```text
uv run --no-sync python tools/verify_atlas_source_fidelity.py \
  --distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13b/distribution \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --only <unit> --output /tmp/codex-patternrow-<unit>.json
```

The required gates pass in the existing environment:

```text
UV_NO_SYNC=1 make lint
All checks passed!

uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q
239 passed
```

The extra test is reader-level, not per-spec. It proves that fixed-width
wrapped and cross-page columns pass and an unknown continuation fails. The
general reader retains the faithful-pair and rewritten-label fault tests that
replaced the old FEC-reader pair.

No unscoped audit or Atlas build ran. The final CourtListener scoped receipt
reports 19 uncovered units, which reconciles to 91/110. `/usr/bin/time -l`
could not report resident memory in this sandbox because `sysctl
kern.clockrate` is unavailable; the run remained scoped and completed in 5.18
seconds. This report does not invent an RSS figure.

The implementation landed in publisher-family commits. The principal commits
are `65b2e572` (reader and FEC), `b5e95765` (BILLSTATUS), `6a265f39`
(Regulations.gov), `008739a3` and `ecf64d4c` (SAM), `6d17a442` (FERC HTML),
`2066dd53` (Grants.gov), `9f88bd51` (OIRA), `56a8936e` (Oversight),
`56b3ece6` (SEC), `4eed665f` (SCOTUS), `8266ad8c` (Census finance and NASBO),
`1d24bd8d` (PRA), `7adb81e0` (EPA), `a99cd46c` (FAC), `8f202047` (Census
geography), `347505fb` (GAO), `83d591c5` (CourtListener), `950b85b2` (OMB),
`e84d4bc6` (U.S. Courts), and `c79b7af3` (fixed-width fault test).

An earlier `54c5ea19` batch put three XSD enumerations in this reader. Commit
`9727e0b5` removes that batch because the authoritative design assigns those
units to `xml-record-selector-v1`. The attempted targeted revert conflicted
beside later declarations, so I aborted it, removed only the intended block,
and compared both versions with `ast`. Every class's annotated fields matched,
and `_unified_agenda_pattern_source` was the only removed function.

The reference checkout and both named `output/` trees remained read-only. The
untracked `CODEX_LOG.txt` and `PROMPT.txt` files in this disposable worktree
were not edited or committed.

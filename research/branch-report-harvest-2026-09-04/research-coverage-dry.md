<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/coverage-dry` at `bec635c8`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# Source-fidelity coverage design

Date: 2026-08-13

## Result

The current auditor covers 49 of the distribution's 110 construction units.
Sixty-one units remain. The 14 `regulatory-native-*` units are already covered;
they belong to the generated `NATIVE_CONTROL_SOURCES` tuple and therefore do
not appear as 14 literal `SourceSpec(...)` calls. They are not candidates for
the proving prototype in this worktree.

The smallest useful design is **six reader kinds**, not 61 bespoke readers.
Five are reusable format-and-row readers. The sixth is a bounded NRC
multi-artifact reader shared by its two construction units. Those readers can
compare 57 units from the inputs sealed today. Four raw-PDF-only units have no
independently parseable input under the auditor's permitted parser set. They
need checked text or JSON extracts; once those inputs exist, the same text-row
reader covers them and the total remains six kinds.

This worktree proves the highest-payoff genuine family available after the
inventory correction: all five FEC units. One `html-code-list-v1/1.0` reader
uses five declarative selectors and contains no spec-name dispatch. Each
scoped run loaded the authenticated publisher bytes and Atlas pack, compared
the intended records exactly, and reported honest differences. The prototype
raises executable coverage from 49 to 54 units if adopted.

## Authoritative uncovered inventory

I derived this list as a set difference, without running the unscoped audit:

1. Parse `tools/verify_atlas_source_fidelity.py` with Python's `ast` module.
2. Read every literal `release_keys` tuple in the top-level `SOURCES` tuple.
3. Expand `*NATIVE_CONTROL_SOURCES` from all 14 rows in
   `_NATIVE_CONTROL_SELECTORS`, using the declared
   `regulatory-native-{control_id}` key rule.
4. Read all `.releases[].key` values from the distribution's sealed
   `atlas-construction-summary.json`.
5. Check uniqueness in both sets and subtract the expanded declarations from
   the construction keys.

The checks produced 35 literal declarations, 14 generated declarations, 49
unique covered keys, 110 unique construction keys, no duplicate covered key,
and no declared key absent from the construction summary. The difference is
the following 61 units:

```text
billstatus-action-codes
billstatus-bill-types
billstatus-summary-version-codes
cbo-119th-congress-publications
census-acs-geography-identifiers
census-data-flags
census-function-items
census-tiger-geoid-structure
courtlistener-jurisdictions-2026-08-03
epa-comptox-substance-bounded-2026-08-03
fac-api-field-dictionary-2026-08-03
fec-committee-designation
fec-committee-type
fec-filing-frequency
fec-organization-type
fec-party
ferc-accession-number-formats
ferc-docket-prefixes
ferc-document-class-types
ferc-sectors
ferc-security-levels
gao-cra-database-facets-2026-08-04
gao-report-gao-26-108505
gao-topics-observed-on-gao-26-108505
grants-gov-eligibilities
grants-gov-funding-categories
gsdm-online-data-dictionary-2026-08-03
naics-2022
nasbo-program-areas
nppes-data-dissemination-layout-v2-2026-08-03
nppes-npi-provider-sample-2026-08-03
nrc-adams-identifier-shapes-2026-08-03
nrc-adams-native-controls-bounded-2026-08-03
oira-review-controls
omb-a11-apportionment-categories
omb-a11-functional-classification
omb-a11-object-classification
opm-ehri-data-standards-2026-08-04
opm-plum-position-status-codes-2026-08-04
oversight-report-types
pra-icr-controls
psc-april-2025
regulations-gov-docket-type
regulations-gov-document-type
regulations-gov-submitter-type
sam-assistance-assistance-types
sam-assistance-eligible-applicant-types
sam-assistance-eligible-beneficiary-types
sam-opportunities-notice-types
sam-opportunities-opportunity-statuses
sam-opportunities-set-aside-codes
scotus-opinion-types
sec-series-categories
treasury-fast-book-accounts-parts-ii-iii-2026-07
treasury-fast-book-fund-types-parts-ii-iii-2026-07
unified-agenda-legal-authority-citation-types
unified-agenda-priority-category
unified-agenda-rule-stage
unified-agenda-timetable-action
uscourts-nature-of-suit
usgs-gnis-identifiers
```

The construction summary at
`/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13/atlas-construction-summary.json`
is the authority for the 110 keys, input pins, adapter recipes, pack ownership,
and record counts. `tools/verify_atlas_source_fidelity.py:5036-5107` establishes
the tuple-expanded native-control declarations, and
`tools/verify_atlas_source_fidelity.py:7759-9193` establishes the complete
`SOURCES` registry.

## What counts as one reader kind

A reader kind has one stock parser or bounded text parser and one stable
record-selection algorithm. A member may vary only declarative data: input
role, section and row selectors, field names, validation rules, identity mode,
source locator, claim mapping, and expected count. The reader may not dispatch
on `spec.name`, call a registry parser, or accept a Python callback.

This boundary matters to the count. Calling a multiplexer for JSON, XML, CSV,
OOXML, and HTML “one reader” would reduce a label, not implementation. At the
other extreme, calling every table layout a reader would reproduce the current
bespoke campaign. The six kinds below are the minimum at which the parser and
record algebra remain real, testable units. Their configuration is data, not a
second programming language.

Identity terms in the family map mean:

- **source-local record**: derive the Atlas member from the authenticated
  source artifact, source path, and observed value; the publisher did not mint
  a reusable member IRI.
- **source-scoped key**: derive the member from a publisher code or composite
  key plus the source IRI.
- **publisher key**: derive the member from an identifier the publisher owns,
  such as an NPI, DTXSID, TAS, or GAO publication identifier.
- **publisher IRI**: retain a publisher URL as the member identity.

For every row below, “compare” includes the authenticated input pin, Atlas pack
transport, resource set/count, member identity, source locator and digest, and
the named row claims. Any source field not named is counted and reported as
unevaluated; it is never silently treated as an Atlas match.

## Family map

### 1. Pattern rows: 42 units now, 46 after four checked extracts

This family decodes one or more bounded UTF-8 inputs, selects a declared
region, and applies a declared row pattern with named fields. HTML fragment
text, Markdown tables, YAML enum blocks, and checked PDF text differ only in
configuration. The reader requires an exact section count, row count, order or
key set, unique identities, and an explicit mapping of fields to labels,
notations, definitions, status, and native-payload claims.

The parameters that vary are `inputs`, `section_pattern`, `row_pattern`,
`field_normalizers`, `row_filter`, `row_key`, `identity_mode`,
`identity_template`, `source_locator_template`, `claim_fields`,
`native_payload_fields`, `expected_count`, and
`declared_unevaluated_fields`. `html_visible_text` is a bounded built-in
normalizer, not member-specific code.

| Unit | Publisher input and registry module | Format and source row | Identity | What is compared |
| --- | --- | --- | --- | --- |
| `billstatus-action-codes` | `billstatus-xml-user-guide-2026-08-03.md`; `billstatus_codes` | Markdown pipe-table row | source-local record | 36 action codes, labels, use text, flags, exact row payload |
| `billstatus-bill-types` | `billstatus-xml-user-guide-2026-08-03.md`; `billstatus_codes` | Markdown pipe-table row | source-local record | 8 bill-type codes, labels, chamber/type fields, exact row payload |
| `billstatus-summary-version-codes` | `billstatus-xml-user-guide-2026-08-03.md`; `billstatus_codes` | Markdown pipe-table row | source-local record | 88 version codes, labels, descriptions, exact row payload |
| `census-acs-geography-identifiers` | `acs-variables-2026-08-03.html`; `census_geo_codes` | selected ACS variable table rows | source-local record | 7 selected names, labels, concepts, required/type/group fields, exact row payload |
| `census-data-flags` | `census-aspep-data-flag-codes-2026-08-03.html`; `census_gov_finance_codes` | section header plus code/definition row | source-local record | 16 codes, definitions, sections, identifiers, exact row payload |
| `census-function-items` | `census-aspep-function-item-codes-2026-08-03.html`; `census_gov_finance_codes` | `CODE = Label` table cell | source-local record | 33 codes, labels, identifiers, exact row payload |
| `census-tiger-geoid-structure` | `geoid-structure-2026-08-03.html`; `census_geo_codes` | structure table plus example table | source-local record | 14 selected area/example rows, digit structures, names and example GEOIDs |
| `courtlistener-jurisdictions-2026-08-03` | `courtlistener-jurisdictions-zyte.html`; `courtlistener_codes` | rich HTML table row | source-scoped key | 3,359 IDs, names, citation abbreviations, type, dates, in-use status, ordinal, exact row payload |
| `epa-comptox-substance-bounded-2026-08-03` | `comptox-DTXSID7020182.normalized.html`; `epa_srs_substances` | one bounded substance page | publisher key | DTXSID/DTXCID/CASRN, preferred name, TSCA inventory status and exact source URI |
| `fac-api-field-dictionary-2026-08-03` | `fac-api-dictionary-2026-08-03.html`; `fac_dictionary` | endpoint section plus field row | publisher key | 163 endpoint/field keys, labels, types, descriptions, legacy names, exact row payload |
| `fec-committee-designation` | `fec-committee-master-file-description-2026-08-03.html`; `fec_committee_codes` | code/label list | source-local record | 6 codes, labels, identifiers and complete native payload |
| `fec-committee-type` | `fec-committee-type-code-descriptions-2026-08-03.html`; `fec_committee_codes` | code/label/description table | source-local record | 16 codes and labels, 15 descriptions, identifiers and complete native payload |
| `fec-filing-frequency` | `fec-committee-master-file-description-2026-08-03.html`; `fec_committee_codes` | code/label list | source-local record | 6 codes, labels, identifiers and complete native payload |
| `fec-organization-type` | `fec-committee-master-file-description-2026-08-03.html`; `fec_committee_codes` | code/label list | source-local record | 6 codes, labels, identifiers and complete native payload |
| `fec-party` | `fec-party-code-descriptions-2026-08-03.html`; `fec_committee_codes` | code/label/optional-description table | source-local record | 95 codes and labels, 7 descriptions, identifiers and complete native payload |
| `ferc-accession-number-formats` | `ferc-accessibility-tips.html`; `ferc_elibrary_codes` | labeled format examples | source-local record | 2 format labels, patterns/examples and exact row payload |
| `ferc-sectors` | `ferc-general-search-help.html`; `ferc_elibrary_codes` | select option | source-local record | 6 option values and labels, order and exact row payload |
| `ferc-security-levels` | `ferc-general-search-help.html`; `ferc_elibrary_codes` | select option | source-local record | 4 option values and labels, order and exact row payload |
| `gao-cra-database-facets-2026-08-04` | `gao-cra-database-real-capture-2026-08-04.html`; `gao_cra_facets` | search-facet group | publisher key | 6 facet IDs/names, option values/labels/counts and exact group payload |
| `gao-report-gao-26-108505` | `gao-product-gao-26-108505-2026-08-04.html`; `gao_topics` | one product record | publisher IRI | publication ID/URL, title, date, description and product metadata |
| `gao-topics-observed-on-gao-26-108505` | `gao-product-gao-26-108505-2026-08-04.html`; `gao_topics` | topic link on product record | source-local record | observed topic label/link and its relationship to the report |
| `grants-gov-eligibilities` | `grants-gov-status-codes-2026-08-03.html`; `grants_gov_codes` | section table row | source-local record | 17 eligibility codes, labels/descriptions and exact row payload |
| `grants-gov-funding-categories` | `grants-gov-status-codes-2026-08-03.html`; `grants_gov_codes` | section table row | source-local record | 26 category codes, labels/descriptions and exact row payload |
| `nasbo-program-areas` | `nasbo-ser-program-area-chapters-2026-08-03.html`; `census_gov_finance_codes` | chapter table cell | source-local record | 7 publisher titles and order; no code is invented where the source has none |
| `oira-review-controls` | `ruleStage.html`, `meetingStatus.html`, `concludedAction.html`, `reviewStatus.html`; `oira_review_codes` | select options across four pages | source-local record | 20 resource-name/code/label rows, source page and exact payload |
| `oversight-report-types` | `oversight-reports-federal-2026-08-03.html`; `oversight_report_types` | select option | source-local record | 10 values, labels, order and exact row payload |
| `pra-icr-controls` | `pra-search-2026-08-03.html`; `pra_icr_codes` | several bounded controls | source-local record | 21 control names/values/labels, groups and exact row payload |
| `regulations-gov-docket-type` | `regulations-gov-openapi-v4-2026-08-03.yaml`; `regulations_gov_codes` | named YAML enum block | source-local record | 2 enum values/labels, schema path and exact row payload |
| `regulations-gov-document-type` | `regulations-gov-openapi-v4-2026-08-03.yaml`; `regulations_gov_codes` | named YAML enum block | source-local record | 5 enum values/labels, schema path and exact row payload |
| `regulations-gov-submitter-type` | `regulations-gov-openapi-v4-2026-08-03.yaml`; `regulations_gov_codes` | named YAML enum block | source-local record | 3 enum values/labels, schema path and exact row payload |
| `sam-assistance-assistance-types` | `sam-assistance-listings-api-2026-08-03.html`; `sam_assistance_listing_codes` | named documentation table | source-local record | 17 codes, labels/descriptions and exact row payload |
| `sam-assistance-eligible-applicant-types` | `sam-assistance-listings-api-2026-08-03.html`; `sam_assistance_listing_codes` | named documentation table | source-local record | 44 codes, labels/descriptions and exact row payload |
| `sam-assistance-eligible-beneficiary-types` | `sam-assistance-listings-api-2026-08-03.html`; `sam_assistance_listing_codes` | named documentation table | source-local record | 73 codes, labels/descriptions and exact row payload |
| `sam-opportunities-notice-types` | `sam-get-opportunities-public-api-2026-08-03.html`; `sam_opportunities_codes` | named documentation table | source-local record | 11 codes, labels/descriptions and exact row payload |
| `sam-opportunities-opportunity-statuses` | `sam-get-opportunities-public-api-2026-08-03.html`; `sam_opportunities_codes` | named documentation table | source-local record | 5 codes, labels/descriptions and exact row payload |
| `sam-opportunities-set-aside-codes` | `sam-get-opportunities-public-api-2026-08-03.html`; `sam_opportunities_codes` | named documentation table | source-local record | 18 codes, labels/descriptions and exact row payload |
| `scotus-opinion-types` | `scotus-opinions-2026-08-03.html`; `scotus_opinion_types` | bounded opinion-type row | source-local record | 7 type values, labels/descriptions, order and exact row payload |
| `sec-series-categories` | `sec-rules-regulations-2026-08-03.html`; `sec_series_categories` | series/category link row | source-local record | 19 category IDs, labels, links, order and exact row payload |
| `omb-a11-apportionment-categories` | `omb-a11-2025-wayback.pdf` plus `section-120-13-apportionment-categories-2025.txt`; `omb_a11_budget_codes` | checked text table | source-local record | 8 category codes, labels/descriptions and text locators; PDF and extract pins both authenticate |
| `omb-a11-functional-classification` | `omb-a11-2025-wayback.pdf` plus `exhibit-79a-functional-classification-2025.txt`; `omb_a11_budget_codes` | checked text table | source-local record | 98 function/subfunction codes, labels, levels and line locators |
| `omb-a11-object-classification` | `omb-a11-2025-wayback.pdf` plus `exhibit-83a-object-classification-2025.txt`; `omb_a11_budget_codes` | checked text table | source-local record | 38 object-class codes, labels, levels and line locators |
| `uscourts-nature-of-suit` | `js_044_code_descriptions.pdf` plus `js_044_code_descriptions.layout.txt`; `nature_of_suit_codes` | checked layout-text row | source-local record | 93 codes, labels/descriptions, category/order and text locators |

Four more units join this family only after an independently reviewed extract
is added as a construction input. They are listed under “blocked and bespoke”
below. A raw PDF pin authenticates bytes but supplies no rows to compare.

### 2. XML record selection: 4 units

One ElementTree-based reader takes a namespace map, record XPath, field XPaths,
row filter, regex captures/templates, identity rule, expected key set/count,
and claim mapping. It generalizes the existing XML label-tree reader from a
fixed tree to declarative record selection.

| Unit | Publisher input and registry module | Source row | Identity | What is compared |
| --- | --- | --- | --- | --- |
| `cbo-119th-congress-publications` | `cbo-119congress-cost-estimates-2026-08-04.xml`; `cbo_topic_codes` | one feed publication element | publisher IRI | 1,058 publication URLs/IDs, titles, dates, descriptions, bill numbers and exact selected payload |
| `unified-agenda-priority-category` | `reginfo-rin-data-ver10262011.xsd`; `unified_agenda_codes` | documented XSD enumeration | source-local record | 6 enum values, documentation labels and schema paths |
| `unified-agenda-rule-stage` | `reginfo-rin-data-ver10262011.xsd`; `unified_agenda_codes` | documented XSD enumeration | source-local record | 6 enum values, documentation labels and schema paths |
| `unified-agenda-timetable-action` | `reginfo-rin-data-ver10262011.xsd`; `unified_agenda_codes` | documented XSD enumeration | source-local record | 34 enum values, documentation labels and schema paths |

### 3. JSON dictionary records: 1 unit

This generalizes the campaign's API-capture JSON reader by replacing its
spec-name dispatch table with JSON path, row-key, field-map, identity, and
expected-count configuration.

| Unit | Publisher inputs and registry module | Source row | Identity | What is compared |
| --- | --- | --- | --- | --- |
| `gsdm-online-data-dictionary-2026-08-03` | `gsdm-data-dictionary-2026-08-03.json` (`completeOnlineDataDictionary`) plus pinned architecture PDF; `usaspending_gsdm_codes` | one dictionary element with an 18-cell map | publisher key | 457 element keys/names, all cells, labels/definitions, identifiers and exact row payload; PDF is authenticated context, not silently treated as parsed rows |

### 4. CSV records and distinct values: 3 units

This reader generalizes the existing GCMD CSV reader. Parameters are encoding,
dialect, input roles, exact headers, direct-row or distinct-value mode, key
columns, filters, sort/order rule, identity policy, claim mapping, and expected
count. The NPPES two-input case declares one schema input and one data input;
the same algorithm verifies header agreement before reading rows.

| Unit | Publisher inputs and registry module | Source row | Identity | What is compared |
| --- | --- | --- | --- | --- |
| `nppes-data-dissemination-layout-v2-2026-08-03` | `npidata_pfile_fileheader_v2.csv`; `nppes_npi_identifiers` | one header column by ordinal | publisher key | 330 column names, ordinals, layout identifiers and exact payload |
| `nppes-npi-provider-sample-2026-08-03` | `npidata_pfile_fileheader_v2.csv` plus `npidata_pfile_sample_v2.csv`; `nppes_npi_identifiers` | one 330-field provider row | publisher key | 3 NPIs, entity type/name, all source columns, header agreement and exact row payload |
| `opm-plum-position-status-codes-2026-08-04` | `OPM-PLUM-all-data-20260804.csv`; `opm_workforce_codes` | distinct non-empty `PositionStatus` value | source-scoped key | 27 status values, labels, observed occurrence basis and exact distinct-value payload |

### 5. OOXML relational tables: 5 units

One stock OOXML reader uses `zipfile` and ElementTree for workbook metadata,
shared strings, styles, and worksheets. Its bounded relational plan supports
sheet selection, exact headers, row projection, regex validation, joins by
declared keys, grouping, distinct values, and counts. Those operations are
enough for all five workbooks without a unit-name branch. Arbitrary callbacks
and expressions are not allowed.

This kind generalizes the GCMD CSV row model with an OOXML transport and a
small relational layer. The layer earns its cost across 25,324 represented
records and has invariants that fault tests can break: wrong sheet/header,
duplicate key, dangling join, wrong group count, changed cell, or reordered
key set.

| Unit | Publisher input and registry module | Source row/operation | Identity | What is compared |
| --- | --- | --- | --- | --- |
| `naics-2022` | `2-6-digit_2022_Codes.xlsx`; `naics_psc_codes` | selected worksheet row and hierarchy fields | source-scoped key | 2,125 codes, titles, levels/hierarchy, source row and exact payload |
| `psc-april-2025` | `PSC-April-2025-wayback.xlsx`; `naics_psc_codes` | selected worksheet row | source-scoped key | 2,344 PSC codes, names, category/status fields, source row and exact payload |
| `treasury-fast-book-accounts-parts-ii-iii-2026-07` | `fast-book-part-ii-iii-2026-07-31.xlsx`; `treasury_tas_fast_book` | Part II/III rows grouped by exact TAS | publisher key | 3,581 TAS identities, every published row, duplicate counts, agency/account/fund/date fields and publisher anomalies |
| `treasury-fast-book-fund-types-parts-ii-iii-2026-07` | `fast-book-part-ii-iii-2026-07-31.xlsx`; `treasury_tas_fast_book` | distinct fund type grouped by Part II/III | publisher key | 11 exact fund-type labels, represented parts and account counts by part |
| `opm-ehri-data-standards-2026-08-04` | `EHRI-Data-Standards-20260804.xlsx`; `opm_workforce_codes` | each `CurrentValues` row joined to `AllDataElements` and matching `PastValues` | source-scoped key | 17,263 field/code identities, explanations, dates, field metadata, current status and complete past lifecycle |

### 6. NRC ADAMS multi-artifact records: 2 units

NRC is the one genuine source-specific reader kind. Both releases use the same
four HTML captures and two verbatim JavaScript excerpts, but they select two
different projections. A single reader can authenticate the six pins, run a
declarative ordered list of bounded patterns, and select either `controls` or
`identifier_shapes`. The configuration varies only the projection, expected
source-to-row mapping, identity template, and claim mapping.

| Unit | Publisher inputs and registry module | Source row | Identity | What is compared |
| --- | --- | --- | --- | --- |
| `nrc-adams-native-controls-bounded-2026-08-03` | `nrc-adams-{faq,help-reference,landing-page,system-notices}-2026-08-03.html` plus `nrc-aps-{library-facet-labels,result-field-labels}-excerpt-2026-08-03.js`; `nrc_adams_codes` | result-field labels, library facets and docket-category links | publisher key | 19 control identities, publisher labels, source artifact per row, ordinal and exact control payload |
| `nrc-adams-identifier-shapes-2026-08-03` | `nrc-adams-{faq,help-reference,landing-page,system-notices}-2026-08-03.html` plus `nrc-aps-{library-facet-labels,result-field-labels}-excerpt-2026-08-03.js`; `nrc_adams_codes` | four prose-derived identifier shapes | publisher key | 4 shape identities, kinds, bases, regex patterns, explanations, samples and exact payload |

### Blocked raw-PDF sources: 4 units

These units have authenticated artifacts but no row input that the permitted
stock parsers can open. They are part of the eventual pattern-row family only
after checked extracts become construction inputs.

| Unit | Publisher input and registry module | Source row | Identity | What can be compared now |
| --- | --- | --- | --- | --- |
| `ferc-docket-prefixes` | `ferc-docket-prefix-june-2025.pdf`; `ferc_elibrary_codes` | 95 PDF table rows | source-local record | artifact pin only; no prefix row or label claim can be compared honestly |
| `ferc-document-class-types` | `ferc-class-types-january-2025.pdf`; `ferc_elibrary_codes` | 235 PDF table rows | source-local record | artifact pin only; no class/type row or label claim can be compared honestly |
| `unified-agenda-legal-authority-citation-types` | `risc-preamble-202210.pdf`; `unified_agenda_codes` | 3 PDF prose/table rows | source-local record | artifact pin only; no citation-type row or label claim can be compared honestly |
| `usgs-gnis-identifiers` | `gnis-file-format-2026-08-03.pdf`; `census_geo_codes` | 3 PDF identifier descriptions | source-local record | artifact pin only; no identifier row, label or definition can be compared honestly |

## Minimum reader set

| Reader kind | Units now / eventual | Required parameters | Existing reader generalized |
| --- | ---: | --- | --- |
| `pattern-row-v2` | 42 / 46 | input/region/row patterns, normalizers, row key, identity and locator templates, claim map, counts, explicit residue | `html-code-list-v1` prototype plus the current source-extract comparison |
| `xml-record-selector-v1` | 4 / 4 | namespaces, record and field XPaths, filters, captures/templates, identity, claim map, counts | XML label-tree reader |
| `json-record-selector-v2` | 1 / 1 | input role, JSON path, key and field map, identity, count and residue | API-capture JSON reader; removes its spec-name dispatch |
| `csv-record-selector-v2` | 3 / 3 | encoding/dialect, roles, headers, direct/distinct mode, keys, filter/sort, identity and claims | GCMD CSV reader |
| `ooxml-relational-v1` | 5 / 5 | workbook/sheet/header pins, cell types, projection, join/group/distinct plan, key/identity and claims | GCMD tabular view; adds stock ZIP/XML transport |
| `nrc-adams-multi-artifact-v1` | 2 / 2 | six input roles, ordered patterns, projection, row-source map, identity and claims | new; no existing reader has a six-input HTML/JavaScript semantic union |

The lower bound is six under the definition above. Pattern rows cannot safely
parse structured XML, JSON, CSV, or OOXML. Those four formats require their
stock parsers and have different failure rules. NRC cannot join six artifacts
with the single-input pattern-row algorithm without adding a general workflow
language to configuration. Conversely, the two NRC projections do not need
two readers, and the five OOXML units do not justify source-specific workbook
readers because relational selection covers every operation they use.

## Proving prototype: the FEC family

The original suggested target, `regulatory-native-*`, was invalid because all
14 units already had executable readers. FEC is the largest genuine uncovered
family that shares one publisher row model and identity policy, so it is the
best honest proof.

`HtmlCodeListSelector` declares the section pattern, row pattern, source
resource name/token, identifier kind and authority, observation namespace and
time, expected count, and use. `_read_html_code_list` applies that declaration
without importing `refspec.registry.fec_committee_codes` or dispatching on a
spec name. It requires exactly one selected section, an exact row count,
non-empty unique codes and labels, and reconstructs each source-local identity,
source path, identifier, label, notation, optional definition, source-record
digest and complete native payload.

The five entries vary only the input pin, the two patterns, the declared
resource/identifier names, observation namespace, time and expected count.
The implementation remains additive to the auditor and uses only standard
library byte decoding, regular expressions, HTML entity decoding, JSON,
hashing and UUID reconstruction.

One faithful full comparison passes every check in the fixture. One changed
Atlas label fails `label-fidelity`. Those two tests satisfy the requested
reader-kind proof; duplicating them for all five configurations would test data
entry repetition rather than reader behavior.

### Scoped results

I ran exactly one `--only` audit for each FEC member against the distribution
and source root named in the request. I did not run the unscoped audit or a
build. All five commands exited 1 with `differences-found`, which is the
expected audit result, and none reported a reader, pin, inventory, pack,
identity, count or native-payload error.

| Unit | Publisher records loaded | Exact comparisons that passed | Honest differences reported |
| --- | ---: | --- | --- |
| `fec-committee-designation` | 6 | 6 identities, labels, notations, locators, record/native digests and payloads | scoped distribution remains incomplete; 6 labels are below the 200-label floor; Atlas adds release metadata; surrounding HTML is explicitly unevaluated |
| `fec-committee-type` | 16 | 16 identities/labels/notations/payloads and 15 definitions | same systematic classes |
| `fec-filing-frequency` | 6 | 6 identities, labels, notations and payloads | same systematic classes |
| `fec-organization-type` | 6 | 6 identities, labels, notations and payloads | same systematic classes |
| `fec-party` | 95 | 95 identities/labels/notations/payloads and 7 definitions | same systematic classes |

The release-metadata differences are not new findings. The JSON campaign
already established that Atlas commonly adds `dcterms:issued` and, for these
source-local captures, `dcterms:identifier` that the publisher bytes do not
assert. Its LDA result also established the separate record-level versus
document-level digest class; a digest disagreement never substitutes for the
field-by-field payload comparison. See
`../codex-cov-json/REPORT.md`, especially its systematic findings section.
The bulk and baseline reports establish the same fail-closed interpretation of
`differences-found`; see `../codex-cov-bulk/REPORT.md` and
`../codex-fidelity-coverage/REPORT.md`.

Verification run after the prototype:

```text
uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q
238 passed in 3.87s

uv run --no-sync ruff check tools/verify_atlas_source_fidelity.py \
  tests/test_verify_atlas_source_fidelity.py
All checks passed!
```

The scoped receipts are `/tmp/codex-coverage-dry-fec-<unit>.json`. They are
scratch evidence, not repository deliverables.

## Blocked and genuinely bespoke units

The four raw-PDF units in the family map cannot be covered honestly from the
sealed inputs under the stated parser rule. Each needs a reviewed text or JSON
extract bound to the exact PDF digest.

Adding a PDF library to this auditor would violate the permitted stock-parser
boundary. Pin authentication alone compares no publisher rows. The correct
work is to add checked extracts as construction inputs and use
`pattern-row-v2`, while the receipt states that the extract is a frozen,
reviewed restatement rather than an independent PDF parse. This follows the
existing source-extract precedent.

The two NRC units are genuinely bespoke in code shape because six artifacts
contribute different semantic records. They share one bounded reader, not two.
Four configurations deserve bespoke review but not bespoke reader code:
`cbo-119th-congress-publications` normalizes publisher publication IDs;
`nppes-npi-provider-sample-2026-08-03` binds a 330-column header to sample
rows; `opm-ehri-data-standards-2026-08-04` joins three sheets; and the two
Treasury releases validate TAS rows and aggregate fund types. Their required
operations are explicit parameters of the XML, CSV, and OOXML kinds above.

## Remaining arithmetic

The design changes the work from “61 readers” to the following:

| Work item | Total design | Done here | Remaining |
| --- | ---: | ---: | ---: |
| Distinct reader kinds | 6 | 1 narrow proving implementation | 5 new kinds plus generalizing the proof to `pattern-row-v2` |
| Declarative construction-unit entries | 61 | 5 FEC entries | 56 entries |
| Entries usable from current sealed inputs | 57 | 5 | 52 |
| Checked extracts/construction-input additions | 4 | 0 | 4 |
| Genuinely source-specific reader kinds | 1 | 0 | 1 NRC reader serving 2 units |
| Reader-kind faithful/fault test pairs | 6 | 1 pair | 5 new pairs; revise the existing pair when generalized |
| Remaining scoped audit commands | 61 | 5 | 56 |

After the five FEC entries, the auditor declares 54 of 110 construction units
and 56 remain uncovered. Implementing the other five reader kinds and 52
currently usable entries reaches 106 of 110 without changing publisher input
evidence. The final four require checked extracts, then four more declarative
entries; they do not require a seventh reader kind.

This arithmetic is intentionally about reusable implementation work, not a
promise that every scoped receipt will be exact. Each future unit can still
report publisher/Atlas differences, source fields outside Atlas, sample-floor
failures, or the already documented release-metadata and digest classes. A unit
counts as covered only when the reader loads actual authenticated rows and the
receipt names what matched and what did not.

## Delivery and safety

The worktree contains two incremental commits:

- `5ec33d2c` — derive the authoritative tuple-expanded gap.
- `121be0ee` — add and test the declarative FEC reader family.

No file under `/Users/mikewolfd/Work/spicy-regs/RefSpec` was written. No full
audit or Atlas build ran. The inventory work read the small construction
summary and registry source; every proof audit was scoped to one FEC unit.

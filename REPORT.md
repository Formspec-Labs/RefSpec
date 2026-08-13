# SourceSpec fidelity coverage expansion

Date: 2026-08-13

## Result

This work raises declared construction-unit coverage from **24/110 to 27/110**.
The three new comparisons cover 42,651 of the 523,013 resource records that
were previously uncovered (8.15%). Eighty-three construction units remain
uncovered.

Declared coverage means that the auditor loaded authenticated publisher bytes,
loaded the matching Atlas pack, and ran an independent comparison. It does not
mean that the comparison passed. All three new comparisons honestly report
differences in the current distribution:

| SourceSpec | Records | Exact comparisons | Reported differences |
| --- | ---: | --- | --- |
| `mesh-descriptors-2026` | 31,110 | 31,110 identities; 134,904 labels; 65,360 notations | Atlas `sourceDigest` values do not equal the pinned XML digest; 81 authenticated XML path/attribute families are explicitly unevaluated |
| `federal-register-api-topics-2026-08-03` | 7,767 | 7,767 identities and preferred labels; 7,764 notations; 1,428 relations | Atlas `sourceDigest` values do not equal the independently reconstructed per-row JSON digests |
| `gcmd-science-keywords-24-4` | 3,774 | 3,774 identities, preferred labels, and notations | Atlas `sourceDigest` values do not equal the pinned CSV digest; three authenticated file-header metadata fields are not represented |

Neither scoped audit produced a source-load, pack-load, pin, configuration, or
graph-structure error. The receipt caps repeated failures at 100, so the report
describes repeated digest differences as systematic without inventing an exact
count beyond the stored evidence.

## Inventory method and source-kind totals

The baseline inventory comes from the receipt's `coverage.constructionUnits`
rows. Input formats and construction behavior come from
`atlas-construction-summary.json`, `src/refspec/atlas/v3_registry_codes.py`,
`v3_registry_documents.py`, `v3_registry_large.py`,
`v3_registry_nonemitters.py`, `v3_registry_vocabularies.py`,
`v3_registry_alignments.py`, and the source parsers they call under
`src/refspec/registry/`.

| Source family | Initial units | Initial records | After this work |
| --- | ---: | ---: | --- |
| Bulk vocabulary data (RDF, MARC, XML, managed vocabulary release) | 5 | 478,016 | 4 units / 446,906 records remain |
| JSON and API captures, including managed bundles | 19 | 9,203 | 18 units / 1,436 records remain |
| CSV and XLSX | 9 | 29,458 | 8 units / 25,684 records remain |
| PDF and checked extracts | 9 | 1,030 | unchanged |
| HTML, XML captures, Markdown, YAML, XSD, and JavaScript fixtures | 44 | 5,306 | unchanged |
| Native-control Parquet | 0 | 0 | No uncovered units; all 14 existing native-control comparisons were already declared |

The categories describe the source bytes that an independent reader must open,
not the Atlas output format.

## Payoff order

Effort is relative authoring cost for an independent reader, provenance inverse,
faithful test pair, fault injection, and real scoped verification. Small means
less than one engineer-day, medium means roughly one to two days, and large
means three or more days.

| Rank | Unit | Records | Source shape | Effort | Decision |
| ---: | --- | ---: | --- | --- | --- |
| 1 | `fast-topical-current` | 441,127 | N-Triples base plus four MARC change files | Large | Highest record payoff, but not a safe base-RDF declaration: fidelity requires an independent MARC delta reader and reconciliation rules |
| 2 | `mesh-descriptors-2026` | 31,110 | XML vocabulary | Small | Added and verified |
| 3 | `opm-ehri-data-standards-2026-08-04` | 17,263 | XLSX | Medium | Next large tabular win; needs a narrow OOXML sheet reader |
| 4 | `federal-register-api-topics-2026-08-03` | 7,767 | JSON API capture | Small | Added and verified |
| 5 | `icpsr-subject-thesaurus` | 3,810 | Managed vocabulary release | Large | Construction pins the managed-release manifest, not every publisher artifact needed for a direct comparison |
| 6 | `gcmd-science-keywords-24-4` | 3,774 | CSV | Small | Added and verified |
| 7 | `treasury-fast-book-accounts-parts-ii-iii-2026-07` | 3,581 | XLSX | Medium | Reuses the future OOXML reader and also unlocks the 11-record fund-type unit |
| 8 | `courtlistener-jurisdictions-2026-08-03` | 3,359 | HTML capture | Medium | Large HTML win, but its page structure needs a source-specific parser |
| 9 | `psc-april-2025` | 2,344 | XLSX | Medium | Reuses OOXML transport handling; workbook layout remains source-specific |
| 10 | `naics-2022` | 2,125 | XLSX | Medium | Reuses OOXML transport handling; code hierarchy and row identity need exact tests |
| 11 | `lcsh-eurovoc-alignment-endpoints-2026-08-06` | 1,966 | RDF plus compressed JSON-LD | Medium/large | Two-source endpoint selection requires a bounded JSON-LD reader as well as the existing RDF reader |
| 12 | `cbo-119th-congress-publications` | 1,058 | XML capture | Medium | Stock XML is available, but the publication-identifier normalization needs an independent inverse |

## Complete baseline inventory

This table lists all 86 units that were uncovered in the baseline receipt,
sorted by represented record count. “Added; verified differences” is declared
coverage, not an exact fidelity verdict.

| Unit | Source kind | Records | SourceSpec status |
| --- | --- | ---: | --- |
| `fast-topical-current` | Bulk RDF + MARC | 441,127 | Uncovered |
| `mesh-descriptors-2026` | XML vocabulary | 31,110 | Added; verified differences |
| `opm-ehri-data-standards-2026-08-04` | XLSX | 17,263 | Uncovered |
| `federal-register-api-topics-2026-08-03` | JSON API capture | 7,767 | Added; verified differences |
| `icpsr-subject-thesaurus` | Managed vocabulary release | 3,810 | Uncovered |
| `gcmd-science-keywords-24-4` | CSV | 3,774 | Added; verified differences |
| `treasury-fast-book-accounts-parts-ii-iii-2026-07` | XLSX | 3,581 | Uncovered |
| `courtlistener-jurisdictions-2026-08-03` | HTML capture | 3,359 | Uncovered |
| `psc-april-2025` | XLSX | 2,344 | Uncovered |
| `naics-2022` | XLSX | 2,125 | Uncovered |
| `lcsh-eurovoc-alignment-endpoints-2026-08-06` | RDF + JSON-LD | 1,966 | Uncovered |
| `cbo-119th-congress-publications` | XML capture | 1,058 | Uncovered |
| `crs-legislative-subjects` | JSON managed bundle | 565 | Uncovered |
| `crs-legislative-entities` | JSON managed bundle | 478 | Uncovered |
| `gsdm-online-data-dictionary-2026-08-03` | PDF + JSON extract | 457 | Uncovered |
| `nppes-data-dissemination-layout-v2-2026-08-03` | CSV | 330 | Uncovered |
| `ferc-document-class-types` | PDF | 235 | Uncovered |
| `fac-api-field-dictionary-2026-08-03` | HTML capture | 163 | Uncovered |
| `omb-a11-functional-classification` | PDF + checked extract | 98 | Uncovered |
| `fec-party` | HTML capture | 95 | Uncovered |
| `ferc-docket-prefixes` | PDF | 95 | Uncovered |
| `uscourts-nature-of-suit` | PDF + checked extract | 93 | Uncovered |
| `billstatus-summary-version-codes` | Markdown table | 88 | Uncovered |
| `lda-general-issue-codes` | JSON API capture | 79 | Uncovered |
| `sam-assistance-eligible-beneficiary-types` | HTML capture | 73 | Uncovered |
| `ecfr-cfr-titles` | JSON API capture | 50 | Uncovered |
| `lda-filing-types` | JSON API capture | 50 | Uncovered |
| `sam-assistance-eligible-applicant-types` | HTML capture | 44 | Uncovered |
| `govinfo-collections` | JSON API capture | 42 | Uncovered |
| `gsdm-reviewed-domain-values-2026-08-03` | JSON API capture | 40 | Uncovered |
| `omb-a11-object-classification` | PDF + checked extract | 38 | Uncovered |
| `billstatus-action-codes` | Markdown table | 36 | Uncovered |
| `unified-agenda-timetable-action` | XSD schema | 34 | Uncovered |
| `census-function-items` | HTML capture | 33 | Uncovered |
| `usaspending-award-types` | JSON API capture | 33 | Uncovered |
| `crs-policy-areas` | JSON managed bundle | 32 | Uncovered |
| `opm-plum-position-status-codes-2026-08-04` | CSV | 27 | Uncovered |
| `grants-gov-funding-categories` | HTML capture | 26 | Uncovered |
| `pra-icr-controls` | HTML capture | 21 | Uncovered |
| `federal-hierarchy-orgs-bounded-2026-08-03` | JSON API capture | 20 | Uncovered |
| `oira-review-controls` | HTML capture set | 20 | Uncovered |
| `nrc-adams-native-controls-bounded-2026-08-03` | HTML + JavaScript capture | 19 | Uncovered |
| `sec-series-categories` | HTML capture | 19 | Uncovered |
| `sam-opportunities-set-aside-codes` | HTML capture | 18 | Uncovered |
| `grants-gov-eligibilities` | HTML capture | 17 | Uncovered |
| `nasa-technology-taxonomy-8817` | JSON API capture | 17 | Uncovered |
| `sam-assistance-assistance-types` | HTML capture | 17 | Uncovered |
| `census-data-flags` | HTML capture | 16 | Uncovered |
| `fec-committee-type` | HTML capture | 16 | Uncovered |
| `fcc-ecfs-proceedings` | JSON API capture | 15 | Uncovered |
| `census-tiger-geoid-structure` | HTML capture | 14 | Uncovered |
| `sam-opportunities-notice-types` | HTML capture | 11 | Uncovered |
| `treasury-fast-book-fund-types-parts-ii-iii-2026-07` | XLSX | 11 | Uncovered |
| `oversight-report-types` | HTML capture | 10 | Uncovered |
| `billstatus-bill-types` | Markdown table | 8 | Uncovered |
| `omb-a11-apportionment-categories` | PDF + checked extract | 8 | Uncovered |
| `census-acs-geography-identifiers` | HTML capture | 7 | Uncovered |
| `nasbo-program-areas` | HTML capture | 7 | Uncovered |
| `scotus-opinion-types` | HTML capture | 7 | Uncovered |
| `fcc-ecfs-filing-types` | JSON API capture | 6 | Uncovered |
| `fec-committee-designation` | HTML capture | 6 | Uncovered |
| `fec-filing-frequency` | HTML capture | 6 | Uncovered |
| `fec-organization-type` | HTML capture | 6 | Uncovered |
| `ferc-sectors` | HTML capture | 6 | Uncovered |
| `gao-cra-database-facets-2026-08-04` | HTML capture | 6 | Uncovered |
| `unified-agenda-priority-category` | XSD schema | 6 | Uncovered |
| `unified-agenda-rule-stage` | XSD schema | 6 | Uncovered |
| `fcc-ecfs-bureaus` | JSON API capture | 5 | Uncovered |
| `regulations-gov-document-type` | YAML schema | 5 | Uncovered |
| `sam-opportunities-opportunity-statuses` | HTML capture | 5 | Uncovered |
| `ferc-security-levels` | HTML capture | 4 | Uncovered |
| `nrc-adams-identifier-shapes-2026-08-03` | HTML + JavaScript capture | 4 | Uncovered |
| `epa-enterprise-vocabulary-label-tree-2026-08-03` | XML vocabulary | 3 | Uncovered |
| `nppes-npi-provider-sample-2026-08-03` | CSV | 3 | Uncovered |
| `regulations-gov-submitter-type` | YAML schema | 3 | Uncovered |
| `unified-agenda-legal-authority-citation-types` | PDF | 3 | Uncovered |
| `usgs-gnis-identifiers` | PDF | 3 | Uncovered |
| `ferc-accession-number-formats` | HTML capture | 2 | Uncovered |
| `regulations-gov-docket-type` | YAML schema | 2 | Uncovered |
| `epa-comptox-substance-bounded-2026-08-03` | HTML capture | 1 | Uncovered |
| `fcc-ecfs-access-statuses` | JSON API capture | 1 | Uncovered |
| `gao-report-gao-26-108505` | HTML capture | 1 | Uncovered |
| `gao-topics-observed-on-gao-26-108505` | HTML capture | 1 | Uncovered |
| `govinfo-cfr-package-bounded-2026-08-03` | JSON + XML capture | 1 | Uncovered |
| `sam-cage-bounded-public-facility-2026-08-03` | JSON API capture | 1 | Uncovered |
| `sam-uei-bounded-public-entity-2026-08-03` | JSON API capture | 1 | Uncovered |

## Implementation

The auditor now dispatches publisher readers by `SourceSpec.reader` while
retaining `rdf` as the default. The added readers use only Python standard
library parsers and do not import RefSpec registry or transformation code:

- `mesh-descriptor-xml-2026-v1` streams `desc2026.xml` with
  `xml.etree.ElementTree`, reconstructing MeSH IRIs, heading and entry-term
  labels, tree-number notations, descriptor class, locators, and source fields.
- `federal-register-topics-json-v1` uses `json`, rejects duplicate fields and
  shape drift, independently derives source-local UUIDv7 identities and row
  digests, and reconstructs `see`/`see_also` relations.
- `gcmd-science-keywords-csv-v1` uses `csv`, validates the version, revision,
  columns, UUIDs, row hierarchy shape, and independently derives source-scoped
  identities and locators.

`SourceSpec.identity_policy` makes the existing identifier check distinguish
publisher IRIs from reviewed source-local and source-scoped identities. The
receipt records both the publisher reader and identity policy.

Tests add one faithful pair and one rewritten-label fault for every new reader
kind. The faithful fixtures state expected identities, locators, digests, and
native fields directly; they do not call the registry adapters under audit.

## Verification

Focused and full tests:

```text
uv run --no-sync pytest -q tests/test_verify_atlas_source_fidelity.py \
  -k 'mesh_xml_reader or federal_register_json_reader or gcmd_csv_reader'
6 passed, 207 deselected

uv run --no-sync pytest -q tests/test_verify_atlas_source_fidelity.py
213 passed

ruff check tools/verify_atlas_source_fidelity.py \
  tests/test_verify_atlas_source_fidelity.py
All checks passed!
```

Real scoped audits used the requested distribution and source root:

```text
uv run --no-sync python tools/verify_atlas_source_fidelity.py \
  --distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12c \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --only mesh-descriptors-2026 \
  --output /tmp/codex-fidelity-mesh-rss.json

uv run --no-sync python tools/verify_atlas_source_fidelity.py \
  --distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12c \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --only federal-register-api-topics-2026-08-03 \
  --only gcmd-science-keywords-24-4 \
  --output /tmp/codex-fidelity-json-csv-rss.json
```

Both commands exit 1 because the auditor found the fidelity differences listed
above and the intentionally scoped run still reports undeclared construction
units. Measured peak resident memory was 1.48 GiB for MeSH and 358 MiB for the
combined JSON/CSV batch, below the 6 GiB limit.

## Remaining work and estimated cost

The remaining campaign is not 83 equal declarations:

- FAST dominates the record payoff: 441,127 records, or 91.83% of all records
  still uncovered. Its four MARC change streams prevent an honest base-RDF-only
  comparison.
- Eight remaining tabular units need independent CSV or OOXML readers. A small
  stock OOXML transport reader can be shared, but sheet selection and row
  meaning remain source-specific.
- Nine PDF units need a checked extract and a direct PDF-to-extract comparison.
  Several already include a repository text extract; the raw-PDF-only units do
  not.
- HTML, XML, Markdown, YAML, XSD, and JavaScript captures account for 44 units.
  Many share publisher files, but each distinct source shape needs a negative
  fixture.
- ICPSR and the three CRS units pin managed bundle manifests as construction
  inputs. Their publisher artifacts are not separate construction pins, so a
  direct source comparison requires either a bounded checked-extract design or
  an additive construction-summary change outside this auditor-only branch.

Estimated effort to reach 110/110 is **24–38 engineer-days**: 5–8 for the four
remaining bulk vocabulary units (including FAST), 3–5 for JSON/bundle captures,
3–5 for CSV/XLSX, 4–6 for PDFs and checked extracts, 7–11 for the remaining
HTML/schema/text families, and 2–3 for final integration and regression runs.
The estimate assumes the current pinned bytes remain available and excludes
publisher reacquisition or redesign of construction inputs.

## Delivery status

The code, tests, and this report are present only in the disposable worktree.
Git could not create the linked-worktree index lock:

```text
fatal: Unable to create '/Users/mikewolfd/Work/spicy-regs/.git/modules/RefSpec/worktrees/codex-fidelity-coverage/index.lock': Operation not permitted
```

The failure occurs before staging and is outside the writable worktree root, so
no incremental commits could be created in this environment. The untracked
`CODEX_LOG.txt` and `PROMPT.txt` files were not modified.

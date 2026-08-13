# Source-fidelity coverage design

Date: 2026-08-13

## Result so far

The current auditor covers 49 of the distribution's 110 construction units.
Sixty-one units remain. The 14 `regulatory-native-*` units are already covered;
they belong to the generated `NATIVE_CONTROL_SOURCES` tuple and therefore do
not appear as 14 literal `SourceSpec(...)` calls. They are not candidates for
the proving prototype in this worktree.

This is an inventory result, not a fidelity verdict. The family map, minimum
reader set, prototype results, and remaining-work arithmetic follow in later
sections.

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
and record counts. `tools/verify_atlas_source_fidelity.py:4881-4952` establishes
the tuple-expanded native-control declarations, and
`tools/verify_atlas_source_fidelity.py:7410-8843` establishes the complete
`SOURCES` registry.


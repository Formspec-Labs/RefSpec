<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/icpsr-provenance` at `1e7724c4`,
> file `REPORT.md`, committed 2026-08-13. Verbatim; nothing edited.

# ICPSR provenance walk

## Result

All 112 ICPSR provenance findings were auditor defects. None was an Atlas
producer defect, a legitimate exclusion, or unresolvable from the pinned bytes.
The old reader stopped at the 3,760-record managed intersection. It did not
reparse the authenticated public-index HTML or subject XML that define the
50-member union extension, so it asked the wrong provenance questions about
those records.

The corrected reader independently reconstructs the complete union with stock
parsers. Against the `2026-08-13d` distribution it now passes these checks:

- 3,832 RDF source records, including 22 transformed-relation records;
- 3,810 concept identities and source-record links;
- 3,810 labels and 730 scope notes; and
- 18,761 relations, with exact direction and no manufactured relation.

The scoped command still exits 1 for two reasons outside the 112 findings. It
reports the known Atlas-created `dcterms:issued` and `dcterms:identifier` source
release claims, and scoped distribution accounting reports four construction
units that have no declared reader. It does not report an ICPSR member,
provenance, identity, label, annotation, or relation difference.

## Reproduction

I used the requested and complete `2026-08-13d` distribution. No fallback was
needed.

```text
uv run --no-sync python tools/verify_atlas_source_fidelity.py \
  --distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13d/distribution \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --only icpsr-subject-thesaurus \
  --output /tmp/icpsr-13d-baseline.json
```

The baseline receipt reports 112 `rdf-provenance-fidelity` failures. The JSON
receipt intentionally stores only the first 100, so I retained and classified
all 112 lines from the command output. The arithmetic is exact:

| Baseline message class | Findings |
| --- | ---: |
| Union source record “is not a publisher concept” | 50 |
| Union source record has zero direct publisher digest candidates | 50 |
| Source locator differs | 5 |
| Unevaluated native-payload field summary | 7 |
| **Total** | **112** |

## Classification of all 112 findings

| Root cause | Finding count | Affected records | Classification | Resolution |
| --- | ---: | ---: | --- | --- |
| Reader omitted the authenticated union extension | 100 | 50 | Auditor defect | Reparse the raw index and XML; reconstruct all 50 concepts, labels, payloads, and direct canonical payload digests. The 100 findings split into 50 false “not a publisher concept” findings and 50 false zero-digest findings. Within each set, 45 records are index-only and 5 are XML-only. |
| Reader used the resource IRI as the default locator | 5 | 5 | Auditor defect | Derive the five XML locators from the pinned subject-XML digest and `TNR` record number. Atlas had the right locators. |
| Provenance policy assumed one native-payload shape | 7 | 50 | Auditor defect | Declare and compare the union of fields, but require only the exact independently reconstructed fields for each record shape. Six findings cover the five XML-only records: `identitySeed`, `mintingPolicy`, `mintingRule`, `recordedAt`, `sourceIdentity`, and `sourceLocalRecordNumber`. The seventh covers `sourcePath` on all 50 union-only records. |
| **Total** | **112** |  |  |  |

Category totals are therefore: Atlas-side defect **0**; auditor-side defect
**112**; declared legitimate scope **0**; genuinely unresolvable **0**. No
finding was suppressed or converted to a waiver.

## What the 50 union concepts are

“Union” means a lossless union of two authenticated publisher serializations,
not 50 concepts invented by Atlas:

```text
3,760 labels present in both the public index and subject XML
   45 labels present only in the public index capture
    5 labels present only in the subject XML capture
-----
3,810 Atlas members
```

The outer managed manifest is pinned as
`sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a`.
It authenticates the index manifest, every captured HTML page, `robots.txt`,
the managed concept and indexed-expression artifacts, the coverage report, and
the subject XML. The two principal source digests are:

- index manifest:
  `sha256:67b90a239de8ba7cb70a4e9d81c5c7bf30198800cf1aa0ecdc96246b30f94fea`;
- subject XML:
  `sha256:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff`.

The corrected reader does not trust the managed gap lists as semantic proof. It
authenticates every nested artifact, reparses all 27 HTML pages with
`html.parser.HTMLParser`, reparses XML with
`xml.etree.ElementTree`, reconstructs the managed intersection and indexed
expressions, and then checks the coverage report against that independent
reconstruction. It imports no production extraction, transformation, and load
(ETL) code.

### Traceability verdict

Every union concept is traceable.

- Each of the 45 index-only members keeps the publisher term IRI. Its source
  record carries the exact parsed index term, page-level identifier evidence,
  authenticated index-manifest digest, and index-page/term path. Its locator is
  the publisher term IRI.
- Each of the 5 XML-only members has no publisher IRI in the pinned XML. Its
  source record carries the exact XML term, XML digest, `TNR`, source path,
  identity seed, recorded time, minting rule, and deterministic source-scoped
  identity. Its locator addresses the exact XML digest and record.
- The five XML-only terms and their five publisher-authored reciprocal
  relations add the 10 relations beyond the managed intersection: four
  `narrower`/`broader` pairs and one `usedFor`/`use` pair.

After the fix, `concept-traceability`, `identifier-retention`,
`rdf-provenance-fidelity`, `label-fidelity`, `relation-fidelity`, and
`no-manufactured-relations` all pass over the complete union. A consumer can
therefore move from every Atlas member to one source record, from that record to
an exact source address and digest, and from the native payload to the pinned
HTML or XML bytes.

## The five locator differences

The pinned XML gives each of these records a label and `TNR`; it gives none a
publisher term IRI. Atlas correctly uses an evidence locator of the form
`urn:ref:icpsr:subject-xml:<XML-SHA-256>#record=<TNR>`. The old auditor wrongly
expected the newly minted concept IRI to double as the source address.

| XML `TNR` | Publisher XML says | Atlas concept | Atlas source locator | Call |
| ---: | --- | --- | --- | --- |
| 124 | `Alaskan Natives`; broader `ethnic groups` | `urn:ref:source-concept:v2:icpsr-subject-thesaurus:019fb3c1-0800-7748-8a84-7ed01f17b24a` | `urn:ref:icpsr:subject-xml:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff#record=124` | Atlas right; auditor wrong |
| 2426 | `Obama Administration (2009-  )`; broader `presidential administrations` | `urn:ref:source-concept:v2:icpsr-subject-thesaurus:019fb3c1-0800-763c-935f-8406668d3f8e` | `urn:ref:icpsr:subject-xml:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff#record=2426` | Atlas right; auditor wrong |
| 3050 | `runaway slaves`; broader `slavery` | `urn:ref:source-concept:v2:icpsr-subject-thesaurus:019fb3c1-0800-77b4-acac-81bee4c29aa3` | `urn:ref:icpsr:subject-xml:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff#record=3050` | Atlas right; auditor wrong |
| 3279 | `special  elections`; broader `elections` | `urn:ref:source-concept:v2:icpsr-subject-thesaurus:019fb3c1-0800-7f2a-a8d1-f6b415b16cb7` | `urn:ref:icpsr:subject-xml:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff#record=3279` | Atlas right; auditor wrong |
| 3525 | `treatment outcomes`; `USE` `treatment outcome` | `urn:ref:source-concept:v2:icpsr-subject-thesaurus:019fb3c1-0800-7fcc-bf10-2c770ad9bb87` | `urn:ref:icpsr:subject-xml:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff#record=3525` | Atlas right; auditor wrong |

The doubled spaces in the two XML labels are source data. The public index has
single-space labels for two distinct publisher-IRI members. The union correctly
retains both forms and both identities.

## Auditor fixes

Commit `79e2884a` makes the following additive changes:

1. It authenticates and reparses the complete ICPSR artifact set with stock
   parsers, including raw HTML, XML, indexed expressions, coverage, page pins,
   the index capture seal, and the outer managed-release seal.
2. It reconstructs all three member classes and all raw XML relations. The old
   3,760-record managed comparison remains an exact oracle inside the reader;
   the union adds evidence without weakening that comparison.
3. It verifies each record's exact conditional native-payload shape. A generic
   provenance correction stops requiring fields that the independent reader
   proves belong only to a different record shape.
4. It declares `publisher-iri-or-source-local-record` for ICPSR and checks the
   declaration fail-closed. `publisherIdentifierVerified` requires a publisher
   IRI; `publisherIdentifierAbsent` requires a v2 source-scoped IRI. Missing or
   unknown identity status fails.
5. It preserves the previously landed transformed-relation rule: a
   source-shaped `publisherRelation` is accepted only when its canonical digest
   matches `publisherRelationDigest` and the payload declares the editorial
   transformation. The prior report records that rule and its negative fixture
   at `/Users/mikewolfd/Work/spicy-regs/RefSpec/.claude/worktrees/codex-cov-bulk/REPORT.md:35-39`.

The test file now has 255 tests, up from 249. New synthetic cases prove the
complete three-member-class union and reject an artifact-pin fault, repinned but
inconsistent raw HTML, repinned but inconsistent XML, changed indexed-expression
evidence, changed coverage, and a mixed-identity declaration with no source
identity status.

## Producer verdict and ownership

No ICPSR producer defect is justified by the pinned evidence, so I made and
specified no producer patch. `tools/generate_atlas_v3_full.py::_load_icpsr`
produces exactly the independently reconstructed 3,810 members and 18,761
relations. Its declared registry owner is
`refspec.registry.managed_releases.icpsr_managed_release`, implemented in
`src/refspec/registry/managed_releases/icpsr_managed_release.py`; raw ICPSR
capture and parsing live in `src/refspec/registry/icpsr_subject.py`. Those are
the modules to change if a future pinned capture disproves the union. The 13d
bytes do not.

## Legitimate scope outside the 112

The scoped run still reports one `dcterms:issued` and one
`dcterms:identifier` on the constructed source-release node. These are the
already-characterized campaign-wide class: Atlas adds release metadata that the
publishers do not assert. The campaign record describes that finding direction
at `plans/validation-cost-reset-plan.md:1033-1040`; the JSON-reader report gives
the per-source interpretation at
`/Users/mikewolfd/Work/spicy-regs/RefSpec/.claude/worktrees/codex-cov-json/REPORT.md:65-65`.
I did not reclassify or rederive that systematic finding here.

The exact follow-up declaration should mirror `DeclaredClaimExclusion`, but on
the Atlas side:

- select only the evaluated pack's one `atlas:SourceRelease` subject;
- select only `dcterms:issued` and `dcterms:identifier`;
- require exactly one claim for each predicate;
- require the identifier literal, including datatype, to equal the selected
  source-release IRI;
- require the issued literal, including datatype, to equal the declaration's
  pinned `YYYY-MM-DD` value;
- prove that the publisher comparison adopted no claim on that constructed
  release subject;
- publish exact per-source and per-predicate counts in the receipt; and
- fail on subject, value, datatype, predicate, multiplicity, overlap, or count
  drift.

For this snapshot the selected subject is
`urn:ref:icpsr:source-release:union:d315247f99134ec3acc0eac76610d2efa59df5383c623aad8f66ed683ce9f13a`,
the issued value is `2026-07-30` as `xsd:date`, and the identifier is the subject
IRI as `xsd:string`. A bare predicate allowlist would not meet this requirement.

The Lobbying Disclosure Act (LDA) record-level versus document-level digest
class is unrelated to ICPSR and remains exactly as previously characterized;
see
`/Users/mikewolfd/Work/spicy-regs/RefSpec/.claude/worktrees/codex-cov-json/REPORT.md:63-63`.

## What remains unresolvable

Nothing in the 112 findings remains unresolvable from the pinned bytes. The
audit proves the contents of the pinned 2026-07-30 capture; it does not claim
that the current live ICPSR site still matches that capture. The two constructed
release claims need the checked scope declaration above, not an ICPSR producer
change.

The four uncovered-unit messages in this scoped run are
`ferc-docket-prefixes`, `ferc-document-class-types`,
`unified-agenda-legal-authority-citation-types`, and
`usgs-gnis-identifiers`. They are distribution-level campaign bookkeeping, not
ICPSR findings.

## Verification

Only scoped runs were used. No full build or unscoped audit was run.

```text
ruff check tools/verify_atlas_source_fidelity.py tests/test_verify_atlas_source_fidelity.py
# All checks passed

pytest -q tests/test_verify_atlas_source_fidelity.py
# 255 passed in 6.31s

verify_atlas_source_fidelity.py ... --only icpsr-subject-thesaurus ...
# rdf-provenance-fidelity: PASS, 3,832 records
# concept-traceability: PASS, 3,810 concepts
# identifier-retention: PASS, 3,810 identities
# relation-fidelity: PASS, 18,761 relations
# peak RSS: 554,254,336 bytes (about 529 MiB)
```

## Appendix: all 45 public-index-only members

Each IRI is
`https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001/terms/<code>`.

| Code | Label | Code | Label | Code | Label |
| ---: | --- | ---: | --- | ---: | --- |
| 24162 | Alaska Natives | 31726 | Bluesky | 31721 | Facebook |
| 31722 | Instagram | 26451 | Obama Administration (2009- ) | 31724 | Reddit |
| 31725 | X (Social networking service) | 31723 | YouTube | 32341 | academic publishing |
| 34823 | child care provider | 34821 | child care providers | 34824 | childcare provider |
| 34822 | childcare providers | 31940 | community-based research | 32224 | crosswalks (metadata) |
| 32141 | diversity in the workplace | 32421 | enslaved persons | 31583 | firearm education |
| 31580 | firearm locks | 31582 | firearm safety | 31581 | firearm storage |
| 31920 | health literacy | 31460 | inequity | 32020 | inflammation |
| 32345 | journals (scholarly) | 32140 | mentoring | 32223 | metadata crosswalks |
| 32243 | mindfulness | 32321 | nervous system diseases | 32242 | opioids |
| 32221 | palliative care | 31941 | patient outcome assessment | 31943 | patient reported outcome measures |
| 31942 | patient-centered outcomes research | 32342 | publishing (academic) | 34761 | qualitative research |
| 31900 | race identity | 31901 | racial identity | 31800 | reproductive health |
| 32344 | scholarly journals | 32040 | self care (health) | 27293 | special elections |
| 32222 | stroke | 32202 | vaping | 32142 | workforce diversity |

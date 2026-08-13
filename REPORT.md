# Bulk vocabulary source-fidelity coverage report

## Result

This batch adds independent source-fidelity comparisons for all four bulk
vocabulary construction units. Together they cover 446,906 Atlas records. All
four readers loaded authenticated publisher bytes and Atlas packs successfully.
Each comparison found either exact agreement or specific, reproducible
differences; none failed because of a reader, pin, pack, or configuration error.

Against the shared campaign baseline of 27 covered construction units, merging
this batch raises coverage to 31 of 110 units and leaves 79 uncovered. This
isolated branch contains 28 declared construction-unit keys because it does not
contain the sibling branch's three adapters. A scoped `--only` receipt reports
one evaluated unit by design and must not be read as the global campaign count.

| Construction unit | Publisher source and stock reader | Records | Spec status | Exact comparison | Differences found |
| --- | --- | ---: | --- | --- | --- |
| `epa-enterprise-vocabulary-label-tree-2026-08-03` | XML label tree; `epa-enterprise-vocabulary-xml-v1` | 3 | Differences found | 3 identities, 3 preferred labels, 1 scope note, 1 broader relation, and 3 source-record provenance links | The exact three-label comparison is below the auditor's 200-label safety floor. Atlas also adds an issued date and identifier to the source-release node. |
| `fast-topical-current` | Zipped N-Triples base plus four MARC change files; `fast-topical-ntriples-marc-v1` | 441,127 | Differences found | 441,127 identities, 709,779 labels, 882,254 notations, 189,660 relations, and 441,127 source-record provenance links | 51 authenticated source field families are not represented: 12 base-RDF predicate families and 39 MARC tag families. Atlas also adds an issued date and identifier to the source-release node. |
| `icpsr-subject-thesaurus` | Managed-release JSON and its authenticated concept artifact; `icpsr-managed-release-json-v1` | 3,810 | Differences found | The 3,760 managed concepts agree on 3,760 labels, 730 scope notes, 18,751 relations, and exact member IRI metadata | Atlas adds 50 union concepts, 50 labels, and 10 relations beyond the managed concept artifact. Provenance reports 112 findings, including union-only targets without direct digest candidates and 5 locator differences. Four source-coverage categories remain explicit: 45 index-only members, 5 XML-only members, 5 unresolved relations, and transitively authenticated raw artifacts not reparsed by this reader. Atlas also adds two source-release claims. |
| `lcsh-eurovoc-alignment-endpoints-2026-08-06` | EuroVoc alignment RDF/XML plus the selected records from the compressed LCSH MADS JSON-LD release; `lcsh-alignment-endpoint-jsonld-v1` | 1,966 | Differences found | 1,966 identities, 7,522 labels, 1,960 notations, 933 relations, and 1,966 source-record provenance links | 23 authenticated MADS/JSON-LD field families are not represented, including administrative metadata, classification, collection membership, non-English variants, and unselected graph-node claims. Atlas also adds an issued date and identifier to the source-release node. |

## Comparison boundaries

The readers use stock XML, JSON, RDFLib, and pymarc parsing. They do not import
the registry extract-transform-load code that built the distribution. Every
input is pinned by SHA-256 digest and byte length and is reconciled to the
construction summary before semantic checks run.

No unit was judged impossible. Each unit has pinned publisher bytes and asserts
identities or values that the Atlas represents. Claims that the Atlas does not
represent remain findings in the receipt instead of becoming exclusions.

The ICPSR reader accepts the source-shaped `publisherRelation` only when its
canonical JSON digest matches `publisherRelationDigest` and the payload declares
the editorial transformation. A faithful fixture passes and a changed digest
fails. This preserves evidence for the transformed relation without pretending
the publisher directly asserted the normalized RDF triple.

## Memory bound

The first complete FAST scoped run peaked at 11.803 GiB. The final verifier
peaked at 7.879 GiB and completed in 218.066 seconds, below the requested 8 GiB
ceiling. It retains exact semantic indexes and native-payload digests while
avoiding duplicate high-cardinality claim, type, payload, and mutable-to-frozen
indexes.

The final receipts for EPA, FAST, ICPSR, and LCSH are byte-for-byte equivalent
to the pre-optimization receipts after removing only the verifier-version field.
The memory work therefore changed no finding, count, or source status.

## Verification

Each new spec was run separately with this shape; no unscoped audit was run:

```text
uv run --no-sync python tools/verify_atlas_source_fidelity.py \
  --distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13 \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --only <spec-name> --output <scratch-receipt>.json
```

All four scoped commands returned exit code 1 because an honest difference and
the remaining uncovered units make the audit fail closed. In every receipt,
`publisherLoaded` and `atlasLoaded` are true; `load-errors`, input-pin checks,
and graph-structure checks pass.

The code gates pass:

```text
make lint
# All checks passed

uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q
# 217 passed in 3.59s
```

There is one faithful-pair and one fault-injection test for every new reader
kind. The compact native-payload index also has a faithful digest case and an
unexpected-field/digest fault case.

## Commits

- `bca4b29d` — add the four SourceSpecs, readers, and reader-kind tests.
- `e8019a1c` — validate source-shaped transformed ICPSR relation evidence.
- `72253c10` — keep the full FAST comparison below the 8 GiB memory ceiling.

These commits are local to `research/coverage-bulk`; nothing was pushed or
published.

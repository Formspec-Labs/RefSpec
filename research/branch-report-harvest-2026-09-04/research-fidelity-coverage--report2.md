<!-- markdownlint-disable MD013 -->

> Harvested 2026-09-04 from branch `research/fidelity-coverage` at `b8bc4bec`,
> file `REPORT2.md`, committed 2026-08-13. Verbatim; nothing edited.

# Fidelity coverage integration

Date: 2026-08-13

## Result

Commit `f1b90b18` integrates the three missing SourceSpecs on the live primary
tip, `b2b36bee`. The integrated auditor remains
`atlas-source-fidelity/13`, and all three comparisons load and run against the
2026-08-13 artifact of record:

- `mesh-descriptors-2026`
- `federal-register-api-topics-2026-08-03`
- `gcmd-science-keywords-24-4`

The campaign subtotal moves from **28 to 31**. That subtotal excludes the 18
JSON/API-capture comparisons already landed in `fa7839f4`. The complete
runtime `SOURCES` tuple moves from **46 to 49**. The integrated real-data
receipts therefore account for 49 declared comparisons, 61 uncovered
construction units, and 110 construction units in all.

Each scoped audit reports one covered unit and 48 scoped-out declared units.
The `--only` selector causes that scoped count; `1 + 48 + 61 = 110` proves the
full 49-comparison registry without running the unscoped audit.

## Integration resolution

The merge conflicted only in `tools/verify_atlas_source_fidelity.py` and
`tests/test_verify_atlas_source_fidelity.py`. I used main's files as the
starting point, then adapted the three readers and their six tests.

Main's bounded-memory machinery wins:

- `_StockSourceRecord` and `_stock_source_view` now form a thin adapter to
  main's `_StockVocabularyRecord` and `_stock_vocabulary_view`.
- The three readers set `retain_claim_sets=False` and
  `retain_predicate_counts=False`; they do not restore duplicate label,
  notation, or predicate-count indexes.
- They set `compact_resource_digests=True`, which stores one digest string per
  resource instead of one `frozenset` per resource.
- The MeSH reader streams `DescriptorRecord` elements and clears each XML
  element after use.

One part of these exact comparisons cannot use main's compact native-payload
mode. That mode proves a payload by requiring `atlas:sourceDigest` to equal the
canonical native-payload digest. These readers use different digest meanings:
MeSH and GCMD retain the pinned file digest, and Federal Register retains an
independently reconstructed source-row digest. Treating any of those values as
the native-payload digest would create false failures. Dropping the expected
payload values would stop checking fields that the old comparison checked.

The integrated readers therefore retain only their per-resource expected
native-payload values. They use main's compact machinery for the other shared
indexes. This preserves the comparison instead of weakening it. The measured
peak remains 1.061 GiB, below both the old MeSH result of 1.48 GiB and the 6 GiB
limit.

Main's new source-release metadata check also exposes two differences per
source that the original version did not report: Atlas adds one date claim and
one identity claim that the publisher bytes do not state. The integration
keeps those findings.

## Structural verification

I parsed the old branch, current primary tip, and integrated files with
`ast`. For both the auditor and its test file, the check compared module-level
assigned names, every function name, every class name, and every annotated
field name. Both histories are subsets of the integrated result:

```text
tools/verify_atlas_source_fidelity.py
  integrated: module_names=152 functions=219 classes=30 annotated_fields=260
  old-branch subset: missing_module_names=0 missing_functions=0 missing_classes=0 missing_annotated_fields=0
  current-primary subset: missing_module_names=0 missing_functions=0 missing_classes=0 missing_annotated_fields=0
tests/test_verify_atlas_source_fidelity.py
  integrated: module_names=18 functions=258 classes=3 annotated_fields=0
  old-branch subset: missing_module_names=0 missing_functions=0 missing_classes=0 missing_annotated_fields=0
  current-primary subset: missing_module_names=0 missing_functions=0 missing_classes=0 missing_annotated_fields=0
STRUCTURAL SUBSET CHECK: PASS
```

This check includes the MeSH module-level regex, the two shared dataclass field
sets, and the reader/test functions that a conflict-marker-only review could
miss.

## Test verification

```text
make lint
All checks passed!

uv run --no-sync pytest tests/test_verify_atlas_source_fidelity.py -q
236 passed in 3.42s

uv run --no-sync pytest -q tests/test_verify_atlas_source_fidelity.py \
  -k 'mesh_xml_reader or federal_register_json_reader or gcmd_csv_reader'
6 passed, 230 deselected in 0.44s
```

The sandbox could not read the default uv cache and has no network access. I
ran the commands offline with `UV_NO_SYNC=1`, a `/tmp` uv cache, and the
already-provisioned primary-worktree virtual environment. These settings did
not change the commands' lint or test scope.

## Scoped real-data receipts

All runs used this read-only distribution and source root:

```text
--distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13
--source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources
```

| SourceSpec | Independently matched claims | Reported differences | Peak RSS |
| --- | --- | --- | ---: |
| `mesh-descriptors-2026` | 31,110 identities; 134,904 labels; 65,360 notations | 31,110 source-digest differences; 2 Atlas-only release claims; 81 authenticated XML path or attribute families remain unrepresented | 1.061 GiB |
| `federal-register-api-topics-2026-08-03` | 7,767 identities and labels; 7,764 notations; 1,428 relations | 7,767 source-digest differences; 2 Atlas-only release claims; no residual publisher claims | 0.220 GiB |
| `gcmd-science-keywords-24-4` | 3,774 identities, labels, and notations | 3,774 source-digest differences; 2 Atlas-only release claims; 3 authenticated CSV metadata fields remain unrepresented | 0.144 GiB |

Every receipt reports:

- `load-errors`: passed with zero failures;
- `publisher-input-pins`: passed, `1/1` construction input matched;
- `graph-structure`: passed for the one selected pack;
- `concept-traceability`, `identifier-retention`, label fidelity, notation
  fidelity, and count reconciliation: passed; and
- selected comparison status: `differences-found`.

Each command exits 1 because the selected comparison reports the differences
above and 61 construction units remain uncovered. The receipts record the
complete failure counts even when they store only the first 100 repeated digest
messages.

Receipt paths:

```text
/tmp/codex-fidelity-mesh-2026-08-13.json
/tmp/codex-fidelity-federal-register-2026-08-13.json
/tmp/codex-fidelity-gcmd-2026-08-13.json
```

No unscoped audit or full Atlas build ran. The artifact and source directories
remained read-only.

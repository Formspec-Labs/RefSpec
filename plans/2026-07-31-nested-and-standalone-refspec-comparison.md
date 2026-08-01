# Nested and Standalone RefSpec Comparison

**Date:** 31 July 2026  
**Nested baseline:** `8fdf2d2a12ae0105a515369bb7aa1f27f28b7d01`  
**Standalone baseline:** `210d671`  
**Decision status:** Accepted and implemented locally; unreleased

## Verdict

The nested implementation is the better engineering base. The standalone
implementation has the better current product boundary and the genuinely new
atlas design.

Do not keep the standalone branch as a parallel RefSpec. Port its atlas and
machine-first qualification into the older managed-release implementation,
while removing the older implementation's out-of-boundary responsibilities as
their consumers migrate.

## Side-by-side comparison

| Dimension | Nested RefSpec at `8fdf2d2` | Standalone RefSpec at `210d671` |
| --- | --- | --- |
| Product shape | A broad Regulatory Evidence Framework covering acquisition, processing, vocabulary management, evaluation, deployment, and publication. Its later vocabulary plan already separates RefSpec management from consumer lookup, creating internal scope tension. | A narrow vocabulary publisher: `VocabularyRelease`, source-term resolution, crosswalk validation, and static `VocabularyAtlasAsset`. Document processing, extrapolation, and search belong elsewhere. |
| Release shape | A rich multi-file bundle containing exact source bytes, a Rulespec graph, operational records, normalized rows, an expression corpus, coverage, a dependency manifest, and a validation receipt. | One canonical JSON `VocabularyRelease`, plus a separate two-graph N-Quads atlas and canonical manifest. |
| Real data | Nine packaged resources and 20,970 records or observations, including all 705 current Federal Register concepts, ELSST releases, and an ICPSR subset. | Five Federal Register concepts. The checked atlas contains no mappings; multi-release crosswalk behavior exists only in synthetic tests. |
| Crosswalk model | A source-specific, analysis-only 1995-to-2025 Federal Register crosswalk plus mappings embedded in managed Rulespec graphs. | General cross-vocabulary candidates with exact endpoints, model and prompt lineage, independent agent receipts, `searchOnly` qualification, and optional later feedback. |
| Validation | CUE-generated schemas and Python types, 98 embedded conformance assets, cross-record checks, Rulespec graph validation, deployment permissions, and rollback evidence. | Handwritten Python validation, copied Rulespec Core fixtures, deterministic asset checks, and focused adversarial tests. The release validator is Federal Register-specific while the atlas has a second, less complete generic validator. |
| Review model | Experiments may use automatically generated candidate eligibility, but promotion expects independent review and deployment authority. | Two independent LLM or agent validations can qualify `searchOnly`; human feedback is optional later input. This matches the current decision. |
| Consumer seam | SpicyRegs directly imports `ManagedReleaseView` and other RefSpec Python APIs. This is mature and working, but violates the file-only product seam. | SpicySearch validates the release file through its own adapter. At the baseline, atlas consumption was documented but not implemented. |
| Complexity | About 36,620 source lines across 43 modules, with substantial dependency and governance machinery. | About 5,108 source lines across 15 modules and one runtime dependency. It is easier to understand, but much less complete. |

## Important incompatibilities

The two release foundations cannot coexist safely.

1. **Different canonical JSON.** The nested binding forbids `null`,
   floating-point numbers, and unsafe integers. The standalone serializer
   permits finite floats and uses one for model temperature. Equivalent
   records can therefore produce different digests.
2. **Different meanings of a valid release.** The standalone public validator
   accepts only its five-concept fixture, while its atlas reader accepts
   synthetic releases lacking source pins, coverage, resolution records, and
   validation receipts.
3. **Incomplete crosswalk evidence closure.** The standalone bundle includes
   candidates and receipts but not the evidence, request, or response artifacts
   those records reference. It checks reference shape, not resolution against
   pinned content.
4. **Different existing consumers.** Eighteen SpicyRegs files import the older
   RefSpec package, while SpicySearch already parses the newer compact
   `VocabularyRelease` shape. This is a real migration problem, not an unused
   prototype.

## Baseline verification

- Standalone: 44 tests passed.
- Nested: 304 passed, 17 failed, 11 errored, and 10 skipped.
- The inspected nested failures are fail-closed Rulespec pin mismatches. The
  branch expects `2c66a85`, while Rulespec is at `320ed37`. The dependency
  must migrate to the new Core and Extrapolator split; changing the old pin
  without that migration would hide the incompatibility.

## What to keep

From the nested implementation:

- CUE and JSON Schema generation plus conformance fixtures;
- exact source capture and vocabulary-specific importers;
- complete Federal Register, ELSST, ICPSR, and other managed packages;
- coverage, reconciliation, expression-corpus, and immutable bundle
  machinery;
- `ManagedReleaseView` exact membership and mapping validation; and
- existing consumer and rollback tests.

From the standalone implementation:

- the narrow four-product ownership boundary;
- `VocabularyAtlasAsset` and deterministic two-graph N-Quads;
- external manifest, implementation, runtime, and output pins;
- machine-first `searchOnly` qualification;
- optional append-only human feedback;
- file-based consumer integration; and
- historical atlas research preservation.

## Reconciliation

1. Start from the nested 23-commit branch and preserve its existing dirty
   changes.
2. Make its generated schema and managed bundle the single release foundation.
3. Port the static-atlas behavior from standalone commit `abfa5b3`; do not port
   the duplicate release, canonicalization, receipt, or Federal Register
   fixture foundation from `6298262`.
4. Make the atlas consume verified managed-release distributions and close
   every evidence reference inside a pinned bundle.
5. Update RefSpec to depend only on the new Rulespec Core publication for new
   release work.
6. Remove human attestation as a prerequisite for `searchOnly`; retain it only
   for stronger later adoption.
7. Move document observations to SpicyRegs, extrapolation and accepted-output
   decisions to Rulespec Extrapolator, and ranking and query behavior to
   SpicySearch.
8. Replace direct cross-repository Python imports with product-local readers of
   the one published release format.

The decisive user-value test is one complete vocabulary release built once,
then independently consumed by SpicyRegs, Rulespec Extrapolator, and
SpicySearch without importing RefSpec source. Until that works, the split
remains unresolved.

**Verdict:** `RECONSIDER`. Reverse the standalone release foundation, retain
its atlas work, and reshape the mature nested implementation around the current
product boundary. Confidence: high.

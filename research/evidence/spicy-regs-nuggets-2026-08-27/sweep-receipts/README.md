# Twelve-agent archive-surface sweep

Date: 2026-08-27

This directory preserves the completed twelve-agent review of the SpicyRegs
archive surface. The review searched source, tests, documentation, ontology,
fixtures, workflows, and large-output descriptions for behavior or evidence
that the first nugget index had not captured.

The findings are dated analysis. They identify candidate preservation and
adoption work; they do not change product ownership, accept a design, prove the
current worktrees, or authorize publication. Current code, accepted decisions,
and freshly executed checks remain authoritative.

## Provenance

The reports came from Claude session
`346992e7-eac1-4092-8012-86e27637a8bd`. The original files lived under that
session's `/private/tmp` scratchpad and would not survive routine temporary-file
cleanup.

- `raw/out1.txt` through `raw/out12.txt` are byte-for-byte copies of the full
  agent traces.
- `reports/` contains the final answer from each trace, extracted after its
  `tokens used` marker for easier reading.
- `MANIFEST.tsv` records each trace's scope, session identity, timestamp, size,
  line count, and SHA-256 digest.
- `SHA256SUMS` covers all 36 files under `raw/`, `reports/`,
  `source-snapshots/`, and `closure/`. Its own digest is
  `70c1b0adb2ae3a48526b10bbb8203dbc392154a8face23fe52b6d4048efb6dc6`.

The raw traces repeat each final answer once as part of the event stream. The
short reports retain the final copy and do not replace the traces behind
absence or comparison claims.

## Preservation closure

The sweep is no longer report-only. [`closure/dispositions.tsv`](closure/dispositions.tsv)
accounts for 272 distinct findings across all twelve reports. Every finding is
classified as physically copied, retained at an exact active-repository
commit and path, reproducible from preserved inputs, or superseded with
evidence. The readable rules and totals are in
[`closure/README.md`](closure/README.md).

Complete tracked source exports and verified Git history bundles are under
[`source-snapshots/`](source-snapshots/). The ignored datasets and receipts are
covered by the complete output copies and SHA-256 manifests described in
[`../../../_preserved-2026-08-27/README.md`](../../../_preserved-2026-08-27/README.md).
Preservation does not accept a candidate behavior, change current ownership,
or authorize retirement; those remain separate decision and verification
boundaries.

## Review map

| Report | Scope |
| --- | --- |
| `01-source-catalog.md` | Landing source-catalog implementation and successor gaps |
| `02-metadata-complete-diff.md` | Dirty metadata-complete predecessor work |
| `03-docpipeline-core.md` | Document pipeline, segmentation, models, and handoffs |
| `04-document-release.md` | `DocumentRelease` v1-v3 family |
| `05-acquisition-parsers.md` | Acquisition, parser, and build-tool behavior |
| `06-docs-evidence.md` | Specifications, evidence, and broken citations |
| `07-ontology.md` | Ontology, candidate generation, review, and release gates |
| `08-source-native-publication.md` | Source-native publication and public tables |
| `09-tests-fixtures.md` | Test invariants and local-only fixtures |
| `10-top-level-modules.md` | Pipelines, transforms, corpora, and materialization |
| `11-adapters-extraction.md` | Extraction adapters, model safety, and retrieval experiments |
| `12-assets-workflows.md` | Large outputs, receipts, samples, and workflows |

## Deduplicated findings

The sweep adds six broad groups to the first index:

1. **Catalog predecessor behavior.** Preserve the policy-scoped universe and
   reason taxonomy, independent consumer recomputation, unavailable and failed
   draw rows, verified-byte rendition preference, source-topic namespace
   refusal, closed lexical checks, separate source-item and document identity,
   carried schema bytes, and the exact predecessor universe and measurements.
2. **Acquisition and publication behavior.** Preserve replayable source-native
   releases, capped-window and terminal-enumeration proofs, exact listing and
   tie refusal, external-blob accounting, faithful public Parquet and Iceberg
   views, and the source-specific CourtListener, OLRC, USLM, Supreme Court, and
   bill-subject parsing rules.
3. **Document and processing behavior.** Evaluate the reported v3 reader and
   reversibility gaps, active-set and compaction rules, structure-aware token
   packing, sealed model-input handoff, provider-free forensic rebuild,
   Office/Docling extraction, structured model adapters, thin-parse refusal,
   SPLADE, and reranking with restart and drift checks.
4. **Ontology and evaluation behavior.** Preserve corpus-wide acceptance
   gates, negative outcomes, independent candidate channels, attestations,
   append-only and acyclic assertions, published-release proof, and the named
   test invariants and local-only fixtures.
5. **Materialization and operational behavior.** Preserve atomic dataset
   resolution, conservative rulemaking identity and time transforms,
   schema/source-domain drift checks, raw provider judgments, CourtListener
   capacity and failure measurements, exact receipt tuples, workflow schedules,
   and the MCP deployment smoke gate.
6. **Exact data and lineage.** Retain the large copied datasets, sample
   captures, historical pins, and experimental policies required to replay
   old measurements, while keeping them separate from current authority.

Several findings overlap intentionally: separate agents inspected code,
documentation, tests, and assets as independent evidence. Existing root-index
entries for SPLADE, reranking, Federal Register identifiers, IRI minters,
OLRC/USLM, approximate nearest-neighbor search, relation evaluation, and
retention remain the concise primary entries; these reports supply broader
supporting detail.

## Measurement cautions

Report 12 cites approximately 23.1 GB and 9.3 GB from the source directories it
inspected. The root index records approximately 11 GB and 8.7 GB for the
selected preserved copies. These figures describe different scopes. Use the
copy manifests and per-file hashes, not either rounded source-directory total,
when deciding what was preserved.

Many report links name historical worktree paths. A missing path does not erase
the preserved report, and a surviving path does not make the report current.
Recheck the live repository and its accepted decisions before adopting a
finding.

<!-- markdownlint-disable MD013 -->

# Research-input register

RefSpec was designed against a broad source and controlled-resource portfolio.
The public [research archive](../research/README.md) preserves the inventories,
proposals, and external research used by the 28 July 2026 editor's draft.

The archive is not a closed list of source types, document types, vocabularies,
ontologies, thesauri, or authority files. A conforming implementation can add
other resources through the extension and portfolio-accounting rules in the
specification.

## Normative portfolio baseline for this editor's draft

Only the enumerated row universes of these two inventories form the
editor's-draft portfolio baseline. Their architecture proposals and adoption
recommendations are informative.

| Input | Public archive | Published SHA-256 | Pre-publication snapshot SHA-256 |
| --- | --- | --- | --- |
| *Source and Document Type Matrix*, 28 July 2026 | [Research snapshot](../research/source-document-type-matrix-2026-07-28.md) | `94a021c1da378cdf767d2f2f10264891364ec997df86aba9e44be19c98cbfd3e` | `ce82a5f74111222b14fb8429cfe3293cd7aaad86808583d301974ad6a75f5bd7` |
| *Source Vocabulary, Ontology, Thesaurus, and Authority Catalog*, 28 July 2026 | [Research snapshot](../research/source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md) | `cf0f642188840c9df74819750b6ab9f4feabcd18d56322fdbf269892f24a6191` | `09ed778632f2f22e3b64693de82afc6f1bcff45d3540ea28cd96c39334e0d53b` |

The published digests identify the neutral public editions. The
pre-publication digests identify the source snapshots before private
provenance, product identifiers, endpoints, and repository-local paths were
removed. The editorial scrub did not intentionally change the inventories'
row universes.

## Informative research

The [external label-space research index](../research/evidence/blind-external-research-recovery-2026-07-28/README.md)
links to reports on:

- [industry and large-label-space tagging](../research/evidence/blind-external-research-recovery-2026-07-28/01-industry-and-llm-era-large-label-space-tagging.md);
- [extreme multilabel classification](../research/evidence/blind-external-research-recovery-2026-07-28/02-extreme-multilabel-classification.md);
- [taxonomy induction](../research/evidence/blind-external-research-recovery-2026-07-28/03-taxonomy-induction.md);
- [label text and embedding geometry](../research/evidence/blind-external-research-recovery-2026-07-28/04-label-text-and-embedding-geometry.md);
- [controlled-vocabulary scoping](../research/evidence/blind-external-research-recovery-2026-07-28/05-controlled-vocabulary-scoping.md);
- [source partitioning and metadata priors](../research/evidence/blind-external-research-recovery-2026-07-28/06-source-partitioning-and-metadata-priors.md);
- [United States federal controlled vocabularies](../research/evidence/blind-external-research-recovery-2026-07-28/07-us-federal-controlled-vocabularies.md);
- [corpus-driven vocabulary development](../research/evidence/blind-external-research-recovery-2026-07-28/08-corpus-driven-vocabulary-development.md); and
- [controlled-vocabulary stop rules and a federal inventory](../research/evidence/blind-external-research-recovery-2026-07-28/when-to-abandon-controlled-vocabulary-and-federal-vocabulary-inventory.md).

The public external-research index has SHA-256
`ed70f1befad68bd7df101bee4a8885c5f54a2168e5167f6575a4a436717e8f92`;
its pre-publication snapshot had SHA-256
`4409eef997dd52579762a49655728f1812f2ff82a6158397d253e9f57674d8f8`.

The public stop-rules report has SHA-256
`466960e81481a269dfc881de3b49569793b34e9991179f2fbe5275efd4ac26ad`;
its pre-publication snapshot had SHA-256
`46fe48f589ae9239e480d66ca0af57c87d48791662c8d4654dc642b962ad6ee7`.

## Publication gate

Before a RefSpec release treats either inventory as a normative conformance
input, maintainers MUST:

1. pin the exact RefSpec commit and verify each published digest;
2. record access and permitted-use terms for the baseline;
3. enumerate every constituent as required by RefSpec Section 2.6;
4. pin that enumeration in the release manifest; and
5. publish a new digest and change note whenever a baseline file changes.

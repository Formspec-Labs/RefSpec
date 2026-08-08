# RefSpec research archive

This directory preserves the research used to shape the 28 July 2026 RefSpec
editor's draft. The archive is public so readers can inspect the source
portfolio, design rationale, and evidence behind the specification.

The files are research snapshots, not normative RefSpec requirements. The
[specification](../spec/refspec.md) and
[Rulespec application profile](../profiles/rulespec-application-profile.md)
define conformance. The
[managed vocabulary experiment roadmap](../plans/managed-vocabulary-experiment-roadmap.md)
defines current execution. The
[early implementation plan](../plans/implementation-plan.md) is a historical,
non-authoritative conceptual draft.

Private transcript locations, session identifiers, product identifiers,
private endpoints, and repository-local implementation paths were removed for
publication. Those removals do not change the substantive findings.

## Portfolio inventories

- [Source and Document Type Matrix](source-document-type-matrix-2026-07-28.md)
- [Source Vocabulary, Ontology, Thesaurus, and Authority Catalog](source-vocabulary-ontology-thesaurus-catalog-2026-07-28.md)

These two inventories are the editor's-draft portfolio baseline. They test the
framework's breadth but do not limit RefSpec to the listed sources, document
types, or controlled resources.

## Architecture research

- [Concept Tagging Architecture Research Proposal](concept-tagging-architecture-proposal-2026-07-28.md)
- [Axiom Ecosystem Assessment](axiom-ecosystem-analysis-2026-07-28.md)

These documents record proposals and adjacent-system analysis. RefSpec adopts
only the decisions that appear in the specification or application profile.

## External label-space research

The [external-research index](evidence/blind-external-research-recovery-2026-07-28/README.md)
links to nine reports covering:

- large-label-space tagging;
- extreme multilabel classification;
- taxonomy induction;
- label text and embedding geometry;
- controlled-vocabulary scoping;
- source partitioning and metadata priors;
- United States federal controlled vocabularies;
- corpus-driven vocabulary development; and
- controlled-vocabulary stop rules.

## Controlled-resource research

- [Regulatory and legal resources](evidence/source-vocabulary-research-2026-07-28/01-regulatory-legal.md)
- [Legislative and fiscal resources](evidence/source-vocabulary-research-2026-07-28/02-legislative-fiscal.md)
- [Health and specialist resources](evidence/source-vocabulary-research-2026-07-28/03-health-domain.md)
- [Roadmap feeds and reference spines](evidence/source-vocabulary-research-2026-07-28/04-roadmap-reference-feeds.md)

## Managed-vocabulary execution evidence

- [ELSST R5/R6 managed-release scale proof](evidence/elsst-r5-r6-managed-release-2026-07-29/README.md)
- [Federal Register topics unresolved reconciliation proof](evidence/federal-register-topics-reconciliation-2026-07-29/README.md)

## Static atlas research

- [Multidimensional vocabulary atlas experiment](evidence/vocabulary-atlas-graph-experiment-2026-07-31.md)
- [LadybugDB static-atlas serving spike](evidence/ladybug-vocabulary-atlas-spike-2026-07-31/README.md)
- [GraphDB v5 repository configuration](evidence/vocabulary-atlas-graphdb-v5/README.md)

These snapshots preserve the experiments that led to the two-graph static
asset. Their document-oriented projections predate the four-product split.
Current RefSpec code retains only managed-vocabulary, crosswalk, and static
atlas behavior; SpicyRegs and SpicySearch own document data and retrieval.

## Archived implementation evidence

- [Atlas 3.0 exhaustive compact-to-RDF parity](archive/atlas-3.0-exhaustive-compact-parity-2026-08-08.md)

This note identifies the exact Git snapshot for the retired exhaustive parity
check. The current Atlas 3 binding and decision ledger remain authoritative.

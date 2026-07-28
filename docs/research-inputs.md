# Research-input register

RefSpec was designed against a broad source and controlled-resource portfolio.
Those documents remain external research inputs; they are not RefSpec
specifications and are not copied here.

This register gives the 28 July 2026 editor's draft stable content identities
for the inputs it used. The source files are not yet published at immutable
GitHub URLs. A RefSpec release MUST replace the local-source status with
immutable source revisions or package identifiers before it can claim the
portfolio baseline.

## Normative portfolio baseline for this editor's draft

| Input | Source status | SHA-256 |
| --- | --- | --- |
| *Source and Document Type Matrix*, 28 July 2026 | Local research snapshot; not yet published | `ce82a5f74111222b14fb8429cfe3293cd7aaad86808583d301974ad6a75f5bd7` |
| *Source Vocabulary, Ontology, Thesaurus, and Authority Catalog*, 28 July 2026 | Local research snapshot; not yet published | `09ed778632f2f22e3b64693de82afc6f1bcff45d3540ea28cd96c39334e0d53b` |

These inventories are the minimum breadth and portfolio-accounting test for
this draft. They are not a closed list of source types or controlled
resources, and their architecture proposals and adoption recommendations are
not incorporated by reference.

## Informative research

The draft also considered a recovered external-research set dated 28 July
2026:

- industry and large-label-space tagging;
- extreme multilabel classification;
- taxonomy induction;
- label-text and embedding geometry;
- controlled-vocabulary scoping;
- source partitioning and metadata priors;
- United States federal controlled vocabularies;
- corpus-driven vocabulary development; and
- when to abandon a controlled vocabulary.

The recovered research is not copied here because it includes project-specific
provenance and machine-local recovery context. Its index snapshot has SHA-256
`4409eef997dd52579762a49655728f1812f2ff82a6158397d253e9f57674d8f8`.
The separately recovered controlled-vocabulary report has SHA-256
`46fe48f589ae9239e480d66ca0af57c87d48791662c8d4654dc642b962ad6ee7`.

## Publication gate

Before a RefSpec release treats either inventory as a normative conformance
input, maintainers MUST:

1. publish or package the exact source bytes under an immutable identifier;
2. verify the recorded digest;
3. record access and permitted-use terms;
4. enumerate the baseline as required by RefSpec Section 2.6; and
5. pin that enumeration in the release manifest.

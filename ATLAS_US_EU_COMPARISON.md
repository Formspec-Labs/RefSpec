# Atlas in the United States and Europe

_Landscape review as of August 6, 2026_

## Conclusion

Europe operates an Atlas-like ecosystem, although several services divide the
work. The United States operates strong domain systems, but no publicly
documented service combines Atlas's full scope.

The clearest position for Atlas is:

> **Atlas is a U.S. public reference-data authority: EU Vocabularies-style
> publication, UMLS-style reconciliation, NIEM-style breadth, and a stricter
> evidence model.**

This review compares what each system governs, reconciles, publishes, and
proves. Shared use of RDF alone does not make two systems equivalent.

## Europe

[EU Vocabularies](https://op.europa.eu/en/web/eu-vocabularies/about) is the
closest overall match. It publishes EU-managed thesauri, authority tables, code
lists, ontologies, schemas, and data models with stable identifiers, versions,
multiple formats, alignments, documentation, and release history.

Its supporting services divide responsibilities that Atlas currently combines:

| Service | Role | Relationship to Atlas |
| --- | --- | --- |
| [EU Vocabularies](https://op.europa.eu/en/web/eu-vocabularies/about) | Publishes controlled vocabularies, models, versions, downloads, and documentation. | Closest European counterpart to Atlas publication. |
| [VocBench and ShowVoc](https://op.europa.eu/en/web/eu-vocabularies/online-tools) | Provide collaborative editing and visual exploration. | Models the editor and explorer services Atlas still needs. |
| [EU Vocabularies release views](https://op.europa.eu/en/web/eu-vocabularies/navigation) | Provide base SKOS, richer SKOS-AP-ACT with SKOS-XL and editorial metadata, previous versions, release notes, diffs, and cross-vocabulary mappings. | Closely matches Atlas's source, label, lifecycle, and mapping concerns. |
| [Cellar](https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph) | Stores EU publications and metadata in a public knowledge graph with REST and SPARQL access. | Supplies the document and public-query layer outside Atlas's current static release. |
| [EuroVoc](https://op.europa.eu/en/web/eu-vocabularies/eurovoc) | Provides a multilingual, multidisciplinary governmental thesaurus. | Resembles a major Atlas subject-ring source. |
| [ESCO](https://esco.ec.europa.eu/en/about-esco/what-esco) | Publishes occupations, skills, and their relationships for labor and education. | Covers one domain; it is not a general Atlas equivalent. |

Europe's advantage is operational maturity: public identifiers, APIs, SPARQL,
multilingual delivery, editors, stewardship, versions, and change information.

Atlas can offer a stronger and more consistent boundary between:

- publisher assertions;
- cross-source mappings;
- derived relationships;
- evidence and review warrants; and
- immutable, digest-pinned releases.

European services use many of these ideas, but no single portable model applies
all of them across the ecosystem.

## United States

No single U.S. system combines Atlas's intended breadth, source preservation,
reconciliation, evidence, and release discipline. The pieces remain distributed
across institutions.

| System | What it does | Difference from Atlas |
| --- | --- | --- |
| [Library of Congress Linked Data Service](https://www.loc.gov/apis/additional-apis/linked-data-service/) | Publishes authorities, controlled vocabularies, ontologies, stable URIs, downloads, and APIs. | It centers on library and bibliographic data and does not attach Atlas-style evidence to every assertion. |
| [O*NET](https://www.onetcenter.org/database.html) | Publishes more than 900 occupations with skills, tasks, knowledge, abilities, ratings, crosswalks, quarterly releases, RDF, downloads, and APIs. | O*NET is effectively the U.S. counterpart to ESCO, but only for employment and skills. |
| [UMLS Metathesaurus](https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/index.html) | Reconciles nearly 200 biomedical vocabularies while preserving source terms, codes, hierarchies, and relationships. | It provides the strongest precedent for Atlas-style reconciliation, but its scope is biomedical and some sources restrict reuse. |
| [NCI Enterprise Vocabulary Services](https://www.cancer.gov/about-nci/organization/cbiit/vocabulary) | Operates terminologies, ontologies, value sets, mappings, an editor, downloads, a browser, and a triple-store API. | It demonstrates a mature operational service within cancer and biomedicine. |
| [NIEMOpen](https://niemopen.org/about/model/) | Provides a governed common vocabulary and reusable data model across government domains, with harmonization and versioned releases. | It defines how systems exchange information; it does not publish a populated national reference graph. |
| [EPA System of Registries](https://sor.epa.gov/sor_internet/registry/termreg/searchandretrieve/home.do) | Maintains environmental terminology, substances, facilities, laws, identifiers, synonyms, and hierarchies. | It is the closest operational agency-scale analogue, but it is environmental rather than government-wide and does not use Atlas's immutable release model. |
| [Data.gov](https://resources.data.gov/catalog-api/) | Catalogs dataset metadata from federal, state, local, and tribal governments. | It discovers datasets but does not reconcile the concepts and identifiers inside them. |
| [NSF Proto-OKN](https://www.nsf.gov/tip/updates/nsf-invests-first-ever-prototype-open-knowledge-network) | Funded 18 projects to build interoperable public knowledge graphs and connecting infrastructure. | It is the closest national graph initiative, but it remains a research federation rather than a standing semantic authority. |
| [Data Commons](https://docs.datacommons.org/what_is.html) | Normalizes public statistical datasets, reconciles entities and schemas, and provides a graph browser and APIs. | It is statistical, global, Google-led, and not an evidence-pinned public reference authority. |

Atlas is therefore not the first U.S. linked-data system, terminology service,
or knowledge graph. Its distinct contribution can be the combination of their
strongest properties across unrelated public domains.

## Atlas today

The Atlas 3.0 binding already defines a strong authority and release model. See
the [Atlas 3.0 binding](bindings/atlas/3.0/README.md) and the
[decision ledger](docs/decisions.md).

The local full-development build reviewed on August 6, 2026 contained:

- 110 source releases represented by 109 normalized Atlas releases;
- 588,409 resources;
- 984,114 English labels; and
- 560,429 relationship assertions.

It also contained 2,003 separately evidenced EuroVoc--LCSH mappings, zero
projected relations, zero derived relations, and one cross-ring relation. Most
resources belonged to the subject ring. These dated figures describe the ignored local build at
`output/atlas-3.0-full-2026-08-06/`; they do not describe a published release.

Atlas has therefore reached a specific stage:

- The binding and release machinery are strong.
- The current artifact faithfully federates source data.
- Cross-source semantic reconciliation has begun with one official alignment;
  broader qualification remains future work.
- Public stable URLs, APIs, editorial workflows, and service operations remain
  future work.

## Position and direction

Calling Atlas "the U.S. ESCO" would obscure its scope because O*NET already
fills much of that role. A more accurate description is:

> **Atlas is the missing U.S. public vocabulary, identifier, and reference-data
> commons, built with verifiable provenance and an explicit boundary between
> published facts and derived knowledge.**

The next work that makes this position credible is not another schema rewrite.
It is:

1. qualifying cross-source mappings;
2. publishing stable web identifiers, downloads, and APIs;
3. establishing steward and editorial workflows; and
4. expanding entity, value, legal-identity, and cross-ring coverage.

This absence finding is bounded to public sources reviewed through August 6,
2026. Internal government programs and changing Proto-OKN projects may not be
publicly visible.

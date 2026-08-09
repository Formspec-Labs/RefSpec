# Atlas source-fidelity issues

Status: development finding from the August 7, 2026 local Atlas candidate at
`output/atlas-3.0-full-2026-08-07-ring-audit/`. This is not a published release
assessment.

## Working acceptance rules

The current product priority is usable, complete English data. Missing
non-English labels and annotations are not release blockers. An English-only
selection is acceptable when the release declares that scope.

Official distributions are preferable, but they are not required. Scraped,
sampled, reconstructed, or extrapolated data is acceptable when the release
records:

- the source locator and captured input bytes, when available;
- the capture date, source version or observation window, and byte digest;
- whether each value was observed, scraped, normalized, inferred, or
  extrapolated;
- the extraction or derivation method and its version;
- the covered population, known omissions, assumptions, and confidence limits;
  and
- a materialized, digest-pinned derived dataset that Atlas can be compared
  against directly.

Under this policy, source fidelity means that Atlas matches the declared,
pinned input dataset for the release. A release may improve malformed source
data or fill gaps, but it must retain the raw capture, distinguish observed
claims from derived claims, and declare every repair or extrapolation. Silent
repair and silent omission remain failures.

Atlas-only semantic rings, profiles, governed schemes, releases, class
assignments, and named-graph placement do not participate in the source-data
verdict. Publisher-native schemes and memberships remain source data.

## Ranked issues

Counts can overlap because one missing claim can fail more than one check.

| Rank | Priority | Issue | Effect on use or completeness |
| ---: | :---: | --- | --- |
| 1 | P0 | **87 of 110 construction units have no independent comparison.** | Most of the candidate cannot yet be certified against a pinned publisher, scrape, or derived dataset. Uncovered units fail closed. |
| 2 | P0 | **Only 5 of 75 indexed registry resources are release-ready; 70 lack an exact release.** | The binding describes substantially more material than it can deliver as reproducible data. Scraped or extrapolated releases can close this gap if they follow the evidence rules above. |
| 3 | P0 | **9,667 publisher semantic relations are missing.** | Hierarchy and related-concept navigation are incomplete. GEMET accounts for 9,658 missing relations, DOE for five, and the bounded NALT sample for four. Every relation Atlas does emit is source-backed and directionally exact. |
| 4 | P0 | **GEMET collection and grouping structure is largely absent.** | Atlas omits 16,178 `skos:member` edges, 78 group memberships, 32 subgroup relations, and supporting group identities and labels. Users cannot reproduce GEMET's thematic organization. |
| 5 | P1 | **Useful English explanatory content is missing.** | EuroVoc is missing 1,557 English definitions and 558 English notes. The bounded NALT sample is missing one English annotation-target definition. Four additional GEMET English definitions are empty in the source and provide no usable content. |
| 6 | P1 | **NASA relation annotations cannot be reconstructed.** | The 160,370 base NASA relations match, but 9,656 `zthes:termNote` annotations, their detached labels, and their RDF reification context are absent. Navigation works; supporting context does not. |
| 7 | P1 | **Publisher-native scheme descriptions are missing.** | Atlas cannot reconstruct 133 `ConceptScheme` identities, six IRI metadata claims, or 3,639 scheme literals. All 48,113 source memberships do reconstruct exactly, including all 15,438 EuroVoc memberships. |
| 8 | P1 | **113 hierarchy-root claims are missing.** | GEMET loses 112 `hasTopConcept` claims. DOE loses one because the source points to undeclared concept `29668`. Root-based browsing can omit valid entry points. |
| 9 | P1 | **Member and source metadata is heavily reduced.** | Atlas omits 9,891 IRI-valued member claims and 109,784 literal or detached-source claims. Much of this is secondary metadata, but it affects provenance, dates, classifications, and auditability. |
| 10 | P1 | **32,648 source-shaped claims fall outside an executable comparison.** | The total contains 21,641 publisher claims and 11,007 Atlas claims. The Atlas side is mostly `atlas:recordStatus` values without demonstrated source or derivation evidence. |
| 11 | P1 | **The covered RDF units still have 69 incomplete claim-family evaluations and 142 provenance failures.** | Embedded fields such as AGROVOC capture data, EuroVoc publisher/license/version data, mapping-release metadata, and NALT capture information are not independently tied to observed or derived inputs. |
| 12 | P1 | **The 11 artifact acceptance gates do not establish source fidelity.** | They perform useful internal checks but never compare Atlas with publisher, scraped, or derived input bytes. A passed acceptance receipt can therefore coexist with incomplete source data. |
| 13 | P2 | **EuroVoc--LCSH release metadata is missing.** | All 2,003 mapping pairs and their `exactMatch` or `closeMatch` types are correct, but 856 release, linkset, statistics, and provenance claims are unrepresented. Pair lookup works without this context; audit and reuse are weaker. |
| 14 | P2 | **ELSST note roles are flattened.** | English note text is generally retained, but source distinctions such as `scopeNote` and `historyNote` can become generic `atlas:note`. Humans can read the note while software loses its intended role. |
| 15 | P3 | **Twenty GEMET notations change RDF literal shape.** | Lexical values remain, but source language-tagged values become `xsd:string`. This matters only to datatype-sensitive consumers. |
| 16 | P3 | **Eighteen English labels are whitespace-normalized without a declared rule.** | Two ELSST and sixteen EuroVoc labels have newlines or non-breaking spaces trimmed. The normalized values are more usable, and this repair is acceptable under the working policy once the release declares it and preserves the raw values. |
| 17 | Accepted limitation | **Non-English labels and annotations are omitted.** | The current verifier reports the omissions because it compares every language. They are not a usability or release-priority issue under the English-only policy, but the release must declare its language scope so consumers do not assume multilingual coverage. |

## Defects in source data

These are publisher-data defects. They should remain visible in the raw capture.
Atlas may repair or supplement them in a separately identified derived release.

| Source | Defect | Recommended disposition |
| --- | --- | --- |
| ELSST | Uses `dcat:CatalogRecord`, normally a class, as a predicate on 51,848 triples. | Preserve the raw triples. If Atlas extracts the linked information into a better shape, identify the extraction as a declared transformation. |
| ELSST | Declares a namespace containing whitespace, represented as `http://purl.org/dc/terms/%20#`. Strict parsers can fail or disagree across serializations. | Retain the raw capture and publish the parser or repair rule used for the derived dataset. |
| GEMET | Contains 11,298 empty literals typed as `xsd:dateTime`. | Preserve them in raw evidence; omit or replace them only through a declared invalid-date rule. |
| AGROVOC bounded sample | Contains 41 referenced SKOS-XL label nodes with no `literalForm`. | Preserve the broken nodes. A scrape or supplemental lookup may add text as derived evidence, not as an unqualified publisher assertion. |
| DOE | Has one `hasTopConcept` target, `29668`, that is not declared as a concept. | Preserve the dangling source claim or create an explicitly derived unresolved placeholder; do not silently drop it. |
| EuroVoc | Publishes VoID metadata through blank-node structures that the current Atlas reverse path cannot reproduce. | Retain the metadata as a pinned supplemental artifact or implement a declared reverse shape. |
| EuroVoc metadata | Contains four `skos:Concept` resources without a preferred label. | A scraped or inferred label is acceptable when marked as derived and linked to its evidence. |
| ELSST and EuroVoc | Contain 18 English labels with surrounding newline or non-breaking-space characters. | Normalize for display if desired, while retaining the exact raw value and naming the normalization rule. |

## Material that already passes

- All 62,830 covered concept identities trace to publisher records and retain
  publisher IRIs.
- All 343,353 emitted relations match a source relation exactly, including
  predicate and direction; none is manufactured or strengthened.
- All 48,113 publisher-native scheme memberships reconstruct exactly.
- All 2,003 EuroVoc--LCSH mapping relations match.
- All 1,861 covered Regulations.gov, Federal Register, and Unified Agenda
  native-control values match.
- All 17 inspected input artifacts match their declared pins, and all 23
  inspected Atlas packs load successfully.

The machine-readable evidence is the local receipt at
`/tmp/refspec-atlas-source-fidelity-v10.json`; the complete collected-error log
is `/tmp/refspec-atlas-source-fidelity-v10.log`.

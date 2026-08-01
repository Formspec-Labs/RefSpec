# Vocabulary atlas in GraphDB

This configuration documents the historical pre-split v5 artifact and retains
its original namespace. New RefSpec atlas generations use the current RefSpec
asset manifest and query API.

The atlas is a standard N-Quads dataset. Import `atlas.nq` without rewriting
its graph contexts. Create the repository from
`vocabulary-atlas-repository.ttl`, which selects the empty ruleset, disables
`owl:sameAs` optimization, and enables context and predicate-list indexes.

The dataset intentionally contains two populated named graphs:

- the graph whose IRI is also an `atlas:AtlasGeneration` is asserted and
  source-backed;
- the graph whose IRI is also an `atlas:AnalysisGeneration` is replaceable
  candidate analysis.

Do not union the two graphs in authority-sensitive queries.

## Find the current graph IRIs

```sparql
PREFIX atlas: <https://spicy-regs.dev/ns/vocabulary-atlas#>

SELECT ?asserted ?analysis
WHERE {
  GRAPH ?asserted {
    ?asserted a atlas:AtlasGeneration ;
      atlas:analysisGraph ?analysis .
  }
  GRAPH ?analysis {
    ?analysis a atlas:AnalysisGeneration .
  }
}
```

## Filter exact source dimensions

This example finds a Federal Register document with an exact agency, document
type, and CFR part. Source controls remain observations; the query does not
turn their values into concepts.

```sparql
PREFIX atlas: <https://spicy-regs.dev/ns/vocabulary-atlas#>

SELECT DISTINCT ?document
WHERE {
  GRAPH ?asserted {
    ?asserted a atlas:AtlasGeneration .

    ?agencyObservation
      a atlas:SourceControlObservation ;
      atlas:controlSubject ?document ;
      atlas:controlKind atlas:FederalRegisterAgency ;
      atlas:controlValue
        <https://www.federalregister.gov/agencies/food-safety-and-inspection-service> .

    ?typeObservation
      a atlas:SourceControlObservation ;
      atlas:controlSubject ?document ;
      atlas:controlKind atlas:FederalRegisterDocumentType ;
      atlas:controlValue "Proposed Rule" .

    ?cfrObservation
      a atlas:SourceControlObservation ;
      atlas:controlSubject ?document ;
      atlas:controlKind atlas:FederalRegisterCfrReference ;
      atlas:controlValue <urn:rkaf:us:cfr:9:381> .
  }
}
```

## Filter current Federal Register API Topics

API Topics remain mutable source observations. Match the qualified normalized
label; do not query them as SKOS concepts.

```sparql
PREFIX atlas: <https://spicy-regs.dev/ns/vocabulary-atlas#>

SELECT DISTINCT ?document
WHERE {
  GRAPH ?asserted {
    ?asserted a atlas:AtlasGeneration .
    ?observation
      a atlas:SourceTermObservation ;
      atlas:observedOn ?document ;
      atlas:observationKind atlas:FederalRegisterApiTopic .
    ?labelRecord
      a atlas:SourceObservationLabelRecord ;
      atlas:observation ?observation ;
      atlas:normalizedLabel "meat inspection" .
  }
}
ORDER BY ?document
```

## Check Lists-of-Subjects resolution coverage

This query must return zero rows.

```sparql
PREFIX atlas: <https://spicy-regs.dev/ns/vocabulary-atlas#>

SELECT ?observation
WHERE {
  GRAPH ?asserted {
    ?asserted a atlas:AtlasGeneration .
    ?observation
      a atlas:SourceTermObservation ;
      atlas:observationKind atlas:FederalRegisterListOfSubjects .
    FILTER NOT EXISTS {
      ?resolution
        a atlas:SourceTermResolution ;
        atlas:sourceObservation ?observation .
    }
  }
}
```

## Authority boundary

Accepted document tags require a complete `atlas:EnrichmentDecisionProjection`
in the asserted graph. Review-only assignments remain in the analysis graph.
Likewise, an equal-label `atlas:ConceptMappingCandidate` is not a reviewed
`rkaf:ConceptMapping`.

The application query code in
`src/spicy_regs/ontology/vocabulary_atlas_queries.py` enforces the full
assignment, decision, mapping, release-membership, and evidence shapes.

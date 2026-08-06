# Atlas 3 native-relation test sets

Date: 2026-08-06

Three per-source reference sets built from publisher-asserted intra-vocabulary
relations in the Atlas 3 source-native import. Regenerate with
`uv run python tools/build_atlas_native_relation_testsets.py`.

Every row is a publisher editorial decision. No RefSpec retrieval arm, scorer,
or judge produced any row, so these are independent of the candidate pipeline
in a way the 582 historical mapping assertions are not.

| File | Rows | Hierarchy | Associative | Equivalence |
| --- | ---: | ---: | ---: | ---: |
| `federal-register-thesaurus-2025.jsonl` | 780 | 0 | 780 | 0 |
| `elsst-r6.jsonl` | 6,241 | 3,393 | 2,848 | 0 |
| `icpsr-subject-thesaurus.jsonl` | 9,428 | 1,763 | 7,180 | 485 |

16,449 canonical rows from all 32,694 native relations in the build. The three
CRS releases contribute none.

## Row shape

One row per distinct edge. `subject` and `object` each carry `iri`, `label`,
`labelRole`, `altLabels`, and any `definition`, `notes`, and `notations`.

- **hierarchy** — directed, normalised to SKOS `broader` orientation, so
  `subject` is the narrower concept and `object` the broader one.
- **associative** — undirected, endpoints sorted by IRI.
- **equivalence** — directed from the publisher access term to the preferred
  term. ICPSR publishes access terms as members whose only label carries the
  `alternate` role, so check `labelRole` rather than assuming a preferred label.

`assertedPredicates` lists the raw predicates the publisher materialised for
the edge. `oneWayInSource` is true when only one direction was asserted.

## Deduplication

ELSST and ICPSR materialise every symmetric and inverse edge in both
directions. Scoring against the raw relation list would double every hierarchy
and associative edge and inflate any recall denominator. Rows collapse those to
one canonical edge and keep both source payloads.

Federal Register does not: 109 of its 780 associative edges are asserted in one
direction only. ICPSR has 95 such rows. That asymmetry is preserved, not
repaired.

## Ablation requirement

The sparse and graph retrieval arms read parent and child text. Scoring
retrieval against the **hierarchy** rows without first removing broader and
narrower text from the concept input measures whether retrieval recovers pairs
it was handed, not whether it can discover them. Ablate before scoring.

Associative and equivalence rows do not have this problem unless the harness
also injects related or `use` text.

## What these sets can and cannot measure

They can measure directional discovery, judge direction accuracy, directness
calibration against professional editorial practice, and synonym and acronym
recovery (`abduction` → `kidnapping`, `ACA` → `Affordable Care Act`).

They cannot measure cross-vocabulary mapping recall. No native cross-vocabulary
edges exist — that absence is why the Atlas is being built. The v3 build reports
`mappingAssertions: 0`.

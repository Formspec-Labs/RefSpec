# Vocabulary Atlas outside-BGE-K50 residual manual audit

Date: 2026-08-05

Status: fixed human decisions recorded before any row-level residual analysis.
This audit makes no provider call and changes no qualification or production
artifact.

The input is the 60-row English sentinel sample at
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-three-family-outside-bge-k50-residual-blind-review-sample.json`,
file SHA-256
`6286e56044f2fdb1a1a82430291f5bc2c34996c9852042c2bb312591d03ce5b6`
and internal sample digest
`sha256:70ad88877e7a01f3ac78a6958b053f5db69b29dd3197d2a48812f59002f4eda2`.
The context-only rendering has SHA-256
`153bb22fb2402ad192ab6c414a182e2dc46717a052614eba5e42f8f0533a90e4`.

The sample contains 15 rows from each of the four vocabulary pairs that have a
nonempty population outside both the lexical-K3 plus sparse/mutual-graph-K1
floor and five-view BGE K50. The two pairs with a 32-concept side have no such
population and therefore contribute no rows. I reviewed only preferred and
alternate labels, definitions, scope notes, and native parents and children.
The rendering omitted rank, known mappings, relation labels, and verdicts.

I applied the Atlas search-expansion rubric with a directness and nonredundancy
test. The finder needs plausible direct cross-vocabulary mappings, not every
pair that can co-occur or connect through an existing graph path. For example,
an actor and a broad field do not need a direct `relatedMatch` when native and
qualified links already connect the actor to an institution and the
institution to the field. Every verdict other than `unrelated` or
`insufficient_evidence` is a potential direct relation for blind judgment, not
an asserted mapping. `related` grants no default traversal.

| Row | Independent verdict | Row | Independent verdict | Row | Independent verdict |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `unrelated` | 21 | `unrelated` | 41 | `unrelated` |
| 2 | `unrelated` | 22 | `unrelated` | 42 | `unrelated` |
| 3 | `unrelated` | 23 | `unrelated` | 43 | `unrelated` |
| 4 | `unrelated` | 24 | `unrelated` | 44 | `unrelated` |
| 5 | `unrelated` | 25 | `unrelated` | 45 | `unrelated` |
| 6 | `unrelated` | 26 | `unrelated` | 46 | `unrelated` |
| 7 | `unrelated` | 27 | `unrelated` | 47 | `unrelated` |
| 8 | `unrelated` | 28 | `unrelated` | 48 | `unrelated` |
| 9 | `unrelated` | 29 | `unrelated` | 49 | `unrelated` |
| 10 | `unrelated` | 30 | `unrelated` | 50 | `unrelated` |
| 11 | `unrelated` | 31 | `unrelated` | 51 | `unrelated` |
| 12 | `unrelated` | 32 | `unrelated` | 52 | `unrelated` |
| 13 | `unrelated` | 33 | `related` | 53 | `unrelated` |
| 14 | `unrelated` | 34 | `unrelated` | 54 | `unrelated` |
| 15 | `unrelated` | 35 | `unrelated` | 55 | `unrelated` |
| 16 | `unrelated` | 36 | `unrelated` | 56 | `unrelated` |
| 17 | `unrelated` | 37 | `unrelated` | 57 | `unrelated` |
| 18 | `unrelated` | 38 | `unrelated` | 58 | `unrelated` |
| 19 | `unrelated` | 39 | `unrelated` | 59 | `unrelated` |
| 20 | `unrelated` | 40 | `unrelated` | 60 | `unrelated` |

The one potential direct row is based only on the displayed concept facts:

- `Critical infrastructure` and `MANUFACTURING INDUSTRIES` overlap in public
  policy because critical manufacturing is an infrastructure sector, but the
  displayed concepts do not support strict containment in either direction.

The other six initially plausible thematic associations—civil disturbances
with weapons, housing for older people with licensing, vaccination with
physical condition, an industry with revenue, public lands with national
security, and social insurance with economic crises—do not pass the directness
test. They can be expressed through more specific native or qualified graph
paths and would make the associative mapping layer noisy if asserted directly.

This fixed sentinel can show that useful candidates exist outside K50. Its
equal 15-row allocation across four unequal residual populations cannot
estimate pool prevalence, K50 recall, or a deeper rank cutoff. The next step
may join these decisions to population metadata and other retrieval arms; it
must not reinterpret the verdicts after seeing that evidence.

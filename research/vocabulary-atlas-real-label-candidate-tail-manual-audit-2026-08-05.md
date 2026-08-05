# Vocabulary Atlas real-label candidate tail manual audit

Date: 2026-08-05

Status: independent candidate decisions recorded before row-level rank and
rank-band analysis. This audit makes no provider call and changes no
qualification artifact.

The input is the 60-row English sample at
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-three-family-bge-tail-blind-review-sample.json`,
file SHA-256
`40ccb74a5b16893e06b9deb13946a69996e820020789e77cfdb424fab902651a`
and internal sample digest
`sha256:9961c0796940c4eb0d4bdf920763543a8418df02c09363a26e5a09ce632073cd`.
The context-only rendering has SHA-256
`c64a3cf47c5285d6081cd71e7f3fa480b7ee300a70b336f975378520c8a80543`.

The sample contains ten rows from each real Atlas vocabulary pair. I reviewed
only the numbered rendering's preferred and alternate labels, definitions,
scope notes, and native parents and children. The rendering omitted rank,
rank band, retrieval membership, known mappings, and verdicts.

I applied the Atlas search-expansion rubric. Every verdict other than
`unrelated` or `insufficient_evidence` is a potential relation that belongs in
front of the blind judges; it is not an asserted mapping. `related` grants no
default traversal.

| Row | Independent verdict | Row | Independent verdict | Row | Independent verdict |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `unrelated` | 21 | `unrelated` | 41 | `unrelated` |
| 2 | `unrelated` | 22 | `unrelated` | 42 | `related` |
| 3 | `unrelated` | 23 | `unrelated` | 43 | `related` |
| 4 | `unrelated` | 24 | `unrelated` | 44 | `unrelated` |
| 5 | `unrelated` | 25 | `unrelated` | 45 | `related` |
| 6 | `unrelated` | 26 | `unrelated` | 46 | `unrelated` |
| 7 | `unrelated` | 27 | `unrelated` | 47 | `unrelated` |
| 8 | `unrelated` | 28 | `unrelated` | 48 | `related` |
| 9 | `unrelated` | 29 | `unrelated` | 49 | `unrelated` |
| 10 | `unrelated` | 30 | `unrelated` | 50 | `unrelated` |
| 11 | `related` | 31 | `related` | 51 | `unrelated` |
| 12 | `unrelated` | 32 | `unrelated` | 52 | `unrelated` |
| 13 | `unrelated` | 33 | `related` | 53 | `related` |
| 14 | `unrelated` | 34 | `unrelated` | 54 | `unrelated` |
| 15 | `unrelated` | 35 | `related` | 55 | `unrelated` |
| 16 | `unrelated` | 36 | `related` | 56 | `unrelated` |
| 17 | `unrelated` | 37 | `unrelated` | 57 | `unrelated` |
| 18 | `unrelated` | 38 | `unrelated` | 58 | `unrelated` |
| 19 | `unrelated` | 39 | `unrelated` | 59 | `related` |
| 20 | `unrelated` | 40 | `target_is_narrower` | 60 | `unrelated` |

The 12 potential rows are deliberately interpreted from concept facts, not
from their withheld ranks:

- `Fraud offenses and financial crimes` and `Watches and jewelry` are
  associatively linked through jewelry fraud, stolen property, and financial
  crime, without implying substitution.
- `CRIMINAL DAMAGE` and `police response` are neighboring offense and response
  topics.
- `ECONOMIC VALUE` and `expenditures` are related economic measures.
- `LIBRARIES` and `Internet` are associated information-access systems.
- `PARENTING` and `intergenerational conflict` are directly associated family
  topics.
- `STATE AID` contains the more specific `small business tax credit`, so the
  target is narrower.
- `Bonds` and `RESEARCH FINANCE` connect a financing instrument with a funding
  domain.
- `Nuclear materials` and `ENERGY POLICY` are associated regulatory and energy
  topics without being subclasses of one another.
- `Public health` and `LIFE HISTORIES` are associated through health-history
  and longitudinal public-health evidence.
- `Tobacco` and `MIDWIVES` are associated through maternal and prenatal
  tobacco exposure and care.
- `Metric system` and `functional literacy` are associated through practical
  numeracy and measurement skills.
- `Archives and records` and `academic disciplines` are associated through
  research use, especially the target hierarchy's information-science and
  humanities branches.

The next step joins these fixed decisions to the withheld rank bands. That
comparison measures discovery yield; it does not reinterpret the decisions
after seeing the retrieval method.

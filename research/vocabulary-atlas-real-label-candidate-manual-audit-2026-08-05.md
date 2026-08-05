# Vocabulary Atlas real-label candidate manual audit

Date: 2026-08-05

Status: independent candidate decisions recorded before rank-band and signal
membership analysis. This audit makes no provider call and changes no
qualification artifact.

The input is the 120-row English sample at
`/tmp/refspec-candidate-benchmark.ANhNrc/atlas-three-family-blind-review-sample.json`,
file SHA-256
`300417f73210043c010be64389d60a672a59faf7c0b48d79fd0ad6a150a6a716`
and internal sample digest
`sha256:6be93190ae877e736cb0ee9ade720b5718ac258078bf7c97c224998ab855f2a8`.
It contains 20 rows from each real Atlas vocabulary pair. I reviewed a
context-only rendering with preferred and alternate labels, definitions, scope
notes, and native parents and children. The rendering omitted rank band,
retrieval family, cutoff membership, and any existing mapping label.

I applied the Atlas search-expansion rubric. Every verdict other than
`unrelated` or `insufficient_evidence` is a potential relation that belongs in
front of the blind judges; it is not an asserted mapping. `related` grants no
default traversal.

| Row | Independent verdict | Row | Independent verdict | Row | Independent verdict |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `related` | 41 | `target_is_broader` | 81 | `related` |
| 2 | `related` | 42 | `related` | 82 | `related` |
| 3 | `unrelated` | 43 | `unrelated` | 83 | `unrelated` |
| 4 | `unrelated` | 44 | `related` | 84 | `unrelated` |
| 5 | `related` | 45 | `related` | 85 | `unrelated` |
| 6 | `related` | 46 | `unrelated` | 86 | `related` |
| 7 | `unrelated` | 47 | `unrelated` | 87 | `related` |
| 8 | `unrelated` | 48 | `unrelated` | 88 | `related` |
| 9 | `unrelated` | 49 | `unrelated` | 89 | `related` |
| 10 | `unrelated` | 50 | `unrelated` | 90 | `related` |
| 11 | `unrelated` | 51 | `unrelated` | 91 | `unrelated` |
| 12 | `unrelated` | 52 | `unrelated` | 92 | `unrelated` |
| 13 | `target_is_narrower` | 53 | `target_is_broader` | 93 | `related` |
| 14 | `related` | 54 | `unrelated` | 94 | `target_is_broader` |
| 15 | `target_is_narrower` | 55 | `related` | 95 | `unrelated` |
| 16 | `unrelated` | 56 | `unrelated` | 96 | `unrelated` |
| 17 | `unrelated` | 57 | `unrelated` | 97 | `unrelated` |
| 18 | `unrelated` | 58 | `unrelated` | 98 | `unrelated` |
| 19 | `unrelated` | 59 | `unrelated` | 99 | `related` |
| 20 | `unrelated` | 60 | `unrelated` | 100 | `related` |
| 21 | `target_is_narrower` | 61 | `related` | 101 | `related` |
| 22 | `unrelated` | 62 | `related` | 102 | `unrelated` |
| 23 | `target_is_narrower` | 63 | `related` | 103 | `related` |
| 24 | `unrelated` | 64 | `unrelated` | 104 | `unrelated` |
| 25 | `related` | 65 | `related` | 105 | `related` |
| 26 | `related` | 66 | `unrelated` | 106 | `unrelated` |
| 27 | `unrelated` | 67 | `related` | 107 | `related` |
| 28 | `unrelated` | 68 | `related` | 108 | `unrelated` |
| 29 | `unrelated` | 69 | `related` | 109 | `related` |
| 30 | `unrelated` | 70 | `unrelated` | 110 | `related` |
| 31 | `related` | 71 | `unrelated` | 111 | `unrelated` |
| 32 | `unrelated` | 72 | `related` | 112 | `unrelated` |
| 33 | `related` | 73 | `related` | 113 | `related` |
| 34 | `unrelated` | 74 | `target_is_broader` | 114 | `related` |
| 35 | `unrelated` | 75 | `related` | 115 | `related` |
| 36 | `related` | 76 | `target_is_narrower` | 116 | `unrelated` |
| 37 | `related` | 77 | `unrelated` | 117 | `unrelated` |
| 38 | `unrelated` | 78 | `unrelated` | 118 | `unrelated` |
| 39 | `unrelated` | 79 | `unrelated` | 119 | `unrelated` |
| 40 | `unrelated` | 80 | `unrelated` | 120 | `unrelated` |

The next step joins these fixed decisions to the withheld rank bands and signal
memberships. That comparison measures discovery yield; it does not reinterpret
the decisions after seeing the retrieval method.

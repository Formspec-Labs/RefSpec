# Vocabulary Atlas direct and nonredundant candidate re-review

Date: 2026-08-05

Status: fixed human re-review of the 65 rows previously marked as possible
relations in the ranks 1-25 and ranks 26-50 samples. This changes no earlier
verdict, mapping assertion, qualification artifact, or production file.

## Question

The earlier rubric asked whether two concepts were broadly associated. The
refined question is narrower:

> Is this a plausible direct cross-vocabulary mapping worth sending to the
> blind judges, or is it a generic thematic shortcut that would make the graph
> noisy? If an existing typed path already supplies the useful navigation, is
> another direct edge redundant?

`direct_candidate` means the row still deserves blind semantic judgment. It is
not an asserted mapping. `generic_thematic` means the pair can co-occur or
influence one another but does not need a direct vocabulary edge.
`redundant_via_path` means the current Atlas already supplies a short typed
route with the same useful direction.

The re-review pins:

- the original ranks 1-25 decision file at SHA-256
  `4dc6a07fe2f0798254e0a0ef02dd497125ac98a3f5c9cf830596a8fc3f5256f7`;
- the original ranks 26-50 decision file at SHA-256
  `4490ddfde032ddbce4d8612a6dfa981066505ea8f3e7967036c60b918252cd6f`;
  and
- the bounded typed-path report at SHA-256
  `faf57dd27df4b0a10aa292dbd1ebb4aeb5872c56fdbdbc5e459159bdb9edee92`.

The 115 rows originally judged `unrelated` remain outside the direct-candidate
set. The tables below re-review every one of the 65 earlier positives.

## Ranks 1-25 re-review

| Row | Directness disposition | Row | Directness disposition | Row | Directness disposition |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `generic_thematic` | 21 | `direct_candidate` | 61 | `generic_thematic` |
| 2 | `generic_thematic` | 23 | `direct_candidate` | 62 | `generic_thematic` |
| 5 | `generic_thematic` | 25 | `direct_candidate` | 63 | `generic_thematic` |
| 6 | `generic_thematic` | 26 | `generic_thematic` | 65 | `generic_thematic` |
| 13 | `direct_candidate` | 31 | `generic_thematic` | 67 | `generic_thematic` |
| 14 | `generic_thematic` | 33 | `generic_thematic` | 68 | `generic_thematic` |
| 15 | `generic_thematic` | 36 | `generic_thematic` | 69 | `generic_thematic` |
| 37 | `generic_thematic` | 41 | `direct_candidate` | 72 | `generic_thematic` |
| 42 | `generic_thematic` | 44 | `generic_thematic` | 73 | `direct_candidate` |
| 45 | `generic_thematic` | 53 | `direct_candidate` | 74 | `direct_candidate` |
| 55 | `generic_thematic` | 75 | `generic_thematic` | 76 | `direct_candidate` |
| 81 | `generic_thematic` | 82 | `generic_thematic` | 86 | `generic_thematic` |
| 87 | `generic_thematic` | 88 | `direct_candidate` | 89 | `generic_thematic` |
| 90 | `generic_thematic` | 93 | `direct_candidate` | 94 | `redundant_via_path` |
| 99 | `generic_thematic` | 100 | `generic_thematic` | 101 | `generic_thematic` |
| 103 | `generic_thematic` | 105 | `generic_thematic` | 107 | `generic_thematic` |
| 109 | `generic_thematic` | 110 | `generic_thematic` | 113 | `generic_thematic` |
| 114 | `generic_thematic` | 115 | `generic_thematic` |  |  |

The 11 direct candidates are:

- `International Affairs` -> `Foreign officials`;
- `Land use and conservation` -> `Range management`;
- `Customs enforcement` -> `Countervailing duties`;
- `Housing supply and affordability` -> `Manufactured homes`;
- `Evidence and witnesses` -> `Law`;
- `Government ethics and transparency, public corruption` -> `Government
  Operations and Politics`;
- `FINANCIAL EXPECTATIONS` -> `consumer expectations`;
- `CRUISING HOLIDAYS` -> `holidays`;
- `PERCEPTION` -> `political perceptions`;
- `Foreign trade` -> `ECONOMIC POLICY`; and
- `Arms and munitions` -> `ARMS INDUSTRY`.

These rows express plausible cross-scheme overlap, direct hierarchy, or a
stable terminological association. The blind judges still determine the
semantic predicate and may reject them.

Row 94 is redundant for graph navigation:

```text
Federal Register Water resources
  -- baseline skos:closeMatch -->
ELSST WATER RESOURCES
  -- native skos:broader -->
ELSST NATURAL RESOURCES
```

That cautious close-plus-broader path has the same direction as the earlier
`target_is_broader` verdict. The original row remains evidence, but another
direct edge would repeat the existing route.

## Ranks 26-50 re-review

| Row | Directness disposition | Row | Directness disposition |
| ---: | --- | ---: | --- |
| 11 | `generic_thematic` | 31 | `generic_thematic` |
| 33 | `generic_thematic` | 35 | `generic_thematic` |
| 36 | `generic_thematic` | 40 | `direct_candidate` |
| 42 | `generic_thematic` | 43 | `generic_thematic` |
| 45 | `generic_thematic` | 48 | `generic_thematic` |
| 53 | `generic_thematic` | 59 | `generic_thematic` |

The one direct candidate is `STATE AID` -> `small business tax credit` at
exact BGE rank 50. The target is plausibly a specific form of the source. It is
the directness-aware reason not to select an earlier dense cutoff.

## Result and limit

Across the 65 earlier positives, 12 remain direct candidates, 52 are generic
thematic associations, and one is redundant through a current typed path. The
direct candidates occur at BGE ranks 1, 1, 1, 1, 1, 1, 2, 3, 5, 6, 8, and
50.
Eleven are at or below K8; the remaining hierarchy candidate is exactly K50.

This is a fixed expert review of a deterministic stratified sample, not
objective truth or population recall. It supports K50 as the widest measured
direct-candidate boundary and demonstrates why the judgment policy needs a
directness outcome. The separate outside-K50 sentinel still contains one
tentative direct association and therefore prevents a semantic-saturation
claim.

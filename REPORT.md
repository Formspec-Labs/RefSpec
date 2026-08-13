**No. Full scale does not change the memory verdict: TDB2's loader alone reached 11.756 GiB RSS and was stopped before it finished the database, so the disk-backed path did not stay bounded or establish a safe crossover.**

# Full-scale TopBraid/TDB2 memory result

Research date: 2026-08-13

Branch: `research/engine-fullscale`

Checkout at start: `d580bfad`

## Decision

The owner's fixed-JVM-cost explanation is insufficient. TDB2's stopped load
sat closer to the pySHACL full-scale peak than it did at staging, but its
resident set did not stay near a fixed baseline.
The full-scale loader's sampled RSS rose from 1,953.6 MiB at five seconds to
12,038.5 MiB at 95 seconds. The harness stopped it at the 11 GiB safety trigger,
249.5 MiB below the absolute 12 GiB limit.

The stop occurred after TDB2 had read all 29,286,753 quads but before it had
finished the indexes required for a valid database. The observed 11.756 GiB is
therefore a lower bound on full-load peak RSS, not a completed TDB2 result. A
partial load below pySHACL's completed 13.83 GiB acceptance peak does not prove
a crossover.

This result answers the narrow hypothesis: the tested native-store load was not
bounded. It does not qualify TopBraid as a replacement, and it does not justify
a larger-memory repeat on this shared machine.

## Load phase

The requested artifact contains 126 packs and 29,286,753 quads. This is the
specified `2026-08-13b` distribution, which has 3,470 more quads than the
29,283,283-quad artifact named in the older hypothesis. The recorded 13.83 GiB
pySHACL acceptance result also applies to `2026-08-13b`. The manifest SHA-256
is `656e4cc79923398ce3f1546cc321e2c40d871bc8d0297c053ba59218877bd3db`.

| Operation | Status | Wall time | Peak RSS | Disk at stop | Work completed |
| --- | --- | ---: | ---: | ---: | --- |
| Decompress and verify 126 packs | Completed | 9.023 s | Not sampled; not an engine run | 6.160 GiB | 29,286,753 lines; every byte count, line count, and SHA-256 matched the manifest |
| Jena 6.2.0 `tdb2.tdbloader`, `-Xmx6g` | Safety-stopped, exit 143 | 96.657 s | 12,038.5 MiB sampled; 12,039.0 MiB end maximum | 9.157 GiB, incomplete | Read all tuples; completed the first index replay; reached 20,000,000 of 29,286,753 entries in the second replay |
| pySHACL on the same full distribution | Recorded prior measurement; not rerun | 1,098.77 s for all 13 acceptance gates | 13.83 GiB | Not applicable | Completed and passed acceptance |

The TDB2 load ran as the direct Java main class under literal `timeout 600`,
with a 6 GiB maximum heap and a separate 11 GiB RSS abort threshold. It did not
reach the timeout. The memory guard terminated the process group at 96.657
seconds.

The loader log gives the exact progress:

1. It read all 126 files and 29,286,753 tuples in 53.47 seconds.
2. It completed the `GSPO -> GPOS, GOSP` replay over all 29,286,753 items in
   24.0 seconds.
3. It started the `GSPO -> SPOG, POSG, OSPG` replay and logged 20,000,000 of
   29,286,753 items, or 68.29%, before the safety stop.

The store lacked a complete second replay and was not valid input for
validation. Its 9.157 GiB size is a post-stop `du` measurement, not a projected
finished size.

Raw evidence:

- [pack preparation receipt](measurements/fullscale-pack-preparation.json)
- [load measurement and complete five-second trajectory](measurements/tdb2-full-load.json)
- [loader progress log](measurements/tdb2-full-load.stderr.txt)
- [loader stdout](measurements/tdb2-full-load.stdout.txt)
- [incomplete store-size receipt](measurements/tdb2-full-load-store-size.txt)

## RSS trajectory

The table contains every sample. The load had three visible periods: tuple
ingestion through 53.47 seconds, the first full index replay through about 80
seconds, and the incomplete second replay after that.

| Elapsed seconds | RSS MiB | Physical footprint MiB | Observed work |
| ---: | ---: | ---: | --- |
| 0.016 | 17.0 | 3.8 | JVM starting |
| 5.075 | 1,953.6 | 1,804.7 | Tuple ingestion |
| 10.046 | 2,188.1 | 1,910.8 | Tuple ingestion |
| 15.074 | 2,860.6 | 2,389.4 | Tuple ingestion |
| 20.075 | 3,191.7 | 2,513.5 | Tuple ingestion |
| 25.060 | 3,319.5 | 2,529.8 | Tuple ingestion |
| 30.056 | 3,565.6 | 2,653.6 | Tuple ingestion |
| 35.040 | 3,746.8 | 2,679.9 | Tuple ingestion |
| 40.032 | 3,887.7 | 2,695.1 | Tuple ingestion |
| 45.047 | 4,147.8 | 2,728.2 | Tuple ingestion |
| 50.021 | 4,331.2 | 2,728.9 | Tuple ingestion |
| 55.057 | 4,508.4 | 2,766.2 | All 29,286,753 tuples read |
| 60.056 | 4,661.7 | 2,351.8 | First index replay |
| 65.028 | 6,097.7 | 3,073.7 | First index replay |
| 70.069 | 5,979.8 | 2,324.2 | First index replay |
| 75.074 | 6,563.6 | 2,312.6 | First index replay |
| 80.041 | 7,287.1 | 2,353.6 | First replay complete; second replay starting |
| 85.033 | 9,783.6 | 3,524.3 | Second index replay |
| 90.060 | 10,626.3 | 3,121.5 | Second index replay |
| 95.059 | 12,038.5 | 3,434.1 | Second replay incomplete; safety stop |

The physical-footprint column shows that macOS charged the process for much
less than its 12 GiB resident set. The difference is consistent with resident
file mappings from the large TDB2 index files; it is an interpretation, not a
separate allocation measurement. The requested metric is RSS, and the staging
survey used the same resident-set semantics. Reclaimable mappings therefore do
not make this a flat RSS curve.

System-wide counters changed by 472 swap-ins (7.375 MiB), zero swap-outs, and
687 page-outs (10.734 MiB) during the 96.657-second run. These counters include
the other work on the shared machine, so they cannot be assigned to TDB2. The
small amount of page activity prevents treating 12,038.5 MiB as a precision
benchmark; it remains a conservative lower bound. Memory-pressure reporting
stayed at 69% free before the run and 68% after it.

## Crossover analysis

No valid crossover was measured.

| Scale and phase | pySHACL peak | TopBraid/TDB2 peak | Evidence |
| --- | ---: | ---: | --- |
| 1,013,723-quads staging, full validation path | 598.5 MiB | 1,134.0 MiB | Prior measured results; TDB2 was 1.89 times pySHACL |
| 29,286,753-quads full scale | 13.83 GiB | At least 11.756 GiB | pySHACL completed acceptance; TDB2 load stopped with incomplete indexes |

The input grew 28.89 times from staging to full scale. TDB2's observed peak grew
at least 10.62 times, even though the full run never reached validation or a
finished store. That growth falsifies the proposed flat native-store curve.

At the stop, TDB2 RSS was 85.0% of pySHACL's recorded full acceptance peak.
That numerical ordering is not a crossover: it compares an aborted load-only
lower bound with a completed load-and-validation peak. The completed TDB2 load
peak and validation peak remain unknown and could not be measured under the
12 GiB ceiling. I did not extrapolate either value because the index-replay
trajectory was nonlinear.

The pySHACL figures are prior measured peaks. The explanation that about 371
bytes per quad comes from Python index-container overhead is based on the
measured staging composition. Applying that composition to full scale is an
explanation or extrapolation, not a separate full-scale parse-only measurement.
No extrapolated number determines this report's verdict.

## Validation and the combination pathology

Full-scale TopBraid validation did not run, so this study did not reproduce or
clear the known `SkosXlLabelShape` combination pathology under TopBraid.

The load step settled the memory question and left an incomplete TDB2 database.
Opening that database for validation would not test the requested input. A
second load configured to use enough memory to finish would risk crossing the
12 GiB cap and adding swap pressure. The staging result remains unchanged:
TopBraid did not reproduce the combination pathology at 1,013,723 quads. The
full-scale TopBraid pathology result is **not tested**, not a pass.

## Measurement method and limits

The managed shell denied `ps -o rss=` even for a direct child with `Operation
not permitted`. The harness therefore sampled macOS's public
`proc_pid_rusage(..., RUSAGE_INFO_V0)` `ri_resident_size` field on the engine
process every five seconds. That field reports resident bytes directly. The
same run's end maximum was 12,039.0 MiB, 0.5 MiB above the largest periodic
sample.

The harness recorded the logical and executed commands, process identifier,
five-second samples, stdout and stderr digests, end resource use, and system
virtual-memory counters in the raw JSON. It also enforced two independent
limits: GNU `timeout 600` and an 11 GiB sampled-RSS stop. Because RSS jumped
1,412.2 MiB between the last two samples, the stop landed at 12,038.5 MiB but
remained below 12 GiB.

This study used the digest-verified Temurin 21.0.12+8 and Apache Jena 6.2.0 from
the existing Jena spike. It used the prior survey's verified TopBraid SHACL
1.5.0 classes and the unmodified
`bindings/atlas/3.1/shapes/atlas.shacl.ttl` (SHA-256
`af85315e9f6918d166ed24a0cef6d98820c4430c936178842382a3a1279c1abf`).
The TopBraid validator adapter was compiled but never executed because the load
did not produce a valid database.

## What did not run

- TopBraid validation did not run because the full TDB2 database was incomplete
  and rebuilding it safely was not possible under the measured RSS trajectory.
- The combination-shape probe did not run at full scale for the same reason.
- Intermediate 3M, 8M, and 15M loads did not run. The full load already showed
  that RSS grows with index construction, and partial-scale points could not
  turn the incomplete full result into a bounded one.
- Jena's in-memory model did not run because the owner prohibited it and it
  would threaten the shared machine.
- pySHACL did not run because the same artifact already has a measured 13.83 GiB
  acceptance result, above this study's 12 GiB ceiling.
- The roughly 25-minute full build did not run.

All decompressed packs, compiled classes, and the incomplete TDB2 store stayed
under this worktree's ignored `build/engine-fullscale/` directory. The study
read the specified distribution and reference worktrees without writing to
them.

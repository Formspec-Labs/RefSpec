# Re-survey samples, drawn 2026-08-24 on rebuild #11 (receipt ca8d7912…)

The 2026-08-22 recipe, unchanged: frame `parse_status IN ('ok','partial',
'corroborated')`; sample A = the distinct authority texts ordered by DuckDB
`hash(authority_text || 'saltA')`, first 150; sample B = the frame's rows
ordered by `hash(rin||publication_id||ordinal||citation_ordinal||'saltB')`,
first 150 (resolving to 140 distinct texts, each carrying its in-sample row
weight). Same engine (DuckDB 1.5.0), so the same ordering: re-running the
draw against the 2026-08-22 as-measured parquet reproduces that survey's
sampleA.json and sampleB.json exactly (checked before drawing today's).
Today's frame is 780,582 rows / 41,063 texts (was 776,470 / 40,389); 149 of
150 A units and all 140 B units recur, so the two surveys are effectively
paired. Each unit carries every citation the current artifact emits for the
text plus today's evidence columns (verdicts, corrections, note witness,
act resolution, roster, join) so an adjudicator can say whether a defect is
loud or silent. Halves `_1`/`_2` go to independent reviewers, as before.

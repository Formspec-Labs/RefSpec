# Adjudication tallies

Four reviewers, one rubric, no reviewer saw another's batch. Verdict vocabulary:
`CORRECT`, `MISREAD_GRAMMAR`, `MISREAD_LAUNDERED`, `DROPPED`, `UNKNOWN`.

| batch | sample | unit | n | CORRECT | MISREAD_* | DROPPED | UNKNOWN | rate |
|---|---|---|---:|---:|---:|---:|---:|---:|
| B_1 | per-row | rows | 70 | 64 | 4 | 2 | 0 | 8.6% |
| B_2 | per-row | rows | 70 | 63 | 7 | 0 | 0 | 10.0% |
| A_1 | per-text | texts | 75 | 63 | 12 | 0 | 0 | 16.0% |
| A_2 | per-text | texts | 75 | 65 | 9 | 1 | 0 | 13.3% |

Pooled:

| estimator | strict misread | + dropped | 95% CI (Wilson, strict) |
|---|---|---|---|
| per row (B_1+B_2) | 11/150 = **7.3%** | 13/150 = 8.7% | [4.1%, 12.7%] |
| per distinct text (A_1+A_2) | 21/150 = **14.0%** | 22/150 = 14.7% | [9.3%, 20.5%] |

## What is NOT here

**The full per-item verdict tables were never written to disk.** All four
reviewers returned their 300 item-level verdicts as agent messages, which were
read, tallied, and used to compute the rates above — but no file was produced.
Only the tallies (this file) and the non-`CORRECT` items are recoverable.

- Sample B's 13 non-`CORRECT` items are recorded verbatim, with index and
  reason, in `adjudication-sample-b-flagged.tsv`.
- **Sample A's 22 non-`CORRECT` items were not recorded at item-index level.**
  The specimens named in the report's "What the samples caught" table are drawn
  from the reviewers' prose and are reliable as *specimens*; they are not a
  complete or index-aligned list, and are not reproduced here as one, because
  writing down a list I cannot verify item-by-item would be exactly the guess
  this campaign's doctrine forbids.
- The rates above are reproducible from the tallies, which are certain. The
  per-item audit trail for the ~267 `CORRECT` verdicts is lost. **Re-running
  the audit would require re-adjudicating the samples**, which are preserved
  verbatim in `samples/` with the drawing script, so the frame is exactly
  reconstructible even though the verdicts are not.

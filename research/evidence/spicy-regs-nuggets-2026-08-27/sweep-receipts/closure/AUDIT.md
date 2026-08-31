# Independent closure audit

Date: 2026-08-27

## Verdict

Pass. Every materially distinct finding in reports 01 through 12 has one row
in the 272-row combined ledger. All written preservation references and exact
repository anchors resolve.

The first audit found four ledger defects: the complete-snapshot designation
and 366-day query bound were implicit rather than stated; one producer-evidence
row used descriptive output names instead of paths; one dataset row used a
descriptive research-script phrase; and one graph-evidence row pointed to the
wrong repository. The rows were corrected and the focused re-audit passed.

## Checks

- 272 unique findings, each with exactly eight tab-separated fields.
- Dispositions: 180 `copy`, 47 `durable-current-reference`, 8 `reproducible`,
  and 37 `superseded`.
- The combined ledger exactly matches the three range ledgers.
- Every `copy` preservation reference resolves.
- Every non-copy row has a durable evidence anchor.
- The two source tarballs exactly match their named Git trees: 930 of 930 files
  for SpicyRegs and 890 of 890 files for landing, with no byte differences.
- The Git bundle contains both named local heads and the pre-strip snapshot ref
  and reports complete history.
- The complete SpicyRegs output copy matches 21,635 regular files and
  23,135,060,429 bytes; the landing copy matches 26 regular files and
  9,298,482,522 bytes; the RefSpec-linked copy contains all seven target files.
- The three output SHA-256 manifests and the archive-surface `SHA256SUMS` file
  verify.

This audit proves preservation and traceability. It does not approve adoption,
prove future parity, authorize publication, or retire any current reader or
service.

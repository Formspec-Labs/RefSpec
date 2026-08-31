# Sweep closure ledger

This ledger closes the preservation question for every materially distinct
finding in reports 01 through 12. It does not accept every finding as current
architecture or authorize adoption.

`dispositions.tsv` is the combined machine-readable ledger. Its 272 findings
have exactly one preservation disposition:

Relative paths in `preservation_evidence` resolve from the archive-surface
directory containing this `closure/` directory.

| disposition | count | meaning |
| --- | ---: | --- |
| `copy` | 180 | The reviewed bytes are in a source snapshot, the complete output copy, or both. |
| `durable-current-reference` | 47 | The behavior or evidence survives at the exact active-repository commit and path recorded in the row. |
| `reproducible` | 8 | Current owners can recreate the behavior from preserved inputs; the listed verification remains future work, not a preservation blocker. |
| `superseded` | 37 | Current decisions or stronger implementations replace the old behavior; the row records the evidence and any narrow retained gap. |

The three range files retain the independent section reviews used to build the
combined ledger. All 273 lines in `dispositions.tsv` have eight tab-separated
fields, and finding IDs are unique. [`AUDIT.md`](AUDIT.md) records the initial
defects, corrections, and passing independent re-audit.

## Physical preservation

- `../source-snapshots/` contains complete tracked-tree exports for the two
  reviewed heads and a verified Git bundle containing both local heads and the
  pre-strip snapshot ref.
- `../../../../_preserved-2026-08-27/spicy-regs-output-complete/` contains
  all 21,635 regular files and 23,135,060,429 bytes from ignored
  `spicy-regs/output/`, with a full SHA-256 manifest.
- `../../../../_preserved-2026-08-27/landing-output/` contains all 26
  regular files and 9,298,482,522 bytes from ignored landing output, also with
  a full manifest.
- `../../../../_preserved-2026-08-27/refspec-linked-output/` contains the
  seven files behind the two RefSpec output symlinks.
- `../raw/` and `../reports/` retain the complete agent traces and the readable
  analyses behind each disposition.

Both large output trees matched their sources under checksum-based dry-run
comparison after copying. Source-snapshot hashes and bundle verification are
recorded in `../source-snapshots/README.md`.

## Boundary

Preservation is complete when this ledger and its referenced bytes verify.
Behavioral adoption, parity tests, package publication, deployment, and legacy
retirement remain separate decisions. The `future_verification` column records
those later checks without turning them into archive-copy blockers.

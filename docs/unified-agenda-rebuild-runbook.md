<!-- markdownlint-disable MD013 -->

# Rebuilding the Unified Agenda artifact after a producer module moves

Written 2026-09-03 because the path from "a producer module changed" to "the
provenance test is green" existed only in one session's head. It is procedure,
not law; REF-067 in [the decision ledger](decisions.md) is the decision this
serves.

## When you need this

`tests/test_unified_agenda_parquet.py::test_the_receipt_names_the_code_that_wrote_it`
is RED with a message naming one or more `modules/…`. That is the check
working: you edited a module whose bytes are hashed into the receipt, so the
artifact on disk was written by different code than the code now in the tree.

**Do not re-pin to make it green.** The receipt is the input to the pins, never
the other way round. Rebuild, then re-pin from the resulting delta.

## Establish the starting state first

```
.venv/bin/python -m refspec.registry.unified_agenda_parquet --verify
```

This builds nothing and is safe to run at any time. Two outcomes matter:

- `PASS … matches its receipt` plus `NOTE  the artifact was written by other
  code or oracles than these: modules/…` — **the tables are intact and only
  the producer block is stale.** This is the ordinary case after a code
  change, and it is where this repository stood on 2026-09-03 at `ae8f90c5`.
- Any `FAIL` line — the tables themselves disagree with the receipt. Stop.
  That is a different problem and this runbook is not it.

## The rebuild

```
.venv/bin/python -m refspec.registry.unified_agenda_parquet
```

Writing is the default; there is no `--write` flag. It reads the 61 pinned
editions under `output/registry-real-data-sources/unified-agenda-editions`
(981 MB) and rewrites the four tables plus `receipt.json` into
`output/registry-real-data-sources/unified-agenda-parquet` (14 MB). Every
input is authenticated and no path is guessed; `--source-root`,
`--output-root` and `--act-index` exist but the defaults are the pinned ones.

**Duration: 2m32s**, measured 2026-09-03 on an Apple M4 Pro rebuilding from
`dbcd445f` (22:34:48 to 22:37:20). One measurement, not a budget — but it is
short enough to watch rather than background, which is what you should do
anyway.

**A successful rebuild leaves NOTHING to commit.** `output/` is gitignored, so
the receipt and tables never enter git; if the tables do not move, no digest
pin moves either, and `git status` is empty at the end. Do not go looking for
a diff to commit, and do not treat its absence as the rebuild having failed —
`--verify` is the check, not `git status`.

## What "done" looks like

1. `--verify` prints `PASS` **and no `NOTE`**. The absent NOTE is the point:
   it means the producer block now names the code in the tree.
2. `tests/test_unified_agenda_parquet.py` is green — 150 passed as of
   2026-09-03.
3. Only then, re-pin anything that moved, **from the receipt delta**.

## The re-pin surface

Seven test modules reference this artifact; the literal digest pins are
concentrated in three:

| File | literal `sha256:` pins |
| --- | --- |
| `tests/test_unified_agenda_parquet.py` | 32 |
| `tests/test_citation_grammar.py` | 2 |
| `tests/test_unified_agenda_loud_tier.py` | 2 |
| `test_identifier_shapes`, `test_iri_minting`, `test_act_resolution`, `test_agenda_value_diff` | 0 — they read the artifact, they do not pin its digests |

## The hazard, and it is not hypothetical

**A rebuild can change table CONTENT, not just the producer block.** The
producer modules include `identifier_shapes` and `citation_grammar`, so a
grammar change alters what the tables parse out of the same source bytes. That
is the whole reason those modules are hashed into the receipt.

Scale it before you run it — and be careful WHICH corpus you scale from. For
the 2026-09-03 segment-vocabulary change (`ae8f90c5`) the prediction was **one
value**, and the measured delta was **zero**: all four tables came back
byte-identical and only `receipt.json` moved.

The prediction was wrong, and the reason is worth more than the number. That
"one value" was measured over the **Federal Register** parquet's four pinned
columns, and then quoted as a prediction about the **Unified Agenda** tables —
a different corpus with different columns. The right prediction for these
tables was never taken, and zero is what the grammar change actually does to
them, because the five-token vocabulary is regulations.gov-shaped and these
tables carry RIN, CFR and timetable data.

So: predict from the corpus the rebuild actually writes, name that corpus when
you state the number, and treat a delta ABOVE the prediction as the finding.
A delta below it means the prediction was drawn from the wrong population,
which is a finding about the predictor rather than about the build.

**And do not regenerate partially.** On 2026-09-03 a partial regeneration of a
sibling artifact chain took the suite from 42 failures to 65: the index and
coverage were rebuilt while the descriptors and fixtures were not, and the
mismatch cascaded. If a rebuild raises the failure count, revert the whole
thing and start again rather than chasing the new failures.

## Not covered here

`make generate` is a different chain — eight steps rebuilding the Atlas model,
releases, catalog, index, coverage, descriptors, source manifest and fixtures,
with `make check-generated` as its `--check` mirror. It does not touch this
artifact, and this command does not touch those.

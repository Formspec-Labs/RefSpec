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

**Duration is unmeasured.** Nobody has timed it in this repository's records,
so budget for the input scale above rather than for a number someone
remembers. Watch it rather than backgrounding it.

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

Scale it before you run it. For the 2026-09-03 segment-vocabulary change
(`ae8f90c5`), the measured effect across the four pinned columns was **one
value** — so the expectation was a receipt refresh with a one-row content
delta, and a delta larger than that would itself have been the finding.

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

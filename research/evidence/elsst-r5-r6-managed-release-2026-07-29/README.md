# ELSST R5/R6 managed-release scale proof

## Result

RefSpec built one source-faithful, two-release ELSST history from the exact
Version 5 and Version 6 Turtle distributions. It passed the real Rulespec
validator, wrote a complete managed-release bundle, reopened that bundle
through the public reader, iterated all 308,639 indexed expressions, selected
Version 6 for candidate lookup, and excluded a deprecated Version 6 concept
from the current candidate view.

The passing run took 343.264 seconds and peaked at 2,766,995,456 bytes. The
opt-in experimental gate allows 420 seconds and 3.5 GiB. These limits are
regression alarms for the local playground, not production service-level
objectives.

The full structured result is in [evidence.json](evidence.json).

## Exact sources

| Release | SHA-256 | Bytes |
| --- | --- | ---: |
| ELSST Version 5 | `d0d2514d7535309b82cc6966ee6e2b5794cf6f390896a5175f41dff4a02e03b7` | 19,167,985 |
| ELSST Version 6 | `c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95` | 19,915,491 |

The native distributions remain canonical. The generated bundle packages
their exact bytes and checks their length and digest before parsing and again
when the bundle opens.

## Managed result

| Output | Count or digest |
| --- | --- |
| Concepts across both releases | 6,905 |
| Indexed expressions | 308,639 |
| Normalized concept labels | 176,664 |
| Normalized relations | 24,844 |
| Lifecycle participants | 6 |
| Logical expression-corpus digest | `sha256:f1692767e562c9d60573b039940e269289fa6f705b8749bc6737f3a26a1fbedf` |
| JSONL artifact digest | `sha256:6c4fa2aacb03e72fddf49369f53275a8e4abb95af5c5615ffa480df2d48540b8` |
| Bundle-manifest digest | `sha256:8dd408effe1d57109460a01a9c6620107b4662cbb95eed829ef905f3bfe8b71e` |
| Rulespec graph digest | `sha256:2bff13ca942d801136ba0723118e68c086e7216de30d3ce449d657e59d9c3572` |
| Combined receipt digest | `sha256:1a43836ffe2bc358b63218a0c111c29ee3e8b93badbe0f122bd21201140d7647` |

Both import-coverage reports passed. For every required feature, the
source-observed, parsed, and indexed assertion counts and digests agree.
Excluded and failed counts are zero. The source contains no notation or SKOS
mapping assertions, so those feature counts correctly remain zero instead of
being synthesized.

## Failures that improved the design

The scale proof found two real defects before it passed:

1. The first compact full-source attempt found 15 language and identifier
   assertions present on the Version 5 concept scheme but absent from the
   projected graph. RefSpec now preserves exact language-tagged scheme
   identifiers, and omission or tampering fails coverage.
2. The first semantically complete run passed every data assertion but
   exceeded provisional 180-second and 2.5-GiB limits. Removing a needless
   seed-to-expression index entry for non-label expressions reduced the peak
   by 211,091,456 bytes. A larger improvement requires a lazy or on-disk
   expression view; the current reader intentionally validates and retains the
   complete corpus.

These were implementation findings, not reasons to weaken source coverage or
skip the Rulespec gate.

## Authority boundary

This is a complete development candidate release, not a production
deployment or accuracy claim.

- Version 6 is selected only for `developmentOnly` candidate use.
- Deprecated history remains inspectable but cannot enter the current
  assignment candidate view.
- The real Rulespec receipt authorizes the selected local development
  decision.
- ELSST licensing and attribution are recorded, but they do not limit
  playground acquisition, indexing, or experimental lookup.
- No sealed gold, product evaluation, or accepted-output permission is
  asserted.
- The source has no native SKOS mapping assertions. Mapping behavior remains
  executable through Rulespec and RefSpec conformance fixtures, but this run
  does not invent a real mapping.

## Reproduce

The ordinary suite uses source-derived mini fixtures. Run the full opt-in gate
only when both exact native distributions are available:

```text
REFSPEC_ELSST_R5_PATH=<content-addressed ELSST_R5.ttl> \
REFSPEC_ELSST_R6_PATH=<content-addressed ELSST_R6.ttl> \
uv run pytest -q -s \
  tests/test_elsst_managed_release.py::test_opt_in_full_r5_r6_managed_release_opens_and_selects_current_r6
```

The complete bundle remains in the ignored Spicy Regs experiment output. Git
tracks only this compact evidence record and the tests that reproduce it.

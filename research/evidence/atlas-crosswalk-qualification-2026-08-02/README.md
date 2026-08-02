# Atlas crosswalk qualification run, 2026-08-02

The complete artifacts of the first real crosswalk qualification run: 365
candidates over Federal Register Thesaurus 2025 and ELSST R6, 730 provider
calls, 121 qualified `searchOnly` mappings. The analysis is in
[`docs/atlas-crosswalk-qualification-pilot.md`](../../../docs/atlas-crosswalk-qualification-pilot.md).

These files are committed because **`qualify` is not reproducible**. Everything
else in this repository can be rebuilt from pinned inputs; a provider call
cannot. Re-running would cost money, would not return the same bytes, and — if
either upstream model changes — could not return the same answers at all.
`receipts.jsonl` is the irreplaceable file: the bundle is a deterministic
function of it plus `candidates.json`, so the run survives as long as this
directory does.

| File | What it is |
|---|---|
| `concepts-source.json` | 705 Federal Register 2025 concepts projected for crosswalk use |
| `concepts-target.json` | 3,470 ELSST R6 concepts projected for crosswalk use |
| `candidates.json` | the 365-candidate pilot slice; reproducible from the two concept tables |
| `receipts.jsonl` | one row per provider call — 730 rows, request and response digests, token counts, cost, verdict |
| `crosswalk-bundle.json` | the sealed digest-pinned bundle the atlas consumes |
| `qualification-receipt.json` | run rollup: outcomes by class, verdicts by family, spend, resolved model ids |
| `spend.json` | per-family token counts and assumed cost against the hard caps |
| `models-list.json` | the live models-list responses the model ids were resolved against |

Digests, for pinning:

```
crosswalk-bundle.json  file    sha256:d95967187e804eaef8a4846237ef5d973d63ef607a4671d99c8f2a36687d8887
crosswalk-bundle.json  bundle  sha256:e099b26aaa47d489639f1c47874a6c3d3791e13c003e70c51d63e21b2eb3b25b
candidates.json                sha256:8855a3ad8b7db86d308562e8801e2985e6ed2830de29fc0925c6788fb5049a78
```

Rebuild the bundle from the receipts, with no provider calls and no cost:

```
mkdir -p /tmp/rebuild && cp concepts-*.json candidates.json receipts.jsonl /tmp/rebuild/
tools/run_atlas_qualification.py --output /tmp/rebuild bundle
```

Per the research-archive convention, machine-local absolute paths were not
recorded: each concept table names its managed-release bundle by file name and
pins it by digest, which is the identity that matters.

No credential appears in any file here. The receipts carry scrubbed headers
(`Authorization: <redacted>`) and request digests, never request bodies with
keys; a scan for every value in the dotenv file finds none of them.

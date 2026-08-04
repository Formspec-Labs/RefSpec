# Publish and inspect a vocabulary atlas

`refspec-publish-vocabulary-atlas` turns one verified atlas into a directory
that can be uploaded to any static file host or opened locally. It does not
fetch, license, or approve source vocabularies. The operator supplies the
files; the existing atlas builder verifies their managed-release pins before
this command runs.

The canonical atlas remains the two-file distribution defined by
[`bindings/atlas/1.0`](../bindings/atlas/1.0/README.md). Publication adds a
compressed download and a bounded browser view. Neither one can authorize a
mapping or change a source fact.

## What goes in?

Pass a directory containing `atlas-manifest.json` and `atlas.nq`, plus an
independent SHA-256 pin for each file. A multi-vocabulary atlas is built by
repeating `--managed-release` with `refspec-build-vocabulary-atlas`; source
acquisition is outside both commands.

## What happens?

The publisher performs the full `VocabularyAtlasAsset.open` check before it
writes anything. It then:

1. compresses the exact `atlas.nq` bytes with a deterministic gzip header;
2. selects a bounded graph view in a fixed order: qualified mapping endpoints,
   cross-release shared labels, one representative for any unseen reference
   release, and immediate hierarchy context;
3. writes a standalone HTML explorer with no remote scripts, fonts, database,
   or API calls; and
4. records every payload file, byte length, and digest in
   `publication-manifest.json`.

Equal labels remain discovery signals in the explorer. Only the atlas's
qualified `searchOnly` rows appear as mappings.

## What comes out?

The new output directory contains:

| File | Purpose |
|---|---|
| `atlas-manifest.json` | The unchanged canonical atlas manifest |
| `atlas.nq.gz` | The unchanged canonical N-Quads after decompression |
| `atlas-explorer.json` | A bounded, digest-linked browser view that other tools may reuse |
| `index.html` | The offline graph explorer with the view embedded |
| `publication-manifest.json` | Digests and byte lengths for every payload file |

The explorer supports concept search, reference-release filters, relationship
filters, pan and zoom, and an inspector that exposes exact identifiers and
visible relationships. The complete graph stays in `atlas.nq.gz`; the browser
view states its limits and never presents itself as the full dataset.

## Current multi-vocabulary MVP

Atlas `urn:ref:vocabulary-atlas:57a69e9a68a5877cb8b4e2b225153e2674b56af128a1ab9877f1787e57fb3042`
has manifest file digest
`sha256:a86ece8d75a003d1fea50ab92e0e920451ecd12b4f97eff44f0d7c51d617ea2a`
and N-Quads digest
`sha256:0cca97156192fc15e2fed8b0386f70a1ea9b313e34da12e3703adab1bd1ef58f`.
That named build combines three managed-release inputs: Federal Register
Thesaurus 2025, ELSST R6, and the ICPSR subject thesaurus. It contains 233,999
quads, 5,152 hierarchy edges, and 240 qualified `searchOnly` mappings.

Publish that exact local build with:

```sh
uv run refspec-publish-vocabulary-atlas \
  --atlas output/atlas-fr-elsst-icpsr-2026-08-03 \
  --atlas-manifest-digest sha256:a86ece8d75a003d1fea50ab92e0e920451ecd12b4f97eff44f0d7c51d617ea2a \
  --atlas-output-digest sha256:0cca97156192fc15e2fed8b0386f70a1ea9b313e34da12e3703adab1bd1ef58f \
  --title "Federal Register · ELSST · ICPSR atlas" \
  --output output/publications/refspec-atlas-mvp
```

Open `output/publications/refspec-atlas-mvp/index.html` directly, or serve the
directory for an ordinary HTTP check:

```sh
python -m http.server 8000 \
  --directory output/publications/refspec-atlas-mvp
```

## How do we check it?

The command prints the publication identifier, publication-manifest digest,
original atlas pins, selected graph counts, output directory, and explorer
path. For an independent content check:

1. verify every file against `publication-manifest.json`;
2. decompress `atlas.nq.gz` without transforming its bytes;
3. confirm the decompressed digest equals `atlas.distributionDigest`; and
4. place the decompressed file beside `atlas-manifest.json` as `atlas.nq`, then
   call `VocabularyAtlasAsset.open` with the two printed atlas pins.

The test suite performs that complete round trip. Uploading the directory,
creating a hosted release, and setting a public URL are delivery actions after
the local MVP build; this command does not choose a hosting provider.

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

The current real build combines three verified managed-release inputs:
Federal Register Thesaurus 2025, ELSST, and the ICPSR subject thesaurus. The
ELSST package contains R5 and R6, so the explorer shows four reference
releases. The atlas contains 929,327 quads, 8,513 hierarchy edges, and 121
qualified mappings.

Publish that exact local build with:

```sh
uv run refspec-publish-vocabulary-atlas \
  --atlas output/atlas-scratch/three-vocab-crosswalk \
  --atlas-manifest-digest sha256:000595091c752df132b312178ec179b4baf8a180d0abb059dd5f24b42b7c04f7 \
  --atlas-output-digest sha256:b7fcca718d4a57365a8230bb34d5b6d569888d06cb50828c72624c38ef75a897 \
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

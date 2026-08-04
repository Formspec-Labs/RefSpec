# Publish and inspect Atlas 2.0

The Atlas 2.0 publisher turns one authorized canonical atlas or closed
projection into a static directory. It preserves the source distribution and
the publication decision exactly. The added gzip download and bounded explorer
do not create concepts, mappings, evidence, or permission.

## What goes in?

Publication requires:

- a verified Atlas 2.0 distribution and its independently obtained manifest
  digest;
- a `VocabularyAtlasPublicationDecision` file and its independently obtained
  file digest; and
- for a projection, the verified canonical parent and its manifest digest.

A canonical atlas contains `atlas-manifest.json`, `atlas-scope.json`, and
`atlas.nq`. A projection contains `atlas-manifest.json` and `atlas.nq`; its
manifest pins the canonical parent and the exact projection policy.

The decision must name the exact distribution result. A projection decision
must also name the same parent and projection policy. Publication fails before
writing output if any pin or decision differs.

## What happens?

The publisher:

1. opens and fully verifies the canonical atlas or projection;
2. checks `VocabularyAtlasPublicationDecision.validate_distribution(...)`;
3. copies the exact source manifest, exact decision, and canonical scope when
   present;
4. compresses the exact N-Quads with a deterministic gzip header;
5. uses `VocabularyAtlasQueries` to make a bounded explorer view; and
6. writes a content-derived publication manifest with the digest and byte
   length of every artifact.

The explorer's closed 2.0 JSON names `conceptReleases`, `concepts`, and
`mappingAssertions` directly. It keeps release-scoped concept identity intact.
Each mapping assertion retains its semantic ring, native ring-scoped relation,
evidence classes, evidence assertion identifiers, and machine-proof
identifiers. Labels select display text only; label equality never creates
identity or a mapping.

## Publish a canonical atlas

```sh
uv run python -m refspec.atlas.publication \
  --distribution output/atlas-2.0 \
  --distribution-manifest-digest sha256:<atlas-manifest-digest> \
  --decision decisions/atlas-publication-decision.json \
  --decision-file-digest sha256:<decision-file-digest> \
  --title "RefSpec vocabulary atlas" \
  --output output/publications/refspec-atlas
```

The command prints the digest of `publication-manifest.json`. Keep that digest
outside the publication directory; it is the trust anchor for reopening the
static publication.

## Publish a projection

```sh
uv run python -m refspec.atlas.publication \
  --distribution output/atlas-subject-projection \
  --distribution-manifest-digest sha256:<projection-manifest-digest> \
  --parent output/atlas-2.0 \
  --parent-manifest-digest sha256:<parent-manifest-digest> \
  --decision decisions/subject-projection-publication-decision.json \
  --decision-file-digest sha256:<decision-file-digest> \
  --output output/publications/refspec-atlas-subject
```

The publisher detects canonical and projection manifests itself. Canonical
publication rejects parent arguments. Projection publication requires both
parent arguments.

Optional `--max-concepts`, `--max-mapping-assertions`, and repeated
`--release-label RELEASE_ID=LABEL` arguments affect only the bounded explorer.
They do not affect the authoritative distribution.

## What comes out?

Every publication contains:

| File | Purpose |
|---|---|
| `atlas-manifest.json` | Exact canonical or projection manifest |
| `atlas.nq.gz` | Deterministic gzip of the exact source N-Quads |
| `publication-decision.json` | Exact authorization decision |
| `atlas-explorer.json` | Deterministic bounded view |
| `index.html` | Dependency-free offline explorer |
| `publication-manifest.json` | Content-derived identity and exact artifact digests |

Canonical publication also contains the exact `atlas-scope.json`. Projection
publication does not copy the parent scope; it retains the exact parent pin in
the projection manifest, publication manifest, and decision.

## How do we check it?

Use the printed publication-manifest digest as the external pin:

```python
from refspec.atlas.publication import AtlasPublication

publication = AtlasPublication.open(
    "output/publications/refspec-atlas",
    expected_manifest_digest="sha256:<publication-manifest-digest>",
)
```

That file-only form verifies the closed file set, canonical JSON bytes, every
artifact digest and byte length, deterministic gzip bytes, the full Atlas 2.0
distribution, the decision result and embedded policy pins, the derived
explorer data, and the exact HTML rendering. For a projection, pass the verified
canonical parent to prove that the published bytes reproduce from it:

```python
publication = AtlasPublication.open(
    "output/publications/refspec-atlas-subject",
    expected_manifest_digest="sha256:<publication-manifest-digest>",
    parent=verified_canonical_atlas,
)
```

The parent-backed form also validates the decision against the parent's exact
scope and rebuilds the projection byte for byte. The reader opens the
publication directory and every child through descriptor-relative no-follow
operations, then verifies stable descriptor metadata and bytes twice. It
rejects symlinks, unexpected files, and changes observed while opening. On a
platform without descriptor-relative no-follow support, it fails closed instead
of falling back to path-based reads.

Open `index.html` directly, or serve the directory with any static file server.
Hosting and release remain separate delivery actions.

# Atlas 3.0 mapping evidence archive

This directory preserves the exact evidence bytes from 582 historical generated
cross-vocabulary pairs. It supports future testing, requalification, and
regeneration, but it is not an Atlas 3 production-generator input and does not
contribute RDF statements, acceptance counts, or publication authority. It does
not depend on the disposable `output/vocabulary-atlas-v1-rc1` tree.

This archive covers mapping evidence only. It does not copy the six upstream
managed/source releases. In particular, the ELSST managed release remains an
external generated input under
`output/elsst-r6-atlas2-bench-input-2026-08-04/managed-release/`; despite that
historical directory name, the generator reads `managed-release-bundle.json`
and never reads an Atlas 1.x or Atlas 2.x graph.

The archive contains three evidence chains:

- `fr-elsst`: 190 mapping assertions;
- `fr-icpsr`: 201 mapping assertions; and
- `elsst-icpsr`: 191 mapping assertions.

The total is 582. Each chain contains the unchanged Crosswalk v2 bundle, the
unchanged relation-assertion bundle, and its unchanged bundle manifest. The
relation assertions pin the Crosswalk bundle by identifier, canonical payload
digest, and file digest. `manifest.json` closes the nine-file archive with exact
paths, byte lengths, and SHA-256 digests.

`manifest.json.canonicalPayloadDigest` is SHA-256 over canonical JSON of the
manifest without `canonicalPayloadDigest` and without a terminal line feed. A
test-only seal check verifies the manifest and all nine artifacts independently
of production generation. Historical fields such as `useCeiling` remain
unchanged in these sealed source bytes; they are absent from the portable graph
and grant no Atlas 3 product permission.

These records preserve historical machine evidence. They do not authorize a
broader use ceiling or turn derived relations into editorial assertions.

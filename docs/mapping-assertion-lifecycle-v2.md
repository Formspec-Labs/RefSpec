# Mapping assertion lifecycle in relation bundles 2.0

Relation-assertion bundle 2.0 makes lifecycle and supersession facts part of
every content-derived `MappingAssertion`:

- `lifecycleStatus` uses the closed v1 vocabulary `current`.
- `supersedes` is a canonical, sorted array of prior content-derived mapping
  assertion identifiers.

An incoming `supersedes` link makes the referenced assertion effectively
`superseded` in an assembled Atlas. The referenced assertion remains unchanged
and resolvable, so history and contradictory assertions stay available. A
relation bundle validates the links it contains. The canonical Atlas validates
the complete cross-bundle graph, including reference closure, time order,
self-reference, and cycles.

Vocabulary Atlas v1 admits the narrow initial state only: every mapping must
declare `lifecycleStatus: current` and `supersedes: []`. This keeps v1 exact
while reserving content-addressed supersession links for a later Atlas.

## Migration

Relation-assertion bundle 1.0 records do not carry lifecycle facts and fail
closed at the 2.0 reader. The baseline preparation command reads each pinned
1.0 bundle, adds `current` and an empty supersession list to every mapping,
recomputes all content-derived mapping and bundle identities, verifies the
result, and writes a new `relation-assertions-v2` directory. It preserves the
original `relation-assertions` and `.pre-source-records` directories byte for
byte.

Run:

```text
uv run python tools/prepare_vocabulary_atlas_v1_baseline_release.py
uv run python tools/prepare_vocabulary_atlas_v1_baseline_release.py --check
```

The prepared release definition pins the new 2.0 manifests. Provider evidence,
qualification receipts, machine-proof pins, endpoint releases, predicates, and
the 582 admitted baseline mappings remain unchanged in meaning.

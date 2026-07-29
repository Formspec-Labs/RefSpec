# REF structural model

`ref-records.cue` is the authoritative machine-readable source for REF-owned
record structures. It uses JSON-compatible CUE: every byte after parsing is
valid JSON and valid CUE. This keeps CUE as the structural language while
making a clean checkout reproducible without downloading a CUE executable.

Run:

```text
make generate
make check-generated
```

The generator writes:

- JSON Schema 2020-12 files under `bindings/json/1.0/schemas/`;
- Python `TypedDict` interfaces under `src/refspec/generated_types.py`; and
- `generated-artifacts.json`, which binds every generated file to the exact
  model digest.

Generated files are reviewable outputs, not independent sources of meaning.
Change the CUE model, regenerate, and run the binding and package gates. The
drift gate fails when a generated file changes by hand or regeneration was
omitted.

Rulespec-owned structures do not belong in this model. REF records refer to
Rulespec identifiers, graph digests, records, and validation receipts. The
pinned Rulespec validator remains the only validator for Rulespec semantics.

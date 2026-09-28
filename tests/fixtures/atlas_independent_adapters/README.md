# Bounded independent agency fixture

`agency-registry.nq.zst` copies the mapping-only pack from the independently
compared September 27 agency distribution. It is a frozen observed artifact,
not expected truth: tests reconstruct expectations from the committed candidate,
decision and raw-roster inputs, and mutate the artifact's semantic fields.
The frozen comparison implementation remains under `tests/oracles/atlas_refresh/`.

Fast source-reading tests use the committed Poppler coordinate captures and
compare the old and new page algorithms. They need Python, not Poppler.

Run the additional retained-evidence replay explicitly:

```sh
uv run pytest -q tests/test_atlas_independent_adapters.py -m slow
```

That replay requires `pdftotext` from Poppler, the pinned PDFs and the 20
primary originals the audit-evidence manifest names (`make fetch-pinned-inputs`
places both), and the bounded agency distribution and view
(`make build-derived`). Missing inputs fail rather than skip; the tests
acquire, fabricate and rebuild nothing themselves.

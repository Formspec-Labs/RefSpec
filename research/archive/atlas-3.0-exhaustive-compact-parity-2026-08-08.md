# Atlas 3.0 exhaustive compact-to-RDF parity archive

**Date:** 2026-08-08

**Status:** Archived implementation history; nonnormative

Atlas 3.0 previously reconstructed every compact record from RDF and compared
the complete compact and RDF representations. That check duplicated work over
millions of records and contributed to a 74-minute full-distribution validation
run.

Commit `cdf368e` replaced exhaustive parity with three bounded checks:

- authenticate every compact pack and logical row;
- reconcile exact role and record counts; and
- compare a deterministic sample of at most five records per pack with RDF.

The last implementation before that change is pinned locally at:

```text
refs/archive/atlas-3.0-exhaustive-compact-parity/2026-08-08
55e9e1332d014957f20fec5eaae8929699d24670
```

Inspect the archived implementation without copying it back into the active
binding:

```sh
git show \
  refs/archive/atlas-3.0-exhaustive-compact-parity/2026-08-08:bindings/atlas/3.0/tools/validate.py
```

The archived code centered on `_check_compact_dependency_closure`,
`_check_compact_rdf_parity`, and
`_validate_semantics_then_compact_parity`. Git preserves the implementation;
the repository does not carry a second runnable copy.

## Current boundary

The archive retires exhaustive compact-to-RDF parity only. The independent RDF
validator remains the Atlas 3 release verdict because the fast Parquet
preflight does not run normative SHACL, RDF lexical and graph checks, node
digest reconstruction, projection and derived replay, source-accounting
reconciliation, transitive SKOS conflict analysis, or reasoning isolation.

The archive ref is local. A default push does not publish it.

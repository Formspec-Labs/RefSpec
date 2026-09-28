# Atlas refresh, 2026-09-27

The refresh started from RefSpec dev21 (`41e2bf9d`, SpicyDocs 0.46.0) and
revisits the [August acceptance findings](../acceptance-gate-blind-spots-2026-08-21.md)
against current code and the pinned publisher inputs. It found one binding
defect, three source-fidelity verifier defects, four construction units with
no independent comparison, and a full build that stopped at its memory guard.
The [repair proposal](../../plans/atlas-refresh-repair-plan-2026-09-27.md)
answers each finding. Nothing in this lane was published.

The investigation ran on `lane/atlas-refresh-20260927` (a Codex session); its
commits were rewritten into this history. Its raw logs and receipts were not
kept: the owner kept only the evidence files a check reads (decision of
2026-09-28). Figures below are the lane's recorded measurements.

## Label policy and source evidence

REF-037 and the binding README allow one preferred label per language. The
resource shape instead imposed one preferred label in total. The pinned UMTHES
archive `output/registry-real-data-sources/umthes-gemet-endpoints-2026-08-15.zip`
(SHA-256 `978b10cd1e3f2f8729372a86f2afa1b62d2790e4810c6d57af5343835259d25f`)
contains the counterexample in `records/_00000013.nt`.

Its subject `https://sns.uba.de/umthes/_00000013` is a SKOS concept in the
UMTHES scheme, with `"Abbau"@de` and `"degradation"@en` explicitly marked as
preferred labels. The surrounding triples mark `"Abbaumechanismus"@de` and
`"decomposition"@en` as alternatives and link broader concepts `_00047435`
and `_00049270`. The two preferred labels belong to the same concept; they
are neither alternatives nor labels of a parent.

The shape now uses `sh:uniqueLang` over preferred literal forms. The linear
label-integrity check counts label identities before deduplicating literal
values, so distinct label nodes carrying identical preferred text in one
language still fail. `tests/test_atlas_v3_preferred_languages.py` keeps the
old cardinality clause as a test-only oracle; its mutation table freezes the
intended difference (distinct languages change from refusal to acceptance;
duplicate languages, including identical literals on distinct label nodes,
stay refused). A complete UMTHES-only distribution then passed the standalone
validator (manifest `474328e2a2d2bcbbcb2c00861afc18831c215c06ec82b826700b79c845838e02`,
262,530 quads).

## Source-fidelity defects

The UMTHES fidelity run failed. Labels, identities and admitted relations
agreed with publisher bytes; three verifier defects did not:

- The declaration check rejected the grouped
  `lc-external-target-endpoints-2026-08-15` comparison for owning several
  construction units, and the eCFR and Regulations.gov agency rosters'
  `publisher-key` identity policy. Splitting the LC declaration alone would
  have reused one vocabulary's cached publisher subset for the next, because
  its reader was not in `SPEC_SCOPED_RECORD_READERS`: separately, AGROVOC and
  Getty select their own records; together, the split reused AGROVOC's records
  for Getty.
- UMTHES provenance compared two digest meanings. `_add_source_record` writes
  the digest of the canonical `nativePayload`, which the binding validator
  verifies; the verifier expected the raw archive-member digest. On source
  record `urn:ref:atlas-source-record:000e6359baff727a9e55e40b8c8f9a4415e901c9dd60e211ae529b73df9b0f08`
  (publisher concept `_00028834`) the stored and independently hashed payload
  digests are both `b2f45f92...be4eaba8`, while the raw member hashes to
  `3c81b1fe...1bf8974`, the retained `responseDigest`. The verifier refused
  3,415 records for that reason alone; an independent archive-to-artifact
  comparison found no discrepancy in payloads, hashes or record identities.
- Relation provenance missed altered evidence: mutating a relation's
  `responseDigest` or transformation reason and recomputing its hashes added
  no failure; mutating the relation object was caught.

Four construction units had no independent comparison:
`agency-registry-2026-09-26`, `ferc-docket-prefixes`,
`ferc-document-class-types` and `unified-agenda-legal-authority-citation-types`.
Bounded probes reproduced the digest-meaning mismatch beyond UMTHES (Federal
Register API topics, GCMD, GovInfo collections, GAO topics, EuroVoc-to-MeSH
evidence); BILLSTATUS bill types showed that a missing policy flag does not by
itself prove a mismatch.

## Omitted vocabulary units and the agency registry

An independent PDF extraction matched every docket-prefix record and the
selected Unified Agenda citation types. The FERC class/type table has one
explicit exception: the rendered page and the emitted row end in
`Hinshaw Pipe`, while Poppler's text layer also carries `lines`. Full-page and
high-resolution renders confirm the emitted reading; appending the word would
also change the derived resource identity.

An independent agency comparison matched events, result rows, identity
bridges, recorded non-emissions, selected roster names and parents and the
owner decisions, with their evidence bindings and hashes; deliberate
corruptions were caught. The reviewer retrieved and hashed the 20 cited
primary records and read the relevant rendered PDF pages. Order dates are not relabeled as effective
dates, and a statutory rename does not settle the owner's identity-versus-
succession judgment. An independent re-implementation of the documented
digest rules reproduced every item, event and decision digest.

## Full build

The full build ran 18:54:43Z–20:36:38Z and exited 143 at its 18 GiB
process-tree RSS guard (last sampled peak 20,499,008 KiB) during
`derive-registered-relations`, after every source and mapping release was
constructed. RSS understated demand on macOS: the builder's physical
footprint, including compressed and swapped pages, was 31.45 GiB at 20:35:50Z,
beside a separately owned full-Atlas test worker. A one-second native sample
put every main-thread sample in `gc.collect()`: `_stream_construct_graphs`
collected the whole tracked heap after every release while retaining all
source and mapping releases, which repeats work over the retained population
once per release.

## Repairs and their measurements

Each finding (F1-F14 in the proposal) landed as its own commit after
`9855dff5`: source-fidelity verifier 16, bounded accounting and sorting, the
phase guard and qualification target, the explorer's candidate publication
checks, and the audit refactor. Their bodies state what changed and why. The
lane's figures, from receipts it produced and this history does not keep:

- The repaired full build completed in 8,562.7 s, peaking at 8.79 GiB
  physical footprint and 10.05 GiB RSS against 18 GiB guards, with about
  74 GiB of build disk. The phase that failed before now takes about 108 s.
  Its largest pack is about 0.94 GiB and the aggregate about 23.3 GiB,
  inside the 4 GiB and 32 GiB limits.
- Reconstruction with identical inputs reproduced both the old and the new
  Federal Register topic release identities, attributing the change to the
  shared reader's parser version alone; the two repartitioned mapping units
  sort to byte-identical RDF (79.5 s comparison).
- Accounting at 4x the probe's records and releases: all digests equal, 962
  retained expected-graph triples instead of 15,362, 92-93 MB footprint
  instead of 114-116 MB. These are accounting-only probes.
- Qualification of that candidate stopped in the standalone audit at the
  30 GiB footprint guard (30.10 GiB, about 26 minutes) after 120 packs, at
  least 54,014,188 of 100,916,862 quads. The validator keeps every pack in
  one two-index dataset, `O(T + U + I)` in statements, payload bytes and
  identities; this is a capacity stop, not a verdict.
- The columnar preflight passed on the full candidate in 14.23 s (2.35 GiB
  peak footprint); the sampled RDF/Parquet comparison, which cost about 33
  minutes of that run as one scan per sampled subject, now scans once
  (0.082 s instead of 0.381 s on 50,000 lines and 45 subjects).

The lane also installed a candidate wheel into DocSpec and SpicySearch and
passed their adoption checks. This branch does not change the package
version: it sits on dev22 as released, and the merged source needs a version
of its own before consumers adopt it.

## Retained evidence and what reads it

The owner kept only the evidence a check reads (2026-09-28); the other 200
files of the lane's evidence tree were not carried over.

| File under `independent/` | Read by |
| --- | --- |
| `omitted-vocabularies/receipts/class-bbox.html`, `docket-bbox.html`, `ua-glossary.txt` | `tests/test_atlas_independent_adapters.py::test_pdf_frozen_oracle_and_explicit_reading_divergence` (fast): Poppler coordinate captures for the old and new page algorithms |
| `omitted-vocabularies/receipts/artifact-observed.json` | `test_pdf_real_exact_artifact_population_and_fields` (slow): the emitted rows the positioned-PDF reader must reproduce |
| `provenance/relation-specimen.json` | `tests/test_atlas_provenance_repair.py::test_resealed_artifact_tamper_passes_binding_but_fails_publisher` (fast) |
| `agency/audit-evidence-manifest.json` | the release job's qualification (pinned `sha256:fde4401e...`) and the agency slow tests; it names the 20 primary sources, which are pinned inputs |
| `agency/claim-receipt.json` | the release job's qualification (pinned `sha256:4b6a8e01...`) and the agency slow tests |

## Known costs and follow-ups

- The Parquet preflight issues 70 DuckDB queries on a passing view, each
  re-reading the columns it needs: bounded memory, repeated scans.
- The verifier re-hashes every `nativePayload`, which the binding validator
  already checks: `O(payload bytes)` twice per audit.
- `_requested_reachability` runs one depth-first search per start node,
  `O(s(V + E))`, where ICPSR's reader used to memoize ancestor sets.
- `_write_sorted_lines` encodes every line to measure it, one transient copy
  per line (about 25 GB at full scale).
- Derivation reads each release spool three times (facts, labels, node
  digests) to avoid holding it; mapping accounting still retains every
  expected identity, linear in mappings.
- Qualification pins the compact view to the digest of the manifest it just
  built, so `verify-compact-view` proves the view did not change between
  build and check, not that an external party agreed to it.
- Full publisher-fidelity capacity is unmeasured: no qualification reached it.

## What remains for release

- No candidate has completed qualification. The standalone audit needs more
  than the 30 GiB guard `release.yml` keeps (`--memory-gib 30`): a bounded
  validator, proved against the current one as an oracle, or a measured
  larger exclusive runner.
- `make stage-atlas-mapping-topology` exits 2 on `main` and on this branch:
  the staged build refuses assertion `1e1194...` with
  `dataset.assertion-identity`.

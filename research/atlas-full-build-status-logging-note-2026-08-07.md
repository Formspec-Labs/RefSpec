# Atlas full-build status logging record

Status reporting is implemented in `tools/generate_atlas_v3_full.py` and the
independent `bindings/atlas/3.0/tools/validate.py` consumer. Both commands now
write elapsed time and coarse phase changes to standard error by default. The
builder also reports completed and total release counts. The validator reports
RDF-pack and compact-pack progress. `--quiet` disables these lines.

The implementation reports only logical release keys and distribution-relative
pack paths. It does not add status data to canonical JSON, released receipts,
digests, or standard output. Phase lines are immediate. Repeated progress lines
are limited to one every 15 seconds, with builder checkpoints every 25,000
resources and validator checkpoints after each authenticated compact pack.

## Overhead evidence

On 2026-08-07, real full-input `--check-inputs` runs produced identical standard
output with status enabled and disabled:

- status enabled: 100.956 seconds and 8 standard-error lines;
- `--quiet`: 101.405 seconds and no standard-error lines.

A five-million-iteration checkpoint benchmark measured about 12.7 nanoseconds
per builder resource. At the current 588,409-resource build size, the builder
checkpoint calculation adds about 0.008 seconds. The measured difference is too
small to justify another costly cold full build solely for logging. The
existing builder and binding tests cover cold, incremental, and exact-reuse
behavior, and 252 focused tests passed after fixture regeneration.

On 2026-08-08, exhaustive compact-to-RDF row parity was replaced with full
compact shape and size validation plus a deterministic sample of up to five RDF
comparisons per compact pack. Validator status now follows those bounded pack
checks rather than reporting exhaustive record comparisons.

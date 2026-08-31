# Hand attestations

**Opened 2026-08-31 with one row.**

An attestation is a claim that two spellings name one thing, signed by someone
who looked at the bytes. Nothing here runs. Nothing here is imported. This is an
evidence home, and the rows in `attestations.jsonl` are its founding corpus.

## What a row asserts

That a value written one way and a value written another way denote the same
real object — here, one Federal Register document — and that a named, durable attester identity — a person, or an agent
session with its operator named —
reached that conclusion by reading witnesses that are saved in this directory
alongside the claim.

A row carries its own uncertainty. `strength` says, field by field, which parts
of the assertion were *witnessed* and which were *inferred*, and the inferred
ones must show their reasoning. A row that asserts uniformly and confidently is
a row that has not been read carefully.

## What a row never does

**It never rewrites source data.** The fused spelling `E5-2394Filed` keeps its
lossless identity: it is what the Federal Register stores, what GovInfo names
its granule, and — as the founding row discovered — what the printed page says.
An attestation adds a reading path; it does not edit the record. Where the two
spellings differ in reachability, the row says so in `direction`, and
`direction.reverse_substitution` is the field that stops a well-meaning
normaliser from turning a fetchable identifier into a dead one.

**It never generalises.** See below.

## The witness-required rule

No row without witnesses, and no witness that is not in this directory.

A witness is bytes: a file under `witnesses/`, its source URL, its sha256, and
the exact string it shows. If a claim cannot be tied to bytes a reader can
re-hash, the claim does not go in the row — it goes in `notes`, marked as
reasoning rather than observation. The founding row's causal account of *how*
the defect happened lives in `notes` for exactly this reason: it is the best
explanation of the witnesses, not a thing anyone saw.

Two disciplines the founding row had to learn the hard way:

- **Count derivations, not copies.** The fused token appears in the print page,
  in GovInfo's granule id, and in the Federal Register API. That is one defect
  observed once and inherited twice, not three independent confirmations. A
  witness list is a list of *sources*; the row's prose must say when several of
  them share an origin.
- **A derived artifact is not a witness.** `colophon-comparison-600dpi.png` is
  in the witness list for the convenience of the next human, flagged as
  carrying no information its parent PDF lacks. Keep such things; never let
  them raise the apparent count of evidence.

## Per value, never per pattern

Every row is about one value. `E5-2394Filed` is attested. Nothing else is.

There are other fused document numbers in the Federal Register's history, and
this row says nothing about any of them. It licenses no regex, no
`endswith("Filed")` rule, no repair pass over a corpus. The reason is visible in
the founding row: the fusion is a *per-document* composition defect — the
control colophon on the very same printed page, in the same font, has its space
intact. Whatever produced it did not apply uniformly, so no uniform rule may be
inferred from it. A second fused number needs a second row and a second reading.

This is the expensive property of the registry and the only one that makes it
worth having.

## Reopening

Every row carries `reopen_if`: the conditions under which it stops being true.
A row is not a permanent finding. Publishers correct records; a spelling that
resolves today may 404 tomorrow, and the founding row's whole `direction`
argument rests on a reachability fact that GPO could change without notice.

To reopen: re-fetch the witnesses, compare digests against
`witnesses/MANIFEST-sha256.csv`, and if the bytes moved, write a new row rather
than editing the old one. Rows are append-only. The record of what someone
believed on 2026-08-31, and on what evidence, is the point.

## Promotion

There is deliberately no module here, no reader, and no test.

Structure earns its keep by having a consumer that breaks without it. These rows
have no consumer yet, so a `hand-validation registry` module would be structure
documenting itself. When something actually needs to resolve `E5-2394` to
`E5-2394Filed` at runtime, that need brings the module, the schema check, and
the negative fixture with it — and these rows become its founding corpus,
already shaped for the purpose. Until then, evidence, correctly homed.

The row shape is deliberately UNVERSIONED and private to this evidence
home. Versioning a private format with no consumer would be structure
documenting itself, and minting a RefSpec attestation term would shadow
the platform's existing Rulespec-owned `rkaf:Attestation` (REF-023: never
mint a parallel term for a concept rkaf already defines). If promotion
ever comes, the runtime shape is rkaf's, and these rows are its evidence
inputs — not a competing schema.

## Layout

```
README.md            this ceremony statement
attestations.jsonl   the rows, one JSON object per line (read with: jq . attestations.jsonl)
witnesses/           the saved bytes
witnesses/MANIFEST-sha256.csv   digests over them
```

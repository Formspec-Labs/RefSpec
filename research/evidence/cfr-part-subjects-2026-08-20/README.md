# CFR part subjects, witnessed

**2026-08-20.** A `(CFR title, part) -> subject terms` mapping built only from
Federal Register documents that cite **exactly one** CFR part, so no attribution
is inferred.

## Why this exists, and what it is not

A parallel session measured that propagating topics through cited CFR parts
scores **F1 85.3** against an agency prior's 57.3 — and 85.3 in the
*substantive* band against 53.9. It asked for the authoritative CFR List of
Subjects to replace its inferred part-to-topic table.

**That authoritative list does not exist as a machine-readable publisher
artifact.** `src/refspec/registry/cfr_list_of_subjects.py` establishes this and
carries a drift tripwire that raises if eCFR ever exposes a subject element, so
the parser gets updated rather than silently reporting zero. The only
machine-readable source is Federal Register document JSON, which carries a
document's `topics` and its `cfr_references` side by side — and deliberately
does not say which topic belongs to which part when a document cites several.

So this artifact does not claim publisher authority for the mapping. It claims
something narrower and checkable: **for the subset of documents where the
attribution is unambiguous, the assignment is witnessed rather than inferred.**

## The construction

Include a document only when it cites exactly one CFR part. Then every one of
its topics attaches to that part with no inference step. Measured over the
labelled corpus:

| citation shape | documents | share | topic assignments | share |
|---|---:|---:|---:|---:|
| **1 part (unambiguous)** | 96,941 | **84.9%** | 447,253 | **78.3%** |
| 2–3 parts | 12,208 | 10.7% | 71,338 | 12.5% |
| 4+ parts | 5,010 | 4.4% | 52,884 | 9.3% |

The ambiguity the registry module refuses to resolve affects 15.1% of documents.
Discarding them costs 21.7% of assignments and buys a mapping with no
attribution guesswork in it at all.

## What the artifact contains

`part-subjects.csv` — 19,601 rows:

| | |
|---|---:|
| distinct CFR parts | **4,256** |
| distinct subject terms | 852 |
| CFR titles | 48 |
| witnessing documents | 445,353 |
| rows whose term resolves to an Atlas concept | **19,601 / 19,601** |
| publication range | 2000-01-18 → 2026-07-23 |

Columns: `cfr_title`, `cfr_part`, `topic`, `atlas_concept`, `witness_documents`,
`first_witnessed`, `last_witnessed`.

Two properties requested by the consumer and both held:

- **Part-level granularity is preserved.** Title-level would collapse the entire
  signal — the effect is that `42 CFR 416` means something specific.
- **Terms are concept identities, not only strings.** Every row carries the
  `federal-register-api-topics` concept IRI its term resolves to. Zero rows fail
  to resolve, which is expected: the topics *are* that scheme's vocabulary.

`witness_documents` is the count of single-part documents that attached this
term to this part, and `first_witnessed`/`last_witnessed` bound when. A
consumer wanting precision over coverage should threshold on
`witness_documents`; a term witnessed once on a part from 2003 is weaker
evidence than one witnessed 400 times across two decades.

## Honest limits

- **It is Federal Register evidence, not a CFR publisher assertion.** It records
  what agencies filed, aggregated. A part whose rules were never amended in this
  window is absent, and 4,256 parts is not all of the CFR.
- **It is not time-sliced.** A term witnessed in 2003 and never since is carried
  the same as a current one, distinguishable only through the date columns. A
  part's subjects genuinely change as it is amended.
- **The 84.9% subset is not a random sample of the CFR.** Documents amending one
  part skew toward routine single-part actions; complex rulemakings citing many
  parts are exactly the ones excluded, so the parts they touch are
  under-represented here.
- **This does not license the multi-part case.** The remaining 15.1% still has no
  warranted attribution, and nothing here should be read as a method for
  supplying one.

## Reproduction

Built by grouping single-part Federal Register documents from
`spicy-regs/output/rulespec-stabilization-candidate-final/federal_register.parquet`
(1,004,233 documents, 114,220 labelled) and joining terms to the
`federal-register-api-topics` scheme of the sealed 2026-08-20 Atlas search view.

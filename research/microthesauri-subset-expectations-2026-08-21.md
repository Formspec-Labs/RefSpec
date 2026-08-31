# The microthesauri unit: what an inverse-shaped subset broke

**Date:** 2026-08-21
**Scope:** `eurovoc-microthesauri-4.24` in `tools/verify_atlas_source_fidelity.py`

EuroVoc's 127 microthesauri are the only construction unit whose resources
are *schemes*. Every other vocabulary unit holds concepts that belong to a
scheme; this one holds the schemes themselves, and its concepts live in
`eurovoc-4.24`. Four independent verifier expectations had quietly encoded
"a unit holds concepts", and all four broke at once when the unit landed.

None was a data defect. Across every failing run the records, the graph,
the labels, and the notations were sound — `rdf-provenance-fidelity`,
`concept-traceability`, `identifier-retention`, and `notation-fidelity`
passed throughout, on the same bytes that produced hundreds of failures
elsewhere. That pattern is the finding: **the failures described the
checks, not the artifact.**

## What each expectation assumed

| expectation | assumed | true for this unit |
|---|---|---|
| member-IRI claims | the Atlas types a resource as the publisher does | publisher says `ConceptScheme`, Atlas says `Concept` of its own microthesauri scheme |
| scheme identity | a publisher scheme is recognisable by an explicit `ConceptScheme` typing | the typing is inverted, so no publisher scheme was recognised at all |
| scheme metadata | claims on a scheme subject are claims *about* that publisher scheme | the Atlas's own `skos:inScheme` linking each mt to its minted scheme leaked in as an added publisher claim |
| label floor | a real run compares at least 200 labels | a bounded unit exposes 127, and comparing all 127 with zero mismatches is exhaustive, not thin |

## The fixes, and why they are not waivers

A spec now declares `member_type_inverse`: the (Atlas type, publisher type)
pair its unit reverses. The microthesauri spec already said "a microthesaurus
is a scheme" in a comment; the declaration makes that statement executable,
and the reversal is applied to exactly the declared pair. Recognition stays
fail-closed by intersecting with the publisher's own schemes, so a spec
cannot declare its way into recognising a scheme the publisher never
published.

Governed-scheme membership is representation structure, keyed on the
subject's own `atlas:inScheme` — the Atlas naming the scheme it governs a
resource under. Membership in a *publisher* scheme stays compared. The first
attempt keyed on the wrong set (`skos_schemes`, which holds only subjects
typed inside the source pack, while the minted scheme is typed in the
catalog) and silently failed to match; the scoped run against real bytes
caught it.

The label floor became the lesser of the configured sample and what the
scoped pairs expose, never below one. Its own test had asserted "inspected
few" rather than the "inspected nothing" the guard exists for — so the test
passed for the wrong reason and would have kept passing had the floor been
deleted outright. Both properties now have tests.

## Measured result

Scoped against `atlas-3.1-full-2026-08-21c` and the pinned publisher bytes:
**24 of 26 checks pass.** The two failures are `distribution-coverage`
(126 units scoped out — the check correctly refusing to treat a scoped run
as whole-corpus proof) and `configuration` (three acquisition-era specs
using an identity policy the allowed set does not list, plus one release-key
arity mismatch) — pre-existing module debt, unrelated to this unit.

## Open, and needing an owner's decision

`eurovoc-domains` and `eurovoc-main` have a *genuine* representation gap,
verified empirically rather than inferred: the Atlas asserts nothing at
`<http://eurovoc.europa.eu/domains>`, and its minted scheme carries neither
that IRI nor the publisher's `"Eurovoc domains"@en` label. The publisher's
scheme self-description is unrepresented — one subject for domains, 128 for
main. No verifier expectation can honestly close this; it needs either a
producer anchor (the minted scheme asserting `atlas:representsResource`
back to the publisher IRI, plus the retained label, which a declared inverse
could then reverse) or an explicit decision that grouping-scheme
self-description sits outside the Atlas model.

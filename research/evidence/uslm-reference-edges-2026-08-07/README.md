<!-- markdownlint-disable MD013 -->

# USLM statutory reference edges — OLRC release point 119/102

Extraction of every citation the Office of the Law Revision Counsel marked up in
the USLM XML edition of the United States Code: 58 published titles, appendices
included, at release point `119/102`.

Producer: [`tools/extract_uslm_reference_edges.py`](../../../tools/extract_uslm_reference_edges.py).
Tests: [`tests/test_extract_uslm_reference_edges.py`](../../../tests/test_extract_uslm_reference_edges.py).

`manifest.json` is the committed record. It pins every input zip by URL, byte
length and SHA-256, every output file by digest, and the corpus counts. The
edge JSONL itself is **not committed** — it is 431 MB and is written to the
git-ignored `output/`. The manifest is sufficient to check a later run against
this one without either extraction being in the tree.

## Reproducing

```sh
uv run python tools/extract_uslm_reference_edges.py \
  --cache output/uslm-cache \
  --output output/uslm-reference-edges-2026-08-07 \
  --claims-output output/uslm-reference-claims-2026-08-07 \
  --evidence-manifest research/evidence/uslm-reference-edges-2026-08-07/manifest.json
```

Roughly 25 seconds of parsing over a warm cache, plus the download on a cold
one. Every digest is re-derived from the cached bytes, so a hand-edited cache
cannot pass itself off as the publisher's payload.

## What was extracted

| Unit | Count |
| --- | --- |
| Occurrence rows emitted | 1,342,167 |
| — with no source anchor (state no claim) | 2,641 |
| — redundant repeats of a claim already counted | 146,636 |
| **Distinct claims** | **1,192,890** |
| **Section-to-section references made by enacted text** | **87,586** |

By citator: `enactingPublicLaw` 611,771 · `statutesAtLarge` 340,040 ·
`uscCrossReference` 330,508 · `actName` 59,848.
By context: `note` 871,613 · `sourceCredit` 299,642 · `operative` 106,886 ·
`toc` 64,026. Only 8.0% of emitted rows sit in operative enacted text.

Title 26 reproduces the prior validation table to the digit: `/us/pl` 73,243 ·
`/us/stat` 26,590 · `/us/usc` 17,604 · `/us/act` 1,908.

## Decision: the deduplication policy

**An emitted row is a markup occurrence; a claim is `(title, sourceAnchor,
edgeType, href, context)`.** Stated in `ASSERTION_KEY`, applied in `dedupe()`,
reported in the manifest. Three parts of it were decisions, each measured
against the full corpus before being taken.

**`context` stays in the key.** This is the consequential one. Dropping it
yields 1,170,595 keys against 1,192,890 with it — **22,295 `(anchor, href,
type)` triples that the publisher marked up in two different kinds of text**.
Those are precisely the pairs where a citation appears once in enacted text and
once in an editorial note. A context-free key merges them, which reintroduces at
the assertion layer exactly the amendment-versus-reference conflation the
`context` field exists to prevent. **Filter on context first, deduplicate within
it, never the reverse.**

**A null `sourceAnchor` states no claim.** 2,641 rows (0.20%) sit in a repealed
or transferred unit that kept its `id` but lost its `identifier`, so there is no
subject endpoint to hang an edge on. They are retained in the JSONL as evidence
and excluded from the claim population, counted rather than dropped. Note 1,422
of them are in `operative` context, so this is not a rounding error confined to
notes.

**`noteTopic`, `element`, `sourceUnit` and `targetResolved` are not in the key.**
They are properties of the occurrence or of the target, not of the claim:
whether the publisher rendered a reference as `<ref>` or `<a>` does not make it a
different reference.

The 105,742 exact-duplicate JSON rows are a subset of the 146,636 redundant
occurrences and are reported separately, because a byte-identical repeat and a
repeat differing only in an off-key field are different kinds of evidence about
the publisher's markup.

## What this does and does not license

These edges are **asserted, not derived**. Nothing here recognises citations —
OLRC already did, in the course of producing an official edict of the US
government, and every row is a transcription of an editorial decision. A tool
that ran a citation *recogniser* over the same text would be replacing a curated
answer with a guess, and that tool's output would be derived. This one's is not.

`edgeType` names **the citator the publisher used**. It is not a legal predicate
and it does not establish an edge direction. Establishing those is a separate
question, and the honest answer differs per type:

| Edge type | Direction of the markup | Direction of the legal relation |
| --- | --- | --- |
| `uscCrossReference` | citing provision → cited provision | same — recoverable |
| `actName` | citing provision → named act | same — recoverable |
| `enactingPublicLaw` | section → public law | **inverted**: the law amends the section |
| `statutesAtLarge` | section → Statutes page | **inverted**, and the same event as the `/us/pl` edge beside it |

For the two inverted types the publisher's markup direction is the *reverse* of
the legal relation, and inverting it is an editorial act OLRC did not perform.
That inversion is available but must be asserted by someone, not assumed here.

Do not use this extraction for: a single pooled "cross-references" total; an
amendment count (a `/us/pl` and a `/us/stat` edge routinely describe one
amendment twice); an assumption that every `/us/usc` target resolves; or a
corpus-wide markup-completeness claim. Markup density is a **per-title**
property — Title 42 marks up 83% of operative references, Title 26 only 8.7% —
so Title 26's intra-title network is genuinely absent while Title 42's is largely
present. Check `uscByContext` per title before relying on either.

## Integration status against Atlas 3.0

The `legalIdentity` ring currently holds 3,747 resources and **zero same-ring
relations** (re-derived from
`output/atlas-3.0-full-2026-08-06/distribution/atlas-construction-summary.json`;
the 3,732 figure in the 2026-08-06 takeaways is stale by one release). It is
empty of relations because no source adapter supplies any — **not** because
anything blocks them.

**Resolved — these edges are asserted facts and need no binding change.** The
producer check's "zero inferred mappings, projections, derived relations, and
supersession" is enforced at `tools/generate_atlas_v3_full.py:4025-4030` and
touches only `graphs.projection`, `graphs.derived`, and `atlas:supersedes`. It
never inspects asserted relation types, and the same build already emits 553,540
`atlas:NativeRelationAssertion` records through that path. Per the binding, an
`atlas:NativeRelationAssertion` "preserves a publisher-authored relation between
resources in the same semantic ring" whose endpoints "may belong to one release
or to different releases" — which REF-014 added for exactly this shape. A
marked-up `<ref href>` qualifies.

**Resolved — the predicate constants in `semantic_foundation.py` are the wrong
vocabulary.** `LEGAL_CITES` / `LEGAL_AMENDS` / `LEGAL_AUTHORIZES` /
`LEGAL_IMPLEMENTS` are `urn:ref:relation:legal-identity:*` URNs gating
`MappingAssertion`, `EvidenceAssertion` and `MachineEvidenceProof` — never
`NativeRelationAssertion`, which does not appear in that module at all. They have
**zero production references**. The binding's normative policy is a disjoint
vocabulary in `bindings/atlas/3.0/registry-resource-profiles.json`, which admits
exactly two legalIdentity native predicates: `atlas:relatedLegalIdentity` and
`atlas:versionOf`. Of the four edge types only `uscCrossReference` maps honestly
onto `relatedLegalIdentity`; the three provenance types have no admissible
predicate and would need one added to that digest-pinned file.

**Blocked — the US Code is not a catalogued source.** The catalog's `uslm` row
is the *markup schema*: `resourceKind: structuralSchema`, `consumability:
inventoryOnly`, `memberDisposition: noPublisherRecord`, locator
`github.com/usgpo/uslm`. The Code corpus itself — the 58 titles of statutory text
at `uscode.house.gov` — has no catalog row at all. A `NativeRelationAssertion`
requires both endpoints to be `atlas:LegalIdentityResource` members of exact
`atlas:AtlasRelease`s, and no USC release exists. Under REF-013 an atlas row
"cannot claim release readiness or enter a build until it names a conforming,
complete release." Admitting USC is an owner decision, not an implementation
step. See the report accompanying this evidence for what that decision requires.

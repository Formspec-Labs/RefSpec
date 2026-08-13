# Definition fidelity decision package

**Decision owner:** product owner  
**Research date:** 2026-08-13  
**Measured artifact:** `/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13`  
**Decision status:** advice only; no builder, auditor, binding, or release was changed

## Advice

Choose **CARRY** for usable English `skos:definition` and `skos:scopeNote`
content. The implementation is small because the Atlas wire, compact records,
full Parquet view, and search view already have definition and note fields. The
measured addition is 1,885 quads, 235,961 bytes of publisher text, about 81.7 KB
of independently compressed N-Quads, and about 79.0 KB in the existing Parquet
columns. EuroVoc accounts for all but one of those quads.

Do not treat that English carry as closure of the full 43,837-claim EuroVoc
finding. The commonly quoted number is not only definitions and scope notes: it
contains 30,621 `skos:definition`, 8,233 `skos:scopeNote`, and 4,983
`skos:historyNote` claims across all publisher languages. The proposed
English-only change represents 1,557 definition claims and 327 scope-note claims
from EuroVoc. It leaves 41,953 EuroVoc claims outside the wire. The owner must
separately choose whether the English-only Atlas declares those multilingual and
history-note claims out of scope or evolves to carry their language and role.

If forced to choose one side of the stated binary, the arithmetic favors
**CARRY**. A declaration is not a configuration-only alternative: the current
`DeclaredClaimExclusion` can exclude entity layers, but it cannot exclude
selected predicates on concepts the auditor already compares. Honest
declaration therefore requires auditor code, tests, and documentation while
delivering less downstream value.

## What was measured

The prototype uses the eight vocabulary `SourceSpec` entries in the auditor's
`SOURCES`, not an independently invented source list
([`tools/verify_atlas_source_fidelity.py:3186-3627`](tools/verify_atlas_source_fidelity.py#L3186-L3627)).
It authenticates the declared publisher pins, applies the auditor's exact source
subsets, reads the source-owned Atlas packs named by the construction summary,
and compares unique RDF claims by subject and literal. The complete method,
input digests, pack digests, and measurements are in
[`prototype-measurements.json`](prototype-measurements.json); the reproducible
program is [`prototype_measurements.py`](prototype_measurements.py).

“Publisher semantic claims” below means the unique IRI-subject, literal-object
and IRI-object triples retained by each selected auditor view. Blank-node claims
are not in that denominator. “Carried” requires an exact subject-and-literal
match in `atlas:definition` or `atlas:note`; it does not infer equivalence from
similar text. This follows the repository's stated source-fidelity boundary:
the release seal proves internally consistent artifact bytes, while the fidelity
auditor compares those bytes with the publisher inputs and fails in both
directions ([`README.md:82-98`](README.md#L82-L98)).

### Full eight-source landscape

| Audit source | `definition` | `scopeNote` | `note` | `example` | `historyNote` | `editorialNote` | `rdfs:comment` | Atlas definitions | Atlas notes | Listed claims not carried |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| eurovoc | 30,621 | 8,233 | 0 | 0 | 4,983 | 0 | 0 | 0 | 0 | 43,837 |
| elsst | 9,107 | 1,708 | 0 | 0 | 4,056 | 0 | 0 | 903 | 1,004 | 13,097 |
| gemet | 46,361 | 362 | 0 | 0 | 0 | 774 | 0 | 5,134 | 3,653 | 42,135 |
| agrovoc | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| nasa-thesaurus | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| osti | 1,638 | 152 | 0 | 0 | 0 | 0 | 0 | 1,638 | 152 | 0 |
| eurovoc-domains | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| nalt | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| **Total** | **87,729** | **10,455** | **0** | **0** | **9,039** | **774** | **0** | **7,675** | **4,809** | **99,071** |

The source columns count all publisher languages. Atlas 3.1 is English-only and
keeps multilingual publisher text external behind an exact locator and digest
([`bindings/atlas/3.1/README.md:161-166`](bindings/atlas/3.1/README.md#L161-L166),
[`bindings/atlas/3.1/README.md:379-403`](bindings/atlas/3.1/README.md#L379-L403)).
That is why ELSST and GEMET have large all-language differences even though
their usable English definitions and scope notes are already present.

Two source-specific facts prevent the zero rows from becoming misleading:

- NASA publishes 9,656 `zthes:termNote` marker claims outside the seven
  requested predicates. The actual text lives on detached `zthes:label`
  resources whose relative identifiers do not join to the reified note
  identifiers. The reader deliberately refuses to invent that association
  ([`src/refspec/registry/nasa_thesaurus.py:1-23`](src/refspec/registry/nasa_thesaurus.py#L1-L23),
  [`src/refspec/registry/nasa_thesaurus.py:186-226`](src/refspec/registry/nasa_thesaurus.py#L186-L226)).
  NASA therefore has a separate publisher-model problem; it does not have
  standard-SKOS annotation claims in this measurement.
- NALT's two `skos:definition` claims point to publisher definition-node IRIs
  rather than literals. One selected node has an English `rdf:value`; the other
  has no text value. The reader preserves this indirection
  ([`src/refspec/registry/nalt_core.py:68-75`](src/refspec/registry/nalt_core.py#L68-L75)).
  The carry estimate resolves one usable English definition and leaves the
  textless claim explicit.

GEMET also has 4,547 source-citation claims under its own `gemet:source`
predicate. Its adapter flattens English source citations and other note kinds
into `atlas:note`, which explains why the Atlas note total is larger than the
exact carry count for the seven predicates. Four publisher English definitions
are empty strings; the emitter correctly adds no empty definition quad.

## Price of CARRY

### Measured wire and serving growth

| Increment | EuroVoc | NALT | Total |
| --- | ---: | ---: | ---: |
| Usable English publisher definition claims | 1,557 | 1 | 1,558 |
| Usable English publisher scope-note claims | 327 | 0 | 327 |
| New `atlas:definition` quads | 1,555 | 1 | 1,556 |
| New `atlas:note` quads | 329 | 0 | 329 |
| New wire quads | 1,884 | 1 | 1,885 |
| Publisher text, UTF-8 bytes | 235,738 | 223 | 235,961 |
| Canonical N-Quads bytes | 460,581 | 347 | 460,928 |
| N-Quads compressed separately at Zstandard level 19 | 81,410 | 251 | 81,661 |
| Estimated existing Parquet definition/notes column growth | 77,919 | 1,079 | 78,998 |

EuroVoc has two concepts with two English definitions. The compact format allows
at most one definition, so the prototype follows the existing adapter rule:
the first sorted definition becomes `atlas:definition`, and the two additional
definitions become `atlas:note`
([`tools/generate_atlas_v3_full.py:5282-5289`](tools/generate_atlas_v3_full.py#L5282-L5289)).
That is why 1,557 definition claims become 1,555 definition quads and two extra
note quads.

The EuroVoc addition is 0.220% of its current 856,733 quads. Compressing only
the new lines produces 81,410 bytes, 0.792% of its current 10,274,241-byte pack.
This is an estimate of rebuild growth, not a promise of the final byte delta:
the pack must be sorted and recompressed as a whole. The Parquet estimate uses
the search view's actual string/list types, 50,000-row groups, Zstandard level
19, and no dictionary encoding for these columns. Per-file footer overhead makes
the one-row NALT estimate conservative.

### Code and validation work

No new public RDF term or Parquet column is needed:

- The ontology already defines `atlas:definition` and `atlas:note`
  ([`bindings/atlas/3.1/ontology/atlas.ttl:750-763`](bindings/atlas/3.1/ontology/atlas.ttl#L750-L763)).
- The SHACL shapes already admit both properties on schemes and resources
  ([`bindings/atlas/3.1/shapes/atlas.shacl.ttl:263-266`](bindings/atlas/3.1/shapes/atlas.shacl.ttl#L263-L266),
  [`bindings/atlas/3.1/shapes/atlas.shacl.ttl:284-329`](bindings/atlas/3.1/shapes/atlas.shacl.ttl#L284-L329)).
- `RegistryResource` already exposes `definition` and `notes`, and the generator
  already emits non-empty English literals
  ([`src/refspec/atlas/v3_source_data.py:180-193`](src/refspec/atlas/v3_source_data.py#L180-L193),
  [`tools/generate_atlas_v3_full.py:4387-4397`](tools/generate_atlas_v3_full.py#L4387-L4397)).
- Both the full Resource table and the compact search Resource table already
  contain `definition` and `notes`
  ([`src/refspec/atlas/parquet_tables.py:69-83`](src/refspec/atlas/parquet_tables.py#L69-L83),
  [`src/refspec/atlas/parquet_search_view.py:110-124`](src/refspec/atlas/parquet_search_view.py#L110-L124)).

The work sits at the adapter boundary:

| Source | Current behavior | CARRY work |
| --- | --- | --- |
| OSTI | Carries the first English definition and English scope notes. | None; all 1,790 usable definition/scope claims match. |
| ELSST | Carries the first English definition and flattens other English note roles into `atlas:note`. | None for definition/scope; all 1,086 usable claims match. |
| GEMET | Carries non-empty English definitions and flattens English note/source roles into `atlas:note`. | None for definition/scope; all 5,236 non-empty usable claims match. Keep the four empty source definitions explicit in audit results. |
| EuroVoc | Builds resources from labels, notation, and IRI fields; it does not select annotations. | Add English literal-selection rules for definition and scope note to the claim-release path and the parser-backed fallback. Preserve the one-definition rule and deterministic ordering. |
| NALT | Preserves the definition-node indirection in parsed source data but does not populate the wire fields. | Resolve English `rdf:value` only when the publisher link and target are exact. Use the pinned source to verify the target and `dcterms:source`; refuse or report a link with no value. Preserving those fields in `nativePayload` is an optional, wider provenance change. |
| AGROVOC | Keeps parsed notes in `nativePayload`, not in the common wire fields. | No change for the bounded audit sample because it has no requested annotation claims. Apply the same mapping if a larger admitted release contains them. |
| NASA | Marks detached annotations as not joined and populates neither common field. | No standard-SKOS work. Any proprietary-note carry requires a publisher-supported join or a separately governed derivation; string-matching identifiers is not source fidelity. |
| EuroVoc domains | Populates neither field. | No change; the 21-domain scope has no requested annotation claims. |

The asymmetry is in current code, not in the schema. OSTI, ELSST, and GEMET
select English note rows and assign `RegistryResource.definition` and `.notes`
([`src/refspec/atlas/v3_registry_vocabularies.py:411-451`](src/refspec/atlas/v3_registry_vocabularies.py#L411-L451),
[`src/refspec/atlas/v3_registry_vocabularies.py:489-550`](src/refspec/atlas/v3_registry_vocabularies.py#L489-L550),
[`src/refspec/atlas/v3_registry_vocabularies.py:1050-1111`](src/refspec/atlas/v3_registry_vocabularies.py#L1050-L1111)).
EuroVoc's parser-backed resources omit those fields
([`src/refspec/atlas/v3_registry_vocabularies.py:587-674`](src/refspec/atlas/v3_registry_vocabularies.py#L587-L674));
its declarative claim rules have selectors only for labels, notation, and native
IRIs, and the generic converter never assigns definition or notes
([`src/refspec/atlas/registry_claim_input.py:77-89`](src/refspec/atlas/registry_claim_input.py#L77-L89),
[`src/refspec/atlas/registry_claim_input.py:171-220`](src/refspec/atlas/registry_claim_input.py#L171-L220)).
Both EuroVoc routes must change together so build inputs cannot choose different
fidelity.

The change should add running checks that fail on a removed definition, a wrong
language, a scope note emitted as a definition, a second definition emitted
against the compact cardinality rule, an empty text value, and an unresolved
NALT target. The independent auditor must compare the new values in both
directions. This satisfies the repository rule that new structure arrives with
the validator or consumer that breaks when it is violated.

### Re-mint blast radius

Publisher concept IRIs do not change. Definition and note facts do enter the
resource node digest: `rdf_node_digest` hashes the sorted outgoing facts
([`bindings/atlas/3.1/tools/validate.py:1682-1685`](bindings/atlas/3.1/tools/validate.py#L1682-L1685)),
and the compact Resource record recomputes that value from the graph
([`tools/generate_atlas_v3_full.py:5221-5234`](tools/generate_atlas_v3_full.py#L5221-L5234)).
Therefore the affected full-Parquet `Resource.content_digest` values change.
The canonical source packs, their pack digests and quad counts, construction
keys, manifest/distribution identity, receipts, full Parquet members, compact
search view, and seal must all be rebuilt.

The minimal EuroVoc change and a source-pin-verified NALT flattening do **not**
need to change `SourceRecord.nativePayload`, so source-record IRIs and their
source-assignment evidence can remain stable. If the implementation instead
adds source predicate roles, the NALT target and attribution, or annotation text
to the native payload, the source-record constructor includes that payload
digest in the source-record IRI basis
([`tools/generate_atlas_v3_full.py:2571-2606`](tools/generate_atlas_v3_full.py#L2571-L2606)).
That wider design would re-mint source records and downstream assignment
evidence. Add it only with a consumer and negative fixture that need the role;
the generic `atlas:note` carry does not require it.

## Price of DECLARE

### The current mechanism cannot express this decision

`DeclaredClaimExclusion` selects whole publisher subjects by `rdf:type` or IRI
prefix and reports every selected claim by predicate. It is fail-closed only
while Atlas asserts nothing about those subjects
([`tools/verify_atlas_source_fidelity.py:761-803`](tools/verify_atlas_source_fidelity.py#L761-L803),
[`tools/verify_atlas_source_fidelity.py:6995-7054`](tools/verify_atlas_source_fidelity.py#L6995-L7054)).
EuroVoc annotation subjects are the same concepts whose labels, membership, and
relations the auditor compares. The overlap guard expressly refuses to exclude
them ([`tools/verify_atlas_source_fidelity.py:6922-6992`](tools/verify_atlas_source_fidelity.py#L6922-L6992)).

DECLARE therefore requires a predicate-scoped claim-family declaration, not a
new `DeclaredClaimExclusion` row. It must:

1. select exact source predicates within an exact `SourceSpec` scope;
2. report publisher claim counts by predicate and language policy;
3. name the corresponding Atlas predicate or declared absence;
4. permit other Atlas claims on the same concepts;
5. fail if an excluded claim starts appearing on the Atlas side, if the count
   changes without review, or if an undeclared predicate remains; and
6. include negative fixtures for those three failure modes.

Without that change, a declaration would either hide all EuroVoc concept claims
or fail the existing overlap check. Neither is an honest implementation.

### Counts an honest declaration would record

The table below is the predicate-level residue after exact Atlas carry, across
the seven requested predicates:

| Source | `definition` | `scopeNote` | `historyNote` | `editorialNote` | Total declared away |
| --- | ---: | ---: | ---: | ---: | ---: |
| eurovoc | 30,621 | 8,233 | 4,983 | 0 | 43,837 |
| elsst | 8,204 | 1,525 | 3,368 | 0 | 13,097 |
| gemet | 41,227 | 260 | 0 | 648 | 42,135 |
| nalt | 2 | 0 | 0 | 0 | 2 |
| agrovoc, nasa-thesaurus, osti, eurovoc-domains | 0 | 0 | 0 | 0 | 0 |
| **Total** | **80,054** | **10,018** | **8,351** | **648** | **99,071** |

The decision's narrow zero-carry gap—EuroVoc plus the bounded NALT claims—is
43,839 claims. That is 8.374% of the 523,525 semantic claims in those two audit
scopes and 1.773% of the 2,472,693 semantic claims across all eight scopes.
EuroVoc alone declares away 8.375% of its selected publisher triples. If the
product declares every current listed-predicate residue across all eight
sources, the total is 99,071 claims, or 4.007% of the aggregate publisher
semantic claims.

That is the product-honesty cost. RefSpec says adapters construct a product from
the publisher's exact pinned bytes and calls the independent source-fidelity
auditor part of what makes the result trustworthy
([`README.md:3-27`](README.md#L3-L27)). Its strategy describes intended source
preservation and a stronger boundary around publisher assertions
([`ATLAS_US_EU_COMPARISON.md:38-55`](ATLAS_US_EU_COMPARISON.md#L38-L55)). A
declaration can still be honest—the binding already says the distribution is an
English normalized view—but the README, comparison, receipt, and source
accounting must say that fidelity means “represented or enumerated as omitted,”
not “publisher semantic content is present.” The public statement should include
the exact counts above and distinguish non-English content, note-role loss,
empty publisher values, unresolved resource annotations, and proprietary NASA
notes.

## Search value

REF-024 assigns vocabulary and search-view publication to RefSpec and
snapshot-specific concept tagging and search to SpicySearch
([`docs/decisions.md:1105-1119`](docs/decisions.md#L1105-L1119)). Carrying
definitions makes useful concept text available to SpicySearch without a
RefSpec search-view schema change: `Resource.definition` and `Resource.notes`
are already present and survive the compacting transform
([`src/refspec/atlas/parquet_search_view.py:110-124`](src/refspec/atlas/parquet_search_view.py#L110-L124),
[`src/refspec/atlas/parquet_search_view.py:239-245`](src/refspec/atlas/parquet_search_view.py#L239-L245)).
The measured payload cost is about 79 KB in those existing columns. The benefit
is potential, not automatic. At SpicySearch commit `f147ffba3fde`, the semantic
lane embeds document `searchSegment` records, while concept retrieval resolves
queries against Atlas and searches snapshot-local topic tags
(`/Users/mikewolfd/Work/spicysearch/PLAN.md:12-22` and `:153-160`). The current
`VocabularyLookup` reads only Resource identity fields and Label rows, and its
policy explicitly says expansion is not used
(`/Users/mikewolfd/Work/spicysearch/src/spicysearch/vocabulary_lookup.py:19-38`
and `:185-252`). Definitions would let a future, quality-gated concept resolver
embed or otherwise match concept descriptions, improving differently worded
queries without altering publisher facts. That downstream feature requires a
SpicySearch snapshot-policy and evaluation change; carrying the column does not
silently activate it.

## Verification and limits

Run the prototype with:

```sh
/Users/mikewolfd/Work/spicy-regs/RefSpec/.venv/bin/python \
  prototype_measurements.py \
  --source-root /Users/mikewolfd/Work/spicy-regs/RefSpec/output/registry-real-data-sources \
  --distribution /Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-13 \
  --output prototype-measurements.json
```

The final run passed Ruff and completed at **4,499,832,832 bytes (4.191 GiB)
peak resident memory**, below the 6 GiB limit. The program processes one source
at a time and records the observed limit result in the JSON. It only read the
main repository's `output/` artifacts; all generated files are in this disposable
worktree.

The byte prices cover English definition and scope-note additions only. They do
not price a multilingual wire, a predicate-role extension, a safe NASA
annotation join, or the normal release-wide cost of rebuilding and resealing.
No full Atlas build was produced, so the compressed pack figure and the
definition/notes-only Parquet delta remain measured estimates rather than final
release sizes.

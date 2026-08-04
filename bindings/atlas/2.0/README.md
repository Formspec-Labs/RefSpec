# RefSpec Vocabulary Atlas Distribution 2.0

This binding defines the portable file boundary for
`refspec-vocabulary-atlas-nquads-2.0`. It publishes one exact, four-ring atlas
scope as lossless JSON records in a deterministic N-Quads dataset. A Python
publisher may implement this binding, but Python is not part of the consumer
interface.

This is one closed 2.0 boundary. Producers and consumers MUST reject another
`format`, manifest `schemaVersion`, scope `schemaVersion`, graph role, or
missing required pin. They MUST NOT infer omitted fields or translate another
atlas shape while claiming conformance to this binding.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

## Distribution

A distribution contains exactly three regular files and no symlinks:

| File | Media type | Purpose |
| --- | --- | --- |
| `atlas-scope.json` | `application/vnd.refspec.vocabulary-atlas-scope+json` | Exact index, concept-release, and relation-bundle scope |
| `atlas.nq` | `application/n-quads` | Canonical records and their exact-equality index |
| `atlas-manifest.json` | `application/json` | Distribution identity, file pins, policies, counts, and ring summaries |

`atlas-scope.json` MUST validate against
[`schemas/vocabulary-atlas-scope.schema.json`](schemas/vocabulary-atlas-scope.schema.json).
`atlas-manifest.json` MUST validate against
[`schemas/vocabulary-atlas-manifest.schema.json`](schemas/vocabulary-atlas-manifest.schema.json).
Both schemas are closed: a producer or consumer MUST reject unknown fields.

A distributor MUST provide a trusted, independent
`sha256:<64 lowercase hex>` digest for `atlas-manifest.json`. The manifest
then pins the exact scope and N-Quads files by path, media type, SHA-256 digest,
and byte length. A consumer MUST verify these file pins before using any atlas
record.

## Canonical JSON and distribution identity

The two JSON files use canonical REF JSON. They MUST be UTF-8, contain no
duplicate object keys, `null`, or floating-point values, and use integers only
in the inclusive range -9,007,199,254,740,991 through
9,007,199,254,740,991. Object keys use ascending Unicode code-point order;
arrays retain their declared order. The encoding uses compact `,` and `:`
separators, emits Unicode directly without normalization, and ends with one LF.

The manifest's `canonicalPayloadDigest` is SHA-256 over the canonical JSON
object with `canonicalPayloadDigest` removed and without a terminal LF.
`generationDigest` is SHA-256 over canonical JSON containing exactly these
fields, without a terminal LF:

```json
{
  "format": "refspec-vocabulary-atlas-nquads-2.0",
  "implementation": {},
  "policies": {},
  "scope": {}
}
```

The values in that basis MUST equal the complete corresponding manifest
values. The atlas identifier MUST be
`urn:ref:vocabulary-atlas:<generationDigest hex>`.

`implementation.sourceModules` identifies the producer's exact generator
artifacts; its rows MUST be unique and ordered by `path`. `runtime` records
exact producer-defined component versions. Consumers MUST verify the closed
shape and digests, but MUST NOT require RefSpec module paths, Python, or any
particular runtime key.

The manifest policies have one allowed value each:

- `graphPartition`: `releaseFactsAndCrossReleaseRecords`
- `recordEncoding`: `canonicalRefJsonV1`
- `recordIndexing`: `derivedExactEqualityV1`
- `labelEquality`: `discoveryOnly`
- `permission`: `externalProductPolicyOnly`

## Exact atlas scope

The scope uses `VocabularyAtlasScope` schema version `1.0`. Its
`contentDigest` is SHA-256 over the canonical REF JSON encoding, including its
terminal LF, of exactly `type`, `schemaVersion`, `scopeName`, `scopeKind`,
`atlasIndex`, `releases`, and `relationBundles`. Its identifier MUST be
`urn:ref:vocabulary-atlas-scope:<contentDigest hex>`. The manifest scope
descriptor combines the exact scope pin with its distribution file descriptor.
Its `role` MUST be `VocabularyAtlasScope`; its `id` and `contentDigest` MUST
equal the fields in `atlas-scope.json`; and its `fileDigest` MUST cover the
complete scope file bytes. Its `path`, `mediaType`, and `byteLength` identify
those same bytes.

`scopeKind` is either `bench` or `product`. It describes the intended build
context and grants no permission.

`atlasIndex` pins one exact index identity, content digest, and file digest.
Every release row MUST contain every matching index row as a non-empty
`atlasIndexRows` array of exact `{rowId,rowDigest}` references. Releases MUST
be ordered by `(semanticRing, releaseId)`; each release's index references MUST
be ordered by `rowId`; relation bundles MUST be ordered by `id`. All
identifiers in each array MUST be unique. An index row MUST occur in exactly
one release row.

A producer MUST resolve every index-row reference against the pinned index and
verify all of these conditions:

1. The index row names the same `releaseId`, `manifestDigest`, and
   `semanticRing` as the exact release pin.
2. All index rows for that release agree on semantic ring, subject
   participation, source module, and resource identifier.
3. The scope includes every index row for that release; a producer cannot
   select only a convenient classification.
4. Each relation bundle uses releases already pinned in the scope, with exact
   pin equality after removing `atlasIndexRows`.

The scope never copies `subjectParticipation` onto a release. Core,
specialist, bridge, or evidence-only participation comes only from the pinned
index rows. A subject release may have no participation class. Participation
is planning metadata, not admission or use permission.

## N-Quads byte profile

`atlas.nq` MUST:

1. be valid UTF-8 N-Quads;
2. contain no blank node and no default-graph statement;
3. use one statement per line, LF line endings, no blank lines or surrounding
   whitespace, lexicographically sorted statement lines, and one terminal LF;
4. use only the two named graph identifiers declared by the manifest; and
5. match every declared file, graph, record, ring, and total count.

The graph identifiers MUST be `<atlas id>:release-facts` and
`<atlas id>:cross-release`. The manifest lists their rows in the fixed order
`releaseFacts`, then `crossRelease`. `releaseFacts` is non-empty.
`crossRelease` MUST be non-empty when the exact scope contains a relation
bundle. It MUST have zero quads when the scope contains no relation bundle; in
that case all four cross-release counters MUST also be zero. A relation bundle
contains at least one mapping assertion and its evidence, so non-zero relation
bundle, mapping-assertion, and evidence-assertion counts rise together.

The namespace prefix `atlas:` in this binding means
`https://refspec.org/ns/vocabulary-atlas/v2#`. `rdf:` means
`http://www.w3.org/1999/02/22-rdf-syntax-ns#`.

## Lossless canonical record encoding

The N-Quads dataset preserves complete JSON records. It does not flatten a
record into a partial RDF interpretation. For each native JSON record, the
producer MUST preserve every field, JSON type, string code point, and array
position, then encode that JSON value with `canonicalRefJsonV1`:

- the canonical REF JSON value rules above apply, except that a native
  captured record's JSON `null` values remain `null` rather than being
  dropped or rewritten;
- the UTF-8 record bytes omit the JSON-file terminal LF; and
- the `rdf:JSON` lexical value is exactly those UTF-8 bytes decoded as text.

The record digest is SHA-256 over those record bytes. Its record IRI MUST be
`urn:ref:vocabulary-atlas-record:<record digest hex>`. Each record node MUST
have exactly one value for each of these statements in its declared graph:

- `rdf:type atlas:CanonicalRecord`;
- `atlas:recordRole atlas:<role>`;
- `atlas:recordDigest "sha256:<64 lowercase hex>"`; and
- `atlas:canonicalJson "<canonical JSON>"^^rdf:JSON`.

If the native record has an absolute-IRI `id`, or an absolute-IRI JSON-LD
`@id` when `id` is absent, the node MUST also have exactly one
`atlas:recordId <native-id>` statement. A record carrying both MUST use the
same IRI in each field or the producer MUST reject it. A record with neither
form MUST omit `atlas:recordId`. A contained release record MUST have one
`atlas:inRelease <release-id>` statement for every exact release that contains
it. A contained cross-release record MUST likewise have one
`atlas:inRelationBundle <bundle-id>` statement for every exact relation bundle
that contains it. The top-level concept-release and relation-bundle records do
not point to themselves.

The allowed roles and graph placement are closed:

| Graph | `atlas:recordRole` | Manifest counter |
| --- | --- | --- |
| `releaseFacts` | `atlas:conceptRelease` | `conceptReleases` |
| `releaseFacts` | `atlas:concept` | `concepts` |
| `releaseFacts` | `atlas:releaseRecord` | `releaseRecords` |
| `crossRelease` | `atlas:relationBundle` | `relationBundles` |
| `crossRelease` | `atlas:evidenceAssertion` | `evidenceAssertions` |
| `crossRelease` | `atlas:mappingAssertion` | `mappingAssertions` |
| `crossRelease` | `atlas:machineProof` | `machineProofs` |

`releaseRecords` counts only `atlas:releaseRecord` nodes. It does not count
`atlas:conceptRelease` or `atlas:concept` nodes again. All seven manifest
counters count distinct record nodes in their named role. Graph `quadCount`
values count N-Quads statements, and `output.quadCount` MUST equal the sum of
the two graph counts.

An identical canonical record appearing in more than one exact container uses
one record node with all exact containment statements. A producer MAY
deduplicate only records with the same record IRI and byte-identical canonical
JSON. The producer MUST reject one record IRI associated with different JSON.

## Derived exact-equality index

`canonicalJson` is authoritative. `rdf:type`, `recordRole`, `recordDigest`,
`recordId`, `inRelease`, and `inRelationBundle` form the complete
`derivedExactEqualityV1` index. A producer MUST regenerate this index exactly
from the canonical records and their pinned containers. It MUST NOT add other
predicates to either named graph under this policy.

Derivation uses exact, case-sensitive JSON equality. It performs no Unicode,
label, whitespace, identifier, date, or numeric normalization and makes no RDF
or vocabulary inference. In particular, equal labels can support discovery,
but they never create concept identity, a mapping assertion, or an entity
link. Consumers MAY build search, graph, columnar, or semantic indexes from
the records. Those indexes are disposable views and MUST NOT replace or alter
the canonical records.

## Four rings and ring-specific meaning

Every concept release and relation bundle belongs to exactly one of four
semantic rings:

- `subject` describes topics. SKOS match relations compare meaning and never
  assert identity.
- `entity` describes organizations, people, places, and other named things.
  Name equality alone never establishes entity identity.
- `value` describes governed code-list or value-set members. Crosswalk
  assertions retain source and target editions and their effective dates.
- `legalIdentity` describes stable identities and versioned links among legal
  authorities, provisions, dockets, and related legal objects.

All four rings use the same concept, release, evidence, mapping-assertion, and
lifecycle record foundation. Each ring retains its own relation vocabulary and
validation rules. A producer MUST reject a relation that is invalid for its
ring or whose endpoint releases fall outside the exact relation bundle and
scope.

The manifest's four ring summaries MUST appear in this order: `subject`,
`entity`, `value`, `legalIdentity`. Each summary counts the distinct release,
concept, relation-bundle, and mapping-assertion records in that ring. The sums
of those four fields across all ring rows MUST equal `conceptReleases`,
`concepts`, `relationBundles`, and `mappingAssertions` in `counts`. Empty rings
remain present with zero counts.

## Mapping assertions and contradictions

A native `MappingAssertion` has content-derived identity over exactly these
semantic fields: `type`, `semanticRing`, `sourceConcept`, `targetConcept`,
`sourceRelease`, `targetRelease`, `relation`, the canonically ordered
`evidence` identifiers, `assertedAt`, and the ring-required `context` when
present. Subject and entity assertions omit `context`. Value assertions require
`sourceEdition`, `targetEdition`, and `effectiveFrom`, with optional
`effectiveThrough`. Legal-identity assertions require `effectiveAt`.

Its `contentDigest` is SHA-256 over the canonical REF JSON encoding, including
one terminal LF, of exactly that basis. Its identifier is
`urn:ref:mapping-assertion:<semanticRing>:<contentDigest hex>`.

The atlas MUST preserve that native `id` and `contentDigest`; the outer atlas
record IRI and `recordDigest` identify the complete encoded record and do not
replace native identity. Candidate identity also remains separate from mapping
assertion identity. A candidate becomes a mapping only when a closed mapping
assertion cites admissible evidence.

Assertions that share endpoints but differ in relation, evidence, time, or
context are distinct facts, even when they contradict one another. A producer
MUST retain every such assertion and its evidence. It MUST NOT use
last-write-wins, select a preferred assertion silently, or collapse assertions
by endpoint pair. Only the same content-derived assertion identifier with
byte-identical canonical JSON may be deduplicated.

## Facts are not permission

The atlas scope, ring, participation, rights metadata, evidence class,
`useCeiling`, mapping assertion, manifest, and derived index are factual
records. None admits a concept for emission or authorizes search, assignment,
accepted output, or publication. A product's separately pinned policy makes
those decisions. The canonical atlas MUST contain no admission, authorization,
output-profile, or product-permission field added by the publisher.

## Verification levels

**File-only verification** uses the three published files. A verifier MUST:

1. verify the trusted external manifest digest and canonical manifest bytes;
2. validate both JSON files against their schemas and recompute their content
   identities;
3. verify the scope and output descriptors, file digests, and byte lengths;
4. verify canonical N-Quads bytes, graph identifiers, record encodings,
   containment, the complete derived index, and all counts; and
5. recompute `generationDigest`, the atlas identifier, and
   `canonicalPayloadDigest`.

This level proves the distribution is internally complete and unchanged. It
does not prove that a producer could still obtain the exact source captures.

**Producer reproduction** performs every file-only check, reopens the pinned
atlas index, index rows, concept releases, relation bundles, machine proofs,
and implementation source modules, and rebuilds all three files byte for byte.
A producer MUST refuse reproduction when any pinned input is missing, changed,
or fails ring and release closure. This stronger level proves both file
integrity and derivation from the exact declared sources.

## Derived products and SSSOM

Ring views, source-module views, search indexes, and other consumer products
are derived from this canonical distribution and MUST pin its manifest and
N-Quads digests. They do not become additional canonical files.

### Ring and subject-module projections

A portable projection contains exactly `atlas.nq` and
`atlas-manifest.json`. Its manifest MUST validate against
[`schemas/vocabulary-atlas-projection-manifest.schema.json`](schemas/vocabulary-atlas-projection-manifest.schema.json).
The projection is a sibling distribution type,
`VocabularyAtlasProjectionManifest`, and MUST NOT claim to be a canonical
atlas or reuse its parent's identifier. `derivedFrom` pins the verified
parent's atlas identifier, manifest digest, and N-Quads digest.

Projection policies use absolute, versioned identifiers and declarative
selectors:

- `ring:<semanticRing>` retains every release in one ring and each complete
  relation bundle whose endpoint releases remain selected.
- `module:<sourceModule>` requires a subject-ring specialist module, retains
  that module plus every subject-core release, and retains a relation bundle
  only when all endpoint releases remain selected.

The policy `id` is an absolute
`urn:ref:policy:vocabulary-atlas-projection:...` IRI. Its `selectors` object
contains only `semanticRing` or `sourceModule`; it MUST NOT copy the release
identifiers resolved from the parent or an output digest. The projection keeps
each selected canonical JSON record byte-for-byte. A selected relation bundle
brings its complete mapping, evidence, and machine-proof record closure. A
projection MUST NOT publish a mapping with only one endpoint release.

Reproduction accepts the verified parent distribution as its only source and
reapplies the named selector. It MUST reproduce the projection manifest and
N-Quads bytes exactly. Atlas 2.0 defines no separate
`consumer-read-closure` policy: unlike Atlas 1.0, the canonical cross-release
graph already carries closed assertions rather than disposable candidate and
label-cluster analysis. Product permission remains in the separately pinned
product policy.

SSSOM, the Simple Standard for Sharing Ontological Mappings, is an optional
interoperability view for `subject` mapping assertions and `value` crosswalk
assertions only. An SSSOM exporter MUST NOT emit `entity` or `legalIdentity`
relations. It MUST NOT emit a raw candidate as a mapping row, and every emitted
row MUST link to exactly one native content-derived `MappingAssertion` IRI.
The export and any evidence sidecar remain derived files; product use still
requires the product's external policy.

# RefSpec Atlas 3.0

Atlas 3.0 is an authority-first RDF profile for governed vocabularies,
code lists, identifier authorities, classifications, structural schemas, and
related reference resources. It keeps the content-addressed release and proof
discipline of Atlas 2.0 while making the semantic model explicit in RDF.

Atlas 3.0 is a greenfield binding. It does not preserve the Atlas 1.0 or 2.0
wire format. A producer MUST NOT translate an older release silently and claim
3.0 conformance.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative.

## What is authoritative

An Atlas distribution has three named graph roles:

| Graph role | Contents | Authority |
| --- | --- | --- |
| `asserted` | Exact releases, normalized resources, source records, SKOS-XL labels, evidence bindings, and editorial assertions | Authoritative for the distribution |
| `projection` | Plain SKOS labels and bare relation triples generated from the asserted graph | Reproducible interoperability view |
| `derived` | Optional rule results represented as `atlas:DerivedRelation` records | Non-authoritative |

Named graph placement is not self-authenticating. The manifest assigns each
graph role, and the dataset validator enforces the assignment. Consumers that
need editorial provenance MUST query assertion resources in the `asserted`
graph. They MUST NOT treat a bare triple in the projection graph, or a logical
consequence of that graph, as evidence that an editor asserted it.

A relationship is authoritative if and only if the asserted graph contains an
admissible, terminal-current, digest-checked, evidence-bearing
`atlas:RelationAssertion` for it.

## Distribution

A release is one self-contained directory. It contains one root manifest, four
supporting JSON files, one or more N-Quads packs, and no symlinks:

| File | Role | Purpose |
| --- | --- | --- |
| `atlas-manifest.json` | manifest | Closed distribution description and exact file pins |
| one or more `*.nq` or `*.nq.zst` files | packs | Partitioned asserted data and optional reproducible views |
| `atlas-source-accounting.json` | source accounting | One disposition for every enumerated source member |
| `atlas-acceptance.json` | acceptance | Passed validation gates and their evidence |
| `atlas-producer-validation.json` | producer validation | Compiled producer checks pinned to this binding and release |
| `atlas-construction-summary.json` | construction summary | Authenticated release-local build keys, inputs, dependencies, and pack receipts |
| `packs/compact/**/*.jsonl.zst` | compact construction records | Non-authoritative logical records used to verify and reuse unchanged release units |

The manifest MUST validate against
[`schemas/atlas-manifest.schema.json`](schemas/atlas-manifest.schema.json).
The other JSON files MUST validate against their correspondingly named schemas.
Every schema uses JSON Schema Draft 2020-12 and is closed to unknown fields.

The manifest pins the exact ontology, SHACL shapes, core JSON Schemas, validator
version, every RDF pack, and all four supporting JSON files. The construction
summary transitively pins every compact construction pack. Its
`bindingBundleDigest` additionally covers a sorted path, length, and digest
inventory of the README, ontology, shapes, every schema, registry profile map,
requirements, conformance-corpus declaration, coverage proof, real-registry
descriptor dataset and proof, fixture builder, shared canonical RDF renderer,
and independent validator, so a supporting binding asset cannot change
invisibly. The
manifest itself is pinned by a trusted digest supplied outside the distribution.
Its `canonicalPayloadDigest` covers the canonical JSON object with that one
field removed.

Every pack has a stable `packId`, a safe relative path, its graph counts, exact
dependencies, source-release and ring coverage, and two pins:

- `transport` pins the bytes stored in the distribution. It declares either
  uncompressed N-Quads or a Zstandard frame and records its media type, SHA-256
  digest, and byte length.
- `content` pins the canonical uncompressed N-Quads with its SHA-256 digest,
  byte length, and quad count.

A validator MUST stream-decompress a Zstandard pack, enforce the declared
uncompressed length, and require the resulting bytes to match `content`. The
transport digest makes the release byte-exact; the content digest keeps pack
identity independent from compression settings.

The construction summary is not another semantic authority. It is a sealed
index of how the authoritative RDF was built. For each source or mapping
release it records the exact input pins, adapter recipe, endpoint dependencies,
build key, source-accounting digest, owned RDF packs, compact logical-record
packs, and role counts. An incremental producer MAY reuse a unit only after it
verifies those receipts and independently recomputes the current pre-parse input
pins and build key. A changed source invalidates its unit, every mapping unit
that names it as an endpoint, and the shared catalog. Clean units bypass their
source parser and graph constructors. The merged candidate MUST still pass the
complete producer checks and reproduce the same bytes as a cold build for the
same inputs.

Compact construction packs use closed `Resource`, `Label`, `Statement`,
`EvidenceBinding`, `SourceRecord`, `Release`, `Identifier`, and
`LifecycleEvent` roles. Their canonical rows, defaults, dependencies, logical
digest, uncompressed receipt, and stored-byte receipt are all authenticated by
the construction summary. They remain non-authoritative until the separate
compact-record cutover in REF-015; consumers continue to treat the RDF packs as
the Atlas 3.0 knowledge base.

The manifest's `graphs` rows reconcile aggregate quad and pack counts. A graph
`inventoryDigest` is SHA-256 over REF-canonical JSON containing the sorted list
of `{packId, contentDigest, quadCount}` rows for packs with a nonzero count for
that role. An empty role hashes the empty list. The asserted graph's inventory
digest is the distribution-wide asserted-data pin. `atlas-acceptance.json`
records that value as `inputs.atlasDigest`.

Production distributions SHOULD use one or more `sourceRelease` packs per exact
source release. A large release MAY use stable subject buckets: hash the UTF-8
subject IRI with SHA-256 and select the declared lowercase hexadecimal prefix.
All asserted outgoing facts for one subject MUST remain in one pack. This rule
applies per graph role, so the same resource may also be a subject in a separate
projection pack. `catalog` packs hold descriptor-only shared data. Cross-release
`MappingAssertion` records belong in `mapping` packs that depend
on the exact endpoint release packs. Publisher-native and cross-ring relation
assertions belong to the evidence source's release pack. A small distribution
or fixture MAY use one uncompressed `aggregate` pack.

Pack dependencies refer to `packId` values in the same root manifest. Pack IDs,
paths, and dependency entries MUST be unique. Arrays and packs MUST be ordered
lexicographically by their identifying value. Dependencies MAY contain cycles
when publisher relations point both ways; they express exact input closure, not
an execution order.

Projection and derived packs are optional `view` packs. They contain no asserted
quads, declare the asserted graph's `inventoryDigest` as
`inputAssertedDigest`, and remain non-authoritative. A producer MAY omit the
projection even when asserted labels or relations can reproduce it; in that
case the projection graph count is zero and validation checks the asserted
preconditions for later reproduction. When a projection pack is present, it
MUST equal the projection regenerated from the asserted packs. The same rule
applies to a mixed `aggregate` pack: graph role, not physical co-location,
determines authority.

JSON files use the REF canonical JSON profile: UTF-8; no duplicate keys,
`null`, floating-point values, or non-finite numbers; sorted object keys;
compact separators; and one terminal LF. Integers MUST be within the exact
JavaScript integer range. Arrays retain their declared order.

An `atlas:nativePayload` uses the same canonical ordering and number rules but
MAY contain JSON `null` when its normalized source-evidence view contains it.
The payload need not copy the publisher record verbatim: an English-only Atlas
distribution keeps multilingual source content external and pins its exact
locator and digest. Descriptor and policy payloads remain on the stricter REF
profile.

The uncompressed content of every pack MUST be valid UTF-8 N-Quads with absolute
IRIs, no blank nodes, no default-graph statements, one statement per line,
lexicographically sorted unique lines, LF line endings, and one terminal LF. A
serialized line MUST NOT exceed 16,777,216 bytes. Across the complete pack set,
the same quad MUST NOT appear twice. The only named graphs are the three graph
IRIs declared by the manifest. The projection and derived roles may have zero
statements. Global line sorting across packs is neither required nor meaningful.

Every scheme, release, normalized resource, identifier, source record,
SKOS-XL label, editorial policy, relation assertion, evidence binding,
lifecycle event, projected relation, and derived relation carries
`atlas:contentDigest`. For these nodes, the digest
preimage is the UTF-8 encoding of every outgoing
predicate-object pair except `atlas:contentDigest`, rendered with the RDF 1.1
N-Triples term representation as `<predicate> <object> .`, sorted by complete
line, joined with LF, and terminated by one LF. The value is
`sha256:<64 lowercase hex>`. This digest detects semantic record drift without
requiring publisher-assigned resource IRIs to be replaced.

The binding supplies one shared term renderer for fixture construction,
registry-descriptor generation, and validation. It escapes quotes, backslashes,
tabs, line breaks, carriage returns, form feeds, and disallowed control
characters according to N-Triples while preserving valid Unicode. Validation
parses each pack and inspects RDF terms for blank nodes; text such as
`_:not-a-node` inside a literal is not a blank node. It reconstructs every
canonical N-Quads line and requires byte-for-byte equality with the uncompressed
content.

## Standards boundary

Atlas uses SKOS and SKOS-XL according to the
[SKOS Reference](https://www.w3.org/TR/skos-reference/). SKOS plus SKOS-XL is
formally an OWL Full vocabulary. Atlas therefore does not claim that the
combined SKOS dataset is an OWL 2 RL ontology.

The Atlas-owned ontology in [`ontology/atlas.ttl`](ontology/atlas.ttl) uses a
small OWL 2 RL-safe subset: named classes, subclass and disjointness axioms,
named properties, domains, ranges, and the OWL 2 RL datatype allowlist. The
ontology uses `rdfs:Literal` as the range for RDF JSON fields; SHACL applies the
more specific `rdf:JSON` publication constraint. The ontology contains no
property chain, functional property, inverse-property axiom, or Atlas-authored
axiom that changes a SKOS mapping property. The validator enforces an explicit
allowlist of ontology predicates, declaration types, and datatype ranges. OWL
supplies optional consequences; SHACL and the dataset validator decide whether
a release is publishable.

## Registry resource profiles

Atlas covers the full RefSpec registry through five resource profiles. The
checked profile map is
[`registry-resource-profiles.json`](registry-resource-profiles.json).

| Profile | Registry resource kinds | Typical content |
| --- | --- | --- |
| `conceptScheme` | subject, source-assigned, historical, and mapping vocabularies | Concepts, labels, definitions, notes, native semantic relations, mappings |
| `codeScheme` | code lists and classifications | Governed values, notations, field meanings, status and effective dates |
| `identifierScheme` | identifier authorities | Identifier values, validation rules, component positions, identified resources |
| `structureScheme` | structural schemas | Named fields, sections, ordered nodes, validation rules, and native relations |
| `resourceCollection` | resource families | Schemes whose members are separately released schemes |

The five profiles describe how a registry resource can be represented; they do
not claim that every inventoried resource already has a complete release.
Every catalog row is an `atlas:RegistrySource` descriptor. It identifies the
publisher or reference source independently from the governed schemes emitted
from it. A source may supply zero, one, or several `atlas:ResourceScheme`
instances. Schemes remain descriptor-only until exact source membership and
distributions are available. The generated coverage report
proves that every current resource kind, catalog row, Atlas index row, source
module, and implementation module has a disposition without copying the
registry inventory into this binding.

The same digest-pinned file is the single normative policy source for allowed
relation predicates by semantic ring and assertion type. SHACL Core checks
closed record structure, exact local path equality, and inverse release
membership. The shape graph contains no SPARQL constraints. The standalone
validator enforces carrier-type and graph-role exclusivity once in an indexed
pass, then checks conditions SHACL Core cannot express: a scheme supports each
release ring; labels share their resource's release and source record; equal
literals never cross label roles; evidence pins the exact source-record digest;
lifecycle chains remain linear; and each assertion predicate occupies an allowed
ring/type policy cell. The validator loads that policy matrix from the profile
file instead of repeating it in SHACL.

The profile map, registry coverage report, and descriptor proof each validate
against their own closed Draft 2020-12 JSON Schema. Procedural checks then
enforce ordering, embedded digests, exact inventory, and count reconciliation
that JSON Schema cannot express safely.

The checked `tests/registry-descriptors.nq` artifact serializes every current
catalog row as one `atlas:RegistrySource` plus its primary
`atlas:ResourceScheme`. Each source descriptor preserves its complete catalog
row as canonical `rdf:JSON`. Each primary scheme declares its source, profile,
and every ring supported by current Atlas index placements. Both nodes have a
recomputed content digest. Its proof pins the
catalog, index, profile policy, exact N-Quads bytes, resource-identity set, and
reconciled counts. This proves descriptor serialization, not complete member
releases: only resources with exact source membership may advance from a
descriptor to an `atlas:AtlasRelease`.

Common fields use `atlas:notation`, `atlas:definition`, `atlas:note`,
`atlas:recordStatus`, `atlas:validFrom`, `atlas:validUntil`,
`atlas:validationRule`, `atlas:componentPosition`, and
`atlas:collectionMember`. Source-specific fields that do not belong in that
small shared vocabulary remain in a canonical `rdf:JSON` `atlas:nativePayload`
on the source record. In an English-only distribution, that payload is an
English-only normalized view. The source record pins the exact external source
locator and digest, and may preserve dropped-language counts and digests without
copying dropped text. The native payload is evidence, not an invitation to
create an ungoverned property for every publisher column.

Every release and normalized resource belongs to exactly one semantic ring:

- `subject` describes topics and may use SKOS semantic and mapping relations;
- `entity` describes named real-world things and retains entity-specific
  identifiers and relations;
- `value` describes governed code and value members with edition context; and
- `legalIdentity` describes legal authorities, provisions, dockets, and their
  versioned relations.

Only `atlas:SubjectConcept` is necessarily a `skos:Concept`. An
`atlas:ValueResource` MAY also be a `skos:Concept` when its publisher treats
the code-list member as a concept. Atlas MUST NOT type entity or legal-identity
resources as `skos:Concept` merely to reuse SKOS predicates.

## Releases, schemes, resources, and source records

`atlas:AtlasRelease` identifies one immutable normalized edition, declares its
resource profile and semantic ring, and lists its complete membership with
`prov:hadMember`. Every member MUST point back to exactly that release with
`atlas:inRelease`. `atlas:SourceRelease` separately identifies the captured
publisher edition used by source records.

`atlas:RegistrySource` identifies a cataloged publisher or reference source.
It is not itself a concept scheme, code list, identifier authority, or
structural schema. Its `atlas:memberDisposition` states whether Atlas emits a
member release, uses child releases or assignment evidence, retains only a
definition or historical evidence, emits only mapping assertions, withholds
unreviewed mappings, records a source with no publisher rows, or describes a
resource family. This prevents a
descriptor-only source from looking like a silently unfinished adapter.
`atlas:ResourceScheme` identifies one stable governed
resource supplied by that source, independently from any edition. Every scheme
points to exactly one source descriptor; a source may supply several schemes
when its records have different governing semantics. A scheme declares zero or
more `atlas:supportedRing` values;
it does not collapse a multi-purpose registry resource into one singular ring.
Each release points to that scheme and selects exactly one supported ring. A
normalized member uses one of `atlas:SubjectConcept`, `atlas:EntityResource`,
`atlas:ValueResource`, or `atlas:LegalIdentityResource` and agrees with its
release on scheme, profile, and ring. A scheme is also a
`skos:ConceptScheme` whenever it uses the `conceptScheme` profile or hosts a
resource linked through `skos:inScheme`, regardless of its Atlas profile.

`atlas:Identifier` represents an authority-scoped identifier. Its literal value
is not a label and does not establish identity outside the named scheme. The
manifest counts distinct identifier records under `identifiers`; it MUST NOT
fold them into the `resources` count. Within one distribution, each ordered
pair of `atlas:identifierScheme` and `atlas:identifierValue` MUST identify
exactly one `atlas:AtlasResource`. More than one identifier record MAY repeat
the pair only when every record identifies that same resource.

`atlas:SourceRecord` identifies the source-local record and pins the exact
external locator and digest from which normalized resources, labels, or
assertions were derived. It carries a canonical English-only normalized native
view and explicit `atlas:representsResource` links; it does not claim to copy a
multilingual publisher record verbatim. Source record, label, and normalized
resource identities MUST be distinct. A source record belongs to exactly one
captured source release and has exactly one disposition in
`atlas-source-accounting.json` when that source release has enumerated
membership.

## SKOS-XL labels

SKOS-XL labels are canonical. Every label:

1. has an absolute IRI;
2. is a `skosxl:Label` and no normalized resource class;
3. has exactly one non-empty English `skosxl:literalForm`, represented as an
   `rdf:langString` with the language tag `en`;
4. identifies its exact Atlas release; and
5. identifies the source record from which it was produced.

Atlas 3.0 is English-only. Producers MUST omit non-English source labels from
the Atlas distribution and MUST NOT emit untagged label literals. The original
source may remain multilingual outside the distribution and may be referenced
by its exact locator and digest.

An Atlas resource MUST have at least one SKOS-XL label in any role. A source
may publish an alternate-only term identity, so Atlas does not invent a
preferred role that the publisher did not assert. Label identity MUST NOT be
derived from literal text alone. Two publishers, two
releases, or two records may use equal lexical forms without sharing a label
identity. Preferred, alternate, and hidden roles are expressed only through
`skosxl:prefLabel`, `skosxl:altLabel`, and `skosxl:hiddenLabel`. A resource has
at most one preferred English label. Label roles are pairwise
disjoint both by label IRI and by the literal that the plain-SKOS projection
would expose. A subject concept's `skos:inScheme` MUST equal its
`atlas:inScheme`; a `conceptScheme` is also a `skos:ConceptScheme`.

Plain `skos:prefLabel`, `skos:altLabel`, and `skos:hiddenLabel` statements are
generated into the projection graph. A producer MUST NOT maintain those
literals independently. The validator reconstructs them from the asserted
SKOS-XL labels and requires exact equality.

## Assertions and evidence

Every relation assertion uses the standard RDF reification fields
`rdf:subject`, `rdf:predicate`, and `rdf:object`. Rulespec's separation of
proposition, evidence, and lifecycle informed this design, but Atlas 3.0 does
not claim Rulespec record conformance: RefSpec's currently pinned Rulespec
dependency is unpublished and explicitly ineligible for production
conformance. A future Rulespec compatibility view MUST pin and validate an
exact published Rulespec contract; it MUST NOT infer conformance from shared
field names.

Atlas defines four assertion specializations:

- `atlas:NativeRelationAssertion` preserves a publisher-authored relation
  between resources in the same semantic ring. Its exact endpoints may belong
  to one release or to different releases;
- `atlas:MappingAssertion` compares resources across exact releases; a
  subject-ring mapping is also an `atlas:SkosMappingAssertion`; and
- `atlas:SourceAssignment` preserves a publisher assignment from a source
  record to a normalized resource; and
- `atlas:CrossRingRelationAssertion` links normalized resources in different
  semantic rings without weakening the same-ring rules for mappings and native
  relations.

A cross-ring assertion records `atlas:sourceRing` and `atlas:targetRing`, and
its exact endpoint releases and resource types MUST agree with those rings. It
MUST NOT also record `atlas:semanticRing`. The closed profile policy admits only
these directed cells:

| Source ring | Predicate | Target ring |
| --- | --- | --- |
| `entity` | `atlas:hasIndexedSubject` | `subject` |
| `legalIdentity` | `atlas:hasIndexedSubject` | `subject` |
| `entity` | `atlas:referencesLegalIdentity` | `legalIdentity` |

Cross-ring assertions MUST NOT use a SKOS predicate. Atlas declares the two
cross-ring predicates as ordinary object properties without inverse,
transitive, symmetric, property-chain, or SKOS subproperty axioms. Validation
and projection use their asserted direction only; no inference may create an
authoritative cross-ring claim.

For subject thesauri, `atlas:thesaurusUse` and
`atlas:thesaurusUsedFor` preserve publisher-authored USE/UF links as ordinary
Atlas predicates. `atlas:thesaurusRelated` preserves an authored associative
link when projecting it as `skos:related` would violate a SKOS integrity
condition because the same resources also have a transitive hierarchy path.
Atlas does not declare these predicates inverse, transitive, or equivalent to
SKOS label or semantic relations.

Each same-ring assertion records its semantic ring. Each cross-ring assertion
records its distinct source and target rings. Every assertion records exact
endpoint releases, sealed editorial policy, assertion time, lifecycle status,
stable identity digest, and content digest. `atlas:EditorialPolicy` preserves its policy document as
canonical `rdf:JSON`, has a recomputed content digest, and uses the
content-derived IRI `urn:ref:atlas-policy:<digest hex>`.

An assertion has at least one `atlas:EvidenceBinding` through the inverse
`atlas:bindsAssertion` path. Each binding identifies and pins the exact
`contentDigest` of one source record. It also records the approving reviewer,
review method, decision time, and optional decimal confidence in the closed
range 0 through 1. Review methods describe only how the claim was warranted:
human review, two-machine adjudication, publisher assertion, operator adoption,
or deterministic transformation. `atlas:trustedPipelineReview` remains the
generic method for a trusted process that cannot yet use a more precise basis.
No review method grants search, tagging, emission, or other product permission.
Only an `atlas:approved` binding supports an authoritative assertion. A binding
has a content digest and the content-derived IRI
`urn:ref:atlas-evidence:<digest hex>`. Evidence may be added without changing
the claim identity; an existing binding MUST NOT be rewritten.

The stable identity of a same-ring assertion is SHA-256 over canonical REF JSON,
including one terminal LF, with exactly these keys: `object`, `policy`,
`policyContentDigest`, `predicate`, `semanticRing`, `sourceRelease`, `subject`,
`targetRelease`, and `type`. A cross-ring assertion replaces `semanticRing`
with the two keys `sourceRing` and `targetRing`. The result is both
`atlas:assertionIdentityDigest` and the suffix of
`urn:ref:atlas-assertion:<digest hex>`. It deliberately excludes evidence,
timestamps, lifecycle status, and supersession. The separate
`atlas:contentDigest` covers the assertion's complete outgoing RDF state.

Publisher provenance and Atlas version adoption are separate facts. A mapping
source release pins the exact publisher alignment artifact it identifies;
supporting version metadata remains a separate pinned input and MUST NOT be
folded into that source-release digest. If Atlas applies a publisher mapping to
different loaded editions, the evidence binding uses `atlas:operatorAdoption`
and the assertion names those exact endpoint releases. A newer publisher
linkset count does not by itself establish pairwise re-review, and a producer
MUST NOT infer confidence from publication alone. Each later source version or
adoption creates immutable new evidence rather than rewriting an existing
binding.

Every distribution is immutable. A later distribution may retain the same
stable claim IRI while changing its lifecycle state and therefore its content
digest. `atlas:supersedes` connects a later, distinct claim to its predecessor.
The chain is linear: a predecessor has at most one direct successor, a successor
is strictly later, and the two records agree on assertion type, ring context,
subject, and source release. A non-terminal record MUST be `atlas:superseded`; a
terminal record MUST NOT be. Only a terminal `atlas:current` assertion is
admitted to the projection. A terminal `atlas:withdrawn` assertion remains
auditable but has no public relation triple.

## Projection and inference

For each admitted relation assertion, the projection graph contains:

1. the bare subject-predicate-object triple for interoperability; and
2. one `atlas:ProjectedRelation` record with the same subject, predicate, and
   object and one or more `atlas:supportingAssertion` links.

A projected same-ring relation records `atlas:semanticRing`. A projected
cross-ring relation instead records `atlas:sourceRing` and `atlas:targetRing`.
It retains the supporting cross-ring assertion identifier and remains a
reproducible, non-authoritative convenience record.

Projection and derivation records use the neutral fields
`atlas:relationSubject`, `atlas:relationPredicate`, and
`atlas:relationObject`; an editorial assertion query over `rdf:predicate`
therefore cannot return them accidentally.

Several assertions may converge on one projection record. Every projected
relation MUST have support; every terminal current assertion MUST be projected
exactly once by value, while superseded and withdrawn assertions MUST NOT
support it. The projection is reproducible from the asserted graph.
The projection-record IRI is `urn:ref:atlas-projection:<digest hex>`, where the
digest covers canonical REF JSON with exactly `subject`, `predicate`, and
`object`, without a terminal LF.

The 3.0 baseline performs no mapping closure. This point is especially
important for `skos:exactMatch`, which SKOS defines as symmetric and
transitive. Given asserted mappings `A exactMatch B` and `B exactMatch C`, an
OWL-aware consumer may conclude `A exactMatch C`. Atlas does not thereby claim
that an editor asserted or reviewed that third relationship.

If a producer publishes a useful consequence, it creates an
`atlas:DerivedRelation` in the `derived` graph. That record identifies its
input assertions, rule, engine and version, exact input digest, generation
time, and `atlas:nonAuthoritative` status. It MUST NOT be a
`atlas:RelationAssertion`, appear in the direct projection, or satisfy an
editorial mapping query. Applications opt into derived relations explicitly.

The derived input digest is SHA-256 over canonical REF JSON without a terminal
LF: `{"assertions":[{"assertion":<IRI>,"contentDigest":<digest>},...]}` with
rows sorted by assertion IRI. The 3.0 baseline allowlists only
`urn:ref:rule:skos-exact-match-closure-path` executed by `owlrl` 7.1.4. Every
input MUST be a terminal current exact-match assertion. The output endpoints
MUST be distinct, the cited undirected exact-match edges MUST form one simple
path of at least two edges with no branches, cycles, duplicates, or unused
inputs, and the output MUST NOT already have a directly asserted projection.
The validator recomputes the input digest, checks endpoint existence and rings,
pins the engine, and replays that exact proof path. A separate pinned `owlrl`
closure then confirms that every derived output is a newly inferred mapping,
not a direct projection relation.

`skos:exactMatch` retains its W3C semantics. A producer that does not accept
transitive consequences SHOULD use `skos:closeMatch` or a ring-specific Atlas
predicate that is not a subproperty of `skos:exactMatch`.

Publication integrity applies those semantics even though Atlas does not
materialize their closure. For SKOS S46, the validator builds symmetric,
transitive exact-match components and rejects any broad, narrow, or related
mapping inside a component, including inverse and multi-hop conflicts. For
SKOS S27, it normalizes `broadMatch`/`narrowMatch` as hierarchy directions and
`relatedMatch` as an associative relation, then rejects direct or transitive
hierarchy/association conflicts.

## Source accounting and acceptance

The source-accounting ledger states whether each captured member was
`represented`, `excluded`, or `unresolved`. Represented members identify one or
more normalized Atlas resources or evidence-backed assertions. Excluded and
unresolved members carry a reason. Totals MUST reconcile exactly, and a
validator MUST reject duplicate, missing, unknown, or falsely linked
source-record dispositions. The ledger's resource list MUST exactly equal each
record's `atlas:representsResource` links; when `atlasAssertions` is present it
MUST exactly name the assertions whose evidence bindings use that record. A
represented disposition MUST name at least one resource or assertion. Excluded
and unresolved dispositions omit both fields and carry a reason.
`notEnumerated` sources record
that completeness cannot be claimed; they do not silently pass a complete
membership gate.

The acceptance file records successful gates, not permission for a downstream
product. Each gate has an `evidenceDigest` over its name, passed status, exact
input digests, and exact validator identity. The standalone validator
recomputes every receipt. The file MUST include these gate names:

- `canonical-json`
- `json-schema`
- `rdf-syntax`
- `ontology-profile`
- `shacl-meta`
- `shacl-data`
- `dataset-closure`
- `source-accounting`
- `projection-parity`
- `reasoning-isolation`
- `profile-conformance`

Registry coverage is a binding-level proof, not a per-distribution gate. The
binding validator verifies its canonical digest, profile pin, non-vacuous
counts, set digests, and reconciliation relationships. Repository generation
then proves exact regeneration from the current registry inputs.

An Atlas acceptance proves that the distribution conforms to this binding. It
does not authorize search expansion, entity linking, assignment, publication,
or another product use. Such permission remains in a separately pinned product
policy.

## Validation order

A conforming validator MUST fail closed in this order:

1. reject unsafe paths, symlinks, missing or extra files, and digest or length
   mismatches;
2. reject non-canonical JSON and validate every JSON document with its closed
   schema;
3. stream-decompress each pack, check its transport and content pins, parse the
   no-blank-node N-Quads profile, and reconcile per-pack and aggregate graph
   counts and inventory digests;
4. lint the Atlas ontology's local OWL profile, then parse and meta-validate the
   SHACL shapes;
5. validate each asserted pack under its shapes and placement rules, then
   reconcile global subject ownership, duplicate quads, and pack dependencies;
6. reconcile releases, membership, endpoint releases, evidence, identities,
   source accounting, and manifest counts across the complete pack set;
7. when projection packs exist, regenerate the label and relation projection
   and require exact equality; otherwise verify its asserted preconditions;
8. prove that allowlisted reasoning adds no assertion, projection record, or
   authoritative graph statement; and
9. require the acceptance gate set; then, for binding validation, verify the
    sealed corpus, registry coverage report, and real-registry descriptor
    export.

A validator MAY cache a successful pack receipt by binding digest, content
digest, graph counts, and dependency digest. It MAY reuse that receipt when all
pins match exactly. It MUST still run the root-level uniqueness, endpoint,
dependency, accounting, count, projection, and acceptance checks. The cache is
disposable and transfers no authority.

The independent validator also supports an authenticated local receipt for an
unchanged complete distribution:

```sh
python tools/validate.py \
  --distribution /path/to/distribution \
  --cache-dir /path/to/private-atlas-cache
```

The first run performs full parsing and semantic validation. A later exact hit
still checks the closed file set, canonical manifest and JSON, binding pins,
acceptance, lengths, and the SHA-256 digest of every stored pack. It can then
reuse the prior semantic result without decompressing or loading the RDF. The
receipt is keyed by the manifest, binding, and validator identity and protected
by a private local authentication key. A missing, malformed, moved, or modified
receipt is only a cache miss and triggers full validation. The cache directory
must remain outside the distribution. If any pack or root input changes, the
validator reparses the complete graph because the global checks above still
need the cross-pack facts; compact per-pack receipts cannot safely replace
those facts.

A trusted writer MAY satisfy `shacl-data` with a compiled producer proof instead
of running general SHACL over its own generated RDF. The proof MUST pin the
exact ontology and SHACL-shape digests it implements, run meta-SHACL, validate
the normalized source and publisher-mapping rows and their joins, and reconcile
the fixed constructor counts with source accounting and exact pack receipts. It
MUST fail closed when either binding pin changes. The current compiled profile
admits publisher-source resources, English labels, identifiers, native and
cross-ring relations, source assignments, and separately pinned explicit
publisher mappings. Projections, derived relations, inferred mappings, and
supersession remain absent.

The generation report distinguishes this compiled producer proof from
independent consumer validation. A consumer does not inherit the writer's trust
or resident state: `validate_distribution` still decompresses and parses the
files, runs normative SHACL and the global semantic checks, and recomputes every
receipt. The conformance tests compare representative output from every current
assertion constructor with that normative verdict.

The conformance corpus declares its expected result and first issue code. Its
required case inventory is closed in the independent validator, and its paths
must equal the fixture directories. Each invalid case MUST fail for that named
reason. The synthetic fixtures cover every canonical resource and graph role,
all five registry profiles, the four semantic rings, SKOS and SKOS-XL
integrity, native-payload preservation, source accounting, immutable evidence,
graph-role isolation, projection parity, and inference isolation. The separate
registry proofs establish both inventory/profile coverage and lossless
descriptor serialization for all 86 resources. They do not pretend that a
descriptor is a complete production release or that the synthetic fixture
members came from those resources.

## Compatibility views

JSON-LD, Turtle, SSSOM, tables, search indexes, and application-specific graph
views MAY be generated from a verified distribution. They are derived products,
pin the root manifest and asserted inventory digest, and do not become competing
sources of truth. A portable derived view MAY be included as a manifest-pinned
`view` pack; a local file index need not be distributed. Neither case requires a
database service. SSSOM exports only semantically applicable mapping assertions
and retain the supporting Atlas assertion identifiers.

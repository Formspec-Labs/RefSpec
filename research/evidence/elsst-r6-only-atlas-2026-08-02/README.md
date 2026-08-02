# ELSST R6-only managed release and its atlas projection, 2026-08-02

The structured result is in [evidence.json](evidence.json). It closes two
things [`docs/atlas-distribution-measurement.md`](../../../docs/atlas-distribution-measurement.md)
left open: the R6-only figures were a *projection over a two-edition build*
rather than the output of one, and a projection had no identity of its own.

## What was built

| Artifact | Identity |
| --- | --- |
| ELSST R6-only managed release | bundle manifest `sha256:e20928a6cb68494dfac8b8c16d6aa3db1147f2145d99c31bd01287eeced9761f` |
| … its publication release | `urn:ref:elsst:publication:development:f05a1aeb…` |
| FR 2025 + ELSST R6 + crosswalk atlas | `urn:ref:vocabulary-atlas:d33c05df2446cfa57129005db911d21c4fefe027598af3afb3b0cb559120a3e8` |
| … its consumer projection | `urn:ref:vocabulary-atlas-projection:f720ae717d10af5521c895817f296f1e1a1ab5b737c79080000b1e11efd65018` |

The managed release is a real bundle, not a filtered read: 3,470 members over
one release, 155,447 indexed expressions, 88,913 normalized labels, 12,482
normalized relations, zero lifecycle participants (a one-edition history proves
no transition), one import-coverage report, and its own combined RefSpec/Rulespec
validation receipt. It opens through `ManagedReleaseView.open` and
`PinnedManagedRelease.open` like any other atlas input. The build took 406.6
seconds and peaked at 4,068,278,272 bytes.

## Losslessness, by execution

Two crosswalk-bearing atlases, same Federal Register 2025 package, same Rulespec
Core release, same 2026-08-02 qualification bundle; only the ELSST input differs.

| | R5 + R6 | R6 only |
| --- | ---: | ---: |
| `atlas.nq` | 263,620,491 | **45,066,321** |
| gzip -9 | 17,038,083 | 3,443,202 |
| mapping candidates | 365 | **365** |
| … `searchOnly` / `notEligible` | 121 / 244 | **121 / 244** |
| qualified `searchOnly` mappings | 121 | **121** |
| machine validations | 729 | **729** |
| Federal Register 2025 members | 705 | **705** |
| ELSST R6 members | 3,470 | **3,470** |
| ELSST R5 members | 3,435 | 0 |
| label clusters | 96,867 | 279 |
| hierarchy edges | 6,754 | 3,393 |

**The qualified set is identical, not merely the same size**: the 121
`(source, target, relation, source release, target release)` tuples compare
equal. −82.9% of the bytes.

One thing does move and it is worth naming. R6's `rkaf:referenceReleaseDigest`
changes from `sha256:a75f6dd4…` to `sha256:fdaf27ad…`, because a distribution
IRI is scoped to the set of sources the history was built from and the release
digest closes over its distribution. Nothing breaks: a crosswalk candidate pins
release **IRIs**, and the atlas independently requires each named release to
carry exactly one digest, which both do.

## The projection

`refspec-vocabulary-atlas-projection-nquads-1.0` under policy
`urn:ref:policy:vocabulary-atlas-projection:consumer-read-closure` version 1.

**30,174,064 bytes, 1,911,890 gzipped** — 67.0% of the atlas it came from, and
1.30× the raw size of today's vendored 1,469,637-byte Federal-Register-only
asset once gzipped. It opens in 2.5 seconds and rebuilds byte-identically in
8.4.

It carries 3,393 `skos:broader` edges, 121 qualified mappings with their 121
candidates and 242 validations, 104,770 release facts and zero label clusters.

Every fact a consumer reads is byte-identical to the atlas it came from —
digested predicate by predicate, not sampled:

| Read | Atlas | Projection |
| --- | --- | --- |
| concept labels (`prefLabel`/`altLabel` on members) | 90,051 / `a6ac98f506c6a845` | 90,051 / `a6ac98f506c6a845` |
| `skos:related` | 7,147 / `c3724535b7be6116` | 7,147 / `c3724535b7be6116` |
| `skos:broader` | 3,393 / `0137590b43c309b0` | 3,393 / `0137590b43c309b0` |
| `prov:hadMember` | 4,175 / `34727d988699e797` | 4,175 / `34727d988699e797` |
| `atlas:memberOfRelease` | 4,175 / `b3ab0a17b6310bad` | 4,175 / `b3ab0a17b6310bad` |
| reference releases + digests | 2 / `02330cf5c3ec8a31`, `a50acbc743d2f35a` | identical |

Its identity is its own: `urn:ref:vocabulary-atlas-projection:f720ae71…` against
the parent's `urn:ref:vocabulary-atlas:d33c05df…`, derived from the parent asset
id, both parent digests, the named policy version and the projecting
implementation. `reproduce_from_parent` rebuilds it from the parent and the keep
rule and compares both files. The atlas reader refuses it with *"atlas manifest
fields differ from v1"*, and `reproduce_distribution` without a parent refuses
with *"a vocabulary atlas projection reproduces from its parent distribution,
not from managed releases"* — neither is the corrupted-atlas message that
refusal used to borrow.

## What the vendored consumer does with both

Run against `spicysearch/src/spicysearch/vocabulary_atlas.py`
`sha256:0b396888ebaeb8ca1149fdae573517b2ad5f213d20eedf7f9073a26a9a5952d0`:

- **the edition-restricted atlas opens**, in 4.2 seconds, returning 90,051
  `concept_labels()` rows — the same count RefSpec reads from it. The
  `hierarchyEdges` refusal recorded on 2026-08-02 against reader
  `sha256:5f96c241…` no longer fires; that consumer amendment has landed.
- **the projection is refused**: `atlas manifest fields differ from the
  supported format`. That is correct and expected. A projection is a different
  kind, and the consumer has not been taught it.

So the vendorable-today artifact is the 45 MB edition-restricted atlas, and the
30 MB projection is what a consumer gets once it learns one more manifest shape.

## Reproducing

Builds are machine-local under `RefSpec/output/` (gitignored). The ELSST R6
source is `sha256:c362aec545db916ecb67af0eb9b8b4cecac1cb2118a717b69d8e6dad5591aa95`,
19,915,491 bytes. The other pinned inputs are the ones named in
[`atlas-distribution-2026-08-02`](../atlas-distribution-2026-08-02/README.md).
The managed release is built by the opt-in gate in
`tests/test_elsst_managed_release.py`; the atlas and its projection by
`refspec-build-vocabulary-atlas` and
`refspec-build-vocabulary-atlas-projection`.

## One pre-existing defect found on the way

`tests/test_elsst_managed_release.py` asserts that the full two-edition gate
reproduces bundle manifest digest `sha256:8dd408ef…`. **It cannot, and has not
been able to since commit `05805d4`** — three weeks of RefSpec commits before
this work. The bundle records
`operationalSerializationProfile.digest`, which is a digest of the REF JSON
binding schema set; `09c1ce9` set it to `sha256:160f2ae5…`, which is the value
the 2026-07-29 evidence recorded, and `05805d4` moved it to
`sha256:cc3d2aba…`. Rebuilt today the gate produces `sha256:379bd131…`, and
exactly two records differ from the 2026-07-29 bundle: the publication release
manifest and the combined receipt that pins it. Everything else — the Rulespec
graph, every operational record, the 308,639-row corpus, the tables, the source
artifacts — is byte-identical.

Nobody noticed because the gate is environment-gated and skips by default. It
is recorded here rather than repaired quietly: the fix is a judgement about
whether a managed release should pin a schema-set digest that moves under it,
and that is a separate decision from this one.

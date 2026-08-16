# REF-038 protected-file integration

This handoff targets the protected files as they stood on 2026-08-16. Rebase
the snippets onto the sibling job before applying them. The REF-038 job did not
edit any file named below and did not build a distribution.

## 1. Admit the source to the registry source manifest

In `tools/build_registry_source_manifest.py`, add this member to `TEST_INPUTS`:

```python
    "regulations_gov_agencies.py": (
        {
            "name": "regulationsGovAgencies20260816",
            "localPath": (
                "tests/fixtures/regulations_gov_agencies/"
                "regulations-gov-agencies-2026-08-16.json"
            ),
            "publisherUrl": "https://api.regulations.gov/v4/agencies",
            "sha256": (
                "sha256:28ab9f5422dd27fc7906ddc696e8e7811"
                "b11056822f370bcee7ea18a28418fa2"
            ),
            "byteLength": 91_408,
            "acquisition": "authenticatedPublisherApi",
            "provenance": "publisherApiResponse",
        },
    ),
```

Then regenerate the checked manifest with the sibling job's normal command:

```text
uv run python tools/build_registry_source_manifest.py
uv run python tools/build_registry_source_manifest.py --check
```

The entry names the credential requirement through the reader and release
metadata. It must never contain the key value, an authorization header value,
or a query parameter.

## 2. Add independent source-fidelity reconstruction

In `tools/verify_atlas_source_fidelity.py`, bump `VERIFIER_VERSION`, then add:

```python
REGULATIONS_GOV_AGENCIES_JSON_READER = (
    "regulations-gov-agencies-json-v1/1.0"
)
```

Add that constant to `SPEC_SCOPED_RECORD_READERS` and `_PUBLISHER_READERS`:

```python
SPEC_SCOPED_RECORD_READERS = frozenset(
    {
        # existing readers ...
        REGULATIONS_GOV_AGENCIES_JSON_READER,
    }
)

_PUBLISHER_READERS: Mapping[
    str,
    Callable[[SourceSpec, Mapping[SourcePin, bytes]], PublisherView],
] = {
    # existing readers ...
    REGULATIONS_GOV_AGENCIES_JSON_READER: (
        _read_regulations_gov_agencies_capture
    ),
}
```

Place this independent reader beside `_read_ecfr_agencies_capture`. It uses
only the verifier's stock JSON and API-capture helpers; it must not import
`refspec.registry.regulations_gov_agencies` or the Atlas roster adapter.

```python
_REGULATIONS_GOV_RECORD_FIELDS = frozenset(
    {"id", "type", "attributes", "links"}
)
_REGULATIONS_GOV_ATTRIBUTE_FIELDS = frozenset(
    {
        "parent",
        "participate",
        "partner",
        "postingGuidelines",
        "name",
        "agencyType",
    }
)
_REGULATIONS_GOV_LINK_FIELDS = frozenset({"self"})
_REGULATIONS_GOV_AGENCY_ID = re.compile(r"^[A-Z0-9-]+$")


def _read_regulations_gov_agencies_capture(
    spec: SourceSpec,
    payloads: Mapping[SourcePin, bytes],
) -> PublisherView:
    """Reconstruct the complete regulations.gov agency roster independently."""

    pin, payload = _pin_with_role(
        spec,
        payloads,
        "publisherAgencyRoster",
    )
    root = _json_without_duplicate_keys(payload, spec.name)
    if not isinstance(root, Mapping) or set(root) != {"data"}:
        raise ValueError(f"{spec.name} top-level fields drifted")
    values = root["data"]
    if not isinstance(values, list) or len(values) != 331:
        raise ValueError(f"{spec.name} must contain exactly 331 records")

    records: list[_ApiCaptureRecord] = []
    ids: set[str] = set()
    parents: set[str] = set()
    parent_count = 0
    for ordinal, value in enumerate(values):
        label = f"{spec.name}.data[{ordinal}]"
        if not isinstance(value, Mapping) or set(value) != (
            _REGULATIONS_GOV_RECORD_FIELDS
        ):
            raise ValueError(f"{label} fields drifted")
        agency_id = _required_text(value.get("id"), f"{label}.id")
        if _REGULATIONS_GOV_AGENCY_ID.fullmatch(agency_id) is None:
            raise ValueError(f"{label}.id has an unsupported shape")
        if agency_id in ids:
            raise ValueError(f"{spec.name} repeats agency id {agency_id!r}")
        ids.add(agency_id)
        if value.get("type") != "agencies":
            raise ValueError(f"{label}.type must remain 'agencies'")

        attributes = value.get("attributes")
        if not isinstance(attributes, Mapping) or set(attributes) != (
            _REGULATIONS_GOV_ATTRIBUTE_FIELDS
        ):
            raise ValueError(f"{label}.attributes fields drifted")
        parent = attributes.get("parent")
        if parent is not None and (
            not isinstance(parent, str)
            or _REGULATIONS_GOV_AGENCY_ID.fullmatch(parent) is None
        ):
            raise ValueError(f"{label}.attributes.parent is invalid")
        for field in ("participate", "partner"):
            if not isinstance(attributes.get(field), bool):
                raise ValueError(f"{label}.attributes.{field} must be boolean")
        guidelines = attributes.get("postingGuidelines")
        if guidelines is not None and not isinstance(guidelines, str):
            raise ValueError(
                f"{label}.attributes.postingGuidelines must be text or null"
            )
        name = _required_text(attributes.get("name"), f"{label}.attributes.name")
        if attributes.get("agencyType") != "Federal":
            raise ValueError(f"{label}.attributes.agencyType must remain 'Federal'")

        links = value.get("links")
        if not isinstance(links, Mapping) or set(links) != (
            _REGULATIONS_GOV_LINK_FIELDS
        ):
            raise ValueError(f"{label}.links fields drifted")
        self_link = _required_text(links.get("self"), f"{label}.links.self")
        expected_link = (
            "https://api.regulations.gov/v4/agencies/" + agency_id
        )
        if self_link != expected_link:
            raise ValueError(f"{label}.links.self differs")

        resource = (
            "urn:ref:regulations-gov-agency:"
            + urllib.parse.quote(agency_id, safe="")
        )
        relations: tuple[tuple[str, str], ...] = ()
        if parent is not None:
            parent_count += 1
            parents.add(parent)
            relations = (
                (
                    _ATLAS_PARENT_ENTITY,
                    "urn:ref:regulations-gov-agency:"
                    + urllib.parse.quote(parent, safe=""),
                ),
            )
        records.append(
            _ApiCaptureRecord(
                resource=resource,
                preferred_label=name,
                notations=(agency_id,),
                source_locator=self_link,
                source_digest=pin.sha256,
                native_payload={
                    "id": agency_id,
                    "type": "agencies",
                    "parent": parent,
                    "participate": attributes["participate"],
                    "partner": attributes["partner"],
                    "postingGuidelines": guidelines,
                    "name": name,
                    "agencyType": attributes["agencyType"],
                    "links": dict(links),
                },
                is_skos_concept=False,
                relations=relations,
            )
        )

    if any(parent not in ids for parent in parents):
        raise ValueError(f"{spec.name} names a parent outside the roster")
    if parent_count != 160 or len(parents) != 17:
        raise ValueError(
            f"{spec.name} parent census differs: "
            f"relations={parent_count}, distinct={len(parents)}"
        )
    return _api_capture_view(records, spec, payloads)
```

Add this `SourceSpec` beside the other entity rosters:

```python
    SourceSpec(
        name="regulations-gov-agencies-roster-2026-08-16",
        kind="vocabulary",
        release_keys=("regulations-gov-agencies-roster-2026-08-16",),
        inputs=(
            SourcePin(
                path=(
                    "tests/fixtures/regulations_gov_agencies/"
                    "regulations-gov-agencies-2026-08-16.json"
                ),
                sha256=(
                    "sha256:28ab9f5422dd27fc7906ddc696e8e7811"
                    "b11056822f370bcee7ea18a28418fa2"
                ),
                byte_length=91_408,
                fmt="json",
                role="publisherAgencyRoster",
                source_iri="https://api.regulations.gov/v4/agencies",
            ),
        ),
        reader=REGULATIONS_GOV_AGENCIES_JSON_READER,
        identity_policy="publisher-key",
        policies=DIRECT_SKOS_POLICIES,
        rdf_source=_rdf_source_policy(
            frozenset(
                {
                    "id",
                    "type",
                    "parent",
                    "participate",
                    "partner",
                    "postingGuidelines",
                    "name",
                    "agencyType",
                    "links",
                }
            ),
            additional_relation_predicates=(f"{ATLAS}parentEntity",),
        ),
    ),
```

The source-fidelity proof must report 331 resources, 331 preferred labels, 331
notations, 331 source records, zero identifier rows, and 160 parent relations.

## 3. Write the two projection tables

In `src/refspec/atlas/parquet_tables.py`, add these table definitions after
`TABLE_NAMES`. Keep the projection separate from `CompactRecordRole`: these
rows derive from REF-038 adjudication and are not asserted Atlas logical
records.

```python
AGENCY_PROJECTION_ROLE = "agencyProjection"
AGENCY_PROJECTION_UNRESOLVED_ROLE = "agencyProjectionUnresolved"

_AGENCY_PROJECTION_SOURCE_RECORD = pa.struct(
    [
        pa.field("release_key", pa.string(), nullable=False),
        pa.field("release_digest", pa.string(), nullable=False),
        pa.field("resource", pa.string(), nullable=False),
        pa.field("source_locator", pa.string(), nullable=False),
        pa.field("source_digest", pa.string(), nullable=False),
        pa.field("field", pa.string(), nullable=False),
        pa.field("value", pa.string(), nullable=False),
    ]
)
_AGENCY_PROJECTION_EVIDENCE = pa.struct(
    [
        pa.field("record_id", pa.string(), nullable=False),
        pa.field("evidence_tier", pa.string(), nullable=False),
        pa.field("warrant", pa.string(), nullable=False),
        pa.field("reviewer", pa.string(), nullable=False),
        pa.field("adjudicated_on", pa.string(), nullable=False),
        pa.field("decision_record", pa.string(), nullable=False),
        pa.field("decision", pa.string(), nullable=False),
        pa.field("decision_basis", pa.string(), nullable=False),
        pa.field("relation", pa.string(), nullable=False),
        pa.field("name_similarity_used", pa.bool_(), nullable=False),
        pa.field(
            "source_record",
            _AGENCY_PROJECTION_SOURCE_RECORD,
            nullable=False,
        ),
        pa.field(
            "target_record",
            _AGENCY_PROJECTION_SOURCE_RECORD,
            nullable=False,
        ),
    ]
)
AGENCY_PROJECTION_TABLE_SCHEMAS: Mapping[str, pa.Schema] = {
    AGENCY_PROJECTION_ROLE: pa.schema(
        [
            pa.field("source_value_kind", pa.string(), nullable=False),
            pa.field("source_value", pa.string(), nullable=False),
            pa.field("org", pa.string(), nullable=False),
            pa.field("pref_label", pa.string(), nullable=False),
            pa.field("abbreviations", pa.list_(pa.string()), nullable=False),
            pa.field("aliases", pa.list_(pa.string()), nullable=False),
            pa.field("parent_org", pa.string()),
            pa.field("relation", pa.string(), nullable=False),
            pa.field("evidence_tier", pa.string(), nullable=False),
            pa.field("warrant", pa.string(), nullable=False),
            pa.field("basis", pa.string(), nullable=False),
            pa.field(
                "evidence_records",
                pa.list_(_AGENCY_PROJECTION_EVIDENCE),
                nullable=False,
            ),
        ]
    ),
    AGENCY_PROJECTION_UNRESOLVED_ROLE: pa.schema(
        [
            pa.field("source_value_kind", pa.string(), nullable=False),
            pa.field("source_value", pa.string(), nullable=False),
            pa.field("source_org", pa.string(), nullable=False),
            pa.field("pref_label", pa.string(), nullable=False),
            pa.field("source_parent_org", pa.string()),
            pa.field("reason", pa.string(), nullable=False),
            pa.field(
                "candidate_resources",
                pa.list_(pa.string()),
                nullable=False,
            ),
        ]
    ),
}
AGENCY_PROJECTION_TABLE_NAMES: Mapping[str, str] = {
    AGENCY_PROJECTION_ROLE: "agency-projection.parquet",
    AGENCY_PROJECTION_UNRESOLVED_ROLE: (
        "agency-projection-unresolved.parquet"
    ),
}


def agency_projection_table_relative_path(role: str) -> str:
    return f"{TABLE_DIRECTORY}/{AGENCY_PROJECTION_TABLE_NAMES[role]}"


def write_agency_projection_tables(
    output: Path,
    projection: AgencyProjection,
) -> None:
    rows_by_role = {
        AGENCY_PROJECTION_ROLE: [row.to_dict() for row in projection.rows],
        AGENCY_PROJECTION_UNRESOLVED_ROLE: [
            row.to_dict() for row in projection.unresolved
        ],
    }
    directory = output / TABLE_DIRECTORY
    for role, rows in rows_by_role.items():
        target = directory / AGENCY_PROJECTION_TABLE_NAMES[role]
        if target.exists():
            raise FileExistsError(
                f"agency projection table already exists: {target}"
            )
        pq.write_table(
            pa.Table.from_pylist(
                rows,
                schema=AGENCY_PROJECTION_TABLE_SCHEMAS[role],
            ),
            target,
            compression=COMPRESSION,
            compression_level=COMPRESSION_LEVEL,
            use_dictionary=True,
            write_statistics=True,
            version=PARQUET_VERSION,
            data_page_version=DATA_PAGE_VERSION,
            row_group_size=ROW_GROUP_SIZE,
        )
        if pq.read_table(target).to_pylist() != rows:
            raise AtlasParquetTableError(
                f"agency projection Parquet round trip differs: {role}"
            )
```

Add `from refspec.atlas.agency_projection import AgencyProjection` and export
the new constants, schemas, path helper, and writer in `__all__`.

## 4. Carry the pure result through the producer

In `tools/generate_atlas_v3_full.py`, extend the imports:

```python
from typing import Any, TextIO, cast

from refspec.atlas.agency_projection import (
    AGENCY_ROSTER_RELEASE_KEYS,
    AgencyProjection,
    build_agency_projection,
)
from refspec.atlas.parquet_tables import (
    TABLE_DIRECTORY,
    TABLE_NAMES,
    AtlasParquetTableWriter,
    write_agency_projection_tables,
)
from refspec.atlas.v3_source_data import (
    # existing names ...
    RegistryRelation,
    RegistryResource,
)
```

Add these helpers beside `_adapt_registry_release`:

```python
def _registry_release_for_agency_projection(
    release: LoadedRelease,
) -> RegistryRelease:
    if release.spec.resource_id is None or release.spec.source_module is None:
        raise ValueError(
            f"agency projection release {release.spec.key} lacks registry metadata"
        )
    return RegistryRelease(
        key=release.spec.key,
        resource_id=release.spec.resource_id,
        source_module=release.spec.source_module,
        profile=release.spec.profile,
        ring=release.spec.ring,
        scope=release.spec.scope,  # type: ignore[arg-type]
        issued=release.issued,
        source_release_iri=release.source_release_iri,
        source_release_digest=release.source_release_digest,
        atlas_release_iri=release.atlas_release_iri,
        scheme_iri=release.scheme_iri,
        inputs=release.spec.input_pins,
        resources=cast(Sequence[RegistryResource], release.resources),
        relations=cast(Sequence[RegistryRelation], release.relations),
        cross_ring_relations=release.cross_ring_relations,
        supplemental_source_records=release.supplemental_source_records,
        dropped_label_count=release.dropped_label_count,
        metadata=release.metadata,
    )


def _agency_projection_from_loaded_releases(
    releases: Sequence[LoadedRelease],
) -> tuple[AgencyProjection | None, tuple[str, ...]]:
    by_key = {release.spec.key: release for release in releases}
    missing = tuple(
        key for key in AGENCY_ROSTER_RELEASE_KEYS if key not in by_key
    )
    if missing:
        return None, missing
    selected = tuple(
        _registry_release_for_agency_projection(by_key[key])
        for key in AGENCY_ROSTER_RELEASE_KEYS
    )
    return build_agency_projection(selected), ()


def _agency_projection_manifest_metadata(
    projection: AgencyProjection | None,
    missing_release_keys: Sequence[str],
) -> dict[str, Any]:
    if projection is None:
        return {
            "status": "notEmitted",
            "missingReleaseKeys": list(missing_release_keys),
        }
    return {
        "status": "emitted",
        "decision": "REF-038",
        "digest": projection.digest,
        "coverage": projection.coverage.to_dict(),
    }
```

In `build_distribution()`, compute the result before `del releases`:

```python
    agency_projection: AgencyProjection | None = None
    agency_projection_missing_keys: tuple[str, ...] = ()
    if parquet_view:
        (
            agency_projection,
            agency_projection_missing_keys,
        ) = _agency_projection_from_loaded_releases(releases)
```

Add both values as keyword-only parameters through `_write_distribution()`.
Add `agency_projection` to `_write_candidate_distribution()`. Immediately
after `parquet.close()`, write the two derived tables:

```python
        if parquet is not None:
            parquet.close()
            if agency_projection is not None:
                write_agency_projection_tables(
                    parquet_tables,
                    agency_projection,
                )
```

Pass this exact metadata to `seal_atlas_parquet_view()`:

```python
            seal_atlas_parquet_view(
                candidate,
                staged_tables,
                sealed_view,
                expected_manifest_digest=_sha256_file(
                    candidate / "atlas-manifest.json"
                ),
                agency_projection=(
                    _agency_projection_manifest_metadata(
                        agency_projection,
                        agency_projection_missing_keys,
                    )
                ),
            )
```

A complete build emits 279 resolved and 52 unresolved rows. A bounded build
that omits any required roster emits neither table and records every missing
release key. It must never emit a partial projection.

## 5. Close and verify the expanded Parquet view

In `src/refspec/atlas/parquet_view.py`, bump `VIEW_SCHEMA_VERSION` and
`VIEW_IMPLEMENTATION_VERSION`. Import the projection table constants, schemas,
names, and path helper; also add `import pyarrow as pa`. Add
`"agencyProjection"` to
`_VIEW_MANIFEST_FIELDS`.

Add `agency_projection: Mapping[str, Any]` to
`atlas_parquet_view_manifest()` and `seal_atlas_parquet_view()`. Store a plain
copy as the top-level `agencyProjection` member. Before computing the manifest
digest, enforce:

```python
    if not isinstance(agency_projection, Mapping):
        raise AtlasParquetViewError(
            "agency projection metadata must be an object"
        )
    if agency_projection.get("status") == "emitted":
        if set(agency_projection) != {
            "status",
            "decision",
            "digest",
            "coverage",
        }:
            raise AtlasParquetViewError(
                "agency projection metadata fields differ"
            )
        coverage = agency_projection["coverage"]
        if not isinstance(coverage, Mapping):
            raise AtlasParquetViewError(
                "agency projection coverage must be an object"
            )
        if (
            agency_projection.get("decision") != "REF-038"
            or _DIGEST.fullmatch(str(agency_projection.get("digest"))) is None
            or counts.get(AGENCY_PROJECTION_ROLE)
            != coverage.get("resolved_value_count")
            or counts.get(AGENCY_PROJECTION_UNRESOLVED_ROLE)
            != coverage.get("unresolved_value_count")
            or coverage.get("source_value_count")
            != coverage.get("resolved_value_count")
            + coverage.get("unresolved_value_count")
        ):
            raise AtlasParquetViewError(
                "agency projection coverage differs from table rows"
            )
    elif agency_projection.get("status") == "notEmitted":
        if set(agency_projection) != {"status", "missingReleaseKeys"}:
            raise AtlasParquetViewError(
                "absent agency projection metadata fields differ"
            )
        if not agency_projection["missingReleaseKeys"]:
            raise AtlasParquetViewError(
                "absent agency projection names no missing release"
            )
    else:
        raise AtlasParquetViewError(
            "agency projection metadata has an unsupported status"
        )
```

Generalize `_staged_table_members()` with this exact table inventory. The two
projection files must appear together or both remain absent:

```python
    contracts: list[tuple[str, str, pa.Schema]] = [
        (
            role.value,
            table_relative_path(role),
            TABLE_SCHEMAS[role],
        )
        for role in CompactRecordRole
    ]
    derived_present = {
        role: _safe_path(
            staged,
            agency_projection_table_relative_path(role),
        ).is_file()
        for role in AGENCY_PROJECTION_TABLE_SCHEMAS
    }
    if len(set(derived_present.values())) != 1:
        raise AtlasParquetViewError(
            "agency projection tables must be emitted together"
        )
    if all(derived_present.values()):
        contracts.extend(
            (
                role,
                agency_projection_table_relative_path(role),
                schema,
            )
            for role, schema in AGENCY_PROJECTION_TABLE_SCHEMAS.items()
        )
```

Loop over `contracts` instead of `CompactRecordRole`, using each tuple's role,
path, and schema for schema checks and member descriptors. Apply the same
inventory in `verify_atlas_parquet_view()`:

```python
    schema_by_role = {
        role.value: TABLE_SCHEMAS[role] for role in CompactRecordRole
    }
    if manifest["agencyProjection"]["status"] == "emitted":
        schema_by_role.update(AGENCY_PROJECTION_TABLE_SCHEMAS)
    expected_roles = set(schema_by_role)
```

Replace `role = CompactRecordRole(member["role"])` with a lookup in
`schema_by_role`, and compare the Parquet file with that schema. Re-run the
metadata-and-count checks during verification; do not trust the sealer's first
pass. After reading the two projection tables, verify their logical content
against the recorded digest with the same canonical JSON algorithm used by
`AgencyProjection`:

```python
    if manifest["agencyProjection"]["status"] == "emitted":
        resolved = pq.read_table(
            _safe_path(
                directory,
                agency_projection_table_relative_path(
                    AGENCY_PROJECTION_ROLE
                ),
            )
        ).to_pylist()
        unresolved = pq.read_table(
            _safe_path(
                directory,
                agency_projection_table_relative_path(
                    AGENCY_PROJECTION_UNRESOLVED_ROLE
                ),
            )
        ).to_pylist()
        projection_digest = canonical_payload_sha256(
            {
                "rows": resolved,
                "unresolved": unresolved,
                "coverage": manifest["agencyProjection"]["coverage"],
            }
        )
        if projection_digest != manifest["agencyProjection"]["digest"]:
            raise AtlasParquetViewError(
                "agency projection logical-content digest differs"
            )
```

Add negative tests for one missing projection file, a missing mapping basis,
mutated evidence, changed coverage, changed projection digest, and a bounded
build that tries to emit a partial table pair. Add a determinism test that
seals twice from reordered release inputs and compares all two table bytes and
the view manifest bytes.

## 6. Producer pins and intentionally unchanged areas

Update the sibling producer-validation tests and generated source accounting
by these exact source deltas:

| Measure | Delta |
| --- | ---: |
| Releases | +1 |
| Entity resources | +331 |
| Preferred labels | +331 |
| Notations | +331 |
| Source records | +331 |
| Native `atlas:parentEntity` relations | +160 |
| Identifier rows | +0 |
| Cross-ring relations | +0 |

Do not add a `portfolio/` row. The existing
`regulations-gov-native-controls` descriptor already owns this source family.
Do not change the Atlas 3.1 RDF binding for the projection: REF-038 defines a
derived Parquet view, not new asserted Atlas statements. If a later decision
promotes these adjudications into the asserted graph, that change needs its
own binding rule and negative fixture.

Run the sibling job's source-fidelity, producer-validation, Parquet-view, and
full input checks after rebasing. Building the distribution remains a separate
owner-authorized operation.

## 7. Owner-ruling delta: asserted identity graph

This section supersedes sections 3 through 6 wherever they describe the 279/52
first-pass result or say that agency identity is not asserted. The owner has
confirmed that identity claims live in the asserted entity graph and that the
Parquet table is only a projection of those claims. The implementation is in
`src/refspec/atlas/v3_registry_alignments_entity.py` and
`src/refspec/atlas/agency_projection.py`; do not reimplement its matching in the
producer or Parquet layer.

### Load and publish the mapping release

After loading the five roster releases, call
`load_regulations_gov_agency_identity_mapping_release(rosters)`. Add the result
to the producer's complete mapping-release inventory under key
`regulations-gov-agency-identity-2026-08-16`. The complete construction adds:

| Measure | Delta |
| --- | ---: |
| Mapping releases | +1 |
| `atlas:sameEntityAs` assertions | +321 |
| Mapping evidence records | +642 |
| Candidate decisions in release metadata | +331 |
| Inverse assertions | +0 |
| Subunit assertions | +0 |
| Scalar confidence fields | +0 |

The 321 mappings run from a regulations.gov resource to one Federal Register,
eCFR, or Federal Hierarchy resource. Preserve that direction and emit no
inverse. The mapping release owns the identity decision; its metadata owns the
ten abstentions. The entity-ring policy must continue to admit exactly
`atlas:sameEntityAs` for mapping assertions. Keep the REF-030, REF-031, and
REF-032 refusal checks and the identifier tripwire over the added release.

The asserted source needs its own `mappingAssertionsOnly` portfolio descriptor
and generated catalog/index/reference entries for resource id
`regulations-gov-agency-identity`. This requirement supersedes section 6's
instruction not to add a portfolio row. Add the binding rule and negative
fixture needed to serialize these asserted mappings. Do not mint inverse
statements. The `MKU` candidate accounting names a duplicate-name Federal
Hierarchy sub-tier; it is deliberately not emitted because the entity ring has
no subunit mapping predicate.

### Derive the projection from the loaded mapping release

Change the producer call to:

```python
build_agency_projection(rosters, agency_identity_mapping_release)
```

The complete build must emit 321 projection rows and ten unresolved rows. A
bounded build that lacks any roster or the identity mapping release emits
neither projection table and reports every missing release key. It must never
fall back to acronym or name matching at projection time.

The parity gate must compare the data, not only the counts:

- projection `(source_org, relation, org)` triples equal all 321 graph
  assertions after `source_org` is read from each source evidence record;
- projection source values equal the 321 metadata decisions marked `adopted`;
- unresolved source values equal the ten metadata decisions marked `abstained`;
- the sets are disjoint and account for all 331 regulations.gov ids.

The expected complete coverage is 321 resolved, ten unresolved, 159 rows with a
target-roster parent, and 321 aggregate projection evidence records. The
mapping release separately carries two publisher evidence records per
assertion, for 642 total.

### Apply the Parquet schema delta

Keep the two table roles from section 3, but amend its schemas to match the
current derived records:

- add non-null `publisher_name: string` to
  `_AGENCY_PROJECTION_SOURCE_RECORD`;
- add non-null `reasoning: string` to `_AGENCY_PROJECTION_EVIDENCE`;
- add non-null `reasoning: string` to the unresolved table;
- add nullable `closest_non_adopted_candidate`, a struct with non-null
  `resource`, `publisherName`, and `reason` strings, to the unresolved table.

Remove duplicated schema fields shown in the older illustrative snippets before
applying them. The table writer, view sealer, and verifier must compare the
expanded logical rows exactly. Retain the content-derived projection digest and
the all-or-none two-table rule.

### Integration verification

Update producer totals for both the +331-resource roster delta in section 6 and
the asserted mapping delta above. Add or update negative fixtures for a missing
publisher name, incomplete E4 evidence, an adoption without an assertion, an
unsupported entity-ring predicate, an inverse assertion, identifier emission,
and a partial Parquet pair. Then run the sibling job's source-fidelity,
producer-validation, binding, Parquet-view, and full-input checks. Do not build
the distribution as part of this handoff.

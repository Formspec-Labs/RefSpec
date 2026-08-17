"""The one Atlas Parquet table contract: schema, projection, and writer.

Two producers write these tables and one verifier reads them, so all three
share this module.  The Atlas builder emits the tables straight from its
in-memory graph while it walks that graph for the RDF and compact packs;
``refspec.atlas.parquet_view`` still derives them from authenticated compact
packs for a distribution that was built before the builder emitted its own.
One schema, one projection, one writer configuration -- a second copy of any
of the three is a drift class, and the verifier compares against the same
objects the writers used.

Losslessness is the contract, not an aspiration.  Every field a compact
logical record carries becomes a column, which is why the four remaining
``rkaf`` warrant axes and the optional ``rkaf:basedOnAttestation`` referent are
here: a projection that dropped them could not detect the exact defect class
that produced the warrant bug (a binding whose axes match no sanctioned
branch), and the view manifest's ``logicalRecordsPreserved`` claim would be
false.  ``native_payload`` is the ``atlas:nativePayload`` literal's exact
lexical bytes -- one encoder, ``release_model.canonical_native_json_bytes`` --
so proving the column against RDF is two byte comparisons rather than a
re-encoding that could agree with the emitter by sharing its bug.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from refspec.atlas.agency_projection import AgencyProjection
from refspec.atlas.compact_pack import CompactRecordRole, compact_record_fields
from refspec.atlas.parquet_artifact import arrow_schema_sha256, file_sha256
from refspec.release_model import canonical_native_json_bytes

ROW_GROUP_SIZE = 50_000
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 9
PARQUET_VERSION = "2.6"
DATA_PAGE_VERSION = "2.0"
TABLE_MEDIA_TYPE = "application/vnd.apache.parquet"
TABLE_DIRECTORY = "tables"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class AtlasParquetTableError(ValueError):
    """One logical record cannot be projected onto the Parquet contract."""


def _digest_bytes(value: object, label: str) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise AtlasParquetTableError(f"{label} must be a lowercase SHA-256 digest")
    return bytes.fromhex(value.removeprefix("sha256:"))


def _binary_digest_field(name: str, *, nullable: bool = True) -> pa.Field:
    return pa.field(name, pa.binary(32), nullable=nullable)


# Low-cardinality string columns are dictionary-encoded on disk by the writer's
# `use_dictionary=True`, so the four warrant axes cost almost nothing: measured
# on the 560k-row evidence-binding table the five added columns are +99 KB,
# +0.12% of the view.
TABLE_SCHEMAS: Mapping[CompactRecordRole, pa.Schema] = {
    CompactRecordRole.RESOURCE: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("release", pa.string(), nullable=False),
            pa.field("scheme", pa.string(), nullable=False),
            pa.field("semantic_ring", pa.string(), nullable=False),
            pa.field("resource_profile", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            pa.field("definition", pa.string()),
            pa.field("notes", pa.list_(pa.string())),
            pa.field("notations", pa.list_(pa.string())),
            pa.field("record_status", pa.string()),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.LABEL: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("resource", pa.string(), nullable=False),
            pa.field("label_role", pa.string(), nullable=False),
            pa.field("value", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("release", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.STATEMENT: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("statement_type", pa.string(), nullable=False),
            pa.field("subject", pa.string(), nullable=False),
            pa.field("predicate", pa.string(), nullable=False),
            pa.field("object", pa.string(), nullable=False),
            pa.field("source_release", pa.string(), nullable=False),
            pa.field("target_release", pa.string(), nullable=False),
            pa.field("policy", pa.string(), nullable=False),
            pa.field("asserted_at", pa.string(), nullable=False),
            _binary_digest_field("assertion_identity_digest", nullable=False),
            pa.field("semantic_ring", pa.string()),
            pa.field("source_ring", pa.string()),
            pa.field("target_ring", pa.string()),
            pa.field("supersedes_assertion", pa.string()),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.EVIDENCE_BINDING: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("statement", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            _binary_digest_field("evidence_source_digest", nullable=False),
            pa.field("attestor", pa.string(), nullable=False),
            pa.field("attestor_kind", pa.string(), nullable=False),
            pa.field("assertion_origin", pa.string(), nullable=False),
            pa.field("epistemic_basis", pa.string(), nullable=False),
            pa.field("evidence_role", pa.string(), nullable=False),
            pa.field("evidentiary_function", pa.string(), nullable=False),
            pa.field("based_on_attestation", pa.string()),
            pa.field("decision", pa.string(), nullable=False),
            pa.field("attested_at", pa.string(), nullable=False),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.SOURCE_RECORD: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("source_release", pa.string(), nullable=False),
            _binary_digest_field("source_digest", nullable=False),
            pa.field("source_locator", pa.string(), nullable=False),
            pa.field("native_payload", pa.large_binary(), nullable=False),
            pa.field("represents_resource", pa.string()),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.RELEASE: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("release_type", pa.string(), nullable=False),
            pa.field("identifier", pa.string(), nullable=False),
            pa.field("issued", pa.string(), nullable=False),
            _binary_digest_field("source_digest"),
            pa.field("source_locator", pa.string()),
            pa.field("resource_profile", pa.string()),
            pa.field("semantic_ring", pa.string()),
            pa.field("scheme", pa.string()),
            pa.field("membership_mode", pa.string()),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.IDENTIFIER: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("identifier_value", pa.string(), nullable=False),
            pa.field("identifier_scheme", pa.string(), nullable=False),
            pa.field("identifies", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            _binary_digest_field("content_digest"),
        ]
    ),
    CompactRecordRole.LIFECYCLE_EVENT: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("applies_to", pa.string(), nullable=False),
            pa.field("lifecycle_event_kind", pa.string(), nullable=False),
            pa.field("effective_date", pa.string(), nullable=False),
            pa.field("source_records", pa.list_(pa.string()), nullable=False),
            pa.field("from_release", pa.string()),
            pa.field("to_release", pa.string()),
            _binary_digest_field("content_digest"),
        ]
    ),
}

TABLE_NAMES: Mapping[CompactRecordRole, str] = {
    CompactRecordRole.RESOURCE: "resources.parquet",
    CompactRecordRole.LABEL: "labels.parquet",
    CompactRecordRole.STATEMENT: "statements.parquet",
    CompactRecordRole.EVIDENCE_BINDING: "evidence-bindings.parquet",
    CompactRecordRole.SOURCE_RECORD: "source-records.parquet",
    CompactRecordRole.RELEASE: "releases.parquet",
    CompactRecordRole.IDENTIFIER: "identifiers.parquet",
    CompactRecordRole.LIFECYCLE_EVENT: "lifecycle-events.parquet",
}

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
        pa.field("publisher_name", pa.string(), nullable=False),
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
        pa.field("reasoning", pa.string(), nullable=False),
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
_AGENCY_PROJECTION_CLOSEST_CANDIDATE = pa.struct(
    [
        pa.field("resource", pa.string(), nullable=False),
        pa.field("publisherName", pa.string(), nullable=False),
        pa.field("reason", pa.string(), nullable=False),
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
            pa.field("reasoning", pa.string(), nullable=False),
            pa.field(
                "candidate_resources",
                pa.list_(pa.string()),
                nullable=False,
            ),
            pa.field(
                "closest_non_adopted_candidate",
                _AGENCY_PROJECTION_CLOSEST_CANDIDATE,
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
    """Return one REF-038 table's view-relative path."""

    return f"{TABLE_DIRECTORY}/{AGENCY_PROJECTION_TABLE_NAMES[role]}"


def write_agency_projection_tables(
    output: Path,
    projection: AgencyProjection,
) -> None:
    """Write and round-trip-check the two all-or-none REF-038 view tables."""

    rows_by_role = {
        AGENCY_PROJECTION_ROLE: [row.to_dict() for row in projection.rows],
        AGENCY_PROJECTION_UNRESOLVED_ROLE: [
            row.to_dict() for row in projection.unresolved
        ],
    }
    directory = output / TABLE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
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


def table_relative_path(role: CompactRecordRole) -> str:
    """Return the view-relative path one role's table always occupies."""

    return f"{TABLE_DIRECTORY}/{TABLE_NAMES[role]}"


def column_name(field: str) -> str:
    """Return the one column a compact record field is carried in."""

    return re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()


def unpreserved_record_fields() -> dict[str, list[str]]:
    """Name every compact record field no Parquet column carries, by role.

    The mapping is mechanical -- a compact field's column is its name in
    snake case -- so this is a derivation, not a second list to maintain: a
    field added to the compact record schema with no column appears here, and
    a column with no compact field appears under ``"+<role>"``.
    """

    gaps: dict[str, list[str]] = {}
    for role in CompactRecordRole:
        expected = {column_name(field) for field in compact_record_fields(role)}
        columns = set(TABLE_SCHEMAS[role].names)
        if missing := sorted(expected - columns):
            gaps[role.value] = missing
        if extra := sorted(columns - expected):
            gaps["+" + role.value] = extra
    return gaps


def logical_records_preserved() -> bool:
    """Is the Parquet projection lossless for every compact record field?

    The view manifest publishes this as a status claim.  It is computed, never
    asserted: until the four remaining warrant axes and
    ``rkaf:basedOnAttestation`` became columns this returned False, and the
    manifest said True anyway.
    """

    return not unpreserved_record_fields()


def parquet_row(role: CompactRecordRole, row: Mapping[str, Any]) -> dict[str, Any]:
    """Project one compact logical record onto its typed Parquet row.

    Lossless by construction: every field the compact record schema declares
    for this role appears here, absent optional fields as nulls.
    """

    common = {"id": row["id"], "content_digest": _digest_bytes(row.get("contentDigest"), "contentDigest")}
    if role is CompactRecordRole.RESOURCE:
        return {
            **common,
            "release": row["release"],
            "scheme": row["scheme"],
            "semantic_ring": row["semanticRing"],
            "resource_profile": row["resourceProfile"],
            "source_record": row["sourceRecord"],
            "definition": row.get("definition"),
            "notes": row.get("notes"),
            "notations": row.get("notations"),
            "record_status": row.get("recordStatus"),
        }
    if role is CompactRecordRole.LABEL:
        return {
            **common,
            "resource": row["resource"],
            "label_role": row["labelRole"],
            "value": row["value"],
            "language": row["language"],
            "release": row["release"],
            "source_record": row["sourceRecord"],
        }
    if role is CompactRecordRole.STATEMENT:
        return {
            **common,
            "statement_type": row["statementType"],
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "source_release": row["sourceRelease"],
            "target_release": row["targetRelease"],
            "policy": row["policy"],
            "asserted_at": row["assertedAt"],
            "assertion_identity_digest": _digest_bytes(row["assertionIdentityDigest"], "assertionIdentityDigest"),
            "semantic_ring": row.get("semanticRing"),
            "source_ring": row.get("sourceRing"),
            "target_ring": row.get("targetRing"),
            "supersedes_assertion": row.get("supersedesAssertion"),
        }
    if role is CompactRecordRole.EVIDENCE_BINDING:
        return {
            **common,
            "statement": row["statement"],
            "source_record": row["sourceRecord"],
            "evidence_source_digest": _digest_bytes(row["evidenceSourceDigest"], "evidenceSourceDigest"),
            "attestor": row["attestor"],
            "attestor_kind": row["attestorKind"],
            "assertion_origin": row["assertionOrigin"],
            "epistemic_basis": row["epistemicBasis"],
            "evidence_role": row["evidenceRole"],
            "evidentiary_function": row["evidentiaryFunction"],
            "based_on_attestation": row.get("basedOnAttestation"),
            "decision": row["decision"],
            "attested_at": row["attestedAt"],
        }
    if role is CompactRecordRole.SOURCE_RECORD:
        return {
            **common,
            "source_release": row["sourceRelease"],
            "source_digest": _digest_bytes(row["sourceDigest"], "sourceDigest"),
            "source_locator": row["sourceLocator"],
            "native_payload": canonical_native_json_bytes(row["nativePayload"]),
            "represents_resource": row.get("representsResource"),
        }
    if role is CompactRecordRole.RELEASE:
        return {
            **common,
            "release_type": row["releaseType"],
            "identifier": row["identifier"],
            "issued": row["issued"],
            "source_digest": _digest_bytes(row.get("sourceDigest"), "sourceDigest"),
            "source_locator": row.get("sourceLocator"),
            "resource_profile": row.get("resourceProfile"),
            "semantic_ring": row.get("semanticRing"),
            "scheme": row.get("scheme"),
            "membership_mode": row.get("membershipMode"),
        }
    if role is CompactRecordRole.IDENTIFIER:
        return {
            **common,
            "identifier_value": row["identifierValue"],
            "identifier_scheme": row["identifierScheme"],
            "identifies": row["identifies"],
            "source_record": row["sourceRecord"],
        }
    if role is CompactRecordRole.LIFECYCLE_EVENT:
        return {
            **common,
            "applies_to": row["appliesTo"],
            "lifecycle_event_kind": row["lifecycleEventKind"],
            "effective_date": row["effectiveDate"],
            "source_records": row["sourceRecords"],
            "from_release": row.get("fromRelease"),
            "to_release": row.get("toRelease"),
        }
    raise AtlasParquetTableError(f"unsupported compact record role {role}")


class AtlasParquetTableWriter:
    """Write the eight typed tables, streaming, one row group at a time.

    Records may arrive in any interleaving of roles, so every writer stays
    open until :meth:`close`.  Memory is bounded by one row group per role,
    never by the size of a table -- the builder streams 32M quads' worth of
    logical records through this without materializing them.
    """

    def __init__(self, output: Path) -> None:
        self._output = output
        self._directory = output / TABLE_DIRECTORY
        self._directory.mkdir(parents=True, exist_ok=True)
        self._buffers: dict[CompactRecordRole, list[dict[str, Any]]] = {role: [] for role in CompactRecordRole}
        self._counts: dict[CompactRecordRole, int] = dict.fromkeys(CompactRecordRole, 0)
        self._wrote: dict[CompactRecordRole, bool] = dict.fromkeys(CompactRecordRole, False)
        self._writers: dict[CompactRecordRole, pq.ParquetWriter] = {
            role: pq.ParquetWriter(
                self._directory / TABLE_NAMES[role],
                TABLE_SCHEMAS[role],
                compression=COMPRESSION,
                compression_level=COMPRESSION_LEVEL,
                use_dictionary=True,
                write_statistics=True,
                version=PARQUET_VERSION,
                data_page_version=DATA_PAGE_VERSION,
            )
            for role in CompactRecordRole
        }
        self._closed = False

    def add(self, role: CompactRecordRole, record: Mapping[str, Any]) -> None:
        """Buffer one compact logical record; flush when a row group fills."""

        if self._closed:
            raise AtlasParquetTableError("Atlas Parquet table writer is closed")
        buffer = self._buffers[role]
        buffer.append(parquet_row(role, record))
        if len(buffer) >= ROW_GROUP_SIZE:
            self._flush(role)

    def extend(self, role: CompactRecordRole, records: Iterable[Mapping[str, Any]]) -> None:
        for record in records:
            self.add(role, record)

    def _flush(self, role: CompactRecordRole) -> None:
        buffer = self._buffers[role]
        if not buffer:
            return
        schema = TABLE_SCHEMAS[role]
        self._writers[role].write_table(
            pa.Table.from_pylist(buffer, schema=schema),
            row_group_size=ROW_GROUP_SIZE,
        )
        self._counts[role] += len(buffer)
        self._wrote[role] = True
        buffer.clear()

    def close(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Finish every table and return its member descriptor and counts."""

        if self._closed:
            raise AtlasParquetTableError("Atlas Parquet table writer is closed")
        members: list[dict[str, Any]] = []
        try:
            for role in CompactRecordRole:
                self._flush(role)
                if not self._wrote[role]:
                    self._writers[role].write_table(TABLE_SCHEMAS[role].empty_table())
        finally:
            self._closed = True
            for writer in self._writers.values():
                writer.close()
        for role in CompactRecordRole:
            relative = table_relative_path(role)
            target = self._directory / TABLE_NAMES[role]
            members.append(
                {
                    "byteLength": target.stat().st_size,
                    "mediaType": TABLE_MEDIA_TYPE,
                    "path": relative,
                    "role": role.value,
                    "rowCount": self._counts[role],
                    # Pin the schema as serialized by Parquet. PyArrow restores the
                    # same logical schema but may normalize nested-field metadata.
                    "schemaDigest": arrow_schema_sha256(pq.ParquetFile(target).schema_arrow),
                    "sha256": file_sha256(target),
                }
            )
        return members, {role.value: self._counts[role] for role in CompactRecordRole}

    def __enter__(self) -> AtlasParquetTableWriter:
        return self

    def __exit__(self, *_: object) -> None:
        if not self._closed:
            self._closed = True
            for writer in self._writers.values():
                writer.close()


def write_parquet_tables(
    output: Path,
    records_by_role: Iterable[tuple[CompactRecordRole, Sequence[Mapping[str, Any]]]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Write every table from an iterable of (role, records) batches."""

    writer = AtlasParquetTableWriter(output)
    try:
        for role, records in records_by_role:
            writer.extend(role, records)
        return writer.close()
    except BaseException:
        writer.__exit__()
        raise


__all__ = [
    "AGENCY_PROJECTION_ROLE",
    "AGENCY_PROJECTION_TABLE_NAMES",
    "AGENCY_PROJECTION_TABLE_SCHEMAS",
    "AGENCY_PROJECTION_UNRESOLVED_ROLE",
    "COMPRESSION",
    "COMPRESSION_LEVEL",
    "DATA_PAGE_VERSION",
    "PARQUET_VERSION",
    "ROW_GROUP_SIZE",
    "TABLE_MEDIA_TYPE",
    "TABLE_NAMES",
    "TABLE_SCHEMAS",
    "AtlasParquetTableError",
    "AtlasParquetTableWriter",
    "agency_projection_table_relative_path",
    "column_name",
    "logical_records_preserved",
    "parquet_row",
    "table_relative_path",
    "unpreserved_record_fields",
    "write_agency_projection_tables",
    "write_parquet_tables",
]

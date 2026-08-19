"""Compact an authenticated Atlas Parquet view for search and graph browsing.

The compact view preserves graph facts, labels, statement provenance, source
locators, and stable identifiers. It replaces repeated references with
deterministic 32-byte keys and omits only source-native payload bodies. The
full logical-record view and canonical RDF remain the audit sources.
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_artifact import (
    PARQUET_MEMBER_FIELDS,
    arrow_schema_sha256,
    artifact_file_paths,
    canonical_payload_sha256,
    file_sha256,
    normalize_sha256_prefix,
)
from refspec.atlas.parquet_tables import (
    AGENCY_PROJECTION_ROLE,
    AGENCY_PROJECTION_TABLE_SCHEMAS,
    AGENCY_PROJECTION_UNRESOLVED_ROLE,
    DERIVED_RELATION_ROLE,
    DERIVED_RELATION_TABLE_SCHEMA,
    agency_projection_table_relative_path,
    derived_relation_table_relative_path,
)
from refspec.atlas.parquet_view import verify_atlas_parquet_view
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes

SEARCH_VIEW_RECORD_TYPE = "AtlasParquetSearchViewManifest"
SEARCH_VIEW_SCHEMA_VERSION = "1.1"
SEARCH_VIEW_ID_PREFIX = "urn:ref:atlas-parquet-search-view:"
SEARCH_VIEW_IMPLEMENTATION = "refspec.atlas.parquet_search_view"
SEARCH_VIEW_IMPLEMENTATION_VERSION = "1.3"
MANIFEST_FILE = "search-view-manifest.json"
ROW_GROUP_SIZE = 50_000
COMPRESSION_LEVEL = 19

#: REF-038's agency-projection tables are consumer-projection members, not
#: one of the eight closed logical-record roles `CompactRecordRole` names --
#: that enum is the closed compact-record contract and stays that way. They
#: are modeled as a separate, optional member category: zero or both may
#: appear (the full view already enforces "emitted together"), each carried
#: through compaction by verbatim byte copy -- their digests come from the
#: verified full view, never recomputed -- rather than by the per-role
#: `_write_role` transform every compact record role goes through.
PROJECTION_MEMBER_ROLES = frozenset({AGENCY_PROJECTION_ROLE, AGENCY_PROJECTION_UNRESOLVED_ROLE})

#: REF-042's derived-relations table rides the same rails: a separate,
#: optional member carried by verbatim byte copy with its digest forwarded
#: from the verified full view. It is a single table with no pair rule --
#: present or absent, exactly as the full view's verified manifest declares.
#: The manifest contract does not change (no new field; one more admitted
#: optional member role), so the schema version stays 1.1; only the
#: implementation version moves.
_VERBATIM_TABLE_SCHEMAS: Mapping[str, pa.Schema] = {
    **AGENCY_PROJECTION_TABLE_SCHEMAS,
    DERIVED_RELATION_ROLE: DERIVED_RELATION_TABLE_SCHEMA,
}
_VERBATIM_RELATIVE_PATHS: Mapping[str, str] = {
    AGENCY_PROJECTION_ROLE: agency_projection_table_relative_path(AGENCY_PROJECTION_ROLE),
    AGENCY_PROJECTION_UNRESOLVED_ROLE: agency_projection_table_relative_path(
        AGENCY_PROJECTION_UNRESOLVED_ROLE
    ),
    DERIVED_RELATION_ROLE: derived_relation_table_relative_path(),
}

_PREFIXES = {
    "assertion": "urn:ref:atlas-assertion:",
    "evidence": "urn:ref:atlas-evidence:",
    "identifier": "urn:ref:atlas-identifier:",
    "label": "urn:ref:atlas-label:",
    "policy": "urn:ref:atlas-policy:",
    "sourceRecord": "urn:ref:atlas-source-record:",
}
_OMITTED_FIELDS = (
    "EvidenceBinding.id",
    "Label.contentDigest",
    "Resource.contentDigest",
    "SourceRecord.contentDigest",
    "SourceRecord.nativePayload",
    "Statement.assertionIdentityDigest",
    "Statement.contentDigest",
    "Identifier.contentDigest",
    "LifecycleEvent.contentDigest",
    "Release.contentDigest",
)
_MANIFEST_FIELDS = frozenset(
    {
        "canonicalPayloadDigest",
        "construction",
        "counts",
        "input",
        "members",
        "recordType",
        "schemaVersion",
        "status",
        "viewId",
    }
)
_MISSING_LABEL_ID = (
    f"search view {SEARCH_VIEW_SCHEMA_VERSION} retains the canonical Label.id "
    "(REF-025); the Label member omits it"
)


class AtlasParquetSearchViewError(ValueError):
    """The full view or compact search view is unsafe or inconsistent."""


def _safe_member_path(directory: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise AtlasParquetSearchViewError("compact view member path must be text")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise AtlasParquetSearchViewError(f"compact view member path is unsafe: {relative!r}")
    return directory.joinpath(*parsed.parts)


def _suffix(value: str | None, prefix_name: str) -> bytes | None:
    if value is None:
        return None
    prefix = _PREFIXES[prefix_name]
    if not value.startswith(prefix):
        raise AtlasParquetSearchViewError(f"{prefix_name} identifier has an unsupported prefix: {value}")
    suffix = value.removeprefix(prefix)
    if len(suffix) != 64:
        raise AtlasParquetSearchViewError(f"{prefix_name} identifier has an unsupported digest suffix")
    try:
        return bytes.fromhex(suffix)
    except ValueError as error:
        raise AtlasParquetSearchViewError(f"{prefix_name} identifier has a non-hex digest suffix") from error


_B32 = pa.binary(32)
_SCHEMAS: Mapping[CompactRecordRole, pa.Schema] = {
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
            pa.field("semantic_ring", pa.string()),
            pa.field("source_ring", pa.string()),
            pa.field("target_ring", pa.string()),
            pa.field("supersedes_assertion", pa.string()),
        ]
    ),
    CompactRecordRole.EVIDENCE_BINDING: pa.schema(
        [
            pa.field("evidence_id", _B32, nullable=False),
            pa.field("statement", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
            pa.field("evidence_source_digest", _B32, nullable=False),
            pa.field("attestor", pa.string(), nullable=False),
            pa.field("evidence_role", pa.string(), nullable=False),
            pa.field("decision", pa.string(), nullable=False),
            pa.field("attested_at", pa.string(), nullable=False),
        ]
    ),
    CompactRecordRole.SOURCE_RECORD: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("source_release", pa.string(), nullable=False),
            pa.field("source_digest", _B32, nullable=False),
            pa.field("source_locator", pa.string(), nullable=False),
            pa.field("represents_resource", pa.string()),
        ]
    ),
    CompactRecordRole.RELEASE: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("release_type", pa.string(), nullable=False),
            pa.field("identifier", pa.string(), nullable=False),
            pa.field("issued", pa.string(), nullable=False),
            pa.field("source_digest", _B32),
            pa.field("source_locator", pa.string()),
            pa.field("resource_profile", pa.string()),
            pa.field("semantic_ring", pa.string()),
            pa.field("scheme", pa.string()),
            pa.field("membership_mode", pa.string()),
        ]
    ),
    CompactRecordRole.IDENTIFIER: pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("identifier_value", pa.string(), nullable=False),
            pa.field("identifier_scheme", pa.string(), nullable=False),
            pa.field("identifies", pa.string(), nullable=False),
            pa.field("source_record", pa.string(), nullable=False),
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
        ]
    ),
}

_DICTIONARIES = {
    CompactRecordRole.RESOURCE: ["scheme", "semantic_ring", "resource_profile", "record_status"],
    CompactRecordRole.LABEL: ["label_role", "language"],
    CompactRecordRole.STATEMENT: [
        "statement_type",
        "predicate",
        "semantic_ring",
        "source_ring",
        "target_ring",
    ],
    CompactRecordRole.EVIDENCE_BINDING: [
        "attestor",
        "evidence_role",
        "decision",
    ],
    CompactRecordRole.SOURCE_RECORD: [],
    CompactRecordRole.RELEASE: [
        "release_type",
        "resource_profile",
        "semantic_ring",
        "scheme",
        "membership_mode",
    ],
    CompactRecordRole.IDENTIFIER: ["identifier_scheme"],
    CompactRecordRole.LIFECYCLE_EVENT: ["lifecycle_event_kind"],
}


def _transform(role: CompactRecordRole, row: Mapping[str, Any]) -> dict[str, Any]:
    if role is CompactRecordRole.RESOURCE:
        return {key: value for key, value in row.items() if key != "content_digest"}
    if role is CompactRecordRole.LABEL:
        if not row.get("id"):
            raise AtlasParquetSearchViewError(_MISSING_LABEL_ID)
        return {key: value for key, value in row.items() if key != "content_digest"}
    if role is CompactRecordRole.STATEMENT:
        if _suffix(row["id"], "assertion") != row["assertion_identity_digest"]:
            raise AtlasParquetSearchViewError("statement identifier differs from assertionIdentityDigest")
        return {key: value for key, value in row.items() if key not in {"assertion_identity_digest", "content_digest"}}
    if role is CompactRecordRole.EVIDENCE_BINDING:
        evidence_id = _suffix(row["id"], "evidence")
        if evidence_id != row["content_digest"]:
            raise AtlasParquetSearchViewError("evidence identifier differs from contentDigest")
        return {
            "evidence_id": evidence_id,
            "statement": row["statement"],
            "source_record": row["source_record"],
            "evidence_source_digest": row["evidence_source_digest"],
            "attestor": row["attestor"],
            "evidence_role": row["evidence_role"],
            "decision": row["decision"],
            "attested_at": row["attested_at"],
        }
    if role is CompactRecordRole.SOURCE_RECORD:
        return {
            "id": row["id"],
            "source_release": row["source_release"],
            "source_digest": row["source_digest"],
            "source_locator": row["source_locator"],
            "represents_resource": row["represents_resource"],
        }
    if role is CompactRecordRole.RELEASE:
        return {key: value for key, value in row.items() if key != "content_digest"}
    if role is CompactRecordRole.IDENTIFIER:
        return {key: value for key, value in row.items() if key != "content_digest"}
    if role is CompactRecordRole.LIFECYCLE_EVENT:
        return {key: value for key, value in row.items() if key != "content_digest"}
    raise AssertionError(role)


def _write_role(source: Path, target: Path, role: CompactRecordRole) -> int:
    parquet = pq.ParquetFile(source)
    schema = _SCHEMAS[role]
    writer = pq.ParquetWriter(
        target,
        schema,
        compression="zstd",
        compression_level=COMPRESSION_LEVEL,
        use_dictionary=_DICTIONARIES[role],
        write_statistics=True,
        version="2.6",
        data_page_version="2.0",
    )
    count = 0
    try:
        for batch in parquet.iter_batches(batch_size=ROW_GROUP_SIZE):
            rows = [_transform(role, row) for row in batch.to_pylist()]
            writer.write_table(pa.Table.from_pylist(rows, schema=schema), row_group_size=ROW_GROUP_SIZE)
            count += len(rows)
        if count == 0:
            writer.write_table(schema.empty_table())
    finally:
        writer.close()
    return count


def build_atlas_parquet_search_view(
    full_view: Path,
    output: Path,
    *,
    expected_manifest_digest: str,
) -> dict[str, Any]:
    """Build one immutable compact search view from a verified full view."""

    if output.is_symlink() or output.exists():
        raise AtlasParquetSearchViewError(f"refusing to replace existing output: {output}")
    full_manifest = verify_atlas_parquet_view(
        full_view,
        expected_manifest_digest=expected_manifest_digest,
    )
    # The full view may also ship REF-038's agency-projection tables and
    # REF-042's derived-relations table, carried here as separate optional
    # member categories (see PROJECTION_MEMBER_ROLES and
    # _VERBATIM_TABLE_SCHEMAS).
    by_role: dict[CompactRecordRole, dict[str, Any]] = {}
    verbatim_members: dict[str, dict[str, Any]] = {}
    for member in full_manifest["members"]:
        if member["role"] in _VERBATIM_TABLE_SCHEMAS:
            verbatim_members[member["role"]] = member
        else:
            by_role[CompactRecordRole(member["role"])] = member
    projection_seen = {
        role for role in verbatim_members if role in PROJECTION_MEMBER_ROLES
    }
    if projection_seen and projection_seen != PROJECTION_MEMBER_ROLES:
        raise AtlasParquetSearchViewError(
            "agency projection tables must be carried through together"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        table_root = temporary / "tables"
        table_root.mkdir()
        members = []
        counts = {}
        for role in CompactRecordRole:
            source = full_view / by_role[role]["path"]
            relative = f"tables/{by_role[role]['path'].split('/')[-1]}"
            target = temporary / relative
            row_count = _write_role(source, target, role)
            counts[role.value] = row_count
            if row_count != by_role[role]["rowCount"]:
                raise AtlasParquetSearchViewError(f"{role.value} row count differs from the full view")
            stored_schema = pq.ParquetFile(target).schema_arrow
            members.append(
                {
                    "byteLength": target.stat().st_size,
                    "mediaType": "application/vnd.apache.parquet",
                    "path": relative,
                    "role": role.value,
                    "rowCount": row_count,
                    "schemaDigest": arrow_schema_sha256(stored_schema),
                    "sha256": file_sha256(target),
                }
            )
        for role, relative in _VERBATIM_RELATIVE_PATHS.items():
            source_member = verbatim_members.get(role)
            if source_member is None:
                continue
            source = full_view / source_member["path"]
            target = temporary / relative
            shutil.copyfile(source, target)
            if target.stat().st_size != source_member["byteLength"] or file_sha256(target) != source_member["sha256"]:
                raise AtlasParquetSearchViewError(f"optional table copy differs from the full view: {role}")
            copied_schema = pq.ParquetFile(target).schema_arrow
            if (
                copied_schema != _VERBATIM_TABLE_SCHEMAS[role]
                or arrow_schema_sha256(copied_schema) != source_member["schemaDigest"]
            ):
                raise AtlasParquetSearchViewError(f"optional table schema differs from the full view: {role}")
            counts[role] = source_member["rowCount"]
            members.append(
                {
                    "byteLength": source_member["byteLength"],
                    "mediaType": source_member["mediaType"],
                    "path": relative,
                    "role": role,
                    "rowCount": source_member["rowCount"],
                    "schemaDigest": source_member["schemaDigest"],
                    "sha256": source_member["sha256"],
                }
            )
        construction = {
            "compression": "zstd",
            "compressionLevel": COMPRESSION_LEVEL,
            "implementation": SEARCH_VIEW_IMPLEMENTATION,
            "implementationVersion": SEARCH_VIEW_IMPLEMENTATION_VERSION,
            "parquetVersion": "2.6",
            "pyarrowVersion": importlib.metadata.version("pyarrow"),
            "referenceEncoding": "nativeTextWithSelectiveParquetDictionaries",
            "rowGroupSize": ROW_GROUP_SIZE,
        }
        input_pin = {
            "atlas": full_manifest["input"],
            "fullViewId": full_manifest["viewId"],
            "fullViewManifestSha256": normalize_sha256_prefix(expected_manifest_digest),
            "fullViewPayloadDigest": full_manifest["canonicalPayloadDigest"],
        }
        identity = canonical_payload_sha256({"construction": construction, "input": input_pin})
        manifest: dict[str, Any] = {
            "construction": construction,
            "counts": counts,
            "input": input_pin,
            "members": members,
            "recordType": SEARCH_VIEW_RECORD_TYPE,
            "schemaVersion": SEARCH_VIEW_SCHEMA_VERSION,
            "status": {
                "canonicalAtlas": False,
                "consumerViewOnly": True,
                "expansion": "not_used",
                "graphFactsPreserved": True,
                "logicalRecordsPreserved": False,
                "omittedFields": list(_OMITTED_FIELDS),
            },
            "viewId": SEARCH_VIEW_ID_PREFIX + identity.removeprefix("sha256:"),
        }
        manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
        (temporary / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
        verify_atlas_parquet_search_view(
            temporary,
            expected_manifest_digest=file_sha256(temporary / MANIFEST_FILE),
        )
        os.rename(temporary, output)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_atlas_parquet_search_view(
    directory: Path,
    *,
    expected_manifest_digest: str,
) -> dict[str, Any]:
    """Verify closed membership, schemas, counts, and exact compact-view bytes."""

    if directory.is_symlink() or not directory.is_dir():
        raise AtlasParquetSearchViewError("compact Atlas view must be a regular directory")
    expected = normalize_sha256_prefix(expected_manifest_digest)
    manifest_path = directory / MANIFEST_FILE
    if manifest_path.is_symlink() or not manifest_path.is_file() or file_sha256(manifest_path) != expected:
        raise AtlasParquetSearchViewError("compact view manifest bytes differ from the external pin")
    try:
        import json

        manifest = json.loads(manifest_path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AtlasParquetSearchViewError("compact view manifest is invalid JSON") from error
    if manifest_path.read_bytes() != canonical_json_bytes(manifest):
        raise AtlasParquetSearchViewError("compact view manifest is not canonical JSON")
    if set(manifest) != _MANIFEST_FIELDS:
        raise AtlasParquetSearchViewError("compact view manifest fields are unsupported")
    payload = dict(manifest)
    actual_digest = payload.pop("canonicalPayloadDigest", None)
    if actual_digest != canonical_payload_sha256(payload):
        raise AtlasParquetSearchViewError("compact view manifest payload digest differs")
    if (
        manifest.get("recordType") != SEARCH_VIEW_RECORD_TYPE
        or manifest.get("schemaVersion") != SEARCH_VIEW_SCHEMA_VERSION
    ):
        raise AtlasParquetSearchViewError(
            f"compact view type or version is unsupported: expected schema version {SEARCH_VIEW_SCHEMA_VERSION}"
        )
    if manifest.get("status") != {
        "canonicalAtlas": False,
        "consumerViewOnly": True,
        "expansion": "not_used",
        "graphFactsPreserved": True,
        "logicalRecordsPreserved": False,
        "omittedFields": list(_OMITTED_FIELDS),
    }:
        raise AtlasParquetSearchViewError("compact view status is unsupported")
    expected_files = {MANIFEST_FILE}
    counts = {}
    seen: set[CompactRecordRole] = set()
    seen_verbatim_roles: set[str] = set()
    for member in manifest["members"]:
        if set(member) != PARQUET_MEMBER_FIELDS:
            raise AtlasParquetSearchViewError("compact view member fields are unsupported")
        member_role = member["role"]
        is_verbatim = member_role in _VERBATIM_TABLE_SCHEMAS
        if is_verbatim:
            if member_role in seen_verbatim_roles:
                raise AtlasParquetSearchViewError("compact view repeats a table role")
            seen_verbatim_roles.add(member_role)
            schema = _VERBATIM_TABLE_SCHEMAS[member_role]
        else:
            role = CompactRecordRole(member_role)
            if role in seen:
                raise AtlasParquetSearchViewError("compact view repeats a table role")
            seen.add(role)
            schema = _SCHEMAS[role]
        path = _safe_member_path(directory, member["path"])
        expected_files.add(member["path"])
        if path.is_symlink() or not path.is_file():
            raise AtlasParquetSearchViewError(f"compact view member is missing or unsafe: {member['path']}")
        if path.stat().st_size != member["byteLength"] or file_sha256(path) != member["sha256"]:
            raise AtlasParquetSearchViewError(f"compact view member bytes differ: {member['path']}")
        parquet = pq.ParquetFile(path)
        if not is_verbatim and role is CompactRecordRole.LABEL and "id" not in parquet.schema_arrow.names:
            raise AtlasParquetSearchViewError(f"{_MISSING_LABEL_ID}: {member['path']}")
        if parquet.schema_arrow != schema or arrow_schema_sha256(parquet.schema_arrow) != member["schemaDigest"]:
            raise AtlasParquetSearchViewError(f"compact view schema differs: {member['path']}")
        if parquet.metadata.num_rows != member["rowCount"]:
            raise AtlasParquetSearchViewError(f"compact view row count differs: {member['path']}")
        counts[member_role if is_verbatim else role.value] = parquet.metadata.num_rows
    if seen != set(CompactRecordRole) or counts != manifest["counts"]:
        raise AtlasParquetSearchViewError("compact view roles or aggregate counts differ")
    projection_seen = seen_verbatim_roles & PROJECTION_MEMBER_ROLES
    if projection_seen and projection_seen != PROJECTION_MEMBER_ROLES:
        raise AtlasParquetSearchViewError(
            "compact view agency projection tables must be carried through together"
        )
    if artifact_file_paths(directory) != expected_files:
        raise AtlasParquetSearchViewError("compact view file membership is not closed")
    return manifest


__all__ = [
    "PROJECTION_MEMBER_ROLES",
    "AtlasParquetSearchViewError",
    "build_atlas_parquet_search_view",
    "verify_atlas_parquet_search_view",
]

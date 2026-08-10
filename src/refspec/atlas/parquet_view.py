"""Build and verify a compact Parquet view of an Atlas 3.0 distribution.

The canonical Atlas remains the asserted RDF distribution.  This module turns
its authenticated compact logical-record packs into typed, queryable Parquet
tables.  It preserves every logical record and its canonical RDF content
digest, but does not duplicate the 30-million-row N-Quads serialization.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from refspec.atlas.compact_pack import (
    CompactPackInventory,
    CompactRecordRole,
    read_compact_record_pack,
)
from refspec.atlas.parquet_artifact import (
    PARQUET_MEMBER_FIELDS,
    arrow_schema_sha256,
    artifact_file_paths,
    canonical_payload_sha256,
    file_sha256,
    normalize_sha256_prefix,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

VIEW_SCHEMA_VERSION = "1.0"
VIEW_RECORD_TYPE = "AtlasParquetViewManifest"
VIEW_IMPLEMENTATION = "refspec.atlas.parquet_view"
VIEW_IMPLEMENTATION_VERSION = "1.0"
VIEW_ID_PREFIX = "urn:ref:atlas-parquet-view:"
MANIFEST_FILE = "view-manifest.json"
ROW_GROUP_SIZE = 50_000
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 9

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROOT_MANIFEST_FIELDS = frozenset(
    {
        "binding",
        "canonicalPayloadDigest",
        "counts",
        "createdAt",
        "distributionId",
        "format",
        "graphs",
        "members",
        "packs",
        "schemaVersion",
        "type",
    }
)
_VIEW_MANIFEST_FIELDS = frozenset(
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


class AtlasParquetViewError(ValueError):
    """The Atlas input or derived Parquet view is unsafe or inconsistent."""


def _digest_bytes(value: object, label: str) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise AtlasParquetViewError(f"{label} must be a lowercase SHA-256 digest")
    return bytes.fromhex(value.removeprefix("sha256:"))


def _digest_text(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise AtlasParquetViewError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _strict_json(path: Path, *, expected_digest: str | None = None) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AtlasParquetViewError(f"JSON input is missing or unsafe: {path}")
    raw = path.read_bytes()
    if expected_digest is not None and sha256_digest(raw) != expected_digest:
        raise AtlasParquetViewError(f"JSON input digest differs: {path.name}")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise AtlasParquetViewError(f"{path.name} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AtlasParquetViewError(f"{path.name} is not UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise AtlasParquetViewError(f"{path.name} must contain one JSON object")
    if raw != canonical_json_bytes(value):
        raise AtlasParquetViewError(f"{path.name} is not newline-terminated canonical JSON")
    return value


def _safe_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise AtlasParquetViewError("artifact path must be text")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise AtlasParquetViewError(f"artifact path is unsafe: {relative!r}")
    path = root.joinpath(*parsed.parts)
    if path.is_symlink():
        raise AtlasParquetViewError(f"artifact path cannot be a symlink: {relative}")
    return path


def _binary_digest_field(name: str, *, nullable: bool = True) -> pa.Field:
    return pa.field(name, pa.binary(32), nullable=nullable)


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
            pa.field("evidence_role", pa.string(), nullable=False),
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

_TABLE_NAMES = {
    CompactRecordRole.RESOURCE: "resources.parquet",
    CompactRecordRole.LABEL: "labels.parquet",
    CompactRecordRole.STATEMENT: "statements.parquet",
    CompactRecordRole.EVIDENCE_BINDING: "evidence-bindings.parquet",
    CompactRecordRole.SOURCE_RECORD: "source-records.parquet",
    CompactRecordRole.RELEASE: "releases.parquet",
    CompactRecordRole.IDENTIFIER: "identifiers.parquet",
    CompactRecordRole.LIFECYCLE_EVENT: "lifecycle-events.parquet",
}


def _record_row(role: CompactRecordRole, row: Mapping[str, Any]) -> dict[str, Any]:
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
            "evidence_role": row["evidenceRole"],
            "decision": row["decision"],
            "attested_at": row["attestedAt"],
        }
    if role is CompactRecordRole.SOURCE_RECORD:
        return {
            **common,
            "source_release": row["sourceRelease"],
            "source_digest": _digest_bytes(row["sourceDigest"], "sourceDigest"),
            "source_locator": row["sourceLocator"],
            "native_payload": canonical_json_bytes(row["nativePayload"])[:-1],
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
    raise AssertionError(f"unsupported compact record role {role}")


def _chunks(rows: Sequence[Mapping[str, Any]], size: int = ROW_GROUP_SIZE) -> Iterable[Sequence[Mapping[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


@dataclass(frozen=True, slots=True)
class VerifiedAtlasParquetSourceMetadata:
    """Verified Atlas source metadata needed to derive a Parquet view."""

    root: Path
    manifest: Mapping[str, Any]
    manifest_digest: str
    construction_summary: Mapping[str, Any]
    compact_packs: tuple[Mapping[str, Any], ...]

    @property
    def view_input_pin(self) -> dict[str, Any]:
        """Return the complete authenticated input identity for a derived view."""

        asserted = next(graph for graph in self.manifest["graphs"] if graph["role"] == "asserted")
        construction = next(member for member in self.manifest["members"] if member["role"] == "constructionSummary")
        return {
            "assertedInventoryDigest": asserted["inventoryDigest"],
            "bindingBundleDigest": self.manifest["binding"]["bindingBundleDigest"],
            "canonicalPayloadDigest": self.manifest["canonicalPayloadDigest"],
            "compactPackInventoryDigest": self.construction_summary["compactPackInventoryDigest"],
            "constructionSummaryDigest": construction["digest"],
            "distributionId": self.manifest["distributionId"],
            "manifestSha256": self.manifest_digest,
            "ontologyDigest": self.manifest["binding"]["ontologyDigest"],
        }


def verify_atlas_parquet_source_metadata(
    root: Path,
    expected_manifest_digest: str,
) -> VerifiedAtlasParquetSourceMetadata:
    """Verify the Atlas manifest, supporting members, and pack inventory.

    Compact-pack bytes are authenticated when the builder reads them. This
    check is not an Atlas release-conformance verdict; call the independent
    Atlas validator for that verdict.
    """

    if root.is_symlink() or not root.is_dir():
        raise AtlasParquetViewError("Atlas distribution root must be a regular directory")
    expected_manifest_digest = normalize_sha256_prefix(expected_manifest_digest)
    _digest_text(expected_manifest_digest, "expected manifest digest")
    manifest_path = root / "atlas-manifest.json"
    manifest = _strict_json(manifest_path, expected_digest=expected_manifest_digest)
    if set(manifest) != _ROOT_MANIFEST_FIELDS:
        raise AtlasParquetViewError("Atlas root manifest fields are unsupported")
    if (
        manifest["type"] != "AtlasManifest"
        or manifest["schemaVersion"] != "3.0"
        or manifest["format"] != "refspec-atlas-packed-nquads-3.0"
    ):
        raise AtlasParquetViewError("Atlas root manifest type, version, or format is unsupported")
    payload = dict(manifest)
    declared_payload_digest = _digest_text(payload.pop("canonicalPayloadDigest"), "canonicalPayloadDigest")
    if canonical_payload_sha256(payload) != declared_payload_digest:
        raise AtlasParquetViewError("Atlas root canonicalPayloadDigest differs")

    members = manifest["members"]
    packs = manifest["packs"]
    graphs = manifest["graphs"]
    if not isinstance(members, list) or not isinstance(packs, list) or not isinstance(graphs, list):
        raise AtlasParquetViewError("Atlas members, packs, and graphs must be arrays")
    construction_members = [member for member in members if member.get("role") == "constructionSummary"]
    if len(construction_members) != 1:
        raise AtlasParquetViewError("Atlas requires exactly one construction summary member")
    construction_member = construction_members[0]
    construction_path = _safe_path(root, construction_member.get("path"))
    construction_summary = _strict_json(
        construction_path,
        expected_digest=_digest_text(construction_member.get("digest"), "construction summary digest"),
    )
    if construction_path.stat().st_size != construction_member.get("byteLength"):
        raise AtlasParquetViewError("construction summary byte length differs")
    summary_payload = dict(construction_summary)
    summary_digest = _digest_text(summary_payload.pop("canonicalPayloadDigest", None), "summary payload digest")
    if canonical_payload_sha256(summary_payload) != summary_digest:
        raise AtlasParquetViewError("construction summary canonicalPayloadDigest differs")
    compact_packs = construction_summary.get("compactPacks")
    if not isinstance(compact_packs, list) or not compact_packs:
        raise AtlasParquetViewError("construction summary has no compact packs")
    if construction_summary.get("compactPackCount") != len(compact_packs):
        raise AtlasParquetViewError("construction summary compact pack count differs")
    if construction_summary.get("compactPackInventoryDigest") != sha256_digest(canonical_json_bytes(compact_packs)):
        raise AtlasParquetViewError("construction summary compact pack inventory digest differs")

    asserted = [graph for graph in graphs if graph.get("role") == "asserted"]
    if len(asserted) != 1:
        raise AtlasParquetViewError("Atlas requires exactly one asserted graph descriptor")
    if construction_summary.get("assertedInventoryDigest") != asserted[0].get("inventoryDigest"):
        raise AtlasParquetViewError("construction summary asserted inventory digest differs")
    if construction_summary.get("distributionId") != manifest["distributionId"]:
        raise AtlasParquetViewError("construction summary distribution identifier differs")
    if construction_summary.get("bindingBundleDigest") != manifest["binding"].get("bindingBundleDigest"):
        raise AtlasParquetViewError("construction summary binding digest differs")

    pack_ids = {pack.get("packId") for pack in packs}
    if len(pack_ids) != len(packs):
        raise AtlasParquetViewError("Atlas RDF pack identifiers are not unique")
    for role_graph in graphs:
        role = role_graph.get("role")
        inventory = sorted(
            (
                {
                    "contentDigest": pack["content"]["digest"],
                    "packId": pack["packId"],
                    "quadCount": pack["graphCounts"][role],
                }
                for pack in packs
                if pack["graphCounts"][role]
            ),
            key=lambda row: row["packId"],
        )
        if canonical_payload_sha256(inventory) != role_graph.get("inventoryDigest"):
            raise AtlasParquetViewError(f"Atlas {role} graph inventory digest differs")
        if role_graph.get("packCount") != len(inventory) or role_graph.get("quadCount") != sum(
            row["quadCount"] for row in inventory
        ):
            raise AtlasParquetViewError(f"Atlas {role} graph counts differ")

    expected_files = {"atlas-manifest.json"}
    for member in members:
        path = _safe_path(root, member.get("path"))
        expected_files.add(path.relative_to(root).as_posix())
        if path == construction_path:
            # _strict_json and the preceding length check already authenticated
            # this member and its canonical JSON form.
            continue
        if path.is_symlink() or not path.is_file():
            raise AtlasParquetViewError(f"Atlas member is missing or unsafe: {member.get('path')}")
        if path.stat().st_size != member.get("byteLength") or file_sha256(path) != member.get("digest"):
            raise AtlasParquetViewError(f"Atlas member bytes differ: {member.get('path')}")
    for pack in packs:
        path = _safe_path(root, pack.get("path"))
        expected_files.add(path.relative_to(root).as_posix())
        transport = pack.get("transport")
        content = pack.get("content")
        if not isinstance(transport, Mapping) or not isinstance(content, Mapping):
            raise AtlasParquetViewError("Atlas RDF pack descriptor is malformed")
        if path.is_symlink() or not path.is_file():
            raise AtlasParquetViewError(f"Atlas RDF pack is missing or unsafe: {pack.get('path')}")
        if path.stat().st_size != transport.get("byteLength") or file_sha256(path) != transport.get("digest"):
            raise AtlasParquetViewError(f"Atlas RDF pack transport differs: {pack.get('path')}")
        expected_id = "urn:ref:atlas:pack:" + str(content.get("digest", "")).removeprefix("sha256:")
        if pack.get("packId") != expected_id:
            raise AtlasParquetViewError(f"Atlas RDF pack identity differs: {pack.get('path')}")
    compact_paths: list[str] = []
    compact_ids: set[str] = set()
    for descriptor in compact_packs:
        inventory = CompactPackInventory.from_dict(descriptor)
        path = _safe_path(root, inventory.path)
        expected_files.add(path.relative_to(root).as_posix())
        compact_paths.append(inventory.path)
        if inventory.pack_id in compact_ids:
            raise AtlasParquetViewError("compact pack identifiers are not unique")
        compact_ids.add(inventory.pack_id)
    if compact_paths != sorted(compact_paths) or len(compact_paths) != len(set(compact_paths)):
        raise AtlasParquetViewError("compact pack paths must be unique and sorted")
    if artifact_file_paths(root) != expected_files:
        raise AtlasParquetViewError("Atlas distribution file membership is not closed")
    return VerifiedAtlasParquetSourceMetadata(
        root=root.resolve(),
        manifest=manifest,
        manifest_digest=expected_manifest_digest,
        construction_summary=construction_summary,
        compact_packs=tuple(compact_packs),
    )


def _write_tables(
    input_: VerifiedAtlasParquetSourceMetadata,
    output: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    descriptors_by_role: dict[CompactRecordRole, list[Mapping[str, Any]]] = {role: [] for role in CompactRecordRole}
    for descriptor in input_.compact_packs:
        try:
            role = CompactRecordRole(str(descriptor.get("role")))
        except ValueError as error:
            raise AtlasParquetViewError(f"unsupported compact record role {descriptor.get('role')!r}") from error
        descriptors_by_role[role].append(descriptor)

    members: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for role in CompactRecordRole:
        schema = _SCHEMAS[role]
        relative = "tables/" + _TABLE_NAMES[role]
        target = _safe_path(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(
            target,
            schema,
            compression=COMPRESSION,
            compression_level=COMPRESSION_LEVEL,
            use_dictionary=True,
            write_statistics=True,
            version="2.6",
            data_page_version="2.0",
        )
        try:
            wrote = False
            for descriptor in descriptors_by_role[role]:
                artifact = read_compact_record_pack(input_.root, descriptor)
                for chunk in _chunks(artifact.rows):
                    rows = [_record_row(role, row) for row in chunk]
                    writer.write_table(pa.Table.from_pylist(rows, schema=schema), row_group_size=ROW_GROUP_SIZE)
                    counts[role.value] += len(rows)
                    wrote = True
            if not wrote:
                writer.write_table(schema.empty_table())
        finally:
            writer.close()
        members.append(
            {
                "byteLength": target.stat().st_size,
                "mediaType": "application/vnd.apache.parquet",
                "path": relative,
                "role": role.value,
                "rowCount": counts[role.value],
                # Pin the schema as serialized by Parquet. PyArrow restores the
                # same logical schema but may normalize nested-field metadata.
                "schemaDigest": arrow_schema_sha256(pq.ParquetFile(target).schema_arrow),
                "sha256": file_sha256(target),
            }
        )
    expected_counts = Counter()
    for descriptor in input_.compact_packs:
        expected_counts[str(descriptor["role"])] += int(descriptor["content"]["recordCount"])
    if counts != expected_counts:
        raise AtlasParquetViewError(
            f"Parquet row counts differ from compact pack inventory: expected={dict(expected_counts)}, actual={dict(counts)}"
        )
    return members, {role.value: counts[role.value] for role in CompactRecordRole}


def build_atlas_parquet_view(
    distribution: Path,
    output: Path,
    *,
    expected_manifest_digest: str,
) -> dict[str, Any]:
    """Build one immutable, typed Parquet view from an exact Atlas 3.0 input."""

    if output.is_symlink() or output.exists():
        raise AtlasParquetViewError(f"refusing to replace existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    input_ = verify_atlas_parquet_source_metadata(distribution, expected_manifest_digest)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        members, counts = _write_tables(input_, temporary)
        construction = {
            "compression": COMPRESSION,
            "compressionLevel": COMPRESSION_LEVEL,
            "implementation": VIEW_IMPLEMENTATION,
            "implementationVersion": VIEW_IMPLEMENTATION_VERSION,
            "parquetVersion": "2.6",
            "pyarrowVersion": importlib.metadata.version("pyarrow"),
            "rowGroupSize": ROW_GROUP_SIZE,
            "sourceRepresentation": "authenticatedAtlasCompactLogicalRecords",
        }
        input_pin = input_.view_input_pin
        identity = canonical_payload_sha256({"construction": construction, "input": input_pin})
        manifest: dict[str, Any] = {
            "construction": construction,
            "counts": counts,
            "input": input_pin,
            "members": members,
            "recordType": VIEW_RECORD_TYPE,
            "schemaVersion": VIEW_SCHEMA_VERSION,
            "status": {
                "canonicalAtlas": False,
                "containsExactRdfTable": False,
                "derivedView": True,
                "expansion": "not_used",
                "logicalRecordsPreserved": True,
            },
            "viewId": VIEW_ID_PREFIX + identity.removeprefix("sha256:"),
        }
        manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
        (temporary / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
        verify_atlas_parquet_view(temporary, expected_manifest_digest=file_sha256(temporary / MANIFEST_FILE))
        os.rename(temporary, output)
        return manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_atlas_parquet_view(
    directory: Path,
    *,
    expected_manifest_digest: str,
) -> dict[str, Any]:
    """Verify a closed Atlas Parquet view against its external manifest pin."""

    if directory.is_symlink() or not directory.is_dir():
        raise AtlasParquetViewError("Atlas Parquet view must be a regular directory")
    expected_manifest_digest = normalize_sha256_prefix(expected_manifest_digest)
    _digest_text(expected_manifest_digest, "expected view manifest digest")
    manifest = _strict_json(directory / MANIFEST_FILE, expected_digest=expected_manifest_digest)
    if set(manifest) != _VIEW_MANIFEST_FIELDS:
        raise AtlasParquetViewError("Atlas Parquet view manifest fields are unsupported")
    if manifest["recordType"] != VIEW_RECORD_TYPE or manifest["schemaVersion"] != VIEW_SCHEMA_VERSION:
        raise AtlasParquetViewError("Atlas Parquet view type or version is unsupported")
    payload = dict(manifest)
    actual_payload_digest = _digest_text(payload.pop("canonicalPayloadDigest"), "view payload digest")
    if canonical_payload_sha256(payload) != actual_payload_digest:
        raise AtlasParquetViewError("Atlas Parquet view canonicalPayloadDigest differs")
    status = manifest["status"]
    if status != {
        "canonicalAtlas": False,
        "containsExactRdfTable": False,
        "derivedView": True,
        "expansion": "not_used",
        "logicalRecordsPreserved": True,
    }:
        raise AtlasParquetViewError("Atlas Parquet view status is unsupported")
    expected_files = {MANIFEST_FILE}
    counts: dict[str, int] = {}
    expected_roles = {role.value for role in CompactRecordRole}
    observed_roles: set[str] = set()
    for member in manifest["members"]:
        if set(member) != PARQUET_MEMBER_FIELDS:
            raise AtlasParquetViewError("Atlas Parquet member fields are unsupported")
        role = CompactRecordRole(member["role"])
        if role.value in observed_roles:
            raise AtlasParquetViewError("Atlas Parquet view repeats a table role")
        observed_roles.add(role.value)
        path = _safe_path(directory, member["path"])
        expected_files.add(path.relative_to(directory).as_posix())
        if path.is_symlink() or not path.is_file():
            raise AtlasParquetViewError(f"Parquet member is missing or unsafe: {member['path']}")
        if path.stat().st_size != member["byteLength"] or file_sha256(path) != member["sha256"]:
            raise AtlasParquetViewError(f"Parquet member bytes differ: {member['path']}")
        parquet = pq.ParquetFile(path)
        if parquet.schema_arrow != _SCHEMAS[role]:
            raise AtlasParquetViewError(f"Parquet schema differs: {member['path']}")
        if arrow_schema_sha256(parquet.schema_arrow) != member["schemaDigest"]:
            raise AtlasParquetViewError(f"Parquet schema digest differs: {member['path']}")
        row_count = parquet.metadata.num_rows
        if row_count != member["rowCount"]:
            raise AtlasParquetViewError(f"Parquet row count differs: {member['path']}")
        counts[role.value] = row_count
    if observed_roles != expected_roles or counts != manifest["counts"]:
        raise AtlasParquetViewError("Atlas Parquet roles or aggregate counts differ")
    if artifact_file_paths(directory) != expected_files:
        raise AtlasParquetViewError("Atlas Parquet view file membership is not closed")
    return manifest


__all__ = [
    "AtlasParquetViewError",
    "VerifiedAtlasParquetSourceMetadata",
    "build_atlas_parquet_view",
    "verify_atlas_parquet_source_metadata",
    "verify_atlas_parquet_view",
]

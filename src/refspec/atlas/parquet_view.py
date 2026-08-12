"""Close and verify the typed Parquet view of an Atlas 3.1 distribution.

The canonical Atlas remains the asserted RDF distribution.  The typed Parquet
tables are its served projection: they preserve every logical record and its
canonical RDF node digest without duplicating the 30-million-row N-Quads
serialization.

The tables are written by the Atlas builder, out of the same in-memory graph
walk that writes the RDF packs, and this module gives them their authenticated
identity: it verifies the distribution manifest, writes the view manifest
against it, re-verifies the closed result, and promotes it.  The second
producer that re-derived the tables from compact JSONL packs is gone with that
wire; :func:`seal_atlas_parquet_view` is the only path.

The view is written beside the distribution, never inside it -- a distribution
validates its own membership as a closed set.  What binds the two is the seal:
its signed payload carries this view manifest's digest alongside the
distribution manifest's, so one signature reaches every byte of both.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

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
    COMPRESSION,
    COMPRESSION_LEVEL,
    PARQUET_VERSION,
    ROW_GROUP_SIZE,
    TABLE_MEDIA_TYPE,
    TABLE_SCHEMAS,
    logical_records_preserved,
    table_relative_path,
    unpreserved_record_fields,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

# 3.0: the compact JSONL wire is gone, so the input pin loses
# `compactPackInventoryDigest` and the tables are the distribution's only
# served projection. 2.0 added the five warrant columns (four rkaf axes plus
# the optional basedOnAttestation referent), which is what makes
# `logicalRecordsPreserved` computed rather than declared.
VIEW_SCHEMA_VERSION = "3.0"
VIEW_RECORD_TYPE = "AtlasParquetViewManifest"
VIEW_IMPLEMENTATION = "refspec.atlas.parquet_view"
VIEW_IMPLEMENTATION_VERSION = "3.0"
VIEW_ID_PREFIX = "urn:ref:atlas-parquet-view:"
MANIFEST_FILE = "view-manifest.json"

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


@dataclass(frozen=True, slots=True)
class VerifiedAtlasParquetSourceMetadata:
    """Verified Atlas source metadata needed to derive a Parquet view."""

    root: Path
    manifest: Mapping[str, Any]
    manifest_digest: str
    construction_summary: Mapping[str, Any]

    @property
    def view_input_pin(self) -> dict[str, Any]:
        """Return the complete authenticated input identity for a derived view."""

        asserted = next(graph for graph in self.manifest["graphs"] if graph["role"] == "asserted")
        construction = next(member for member in self.manifest["members"] if member["role"] == "constructionSummary")
        return {
            "assertedInventoryDigest": asserted["inventoryDigest"],
            "bindingBundleDigest": self.manifest["binding"]["bindingBundleDigest"],
            "canonicalPayloadDigest": self.manifest["canonicalPayloadDigest"],
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

    This check is not an Atlas release-conformance verdict; call the
    independent Atlas validator for that verdict.
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
        or manifest["schemaVersion"] != "3.1"
        or manifest["format"] != "refspec-atlas-packed-nquads-3.1"
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
    if artifact_file_paths(root) != expected_files:
        raise AtlasParquetViewError("Atlas distribution file membership is not closed")
    return VerifiedAtlasParquetSourceMetadata(
        root=root.resolve(),
        manifest=manifest,
        manifest_digest=expected_manifest_digest,
        construction_summary=construction_summary,
    )


#: What the builder writes when it emits the tables from its own graph. It is
#: part of the view identity, so a consumer can tell which producer wrote the
#: tables it is reading.
BUILDER_SOURCE_REPRESENTATION = "atlasBuilderAssertedGraph"


def atlas_parquet_view_manifest(
    input_: VerifiedAtlasParquetSourceMetadata,
    members: Sequence[Mapping[str, Any]],
    counts: Mapping[str, int],
    *,
    source_representation: str,
) -> dict[str, Any]:
    """Assemble the view manifest for tables that are already written.

    ``logicalRecordsPreserved`` is computed from the schema against the logical
    record contract -- the claim was hard-coded ``True`` while four warrant
    axes had no column, which is what made it false.
    """

    gaps = unpreserved_record_fields()
    construction = {
        "compression": COMPRESSION,
        "compressionLevel": COMPRESSION_LEVEL,
        "implementation": VIEW_IMPLEMENTATION,
        "implementationVersion": VIEW_IMPLEMENTATION_VERSION,
        "parquetVersion": PARQUET_VERSION,
        "pyarrowVersion": importlib.metadata.version("pyarrow"),
        "rowGroupSize": ROW_GROUP_SIZE,
        "sourceRepresentation": source_representation,
    }
    input_pin = input_.view_input_pin
    identity = canonical_payload_sha256({"construction": construction, "input": input_pin})
    manifest: dict[str, Any] = {
        "construction": construction,
        "counts": dict(counts),
        "input": input_pin,
        "members": [dict(member) for member in members],
        "recordType": VIEW_RECORD_TYPE,
        "schemaVersion": VIEW_SCHEMA_VERSION,
        "status": {
            "canonicalAtlas": False,
            "containsExactRdfTable": False,
            "derivedView": True,
            "expansion": "not_used",
            "logicalRecordsPreserved": logical_records_preserved(),
        },
        "viewId": VIEW_ID_PREFIX + identity.removeprefix("sha256:"),
    }
    if gaps:
        # Never silently narrow: an unprojected compact field is named in the
        # artifact rather than left for a reader to discover by its absence.
        manifest["status"]["unpreservedRecordFields"] = {role: list(fields) for role, fields in sorted(gaps.items())}
    manifest["canonicalPayloadDigest"] = canonical_payload_sha256(manifest)
    return manifest


def seal_atlas_parquet_view(
    distribution: Path,
    staged_tables: Path,
    output: Path,
    *,
    expected_manifest_digest: str,
) -> dict[str, Any]:
    """Close a view over tables the Atlas builder already wrote.

    The builder streams the tables out of the graph it is already walking, so
    by the time the distribution manifest exists the tables are on disk and
    only their authenticated identity is missing.  This verifies that manifest,
    writes the view manifest against it, re-verifies the closed result, and
    promotes it.
    """

    if output.is_symlink() or output.exists():
        raise AtlasParquetViewError(f"refusing to replace existing output: {output}")
    if staged_tables.is_symlink() or not staged_tables.is_dir():
        raise AtlasParquetViewError(f"staged Parquet tables are missing or unsafe: {staged_tables}")
    output.parent.mkdir(parents=True, exist_ok=True)
    input_ = verify_atlas_parquet_source_metadata(distribution, expected_manifest_digest)
    members, counts = _staged_table_members(staged_tables)
    manifest = atlas_parquet_view_manifest(
        input_,
        members,
        counts,
        source_representation=BUILDER_SOURCE_REPRESENTATION,
    )
    (staged_tables / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
    verify_atlas_parquet_view(staged_tables, expected_manifest_digest=file_sha256(staged_tables / MANIFEST_FILE))
    os.rename(staged_tables, output)
    return manifest


def _staged_table_members(staged: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Re-read the staged tables so the manifest describes the bytes on disk."""

    members: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for role in CompactRecordRole:
        relative = table_relative_path(role)
        target = _safe_path(staged, relative)
        if target.is_symlink() or not target.is_file():
            raise AtlasParquetViewError(f"staged Parquet table is missing or unsafe: {relative}")
        parquet = pq.ParquetFile(target)
        if parquet.schema_arrow != TABLE_SCHEMAS[role]:
            raise AtlasParquetViewError(f"staged Parquet schema differs: {relative}")
        counts[role.value] = parquet.metadata.num_rows
        members.append(
            {
                "byteLength": target.stat().st_size,
                "mediaType": TABLE_MEDIA_TYPE,
                "path": relative,
                "role": role.value,
                "rowCount": counts[role.value],
                "schemaDigest": arrow_schema_sha256(parquet.schema_arrow),
                "sha256": file_sha256(target),
            }
        )
    if artifact_file_paths(staged) != {member["path"] for member in members}:
        raise AtlasParquetViewError("staged Parquet table directory is not closed")
    return members, counts


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
    expected_status: dict[str, Any] = {
        "canonicalAtlas": False,
        "containsExactRdfTable": False,
        "derivedView": True,
        "expansion": "not_used",
        "logicalRecordsPreserved": logical_records_preserved(),
    }
    if gaps := unpreserved_record_fields():
        expected_status["unpreservedRecordFields"] = {role: list(fields) for role, fields in sorted(gaps.items())}
    if status != expected_status:
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
        if parquet.schema_arrow != TABLE_SCHEMAS[role]:
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
    "BUILDER_SOURCE_REPRESENTATION",
    "AtlasParquetViewError",
    "VerifiedAtlasParquetSourceMetadata",
    "atlas_parquet_view_manifest",
    "seal_atlas_parquet_view",
    "verify_atlas_parquet_source_metadata",
    "verify_atlas_parquet_view",
]

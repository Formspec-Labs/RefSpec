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
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    COMPRESSION,
    COMPRESSION_LEVEL,
    DERIVED_RELATION_DECISION,
    DERIVED_RELATION_ID_PREFIX,
    DERIVED_RELATION_ROLE,
    DERIVED_RELATION_TABLE_SCHEMA,
    PARQUET_VERSION,
    ROW_GROUP_SIZE,
    TABLE_MEDIA_TYPE,
    TABLE_SCHEMAS,
    agency_projection_table_relative_path,
    derived_relation_content_digest,
    derived_relation_coverage,
    derived_relation_logical_row,
    derived_relation_table_relative_path,
    logical_records_preserved,
    table_relative_path,
    unpreserved_record_fields,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import SEMANTIC_RINGS

# 3.0: the compact JSONL wire is gone. 2.0 added the five warrant columns.
# 3.1 added the optional REF-038 agency-projection tables and their manifest
# block. 3.2 adds the optional derived-relations table (REF-042's derived
# graph carried into the served view) and its manifest block; a 3.2 view of
# a distribution that declares derived content MUST carry the table, which
# is what closes the gap the first content-bearing derived graph shipped
# with -- 42,519 derived relations sealed in the packs, zero reachable from
# the view.
VIEW_SCHEMA_VERSION = "3.2"
LEGACY_VIEW_SCHEMA_VERSION = "3.1"
LEGACY_VIEW_SCHEMA_VERSION_3_0 = "3.0"
VIEW_RECORD_TYPE = "AtlasParquetViewManifest"
VIEW_IMPLEMENTATION = "refspec.atlas.parquet_view"
VIEW_IMPLEMENTATION_VERSION = "3.2"
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
_AGENCY_PROJECTION_COVERAGE_FIELDS = frozenset(
    {
        "source_value_kind",
        "source_value_count",
        "resolved_value_count",
        "unresolved_value_count",
        "basis_counts",
        "unresolved_reason_counts",
        "rows_with_parent_org",
        "evidence_record_count",
    }
)
_DERIVED_RELATION_COVERAGE_FIELDS = frozenset(
    {
        "rowCount",
        "ruleCounts",
        "predicateCounts",
        "generatedAt",
    }
)
_VIEW_MANIFEST_FIELDS = frozenset(
    {
        "agencyProjection",
        "canonicalPayloadDigest",
        "construction",
        "counts",
        "derivedRelations",
        "input",
        "members",
        "recordType",
        "schemaVersion",
        "status",
        "viewId",
    }
)
#: 3.1 carried the agency-projection block; 3.0 carried neither optional
#: table category. Both stay verifiable so already-sealed views do not.
_LEGACY_3_1_VIEW_MANIFEST_FIELDS = _VIEW_MANIFEST_FIELDS - {"derivedRelations"}
_LEGACY_3_0_VIEW_MANIFEST_FIELDS = _LEGACY_3_1_VIEW_MANIFEST_FIELDS - {"agencyProjection"}


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
            "canonicalPayloadDigest": self.manifest["canonicalPayloadDigest"],
            "constructionSummaryDigest": construction["digest"],
            "contractDigest": self.manifest["binding"]["contractDigest"],
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
    if construction_summary.get("contractDigest") != manifest["binding"].get("contractDigest"):
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


def _validated_agency_projection_metadata(
    agency_projection: Mapping[str, Any],
    counts: Mapping[str, int],
) -> dict[str, Any]:
    """Validate and detach the REF-038 view metadata from its caller."""

    if not isinstance(agency_projection, Mapping):
        raise AtlasParquetViewError(
            "agency projection metadata must be an object"
        )
    metadata = dict(agency_projection)
    if metadata.get("status") == "emitted":
        if set(metadata) != {
            "status",
            "decision",
            "digest",
            "coverage",
        }:
            raise AtlasParquetViewError(
                "agency projection metadata fields differ"
            )
        coverage = metadata["coverage"]
        if not isinstance(coverage, Mapping):
            raise AtlasParquetViewError(
                "agency projection coverage must be an object"
            )
        coverage = dict(coverage)
        if set(coverage) != _AGENCY_PROJECTION_COVERAGE_FIELDS:
            raise AtlasParquetViewError(
                "agency projection coverage fields differ"
            )
        integer_fields = (
            "source_value_count",
            "resolved_value_count",
            "unresolved_value_count",
            "rows_with_parent_org",
            "evidence_record_count",
        )
        if any(
            not isinstance(coverage[field], int)
            or isinstance(coverage[field], bool)
            or coverage[field] < 0
            for field in integer_fields
        ):
            raise AtlasParquetViewError(
                "agency projection coverage counts must be non-negative integers"
            )
        basis_counts = coverage["basis_counts"]
        reason_counts = coverage["unresolved_reason_counts"]
        if not isinstance(basis_counts, Mapping) or not isinstance(
            reason_counts,
            Mapping,
        ):
            raise AtlasParquetViewError(
                "agency projection coverage breakdowns must be objects"
            )
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
            for breakdown in (basis_counts, reason_counts)
            for key, value in breakdown.items()
        ):
            raise AtlasParquetViewError(
                "agency projection coverage breakdowns are invalid"
            )
        if (
            metadata.get("decision") != "REF-038"
            or _DIGEST.fullmatch(str(metadata.get("digest"))) is None
            or coverage.get("source_value_kind")
            != "regulationsGovAgencyId"
            or counts.get(AGENCY_PROJECTION_ROLE)
            != coverage.get("resolved_value_count")
            or counts.get(AGENCY_PROJECTION_UNRESOLVED_ROLE)
            != coverage.get("unresolved_value_count")
            or coverage.get("source_value_count")
            != coverage.get("resolved_value_count")
            + coverage.get("unresolved_value_count")
            or sum(basis_counts.values())
            != coverage.get("resolved_value_count")
            or sum(reason_counts.values())
            != coverage.get("unresolved_value_count")
        ):
            raise AtlasParquetViewError(
                "agency projection coverage differs from table rows"
            )
        metadata["coverage"] = coverage
    elif metadata.get("status") == "notEmitted":
        if set(metadata) != {"status", "missingReleaseKeys"}:
            raise AtlasParquetViewError(
                "absent agency projection metadata fields differ"
            )
        missing = metadata["missingReleaseKeys"]
        if (
            not isinstance(missing, list)
            or not missing
            or any(not isinstance(key, str) or not key for key in missing)
            or len(missing) != len(set(missing))
        ):
            raise AtlasParquetViewError(
                "absent agency projection names no valid missing release set"
            )
        if any(role in counts for role in AGENCY_PROJECTION_TABLE_SCHEMAS):
            raise AtlasParquetViewError(
                "absent agency projection metadata accompanies emitted tables"
            )
    else:
        raise AtlasParquetViewError(
            "agency projection metadata has an unsupported status"
        )
    return metadata


def _verify_agency_projection_content(
    directory: Path,
    manifest: Mapping[str, Any],
) -> None:
    """Recompute REF-038 coverage and its logical-content digest from rows."""

    metadata = manifest["agencyProjection"]
    if metadata["status"] != "emitted":
        return
    resolved = pq.read_table(
        _safe_path(
            directory,
            agency_projection_table_relative_path(AGENCY_PROJECTION_ROLE),
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

    resolved_values: set[str] = set()
    basis_counts: Counter[str] = Counter()
    parent_count = 0
    evidence_count = 0
    for row in resolved:
        source_value = row["source_value"]
        if not source_value or source_value in resolved_values:
            raise AtlasParquetViewError(
                "agency projection repeats or empties a resolved source value"
            )
        resolved_values.add(source_value)
        if (
            row["source_value_kind"] != "regulationsGovAgencyId"
            or not row["org"]
            or not row["basis"]
            or not row["evidence_records"]
        ):
            raise AtlasParquetViewError(
                "agency projection resolved row is incomplete"
            )
        basis_counts[row["basis"]] += 1
        parent_count += row["parent_org"] is not None
        for evidence in row["evidence_records"]:
            evidence_count += 1
            source_record = evidence["source_record"]
            target_record = evidence["target_record"]
            if (
                evidence["evidence_tier"] != row["evidence_tier"]
                or evidence["evidence_tier"] != "E4"
                or evidence["warrant"] != row["warrant"]
                or evidence["warrant"] != "humanReview"
                or evidence["decision"] != "approved"
                or evidence["decision_basis"] != row["basis"]
                or evidence["relation"] != row["relation"]
                or evidence["name_similarity_used"] is not False
                or not evidence["reasoning"]
                or source_record["value"] != source_value
                or not source_record["publisher_name"]
                or target_record["resource"] != row["org"]
                or not target_record["publisher_name"]
            ):
                raise AtlasParquetViewError(
                    "agency projection mapping evidence differs from its row"
                )

    unresolved_values: set[str] = set()
    reason_counts: Counter[str] = Counter()
    for row in unresolved:
        source_value = row["source_value"]
        if not source_value or source_value in unresolved_values:
            raise AtlasParquetViewError(
                "agency projection repeats or empties an unresolved source value"
            )
        unresolved_values.add(source_value)
        if (
            row["source_value_kind"] != "regulationsGovAgencyId"
            or not row["source_org"]
            or not row["reason"]
            or not row["reasoning"]
        ):
            raise AtlasParquetViewError(
                "agency projection unresolved row is incomplete"
            )
        reason_counts[row["reason"]] += 1
    if resolved_values & unresolved_values:
        raise AtlasParquetViewError(
            "agency projection resolves and abstains on one source value"
        )

    coverage = metadata["coverage"]
    observed_coverage = {
        "source_value_kind": "regulationsGovAgencyId",
        "source_value_count": len(resolved_values | unresolved_values),
        "resolved_value_count": len(resolved),
        "unresolved_value_count": len(unresolved),
        "basis_counts": dict(sorted(basis_counts.items())),
        "unresolved_reason_counts": dict(sorted(reason_counts.items())),
        "rows_with_parent_org": parent_count,
        "evidence_record_count": evidence_count,
    }
    if observed_coverage != coverage:
        raise AtlasParquetViewError(
            "agency projection coverage differs from logical rows"
        )
    projection_digest = canonical_payload_sha256(
        {
            "rows": resolved,
            "unresolved": unresolved,
            "coverage": coverage,
        }
    )
    if projection_digest != metadata["digest"]:
        raise AtlasParquetViewError(
            "agency projection logical-content digest differs"
        )


def _validated_derived_relation_metadata(
    derived_relations: object,
    counts: Mapping[str, int],
    distribution_counts: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate the derived-relations block against the tables it describes.

    ``counts`` are the view's table row counts by role. When
    ``distribution_counts`` is given (seal time, from the verified Atlas
    manifest) the block is additionally tied to the distribution's own
    declared ``derivedRelations`` count: a view of a distribution that
    declares derived content must carry it, and a view of a distribution
    with none must not invent it. At verify time no distribution is at
    hand; the tie was checked when the manifest was sealed and survives the
    manifest's payload digest.
    """

    if not isinstance(derived_relations, Mapping):
        raise AtlasParquetViewError(
            "derived relations metadata must be an object"
        )
    metadata = dict(derived_relations)
    if metadata.get("status") == "emitted":
        if set(metadata) != {
            "status",
            "decision",
            "digest",
            "coverage",
        }:
            raise AtlasParquetViewError(
                "derived relations metadata fields differ"
            )
        coverage = metadata["coverage"]
        if not isinstance(coverage, Mapping):
            raise AtlasParquetViewError(
                "derived relations coverage must be an object"
            )
        coverage = dict(coverage)
        if set(coverage) != _DERIVED_RELATION_COVERAGE_FIELDS:
            raise AtlasParquetViewError(
                "derived relations coverage fields differ"
            )
        row_count = coverage["rowCount"]
        if (
            not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 1
            or not isinstance(coverage["generatedAt"], str)
            or not coverage["generatedAt"]
        ):
            raise AtlasParquetViewError(
                "derived relations coverage rowCount or generatedAt is invalid"
            )
        for field in ("ruleCounts", "predicateCounts"):
            breakdown = coverage[field]
            if not isinstance(breakdown, Mapping) or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                for key, value in breakdown.items()
            ):
                raise AtlasParquetViewError(
                    "derived relations coverage breakdowns are invalid"
                )
            if sum(breakdown.values()) != row_count:
                raise AtlasParquetViewError(
                    "derived relations coverage breakdown does not sum to its rows"
                )
        if (
            metadata.get("decision") != DERIVED_RELATION_DECISION
            or _DIGEST.fullmatch(str(metadata.get("digest"))) is None
            or counts.get(DERIVED_RELATION_ROLE) != row_count
        ):
            raise AtlasParquetViewError(
                "derived relations coverage differs from table rows"
            )
        if distribution_counts is not None and distribution_counts.get(
            "derivedRelations"
        ) != row_count:
            raise AtlasParquetViewError(
                "derived relations differ from the distribution's declared count"
            )
        metadata["coverage"] = coverage
    elif metadata.get("status") == "notEmitted":
        if set(metadata) != {"status"}:
            raise AtlasParquetViewError(
                "absent derived relations metadata fields differ"
            )
        if DERIVED_RELATION_ROLE in counts:
            raise AtlasParquetViewError(
                "absent derived relations metadata accompanies an emitted table"
            )
        if distribution_counts is not None and distribution_counts.get(
            "derivedRelations",
            0,
        ) != 0:
            raise AtlasParquetViewError(
                "distribution declares derived relations the view does not carry"
            )
    else:
        raise AtlasParquetViewError(
            "derived relations metadata has an unsupported status"
        )
    return metadata


def _verify_derived_relation_content(
    directory: Path,
    manifest: Mapping[str, Any],
) -> None:
    """Recompute derived-relation coverage and content digest from rows."""

    metadata = manifest["derivedRelations"]
    if metadata["status"] != "emitted":
        return
    rows = pq.read_table(
        _safe_path(directory, derived_relation_table_relative_path())
    ).to_pylist()
    identifiers: set[str] = set()
    for row in rows:
        row_id = row["id"]
        if not row_id or row_id in identifiers:
            raise AtlasParquetViewError(
                "derived relation repeats or empties an identifier"
            )
        identifiers.add(row_id)
        if row_id != DERIVED_RELATION_ID_PREFIX + bytes(row["content_digest"]).hex():
            raise AtlasParquetViewError(
                "derived relation identifier differs from its contentDigest"
            )
        evidence = row["derived_from_assertions"]
        if not evidence or evidence != sorted(set(evidence)):
            raise AtlasParquetViewError(
                "derived relation evidence rows are empty, repeated, or unsorted"
            )
        if (
            row["semantic_ring"] not in SEMANTIC_RINGS
            or not row["subject"]
            or not row["predicate"]
            or not row["object"]
            or not row["derivation_rule"]
            or not row["engine"]
            or not row["engine_version"]
            or not row["generated_at"]
        ):
            raise AtlasParquetViewError(
                "derived relation row is incomplete"
            )
    logical = [derived_relation_logical_row(row) for row in rows]
    coverage = derived_relation_coverage(logical)
    if coverage != metadata["coverage"]:
        raise AtlasParquetViewError(
            "derived relations coverage differs from table rows"
        )
    if derived_relation_content_digest(logical, coverage) != metadata["digest"]:
        raise AtlasParquetViewError(
            "derived relations logical-content digest differs"
        )


def atlas_parquet_view_manifest(
    input_: VerifiedAtlasParquetSourceMetadata,
    members: Sequence[Mapping[str, Any]],
    counts: Mapping[str, int],
    *,
    source_representation: str,
    agency_projection: Mapping[str, Any],
    derived_relations: Mapping[str, Any],
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
    projection_metadata = _validated_agency_projection_metadata(
        agency_projection,
        counts,
    )
    derived_metadata = _validated_derived_relation_metadata(
        derived_relations,
        counts,
        input_.manifest["counts"],
    )
    manifest: dict[str, Any] = {
        "agencyProjection": projection_metadata,
        "construction": construction,
        "counts": dict(counts),
        "derivedRelations": derived_metadata,
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
    agency_projection: Mapping[str, Any],
    derived_relations: Mapping[str, Any],
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
        agency_projection=agency_projection,
        derived_relations=derived_relations,
    )
    (staged_tables / MANIFEST_FILE).write_bytes(canonical_json_bytes(manifest))
    verify_atlas_parquet_view(staged_tables, expected_manifest_digest=file_sha256(staged_tables / MANIFEST_FILE))
    os.rename(staged_tables, output)
    return manifest


def _staged_table_members(staged: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Re-read the staged tables so the manifest describes the bytes on disk."""

    members: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    contracts: list[tuple[str, str, pa.Schema]] = [
        (
            role.value,
            table_relative_path(role),
            TABLE_SCHEMAS[role],
        )
        for role in CompactRecordRole
    ]
    projection_present = {
        role: _safe_path(
            staged,
            agency_projection_table_relative_path(role),
        ).is_file()
        for role in AGENCY_PROJECTION_TABLE_SCHEMAS
    }
    if len(set(projection_present.values())) != 1:
        raise AtlasParquetViewError(
            "agency projection tables must be emitted together"
        )
    if all(projection_present.values()):
        contracts.extend(
            (
                role,
                agency_projection_table_relative_path(role),
                schema,
            )
            for role, schema in AGENCY_PROJECTION_TABLE_SCHEMAS.items()
        )
    if _safe_path(staged, derived_relation_table_relative_path()).is_file():
        contracts.append(
            (
                DERIVED_RELATION_ROLE,
                derived_relation_table_relative_path(),
                DERIVED_RELATION_TABLE_SCHEMA,
            )
        )

    for role, relative, schema in contracts:
        target = _safe_path(staged, relative)
        if target.is_symlink() or not target.is_file():
            raise AtlasParquetViewError(f"staged Parquet table is missing or unsafe: {relative}")
        parquet = pq.ParquetFile(target)
        if parquet.schema_arrow != schema:
            raise AtlasParquetViewError(f"staged Parquet schema differs: {relative}")
        counts[role] = parquet.metadata.num_rows
        members.append(
            {
                "byteLength": target.stat().st_size,
                "mediaType": TABLE_MEDIA_TYPE,
                "path": relative,
                "role": role,
                "rowCount": counts[role],
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
    schema_version = manifest.get("schemaVersion")
    if schema_version == VIEW_SCHEMA_VERSION:
        expected_manifest_fields = _VIEW_MANIFEST_FIELDS
    elif schema_version == LEGACY_VIEW_SCHEMA_VERSION:
        expected_manifest_fields = _LEGACY_3_1_VIEW_MANIFEST_FIELDS
    elif schema_version == LEGACY_VIEW_SCHEMA_VERSION_3_0:
        expected_manifest_fields = _LEGACY_3_0_VIEW_MANIFEST_FIELDS
    else:
        raise AtlasParquetViewError("Atlas Parquet view type or version is unsupported")
    if set(manifest) != expected_manifest_fields:
        raise AtlasParquetViewError("Atlas Parquet view manifest fields are unsupported")
    if manifest["recordType"] != VIEW_RECORD_TYPE:
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
    schema_by_role = {
        role.value: TABLE_SCHEMAS[role] for role in CompactRecordRole
    }
    if (
        schema_version in (VIEW_SCHEMA_VERSION, LEGACY_VIEW_SCHEMA_VERSION)
        and manifest["agencyProjection"]["status"] == "emitted"
    ):
        schema_by_role.update(AGENCY_PROJECTION_TABLE_SCHEMAS)
    if (
        schema_version == VIEW_SCHEMA_VERSION
        and manifest["derivedRelations"]["status"] == "emitted"
    ):
        schema_by_role[DERIVED_RELATION_ROLE] = DERIVED_RELATION_TABLE_SCHEMA
    expected_roles = set(schema_by_role)
    observed_roles: set[str] = set()
    for member in manifest["members"]:
        if set(member) != PARQUET_MEMBER_FIELDS:
            raise AtlasParquetViewError("Atlas Parquet member fields are unsupported")
        role = member["role"]
        schema = schema_by_role.get(role)
        if schema is None:
            raise AtlasParquetViewError(
                f"Atlas Parquet view has an unsupported table role: {role!r}"
            )
        if role in observed_roles:
            raise AtlasParquetViewError("Atlas Parquet view repeats a table role")
        observed_roles.add(role)
        path = _safe_path(directory, member["path"])
        expected_files.add(path.relative_to(directory).as_posix())
        if path.is_symlink() or not path.is_file():
            raise AtlasParquetViewError(f"Parquet member is missing or unsafe: {member['path']}")
        if path.stat().st_size != member["byteLength"] or file_sha256(path) != member["sha256"]:
            raise AtlasParquetViewError(f"Parquet member bytes differ: {member['path']}")
        parquet = pq.ParquetFile(path)
        if parquet.schema_arrow != schema:
            raise AtlasParquetViewError(f"Parquet schema differs: {member['path']}")
        if arrow_schema_sha256(parquet.schema_arrow) != member["schemaDigest"]:
            raise AtlasParquetViewError(f"Parquet schema digest differs: {member['path']}")
        row_count = parquet.metadata.num_rows
        if row_count != member["rowCount"]:
            raise AtlasParquetViewError(f"Parquet row count differs: {member['path']}")
        counts[role] = row_count
    if observed_roles != expected_roles or counts != manifest["counts"]:
        raise AtlasParquetViewError("Atlas Parquet roles or aggregate counts differ")
    if schema_version in (VIEW_SCHEMA_VERSION, LEGACY_VIEW_SCHEMA_VERSION):
        _validated_agency_projection_metadata(
            manifest["agencyProjection"],
            counts,
        )
        _verify_agency_projection_content(directory, manifest)
    if schema_version == VIEW_SCHEMA_VERSION:
        _validated_derived_relation_metadata(
            manifest["derivedRelations"],
            counts,
            None,
        )
        _verify_derived_relation_content(directory, manifest)
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

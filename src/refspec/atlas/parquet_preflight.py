"""Fast relational preflight for an authenticated Atlas Parquet view.

This is a development gate, not a replacement for the Atlas 3 normative RDF
validator.  It uses the typed logical-record view to catch the global
referential and cardinality failures that are expensive to discover by
repeatedly walking a large RDFLib graph.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_artifact import normalize_sha256_prefix
from refspec.atlas.parquet_view import (
    verify_atlas_parquet_source_metadata,
    verify_atlas_parquet_view,
)
from refspec.registry.infrastructure.source_controlled_resource import LABEL_ROLES

ATLAS = "https://refspec.org/ns/atlas/v3#"
RKAF = "https://rulespec.org/ns/v1#"
APPROVED = RKAF + "approved"
# rkaf:evidenceRole is the axis that discriminates all six review warrants, so
# it is what a columnar preflight checks. The other three axes are constrained
# by the SHACL shape and the dataset validator; a column scan that repeated
# them would not catch anything this one misses.
REVIEW_METHODS = frozenset(
    {
        RKAF + "structuralEvidence",
        RKAF + "textualEvidence",
        RKAF + "formalAdoptionEvent",
        RKAF + "officialSourceMetadata",
        RKAF + "authorityCitation",
        RKAF + "reviewedAuthorityChain",
    }
)
STATEMENT_TYPES = frozenset(
    {
        "CrossRingRelationAssertion",
        "MappingAssertion",
        "NativeRelationAssertion",
        "SourceAssignment",
    }
)

PREFLIGHT_CHECKS = (
    "authenticated-distribution-and-view",
    "manifest-counts",
    "unique-logical-record-identities",
    "release-membership-and-profile",
    "source-record-closure",
    "label-provenance-and-uniqueness",
    "identifier-authority-uniqueness",
    "statement-endpoints-releases-and-rings",
    "immutable-evidence-coverage",
)

RELEASE_ONLY_CHECKS = (
    "closed-json-schema-and-binding-pins",
    "producer-proof-and-acceptance-receipts",
    "normative-shacl",
    "rdf-canonical-lexical-profile",
    "rdf-graph-role-and-pack-dependencies",
    "rdf-node-digest-recomputation",
    "assertion-policy-identity-and-lifecycle-semantics",
    "projection-and-derived-graph-replay",
    "skos-transitive-conflict-analysis",
    "source-accounting-ledger-reconciliation",
    "construction-record-ownership",
    "reasoning-isolation",
)


class AtlasParquetPreflightError(ValueError):
    """An authenticated Atlas Parquet view fails a columnar invariant."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _fail(code: str, detail: str) -> None:
    raise AtlasParquetPreflightError(code, detail)


def _has_true(mask: pa.Array | pa.ChunkedArray) -> bool:
    result = pc.any(pc.fill_null(mask, True)).as_py()
    return bool(result)


def _first_value(
    table: pa.Table,
    mask: pa.Array | pa.ChunkedArray,
    column: str = "id",
) -> object:
    return table.filter(pc.fill_null(mask, True))[column][0].as_py()


def _require_unique(table: pa.Table, columns: list[str], code: str) -> None:
    grouped = table.group_by(columns).aggregate([("id", "count")])
    count_column = "id_count"
    duplicate = pc.greater(grouped[count_column], 1)
    if _has_true(duplicate):
        row = grouped.filter(duplicate).slice(0, 1).to_pylist()[0]
        _fail(code, f"duplicate values for {columns}: {row}")


def _validate_record_identities(tables: Mapping[str, pa.Table]) -> None:
    """Check all logical-record identifiers with one success-path count."""

    all_ids = pa.concat_arrays([table["id"].combine_chunks() for table in tables.values()])
    counts = pc.value_counts(all_ids)
    values = counts.field("values")
    if _has_true(pc.is_null(values)):
        for role, table in tables.items():
            if _has_true(pc.is_null(table["id"])):
                _fail(f"preflight.{role.casefold()}-identity", "logical record identifier is null")

    duplicate_mask = pc.greater(counts.field("counts"), 1)
    if not _has_true(duplicate_mask):
        return

    duplicate_ids = pc.filter(values, duplicate_mask)
    for role, table in tables.items():
        role_duplicates = Counter(
            pc.filter(
                table["id"],
                pc.is_in(table["id"], value_set=duplicate_ids),
            ).to_pylist()
        )
        repeated = next((identifier for identifier, count in role_duplicates.items() if count > 1), None)
        if repeated is not None:
            _fail(
                f"preflight.{role.casefold()}-identity",
                f"duplicate logical record identifier {repeated!r}",
            )
    _fail("preflight.cross-role-identity", "one logical record identifier occurs in multiple table roles")


def _foreign_indices(
    table: pa.Table,
    column: str,
    target: pa.Table,
    *,
    target_column: str = "id",
    code: str,
) -> pa.Array | pa.ChunkedArray:
    indices = pc.index_in(table[column], value_set=target[target_column])
    missing = pc.is_null(indices)
    if _has_true(missing):
        value = _first_value(table, missing, column)
        _fail(code, f"{column} names unknown {target_column} {value!r}")
    return indices


def _require_columns_equal(
    table: pa.Table,
    left: str,
    right: pa.Array | pa.ChunkedArray,
    *,
    code: str,
    detail: str,
) -> None:
    differs = pc.invert(pc.equal(table[left], right))
    if _has_true(differs):
        _fail(code, f"{_first_value(table, differs)} {detail}")


def _take(table: pa.Table, column: str, indices: pa.Array | pa.ChunkedArray) -> pa.ChunkedArray:
    return pa.chunked_array([pc.take(table[column], indices)])


def _only(table: pa.Table, column: str, value: str) -> pa.Table:
    return table.filter(pc.equal(table[column], value))


def _statement_counts(statements: pa.Table) -> dict[str, int]:
    grouped = statements.group_by(["statement_type"]).aggregate([("id", "count")])
    return {str(row["statement_type"]): int(row["id_count"]) for row in grouped.to_pylist()}


def _validate_manifest_counts(
    tables: Mapping[str, pa.Table],
    view_counts: Mapping[str, Any],
    distribution_counts: Mapping[str, Any],
    statement_counts: Mapping[str, int],
) -> None:
    observed = {role: table.num_rows for role, table in tables.items()}
    if observed != dict(view_counts):
        _fail("preflight.counts", f"view counts differ: expected={dict(view_counts)}, actual={observed}")

    releases = tables[CompactRecordRole.RELEASE.value]
    atlas_releases = _only(releases, "release_type", "AtlasRelease").num_rows
    expected = {
        "resources": observed[CompactRecordRole.RESOURCE.value],
        "labels": observed[CompactRecordRole.LABEL.value],
        "sourceRecords": observed[CompactRecordRole.SOURCE_RECORD.value],
        "identifiers": observed[CompactRecordRole.IDENTIFIER.value],
        "relationAssertions": observed[CompactRecordRole.STATEMENT.value],
        "releases": atlas_releases,
        "mappingAssertions": statement_counts.get("MappingAssertion", 0),
        "nativeRelationAssertions": statement_counts.get("NativeRelationAssertion", 0),
        "crossRingRelationAssertions": statement_counts.get("CrossRingRelationAssertion", 0),
        "sourceAssignments": statement_counts.get("SourceAssignment", 0),
    }
    actual = {name: distribution_counts.get(name) for name in expected}
    if expected != actual:
        _fail("preflight.counts", f"distribution counts differ: expected={expected}, actual={actual}")


def _validate_releases(
    releases: pa.Table,
    resources: pa.Table,
    source_records: pa.Table,
) -> None:
    release_types = set(pc.unique(releases["release_type"]).to_pylist())
    if release_types - {"AtlasRelease", "SourceRelease"}:
        _fail("preflight.release-type", f"unsupported release types: {sorted(release_types)}")

    atlas_releases = _only(releases, "release_type", "AtlasRelease")
    source_releases = _only(releases, "release_type", "SourceRelease")
    resource_release_indices = _foreign_indices(
        resources,
        "release",
        atlas_releases,
        code="preflight.resource-release",
    )
    for resource_column, release_column in (
        ("scheme", "scheme"),
        ("semantic_ring", "semantic_ring"),
        ("resource_profile", "resource_profile"),
    ):
        _require_columns_equal(
            resources,
            resource_column,
            _take(atlas_releases, release_column, resource_release_indices),
            code="preflight.resource-release",
            detail=f"{resource_column} differs from its release",
        )
    _foreign_indices(
        source_records,
        "source_release",
        source_releases,
        code="preflight.source-release",
    )


def _validate_labels(
    labels: pa.Table,
    resources: pa.Table,
    source_records: pa.Table,
) -> None:
    resource_indices = _foreign_indices(
        labels,
        "resource",
        resources,
        code="preflight.label-resource",
    )
    _foreign_indices(
        labels,
        "source_record",
        source_records,
        code="preflight.label-source-record",
    )
    _require_columns_equal(
        labels,
        "release",
        _take(resources, "release", resource_indices),
        code="preflight.label-release",
        detail="release differs from its resource",
    )
    _require_columns_equal(
        labels,
        "source_record",
        _take(resources, "source_record", resource_indices),
        code="preflight.label-provenance",
        detail="does not share its resource SourceRecord",
    )
    roles = set(pc.unique(labels["label_role"]).to_pylist())
    if roles - LABEL_ROLES:
        _fail("preflight.label-role", f"unsupported label roles: {sorted(roles)}")
    preferred = _only(labels, "label_role", "preferred")
    _require_unique(
        preferred,
        ["resource", "language"],
        "preflight.label-preferred-language",
    )
    _require_unique(
        labels,
        ["resource", "value", "language"],
        "preflight.label-role-overlap",
    )


def _validate_identifiers(
    identifiers: pa.Table,
    resources: pa.Table,
    source_records: pa.Table,
) -> None:
    _foreign_indices(
        identifiers,
        "identifies",
        resources,
        code="preflight.identifier-resource",
    )
    _foreign_indices(
        identifiers,
        "source_record",
        source_records,
        code="preflight.identifier-source-record",
    )
    grouped = identifiers.group_by(["identifier_scheme", "identifier_value"]).aggregate(
        [("identifies", "count_distinct")]
    )
    conflicts = pc.greater(grouped["identifies_count_distinct"], 1)
    if _has_true(conflicts):
        row = grouped.filter(conflicts).slice(0, 1).to_pylist()[0]
        _fail("preflight.identifier-uniqueness", f"authority-scoped identifier is ambiguous: {row}")


def _validate_relation_statements(statements: pa.Table, resources: pa.Table) -> None:
    subject_indices = _foreign_indices(
        statements,
        "subject",
        resources,
        code="preflight.statement-subject",
    )
    object_indices = _foreign_indices(
        statements,
        "object",
        resources,
        code="preflight.statement-object",
    )
    for statement_column, resource_column, indices, endpoint in (
        ("source_release", "release", subject_indices, "source"),
        ("target_release", "release", object_indices, "target"),
    ):
        _require_columns_equal(
            statements,
            statement_column,
            _take(resources, resource_column, indices),
            code="preflight.statement-release",
            detail=f"{endpoint} release does not contain its endpoint",
        )

    cross_mask = pc.equal(statements["statement_type"], "CrossRingRelationAssertion")
    cross_ring = statements.filter(cross_mask)
    if cross_ring.num_rows:
        _require_columns_equal(
            cross_ring,
            "source_ring",
            pc.filter(_take(resources, "semantic_ring", subject_indices), cross_mask),
            code="preflight.statement-ring",
            detail="source ring differs from its endpoint",
        )
        _require_columns_equal(
            cross_ring,
            "target_ring",
            pc.filter(_take(resources, "semantic_ring", object_indices), cross_mask),
            code="preflight.statement-ring",
            detail="target ring differs from its endpoint",
        )
        same_ring = pc.equal(cross_ring["source_ring"], cross_ring["target_ring"])
        if _has_true(same_ring):
            _fail(
                "preflight.statement-ring",
                f"{_first_value(cross_ring, same_ring)} does not cross semantic rings",
            )
        if _has_true(pc.is_valid(cross_ring["semantic_ring"])):
            _fail("preflight.statement-ring", "cross-ring assertion also has semantic_ring")

    same_mask = pc.invert(cross_mask)
    same_ring = statements.filter(same_mask)
    if same_ring.num_rows:
        for indices, endpoint in (
            (subject_indices, "subject"),
            (object_indices, "object"),
        ):
            _require_columns_equal(
                same_ring,
                "semantic_ring",
                pc.filter(_take(resources, "semantic_ring", indices), same_mask),
                code="preflight.statement-ring",
                detail=f"semantic ring differs from its {endpoint}",
            )
        if _has_true(pc.or_(pc.is_valid(same_ring["source_ring"]), pc.is_valid(same_ring["target_ring"]))):
            _fail("preflight.statement-ring", "same-ring assertion has cross-ring context")


def _validate_source_assignments(
    assignments: pa.Table,
    resources: pa.Table,
    source_records: pa.Table,
) -> None:
    source_indices = _foreign_indices(
        assignments,
        "subject",
        source_records,
        code="preflight.assignment-source-record",
    )
    resource_indices = _foreign_indices(
        assignments,
        "object",
        resources,
        code="preflight.assignment-resource",
    )
    for statement_column, target, target_column, indices, detail in (
        (
            "source_release",
            source_records,
            "source_release",
            source_indices,
            "source release differs from its SourceRecord",
        ),
        (
            "target_release",
            resources,
            "release",
            resource_indices,
            "target release does not contain its resource",
        ),
        (
            "semantic_ring",
            resources,
            "semantic_ring",
            resource_indices,
            "semantic ring differs from its resource",
        ),
    ):
        _require_columns_equal(
            assignments,
            statement_column,
            _take(target, target_column, indices),
            code="preflight.assignment",
            detail=detail,
        )


def _validate_statements(
    statements: pa.Table,
    resources: pa.Table,
    source_records: pa.Table,
    statement_counts: Mapping[str, int],
) -> None:
    observed_types = set(statement_counts)
    if observed_types - STATEMENT_TYPES:
        _fail("preflight.statement-type", f"unsupported statement types: {sorted(observed_types)}")
    assignment_mask = pc.equal(statements["statement_type"], "SourceAssignment")
    assignments = statements.filter(assignment_mask)
    relations = statements.filter(pc.invert(assignment_mask))
    if relations.num_rows:
        _validate_relation_statements(relations, resources)
    if assignments.num_rows:
        _validate_source_assignments(assignments, resources, source_records)

    mappings = _only(statements, "statement_type", "MappingAssertion")
    same_release = pc.equal(mappings["source_release"], mappings["target_release"])
    if _has_true(same_release):
        _fail(
            "preflight.mapping-release",
            f"{_first_value(mappings, same_release)} maps within one release",
        )
    superseding = statements.filter(pc.is_valid(statements["supersedes_assertion"]))
    if superseding.num_rows:
        _foreign_indices(
            superseding,
            "supersedes_assertion",
            statements,
            code="preflight.supersession",
        )
        self_supersession = pc.equal(superseding["id"], superseding["supersedes_assertion"])
        if _has_true(self_supersession):
            _fail(
                "preflight.supersession",
                f"{_first_value(superseding, self_supersession)} supersedes itself",
            )
        _require_unique(superseding, ["supersedes_assertion"], "preflight.supersession")


def _validate_evidence(
    evidence: pa.Table,
    statements: pa.Table,
    source_records: pa.Table,
) -> None:
    _foreign_indices(
        evidence,
        "statement",
        statements,
        code="preflight.evidence-statement",
    )
    source_indices = _foreign_indices(
        evidence,
        "source_record",
        source_records,
        code="preflight.evidence-source-record",
    )
    _require_columns_equal(
        evidence,
        "evidence_source_digest",
        _take(source_records, "content_digest", source_indices),
        code="preflight.evidence-digest",
        detail="does not pin its exact SourceRecord",
    )
    missing_evidence = pc.is_null(pc.index_in(statements["id"], value_set=evidence["statement"]))
    if _has_true(missing_evidence):
        _fail(
            "preflight.evidence-coverage",
            f"statement has no evidence binding: {_first_value(statements, missing_evidence)}",
        )
    invalid_decision = pc.not_equal(evidence["decision"], APPROVED)
    if _has_true(invalid_decision):
        _fail(
            "preflight.evidence-decision",
            f"{_first_value(evidence, invalid_decision)} is not approved",
        )
    invalid_method = pc.invert(pc.is_in(evidence["evidence_role"], value_set=pa.array(sorted(REVIEW_METHODS))))
    if _has_true(invalid_method):
        _fail(
            "preflight.evidence-method",
            f"{_first_value(evidence, invalid_method)} uses an unsupported review method",
        )


#: Derived projections a view may carry beside the closed record roles.
DERIVED_VIEW_TABLES = frozenset(
    {"agencyProjection", "agencyProjectionUnresolved", "derivedRelations"}
)


def validate_atlas_parquet_tables(
    tables: Mapping[str, pa.Table],
    *,
    view_counts: Mapping[str, Any],
    distribution_counts: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate global relational invariants over already-authenticated tables."""

    # The record roles are the closed relational core every view must carry.
    # A view may also carry derived projections beside them -- the agency
    # projection and the derived-relation table the mapping era added -- which
    # are checked by their own producers, not by these relational invariants.
    expected_roles = {role.value for role in CompactRecordRole}
    missing = sorted(expected_roles - set(tables))
    if missing:
        _fail("preflight.tables", f"view omits record roles: {missing}")
    unknown = sorted(set(tables) - expected_roles - DERIVED_VIEW_TABLES)
    if unknown:
        _fail("preflight.tables", f"view carries unknown tables: {unknown}")
    # Only the record roles carry a logical-record identifier; the derived
    # projections are keyed by their own subjects.
    _validate_record_identities({role: tables[role] for role in sorted(expected_roles)})

    resources = tables[CompactRecordRole.RESOURCE.value]
    labels = tables[CompactRecordRole.LABEL.value]
    statements = tables[CompactRecordRole.STATEMENT.value]
    evidence = tables[CompactRecordRole.EVIDENCE_BINDING.value]
    source_records = tables[CompactRecordRole.SOURCE_RECORD.value]
    releases = tables[CompactRecordRole.RELEASE.value]
    identifiers = tables[CompactRecordRole.IDENTIFIER.value]
    statement_counts = _statement_counts(statements)

    _validate_manifest_counts(
        tables,
        view_counts,
        distribution_counts,
        statement_counts,
    )
    _foreign_indices(
        resources,
        "source_record",
        source_records,
        code="preflight.resource-source-record",
    )
    _validate_releases(releases, resources, source_records)
    _validate_labels(labels, resources, source_records)
    _validate_identifiers(identifiers, resources, source_records)
    _validate_statements(statements, resources, source_records, statement_counts)
    _validate_evidence(evidence, statements, source_records)

    return {
        "checks": list(PREFLIGHT_CHECKS),
        "counts": dict(view_counts),
        "mode": "authenticatedColumnarPreflight",
        "releaseOnlyChecks": list(RELEASE_ONLY_CHECKS),
        "status": "passed",
    }


def validate_atlas_parquet_preflight(
    distribution: Path,
    view: Path,
    *,
    expected_distribution_manifest_digest: str,
    expected_view_manifest_digest: str,
) -> dict[str, Any]:
    """Run the authenticated columnar preflight for one exact distribution."""

    # The Atlas builder uses this same source-metadata verifier when it seals
    # the view. Keeping one implementation prevents trust-chain drift while the
    # preflight API is still experimental.
    verified_input = verify_atlas_parquet_source_metadata(distribution, expected_distribution_manifest_digest)
    view_manifest = verify_atlas_parquet_view(
        view,
        expected_manifest_digest=expected_view_manifest_digest,
    )
    if view_manifest["input"] != verified_input.view_input_pin:
        _fail("preflight.input-pin", "Parquet view does not pin the complete supplied Atlas input")

    tables: dict[str, pa.Table] = {}
    for member in view_manifest["members"]:
        tables[str(member["role"])] = pq.read_table(view / str(member["path"]))
    result = validate_atlas_parquet_tables(
        tables,
        view_counts=view_manifest["counts"],
        distribution_counts=verified_input.manifest["counts"],
    )
    return {
        **result,
        "distributionId": verified_input.manifest["distributionId"],
        "distributionManifestDigest": verified_input.manifest_digest,
        "viewId": view_manifest["viewId"],
        "viewManifestDigest": normalize_sha256_prefix(expected_view_manifest_digest),
    }


__all__ = [
    "PREFLIGHT_CHECKS",
    "RELEASE_ONLY_CHECKS",
    "AtlasParquetPreflightError",
    "validate_atlas_parquet_preflight",
    "validate_atlas_parquet_tables",
]

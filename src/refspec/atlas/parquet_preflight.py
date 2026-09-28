"""Fast relational preflight for an authenticated Atlas Parquet view.

This is a development gate, not a replacement for the Atlas 3 normative RDF
validator.  It uses the typed logical-record view to catch the global
referential and cardinality failures that are expensive to discover by
repeatedly walking a large RDFLib graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import duckdb
import pyarrow as pa

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


# Derived tables contribute counts, but do not carry logical-record identities.
DERIVED_VIEW_TABLES = frozenset({"agencyProjection", "agencyProjectionUnresolved", "derivedRelations"})


def _validate_relations(
    db: duckdb.DuckDBPyConnection,
    roles: set[str],
    view_counts: Mapping[str, Any],
    distribution_counts: Mapping[str, Any],
) -> dict[str, Any]:
    """Run projected scans and spillable global joins; return only failure samples."""

    def check(query: str, code: str, detail: str) -> None:
        row = db.execute(query + " LIMIT 1").fetchone()
        if row is not None:
            _fail("preflight." + code, f"{detail}: {row}")

    def bad(table: str, condition: str, code: str, detail: str) -> None:
        check(f'SELECT id FROM "{table}" WHERE {condition}', code, detail)

    def foreign(table: str, column: str, target: str, code: str) -> None:
        check(
            f'SELECT a.id, a."{column}" FROM "{table}" a ANTI JOIN "{target}" b ON a."{column}" = b.id',
            code,
            f"{column} names unknown id",
        )

    def equal(table: str, key: str, target: str, left: str, right: str, code: str, detail: str) -> None:
        # Arrow's original comparison treats *either* null as a failure,
        # including null/null; SQL IS DISTINCT FROM alone would weaken it.
        check(
            f'SELECT a.id FROM "{table}" a JOIN "{target}" b ON a."{key}" = b.id '
            f'WHERE a."{left}" IS NULL OR b."{right}" IS NULL '
            f'OR a."{left}" <> b."{right}"',
            code,
            detail,
        )

    def unique(table: str, columns: str, code: str) -> None:
        check(
            f'SELECT {columns} FROM "{table}" GROUP BY {columns} HAVING count(*) > 1',
            code,
            f"duplicate values for {columns}",
        )

    core = sorted(role.value for role in CompactRecordRole)
    for role in core:
        bad(role, "id IS NULL", role.casefold() + "-identity", "logical record identifier is null")
    for role in core:
        unique(role, "id", role.casefold() + "-identity")
    ids = " UNION ALL ".join(f'SELECT id FROM "{role}"' for role in core)
    check(
        f"SELECT id FROM ({ids}) GROUP BY id HAVING count(*) > 1",
        "cross-role-identity",
        "one logical record identifier occurs in multiple table roles",
    )

    observed = {role: db.execute(f'SELECT count(*) FROM "{role}"').fetchone()[0] for role in sorted(roles)}
    if observed != dict(view_counts):
        _fail("preflight.counts", f"view counts differ: expected={dict(view_counts)}, actual={observed}")
    statement_counts = dict(
        db.execute('SELECT statement_type, count(*) FROM "Statement" GROUP BY statement_type').fetchall()
    )
    expected = {
        name: observed[role]
        for name, role in (
            ("resources", "Resource"),
            ("labels", "Label"),
            ("sourceRecords", "SourceRecord"),
            ("identifiers", "Identifier"),
            ("relationAssertions", "Statement"),
        )
    }
    expected["releases"] = db.execute(
        "SELECT count(*) FROM \"Release\" WHERE release_type = 'AtlasRelease'"
    ).fetchone()[0]
    expected.update(
        {
            name: statement_counts.get(kind, 0)
            for name, kind in (
                ("mappingAssertions", "MappingAssertion"),
                ("nativeRelationAssertions", "NativeRelationAssertion"),
                ("crossRingRelationAssertions", "CrossRingRelationAssertion"),
                ("sourceAssignments", "SourceAssignment"),
            )
        }
    )
    actual = {name: distribution_counts.get(name) for name in expected}
    if expected != actual:
        _fail("preflight.counts", f"distribution counts differ: expected={expected}, actual={actual}")

    foreign("Resource", "source_record", "SourceRecord", "resource-source-record")
    bad(
        "Release",
        "release_type IS NULL OR release_type NOT IN ('AtlasRelease', 'SourceRelease')",
        "release-type",
        "unsupported release type",
    )
    db.execute("CREATE VIEW atlas_releases AS SELECT * FROM \"Release\" WHERE release_type = 'AtlasRelease'")
    db.execute("CREATE VIEW source_releases AS SELECT * FROM \"Release\" WHERE release_type = 'SourceRelease'")
    foreign("Resource", "release", "atlas_releases", "resource-release")
    for column in ("scheme", "semantic_ring", "resource_profile"):
        equal(
            "Resource",
            "release",
            "atlas_releases",
            column,
            column,
            "resource-release",
            f"{column} differs from its release",
        )
    foreign("SourceRecord", "source_release", "source_releases", "source-release")

    foreign("Label", "resource", "Resource", "label-resource")
    foreign("Label", "source_record", "SourceRecord", "label-source-record")
    equal("Label", "resource", "Resource", "release", "release", "label-release", "release differs from its resource")
    equal(
        "Label",
        "resource",
        "Resource",
        "source_record",
        "source_record",
        "label-provenance",
        "does not share its resource SourceRecord",
    )
    label_roles = ", ".join("'" + role + "'" for role in sorted(LABEL_ROLES))
    bad("Label", f"label_role IS NULL OR label_role NOT IN ({label_roles})", "label-role", "unsupported label role")
    db.execute("CREATE VIEW preferred AS SELECT * FROM \"Label\" WHERE label_role = 'preferred'")
    unique("preferred", "resource, language", "label-preferred-language")
    unique("Label", "resource, value, language", "label-role-overlap")

    foreign("Identifier", "identifies", "Resource", "identifier-resource")
    foreign("Identifier", "source_record", "SourceRecord", "identifier-source-record")
    check(
        'SELECT identifier_scheme, identifier_value FROM "Identifier" '
        "GROUP BY identifier_scheme, identifier_value HAVING count(DISTINCT identifies) > 1",
        "identifier-uniqueness",
        "authority-scoped identifier is ambiguous",
    )

    if set(statement_counts) - STATEMENT_TYPES:
        _fail("preflight.statement-type", f"unsupported statement types: {list(statement_counts)}")
    db.execute("CREATE VIEW relations AS SELECT * FROM \"Statement\" WHERE statement_type <> 'SourceAssignment'")
    db.execute("CREATE VIEW assignments AS SELECT * FROM \"Statement\" WHERE statement_type = 'SourceAssignment'")
    foreign("relations", "subject", "Resource", "statement-subject")
    foreign("relations", "object", "Resource", "statement-object")
    for column, key, endpoint in (("source_release", "subject", "source"), ("target_release", "object", "target")):
        equal(
            "relations",
            key,
            "Resource",
            column,
            "release",
            "statement-release",
            f"{endpoint} release does not contain its endpoint",
        )
    db.execute("CREATE VIEW cross_ring AS SELECT * FROM relations WHERE statement_type = 'CrossRingRelationAssertion'")
    db.execute("CREATE VIEW same_ring AS SELECT * FROM relations WHERE statement_type <> 'CrossRingRelationAssertion'")
    for column, key in (("source_ring", "subject"), ("target_ring", "object")):
        equal(
            "cross_ring",
            key,
            "Resource",
            column,
            "semantic_ring",
            "statement-ring",
            f"{column} differs from its endpoint",
        )
    bad("cross_ring", "source_ring = target_ring", "statement-ring", "does not cross semantic rings")
    bad("cross_ring", "semantic_ring IS NOT NULL", "statement-ring", "cross-ring assertion also has semantic_ring")
    for key in ("subject", "object"):
        equal(
            "same_ring",
            key,
            "Resource",
            "semantic_ring",
            "semantic_ring",
            "statement-ring",
            f"semantic ring differs from its {key}",
        )
    bad(
        "same_ring",
        "source_ring IS NOT NULL OR target_ring IS NOT NULL",
        "statement-ring",
        "same-ring assertion has cross-ring context",
    )

    foreign("assignments", "subject", "SourceRecord", "assignment-source-record")
    foreign("assignments", "object", "Resource", "assignment-resource")
    for key, target, left, right, detail in (
        ("subject", "SourceRecord", "source_release", "source_release", "source release differs from its SourceRecord"),
        ("object", "Resource", "target_release", "release", "target release does not contain its resource"),
        ("object", "Resource", "semantic_ring", "semantic_ring", "semantic ring differs from its resource"),
    ):
        equal("assignments", key, target, left, right, "assignment", detail)
    bad(
        "Statement",
        "statement_type = 'MappingAssertion' AND source_release = target_release",
        "mapping-release",
        "maps within one release",
    )
    db.execute('CREATE VIEW superseding AS SELECT * FROM "Statement" WHERE supersedes_assertion IS NOT NULL')
    foreign("superseding", "supersedes_assertion", "Statement", "supersession")
    bad("superseding", "id = supersedes_assertion", "supersession", "supersedes itself")
    unique("superseding", "supersedes_assertion", "supersession")

    foreign("EvidenceBinding", "statement", "Statement", "evidence-statement")
    foreign("EvidenceBinding", "source_record", "SourceRecord", "evidence-source-record")
    equal(
        "EvidenceBinding",
        "source_record",
        "SourceRecord",
        "evidence_source_digest",
        "content_digest",
        "evidence-digest",
        "does not pin its exact SourceRecord",
    )
    check(
        'SELECT a.id FROM "Statement" a ANTI JOIN "EvidenceBinding" b ON a.id = b.statement',
        "evidence-coverage",
        "statement has no evidence binding",
    )
    bad("EvidenceBinding", f"decision IS NULL OR decision <> '{APPROVED}'", "evidence-decision", "is not approved")
    methods = ", ".join("'" + method + "'" for method in sorted(REVIEW_METHODS))
    bad(
        "EvidenceBinding",
        f"evidence_role IS NULL OR evidence_role NOT IN ({methods})",
        "evidence-method",
        "uses an unsupported review method",
    )
    return {
        "checks": list(PREFLIGHT_CHECKS),
        "counts": dict(view_counts),
        "mode": "authenticatedColumnarPreflight",
        "releaseOnlyChecks": list(RELEASE_ONLY_CHECKS),
        "status": "passed",
    }


def validate_atlas_parquet_tables(
    tables: Mapping[str, pa.Table | Path],
    *,
    view_counts: Mapping[str, Any],
    distribution_counts: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate authenticated Parquet paths or caller-owned Arrow tables.

    Parquet stays on disk. DuckDB selects the columns each query needs and
    spills global aggregates/joins into a disposable directory under pressure.
    The memory limit governs DuckDB's buffer manager, not total process RSS.
    """

    expected_roles = {role.value for role in CompactRecordRole}
    missing = sorted(expected_roles - set(tables))
    if missing:
        _fail("preflight.tables", f"view omits record roles: {missing}")
    unknown = sorted(set(tables) - expected_roles - DERIVED_VIEW_TABLES)
    if unknown:
        _fail("preflight.tables", f"view carries unknown tables: {unknown}")
    with (
        TemporaryDirectory(prefix="atlas-preflight-") as spill,
        duckdb.connect(
            config={"memory_limit": "512MB", "threads": 2, "temp_directory": spill, "preserve_insertion_order": False}
        ) as db,
    ):
        for role, table in tables.items():
            if isinstance(table, Path):
                db.read_parquet(str(table)).create_view(role)
            else:
                db.register(role, table)
        return _validate_relations(db, set(tables), view_counts, distribution_counts)


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

    tables: dict[str, Path] = {}
    for member in view_manifest["members"]:
        tables[str(member["role"])] = view / str(member["path"])
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

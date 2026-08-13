from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pyarrow as pa
import pytest

from refspec.atlas import parquet_preflight
from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_preflight import (
    APPROVED,
    REVIEW_METHODS,
    AtlasParquetPreflightError,
    validate_atlas_parquet_preflight,
    validate_atlas_parquet_tables,
)
from refspec.atlas.parquet_view import VerifiedAtlasParquetSourceMetadata

REVIEW_ROLE = min(REVIEW_METHODS)


def _tables() -> dict[str, pa.Table]:
    source_release = "urn:test:source-release"
    atlas_release = "urn:test:atlas-release"
    source_record = "urn:test:source-record"
    first_resource = "urn:test:resource:first"
    second_resource = "urn:test:resource:second"
    statement = "urn:test:statement"
    digest = b"1" * 32
    return {
        CompactRecordRole.RESOURCE.value: pa.table(
            {
                "id": [first_resource, second_resource],
                "release": [atlas_release, atlas_release],
                "scheme": ["urn:test:scheme", "urn:test:scheme"],
                "semantic_ring": ["subject", "subject"],
                "resource_profile": ["conceptScheme", "conceptScheme"],
                "source_record": [source_record, source_record],
            }
        ),
        CompactRecordRole.LABEL.value: pa.table(
            {
                "id": ["urn:test:label:first", "urn:test:label:second"],
                "resource": [first_resource, second_resource],
                "label_role": ["preferred", "preferred"],
                "value": ["First", "Second"],
                "language": ["en", "en"],
                "release": [atlas_release, atlas_release],
                "source_record": [source_record, source_record],
            }
        ),
        CompactRecordRole.STATEMENT.value: pa.table(
            {
                "id": [statement],
                "statement_type": ["NativeRelationAssertion"],
                "subject": [first_resource],
                "predicate": ["http://www.w3.org/2004/02/skos/core#broader"],
                "object": [second_resource],
                "source_release": [atlas_release],
                "target_release": [atlas_release],
                "semantic_ring": ["subject"],
                "source_ring": pa.array([None], type=pa.string()),
                "target_ring": pa.array([None], type=pa.string()),
                "supersedes_assertion": pa.array([None], type=pa.string()),
            }
        ),
        CompactRecordRole.EVIDENCE_BINDING.value: pa.table(
            {
                "id": ["urn:test:evidence"],
                "statement": [statement],
                "source_record": [source_record],
                "evidence_source_digest": [digest],
                "review_method": ["https://refspec.org/ns/atlas/v3#publisherAssertion"],
                "decision": [APPROVED],
                "evidence_role": [REVIEW_ROLE],
            }
        ),
        CompactRecordRole.SOURCE_RECORD.value: pa.table(
            {
                "id": [source_record],
                "source_release": [source_release],
                "content_digest": [digest],
            }
        ),
        CompactRecordRole.RELEASE.value: pa.table(
            {
                "id": [source_release, atlas_release],
                "release_type": ["SourceRelease", "AtlasRelease"],
                "resource_profile": [None, "conceptScheme"],
                "semantic_ring": [None, "subject"],
                "scheme": [None, "urn:test:scheme"],
            }
        ),
        CompactRecordRole.IDENTIFIER.value: pa.table(
            {
                "id": ["urn:test:identifier"],
                "identifier_value": ["FIRST"],
                "identifier_scheme": ["urn:test:identifier-scheme"],
                "identifies": [first_resource],
                "source_record": [source_record],
            }
        ),
        CompactRecordRole.LIFECYCLE_EVENT.value: pa.table({"id": pa.array([], type=pa.string())}),
    }


def _counts(tables: Mapping[str, pa.Table]) -> dict[str, int]:
    return {role: table.num_rows for role, table in tables.items()}


def _distribution_counts() -> dict[str, int]:
    return {
        "crossRingRelationAssertions": 0,
        "identifiers": 1,
        "labels": 2,
        "mappingAssertions": 0,
        "nativeRelationAssertions": 1,
        "relationAssertions": 1,
        "releases": 1,
        "resources": 2,
        "sourceAssignments": 0,
        "sourceRecords": 1,
    }


def _replace_column(table: pa.Table, name: str, values: list[object]) -> pa.Table:
    return table.set_column(table.schema.get_field_index(name), name, pa.array(values))


def _digest(value: str) -> str:
    return "sha256:" + value * 64


def _verified_parquet_input() -> VerifiedAtlasParquetSourceMetadata:
    return VerifiedAtlasParquetSourceMetadata(
        root=Path("/test/distribution"),
        manifest={
            "binding": {
                "contractDigest": _digest("1"),
                "ontologyDigest": _digest("2"),
            },
            "canonicalPayloadDigest": _digest("3"),
            "counts": {},
            "distributionId": "urn:test:distribution",
            "graphs": [{"inventoryDigest": _digest("4"), "role": "asserted"}],
            "members": [{"digest": _digest("5"), "role": "constructionSummary"}],
        },
        manifest_digest=_digest("6"),
        construction_summary={},
    )


def test_columnar_preflight_accepts_closed_relational_view() -> None:
    tables = _tables()

    result = validate_atlas_parquet_tables(
        tables,
        view_counts=_counts(tables),
        distribution_counts=_distribution_counts(),
    )

    assert result["status"] == "passed"
    assert result["mode"] == "authenticatedColumnarPreflight"
    assert {
        "assertion-policy-identity-and-lifecycle-semantics",
        "closed-json-schema-and-binding-pins",
        "normative-shacl",
        "producer-proof-and-acceptance-receipts",
        "reasoning-isolation",
    } <= set(result["releaseOnlyChecks"])


def test_columnar_preflight_rejects_dangling_statement_endpoint() -> None:
    tables = _tables()
    statements = tables[CompactRecordRole.STATEMENT.value]
    tables[CompactRecordRole.STATEMENT.value] = _replace_column(
        statements,
        "object",
        ["urn:test:missing"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.statement-object"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_duplicate_preferred_language() -> None:
    tables = _tables()
    labels = tables[CompactRecordRole.LABEL.value]
    tables[CompactRecordRole.LABEL.value] = _replace_column(
        labels,
        "resource",
        ["urn:test:resource:first", "urn:test:resource:first"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.label-preferred-language"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_stale_evidence_digest() -> None:
    tables = _tables()
    evidence = tables[CompactRecordRole.EVIDENCE_BINDING.value]
    tables[CompactRecordRole.EVIDENCE_BINDING.value] = _replace_column(
        evidence,
        "evidence_source_digest",
        [b"2" * 32],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.evidence-digest"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_cross_role_identity() -> None:
    tables = _tables()
    identifiers = tables[CompactRecordRole.IDENTIFIER.value]
    tables[CompactRecordRole.IDENTIFIER.value] = _replace_column(
        identifiers,
        "id",
        ["urn:test:resource:first"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.cross-role-identity"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_rejects_duplicate_identity_within_role() -> None:
    tables = _tables()
    labels = tables[CompactRecordRole.LABEL.value]
    tables[CompactRecordRole.LABEL.value] = _replace_column(
        labels,
        "id",
        ["urn:test:label:duplicate", "urn:test:label:duplicate"],
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.label-identity"):
        validate_atlas_parquet_tables(
            tables,
            view_counts=_counts(tables),
            distribution_counts=_distribution_counts(),
        )


def test_columnar_preflight_handles_same_and_cross_ring_relations_together() -> None:
    tables = _tables()
    resources = tables[CompactRecordRole.RESOURCE.value]
    tables[CompactRecordRole.RESOURCE.value] = pa.concat_tables(
        [
            resources,
            pa.table(
                {
                    "id": ["urn:test:resource:third"],
                    "release": ["urn:test:atlas-release:entity"],
                    "scheme": ["urn:test:scheme:entity"],
                    "semantic_ring": ["entity"],
                    "resource_profile": ["conceptScheme"],
                    "source_record": ["urn:test:source-record"],
                }
            ),
        ]
    )
    releases = tables[CompactRecordRole.RELEASE.value]
    tables[CompactRecordRole.RELEASE.value] = pa.concat_tables(
        [
            releases,
            pa.table(
                {
                    "id": ["urn:test:atlas-release:entity"],
                    "release_type": ["AtlasRelease"],
                    "resource_profile": ["conceptScheme"],
                    "semantic_ring": ["entity"],
                    "scheme": ["urn:test:scheme:entity"],
                }
            ),
        ]
    )
    statements = tables[CompactRecordRole.STATEMENT.value]
    tables[CompactRecordRole.STATEMENT.value] = pa.concat_tables(
        [
            statements,
            pa.table(
                {
                    "id": ["urn:test:statement:cross-ring"],
                    "statement_type": ["CrossRingRelationAssertion"],
                    "subject": ["urn:test:resource:first"],
                    "predicate": ["urn:test:related"],
                    "object": ["urn:test:resource:third"],
                    "source_release": ["urn:test:atlas-release"],
                    "target_release": ["urn:test:atlas-release:entity"],
                    "semantic_ring": pa.array([None], type=pa.string()),
                    "source_ring": ["subject"],
                    "target_ring": ["entity"],
                    "supersedes_assertion": pa.array([None], type=pa.string()),
                }
            ),
        ]
    )
    evidence = tables[CompactRecordRole.EVIDENCE_BINDING.value]
    tables[CompactRecordRole.EVIDENCE_BINDING.value] = pa.concat_tables(
        [
            evidence,
            pa.table(
                {
                    "id": ["urn:test:evidence:cross-ring"],
                    "statement": ["urn:test:statement:cross-ring"],
                    "source_record": ["urn:test:source-record"],
                    "evidence_source_digest": [b"1" * 32],
                    "review_method": ["https://refspec.org/ns/atlas/v3#publisherAssertion"],
                    "decision": [APPROVED],
                "evidence_role": [REVIEW_ROLE],
                    }
            ),
        ]
    )
    distribution_counts = {
        **_distribution_counts(),
        "crossRingRelationAssertions": 1,
        "relationAssertions": 2,
        "releases": 2,
        "resources": 3,
    }

    result = validate_atlas_parquet_tables(
        tables,
        view_counts=_counts(tables),
        distribution_counts=distribution_counts,
    )

    assert result["status"] == "passed"


def test_authenticated_preflight_rejects_drift_in_any_input_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verified_input = _verified_parquet_input()
    view_input_pin = verified_input.view_input_pin
    view_input_pin["ontologyDigest"] = _digest("8")
    view_manifest = {
        "counts": {},
        "input": view_input_pin,
        "members": [],
        "viewId": "urn:test:view",
    }
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_source_metadata",
        lambda *_args, **_kwargs: verified_input,
    )
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_view",
        lambda *_args, **_kwargs: view_manifest,
    )

    with pytest.raises(AtlasParquetPreflightError, match="preflight.input-pin"):
        validate_atlas_parquet_preflight(
            tmp_path / "distribution",
            tmp_path / "view",
            expected_distribution_manifest_digest=_digest("6"),
            expected_view_manifest_digest=_digest("9"),
        )


def test_authenticated_preflight_normalizes_returned_view_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verified_input = _verified_parquet_input()
    view_manifest = {
        "counts": {},
        "input": verified_input.view_input_pin,
        "members": [],
        "viewId": "urn:test:view",
    }
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_source_metadata",
        lambda *_args, **_kwargs: verified_input,
    )
    monkeypatch.setattr(
        parquet_preflight,
        "verify_atlas_parquet_view",
        lambda *_args, **_kwargs: view_manifest,
    )
    monkeypatch.setattr(
        parquet_preflight,
        "validate_atlas_parquet_tables",
        lambda *_args, **_kwargs: {"status": "passed"},
    )

    view_digest = "9" * 64
    result = validate_atlas_parquet_preflight(
        tmp_path / "distribution",
        tmp_path / "view",
        expected_distribution_manifest_digest=_digest("6"),
        expected_view_manifest_digest=view_digest,
    )

    assert result["viewManifestDigest"] == "sha256:" + view_digest

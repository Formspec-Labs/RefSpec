"""Column projection retains the frozen full-column writer's bytes and refusals."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_atlas_parquet_view import _fixture_distribution, _seal_view

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_search_view import (
    _DICTIONARIES,
    _MISSING_LABEL_ID,
    _SCHEMAS,
    COMPRESSION_LEVEL,
    ROW_GROUP_SIZE,
    AtlasParquetSearchViewError,
    _suffix,
    _write_role,
)
from refspec.atlas.parquet_tables import table_relative_path


# Copied from b6f30f4c. No deliberate output/verdict divergences.
def _old_transform(role: CompactRecordRole, row: Mapping[str, Any]) -> dict[str, Any]:
    """Project one full-view row into its compact column set, refusing identity drift.

    A Statement row's ``id`` must carry an assertion digest suffix equal to
    ``assertion_identity_digest``, and an EvidenceBinding row's must equal its
    ``content_digest``; a Label row must retain ``id``.
    """
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


def _old_write_role(source: Path, target: Path, role: CompactRecordRole) -> int:
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
            rows = [_old_transform(role, row) for row in batch.to_pylist()]
            writer.write_table(pa.Table.from_pylist(rows, schema=schema), row_group_size=ROW_GROUP_SIZE)
            count += len(rows)
        if count == 0:
            writer.write_table(schema.empty_table())
    finally:
        writer.close()
    return count


@pytest.fixture
def full_view(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    digest = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=digest)
    return full


@pytest.mark.parametrize("role", list(CompactRecordRole))
def test_projected_writer_matches_old_bytes(full_view, tmp_path, role):
    source = full_view / table_relative_path(role)
    old, new = tmp_path / "old.parquet", tmp_path / "new.parquet"
    assert _old_write_role(source, old, role) == _write_role(source, new, role)
    assert old.read_bytes() == new.read_bytes()


@pytest.mark.parametrize(
    "role,column",
    [
        (CompactRecordRole.STATEMENT, "assertion_identity_digest"),
        (CompactRecordRole.EVIDENCE_BINDING, "content_digest"),
        (CompactRecordRole.LABEL, "id"),
    ],
)
def test_projected_writer_keeps_identity_refusals(full_view, tmp_path, role, column):
    source = full_view / table_relative_path(role)
    table = pq.read_table(source)
    rows = table.to_pylist()
    assert rows
    rows[0][column] = "" if column == "id" else bytes(32)
    altered = tmp_path / "altered.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), altered)
    messages = []
    for index, write in enumerate((_old_write_role, _write_role)):
        with pytest.raises(AtlasParquetSearchViewError) as error:
            write(altered, tmp_path / f"out-{index}.parquet", role)
        messages.append(str(error.value))
    assert messages[0] == messages[1]

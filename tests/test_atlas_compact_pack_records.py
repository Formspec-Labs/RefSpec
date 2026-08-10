from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec.atlas import compact_pack
from refspec.atlas.compact_pack import (
    CompactPackError,
    CompactPackHeader,
    CompactRecordRole,
    build_compact_record_pack,
    normalize_compact_record,
    read_compact_record_pack,
    summarize_compact_records,
    write_compact_record_pack,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64

_SUMMARY_FIELD = {
    CompactRecordRole.RESOURCE: "resourceOwnership",
    CompactRecordRole.LABEL: "labelClaims",
    CompactRecordRole.STATEMENT: "statementEndpoints",
    CompactRecordRole.EVIDENCE_BINDING: "evidenceLinks",
    CompactRecordRole.SOURCE_RECORD: "sourceRecordLinks",
    CompactRecordRole.RELEASE: "releaseRecords",
    CompactRecordRole.IDENTIFIER: "identifierClaims",
    CompactRecordRole.LIFECYCLE_EVENT: "lifecycleEvents",
}


def _header(
    role: CompactRecordRole,
    *,
    defaults: dict[str, object] | None = None,
) -> CompactPackHeader:
    return CompactPackHeader(
        role=role.value,
        path=f"packs/records/{role.value.lower()}.jsonl.zst",
        defaults={} if defaults is None else defaults,
        dependencies=("urn:ref:atlas:compact-pack:upstream",),
    )


def _record(role: CompactRecordRole) -> dict[str, object]:
    records: dict[CompactRecordRole, dict[str, object]] = {
        CompactRecordRole.RESOURCE: {
            "id": "urn:example:resource:1",
            "release": "urn:example:atlas-release:1",
            "scheme": "urn:example:scheme:1",
            "semanticRing": "subject",
            "resourceProfile": "conceptScheme",
            "sourceRecord": "urn:example:source-record:1",
            "definition": "One resource",
            "notes": ["Second", "First"],
            "notations": ["B", "A"],
            "contentDigest": _DIGEST_A,
        },
        CompactRecordRole.LABEL: {
            "id": "urn:example:label:1",
            "resource": "urn:example:resource:1",
            "labelRole": "preferred",
            "value": "Example",
            "language": "en",
            "release": "urn:example:atlas-release:1",
            "sourceRecord": "urn:example:source-record:1",
        },
        CompactRecordRole.STATEMENT: {
            "id": "urn:example:statement:1",
            "statementType": "NativeRelationAssertion",
            "subject": "urn:example:resource:1",
            "predicate": "urn:example:predicate:broader",
            "object": "urn:example:resource:2",
            "sourceRelease": "urn:example:atlas-release:1",
            "targetRelease": "urn:example:atlas-release:1",
            "policy": "urn:example:policy:1",
            "assertedAt": "2026-08-06T08:45:00+00:00",
            "assertionIdentityDigest": _DIGEST_A,
            "semanticRing": "subject",
        },
        CompactRecordRole.EVIDENCE_BINDING: {
            "id": "urn:example:evidence:1",
            "statement": "urn:example:statement:1",
            "sourceRecord": "urn:example:source-record:1",
            "evidenceSourceDigest": _DIGEST_A,
            "attestor": "urn:example:reviewer:publisher",
            "attestorKind": "automatedParser",
            "assertionOrigin": "imported",
            "epistemicBasis": "sourceExplicit",
            "evidenceRole": "officialSourceMetadata",
            "evidentiaryFunction": "supports",
            "decision": "approved",
            "attestedAt": "2026-08-06T08:45:00+00:00",
        },
        CompactRecordRole.SOURCE_RECORD: {
            "id": "urn:example:source-record:1",
            "sourceRelease": "urn:example:source-release:1",
            "sourceDigest": _DIGEST_A,
            "sourceLocator": "https://example.gov/source.json#row=1",
            "nativePayload": {"code": "A", "label": "Example"},
            "representsResource": "urn:example:resource:1",
        },
        CompactRecordRole.RELEASE: {
            "id": "urn:example:source-release:1",
            "releaseType": "SourceRelease",
            "identifier": "example-source-2026",
            "issued": "2026-08-06",
            "sourceDigest": _DIGEST_A,
            "sourceLocator": "https://example.gov/source.json",
        },
        CompactRecordRole.IDENTIFIER: {
            "id": "urn:example:identifier:1",
            "identifierValue": "EX-1",
            "identifierScheme": "urn:example:identifier-scheme:1",
            "identifies": "urn:example:resource:1",
            "sourceRecord": "urn:example:source-record:1",
        },
        CompactRecordRole.LIFECYCLE_EVENT: {
            "id": "urn:example:lifecycle-event:1",
            "appliesTo": "urn:example:resource:1",
            "lifecycleEventKind": "urn:ref:atlas:event-type:superseded",
            "effectiveDate": "2026-08-06T08:45:00+00:00",
            "sourceRecords": [
                "urn:example:source-record:2",
                "urn:example:source-record:1",
            ],
            "fromRelease": "urn:example:atlas-release:1",
            "toRelease": "urn:example:atlas-release:2",
        },
    }
    return records[role]


@pytest.mark.parametrize("role", list(CompactRecordRole))
def test_closed_roles_normalize_and_emit_one_exact_summary_projection(
    role: CompactRecordRole,
) -> None:
    normalized = normalize_compact_record(role, _record(role))
    repeated = normalize_compact_record(role, normalized)
    summary = summarize_compact_records(role, [normalized])

    assert repeated == normalized
    assert normalized["canonicalPayloadDigest"].startswith("sha256:")
    assert summary["recordRole"] == role.value
    assert summary["recordIds"] == [normalized["id"]]
    for field_name in _SUMMARY_FIELD.values():
        assert len(summary[field_name]) == (1 if field_name == _SUMMARY_FIELD[role] else 0)


def test_record_pack_serializes_only_a_small_summary_receipt_and_rebuilds_full_summary(
    tmp_path: Path,
) -> None:
    defaults = {
        "release": "urn:example:atlas-release:1",
        "scheme": "urn:example:scheme:1",
        "semanticRing": "subject",
        "resourceProfile": "conceptScheme",
        "sourceRecord": "urn:example:source-record:1",
    }
    rows = [
        {"id": "urn:example:resource:2"},
        {"id": "urn:example:resource:1"},
    ]
    inventory = write_compact_record_pack(
        tmp_path,
        _header(CompactRecordRole.RESOURCE, defaults=defaults),
        rows,
    )
    descriptor = inventory.to_dict()
    receipt = descriptor["globalInvariantSummary"]
    assert receipt == {
        "schemaVersion": "1.0",
        "recordRole": "Resource",
        "recordCount": 2,
        "fieldCounts": {
            "evidenceLinks": 0,
            "identifierClaims": 0,
            "labelClaims": 0,
            "recordIds": 2,
            "releaseRecords": 0,
            "resourceOwnership": 2,
            "sourceRecordLinks": 0,
            "statementEndpoints": 0,
            "lifecycleEvents": 0,
        },
        "digest": receipt["digest"],
    }
    assert descriptor["recordSchemaVersion"] == "1.0"
    serialized_descriptor = json.dumps(descriptor, sort_keys=True)
    assert "urn:example:resource:1" not in serialized_descriptor
    assert "resourceOwnership\"" in serialized_descriptor

    stored = read_compact_record_pack(tmp_path, descriptor)
    assert stored.global_invariant_summary is not None
    assert stored.global_invariant_summary["recordIds"] == [
        "urn:example:resource:1",
        "urn:example:resource:2",
    ]
    assert stored.global_invariant_summary["resourceOwnership"] == [
        {
            "id": "urn:example:resource:1",
            **defaults,
        },
        {
            "id": "urn:example:resource:2",
            **defaults,
        },
    ]
    header = json.loads(stored.content.splitlines()[0])
    assert header["recordSchemaVersion"] == "1.0"
    assert header["globalInvariantSummaryDigest"] == receipt["digest"]
    assert "resourceOwnership" not in header


def test_record_pack_is_stable_after_set_like_normalization_and_input_reordering() -> None:
    first_record = _record(CompactRecordRole.RESOURCE)
    second_record = {
        **first_record,
        "id": "urn:example:resource:2",
        "notes": ["Fourth", "Third"],
    }
    first = build_compact_record_pack(
        _header(CompactRecordRole.RESOURCE),
        [first_record, second_record],
    )
    second = build_compact_record_pack(
        _header(CompactRecordRole.RESOURCE),
        [
            {**second_record, "notes": ["Third", "Fourth"]},
            {**first_record, "notes": ["First", "Second"], "notations": ["A", "B"]},
        ],
    )

    assert second.content == first.content
    assert second.transport == first.transport
    assert second.inventory.to_dict() == first.inventory.to_dict()
    assert second.global_invariant_summary == first.global_invariant_summary


def test_closed_record_roles_reject_unknown_fields_and_invalid_conditions() -> None:
    with pytest.raises(CompactPackError, match="unknown fields: surprise"):
        normalize_compact_record(
            CompactRecordRole.RESOURCE,
            {**_record(CompactRecordRole.RESOURCE), "surprise": True},
        )
    with pytest.raises(CompactPackError, match="expected one of Resource"):
        normalize_compact_record("resources", _record(CompactRecordRole.RESOURCE))
    with pytest.raises(CompactPackError, match="fields are not admitted by Resource"):
        build_compact_record_pack(
            _header(CompactRecordRole.RESOURCE, defaults={"surprise": True}),
            [],
        )
    with pytest.raises(CompactPackError, match="same-ring statements require semanticRing"):
        normalize_compact_record(
            CompactRecordRole.STATEMENT,
            {
                **_record(CompactRecordRole.STATEMENT),
                "sourceRing": "subject",
                "targetRing": "entity",
            },
        )
    with pytest.raises(CompactPackError, match="SourceRelease field mismatch"):
        normalize_compact_record(
            CompactRecordRole.RELEASE,
            {
                **_record(CompactRecordRole.RELEASE),
                "semanticRing": "subject",
            },
        )


def test_record_digest_rejects_a_retargeted_logical_record() -> None:
    normalized = normalize_compact_record(
        CompactRecordRole.RESOURCE,
        _record(CompactRecordRole.RESOURCE),
    )
    with pytest.raises(CompactPackError, match="digest does not match"):
        normalize_compact_record(
            CompactRecordRole.RESOURCE,
            {**normalized, "release": "urn:example:atlas-release:other"},
        )


def test_statement_supersedes_and_lifecycle_sources_are_preserved_canonically() -> None:
    statement = normalize_compact_record(
        CompactRecordRole.STATEMENT,
        {
            **_record(CompactRecordRole.STATEMENT),
            "supersedesAssertion": "urn:example:statement:old",
        },
    )
    lifecycle = normalize_compact_record(
        CompactRecordRole.LIFECYCLE_EVENT,
        _record(CompactRecordRole.LIFECYCLE_EVENT),
    )

    assert statement["supersedesAssertion"] == "urn:example:statement:old"
    assert lifecycle["sourceRecords"] == [
        "urn:example:source-record:1",
        "urn:example:source-record:2",
    ]
    with pytest.raises(CompactPackError, match="expected at least one source record"):
        normalize_compact_record(
            CompactRecordRole.LIFECYCLE_EVENT,
            {**_record(CompactRecordRole.LIFECYCLE_EVENT), "sourceRecords": []},
        )


def test_source_record_preserves_native_payload_null_but_other_nulls_fail(
    tmp_path: Path,
) -> None:
    source_record = {
        **_record(CompactRecordRole.SOURCE_RECORD),
        "nativePayload": {
            "optional": None,
            "nested": ["kept", None, {"alsoNull": None}],
        },
    }
    inventory = write_compact_record_pack(
        tmp_path,
        _header(CompactRecordRole.SOURCE_RECORD),
        [source_record],
    )
    stored = read_compact_record_pack(tmp_path, inventory)

    assert stored.rows[0]["nativePayload"] == source_record["nativePayload"]
    with pytest.raises(CompactPackError, match="null is forbidden"):
        normalize_compact_record(
            CompactRecordRole.RESOURCE,
            {**_record(CompactRecordRole.RESOURCE), "definition": None},
        )
    with pytest.raises(CompactPackError, match="floating-point values are forbidden"):
        normalize_compact_record(
            CompactRecordRole.SOURCE_RECORD,
            {**source_record, "nativePayload": {"ratio": 0.5}},
        )


def test_summary_receipt_rejects_count_tampering(tmp_path: Path) -> None:
    inventory = write_compact_record_pack(
        tmp_path,
        _header(CompactRecordRole.RESOURCE),
        [_record(CompactRecordRole.RESOURCE)],
    )
    descriptor = json.loads(json.dumps(inventory.to_dict()))
    descriptor["globalInvariantSummary"]["fieldCounts"]["resourceOwnership"] = 0

    with pytest.raises(CompactPackError, match="resourceOwnership: expected 1"):
        read_compact_record_pack(tmp_path, descriptor)


def test_fully_repinned_summary_tampering_still_fails_against_authenticated_rows(
    tmp_path: Path,
) -> None:
    artifact = build_compact_record_pack(
        _header(CompactRecordRole.RESOURCE),
        [_record(CompactRecordRole.RESOURCE)],
    )
    descriptor = artifact.inventory.to_dict()
    replacement_digest = _DIGEST_B
    descriptor["globalInvariantSummary"]["digest"] = replacement_digest

    lines = artifact.content.splitlines(keepends=True)
    header = json.loads(lines[0])
    header["globalInvariantSummaryDigest"] = replacement_digest
    content = canonical_json_bytes(header) + b"".join(lines[1:])
    transport = compact_pack.zstd.compress(content, level=9)
    content_digest = sha256_digest(content)
    descriptor["content"]["digest"] = content_digest
    descriptor["content"]["byteLength"] = len(content)
    descriptor["transport"]["digest"] = sha256_digest(transport)
    descriptor["transport"]["byteLength"] = len(transport)
    descriptor["packId"] = compact_pack.PACK_ID_PREFIX + content_digest.removeprefix("sha256:")
    target = tmp_path.joinpath(*descriptor["path"].split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(transport)

    with pytest.raises(CompactPackError, match="summary does not match"):
        read_compact_record_pack(tmp_path, descriptor)


def test_explicit_compression_level_preserves_logical_content_identity() -> None:
    rows = [
        {
            **_record(CompactRecordRole.SOURCE_RECORD),
            "nativePayload": {"repeated": "atlas " * 2_000},
        }
    ]

    fast = build_compact_record_pack(
        _header(CompactRecordRole.SOURCE_RECORD),
        rows,
        compression_level=1,
    )
    repeated = build_compact_record_pack(
        _header(CompactRecordRole.SOURCE_RECORD),
        rows,
        compression_level=1,
    )
    dense = build_compact_record_pack(
        _header(CompactRecordRole.SOURCE_RECORD),
        rows,
        compression_level=9,
    )

    assert repeated.transport == fast.transport
    assert dense.content == fast.content
    assert dense.inventory.pack_id == fast.inventory.pack_id
    assert dense.inventory.logical_rows_digest == fast.inventory.logical_rows_digest


@pytest.mark.parametrize("compression_level", (True, 0, 23))
def test_compact_pack_rejects_invalid_compression_level(
    compression_level: object,
) -> None:
    with pytest.raises(CompactPackError, match="compression_level"):
        build_compact_record_pack(
            _header(CompactRecordRole.RESOURCE),
            [_record(CompactRecordRole.RESOURCE)],
            compression_level=compression_level,  # type: ignore[arg-type]
        )

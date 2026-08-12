from __future__ import annotations

import pytest

from refspec.atlas.compact_pack import (
    CompactPackError,
    CompactRecordRole,
    normalize_compact_record,
)

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64





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








def test_closed_record_roles_reject_unknown_fields_and_invalid_conditions() -> None:
    with pytest.raises(CompactPackError, match="unknown fields: surprise"):
        normalize_compact_record(
            CompactRecordRole.RESOURCE,
            {**_record(CompactRecordRole.RESOURCE), "surprise": True},
        )
    with pytest.raises(CompactPackError, match="expected one of Resource"):
        normalize_compact_record("resources", _record(CompactRecordRole.RESOURCE))
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


def test_source_record_preserves_native_payload_null_but_other_nulls_fail() -> None:
    source_record = {
        **_record(CompactRecordRole.SOURCE_RECORD),
        "nativePayload": {
            "optional": None,
            "nested": ["kept", None, {"alsoNull": None}],
        },
    }
    normalized = normalize_compact_record(
        CompactRecordRole.SOURCE_RECORD,
        source_record,
    )

    assert normalized["nativePayload"] == source_record["nativePayload"]
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









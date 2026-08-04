from __future__ import annotations

import uuid

import pytest

from refspec.registry.infrastructure.source_identity import (
    SourceCaptureEvent,
    SourceIdentityError,
    SourceRegistrationEvent,
    derive_uuid7,
    uuid7_timestamp_milliseconds,
    validate_uuid7,
    validate_uuid7_urn,
)

FETCHED_AT = "2026-08-03T23:25:59Z"
FETCH_ID = "019fc9f2-c758-7b5c-9c19-f7fe5e2bf611"


def test_capture_event_validates_uuidv7_and_explicit_time() -> None:
    event = SourceCaptureEvent(fetch_id=FETCH_ID, fetched_at=FETCHED_AT)

    parsed = uuid.UUID(event.fetch_id)
    assert parsed.version == 7
    assert validate_uuid7(event.fetch_id) == event.fetch_id
    assert uuid7_timestamp_milliseconds(event.fetch_id) == 1_785_799_559_000
    assert event.as_dict() == {
        "fetchId": FETCH_ID,
        "fetchedAt": FETCHED_AT,
    }


def test_derived_local_ids_are_repeatable_distinct_uuidv7_urns() -> None:
    event = SourceRegistrationEvent(
        registration_id=FETCH_ID,
        registered_at=FETCHED_AT,
    )

    first = event.derived_record_urn(purpose="term", source_key="subject/1")
    rebuilt = event.derived_record_urn(purpose="term", source_key="subject/1")
    second = event.derived_record_urn(purpose="term", source_key="subject/2")

    assert first == rebuilt
    assert first != second
    assert validate_uuid7_urn(first) == first
    assert uuid.UUID(first.removeprefix("urn:uuid:")).version == 7
    assert derive_uuid7(FETCHED_AT, seed=b"seed") == derive_uuid7(
        FETCHED_AT,
        seed=b"seed",
    )


def test_registration_event_uses_distinct_manifest_names() -> None:
    event = SourceRegistrationEvent(
        registration_id=FETCH_ID,
        registered_at=FETCHED_AT,
    )

    assert event.as_dict() == {
        "registrationId": FETCH_ID,
        "registeredAt": FETCHED_AT,
    }


def test_capture_event_rejects_non_v7_or_mismatched_timestamp() -> None:
    with pytest.raises(SourceIdentityError, match="lowercase"):
        validate_uuid7(FETCH_ID.upper())

    with pytest.raises(SourceIdentityError, match="UUIDv7"):
        SourceCaptureEvent(
            fetch_id="123e4567-e89b-42d3-a456-426614174000",
            fetched_at=FETCHED_AT,
        )

    with pytest.raises(SourceIdentityError, match="does not match"):
        SourceCaptureEvent(
            fetch_id=FETCH_ID,
            fetched_at="2026-08-03T23:26:00Z",
        )

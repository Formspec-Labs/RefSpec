"""Local UUIDv7 identities for source acquisitions and durable source records.

Publisher identifiers remain the authority for publisher concepts.  These
helpers create RefSpec-owned identifiers only for acquisition events and local
source records when a publisher supplies no record identifier.  A caller must
persist the generated acquisition UUID and must carry a local record UUID
forward explicitly after reconciliation; rebuilding a capture must never
silently generate a different history.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


class SourceIdentityError(ValueError):
    """A local acquisition or record identity is malformed or inconsistent."""


def parse_aware_datetime(value: str, *, label: str) -> datetime:
    """Parse a timezone-aware ISO 8601 date-time into UTC.

    Callers that own a different domain exception should catch
    ``SourceIdentityError`` and remap the message.
    """

    if not isinstance(value, str) or not value.strip():
        raise SourceIdentityError(f"{label} must be a non-empty ISO 8601 date-time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise SourceIdentityError(f"{label} must be an ISO 8601 date-time") from error
    if parsed.tzinfo is None:
        raise SourceIdentityError(f"{label} must include a time zone")
    return parsed.astimezone(UTC)


def require_aware_datetime_text(value: object, *, label: str) -> str:
    """Validate a timezone-aware ISO 8601 date-time and return the original text."""

    if not isinstance(value, str):
        raise SourceIdentityError(f"{label} must be a non-empty ISO 8601 date-time")
    parse_aware_datetime(value, label=label)
    return value


def _timestamp_milliseconds(value: str, *, label: str) -> int:
    parsed = parse_aware_datetime(value, label=label)
    milliseconds = int(parsed.timestamp() * 1_000)
    if milliseconds < 0 or milliseconds >= 1 << 48:
        raise SourceIdentityError(f"{label} is outside the UUIDv7 timestamp range")
    return milliseconds


def _uuid7_from_parts(timestamp_ms: int, random_bits: int) -> uuid.UUID:
    if random_bits < 0 or random_bits >= 1 << 74:
        raise SourceIdentityError("UUIDv7 random bits must fit in 74 bits")
    random_a = random_bits >> 62
    random_b = random_bits & ((1 << 62) - 1)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= random_a << 64
    value |= 0b10 << 62
    value |= random_b
    return uuid.UUID(int=value)


def generate_uuid7(recorded_at: str) -> str:
    """Generate a UUIDv7 whose embedded timestamp matches ``recorded_at``.

    The caller records the returned value once.  Rebuilds receive that recorded
    value as input instead of calling this function again.
    """

    timestamp_ms = _timestamp_milliseconds(recorded_at, label="recorded_at")
    return str(_uuid7_from_parts(timestamp_ms, secrets.randbits(74)))


def derive_uuid7(recorded_at: str, *, seed: bytes) -> str:
    """Derive a repeatable UUIDv7 within one already-recorded acquisition.

    This is used for local rows created by a capture.  It does not infer
    cross-capture identity: reconciliation must decide whether a prior local
    record UUID is carried forward.
    """

    if not isinstance(seed, bytes) or not seed:
        raise SourceIdentityError("UUIDv7 derivation seed must be non-empty bytes")
    timestamp_ms = _timestamp_milliseconds(recorded_at, label="recorded_at")
    random_bits = int.from_bytes(hashlib.sha256(seed).digest(), "big") >> (256 - 74)
    return str(_uuid7_from_parts(timestamp_ms, random_bits))


def validate_uuid7(value: str, *, label: str = "UUIDv7") -> str:
    """Return the canonical UUID spelling after validating version and variant."""

    if not isinstance(value, str):
        raise SourceIdentityError(f"{label} must be text")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as error:
        raise SourceIdentityError(f"{label} must be a UUID") from error
    if parsed.version != 7 or parsed.variant != uuid.RFC_4122:
        raise SourceIdentityError(f"{label} must be an RFC 9562 UUIDv7")
    if value != str(parsed):
        raise SourceIdentityError(f"{label} must use canonical lowercase UUID spelling")
    return value


def validate_uuid7_urn(value: str, *, label: str = "UUIDv7 URN") -> str:
    """Return a canonical ``urn:uuid:`` value containing a UUIDv7."""

    prefix = "urn:uuid:"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise SourceIdentityError(f"{label} must use urn:uuid:<UUIDv7>")
    validate_uuid7(value.removeprefix(prefix), label=label)
    return value


def uuid7_timestamp_milliseconds(value: str) -> int:
    """Read the Unix-millisecond timestamp embedded in a valid UUIDv7."""

    canonical = validate_uuid7(value)
    return uuid.UUID(canonical).int >> 80


@dataclass(frozen=True, slots=True)
class SourceCaptureEvent:
    """One recorded acquisition run and its explicit wall-clock time."""

    fetch_id: str
    fetched_at: str

    def __post_init__(self) -> None:
        validate_uuid7(self.fetch_id, label="fetch_id")
        expected_ms = _timestamp_milliseconds(self.fetched_at, label="fetched_at")
        if uuid7_timestamp_milliseconds(self.fetch_id) != expected_ms:
            raise SourceIdentityError("fetch_id timestamp does not match fetched_at")

    @classmethod
    def generate(cls, *, fetched_at: str) -> SourceCaptureEvent:
        """Create a new event whose UUID must then be persisted by the caller."""

        return cls(fetch_id=generate_uuid7(fetched_at), fetched_at=fetched_at)

    def as_dict(self) -> dict[str, str]:
        """Return the stable manifest representation."""

        return {
            "fetchId": self.fetch_id,
            "fetchedAt": self.fetched_at,
        }

    def derived_record_urn(self, *, purpose: str, source_key: str) -> str:
        """Create a UUIDv7 URN unique within this acquisition event."""

        if not purpose.strip() or not source_key.strip():
            raise SourceIdentityError("derived record purpose and source_key must not be empty")
        seed = f"refspec-source-identity-v1\n{self.fetch_id}\n{purpose}\n{source_key}\n".encode()
        return "urn:uuid:" + derive_uuid7(self.fetched_at, seed=seed)


@dataclass(frozen=True, slots=True)
class SourceRegistrationEvent:
    """One recorded RefSpec package registration and its wall-clock time."""

    registration_id: str
    registered_at: str

    def __post_init__(self) -> None:
        validate_uuid7(self.registration_id, label="registration_id")
        expected_ms = _timestamp_milliseconds(self.registered_at, label="registered_at")
        if uuid7_timestamp_milliseconds(self.registration_id) != expected_ms:
            raise SourceIdentityError("registration_id timestamp does not match registered_at")

    @classmethod
    def generate(cls, *, registered_at: str) -> SourceRegistrationEvent:
        """Create a package registration whose UUID must be persisted by the caller."""

        return cls(
            registration_id=generate_uuid7(registered_at),
            registered_at=registered_at,
        )

    def as_dict(self) -> dict[str, str]:
        """Return the stable manifest representation."""

        return {
            "registrationId": self.registration_id,
            "registeredAt": self.registered_at,
        }

    def derived_record_urn(self, *, purpose: str, source_key: str) -> str:
        """Create a repeatable UUIDv7 URN for a row first registered in this package."""

        if not purpose.strip() or not source_key.strip():
            raise SourceIdentityError("derived record purpose and source_key must not be empty")
        seed = (f"refspec-source-registration-v1\n{self.registration_id}\n{purpose}\n{source_key}\n").encode()
        return "urn:uuid:" + derive_uuid7(self.registered_at, seed=seed)


__all__ = [
    "SourceCaptureEvent",
    "SourceIdentityError",
    "SourceRegistrationEvent",
    "derive_uuid7",
    "generate_uuid7",
    "parse_aware_datetime",
    "require_aware_datetime_text",
    "uuid7_timestamp_milliseconds",
    "validate_uuid7",
    "validate_uuid7_urn",
]

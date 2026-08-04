"""Structured, repeatable identifiers retained from controlled-resource sources."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from refspec.registry.infrastructure.identifier_validation import (
    absolute_uri_issue,
    is_sha256_digest,
    parse_iso_date_or_datetime,
)


class ControlledIdentifierError(ValueError):
    """A source identifier lacks the evidence needed to interpret it."""


def _require_text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise ControlledIdentifierError(f"{field} must not be empty")
    return text


def _require_uri(value: str, field: str) -> str:
    uri = _require_text(value, field)
    issue = absolute_uri_issue(uri)
    if issue == "missing-scheme":
        raise ControlledIdentifierError(f"{field} must be an absolute URI")
    if issue == "credentials":
        raise ControlledIdentifierError(f"{field} must not contain credentials")
    return uri


def validate_identifier_date(
    value: str,
    field: str = "identifier date",
) -> str:
    text = _require_text(value, field)
    try:
        parse_iso_date_or_datetime(text)
    except ValueError as error:
        raise ControlledIdentifierError(f"{field} must be an ISO 8601 date or date-time") from error
    return text


@dataclass(frozen=True, slots=True)
class ControlledIdentifier:
    """One publisher-observed identifier with explicit source context."""

    value: str
    kind: str
    authority_uri: str
    source_uri: str
    observed_at: str | None
    effective_at: str | None
    source_digest: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.value, "identifier value")
        _require_text(self.kind, "identifier kind")
        _require_uri(self.authority_uri, "identifier authority_uri")
        _require_uri(self.source_uri, "identifier source_uri")
        for value, field in (
            (self.observed_at, "identifier observed_at"),
            (self.effective_at, "identifier effective_at"),
        ):
            if value is not None:
                validate_identifier_date(value, field)
        if self.source_digest is not None and not is_sha256_digest(self.source_digest):
            raise ControlledIdentifierError(
                "identifier source_digest must be a lowercase sha256:<64 hex> digest"
            )

    def as_dict(self) -> dict[str, str | None]:
        """Return every field, including explicit unknown dates."""

        return {
            "value": self.value,
            "kind": self.kind,
            "authorityUri": self.authority_uri,
            "sourceUri": self.source_uri,
            "observedAt": self.observed_at,
            "effectiveAt": self.effective_at,
            "sourceDigest": self.source_digest,
        }


def distinct_identifiers(
    values: Iterable[ControlledIdentifier],
) -> tuple[ControlledIdentifier, ...]:
    """Retain ordered distinct identifier observations."""

    result: list[ControlledIdentifier] = []
    seen: set[tuple[str, str, str, str, str | None, str | None, str | None]] = set()
    for identifier in values:
        key = (
            identifier.kind,
            identifier.value,
            identifier.authority_uri,
            identifier.source_uri,
            identifier.observed_at,
            identifier.effective_at,
            identifier.source_digest,
        )
        if key not in seen:
            seen.add(key)
            result.append(identifier)
    return tuple(result)


def identifier_values(
    identifiers: Iterable[ControlledIdentifier],
    *,
    kinds: frozenset[str],
) -> tuple[str, ...]:
    """Read distinct values for selected compatibility kinds."""

    values: list[str] = []
    seen: set[str] = set()
    for identifier in identifiers:
        if identifier.kind not in kinds or identifier.value in seen:
            continue
        seen.add(identifier.value)
        values.append(identifier.value)
    return tuple(values)


__all__ = [
    "ControlledIdentifier",
    "ControlledIdentifierError",
    "distinct_identifiers",
    "identifier_values",
    "validate_identifier_date",
]

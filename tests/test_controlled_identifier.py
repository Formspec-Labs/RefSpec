"""Tests for repeatable source identifiers and their observation dates."""

from __future__ import annotations

import pytest

from refspec.registry.controlled_identifier import (
    ControlledIdentifier,
    ControlledIdentifierError,
    distinct_identifiers,
)

SOURCE_DIGEST = "sha256:" + ("a" * 64)


def _identifier(**changes: str | None) -> ControlledIdentifier:
    values: dict[str, str | None] = {
        "value": "24042",
        "kind": "publisherCode",
        "authority_uri": "https://example.test/thesaurus",
        "source_uri": "https://example.test/thesaurus/index",
        "observed_at": None,
        "effective_at": None,
        "source_digest": SOURCE_DIGEST,
    }
    values.update(changes)
    return ControlledIdentifier(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value",
    [
        ("observed_at", "2026-07-30"),
        ("observed_at", "2026-07-30T12:34:56Z"),
        ("observed_at", "2026-07-30T12:34:56.123456-04:00"),
        ("effective_at", "2026-07-30"),
        ("effective_at", "2026-07-30T12:34:56+00:00"),
    ],
)
def test_identifier_dates_accept_iso_dates_and_date_times(
    field: str,
    value: str,
) -> None:
    identifier = _identifier(**{field: value})

    assert getattr(identifier, field) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "July 30, 2026",
        "2026-02-30",
        "2026-07-30 12:34:56Z",
        "2026-07-30T12:34Z",
        "2026-07-30T12:34:56+0000",
    ],
)
def test_identifier_dates_reject_non_iso_or_impossible_values(value: str) -> None:
    with pytest.raises(ControlledIdentifierError, match="empty|ISO 8601"):
        _identifier(observed_at=value)


def test_identifier_serialization_retains_explicit_unknown_dates() -> None:
    assert _identifier().as_dict() == {
        "value": "24042",
        "kind": "publisherCode",
        "authorityUri": "https://example.test/thesaurus",
        "sourceUri": "https://example.test/thesaurus/index",
        "observedAt": None,
        "effectiveAt": None,
        "sourceDigest": SOURCE_DIGEST,
    }


def test_distinct_identifiers_removes_only_exact_repeated_observations() -> None:
    first = _identifier()
    later = _identifier(observed_at="2026-07-30")

    assert distinct_identifiers((first, first, later)) == (first, later)

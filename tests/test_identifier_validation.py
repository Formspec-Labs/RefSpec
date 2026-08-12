"""Shared identifier validation primitives used by SCR and ControlledIdentifier."""

from __future__ import annotations

import pytest

from refspec.registry.infrastructure.identifier_validation import (
    absolute_uri_issue,
    is_sha256_digest,
    parse_iso_date_or_datetime,
)


def test_sha256_digest_requires_lowercase_prefixed_hex() -> None:
    assert is_sha256_digest("sha256:" + ("a" * 64))
    assert not is_sha256_digest("sha256:" + ("A" * 64))
    assert not is_sha256_digest("a" * 64)


def test_absolute_uri_issue_codes() -> None:
    assert absolute_uri_issue("https://example.test/id") is None
    assert absolute_uri_issue("not-a-uri") == "missing-scheme"
    assert absolute_uri_issue("https://user:pass@example.test/id") == "credentials"


def test_absolute_uri_issue_refuses_characters_rfc_3987_excludes() -> None:
    """The exact class that put 7,770 unparseable IRIs in a published pack.

    A JSON-pointer-ish source path (`results.ad_hoc[5345]`) concatenated into a
    fragment is legal Python, legal rdflib, and not an IRI. Percent-encoded, it
    is fine -- so the check has to fall on the raw character, not the shape.
    """

    assert (
        absolute_uri_issue("https://example.test/topics.json#results.ad_hoc[5345]")
        == "forbidden-character"
    )
    assert (
        absolute_uri_issue("https://example.test/topics.json#results.ad_hoc%5B5345%5D")
        is None
    )
    for character in '<>"{}|^`\\[]':
        assert (
            absolute_uri_issue(f"https://example.test/a{character}b")
            == "forbidden-character"
        ), character
    for character in ("\x00", "\x1f", " ", "\x7f", "\x85", "\x9f"):
        assert (
            absolute_uri_issue(f"https://example.test/a{character}b")
            == "forbidden-character"
        ), repr(character)
    # An IP-literal host is the one place RFC 3986 admits brackets. Atlas mints
    # none, and the shared check refuses them rather than tracking components;
    # this pins that as a decision rather than an oversight.
    assert absolute_uri_issue("https://[::1]/x") == "forbidden-character"


def test_iso_date_or_datetime_accepts_date_and_optional_timezone() -> None:
    parse_iso_date_or_datetime("2026-07-30")
    parse_iso_date_or_datetime("2026-07-30T12:34:56")
    parse_iso_date_or_datetime("2026-07-30T12:34:56Z")


def test_iso_date_or_datetime_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        parse_iso_date_or_datetime("2026-02-30")
    with pytest.raises(ValueError):
        parse_iso_date_or_datetime("July 30, 2026")

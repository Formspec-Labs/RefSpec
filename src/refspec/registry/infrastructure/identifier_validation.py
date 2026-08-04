"""Shared validation primitives for controlled-source identifiers.

``ControlledIdentifier`` and SCR observation identifiers share digest format,
absolute URI/IRI checks, and overlapping date rules, but they keep distinct
public shapes:

* SCR requires ``sourcePath``, timezone-aware ``observedAt``, and a
  ``sourceDigest`` that matches the retained artifact; optional bounds are
  ``effectiveFrom`` / ``effectiveThrough``.
* ``ControlledIdentifier`` uses ``effective_at``, allows date-only values and
  optional digests, and does not carry ``sourcePath``.

A full schema merge would break package contracts, so this module only owns the
overlapping primitives. Domain modules keep their public shapes and remap
errors at the boundary.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date, datetime

SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def is_sha256_digest(value: object) -> bool:
    """Return whether ``value`` is a lowercase ``sha256:<64 hex>`` digest."""

    return isinstance(value, str) and SHA256_DIGEST.fullmatch(value) is not None


def absolute_uri_issue(value: str) -> str | None:
    """Return a short issue code for a non-absolute or credentialed URI.

    Returns ``None`` when ``value`` is an absolute URI/IRI without credentials.
    Issue codes are ``missing-scheme`` and ``credentials``.
    """

    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme:
        return "missing-scheme"
    if parsed.username is not None or parsed.password is not None:
        return "credentials"
    return None


def parse_iso_date_or_datetime(value: str) -> None:
    """Validate one ISO 8601 calendar date or date-time.

    Date-times may omit a timezone. Raises ``ValueError`` when the text is not
    an accepted ISO form or names an impossible calendar day.
    """

    if _ISO_DATE.fullmatch(value):
        date.fromisoformat(value)
        return
    if _ISO_DATETIME.fullmatch(value):
        datetime.fromisoformat(
            value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
        )
        return
    raise ValueError("not an ISO 8601 date or date-time")


__all__ = [
    "SHA256_DIGEST",
    "absolute_uri_issue",
    "is_sha256_digest",
    "parse_iso_date_or_datetime",
]

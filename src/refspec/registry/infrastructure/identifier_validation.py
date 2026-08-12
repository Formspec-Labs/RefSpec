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
# The characters RFC 3987 excludes from an IRI. `[` and `]` are gen-delims
# reserved for an IP-literal host and illegal anywhere else; the rest are the
# ASCII exclusions plus DEL and the C1 block. This mirrors the Atlas binding's
# `rdf_canonical.FORBIDDEN_IRI_CHARACTERS` term for term -- the binding cannot
# import this module (it is deliberately self-contained), so
# `test_the_binding_and_the_package_reject_the_same_credentialed_iris` is the
# running check that the two copies still agree.
_FORBIDDEN_IRI_CHARACTER = re.compile(r'[\x00-\x20\x7f-\x9f<>"{}|^`\\\[\]]')


def is_sha256_digest(value: object) -> bool:
    """Return whether ``value`` is a lowercase ``sha256:<64 hex>`` digest."""

    return isinstance(value, str) and SHA256_DIGEST.fullmatch(value) is not None


def absolute_uri_issue(value: str) -> str | None:
    """Return a short issue code for a URI this repository may not mint.

    Returns ``None`` when ``value`` is an absolute URI/IRI without credentials
    and without a character RFC 3987 excludes. Issue codes are
    ``missing-scheme``, ``credentials`` and ``forbidden-character``.

    The character check is not decoration: 7,770 published ``sourceLocator``
    IRIs carried raw ``[``/``]`` from JSON-pointer-ish source paths, which
    rdflib accepted and every strict RDF parser refused. Adapters that build an
    IRI from source text percent-encode it at the mint; this is the shared
    check that says so once.
    """

    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme:
        return "missing-scheme"
    if parsed.username is not None or parsed.password is not None:
        return "credentials"
    if _FORBIDDEN_IRI_CHARACTER.search(value):
        return "forbidden-character"
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

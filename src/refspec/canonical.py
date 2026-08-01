"""Canonical JSON, digests, and content-derived RefSpec identifiers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any


DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CanonicalValueError(ValueError):
    """A value cannot be represented by the RefSpec canonical JSON profile."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize finite JSON using the RefSpec canonical byte profile."""

    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise CanonicalValueError(
            "value is not finite JSON under the RefSpec canonical profile"
        ) from error
    return rendered.encode("utf-8")


def canonical_digest(
    value: Any,
    *,
    omit_root_fields: Iterable[str] = (),
) -> str:
    """Hash canonical JSON after omitting only named root object fields."""

    omitted_fields = tuple(omit_root_fields)
    if not isinstance(value, Mapping):
        if omitted_fields:
            raise CanonicalValueError("root-field omission requires a JSON object")
        payload: Any = value
    else:
        omitted = frozenset(omitted_fields)
        payload = {key: child for key, child in value.items() if key not in omitted}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def stable_record(
    payload: Mapping[str, Any],
    *,
    id_field: str,
    digest_field: str,
    id_prefix: str,
) -> dict[str, Any]:
    """Seal identity-defining fields with a digest-derived identifier."""

    if id_field in payload or digest_field in payload:
        raise CanonicalValueError(
            f"payload must omit generated fields {id_field!r} and " f"{digest_field!r}"
        )
    digest = canonical_digest(payload)
    identifier = id_prefix + digest.removeprefix("sha256:")
    return {
        id_field: identifier,
        digest_field: digest,
        **dict(payload),
    }


def validate_stable_record(
    record: Mapping[str, Any],
    *,
    id_field: str,
    digest_field: str,
    id_prefix: str,
) -> None:
    """Verify one record's digest and content-derived identifier."""

    actual_digest = record.get(digest_field)
    actual_identifier = record.get(id_field)
    if (
        not isinstance(actual_digest, str)
        or DIGEST_PATTERN.fullmatch(actual_digest) is None
    ):
        raise CanonicalValueError(f"{digest_field} is not a SHA-256 digest")
    expected_digest = canonical_digest(
        record,
        omit_root_fields=(id_field, digest_field),
    )
    if actual_digest != expected_digest:
        raise CanonicalValueError(f"{digest_field} does not match record content")
    expected_identifier = id_prefix + expected_digest.removeprefix("sha256:")
    if actual_identifier != expected_identifier:
        raise CanonicalValueError(f"{id_field} does not match record content")


def vocabulary_release_digest(record: Mapping[str, Any]) -> str:
    """Digest a vocabulary release, omitting only its two root identity fields."""

    return canonical_digest(
        record,
        omit_root_fields=("release_id", "release_digest"),
    )


def seal_vocabulary_release(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add the canonical release digest and required release identifier."""

    if "release_id" in payload or "release_digest" in payload:
        raise CanonicalValueError(
            "release payload must omit release_id and release_digest"
        )
    digest = vocabulary_release_digest(payload)
    return {
        "release_id": (
            "urn:refspec:vocabulary-release:" + digest.removeprefix("sha256:")
        ),
        "release_digest": digest,
        **dict(payload),
    }


def validate_vocabulary_release_identity(record: Mapping[str, Any]) -> None:
    """Verify the canonical digest and identifier of a vocabulary release."""

    expected_digest = vocabulary_release_digest(record)
    if record.get("release_digest") != expected_digest:
        raise CanonicalValueError(
            "release_digest does not match the canonical release payload"
        )
    expected_id = "urn:refspec:vocabulary-release:" + expected_digest.removeprefix(
        "sha256:"
    )
    if record.get("release_id") != expected_id:
        raise CanonicalValueError(
            "release_id does not match the canonical release payload"
        )

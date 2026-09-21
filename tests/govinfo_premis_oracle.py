"""Frozen PREMIS reader/check from RefSpec 7f0d5614, copied before replacement.

Only unchanged domain models, hashing and identifier construction are imported.
The XML parsing, source-pin verification and acceptance decisions are independent.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

from refspec.registry.govinfo_collections import (
    GOVINFO_IDENTIFIER_AUTHORITY_URI,
    AcquiredGovInfoSource,
    GovInfoFixityRecord,
    GovInfoSnapshotPin,
    GovInfoSourceDriftError,
    ParsedGovInfoPackageFixity,
    _make_identifier,
    sha256_digest,
)

_PREMIS_NS = "info:lc/xmlns/premis-v2"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _verify_payload(payload: bytes, pin: GovInfoSnapshotPin, *, location: str) -> tuple[str, int]:
    """Raise GovInfoSourceDriftError unless payload matches the pin's byte length, digest, and content kind."""

    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise GovInfoSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise GovInfoSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    if pin.source.content_kind == "json":
        try:
            json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GovInfoSourceDriftError(f"{location} is not valid JSON") from error
    else:
        try:
            ElementTree.fromstring(payload)
        except ElementTree.ParseError as error:
            raise GovInfoSourceDriftError(f"{location} is not valid XML") from error
    return actual_sha256, byte_length


def _premis_tag(name: str) -> str:
    return f"{{{_PREMIS_NS}}}{name}"


def parse_govinfo_cfr_package_fixity(
    acquired: AcquiredGovInfoSource,
    *,
    expected_package_id: str,
) -> ParsedGovInfoPackageFixity:
    """Parse a package's PREMIS record for its SHA-256 file fixity digests.

    A ``file`` object without a ``fixity`` element is skipped: GovInfo only
    computes fixity for a subset of a package's file objects (see
    GOVINFO_PORTFOLIO_GAPS). A ``fixity`` element with an algorithm other
    than SHA-256 is treated as drift, since no non-SHA-256 digest has ever
    been observed from this source.
    """

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed GovInfo package PREMIS source")
    root = ElementTree.fromstring(payload)
    if root.tag != _premis_tag("premis"):
        raise GovInfoSourceDriftError("PREMIS payload root element is not a premis-v2 <premis> document")

    records: list[GovInfoFixityRecord] = []
    seen_object_ids: set[str] = set()
    for obj in root.findall(_premis_tag("object")):
        if obj.get(f"{{{_XSI_NS}}}type") != "file":
            continue
        fixity_el = obj.find(f"{_premis_tag('objectCharacteristics')}/{_premis_tag('fixity')}")
        if fixity_el is None:
            continue

        identifier_type_el = obj.find(f"{_premis_tag('objectIdentifier')}/{_premis_tag('objectIdentifierType')}")
        identifier_value_el = obj.find(f"{_premis_tag('objectIdentifier')}/{_premis_tag('objectIdentifierValue')}")
        if identifier_type_el is None or identifier_type_el.text != "FDsys ACP":
            raise GovInfoSourceDriftError("PREMIS file object uses an unrecognized objectIdentifierType")
        if identifier_value_el is None or not (identifier_value_el.text or "").strip():
            raise GovInfoSourceDriftError("PREMIS file object is missing an objectIdentifierValue")
        object_identifier_value = identifier_value_el.text.strip()  # type: ignore[union-attr]

        algorithm_el = fixity_el.find(_premis_tag("messageDigestAlgorithm"))
        digest_el = fixity_el.find(_premis_tag("messageDigest"))
        if algorithm_el is None or algorithm_el.text != "SHA-256":
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} uses an unsupported fixity algorithm"
            )
        digest = (digest_el.text or "").strip().lower() if digest_el is not None else ""
        if _HEX64.fullmatch(digest) is None:
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} has a malformed SHA-256 digest"
            )

        original_name_el = obj.find(_premis_tag("originalName"))
        if original_name_el is None or not (original_name_el.text or "").strip():
            raise GovInfoSourceDriftError(f"PREMIS file object {object_identifier_value} is missing originalName")
        original_name = original_name_el.text.strip()  # type: ignore[union-attr]
        if not original_name.startswith(expected_package_id):
            raise GovInfoSourceDriftError(
                f"PREMIS file object originalName {original_name!r} does not belong to {expected_package_id!r}"
            )

        location_type_el = obj.find(
            f"{_premis_tag('storage')}/{_premis_tag('contentLocation')}/{_premis_tag('contentLocationType')}"
        )
        location_value_el = obj.find(
            f"{_premis_tag('storage')}/{_premis_tag('contentLocation')}/{_premis_tag('contentLocationValue')}"
        )
        if location_type_el is None or location_type_el.text != "URI":
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} contentLocationType is not URI"
            )
        if location_value_el is None or not (location_value_el.text or "").strip():
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} is missing contentLocationValue"
            )
        content_location_uri = location_value_el.text.strip().rsplit(" ", 1)[-1]  # type: ignore[union-attr]
        parsed_uri = urlsplit(content_location_uri)
        if parsed_uri.scheme != "https" or parsed_uri.hostname != "www.govinfo.gov":
            raise GovInfoSourceDriftError(
                f"PREMIS file object {object_identifier_value} contentLocationValue is not a www.govinfo.gov HTTPS URI"
            )

        if object_identifier_value in seen_object_ids:
            raise GovInfoSourceDriftError(f"PREMIS payload repeats objectIdentifierValue {object_identifier_value!r}")
        seen_object_ids.add(object_identifier_value)

        identifier = _make_identifier(
            value=digest,
            kind="govInfoPremisSha256Fixity",
            authority_uri=GOVINFO_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.source.source_url,
            observed_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        )
        records.append(
            GovInfoFixityRecord(
                object_identifier_value=object_identifier_value,
                original_name=original_name,
                content_location_uri=content_location_uri,
                algorithm="SHA-256",
                digest=digest,
                identifiers=(identifier,),
            )
        )

    if not records:
        raise GovInfoSourceDriftError("PREMIS payload does not contain any SHA-256 file fixity records")

    return ParsedGovInfoPackageFixity(
        package_id=expected_package_id,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        records=tuple(records),
    )

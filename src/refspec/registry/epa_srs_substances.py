"""Identifier-shape capture for EPA Substance Registry Services and CompTox.

EPA's Substance Registry Services (SRS), the CompTox Chemicals Dashboard, and
the Distributed Structure-Searchable Toxicity (DSSTox) database assign two
distinct, non-interchangeable identifiers to a chemical substance:

* DTXSID -- a *substance* identifier.  It can name a mixture, a salt, or any
  other substance that has no single defined chemical structure.
* DTXCID -- a *structure* identifier for one defined chemical structure.

One DTXSID can relate to zero, one, or more DTXCID structures.  The two
identifier kinds use different prefixes and are validated by different
functions below, so a value can never satisfy both at once -- this module
never merges substance identity into structure identity or the reverse.

Toxic Substances Control Act (TSCA) Inventory membership is captured as a
plain status value on a substance record.  It is list membership, not a
subject: it is never treated as a topic/label and never mints Rulespec
concept identity by itself.

This module captures identifier SHAPE (syntax rules and a public validity
check) plus a small, pinned sample of substance identifier records.  It
does not ingest bulk DSSTox/CompTox rows -- the full inventory holds several
hundred thousand substances, and none of that bulk data belongs here.

Every function here is a pure transform over bytes or values a caller
supplies.  Nothing in this module opens a network connection, reads a file,
or otherwise performs I/O; importing it is always side-effect free.

Catalog scope (verbatim source URLs this module was scoped from):
* https://sor.epa.gov/sor_internet/registry/sysofreg/sorservices/sorServices.html
* https://www.epa.gov/comptox-tools/computational-toxicology-and-exposure-apis
* https://www.epa.gov/tsca-inventory/about-tsca-chemical-substance-inventory
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier, distinct_identifiers
from refspec.storage import canonical_json

SUBSTANCE_CAPTURE_FORMAT = "urn:ref:registry:epa-srs-substance-identifier-capture:v1"
PARSER_VERSION = "epa-srs-substances-identifier-shape-v1"

# Catalog scope: the exact source URLs this module's identifier shapes and
# pinned sample were scoped from (see module docstring).
SRS_SOURCE_URI = "https://sor.epa.gov/sor_internet/registry/sysofreg/sorservices/sorServices.html"
COMPTOX_SOURCE_URI = "https://www.epa.gov/comptox-tools/computational-toxicology-and-exposure-apis"
TSCA_INVENTORY_SOURCE_URI = "https://www.epa.gov/tsca-inventory/about-tsca-chemical-substance-inventory"

# Identifier authority URIs, kept separate even though DTXSID and DTXCID are
# currently issued by the same CompTox/DSSTox system -- the two identifier
# kinds are governed distinctly and must not be collapsed into one constant.
DTXSID_AUTHORITY_URI = "https://comptox.epa.gov/dashboard/"
DTXCID_AUTHORITY_URI = "https://comptox.epa.gov/dashboard/"
# CAS Registry Numbers are governed by CAS, not EPA. A record may report one
# as observed; this module never compiles CAS's own proprietary registry.
CAS_REGISTRY_AUTHORITY_URI = "https://www.cas.org/cas-data/cas-registry"

# DTXSID/DTXCID digit counts observed across published EPA CompTox examples
# (Bisphenol A = DTXSID7020182 / DTXCID30182, cross-checked against a live
# CompTox Chemicals Dashboard capture during this module's construction).
# EPA has not published a fixed-width grammar for either identifier, so this
# bound describes observed practice, not a guaranteed invariant. A real
# capture outside it must fail loudly rather than silently widen the shape.
_DTXSID = re.compile(r"^DTXSID\d{6,9}$")
_DTXCID = re.compile(r"^DTXCID\d{4,9}$")
_CASRN = re.compile(r"^\d{2,7}-\d{2}-\d$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMPTOX_DETAIL_DTXSID = re.compile(r"/chemical/details/(DTXSID\d{6,9})")
_COMPTOX_PAGE_DTXSID = re.compile(r"DTXSID\d{6,9}")
_COMPTOX_PAGE_DTXCID = re.compile(r"DTXCID\d{4,9}")
_COMPTOX_PAGE_CASRN = re.compile(r'casrn:"(\d{2,7}-\d{2}-\d)"')
_COMPTOX_PAGE_PREFERRED_NAME = re.compile(r'preferredName:"([^"\\]+)"')

# TSCA Inventory status values as EPA's own status field distinguishes them:
# a substance can be actively on the inventory, formally inactive under the
# post-2016 Lautenberg Act reset, or absent from the inventory entirely.
TSCA_STATUSES = frozenset({"active", "inactive", "notListed"})

_RECORD_FIELDS = frozenset(
    {
        "dtxsid",
        "dtxcid",
        "casrn",
        "preferredName",
        "tscaInventoryStatus",
        "sourceUri",
    }
)


class EpaSrsSubstanceError(ValueError):
    """A substance identifier, record, or sample fails EPA SRS/CompTox shape rules."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EpaSrsSubstanceError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpaSrsSubstanceError(f"{label} must be non-empty text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, label)


def _require_https_uri(value: object, label: str) -> str:
    text = _require_text(value, label)
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise EpaSrsSubstanceError(f"{label} must be an absolute HTTPS URI")
    return text


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as error:
        raise EpaSrsSubstanceError(f"{label} must be an ISO 8601 date-time") from error
    if parsed.tzinfo is None:
        raise EpaSrsSubstanceError(f"{label} must include a time zone")
    return text


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise EpaSrsSubstanceError(
            f"{label} fields changed; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def validate_dtxsid(value: str) -> str:
    """Validate one CompTox/DSSTox *substance* identifier's syntax."""

    if not isinstance(value, str) or _DTXSID.fullmatch(value) is None:
        raise EpaSrsSubstanceError(f"DTXSID does not match the observed shape: {value!r}")
    return value


def validate_dtxcid(value: str) -> str:
    """Validate one CompTox/DSSTox *structure* identifier's syntax."""

    if not isinstance(value, str) or _DTXCID.fullmatch(value) is None:
        raise EpaSrsSubstanceError(f"DTXCID does not match the observed shape: {value!r}")
    return value


def _casrn_check_digit(leading_digits: str) -> int:
    """Compute a CAS Registry Number check digit from its leading digits.

    The published CAS check-digit algorithm sums each digit -- read right to
    left, starting at the digit immediately before the check digit -- times
    its 1-based position, then takes that sum modulo 10. This validates
    public CAS Registry Number *syntax* only; it never compiles or stores
    CAS's own proprietary name/substance registry content.
    """

    return sum(int(digit) * weight for weight, digit in enumerate(reversed(leading_digits), start=1)) % 10


def validate_casrn(value: str) -> str:
    """Validate one CAS Registry Number's syntax and public check digit."""

    if not isinstance(value, str) or _CASRN.fullmatch(value) is None:
        raise EpaSrsSubstanceError(f"CASRN does not match the observed shape: {value!r}")
    first, second, check = value.split("-")
    if _casrn_check_digit(first + second) != int(check):
        raise EpaSrsSubstanceError(f"CASRN check digit is invalid: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class SubstanceIdentifierRecord:
    """One substance's identifiers as observed on an EPA SRS/CompTox record."""

    dtxsid: str
    dtxcid: str | None
    casrn: str | None
    preferred_name: str
    tsca_inventory_status: str | None
    source_uri: str

    def __post_init__(self) -> None:
        validate_dtxsid(self.dtxsid)
        if self.dtxcid is not None:
            validate_dtxcid(self.dtxcid)
        if self.casrn is not None:
            validate_casrn(self.casrn)
        _require_text(self.preferred_name, "record.preferredName")
        if self.tsca_inventory_status is not None and self.tsca_inventory_status not in TSCA_STATUSES:
            raise EpaSrsSubstanceError(f"tscaInventoryStatus is not a recognized status: {self.tsca_inventory_status!r}")
        _require_https_uri(self.source_uri, "record.sourceUri")

    def native_payload(self) -> dict[str, Any]:
        return {
            "dtxsid": self.dtxsid,
            "dtxcid": self.dtxcid,
            "casrn": self.casrn,
            "preferredName": self.preferred_name,
            "tscaInventoryStatus": self.tsca_inventory_status,
            "sourceUri": self.source_uri,
        }


def _parse_record(value: object, index: int) -> SubstanceIdentifierRecord:
    label = f"records[{index}]"
    if not isinstance(value, Mapping):
        raise EpaSrsSubstanceError(f"{label} must be an object")
    _exact_keys(value, _RECORD_FIELDS, label)
    try:
        return SubstanceIdentifierRecord(
            dtxsid=_require_text(value["dtxsid"], f"{label}.dtxsid"),
            dtxcid=_optional_text(value["dtxcid"], f"{label}.dtxcid"),
            casrn=_optional_text(value["casrn"], f"{label}.casrn"),
            preferred_name=_require_text(value["preferredName"], f"{label}.preferredName"),
            tsca_inventory_status=_optional_text(value["tscaInventoryStatus"], f"{label}.tscaInventoryStatus"),
            source_uri=_require_https_uri(value["sourceUri"], f"{label}.sourceUri"),
        )
    except EpaSrsSubstanceError as error:
        raise EpaSrsSubstanceError(f"{label}: {error}") from error


@dataclass(frozen=True, slots=True)
class SubstanceSample:
    """A small, closed, pinned sample of EPA SRS/CompTox substance identifier records.

    Never a bulk extract: callers are expected to keep ``records`` small.
    ``conceptIdentityClaimed`` in the rendered payload is always False --
    a publisher-assigned identifier makes a record a candidate for entity
    normalization, never a minted Rulespec concept by itself.
    """

    captured_at: str
    source_digest: str
    records: tuple[SubstanceIdentifierRecord, ...]

    def __post_init__(self) -> None:
        _require_datetime(self.captured_at, "capturedAt")
        if not isinstance(self.source_digest, str) or _DIGEST.fullmatch(self.source_digest) is None:
            raise EpaSrsSubstanceError("sourceDigest must be a lowercase sha256:<64 hex> digest")
        if not self.records:
            raise EpaSrsSubstanceError("records must not be empty")
        dtxsids = [record.dtxsid for record in self.records]
        if len(dtxsids) != len(set(dtxsids)):
            raise EpaSrsSubstanceError("records repeats a DTXSID")

    @property
    def identifiers(self) -> tuple[ControlledIdentifier, ...]:
        """Every DTXSID/DTXCID/CASRN observed, as distinct qualified identifiers.

        DTXSID and DTXCID are emitted under separate authority-bearing kinds
        and are never merged; a record with no DTXCID or no CASRN simply
        contributes no identifier of that kind.
        """

        built: list[ControlledIdentifier] = []
        for record in self.records:
            built.append(
                ControlledIdentifier(
                    value=record.dtxsid,
                    kind="dtxsid",
                    authority_uri=DTXSID_AUTHORITY_URI,
                    source_uri=record.source_uri,
                    observed_at=self.captured_at,
                    effective_at=None,
                    source_digest=self.source_digest,
                )
            )
            if record.dtxcid is not None:
                built.append(
                    ControlledIdentifier(
                        value=record.dtxcid,
                        kind="dtxcid",
                        authority_uri=DTXCID_AUTHORITY_URI,
                        source_uri=record.source_uri,
                        observed_at=self.captured_at,
                        effective_at=None,
                        source_digest=self.source_digest,
                    )
                )
            if record.casrn is not None:
                built.append(
                    ControlledIdentifier(
                        value=record.casrn,
                        kind="casrn",
                        authority_uri=CAS_REGISTRY_AUTHORITY_URI,
                        source_uri=record.source_uri,
                        observed_at=self.captured_at,
                        effective_at=None,
                        source_digest=self.source_digest,
                    )
                )
        return distinct_identifiers(built)

    def native_payload(self) -> dict[str, Any]:
        return {
            "format": SUBSTANCE_CAPTURE_FORMAT,
            "parserVersion": PARSER_VERSION,
            "capturedAt": self.captured_at,
            "sourceDigest": self.source_digest,
            "conceptIdentityClaimed": False,
            "records": [record.native_payload() for record in self.records],
        }

    @property
    def digest(self) -> str:
        """A stable digest over the rendered payload, for reproducibility checks."""

        return _sha256_bytes(canonical_json(self.native_payload()).encode("utf-8"))


_SAMPLE_ENVELOPE_FIELDS = frozenset({"format", "capturedAt", "records"})


def parse_substance_sample(payload: bytes) -> SubstanceSample:
    """Parse one exact source-artifact payload into a pinned substance sample.

    ``payload`` must already be in hand -- this function never fetches it.
    Its sha256 becomes every identifier's ``source_digest``, so a caller can
    always trace a captured value back to the exact bytes it came from.
    """

    if not isinstance(payload, bytes) or not payload:
        raise EpaSrsSubstanceError("substance sample must be non-empty bytes")
    digest = _sha256_bytes(payload)
    try:
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EpaSrsSubstanceError("substance sample must be valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise EpaSrsSubstanceError("substance sample must contain one object")
    _exact_keys(value, _SAMPLE_ENVELOPE_FIELDS, "substance sample")
    if value["format"] != SUBSTANCE_CAPTURE_FORMAT:
        raise EpaSrsSubstanceError("unknown substance-sample format")
    captured_at = _require_datetime(value["capturedAt"], "capturedAt")
    records_value = value["records"]
    if not isinstance(records_value, list) or not records_value:
        raise EpaSrsSubstanceError("records must be a non-empty array")
    records = tuple(_parse_record(item, index) for index, item in enumerate(records_value))
    return SubstanceSample(captured_at=captured_at, source_digest=digest, records=records)


def parse_comptox_detail_page(
    payload: bytes,
    *,
    source_uri: str,
    captured_at: str,
) -> SubstanceSample:
    """Parse one real CompTox detail page into a one-record measured sample."""

    if not isinstance(payload, bytes) or not payload:
        raise EpaSrsSubstanceError("CompTox detail page must be non-empty bytes")
    source_uri = _require_https_uri(source_uri, "sourceUri")
    source_match = _COMPTOX_DETAIL_DTXSID.search(source_uri)
    if source_match is None or urlsplit(source_uri).hostname != "comptox.epa.gov":
        raise EpaSrsSubstanceError("sourceUri must name an official CompTox chemical detail page")
    captured_at = _require_datetime(captured_at, "capturedAt")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EpaSrsSubstanceError("CompTox detail page must be UTF-8 HTML") from error
    if "<title>CompTox Chemicals Dashboard</title>" not in text:
        raise EpaSrsSubstanceError("CompTox detail page title marker is missing")

    dtxsids = sorted(set(_COMPTOX_PAGE_DTXSID.findall(text)))
    dtxcids = sorted(set(_COMPTOX_PAGE_DTXCID.findall(text)))
    casrns = sorted(set(_COMPTOX_PAGE_CASRN.findall(text)))
    names = sorted(set(_COMPTOX_PAGE_PREFERRED_NAME.findall(text)))
    if dtxsids != [source_match.group(1)]:
        raise EpaSrsSubstanceError("CompTox detail page DTXSID does not match its source URI")
    if len(dtxcids) != 1 or len(casrns) != 1 or len(names) != 1:
        raise EpaSrsSubstanceError("CompTox detail page must expose one DTXCID, CASRN, and preferred name")

    return SubstanceSample(
        captured_at=captured_at,
        source_digest=_sha256_bytes(payload),
        records=(
            SubstanceIdentifierRecord(
                dtxsid=dtxsids[0],
                dtxcid=dtxcids[0],
                casrn=casrns[0],
                preferred_name=names[0],
                tsca_inventory_status=None,
                source_uri=source_uri,
            ),
        ),
    )


__all__ = [
    "CAS_REGISTRY_AUTHORITY_URI",
    "COMPTOX_SOURCE_URI",
    "DTXCID_AUTHORITY_URI",
    "DTXSID_AUTHORITY_URI",
    "PARSER_VERSION",
    "SRS_SOURCE_URI",
    "SUBSTANCE_CAPTURE_FORMAT",
    "TSCA_INVENTORY_SOURCE_URI",
    "TSCA_STATUSES",
    "EpaSrsSubstanceError",
    "SubstanceIdentifierRecord",
    "SubstanceSample",
    "parse_comptox_detail_page",
    "parse_substance_sample",
    "validate_casrn",
    "validate_dtxcid",
    "validate_dtxsid",
]

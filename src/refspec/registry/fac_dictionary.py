"""Pinned Federal Audit Clearinghouse (FAC) API data dictionary import.

The page at ``https://www.fac.gov/api/dictionary/`` is served as HTML
(``text/html``) despite living under an ``/api/`` path; it is documentation,
not a JSON endpoint. It publishes one table per FAC API endpoint (general,
federal_awards, notes_to_sefa, findings, findings_text,
corrective_action_plans, passthrough, secondary_auditors, additional_ueis,
additional_eins, resubmission). Each row states the GSA field name, its SQL
data type, and the legacy Census Bureau field it replaced. The page states no
version or release identifier; retrieval time and exact digest are the
available revision pin.

This is a field-identity dictionary, not an enumerated code-value list: it
never publishes the values a field may hold. In particular, findings'
``type_requirement`` field is documented only as TEXT; the letter codes it
holds (e.g. A-N) and their meanings come from the OMB Compliance Supplement
for the record's audit year, which this page does not publish and this
module does not attempt to resolve. Every field here is deterministic API
schema metadata, never a general subject concept; findings_text.finding_text
is free narrative that a separate subject-assignment process may tag, which
is out of scope for this field catalog.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import (
    ControlledIdentifier,
    ControlledIdentifierError,
    validate_identifier_date,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

FAC_PUBLISHER = "U.S. General Services Administration — Federal Audit Clearinghouse (FAC)"
FAC_IDENTIFIER_AUTHORITY_URI = "https://www.fac.gov/"
FAC_DOC_URL = "https://www.fac.gov/api/dictionary/"

# Exact HTML observed on 2026-08-03 (two independent fetches, same bytes).
# The response Last-Modified header on that request was
# Wed, 29 Jul 2026 20:07:44 GMT, recorded below as publisher_last_modified.
FAC_DICTIONARY_DOC_RETRIEVED_AT = "2026-08-03T19:25:31Z"
FAC_DICTIONARY_DOC_SHA256 = "sha256:95799a6f28b2f9a4d48bb0a88a1429381f2bc6e0677a9ec3a6608aa46a5a369c"
FAC_DICTIONARY_DOC_BYTE_LENGTH = 74_851

FACEndpoint = Literal[
    "general",
    "federal_awards",
    "notes_to_sefa",
    "findings",
    "findings_text",
    "corrective_action_plans",
    "passthrough",
    "secondary_auditors",
    "additional_ueis",
    "additional_eins",
    "resubmission",
]
FACDataType = Literal["ARRAY", "BIGINT", "BOOLEAN", "DATE", "INT", "TEXT"]
FACFieldUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_ENDPOINT_LIST_ITEM = re.compile(r'<li><a href="#endpoint-([a-z_]+)">([a-z_]+)</a></li>')
_ENDPOINT_SECTION = re.compile(
    r'<h3 id="endpoint-([a-z_]+)">Endpoint: <code>([a-z_]+)</code> \(formerly <code>([^)]*)\)</h3>'
    r'.*?<table class="usa-table">(.*?)</table>',
    re.DOTALL,
)
_FIELD_ROW = re.compile(
    r'<tr>\s*<td>(.*?)</td>\s*<th scope="row">(.*?)</th>\s*<td>(.*?)</td>\s*</tr>',
    re.DOTALL,
)
_GSA_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*(?: \+ [A-Za-z][A-Za-z0-9_.]*)?$")
_AUDIT_YEAR = re.compile(r"^\d{4}$")

# Documented endpoint order and the reviewed distinct-field count per endpoint.
# The general table repeats one row (FACACCEPTEDDATE/fac_accepted_date/DATE)
# identically; that duplicate collapses to one field rather than counting twice.
_ENDPOINT_ORDER: tuple[FACEndpoint, ...] = (
    "general",
    "federal_awards",
    "notes_to_sefa",
    "findings",
    "findings_text",
    "corrective_action_plans",
    "passthrough",
    "secondary_auditors",
    "additional_ueis",
    "additional_eins",
    "resubmission",
)
_ENDPOINT_FIELD_COUNTS: Mapping[str, int] = {
    "general": 63,
    "federal_awards": 22,
    "notes_to_sefa": 10,
    "findings": 15,
    "findings_text": 7,
    "corrective_action_plans": 7,
    "passthrough": 7,
    "secondary_auditors": 14,
    "additional_ueis": 5,
    "additional_eins": 5,
    "resubmission": 8,
}
_KNOWN_DATA_TYPES = frozenset({"ARRAY", "BIGINT", "BOOLEAN", "DATE", "INT", "TEXT"})

FAC_REQUIREMENT_CODE_ENDPOINT = "findings"
FAC_REQUIREMENT_CODE_FIELD = "type_requirement"

FAC_DICTIONARY_GAPS = (
    (
        "The FAC dictionary publishes only field identity (GSA name, legacy "
        "Census name, and SQL data type); it does not publish the "
        "compliance-requirement letter codes that findings.type_requirement "
        "holds or their meanings. Those codes and meanings are defined by the "
        "OMB Compliance Supplement for the record's general.audit_year. "
        "RefSpec records the audit_year alongside the code and does not "
        "resolve requirement-code meaning without ingesting that year's "
        "Supplement."
    ),
    (
        "The page does not publish a code-list release date, version number, "
        "or enumerated value list for any field; retrieval time and exact "
        "digest are the available revision pin."
    ),
    (
        "findings_text.finding_text is free narrative text the dictionary "
        "identifies as audit finding content; subject assignment for that "
        "text is out of scope for this deterministic field catalog."
    ),
)


class FACDictionaryError(ValueError):
    """Base class for FAC data dictionary failures."""


class FACAcquisitionError(FACDictionaryError):
    """Exact official documentation bytes could not be acquired safely."""


class FACSourceDriftError(FACDictionaryError):
    """The FAC dictionary no longer matches the reviewed structure or pin."""


class FACAssignmentError(FACDictionaryError):
    """A submitted field or code reference is unknown or incomplete."""


class FACPackageError(FACDictionaryError):
    """A FAC dictionary controlled-code package is incomplete or inconsistent."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_datetime(value: str, field: str) -> str:
    try:
        return validate_identifier_date(value, field)
    except ControlledIdentifierError as error:
        raise FACAcquisitionError(str(error)) from error


@dataclass(frozen=True, slots=True)
class FACDictionaryDocSource:
    """The one official documentation page publishing this field dictionary."""

    source_url: str = FAC_DOC_URL
    filename: str = "fac-api-dictionary.html"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "www.fac.gov":
            raise FACAcquisitionError("source_url must be an official HTTPS www.fac.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise FACAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FACAcquisitionError("filename must be one plain path component")


FAC_DICTIONARY_DOC_SOURCE = FACDictionaryDocSource()


@dataclass(frozen=True, slots=True)
class FACSnapshotPin:
    """Exact identity of one official documentation response."""

    source: FACDictionaryDocSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    publisher_last_modified: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FACAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FACAcquisitionError("expected_byte_length must be positive")
        _require_datetime(self.retrieved_at, "retrieved_at")
        if self.publisher_last_modified is not None:
            _require_datetime(self.publisher_last_modified, "publisher_last_modified")


FAC_DICTIONARY_DOC_2026_08_03 = FACSnapshotPin(
    source=FAC_DICTIONARY_DOC_SOURCE,
    retrieved_at=FAC_DICTIONARY_DOC_RETRIEVED_AT,
    expected_sha256=FAC_DICTIONARY_DOC_SHA256,
    expected_byte_length=FAC_DICTIONARY_DOC_BYTE_LENGTH,
    publisher_last_modified="2026-07-29T20:07:44Z",
)


@dataclass(frozen=True, slots=True)
class FetchedFACResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class FACFetcher(Protocol):
    """Small transport boundary for the official FAC dictionary page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedFACResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredFACSource:
    """One verified source object in the content-addressed store."""

    pin: FACSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class FACFieldDefinition:
    """One exact FAC API field identity: its GSA name, type, and legacy mapping."""

    endpoint: str
    formerly_endpoint: str
    gsa_field: str
    legacy_census_field: str | None
    data_type: FACDataType
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    use: FACFieldUse = "deterministicMetadata"
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class FACDictionaryPortfolio:
    """A parsed, digest-pinned capture of the FAC data dictionary page."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    source_url: str
    publisher_last_modified: str | None
    endpoints: tuple[FACEndpoint, ...]
    fields: tuple[FACFieldDefinition, ...]
    gaps: tuple[str, ...]

    def fields_by_endpoint(self, endpoint: str) -> tuple[FACFieldDefinition, ...]:
        """Return every distinct field documented for one endpoint."""

        return tuple(field for field in self.fields if field.endpoint == endpoint)

    def field(self, endpoint: str, gsa_field: str) -> FACFieldDefinition:
        """Look up one exact (endpoint, GSA field name) pair, failing closed."""

        for candidate in self.fields:
            if candidate.endpoint == endpoint and candidate.gsa_field == gsa_field:
                return candidate
        raise FACAssignmentError(f"unknown FAC field {endpoint}.{gsa_field!r}")


@dataclass(frozen=True, slots=True)
class FACRequirementCodeReference:
    """One ``type_requirement`` value paired with the audit year that governs it.

    The FAC dictionary never publishes what a requirement code means; only the
    OMB Compliance Supplement for the record's audit year does. This reference
    refuses to detach the raw code from that year rather than guessing at a
    meaning RefSpec was not given.
    """

    field: FACFieldDefinition
    code: str
    audit_year: str
    gap: str


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.fac.gov":
        raise FACAcquisitionError("fetcher resolved_url must remain on official HTTPS www.fac.gov")
    if parsed.username is not None or parsed.password is not None:
        raise FACAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: FACSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise FACSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise FACSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FACSourceDriftError(f"{location} is not valid UTF-8 HTML") from error
    if not text.lstrip().lower().startswith("<!doctype html"):
        raise FACSourceDriftError(f"{location} does not open with an HTML doctype")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: FACSnapshotPin) -> AcquiredFACSource:
    if path.is_symlink() or not path.is_file():
        raise FACAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached FAC source",
    )
    return AcquiredFACSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: FACSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredFACSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} FAC source",
    )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, pin)
        return AcquiredFACSource(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            source_url=pin.source.source_url,
            resolved_url=resolved_url,
            content_type=content_type,
            acquisition_mode=acquisition_mode,
            cache_hit=False,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_fac_dictionary_doc(
    pin: FACSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: FACFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredFACSource:
    """Acquire the exact documentation response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise FACAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise FACAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise FACAcquisitionError(f"local FAC source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/html",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise FACAcquisitionError("FAC dictionary is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise FACAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise FACSourceDriftError(f"FAC dictionary content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _parse_endpoint_list(text: str) -> tuple[FACEndpoint, ...]:
    match = re.search(r"<h2>Dictionary by endpoint</h2>\s*<ol>(.*?)</ol>", text, re.DOTALL)
    if match is None:
        raise FACSourceDriftError("could not locate the 'Dictionary by endpoint' endpoint list")
    items = _ENDPOINT_LIST_ITEM.findall(match.group(1))
    anchors = tuple(anchor for anchor, _label in items)
    if anchors != _ENDPOINT_ORDER:
        raise FACSourceDriftError(
            f"FAC dictionary endpoint list drift: expected {_ENDPOINT_ORDER}, parsed {anchors}"
        )
    return cast(tuple[FACEndpoint, ...], anchors)


def _identifier(value: str, kind: str, source_uri: str, acquired: AcquiredFACSource) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=FAC_IDENTIFIER_AUTHORITY_URI,
        source_uri=source_uri,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _parse_endpoint_fields(
    endpoint: FACEndpoint,
    formerly_endpoint: str,
    table_body: str,
    acquired: AcquiredFACSource,
) -> tuple[FACFieldDefinition, ...]:
    rows = _FIELD_ROW.findall(table_body)
    if not rows:
        raise FACSourceDriftError(f"FAC dictionary endpoint {endpoint!r} table has no field rows")

    source_uri = f"{FAC_DOC_URL}#endpoint-{endpoint}"
    by_gsa_field: dict[str, FACFieldDefinition] = {}
    for raw_census, raw_gsa, raw_type in rows:
        census = html.unescape(raw_census).strip()
        gsa_field = html.unescape(raw_gsa).strip()
        data_type = html.unescape(raw_type).strip()

        if _GSA_FIELD.fullmatch(gsa_field) is None:
            raise FACSourceDriftError(f"FAC dictionary endpoint {endpoint!r} has a malformed GSA field: {gsa_field!r}")
        if data_type not in _KNOWN_DATA_TYPES:
            raise FACSourceDriftError(
                f"FAC dictionary endpoint {endpoint!r} field {gsa_field!r} has an unknown data type: {data_type!r}"
            )
        legacy_census_field = None if census == "____" else census
        if not census:
            raise FACSourceDriftError(f"FAC dictionary endpoint {endpoint!r} field {gsa_field!r} has an empty Census cell")

        field = FACFieldDefinition(
            endpoint=endpoint,
            formerly_endpoint=formerly_endpoint,
            gsa_field=gsa_field,
            legacy_census_field=legacy_census_field,
            data_type=cast(FACDataType, data_type),
            source_url=source_uri,
            identifiers=(_identifier(gsa_field, "facApiFieldName", source_uri, acquired),),
        )
        existing = by_gsa_field.get(gsa_field)
        if existing is None:
            by_gsa_field[gsa_field] = field
        elif existing.legacy_census_field != field.legacy_census_field or existing.data_type != field.data_type:
            raise FACSourceDriftError(
                f"FAC dictionary endpoint {endpoint!r} repeats field {gsa_field!r} with a conflicting definition"
            )
        # else: an exact repeat of an already-seen row; the source's own
        # duplicate collapses to the one field it redundantly describes.

    fields = tuple(by_gsa_field.values())
    expected = _ENDPOINT_FIELD_COUNTS.get(endpoint)
    if expected is not None and len(fields) != expected:
        raise FACSourceDriftError(
            f"FAC dictionary endpoint {endpoint!r} field count drift: expected {expected}, parsed {len(fields)}"
        )
    return fields


def parse_fac_dictionary(acquired: AcquiredFACSource) -> FACDictionaryPortfolio:
    """Parse exact endpoint field tables without inventing code values the source lacks."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FAC source")
    text = payload.decode("utf-8")

    endpoints = _parse_endpoint_list(text)
    sections = _ENDPOINT_SECTION.findall(text)
    section_by_anchor = {anchor: (formerly, body) for anchor, _label, formerly, body in sections}
    if set(section_by_anchor) != set(endpoints) or len(sections) != len(endpoints):
        raise FACSourceDriftError(
            f"FAC dictionary endpoint sections drift: expected {endpoints}, parsed {tuple(section_by_anchor)}"
        )

    fields: list[FACFieldDefinition] = []
    for endpoint in endpoints:
        formerly_endpoint, table_body = section_by_anchor[endpoint]
        fields.extend(_parse_endpoint_fields(endpoint, formerly_endpoint.strip(), table_body, acquired))

    return FACDictionaryPortfolio(
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=acquired.pin.source.source_url,
        publisher_last_modified=acquired.pin.publisher_last_modified,
        endpoints=endpoints,
        fields=tuple(fields),
        gaps=FAC_DICTIONARY_GAPS,
    )


def validate_fac_field_reference(
    endpoint: str,
    gsa_field: str,
    portfolio: FACDictionaryPortfolio,
) -> FACFieldDefinition:
    """Validate one submitted (endpoint, field) reference, failing closed."""

    if endpoint not in portfolio.endpoints:
        raise FACAssignmentError(f"unknown FAC endpoint {endpoint!r}")
    return portfolio.field(endpoint, gsa_field)


def reference_finding_requirement_code(
    finding: Mapping[str, object],
    portfolio: FACDictionaryPortfolio,
) -> FACRequirementCodeReference:
    """Pair a submitted ``type_requirement`` code with its governing audit year.

    The FAC dictionary does not publish requirement-code meanings; only the
    applicable audit year's OMB Compliance Supplement defines them. This
    function refuses to detach the raw code from that year rather than
    resolving a meaning RefSpec was not given.
    """

    field = portfolio.field(FAC_REQUIREMENT_CODE_ENDPOINT, FAC_REQUIREMENT_CODE_FIELD)
    raw_code = finding.get(FAC_REQUIREMENT_CODE_FIELD)
    if not isinstance(raw_code, str) or not raw_code.strip():
        raise FACAssignmentError("finding must carry a non-empty string type_requirement code")
    raw_year = finding.get("audit_year")
    if not isinstance(raw_year, str) or _AUDIT_YEAR.fullmatch(raw_year) is None:
        raise FACAssignmentError(
            "finding must carry a 4-digit audit_year; type_requirement code meaning "
            "is governed by that year's OMB Compliance Supplement"
        )
    return FACRequirementCodeReference(
        field=field,
        code=raw_code.strip(),
        audit_year=raw_year,
        gap=(
            f"type_requirement value {raw_code.strip()!r} is uninterpreted by RefSpec: "
            f"consult the {raw_year} OMB Compliance Supplement for its meaning."
        ),
    )


def _package_observations(
    endpoint: str,
    fields: tuple[FACFieldDefinition, ...],
    acquired: AcquiredFACSource,
) -> tuple[Mapping[str, Any], ...]:
    observations: list[Mapping[str, Any]] = []
    for ordinal, field in enumerate(fields):
        identifier = field.identifiers[0]
        source_path = f"$.endpoints.{endpoint}.fields.{identifier.value}"
        identifier_payload = {
            "value": identifier.value,
            "kind": identifier.kind,
            "authorityUri": identifier.authority_uri,
            "sourceUri": identifier.source_uri,
            "sourcePath": source_path,
            "observedAt": identifier.observed_at,
            "sourceDigest": identifier.source_digest,
        }
        identity = {
            "endpoint": endpoint,
            "sourceArtifact": acquired.pin.source.source_url,
            "sourcePath": source_path,
            "gsaField": identifier.value,
        }
        observation_id = (
            "urn:ref:source-observation:fac-dictionary:"
            + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        )
        observations.append(
            {
                "id": observation_id,
                "sourceArtifact": acquired.pin.source.source_url,
                "sourcePath": source_path,
                # This ordinal is a source locator only; publisher identity is
                # preserved in identifiers and never derived from row order.
                "sourceOrdinal": ordinal,
                "labels": [
                    {
                        "value": field.gsa_field,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": [identifier_payload],
                "eligibleUses": [field.use],
                "conceptIdentityClaimed": False,
                "gsaField": field.gsa_field,
                "legacyCensusField": field.legacy_census_field,
                "dataType": field.data_type,
                "formerlyEndpoint": field.formerly_endpoint,
            }
        )
    return tuple(observations)


def build_fac_dictionary_package(
    endpoint: str,
    portfolio: FACDictionaryPortfolio,
    acquired: AcquiredFACSource,
) -> SourceControlledResourceBundle:
    """Build one development-only, deterministic closed package for one endpoint."""

    if endpoint not in portfolio.endpoints:
        raise FACPackageError(f"unknown FAC dictionary endpoint {endpoint!r}")
    fields = portfolio.fields_by_endpoint(endpoint)
    payload = acquired.path.read_bytes()
    captured_date = portfolio.retrieved_at[:10]
    return build_source_controlled_resource_bundle(
        resource_id=f"fac-dictionary-{endpoint}-{captured_date}",
        title=f"FAC API data dictionary: {endpoint} fields, captured {captured_date}",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=portfolio.retrieved_at,
        candidate_use_authorized=True,
        observations=_package_observations(endpoint, fields, acquired),
        source_artifacts={acquired.pin.source.source_url: payload},
        source_observed_count=len(fields),
        gaps=[{"kind": "fieldOnlyDictionary", "reason": gap} for gap in portfolio.gaps],
    )


__all__ = [
    "FAC_DICTIONARY_DOC_2026_08_03",
    "FAC_DICTIONARY_DOC_SOURCE",
    "FAC_DICTIONARY_GAPS",
    "FAC_DOC_URL",
    "FAC_IDENTIFIER_AUTHORITY_URI",
    "FAC_PUBLISHER",
    "FAC_REQUIREMENT_CODE_ENDPOINT",
    "FAC_REQUIREMENT_CODE_FIELD",
    "AcquiredFACSource",
    "FACAcquisitionError",
    "FACAssignmentError",
    "FACDictionaryDocSource",
    "FACDictionaryError",
    "FACDictionaryPortfolio",
    "FACEndpoint",
    "FACFetcher",
    "FACFieldDefinition",
    "FACPackageError",
    "FACRequirementCodeReference",
    "FACSnapshotPin",
    "FACSourceDriftError",
    "acquire_fac_dictionary_doc",
    "build_fac_dictionary_package",
    "parse_fac_dictionary",
    "reference_finding_requirement_code",
    "sha256_digest",
    "validate_fac_field_reference",
]

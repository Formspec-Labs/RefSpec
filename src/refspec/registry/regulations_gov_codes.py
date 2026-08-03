"""Pinned Regulations.gov API v4 controlled code lists.

The official Regulations.gov API publishes one OpenAPI specification document
that defines exactly three closed value sets: ``DocumentType`` (5 values),
``DocketType`` (2 values), and ``SubmitterType`` (3 values). These are
deterministic API-schema metadata used to interpret dockets, documents, and
comment submissions -- none of them is a general subject concept merely
because it has a readable label, and Regulations.gov publishes no maintained
cross-agency topic taxonomy for this catalog to import.

The specification also documents several agency-configured free-text fields
(``subtype``, ``category``, ``organizationType``, ``govAgencyType``,
``restrictReasonType``) and a free-text attachment ``format`` field. Those
fields are explicitly *not* enumerations in the source, so this module does
not invent closed lists for them; they remain named gaps.

The specification does not publish a code-list release number or an
independent revision identifier. RefSpec identifies a source snapshot by the
official URL, declared API version, retrieval time, byte length, and SHA-256
digest, the same approach used for the LDA constants. It preserves the
publisher-issued enum value as identity and does not mint an IRI or a
separate status code from the label.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and no scraping provider is
required for the current static-file endpoint.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import ControlledIdentifier

RGOV_PUBLISHER = "General Services Administration (Regulations.gov API)"
RGOV_IDENTIFIER_AUTHORITY_URI = "https://open.gsa.gov/api/regulationsgov/"
RGOV_OPENAPI_URL = "https://open.gsa.gov/api/regulationsgov/v4/openapi.yaml"
RGOV_API_SPEC_VERSION = "4.0"

# Exact OpenAPI YAML observed on 2026-08-03. This single document is the only
# source; it defines all three controlled code lists inline as schema enums.
RGOV_OPENAPI_2026_08_03_SHA256 = "sha256:be43c866f5ca424a456bde36ea03cb9326c454ef4e1894a13df80b6dc6e22488"
RGOV_OPENAPI_2026_08_03_BYTE_LENGTH = 60_826
RGOV_OPENAPI_2026_08_03_RETRIEVED_AT = "2026-08-03T19:13:12Z"
# Publisher's HTTP Last-Modified response header, converted to ISO 8601. It is
# evidence only -- the digest above is the actual revision pin.
RGOV_OPENAPI_2026_08_03_LAST_MODIFIED = "2026-07-02T21:13:41Z"

ResourceName = Literal["documentType", "docketType", "submitterType"]
# All three lists are schema-level classification, not filer-selected topic
# evidence: DocumentType/DocketType are assigned by the posting agency system,
# and SubmitterType is a required structural discriminator on comment
# submission, not evidence of a subject.
ResourceUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_OPENAPI_DECLARATION = "openapi: 3.0.0"
# Media types accepted from an injected fetcher. The specification is hosted
# as a static file (observed as `binary/octet-stream`) rather than served by
# the API itself, so acceptance covers the observed type plus common
# equivalents used by static file hosts for a YAML document.
_ACCEPTED_MEDIA_TYPES = frozenset(
    {
        "binary/octet-stream",
        "application/octet-stream",
        "application/x-yaml",
        "application/yaml",
        "text/yaml",
        "text/x-yaml",
        "text/plain",
    }
)
# (OpenAPI schema name, ControlledIdentifier kind, expected enum member count)
_SCHEMA_BY_RESOURCE: dict[ResourceName, tuple[str, str, int]] = {
    "documentType": ("DocumentType", "documentTypeCode", 5),
    "docketType": ("DocketType", "docketTypeCode", 2),
    "submitterType": ("SubmitterType", "submitterTypeCode", 3),
}


def _enum_block_pattern(schema_name: str) -> re.Pattern[str]:
    """Match one ``<schema_name>: {type: string, description, enum: [...]}`` block.

    The indentation is exact (4/6/8 spaces) because it is the real structure
    observed in the pinned specification; any drift in shape fails to match
    and is reported as source drift rather than silently accepted.
    """

    return re.compile(
        r"\n {4}"
        + re.escape(schema_name)
        + r":\n"
        r" {6}type: string\n"
        r" {6}description: [^\n]+\n"
        r" {6}enum:\n"
        r"(?P<items>(?: {8}- [^\n]*\n)+)"
    )


class RegulationsGovResourceError(ValueError):
    """Base class for Regulations.gov controlled-code failures."""


class RegulationsGovAcquisitionError(RegulationsGovResourceError):
    """Exact official source bytes could not be acquired safely."""


class RegulationsGovSourceDriftError(RegulationsGovResourceError):
    """The Regulations.gov OpenAPI specification no longer matches the reviewed shape or pin."""


class RegulationsGovAssignmentError(RegulationsGovResourceError):
    """A record carries an unknown or malformed source-assigned code."""


@dataclass(frozen=True, slots=True)
class RGovOpenAPISource:
    """The one official Regulations.gov OpenAPI specification document."""

    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "open.gsa.gov":
            raise RegulationsGovAcquisitionError("source_url must be an official HTTPS open.gsa.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise RegulationsGovAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise RegulationsGovAcquisitionError("filename must be one plain path component")


RGOV_OPENAPI_SOURCE = RGovOpenAPISource(
    source_url=RGOV_OPENAPI_URL,
    filename="regulations-gov-openapi-v4.yaml",
)


@dataclass(frozen=True, slots=True)
class RGovSnapshotPin:
    """Exact identity of one official Regulations.gov OpenAPI response."""

    source: RGovOpenAPISource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    api_spec_version: str = RGOV_API_SPEC_VERSION
    publisher_last_modified: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise RegulationsGovAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise RegulationsGovAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at or not self.api_spec_version:
            raise RegulationsGovAcquisitionError("retrieved_at and api_spec_version must not be empty")


RGOV_OPENAPI_2026_08_03 = RGovSnapshotPin(
    source=RGOV_OPENAPI_SOURCE,
    retrieved_at=RGOV_OPENAPI_2026_08_03_RETRIEVED_AT,
    expected_sha256=RGOV_OPENAPI_2026_08_03_SHA256,
    expected_byte_length=RGOV_OPENAPI_2026_08_03_BYTE_LENGTH,
    publisher_last_modified=RGOV_OPENAPI_2026_08_03_LAST_MODIFIED,
)


@dataclass(frozen=True, slots=True)
class FetchedRGovResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class RGovFetcher(Protocol):
    """Small transport boundary for the official Regulations.gov OpenAPI document."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedRGovResponse:
        """Fetch the response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredRGovSource:
    """One verified source object in the content-addressed store."""

    pin: RGovSnapshotPin
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
class RGovCode:
    """One exact enum label from the pinned OpenAPI specification."""

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedRegulationsGovResource:
    """One parsed, digest-pinned Regulations.gov controlled code list."""

    resource_name: ResourceName
    use: ResourceUse
    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    api_spec_version: str
    publisher_last_modified: str | None
    codes: tuple[RGovCode, ...]

    def by_code(self) -> dict[str, RGovCode]:
        """Index the enum's exact publisher label to its retained code."""

        result: dict[str, RGovCode] = {}
        for entry in self.codes:
            result[entry.publisher_label] = entry
        return result


@dataclass(frozen=True, slots=True)
class RegulationsGovControlPortfolio:
    """The three closed code lists and the explicitly unsupported controls."""

    document_type: ParsedRegulationsGovResource
    docket_type: ParsedRegulationsGovResource
    submitter_type: ParsedRegulationsGovResource
    agency_configured_fields: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RGovCodeAssignment:
    """A record value validated against the exact pinned enum."""

    source_field: str
    publisher_label: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


RGOV_AGENCY_CONFIGURED_FIELDS = (
    "subtype",
    "category",
    "organizationType",
    "govAgencyType",
    "restrictReasonType",
)

RGOV_PORTFOLIO_GAPS = (
    (
        "The OpenAPI specification does not publish a code-list release number or "
        "independent revision identifier; retrieved time, the publisher's Last-Modified "
        "response header, and the exact digest are the available revision pins."
    ),
    (
        "`subtype`, `category`, `organizationType`, `govAgencyType`, and `restrictReasonType` "
        "are documented as agency-configured free text, not enumerations; no cross-agency "
        "taxonomy for them was found, and RefSpec does not invent one."
    ),
    (
        "The `FileFormat.format` attachment field (for example `pdf`, `docx`) is free text with "
        "no published enumeration; no fine-grained cross-agency attachment taxonomy was found."
    ),
    (
        "Comment submission payloads and the Comments resource are outside this catalog's current "
        "scope; SubmitterType is captured as a published code list, not validated against a live record."
    ),
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "open.gsa.gov":
        raise RegulationsGovAcquisitionError("fetcher resolved_url must remain on official HTTPS open.gsa.gov")
    if parsed.username is not None or parsed.password is not None:
        raise RegulationsGovAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: RGovSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise RegulationsGovSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise RegulationsGovSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RegulationsGovSourceDriftError(f"{location} is not valid UTF-8 text") from error
    if _OPENAPI_DECLARATION not in text.splitlines():
        raise RegulationsGovSourceDriftError(f"{location} is missing the expected `{_OPENAPI_DECLARATION}` line")
    if f'  version: "{pin.api_spec_version}"' not in text.splitlines():
        raise RegulationsGovSourceDriftError(
            f"{location} OpenAPI info.version drifted from pinned {pin.api_spec_version!r}"
        )
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: RGovSnapshotPin) -> AcquiredRGovSource:
    if path.is_symlink() or not path.is_file():
        raise RegulationsGovAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached Regulations.gov source",
    )
    return AcquiredRGovSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="application/x-yaml",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: RGovSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredRGovSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} Regulations.gov source",
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
        return AcquiredRGovSource(
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


def acquire_regulations_gov_openapi(
    pin: RGovSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: RGovFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredRGovSource:
    """Acquire the exact OpenAPI response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise RegulationsGovAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise RegulationsGovAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise RegulationsGovAcquisitionError(f"local Regulations.gov source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="application/x-yaml",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise RegulationsGovAcquisitionError(
            "the Regulations.gov OpenAPI document is not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise RegulationsGovAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in _ACCEPTED_MEDIA_TYPES:
        raise RegulationsGovSourceDriftError(
            f"Regulations.gov OpenAPI content type drifted to {fetched.content_type!r}"
        )
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def parse_regulations_gov_resource(
    acquired: AcquiredRGovSource,
    resource_name: ResourceName,
) -> ParsedRegulationsGovResource:
    """Parse one exact enum block without converting its members to concepts."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed Regulations.gov source")
    text = payload.decode("utf-8")

    schema_name, identifier_kind, expected_count = _SCHEMA_BY_RESOURCE[resource_name]
    match = _enum_block_pattern(schema_name).search(text)
    if match is None:
        raise RegulationsGovSourceDriftError(
            f"{resource_name} enum block for schema `{schema_name}` was not found in the expected shape"
        )

    values: list[str] = []
    for line in match.group("items").splitlines():
        # Each line is exactly `        - <value>`; a plain YAML scalar's
        # trailing whitespace (observed once, on `Nonrulemaking `) folds away
        # and is not part of the value.
        raw = line[len("        - ") :].rstrip()
        if not raw:
            raise RegulationsGovSourceDriftError(f"{resource_name} enum contains a blank member")
        values.append(raw)

    if len(values) != expected_count:
        raise RegulationsGovSourceDriftError(
            f"{resource_name} count drift: expected {expected_count}, parsed {len(values)}"
        )
    if len(set(values)) != len(values):
        raise RegulationsGovSourceDriftError(f"{resource_name} enum contains duplicate publisher labels")

    codes = tuple(
        RGovCode(
            resource_name=resource_name,
            use="deterministicMetadata",
            publisher_label=value,
            source_url=acquired.pin.source.source_url,
            identifiers=(
                ControlledIdentifier(
                    value=value,
                    kind=identifier_kind,
                    authority_uri=RGOV_IDENTIFIER_AUTHORITY_URI,
                    source_uri=acquired.pin.source.source_url,
                    observed_at=acquired.pin.retrieved_at,
                    effective_at=None,
                    source_digest=acquired.sha256,
                ),
            ),
        )
        for value in values
    )
    return ParsedRegulationsGovResource(
        resource_name=resource_name,
        use="deterministicMetadata",
        source_url=acquired.pin.source.source_url,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        api_spec_version=acquired.pin.api_spec_version,
        publisher_last_modified=acquired.pin.publisher_last_modified,
        codes=codes,
    )


def assemble_regulations_gov_control_portfolio(
    resources: Sequence[ParsedRegulationsGovResource],
) -> RegulationsGovControlPortfolio:
    """Require all three distinct resources and retain unsupported-control gaps."""

    by_name = {resource.resource_name: resource for resource in resources}
    if len(resources) != 3 or set(by_name) != {"documentType", "docketType", "submitterType"}:
        raise RegulationsGovSourceDriftError(
            "Regulations.gov control portfolio requires exactly one documentType, docketType, "
            "and submitterType resource"
        )
    return RegulationsGovControlPortfolio(
        document_type=by_name["documentType"],
        docket_type=by_name["docketType"],
        submitter_type=by_name["submitterType"],
        agency_configured_fields=RGOV_AGENCY_CONFIGURED_FIELDS,
        gaps=RGOV_PORTFOLIO_GAPS,
    )


def _assignment(code: RGovCode, source_field: str) -> RGovCodeAssignment:
    return RGovCodeAssignment(
        source_field=source_field,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_regulations_gov_document_type(
    document: Mapping[str, object],
    portfolio: RegulationsGovControlPortfolio,
) -> RGovCodeAssignment:
    """Validate the ``documentType`` field retained on a documents/comments record."""

    raw = document.get("documentType")
    if not isinstance(raw, str):
        raise RegulationsGovAssignmentError("Regulations.gov document must carry a string documentType")
    code = portfolio.document_type.by_code().get(raw)
    if code is None:
        raise RegulationsGovAssignmentError(f"unknown Regulations.gov documentType {raw!r}")
    return _assignment(code, "documentType")


def validate_regulations_gov_docket_type(
    docket: Mapping[str, object],
    portfolio: RegulationsGovControlPortfolio,
) -> RGovCodeAssignment:
    """Validate the ``docketType`` field retained on a docket record."""

    raw = docket.get("docketType")
    if not isinstance(raw, str):
        raise RegulationsGovAssignmentError("Regulations.gov docket must carry a string docketType")
    code = portfolio.docket_type.by_code().get(raw)
    if code is None:
        raise RegulationsGovAssignmentError(f"unknown Regulations.gov docketType {raw!r}")
    return _assignment(code, "docketType")

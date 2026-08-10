"""Pinned Grants.gov status/code page imports for the ``T1-06`` catalog row.

The official Grants.gov "Status Codes" page (grants.gov/api/status-codes)
publishes exactly three server-rendered HTML tables: an HTTP Status Code
Summary, an Eligibility Codes ("eligibilities") table, and a Category Codes
("fundingCategories") table. There is no JSON or OpenAPI endpoint for these
values; the rendered page is the source of record.

The catalog row for this source names funding-activity category, eligibility,
instrument, opportunity status, and statutory initiative values as in scope.
This page publishes only the first two: eligibility codes are deterministic
applicant-type metadata (structural, not topical), and funding category codes
are the closest thing to a topic a funder assigns to an opportunity, so they
are retained as source-assigned evidence. Funding instrument, opportunity
status, and statutory initiative values are not published at this URL; that
absence is recorded as a gap rather than guessed at. The HTTP Status Code
Summary table documents API transport-level response codes, not a
funding-domain value, so it is used only as a structural drift check and is
never packaged as an observation. None of these values is a general subject
concept merely because it has a readable label.

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
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

GRANTS_GOV_PUBLISHER = "Grants.gov (U.S. Department of Health and Human Services)"
GRANTS_GOV_IDENTIFIER_AUTHORITY_URI = "https://www.grants.gov/"
GRANTS_GOV_STATUS_CODES_URL = "https://www.grants.gov/api/status-codes"

# Exact HTML observed on 2026-08-03. The response carried no Last-Modified,
# ETag, or other publisher revision header; retrieval time and this digest
# are the only available revision pin (see GRANTS_GOV_PORTFOLIO_GAPS).
GRANTS_GOV_STATUS_CODES_RETRIEVED_AT = "2026-08-03T19:28:12Z"
GRANTS_GOV_STATUS_CODES_SHA256 = "sha256:bcbe4c44f8c1743eeaa26ab9f350c53214238c31d807057f248af8dd96cd5f85"
GRANTS_GOV_STATUS_CODES_BYTE_LENGTH = 46_093

ResourceName = Literal["eligibilities", "fundingCategories"]
GrantsGovCodeUse = Literal["sourceAssignedEvidence", "deterministicMetadata"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_ELIGIBILITY_CODE = re.compile(r"^[0-9]{2}$")
_FUNDING_CATEGORY_CODE = re.compile(r"^[A-Z]{1,3}$")
_TABLE_ROW = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.DOTALL)

_ELIGIBILITY_HEADING = "Eligibility Codes (&quot;eligibilities&quot;):"
_CATEGORY_HEADING = "Category Codes (&quot;fundingCategories&quot;):"
_HTTP_STATUS_HEADING = "HTTP STATUS CODE SUMMARY"

_RESOURCE_COUNTS: Mapping[ResourceName, int] = {
    "eligibilities": 17,
    "fundingCategories": 26,
}
_RESOURCE_USE: Mapping[ResourceName, GrantsGovCodeUse] = {
    "eligibilities": "deterministicMetadata",
    "fundingCategories": "sourceAssignedEvidence",
}
_RESOURCE_IDENTIFIER_KIND: Mapping[ResourceName, str] = {
    "eligibilities": "eligibilityCode",
    "fundingCategories": "fundingCategoryCode",
}
_RESOURCE_CODE_PATTERN: Mapping[ResourceName, re.Pattern[str]] = {
    "eligibilities": _ELIGIBILITY_CODE,
    "fundingCategories": _FUNDING_CATEGORY_CODE,
}
_RESOURCE_HEADING: Mapping[ResourceName, str] = {
    "eligibilities": _ELIGIBILITY_HEADING,
    "fundingCategories": _CATEGORY_HEADING,
}


class GrantsGovCodeError(ValueError):
    """Base class for Grants.gov controlled-code failures."""


class GrantsGovAcquisitionError(GrantsGovCodeError):
    """Exact official page bytes could not be acquired safely."""


class GrantsGovSourceDriftError(GrantsGovCodeError):
    """The Grants.gov status-codes page no longer matches the reviewed structure or pin."""


class GrantsGovAssignmentError(GrantsGovCodeError):
    """A submitted value is unknown to the exact source snapshot."""


class GrantsGovPackageError(GrantsGovCodeError):
    """A Grants.gov controlled-code package is incomplete or inconsistent."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_datetime(value: str, field: str) -> str:
    try:
        return validate_identifier_date(value, field)
    except ControlledIdentifierError as error:
        raise GrantsGovAcquisitionError(str(error)) from error


@dataclass(frozen=True, slots=True)
class GrantsGovDocSource:
    """The one official page publishing these controlled codes."""

    source_url: str = GRANTS_GOV_STATUS_CODES_URL
    filename: str = "status-codes.html"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "www.grants.gov":
            raise GrantsGovAcquisitionError("source_url must be an official HTTPS www.grants.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise GrantsGovAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise GrantsGovAcquisitionError("filename must be one plain path component")


GRANTS_GOV_STATUS_CODES_SOURCE = GrantsGovDocSource()


@dataclass(frozen=True, slots=True)
class GrantsGovSnapshotPin:
    """Exact identity of one official page response."""

    source: GrantsGovDocSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GrantsGovAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GrantsGovAcquisitionError("expected_byte_length must be positive")
        _require_datetime(self.retrieved_at, "retrieved_at")


GRANTS_GOV_STATUS_CODES_2026_08_03 = GrantsGovSnapshotPin(
    source=GRANTS_GOV_STATUS_CODES_SOURCE,
    retrieved_at=GRANTS_GOV_STATUS_CODES_RETRIEVED_AT,
    expected_sha256=GRANTS_GOV_STATUS_CODES_SHA256,
    expected_byte_length=GRANTS_GOV_STATUS_CODES_BYTE_LENGTH,
)


@dataclass(frozen=True, slots=True)
class FetchedGrantsGovResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class GrantsGovFetcher(Protocol):
    """Small transport boundary for the official Grants.gov status-codes page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedGrantsGovResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredGrantsGovSource:
    """One verified source object in the content-addressed store."""

    pin: GrantsGovSnapshotPin
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
class GrantsGovCode:
    """One exact publisher-documented code and label."""

    resource_name: ResourceName
    use: GrantsGovCodeUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class GrantsGovCodePortfolio:
    """A parsed, digest-pinned Grants.gov status-codes capture."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    source_url: str
    eligibilities: tuple[GrantsGovCode, ...]
    funding_categories: tuple[GrantsGovCode, ...]
    gaps: tuple[str, ...]

    def eligibilities_by_code(self) -> dict[str, GrantsGovCode]:
        """Index every documented eligibility code."""

        return _index_by_code(self.eligibilities)

    def funding_categories_by_code(self) -> dict[str, GrantsGovCode]:
        """Index every documented funding category code."""

        return _index_by_code(self.funding_categories)


GRANTS_GOV_PORTFOLIO_GAPS = (
    (
        "The status-codes page publishes no revision date, version number, "
        "change log, or Last-Modified/ETag response header; retrieval time "
        "and exact digest are the only available revision pin."
    ),
    (
        "The catalog also names funding instrument, opportunity status, and "
        "statutory initiative values, but https://www.grants.gov/api/status-codes "
        "publishes only Eligibility Codes and Category Codes; those other "
        "code lists are not present at this URL."
    ),
    (
        "The page's HTTP Status Code Summary table documents API "
        "transport-level response codes (200, 400, 401, ...), not a "
        "funding-domain value; it is used only to confirm the page's "
        "reviewed structure and is never packaged as an observation."
    ),
)


def _index_by_code(codes: tuple[GrantsGovCode, ...]) -> dict[str, GrantsGovCode]:
    result: dict[str, GrantsGovCode] = {}
    for entry in codes:
        result[entry.identifiers[0].value] = entry
    return result


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.grants.gov":
        raise GrantsGovAcquisitionError("fetcher resolved_url must remain on official HTTPS www.grants.gov")
    if parsed.username is not None or parsed.password is not None:
        raise GrantsGovAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: GrantsGovSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise GrantsGovSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise GrantsGovSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GrantsGovSourceDriftError(f"{location} is not valid UTF-8 HTML") from error
    if not text.lstrip().lower().startswith("<!doctype html"):
        raise GrantsGovSourceDriftError(f"{location} does not open with an HTML doctype")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: GrantsGovSnapshotPin) -> AcquiredGrantsGovSource:
    if path.is_symlink() or not path.is_file():
        raise GrantsGovAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached Grants.gov source",
    )
    return AcquiredGrantsGovSource(
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
    pin: GrantsGovSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGrantsGovSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} Grants.gov source",
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
        return AcquiredGrantsGovSource(
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


def acquire_grants_gov_status_codes(
    pin: GrantsGovSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: GrantsGovFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredGrantsGovSource:
    """Acquire the exact status-codes page through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise GrantsGovAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise GrantsGovAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GrantsGovAcquisitionError(f"local Grants.gov source is not a regular file: {local_path}")
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
        raise GrantsGovAcquisitionError(
            "Grants.gov status codes are not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise GrantsGovAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise GrantsGovSourceDriftError(f"Grants.gov page content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _extract_following_table(text: str, heading: str, *, label: str) -> str:
    heading_index = text.find(heading)
    if heading_index == -1:
        raise GrantsGovSourceDriftError(f"could not locate the {label!r} heading")
    table_start = text.find("<table", heading_index)
    if table_start == -1:
        raise GrantsGovSourceDriftError(f"{label!r} heading has no following table")
    table_end = text.find("</table>", table_start)
    if table_end == -1:
        raise GrantsGovSourceDriftError(f"{label!r} table was not closed")
    return text[table_start : table_end + len("</table>")]


def _identifier(
    value: str,
    kind: str,
    source_uri: str,
    acquired: AcquiredGrantsGovSource,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=GRANTS_GOV_IDENTIFIER_AUTHORITY_URI,
        source_uri=source_uri,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _parse_two_column_codes(
    text: str,
    resource_name: ResourceName,
    acquired: AcquiredGrantsGovSource,
) -> tuple[GrantsGovCode, ...]:
    heading = _RESOURCE_HEADING[resource_name]
    table = _extract_following_table(text, heading, label=heading)
    code_pattern = _RESOURCE_CODE_PATTERN[resource_name]
    identifier_kind = _RESOURCE_IDENTIFIER_KIND[resource_name]
    use = _RESOURCE_USE[resource_name]

    codes: list[GrantsGovCode] = []
    for raw_code, raw_label in _TABLE_ROW.findall(table):
        code = html.unescape(raw_code).strip()
        label = html.unescape(raw_label).strip()
        if code_pattern.fullmatch(code) is None:
            raise GrantsGovSourceDriftError(f"{resource_name} has a malformed publisher code: {code!r}")
        if not label:
            raise GrantsGovSourceDriftError(f"{resource_name} code {code!r} has an empty description")
        codes.append(
            GrantsGovCode(
                resource_name=resource_name,
                use=use,
                publisher_label=label,
                source_url=GRANTS_GOV_STATUS_CODES_URL,
                identifiers=(_identifier(code, identifier_kind, GRANTS_GOV_STATUS_CODES_URL, acquired),),
            )
        )

    expected_count = _RESOURCE_COUNTS[resource_name]
    if len(codes) != expected_count:
        raise GrantsGovSourceDriftError(f"{resource_name} count drift: expected {expected_count}, parsed {len(codes)}")
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise GrantsGovSourceDriftError(f"{resource_name} contains a duplicate publisher code")
    return tuple(codes)


def _require_http_status_summary_present(text: str) -> None:
    # This table is out of the catalog's funding-domain scope (see module
    # docstring and GRANTS_GOV_PORTFOLIO_GAPS); it is checked only so an
    # unrelated page served at this URL fails loudly instead of silently
    # producing an empty eligibility/category portfolio.
    _extract_following_table(text, _HTTP_STATUS_HEADING, label=_HTTP_STATUS_HEADING)


def parse_grants_gov_status_codes(acquired: AcquiredGrantsGovSource) -> GrantsGovCodePortfolio:
    """Parse the exact eligibility and funding-category tables without minting concepts."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed Grants.gov source")
    text = payload.decode("utf-8")

    _require_http_status_summary_present(text)
    eligibilities = _parse_two_column_codes(text, "eligibilities", acquired)
    funding_categories = _parse_two_column_codes(text, "fundingCategories", acquired)

    return GrantsGovCodePortfolio(
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=acquired.pin.source.source_url,
        eligibilities=eligibilities,
        funding_categories=funding_categories,
        gaps=GRANTS_GOV_PORTFOLIO_GAPS,
    )


def validate_eligibility_code(value: str, portfolio: GrantsGovCodePortfolio) -> GrantsGovCode:
    """Validate one submitted eligibility code against the exact source snapshot."""

    code = portfolio.eligibilities_by_code().get(value)
    if code is None:
        raise GrantsGovAssignmentError(f"unknown Grants.gov eligibility code {value!r}")
    return code


def validate_funding_category_code(value: str, portfolio: GrantsGovCodePortfolio) -> GrantsGovCode:
    """Validate one submitted funding category code against the exact source snapshot."""

    code = portfolio.funding_categories_by_code().get(value)
    if code is None:
        raise GrantsGovAssignmentError(f"unknown Grants.gov funding category code {value!r}")
    return code


def _package_observations(
    resource_name: ResourceName,
    codes: tuple[GrantsGovCode, ...],
    acquired: AcquiredGrantsGovSource,
) -> tuple[Mapping[str, Any], ...]:
    observations: list[Mapping[str, Any]] = []
    for ordinal, code in enumerate(codes):
        identifier = code.identifiers[0]
        source_path = f"$.{resource_name}.{identifier.value}"
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
            "resourceName": resource_name,
            "sourceArtifact": acquired.pin.source.source_url,
            "sourcePath": source_path,
            "value": identifier.value,
        }
        observation_id = (
            "urn:ref:source-observation:grants-gov-codes:"
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
                        "value": code.publisher_label,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": [identifier_payload],
                "uses": [code.use],
                "conceptIdentityClaimed": False,
            }
        )
    return tuple(observations)


def build_grants_gov_code_package(
    resource_name: ResourceName,
    portfolio: GrantsGovCodePortfolio,
    acquired: AcquiredGrantsGovSource,
) -> SourceControlledResourceBundle:
    """Build one development-only, deterministic closed package for one code family."""

    codes_by_resource: Mapping[ResourceName, tuple[GrantsGovCode, ...]] = {
        "eligibilities": portfolio.eligibilities,
        "fundingCategories": portfolio.funding_categories,
    }
    if resource_name not in codes_by_resource:
        raise GrantsGovPackageError(f"unknown Grants.gov resource family {resource_name!r}")
    codes = codes_by_resource[resource_name]
    payload = acquired.path.read_bytes()
    captured_date = portfolio.retrieved_at[:10]
    return build_source_controlled_resource_bundle(
        resource_id=f"grants-gov-{resource_name}-{captured_date}",
        title=f"Grants.gov {resource_name}, captured {captured_date}",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=(_RESOURCE_USE[resource_name],),
        captured_at=portfolio.retrieved_at,
        observations=_package_observations(resource_name, codes, acquired),
        source_artifacts={acquired.pin.source.source_url: payload},
        source_observed_count=len(codes),
        gaps=[{"kind": "codeListNotFullyPublished", "reason": gap} for gap in portfolio.gaps],
    )


__all__ = [
    "GRANTS_GOV_IDENTIFIER_AUTHORITY_URI",
    "GRANTS_GOV_PORTFOLIO_GAPS",
    "GRANTS_GOV_PUBLISHER",
    "GRANTS_GOV_STATUS_CODES_2026_08_03",
    "GRANTS_GOV_STATUS_CODES_SOURCE",
    "GRANTS_GOV_STATUS_CODES_URL",
    "AcquiredGrantsGovSource",
    "FetchedGrantsGovResponse",
    "GrantsGovAcquisitionError",
    "GrantsGovAssignmentError",
    "GrantsGovCode",
    "GrantsGovCodeError",
    "GrantsGovCodePortfolio",
    "GrantsGovCodeUse",
    "GrantsGovDocSource",
    "GrantsGovFetcher",
    "GrantsGovPackageError",
    "GrantsGovSnapshotPin",
    "GrantsGovSourceDriftError",
    "ResourceName",
    "acquire_grants_gov_status_codes",
    "build_grants_gov_code_package",
    "parse_grants_gov_status_codes",
    "sha256_digest",
    "validate_eligibility_code",
    "validate_funding_category_code",
]

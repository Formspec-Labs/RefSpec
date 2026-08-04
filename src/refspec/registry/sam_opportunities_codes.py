"""Pinned SAM.gov Opportunities notice type, status, and set-aside code imports.

The official SAM.gov Get Opportunities Public API documentation
(open.gsa.gov/api/get-opportunities-public-api/) publishes procurement notice
type codes (the ``ptype`` request parameter), opportunity status values (the
``status`` request parameter), and set-aside codes as prose text inside HTML
documentation tables. There is no machine-readable code-list endpoint or JSON
schema for these values; the documentation page itself is the source of
record.

The documentation states this API "only provides the latest active version of
the opportunity." It also explicitly marks two ``ptype`` codes retired
(``f`` = Foreign Government Standard, ``l`` = Fair Opportunity / Limited
Sources) and directs callers to use ``u`` (Justification) instead. Because the
live API surfaces only current values, this capture is the mechanism that
preserves the retired codes and the documented version history of the status
values. None of these values is a general subject concept; they are
deterministic procurement lifecycle and eligibility metadata.

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

SAM_PUBLISHER = "U.S. General Services Administration — SAM.gov Get Opportunities Public API"
SAM_IDENTIFIER_AUTHORITY_URI = "https://open.gsa.gov/"
SAM_DOC_URL = "https://open.gsa.gov/api/get-opportunities-public-api/"
SAM_DOC_REQUEST_PARAMETERS_ANCHOR = f"{SAM_DOC_URL}#get-opportunities-request-parameters"
SAM_DOC_SET_ASIDE_VALUES_ANCHOR = f"{SAM_DOC_URL}#set-aside-values"

# Exact HTML observed on 2026-08-03. The response Last-Modified header on that
# request was Thu, 12 Sep 2024 15:05:24 GMT, recorded below as
# publisher_last_modified; the page's own Change Log table was last updated
# 2021-06-11 (v1.97), well before either date.
SAM_OPPORTUNITIES_DOC_RETRIEVED_AT = "2026-08-03T19:18:48Z"
SAM_OPPORTUNITIES_DOC_SHA256 = "sha256:448b85ab4a22e33d139295cb1d6a3a6384b685a936d8c645dd12e69ed938fa62"
SAM_OPPORTUNITIES_DOC_BYTE_LENGTH = 46_217

ResourceName = Literal["noticeTypes", "opportunityStatuses", "setAsideCodes"]
SAMCodeUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_NOTICE_TYPE_LINE = re.compile(r"^([a-z])\s*=\s*(.+)$")
_STATUS_CODE = re.compile(r"^[a-z]+$")
_SET_ASIDE_CODE = re.compile(r"^[A-Za-z0-9]{2,8}$")

_RESOURCE_COUNTS: Mapping[ResourceName, int] = {
    "noticeTypes": 11,
    "opportunityStatuses": 5,
    "setAsideCodes": 18,
}


class SAMOpportunitiesCodeError(ValueError):
    """Base class for SAM.gov Opportunities controlled-code failures."""


class SAMAcquisitionError(SAMOpportunitiesCodeError):
    """Exact official documentation bytes could not be acquired safely."""


class SAMSourceDriftError(SAMOpportunitiesCodeError):
    """The SAM.gov documentation no longer matches the reviewed structure or pin."""


class SAMAssignmentError(SAMOpportunitiesCodeError):
    """A submitted value is unknown, retired, or inconsistent with the source."""


class SAMPackageError(SAMOpportunitiesCodeError):
    """A SAM.gov controlled-code package is incomplete or inconsistent."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_datetime(value: str, field: str) -> str:
    try:
        return validate_identifier_date(value, field)
    except ControlledIdentifierError as error:
        raise SAMAcquisitionError(str(error)) from error


@dataclass(frozen=True, slots=True)
class SAMOpportunitiesDocSource:
    """The one official documentation page publishing these controlled codes."""

    source_url: str = SAM_DOC_URL
    filename: str = "get-opportunities-public-api.html"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "open.gsa.gov":
            raise SAMAcquisitionError("source_url must be an official HTTPS open.gsa.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise SAMAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise SAMAcquisitionError("filename must be one plain path component")


SAM_OPPORTUNITIES_DOC_SOURCE = SAMOpportunitiesDocSource()


@dataclass(frozen=True, slots=True)
class SAMSnapshotPin:
    """Exact identity of one official documentation response."""

    source: SAMOpportunitiesDocSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    publisher_last_modified: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise SAMAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise SAMAcquisitionError("expected_byte_length must be positive")
        _require_datetime(self.retrieved_at, "retrieved_at")
        if self.publisher_last_modified is not None:
            _require_datetime(self.publisher_last_modified, "publisher_last_modified")


SAM_OPPORTUNITIES_DOC_2026_08_03 = SAMSnapshotPin(
    source=SAM_OPPORTUNITIES_DOC_SOURCE,
    retrieved_at=SAM_OPPORTUNITIES_DOC_RETRIEVED_AT,
    expected_sha256=SAM_OPPORTUNITIES_DOC_SHA256,
    expected_byte_length=SAM_OPPORTUNITIES_DOC_BYTE_LENGTH,
    publisher_last_modified="2024-09-12T15:05:24Z",
)


@dataclass(frozen=True, slots=True)
class FetchedSAMResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class SAMFetcher(Protocol):
    """Small transport boundary for the official SAM.gov documentation page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedSAMResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredSAMSource:
    """One verified source object in the content-addressed store."""

    pin: SAMSnapshotPin
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
class SAMCode:
    """One exact publisher-documented code, label, and retirement status."""

    resource_name: ResourceName
    use: SAMCodeUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    retired: bool
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class SAMOpportunitiesCodePortfolio:
    """A parsed, digest-pinned SAM.gov Opportunities controlled-code capture."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    source_url: str
    publisher_last_modified: str | None
    publisher_doc_version: str
    publisher_doc_version_date: str
    notice_types: tuple[SAMCode, ...]
    opportunity_statuses: tuple[SAMCode, ...]
    set_aside_codes: tuple[SAMCode, ...]
    status_version_history: tuple[str, ...]
    gaps: tuple[str, ...]

    def notice_types_by_code(self) -> dict[str, SAMCode]:
        """Index every notice type code, including retired ones."""

        return _index_by_code(self.notice_types)

    def opportunity_statuses_by_code(self) -> dict[str, SAMCode]:
        """Index every documented opportunity status value."""

        return _index_by_code(self.opportunity_statuses)

    def set_aside_codes_by_code(self) -> dict[str, SAMCode]:
        """Index every set-aside code, preserving exact publisher casing."""

        return _index_by_code(self.set_aside_codes)


SAM_PORTFOLIO_GAPS = (
    (
        "SAM.gov's Get Opportunities Public API documentation states this API "
        '"only provides the latest active version of the opportunity"; the '
        "documented ptype retirement note is the only mechanism that preserves "
        "the retired 'f' (Foreign Government Standard) and 'l' (Fair "
        "Opportunity / Limited Sources) notice type codes, which the live API "
        "no longer returns or accepts."
    ),
    (
        "Notice types, opportunity statuses, and set-aside codes are published "
        "only as prose text inside HTML documentation tables; open.gsa.gov "
        "publishes no machine-readable code-list endpoint or JSON schema for "
        "these values."
    ),
    (
        "The 'status' request parameter is marked '(Coming Soon)' in the "
        "documentation. Its five accepted values have no documented mapping "
        "onto response fields; the response schema on this page exposes only "
        "a boolean 'active' flag plus archiveType/archiveDate, not the "
        "five-value status vocabulary."
    ),
    (
        "The change log records that Set-Aside Values were added in v0.3 "
        "(10/17/19) and revised in v0.4 (10/23/19); this capture preserves "
        "only the current 18-code table and does not recover the pre-v0.4 "
        "set-aside code list."
    ),
)


def _index_by_code(codes: tuple[SAMCode, ...]) -> dict[str, SAMCode]:
    result: dict[str, SAMCode] = {}
    for entry in codes:
        result[entry.identifiers[0].value] = entry
    return result


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "open.gsa.gov":
        raise SAMAcquisitionError("fetcher resolved_url must remain on official HTTPS open.gsa.gov")
    if parsed.username is not None or parsed.password is not None:
        raise SAMAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: SAMSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise SAMSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise SAMSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SAMSourceDriftError(f"{location} is not valid UTF-8 HTML") from error
    if not text.lstrip().lower().startswith("<!doctype html"):
        raise SAMSourceDriftError(f"{location} does not open with an HTML doctype")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: SAMSnapshotPin) -> AcquiredSAMSource:
    if path.is_symlink() or not path.is_file():
        raise SAMAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached SAM.gov source",
    )
    return AcquiredSAMSource(
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
    pin: SAMSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredSAMSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} SAM.gov source",
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
        return AcquiredSAMSource(
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


def acquire_sam_opportunities_doc(
    pin: SAMSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: SAMFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredSAMSource:
    """Acquire the exact documentation response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise SAMAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise SAMAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise SAMAcquisitionError(f"local SAM.gov source is not a regular file: {local_path}")
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
        raise SAMAcquisitionError("SAM.gov documentation is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise SAMAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise SAMSourceDriftError(f"SAM.gov documentation content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _extract_request_parameter_cell(text: str, param_name: str) -> str:
    pattern = re.compile(
        r"<tr>\s*<td>" + re.escape(param_name) + r"</td>\s*<td>(.*?)</td>\s*<td>",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise SAMSourceDriftError(f"could not locate the {param_name!r} request parameter row")
    return match.group(1)


def _identifier(
    value: str,
    kind: str,
    source_uri: str,
    acquired: AcquiredSAMSource,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=SAM_IDENTIFIER_AUTHORITY_URI,
        source_uri=source_uri,
        observed_at=acquired.pin.retrieved_at,
        effective_at=None,
        source_digest=acquired.sha256,
    )


def _parse_notice_types(text: str, acquired: AcquiredSAMSource) -> tuple[SAMCode, ...]:
    cell = _extract_request_parameter_cell(text, "ptype")
    lines = [html.unescape(part).strip() for part in re.split(r"<br\s*/?>", cell)]
    lines = [line for line in lines if line]
    if not lines or not lines[0].startswith("Procurement Type."):
        raise SAMSourceDriftError("ptype cell lost its introductory sentence")

    retired = False
    codes: list[SAMCode] = []
    for line in lines[1:]:
        lowered = line.lower()
        if lowered.startswith("note: below services are now retired"):
            retired = True
            continue
        if lowered.startswith("use justification"):
            continue
        match = _NOTICE_TYPE_LINE.fullmatch(line)
        if match is None:
            raise SAMSourceDriftError(f"unrecognized ptype description line: {line!r}")
        code, label = match.group(1), match.group(2).strip()
        codes.append(
            SAMCode(
                resource_name="noticeTypes",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=SAM_DOC_REQUEST_PARAMETERS_ANCHOR,
                retired=retired,
                identifiers=(_identifier(code, "noticeTypeCode", SAM_DOC_REQUEST_PARAMETERS_ANCHOR, acquired),),
            )
        )

    if len(codes) != _RESOURCE_COUNTS["noticeTypes"]:
        raise SAMSourceDriftError(
            f"ptype code count drift: expected {_RESOURCE_COUNTS['noticeTypes']}, parsed {len(codes)}"
        )
    active_count = sum(1 for code in codes if not code.retired)
    retired_count = len(codes) - active_count
    if active_count != 9 or retired_count != 2:
        raise SAMSourceDriftError("ptype active/retired split drifted from the reviewed structure")
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise SAMSourceDriftError("ptype codes contain a duplicate publisher code")
    return tuple(codes)


def _parse_statuses(text: str, acquired: AcquiredSAMSource) -> tuple[SAMCode, ...]:
    cell = _extract_request_parameter_cell(text, "status (Coming Soon)")
    flattened = html.unescape(re.sub(r"<br\s*/?>", " ", cell)).strip()
    match = re.search(r"Accepts following:\s*(.+)$", flattened)
    if match is None:
        raise SAMSourceDriftError("status request parameter lost its accepted-values sentence")
    values = [value.strip() for value in match.group(1).split(",")]
    values = [value for value in values if value]
    if len(values) != _RESOURCE_COUNTS["opportunityStatuses"]:
        raise SAMSourceDriftError(
            f"status value count drift: expected {_RESOURCE_COUNTS['opportunityStatuses']}, parsed {len(values)}"
        )

    codes: list[SAMCode] = []
    for value in values:
        if _STATUS_CODE.fullmatch(value) is None:
            raise SAMSourceDriftError(f"malformed status value: {value!r}")
        codes.append(
            SAMCode(
                resource_name="opportunityStatuses",
                use="deterministicMetadata",
                publisher_label=value,
                source_url=SAM_DOC_REQUEST_PARAMETERS_ANCHOR,
                retired=False,
                identifiers=(_identifier(value, "opportunityStatusCode", SAM_DOC_REQUEST_PARAMETERS_ANCHOR, acquired),),
            )
        )
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise SAMSourceDriftError("status values contain a duplicate publisher code")
    return tuple(codes)


def _parse_set_aside_codes(text: str, acquired: AcquiredSAMSource) -> tuple[SAMCode, ...]:
    section = re.search(r'<h3 id="set-aside-values">.*?<table>(.*?)</table>', text, re.DOTALL)
    if section is None:
        raise SAMSourceDriftError("could not locate the Set-Aside Values table")
    rows = re.findall(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", section.group(1), re.DOTALL)
    if not rows:
        raise SAMSourceDriftError("Set-Aside Values table has no code rows")

    codes: list[SAMCode] = []
    for raw_code, raw_label in rows:
        code = html.unescape(raw_code).strip()
        label = html.unescape(raw_label).strip()
        if _SET_ASIDE_CODE.fullmatch(code) is None:
            raise SAMSourceDriftError(f"malformed set-aside code: {code!r}")
        if not label:
            raise SAMSourceDriftError(f"set-aside code {code!r} has an empty description")
        codes.append(
            SAMCode(
                resource_name="setAsideCodes",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=SAM_DOC_SET_ASIDE_VALUES_ANCHOR,
                retired=False,
                identifiers=(_identifier(code, "setAsideCode", SAM_DOC_SET_ASIDE_VALUES_ANCHOR, acquired),),
            )
        )
    if len(codes) != _RESOURCE_COUNTS["setAsideCodes"]:
        raise SAMSourceDriftError(
            f"set-aside code count drift: expected {_RESOURCE_COUNTS['setAsideCodes']}, parsed {len(codes)}"
        )
    if len({code.identifiers[0].value for code in codes}) != len(codes):
        raise SAMSourceDriftError("Set-Aside Values table contains duplicate codes")
    return tuple(codes)


def _parse_change_log(text: str) -> tuple[str, str, tuple[str, ...]]:
    section = re.search(r'<h2 id="change-log">.*?<table>(.*?)</table>', text, re.DOTALL)
    if section is None:
        raise SAMSourceDriftError("could not locate the Change Log table")
    rows = re.findall(
        r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
        section.group(1),
        re.DOTALL,
    )
    if not rows:
        raise SAMSourceDriftError("Change Log table has no version rows")

    parsed_rows = [
        (html.unescape(date).strip(), html.unescape(version).strip(), html.unescape(description).strip())
        for date, version, description in rows
    ]
    status_history = tuple(
        f"{version} ({date}): {description}"
        for date, version, description in parsed_rows
        if "status" in description.lower()
    )
    if not status_history:
        raise SAMSourceDriftError("Change Log lost every status-related version entry")
    latest_date, latest_version, _ = parsed_rows[-1]
    return latest_version, latest_date, status_history


def parse_sam_opportunities_codes(acquired: AcquiredSAMSource) -> SAMOpportunitiesCodePortfolio:
    """Parse exact publisher prose into three controlled code lists."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed SAM.gov source")
    text = payload.decode("utf-8")

    notice_types = _parse_notice_types(text, acquired)
    statuses = _parse_statuses(text, acquired)
    set_asides = _parse_set_aside_codes(text, acquired)
    doc_version, doc_version_date, status_history = _parse_change_log(text)

    return SAMOpportunitiesCodePortfolio(
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        source_url=acquired.pin.source.source_url,
        publisher_last_modified=acquired.pin.publisher_last_modified,
        publisher_doc_version=doc_version,
        publisher_doc_version_date=doc_version_date,
        notice_types=notice_types,
        opportunity_statuses=statuses,
        set_aside_codes=set_asides,
        status_version_history=status_history,
        gaps=SAM_PORTFOLIO_GAPS,
    )


def validate_notice_type_query_value(
    value: str,
    portfolio: SAMOpportunitiesCodePortfolio,
) -> SAMCode:
    """Validate one submitted ``ptype`` filter value; retired codes fail closed."""

    code = portfolio.notice_types_by_code().get(value)
    if code is None:
        raise SAMAssignmentError(f"unknown SAM.gov notice type code {value!r}")
    if code.retired:
        raise SAMAssignmentError(
            f"SAM.gov notice type code {value!r} ({code.publisher_label}) is documented as retired"
        )
    return code


def validate_status_query_value(
    value: str,
    portfolio: SAMOpportunitiesCodePortfolio,
) -> SAMCode:
    """Validate one submitted ``status`` filter value."""

    code = portfolio.opportunity_statuses_by_code().get(value)
    if code is None:
        raise SAMAssignmentError(f"unknown SAM.gov opportunity status {value!r}")
    return code


def validate_set_aside_code(
    value: str,
    portfolio: SAMOpportunitiesCodePortfolio,
) -> SAMCode:
    """Validate one submitted set-aside code using its exact publisher casing."""

    code = portfolio.set_aside_codes_by_code().get(value)
    if code is None:
        raise SAMAssignmentError(f"unknown SAM.gov set-aside code {value!r}")
    return code


def _package_observations(
    resource_name: ResourceName,
    codes: tuple[SAMCode, ...],
    acquired: AcquiredSAMSource,
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
            "urn:ref:source-observation:sam-opportunities:"
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
                "eligibleUses": [code.use],
                "conceptIdentityClaimed": False,
                "retired": code.retired,
            }
        )
    return tuple(observations)


def build_sam_opportunities_code_package(
    resource_name: ResourceName,
    portfolio: SAMOpportunitiesCodePortfolio,
    acquired: AcquiredSAMSource,
) -> SourceControlledResourceBundle:
    """Build one development-only, deterministic closed package for one code family."""

    codes_by_resource: Mapping[ResourceName, tuple[SAMCode, ...]] = {
        "noticeTypes": portfolio.notice_types,
        "opportunityStatuses": portfolio.opportunity_statuses,
        "setAsideCodes": portfolio.set_aside_codes,
    }
    if resource_name not in codes_by_resource:
        raise SAMPackageError(f"unknown SAM.gov resource family {resource_name!r}")
    codes = codes_by_resource[resource_name]
    payload = acquired.path.read_bytes()
    captured_date = portfolio.retrieved_at[:10]
    return build_source_controlled_resource_bundle(
        resource_id=f"sam-opportunities-{resource_name}-{captured_date}",
        title=f"SAM.gov Opportunities {resource_name}, captured {captured_date}",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=portfolio.retrieved_at,
        candidate_use_authorized=True,
        observations=_package_observations(resource_name, codes, acquired),
        source_artifacts={acquired.pin.source.source_url: payload},
        source_observed_count=len(codes),
        gaps=[{"kind": "sourceProseOnly", "reason": gap} for gap in portfolio.gaps],
    )


__all__ = [
    "SAM_IDENTIFIER_AUTHORITY_URI",
    "SAM_OPPORTUNITIES_DOC_2026_08_03",
    "SAM_OPPORTUNITIES_DOC_SOURCE",
    "SAM_PORTFOLIO_GAPS",
    "SAM_PUBLISHER",
    "AcquiredSAMSource",
    "FetchedSAMResponse",
    "ResourceName",
    "SAMAcquisitionError",
    "SAMAssignmentError",
    "SAMCode",
    "SAMFetcher",
    "SAMOpportunitiesCodeError",
    "SAMOpportunitiesCodePortfolio",
    "SAMOpportunitiesDocSource",
    "SAMPackageError",
    "SAMSnapshotPin",
    "SAMSourceDriftError",
    "acquire_sam_opportunities_doc",
    "build_sam_opportunities_code_package",
    "parse_sam_opportunities_codes",
    "sha256_digest",
    "validate_notice_type_query_value",
    "validate_set_aside_code",
    "validate_status_query_value",
]

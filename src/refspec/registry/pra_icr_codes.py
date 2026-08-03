"""Pinned Paperwork Reduction Act ICR search controlled values for ``pra-icr-v1``.

The official PRASearch page (https://www.reginfo.gov/public/do/PRASearch)
renders its Information Collection Review search form as server-side HTML.
That form exposes the OMB Control Number field shape, the closed Type of
Request list, the closed ICR Status list, and the five Burden Range measures
(Hours, Dollars, Responses, Respondents, Respondents-Small Entities) as
``<select>``/``<option>`` and labeled ``<input>`` elements with publisher
codes and field identifiers.

Catalog guidance binds this module to that scope only: OMB Control Number
shape, request types, statuses, and burden fields. The page also renders a
Conclusion Action list, a Type of Review list, Certification checkboxes, an
ICR Ended Due To list, and a Date Type list; those remain out of scope and
are recorded as gaps rather than silently dropped. Agency and Sub-Agency
codes are populated by client-side JavaScript after page load and are never
present in the captured server-rendered bytes, so this module does not
attempt to scrape them.

No maintained Paperwork Reduction Act subject thesaurus exists. Every value
captured here is deterministic search or administrative metadata -- never a
general-subject concept -- and the module packages it as a
``controlledCodeList`` resource rather than promoting it into a concept
scheme.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

PRA_PUBLISHER = "Office of Information and Regulatory Affairs, Office of Management and Budget"
PRA_IDENTIFIER_AUTHORITY_URI = "https://www.reginfo.gov/"
PRA_SEARCH_URL = "https://www.reginfo.gov/public/do/PRASearch"

ResourceName = Literal["ombControlNumberShape", "requestTypes", "icrStatuses", "burdenMeasures"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_CODE_VALUE = re.compile(r"^[A-Z]{2}$")
# OMB Control Numbers are documented on the source page as NNNN-XXXX (an
# agency/subagency code, a hyphen, and a sequential number). The page never
# renders that shape as a machine regex, so this pattern is derived from the
# documented convention and cross-checked against the field's maxlength.
OMB_CONTROL_NUMBER_PATTERN = re.compile(r"^\d{4}-\d{4}$")
_OMB_CONTROL_NUMBER_MAX_LENGTH = 9
_IDENTIFIER_ATTRIBUTE_BY_KIND = {
    "requestTypeCode": "value",
    "icrStatusCode": "value",
    "burdenMeasureLowFieldId": "id",
    "burdenMeasureHighFieldId": "id",
    "ombControlNumberFieldId": "name",
    "ombControlNumberMaxLength": "maxlength",
}


class PRAResourceError(ValueError):
    """Base class for PRA ICR controlled-value failures."""


class PRAAcquisitionError(PRAResourceError):
    """Exact official source bytes could not be acquired safely."""


class PRASourceDriftError(PRAResourceError):
    """The PRASearch page no longer matches the reviewed structure or pin."""


class PRAAssignmentError(PRAResourceError):
    """An ICR record carries an unknown or inconsistent source-assigned code."""


@dataclass(frozen=True, slots=True)
class PRAPageSource:
    """The one official PRA ICR search page that publishes these values."""

    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "www.reginfo.gov":
            raise PRAAcquisitionError("source_url must be an official HTTPS www.reginfo.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise PRAAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise PRAAcquisitionError("filename must be one plain path component")


PRA_SEARCH_PAGE = PRAPageSource(
    source_url=PRA_SEARCH_URL,
    filename="pra-search.html",
)


@dataclass(frozen=True, slots=True)
class PRASnapshotPin:
    """Exact identity of one official PRASearch page capture."""

    source: PRAPageSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_request_type_count: int
    expected_icr_status_count: int
    expected_burden_measure_count: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise PRAAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise PRAAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise PRAAcquisitionError("retrieved_at must not be empty")
        if (
            self.expected_request_type_count <= 0
            or self.expected_icr_status_count <= 0
            or self.expected_burden_measure_count <= 0
        ):
            raise PRAAcquisitionError("expected control counts must be positive")


# This pin was captured live from the official PRASearch page. It is updated
# only when a new exact capture replaces it after review.
PRA_SEARCH_PAGE_2026_08_03 = PRASnapshotPin(
    source=PRA_SEARCH_PAGE,
    retrieved_at="2026-08-03T19:13:39Z",
    expected_sha256="sha256:7f1e24bbe278c67171a71c9e85d50bf7c886646ae25c835194bda5a6e9d4fa4e",
    expected_byte_length=174_551,
    expected_request_type_count=10,
    expected_icr_status_count=5,
    expected_burden_measure_count=5,
)


@dataclass(frozen=True, slots=True)
class FetchedPRAResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class PRAFetcher(Protocol):
    """Small transport boundary for the official PRASearch page."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedPRAResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredPRASource:
    """One verified source object in the content-addressed store."""

    pin: PRASnapshotPin
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
class PRACode:
    """One exact publisher label plus its identifiers and HTML source path."""

    resource_name: ResourceName
    publisher_label: str
    source_url: str
    source_path: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedPRAResource:
    """A parsed, digest-pinned set of PRA ICR controlled values."""

    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    source_url: str
    omb_control_number_shape: PRACode
    request_types: tuple[PRACode, ...]
    icr_statuses: tuple[PRACode, ...]
    burden_measures: tuple[PRACode, ...]
    gaps: tuple[str, ...]

    def by_request_type_code(self) -> dict[str, PRACode]:
        """Index request types by their exact ``requestType`` option value."""

        return _by_identifier_kind(self.request_types, "requestTypeCode")

    def by_icr_status_code(self) -> dict[str, PRACode]:
        """Index ICR statuses by their exact ``icrStatus`` option value."""

        return _by_identifier_kind(self.icr_statuses, "icrStatusCode")

    def all_codes(self) -> tuple[PRACode, ...]:
        """Return every captured control value in a stable packaging order."""

        return (self.omb_control_number_shape, *self.request_types, *self.icr_statuses, *self.burden_measures)


@dataclass(frozen=True, slots=True)
class PRACodeAssignment:
    """A control value validated against the exact source snapshot."""

    source_field: str
    publisher_label: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedPRAICRControls:
    """Code evidence retained from one ``pra-icr-v1`` record."""

    omb_control_number: str | None
    request_type: PRACodeAssignment | None
    icr_status: PRACodeAssignment | None
    gaps: tuple[str, ...]


PRA_PORTFOLIO_GAPS = (
    (
        "The PRASearch page also publishes Conclusion Action, Type of Review, Certification, "
        "ICR Ended Due To, and Date Type controls; catalog guidance binds this module to OMB "
        "Control Number shape, request types, ICR statuses, and burden fields, so those "
        "controls are not packaged."
    ),
    (
        "Agency and Sub-Agency codes are generated by client-side JavaScript after page load "
        "and are absent from the captured server-rendered HTML; this module does not execute "
        "client-side scripts to scrape them."
    ),
    (
        "The page publishes no standalone code-list release date or revision identifier for "
        "these controlled values; retrieval time and the exact page digest are the available "
        "revision pin."
    ),
    (
        "No separate Paperwork Reduction Act subject thesaurus exists; every value captured "
        "here is deterministic search or administrative metadata, not a general-subject concept."
    ),
)
_PRA_PACKAGE_GAPS = (
    MappingProxyType({"kind": "outOfScopeControlsExcluded", "reason": PRA_PORTFOLIO_GAPS[0]}),
    MappingProxyType({"kind": "javaScriptPopulatedAgencyCodes", "reason": PRA_PORTFOLIO_GAPS[1]}),
    MappingProxyType({"kind": "publisherReleaseUnavailable", "reason": PRA_PORTFOLIO_GAPS[2]}),
    MappingProxyType({"kind": "noSubjectThesaurus", "reason": PRA_PORTFOLIO_GAPS[3]}),
)

PRA_ICR_RESOURCE_ID = "pra-icr-search-controlled-values-2026-08-03"
PRA_ICR_PACKAGE_TITLE = "PRA ICR Search Controlled Values, captured 2026-08-03"


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _by_identifier_kind(codes: Sequence[PRACode], kind: str) -> dict[str, PRACode]:
    result: dict[str, PRACode] = {}
    for entry in codes:
        matches = [identifier for identifier in entry.identifiers if identifier.kind == kind]
        if len(matches) != 1:
            raise PRASourceDriftError(f"{entry.resource_name} row must retain exactly one {kind}")
        result[matches[0].value] = entry
    return result


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.reginfo.gov":
        raise PRAAcquisitionError("fetcher resolved_url must remain on official HTTPS www.reginfo.gov")
    if parsed.username is not None or parsed.password is not None:
        raise PRAAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: PRASnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise PRASourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise PRASourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PRASourceDriftError(f"{location} is not valid UTF-8 text") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: PRASnapshotPin) -> AcquiredPRASource:
    if path.is_symlink() or not path.is_file():
        raise PRAAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached PRA source",
    )
    return AcquiredPRASource(
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
    pin: PRASnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredPRASource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} PRA source",
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
        return AcquiredPRASource(
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


def acquire_pra_search_page(
    pin: PRASnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: PRAFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredPRASource:
    """Acquire one exact PRASearch page through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise PRAAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise PRAAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise PRAAcquisitionError(f"local PRA source is not a regular file: {local_path}")
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
        raise PRAAcquisitionError("PRASearch page is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise PRAAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise PRASourceDriftError(f"PRASearch content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _extract_select_options(html_text: str, element_id: str) -> list[tuple[str, str]]:
    anchor = re.search(
        rf'<select id="{re.escape(element_id)}" name="{re.escape(element_id)}"[^>]*>',
        html_text,
    )
    if anchor is None:
        raise PRASourceDriftError(f'PRASearch page no longer publishes a <select id="{element_id}"> control')
    end = html_text.find("</select>", anchor.end())
    if end == -1:
        raise PRASourceDriftError(f"PRASearch page {element_id} select is never closed")
    block = html_text[anchor.end() : end]
    options = re.findall(r'<option value="([^"]*)">([^<]*)</option>', block)
    return [(value, html.unescape(label).strip()) for value, label in options if value]


_BURDEN_ROW_PATTERN = re.compile(
    r'<td[^>]*style="font-weight:600;">\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*Between\s*'
    r'<input id="(low\w+)"[^>]*/>.*?<input id="(high\w+)"[^>]*/>',
    re.DOTALL,
)


def _extract_burden_rows(html_text: str) -> list[tuple[str, str, str]]:
    matches = _BURDEN_ROW_PATTERN.findall(html_text)
    return [(html.unescape(label).strip(), low_id, high_id) for label, low_id, high_id in matches]


_OMB_INPUT_TAG = re.compile(r'<input id="ombControlNumber"[^>]*>')


def _extract_omb_control_number_field(html_text: str) -> tuple[str, int]:
    match = _OMB_INPUT_TAG.search(html_text)
    if match is None:
        raise PRASourceDriftError("PRASearch page no longer publishes an ombControlNumber field")
    tag = match.group(0)
    name_match = re.search(r'name="([^"]*)"', tag)
    max_length_match = re.search(r'maxlength="(\d+)"', tag)
    if name_match is None or max_length_match is None:
        raise PRASourceDriftError("PRASearch page ombControlNumber field is missing name or maxlength")
    return name_match.group(1), int(max_length_match.group(1))


def _require_unique_codes(codes: Sequence[PRACode], kind: str) -> None:
    values = [identifier.value for entry in codes for identifier in entry.identifiers if identifier.kind == kind]
    if len(values) != len(codes) or len(set(values)) != len(codes):
        raise PRASourceDriftError(f"PRASearch {kind} rows must each retain exactly one distinct code")
    labels = {entry.publisher_label for entry in codes}
    if len(labels) != len(codes):
        raise PRASourceDriftError(f"PRASearch {kind} rows contain duplicate publisher labels")


def parse_pra_icr_controls(acquired: AcquiredPRASource) -> ParsedPRAResource:
    """Parse exact request-type, status, burden, and OMB-number-shape controls."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed PRA source")
    html_text = payload.decode("utf-8")
    if 'name="PRASearchForm"' not in html_text or 'name="requestTypeCategory" value="ICR"' not in html_text:
        raise PRASourceDriftError("PRASearch page no longer carries the expected ICR search form")

    source_url = acquired.pin.source.source_url
    observed_at = acquired.pin.retrieved_at
    digest = acquired.sha256

    def identifier(value: str, kind: str) -> ControlledIdentifier:
        return ControlledIdentifier(
            value=value,
            kind=kind,
            authority_uri=PRA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source_url,
            observed_at=observed_at,
            effective_at=None,
            source_digest=digest,
        )

    request_type_rows = _extract_select_options(html_text, "requestType")
    if len(request_type_rows) != acquired.pin.expected_request_type_count:
        raise PRASourceDriftError(
            f"requestTypes count drift: expected {acquired.pin.expected_request_type_count}, "
            f"parsed {len(request_type_rows)}"
        )
    request_types: list[PRACode] = []
    for code, label in request_type_rows:
        if _CODE_VALUE.fullmatch(code) is None:
            raise PRASourceDriftError(f"PRASearch requestType row has malformed publisher code {code!r}")
        if not label:
            raise PRASourceDriftError(f"PRASearch requestType row {code!r} has an empty publisher label")
        request_types.append(
            PRACode(
                resource_name="requestTypes",
                publisher_label=label,
                source_url=source_url,
                source_path=f'select[@id="requestType"]/option[@value="{code}"]',
                identifiers=(identifier(code, "requestTypeCode"),),
            )
        )
    _require_unique_codes(request_types, "requestTypeCode")

    icr_status_rows = _extract_select_options(html_text, "icrStatus")
    if len(icr_status_rows) != acquired.pin.expected_icr_status_count:
        raise PRASourceDriftError(
            f"icrStatuses count drift: expected {acquired.pin.expected_icr_status_count}, parsed {len(icr_status_rows)}"
        )
    icr_statuses: list[PRACode] = []
    for code, label in icr_status_rows:
        if _CODE_VALUE.fullmatch(code) is None:
            raise PRASourceDriftError(f"PRASearch icrStatus row has malformed publisher code {code!r}")
        if not label:
            raise PRASourceDriftError(f"PRASearch icrStatus row {code!r} has an empty publisher label")
        icr_statuses.append(
            PRACode(
                resource_name="icrStatuses",
                publisher_label=label,
                source_url=source_url,
                source_path=f'select[@id="icrStatus"]/option[@value="{code}"]',
                identifiers=(identifier(code, "icrStatusCode"),),
            )
        )
    _require_unique_codes(icr_statuses, "icrStatusCode")

    burden_rows = _extract_burden_rows(html_text)
    if len(burden_rows) != acquired.pin.expected_burden_measure_count:
        raise PRASourceDriftError(
            f"burdenMeasures count drift: expected {acquired.pin.expected_burden_measure_count}, "
            f"parsed {len(burden_rows)}"
        )
    burden_measures: list[PRACode] = []
    for label, low_id, high_id in burden_rows:
        if not label:
            raise PRASourceDriftError("PRASearch burden row has an empty publisher label")
        if low_id[3:].lower() != high_id[4:].lower():
            raise PRASourceDriftError(f"PRASearch burden row field ids do not pair: {low_id!r}/{high_id!r}")
        burden_measures.append(
            PRACode(
                resource_name="burdenMeasures",
                publisher_label=label,
                source_url=source_url,
                source_path=f'input[@id="{low_id}"]|input[@id="{high_id}"]',
                identifiers=(
                    identifier(low_id, "burdenMeasureLowFieldId"),
                    identifier(high_id, "burdenMeasureHighFieldId"),
                ),
            )
        )
    if len({entry.publisher_label for entry in burden_measures}) != len(burden_measures):
        raise PRASourceDriftError("PRASearch burden rows contain duplicate publisher labels")

    field_name, max_length = _extract_omb_control_number_field(html_text)
    if field_name != "ombControlNumber":
        raise PRASourceDriftError(f"PRASearch OMB Control Number field name drifted to {field_name!r}")
    if max_length != _OMB_CONTROL_NUMBER_MAX_LENGTH:
        raise PRASourceDriftError(
            f"PRASearch OMB Control Number maxlength drifted: expected "
            f"{_OMB_CONTROL_NUMBER_MAX_LENGTH}, got {max_length}"
        )
    omb_shape = PRACode(
        resource_name="ombControlNumberShape",
        publisher_label="OMB Control Number",
        source_url=source_url,
        source_path='input[@id="ombControlNumber"]',
        identifiers=(
            identifier(field_name, "ombControlNumberFieldId"),
            identifier(str(max_length), "ombControlNumberMaxLength"),
        ),
    )

    return ParsedPRAResource(
        retrieved_at=observed_at,
        source_sha256=digest,
        source_byte_length=acquired.byte_length,
        source_url=source_url,
        omb_control_number_shape=omb_shape,
        request_types=tuple(request_types),
        icr_statuses=tuple(icr_statuses),
        burden_measures=tuple(burden_measures),
        gaps=PRA_PORTFOLIO_GAPS,
    )


def _validate_code_field(
    record: Mapping[str, object],
    *,
    code_field: str,
    display_field: str,
    lookup: Mapping[str, PRACode],
    error_label: str,
) -> PRACodeAssignment | None:
    raw_code = record.get(code_field)
    if raw_code is None:
        return None
    if not isinstance(raw_code, str):
        raise PRAAssignmentError(f"{code_field} must be a string code")
    code = lookup.get(raw_code)
    if code is None:
        raise PRAAssignmentError(f"unknown PRA {error_label} {raw_code!r}")
    raw_display = record.get(display_field)
    if raw_display is not None and raw_display != code.publisher_label:
        raise PRAAssignmentError(
            f"{error_label} display mismatch for {raw_code}: expected {code.publisher_label!r}, got {raw_display!r}"
        )
    return PRACodeAssignment(
        source_field=code_field,
        publisher_label=code.publisher_label,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_icr_record(
    record: Mapping[str, object],
    resource: ParsedPRAResource,
) -> ValidatedPRAICRControls:
    """Validate exact source codes retained by one ``pra-icr-v1`` record."""

    raw_omb = record.get("omb_control_number")
    omb_control_number: str | None = None
    if raw_omb is not None:
        if not isinstance(raw_omb, str) or OMB_CONTROL_NUMBER_PATTERN.fullmatch(raw_omb) is None:
            raise PRAAssignmentError(f"malformed OMB Control Number {raw_omb!r}; expected NNNN-NNNN")
        omb_control_number = raw_omb

    request_type = _validate_code_field(
        record,
        code_field="request_type",
        display_field="request_type_display",
        lookup=resource.by_request_type_code(),
        error_label="request_type",
    )
    icr_status = _validate_code_field(
        record,
        code_field="icr_status",
        display_field="icr_status_display",
        lookup=resource.by_icr_status_code(),
        error_label="icr_status",
    )
    return ValidatedPRAICRControls(
        omb_control_number=omb_control_number,
        request_type=request_type,
        icr_status=icr_status,
        gaps=resource.gaps,
    )


def _identifier_row(identifier: ControlledIdentifier, *, source_path: str) -> dict[str, Any]:
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": source_path,
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _observation_id(*, source_url: str, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "resourceId": PRA_ICR_RESOURCE_ID,
        "sourceArtifact": source_url,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]} for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{PRA_ICR_RESOURCE_ID}:{digest}"


def _observation_row(code: PRACode, *, ordinal: int) -> dict[str, Any]:
    identifier_rows = [
        _identifier_row(
            item,
            source_path=f"{code.source_path}/@{_IDENTIFIER_ATTRIBUTE_BY_KIND[item.kind]}",
        )
        for item in code.identifiers
    ]
    return {
        "id": _observation_id(
            source_url=code.source_url,
            source_path=code.source_path,
            identifiers=identifier_rows,
        ),
        "sourceArtifact": code.source_url,
        "sourcePath": code.source_path,
        # This ordinal is a source-order locator only. Publisher identity is
        # preserved in identifiers and never derived from row order.
        "sourceOrdinal": ordinal,
        "labels": [
            {
                "value": code.publisher_label,
                "language": "en",
                "role": "preferred",
            }
        ],
        "identifiers": identifier_rows,
        "eligibleUses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
    }


def build_pra_icr_controlled_value_package(source_path: Path) -> SourceControlledResourceBundle:
    """Build one exact, development-only PRA ICR controlled-value package."""

    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise PRAAcquisitionError(f"PRA source is not a regular file: {path}")
    payload = path.read_bytes()

    with tempfile.TemporaryDirectory(prefix="refspec-pra-package-") as temporary:
        acquired = acquire_pra_search_page(
            PRA_SEARCH_PAGE_2026_08_03,
            Path(temporary) / "store",
            source_path=path,
        )
        resource = parse_pra_icr_controls(acquired)

    observations = tuple(_observation_row(code, ordinal=ordinal) for ordinal, code in enumerate(resource.all_codes()))
    return build_source_controlled_resource_bundle(
        resource_id=PRA_ICR_RESOURCE_ID,
        title=PRA_ICR_PACKAGE_TITLE,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=resource.retrieved_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts={resource.source_url: payload},
        source_observed_count=len(observations),
        gaps=_PRA_PACKAGE_GAPS,
    )


__all__ = [
    "OMB_CONTROL_NUMBER_PATTERN",
    "PRA_ICR_PACKAGE_TITLE",
    "PRA_ICR_RESOURCE_ID",
    "PRA_IDENTIFIER_AUTHORITY_URI",
    "PRA_PORTFOLIO_GAPS",
    "PRA_PUBLISHER",
    "PRA_SEARCH_PAGE",
    "PRA_SEARCH_PAGE_2026_08_03",
    "PRA_SEARCH_URL",
    "AcquiredPRASource",
    "AcquisitionMode",
    "FetchedPRAResponse",
    "PRAAcquisitionError",
    "PRAAssignmentError",
    "PRACode",
    "PRACodeAssignment",
    "PRAFetcher",
    "PRAPageSource",
    "PRAResourceError",
    "PRASnapshotPin",
    "PRASourceDriftError",
    "ParsedPRAResource",
    "ResourceName",
    "ValidatedPRAICRControls",
    "acquire_pra_search_page",
    "build_pra_icr_controlled_value_package",
    "parse_pra_icr_controls",
    "sha256_digest",
    "validate_icr_record",
]

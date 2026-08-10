"""Pinned LDA issue and filing code imports for ``lobbying-filing-v1``.

The official Lobbying Disclosure API publishes General Issue Codes and Filing
Types as JSON arrays of ``value``/``name`` pairs. General Issue Codes are
filer-selected source evidence. Filing Types and the OpenAPI filing-period enum
are deterministic filing metadata. None of these values is a general subject
concept merely because it has a readable label.

The API does not publish a named code-list release, an independent filing-status
list, or stable concept IRIs. RefSpec therefore identifies a source snapshot by
the official URL, API interface version, retrieval time, byte length, and
SHA-256 digest. It preserves the publisher-issued code as identity and does not
derive an IRI or a separate status code from the label.

Acquisition accepts a local exact capture or an injected fetcher. Importing this
module never opens a network connection, and no scraping provider is required
for the current JSON endpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode

LDA_PUBLISHER = "Clerk of the U.S. House of Representatives and Secretary of the U.S. Senate"
LDA_IDENTIFIER_AUTHORITY_URI = "https://lda.gov/"
LDA_API_BASE = "https://lda.gov/api/v1"
LDA_OPENAPI_URL = "https://lda.gov/api/openapi/v1/"
LDA_API_INTERFACE_VERSION = "1.0.0"
LDA_OPENAPI_JSON_MEDIA_TYPE = "application/vnd.oai.openapi+json"

# Exact OpenAPI JSON observed on 2026-07-30. This pins the source for the
# filing-period enum and proves that no filing-status constants path existed.
LDA_OPENAPI_2026_07_30_SHA256 = "sha256:0995cb8dc67b20195230075230f40710915cbee7d506ad639de9ffbc11de2d6f"
LDA_OPENAPI_2026_07_30_BYTE_LENGTH = 322_740
LDA_OPENAPI_2026_07_30_RETRIEVED_AT = "2026-07-30T12:46:07Z"
LDA_FILING_PERIOD_VALUES = (
    "first_quarter",
    "second_quarter",
    "third_quarter",
    "fourth_quarter",
    "mid_year",
    "year_end",
)

ResourceName = Literal["generalIssueCodes", "filingTypes"]
ResourceUse = Literal["sourceAssignedEvidence", "deterministicMetadata"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_GENERAL_ISSUE_CODE = re.compile(r"^[A-Z]{3}$")
_FILING_TYPE_CODE = re.compile(r"^[A-Z0-9@]{1,3}$")
_ADDITIONAL_IDENTIFIER_KINDS = {
    "id": "publisherRecordId",
    "identifier": "publisherIdentifier",
    "code": "publisherCode",
    "url": "publisherTermURI",
}


class LDAResourceError(ValueError):
    """Base class for LDA controlled-code failures."""


class LDAAcquisitionError(LDAResourceError):
    """Exact official source bytes could not be acquired safely."""


class LDASourceDriftError(LDAResourceError):
    """An LDA source no longer matches the reviewed structure or pin."""


class LDAAssignmentError(LDAResourceError):
    """A filing carries an unknown or inconsistent source-assigned code."""


@dataclass(frozen=True, slots=True)
class LDAConstantSource:
    """One official LDA constants endpoint."""

    resource_name: ResourceName
    use: ResourceUse
    source_url: str
    filename: str
    expected_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "lda.gov":
            raise LDAAcquisitionError("source_url must be an official HTTPS lda.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise LDAAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise LDAAcquisitionError("filename must be one plain path component")
        if self.expected_count <= 0:
            raise LDAAcquisitionError("expected_count must be positive")


LDA_GENERAL_ISSUE_CODES = LDAConstantSource(
    resource_name="generalIssueCodes",
    use="sourceAssignedEvidence",
    source_url=f"{LDA_API_BASE}/constants/filing/lobbyingactivityissues/",
    filename="lobbying-activity-issues.json",
    expected_count=79,
)
LDA_FILING_TYPES = LDAConstantSource(
    resource_name="filingTypes",
    use="deterministicMetadata",
    source_url=f"{LDA_API_BASE}/constants/filing/filingtypes/",
    filename="filing-types.json",
    expected_count=50,
)


@dataclass(frozen=True, slots=True)
class LDASnapshotPin:
    """Exact identity of one official constants response."""

    source: LDAConstantSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    api_interface_version: str = LDA_API_INTERFACE_VERSION
    publisher_release: str | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise LDAAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise LDAAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at or not self.api_interface_version:
            raise LDAAcquisitionError("retrieved_at and api_interface_version must not be empty")


LDA_GENERAL_ISSUE_CODES_2026_07_30 = LDASnapshotPin(
    source=LDA_GENERAL_ISSUE_CODES,
    retrieved_at="2026-07-30T12:45:14Z",
    expected_sha256="sha256:e1820ef17f3e63048ae50e526c2f56e507b2cf60d720fc227c76ee7c3610d5bf",
    expected_byte_length=3_596,
)
LDA_FILING_TYPES_2026_07_30 = LDASnapshotPin(
    source=LDA_FILING_TYPES,
    retrieved_at="2026-07-30T12:45:14Z",
    expected_sha256="sha256:49fbd39383b0be63fb474878aa229d4e397880a30c2e0dac1a0905bc660a3149",
    expected_byte_length=2_803,
)


@dataclass(frozen=True, slots=True)
class FetchedLDAResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class LDAFetcher(Protocol):
    """Small transport boundary for official LDA JSON endpoints."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedLDAResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredLDASource:
    """One verified source object in the content-addressed store."""

    pin: LDASnapshotPin
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
class LDACode:
    """One exact label plus every identifier published for that row."""

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedLDAResource:
    """A parsed, digest-pinned LDA code list."""

    source: LDAConstantSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    api_interface_version: str
    publisher_release: str | None
    codes: tuple[LDACode, ...]
    gaps: tuple[str, ...]

    def by_code(self) -> dict[str, LDACode]:
        """Index the endpoint's ``value`` code while retaining all other IDs."""

        code_kind = "generalIssueCode" if self.source.resource_name == "generalIssueCodes" else "filingTypeCode"
        result: dict[str, LDACode] = {}
        for entry in self.codes:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == code_kind]
            if len(matches) != 1:
                raise LDASourceDriftError(f"{self.source.resource_name} row must retain exactly one {code_kind}")
            result[matches[0].value] = entry
        return result


@dataclass(frozen=True, slots=True)
class LDAControlPortfolio:
    """The two imported resources and known unsupported controls."""

    general_issue_codes: ParsedLDAResource
    filing_types: ParsedLDAResource
    filing_period_values: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LDAFilingCodeAssignment:
    """A filing value validated against the exact source snapshot."""

    source_field: str
    publisher_label: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedLDAFilingCodes:
    """Code evidence retained from one ``lobbying-filing-v1`` record."""

    filing_type: LDAFilingCodeAssignment
    filing_period: str | None
    general_issues: tuple[LDAFilingCodeAssignment, ...]
    filing_status: None
    gaps: tuple[str, ...]


LDA_PORTFOLIO_GAPS = (
    (
        "The constants endpoints do not publish a code-list release date or revision identifier; "
        "retrieval time and exact digest are the available revision pin."
    ),
    (
        "The official API publishes no standalone filing-status code list; report, amendment, "
        "termination, and no-activity semantics remain embedded in Filing Type codes."
    ),
    (
        "The official API publishes filing-period enum values but no independent period constants "
        "endpoint or authoritative display-label list."
    ),
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "lda.gov":
        raise LDAAcquisitionError("fetcher resolved_url must remain on official HTTPS lda.gov")
    if parsed.username is not None or parsed.password is not None:
        raise LDAAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: LDASnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise LDASourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise LDASourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LDASourceDriftError(f"{location} is not valid JSON") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: LDASnapshotPin) -> AcquiredLDASource:
    if path.is_symlink() or not path.is_file():
        raise LDAAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached LDA source",
    )
    return AcquiredLDASource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type="application/json",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: LDASnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredLDASource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} LDA source",
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
        return AcquiredLDASource(
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


def acquire_lda_constants(
    pin: LDASnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: LDAFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredLDASource:
    """Acquire one exact constants response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise LDAAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise LDAAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise LDAAcquisitionError(f"local LDA source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="application/json",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise LDAAcquisitionError("LDA constants are not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise LDAAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"application/json", "application/problem+json"}:
        raise LDASourceDriftError(f"LDA constants content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def parse_lda_constants(acquired: AcquiredLDASource) -> ParsedLDAResource:
    """Parse exact ``value``/``name`` records without converting them to concepts."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed LDA source")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LDASourceDriftError("LDA constants payload is not valid JSON") from error
    if not isinstance(root, list):
        raise LDASourceDriftError("LDA constants payload must be an array")
    if len(root) != acquired.pin.source.expected_count:
        raise LDASourceDriftError(
            f"{acquired.pin.source.resource_name} count drift: expected "
            f"{acquired.pin.source.expected_count}, parsed {len(root)}"
        )

    code_pattern = (
        _GENERAL_ISSUE_CODE if acquired.pin.source.resource_name == "generalIssueCodes" else _FILING_TYPE_CODE
    )
    parsed: list[LDACode] = []
    for ordinal, record in enumerate(root, start=1):
        if not isinstance(record, Mapping):
            raise LDASourceDriftError(f"LDA constants record {ordinal} must be an object")
        allowed_fields = {"value", "name", *_ADDITIONAL_IDENTIFIER_KINDS}
        if not {"value", "name"}.issubset(record) or not set(record).issubset(allowed_fields):
            raise LDASourceDriftError(f"LDA constants record {ordinal} fields drifted: {sorted(record)}")
        code = record["value"]
        label = record["name"]
        if not isinstance(code, str) or code_pattern.fullmatch(code) is None:
            raise LDASourceDriftError(f"LDA constants record {ordinal} has malformed publisher code")
        if not isinstance(label, str) or not label.strip() or label != label.strip():
            raise LDASourceDriftError(f"LDA constants record {ordinal} has malformed publisher label")
        code_kind = "generalIssueCode" if acquired.pin.source.resource_name == "generalIssueCodes" else "filingTypeCode"
        identifiers = [
            ControlledIdentifier(
                value=code,
                kind=code_kind,
                authority_uri=LDA_IDENTIFIER_AUTHORITY_URI,
                source_uri=acquired.pin.source.source_url,
                observed_at=acquired.pin.retrieved_at,
                effective_at=None,
                source_digest=acquired.sha256,
            )
        ]
        for field_name, identifier_kind in _ADDITIONAL_IDENTIFIER_KINDS.items():
            raw_identifier = record.get(field_name)
            if raw_identifier is None:
                continue
            if not isinstance(raw_identifier, (str, int)) or not str(raw_identifier).strip():
                raise LDASourceDriftError(f"LDA constants record {ordinal} has malformed {field_name} identifier")
            identifiers.append(
                ControlledIdentifier(
                    value=str(raw_identifier).strip(),
                    kind=identifier_kind,
                    authority_uri=LDA_IDENTIFIER_AUTHORITY_URI,
                    source_uri=acquired.pin.source.source_url,
                    observed_at=acquired.pin.retrieved_at,
                    effective_at=None,
                    source_digest=acquired.sha256,
                )
            )
        parsed.append(
            LDACode(
                resource_name=acquired.pin.source.resource_name,
                use=acquired.pin.source.use,
                publisher_label=label,
                source_url=acquired.pin.source.source_url,
                identifiers=tuple(identifiers),
            )
        )
    code_values = {
        identifier.value
        for entry in parsed
        for identifier in entry.identifiers
        if identifier.kind == ("generalIssueCode" if entry.resource_name == "generalIssueCodes" else "filingTypeCode")
    }
    if len(code_values) != len(parsed):
        raise LDASourceDriftError("LDA constants contain duplicate publisher codes")
    if len({entry.publisher_label for entry in parsed}) != len(parsed):
        raise LDASourceDriftError("LDA constants contain duplicate publisher labels")

    return ParsedLDAResource(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        api_interface_version=acquired.pin.api_interface_version,
        publisher_release=acquired.pin.publisher_release,
        codes=tuple(parsed),
        gaps=LDA_PORTFOLIO_GAPS,
    )


def assemble_lda_control_portfolio(
    resources: Sequence[ParsedLDAResource],
) -> LDAControlPortfolio:
    """Require both distinct resources and retain unsupported-control gaps."""

    by_name = {resource.source.resource_name: resource for resource in resources}
    if len(resources) != 2 or set(by_name) != {"generalIssueCodes", "filingTypes"}:
        raise LDASourceDriftError(
            "LDA control portfolio requires exactly one General Issue Code and one Filing Type resource"
        )
    return LDAControlPortfolio(
        general_issue_codes=by_name["generalIssueCodes"],
        filing_types=by_name["filingTypes"],
        filing_period_values=LDA_FILING_PERIOD_VALUES,
        gaps=LDA_PORTFOLIO_GAPS,
    )


def _assignment(code: LDACode, source_field: str) -> LDAFilingCodeAssignment:
    return LDAFilingCodeAssignment(
        source_field=source_field,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def validate_lobbying_filing_codes(
    filing: Mapping[str, object],
    portfolio: LDAControlPortfolio,
) -> ValidatedLDAFilingCodes:
    """Validate exact source codes retained by a ``lobbying-filing-v1`` record."""

    raw_filing_type = filing.get("filing_type")
    if not isinstance(raw_filing_type, str):
        raise LDAAssignmentError("lobbying filing must carry a string filing_type")
    filing_type = portfolio.filing_types.by_code().get(raw_filing_type)
    if filing_type is None:
        raise LDAAssignmentError(f"unknown LDA filing_type {raw_filing_type!r}")

    raw_period = filing.get("filing_period")
    if raw_period is not None and raw_period not in portfolio.filing_period_values:
        raise LDAAssignmentError(f"unknown LDA filing_period {raw_period!r}")
    filing_period = cast(str | None, raw_period)

    raw_activities = filing.get("lobbying_activities")
    if raw_activities is None:
        raw_activities = []
    if not isinstance(raw_activities, list):
        raise LDAAssignmentError("lobbying_activities must be an array")
    issue_lookup = portfolio.general_issue_codes.by_code()
    issues: list[LDAFilingCodeAssignment] = []
    for ordinal, raw_activity in enumerate(raw_activities, start=1):
        if not isinstance(raw_activity, Mapping):
            raise LDAAssignmentError(f"lobbying activity {ordinal} must be an object")
        raw_code = raw_activity.get("general_issue_code")
        raw_label = raw_activity.get("general_issue_code_display")
        if not isinstance(raw_code, str):
            raise LDAAssignmentError(f"lobbying activity {ordinal} must carry a string general_issue_code")
        source_code = issue_lookup.get(raw_code)
        if source_code is None:
            raise LDAAssignmentError(f"lobbying activity {ordinal} has unknown general_issue_code {raw_code!r}")
        if raw_label is not None and raw_label != source_code.publisher_label:
            raise LDAAssignmentError(
                f"lobbying activity {ordinal} display mismatch for {raw_code}: "
                f"expected {source_code.publisher_label!r}, got {raw_label!r}"
            )
        issues.append(
            _assignment(
                source_code,
                f"lobbying_activities[{ordinal - 1}].general_issue_code",
            )
        )

    return ValidatedLDAFilingCodes(
        filing_type=_assignment(filing_type, "filing_type"),
        filing_period=filing_period,
        general_issues=tuple(issues),
        filing_status=None,
        gaps=LDA_PORTFOLIO_GAPS,
    )

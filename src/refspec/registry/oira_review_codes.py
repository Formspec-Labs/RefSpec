"""Pinned OIRA EO 12866 review and meeting field imports for ``controlledCodeList``.

RegInfo.gov exposes the EO 12866 Advanced Search and EO 12866 Meeting Search
forms as HTML pages. Their Review Status, Stage of Rulemaking, Concluded
Action, and Meeting Type controls are the only closed value sets OIRA
publishes for review and meeting process metadata. None of these values is a
general subject; the catalog directs subjects to the linked rule text or its
source-assigned Federal Register/Unified Agenda topic, never to this process
vocabulary, and there is no subject on the review or meeting event itself.

Both pages embed a per-request session identifier and CSRF token throughout
their markup, so the full page response is not byte-stable across separate
requests even when its length happens to match. RefSpec therefore pins the
exact byte span of each control's markup -- located by a literal,
occurs-exactly-once anchor pair -- rather than the whole page. A pinned span
that no longer occurs exactly once, or whose extracted bytes drift from the
recorded digest, fails acquisition instead of silently reparsing a changed
form.

RegInfo.gov publishes no separate meeting-status code list, and no release
date or revision identifier for any of these four value sets. The two pages
also label the shared six-value Stage of Rulemaking codes differently
("Prerule" on the review search form, "Prerule Stage" on the meeting search
form); this module keeps each page's exact label text rather than merging
them into one canonical label.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

OIRA_PUBLISHER = "Office of Information and Regulatory Affairs (OIRA), Office of Management and Budget"
OIRA_IDENTIFIER_AUTHORITY_URI = "https://www.reginfo.gov/"
OIRA_EO_ADVANCED_SEARCH_URL = "https://www.reginfo.gov/public/do/eoAdvancedSearch?eoStatusCode=CD"
OIRA_EO_MEETING_SEARCH_URL = "https://www.reginfo.gov/public/do/eom12866Search"

FieldName = Literal["reviewStatus", "ruleStage", "concludedAction", "meetingStatus"]
ControlType = Literal["radio", "checkbox", "select"]
FieldUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_REVIEW_STATUS_CODE = re.compile(r"^[A-Z]{2}$")
_RULE_STAGE_CODE = re.compile(r"^[1-6]$")
_CONCLUDED_ACTION_CODE = re.compile(r"^[A-Z]{2}$")
_MEETING_STATUS_CODE = re.compile(r"^[A-Z]$")
_CODE_PATTERNS: Mapping[FieldName, re.Pattern[str]] = {
    "reviewStatus": _REVIEW_STATUS_CODE,
    "ruleStage": _RULE_STAGE_CODE,
    "concludedAction": _CONCLUDED_ACTION_CODE,
    "meetingStatus": _MEETING_STATUS_CODE,
}
_LABELED_OPTION = re.compile(
    r'<label\b[^>]*>\s*<input\b(?P<attrs>[^>]*)/>'
    r'(?:<input\s+type="hidden"[^>]*/>)?'
    r"(?P<label>[^<]*)</label>",
    re.DOTALL,
)
_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')
_SELECT_OPTION = re.compile(r'<option\s+value="(?P<value>[^"]*)"[^>]*>(?P<label>[^<]*)</option>')


class OIRAResourceError(ValueError):
    """Base class for OIRA controlled-field failures."""


class OIRAAcquisitionError(OIRAResourceError):
    """Exact official field markup could not be acquired safely."""


class OIRASourceDriftError(OIRAResourceError):
    """An OIRA source no longer matches the reviewed structure or pin."""


class OIRAAssignmentError(OIRAResourceError):
    """A review or meeting record carries an unknown or inconsistent code."""


@dataclass(frozen=True, slots=True)
class OIRAFieldSource:
    """The exact anchor pair that locates one official control's markup."""

    field_name: FieldName
    control_type: ControlType
    html_field_name: str
    page_url: str
    begin_marker: bytes
    end_marker: bytes
    expected_count: int
    excluded_placeholder_count: int = 0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.page_url)
        if parsed.scheme != "https" or parsed.hostname != "www.reginfo.gov":
            raise OIRAAcquisitionError("page_url must be an official HTTPS www.reginfo.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise OIRAAcquisitionError("page_url must not contain credentials")
        if not self.begin_marker or not self.end_marker:
            raise OIRAAcquisitionError("begin_marker and end_marker must not be empty")
        if self.expected_count <= 0:
            raise OIRAAcquisitionError("expected_count must be positive")
        if self.excluded_placeholder_count < 0:
            raise OIRAAcquisitionError("excluded_placeholder_count must not be negative")

    @property
    def source_id(self) -> str:
        """A stable, page-scoped locator for this control's captured fragment."""

        return f"{self.page_url}#{self.html_field_name}"


OIRA_REVIEW_STATUS = OIRAFieldSource(
    field_name="reviewStatus",
    control_type="radio",
    html_field_name="eoStatusCode",
    page_url=OIRA_EO_ADVANCED_SEARCH_URL,
    begin_marker=b'<label style="font-weight:100"><input id="eoStatusCode1"',
    end_marker=b"Concluded</label>",
    expected_count=2,
)
OIRA_RULE_STAGE = OIRAFieldSource(
    field_name="ruleStage",
    control_type="checkbox",
    html_field_name="ruleStages",
    page_url=OIRA_EO_ADVANCED_SEARCH_URL,
    begin_marker=b'<label for="ruleStagePrerule"',
    end_marker=b"Notice</label>",
    expected_count=6,
)
OIRA_CONCLUDED_ACTION = OIRAFieldSource(
    field_name="concludedAction",
    control_type="select",
    html_field_name="concludedActionCode",
    page_url=OIRA_EO_ADVANCED_SEARCH_URL,
    begin_marker=b'<select id="concludedActionCode" name="concludedActionCode">',
    end_marker=b"</select>",
    expected_count=9,
    excluded_placeholder_count=1,
)
OIRA_MEETING_STATUS = OIRAFieldSource(
    field_name="meetingStatus",
    control_type="select",
    html_field_name="meetingType",
    page_url=OIRA_EO_MEETING_SEARCH_URL,
    begin_marker=b'<select name="meetingType" style="min-width: 100px;" id="meetingType">',
    end_marker=b"</select>",
    expected_count=3,
    excluded_placeholder_count=1,
)
OIRA_FIELD_SOURCES = (OIRA_REVIEW_STATUS, OIRA_RULE_STAGE, OIRA_CONCLUDED_ACTION, OIRA_MEETING_STATUS)


@dataclass(frozen=True, slots=True)
class OIRAFieldSnapshotPin:
    """Exact identity of one official control's captured markup span."""

    field: OIRAFieldSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise OIRAAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise OIRAAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise OIRAAcquisitionError("retrieved_at must not be empty")


# Real span digests captured 2026-08-03 from the live pages. RegInfo.gov
# publishes no release date or revision identifier for these forms; retrieval
# time and the exact span digest are the available revision pin.
OIRA_REVIEW_STATUS_2026_08_03 = OIRAFieldSnapshotPin(
    field=OIRA_REVIEW_STATUS,
    retrieved_at="2026-08-03T19:13:02Z",
    expected_sha256="sha256:bc92190b16d9855c05700592bd957491089434bed031aff369103add47af4f76",
    expected_byte_length=405,
)
OIRA_RULE_STAGE_2026_08_03 = OIRAFieldSnapshotPin(
    field=OIRA_RULE_STAGE,
    retrieved_at="2026-08-03T19:13:02Z",
    expected_sha256="sha256:90ccba72caf4a3b98654937fd9a5297c0413b803b9e513c85b1851daf7fbb15a",
    expected_byte_length=1_390,
)
OIRA_CONCLUDED_ACTION_2026_08_03 = OIRAFieldSnapshotPin(
    field=OIRA_CONCLUDED_ACTION,
    retrieved_at="2026-08-03T19:13:02Z",
    expected_sha256="sha256:a402dfde370f0b506dc5262b6002a41983e28f1ac7a4338c1ed048ee49cadbef",
    expected_byte_length=570,
)
OIRA_MEETING_STATUS_2026_08_03 = OIRAFieldSnapshotPin(
    field=OIRA_MEETING_STATUS,
    retrieved_at="2026-08-03T19:13:02Z",
    expected_sha256="sha256:9bec2066ff2c01731b201765cad4a175a0b34230c30dfc854655341040cc9aea",
    expected_byte_length=379,
)
OIRA_FIELD_PINS_2026_08_03 = (
    OIRA_REVIEW_STATUS_2026_08_03,
    OIRA_RULE_STAGE_2026_08_03,
    OIRA_CONCLUDED_ACTION_2026_08_03,
    OIRA_MEETING_STATUS_2026_08_03,
)

OIRA_PORTFOLIO_GAPS = (
    (
        "RegInfo.gov publishes no release date, revision identifier, or standalone "
        "code-list export for these four fields; retrieval time and the exact "
        "captured-span digest are the available revision pin."
    ),
    (
        "The EO Advanced Search and EO 12866 Meeting Search forms label the same "
        "six Stage of Rulemaking codes differently (\"Prerule\" vs \"Prerule Stage\"); "
        "this module preserves each page's exact label text rather than merging them."
    ),
    (
        "No subject exists on the review or meeting event itself; obtain subjects "
        "from the linked rule text or its source-assigned Federal Register/Unified "
        "Agenda topic."
    ),
)


@dataclass(frozen=True, slots=True)
class FetchedOIRAResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class OIRAFetcher(Protocol):
    """Small transport boundary for the official RegInfo.gov search pages."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedOIRAResponse:
        """Fetch one page response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredOIRAField:
    """One verified control-markup span in the content-addressed store."""

    pin: OIRAFieldSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    page_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class OIRAValue:
    """One exact publisher label plus its identifier for a single control value."""

    field_name: FieldName
    use: FieldUse
    publisher_label: str
    page_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedOIRAField:
    """A parsed, digest-pinned OIRA control value set."""

    field: OIRAFieldSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    values: tuple[OIRAValue, ...]
    gaps: tuple[str, ...]

    def by_code(self) -> dict[str, OIRAValue]:
        """Index the control's publisher code while retaining its full identifier."""

        identifier_kind = f"{self.field.field_name}Code"
        result: dict[str, OIRAValue] = {}
        for entry in self.values:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == identifier_kind]
            if len(matches) != 1:
                raise OIRASourceDriftError(f"{self.field.field_name} value must retain exactly one {identifier_kind}")
            result[matches[0].value] = entry
        return result


@dataclass(frozen=True, slots=True)
class OIRAControlPortfolio:
    """The four imported controls plus their known publishing gaps."""

    review_status: ParsedOIRAField
    rule_stage: ParsedOIRAField
    concluded_action: ParsedOIRAField
    meeting_status: ParsedOIRAField
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OIRAFieldAssignment:
    """A control value validated against the exact source snapshot."""

    source_field: str
    publisher_label: str
    use: FieldUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedOIRARecordCodes:
    """Code evidence retained from one EO 12866 review or meeting record."""

    review_status: OIRAFieldAssignment
    rule_stages: tuple[OIRAFieldAssignment, ...]
    concluded_action: OIRAFieldAssignment | None
    meeting_status: OIRAFieldAssignment | None
    gaps: tuple[str, ...]


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _extract_field_fragment(full_page: bytes, field: OIRAFieldSource) -> bytes:
    """Locate one control's markup by an anchor pair that must occur exactly once."""

    starts = [match.start() for match in re.finditer(re.escape(field.begin_marker), full_page)]
    if len(starts) != 1:
        raise OIRASourceDriftError(
            f"{field.field_name} begin marker occurs {len(starts)} times in the source page; expected exactly one"
        )
    end_index = full_page.find(field.end_marker, starts[0])
    if end_index == -1:
        raise OIRASourceDriftError(f"{field.field_name} end marker was not found after its begin marker")
    return full_page[starts[0] : end_index + len(field.end_marker)]


def _verify_payload(payload: bytes, pin: OIRAFieldSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise OIRASourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise OIRASourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.reginfo.gov":
        raise OIRAAcquisitionError("fetcher resolved_url must remain on official HTTPS www.reginfo.gov")
    if parsed.username is not None or parsed.password is not None:
        raise OIRAAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_existing(path: Path, pin: OIRAFieldSnapshotPin) -> AcquiredOIRAField:
    if path.is_symlink() or not path.is_file():
        raise OIRAAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached OIRA field span",
    )
    return AcquiredOIRAField(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        page_url=pin.field.page_url,
        resolved_url=None,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: OIRAFieldSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredOIRAField:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} OIRA field span",
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
        return AcquiredOIRAField(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            page_url=pin.field.page_url,
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


def acquire_oira_field(
    pin: OIRAFieldSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: OIRAFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredOIRAField:
    """Acquire one control's exact markup span through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise OIRAAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise OIRAAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / f"{pin.field.field_name}.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise OIRAAcquisitionError(f"local OIRA source is not a regular file: {local_path}")
        fragment = _extract_field_fragment(local_path.read_bytes(), pin.field)
        return _publish_payload(
            fragment,
            pin,
            final_path,
            content_type="text/html",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise OIRAAcquisitionError("OIRA field is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.field.page_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise OIRAAcquisitionError(f"could not acquire {pin.field.page_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "text/html":
        raise OIRASourceDriftError(f"OIRA page content type drifted to {fetched.content_type!r}")
    fragment = _extract_field_fragment(fetched.body, pin.field)
    return _publish_payload(
        fragment,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _parse_labeled_options(fragment: str, html_field_name: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for match in _LABELED_OPTION.finditer(fragment):
        attrs = dict(_ATTR.findall(match.group("attrs")))
        if attrs.get("name") != html_field_name:
            continue
        if "value" not in attrs:
            raise OIRASourceDriftError(f"{html_field_name} option markup is missing a value attribute")
        result.append((attrs["value"], match.group("label").strip()))
    return result


def _parse_select_options(fragment: str) -> list[tuple[str, str]]:
    return [(match.group("value"), match.group("label").strip()) for match in _SELECT_OPTION.finditer(fragment)]


def parse_oira_field(acquired: AcquiredOIRAField) -> ParsedOIRAField:
    """Parse exact value/label pairs from a pinned span without minting concepts."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed OIRA field span")
    try:
        fragment_text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OIRASourceDriftError("OIRA field span is not valid UTF-8") from error

    field = acquired.pin.field
    if field.control_type in ("radio", "checkbox"):
        raw_pairs = _parse_labeled_options(fragment_text, field.html_field_name)
    else:
        raw_pairs = _parse_select_options(fragment_text)

    placeholders = [pair for pair in raw_pairs if pair[0] == ""]
    real_pairs = [pair for pair in raw_pairs if pair[0] != ""]
    if len(placeholders) != field.excluded_placeholder_count:
        raise OIRASourceDriftError(
            f"{field.field_name} placeholder-option count drift: expected "
            f"{field.excluded_placeholder_count}, parsed {len(placeholders)}"
        )
    if len(real_pairs) != field.expected_count:
        raise OIRASourceDriftError(
            f"{field.field_name} count drift: expected {field.expected_count}, parsed {len(real_pairs)}"
        )

    code_pattern = _CODE_PATTERNS[field.field_name]
    identifier_kind = f"{field.field_name}Code"
    values: list[OIRAValue] = []
    for code, label in real_pairs:
        if code_pattern.fullmatch(code) is None:
            raise OIRASourceDriftError(f"{field.field_name} has a malformed publisher code {code!r}")
        if not label:
            raise OIRASourceDriftError(f"{field.field_name} code {code!r} has an empty publisher label")
        values.append(
            OIRAValue(
                field_name=field.field_name,
                use="deterministicMetadata",
                publisher_label=label,
                page_url=field.page_url,
                identifiers=(
                    ControlledIdentifier(
                        value=code,
                        kind=identifier_kind,
                        authority_uri=OIRA_IDENTIFIER_AUTHORITY_URI,
                        source_uri=field.source_id,
                        observed_at=acquired.pin.retrieved_at,
                        effective_at=None,
                        source_digest=acquired.sha256,
                    ),
                ),
            )
        )
    if len({value.identifiers[0].value for value in values}) != len(values):
        raise OIRASourceDriftError(f"{field.field_name} contains duplicate publisher codes")
    if len({value.publisher_label for value in values}) != len(values):
        raise OIRASourceDriftError(f"{field.field_name} contains duplicate publisher labels")

    return ParsedOIRAField(
        field=field,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        values=tuple(values),
        gaps=OIRA_PORTFOLIO_GAPS,
    )


def assemble_oira_control_portfolio(
    fields: Sequence[ParsedOIRAField],
) -> OIRAControlPortfolio:
    """Require all four known fields and retain their publishing gaps."""

    by_name = {parsed.field.field_name: parsed for parsed in fields}
    expected_names = {"reviewStatus", "ruleStage", "concludedAction", "meetingStatus"}
    if len(fields) != 4 or set(by_name) != expected_names:
        raise OIRASourceDriftError(
            "OIRA control portfolio requires exactly the four known review and meeting fields"
        )
    return OIRAControlPortfolio(
        review_status=by_name["reviewStatus"],
        rule_stage=by_name["ruleStage"],
        concluded_action=by_name["concludedAction"],
        meeting_status=by_name["meetingStatus"],
        gaps=OIRA_PORTFOLIO_GAPS,
    )


def _assignment(value: OIRAValue, source_field: str) -> OIRAFieldAssignment:
    return OIRAFieldAssignment(
        source_field=source_field,
        publisher_label=value.publisher_label,
        use=value.use,
        identifiers=value.identifiers,
        is_general_subject_concept=value.is_general_subject_concept,
    )


def validate_oira_record_codes(
    record: Mapping[str, object],
    portfolio: OIRAControlPortfolio,
) -> ValidatedOIRARecordCodes:
    """Validate exact source codes retained by one EO 12866 review or meeting record."""

    raw_status = record.get("review_status")
    if not isinstance(raw_status, str):
        raise OIRAAssignmentError("OIRA review record must carry a string review_status")
    review_status = portfolio.review_status.by_code().get(raw_status)
    if review_status is None:
        raise OIRAAssignmentError(f"unknown OIRA review_status {raw_status!r}")

    raw_stages = record.get("rule_stages")
    if raw_stages is None:
        raw_stages = []
    if not isinstance(raw_stages, list):
        raise OIRAAssignmentError("rule_stages must be an array")
    stage_lookup = portfolio.rule_stage.by_code()
    stages: list[OIRAFieldAssignment] = []
    for ordinal, raw_stage in enumerate(raw_stages, start=1):
        if not isinstance(raw_stage, str):
            raise OIRAAssignmentError(f"rule_stages[{ordinal - 1}] must be a string")
        stage_value = stage_lookup.get(raw_stage)
        if stage_value is None:
            raise OIRAAssignmentError(f"unknown OIRA rule_stage {raw_stage!r}")
        stages.append(_assignment(stage_value, f"rule_stages[{ordinal - 1}]"))

    raw_action = record.get("concluded_action")
    concluded_action: OIRAFieldAssignment | None = None
    if raw_action is not None:
        if not isinstance(raw_action, str):
            raise OIRAAssignmentError("concluded_action must be a string when present")
        action_value = portfolio.concluded_action.by_code().get(raw_action)
        if action_value is None:
            raise OIRAAssignmentError(f"unknown OIRA concluded_action {raw_action!r}")
        concluded_action = _assignment(action_value, "concluded_action")

    raw_meeting = record.get("meeting_status")
    meeting_status: OIRAFieldAssignment | None = None
    if raw_meeting is not None:
        if not isinstance(raw_meeting, str):
            raise OIRAAssignmentError("meeting_status must be a string when present")
        meeting_value = portfolio.meeting_status.by_code().get(raw_meeting)
        if meeting_value is None:
            raise OIRAAssignmentError(f"unknown OIRA meeting_status {raw_meeting!r}")
        meeting_status = _assignment(meeting_value, "meeting_status")

    return ValidatedOIRARecordCodes(
        review_status=_assignment(review_status, "review_status"),
        rule_stages=tuple(stages),
        concluded_action=concluded_action,
        meeting_status=meeting_status,
        gaps=OIRA_PORTFOLIO_GAPS,
    )


OIRA_REVIEW_AND_MEETING_CODES_RESOURCE_ID = "oira-eo-12866-review-and-meeting-codes-2026-08-03"
OIRA_REVIEW_AND_MEETING_CODES_TITLE = "OIRA EO 12866 review and meeting field values, captured 2026-08-03"


def _identifier_payload(*, identifier: ControlledIdentifier, source_path: str) -> dict[str, Any]:
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": source_path,
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _observation_id(
    *,
    resource_id: str,
    source_artifact: str,
    source_path: str,
    identifiers: Sequence[Mapping[str, Any]],
) -> str:
    identity = {
        "resourceId": resource_id,
        "sourceArtifact": source_artifact,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]}
            for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{resource_id}:{digest}"


def _field_observations(resource_id: str, parsed: ParsedOIRAField) -> list[dict[str, Any]]:
    source_artifact = parsed.field.source_id
    result: list[dict[str, Any]] = []
    for ordinal, value in enumerate(parsed.values):
        source_path = f"$[{ordinal}]"
        identifiers = [
            _identifier_payload(identifier=identifier, source_path=source_path) for identifier in value.identifiers
        ]
        result.append(
            {
                "id": _observation_id(
                    resource_id=resource_id,
                    source_artifact=source_artifact,
                    source_path=source_path,
                    identifiers=identifiers,
                ),
                "sourceArtifact": source_artifact,
                "sourcePath": source_path,
                # This ordinal is a source locator only; publisher identity is
                # preserved in identifiers and never derived from control order.
                "sourceOrdinal": ordinal,
                "labels": [
                    {
                        "value": value.publisher_label,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": identifiers,
                "eligibleUses": ["deterministicMetadata"],
                "conceptIdentityClaimed": False,
            }
        )
    return result


def build_oira_review_and_meeting_package(
    review_status: AcquiredOIRAField,
    rule_stage: AcquiredOIRAField,
    concluded_action: AcquiredOIRAField,
    meeting_status: AcquiredOIRAField,
) -> SourceControlledResourceBundle:
    """Package the four pinned OIRA fields as one closed, development-only resource."""

    acquired_fields = (review_status, rule_stage, concluded_action, meeting_status)
    portfolio = assemble_oira_control_portfolio(tuple(parse_oira_field(acquired) for acquired in acquired_fields))
    parsed_by_field_name = {
        portfolio.review_status.field.field_name: portfolio.review_status,
        portfolio.rule_stage.field.field_name: portfolio.rule_stage,
        portfolio.concluded_action.field.field_name: portfolio.concluded_action,
        portfolio.meeting_status.field.field_name: portfolio.meeting_status,
    }

    observations: list[Mapping[str, Any]] = []
    source_artifacts: dict[str, bytes] = {}
    excluded = 0
    for acquired in acquired_fields:
        parsed = parsed_by_field_name[acquired.pin.field.field_name]
        observations.extend(_field_observations(OIRA_REVIEW_AND_MEETING_CODES_RESOURCE_ID, parsed))
        source_artifacts[parsed.field.source_id] = acquired.path.read_bytes()
        excluded += parsed.field.excluded_placeholder_count

    return build_source_controlled_resource_bundle(
        resource_id=OIRA_REVIEW_AND_MEETING_CODES_RESOURCE_ID,
        title=OIRA_REVIEW_AND_MEETING_CODES_TITLE,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=review_status.pin.retrieved_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts=source_artifacts,
        source_observed_count=len(observations) + excluded,
        excluded_count=excluded,
        gaps=tuple({"kind": "processMetadataOnly", "reason": gap} for gap in OIRA_PORTFOLIO_GAPS),
    )


__all__ = [
    "OIRA_CONCLUDED_ACTION",
    "OIRA_CONCLUDED_ACTION_2026_08_03",
    "OIRA_EO_ADVANCED_SEARCH_URL",
    "OIRA_EO_MEETING_SEARCH_URL",
    "OIRA_FIELD_PINS_2026_08_03",
    "OIRA_FIELD_SOURCES",
    "OIRA_IDENTIFIER_AUTHORITY_URI",
    "OIRA_MEETING_STATUS",
    "OIRA_MEETING_STATUS_2026_08_03",
    "OIRA_PORTFOLIO_GAPS",
    "OIRA_PUBLISHER",
    "OIRA_REVIEW_AND_MEETING_CODES_RESOURCE_ID",
    "OIRA_REVIEW_AND_MEETING_CODES_TITLE",
    "OIRA_REVIEW_STATUS",
    "OIRA_REVIEW_STATUS_2026_08_03",
    "OIRA_RULE_STAGE",
    "OIRA_RULE_STAGE_2026_08_03",
    "AcquiredOIRAField",
    "FetchedOIRAResponse",
    "OIRAAcquisitionError",
    "OIRAAssignmentError",
    "OIRAControlPortfolio",
    "OIRAFetcher",
    "OIRAFieldAssignment",
    "OIRAFieldSnapshotPin",
    "OIRAFieldSource",
    "OIRAResourceError",
    "OIRASourceDriftError",
    "OIRAValue",
    "ParsedOIRAField",
    "ValidatedOIRARecordCodes",
    "acquire_oira_field",
    "assemble_oira_control_portfolio",
    "build_oira_review_and_meeting_package",
    "parse_oira_field",
    "sha256_digest",
    "validate_oira_record_codes",
]

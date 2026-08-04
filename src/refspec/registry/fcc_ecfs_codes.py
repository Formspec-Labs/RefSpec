"""Pinned FCC ECFS filing-record code capture for controlled code lists.

The FCC ECFS public API (https://www.fcc.gov/ecfs/help/public_api) publishes
live filing search and proceeding endpoints. It publishes no dedicated
code-list or constants endpoint comparable to the LDA constants API: filing
types, access statuses, and bureaus appear only as fields embedded on filing
search records, and proceeding identity appears the same way. The catalog
decision for this source is explicit: proceeding, bureau, filing-type, and
access-status values remain deterministic source metadata, and no FCC subject
thesaurus exists.

This module therefore captures one exact, digest-pinned filing search
response and derives four controlled code lists from the values that
response actually observed:

* Filing Types (``submissiontype``) -- publisher id plus a 2-3 letter code.
* Access Statuses (``viewingstatus``) -- publisher id plus a display label.
* Bureaus -- the ``bureau_code``/``bureau_name`` pairs embedded on each
  filing's proceedings.
* Proceedings -- the docket number, description, and bureau assignment
  embedded on each filing's proceedings.

None of these is a general subject concept merely because it has a readable
label, and none of them is claimed to be an exhaustive enumeration: this
capture reports exactly what one snapshot observed, not a publisher-asserted
complete list. Every packaged value keeps the identifier the publisher itself
supplied (a numeric id or a bureau/docket code); this module never mints a
concept identifier of its own.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and no scraping provider is
required for the current JSON endpoint.
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
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

FCC_ECFS_PUBLISHER = "Federal Communications Commission"
FCC_ECFS_IDENTIFIER_AUTHORITY_URI = "https://www.fcc.gov/ecfs/"
FCC_ECFS_HELP_URL = "https://www.fcc.gov/ecfs/help/public_api"
FCC_ECFS_API_HOST = "publicapi.fcc.gov"
FCC_ECFS_CONTROLLED_LIST_PACKAGE_VERSION = "fcc-ecfs-controlled-list-package-v1"

ResourceName = Literal["filingTypes", "accessStatuses", "bureaus", "proceedings"]
ResourceUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")

# The exact key set the /ecfs/filings response envelope and one filing record
# exhibited in the snapshot this module was built against. A publisher field
# addition or removal is real drift, not something this parser silently
# tolerates.
_ENVELOPE_FIELDS = frozenset({"filing", "aggregations"})
# Fields present on every filing record regardless of express_comment.
_FILING_RECORD_REQUIRED_FIELDS = frozenset(
    {
        "_index",
        "attachments",
        "authors",
        "bureaus",
        "created",
        "date_disseminated",
        "date_last_modified",
        "date_received",
        "date_submission",
        "documents",
        "exparte_or_late_filed",
        "express_comment",
        "filers",
        "filingstatus",
        "id_submission",
        "lawfirms",
        "proceedings",
        "submissiontype",
        "total_page_count",
        "viewingstatus",
    }
)
# A regular filing (express_comment == 0) additionally carries these fields.
_FILING_RECORD_STANDARD_ONLY_FIELDS = frozenset({"entity", "file_number", "id_bureau", "presented_to", "report_number"})
# An express-comment filing (express_comment == 1) carries this field instead.
_FILING_RECORD_EXPRESS_ONLY_FIELDS = frozenset({"text_data"})
_FILING_RECORD_ALLOWED_FIELDS = (
    _FILING_RECORD_REQUIRED_FIELDS | _FILING_RECORD_STANDARD_ONLY_FIELDS | _FILING_RECORD_EXPRESS_ONLY_FIELDS
)
_SUBMISSION_TYPE_REQUIRED_FIELDS = frozenset({"id", "description"})
# Regular filings carry "abbreviation"; express-comment filings carry "type"
# with the identical short code plus a "flag_public" marker instead. Both are
# observed, real API shapes, not a hypothetical the parser guards against.
_SUBMISSION_TYPE_ALLOWED_FIELDS = frozenset({"id", "description", "short", "abbreviation", "type", "flag_public"})
_VIEWING_STATUS_FIELDS = frozenset({"id", "description"})
_PROCEEDING_FIELDS = frozenset(
    {
        "sunshine_start_date",
        "date_closed",
        "id_proceeding",
        "name",
        "bureau_code",
        "description",
        "created_date",
        "description_display",
        "sunshine_end_date",
        "bureau_name",
    }
)
_PRIMARY_IDENTIFIER_KIND: Mapping[ResourceName, str] = MappingProxyType(
    {
        "filingTypes": "filingTypeAbbreviation",
        "accessStatuses": "accessStatusId",
        "bureaus": "bureauCode",
        "proceedings": "proceedingNumber",
    }
)


class FCCECFSResourceError(ValueError):
    """Base class for FCC ECFS controlled-code failures."""


class FCCECFSAcquisitionError(FCCECFSResourceError):
    """Exact official source bytes could not be acquired safely."""


class FCCECFSSourceDriftError(FCCECFSResourceError):
    """A captured FCC ECFS response no longer matches the reviewed shape."""


class FCCECFSPackageError(FCCECFSResourceError):
    """A packaged FCC ECFS resource differs from its declared spec or pin."""


@dataclass(frozen=True, slots=True)
class FCCECFSCaptureSource:
    """One official FCC ECFS live endpoint whose response this module captures."""

    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != FCC_ECFS_API_HOST:
            raise FCCECFSAcquisitionError("source_url must be an official HTTPS publicapi.fcc.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise FCCECFSAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FCCECFSAcquisitionError("filename must be one plain path component")


# limit/sort are part of what this endpoint returns and stay in the pinned
# URL; an api_key is an auth credential the injected fetcher supplies at
# request time, never part of the captured resource's identity.
FCC_ECFS_FILINGS_SNAPSHOT = FCCECFSCaptureSource(
    source_url=f"https://{FCC_ECFS_API_HOST}/ecfs/filings?limit=25&sort=date_disseminated,DESC",
    filename="fcc-ecfs-filings-snapshot.json",
)


@dataclass(frozen=True, slots=True)
class FCCECFSSnapshotPin:
    """Exact identity of one official filing search response."""

    source: FCCECFSCaptureSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_filing_count: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise FCCECFSAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise FCCECFSAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise FCCECFSAcquisitionError("retrieved_at must not be empty")
        if self.expected_filing_count <= 0:
            raise FCCECFSAcquisitionError("expected_filing_count must be positive")


# Captured 2026-08-03 via a documented `limit`/`sort` query against the live
# public filings search. ECFS is a live corpus with no code-list release, so
# this pin identifies one observed snapshot, not a publisher-versioned
# release the way an LDA constants response does.
FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03 = FCCECFSSnapshotPin(
    source=FCC_ECFS_FILINGS_SNAPSHOT,
    retrieved_at="2026-08-03T19:20:00Z",
    expected_sha256="sha256:4393e9c73ab5e12e25c79a707ca85856ba1d9cc1c3eccdfdfa235223f17773da",
    expected_byte_length=51_284,
    expected_filing_count=25,
)


@dataclass(frozen=True, slots=True)
class FetchedFCCECFSResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class FCCECFSFetcher(Protocol):
    """Small transport boundary for the official ECFS filings endpoint."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedFCCECFSResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredFCCECFSSnapshot:
    """One verified source object in the content-addressed store."""

    pin: FCCECFSSnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != FCC_ECFS_API_HOST:
        raise FCCECFSAcquisitionError("fetcher resolved_url must remain on official HTTPS publicapi.fcc.gov")
    if parsed.username is not None or parsed.password is not None:
        raise FCCECFSAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: FCCECFSSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise FCCECFSSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise FCCECFSSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FCCECFSSourceDriftError(f"{location} is not valid JSON") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: FCCECFSSnapshotPin) -> AcquiredFCCECFSSnapshot:
    if path.is_symlink() or not path.is_file():
        raise FCCECFSAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached FCC ECFS source",
    )
    return AcquiredFCCECFSSnapshot(
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
    pin: FCCECFSSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredFCCECFSSnapshot:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} FCC ECFS source",
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
        return AcquiredFCCECFSSnapshot(
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


def acquire_fcc_ecfs_snapshot(
    pin: FCCECFSSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: FCCECFSFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredFCCECFSSnapshot:
    """Acquire one exact filings response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise FCCECFSAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise FCCECFSAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise FCCECFSAcquisitionError(f"local FCC ECFS source is not a regular file: {local_path}")
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
        raise FCCECFSAcquisitionError("FCC ECFS snapshot is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise FCCECFSAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type != "application/json":
        raise FCCECFSSourceDriftError(f"FCC ECFS response content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


@dataclass(frozen=True, slots=True)
class FCCCode:
    """One exact publisher-observed code plus every field this module retains."""

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    source_url: str
    source_path: str
    source_ordinal: int
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedFCCECFSSnapshot:
    """A parsed, digest-pinned FCC ECFS filing search snapshot."""

    source: FCCECFSCaptureSource
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    filing_count: int
    filing_types: tuple[FCCCode, ...]
    access_statuses: tuple[FCCCode, ...]
    bureaus: tuple[FCCCode, ...]
    proceedings: tuple[FCCCode, ...]
    raw_occurrence_counts: Mapping[ResourceName, int]
    gaps: tuple[str, ...]

    def by_primary_code(self, resource_name: ResourceName) -> dict[str, FCCCode]:
        """Index one resource's publisher-observed primary code."""

        codes = {
            "filingTypes": self.filing_types,
            "accessStatuses": self.access_statuses,
            "bureaus": self.bureaus,
            "proceedings": self.proceedings,
        }[resource_name]
        kind = _PRIMARY_IDENTIFIER_KIND[resource_name]
        result: dict[str, FCCCode] = {}
        for entry in codes:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == kind]
            if len(matches) != 1:
                raise FCCECFSSourceDriftError(f"{resource_name} row must retain exactly one {kind}")
            result[matches[0].value] = entry
        return result


FCC_ECFS_SNAPSHOT_GAPS = (
    (
        "The public API help page documents live filing search and proceeding endpoints, not a "
        "dedicated code-list or constants endpoint; filing-type, access-status, bureau, and "
        "proceeding values are read from fields embedded on captured filing records."
    ),
    (
        "This snapshot's distinct values are exactly what one capture observed, not a "
        "publisher-asserted complete enumeration; a different or larger capture could observe "
        "additional filing types, access statuses, bureaus, or proceedings."
    ),
    (
        "No FCC subject thesaurus was found; filing-type, access-status, bureau, and proceeding "
        "values remain deterministic source metadata and are never treated as general subject "
        "concepts."
    ),
)


def _identifier(
    value: str,
    kind: str,
    *,
    pin: FCCECFSSnapshotPin,
    acquired_sha256: str,
) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=FCC_ECFS_IDENTIFIER_AUTHORITY_URI,
        source_uri=pin.source.source_url,
        observed_at=pin.retrieved_at,
        effective_at=None,
        source_digest=acquired_sha256,
    )


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise FCCECFSSourceDriftError(f"{label} must be a positive integer")
    return value


def _require_nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FCCECFSSourceDriftError(f"{label} must be non-empty text")
    return value


def _parse_submission_type(value: object, *, context: str) -> tuple[str, str, str]:
    if not isinstance(value, Mapping):
        raise FCCECFSSourceDriftError(f"{context}.submissiontype must be an object")
    if not _SUBMISSION_TYPE_REQUIRED_FIELDS.issubset(value) or not set(value).issubset(
        _SUBMISSION_TYPE_ALLOWED_FIELDS
    ):
        raise FCCECFSSourceDriftError(f"{context}.submissiontype fields drifted: {sorted(value)}")
    type_id = _require_positive_int(value["id"], f"{context}.submissiontype.id")
    description = _require_nonempty_text(value["description"], f"{context}.submissiontype.description")
    abbreviation = value.get("abbreviation")
    type_alias = value.get("type")
    if abbreviation is None and type_alias is None:
        raise FCCECFSSourceDriftError(f"{context}.submissiontype must supply abbreviation or type")
    if abbreviation is not None and type_alias is not None and abbreviation != type_alias:
        raise FCCECFSSourceDriftError(
            f"{context}.submissiontype abbreviation/type disagree: {abbreviation!r} vs {type_alias!r}"
        )
    code = abbreviation if abbreviation is not None else type_alias
    code = _require_nonempty_text(code, f"{context}.submissiontype.abbreviation")
    short = value.get("short")
    if short is not None:
        _require_nonempty_text(short, f"{context}.submissiontype.short")
    flag_public = value.get("flag_public")
    if flag_public is not None and flag_public not in ("Y", "N"):
        raise FCCECFSSourceDriftError(f"{context}.submissiontype.flag_public must be Y or N")
    return code, description, str(type_id)


def _parse_viewing_status(value: object, *, context: str) -> tuple[str, str]:
    if not isinstance(value, Mapping) or set(value) != _VIEWING_STATUS_FIELDS:
        raise FCCECFSSourceDriftError(
            f"{context}.viewingstatus fields drifted: "
            f"{sorted(value) if isinstance(value, Mapping) else type(value).__name__}"
        )
    status_id = _require_positive_int(value["id"], f"{context}.viewingstatus.id")
    description = _require_nonempty_text(value["description"], f"{context}.viewingstatus.description")
    return str(status_id), description


def _parse_proceeding(value: object, *, context: str) -> tuple[str, str, str, str, str]:
    if not isinstance(value, Mapping) or set(value) != _PROCEEDING_FIELDS:
        raise FCCECFSSourceDriftError(
            f"{context} fields drifted: {sorted(value) if isinstance(value, Mapping) else type(value).__name__}"
        )
    id_proceeding = _require_positive_int(value["id_proceeding"], f"{context}.id_proceeding")
    name = _require_nonempty_text(value["name"], f"{context}.name")
    description = _require_nonempty_text(value["description"], f"{context}.description")
    bureau_code = _require_nonempty_text(value["bureau_code"], f"{context}.bureau_code")
    bureau_name = _require_nonempty_text(value["bureau_name"], f"{context}.bureau_name")
    _require_nonempty_text(value["description_display"], f"{context}.description_display")
    for date_field in ("sunshine_start_date", "date_closed", "created_date", "sunshine_end_date"):
        raw_date = value[date_field]
        if raw_date is not None and not isinstance(raw_date, str):
            raise FCCECFSSourceDriftError(f"{context}.{date_field} must be text or null")
    return str(id_proceeding), name, description, bureau_code, bureau_name


def _parse_filing_record(record: object, ordinal: int) -> tuple[str, object, object, list[object]]:
    if (
        not isinstance(record, Mapping)
        or not _FILING_RECORD_REQUIRED_FIELDS.issubset(record)
        or not set(record).issubset(_FILING_RECORD_ALLOWED_FIELDS)
    ):
        raise FCCECFSSourceDriftError(
            f"filing[{ordinal}] fields drifted: "
            f"{sorted(record) if isinstance(record, Mapping) else type(record).__name__}"
        )
    express_comment = record["express_comment"]
    if express_comment not in (0, 1):
        raise FCCECFSSourceDriftError(f"filing[{ordinal}].express_comment must be 0 or 1")
    extra_fields = set(record) - _FILING_RECORD_REQUIRED_FIELDS
    expected_extra = _FILING_RECORD_STANDARD_ONLY_FIELDS if express_comment == 0 else _FILING_RECORD_EXPRESS_ONLY_FIELDS
    if extra_fields != expected_extra:
        raise FCCECFSSourceDriftError(f"filing[{ordinal}] fields drifted for express_comment={express_comment}: {sorted(extra_fields)}")
    id_submission = _require_nonempty_text(record["id_submission"], f"filing[{ordinal}].id_submission")
    proceedings = record["proceedings"]
    if not isinstance(proceedings, list) or not proceedings:
        raise FCCECFSSourceDriftError(f"filing[{ordinal}].proceedings must be a non-empty array")
    return id_submission, record["submissiontype"], record["viewingstatus"], proceedings


def _merge_code(store: dict[str, FCCCode], key: str, code: FCCCode, *, context: str) -> None:
    existing = store.get(key)
    if existing is None:
        store[key] = code
        return
    if existing.publisher_label != code.publisher_label or existing.identifiers != code.identifiers:
        raise FCCECFSSourceDriftError(
            f"{context}: {code.resource_name} {key!r} was observed with a conflicting label or identifier"
        )


def parse_fcc_ecfs_snapshot(acquired: AcquiredFCCECFSSnapshot) -> ParsedFCCECFSSnapshot:
    """Derive four controlled code lists from one exact filing search response."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed FCC ECFS source")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FCCECFSSourceDriftError("FCC ECFS payload is not valid JSON") from error
    if not isinstance(root, Mapping) or set(root) != _ENVELOPE_FIELDS:
        raise FCCECFSSourceDriftError(
            f"FCC ECFS envelope fields drifted: {sorted(root) if isinstance(root, Mapping) else type(root).__name__}"
        )
    if not isinstance(root["aggregations"], Mapping):
        raise FCCECFSSourceDriftError("FCC ECFS aggregations must be an object")
    filing_list = root["filing"]
    if not isinstance(filing_list, list):
        raise FCCECFSSourceDriftError("FCC ECFS filing must be an array")
    if len(filing_list) != acquired.pin.expected_filing_count:
        raise FCCECFSSourceDriftError(
            f"filing count drift: expected {acquired.pin.expected_filing_count}, parsed {len(filing_list)}"
        )

    filing_types: dict[str, FCCCode] = {}
    access_statuses: dict[str, FCCCode] = {}
    bureaus: dict[str, FCCCode] = {}
    proceedings: dict[str, FCCCode] = {}
    raw_occurrences: dict[ResourceName, int] = {
        "filingTypes": 0,
        "accessStatuses": 0,
        "bureaus": 0,
        "proceedings": 0,
    }

    for ordinal, record in enumerate(filing_list):
        id_submission, raw_submission_type, raw_viewing_status, raw_proceedings = _parse_filing_record(
            record, ordinal
        )
        context = f"filing[{ordinal}] ({id_submission})"

        abbreviation, description, type_id = _parse_submission_type(raw_submission_type, context=context)
        submission_path = f"$.filing[{ordinal}].submissiontype"
        raw_occurrences["filingTypes"] += 1
        _merge_code(
            filing_types,
            abbreviation,
            FCCCode(
                resource_name="filingTypes",
                use="deterministicMetadata",
                publisher_label=description,
                source_url=acquired.pin.source.source_url,
                source_path=submission_path,
                source_ordinal=ordinal,
                identifiers=(
                    _identifier(
                        abbreviation,
                        "filingTypeAbbreviation",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                    _identifier(
                        type_id,
                        "publisherRecordId",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                ),
            ),
            context=context,
        )

        status_id, status_description = _parse_viewing_status(raw_viewing_status, context=context)
        status_path = f"$.filing[{ordinal}].viewingstatus"
        raw_occurrences["accessStatuses"] += 1
        _merge_code(
            access_statuses,
            status_id,
            FCCCode(
                resource_name="accessStatuses",
                use="deterministicMetadata",
                publisher_label=status_description,
                source_url=acquired.pin.source.source_url,
                source_path=status_path,
                source_ordinal=ordinal,
                identifiers=(
                    _identifier(
                        status_id,
                        "accessStatusId",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                ),
            ),
            context=context,
        )

        for proceeding_ordinal, raw_proceeding in enumerate(raw_proceedings):
            proceeding_context = f"{context}.proceedings[{proceeding_ordinal}]"
            (
                id_proceeding,
                name,
                proceeding_description,
                bureau_code,
                bureau_name,
            ) = _parse_proceeding(raw_proceeding, context=proceeding_context)
            proceeding_path = f"$.filing[{ordinal}].proceedings[{proceeding_ordinal}]"
            source_ordinal = (ordinal * 1000) + proceeding_ordinal

            raw_occurrences["bureaus"] += 1
            _merge_code(
                bureaus,
                bureau_code,
                FCCCode(
                    resource_name="bureaus",
                    use="deterministicMetadata",
                    publisher_label=bureau_name,
                    source_url=acquired.pin.source.source_url,
                    source_path=proceeding_path,
                    source_ordinal=source_ordinal,
                    identifiers=(
                        _identifier(
                            bureau_code,
                            "bureauCode",
                            pin=acquired.pin,
                            acquired_sha256=acquired.sha256,
                        ),
                    ),
                ),
                context=proceeding_context,
            )

            raw_occurrences["proceedings"] += 1
            _merge_code(
                proceedings,
                name,
                FCCCode(
                    resource_name="proceedings",
                    use="deterministicMetadata",
                    publisher_label=proceeding_description,
                    source_url=acquired.pin.source.source_url,
                    source_path=proceeding_path,
                    source_ordinal=source_ordinal,
                    identifiers=(
                        _identifier(
                            name,
                            "proceedingNumber",
                            pin=acquired.pin,
                            acquired_sha256=acquired.sha256,
                        ),
                        _identifier(
                            id_proceeding,
                            "publisherRecordId",
                            pin=acquired.pin,
                            acquired_sha256=acquired.sha256,
                        ),
                        _identifier(
                            bureau_code,
                            "bureauCode",
                            pin=acquired.pin,
                            acquired_sha256=acquired.sha256,
                        ),
                    ),
                ),
                context=proceeding_context,
            )

    return ParsedFCCECFSSnapshot(
        source=acquired.pin.source,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        filing_count=len(filing_list),
        filing_types=tuple(filing_types.values()),
        access_statuses=tuple(access_statuses.values()),
        bureaus=tuple(bureaus.values()),
        proceedings=tuple(proceedings.values()),
        raw_occurrence_counts=MappingProxyType(raw_occurrences),
        gaps=FCC_ECFS_SNAPSHOT_GAPS,
    )


# ---------------------------------------------------------------------------
# Deterministic closed packaging, one SourceControlledResourceBundle per
# controlled code list, all derived from the same pinned snapshot.
# ---------------------------------------------------------------------------

_NO_DEDICATED_CODE_LIST_ENDPOINT_GAP = MappingProxyType(
    {
        "kind": "dedicatedCodeListEndpointUnavailable",
        "reason": (
            "The public API help page documents live filing search and proceeding endpoints, not "
            "a dedicated code-list or constants endpoint; this package's values are read from "
            "fields embedded on captured filing records."
        ),
    }
)
_OBSERVED_SET_NOT_EXHAUSTIVE_GAP = MappingProxyType(
    {
        "kind": "observedSetNotExhaustive",
        "reason": (
            "This package's distinct values are exactly what one capture observed, not a "
            "publisher-asserted complete enumeration."
        ),
    }
)
_KNOWN_GAPS = (_NO_DEDICATED_CODE_LIST_ENDPOINT_GAP, _OBSERVED_SET_NOT_EXHAUSTIVE_GAP)


@dataclass(frozen=True, slots=True)
class FCCECFSCodeListPackageSpec:
    """Pinned identity and use of one FCC ECFS controlled-list package."""

    resource_name: ResourceName
    resource_id: str
    title: str
    pin: FCCECFSSnapshotPin
    uses: tuple[ResourceUse, ...]
    known_gaps: tuple[Mapping[str, str], ...]
    expected_distinct_count: int
    expected_raw_occurrence_count: int
    expected_logical_digest: str

    def __post_init__(self) -> None:
        if not self.resource_id or not self.title:
            raise FCCECFSPackageError("package identity fields must not be empty")
        if not self.uses:
            raise FCCECFSPackageError("package must declare at least one eligible use")
        if self.expected_distinct_count <= 0 or self.expected_raw_occurrence_count <= 0:
            raise FCCECFSPackageError("package expected counts must be positive")
        if _DIGEST.fullmatch(self.expected_logical_digest) is None:
            raise FCCECFSPackageError("expected_logical_digest must be a SHA-256 digest")

    @property
    def primary_identifier_kind(self) -> str:
        return _PRIMARY_IDENTIFIER_KIND[self.resource_name]


FCC_ECFS_FILING_TYPE_PACKAGE = FCCECFSCodeListPackageSpec(
    resource_name="filingTypes",
    resource_id="fcc-ecfs-filing-types-2026-08-03",
    title="FCC ECFS Filing Types, observed 2026-08-03",
    pin=FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03,
    uses=("deterministicMetadata",),
    known_gaps=_KNOWN_GAPS,
    expected_distinct_count=6,
    expected_raw_occurrence_count=25,
    expected_logical_digest="sha256:e50e9040e8444451ea0abaa85ee0782dba1e03e3419c22073de58ed1d3b482c5",
)
FCC_ECFS_ACCESS_STATUS_PACKAGE = FCCECFSCodeListPackageSpec(
    resource_name="accessStatuses",
    resource_id="fcc-ecfs-access-statuses-2026-08-03",
    title="FCC ECFS Access Statuses, observed 2026-08-03",
    pin=FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03,
    uses=("deterministicMetadata",),
    known_gaps=_KNOWN_GAPS,
    expected_distinct_count=1,
    expected_raw_occurrence_count=25,
    expected_logical_digest="sha256:44bcfeb3af62fc7c80cc70aa8c41f6c49cc44db5a0828ceb1fde69858726081a",
)
FCC_ECFS_BUREAU_PACKAGE = FCCECFSCodeListPackageSpec(
    resource_name="bureaus",
    resource_id="fcc-ecfs-bureaus-2026-08-03",
    title="FCC ECFS Bureaus, observed 2026-08-03",
    pin=FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03,
    uses=("deterministicMetadata",),
    known_gaps=_KNOWN_GAPS,
    expected_distinct_count=5,
    expected_raw_occurrence_count=40,
    expected_logical_digest="sha256:ce8bc18192277d008978adeff5fd0cfd207cd0e3c058377027e9cbe91f94d9df",
)
FCC_ECFS_PROCEEDING_PACKAGE = FCCECFSCodeListPackageSpec(
    resource_name="proceedings",
    resource_id="fcc-ecfs-proceedings-2026-08-03",
    title="FCC ECFS Proceedings, observed 2026-08-03",
    pin=FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03,
    uses=("deterministicMetadata",),
    known_gaps=_KNOWN_GAPS,
    expected_distinct_count=15,
    expected_raw_occurrence_count=40,
    expected_logical_digest="sha256:1ddd7f44d51ad220a89b59bcecc164edf2597eb7dbfaa1e694fd2fd3b6b6b2ff",
)
FCC_ECFS_CONTROLLED_LIST_PACKAGES = (
    FCC_ECFS_FILING_TYPE_PACKAGE,
    FCC_ECFS_ACCESS_STATUS_PACKAGE,
    FCC_ECFS_BUREAU_PACKAGE,
    FCC_ECFS_PROCEEDING_PACKAGE,
)
_PACKAGE_BY_RESOURCE_ID = MappingProxyType({spec.resource_id: spec for spec in FCC_ECFS_CONTROLLED_LIST_PACKAGES})


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _parse_exact_source(pin: FCCECFSSnapshotPin, payload: bytes) -> ParsedFCCECFSSnapshot:
    with tempfile.TemporaryDirectory(prefix="refspec-fcc-ecfs-package-") as temporary:
        root = Path(temporary)
        source_path = root / pin.source.filename
        source_path.write_bytes(payload)
        acquired = acquire_fcc_ecfs_snapshot(pin, root / "store", source_path=source_path)
        return parse_fcc_ecfs_snapshot(acquired)


def _codes_for(resource_name: ResourceName, parsed: ParsedFCCECFSSnapshot) -> tuple[FCCCode, ...]:
    return {
        "filingTypes": parsed.filing_types,
        "accessStatuses": parsed.access_statuses,
        "bureaus": parsed.bureaus,
        "proceedings": parsed.proceedings,
    }[resource_name]


def _identifier_payload(identifier: ControlledIdentifier, *, source_path: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": source_path,
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }
    if identifier.effective_at is not None:
        result["effectiveFrom"] = identifier.effective_at
    return result


def _observation_id(
    *,
    spec: FCCECFSCodeListPackageSpec,
    source_path: str,
    identifiers: Sequence[Mapping[str, Any]],
) -> str:
    identity = {
        "packageVersion": FCC_ECFS_CONTROLLED_LIST_PACKAGE_VERSION,
        "resourceId": spec.resource_id,
        "sourceArtifact": spec.pin.source.source_url,
        "sourcePath": source_path,
        "identifiers": [
            {
                "value": identifier["value"],
                "kind": identifier["kind"],
                "authorityUri": identifier["authorityUri"],
            }
            for identifier in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{spec.resource_id}:{digest}"


def _observations(
    spec: FCCECFSCodeListPackageSpec,
    parsed: ParsedFCCECFSSnapshot,
) -> tuple[Mapping[str, Any], ...]:
    if parsed.source != spec.pin.source:
        raise FCCECFSPackageError("parsed snapshot differs from its package source")
    if parsed.source_sha256 != spec.pin.expected_sha256:
        raise FCCECFSPackageError("parsed snapshot digest differs from its package source")
    if parsed.filing_count != spec.pin.expected_filing_count:
        raise FCCECFSPackageError("parsed snapshot filing count differs from its package source")

    codes = _codes_for(spec.resource_name, parsed)
    if len(codes) != spec.expected_distinct_count:
        raise FCCECFSPackageError(
            f"{spec.resource_name} distinct count drift: expected {spec.expected_distinct_count}, got {len(codes)}"
        )
    if parsed.raw_occurrence_counts[spec.resource_name] != spec.expected_raw_occurrence_count:
        raise FCCECFSPackageError(
            f"{spec.resource_name} raw occurrence count drift: "
            f"expected {spec.expected_raw_occurrence_count}, "
            f"got {parsed.raw_occurrence_counts[spec.resource_name]}"
        )

    result: list[Mapping[str, Any]] = []
    for ordinal, code in enumerate(codes):
        if code.resource_name != spec.resource_name or code.use not in spec.uses or code.is_general_subject_concept:
            raise FCCECFSPackageError(f"{spec.resource_name} row {ordinal} has an incompatible type or use")
        identifiers = tuple(
            _identifier_payload(identifier, source_path=code.source_path) for identifier in code.identifiers
        )
        primary_matches = [identifier for identifier in identifiers if identifier["kind"] == spec.primary_identifier_kind]
        if len(primary_matches) != 1:
            raise FCCECFSPackageError(
                f"{spec.resource_name} row {ordinal} must retain exactly one {spec.primary_identifier_kind}"
            )
        result.append(
            {
                "id": _observation_id(spec=spec, source_path=code.source_path, identifiers=identifiers),
                "sourceArtifact": spec.pin.source.source_url,
                "sourcePath": code.source_path,
                "sourceOrdinal": code.source_ordinal,
                "labels": [
                    {
                        "value": code.publisher_label,
                        "language": "en",
                        "role": "preferred",
                    }
                ],
                "identifiers": list(identifiers),
                "eligibleUses": list(spec.uses),
                "conceptIdentityClaimed": False,
            }
        )
    return tuple(result)


def build_fcc_ecfs_code_list_package(
    spec: FCCECFSCodeListPackageSpec,
    source_path: Path,
) -> SourceControlledResourceBundle:
    """Build one exact, development-only FCC ECFS controlled-list package."""

    path = Path(source_path)
    if path.is_symlink() or not path.is_file():
        raise FCCECFSPackageError(f"FCC ECFS controlled-list source is not a regular file: {path}")
    payload = path.read_bytes()
    parsed = _parse_exact_source(spec.pin, payload)
    excluded_count = spec.expected_raw_occurrence_count - spec.expected_distinct_count
    return build_source_controlled_resource_bundle(
        resource_id=spec.resource_id,
        title=spec.title,
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=spec.uses,
        captured_at=spec.pin.retrieved_at,
        candidate_use_authorized=True,
        observations=_observations(spec, parsed),
        source_artifacts={spec.pin.source.source_url: payload},
        source_observed_count=spec.expected_raw_occurrence_count,
        excluded_count=excluded_count,
        gaps=spec.known_gaps,
    )


def build_fcc_ecfs_filing_type_package(source_path: Path) -> SourceControlledResourceBundle:
    """Package this snapshot's observed Filing Types as deterministic metadata."""

    return build_fcc_ecfs_code_list_package(FCC_ECFS_FILING_TYPE_PACKAGE, source_path)


def build_fcc_ecfs_access_status_package(source_path: Path) -> SourceControlledResourceBundle:
    """Package this snapshot's observed Access Statuses as deterministic metadata."""

    return build_fcc_ecfs_code_list_package(FCC_ECFS_ACCESS_STATUS_PACKAGE, source_path)


def build_fcc_ecfs_bureau_package(source_path: Path) -> SourceControlledResourceBundle:
    """Package this snapshot's observed Bureaus as deterministic metadata."""

    return build_fcc_ecfs_code_list_package(FCC_ECFS_BUREAU_PACKAGE, source_path)


def build_fcc_ecfs_proceeding_package(source_path: Path) -> SourceControlledResourceBundle:
    """Package this snapshot's observed Proceedings as deterministic metadata."""

    return build_fcc_ecfs_code_list_package(FCC_ECFS_PROCEEDING_PACKAGE, source_path)


@dataclass(frozen=True, slots=True)
class FCCECFSCodeListView:
    """An FCC ECFS package reopened only after its complete closed set verifies."""

    package: SourceControlledResourceView
    spec: FCCECFSCodeListPackageSpec
    observations_by_code: Mapping[str, Mapping[str, Any]]

    @classmethod
    def open(cls, path: Path) -> FCCECFSCodeListView:
        """Open one known FCC ECFS package and rebuild it from retained source bytes."""

        package = SourceControlledResourceView.open(path)
        resource_id = package.resource_manifest.get("resourceId")
        if not isinstance(resource_id, str) or resource_id not in _PACKAGE_BY_RESOURCE_ID:
            raise FCCECFSPackageError(f"unknown FCC ECFS controlled-list resource {resource_id!r}")
        spec = _PACKAGE_BY_RESOURCE_ID[resource_id]
        if package.logical_digest != spec.expected_logical_digest:
            raise FCCECFSPackageError(f"{resource_id} logical digest differs from its external pin")
        source_bytes = package.source_artifact_bytes(spec.pin.source.source_url)
        if len(source_bytes) != spec.pin.expected_byte_length or _sha256(source_bytes) != spec.pin.expected_sha256:
            raise FCCECFSPackageError(f"{resource_id} retained source differs from its dated pin")

        excluded_count = spec.expected_raw_occurrence_count - spec.expected_distinct_count
        rebuilt = build_source_controlled_resource_bundle(
            resource_id=spec.resource_id,
            title=spec.title,
            resource_kind="controlledCodeList",
            identity_status="publisherIdentifiersPreserved",
            uses=spec.uses,
            captured_at=spec.pin.retrieved_at,
            candidate_use_authorized=True,
            observations=_observations(spec, _parse_exact_source(spec.pin, source_bytes)),
            source_artifacts={spec.pin.source.source_url: source_bytes},
            source_observed_count=spec.expected_raw_occurrence_count,
            excluded_count=excluded_count,
            gaps=spec.known_gaps,
        )
        if rebuilt.artifact_bytes() != {
            relative_path: (Path(path) / relative_path).read_bytes() for relative_path in rebuilt.artifact_bytes()
        }:
            raise FCCECFSPackageError(f"{resource_id} package differs from its deterministic FCC ECFS build")

        by_code: dict[str, Mapping[str, Any]] = {}
        for observation in package.observations:
            matches = [
                identifier
                for identifier in observation["identifiers"]
                if identifier["kind"] == spec.primary_identifier_kind
            ]
            if len(matches) != 1:
                raise FCCECFSPackageError(f"{resource_id} observation lacks one publisher code")
            code = matches[0]["value"]
            if code in by_code:
                raise FCCECFSPackageError(f"{resource_id} repeats publisher code {code!r}")
            by_code[code] = observation
        return cls(
            package=package,
            spec=spec,
            observations_by_code=MappingProxyType(by_code),
        )

    def lookup_code(self, value: str) -> Mapping[str, Any] | None:
        """Return one exact source observation by publisher code."""

        return self.observations_by_code.get(value)


__all__ = [
    "FCC_ECFS_ACCESS_STATUS_PACKAGE",
    "FCC_ECFS_BUREAU_PACKAGE",
    "FCC_ECFS_CONTROLLED_LIST_PACKAGES",
    "FCC_ECFS_CONTROLLED_LIST_PACKAGE_VERSION",
    "FCC_ECFS_FILINGS_SNAPSHOT",
    "FCC_ECFS_FILINGS_SNAPSHOT_2026_08_03",
    "FCC_ECFS_FILING_TYPE_PACKAGE",
    "FCC_ECFS_PROCEEDING_PACKAGE",
    "FCC_ECFS_SNAPSHOT_GAPS",
    "AcquiredFCCECFSSnapshot",
    "FCCCode",
    "FCCECFSAcquisitionError",
    "FCCECFSCaptureSource",
    "FCCECFSCodeListPackageSpec",
    "FCCECFSCodeListView",
    "FCCECFSFetcher",
    "FCCECFSPackageError",
    "FCCECFSResourceError",
    "FCCECFSSnapshotPin",
    "FCCECFSSourceDriftError",
    "FetchedFCCECFSResponse",
    "ParsedFCCECFSSnapshot",
    "acquire_fcc_ecfs_snapshot",
    "build_fcc_ecfs_access_status_package",
    "build_fcc_ecfs_bureau_package",
    "build_fcc_ecfs_code_list_package",
    "build_fcc_ecfs_filing_type_package",
    "build_fcc_ecfs_proceeding_package",
    "parse_fcc_ecfs_snapshot",
    "sha256_digest",
]

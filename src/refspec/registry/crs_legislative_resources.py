"""Source-faithful CRS legislative controlled-resource capture and parsing.

Congress.gov currently publishes the CRS Legislative Subject Terms as three
HTML field-value pages: topical subjects, geographic entities, and organization
names.  It publishes Policy Areas as a separate HTML table with scope notes.
The Congress.gov API exposes assignments on individual bills, but its documented
and observed payloads identify terms only by ``name``.

The Library of Congress Linked Data Service separately identifies the two
source schemes as ``lst`` and ``cgpa``.  This module preserves those scheme
identities alongside exact page and API bytes, official labels, source
categories, descriptions, and assignment update dates.  The scheme records do
not identify individual terms, so this module still records the absence of
publisher-issued term identifiers and never mints publisher or concept identity
from a label or list position.  The package layer may assign RefSpec local
record UUIDs and reconcile them across captures; those IDs identify registry
records only.  A managed release remains blocked until authoritative term
identifiers or a separately reviewed concept-identity policy are available.

Live retrieval is provider-independent.  Callers inject a fetcher (for example,
a Zyte-backed transport) or provide an already captured local file.  Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import quote, urlsplit

from refspec.registry.infrastructure.controlled_identifier import (
    ControlledIdentifier,
    distinct_identifiers,
    identifier_values,
)
from refspec.registry.infrastructure.source_identity import SourceCaptureEvent, SourceIdentityError

CRS_PUBLISHER = "Congressional Research Service"
CONGRESS_GOV_PUBLISHER = "Library of Congress"
CRS_LANGUAGE = "en"

ResourceName = Literal["legislativeSubjectTerms", "policyAreas"]
TermCategory = Literal["subject", "geographicEntity", "organizationName", "policyArea"]
ResourceRole = Literal["selectableSubject", "navigation"]
AcquisitionMode = Literal["cache", "local", "fetcher"]
IdentityStatus = Literal["publisherIdentifierAbsent", "publisherIdentifierPresent"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_IDENTIFIER_KEYS = ("id", "identifier", "code")
_IRI_KEYS = ("uri", "url")
_ASSIGNMENT_KEYS = frozenset({"name", "updateDate", *_IDENTIFIER_KEYS, *_IRI_KEYS})
_IDENTIFIER_KIND_BY_KEY = {
    "id": "publisherId",
    "identifier": "publisherIdentifier",
    "code": "publisherCode",
    "uri": "publisherTermUri",
    "url": "publisherTermUrl",
}
_PUBLISHER_IDENTIFIER_KINDS = frozenset(_IDENTIFIER_KIND_BY_KEY[key] for key in _IDENTIFIER_KEYS)
_PUBLISHER_TERM_IRI_KINDS = frozenset(_IDENTIFIER_KIND_BY_KEY[key] for key in _IRI_KEYS)
CONGRESS_GOV_IDENTIFIER_AUTHORITY_URI = "https://www.congress.gov/"
_CHALLENGE_MARKERS = (
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)


class CRSResourceError(ValueError):
    """Base class for CRS controlled-resource failures."""


class CRSAcquisitionError(CRSResourceError):
    """Exact source bytes could not be captured safely."""


class CRSSourceDriftError(CRSResourceError):
    """The captured publisher source no longer has the reviewed structure."""


class CRSIdentityError(CRSResourceError):
    """A managed release was requested without authoritative term identity."""


@dataclass(frozen=True, slots=True)
class CRSSourceScheme:
    """Library of Congress identity for one CRS controlled resource."""

    resource_name: ResourceName
    scheme_iri: str
    code: str
    label: str
    authority_record_url: str
    publisher_page_url: str

    def __post_init__(self) -> None:
        scheme = urlsplit(self.scheme_iri)
        if (
            scheme.scheme != "http"
            or scheme.hostname != "id.loc.gov"
            or scheme.path != f"/vocabulary/subjectSchemes/{self.code}"
        ):
            raise CRSAcquisitionError("scheme_iri must be the canonical LoC subject-scheme IRI")
        record = urlsplit(self.authority_record_url)
        if (
            record.scheme != "https"
            or record.hostname != "id.loc.gov"
            or record.path != f"/vocabulary/subjectSchemes/{self.code}.json"
        ):
            raise CRSAcquisitionError("authority_record_url must be the LoC JSON authority record")
        publisher_page = urlsplit(self.publisher_page_url)
        if publisher_page.scheme != "https" or publisher_page.hostname not in {"congress.gov", "www.congress.gov"}:
            raise CRSAcquisitionError("publisher_page_url must be an official HTTPS Congress.gov URL")
        if not self.code or not self.label:
            raise CRSAcquisitionError("source-scheme code and label must not be empty")


@dataclass(frozen=True, slots=True)
class CRSPageSource:
    """One official page that contributes terms to a CRS resource."""

    resource_name: ResourceName
    term_category: TermCategory
    role: ResourceRole
    source_url: str
    filename: str
    expected_heading: str
    expected_term_count: int
    category_label: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in {"congress.gov", "www.congress.gov"}:
            raise CRSAcquisitionError("source_url must be an official HTTPS Congress.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise CRSAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise CRSAcquisitionError("filename must be one plain path component")
        if self.expected_term_count <= 0:
            raise CRSAcquisitionError("expected_term_count must be positive")
        if not self.expected_heading or not self.category_label:
            raise CRSAcquisitionError("expected_heading and category_label must not be empty")


CRS_LEGISLATIVE_SUBJECTS_PAGE = CRSPageSource(
    resource_name="legislativeSubjectTerms",
    term_category="subject",
    role="selectableSubject",
    source_url="https://www.congress.gov/help/field-values/legislative-subject-terms",
    filename="legislative-subject-terms.html",
    expected_heading="Legislative Subject Terms",
    expected_term_count=565,
    category_label="Subjects",
)
CRS_LEGISLATIVE_GEOGRAPHIC_PAGE = CRSPageSource(
    resource_name="legislativeSubjectTerms",
    term_category="geographicEntity",
    role="selectableSubject",
    source_url="https://www.congress.gov/help/field-values/legislative-subject-terms/geographic",
    filename="legislative-subject-geographic-entities.html",
    expected_heading="Legislative Subject Terms",
    expected_term_count=301,
    category_label="Geographic Entities",
)
CRS_LEGISLATIVE_ORGANIZATIONS_PAGE = CRSPageSource(
    resource_name="legislativeSubjectTerms",
    term_category="organizationName",
    role="selectableSubject",
    source_url="https://www.congress.gov/help/field-values/legislative-subject-terms/organizations",
    filename="legislative-subject-organization-names.html",
    expected_heading="Legislative Subject Terms",
    expected_term_count=177,
    category_label="Organization Names",
)
CRS_LEGISLATIVE_SUBJECT_TERM_PAGES = (
    CRS_LEGISLATIVE_SUBJECTS_PAGE,
    CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
    CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
)
CRS_LEGISLATIVE_SUBJECT_TERM_LISTED_COUNT = sum(
    source.expected_term_count for source in CRS_LEGISLATIVE_SUBJECT_TERM_PAGES
)

CRS_POLICY_AREAS_PAGE = CRSPageSource(
    resource_name="policyAreas",
    term_category="policyArea",
    role="navigation",
    source_url="https://www.congress.gov/help/field-values/policy-area",
    filename="policy-areas.html",
    expected_heading="Policy Areas",
    expected_term_count=32,
    category_label="Policy Area",
)

CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME = CRSSourceScheme(
    resource_name="legislativeSubjectTerms",
    scheme_iri="http://id.loc.gov/vocabulary/subjectSchemes/lst",
    code="lst",
    label="Legislative subject terms",
    authority_record_url="https://id.loc.gov/vocabulary/subjectSchemes/lst.json",
    publisher_page_url=CRS_LEGISLATIVE_SUBJECTS_PAGE.source_url,
)
CRS_POLICY_AREAS_SCHEME = CRSSourceScheme(
    resource_name="policyAreas",
    scheme_iri="http://id.loc.gov/vocabulary/subjectSchemes/cgpa",
    code="cgpa",
    label="Congress.gov Policy Areas",
    authority_record_url="https://id.loc.gov/vocabulary/subjectSchemes/cgpa.json",
    publisher_page_url=CRS_POLICY_AREAS_PAGE.source_url,
)
CRS_SOURCE_SCHEMES = (
    CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME,
    CRS_POLICY_AREAS_SCHEME,
)
_CRS_SOURCE_SCHEME_BY_RESOURCE = {scheme.resource_name: scheme for scheme in CRS_SOURCE_SCHEMES}


def crs_source_scheme(resource_name: ResourceName) -> CRSSourceScheme:
    """Return the reviewed LoC scheme identity for one CRS resource."""

    return _CRS_SOURCE_SCHEME_BY_RESOURCE[resource_name]


@dataclass(frozen=True, slots=True)
class CRSPageSnapshotPin:
    """Expected identity of one exact Congress.gov page capture."""

    source: CRSPageSource
    retrieved_at: str
    fetch_id: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CRSAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CRSAcquisitionError("expected_byte_length must be positive")
        try:
            SourceCaptureEvent(fetch_id=self.fetch_id, fetched_at=self.retrieved_at)
        except SourceIdentityError as error:
            raise CRSAcquisitionError(f"CRS page fetch event is invalid: {error}") from error


@dataclass(frozen=True, slots=True)
class FetchedCRSPage:
    """Provider-independent result returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CRSPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCRSPage:
        """Fetch one official page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCRSPage:
    """One verified Congress.gov page in the content-addressed source store."""

    pin: CRSPageSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class CRSControlledTerm:
    """One exact value observed on a CRS field-value page."""

    resource_name: ResourceName
    category: TermCategory
    official_label: str
    definition: str | None
    language: str
    identifiers: tuple[ControlledIdentifier, ...]
    record_iri: str
    source_url: str
    source_ordinal: int

    @property
    def identity_status(self) -> IdentityStatus:
        return "publisherIdentifierPresent" if self.identifiers else "publisherIdentifierAbsent"

    @property
    def publisher_identifiers(self) -> tuple[str, ...]:
        return identifier_values(
            self.identifiers,
            kinds=_PUBLISHER_IDENTIFIER_KINDS,
        )

    @property
    def publisher_term_iris(self) -> tuple[str, ...]:
        return identifier_values(
            self.identifiers,
            kinds=_PUBLISHER_TERM_IRI_KINDS,
        )

    @property
    def publisher_identifier(self) -> str | None:
        values = self.publisher_identifiers
        return values[0] if len(values) == 1 else None

    @property
    def publisher_term_iri(self) -> str | None:
        values = self.publisher_term_iris
        return values[0] if len(values) == 1 else None


@dataclass(frozen=True, slots=True)
class CRSDuplicateLabelEvidence:
    """Source rows that share a label but remain separate observations."""

    official_label: str
    record_iris: tuple[str, ...]
    source_ordinals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedCRSPage:
    """Parsed terms from one exact, digest-pinned page."""

    source: CRSPageSource
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    terms: tuple[CRSControlledTerm, ...]
    duplicate_label_evidence: tuple[CRSDuplicateLabelEvidence, ...]


@dataclass(frozen=True, slots=True)
class CRSManagedReleaseReadiness:
    """Why an imported page set can or cannot become a managed release."""

    resource_name: ResourceName
    source_term_count: int
    source_digests: tuple[str, ...]
    publisher_identified_term_count: int
    ready: bool
    blockers: tuple[str, ...]

    def require_ready(self) -> None:
        """Fail rather than minting missing concept identity from labels."""

        if not self.ready:
            raise CRSIdentityError("; ".join(self.blockers))


@dataclass(frozen=True, slots=True)
class ParsedCRSResource:
    """A complete source-level view of one CRS controlled resource."""

    resource_name: ResourceName
    source_scheme: CRSSourceScheme
    role: ResourceRole
    pages: tuple[ParsedCRSPage, ...]
    terms: tuple[CRSControlledTerm, ...]
    readiness: CRSManagedReleaseReadiness


@dataclass(frozen=True, slots=True)
class CRSBillSubjectAssignment:
    """One CRS value assigned to an exact bill in the Congress.gov API."""

    category: Literal["legislativeSubject", "policyArea"]
    official_label: str
    assignment_update_date: str
    identifiers: tuple[ControlledIdentifier, ...]

    @property
    def identity_status(self) -> IdentityStatus:
        return "publisherIdentifierPresent" if self.identifiers else "publisherIdentifierAbsent"

    @property
    def publisher_identifiers(self) -> tuple[str, ...]:
        return identifier_values(
            self.identifiers,
            kinds=_PUBLISHER_IDENTIFIER_KINDS,
        )

    @property
    def publisher_term_iris(self) -> tuple[str, ...]:
        return identifier_values(
            self.identifiers,
            kinds=_PUBLISHER_TERM_IRI_KINDS,
        )

    @property
    def publisher_identifier(self) -> str | None:
        values = self.publisher_identifiers
        return values[0] if len(values) == 1 else None

    @property
    def publisher_term_iri(self) -> str | None:
        values = self.publisher_term_iris
        return values[0] if len(values) == 1 else None


@dataclass(frozen=True, slots=True)
class ParsedCRSBillAssignments:
    """Source-derived bill assignment evidence from one exact API payload."""

    bill_url: str
    source_sha256: str
    source_byte_length: int
    legislative_subjects: tuple[CRSBillSubjectAssignment, ...]
    policy_area: CRSBillSubjectAssignment | None


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def crs_source_record_iri(
    source: CRSPageSource,
    *,
    source_sha256: str,
    source_ordinal: int,
) -> str:
    """Build a capture-local observation IRI, not a publisher identifier."""

    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise CRSSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if source_ordinal <= 0:
        raise CRSSourceDriftError("source_ordinal must be positive")
    source_path = quote(urlsplit(source.source_url).path, safe="")
    return f"urn:ref:crs-source-record:{match.group(1)}:{source.term_category}:{source_path}:{source_ordinal}"


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"congress.gov", "www.congress.gov"}:
        raise CRSAcquisitionError("fetcher resolved_url must remain on official HTTPS Congress.gov")
    if parsed.username is not None or parsed.password is not None:
        raise CRSAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise CRSSourceDriftError("Congress.gov returned a challenge page instead of field values")
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise CRSSourceDriftError("Congress.gov field-value capture is not an HTML document")


def _validate_fetched_page(
    fetched: FetchedCRSPage,
    *,
    source_url: str,
) -> None:
    if fetched.status_code != 200:
        raise CRSAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise CRSSourceDriftError(f"Congress.gov field-value page content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: CRSPageSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CRSSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CRSSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: CRSPageSnapshotPin) -> AcquiredCRSPage:
    if path.is_symlink() or not path.is_file():
        raise CRSAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached CRS page",
    )
    return AcquiredCRSPage(
        pin=pin,
        path=path,
        source_url=pin.source.source_url,
        resolved_url=None,
        sha256=actual_sha256,
        byte_length=byte_length,
        content_type="text/html",
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: CRSPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCRSPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} CRS page",
    )
    object_dir = final_path.parent
    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=object_dir,
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
        return AcquiredCRSPage(
            pin=pin,
            path=final_path,
            source_url=pin.source.source_url,
            resolved_url=resolved_url,
            sha256=actual_sha256,
            byte_length=byte_length,
            content_type=content_type,
            acquisition_mode=acquisition_mode,
            cache_hit=False,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_crs_page(
    pin: CRSPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CRSPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredCRSPage:
    """Acquire one exact page from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache miss.
    This keeps Zyte, direct HTTP, and future transports outside the source
    parser while applying the same digest, length, origin, and challenge-page
    checks to all fetched bytes.
    """

    if timeout_seconds <= 0:
        raise CRSAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CRSAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CRSAcquisitionError(f"local CRS source is not a regular file: {local_path}")
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
        raise CRSAcquisitionError("CRS page is not cached; provide source_path or an injected fetcher")

    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(
        fetched,
        source_url=pin.source.source_url,
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


def capture_initial_crs_page_snapshot(
    source: CRSPageSource,
    store_dir: Path,
    *,
    retrieved_at: str,
    fetcher: CRSPageFetcher,
    fetch_event: SourceCaptureEvent | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredCRSPage:
    """Capture valid first-seen bytes and return the exact pin they establish.

    This is the discovery step used before a strict
    :func:`acquire_crs_page` reopen.  It validates origin, status, media type,
    challenge markers, and HTML shape before publishing bytes under their
    content digest.
    """

    if timeout_seconds <= 0:
        raise CRSAcquisitionError("timeout_seconds must be positive")
    if not retrieved_at.strip():
        raise CRSAcquisitionError("retrieved_at must not be empty")
    event = SourceCaptureEvent.generate(fetched_at=retrieved_at) if fetch_event is None else fetch_event
    if event.fetched_at != retrieved_at:
        raise CRSAcquisitionError("CRS page fetch event time must equal retrieved_at")
    fetched = fetcher.fetch(
        source.source_url,
        timeout_seconds=timeout_seconds,
    )
    _validate_fetched_page(fetched, source_url=source.source_url)
    pin = CRSPageSnapshotPin(
        source=source,
        retrieved_at=retrieved_at,
        fetch_id=event.fetch_id,
        expected_sha256=sha256_digest(fetched.body),
        expected_byte_length=len(fetched.body),
    )
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / source.filename
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


@dataclass(slots=True)
class _ListContext:
    items: list[str]


@dataclass(slots=True)
class _ListItemContext:
    list_context: _ListContext
    text: list[str]
    contains_heading: bool = False


@dataclass(slots=True)
class _TableContext:
    rows: list[tuple[str, ...]]


class _FieldValuesParser(HTMLParser):
    """Collect headings, list candidates, and tables without site dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.lists: list[tuple[str, ...]] = []
        self.tables: list[tuple[tuple[str, ...], ...]] = []
        self.all_text: list[str] = []
        self._heading_text: list[str] | None = None
        self._heading_tag: str | None = None
        self._list_stack: list[_ListContext] = []
        self._item_stack: list[_ListItemContext] = []
        self._table_stack: list[_TableContext] = []
        self._row: list[str] | None = None
        self._cell_text: list[str] | None = None
        self._cell_tag: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in {"h1", "h2", "h3"}:
            self._heading_tag = tag
            self._heading_text = []
            if self._item_stack:
                self._item_stack[-1].contains_heading = True
        if tag in {"ul", "ol"}:
            self._list_stack.append(_ListContext(items=[]))
        elif tag == "li" and self._list_stack:
            self._item_stack.append(_ListItemContext(list_context=self._list_stack[-1], text=[]))
        if tag == "table":
            self._table_stack.append(_TableContext(rows=[]))
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_tag = tag
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self._heading_text is not None:
            self._heading_text.append(data)
        if self._item_stack:
            self._item_stack[-1].text.append(data)
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag and self._heading_text is not None:
            text = _normalize_text(self._heading_text)
            if text:
                self.headings.append(text)
            self._heading_text = None
            self._heading_tag = None
        if tag == "li" and self._item_stack:
            item = self._item_stack.pop()
            text = _normalize_text(item.text)
            if text and not item.contains_heading:
                item.list_context.items.append(text)
        elif tag in {"ul", "ol"} and self._list_stack:
            completed = self._list_stack.pop()
            if completed.items:
                self.lists.append(tuple(completed.items))
        if tag == self._cell_tag and self._cell_text is not None and self._row is not None:
            self._row.append(_normalize_text(self._cell_text))
            self._cell_text = None
            self._cell_tag = None
        elif tag == "tr" and self._row is not None and self._table_stack:
            self._table_stack[-1].rows.append(tuple(self._row))
            self._row = None
        elif tag == "table" and self._table_stack:
            completed_table = self._table_stack.pop()
            if completed_table.rows:
                self.tables.append(tuple(completed_table.rows))


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


def _read_acquired_payload(page: AcquiredCRSPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed CRS page")
    return payload


def _parse_html(page: AcquiredCRSPage) -> _FieldValuesParser:
    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CRSSourceDriftError("Congress.gov field-value page is not UTF-8") from error
    parser = _FieldValuesParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as error:
        raise CRSSourceDriftError("Congress.gov field-value page is malformed HTML") from error
    if not any(page.pin.source.expected_heading in heading for heading in parser.headings):
        raise CRSSourceDriftError(f"missing expected heading {page.pin.source.expected_heading!r}")
    return parser


def _term(
    source: CRSPageSource,
    label: str,
    ordinal: int,
    *,
    definition: str | None,
    source_sha256: str,
) -> CRSControlledTerm:
    return CRSControlledTerm(
        resource_name=source.resource_name,
        category=source.term_category,
        official_label=label,
        definition=definition,
        language=CRS_LANGUAGE,
        identifiers=(),
        record_iri=crs_source_record_iri(
            source,
            source_sha256=source_sha256,
            source_ordinal=ordinal,
        ),
        source_url=source.source_url,
        source_ordinal=ordinal,
    )


def _duplicate_label_evidence(
    terms: Sequence[CRSControlledTerm],
) -> tuple[CRSDuplicateLabelEvidence, ...]:
    grouped: dict[str, list[CRSControlledTerm]] = {}
    for term in terms:
        grouped.setdefault(term.official_label, []).append(term)
    return tuple(
        CRSDuplicateLabelEvidence(
            official_label=label,
            record_iris=tuple(term.record_iri for term in matches),
            source_ordinals=tuple(term.source_ordinal for term in matches),
        )
        for label, matches in grouped.items()
        if len(matches) > 1
    )


def parse_crs_field_value_page(page: AcquiredCRSPage) -> ParsedCRSPage:
    """Parse one pinned LST category page or the separate Policy Area table."""

    parser = _parse_html(page)
    source = page.pin.source
    if source.resource_name == "legislativeSubjectTerms":
        marker = f"{source.category_label} ({source.expected_term_count})"
        page_text = _normalize_text(parser.all_text)
        if marker not in page_text:
            raise CRSSourceDriftError(f"missing expected CRS category/count marker {marker!r}")
        if not parser.lists:
            raise CRSSourceDriftError("Legislative Subject Terms page has no term list")
        labels = max(parser.lists, key=len)
        if len(labels) != source.expected_term_count:
            raise CRSSourceDriftError(
                f"{source.category_label} count drift: expected {source.expected_term_count}, parsed {len(labels)}"
            )
        terms = tuple(
            _term(
                source,
                label,
                ordinal,
                definition=None,
                source_sha256=page.sha256,
            )
            for ordinal, label in enumerate(labels, start=1)
        )
    else:
        expected_intro = f"One of {source.expected_term_count} broad policy area terms"
        if expected_intro not in _normalize_text(parser.all_text):
            raise CRSSourceDriftError(f"missing expected Policy Area count statement {expected_intro!r}")
        matching_tables = [
            table
            for table in parser.tables
            if table and tuple(cell.casefold() for cell in table[0]) == ("policy area", "description")
        ]
        if len(matching_tables) != 1:
            raise CRSSourceDriftError("Policy Areas page must contain exactly one Policy Area/Description table")
        rows = matching_tables[0][1:]
        if len(rows) != source.expected_term_count:
            raise CRSSourceDriftError(
                f"Policy Area count drift: expected {source.expected_term_count}, parsed {len(rows)}"
            )
        if any(len(row) != 2 or not row[0] or not row[1] for row in rows):
            raise CRSSourceDriftError("every Policy Area row must contain a non-empty label and description")
        labels = tuple(row[0] for row in rows)
        if len(set(labels)) != len(labels):
            raise CRSSourceDriftError("Policy Areas page contains duplicate labels")
        terms = tuple(
            _term(
                source,
                label,
                ordinal,
                definition=description,
                source_sha256=page.sha256,
            )
            for ordinal, (label, description) in enumerate(rows, start=1)
        )

    return ParsedCRSPage(
        source=source,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        terms=terms,
        duplicate_label_evidence=_duplicate_label_evidence(terms),
    )


def _resource_readiness(
    resource_name: ResourceName,
    pages: Sequence[ParsedCRSPage],
    terms: Sequence[CRSControlledTerm],
) -> CRSManagedReleaseReadiness:
    identified = sum(bool(term.identifiers) for term in terms)
    blockers: list[str] = []
    if identified != len(terms):
        blockers.append("Congress.gov does not publish stable identifiers or term IRIs for every value")
    duplicate_groups = sum(len(page.duplicate_label_evidence) for page in pages)
    if duplicate_groups:
        blockers.append(
            f"{duplicate_groups} repeated source label group(s) require publisher identity or reviewed reconciliation"
        )
    blockers.append("Congress.gov does not publish these pages as a named, versioned vocabulary release")
    return CRSManagedReleaseReadiness(
        resource_name=resource_name,
        source_term_count=len(terms),
        source_digests=tuple(page.source_sha256 for page in pages),
        publisher_identified_term_count=identified,
        ready=not blockers,
        blockers=tuple(blockers),
    )


def assemble_crs_legislative_subject_terms(
    pages: Sequence[ParsedCRSPage],
) -> ParsedCRSResource:
    """Assemble all three official LST category pages without merging labels."""

    expected_categories = {source.term_category for source in CRS_LEGISLATIVE_SUBJECT_TERM_PAGES}
    categories = [page.source.term_category for page in pages]
    if len(pages) != len(expected_categories) or set(categories) != expected_categories:
        raise CRSSourceDriftError(
            "Legislative Subject Terms require exactly one subject, geographicEntity, and organizationName page"
        )
    if len(set(categories)) != len(categories):
        raise CRSSourceDriftError("Legislative Subject Terms page categories must not repeat")
    ordered_pages = tuple(
        next(page for page in pages if page.source.term_category == source.term_category)
        for source in CRS_LEGISLATIVE_SUBJECT_TERM_PAGES
    )
    terms = tuple(term for page in ordered_pages for term in page.terms)
    return ParsedCRSResource(
        resource_name="legislativeSubjectTerms",
        source_scheme=CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME,
        role="selectableSubject",
        pages=ordered_pages,
        terms=terms,
        readiness=_resource_readiness("legislativeSubjectTerms", ordered_pages, terms),
    )


def assemble_crs_policy_areas(page: ParsedCRSPage) -> ParsedCRSResource:
    """Keep broad Policy Areas separate from detailed Legislative Subject Terms."""

    if page.source.resource_name != "policyAreas" or page.source.term_category != "policyArea":
        raise CRSSourceDriftError("Policy Areas assembly requires the Policy Area page")
    pages = (page,)
    return ParsedCRSResource(
        resource_name="policyAreas",
        source_scheme=CRS_POLICY_AREAS_SCHEME,
        role="navigation",
        pages=pages,
        terms=page.terms,
        readiness=_resource_readiness("policyAreas", pages, page.terms),
    )


def _assignment_identifier_values(
    value: object,
    *,
    field: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values: Sequence[object] = (value,)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray),
    ):
        raw_values = value
    else:
        raise CRSSourceDriftError(f"assignment {field} must be a string or array of strings")
    result: list[str] = []
    for item in raw_values:
        if not isinstance(item, str) or not item.strip():
            raise CRSSourceDriftError(f"assignment {field} values must be non-empty strings")
        text = item.strip()
        if text not in result:
            result.append(text)
    return tuple(result)


def _assignment_identifiers(
    record: Mapping[str, object],
    *,
    source_uri: str,
    effective_at: str,
    source_digest: str,
    category: str,
) -> tuple[ControlledIdentifier, ...]:
    identifiers: list[ControlledIdentifier] = []
    for key, kind in _IDENTIFIER_KIND_BY_KEY.items():
        for value in _assignment_identifier_values(
            record.get(key),
            field=key,
        ):
            if key in _IRI_KEYS and not urlsplit(value).scheme:
                raise CRSSourceDriftError(f"{category} publisher term URI must be absolute")
            identifiers.append(
                ControlledIdentifier(
                    value=value,
                    kind=kind,
                    authority_uri=CONGRESS_GOV_IDENTIFIER_AUTHORITY_URI,
                    source_uri=source_uri,
                    observed_at=None,
                    effective_at=effective_at,
                    source_digest=source_digest,
                )
            )
    return distinct_identifiers(identifiers)


def _assignment(
    record: object,
    category: Literal["legislativeSubject", "policyArea"],
    *,
    source_uri: str,
    source_digest: str,
) -> CRSBillSubjectAssignment:
    if not isinstance(record, Mapping):
        raise CRSSourceDriftError(f"{category} assignment must be an object")
    unexpected = set(record) - _ASSIGNMENT_KEYS
    if unexpected:
        raise CRSSourceDriftError(f"{category} assignment added unreviewed fields: {sorted(unexpected)}")
    label_value = record.get("name")
    update_value = record.get("updateDate")
    if not isinstance(label_value, str) or not label_value.strip():
        raise CRSSourceDriftError(f"{category} assignment name must be a non-empty string")
    if not isinstance(update_value, str) or not update_value.strip():
        raise CRSSourceDriftError(f"{category} assignment updateDate must be a non-empty string")
    update_date = update_value.strip()
    identifiers = _assignment_identifiers(
        record,
        source_uri=source_uri,
        effective_at=update_date,
        source_digest=source_digest,
        category=category,
    )
    return CRSBillSubjectAssignment(
        category=category,
        official_label=label_value.strip(),
        assignment_update_date=update_date,
        identifiers=identifiers,
    )


def parse_crs_bill_subject_assignments(payload: bytes) -> ParsedCRSBillAssignments:
    """Parse one exact Congress.gov ``/bill/.../subjects`` JSON response.

    This parser is assignment evidence, not a vocabulary importer.  It accepts
    and preserves publisher identifiers if Congress.gov adds them later, while
    current payloads truthfully report ``publisherIdentifierAbsent``.
    """

    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CRSSourceDriftError("Congress.gov bill subjects payload is not valid JSON") from error
    if not isinstance(root, Mapping):
        raise CRSSourceDriftError("Congress.gov bill subjects payload must be an object")
    request = root.get("request")
    subjects = root.get("subjects")
    pagination = root.get("pagination")
    if not isinstance(request, Mapping) or not isinstance(subjects, Mapping):
        raise CRSSourceDriftError("Congress.gov bill subjects payload lacks request or subjects")
    bill_url_value = request.get("billUrl")
    if not isinstance(bill_url_value, str) or not bill_url_value.startswith("https://api.congress.gov/"):
        raise CRSSourceDriftError("Congress.gov bill subjects request lacks an official billUrl")
    source_digest = sha256_digest(payload)
    raw_subjects = subjects.get("legislativeSubjects")
    if not isinstance(raw_subjects, list):
        raise CRSSourceDriftError("subjects.legislativeSubjects must be a list")
    legislative_subjects = tuple(
        _assignment(
            record,
            "legislativeSubject",
            source_uri=bill_url_value,
            source_digest=source_digest,
        )
        for record in raw_subjects
    )
    labels = [assignment.official_label for assignment in legislative_subjects]
    if len(labels) != len(set(labels)):
        raise CRSSourceDriftError("bill subjects payload contains duplicate legislative labels")

    raw_policy = subjects.get("policyArea")
    policy_area = (
        _assignment(
            raw_policy,
            "policyArea",
            source_uri=bill_url_value,
            source_digest=source_digest,
        )
        if raw_policy is not None
        else None
    )
    if isinstance(pagination, Mapping) and isinstance(pagination.get("count"), int):
        expected = len(legislative_subjects) + (1 if policy_area is not None else 0)
        if pagination["count"] != expected:
            raise CRSSourceDriftError(
                f"bill subjects pagination count drift: expected {expected}, got {pagination['count']}"
            )
    return ParsedCRSBillAssignments(
        bill_url=bill_url_value,
        source_sha256=source_digest,
        source_byte_length=len(payload),
        legislative_subjects=legislative_subjects,
        policy_area=policy_area,
    )

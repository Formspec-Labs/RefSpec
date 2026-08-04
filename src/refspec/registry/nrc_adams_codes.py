"""NRC ADAMS identifier shapes and current public search facet values.

The NRC ADAMS Public Documents source (https://www.nrc.gov/reading-rm/adams)
publishes no dedicated code-list or constants endpoint. This module packages a
source audit of what the official pages and the live ADAMS Public Search (APS)
application actually expose: the syntax of docket numbers and of the "Public
Legacy Library" (PLL) accession number is documented in FAQ prose; the current
("ML") accession number is not documented in prose anywhere this module
checked, so its shape is inferred from two real example values embedded in
linked document filenames on the landing page; a small, fixed list of docket/
license reference categories is enumerated on the Help and References page;
and the current APS result-field and library-facet labels are read from the
live APS application bundle, because APS -- not the legacy Web-based ADAMS
(WBA) interface the FAQ otherwise documents -- is the current public search
interface and publishes no equivalent prose reference page of its own.

None of these values is a general subject concept: they are identifier syntax
rules and small, source-observed search/reference vocabularies. This module
never mints a concept identifier, never reconciles them into a normalized NRC
type list, and never claims the captured lists are exhaustive beyond what one
snapshot observed.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and no scraping provider is
required for the currently public HTML pages and JavaScript asset.
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

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier

NRC_PUBLISHER = "U.S. Nuclear Regulatory Commission"
NRC_ADAMS_IDENTIFIER_AUTHORITY_URI = "https://www.nrc.gov/reading-rm/adams"
NRC_ADAMS_LANDING_URL = "https://www.nrc.gov/reading-rm/adams"
NRC_ADAMS_HELP_REFERENCE_URL = "https://www.nrc.gov/reading-rm/adams/help-reference.html"
NRC_ADAMS_FAQ_URL = "https://www.nrc.gov/reading-rm/adams/faq.html"
NRC_ADAMS_SYSTEM_NOTICES_URL = "https://www.nrc.gov/reading-rm/adams/adams-sys-notice"
# Angular build output; the filename hash changes on every publisher deploy
# (see NRC_ADAMS_PORTFOLIO_GAPS). This is the exact URL captured for this audit.
NRC_APS_SEARCH_BUNDLE_URL = "https://adams-search.nrc.gov/main.6c73a88ad6c1b2ad.js"

ResourceName = Literal[
    "landingPage",
    "helpReferencePage",
    "faqPage",
    "systemNoticesPage",
    "apsResultFieldLabels",
    "apsLibraryFacetLabels",
]
# Every captured value here is search/reference metadata, never filer-selected
# subject evidence and never a general subject concept.
ResourceUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]
CaptureKind = Literal["fullOfficialResponse", "verbatimExcerptOfLargerOfficialAsset"]
IdentifierShapeKind = Literal[
    "docketNumber",
    "legacyLibraryAccessionNumber",
    "currentAccessionNumber",
]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_HOSTS_BY_RESOURCE: Mapping[ResourceName, str] = {
    "landingPage": "www.nrc.gov",
    "helpReferencePage": "www.nrc.gov",
    "faqPage": "www.nrc.gov",
    "systemNoticesPage": "www.nrc.gov",
    "apsResultFieldLabels": "adams-search.nrc.gov",
    "apsLibraryFacetLabels": "adams-search.nrc.gov",
}
_CONTENT_TYPE_BY_RESOURCE: Mapping[ResourceName, str] = {
    "landingPage": "text/html",
    "helpReferencePage": "text/html",
    "faqPage": "text/html",
    "systemNoticesPage": "text/html",
    "apsResultFieldLabels": "text/javascript",
    "apsLibraryFacetLabels": "text/javascript",
}
_ACCEPTED_MEDIA_TYPES: Mapping[ResourceName, frozenset[str]] = {
    "landingPage": frozenset({"text/html"}),
    "helpReferencePage": frozenset({"text/html"}),
    "faqPage": frozenset({"text/html"}),
    "systemNoticesPage": frozenset({"text/html"}),
    "apsResultFieldLabels": frozenset({"application/javascript", "text/javascript"}),
    "apsLibraryFacetLabels": frozenset({"application/javascript", "text/javascript"}),
}


class AdamsResourceError(ValueError):
    """Base class for NRC ADAMS controlled-code and identifier-shape failures."""


class AdamsAcquisitionError(AdamsResourceError):
    """Exact official source bytes could not be acquired safely."""


class AdamsSourceDriftError(AdamsResourceError):
    """An ADAMS source no longer matches the reviewed structure or pin."""


class AdamsAssignmentError(AdamsResourceError):
    """A record carries an unknown or malformed source-assigned ADAMS identifier."""


@dataclass(frozen=True, slots=True)
class AdamsSource:
    """One official NRC ADAMS resource this module captures."""

    resource_name: ResourceName
    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        expected_host = _HOSTS_BY_RESOURCE[self.resource_name]
        if parsed.scheme != "https" or parsed.hostname != expected_host:
            raise AdamsAcquisitionError(f"source_url must be an official HTTPS {expected_host} URL")
        if parsed.username is not None or parsed.password is not None:
            raise AdamsAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise AdamsAcquisitionError("filename must be one plain path component")


NRC_ADAMS_LANDING_PAGE = AdamsSource(
    resource_name="landingPage",
    source_url=NRC_ADAMS_LANDING_URL,
    filename="nrc-adams-landing-page.html",
)
NRC_ADAMS_HELP_REFERENCE = AdamsSource(
    resource_name="helpReferencePage",
    source_url=NRC_ADAMS_HELP_REFERENCE_URL,
    filename="nrc-adams-help-reference.html",
)
NRC_ADAMS_FAQ = AdamsSource(
    resource_name="faqPage",
    source_url=NRC_ADAMS_FAQ_URL,
    filename="nrc-adams-faq.html",
)
NRC_ADAMS_SYSTEM_NOTICES = AdamsSource(
    resource_name="systemNoticesPage",
    source_url=NRC_ADAMS_SYSTEM_NOTICES_URL,
    filename="nrc-adams-system-notices.html",
)
NRC_APS_RESULT_FIELD_LABELS_SOURCE = AdamsSource(
    resource_name="apsResultFieldLabels",
    source_url=NRC_APS_SEARCH_BUNDLE_URL,
    filename="nrc-aps-result-field-labels-excerpt.js",
)
NRC_APS_LIBRARY_FACET_LABELS_SOURCE = AdamsSource(
    resource_name="apsLibraryFacetLabels",
    source_url=NRC_APS_SEARCH_BUNDLE_URL,
    filename="nrc-aps-library-facet-labels-excerpt.js",
)


@dataclass(frozen=True, slots=True)
class AdamsSnapshotPin:
    """Exact identity of one official ADAMS capture.

    ``capture_kind`` distinguishes a full official response from a small,
    byte-exact excerpt of a much larger official asset (the APS JavaScript
    bundle); an excerpt pin must also record the full asset's own digest and
    length so its provenance stays traceable even though this module does not
    package the entire bundle.
    """

    source: AdamsSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    capture_kind: CaptureKind
    full_asset_sha256: str | None = None
    full_asset_byte_length: int | None = None

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise AdamsAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise AdamsAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise AdamsAcquisitionError("retrieved_at must not be empty")
        if self.capture_kind == "verbatimExcerptOfLargerOfficialAsset":
            if self.full_asset_sha256 is None or self.full_asset_byte_length is None:
                raise AdamsAcquisitionError(
                    "an excerpt pin must record its full_asset_sha256 and full_asset_byte_length"
                )
            if _DIGEST.fullmatch(self.full_asset_sha256) is None:
                raise AdamsAcquisitionError("full_asset_sha256 must be a lowercase sha256:<64 hex> digest")
            if self.full_asset_byte_length <= self.expected_byte_length:
                raise AdamsAcquisitionError("full_asset_byte_length must exceed the excerpt's own byte length")
        elif self.full_asset_sha256 is not None or self.full_asset_byte_length is not None:
            raise AdamsAcquisitionError("a full-page capture must not declare a parent asset")


# Captured 2026-08-03 from the live, currently public pages and application.
NRC_ADAMS_LANDING_PAGE_2026_08_03 = AdamsSnapshotPin(
    source=NRC_ADAMS_LANDING_PAGE,
    retrieved_at="2026-08-03T19:26:41Z",
    expected_sha256="sha256:437f3bdec4b6d56c27141bf5242cbd60ee6e3d80826687859dbc6931e7f345fb",
    expected_byte_length=91_742,
    capture_kind="fullOfficialResponse",
)
NRC_ADAMS_HELP_REFERENCE_2026_08_03 = AdamsSnapshotPin(
    source=NRC_ADAMS_HELP_REFERENCE,
    retrieved_at="2026-08-03T19:29:40Z",
    expected_sha256="sha256:97dd3e55dafa35fabeaccb90a47d5787a9558d528c6e83c0eaa4cc844a75a341",
    expected_byte_length=85_748,
    capture_kind="fullOfficialResponse",
)
NRC_ADAMS_FAQ_2026_08_03 = AdamsSnapshotPin(
    source=NRC_ADAMS_FAQ,
    retrieved_at="2026-08-03T19:29:41Z",
    expected_sha256="sha256:13e3041bccbfebd4d06696c388d76595cf343b1be798bbcf727399bbd98012f2",
    expected_byte_length=100_397,
    capture_kind="fullOfficialResponse",
)
NRC_ADAMS_SYSTEM_NOTICES_2026_08_03 = AdamsSnapshotPin(
    source=NRC_ADAMS_SYSTEM_NOTICES,
    retrieved_at="2026-08-03T23:04:00Z",
    expected_sha256="sha256:1acc97940de447be550ee9d8f2dea57cf9b49c9d4e73b23b2039ffd71be82732",
    expected_byte_length=79_649,
    capture_kind="fullOfficialResponse",
)
# The full bundle these two excerpts were cut from was 1,578,086 bytes at
# sha256:b5c6858c1d32cc084a116633c3e1d0152ee7d998495ec74844303317f022c243;
# this module packages only the small, byte-exact regions parsed below.
NRC_APS_RESULT_FIELD_LABELS_2026_08_03 = AdamsSnapshotPin(
    source=NRC_APS_RESULT_FIELD_LABELS_SOURCE,
    retrieved_at="2026-08-03T19:33:10Z",
    expected_sha256="sha256:7247022b52a8ffff04ba3589235d300a4a40ad284b89ee18702af9bf5c08b911",
    expected_byte_length=1_779,
    capture_kind="verbatimExcerptOfLargerOfficialAsset",
    full_asset_sha256="sha256:b5c6858c1d32cc084a116633c3e1d0152ee7d998495ec74844303317f022c243",
    full_asset_byte_length=1_578_086,
)
NRC_APS_LIBRARY_FACET_LABELS_2026_08_03 = AdamsSnapshotPin(
    source=NRC_APS_LIBRARY_FACET_LABELS_SOURCE,
    retrieved_at="2026-08-03T19:33:10Z",
    expected_sha256="sha256:6586681097db869c5c8116d8fca288a9f07174a24029ed27c3583afbc7deb603",
    expected_byte_length=197,
    capture_kind="verbatimExcerptOfLargerOfficialAsset",
    full_asset_sha256="sha256:b5c6858c1d32cc084a116633c3e1d0152ee7d998495ec74844303317f022c243",
    full_asset_byte_length=1_578_086,
)


@dataclass(frozen=True, slots=True)
class FetchedAdamsResponse:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class AdamsFetcher(Protocol):
    """Small transport boundary for the official ADAMS pages and APS asset."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedAdamsResponse:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredAdamsSource:
    """One verified source object in the content-addressed store."""

    pin: AdamsSnapshotPin
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


def _validate_resolved_url(pin: AdamsSnapshotPin, value: str) -> None:
    parsed = urlsplit(value)
    expected_host = _HOSTS_BY_RESOURCE[pin.source.resource_name]
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise AdamsAcquisitionError(f"fetcher resolved_url must remain on official HTTPS {expected_host}")
    if parsed.username is not None or parsed.password is not None:
        raise AdamsAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: AdamsSnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise AdamsSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise AdamsSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AdamsSourceDriftError(f"{location} is not valid UTF-8 text") from error
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: AdamsSnapshotPin) -> AcquiredAdamsSource:
    if path.is_symlink() or not path.is_file():
        raise AdamsAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached NRC ADAMS source",
    )
    return AcquiredAdamsSource(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.source.source_url,
        resolved_url=None,
        content_type=_CONTENT_TYPE_BY_RESOURCE[pin.source.resource_name],
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: AdamsSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredAdamsSource:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} NRC ADAMS source",
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
        return AcquiredAdamsSource(
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


def acquire_adams_source(
    pin: AdamsSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: AdamsFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredAdamsSource:
    """Acquire one exact ADAMS response through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise AdamsAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise AdamsAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise AdamsAcquisitionError(f"local NRC ADAMS source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type=_CONTENT_TYPE_BY_RESOURCE[pin.source.resource_name],
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise AdamsAcquisitionError("NRC ADAMS source is not cached; provide source_path or an injected fetcher")
    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise AdamsAcquisitionError(f"could not acquire {pin.source.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(pin, fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in _ACCEPTED_MEDIA_TYPES[pin.source.resource_name]:
        raise AdamsSourceDriftError(f"NRC ADAMS response content type drifted to {fetched.content_type!r}")
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


# ---------------------------------------------------------------------------
# Small controlled code lists: current APS result-field labels, current APS
# library-facet labels, and the fixed docket/license reference-category list.
# ---------------------------------------------------------------------------

_RESULT_FIELD_ROW = re.compile(
    r'function \w+\(t,n\)\{if\(1&t&&\(_\(0,"tr"\)\(1,"td",2\),b\(2,"(?P<label>[^"]*)"\),m\(\),_\(3,"td"\),b\(4\)'
    r'(?P<date_marker>,St\(5,"date"\))?,m\(\)\(\)\),2&t\)\{const e=h\(\);f\(4\),_e\('
    r"(?P<value_expr>(?:_n\(5,1,)?e\.item\.\w+\)?)\)\}\}"
)
_PROPERTY_KEY = re.compile(r"e\.item\.(\w+)")
_EXPECTED_RESULT_FIELD_COUNT = 12

_LIBRARY_FACET_ROW = re.compile(
    r'\["formControlName","(?P<control>\w+)","label","(?P<label>[^"]+)",1,"me-3",3,"binary","onChange"\]'
)
_EXPECTED_LIBRARY_FACET_COUNT = 2

_LICENSE_LIST_SECTION = re.compile(
    r'<h2 id="ListofLicenses">Lists of Licenses and Docket Numbers</h2><ul>'
    r'(?P<items>(?:<li data-list-item-id="[0-9a-f]+"><a href="[^"]+">[^<]+</a></li>)+)'
    r"</ul>"
)
_LICENSE_LIST_ITEM = re.compile(
    r'<li data-list-item-id="[0-9a-f]+"><a href="(?P<href>[^"]+)">(?P<label>[^<]+)</a></li>'
)
_EXPECTED_LICENSE_CATEGORY_COUNT = 5


@dataclass(frozen=True, slots=True)
class AdamsCode:
    """One exact publisher-observed facet label or reference-category link."""

    resource_name: ResourceName
    use: ResourceUse
    publisher_label: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


def _identifier(value: str, kind: str, *, pin: AdamsSnapshotPin, acquired_sha256: str) -> ControlledIdentifier:
    return ControlledIdentifier(
        value=value,
        kind=kind,
        authority_uri=NRC_ADAMS_IDENTIFIER_AUTHORITY_URI,
        source_uri=pin.source.source_url,
        observed_at=pin.retrieved_at,
        effective_at=None,
        source_digest=acquired_sha256,
    )


def parse_aps_result_field_labels(acquired: AcquiredAdamsSource) -> tuple[AdamsCode, ...]:
    """Parse the exact APS result-detail field labels and their bound property keys."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")

    matches = list(_RESULT_FIELD_ROW.finditer(text))
    covered = "".join(match.group(0) for match in matches)
    if covered != text:
        raise AdamsSourceDriftError("APS result-field label excerpt no longer matches the reviewed row shape")
    if len(matches) != _EXPECTED_RESULT_FIELD_COUNT:
        raise AdamsSourceDriftError(
            f"APS result-field label count drift: expected {_EXPECTED_RESULT_FIELD_COUNT}, parsed {len(matches)}"
        )

    codes: list[AdamsCode] = []
    seen_labels: set[str] = set()
    seen_properties: set[str] = set()
    for match in matches:
        label = match.group("label")
        property_match = _PROPERTY_KEY.search(match.group("value_expr"))
        if not label.strip() or property_match is None:
            raise AdamsSourceDriftError("APS result-field row has an empty label or an unbound property key")
        property_key = property_match.group(1)
        if label in seen_labels or property_key in seen_properties:
            raise AdamsSourceDriftError(f"APS result-field label {label!r} or property {property_key!r} repeats")
        seen_labels.add(label)
        seen_properties.add(property_key)
        codes.append(
            AdamsCode(
                resource_name="apsResultFieldLabels",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    _identifier(label, "apsResultFieldLabel", pin=acquired.pin, acquired_sha256=acquired.sha256),
                    _identifier(
                        property_key,
                        "apsResultFieldPropertyKey",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


def parse_aps_library_facet_labels(acquired: AcquiredAdamsSource) -> tuple[AdamsCode, ...]:
    """Parse the exact APS library-facet checkbox labels and their form-control names."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")

    matches = list(_LIBRARY_FACET_ROW.finditer(text))
    covered = ",".join(match.group(0) for match in matches)
    if covered != text:
        raise AdamsSourceDriftError("APS library-facet label excerpt no longer matches the reviewed row shape")
    if len(matches) != _EXPECTED_LIBRARY_FACET_COUNT:
        raise AdamsSourceDriftError(
            f"APS library-facet label count drift: expected {_EXPECTED_LIBRARY_FACET_COUNT}, parsed {len(matches)}"
        )

    codes: list[AdamsCode] = []
    for match in matches:
        label = match.group("label")
        control = match.group("control")
        codes.append(
            AdamsCode(
                resource_name="apsLibraryFacetLabels",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    _identifier(label, "apsLibraryFacetLabel", pin=acquired.pin, acquired_sha256=acquired.sha256),
                    _identifier(
                        control,
                        "apsLibraryFacetControlName",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


def parse_docket_number_category_links(acquired: AcquiredAdamsSource) -> tuple[AdamsCode, ...]:
    """Parse the "Lists of Licenses and Docket Numbers" reference-category list."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")

    section = _LICENSE_LIST_SECTION.search(text)
    if section is None:
        raise AdamsSourceDriftError("Lists of Licenses and Docket Numbers section was not found in the expected shape")
    items = list(_LICENSE_LIST_ITEM.finditer(section.group("items")))
    covered = "".join(item.group(0) for item in items)
    if covered != section.group("items"):
        raise AdamsSourceDriftError("Lists of Licenses and Docket Numbers section contains an unrecognized row shape")
    if len(items) != _EXPECTED_LICENSE_CATEGORY_COUNT:
        raise AdamsSourceDriftError(
            f"docket/license category count drift: expected {_EXPECTED_LICENSE_CATEGORY_COUNT}, parsed {len(items)}"
        )

    codes: list[AdamsCode] = []
    seen_labels: set[str] = set()
    for item in items:
        label = item.group("label")
        href = item.group("href")
        if label in seen_labels:
            raise AdamsSourceDriftError(f"docket/license category {label!r} repeats")
        seen_labels.add(label)
        codes.append(
            AdamsCode(
                resource_name="helpReferencePage",
                use="deterministicMetadata",
                publisher_label=label,
                source_url=acquired.pin.source.source_url,
                identifiers=(
                    _identifier(
                        label,
                        "docketNumberCategoryLabel",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                    _identifier(
                        href,
                        "docketNumberCategoryReferenceUrl",
                        pin=acquired.pin,
                        acquired_sha256=acquired.sha256,
                    ),
                ),
            )
        )
    return tuple(codes)


# ---------------------------------------------------------------------------
# Identifier shapes: syntax rules and a small pinned sample, not enumerated
# code lists. ``matches`` is the validity check the entity-authority use case
# requires.
# ---------------------------------------------------------------------------

_DOCKET_NUMBER_SENTENCE = re.compile(
    r"<p>To search by a docket number, you must enter it in an 8-digit format, such as "
    r"(?P<example>\d{8}), in the Docket Number field in Web-based ADAMS Content Search or Advanced Search\. "
    r"You might see a docket number listed elsewhere as (?P<hyphenated>[\d-]+) or a variation of this, "
    r"but Web-based ADAMS will only accept the 8-digit format with no dashes in the Docket Number field\.</p>"
    r"<p>Examples for Docket (?P<prefix_a>\d+) \((?P<prefix_a_desc>[^)]+)\) and Docket (?P<prefix_b>\d+) "
    r"\((?P<prefix_b_desc>[^)]+)\) would be (?P<example_a>\d{8}) and (?P<example_b>\d{8})\.</p>"
)
_NUDOCS_SENTENCE = (
    "<p>If you have the Public Legacy Library accession number of the document you are looking for in "
    "the Public Library, use Web-based ADAMS Advanced Search and type the word NUDOCS followed by the "
    "10-digit Public Legacy Library accession number into the <em>Document/Report</em> Property field as "
    "shown in the below example. Be sure to have <em>Public Library</em> selected from the Libraries "
    "list.</p>"
)
_ACCESSION_LINK = re.compile(r'href="/docs/(?P<folder>ML\d{4})/(?P<accession>[A-Za-z0-9]+)\.pdf"')
_EXPECTED_ACCESSION_LINK_COUNT = 2


@dataclass(frozen=True, slots=True)
class AdamsIdentifierShape:
    """A documented or empirically observed identifier syntax rule.

    This is a schema/syntax-rule capture, not an enumerated code list: it
    exists so a caller can validate a candidate value's shape (``matches``)
    against a small pinned sample of real, source-observed values.
    """

    identifier_kind: IdentifierShapeKind
    pattern: str
    shape_basis: Literal["publisherDocumentedProse", "observedFromRealExamples"]
    explanation: str
    sample_values: tuple[str, ...]
    raw_notes: tuple[str, ...]
    source_url: str

    def __post_init__(self) -> None:
        if not self.identifier_kind or not self.pattern or not self.explanation:
            raise AdamsResourceError("identifier shape must declare identifier_kind, pattern, and explanation")
        try:
            compiled = re.compile(self.pattern)
        except re.error as error:
            raise AdamsResourceError(f"identifier shape pattern is not a valid regex: {error}") from error
        for sample in self.sample_values:
            if compiled.fullmatch(sample) is None:
                raise AdamsResourceError(f"identifier shape sample {sample!r} does not match its own pattern")

    def matches(self, value: str) -> bool:
        """Check one candidate value's syntax against this shape's pattern."""

        return re.fullmatch(self.pattern, value) is not None


def parse_docket_number_shape(acquired: AcquiredAdamsSource) -> AdamsIdentifierShape:
    """Parse the documented 8-digit Docket Number syntax from the FAQ prose."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")

    match = _DOCKET_NUMBER_SENTENCE.search(text)
    if match is None:
        raise AdamsSourceDriftError("docket-number format paragraph was not found in the expected shape")
    fields = match.groupdict()
    return AdamsIdentifierShape(
        identifier_kind="docketNumber",
        pattern=r"^\d{8}$",
        shape_basis="publisherDocumentedProse",
        explanation=(
            "Web-based ADAMS requires an 8-digit docket number with no dashes in the Docket Number "
            "field; the FAQ states a docket number may be shown elsewhere with a hyphen, but that "
            "hyphenated form is explicitly not accepted for search."
        ),
        sample_values=(fields["example"], fields["example_a"], fields["example_b"]),
        raw_notes=(
            f"hyphenated display variant observed for the first example: {fields['hyphenated']!r}",
            f"Docket {fields['prefix_a']} ({fields['prefix_a_desc']}) example: {fields['example_a']}",
            f"Docket {fields['prefix_b']} ({fields['prefix_b_desc']}) example: {fields['example_b']}",
        ),
        source_url=acquired.pin.source.source_url,
    )


def parse_legacy_library_accession_number_shape(acquired: AcquiredAdamsSource) -> AdamsIdentifierShape:
    """Parse the documented 10-digit Public Legacy Library accession-number syntax."""

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")

    if _NUDOCS_SENTENCE not in text:
        raise AdamsSourceDriftError(
            "Public Legacy Library accession-number paragraph was not found in the expected shape"
        )
    return AdamsIdentifierShape(
        identifier_kind="legacyLibraryAccessionNumber",
        pattern=r"^\d{10}$",
        shape_basis="publisherDocumentedProse",
        explanation=(
            "The FAQ documents searching Web-based ADAMS Advanced Search for a Public Legacy Library "
            "document by typing the literal token NUDOCS immediately followed by its 10-digit accession "
            "number into the Document/Report Property field, with Public Library selected from the "
            "Libraries list."
        ),
        # The FAQ shows its worked example only as a screenshot image, not as
        # selectable text, so no textual digit sample is captured here.
        sample_values=(),
        raw_notes=(
            "search token prefix observed in the FAQ text: 'NUDOCS' (immediately precedes the 10-digit number)",
        ),
        source_url=acquired.pin.source.source_url,
    )


def parse_current_accession_number_shape(acquired: AcquiredAdamsSource) -> AdamsIdentifierShape:
    """Infer the current ("ML") accession-number syntax from real linked examples.

    Neither page this module captures states this format in prose; the shape
    is derived only from the two accession numbers actually embedded in
    linked document filenames on the landing page.
    """

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")

    matches = list(_ACCESSION_LINK.finditer(text))
    if len(matches) != _EXPECTED_ACCESSION_LINK_COUNT:
        raise AdamsSourceDriftError(
            f"current accession-number example count drift: expected {_EXPECTED_ACCESSION_LINK_COUNT}, "
            f"parsed {len(matches)}"
        )
    samples = tuple(match.group("accession") for match in matches)
    return AdamsIdentifierShape(
        identifier_kind="currentAccessionNumber",
        pattern=r"^(?i:ML)\d{2}\d{3}(?:\d{4}|[A-Za-z]\d{3})$",
        shape_basis="observedFromRealExamples",
        explanation=(
            "Neither the landing page, the help-and-references page, nor the FAQ states the current "
            '("ML") accession-number format in prose. This pattern is inferred from two real example '
            "values embedded in linked document filenames on the landing page: an 'ML' prefix, a "
            "2-digit year, a 3-digit day-of-year, and either a 4-digit sequence or a 1-letter-plus-3-digit "
            "sequence."
        ),
        sample_values=samples,
        raw_notes=tuple(
            f"observed folder grouping: {match.group('folder')} for accession {match.group('accession')}"
            for match in matches
        ),
        source_url=acquired.pin.source.source_url,
    )


#: The one sentence on the System Notices page that states both accession
#: formats.  Matched byte-for-byte: a reworded notice is a different fact.
_FORMAT_NOTICE_SENTENCE = (
    'The structure of the accession numbers will change from "ML" followed by nine numbers '
    '(for example, ML100010001) to "ML" followed by eight numbers plus an alphabetic character '
    "in the sequence (for example, ML10001A001)."
)


def parse_accession_number_format_notice(acquired: AcquiredAdamsSource) -> AdamsIdentifierShape:
    """Parse the publisher-stated current ("ML") accession-number format.

    The ADAMS System Notices page announcing the December 2010 renumbering is
    the one captured NRC page that states the format in prose: "ML" followed
    by nine numbers before the change, "ML" followed by eight numbers plus an
    alphabetic character in the sequence after it.  The prose does not fix the
    letter's position; the pattern takes it from the publisher's own example
    (ML10001A001), which every observed value also matches.
    """

    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed NRC ADAMS source")
    text = payload.decode("utf-8")
    if text.count(_FORMAT_NOTICE_SENTENCE) != 1:
        raise AdamsSourceDriftError("accession-number format notice sentence was not found exactly once")
    return AdamsIdentifierShape(
        identifier_kind="currentAccessionNumber",
        pattern=r"^(?i:ML)(?:\d{9}|\d{5}[A-Za-z]\d{3})$",
        shape_basis="publisherDocumentedProse",
        explanation=(
            'The ADAMS System Notices page states both accession-number formats in prose: "ML" followed '
            "by nine numbers for documents added before December 15, 2010 (for example, ML100010001), and "
            '"ML" followed by eight numbers plus an alphabetic character in the sequence afterwards (for '
            "example, ML10001A001). The prose does not fix the alphabetic character's position; this "
            "pattern places it where the publisher's own example and every observed value put it."
        ),
        sample_values=("ML100010001", "ML10001A001"),
        raw_notes=(
            "publisher examples quoted verbatim from the December 2010 renumbering notice",
            "the pre-2010 nine-number form remains valid for documents added before December 15, 2010",
        ),
        source_url=acquired.pin.source.source_url,
    )


# ---------------------------------------------------------------------------
# Portfolio assembly and record-level validation.
# ---------------------------------------------------------------------------

NRC_ADAMS_PORTFOLIO_GAPS = (
    (
        'The ADAMS landing page, help-and-references page, and FAQ do not state the current ("ML") '
        "accession-number format in prose; the publisher statement lives on the ADAMS System Notices page "
        "announcing the December 2010 renumbering, captured and parsed here, and the landing-page "
        "derivation from real linked examples is retained as corroboration. The notice fixes the character "
        "count but not the alphabetic character's position, which is taken from the publisher's own example."
    ),
    (
        "The FAQ's docket-number and Public Legacy Library accession-number documentation describes the "
        "legacy Web-based ADAMS (WBA) interface; the ADAMS Public Search (APS) result-field and "
        "library-facet labels captured here instead come from the live APS application, because APS is now "
        "the primary public interface but does not publish an equivalent prose reference page of its own."
    ),
    (
        "The APS application bundle is served from a content-hashed filename that changes on every "
        "publisher deploy; the exact URL pinned here will not remain fetchable indefinitely, and a future "
        "audit must first re-discover the current bundle URL from https://adams-search.nrc.gov/home."
    ),
    (
        "The two APS captures are small, byte-exact excerpts of a much larger (1,578,086-byte) official "
        "JavaScript bundle, not the full official asset; the full bundle's own digest and length are "
        "recorded on each excerpt's snapshot pin for provenance, and the label set is exactly what those "
        "two excerpts observed, not a publisher-asserted complete enumeration of every APS search field."
    ),
    (
        "License Number is a confirmed APS result-field label, but none of the captured pages documents a "
        "license-number syntax; only the docket-number and accession-number shapes are captured here."
    ),
    (
        "The FAQ (last reviewed 2021-01-28) and the landing page (undated) report inconsistent PARS Library "
        "document counts (roughly 520,000 versus more than 3 million), evidencing that NRC's own public "
        "pages are not kept in sync with each other."
    ),
)


@dataclass(frozen=True, slots=True)
class NrcAdamsControlPortfolio:
    """The captured identifier shapes and small controlled lists, plus known gaps."""

    docket_number_shape: AdamsIdentifierShape
    legacy_library_accession_number_shape: AdamsIdentifierShape
    current_accession_number_shape: AdamsIdentifierShape
    docket_number_category_links: tuple[AdamsCode, ...]
    aps_result_field_labels: tuple[AdamsCode, ...]
    aps_library_facet_labels: tuple[AdamsCode, ...]
    gaps: tuple[str, ...]

    def by_result_field_label(self) -> dict[str, AdamsCode]:
        """Index the current APS result-field codes by their exact publisher label."""

        result: dict[str, AdamsCode] = {}
        for entry in self.aps_result_field_labels:
            matches = [identifier for identifier in entry.identifiers if identifier.kind == "apsResultFieldLabel"]
            if len(matches) != 1:
                raise AdamsSourceDriftError("APS result-field row must retain exactly one apsResultFieldLabel")
            result[matches[0].value] = entry
        return result


def assemble_nrc_adams_control_portfolio(
    *,
    docket_number_shape: AdamsIdentifierShape,
    legacy_library_accession_number_shape: AdamsIdentifierShape,
    current_accession_number_shape: AdamsIdentifierShape,
    docket_number_category_links: Sequence[AdamsCode],
    aps_result_field_labels: Sequence[AdamsCode],
    aps_library_facet_labels: Sequence[AdamsCode],
) -> NrcAdamsControlPortfolio:
    """Require every captured resource and retain the documented gaps."""

    if docket_number_shape.identifier_kind != "docketNumber":
        raise AdamsSourceDriftError("docket_number_shape must carry identifier_kind 'docketNumber'")
    if legacy_library_accession_number_shape.identifier_kind != "legacyLibraryAccessionNumber":
        raise AdamsSourceDriftError(
            "legacy_library_accession_number_shape must carry identifier_kind 'legacyLibraryAccessionNumber'"
        )
    if current_accession_number_shape.identifier_kind != "currentAccessionNumber":
        raise AdamsSourceDriftError(
            "current_accession_number_shape must carry identifier_kind 'currentAccessionNumber'"
        )
    if not docket_number_category_links or not aps_result_field_labels or not aps_library_facet_labels:
        raise AdamsSourceDriftError("NRC ADAMS control portfolio requires every captured resource to be non-empty")
    return NrcAdamsControlPortfolio(
        docket_number_shape=docket_number_shape,
        legacy_library_accession_number_shape=legacy_library_accession_number_shape,
        current_accession_number_shape=current_accession_number_shape,
        docket_number_category_links=tuple(docket_number_category_links),
        aps_result_field_labels=tuple(aps_result_field_labels),
        aps_library_facet_labels=tuple(aps_library_facet_labels),
        gaps=NRC_ADAMS_PORTFOLIO_GAPS,
    )


@dataclass(frozen=True, slots=True)
class ValidatedAdamsIdentifiers:
    """Identifier evidence retained from one candidate record."""

    docket_number: str | None
    legacy_accession_number: str | None
    current_accession_number: str | None
    aps_search_field: AdamsCode | None
    gaps: tuple[str, ...]


def validate_adams_identifiers(
    record: Mapping[str, object],
    portfolio: NrcAdamsControlPortfolio,
) -> ValidatedAdamsIdentifiers:
    """Validate the shape of any ADAMS identifiers a record supplies.

    Every field is optional: this module does not assert that a record must
    carry a docket number, an accession number, or a search field, only that
    whichever ones it does supply match the captured, source-observed syntax.
    """

    raw_docket = record.get("docket_number")
    docket_number: str | None = None
    if raw_docket is not None:
        if not isinstance(raw_docket, str) or not portfolio.docket_number_shape.matches(raw_docket):
            raise AdamsAssignmentError(f"docket_number does not match the documented 8-digit shape: {raw_docket!r}")
        docket_number = raw_docket

    raw_legacy = record.get("legacy_accession_number")
    legacy_accession_number: str | None = None
    if raw_legacy is not None:
        if not isinstance(raw_legacy, str) or not portfolio.legacy_library_accession_number_shape.matches(raw_legacy):
            raise AdamsAssignmentError(
                f"legacy_accession_number does not match the documented 10-digit shape: {raw_legacy!r}"
            )
        legacy_accession_number = raw_legacy

    raw_current = record.get("accession_number")
    current_accession_number: str | None = None
    if raw_current is not None:
        if not isinstance(raw_current, str) or not portfolio.current_accession_number_shape.matches(raw_current):
            raise AdamsAssignmentError(f"accession_number does not match the observed ML-number shape: {raw_current!r}")
        current_accession_number = raw_current

    raw_field = record.get("aps_search_field")
    aps_search_field: AdamsCode | None = None
    if raw_field is not None:
        if not isinstance(raw_field, str):
            raise AdamsAssignmentError("aps_search_field must be a string when present")
        aps_search_field = portfolio.by_result_field_label().get(raw_field)
        if aps_search_field is None:
            raise AdamsAssignmentError(f"unknown APS search field {raw_field!r}")

    return ValidatedAdamsIdentifiers(
        docket_number=docket_number,
        legacy_accession_number=legacy_accession_number,
        current_accession_number=current_accession_number,
        aps_search_field=aps_search_field,
        gaps=portfolio.gaps,
    )

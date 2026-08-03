"""Pinned GAO Congressional Review Act database search-facet import.

GAO's CRA database page (``/legal/other-legal-work/congressional-review-act``)
exposes three named search facets, visible directly in its own documented URL
(``?priority=all&processed=1&type=all``):

* ``priority`` -- the major/non-major rule flag GAO assigns on review.
* ``processed`` -- whether GAO has completed its review of the submission.
* ``type`` -- the record type shown (a rule submission, a report on a major
  rule, a legal coverage decision, or a rule disapproved by joint
  resolution).

Every facet value is a code GAO itself assigns and publishes as the literal
query-string value used to filter its own database; this module preserves
that exact value as identity and never mints a substitute. The catalog's
recommended role for this source is deterministic metadata, not
filer-selected evidence and not a subject vocabulary: nothing parsed here is
treated as a general subject concept.

GAO's CRA search page also renders per-row receipt and effective dates for
each submission. Those two fields are accepted here only as opaque,
already-formatted passthrough text -- this module never interprets them and
never computes, accepts, or stores a project-calculated CRA review window
(the statutory 60-day/legislative-day count is a project-owned, separately
versioned rule, out of scope for this source-facet import). Any rule
submission record that carries a review-window-shaped field is refused, not
silently dropped.

The search UI publishes no documented stable bulk API and no facet code-list
release identifier (confirmed in the catalog research evidence for this
source). A live fetch attempted at initial implementation time (2026-08-03)
returned an Akamai access-denied response (HTTP 403); that denial response is
kept on disk as ``gao-cra-access-denied-real-capture-2026-08-03.html``,
historical negative evidence that acquisition fails closed on a block page,
not a source of facet shape. Because that attempt failed, the original
pinned bytes (``GAO_CRA_FACETS_2026_08_03``) were a hand-built fixture
constructed to be faithful to the *documented, but unverified* Drupal
exposed-filter ``<select>``/``<option>`` shape -- a hypothesis, never a
confirmed capture.

A REAL page has since been captured through the project's Zyte transport
(2026-08-04, pinned as ``GAO_CRA_REAL_CAPTURE_2026_08_04``) and confirmed to
be the live CRA database page (title "Congressional Review Act | U.S. GAO"),
not a denial page. It falsifies the hypothesis: the real page renders ZERO
``<select>`` and ZERO ``<option>`` elements. The three facets are visible
only as the currently-selected filter state GAO's own client-side JavaScript
echoes back into the page's ``drupal-settings-json`` blob, at
``path.currentQuery``. ``parse_gao_cra_facets`` and its ``<select>``-based
fixture are therefore kept only as legacy strict-parser test coverage -- they
describe a plausible markup shape the real server HTML does not satisfy, not
a claim about how the live page actually renders. Use
``parse_gao_cra_real_page_echoed_query`` for the shape the real capture
actually confirms: it verifies the page's identity (title/heading anchor),
extracts the three facets' currently-echoed query values, and explicitly
refuses to enumerate the legal value list for any facet -- that list is
client-rendered and not present in any server HTML this module has
captured. Enumerating it is an open follow-up that requires a rendered-DOM
capture (a browser-executed snapshot taken after client-side JavaScript
renders the facet widgets).

Acquisition accepts a local exact capture or an injected fetcher. Importing
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
from types import MappingProxyType
from typing import Any, Literal, NoReturn, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.source_controlled_resource import (
    ResourceUse as PackageResourceUse,
)
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

GAO_CRA_PUBLISHER = "Government Accountability Office"
GAO_CRA_IDENTIFIER_AUTHORITY_URI = "https://www.gao.gov/"
GAO_CRA_HOSTS = frozenset({"gao.gov", "www.gao.gov"})
GAO_CRA_DATABASE_PATH = "/legal/other-legal-work/congressional-review-act"
GAO_CRA_DATABASE_URL = f"https://www.gao.gov{GAO_CRA_DATABASE_PATH}?priority=all&processed=1&type=all"
GAO_CRA_LANGUAGE = "en"
GAO_CRA_RESOURCE_ID = "gao-cra-database-facets-2026-08-03"

# Hand-built fixture bytes describing a hypothesized <select>-based shape,
# not a verified live gao.gov capture -- a real capture now exists and is
# pinned separately below as GAO_CRA_REAL_CAPTURE_2026_08_04; see the module
# docstring and the ``liveCaptureUnverified`` package gap below.
GAO_CRA_FACETS_2026_08_03_SHA256 = "sha256:f98e37c6c5a25c5448a9fb2f4effadcf98fff4252ef2f514102f9ee0fb344de9"
GAO_CRA_FACETS_2026_08_03_BYTE_LENGTH = 1_906
GAO_CRA_FACETS_2026_08_03_RETRIEVED_AT = "2026-08-03T00:00:00Z"

# A REAL gao.gov CRA database page, captured through the project's Zyte
# transport and confirmed to be the live page (title "Congressional Review
# Act | U.S. GAO"), not a denial page. It renders zero <select> and zero
# <option> elements; see parse_gao_cra_real_page_echoed_query.
GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256 = "sha256:d1a8ba0607dc3c8c9aff63fe98355f4a3c503252b31b8ae39e48632718b5b6e0"
GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH = 87_676
GAO_CRA_REAL_CAPTURE_2026_08_04_RETRIEVED_AT = "2026-08-04T00:12:00Z"

FacetName = Literal["priority", "processed", "type"]
ResourceUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_FACET_OPTION_VALUE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EXPECTED_FACET_NAMES: frozenset[FacetName] = frozenset({"priority", "processed", "type"})
# Identity anchors and extraction pattern for the REAL captured page shape,
# where the three facets never render as <select>/<option> markup -- they
# are echoed query parameters inside a drupal-settings JSON script tag.
_CRA_DATABASE_PAGE_HEADING = "Congressional Review Act"
_TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_HEADING = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_DRUPAL_SETTINGS_SCRIPT = re.compile(
    r'<script[^>]*data-drupal-selector="drupal-settings-json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_FACET_IDENTIFIER_KIND: Mapping[FacetName, str] = MappingProxyType(
    {
        "priority": "craPriorityFacetValue",
        "processed": "craProcessedFacetValue",
        "type": "craTypeFacetValue",
    }
)
# Observed verbatim from the real gao.gov WAF response captured while this
# module was implemented (an Akamai edge "Access Denied" block), plus the
# generic markers other RefSpec gao.gov adapters check for so a future vendor
# change still fails closed instead of packaging a block page.
_CHALLENGE_MARKERS = (
    b"<title>access denied</title>",
    b"errors.edgesuite.net",
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)
_ALLOWED_RECORD_FIELDS = frozenset({"priority", "processed", "type", "receivedDate", "effectiveDate"})
# Any unsupported field whose name looks like a computed CRA review window is
# refused with a distinct, explicit error rather than the generic unknown-
# field error, so the binding scope constraint ("source facets only") is
# self-documenting at the call site.
_REVIEW_WINDOW_FIELD_HINTS = ("window", "deadline", "calculated", "computed", "projected", "legislativeday")

_NOT_A_STABLE_BULK_API_GAP = MappingProxyType(
    {
        "kind": "noStableBulkApi",
        "reason": (
            "GAO's CRA database search page has no documented stable bulk API; "
            "this module captures only the exposed HTML facet controls "
            "(priority, processed, type), not a machine-readable listing "
            "endpoint or the underlying rule-submission row schema."
        ),
    }
)
_NO_FACET_RELEASE_GAP = MappingProxyType(
    {
        "kind": "publisherReleaseUnavailable",
        "reason": (
            "gao.gov publishes no facet code-list release date or revision "
            "identifier for this search form; retrieval time and exact source "
            "digest are the available revision pin."
        ),
    }
)
_LIVE_CAPTURE_UNVERIFIED_GAP = MappingProxyType(
    {
        "kind": "liveCaptureUnverified",
        "reason": (
            "This parser's own pinned bytes (GAO_CRA_FACETS_2026_08_03) are a "
            "hand-built fixture, not a verified live gao.gov capture: a live "
            "fetch attempted at implementation time (2026-08-03) returned an "
            "Akamai access-denied response (HTTP 403), so the fixture was "
            "built faithful to a hypothesized Drupal exposed-filter "
            "<select>/<option> shape. A real page has since been captured "
            "through the project's Zyte transport (2026-08-04) and is pinned "
            "separately as GAO_CRA_REAL_CAPTURE_2026_08_04; it renders zero "
            "<select> and zero <option> elements, so the hypothesis this "
            "parser encodes is one the real gao.gov server HTML does not "
            "satisfy. Use parse_gao_cra_real_page_echoed_query for the shape "
            "confirmed against the real capture; this <select>-based parser "
            "and its fixture are retained only as legacy strict-parser test "
            "coverage."
        ),
    }
)
_REVIEW_WINDOW_OUT_OF_SCOPE_GAP = MappingProxyType(
    {
        "kind": "reviewWindowOutOfScope",
        "reason": (
            "This module packages only GAO's own source-published facets and "
            "opaque receipt/effective date passthrough fields; it never "
            "accepts or derives a project-calculated CRA review-window value."
        ),
    }
)
_FACET_VALUE_ENUMERATION_REQUIRES_RENDERED_DOM_GAP = MappingProxyType(
    {
        "kind": "facetValueEnumerationRequiresRenderedDom",
        "reason": (
            "The real gao.gov CRA database page renders zero <select> and "
            "zero <option> elements in server HTML; the three facets "
            "(priority, processed, type) are visible only as the "
            "currently-selected filter state echoed back into the page's "
            "drupal-settings JSON, at path.currentQuery. Enumerating the "
            "full set of legal values each facet accepts is an open "
            "follow-up that requires a rendered-DOM capture (a "
            "browser-executed snapshot taken after client-side JavaScript "
            "renders the facet widgets), which this module does not "
            "perform; the 10 option codes this module's legacy <select>-"
            "based parser reports are a hypothesis, not values confirmed "
            "against a real capture."
        ),
    }
)
GAO_CRA_PACKAGE_GAPS = (
    _NOT_A_STABLE_BULK_API_GAP,
    _NO_FACET_RELEASE_GAP,
    _LIVE_CAPTURE_UNVERIFIED_GAP,
    _REVIEW_WINDOW_OUT_OF_SCOPE_GAP,
    _FACET_VALUE_ENUMERATION_REQUIRES_RENDERED_DOM_GAP,
)
GAO_CRA_KNOWN_GAPS = tuple(gap["reason"] for gap in GAO_CRA_PACKAGE_GAPS)

# Gaps recorded against the REAL captured page's echoed-query parse path
# (parse_gao_cra_real_page_echoed_query). This omits liveCaptureUnverified
# (the real capture IS verified) but keeps facetValueEnumerationRequires-
# RenderedDom, since the real page still cannot supply a facet value list.
GAO_CRA_REAL_PAGE_GAPS = (
    _NOT_A_STABLE_BULK_API_GAP,
    _NO_FACET_RELEASE_GAP,
    _REVIEW_WINDOW_OUT_OF_SCOPE_GAP,
    _FACET_VALUE_ENUMERATION_REQUIRES_RENDERED_DOM_GAP,
)
GAO_CRA_REAL_PAGE_KNOWN_GAPS = tuple(gap["reason"] for gap in GAO_CRA_REAL_PAGE_GAPS)


class GAOCRAFacetError(ValueError):
    """Base class for GAO CRA facet import failures."""


class GAOCRAAcquisitionError(GAOCRAFacetError):
    """Exact official source bytes could not be acquired safely."""


class GAOCRASourceDriftError(GAOCRAFacetError):
    """The captured CRA database page no longer matches the reviewed structure."""


class GAOCRAAssignmentError(GAOCRAFacetError):
    """A rule submission record carries an unknown or unsupported facet field."""


class GAOCRAScopeError(GAOCRAFacetError):
    """A caller attempted to attach an out-of-scope, project-calculated field."""


class GAOCRAFacetEnumerationUnavailableError(GAOCRAFacetError):
    """A caller asked for a facet's legal value list from a static server capture.

    The real gao.gov CRA database page renders zero ``<select>`` and zero
    ``<option>`` elements; only the currently-echoed query value is visible
    in server HTML. Enumerating the legal value list requires a rendered-DOM
    capture, which this module does not perform.
    """


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_source_url(source_url: str) -> None:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname not in GAO_CRA_HOSTS:
        raise GAOCRAAcquisitionError("source_url must be an official HTTPS gao.gov URL")
    if parsed.username is not None or parsed.password is not None:
        raise GAOCRAAcquisitionError("source_url must not contain credentials")
    if parsed.path != GAO_CRA_DATABASE_PATH:
        raise GAOCRAAcquisitionError(
            f"source_url must address the CRA database search page ({GAO_CRA_DATABASE_PATH}); "
            "other gao.gov pages are out of scope for this facet capture"
        )


@dataclass(frozen=True, slots=True)
class GAOCRAFacetSnapshotPin:
    """Expected identity of one exact captured CRA database page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _validate_source_url(self.source_url)
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GAOCRAAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GAOCRAAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise GAOCRAAcquisitionError("retrieved_at must not be empty")


GAO_CRA_FACETS_2026_08_03 = GAOCRAFacetSnapshotPin(
    source_url=GAO_CRA_DATABASE_URL,
    retrieved_at=GAO_CRA_FACETS_2026_08_03_RETRIEVED_AT,
    expected_sha256=GAO_CRA_FACETS_2026_08_03_SHA256,
    expected_byte_length=GAO_CRA_FACETS_2026_08_03_BYTE_LENGTH,
)

GAO_CRA_REAL_CAPTURE_2026_08_04 = GAOCRAFacetSnapshotPin(
    source_url=GAO_CRA_DATABASE_URL,
    retrieved_at=GAO_CRA_REAL_CAPTURE_2026_08_04_RETRIEVED_AT,
    expected_sha256=GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256,
    expected_byte_length=GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH,
)


@dataclass(frozen=True, slots=True)
class FetchedGAOCRAPage:
    """Provider-independent response returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class GAOCRAPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedGAOCRAPage:
        """Fetch one official CRA database page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredGAOCRAFacetPage:
    """One verified CRA database page in the content-addressed source store."""

    pin: GAOCRAFacetSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise GAOCRASourceDriftError(
            "gao.gov returned an access-denied or challenge page instead of the CRA database page"
        )
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise GAOCRASourceDriftError("gao.gov CRA database capture is not an HTML document")


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in GAO_CRA_HOSTS:
        raise GAOCRAAcquisitionError("fetcher resolved_url must remain on official HTTPS gao.gov")
    if parsed.username is not None or parsed.password is not None:
        raise GAOCRAAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_fetched_page(fetched: FetchedGAOCRAPage, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise GAOCRAAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise GAOCRASourceDriftError(f"gao.gov CRA database page content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: GAOCRAFacetSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise GAOCRASourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise GAOCRASourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: GAOCRAFacetSnapshotPin) -> AcquiredGAOCRAFacetPage:
    if path.is_symlink() or not path.is_file():
        raise GAOCRAAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached CRA database page",
    )
    return AcquiredGAOCRAFacetPage(
        pin=pin,
        path=path,
        source_url=pin.source_url,
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
    pin: GAOCRAFacetSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGAOCRAFacetPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} CRA database page",
    )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".acquire-", suffix=".tmp", dir=final_path.parent)
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
        return AcquiredGAOCRAFacetPage(
            pin=pin,
            path=final_path,
            source_url=pin.source_url,
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


def acquire_gao_cra_facets_page(
    pin: GAOCRAFacetSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: GAOCRAPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredGAOCRAFacetPage:
    """Acquire one exact CRA database page from cache, a local capture, or an injected fetcher."""

    if timeout_seconds <= 0:
        raise GAOCRAAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise GAOCRAAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / "congressional-review-act.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GAOCRAAcquisitionError(f"local CRA database source is not a regular file: {local_path}")
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
        raise GAOCRAAcquisitionError("CRA database page is not cached; provide source_path or an injected fetcher")

    fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=pin.source_url)
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


class _CRAFacetFormParser(HTMLParser):
    """Collect only the named exposed-filter ``<select>`` facets this module trusts.

    Real Drupal-rendered option markup normally closes every ``<option>``
    explicitly, but this parser also tolerates an omitted closing tag (a
    legal HTML5 pattern) by implicitly closing the previous option before
    starting a new one, or before its enclosing ``<select>`` closes.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.facets: dict[str, list[tuple[str, str, bool]]] = {}
        self.facet_open_count: dict[str, int] = {}
        self._current_facet: str | None = None
        self._current_option: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs))
        if tag == "option":
            self._close_option()

    def handle_endtag(self, tag: str) -> None:
        if tag == "option":
            self._close_option()
        elif tag == "select":
            self._close_option()
            self._current_facet = None

    def handle_data(self, data: str) -> None:
        if self._current_option is not None:
            self._current_option["text"].append(data)

    def _open(self, tag: str, attr_map: dict[str, str | None]) -> None:
        if tag == "select":
            name = attr_map.get("name")
            if name in _EXPECTED_FACET_NAMES:
                self.facet_open_count[name] = self.facet_open_count.get(name, 0) + 1
                if self.facet_open_count[name] > 1:
                    raise GAOCRASourceDriftError(f"facet <select name={name!r}> appears more than once")
                self._current_facet = name
                self.facets[name] = []
            else:
                self._current_facet = None
        elif tag == "option" and self._current_facet is not None:
            self._close_option()
            value = attr_map.get("value")
            if value is None:
                raise GAOCRASourceDriftError(f"facet {self._current_facet!r} has an <option> without a value")
            self._current_option = {
                "value": value,
                "text": [],
                "default": "selected" in attr_map,
            }

    def _close_option(self) -> None:
        if self._current_option is None or self._current_facet is None:
            return
        label = _normalize_text(self._current_option["text"])
        self.facets[self._current_facet].append((self._current_option["value"], label, self._current_option["default"]))
        self._current_option = None


@dataclass(frozen=True, slots=True)
class GAOCRAFacetCode:
    """One exact facet option value plus its label and identifiers."""

    facet_name: FacetName
    use: ResourceUse
    publisher_label: str
    is_default: bool
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ParsedGAOCRAFacets:
    """The three parsed, digest-pinned CRA database search facets."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    facets: Mapping[FacetName, tuple[GAOCRAFacetCode, ...]]
    gaps: tuple[str, ...]

    def by_value(self, facet_name: FacetName) -> dict[str, GAOCRAFacetCode]:
        """Index one facet's exact option value while retaining every field."""

        if facet_name not in self.facets:
            raise GAOCRASourceDriftError(f"unknown CRA facet {facet_name!r}")
        result: dict[str, GAOCRAFacetCode] = {}
        for entry in self.facets[facet_name]:
            matches = [
                identifier for identifier in entry.identifiers if identifier.kind == _FACET_IDENTIFIER_KIND[facet_name]
            ]
            if len(matches) != 1:
                raise GAOCRASourceDriftError(f"{facet_name} option must retain exactly one facet-value identifier")
            result[matches[0].value] = entry
        return result


def _read_acquired_payload(page: AcquiredGAOCRAFacetPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed CRA database page")
    return payload


def parse_gao_cra_facets(page: AcquiredGAOCRAFacetPage) -> ParsedGAOCRAFacets:
    """Parse the three exact search facets from one digest-pinned CRA database page."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GAOCRASourceDriftError("gao.gov CRA database page is not UTF-8") from error

    parser = _CRAFacetFormParser()
    try:
        parser.feed(decoded)
        parser.close()
    except GAOCRAFacetError:
        raise
    except Exception as error:
        raise GAOCRASourceDriftError("gao.gov CRA database page is malformed HTML") from error

    missing = _EXPECTED_FACET_NAMES - set(parser.facets)
    if missing:
        raise GAOCRASourceDriftError(f"CRA database page is missing facet(s) {sorted(missing)}")

    facets: dict[FacetName, tuple[GAOCRAFacetCode, ...]] = {}
    for facet_name in sorted(_EXPECTED_FACET_NAMES):
        options = parser.facets[facet_name]
        if not options:
            raise GAOCRASourceDriftError(f"facet {facet_name!r} has no options")
        codes: list[GAOCRAFacetCode] = []
        seen_values: set[str] = set()
        default_count = 0
        for value, label, is_default in options:
            if _FACET_OPTION_VALUE.fullmatch(value) is None:
                raise GAOCRASourceDriftError(f"facet {facet_name!r} option value {value!r} has an unrecognized shape")
            if not label:
                raise GAOCRASourceDriftError(f"facet {facet_name!r} option {value!r} has an empty label")
            if value in seen_values:
                raise GAOCRASourceDriftError(f"facet {facet_name!r} repeats option value {value!r}")
            seen_values.add(value)
            default_count += 1 if is_default else 0
            codes.append(
                GAOCRAFacetCode(
                    facet_name=facet_name,
                    use="deterministicMetadata",
                    publisher_label=label,
                    is_default=is_default,
                    source_url=page.pin.source_url,
                    identifiers=(
                        ControlledIdentifier(
                            value=value,
                            kind=_FACET_IDENTIFIER_KIND[facet_name],
                            authority_uri=GAO_CRA_IDENTIFIER_AUTHORITY_URI,
                            source_uri=page.pin.source_url,
                            observed_at=page.pin.retrieved_at,
                            effective_at=None,
                            source_digest=page.sha256,
                        ),
                    ),
                )
            )
        if default_count > 1:
            raise GAOCRASourceDriftError(f"facet {facet_name!r} declares more than one default option")
        facets[facet_name] = tuple(codes)

    return ParsedGAOCRAFacets(
        source_url=page.pin.source_url,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        facets=MappingProxyType(facets),
        gaps=GAO_CRA_KNOWN_GAPS,
    )


@dataclass(frozen=True, slots=True)
class ParsedGAOCRAEchoedFacetQuery:
    """The three facets' currently-echoed query values from a REAL captured page.

    This is read directly from the real gao.gov CRA database page's
    ``drupal-settings-json`` blob, at ``path.currentQuery`` -- the *only*
    place the three facets appear in that page's server HTML. It captures
    only the currently-selected filter state GAO's own client-side
    JavaScript echoes back; it is never an enumeration of the legal values
    each facet accepts. The real page renders zero ``<select>`` and zero
    ``<option>`` elements, so any list of legal facet values is
    client-rendered and not present here -- call ``available_facet_values``
    for the explicit refusal.
    """

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    echoed_query: Mapping[FacetName, str]
    gaps: tuple[str, ...]

    def available_facet_values(self, facet_name: FacetName) -> NoReturn:
        """Refuse to enumerate the legal value list for one facet.

        This static server capture never carries the legal value list for
        any facet -- only the currently-echoed query value. Enumerating the
        full list GAO accepts (e.g., every ``priority`` code) requires a
        rendered-DOM capture (a browser-executed snapshot taken after
        client-side JavaScript renders the facet widgets), which this
        module does not perform. Always raises
        ``GAOCRAFacetEnumerationUnavailableError``.
        """

        if facet_name not in self.echoed_query:
            raise GAOCRASourceDriftError(f"unknown CRA facet {facet_name!r}")
        raise GAOCRAFacetEnumerationUnavailableError(
            f"cannot enumerate legal values for CRA facet {facet_name!r} from a static "
            "server-rendered capture; the real gao.gov CRA database page renders zero "
            "<select> and zero <option> elements, only this facet's currently echoed "
            "query value; enumerating the full legal value list requires a rendered-DOM "
            "capture"
        )


def parse_gao_cra_real_page_echoed_query(page: AcquiredGAOCRAFacetPage) -> ParsedGAOCRAEchoedFacetQuery:
    """Parse the three facets' echoed query values from a REAL captured CRA database page.

    Unlike ``parse_gao_cra_facets`` (which parses the hand-built, hypothesized
    ``<select>``/``<option>`` shape), this function parses the shape
    confirmed against a real page captured through the project's Zyte
    transport: the three facets never render as ``<select>`` controls in
    server HTML at all. They are visible only as the filter state GAO's own
    client-side JavaScript echoes back into the page's
    ``drupal-settings-json`` blob, at ``path.currentQuery``.

    This function confirms page identity via the ``<title>`` and ``<h1>``
    anchors before trusting any extracted values, and it deliberately does
    not -- and cannot -- enumerate the legal values each facet accepts; see
    ``ParsedGAOCRAEchoedFacetQuery.available_facet_values``.
    """

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GAOCRASourceDriftError("gao.gov CRA database page is not UTF-8") from error

    title_match = _TITLE_TAG.search(decoded)
    if title_match is None or _CRA_DATABASE_PAGE_HEADING not in _normalize_text([title_match.group(1)]):
        raise GAOCRASourceDriftError("gao.gov CRA database page <title> does not identify the CRA database page")
    heading_match = _H1_HEADING.search(decoded)
    if heading_match is None or _normalize_text([heading_match.group(1)]) != _CRA_DATABASE_PAGE_HEADING:
        raise GAOCRASourceDriftError(
            "gao.gov CRA database page is missing its 'Congressional Review Act' <h1> heading anchor"
        )

    settings_match = _DRUPAL_SETTINGS_SCRIPT.search(decoded)
    if settings_match is None:
        raise GAOCRASourceDriftError(
            "gao.gov CRA database page is missing its drupal-settings-json script; "
            "cannot extract the echoed facet query"
        )
    try:
        settings = json.loads(settings_match.group(1))
    except json.JSONDecodeError as error:
        raise GAOCRASourceDriftError("gao.gov CRA database page drupal-settings JSON is malformed") from error

    path_settings = settings.get("path") if isinstance(settings, dict) else None
    current_query = path_settings.get("currentQuery") if isinstance(path_settings, dict) else None
    if not isinstance(current_query, dict):
        raise GAOCRASourceDriftError("gao.gov CRA database page drupal-settings JSON is missing path.currentQuery")

    echoed: dict[FacetName, str] = {}
    for facet_name in sorted(_EXPECTED_FACET_NAMES):
        value = current_query.get(facet_name)
        if not isinstance(value, str) or not value:
            raise GAOCRASourceDriftError(
                f"gao.gov CRA database page currentQuery is missing echoed facet {facet_name!r}"
            )
        echoed[facet_name] = value

    return ParsedGAOCRAEchoedFacetQuery(
        source_url=page.pin.source_url,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        echoed_query=MappingProxyType(echoed),
        gaps=GAO_CRA_REAL_PAGE_KNOWN_GAPS,
    )


@dataclass(frozen=True, slots=True)
class GAOCRAFacetAssignment:
    """A rule-submission facet value validated against the exact source snapshot."""

    source_field: str
    publisher_label: str
    use: ResourceUse
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool


@dataclass(frozen=True, slots=True)
class ValidatedGAOCRARuleSubmissionFacets:
    """Facet evidence retained from one CRA rule-submission record.

    ``received_date`` and ``effective_date`` are opaque passthrough text --
    this module never interprets them into a computed review window.
    """

    priority: GAOCRAFacetAssignment
    processed: GAOCRAFacetAssignment
    rule_type: GAOCRAFacetAssignment
    received_date: str | None
    effective_date: str | None
    gaps: tuple[str, ...]


def _assignment(code: GAOCRAFacetCode, source_field: str) -> GAOCRAFacetAssignment:
    return GAOCRAFacetAssignment(
        source_field=source_field,
        publisher_label=code.publisher_label,
        use=code.use,
        identifiers=code.identifiers,
        is_general_subject_concept=code.is_general_subject_concept,
    )


def _looks_like_review_window_field(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(hint in lowered for hint in _REVIEW_WINDOW_FIELD_HINTS)


def _required_facet(
    record: Mapping[str, object],
    parsed: ParsedGAOCRAFacets,
    field: FacetName,
) -> GAOCRAFacetAssignment:
    raw_value = record.get(field)
    if not isinstance(raw_value, str):
        raise GAOCRAAssignmentError(f"CRA rule submission record must carry a string {field!r} facet value")
    code = parsed.by_value(field).get(raw_value)
    if code is None:
        raise GAOCRAAssignmentError(f"unknown CRA {field} facet value {raw_value!r}")
    return _assignment(code, field)


def _optional_date(record: Mapping[str, object], field: str) -> str | None:
    raw_value = record.get(field)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise GAOCRAAssignmentError(f"CRA rule submission {field} must be non-empty text when present")
    return raw_value


def validate_cra_rule_submission_facets(
    record: Mapping[str, object],
    parsed: ParsedGAOCRAFacets,
) -> ValidatedGAOCRARuleSubmissionFacets:
    """Validate exact source facets retained by one CRA rule-submission record.

    ``receivedDate`` and ``effectiveDate`` pass through unparsed. Any field
    that is not one of GAO's own facets or these two passthrough dates is
    refused; a field that looks like a project-calculated CRA review window
    is refused with an explicit, distinct scope error rather than treated as
    an ordinary unknown field.
    """

    unknown_fields = set(record) - _ALLOWED_RECORD_FIELDS
    if unknown_fields:
        review_window_fields = sorted(field for field in unknown_fields if _looks_like_review_window_field(field))
        if review_window_fields:
            raise GAOCRAScopeError(
                f"CRA rule submission record carries out-of-scope project-calculated review window "
                f"field(s) {review_window_fields}; this module packages only GAO's source-published "
                "facets and opaque receipt/effective date passthrough, never a project-computed window"
            )
        raise GAOCRAAssignmentError(f"CRA rule submission record has unsupported field(s) {sorted(unknown_fields)}")

    return ValidatedGAOCRARuleSubmissionFacets(
        priority=_required_facet(record, parsed, "priority"),
        processed=_required_facet(record, parsed, "processed"),
        rule_type=_required_facet(record, parsed, "type"),
        received_date=_optional_date(record, "receivedDate"),
        effective_date=_optional_date(record, "effectiveDate"),
        gaps=GAO_CRA_KNOWN_GAPS,
    )


def _observation(parsed: ParsedGAOCRAFacets, code: GAOCRAFacetCode, ordinal: int) -> dict[str, Any]:
    identifier = code.identifiers[0]
    source_path = f"form.select[name={code.facet_name}].option[{ordinal}]"
    return {
        "id": (f"urn:ref:source-observation:{GAO_CRA_RESOURCE_ID}:{identifier.kind}:{identifier.value}"),
        "sourceArtifact": parsed.source_url,
        "sourcePath": source_path,
        "sourceOrdinal": ordinal,
        "labels": [
            {
                "value": code.publisher_label,
                "language": GAO_CRA_LANGUAGE,
                "role": "preferred",
            }
        ],
        "identifiers": [
            {
                "value": identifier.value,
                "kind": identifier.kind,
                "authorityUri": identifier.authority_uri,
                "sourceUri": identifier.source_uri,
                "sourcePath": source_path,
                "observedAt": identifier.observed_at,
                "sourceDigest": identifier.source_digest,
            }
        ],
        "eligibleUses": [cast(PackageResourceUse, code.use)],
        "conceptIdentityClaimed": False,
    }


def build_gao_cra_facets_package(
    page: AcquiredGAOCRAFacetPage,
    parsed: ParsedGAOCRAFacets,
) -> SourceControlledResourceBundle:
    """Package the three exact CRA database facets as a development-only controlled code list.

    This never promotes the result into a concept scheme: every observation's
    ``eligibleUses`` stays ``deterministicMetadata``, ``conceptIdentityClaimed``
    stays false, and ``candidateUseAuthorized`` stays false pending a verified
    live capture (see the ``liveCaptureUnverified`` gap).
    """

    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise GAOCRASourceDriftError("CRA database page package source differs from its acquired pin")
    if parsed.source_sha256 != page.sha256:
        raise GAOCRASourceDriftError("parsed CRA database page and acquired page digests differ")
    if parsed.source_url != page.pin.source_url:
        raise GAOCRASourceDriftError("parsed CRA database page source_url differs from its acquired pin")

    observations = tuple(
        _observation(parsed, code, ordinal)
        for facet_name in sorted(parsed.facets)
        for ordinal, code in enumerate(parsed.facets[facet_name])
    )
    return build_source_controlled_resource_bundle(
        resource_id=GAO_CRA_RESOURCE_ID,
        title="GAO Congressional Review Act database search facets",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=parsed.retrieved_at,
        candidate_use_authorized=False,
        observations=observations,
        source_artifacts={parsed.source_url: payload},
        gaps=GAO_CRA_PACKAGE_GAPS,
    )


__all__ = [
    "GAO_CRA_DATABASE_PATH",
    "GAO_CRA_DATABASE_URL",
    "GAO_CRA_FACETS_2026_08_03",
    "GAO_CRA_FACETS_2026_08_03_BYTE_LENGTH",
    "GAO_CRA_FACETS_2026_08_03_RETRIEVED_AT",
    "GAO_CRA_FACETS_2026_08_03_SHA256",
    "GAO_CRA_HOSTS",
    "GAO_CRA_IDENTIFIER_AUTHORITY_URI",
    "GAO_CRA_KNOWN_GAPS",
    "GAO_CRA_LANGUAGE",
    "GAO_CRA_PACKAGE_GAPS",
    "GAO_CRA_PUBLISHER",
    "GAO_CRA_REAL_CAPTURE_2026_08_04",
    "GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH",
    "GAO_CRA_REAL_CAPTURE_2026_08_04_RETRIEVED_AT",
    "GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256",
    "GAO_CRA_REAL_PAGE_GAPS",
    "GAO_CRA_REAL_PAGE_KNOWN_GAPS",
    "GAO_CRA_RESOURCE_ID",
    "AcquiredGAOCRAFacetPage",
    "AcquisitionMode",
    "FacetName",
    "FetchedGAOCRAPage",
    "GAOCRAAcquisitionError",
    "GAOCRAAssignmentError",
    "GAOCRAFacetAssignment",
    "GAOCRAFacetCode",
    "GAOCRAFacetEnumerationUnavailableError",
    "GAOCRAFacetError",
    "GAOCRAFacetSnapshotPin",
    "GAOCRAPageFetcher",
    "GAOCRAScopeError",
    "GAOCRASourceDriftError",
    "ParsedGAOCRAEchoedFacetQuery",
    "ParsedGAOCRAFacets",
    "ResourceUse",
    "ValidatedGAOCRARuleSubmissionFacets",
    "acquire_gao_cra_facets_page",
    "build_gao_cra_facets_package",
    "parse_gao_cra_facets",
    "parse_gao_cra_real_page_echoed_query",
    "sha256_digest",
    "validate_cra_rule_submission_facets",
]

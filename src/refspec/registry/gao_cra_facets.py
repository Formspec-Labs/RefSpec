"""Pinned GAO Congressional Review Act database search-facet import.

GAO's actual ``Search Database of Rules`` page is server-rendered and
publishes two radio groups directly in its HTML: ``priority`` and ``type``.
The six literal query values are preserved as deterministic filing metadata;
none are promoted to general subject concepts. ``processed=1`` occurs in
GAO's own query string and Drupal settings but is not a visible search facet,
so this module does not invent a code list for it.

The exact page was captured through the project's Zyte transport on
2026-08-04 and is pinned as ``GAO_CRA_REAL_CAPTURE_2026_08_04``. The earlier
``GAO_CRA_FACETS_2026_08_03`` select-shaped fixture is retained only as
historical parser evidence and cannot be packaged. GAO exposes no documented
bulk API; public GitHub implementations likewise scrape this page and its
``fedrules/{control_number}`` detail pages.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection, and package generation accepts
only the verified real-page digest.
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

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse as PackageResourceUse,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

GAO_CRA_PUBLISHER = "Government Accountability Office"
GAO_CRA_IDENTIFIER_AUTHORITY_URI = "https://www.gao.gov/"
GAO_CRA_HOSTS = frozenset({"gao.gov", "www.gao.gov"})
GAO_CRA_OVERVIEW_PATH = "/legal/other-legal-work/congressional-review-act"
GAO_CRA_OVERVIEW_URL = f"https://www.gao.gov{GAO_CRA_OVERVIEW_PATH}?priority=all&processed=1&type=all"
GAO_CRA_DATABASE_PATH = "/legal/congressional-review-act/search-database-of-rules"
GAO_CRA_DATABASE_URL = f"https://www.gao.gov{GAO_CRA_DATABASE_PATH}?priority=all&processed=1&type=all"
GAO_CRA_LANGUAGE = "en"
GAO_CRA_RESOURCE_ID = "gao-cra-database-facets-2026-08-04"

# Hand-built fixture bytes describing a hypothesized <select>-based shape,
# not a verified live gao.gov capture. It is retained only as historical
# negative evidence and cannot be packaged.
GAO_CRA_FACETS_2026_08_03_SHA256 = "sha256:f98e37c6c5a25c5448a9fb2f4effadcf98fff4252ef2f514102f9ee0fb344de9"
GAO_CRA_FACETS_2026_08_03_BYTE_LENGTH = 1_906
GAO_CRA_FACETS_2026_08_03_RETRIEVED_AT = "2026-08-03T00:00:00Z"

# A REAL gao.gov CRA database page, captured through the project's Zyte
# transport and confirmed to be the live Search Database of Rules page, not a
# denial page. It server-renders the two public facets as radio groups.
GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256 = "sha256:50c6a5a94627a09539ddfb991397a22e257e2d1ec1f25e1206be5214322d9c12"
GAO_CRA_REAL_CAPTURE_2026_08_04_BYTE_LENGTH = 130_944
GAO_CRA_REAL_CAPTURE_2026_08_04_RETRIEVED_AT = "2026-08-04T04:35:23Z"

# GAO's own blank "Submission of Federal Rules Under the Congressional
# Review Act" form (the "11/17/23" edition footer on the PDF page itself),
# captured through the project's Zyte transport. This PDF is reference-only
# provenance for the vocabulary constants below -- it is never fetched
# through the acquisition pipeline and never parsed at runtime, the same way
# treasury_tas_fast_book.py pins its Component TAS-BETC flyer.
GAO_CRA_BLANK_FORM_2023_11_URL = "https://www.gao.gov/assets/2023-11/Blank%20CRA%20Form-Updated.pdf"
GAO_CRA_BLANK_FORM_2023_11_SHA256 = "sha256:4dc381d7305111a92c9cc1334e6e523fa0c3f719518f6784145b91e83a591d9d"
GAO_CRA_BLANK_FORM_2023_11_BYTE_LENGTH = 111_887
GAO_CRA_BLANK_FORM_2023_11_RETRIEVED_AT = "2026-08-04T00:55:00Z"

# Item 5 of the blank form ("Major Rule" / "Non-major Rule"), publisher-
# stated exactly as printed.
CRA_RULE_TYPES: tuple[str, ...] = ("Major Rule", "Non-major Rule")
# Item 8 of the blank form ("Priority of Regulation (fill in one)"),
# publisher-stated exactly as printed, in the form's own reading order.
CRA_PRIORITY_LEVELS: tuple[str, ...] = (
    "Economically Significant",
    "Significant",
    "Substantive, Nonsignificant",
    "Routine and Frequent",
    "Informational/Administrative/Other",
)

FacetName = Literal["priority", "processed", "type"]
ResourceUse = Literal["deterministicMetadata"]
AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_FACET_OPTION_VALUE = re.compile(r"^[A-Za-z0-9]+(?:[ /-][A-Za-z0-9]+)*$")
_EXPECTED_FACET_NAMES: frozenset[FacetName] = frozenset({"priority", "type"})
_LEGACY_FACET_NAMES: frozenset[FacetName] = frozenset({"priority", "processed", "type"})
# Identity anchors and extraction pattern for the real page's selected query
# values in its Drupal settings. Full enumeration uses the radio-form parser.
_CRA_DATABASE_PAGE_HEADING = "Search Database of Rules"
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
_ALLOWED_RECORD_FIELDS = frozenset({"priority", "type", "receivedDate", "effectiveDate"})
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
            "(priority and type), not a machine-readable listing "
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
            "<select>/<option> shape. GAO's actual Search Database of Rules "
            "page has since been captured through Zyte and is pinned as "
            "GAO_CRA_REAL_CAPTURE_2026_08_04. It server-renders radio groups "
            "for priority and type. This select-shaped fixture remains only "
            "as historical negative evidence and cannot be packaged."
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
            "zero <option> elements in server HTML; the three search-page "
            "facets (priority, processed, type) are visible only as the "
            "currently-selected filter state echoed back into the page's "
            "drupal-settings JSON, at path.currentQuery. The exhaustive "
            "query-string slug list each search-page facet's own <select> "
            "would offer is still unknown and still requires a "
            "rendered-DOM capture (a browser-executed snapshot taken after "
            "client-side JavaScript renders the facet widgets), which this "
            "module does not perform. That gap is narrower than it was, "
            "though: the underlying facet VOCABULARIES are no longer a "
            "guess -- GAO's own blank CRA submission form "
            "publisher-documents the rule-type vocabulary ('Major Rule' / "
            "'Non-major Rule', CRA_RULE_TYPES) and the five-value priority "
            "vocabulary (CRA_PRIORITY_LEVELS), pinned as "
            "GAO_CRA_BLANK_FORM_2023_11 -- and one specific rule's actual "
            "type and priority VALUES are separately capturable from its "
            "own fedrules/{control_number} detail page via an injected "
            "proxy fetcher (see parse_gao_fedrules_page), which is "
            "server-rendered and needs no rendered-DOM capture. What "
            "remains unavailable from any static server capture is the "
            "search page's own slug enumeration, not the facet vocabulary "
            "or any one rule's value."
        ),
    }
)
GAO_CRA_LEGACY_PACKAGE_GAPS = (
    _NOT_A_STABLE_BULK_API_GAP,
    _NO_FACET_RELEASE_GAP,
    _LIVE_CAPTURE_UNVERIFIED_GAP,
    _REVIEW_WINDOW_OUT_OF_SCOPE_GAP,
)
GAO_CRA_LEGACY_KNOWN_GAPS = tuple(gap["reason"] for gap in GAO_CRA_LEGACY_PACKAGE_GAPS)

# The actual Search Database of Rules page is server-rendered. Its two public
# radio groups enumerate all six query values directly in the pinned bytes.
# ``processed=1`` remains in GAO's own query string but is not a visible facet
# and is therefore not promoted into a code list.
GAO_CRA_PACKAGE_GAPS = (
    _NOT_A_STABLE_BULK_API_GAP,
    _NO_FACET_RELEASE_GAP,
    _REVIEW_WINDOW_OUT_OF_SCOPE_GAP,
)
GAO_CRA_KNOWN_GAPS = tuple(gap["reason"] for gap in GAO_CRA_PACKAGE_GAPS)

# Gaps recorded against the REAL captured page's echoed-query parse path
# (parse_gao_cra_real_page_echoed_query). This omits liveCaptureUnverified
# (the real capture IS verified) but keeps facetValueEnumerationRequires-
# RenderedDom, since the real page still cannot supply a facet value list.
GAO_CRA_REAL_PAGE_GAPS = GAO_CRA_PACKAGE_GAPS
GAO_CRA_REAL_PAGE_KNOWN_GAPS = tuple(gap["reason"] for gap in GAO_CRA_REAL_PAGE_GAPS)

_FEDRULES_NO_BULK_LISTING_GAP = MappingProxyType(
    {
        "kind": "fedrulesNoBulkListingApi",
        "reason": (
            "gao.gov publishes no documented bulk API for fedrules records either; "
            "each fedrules/{control_number} page must be fetched individually, and "
            "this module extracts only one rule's type, priority, and control "
            "number per page, not a bulk listing."
        ),
    }
)
# The one real per-rule page captured so far (control number 167777) renders
# a Priority value ("Routine/Info/Other") that does not literally match any
# single one of the blank form's five item-8 priority strings
# (CRA_PRIORITY_LEVELS). See _validate_fedrules_priority for what this
# module accepts and why.
_FEDRULES_PRIORITY_VOCABULARY_UNRECONCILED_GAP = MappingProxyType(
    {
        "kind": "fedrulesPriorityVocabularyUnreconciled",
        "reason": (
            "The fedrules per-rule page's Priority field is a Drupal "
            "entity-reference to GAO's own internal Priority taxonomy, not "
            "a verbatim rendering of the blank form's five item-8 priority "
            "checkboxes. The one real per-rule page captured so far "
            "(control number 167777) displays 'Routine/Info/Other', which "
            "does not literally match any single one of CRA_PRIORITY_LEVELS "
            "-- most plausibly a GAO-derived, collapsed label for the "
            "form's last two categories ('Routine and Frequent' / "
            "'Informational/Administrative/Other'), which the form itself "
            "visually pairs as one 'do not complete the other side' "
            "choice. This module accepts that one confirmed real display "
            "value as recognized in addition to the five literal form "
            "strings, and fails closed on anything else, but full "
            "reconciliation between the form's five-value vocabulary and "
            "GAO's own fedrules Priority taxonomy remains unconfirmed and "
            "is an open follow-up pending additional real per-rule "
            "captures spanning the full priority range."
        ),
    }
)
GAO_CRA_FEDRULES_GAPS = (
    _FEDRULES_NO_BULK_LISTING_GAP,
    _FEDRULES_PRIORITY_VOCABULARY_UNRECONCILED_GAP,
)
GAO_CRA_FEDRULES_KNOWN_GAPS = tuple(gap["reason"] for gap in GAO_CRA_FEDRULES_GAPS)


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
    """A caller asked the echoed-query view to enumerate a facet.

    That narrow view retains only selected query values. Call
    ``parse_gao_cra_facets`` on the same page to read the complete public
    radio groups.
    """


class GAOCRAVocabularyDriftError(GAOCRASourceDriftError):
    """A fedrules per-rule page reports a type or priority value outside GAO's own vocabulary.

    Raised by ``parse_gao_fedrules_page`` when the extracted rule-type or
    priority value does not match GAO's own publisher-stated vocabulary
    (``CRA_RULE_TYPES``, ``CRA_PRIORITY_LEVELS``) or a confirmed real
    fedrules-site display variant of it; see
    ``_FEDRULES_PRIORITY_VOCABULARY_UNRECONCILED_GAP``.
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
    if parsed.path not in {GAO_CRA_DATABASE_PATH, GAO_CRA_OVERVIEW_PATH}:
        raise GAOCRAAcquisitionError(
            f"source_url must address the CRA search page ({GAO_CRA_DATABASE_PATH}); "
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
    source_url=GAO_CRA_OVERVIEW_URL,
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


_FEDRULES_PATH_PATTERN = re.compile(r"^/fedrules/(\d+)$")


def _validate_fedrules_source_url(source_url: str) -> str:
    """Validate an official fedrules per-rule detail page URL, returning its control number."""

    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname not in GAO_CRA_HOSTS:
        raise GAOCRAAcquisitionError("source_url must be an official HTTPS gao.gov URL")
    if parsed.username is not None or parsed.password is not None:
        raise GAOCRAAcquisitionError("source_url must not contain credentials")
    match = _FEDRULES_PATH_PATTERN.fullmatch(parsed.path)
    if match is None:
        raise GAOCRAAcquisitionError(
            "source_url must address a fedrules per-rule detail page (/fedrules/<control_number>); "
            "other gao.gov pages are out of scope for this parser"
        )
    return match.group(1)


@dataclass(frozen=True, slots=True)
class GAOFedRulesPageSnapshotPin:
    """Expected identity of one exact captured fedrules per-rule detail page."""

    source_url: str
    control_number: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        url_control_number = _validate_fedrules_source_url(self.source_url)
        if url_control_number != self.control_number:
            raise GAOCRAAcquisitionError(
                f"control_number {self.control_number!r} does not match source_url control "
                f"number {url_control_number!r}"
            )
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GAOCRAAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GAOCRAAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise GAOCRAAcquisitionError("retrieved_at must not be empty")


# A real fedrules per-rule detail page, captured through the project's Zyte
# transport. Unlike the CRA database search page, this page is
# server-rendered: see parse_gao_fedrules_page.
GAO_FEDRULES_167777_URL = "https://www.gao.gov/fedrules/167777"
GAO_FEDRULES_167777_SHA256 = "sha256:773d9775bd5dfe65e9427e3460c7a098341d2687fda27f3165aa11709d722bb3"
GAO_FEDRULES_167777_BYTE_LENGTH = 36_828
GAO_FEDRULES_167777_RETRIEVED_AT = "2026-08-04T00:58:00Z"

GAO_FEDRULES_167777 = GAOFedRulesPageSnapshotPin(
    source_url=GAO_FEDRULES_167777_URL,
    control_number="167777",
    retrieved_at=GAO_FEDRULES_167777_RETRIEVED_AT,
    expected_sha256=GAO_FEDRULES_167777_SHA256,
    expected_byte_length=GAO_FEDRULES_167777_BYTE_LENGTH,
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


@dataclass(frozen=True, slots=True)
class AcquiredGAOFedRulesPage:
    """One verified fedrules per-rule detail page in the content-addressed source store."""

    pin: GAOFedRulesPageSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _verify_fedrules_payload(payload: bytes, pin: GAOFedRulesPageSnapshotPin, *, location: str) -> tuple[str, int]:
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


def _verify_existing_fedrules(path: Path, pin: GAOFedRulesPageSnapshotPin) -> AcquiredGAOFedRulesPage:
    if path.is_symlink() or not path.is_file():
        raise GAOCRAAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_fedrules_payload(
        path.read_bytes(),
        pin,
        location="cached fedrules page",
    )
    return AcquiredGAOFedRulesPage(
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


def _publish_fedrules_payload(
    payload: bytes,
    pin: GAOFedRulesPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGAOFedRulesPage:
    actual_sha256, byte_length = _verify_fedrules_payload(
        payload,
        pin,
        location=f"{acquisition_mode} fedrules page",
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
            return _verify_existing_fedrules(final_path, pin)
        return AcquiredGAOFedRulesPage(
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


def acquire_gao_fedrules_page(
    pin: GAOFedRulesPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: GAOCRAPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredGAOFedRulesPage:
    """Acquire one exact fedrules per-rule detail page from cache, a local capture, or an injected fetcher.

    Per-rule pages at gao.gov/fedrules/{control_number} are the record-level
    acquisition target: unlike the CRA database search page, they are
    server-rendered and expose the rule type, priority, and control number
    directly in Drupal field markup (see parse_gao_fedrules_page). The same
    injected-fetcher transport boundary as acquire_gao_cra_facets_page
    applies here; importing this module never opens a network connection.
    """

    if timeout_seconds <= 0:
        raise GAOCRAAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise GAOCRAAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / f"fedrules-{pin.control_number}.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing_fedrules(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GAOCRAAcquisitionError(f"local fedrules source is not a regular file: {local_path}")
        return _publish_fedrules_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type="text/html",
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise GAOCRAAcquisitionError("fedrules page is not cached; provide source_path or an injected fetcher")

    fetched = fetcher.fetch(pin.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=pin.source_url)
    return _publish_fedrules_payload(
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
            if name in _LEGACY_FACET_NAMES:
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


class _CRARadioFacetFormParser(HTMLParser):
    """Read the two public radio groups from GAO's real database search form."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.facets: dict[str, list[tuple[str, str, bool]]] = {}
        self._in_search_form = False
        self._inputs: dict[str, tuple[str, str, bool]] = {}
        self._current_label_for: str | None = None
        self._current_label_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "form" and attr_map.get("id") == "database-rules-search-form":
            if self._in_search_form:
                raise GAOCRASourceDriftError("CRA database search form appears more than once")
            self._in_search_form = True
            return
        if not self._in_search_form:
            return
        if tag == "input" and attr_map.get("type") == "radio":
            name = attr_map.get("name")
            if name not in _EXPECTED_FACET_NAMES:
                return
            element_id = attr_map.get("id")
            value = attr_map.get("value")
            if not element_id or value is None:
                raise GAOCRASourceDriftError(f"facet {name!r} radio is missing id or value")
            if element_id in self._inputs:
                raise GAOCRASourceDriftError(f"facet radio id {element_id!r} appears more than once")
            self._inputs[element_id] = (name, value, "checked" in attr_map)
        elif tag == "label":
            label_for = attr_map.get("for")
            if label_for in self._inputs:
                self._current_label_for = label_for
                self._current_label_text = []

    def handle_data(self, data: str) -> None:
        if self._current_label_for is not None:
            self._current_label_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._current_label_for is not None:
            name, value, is_default = self._inputs.pop(self._current_label_for)
            label = _normalize_text(self._current_label_text)
            self.facets.setdefault(name, []).append((value, label, is_default))
            self._current_label_for = None
            self._current_label_text = []
        elif tag == "form" and self._in_search_form:
            self._in_search_form = False

    def finish(self) -> None:
        if self._inputs:
            raise GAOCRASourceDriftError(f"CRA database facet radio(s) have no matching label: {sorted(self._inputs)}")


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
    """Parse exact search facets from a digest-pinned CRA database page.

    The current publisher page exposes two radio groups: ``priority`` and
    ``type``. The older select parser remains only for the explicitly marked
    legacy hypothesis fixture; it is not accepted by package generation.
    """

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GAOCRASourceDriftError("gao.gov CRA database page is not UTF-8") from error

    is_real_search_page = 'id="database-rules-search-form"' in decoded
    parser: _CRARadioFacetFormParser | _CRAFacetFormParser
    parser = _CRARadioFacetFormParser() if is_real_search_page else _CRAFacetFormParser()
    try:
        parser.feed(decoded)
        parser.close()
        if isinstance(parser, _CRARadioFacetFormParser):
            parser.finish()
    except GAOCRAFacetError:
        raise
    except Exception as error:
        raise GAOCRASourceDriftError("gao.gov CRA database page is malformed HTML") from error

    expected_names = _EXPECTED_FACET_NAMES if is_real_search_page else _LEGACY_FACET_NAMES
    missing = expected_names - set(parser.facets)
    if missing:
        raise GAOCRASourceDriftError(f"CRA database page is missing facet(s) {sorted(missing)}")

    facets: dict[FacetName, tuple[GAOCRAFacetCode, ...]] = {}
    for facet_name in sorted(expected_names):
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
        gaps=GAO_CRA_KNOWN_GAPS if is_real_search_page else GAO_CRA_LEGACY_KNOWN_GAPS,
    )


@dataclass(frozen=True, slots=True)
class ParsedGAOCRAEchoedFacetQuery:
    """The two public facets' currently echoed values from the Drupal settings.

    This view intentionally captures only selection state. Use
    ``parse_gao_cra_facets`` to read all six server-rendered radio values.
    """

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    echoed_query: Mapping[FacetName, str]
    gaps: tuple[str, ...]

    def available_facet_values(self, facet_name: FacetName) -> NoReturn:
        """Refuse because this narrow view contains only selected values."""

        if facet_name not in self.echoed_query:
            raise GAOCRASourceDriftError(f"unknown CRA facet {facet_name!r}")
        raise GAOCRAFacetEnumerationUnavailableError(
            f"echoed-query view does not enumerate CRA facet {facet_name!r}; "
            "call parse_gao_cra_facets on the same acquired page"
        )


def parse_gao_cra_real_page_echoed_query(page: AcquiredGAOCRAFacetPage) -> ParsedGAOCRAEchoedFacetQuery:
    """Parse the two public facets' selected values from Drupal settings."""

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
            "gao.gov CRA database page is missing its 'Search Database of Rules' <h1> heading anchor"
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


# ---------------------------------------------------------------------------
# Fedrules per-rule detail page (record-level acquisition target)
# ---------------------------------------------------------------------------
#
# Unlike the CRA database search page, gao.gov/fedrules/{control_number}
# pages are server-rendered: the rule type, priority, and control number are
# present directly in Drupal field markup, anchored by each field's
# "field--name-field-<name>" class.

_FEDRULES_TITLE_PREFIX = "Federal Rules: "
_FEDRULES_TITLE_SUFFIX = " | U.S. GAO"
_FEDRULES_ARTICLE_MARKER = 'class="node node--type-federal-rules'
_FEDRULES_CANONICAL_LINK = re.compile(r'<link rel="canonical" href="([^"]+)"\s*/?>', re.IGNORECASE)


def _fedrules_field_pattern(field_class: str) -> re.Pattern[str]:
    return re.compile(
        r'<div class="field ' + re.escape(field_class) + r'\b[^"]*field--label-above">'
        r'\s*<h2 class="field__label">([^<]*)</h2>'
        r'\s*<div class="field__item">(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )


def _extract_fedrules_field(decoded: str, *, field_class: str, expected_label: str) -> str:
    match = _fedrules_field_pattern(field_class).search(decoded)
    if match is None:
        raise GAOCRASourceDriftError(f"gao.gov fedrules page is missing its {field_class!r} field markup")
    label = _normalize_text([match.group(1)])
    if label != expected_label:
        raise GAOCRASourceDriftError(
            f"gao.gov fedrules page {field_class!r} field label drifted: expected {expected_label!r}, got {label!r}"
        )
    return _normalize_text([match.group(2)])


def _normalize_cra_vocabulary_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


# The blank form's item 5 checkbox wording ("Major Rule" / "Non-major
# Rule") is rendered on the fedrules page's Type field with the trailing
# word "Rule" dropped ("Major" / "Non-Major"); this normalization accepts
# either the literal form wording or that mechanical abbreviation.
_CRA_RULE_TYPE_RECOGNIZED_NORMALIZED: frozenset[str] = frozenset(
    {_normalize_cra_vocabulary_label(value) for value in CRA_RULE_TYPES}
    | {_normalize_cra_vocabulary_label(value.removesuffix(" Rule")) for value in CRA_RULE_TYPES}
)

# The one real per-rule page captured so far (control number 167777) shows a
# Priority display value that does not literally match any single one of
# CRA_PRIORITY_LEVELS; see _FEDRULES_PRIORITY_VOCABULARY_UNRECONCILED_GAP for
# why this confirmed real value is nonetheless recognized here.
_CRA_FEDRULES_PRIORITY_DISPLAY_VALUES: tuple[str, ...] = ("Routine/Info/Other",)
_CRA_PRIORITY_RECOGNIZED_NORMALIZED: frozenset[str] = frozenset(
    {_normalize_cra_vocabulary_label(value) for value in CRA_PRIORITY_LEVELS}
    | {_normalize_cra_vocabulary_label(value) for value in _CRA_FEDRULES_PRIORITY_DISPLAY_VALUES}
)


def _validate_fedrules_rule_type(raw_value: str) -> str:
    if _normalize_cra_vocabulary_label(raw_value) not in _CRA_RULE_TYPE_RECOGNIZED_NORMALIZED:
        raise GAOCRAVocabularyDriftError(
            f"fedrules page Type value {raw_value!r} is not in GAO's publisher-stated CRA rule-type "
            f"vocabulary {CRA_RULE_TYPES!r}"
        )
    return raw_value


def _validate_fedrules_priority(raw_value: str) -> str:
    if _normalize_cra_vocabulary_label(raw_value) not in _CRA_PRIORITY_RECOGNIZED_NORMALIZED:
        raise GAOCRAVocabularyDriftError(
            f"fedrules page Priority value {raw_value!r} is not in GAO's publisher-stated CRA priority "
            f"vocabulary {CRA_PRIORITY_LEVELS!r} or its known fedrules-site display variants "
            f"{_CRA_FEDRULES_PRIORITY_DISPLAY_VALUES!r}"
        )
    return raw_value


@dataclass(frozen=True, slots=True)
class ParsedGAOFedRulesPage:
    """The rule type, priority, and control number read from one real fedrules per-rule page."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    control_number: str
    rule_type: str
    priority: str
    gaps: tuple[str, ...]


def parse_gao_fedrules_page(page: AcquiredGAOFedRulesPage) -> ParsedGAOFedRulesPage:
    """Parse the rule type, priority, and control number from one captured fedrules detail page.

    Unlike the CRA database search page, gao.gov/fedrules/{control_number}
    pages are server-rendered: this function confirms page identity via the
    ``<title>``, canonical ``<link>``, and ``node--type-federal-rules``
    article anchors before trusting any extracted field, then reads the
    Type, Priority, and Control Number fields directly from their anchoring
    Drupal ``field--name-field-*`` markup, failing closed if any anchor or
    field is missing, relabeled, or the control number in the page body does
    not match the one in its own pinned URL. The extracted Type and Priority
    values are validated against GAO's own publisher-stated CRA vocabulary
    (``CRA_RULE_TYPES``, ``CRA_PRIORITY_LEVELS``); see
    ``_validate_fedrules_priority`` for the one confirmed real display
    variant this module also recognizes.
    """

    payload = page.path.read_bytes()
    _verify_fedrules_payload(payload, page.pin, location="parsed fedrules page")
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GAOCRASourceDriftError("gao.gov fedrules page is not UTF-8") from error

    title_match = _TITLE_TAG.search(decoded)
    title = _normalize_text([title_match.group(1)]) if title_match is not None else ""
    if title_match is None or not (title.startswith(_FEDRULES_TITLE_PREFIX) and title.endswith(_FEDRULES_TITLE_SUFFIX)):
        raise GAOCRASourceDriftError("gao.gov fedrules page <title> does not identify a Federal Rules detail page")

    canonical_match = _FEDRULES_CANONICAL_LINK.search(decoded)
    if canonical_match is None or canonical_match.group(1) != page.pin.source_url:
        raise GAOCRASourceDriftError("gao.gov fedrules page canonical link does not match its acquired source_url")

    if _FEDRULES_ARTICLE_MARKER not in decoded:
        raise GAOCRASourceDriftError("gao.gov fedrules page is missing its 'node--type-federal-rules' article anchor")

    control_number = _extract_fedrules_field(
        decoded, field_class="field--name-field-control-number", expected_label="Control Number"
    )
    if not control_number.isdigit():
        raise GAOCRASourceDriftError(f"fedrules page control number {control_number!r} is not numeric")
    if control_number != page.pin.control_number:
        raise GAOCRASourceDriftError(
            f"fedrules page control number {control_number!r} does not match its pinned source_url "
            f"control number {page.pin.control_number!r}"
        )

    rule_type_raw = _extract_fedrules_field(decoded, field_class="field--name-field-type", expected_label="Type")
    priority_raw = _extract_fedrules_field(decoded, field_class="field--name-field-priority", expected_label="Priority")

    return ParsedGAOFedRulesPage(
        source_url=page.pin.source_url,
        retrieved_at=page.pin.retrieved_at,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        control_number=control_number,
        rule_type=_validate_fedrules_rule_type(rule_type_raw),
        priority=_validate_fedrules_priority(priority_raw),
        gaps=GAO_CRA_FEDRULES_KNOWN_GAPS,
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
        rule_type=_required_facet(record, parsed, "type"),
        received_date=_optional_date(record, "receivedDate"),
        effective_date=_optional_date(record, "effectiveDate"),
        gaps=GAO_CRA_KNOWN_GAPS,
    )


def _observation(parsed: ParsedGAOCRAFacets, code: GAOCRAFacetCode, ordinal: int) -> dict[str, Any]:
    identifier = code.identifiers[0]
    source_path = f"form#database-rules-search-form input[type=radio][name={code.facet_name}][{ordinal}]"
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
        "uses": [cast(PackageResourceUse, code.use)],
        "conceptIdentityClaimed": False,
    }


def build_gao_cra_facets_package(
    page: AcquiredGAOCRAFacetPage,
    parsed: ParsedGAOCRAFacets,
) -> SourceControlledResourceBundle:
    """Package six real GAO search values as a controlled code list.

    This never promotes the result into a concept scheme: every observation's
    ``uses`` stays ``deterministicMetadata``, ``conceptIdentityClaimed``
    stays false. Package generation accepts only the verified Search Database
    of Rules capture; the historical hand-built select fixture is rejected.
    """

    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise GAOCRASourceDriftError("CRA database page package source differs from its acquired pin")
    if parsed.source_sha256 != page.sha256:
        raise GAOCRASourceDriftError("parsed CRA database page and acquired page digests differ")
    if parsed.source_url != page.pin.source_url:
        raise GAOCRASourceDriftError("parsed CRA database page source_url differs from its acquired pin")
    if page.sha256 != GAO_CRA_REAL_CAPTURE_2026_08_04_SHA256 or page.pin.source_url != GAO_CRA_DATABASE_URL:
        raise GAOCRASourceDriftError("CRA facet packages require the verified GAO Search Database of Rules capture")
    if set(parsed.facets) != set(_EXPECTED_FACET_NAMES):
        raise GAOCRASourceDriftError("CRA facet package must contain exactly the real priority and type facets")

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
        observations=observations,
        source_artifacts={parsed.source_url: payload},
        gaps=GAO_CRA_PACKAGE_GAPS,
    )


__all__ = [
    "CRA_PRIORITY_LEVELS",
    "CRA_RULE_TYPES",
    "GAO_CRA_BLANK_FORM_2023_11_BYTE_LENGTH",
    "GAO_CRA_BLANK_FORM_2023_11_RETRIEVED_AT",
    "GAO_CRA_BLANK_FORM_2023_11_SHA256",
    "GAO_CRA_BLANK_FORM_2023_11_URL",
    "GAO_CRA_DATABASE_PATH",
    "GAO_CRA_DATABASE_URL",
    "GAO_CRA_FACETS_2026_08_03",
    "GAO_CRA_FACETS_2026_08_03_BYTE_LENGTH",
    "GAO_CRA_FACETS_2026_08_03_RETRIEVED_AT",
    "GAO_CRA_FACETS_2026_08_03_SHA256",
    "GAO_CRA_FEDRULES_GAPS",
    "GAO_CRA_FEDRULES_KNOWN_GAPS",
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
    "GAO_FEDRULES_167777",
    "GAO_FEDRULES_167777_BYTE_LENGTH",
    "GAO_FEDRULES_167777_RETRIEVED_AT",
    "GAO_FEDRULES_167777_SHA256",
    "GAO_FEDRULES_167777_URL",
    "AcquiredGAOCRAFacetPage",
    "AcquiredGAOFedRulesPage",
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
    "GAOCRAVocabularyDriftError",
    "GAOFedRulesPageSnapshotPin",
    "ParsedGAOCRAEchoedFacetQuery",
    "ParsedGAOCRAFacets",
    "ParsedGAOFedRulesPage",
    "ResourceUse",
    "ValidatedGAOCRARuleSubmissionFacets",
    "acquire_gao_cra_facets_page",
    "acquire_gao_fedrules_page",
    "build_gao_cra_facets_package",
    "parse_gao_cra_facets",
    "parse_gao_cra_real_page_echoed_query",
    "parse_gao_fedrules_page",
    "sha256_digest",
    "validate_cra_rule_submission_facets",
]

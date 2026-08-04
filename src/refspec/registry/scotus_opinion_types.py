"""Source-faithful capture of the Supreme Court's opinion and package types.

supremecourt.gov publishes no JSON constants endpoint or code list for the
categories it uses to organize opinions. It exposes them only through the
"opinions" landing page: a sidebar navigation list of opinion categories
(Opinions of the Court, Opinions Relating to Orders, In-Chambers Opinions,
U. S. Reports) and a plain-prose description of the slip-opinion to
preliminary-print to bound-volume publication ladder. The catalog decision
for this source is explicit: preserve the official opinion/package type and
version ladder as deterministic metadata, and split individual writings
(majority/principal, concurrence, dissent, per curiam) only when the official
source itself supplies a reliable boundary between them -- which this page
does not. This module therefore captures the four navigational categories
and the three named version-ladder stages only, and never invents a
per-writing split.

The landing URL ``https://www.supremecourt.gov/opinions/`` is a client-side
meta-refresh stub that immediately forwards to ``opinions.aspx``; this module
addresses that resolved content page directly, the same page a browser
following the stub would render. Neither page publishes a stable code or IRI
for any category: the sidebar hrefs carry a term-year path segment that
changes every October Term, so no publisher identifier is minted here.

Live retrieval is provider-independent. Callers inject a fetcher or provide
an already captured local file. Importing this module never opens a network
connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

SCOTUS_HOSTS = frozenset({"supremecourt.gov", "www.supremecourt.gov"})
SCOTUS_LANGUAGE = "en"
SCOTUS_OPINIONS_LANDING_URL = "https://www.supremecourt.gov/opinions/"
SCOTUS_OPINIONS_SOURCE_URL = "https://www.supremecourt.gov/opinions/opinions.aspx"
SCOTUS_OPINION_AND_PACKAGE_TYPES_RESOURCE_ID = "scotus-opinion-and-package-types"

AcquisitionMode = Literal["cache", "local", "fetcher"]
OpinionTypeFacet = Literal["opinionType", "reporterSeries", "packageVersionStage"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
# Observed generic vendor block/challenge markers other RefSpec adapters
# check for so a future WAF or bot-management change still fails closed.
_CHALLENGE_MARKERS = (
    b"<title>access denied</title>",
    b"errors.edgesuite.net",
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)

_NO_STABLE_OPINION_TYPE_CODE_GAP = MappingProxyType(
    {
        "kind": "publisherOpinionTypeCodeUnavailable",
        "reason": (
            "supremecourt.gov exposes opinion/package categories only through "
            "sidebar navigation labels and hrefs (which carry a term-year path "
            "segment that changes every October Term), and the slip/"
            "preliminary-print/bound-volume ladder only through descriptive "
            "prose. It publishes no code, IRI, or constants list for either "
            "facet, so this module mints no publisher identifier."
        ),
    }
)
_NO_PER_WRITING_SPLIT_GAP = MappingProxyType(
    {
        "kind": "perWritingBoundaryUnavailable",
        "reason": (
            "The Court's own description groups the majority/principal opinion "
            "with any concurring or dissenting opinions, and separately "
            "describes per curiam dispositions, all under Opinions of the "
            "Court, without publishing a reliable per-writing boundary; this "
            "module does not split them into separate controlled values."
        ),
    }
)
SCOTUS_OPINION_TYPE_GAPS: tuple[Mapping[str, str], ...] = (
    _NO_STABLE_OPINION_TYPE_CODE_GAP,
    _NO_PER_WRITING_SPLIT_GAP,
)


class SCOTUSOpinionTypesError(ValueError):
    """Base class for SCOTUS opinion/package-type controlled-resource failures."""


class SCOTUSAcquisitionError(SCOTUSOpinionTypesError):
    """Exact source bytes could not be captured safely."""


class SCOTUSSourceDriftError(SCOTUSOpinionTypesError):
    """The captured opinions page no longer has the reviewed structure."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_source_url(source_url: str) -> None:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname not in SCOTUS_HOSTS:
        raise SCOTUSAcquisitionError("source_url must be an official HTTPS supremecourt.gov URL")
    if parsed.username is not None or parsed.password is not None:
        raise SCOTUSAcquisitionError("source_url must not contain credentials")


@dataclass(frozen=True, slots=True)
class SCOTUSOpinionsPageSnapshotPin:
    """Expected identity of one exact captured opinions page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _validate_source_url(self.source_url)
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise SCOTUSAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise SCOTUSAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise SCOTUSAcquisitionError("retrieved_at must not be empty")


# The exact page captured while this module was implemented. A future term
# rolls the sidebar hrefs' year segment forward (see the parser's tolerant
# href patterns) and will require a newly captured pin, not an edit to this
# one: this pin freezes one historical, reproducible snapshot.
SCOTUS_OPINIONS_2026_08_03 = SCOTUSOpinionsPageSnapshotPin(
    source_url=SCOTUS_OPINIONS_SOURCE_URL,
    retrieved_at="2026-08-03T19:15:13Z",
    expected_sha256="sha256:26d9c70afb7ee7b66678eea7eb32851c74a10ee8e60249ffc5433a45a82b2bd5",
    expected_byte_length=42_237,
)


@dataclass(frozen=True, slots=True)
class FetchedSCOTUSPage:
    """Provider-independent result returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class SCOTUSPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedSCOTUSPage:
        """Fetch one official page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredSCOTUSOpinionsPage:
    """One verified opinions page in the content-addressed source store."""

    pin: SCOTUSOpinionsPageSnapshotPin
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
        raise SCOTUSSourceDriftError(
            "supremecourt.gov returned an access-denied or challenge page instead of the opinions page"
        )
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise SCOTUSSourceDriftError("supremecourt.gov opinions capture is not an HTML document")
    if b'http-equiv="refresh"' in lowered and b"sidenav-list" not in lowered:
        raise SCOTUSSourceDriftError(
            "supremecourt.gov opinions capture is the client-side meta-refresh stub at "
            "/opinions/, not the resolved opinions.aspx content page this module parses"
        )
    if b"sidenav-list" not in lowered:
        raise SCOTUSSourceDriftError("supremecourt.gov opinions capture is missing its sidebar category list")


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in SCOTUS_HOSTS:
        raise SCOTUSAcquisitionError("fetcher resolved_url must remain on official HTTPS supremecourt.gov")
    if parsed.username is not None or parsed.password is not None:
        raise SCOTUSAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_fetched_page(fetched: FetchedSCOTUSPage, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise SCOTUSAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise SCOTUSSourceDriftError(f"supremecourt.gov opinions page content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: SCOTUSOpinionsPageSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise SCOTUSSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise SCOTUSSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: SCOTUSOpinionsPageSnapshotPin) -> AcquiredSCOTUSOpinionsPage:
    if path.is_symlink() or not path.is_file():
        raise SCOTUSAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached SCOTUS opinions page",
    )
    return AcquiredSCOTUSOpinionsPage(
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
    pin: SCOTUSOpinionsPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredSCOTUSOpinionsPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} SCOTUS opinions page",
    )
    object_dir = final_path.parent
    object_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".acquire-", suffix=".tmp", dir=object_dir)
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
        return AcquiredSCOTUSOpinionsPage(
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


def acquire_scotus_opinions_page(
    pin: SCOTUSOpinionsPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: SCOTUSPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredSCOTUSOpinionsPage:
    """Acquire one exact opinions page from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache miss.
    This keeps every live transport outside the source parser while applying
    the same digest, length, origin, and access-denied/challenge checks to
    all fetched bytes.
    """

    if timeout_seconds <= 0:
        raise SCOTUSAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise SCOTUSAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "opinions.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise SCOTUSAcquisitionError(f"local SCOTUS opinions source is not a regular file: {local_path}")
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
        raise SCOTUSAcquisitionError("SCOTUS opinions page is not cached; provide source_path or an injected fetcher")

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


def capture_initial_scotus_opinions_page_snapshot(
    source_url: str,
    store_dir: Path,
    *,
    retrieved_at: str,
    fetcher: SCOTUSPageFetcher,
    timeout_seconds: float = 60.0,
) -> AcquiredSCOTUSOpinionsPage:
    """Capture valid first-seen bytes and return the exact pin they establish.

    This is the discovery step used before a strict
    :func:`acquire_scotus_opinions_page` reopen, and the way a later October
    Term's rolled sidebar hrefs get their own frozen pin.
    """

    if timeout_seconds <= 0:
        raise SCOTUSAcquisitionError("timeout_seconds must be positive")
    if not retrieved_at.strip():
        raise SCOTUSAcquisitionError("retrieved_at must not be empty")
    _validate_source_url(source_url)
    fetched = fetcher.fetch(source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=source_url)
    pin = SCOTUSOpinionsPageSnapshotPin(
        source_url=source_url,
        retrieved_at=retrieved_at,
        expected_sha256=sha256_digest(fetched.body),
        expected_byte_length=len(fetched.body),
    )
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / "opinions.html"
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


_TRACKED_TAGS = frozenset({"ul", "a", "div", "p"})
_SIDENAV_CONTENT_DIV_ID = "ctl00_ctl00_MainEditable_mainContent_RadEditor1"


class _SCOTUSOpinionsPageParser(HTMLParser):
    """Collect only the sidebar category list and the description paragraphs.

    The parser never interprets any other part of the page -- top navigation,
    footer navigation, and every other sidebar/footer link that also happens
    to point under ``/opinions/`` are ignored. It walks one already-fetched
    page and records exactly the sidebar category list and the paragraphs of
    the one description block that page renders about itself. Every
    structural expectation is checked by the caller against the counts and
    text collected here, not guessed.

    Only ``ul``, ``a``, ``div``, and ``p`` push a stack frame. Inline tags
    such as ``<i>`` (used for "per curiam") are not tracked, so their text
    still reaches the open paragraph frame without desyncing the stack.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sidenav_root_match_count = 0
        self.content_root_match_count = 0
        self.categories: list[tuple[str | None, str | None, str]] = []
        self.paragraphs: list[str] = []

        self._stack: list[dict[str, Any]] = []
        self._sidenav_root_open = False
        self._content_root_open = False
        self._current_anchor_attrs: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs)
        if tag in _TRACKED_TAGS:
            self._close(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _TRACKED_TAGS:
            self._close(tag)

    def handle_data(self, data: str) -> None:
        for frame in self._stack:
            if frame["role"] in {"sidenavAnchor", "contentParagraph"}:
                frame["text"].append(data)

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        role: str | None = None

        if tag == "ul" and "sidenav-list" in frozenset((attr_map.get("class") or "").split()):
            self.sidenav_root_match_count += 1
            if not self._sidenav_root_open:
                role = "sidenavRoot"

        if tag == "a" and self._sidenav_root_open and self._current_anchor_attrs is None:
            role = "sidenavAnchor"
            self._current_anchor_attrs = {"id": attr_map.get("id"), "href": attr_map.get("href")}

        if tag == "div" and attr_map.get("id") == _SIDENAV_CONTENT_DIV_ID:
            self.content_root_match_count += 1
            if not self._content_root_open:
                role = "contentRoot"

        if tag == "p" and self._content_root_open:
            role = "contentParagraph"

        if role == "sidenavRoot":
            self._sidenav_root_open = True
        if role == "contentRoot":
            self._content_root_open = True

        self._stack.append({"tag": tag, "role": role, "text": []})

    def _close(self, tag: str) -> None:
        if not self._stack:
            return
        if self._stack[-1]["tag"] != tag:
            for index in range(len(self._stack) - 1, -1, -1):
                if self._stack[index]["tag"] == tag:
                    del self._stack[index + 1 :]
                    break
            else:
                return
        frame = self._stack.pop()
        role = frame["role"]
        if role == "sidenavRoot":
            self._sidenav_root_open = False
        elif role == "contentRoot":
            self._content_root_open = False
        elif role == "sidenavAnchor":
            attrs = self._current_anchor_attrs
            self._current_anchor_attrs = None
            element_id = attrs["id"] if attrs else None
            href = attrs["href"] if attrs else None
            self.categories.append((element_id, href, _normalize_text(frame["text"])))
        elif role == "contentParagraph":
            self.paragraphs.append(_normalize_text(frame["text"]))


# (id suffix, exact label, href pattern). The href pattern tolerates the
# term-year segment ("slipopinion/25") rolling forward every October Term.
_EXPECTED_SIDENAV_CATEGORIES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("hypOpinion", "Opinions of the Court", re.compile(r"^slipopinion/\d+$")),
    ("hypRelating", "Opinions Relating to Orders", re.compile(r"^relatingtoorders/\d+$")),
    ("hypInChamber", "In-Chambers Opinions", re.compile(r"^in-chambers\.aspx$")),
    ("hypusreports", "U. S. Reports", re.compile(r"^USReports\.aspx$")),
)
# Other links this same sidebar carries that are not opinion/package types
# (case-citation search, cited-sources index, cited-media index); required
# present in order so a page restructure is still caught, but never packaged.
_EXPECTED_TRAILING_SIDENAV_LABELS = (
    "Online Sources Cited in Opinions",
    "Media Files Cited in Opinions",
    "Case Citation Finder",
)
# (canonical controlled label, literal phrase to find in the ladder
# paragraph). Order matters: the paragraph must name them in this sequence.
_VERSION_LADDER_STAGES: tuple[tuple[str, str], ...] = (
    ("Slip opinion", "slip opinion"),
    ("Preliminary print", "preliminary print"),
    ("Bound volume", "bound volume"),
)
_EXPECTED_PARAGRAPH_COUNT = 6
_LADDER_PARAGRAPH_INDEX = 5


def scotus_opinion_type_record_iri(source_sha256: str, facet: str, source_ordinal: int) -> str:
    """Build a capture-local observation IRI, not a publisher identifier."""

    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise SCOTUSSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if source_ordinal < 0:
        raise SCOTUSSourceDriftError("source_ordinal must be non-negative")
    return f"urn:ref:scotus-opinion-type:{match.group(1)}:{facet}:{source_ordinal}"


@dataclass(frozen=True, slots=True)
class SCOTUSOpinionOrPackageType:
    """One exact opinion/package category or version-ladder stage."""

    facet: OpinionTypeFacet
    label: str
    source_path: str
    source_ordinal: int
    navigation_href: str | None
    stage_order: int | None
    record_iri: str


@dataclass(frozen=True, slots=True)
class ParsedSCOTUSOpinionsPage:
    """Parsed opinion/package types from one exact, digest-pinned opinions page."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    entries: tuple[SCOTUSOpinionOrPackageType, ...]
    gaps: tuple[Mapping[str, str], ...]


def _read_acquired_payload(page: AcquiredSCOTUSOpinionsPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed SCOTUS opinions page")
    return payload


def parse_scotus_opinions_page(page: AcquiredSCOTUSOpinionsPage) -> ParsedSCOTUSOpinionsPage:
    """Parse the opinion/package types one exact, digest-pinned opinions page names."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SCOTUSSourceDriftError("supremecourt.gov opinions page is not UTF-8") from error

    parser = _SCOTUSOpinionsPageParser()
    try:
        parser.feed(decoded)
        parser.close()
    except SCOTUSOpinionTypesError:
        raise
    except Exception as error:
        raise SCOTUSSourceDriftError("supremecourt.gov opinions page is malformed HTML") from error

    if parser.sidenav_root_match_count != 1:
        raise SCOTUSSourceDriftError("opinions page must contain exactly one sidebar category list")
    if parser.content_root_match_count != 1:
        raise SCOTUSSourceDriftError("opinions page must contain exactly one opinions description block")

    expected_category_count = len(_EXPECTED_SIDENAV_CATEGORIES) + len(_EXPECTED_TRAILING_SIDENAV_LABELS)
    if len(parser.categories) != expected_category_count:
        raise SCOTUSSourceDriftError(
            f"sidebar category count drift: expected {expected_category_count}, parsed {len(parser.categories)}"
        )

    entries: list[SCOTUSOpinionOrPackageType] = []
    for ordinal, (expected_suffix, expected_label, href_pattern) in enumerate(_EXPECTED_SIDENAV_CATEGORIES):
        element_id, href, label = parser.categories[ordinal]
        if element_id is None or not element_id.endswith(f"_{expected_suffix}"):
            raise SCOTUSSourceDriftError(f"sidebar category {ordinal} id drifted: {element_id!r}")
        if label != expected_label:
            raise SCOTUSSourceDriftError(f"sidebar category {ordinal} label drifted: {label!r}")
        if href is None or href_pattern.fullmatch(href) is None:
            raise SCOTUSSourceDriftError(f"sidebar category {ordinal} href drifted: {href!r}")
        facet: OpinionTypeFacet = "reporterSeries" if expected_suffix == "hypusreports" else "opinionType"
        entries.append(
            SCOTUSOpinionOrPackageType(
                facet=facet,
                label=label,
                source_path=f"sidenav.categories[{ordinal}]",
                source_ordinal=ordinal,
                navigation_href=href,
                stage_order=None,
                record_iri=scotus_opinion_type_record_iri(page.sha256, facet, ordinal),
            )
        )

    trailing_offset = len(_EXPECTED_SIDENAV_CATEGORIES)
    for offset, expected_label in enumerate(_EXPECTED_TRAILING_SIDENAV_LABELS):
        _, _, label = parser.categories[trailing_offset + offset]
        if label != expected_label:
            raise SCOTUSSourceDriftError(f"sidebar trailing category {offset} label drifted: {label!r}")

    if len(parser.paragraphs) != _EXPECTED_PARAGRAPH_COUNT:
        raise SCOTUSSourceDriftError(
            f"opinions description block paragraph count drift: expected {_EXPECTED_PARAGRAPH_COUNT}, "
            f"parsed {len(parser.paragraphs)}"
        )

    ladder_paragraph = parser.paragraphs[_LADDER_PARAGRAPH_INDEX].casefold()
    positions = [ladder_paragraph.find(phrase) for _, phrase in _VERSION_LADDER_STAGES]
    if any(position < 0 for position in positions):
        raise SCOTUSSourceDriftError(
            "opinions description block no longer names the slip/preliminary-print/bound-volume ladder"
        )
    if positions != sorted(positions):
        raise SCOTUSSourceDriftError("opinions description block ladder phrases are out of their documented order")

    for stage_index, (canonical_label, _phrase) in enumerate(_VERSION_LADDER_STAGES, start=1):
        entries.append(
            SCOTUSOpinionOrPackageType(
                facet="packageVersionStage",
                label=canonical_label,
                source_path=f"content.paragraphs[{_LADDER_PARAGRAPH_INDEX}]",
                source_ordinal=len(entries),
                navigation_href=None,
                stage_order=stage_index,
                record_iri=scotus_opinion_type_record_iri(page.sha256, "packageVersionStage", stage_index - 1),
            )
        )

    return ParsedSCOTUSOpinionsPage(
        source_url=page.pin.source_url,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        entries=tuple(entries),
        gaps=SCOTUS_OPINION_TYPE_GAPS,
    )


def _observation(parsed: ParsedSCOTUSOpinionsPage, entry: SCOTUSOpinionOrPackageType) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entry.record_iri,
        "sourceArtifact": parsed.source_url,
        "sourcePath": entry.source_path,
        "sourceOrdinal": entry.source_ordinal,
        "labels": [
            {"value": entry.label, "language": SCOTUS_LANGUAGE, "role": "preferred"},
        ],
        # supremecourt.gov documents no stable code or IRI for either facet
        # (see SCOTUS_OPINION_TYPE_GAPS), so this module mints none.
        "identifiers": [],
        "eligibleUses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
        "facet": entry.facet,
    }
    if entry.navigation_href is not None:
        payload["navigationHref"] = entry.navigation_href
    if entry.stage_order is not None:
        payload["stageOrder"] = entry.stage_order
    return payload


def build_scotus_opinion_type_package(
    page: AcquiredSCOTUSOpinionsPage,
    parsed: ParsedSCOTUSOpinionsPage,
) -> SourceControlledResourceBundle:
    """Package one exact opinions page's opinion/package types as deterministic metadata.

    This never promotes the result into a concept scheme: ``identity_status``
    stays ``captureLocalObservationsOnly`` and every observation's
    ``identifiers`` list stays empty, matching the catalog's "no open
    court-assigned topic thesaurus" and "deterministic metadata" guidance.
    """

    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise SCOTUSSourceDriftError("SCOTUS opinions page package source differs from its acquired pin")
    if parsed.source_sha256 != page.sha256:
        raise SCOTUSSourceDriftError("parsed SCOTUS opinions page and acquired page digests differ")
    if parsed.source_url != page.pin.source_url:
        raise SCOTUSSourceDriftError("parsed SCOTUS opinions page source_url differs from its acquired pin")

    observations = tuple(_observation(parsed, entry) for entry in parsed.entries)
    return build_source_controlled_resource_bundle(
        resource_id=SCOTUS_OPINION_AND_PACKAGE_TYPES_RESOURCE_ID,
        title="Supreme Court opinion and package types",
        resource_kind="controlledCodeList",
        identity_status="captureLocalObservationsOnly",
        uses=("deterministicMetadata",),
        captured_at=parsed.retrieved_at,
        candidate_use_authorized=True,
        observations=observations,
        source_artifacts={parsed.source_url: payload},
        gaps=parsed.gaps,
    )


__all__ = [
    "SCOTUS_HOSTS",
    "SCOTUS_LANGUAGE",
    "SCOTUS_OPINIONS_2026_08_03",
    "SCOTUS_OPINIONS_LANDING_URL",
    "SCOTUS_OPINIONS_SOURCE_URL",
    "SCOTUS_OPINION_AND_PACKAGE_TYPES_RESOURCE_ID",
    "SCOTUS_OPINION_TYPE_GAPS",
    "AcquiredSCOTUSOpinionsPage",
    "AcquisitionMode",
    "FetchedSCOTUSPage",
    "OpinionTypeFacet",
    "ParsedSCOTUSOpinionsPage",
    "SCOTUSAcquisitionError",
    "SCOTUSOpinionOrPackageType",
    "SCOTUSOpinionTypesError",
    "SCOTUSOpinionsPageSnapshotPin",
    "SCOTUSPageFetcher",
    "SCOTUSSourceDriftError",
    "acquire_scotus_opinions_page",
    "build_scotus_opinion_type_package",
    "capture_initial_scotus_opinions_page_snapshot",
    "parse_scotus_opinions_page",
    "scotus_opinion_type_record_iri",
    "sha256_digest",
]

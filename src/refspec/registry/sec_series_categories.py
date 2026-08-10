"""Source-faithful SEC Rules and Regulations page-category capture and parsing.

sec.gov publishes "Rules and Regulations" as one HTML landing page.  Two
independent navigation blocks on that single page enumerate the categories
SEC uses for rules, releases, orders, guidance, no-action letters, petitions,
and self-regulatory-organization (SRO) filings:

* A side-navigation menu, rendered twice on the page (once inside a mobile
  accordion, once inside the desktop aside) with byte-identical content.  Each
  rendering also emits one extra, unmatched ``</ul>`` after the list -- a
  Drupal template artifact observed in the live capture, not a parsing error.
* A "subpage card" grid with a short description per category.

The two blocks label and link several of the same categories differently.
For example, the side-navigation "Staff Guidance" entry points to
``/rules-regulations/staff-guidance`` while the subpage card of the same name
points to ``/regulation/staff-interpretations``; "Petitions for Rulemaking"
and "Public Petitions for Rulemaking" share a target path but not a label.
This module keeps the two collections separate rather than reconciling them,
matching the catalog guidance that site navigation is not a universal
taxonomy.

Every observation records ``conceptIdentityClaimed=False`` and carries no
identifiers: sec.gov exposes these categories as Drupal menu labels and
relative paths, not as a published code system with stable term identifiers.
Release and file number shapes (for example "Release No. 33-XXXXX" or "File
No. S7-XX-XX") appear on the individual rulemaking documents this page links
to, not on the page itself; preserving those belongs to the importer for that
document series, not to this module.

Live retrieval is provider-independent.  Callers inject a fetcher (for
example, a Zyte-backed transport) or provide an already captured local file.
Importing this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote, urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode
from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

SEC_PUBLISHER = "U.S. Securities and Exchange Commission"
SEC_LANGUAGE = "en"

CollectionName = Literal["sideNavigation", "subpageCard"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_CHALLENGE_MARKERS = (
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)


class SECResourceError(ValueError):
    """Base class for SEC controlled-resource failures."""


class SECAcquisitionError(SECResourceError):
    """Exact source bytes could not be captured safely."""


class SECSourceDriftError(SECResourceError):
    """The captured publisher source no longer has the reviewed structure."""


class SECIdentityError(SECResourceError):
    """A managed release or concept scheme was requested without identity."""


@dataclass(frozen=True, slots=True)
class SECPageSource:
    """The one official page whose category navigation this module captures."""

    source_url: str
    filename: str
    expected_title: str
    expected_h1: str
    expected_sidenav_category_count: int
    expected_subpage_card_count: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in {"sec.gov", "www.sec.gov"}:
            raise SECAcquisitionError("source_url must be an official HTTPS sec.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise SECAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise SECAcquisitionError("filename must be one plain path component")
        if not self.expected_title or not self.expected_h1:
            raise SECAcquisitionError("expected_title and expected_h1 must not be empty")
        if self.expected_sidenav_category_count <= 0 or self.expected_subpage_card_count <= 0:
            raise SECAcquisitionError("expected category counts must be positive")


SEC_RULES_REGULATIONS_PAGE = SECPageSource(
    source_url="https://www.sec.gov/rules-regulations",
    filename="rules-regulations.html",
    expected_title="SEC.gov | Rules and Regulations",
    expected_h1="Rules and Regulations",
    expected_sidenav_category_count=13,
    expected_subpage_card_count=6,
)


@dataclass(frozen=True, slots=True)
class SECPageSnapshotPin:
    """Expected identity of one exact sec.gov page capture."""

    source: SECPageSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise SECAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise SECAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise SECAcquisitionError("retrieved_at must not be empty")


# This pin is an external record of the 2026-08-03 live capture used to seed
# the module. It is updated only when a freshly reviewed capture replaces it.
SEC_RULES_REGULATIONS_PIN_2026_08_03 = SECPageSnapshotPin(
    source=SEC_RULES_REGULATIONS_PAGE,
    retrieved_at="2026-08-03T19:25:10Z",
    expected_sha256=("sha256:2f39c9d08f0dc55462e30fbda57315fd5159d47a4894dd113dc0bf226112c1b1"),
    expected_byte_length=70_936,
)


@dataclass(frozen=True, slots=True)
class FetchedSECPage:
    """Provider-independent result returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class SECPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedSECPage:
        """Fetch one official page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredSECPage:
    """One verified sec.gov page in the content-addressed source store."""

    pin: SECPageSnapshotPin
    path: Path
    source_url: str
    resolved_url: str | None
    sha256: str
    byte_length: int
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sec_source_record_iri(
    source: SECPageSource,
    *,
    source_sha256: str,
    collection: CollectionName,
    source_ordinal: int,
) -> str:
    """Build a capture-local observation IRI, not a publisher identifier."""

    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise SECSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if source_ordinal <= 0:
        raise SECSourceDriftError("source_ordinal must be positive")
    source_path = quote(urlsplit(source.source_url).path, safe="")
    return f"urn:ref:sec-source-record:{match.group(1)}:{collection}:{source_path}:{source_ordinal}"


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"sec.gov", "www.sec.gov"}:
        raise SECAcquisitionError("fetcher resolved_url must remain on official HTTPS sec.gov")
    if parsed.username is not None or parsed.password is not None:
        raise SECAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise SECSourceDriftError("sec.gov returned a challenge page instead of Rules and Regulations")
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise SECSourceDriftError("sec.gov Rules and Regulations capture is not an HTML document")


def _validate_fetched_page(fetched: FetchedSECPage, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise SECAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise SECSourceDriftError(f"sec.gov Rules and Regulations content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: SECPageSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise SECSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise SECSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: SECPageSnapshotPin) -> AcquiredSECPage:
    if path.is_symlink() or not path.is_file():
        raise SECAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached SEC page",
    )
    return AcquiredSECPage(
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
    pin: SECPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredSECPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} SEC page",
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
        return AcquiredSECPage(
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


def acquire_sec_page(
    pin: SECPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: SECPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredSECPage:
    """Acquire one exact page from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache miss.
    This keeps Zyte, direct HTTP, and future transports outside the source
    parser while applying the same digest, length, origin, and challenge-page
    checks to all fetched bytes.
    """

    if timeout_seconds <= 0:
        raise SECAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise SECAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise SECAcquisitionError(f"local SEC source is not a regular file: {local_path}")
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
        raise SECAcquisitionError("SEC page is not cached; provide source_path or an injected fetcher")

    fetched = fetcher.fetch(pin.source.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=pin.source.source_url)
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def capture_initial_sec_page_snapshot(
    source: SECPageSource,
    store_dir: Path,
    *,
    retrieved_at: str,
    fetcher: SECPageFetcher,
    timeout_seconds: float = 60.0,
) -> AcquiredSECPage:
    """Capture valid first-seen bytes and return the exact pin they establish.

    This is the discovery step used before a strict :func:`acquire_sec_page`
    reopen. It validates origin, status, media type, challenge markers, and
    HTML shape before publishing bytes under their content digest.
    """

    if timeout_seconds <= 0:
        raise SECAcquisitionError("timeout_seconds must be positive")
    if not retrieved_at.strip():
        raise SECAcquisitionError("retrieved_at must not be empty")
    fetched = fetcher.fetch(source.source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=source.source_url)
    pin = SECPageSnapshotPin(
        source=source,
        retrieved_at=retrieved_at,
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


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


def _classes(attrs: list[tuple[str, str | None]]) -> frozenset[str]:
    for key, value in attrs:
        if key == "class" and value:
            return frozenset(value.split())
    return frozenset()


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    for key, value in attrs:
        if key == name:
            return value
    return None


class _RulesRegulationsPageParser(HTMLParser):
    """Collect the title, heading, and both category collections by hand.

    The live page is not always well-nested: sec.gov's Drupal template emits
    one extra, unmatched ``</ul>`` after each side-navigation list. A generic
    tag-stack parser would desynchronize on that, so this parser tracks only
    the handful of elements it needs with dedicated flags instead of a full
    nesting stack.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_text: list[str] = []
        self.h1_text: list[str] = []
        self.sidenav_entries: list[tuple[str, str, bool]] = []
        self.subpage_cards: list[tuple[str, str, str]] = []
        self._in_title = False
        self._title_captured = False
        self._in_h1 = False
        self._in_sidenav = False
        self._sidenav_a: dict[str, Any] | None = None
        self._card: dict[str, Any] | None = None
        self._card_depth = 0
        self._card_label_capturing = False
        self._card_body_capturing = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _classes(attrs)
        # SVG icons on this page (for example the header lock glyph) carry
        # their own nested <title> elements; only the document head title is
        # the page's own title.
        if tag == "title" and not self._title_captured:
            self._in_title = True
        if tag == "h1":
            self._in_h1 = True
            self.h1_text = []
        if tag == "ul" and "usa-sidenav" in classes and not self._in_sidenav:
            self._in_sidenav = True
        if tag == "a" and self._in_sidenav and self._sidenav_a is None:
            href = _attr(attrs, "href")
            if href is not None:
                self._sidenav_a = {"href": href, "class": classes, "text": []}
        if tag == "div" and "subpage-card" in classes and self._card is None:
            self._card = {"href": None, "label": [], "body": []}
            self._card_depth = 1
        elif self._card is not None and tag == "div":
            self._card_depth += 1
        if self._card is not None and tag == "a" and "subpage-card__headline__link" in classes:
            self._card["href"] = _attr(attrs, "href")
            self._card_label_capturing = True
        if self._card is not None and tag == "p" and "subpage-card__body" in classes:
            self._card_body_capturing = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_text.append(data)
        if self._in_h1:
            self.h1_text.append(data)
        if self._sidenav_a is not None:
            self._sidenav_a["text"].append(data)
        if self._card_label_capturing:
            self._card["label"].append(data)
        if self._card_body_capturing:
            self._card["body"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_captured = True
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
        if tag == "a" and self._sidenav_a is not None:
            entry = self._sidenav_a
            self.sidenav_entries.append(
                (
                    entry["href"],
                    _normalize_text(entry["text"]),
                    "usa-title" in entry["class"],
                )
            )
            self._sidenav_a = None
        if tag == "a" and self._card_label_capturing:
            self._card_label_capturing = False
        if tag == "p" and self._card_body_capturing:
            self._card_body_capturing = False
        if tag == "ul" and self._in_sidenav:
            self._in_sidenav = False
        if self._card is not None and tag == "div":
            self._card_depth -= 1
            if self._card_depth == 0:
                self.subpage_cards.append(
                    (
                        self._card["href"] or "",
                        _normalize_text(self._card["label"]),
                        _normalize_text(self._card["body"]),
                    )
                )
                self._card = None


@dataclass(frozen=True, slots=True)
class SECCategoryObservation:
    """One exact category label and target path observed on the page."""

    collection: CollectionName
    label: str
    target_path: str
    description: str | None
    language: str
    identifiers: tuple[ControlledIdentifier, ...]
    record_iri: str
    source_url: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class SECDuplicateLabelEvidence:
    """Source rows that share a label but remain separate observations."""

    collection: CollectionName
    official_label: str
    record_iris: tuple[str, ...]
    source_ordinals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedSECRulesRegulationsPage:
    """Parsed categories from one exact, digest-pinned page."""

    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    side_navigation_categories: tuple[SECCategoryObservation, ...]
    subpage_card_categories: tuple[SECCategoryObservation, ...]
    duplicate_label_evidence: tuple[SECDuplicateLabelEvidence, ...]

    @property
    def categories(self) -> tuple[SECCategoryObservation, ...]:
        return (*self.side_navigation_categories, *self.subpage_card_categories)


def _category(
    source: SECPageSource,
    *,
    collection: CollectionName,
    label: str,
    target_path: str,
    description: str | None,
    ordinal: int,
    source_sha256: str,
) -> SECCategoryObservation:
    return SECCategoryObservation(
        collection=collection,
        label=label,
        target_path=target_path,
        description=description,
        language=SEC_LANGUAGE,
        identifiers=(),
        record_iri=sec_source_record_iri(
            source,
            source_sha256=source_sha256,
            collection=collection,
            source_ordinal=ordinal,
        ),
        source_url=source.source_url,
        source_ordinal=ordinal,
    )


def _duplicate_label_evidence(
    collection: CollectionName,
    categories: Sequence[SECCategoryObservation],
) -> tuple[SECDuplicateLabelEvidence, ...]:
    grouped: dict[str, list[SECCategoryObservation]] = {}
    for category in categories:
        grouped.setdefault(category.label, []).append(category)
    return tuple(
        SECDuplicateLabelEvidence(
            collection=collection,
            official_label=label,
            record_iris=tuple(category.record_iri for category in matches),
            source_ordinals=tuple(category.source_ordinal for category in matches),
        )
        for label, matches in grouped.items()
        if len(matches) > 1
    )


def _read_acquired_payload(page: AcquiredSECPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed SEC page")
    return payload


def parse_sec_rules_regulations_page(page: AcquiredSECPage) -> ParsedSECRulesRegulationsPage:
    """Parse one pinned capture of https://www.sec.gov/rules-regulations."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SECSourceDriftError("sec.gov Rules and Regulations page is not UTF-8") from error
    parser = _RulesRegulationsPageParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as error:
        raise SECSourceDriftError("sec.gov Rules and Regulations page is malformed HTML") from error

    source = page.pin.source
    title_text = _normalize_text(parser.title_text)
    if title_text != source.expected_title:
        raise SECSourceDriftError(f"missing expected page title {source.expected_title!r}; found {title_text!r}")
    h1_text = _normalize_text(parser.h1_text)
    if h1_text != source.expected_h1:
        raise SECSourceDriftError(f"missing expected page heading {source.expected_h1!r}; found {h1_text!r}")

    block_length = source.expected_sidenav_category_count + 1
    if len(parser.sidenav_entries) != 2 * block_length:
        raise SECSourceDriftError(
            "side-navigation category count drift: expected two identical "
            f"{block_length}-item blocks, parsed {len(parser.sidenav_entries)} total entries"
        )
    first_block = parser.sidenav_entries[:block_length]
    second_block = parser.sidenav_entries[block_length:]
    if first_block != second_block:
        raise SECSourceDriftError("the mobile and desktop side-navigation blocks no longer match byte-for-byte")
    if not first_block or not first_block[0][2]:
        raise SECSourceDriftError(
            "side-navigation block is missing its leading self-referential Rules & Regulations link"
        )
    sidenav_rows = first_block[1:]
    if any(is_self for _href, _label, is_self in sidenav_rows):
        raise SECSourceDriftError("side-navigation block contains more than one self-referential link")

    if len(parser.subpage_cards) != source.expected_subpage_card_count:
        raise SECSourceDriftError(
            f"subpage-card category count drift: expected {source.expected_subpage_card_count}, "
            f"parsed {len(parser.subpage_cards)}"
        )

    side_navigation = tuple(
        _category(
            source,
            collection="sideNavigation",
            label=label,
            target_path=href,
            description=None,
            ordinal=ordinal,
            source_sha256=page.sha256,
        )
        for ordinal, (href, label, _is_self) in enumerate(sidenav_rows, start=1)
    )
    subpage_card = tuple(
        _category(
            source,
            collection="subpageCard",
            label=label,
            target_path=href,
            description=description,
            ordinal=ordinal,
            source_sha256=page.sha256,
        )
        for ordinal, (href, label, description) in enumerate(parser.subpage_cards, start=1)
    )
    if any(not category.target_path or not category.label for category in (*side_navigation, *subpage_card)):
        raise SECSourceDriftError("every page category must carry a non-empty label and target path")

    return ParsedSECRulesRegulationsPage(
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        side_navigation_categories=side_navigation,
        subpage_card_categories=subpage_card,
        duplicate_label_evidence=(
            *_duplicate_label_evidence("sideNavigation", side_navigation),
            *_duplicate_label_evidence("subpageCard", subpage_card),
        ),
    )


@dataclass(frozen=True, slots=True)
class SECCategoryReadiness:
    """Why this capture can never become a managed release or concept scheme."""

    source_category_count: int
    source_digest: str
    ready: bool
    blockers: tuple[str, ...]

    def require_ready(self) -> None:
        """Fail rather than promoting site navigation into a taxonomy."""

        if not self.ready:
            raise SECIdentityError("; ".join(self.blockers))


def sec_category_readiness(parsed: ParsedSECRulesRegulationsPage) -> SECCategoryReadiness:
    """Report why the captured page categories stay source evidence, not a scheme."""

    blockers = [
        "sec.gov does not publish stable identifiers for rules-regulations page categories",
        (
            "the side-navigation and subpage-card collections label and link overlapping "
            "categories differently and must not be reconciled into one taxonomy"
        ),
        "sec.gov does not publish this page as a named, versioned code-list release",
    ]
    if parsed.duplicate_label_evidence:
        blockers.append(
            f"{len(parsed.duplicate_label_evidence)} repeated source label group(s) require reviewed reconciliation"
        )
    return SECCategoryReadiness(
        source_category_count=len(parsed.categories),
        source_digest=parsed.source_sha256,
        ready=not blockers,
        blockers=tuple(blockers),
    )


SEC_SERIES_CATEGORY_RESOURCE_ID = "sec-rules-regulations-page-categories-2026-08-03"
SEC_SERIES_CATEGORY_TITLE = "SEC Rules and Regulations page categories, captured 2026-08-03"


def _source_artifact_iri(page: AcquiredSECPage) -> str:
    digest = page.sha256.removeprefix("sha256:")
    return f"urn:ref:sec-source-artifact:rules-regulations:{digest}"


def _observation(category: SECCategoryObservation, page: AcquiredSECPage) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": category.record_iri,
        "sourceArtifact": _source_artifact_iri(page),
        "sourcePath": f"{category.collection}[{category.source_ordinal}]",
        "sourceOrdinal": category.source_ordinal,
        "labels": [
            {
                "value": category.label,
                "language": category.language,
                "role": "preferred",
            }
        ],
        # sec.gov exposes this page as Drupal menu content, not a published
        # code system; there is no publisher identifier to preserve here.
        "identifiers": [],
        "uses": ["navigation"],
        "conceptIdentityClaimed": False,
        "collection": category.collection,
        "targetPath": category.target_path,
        "sourceUrl": category.source_url,
        "sourceObservedAt": page.pin.retrieved_at,
    }
    if category.description is not None:
        row["description"] = category.description
    return row


def _package_gaps(parsed: ParsedSECRulesRegulationsPage) -> tuple[dict[str, Any], ...]:
    total = len(parsed.categories)
    return (
        {
            "code": "publisherCategoryIdentifiersAbsent",
            "affectedObservationCount": total,
            "effect": (
                "Categories remain capture-local observations; sec.gov publishes no code, "
                "id, or term IRI for a rules-regulations page category."
            ),
        },
        {
            "code": "navigationCollectionsNotReconciled",
            "affectedObservationCount": total,
            "effect": (
                "The side-navigation and subpage-card blocks label and link several of the "
                "same categories differently (for example, side navigation's Staff Guidance "
                "resolves to /rules-regulations/staff-guidance while the subpage card of the "
                "same name resolves to /regulation/staff-interpretations). Observations from "
                "each collection are kept separate and must not be merged into one taxonomy."
            ),
        },
    )


def build_sec_series_category_package(
    page: AcquiredSECPage,
    parsed: ParsedSECRulesRegulationsPage,
    *,
    resource_id: str = SEC_SERIES_CATEGORY_RESOURCE_ID,
    title: str = SEC_SERIES_CATEGORY_TITLE,
) -> SourceControlledResourceBundle:
    """Package captured page categories as development-only controlled-code-list evidence.

    The capture package never claims concept identity or a managed release:
    every observation ships ``conceptIdentityClaimed=False`` and no
    identifiers. Product policy decides whether and how to use the evidence.
    """

    if parsed.source_sha256 != page.sha256 or parsed.source_byte_length != page.byte_length:
        raise SECSourceDriftError("parsed categories differ from their acquired page bytes")
    payload = _read_acquired_payload(page)
    observations = tuple(_observation(category, page) for category in parsed.categories)
    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title=title,
        resource_kind="controlledCodeList",
        identity_status="captureLocalObservationsOnly",
        uses=("navigation",),
        captured_at=parsed.retrieved_at,
        observations=observations,
        source_artifacts={_source_artifact_iri(page): payload},
        source_observed_count=len(parsed.categories),
        gaps=_package_gaps(parsed),
    )


__all__ = [
    "SEC_LANGUAGE",
    "SEC_PUBLISHER",
    "SEC_RULES_REGULATIONS_PAGE",
    "SEC_RULES_REGULATIONS_PIN_2026_08_03",
    "SEC_SERIES_CATEGORY_RESOURCE_ID",
    "SEC_SERIES_CATEGORY_TITLE",
    "AcquiredSECPage",
    "CollectionName",
    "FetchedSECPage",
    "ParsedSECRulesRegulationsPage",
    "SECAcquisitionError",
    "SECCategoryObservation",
    "SECCategoryReadiness",
    "SECDuplicateLabelEvidence",
    "SECIdentityError",
    "SECPageFetcher",
    "SECPageSnapshotPin",
    "SECPageSource",
    "SECResourceError",
    "SECSourceDriftError",
    "acquire_sec_page",
    "build_sec_series_category_package",
    "capture_initial_sec_page_snapshot",
    "parse_sec_rules_regulations_page",
    "sec_category_readiness",
    "sec_source_record_iri",
    "sha256_digest",
]

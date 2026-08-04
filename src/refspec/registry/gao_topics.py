"""Source-faithful capture of actual GAO Topics assignments on GAO products.

GAO publishes a ``/topics`` browse index and per-topic listing pages that
enumerate a topic *category scheme* through site navigation, plus a 1998 GAO
Thesaurus that GAO itself has retired.  Neither is an actual assignment.  The
catalog decision for this source is explicit: capture only an actual GAO
assignment on a product, never reconstruct a scheme from navigation, and
never substitute the obsolete 1998 GAO Thesaurus.

This module therefore parses only one already-published GAO product page at a
time and records exactly the Topics field that page renders about itself --
the labels GAO's own publishing workflow assigned to that one report or
testimony.  It never crawls ``/topics`` or a topic listing page, and it never
turns a topic's navigational ``/topics/<slug>`` link into a minted publisher
identifier: GAO does not document that path as a stable term identifier, so
every observation carries an empty ``identifiers`` list and stays capture-
local evidence.

Live retrieval is provider-independent.  Callers inject a fetcher or provide
an already captured local file.  Importing this module never opens a network
connection.

Acquisition of one real product page is no longer unpinned.  A capture taken
through the project's Zyte transport -- ``gao-product-gao-26-108505-2026-08-
04.html``, pinned as ``GAO_PRODUCT_GAO_26_108505_2026_08_04`` below -- passed
this module's own challenge-page validation and is checked into the fixture
suite, so the real ``field--topic`` / ``views-row`` markup this parser targets
is exercised end to end rather than guessed.  Plain, direct ``curl`` still
receives gao.gov's Akamai edge "Access Denied" block (see
``_CHALLENGE_MARKERS``), so unattended live acquisition still requires an
injected proxy fetcher -- a Zyte-backed :class:`GAOPageFetcher`, not a bare
HTTP client -- passed into :func:`acquire_gao_product_page` or
:func:`capture_initial_gao_product_page_snapshot`.
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
from types import MappingProxyType
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlsplit

from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

GAO_HOSTS = frozenset({"gao.gov", "www.gao.gov"})
GAO_LANGUAGE = "en"
GAO_PRODUCT_TOPIC_ASSIGNMENTS_RESOURCE_ID = "gao-product-topic-assignments"

AcquisitionMode = Literal["cache", "local", "fetcher"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_PRODUCT_PATH = re.compile(r"^/products/(gao-[0-9]{2}-[0-9a-z]+)$")
# Observed verbatim from the real gao.gov WAF response captured while this
# module was implemented (an Akamai edge "Access Denied" block, not a
# Cloudflare challenge), plus the generic markers other RefSpec adapters
# check for so a future vendor change still fails closed.
_CHALLENGE_MARKERS = (
    b"<title>access denied</title>",
    b"errors.edgesuite.net",
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)
_NO_STABLE_TOPIC_IDENTIFIER_GAP = MappingProxyType(
    {
        "kind": "publisherTopicIdentifierUnavailable",
        "reason": (
            "gao.gov links each assigned Topic to a navigational /topics/<slug> "
            "page only; it publishes no stable topic code or IRI on the product "
            "page, and the 1998 GAO Thesaurus that once assigned codes is "
            "retired and out of scope for this capture."
        ),
    }
)


class GAOTopicsError(ValueError):
    """Base class for GAO Topics controlled-resource failures."""


class GAOAcquisitionError(GAOTopicsError):
    """Exact source bytes could not be captured safely."""


class GAOSourceDriftError(GAOTopicsError):
    """The captured publisher page no longer has the reviewed structure."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _product_slug(source_url: str) -> str:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname not in GAO_HOSTS:
        raise GAOAcquisitionError("source_url must be an official HTTPS gao.gov URL")
    if parsed.username is not None or parsed.password is not None:
        raise GAOAcquisitionError("source_url must not contain credentials")
    match = _PRODUCT_PATH.fullmatch(parsed.path)
    if match is None:
        raise GAOAcquisitionError(
            "source_url must address one GAO product page (/products/<report-id>); "
            "the /topics browse index and topic listing pages are site "
            "navigation and are never treated as an assignment source"
        )
    return match.group(1)


@dataclass(frozen=True, slots=True)
class GAOProductPageSnapshotPin:
    """Expected identity of one exact captured GAO product page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        _product_slug(self.source_url)
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GAOAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GAOAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at.strip():
            raise GAOAcquisitionError("retrieved_at must not be empty")

    @property
    def product_slug(self) -> str:
        return _product_slug(self.source_url)


# Captured 2026-08-04 through the project's Zyte transport (proxy-fetched;
# direct curl still receives gao.gov's Akamai "Access Denied" block -- see
# _CHALLENGE_MARKERS).  This is a real, currently public product page, not a
# constructed guess: it is the fixture that drove the real-markup rewrite of
# _GAOProductPageParser below (a Drupal "views-row" / "views-field-field-
# topic" block, not the field__items shape this module first guessed).
GAO_PRODUCT_GAO_26_108505_2026_08_04 = GAOProductPageSnapshotPin(
    source_url="https://www.gao.gov/products/gao-26-108505",
    retrieved_at="2026-08-04T00:18:00Z",
    expected_sha256="sha256:c50268888ddb9c7cae2277d55229394b6434ba7503d79a61cb3ff3775a0683fd",
    expected_byte_length=107_634,
)


@dataclass(frozen=True, slots=True)
class FetchedGAOPage:
    """Provider-independent result returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class GAOPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedGAOPage:
        """Fetch one official product page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredGAOProductPage:
    """One verified GAO product page in the content-addressed source store."""

    pin: GAOProductPageSnapshotPin
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
        raise GAOSourceDriftError("gao.gov returned an access-denied or challenge page instead of a product page")
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise GAOSourceDriftError("gao.gov product capture is not an HTML document")


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in GAO_HOSTS:
        raise GAOAcquisitionError("fetcher resolved_url must remain on official HTTPS gao.gov")
    if parsed.username is not None or parsed.password is not None:
        raise GAOAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_fetched_page(fetched: FetchedGAOPage, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise GAOAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise GAOSourceDriftError(f"gao.gov product page content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: GAOProductPageSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise GAOSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise GAOSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: GAOProductPageSnapshotPin) -> AcquiredGAOProductPage:
    if path.is_symlink() or not path.is_file():
        raise GAOAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached GAO product page",
    )
    return AcquiredGAOProductPage(
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
    pin: GAOProductPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredGAOProductPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} GAO product page",
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
        return AcquiredGAOProductPage(
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


def acquire_gao_product_page(
    pin: GAOProductPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: GAOPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredGAOProductPage:
    """Acquire one exact product page from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache miss.
    This keeps every live transport outside the source parser while applying
    the same digest, length, origin, and access-denied/challenge checks to
    all fetched bytes.
    """

    if timeout_seconds <= 0:
        raise GAOAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise GAOAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / f"{pin.product_slug}.html"
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise GAOAcquisitionError(f"local GAO product source is not a regular file: {local_path}")
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
        raise GAOAcquisitionError("GAO product page is not cached; provide source_path or an injected fetcher")

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


def capture_initial_gao_product_page_snapshot(
    source_url: str,
    store_dir: Path,
    *,
    retrieved_at: str,
    fetcher: GAOPageFetcher,
    timeout_seconds: float = 60.0,
) -> AcquiredGAOProductPage:
    """Capture valid first-seen bytes and return the exact pin they establish.

    This is the discovery step used before a strict
    :func:`acquire_gao_product_page` reopen.
    """

    if timeout_seconds <= 0:
        raise GAOAcquisitionError("timeout_seconds must be positive")
    if not retrieved_at.strip():
        raise GAOAcquisitionError("retrieved_at must not be empty")
    slug = _product_slug(source_url)
    fetched = fetcher.fetch(source_url, timeout_seconds=timeout_seconds)
    _validate_fetched_page(fetched, source_url=source_url)
    pin = GAOProductPageSnapshotPin(
        source_url=source_url,
        retrieved_at=retrieved_at,
        expected_sha256=sha256_digest(fetched.body),
        expected_byte_length=len(fetched.body),
    )
    digest_hex = pin.expected_sha256.removeprefix("sha256:")
    final_path = Path(store_dir) / "sha256" / digest_hex / f"{slug}.html"
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


_TRACKED_TAGS = frozenset({"div", "h1", "h2", "section", "strong", "a"})

# gao.gov's real markup links each assigned Topic through a slug, e.g.
# "/topics/auditing-and-financial-management"; this is deliberately stricter
# than a bare "/topics/" prefix check so a malformed or empty slug fails
# closed instead of being accepted as an assignment.
_TOPIC_HREF = re.compile(r"^/topics/[a-z0-9]+(?:-[a-z0-9]+)*$")


class _GAOProductPageParser(HTMLParser):
    """Collect only the elements this module treats as source evidence.

    The parser never interprets the /topics browse index; it only walks one
    already-fetched product page and records the Topics field block that page
    renders about itself.  Every structural expectation below is a check, not
    a guess: unmatched counts are left for the caller to reject as drift.

    The real gao.gov product page renders its own report number and its
    Topics assignments through Drupal render structure, not through the
    ``product-id`` / ``field--name-field-topics`` classes this module first
    guessed:

    * the product id is the text of a ``<strong>`` inside the
      ``<section class="block-post-title-info ...">`` post-title block --
      the same number also appears repeatedly in body prose and figure
      captions, so only that one structural position counts;
    * each Topic assignment is one ``<a href="/topics/<slug>">`` inside a
      ``<div class="views-field views-field-field-topic">`` row, and those
      rows only count when they sit inside the Drupal views block whose own
      ``<h2 class="... block__title ...">`` heading reads exactly "Topics".
      A sibling ``views-field-field-subject-term`` field in the same row
      (GAO's separate, uncontrolled Subject Terms) is a different field and
      is never read as a Topic.  Nav chrome such as the header's "View
      Topics" link (``href="/topics"``) and the "Jump To" menu's Topics
      entry (``class="jump-to-link ... link--topics"``) sit outside this
      views block entirely and so are structurally excluded, not merely
      filtered by text.

    Only ``div``, ``h1``, ``h2``, ``section``, ``strong``, and ``a`` push a
    stack frame.  Void elements such as ``<link>`` or ``<meta>`` are read
    directly in ``_open`` and never pushed, so a real capture that omits
    their self-closing slash cannot desync the stack from tags this parser
    actually tracks.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_href: str | None = None
        self.product_id: str | None = None
        self.title: str | None = None
        self.topic_items: list[tuple[str | None, str]] = []

        self.product_id_section_match_count = 0
        self.product_id_match_count = 0
        self.title_match_count = 0
        self.topics_root_match_count = 0
        self.topic_item_count = 0

        self._stack: list[dict[str, Any]] = []
        self._current_topic_href: str | None = None

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
            if frame["role"] in {"productId", "title", "topicAnchor", "topicsHeadingCandidate"}:
                frame["text"].append(data)

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)

        if tag == "link" and attr_map.get("rel") == "canonical" and self.canonical_href is None:
            self.canonical_href = attr_map.get("href")

        if tag not in _TRACKED_TAGS:
            return

        classes = frozenset((attr_map.get("class") or "").split())
        role: str | None = None

        if tag == "section" and "block-post-title-info" in classes:
            self.product_id_section_match_count += 1
            role = "productIdSection"

        if tag == "strong" and self.product_id is None and self._inside_open_role("productIdSection"):
            self.product_id_match_count += 1
            role = "productId"

        if tag == "h1":
            self.title_match_count += 1
            if self.title is None:
                role = "title"

        if tag == "h2" and "block__title" in classes:
            role = "topicsHeadingCandidate"

        if tag == "div" and "views-field-field-topic" in classes and self._inside_open_role("topicsRoot"):
            self.topic_item_count += 1
            role = "topicItem"

        if tag == "a" and self._current_topic_href is None and self._inside_open_role("topicItem"):
            role = "topicAnchor"
            self._current_topic_href = attr_map.get("href")

        self._stack.append({"tag": tag, "role": role, "text": []})

    def _inside_open_role(self, role: str) -> bool:
        return any(frame["role"] == role for frame in self._stack)

    def _promote_enclosing_div_to_topics_root(self) -> None:
        for candidate in reversed(self._stack):
            if candidate["tag"] == "div":
                if candidate["role"] != "topicsRoot":
                    candidate["role"] = "topicsRoot"
                    self.topics_root_match_count += 1
                return

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
        if role == "productId":
            self.product_id = _normalize_text(frame["text"])
        elif role == "title":
            self.title = _normalize_text(frame["text"])
        elif role == "topicsHeadingCandidate":
            # A Drupal views block's own <h2 ...block__title...> heading; only
            # the one that reads exactly "Topics" promotes its nearest
            # enclosing <div> to the Topics assignment root.  Other headings
            # sharing the "block__title" class (Multimedia, related products,
            # ...) never match this text and so never promote anything.
            if _normalize_text(frame["text"]) == "Topics":
                self._promote_enclosing_div_to_topics_root()
        elif role == "topicAnchor":
            href = self._current_topic_href
            self._current_topic_href = None
            self.topic_items.append((href, _normalize_text(frame["text"])))


@dataclass(frozen=True, slots=True)
class GAOTopicAssignment:
    """One exact Topic a GAO product page assigned to itself."""

    product_report_number: str
    label: str
    topic_path: str
    source_ordinal: int
    record_iri: str


@dataclass(frozen=True, slots=True)
class GAODuplicateTopicEvidence:
    """Source rows that share a Topic label but remain separate observations."""

    label: str
    record_iris: tuple[str, ...]
    source_ordinals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedGAOProductTopicsPage:
    """Parsed Topics assignments from one exact, digest-pinned product page."""

    source_url: str
    canonical_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    product_report_number: str
    product_title: str
    assignments: tuple[GAOTopicAssignment, ...]
    duplicate_topic_evidence: tuple[GAODuplicateTopicEvidence, ...]


def gao_topic_assignment_record_iri(
    source_sha256: str,
    product_report_number: str,
    source_ordinal: int,
) -> str:
    """Build a capture-local observation IRI, not a publisher identifier."""

    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise GAOSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if source_ordinal < 0:
        raise GAOSourceDriftError("source_ordinal must be non-negative")
    product = quote(product_report_number, safe="")
    return f"urn:ref:gao-topic-assignment:{match.group(1)}:{product}:{source_ordinal}"


def _duplicate_topic_evidence(
    assignments: Sequence[GAOTopicAssignment],
) -> tuple[GAODuplicateTopicEvidence, ...]:
    grouped: dict[str, list[GAOTopicAssignment]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment.label, []).append(assignment)
    return tuple(
        GAODuplicateTopicEvidence(
            label=label,
            record_iris=tuple(a.record_iri for a in matches),
            source_ordinals=tuple(a.source_ordinal for a in matches),
        )
        for label, matches in grouped.items()
        if len(matches) > 1
    )


def _read_acquired_payload(page: AcquiredGAOProductPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed GAO product page")
    return payload


def parse_gao_product_topics_page(page: AcquiredGAOProductPage) -> ParsedGAOProductTopicsPage:
    """Parse the Topics a single exact, digest-pinned GAO product page assigned to itself."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GAOSourceDriftError("gao.gov product page is not UTF-8") from error

    parser = _GAOProductPageParser()
    try:
        parser.feed(decoded)
        parser.close()
    except GAOTopicsError:
        raise
    except Exception as error:
        raise GAOSourceDriftError("gao.gov product page is malformed HTML") from error

    if parser.product_id_section_match_count != 1:
        raise GAOSourceDriftError("product page must contain exactly one product identity block")
    if parser.product_id_match_count != 1:
        raise GAOSourceDriftError("product page must contain exactly one product-id element")
    if parser.title_match_count != 1:
        raise GAOSourceDriftError("product page must contain exactly one title heading")
    if parser.topics_root_match_count != 1:
        raise GAOSourceDriftError("product page must contain exactly one Topics field block")
    if parser.canonical_href is None:
        raise GAOSourceDriftError("product page is missing its canonical link")
    if len(parser.topic_items) != parser.topic_item_count:
        raise GAOSourceDriftError("a Topics field item is missing its link")
    if not parser.topic_items:
        raise GAOSourceDriftError("product page Topics field block has no assigned topic")

    slug = page.pin.product_slug
    canonical = urlsplit(parser.canonical_href)
    if canonical.scheme != "https" or canonical.hostname not in GAO_HOSTS or canonical.path != f"/products/{slug}":
        raise GAOSourceDriftError("product page canonical link does not match its captured product URL")

    product_id = (parser.product_id or "").strip()
    if not product_id or product_id.casefold() != slug.casefold():
        raise GAOSourceDriftError(
            f"product page product-id {product_id!r} does not match its captured URL slug {slug!r}"
        )

    title = (parser.title or "").strip()
    if not title:
        raise GAOSourceDriftError("product page title must not be empty")

    for href, label in parser.topic_items:
        if not href or _TOPIC_HREF.fullmatch(href) is None:
            raise GAOSourceDriftError(f"Topics field item links outside /topics/<slug>: {href!r}")
        if not label:
            raise GAOSourceDriftError("Topics field item has no label text")

    assignments = tuple(
        GAOTopicAssignment(
            product_report_number=product_id,
            label=label,
            topic_path=href,
            source_ordinal=ordinal,
            record_iri=gao_topic_assignment_record_iri(page.sha256, product_id, ordinal),
        )
        for ordinal, (href, label) in enumerate(parser.topic_items)
        if href is not None
    )

    return ParsedGAOProductTopicsPage(
        source_url=page.pin.source_url,
        canonical_url=parser.canonical_href,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        product_report_number=product_id,
        product_title=title,
        assignments=assignments,
        duplicate_topic_evidence=_duplicate_topic_evidence(assignments),
    )


def _observation(parsed: ParsedGAOProductTopicsPage, assignment: GAOTopicAssignment) -> dict[str, Any]:
    return {
        "id": assignment.record_iri,
        "sourceArtifact": parsed.source_url,
        "sourcePath": f"topics.viewsRow[{assignment.source_ordinal}].viewsFieldFieldTopic",
        "sourceOrdinal": assignment.source_ordinal,
        "labels": [
            {
                "value": assignment.label,
                "language": GAO_LANGUAGE,
                "role": "preferred",
            }
        ],
        # gao.gov links each Topic to a navigational /topics/<slug> path only;
        # it documents no stable publisher code or IRI for the term, so this
        # module never mints one.
        "identifiers": [],
        "uses": ["sourceAssignedEvidence"],
        "conceptIdentityClaimed": False,
        "productReportNumber": parsed.product_report_number,
        "productTitle": parsed.product_title,
        "topicPath": assignment.topic_path,
    }


def build_gao_product_topic_assignments_package(
    page: AcquiredGAOProductPage,
    parsed: ParsedGAOProductTopicsPage,
) -> SourceControlledResourceBundle:
    """Package one product page's actual Topics assignments as source evidence.

    This never promotes the result into a concept scheme: ``resource_kind``
    stays ``sourceTermSnapshot`` and every observation's ``identifiers`` list
    stays empty. Candidate authorization does not apply to this non-atlas
    package.
    """

    payload = page.path.read_bytes()
    if len(payload) != page.byte_length or sha256_digest(payload) != page.sha256:
        raise GAOSourceDriftError("GAO product page package source differs from its acquired pin")
    if parsed.source_sha256 != page.sha256:
        raise GAOSourceDriftError("parsed GAO product page and acquired page digests differ")
    if parsed.source_url != page.pin.source_url:
        raise GAOSourceDriftError("parsed GAO product page source_url differs from its acquired pin")

    observations = tuple(_observation(parsed, assignment) for assignment in parsed.assignments)
    return build_source_controlled_resource_bundle(
        resource_id=GAO_PRODUCT_TOPIC_ASSIGNMENTS_RESOURCE_ID,
        title="GAO product page Topics assignments",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("sourceAssignedEvidence",),
        captured_at=parsed.retrieved_at,
        observations=observations,
        source_artifacts={parsed.source_url: payload},
        gaps=(_NO_STABLE_TOPIC_IDENTIFIER_GAP,),
    )


__all__ = [
    "GAO_HOSTS",
    "GAO_LANGUAGE",
    "GAO_PRODUCT_TOPIC_ASSIGNMENTS_RESOURCE_ID",
    "AcquiredGAOProductPage",
    "AcquisitionMode",
    "FetchedGAOPage",
    "GAOAcquisitionError",
    "GAODuplicateTopicEvidence",
    "GAOPageFetcher",
    "GAOProductPageSnapshotPin",
    "GAOSourceDriftError",
    "GAOTopicAssignment",
    "GAOTopicsError",
    "ParsedGAOProductTopicsPage",
    "acquire_gao_product_page",
    "build_gao_product_topic_assignments_package",
    "capture_initial_gao_product_page_snapshot",
    "gao_topic_assignment_record_iri",
    "parse_gao_product_topics_page",
    "sha256_digest",
]

"""Source-faithful CRS Product Types and Product Topics capture and parsing.

Congress.gov's CRS products help page documents a small set of product-type
genres (Report, In Focus, Insight, Legal Sidebar, Infographic, Testimony, and
Appropriations Status Table) and explains that every CRS product edition
carries its own topic labels.  The page does not publish topics as a
separately governed, enumerable thesaurus: a topic label is source evidence
tied to one product edition, not a stable concept with an identifier.

This module preserves exact page bytes, official product-type labels and
descriptions as genre metadata, and the page's own explanation of how topics
work as a source-evidence scope note.  It never enumerates or merges topic
labels into a controlled term list, and it does not mint concept identity
from a label or list position.  A separate pure helper preserves the topic
labels actually observed on one product edition without merging them across
editions or products.

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
from typing import Literal, Protocol, cast
from urllib.parse import quote, urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode

CRS_PUBLISHER = "Congressional Research Service"
CONGRESS_GOV_PUBLISHER = "Library of Congress"
CRS_LANGUAGE = "en"

ProductTopicsRole = Literal["genreMetadata", "sourceEvidenceOnly"]
IdentityStatus = Literal["publisherIdentifierAbsent", "publisherIdentifierPresent"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_OFFICIAL_HOSTNAMES = frozenset({"congress.gov", "www.congress.gov"})
_PRODUCT_EDITION_HOSTNAMES = frozenset(
    {"congress.gov", "www.congress.gov", "crsreports.congress.gov"}
)
_CHALLENGE_MARKERS = (
    b"cf-chl-",
    b"challenge-platform",
    b"cf-mitigated",
    b"attention required! | cloudflare",
    b"just a moment...</title>",
)


class CRSProductResourceError(ValueError):
    """Base class for CRS Product Types and Product Topics failures."""


class CRSProductAcquisitionError(CRSProductResourceError):
    """Exact source bytes, or supplied evidence, could not be captured safely."""


class CRSProductSourceDriftError(CRSProductResourceError):
    """The captured publisher source no longer has the reviewed structure."""


class CRSProductIdentityError(CRSProductResourceError):
    """A managed release was requested without authoritative term identity."""


@dataclass(frozen=True, slots=True)
class CRSProductsPageSource:
    """The official CRS products help page and the structure it must show."""

    source_url: str
    filename: str
    expected_heading: str
    product_types_heading: str
    expected_product_type_count: int
    topics_heading: str
    topics_marker_phrase: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTNAMES:
            raise CRSProductAcquisitionError("source_url must be an official HTTPS Congress.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise CRSProductAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise CRSProductAcquisitionError("filename must be one plain path component")
        if self.expected_product_type_count <= 0:
            raise CRSProductAcquisitionError("expected_product_type_count must be positive")
        if not self.expected_heading or not self.product_types_heading or not self.topics_heading:
            raise CRSProductAcquisitionError("expected_heading, product_types_heading, and topics_heading are required")
        if not self.topics_marker_phrase:
            raise CRSProductAcquisitionError("topics_marker_phrase must not be empty")


# The live publisher page captured through Zyte on 2026-08-03 contains a
# seven-row Product/Description table. It mentions CRS Product Topic as a
# search/filter field, but does not publish an enumerable topic list.
CRS_PRODUCTS_PAGE = CRSProductsPageSource(
    source_url="https://www.congress.gov/help/crs-products",
    filename="crs-products.html",
    expected_heading="Congressional Research Service (CRS) Products",
    product_types_heading="CRS Product Types",
    expected_product_type_count=7,
    topics_heading="Searching CRS products",
    topics_marker_phrase="CRS Product Topic",
)


@dataclass(frozen=True, slots=True)
class CRSProductsPageSnapshotPin:
    """Expected identity of one exact capture of the CRS products help page."""

    source: CRSProductsPageSource
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise CRSProductAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise CRSProductAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise CRSProductAcquisitionError("retrieved_at must not be empty")


@dataclass(frozen=True, slots=True)
class FetchedCRSProductsPage:
    """Provider-independent result returned by an injected page fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class CRSProductsPageFetcher(Protocol):
    """Minimal transport boundary implemented by direct or proxy fetchers."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedCRSProductsPage:
        """Fetch the official page without changing its bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredCRSProductsPage:
    """One verified capture of the CRS products help page in content-addressed storage."""

    pin: CRSProductsPageSnapshotPin
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
class CRSProductType:
    """One exact product-type genre entry observed on the help page."""

    official_label: str
    description: str
    source_ordinal: int
    record_iri: str
    source_url: str
    identifiers: tuple[ControlledIdentifier, ...] = ()

    @property
    def role(self) -> ProductTopicsRole:
        return "genreMetadata"

    @property
    def identity_status(self) -> IdentityStatus:
        return "publisherIdentifierPresent" if self.identifiers else "publisherIdentifierAbsent"


@dataclass(frozen=True, slots=True)
class CRSProductTopicsScopeNote:
    """The page's own explanation of how product topics work, kept verbatim."""

    text: str
    source_ordinal: int
    record_iri: str
    source_url: str

    @property
    def role(self) -> ProductTopicsRole:
        return "sourceEvidenceOnly"

    @property
    def identity_status(self) -> IdentityStatus:
        return "publisherIdentifierAbsent"


@dataclass(frozen=True, slots=True)
class ParsedCRSProductsPage:
    """Parsed product types and the topics scope note from one pinned capture."""

    source: CRSProductsPageSource
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    product_types: tuple[CRSProductType, ...]
    topics_scope_note: CRSProductTopicsScopeNote


@dataclass(frozen=True, slots=True)
class CRSProductTopicsManagedReleaseReadiness:
    """Why the captured page can or cannot become a managed release."""

    source_digest: str
    product_type_count: int
    ready: bool
    blockers: tuple[str, ...]

    def require_ready(self) -> None:
        """Fail rather than promoting genre labels or topic text into a scheme."""

        if not self.ready:
            raise CRSProductIdentityError("; ".join(self.blockers))


@dataclass(frozen=True, slots=True)
class ParsedCRSProductTopicsResource:
    """A complete source-level view of the CRS Product Types and Topics page."""

    page: ParsedCRSProductsPage
    readiness: CRSProductTopicsManagedReleaseReadiness


@dataclass(frozen=True, slots=True)
class CRSProductEditionTopicAssignment:
    """Topic labels observed on exactly one CRS product edition.

    Congress.gov attaches topics to a specific product edition, not to a
    reusable governed thesaurus.  Every call preserves exactly one edition's
    labels; callers must never merge labels across editions or products.
    """

    product_number: str
    edition_label: str
    topic_labels: tuple[str, ...]
    source_url: str
    retrieved_at: str
    record_iri: str

    @property
    def role(self) -> ProductTopicsRole:
        return "sourceEvidenceOnly"

    @property
    def identity_status(self) -> IdentityStatus:
        return "publisherIdentifierAbsent"


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _crs_product_record_iri(
    category: Literal["productType", "productTopicsScopeNote"],
    *,
    source_sha256: str,
    source_ordinal: int,
) -> str:
    match = _DIGEST.fullmatch(source_sha256)
    if match is None:
        raise CRSProductSourceDriftError("source_sha256 must be a lowercase sha256:<64 hex> digest")
    if source_ordinal <= 0:
        raise CRSProductSourceDriftError("source_ordinal must be positive")
    return f"urn:ref:crs-product-source-record:{match.group(1)}:{category}:{source_ordinal}"


def _validate_official_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTNAMES:
        raise CRSProductAcquisitionError("fetcher resolved_url must remain on official HTTPS Congress.gov")
    if parsed.username is not None or parsed.password is not None:
        raise CRSProductAcquisitionError("fetcher resolved_url must not contain credentials")


def _validate_html_payload(payload: bytes) -> None:
    lowered = payload[:64_000].lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        raise CRSProductSourceDriftError("Congress.gov returned a challenge page instead of the CRS products help page")
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise CRSProductSourceDriftError("Congress.gov CRS products capture is not an HTML document")


def _validate_fetched_page(fetched: FetchedCRSProductsPage, *, source_url: str) -> None:
    if fetched.status_code != 200:
        raise CRSProductAcquisitionError(f"could not acquire {source_url}: HTTP {fetched.status_code}")
    _validate_official_resolved_url(fetched.resolved_url)
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise CRSProductSourceDriftError(f"CRS products help page content type drifted to {fetched.content_type!r}")
    _validate_html_payload(fetched.body)


def _verify_payload(payload: bytes, pin: CRSProductsPageSnapshotPin, *, location: str) -> tuple[str, int]:
    _validate_html_payload(payload)
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise CRSProductSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise CRSProductSourceDriftError(f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}")
    return actual_sha256, byte_length


def _verify_existing(path: Path, pin: CRSProductsPageSnapshotPin) -> AcquiredCRSProductsPage:
    if path.is_symlink() or not path.is_file():
        raise CRSProductAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached CRS products page",
    )
    return AcquiredCRSProductsPage(
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
    pin: CRSProductsPageSnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredCRSProductsPage:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} CRS products page",
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
        return AcquiredCRSProductsPage(
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


def acquire_crs_products_page(
    pin: CRSProductsPageSnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: CRSProductsPageFetcher | None = None,
    timeout_seconds: float = 60.0,
) -> AcquiredCRSProductsPage:
    """Acquire the CRS products help page from cache, a local capture, or an injected fetcher.

    The caller supplies either ``source_path`` or ``fetcher`` on a cache
    miss.  This keeps any live transport outside the source parser while
    applying the same digest, length, origin, and challenge-page checks to
    all fetched bytes.
    """

    if timeout_seconds <= 0:
        raise CRSProductAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise CRSProductAcquisitionError("provide source_path or fetcher, not both")

    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.source.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise CRSProductAcquisitionError(f"local CRS products source is not a regular file: {local_path}")
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
        raise CRSProductAcquisitionError("CRS products page is not cached; provide source_path or an injected fetcher")

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


class _ProductsPageParser(HTMLParser):
    """Collect headings, paragraphs, definition lists, and two-column tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.paragraphs: list[tuple[str, str]] = []
        self.definition_lists: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self.tables: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self._heading_tag: str | None = None
        self._heading_text: list[str] | None = None
        self._current_heading = ""
        self._p_text: list[str] | None = None
        self._dl_stack: list[list[tuple[str, str]]] = []
        self._dl_heading_stack: list[str] = []
        self._dt_text: list[str] | None = None
        self._dd_text: list[str] | None = None
        self._pending_term: str | None = None
        self._table_rows: list[tuple[str, str]] | None = None
        self._table_heading = ""
        self._row_cells: list[str] | None = None
        self._cell_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"h1", "h2", "h3"}:
            self._heading_tag = tag
            self._heading_text = []
        elif tag == "p":
            self._p_text = []
        elif tag == "dl":
            self._dl_stack.append([])
            self._dl_heading_stack.append(self._current_heading)
        elif tag == "dt":
            self._dt_text = []
        elif tag == "dd":
            self._dd_text = []
        elif tag == "table":
            self._table_rows = []
            self._table_heading = self._current_heading
        elif tag == "tr" and self._table_rows is not None:
            self._row_cells = []
        elif tag in {"th", "td"} and self._row_cells is not None:
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._heading_text is not None:
            self._heading_text.append(data)
        if self._p_text is not None:
            self._p_text.append(data)
        if self._dt_text is not None:
            self._dt_text.append(data)
        if self._dd_text is not None:
            self._dd_text.append(data)
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag and self._heading_text is not None:
            text = _normalize_text(self._heading_text)
            if text:
                self.headings.append(text)
                self._current_heading = text
            self._heading_tag = None
            self._heading_text = None
        elif tag == "p" and self._p_text is not None:
            text = _normalize_text(self._p_text)
            if text:
                self.paragraphs.append((self._current_heading, text))
            self._p_text = None
        elif tag == "dt" and self._dt_text is not None:
            self._pending_term = _normalize_text(self._dt_text)
            self._dt_text = None
        elif tag == "dd" and self._dd_text is not None:
            text = _normalize_text(self._dd_text)
            if self._dl_stack and self._pending_term is not None:
                self._dl_stack[-1].append((self._pending_term, text))
            self._pending_term = None
            self._dd_text = None
        elif tag == "dl" and self._dl_stack:
            pairs = tuple(self._dl_stack.pop())
            heading = self._dl_heading_stack.pop()
            if pairs:
                self.definition_lists.append((heading, pairs))
        elif tag in {"th", "td"} and self._cell_text is not None:
            if self._row_cells is not None:
                self._row_cells.append(_normalize_text(self._cell_text))
            self._cell_text = None
        elif tag == "tr" and self._row_cells is not None:
            if len(self._row_cells) == 2 and self._row_cells != ["Product", "Description"]:
                self._table_rows.append((self._row_cells[0], self._row_cells[1]))
            self._row_cells = None
        elif tag == "table" and self._table_rows is not None:
            if self._table_rows:
                self.tables.append((self._table_heading, tuple(self._table_rows)))
            self._table_rows = None


def _normalize_text(chunks: Sequence[str]) -> str:
    return " ".join("".join(chunks).split())


def _read_acquired_payload(page: AcquiredCRSProductsPage) -> bytes:
    payload = page.path.read_bytes()
    _verify_payload(payload, page.pin, location="parsed CRS products page")
    return payload


def parse_crs_products_page(page: AcquiredCRSProductsPage) -> ParsedCRSProductsPage:
    """Parse product types and the topics scope note from one pinned capture."""

    payload = _read_acquired_payload(page)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CRSProductSourceDriftError("CRS products help page is not UTF-8") from error

    parser = _ProductsPageParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as error:
        raise CRSProductSourceDriftError("CRS products help page is malformed HTML") from error

    source = page.pin.source
    if not any(source.expected_heading in heading for heading in parser.headings):
        raise CRSProductSourceDriftError(f"missing expected heading {source.expected_heading!r}")

    matching_collections = [
        pairs
        for heading, pairs in (*parser.definition_lists, *parser.tables)
        if heading in {
            source.product_types_heading,
            f"{source.product_types_heading} ({source.expected_product_type_count})",
        }
    ]
    if len(matching_collections) != 1:
        raise CRSProductSourceDriftError(
            f"missing one {source.product_types_heading!r} definition list or two-column table"
        )
    pairs = matching_collections[0]
    if len(pairs) != source.expected_product_type_count:
        raise CRSProductSourceDriftError(
            f"CRS Product Types count drift: expected {source.expected_product_type_count}, parsed {len(pairs)}"
        )
    labels = [label for label, _description in pairs]
    if len(set(labels)) != len(labels):
        raise CRSProductSourceDriftError("CRS Product Types page contains duplicate labels")
    product_types = tuple(
        CRSProductType(
            official_label=label,
            description=description,
            source_ordinal=ordinal,
            record_iri=_crs_product_record_iri(
                "productType",
                source_sha256=page.sha256,
                source_ordinal=ordinal,
            ),
            source_url=source.source_url,
        )
        for ordinal, (label, description) in enumerate(pairs, start=1)
    )

    if not any(source.topics_heading in heading for heading in parser.headings):
        raise CRSProductSourceDriftError(f"missing expected {source.topics_heading!r} heading")
    topic_paragraphs = [text for heading, text in parser.paragraphs if heading == source.topics_heading]
    scope_note_text = " ".join(topic_paragraphs)
    if source.topics_marker_phrase not in scope_note_text:
        raise CRSProductSourceDriftError(
            f"missing expected CRS Product Topics scope-note marker phrase {source.topics_marker_phrase!r}"
        )
    topics_scope_note = CRSProductTopicsScopeNote(
        text=scope_note_text,
        source_ordinal=1,
        record_iri=_crs_product_record_iri(
            "productTopicsScopeNote",
            source_sha256=page.sha256,
            source_ordinal=1,
        ),
        source_url=source.source_url,
    )

    return ParsedCRSProductsPage(
        source=source,
        source_sha256=page.sha256,
        source_byte_length=page.byte_length,
        retrieved_at=page.pin.retrieved_at,
        product_types=product_types,
        topics_scope_note=topics_scope_note,
    )


def assemble_crs_product_topics(page: ParsedCRSProductsPage) -> ParsedCRSProductTopicsResource:
    """Package the parsed page while explicitly refusing a managed release.

    Congress.gov supplies neither publisher identifiers for product types
    nor an enumerable, versioned topic vocabulary, so a managed release
    remains blocked until an authoritative identity source is reviewed.
    """

    blockers = (
        "Congress.gov does not publish stable identifiers for CRS product types",
        (
            "CRS Product Topics are source evidence tied to individual product "
            "editions, not an enumerable governed thesaurus"
        ),
        "Congress.gov does not publish this help page as a named, versioned vocabulary release",
    )
    readiness = CRSProductTopicsManagedReleaseReadiness(
        source_digest=page.source_sha256,
        product_type_count=len(page.product_types),
        ready=False,
        blockers=blockers,
    )
    return ParsedCRSProductTopicsResource(page=page, readiness=readiness)


def capture_product_edition_topic_assignment(
    *,
    product_number: str,
    edition_label: str,
    topic_labels: Sequence[str],
    source_url: str,
    retrieved_at: str,
) -> CRSProductEditionTopicAssignment:
    """Preserve one product edition's topic labels as source evidence.

    Congress.gov attaches topics to a specific product edition, not to a
    reusable governed thesaurus.  Each call records exactly one edition's
    labels in source order with duplicates removed; callers must not merge
    labels across editions or products.
    """

    product = product_number.strip()
    if not product:
        raise CRSProductSourceDriftError("product_number must not be empty")
    edition = edition_label.strip()
    if not edition:
        raise CRSProductSourceDriftError("edition_label must not be empty")
    parsed_url = urlsplit(source_url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in _PRODUCT_EDITION_HOSTNAMES:
        raise CRSProductAcquisitionError("source_url must be an official HTTPS Congress.gov product URL")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise CRSProductAcquisitionError("source_url must not contain credentials")
    retrieved = retrieved_at.strip()
    if not retrieved:
        raise CRSProductAcquisitionError("retrieved_at must not be empty")

    labels: list[str] = []
    for raw_label in topic_labels:
        text = raw_label.strip()
        if not text:
            raise CRSProductSourceDriftError("topic_labels must not contain empty values")
        if text not in labels:
            labels.append(text)
    if not labels:
        raise CRSProductSourceDriftError("topic_labels must not be empty")

    record_iri = f"urn:ref:crs-product-edition-topic:{quote(product, safe='')}:{quote(edition, safe='')}"
    return CRSProductEditionTopicAssignment(
        product_number=product,
        edition_label=edition,
        topic_labels=tuple(labels),
        source_url=source_url,
        retrieved_at=retrieved,
        record_iri=record_iri,
    )

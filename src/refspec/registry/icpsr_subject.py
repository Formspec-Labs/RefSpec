"""Bounded acquisition and identity-safe parsing for the ICPSR Subject Thesaurus.

ICPSR publishes two complementary public views:

* 27 server-rendered letter indexes publish the official numeric term code and
  public term URI for every preferred and non-preferred term.
* The ICPSR metadata repository publishes XML containing the authored
  thesaurus semantics, including USE/UF, BT/NT/RT, scope notes, and timestamps.

This module joins those sources by an exact, unique authored label.  The label
is only a join key between two ICPSR publications; it is never used to mint a
concept identifier.  Missing, duplicate, ambiguous, or role-conflicting joins
fail closed.

Importing this module never opens a network connection.  Live acquisition is
explicit and accepts an injectable page fetcher so a permitted browser or
managed acquisition service can be used when the public site rejects a direct
HTTP client.
"""

from __future__ import annotations

import hashlib
import html.parser
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from refspec.registry.infrastructure.controlled_identifier import (
    ControlledIdentifier,
    identifier_values,
    validate_identifier_date,
)

ICPSR_SUBJECT_SCHEME_IRI = "https://www.icpsr.umich.edu/web/ICPSR/thesaurus/10001"
ICPSR_ROBOTS_URL = "https://www.icpsr.umich.edu/robots.txt"
ICPSR_INDEX_LETTERS = (*"abcdefghijklmnopqrstuvwxyz", "#")
ICPSR_INDEX_PARSER_VERSION = "refspec-icpsr-index-v1"
ICPSR_XML_PARSER_VERSION = "refspec-icpsr-xml-v1"
ICPSR_SUBJECT_XML_REVISION = "6e2651e55fb42b119a167f34000ec728d1206865"
ICPSR_SUBJECT_XML_URL = (
    "https://raw.githubusercontent.com/ICPSR/metadata/"
    f"{ICPSR_SUBJECT_XML_REVISION}/projects/thesaurus/processed/subject.xml"
)
ICPSR_SUBJECT_XML_SHA256 = "sha256:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff"
ICPSR_SUBJECT_XML_BYTE_LENGTH = 1_244_558
ICPSR_USER_AGENT = "RefSpec bounded ICPSR public-index resolver/1.0 (research capture; contact via repository)"
DEFAULT_MAX_PAGE_BYTES = 2 * 1024 * 1024
DEFAULT_MINIMUM_INTERVAL_SECONDS = 1.0
ICPSR_TERM_CODE_KIND = "publisherCode"
ICPSR_TERM_URI_KIND = "publisherTermUri"

_TERM_PATH = re.compile(r"^/web/ICPSR/thesaurus/10001/terms/([1-9][0-9]*)$")
_ALLOWED_XML_TAGS = frozenset(
    {
        "DESCRIPTOR",
        "NON-DESCRIPTOR",
        "SN",
        "BT",
        "NT",
        "RT",
        "USE",
        "UF",
        "INP",
        "UPD",
        "TNR",
    }
)


class IcpsrSubjectError(ValueError):
    """ICPSR acquisition or parsing could not preserve source meaning."""


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _index_url(letter: str) -> str:
    return ICPSR_SUBJECT_SCHEME_IRI + "?" + urllib.parse.urlencode({"letter": letter})


def _require_nonempty_text(value: str | None, field: str) -> str:
    if value is None:
        raise IcpsrSubjectError(f"{field} is missing")
    text = value.strip()
    if not text:
        raise IcpsrSubjectError(f"{field} must not be empty")
    return text


@dataclass(frozen=True, slots=True)
class IcpsrFetchedPage:
    """One bounded page response supplied by an acquisition transport."""

    requested_url: str
    resolved_url: str
    status_code: int
    content_type: str | None
    body: bytes

    def __post_init__(self) -> None:
        for value, field in (
            (self.requested_url, "requested_url"),
            (self.resolved_url, "resolved_url"),
        ):
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise IcpsrSubjectError(f"{field} must be an absolute HTTP(S) URL")
        if self.status_code < 100 or self.status_code > 599:
            raise IcpsrSubjectError("status_code must be an HTTP status")
        if not isinstance(self.body, bytes):
            raise IcpsrSubjectError("page body must be bytes")


class IcpsrPageFetcher(Protocol):
    """Transport boundary used by the bounded index acquisition."""

    def __call__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> IcpsrFetchedPage: ...


def fetch_icpsr_page_with_urllib(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
) -> IcpsrFetchedPage:
    """Fetch one page directly; callers must opt into this transport."""

    if timeout_seconds <= 0:
        raise IcpsrSubjectError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise IcpsrSubjectError("max_bytes must be positive")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,text/plain;q=0.9",
            "User-Agent": ICPSR_USER_AGENT,
        },
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as error:
        if error.code == 403:
            raise IcpsrSubjectError(
                "ICPSR denied the direct HTTP request with status 403; "
                "supply a permitted browser-backed or managed page fetcher"
            ) from error
        raise IcpsrSubjectError(f"ICPSR returned HTTP {error.code} for {url}") from error
    except (OSError, urllib.error.URLError) as error:
        raise IcpsrSubjectError(f"could not fetch {url}: {error}") from error
    with response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise IcpsrSubjectError(f"ICPSR response exceeds max_bytes={max_bytes}: {url}")
        return IcpsrFetchedPage(
            requested_url=url,
            resolved_url=response.geturl(),
            status_code=getattr(response, "status", 200),
            content_type=response.headers.get("Content-Type"),
            body=body,
        )


@dataclass(frozen=True, slots=True)
class IcpsrIndexTerm:
    """One official identity observed in an ICPSR letter index."""

    label: str
    preferred: bool
    source_letter: str
    identifiers: tuple[ControlledIdentifier, ...]

    @property
    def code(self) -> str:
        """Compatibility view of the one required ICPSR numeric code."""

        values = identifier_values(
            self.identifiers,
            kinds=frozenset({ICPSR_TERM_CODE_KIND}),
        )
        if len(values) != 1:
            raise IcpsrSubjectError("ICPSR term must contain exactly one publisher code")
        return values[0]

    @property
    def concept_iri(self) -> str:
        """Compatibility view of the one required public term URI."""

        values = identifier_values(
            self.identifiers,
            kinds=frozenset({ICPSR_TERM_URI_KIND}),
        )
        if len(values) != 1:
            raise IcpsrSubjectError("ICPSR term must contain exactly one publisher term URI")
        return values[0]


@dataclass(frozen=True, slots=True)
class IcpsrIndexPage:
    """Exact bytes and parsed identities for one source index page."""

    letter: str
    requested_url: str
    resolved_url: str
    sha256: str
    byte_length: int
    body: bytes
    terms: tuple[IcpsrIndexTerm, ...]


@dataclass(frozen=True, slots=True)
class IcpsrSubjectIndex:
    """One captured official index, complete or explicitly partial."""

    robots_url: str
    robots_sha256: str
    robots_body: bytes
    pages: tuple[IcpsrIndexPage, ...]
    terms: tuple[IcpsrIndexTerm, ...]
    complete: bool
    observed_at: str | None
    capture_digest: str

    def term_by_label(self) -> dict[str, IcpsrIndexTerm]:
        return {term.label: term for term in self.terms}


class _IcpsrLetterIndexParser(html.parser.HTMLParser):
    def __init__(self, *, source_letter: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_letter = source_letter
        self._heading_level: str | None = None
        self._heading_text: list[str] = []
        self._in_terms = False
        self._term_href: str | None = None
        self._term_text: list[str] = []
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"h1", "h2"}:
            self._heading_level = tag
            self._heading_text = []
            return
        if tag != "a" or not self._in_terms:
            return
        href = dict(attrs).get("href")
        if href is None:
            return
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(ICPSR_SUBJECT_SCHEME_IRI, href))
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.icpsr.umich.edu"
            or parsed.query
            or parsed.fragment
            or _TERM_PATH.fullmatch(parsed.path) is None
        ):
            return
        self._term_href = parsed.path
        self._term_text = []

    def handle_data(self, data: str) -> None:
        if self._heading_level is not None:
            self._heading_text.append(data)
        if self._term_href is not None:
            self._term_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_level:
            heading = " ".join("".join(self._heading_text).split())
            self._in_terms = self._heading_level == "h2" and heading == "Terms"
            self._heading_level = None
            self._heading_text = []
            return
        if tag == "a" and self._term_href is not None:
            label = " ".join("".join(self._term_text).split())
            self.rows.append((self._term_href, label))
            self._term_href = None
            self._term_text = []


def parse_icpsr_index_page(
    payload: bytes,
    *,
    letter: str,
    requested_url: str | None = None,
    resolved_url: str | None = None,
    observed_at: str | None = None,
) -> IcpsrIndexPage:
    """Parse one captured letter page without performing network access."""

    if letter not in ICPSR_INDEX_LETTERS:
        raise IcpsrSubjectError(f"unsupported ICPSR index letter {letter!r}")
    requested = requested_url or _index_url(letter)
    resolved = resolved_url or requested
    if observed_at is not None:
        validate_identifier_date(observed_at, "ICPSR index observed_at")
    page_sha256 = _sha256(payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IcpsrSubjectError(f"ICPSR index {letter!r} is not valid UTF-8") from error
    parser = _IcpsrLetterIndexParser(source_letter=letter)
    parser.feed(text)
    parser.close()

    terms: list[IcpsrIndexTerm] = []
    seen_codes: set[str] = set()
    seen_labels: set[str] = set()
    for path, displayed_label in parser.rows:
        match = _TERM_PATH.fullmatch(path)
        if match is None:
            raise IcpsrSubjectError(f"ICPSR index {letter!r} exposed an invalid term path")
        code = match.group(1)
        preferred = not displayed_label.endswith("*")
        label = _require_nonempty_text(
            displayed_label[:-1] if not preferred else displayed_label,
            f"ICPSR index {letter!r} term label",
        )
        if code in seen_codes:
            raise IcpsrSubjectError(f"ICPSR index {letter!r} repeats term code {code}")
        if label in seen_labels:
            raise IcpsrSubjectError(f"ICPSR index {letter!r} repeats term label {label!r}")
        seen_codes.add(code)
        seen_labels.add(label)
        terms.append(
            IcpsrIndexTerm(
                label=label,
                preferred=preferred,
                source_letter=letter,
                identifiers=(
                    ControlledIdentifier(
                        value=code,
                        kind=ICPSR_TERM_CODE_KIND,
                        authority_uri=ICPSR_SUBJECT_SCHEME_IRI,
                        source_uri=requested,
                        observed_at=observed_at,
                        effective_at=None,
                        source_digest=page_sha256,
                    ),
                    ControlledIdentifier(
                        value=(f"{ICPSR_SUBJECT_SCHEME_IRI}/terms/{code}"),
                        kind=ICPSR_TERM_URI_KIND,
                        authority_uri=ICPSR_SUBJECT_SCHEME_IRI,
                        source_uri=requested,
                        observed_at=observed_at,
                        effective_at=None,
                        source_digest=page_sha256,
                    ),
                ),
            )
        )
    if letter != "#" and not terms:
        raise IcpsrSubjectError(f"ICPSR index {letter!r} contains no official term links")
    return IcpsrIndexPage(
        letter=letter,
        requested_url=requested,
        resolved_url=resolved,
        sha256=page_sha256,
        byte_length=len(payload),
        body=payload,
        terms=tuple(terms),
    )


def build_icpsr_subject_index(
    pages: Mapping[str, bytes | IcpsrFetchedPage],
    *,
    robots_body: bytes,
    require_complete: bool = True,
    observed_at: str | None = None,
) -> IcpsrSubjectIndex:
    """Build and digest an offline index capture from exact page bytes."""

    supplied_letters = set(pages)
    if observed_at is not None:
        validate_identifier_date(observed_at, "ICPSR capture observed_at")
    unknown = supplied_letters - set(ICPSR_INDEX_LETTERS)
    if unknown:
        raise IcpsrSubjectError("unsupported ICPSR index letters: " + ", ".join(sorted(unknown)))
    if require_complete and supplied_letters != set(ICPSR_INDEX_LETTERS):
        missing = set(ICPSR_INDEX_LETTERS) - supplied_letters
        raise IcpsrSubjectError("complete ICPSR index capture is missing: " + ", ".join(sorted(missing)))
    parsed_pages: list[IcpsrIndexPage] = []
    for letter in ICPSR_INDEX_LETTERS:
        if letter not in pages:
            continue
        page = pages[letter]
        if isinstance(page, IcpsrFetchedPage):
            if page.status_code != 200:
                raise IcpsrSubjectError(f"ICPSR index {letter!r} returned HTTP {page.status_code}")
            parsed = parse_icpsr_index_page(
                page.body,
                letter=letter,
                requested_url=page.requested_url,
                resolved_url=page.resolved_url,
                observed_at=observed_at,
            )
        elif isinstance(page, bytes):
            parsed = parse_icpsr_index_page(
                page,
                letter=letter,
                observed_at=observed_at,
            )
        else:
            raise IcpsrSubjectError(f"ICPSR index {letter!r} must be bytes or a fetched page")
        parsed_pages.append(parsed)

    all_terms: list[IcpsrIndexTerm] = []
    code_owner: dict[str, str] = {}
    label_owner: dict[str, str] = {}
    for page in parsed_pages:
        for term in page.terms:
            if term.code in code_owner:
                raise IcpsrSubjectError(
                    f"ICPSR term code {term.code} appears on both {code_owner[term.code]!r} and {page.letter!r} indexes"
                )
            if term.label in label_owner:
                raise IcpsrSubjectError(
                    f"ICPSR term label {term.label!r} appears on both "
                    f"{label_owner[term.label]!r} and {page.letter!r} indexes"
                )
            code_owner[term.code] = page.letter
            label_owner[term.label] = page.letter
            all_terms.append(term)

    manifest = {
        "parserVersion": ICPSR_INDEX_PARSER_VERSION,
        "schemeIri": ICPSR_SUBJECT_SCHEME_IRI,
        "observedAt": observed_at,
        "robots": {
            "url": ICPSR_ROBOTS_URL,
            "sha256": _sha256(robots_body),
            "byteLength": len(robots_body),
        },
        "pages": [
            {
                "letter": page.letter,
                "url": page.requested_url,
                "resolvedUrl": page.resolved_url,
                "sha256": page.sha256,
                "byteLength": page.byte_length,
            }
            for page in parsed_pages
        ],
        "terms": [
            {
                "code": term.code,
                "conceptIri": term.concept_iri,
                "identifiers": [identifier.as_dict() for identifier in term.identifiers],
                "label": term.label,
                "preferred": term.preferred,
                "sourceLetter": term.source_letter,
            }
            for term in all_terms
        ],
        "complete": supplied_letters == set(ICPSR_INDEX_LETTERS),
    }
    return IcpsrSubjectIndex(
        robots_url=ICPSR_ROBOTS_URL,
        robots_sha256=_sha256(robots_body),
        robots_body=robots_body,
        pages=tuple(parsed_pages),
        terms=tuple(all_terms),
        complete=manifest["complete"],
        observed_at=observed_at,
        capture_digest=_sha256(_canonical_json(manifest)),
    )


def _capture_manifest(index: IcpsrSubjectIndex) -> dict[str, object]:
    return {
        "captureDigest": index.capture_digest,
        "parserVersion": ICPSR_INDEX_PARSER_VERSION,
        "schemeIri": ICPSR_SUBJECT_SCHEME_IRI,
        "complete": index.complete,
        "observedAt": index.observed_at,
        "robots": {
            "url": index.robots_url,
            "sha256": index.robots_sha256,
            "byteLength": len(index.robots_body),
            "path": "robots.txt",
        },
        "pages": [
            {
                "letter": page.letter,
                "url": page.requested_url,
                "resolvedUrl": page.resolved_url,
                "sha256": page.sha256,
                "byteLength": page.byte_length,
                "path": ("pages/hash.html" if page.letter == "#" else f"pages/{page.letter}.html"),
            }
            for page in index.pages
        ],
        "terms": [
            {
                "code": term.code,
                "conceptIri": term.concept_iri,
                "identifiers": [identifier.as_dict() for identifier in term.identifiers],
                "label": term.label,
                "preferred": term.preferred,
                "sourceLetter": term.source_letter,
            }
            for term in index.terms
        ],
    }


def _publish_exact_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise IcpsrSubjectError(f"ICPSR capture target is not a regular file: {path}")
        if path.read_bytes() != payload:
            raise IcpsrSubjectError(f"ICPSR capture target contains different bytes: {path}")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".icpsr-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            if path.is_symlink() or path.read_bytes() != payload:
                raise IcpsrSubjectError(f"ICPSR capture target changed during publication: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def write_icpsr_subject_index_capture(
    index: IcpsrSubjectIndex,
    output_dir: Path,
) -> Path:
    """Write exact captured pages and a deterministic manifest."""

    destination = Path(output_dir)
    _publish_exact_file(destination / "robots.txt", index.robots_body)
    for page in index.pages:
        filename = "hash.html" if page.letter == "#" else f"{page.letter}.html"
        _publish_exact_file(destination / "pages" / filename, page.body)
    manifest_path = destination / "manifest.json"
    _publish_exact_file(
        manifest_path,
        _canonical_json(_capture_manifest(index)) + b"\n",
    )
    return manifest_path


def acquire_icpsr_subject_index(
    *,
    fetch_page: IcpsrPageFetcher | None = None,
    allow_direct_network: bool = False,
    timeout_seconds: float = 30.0,
    max_page_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    minimum_interval_seconds: float = DEFAULT_MINIMUM_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    observed_at: str | None = None,
) -> IcpsrSubjectIndex:
    """Acquire robots plus all 27 official index pages at a bounded rate."""

    if timeout_seconds <= 0:
        raise IcpsrSubjectError("timeout_seconds must be positive")
    if max_page_bytes <= 0:
        raise IcpsrSubjectError("max_page_bytes must be positive")
    if minimum_interval_seconds < 0:
        raise IcpsrSubjectError("minimum_interval_seconds must not be negative")
    if fetch_page is None:
        if not allow_direct_network:
            raise IcpsrSubjectError("live ICPSR acquisition requires fetch_page or allow_direct_network=True")
        fetch_page = fetch_icpsr_page_with_urllib

    requests_made = 0

    def fetch(url: str) -> IcpsrFetchedPage:
        nonlocal requests_made
        if requests_made:
            sleep(minimum_interval_seconds)
        requests_made += 1
        if requests_made > len(ICPSR_INDEX_LETTERS) + 1:
            raise IcpsrSubjectError("ICPSR acquisition exceeded its 28-request bound")
        page = fetch_page(
            url,
            timeout_seconds=timeout_seconds,
            max_bytes=max_page_bytes,
        )
        if page.requested_url != url:
            raise IcpsrSubjectError("page fetcher returned a different requested_url")
        if len(page.body) > max_page_bytes:
            raise IcpsrSubjectError(f"page fetcher exceeded max_page_bytes={max_page_bytes}")
        if page.status_code != 200:
            raise IcpsrSubjectError(f"ICPSR returned HTTP {page.status_code} for {url}")
        return page

    robots = fetch(ICPSR_ROBOTS_URL)
    try:
        robots_text = robots.body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IcpsrSubjectError("ICPSR robots.txt is not valid UTF-8") from error
    robots_policy = urllib.robotparser.RobotFileParser()
    robots_policy.set_url(ICPSR_ROBOTS_URL)
    robots_policy.parse(robots_text.splitlines())
    for letter in ICPSR_INDEX_LETTERS:
        url = _index_url(letter)
        if not robots_policy.can_fetch(ICPSR_USER_AGENT, url):
            raise IcpsrSubjectError(f"ICPSR robots.txt disallows the public index URL {url}")

    pages = {letter: fetch(_index_url(letter)) for letter in ICPSR_INDEX_LETTERS}
    if requests_made != len(ICPSR_INDEX_LETTERS) + 1:
        raise IcpsrSubjectError("ICPSR acquisition request count drifted")
    return build_icpsr_subject_index(
        pages,
        robots_body=robots.body,
        require_complete=True,
        observed_at=observed_at,
    )


@dataclass(frozen=True, slots=True)
class IcpsrXmlTerm:
    """One lossless semantic record from the ICPSR XML source."""

    source_local_record_number: str
    label: str
    preferred: bool
    scope_notes: tuple[str, ...]
    broader_labels: tuple[str, ...]
    narrower_labels: tuple[str, ...]
    related_labels: tuple[str, ...]
    use_labels: tuple[str, ...]
    used_for_labels: tuple[str, ...]
    input_timestamp: str | None
    update_timestamp: str | None


@dataclass(frozen=True, slots=True)
class IcpsrXmlSnapshot:
    """Parsed XML with exact source-byte identity."""

    source_sha256: str
    source_byte_length: int
    terms: tuple[IcpsrXmlTerm, ...]


def _xml_values(
    concept: ElementTree.Element,
    tag: str,
) -> tuple[str, ...]:
    return tuple(_require_nonempty_text(child.text, tag) for child in concept.findall(tag))


def _optional_single_xml_value(
    concept: ElementTree.Element,
    tag: str,
) -> str | None:
    values = _xml_values(concept, tag)
    if len(values) > 1:
        raise IcpsrSubjectError(f"ICPSR XML repeats {tag}")
    return values[0] if values else None


def parse_icpsr_subject_xml(payload: bytes) -> IcpsrXmlSnapshot:
    """Parse the authored XML while retaining every supported source field."""

    upper_prefix = payload[:4096].upper()
    if b"<!DOCTYPE" in upper_prefix or b"<!ENTITY" in upper_prefix:
        raise IcpsrSubjectError("ICPSR XML must not declare a DTD or entity")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise IcpsrSubjectError("ICPSR subject XML is malformed") from error
    if root.tag != "THESAURUS":
        raise IcpsrSubjectError("ICPSR XML root must be THESAURUS")

    terms: list[IcpsrXmlTerm] = []
    seen_labels: set[str] = set()
    seen_record_numbers: set[str] = set()
    for ordinal, concept in enumerate(root, start=1):
        if concept.tag != "CONCEPT":
            raise IcpsrSubjectError(f"ICPSR XML root child {ordinal} must be CONCEPT")
        unknown_tags = {child.tag for child in concept} - _ALLOWED_XML_TAGS
        if unknown_tags:
            raise IcpsrSubjectError("ICPSR XML contains unsupported fields: " + ", ".join(sorted(unknown_tags)))
        descriptors = _xml_values(concept, "DESCRIPTOR")
        non_descriptors = _xml_values(concept, "NON-DESCRIPTOR")
        if len(descriptors) + len(non_descriptors) != 1:
            raise IcpsrSubjectError(f"ICPSR XML record {ordinal} must contain exactly one DESCRIPTOR or NON-DESCRIPTOR")
        preferred = bool(descriptors)
        label = (descriptors or non_descriptors)[0]
        record_number = _require_nonempty_text(
            _optional_single_xml_value(concept, "TNR"),
            f"ICPSR XML record {ordinal} TNR",
        )
        if label in seen_labels:
            raise IcpsrSubjectError(f"ICPSR XML repeats term label {label!r}")
        if record_number in seen_record_numbers:
            raise IcpsrSubjectError(f"ICPSR XML repeats source-local TNR {record_number}")
        seen_labels.add(label)
        seen_record_numbers.add(record_number)
        terms.append(
            IcpsrXmlTerm(
                source_local_record_number=record_number,
                label=label,
                preferred=preferred,
                scope_notes=_xml_values(concept, "SN"),
                broader_labels=_xml_values(concept, "BT"),
                narrower_labels=_xml_values(concept, "NT"),
                related_labels=_xml_values(concept, "RT"),
                use_labels=_xml_values(concept, "USE"),
                used_for_labels=_xml_values(concept, "UF"),
                input_timestamp=_optional_single_xml_value(concept, "INP"),
                update_timestamp=_optional_single_xml_value(concept, "UPD"),
            )
        )
    if not terms:
        raise IcpsrSubjectError("ICPSR XML contains no CONCEPT records")
    return IcpsrXmlSnapshot(
        source_sha256=_sha256(payload),
        source_byte_length=len(payload),
        terms=tuple(terms),
    )


def open_pinned_icpsr_subject_xml(path: Path) -> IcpsrXmlSnapshot:
    """Open and verify the exact XML revision used by the development bridge."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise IcpsrSubjectError(f"ICPSR XML source is not a regular file: {source}")
    payload = source.read_bytes()
    if len(payload) != ICPSR_SUBJECT_XML_BYTE_LENGTH:
        raise IcpsrSubjectError("ICPSR XML byte length does not match the pinned revision")
    actual_sha256 = _sha256(payload)
    if actual_sha256 != ICPSR_SUBJECT_XML_SHA256:
        raise IcpsrSubjectError("ICPSR XML digest does not match the pinned revision")
    return parse_icpsr_subject_xml(payload)


@dataclass(frozen=True, slots=True)
class IcpsrResolvedTerm:
    """One XML semantic record bound to official ICPSR identities."""

    identity: IcpsrIndexTerm
    source_local_record_number: str
    scope_notes: tuple[str, ...]
    broader: tuple[IcpsrIndexTerm, ...]
    narrower: tuple[IcpsrIndexTerm, ...]
    related: tuple[IcpsrIndexTerm, ...]
    use: tuple[IcpsrIndexTerm, ...]
    used_for: tuple[IcpsrIndexTerm, ...]
    input_timestamp: str | None
    update_timestamp: str | None


@dataclass(frozen=True, slots=True)
class IcpsrResolvedThesaurus:
    """Identity-safe XML/index join plus visible version skew."""

    xml_sha256: str
    xml_byte_length: int
    index_capture_digest: str
    terms: tuple[IcpsrResolvedTerm, ...]
    index_only_terms: tuple[IcpsrIndexTerm, ...]


@dataclass(frozen=True, slots=True)
class IcpsrRoleConflict:
    """One label whose preferred/non-preferred role changed between sources."""

    label: str
    xml_preferred: bool
    index_preferred: bool


@dataclass(frozen=True, slots=True)
class IcpsrCompatibilityReport:
    """Exact overlap and drift between one XML and public-index snapshot."""

    xml_sha256: str
    index_capture_digest: str
    xml_term_count: int
    index_term_count: int
    matched_term_count: int
    xml_only_labels: tuple[str, ...]
    index_only_terms: tuple[IcpsrIndexTerm, ...]
    role_conflicts: tuple[IcpsrRoleConflict, ...]

    @property
    def compatible(self) -> bool:
        """Whether every XML term can bind to a current official identity."""

        return not self.xml_only_labels and not self.role_conflicts


def compare_icpsr_xml_to_official_index(
    xml: IcpsrXmlSnapshot,
    index: IcpsrSubjectIndex,
    *,
    require_complete_index: bool = True,
) -> IcpsrCompatibilityReport:
    """Report source-version drift without guessing missing identities."""

    if require_complete_index and not index.complete:
        raise IcpsrSubjectError("an identity compatibility report requires all 27 index pages")
    identities = index.term_by_label()
    xml_by_label = {term.label: term for term in xml.terms}
    xml_labels = set(xml_by_label)
    index_labels = set(identities)
    shared_labels = xml_labels & index_labels
    return IcpsrCompatibilityReport(
        xml_sha256=xml.source_sha256,
        index_capture_digest=index.capture_digest,
        xml_term_count=len(xml.terms),
        index_term_count=len(index.terms),
        matched_term_count=len(shared_labels),
        xml_only_labels=tuple(sorted(xml_labels - index_labels)),
        index_only_terms=tuple(
            sorted(
                (term for term in index.terms if term.label not in xml_labels),
                key=lambda term: (term.label, term.code),
            )
        ),
        role_conflicts=tuple(
            IcpsrRoleConflict(
                label=label,
                xml_preferred=xml_by_label[label].preferred,
                index_preferred=identities[label].preferred,
            )
            for label in sorted(shared_labels)
            if xml_by_label[label].preferred is not identities[label].preferred
        ),
    )


def join_icpsr_xml_to_official_index(
    xml: IcpsrXmlSnapshot,
    index: IcpsrSubjectIndex,
    *,
    require_complete_index: bool = True,
    require_no_index_only_terms: bool = False,
) -> IcpsrResolvedThesaurus:
    """Bind XML semantics to public identities without minting from labels."""

    compatibility = compare_icpsr_xml_to_official_index(
        xml,
        index,
        require_complete_index=require_complete_index,
    )
    identities = index.term_by_label()
    if compatibility.xml_only_labels:
        preview = ", ".join(repr(label) for label in compatibility.xml_only_labels[:5])
        raise IcpsrSubjectError(
            f"{len(compatibility.xml_only_labels)} XML terms lack an official "
            "public "
            f"identity; first missing labels: {preview}"
        )
    if compatibility.role_conflicts:
        conflict = compatibility.role_conflicts[0]
        xml_role = "DESCRIPTOR" if conflict.xml_preferred else "NON-DESCRIPTOR"
        index_role = "preferred" if conflict.index_preferred else "non-preferred"
        raise IcpsrSubjectError(
            f"ICPSR role mismatch for {conflict.label!r}: XML publishes {xml_role}, public index publishes {index_role}"
        )

    def resolve_labels(
        labels: Sequence[str],
        *,
        source_label: str,
        relation: str,
        expected_preferred: bool | None,
    ) -> tuple[IcpsrIndexTerm, ...]:
        resolved: list[IcpsrIndexTerm] = []
        for label in labels:
            identity = identities.get(label)
            if identity is None:
                raise IcpsrSubjectError(
                    f"{source_label!r} {relation} target {label!r} lacks an official public identity"
                )
            if expected_preferred is not None and identity.preferred is not expected_preferred:
                role = "preferred" if expected_preferred else "non-preferred"
                raise IcpsrSubjectError(f"{source_label!r} {relation} target {label!r} is not published as {role}")
            resolved.append(identity)
        return tuple(resolved)

    resolved_terms: list[IcpsrResolvedTerm] = []
    for term in xml.terms:
        identity = identities[term.label]
        if identity.preferred is not term.preferred:
            xml_role = "DESCRIPTOR" if term.preferred else "NON-DESCRIPTOR"
            index_role = "preferred" if identity.preferred else "non-preferred"
            raise IcpsrSubjectError(
                f"ICPSR role mismatch for {term.label!r}: XML publishes {xml_role}, public index publishes {index_role}"
            )
        resolved_terms.append(
            IcpsrResolvedTerm(
                identity=identity,
                source_local_record_number=term.source_local_record_number,
                scope_notes=term.scope_notes,
                broader=resolve_labels(
                    term.broader_labels,
                    source_label=term.label,
                    relation="BT",
                    expected_preferred=True,
                ),
                narrower=resolve_labels(
                    term.narrower_labels,
                    source_label=term.label,
                    relation="NT",
                    expected_preferred=True,
                ),
                related=resolve_labels(
                    term.related_labels,
                    source_label=term.label,
                    relation="RT",
                    expected_preferred=True,
                ),
                use=resolve_labels(
                    term.use_labels,
                    source_label=term.label,
                    relation="USE",
                    expected_preferred=True,
                ),
                used_for=resolve_labels(
                    term.used_for_labels,
                    source_label=term.label,
                    relation="UF",
                    expected_preferred=False,
                ),
                input_timestamp=term.input_timestamp,
                update_timestamp=term.update_timestamp,
            )
        )
    index_only = compatibility.index_only_terms
    if require_no_index_only_terms and index_only:
        raise IcpsrSubjectError(f"official index contains {len(index_only)} terms absent from the XML snapshot")
    return IcpsrResolvedThesaurus(
        xml_sha256=xml.source_sha256,
        xml_byte_length=xml.source_byte_length,
        index_capture_digest=index.capture_digest,
        terms=tuple(resolved_terms),
        index_only_terms=index_only,
    )


__all__ = [
    "DEFAULT_MAX_PAGE_BYTES",
    "DEFAULT_MINIMUM_INTERVAL_SECONDS",
    "ICPSR_INDEX_LETTERS",
    "ICPSR_INDEX_PARSER_VERSION",
    "ICPSR_ROBOTS_URL",
    "ICPSR_SUBJECT_SCHEME_IRI",
    "ICPSR_SUBJECT_XML_BYTE_LENGTH",
    "ICPSR_SUBJECT_XML_REVISION",
    "ICPSR_SUBJECT_XML_SHA256",
    "ICPSR_SUBJECT_XML_URL",
    "ICPSR_TERM_CODE_KIND",
    "ICPSR_TERM_URI_KIND",
    "ICPSR_USER_AGENT",
    "ICPSR_XML_PARSER_VERSION",
    "IcpsrCompatibilityReport",
    "IcpsrFetchedPage",
    "IcpsrIndexPage",
    "IcpsrIndexTerm",
    "IcpsrPageFetcher",
    "IcpsrResolvedTerm",
    "IcpsrResolvedThesaurus",
    "IcpsrRoleConflict",
    "IcpsrSubjectError",
    "IcpsrSubjectIndex",
    "IcpsrXmlSnapshot",
    "IcpsrXmlTerm",
    "acquire_icpsr_subject_index",
    "build_icpsr_subject_index",
    "compare_icpsr_xml_to_official_index",
    "fetch_icpsr_page_with_urllib",
    "join_icpsr_xml_to_official_index",
    "open_pinned_icpsr_subject_xml",
    "parse_icpsr_index_page",
    "parse_icpsr_subject_xml",
    "write_icpsr_subject_index_capture",
]

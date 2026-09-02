"""GAO's published /topics browse index from gao.gov.

REF-032 removed the observed GAO topics unit: one topic label observed on one
report page, carrying RefSpec-minted UUIDv7 identity and
``publisherConceptIdentityClaimed: False``. Its named follow-up is the index
GAO itself publishes: the ``https://www.gao.gov/topics`` page, whose
``Browse Topics Alphabetically`` listing enumerates 30 publisher topics. It is
not the vocabulary boundary: GAO's own Science and Technology topic page is a
31st captured term that the browse page omits (REF-060). The publisher's own
markup states the identity this module relies on: each topic is rendered as a Drupal taxonomy term
(``<div id="taxonomy-term-<id>" class="... taxonomy-term vocabulary-topic">``)
with a stable ``/topics/<slug>`` path, a name field, and the publisher's own
scope description. Slug and numeric term id are both publisher-minted; nothing
here is RefSpec-invented identity.

The same page carries a four-entry "featured topics" block of content nodes
(``node--type-featured-topic``) that are not taxonomy terms; the parser
counts and reports them but never emits them as topics.

Publisher renderings are preserved verbatim, including the misspelled
description class the publisher serves (``taxonomy-term-descripiton``); the
parser targets that exact spelling and treats its absence as drift, not as
something to repair.

Importing this module performs no network access. gao.gov returns 403 to
plain HTTP clients (an Akamai challenge); the pinned capture was fetched
through the shared Zyte transport
(``refspec.registry.infrastructure.zyte_transport``), which returned the
publisher's 200 response.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

GAO_PUBLISHER = "U.S. Government Accountability Office"
GAO_TOPICS_URL = "https://www.gao.gov/topics"
GAO_PAGE_HOST = "https://www.gao.gov"
GAO_SCIENCE_AND_TECHNOLOGY_URL = f"{GAO_PAGE_HOST}/topics/science-and-technology"

# The publisher's own listing title, and how many topics that LISTING holds
# in the pinned capture. A different title or count is drift in the listing.
#
# It is not GAO's vocabulary. The browse page shows 30 slugs, but
# /topics/science-and-technology is a live taxonomy term of the same shape
# that the listing does not name (verified 2026-08-22; a consumer joining
# GAO's own Topic Area assignments hit it on 2 of 47 reports). So this count
# bounds a page, never the world: read as completeness it would license the
# claim that a report's topic outside these 30 does not exist, which is
# false, and the refusal below would reject a capture in which GAO published
# a 31st topic -- the one case where drift is the news rather than the error.
GAO_TOPICS_LISTING_TITLE = "Browse Topics Alphabetically"
#: How many topics the browse LISTING names, not how many topics GAO has.
GAO_TOPICS_LISTED_COUNT = 30
#: Retained under its former name: this module's consumers pin it.
GAO_TOPICS_EXPECTED_COUNT = GAO_TOPICS_LISTED_COUNT

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOPIC_HREF = re.compile(r"^/topics/[a-z0-9-]+$")
_TERM_DIV_ID = re.compile(r"^taxonomy-term-([1-9]\d*)$")
_TOPIC_PAGE_TITLE_BLOCK_ID = "block-gao-uswds-page-title"


class GaoPublishedTopicsError(ValueError):
    """Base class for GAO published-topics index failures."""


class GaoSourceDriftError(GaoPublishedTopicsError):
    """The page no longer matches the reviewed structure or pin."""


@dataclass(frozen=True, slots=True)
class GaoPagePin:
    """Exact identity of one captured gao.gov page."""

    source_url: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if not self.source_url.startswith("https://www.gao.gov/"):
            raise GaoPublishedTopicsError("source_url must be an official HTTPS gao.gov URL")
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise GaoPublishedTopicsError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise GaoPublishedTopicsError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise GaoPublishedTopicsError("retrieved_at must not be empty")


GAO_TOPICS_2026_08_15 = GaoPagePin(
    source_url=GAO_TOPICS_URL,
    retrieved_at="2026-08-15T13:56:14Z",
    expected_sha256="sha256:9aa9e7f185b9433236f512a6f694f6c9cf57f109bba3e9ea99ac42de19180096",
    expected_byte_length=122_070,
)

GAO_SCIENCE_AND_TECHNOLOGY_2026_09_01 = GaoPagePin(
    source_url=GAO_SCIENCE_AND_TECHNOLOGY_URL,
    # The bounded Zyte capture command completed at 23:33:02.718Z. The pin
    # records that completion to whole-second precision; it does not invent a
    # midnight time or claim a publisher-server timestamp that was not kept.
    retrieved_at="2026-09-01T23:33:02Z",
    expected_sha256="sha256:98391cad16eba43e48017782765088d8720116ba988e1591d85215804906d0cd",
    expected_byte_length=148_620,
)


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class GaoPublishedTopic:
    """One topic exactly as the publisher's index states it."""

    slug: str
    term_id: str
    name: str
    description: str
    page_href: str
    page_url: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class GaoPublishedTopicsIndex:
    """The parsed, digest-pinned 30-row browse index."""

    topics: tuple[GaoPublishedTopic, ...]
    listing_title: str
    featured_entry_hrefs: tuple[str, ...]
    source_sha256: str
    source_byte_length: int
    retrieved_at: str

    def by_slug(self) -> dict[str, GaoPublishedTopic]:
        return {topic.slug: topic for topic in self.topics}


@dataclass(frozen=True, slots=True)
class GaoPublishedTopicPage:
    """One publisher topic identity stated by its own GAO taxonomy page."""

    slug: str
    term_id: str
    name: str
    page_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str


def _normalized(pieces: list[str]) -> str:
    return " ".join("".join(pieces).split())


class _TopicsParser(HTMLParser):
    """Collect taxonomy-term topic entries and featured-topic content nodes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.listing_titles: list[str] = []
        self.entries: list[dict[str, object]] = []
        self.featured_hrefs: list[str] = []
        self._collect: str | None = None
        self._buffer: list[str] = []
        self._entry_depth = 0
        self._collect_depth = 0
        self._featured_depth = 0
        self._featured_href_taken = False

    def _current(self) -> dict[str, object]:
        return self.entries[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "h2" and "block-views-blocktopics-block-topic-listing__title" in classes:
            self._collect = "listing-title"
            self._buffer = []
            return
        if tag == "div" and self._featured_depth == 0 and "node--type-featured-topic" in classes:
            self._featured_depth = 1
            self._featured_href_taken = False
            return
        if self._featured_depth > 0:
            if tag == "div":
                self._featured_depth += 1
            if tag == "a" and not self._featured_href_taken:
                self.featured_hrefs.append(attributes.get("href") or "")
                self._featured_href_taken = True
            return
        if tag == "div" and self._entry_depth == 0 and "taxonomy-term" in classes and "vocabulary-topic" in classes:
            matched = _TERM_DIV_ID.fullmatch(attributes.get("id") or "")
            if matched is None:
                raise GaoSourceDriftError(
                    f"GAO topic term div carries an unsupported id: {attributes.get('id')!r}"
                )
            self.entries.append({"termId": matched.group(1), "hrefs": [], "name": None, "description": None})
            self._entry_depth = 1
            return
        if self._entry_depth == 0:
            return
        if tag == "div":
            self._entry_depth += 1
            if "field--name-name" in classes:
                self._collect = "name"
                self._buffer = []
                self._collect_depth = self._entry_depth
            elif "taxonomy-term-descripiton" in classes:
                # The publisher's own misspelled class name, targeted verbatim.
                self._collect = "description"
                self._buffer = []
                self._collect_depth = self._entry_depth
            return
        if tag == "a":
            href = attributes.get("href")
            if href is not None:
                hrefs = self._current()["hrefs"]
                assert isinstance(hrefs, list)
                hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._collect == "listing-title":
            self.listing_titles.append(_normalized(self._buffer))
            self._collect = None
            self._buffer = []
            return
        if self._featured_depth > 0:
            if tag == "div":
                self._featured_depth -= 1
            return
        if self._entry_depth > 0 and tag == "div":
            if self._collect in {"name", "description"} and self._entry_depth == self._collect_depth:
                field = self._collect
                current = self._current()
                if current[field] is not None:
                    raise GaoSourceDriftError(f"GAO topic term repeats its {field} field")
                current[field] = _normalized(self._buffer)
                self._collect = None
                self._buffer = []
            self._entry_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._collect is not None:
            self._buffer.append(data)


_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)


class _TopicPageParser(HTMLParser):
    """Read the independent identity claims on one GAO taxonomy-term page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_urls: list[str] = []
        self.og_titles: list[str] = []
        self.document_titles: list[str] = []
        self.heading_titles: list[str] = []
        self.term_ids: list[str] = []
        self.settings_payloads: list[str] = []
        self.page_title_block_count = 0
        self._document_title: list[str] | None = None
        self._heading: list[str] | None = None
        self._heading_depth = 0
        self._page_title_depth = 0
        self._settings: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "section" and attributes.get("id") == _TOPIC_PAGE_TITLE_BLOCK_ID:
            self.page_title_block_count += 1
            if self._page_title_depth > 0:
                raise GaoSourceDriftError("GAO topic page nests its page-title block")
            self._page_title_depth = 1
        elif self._page_title_depth > 0 and tag not in _VOID_ELEMENTS:
            self._page_title_depth += 1
        if self._heading is not None:
            if tag not in _VOID_ELEMENTS:
                self._heading_depth += 1
            return
        if tag == "link" and "canonical" in (attributes.get("rel") or "").split():
            self.canonical_urls.append(attributes.get("href") or "")
        elif tag == "meta" and attributes.get("property") == "og:title":
            self.og_titles.append(attributes.get("content") or "")
        elif tag == "title":
            self._document_title = []
        elif tag == "h1" and "split-headings" in classes and self._page_title_depth > 0:
            self._heading = []
            self._heading_depth = 0
        elif tag == "article" and {"taxonomy-term", "vocabulary-topic"} <= set(classes):
            matched = _TERM_DIV_ID.fullmatch(attributes.get("id") or "")
            if matched is None:
                raise GaoSourceDriftError(
                    f"GAO topic page carries an unsupported taxonomy identity: {attributes.get('id')!r}"
                )
            self.term_ids.append(matched.group(1))
        elif tag == "script" and attributes.get("data-drupal-selector") == "drupal-settings-json":
            self._settings = []

    def handle_endtag(self, tag: str) -> None:
        if self._heading is not None:
            if tag == "h1" and self._heading_depth == 0:
                self.heading_titles.append(_normalized(self._heading))
                self._heading = None
            elif tag not in _VOID_ELEMENTS and self._heading_depth > 0:
                self._heading_depth -= 1
        elif tag == "title" and self._document_title is not None:
            self.document_titles.append(_normalized(self._document_title))
            self._document_title = None
        elif tag == "script" and self._settings is not None:
            self.settings_payloads.append("".join(self._settings))
            self._settings = None
        if self._page_title_depth > 0 and tag not in _VOID_ELEMENTS:
            self._page_title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._heading is not None and self._heading_depth == 0:
            self._heading.append(data)
        elif self._document_title is not None:
            self._document_title.append(data)
        elif self._settings is not None:
            self._settings.append(data)


def _verified_page_digest(payload: bytes, pin: GaoPagePin, *, page_name: str) -> str:
    if len(payload) != pin.expected_byte_length:
        raise GaoSourceDriftError(
            f"{page_name} byte length drift: expected {pin.expected_byte_length}, got {len(payload)}"
        )
    actual = sha256_digest(payload)
    if actual != pin.expected_sha256:
        raise GaoSourceDriftError(
            f"{page_name} digest drift: expected {pin.expected_sha256}, got {actual}"
        )
    return actual


def parse_gao_topic_page(
    payload: bytes,
    *,
    pin: GaoPagePin,
) -> GaoPublishedTopicPage:
    """Parse one publisher-owned GAO topic page from exact captured bytes.

    This deliberately does not infer vocabulary membership from product rows.
    The page must independently agree on its canonical slug, visible name,
    numeric Drupal taxonomy id, and ``vocabulary-topic`` class.  For ``B``
    input bytes, parsing costs ``O(B)`` time and ``O(B)`` memory because
    ``HTMLParser`` consumes decoded text; no corpus-sized state is retained.
    """

    actual = _verified_page_digest(payload, pin, page_name="GAO topic page")
    parsed_url = urlsplit(pin.source_url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "www.gao.gov":
        raise GaoPublishedTopicsError("GAO topic page pin must name www.gao.gov over HTTPS")
    matched_href = _TOPIC_HREF.fullmatch(parsed_url.path)
    if matched_href is None or parsed_url.query or parsed_url.fragment:
        raise GaoPublishedTopicsError("GAO topic page pin must name one canonical /topics/<slug> URL")
    slug = parsed_url.path.removeprefix("/topics/")

    parser = _TopicPageParser()
    parser.feed(payload.decode("utf-8"))
    parser.close()
    if parser.canonical_urls != [pin.source_url]:
        raise GaoSourceDriftError(
            f"GAO topic page canonical URL drifted: expected {[pin.source_url]!r}, observed {parser.canonical_urls!r}"
        )
    if len(parser.term_ids) != 1:
        raise GaoSourceDriftError(
            f"GAO topic page taxonomy identity drifted: expected one term, observed {parser.term_ids!r}"
        )
    term_id = parser.term_ids[0]
    if len(parser.settings_payloads) != 1:
        raise GaoSourceDriftError("GAO topic page must carry one Drupal settings payload")
    try:
        settings = json.loads(parser.settings_payloads[0])
        current_path = settings["path"]["currentPath"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise GaoSourceDriftError("GAO topic page Drupal taxonomy path is invalid") from error
    if current_path != f"taxonomy/term/{term_id}":
        raise GaoSourceDriftError(
            f"GAO topic page taxonomy identity disagrees: article {term_id!r}, settings {current_path!r}"
        )
    if parser.page_title_block_count != 1:
        raise GaoSourceDriftError(
            "GAO topic page must carry one #block-gao-uswds-page-title page-title block"
        )
    if len(parser.heading_titles) != 1 or not parser.heading_titles[0].strip():
        raise GaoSourceDriftError(
            "GAO topic page must carry one nonempty h1.split-headings in its page-title block"
        )
    name = parser.heading_titles[0].strip()
    if parser.og_titles != [name]:
        raise GaoSourceDriftError(
            f"GAO topic page Open Graph name drifted: expected {[name]!r}, observed {parser.og_titles!r}"
        )
    if parser.document_titles != [f"U.S. GAO - {name}"]:
        raise GaoSourceDriftError(
            f"GAO topic page document title drifted: observed {parser.document_titles!r}"
        )
    return GaoPublishedTopicPage(
        slug=slug,
        term_id=term_id,
        name=name,
        page_url=pin.source_url,
        source_sha256=actual,
        source_byte_length=len(payload),
        retrieved_at=pin.retrieved_at,
    )


def parse_gao_published_topics(
    payload: bytes,
    *,
    pin: GaoPagePin = GAO_TOPICS_2026_08_15,
) -> GaoPublishedTopicsIndex:
    """Parse the publisher's browse index from exact page bytes."""

    actual = _verified_page_digest(payload, pin, page_name="GAO topics page")

    parser = _TopicsParser()
    parser.feed(payload.decode("utf-8"))
    parser.close()

    if parser.listing_titles != [GAO_TOPICS_LISTING_TITLE]:
        raise GaoSourceDriftError(
            f"GAO topics listing title drifted: expected [{GAO_TOPICS_LISTING_TITLE!r}], "
            f"observed {parser.listing_titles!r}"
        )
    if len(parser.entries) != GAO_TOPICS_LISTED_COUNT:
        raise GaoSourceDriftError(
            f"GAO browse listing drifted: it named {GAO_TOPICS_LISTED_COUNT} topics when pinned "
            f"and names {len(parser.entries)} now. This bounds the listing, not GAO's "
            "vocabulary -- /topics/science-and-technology is a live term the listing omits."
        )

    topics: list[GaoPublishedTopic] = []
    for ordinal, entry in enumerate(parser.entries, start=1):
        term_id = entry["termId"]
        name = entry["name"]
        description = entry["description"]
        hrefs = entry["hrefs"]
        assert isinstance(term_id, str) and isinstance(hrefs, list)
        if not isinstance(name, str) or not name:
            raise GaoSourceDriftError(f"GAO topic term {term_id} has no name field")
        if not isinstance(description, str) or not description:
            raise GaoSourceDriftError(f"GAO topic {name!r} has no description")
        distinct_hrefs = set(hrefs)
        if len(distinct_hrefs) != 1:
            raise GaoSourceDriftError(
                f"GAO topic {name!r} links to more than one path: {sorted(distinct_hrefs)!r}"
            )
        href = hrefs[0]
        if _TOPIC_HREF.fullmatch(href) is None:
            raise GaoSourceDriftError(f"GAO topic {name!r} has an unsupported href: {href!r}")
        topics.append(
            GaoPublishedTopic(
                slug=href.removeprefix("/topics/"),
                term_id=term_id,
                name=name,
                description=description,
                page_href=href,
                page_url=GAO_PAGE_HOST + href,
                source_ordinal=ordinal,
            )
        )

    if len({topic.slug for topic in topics}) != len(topics):
        raise GaoSourceDriftError("GAO topic index repeats a slug")
    if len({topic.term_id for topic in topics}) != len(topics):
        raise GaoSourceDriftError("GAO topic index repeats a taxonomy term id")
    names = [topic.name for topic in topics]
    if names != sorted(names, key=str.casefold):
        raise GaoSourceDriftError("GAO topic index is not alphabetical, contradicting its own title")

    # Featured entries are content nodes, never taxonomy terms. One that
    # resolves to a /topics/ path would mean this exclusion is dropping a
    # real topic, so that is drift, not something to skip silently.
    featured = tuple(parser.featured_hrefs)
    for href in featured:
        if not href.startswith("/") or _TOPIC_HREF.fullmatch(href) is not None:
            raise GaoSourceDriftError(f"GAO featured entry has an unsupported href: {href!r}")
    return GaoPublishedTopicsIndex(
        topics=tuple(topics),
        listing_title=GAO_TOPICS_LISTING_TITLE,
        featured_entry_hrefs=featured,
        source_sha256=actual,
        source_byte_length=len(payload),
        retrieved_at=pin.retrieved_at,
    )


__all__ = [
    "GAO_PAGE_HOST",
    "GAO_PUBLISHER",
    "GAO_SCIENCE_AND_TECHNOLOGY_2026_09_01",
    "GAO_SCIENCE_AND_TECHNOLOGY_URL",
    "GAO_TOPICS_2026_08_15",
    "GAO_TOPICS_EXPECTED_COUNT",
    "GAO_TOPICS_LISTED_COUNT",
    "GAO_TOPICS_LISTING_TITLE",
    "GAO_TOPICS_URL",
    "GaoPagePin",
    "GaoPublishedTopic",
    "GaoPublishedTopicPage",
    "GaoPublishedTopicsError",
    "GaoPublishedTopicsIndex",
    "GaoSourceDriftError",
    "parse_gao_published_topics",
    "parse_gao_topic_page",
    "sha256_digest",
]

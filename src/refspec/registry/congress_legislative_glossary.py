"""Read the pinned Congress.gov legislative glossary without minting concepts.

The reviewed page has alphabetic ``dl`` lists of alternating ``dt`` and ``dd``
elements. Its real fragment anchors locate entries on that page; they establish
neither stable concept identity nor an edition series. The title names
Congress.gov and the Library of Congress, but does not identify a glossary
author. CRS subject terms and policy areas remain separate resources.

This offline reader uses the standard HTML tokenizer and ElementTree. Original
definition HTML remains an exact source slice; readable text only collapses
layout whitespace and retains paragraph boundaries. No network or raw store is
created here. Supply the original from the maintained acquisition workflow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree.ElementTree import Element, TreeBuilder

from refspec.registry.infrastructure.pinned_acquisition import (
    PinnedAcquisitionError,
    expected_digest_hex,
    verify_pinned_payload,
)
from refspec.registry.infrastructure.source_identity import require_aware_datetime_text

GLOSSARY_URL = "https://www.congress.gov/help/legislative-glossary"
GLOSSARY_TITLE = "Glossary of Legislative Terms"
PAGE_TITLE = f"{GLOSSARY_TITLE} | Congress.gov | Library of Congress"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
PARSER_VERSION = "congress-legislative-glossary/v1"


class LegislativeGlossaryError(ValueError):
    """Source bytes or the reviewed glossary structure changed."""


@dataclass(frozen=True, slots=True)
class GlossaryPin:
    """Exact observed source identity and reviewed structural expectations."""

    expected_sha256: str
    expected_byte_length: int
    retrieved_at: str
    expected_records: int
    expected_sections: tuple[str, ...]
    source_url: str = GLOSSARY_URL
    filename: str = "congress-legislative-glossary.html"

    def __post_init__(self) -> None:
        expected_digest_hex(self.expected_sha256)
        require_aware_datetime_text(self.retrieved_at, label="retrieved_at")
        if not 0 < self.expected_byte_length <= MAX_SOURCE_BYTES or self.expected_records <= 0:
            raise LegislativeGlossaryError("glossary pin exceeds the byte bound or has no records")
        if self.source_url != GLOSSARY_URL or not self.expected_sections:
            raise LegislativeGlossaryError("glossary pin requires the official URL and reviewed sections")


GLOSSARY_2026_11_14 = GlossaryPin(
    expected_sha256="sha256:501fab7f243c13cd402a5fa7c30a5e8e53f9f524b019cdf47c40774fa32d631e",
    expected_byte_length=418_089,
    retrieved_at="2026-11-14T18:34:36.547332Z",
    expected_records=117,
    expected_sections=tuple("abcdefghijlmnopqrstuv"),
)


@dataclass(frozen=True, slots=True)
class GlossaryLink:
    """An authored link, with its literal href; no inferred relationship."""

    href: str
    text: str


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """A page-local term and its complete definition, in publisher order."""

    ordinal: int
    section: str
    anchor: str
    term: str
    term_html: str
    definition_text: str
    definition_html: str
    links: tuple[GlossaryLink, ...]

    @property
    def source_locator(self) -> str:
        return "#" + self.anchor

    @property
    def source_url(self) -> str:
        return GLOSSARY_URL + self.source_locator


@dataclass(frozen=True, slots=True)
class LegislativeGlossary:
    """A reference view of one capture, with absent attribution kept explicit."""

    pin: GlossaryPin
    page_title: str
    introduction: str
    entries: tuple[GlossaryEntry, ...]
    publisher: str = "Library of Congress"
    author: str | None = None
    publisher_edition: str | None = None

    @property
    def unresolved_fragment_links(self) -> tuple[str, ...]:
        """Keep broken source links visible rather than correcting their targets."""
        anchors = {entry.source_locator for entry in self.entries} | {
            "#" + section for section in self.pin.expected_sections
        }
        return tuple(sorted({
            link.href for entry in self.entries for link in entry.links
            if link.href.startswith("#") and link.href not in anchors
        }))


class _Page(HTMLParser):
    """Tokenize only the reviewed content into a stock ElementTree, retaining spans."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.lines = [0]
        for line in source.splitlines(keepends=True):
            self.lines.append(self.lines[-1] + len(line))
        self.builder = TreeBuilder()
        self.stack: list[Element] = []
        self.spans: dict[Element, tuple[int, int]] = {}
        self.content: Element | None = None
        self.title: list[str] = []
        self.in_title = False
        self.canonicals: list[str | None] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            raise LegislativeGlossaryError("duplicate HTML attributes")
        if tag == "title":
            self.in_title = True
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonicals.append(attributes.get("href"))
        if attributes.get("id") == "help-content":
            if self.content is not None or self.stack or tag != "div":
                raise LegislativeGlossaryError("duplicate or changed glossary content region")
        elif not self.stack:
            return
        if len(self.stack) >= 16 or tag not in {"div", "h1", "p", "ul", "li", "a", "h2", "dl", "dt", "dd", "em", "i"}:
            raise LegislativeGlossaryError("unreviewed glossary HTML element or nesting depth")
        element = self.builder.start(tag, {key: value or "" for key, value in attrs})
        self.stack.append(element)
        self.spans[element] = (self._offset() + len(self.get_starttag_text()), -1)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if not self.stack:
            return
        if self.stack[-1].tag != tag:
            raise LegislativeGlossaryError("unbalanced glossary HTML")
        element = self.stack.pop()
        self.builder.end(tag)
        self.spans[element] = (self.spans[element][0], self._offset())
        if not self.stack:
            self.content = self.builder.close()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.stack:
            raise LegislativeGlossaryError("unreviewed self-closing glossary element")
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        if self.stack:
            self.builder.data(data)

    def inner_html(self, node: Element) -> str:
        start, end = self.spans[node]
        return self.source[start:end]


def _text(element: Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _definition_text(element: Element) -> str:
    parts = [element.text or ""]
    for child in element:
        parts.extend(["\n\n" if child.tag == "p" else "", "".join(child.itertext()), child.tail or ""])
    return "\n\n".join(" ".join(part.split()) for part in "".join(parts).split("\n\n")).strip()


def parse_legislative_glossary(
    payload: bytes, *, pin: GlossaryPin = GLOSSARY_2026_11_14,
) -> LegislativeGlossary:
    """Check the pin and parse the entire reviewed region in O(source bytes)."""
    if len(payload) > MAX_SOURCE_BYTES:
        raise LegislativeGlossaryError("glossary exceeds the source byte bound")
    try:
        verify_pinned_payload(payload, pin, location="Congress.gov glossary")
        source = payload.decode("utf-8", errors="strict")
    except (PinnedAcquisitionError, UnicodeDecodeError) as error:
        raise LegislativeGlossaryError(str(error)) from error
    page = _Page(source)
    page.feed(source)
    page.close()
    root = page.content
    if root is None or page.stack or "".join(page.title) != PAGE_TITLE or page.canonicals != [GLOSSARY_URL]:
        raise LegislativeGlossaryError("glossary title, canonical URL or complete content region changed")
    children = list(root)
    expected_tags = ["h1", "p", "ul", *[tag for _ in pin.expected_sections for tag in ("h2", "dl")]]
    if [node.tag for node in children] != expected_tags or _text(children[0]) != GLOSSARY_TITLE:
        raise LegislativeGlossaryError("glossary heading or alphabetic section structure changed")
    if (root.text or "").strip() or any((node.tail or "").strip() for node in children):
        raise LegislativeGlossaryError("unhandled text in glossary content region")
    if not _text(children[1]).startswith("Brief explanations of legislative terms used throughout Congress.gov."):
        raise LegislativeGlossaryError("glossary introduction changed")
    ids = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
    if len(ids) != len(set(ids)):
        raise LegislativeGlossaryError("duplicate glossary anchors")
    entries: list[GlossaryEntry] = []
    for index, section in enumerate(pin.expected_sections):
        heading, terms = children[3 + 2 * index:5 + 2 * index]
        if heading.attrib != {"id": section} or _text(heading) != section.upper():
            raise LegislativeGlossaryError("glossary alphabetical heading changed")
        if terms.attrib != {"class": "cdg-dl-alpha"} or not len(terms) or len(terms) % 2:
            raise LegislativeGlossaryError("glossary definition list structure changed")
        if (terms.text or "").strip() or any((node.tail or "").strip() for node in terms):
            raise LegislativeGlossaryError("unhandled text in glossary definition list")
        for term, definition in zip(terms[::2], terms[1::2], strict=True):
            anchor = term.get("id", "")
            if term.tag != "dt" or term.attrib != {"id": anchor} or not re.fullmatch(r"glossary_[a-z0-9_]+", anchor):
                raise LegislativeGlossaryError("glossary term or fragment anchor changed")
            if any(node.tag != "em" or node.attrib for node in term.iter() if node is not term):
                raise LegislativeGlossaryError("unreviewed glossary term markup")
            if definition.tag != "dd" or definition.attrib or not _text(term) or not _text(definition):
                raise LegislativeGlossaryError("glossary term is missing its definition")
            for node in definition.iter():
                if node is definition:
                    continue
                if node.tag not in {"p", "a", "em", "i"} or (
                    node.tag == "a" and (not node.get("href") or set(node.attrib) - {"href", "target", "rel"})
                ) or (node.tag != "a" and node.attrib):
                    raise LegislativeGlossaryError("unreviewed glossary definition markup")
            entries.append(GlossaryEntry(
                ordinal=len(entries) + 1, section=section, anchor=anchor, term=_text(term), term_html=page.inner_html(term),
                definition_text=_definition_text(definition), definition_html=page.inner_html(definition),
                links=tuple(GlossaryLink(node.attrib["href"], _text(node)) for node in definition.iter("a")),
            ))
    if len(entries) != pin.expected_records:
        raise LegislativeGlossaryError(f"glossary record count changed: expected {pin.expected_records}, got {len(entries)}")
    return LegislativeGlossary(pin, PAGE_TITLE, _text(children[1]), tuple(entries))


def read_legislative_glossary(
    path: Path, *, pin: GlossaryPin = GLOSSARY_2026_11_14,
) -> LegislativeGlossary:
    """Read at most the source byte bound plus one refusal byte from a local original."""
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_SOURCE_BYTES + 1)
    return parse_legislative_glossary(payload, pin=pin)

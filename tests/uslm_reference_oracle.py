"""Copied pre-extraction native checks; test-only independent oracle."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"

EDGE_TYPES: dict[str, str] = {
    "/us/pl": "enactingPublicLaw",
    "/us/stat": "statutesAtLarge",
    "/us/usc": "uscCrossReference",
    "/us/act": "actName",
}

USC_LEVELS: tuple[tuple[str, str], ...] = (
    ("sch", "subchapter"),
    ("spt", "subpart"),
    ("st", "subtitle"),
    ("ch", "chapter"),
    ("pt", "part"),
    ("d", "division"),
    ("s", "section"),
)

AMENDMENT_TOPICS = frozenset({"amendments", "effectiveDateOfAmendment", "prospectiveAmendment", "shortTitleOfAmendment"})

SECTION_TAG = "section"

SOURCE_CREDIT_TAG = "sourceCredit"

NOTE_TAG = "note"

UNIT_TAGS: tuple[str, ...] = ("section", "reorganizationPlan", "courtRule", "article", "compiledAct")

TOC_TAGS = frozenset({"toc", "tocItem"})

ANCHOR_TAGS = frozenset(
    {
        "title", "subtitle", "chapter", "subchapter", "part", "subpart", "division",
        "section", "subsection", "paragraph", "subparagraph", "clause", "subclause",
        "item", "subitem",
    }
)

class ExtractionError(RuntimeError):
    """The corpus contained something this tool has no defined meaning for."""

def _localname(tag: str) -> str:
    """Strip the USLM namespace; every element in these documents carries it."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def classify_href(href: str) -> tuple[str, str | None]:
    """Map an href to its edge type and, for USC targets, the level it points at.

    Fails closed.  A prefix outside :data:`EDGE_TYPES` means the corpus cites a
    citator this tool does not model, and emitting it under a guessed type would
    put a row of unknown meaning into the graph.
    """
    if not href.startswith("/"):
        raise ExtractionError(f"href is not an absolute identifier: {href!r}")
    prefix = "/".join(href.split("/")[:3])
    edge_type = EDGE_TYPES.get(prefix)
    if edge_type is None:
        raise ExtractionError(f"unrecognised href prefix {prefix!r} in {href!r}")
    if edge_type != "uscCrossReference":
        return edge_type, None

    parts = href.split("/")
    if len(parts) < 5:
        # /us/usc/tNN -- a reference to a whole title.
        return edge_type, "title"
    segment = parts[4]
    for marker, level in USC_LEVELS:
        if segment.startswith(marker):
            return edge_type, level
    raise ExtractionError(f"unrecognised USC level in {href!r} (segment {segment!r})")

@dataclass(frozen=True)
class Anchor:
    """One element on the ancestor stack that an edge can be attributed to."""

    tag: str
    identifier: str | None
    note_topic: str | None
    status: str | None

def _context(
    stack: Sequence[Anchor],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str, str | None]:
    """Locate an edge: its section, its finest anchor, and what kind of text it sits in.

    The context label is the part that keeps amendment credits separable from
    genuine cross-references.  ``sourceCredit`` and the amendment note topics are
    the section's history; ``operative`` is the enacted text itself.  Precedence
    runs innermost-first, because a ``<sourceCredit>`` nested in a note is still a
    source credit.
    """
    section: str | None = None
    anchor: str | None = None
    unit: str | None = None
    unit_kind: str | None = None
    unit_status: str | None = None
    context = "operative"
    topic: str | None = None
    for entry in reversed(stack):
        if entry.tag == SOURCE_CREDIT_TAG and context == "operative":
            context = "sourceCredit"
        elif entry.tag in TOC_TAGS and context == "operative":
            context = "toc"
        elif entry.tag == NOTE_TAG and context == "operative":
            context = "note"
            topic = entry.note_topic
        if anchor is None and entry.identifier and entry.tag in ANCHOR_TAGS:
            anchor = entry.identifier
        # The enclosing unit is recorded whether or not it carries an identifier.
        # A repealed or transferred section keeps its ``id`` but loses its
        # ``identifier`` -- the publisher mints identifiers only for units that
        # still exist -- and the repeal notice in its heading still cites the
        # Public Law that repealed it.  Those citations are real and are kept,
        # with ``sourceUnit`` null and ``sourceUnitStatus`` saying why.
        if unit_kind is None and entry.tag in UNIT_TAGS:
            unit, unit_kind, unit_status = entry.identifier, entry.tag, entry.status
        if section is None and entry.tag == SECTION_TAG and entry.identifier:
            section = entry.identifier
    return section, anchor, unit, unit_kind, unit_status, context, topic

def iter_edges(xml: bytes, title: str, skipped: Counter[str]) -> Iterator[dict[str, Any]]:
    """Walk the document once, yielding one row per href-bearing element.

    ``iterparse`` with an explicit ancestor stack rather than a DOM walk: the
    larger titles run to tens of megabytes and every edge needs to know which
    section encloses it, which is ancestor state a streaming parse already has.

    Anything deliberately not emitted is tallied into ``skipped`` rather than
    dropped, so the manifest can account for every href in the document.
    """
    stack: list[Anchor] = []
    for event, element in ET.iterparse(_BytesReader(xml), events=("start", "end")):
        tag = _localname(element.tag)
        if event == "start":
            stack.append(
                Anchor(
                    tag=tag,
                    identifier=element.get("identifier"),
                    note_topic=element.get("topic"),
                    status=element.get("status"),
                )
            )
            href = element.get("href")
            if tag == "ref":
                skipped["refElementsSeen"] += 1
                if href is None:
                    # class="footnoteRef" with an idref: an internal footnote
                    # pointer, well-formed and simply not a citation.
                    skipped["refWithoutHref"] += 1
            if href is not None:
                # An in-document anchor (``#TAB_231_0``) points at a table in this
                # same file.  It is navigation, not a citation of another law, and
                # it is the one href shape that is not an identifier.
                if href.startswith("#"):
                    skipped["inDocumentFragment"] += 1
                    if tag == "ref":
                        skipped["inDocumentFragmentOnRef"] += 1
                    continue
                edge_type, usc_level = classify_href(href)
                section, anchor, unit, unit_kind, unit_status, context, topic = _context(stack)
                yield {
                    "title": title,
                    "sourceSection": section,
                    "sourceUnit": unit,
                    "sourceUnitKind": unit_kind,
                    "sourceUnitStatus": unit_status,
                    "sourceAnchor": anchor,
                    "href": href,
                    "edgeType": edge_type,
                    "uscTargetLevel": usc_level,
                    "element": tag,
                    "context": context,
                    "noteTopic": topic,
                    "historical": context == "sourceCredit" or topic in AMENDMENT_TOPICS,
                }
        else:
            if not stack:
                raise ExtractionError(f"title {title}: unbalanced element stack at </{tag}>")
            stack.pop()
            element.clear()

class _BytesReader:
    """Minimal file-like wrapper so ``iterparse`` can stream an in-memory payload."""

    def __init__(self, payload: bytes) -> None:
        self._payload = memoryview(payload)
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return bytes(chunk)

def section_identifiers(xml: bytes) -> set[str]:
    """Every ``<section identifier>`` in the document, for resolving USC targets."""
    found: set[str] = set()
    for event, element in ET.iterparse(_BytesReader(xml), events=("end",)):
        del event
        if _localname(element.tag) == SECTION_TAG:
            identifier = element.get("identifier")
            if identifier:
                found.add(identifier)
        element.clear()
    return found

def _target_section(href: str) -> str | None:
    """The section-granularity prefix of a USC href, or None if it targets no section."""
    parts = href.split("/")
    if len(parts) < 5:
        return None
    segment = parts[4]
    if not segment.startswith("s") or segment.startswith(("sch", "spt", "st")):
        return None
    return "/".join(parts[:5])

"""Read publisher USLM reference occurrences without inferring legal relationships.

Shared with the corpus build tool. Preserve original identifiers, enclosing
source context, skipped occurrences and refusal behavior. Optional source paths
locate markup elements, not positions in decoded text or the original XML bytes.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from spicy_docs.sources.uscode import USLM_NAMESPACE
from spicy_docs.sources.uscode_references import UsCodeReference, scan_uscode_references
from spicy_docs.sources.xml_observations import XmlElement

USLM_NS = USLM_NAMESPACE

#: The four citators the corpus uses, mapped to a descriptive label for each.
#:
#: These names describe *which citator the publisher used*.  They are deliberately
#: not legal predicates and not Atlas predicates: see the module docstring and the
#: evidence README for why establishing the predicate is a separate, unresolved
#: question that this tool must not pre-empt.  Membership here is the fail-closed
#: gate: an href outside these prefixes aborts the build rather than being emitted
#: with a guessed type.
EDGE_TYPES: dict[str, str] = {
    "/us/pl": "enactingPublicLaw",
    "/us/stat": "statutesAtLarge",
    "/us/usc": "uscCrossReference",
    "/us/act": "actName",
}

#: What a ``/us/usc`` href actually points at.  USLM spells the level in the path
#: segment, and ``st`` (subtitle) shares a prefix with ``s`` (section), so the
#: longer keys must be tested first or every subtitle is misread as a section.
USC_LEVELS: tuple[tuple[str, str], ...] = (
    ("sch", "subchapter"),
    ("spt", "subpart"),
    ("st", "subtitle"),
    ("ch", "chapter"),
    ("pt", "part"),
    ("d", "division"),
    ("s", "section"),
)

#: Note topics whose references are historical apparatus rather than operative
#: text.  Used only to *label* an edge's context; nothing is filtered on it.
AMENDMENT_TOPICS = frozenset({"amendments", "effectiveDateOfAmendment", "prospectiveAmendment", "shortTitleOfAmendment"})

SECTION_TAG = "section"
SOURCE_CREDIT_TAG = "sourceCredit"
NOTE_TAG = "note"

#: The unit that *makes* a citation.  In the fifty-odd ordinary titles this is
#: always ``<section>``, which is why it is tempting to hardcode -- but the five
#: appendix titles are not built from sections at all.  Title 5 Appendix is 107
#: ``<reorganizationPlan>`` elements; Titles 11 and 28 Appendix are the Federal
#: Rules, built from ``<courtRule>``.  An invariant written against ``<section>``
#: alone reports 1,420 "orphaned" edges in Title 5 Appendix that are perfectly
#: well anchored, just not to a section.  ``sourceSection`` is still emitted
#: separately, so a consumer that only wants sections can still filter on it
#: without having to know which titles are exceptions.
UNIT_TAGS: tuple[str, ...] = ("section", "reorganizationPlan", "courtRule", "article", "compiledAct")

#: Table-of-contents scaffolding.  A ``<ref>`` inside a ``<toc>`` is a navigation
#: link to a subdivision the document already contains, not a citation made by the
#: law.  It must be its own context: folded into ``operative`` it produced 2,992
#: bogus "section-to-section references" in Title 26 that are really TOC entries
#: pointing at subtitles, with no citing section at all.
TOC_TAGS = frozenset({"toc", "tocItem"})

#: Levels that can carry an ``identifier`` and so can serve as an edge's anchor.
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

def _context(
    stack: Sequence[XmlElement],
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
        tag = _localname(entry.tag)
        identifier = entry.attributes.get("identifier")
        if tag == SOURCE_CREDIT_TAG and context == "operative":
            context = "sourceCredit"
        elif tag in TOC_TAGS and context == "operative":
            context = "toc"
        elif tag == NOTE_TAG and context == "operative":
            context = "note"
            topic = entry.attributes.get("topic")
        if anchor is None and identifier and tag in ANCHOR_TAGS:
            anchor = identifier
        # The enclosing unit is recorded whether or not it carries an identifier.
        # A repealed or transferred section keeps its ``id`` but loses its
        # ``identifier`` -- the publisher mints identifiers only for units that
        # still exist -- and the repeal notice in its heading still cites the
        # Public Law that repealed it.  Those citations are real and are kept,
        # with ``sourceUnit`` null and ``sourceUnitStatus`` saying why.
        if unit_kind is None and tag in UNIT_TAGS:
            unit, unit_kind, unit_status = identifier, tag, entry.attributes.get("status")
        if section is None and tag == SECTION_TAG and identifier:
            section = identifier
    return section, anchor, unit, unit_kind, unit_status, context, topic

def read_edges(
    xml: bytes,
    title: str,
    skipped: Counter[str],
    emit: Callable[[dict[str, Any]], object],
    *,
    include_source_path: bool = False,
) -> None:
    """Apply RefSpec's citation policy to source observations from SpicyDocs.

    Emitted rows are provisional until the reader returns successfully. The
    caller owns collection/publication; no second title-sized observation list
    is materialized between source reading and policy application.
    """
    def reference(observation: UsCodeReference) -> None:
        tag = _localname(observation.element.tag)
        href = observation.href
        if tag == "ref":
            skipped["refElementsSeen"] += 1
            if href is None:
                skipped["refWithoutHref"] += 1
        if href is None:
            return
        if href.startswith("#"):
            skipped["inDocumentFragment"] += 1
            if tag == "ref":
                skipped["inDocumentFragmentOnRef"] += 1
            return
        edge_type, usc_level = classify_href(href)
        section, anchor, unit, unit_kind, unit_status, context, topic = _context(
            (*observation.ancestors, observation.element)
        )
        row = {
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
        if include_source_path:
            row["sourceXPath"] = observation.element.source_xpath
        emit(row)

    scan_uscode_references(xml, on_reference=reference)


def _target_section(href: str) -> str | None:
    """The section-granularity prefix of a USC href, or None if it targets no section."""
    parts = href.split("/")
    if len(parts) < 5:
        return None
    segment = parts[4]
    if not segment.startswith("s") or segment.startswith(("sch", "spt", "st")):
        return None
    return "/".join(parts[:5])


def read_text(xml: bytes) -> dict[str, Any]:
    """Prepare readable USLM text, preserving decoded source and XPath positions."""
    from .xml_text import read_text as read_xml_text
    return read_xml_text(xml, profile='uslm')

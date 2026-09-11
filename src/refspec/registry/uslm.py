"""Read publisher USLM reference occurrences without inferring legal relationships.

Shared with the corpus build tool. Preserve original identifiers, enclosing
source context, skipped occurrences and refusal behavior. Optional source paths
locate markup elements, not positions in decoded text or the original XML bytes.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Any
import xml.etree.ElementTree as ET

USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"

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

def iter_edges(xml: bytes, title: str, skipped: Counter[str], *, include_source_path: bool = False) -> Iterator[dict[str, Any]]:
    """Walk the document once, yielding one row per href-bearing element.

    ``iterparse`` with an explicit ancestor stack rather than a DOM walk: the
    larger titles run to tens of megabytes and every edge needs to know which
    section encloses it, which is ancestor state a streaming parse already has.

    Anything deliberately not emitted is tallied into ``skipped`` rather than
    dropped, so the manifest can account for every href in the document.
    ``include_source_path`` adds a namespace-independent ``sourceXPath`` selecting
    the exact element in these bytes. Repeated equal references have distinct
    paths. The default row shape and traversal order are unchanged.
    """
    stack: list[Anchor] = []
    positions: list[int] = []
    sibling_counts = [0]
    for event, element in ET.iterparse(BytesIO(xml), events=("start", "end")):
        tag = _localname(element.tag)
        if event == "start":
            if include_source_path:
                sibling_counts[-1] += 1
                positions.append(sibling_counts[-1])
                sibling_counts.append(0)
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
                    row["sourceXPath"] = "".join(f"/*[{p}]" for p in positions)
                yield row
        else:
            if not stack:
                raise ExtractionError(f"title {title}: unbalanced element stack at </{tag}>")
            stack.pop()
            if include_source_path:
                positions.pop()
                sibling_counts.pop()
            element.clear()

def section_identifiers(xml: bytes) -> set[str]:
    """Every ``<section identifier>`` in the document, for resolving USC targets."""
    found: set[str] = set()
    for event, element in ET.iterparse(BytesIO(xml), events=("end",)):
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


_TEXT_BLOCKS = frozenset('main appendix title subtitle chapter subchapter part subpart '
    'division subdivision level compiledAct courtRules courtRule reorganizationPlans '
    'reorganizationPlan section subsection paragraph subparagraph clause subclause '
    'item subitem subsubitem continuation notes sourceCredit note p ul ol li longTitle '
    'enactingFormula table thead tbody tfoot tr'.split())
_TEXT_CELLS = frozenset({'td', 'th'})
_SEPARATOR_RANK = {'': 0, ' ': 1, '\t': 2, '\n\n': 3}


def read_text(xml: bytes) -> dict[str, Any]:
    """Prepare readable USLM text with original decoded-text and XPath positions.

    Source-map entries distinguish unchanged decoded XML text from inserted layout
    whitespace. Node offsets address both text representations; empty nodes have
    only source positions. These are Unicode codepoints, not original XML bytes.
    The captured publisher stylesheet supplies the block/table profile; explicit
    heading separation prevents joined words when headings use inline display.
    This preserves reading order and cell boundaries, not full visual table layout.
    """
    root = ET.fromstring(xml)
    if root.tag != f'{{{USLM_NS}}}uscDoc':
        raise ValueError('Expected a captured USLM uscDoc')
    raw_parts, output, parts, nodes = [], [], [], {}
    raw_cursor = cursor = 0
    pending = ''
    trailing_newlines, trailing_tab = 0, False

    def append(value):
        nonlocal raw_cursor, cursor, pending, trailing_newlines, trailing_tab
        if not value:
            return
        if pending and value.strip():
            # Existing source whitespace remains source text. Supply only the
            # missing separator before the next visible source character.
            leading = value[:len(value) - len(value.lstrip())]
            if pending == '\n\n':
                needed = max(0, 2 - trailing_newlines - leading.count('\n'))
            elif pending == '\t':
                needed = 0 if trailing_tab or '\t' in leading else 1
            else:
                whitespace_before = output and output[-1][-1:].isspace()
                needed = 0 if whitespace_before or leading else 1
            separator = ('\n' if pending == '\n\n' else pending) * needed
            if cursor and separator:
                output.append(separator)
                parts.append({'kind': 'inserted', 'start': cursor,
                              'end': cursor + len(separator), 'text': separator})
                cursor += len(separator)
            pending = ''
        output.append(value)
        part = {'kind': 'source', 'start': cursor, 'end': cursor + len(value),
                'source_start': raw_cursor, 'source_end': raw_cursor + len(value)}
        if parts and parts[-1]['kind'] == 'source':
            parts[-1].update(end=part['end'], source_end=part['source_end'])
        else:
            parts.append(part)
        cursor += len(value)
        raw_cursor += len(value)
        raw_parts.append(value)
        if not value.isspace():
            trailing_newlines, trailing_tab = 0, False
        trailing = value[len(value.rstrip()):]
        trailing_newlines += trailing.count('\n')
        trailing_tab |= '\t' in trailing

    def boundary(separator):
        nonlocal pending
        if _SEPARATOR_RANK[separator] > _SEPARATOR_RANK[pending]:
            pending = separator

    def visit(node, path, parent='', inside_cell=False):
        nonlocal pending
        tag = node.tag.rsplit('}', 1)[-1]
        cell = tag in _TEXT_CELLS
        block = tag in _TEXT_BLOCKS and not (inside_cell and tag == 'p')
        block |= tag == 'content' and parent in {'section', 'reorganizationPlan'}
        block |= tag == 'heading' and parent in {'note', 'appendix'}
        block |= tag == 'chapeau' and any(c.startswith('blockIndent') for c in node.get('class', '').split())
        if block or tag == 'br':
            boundary('\n\n')
        if cell:
            boundary('\t')
        start = raw_cursor
        append(node.text)
        for index, child in enumerate(node, 1):
            visit(child, path + f'/*[{index}]', tag, inside_cell or cell)
            append(child.tail)
        nodes[path] = {'source_start': start, 'source_end': raw_cursor,
                       'tag': tag, **({'identifier': node.get('identifier')} if node.get('identifier') else {})}
        if block or tag == 'heading' and parent == 'section' or inside_cell and tag == 'p':
            boundary('\n\n')
        if tag == 'heading':
            boundary(' ')
        if cell:
            pending = '\t'

    visit(root, '/*[1]')
    source_text, text = ''.join(raw_parts), ''.join(output)
    assert source_text == ''.join(root.itertext())
    sources = [part for part in parts if part['kind'] == 'source']
    starts, ends = [part['source_start'] for part in sources], [part['source_end'] for part in sources]
    for node in nodes.values():
        lo, hi = node['source_start'], node['source_end']
        if lo < hi:
            first, last = sources[bisect_right(ends, lo)], sources[bisect_left(starts, hi) - 1]
            node.update(start=first['start'] + lo - first['source_start'],
                        end=last['start'] + hi - last['source_start'])
    return {'text': text, 'source_text': source_text, 'source_map': parts, 'nodes': nodes,
            'method': 'uslm-block-boundaries/1'}

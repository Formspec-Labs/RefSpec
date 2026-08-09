"""Extract statutory identifier edges from the OLRC's USLM XML edition of the US Code.

The Office of the Law Revision Counsel publishes the US Code as United States
Legislative Markup, an XML vocabulary in which every citation the editors
recognised is already resolved to a machine identifier: ``<ref href="/us/pl/99/514/s2">``
rather than the prose string "Pub. L. 99-514, Sec. 2".  That is the whole reason
this corpus is worth reading.  Nothing here recognises citations -- the publisher
already did that, in the course of producing an official edict of the US
government, and every edge below is a transcription of an editorial decision
rather than an inference of ours.  A tool that ran a citation *recogniser* over
the same text would be replacing a curated answer with a guess.

That distinction is what makes these edges *asserted* rather than *derived* under
[REF-014](../docs/decisions.md) and the Atlas 3.0 binding: an
``atlas:NativeRelationAssertion`` "preserves a publisher-authored relation
between resources in the same semantic ring", and its endpoints "may belong to
one release or to different releases".  A marked-up ``<ref href>`` is exactly
that.  See ``research/evidence/uslm-reference-edges-2026-08-07/README.md`` for
what this does and does not license.

**Why the edges decompose, and why a single total is a lie.**  The href prefix is
not a formatting detail; it names four populations that answer different
questions, and the programme has already been burned by pooling them.  An
archived project advertises "~109,000 cross-references for Title 26", a figure
that can only be reached by adding amendment credits to genuine cross-references.
They are not the same relation and they do not belong in the same edge set:

* ``/us/pl/…``   -- the section's **amendment history**.  Overwhelmingly these sit
  inside ``<sourceCredit>`` and ``<note topic="amendments">``: they say "Public
  Law 99-514 amended this section", not "this section refers to Public Law
  99-514".  As a graph edge the direction of interest is provenance, not
  reference.  They are ~61% of Title 26's hrefs and they dominate any pooled
  count, which is exactly how a pooled count misleads.
* ``/us/stat/…`` -- the Statutes at Large page the amendment was printed on.  A
  citation *of the same event* as the ``/us/pl`` edge beside it, in a different
  citator.  Counting both as independent references double-counts the amendment.
* ``/us/usc/…`` -- the **section-to-section cross-reference**, and the population
  everyone actually wants.  Where it sits matters more than how many there are:
  corpus-wide the 330,508 split as 175,739 in editorial notes, 64,021 in
  table-of-contents scaffolding, and 90,692 in operative enacted text.  Target
  level is not homogeneous either -- 1,895 address a *subtitle*, 1,548 a chapter --
  so ``uscTargetLevel`` is emitted rather than assumed.

  **Markup density is a per-title property, and Title 26 is its worst case.**
  This is the single most important thing to know before generalising from one
  title.  Across most titles OLRC marks up same-title references heavily: 65-88%
  of operative USC references stay inside their own title, and in Title 42
  marked-up refs outnumber unmarked "section NNN" prose 26,417 to 5,366 (83%
  markup).  Title 26 inverts it -- 1,574 marked against 16,421 unmarked, an 8.7%
  markup share, and of its 539 operative USC references just *six* point at
  Title 26 itself.  So "the enacted text's internal reference network is missing"
  is true of Title 26 and false of the corpus.  A consumer validating on Title 26
  alone would conclude the corpus is unusable for intra-title graphs; one
  validating on Title 42 alone would conclude it is complete.  Both would be
  wrong, which is why per-title context counts are in the manifest rather than a
  single corpus-level rate.
* ``/us/act/…``  -- reference to a named act (``/us/act/1954-08-16/ch736``), used
  where the drafters cited the act rather than its codified location.

**An emitted row is an occurrence, not an edge.**  This is the second way a
pooled total misleads, and it is subtler than the first.  The walk yields one row
per href-bearing element, which is the right unit for *evidence*: it is a
faithful record of where the publisher put each mark-up, and discarding
repetition at extraction time would destroy the ability to audit the transcript
against the source.  But a graph edge is a claim, and the same claim marked up
four times in one section is one claim.  Over the full corpus the two units
differ by more than an order of magnitude in the only place it matters --
1,342,167 occurrence rows contain 87,586 distinct operative section-to-section
references -- so the tool computes both and refuses to let either stand in for
the other.  :data:`ASSERTION_KEY` is the deduplication policy, stated once,
applied here, and reported in the manifest.  See :func:`dedupe`.

**What this tool refuses to do.**  It does not normalise identifiers, resolve
dangling targets, collapse the four types into one, or repair the publisher's
markup.  Two refusals are load-bearing:

*Identifiers are copied byte-for-byte.*  Section numbers in this corpus contain
U+2013 EN DASH, not ASCII hyphen -- ``/us/usc/t26/s1400Z–1`` -- and the ``href``
joins to the corresponding ``<section identifier>`` only if that codepoint
survives.  "Tidying" the dash to ASCII silently severs the join, and a consumer
who did it would see a plausible-looking identifier that matches nothing.

*Dangling targets are kept and flagged, never dropped.*  About 1% of same-title
section references point at sections that no longer exist in this edition,
because the corpus retains the historical citation after a repeal.  Dropping them
would misrepresent the law's own text; silently keeping them would misrepresent
the graph.  They are emitted with ``targetResolved: false``.

**Where an edge sits is part of what it means**, so ``context`` is a first-class
field rather than a filter applied here.  ``sourceCredit`` and the amendment note
topics are the section's history; ``note`` is editorial apparatus; ``toc`` is
navigation the publisher generated; only ``operative`` is enacted text.  The
distinction is not cosmetic -- an earlier revision of this tool folded ``toc``
into ``operative`` and thereby invented 2,992 Title 26 "section-to-section
references" that were really contents-table entries pointing at subtitles, with
no citing section at all.  That every ``operative`` edge has a non-null
``sourceUnit`` is checked on every run, and is what makes that class of error
loud instead of silent.  It is also what caught the appendix titles: the same
check written against ``<section>`` alone failed on Title 5 Appendix, which is
built from reorganization plans rather than sections (see :data:`UNIT_TAGS`).

**Element scope, and why it is not just ``<ref>``.**  Most hrefs sit on a ``<ref>``,
but 42,065 of them -- 3.1% of the corpus, spread over 33 titles -- ride on ``<a>``
instead.  Title 26 has only 8, which is exactly why this is worth stating: judged
on Title 26 alone the difference looks like a rounding error, and a ``<ref>``-only
extractor would appear correct while silently dropping 8,343 edges from Title 49,
4,833 from Title 10 and 4,517 from Title 54.  The pattern is not random.  ``<a>``
appears where the publisher renders a *tabular* note -- overwhelmingly
``topic="historicalAndRevision"``, the revision tables that the positive-law
restated titles carry and Title 26 does not.  Every href-bearing element is
therefore read and its tag recorded, so the choice is visible in the output rather
than baked into a filter.  Conversely ``<ref class="footnoteRef">`` carries no href
at all: it is an internal footnote pointer, not a citation, and is counted as
skipped rather than malformed.

Read-only against the publisher's bytes.  The downloaded zip is hashed and never
rewritten, and the build fails closed on any href whose prefix it does not
already have a meaning for -- an unrecognised citator is a signal that the corpus
grew a relation this tool does not model, which is a reason to stop rather than
to emit a row typed ``unknown``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"

RELEASE_POINT = "119/102"
BASE_URL = "https://uscode.house.gov/download/releasepoints/us/pl"

#: Every title the OLRC publishes as USLM at this release point, appendices included.
#: Title 53 is deliberately absent: it is *reserved* and has no text, and although
#: the download page still lists a link for it, the URL 302s to an error page.  The
#: server answers that redirect with HTTP 200 and an HTML body, so a fetcher that
#: trusts the status code will happily save a web page as ``xml_usc53.zip`` --
#: which is why :func:`fetch_title` checks the payload is a zip and not merely that
#: the request succeeded.
TITLES: tuple[str, ...] = (
    "01", "02", "03", "04", "05", "05a", "06", "07", "08", "09", "10", "11", "11a", "12", "13",
    "14", "15", "16", "17", "18", "18a", "19", "20", "21", "22", "23", "24", "25", "26", "27",
    "28", "28a", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41",
    "42", "43", "44", "45", "46", "47", "48", "49", "50", "50a", "51", "52", "54",
)

#: Reserved titles the publisher lists but does not publish.  Named rather than
#: merely omitted, so that asking for one gets an explanation instead of a 404.
RESERVED_TITLES: dict[str, str] = {"53": "Title 53 is reserved and has no USLM text at any release point"}

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

# --------------------------------------------------------------------------- #
# deduplication policy
# --------------------------------------------------------------------------- #

#: The fields that distinguish one *claim* from another.
#:
#: An emitted row is a markup occurrence; this key is what makes two occurrences
#: the same edge.  Three choices in it are decisions rather than conveniences,
#: and each was measured against the full corpus before being taken:
#:
#: ``context`` **is in the key.**  This is the one that matters.  Dropping it
#: yields 1,170,595 keys against 1,192,890 with it -- 22,295 triples that the
#: publisher marked up in *two different kinds of text* and that a context-free
#: key silently merges.  Those are precisely the pairs where the same citation
#: appears once in enacted text and once in an editorial note, which is the
#: distinction this entire tool is built to preserve.  A context-free dedup would
#: reintroduce, at the assertion layer, exactly the conflation the ``context``
#: field exists to prevent.  Filter on context first, then deduplicate within it;
#: never the other way round.
#:
#: ``sourceAnchor`` **is the subject, and a null one is not a claim.**  2,641 rows
#: (0.20%) carry no anchor: they sit in a repealed or transferred unit that kept
#: its ``id`` but lost its ``identifier``, so there is no endpoint to hang an edge
#: on.  They are retained in the JSONL as evidence and excluded from the assertion
#: population, counted rather than dropped.  Note that 1,422 of them are in
#: ``operative`` context -- so this is not a rounding error confined to notes.
#:
#: ``noteTopic``, ``element``, ``sourceUnit`` and ``targetResolved`` are **not** in
#: the key.  They are properties of the occurrence or of the target, not of the
#: claim: whether the publisher rendered a reference as ``<ref>`` or ``<a>`` does
#: not make it a different reference.  ``title`` is included although it is
#: recoverable from ``sourceAnchor``, because it makes the key self-describing and
#: keeps per-title accounting exact without a parse.
ASSERTION_KEY: tuple[str, ...] = ("title", "sourceAnchor", "edgeType", "href", "context")


class ExtractionError(RuntimeError):
    """The corpus contained something this tool has no defined meaning for."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _localname(tag: str) -> str:
    """Strip the USLM namespace; every element in these documents carries it."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def assertion_key(edge: dict[str, Any]) -> tuple[Any, ...] | None:
    """The claim this occurrence expresses, or ``None`` if it expresses none.

    ``None`` means the row has no usable subject endpoint -- see
    :data:`ASSERTION_KEY`.  It is a distinct outcome from "duplicate", and the
    accounting keeps them separate.
    """
    if edge["sourceAnchor"] is None:
        return None
    return tuple(edge[field] for field in ASSERTION_KEY)


def dedupe(edges: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse occurrence rows to distinct claims under :data:`ASSERTION_KEY`.

    Returns the first occurrence of each claim in document order, plus the
    accounting that makes the collapse auditable.  Document order rather than
    sorted order because the first mark-up of a citation in a section is the one
    a reader meets first; nothing downstream depends on which representative is
    kept, and picking one deterministically beats picking one arbitrarily.

    The counts are the point.  A caller that reports the length of this list
    without also reporting ``occurrenceRows`` has reproduced the pooled-total
    error at a different layer.
    """
    seen: set[tuple[Any, ...]] = set()
    kept: list[dict[str, Any]] = []
    anchorless = 0
    exact_duplicate_rows: Counter[str] = Counter()
    for edge in edges:
        exact_duplicate_rows[_canonical(edge)] += 1
        key = assertion_key(edge)
        if key is None:
            anchorless += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        kept.append(edge)
    redundant = len(edges) - anchorless - len(kept)
    accounting = {
        "policy": {
            "key": list(ASSERTION_KEY),
            "anchorlessRowsExcluded": (
                "a row with a null sourceAnchor has no subject endpoint and states no claim; "
                "it is retained in the JSONL as evidence and excluded here"
            ),
            "contextInKey": (
                "context is part of the key: omitting it merges citations the publisher placed in "
                "different kinds of text, which is the conflation the context field exists to prevent"
            ),
        },
        "occurrenceRows": len(edges),
        "anchorlessRows": anchorless,
        "distinctClaims": len(kept),
        "redundantOccurrences": redundant,
        "exactDuplicateRows": sum(count - 1 for count in exact_duplicate_rows.values() if count > 1),
        "distinctClaimsByContext": dict(sorted(Counter(edge["context"] for edge in kept).items())),
        "distinctClaimsByEdgeType": dict(sorted(Counter(edge["edgeType"] for edge in kept).items())),
        #: The population a legal-identity graph would actually draw on: a
        #: section-to-section reference made by enacted text, counted once.
        "operativeUscCrossReferences": sum(
            1 for edge in kept if edge["context"] == "operative" and edge["edgeType"] == "uscCrossReference"
        ),
    }
    return kept, accounting


@dataclass(frozen=True)
class SourceBytes:
    """The exact publisher payload an extraction ran against."""

    url: str
    zip_bytes: int
    zip_sha256: str
    member: str
    xml_bytes: int
    xml_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "zipBytes": self.zip_bytes,
            "zipSha256": self.zip_sha256,
            "member": self.member,
            "xmlBytes": self.xml_bytes,
            "xmlSha256": self.xml_sha256,
        }


def fetch_title(title: str, release_point: str, cache: Path) -> tuple[bytes, SourceBytes]:
    """Return the title's USLM XML and a pin describing the bytes it came from.

    The zip is cached verbatim.  Re-running against a cached file re-derives every
    digest from those bytes, so a corrupted or hand-edited cache cannot pass
    itself off as the publisher's payload.
    """
    url = f"{BASE_URL}/{release_point}/xml_usc{title}@{release_point.replace('/', '-')}.zip"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"xml_usc{title}.zip"
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "RefSpec-USLM-extractor/1.0"})
        # Fixed https host, built from the release point and a validated title code.
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.status != 200:
                raise ExtractionError(f"title {title}: {url} returned HTTP {response.status}")
            path.write_bytes(response.read())

    payload = path.read_bytes()
    # The publisher redirects unknown titles to an HTML error page that arrives
    # with a success status, so "the request worked" is not evidence the bytes are
    # the corpus.  Check the payload itself.
    if not payload.startswith(b"PK"):
        raise ExtractionError(
            f"title {title}: {url} did not return a zip archive "
            f"({len(payload)} bytes beginning {payload[:16]!r}) — the title may be reserved or withdrawn"
        )
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if len(members) != 1:
            raise ExtractionError(f"title {title}: expected exactly one XML member, found {members}")
        xml = archive.read(members[0])

    pin = SourceBytes(
        url=url,
        zip_bytes=len(payload),
        zip_sha256=_sha256(payload),
        member=members[0],
        xml_bytes=len(xml),
        xml_sha256=_sha256(xml),
    )
    return xml, pin


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


def extract_title(title: str, release_point: str, cache: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract one title's edges and the report describing that extraction."""
    started = time.monotonic()
    xml, pin = fetch_title(title, release_point, cache)
    sections = section_identifiers(xml)
    skipped: Counter[str] = Counter()
    edges = list(iter_edges(xml, title, skipped))

    # Every <ref> the parser saw is either emitted, skipped as a fragment, or
    # skipped as href-less.  Proving that closes the account: no <ref> can go
    # missing without the arithmetic noticing.
    emitted_refs = sum(1 for edge in edges if edge["element"] == "ref")
    fragment_refs = skipped["inDocumentFragmentOnRef"]
    unaccounted = skipped["refElementsSeen"] - emitted_refs - fragment_refs - skipped["refWithoutHref"]
    if unaccounted:
        raise ExtractionError(
            f"title {title}: {unaccounted} <ref> elements are neither emitted nor accounted for as skipped"
        )

    #: Resolution is only decidable inside the title being read; a reference into
    #: another title cannot be checked against a document we have not loaded, and
    #: is reported as unknown rather than guessed either way.
    own_title = f"/us/usc/t{title.lstrip('0') or '0'}"
    resolved = unresolved = external = 0
    for edge in edges:
        if edge["edgeType"] != "uscCrossReference":
            continue
        target = _target_section(edge["href"])
        if target is None:
            continue
        if not target.startswith(own_title + "/"):
            edge["targetResolved"] = None
            external += 1
            continue
        edge["targetResolved"] = target in sections
        resolved += edge["targetResolved"]
        unresolved += not edge["targetResolved"]

    # An operative edge is a citation made by enacted text, so enacted text must
    # enclose it.  If one does not, the context taxonomy has lost track of some
    # structure -- which is exactly how table-of-contents entries once passed for
    # section-to-section references -- and the run must stop rather than emit it.
    orphaned = [edge for edge in edges if edge["context"] == "operative" and not edge["sourceUnitKind"]]
    if orphaned:
        raise ExtractionError(
            f"title {title}: {len(orphaned)} operative edges sit in no {'/'.join(UNIT_TAGS)} at all, "
            f"e.g. {orphaned[0]['href']!r} anchored at {orphaned[0]['sourceAnchor']!r}"
        )

    # A unit with no identifier is expected only when the publisher withdrew it.
    # If one turns up with no status either, the document has a shape this tool
    # has not accounted for and the counts below cannot be trusted.
    unexplained = [
        edge
        for edge in edges
        if edge["context"] == "operative" and not edge["sourceUnit"] and not edge["sourceUnitStatus"]
    ]
    if unexplained:
        raise ExtractionError(
            f"title {title}: {len(unexplained)} operative edges sit in an unidentified "
            f"{unexplained[0]['sourceUnitKind']} with no status explaining why, e.g. {unexplained[0]['href']!r}"
        )

    by_type = Counter(edge["edgeType"] for edge in edges)
    _, dedup = dedupe(edges)
    report = {
        "title": title,
        "source": pin.as_dict(),
        "sections": len(sections),
        "edges": len(edges),
        "byEdgeType": dict(sorted(by_type.items())),
        "byElement": dict(sorted(Counter(edge["element"] for edge in edges).items())),
        "byContext": dict(sorted(Counter(edge["context"] for edge in edges).items())),
        "byUnitKind": dict(sorted(Counter(str(edge["sourceUnitKind"]) for edge in edges).items())),
        "historical": sum(1 for edge in edges if edge["historical"]),
        "uscByTargetLevel": dict(
            sorted(Counter(e["uscTargetLevel"] for e in edges if e["edgeType"] == "uscCrossReference").items())
        ),
        #: The refinement that keeps "N cross-references" from being read as
        #: "N references made by the enacted text".
        "uscByContext": dict(
            sorted(Counter(e["context"] for e in edges if e["edgeType"] == "uscCrossReference").items())
        ),
        "sameTitleSectionTargets": {"resolved": resolved, "dangling": unresolved},
        "crossTitleSectionTargets": external,
        "skipped": dict(sorted(skipped.items())),
        "deduplication": dedup,
        "elapsedSeconds": round(time.monotonic() - started, 2),
    }
    return edges, report


def _sum_counters(reports: Sequence[dict[str, Any]], *path: str) -> dict[str, int]:
    """Add one nested count mapping across every title report."""
    total: Counter[str] = Counter()
    for report in reports:
        node: Any = report
        for step in path:
            node = node[step]
        total.update(node)
    return dict(sorted(total.items()))


def corpus_deduplication(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Roll the per-title dedup accounting up to the corpus.

    Summing rather than re-deriving is safe because :data:`ASSERTION_KEY` starts
    with ``title``: no claim can span two titles, so the per-title partitions are
    disjoint by construction and their counts add.  That is a property of the key,
    so it is asserted here rather than assumed -- if ``title`` ever leaves the key
    this function becomes wrong and must be replaced by a global pass.
    """
    if ASSERTION_KEY[0] != "title":
        raise ExtractionError(
            "corpus_deduplication sums per-title counts, which is only valid while 'title' leads ASSERTION_KEY"
        )
    per_title = [report["deduplication"] for report in reports]
    return {
        "policy": per_title[0]["policy"] if per_title else {"key": list(ASSERTION_KEY)},
        "occurrenceRows": sum(entry["occurrenceRows"] for entry in per_title),
        "anchorlessRows": sum(entry["anchorlessRows"] for entry in per_title),
        "distinctClaims": sum(entry["distinctClaims"] for entry in per_title),
        "redundantOccurrences": sum(entry["redundantOccurrences"] for entry in per_title),
        "exactDuplicateRows": sum(entry["exactDuplicateRows"] for entry in per_title),
        "distinctClaimsByContext": _sum_counters(reports, "deduplication", "distinctClaimsByContext"),
        "distinctClaimsByEdgeType": _sum_counters(reports, "deduplication", "distinctClaimsByEdgeType"),
        "operativeUscCrossReferences": sum(entry["operativeUscCrossReferences"] for entry in per_title),
    }


def build_manifest(reports: Sequence[dict[str, Any]], release_point: str, elapsed: float) -> dict[str, Any]:
    """The record of one extraction: what was read, what came out, and what it is not for."""
    return {
        "type": "UslmReferenceEdgeManifest",
        "releasePoint": release_point,
        "publisher": "Office of the Law Revision Counsel, US House of Representatives",
        "rights": "US Government edict — public domain (17 U.S.C. 105)",
        "titles": len(reports),
        "edges": sum(report["edges"] for report in reports),
        "byEdgeType": _sum_counters(reports, "byEdgeType"),
        "byContext": _sum_counters(reports, "byContext"),
        "deduplication": corpus_deduplication(reports),
        "decomposition": {
            "enactingPublicLaw": "amendment source credits — the section's history, not a reference from its text",
            "statutesAtLarge": "the Statutes at Large printing of that same amendment; not an independent reference",
            "uscCrossReference": "genuine section-to-section reference; see uscByTargetLevel, not all target sections",
            "actName": "reference to a named act rather than to its codified location",
        },
        "notUsableFor": [
            "a single 'cross-references' total — pooling the four types conflates amendment credits with references",
            "counting amendments — a /us/pl and a /us/stat edge routinely describe one amendment twice",
            "assuming every /us/usc target resolves — dangling targets to repealed sections are retained and flagged",
            (
                "a corpus-wide markup-completeness claim — markup density is per-title: Title 42 marks up 83% of "
                "operative references, Title 26 only 8.7%, so Title 26's intra-title network is genuinely absent "
                "while Title 42's is largely present. Check uscByContext per title before relying on either"
            ),
            "reading uscCrossReference as enacted-text references — filter context=='operative' first",
            (
                "counting emitted rows as edges — a row is a markup occurrence; see deduplication.distinctClaims "
                "and deduplication.operativeUscCrossReferences for the claim-level counts"
            ),
            (
                "a legal predicate or an edge direction — edgeType names the citator the publisher used, not what "
                "the citation asserts; establishing the predicate is a separate unresolved question"
            ),
        ],
        "skipped": {
            "counts": _sum_counters(reports, "skipped"),
            "refWithoutHref": "<ref class='footnoteRef'> carries idref, not href: an internal pointer, not a citation",
            "inDocumentFragment": "href='#TAB_…' anchors a table in the same file: navigation, not a citation",
            "unmarkedProseCitations": (
                "same-title 'section NNN' mentions in operative text are not marked up by OLRC and cannot be "
                "recovered from this corpus at all — they are absent, not skipped by choice"
            ),
            "reservedTitles": RESERVED_TITLES,
        },
        "elapsedSeconds": round(elapsed, 2),
        "titleReports": list(reports),
    }


def build_evidence_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """The committable record of an extraction, without the extraction.

    The edge JSONL runs to hundreds of megabytes and is not committed.  What is
    committed is this: every input's URL, byte length and SHA-256; every output
    file's digest and row count; and the corpus counts.  A later run can be
    checked against it byte for byte without either artefact being in the tree.
    """
    return {
        "type": "UslmReferenceEdgeEvidence",
        "releasePoint": manifest["releasePoint"],
        "publisher": manifest["publisher"],
        "rights": manifest["rights"],
        "sourceBaseUrl": BASE_URL,
        "titles": manifest["titles"],
        "occurrenceRows": manifest["edges"],
        "byEdgeType": manifest["byEdgeType"],
        "byContext": manifest["byContext"],
        "deduplication": manifest["deduplication"],
        "skipped": manifest["skipped"],
        "notUsableFor": manifest["notUsableFor"],
        "inputs": [
            {
                "title": report["title"],
                **report["source"],
                "sections": report["sections"],
                "occurrenceRows": report["edges"],
                "distinctClaims": report["deduplication"]["distinctClaims"],
                "operativeUscCrossReferences": report["deduplication"]["operativeUscCrossReferences"],
                "outputFile": report.get("file"),
                "outputSha256": report.get("fileSha256"),
            }
            for report in manifest["titleReports"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", action="append", help="USC title code, e.g. 26 or 05a (repeatable; default: all)")
    parser.add_argument("--release-point", default=RELEASE_POINT, help=f"OLRC release point (default {RELEASE_POINT})")
    parser.add_argument("--cache", type=Path, required=True, help="directory for the downloaded publisher zips")
    parser.add_argument("--output", type=Path, required=True, help="directory to write edges and the manifest into")
    parser.add_argument(
        "--claims-output",
        type=Path,
        default=None,
        help="optional directory for the deduplicated claim rows (see ASSERTION_KEY)",
    )
    parser.add_argument(
        "--evidence-manifest",
        type=Path,
        default=None,
        help="optional path for the committable evidence manifest (inputs, digests and counts only)",
    )
    args = parser.parse_args()

    selected = tuple(args.title) if args.title else TITLES
    for title in selected:
        if title in RESERVED_TITLES:
            raise ExtractionError(RESERVED_TITLES[title])
    unknown = [title for title in selected if title not in TITLES]
    if unknown:
        raise ExtractionError(f"not USLM titles at this release point: {unknown}")

    args.output.mkdir(parents=True, exist_ok=True)
    if args.claims_output:
        args.claims_output.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    started = time.monotonic()

    for title in selected:
        edges, report = extract_title(title, args.release_point, args.cache)
        payload = "".join(_canonical(edge) + "\n" for edge in edges).encode("utf-8")
        filename = f"edges-t{title}.jsonl"
        (args.output / filename).write_bytes(payload)
        report["file"] = filename
        report["fileSha256"] = _sha256(payload)
        if args.claims_output:
            claims, _ = dedupe(edges)
            claim_payload = "".join(_canonical(edge) + "\n" for edge in claims).encode("utf-8")
            claim_name = f"claims-t{title}.jsonl"
            (args.claims_output / claim_name).write_bytes(claim_payload)
            report["claimsFile"] = claim_name
            report["claimsFileSha256"] = _sha256(claim_payload)
        reports.append(report)
        print(
            f"  t{title:<4} {report['edges']:>7} rows  {report['deduplication']['distinctClaims']:>7} claims  "
            + "  ".join(f"{k}={v}" for k, v in sorted(report["byEdgeType"].items()))
            + f"  [{report['elapsedSeconds']}s]"
        )

    manifest = build_manifest(reports, args.release_point, time.monotonic() - started)
    (args.output / "manifest.json").write_text(_canonical(manifest) + "\n", encoding="utf-8")

    dedup = manifest["deduplication"]
    print(f"\n{manifest['edges']} occurrence rows across {manifest['titles']} titles in {manifest['elapsedSeconds']}s")
    for edge_type, count in manifest["byEdgeType"].items():
        print(f"  {edge_type:<20} {count}")
    print(
        f"\ndeduplication under {'+'.join(ASSERTION_KEY)}:\n"
        f"  {dedup['occurrenceRows']} occurrence rows\n"
        f"  {dedup['anchorlessRows']} with no source anchor (state no claim; retained as evidence)\n"
        f"  {dedup['redundantOccurrences']} redundant repeats of a claim already counted\n"
        f"  {dedup['distinctClaims']} distinct claims\n"
        f"  {dedup['operativeUscCrossReferences']} section-to-section references made by enacted text"
    )
    if args.evidence_manifest:
        args.evidence_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_manifest.write_text(_canonical(build_evidence_manifest(manifest)) + "\n", encoding="utf-8")
        print(f"\nwrote {args.evidence_manifest}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

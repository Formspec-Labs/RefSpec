"""The publisher's own authority note for a CFR part, asked of a pinned cache.

Every rule in the Unified Agenda names the CFR parts it amends, and the Office
of the Federal Register prints, at the head of each of those parts, the
agency's own statement of the authority under which it was issued. That note is
the same claim the rule's Legal Authority boxes make, written by the same
agency and typeset by a publisher -- **the record carrying its own answer key**,
which is the first of the five cross-cutting findings of the human review of
2026-08-23 (``research/evidence/sample-review-2026-08-23/review.md``). It
settled seven of the ten rows in that review's class A ("unreadable") and
resolved or bounded five of the ten in class E ("section absent"), and the
reviewers asked for it by name in both.

This module is the reader for the cache the silent-misreads campaign left
behind, and nothing more: it says whether a note names a citation, one edit
away from one, or neither. **It repairs nothing.** A verdict is a fact about
the publisher's note beside the filer's text; which of the two is wrong is a
different question, and this module does not answer it.

What the cache is
-----------------
``research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl``, **8,240
records -- every authority note the CFR publishes**, digest-pinned here
(:data:`NOTES_SHA256`, :data:`NOTES_BYTE_LENGTH`) and re-checked on every load,
the way :mod:`refspec.registry.usc_section_oracle` pins its six tables. Fetched
**2026-08-24**, one request per TITLE rather than one per part: the 49
non-reserved titles' full XML, each at its own ``latest_issue_date`` as
``titles.json`` named it that day, so every document is the edition the
publisher currently serves. Those dates run from 2024-05-17 (title 3, unamended
since 2015) to 2026-08-20 and are **not** the fetch date, which is why
:data:`NOTES_ENDPOINT` states an issue date it cannot fill in; every record
carries the concrete URL it came from and the digest of the document it was cut
from.

The register publishes 9,666 parts; 8,240 state an authority and 1,426 state
none (mostly ``[RESERVED]`` placeholders). Each record carries the part, the
note and source-note TEXT as the publisher wrote them, the request URL, the
fetch date, and the ``raw_sha256``/``raw_bytes`` of the title document it was
cut from, so a re-fetch is checkable byte-for-byte. Nothing was truncated:
``raw_truncated_at_128k`` is false on all 8,240 rows, where the 287-record
generation 1 flagged 211 responses captured to a 128 KB head. The raw XML is
**not** retained -- 810 MB -- and the fetch, the extractor and the validation
are in that directory's README.

**Generation 1 is still committed and untouched** at
``research/evidence/silent-misreads-2026-08-22/ecfr-authority-notes.jsonl``:
287 parts chosen by greedy set-cover over the agenda-to-CFR mapping. All 287
are here, 278 byte-identical and 9 differing in a single character reference
apiece -- the ``?part=`` view escapes non-ASCII and the full-title view emits
UTF-8 -- and **no note's words changed between the two dates**. Two of the nine
were fetched at the same issue date on both sides and still differ, which
settles that the cause is the API view rather than the passage of time.
:func:`note_body` reads all nine identically, so nothing a row already carried
moved because of the encoding; the 21,882 verdicts that did move at the switch
are the coverage effect described below, and none of them is one of these.

**80 of the 8,240 parts state no authority at part level and do state one under
their first subdivision**, and this reader takes that note as the part's
witness -- deliberately, and for continuity: generation 1 read a per-part
response top-down and took the first ``<AUTH>`` it met, so 20 CFR 404 and 416
and 5 CFR 550, three of the most-cited parts in the corpus, were already being
judged against a Subpart A note. Dropping them would have deleted verdicts
rather than added any. What changes is that the arrangement is now stated
rather than implied: :attr:`AuthorityNote.authority_level` is ``"part"`` or
``"subdivision"`` and :attr:`AuthorityNote.authority_scope` names the
subdivision, so a consumer who wants only part-level authority can tell the two
apart, and ``cfr_note_part`` naming "20 CFR 404" can be traced to the note that
actually said it. An ``<AUTH>`` under a LATER subdivision is not the part's
note and is not read here at all.

Coverage: the corpus names 8,652 distinct parts on this reader's own join key
and the cache holds **5,793 of them (67.0%), carrying 384,451 of the 420,622
CFR-reference rows (91.4%)**. The 2,859 misses are almost all time rather than
gap -- 1,926 parts no longer exist at the current date, 645 fall inside a
published reserved block, 228 are published ``[RESERVED]`` -- and they skew
old: 72.0% of their rows come from Agenda publications before 2010, against
54.7% of the covered ones. Measured on the pinned Agenda build, that is
**713,547 of 799,126 authority rows covered and 668,894 judged, over 40,613
RINs**, where the 287 parts covered 489,969 and judged 460,887 over 22,788.

**Widening the cache moved verdicts that rows already carried, and that is a
property of :meth:`CfrAuthorityNotes.judge` rather than of the notes.** The
verdict is the best one ANY of the rule's own held parts gives, because a rule
amending four parts is authorised by all four notes together -- so an absence
recorded against the one part the set-cover happened to reach can be settled by
a sibling part it did not. At the switch that moved 21,882 already-judged rows,
every one of them upward (11,287 absent to present, 8,091 near-miss to present,
2,504 absent to near-miss) with no downgrade and no return to NULL, plus 38,913
rows that keep their verdict and name a different part because the part an
absence names is the first HELD part in citation order. No note said anything
new: asking each of the 287 generation-1 parts' own note the 16,373
(part, citation) questions the corpus puts to it gives the identical verdict
under both generations, 0 disagreements.

The gap the switch closes is best read on the campaign's own opening specimen:
**45 CFR 12a, whose entire note is** *"42 U.S.C. 11411; 40 U.S.C. 550."*, was a
tiny part the top-300 set-cover never reached and was fetched by hand; it is
now held, and
``test_the_cache_now_holds_the_part_that_settled_the_opening_specimen`` reads
that note rather than pinning its absence.

The extractor was written independently of :mod:`citation_grammar` on purpose,
so the oracle shares no code with the thing under test. **This reader is the
other side of that arrangement and deliberately does not repeat it**: the
question here is "does the note name what the filer named", and the two sides
of that comparison have to be spelled by one grammar or the comparison is
between two spellings rather than between two claims. So a note is read with
:func:`refspec.registry.citation_grammar.parse_authority_citation`, exactly as
a filer's box is, and the note text stays in :attr:`AuthorityNote.authority_note`
for a consumer who disagrees with the reading.

The three verdicts, and what the survey measured each to be worth
----------------------------------------------------------------
``present``
    The note names the citation. Identity is compared, not spelling:
    ``40:550`` is the pair (title, section) with the section normalized the
    way the section oracle normalizes it. A note **range** covers the sections
    between its endpoints -- 10 CFR 430 says "42 U.S.C. 6291-6309" and a rule
    citing 42 U.S.C. 6295 is named by it -- because that is the note's own
    claim about its own span. ``et seq.`` is **not** a range and is never read
    as one: "49 U.S.C. 60101 et. seq." names 60101, so 49 U.S.C. 60137 is
    absent from 49 CFR 192's note as the publisher writes it today, which is
    the honest answer and not the one a reader hoping to confirm review A's
    specimen would prefer.

``near-miss``
    The note names a citation of the same family **one edit away**, where an
    edit is one insertion, deletion, substitution or transposition of a single
    character (:func:`citation_grammar.damerau_levenshtein` = 1) in the
    canonical identity. The identity is spelled title-and-section
    (``17:12a``), so a wrong TITLE beside a right section is one edit too --
    the mechanism behind the campaign's ``17 USC 12a`` specimen, which 17 CFR
    part 1's note settles as **7** U.S.C. 12a.

    **It is nearly worthless on its own, and that is worth knowing.** The
    campaign adjudicated 31 random near-miss texts (428 rows) and measured
    precision **12.9% by text, 5.6% by rows**: the bucket is dominated by
    agencies legitimately citing a real neighbouring section. What made it
    sharp was conjunction with an independent impossible-referent oracle --
    Table III absence plus a not-found at OLRC -- which took 4,455 rows to
    100% precision on 44 adjudicated texts. This module publishes the loose
    verdict because the conjunction is a consumer's join (the section oracle's
    columns sit in the same table), and it says here, once, that the loose
    verdict alone accuses nobody.

``absent``
    Neither. **Absent from the note as fetched on 2026-08-24** -- never
    "wrong": a note is a living document and the corpus runs from 1995. 49 CFR
    192's note enumerated §§ 60102-60137 when RIN 2137-AE60 cited them in 2010
    and reads "60101 et. seq." today; both are the publisher's text, eight
    years apart. An ``absent`` here is a question, and the era caveat is
    attached to the class rather than to the row because it is a property of
    every row in it.

What is judged, and what is not
-------------------------------
Four families, named in :data:`FAMILIES`: the U.S.C. title and section, the
Public Law, the CFR title and part, and the act NAME for an act-relative row
(resolved key, or the name as stated where nothing resolved it). They are the
four the review's evidence rests on. Executive orders, Statutes-at-Large
pages, chapters and the rest are left unjudged rather than half-judged: an EO
number has no impossible-referent oracle behind it (every in-range number
names a real order), and the campaign says so explicitly. The builder counts
the rows it leaves unjudged, by type, so the population stays visible.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path

from refspec.registry.citation_grammar import (
    damerau_levenshtein,
    normalize_popular_name,
    parse_authority_citation,
    stated_act_name,
)
from refspec.registry.usc_section_oracle import (
    USC_SECTION_ORACLE_ARTIFACT,
    UscSectionOracle,
    normalize_section,
)

__all__ = [
    "CFR_AUTHORITY_NOTES_ARTIFACT",
    "FAMILIES",
    "NEAR_MISS_MAX_EDITS",
    "NOTES_BYTE_LENGTH",
    "NOTES_ENDPOINT",
    "NOTES_EXPECTED_RECORDS",
    "NOTES_FETCHED",
    "NOTES_SHA256",
    "VERDICTS",
    "AuthorityNote",
    "CfrAuthorityNotes",
    "Citation",
    "NoteVerdict",
    "act_citation",
    "cfr_citation",
    "normalize_part",
    "note_body",
    "public_law_citation",
    "read_note_citations",
    "usc_citation",
]

#: The cache, relative to the repository root. One file, so a flat pin: the
#: digest and the byte length are literals here rather than read from the
#: README beside the file, because reading the pin FROM the artifact would
#: authenticate a swapped file against its own paperwork -- the same argument
#: :data:`refspec.registry.usc_section_oracle._ORACLE_PINS` makes.
CFR_AUTHORITY_NOTES_ARTIFACT = "research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl"
NOTES_SHA256 = "sha256:ec2e57aa15c5284b2073fad53dd27a686110e398f6c6f20f6c54207e4b9386de"
NOTES_BYTE_LENGTH = 7_470_473
#: Pinned beside the digest because it is the claim a reader makes out loud:
#: 9,666 parts published across the 49 non-reserved titles, 8,240 of them
#: stating an authority somewhere this reader reads.
NOTES_EXPECTED_RECORDS = 8_240

#: When, and from where. Both are in every record too; these are what the
#: module states without opening the file.
NOTES_FETCHED = "2026-08-24"
#: **Two placeholders, and the date is not this module's to supply.** One request
#: per title, at that title's OWN latest issue date -- 49 different dates on one
#: fetch day -- so the endpoint cannot be a string with the date already in it
#: the way generation 1's per-part request was. The date belongs to the
#: document, not to the reader: each record's ``api_url`` is the concrete URL
#: that answered, and
#: ``research/evidence/ecfr-authority-notes-2026-08-24/manifest.json`` is the
#: copy of record for all 50 titles including the reserved one.
#: ``test_the_cache_is_the_bytes_this_module_pins`` holds this template against
#: every record's own URL, so a drifted endpoint fails rather than describes.
NOTES_ENDPOINT = "https://www.ecfr.gov/api/versioner/v1/full/{issue_date}/title-{title}.xml"

VERDICTS = ("present", "near-miss", "absent")

#: The four citation families this module compares. See the module docstring
#: for why an executive order is not one of them.
FAMILIES = ("usc", "public_law", "cfr", "act")

#: One edit, the survey's own definition. Raising it was not measured and must
#: not be done quietly: at one edit the bucket already runs 12.9% precise by
#: text.
NEAR_MISS_MAX_EDITS = 1

#: The publisher's label on the front of the note ("Authority:"), which is not
#: part of any citation. Left on, the grammar reads nothing extra -- but the
#: text a test quotes should be the text the reader judges.
_AUTHORITY_LABEL = re.compile(r"^\s*Authority\s*:\s*", re.IGNORECASE)

#: A note is a semicolon-separated list of authorities, the same shape the
#: Agenda's boxes have. Two things are read off the segments: the ACT NAME
#: (``stated_act_name`` reports one name per string, and 10 CFR 50's note names
#: six acts) and the ELIDED TITLE (see :func:`_carried_title_citations`).
_NOTE_SEGMENT = re.compile(r";")

#: A segment that is nothing but section tokens and the separators between
#: them: "1531-1544", "551, 552a", "1103, 1104". Prose, a parenthetical, a
#: statute page or a scheme label all fail it, which is what keeps the title
#: carry below off everything except a continued list.
_SECTION_TOKEN = r"\d{1,5}[A-Za-z]{0,3}(?:-\d{1,5}[A-Za-z]{0,3})?(?:\([0-9A-Za-z]{1,4}\))*"
_SECTION_LIST_ONLY = re.compile(
    rf"^(?:and\s+)?{_SECTION_TOKEN}(?:\s*(?:,|and|or|to|through)\s*{_SECTION_TOKEN})*[.,]?$",
    re.IGNORECASE,
)

#: A section token's sort key, as the Code orders sections: leading digits as a
#: number, the remainder as text. Restated from
#: ``usc_section_oracle._section_key`` rather than imported -- it is private
#: there -- and held true by
#: ``test_the_section_order_is_the_oracles_over_every_section_the_notes_name``,
#: which runs both over every section in the cache. Comparing numeric prefixes
#: alone reports "15 USC 717 to 717w" as a descending range; it is not.
_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")


def _section_order(section: str) -> tuple[int, str] | None:
    match = _LEADING_DIGITS.match(section)
    return (int(match.group(1)), match.group(2)) if match else None


def normalize_part(part: object) -> str | None:
    """The join key for a CFR part: leading zeros stripped, case folded.

    "0718" and "718" are one part, which is what the Agenda's own reference
    table declares (``partIsAJoinKey``); "12a" is not "12". ``None`` where
    there is no part.
    """

    text = str(part or "").strip().lower()
    if not text:
        return None
    return text.lstrip("0") or "0"


@dataclass(frozen=True)
class Citation:
    """One citation, reduced to the identity two claims are compared on.

    ``identity`` is a string per family and never parsed again: ``40:550`` for
    a U.S.C. section, ``95-217`` for a Public Law, ``49:1`` for a CFR part,
    and the normalized popular name for an act. One string means one
    edit-distance rule for all four, and it means a wrong title counts as the
    edit it is.
    """

    family: str
    identity: str
    #: U.S.C. only, and only on the NOTE side: the far end of a stated span, so
    #: "42 U.S.C. 6291-6309" can cover the 6295 a rule cites. A filer's range
    #: is judged on its start alone, the way the section fence judges
    #: ``usc_section`` and never ``usc_section_end``.
    span_end: str | None = None

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"undeclared citation family: {self.family!r}")
        if not self.identity:
            raise ValueError("a citation with no identity is not a citation")
        if self.span_end is not None and self.family != "usc":
            raise ValueError("only a U.S.C. citation carries a span")


def usc_citation(title: object, section: object, section_end: object = None) -> Citation | None:
    """``(40, "550")`` -> ``usc 40:550``. ``None`` where either half is missing."""

    if title is None:
        return None
    normalized = normalize_section(section)
    if not normalized:
        return None
    end = normalize_section(section_end) or None
    return Citation(family="usc", identity=f"{int(title)}:{normalized}", span_end=end)


def public_law_citation(public_law: object) -> Citation | None:
    """``"95-217"`` -> ``public_law 95-217``."""

    text = str(public_law or "").strip().lower()
    return Citation(family="public_law", identity=text) if text else None


def cfr_citation(cfr_title: object, cfr_part: object) -> Citation | None:
    """``(49, "1")`` -> ``cfr 49:1``. The SECTION under the part is not identity
    here: a note naming "49 CFR 1.97" names part 1, and a rule citing 49 CFR
    1.53 names the same part. Judging the section would call two delegations of
    the same part a mismatch."""

    part = normalize_part(cfr_part)
    if cfr_title is None or part is None:
        return None
    return Citation(family="cfr", identity=f"{int(cfr_title)}:{part}")


def act_citation(name: object) -> Citation | None:
    """A popular name, normalized the way the OLRC index keys it."""

    key = normalize_popular_name(name)
    return Citation(family="act", identity=key) if key else None


def note_body(note: object) -> str:
    """The note's text as the publisher wrote it: label off, entities decoded.

    The cache holds the ``<AUTH>`` element's text as the extractor took it, and
    **every HTML entity ends in a semicolon**, which is the character a note is
    split on. So an undecoded entity splits a segment down the middle, and the
    title carry below then reads the tail as a section list.

    The full-title documents generation 2 was cut from write a section sign and
    an em dash as literal UTF-8 (104 and 22 occurrences, over 56 and 19 notes),
    so the entity generation 1 met most often is not the one here. What is here
    is **``&amp;`` six times over six notes**, plus one ``&gt;`` in a source
    note. Generation 1 spelled the section sign ``&#xA7;`` and the em dash
    ``&#x2014;``, 19 and 4 occurrences over 9 of its 287 notes, and decoding is
    what makes those nine read identically across the two generations.

    **Decoding changes what the grammar reads, in both directions, and the
    three places it does are measured rather than assumed.** Over every
    entity-bearing note in both files:

    * 19 CFR part 4 (generation 1) writes "Pub. L. 108-7, Division B, Title
      II,&#xA7; 211", which segments into a bare "211" and the carry reads as
      46 U.S.C. 211. Decoding **deletes that phantom**, which is the whole
      reason this function exists.
    * 36 CFR 59 writes "Sec. 6, L&amp;WCF Act of 1965", which reads as the act
      named "wcf act of 1965" undecoded and "l&wcf act of 1965" decoded.
      Decoding is right: the Land and Water Conservation Fund Act is not the
      WCF Act.
    * 36 CFR 230's whole note is "16 U.S.C. 2103(d) &amp; 2109(e)." Undecoded
      it splits into "…2103(d) &amp" and "2109(e).", and the carry supplies
      title 16 to the tail. Decoded it is one segment, and the grammar does not
      continue a section list across "&" -- so **decoding LOSES 16 U.S.C.
      2109**. That costs exactly **2 rows**: the corpus cites 16 U.S.C. 2109
      twice, both under rules that name 36 CFR 230, both written by the filer
      as "16 U.S.C. 2103(d) and 2109(e)" -- the same list the note writes with
      an ampersand -- and both read ``near-miss`` against a note that names it
      in plain sight. Recorded, not repaired: the fix belongs in the grammar's
      treatment of "&" as a list separator and not in a decision to leave the
      publisher's own text mis-spelled.
      ``test_decoding_the_publishers_ampersand_costs_36_cfr_230_its_second_section``
      pins it.

    Decoding is not a normalization of the publisher's words, it IS the
    publisher's words; where it costs something, the cost is named above.
    """

    return html.unescape(_AUTHORITY_LABEL.sub("", str(note or ""), count=1))


def _carried_title_citations(segment: str, title: int) -> tuple[Citation, ...]:
    """A continued section list under the title stated one segment earlier.

    The publisher writes one authority list and elides the repeated title:
    50 CFR part 17's whole note is "16 U.S.C. 1361-1407; **1531-1544**; and
    4201-4245". The grammar carries a title across a COMMA and not across a
    semicolon -- ``16 U.S.C. 1361-1407, 1531-1544`` reads three ranges and
    ``16 U.S.C. 1361-1407; 1531-1544`` reads one -- so the separator the
    publisher happened to choose decided whether the Endangered Species Act
    was in its own part's note. It was not: **8,126 rows** citing 16 U.S.C.
    1531 read "absent" against a note that lists it in plain sight, and they
    were the largest single block in that bucket.

    So the title is supplied and the GRAMMAR does the reading -- the same
    shape the builder's own titleless-U.S.C. corroboration takes. The guard is
    tight, because inventing a note citation would turn a real absence into a
    false present: the segment must state no citation of any kind on its own,
    and must be nothing but section tokens and separators
    (:data:`_SECTION_LIST_ONLY`). Over the whole register that carries **124
    segments in 58 parts** -- all 18 that generation 1's 287 notes carried are
    among them, unchanged -- and every one but the two named below is a
    continued list.

    **Two of them are wrong, and both are the publisher's elision rather than
    the rule's.** 22 CFR part 41 ends "8 U.S.C. 1101; ... 1323; 1361; 2651a."
    and that last one is 22 U.S.C. 2651a, the Secretary of State's own
    authority -- the title changes and the note does not say so. And 32 CFR
    part 634, which generation 1 did not hold, ends "5 U.S.C. 2951; Pub. L.
    89-564; 89-670; 91-605; and 93-87.": the elided label is **Pub. L.** and
    not a U.S.C. title, so the carry reads three Public Law numbers as section
    ranges of title 5, two of which (89-670 and 91-605) are ordered and
    therefore SPAN. Neither costs anything in this corpus -- no row cites 8
    U.S.C. 2651a, and the 92 rows on the two RINs that name 32 CFR 634 cite 5
    U.S.C. 2951, which is outside both spans -- and both are pinned by
    ``test_the_two_carried_titles_the_publishers_own_elision_gets_wrong``
    rather than left to be discovered. A guard that could tell them from the
    122 right ones would need to know that a hyphenated pair after a Pub. L.
    segment is a law and not a range, which is a Code roster and a label
    memory this reader does not have; this unit widened the notes and not the
    predicate, and the candidate is recorded here rather than half-fixed.

    **And the guard's own cost, measured**: the same note's "1185 note (Section
    7209 of Pub. L. 108-458, as amended by Section 546 of Pub. L. 109-295)"
    carries a parenthetical, so it is not a section list and the title does not
    carry into it -- and the **30 rows** whose filers write "8 USC 1185 note"
    read ``near-miss`` against a note that names exactly that. Widening the
    guard to admit a parenthetical would admit prose, and prose under a
    supplied title is how a note citation gets invented; 30 rows of false lead
    is the cheaper error, and it is stated rather than absorbed.
    """

    return tuple(
        citation
        for parsed in parse_authority_citation(f"{title} U.S.C. {segment.strip()}")
        if parsed.authority_type == "usc"
        and (citation := usc_citation(parsed.usc_title, parsed.usc_section, parsed.usc_section_end)) is not None
    )


def read_note_citations(note: str, *, oracle: UscSectionOracle | None = None) -> tuple[Citation, ...]:
    """Every citation of the four families a note names, in the note's order.

    One grammar: the note is read by
    :func:`refspec.registry.citation_grammar.parse_authority_citation`, which
    is what reads the filer's box on the other side of the comparison. Act
    NAMES come from :func:`citation_grammar.stated_act_name` over the note's
    semicolon-separated segments, because that function reports one name per
    string and a note names as many acts as it has segments -- 10 CFR 50 names
    six. The same segments carry the elided title; see
    :func:`_carried_title_citations`.

    **The Statutes-at-Large gate** (mined ledger item 4,
    research/investigations-mined-2026-08-31.md ~lines 77-85). The grammar
    marks (:attr:`AuthorityCitation.usc_section_after_statute`) every U.S.C.
    list member it reaches by scanning PAST a Statutes-at-Large citation --
    "12 U.S.C. 2013, ...; sec. 301(a), Pub. L. 100-233, 101 Stat. 1568,
    1608" published 12 U.S.C. 1608, the Act's own pinpoint page, not a
    section (12 CFR 615's own note, one of 129 notes / 403 marked citations
    measured 2026-09-01). It cannot decide which are real -- 14 CFR 121's
    note is the identical shape and genuinely resumes 49 U.S.C. 44101,
    44701-44702, ... after "126 Stat. 89" -- so it marks rather than refuses,
    and THIS is where the mark is spent: a marked citation is offered only
    when ``oracle.section_is_enumerated`` says so -- the EXACT-list check
    (:meth:`UscSectionOracle.section_is_enumerated`), not the broader
    :meth:`UscSectionOracle.section_exists`, which also affirms a bare
    printed RANGE stub and admitted every one of 12 CFR 615's own fabricated
    pages ("993" among them) on that softer evidence alone, measured before
    this method settled on the stricter one. ``oracle=None`` (no caller
    supplied one, and :meth:`CfrAuthorityNotes.from_file` found no sealed
    oracle directory in the tree the notes cache lives in) withholds every
    marked citation -- refusing rather than reintroducing the fabrication
    silently. A DRIFTED oracle is a different fact and is not degraded to
    this one: see :func:`_oracle_for_root`.

    The gate is not perfect and is not claimed to be, even at the stricter
    check: 8 CFR 281's own note carries "Public Law 107-296, 116 Stat. 2135
    (6 U.S.C. 101 et seq.); 66 Stat. 173, 195, 197, 201, 203, 212, 219,
    221-223, 226, 227, 230" -- the Immigration and Nationality Act's own
    page list, misattributed to title 6 because "6 U.S.C. 101" is the
    nearest anchor a comma-list this reader has always walked from (a
    PRE-EXISTING property of how a title governs a list, not something this
    gate introduces or can fix within its own scope). "197", "219", "227"
    and "230" are refused (title 6 has no such sections); "195", "201",
    "203", "212" and "226" are each, coincidentally, real title-6 sections
    (the Homeland Security Act's own numbering happens to fill that range)
    and are admitted. Measured 2026-09-01: of 403 marked citations, 266 are
    refused and roughly 111 admitted that a no-oracle default would have
    withheld; a manual digit-length pass over the admitted set found this
    same misattributed-title shape behind most of the short (1-3 digit)
    survivors, concentrated in a handful of long, multi-Act notes (17 CFR
    240 and 249 among them). This is the same shape of imperfection B8's
    two-witness rule and the near-miss bucket already carry in this module;
    it is not solved here, and is recorded rather than hidden -- see the
    DELTAS.md beside the measurement in
    ``research/evidence/stat-page-gate-2026-09-01/``.
    """

    body = note_body(note)
    found: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    def offer(citation: Citation | None) -> None:
        if citation is None or (citation.family, citation.identity) in seen:
            return
        seen.add((citation.family, citation.identity))
        found.append(citation)

    for parsed in parse_authority_citation(body):
        if parsed.authority_type == "usc":
            if parsed.usc_section_after_statute and not (
                oracle is not None
                and parsed.usc_title is not None
                and parsed.usc_section is not None
                and oracle.section_is_enumerated(parsed.usc_title, parsed.usc_section, appendix=parsed.usc_appendix)
            ):
                continue
            offer(usc_citation(parsed.usc_title, parsed.usc_section, parsed.usc_section_end))
        elif parsed.authority_type == "public_law":
            offer(public_law_citation(parsed.public_law))
        elif parsed.authority_type == "cfr":
            offer(cfr_citation(parsed.cfr_title, parsed.cfr_part))
    title: int | None = None
    for segment in _NOTE_SEGMENT.split(body):
        parsed_segment = parse_authority_citation(segment)
        stated = [one for one in parsed_segment if one.authority_type == "usc" and one.usc_title is not None]
        if stated:
            title = stated[-1].usc_title
        elif (
            title is not None
            and all(one.authority_type in {"other", "unstated"} for one in parsed_segment)
            and _SECTION_LIST_ONLY.match(segment.strip())
        ):
            for carried in _carried_title_citations(segment, title):
                offer(carried)
        offer(act_citation(stated_act_name(segment)))
    return tuple(found)


@dataclass(frozen=True)
class NoteVerdict:
    """One verdict, and WHICH part's note gave it."""

    verdict: str
    cfr_title: int
    cfr_part: str

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"undeclared verdict: {self.verdict!r}")

    @property
    def cited_as(self) -> str:
        """``"40 CFR 136"`` -- the part as a citation, which is how a consumer
        will look it up."""

        return f"{self.cfr_title} CFR {self.cfr_part}"


@dataclass(frozen=True)
class AuthorityNote:
    """One part's note, as the publisher wrote it, and what it names."""

    cfr_title: int
    cfr_part: str
    #: The publisher's text, kept whole beside the reading, the way the Agenda
    #: tables keep ``authority_text`` beside a parse.
    authority_note: str
    source_note: str | None
    api_url: str
    fetched: str
    raw_sha256: str
    raw_bytes: int
    raw_truncated_at_128k: bool
    citations: tuple[Citation, ...]
    #: ``"part"`` where the publisher states the authority under the part's own
    #: head, ``"subdivision"`` on the 80 parts that state it only under their
    #: first subdivision -- and :attr:`authority_scope` names that subdivision
    #: ("SUBPART A"). Carried rather than flattened because the note this
    #: reader answers with is what a consumer will go and read: ``cfr_note_part``
    #: says "20 CFR 404" and the words are Subpart A's, and without these two
    #: fields there is no way to learn that from the reader. Defaults say
    #: "part" so a file in this schema that omits them still loads.
    authority_level: str = "part"
    authority_scope: str = "part"

    @property
    def part(self) -> tuple[int, str]:
        return (self.cfr_title, self.cfr_part)

    @property
    def cited_as(self) -> str:
        return f"{self.cfr_title} CFR {self.cfr_part}"

    @cached_property
    def identities(self) -> Mapping[str, frozenset[str]]:
        """``family -> the identities the note names``."""

        out: dict[str, set[str]] = {family: set() for family in FAMILIES}
        for citation in self.citations:
            out[citation.family].add(citation.identity)
        return {family: frozenset(values) for family, values in out.items()}

    @cached_property
    def _usc_spans(self) -> tuple[tuple[int, tuple[int, str], tuple[int, str]], ...]:
        """The note's stated U.S.C. ranges, as ``(title, low key, high key)``."""

        spans: list[tuple[int, tuple[int, str], tuple[int, str]]] = []
        for citation in self.citations:
            if citation.family != "usc" or citation.span_end is None:
                continue
            title, section = citation.identity.split(":", 1)
            low, high = _section_order(section), _section_order(citation.span_end)
            if low is not None and high is not None and low <= high:
                spans.append((int(title), low, high))
        return tuple(spans)

    def _span_covers(self, citation: Citation) -> bool:
        title, section = citation.identity.split(":", 1)
        key = _section_order(section)
        if key is None:
            return False
        return any(low <= key <= high for span_title, low, high in self._usc_spans if span_title == int(title))

    def judge(self, citation: Citation) -> str:
        """present / near-miss / absent, for one citation against this note."""

        identities = self.identities.get(citation.family, frozenset())
        if citation.identity in identities:
            return "present"
        if citation.family == "usc" and self._span_covers(citation):
            return "present"
        if any(damerau_levenshtein(citation.identity, other) <= NEAR_MISS_MAX_EDITS for other in identities):
            return "near-miss"
        return "absent"


def _verify(path: Path) -> tuple[bytes, str]:
    """The cache's bytes, refusing loudly on drift. Returns (bytes, digest)."""

    payload = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if digest != NOTES_SHA256 or len(payload) != NOTES_BYTE_LENGTH:
        raise ValueError(
            "pinned eCFR authority-note cache drifted: "
            f"expected {NOTES_SHA256}/{NOTES_BYTE_LENGTH}, observed {digest}/{len(payload)}"
        )
    return payload, digest


#: How many path components :data:`CFR_AUTHORITY_NOTES_ARTIFACT` itself has
#: ("research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl" = 4) --
#: walking up that many parents from any concrete notes.jsonl path recovers
#: the repository root without a caller having to state it twice. The
#: production builder (``unified_agenda_parquet._cfr_authority_notes``) calls
#: :meth:`CfrAuthorityNotes.from_file` with the bare path, not
#: :meth:`from_repository`, and is not this lane's file to change to pass an
#: oracle explicitly -- so :meth:`from_file` has to be able to find one on
#: its own.
_ARTIFACT_PATH_DEPTH = len(Path(CFR_AUTHORITY_NOTES_ARTIFACT).parts)


@cache
def _oracle_for_root(root: Path) -> UscSectionOracle | None:
    """The section-existence oracle a repository root carries, or ``None``.

    ``None`` for exactly ONE fact: the sealed oracle directory is not there
    at all. That is a tree which never carried the artifact, the caller
    (:meth:`CfrAuthorityNotes.from_file`) degrades to withholding every
    Statutes-at-Large-gated citation, and withholding is the fail-closed
    reading -- see :func:`read_note_citations`.

    Every OTHER failure PROPAGATES, and the drifted pin is the one that
    matters. :class:`UscSectionOracle` refuses drifted tables by raising and
    this module refuses a drifted note cache by raising (:func:`_verify`);
    catching the oracle's refusal here would make a corrupted artifact the
    one quiet failure in a repository that has no other, silently costing
    the 111 genuine citations the oracle admits (measured 2026-09-01:
    34,777 citations with the oracle, 34,666 without) with no receipt saying
    it was never asked.

    Memoized on the root: the six tables are 9,229,092 bytes, and without
    this every :meth:`CfrAuthorityNotes.from_file` call pays their load
    again -- 7.5 s per construction against 5.4 s without the oracle,
    measured 2026-09-01 on the machine the suite's budget was set on. One
    root per process, in practice.
    """

    if not (root / USC_SECTION_ORACLE_ARTIFACT).is_dir():
        return None
    return UscSectionOracle.from_repository(root)


def _default_oracle(notes_path: Path) -> UscSectionOracle | None:
    """The oracle carried by the repository the notes cache itself lives in."""

    root = notes_path.resolve()
    for _ in range(_ARTIFACT_PATH_DEPTH):
        root = root.parent
    return _oracle_for_root(root)


@dataclass(frozen=True)
class CfrAuthorityNotes:
    """The 8,240 pinned notes, read once and asked many times.

    Constructed only through :meth:`from_file` or :meth:`from_repository`, so
    a reader that exists has already authenticated its bytes -- there is one
    file here, so unlike the six-table section oracle there is no way to
    authenticate part of it.

    **Construction reads every note through the grammar**: 34,777 citations
    against generation 1's 4,488, which measures at ~5.4 s against ~1.35 s on
    the machine the suite's budget was set on -- plus the section-existence
    oracle's own load (:func:`_default_oracle`), ~2.1 s, paid once per
    repository root per process rather than once per reader
    (:func:`_oracle_for_root` memoizes it). The builder constructs one reader
    per build and the test module constructs three, so the cost is paid a
    handful of times and never per row; the per-question cost is
    :attr:`_memo`'s.

    **That count moved twice.** It read 36,325 until the #46 list-tail
    fences landed on 2026-08-24, when 1,282 citations in 806 notes stopped
    being read because they were never citations: 793 of them numbers
    belonging to a Title 3 COMPILATION LOCATOR ("E.O. 12234, 45 FR 58801, 3
    CFR, 1980 Comp., p. 277" published sections 1980 of whatever title the
    note last named), 467 DOTTED CFR SECTIONS ("7 CFR 2.22, 2.80, and 371.4"
    published 21 U.S.C. 2 and 21 U.S.C. 371, the second of which is real),
    and 22 in 14 notes that were the VOLUME of a treaty series or a case
    reporter standing behind a comma ("United States ex rel. Touhy v. Ragen,
    340 U.S. 462" behind "50 U.S.C. 403g" published 50 U.S.C. 340). None
    arrived. The full list, note by note with each note's text, is the
    unit's evidence; both rules and their measured populations are in
    :data:`~refspec.registry.citation_grammar._A_DOTTED_NUMBER_IS_A_CFR_SECTION`
    and the compilation fence beside it.

    **It moved again on 2026-09-01, from 35,043 to 34,777** — the Statutes-
    at-Large gate (mined ledger item 4): a Public Law's own pinpoint page,
    written "101 Stat. 1568, 1608", was read as a resumed U.S.C. list member
    of whatever title the note last named ("12 U.S.C. 1608" from 12 CFR
    615's own note, which never named that section). 266 citations in 107
    notes were refused this way, gated by :func:`read_note_citations`'s own
    exact-enumeration check rather than deleted outright -- 14 CFR 121's
    note genuinely resumes a real 49 U.S.C. list after its own Stat.
    citation, and roughly 111 marked citations across 40 notes are admitted
    rather than refused for exactly that reason, or for the documented
    residual: see ``research/evidence/stat-page-gate-2026-09-01/`` and
    :func:`read_note_citations`'s own docstring for both.
    """

    path: Path
    #: The observed digest, which :meth:`from_file` has already proved equal to
    #: :data:`NOTES_SHA256`. Carried so an execution receipt records WHICH
    #: bytes answered, rather than that some file was read.
    sha256: str
    byte_length: int
    records: tuple[AuthorityNote, ...]

    @classmethod
    def from_file(cls, path: Path | str, *, oracle: UscSectionOracle | None = None) -> CfrAuthorityNotes:
        """Read and verify the cache. Refuses on digest, length or count drift.

        ``oracle`` is the section-existence oracle :func:`read_note_citations`
        gates its Statutes-at-Large-resumed citations on. Omitted, this
        method loads the default the notes cache's own repository carries
        (:func:`_default_oracle`) -- so the production builder, which calls
        this method with the bare path and not :meth:`from_repository`,
        still gets a gated read without having to be changed to ask for one.
        A caller that ALREADY holds an oracle should pass it: the auto-load
        is a fallback for a bare reader, not an invitation to build the same
        six tables twice in one process. A tree with no oracle directory
        degrades to withholding every gated citation; a tree whose oracle
        has DRIFTED refuses out loud rather than degrading.
        """

        path = Path(path)
        payload, digest = _verify(path)
        if oracle is None:
            oracle = _default_oracle(path)
        records = tuple(
            AuthorityNote(
                cfr_title=int(record["cfr_title"]),
                cfr_part=str(record["cfr_part"]),
                authority_note=record["authority_note"],
                source_note=record.get("source_note"),
                api_url=record["api_url"],
                fetched=record["fetched"],
                raw_sha256=record["raw_sha256"],
                raw_bytes=int(record["raw_bytes"]),
                raw_truncated_at_128k=bool(record["raw_truncated_at_128k"]),
                citations=read_note_citations(record["authority_note"], oracle=oracle),
                authority_level=str(record.get("authority_level", "part")),
                authority_scope=str(record.get("authority_scope", "part")),
            )
            for record in (json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip())
        )
        if len(records) != NOTES_EXPECTED_RECORDS:
            raise ValueError(f"expected {NOTES_EXPECTED_RECORDS} pinned authority notes, read {len(records)}")
        return cls(path=path, sha256=digest, byte_length=len(payload), records=records)

    @classmethod
    def from_repository(cls, root: Path | str) -> CfrAuthorityNotes:
        """Read the copy this repository carries.

        Delegates to :meth:`from_file`'s own oracle auto-detection --
        ``root`` and the path :func:`_default_oracle` would recover from the
        notes path it is given are the same directory either way.
        """

        return cls.from_file(Path(root) / CFR_AUTHORITY_NOTES_ARTIFACT)

    @cached_property
    def _by_part(self) -> Mapping[tuple[int, str], AuthorityNote]:
        return {(note.cfr_title, normalize_part(note.cfr_part) or note.cfr_part): note for note in self.records}

    @cached_property
    def _memo(self) -> dict[tuple[tuple[int, str], str, str], str]:
        """One verdict per (part, family, identity), computed once.

        The covered rows ask about 25,000-odd distinct citations, and a
        near-miss question walks every identity in the note. Without this the
        pass costs minutes on a 100 s build; with it, seconds. The memo is
        keyed by part, so widening the cache from 287 parts to 8,240 widens the
        key space rather than the work per question.
        """

        return {}

    def coverage(self) -> tuple[tuple[int, str], ...]:
        """Every ``(cfr_title, cfr_part)`` the cache holds, in citation order."""

        return tuple(sorted(self._by_part, key=lambda part: (part[0], _section_order(part[1]) or (0, part[1]))))

    def holds(self, cfr_title: object, cfr_part: object) -> bool:
        """Whether the cache carries this part's note."""

        return self.note(cfr_title, cfr_part) is not None

    def note(self, cfr_title: object, cfr_part: object) -> AuthorityNote | None:
        """The part's note, or ``None`` where the cache does not hold it."""

        part = normalize_part(cfr_part)
        if cfr_title is None or part is None:
            return None
        return self._by_part.get((int(cfr_title), part))

    def judge(self, citation: Citation, parts: Iterable[tuple[int, str]]) -> NoteVerdict | None:
        """The best verdict any of the rule's held parts gives, and which gave it.

        Precedence is ``present`` > ``near-miss`` > ``absent``: a rule amending
        four parts is authorised by all four notes together, so one note naming
        the citation settles it and the others cannot un-name it. Ties go to
        the first part in citation order, so the answer does not depend on the
        order the publisher listed the rule's parts in.

        ``None`` when none of ``parts`` is held -- there is nothing to judge
        against, which is not the same fact as ``absent``.
        """

        best: NoteVerdict | None = None
        for part in sorted(set(parts), key=lambda item: (item[0], _section_order(item[1]) or (0, item[1]))):
            note = self._by_part.get(part)
            if note is None:
                continue
            key = (part, citation.family, citation.identity)
            verdict = self._memo.get(key)
            if verdict is None:
                verdict = note.judge(citation)
                self._memo[key] = verdict
            if best is None or VERDICTS.index(verdict) < VERDICTS.index(best.verdict):
                best = NoteVerdict(verdict=verdict, cfr_title=part[0], cfr_part=part[1])
            if best.verdict == VERDICTS[0]:
                break
        return best

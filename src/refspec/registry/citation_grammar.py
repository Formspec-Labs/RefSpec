"""One home for CFR and legal-authority citation grammars.

Five implementations of this existed across the repositories: SpicySearch's
``identifiers.py`` (the origin), a port of it into ``spicy_regs/ontology/
citations.py`` (the most evolved — 24 compiled patterns, several bought with
evidence files), that repository's ``build_authority_edges`` consumer, a
filtering consumer's keep-logic, and an earlier version of this module written
without reading the other four. This version is the deliberate union: every
rule below that cites a source was carried over because it was *bought* —
with a bakeoff false positive, a benchmark miss, or a mis-minted URN — and
none of them was ours to rediscover.

**What this module refuses to do.** Nothing is repaired and nothing is
dropped. A citation whose title cannot exist is returned with a false verdict;
an authority string nothing here can read comes back as ``other``/``failed``
rather than vanishing. The consumer filtering for real citations and the
consumer studying publisher damage need the same rows.

Provenance of the load-bearing rules:

- Boundary guards (``_LEFT``/``_RIGHT``): SpicySearch — without them
  "040 CFR 060" matched at offset 1 and reported a fabricated "40 CFR 60".
- Dash normalization: SpicySearch/USLM readers — seven Unicode dash
  codepoints collapse to "-", one character for one character, so spans on
  the normalized text still index the original.
- Trailing-punctuation rule in the section capture: SpicySearch — a greedy
  capture read "49 CFR 900.42." as section "900.42." and the whole citation
  was then dropped rather than the period.
- The Title 3 compilation diversion: citations.py — "3 CFR, 1977 Comp.,
  p. 123" locates an Executive Order's printed page; there is no 3 CFR
  § 1977, and a CFR grammar that reads one fabricates a citation. The
  closed separator set inside it was bought when an enumerated set left
  "through" still minting ``urn:rkaf:us:cfr:3:1949``.
- The U.S.C. range ordering rule: citations.py — a hyphen means two things
  in the U.S. Code ("1395w-4" is one section's name; "7401-7671q" is a
  range), nothing in the characters distinguishes them, and the ordering
  does. Fail-closed: "1484-86" stays one opaque token because reading it
  either way would be an invention.
- The chapter grammar: citations.py — bought as the largest well-defined
  slice of the citation bakeoff's shared-miss cell (31 strings neither
  implementation detected).
- Capitalization as evidence: SpicySearch — bare "EO" must be uppercase and
  "Stat" capitalized, or prose mints citations ("Romeo" contains "eo").
- Zero-padded titles read by integer value: this module — the Unified
  Agenda's structured field zero-pads 95 titles ("07 CFR 1943" is USDA's
  title 7), and a [1-9] capture silently dropped all of them.
- Lettered CFR parts: this module — the OFR's own index lists 272 parts
  with a letter suffix among its 8,424, and "7 CFR 15" and "7 CFR 15a" are
  separate parts; every ancestor merged them.
"""

from __future__ import annotations

import re
from collections.abc import Container
from dataclasses import dataclass, replace

__all__ = [
    "ActRelativeCitation",
    "FederalRegisterCitation",
    "CFR_LETTERED_PART_SHARE",
    "CFR_TITLE_COUNT",
    "AuthorityCitation",
    "CfrCitation",
    "EoCompilationLocator",
    "parse_authority_citation",
    "parse_cfr_citations",
    "parse_eo_compilation_locators",
    "parse_federal_register_citations",
    "usc_title_is_possible",
    "EO_HIGHEST_KNOWN",
    "STAT_VOLUME_HIGHEST_KNOWN",
    "PL_FIRST_NUMBERED_CONGRESS",
    "CONGRESS_CURRENT",
    "USC_TITLE_COUNT",
    "USC_RESERVED_TITLES",
    "find_act_relative_citations",
    "normalize_popular_name",
]

#: The Code of Federal Regulations has 50 titles. Title 35 is Reserved TODAY
#: but was the Panama Canal title through the 2000 revision — the Canal Zone
#: was U.S.-controlled until the 1999 handover — so a citation to 35 CFR in a
#: 1990s document is real. The grammar judges citations, which have dates;
#: the subject-index module keeps its own present-day reserved set for
#: judging today's roster.
CFR_TITLE_COUNT = 50

#: The U.S. Code has 54 titles. Title 53 is reserved and — unlike CFR title
#: 35, which held the Panama Canal until 2000 — has NEVER held content, so a
#: citation to it is impossible in any year. Title 54 (National Park Service)
#: was enacted 2014-12-19.
USC_TITLE_COUNT = 54
USC_RESERVED_TITLES = frozenset({53})

#: Series bounds for damage detection, each a verified fact with a date. A
#: value beyond its series is damage IN DATA CAPTURED BEFORE the as-of date;
#: these are for builders judging pinned captures, not for the grammar to
#: hard-refuse (the next Congress will outrun them, the way the CFR's 2025
#: roster outran 1990s Panama citations).
EO_HIGHEST_KNOWN = 14_420  # as of 2026-08; the numbered series starts at 1
STAT_VOLUME_HIGHEST_KNOWN = 139  # volume 139 = 2025 session laws
PL_FIRST_NUMBERED_CONGRESS = 57  # numbered Public Laws begin in 1901
CONGRESS_CURRENT = 119  # as of 2026-08


def usc_title_is_possible(title: int | None) -> bool | None:
    """1-54, excluding never-enacted 53. None when there is no title to judge."""

    if title is None:
        return None
    return 1 <= title <= USC_TITLE_COUNT and title not in USC_RESERVED_TITLES

#: 272 of the 8,424 parts in the OFR's published subject index carry a letter
#: suffix. Recorded so the part capture below is not "simplified" back to
#: digits by someone who has not counted.
CFR_LETTERED_PART_SHARE = (272, 8_424)

#: Real CFR parts reach FIVE digits — 5 CFR 10001 and 10002 (National Council
#: on Disability) exist today — so five digits proves nothing either way:
#: "40 CFR 60758" is still fused-dot damage, but a length rule cannot tell it
#: from 10001. Only six digits and up is asserted implausible ("42 CFR
#: 412106"). The evidence-grade signal for five-digit parts is membership in
#: the OFR's own part index, which the Agenda tables carry as a column.
_MAX_PLAUSIBLE_PART_DIGITS = 5

# Boundary guards: no citation may start or end inside a longer token.
_LEFT = r"(?<![0-9A-Za-z])"
_RIGHT = r"(?![0-9A-Za-z])"

#: Every dash spelling (hyphen, non-breaking hyphen, figure dash, en dash, em
#: dash, horizontal bar, minus sign) collapses to "-" before matching — one
#: character for one character, so spans still index the original text.
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−", "-"))

# --------------------------------------------------------------------------- #
# CFR

#: A section's inner dots and hyphens belong to its name ("60.5-1"); a
#: trailing one is the sentence's punctuation.
_CFR_SECTION_CAPTURE = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"

#: A part number, optionally with the letter suffix the CFR actually uses.
#: The suffix is only part of the part when nothing alphanumeric follows it:
#: "17 CFR 15c3-3" is rule 15c3-3 under part 240, and reading "15c" invents a
#: part that does not exist.
_CFR_PART_CAPTURE = rf"\d+[A-Za-z]?{_RIGHT}"

# The title accepts leading zeros deliberately; the verdict falls on the
# integer (07 -> 7 possible, 00 -> 0 impossible). The offset-matching hazard
# the ancestors' [1-9] guarded against is carried by _LEFT alone.
_CFR_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?"
    r"\s*(?P<label>parts?|pt\.?|§{1,2}|sections?|secs?\.?)?\s*"
    rf"(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?",
    re.IGNORECASE,
)

#: "title 40, part 60" / "40 CFR part 60" — the spelling that names the part
#: with a keyword. Ported from citations.py with one tightening: the ancestor
#: made BOTH the word "title" and "CFR" optional, so bare "5, part 2" in prose
#: fabricated title 5 part 2. Here at least one of the two anchors must be
#: present — a number and the word "part" alone name nothing.
_CFR_TITLE_PART = re.compile(
    rf"{_LEFT}(?:"
    rf"title\s+(?P<title>\d+)\s*[,;:-]?\s*(?:C\.?\s*F\.?\s*R\.?\s*)?"
    rf"|(?P<title_cfr>\d+)\s*[,;:-]?\s*C\.?\s*F\.?\s*R\.?\s*"
    r")(?:parts?|pt\.?)\s+"
    rf"(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?",
    re.IGNORECASE,
)

#: One further list item after a citation: ", 61", ", and 63", "and 63".
#: The negative lookahead is citations.py's list-tail lesson applied here: a
#: number that LEADS ANOTHER CITATION is never a list member, so
#: "17 CFR 240, 15 U.S.C. 78c" does not fabricate a part 15.
_CFR_LIST_ITEM = re.compile(
    rf"\s*(?:,\s*(?:and\s+)?|and\s+)(?P<part>{_CFR_PART_CAPTURE})"
    rf"(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?"
    r"(?!\s*(?:U\.?\s*S\.?\s*C|C\.?\s*F\.?\s*R|Stat\b))",
    re.IGNORECASE,
)

_PLURAL_LABEL = re.compile(r"^(?:parts|pts\.?|§§|sections|secs\.?)$", re.IGNORECASE)

#: "3 CFR, 1977 Comp., p. 123" — a Title 3 *compilation* locator, the page an
#: Executive Order was printed on, not a CFR citation. Only title 3 compiles
#: presidential documents, so only title 3 is recognized. The separator set
#: between a volume's two years is closed, not enumerated: a dash, a slash,
#: "to", "through", "thru", "and" — none of it is ever a part number.
#: Enumerating instead left "through" still minting urn:rkaf:us:cfr:3:1949.
_EO_COMPILATION = re.compile(
    r"\b3\s*C\.?\s*F\.?\s*R\.?\s*,?\s*"
    r"(?P<start>(?:1[789]|20)\d{2})"
    r"(?:\s*(?:[-/]|to|thru|through|and)\s*(?P<end>(?:1[789]|20)\d{2}))?"
    r"\s*,?\s*Comp\.?"
    r"(?:\s*,?\s*(?:pp?\.?|pages?)\s*(?P<page>\d+))?",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# U.S. Code and the other authorities

# The code names itself three ways: abbreviated ("U.S.C."), written out
# ("49 U.S. Code 106"), and as the annotated edition ("50 U.S.C.A. 4701(a)").
# All three are the same code and read to the same title and section.
_USC_CODE_NAME = r"U\.?\s*S\.?\s*(?:Code\b|C\.?(?:\s*A\.?)?)"

_USC_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>[1-9]\d*)\s*{_USC_CODE_NAME}"
    r"(?:\s*(?:§{1,2}|sections?|secs?\.?))?\s*"
    r"(?P<section>\d+[A-Za-z]{0,3}(?:-\d+[A-Za-z]{0,3})?)"
    # A spelled range tail: "7401 to 7671q". The hyphenated spelling is
    # already inside ``section`` (a hyphen is also part of the section
    # grammar, so it has to be). Whether either spelling is really a range is
    # decided by the ordering rule, never by the separator's shape.
    r"(?:\s+(?:to|through)\s+(?P<range_end>\d+[A-Za-z]{0,3}))?",
    re.IGNORECASE,
)

#: "49 U.S.C. ch. 311" — the unit above a section, spelled every way the
#: corpus can ("ch.", "Ch", "ch.13" with no space, "chapter"). A chapter
#: number never contains a hyphen, so a dash after one is always a separator
#: — but the range tail still requires a number behind it, because
#: "22 USC Ch. 34- The Peace Corps Act" cites chapter 34 and the dash there
#: is punctuation before a title.
_USC_CHAPTER = re.compile(
    rf"{_LEFT}(?P<title>[1-9]\d*)\s*{_USC_CODE_NAME}"
    r"\s*(?:chapters?|chaps?\.?|chs?\.?)\s*"
    r"(?P<chapter>\d+[A-Za-z]?)\b"
    r"(?:(?:\s+(?:to|through)\s+|\s*-\s*)(?P<chapter_end>\d+[A-Za-z]?)\b)?",
    re.IGNORECASE,
)

#: A section list under one title: "42 U.S.C. 1395, 1396, 1397". The lookahead
#: stops the expansion at a number that leads another citation form, so
#: "5 U.S.C. 301, 117 Stat. 429" never lists section 117.
_USC_LIST_TAIL = re.compile(
    r"(?:,|\band\b|\bor\b)\s*(?P<section>\d+[A-Za-z]{0,3}(?:-\d+[A-Za-z]{0,3})?)\b"
    r"(?!\s*(?:U\.?\s*S\.?\s*C|C\.?\s*F\.?\s*R|Stat\b))",
    re.IGNORECASE,
)

#: "section 553 of title 5" — the spelling statutes themselves use, with the
#: plural-list variant ("sections 3501, 3502 and 3503 of title 44") from
#: SpicySearch, whose gap here was found by a search-quality benchmark. A bare
#: "section 553" with no "of title" tail stays undetected rather than guessed.
_USC_TITLE_FORM = re.compile(
    rf"{_LEFT}(?:§{{1,2}}|sections?|secs?\.?)\s*"
    r"(?P<first>\d+[A-Za-z]{0,3}(?:-\d+[A-Za-z]{0,3})?)"
    r"(?P<items>(?:\s*(?:,\s*(?:and\s+)?|\s+and\s+)\d+[A-Za-z]{0,3})*)"
    rf"\s+of\s+title\s+(?P<title>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)
_USC_TITLE_FORM_ITEM = re.compile(r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?P<section>\d+[A-Za-z]{0,3})")

#: "50 U.S.C. app. 2401" — a section of a title's APPENDIX, which is a real
#: place (the Export Administration Act lived in 50 U.S.C. app. for decades)
#: and not the same place as the title proper. 3,870 Agenda authorities cite
#: appendices; reading them as plain title-50 sections would merge two
#: different bodies of law, so the appendix is carried as its own flag.
_USC_APPENDIX = re.compile(
    rf"{_LEFT}(?P<title>[1-9]\d*)\s*{_USC_CODE_NAME}"
    r"\s*(?:§{1,2}\s*)?[Aa]pp(?:endix|x?\.?)?\s*"
    r"(?P<section>\d+[A-Za-z]{0,3}(?:-\d+[A-Za-z]{0,3})?)?",
)

#: "123 F 3d 1460", "141 F.3d 662", "550 U.S. 544", "128 S. Ct. 2131" — case
#: reporter citations. A different identifier family from everything above:
#: volume-reporter-page locates a decision, not an enactment. The reporter
#: token is the anchor and is matched from a closed set, because "F" and "S"
#: are letters prose uses freely.
_CASE_REPORTER = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s+"
    r"(?P<reporter>F\.?\s?(?:2d|3d|4th)|F\.?\s?Supp\.?\s?(?:2d|3d)?|U\.\s?S\.|S\.\s?Ct\.)"
    rf"\s+(?P<page>[1-9]\d{{0,4}}){_RIGHT}"
)

#: "Reorganization Plan No. 3 of 1970" — a real authority type: plans made
#: under the Reorganization Acts carry the force of law and the Agenda cites
#: ~1,300 of them.
_REORGANIZATION_PLAN = re.compile(
    r"[Rr]eorg(?:anization)?\.?\s*Plan\s*(?:No\.?\s*)?(?P<number>\d+)\s*of\s*(?P<year>(?:1[89]|20)\d{2})"
)

#: A code that names itself instead of its title number. The Internal Revenue
#: Code IS title 26, so "I.R.C. 337(d)" and "26 U.S.C. 337(d)" must reach one
#: identifier. The title comes from the expression that recognized the code —
#: never from a shared "guess the code" rule — and the three-letter
#: abbreviation publishes nothing without a section behind it, because naming
#: a code is not citing one.
_INTERNAL_REVENUE_CODE = re.compile(
    r"\bI\.?\s*R\.?\s*C\.?(?:\s*(?:§{1,2}|sections?|secs?\.?))?\s*"
    r"(?P<section>\d+[A-Za-z]{0,3}(?:-\d+[A-Za-z]{0,3})?)",
    re.IGNORECASE,
)
_NAMED_CODE_USC_TITLE: dict[re.Pattern[str], int] = {_INTERNAL_REVENUE_CODE: 26}

# "Public Law", "Pub. L.", "Pub. Law", "P.L." — one law, four spellings.
_PUBLIC_LAW = re.compile(
    rf"{_LEFT}(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?"
    rf"(?P<congress>[1-9]\d*)\s*-\s*(?P<number>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)

# Capitalization is load-bearing where an abbreviation is also inside English
# words: the spelled forms may relax case, but bare "EO"/"E.O." must be
# uppercase or "Romeo 12345" mints an order. The spelled forms accept any
# order number (early orders are two digits); the bare form demands the
# modern 4-5 digit shape, because without a label the number is the only
# other evidence.
_EXECUTIVE_ORDER_SPELLED = re.compile(
    rf"{_LEFT}(?:Executive\s+Orders?|Exec\.?\s*(?:Orders?|Ord\.?))\s*(?:Nos?\.?\s*)?(?P<number>[1-9]\d*){_RIGHT}",
    re.IGNORECASE,
)
#: "Executive Orders 13990 and 14008" — the plural licenses a number list,
#: the same rule the CFR and U.S.C. lists use.
_EXECUTIVE_ORDER_LIST_TAIL = re.compile(r"\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?P<number>1?\d{4,5})\b")
_EXECUTIVE_ORDER_ABBREVIATED = re.compile(
    rf"{_LEFT}(?:EO|E\.\s*O\.?)\s*(?:No\.?\s*)?(?P<number>\d{{4,5}}){_RIGHT}"
)

#: A Federal Register citation: "89 FR 91529". Uppercase "FR" only, for the
#: same reason bare "EO" is — lowercase "fr" is ordinary prose. Volume bounded
#: to the real series (1..999); the page to the Register's actual widths.
#: The separators tolerate the publisher's own damage — "78FR 63152",
#: "82-FR 22190" and "83 FR32768" all occur in the Unified Agenda's timetable
#: field — but only one dash or nothing: "76 R 11462" (a lost F) and a CFR
#: citation sitting in the FR column stay unread rather than guessed.
_FR_CITATION_FORM = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,2}})\s*-?\s*FR\s*-?\s*(?P<page>\d{{1,6}}){_RIGHT}"
)

#: "Stat" must be capitalized for the same reason, and the digit ranges are
#: bounded to the real series (volume 1..~1400, page 1..99999).
_STATUTE_AT_LARGE = re.compile(
    rf"{_LEFT}(?P<volume>[1-9]\d{{0,3}})\s+Stat\.?\s+(?P<page>[1-9]\d{{0,4}}){_RIGHT}"
)

#: What may follow a citation without making it partial: "et seq.",
#: "as amended", "and following", "ff.", and punctuation.
_IGNORABLE_TAIL = re.compile(
    r"^[\s,;:.]*(?:et\s+seq\.?|as\s+amended|and\s+following|ff\.?)?[\s,;:.]*$",
    re.IGNORECASE,
)

_USC_SECTION_ATOM = re.compile(r"(?P<number>\d+)(?P<suffix>[a-z]*)")

#: Values that state nothing: stringified nulls plus the Unified Agenda's own
#: placeholders ("Not Yet Determined" 5,338 times, "..." 6,873 times in the
#: authority field alone; "00 CFR NYD" in the CFR field). A consumer must be
#: able to tell "the publisher said nothing" from "the publisher said
#: something unreadable" — the same distinction the docket sentinels carry.
UNSTATED_SENTINELS = frozenset({
    "", "none", "nan", "null", "n/a", "na", "...", "not yet determined",
    "undetermined", "not determined", "nyd", "tbd", "to be determined",
})


def states_nothing(text: object) -> bool:
    """Whether a field value is a placeholder rather than a statement."""

    return str(text or "").strip().casefold() in UNSTATED_SENTINELS


# --------------------------------------------------------------------------- #
# Result types


@dataclass(frozen=True)
class CfrCitation:
    """One CFR reference, split and judged but never discarded."""

    cfr_title: int
    cfr_part: str | None
    cfr_section: str | None = None
    #: 1-50 and not Reserved. False keeps the row inspectable rather than
    #: dropping what a data-quality question needs.
    title_is_possible: bool = True
    #: False for a part whose digit run is longer than any real part — the
    #: publisher's lost-separator damage.
    part_is_plausible: bool | None = None


@dataclass(frozen=True)
class AuthorityCitation:
    """One legal authority, with a status instead of silence.

    ``parse_status`` is "ok" when the citation covers its whole string apart
    from an ignorable tail ("et seq.", "as amended"), "partial" when prose or
    a declined range tail remains uncovered or the string carries several
    citations, and "failed" on the one ``other`` row an unreadable string
    still produces — nothing vanishes.
    """

    authority_type: str
    parse_status: str = "ok"
    usc_title: int | None = None
    usc_section: str | None = None
    usc_section_end: str | None = None
    usc_chapter: str | None = None
    usc_chapter_end: str | None = None
    #: True when the section lives in the title's appendix, a different place
    #: from the title proper.
    usc_appendix: bool = False
    cfr_title: int | None = None
    cfr_part: str | None = None
    reorganization_plan: str | None = None
    #: An act-relative authority ("Clean Air Act sec 112"): the OLRC popular
    #: name key, with the act's own section number when one was cited.
    #: Resolution to a U.S.C. identifier is act_resolution's job, not this
    #: type's — it carries what the text said and nothing it did not.
    act_key: str | None = None
    act_section: str | None = None
    #: A case-reporter citation: "123 F 3d 1460". Locates a decision.
    case_reporter: str | None = None
    case_volume: int | None = None
    case_page: int | None = None
    public_law: str | None = None
    executive_order: str | None = None
    statute_volume: int | None = None
    statute_page: int | None = None


@dataclass(frozen=True)
class EoCompilationLocator:
    """A Title 3 compilation locator: the page an EO was printed on.

    Deliberately carries no identifier — the volume and page locate a printed
    order, and inventing either a CFR citation or an order number from them
    would be one of the two wrong answers this type exists to refuse.
    """

    compilation_start: str
    compilation_end: str | None
    page: str | None


# --------------------------------------------------------------------------- #
# Helpers


def _title_is_possible(title: int) -> bool:
    # 1-50, title 35 included: Reserved today, Panama Canal until 2000, and a
    # grammar that judged by today's roster called 115 real 1990s citations
    # impossible before this was web-verified.
    return 1 <= title <= CFR_TITLE_COUNT


def _part_is_plausible(part: str | None) -> bool | None:
    if part is None:
        return None
    return len([c for c in part if c.isdigit()]) <= _MAX_PLAUSIBLE_PART_DIGITS


def _canonical_part(part: str | None) -> str | None:
    """Strip leading zeros: the part is a JOIN KEY, and "0718" must meet "718"."""

    if part is None:
        return None
    stripped = part.lstrip("0")
    return stripped if stripped else "0"


def _normalize_dashes(text: str) -> str:
    return text.translate(_DASHES)


def _usc_section(value: str | None) -> str | None:
    """Lowercase a section token and drop subsection detail: "337(d)" -> "337"."""

    if value is None:
        return None
    text = re.sub(r"\([^)]*\)", "", value.strip().lower())
    return text or None


def _usc_section_key(section: str | None) -> tuple[int, str] | None:
    """Order a U.S.C. section by numeric stem, then letter suffix.

    ``7671`` < ``7671a`` < ``7671q`` < ``7672``. None for anything that is not
    a single well-formed token, so a caller can never compare two values it
    does not understand.
    """

    if not section:
        return None
    match = _USC_SECTION_ATOM.fullmatch(section)
    return (int(match["number"]), match["suffix"]) if match else None


def _usc_section_range(section: str | None, range_end: str | None = None) -> tuple[str | None, str | None]:
    """Split a section token into ``(section, range_end)`` by the ordering rule.

    A hyphen means two things in the U.S. Code: in "1395w-4" and "300j-9" it
    is part of one section's name; in "7401-7671q" it separates a range's
    endpoints. Nothing in the characters distinguishes them, so the ordering
    does: a range is a pair whose second endpoint sorts strictly after its
    first, and a compound name never satisfies that because its suffix is a
    small ordinal. Fail-closed: an unordered or unparsable pair — including
    the abbreviated "1484-86" — keeps the original token whole, because
    reading it either way would be an invention.
    """

    if not section:
        return (section, None)
    if range_end is not None:
        start, end = section, range_end
    elif section.count("-") == 1:
        start, end = section.split("-")
    else:
        return (section, None)
    low, high = _usc_section_key(start), _usc_section_key(end)
    if low is None or high is None or low >= high:
        return (section, None)
    return (start, end)


def _status_for_span(text: str, start: int, end: int) -> str:
    """Status for a citation covering ``text[start:end]`` and nothing else.

    The span is passed rather than taken from a match, because a U.S.C. match
    may consume a range tail the ordering rule then declines — the declined
    characters are not covered and must still count against "ok".
    """

    remainder = f"{text[:start]} {text[end:]}"
    return "ok" if _IGNORABLE_TAIL.fullmatch(remainder) else "partial"


# --------------------------------------------------------------------------- #
# CFR parsing


def parse_eo_compilation_locators(text: str) -> tuple[EoCompilationLocator, ...]:
    """Read every Title 3 compilation locator, identifying nothing."""

    normalized = _normalize_dashes(text)
    return tuple(
        EoCompilationLocator(
            compilation_start=match.group("start"),
            compilation_end=match.group("end"),
            page=match.group("page"),
        )
        for match in _EO_COMPILATION.finditer(normalized)
    )


def _excise_compilations(text: str) -> str:
    """Blank out compilation locators so the CFR grammar cannot read them.

    "3 CFR, 1977 Comp., p. 123" is not a CFR citation, and left in place it
    parses as title 3, part 1977 — plausible on every axis and entirely
    fabricated. Spans are replaced with spaces so every other citation keeps
    its offsets.
    """

    def _blank(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    return _EO_COMPILATION.sub(_blank, text)


def parse_cfr_citations(text: str, *, list_expansion: str = "plural-label") -> tuple[CfrCitation, ...]:
    """Read every CFR citation in one string.

    ``list_expansion`` decides when ", 61, and 63" continues a citation:

    ``"plural-label"`` (default)
        Only a plural label — "parts", "§§", "sections" — licenses expansion.
        Correct for PROSE, where a comma after "part 37" may belong to the
        sentence rather than the citation.

    ``"always"``
        Any comma-separated run continues the citation. Correct for a
        STRUCTURED field, where the whole value is the citation: in the
        Unified Agenda's CFR field, 953 references list parts with no label
        at all against 43 with a plural one, so the prose rule would drop
        the dominant shape.

    Title 3 compilation locators are excised before matching (see
    :func:`parse_eo_compilation_locators` to read them), and either policy
    stops a list at a number that leads another citation form.
    """

    if list_expansion not in {"plural-label", "always"}:
        raise ValueError(f"unknown list expansion policy: {list_expansion!r}")

    normalized = _excise_compilations(_normalize_dashes(text))
    citations: list[CfrCitation] = []
    spans: list[tuple[int, int]] = []

    def _collect_title_part(match: re.Match[str]) -> None:
        title = int(match.group("title") or match.group("title_cfr"))
        part = _canonical_part(match.group("part"))
        citations.append(
            CfrCitation(
                cfr_title=title,
                cfr_part=part,
                cfr_section=match.group("section"),
                title_is_possible=_title_is_possible(title),
                part_is_plausible=_part_is_plausible(part),
            )
        )
        spans.append(match.span())

    def _collect(match: re.Match[str], *, label: str | None) -> None:
        title = int(match.group("title"))
        possible = _title_is_possible(title)
        part = _canonical_part(match.group("part"))
        citations.append(
            CfrCitation(
                cfr_title=title,
                cfr_part=part,
                cfr_section=match.group("section"),
                title_is_possible=possible,
                part_is_plausible=_part_is_plausible(part),
            )
        )
        spans.append(match.span())
        if list_expansion != "always" and not (label and _PLURAL_LABEL.match(label)):
            return
        position = match.end()
        while (item := _CFR_LIST_ITEM.match(normalized, position)) is not None:
            item_part = _canonical_part(item.group("part"))
            citations.append(
                CfrCitation(
                    cfr_title=title,
                    cfr_part=item_part,
                    cfr_section=item.group("section"),
                    title_is_possible=possible,
                    part_is_plausible=_part_is_plausible(item_part),
                )
            )
            spans.append(item.span())
            position = item.end()

    for match in _CFR_STANDARD.finditer(normalized):
        _collect(match, label=match.group("label"))
    # The keyword spelling ("title 40, part 60") only where the standard
    # grammar read nothing at that position — the two overlap on "40 CFR
    # part 60" and one citation must not become two.
    for match in _CFR_TITLE_PART.finditer(normalized):
        if any(start < match.end() and match.start() < end for start, end in spans):
            continue
        _collect_title_part(match)

    if citations:
        return tuple(citations)
    bare = re.match(rf"{_LEFT}(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?", normalized, re.IGNORECASE)
    if bare is None:
        return ()
    # A title with no readable part still tells a consumer the title, which
    # is how "35 CFR ch. II" stays visible as a Reserved-title citation.
    title = int(bare.group("title"))
    return (CfrCitation(cfr_title=title, cfr_part=None, title_is_possible=_title_is_possible(title)),)


# --------------------------------------------------------------------------- #
# Authority parsing


def parse_authority_citation(text: str) -> tuple[AuthorityCitation, ...]:
    """Read every legal authority in one string, with a status instead of silence.

    Every input yields at least one result: unreadable text is retained as an
    ``other``/``failed`` row, and a citation embedded in extra prose is
    ``partial`` rather than discarded. The Unified Agenda's
    ``LEGAL_AUTHORITY_LIST`` carries 755,727 of these.
    """

    normalized = _normalize_dashes(text.strip())
    if states_nothing(normalized):
        # A placeholder is not a failed parse: the publisher said nothing.
        return (AuthorityCitation(authority_type="unstated", parse_status="failed"),)

    citations: list[AuthorityCitation] = []

    def _add(citation: AuthorityCitation) -> None:
        if citation not in citations:
            citations.append(citation)

    # The appendix form runs FIRST and its span suppresses the standard form:
    # "50 U.S.C. app. 2401" must not also read as plain 50 U.S.C. section
    # 2401, which is a different place.
    appendix_spans: list[tuple[int, int]] = []
    for match in _USC_APPENDIX.finditer(normalized):
        appendix_spans.append(match.span())
        section, section_end = _usc_section_range(_usc_section(match.group("section")))
        _add(
            AuthorityCitation(
                authority_type="usc",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                usc_title=int(match.group("title")),
                usc_section=section,
                usc_section_end=section_end,
                usc_appendix=True,
            )
        )

    for pattern in (_USC_STANDARD, _INTERNAL_REVENUE_CODE):
        named_title = _NAMED_CODE_USC_TITLE.get(pattern)
        for match in pattern.finditer(normalized):
            if any(start <= match.start() and match.end() <= end for start, end in appendix_spans):
                continue
            section, section_end = _usc_section_range(
                _usc_section(match.group("section")),
                _usc_section(match.groupdict().get("range_end")),
            )
            # A range tail the ordering rule declined stays uncovered text, so
            # "12 U.S.C. 1831p-1" is a partial parse of 1831p rather than an
            # "ok" one that quietly dropped the suffix.
            covered_end = (
                match.end("section")
                if match.groupdict().get("range_end") is not None and section_end is None
                else match.end()
            )
            title = match.groupdict().get("title")
            _add(
                AuthorityCitation(
                    authority_type="usc",
                    parse_status=_status_for_span(normalized, match.start(), covered_end),
                    usc_title=int(title) if title else named_title,
                    usc_section=section,
                    usc_section_end=section_end,
                )
            )

    for match in _USC_TITLE_FORM.finditer(normalized):
        title = int(match.group("title"))
        status = _status_for_span(normalized, match.start(), match.end())
        first, first_end = _usc_section_range(_usc_section(match.group("first")))
        _add(
            AuthorityCitation(
                authority_type="usc",
                parse_status=status,
                usc_title=title,
                usc_section=first,
                usc_section_end=first_end,
            )
        )
        for item in _USC_TITLE_FORM_ITEM.finditer(match.group("items") or ""):
            _add(
                AuthorityCitation(
                    authority_type="usc",
                    parse_status="partial",
                    usc_title=title,
                    usc_section=_usc_section(item.group("section")),
                )
            )

    for match in _USC_CHAPTER.finditer(normalized):
        # A deviation from citations.py, which kept chapters out of the
        # authority parse entirely: the Agenda's authority field does cite
        # chapters, and a typed row beats an "other/failed" one.
        _add(
            AuthorityCitation(
                authority_type="usc_chapter",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                usc_title=int(match.group("title")),
                usc_chapter=match.group("chapter").lower(),
                usc_chapter_end=(match.group("chapter_end") or "").lower() or None,
            )
        )

    for match in _PUBLIC_LAW.finditer(normalized):
        _add(
            AuthorityCitation(
                authority_type="public_law",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                public_law=f"{int(match.group('congress'))}-{int(match.group('number'))}",
            )
        )
    for match in _STATUTE_AT_LARGE.finditer(normalized):
        _add(
            AuthorityCitation(
                authority_type="statute_at_large",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                statute_volume=int(match.group("volume")),
                statute_page=int(match.group("page")),
            )
        )
    for pattern in (_EXECUTIVE_ORDER_SPELLED, _EXECUTIVE_ORDER_ABBREVIATED):
        for match in pattern.finditer(normalized):
            _add(
                AuthorityCitation(
                    authority_type="executive_order",
                    parse_status=_status_for_span(normalized, match.start(), match.end()),
                    executive_order=str(int(match.group("number"))),
                )
            )
            # A plural label licenses a number list: "Executive Orders 13990
            # and 14008" names two orders, and reading one is dropping one.
            position = match.end()
            while (item := _EXECUTIVE_ORDER_LIST_TAIL.match(normalized, position)) is not None:
                _add(
                    AuthorityCitation(
                        authority_type="executive_order",
                        parse_status="partial",
                        executive_order=str(int(item.group("number"))),
                    )
                )
                position = item.end()

    for match in _CASE_REPORTER.finditer(normalized):
        reporter = re.sub(r"\s+", " ", match.group("reporter").replace(" ", " ")).strip()
        _add(
            AuthorityCitation(
                authority_type="case_citation",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                case_reporter=reporter,
                case_volume=int(match.group("volume")),
                case_page=int(match.group("page")),
            )
        )

    for match in _REORGANIZATION_PLAN.finditer(normalized):
        _add(
            AuthorityCitation(
                authority_type="reorganization_plan",
                parse_status=_status_for_span(normalized, match.start(), match.end()),
                reorganization_plan=f"{int(match.group('number'))}-of-{match.group('year')}",
            )
        )

    # A CFR citation in the authority field is a real citation in the wrong
    # column — 7,092 of them, "delegation of authority at 49 CFR 1.95" the
    # commonest. Typed as what it is rather than left "failed"; the field's
    # semantics stay the consumer's question.
    for cfr in parse_cfr_citations(normalized):
        if cfr.cfr_part is None or not cfr.title_is_possible:
            continue
        _add(
            AuthorityCitation(
                authority_type="cfr",
                parse_status="partial",
                cfr_title=cfr.cfr_title,
                cfr_part=cfr.cfr_part,
            )
        )

    # A section list is never covered by a single citation, so every listed
    # member is partial. A listed member may itself be a range
    # ("42 U.S.C. 7401, 7671a-7671q"), split by the same ordering rule.
    usc_matches = list(_USC_STANDARD.finditer(normalized))
    for index, match in enumerate(usc_matches):
        stop = usc_matches[index + 1].start() if index + 1 < len(usc_matches) else len(normalized)
        for tail in _USC_LIST_TAIL.finditer(normalized[match.end() : stop]):
            section, section_end = _usc_section_range(_usc_section(tail.group("section")))
            if section is not None:
                _add(
                    AuthorityCitation(
                        authority_type="usc",
                        parse_status="partial",
                        usc_title=int(match.group("title")),
                        usc_section=section,
                        usc_section_end=section_end,
                    )
                )

    if not citations:
        return (AuthorityCitation(authority_type="other", parse_status="failed"),)
    if len(citations) > 1:
        # Several citations can each cover the whole string only vacuously;
        # one string, several authorities means none of them is the whole.
        citations = [replace(item, parse_status="partial") for item in citations]
    return tuple(citations)


# --------------------------------------------------------------------------- #
# Act-relative citations — the grammar half; resolution lives in
# refspec.registry.act_resolution over the pinned OLRC artifacts.

#: "sec. 111", "section 111", "§ 111" — the marker an act-relative citation
#: hangs its section on.
_ACT_SECTION = re.compile(r"(?:sec(?:tion)?s?\.?|§{1,2})\s*(?P<section>\d+[A-Za-z]?)", re.IGNORECASE)
_CITED_DIVISION = re.compile(r"\bdiv(?:ision)?\.?\s+(?P<division>[A-Z]{1,3})\b")
#: The inverted spelling: "sec. 3505 of the Modernization of Cosmetics ... Act".
_ACT_SECTION_OF_THE = re.compile(r"\A\s*of\s+(?:the\s+)?", re.IGNORECASE)
#: No popular name in the Popular Name Tool is longer than this many words;
#: bounding the backward scan keeps recognition linear in the text.
_MAX_ACT_NAME_WORDS = 24
#: Punctuation a name may pick up from the sentence around it.
_NAME_EDGE = re.compile(r"^[\s(\"'“”]+|[\s,;:.)\"'“”]+$")
_CURLY_APOSTROPHE = re.compile(r"[’‘`]")


def normalize_popular_name(name: object) -> str:
    """The key a popular name joins on.

    Case, whitespace, sentence punctuation and the difference between a curly
    and a straight apostrophe are all spelling, not identity: the Popular Name
    Tool writes "Workers’ Compensation Act" and prose writes "Workers'
    Compensation Act", and they are one act. Internal commas are kept, because
    "Federal Food, Drug, and Cosmetic Act" is how that act is named.
    """

    text = _NAME_EDGE.sub("", str(name or ""))
    text = _CURLY_APOSTROPHE.sub("'", _normalize_dashes(text))
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass(frozen=True)
class ActRelativeCitation:
    """A provision cited through the act that created it.

    "Clean Air Act section 111" identifies a real provision but names no code,
    title or section number — it resolves only through the OLRC's tables, so
    this type carries what the text said and nothing it did not.
    """

    act_name: str
    act_key: str
    section: str
    #: The division the citation itself names, when it names one. ``None``
    #: means the text stated none — never that it stated the whole law.
    division: str | None = None


def _longest_name_before(before: str, act_names: Container[str]) -> str | None:
    words = before.split()
    for length in range(min(_MAX_ACT_NAME_WORDS, len(words)), 0, -1):
        candidate = " ".join(words[-length:])
        if normalize_popular_name(candidate) in act_names:
            return _NAME_EDGE.sub("", candidate)
    return None


def _longest_name_after(after: str, act_names: Container[str]) -> str | None:
    opening = _ACT_SECTION_OF_THE.match(after)
    if opening is None:
        return None
    words = after[opening.end() :].split()
    for length in range(min(_MAX_ACT_NAME_WORDS, len(words)), 0, -1):
        candidate = " ".join(words[:length])
        if normalize_popular_name(candidate) in act_names:
            return _NAME_EDGE.sub("", candidate)
    return None


def find_act_relative_citations(text: object, *, act_names: Container[str]) -> tuple[ActRelativeCitation, ...]:
    """Find act-relative citations whose act ``act_names`` knows.

    **The index is the grammar.** ``act_names`` holds normalized popular names
    — in production, the 13,626 the OLRC publishes — and a span is an act name
    only if the index says so. The alternative, recognizing a shape
    (capitalized words ending in "Act"), was measured against 4,777 sealed
    authority strings and matched "U.S.C." 108 times.

    Longest match wins, because one popular name may end with another: the
    Clean Air Act Amendments of 1977 are not the Clean Air Act. An act the
    index does not name is not read — the corpus writes "INA sec. 103(a)(1)",
    and inferring which act that abbreviates is precisely the guess the
    identity fence exists to stop.
    """

    document = "" if text is None else str(text)
    found: list[ActRelativeCitation] = []
    for marker in _ACT_SECTION.finditer(document):
        section = _usc_section(marker.group("section"))
        named = _longest_name_before(document[: marker.start()], act_names) or _longest_name_after(
            document[marker.end() :], act_names
        )
        if section is None or named is None:
            continue
        # A division stated anywhere across the citation's own span belongs to
        # it; the window is the span, not the string, so a second citation's
        # division is never borrowed.
        window = document[max(0, marker.start() - len(named) - 40) : marker.end() + 40]
        stated_division = _CITED_DIVISION.search(window)
        citation = ActRelativeCitation(
            act_name=named,
            act_key=normalize_popular_name(named),
            section=section,
            division=stated_division.group("division") if stated_division else None,
        )
        if citation not in found:
            found.append(citation)
    return tuple(found)


@dataclass(frozen=True)
class FederalRegisterCitation:
    """One "VV FR PPPPP" citation: a volume and starting page."""

    volume: int
    page: int


def parse_federal_register_citations(text: str) -> tuple[FederalRegisterCitation, ...]:
    """Every Federal Register citation in one string, in order.

    The Unified Agenda's timetable field writes these as the whole value
    ("89 FR 91529"); prose writes them inline. Uppercase "FR" is required —
    lowercase is ordinary prose, the same capitalization-as-evidence rule the
    bare "EO" and "Stat" forms carry.
    """

    normalized = _normalize_dashes(text)
    return tuple(
        # The page reads through leading zeros ("62 FR 04670" occurs in the
        # Agenda's own field) by integer value — the third appearance of the
        # zero-padding lesson today. Page 0 does not exist and stays unread.
        FederalRegisterCitation(volume=int(m.group("volume")), page=int(m.group("page")))
        for m in _FR_CITATION_FORM.finditer(normalized)
        if int(m.group("page")) > 0
    )

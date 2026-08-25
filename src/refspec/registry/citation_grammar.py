"""One home for CFR and legal-authority citation grammars.

Four implementations of this existed before this module: SpicySearch's
``identifiers.py``, a port of it into another repository's ``citations.py``, a
consumer's own keep-logic written to filter a table, and a fourth written here
for the Unified Agenda Parquet capture. Each was partial in a different way, and
today two sessions independently hit the same publisher damage and wrote two
different partial fixes for it.

RefSpec is the only one of these packages every other can depend on, so the
grammar lives here. The design is SpicySearch's -- boundary guards, a captured
label, plural-licenses-expansion -- carried over deliberately rather than
reinvented, because each of those rules was bought with an evidence file.

**What the port fixes rather than inherits.** Both prior grammars capture a part
as ``(?P<part>\\d+)``, so ``7 CFR 15a`` reads as part 15. The OFR's own subject
index lists **272 parts with a letter suffix** among its 8,424, and both
``7 CFR 15`` and ``7 CFR 15a`` appear there as separate parts, as do
``42 CFR 59`` and ``42 CFR 59a``. Merging them is not a rounding error; it
silently unions two distinct bodies of regulation. The part capture here admits
the suffix, and :data:`CFR_LETTERED_PART_SHARE` records how much of the CFR that
covers.

**Nothing is repaired and nothing is refused.** A citation whose title cannot
exist is returned with the title it names and a false verdict, because a
consumer studying publisher data quality needs the row the filtering consumer
discards. That is the one place this grammar deliberately differs from both
ancestors, which drop an impossible title on the floor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "CFR_LETTERED_PART_SHARE",
    "CFR_TITLE_COUNT",
    "AuthorityCitation",
    "CfrCitation",
    "parse_authority_citation",
    "parse_cfr_citations",
]

#: The Code of Federal Regulations has 50 titles. Title 35 is Reserved.
CFR_TITLE_COUNT = 50

#: 272 of the 8,424 parts in the OFR's published subject index carry a letter
#: suffix. Recorded so the part capture below is not "simplified" back to
#: digits by someone who has not counted.
CFR_LETTERED_PART_SHARE = (272, 8_424)

#: The largest real CFR part is four digits (48 CFR 9904). A longer digit run is
#: the publisher's fused-dot damage: "40 CFR 60758" is 40 CFR 60.758 with the
#: separator lost.
_MAX_PLAUSIBLE_PART_DIGITS = 4

# Boundary guards. Without them "040 CFR 060" matches at offset 1 and reports
# "40 CFR 60" -- SpicySearch identifiers.py bought this rule with a false
# positive, and it is kept for the same reason.
_LEFT = r"(?<![0-9A-Za-z])"
_RIGHT = r"(?![0-9A-Za-z])"

#: A section's inner dots and hyphens belong to its name ("60.5-1"); a trailing
#: one is the sentence's punctuation. A greedy capture read "49 CFR 900.42." as
#: section "900.42." and the whole citation was then dropped rather than the
#: period.
_CFR_SECTION_CAPTURE = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"

#: A part number, optionally with the letter suffix the CFR actually uses.
#: The suffix is only part of the part when nothing alphanumeric follows it:
#: "17 CFR 15c3-3" is rule 15c3-3 under part 240, and reading "15c" invents a
#: part that does not exist.
_CFR_PART_CAPTURE = rf"\d+[A-Za-z]?{_RIGHT}"

_CFR_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>[1-9]\d*)\s*C\.?\s*F\.?\s*R\.?"
    r"\s*(?P<label>parts?|pt\.?|§{1,2}|sections?|secs?\.?)?\s*"
    rf"(?P<part>{_CFR_PART_CAPTURE})(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?",
    re.IGNORECASE,
)

#: One further list item after a citation whose label was PLURAL: ", 61",
#: ", and 63", "and 63". A singular label never licenses expansion, which is
#: what stops "part 37" from swallowing a following unrelated number.
_CFR_LIST_ITEM = re.compile(
    rf"\s*(?:,\s*(?:and\s+)?|and\s+)(?P<part>{_CFR_PART_CAPTURE})"
    rf"(?:\.(?P<section>{_CFR_SECTION_CAPTURE}))?",
    re.IGNORECASE,
)

_PLURAL_LABEL = re.compile(r"^(?:parts|pts\.?|§§|sections|secs\.?)$", re.IGNORECASE)

_USC_STANDARD = re.compile(
    rf"{_LEFT}(?P<title>[1-9]\d*)\s*U\.?\s*S\.?\s*C\.?"
    r"(?:\s*(?:§{1,2}|sections?|secs?\.?))?\s*"
    r"(?P<section>\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)",
    re.IGNORECASE,
)
_PUBLIC_LAW = re.compile(r"(?:Pub(?:lic)?\.?\s*L(?:aw)?\.?|P\.?\s*L\.?)\s*(?P<number>\d+-\d+)", re.IGNORECASE)
_EXECUTIVE_ORDER = re.compile(r"(?:E\.?\s*O\.?|Executive\s+Order)\s*(?:No\.?\s*)?(?P<number>\d{4,5})", re.IGNORECASE)
_STATUTE_AT_LARGE = re.compile(rf"{_LEFT}(?P<volume>\d+)\s*Stat\.?\s*(?P<page>\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class CfrCitation:
    """One CFR reference, split and judged but never discarded."""

    cfr_title: int
    cfr_part: str | None
    cfr_section: str | None = None
    #: 1-50 and not Reserved. False keeps the row inspectable rather than
    #: dropping what a data-quality question needs.
    title_is_possible: bool = True
    #: False for a part whose digit run is longer than any real part, which is
    #: the publisher's lost-separator damage.
    part_is_plausible: bool | None = None


@dataclass(frozen=True)
class AuthorityCitation:
    """One legal authority: a statute, public law, executive order or Stat. cite."""

    authority_type: str
    usc_title: int | None = None
    usc_section: str | None = None
    public_law: str | None = None
    executive_order: str | None = None
    statute_volume: int | None = None
    statute_page: int | None = None


def _title_is_possible(title: int) -> bool:
    # 35 is Reserved: a real number naming nothing.
    return 1 <= title <= CFR_TITLE_COUNT and title != 35


def _part_is_plausible(part: str | None) -> bool | None:
    if part is None:
        return None
    return len([c for c in part if c.isdigit()]) <= _MAX_PLAUSIBLE_PART_DIGITS


def parse_cfr_citations(text: str, *, list_expansion: str = "plural-label") -> tuple[CfrCitation, ...]:
    """Read every CFR citation in one string.

    ``list_expansion`` decides when ", 61, and 63" continues a citation, and
    the right answer depends on where the text came from:

    ``"plural-label"`` (default)
        Only a plural label -- "parts", "§§", "sections" -- licenses expansion.
        This is SpicySearch's rule and it is correct for PROSE, where a comma
        after "part 37" may belong to the sentence rather than the citation.

    ``"always"``
        Any comma-separated run continues the citation. Correct for a
        STRUCTURED field, where the whole value is the citation and there is no
        sentence for a comma to belong to. In the Unified Agenda's own
        ``CFR_LIST``, 953 references list parts with no label at all
        ("40 CFR 60, 61, 63") against 43 with a plural label and 7 with a
        singular one -- so the prose rule would drop the dominant shape.

    Returns an empty tuple when the string carries no citation at all -- about
    5% of that field, which holds ``(app B)``, ``(new)`` and bare ``...``.
    Those are not failures to repair.
    """

    if list_expansion not in {"plural-label", "always"}:
        raise ValueError(f"unknown list expansion policy: {list_expansion!r}")

    citations: list[CfrCitation] = []
    for match in _CFR_STANDARD.finditer(text):
        title = int(match.group("title"))
        possible = _title_is_possible(title)
        part = match.group("part")
        citations.append(
            CfrCitation(
                cfr_title=title,
                cfr_part=part,
                cfr_section=match.group("section"),
                title_is_possible=possible,
                part_is_plausible=_part_is_plausible(part),
            )
        )
        if list_expansion != "always" and not _PLURAL_LABEL.match(match.group("label") or ""):
            continue
        # A plural label licenses expansion; the scan stops at the first token
        # that is not another list item.
        position = match.end()
        while (item := _CFR_LIST_ITEM.match(text, position)) is not None:
            item_part = item.group("part")
            citations.append(
                CfrCitation(
                    cfr_title=title,
                    cfr_part=item_part,
                    cfr_section=item.group("section"),
                    title_is_possible=possible,
                    part_is_plausible=_part_is_plausible(item_part),
                )
            )
            position = item.end()
    if citations:
        return tuple(citations)
    # A title with no readable part still tells a consumer the title, which is
    # how "35 CFR ch. II" stays visible as a Reserved-title citation.
    bare = re.match(rf"{_LEFT}(?P<title>[1-9]\d*)\s*C\.?\s*F\.?\s*R\.?", text, re.IGNORECASE)
    if bare is None:
        return ()
    title = int(bare.group("title"))
    return (CfrCitation(cfr_title=title, cfr_part=None, title_is_possible=_title_is_possible(title)),)


def parse_authority_citation(text: str) -> tuple[AuthorityCitation, ...]:
    """Read every legal authority in one string.

    The Unified Agenda's ``LEGAL_AUTHORITY_LIST`` carries all four shapes --
    "5 U.S.C. 301", "PL 107-171", "E.O. 13559", "106 Stat. 4777" -- and 755,727
    of them ship unparsed unless something reads them.
    """

    found: list[AuthorityCitation] = []
    for match in _USC_STANDARD.finditer(text):
        found.append(
            AuthorityCitation(
                authority_type="usc",
                usc_title=int(match.group("title")),
                usc_section=match.group("section"),
            )
        )
    for match in _PUBLIC_LAW.finditer(text):
        found.append(AuthorityCitation(authority_type="public_law", public_law=match.group("number")))
    for match in _EXECUTIVE_ORDER.finditer(text):
        found.append(AuthorityCitation(authority_type="executive_order", executive_order=match.group("number")))
    for match in _STATUTE_AT_LARGE.finditer(text):
        found.append(
            AuthorityCitation(
                authority_type="statute_at_large",
                statute_volume=int(match.group("volume")),
                statute_page=int(match.group("page")),
            )
        )
    return tuple(found)

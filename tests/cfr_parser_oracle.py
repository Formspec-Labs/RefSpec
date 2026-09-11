"""Frozen CFR reader from abe33842, retained only as the refactor oracle."""
import re

from refspec.registry.citation_grammar import (
    _LEFT,
    CfrCitation,
    _canonical_part,
    _cfr_title_is_possible,
    _label_is_plural,
    _normalize_dashes,
    states_nothing,
)

# Frozen before whole-token/range work: do not import the patterns under test.
_CFR_LIST_ITEM = re.compile('\\s*(?:,\\s*(?:and\\s+)?|and\\s+)(?P<part>\\d+[A-Za-z]?(?![0-9A-Za-z]))(?:\\.(?P<section>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?))?(?!\\s*(?:U\\.?\\s*S\\.?\\s*C|C\\.?\\s*F\\.?\\s*R|Stat\\b|FR\\b|Fed\\.?\\s?Reg|U\\.?\\s?S\\.?\\s?T\\b|U\\.?\\s?N\\.?\\s?T\\.?\\s?S\\b|T\\.?\\s?I\\.?\\s?A\\.?\\s?S\\b|U\\.\\s?S\\.\\s*\\d|S\\.\\s?Ct\\b|F\\.?\\s?(?:2d|3d|4th)\\b|F\\.?\\s?Supp\\b|Cl\\.?\\s?Ct\\b))', 34)
_CFR_LONGHAND = re.compile('(?<![0-9A-Za-z])(?<!\\d-)title\\s+(?P<title>\\d+),?\\s+Code\\s+of\\s+Federal\\s+Regulations(?:,?\\s*(?:parts?|pt\\.?)\\s*(?P<part>\\d+[A-Za-z]?))?', 34)
_CFR_PART_RANGE_TAIL = re.compile('\\s*-\\s*\\d', 32)
_CFR_STANDARD = re.compile('(?<![0-9A-Za-z])(?<!\\d-)(?P<title>\\d+)\\s*C\\.?\\s*F\\.?\\s*R\\.?\\s*(?P<label>(?:parts?|pts?\\.?|(?:sec(?:tion)?s?\\.?(?![A-Za-z])|§{1,2})))?\\s*(?P<part>\\d+[A-Za-z]?(?![0-9A-Za-z]))(?:\\.(?P<section>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?))?', 34)
_CFR_TITLE_PART = re.compile('(?<![0-9A-Za-z])(?<!\\d-)(?:title\\s+(?P<title>\\d+)\\s*[,;:-]?\\s*(?:C\\.?\\s*F\\.?\\s*R\\.?\\s*)?|(?P<title_cfr>\\d+)\\s*[,;:-]?\\s*C\\.?\\s*F\\.?\\s*R\\.?\\s*)(?:parts?|pt\\.?)\\s+(?P<part>\\d+[A-Za-z]?(?![0-9A-Za-z]))(?:\\.(?P<section>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?))?', 34)

_EO_COMPILATION = re.compile('\\b3\\s*C\\.?\\s*F\\.?\\s*R\\.?\\s*[,;:]?\\s*(?:(?P<page_before>\\d+)(?:\\s*-\\s*(?P<page_before_end>\\d+))?\\s*\\(\\s*)?(?:(?:1[789]|20)\\d{2}\\s*,\\s*(?=(?:1[789]|20)\\d{2}\\s*,?\\s*(?:Comp|Supp)\\.?(?!\\w)))?(?P<start>(?:1[789]|20)\\d{2})(?:(?:\\s*(?:(?:-\\s*){1,2}|/|to|thru|through|and)\\s*(?P<end>(?:1[789]|20)\\d{2}|\\d{4}(?=\\s*,?\\s*(?:Comp|Supp)\\.?(?!\\w))|\\d{2}(?!\\d)))\\s*,?\\s*(?(page_before)(?:Comp|Supp)\\.?(?!\\w)|(?:(?:Comp|Supp)\\.?(?!\\w))?)|\\s*,?\\s*(?:Comp|Supp)\\.?(?!\\w)|(?(page_before)(?!)|(?=\\s*,?\\s*(?:pp?\\.?|pages?)\\s*\\d)))(?(page_before)(?P<closing>\\s*\\))?|(?:\\s*,?\\s*(?:pp?\\.?|pages?)?\\s*(?P<page>\\d+)(?!\\w)(?:\\s*-\\s*(?P<page_end>\\d+)(?!\\w))?(?!\\s*(?:U\\.?\\s*S\\.?\\s*C|C\\.?\\s*F\\.?\\s*R|Stat\\b|FR\\b|Fed\\.?\\s?Reg|U\\.?\\s?S\\.?\\s?T\\b|U\\.?\\s?N\\.?\\s?T\\.?\\s?S\\b|T\\.?\\s?I\\.?\\s?A\\.?\\s?S\\b|U\\.\\s?S\\.\\s*\\d|S\\.\\s?Ct\\b|F\\.?\\s?(?:2d|3d|4th)\\b|F\\.?\\s?Supp\\b|Cl\\.?\\s?Ct\\b)))?)', 34)

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

def _part_is_plausible(part):
    return None if part is None else sum(c.isdigit() for c in part) <= 5


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

    # A placeholder locates nothing, and the CFR field writes several of them
    # with a zero title glued on ("00 CFR NYD", "00 CFR None"). Without this
    # gate the grammar read title 0 and the builder published 35 rows saying
    # "impossible CFR title" about values that name no title at all.
    # :func:`parse_authority_citation` has asked the same question of the same
    # detector since it existed; this reader simply never did.
    #
    # Nothing vanishes: the builder emits a row carrying the reference_text
    # with a NULL title whenever this returns empty, which is what the 4,453
    # bare "None" rows already do.
    if states_nothing(text):
        return ()

    normalized = _excise_compilations(_normalize_dashes(text))
    citations: list[CfrCitation] = []
    spans: list[tuple[int, int]] = []

    def _collect(title: int, part: str | None, section: str | None, span: tuple[int, int]) -> None:
        """Record one citation and the characters it accounts for.

        Three call sites built this identically before, and the third had
        already dropped its ``cfr_section`` — the longhand spelling captures
        no section, so nothing broke, and nothing would have said so if the
        spelling grew one.
        """

        citations.append(
            CfrCitation(
                cfr_title=title,
                cfr_part=part,
                cfr_section=section,
                title_is_possible=_cfr_title_is_possible(title),
                part_is_plausible=_part_is_plausible(part),
            )
        )
        spans.append(span)

    def _overlaps_a_read_span(match: re.Match[str]) -> bool:
        return any(start < match.end() and match.start() < end for start, end in spans)

    for match in _CFR_STANDARD.finditer(normalized):
        title = int(match.group("title"))
        plural = _label_is_plural(match.group("label"))
        # A plural label with a dash-joined pair behind it names a RANGE of
        # parts, and there is no column for one. The part is refused rather
        # than minted: "16 CFR pts. 0-4" cites five parts, and recording the
        # first is recording a part the citation does not single out.
        ranged = plural and _CFR_PART_RANGE_TAIL.match(normalized, match.end("part")) is not None
        _collect(
            title,
            None if ranged else _canonical_part(match.group("part")),
            None if ranged else match.group("section"),
            match.span(),
        )
        if ranged or (list_expansion != "always" and not plural):
            continue
        # The list is walked ANCHORED, one item touching the next, so an
        # expansion can never jump over intervening prose to a number that
        # belongs to something else.
        position = match.end()
        while (item := _CFR_LIST_ITEM.match(normalized, position)) is not None:
            _collect(title, _canonical_part(item.group("part")), item.group("section"), item.span())
            position = item.end()

    # The keyword spellings, each only where nothing has already been read at
    # that position — they overlap the standard grammar on "40 CFR part 60"
    # and one citation must not become two.
    for match in _CFR_TITLE_PART.finditer(normalized):
        if _overlaps_a_read_span(match):
            continue
        _collect(
            int(match.group("title") or match.group("title_cfr")),
            _canonical_part(match.group("part")),
            match.group("section"),
            match.span(),
        )
    for match in _CFR_LONGHAND.finditer(normalized):
        if _overlaps_a_read_span(match):
            continue
        _collect(int(match.group("title")), _canonical_part(match.group("part")), None, match.span())

    if citations:
        return tuple(citations)
    bare = re.match(rf"{_LEFT}(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?", normalized, re.IGNORECASE)
    if bare is None:
        return ()
    # A title with no readable part still tells a consumer the title, which
    # is how "35 CFR ch. II" stays visible as a Reserved-title citation.
    title = int(bare.group("title"))
    return (CfrCitation(cfr_title=title, cfr_part=None, title_is_possible=_cfr_title_is_possible(title)),)


# --------------------------------------------------------------------------- #
# Authority parsing




# Frozen occurrence callback before the 2026-09-11 subpart extension.
from collections.abc import Callable

from refspec.registry.citation_grammar import CfrCitationOccurrence


def _parse_cfr_citations(
    text: str, *, list_expansion: str,
    record: Callable[[CfrCitation, tuple[int, int], tuple[int, int] | None], int] | None = None,
) -> tuple[CfrCitation, ...]:
    if list_expansion not in {"plural-label", "always"}:
        raise ValueError(f"unknown list expansion policy: {list_expansion!r}")

    # A placeholder locates nothing, and the CFR field writes several of them
    # with a zero title glued on ("00 CFR NYD", "00 CFR None"). Without this
    # gate the grammar read title 0 and the builder published 35 rows saying
    # "impossible CFR title" about values that name no title at all.
    # :func:`parse_authority_citation` has asked the same question of the same
    # detector since it existed; this reader simply never did.
    #
    # Nothing vanishes: the builder emits a row carrying the reference_text
    # with a NULL title whenever this returns empty, which is what the 4,453
    # bare "None" rows already do.
    if states_nothing(text):
        return ()

    normalized = _excise_compilations(_normalize_dashes(text))
    citations: list[CfrCitation] = []
    spans: list[tuple[int, int]] = []

    def _collect(title: int, part: str | None, section: str | None, span: tuple[int, int],
                 context: tuple[int, int] | None = None) -> int:
        """Record one citation and the characters it accounts for.

        Three call sites built this identically before, and the third had
        already dropped its ``cfr_section`` — the longhand spelling captures
        no section, so nothing broke, and nothing would have said so if the
        spelling grew one.
        """

        citations.append(
            CfrCitation(
                cfr_title=title,
                cfr_part=part,
                cfr_section=section,
                title_is_possible=_cfr_title_is_possible(title),
                part_is_plausible=_part_is_plausible(part),
            )
        )
        spans.append(span)
        if record is not None:
            return record(citations[-1], span, context)
        return span[1]

    def _overlaps_a_read_span(match: re.Match[str]) -> bool:
        return any(start < match.end() and match.start() < end for start, end in spans)

    for match in _CFR_STANDARD.finditer(normalized):
        title = int(match.group("title"))
        plural = _label_is_plural(match.group("label"))
        # A plural label with a dash-joined pair behind it names a RANGE of
        # parts, and there is no column for one. The part is refused rather
        # than minted: "16 CFR pts. 0-4" cites five parts, and recording the
        # first is recording a part the citation does not single out.
        ranged = plural and _CFR_PART_RANGE_TAIL.match(normalized, match.end("part")) is not None
        position = _collect(
            title,
            None if ranged else _canonical_part(match.group("part")),
            None if ranged else match.group("section"),
            match.span(),
        )
        if ranged or (list_expansion != "always" and not plural):
            continue
        # The list is walked ANCHORED, one item touching the next, so an
        # expansion can never jump over intervening prose to a number that
        # belongs to something else.
        context = (match.start(), position)
        while (item := _CFR_LIST_ITEM.match(normalized, position)) is not None:
            position = _collect(title, _canonical_part(item.group("part")), item.group("section"), item.span(), context)

    # The keyword spellings, each only where nothing has already been read at
    # that position — they overlap the standard grammar on "40 CFR part 60"
    # and one citation must not become two.
    for match in _CFR_TITLE_PART.finditer(normalized):
        if _overlaps_a_read_span(match):
            continue
        _collect(
            int(match.group("title") or match.group("title_cfr")),
            _canonical_part(match.group("part")),
            match.group("section"),
            match.span(),
        )
    for match in _CFR_LONGHAND.finditer(normalized):
        if _overlaps_a_read_span(match):
            continue
        _collect(int(match.group("title")), _canonical_part(match.group("part")), None, match.span())

    if citations:
        return tuple(citations)
    bare = re.match(rf"{_LEFT}(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?", normalized, re.IGNORECASE)
    if bare is None:
        return ()
    # A title with no readable part still tells a consumer the title, which
    # is how "35 CFR ch. II" stays visible as a Reserved-title citation.
    title = int(bare.group("title"))
    citation = CfrCitation(cfr_title=title, cfr_part=None, title_is_possible=_cfr_title_is_possible(title))
    if record is not None:
        record(citation, bare.span(), None)
    return (citation,)


_CFR_PINPOINT_LABEL = re.compile(r"\(\s*([0-9A-Za-z]{1,4})\s*\)")

def find_cfr_citations(text: str, *, list_expansion: str = "plural-label") -> tuple[CfrCitationOccurrence, ...]:
    """Locate the existing grammar's CFR readings without changing identities.

    Source spelling, repeated occurrences and impossible-title verdicts survive.
    Explicit CFR citations only: no title or local paragraph target is inferred
    from document context. Unlike the identity-only reader, attached pinpoints
    are consumed before walking a plural list. Ranges are not expanded.
    """
    found: list[CfrCitationOccurrence] = []

    def record(citation: CfrCitation, span: tuple[int, int], context: tuple[int, int] | None) -> int:
        start, end = span
        labels: list[str] = []
        if citation.cfr_section is not None:
            while (label := _CFR_PINPOINT_LABEL.match(text, end)) is not None:
                labels.append(label.group(1))
                end = label.end()
        found.append(CfrCitationOccurrence(citation, start, end, text[start:end], tuple(labels),
                                           context[0] if context else None, context[1] if context else None))
        return end

    _parse_cfr_citations(text, list_expansion=list_expansion, record=record)
    return tuple(found)

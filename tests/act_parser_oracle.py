"""Frozen pre-occurrence matcher; normalization and data types are unchanged."""
import re
from collections.abc import Container, Mapping
from refspec.registry.citation_grammar import ActRelativeCitation, normalize_popular_name, _usc_section

_ACT_SECTION = re.compile(r"(?:sec(?:tion)?s?\.?|§{1,2})\s*(?P<section>\d+[A-Za-z]?)", re.IGNORECASE)

_CITED_DIVISION = re.compile(r"\bdiv(?:ision)?\.?\s+(?P<division>[A-Z]{1,3})\b")

_ACT_SECTION_OF_THE = re.compile(r"\A\s*(?:of\s+(?:the\s+)?|,\s*(?:the\s+)?)", re.IGNORECASE)

_MAX_ACT_NAME_WORDS = 24

_NAME_EDGE = re.compile(r"^[\s(\"'“”]+|[\s,;:.)\"'“”]+$")

def _longest_name_before(before: str, act_names: Container[str]) -> str | None:
    words = before.split()
    for length in range(min(_MAX_ACT_NAME_WORDS, len(words)), 0, -1):
        candidate = " ".join(words[-length:])
        if normalize_popular_name(candidate) in act_names:
            return _NAME_EDGE.sub("", candidate)
    return None

def _longest_name_after(after: str, act_names: Container[str]) -> str | None:
    # "Sec 1886(d) of the Social Security Act": the subsection parenthetical
    # sits between the section number and "of the", and requiring adjacency
    # silently failed every such citation — 25 of the commonest single form
    # alone. Parentheticals are skipped, bounded so a sentence in parentheses
    # is not.
    after = re.sub(r"^(?:\s*\([^()]{1,12}\))+", "", after)
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
        key = normalize_popular_name(named)
        if isinstance(act_names, Mapping):
            # A Mapping container carries spelling variants ("Motor Carrier
            # Act of 1935") keyed to their canonical popular name ("Motor
            # Carrier Act, 1935"); the key published is always canonical, so
            # act_resolution's join never sees a variant.
            key = act_names[key]
        citation = ActRelativeCitation(
            act_name=named,
            act_key=key,
            section=section,
            division=stated_division.group("division") if stated_division else None,
        )
        if citation not in found:
            found.append(citation)
    return tuple(found)

"""Frozen occurrence implementation before reusing the existing year-spelling operator."""
import re
from bisect import bisect_left, bisect_right
from collections.abc import Container, Mapping
from refspec.registry.citation_grammar import (
    _ACT_SECTION, _usc_section, _ACT_SPACE, _CITATION_PARAGRAPH_BREAK,
    _ACT_PARENTHETICAL, _CFR_PINPOINT_LABEL, _MAX_ACT_NAME_WORDS,
    _ACT_NAME_GAP, _ACT_SECTION_OF_THE, _CITED_DIVISION, _ACT_DIVISION_OF,
    _NAME_EDGE, normalize_popular_name, ActRelativeCitation, ActRelativeCitationOccurrence,
)

def _act_name_span(document: str, words: list[re.Match[str]], act_names: Container[str],
                   *, before: bool) -> tuple[int, int, str] | None:
    """Longest indexed name from at most 24 adjacent source tokens."""
    for length in range(len(words), 0, -1):
        selected = words[-length:] if before else words[:length]
        start, end = selected[0].start(), selected[-1].end()
        raw = document[start:end]
        if _CITATION_PARAGRAPH_BREAK.search(raw):
            continue
        candidate = " ".join(raw.split())
        if normalize_popular_name(candidate) not in act_names:
            continue
        edges = list(_NAME_EDGE.finditer(raw))
        left = edges[0].end() if edges and edges[0].start() == 0 else 0
        right = edges[-1].start() if edges and edges[-1].end() == len(raw) else len(raw)
        return start + left, start + right, _NAME_EDGE.sub("", candidate)
    return None

def find_act_relative_occurrences(text: object, *, act_names: Container[str]) -> tuple[ActRelativeCitationOccurrence, ...]:
    """Read indexed act names with exact spans, repeats and source pinpoints.

    The supplied name index remains the grammar: no guessed acronyms or acts.
    Tokens are indexed once; each section examines at most 24 adjacent tokens
    on either side instead of splitting the entire preceding document again.
    A directly adjacent name is supported by the published 199510 crop-insurance
    authority fields. A division must explicitly name the act it belongs to;
    nearby prose is never searched for a replacement division.
    """
    document = "" if text is None else str(text)
    words = list(re.finditer(r"\S+", document))
    starts, ends = [w.start() for w in words], [w.end() for w in words]
    found: list[ActRelativeCitationOccurrence] = []
    for marker in _ACT_SECTION.finditer(document):
        section = _usc_section(marker.group("section"))
        if section is None:
            continue
        end, labels = marker.end(), []
        while True:
            position = _ACT_SPACE.match(document, end).end()
            if _CITATION_PARAGRAPH_BREAK.search(document, end, position):
                break
            parenthetical = _ACT_PARENTHETICAL.match(document, position)
            if parenthetical is None:
                break
            label = _CFR_PINPOINT_LABEL.fullmatch(document, position, parenthetical.end())
            if label is not None and not (position > end and label.group(1).isdigit() and len(label.group(1)) == 4):
                labels.append(label.group(1))
            end = parenthetical.end()  # Other short qualifiers remain in the exact source slice.
        left = bisect_right(ends, marker.start())
        named = _act_name_span(document, words[max(0, left - _MAX_ACT_NAME_WORDS):left], act_names, before=True)
        if named is not None and (not _ACT_NAME_GAP.fullmatch(document, named[1], marker.start())
                                  or _CITATION_PARAGRAPH_BREAK.search(document, named[1], marker.start())):
            named = None
        if named is None:
            opening = _ACT_SECTION_OF_THE.match(document, end)
            if opening is None or _CITATION_PARAGRAPH_BREAK.search(document, end, opening.end()):
                continue
            right = bisect_left(starts, opening.end())
            named = _act_name_span(document, words[right:right + _MAX_ACT_NAME_WORDS], act_names, before=False)
        if named is None:
            continue
        name_start, name_end, name = named
        start, end = min(marker.start(), name_start), max(end, name_end)
        division = None
        if name_start == start:
            prefix = words[max(0, bisect_right(ends, start) - 4)].start()  # "division B of the"
            for stated in _CITED_DIVISION.finditer(document, prefix, start):
                if _ACT_DIVISION_OF.fullmatch(document, stated.end(), start):
                    division, start = stated.group('division'), stated.start()
                    break
        key = normalize_popular_name(name)
        if isinstance(act_names, Mapping):
            key = act_names[key]  # Preserve the supplied canonical spelling map.
        citation = ActRelativeCitation(name, key, section, division)
        found.append(ActRelativeCitationOccurrence(citation, start, end, document[start:end], tuple(labels)))
    return tuple(found)


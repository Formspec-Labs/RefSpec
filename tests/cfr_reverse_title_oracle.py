"""Pre-reverse-title dispatcher and callback, copied before production edits.

Only these replaced functions are the oracle. Unchanged data classes, lexical
patterns and coordinate reading are shared dependencies.
"""
from refspec.registry.citation_grammar import (
    _CFR_COORDINATE,
    _CFR_LIST_ITEM,
    _CFR_LONGHAND,
    _CFR_NOTE_PROSE,
    _CFR_STANDARD,
    _CFR_SUBPART,
    _CFR_SUBPART_CONTEXT,
    _CFR_SUBPART_ITEM,
    _CFR_SUBPART_RANGE,
    _CFR_TITLE_PART,
    _CITATION_PARAGRAPH_BREAK,
    _USC_NOTE_TAIL,
    _USC_OPEN_END_TAIL,
    Callable,
    CfrCitation,
    CfrCitationOccurrence,
    CfrCitationRange,
    _cfr_coordinate,
    _excise_compilations,
    _label_is_plural,
    _normalize_dashes,
    _read_cfr_item,
    replace,
    states_nothing,
)


def find_cfr_citations(
    text: str, *, list_expansion: str = "plural-label", expand_qualifiers: bool = True,
) -> tuple[CfrCitationOccurrence, ...]:
    """Read complete CFR coordinates and ranges with their exact source evidence.

    Source spelling, repeated occurrences and impossible-title verdicts survive.
    Explicit CFR citations only: no title or local paragraph target is inferred
    from document context. Attached pinpoints and subpart qualifiers are consumed
    before walking lists. Written range endpoints survive without expansion.
    List connectors and parenthetical qualifications remain in the source slice;
    their legal relationship is not inferred. Ambiguous part/subpart pairings
    and unsupported note/open-ended scope carry refusals rather than becoming
    definite addresses. The identity-only parser does not retain these tails.
    ``expand_qualifiers=False`` keeps one occurrence per coordinate while still
    consuming its complete qualifier text and retaining ambiguity verdicts.
    """
    found: list[CfrCitationOccurrence] = []

    def record(base: CfrCitationOccurrence) -> int:
        citation, start, end = base.citation, base.start, base.end
        context = None if base.context_start is None else (base.context_start, base.context_end)
        if (isinstance(citation, CfrCitation) and not base.refusal
                and citation.cfr_section is None and citation.cfr_part is not None
                and (subpart := _CFR_SUBPART.match(text, end)) is not None
                and not _CITATION_PARAGRAPH_BREAK.search(text, end, subpart.end())):
            appendix = subpart.group('appendix')
            plural = bool(subpart.group('plural'))
            status = 'ambiguous_part_scope' if context is not None else None
            while subpart is not None:
                end = subpart.end()
                range_end = None
                if ((tail := _CFR_SUBPART_RANGE.match(text, end)) is not None
                        and not _CITATION_PARAGRAPH_BREAK.search(text, end, tail.end())):
                    range_end, end = tail.group('end'), tail.end()
                if (description := _CFR_SUBPART_CONTEXT.match(text, end)) is not None:
                    end = description.end()
                found.append(CfrCitationOccurrence(
                    citation, start, end, text[start:end], (),
                    context[0] if context else None, context[1] if context else None,
                    subpart.group('subpart'), range_end, appendix, status,
                ))
                if range_end is not None:
                    break
                next_item = _CFR_SUBPART_ITEM.match(text, end)
                if (next_item is None or (not plural and not next_item.group('label'))
                        or _CITATION_PARAGRAPH_BREAK.search(text, end, next_item.end())):
                    break
                # Keep the whole written anchor when a part list is ambiguous.
                if start == base.start:
                    context = (context[0] if context else start, end)
                plural = plural or (next_item.group('label') or '').strip().casefold() == 'subparts'
                start, subpart = end, next_item
            return end
        found.append(base)
        return end

    def collect(base: CfrCitationOccurrence) -> int:
        before = len(found)
        end = record(base)
        # Reuse the authority reader's written scope lexemes. A note or an
        # open-ended continuation cannot be resolved as the bare coordinate.
        for pattern, refusal in (
            (_USC_NOTE_TAIL[True], 'note_target_unresolved'),
            (_USC_OPEN_END_TAIL, 'open_ended_reference_unresolved'),
        ):
            tail = pattern.match(text, end)
            if tail is None or _CITATION_PARAGRAPH_BREAK.search(text, end, tail.end()):
                continue
            if pattern is _USC_NOTE_TAIL[True]:
                prose = _CFR_NOTE_PROSE.match(text, tail.end())
                if prose and not _CITATION_PARAGRAPH_BREAK.search(text, tail.end(), prose.end()):
                    continue
            end = tail.end()
            last = found[-1]
            found[-1] = replace(last, end=end, text=text[last.start:end],
                                refusal=last.refusal or refusal)
        if not expand_qualifiers and len(found) > before:
            first = found[before]
            found[before:] = [replace(
                first, end=end, text=text[first.start:end], subpart=None,
                subpart_end=None, appendix=None,
                refusal=first.refusal or first.qualifier_status or found[-1].refusal,
            )]
        return end

    _parse_cfr_citations(text, list_expansion=list_expansion, record=collect)
    return tuple(found)


def _parse_cfr_citations(
    text: str, *, list_expansion: str,
    record: Callable[[CfrCitationOccurrence], int] | None = None,
) -> tuple[CfrCitation | CfrCitationRange, ...]:
    if list_expansion not in {"plural-label", "always"}:
        raise ValueError(f"unknown list expansion policy: {list_expansion!r}")
    if states_nothing(text):
        return ()
    normalized = _excise_compilations(_normalize_dashes(text))
    citations: list[CfrCitation | CfrCitationRange] = []
    spans: list[tuple[int, int]] = []

    def collect(item: CfrCitationOccurrence) -> int:
        # The identity-only API has no refusal column. A rejected start must
        # not escape as a complete single-part identifier through that API.
        citation = item.citation
        if item.refusal:
            head = citation.start if isinstance(citation, CfrCitationRange) else citation
            citation = _cfr_coordinate(head.cfr_title, None)
        citations.append(citation)
        end = record(item) if record is not None else item.end
        spans.append((item.start, end))
        return end

    for pattern in (_CFR_STANDARD, _CFR_TITLE_PART, _CFR_LONGHAND):
        for match in pattern.finditer(normalized):
            # The standard scan and its anchored list items advance in source
            # order. Only alternate anchor spellings need the old overlap walk.
            overlaps = (bool(spans) and match.start() < spans[-1][1] if pattern is _CFR_STANDARD else
                        any(start < match.end() and match.start() < end for start, end in spans))
            if overlaps:
                continue
            title = int(match.group('title') or match.groupdict().get('title_cfr'))
            plural = _label_is_plural(match.group('label'))
            if pattern is _CFR_LONGHAND and match.group('label') is None:
                item = CfrCitationOccurrence(_cfr_coordinate(title, None), match.start(), match.end(), match.group())
            else:
                item = _read_cfr_item(text, normalized, title, match.start(), match.end(), plural)
            position = collect(item)
            if item.refusal or (list_expansion != 'always' and not plural):
                continue
            context = (match.start(), position)
            while (separator := _CFR_LIST_ITEM.match(normalized, position)) is not None:
                if _CITATION_PARAGRAPH_BREAK.search(text, position, separator.end()):
                    break
                # Check the same whole-coordinate guard for the first member,
                # every list member and every range endpoint.
                if _CFR_COORDINATE.match(normalized, separator.end()) is None:
                    break
                item = _read_cfr_item(text, normalized, title, position, separator.end(), plural, context)
                position = collect(item)
                if item.refusal:
                    break
    return tuple(citations)


def parse_cfr_citations(text, *, list_expansion="plural-label"):
    return _parse_cfr_citations(text, list_expansion=list_expansion)

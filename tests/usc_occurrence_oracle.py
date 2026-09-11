"""Copied USC occurrence reader from c5c0a27d; unchanged helpers stay shared."""
from dataclasses import replace

from refspec.registry.citation_grammar import (
    _ACT_SPACE,
    _CFR_PINPOINT_LABEL,
    _CITATION_PARAGRAPH_BREAK,
    _USC_NOTE_TAIL,
    _USC_SUBCHAPTER_TAIL,
    _USC_UNREAD_TAIL,
    UscCitationOccurrence,
    _normalize_dashes,
    _parse_authority_citation,
    usc_title_is_possible,
)


def find_usc_citations(text: str) -> tuple[UscCitationOccurrence, ...]:
    """Locate qualified USC mentions using the existing authority matcher.

    Prose lists continue only across adjacent citation syntax. The field reader's
    wider list policy and identity-only results remain separate. Source spelling,
    repeated mentions, range interpretation and refusals survive; neither a valid
    token nor a supported title establishes existence in an edition.
    """
    found: list[UscCitationOccurrence] = []
    normalized = _normalize_dashes(text)

    def points(position):
        labels, end = [], position
        while True:
            start = _ACT_SPACE.match(text, end).end()
            if _CITATION_PARAGRAPH_BREAK.search(text, end, start):
                break
            label = _CFR_PINPOINT_LABEL.match(text, start)
            if label is None or (start > end and label.group(1).isdigit() and len(label.group(1)) == 4):
                break
            labels.append(label.group(1))
            end = label.end()
        return tuple(labels), end

    def record(citation, match, offset, span, context):
        start, end = span
        end = max(end, offset + match.end())
        while end > start and text[end - 1].isspace():
            end -= 1  # An optional appendix section can leave trailing space.
        groups = match.groupdict()
        section = 'section' if groups.get('section') is not None else 'first'
        labels, end_labels = (), ()
        if groups.get(section) is not None:
            labels, position = points(offset + match.end(section))
            end = max(end, position)
            if groups.get('range_end') is not None:
                end_labels, position = points(offset + match.end('range_end'))
                end = max(end, position)
            elif citation.usc_section_end is not None:
                end_labels, labels = labels, ()  # A label after "552-553" belongs to 553.
        refusal = None
        note = _USC_NOTE_TAIL[True].match(text, end)
        if note is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, note.end()):
            citation, end = replace(citation, usc_note=True), note.end()
            if note.group('position'):
                refusal = 'usc_note_position_unresolved'
        subchapter = subchapter_end = None
        if citation.usc_chapter is not None:
            tail = _USC_SUBCHAPTER_TAIL.match(normalized, end)
            if tail is not None and not _CITATION_PARAGRAPH_BREAK.search(text, end, tail.end()):
                subchapter, subchapter_end, end = tail.group('first'), tail.group('last'), tail.end()
                if subchapter is None:
                    refusal = 'usc_subchapter_unresolved'
                elif tail.group('plural') and '-' in subchapter and subchapter_end is None:
                    # The plural marker distinguishes written endpoints from
                    # a singular compound label such as subchapter I-A.
                    endpoints = subchapter.split('-')
                    if len(endpoints) == 2:
                        subchapter, subchapter_end = endpoints
                    else:
                        refusal = 'usc_subchapter_unresolved'
                if citation.usc_chapter_end is not None:
                    refusal = 'usc_subchapter_scope_ambiguous'
        tail = _USC_UNREAD_TAIL.match(text, end)
        if tail is not None and tail.end() > end:
            end, refusal = tail.end(), 'usc_token_continuation_unresolved'
        if groups.get('range_end') is not None and citation.usc_section_end is None:
            refusal = 'usc_range_unresolved'
        if start and text[start].isalnum() and (text[start - 1].isalnum() or text[start - 1] == '_'):
            while start and (text[start - 1].isalnum() or text[start - 1] == '_'):
                start -= 1
            refusal = 'usc_token_boundary_unresolved'
        if not usc_title_is_possible(citation.usc_title):
            refusal = 'usc_title_outside_supported_space'
        found.append(UscCitationOccurrence(
            citation, start, end, text[start:end], labels, end_labels,
            subchapter, subchapter_end,
            context[0] if context else None, context[1] if context else None, refusal,
        ))
        return end

    _parse_authority_citation(text, usc_record=record)
    return tuple(sorted(found, key=lambda item: (item.start, item.end)))

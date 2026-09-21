"""Qualified source references and unchanged authority-field interpretation.

Fixtures pin every occurrence's written text, byte offsets, pinpoint and
refusal against a frozen sha256; the same text is replayed through the copied
usc_occurrence_oracle and usc_authority_oracle to prove the rewritten readers
kept the prior interpretation verdict for verdict.
"""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from usc_authority_oracle import parse_authority_citation as prior_field_reader
from usc_occurrence_oracle import find_usc_citations as prior_occurrence_reader

from refspec.registry.citation_grammar import find_usc_citations, parse_authority_citation

CASES = json.loads((Path(__file__).parent / 'fixtures/usc-occurrences.json').read_text())
FIELD_CASES = [*CASES, *(
    {'id': f"authority-{row['cfr_title']}-{row['cfr_part']}", 'raw': row['authority_note']}
    for row in json.loads((Path(__file__).parent / 'fixtures/usc-authority-contexts.json').read_text())
)]


def reading(item):
    """The non-empty citation parts plus pinpoint, range end, subchapter and refusal."""

    result = {k: v for k, v in asdict(item.citation).items()
              if v is not None and v is not False and v != () and v != {} and k != 'parse_status'}
    for name in ('pinpoint', 'range_end_pinpoint', 'subchapter', 'subchapter_end', 'refusal'):
        value = getattr(item, name)
        if value:
            result[name] = list(value) if isinstance(value, tuple) else value
    return result


def check_positions(text, items):
    """Every occurrence's span and context must slice the source text exactly."""

    for item in items:
        assert 0 <= item.start < item.end <= len(text)
        assert text[item.start:item.end] == item.text
        if item.context_start is None:
            assert item.context_end is None
        else:
            assert 0 <= item.context_start < item.context_end <= len(text)


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['id'])
def test_frozen_written_targets_and_original_positions(case):
    """Each case's raw sha256, occurrence readings, spans and context slices match the frozen record."""

    assert hashlib.sha256(case['raw'].encode()).hexdigest() == case['text_sha256']
    items = find_usc_citations(case['raw'])
    check_positions(case['raw'], items)
    assert [reading(item) for item in items] == [row['reading'] for row in case['occurrences']]
    assert [(item.start, item.end, item.text) for item in items] == [
        (row['start'], row['end'], row['text']) for row in case['occurrences']]
    for item, expected in zip(items, case['occurrences'], strict=True):
        context = None if item.context_start is None else case['raw'][item.context_start:item.context_end]
        assert context == expected.get('context')


@pytest.mark.parametrize('case', FIELD_CASES, ids=lambda row: row['id'])
def test_existing_field_reader_matches_copied_oracle_on_source_and_mutations(case):
    """The field reader agrees with the copied oracle on the source text and five mutations."""

    text = case['raw']
    variants = (text, '  '+text+'\n', 'See '+text+'; 7 U.S.C. 1.',
                text.replace('U.S.C.', 'USC'), text.replace(' ', '\u00a0'),
                text+' and 552a', text.replace('note', 'NOTE'))
    for value in variants:
        assert [asdict(c) for c in parse_authority_citation(value)] == [
            asdict(c) for c in prior_field_reader(value)]


@pytest.mark.parametrize('case', FIELD_CASES, ids=lambda row: row['id'])
def test_previous_occurrence_results_stay_identical_on_prior_sources(case):
    """The occurrence reader agrees with the copied oracle on the source text and its mutations."""

    text = case['raw']
    for value in (text, '  ' + text + '\n', text.replace('U.S.C.', 'USC'),
                  text.replace(' ', '\u00a0'), 'See ' + text + '; 7 U.S.C. 1.'):
        assert find_usc_citations(value) == prior_occurrence_reader(value)


@pytest.mark.parametrize('tail', [', et seq.', ' and following', ' ff.'])
def test_open_ended_citation_is_not_reduced_to_its_first_section(tail):
    """et seq., and following, and ff. extend the span and refuse as usc_open_ended_reference_unresolved."""

    text = 'Under 38 U.S.C. 4301' + tail + ', the employee retains rights.'
    before, = prior_occurrence_reader(text)
    after, = find_usc_citations(text)
    assert before.text == '38 U.S.C. 4301' and before.refusal is None
    assert after.text == '38 U.S.C. 4301' + tail
    assert after.refusal == 'usc_open_ended_reference_unresolved'
    assert after.citation == before.citation and after.citation.usc_section_end is None
    assert parse_authority_citation(text) == prior_field_reader(text)


def test_ordinary_prose_and_paragraph_boundaries_are_not_open_ranges():
    """A sentence end or paragraph break after the section is not an open range; verdicts match the oracle."""

    for text in ('38 U.S.C. 4301 applies to this employee.', '38 U.S.C. 4301\n\net seq.'):
        assert find_usc_citations(text) == prior_occurrence_reader(text)


def test_qualified_list_keeps_its_title_context_and_literal_connectors():
    """A comma list keeps each member's literal connector and the first title as context."""

    text = '5 U.S.C. 552(a), 552a note, and 553(b)'
    items = find_usc_citations(text)
    check_positions(text, items)
    assert [c.citation.usc_section for c in items] == ['552', '552a', '553']
    assert [c.pinpoint for c in items] == [('a',), (), ('b',)]
    assert [c.citation.usc_note for c in items] == [False, True, False]
    assert items[1].text == ', 552a note'
    assert items[2].text == 'and 553(b)'
    assert text[items[2].context_start:items[2].context_end] == '5 U.S.C. 552(a), 552a note'
    assert all(c.refusal is None for c in items)


def test_repeated_section_pinpoints_are_not_merged():
    """Two mentions of one section remain two non-overlapping occurrences."""

    text = '5 U.S.C. 552(a); 5 U.S.C. 552(b)'
    items = find_usc_citations(text)
    check_positions(text, items)
    assert [c.pinpoint for c in items] == [('a',), ('b',)]
    assert items[0].end < items[1].start


def test_commas_separate_list_members_without_creating_token_damage():
    """Comma-joined sections each stay their own occurrence with no refusal."""

    text = '12 U.S.C. 2013, 2015, 2018'
    items = find_usc_citations(text)
    check_positions(text, items)
    assert [c.text for c in items] == ['12 U.S.C. 2013', ', 2015', ', 2018']
    assert all(c.refusal is None for c in items)


@pytest.mark.parametrize('position', ['preceding', 'following'])
def test_positioned_note_is_retained_and_refuses_a_section_identity(position):
    """A preceding or following note stays in the span and refuses as usc_note_position_unresolved."""

    text = f'49 U.S.C. 42301 {position} note'
    item, = find_usc_citations(text)
    assert item.text == text and item.citation.usc_note is True
    assert item.refusal == 'usc_note_position_unresolved'


@pytest.mark.parametrize('case', FIELD_CASES[-2:], ids=lambda row: row['id'])
def test_publisher_authority_lists_have_no_false_token_boundary_refusals(case):
    """The last two authority fixtures refuse nothing beyond the known note caveat."""

    items = find_usc_citations(case['raw'])
    check_positions(case['raw'], items)
    assert all(c.refusal in (None, 'usc_note_position_unresolved') for c in items)
    if case['id'] == 'authority-14-121':
        note, = (c for c in items if c.citation.usc_section == '42301')
        assert note.text == ', 42301 preceding note'
        assert note.refusal == 'usc_note_position_unresolved'


@pytest.mark.parametrize('text,first,last', [
    ('5 U.S.C. 552-553(a)', (), ('a',)),
    ('5 U.S.C. 552(a) through 553(b)', ('a',), ('b',)),
])
def test_pinpoints_stay_with_the_written_range_endpoint(text, first, last):
    """552-553(a) gives the (a) pinpoint to 553, not to 552."""

    item, = find_usc_citations(text)
    assert item.text == text
    assert item.pinpoint == first and item.range_end_pinpoint == last
    assert item.citation.usc_section == '552' and item.citation.usc_section_end == '553'
    assert item.citation.usc_section_span_rule == 'stated'
    assert item.refusal is None


def test_declined_range_preserves_both_written_pinpoints_and_refuses_narrowing():
    """49 U.S.C. 1354(a) to 1354(c) keeps both written pinpoints and refuses as usc_range_unresolved."""

    text = '49 U.S.C. 1354(a) to 1354(c)'
    item, = find_usc_citations(text)
    assert item.text == text and item.pinpoint == ('a',) and item.range_end_pinpoint == ('c',)
    assert item.refusal == 'usc_range_unresolved'


@pytest.mark.parametrize('text,appendix,quote', [
    ('5 U.S.C.', False, '5 U.S.C.'),
    ('5 U.S.C. App.', True, '5 U.S.C. App.'),
    ('Under 5 U.S.C. App. other provisions apply.', True, '5 U.S.C. App.'),
])
def test_bare_title_or_appendix_does_not_invent_a_section(text, appendix, quote):
    """A bare title, or title plus Appendix, keeps no section and no refusal."""

    item, = find_usc_citations(text)
    assert item.text == quote and item.citation.usc_title == 5
    assert item.citation.usc_appendix is appendix and item.citation.usc_section is None
    assert item.refusal is None


def test_unicode_left_boundary_is_retained_as_a_refusal():
    """A letter before the title is kept in the span and refuses as usc_token_boundary_unresolved."""

    text = 'α5 USC 552'
    item, = find_usc_citations(text)
    assert item.text == text and item.refusal == 'usc_token_boundary_unresolved'


def test_a_paragraph_break_stops_an_inherited_title():
    """A paragraph break stops 553 from inheriting title 5 from the 552 occurrence."""

    assert [c.citation.usc_section for c in find_usc_citations('5 USC 552\n\nand 553')] == ['552']


def test_subchapter_does_not_pick_a_chapter_from_a_range():
    """A chapter range plus subchapter refuses as usc_subchapter_scope_ambiguous rather than choosing one."""

    item, = find_usc_citations('5 USC chapters 5-7, subchapter I')
    assert item.subchapter == 'I' and item.citation.usc_chapter_end == '7'
    assert item.refusal == 'usc_subchapter_scope_ambiguous'


def test_declared_but_missing_subchapter_is_not_broadened_to_the_chapter():
    """A declared but unnamed subchapter refuses as usc_subchapter_unresolved rather than widening to the chapter."""

    text = '5 USC chapter 81, subchapter'
    item, = find_usc_citations(text)
    assert item.text == text and item.refusal == 'usc_subchapter_unresolved'


@pytest.mark.parametrize('text,first,last', [
    ('5 USC chapter 81, subchapters I-II', 'I', 'II'),
    ('5 USC chapter 81, subchapter I-A', 'I-A', None),
    ('5 USC chapter 81, subchapters I through II', 'I', 'II'),
])
def test_subchapter_names_and_written_ranges_are_preserved(text, first, last):
    """I-II, I-A and "I through II" each keep their written subchapter names and range semantics."""

    item, = find_usc_citations(text)
    assert item.text == text and item.subchapter == first and item.subchapter_end == last
    assert item.refusal is None


def test_a_range_separator_does_not_steal_the_next_explicit_title():
    """A dash between two fully written citations yields two occurrences, not one range."""

    items = find_usc_citations('7 U.S.C. 6501 - 7 U.S.C. 6524')
    assert [c.citation.usc_section for c in items] == ['6501', '6524']
    assert all(c.citation.usc_section_end is None and c.refusal is None for c in items)

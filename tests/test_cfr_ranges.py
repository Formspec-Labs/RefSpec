"""Publisher paragraphs and declared mutations distinguish coordinates from ranges."""
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from cfr_parser_oracle import parse_cfr_citations as original_parse

from refspec.registry.citation_grammar import (
    CfrCitation,
    CfrCitationRange,
    find_cfr_citations,
    parse_authority_citation,
    parse_cfr_citations,
)

CASES = json.loads(Path(__file__).with_name('fixtures').joinpath('cfr-ranges.json').read_text())
DIVERGENCES = {
    'compound_section_range', 'compound_singular', 'compound_list', 'compound_list_three',
    'numeric_part_range', 'compound_cross_title', 'compound_cross_title_list',
}


def coordinate(title, value):
    """Partition "part.section" into an exact citation, with a section only when a dot is present."""
    part, dot, section = value.partition('.')
    return CfrCitation(title, part, section if dot else None, True, True)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
@pytest.mark.parametrize('mutation', ['original', 'unicode_dash', 'linebreak', 'neighbor', 'full_paragraph'])
def test_publisher_context_and_mutations_preserve_complete_meaning(case, mutation):
    """Across every fixture case and five mutations, the frozen pre-change
    reader agrees, the readable span is complete, and the frozen divergence
    list stays exact.
    """
    text = case['focus']
    if mutation == 'unicode_dash':
        text = text.replace('-', '–')
    elif mutation == 'linebreak':
        text = text.replace(' ', '\n')
    elif mutation == 'neighbor':
        text += '; 5 USC 552.'
    elif mutation == 'full_paragraph':
        text = case['text']
    before = [asdict(c) for c in original_parse(text)]
    assert before == case['frozen_before']  # Independent copied pre-change reader.
    title = int(case['focus'].split()[0])
    meaning = case['expected']
    expected = ([CfrCitationRange(coordinate(title, meaning['range_start']),
                                  coordinate(title, meaning['range_end']))]
                if 'range_start' in meaning else [coordinate(title, part) for part in meaning['parts']])
    rows = find_cfr_citations(text)
    assert [row.citation for row in rows] == expected
    assert all(row.refusal is None for row in rows)
    assert all(text[row.start:row.end] == row.text for row in rows)
    assert (before != [asdict(c) for c in expected]) == (case['id'] in DIVERGENCES)
    assert parse_cfr_citations(text) == tuple(expected)
    if mutation != 'full_paragraph':
        assert text[rows[0].start:rows[-1].end] == text.removesuffix('; 5 USC 552.')


def test_cross_part_range_and_mixed_list_keep_both_pinpoints():
    """A range with pinpoints keeps both endpoints and their pinpoints; the
    authority reader refuses the pair as range_pinpoints_not_represented.
    """
    text = '40 CFR §§ 60.1(a) through 61.2(b), and 63.3(c)'
    rows = find_cfr_citations(text)
    assert len(rows) == 2
    first, second = rows
    assert first.citation == CfrCitationRange(coordinate(40, '60.1'), coordinate(40, '61.2'))
    assert (first.pinpoint, first.range_end_pinpoint) == (('a',), ('b',))
    assert second.citation == coordinate(40, '63.3') and second.pinpoint == ('c',)
    assert text[second.context_start:second.context_end] == first.text
    assert text[first.start:second.end] == text
    assert [row.cfr_refusal for row in parse_authority_citation(text)] == ['range_pinpoints_not_represented', None]


def test_mixed_compound_list_contains_a_range_without_expanding_it():
    """A compound list keeps its range member as a written range rather than expanding it."""
    text = '41 CFR parts 60-1, 60-3 through 60-4, and 102-193'
    assert [r.citation for r in find_cfr_citations(text)] == [
        coordinate(41, '60-1'),
        CfrCitationRange(coordinate(41, '60-3'), coordinate(41, '60-4')),
        coordinate(41, '102-193'),
    ]


@pytest.mark.parametrize('text, refusal', [
    ('41 CFR 60-1-60-2', 'ambiguous_hyphen'),
    ('40 CFR 60-63', 'ambiguous_hyphen'),
    ('32 CFR 1-403', 'ambiguous_hyphen'),
    ('17 CFR 15c3-3', 'unread_coordinate'),
    ('41 CFR 60- 1', 'unread_coordinate'),
    ('40 CFR parts 60 through', 'range_end_unread'),
    ('40 CFR parts 60 through unknown', 'range_end_unread'),
    ('40 CFR parts 60 through 61.2', 'mixed_range_units'),
    ('40 CFR parts 60 through 61 through 62', 'nested_range'),
    ('40 CFR §§ 60.1-61.2', 'ambiguous_section_range'),
])
def test_unknown_tails_stay_observable_and_do_not_escape_as_single_identities(text, refusal):
    """Every refusal keeps its source text and reason, the identity-only API
    emits no part, and the authority API repeats the refusal.
    """
    row, = find_cfr_citations(text)
    assert row.text == text and row.refusal == refusal
    safe, = parse_cfr_citations(text)
    assert isinstance(safe, CfrCitation) and safe.cfr_part is None
    authority, = parse_authority_citation(text)
    assert authority.cfr_refusal == refusal


@pytest.mark.parametrize('text', [
    '40 CFR part 37, 12 people attended.', '41 CFR part 102-117, 15 USC 78c.',
    '41 CFR parts 102-117, 15 USC 78c.',
])
def test_another_citation_and_singular_prose_do_not_continue_a_list(text):
    """A following citation or singular prose must not be consumed as part of a plural list."""
    row, = find_cfr_citations(text)
    assert row.refusal is None
    assert row.text in {'40 CFR part 37', '41 CFR part 102-117', '41 CFR parts 102-117'}


@pytest.mark.parametrize('expand', [False, True])
def test_qualifier_mode_is_native_and_never_deduplicates_explicit_repetitions(expand):
    """Collapsed qualifier mode keeps one occurrence per coordinate while still
    consuming its qualifier, and repeated mentions are not deduplicated.
    """
    mention = '49 CFR part 172, subparts E and F'
    text = mention + '; ' + mention
    rows = find_cfr_citations(text, expand_qualifiers=expand)
    assert len(rows) == (4 if expand else 2)
    if not expand:
        assert [row.text for row in rows] == [mention, mention]
        assert rows[0].start == 0 and rows[1].start == len(mention) + 2
    else:
        assert [row.subpart for row in rows] == ['E', 'F', 'E', 'F']


def test_collapsing_qualifiers_retains_ambiguous_part_scope():
    """Collapsing a multi-part list keeps the whole written anchor and the ambiguous_part_scope refusal."""
    text = '45 CFR parts 160 and 164, subparts A and E'
    first, last = find_cfr_citations(text, expand_qualifiers=False)
    assert first.citation.cfr_part == '160'
    assert last.text == ' and 164, subparts A and E'
    assert last.refusal == 'ambiguous_part_scope'


def test_numeric_range_keeps_zero_and_five_digit_parts_remain_plausible():
    """Zero is a valid part, five-digit parts stay plausible, and a fused 42 CFR 412106 part is implausible."""
    assert parse_cfr_citations('16 CFR pts. 0-4') == (
        CfrCitationRange(coordinate(16, '0'), coordinate(16, '4')),)
    assert parse_cfr_citations('5 CFR part 10001') == (coordinate(5, '10001'),)
    assert parse_cfr_citations('42 CFR 412106')[0].part_is_plausible is False


def test_authority_rows_keep_both_coordinates_without_asserting_range_members():
    """The authority reader keeps both written coordinates and marks both
    plausible without expanding the range.
    """
    row, = parse_authority_citation('41 CFR 101-19.600 to 101-19.607')
    assert (row.cfr_part, row.cfr_section, row.cfr_part_end, row.cfr_section_end) == (
        '101-19', '600', '101-19', '607')
    assert row.cfr_part_is_plausible is True and row.cfr_end_part_is_plausible is True
    assert row.cfr_refusal is None


def test_refused_end_does_not_swallow_a_neighboring_explicit_citation():
    """An unread range end must stop at the next explicit citation instead of swallowing it."""
    text = '41 CFR parts 60-1 through 40 CFR part 60'
    first, second = find_cfr_citations(text)
    assert first.refusal == 'range_end_unread'
    assert first.text == '41 CFR parts 60-1 through'
    assert second.citation == coordinate(40, '60') and second.text == '40 CFR part 60'


@pytest.mark.parametrize('text', [
    '40 CFR §§60.1(a) through (c)',
    '40 CFR parts 60 through 61 through 62 through 63',
])
def test_unresolved_label_end_and_chains_keep_full_source_without_guessing(text):
    """An unresolved label end or a chained range keeps the full source text with a refusal."""
    row, = find_cfr_citations(text)
    assert row.refusal is not None and row.text == text


def test_compilation_word_overrides_misleading_parts_label_in_publisher_note():
    """A ``Comp.`` compilation locator is not a CFR range; the EO-locator reader claims it instead."""
    # Exact note under title40 XML PART110, followed by its independent Source
    # note (52 FR10719), confirms this is the EO's compilation locator.
    text = ('Authority: 33 U.S.C. 1251 et seq., 33 U.S.C. 1321(b)(3) and (b)(4) and 1361(a); '
            'E.O. 11735, 38 FR 21243, 3 CFR parts 1971-1975 Comp., p. 793.')
    from refspec.registry.citation_grammar import find_eo_compilation_locators
    assert find_cfr_citations(text) == ()
    locator, = find_eo_compilation_locators(text)
    assert locator.text == '3 CFR parts 1971-1975 Comp., p. 793'
    assert (locator.locator.compilation_start, locator.locator.compilation_end, locator.locator.page) == (
        '1971', '1975', '793')
    assert isinstance(parse_cfr_citations('3 CFR parts 100 through 102')[0], CfrCitationRange)


def test_observed_no_space_after_cfr_is_preserved():
    """The observed 49 CFR1.97 spelling without a space is read as written."""
    text = '60103-4, 60108, 60110, 60113, 60118, 49 CFR1.97'
    row, = find_cfr_citations(text)
    assert row.citation == coordinate(49, '1.97') and row.text == '49 CFR1.97'


@pytest.mark.parametrize('name', ['range_end', 'compound', 'pinpoint', 'plausibility'])
def test_semantic_checks_detect_deliberately_broken_readers(name, monkeypatch):
    """Monkeypatching each semantic guard must make its test fail, proving the checks detect breakage."""
    import re

    from refspec.registry import citation_grammar as grammar
    if name == 'range_end':
        monkeypatch.setattr(grammar, '_CFR_RANGE_CONNECTOR', re.compile(r'(?!)'))
        def check():
            test_publisher_context_and_mutations_preserve_complete_meaning(CASES[0], 'original')
    elif name == 'compound':
        monkeypatch.setattr(grammar, '_CFR_COORDINATE', re.compile(r'(?P<part>\d+)(?:\.(?P<section>\d+))?'))
        case = next(c for c in CASES if c['id'] == 'compound_singular')
        def check():
            test_publisher_context_and_mutations_preserve_complete_meaning(case, 'original')
    elif name == 'pinpoint':
        monkeypatch.setattr(grammar, '_CFR_PINPOINT_LABEL', re.compile(r'(?!)'))
        check = test_cross_part_range_and_mixed_list_keep_both_pinpoints
    else:
        monkeypatch.setattr(grammar, '_part_is_plausible', lambda part: True)
        check = test_numeric_range_keeps_zero_and_five_digit_parts_remain_plausible
    with pytest.raises(AssertionError):
        check()

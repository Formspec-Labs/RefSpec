"""Real subpart contexts plus mutation controls for the subpart grammar.

Pins the EXPECTED rows for seven real sources and proves the new reader matches
cfr_parser_oracle everywhere else, including unicode source coordinates.
"""
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from cfr_parser_oracle import find_cfr_citations as old_find
from cfr_parser_oracle import parse_cfr_citations as old_parse

from refspec.registry.citation_grammar import find_cfr_citations, parse_cfr_citations

CASES = json.loads((Path(__file__).parent / 'fixtures/cfr-subparts.json').read_text())
# (title, part, subpart, appendix, refusal) -- every deliberate old-reader change.
EXPECTED = {
    'ohio': [(49, '172', 'E', None, None), (49, '172', 'F', None, None)],
    'ecfr-21-1': [(40, '82', 'A', 'A', None), (40, '82', 'A', 'B', None)],
    'ecfr-21-2': [(21, '10', 'C', None, None)],
    'ecfr-40-1': [(40, '59', 'F', None, None)],
    'ecfr-40-2': [(40, '3', 'E', None, None)],
    'ecfr-49-1': [(45, '46', s, None, None) for s in 'BCD'],
    'ecfr-49-2': [(45, '164', s, None, 'ambiguous_part_scope') for s in 'AE'],
}


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_real_sources_preserve_subparts_and_every_unrelated_reading(case):
    """Pin the frozen subpart/appendix/refusal rows and prove every unlisted reading still matches the old reader."""

    text = case['raw']
    assert parse_cfr_citations(text) == old_parse(text)
    rows = find_cfr_citations(text)
    qualified = [r for r in rows if r.subpart]
    assert [(r.citation.cfr_title, r.citation.cfr_part, r.subpart, r.appendix, r.qualifier_status)
            for r in qualified] == EXPECTED[case['id']]
    for old in old_find(text):
        overlaps = [r for r in qualified if r.start <= old.start < r.end]
        if not overlaps:
            assert old in rows  # Unlisted changes fail; exact fields/spans stay equal.
    assert all(text[r.start:r.end] == r.text for r in rows)
    assert all(r.context_start is None or 0 <= r.context_start < r.context_end <= r.start for r in rows)


def test_ohio_alternatives_keep_connector_descriptors_and_written_context():
    """Pin that a connector-led second alternative keeps its own span and written context, with no pinpoint."""

    raw = '49 CFR Part 172 subpart E (labeling) or subpart F (placarding)'
    a, b = find_cfr_citations(raw)
    assert a.text == '49 CFR Part 172 subpart E (labeling)'
    assert b.text == ' or subpart F (placarding)'
    assert raw[b.context_start:b.context_end] == a.text
    assert not a.pinpoint and not b.pinpoint


@pytest.mark.parametrize('text', [
    '49 CFR Part 172. Subpart E applies elsewhere.',
    '49 CFR Part 172\n\nsubpart E', '49 CFR Part 172\r\n \r\nsubpart E',
    '49 CFR Part 172 concerns subpart E.', '49 CFR Part 172, subpart Elsewhere',
    '49 CFR Part 172, subpart E1', '49 CFR Part 172, subpart E-related',
    '49 CFR Part 172, subpart', '49 CFR Part 172.400 subpart E',
    'Subpart E of this part', '49 CFR Part 172, appendix A to another subpart E',
    '49 CFR Part 172, subparts involving engines',
])
def test_no_new_qualification_from_unrelated_or_damaged_text(text):
    """Fail if unrelated or damaged text mints a subpart qualification the old reader did not."""

    assert find_cfr_citations(text) == old_find(text)
    assert parse_cfr_citations(text) == old_parse(text)


@pytest.mark.parametrize('tail', [
    '. Subpart F', '\n\n or subpart F', '; or subpart F',
    ', F refers to another document', ' or 40 CFR part 59, subpart F',
])
def test_a_singular_subpart_does_not_license_unanchored_list_members(tail):
    """Pin that a singular subpart does not extend past punctuation, except a newly anchored 40 CFR part."""

    text = '49 CFR Part 172 subpart E' + tail
    rows = find_cfr_citations(text)
    assert [(r.citation.cfr_title, r.subpart) for r in rows] == (
        [(49, 'E'), (40, 'F')] if '40 CFR' in tail else [(49, 'E')])


@pytest.mark.parametrize('separator', [' through ', ' to ', '–', '-'])
def test_ranges_keep_stated_endpoints_without_enumeration(separator):
    """Pin that E through G stays one row with subpart_end=G rather than enumerated members."""

    text = f'49 CFR part 172, subparts E{separator}G'
    row, = find_cfr_citations(text)
    assert (row.subpart, row.subpart_end) == ('E', 'G')
    assert row.text == text


def test_plural_subparts_and_repeats_use_exact_unicode_source_coordinates():
    """Pin exact unicode offsets and per-member text for repeated plural lists after an emoji."""

    source = '45 CFR part 46, subparts B, C, and D'
    text = f'😀 {source}; then {source}'
    rows = find_cfr_citations(text)
    assert [r.subpart for r in rows] == list('BCDBCD')
    assert rows[0].start == 2 and rows[3].start == text.rindex(source)
    assert [r.text for r in rows[:3]] == ['45 CFR part 46, subparts B', ', C', ', and D']


def test_an_explicit_plural_continuation_licenses_its_own_list():
    """Pin that an explicit "subparts F and G" continuation yields E, F, and G."""

    rows = find_cfr_citations('49 CFR part 172 subpart E or subparts F and G')
    assert [r.subpart for r in rows] == list('EFG')


def test_parenthetical_qualification_is_source_text_not_a_subpart_name():
    """Pin that a parenthetical stays source text, not a subpart name or pinpoint."""

    text = '40 CFR part 3, subpart E (employees must state their own views)'
    row, = find_cfr_citations(text)
    assert row.text == text and row.subpart == 'E'
    assert row.pinpoint == () and row.appendix is None


def test_invalid_titles_keep_their_existing_verdict():
    """Pin that an impossible CFR title still yields its subpart, with title_is_possible False."""

    row, = find_cfr_citations('99 CFR part 172, subpart E')
    assert not row.citation.title_is_possible and row.subpart == 'E'


def test_unqualified_serialization_has_only_empty_new_optional_fields():
    """Pin that an unqualified citation serializes the four new optional fields as None only."""

    row, = find_cfr_citations('40 CFR 82.154(a)')
    assert {k: v for k, v in asdict(row).items() if k in
            ('subpart', 'subpart_end', 'appendix', 'qualifier_status')} == {
                'subpart': None, 'subpart_end': None, 'appendix': None, 'qualifier_status': None}

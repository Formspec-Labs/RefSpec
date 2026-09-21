"""Reverse explicit titles: source comparison and declared scope controls.

Only the case ids in DIVERGENCES may differ from the frozen oracle, which
every comparison here asserts by equality.
"""
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from cfr_reverse_title_oracle import find_cfr_citations as before_find
from cfr_reverse_title_oracle import parse_cfr_citations as before_parse

from refspec.registry.citation_grammar import (
    CfrCitation,
    CfrCitationRange,
    find_cfr_citations,
    parse_authority_citation,
    parse_cfr_citations,
)

CASES = json.loads(Path(__file__).with_name('fixtures').joinpath('cfr-reverse-title.json').read_text())
DIVERGENCES = {'foreign-title-suffix', 'other-title-suffix'}


def meanings(rows):
    """Return (title, part, section) triples for coordinate citations, skipping ranges."""
    return [(row.citation.cfr_title, row.citation.cfr_part, row.citation.cfr_section)
            for row in rows if isinstance(row.citation, CfrCitation)]


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
@pytest.mark.parametrize('expand', [True, False])
def test_original_paragraphs_and_mutations_have_only_declared_changes(case, expand):
    """Pins that the readers differ only on the frozen DIVERGENCES ids across both qualifier and list policies."""
    text = case['text']
    old = [asdict(r) for r in before_find(text, expand_qualifiers=expand)]
    new = [asdict(r) for r in find_cfr_citations(text, expand_qualifiers=expand)]
    assert (old != new) == (case['id'] in DIVERGENCES)
    for policy in ('always', 'plural-label'):
        assert (before_parse(text, list_expansion=policy) != parse_cfr_citations(text, list_expansion=policy)) == (
            case['id'] in DIVERGENCES)
    if case['id'] == 'foreign-title-suffix':
        assert meanings(find_cfr_citations(text)) == [(29, '1910', None), (29, '1954', '3'), (29, '1910', None)]
        assert find_cfr_citations(text)[1].pinpoint == ('d', '1', 'i')
    if case['id'] == 'other-title-suffix':
        assert meanings(find_cfr_citations(text)) == [(17, '1', '3')]


@pytest.mark.parametrize('body,title,expected', [
    ('§ 1954.3(d)(1)(i)', 29, [('1954', '3')]),
    ('part 1910', 29, [('1910', None)]),
    ('parts 1910 and 1911', 29, [('1910', None), ('1911', None)]),
    ('sections 82.155(a), 82.156(b)', 40, [('82', '155'), ('82', '156')]),
    ('§ 102-5.20', 41, [('102-5', '20')]),
    ('§ 1.3', 99, [('1', '3')]),
    ('part 82, subpart F', 40, [('82', None)]),
    ('part 82, subparts F and G', 40, [('82', None), ('82', None)]),
])
def test_complete_reverse_coordinates_and_context(body, title, expected):
    """Pins each reverse coordinate's meaning, exact source slice, context span and title-possibility verdict."""
    text = f'Before {body} of title {title}, Code of Federal Regulations; after.'
    rows = find_cfr_citations(text)
    assert meanings(rows) == [(title, part, section) for part, section in expected]
    context = f'{body} of title {title}, Code of Federal Regulations'
    for row in rows:
        assert text[row.start:row.end] == row.text
        if len(rows) == 1:
            assert (row.context_start, row.context_end) == (None, None)
            assert row.text == context
        else:
            assert text[row.context_start:row.context_end] == context
        assert row.citation.title_is_possible == (title != 99)
        assert row.refusal is None
    if 'subpart' in body:
        assert rows[0].subpart == 'F'


@pytest.mark.parametrize('body', ['§§ 82.155(a) through 82.156(b)', 'parts 60-1 through 60-3'])
def test_reverse_ranges_preserve_endpoints_and_source(body):
    """Pins that reverse ranges keep their written endpoints, full source slice and end pinpoints."""
    title = 41 if '60-1' in body else 40
    text = f'{body} of title {title}, Code of Federal Regulations'
    row, = find_cfr_citations(text)
    assert row.text == text and isinstance(row.citation, CfrCitationRange)
    assert row.refusal is None
    if title == 40:
        assert row.pinpoint == ('a',) and row.range_end_pinpoint == ('b',)
        assert row.citation.end.cfr_section == '156'
    else:
        assert (row.citation.start.cfr_part, row.citation.end.cfr_part) == ('60-1', '60-3')


@pytest.mark.parametrize('text,refusal', [
    ('§ 82.155 note of title 40, Code of Federal Regulations', 'note_target_unresolved'),
    ('§ 82.155 of title 40, Code of Federal Regulations, note', 'note_target_unresolved'),
    ('§ 82.155 et seq. of title 40, Code of Federal Regulations', 'open_ended_reference_unresolved'),
    ('§ 82.155 of title 40, Code of Federal Regulations et seq.', 'open_ended_reference_unresolved'),
    ('§§ 82.155, 82.156 of title 40, Code of Federal Regulations, note', 'note_target_unresolved'),
    ('§§ 82.155 through unknown of title 40, Code of Federal Regulations', 'range_end_unread'),
])
def test_shared_scope_is_not_stripped_to_accept_a_section(text, refusal):
    """Pins that note, open-ended and unread range-end scope is refused rather than stripped to accept the section."""
    rows = find_cfr_citations(text)
    assert rows and all(row.refusal == refusal for row in rows)
    assert all(row.text == text if len(rows) == 1 else text[row.context_start:row.context_end] == text for row in rows)
    assert all(row.cfr_part is None for row in parse_cfr_citations(text))
    assert all(row.cfr_refusal == refusal for row in parse_authority_citation(text) if row.authority_type == 'cfr')


@pytest.mark.parametrize('text', [
    '§ 82.155',
    'section 552 of title 5',
    'section 552 of title 5, United States Code',
    'section 552 of title 5, Code of Federal Regulations',
    '§ 82.155 is discussed in a review of title 40, Code of Federal Regulations',
    '§ 82.155. The review of title 40, Code of Federal Regulations follows.',
    '§ 82.155\n\nof title 40, Code of Federal Regulations',
    '§\n\n82.155 of title 40, Code of Federal Regulations',
    '§§ 82.155, 17 CFR 1.3 of title 40, Code of Federal Regulations',
    '40 CFR § 82.155 of title 17, Code of Federal Regulations',
    'section 82.155, 82.156 of title 40, Code of Federal Regulations',
])
def test_incomplete_or_competing_anchors_keep_prior_readings(text):
    """Pins that incomplete or competing anchors keep the frozen oracle's readings exactly."""
    assert [asdict(r) for r in find_cfr_citations(text)] == [asdict(r) for r in before_find(text)]


def test_repeats_mixed_titles_and_line_wrapping_preserve_occurrences():
    """Pins that repeated wrapped reverse citations keep distinct occurrences with identical source text."""
    local = '§ 1.3\nof title 17, Code of Federal Regulations'
    text = f'{local}; 40 CFR 82.155; {local}'
    rows = sorted(find_cfr_citations(text), key=lambda row: row.start)
    assert meanings(rows) == [(17, '1', '3'), (40, '82', '155'), (17, '1', '3')]
    assert rows[0].start != rows[2].start
    assert rows[0].text == rows[2].text == local


def test_structured_list_policy_remains_explicit():
    """Pins that list_expansion='always' reads both parts while the default keeps one title-only coordinate."""
    text = 'part 1910, 1911 of title 29, Code of Federal Regulations'
    assert meanings(find_cfr_citations(text, list_expansion='always')) == [(29, '1910', None), (29, '1911', None)]
    assert meanings(find_cfr_citations(text)) == [(29, None, None)]


@pytest.mark.parametrize('label', ['§§', '§'])
def test_repeated_section_labels_do_not_hide_the_first_member(label):
    """Pins that a repeated section label does not hide the first list member."""
    text = f'{label} 82.155 and § 82.156 of title 40, Code of Federal Regulations'
    rows = find_cfr_citations(text)
    assert meanings(rows) == [(40, '82', '155'), (40, '82', '156')]
    assert all(text[row.context_start:row.context_end] == text for row in rows)


def test_note_before_shared_title_stays_on_its_own_member():
    """Pins that a note before the shared title refuses only the member it follows."""
    text = '§§ 82.155, 82.156 note of title 40, Code of Federal Regulations'
    rows = find_cfr_citations(text)
    assert meanings(rows) == [(40, '82', '155'), (40, '82', '156')]
    assert [row.refusal for row in rows] == [None, 'note_target_unresolved']

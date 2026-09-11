"""Occurrence coordinates add evidence without changing existing CFR readings."""
from dataclasses import asdict

import pytest
from cfr_parser_oracle import parse_cfr_citations as original_parse

from refspec.registry.citation_grammar import CfrCitation, CfrCitationRange, find_cfr_citations, parse_cfr_citations


@pytest.mark.parametrize('text', [
    '40 CFR 82.154(a)(2)', '14 CFR § 91.107(a)(3)(iii)(B)( 4 )',
    '40 CFR §§ 82.155, 82.156, and 82.157', '7 CFR 15a',
    '40 CFR 60, 61, 63', '41 CFR 60–1', '16 CFR pts. 0-4',
    '3 CFR, 1977 Comp., p. 123', '3 CFR 127 (1981 Comp.)',
    '1345 CFR 1370.31(a)', '040 CFR 060', 'x40 CFR 60', '00 CFR NYD',
    '35 CFR ch. II', 'title 36, Code of Federal Regulations, chapter XII',
    'paragraphs (b)(1) through (4), (c), and (d)(1) of this section',
    '§ 91.107(a)(3)(iii)(B)( 4 )', '5401-5405', '',
    ('( 4 ) Except as provided in § 91.107(a)(3)(iii)(B)( 3 )( iii ) and '
    '§ 91.107(a)(3)(iii)(B)( 3 )( iv ), booster-type child restraint systems '
    '(as defined in Federal Motor Vehicle Safety Standard No. 213 (49 CFR 571.213)), '
    'vest- and harness-type child restraint systems, and lap held child restraints '
    'are not approved for use in aircraft; and'),
])
@pytest.mark.parametrize('policy', ['plural-label', 'always'])
def test_existing_readings_match_frozen_oracle(text, policy):
    expected = original_parse(text, list_expansion=policy)
    # Frozen, named changes: complete compound identity and stated range.
    if text == '41 CFR 60–1':
        assert expected[0].cfr_part == '60'
        expected = (CfrCitation(41, '60-1', part_is_plausible=True),)
    elif text == '16 CFR pts. 0-4':
        assert expected[0].cfr_part is None
        expected = (CfrCitationRange(CfrCitation(16, '0', part_is_plausible=True),
                                     CfrCitation(16, '4', part_is_plausible=True)),)
    assert parse_cfr_citations(text, list_expansion=policy) == expected
    occurrences = find_cfr_citations(text, list_expansion=policy)
    assert tuple(o.citation for o in occurrences) == expected
    assert all(text[o.start:o.end] == o.text for o in occurrences)


def test_repeated_occurrences_preserve_unicode_positions_and_raw_pinpoint_spacing():
    citation = '14 CFR § 91.107(a)(3)(iii)(B)( 4 )'
    text = f'😀 {citation}; then {citation}.'
    first, second = find_cfr_citations(text)
    assert first.start == 2 and second.start == text.rindex(citation)
    assert first.text == second.text == citation
    assert first.pinpoint == second.pinpoint == ('a', '3', 'iii', 'B', '4')
    assert first.end < second.start


def test_list_continuations_keep_the_source_that_supplied_their_title():
    text = '40 CFR §§ 82.155, 82.156, and 82.157'
    first, *rest = find_cfr_citations(text)
    assert first.context_start is None
    assert [o.citation.cfr_section for o in rest] == ['156', '157']
    assert all(text[o.context_start:o.context_end] == first.text for o in rest)


def test_pinpoints_do_not_hide_the_next_member_of_a_plural_list():
    text = '40 CFR §§ 82.155(a), 82.156(b)'
    # Both native readers now walk past pinpoints; the copied old reader
    # proves this is a named coverage change, not unchanged behavior.
    assert len(original_parse(text)) == 1
    assert [c.cfr_section for c in parse_cfr_citations(text)] == ['155', '156']
    first, second = find_cfr_citations(text)
    assert [o.citation.cfr_section for o in (first, second)] == ['155', '156']
    assert [o.pinpoint for o in (first, second)] == [('a',), ('b',)]
    assert text[second.context_start:second.context_end] == first.text


def test_separated_edition_is_not_a_pinpoint_and_invalid_title_stays_inspectable():
    citation, = find_cfr_citations('40 CFR 82.154 (2025)')
    assert not citation.pinpoint and citation.text == '40 CFR 82.154'
    damaged, = find_cfr_citations('1345 CFR 1370.31(a)')
    assert not damaged.citation.title_is_possible
    assert damaged.text == '1345 CFR 1370.31(a)'


def test_serialized_existing_identity_fields_do_not_change():
    citation, = parse_cfr_citations('40 CFR 82.154(a)(2)')
    assert asdict(citation) == {'cfr_title': 40, 'cfr_part': '82', 'cfr_section': '154',
                               'title_is_possible': True, 'part_is_plausible': True}

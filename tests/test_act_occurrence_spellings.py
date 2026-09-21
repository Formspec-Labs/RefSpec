"""Reuse a publisher-spelling operation while preserving literal source names."""
import re

import pytest
from act_occurrence_spelling_oracle import find_act_relative_occurrences as original
from refspec.registry.citation_grammar import find_act_relative_occurrences, act_name_with_trailing_year

NAMES = {'pipes act of 2020', 'secure 2.0 act of 2022', 'clean air act', 'faa reauthorization act of 2018'}


@pytest.mark.parametrize('text, name, key, section', [
    ('sec. 103 of the 2020 PIPES Act', '2020 PIPES Act', 'pipes act of 2020', '103'),
    ('The 2020 PIPES Act section 103', 'The 2020 PIPES Act', 'pipes act of 2020', '103'),
    ('sec. 303 of the 2022 SECURE 2.0 Act', '2022 SECURE 2.0 Act', 'secure 2.0 act of 2022', '303'),
    ('sec. 403 of the 2018 FAA Reauthorization Act', '2018 FAA Reauthorization Act', 'faa reauthorization act of 2018', '403'),
])
def test_year_first_indexed_name_retains_source_name_and_offsets(text, name, key, section):
    """Pins that year-first names the frozen oracle misses resolve while literal source spelling and offsets survive."""
    assert original(text, act_names=NAMES) == ()
    row, = find_act_relative_occurrences(text, act_names=NAMES)
    assert (row.citation.act_name, row.citation.act_key, row.citation.section) == (name, key, section)
    assert row.text == text[row.start:row.end] == text


@pytest.mark.parametrize('text', [
    'SECURE 2.0 Act of 2022, sec. 127', 'SECURE 2.0 Act of 2022, sec. 303',
    'Clean Air Act section 111(d)', '2019 PIPES Act section 103',
    '2020 Imaginary Act section 103', '2020 PIPES Amendments Act section 103',
    '2020 PIPES Act. Section 103 is somewhere else.',
    'Section 103. The 2020 PIPES Act is mentioned separately.',
    '2020 PIPES\n\nAct section 103',
])
def test_existing_readings_and_rejections_do_not_change(text):
    """Pins verdict identity with the frozen oracle on already-read names, near-miss acts, and paragraph-split names."""
    assert find_act_relative_occurrences(text, act_names=NAMES) == original(text, act_names=NAMES)


def test_exact_indexed_spelling_precedes_a_reordered_candidate():
    """Pins that a literal indexed key ('2020 pipes act') wins over the reordered year-spelling key."""
    names = {'2020 pipes act': 'literal-key', 'pipes act of 2020': 'reordered-key'}
    row, = find_act_relative_occurrences('2020 PIPES Act section 103', act_names=names)
    assert row.citation.act_key == 'literal-key'


@pytest.mark.parametrize('name', ['2020 PIPES Act', 'the 2018 FAA Reauthorization Act',
    'Clean Air Act', 'SECURE 2.0 Act of 2022', '17th Act', '2020 ', '2020\nPIPES Act'])
def test_shared_operator_matches_the_frozen_existing_operator(name):
    """Pins act_name_with_trailing_year against the regex copied from _act_prose_recoveries, including None cases."""
    # Copied from _act_prose_recoveries before extracting its two identical uses.
    old = re.compile(r'^\s*(?:the\s+)?((?:18|19|20)\d{2})\s+(\S.*)$', re.IGNORECASE).match(name)
    expected = f'{old.group(2)} of {old.group(1)}' if old else None
    assert act_name_with_trailing_year(name) == expected

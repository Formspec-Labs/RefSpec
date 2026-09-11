"""Compilation pages remain locators, with independent old parsing checks."""
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from refspec.registry import citation_grammar as grammar
from compilation_parser_oracle import (
    _excise_compilations as old_excise,
    parse_eo_compilation_locators as old_locators,
)

CASES = json.loads((Path(__file__).parent / 'fixtures/compilation-occurrences.json').read_text())['cases']
YEAR_FIRST = [
    '3 CFR, 1977 Comp., p. 123', '3 CFR 1949 through 1953 Comp',
    '3 CFR 1966--1970 p 939', '3 CFR; 1982 Comp., 166; 8 CFR part 2',
    '3 CFR 1987, 1987 Comp., p. 235', '3 CFR 1987, p. 235',
    '3 CFR, 1950 Supp.', '3 CFR, 1949-53 Comp, 1002',
    '3 CFR, 1971-1075 Comp., p. 793', '3 CFR 1981',
]
ORDINARY = [
    '3 CFR part 100', '3 CFR 100 (1981 ed.)', '3 CFR 100 (1981–1982)',
    '4 CFR 127 (1981 Comp.)', '13 CFR 127 (1981 Comp.)',
    '3 CFR 127 (1981 Company)', '3 CFR 127 (1981 p. 23)',
]


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
@pytest.mark.parametrize('mutation', ['original', 'prefix', 'linebreaks', 'ascii-dash', 'lowercase'])
def test_printed_court_locators_preserve_fields_and_exact_source(case, mutation):
    text = case['text']
    if mutation == 'prefix':
        text = '🧭 Example: ' + text
    elif mutation == 'linebreaks':
        text = text.replace(' ', '\r\n')
    elif mutation == 'ascii-dash':
        text = text.replace('–', '-')
    elif mutation == 'lowercase':
        text = text.lower()
    found, = grammar.find_eo_compilation_locators(text)
    assert asdict(found.locator) == case['expected']
    assert found.refusal is None
    assert found.text == text[found.start:found.end]
    assert grammar.parse_cfr_citations(text) == ()
    assert old_locators(text) == ()  # Deliberate divergence: old grammar missed this form.
    normalized = grammar._normalize_dashes(text)
    assert grammar._excise_compilations(normalized) == (
        text[:found.start] + ' ' * (found.end - found.start) + text[found.end:]
    )
    assert old_excise(normalized) != grammar._excise_compilations(normalized)


@pytest.mark.parametrize('text', YEAR_FIRST + ORDINARY)
@pytest.mark.parametrize('mutation', ['original', 'prefix', 'linebreaks', 'unicode-dash', 'lowercase'])
def test_old_volume_forms_and_non_locators_agree_with_copied_checks(text, mutation):
    if mutation == 'prefix':
        text = '🧭 ' + text + '; 40 CFR 60.'
    elif mutation == 'linebreaks':
        text = text.replace(' ', '\n')
    elif mutation == 'unicode-dash':
        text = text.replace('-', '–')
    elif mutation == 'lowercase':
        text = text.lower()
    assert grammar.parse_eo_compilation_locators(text) == old_locators(text)
    normalized = grammar._normalize_dashes(text)
    assert grammar._excise_compilations(normalized) == old_excise(normalized)


@pytest.mark.parametrize('text', ORDINARY)
def test_a_volume_label_is_required_in_the_page_first_form(text):
    assert grammar.find_eo_compilation_locators(text) == ()
    assert grammar.parse_cfr_citations(text)


def test_both_page_orderings_preserve_range_endpoints():
    a, = grammar.parse_eo_compilation_locators('3 CFR 60–61 (1971–1975 Comp.)')
    b, = grammar.parse_eo_compilation_locators('3 CFR, 1971–1975 Comp., pp. 60–61')
    assert a == b
    assert (a.page, a.page_end, a.compilation_start, a.compilation_end) == ('60', '61', '1971', '1975')


def test_unclosed_parenthetical_retains_the_refusal_and_does_not_become_a_part():
    text = '3 CFR 127 (1981 Comp.'
    found, = grammar.find_eo_compilation_locators(text)
    assert found.refusal == 'compilation_parenthetical_unclosed'
    assert found.text == text
    assert found.locator.page == '127'
    assert grammar.parse_cfr_citations(text) == ()


def test_repeats_and_neighbors_remain_distinct():
    quote = '3 CFR 127 (1981 Comp.)'
    text = f'{quote}; 3 CFR 100; 5 USC 552; {quote}.'
    first, second = grammar.find_eo_compilation_locators(text)
    assert first.locator == second.locator and first.start != second.start
    assert first.text == second.text == quote
    assert [c.cfr_part for c in grammar.parse_cfr_citations(text)] == ['100']
    assert [c.citation.usc_section for c in grammar.find_usc_citations(text)] == ['552']


def test_compilation_word_does_not_match_the_prefix_of_an_ordinary_word():
    # Deliberate correction of the old year-first token boundary.
    text = '3 CFR 1981 Company'
    assert old_locators(text)
    assert grammar.find_eo_compilation_locators(text) == ()
    assert grammar.parse_cfr_citations(text)[0].cfr_part == '1981'

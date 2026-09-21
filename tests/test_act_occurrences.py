"""Exact act occurrences: spans, pinpoints, division fencing, and verdict identity with the frozen matcher."""
import json
from pathlib import Path

import pytest

from refspec.registry import citation_grammar as grammar
from act_parser_oracle import find_act_relative_citations as before

ROWS = json.loads((Path(__file__).parent / 'fixtures/act-occurrences.json').read_text())['cases']
NAMES = {r['act_key'] for r in ROWS if r['act_key']} | {'clean air act', 'social security act'}
ADJACENT = {
    'Sec 508 (b)(7)(A) Federal Crop Insurance Reform Act of 1994',
    'Sec 508(b)(7)(A) Federal Crop Insurance Reform Act of 1994',
}


def occurrences(text, names=NAMES):
    """Return the current reader's act-relative occurrences for a text."""
    return grammar.find_act_relative_occurrences(text, act_names=names)


@pytest.mark.parametrize('row', ROWS, ids=lambda r:r['rin'])
def test_real_fields_and_mutations_preserve_legacy_except_declared_additions(row):
    """Real rows plus three mutations keep verdict identity with the frozen matcher.

    The two ADJACENT spellings are the declared exception: the legacy matcher
    found nothing there and the new reader returns the act.
    """
    raw = row['authority_text']
    for text in (raw, '🧭 ' + raw, raw.replace(' ', '\n'), raw + '; separate statement.'):
        old = before(text, act_names=NAMES)
        new = grammar.find_act_relative_citations(text, act_names=NAMES)
        if raw in ADJACENT:
            assert not old
            assert [(c.act_key,c.section,c.division) for c in new] == [('federal crop insurance reform act of 1994','508',None)]
        else:
            assert new == old
        for item in occurrences(text):
            assert text[item.start:item.end] == item.text
            assert item.citation in new


def test_repeats_pinpoints_and_line_breaks_survive():
    """Pins that one citation repeated across a line break yields two spans, one citation, one pinpoint."""
    text = '🧭 Clean Air\nAct section 111(d); then Clean Air Act section 111(d).'
    first, second = occurrences(text)
    assert first.start < first.end < second.start < second.end
    assert first.text == 'Clean Air\nAct section 111(d)'
    assert second.text == 'Clean Air Act section 111(d)'
    assert first.pinpoint == second.pinpoint == ('d',)
    assert first.citation == second.citation
    assert len(grammar.find_act_relative_citations(text, act_names=NAMES)) == 1


def test_reversed_and_spaced_pinpoints():
    """Pins that a spaced reversed pinpoint "(d)( 2 )" still reads ('d','2') and keeps the full span."""
    item, = occurrences('Section 1886(d)( 2 ) of the Social Security Act.')
    assert item.text == 'Section 1886(d)( 2 ) of the Social Security Act'
    assert item.pinpoint == ('d','2')


@pytest.mark.parametrize('neighbor, old_division', [
    (' A different provision names division B.', 'B'),
    ('; division B of another act.', 'B'),
    ('\n\nDivision B is unrelated.', None),
])
def test_unrelated_division_is_not_borrowed(neighbor, old_division):
    """Pins that a division label in an unrelated neighbor is not borrowed into the citation.

    The old lowercase matcher did borrow it; uppercase is the no-change control.
    """
    text = 'Clean Air Act section 111.' + neighbor
    old, = before(text, act_names=NAMES)
    item, = occurrences(text)
    # The old lowercase matcher borrowed the label; uppercase is a no-change control.
    assert old.division == old_division
    assert item.citation.division is None
    assert item.text == 'Clean Air Act section 111'


def test_explicit_division_of_named_act_remains_in_citation():
    """Pins that an explicit "Division B of the Clean Air Act" keeps B, including across a long gap."""
    item, = occurrences('Division B of the Clean Air Act section 111.')
    assert item.citation.division == 'B'
    assert item.text == 'Division B of the Clean Air Act section 111'
    spaced = 'division B of the' + (' ' * 90) + 'Clean Air Act section 111'
    item, = occurrences(spaced)
    assert item.citation.division == 'B'
    assert item.text == spaced


@pytest.mark.parametrize('qualifier', ['(2025)', '(as amended)'])
def test_short_surrounding_qualifier_does_not_become_a_pinpoint(qualifier):
    """Pins that a short parenthetical qualifier such as "(2025)" is not read as a pinpoint."""
    text = f'Section 111 {qualifier} of the Clean Air Act'
    assert grammar.find_act_relative_citations(text, act_names=NAMES) == before(text, act_names=NAMES)
    item, = occurrences(text)
    assert item.text == text
    assert item.pinpoint == ()


@pytest.mark.parametrize('text', [
    'Imaginary Marshmallow Act section 111.',
    'Section 111 of an unknown act.',
    'Clean Air Act is discussed. Section 111 applies elsewhere.',
    'Clean Air Act. Section 111 applies elsewhere.',
    'Clean Air Act\n\nSection 111 applies elsewhere.',
    'Section 111\n\nClean Air Act',
])
def test_unknown_or_separate_name_does_not_become_a_citation(text):
    """Pins that an unknown act name or a name across a sentence/paragraph boundary yields no occurrence."""
    assert not occurrences(text)


def test_mapping_keys_remain_canonical():
    """Pins that a Mapping of spelling variants still publishes the canonical popular-name key."""
    item, = occurrences('sec. 204 of the Motor Carrier Act of 1935', {'motor carrier act of 1935':'motor carrier act, 1935'})
    assert item.citation.act_key == 'motor carrier act, 1935'
    assert item.text == 'sec. 204 of the Motor Carrier Act of 1935'

"""Source-only scope tails: constructed diagnostics and publisher controls."""
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from cfr_scope_tail_oracle import find_cfr_citations as before_find
from cfr_scope_tail_oracle import parse_cfr_citations as before_parse

from refspec.registry.citation_grammar import find_cfr_citations, parse_authority_citation, parse_cfr_citations
from refspec.registry.ecfr import read_text

FIXTURES = Path(__file__).with_name('fixtures')
# Frozen deliberate divergences: each named item retains an unsupported marker.
TAILS = {
    'note': (' note', 'note_target_unresolved'),
    'notes': (' notes', 'note_target_unresolved'),
    'uppercase': (', NOTE', 'note_target_unresolved'),
    'preceding': (' preceding note', 'note_target_unresolved'),
    'following': (' following notes', 'note_target_unresolved'),
    'wrapped_note': ('\n note', 'note_target_unresolved'),
    'open_ended': (' et seq.', 'open_ended_reference_unresolved'),
    'open_no_period': (' et seq', 'open_ended_reference_unresolved'),
    'open_comma': (', et seq.', 'open_ended_reference_unresolved'),
    'following_open': (' and following', 'open_ended_reference_unresolved'),
    'ff': (' ff.', 'open_ended_reference_unresolved'),
    'wrapped_open': ('\n et\nseq.', 'open_ended_reference_unresolved'),
    'note_then_open': (' note et seq.', 'note_target_unresolved'),
}
ANCHORS = ['49 CFR 390.5', '49 CFR 390.5(a)(1)',
           '49 CFR §§ 390.5(a) through 391.1(b)', '49 CFR part 390, subpart A']
NEGATIVE_TAILS = [' notes that the rule applies.', ' note that the rule applies.',
                  ' notes how it applies.', ' notes why it applies.',
                  ' notes whether it applies.', ' noteworthy changes follow.',
                  '. Note the change.', '. Et seq. is an abbreviation.',
                  '\n\nNote the change.', '\r\n \r\nnotes follow.',
                  '\n\net seq.', '\n\nfollowing note',
                  ' et sequence', ' fff.', '; 40 CFR 82.158',
                  ' and follows the process.']


@pytest.mark.parametrize('name', TAILS)
@pytest.mark.parametrize('anchor', ANCHORS)
@pytest.mark.parametrize('expand', [True, False])
def test_written_scope_is_retained_without_promoting_a_target(name, anchor, expand):
    tail, reason = TAILS[name]
    text = anchor + tail
    before, = before_find(text, expand_qualifiers=expand)
    after, = find_cfr_citations(text, expand_qualifiers=expand)
    assert before.refusal is None
    assert after.refusal == reason
    assert after.text == text and text[after.start:after.end] == after.text
    assert after.citation == before.citation
    assert after.pinpoint == before.pinpoint
    assert after.range_end_pinpoint == before.range_end_pinpoint
    assert after.subpart == before.subpart
    assert parse_cfr_citations(text) == before_parse(text)
    authority, = parse_authority_citation(text)
    assert authority.cfr_refusal == reason


@pytest.mark.parametrize('tail', NEGATIVE_TAILS)
@pytest.mark.parametrize('anchor', ANCHORS)
def test_prose_and_boundaries_keep_the_existing_source_reading(tail, anchor):
    text = anchor + tail
    assert find_cfr_citations(text) == before_find(text)
    assert parse_cfr_citations(text) == before_parse(text)


@pytest.mark.parametrize('tail,reason', [TAILS['note'], TAILS['open_ended']])
def test_qualifier_on_last_list_item_does_not_erase_other_items(tail, reason):
    text = '49 CFR §§ 390.5(a), 390.6(b)' + tail
    old = before_find(text)
    first, last = find_cfr_citations(text)
    assert first == old[0]
    assert last.refusal == reason and last.pinpoint == ('b',)
    assert last.context_start == old[1].context_start and last.context_end == old[1].context_end
    assert text[last.start:last.end] == last.text
    assert last.end == len(text)
    assert parse_cfr_citations(text) == before_parse(text)


def test_qualified_list_member_keeps_next_explicit_coordinate_and_neighbor():
    text = '49 CFR §§ 390.5 note, 390.6(b); 40 CFR 82.158'
    first, second, third = find_cfr_citations(text)
    assert first.refusal == 'note_target_unresolved'
    assert first.text == '49 CFR §§ 390.5 note'
    assert second.citation.cfr_section == '6' and second.pinpoint == ('b',)
    assert second.refusal is None and third.refusal is None
    assert text[second.context_start:second.context_end] == first.text
    assert third.text == '40 CFR 82.158'
    assert parse_cfr_citations(text) == before_parse(text)


def test_collapsed_subpart_list_keeps_final_refusal():
    text = '49 CFR part 390, subparts A and B et seq.'
    first, last = find_cfr_citations(text)
    assert first.refusal is None
    assert last.subpart == 'B' and last.refusal == 'open_ended_reference_unresolved'
    collapsed, = find_cfr_citations(text, expand_qualifiers=False)
    assert collapsed.text == text and collapsed.refusal == last.refusal
    assert parse_cfr_citations(text) == before_parse(text)


def test_previous_ambiguity_is_not_overwritten():
    text = '49 CFR parts 390 and 391, subpart A note'
    _, last = find_cfr_citations(text)
    assert last.qualifier_status == 'ambiguous_part_scope'
    assert last.refusal == 'note_target_unresolved'
    assert parse_authority_citation(text)[-1].cfr_refusal is not None


SAVED = [(item['id'], item['raw']) for item in json.loads((FIXTURES / 'cfr-subparts.json').read_text())]
SAVED += [('range-' + item['id'], item['text']) for item in json.loads((FIXTURES / 'cfr-ranges.json').read_text())]
for path in sorted((FIXTURES / 'ecfr-text').glob('*.xml')):
    xml = path.read_bytes()
    SAVED.extend([(path.stem + '-xml', xml.decode()), (path.stem + '-readable', read_text(xml)['text'])])


@pytest.mark.parametrize('case,text', SAVED, ids=[case for case, _ in SAVED])
@pytest.mark.parametrize('mutation', ['original', 'wrapped', 'neighbor', 'paragraph'])
@pytest.mark.parametrize('expand', [True, False])
def test_saved_sources_and_boundary_mutations_agree_with_copied_callback(case, text, mutation, expand):
    if mutation == 'wrapped':
        text = text.replace(' ', '\n')
    elif mutation == 'neighbor':
        text += '; 49 CFR 390.5(a). Notes that follow describe another subject.'
    elif mutation == 'paragraph':
        text += '\n\nNote that context matters.'
    assert [asdict(row) for row in find_cfr_citations(text, expand_qualifiers=expand)] == [
        asdict(row) for row in before_find(text, expand_qualifiers=expand)]
    assert parse_cfr_citations(text) == before_parse(text)
    assert parse_cfr_citations(text, list_expansion='always') == before_parse(text, list_expansion='always')


def test_note_is_not_reinterpreted_as_a_verb_across_a_paragraph():
    text = '49 CFR 390.5 note\n\nThat provision has a separate context.'
    row, = find_cfr_citations(text)
    assert row.text == '49 CFR 390.5 note'
    assert row.refusal == 'note_target_unresolved'

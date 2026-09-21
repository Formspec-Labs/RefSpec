"""Readable source boundaries preserve XML text and publisher element identity."""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from refspec.registry.uslm import USLM_NS, read_text

FIXTURES = Path(__file__).parent / 'fixtures/uslm-source-links'


def check(xml):
    """Assert the readable text equals the source text and the map tiles it exactly, then return the result."""
    result = read_text(xml)
    original = ''.join(ET.fromstring(xml).itertext())
    assert result['source_text'] == original
    assert ''.join(result['text'][p['start']:p['end']] for p in result['source_map'] if p['kind']=='source') == original
    cursor = 0
    for part in result['source_map']:
        assert part['start'] == cursor
        cursor = part['end']
        quote = result['text'][part['start']:part['end']]
        if part['kind'] == 'source':
            assert quote == original[part['source_start']:part['source_end']]
        else:
            assert quote == part['text'] and quote.isspace()
    assert cursor == len(result['text'])
    return result


@pytest.mark.parametrize('name', ['title-05-s423', 'title-42-s242c', 'fresh-title-05-pair'])
def test_publisher_sources_match_frozen_readable_text(name):
    """Pinned XML fixtures must reproduce their frozen readable-text files exactly."""
    result = check((FIXTURES/(name+'.xml')).read_bytes())
    assert result['text'] == (FIXTURES/(name+'.txt')).read_text()


@pytest.mark.parametrize(('body','expected'), [
    ('<p>non<inline>discretionary</inline>, café &amp; <b>🦉</b>—x.\r\nNext.</p>', 'nondiscretionary, café & 🦉—x.\nNext.'),
    ('<subsection><num>(b)</num><heading> Functions</heading><chapeau>The Secretary shall—</chapeau></subsection>', '(b) Functions The Secretary shall—'),
    ('<paragraph><heading>Rule </heading><content>applies.</content></paragraph>', 'Rule applies.'),
    ('<table><tr><th><p>A</p></th><th><p>B</p></th></tr><tr><td><p>One</p><p>continued</p></td><td><p>Two</p></td></tr></table>', 'A\tB\n\nOne\n\ncontinued\tTwo'),
    ('<p>Rule<ref class="footnoteRef">1</ref><note type="footnote"><num>1</num> So in original.</note>Next.</p>', 'Rule1\n\n1 So in original.\n\nNext.'),
])
def test_source_layout_and_inline_counterexamples(body, expected):
    """Inline elements, spacing, tables and footnotes normalise exactly as pinned, including the counterexamples."""
    result = check(f'<uscDoc xmlns="{USLM_NS}">{body}</uscDoc>'.encode())
    assert result['text'] == expected


def test_repeated_and_empty_nodes_do_not_lose_their_locations():
    """Repeated nodes keep distinct locations, and an empty node keeps a
    zero-width source span with no readable span.
    """
    xml = f'<uscDoc xmlns="{USLM_NS}"><p>Same<ref href="/us/usc/t5/s1"/></p><p>Same</p></uscDoc>'.encode()
    result = check(xml)
    first = result['nodes']['/*[1]/*[1]']
    second = result['nodes']['/*[1]/*[2]']
    assert first['start'] != second['start']
    empty = result['nodes']['/*[1]/*[1]/*[1]']
    assert empty['source_start'] == empty['source_end']
    assert 'start' not in empty


def test_foreign_root_is_refused():
    """A root that is not a USLM uscDoc is refused."""
    with pytest.raises(ValueError, match='USLM uscDoc'):
        read_text(b'<html><p>Other format</p></html>')

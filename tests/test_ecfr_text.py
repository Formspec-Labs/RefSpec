"""Exact source maps, readable boundaries, native attributes and legacy parity."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from uslm_text_oracle import read_text as old_uslm_read_text

from refspec.registry import ecfr, uslm

FIXTURES = Path(__file__).parent / 'fixtures'

def mapped(xml, reader):
    """Read xml and assert exact source maps, node spans and text before returning the result."""
    result = reader(xml)
    original = ''.join(ET.fromstring(xml).itertext())
    assert result['source_text'] == original
    assert ''.join(result['text'][p['start']:p['end']] for p in result['source_map'] if p['kind'] == 'source') == original
    cursor = 0
    for part in result['source_map']:
        assert part['start'] == cursor
        cursor = part['end']
        value = result['text'][part['start']:part['end']]
        if part['kind'] == 'source':
            assert value == original[part['source_start']:part['source_end']]
        else:
            assert value == part['text'] and value.isspace()
    assert cursor == len(result['text'])
    for path, node in result['nodes'].items():
        actual = ET.fromstring(xml)
        for position in path.split('/')[2:]:
            actual = actual[int(position[2:-1]) - 1]
        assert ''.join(actual.itertext()) == original[node['source_start']:node['source_end']]
    return result

@pytest.mark.parametrize('name', ['title-05-s423', 'title-42-s242c', 'fresh-title-05-pair'])
@pytest.mark.parametrize('mutation', ['original', 'no-newlines', 'inline', 'empty-cells', 'notes'])
def test_uslm_matches_copied_engine_on_real_sources_and_mutations(name, mutation):
    """Pins uslm.read_text against the copied old engine on three real sources and four XML mutations."""
    xml = (FIXTURES/'uslm-source-links'/f'{name}.xml').read_bytes()
    original = xml
    if mutation == 'no-newlines':
        xml = xml.replace(b'\n', b'')
    if mutation == 'inline':
        xml = xml.replace(b'</uscDoc>', b'<p>non<i>discretionary</i> &amp; caf&#233;.</p></uscDoc>')
    if mutation == 'empty-cells':
        xml = xml.replace(b'</uscDoc>', b'<table><tr><td/><td>B</td><td/></tr><tr><td>A</td><td>C</td></tr></table></uscDoc>')
    if mutation == 'notes':
        xml = xml.replace(b'</uscDoc>', b'<note><heading>Note</heading><p>Text<br/>next.</p></note></uscDoc>')
    if mutation != 'original':
        assert xml != original
    assert uslm.read_text(xml) == old_uslm_read_text(xml)

@pytest.mark.parametrize('pin', json.loads((FIXTURES/'ecfr-text/pins.json').read_text()))
def test_actual_ecfr_bodies_preserve_all_source_and_native_selectors(pin):
    """Pins each eCFR body's digest and byte pins, root native attributes and source-specific markers."""
    xml = (FIXTURES/'ecfr-text'/pin['file']).read_bytes()
    assert hashlib.sha256(xml).hexdigest() == pin['sha256'] and len(xml) == pin['bytes']
    result = mapped(xml, ecfr.read_text)
    assert result['nodes']['/*[1]']['attributes'] == pin['native_attributes']
    assert all('identifier' not in n for n in result['nodes'].values())
    if pin['file'].startswith('rail'):
        assert 'again suspended indefinitely' in result['text']
        assert any(n['tag']=='EFFDNOT' for n in result['nodes'].values())
    if pin['file'].startswith('refrigerant'):
        assert '\t' in result['text']
        assert any(n['attributes'].get('colspan') == '2' for n in result['nodes'].values())
        assert any(n['tag']=='CAPTION' for n in result['nodes'].values())

@pytest.mark.parametrize(('body', 'expected'), [
    ('<HEAD>Heading</HEAD><P>One</P><P>Two</P>', 'Heading\n\nOne\n\nTwo'),
    ('<P>non<I>discretionary</I>, A<E T="03">B</E>C &amp; caf&#233;.</P>', 'nondiscretionary, ABC & café.'),
    ('<P>A<br/>B<BR/>C<Br/>D</P>', 'A\n\nB\n\nC\n\nD'),
    ('<TABLE><TR><TD/><TD>B</TD><TD/></TR><TR><TD>A</TD><TD/><TD>C</TD></TR></TABLE>', '\tB\t\n\nA\t\tC'),
    ('<TABLE><TR><TD>A</TD>\t<TD>B</TD></TR></TABLE>', 'A\tB'),
    ('<TABLE><TR><TD><P>A</P><P>continued</P></TD><TD>B</TD></TR></TABLE>', 'A\n\ncontinued\tB'),
    ('<EDNOTE><HED>Editorial Note:</HED><PSPACE>Keep this.</PSPACE></EDNOTE><EFFDNOT><HED>Effective Date:</HED><P>Suspended.</P></EFFDNOT>', 'Editorial Note:\n\nKeep this.\n\nEffective Date:\n\nSuspended.'),
])
def test_readable_boundary_controls(body, expected):
    """Pins the readable text across heading, inline, br, table and note boundaries."""
    xml = ('<DIV8 N="1.1" TYPE="SECTION">'+body+'</DIV8>').encode()
    assert mapped(xml, ecfr.read_text)['text'] == expected

@pytest.mark.parametrize('xml', [b'<html><p>text</p></html>', b'<DIV8><P>untyped</P></DIV8>', b'<uscDoc/>', b'<DIV8 TYPE="SECTION">'])
def test_wrong_or_malformed_input_refuses(xml):
    """Pins refusal (ValueError or ParseError) for wrong-profile and malformed XML."""
    with pytest.raises((ValueError, ET.ParseError)):
        ecfr.read_text(xml)

def test_native_root_title_and_empty_source_remain_uninferred():
    """Pins that root title attributes are kept verbatim and an empty paragraph contributes no inferred span."""
    result = mapped(b'<ECFR><DIV1 N="49" TYPE="TITLE"><DIV8 N="390.5" TYPE="SECTION"><P/></DIV8></DIV1></ECFR>', ecfr.read_text)
    assert result['nodes']['/*[1]/*[1]']['attributes'] == {'N':'49','TYPE':'TITLE'}
    assert 'start' not in result['nodes']['/*[1]/*[1]/*[1]/*[1]']
    assert result['text'] == result['source_text'] == ''


def test_shared_dispatch_parses_once_without_changing_profile_output(monkeypatch):
    """Pins that the shared dispatch parses the XML once and still reports the ecfr-block-boundaries/1 method."""
    from refspec.registry import xml_text
    original = xml_text.parse_xml
    calls = []
    def parse(xml, **kwargs):
        calls.append(xml)
        return original(xml, **kwargs)
    monkeypatch.setattr(xml_text, 'parse_xml', parse)
    xml = b'<DIV8 N="1.1" TYPE="SECTION"><P>Rule.</P></DIV8>'
    assert xml_text.read_text(xml)['method'] == 'ecfr-block-boundaries/1'
    assert calls == [xml]

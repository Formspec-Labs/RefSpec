"""Qualify shared parsing against the frozen complete RefSpec text formatter."""

from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest
from xml_text_oracle import read_text as old_read_text

from refspec.registry import xml_text

FIXTURES = Path(__file__).parent / 'fixtures'
RETAINED = (
    ('uslm', 'uslm-source-links/fresh-title-05-pair.xml'),
    ('uslm', 'uslm-source-links/title-05-s423.xml'),
    ('uslm', 'uslm-source-links/title-42-s242c.xml'),
    ('ecfr', 'ecfr-text/alcohol-definition-0.xml'),
    ('ecfr', 'ecfr-text/rail-definition-0.xml'),
    ('ecfr', 'ecfr-text/refrigerant-equipment-0.xml'),
)


@pytest.mark.parametrize(('profile', 'path'), RETAINED)
@pytest.mark.parametrize('mutation', ['original', 'no-newlines', 'crlf', 'comments', 'processing-instructions'])
def test_retained_sources_preserve_complete_formatter_result(profile, path, mutation):
    """Retained real sources, including newline, comment and PI mutations, yield the frozen formatter result."""

    xml = (FIXTURES / path).read_bytes()
    if mutation == 'no-newlines':
        xml = xml.replace(b'\n', b'')
    elif mutation == 'crlf':
        xml = xml.replace(b'\n', b'\r\n')
    elif mutation == 'comments':
        xml = xml.replace(b'</', b'<!-- retained boundary --> </')
    elif mutation == 'processing-instructions':
        xml = xml.replace(b'</', b'<?boundary retained?></')
    assert xml_text.read_text(xml, profile=profile) == old_read_text(xml, profile=profile)


@pytest.mark.parametrize('body', [
    '<P>caf&#233; &amp; 🦉<E>A</E>tail</P>',
    '<P>a<![CDATA[b<c]]><!-- ignored -->d<?instruction text?>e</P>',
    '<P>A\r\nB\rC</P>',
    '<q:P xmlns:q="urn:unknown" q:a="literal">A<q:TD colspan="02"/>B</q:P>',
    '<TABLE><TR><TD/><TD>B</TD><TD/></TR><TR><TD>A</TD><TD/><TD>C</TD></TR></TABLE>',
    '<P>A<EMPTY/>B</P><P>A</P>',
    '<P>' + 'A' * 65520 + '&amp;<E>suffix</E></P>',
])
def test_text_nodes_attributes_and_source_maps_survive_parser_boundaries(body):
    """Entity, CDATA, CRLF, unknown-namespace, table, self-closing and long-text edge cases match the frozen reader."""

    xml = ('<ECFR>' + body + '</ECFR>').encode()
    assert xml_text.read_text(xml) == old_read_text(xml)


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'iso-8859-1'])
def test_declared_encoding_preserves_decoded_codepoints(encoding):
    """A declared encoding yields decoded codepoints and source offsets identical to the frozen reader."""

    xml = (f'<?xml version="1.0" encoding="{encoding}"?><ECFR><P>café</P></ECFR>').encode(encoding)
    actual = xml_text.read_text(xml)
    assert actual == old_read_text(xml)
    assert actual['source_text'] == 'café'
    assert actual['nodes']['/*[1]/*[1]']['source_end'] == 4


@pytest.mark.parametrize('order', ['le', 'be'])
def test_utf16_byte_order_without_bom_keeps_declared_encoding_parity(order):
    """UTF-16 without a BOM parses identically to the frozen reader in either byte order."""

    xml = '<?xml version="1.0" encoding="UTF-16"?><ECFR><P>café</P></ECFR>'.encode('utf-16-' + order)
    assert xml_text.read_text(xml) == old_read_text(xml)


def test_inert_external_doctype_is_not_loaded():
    """An external DOCTYPE is tolerated without fetching the declared DTD."""

    xml = b'<!DOCTYPE ECFR SYSTEM "https://example.invalid/not-fetched.dtd"><ECFR><P>A</P></ECFR>'
    assert xml_text.read_text(xml) == old_read_text(xml)


@pytest.mark.parametrize(('name', 'xml'), [
    ('internal-empty-subset', b'<!DOCTYPE ECFR []><ECFR><P>A</P></ECFR>'),
    ('internal-entity', b'<!DOCTYPE ECFR [<!ENTITY word "source text">]><ECFR><P>&word;</P></ECFR>'),
    ('internal-default-attribute', b'<!DOCTYPE ECFR [<!ATTLIST P N CDATA "123">]><ECFR><P>A</P></ECFR>'),
])
def test_named_internal_dtd_refusals_replace_old_acceptance(name, xml):
    """The frozen reader accepted internal DTD subsets; the shared reader refuses all three shapes."""

    assert old_read_text(xml)['source_text']
    with pytest.raises(ValueError, match='permits only an inert external DOCTYPE'):
        xml_text.read_text(xml)


def test_named_depth_refusal_replaces_old_acceptance():
    """Depth 256 is the bound: 255 nested elements pass and the frozen reader accepted one level more."""

    assert xml_text.MAX_XML_DEPTH == 256
    accepted = b'<ECFR>' + b'<P>' * 255 + b'x' + b'</P>' * 255 + b'</ECFR>'
    assert xml_text.read_text(accepted) == old_read_text(accepted)
    refused = b'<ECFR>' + accepted + b'</ECFR>'
    assert old_read_text(refused)['source_text'] == 'x'
    with pytest.raises(ValueError, match='nesting depth'):
        xml_text.read_text(refused)


def test_named_byte_refusal_uses_inclusive_input_bound(monkeypatch):
    """Input exactly at the byte bound passes; one byte more refuses where the frozen reader accepted."""

    assert xml_text.MAX_XML_BYTES == 256 * 1024 * 1024
    xml = b'<ECFR><P>A</P></ECFR>'
    monkeypatch.setattr(xml_text, 'MAX_XML_BYTES', len(xml))
    assert xml_text.read_text(xml) == old_read_text(xml)
    oversized = xml + b' '
    assert old_read_text(oversized)['source_text'] == 'A'
    with pytest.raises(ValueError, match='within max_bytes'):
        xml_text.read_text(oversized)


@pytest.mark.parametrize('xml', [b'', b'<ECFR><P>', b'<ECFR><P>&unknown;</P></ECFR>', b'<html><P>A</P></html>'])
def test_both_readers_refuse_invalid_source_or_wrong_profile(xml):
    """Empty, unclosed, unknown-entity and wrong-root inputs are refused by both readers."""

    with pytest.raises((ValueError, ParseError)):
        old_read_text(xml)
    with pytest.raises(ValueError):
        xml_text.read_text(xml)


@pytest.mark.parametrize('profile', ['unknown', 'uslm'])
def test_shared_parser_does_not_relax_profile_selection(profile):
    """An unknown profile and a profile the source is not, are refused by both readers."""

    xml = b'<ECFR><P>A</P></ECFR>'
    with pytest.raises(ValueError):
        old_read_text(xml, profile=profile)
    with pytest.raises(ValueError):
        xml_text.read_text(xml, profile=profile)

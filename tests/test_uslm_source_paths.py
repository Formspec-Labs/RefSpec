"""Default-reader parity and exact publisher occurrence locations.

Every fixture and mutation runs through the default uslm reader and the copied
uslm_reference_oracle: readings and refusals must agree (truncated payloads keep reader-specific
diagnostics), and ``include_source_path=True`` must select each actual XML occurrence with an XPath
whose child positions match an independently built DOM."""
import re
import xml.etree.ElementTree as ET
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
import uslm_reference_oracle as oracle
from spicy_docs.sources.uscode import UsCodeSourceError

from refspec.registry import uslm

FIXTURES = Path(__file__).parent / 'fixtures/uslm-source-links'

# Both readers refuse the truncated source; the shared reader owns diagnostics.
MALFORMED_DIAGNOSTICS = {
    'title-05-s423.xml': ('ParseError', 'no element found: line 54, column 8'),
    'title-42-s242c.xml': ('ParseError', 'no element found: line 92, column 8'),
}


def outcome(reader, xml, title):
    """Run either reader shape and return (rows, count dict, (error type, message) or None)."""

    counts = Counter()
    rows = []
    error = None
    try:
        if reader is oracle:
            rows.extend(reader.iter_edges(xml, title, counts))
        else:
            reader.read_edges(xml, title, counts, rows.append)
    except (ET.ParseError, uslm.ExtractionError, oracle.ExtractionError, UsCodeSourceError) as exc:
        error = (type(exc).__name__, str(exc))
    return rows, dict(counts), error


def variants(xml):
    """Yield the original plus ten single-link mutations, then the truncated malformed tail."""

    yield 'original', xml
    for mutation in ('duplicate', 'fragment', 'no-href', 'unknown-prefix', 'relative',
                     'unknown-level', 'no-identifier', 'a-element', 'nested-inline', 'unicode'):
        root = ET.fromstring(xml)
        link = next(e for e in root.iter() if e.get('href'))
        if mutation == 'duplicate':
            parent = next(p for p in root.iter() if link in p)
            parent.append(deepcopy(link))
        elif mutation == 'fragment':
            link.set('href', '#local-table')
        elif mutation == 'no-href':
            del link.attrib['href']
        elif mutation == 'unknown-prefix':
            link.set('href', '/us/unsupported/t5/s1')
        elif mutation == 'relative':
            link.set('href', 's1')
        elif mutation == 'unknown-level':
            link.set('href', '/us/usc/t5/unknown')
        elif mutation == 'no-identifier':
            for e in root.iter():
                e.attrib.pop('identifier', None)
        elif mutation == 'a-element':
            link.tag = f'{{{uslm.USLM_NS}}}a'
        elif mutation == 'nested-inline':
            content = link.text
            link.text = 'before '
            child = ET.SubElement(link, f'{{{uslm.USLM_NS}}}inline')
            child.text = content
            child.tail = ' after'
        else:
            link.set('href', '/us/usc/t26/s1400Z–1')
            link.text = '§\u202f1400Z–1 & another occurrence 🧭'
        yield mutation, ET.tostring(root)
    yield 'malformed', xml[:-20]


@pytest.mark.parametrize('name,title', [('title-05-s423.xml', '05'), ('title-42-s242c.xml', '42')])
def test_default_readings_and_refusals_match_copied_oracle(name, title):
    for mutation, xml in variants((FIXTURES / name).read_bytes()):
        actual, previous = outcome(uslm, xml, title), outcome(oracle, xml, title)
        if mutation == 'malformed':
            assert actual[:2] == previous[:2]
            assert previous[2] == MALFORMED_DIAGNOSTICS[name]
            assert actual[2] == ('UsCodeSourceError', 'U.S. Code XML is malformed')
        else:
            assert actual == previous, mutation


@pytest.mark.parametrize('name,title', [('title-05-s423.xml', '05'), ('title-42-s242c.xml', '42')])
def test_optional_paths_select_each_actual_xml_occurrence(name, title):
    for mutation, xml in variants((FIXTURES / name).read_bytes()):
        rows, counts, error = outcome(oracle, xml, title)
        if error:
            continue
        actual_counts = Counter()
        actual = []
        uslm.read_edges(xml, title, actual_counts, actual.append, include_source_path=True)
        assert dict(actual_counts) == counts
        assert [{k:v for k,v in x.items() if k != 'sourceXPath'} for x in actual] == rows
        root = ET.fromstring(xml)
        # Check the generated child positions against the independently built
        # DOM. ElementTree's abbreviated *[n] lookup counts same-tag siblings
        # differently from XPath; it is not a full XPath evaluator.
        expected = [e for e in root.iter() if e.get('href') and not e.get('href').startswith('#')]
        selected = []
        for row in actual:
            positions = [int(p) for p in re.findall(r'/\*\[(\d+)\]', row['sourceXPath'])]
            assert positions[0] == 1
            assert ''.join(f'/*[{p}]' for p in positions) == row['sourceXPath']
            node = root
            for position in positions[1:]:
                node = node[position - 1]
            assert node is not None, (mutation, row)
            assert node.get('href') == row['href'], (mutation, row)
            selected.append(node)
        assert selected == expected, mutation
        assert len({x['sourceXPath'] for x in actual}) == len(actual), mutation


def test_root_href_and_skipped_fragment_do_not_shift_paths():
    xml = b'<ref href="/us/usc/t5/s1"><ref href="#local"/><ref href="/us/usc/t5/s2"/></ref>'
    rows = []
    uslm.read_edges(xml, '05', Counter(), rows.append, include_source_path=True)
    assert [x['sourceXPath'] for x in rows] == ['/*[1]', '/*[1]/*[2]']


def test_comments_do_not_count_as_element_siblings():
    xml = b'<root><!-- comment --><ref href="/us/usc/t5/s2"/><?instruction test?><ref href="/us/usc/t5/s3"/></root>'
    rows = []
    uslm.read_edges(xml, '05', Counter(), rows.append, include_source_path=True)
    assert [x['sourceXPath'] for x in rows] == ['/*[1]/*[1]', '/*[1]/*[2]']

"""Copied pre-eCFR reader; frozen USLM behavior oracle, not a production import."""
# Keep the copied implementation unchanged, including its original formatting.
# ruff: noqa: I001, SIM905, RUF021
from bisect import bisect_left, bisect_right
from typing import Any
import xml.etree.ElementTree as ET
USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"

_TEXT_BLOCKS = frozenset('main appendix title subtitle chapter subchapter part subpart '
    'division subdivision level compiledAct courtRules courtRule reorganizationPlans '
    'reorganizationPlan section subsection paragraph subparagraph clause subclause '
    'item subitem subsubitem continuation notes sourceCredit note p ul ol li longTitle '
    'enactingFormula table thead tbody tfoot tr'.split())
_TEXT_CELLS = frozenset({'td', 'th'})
_SEPARATOR_RANK = {'': 0, ' ': 1, '\t': 2, '\n\n': 3}


def read_text(xml: bytes) -> dict[str, Any]:
    """Prepare readable USLM text with original decoded-text and XPath positions.

    Source-map entries distinguish unchanged decoded XML text from inserted layout
    whitespace. Node offsets address both text representations; empty nodes have
    only source positions. These are Unicode codepoints, not original XML bytes.
    The captured publisher stylesheet supplies the block/table profile; explicit
    heading separation prevents joined words when headings use inline display.
    This preserves reading order and cell boundaries, not full visual table layout.
    """
    root = ET.fromstring(xml)
    if root.tag != f'{{{USLM_NS}}}uscDoc':
        raise ValueError('Expected a captured USLM uscDoc')
    raw_parts, output, parts, nodes = [], [], [], {}
    raw_cursor = cursor = 0
    pending = ''
    trailing_newlines, trailing_tab = 0, False

    def append(value):
        nonlocal raw_cursor, cursor, pending, trailing_newlines, trailing_tab
        if not value:
            return
        if pending and value.strip():
            # Existing source whitespace remains source text. Supply only the
            # missing separator before the next visible source character.
            leading = value[:len(value) - len(value.lstrip())]
            if pending == '\n\n':
                needed = max(0, 2 - trailing_newlines - leading.count('\n'))
            elif pending == '\t':
                needed = 0 if trailing_tab or '\t' in leading else 1
            else:
                whitespace_before = output and output[-1][-1:].isspace()
                needed = 0 if whitespace_before or leading else 1
            separator = ('\n' if pending == '\n\n' else pending) * needed
            if cursor and separator:
                output.append(separator)
                parts.append({'kind': 'inserted', 'start': cursor,
                              'end': cursor + len(separator), 'text': separator})
                cursor += len(separator)
            pending = ''
        output.append(value)
        part = {'kind': 'source', 'start': cursor, 'end': cursor + len(value),
                'source_start': raw_cursor, 'source_end': raw_cursor + len(value)}
        if parts and parts[-1]['kind'] == 'source':
            parts[-1].update(end=part['end'], source_end=part['source_end'])
        else:
            parts.append(part)
        cursor += len(value)
        raw_cursor += len(value)
        raw_parts.append(value)
        if not value.isspace():
            trailing_newlines, trailing_tab = 0, False
        trailing = value[len(value.rstrip()):]
        trailing_newlines += trailing.count('\n')
        trailing_tab |= '\t' in trailing

    def boundary(separator):
        nonlocal pending
        if _SEPARATOR_RANK[separator] > _SEPARATOR_RANK[pending]:
            pending = separator

    def visit(node, path, parent='', inside_cell=False):
        nonlocal pending
        tag = node.tag.rsplit('}', 1)[-1]
        cell = tag in _TEXT_CELLS
        block = tag in _TEXT_BLOCKS and not (inside_cell and tag == 'p')
        block |= tag == 'content' and parent in {'section', 'reorganizationPlan'}
        block |= tag == 'heading' and parent in {'note', 'appendix'}
        block |= tag == 'chapeau' and any(c.startswith('blockIndent') for c in node.get('class', '').split())
        if block or tag == 'br':
            boundary('\n\n')
        if cell:
            boundary('\t')
        start = raw_cursor
        append(node.text)
        for index, child in enumerate(node, 1):
            visit(child, path + f'/*[{index}]', tag, inside_cell or cell)
            append(child.tail)
        nodes[path] = {'source_start': start, 'source_end': raw_cursor,
                       'tag': tag, **({'identifier': node.get('identifier')} if node.get('identifier') else {})}
        if block or tag == 'heading' and parent == 'section' or inside_cell and tag == 'p':
            boundary('\n\n')
        if tag == 'heading':
            boundary(' ')
        if cell:
            pending = '\t'

    visit(root, '/*[1]')
    source_text, text = ''.join(raw_parts), ''.join(output)
    assert source_text == ''.join(root.itertext())
    sources = [part for part in parts if part['kind'] == 'source']
    starts, ends = [part['source_start'] for part in sources], [part['source_end'] for part in sources]
    for node in nodes.values():
        lo, hi = node['source_start'], node['source_end']
        if lo < hi:
            first, last = sources[bisect_right(ends, lo)], sources[bisect_left(starts, hi) - 1]
            node.update(start=first['start'] + lo - first['source_start'],
                        end=last['start'] + hi - last['source_start'])
    return {'text': text, 'source_text': source_text, 'source_map': parts, 'nodes': nodes,
            'method': 'uslm-block-boundaries/1'}

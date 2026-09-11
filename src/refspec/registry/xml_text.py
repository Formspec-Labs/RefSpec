"""Readable publisher XML with exact source mapping; USLM and eCFR profiles."""
import xml.etree.ElementTree as ET
from bisect import bisect_left, bisect_right
from typing import Any

_TEXT_BLOCKS = frozenset(['main', 'appendix', 'title', 'subtitle', 'chapter', 'subchapter', 'part', 'subpart', 'division', 'subdivision', 'level', 'compiledAct', 'courtRules', 'courtRule', 'reorganizationPlans', 'reorganizationPlan', 'section', 'subsection', 'paragraph', 'subparagraph', 'clause', 'subclause', 'item', 'subitem', 'subsubitem', 'continuation', 'notes', 'sourceCredit', 'note', 'p', 'ul', 'ol', 'li', 'longTitle', 'enactingFormula', 'table', 'thead', 'tbody', 'tfoot', 'tr'])
_TEXT_CELLS = frozenset({'td', 'th'})
_ECFR_DIVS = frozenset('DIV' + str(n) for n in range(1, 10))
_ECFR_TYPES = frozenset(['TITLE', 'SUBTITLE', 'CHAPTER', 'SUBCHAP', 'SUBCHAPTER', 'PART', 'SUBPART', 'SECTION', 'APPENDIX'])
_ECFR_BLOCKS = frozenset(['P', 'PSPACE', 'HEAD', 'HED', 'HD', 'EDNOTE', 'EFFDNOT', 'CITA', 'NOTE', 'NOTES', 'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'CAPTION', 'DIV', 'LI', 'UL', 'OL']) | _ECFR_DIVS
_SEPARATOR_RANK = {'': 0, ' ': 1, '\t': 2, '\n\n': 3}


def read_text(xml: bytes, *, profile: str | None = None) -> dict[str, Any]:
    """Two publisher profiles share exact decoded-text mapping and traversal."""
    root = ET.fromstring(xml)
    if profile is None:
        profile = 'uslm' if root.tag == '{http://xml.house.gov/schemas/uslm/1.0}uscDoc' else 'ecfr'
    ecfr = profile == 'ecfr'
    if profile == 'uslm':
        if root.tag != '{http://xml.house.gov/schemas/uslm/1.0}uscDoc':
            raise ValueError('Expected a captured USLM uscDoc')
    elif ecfr:
        if root.tag != 'ECFR' and not (root.tag in _ECFR_DIVS and root.get('TYPE') in _ECFR_TYPES):
            raise ValueError('Expected captured eCFR ECFR or typed DIV XML')
    else:
        raise ValueError('Unknown publisher XML text profile')
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

    def cell_separator():
        # eCFR preserves empty columns as explicit tabs, including first/last
        # empty cells. Unlike deferred whitespace, an empty cell earns its slot.
        nonlocal cursor, pending, trailing_newlines, trailing_tab
        separator = ('\n' * max(0, 2 - trailing_newlines)) if pending == '\n\n' and cursor else ''
        if separator:
            output.append(separator)
            parts.append({'kind': 'inserted', 'start': cursor, 'end': cursor + len(separator), 'text': separator})
            cursor += len(separator)
            trailing_newlines += len(separator)
        pending = ''

    def visit(node, path, parent='', inside_cell=False, previous_cell=False):
        nonlocal pending, cursor, trailing_newlines, trailing_tab
        tag = node.tag.rsplit('}', 1)[-1]
        kind = tag.upper() if ecfr else tag
        cell = kind in {'TD', 'TH'} if ecfr else tag in _TEXT_CELLS
        if ecfr:
            block = kind in _ECFR_BLOCKS and not (inside_cell and kind == 'P')
        else:
            block = tag in _TEXT_BLOCKS and not (inside_cell and tag == 'p')
            block |= tag == 'content' and parent in {'section', 'reorganizationPlan'}
            block |= tag == 'heading' and parent in {'note', 'appendix'}
            block |= tag == 'chapeau' and any(c.startswith('blockIndent') for c in node.get('class', '').split())
        if block or kind == ('BR' if ecfr else 'br'):
            boundary('\n\n')
        if cell and ecfr:
            cell_separator()
            if previous_cell and not trailing_tab:
                output.append('\t')
                parts.append({'kind': 'inserted', 'start': cursor, 'end': cursor + 1, 'text': '\t'})
                cursor += 1
                trailing_tab = True
        elif cell:
            boundary('\t')
        start = raw_cursor
        append(node.text)
        seen_cell = False
        for index, child in enumerate(node, 1):
            visit(child, path + f'/*[{index}]', tag, inside_cell or cell, seen_cell)
            seen_cell |= child.tag.rsplit('}', 1)[-1].upper() in {'TD', 'TH'}
            append(child.tail)
        nodes[path] = {'source_start': start, 'source_end': raw_cursor,
                       'tag': tag, **({'attributes': dict(node.attrib)} if ecfr else
                                   {'identifier': node.get('identifier')} if node.get('identifier') else {})}
        if block or (not ecfr and tag == 'heading' and parent == 'section') or (inside_cell and kind == ('P' if ecfr else 'p')):
            boundary('\n\n')
        if not ecfr and tag == 'heading':
            boundary(' ')
        if cell:
            pending = '' if ecfr else '\t'
            if ecfr:
                trailing_tab = False  # Only a following source gap can separate the next cell.

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
            'method': 'ecfr-block-boundaries/1' if ecfr else 'uslm-block-boundaries/1'}

"""Read captured eCFR XML without inventing paragraph identities or editions."""
from .xml_text import read_text as _read_text


def read_text(xml: bytes) -> dict:
    """Return exact decoded text, readable boundaries, source map and native nodes.

    Native attributes (including N, TYPE, VOLUME and table spans) belong to the
    supplied XML. A bare section does not acquire title or edition metadata.
    XPath addresses this supplied root; coordinates are Unicode codepoints,
    not XML byte offsets. Table cells retain order and empty slots, not a
    reconstructed visual grid for merged cells. Notes remain source text.
    """
    return _read_text(xml, profile='ecfr')


def section_addresses(prepared: dict) -> tuple[dict[str, str], list[dict]]:
    """Exact section addresses from native TITLE/SECTION ancestry.

    Index an already-read source without reparsing XML. A bare SECTION lacks
    title context. Native part/section disagreement is an input error; no
    filename, edition or prose paragraph marker supplies missing context.
    Address spelling uses the existing citation grammar.
    Return addresses by XPath and unresolved native sections. A combined native
    range remains an issue rather than blocking other sections or expanding into
    invented individual targets.
    """
    from .citation_grammar import CfrCitation, find_cfr_citations

    if prepared.get('method') != 'ecfr-block-boundaries/1':
        raise ValueError('Expected prepared eCFR XML')
    nodes, addresses, unresolved = prepared['nodes'], {}, []
    for path, node in nodes.items():
        if node.get('attributes', {}).get('TYPE') != 'SECTION':
            continue
        titles, parts = [], []
        parent = path.rsplit('/', 1)[0]
        while parent:
            attributes = nodes[parent].get('attributes', {})
            if attributes.get('TYPE') == 'TITLE':
                titles.append(attributes.get('N'))
            if attributes.get('TYPE') == 'PART':
                parts.append(attributes.get('N'))
            parent = parent.rsplit('/', 1)[0]
        if len(titles) != 1:
            raise ValueError('eCFR section needs unambiguous native title context')
        address = f"{titles[0]} CFR {node['attributes'].get('N', '')}"
        matches = list(find_cfr_citations(address))
        match = matches[0] if len(matches) == 1 else None
        if (match is None or not isinstance(match.citation, CfrCitation)
                or (match.start, match.end) != (0, len(address))
                or match.refusal or match.qualifier_status or match.pinpoint
                or not match.citation.title_is_possible or match.citation.cfr_section is None):
            unresolved.append({'code': 'native_section_scope_not_supported',
                               'value': address, 'source_path': path})
            continue
        citation = match.citation
        if any(part != citation.cfr_part for part in parts):
            raise ValueError('Native eCFR part and section disagree: ' + address)
        addresses[path] = f'{citation.cfr_title} CFR {citation.cfr_part}.{citation.cfr_section}'
    return addresses, unresolved

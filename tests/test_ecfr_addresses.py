"""Native XML addressing preserves source scope without guessing missing context.

Addresses come only from native DIV8 sections: a bare section without title context and a part that
disagrees with its section are refused, native ranges are reported as unsupported issues rather than
expanded, and free text or lookalike attributes never yield an address."""
import pytest

from refspec.registry.ecfr import read_text, section_addresses


def source(title='49', part='390', number='390.5', extra=''):
    """A parsed one-title/part/section eCFR document, with optional extra sibling markup."""

    return read_text((f'<ECFR><DIV1 TYPE="TITLE" N="{title}">'
        f'<DIV5 TYPE="PART" N="{part}"><DIV8 TYPE="SECTION" N="{number}">'
        f'<HEAD>Section</HEAD><P>Body.</P></DIV8>{extra}</DIV5></DIV1></ECFR>').encode())


@pytest.mark.parametrize('title,part,number,expected', [
    ('49', '390', '390.5', '49 CFR 390.5'),
    ('49', '390', '390.5T', '49 CFR 390.5T'),
    ('41', '102-5', '102-5.1', '41 CFR 102-5.1'),
    ('5', '0', '0.1', '5 CFR 0.1'),
])
def test_native_complete_addresses_reuse_grammar(title, part, number, expected):
    addresses, issues = section_addresses(source(title, part, number))
    assert list(addresses.values()) == [expected] and issues == []


def test_bare_section_needs_title_but_can_still_be_read():
    prepared = read_text(b'<DIV8 TYPE="SECTION" N="390.5"><P>Body.</P></DIV8>')
    assert prepared['text'] == 'Body.'
    with pytest.raises(ValueError, match='title context'):
        section_addresses(prepared)


def test_part_disagreement_refuses_instead_of_reparenting():
    with pytest.raises(ValueError, match='part and section disagree'):
        section_addresses(source(part='382'))


def test_native_range_is_not_expanded_and_does_not_hide_exact_sibling():
    extra = '<DIV8 TYPE="SECTION" N="390.6-390.8"><P>Reserved.</P></DIV8>'
    prepared = source(extra=extra)
    addresses, issues = section_addresses(prepared)
    assert list(addresses.values()) == ['49 CFR 390.5']
    assert issues == [{'code':'native_section_scope_not_supported',
                      'value':'49 CFR 390.6-390.8', 'source_path':'/*[1]/*[1]/*[1]/*[2]'}]
    assert prepared['nodes'][issues[0]['source_path']]['attributes']['N'] == '390.6-390.8'


def test_duplicate_address_retains_both_native_nodes():
    extra = '<DIV8 TYPE="SECTION" N="390.5"><P>Other.</P></DIV8>'
    addresses, issues = section_addresses(source(extra=extra))
    assert list(addresses.values()) == ['49 CFR 390.5', '49 CFR 390.5'] and not issues


def test_no_section_discovered_from_free_text_or_attribute_lookalikes():
    prepared = read_text(b'<ECFR><DIV1 TYPE="TITLE" N="49"><P N="390.5">49 CFR 390.5</P></DIV1></ECFR>')
    assert section_addresses(prepared) == ({}, [])

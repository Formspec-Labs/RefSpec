"""Independent old-parser comparisons for the shared source-credit reader.

One named divergence: the new reader refuses DOCTYPE entity declarations the
frozen oracle expanded.
"""

import re
from pathlib import Path

import pytest
import usc_source_credit_parser_oracle as oracle
from spicy_docs.sources.uscode import UsCodeSourceError
from spicy_docs.sources.uscode.references import scan_uscode_references

from tools import build_usc_source_credits as builder

FIXTURES = Path(__file__).parent / "fixtures/uslm-source-links"


def observed(body):
    """Return the new reader's (enclosing section identifier, normalized credit text) rows."""

    rows = []

    def credit(row):
        identifier = next((element.attributes["identifier"] for element in reversed(row.ancestors)
                           if element.tag.rsplit("}", 1)[-1] == "section" and element.attributes.get("identifier")), None)
        rows.append((identifier, re.sub(r"[ \t\r\n]+", " ", row.text).strip()))

    scan_uscode_references(body, on_source_credit=credit)
    return rows


@pytest.mark.parametrize("name", ["title-05-s423.xml", "title-42-s242c.xml"])
def test_raw_retained_source_agrees_with_frozen_walker(name):
    """Pin that the real retained fixtures yield the same rows as the frozen walker."""

    body = (FIXTURES / name).read_bytes()
    assert observed(body) == list(oracle.iter_source_credits(body))


@pytest.mark.parametrize("credit", ["", "§\u202f107 – café 🧭", "before <inline>inside</inline> after",
                                     "before <!-- ignored comment --> after"])
@pytest.mark.parametrize("inner", ["identifier='/us/usc/t5/s2'", "", "status='repealed'"])
def test_mutated_ancestry_text_and_duplicate_credits_agree(credit, inner):
    """Pin equal rows across mutated ancestry, unicode/entity text, and duplicate credits."""

    body = (f"<section identifier='/us/usc/t5/s1'><section {inner}><sourceCredit>{credit}</sourceCredit>"
            f"</section><sourceCredit>{credit}</sourceCredit><sourceCredit>{credit}</sourceCredit></section>").encode()
    assert observed(body) == list(oracle.iter_source_credits(body))


def test_unattributed_credit_is_preserved():
    """Pin that a credit under no section yields (None, text) in both readers."""

    body = b"<root><sourceCredit>source</sourceCredit></root>"
    assert observed(body) == list(oracle.iter_source_credits(body)) == [(None, "source")]


def test_malformed_input_returns_no_policy_result():
    """Pin that malformed XML raises UsCodeSourceError instead of returning partial rows."""

    with pytest.raises(UsCodeSourceError, match="malformed"):
        builder.scan_source_credits(b"<section><sourceCredit>prefix</sourceCredit>")


def test_declared_entity_refusal_is_an_intentional_safety_change():
    """Pin the one divergence: the oracle expands a DOCTYPE entity, the new reader refuses it."""

    body = b'<!DOCTYPE root [<!ENTITY extra "text">]><root><sourceCredit>&extra;</sourceCredit></root>'
    assert list(oracle.iter_source_credits(body)) == [(None, "text")]
    with pytest.raises(UsCodeSourceError, match="DOCTYPE"):
        observed(body)

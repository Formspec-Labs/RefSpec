"""Compare shared page reading with the copied pre-port GAO implementation."""

from __future__ import annotations

import io
from dataclasses import asdict, replace
from pathlib import Path

import gao_cra_form_oracle as old
import pytest
from pypdf import PdfReader, PdfWriter
from spicy_docs.extraction.pypdf import PypdfReader

from refspec.registry import gao_cra_form_codes as current

FIXTURES = Path(__file__).parent / "fixtures/gao_cra_form_codes"
CASES = (
    (
        "gao-cra-submission-form-rev-12-24-2026-08-15.pdf",
        "parse_gao_cra_current_form",
        "GAO_CRA_CURRENT_FORM_2026_08_15",
    ),
    ("gao-cra-blank-form-rev-11-17-23-2026-08-15.pdf", "parse_gao_cra_retired_form", "GAO_CRA_RETIRED_FORM_2026_08_15"),
    (
        "gao-09-205-2009-04-20-2026-08-15.pdf",
        "parse_gao_cra_institutional_bridge",
        "GAO_CRA_INSTITUTIONAL_BRIDGE_2026_08_15",
    ),
)


@pytest.mark.parametrize("filename,parser_name,pin_name", CASES)
def test_exact_pinned_pdfs_keep_all_raw_pages_and_interpreted_facts(filename, parser_name, pin_name):
    payload = (FIXTURES / filename).read_bytes()
    with PypdfReader().open(payload, password="") as document:
        old_pages = [page.extract_text() for page in PdfReader(io.BytesIO(payload)).pages]
        assert [document.read_page(i) for i in range(1, document.page_count + 1)] == old_pages
    assert asdict(getattr(current, parser_name)(payload)) == asdict(getattr(old, parser_name)(payload))


def _mutation(payload, mutation):
    if mutation == "header":
        return b"!PDF-" + payload[5:]
    if mutation == "truncated":
        return payload[:512]
    if mutation == "bad-pin":
        return payload + b"\n"
    writer = PdfWriter(clone_from=io.BytesIO(payload))
    if mutation == "blank-page":
        writer.add_blank_page(width=612, height=792)
    else:
        writer.encrypt("" if mutation == "empty-password" else "private", owner_password="owner")
    result = io.BytesIO()
    writer.write(result)
    writer.close()
    return result.getvalue()


@pytest.mark.parametrize("filename,parser_name,pin_name", CASES)
@pytest.mark.parametrize("mutation", ["header", "truncated", "bad-pin", "blank-page", "empty-password", "protected"])
def test_pdf_mutation_verdicts_match_the_frozen_reader(filename, parser_name, pin_name, mutation):
    payload = _mutation((FIXTURES / filename).read_bytes(), mutation)

    def verdict(module):
        pin = getattr(module, pin_name)
        if mutation != "bad-pin":
            pin = replace(pin, expected_sha256=current.sha256_digest(payload), expected_byte_length=len(payload))
        try:
            return "accepted", asdict(getattr(module, parser_name)(payload, pin=pin))
        except module.GaoCraFormSourceDriftError as error:
            return "refused", str(error)

    assert verdict(current) == verdict(old)


def test_failed_page_refuses_the_form_with_original_failure_cause(monkeypatch):
    from pypdf._page import PageObject

    def fail(page):
        raise RuntimeError("test failed text page")

    monkeypatch.setattr(PageObject, "extract_text", fail)
    with pytest.raises(current.GaoCraFormSourceDriftError, match="text layer is unreadable") as failure:
        current.parse_gao_cra_current_form((FIXTURES / CASES[0][0]).read_bytes())
    assert failure.value.__cause__.page == 1
    assert str(failure.value.__cause__.__cause__) == "test failed text page"

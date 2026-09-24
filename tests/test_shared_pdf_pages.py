"""Compare shared page reading with the copied pre-port implementations.

GAO's forms keep a full frozen reader (``gao_cra_form_oracle``). The census
GNIS layout, Unified Agenda RISC preamble and both FERC PDFs moved later and
only their page read changed, so their oracle is that read, copied: pypdf's
own constructor and every page's text layer (GNIS reads only pages 1 and 2,
as its direct loop did). Their one deliberate divergence is where a refusal
surfaces: a protected file or an unreadable page now refuses as the module's
own drift error instead of a raw pypdf exception, which the last test pins at
each module's entry point.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import asdict, replace
from pathlib import Path

import gao_cra_form_oracle as old
import pytest
from pypdf import PdfReader, PdfWriter
from spicy_docs.extraction.pypdf import PdfReadError, PypdfReader

from conftest import missing_pinned_input
from refspec.pdf_text import pdf_page_texts
from refspec.registry import census_geo_codes as geo
from refspec.registry import ferc_elibrary_codes as ferc
from refspec.registry import gao_cra_form_codes as current
from refspec.registry import unified_agenda_codes as ua

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
    """Every raw page text and every interpreted capture field matches the copied pre-port implementation."""

    payload = (FIXTURES / filename).read_bytes()
    with PypdfReader().open(payload, password="") as document:
        old_pages = [page.extract_text() for page in PdfReader(io.BytesIO(payload)).pages]
        assert [document.read_page(i) for i in range(1, document.page_count + 1)] == old_pages
    assert asdict(getattr(current, parser_name)(payload)) == asdict(getattr(old, parser_name)(payload))


def _mutation(payload, mutation):
    """Apply one named byte- or PDF-level mutation; ``bad-pin`` leaves the pin untouched."""

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
    """Acceptance or refusal, and the refusal message, match the frozen reader for every mutation."""

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
    """An unreadable page refuses with the page number and the original error as the cause's cause."""

    from pypdf._page import PageObject

    def fail(page):
        raise RuntimeError("test failed text page")

    monkeypatch.setattr(PageObject, "extract_text", fail)
    with pytest.raises(current.GaoCraFormSourceDriftError, match="text layer is unreadable") as failure:
        current.parse_gao_cra_current_form((FIXTURES / CASES[0][0]).read_bytes())
    assert failure.value.__cause__.page == 1
    assert str(failure.value.__cause__.__cause__) == "test failed text page"


PORTED = (
    ("census GNIS layout", "fixture", "census_geo_codes/gnis-file-format-2026-08-03.pdf"),
    ("Unified Agenda RISC preamble", "fixture", "unified_agenda_codes/risc-preamble-202210.pdf"),
    ("FERC class types", "environment", "REFSPEC_FERC_CLASS_TYPES_2025_PDF_PATH"),
    ("FERC docket prefixes", "environment", "REFSPEC_FERC_DOCKET_PREFIX_2025_PDF_PATH"),
)


def _ported_payload(kind: str, where: str) -> bytes:
    if kind == "fixture":
        return (Path(__file__).parent / "fixtures" / where).read_bytes()
    path = os.environ.get(where)
    if path is None:
        missing_pinned_input(f"{where} is not materialized")
    return Path(path).read_bytes()


def _direct_loop(payload: bytes) -> list[str]:
    """The pre-port read those modules made, copied rather than imported."""

    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(payload)).pages]


def _read(reader, payload):
    try:
        return "accepted", list(reader(payload))
    except Exception:  # noqa: BLE001 - a verdict is any refusal, whatever raised it
        return "refused", None


@pytest.mark.parametrize("name,kind,where", PORTED)
@pytest.mark.parametrize("mutation", [None, "header", "truncated", "blank-page", "empty-password", "protected"])
def test_ported_pdfs_read_every_page_as_the_direct_loop_did(name, kind, where, mutation):
    """The pinned bytes read identically page for page, and every mutation gets the direct loop's verdict."""

    payload = _ported_payload(kind, where)
    if mutation is not None:
        payload = _mutation(payload, mutation)
    assert _read(pdf_page_texts, payload) == _read(_direct_loop, payload)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _gnis(payload, tmp_path, monkeypatch):
    pin = replace(geo.GNIS_FILE_FORMAT_PIN_2026_08_03, expected_sha256=_digest(payload), expected_byte_length=len(payload))
    source = tmp_path / "gnis.pdf"
    source.write_bytes(payload)
    geo.parse_gnis_file_format(geo.acquire_gnis_file_format(pin, tmp_path / "store", source_path=source))


def _risc(payload, tmp_path, monkeypatch):
    pin = replace(ua.UA_RISC_PREAMBLE_2026_08_03, expected_sha256=_digest(payload), expected_byte_length=len(payload))
    source = tmp_path / "risc.pdf"
    source.write_bytes(payload)
    ua.pin_risc_preamble_evidence(ua.acquire_unified_agenda_document(pin, tmp_path / "store", source_path=source))


def _ferc(prefix, parse):
    def entry(payload, tmp_path, monkeypatch):
        monkeypatch.setattr(ferc, f"{prefix}_SHA256", _digest(payload))
        monkeypatch.setattr(ferc, f"{prefix}_BYTE_LENGTH", len(payload))
        parse(payload)

    return entry


ENTRY_POINTS = {
    "census GNIS layout": (_gnis, geo.CensusGeoSourceDriftError, "not a readable PDF"),
    "Unified Agenda RISC preamble": (_risc, ua.UnifiedAgendaSourceDriftError, "RISC Preamble is unreadable"),
    "FERC class types": (
        _ferc("FERC_CLASS_TYPE_PDF", ferc.parse_ferc_class_type_pdf),
        ferc.FercSourceDriftError,
        "class/type PDF is unreadable",
    ),
    "FERC docket prefixes": (
        _ferc("FERC_DOCKET_PREFIX_PDF", ferc.parse_ferc_docket_prefix_pdf),
        ferc.FercSourceDriftError,
        "docket-prefix PDF is unreadable",
    ),
}


@pytest.mark.parametrize("name,kind,where", PORTED)
@pytest.mark.parametrize("failure", ["protected", "failing-page"])
def test_each_entry_point_refuses_an_unreadable_pdf_as_its_own_drift_error(
    name, kind, where, failure, tmp_path, monkeypatch
):
    """A protected file or a page that cannot be read reaches the caller as the module's own drift error,
    caused by the shared reader's refusal, never as a raw reader exception or an empty page."""

    from pypdf._page import PageObject

    payload = _ported_payload(kind, where)
    if failure == "protected":
        payload = _mutation(payload, "protected")
    else:

        def fail(page):
            raise RuntimeError("test failed text page")

        monkeypatch.setattr(PageObject, "extract_text", fail)
    entry, error_type, message = ENTRY_POINTS[name]
    with pytest.raises(error_type, match=message) as refused:
        entry(payload, tmp_path, monkeypatch)
    assert isinstance(refused.value.__cause__, PdfReadError)

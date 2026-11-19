"""Offline fast-tier verification for Library of Congress pre-1951 Statutes at Large (Vols. 1-64)."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from refspec.loc_statutes_at_large import (
    EVIDENCE_RELATIVE_DIR,
    LLSL_CATALOG_BYTE_LENGTH,
    LLSL_CATALOG_FILENAME,
    LLSL_CATALOG_SHA256,
    LLSL_OCR_MANIFEST_BYTE_LENGTH,
    LLSL_OCR_MANIFEST_FILENAME,
    LLSL_OCR_MANIFEST_SHA256,
    LocStatutesError,
    extract_llsl_pdf_ocr_layers,
    int_to_roman,
    llsalvol_segment_urls,
    load_llsl_catalog,
    load_llsl_ocr_verification_manifest,
    normalize_split_smallcaps_designators,
    parse_enactment_year_from_table3_key,
    parse_llsalvol_page_stem,
    resolve_statutes_volume,
    score_llsl_layer_citation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_synthetic_llsl_pdf(
    *,
    include_type1: bool,
    include_invisible_ocr: bool,
    render_mode: int = 3,
    extra_non_legacy_font: str | None = None,
) -> bytes:
    """Build a minimal 1-page PDF reproducing LoC llsl's dual-font content-stream layout."""

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    fonts = DictionaryObject()
    ops: list[str] = ["BT", f"{render_mode} Tr"]
    if include_type1:
        f5 = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Times-Roman"),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
        )
        fonts[NameObject("/F5")] = f5
        ops.append("1 0 0 1 72 750 Tm /F5 11 Tf (570 FIFTH CONGRESS. SESS. II. C. 58. 1798.) Tj")
        ops.append("1 0 0 1 72 680 Tm /F5 11 Tf (CHAP. LVIII. SECTION 1. Be it enacted) Tj")
    if include_invisible_ocr:
        fxf1 = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/InvisibleOCR"),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
        )
        fonts[NameObject("/FXF1")] = fxf1
        ops.append("1 0 0 1 72 750 Tm /FXF1 11 Tf (570 FIFTH CONGRESS. Sass. IL Cn. 58. 1798.) Tj")
        ops.append("1 0 0 1 72 680 Tm /FXF1 11 Tf (C HAP. LVIII. S ECTION 1. Be it enacted) Tj")
    if extra_non_legacy_font:
        f_other = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/TrueType"),
                    NameObject("/BaseFont"): NameObject(extra_non_legacy_font),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
        )
        fonts[NameObject("/FX99")] = f_other
        ops.append("1 0 0 1 72 400 Tm /FX99 11 Tf (STAMP) Tj")
    ops.append("ET")

    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pinned_llsl_catalog_invariants_immutability_and_caption_vs_term_years() -> None:
    """Pins the 64-volume catalogue (97 PDFs, 69 llsalvol objects), immutability, and 5th Congress year bounds."""

    catalog = load_llsl_catalog(REPO_ROOT)
    assert tuple(sorted(catalog)) == tuple(range(1, 65))
    with pytest.raises(TypeError):
        catalog[1] = catalog[2]  # type: ignore[index]

    assert sum(len(v.pdf_resources) for v in catalog.values()) == 97
    single_pdf_vols = [v.volume for v in catalog.values() if len(v.pdf_resources) == 1]
    multi_pdf_vols = [v.volume for v in catalog.values() if len(v.pdf_resources) > 1]
    assert len(single_pdf_vols) == 52
    assert multi_pdf_vols == [1, 2, 3, 4, 5, 9, 10, 11, 12, 18, 20, 44]

    assert sum(len(v.llsalvol_resources) for v in catalog.values()) == 69
    assert [v.volume for v in catalog.values() if len(v.llsalvol_resources) > 1] == [18, 44]

    # llsl-c5.pdf preserves LoC's verbatim "5th Congress (1798/1799)" caption while expanding term years to 1797..1799.
    c5 = catalog[1].pdf_resources[4]
    assert c5.filename == "llsl-c5.pdf"
    assert c5.caption == "5th Congress (1798/1799)"
    assert (c5.caption_year_start, c5.caption_year_end) == (1798, 1799)
    assert (c5.year_start, c5.year_end) == (1797, 1799)


def test_pinned_ocr_manifest_boundary_counterexamples_and_scoped_accuracy() -> None:
    """Pins the 10-PDF / 19,555-page OCR manifest, 51 Stat. 4 p. 10, ALTO header diff, and negative boundaries."""

    manifest = load_llsl_ocr_verification_manifest(REPO_ROOT)
    with pytest.raises(TypeError):
        manifest["verdict"] = {}  # type: ignore[index]

    verdict = manifest["verdict"]
    assert verdict["embedded_ocr_present_in_all_sampled_pdfs"] is True
    assert verdict["sampled_pdf_count"] == 10
    assert verdict["sampled_total_pdf_pages"] == 19_555

    alto = manifest["pinned_alto_xml_samples"]
    assert len(alto) == 2
    assert alto[0]["stat_page"] == 570 and alto[0]["matches_pdf_layer2_header_verbatim"] is True
    assert alto[1]["stat_page"] == 577 and alto[1]["matches_pdf_layer2_header_verbatim"] is False

    # Boundary & counterexample records grounded in cached primary PDFs
    bounds = manifest["boundary_and_negative_checks"]
    assert bounds["c5_page1_1797_session_start"]["stat_page"] == 536
    assert "November, 1797" in bounds["c5_page1_1797_session_start"]["layer1_opening_excerpt"]
    for lk in ("layer1_score_as_51stat4_ch3", "layer2_score_as_51stat4_ch3"):
        assert bounds["c75s2_page9_folio3_rejects_folio4_and_ch3"][lk]["folio_in_running_header"] is False
        assert bounds["c75s2_page9_folio3_rejects_folio4_and_ch3"][lk]["chapter_bound"] is False
    for lk in ("layer1_score", "layer2_score"):
        s_163 = bounds["c48_page360_23stat332_ch163_rejects_neighboring_sec2"][lk]
        assert s_163["folio_in_running_header"] is True
        assert s_163["chapter_heading_strict"] is True
        assert s_163["section_in_act_split_tolerant"] is False
    non_dual = bounds["c48_non_dual_ocr_scan_frames"]
    assert non_dual[0]["pdf_page_1based"] == 292 and non_dual[0]["has_dual_ocr_collision"] is False
    assert non_dual[1]["pdf_page_1based"] == 552 and non_dual[1]["chars_layer1"] == 0 and non_dual[1]["chars_layer2"] == 0

    specimens = manifest["specimens"]
    assert len(specimens) == 16
    by_id = {s["specimen_id"]: s for s in specimens}
    assert by_id["51stat4_fcu_amend"]["pdf_page_1based"] == 10
    assert by_id["51stat4_fcu_amend"]["stat_page"] == 4
    assert by_id["51stat4_fcu_amend"]["expected_chapter"] == "3"
    assert by_id["23stat332_foran_labor"]["pdf_page_1based"] == 360
    assert by_id["49stat647_ssa_1102"]["expected_chapter"] == "531"
    assert all(s["uses_invisible_render_mode_3tr"] is True for s in specimens)

    for lk in ("layer1_score_as_51stat6_ch3", "layer2_score_as_51stat6_ch3"):
        assert bounds["c75s2_page10_rejects_date_day_folio6_and_inline_sec1756"][lk]["folio_in_running_header"] is False
    for lk in ("layer1_score_as_51stat4_ch3_sec1756", "layer2_score_as_51stat4_ch3_sec1756"):
        assert bounds["c75s2_page10_rejects_date_day_folio6_and_inline_sec1756"][lk]["section_in_act_split_tolerant"] is False
    for lk in ("layer1_score", "layer2_score"):
        assert bounds["c9_page96_2stat443_rejects_split_roman_ch10"][lk]["chapter_bound"] is False

    acc = dict(verdict["accuracy_summary"])
    assert acc == {
        "specimen_count": 16,
        "specimens_with_printed_section_label": 12,
        "layer1_folio_in_running_header": 15,
        "layer2_folio_in_running_header": 16,
        "union_folio_in_running_header": 16,
        "layer1_chapter_heading_strict": 14,
        "layer2_chapter_heading_strict": 11,
        "layer1_chapter_heading_tolerant": 15,
        "layer2_chapter_heading_tolerant": 16,
        "union_chapter_heading_tolerant": 16,
        "layer1_section_in_act_strict": 9,
        "layer2_section_in_act_strict": 4,
        "layer1_section_in_act_split_tolerant": 9,
        "layer2_section_in_act_split_tolerant": 12,
        "union_section_in_act_split_tolerant": 12,
        "layer1_full_citation_bound_strict": 12,
        "layer2_full_citation_bound_normalized": 16,
        "union_full_citation_bound_normalized": 16,
    }


def test_pinned_manifest_loaders_refuse_tampered_missing_or_symlinked_files(tmp_path: Path) -> None:
    """Negative gate: byte tampering, missing files, or symlinks raise LocStatutesError."""

    ev_dir = tmp_path / EVIDENCE_RELATIVE_DIR
    ev_dir.mkdir(parents=True)

    with pytest.raises(LocStatutesError, match="missing or not a regular file"):
        load_llsl_catalog(tmp_path)

    src_cat = REPO_ROOT / EVIDENCE_RELATIVE_DIR / LLSL_CATALOG_FILENAME
    dst_cat = ev_dir / LLSL_CATALOG_FILENAME
    assert src_cat.stat().st_size == LLSL_CATALOG_BYTE_LENGTH
    tampered = bytearray(src_cat.read_bytes())
    tampered[-2] ^= 0x01
    dst_cat.write_bytes(bytes(tampered))
    with pytest.raises(LocStatutesError, match=LLSL_CATALOG_SHA256):
        load_llsl_catalog(tmp_path)

    dst_cat.unlink()
    dst_cat.symlink_to(src_cat)
    with pytest.raises(LocStatutesError, match="missing or not a regular file"):
        load_llsl_catalog(tmp_path)

    dst_ocr = ev_dir / LLSL_OCR_MANIFEST_FILENAME
    shutil.copyfile(REPO_ROOT / EVIDENCE_RELATIVE_DIR / LLSL_OCR_MANIFEST_FILENAME, dst_ocr)
    assert dst_ocr.stat().st_size == LLSL_OCR_MANIFEST_BYTE_LENGTH
    dst_ocr.write_bytes(dst_ocr.read_bytes() + b" ")
    with pytest.raises(LocStatutesError, match=LLSL_OCR_MANIFEST_SHA256):
        load_llsl_ocr_verification_manifest(tmp_path)


def test_resolve_statutes_volume_handles_1797_autumn_session_overlaps_and_contradictions() -> None:
    """Tests 1 Stat. 536 (1797:1), 1807 overlap, and explicit unresolved status on contradictory filters."""

    catalog = load_llsl_catalog(REPO_ROOT)

    # 1 Stat. 536 (1797:1, 5th Cong. 2d Sess., Dec. 15, 1797): must retain BOTH llsl-c4.pdf and llsl-c5.pdf
    # rather than wrongly resolving to llsl-c4.pdf from LoC's incomplete "5th Congress (1798/1799)" caption.
    s536 = resolve_statutes_volume(1, statutes_at_large_page=536, table3_key="1797:1", catalog=catalog)
    assert s536.pdf_resolution_status == "ambiguous_multi_part_volume"
    assert s536.unique_pdf is None
    assert [p.filename for p in s536.candidate_pdfs] == ["llsl-c4.pdf", "llsl-c5.pdf"]

    s536_c5 = resolve_statutes_volume(1, statutes_at_large_page=536, table3_key="1797:1", congress=5, catalog=catalog)
    assert s536_c5.pdf_resolution_status == "narrowed_by_year"
    assert s536_c5.unique_pdf is not None and s536_c5.unique_pdf.filename == "llsl-c5.pdf"

    # Contradictory filters NEVER silently fall back to an earlier candidate set!
    contradict_v2 = resolve_statutes_volume(2, statutes_at_large_page=443, table3_key="1807:39", congress=6, catalog=catalog)
    assert contradict_v2.pdf_resolution_status == "unresolved_contradictory_filters"
    assert contradict_v2.candidate_pdfs == ()
    assert contradict_v2.unique_pdf is None

    contradict_single = resolve_statutes_volume(60, statutes_at_large_page=237, table3_key="1797:1", catalog=catalog)
    assert contradict_single.pdf_resolution_status == "unresolved_contradictory_filters"
    assert contradict_single.candidate_pdfs == ()

    contradict_years = resolve_statutes_volume(
        1, statutes_at_large_page=577, enactment_year=1800, table3_key="1798:66", catalog=catalog
    )
    assert contradict_years.pdf_resolution_status == "unresolved_contradictory_filters"
    assert contradict_years.candidate_pdfs == ()

    # Valid single-PDF & narrowed cases
    apa = resolve_statutes_volume(60, statutes_at_large_page=237, table3_key="1946:324", catalog=catalog)
    assert apa.pdf_resolution_status == "single_volume_pdf"
    assert apa.unique_pdf is not None and apa.unique_pdf.filename == "llsl-c79s2.pdf"

    aea = resolve_statutes_volume(1, statutes_at_large_page=577, table3_key="1798:66", catalog=catalog)
    assert aea.pdf_resolution_status == "narrowed_by_year"
    assert aea.unique_pdf is not None and aea.unique_pdf.filename == "llsl-c5.pdf"

    v18_bare = resolve_statutes_volume(18, enactment_year=1874, catalog=catalog)
    assert v18_bare.pdf_resolution_status == "ambiguous_multi_part_volume"
    assert len(v18_bare.candidate_pdfs) == 4

    # Multi-Congress Vol. 6 (Private Laws 1789-1845, congress=None) must retain llsl-vol-6-private.pdf for Congress 1..28,
    # while rejecting contradictory congress/year pairs (e.g. 1790 + congress=20 or congress=50).
    v6_c1 = resolve_statutes_volume(6, enactment_year=1790, congress=1, catalog=catalog)
    assert v6_c1.pdf_resolution_status == "single_volume_pdf"
    assert v6_c1.unique_pdf is not None and v6_c1.unique_pdf.filename == "llsl-vol-6-private.pdf"

    v6_mismatch_year_cong = resolve_statutes_volume(6, enactment_year=1790, congress=20, catalog=catalog)
    assert v6_mismatch_year_cong.pdf_resolution_status == "unresolved_contradictory_filters"
    assert v6_mismatch_year_cong.candidate_pdfs == ()

    v6_out_of_span_cong = resolve_statutes_volume(6, congress=50, catalog=catalog)
    assert v6_out_of_span_cong.pdf_resolution_status == "unresolved_contradictory_filters"
    assert v6_out_of_span_cong.candidate_pdfs == ()


def test_score_llsl_layer_citation_rejects_wrong_folio_wrong_roman_and_wrong_chapter_section() -> None:
    """Proves folio, Roman chapter, and section checks are strictly bound to the header and act block."""

    assert int_to_roman(58) == "LVIII"
    assert int_to_roman(66) == "LXVI"
    with pytest.raises(LocStatutesError):
        int_to_roman(0)

    # 51 Stat. 3 (PDF p. 9) has "$4 per day" in body and footer "3": must FAIL when scored as 51 Stat. 4 ch. 3
    p9_body = (
        "PUBLIC LAWS [CHAPTER 1] JOINT RESOLUTION ... [CHAPTER 2] JOINT RESOLUTION "
        "compensated at the rate of $4 per day. Approved, November 26, 1937."
    )
    p9_as_4 = score_llsl_layer_citation(
        body_text=p9_body,
        header_text="PUBLIC LAWS",
        footer_text="3",
        statutes_at_large_page=4,
        expected_chapter=3,
    )
    assert p9_as_4.folio_in_running_header is False
    assert p9_as_4.chapter_bound is False
    assert p9_as_4.full_citation_bound_normalized is False

    p9_as_3 = score_llsl_layer_citation(
        body_text=p9_body,
        header_text="PUBLIC LAWS",
        footer_text="3",
        statutes_at_large_page=3,
        expected_chapter=2,
    )
    assert p9_as_3.folio_in_running_header is True
    assert p9_as_3.chapter_heading_strict is True

    # 23 Stat. 332 has SEC. 2 in CHAP. 162 AND S EC. 2 in CHAP. 164, while CHAP. 163 in between has NO Sec. 2!
    p332_body = (
        "332 FORTY-EIGHTH CONGRESS. SESS. II. CH. 161-164. 1885. "
        "CHAP. 162.—An act to enlarge the custom-house at Richmond. Be it enacted... "
        "S EC. 2. That said sum shall be expended upon the order of the Secretary. Approved, Feb. 26, 1885. "
        "CHAP. 163.—An act to increase the water-supply of Washington. Be it enacted... extended one year. "
        "CHAP. 164.—An act to prohibit the importation of foreigners under contract to perform labor. "
        "Be it enacted... S EC. 2. That all contracts or agreements shall be utterly void."
    )
    hdr_332 = "332 FORTY-EIGHTH CONGRESS. SESS. II. CH. 161-164. 1885."

    s_163 = score_llsl_layer_citation(
        body_text=p332_body,
        header_text=hdr_332,
        footer_text="",
        statutes_at_large_page=332,
        expected_chapter=163,
        expected_section="2",
    )
    assert s_163.folio_in_running_header is True
    assert s_163.chapter_heading_strict is True
    assert s_163.section_in_act_strict is False
    assert s_163.section_in_act_split_tolerant is False
    assert s_163.full_citation_bound_normalized is False

    s_164 = score_llsl_layer_citation(
        body_text=p332_body,
        header_text=hdr_332,
        footer_text="",
        statutes_at_large_page=332,
        expected_chapter=164,
        expected_section="2",
    )
    assert s_164.section_in_act_strict is False
    assert s_164.section_in_act_split_tolerant is True
    assert s_164.full_citation_bound_normalized is True

    # Arbitrary or split Roman numerals ('CHAP. XXXVII' or 'C HAP. X XX') must NOT match expected_chapter=39 or 10 ('X')
    wrong_roman = score_llsl_layer_citation(
        body_text="CHAP. XXXVII.—An act making appropriations for fortifying the ports.",
        header_text="NINTH CONGRESS. SESS. II. CH. 37. 1807. 443",
        footer_text="",
        statutes_at_large_page=443,
        expected_chapter=39,
    )
    assert wrong_roman.chapter_heading_strict is False
    assert wrong_roman.chapter_heading_tolerant is False

    split_roman_x = score_llsl_layer_citation(
        body_text="C HAP. X XX .Ict making further appropriations for fortifying the ports.",
        header_text="NINTH CONGRESS . S ass. II . C H. 37, 30, 40, 41. 1807. 443",
        footer_text="",
        statutes_at_large_page=443,
        expected_chapter=10,
    )
    assert split_roman_x.chapter_heading_strict is False
    assert split_roman_x.chapter_heading_tolerant is False
    assert split_roman_x.chapter_bound is False

    # Header date day ("DECEMBER 6, 1937") and inline body cross-ref ("title 12, sec. 1756)") must BOTH fail on 51 Stat. 4!
    p10_hdr = "4 75TH CONGRESS, 2D SESSION—CH. 3—DECEMBER 6, 1937"
    p10_body = (
        "[CHAPTER 3] AN ACT To amend certain sections of the Federal Credit Union Act. "
        "Be it enacted, That section 6 of the Federal Credit Union Act (U. S. C., 1934 edition, title 12, sec. 1756), "
        "be, and the same is hereby, amended."
    )
    date_day_6 = score_llsl_layer_citation(
        body_text=p10_body,
        header_text=p10_hdr,
        footer_text="",
        statutes_at_large_page=6,
        expected_chapter=3,
    )
    assert date_day_6.folio_in_running_header is False
    assert date_day_6.full_citation_bound_normalized is False

    inline_1756 = score_llsl_layer_citation(
        body_text=p10_body,
        header_text=p10_hdr,
        footer_text="",
        statutes_at_large_page=4,
        expected_chapter=3,
        expected_section="1756",
    )
    assert inline_1756.folio_in_running_header is True
    assert inline_1756.chapter_heading_strict is True
    assert inline_1756.section_in_act_strict is False
    assert inline_1756.section_in_act_split_tolerant is False
    assert inline_1756.full_citation_bound_normalized is False


@pytest.mark.parametrize(
    ("bad_volume", "bad_page", "bad_congress", "bad_key"),
    [
        (0, 1, None, None),
        (65, 1, None, None),
        (True, 1, None, None),
        (1, 0, None, None),
        (1, False, None, None),
        (1, 10, 0, None),
        (1, 10, True, None),
        (1, 10, None, "85-1"),
    ],
)
def test_resolve_statutes_volume_rejects_out_of_domain_inputs(
    bad_volume: object, bad_page: object, bad_congress: object, bad_key: str | None
) -> None:
    with pytest.raises(LocStatutesError):
        resolve_statutes_volume(
            bad_volume,  # type: ignore[arg-type]
            statutes_at_large_page=bad_page,  # type: ignore[arg-type]
            congress=bad_congress,  # type: ignore[arg-type]
            table3_key=bad_key,
        )


def test_parse_enactment_year_from_table3_key() -> None:
    assert parse_enactment_year_from_table3_key("1798:66") == 1798
    assert parse_enactment_year_from_table3_key(" 1948:758 ") == 1948
    assert parse_enactment_year_from_table3_key("85-1") is None
    assert parse_enactment_year_from_table3_key(None) is None


def test_llsalvol_page_stem_accepts_0043r000_and_url_builders_validate_bounds() -> None:
    """Accepts Vol. 52's 0043r000.alto.xml unnumbered Roman separator while rejecting frame 0."""

    arabic = parse_llsalvol_page_stem("06940570.alto.xml")
    assert (arabic.stem, arabic.scan_frame, arabic.kind, arabic.page_number) == ("06940570", 694, "arabic", 570)

    roman = parse_llsalvol_page_stem("0041r045")
    assert (roman.stem, roman.scan_frame, roman.kind, roman.page_number) == ("0041r045", 41, "roman", 45)

    roman_zero = parse_llsalvol_page_stem("0043r000.alto.xml")
    assert (roman_zero.stem, roman_zero.scan_frame, roman_zero.kind, roman_zero.page_number) == (
        "0043r000",
        43,
        "unnumbered",
        None,
    )

    unnumbered = parse_llsalvol_page_stem("00010000.jp2")
    assert (unnumbered.stem, unnumbered.scan_frame, unnumbered.kind, unnumbered.page_number) == (
        "00010000",
        1,
        "unnumbered",
        None,
    )

    urls_v52 = llsalvol_segment_urls(52, stem="0043r000.alto.xml", sequence_index_1based=43)
    assert urls_v52["alto_xml_url"].endswith("/llsal_052/0043r000.alto.xml")

    for bad_stem in ("short", "00000570", "0000r001", "0000r000", "abcdefgh"):
        with pytest.raises(LocStatutesError):
            parse_llsalvol_page_stem(bad_stem)

    with pytest.raises(LocStatutesError, match="Volume 18 requires part_suffix"):
        llsalvol_segment_urls(18, stem="00100001", sequence_index_1based=10)
    with pytest.raises(LocStatutesError, match="Volume 44 accepts only"):
        llsalvol_segment_urls(44, stem="00100001", sequence_index_1based=10, part_suffix="b")
    with pytest.raises(LocStatutesError, match="only Volumes 18 and 44"):
        llsalvol_segment_urls(1, stem="06940570", sequence_index_1based=693, part_suffix="a")


def test_extract_llsl_pdf_ocr_layers_reader_reuse_3tr_and_font_classification() -> None:
    """Reuses PdfReader, checks 3 Tr operators, isolates third-class fonts, and handles blank pages."""

    dual_bytes = _build_synthetic_llsl_pdf(
        include_type1=True,
        include_invisible_ocr=True,
        render_mode=3,
        extra_non_legacy_font="/CustomStampFont",
    )
    shared_reader = PdfReader(io.BytesIO(dual_bytes))
    layers = extract_llsl_pdf_ocr_layers(shared_reader, 1)
    assert layers.has_legacy_type1_layer is True
    assert layers.has_invisible_ocr_layer is True
    assert layers.has_dual_ocr_collision is True
    assert layers.uses_invisible_render_mode_3tr is True
    assert layers.other_font_names == ("/CustomStampFont",)
    assert layers.other_font_text == "STAMP"
    assert "STAMP" not in layers.layer1_type1_text
    assert layers.layer1_header_text == "570 FIFTH CONGRESS. SESS. II. C. 58. 1798."
    assert normalize_split_smallcaps_designators(layers.layer2_invisible_ocr_text).endswith(
        "CHAP. LVIII. SECTION 1. Be it enacted"
    )

    visible_pdf = _build_synthetic_llsl_pdf(include_type1=True, include_invisible_ocr=False, render_mode=0)
    vis_layers = extract_llsl_pdf_ocr_layers(visible_pdf, 1)
    assert vis_layers.uses_invisible_render_mode_3tr is False
    assert vis_layers.has_dual_ocr_collision is False

    # Setting 3 Tr and immediately resetting to 0 Tr before any Tj must report uses_invisible_render_mode_3tr=False!
    reset_writer = PdfWriter()
    reset_page = reset_writer.add_blank_page(width=612, height=792)
    f_ref = reset_writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Times-Roman"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )
    reset_page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F5"): f_ref})})
    reset_stream = DecodedStreamObject()
    reset_stream.set_data(b"BT 3 Tr 0 Tr /F5 11 Tf (Visible text after 3 Tr reset) Tj ET")
    reset_page[NameObject("/Contents")] = reset_writer._add_object(reset_stream)
    reset_buf = io.BytesIO()
    reset_writer.write(reset_buf)
    assert extract_llsl_pdf_ocr_layers(reset_buf.getvalue(), 1).uses_invisible_render_mode_3tr is False

    blank_writer = PdfWriter()
    blank_writer.add_blank_page(width=612, height=792)
    blank_buf = io.BytesIO()
    blank_writer.write(blank_buf)
    blank_layers = extract_llsl_pdf_ocr_layers(blank_buf.getvalue(), 1)
    assert blank_layers.has_legacy_type1_layer is False
    assert blank_layers.has_invisible_ocr_layer is False
    assert blank_layers.uses_invisible_render_mode_3tr is False

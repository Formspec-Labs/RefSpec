"""Offline fast-tier verification for Library of Congress pre-1951 Statutes at Large (Vols. 1-64)."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from pypdf import PdfWriter
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
    llsalvol_segment_urls,
    load_llsl_catalog,
    load_llsl_ocr_verification_manifest,
    normalize_split_smallcaps_designators,
    parse_enactment_year_from_table3_key,
    parse_llsalvol_page_stem,
    resolve_statutes_volume,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_synthetic_llsl_pdf(*, include_type1: bool, include_invisible_ocr: bool) -> bytes:
    """Build a minimal 1-page PDF reproducing LoC llsl's dual-font 3 Tr content-stream layout."""

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    fonts = DictionaryObject()
    ops: list[str] = ["BT", "3 Tr"]
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
        ops.append("/F5 11 Tf 72 720 Td (FIFTH CONGRESS. SESS. II. C. 58. 1798. SECTION 1. Be it enacted) Tj")
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
        ops.append("/FXF1 11 Tf 72 720 Td (570 FIFTH CONGRESS. Sass. IL Cn. 58. 1798. S ECTION 1. Be it enacted) Tj")
    ops.append("ET")

    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pinned_llsl_catalog_invariants_across_all_64_volumes() -> None:
    """Pins the 64-volume LoC Statutes at Large catalogue structure (97 PDFs, 69 llsalvol objects)."""

    catalog = load_llsl_catalog(REPO_ROOT)
    assert tuple(sorted(catalog)) == tuple(range(1, 65))

    total_pdfs = sum(len(v.pdf_resources) for v in catalog.values())
    assert total_pdfs == 97

    single_pdf_vols = [v.volume for v in catalog.values() if len(v.pdf_resources) == 1]
    multi_pdf_vols = [v.volume for v in catalog.values() if len(v.pdf_resources) > 1]
    assert len(single_pdf_vols) == 52
    assert multi_pdf_vols == [1, 2, 3, 4, 5, 9, 10, 11, 12, 18, 20, 44]

    total_llsalvol = sum(len(v.llsalvol_resources) for v in catalog.values())
    assert total_llsalvol == 69
    multi_llsalvol_vols = [v.volume for v in catalog.values() if len(v.llsalvol_resources) > 1]
    assert multi_llsalvol_vols == [18, 44]
    assert [r.url.rstrip("/").rsplit(".", 1)[-1] for r in catalog[18].llsalvol_resources] == [
        "llsal_018a",
        "llsal_018b",
        "llsal_018c",
        "llsal_018d",
        "llsal_018e",
    ]
    assert [r.url.rstrip("/").rsplit(".", 1)[-1] for r in catalog[44].llsalvol_resources] == [
        "llsal_044",
        "llsal_044a",
    ]

    for vol, entry in catalog.items():
        assert entry.shelf_id == f"llsl-v{vol}"
        assert entry.item_url == f"https://www.loc.gov/item/llsl-v{vol}/"
        for pdf in entry.pdf_resources:
            assert "//llsl-" in pdf.published_pdf_url
            assert "//llsl-" not in pdf.normalized_pdf_url.split("://", 1)[1]
            assert pdf.filename.endswith(".pdf")


def test_pinned_ocr_verification_manifest_verdict_and_specimen_consistency() -> None:
    """Pins the 10-PDF / 19,555-page dual-OCR verdict and all 16 multi-era specimens."""

    manifest = load_llsl_ocr_verification_manifest(REPO_ROOT)
    verdict = manifest["verdict"]
    assert verdict["embedded_ocr_present_in_all_sampled_pdfs"] is True
    assert verdict["sampled_pdf_count"] == 10
    assert verdict["sampled_total_pdf_pages"] == 19_555

    pdfs = manifest["pinned_pdfs"]
    assert len(pdfs) == 10
    assert sum(p["pages"] for p in pdfs) == 19_555
    assert {p["volume"] for p in pdfs} == {1, 2, 23, 24, 38, 49, 51, 54, 60, 62}
    for pdf in pdfs:
        assert pdf["sha256"].startswith("sha256:") and len(pdf["sha256"]) == 71
        assert pdf["has_invisible_ocr"] is True
        assert pdf["has_legacy_type1_ocr"] is True
        assert pdf["producer"] == "Foxit FXPDFA 1.2"

    acc = verdict["accuracy_summary"]
    specimens = manifest["specimens"]
    assert len(specimens) == 16
    assert acc == {
        "specimen_count": 16,
        "specimens_with_printed_section_label": 12,
        "layer1_page_number_exact": 15,
        "layer2_page_number_exact": 16,
        "union_page_number_exact": 16,
        "layer1_chapter_number_exact": 15,
        "layer2_chapter_number_exact": 15,
        "union_chapter_number_exact": 16,
        "layer1_section_strict": 12,
        "layer2_section_strict": 4,
        "layer2_section_split_tolerant": 12,
        "union_section_split_tolerant": 12,
    }

    # Recompute every summary figure from specimen rows to guard against internal drift.
    with_sec = [s for s in specimens if s["printed_section_tested"] is not None]
    assert len(with_sec) == 12
    assert sum(1 for s in specimens if s["layer1_metrics"]["page_number_present"]) == 15
    assert sum(1 for s in specimens if s["layer2_metrics"]["page_number_present"]) == 16
    assert sum(1 for s in specimens if s["union_metrics"]["chapter_number_present"]) == 16
    assert sum(1 for s in with_sec if s["layer1_metrics"]["section_label_strict"]) == 12
    assert sum(1 for s in with_sec if s["layer2_metrics"]["section_label_strict"]) == 4
    assert sum(1 for s in with_sec if s["layer2_metrics"]["section_label_split_tolerant"]) == 12
    for s in specimens:
        assert s["pdf_page_1based"] - s["stat_page"] == s["pdf_minus_stat_offset"]
        assert s["chars_pdftotext_spatial_collided"] > max(
            s["chars_layer1_2007_type1"], s["chars_layer2_2021_invisible_ocr"]
        )


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


def test_resolve_statutes_volume_single_narrowed_and_ambiguous_cases() -> None:
    """Tests single-PDF resolution, table3_key/Congress narrowing, and refusal to guess on multi-PDF overlaps."""

    catalog = load_llsl_catalog(REPO_ROOT)

    # Single-PDF volume (60 Stat. 237, Administrative Procedure Act)
    apa = resolve_statutes_volume(60, statutes_at_large_page=237, table3_key="1946:324", catalog=catalog)
    assert apa.pdf_resolution_status == "single_volume_pdf"
    assert apa.unique_pdf is not None
    assert apa.unique_pdf.filename == "llsl-c79s2.pdf"
    assert apa.llsalvol_is_single_object is True

    # Multi-Congress Vol. 1 narrowed uniquely by 1798:66 (Alien Enemies Act, 1 Stat. 577)
    aea = resolve_statutes_volume(1, statutes_at_large_page=577, table3_key="1798:66", catalog=catalog)
    assert aea.pdf_resolution_status == "narrowed_by_year"
    assert aea.unique_pdf is not None
    assert aea.unique_pdf.filename == "llsl-c5.pdf"

    # Multi-Congress Vol. 1 without year/key must NOT guess among 5 Congress PDFs
    unscoped_v1 = resolve_statutes_volume(1, statutes_at_large_page=577, catalog=catalog)
    assert unscoped_v1.pdf_resolution_status == "ambiguous_multi_part_volume"
    assert unscoped_v1.unique_pdf is None
    assert len(unscoped_v1.candidate_pdfs) == 5

    # Congress-transition year 1807 in Vol. 2 overlaps 9th Congress (1805/1807) and 10th Congress (1807/1809)
    ins_year_only = resolve_statutes_volume(2, statutes_at_large_page=443, table3_key="1807:39", catalog=catalog)
    assert ins_year_only.pdf_resolution_status == "ambiguous_multi_part_volume"
    assert [p.filename for p in ins_year_only.candidate_pdfs] == ["llsl-c9.pdf", "llsl-c10.pdf"]

    # Supplying congress=9 resolves 1807:39 uniquely to llsl-c9.pdf
    ins_cong = resolve_statutes_volume(
        2, statutes_at_large_page=443, table3_key="1807:39", congress=9, catalog=catalog
    )
    assert ins_cong.pdf_resolution_status == "narrowed_by_year"
    assert ins_cong.unique_pdf is not None and ins_cong.unique_pdf.filename == "llsl-c9.pdf"

    # Vol. 18: bare year 1874 keeps Revised Statutes/DC/Post-Roads parts ambiguous, whereas YYYY:ch session-law key narrows to llsl-c43.pdf
    v18_bare_year = resolve_statutes_volume(18, enactment_year=1874, catalog=catalog)
    assert v18_bare_year.pdf_resolution_status == "ambiguous_multi_part_volume"
    assert len(v18_bare_year.candidate_pdfs) == 4
    assert v18_bare_year.llsalvol_is_single_object is False

    v18_session_law = resolve_statutes_volume(18, table3_key="1874:390", catalog=catalog)
    assert v18_session_law.pdf_resolution_status == "narrowed_by_year"
    assert v18_session_law.unique_pdf is not None and v18_session_law.unique_pdf.filename == "llsl-c43.pdf"


@pytest.mark.parametrize(
    ("bad_volume", "bad_page", "bad_congress"),
    [
        (0, 1, None),
        (65, 1, None),
        (-3, 1, None),
        (True, 1, None),
        (1, 0, None),
        (1, -10, None),
        (1, False, None),
        (1, 10, 0),
        (1, 10, True),
    ],
)
def test_resolve_statutes_volume_rejects_out_of_domain_inputs(
    bad_volume: object, bad_page: object, bad_congress: object
) -> None:
    """Negative gate: volumes outside 1..64 (e.g. post-1950 Vol. 65), booleans, or non-positive pages/congress fail."""

    with pytest.raises(LocStatutesError):
        resolve_statutes_volume(
            bad_volume,  # type: ignore[arg-type]
            statutes_at_large_page=bad_page,  # type: ignore[arg-type]
            congress=bad_congress,  # type: ignore[arg-type]
        )


def test_parse_enactment_year_from_table3_key() -> None:
    assert parse_enactment_year_from_table3_key("1798:66") == 1798
    assert parse_enactment_year_from_table3_key(" 1948:758 ") == 1948
    assert parse_enactment_year_from_table3_key("85-1") is None
    assert parse_enactment_year_from_table3_key("1798:0") is None
    assert parse_enactment_year_from_table3_key(None) is None


def test_llsalvol_page_stem_and_url_builders_positive_and_negative() -> None:
    """Tests 8-character METS/ALTO page-stem parsing and Vol. 18 / Vol. 44 part_suffix rules."""

    arabic = parse_llsalvol_page_stem("https://tile.loc.gov/storage-services/service/ll/llsalvol/llsal_001/06940570.alto.xml")
    assert (arabic.stem, arabic.scan_frame, arabic.kind, arabic.page_number) == ("06940570", 694, "arabic", 570)

    roman = parse_llsalvol_page_stem("0041r045")
    assert (roman.stem, roman.scan_frame, roman.kind, roman.page_number) == ("0041r045", 41, "roman", 45)

    unnumbered = parse_llsalvol_page_stem("00010000.jp2")
    assert (unnumbered.stem, unnumbered.scan_frame, unnumbered.kind, unnumbered.page_number) == (
        "00010000",
        1,
        "unnumbered",
        None,
    )

    urls_v1 = llsalvol_segment_urls(1, stem="06940570.alto.xml", sequence_index_1based=693)
    assert urls_v1 == {
        "viewer_url": "https://www.loc.gov/resource/llsalvol.llsal_001/?sp=693",
        "alto_xml_url": "https://tile.loc.gov/storage-services/service/ll/llsalvol/llsal_001/06940570.alto.xml",
        "jp2_url": "https://tile.loc.gov/storage-services/service/ll/llsalvol/llsal_001/06940570.jp2",
        "iiif_full_jpg_url": "https://tile.loc.gov/image-services/iiif/service:ll:llsalvol:llsal_001:06940570/full/pct:100/0/default.jpg",
    }

    urls_v18 = llsalvol_segment_urls(18, stem="00100001", sequence_index_1based=10, part_suffix="a")
    assert "llsal_018a/00100001.alto.xml" in urls_v18["alto_xml_url"]

    urls_v44a = llsalvol_segment_urls(44, stem="00050001", sequence_index_1based=5, part_suffix="a")
    assert "llsal_044a/00050001.alto.xml" in urls_v44a["alto_xml_url"]

    for bad_stem in ("short", "00000570", "0000r001", "0010r000", "abcdefgh"):
        with pytest.raises(LocStatutesError):
            parse_llsalvol_page_stem(bad_stem)

    with pytest.raises(LocStatutesError, match="Volume 18 requires part_suffix"):
        llsalvol_segment_urls(18, stem="00100001", sequence_index_1based=10)
    with pytest.raises(LocStatutesError, match="Volume 44 accepts only"):
        llsalvol_segment_urls(44, stem="00100001", sequence_index_1based=10, part_suffix="b")
    with pytest.raises(LocStatutesError, match="only Volumes 18 and 44"):
        llsalvol_segment_urls(1, stem="06940570", sequence_index_1based=693, part_suffix="a")
    with pytest.raises(LocStatutesError):
        llsalvol_segment_urls(1, stem="06940570", sequence_index_1based=0)
    with pytest.raises(LocStatutesError):
        llsalvol_segment_urls(True, stem="06940570", sequence_index_1based=1)  # type: ignore[arg-type]


def test_extract_llsl_pdf_ocr_layers_and_smallcaps_normalizer() -> None:
    """Separates Type 1 and /InvisibleOCR streams cleanly and normalizes Foxit small-caps splits."""

    dual_pdf = _build_synthetic_llsl_pdf(include_type1=True, include_invisible_ocr=True)
    layers = extract_llsl_pdf_ocr_layers(dual_pdf, 1)
    assert layers.page_number == 1
    assert layers.has_legacy_type1_layer is True
    assert layers.has_invisible_ocr_layer is True
    assert layers.has_dual_ocr_collision is True
    assert layers.font_names == ("/InvisibleOCR", "/Times-Roman")
    assert layers.layer1_type1_text == "FIFTH CONGRESS. SESS. II. C. 58. 1798. SECTION 1. Be it enacted"
    assert layers.layer2_invisible_ocr_text == "570 FIFTH CONGRESS. Sass. IL Cn. 58. 1798. S ECTION 1. Be it enacted"
    assert normalize_split_smallcaps_designators(layers.layer2_invisible_ocr_text).endswith(
        "SECTION 1. Be it enacted"
    )
    assert (
        normalize_split_smallcaps_designators("C HAP. 164. S EC. 201. S ECTION 3.")
        == "CHAP. 164. SEC. 201. SECTION 3."
    )

    single_pdf = _build_synthetic_llsl_pdf(include_type1=False, include_invisible_ocr=True)
    single_layers = extract_llsl_pdf_ocr_layers(single_pdf, 1)
    assert single_layers.has_legacy_type1_layer is False
    assert single_layers.has_invisible_ocr_layer is True
    assert single_layers.has_dual_ocr_collision is False

    with pytest.raises(LocStatutesError, match="exceeds PDF page count"):
        extract_llsl_pdf_ocr_layers(dual_pdf, 2)
    with pytest.raises(LocStatutesError, match="1-based positive integer"):
        extract_llsl_pdf_ocr_layers(dual_pdf, 0)
    with pytest.raises(LocStatutesError, match="1-based positive integer"):
        extract_llsl_pdf_ocr_layers(dual_pdf, True)  # type: ignore[arg-type]

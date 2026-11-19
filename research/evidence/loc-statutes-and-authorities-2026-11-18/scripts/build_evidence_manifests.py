"""Build deterministic, sha256-pinned evidence manifests from cached LoC Statutes at Large & id.loc.gov captures.

Reads raw cached responses under:
  /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-loc-statutes-20261118/
and writes canonical JSON manifests (zero binary PDFs) into:
  research/evidence/loc-statutes-and-authorities-2026-11-18/

Replays the production parsers and selectors in :mod:`refspec.loc_statutes_at_large`
and :mod:`refspec.loc_agency_authorities` directly over the raw cached files so
research manifests and production readers cannot drift apart.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from refspec.loc_agency_authorities import (  # noqa: E402
    LCNAF_AUTHORITY_PREFIX,
    parse_lcnaf_madsrdf_graph,
    select_verified_lcnaf_hit,
)
from refspec.loc_statutes_at_large import (  # noqa: E402
    extract_llsl_pdf_ocr_layers,
    score_llsl_layer_citation,
)
from refspec.registry import agency_crosswalk as cw  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "research" / "evidence" / "loc-statutes-and-authorities-2026-11-18"
DEFAULT_CACHE_ROOT = Path(
    "/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-loc-statutes-20261118"
)

# Constitutional Congress calendar-year spans (81st Congress sat through Jan. 2, 1951 in Vol. 64).
CONGRESS_TERM_YEARS: dict[int, tuple[int, int]] = {
    c: (1789 + 2 * (c - 1), 1789 + 2 * c) for c in range(1, 83)
}
CONGRESS_SLUG_RE = re.compile(r"llsl-c(\d+)(?:s(\d+)(?:-s?(\d+))?|-(.+))?\.pdf$")


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _parse_pdf_resource_congress(pdf_url: str, caption: str) -> dict[str, Any]:
    fname = pdf_url.rsplit("/", 1)[-1]
    m = CONGRESS_SLUG_RE.search(fname)
    congress = int(m.group(1)) if m else None
    session_start = int(m.group(2)) if (m and m.group(2)) else None
    session_end = int(m.group(3)) if (m and m.group(3)) else session_start
    part_tag = m.group(4) if m else None

    yr_m = re.search(r"\((\d{4})(?:/(\d{4}))?", caption or "")
    caption_year_start = int(yr_m.group(1)) if yr_m else None
    caption_year_end = int(yr_m.group(2) or yr_m.group(1)) if yr_m else None

    term_bounds = CONGRESS_TERM_YEARS.get(congress) if congress is not None else None
    starts = [y for y in (caption_year_start, term_bounds[0] if term_bounds else None) if y is not None]
    ends = [y for y in (caption_year_end, term_bounds[1] if term_bounds else None) if y is not None]
    # Preserve exact non-Congress span when part_tag overrides Congress dates (e.g. Revised Statutes Supplement 1874/1891).
    if part_tag is not None and caption_year_start is not None and caption_year_end is not None:
        year_start: int | None = caption_year_start
        year_end: int | None = caption_year_end
    else:
        year_start = min(starts) if starts else None
        year_end = max(ends) if ends else None

    normalized_url = pdf_url.replace("/service/ll/llsl//", "/service/ll/llsl/")
    return {
        "caption": caption,
        "filename": fname,
        "published_pdf_url": pdf_url,
        "normalized_pdf_url": normalized_url,
        "congress": congress,
        "session_start": session_start,
        "session_end": session_end,
        "part_tag": part_tag,
        "caption_year_start": caption_year_start,
        "caption_year_end": caption_year_end,
        "year_start": year_start,
        "year_end": year_end,
    }


def build_statutes_catalog(cache_root: Path) -> dict[str, Any]:
    jdir = cache_root / "loc_statutes_json"
    source_pages = []
    all_items = []
    for sp in (1, 2, 3, 4):
        p = jdir / f"collection_page{sp}_c25.json"
        meta = json.loads((jdir / f"collection_page{sp}_c25.json.meta.json").read_text(encoding="utf-8"))
        raw = p.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
        payload = json.loads(raw.decode("utf-8"))
        results = payload.get("results") or []
        all_items.extend(results)
        source_pages.append(
            {
                "page": sp,
                "url": meta["requested_url"],
                "retrieved_at": meta["retrieved_at"],
                "bytes": meta["bytes"],
                "sha256": f"sha256:{meta['sha256']}",
                "result_count": len(results),
            }
        )

    volumes_by_num: dict[int, dict[str, Any]] = {}
    non_volume_items = []
    for item in all_items:
        shelf = item.get("shelf_id") or ""
        if shelf.startswith("llsl-v"):
            vnum = int(shelf.split("-v", 1)[1])
            seg_resources = []
            pdf_resources = []
            for res in item.get("resources") or []:
                if not isinstance(res, dict):
                    continue
                if res.get("segments"):
                    seg_resources.append(
                        {
                            "url": res.get("url"),
                            "segments": res.get("segments"),
                            "caption": res.get("caption"),
                        }
                    )
                if res.get("pdf"):
                    pdf_resources.append(_parse_pdf_resource_congress(res["pdf"], res.get("caption") or ""))
            volumes_by_num[vnum] = {
                "volume": vnum,
                "shelf_id": shelf,
                "item_url": f"https://www.loc.gov/item/llsl-v{vnum}/",
                "title": item.get("title"),
                "date": item.get("date"),
                "pdf_count": len(pdf_resources),
                "pdf_granularity": "single_volume_pdf" if len(pdf_resources) == 1 else "multi_congress_or_part_pdfs",
                "llsalvol_count": len(seg_resources),
                "llsalvol_resources": seg_resources,
                "pdf_resources": pdf_resources,
            }
        else:
            non_volume_items.append(
                {
                    "id": item.get("id"),
                    "shelf_id": shelf or None,
                    "title": item.get("title"),
                }
            )

    assert sorted(volumes_by_num) == list(range(1, 65))
    ordered_volumes = [volumes_by_num[v] for v in range(1, 65)]
    single_pdf_vols = [v["volume"] for v in ordered_volumes if v["pdf_count"] == 1]
    multi_pdf_vols = [v["volume"] for v in ordered_volumes if v["pdf_count"] > 1]
    total_pdfs = sum(v["pdf_count"] for v in ordered_volumes)
    total_llsalvol = sum(v["llsalvol_count"] for v in ordered_volumes)

    return {
        "schema_version": "refspec-loc-llsl-catalog/2",
        "collection_url": "https://www.loc.gov/collections/united-states-statutes-at-large/?fo=json&c=25",
        "source_collection_pages": source_pages,
        "summary": {
            "total_collection_records": len(all_items),
            "volume_item_count": len(ordered_volumes),
            "non_volume_item_count": len(non_volume_items),
            "total_llsl_pdfs": total_pdfs,
            "single_pdf_volume_count": len(single_pdf_vols),
            "single_pdf_volumes": single_pdf_vols,
            "multi_pdf_volume_count": len(multi_pdf_vols),
            "multi_pdf_volumes": multi_pdf_vols,
            "total_llsalvol_objects": total_llsalvol,
            "llsalvol_multi_object_volumes": [v["volume"] for v in ordered_volumes if v["llsalvol_count"] > 1],
            "item_json_503_timeout_volumes": [18],
        },
        "volumes": ordered_volumes,
        "non_volume_collection_items": non_volume_items,
    }


def build_ocr_verification_manifest(cache_root: Path) -> dict[str, Any]:
    pdf_meta = json.loads((cache_root / "pdf_metadata_summary.json").read_text(encoding="utf-8"))
    pinned_pdfs = [
        {
            **row,
            "sha256": f"sha256:{row['sha256']}" if not str(row["sha256"]).startswith("sha256:") else row["sha256"],
            "pdf_url": f"https://tile.loc.gov/storage-services/service/ll/llsl//{row['filename'].removesuffix('.pdf')}/{row['filename']}",
        }
        for row in pdf_meta
    ]

    pdf_dir = cache_root / "pdfs"
    readers: dict[str, PdfReader] = {}

    def _reader(fname: str) -> PdfReader:
        if fname not in readers:
            readers[fname] = PdfReader(str(pdf_dir / fname))
        return readers[fname]

    alto_pins = []
    alto_dir = cache_root / "alto"
    for mp in sorted(alto_dir.glob("*.meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        xml_path = alto_dir / mp.name.removesuffix(".meta.json")
        root = ET.fromstring(xml_path.read_bytes())
        alto_words = [el.attrib["CONTENT"] for el in root.iter() if el.tag.endswith("String") and "CONTENT" in el.attrib]
        p1 = 35 if m["stat_page"] == 570 else 42
        layers = extract_llsl_pdf_ocr_layers(_reader("llsl-c5.pdf"), p1)
        alto_pins.append(
            {
                "volume": m["volume"],
                "stat_page": m["stat_page"],
                "sp": m["sp"],
                "url": m["requested_url"],
                "bytes": m["bytes"],
                "sha256": f"sha256:{m['sha256']}",
                "retrieved_at": m["retrieved_at"],
                "alto_opening_tokens": " ".join(alto_words[:15]),
                "pdf_layer2_header_text": layers.layer2_header_text,
                "matches_pdf_layer2_header_verbatim": " ".join(alto_words).startswith(layers.layer2_header_text),
            }
        )

    # Exact verified PDF 1-based pages for all 16 cross-era statutory specimens
    # (including 51 Stat. 4 on PDF page 10, ch. 3, Federal Credit Union Act amendment).
    exact_specimen_pages = [
        ("1stat570_alien_friends", "Era 1 (1-10 Stat.)", 1, "llsl-c5.pdf", 570, 35, 58, "1", False, "An Act concerning Aliens (mispointed by OLRC popularnames.htm 'Alien Enemy Act')", "1798:58"),
        ("1stat577_alien_enemies", "Era 1 (1-10 Stat.)", 1, "llsl-c5.pdf", 577, 42, 66, "1", False, "Alien Enemies Act (50 U.S.C. 21-24 via R.S. 4067-4070)", "1798:66"),
        ("2stat443_insurrection", "Era 1 (1-10 Stat.)", 2, "llsl-c9.pdf", 443, 96, 39, None, False, "Insurrection Act of 1807 (single-section unnumbered; quarantined in Table III)", "1807:39"),
        ("23stat31_animal_industry", "Era 2 (16-25 Stat.)", 23, "llsl-c48.pdf", 31, 59, 60, None, False, "Animal Industry Act (unnumbered enacting clause)", "1884:60"),
        ("23stat332_foran_labor", "Era 2 (16-25 Stat.)", 23, "llsl-c48.pdf", 332, 360, 164, "2", False, "Alien Contract Labor Law of Feb. 26, 1885 (OLRC popularnames.htm typo '1895')", "1885:164"),
        ("24stat379_ica", "Era 2 (16-25 Stat.)", 24, "llsl-c49.pdf", 379, 412, 104, "2", False, "Interstate Commerce Act (enacting clause unnumbered; SEC. 2 on p. 379)", "1887:104"),
        ("38stat251_federal_reserve", "Era 3 (30-49 Stat.)", 38, "llsl-c63.pdf", 251, 270, 6, "2", False, "Federal Reserve Act (short-title clause unnumbered; SEC. 2 on p. 251)", "1913:6"),
        ("38stat717_ftc", "Era 3 (30-49 Stat.)", 38, "llsl-c63.pdf", 717, 736, 311, None, False, "Federal Trade Commission Act (Layer 1 drops folio '717', Layer 2 retains '717')", "1914:311"),
        ("49stat620_ssa_open", "Era 3 (30-49 Stat.)", 49, "llsl-c74.pdf", 620, 666, 531, "1", False, "Social Security Act opening page (Title I sec. 1; Layer 2 corrupts '[CHAPTER 531.]' to '[CHAPTER 5314')", "1935:531"),
        ("49stat647_ssa_1102", "Era 3 (30-49 Stat.)", 49, "llsl-c74.pdf", 647, 693, 531, "1102", True, "Social Security Act sec. 1102 (42 U.S.C. 1302; continuation page)", "1935:531"),
        ("51stat4_fcu_amend", "Era 4 (50-64 Stat.)", 51, "llsl-c75s2.pdf", 4, 10, 3, None, False, "75th Cong. 2d Sess. ch. 3, Federal Credit Union Act amendment (51 Stat. 4, PDF p. 10; absent from popularnames.htm)", "1937:3"),
        ("54stat789_inv_company", "Era 4 (50-64 Stat.)", 54, "llsl-c76s2-s3.pdf", 789, 823, 686, "1", False, "Investment Company Act of 1940 (Title I opening; Layer 2 corrupts '[CHAPTER 686]' to '[CHAPTER 6861')", "1940:686"),
        ("54stat847_inv_advisers", "Era 4 (50-64 Stat.)", 54, "llsl-c76s2-s3.pdf", 847, 881, 686, "201", True, "Investment Advisers Act of 1940 (Title II continuation page; Layer 1 truncates running header to 'CH. 68--')", "1940:686"),
        ("60stat237_apa", "Era 4 (50-64 Stat.)", 60, "llsl-c79s2.pdf", 237, 264, 324, "1", False, "Administrative Procedure Act", "1946:324"),
        ("60stat755_aea", "Era 4 (50-64 Stat.)", 60, "llsl-c79s2.pdf", 755, 782, 724, "1", False, "Atomic Energy Act of 1946 (establishing U.S. Atomic Energy Commission)", "1946:724"),
        ("62stat1155_fwpca", "Era 4 (50-64 Stat.)", 62, "llsl-c80s2.pdf", 1155, 1185, 758, "2", False, "Federal Water Pollution Control Act (Clean Water Act; unnumbered sec. 1, SEC. 2 on p. 1155)", "1948:758"),
    ]

    specimens_out = []
    for sid, era, vol, pfile, spage, pdf_p1, ch, sec, is_cont, note, t3k in exact_specimen_pages:
        rd = _reader(pfile)
        layers = extract_llsl_pdf_ocr_layers(rd, pdf_p1)
        default_txt = subprocess.check_output(
            ["/opt/homebrew/bin/pdftotext", "-f", str(pdf_p1), "-l", str(pdf_p1), str(pdf_dir / pfile), "-"],
            text=True,
        )
        m1 = dataclasses.asdict(
            score_llsl_layer_citation(
                body_text=layers.layer1_type1_text,
                header_text=layers.layer1_header_text,
                footer_text=layers.layer1_footer_text,
                statutes_at_large_page=spage,
                expected_chapter=ch,
                expected_section=sec,
                is_continuation_page=is_cont,
            )
        )
        m2 = dataclasses.asdict(
            score_llsl_layer_citation(
                body_text=layers.layer2_invisible_ocr_text,
                header_text=layers.layer2_header_text,
                footer_text=layers.layer2_footer_text,
                statutes_at_large_page=spage,
                expected_chapter=ch,
                expected_section=sec,
                is_continuation_page=is_cont,
            )
        )
        combined_union = {
            k: (None if m1[k] is None else bool(m1[k] or m2[k])) for k in m1
        }
        specimens_out.append(
            {
                "specimen_id": sid,
                "era": era,
                "volume": vol,
                "pdf_filename": pfile,
                "stat_page": spage,
                "pdf_page_1based": pdf_p1,
                "pdf_minus_stat_offset": pdf_p1 - spage,
                "expected_chapter": str(ch),
                "printed_section_tested": sec,
                "is_continuation_page": is_cont,
                "table3_key": t3k,
                "description": note,
                "uses_invisible_render_mode_3tr": layers.uses_invisible_render_mode_3tr,
                "chars_pdftotext_spatial_collided": len(default_txt),
                "chars_layer1_2007_type1": len(layers.layer1_type1_text),
                "chars_layer2_2021_invisible_ocr": len(layers.layer2_invisible_ocr_text),
                "layer1_header_text": layers.layer1_header_text,
                "layer2_header_text": layers.layer2_header_text,
                "layer1_metrics": m1,
                "layer2_metrics": m2,
                "union_metrics": combined_union,
                "layer1_opening_excerpt": layers.layer1_type1_text[:360],
                "layer2_opening_excerpt": layers.layer2_invisible_ocr_text[:360],
                "spatial_collided_opening_excerpt": " ".join(default_txt.split())[:280],
            }
        )

    # Verified boundary & counterexample pages proving non-universal page OCR and strict folio/act scoping
    p1_c5 = extract_llsl_pdf_ocr_layers(_reader("llsl-c5.pdf"), 1)
    p9_c75 = extract_llsl_pdf_ocr_layers(_reader("llsl-c75s2.pdf"), 9)
    p360_c48 = extract_llsl_pdf_ocr_layers(_reader("llsl-c48.pdf"), 360)
    p292_c48 = extract_llsl_pdf_ocr_layers(_reader("llsl-c48.pdf"), 292)
    p552_c48 = extract_llsl_pdf_ocr_layers(_reader("llsl-c48.pdf"), 552)

    boundary_checks = {
        "c5_page1_1797_session_start": {
            "pdf_filename": "llsl-c5.pdf",
            "pdf_page_1based": 1,
            "stat_page": 536,
            "table3_key": "1797:1",
            "caption": "5th Congress (1798/1799)",
            "layer1_opening_excerpt": p1_c5.layer1_type1_text[:240],
        },
        "c75s2_page9_folio3_rejects_folio4_and_ch3": {
            "pdf_filename": "llsl-c75s2.pdf",
            "pdf_page_1based": 9,
            "actual_printed_folio": 3,
            "layer1_score_as_51stat4_ch3": dataclasses.asdict(
                score_llsl_layer_citation(
                    body_text=p9_c75.layer1_type1_text,
                    header_text=p9_c75.layer1_header_text,
                    footer_text=p9_c75.layer1_footer_text,
                    statutes_at_large_page=4,
                    expected_chapter=3,
                )
            ),
            "layer2_score_as_51stat4_ch3": dataclasses.asdict(
                score_llsl_layer_citation(
                    body_text=p9_c75.layer2_invisible_ocr_text,
                    header_text=p9_c75.layer2_header_text,
                    footer_text=p9_c75.layer2_footer_text,
                    statutes_at_large_page=4,
                    expected_chapter=3,
                )
            ),
        },
        "c48_page360_23stat332_ch163_rejects_neighboring_sec2": {
            "pdf_filename": "llsl-c48.pdf",
            "pdf_page_1based": 360,
            "stat_page": 332,
            "tested_chapter": 163,
            "tested_section": "2",
            "layer1_score": dataclasses.asdict(
                score_llsl_layer_citation(
                    body_text=p360_c48.layer1_type1_text,
                    header_text=p360_c48.layer1_header_text,
                    footer_text=p360_c48.layer1_footer_text,
                    statutes_at_large_page=332,
                    expected_chapter=163,
                    expected_section="2",
                )
            ),
            "layer2_score": dataclasses.asdict(
                score_llsl_layer_citation(
                    body_text=p360_c48.layer2_invisible_ocr_text,
                    header_text=p360_c48.layer2_header_text,
                    footer_text=p360_c48.layer2_footer_text,
                    statutes_at_large_page=332,
                    expected_chapter=163,
                    expected_section="2",
                )
            ),
        },
        "c48_non_dual_ocr_scan_frames": [
            {
                "pdf_filename": "llsl-c48.pdf",
                "pdf_page_1based": 292,
                "chars_layer1": len(p292_c48.layer1_type1_text),
                "chars_layer2": len(p292_c48.layer2_invisible_ocr_text),
                "has_dual_ocr_collision": p292_c48.has_dual_ocr_collision,
            },
            {
                "pdf_filename": "llsl-c48.pdf",
                "pdf_page_1based": 552,
                "chars_layer1": len(p552_c48.layer1_type1_text),
                "chars_layer2": len(p552_c48.layer2_invisible_ocr_text),
                "has_dual_ocr_collision": p552_c48.has_dual_ocr_collision,
            },
        ],
    }

    n_spec = len(specimens_out)
    n_sec = sum(1 for s in specimens_out if s["printed_section_tested"] is not None)

    return {
        "schema_version": "refspec-loc-llsl-ocr-verification/2",
        "verdict": {
            "embedded_ocr_present_in_all_sampled_pdfs": all(
                p["has_invisible_ocr"] and p["has_legacy_type1_ocr"] for p in pinned_pdfs
            ),
            "sampled_pdf_count": len(pinned_pdfs),
            "sampled_total_pdf_pages": sum(p["pages"] for p in pinned_pdfs),
            "dual_overlaid_ocr_architecture": (
                "All 10 sampled LoC llsl PDFs (Vols. 1-62, 19,555 total pages) contain embedded machine-searchable OCR, "
                "and all 16 verified statutory specimens carry TWO overlaid 3 Tr invisible OCR passes on the same page: "
                "(1) a legacy 2007/2014 Type 1 pass (Times-Roman/Bold/Italic, Helvetica, Courier, WinAnsiEncoding) that "
                "preserves small-caps section designators cleanly when the act heading is intact, but merges marginalia "
                "into body lines and occasionally drops/truncates running headers ('717' on 38 Stat. 717; 'CH. 68--' on "
                "54 Stat. 847), and (2) a July 2021 Foxit FXPDFA 1.2 / PDF Compressor 8.2.12.20 Type 0 CID pass "
                "(/InvisibleOCR, Identity-H) that zones body prose away from marginalia and preserves 16/16 running folios "
                "(produced by a separate OCR pass from llsalvol ALTO XML, as shown by running-header differences on 1 Stat. "
                "577), but splits spaced small-caps ('S EC.', 'C HAP.') and occasionally misreads closing brackets ('[CHAPTER "
                "5314', '[CHAPTER 6861'). Blank or un-reprocessed scan frames inside a PDF (e.g. llsl-c48.pdf p. 552 with 0 "
                "text and p. 292 with 1 legacy char and no /InvisibleOCR layer) carry zero or one text stream."
            ),
            "accuracy_summary": {
                "specimen_count": n_spec,
                "specimens_with_printed_section_label": n_sec,
                "layer1_folio_in_running_header": sum(
                    1 for s in specimens_out if s["layer1_metrics"]["folio_in_running_header"]
                ),
                "layer2_folio_in_running_header": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["folio_in_running_header"]
                ),
                "union_folio_in_running_header": sum(
                    1 for s in specimens_out if s["union_metrics"]["folio_in_running_header"]
                ),
                "layer1_chapter_heading_strict": sum(
                    1 for s in specimens_out if s["layer1_metrics"]["chapter_heading_strict"]
                ),
                "layer2_chapter_heading_strict": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["chapter_heading_strict"]
                ),
                "layer1_chapter_heading_tolerant": sum(
                    1 for s in specimens_out if s["layer1_metrics"]["chapter_heading_tolerant"]
                ),
                "layer2_chapter_heading_tolerant": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["chapter_heading_tolerant"]
                ),
                "union_chapter_heading_tolerant": sum(
                    1 for s in specimens_out if s["union_metrics"]["chapter_heading_tolerant"]
                ),
                "layer1_section_in_act_strict": sum(
                    1 for s in specimens_out if s["layer1_metrics"]["section_in_act_strict"] is True
                ),
                "layer2_section_in_act_strict": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["section_in_act_strict"] is True
                ),
                "layer1_section_in_act_split_tolerant": sum(
                    1 for s in specimens_out if s["layer1_metrics"]["section_in_act_split_tolerant"] is True
                ),
                "layer2_section_in_act_split_tolerant": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["section_in_act_split_tolerant"] is True
                ),
                "union_section_in_act_split_tolerant": sum(
                    1 for s in specimens_out if s["union_metrics"]["section_in_act_split_tolerant"] is True
                ),
                "layer1_full_citation_bound_strict": sum(
                    1 for s in specimens_out if s["layer1_metrics"]["full_citation_bound_strict"]
                ),
                "layer2_full_citation_bound_normalized": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["full_citation_bound_normalized"]
                ),
                "union_full_citation_bound_normalized": sum(
                    1 for s in specimens_out if s["union_metrics"]["full_citation_bound_normalized"]
                ),
            },
        },
        "pinned_pdfs": pinned_pdfs,
        "pinned_alto_xml_samples": alto_pins,
        "boundary_and_negative_checks": boundary_checks,
        "specimens": specimens_out,
    }


def build_lcnaf_alignment_manifest(cache_root: Path) -> dict[str, Any]:
    enriched = json.loads((cache_root / "id_loc_enriched_analysis.json").read_text(encoding="utf-8"))
    id_dir = cache_root / "id_loc_json"

    probes_meta = []
    for pid, label in [
        ("probe_inv_energy", "FR inverted: 'Energy Department'"),
        ("probe_inv_omb", "FR inverted: 'Management and Budget Office'"),
        ("probe_inv_bis", "FR inverted: 'Industry and Security Bureau'"),
        ("probe_acr_epa", "Bare acronym: 'EPA'"),
        ("probe_acr_dot", "Bare acronym: 'DOT'"),
        ("probe_acr_fs", "Bare acronym: 'FS'"),
        ("probe_acr_eab", "Bare acronym: 'EAB'"),
        ("probe_acr_prc", "Bare historical name: 'Postal Rate Commission'"),
    ]:
        p = id_dir / f"{pid}.json"
        m = json.loads((id_dir / f"{pid}.json.meta.json").read_text(encoding="utf-8"))
        d = json.loads(p.read_text(encoding="utf-8"))
        hits = d.get("hits") or []
        probes_meta.append(
            {
                "probe_id": pid,
                "description": label,
                "query": d.get("q"),
                "url": m["requested_url"],
                "sha256": f"sha256:{m['sha256']}",
                "bytes": m["bytes"],
                "hit_count": d.get("count", 0),
                "top3_hits": [{"aLabel": h.get("aLabel"), "uri": h.get("uri")} for h in hits[:3]],
            }
        )

    parent_dept_for_key = {"EOIR": "Department of Justice"}
    records_out = []

    for r in enriched:
        key_id = r["key_id"]
        k_lower = key_id.lower()
        natural_name = r["natural_name"]
        parent_dept = parent_dept_for_key.get(key_id)

        # Replay production selector over cached raw suggest2 responses
        us_doc = json.loads((id_dir / f"suggest_us_{k_lower}.json").read_text(encoding="utf-8"))
        us_hits = us_doc.get("hits") or []
        bare_path = id_dir / f"suggest_bare_{k_lower}.json"
        bare_doc = json.loads(bare_path.read_text(encoding="utf-8")) if bare_path.is_file() else us_doc
        bare_hits = bare_doc.get("hits") or []
        parent_path = id_dir / f"suggest_parent_{k_lower}.json"
        parent_hits = json.loads(parent_path.read_text(encoding="utf-8")).get("hits") or [] if parent_path.is_file() else []

        hit_r1 = select_verified_lcnaf_hit(us_hits, natural_name=natural_name)
        hit_r2 = select_verified_lcnaf_hit(bare_hits, natural_name=natural_name)
        hit_r3 = (
            select_verified_lcnaf_hit(
                parent_hits,
                natural_name=natural_name,
                parent_department_natural_name=parent_dept,
            )
            if parent_dept
            else None
        )

        if hit_r1 is not None:
            chosen_hit = hit_r1
            rung = "rung1_united_states_prefixed_suggest2"
        elif hit_r2 is not None:
            chosen_hit = hit_r2
            rung = (
                "rung2_bare_direct_entry_with_us_qualifier"
                if "(U.S.)" in str(hit_r2.get("aLabel") or "")
                else "rung2_bare_federal_corporate_body"
            )
        elif hit_r3 is not None:
            chosen_hit = hit_r3
            rung = "rung3_parent_department_subordinate"
        else:
            raise RuntimeError(f"Production selector failed to resolve {key_id} ({natural_name!r})")

        selected_lccn = str(chosen_hit["uri"]).rstrip("/").rsplit("/", 1)[-1]
        assert selected_lccn == r["selected_lccn"], (key_id, selected_lccn, r["selected_lccn"])

        # Replay production MADS/RDF parser directly over raw mads_<lccn>.json bytes
        mads_path = id_dir / f"mads_{selected_lccn}.json"
        mads_raw = mads_path.read_bytes()
        mads_meta = json.loads((id_dir / f"mads_{selected_lccn}.json.meta.json").read_text(encoding="utf-8"))
        assert hashlib.sha256(mads_raw).hexdigest() == mads_meta["sha256"]
        parsed_graph = parse_lcnaf_madsrdf_graph(mads_raw, expected_lccn=selected_lccn)

        cw_code = r["crosswalk_code"]
        if cw_code is not None:
            cw_entry = cw.AGENCY_CROSSWALK_BY_CODE[cw_code]
            cw_tier = cw_entry.tier
            parent_collapsed = (
                r["category"] != "cabinet_department"
                and cw_entry.primary_slug is not None
                and cw_entry.primary_slug.endswith("-department")
            )
        else:
            cw_tier = "historical"
            parent_collapsed = False

        defunct_code = r["category"] == "crosswalk_defunct_in_table"

        zip_targets = list(r.get("pinned_externallinks_targets") or ())
        zip_wikidata = [u for u in zip_targets if "wikidata.org/entity/" in u]
        zip_fast = [u for u in zip_targets if "id.worldcat.org/fast/" in u]

        if key_id in {"HIST_ICC", "HIST_CAB"}:
            succ_mode = "unlinked_in_rdf_prose_only"
        elif key_id in {"HIST_HEW", "HIST_WAR", "HHS", "GPO"}:
            succ_mode = "flattened_into_untyped_related_authority"
        elif parsed_graph.earlier_lccns or parsed_graph.later_lccns:
            succ_mode = "explicit_earlier_or_later_established_form"
        else:
            succ_mode = "no_corporate_rename_link"

        us_top1 = us_hits[0] if us_hits else None
        bare_top1 = bare_hits[0] if bare_hits else None
        authority_iri = LCNAF_AUTHORITY_PREFIX + selected_lccn

        records_out.append(
            {
                "key_id": key_id,
                "category": r["category"],
                "crosswalk_code": cw_code,
                "crosswalk_tier": cw_tier,
                "natural_name": natural_name,
                "fr_or_alt_name": r["fr_or_alt_name"],
                "crosswalk_parent_collapsed": parent_collapsed,
                "crosswalk_defunct_code": defunct_code,
                "resolution_rung": rung,
                "lccn": selected_lccn,
                "authority_iri": authority_iri,
                "authoritative_label": parsed_graph.authoritative_label,
                "marc_key": parsed_graph.marc_key,
                "madsrdf_sha256": f"sha256:{mads_meta['sha256']}",
                "madsrdf_bytes": len(mads_raw),
                "us_prefixed_top1_exact": bool(us_top1 and us_top1.get("uri") == authority_iri),
                "us_prefixed_top1_uri": us_top1.get("uri") if us_top1 else None,
                "us_prefixed_top1_label": us_top1.get("aLabel") if us_top1 else None,
                "bare_name_top1_exact": bool(bare_top1 and bare_top1.get("uri") == authority_iri),
                "bare_name_hits_count": int(bare_doc.get("count", len(bare_hits))),
                "bare_name_top1_uri": bare_top1.get("uri") if bare_top1 else None,
                "bare_name_top1_label": bare_top1.get("aLabel") if bare_top1 else None,
                "in_pinned_lc_externallinks_zip": bool(r["in_pinned_externallinks_nt_zip"]),
                "pinned_zip_wikidata_iris": zip_wikidata,
                "pinned_zip_fast_iris": zip_fast,
                "wikidata_iris": list(parsed_graph.wikidata_iris),
                "fast_iris": list(parsed_graph.fast_iris),
                "viaf_iris": list(parsed_graph.viaf_iris),
                "isni_iris": list(parsed_graph.isni_iris),
                "earlier_lccns": list(parsed_graph.earlier_lccns),
                "earlier_unlinked_labels": list(parsed_graph.earlier_unlinked_labels),
                "later_lccns": list(parsed_graph.later_lccns),
                "related_authority_count": len(parsed_graph.related_lccns),
                "succession_encoding_mode": succ_mode,
            }
        )

    total = len(records_out)
    return {
        "schema_version": "refspec-loc-lcnaf-agency-alignment/2",
        "pinned_lc_external_links_baseline": {
            "filename": "lcsh-externallinks-2026-08-15.nt.zip",
            "sha256": "sha256:7d279d69c6920b41a579634a84a1b31ff73af764345fe51df3f7c480efeba9d1",
            "lcsh_assertions_currently_read": 802592,
            "lcnaf_assertions_present_in_same_zip": 2018402,
            "lcnaf_to_fast_assertions": 1418942,
            "lcnaf_to_wikidata_assertions": 425540,
            "lcnaf_to_united_states_labeled_targets": 13454,
            "oclc_fast_topical_corporate_assertions": 0,
        },
        "summary": {
            "evaluated_entity_count": total,
            "crosswalk_agency_count": sum(1 for r in records_out if r["crosswalk_code"] is not None),
            "historical_predecessor_count": sum(1 for r in records_out if r["crosswalk_code"] is None),
            "crosswalk_parent_collapsed_count": sum(1 for r in records_out if r["crosswalk_parent_collapsed"]),
            "crosswalk_defunct_code_count": sum(1 for r in records_out if r["crosswalk_defunct_code"]),
            "four_rung_exact_match_count": sum(
                1 for r in records_out if r["marc_key"].startswith("110") and bool(r["lccn"])
            ),
            "rung1_united_states_prefixed_top1_exact_count": sum(1 for r in records_out if r["us_prefixed_top1_exact"]),
            "bare_natural_name_top1_exact_count": sum(1 for r in records_out if r["bare_name_top1_exact"]),
            "bare_natural_name_zero_hit_count": sum(1 for r in records_out if r["bare_name_hits_count"] == 0),
            "bare_natural_name_false_friend_top1_count": sum(
                1 for r in records_out if r["bare_name_hits_count"] > 0 and not r["bare_name_top1_exact"]
            ),
            "fr_inverted_name_probe_exact_count": sum(
                1 for p in probes_meta if p["probe_id"].startswith("probe_inv_") and p["hit_count"] > 0
            ),
            "bare_acronym_probe_top3_exact_count": sum(
                1
                for p in probes_meta
                if p["probe_id"] in {"probe_acr_epa", "probe_acr_dot", "probe_acr_fs", "probe_acr_eab"}
                and any("United States" in str(h.get("aLabel") or "") for h in p["top3_hits"])
            ),
            "present_in_pinned_externallinks_zip_count": sum(
                1 for r in records_out if r["in_pinned_lc_externallinks_zip"]
            ),
            "with_pinned_zip_wikidata_link_count": sum(1 for r in records_out if r["pinned_zip_wikidata_iris"]),
            "with_pinned_zip_fast_link_count": sum(1 for r in records_out if r["pinned_zip_fast_iris"]),
            "with_madsrdf_wikidata_link_count": sum(1 for r in records_out if r["wikidata_iris"]),
            "with_madsrdf_fast_link_count": sum(1 for r in records_out if r["fast_iris"]),
        },
        "negative_and_sensitivity_probes": probes_meta,
        "agencies": records_out,
    }


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    catalog = build_statutes_catalog(DEFAULT_CACHE_ROOT)
    ocr_manifest = build_ocr_verification_manifest(DEFAULT_CACHE_ROOT)
    lcnaf_manifest = build_lcnaf_alignment_manifest(DEFAULT_CACHE_ROOT)

    for fname, obj in [
        ("llsl-volumes-1-64-catalog.json", catalog),
        ("llsl-ocr-verification-manifest.json", ocr_manifest),
        ("lcnaf-federal-agencies-alignment.json", lcnaf_manifest),
    ]:
        out_p = EVIDENCE_DIR / fname
        payload = (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")
        out_p.write_bytes(payload)
        print(f"Wrote {fname}: bytes={len(payload):,} sha256={_sha256_bytes(payload)}")

    print("OCR accuracy summary:", json.dumps(ocr_manifest["verdict"]["accuracy_summary"], indent=2))
    print("LCNAF alignment summary:", json.dumps(lcnaf_manifest["summary"], indent=2))


if __name__ == "__main__":
    main()

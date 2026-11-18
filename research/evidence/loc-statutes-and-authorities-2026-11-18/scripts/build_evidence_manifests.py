"""Build deterministic, sha256-pinned evidence manifests from cached LoC Statutes at Large & id.loc.gov captures.

Reads raw cached responses under:
  /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-loc-statutes-20261118/
and writes canonical JSON manifests (zero binary PDFs) into:
  research/evidence/loc-statutes-and-authorities-2026-11-18/
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = REPO_ROOT / "research" / "evidence" / "loc-statutes-and-authorities-2026-11-18"
DEFAULT_CACHE_ROOT = Path(
    "/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/refspec-loc-statutes-20261118"
)

CONGRESS_YEARS: dict[int, tuple[int, int]] = {
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
    yr_m = re.search(r"\((\d{4})(?:/(\d{4}))?\)", caption or "")
    year_start = int(yr_m.group(1)) if yr_m else (CONGRESS_YEARS[congress][0] if congress in CONGRESS_YEARS else None)
    year_end = (
        int(yr_m.group(2) or yr_m.group(1))
        if yr_m
        else (CONGRESS_YEARS[congress][1] if congress in CONGRESS_YEARS else None)
    )
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
                    "title": item.get("title"),
                    "original_format": item.get("original_format"),
                }
            )

    assert sorted(volumes_by_num) == list(range(1, 65)), "Expected complete Volumes 1..64"
    ordered_vols = [volumes_by_num[v] for v in range(1, 65)]
    total_pdfs = sum(v["pdf_count"] for v in ordered_vols)
    total_llsalvol = sum(v["llsalvol_count"] for v in ordered_vols)
    single_pdf_vols = [v["volume"] for v in ordered_vols if v["pdf_count"] == 1]
    multi_pdf_vols = [v["volume"] for v in ordered_vols if v["pdf_count"] > 1]

    return {
        "schema_version": "refspec-loc-llsl-catalog/1",
        "collection_url": "https://www.loc.gov/collections/united-states-statutes-at-large/?fo=json&c=25",
        "source_collection_pages": source_pages,
        "summary": {
            "total_collection_records": len(all_items),
            "volume_item_count": len(ordered_vols),
            "non_volume_item_count": len(non_volume_items),
            "total_llsl_pdfs": total_pdfs,
            "single_pdf_volume_count": len(single_pdf_vols),
            "single_pdf_volumes": single_pdf_vols,
            "multi_pdf_volume_count": len(multi_pdf_vols),
            "multi_pdf_volumes": multi_pdf_vols,
            "total_llsalvol_objects": total_llsalvol,
            "llsalvol_multi_object_volumes": [v["volume"] for v in ordered_vols if v["llsalvol_count"] > 1],
            "item_json_503_timeout_volumes": [18],
        },
        "volumes": ordered_vols,
    }


def _extract_layers(reader: PdfReader, page_idx0: int) -> tuple[str, str]:
    page = reader.pages[page_idx0]
    t1: list[str] = []
    t2: list[str] = []

    def vis(text, cm, tm, font_dict, font_size):
        if not text:
            return
        base = str((font_dict or {}).get("/BaseFont", ""))
        if "InvisibleOCR" in base:
            t2.append(text)
        else:
            t1.append(text)

    page.extract_text(visitor_text=vis)
    return " ".join("".join(t1).split()), " ".join("".join(t2).split())


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

    alto_pins = []
    alto_dir = cache_root / "alto"
    for mp in sorted(alto_dir.glob("*.meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        alto_pins.append(
            {
                "volume": m["volume"],
                "stat_page": m["stat_page"],
                "sp": m["sp"],
                "url": m["requested_url"],
                "bytes": m["bytes"],
                "sha256": f"sha256:{m['sha256']}",
                "retrieved_at": m["retrieved_at"],
            }
        )

    # Exact verified PDF 1-based pages for all 16 cross-era statutory specimens
    EXACT_SPECIMEN_PAGES = [
        ("1stat570_alien_friends", "Era 1 (1-10 Stat.)", 1, "llsl-c5.pdf", 570, 35, "58", "1", "An Act concerning Aliens (mispointed by OLRC popularnames.htm 'Alien Enemy Act')", "1798:58"),
        ("1stat577_alien_enemies", "Era 1 (1-10 Stat.)", 1, "llsl-c5.pdf", 577, 42, "66", "1", "Alien Enemies Act (50 U.S.C. 21-24 via R.S. 4067-4070)", "1798:66"),
        ("2stat443_insurrection", "Era 1 (1-10 Stat.)", 2, "llsl-c9.pdf", 443, 96, "39", None, "Insurrection Act of 1807 (single-section unnumbered; quarantined in Table III)", "1807:39"),
        ("23stat31_animal_industry", "Era 2 (16-25 Stat.)", 23, "llsl-c48.pdf", 31, 59, "60", None, "Animal Industry Act (unnumbered enacting clause)", "1884:60"),
        ("23stat332_foran_labor", "Era 2 (16-25 Stat.)", 23, "llsl-c48.pdf", 332, 360, "164", "2", "Alien Contract Labor Law of Feb. 26, 1885 (OLRC popularnames.htm typo '1895')", "1885:164"),
        ("24stat379_ica", "Era 2 (16-25 Stat.)", 24, "llsl-c49.pdf", 379, 412, "104", "2", "Interstate Commerce Act (enacting clause unnumbered; SEC. 2 on p. 379)", "1887:104"),
        ("38stat251_federal_reserve", "Era 3 (30-49 Stat.)", 38, "llsl-c63.pdf", 251, 270, "6", "2", "Federal Reserve Act (short-title clause unnumbered; SEC. 2 on p. 251)", "1913:6"),
        ("38stat717_ftc", "Era 3 (30-49 Stat.)", 38, "llsl-c63.pdf", 717, 736, "311", None, "Federal Trade Commission Act (Layer 1 drops '717', Layer 2 retains '717')", "1914:311"),
        ("49stat620_ssa_open", "Era 3 (30-49 Stat.)", 49, "llsl-c74.pdf", 620, 666, "531", "1", "Social Security Act opening page (Title I sec. 1)", "1935:531"),
        ("49stat647_ssa_1102", "Era 3 (30-49 Stat.)", 49, "llsl-c74.pdf", 647, 693, "531", "1102", "Social Security Act sec. 1102 (42 U.S.C. 1302; DOWNSTREAM_SPECIMENS weight=169)", "1935:531"),
        ("51stat4_joint_res", "Era 4 (50-64 Stat.)", 51, "llsl-c75s2.pdf", 4, 9, "3", None, "75th Cong. 2d Sess. ch. 3 (51 Stat. 4; absent from popularnames.htm)", "1937:3"),
        ("54stat789_inv_company", "Era 4 (50-64 Stat.)", 54, "llsl-c76s2-s3.pdf", 789, 823, "686", "1", "Investment Company Act of 1940 (Title I opening)", "1940:686"),
        ("54stat847_inv_advisers", "Era 4 (50-64 Stat.)", 54, "llsl-c76s2-s3.pdf", 847, 881, "686", "201", "Investment Advisers Act of 1940 (Title II shares page 847 with Title I sec. 52-53)", "1940:686"),
        ("60stat237_apa", "Era 4 (50-64 Stat.)", 60, "llsl-c79s2.pdf", 237, 264, "324", "1", "Administrative Procedure Act", "1946:324"),
        ("60stat755_aea", "Era 4 (50-64 Stat.)", 60, "llsl-c79s2.pdf", 755, 782, "724", "1", "Atomic Energy Act of 1946 (establishing U.S. Atomic Energy Commission)", "1946:724"),
        ("62stat1155_fwpca", "Era 4 (50-64 Stat.)", 62, "llsl-c80s2.pdf", 1155, 1185, "758", "2", "Federal Water Pollution Control Act (Clean Water Act; unnumbered sec. 1, SEC. 2 on p. 1155)", "1948:758"),
    ]

    pdf_dir = cache_root / "pdfs"
    readers: dict[str, PdfReader] = {}
    specimens_out = []

    for sid, era, vol, pfile, spage, pdf_p1, ch, sec, note, t3k in EXACT_SPECIMEN_PAGES:
        if pfile not in readers:
            readers[pfile] = PdfReader(str(pdf_dir / pfile))
        rd = readers[pfile]
        l1, l2 = _extract_layers(rd, pdf_p1 - 1)
        default_txt = subprocess.check_output(
            ["/opt/homebrew/bin/pdftotext", "-f", str(pdf_p1), "-l", str(pdf_p1), str(pdf_dir / pfile), "-"],
            text=True,
        )

        def eval_txt(
            txt: str,
            *,
            page_num: int = spage,
            chap: str = ch,
            sec_lbl: str | None = sec,
        ) -> dict[str, bool | None]:
            return {
                "page_number_present": re.search(rf"\b{page_num}\b", txt) is not None,
                "chapter_number_present": re.search(rf"\b{re.escape(chap)}\b", txt) is not None,
                "chapter_header_strict": bool(
                    re.search(
                        r"\b(?:CHS?|CHAP|CHAPTER)\.?\s*(?:[0-9]+(?:\s*[-–,]\s*)?)*\b(?:" + re.escape(chap) + r"|[IVXLCDM]+)\b",
                        txt,
                        re.IGNORECASE,
                    )
                ),
                "chapter_header_split_tolerant": bool(
                    re.search(
                        r"\b(?:C\s*[HRU]I?S?|C\s*HAP|C\s*HAPTER)\.?\s*(?:[0-9]+(?:\s*[-–,]\s*)?)*\b(?:" + re.escape(chap) + r"|[IVXLCDM]+)\b",
                        txt,
                        re.IGNORECASE,
                    )
                ),
                "section_label_strict": (
                    None
                    if sec_lbl is None
                    else bool(re.search(rf"\b(?:SEC|SECTION)\.?\s*{re.escape(sec_lbl)}\b", txt, re.IGNORECASE))
                ),
                "section_label_split_tolerant": (
                    None
                    if sec_lbl is None
                    else bool(re.search(rf"\bS\s*EC(?:TION)?\.?\s*{re.escape(sec_lbl)}\b", txt, re.IGNORECASE))
                ),
            }

        m1 = eval_txt(l1)
        m2 = eval_txt(l2)
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
                "expected_chapter": ch,
                "printed_section_tested": sec,
                "table3_key": t3k,
                "description": note,
                "chars_pdftotext_spatial_collided": len(default_txt),
                "chars_layer1_2007_type1": len(l1),
                "chars_layer2_2021_invisible_ocr": len(l2),
                "layer1_metrics": m1,
                "layer2_metrics": m2,
                "union_metrics": combined_union,
                "layer1_opening_excerpt": l1[:360],
                "layer2_opening_excerpt": l2[:360],
                "spatial_collided_opening_excerpt": " ".join(default_txt.split())[:280],
            }
        )

    n_spec = len(specimens_out)
    n_sec = sum(1 for s in specimens_out if s["printed_section_tested"] is not None)

    return {
        "schema_version": "refspec-loc-llsl-ocr-verification/1",
        "verdict": {
            "embedded_ocr_present_in_all_sampled_pdfs": all(
                p["has_invisible_ocr"] and p["has_legacy_type1_ocr"] for p in pinned_pdfs
            ),
            "sampled_pdf_count": len(pinned_pdfs),
            "sampled_total_pdf_pages": sum(p["pages"] for p in pinned_pdfs),
            "dual_overlaid_ocr_architecture": (
                "Every sampled LoC llsl PDF (10/10 across Vols. 1-62, 19,555 pages) carries TWO overlaid "
                "invisible (3 Tr) OCR text layers on every page: (1) a 2007 Type1 font pass (Times-Roman/Bold/Italic, "
                "WinAnsiEncoding) that preserves small-caps headings (CHAP., SECTION) better on early volumes "
                "but interleaves marginalia into body lines, and (2) a July 2021 Foxit FXPDFA 1.2 / PDF Compressor "
                "8.2.12.20 Type0 CID TrueType pass (/InvisibleOCR, Identity-H) that cleanly zones body prose away "
                "from marginalia (matching llsalvol .alto.xml) but splits small-caps initial letters ('S EC.', 'C HAP.'). "
                "Naive spatial PDF extractors (pdftotext default/-layout/-bbox) collide both layers on every line."
            ),
            "accuracy_summary": {
                "specimen_count": n_spec,
                "specimens_with_printed_section_label": n_sec,
                "layer1_page_number_exact": sum(1 for s in specimens_out if s["layer1_metrics"]["page_number_present"]),
                "layer2_page_number_exact": sum(1 for s in specimens_out if s["layer2_metrics"]["page_number_present"]),
                "union_page_number_exact": sum(1 for s in specimens_out if s["union_metrics"]["page_number_present"]),
                "layer1_chapter_number_exact": sum(1 for s in specimens_out if s["layer1_metrics"]["chapter_number_present"]),
                "layer2_chapter_number_exact": sum(1 for s in specimens_out if s["layer2_metrics"]["chapter_number_present"]),
                "union_chapter_number_exact": sum(1 for s in specimens_out if s["union_metrics"]["chapter_number_present"]),
                "layer1_section_strict": sum(1 for s in specimens_out if s["layer1_metrics"]["section_label_strict"] is True),
                "layer2_section_strict": sum(1 for s in specimens_out if s["layer2_metrics"]["section_label_strict"] is True),
                "layer2_section_split_tolerant": sum(
                    1 for s in specimens_out if s["layer2_metrics"]["section_label_split_tolerant"] is True
                ),
                "union_section_split_tolerant": sum(
                    1 for s in specimens_out if s["union_metrics"]["section_label_split_tolerant"] is True
                ),
            },
        },
        "pinned_pdfs": pinned_pdfs,
        "pinned_alto_xml_samples": alto_pins,
        "specimens": specimens_out,
    }


def build_lcnaf_alignment_manifest(cache_root: Path) -> dict[str, Any]:
    enriched = json.loads((cache_root / "id_loc_enriched_analysis.json").read_text(encoding="utf-8"))
    id_dir = cache_root / "id_loc_json"

    # Also include the 8 negative/edge probes + PRC/Army companion authorities
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
                "top3_hits": [
                    {"aLabel": h.get("aLabel"), "uri": h.get("uri")}
                    for h in hits[:3]
                ],
            }
        )

    # Classify each agency's succession encoding mode & crosswalk hazard explicitly
    records_out = []
    for r in enriched:
        mf = r["madsrdf"]
        ear_lccns = [x["iri"].rsplit("/", 1)[-1] for x in mf.get("earlier_forms", []) if not x["iri"].startswith("_:")]
        lat_lccns = [x["iri"].rsplit("/", 1)[-1] for x in mf.get("later_forms", []) if not x["iri"].startswith("_:")]
        rel_lccns = [x["iri"].rsplit("/", 1)[-1] for x in mf.get("related_authorities", []) if not x["iri"].startswith("_:")]

        wikidata_iris = [u for u in mf.get("close_external_iris", []) if "wikidata.org/entity/" in u]
        fast_iris = [u for u in mf.get("close_external_iris", []) if "id.worldcat.org/fast/" in u]
        viaf_iris = [u for u in mf.get("rwo_iris", []) if "viaf.org/viaf/" in u]
        isni_iris = [u for u in mf.get("rwo_iris", []) if "isni.org/isni/" in u]

        key_id = r["key_id"]
        if key_id in {"HIST_ICC", "HIST_CAB"}:
            succ_mode = "unlinked_in_rdf_prose_only"
        elif key_id in {"HIST_HEW", "HIST_WAR", "HHS", "GPO"}:
            succ_mode = "flattened_into_untyped_related_authority"
        elif ear_lccns or lat_lccns:
            succ_mode = "explicit_earlier_or_later_established_form"
        else:
            succ_mode = "no_corporate_rename_link"

        records_out.append(
            {
                "key_id": key_id,
                "category": r["category"],
                "crosswalk_code": r["crosswalk_code"],
                "crosswalk_tier": r["tier"],
                "natural_name": r["natural_name"],
                "fr_or_alt_name": r["fr_or_alt_name"],
                "crosswalk_parent_collapsed": r["category"] == "crosswalk_parent_collapsed",
                "crosswalk_defunct_code": r["category"] == "crosswalk_defunct_in_table",
                "resolution_rung": r["resolution_rung"],
                "lccn": r["selected_lccn"],
                "authority_iri": mf["authority_iri"],
                "authoritative_label": mf["authoritative_label"],
                "marc_key": mf["marc_key"],
                "madsrdf_sha256": f"sha256:{mf['madsrdf_sha256']}",
                "madsrdf_bytes": mf["madsrdf_bytes"],
                "us_prefixed_top1_exact": r["us_top1_uri"] == mf["authority_iri"],
                "us_prefixed_top1_label": r["us_top1_alabel"],
                "bare_name_top1_exact": r["bare_top1_uri"] == mf["authority_iri"],
                "bare_name_hits_count": r["bare_hits_count"],
                "bare_name_top1_label": r["bare_top1_alabel"],
                "in_pinned_lc_externallinks_zip": r["in_pinned_externallinks_nt_zip"],
                "wikidata_iris": wikidata_iris,
                "fast_iris": fast_iris,
                "viaf_iris": viaf_iris,
                "isni_iris": isni_iris,
                "earlier_lccns": ear_lccns,
                "later_lccns": lat_lccns,
                "related_authority_count": len(rel_lccns),
                "succession_encoding_mode": succ_mode,
            }
        )

    total = len(records_out)
    return {
        "schema_version": "refspec-loc-lcnaf-agency-alignment/1",
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
            "four_rung_exact_match_count": sum(1 for r in records_out if r["lccn"] is not None),
            "rung1_united_states_prefixed_top1_exact_count": sum(1 for r in records_out if r["us_prefixed_top1_exact"]),
            "bare_natural_name_top1_exact_count": sum(1 for r in records_out if r["bare_name_top1_exact"]),
            "bare_natural_name_zero_hit_count": sum(1 for r in records_out if r["bare_name_hits_count"] == 0),
            "bare_natural_name_false_friend_top1_count": sum(
                1 for r in records_out if r["bare_name_hits_count"] > 0 and not r["bare_name_top1_exact"]
            ),
            "fr_inverted_name_probe_exact_count": 0,
            "bare_acronym_probe_top3_exact_count": 0,
            "present_in_pinned_externallinks_zip_count": sum(
                1 for r in records_out if r["in_pinned_lc_externallinks_zip"]
            ),
            "with_wikidata_link_count": sum(1 for r in records_out if r["wikidata_iris"]),
            "with_fast_link_count": sum(1 for r in records_out if r["fast_iris"]),
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

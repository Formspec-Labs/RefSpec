"""Read-only scan of all 60 pinned Unified Agenda editions for ADDITIONAL_INFO
continuation markers ("LEGAL AUTHORITY CONT" and variants).

No writes to the source tree. Imports refspec only for the pin table and the
mangled-apostrophe roster; does not call parse_unified_agenda_edition (which
does not expose ADDITIONAL_INFO), so this does its own ElementTree parse.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, "/Users/mikewolfd/Work/RefSpec/src")

from refspec.registry.unified_agenda_editions import (  # noqa: E402
    UNIFIED_AGENDA_EDITION_PINS,
    UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS,
)

SOURCE_ROOT = Path("/Users/mikewolfd/Work/RefSpec/output/registry-real-data-sources/unified-agenda-editions")
OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-29")

MANGLED = b"\x19"

# Broad marker pattern: "AUTHORITY" (any prefix like LEGAL) followed within a
# short span by some form of "CONT" -- catches CONT, CONT:, CONT'D, CONTINUED,
# (CONT, CONT., lower/mixed case, with or without "LEGAL".
MARKER_RE = re.compile(r"AUTHORIT\w*\s*[:\-]?\s*\(?\s*CONT[A-Za-z']*\.?\)?:?", re.IGNORECASE)
# Safety net: any mention of "legal authority" at all inside ADDITIONAL_INFO,
# regardless of "CONT", in case the marker is phrased differently.
LA_RE = re.compile(r"LEGAL\s+AUTHORITY", re.IGNORECASE)


def text_of(el) -> str:
    return el.text or ""


def norm_ws(s: str) -> str:
    return " ".join(s.split())


records = []  # every record with a marker hit
la_mentions = []  # every record mentioning "legal authority" in ADDITIONAL_INFO (superset, for the safety net)
variant_counter: dict[str, dict[str, set]] = {}

for pin in UNIFIED_AGENDA_EDITION_PINS:
    path = SOURCE_ROOT / f"REGINFO_RIN_DATA_{pin.file_stem}.xml"
    payload = path.read_bytes()
    assert len(payload) == pin.expected_byte_length, (pin.file_stem, len(payload), pin.expected_byte_length)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert digest == pin.expected_sha256, (pin.file_stem, digest)
    if pin.publication_id in UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS:
        payload = payload.replace(MANGLED, "’".encode())
    root = ET.fromstring(payload)
    assert root.tag == "REGINFO_RIN_DATA"

    for element in root.findall(".//RIN_INFO"):
        rin = text_of(element.find("RIN")).strip()
        pub_id = text_of(element.find("PUBLICATION/PUBLICATION_ID")).strip()
        assert pub_id == pin.publication_id, (pin.file_stem, pub_id)
        ai_el = element.find("ADDITIONAL_INFO")
        ai_raw = text_of(ai_el) if ai_el is not None else None
        if ai_raw is None or not ai_raw.strip():
            continue
        la_list_el = element.find("LEGAL_AUTHORITY_LIST")
        la_boxes = [text_of(child) for child in ([] if la_list_el is None else la_list_el)]
        cfr_list_el = element.find("CFR_LIST")
        cfr_boxes = [text_of(child) for child in ([] if cfr_list_el is None else cfr_list_el)]

        if LA_RE.search(ai_raw):
            la_mentions.append(
                {"rin": rin, "publication_id": pub_id, "additional_info": ai_raw}
            )

        hits = list(MARKER_RE.finditer(ai_raw))
        if not hits:
            continue
        for hit in hits:
            variant_raw = hit.group(0)
            variant_key = norm_ws(variant_raw).upper()
            bucket = variant_counter.setdefault(variant_key, {"records": set(), "editions": set(), "rins": set(), "example": variant_raw})
            bucket["records"].add((rin, pub_id))
            bucket["editions"].add(pub_id)
            bucket["rins"].add(rin)
        records.append(
            {
                "rin": rin,
                "publication_id": pub_id,
                "additional_info": ai_raw,
                "legal_authority_boxes": la_boxes,
                "cfr_boxes": cfr_boxes,
                "marker_hits": [
                    {"start": h.start(), "end": h.end(), "text": h.group(0)} for h in hits
                ],
            }
        )

print(f"Editions scanned: {len(UNIFIED_AGENDA_EDITION_PINS)}")
print(f"Records with ADDITIONAL_INFO mentioning 'legal authority' (safety net): {len(la_mentions)}")
print(f"Records with a CONT-marker hit: {len(records)}")
print(f"Total marker hits (a record could have >1): {sum(len(r['marker_hits']) for r in records)}")
print(f"Distinct RINs with a marker hit: {len({r['rin'] for r in records})}")
print(f"Distinct editions with a marker hit: {len({r['publication_id'] for r in records})}")
print()
print("Variant table:")
for variant_key, bucket in sorted(variant_counter.items(), key=lambda kv: -len(kv[1]["records"])):
    print(
        f"  {variant_key!r:40s} example={bucket['example']!r:40s} "
        f"records={len(bucket['records']):3d} editions={len(bucket['editions']):3d} rins={len(bucket['rins']):3d}"
    )

# Records that mention "legal authority" but got NO marker hit -- the safety net's catch.
marker_keys = {(r["rin"], r["publication_id"]) for r in records}
extra = [m for m in la_mentions if (m["rin"], m["publication_id"]) not in marker_keys]
print()
print(f"Records mentioning 'legal authority' with NO CONT-marker hit: {len(extra)}")
for m in extra[:30]:
    print(f"  RIN {m['rin']} ed {m['publication_id']}: {m['additional_info']!r}")

OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "raw_marker_records.json").write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
(OUT_DIR / "raw_la_mentions.json").write_text(json.dumps(la_mentions, indent=2, sort_keys=True), encoding="utf-8")
print()
print(f"Wrote {len(records)} records to {OUT_DIR / 'raw_marker_records.json'}")

"""Broader read-only pass: every ADDITIONAL_INFO that mentions "authorit" at
all (any spelling: Authority, Authorities, Authorized...), regardless of
whether "CONT" appears, so we can manually classify what the narrow marker
regex might have missed (reversed order: "Continue... Legal Authority",
different labels: "Additional Legal Authority", no label at all, etc.)
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

AUTHORIT_RE = re.compile(r"AUTHORIT", re.IGNORECASE)


def text_of(el) -> str:
    return el.text or ""


records = []

for pin in UNIFIED_AGENDA_EDITION_PINS:
    path = SOURCE_ROOT / f"REGINFO_RIN_DATA_{pin.file_stem}.xml"
    payload = path.read_bytes()
    assert len(payload) == pin.expected_byte_length
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert digest == pin.expected_sha256
    if pin.publication_id in UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS:
        payload = payload.replace(MANGLED, "’".encode())
    root = ET.fromstring(payload)

    for element in root.findall(".//RIN_INFO"):
        rin = text_of(element.find("RIN")).strip()
        pub_id = text_of(element.find("PUBLICATION/PUBLICATION_ID")).strip()
        ai_el = element.find("ADDITIONAL_INFO")
        ai_raw = text_of(ai_el) if ai_el is not None else None
        if ai_raw is None or not AUTHORIT_RE.search(ai_raw):
            continue
        records.append({"rin": rin, "publication_id": pub_id, "additional_info": ai_raw})

print(f"Records with ADDITIONAL_INFO containing 'authorit' (any form): {len(records)}")
print(f"Distinct RINs: {len({r['rin'] for r in records})}")
print()
for r in records:
    print(f"RIN {r['rin']} ed {r['publication_id']}: {r['additional_info']!r}")
    print()

OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "raw_authorit_broad.json").write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")

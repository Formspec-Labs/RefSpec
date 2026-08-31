"""Diagnostic: records whose ADDITIONAL_INFO contains BOTH 'authorit' and
'cont' anywhere (not necessarily adjacent) -- a looser search someone might
have run to arrive at the prior 52/39/16 belief -- to see how it compares.
Also computes the "Additional Legal Authority(ies)" / "Continue from #N
Legal Authority" sibling-label population precisely.
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
MANGLED = b"\x19"

AUTHORIT_RE = re.compile(r"AUTHORIT", re.IGNORECASE)
CONT_RE = re.compile(r"CONT", re.IGNORECASE)
SIBLING_RE = re.compile(r"ADDITIONAL\s+LEGAL\s+AUTHORIT|CONTINUE\s+FROM\s+#?\d+\s+LEGAL\s+AUTHORIT", re.IGNORECASE)


def text_of(el) -> str:
    return el.text or ""


loose_records = []
sibling_records = []

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
        if ai_raw is None:
            continue
        if AUTHORIT_RE.search(ai_raw) and CONT_RE.search(ai_raw):
            loose_records.append({"rin": rin, "publication_id": pub_id, "additional_info": ai_raw})
        if SIBLING_RE.search(ai_raw):
            sibling_records.append({"rin": rin, "publication_id": pub_id, "additional_info": ai_raw})

print("=== Loose 'authorit' AND 'cont' anywhere in the same field ===")
print(f"Records: {len(loose_records)}")
print(f"Distinct RINs: {len({r['rin'] for r in loose_records})}")
print(f"Distinct editions: {len({r['publication_id'] for r in loose_records})}")
print()
print("By RIN:")
from collections import defaultdict
by_rin = defaultdict(list)
for r in loose_records:
    by_rin[r["rin"]].append(r["publication_id"])
for rin, eds in sorted(by_rin.items()):
    print(f"  {rin}: {sorted(eds)}")

print()
print("=== Sibling label: 'Additional Legal Authority(ies)' / 'Continue from #N Legal Authority' ===")
print(f"Records: {len(sibling_records)}")
print(f"Distinct RINs: {len({r['rin'] for r in sibling_records})}")
print(f"Distinct editions: {len({r['publication_id'] for r in sibling_records})}")
by_rin2 = defaultdict(list)
for r in sibling_records:
    by_rin2[r["rin"]].append(r["publication_id"])
for rin, eds in sorted(by_rin2.items()):
    print(f"  {rin}: {sorted(eds)}")

"""Read every pinned edition through the module's own reader and dump the
LEGAL_AUTHORITY boxes as they reach the builder. Read-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/RefSpec")
sys.path.insert(0, str(REPO / "src"))

from refspec.registry.unified_agenda_editions import (  # noqa: E402
    UNIFIED_AGENDA_EDITION_PINS,
    parse_unified_agenda_edition,
)

SOURCE = REPO / "output/registry-real-data-sources/unified-agenda-editions"
OUT = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/boxes.jsonl")

with OUT.open("w", encoding="utf-8") as handle:
    for pin in UNIFIED_AGENDA_EDITION_PINS:
        payload = (SOURCE / f"REGINFO_RIN_DATA_{pin.file_stem}.xml").read_bytes()
        records = parse_unified_agenda_edition(payload, pin=pin)
        for record in records:
            if not record.legal_authorities:
                continue
            handle.write(
                json.dumps(
                    {
                        "rin": record.rin,
                        "pub": record.publication_id,
                        "boxes": list(record.legal_authorities),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        print(pin.publication_id, len(records), file=sys.stderr)
print("done", file=sys.stderr)

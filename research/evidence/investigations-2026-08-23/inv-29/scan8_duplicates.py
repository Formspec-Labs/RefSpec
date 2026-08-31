"""Read-only duplicate check: parse each record's EXISTING legal-authority
boxes with the same grammar (mirroring the builder's per-box call), and
compare the resulting (type, title, section/public_law/...) identities
against what the continuation parses to -- to find candidate duplicate rows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/mikewolfd/Work/RefSpec/src")

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402

OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-29")
rows = json.loads((OUT_DIR / "final_rows.json").read_text(encoding="utf-8"))


def identity(citation) -> tuple:
    """A rough content key: the fields that would make two rows 'the same authority'."""
    return (
        citation.authority_type,
        citation.usc_title,
        citation.usc_section,
        citation.public_law,
        citation.statute_volume,
        citation.statute_page,
        citation.executive_order,
        citation.cfr_title,
        citation.cfr_part,
        citation.admin_order_kind,
        citation.admin_order_number,
        citation.fr_volume,
        citation.fr_page,
    )


seen_rins = set()
for r in rows:
    key = (r["rin"], r["publication_id"])
    box_identities = set()
    for box_text in r["legal_authority_boxes"]:
        for c in parse_authority_citation(box_text):
            box_identities.add(identity(c))
    cont_identities = []
    for c in parse_authority_citation(r["continuation"]):
        cont_identities.append((identity(c), c))
    overlap = [(ident, c) for ident, c in cont_identities if ident in box_identities]
    if overlap:
        print(f"RIN {r['rin']} ed {r['publication_id']}: {len(overlap)} of {len(cont_identities)} continuation rows DUPLICATE an existing box row")
        for ident, c in overlap:
            print(f"    duplicate: {c.authority_type} usc_title={c.usc_title} usc_section={c.usc_section} public_law={c.public_law}")

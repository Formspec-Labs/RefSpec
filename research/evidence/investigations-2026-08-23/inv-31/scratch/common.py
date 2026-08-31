from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/RefSpec")
sys.path.insert(0, str(REPO / "src"))

BASE = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/old-rebuild6-d19df1bd/out/unified_agenda_legal_authorities.parquet")
BOXES = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/boxes.jsonl")

#: Columns worth showing for a specimen: everything a citation can land in.
VALUE_COLUMNS = (
    "authority_type", "parse_status", "unstated_kind",
    "usc_title", "usc_section", "usc_section_end", "usc_section_span_rule",
    "usc_chapter", "usc_chapter_end", "usc_appendix",
    "cfr_title", "cfr_part", "cfr_section",
    "reorganization_plan", "act_key", "act_section",
    "act_resolution_evidence", "act_resolution_reason", "act_resolution_sibling_ordinal",
    "usc_section_verdict", "usc_section_verdict_reason", "usc_section_attested_at_edition",
    "usc_section_corrected", "usc_section_correction_evidence",
    "public_law", "public_law_corrected", "pl_correction_evidence",
    "executive_order", "statute_volume", "statute_page",
    "stated_act_name", "stated_section",
    "fr_volume", "fr_page", "corroboration_rule",
)


def load_boxes() -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    with BOXES.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            out[(row["rin"], row["pub"])] = row["boxes"]
    return out


def load_base(columns=None):
    import pyarrow.parquet as pq

    cols = None if columns is None else list(dict.fromkeys(
        ["rin", "publication_id", "ordinal", "citation_ordinal", "authority_text", *columns]
    ))
    return pq.read_table(BASE, columns=cols)


def base_rows_by_box(table) -> dict[tuple[str, str, int], list[dict]]:
    cols = {name: table.column(name).to_pylist() for name in table.schema.names}
    out: dict[tuple[str, str, int], list[dict]] = {}
    n = table.num_rows
    for i in range(n):
        key = (cols["rin"][i], cols["publication_id"][i], cols["ordinal"][i])
        out.setdefault(key, []).append({name: cols[name][i] for name in cols})
    return out


def nonnull(row: dict) -> dict:
    return {k: v for k, v in row.items()
            if v is not None and k not in {"rin", "publication_id", "ordinal", "authority_text"}
            and not (k in {"usc_appendix", "usc_note"} and v is False)}

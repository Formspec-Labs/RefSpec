"""Population A: act-name carry across sibling boxes (not just ordinal +-1)."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

sys.path.insert(0, "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-acts")
from common import (  # noqa: E402
    EVID,
    AbstractCache,
    abbrev_survivors,
    abstract_glosses,
    act_initialism,
    build_roster,
    candidate_initialisms,
    group_boxes,
    is_bare_section_list,
    load_act_index,
    load_rows,
    resolve_one,
)
from refspec.registry.citation_grammar import _normalize_dashes  # noqa: E402

rows = load_rows()
keys_by_rin, keys_by_agency = build_roster(rows)
records = group_boxes(rows)
index, credits = load_act_index()
abscache = AbstractCache()

_SECTION_IDENTITY = re.compile(r"\d{1,6}[a-zA-Z]{0,3}(?:-\d{1,6}[a-zA-Z]{0,2})?")


def extract_section_identities(text: str) -> list[str]:
    return [m.group(0).lower() for m in _SECTION_IDENTITY.finditer(_normalize_dashes(text or ""))]


def box_all_other_failed(box) -> bool:
    return all(r["authority_type"] == "other" and r["parse_status"] == "failed" for r in box["rows"])


def act_signal(box, rin: str, publication_id: str):
    """Return (signal_name, carry_key_or_None, detail) or None."""

    any_act_key = next((r["act_key"] for r in box["rows"] if r["act_key"]), None)
    if any_act_key:
        return ("act_key", any_act_key, any_act_key)
    any_stated = next((r["stated_act_name"] for r in box["rows"] if r["stated_act_name"]), None)
    if any_stated:
        return ("stated_act_name", any_stated, any_stated)
    toks = candidate_initialisms(box["text"])
    if toks:
        rin_pool = keys_by_rin.get(rin, set())
        agency_pool = keys_by_agency.get(rin[:4], set())
        for tok in toks:
            survivors = abbrev_survivors(tok, rin_pool) or abbrev_survivors(tok, agency_pool)
            if len(survivors) == 1:
                return ("roster_initialism", survivors[0], f"{tok}->{survivors[0]}")
            if len(survivors) > 1:
                return ("roster_initialism_ambiguous", None, f"{tok}->{sorted(survivors)}")
        abstract_text = abscache.get(rin, publication_id)
        glosses = abstract_glosses(abstract_text)
        for tok in toks:
            if tok in glosses:
                return ("abstract_initialism", glosses[tok], f"{tok}->{glosses[tok]!r}")
    return None


candidates = []  # one entry per attributed later box
anchor_signal_tally = Counter()

for (rin, publication_id), boxes in records.items():
    boxes_sorted = sorted(boxes, key=lambda b: b["ordinal"])
    active = None  # dict or None
    for box in boxes_sorted:
        sig = act_signal(box, rin, publication_id)
        if sig is not None:
            signal_name, carry_key, detail = sig
            anchor_signal_tally[signal_name] += 1
            if carry_key is not None:
                active = {
                    "ordinal": box["ordinal"], "text": box["text"],
                    "signal": signal_name, "carry_key": carry_key, "detail": detail,
                }
            # ambiguous roster hits do not overwrite a usable active act
            continue
        if active is not None and box_all_other_failed(box) and is_bare_section_list(box["text"]):
            candidates.append(
                {
                    "rin": rin, "publication_id": publication_id,
                    "ordinal": box["ordinal"], "text": box["text"],
                    "anchor_ordinal": active["ordinal"], "anchor_text": active["text"],
                    "anchor_signal": active["signal"], "carry_key": active["carry_key"],
                    "row_count": len(box["rows"]),
                }
            )

print("anchor signal tally (boxes that NAME an act, by how):", dict(anchor_signal_tally))
print("candidate later-boxes total:", len(candidates))
distinct_records = {(c["rin"], c["publication_id"]) for c in candidates}
distinct_rins = {c["rin"] for c in candidates}
total_rows = sum(c["row_count"] for c in candidates)
print("distinct records:", len(distinct_records))
print("distinct RINs:", len(distinct_rins))
print("total underlying parquet rows:", total_rows)

# ---- resolution attempt for every candidate box ----
reason_tally = Counter()
resolved_count = 0
partial_count = 0
per_candidate_outcomes = []
for c in candidates:
    identities = extract_section_identities(c["text"])
    outcomes = [resolve_one(c["carry_key"], sec, index, credits) for sec in identities]
    resolved_flags = [o[0] is not None for o in outcomes]
    entry = {**c, "identities": identities, "outcomes": outcomes}
    per_candidate_outcomes.append(entry)
    if identities and all(resolved_flags):
        resolved_count += 1
        reason_tally["RESOLVED"] += 1
    elif any(resolved_flags):
        partial_count += 1
        reason_tally["PARTIALLY_RESOLVED_LIST"] += 1
    else:
        # tally by the first identity's reason (or "no_identity_extracted")
        reason = outcomes[0][3] if outcomes else "no_identity_extracted"
        reason_tally[reason or "none"] += 1

print("\nresolution outcome tally (per candidate BOX):", dict(reason_tally))
print("resolved boxes:", resolved_count, " partially-resolved-list boxes:", partial_count)

with (EVID / "pop_a_candidates.json").open("w") as fh:
    json.dump(
        {
            "anchor_signal_tally": dict(anchor_signal_tally),
            "candidate_box_count": len(candidates),
            "distinct_records": len(distinct_records),
            "distinct_rins": len(distinct_rins),
            "total_rows": total_rows,
            "reason_tally": dict(reason_tally),
            "candidates": per_candidate_outcomes,
        },
        fh,
        indent=2,
        default=str,
    )
print("\nwrote", EVID / "pop_a_candidates.json")

# specimen self-check
spec = [c for c in candidates if c["rin"] == "0936-AA07" and c["publication_id"] == "201710"]
print("\nspecimen check (expect 4 candidate boxes, ordinals 1-4):")
for c in spec:
    print(" ", c["ordinal"], repr(c["text"]), "carry_key=", c["carry_key"], "signal=", c["anchor_signal"])

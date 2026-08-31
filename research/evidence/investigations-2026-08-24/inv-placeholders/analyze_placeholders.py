import sys, os, json, random
from collections import defaultdict, Counter

ROOT = "/Users/mikewolfd/Work/RefSpec"
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import duckdb
from refspec.registry.cfr_authority_notes import (
    CfrAuthorityNotes, usc_citation, public_law_citation, cfr_citation, act_citation,
    normalize_part, FAMILIES, VERDICTS,
)

LA_PATH = f"{ROOT}/output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"
CF_PATH = f"{ROOT}/output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet"
OUT_DIR = "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-placeholders"

con = duckdb.connect(":memory:")

la_cols = [
    "rin", "publication_id", "ordinal", "citation_ordinal", "authority_text",
    "authority_type", "unstated_kind", "usc_title", "usc_section", "public_law",
    "cfr_title", "cfr_part", "act_key", "stated_act_name", "authority_source",
]
la_df = con.execute(f"SELECT {','.join(la_cols)} FROM read_parquet('{LA_PATH}')").df()

cf_cols = ["rin", "publication_id", "cfr_title", "cfr_part"]
cf_df = con.execute(f"SELECT {','.join(cf_cols)} FROM read_parquet('{CF_PATH}')").df()

print(f"legal_authorities rows: {len(la_df)}", file=sys.stderr)
print(f"cfr_references rows: {len(cf_df)}", file=sys.stderr)

notes = CfrAuthorityNotes.from_repository(ROOT)
print(f"notes loaded: {len(notes.records)} parts, sha256={notes.sha256}", file=sys.stderr)

_CITATION_BY_TYPE = {
    "usc": lambda t, s, pl, ct, cp, ak, san: usc_citation(t, s),
    "public_law": lambda t, s, pl, ct, cp, ak, san: public_law_citation(pl),
    "cfr": lambda t, s, pl, ct, cp, ak, san: cfr_citation(ct, cp),
    "act_relative": lambda t, s, pl, ct, cp, ak, san: act_citation(ak or san),
}


def own_citation(row):
    fn = _CITATION_BY_TYPE.get(row.authority_type)
    if fn is None:
        return None
    return fn(row.usc_title, row.usc_section, row.public_law, row.cfr_title, row.cfr_part, row.act_key, row.stated_act_name)


# ---------------------------------------------------------------------------
# Pass 1: per-record (rin, publication_id) aggregates over legal_authorities
# ---------------------------------------------------------------------------
records = {}  # (rin, pub) -> dict

for row in la_df.itertuples(index=False):
    key = (row.rin, row.publication_id)
    rec = records.get(key)
    if rec is None:
        rec = {
            "stated_citations": set(),   # {(family, identity)}
            "any_stated_rows": 0,         # count of rows with authority_type != 'unstated'
            "placeholder_kinds": {},      # kind -> count (rows)
        }
        records[key] = rec
    if row.authority_type == "unstated":
        rec["placeholder_kinds"][row.unstated_kind] = rec["placeholder_kinds"].get(row.unstated_kind, 0) + 1
    else:
        rec["any_stated_rows"] += 1
        cit = own_citation(row)
        if cit is not None:
            rec["stated_citations"].add((cit.family, cit.identity))

print(f"distinct (rin,publication_id) records in legal_authorities: {len(records)}", file=sys.stderr)

# ---------------------------------------------------------------------------
# held_by_rule: (rin, pub) -> set of (title, part) held by the notes cache,
# taken from the rule's OWN cfr_references (the parts the rule amends).
# ---------------------------------------------------------------------------
held_by_rule = defaultdict(set)
for row in cf_df.itertuples(index=False):
    part = normalize_part(row.cfr_part)
    if row.cfr_title is None or part is None:
        continue
    if not notes.holds(row.cfr_title, part):
        continue
    held_by_rule[(row.rin, row.publication_id)].add((int(row.cfr_title), part))

print(f"records with >=1 held CFR part: {len(held_by_rule)}", file=sys.stderr)

# ---------------------------------------------------------------------------
# editions_by_rin: rin -> {pub: rec}  (reuse `records`, grouped)
# ---------------------------------------------------------------------------
editions_by_rin = defaultdict(dict)
for (rin, pub), rec in records.items():
    editions_by_rin[rin][pub] = rec

KINDS = ("more-citations-follow", "not-yet-determined", "none-off-form")

# placeholder record keys, per kind (row-per-record 1:1, confirmed earlier)
placeholder_keys = {kind: [] for kind in KINDS}
for key, rec in records.items():
    for kind in rec["placeholder_kinds"]:
        placeholder_keys[kind].append(key)

for kind in KINDS:
    placeholder_keys[kind].sort()
    print(f"{kind}: {len(placeholder_keys[kind])} records", file=sys.stderr)

# ---------------------------------------------------------------------------
# Part 1: records + stated/none split
# ---------------------------------------------------------------------------
part1 = {}
for kind in KINDS:
    keys = placeholder_keys[kind]
    with_any_stated = sum(1 for k in keys if records[k]["any_stated_rows"] > 0)
    with_family_stated = sum(1 for k in keys if len(records[k]["stated_citations"]) > 0)
    part1[kind] = {
        "records": len(keys),
        "with_any_stated_row": with_any_stated,
        "with_no_stated_row": len(keys) - with_any_stated,
        "with_4family_stated_identity": with_family_stated,
    }

# ---------------------------------------------------------------------------
# Part 2: Witness A
# ---------------------------------------------------------------------------
witnessA = {}       # kind -> per-record candidate set  {key: frozenset((family,identity,cfr_note_part))}
witnessA_summary = {}

for kind in KINDS:
    keys = placeholder_keys[kind]
    per_record = {}
    with_note = 0
    size_hist = Counter()
    gained = 0
    total_pairs = 0
    for key in keys:
        held = held_by_rule.get(key, set())
        if held:
            with_note += 1
        note_cites = set()
        note_cite_source = {}  # (family,identity) -> set of cited_as parts
        for part in held:
            note = notes.note(*part)
            if note is None:
                continue
            for c in note.citations:
                fam_id = (c.family, c.identity)
                note_cites.add(fam_id)
                note_cite_source.setdefault(fam_id, set()).add(f"{part[0]} CFR {part[1]}")
        stated = records[key]["stated_citations"]
        cand = note_cites - stated
        per_record[key] = {"candidates": cand, "sources": note_cite_source, "held_parts": held}
        size_hist[len(cand)] += 1
        if cand:
            gained += 1
        total_pairs += len(cand)
    witnessA[kind] = per_record
    witnessA_summary[kind] = {
        "records_with_ge1_note": with_note,
        "records_with_0_notes": len(keys) - with_note,
        "size_histogram": dict(sorted(size_hist.items())),
        "records_gaining_ge1_candidate": gained,
        "total_candidate_pairs": total_pairs,
    }

# ---------------------------------------------------------------------------
# Part 3: Witness B
# ---------------------------------------------------------------------------
witnessB = {}
witnessB_summary = {}

for kind in KINDS:
    keys = placeholder_keys[kind]
    per_record = {}
    gained = 0
    total_pairs = 0
    with_donor = 0
    donor_count_hist = Counter()
    for key in keys:
        rin, pub_ph = key
        stated_ph = records[key]["stated_citations"]
        count_ph = len(stated_ph)
        donors = []
        cand = set()
        for pub_d, rec_d in editions_by_rin[rin].items():
            if pub_d == pub_ph:
                continue
            if rec_d["placeholder_kinds"]:  # has ANY placeholder -> disqualified as donor
                continue
            if len(rec_d["stated_citations"]) <= count_ph:
                continue
            diff = rec_d["stated_citations"] - stated_ph
            if diff:
                donors.append(pub_d)
                cand |= diff
        per_record[key] = {"candidates": cand, "donors": donors}
        if donors:
            with_donor += 1
            donor_count_hist[len(donors)] += 1
        if cand:
            gained += 1
        total_pairs += len(cand)
    witnessB[kind] = per_record
    witnessB_summary[kind] = {
        "records_with_ge1_donor_edition": with_donor,
        "records_gaining_ge1_candidate": gained,
        "total_candidate_pairs": total_pairs,
        "donor_count_histogram": dict(sorted(donor_count_hist.items())),
    }

# ---------------------------------------------------------------------------
# Agreement between A and B
# ---------------------------------------------------------------------------
agreement = {}
for kind in KINDS:
    keys = placeholder_keys[kind]
    both_present = 0
    intersect_nonempty = 0
    a_only = 0
    b_only = 0
    neither = 0
    union_pairs = 0
    intersect_pairs = 0
    for key in keys:
        a = witnessA[kind][key]["candidates"]
        b = witnessB[kind][key]["candidates"]
        if a and b:
            both_present += 1
            inter = a & b
            if inter:
                intersect_nonempty += 1
            intersect_pairs += len(inter)
            union_pairs += len(a | b)
        elif a and not b:
            a_only += 1
        elif b and not a:
            b_only += 1
        else:
            neither += 1
    agreement[kind] = {
        "both_nonempty": both_present,
        "both_nonempty_and_intersect": intersect_nonempty,
        "a_only": a_only,
        "b_only": b_only,
        "neither": neither,
        "intersect_pairs": intersect_pairs,
        "union_pairs": union_pairs,
    }

# ---------------------------------------------------------------------------
# Save summary numbers
# ---------------------------------------------------------------------------
summary = {
    "part1": part1,
    "witnessA_summary": witnessA_summary,
    "witnessB_summary": witnessB_summary,
    "agreement": agreement,
}
os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "summary.json"), "w") as f:
    json.dump(summary, f, indent=2, default=str)

print(json.dumps(summary, indent=2, default=str))

# ---------------------------------------------------------------------------
# Save full per-record candidate lists (as JSON, for the record) per kind
# ---------------------------------------------------------------------------
for kind in KINDS:
    rows_out = []
    for key in placeholder_keys[kind]:
        rin, pub = key
        a = witnessA[kind][key]
        b = witnessB[kind][key]
        rows_out.append({
            "rin": rin,
            "publication_id": pub,
            "held_parts": sorted(f"{t} CFR {p}" for t, p in a["held_parts"]),
            "candidates_A": sorted(f"{fam}:{ident}" for fam, ident in a["candidates"]),
            "candidates_A_sources": {f"{fam}:{ident}": sorted(a["sources"].get((fam, ident), [])) for fam, ident in a["candidates"]},
            "candidates_B": sorted(f"{fam}:{ident}" for fam, ident in b["candidates"]),
            "donors_B": b["donors"],
        })
    with open(os.path.join(OUT_DIR, f"candidates_{kind}.json"), "w") as f:
        json.dump(rows_out, f, indent=2)

print("wrote candidate JSON files", file=sys.stderr)

# ---------------------------------------------------------------------------
# Seeded specimens
# ---------------------------------------------------------------------------
specimens = {}
for kind in KINDS:
    keys_sorted = sorted(placeholder_keys[kind])
    rng = random.Random(20260823)
    sample = rng.sample(keys_sorted, 10)
    sample_rows = []
    for key in sample:
        rin, pub = key
        # this record's own boxes (all rows, ordered)
        own_rows = la_df[(la_df.rin == rin) & (la_df.publication_id == pub)].sort_values(["ordinal", "citation_ordinal"])
        placeholder_text = None
        stated_boxes = []
        for r in own_rows.itertuples(index=False):
            if r.authority_type == "unstated" and r.unstated_kind == kind:
                placeholder_text = r.authority_text
            elif r.authority_type != "unstated":
                stated_boxes.append({"ordinal": r.ordinal, "citation_ordinal": r.citation_ordinal, "text": r.authority_text, "type": r.authority_type, "source": r.authority_source})
        held = witnessA[kind][key]["held_parts"]
        note_texts = {f"{t} CFR {p}": notes.note(t, p).authority_note for t, p in held if notes.note(t, p)}
        donors = witnessB[kind][key]["donors"]
        donor_lists = {}
        for d in donors:
            d_rows = la_df[(la_df.rin == rin) & (la_df.publication_id == d)].sort_values(["ordinal", "citation_ordinal"])
            donor_lists[d] = [
                {"text": r.authority_text, "type": r.authority_type}
                for r in d_rows.itertuples(index=False)
            ]
        sample_rows.append({
            "rin": rin,
            "publication_id": pub,
            "placeholder_text": placeholder_text,
            "stated_boxes_in_record": stated_boxes,
            "held_cfr_parts": sorted(f"{t} CFR {p}" for t, p in held),
            "note_texts": note_texts,
            "candidates_A": sorted(f"{fam}:{ident}" for fam, ident in witnessA[kind][key]["candidates"]),
            "donor_editions_B": donors,
            "donor_lists_B": donor_lists,
            "candidates_B": sorted(f"{fam}:{ident}" for fam, ident in witnessB[kind][key]["candidates"]),
        })
    specimens[kind] = sample_rows

with open(os.path.join(OUT_DIR, "specimens.json"), "w") as f:
    json.dump(specimens, f, indent=2, default=str)

print("wrote specimens.json", file=sys.stderr)
print("DONE", file=sys.stderr)

"""Measure which federal witness organization strings the pinned Federal Register roster misses.

Demand evidence for the agency alias batch (plans/agency-registry-alias-batch-adjudication.md), not
an input any release reads. Run in RefSpec's environment:

    uv run --frozen python research/evidence/agency-alias-demand-2026-11-08/measure.py <appearances.parquet>

``appearances.parquet`` is congressional-tech's witness appearances table of 2026-11-08
(``.cache/archive-release/investigations/entity-matching-measure-20261108/`` in that repository;
its sha256 is recorded in the output). Whether an appearance is matched is congressional-tech's own
rule, copied verbatim from its ``em-fedagency.py`` (``ct_key``/``ct_match``), with one change: the
index is the pinned 2026-08-15 roster (472 agencies) instead of the live API (473). Each unmatched
string is then split the same way, and each segment is keyed with the alias batch's ``name_key``
(the batch tool owns that function; it is copied here so this script needs no import).

Only federal-typed appearances (``witness_type = 'Government - Federal'``, house_xml rows, the
only source that types witnesses) decide the demand set; ``all_appearances`` counts every
unmatched appearance whose string carries the same segment key, of any witness type.
"""

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ROSTER = ROOT / "tests/fixtures/federal_register_native_controls/fr-agencies-2026-08-15.json"
OUTPUT = HERE / "federal-misses.json"
SPLIT = r"[,;:]| accompanied by "
# The demand set: segment keys seen in at least three federal-typed unmatched appearances, or in
# at least 25 unmatched appearances of any type (General Accounting Office: 2 federal, 214 in all).
MIN_FEDERAL, MIN_ALL = 3, 25


def ct_key(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(the|u s|us|united states|of america)\b", " ", s)
    return " ".join(s.split())


def name_key(text):
    s = unicodedata.normalize("NFKC", text or "").casefold().replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())
    s = re.sub(r"\b(the|u s|us|united states|of america)\b", " ", s)
    return " ".join(s.split())


def sha256(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main(appearances: Path) -> None:
    agencies = json.loads(ROSTER.read_text())
    idx = {}
    for a in agencies:
        for nm in [a["name"], a.get("short_name")]:
            if nm and ct_key(nm):
                idx.setdefault(ct_key(nm), a["slug"])
    for a in agencies:
        m = re.match(r"^(.*) department$", ct_key(a["name"]))
        if m:
            idx.setdefault("department of " + m.group(1), a["slug"])
        m = re.match(r"^department of (.*)$", ct_key(a["name"]))
        if m:
            idx.setdefault(m.group(1) + " department", a["slug"])

    def ct_match(raw):
        hits = [idx[s] for s in (ct_key(x) for x in re.split(SPLIT, raw or "")) if s in idx]
        return hits[0] if hits else None

    con = duckdb.connect()
    query = "select coalesce(organization, on_behalf_of) org, count(*) from read_parquet(?) {} group by 1"
    federal = con.execute(query.format("where witness_type = 'Government - Federal'"), [str(appearances)]).fetchall()
    every = con.execute(query.format(""), [str(appearances)]).fetchall()
    segment_federal, segment_all = Counter(), Counter()
    spellings = defaultdict(Counter)
    for org, count in federal:
        if org is None or ct_match(org):
            continue
        for raw in re.split(SPLIT, org):
            if key := name_key(raw):
                segment_federal[key] += count
                spellings[key][raw.strip()] += count
    for org, count in every:
        if org is None or ct_match(org):
            continue
        for key in {name_key(raw) for raw in re.split(SPLIT, org)} & set(segment_federal):
            segment_all[key] += count
    demand = [
        {
            "key": key,
            "federal_appearances": segment_federal[key],
            "all_appearances": segment_all[key],
            "spellings": [[text, n] for text, n in sorted(spellings[key].items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
        }
        for key in sorted(segment_federal, key=lambda k: (-segment_federal[k], -segment_all[k], k))
        if segment_federal[key] >= MIN_FEDERAL or segment_all[key] >= MIN_ALL
    ]
    total = sum(count for _, count in federal)
    matched = sum(count for org, count in federal if org is not None and ct_match(org))
    result = {
        "inputs": {
            "appearances": {"name": appearances.name, "sha256": sha256(appearances)},
            "roster": {"path": str(ROSTER.relative_to(ROOT)), "sha256": sha256(ROSTER), "agencies": len(agencies)},
            "script_sha256": sha256(Path(__file__)),
        },
        "thresholds": {"min_federal_appearances": MIN_FEDERAL, "min_all_appearances": MIN_ALL},
        "federal": {
            "appearances": total,
            "matched": matched,
            "null_organization": sum(count for org, count in federal if org is None),
            "distinct_strings": len(federal),
            "distinct_matched": sum(1 for org, _ in federal if org is not None and ct_match(org)),
            "unmatched_segment_keys": len(segment_federal),
            "unmatched_segment_appearances": sum(segment_federal.values()),
        },
        "demand": demand,
    }
    OUTPUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "demand"}, indent=1), len(demand), "demand keys")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

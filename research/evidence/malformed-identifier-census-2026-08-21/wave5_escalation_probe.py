"""Wave 5: the two escalations wave 4's fences leave on the table, measured.

Wave 4 read a bare section against the RIN's pool, then the agency's, and
stopped. Wave 3 refused the corpus-wide ACT roster because "CAA" reaches both
the Clean Air Act and the Consolidated Appropriations Act, 2014. Both stopping
points are re-measured here, and one of them is re-measured under the fence
nobody has used: the edition's own date.

A. the section->title read where the citing agency is SILENT -- the exact
   population a corpus-level escalation would answer, held out, and then the
   same population sliced by how much corpus support the section has.
B. the corpus-wide abbreviation roster with the TRUE act removed, unbounded
   and bounded by the edition year -- a 1998 filing cannot cite an act of 2014.

Run: ``uv run python research/evidence/malformed-identifier-census-2026-08-21/wave5_escalation_probe.py``
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
TABLE = ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"

from refspec.registry.unified_agenda_parquet import (  # noqa: E402
    _abbrev_survivors,
    _act_initialism,
)


def distinctive(section: str) -> bool:
    return bool(re.search(r"[a-z]", section) or "-" in section or len(re.sub(r"\D", "", section)) >= 4)


def act_year(key: str) -> int | None:
    years = [int(m.group(0)) for m in re.finditer(r"\b(?:18|19|20)\d{2}\b", key)]
    return max(years) if years else None


def main() -> None:
    rows = pq.read_table(TABLE).to_pylist()
    grammar = [r for r in rows if r["parse_status"] != "corroborated"]

    corpus: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    agency_sec: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    usc_rows = []
    for r in grammar:
        if (
            r["authority_type"] == "usc"
            and r["usc_title"] is not None
            and r["usc_section"]
            and not r["usc_appendix"]
            and r["usc_title_is_possible"]
        ):
            section = r["usc_section"].lower()
            corpus[section][r["usc_title"]] += 1
            agency_sec[(r["rin"][:4], section)][r["rin"]] += 1
            usc_rows.append(r)

    # ---- A. the agency-silent population ---------------------------------
    print("== A. section->title where the citing agency is silent ==")
    tally = collections.Counter()
    wrong = collections.Counter()
    buckets: dict[int, list[int]] = collections.defaultdict(lambda: [0, 0])
    distinct_seen: dict[str, tuple[int, int, int]] = {}
    for r in usc_rows:
        section, title, rin = r["usc_section"].lower(), r["usc_title"], r["rin"]
        contributors = agency_sec[(rin[:4], section)]
        # Hold out this RULE entirely: pretend it never cited the section
        # successfully, which is the situation a damaged row is in.
        if set(contributors) - {rin}:
            tally["agency-speaks"] += 1
            continue
        tally["agency-silent"] += 1
        if not distinctive(section):
            tally["silent-not-distinctive"] += 1
            continue
        counts = collections.Counter(corpus[section])
        counts[title] -= contributors[rin]
        if counts[title] <= 0:
            del counts[title]
        if not counts:
            tally["silent-corpus-empty"] += 1
            continue
        if len(counts) != 1:
            tally["silent-corpus-ambiguous"] += 1
            continue
        answer, support = next(iter(counts.items()))
        tally["answered"] += 1
        hit = answer == title
        tally["right"] += hit
        for threshold in (1, 5, 10, 25, 50, 100, 250, 500, 1000):
            if support >= threshold:
                buckets[threshold][0] += 1
                buckets[threshold][1] += hit
        if not hit:
            wrong[(section, title, answer, support)] += 1
        distinct_seen[section] = (title, answer, support)
    a, g = tally["answered"], tally["right"]
    print(f"   {dict(tally)}")
    print(f"   held-out accuracy on the agency-silent population: {g}/{a} = {g / a:.4f}" if a else "   none")
    print("   sliced by corpus support (how many citations back the unique title):")
    for threshold in sorted(buckets):
        n, r_ = buckets[threshold]
        print(f"      support >= {threshold:5d}:  {r_:5d}/{n:5d} = {r_ / n:.4f}")
    print("   disagreements (section: true vs corpus answer, corpus support):")
    for (section, true, answer, support) in [k for k, _ in wrong.most_common(15)]:
        print(f"      {wrong[(section, true, answer, support)]:4d}  {section!r}: true {true}, corpus {answer} (support {support})")

    # ---- B. the corpus-wide abbreviation roster, true act removed --------
    print("\n== B. corpus-wide abbreviation roster, TRUE ACT REMOVED ==")
    corpus_acts = sorted({r["act_key"] for r in grammar if r["act_key"]})
    print(f"   corpus-wide roster: {len(corpus_acts)} acts")
    seen = set()
    tallyb = collections.Counter()
    invented = collections.Counter()
    for r in grammar:
        if not r["act_key"]:
            continue
        key = (r["act_key"], r["publication_id"])
        if key in seen:
            continue
        seen.add(key)
        ab = _act_initialism(r["act_key"])
        if len(ab) < 2:
            continue
        edition_year = int(r["publication_id"][:4])
        for bounded in (False, True):
            pool = [
                k for k in corpus_acts
                if k != r["act_key"] and (not bounded or (act_year(k) or 0) <= edition_year)
            ]
            survivors = _abbrev_survivors(ab, None, pool)
            label = "bounded" if bounded else "unbounded"
            if len(survivors) == 1:
                tallyb[f"{label}-INVENTED"] += 1
                invented[(ab, r["act_key"], survivors[0], label)] += 1
            elif survivors:
                tallyb[f"{label}-ambiguous(safe)"] += 1
            else:
                tallyb[f"{label}-silent(safe)"] += 1
    print(f"   {dict(tallyb)}")
    for label in ("unbounded", "bounded"):
        bad = tallyb[f"{label}-INVENTED"]
        tot = bad + tallyb[f"{label}-ambiguous(safe)"] + tallyb[f"{label}-silent(safe)"]
        print(f"   {label}: invented a confident WRONG survivor {bad}/{tot} = {bad / tot:.4f}" if tot else "")
    print("   inventions (bounded):")
    for (ab, true, answer, label), n in invented.most_common(20):
        if label == "bounded":
            print(f"      {n:3d}  {ab}: true {true!r} -> roster says {answer!r}")


if __name__ == "__main__":
    main()

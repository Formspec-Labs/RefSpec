"""Wave 5: measure the fences waves 1-4 never used, before adopting any.

Wave 4's lesson was that a better-fenced ORACLE beats better operators. Four
fences were named but never measured:

1. the corpus-wide section->title read with NO agency requirement (wave 4
   required the citing RIN or agency to hold the section too);
2. the RECORD's own authority list -- the citations printed beside this one in
   the same (rin, publication_id) list -- as a title oracle, which needs no
   distinctiveness at all if the record is single-titled;
3. the publication date against a series' dated bounds (a 1998 filing cannot
   cite a 2003 act);
4. the rule's CFR parts as a subject fence.

Every number printed here is held out: the row being predicted contributes
nothing to the oracle that predicts it.

Run: ``uv run python research/evidence/malformed-identifier-census-2026-08-21/wave5_fence_probe.py``
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "output/registry-real-data-sources/unified-agenda-parquet"
TABLE = DIR / "unified_agenda_legal_authorities.parquet"
CFR_TABLE = DIR / "unified_agenda_cfr_references.parquet"


def distinctive(section: str) -> bool:
    return bool(re.search(r"[a-z]", section) or "-" in section or len(re.sub(r"\D", "", section)) >= 4)


def main() -> None:
    rows = pq.read_table(TABLE).to_pylist()
    grammar = [r for r in rows if r["parse_status"] != "corroborated"]

    # ---- pools -----------------------------------------------------------
    # section -> Counter(title): the corpus's whole testimony, held out by
    # subtracting the predicted row's own contribution.
    corpus: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    # (rin, publication_id) -> Counter(title): the record's own authority list.
    record: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    # (rin, publication_id) -> set of sections cited in that record
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
            record[(r["rin"], r["publication_id"])][r["usc_title"]] += 1
            usc_rows.append(r)

    print(f"grammar-read USC citations with a title and section: {len(usc_rows)}")

    # ---- fence 1: corpus-unique + distinctive, NO agency requirement ------
    tally = collections.Counter()
    wrong = collections.Counter()
    for r in usc_rows:
        section, title = r["usc_section"].lower(), r["usc_title"]
        counts = collections.Counter(corpus[section])
        counts[title] -= 1
        if counts[title] <= 0:
            del counts[title]
        if not counts:
            tally["silent"] += 1
            continue
        if not distinctive(section):
            tally["not-distinctive"] += 1
            continue
        if len(counts) != 1:
            tally["not-corpus-unique"] += 1
            continue
        answer = next(iter(counts))
        tally["answered"] += 1
        if answer == title:
            tally["right"] += 1
        else:
            wrong[(section, title, answer)] += 1
    answered, right = tally["answered"], tally["right"]
    print("\n== fence 1: corpus-unique + distinctive, agency NOT consulted ==")
    print(f"   {dict(tally)}")
    print(f"   held-out accuracy: {right}/{answered} = {right / answered:.4f}" if answered else "   none")
    print("   worst disagreements:")
    for (section, true, answer), n in wrong.most_common(12):
        print(f"      {n:4d}  section {section!r}:真 {true} vs corpus {answer}")

    # ---- fence 2: the record's own authority list -------------------------
    for require_corpus_member in (False, True):
        tally2 = collections.Counter()
        wrong2 = collections.Counter()
        for r in usc_rows:
            section, title = r["usc_section"].lower(), r["usc_title"]
            key = (r["rin"], r["publication_id"])
            counts = collections.Counter(record[key])
            counts[title] -= 1
            if counts[title] <= 0:
                del counts[title]
            if not counts:
                tally2["silent"] += 1
                continue
            if len(counts) != 1:
                tally2["record-multi-titled"] += 1
                continue
            answer = next(iter(counts))
            if require_corpus_member:
                members = collections.Counter(corpus[section])
                members[title] -= 1
                if members[title] <= 0:
                    del members[title]
                if answer not in members:
                    tally2["section-not-under-that-title"] += 1
                    continue
            tally2["answered"] += 1
            if answer == title:
                tally2["right"] += 1
            else:
                wrong2[(section, title, answer)] += 1
        a2, r2 = tally2["answered"], tally2["right"]
        label = "record single-titled + section attested under it" if require_corpus_member else "record single-titled"
        print(f"\n== fence 2: {label} ==")
        print(f"   {dict(tally2)}")
        print(f"   held-out accuracy: {r2}/{a2} = {r2 / a2:.4f}" if a2 else "   none")
        for (section, true, answer), n in wrong2.most_common(8):
            print(f"      {n:4d}  section {section!r}: true {true} vs record {answer}")

    # ---- fence 3: dates ---------------------------------------------------
    print("\n== fence 3: the edition as a dated bound ==")
    # Public Laws: a congress's laws cannot be cited before that congress sat.
    # congress N convened in year 1789 + 2*(N-1) ; first session Jan of that year.
    late = collections.Counter()
    total_pl = 0
    for r in grammar:
        if not r["public_law"] or not r["pl_congress_in_series"]:
            continue
        try:
            congress = int(r["public_law"].split("-", 1)[0])
        except ValueError:
            continue
        total_pl += 1
        convened = 1789 + 2 * (congress - 1)
        edition_year = int(r["publication_id"][:4])
        if convened > edition_year:
            late[(congress, r["publication_id"])] += 1
    print(f"   grammar-read PL rows: {total_pl}; citing a congress that had not yet sat: {sum(late.values())}")
    for (congress, pid), n in late.most_common(8):
        print(f"      {n:4d}  congress {congress} in edition {pid}")

    # How much would the date bound narrow the bare-PL roster?
    print("\n   bare-PL roster narrowing (how many congresses an agency's roster offers)")
    agency_pl: dict[str, set[tuple[int, int]]] = collections.defaultdict(set)
    for r in grammar:
        if r["public_law"] and r["pl_congress_in_series"]:
            try:
                c, n = (int(x) for x in r["public_law"].split("-", 1))
            except ValueError:
                continue
            agency_pl[r["rin"][:4]].add((c, n))
    failed = [r for r in rows if r["parse_status"] == "failed" and r["authority_type"] == "other"]
    bare_pl = re.compile(r"^(?:Pub(?:lic)?\.?\s*L(?:aw)?\.?|P\.?\s?L\.?)\s*(?:No\.?\s*)?(\d{1,4}[A-Za-z]?)[\s.,;]*$", re.IGNORECASE)
    narrowing = collections.Counter()
    for r in failed:
        m = bare_pl.match(r["authority_text"].strip())
        if not m or not m.group(1).isdigit():
            continue
        number = int(m.group(1))
        edition_year = int(r["publication_id"][:4])
        roster = agency_pl.get(r["rin"][:4], set())
        all_c = {c for (c, n) in roster if n == number}
        dated_c = {c for c in all_c if 1789 + 2 * (c - 1) <= edition_year}
        narrowing[(len(all_c), len(dated_c))] += 1
    print(f"      (candidates before, after date bound) -> rows: {dict(narrowing)}")

    # ---- fence 4: the rule's CFR parts as a subject fence ------------------
    print("\n== fence 4: the rule's own CFR titles ==")
    cfr = pq.read_table(CFR_TABLE).to_pylist()
    rule_cfr_titles: dict[tuple[str, str], set[int]] = collections.defaultdict(set)
    for c in cfr:
        if c.get("cfr_title") is not None:
            rule_cfr_titles[(c["rin"], c["publication_id"])].add(c["cfr_title"])
    tally4 = collections.Counter()
    for r in usc_rows:
        titles = rule_cfr_titles.get((r["rin"], r["publication_id"]), set())
        if not titles:
            tally4["no-cfr"] += 1
        elif len(titles) > 1:
            tally4["multi-cfr"] += 1
        elif next(iter(titles)) == r["usc_title"]:
            tally4["single-cfr-matches-usc-title"] += 1
        else:
            tally4["single-cfr-differs"] += 1
    print(f"   {dict(tally4)}")
    same = tally4["single-cfr-matches-usc-title"]
    tot = same + tally4["single-cfr-differs"]
    print(f"   CFR title == USC title where the rule has exactly one CFR title: {same}/{tot} = {same / tot:.4f}" if tot else "")


if __name__ == "__main__":
    main()

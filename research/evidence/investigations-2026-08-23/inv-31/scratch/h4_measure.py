"""H4: tokens one edit away from a scheme label, behind a corroboration gate."""
from __future__ import annotations

import collections
import csv
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: F401,E402

import pyarrow.parquet as pq  # noqa: E402

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402
from refspec.registry.unified_agenda_parquet import (  # noqa: E402
    _OFR_INDEX_CSV, _PL_ROSTER_CSV, _SeriesCalendar, _pl_roster, _usc_section_oracle,
    _current_ofr_parts,
)

#: The labels a legal-authority box can wear. Spelled as the grammar accepts
#: them; the repair proposes one of these in place of the damaged token.
CONNECTIVES = ("Stat.", "U.S.C.", "USC", "Pub. L.", "PL", "sec.", "CFR", "FR")
#: Comparison forms: case-folded, punctuation-free.
def fold(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


FOLDED = {c: fold(c) for c in CONNECTIVES}


def lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 2
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_TOKEN = re.compile(r"[A-Za-z0-9.]+")
_SPLIT = re.compile(r"^(?P<lead>\d*)(?P<word>[A-Za-z.]+)(?P<trail>\d*)$")


def candidates_in(text: str) -> list[dict]:
    """Every token one edit from a label, with the digits it is welded to."""
    out = []
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        parts = _SPLIT.match(tok)
        if not parts:
            continue
        word = parts.group("word")
        w = fold(word)
        if not w or len(w) > 8:
            continue
        for label, f in FOLDED.items():
            if w == f:
                break                       # already the label: no damage
        else:
            hits = [(label, lev(w, f)) for label, f in FOLDED.items() if lev(w, f) == 1]
            if hits:
                out.append({"token": tok, "word": word, "lead": parts.group("lead"),
                            "trail": parts.group("trail"), "span": [m.start(), m.end()],
                            "candidates": [h[0] for h in hits]})
    return out


def main() -> None:
    t = pq.read_table(common.BASE)
    cols = {n: t.column(n).to_pylist() for n in t.schema.names}
    n = t.num_rows
    oracle = _usc_section_oracle()
    roster = _pl_roster()
    calendar = _SeriesCalendar.build(roster)
    ofr = _current_ofr_parts()
    stat_by_pl = roster[1] if roster else {}
    print(f"oracle {'loaded' if oracle else 'MISSING'}; PL roster "
          f"{len(roster[0]) if roster else 0:,} laws; OFR parts {len(ofr) if ofr else 0:,}")

    failed = [i for i in range(n)
              if cols["authority_type"][i] == "other" and cols["parse_status"][i] == "failed"]
    print(f"rows typed other/failed: {len(failed):,}  "
          f"(distinct texts {len({cols['authority_text'][i] for i in failed}):,})")

    hits: list[dict] = []
    label_counter = collections.Counter()
    ambiguous = 0
    for i in failed:
        text = cols["authority_text"][i]
        cs = candidates_in(text)
        if not cs:
            continue
        for c in cs:
            label_counter[tuple(sorted(c["candidates"]))] += 1
            if len(c["candidates"]) > 1:
                ambiguous += 1
        hits.append({"row": i, "rin": cols["rin"][i], "pub": cols["publication_id"][i],
                     "ordinal": cols["ordinal"][i], "text": text, "tokens": cs})

    print(f"\nother/failed rows holding a token ONE edit from a label: {len(hits):,}")
    print(f"  distinct texts: {len({h['text'] for h in hits}):,}")
    print(f"  damaged tokens with >1 label within one edit: {ambiguous:,}")
    print("  by proposed label set:")
    for k, c in label_counter.most_common(20):
        print(f"    {'/'.join(k):<26} {c:>6,}")

    # ---- corroborate each repaired reading ---------------------------------
    for h in hits:
        year = int(h["pub"][:4])
        survivors = []
        for c in h["tokens"]:
            for label in c["candidates"]:
                repl = c["lead"] + (" " if c["lead"] else "") + label + \
                       ((" " + c["trail"]) if c["trail"] else "")
                repaired = h["text"][:c["span"][0]] + repl + h["text"][c["span"][1]:]
                reads = parse_authority_citation(repaired)
                for r in reads:
                    if r.authority_type == "other":
                        continue
                    ev: list[str] = []
                    ok = False
                    if r.authority_type == "usc" and r.usc_title and r.usc_section:
                        v = oracle.section_verdict(r.usc_title, r.usc_section, year,
                                                   appendix=r.usc_appendix)
                        ev.append(f"oracle:{r.usc_title} U.S.C. {r.usc_section}={v.verdict}")
                        ok = v.verdict == "exists"
                    elif r.authority_type == "statute_at_large" and r.statute_volume:
                        inser = calendar.stat_volume_in_series(r.statute_volume, h["pub"])
                        ev.append(f"stat_volume_in_series={inser}")
                        ok = bool(inser)
                    elif r.authority_type == "public_law" and r.public_law:
                        try:
                            cong, law = (int(x) for x in r.public_law.split("-", 1))
                            ev.append(f"pl_in_roster={(cong, law) in stat_by_pl}")
                            ok = (cong, law) in stat_by_pl
                        except ValueError:
                            ev.append("pl_unparsed")
                    elif r.authority_type == "cfr" and r.cfr_title and r.cfr_part:
                        inofr = ofr is not None and (r.cfr_title, r.cfr_part.lower()) in ofr
                        ev.append(f"cfr_part_in_current_ofr_index={inofr}")
                        ok = inofr
                    elif r.authority_type == "federal_register" and r.fr_volume:
                        inser = calendar.fr_volume_in_series(r.fr_volume, h["pub"])
                        ev.append(f"fr_volume_in_series={inser}")
                        ok = bool(inser)
                    survivors.append({"label": label, "repaired": repaired,
                                      "type": r.authority_type,
                                      "reading": {k: v for k, v in vars(r).items()
                                                  if v is not None and v is not False
                                                  and k not in {"parse_status"}},
                                      "evidence": ev, "corroborated": ok})
        h["survivors"] = survivors
        good = [s for s in survivors if s["corroborated"]]
        h["corroborated"] = len(good)
        h["exactly_one"] = len({(s["type"], json.dumps(s["reading"], sort_keys=True, default=str))
                                for s in good}) == 1

    with_any = [h for h in hits if h["corroborated"]]
    exactly = [h for h in hits if h["exactly_one"]]
    print(f"\nrows where SOME repaired reading is corroborated:  {len(with_any):,}")
    print(f"rows where EXACTLY ONE corroborated reading survives: {len(exactly):,}")
    print("  by surviving type:",
          dict(collections.Counter(
              next(s["type"] for s in h["survivors"] if s["corroborated"]) for h in exactly)))

    out = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
    (out / "h4_hits.json").write_text(json.dumps(hits, ensure_ascii=False, default=str),
                                      encoding="utf-8")

    keys = sorted((h["rin"], h["pub"], h["ordinal"]) for h in hits)
    sample = random.Random(20260823).sample(keys, 10)
    idx = {(h["rin"], h["pub"], h["ordinal"]): h for h in hits}
    picked = [idx[k] for k in sample]
    print("\n=== 10 seeded examples ===")
    for h in picked:
        print(f"  {h['rin']} {h['pub']} ord{h['ordinal']}  text={h['text']!r}")
        for c in h["tokens"]:
            print(f"    damaged token {c['token']!r} -> {c['candidates']}")
        for s in h["survivors"]:
            print(f"      [{'CORROBORATED' if s['corroborated'] else 'refused     '}] "
                  f"{s['label']:<8} {s['repaired']!r} -> {s['type']} {s['reading']} {s['evidence']}")
        print(f"    exactly-one-survivor: {h['exactly_one']}")
    (out / "h4_seeded.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")

    print("\n=== specimen: 113tat. 1754 (1999) ===")
    for h in hits:
        if h["text"] == "113tat. 1754 (1999)":
            print(f"  {h['rin']} {h['pub']} ord{h['ordinal']}")
            for c in h["tokens"]:
                print(f"    token {c['token']!r} lead={c['lead']!r} -> {c['candidates']}")
            for s in h["survivors"]:
                print(f"    [{'CORROBORATED' if s['corroborated'] else 'refused'}] {s['repaired']!r}"
                      f" -> {s['type']} {s['reading']} {s['evidence']}")
            print(f"    exactly-one-survivor: {h['exactly_one']}")


main()

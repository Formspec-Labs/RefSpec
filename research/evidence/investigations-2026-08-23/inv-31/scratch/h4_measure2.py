"""H4 take 2: three fences before the corroboration gate.

  F1  the folded token is at least two letters ("f", "p" are not damage)
  F2  the token is not already a spelling the grammar accepts (probe test)
  F3  the token sits in citation shape: welded to digits, or with a bare
      number immediately beside it
"""
from __future__ import annotations

import collections
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
    _SeriesCalendar, _current_ofr_parts, _pl_roster, _usc_section_oracle,
)

CONNECTIVES = ("Stat.", "U.S.C.", "USC", "Pub. L.", "PL", "sec.", "CFR", "FR")


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
_ACCEPTED: dict[str, bool] = {}


def already_accepted(word: str) -> bool:
    """F2: does the grammar already read this spelling as a label?"""
    if word not in _ACCEPTED:
        ok = False
        for probe in (f"42 {word} 1983", f"{word} 1983", f"110 {word} 1936"):
            if any(c.authority_type != "other" for c in parse_authority_citation(probe)):
                ok = True
                break
        _ACCEPTED[word] = ok
    return _ACCEPTED[word]


def candidates_in(text: str) -> list[dict]:
    toks = list(_TOKEN.finditer(text))
    out = []
    for k, m in enumerate(toks):
        tok = m.group(0)
        parts = _SPLIT.match(tok)
        if not parts:
            continue
        word, lead, trail = parts.group("word"), parts.group("lead"), parts.group("trail")
        w = fold(word)
        if len(w) < 2 or len(w) > 8:                       # F1
            continue
        if any(w == f for f in FOLDED.values()):
            continue
        if already_accepted(word):                          # F2
            continue
        welded = bool(lead or trail)
        beside = any(
            toks[j].group(0).strip(".").isdigit()
            for j in (k - 1, k + 1) if 0 <= j < len(toks)
        )
        if not (welded or beside):                          # F3
            continue
        hits = [label for label, f in FOLDED.items() if lev(w, f) == 1]
        if hits:
            out.append({"token": tok, "word": word, "lead": lead, "trail": trail,
                        "span": [m.start(), m.end()], "candidates": hits,
                        "shape": "welded" if welded else "beside-a-number"})
    return out


def main() -> None:
    t = pq.read_table(common.BASE)
    cols = {n: t.column(n).to_pylist() for n in t.schema.names}
    n = t.num_rows
    oracle = _usc_section_oracle()
    roster = _pl_roster()
    calendar = _SeriesCalendar.build(roster)
    ofr = _current_ofr_parts()
    pl_keys = set(roster[1]) if roster else set()

    failed = [i for i in range(n)
              if cols["authority_type"][i] == "other" and cols["parse_status"][i] == "failed"]
    print(f"rows typed other/failed: {len(failed):,}  "
          f"(distinct texts {len({cols['authority_text'][i] for i in failed}):,})")

    hits: list[dict] = []
    labels = collections.Counter()
    shapes = collections.Counter()
    for i in failed:
        text = cols["authority_text"][i]
        cs = candidates_in(text)
        if not cs:
            continue
        for c in cs:
            labels[tuple(sorted(c["candidates"]))] += 1
            shapes[c["shape"]] += 1
        hits.append({"rin": cols["rin"][i], "pub": cols["publication_id"][i],
                     "ordinal": cols["ordinal"][i], "text": text, "tokens": cs})

    print(f"\nafter F1/F2/F3 -- other/failed rows with a token one edit from a label: {len(hits):,}")
    print(f"  distinct texts: {len({h['text'] for h in hits}):,}")
    print("  token shape:", dict(shapes))
    print("  proposed label(s):")
    for k, c in labels.most_common():
        print(f"    {'/'.join(k):<26} {c:>6,}")

    for h in hits:
        survivors = []
        for c in h["tokens"]:
            for label in c["candidates"]:
                repl = (c["lead"] + " " if c["lead"] else "") + label + \
                       (" " + c["trail"] if c["trail"] else "")
                repaired = h["text"][:c["span"][0]] + repl + h["text"][c["span"][1]:]
                for r in parse_authority_citation(repaired):
                    if r.authority_type == "other":
                        continue
                    ev: list[str] = []
                    ok = False
                    if r.authority_type == "usc" and r.usc_title and r.usc_section:
                        v = oracle.section_verdict(r.usc_title, r.usc_section,
                                                   int(h["pub"][:4]), appendix=r.usc_appendix)
                        ev.append(f"section-oracle({r.usc_title} U.S.C. {r.usc_section})={v.verdict}"
                                  f"; attested_at_edition={v.attested_at_edition}")
                        ok = v.verdict == "exists"
                    elif r.authority_type == "statute_at_large" and r.statute_volume:
                        s = calendar.stat_volume_in_series(r.statute_volume, h["pub"])
                        ev.append(f"PL-roster stat_volume_in_series({r.statute_volume})={s}")
                        ok = bool(s)
                    elif r.authority_type == "public_law" and r.public_law:
                        try:
                            key = tuple(int(x) for x in r.public_law.split("-", 1))
                            ev.append(f"PL-roster holds {r.public_law}={key in pl_keys}")
                            ok = key in pl_keys
                        except ValueError:
                            ev.append("public_law unparsable")
                    elif r.authority_type == "cfr" and r.cfr_title and r.cfr_part:
                        io = ofr is not None and (r.cfr_title, r.cfr_part.lower()) in ofr
                        ev.append(f"OFR index holds {r.cfr_title} CFR {r.cfr_part}={io}")
                        ok = io
                    elif r.authority_type == "federal_register" and r.fr_volume:
                        s = calendar.fr_volume_in_series(r.fr_volume, h["pub"])
                        ev.append(f"fr_volume_in_series({r.fr_volume})={s}")
                        ok = bool(s)
                    else:
                        ev.append("no oracle for this type")
                    survivors.append({"label": label, "repaired": repaired,
                                      "type": r.authority_type,
                                      "reading": {k: v for k, v in vars(r).items()
                                                  if v is not None and v is not False
                                                  and k != "parse_status"},
                                      "evidence": ev, "corroborated": ok})
        h["survivors"] = survivors
        good = [s for s in survivors if s["corroborated"]]
        h["corroborated"] = len(good)
        h["distinct_corroborated"] = len({json.dumps(s["reading"], sort_keys=True, default=str)
                                          for s in good})
        h["exactly_one"] = h["distinct_corroborated"] == 1

    any_c = [h for h in hits if h["corroborated"]]
    one = [h for h in hits if h["exactly_one"]]
    print(f"\nrows with SOME corroborated repaired reading:     {len(any_c):,}")
    print(f"rows with EXACTLY ONE corroborated reading:       {len(one):,}")
    print("  by type:", dict(collections.Counter(
        next(s["type"] for s in h["survivors"] if s["corroborated"]) for h in one)))
    print("  distinct texts among them:", len({h["text"] for h in one}))

    out = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
    (out / "h4_hits2.json").write_text(json.dumps(hits, ensure_ascii=False, default=str),
                                       encoding="utf-8")

    keys = sorted((h["rin"], h["pub"], h["ordinal"]) for h in hits)
    sample = random.Random(20260823).sample(keys, 10)
    idx = {(h["rin"], h["pub"], h["ordinal"]): h for h in hits}
    picked = [idx[k] for k in sample]
    print("\n=== 10 seeded examples (random.Random(20260823).sample over sorted keys) ===")
    for h in picked:
        print(f"  {h['rin']} {h['pub']} ord{h['ordinal']}  text={h['text']!r}")
        for c in h["tokens"]:
            print(f"    token {c['token']!r} ({c['shape']}) -> propose {c['candidates']}")
        for s in h["survivors"]:
            print(f"      [{'CORROBORATED' if s['corroborated'] else 'refused     '}] "
                  f"{s['repaired']!r} -> {s['type']} {s['reading']}")
            for e in s["evidence"]:
                print(f"            {e}")
        if not h["survivors"]:
            print("      (no repaired reading parses at all)")
        print(f"    exactly-one-survivor: {h['exactly_one']}")
    (out / "h4_seeded2.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1,
                                                    default=str), encoding="utf-8")

    print("\n=== the corroborated set, by distinct text ===")
    seen = collections.Counter()
    for h in one:
        seen[h["text"]] += 1
    for text, c in seen.most_common(40):
        h = next(x for x in one if x["text"] == text)
        s = next(x for x in h["survivors"] if x["corroborated"])
        print(f"  {c:>3} rows  {text!r} -> {s['repaired']!r}  {s['type']} {s['reading']}")
        print(f"            {s['evidence']}")


main()

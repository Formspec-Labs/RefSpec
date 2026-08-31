"""Wave 4's oracle: a rule's own citation history, at the RIN and the agency.

Wave 3 escalated the ACT oracle one level (RIN -> agency) and recovered 2,758
rows. This probe asks the same question of the shapes that lost a *label* or a
*container* rather than a name: a bare section list ("31136(a)"), a title-less
code citation ("USC 44101"), a label-less pair ("49 46105"), a volume-less
Statutes page ("Stat. 2936").

The oracle is the publisher's own resolved citations -- never a corroborated
row, so corroboration never bootstraps on corroboration -- read first at the
citing RIN and then at the citing agency (the RIN's leading four digits are
the OMB agency code). A reading is emitted only when exactly one survivor
stands at the first level that speaks.

Run: ``uv run python research/evidence/malformed-identifier-census-2026-08-21/rin_history_oracle_probe.py``
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
TABLE = ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"

#: A section token that is not a short generic ordinal. Measured 2026-08-22:
#: the held-out accuracy of the corpus-unique fence rises from 0.9574 to
#: 0.9963 once short bare ordinals ("42", "301", "504") are excluded -- those
#: are the numbers every title reuses.
def distinctive(section: str) -> bool:
    return bool(re.search(r"[a-z]", section) or "-" in section or len(re.sub(r"\D", "", section)) >= 4)


TOKEN = r"\d{1,5}[a-z]{0,3}(?:-\d{1,4}[a-z]?)?(?:\([^()]{1,10}\))*(?:\s+note)?(?:\s+et\s+seq\.?)?"
SECTION_LIST = re.compile(
    rf"^(?:[Ss]ecs?\.?\s+|[Ss]ections?\s+)?{TOKEN}(?:\s*(?:,|and|or|through|to)\s*{TOKEN})*[\s.,;]*$"
)
SPLIT = re.compile(r"\s*(?:,|\band\b|\bor\b)\s*")


def section_tokens(text: str) -> list[str] | None:
    stripped = text.strip().strip("\"“”' ")
    if not SECTION_LIST.match(stripped):
        return None
    body = re.sub(r"^(?:[Ss]ecs?\.?|[Ss]ections?)\s+", "", stripped).rstrip(" .,;")
    body = re.sub(rf"({TOKEN})\s+(?:to|through)\s+({TOKEN})", r"\1|\2", body)
    return [token for token in SPLIT.split(body) if token]


def bare(token: str) -> str:
    value = token.strip().lower().replace(" et seq.", "").replace(" et seq", "").replace(" note", "")
    value = re.sub(r"\([^()]*\)", "", value).strip()
    return value.split("|")[0].strip()


def load():
    rows = pq.read_table(TABLE).to_pylist()
    grammar = [r for r in rows if r["parse_status"] != "corroborated"]
    pools: dict[str, dict[str, set]] = {
        level: collections.defaultdict(set) for level in ("usc_rin", "usc_ag", "act_rin", "act_ag", "stat_rin", "stat_ag")
    }
    usc_corpus: dict[str, set[int]] = collections.defaultdict(set)
    for r in grammar:
        rin, agency = r["rin"], r["rin"][:4]
        if (
            r["authority_type"] == "usc"
            and r["usc_title"] is not None
            and r["usc_section"]
            and not r["usc_appendix"]
            and r["usc_title_is_possible"]
        ):
            section = r["usc_section"].lower()
            usc_corpus[section].add(r["usc_title"])
            pools["usc_rin"][rin].add((r["usc_title"], section))
            pools["usc_ag"][agency].add((r["usc_title"], section))
        if r["act_key"] and r["act_section"]:
            pools["act_rin"][rin].add((r["act_key"], r["act_section"].lower()))
            pools["act_ag"][agency].add((r["act_key"], r["act_section"].lower()))
        if r["statute_volume"] is not None and r["statute_page"] is not None:
            pools["stat_rin"][rin].add((r["statute_volume"], r["statute_page"]))
            pools["stat_ag"][agency].add((r["statute_volume"], r["statute_page"]))
    failed = [r for r in rows if r["parse_status"] == "failed" and r["authority_type"] == "other"]
    return rows, failed, pools, usc_corpus


def survivors(pools, usc_corpus, level, key, token):
    value = bare(token)
    out = set()
    if distinctive(value) and len(usc_corpus.get(value, ())) == 1:
        out |= {("usc", t) for (t, s) in pools[f"usc_{level}"].get(key, ()) if s == value}
    out |= {("act", k) for (k, s) in pools[f"act_{level}"].get(key, ()) if s == value}
    return out


def main() -> None:
    rows, failed, pools, usc_corpus = load()
    print(f"rows {len(rows)}  failed {len(failed)}")

    # --- 1. bare section lists ---------------------------------------------
    tally = collections.Counter()
    recovered = collections.defaultdict(list)
    for r in failed:
        tokens = section_tokens(r["authority_text"])
        if tokens is None:
            continue
        tally["shaped"] += 1
        for level, key in (("rin", r["rin"]), ("ag", r["rin"][:4])):
            per = [survivors(pools, usc_corpus, level, key, t) for t in tokens]
            if any(len(s) > 1 for s in per):
                tally[f"ambiguous-{level}"] += 1
                break
            if all(len(s) == 1 for s in per):
                keys = {next(iter(s)) for s in per}
                if len(keys) == 1:
                    tally[f"resolved-{level}"] += 1
                    recovered[(r["authority_text"], next(iter(keys)), level)].append(r["rin"])
                else:
                    tally["tokens-disagree"] += 1
                break
        else:
            tally["silent"] += 1
    print("\n== bare section lists:", dict(tally))
    print(
        "   recovered rows:",
        sum(len(v) for v in recovered.values()),
        "distinct:",
        len({k[0] for k in recovered}),
        "schemes:",
        collections.Counter(k[1][0] for k, v in recovered.items() for _ in v),
    )
    for (text, hit, level), rins in sorted(recovered.items(), key=lambda kv: -len(kv[1]))[:20]:
        print(f"   {len(rins):3d}  [{level}] {hit}  {text!r}  (e.g. {rins[0]})")

    # --- 2. title-less code citations ("USC 44101") -------------------------
    labelled = re.compile(
        r"^U\.?\s?S\.?\s?C\.?(?:\s?A\.?)?\s+(?P<sec>\d{1,5}[A-Za-z]{0,3}(?:-\d{1,4}[A-Za-z]?)?)"
        r"(?:\([^()]{1,10}\))*(?P<note>\s+note)?[\s.,;]*$",
        re.IGNORECASE,
    )
    tally2 = collections.Counter()
    rec2 = collections.defaultdict(list)
    for r in failed:
        m = labelled.match(r["authority_text"].strip().strip("\"“”' "))
        if m is None:
            continue
        tally2["shaped"] += 1
        section = m.group("sec").lower()
        if not distinctive(section) or len(usc_corpus.get(section, ())) != 1:
            tally2["not-corpus-unique"] += 1
            continue
        for level, key in (("rin", r["rin"]), ("ag", r["rin"][:4])):
            hits = {t for (t, s) in pools[f"usc_{level}"].get(key, ()) if s == section}
            if len(hits) == 1:
                tally2[f"resolved-{level}"] += 1
                rec2[(r["authority_text"], next(iter(hits)), level)].append(r["rin"])
                break
            if hits:
                tally2[f"ambiguous-{level}"] += 1
                break
        else:
            tally2["silent"] += 1
    print("\n== title-less USC:", dict(tally2), "recovered", sum(len(v) for v in rec2.values()))
    for (text, hit, level), rins in sorted(rec2.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"   {len(rins):3d}  [{level}] title {hit}  {text!r}  (e.g. {rins[0]})")

    # --- 3. label-less pairs ("49 46105", "8 1252 note") --------------------
    pair = re.compile(
        r"^(?P<title>\d{1,2})\s+(?P<sec>\d{2,5}[A-Za-z]{0,3})(?:\([^()]{1,10}\))*"
        r"(?P<note>\s+note)?(?:\s+et\s+seq\.?)?[\s.,;]*$"
    )
    tally3 = collections.Counter()
    rec3 = collections.defaultdict(list)
    for r in failed:
        m = pair.match(r["authority_text"].strip().strip("\"“”' "))
        if m is None:
            continue
        tally3["shaped"] += 1
        title, section = int(m.group("title")), m.group("sec").lower()
        for level, key in (("rin", r["rin"]), ("ag", r["rin"][:4])):
            usc_hit = (title, section) in pools[f"usc_{level}"].get(key, ())
            stat_hit = section.isdigit() and (title, int(section)) in pools[f"stat_{level}"].get(key, ())
            if usc_hit and stat_hit:
                tally3[f"both-schemes-{level}"] += 1
                break
            if usc_hit or stat_hit:
                tally3[f"resolved-{level}"] += 1
                rec3[(r["authority_text"], ("usc" if usc_hit else "stat", title, section), level)].append(r["rin"])
                break
        else:
            tally3["silent"] += 1
    print("\n== label-less pairs:", dict(tally3), "recovered", sum(len(v) for v in rec3.values()))
    for (text, hit, level), rins in sorted(rec3.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f"   {len(rins):3d}  [{level}] {hit}  {text!r}  (e.g. {rins[0]})")

    # --- 4. volume-less Statutes pages ("Stat. 2936") -----------------------
    statless = re.compile(r"^Stat\.?\s+(?P<page>\d{2,5})[\s.,;]*$", re.IGNORECASE)
    tally4 = collections.Counter()
    rec4 = collections.defaultdict(list)
    for r in failed:
        m = statless.match(r["authority_text"].strip().strip("\"“”' "))
        if m is None:
            continue
        tally4["shaped"] += 1
        page = int(m.group("page"))
        for level, key in (("rin", r["rin"]), ("ag", r["rin"][:4])):
            hits = {v for (v, p) in pools[f"stat_{level}"].get(key, ()) if p == page}
            if len(hits) == 1:
                tally4[f"resolved-{level}"] += 1
                rec4[(r["authority_text"], next(iter(hits)), level)].append(r["rin"])
                break
            if hits:
                tally4[f"ambiguous-{level}"] += 1
                break
        else:
            tally4["silent"] += 1
    print("\n== volume-less Stat pages:", dict(tally4), "recovered", sum(len(v) for v in rec4.values()))
    for (text, hit, level), rins in sorted(rec4.items(), key=lambda kv: -len(kv[1])):
        print(f"   {len(rins):3d}  [{level}] volume {hit}  {text!r}  (e.g. {rins[0]})")

    total = (
        sum(len(v) for v in recovered.values())
        + sum(len(v) for v in rec2.values())
        + sum(len(v) for v in rec3.values())
        + sum(len(v) for v in rec4.values())
    )
    print(f"\nTOTAL recoverable rows across the four shapes: {total}")


if __name__ == "__main__":
    main()

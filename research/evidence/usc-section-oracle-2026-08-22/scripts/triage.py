"""Triage every parsed U.S.C. citation that hits no real section."""

import re
import json
import duckdb
import collections

con = duckdb.connect("/tmp/silent/usc.duckdb", read_only=True)

# ---------------- oracle ----------------
exact = {(t, s) for t, s in con.execute("SELECT title, section FROM ora_exact").fetchall()}
ann = {(t, s) for t, s in con.execute(
    "SELECT DISTINCT title, section FROM ora_ann WHERE NOT appendix").fetchall()}
LIVE = exact | ann
ann_app = {(t, s) for t, s in con.execute(
    "SELECT DISTINCT title, section FROM ora_ann WHERE appendix").fetchall()}
SUBSEC = collections.defaultdict(set)
for t, s, sub in con.execute(
        "SELECT title, section, sub FROM '/tmp/silent/usc_oracle_subsec.parquet'").fetchall():
    SUBSEC[(t, s)].add(sub)
CHAPTER = {(t, c) for t, c in con.execute(
    "SELECT title, chapter FROM '/tmp/silent/usc_oracle_chapter.parquet'").fetchall()}

# sections whose name begins "<stem>-" : 15 USC 80a -> 80a-1 ...
HYPHEN_KIDS = collections.defaultdict(list)
for t, s in LIVE:
    if "-" in s:
        HYPHEN_KIDS[(t, s.split("-", 1)[0])].append(s)


def key(s):
    m = re.match(r"^(\d+)(.*)$", s)
    return (int(m.group(1)), m.group(2)) if m else None


rng_by_title = collections.defaultdict(list)
for t, lo, hi in (con.execute("SELECT title, lo, hi FROM ora_rng").fetchall()
                  + con.execute("SELECT title, lo, hi FROM ora_ann_rng WHERE NOT appendix").fetchall()):
    klo, khi = key(lo), key(hi)
    if klo and khi:
        rng_by_title[t].append((klo, khi))
rng_app = collections.defaultdict(list)
for t, lo, hi in con.execute("SELECT title, lo, hi FROM ora_ann_rng WHERE appendix").fetchall():
    klo, khi = key(lo), key(hi)
    if klo and khi:
        rng_app[t].append((klo, khi))


def sec_exact(t, s):
    """Membership in the exact section list only.

    Range stubs ("Secs. 28 to 43") admit any token whose key sorts inside them,
    which is right for judging a parsed section but far too loose for proposing
    a candidate: it would admit "36o0" as a title 42 section. Candidates are
    therefore tested against the exact list, never against a range.
    """
    return (t, s) in LIVE


def sec_exists(t, s, appendix=False):
    if appendix:
        if (t, s) in ann_app:
            return True
        k = key(s)
        return bool(k) and any(a <= k <= b for a, b in rng_app.get(t, ()))
    if (t, s) in LIVE:
        return True
    k = key(s)
    return bool(k) and any(a <= k <= b for a, b in rng_by_title.get(t, ()))


APPENDIX_TITLES_COVERED = {5, 10, 11, 18, 26, 28, 38, 40, 46, 50}

# ---------------- corpus ----------------
misses = con.execute("""
    SELECT title, section, appendix, rows, texts, rins, first_pub, last_pub, all_note, any_ok
    FROM verdict2 WHERE NOT exists_anywhere ORDER BY rows DESC
""").fetchall()
IMPOSSIBLE = {(t, s) for t, s in con.execute(
    "SELECT DISTINCT usc_title, usc_section FROM rowsv WHERE NOT usc_title_is_possible").fetchall()}

texts_of = collections.defaultdict(list)
for t, s, a, txt, n in con.execute("""
        SELECT usc_title, usc_section, usc_appendix, authority_text, count(*)
        FROM rowsv WHERE NOT exists_anywhere GROUP BY 1,2,3,4""").fetchall():
    texts_of[(t, s, a)].append((txt, n))
for v in texts_of.values():
    v.sort(key=lambda x: -x[1])

rins_of = collections.defaultdict(set)
for r, t, s, a in con.execute(
        "SELECT DISTINCT rin, usc_title, usc_section, usc_appendix FROM rowsv").fetchall():
    rins_of[(t, s, a)].add(r)
rin_states = {(r, t, s) for r, t, s in con.execute(
    "SELECT DISTINCT rin, usc_title, usc_section FROM rowsv").fetchall()}

LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
SUFFIXES = LETTERS + [c * 2 for c in LETTERS] + [c * 3 for c in LETTERS] + [c * 4 for c in LETTERS]
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def near(t, s):
    out = collections.defaultdict(set)

    def add(kind, tt, ss):
        if (tt, ss) != (t, s) and sec_exact(tt, ss):
            out[(tt, ss)].add(kind)

    if re.match(r"^0\d", s):
        add("zero-pad", t, s.lstrip("0"))
    if re.fullmatch(r"\d+", s):
        for suf in SUFFIXES:
            add("suffix-restored", t, s + suf)
    m = re.fullmatch(r"(\d+)([a-z]+)", s)
    if m:
        add("suffix-dropped", t, m.group(1))
    m = re.match(r"^(\d+)(.*)$", s)
    if m:
        num, tail = m.group(1), m.group(2)
        for i in range(len(num) - 1):
            if num[i] != num[i + 1]:
                add("transposed", t, num[:i] + num[i + 1] + num[i] + num[i + 2:] + tail)
        if len(num) > 1:
            for i in range(len(num)):
                add("digit-dropped", t, num[:i] + num[i + 1:] + tail)
        for i in range(len(num) + 1):
            for d in "0123456789":
                add("digit-added", t, num[:i] + d + num[i:] + tail)
        for i in range(len(num)):
            for d in "0123456789":
                if d != num[i]:
                    add("digit-changed", t, num[:i] + d + num[i + 1:] + tail)
    for tt in range(1, 55):
        if tt != t:
            add("other-title", tt, s)
    return out


records = []
for (t, s, app, nrows, ntexts, nrins, fp, lp, all_note, any_ok) in misses:
    tx = texts_of[(t, s, app)]
    joined = " || ".join(x[0] for x in tx).lower()
    cls = fix = why = None

    # ---- C0 the grammar already says this title cannot exist ----
    if (t, s) in IMPOSSIBLE or not (1 <= t <= 54) or t == 53:
        cls, why = "C0 title-impossible", "usc_title_is_possible = false"

    # ---- C1 zero-padded number (derivable: strip the pad) ----
    if cls is None and re.match(r"^0\d", s) and sec_exact(t, s.lstrip("0")):
        cls, fix, why = "C1 zero-padded", f"{t} USC {s.lstrip('0')}", "leading zeros stripped"

    # ---- C2 subsection printed without its parentheses ----
    if cls is None:
        m = re.fullmatch(r"(\d+)([a-z]+)", s)
        if m and sec_exact(t, m.group(1)) and m.group(2) in SUBSEC.get((t, m.group(1)), ()):
            cls, fix = "C2 subsection-as-section", f"{t} USC {m.group(1)}({m.group(2)})"
            why = "no such section; the stem is a section and the tail is one of its subsections"

    # ---- C3 the strip-parenthetical rule ate a real letter suffix ----
    if cls is None and re.fullmatch(r"\d+", s):
        for suf in SUFFIXES:
            if re.search(rf"\b{s}\s*\(\s*{suf}\s*\)", joined):
                for cand in ([s + suf] + sorted(HYPHEN_KIDS.get((t, s + suf), []))):
                    if sec_exact(t, cand):
                        cls, fix = "C3 paren-suffix-eaten", f"{t} USC {cand}"
                        why = f"text writes {s}({suf}); {t} USC {s} is not a section, {t} USC {cand} is"
                        break
            if cls:
                break

    # ---- C4 a date's year read as a section ----
    if cls is None and re.fullmatch(r"(1[789]|20)\d\d", s):
        if re.search(rf"(?:{MONTHS})[a-z]*\.?\s+\d{{1,2}},?\s*{s}\b|\b\d{{1,2}}/\d{{1,2}}/{s}\b", joined):
            cls, fix, why = "C4 date-year-as-section", "no citation", "the token is a calendar year"

    # ---- C5/C6 appendix ----
    if cls is None and app:
        cls = ("C5 appendix-out-of-oracle" if t not in APPENDIX_TITLES_COVERED
               else "C6 appendix-miss")

    # ---- C7 a chapter number read as a section number ----
    if cls is None and (t, s) in CHAPTER and re.fullmatch(r"\d+[a-z]?", s):
        cls, fix = "C7 chapter-as-section", f"{t} USC ch. {s}"
        why = f"{t} USC has no section {s}; it has a chapter {s}"

    # ---- C8 the hyphenated part of a compound section name was dropped ----
    if cls is None and HYPHEN_KIDS.get((t, s)):
        kids = sorted(HYPHEN_KIDS[(t, s)], key=lambda x: key(x.split("-", 1)[1]) or (0, ""))
        cls, fix = "C8 hyphen-part-dropped", f"{t} USC {kids[0]} et seq."
        why = f"{t} USC {s} is not a section; {len(kids)} sections are named {s}-N"

    # ---- C8b the letter o typed as a zero: 78o-10 written 780-10 ----
    if cls is None and "0" in s:
        for cand in {s[:i] + "o" + s[i+1:] for i, ch in enumerate(s) if ch == "0" and i > 0}:
            if sec_exact(t, cand):
                cls, fix = "C8b letter-o-as-zero", f"{t} USC {cand}"
                why = "the section name's letter o was typed as a zero"
                break

    # ---- C8c an inverted range kept whole by the fail-closed rule ----
    if cls is None:
        m = re.fullmatch(r"(\d+)-(\d+)", s)
        if m and int(m.group(2)) < int(m.group(1)) and sec_exact(t, m.group(1)):
            cls, fix = "C8c inverted-range-kept-whole", f"{t} USC {m.group(1)} (range end unread)"
            why = "second endpoint sorts before the first, so the ordering rule kept the pair as one name"

    # ---- C9 pre-1996 title 49 (no 49 App. in any published archive) ----
    if cls is None and t == 49 and (
            (s.isdigit() and (int(s) < 2000 or 10000 <= int(s) <= 11999))
            or re.match(r"^\d{1,4}[a-z]", s)):
        cls = "C9 title-49-pre-1996"

    # ---- C10/C11/C12 near-miss ----
    if cls is None:
        cands = near(t, s)
        my = rins_of[(t, s, app)]
        corr = sorted(((ct, cs, sorted(k), sum(1 for r in my if (r, ct, cs) in rin_states))
                       for (ct, cs), k in cands.items()), key=lambda x: -x[3])
        corr = [c for c in corr if c[3] > 0]
        if len(cands) == 1:
            (ct, cs), k = next(iter(cands.items()))
            cls, fix, why = "C10 unique-near-miss", f"{ct} USC {cs}", sorted(k)
        elif corr:
            cls, fix = "C11 corroborated-near-miss", f"{corr[0][0]} USC {corr[0][1]}"
            why = {"kinds": corr[0][2], "same_rin_hits": corr[0][3], "n_candidates": len(cands),
                   "runners_up": [[c[0], c[1], c[3]] for c in corr[1:4]]}
        else:
            cls, why = "C12 unresolved", {"n_candidates": len(cands)}
    records.append({"title": t, "section": s, "appendix": app, "rows": nrows, "texts": ntexts,
                    "rins": nrins, "first_pub": fp, "last_pub": lp, "all_note": all_note,
                    "any_ok": any_ok, "cls": cls, "fix": fix, "why": why, "specimens": tx[:4]})

json.dump(records, open("/tmp/silent/usc_triage.json", "w"))
agg = collections.defaultdict(lambda: [0, 0, 0])
for r in records:
    a = agg[r["cls"]]
    a[0] += 1
    a[1] += r["rows"]
    a[2] += r["texts"]
print(f"{'class':30s} {'pairs':>6s} {'texts':>7s} {'rows':>8s}")
for k in sorted(agg):
    print(f"{k:30s} {agg[k][0]:6d} {agg[k][2]:7d} {agg[k][1]:8d}")
print(f"{'TOTAL':30s} {len(records):6d} {sum(r['texts'] for r in records):7d} {sum(r['rows'] for r in records):8d}")

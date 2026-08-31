"""H1, take 3: full-column identity, run propagation, and two tiers.

Tier A (productive join): a run whose head names a scheme absorbs following
fragment boxes that read as nothing today -- or a leading fragment box absorbed
by the scheme-naming box after it.
Tier B (list continuation): consecutive boxes that ALL read as nothing today
and that continue one comma list. Joining restores the filer's one list; no new
citation is produced, only the row count and authority_text move.

Read-only.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import base_rows_by_box, load_base, load_boxes  # noqa: E402

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402
from refspec.registry.unified_agenda_parquet import _BARE_SECTION_BOX, _unstated_kind  # noqa: E402

_DANGLING_TAIL = re.compile(
    r"(?:^|[\s,;(])(?:"
    r"sec|secs|sect|sects|section|sections|§|§§|"
    r"pub|pub\.\s?l|p\.\s?l|pl|public\s+law|"
    r"u\.?\s?s\.?\s?c|usc|stat|c\.?\s?f\.?\s?r|cfr|"
    r"and|or|to|through|thru|no|nos"
    r")\.?$",
    re.IGNORECASE,
)
_LEADING_CONNECTIVE = re.compile(r"^(?:and|or|to|through|thru|et\s+seq)\b", re.IGNORECASE)
_ANY_SCHEME = re.compile(
    r"\b(?:u\.?\s?s\.?\s?c|usc|c\.?\s?f\.?\s?r|cfr|stat|pub\.?\s?l|p\.?\s?l\b|pl\b|public\s+law"
    r"|e\.?\s?o\.?|exec(?:utive)?\s+order|f\.?\s?r\b|fed\.?\s*reg|reorg|proc\.?|proclamation"
    r"|treat|const|d\.?\s?c\.?\s?code|r\.?\s?s\.?)\b",
    re.IGNORECASE,
)
#: A box that is nothing but a comma list of section-shaped tokens.
_SECTION_LIST_BOX = re.compile(
    r"^(?:and|or|,)?\s*(?:sec(?:tion)?s?\.?|§{1,2})?\s*"
    r"\d{1,5}[a-z]?(?:\.\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*"
    r"(?:\s*[,;]\s*(?:and\s+)?\d{1,5}[a-z]?(?:\.\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*)*"
    r"\s*[.,;]?\s*$",
    re.IGNORECASE,
)


def right_fragment(text: str) -> tuple[str, ...]:
    out: list[str] = []
    s = text.lstrip()
    if s[:1] in {")", ",", ";"}:
        out.append("R1-opens-with-close-or-comma")
    if _LEADING_CONNECTIVE.match(s):
        out.append("R3-opens-with-connective")
    has_scheme = bool(_ANY_SCHEME.search(s))
    if s[:1].islower() and not has_scheme and not _LEADING_CONNECTIVE.match(s):
        out.append("R2-opens-lowercase-no-scheme")
    if _BARE_SECTION_BOX.fullmatch(s):
        out.append("R4-whole-box-is-a-bare-section")
    if s[:1].isdigit() and not has_scheme and "R4-whole-box-is-a-bare-section" not in out:
        out.append("R5-opens-with-digit-no-scheme")
    return tuple(out)


def left_fragment(text: str) -> tuple[str, ...]:
    out: list[str] = []
    s = text.rstrip()
    if _DANGLING_TAIL.search(s):
        out.append("L1-dangling-label-or-connective")
    if s.endswith((",", ";", "-", "–", "—", "/", "&", "+")):
        out.append("L2-open-punctuation")
    if s.count("(") > s.count(")"):
        out.append("L3-unbalanced-paren")
    if _BARE_SECTION_BOX.fullmatch(s.lstrip()) and not _ANY_SCHEME.search(s):
        out.append("L4-whole-box-is-a-bare-section")
    return tuple(out)


def ident(citation) -> tuple:
    d = asdict(citation)
    return tuple(sorted((k, v) for k, v in d.items()
                        if v is not None and v is not False and k != "parse_status"))


#: Columns the grammar never writes -- filled by a later builder pass.
POST = {"act_resolution_evidence", "act_resolution_reason", "act_resolution_sibling_ordinal",
        "usc_section_verdict", "usc_section_verdict_reason", "usc_section_attested_at_edition",
        "usc_section_corrected", "usc_section_correction_evidence",
        "usc_section_corrected_section", "usc_section_corrected_pinpoint",
        "usc_section_magnitude_is_plausible",
        "public_law_corrected", "pl_correction_evidence", "corroboration_rule",
        "usc_title_is_possible", "eo_in_known_series", "pl_congress_in_series",
        "stat_volume_in_series", "fr_volume_in_series", "fr_page_in_series",
        "unstated_kind", "cfr_authority_note_agrees", "cfr_authority_note_evidence"}
KEYS = {"rin", "publication_id", "ordinal", "citation_ordinal", "authority_text", "parse_status"}


def base_ident(row: dict) -> tuple:
    m = dict(row)
    if m.get("act_resolution_evidence") is not None:
        m["usc_title"] = m["usc_section"] = None
    if m.get("act_resolution_sibling_ordinal") is not None:
        m["act_key"] = None
    if m.get("corroboration_rule") is not None:
        # A corroborated row's values came from a roster, not the grammar.
        return ("CORROBORATED", m.get("corroboration_rule"))
    return tuple(sorted((k, v) for k, v in m.items()
                        if v is not None and v is not False and k not in POST and k not in KEYS))


def silent(rows: list[dict]) -> bool:
    return bool(rows) and all(
        r["authority_type"] == "other" and r["parse_status"] == "failed" for r in rows
    )


def main() -> None:
    boxes = load_boxes()
    table = load_base(None)
    by_box = base_rows_by_box(table)

    stats = collections.Counter()
    by_signal = collections.Counter()
    run_lengths_a = collections.Counter()
    run_lengths_b = collections.Counter()
    outcomes = collections.Counter()
    lost_by_type = collections.Counter()
    lost_columns = collections.Counter()
    runs_a: list[dict] = []
    runs_b: list[dict] = []

    for (rin, pub), bs in boxes.items():
        if len(bs) < 2:
            continue
        rows_of = [by_box.get((rin, pub, i), []) for i in range(len(bs))]
        sil = [silent(r) for r in rows_of]
        placeholder = [bool(_unstated_kind(t)) for t in bs]

        # ---- Tier A: a run anchored on exactly one scheme-naming box -------
        used = [False] * len(bs)
        i = 0
        while i < len(bs):
            if placeholder[i] or sil[i] or used[i]:
                i += 1
                continue
            if not _ANY_SCHEME.search(bs[i]):
                i += 1
                continue
            # absorb following fragment boxes
            j = i
            sigs: set[str] = set()
            while j + 1 < len(bs) and sil[j + 1] and not placeholder[j + 1] and not used[j + 1]:
                f = right_fragment(bs[j + 1])
                if not f:
                    break
                sigs.update(f)
                j += 1
            # absorb a preceding fragment box
            k = i
            if i - 1 >= 0 and sil[i - 1] and not placeholder[i - 1] and not used[i - 1]:
                f = left_fragment(bs[i - 1])
                if f:
                    sigs.update(f)
                    k = i - 1
            if j == i and k == i:
                i += 1
                continue
            for x in range(k, j + 1):
                used[x] = True
            for s in sigs:
                by_signal[s] += 1
            stats["tierA_runs"] += 1
            run_lengths_a[j - k + 1] += 1
            joined = ", ".join(bs[k:j + 1])
            new = [ident(c) for c in parse_authority_citation(joined)]
            old: list[tuple] = []
            for x in range(k, j + 1):
                old.extend(base_ident(r) for r in rows_of[x])
                stats["tierA_boxes"] += 1
                stats["tierA_silent_boxes" if sil[x] else "tierA_valued_boxes"] += 1
                stats["tierA_rows"] += len(rows_of[x])
                if not sil[x]:
                    stats["tierA_rows_on_valued_boxes"] += len(rows_of[x])
            lost = [x for x in old
                    if x and dict(x).get("authority_type") not in (None, "other") and x not in new]
            gained = [x for x in new if x not in old]
            kind = "LOSS" if lost else ("GAIN" if gained else "NEUTRAL")
            outcomes["A:" + kind] += 1
            for x in lost:
                dx = dict(x)
                lost_by_type[dx.get("authority_type")] += 1
                # what exactly the joined read failed to reproduce
                near = [y for y in new
                        if dict(y).get("authority_type") == dx.get("authority_type")]
                for y in near:
                    dy = dict(y)
                    for col in set(dx) | set(dy):
                        if dx.get(col) != dy.get(col):
                            lost_columns[col] += 1
                    break
            runs_a.append({"rin": rin, "pub": pub, "first_ordinal": k, "boxes": bs[k:j + 1],
                           "silent": sil[k:j + 1], "signals": sorted(sigs),
                           "old": [dict(x) if x and x[0] != "CORROBORATED" else {"corroborated": x[1]}
                                   for x in old],
                           "new": [dict(x) for x in new], "kind": kind})
            i = j + 1

        # ---- Tier B: a run of boxes that all read as nothing and continue --
        i = 0
        while i < len(bs):
            if not (sil[i] and not placeholder[i] and not used[i] and _SECTION_LIST_BOX.fullmatch(bs[i].strip())):
                i += 1
                continue
            j = i
            while (j + 1 < len(bs) and sil[j + 1] and not placeholder[j + 1] and not used[j + 1]
                   and _SECTION_LIST_BOX.fullmatch(bs[j + 1].strip())):
                j += 1
            if j > i:
                stats["tierB_runs"] += 1
                run_lengths_b[j - i + 1] += 1
                stats["tierB_boxes"] += j - i + 1
                stats["tierB_rows"] += sum(len(rows_of[x]) for x in range(i, j + 1))
                joined = ", ".join(bs[i:j + 1])
                new = [ident(c) for c in parse_authority_citation(joined)]
                runs_b.append({"rin": rin, "pub": pub, "first_ordinal": i, "boxes": bs[i:j + 1],
                               "new": [dict(x) for x in new]})
                for x in range(i, j + 1):
                    used[x] = True
            i = j + 1

    print("=== Tier A: productive join (scheme-naming head + fragment boxes) ===")
    print(f"runs:               {stats['tierA_runs']:,}   lengths {dict(sorted(run_lengths_a.items()))}")
    print(f"boxes joined:       {stats['tierA_boxes']:,}"
          f"  (silent {stats['tierA_silent_boxes']:,} + valued {stats['tierA_valued_boxes']:,})")
    print(f"baseline rows in a run: {stats['tierA_rows']:,}"
          f"  (on a valued box: {stats['tierA_rows_on_valued_boxes']:,})")
    print("signals:")
    for s, c in by_signal.most_common():
        print(f"  {s:<36} {c:>7,}")
    print("outcomes:", {k: v for k, v in outcomes.most_common()})
    print("baseline readings that DISAPPEAR, by authority_type:", dict(lost_by_type))
    print("columns that differ on the nearest surviving reading:")
    for c, n in lost_columns.most_common(15):
        print(f"  {c:<32} {n:>6,}")
    print()
    print("=== Tier B: list continuation (all boxes silent, all section lists) ===")
    print(f"runs:  {stats['tierB_runs']:,}   lengths {dict(sorted(run_lengths_b.items()))}")
    print(f"boxes: {stats['tierB_boxes']:,}   baseline rows: {stats['tierB_rows']:,}")
    b_reads = collections.Counter(len(r["new"]) for r in runs_b)
    print("joined read yields N citations:", dict(sorted(b_reads.items())))

    out = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch")
    (out / "h1_runs_a.json").write_text(json.dumps(runs_a, ensure_ascii=False), encoding="utf-8")
    (out / "h1_runs_b.json").write_text(json.dumps(runs_b, ensure_ascii=False), encoding="utf-8")


main()

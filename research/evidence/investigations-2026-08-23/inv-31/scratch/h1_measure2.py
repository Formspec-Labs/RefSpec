"""H1, take 2: a NEED-gated join. A boundary is joined only where exactly one
side reads as nothing today AND that side is shaped like a fragment AND the
other side names a scheme. Read-only."""
from __future__ import annotations

import collections
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import VALUE_COLUMNS, base_rows_by_box, load_base, load_boxes  # noqa: E402

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402
from refspec.registry.unified_agenda_parquet import _BARE_SECTION_BOX, _unstated_kind  # noqa: E402

#: STRICT: a scheme label or list connective with its operand missing. "note",
#: "of", "the" are dropped -- "7 USC 1932 note" is a finished citation.
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


POST = {"act_resolution_evidence", "act_resolution_reason", "act_resolution_sibling_ordinal",
        "usc_section_verdict", "usc_section_verdict_reason", "usc_section_attested_at_edition",
        "usc_section_corrected", "usc_section_correction_evidence",
        "public_law_corrected", "pl_correction_evidence", "corroboration_rule"}
KEYS = {"rin", "publication_id", "ordinal", "citation_ordinal", "authority_text", "parse_status"}


def base_ident(row: dict) -> tuple:
    m = dict(row)
    if m.get("act_resolution_evidence") is not None:
        m["usc_title"] = m["usc_section"] = None
    if m.get("act_resolution_sibling_ordinal") is not None:
        m["act_key"] = None
    return tuple(sorted((k, v) for k, v in m.items()
                        if v is not None and v is not False and k not in POST and k not in KEYS))


def silent(rows: list[dict]) -> bool:
    return bool(rows) and all(
        r["authority_type"] == "other" and r["parse_status"] == "failed" for r in rows
    )


def main() -> None:
    boxes = load_boxes()
    by_box = base_rows_by_box(load_base(VALUE_COLUMNS))

    fired = 0
    by_direction = collections.Counter()
    by_signal = collections.Counter()
    runs = 0
    run_lengths = collections.Counter()
    outcomes = collections.Counter()
    silent_boxes_joined = 0
    valued_boxes_joined = 0
    baseline_rows_touched = 0
    baseline_rows_touched_valued = 0
    changed_existing = collections.Counter()
    examples = collections.defaultdict(list)
    per_run: list[dict] = []

    for (rin, pub), bs in boxes.items():
        if len(bs) < 2:
            continue
        fire = [False] * (len(bs) - 1)
        why = [()] * (len(bs) - 1)
        for i in range(len(bs) - 1):
            a, b = bs[i], bs[i + 1]
            if _unstated_kind(a) or _unstated_kind(b):
                continue
            ra = by_box.get((rin, pub, i), [])
            rb = by_box.get((rin, pub, i + 1), [])
            sa, sb = silent(ra), silent(rb)
            if sa == sb:            # both silent or neither: no donor / no need
                continue
            if sb:                  # the RIGHT box is the fragment
                sig = right_fragment(b)
                if sig and _ANY_SCHEME.search(a):
                    fire[i] = True
                    why[i] = ("right",) + sig
            else:                   # the LEFT box is the fragment
                sig = left_fragment(a)
                if sig and _ANY_SCHEME.search(b):
                    fire[i] = True
                    why[i] = ("left",) + sig
            if fire[i]:
                fired += 1
                by_direction[why[i][0]] += 1
                for s in why[i][1:]:
                    by_signal[s] += 1

        start = 0
        while start < len(bs):
            end = start
            while end < len(bs) - 1 and fire[end]:
                end += 1
            if end > start:
                runs += 1
                run_lengths[end - start + 1] += 1
                joined = ", ".join(bs[start:end + 1])
                new = [ident(c) for c in parse_authority_citation(joined)]
                old: list[tuple] = []
                sig_here: set[str] = set()
                for i in range(start, end + 1):
                    rows = by_box.get((rin, pub, i), [])
                    baseline_rows_touched += len(rows)
                    if silent(rows):
                        silent_boxes_joined += 1
                    else:
                        valued_boxes_joined += 1
                        baseline_rows_touched_valued += len(rows)
                    old.extend(base_ident(r) for r in rows)
                for i in range(start, end):
                    sig_here.update(why[i])
                lost = [x for x in old
                        if dict(x).get("authority_type") not in (None, "other") and x not in new]
                gained = [x for x in new if x not in old]
                kind = ("LOSS" if lost else ("GAIN" if gained else "NEUTRAL"))
                outcomes[kind] += 1
                for x in lost:
                    changed_existing[dict(x).get("authority_type")] += 1
                rec = {"rin": rin, "pub": pub, "boxes": bs[start:end + 1],
                       "signals": sorted(sig_here),
                       "old": [dict(x) for x in old], "new": [dict(x) for x in new],
                       "kind": kind}
                per_run.append(rec)
                if len(examples[kind]) < 60:
                    examples[kind].append(rec)
            start = end + 1

    print(f"boundaries the NEED-gated rule fires on: {fired:,}")
    print("  by which side is the fragment:", dict(by_direction))
    print("  by signal:")
    for s, c in by_signal.most_common():
        print(f"    {s:<36} {c:>7,}")
    print(f"runs formed: {runs:,}   lengths: {dict(sorted(run_lengths.items()))}")
    print(f"boxes joined: silent {silent_boxes_joined:,} + valued {valued_boxes_joined:,}"
          f" = {silent_boxes_joined+valued_boxes_joined:,}")
    print(f"baseline rows inside a run: {baseline_rows_touched:,}"
          f"  (of which on a valued box: {baseline_rows_touched_valued:,})")
    print("run outcomes:", dict(outcomes))
    print("baseline readings that DISAPPEAR, by authority_type:", dict(changed_existing))

    Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/h1_runs.json").write_text(
        json.dumps(per_run, ensure_ascii=False), encoding="utf-8")
    Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/h1_examples2.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=1), encoding="utf-8")


main()

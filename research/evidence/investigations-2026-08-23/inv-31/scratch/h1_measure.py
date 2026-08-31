"""H1: how many box boundaries look like a cut citation, and what a join moves.

Read-only. Reproduces the builder's per-box grammar read in a scratch process
and compares it with a run-joined read.
"""
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

# ---------------------------------------------------------------- detector --

#: A token that cannot be the last word of a finished citation: a scheme label
#: or a list connective with its operand missing.
_DANGLING_TAIL = re.compile(
    r"(?:^|[\s,;(])(?:"
    r"sec|secs|sect|sects|section|sections|s|ss|§|§§|"
    r"pub|pub\.\s?l|p\.?\s?l|pl|public\s+law|"
    r"u\.?\s?s\.?\s?c|usc|"
    r"stat|"
    r"c\.?\s?f\.?\s?r|cfr|"
    r"f\.?\s?r|fr|"
    r"and|or|to|through|thru|of|the|no|nos|note|et"
    r")\.?$",
    re.IGNORECASE,
)

#: Left-hand signals: this box does not finish what it started.
def left_signals(text: str) -> tuple[str, ...]:
    out: list[str] = []
    stripped = text.rstrip()
    if _DANGLING_TAIL.search(stripped):
        out.append("L1-dangling-label-or-connective")
    if stripped.endswith((",", ";", "-", "–", "—", "/", "&", "+")):
        out.append("L2-open-punctuation")
    if stripped.count("(") > stripped.count(")"):
        out.append("L3-unbalanced-paren")
    return tuple(out)


_LEADING_CONNECTIVE = re.compile(r"^(?:and|or|to|through|thru|et\s+seq|note)\b", re.IGNORECASE)
#: Any scheme label anywhere in the box -- if the box names its own scheme it
#: is not a fragment, whatever it starts with.
_ANY_SCHEME = re.compile(
    r"\b(?:u\.?\s?s\.?\s?c|usc|c\.?\s?f\.?\s?r|cfr|stat|pub\.?\s?l|p\.?\s?l\b|pl\b|public\s+law"
    r"|e\.?\s?o\.?|exec(?:utive)?\s+order|f\.?\s?r\b|fed\.?\s*reg|reorg|proc\.?|proclamation"
    r"|treat|const|d\.?\s?c\.?\s?code|r\.?\s?s\.?)\b",
    re.IGNORECASE,
)


def right_signals(text: str) -> tuple[str, ...]:
    out: list[str] = []
    stripped = text.lstrip()
    if stripped[:1] in {")", ",", ";"}:
        out.append("R1-opens-with-close-or-comma")
    if _LEADING_CONNECTIVE.match(stripped):
        out.append("R3-opens-with-connective")
    has_scheme = bool(_ANY_SCHEME.search(stripped))
    if stripped[:1].islower() and not has_scheme and not _LEADING_CONNECTIVE.match(stripped):
        out.append("R2-opens-lowercase-no-scheme")
    if _BARE_SECTION_BOX.fullmatch(stripped):
        out.append("R4-whole-box-is-a-bare-section")
    if stripped[:1].isdigit() and not has_scheme and "R4-whole-box-is-a-bare-section" not in out:
        out.append("R5-opens-with-digit-no-scheme")
    return tuple(out)


def grammar_identity(citation) -> tuple:
    d = asdict(citation)
    return tuple(sorted((k, v) for k, v in d.items() if v is not None and v is not False
                        and k not in {"parse_status"}))


def base_identity(row: dict) -> tuple:
    #: The baseline row's grammar-level content, with the post-pass fills
    #: masked: the act resolver writes usc_title/usc_section on act-relative
    #: rows, and the sibling carry writes act_key. Comparing those against a
    #: grammar-only read would report a difference the join never made.
    masked = dict(row)
    if masked.get("act_resolution_evidence") is not None:
        masked["usc_title"] = None
        masked["usc_section"] = None
    if masked.get("act_resolution_sibling_ordinal") is not None:
        masked["act_key"] = None
    drop = {"rin", "publication_id", "ordinal", "citation_ordinal", "authority_text",
            "parse_status", "act_resolution_evidence", "act_resolution_reason",
            "act_resolution_sibling_ordinal", "usc_section_verdict",
            "usc_section_verdict_reason", "usc_section_attested_at_edition",
            "usc_section_corrected", "usc_section_correction_evidence",
            "public_law_corrected", "pl_correction_evidence", "corroboration_rule"}
    return tuple(sorted((k, v) for k, v in masked.items()
                        if v is not None and v is not False and k not in drop))


def main() -> None:
    boxes = load_boxes()
    table = load_base(VALUE_COLUMNS)
    by_box = base_rows_by_box(table)

    boundaries = 0
    boundaries_multi = 0
    left_counter = collections.Counter()
    right_counter = collections.Counter()
    combo = collections.Counter()
    # Candidate rule: fire on a boundary where the RIGHT box is a fragment AND
    # today contributes nothing (all its rows are other/failed), or the LEFT
    # box is left open by a dangling label.
    fired_boundaries = 0
    runs = 0
    run_lengths = collections.Counter()
    rows_in_runs = 0
    rows_in_runs_with_value = 0
    boxes_in_runs = 0
    boxes_in_runs_with_value = 0

    outcomes = collections.Counter()
    examples: dict[str, list] = collections.defaultdict(list)

    for (rin, pub), bs in boxes.items():
        if len(bs) < 2:
            continue
        boundaries_multi += 1
        fire = [False] * (len(bs) - 1)
        for i in range(len(bs) - 1):
            boundaries += 1
            ls = left_signals(bs[i])
            rs = right_signals(bs[i + 1])
            for s in ls:
                left_counter[s] += 1
            for s in rs:
                right_counter[s] += 1
            if ls or rs:
                combo[(bool(ls), bool(rs))] += 1
            right_rows = by_box.get((rin, pub, i + 1), [])
            right_is_empty = all(
                r["authority_type"] == "other" and r["parse_status"] == "failed" for r in right_rows
            ) and bool(right_rows)
            if (rs and right_is_empty) or ls:
                fire[i] = True
                fired_boundaries += 1

        # maximal runs
        start = 0
        while start < len(bs):
            end = start
            while end < len(bs) - 1 and fire[end]:
                end += 1
            if end > start:
                runs += 1
                run_lengths[end - start + 1] += 1
                joined = ", ".join(bs[start:end + 1])
                joined_reads = [grammar_identity(c) for c in parse_authority_citation(joined)]
                base_ids: list[tuple] = []
                for i in range(start, end + 1):
                    boxes_in_runs += 1
                    rows = by_box.get((rin, pub, i), [])
                    rows_in_runs += len(rows)
                    ids = [base_identity(r) for r in rows]
                    has_value = any(
                        i2 and dict(i2).get("authority_type") not in (None, "other")
                        for i2 in ids
                    )
                    if has_value:
                        boxes_in_runs_with_value += 1
                        rows_in_runs_with_value += sum(
                            1 for r in rows if r["authority_type"] != "other"
                        )
                    base_ids.extend(ids)
                lost = [i2 for i2 in base_ids
                        if dict(i2).get("authority_type") not in (None, "other")
                        and i2 not in joined_reads]
                gained = [i2 for i2 in joined_reads if i2 not in base_ids]
                if lost:
                    outcomes["LOSS: a baseline reading disappears"] += 1
                    if len(examples["loss"]) < 40:
                        examples["loss"].append((rin, pub, bs[start:end + 1], base_ids, joined_reads))
                elif gained:
                    outcomes["GAIN: only new readings"] += 1
                    if len(examples["gain"]) < 40:
                        examples["gain"].append((rin, pub, bs[start:end + 1], base_ids, joined_reads))
                else:
                    outcomes["NEUTRAL: same readings"] += 1
                    if len(examples["neutral"]) < 20:
                        examples["neutral"].append((rin, pub, bs[start:end + 1], base_ids, joined_reads))
            start = end + 1

    print(f"records with >1 box:            {boundaries_multi:,}")
    print(f"adjacent box boundaries:        {boundaries:,}")
    print()
    print("LEFT signals (box i does not finish):")
    for s, c in left_counter.most_common():
        print(f"  {s:<36} {c:>8,}  ({c/boundaries:.2%} of boundaries)")
    print("RIGHT signals (box i+1 starts mid-citation):")
    for s, c in right_counter.most_common():
        print(f"  {s:<36} {c:>8,}  ({c/boundaries:.2%} of boundaries)")
    print()
    print("boundaries where any signal fires, by side:")
    for (l, r), c in combo.most_common():
        print(f"  left={l!s:<5} right={r!s:<5} {c:>8,}")
    print()
    print(f"candidate rule fires on:        {fired_boundaries:,} boundaries")
    print(f"runs formed (>=2 boxes):        {runs:,}")
    print("run length histogram:", dict(sorted(run_lengths.items())))
    print(f"boxes inside a run:             {boxes_in_runs:,}")
    print(f"  of which carry a value today: {boxes_in_runs_with_value:,}")
    print(f"baseline rows inside a run:     {rows_in_runs:,}")
    print(f"  of which are not other/failed:{rows_in_runs_with_value:,}")
    print()
    print("run outcomes:")
    for k, c in outcomes.most_common():
        print(f"  {k:<38} {c:>8,}")

    Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-31/scratch/h1_examples.json").write_text(
        json.dumps({k: [[a, b, c, [list(map(list, x)) for x in d], [list(map(list, x)) for x in e]]
                        for a, b, c, d, e in v] for k, v in examples.items()},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


main()

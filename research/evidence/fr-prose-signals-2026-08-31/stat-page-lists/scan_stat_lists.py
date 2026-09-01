#!/usr/bin/env python3
"""Census the ``NNN Stat. NNNN[, NNNN...]`` page-list family in authority notes.

Run from the repo root: ``.venv/bin/python
research/evidence/fr-prose-signals-2026-08-31/stat-page-lists/scan_stat_lists.py``.
Prints every number the README cites and writes ``receipt.json`` alongside
this script. The receipt records the sha256 and byte size of every input.

Corpus: ``research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl``,
8,240 ``authority_note`` strings, one per CFR part/subdivision, fetched
directly from the eCFR versioner API's full title XML (see that directory's
own README for provenance). This is the SAME corpus the known parser bug
lives in (silent item 4 of research/investigations-mined-2026-08-31.md: the
production note reader emits 148 fabricated U.S.C. citations across 80 of
these 8,240 notes by reading a Stat. page list as a U.S.C. section list).
This script does not touch or fix that reader. It measures the underlying
prose shape on its own terms, with a purpose-built regex that is deliberately
NOT the production reader's logic -- a second, independent read.

WHAT CHANGED (2026-08-31, after review)
---------------------------------------
1. THE REGEX NOW ACCEPTS ``Stat`` WITHOUT A PERIOD. The corpus prints the
   volume marker both ways ("102 Stat 989, 993" in 12 CFR 615 and 12 CFR
   628). The previous ``Stat\\.`` pattern silently dropped every no-period
   occurrence, including the very specimen the README quoted as proof the
   regex caught them.
2. THE MARKER METRIC IS NAMED FOR WHAT IT MEASURES. The previous version
   reported a "suspect false continuation" count as though it were a rate.
   It is not: it is the fraction of matches whose FOLLOWING text opens with
   another citation-type keyword. That test is a lower bound by construction
   -- the known 14 CFR 121 false continuation has no such marker and was
   recorded ``suspect=false`` by the old script's own receipt. The field is
   now ``two_token_marker_adjacent`` and its fraction is
   ``two_token_marker_hit_fraction``.
3. THE ACTUAL RATE IS MEASURED, NOT SUBTRACTED. The two-token population is
   split into two strata. The marker-adjacent stratum was read exhaustively
   (all of it is emitted into the receipt). The unmarked stratum is sampled
   with a documented seed and hand-classified specimen by specimen in
   ``manual_verdicts.json``; the script joins that file to the sample it
   redraws and REFUSES to report a rate if any drawn key lacks a verdict.
   The overall two-token rate is a stratified estimate whose arithmetic is
   printed in full.
4. THE PAGE-PAIR SEMANTICS ARE CORRECTED. ``101 Stat. 1568, 1608`` is not a
   start/end SPAN. 1568 is Public Law 100-233's OPENING page and 1608 is the
   sec. 301(a) pinpoint. The corpus proves it without leaving the corpus:
   five notes cite ``101 Stat. 1568`` with three different second pages
   (1608, 1638, 1656), one per cited section. A span reading would give one
   Act three different end pages from one start page. The field is now
   ``two_token_page_pair`` and the receipt carries the shared-opening-page
   evidence.
5. THE PROPOSED GATES ARE SIMULATED, NOT ASSERTED. Both fixes the README
   proposes are run over the corpus so the README can state what they catch
   and -- importantly -- what they do not.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = Path(__file__).resolve().parent
NOTES_PATH = (
    REPO_ROOT / "research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl"
)
VERDICTS_PATH = OUT_DIR / "manual_verdicts.json"

# NNN Stat[.] NNNN[-NNNN][, NNNN[-NNNN]]*  -- volume, then a comma-joined run
# of page tokens, each a bare page or a hyphenated range. The period after
# "Stat" is OPTIONAL: the corpus prints it both ways.
STAT_LIST = re.compile(
    r"(?P<volume>\d{1,3})\s+Stat\.?\s+"
    r"(?P<pages>\d{1,5}(?:-\d{1,5})?(?:,\s*\d{1,5}(?:-\d{1,5})?)*)"
)

# A match is MARKER-ADJACENT when the text immediately following it opens with
# another citation-type keyword. This is evidence that the last comma-joined
# token is that citation's leading number rather than a further Stat. page.
# It is a lower bound on false continuation, never the rate itself.
FOLLOWED_BY_OTHER_CITATION = re.compile(r"^\s*(CFR|U\.S\.C\.|USC|Comp\.)")

# The captured span ending immediately against an alphanumeric means the
# PRINTED token was longer than what the regex kept (the appendix-page form
# "2763A-638" truncates to "2763").
TOKEN_TRUNCATED = re.compile(r"^[A-Za-z0-9]")

SAMPLE_SEED = 20260831
SAMPLE_N = 60


def digest(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path.relative_to(REPO_ROOT)), "present": False}
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "present": True,
        "bytes": path.stat().st_size,
        "sha256": h.hexdigest(),
    }


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval -- honest at these sample sizes, unlike normal-approx."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_notes():
    with NOTES_PATH.open() as fh:
        for line in fh:
            yield json.loads(line)


def main() -> None:
    inputs = {
        "ecfr_authority_notes_jsonl": digest(NOTES_PATH),
        "manual_verdicts_json": digest(VERDICTS_PATH),
    }

    notes = list(load_notes())
    total_notes = len(notes)

    all_matches = []
    for d in notes:
        note = d.get("authority_note") or ""
        for m in STAT_LIST.finditer(note):
            tokens = [t.strip() for t in m.group("pages").split(",")]
            after = note[m.end() : m.end() + 30]
            all_matches.append(
                {
                    "key": f"{d['cfr_title']}|{d['cfr_part']}|{m.start()}",
                    "cfr_title": d["cfr_title"],
                    "cfr_part": d["cfr_part"],
                    "match": m.group(0),
                    "volume": m.group("volume"),
                    "tokens": tokens,
                    "n_tokens": len(tokens),
                    "text_after": after.strip(),
                    "marker_adjacent": bool(FOLLOWED_BY_OTHER_CITATION.match(after)),
                    "captured_token_truncated": bool(TOKEN_TRUNCATED.match(after)),
                    "printed_marker_has_period": bool(
                        re.search(r"Stat\.", m.group(0))
                    ),
                }
            )

    notes_with_stat_period = sum(
        1 for d in notes if "Stat." in (d.get("authority_note") or "")
    )
    notes_with_stat_either = sum(
        1
        for d in notes
        if re.search(r"\bStat\.?\s+\d", d.get("authority_note") or "")
    )
    n_matches = len(all_matches)
    n_no_period = sum(1 for m in all_matches if not m["printed_marker_has_period"])

    by_len: dict[int, list] = {}
    for m in all_matches:
        by_len.setdefault(m["n_tokens"], []).append(m)

    n_singleton = len(by_len.get(1, []))
    two_tok = by_len.get(2, [])
    n_two = len(two_tok)
    two_marker = [m for m in two_tok if m["marker_adjacent"]]
    two_unmarked = [m for m in two_tok if not m["marker_adjacent"]]

    multi = [m for n, ms in by_len.items() if n >= 3 for m in ms]
    n_multi = len(multi)
    multi_marker = [m for m in multi if m["marker_adjacent"]]

    distinct_notes_with_list_of_2plus = len(
        {(m["cfr_title"], m["cfr_part"]) for m in all_matches if m["n_tokens"] >= 2}
    )

    # ---- Stratum 1: marker-adjacent, reviewed exhaustively ----------------
    # Every one of these is emitted into the receipt. They were read in one
    # pass on 2026-08-31; each has the form "NNN Stat. PPPP, TT" where TT is
    # the title number of the U.S.C./CFR/Comp. citation that follows. Zero
    # exceptions were found; the list is in the receipt so the read is
    # re-checkable rather than asserted.
    marker_stratum_review = {
        "method": "exhaustive hand read of every marker-adjacent two-token match",
        "n_reviewed": len(two_marker),
        "exceptions_found": 0,
        "false_continuation_rate_in_stratum": 1.0 if two_marker else None,
    }

    # ---- Stratum 2: unmarked, sampled and hand-classified -----------------
    unmarked_sorted = sorted(two_unmarked, key=lambda m: m["key"])
    rng = random.Random(SAMPLE_SEED)
    draw_indices = sorted(
        rng.sample(range(len(unmarked_sorted)), min(SAMPLE_N, len(unmarked_sorted)))
    )
    sample = [unmarked_sorted[i] for i in draw_indices]

    verdicts_doc = json.loads(VERDICTS_PATH.read_text())
    verdicts = verdicts_doc["verdicts"]
    missing = [m["key"] for m in sample if m["key"] not in verdicts]

    sample_rows = []
    n_false = 0
    for m in sample:
        v = verdicts.get(m["key"])
        if v:
            if v["verdict"] == "false_continuation":
                n_false += 1
        sample_rows.append(
            {
                "key": m["key"],
                "cfr_title": m["cfr_title"],
                "cfr_part": m["cfr_part"],
                "match": m["match"],
                "text_after": m["text_after"],
                "verdict": v["verdict"] if v else None,
                "reason": v.get("reason") if v else None,
                "token_damage": v.get("token_damage") if v else None,
            }
        )

    if missing:
        unmarked_rate = None
        unmarked_ci = None
        overall_rate = None
        overall_ci = None
    else:
        n_s = len(sample)
        unmarked_rate = n_false / n_s
        unmarked_ci = wilson_interval(n_false, n_s)
        # Stratified estimate over the whole two-token population. Stratum
        # sizes are exact counts; stratum 1's rate is exhaustively observed;
        # only stratum 2's rate is estimated.
        overall_rate = (len(two_marker) * 1.0 + len(two_unmarked) * unmarked_rate) / n_two
        overall_ci = (
            (len(two_marker) + len(two_unmarked) * unmarked_ci[0]) / n_two,
            (len(two_marker) + len(two_unmarked) * unmarked_ci[1]) / n_two,
        )

    # ---- Page-pair semantics: opening page + pinpoint, not a span ---------
    # Group unmarked two-token matches by (volume, first token). If the second
    # token were the END of a span, one Act could not carry several.
    opening_page_groups = defaultdict(set)
    for m in two_unmarked:
        opening_page_groups[(m["volume"], m["tokens"][0])].add(m["tokens"][1])
    shared_opening = {
        f"{v} Stat. {p}": sorted(seconds)
        for (v, p), seconds in opening_page_groups.items()
        if len(seconds) > 1
    }

    stat_1568_witnesses = []
    for d in notes:
        note = d.get("authority_note") or ""
        for m in re.finditer(r"101\s+Stat\.?\s+1568[^;)]*", note):
            stat_1568_witnesses.append(
                {
                    "cfr_title": d["cfr_title"],
                    "cfr_part": d["cfr_part"],
                    "text": m.group(0),
                }
            )

    # ---- Damage classes ---------------------------------------------------
    truncated = [m for m in all_matches if m["captured_token_truncated"]]
    malformed_volume = []
    for d in notes:
        note = d.get("authority_note") or ""
        for m in re.finditer(r"\d{4,}\s+Stat\.?\s+\d", note):
            malformed_volume.append(
                {
                    "cfr_title": d["cfr_title"],
                    "cfr_part": d["cfr_part"],
                    "printed": m.group(0),
                    "context": note[max(0, m.start() - 90) : m.end() + 40],
                }
            )

    # ---- Gate simulation --------------------------------------------------
    # Gate 1: stop the list at the first following citation-type keyword.
    # Gate 2: a per-volume maximum-page table. No such table is held locally,
    # so it is simulated by the largest FIRST token seen for that volume
    # anywhere in this corpus. First tokens are used because later tokens are
    # exactly the ones under suspicion. The simulated ceiling is a LOWER bound
    # on the volume's real page count, which makes this gate STRICTER than a
    # real table -- so anything it fails to catch, a real table also misses.
    volume_ceiling: dict[str, int] = {}
    for m in all_matches:
        first_numbers = [int(x) for x in re.findall(r"\d+", m["tokens"][0])]
        if first_numbers:
            volume_ceiling[m["volume"]] = max(
                volume_ceiling.get(m["volume"], 0), max(first_numbers)
            )

    def gate_report(m: dict) -> dict:
        caught_1 = m["marker_adjacent"]
        ceiling = volume_ceiling.get(m["volume"], 0)
        over = [
            t
            for t in m["tokens"]
            if any(int(x) > ceiling for x in re.findall(r"\d+", t))
        ]
        return {
            "gate1_marker_stop_catches": caught_1,
            "gate2_volume_ceiling": ceiling,
            "gate2_tokens_over_ceiling": over,
            "gate2_catches": bool(over),
        }

    multi_token = [m for m in all_matches if m["n_tokens"] >= 2]
    gate1_catch = sum(1 for m in multi_token if m["marker_adjacent"])
    gate2_catch = sum(1 for m in multi_token if gate_report(m)["gate2_catches"])
    either_catch = sum(
        1
        for m in multi_token
        if m["marker_adjacent"] or gate_report(m)["gate2_catches"]
    )

    def find_match(title, part, needle):
        for m in all_matches:
            if (
                m["cfr_title"] == title
                and str(m["cfr_part"]) == str(part)
                and needle in m["match"]
            ):
                return m
        return None

    counterexample = find_match(12, "611", "101 Stat. 1568, 1638")
    resumption = find_match(14, "121", "126 Stat. 89")
    counterexample_gates = gate_report(counterexample) if counterexample else None
    resumption_gates = gate_report(resumption) if resumption else None

    # Named specimens for the README.
    def find_specimen(title, part):
        for d in notes:
            if d["cfr_title"] == title and str(d["cfr_part"]) == str(part):
                return d.get("authority_note")
        return None

    receipt = {
        "inputs": inputs,
        "regex": STAT_LIST.pattern,
        "marker_regex": FOLLOWED_BY_OTHER_CITATION.pattern,
        "total_notes": total_notes,
        "notes_containing_literal_Stat_period": notes_with_stat_period,
        "notes_containing_Stat_with_or_without_period": notes_with_stat_either,
        "total_stat_citation_matches": n_matches,
        "matches_whose_printed_marker_lacks_a_period": n_no_period,
        "distinct_notes_with_2plus_token_list": distinct_notes_with_list_of_2plus,
        "token_length_histogram": {str(k): len(v) for k, v in sorted(by_len.items())},
        "singleton_page_count": n_singleton,
        "two_token_total": n_two,
        "two_token_marker_adjacent": len(two_marker),
        "two_token_marker_hit_fraction": len(two_marker) / n_two if n_two else None,
        "two_token_unmarked_remainder": len(two_unmarked),
        "three_plus_token_total": n_multi,
        "three_plus_token_marker_adjacent": len(multi_marker),
        "marker_stratum_review": marker_stratum_review,
        "unmarked_stratum_sample": {
            "seed": SAMPLE_SEED,
            "requested_n": SAMPLE_N,
            "drawn_n": len(sample),
            "population_n": len(two_unmarked),
            "draw_rule": (
                "random.Random(seed).sample(range(len(population)), n) over the "
                "population sorted by key"
            ),
            "keys_missing_a_manual_verdict": missing,
            "false_continuation_count": n_false,
            "page_pair_count": len(sample) - n_false,
            "false_continuation_rate": unmarked_rate,
            "false_continuation_rate_wilson95": unmarked_ci,
            "specimens": sample_rows,
        },
        "two_token_false_continuation_rate_stratified": overall_rate,
        "two_token_false_continuation_rate_stratified_wilson95": overall_ci,
        "two_token_false_continuation_rate_derivation": (
            f"({len(two_marker)} marker-adjacent x 1.0 + {len(two_unmarked)} unmarked x "
            f"sampled rate) / {n_two} two-token matches"
        ),
        "two_token_false_continuations_gate1_cannot_see_estimate": (
            None
            if unmarked_rate is None
            else {
                "point": round(len(two_unmarked) * unmarked_rate, 1),
                "wilson95": [
                    round(len(two_unmarked) * unmarked_ci[0], 1),
                    round(len(two_unmarked) * unmarked_ci[1], 1),
                ],
                "derivation": (
                    f"{len(two_unmarked)} unmarked two-token matches x the sampled "
                    f"unmarked false-continuation rate"
                ),
            }
        ),
        "page_pair_semantics": {
            "reading": (
                "first token = the cited Act's OPENING page in the bound volume; "
                "second token = the cited section's PINPOINT page. NOT a start/end span."
            ),
            "corpus_evidence": (
                "distinct (volume, first-token) keys carrying more than one second "
                "token -- impossible under a span reading"
            ),
            "distinct_opening_page_keys_in_unmarked_two_token": len(
                opening_page_groups
            ),
            "keys_with_multiple_second_pages": len(shared_opening),
            "keys_with_multiple_second_pages_detail": shared_opening,
            "pub_l_100_233_witnesses": stat_1568_witnesses,
        },
        "damage_captured_token_truncated_count": len(truncated),
        "damage_captured_token_truncated": [
            {
                "cfr_title": m["cfr_title"],
                "cfr_part": m["cfr_part"],
                "captured": m["match"],
                "printed_continues": m["text_after"][:20],
            }
            for m in truncated
        ],
        "damage_malformed_volume_count": len(malformed_volume),
        "damage_malformed_volume": malformed_volume,
        "gate_simulation": {
            "gate1": "stop the page list at the first following citation-type keyword",
            "gate2": (
                "reject a token above the volume's page ceiling; the ceiling is "
                "simulated as the largest FIRST token seen for that volume in this "
                "corpus, a lower bound on the volume's true length, so this "
                "simulation is stricter than a real table"
            ),
            "multi_token_matches": len(multi_token),
            "gate1_catches": gate1_catch,
            "gate2_catches": gate2_catch,
            "either_gate_catches": either_catch,
            "neither_gate_catches": len(multi_token) - either_catch,
            "counterexample_12_cfr_611": {
                "match": counterexample["match"] if counterexample else None,
                "text_after": counterexample["text_after"] if counterexample else None,
                **(counterexample_gates or {}),
                "why_it_matters": (
                    "research/backlog-validation-2026-08-31.md:60 records that the "
                    "raw 12 CFR 611 note reads '101 Stat. 1568, 1638' and that "
                    "12 U.S.C. 1638 (Truth in Lending) EXISTS. Both proposed gates "
                    "pass this match, so neither gate -- nor a U.S.C.-section "
                    "existence oracle -- catches this fabrication."
                ),
            },
            "resumption_14_cfr_121": {
                "match": resumption["match"] if resumption else None,
                "text_after": resumption["text_after"] if resumption else None,
                **(resumption_gates or {}),
            },
        },
        "specimen_12_cfr_615": find_specimen(12, "615"),
        "specimen_12_cfr_611": find_specimen(12, "611"),
        "specimen_14_cfr_121_usc_resumption_trap": find_specimen(14, "121"),
        "specimen_5_cfr_151_false_continuation": find_specimen(5, "151"),
        "specimen_5_cfr_2100_false_continuation": find_specimen(5, "2100"),
        "marker_adjacent_two_token_matches": [
            {
                "cfr_title": m["cfr_title"],
                "cfr_part": m["cfr_part"],
                "match": m["match"],
                "text_after": m["text_after"],
            }
            for m in two_marker
        ],
        "all_matches": all_matches,
    }
    (OUT_DIR / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    print("=== STAT.-PAGE-LIST CENSUS ===")
    print("Inputs (sha256-bound in receipt.json):")
    for key, meta in inputs.items():
        print(f"  {key}: {meta['path']} ({meta['bytes']} bytes, {meta['sha256'][:16]}...)")
    print()
    print(f"Total authority notes in corpus: {total_notes}")
    print(f"Notes containing the literal string 'Stat.': {notes_with_stat_period}")
    print(f"Notes containing 'Stat' with OR without a period: {notes_with_stat_either}")
    print(f"Total 'NNN Stat[.] <page-list>' regex matches: {n_matches}")
    print(f"  of which the printed marker lacks a period: {n_no_period}")
    print(f"Distinct notes carrying a 2+-token list: {distinct_notes_with_list_of_2plus}")
    print()
    print("Token-length histogram (page tokens per Stat. citation):")
    for k in sorted(by_len):
        print(f"  {k:2d} token(s): {len(by_len[k])}")
    print()
    print(f"Singleton pages (1 token, no list to misread): {n_singleton}")
    print(f"Two-token matches: {n_two}")
    print(
        f"  marker-adjacent (next text opens with U.S.C./CFR/Comp.): "
        f"{len(two_marker)}  = {len(two_marker) / n_two:.1%} MARKER-HIT FRACTION"
    )
    print(f"  unmarked remainder: {len(two_unmarked)}")
    print(f"Three-plus-token matches: {n_multi} ({len(multi_marker)} marker-adjacent)")
    print()
    print("--- Measured false-continuation rate (not a marker-hit fraction) ---")
    print(
        f"Stratum 1 (marker-adjacent, n={len(two_marker)}): read exhaustively, "
        f"{marker_stratum_review['exceptions_found']} exceptions -> rate 100%"
    )
    if missing:
        print(f"Stratum 2: REFUSING to report a rate; {len(missing)} sampled keys "
              f"have no manual verdict: {missing}")
    else:
        print(
            f"Stratum 2 (unmarked, n={len(two_unmarked)}): random sample of "
            f"{len(sample)} (seed {SAMPLE_SEED}), each hand-read in full sentence "
            f"context -> {n_false} false continuations, {len(sample) - n_false} "
            f"genuine page pairs"
        )
        print(
            f"  sampled rate {unmarked_rate:.1%}  "
            f"(Wilson 95% CI {unmarked_ci[0]:.1%} - {unmarked_ci[1]:.1%})"
        )
        print(f"Stratified two-token rate: {receipt['two_token_false_continuation_rate_derivation']}")
        print(
            f"  = {overall_rate:.1%}  "
            f"(95% CI {overall_ci[0]:.1%} - {overall_ci[1]:.1%}, from stratum 2 only)"
        )
        resid = receipt["two_token_false_continuations_gate1_cannot_see_estimate"]
        print(
            f"False continuations gate 1 CANNOT see (unmarked stratum): "
            f"~{resid['point']} matches (95% CI {resid['wilson95'][0]}-{resid['wilson95'][1]})"
        )
    print()
    print("--- Page-pair semantics: opening page + pinpoint, NOT a span ---")
    print(
        f"(volume, first-token) keys in the unmarked two-token stratum: "
        f"{len(opening_page_groups)}"
    )
    print(f"  keys carrying MORE THAN ONE second page: {len(shared_opening)}")
    for k, v in sorted(shared_opening.items())[:10]:
        print(f"    {k} -> {v}")
    print("  Public Law 100-233 (101 Stat. 1568) as printed, every witness:")
    for w in stat_1568_witnesses:
        print(f"    {w['cfr_title']} CFR {w['cfr_part']}: {w['text']}")
    print()
    print(f"--- Damage: captured token truncated at a letter ({len(truncated)}) ---")
    for m in truncated[:8]:
        print(f"  {m['cfr_title']} CFR {m['cfr_part']}: captured {m['match']!r} but the "
              f"print continues {m['text_after'][:14]!r}")
    print(f"--- Damage: malformed printed volume ({len(malformed_volume)}) ---")
    for m in malformed_volume:
        print(f"  {m['cfr_title']} CFR {m['cfr_part']}: {m['printed']!r}")
        print(f"      context: ...{m['context']}...")
    print()
    print("--- Gate simulation over the 2+-token population ---")
    print(f"Multi-token matches: {len(multi_token)}")
    print(f"  gate 1 (marker stop) catches: {gate1_catch}")
    print(f"  gate 2 (volume ceiling) catches: {gate2_catch}")
    print(f"  either catches: {either_catch}   neither: {len(multi_token) - either_catch}")
    print("  COUNTEREXAMPLE 12 CFR 611:")
    print(f"    {counterexample['match']!r} followed by {counterexample['text_after']!r}")
    print(f"    gate1 catches: {counterexample_gates['gate1_marker_stop_catches']}")
    print(
        f"    gate2 ceiling for volume {counterexample['volume']}: "
        f"{counterexample_gates['gate2_volume_ceiling']}; tokens over it: "
        f"{counterexample_gates['gate2_tokens_over_ceiling']}; catches: "
        f"{counterexample_gates['gate2_catches']}"
    )
    print("    -> PASSES BOTH GATES, and 12 U.S.C. 1638 is a real section.")
    print("  14 CFR 121 resumption trap:")
    print(f"    {resumption['match']!r} followed by {resumption['text_after']!r}")
    print(f"    gate1 catches: {resumption_gates['gate1_marker_stop_catches']}")
    print(
        f"    gate2 ceiling for volume {resumption['volume']}: "
        f"{resumption_gates['gate2_volume_ceiling']}; tokens over it: "
        f"{resumption_gates['gate2_tokens_over_ceiling']}; catches: "
        f"{resumption_gates['gate2_catches']}"
    )
    print()
    print("--- Specimen: 12 CFR 615 (the '101 Stat. 1568, 1608' example) ---")
    print(receipt["specimen_12_cfr_615"])
    print()
    print("--- Specimen: 12 CFR 611 (the '101 Stat. 1568, 1638' counterexample) ---")
    print(receipt["specimen_12_cfr_611"])
    print()
    print("--- Specimen: 14 CFR 121 (bare U.S.C. list resuming after a Stat. page) ---")
    print(receipt["specimen_14_cfr_121_usc_resumption_trap"])
    print()
    print("--- Specimen: 5 CFR 151 ('92 Stat. 3783, 3' bleeds into '3 CFR') ---")
    print(receipt["specimen_5_cfr_151_false_continuation"])
    print()
    print("--- Specimen: 5 CFR 2100 ('88 Stat. 1896, 5' bleeds into '5 U.S.C.') ---")
    print(receipt["specimen_5_cfr_2100_false_continuation"])


if __name__ == "__main__":
    main()

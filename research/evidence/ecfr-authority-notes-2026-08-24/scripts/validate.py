#!/usr/bin/env python3
"""What generation 2 owes generation 1, and what it covers.

Four measurements, all reported as numbers and none of them assumed:

a. **Re-extraction against generation 1.** Every one of generation 1's 287
   parts is looked up in generation 2 and its note compared, first byte for
   byte and then again after ``html.unescape`` on both sides. A difference is
   classified rather than counted: ``entity`` (the two API views spell the same
   character differently -- the per-part responses generation 1 read escape a
   section sign and an em dash, the full-title documents write them as UTF-8),
   ``drift`` (the publisher's words changed between the two dates), or
   ``missing`` (generation 2 has no note for that part at all). Every
   non-identical pair is printed verbatim.
b. **The two notes known to misprint their own title digits** -- 36 CFR 251 and
   28 CFR 541, named in ``research/evidence/false-presences-2026-08-23.md`` --
   are quoted as they stand at the new date, so "still wrong" is a record
   rather than a memory.
c. **Coverage against the corpus.** The distinct ``(cfr_title, cfr_part)``
   pairs the Unified Agenda's CFR references name, joined against the extracted
   parts on the reader's own join key (leading zeros stripped, case folded).
   Every miss is given a reason.
d. **Totals per title**, from the extraction census.

    python3 validate.py EVIDENCE_DIR REPOSITORY_ROOT [--probe]

``--probe`` additionally asks the eCFR versioner, one polite request at a time,
whether a sample of missed parts ever existed -- the spot check that separates
"never a part" from "removed" from "renumbered".
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

GENERATION_1 = "research/evidence/silent-misreads-2026-08-22/ecfr-authority-notes.jsonl"
CORPUS = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_cfr_references.parquet"

#: The two the false-presences review found misprinting a title digit in their
#: own published text, and what each is very likely meant to say.
KNOWN_MISPRINTS = {
    (36, "251"): ("30 U.S.C. 1740, 1761-1771", "43 U.S.C. -- FLPMA's right-of-way sections"),
    (28, "541"): ("15 U.S.C. 301", "5 U.S.C. 301 -- the departmental-regulations boilerplate"),
}

VERSIONS_URL = "https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}"
USER_AGENT = "RefSpec-research/1.0 (Atlas regulatory-vocabulary research; contact michael.f.deeb@gmail.com)"


def normalize_part(part: object) -> str | None:
    """The reader's own join key (``cfr_authority_notes.normalize_part``)."""

    text = str(part or "").strip().lower()
    if not text:
        return None
    return text.lstrip("0") or "0"


def first_difference(left: str, right: str) -> str:
    """The two strings around the first character they disagree on."""

    for index, (one, other) in enumerate(zip(left, right)):
        if one != other:
            low, high = max(0, index - 60), index + 60
            return f"...{left[low:high]}...\n    vs ...{right[low:high]}..."
    return f"(one is a prefix of the other; {len(left)} vs {len(right)} characters)"


_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def is_reserved(head: str | None) -> bool:
    """Whether the publisher printed this part as a reservation."""

    return bool(head) and "[RESERVED]" in head.upper()


def covered_by_range(part: str, heads: dict) -> str | None:
    """The reserved block a missing part number falls inside, if any.

    A title publishes a removed block as one element -- 7 CFR
    ``<DIV5 N="413-459">``, headed "PARTS 413-459[RESERVED]" -- so a corpus
    reference to 7 CFR 457 is not an unknown part, it is a part the publisher
    has reserved. Saying which is the difference between "no answer" and "the
    answer is that it is gone".

    **The head is what decides, not the hyphen.** Titles 41 and 48 number their
    parts ``chapter-part``: 41 CFR ``50-201`` is chapter 50's part 201, headed
    "PART 50-201—...", and reading it as the numeric range 50 to 201 swallows
    every two- and three-digit part in the title. That is exactly the mistake
    the 41 CFR 101 spot check caught.
    """

    if not part.isdigit():
        return None
    number = int(part)
    for candidate, head in heads.items():
        match = _RANGE.match(candidate)
        if match and is_reserved(head) and int(match.group(1)) <= number <= int(match.group(2)):
            return candidate
    return None


def probe_part(title: int, part: str) -> dict:
    """Ask the versioner whether this part exists, and when it last did.

    Three attempts: the endpoint answered 503 to four of five requests in one
    burst and 200 to the identical requests a minute later, so a single refusal
    is transient rather than an answer.
    """

    url = VERSIONS_URL.format(title=title, part=part)
    result = {"url": url}
    payload = None
    for attempt in range(3):
        completed = subprocess.run(
            ["curl", "-sS", "--max-time", "90", "-A", USER_AGENT, "-w", "\n%{http_code}", url],
            capture_output=True,
            text=True,
        )
        body, _, status = completed.stdout.rpartition("\n")
        result["http_status"] = status.strip()
        result["attempts"] = attempt + 1
        try:
            payload = json.loads(body)
            break
        except json.JSONDecodeError:
            payload = None
            time.sleep(5 * (attempt + 1))
    if payload is None:
        result["verdict"] = "no JSON returned after three attempts"
        return result
    versions = payload.get("content_versions") or []
    result["version_records"] = len(versions)
    if not versions:
        result["verdict"] = "the versioner knows no version of this part: it does not exist in this title"
        return result
    result["issue_dates"] = sorted({one.get("issue_date") for one in versions})[-3:]
    result["removed"] = sorted({bool(one.get("removed")) for one in versions})
    result["identifiers"] = sorted({one.get("identifier") for one in versions})[:4]
    result["verdict"] = "the part exists; see issue dates and the removed flag"
    return result


def main() -> int:
    evidence = Path(sys.argv[1]).resolve()
    root = Path(sys.argv[2]).resolve()
    probe = "--probe" in sys.argv[3:]

    generation_2 = {}
    for line in (evidence / "notes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        generation_2[(row["cfr_title"], normalize_part(row["cfr_part"]))] = row
    census = json.loads((evidence / "extraction-census.json").read_text())

    report: dict = {"generation_2_notes": len(generation_2)}

    # (0) the drop-in check: every field CfrAuthorityNotes.from_file subscripts,
    # present and of the type it coerces, on every row. A schema check rather
    # than an import, so it does not depend on the working tree's grammar.
    required = {
        "cfr_title": int,
        "cfr_part": str,
        "authority_note": str,
        "api_url": str,
        "fetched": str,
        "raw_sha256": str,
        "raw_bytes": int,
        "raw_truncated_at_128k": bool,
    }
    faults = []
    duplicates = []
    keys_seen = set()
    for line in (evidence / "notes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for field, kind in required.items():
            if field not in row or not isinstance(row[field], kind):
                faults.append({"part": f"{row.get('cfr_title')} CFR {row.get('cfr_part')}", "field": field})
        if "source_note" not in row or not isinstance(row["source_note"], (str, type(None))):
            faults.append({"part": f"{row.get('cfr_title')} CFR {row.get('cfr_part')}", "field": "source_note"})
        key = (row["cfr_title"], normalize_part(row["cfr_part"]))
        if key in keys_seen:
            duplicates.append(f"{key[0]} CFR {key[1]}")
        keys_seen.add(key)
    report["schema"] = {
        "rows": len(keys_seen) + len(duplicates),
        "fields_the_reader_requires": sorted(required) + ["source_note"],
        "faults": faults,
        "duplicate_join_keys": sorted(set(duplicates)),
    }

    # (a) generation 1, part by part.
    generation_1 = {}
    for line in (root / GENERATION_1).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        generation_1[(row["cfr_title"], normalize_part(row["cfr_part"]))] = row

    classes = Counter()
    differences = []
    for key, old in sorted(generation_1.items()):
        new = generation_2.get(key)
        if new is None:
            classes["missing"] += 1
            differences.append({"part": f"{key[0]} CFR {key[1]}", "class": "missing", "generation_1": old["authority_note"], "generation_2": None})
            continue
        if new["authority_note"] == old["authority_note"]:
            classes["identical"] += 1
            continue
        if html.unescape(new["authority_note"]) == html.unescape(old["authority_note"]):
            classes["entity"] += 1
            kind = "entity"
        else:
            classes["drift"] += 1
            kind = "drift"
        differences.append(
            {
                "part": f"{key[0]} CFR {key[1]}",
                "class": kind,
                "generation_1_date": old["fetched"],
                "generation_2_date": new["title_issue_date"],
                "authority_level": new.get("authority_level"),
                "generation_1": old["authority_note"],
                "generation_2": new["authority_note"],
                "first_difference": first_difference(old["authority_note"], new["authority_note"]),
            }
        )
    report["generation_1"] = {
        "records": len(generation_1),
        "identical": classes["identical"],
        "entity_encoding_only": classes["entity"],
        "text_drift": classes["drift"],
        "missing_from_generation_2": classes["missing"],
        "differences": differences,
    }

    # (b) the two known title-digit misprints.
    misprints = {}
    for key, (fragment, likely) in KNOWN_MISPRINTS.items():
        new = generation_2.get(key)
        misprints[f"{key[0]} CFR {key[1]}"] = {
            "misprinted_fragment": fragment,
            "very_likely_meant": likely,
            "still_present_at_the_new_date": bool(new and fragment in new["authority_note"]),
            "title_issue_date": new and new["title_issue_date"],
            "authority_note": new and new["authority_note"],
        }
    report["known_misprints"] = misprints

    # (c) coverage against the corpus.
    import pyarrow.parquet as pq

    table = pq.read_table(root / CORPUS, columns=["cfr_title", "cfr_part"])
    titles = table.column("cfr_title").to_pylist()
    parts = table.column("cfr_part").to_pylist()
    raw_pairs = {(int(t), str(p)) for t, p in zip(titles, parts) if t is not None and p not in (None, "")}
    pairs = {(int(t), normalize_part(p)) for t, p in zip(titles, parts) if t is not None and normalize_part(p)}

    fetched_titles = {one["title"] for one in census["titles"] if one["skipped"] is None}
    reserved = {one["title"] for one in census["titles"] if one["skipped"] and "reserved" in one["skipped"]}
    parts_seen: dict[int, set[str]] = {}
    for one in census["titles"]:
        parts_seen.setdefault(one["title"], set())
    seen_by_title = json.loads((evidence / "parts-seen.json").read_text()) if (evidence / "parts-seen.json").is_file() else {}

    weight = Counter()
    for one, other in zip(titles, parts):
        key = (int(one), normalize_part(other)) if one is not None and normalize_part(other) else None
        if key:
            weight[key] += 1

    hits, misses = [], []
    for pair in sorted(pairs):
        if pair in generation_2:
            hits.append(pair)
            continue
        title, part = pair
        heads = seen_by_title.get(str(title), {})
        block = covered_by_range(part, heads)
        if title in reserved:
            family = "the title is reserved: no document is published"
            reason = family
        elif title not in fetched_titles:
            family = "the title is outside 1-50, or a hole in the fetch"
            reason = family
        elif part in heads and is_reserved(heads[part]):
            family = "the part is published as [RESERVED], so it states no authority"
            reason = f"{family}: {heads[part]}"
        elif part in heads:
            family = "the part exists but publishes no authority note anywhere in it"
            reason = family
        elif block:
            family = "removed: the number falls inside a reserved block the title publishes"
            reason = f"{family} ({block})"
        elif any(one.startswith(f"{part}-") for one in heads):
            family = "renumbered: this title numbers its parts chapter-part"
            reason = f"{family}, and publishes {part}-N"
        else:
            family = "the part does not exist in this title at the current date"
            reason = family
        misses.append(
            {
                "part": f"{title} CFR {part}",
                "cfr_title": title,
                "cfr_part": part,
                "corpus_rows": weight[pair],
                "reason": reason,
                "reason_family": family,
            }
        )
    misses.sort(key=lambda one: (-one["corpus_rows"], one["cfr_title"], one["cfr_part"]))

    report["coverage"] = {
        "corpus_distinct_pairs_raw": len(raw_pairs),
        "corpus_distinct_pairs_normalized": len(pairs),
        "covered": len(hits),
        "missed": len(misses),
        "coverage_fraction": round(len(hits) / len(pairs), 4) if pairs else None,
        "corpus_rows_total": sum(weight.values()),
        "corpus_rows_on_covered_parts": sum(weight[pair] for pair in hits),
        "corpus_rows_on_missed_parts": sum(one["corpus_rows"] for one in misses),
        "generation_1_covered_pairs": len(generation_1),
        "miss_reasons": Counter(one["reason_family"] for one in misses),
        "misses": misses,
    }

    # (d) totals per title come straight from the census.
    report["per_title"] = [
        {
            "title": one["title"],
            "date": one["date"],
            "parts_seen": one["parts_seen"],
            "notes": one["notes_extracted"],
            "part_level": one.get("part_level_notes"),
            "subdivision_level": one.get("subdivision_level_notes"),
            "without_note": one["parts_without_note"],
            "skipped": one["skipped"],
        }
        for one in census["titles"]
    ]

    if probe:
        # The five misses that cost the corpus most, one per (title, reason) so
        # the sample is not five faces of one cause. Checked against the live
        # versioner rather than believed.
        probes = []
        used = set()
        for one in misses:
            key = (one["cfr_title"], one["reason_family"])
            if key in used:
                continue
            used.add(key)
            probes.append({"part": one["part"], "corpus_rows": one["corpus_rows"], "reason": one["reason"], "reason_family": one["reason_family"], **probe_part(one["cfr_title"], one["cfr_part"])})
            time.sleep(2)
            if len(probes) == 5:
                break
        report["coverage"]["spot_checks"] = probes

    report["coverage"]["miss_reasons"] = dict(report["coverage"]["miss_reasons"])
    (evidence / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print(json.dumps({k: v for k, v in report.items() if k not in {"per_title"}}, indent=2, ensure_ascii=False)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

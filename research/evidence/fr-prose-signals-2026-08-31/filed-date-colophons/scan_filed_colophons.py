#!/usr/bin/env python3
"""Census the ``[FR Doc. {number} Filed {date}; {time}]`` colophon family.

Run from the repo root:

    .venv/bin/python .../filed-date-colophons/scan_filed_colophons.py
    .venv/bin/python .../filed-date-colophons/scan_filed_colophons.py --repin

The plain run scans ONLY the files pinned in ``input_inventory.json`` next to
this script, verifying each one's sha256 before reading it, and writes
``receipt.json``. ``--repin`` rebuilds that inventory from the working tree.

WHY THE INVENTORY EXISTS (2026-08-31, after review)
---------------------------------------------------
The first version walked ``REPO_ROOT.rglob("*")`` at run time. That is not a
reproducible scan: the working tree is mutable and other evidence lanes add
raw captures to it. A parallel lane's new
``research/evidence/fr-short-tails-2026-08-31/raw/`` files already carry
colophons, so the same script over the same repo silently returned a
different population from one day to the next, while the README quoted the
number as fixed.

BOUNDARY RULE FOR OTHER LANES' RAW DIRECTORIES -- decided, not accidental:
**INCLUDE them, through the pinned inventory.** They are holdings of this
repository and the question this family asks is "what colophon-bearing bytes
do we hold". Excluding them by accident is exactly what produced the previous
"that is the entire population" overclaim. Including them through a pinned
inventory means a lane's new capture does not silently move a published
number: it surfaces as named drift, and someone has to run ``--repin`` on
purpose and re-quote the census.

The plain run reports three drift classes and REFUSES to publish population
numbers on the first two:

- ``missing``      a pinned file is gone;
- ``digest_drift`` a pinned file's bytes changed;
- ``unpinned``     a file matching the walk rule exists on disk but is not in
                   the inventory (named, counted, and NOT scanned).

WHAT ELSE CHANGED
-----------------
- The time-text census is now a COUNT per distinct time, not a bare list of
  distinct values. The README previously said "8:45 am (6 of 9)"; the
  receipt's own specimens said 7.
- The MODS comparison is no longer a grep for stray prose. It reads every
  element name, every attribute name, and every date-bearing element's values
  across the comparison corpus, so the claim "no real filing-time field
  exists here" is bounded by what was actually inspected.
- A bounded presence probe of the LOCAL bulk corpora (outside this repo) is
  recorded, because the previous README claimed no bulk FR full-text corpus
  was available. One exists.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = Path(__file__).resolve().parent
INVENTORY_PATH = OUT_DIR / "input_inventory.json"

# The publisher's own colophon template. Group 1 = document number as printed
# (may itself carry damage, e.g. a fused trailing word), group 2 = date text,
# group 3 = time.
COLOPHON = re.compile(
    r"\[FR Doc\.?\s*(?:No:?\s*)?([A-Za-z0-9-]+?)\s*Filed\s+(\d{1,2}-\d{1,2}-\d{2,4})\s*;\s*"
    r"(\d{1,2}:\d{2}\s*[ap]m)\s*\]",
    re.IGNORECASE,
)

# Document-number family shapes, reusing the census vocabulary already
# established in src/refspec/registry/identifier_shapes.py's module notes.
MODERN = re.compile(r"^\d{4}-\d{3,6}$")
BARE_LEGACY = re.compile(r"^\d{2}-\d{1,6}$")
LETTER_OPENING = re.compile(r"^[A-Za-z]\d[\d-]*$")

# Damage classes found by raw-reading the specimens, not assumed in advance.
# ZERO_FILLED: the printed colophon is a placeholder the publisher never
# filled in -- "[FR Doc. 94-00000 Filed 00-00-94; 8:45 am]". The shape
# vocabulary ADMITS 94-00000 as bare-legacy and the date parses to a day that
# does not exist, so a reader gated on shape alone would take both.
# TRAILING_LETTER: "94-2050F" -- a real published number with a letter
# suffix, of the same micro-family as C0-6263A; no shape admits it today.
ZERO_FILLED_NUMBER = re.compile(r"^\d{2,4}-0+$")
ZERO_FILLED_DATE = re.compile(r"^0+-0+-\d{2,4}$")
TRAILING_LETTER_NUMBER = re.compile(r"^\d{2,4}-\d+[A-Za-z]$")

# The walk rule. Recorded in the inventory so a repin is auditable.
WALK_EXTENSIONS = [".xml", ".txt", ".html", ".htm"]
WALK_SKIP_DIR_NAMES = [".git", "node_modules", ".venv"]

MODS_DIR = (
    REPO_ROOT / "research/evidence/investigations-2026-08-23/inv-frvol/raw/govinfo_mods"
)

# Local bulk corpora, outside this repository. Named because the previous
# README asserted no bulk FR full-text corpus was available to measure.
EXTERNAL_CORPORA = {
    "body_retrieval_corpus_2026_08_02": Path(
        "~/Work/corpora/_preserved-2026-08-10/body-retrieval-corpus-2026-08-02"
    ).expanduser(),
    "body_retrieval_corpus_2026_08_02_copy": Path(
        "~/Work/spicy-regs/output/body-retrieval-corpus-2026-08-02"
    ).expanduser(),
    "salvage_2026_08_28_spicysearch_output": Path(
        "~/Work/corpora/_salvage-2026-08-28/spicysearch-output"
    ).expanduser(),
}
EXTERNAL_PROBE_FILE_CAP = 15

DATE_ELEMENT_NAMES = re.compile(r"date", re.IGNORECASE)
TIMEISH_NAME = re.compile(r"time|filed|filing|hour|clock", re.IGNORECASE)
CLOCK = re.compile(r"\d{1,2}:\d{2}")


def walk_candidates():
    exts = {e.lower() for e in WALK_EXTENSIONS}
    skip = set(WALK_SKIP_DIR_NAMES)
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip for part in path.parts):
            continue
        if path.suffix.lower() in exts:
            yield path


def read_and_hash(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def repin() -> None:
    files = []
    for path in walk_candidates():
        data, sha = read_and_hash(path)
        files.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "bytes": len(data),
                "sha256": sha,
            }
        )
    mods = []
    if MODS_DIR.is_dir():
        for path in sorted(MODS_DIR.glob("*.xml")):
            data, sha = read_and_hash(path)
            mods.append(
                {
                    "path": str(path.relative_to(REPO_ROOT)),
                    "bytes": len(data),
                    "sha256": sha,
                }
            )
    inventory = {
        "what_this_is": (
            "The exact set of files scan_filed_colophons.py is allowed to read. "
            "A plain run scans ONLY these paths and verifies each sha256 first. "
            "Rebuild deliberately with --repin, then re-quote the census."
        ),
        "walk_rule": {
            "root": "repository root",
            "extensions": WALK_EXTENSIONS,
            "skip_dir_names": WALK_SKIP_DIR_NAMES,
            "boundary_rule": (
                "Other evidence lanes' raw/ directories are INCLUDED. They are "
                "holdings of this repository. Their additions surface as 'unpinned' "
                "drift on the next run rather than silently changing the census."
            ),
        },
        "scan_set_file_count": len(files),
        "scan_set_total_bytes": sum(f["bytes"] for f in files),
        "mods_comparison_file_count": len(mods),
        "files": files,
        "mods_comparison_files": mods,
    }
    INVENTORY_PATH.write_text(json.dumps(inventory, indent=2) + "\n")
    print(
        f"Repinned {len(files)} scan files "
        f"({sum(f['bytes'] for f in files)} bytes) and "
        f"{len(mods)} MODS comparison files -> {INVENTORY_PATH.name}"
    )


def classify_number(num: str) -> str:
    if MODERN.match(num):
        return "modern (YYYY-NNNNN)"
    if LETTER_OPENING.match(num):
        return "letter-opening (legacy or modern hybrid)"
    if BARE_LEGACY.match(num):
        return "bare-legacy (YY-NNNNN)"
    return "unclassified"


def inspect_mods(entries: list[dict]) -> dict:
    """Read the comparison corpus's SCHEMA, not just its prose.

    The previous version grepped for the word "filed" and a clock time and
    concluded no filing-time field exists. That conclusion needs the field
    names, so this collects them.
    """
    element_names: Counter = Counter()
    attribute_names: Counter = Counter()
    date_element_values: dict[str, set] = {}
    files_with_colophon = []
    files_with_stray_prose = []
    stray = re.compile(r"\bfiled\b|\d{1,2}:\d{2}\s*[ap]m", re.IGNORECASE)

    for entry in entries:
        path = REPO_ROOT / entry["path"]
        text = path.read_bytes().decode("utf-8", errors="replace")
        if COLOPHON.search(text):
            files_with_colophon.append(entry["path"])
        if stray.search(text):
            files_with_stray_prose.append(path.name)
        for m in re.finditer(r"<([A-Za-z][\w:.-]*)([^>]*)>", text):
            name = m.group(1)
            element_names[name] += 1
            for a in re.findall(r"([A-Za-z][\w:.-]*)\s*=", m.group(2)):
                attribute_names[a] += 1
        for name in list(element_names):
            if not DATE_ELEMENT_NAMES.search(name):
                continue
            bucket = date_element_values.setdefault(name, set())
            for m in re.finditer(rf"<{re.escape(name)}\b[^>]*>(.*?)</{re.escape(name)}>", text, re.S):
                bucket.add(m.group(1).strip()[:60])

    date_fields = {}
    for name, values in sorted(date_element_values.items()):
        with_clock = sorted(v for v in values if CLOCK.search(v))
        date_fields[name] = {
            "distinct_values": len(values),
            "values_carrying_a_clock_time": len(with_clock),
            "clock_time_values": with_clock,
        }

    return {
        "files_inspected": len(entries),
        "distinct_element_names": len(element_names),
        "element_names": sorted(element_names),
        "distinct_attribute_names": len(attribute_names),
        "attribute_names": sorted(attribute_names),
        "element_or_attribute_names_matching_time_filed_filing_hour_clock": sorted(
            n for n in list(element_names) + list(attribute_names) if TIMEISH_NAME.search(n)
        ),
        "date_bearing_elements": date_fields,
        "files_carrying_the_colophon_string": files_with_colophon,
        "files_carrying_stray_filed_or_clock_prose": files_with_stray_prose,
        "claim_this_supports": (
            "Across the element and attribute names actually present in this "
            "comparison corpus, none names a filing time, and no date-bearing "
            "element carries a clock time except one free-text 'dates' value. "
            "Bounded to these files and these names -- not a statement about the "
            "MODS schema in general."
        ),
    }


def probe_external_corpora() -> dict:
    """Bounded presence probe, NOT a census. Names the corpora that exist."""
    out = {}
    for key, root in EXTERNAL_CORPORA.items():
        if not root.is_dir():
            out[key] = {"path": str(root), "present": False}
            continue
        xml = sorted(root.rglob("*.xml"))
        html = sorted(root.rglob("*.htm*"))
        probed = 0
        with_colophon = 0
        examples = []
        for path in xml[:EXTERNAL_PROBE_FILE_CAP]:
            try:
                text = path.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                continue
            probed += 1
            found = COLOPHON.findall(text)
            if found:
                with_colophon += 1
                if len(examples) < 5:
                    examples.append(list(found[0]))
        out[key] = {
            "path": str(root),
            "present": True,
            "xml_file_count": len(xml),
            "html_file_count": len(html),
            "probe": {
                "method": f"first {EXTERNAL_PROBE_FILE_CAP} .xml files by sorted path",
                "files_probed": probed,
                "files_carrying_a_colophon": with_colophon,
                "example_matches": examples,
                "is_a_census": False,
            },
        }
    return out


def main() -> None:
    if "--repin" in sys.argv:
        repin()
        return

    if not INVENTORY_PATH.exists():
        raise SystemExit(
            f"{INVENTORY_PATH} is missing. Build it deliberately with --repin."
        )
    inventory = json.loads(INVENTORY_PATH.read_text())
    pinned = inventory["files"]
    pinned_paths = {f["path"] for f in pinned}

    missing = []
    digest_drift = []
    specimens = []
    files_with_frdoc_tag = []
    files_with_raw_colophon_no_tag = []

    for entry in pinned:
        path = REPO_ROOT / entry["path"]
        if not path.exists():
            missing.append(entry["path"])
            continue
        data, sha = read_and_hash(path)
        if sha != entry["sha256"]:
            digest_drift.append(
                {"path": entry["path"], "pinned": entry["sha256"], "found": sha}
            )
            continue
        text = data.decode("utf-8", errors="replace")
        has_tag = "<FRDOC>" in text
        for m in COLOPHON.finditer(text):
            raw = m.group(0)
            number, date_text, time_text = m.group(1), m.group(2), m.group(3)
            fused = bool(re.search(re.escape(number) + r"Filed", raw))
            trailing_ws_in_tag = False
            if has_tag:
                tagm = re.search(
                    r"<FRDOC>(.*?)</FRDOC>", text[max(0, m.start() - 20) : m.end() + 20]
                )
                if tagm and tagm.group(1) != tagm.group(1).strip():
                    trailing_ws_in_tag = True
            specimens.append(
                {
                    "file": entry["path"],
                    "file_sha256": entry["sha256"],
                    "raw": raw,
                    "number": number,
                    "number_shape": classify_number(number),
                    "date_text": date_text,
                    "time_text": time_text,
                    "fused_number_filed": fused,
                    "trailing_whitespace_in_tag": trailing_ws_in_tag,
                    "zero_filled_placeholder": bool(
                        ZERO_FILLED_NUMBER.match(number)
                        or ZERO_FILLED_DATE.match(date_text)
                    ),
                    "trailing_letter_number": bool(TRAILING_LETTER_NUMBER.match(number)),
                    "carrier": "<FRDOC> tag" if has_tag else "raw prose (no tag)",
                }
            )
            if has_tag:
                if entry["path"] not in files_with_frdoc_tag:
                    files_with_frdoc_tag.append(entry["path"])
            else:
                if entry["path"] not in files_with_raw_colophon_no_tag:
                    files_with_raw_colophon_no_tag.append(entry["path"])

    unpinned = [
        str(p.relative_to(REPO_ROOT))
        for p in walk_candidates()
        if str(p.relative_to(REPO_ROOT)) not in pinned_paths
    ]

    blocking_drift = bool(missing or digest_drift)

    mods_entries = inventory.get("mods_comparison_files", [])
    mods_report = inspect_mods(mods_entries) if mods_entries else {}

    date_counts = Counter(s["date_text"] for s in specimens)
    time_counts = Counter(s["time_text"] for s in specimens)
    number_shape_counts = Counter(s["number_shape"] for s in specimens)
    fused_count = sum(1 for s in specimens if s["fused_number_filed"])
    trailing_ws_count = sum(1 for s in specimens if s["trailing_whitespace_in_tag"])
    placeholder = [s for s in specimens if s["zero_filled_placeholder"]]
    trailing_letter = [s for s in specimens if s["trailing_letter_number"]]

    receipt = {
        "input_inventory": {
            "path": str(INVENTORY_PATH.relative_to(REPO_ROOT)),
            "sha256": hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest(),
            "pinned_scan_file_count": len(pinned),
            "pinned_scan_total_bytes": inventory.get("scan_set_total_bytes"),
            "pinned_mods_file_count": len(mods_entries),
            "boundary_rule": inventory["walk_rule"]["boundary_rule"],
        },
        "drift": {
            "missing": missing,
            "digest_drift": digest_drift,
            "unpinned_files_on_disk_not_scanned": unpinned,
            "unpinned_count": len(unpinned),
            "population_numbers_are_valid": not blocking_drift,
        },
        "population_total_colophon_specimens": None if blocking_drift else len(specimens),
        "population_frdoc_tagged_files": None
        if blocking_drift
        else len(files_with_frdoc_tag),
        "population_raw_prose_files_no_tag": None
        if blocking_drift
        else len(files_with_raw_colophon_no_tag),
        "date_text_census": dict(sorted(date_counts.items())),
        "time_text_census": dict(sorted(time_counts.items(), key=lambda kv: -kv[1])),
        "document_number_shape_census": dict(number_shape_counts),
        "damage_fused_number_filed_count": fused_count,
        "damage_trailing_whitespace_in_tag_count": trailing_ws_count,
        "damage_zero_filled_placeholder_count": len(placeholder),
        "damage_zero_filled_placeholder": [
            {"file": s["file"], "raw": s["raw"], "number_shape": s["number_shape"]}
            for s in placeholder
        ],
        "damage_trailing_letter_number_count": len(trailing_letter),
        "damage_trailing_letter_number": [
            {"file": s["file"], "raw": s["raw"], "number_shape": s["number_shape"]}
            for s in trailing_letter
        ],
        "mods_comparison": mods_report,
        "external_bulk_corpora_probe": probe_external_corpora(),
        "specimens": specimens,
    }
    (OUT_DIR / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    print("=== FILED-DATE COLOPHON CENSUS ===")
    inv = receipt["input_inventory"]
    print(
        f"Pinned input inventory: {inv['path']} "
        f"({inv['pinned_scan_file_count']} files, {inv['pinned_scan_total_bytes']} bytes, "
        f"sha256 {inv['sha256'][:16]}...)"
    )
    print(f"  + {inv['pinned_mods_file_count']} pinned MODS comparison files")
    print(f"Drift: missing={len(missing)} digest_drift={len(digest_drift)} "
          f"unpinned_on_disk={len(unpinned)}")
    for u in unpinned[:10]:
        print(f"    unpinned (NOT scanned): {u}")
    if blocking_drift:
        print("!! Pinned inputs moved. Population numbers withheld. Re-run --repin "
              "deliberately, then re-quote the census.")
        for m in missing:
            print(f"    missing: {m}")
        for d in digest_drift:
            print(f"    digest drift: {d['path']}")
        return
    print()
    print(f"Total colophon specimens in the pinned set: {len(specimens)}")
    print(f"  - carried in a <FRDOC> XML tag: {len(files_with_frdoc_tag)} files")
    print(f"  - carried as raw prose, no tag: {len(files_with_raw_colophon_no_tag)} files")
    print()
    print("Document-number shape census:")
    for shape, n in sorted(number_shape_counts.items()):
        print(f"  {n:3d}  {shape}")
    print()
    print(f"Date-text census ({len(date_counts)} distinct over {len(specimens)} specimens):")
    for d, n in sorted(date_counts.items()):
        print(f"  {n:3d}  {d}")
    print(f"Time-text census ({len(time_counts)} distinct):")
    for t, n in sorted(time_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {t}")
    print()
    print(f"Damage 'fused number+Filed' (E5-2394Filed-shaped): {fused_count}")
    print(f"Damage 'trailing whitespace inside <FRDOC>': {trailing_ws_count}")
    print(f"Damage 'zero-filled placeholder colophon': {len(placeholder)}")
    for s in placeholder:
        print(f"    {s['raw']!r} -- shape vocabulary calls it {s['number_shape']!r}")
        print(f"        {s['file']}")
    print(f"Damage 'trailing-letter document number': {len(trailing_letter)}")
    for s in trailing_letter:
        print(f"    {s['raw']!r} -- shape vocabulary calls it {s['number_shape']!r}")
        print(f"        {s['file']}")
    print()
    print("--- MODS comparison corpus (schema, not just prose) ---")
    print(f"  files inspected: {mods_report.get('files_inspected')}")
    print(f"  distinct element names: {mods_report.get('distinct_element_names')}")
    print(f"  distinct attribute names: {mods_report.get('distinct_attribute_names')}")
    print(
        "  element/attribute names matching time|filed|filing|hour|clock: "
        f"{mods_report.get('element_or_attribute_names_matching_time_filed_filing_hour_clock')}"
    )
    for name, info in mods_report.get("date_bearing_elements", {}).items():
        print(
            f"    {name}: {info['distinct_values']} distinct values, "
            f"{info['values_carrying_a_clock_time']} with a clock time"
        )
        for v in info["clock_time_values"]:
            print(f"        {v!r}")
    print(
        f"  files carrying the colophon STRING: "
        f"{mods_report.get('files_carrying_the_colophon_string')}"
    )
    print()
    print("--- Local bulk corpora (outside this repo) -- bounded probe, not a census ---")
    for key, info in receipt["external_bulk_corpora_probe"].items():
        if not info["present"]:
            print(f"  {key}: ABSENT ({info['path']})")
            continue
        pr = info["probe"]
        print(
            f"  {key}: {info['path']}\n"
            f"      {info['xml_file_count']} .xml + {info['html_file_count']} .htm* files; "
            f"probe of {pr['files_probed']} -> {pr['files_carrying_a_colophon']} carry a colophon"
        )
        for e in pr["example_matches"][:3]:
            print(f"        e.g. [FR Doc. {e[0]} Filed {e[1]}; {e[2]}]")
    print()
    print("--- All specimens ---")
    for s in specimens:
        print(f"  [{s['file']}] {s['raw']!r}  (shape={s['number_shape']}, "
              f"fused={s['fused_number_filed']})")


if __name__ == "__main__":
    main()

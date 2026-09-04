"""Declare the receipt deltas this fix produces in the combined rebuild.

Reads pinned inputs and the shipped artifact. Its only writes in the
repository are the two JSONs it leaves beside itself in this directory (it
also spills HEAD's module to a system temp file to import it). Two stages:

1. Diff the OLD (HEAD, unfixed) and NEW (this fix) citation_grammar module
   in isolation, over every distinct authority_text the shipped artifact
   carries, to find exactly which (authority_text, usc_title, usc_section)
   triples the fix removes. This is the same technique as
   compare_grammar.py's full-corpus diff, restricted to the usc family.

   Diffing the grammar in isolation -- not "new grammar vs. what the
   artifact currently stores" -- is deliberate: the shipped artifact is
   built by unified_agenda_parquet.py, which layers further correction and
   enlargement rules (B8, the #46 fences, usc_section_corrected, ...) on
   top of the raw grammar read. Comparing the new grammar directly against
   the artifact's stored usc_section conflates THIS fix with all of that
   other, unrelated drift (an early, wrong pass of this script found 1,404
   "lost" rows against completely unrelated authority values like "10
   U.S.C. 218" -- rows this fix never touches). Diffing old-vs-new grammar
   output in isolation isolates exactly what THIS change moves.

2. Join those removed triples back to the actual artifact rows (matching
   authority_text + usc_title + usc_section) to get real row counts, RIN
   counts, and verdict crosstabs from the live data -- the numbers the
   integrator attributes after the combined rebuild.
"""
import collections
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile

import duckdb

REPO = str(Path(__file__).resolve().parents[3])


def _load_head_module():
    """The pre-fix grammar, fetched straight from git rather than a stored copy."""

    src = subprocess.run(
        ["git", "-C", REPO, "show", "HEAD:src/refspec/registry/citation_grammar.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
        path = f.name
    spec = importlib.util.spec_from_file_location("cg_head_deltas", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cg_head_deltas"] = mod
    spec.loader.exec_module(mod)
    return mod


orig = _load_head_module()
sys.path.insert(0, f"{REPO}/src")
from refspec.registry import citation_grammar as new  # noqa: E402

ART = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"
con = duckdb.connect(":memory:")
rows = (
    con.execute(
        f"""
        select rin, publication_id, ordinal, citation_ordinal, authority_text,
               authority_type, parse_status, usc_title, usc_section, usc_section_end,
               usc_section_verdict, authority_in_own_cfr_note, cfr_note_part
        from '{ART}'
        """
    )
    .arrow()
    .read_all()
    .to_pylist()
)
print("total rows in current artifact:", len(rows))

distinct_texts = sorted({r["authority_text"] for r in rows if r["authority_text"]})


def usc_pairs(citations):
    return {(c.usc_title, c.usc_section) for c in citations if c.authority_type == "usc" and c.usc_section is not None}


removed_pairs: dict[str, set] = {}
added_pairs: dict[str, set] = {}
for text in distinct_texts:
    o = usc_pairs(orig.parse_authority_citation(text))
    n = usc_pairs(new.parse_authority_citation(text))
    removed = o - n
    added = n - o
    if removed:
        removed_pairs[text] = removed
    if added:
        added_pairs[text] = added

print("distinct authority_text losing at least one usc pair:", len(removed_pairs))
print("distinct authority_text gaining at least one usc pair:", len(added_pairs))
if added_pairs:
    print("UNEXPECTED gains (should be none -- this fix only refuses):", added_pairs)

lost_rows = [
    r
    for r in rows
    if r["authority_text"] in removed_pairs and (r["usc_title"], r["usc_section"]) in removed_pairs[r["authority_text"]]
]

print()
print("== rows carrying a (title, section) pair the fix removes ==")
print("rows:", len(lost_rows))
print("distinct RINs:", len({r["rin"] for r in lost_rows}))
print("distinct authority_text:", len({r["authority_text"] for r in lost_rows}))
print()
print("== by CURRENT usc_section_verdict (what the verdict census loses) ==")
print(collections.Counter(r["usc_section_verdict"] for r in lost_rows))
print()
exists_lost = [r for r in lost_rows if r["usc_section_verdict"] == "exists"]
print("== current verdict == exists (the false affirmatives) ==")
print(len(exists_lost), "rows /", len({r["rin"] for r in exists_lost}), "RINs")
print()
present_lost = [r for r in lost_rows if r["authority_in_own_cfr_note"] == "present"]
print("== rows with exact ground truth in the RIN's own CFR_LIST (authority_in_own_cfr_note == 'present') ==")
print(len(present_lost), "rows /", len({r["rin"] for r in present_lost}))
print()

# Rows for the SAME (rin, publication_id, authority_text) that are NOT
# removed -- proof the fix corrects a member rather than deleting RIN
# coverage entirely, for the list-continuation cases ("40 U.S.C. 102.01,
# 322, 5331" keeps 322 and 5331).
lost_keys = {(r["rin"], r["publication_id"], r["authority_text"]) for r in lost_rows}
survivors_by_key: dict[tuple, list] = collections.defaultdict(list)
for r in rows:
    key = (r["rin"], r["publication_id"], r["authority_text"])
    if key in lost_keys and r["authority_type"] == "usc" and (r["usc_title"], r["usc_section"]) not in removed_pairs.get(r["authority_text"], set()):
        survivors_by_key[key].append(r["usc_section"])

print("== keys (rin, publication_id, authority_text) with a usc row that SURVIVES the fix ==")
print(len(survivors_by_key))
for k, sections in sorted(survivors_by_key.items())[:10]:
    print(" ", k, "keeps", sections)

with open("research/evidence/reg-dot-fence-2026-09-01/lost_rows.json", "w") as f:
    json.dump(lost_rows, f, indent=2, default=str)
with open("research/evidence/reg-dot-fence-2026-09-01/removed_pairs.json", "w") as f:
    json.dump({t: sorted(list(p)) for t, p in removed_pairs.items()}, f, indent=2, default=str)

"""Declare the receipt deltas Unit B moves, against the TRUE pre-fix baseline.

Reads pinned inputs. Its only write in the repository is the one JSON it
leaves beside itself in this directory (it also spills HEAD's modules to
system temp files to import them). Fetches HEAD's citation_grammar.py and
cfr_authority_notes.py
(git show, not a stored copy -- always compares against whatever HEAD
actually is) and wires them together exactly as the pre-fix package did, so
``old.read_note_citations`` calls ``old`` citation_grammar with no marking
and no gate at all -- the actual shipped-before-this-lane behavior, not the
new code's own conservative fallback (measure_gate_deltas.py answers a
different, narrower question: what the oracle recovers relative to this
fix's OWN no-oracle default).

Then builds the real 8,240-note cache under OLD and NEW (oracle-gated, the
production default) and diffs every note's usc citations.

The NEW package is imported FIRST and its class object kept, before any
``sys.modules`` surgery for the OLD one -- otherwise loading HEAD's
cfr_authority_notes under the real module name overwrites
``sys.modules['refspec.registry.cfr_authority_notes']`` and a later `import`
of "new" silently returns the just-loaded OLD module instead (a real bug an
earlier version of this script had: it reported 0 removed because "new" was
secretly "old").
"""
import importlib.util
import json
import subprocess
import sys
import tempfile

REPO = "/Users/mikewolfd/Work/RefSpec"

# NEW first, while sys.modules still holds the real (fixed) package.
from refspec.registry.cfr_authority_notes import CfrAuthorityNotes as NewCfrAuthorityNotes  # noqa: E402


def _load_head_module(repo_relative_path, name):
    src = subprocess.run(
        ["git", "-C", REPO, "show", f"HEAD:{repo_relative_path}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
        path = f.name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# OLD, loaded under the real module names AFTER "new" is already bound above.
# old_notes.py's own `from refspec.registry.citation_grammar import (...)`
# resolves against whatever sys.modules holds at THIS point -- old_grammar,
# loaded the line before -- which is what makes old_notes exercise the
# pre-fix grammar's parse_authority_citation (no usc_section_after_statute
# marking at all, so this particular swap wouldn't have mattered either way:
# OLD read_note_citations never reads that field regardless of which grammar
# module it is bound to).
old_grammar = _load_head_module("src/refspec/registry/citation_grammar.py", "refspec.registry.citation_grammar")
old_notes = _load_head_module("src/refspec/registry/cfr_authority_notes.py", "refspec.registry.cfr_authority_notes")

NOTES_PATH = f"{REPO}/research/evidence/ecfr-authority-notes-2026-08-24/notes.jsonl"

old_cache = old_notes.CfrAuthorityNotes.from_file(NOTES_PATH)
new_cache = NewCfrAuthorityNotes.from_repository(REPO)  # production default: oracle auto-loaded

assert len(old_cache.records) == len(new_cache.records) == 8_240

removed = []
added = []
for old_record, new_record in zip(old_cache.records, new_cache.records, strict=True):
    assert (old_record.cfr_title, old_record.cfr_part) == (new_record.cfr_title, new_record.cfr_part)
    before = {c.identity for c in old_record.citations if c.family == "usc"}
    after = {c.identity for c in new_record.citations if c.family == "usc"}
    for identity in before - after:
        removed.append((old_record.cfr_title, old_record.cfr_part, identity))
    for identity in after - before:
        added.append((old_record.cfr_title, old_record.cfr_part, identity))

print("total citations (HEAD, pre-fix):", sum(len(r.citations) for r in old_cache.records))
print("total citations (this fix, oracle-gated production default):", sum(len(r.citations) for r in new_cache.records))
print()
print("== usc identities the fix REMOVES relative to HEAD ==")
print("count:", len(removed))
print("distinct notes:", len({(t, p) for t, p, _ in removed}))
print()
print("== usc identities the fix ADDS relative to HEAD (should be none) ==")
print("count:", len(added))
for row in added[:20]:
    print(" ", row)

with open("research/evidence/stat-page-gate-2026-09-01/removed_vs_head.json", "w") as f:
    json.dump(removed, f, indent=2, default=str)

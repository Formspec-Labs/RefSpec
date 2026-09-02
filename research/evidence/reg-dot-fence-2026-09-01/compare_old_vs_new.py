"""Full-corpus regression check: diff HEAD's citation_grammar against the
working tree's, over every distinct authority_text the shipped artifact
carries.

Fetches the pre-fix module straight from git (``git show HEAD:...``) rather
than keeping a duplicated copy in this evidence dir, so it always compares
against whatever HEAD actually is. Run from the repo root.

Confirms two things this lane's report claims:
  1. exactly 41 distinct authority_text values change behavior at all
     (every other value in the 42,677-value corpus is untouched);
  2. the fix never adds a new (title, section) pair anywhere -- it only
     ever refuses or narrows, never fabricates.
"""
import importlib.util
import subprocess
import sys
import tempfile

import duckdb

REPO = "/Users/mikewolfd/Work/RefSpec"
ART = "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_legal_authorities.parquet"


def _load_head_module():
    src = subprocess.run(
        ["git", "-C", REPO, "show", "HEAD:src/refspec/registry/citation_grammar.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
        path = f.name
    spec = importlib.util.spec_from_file_location("cg_head", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cg_head"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    old = _load_head_module()
    sys.path.insert(0, f"{REPO}/src")
    from refspec.registry import citation_grammar as new

    con = duckdb.connect(":memory:")
    texts = [
        r[0]
        for r in con.execute(
            f"select distinct authority_text from '{ART}' where authority_text is not null"
        ).fetchall()
    ]
    print("distinct authority_text:", len(texts))

    def summarize(citations):
        return tuple(
            (c.authority_type, c.parse_status, c.usc_title, c.usc_section, c.usc_section_end, c.usc_appendix)
            for c in citations
        )

    changed = 0
    added_anywhere = False
    for t in texts:
        o = summarize(old.parse_authority_citation(t))
        n = summarize(new.parse_authority_citation(t))
        if o != n:
            changed += 1
        o_pairs = {(c[2], c[3]) for c in o if c[0] == "usc" and c[3] is not None}
        n_pairs = {(c[2], c[3]) for c in n if c[0] == "usc" and c[3] is not None}
        if n_pairs - o_pairs:
            added_anywhere = True
            print("UNEXPECTED new pair for", repr(t), n_pairs - o_pairs)

    print("distinct authority_text with any behavior change:", changed)
    print("any newly-added (title, section) pair anywhere:", added_anywhere)


if __name__ == "__main__":
    main()

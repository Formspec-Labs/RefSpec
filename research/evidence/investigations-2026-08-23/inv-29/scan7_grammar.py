"""Read-only grammar demonstration: run every continuation through the
builder's own grammar entry point, parse_authority_citation, exactly as the
builder calls it on a whole LEGAL_AUTHORITY box text. No writes to the repo.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "/Users/mikewolfd/Work/RefSpec/src")

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402

OUT_DIR = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-29")
rows = json.loads((OUT_DIR / "final_rows.json").read_text(encoding="utf-8"))

results = []
type_status_counter = Counter()

for r in rows:
    text = r["continuation"]
    parsed = parse_authority_citation(text)
    parsed_dicts = [asdict(p) for p in parsed]
    for p in parsed:
        type_status_counter[(p.authority_type, p.parse_status)] += 1
    results.append(
        {
            "rin": r["rin"],
            "publication_id": r["publication_id"],
            "continuation": text,
            "row_count": len(parsed),
            "rows": parsed_dicts,
        }
    )

print(f"Total continuation strings run through parse_authority_citation: {len(rows)}")
print(f"Total AuthorityCitation rows produced (whole-string-per-record call): {sum(r['row_count'] for r in results)}")
print()
print("Rows by (authority_type, parse_status):")
for (atype, status), count in sorted(type_status_counter.items(), key=lambda kv: -kv[1]):
    print(f"  {atype:20s} {status:15s} {count:4d}")

print()
print("=" * 100)
for r in results:
    print(f"\nRIN {r['rin']} ed {r['publication_id']}  -> {r['row_count']} row(s)")
    print(f"  continuation: {r['continuation']!r}")
    for row in r["rows"]:
        # Print only the non-null, non-default-ish fields for readability.
        interesting = {
            k: v
            for k, v in row.items()
            if v not in (None, False) and k not in ("usc_appendix", "usc_note")
        }
        print(f"    {interesting}")

(OUT_DIR / "grammar_results.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
print(f"\nWrote {len(results)} records to {OUT_DIR / 'grammar_results.json'}")

# Specific diagnostics called out in the investigation brief.
print()
print("=" * 100)
print("DIAGNOSTIC: does a stray internal space break a USC section match, and")
print("does it silently vanish when sibling citations in the same call succeed?")
for probe in ["15 USC 77 eee", "15 USC 77eee"]:
    out = parse_authority_citation(probe)
    print(f"  parse_authority_citation({probe!r}) -> {[asdict(o) for o in out]}")

specimen = "15 USC 77g; 15 USC 77j; 15 USC 77 eee; 15 USC 77ggg; 15 USC 77nnn; 15 USC 77sss; 15 USC 78d; 15 USC 78ff; 15 USC 80a-20; 15 USC 80a-23; 15 USC 80b-4; 15 USC 80b-11; 15 USC 78ll(d)"
out = parse_authority_citation(specimen)
print(f"\n  Specimen whole-string call -> {len(out)} rows:")
for o in out:
    print(f"    {o.authority_type} {o.parse_status} usc_title={o.usc_title} usc_section={o.usc_section}")
sections_seen = {o.usc_section for o in out if o.usc_section}
print(f"  Distinct usc_section values recovered: {sorted(sections_seen)}")
print("  Is '77eee' (or any spelling of it) among them?", any("eee" in (s or "") for s in sections_seen))

# Split-by-semicolon comparison for the specimen, to show the split-vs-whole
# difference concretely.
print()
print("Split-by-';' comparison for the specimen (each fragment its own call):")
total = 0
for fragment in specimen.split(";"):
    fragment = fragment.strip()
    out = parse_authority_citation(fragment)
    total += len(out)
    print(f"  {fragment!r:30s} -> {[(o.authority_type, o.parse_status, o.usc_section) for o in out]}")
print(f"  Total rows via split-by-';': {total} (vs {len(parse_authority_citation(specimen))} via whole-string call)")

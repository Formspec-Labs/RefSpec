from __future__ import annotations

import collections
import pyarrow.parquet as pq

P = "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/old-rebuild6-d19df1bd/out/unified_agenda_legal_authorities.parquet"
t = pq.read_table(P, columns=["authority_type", "parse_status", "usc_title", "usc_section",
                              "act_key", "act_section", "stated_act_name", "stated_section",
                              "usc_section_verdict", "corroboration_rule"])
n = t.num_rows
print("rows:", f"{n:,}")
pairs = collections.Counter(zip(t.column("authority_type").to_pylist(), t.column("parse_status").to_pylist()))
print("\n(authority_type, parse_status) -- all:")
for (a, s), c in pairs.most_common():
    print(f"  {a:<22} {s:<14} {c:>8,}")
print("\nauthority_type totals:")
for a, c in collections.Counter(t.column("authority_type").to_pylist()).most_common():
    print(f"  {a:<22} {c:>8,}")
print("\nparse_status totals:")
for s, c in collections.Counter(t.column("parse_status").to_pylist()).most_common():
    print(f"  {s:<22} {c:>8,}")
print("\nusc_section_verdict totals:")
for s, c in collections.Counter(t.column("usc_section_verdict").to_pylist()).most_common():
    print(f"  {str(s):<22} {c:>8,}")

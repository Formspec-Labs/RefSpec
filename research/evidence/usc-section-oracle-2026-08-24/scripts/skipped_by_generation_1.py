"""Every archive member generation 1's matcher skipped, all 31 years.

Applies generation 1's pattern -- ``(\\d{4})/\\1usc(\\d+)([a-zA-Z]?)\\.htm$``,
case-sensitive -- to every member of every annual zip and prints the ones it
does not match, beside what generation 2's case-insensitive pattern makes of
the same name.  A member that is a title volume under generation 2 and not
under generation 1 is a silently skipped volume; the rest are the year index
page, the Popular Names table and Tables 1-6, which are not title volumes in
either generation.

Usage:  python3 skipped_by_generation_1.py <zip-dir>
"""

import re
import sys
import zipfile
from pathlib import Path

ZIPS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/usc-annual-2026-08-24")
YEARS = range(1994, 2025)

OLD = re.compile(r"(\d{4})/\1usc(\d+)([a-zA-Z]?)\.htm$")
NEW = re.compile(r"(\d{4})/\1usc(\d+)([a-zA-Z]?)\.htm$", re.IGNORECASE)
TAB = "\t"

print(TAB.join(["year", "member", "bytes", "member_mtime", "gen1_match", "gen2_match", "verdict"]))
skipped_volumes = []
totals = {"members": 0, "gen1": 0, "gen2": 0}
for year in YEARS:
    path = ZIPS / f"{year}.zip"
    if not path.exists():
        print(TAB.join([str(year), "MISSING ZIP", "", "", "", "", ""]))
        continue
    zf = zipfile.ZipFile(path)
    for name in zf.namelist():
        info = zf.getinfo(name)
        old, new = OLD.search(name), NEW.search(name)
        totals["members"] += 1
        totals["gen1"] += 1 if old else 0
        totals["gen2"] += 1 if new else 0
        if old:
            continue
        when = "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time
        if new:
            verdict = "SILENTLY SKIPPED TITLE VOLUME"
            skipped_volumes.append((year, name, info.file_size, when, int(new.group(2)), new.group(3)))
        else:
            verdict = "not a title volume in either generation"
        print(TAB.join([
            str(year), name, str(info.file_size), when,
            "no", f"title={new.group(2)} appendix={bool(new.group(3))}" if new else "no",
            verdict,
        ]))

print()
print(f"members inspected: {totals['members']}   matched by generation 1: {totals['gen1']}"
      f"   matched by generation 2: {totals['gen2']}")
print(f"title volumes generation 1 skipped: {len(skipped_volumes)}")
print(TAB.join(["year", "member", "bytes", "member_mtime", "title", "appendix_suffix"]))
for year, name, size, when, title, suffix in skipped_volumes:
    print(TAB.join([str(year), name, str(size), when, str(title), repr(suffix)]))

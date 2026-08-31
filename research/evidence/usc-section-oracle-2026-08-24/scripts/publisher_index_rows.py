"""The publisher's own listing rows for the twelve uppercase-USC volumes.

Reads the per-year index pages the annual archive publishes -- either the
copies saved by ``research/evidence/investigations-2026-08-24/inv-2012/`` or
the ``YYYY/index.html`` member inside each year's zip -- and prints the name,
size and datetime OLRC states for every title volume whose name is not
lowercase ``usc``.

Usage:  python3 publisher_index_rows.py <index.html> [<index.html> ...]
"""

import re
import sys
from html import unescape

ROW = re.compile(
    r"<tr class='downloadablefilerow'>\s*"
    r"<td class='filetodownloadname'>(?P<name>[^<]*)</td>\s*"
    r"<td class='filetodownloadsize'>(?P<size>[^<]*)</td>\s*"
    r"<td class='filetodownloaddatetime'>(?P<when>[^<]*)</td>",
    re.S,
)
TITLE = re.compile(r"^(\d{4})usc(\d+)([a-zA-Z]?)\.htm$", re.IGNORECASE)
TAB = "\t"

print(TAB.join(["source", "name", "publisher_size", "publisher_datetime", "case"]))
for path in sys.argv[1:]:
    src = open(path, encoding="utf-8", errors="replace").read()
    for m in ROW.finditer(src):
        name = unescape(m.group("name")).strip()
        tm = TITLE.match(name)
        if not tm:
            continue
        case = "lowercase-usc" if "usc" in name else "UPPERCASE-USC"
        if case == "lowercase-usc":
            continue
        size = unescape(m.group("size")).strip()
        when = unescape(m.group("when")).replace("\xa0", " ")
        when = re.sub(r"\s+", " ", when).strip()
        print(TAB.join([path, name, size, when, case]))

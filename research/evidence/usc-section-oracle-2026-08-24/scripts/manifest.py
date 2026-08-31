"""Write MANIFEST.tsv: sha256 and byte length of every file in this directory,
plus the raw OLRC sources the tables were derived from.

Usage:  python3 manifest.py <evidence-dir> <zip-dir>
"""

import hashlib
import sys
from pathlib import Path

DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research/evidence/usc-section-oracle-2026-08-24")
ZIPS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output/usc-annual-2026-08-24")
TAB = "\t"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


lines = [TAB.join(["kind", "path", "bytes", "sha256"])]
for path in sorted(DIR.rglob("*")):
    if path.is_dir() or path.name == "MANIFEST.tsv":
        continue
    kind = "derived" if path.suffix == ".parquet" else ("script" if path.suffix in {".py", ".sh"} else "doc")
    lines.append(TAB.join([kind, str(path.relative_to(DIR)), str(path.stat().st_size), sha256(path)]))

for path in sorted(ZIPS.glob("*.zip")):
    lines.append(TAB.join(["source-zip (not committed)", path.name, str(path.stat().st_size), sha256(path)]))

out = DIR / "MANIFEST.tsv"
out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))

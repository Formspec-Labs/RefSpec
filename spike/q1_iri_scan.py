"""Exactly which lines of a real distribution does pyoxigraph refuse?

Method: a cheap superset filter (any line containing a character that cannot
appear unescaped inside an RFC 3987 IRI) followed by an individual
`pyoxigraph.parse` of each candidate line, so the verdict is oxigraph's own,
not a regex's. rdflib is then asked for the same lines.

    .venv/bin/python spike/q1_iri_scan.py [full|staging]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyoxigraph as ox

FULL_ROOT = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12")
STAGING = Path(
    "/Users/mikewolfd/Work/spicy-regs/RefSpec/output/"
    "atlas-3.1-mapping-topology-staging/distribution"
)
# Characters excluded from RFC 3987 IRIs that oxigraph rejects inside <...>.
SUSPECT = b'[]|\\^`{} '


def _zstd():
    try:
        from compression import zstd
    except ImportError:
        from backports import zstd
    return zstd


def main() -> None:
    root = FULL_ROOT if sys.argv[1:2] == ["full"] else STAGING
    zstd = _zstd()
    packs = json.loads((root / "atlas-manifest.json").read_bytes())["packs"]
    refused: dict[str, int] = {}
    candidates = 0
    samples: list[tuple[str, int, str, str]] = []
    for pack in packs:
        with zstd.open(root / pack["path"], "rb") as fh:
            for n, line in enumerate(fh, 1):
                if not any(c in line for c in SUSPECT):
                    continue
                candidates += 1
                try:
                    list(ox.parse(line, format=ox.RdfFormat.N_QUADS))
                except SyntaxError as exc:
                    refused[pack["path"]] = refused.get(pack["path"], 0) + 1
                    if len(samples) < 8:
                        samples.append((pack["path"], n, line.decode("utf-8").rstrip(), str(exc)))
    print(f"candidate lines examined: {candidates}")
    total = 0
    for path, count in sorted(refused.items()):
        print(f"REFUSED {path}: {count} lines")
        total += count
    print(f"packs refused: {len(refused)}/{len(packs)}; lines refused: {total}")
    from rdflib import Dataset

    for path, n, line, exc in samples:
        print(f"\n{path}:{n}\n  {line[:260]}\n  oxigraph: {exc}")
        ds = Dataset()
        ds.parse(data=line + "\n", format="nquads")
        print(f"  rdflib:   ACCEPTED ({len(list(ds.quads((None, None, None, None))))} quad)")


if __name__ == "__main__":
    main()

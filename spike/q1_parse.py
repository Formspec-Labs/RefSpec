"""Q1 -- parse + store: pyoxigraph vs rdflib on the real staging packs.

One variant per process so `ru_maxrss` is the variant's own peak.

    .venv/bin/python spike/q1_parse.py <variant> [n_packs]

`n_packs` selects the first N packs in ASCENDING size order (linearity probe);
default is all 5 (1,013,723 quads / 232.5 MB).
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/Users/mikewolfd/Work/spicy-regs/RefSpec/bindings/atlas/3.1/tools")

import common  # noqa: E402


def _packs(n: int | None) -> list[Path]:
    paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)
    return paths if n is None else paths[:n]


def _quad_total(paths: list[Path]) -> int:
    m = {p["path"].replace("/", "__").removesuffix(".zst"): p["content"]["quadCount"] for p in common.manifest()["packs"]}
    return sum(m[p.name] for p in paths)


# --------------------------------------------------------------------------- rdflib


def rdflib_stock(paths: list[Path]) -> int:
    """Stock rdflib: NQuadsParser -> Dataset (Memory store). No canonicality proof."""

    from rdflib import Dataset

    ds = Dataset()
    for p in paths:
        with p.open("rb") as fh:
            ds.parse(source=fh, format="nquads")
    return sum(1 for _ in ds.quads((None, None, None, None)))


def rdflib_lexical(paths: list[Path]) -> int:
    """validate.py's pinned parser: lexeme-preserving + per-line canonicality proof."""

    import validate as V
    from rdflib import Dataset

    ds = Dataset()
    total = 0
    for p in paths:
        with p.open("rb") as fh:
            counts = V._parse_nquads_preserving_lexical_forms(ds, fh)
        total += sum(counts.values())
    return total


def rdflib_full(paths: list[Path]) -> int:
    """validate.py's real pack path: zstd stream + byte profile reader + lexical parse."""

    import validate as V
    from rdflib import Dataset, URIRef

    root = common.STAGING
    man = common.manifest()
    graph_ids = {row["role"]: URIRef(row["id"]) for row in man["graphs"]}
    wanted = {p.name for p in paths}
    ds = Dataset()
    owners: dict[str, dict] = {role: {} for role in graph_ids}
    total = 0
    for pack in man["packs"]:
        if pack["path"].replace("/", "__").removesuffix(".zst") not in wanted:
            continue
        counts = V._parse_pack_into_dataset(ds, root, pack, graph_ids, owners)
        total += sum(counts.values())
    return total


def rdflib_profile_only(paths: list[Path]) -> int:
    """Byte-level half of the canonicality proof alone (zstd + digest + line rules)."""

    import validate as V

    root = common.STAGING
    wanted = {p.name for p in paths}
    total = 0
    for pack in common.manifest()["packs"]:
        if pack["path"].replace("/", "__").removesuffix(".zst") not in wanted:
            continue
        try:
            from compression import zstd
        except ImportError:
            from backports import zstd
        with (root / pack["path"]).open("rb") as raw:
            tr = V._DigestingReader(raw, label=pack["path"])
            dec = zstd.open(tr, "rb")
            rd = V._NQuadsProfileReader(dec, label=pack["path"], expected=pack["content"])
            while rd.read(1 << 20):
                pass
            rd.finish(pack["content"])
            tr.finish(pack["transport"], require_consumed=True)
            dec.close()
        total += rd.line_count
    return total


# ----------------------------------------------------------------------- pyoxigraph


def oxi_store(paths: list[Path]) -> int:
    """In-memory pyoxigraph Store, per-pack `load` from an open file handle."""

    import pyoxigraph as ox

    store = ox.Store()
    for p in paths:
        with p.open("rb") as fh:
            store.load(fh, format=ox.RdfFormat.N_QUADS)
    return len(store)


def oxi_store_bulk(paths: list[Path]) -> int:
    """In-memory pyoxigraph Store via `bulk_load` (the documented fast path)."""

    import pyoxigraph as ox

    store = ox.Store()
    for p in paths:
        store.bulk_load(path=str(p), format=ox.RdfFormat.N_QUADS)
    return len(store)


def oxi_parse_count(paths: list[Path]) -> int:
    """oxrdfio through `pyoxigraph.parse`: materialize each quad in Python, no store."""

    import pyoxigraph as ox

    total = 0
    for p in paths:
        with p.open("rb") as fh:
            for _quad in ox.parse(fh, format=ox.RdfFormat.N_QUADS):
                total += 1
    return total


def oxi_store_zstd(paths: list[Path]) -> int:
    """Store load straight off the zstd stream, as validate.py streams its packs."""

    import pyoxigraph as ox

    try:
        from compression import zstd
    except ImportError:
        from backports import zstd

    root = common.STAGING
    wanted = {p.name for p in paths}
    store = ox.Store()
    for pack in common.manifest()["packs"]:
        if pack["path"].replace("/", "__").removesuffix(".zst") not in wanted:
            continue
        with zstd.open(root / pack["path"], "rb") as fh:
            store.load(fh, format=ox.RdfFormat.N_QUADS)
    return len(store)


def oxi_canonicality(paths: list[Path]) -> int:
    """Q5 probe: byte-level line rules + per-quad canonical round trip, oxigraph terms.

    Mirrors `_NQuadsProfileReader`'s line rules and `_LexicalNQuadsParser`'s
    `original != nquads_line(...)` proof, but re-serializes with pyoxigraph's
    own N-Quads writer instead of rdflib's term renderer.
    """

    import hashlib

    import pyoxigraph as ox

    total = 0
    for p in paths:
        digest = hashlib.sha256()
        previous: bytes | None = None
        with p.open("rb") as fh:
            data = fh.read()
        digest.update(data)
        # Line rules (sorted, unique, no CR, no padding) over raw bytes.
        for line in data.splitlines(keepends=True):
            if b"\r" in line:
                raise SystemExit("CR")
            content = line[:-1]
            if not content or content != content.strip():
                raise SystemExit("padded")
            if previous is not None and line <= previous:
                raise SystemExit("unsorted")
            previous = line
            total += 1
        # Term-form proof: re-serialize each parsed quad and compare with its line.
        for line, quad in zip(data.splitlines(), ox.parse(data, format=ox.RdfFormat.N_QUADS)):
            if quad.subject.__class__ is ox.BlankNode or quad.object.__class__ is ox.BlankNode:
                raise SystemExit("bnode")
            rendered = f"{quad.subject} {quad.predicate} {quad.object} {quad.graph_name} ."
            if rendered.encode("utf-8") != line:
                raise SystemExit(f"noncanonical: {line!r} != {rendered!r}")
        digest.hexdigest()
    return total


VARIANTS = {
    "rdflib-stock": rdflib_stock,
    "rdflib-lexical": rdflib_lexical,
    "rdflib-full": rdflib_full,
    "rdflib-profile-only": rdflib_profile_only,
    "oxi-store": oxi_store,
    "oxi-store-bulk": oxi_store_bulk,
    "oxi-parse-count": oxi_parse_count,
    "oxi-store-zstd": oxi_store_zstd,
    "oxi-canonicality": oxi_canonicality,
}


def main() -> None:
    variant = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else None
    paths = _packs(n)
    gc.collect()
    with common.Timer(variant) as t:
        count = VARIANTS[variant](paths)
    common.emit(
        {
            "q": 1,
            "variant": variant,
            "packs": len(paths),
            "quads_declared": _quad_total(paths),
            "quads_seen": count,
            "wall_s": round(t.wall, 3),
            "cpu_s": round(t.cpu, 3),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


if __name__ == "__main__":
    main()

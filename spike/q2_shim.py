"""Q2 -- the shim tax: rdflib's API over oxrdflib's oxigraph-backed store.

    .venv/bin/python spike/q2_shim.py <variant>

Variants pair a *loader* with a *workload* so each process measures one thing:

  load-native / load-oxrdflib-parse / load-oxrdflib-bulk
      how the 1,013,723 staging quads get into each store
  iter-native / iter-oxrdflib
      full-store quad iteration (the thing `_check_graph_roles` used to do twice)
  roles-native / roles-oxrdflib
      validate.py's own `_check_graph_roles` with `asserted_placement=None`,
      i.e. the pre-optimization sweep: one pass over every quad to collect
      per-subject rdf:type sets, then per-subject type-set equality.
  fidelity
      does a term survive the rdflib -> oxigraph -> rdflib round trip?
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402


def _paths() -> list[Path]:
    return sorted(common.decompressed(), key=lambda p: p.stat().st_size)


def _graph_ids():
    from rdflib import URIRef

    return {row["role"]: URIRef(row["id"]) for row in common.manifest()["graphs"]}


def load_native():
    """rdflib Dataset over the default Memory store, validate.py's own parser."""

    import validate as V
    from rdflib import Dataset

    ds = Dataset()
    for p in _paths():
        with p.open("rb") as fh:
            V._parse_nquads_preserving_lexical_forms(ds, fh)
    return ds


def load_oxrdflib_parse():
    """rdflib Dataset whose store is oxrdflib; loaded through the rdflib parser."""

    from rdflib import Dataset

    ds = Dataset(store="Oxigraph")
    for p in _paths():
        with p.open("rb") as fh:
            ds.parse(source=fh, format="nquads")
    return ds


def load_oxrdflib_bulk():
    """pyoxigraph loads natively; rdflib is wrapped around the finished store."""

    import pyoxigraph as ox
    from oxrdflib import OxigraphStore
    from rdflib import Dataset

    inner = ox.Store()
    for p in _paths():
        with p.open("rb") as fh:
            inner.load(fh, format=ox.RdfFormat.N_QUADS)
    return Dataset(store=OxigraphStore(store=inner))


LOADERS = {
    "native": load_native,
    "oxrdflib-parse": load_oxrdflib_parse,
    "oxrdflib-bulk": load_oxrdflib_bulk,
}


def workload_iter(ds) -> int:
    return sum(1 for _ in ds.quads((None, None, None, None)))


def workload_roles(ds) -> int:
    import validate as V

    ids = _graph_ids()
    graphs = {role: ds.graph(gid) for role, gid in ids.items()}
    inventory = V._check_graph_roles(graphs, asserted_placement=None)
    return sum(len(nodes) for nodes in inventory.asserted_by_carrier.values())


def fidelity(_ds=None) -> int:
    """Does an rdflib term survive rdflib -> oxigraph -> rdflib unchanged?"""

    from oxrdflib._converter import from_ox, to_ox
    from rdflib import Literal, URIRef, XSD

    # validate.py's parser builds every literal with normalize=False so the
    # publisher's exact lexeme survives into the digests; these cases ask
    # whether that property survives oxrdflib's converter.
    cases = [
        Literal("04", normalize=False),
        Literal("04", datatype=XSD.string, normalize=False),
        Literal("1.00", datatype=XSD.decimal, normalize=False),
        Literal("+1", datatype=XSD.integer, normalize=False),
        Literal("01", datatype=XSD.integer, normalize=False),
        Literal("2026-08-12T00:00:00Z", datatype=XSD.dateTime, normalize=False),
        Literal("TRUE", datatype=XSD.boolean, normalize=False),
        Literal("hello", lang="en", normalize=False),
        Literal('{"a":1}', datatype=URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#JSON"), normalize=False),
    ]
    bad = 0
    for term in cases:
        back = from_ox(to_ox(term))
        same = type(term) is type(back) and str(term) == str(back) and term.datatype == back.datatype and term.language == back.language
        bad += not same
        print(
            f"  {term.n3()[:70]:<72} -> {back.n3()[:70]:<72} {'OK' if same else 'CHANGED'}",
            flush=True,
        )
    return bad


def digest_parity(_ds=None) -> int:
    """Do validate.py's own node digests survive the shim? (rdf_node_digest)"""

    import validate as V
    from rdflib import URIRef

    ids = _graph_ids()
    native = load_native().graph(ids["asserted"])
    shimmed = load_oxrdflib_bulk().graph(ids["asserted"])
    # Sample carriers that actually carry a stored contentDigest, plus a
    # SubjectConcept (which carries plain literals like atlas:notation).
    nodes = [URIRef("http://eurovoc.europa.eu/c_ff983fb3")]
    nodes += [
        n for n, _ in zip(native.subjects(V.RDF.type, V.RKAF.EvidenceBinding), range(3))
    ]
    nodes += [n for n, _ in zip(native.subjects(V.RDF.type, V.ATLAS.SourceRecord), range(3))]
    mismatches = 0
    for node in nodes:
        a = V.rdf_node_digest(native, node)
        try:
            b = V.rdf_node_digest(shimmed, node)
        except Exception as exc:  # noqa: BLE001
            b = f"ERROR {exc}"
        same = a == b
        mismatches += not same
        print(f"  {str(node)[:78]:<80} {'SAME' if same else 'DIFFERENT'}", flush=True)
        if not same:
            print(f"    native  {a}\n    shimmed {b}", flush=True)
    return mismatches


def main() -> None:
    variant = sys.argv[1]
    if variant == "digest-parity":
        with common.Timer(variant) as t:
            bad = digest_parity()
        common.emit({"q": 2, "variant": variant, "mismatched_nodes": bad, "wall_s": round(t.wall, 3)})
        return
    if variant == "fidelity":
        with common.Timer(variant) as t:
            bad = fidelity()
        common.emit({"q": 2, "variant": variant, "changed_terms": bad, "wall_s": round(t.wall, 3)})
        return
    kind, _, work = variant.partition("/")
    gc.collect()
    with common.Timer("load") as tl:
        ds = LOADERS[kind]()
    load_rss = common.peak_rss_gb()
    result = None
    tw = None
    if work:
        gc.collect()
        with common.Timer(work) as tw:
            result = {"iter": workload_iter, "roles": workload_roles}[work](ds)
    common.emit(
        {
            "q": 2,
            "variant": variant,
            "load_wall_s": round(tl.wall, 3),
            "load_rss_gb": round(load_rss, 3),
            "work_wall_s": round(tw.wall, 3) if tw else None,
            "work_cpu_s": round(tw.cpu, 3) if tw else None,
            "work_result": result,
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


if __name__ == "__main__":
    main()

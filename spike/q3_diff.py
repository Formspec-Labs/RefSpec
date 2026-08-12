"""Q3b -- WHY do the two substrates disagree? Print the spurious violations."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402
import q2_shim  # noqa: E402

SHAPES = Path(__file__).parent / "pinned-binding-3.1" / "shapes" / "atlas.shacl.ttl"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    all_paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)
    q2_shim._paths = lambda: all_paths[:n]

    import validate as V
    from rdflib import Graph

    if "--patched" in sys.argv:
        import oxrdflib._converter as C
        import oxrdflib.store as S
        import pyoxigraph as ox
        from rdflib import BNode, Literal, URIRef, XSD

        def from_ox(term):
            if term is None:
                return None
            if isinstance(term, ox.Literal):
                if term.language:
                    return Literal(term.value, lang=term.language, normalize=False)
                dt = term.datatype.value
                if dt == str(XSD.string):
                    return Literal(term.value, normalize=False)
                return Literal(term.value, datatype=URIRef(dt), normalize=False)
            if isinstance(term, ox.NamedNode):
                return URIRef(term.value)
            if isinstance(term, ox.BlankNode):
                return BNode(term.value)
            raise ValueError(term)

        C.from_ox = from_ox
        S.from_ox = from_ox

    shapes = Graph()
    shapes.parse(SHAPES, format="turtle")
    for kind in ("native", "oxrdflib-bulk"):
        ds = q2_shim.LOADERS[kind]()
        asserted = ds.graph(q2_shim._graph_ids()["asserted"])
        conforms, _g, report = V._validate_shacl_data(asserted, shapes)
        print(f"\n===== {kind}: conforms={conforms}  report={len(report)} chars =====")
        print("\n".join(report.splitlines()[:40]))


if __name__ == "__main__":
    main()

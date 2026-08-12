"""Q2c -- do validate.py's node digests survive the oxrdflib shim?

`rdf_node_digest` hashes `ntriples_term`-rendered outgoing facts, so any term
the shim reconstructs differently moves a digest that the wire pins. Small
subset (first N packs by size) so this stays cheap.

    .venv/bin/python spike/q2_digest_parity.py [n_packs]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402

ASSERTED = "urn:ref:atlas:graph:v3:asserted"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)[:n]

    import pyoxigraph as ox
    import validate as V
    from oxrdflib import OxigraphStore
    from rdflib import Dataset, URIRef

    patched = "--patched" in sys.argv
    if patched:
        # The cheap half of the shim: rebuild rdflib terms with normalize=False
        # and render oxigraph's xsd:string as the RDF 1.1 simple form.
        import oxrdflib._converter as C
        import oxrdflib.store as S
        from rdflib import BNode, Literal, XSD

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

    native_ds = Dataset()
    for p in paths:
        with p.open("rb") as fh:
            V._parse_nquads_preserving_lexical_forms(native_ds, fh)
    native = native_ds.graph(URIRef(ASSERTED))

    inner = ox.Store()
    for p in paths:
        with p.open("rb") as fh:
            inner.load(fh, format=ox.RdfFormat.N_QUADS)
    shimmed = Dataset(store=OxigraphStore(store=inner)).graph(URIRef(ASSERTED))

    subjects = sorted({s for s in native.subjects(unique=True)}, key=str)
    same = diff = err = 0
    shown = 0
    for node in subjects:
        a = V.rdf_node_digest(native, node)
        try:
            b = V.rdf_node_digest(shimmed, node)
        except Exception as exc:  # noqa: BLE001
            err += 1
            continue
        if a == b:
            same += 1
        else:
            diff += 1
            if shown < 3:
                shown += 1
                print(f"  {node}\n    native  {a}\n    shimmed {b}")
                na = sorted(f"{V.ntriples_term(p)} {V.ntriples_term(o)}" for p, o in native.predicate_objects(node))
                nb = sorted(f"{V.ntriples_term(p)} {V.ntriples_term(o)}" for p, o in shimmed.predicate_objects(node))
                for x, y in zip(na, nb):
                    if x != y:
                        print(f"    fact native  {x[:150]}\n    fact shimmed {y[:150]}")
    common.emit(
        {
            "q": "2c",
            "converter": "patched" if patched else "stock",
            "packs": n,
            "subjects": len(subjects),
            "digest_same": same,
            "digest_different": diff,
            "digest_error": err,
        }
    )


if __name__ == "__main__":
    main()

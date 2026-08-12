"""Q5/Q6 -- what the PORT buys, with no rdflib in the loop.

  roles     `_check_graph_roles`' core loop re-expressed over pyoxigraph terms
  canon     the term-form half of the canonicality proof done on raw BYTES
            (the only way it can be done once oxigraph owns the term model)

    .venv/bin/python spike/q5_native_port.py <roles|canon> [n_packs|full]
"""

from __future__ import annotations

import gc
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402

ASSERTED = "urn:ref:atlas:graph:v3:asserted"
FULL_ROOT = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec/output/atlas-3.1-full-2026-08-12")


def _paths(argv: list[str]) -> list[Path]:
    paths = sorted(common.decompressed(), key=lambda p: p.stat().st_size)
    return paths if len(argv) < 3 else paths[: int(argv[2])]


def roles(argv: list[str]) -> None:
    """Same algorithm as `_AssertedPlacementObservation` + the type-set pass."""

    import pyoxigraph as ox
    import validate as V

    paths = _paths(argv)
    store = ox.Store()
    with common.Timer("load") as tl:
        for p in paths:
            with p.open("rb") as fh:
                store.load(fh, format=ox.RdfFormat.N_QUADS)

    RDF_TYPE = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    graph = ox.NamedNode(ASSERTED)
    allowed_predicates = {ox.NamedNode(str(p)) for p in V.ALLOWED_ASSERTED_PREDICATES}
    projection_only = {ox.NamedNode(str(p)) for p in V._projection_only_predicates()}
    allowed_types = {ox.NamedNode(str(t)) for t in V.ALLOWED_ASSERTED_TYPES}
    carrier_types = {ox.NamedNode(str(t)) for t in V.ASSERTED_CARRIER_TYPES}
    resource_types = {ox.NamedNode(str(t)) for t in V.RESOURCE_TYPES}
    assertion_types = {ox.NamedNode(str(t)) for t in V.ASSERTION_TYPES}
    ATLAS_RESOURCE = ox.NamedNode(str(V.ATLAS.AtlasResource))
    SKOS_CONCEPT = ox.NamedNode(str(V.SKOS.Concept))
    SUBJECT_CONCEPT = ox.NamedNode(str(V.ATLAS.SubjectConcept))
    VALUE_RESOURCE = ox.NamedNode(str(V.ATLAS.ValueResource))
    SCHEME = ox.NamedNode(str(V.ATLAS.ResourceScheme))
    SKOS_SCHEME = ox.NamedNode(str(V.SKOS.ConceptScheme))
    RELATION_ASSERTION = ox.NamedNode(str(V.ATLAS.RelationAssertion))
    MAPPING_ASSERTION = ox.NamedNode(str(V.ATLAS.MappingAssertion))
    SKOS_MAPPING_ASSERTION = ox.NamedNode(str(V.ATLAS.SkosMappingAssertion))
    PROFILE = ox.NamedNode(str(V.ATLAS.resourceProfile))
    CONCEPT_SCHEME_PROFILE = ox.NamedNode(str(V.ATLAS.conceptScheme))
    IN_SCHEME = ox.NamedNode(str(V.SKOS.inScheme))
    SEMANTIC_RING = ox.NamedNode(str(V.ATLAS.semanticRing))
    SUBJECT_RING = ox.NamedNode(str(V.ATLAS.subject))

    gc.collect()
    problems: list[str] = []
    with common.Timer("sweep") as t:
        types: dict[object, list] = {}
        verdicts: dict[object, int] = {}
        for q in store.quads_for_pattern(None, None, None, graph):
            p = q.predicate
            v = verdicts.get(p)
            if v is None:
                v = 1 if p == RDF_TYPE else (2 if p in projection_only else (0 if p in allowed_predicates else 3))
                verdicts[p] = v
            s = q.subject
            if v == 1:
                types.setdefault(s, []).append(q.object)
            else:
                types.setdefault(s, [])
                if v and not problems:
                    problems.append(f"placement {v} on {s} via {p}")
        carriers: dict[object, set] = {t: set() for t in carrier_types}
        while types:
            subject, declared = types.popitem()
            ts = set(declared)
            if ts - allowed_types and not problems:
                problems.append(f"unsupported type on {subject}")
            found = ts & carrier_types
            if len(found) != 1:
                if not problems:
                    problems.append(f"{subject} has {len(found)} carrier types")
                continue
            carrier = next(iter(found))
            carriers[carrier].add(subject)
            expected = {carrier}
            if carrier in resource_types:
                expected.add(ATLAS_RESOURCE)
                if carrier == SUBJECT_CONCEPT or (carrier == VALUE_RESOURCE and SKOS_CONCEPT in ts):
                    expected.add(SKOS_CONCEPT)
            elif carrier == SCHEME:
                profiles = {x.object for x in store.quads_for_pattern(subject, PROFILE, None, graph)}
                if profiles == {CONCEPT_SCHEME_PROFILE} or any(
                    store.quads_for_pattern(None, IN_SCHEME, subject, graph)
                ):
                    expected.add(SKOS_SCHEME)
            elif carrier in assertion_types:
                expected.add(RELATION_ASSERTION)
                if carrier == MAPPING_ASSERTION and {
                    x.object for x in store.quads_for_pattern(subject, SEMANTIC_RING, None, graph)
                } == {SUBJECT_RING}:
                    expected.add(SKOS_MAPPING_ASSERTION)
            if ts != expected and not problems:
                problems.append(f"{subject} type set differs")
    common.emit(
        {
            "q": "5-port",
            "probe": "roles-oxigraph-native",
            "packs": len(paths),
            "load_wall_s": round(tl.wall, 3),
            "sweep_wall_s": round(t.wall, 3),
            "carriers": sum(len(v) for v in carriers.values()),
            "problems": problems[:2],
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


# One strict line form for the Atlas canonical N-Quads profile. This is the
# term-form proof (`original != nquads_line(...)`) expressed on bytes, which is
# what a port must do because oxigraph's term model cannot tell `"x"` from
# `"x"^^xsd:string`.
_IRI = rb"<[^\x00-\x20<>\"{}|^`\\]*>"
_ESC = rb'(?:[^"\\\x00-\x1f\x7f]|\\[tbnrf"\\]|\\u[0-9A-F]{4}|\\U[0-9A-F]{8})*'
_LIT = rb'"' + _ESC + rb'"(?:@[a-zA-Z]+(?:-[a-zA-Z0-9]+)*|\^\^' + _IRI + rb")?"
CANONICAL_LINE = re.compile(rb"^" + _IRI + rb" " + _IRI + rb" (?:" + _IRI + rb"|" + _LIT + rb") " + _IRI + rb" \.$")


def canon(argv: list[str]) -> None:
    import hashlib

    full = "full" in argv[2:]
    if full:
        try:
            from compression import zstd
        except ImportError:
            from backports import zstd
        packs = json.loads((FULL_ROOT / "atlas-manifest.json").read_bytes())["packs"]
        opener = [(FULL_ROOT / p["path"], p) for p in packs]
    else:
        opener = [(p, None) for p in _paths(argv)]

    total = bad = 0
    with common.Timer("canon") as t:
        for path, pack in opener:
            digest = hashlib.sha256()
            previous = b""
            if pack is not None:
                fh = zstd.open(path, "rb")
            else:
                fh = path.open("rb")
            with fh:
                for line in fh:
                    digest.update(line)
                    total += 1
                    content = line[:-1]
                    if b"\r" in line or not content or content != content.strip():
                        bad += 1
                        continue
                    if line <= previous:
                        bad += 1
                    previous = line
                    if not CANONICAL_LINE.match(content):
                        bad += 1
            if pack is not None and "sha256:" + digest.hexdigest() != pack["content"]["digest"]:
                bad += 1
    common.emit(
        {
            "q": "5-port",
            "probe": "canonicality-on-bytes",
            "scope": "full" if full else f"{len(opener)} staging packs",
            "lines": total,
            "rejected": bad,
            "wall_s": round(t.wall, 2),
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )


def main() -> None:
    {"roles": roles, "canon": canon}[sys.argv[1]](sys.argv)


if __name__ == "__main__":
    main()

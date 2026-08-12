"""Q4 -- the port specimen: `_check_label_integrity` in pyoxigraph SPARQL.

The Python original (validate.py:5602-5665, 64 lines) enforces six cross-record
SKOS-XL invariants per resource.  This file ports all six to SPARQL over a
native pyoxigraph Store and measures both against the same data, then against
the same data plus one injected violation.

    .venv/bin/python spike/q4_label_port.py <python|sparql> [--inject ROLE]

ROLE is one of: preflabel-language, role-node-reuse, role-literal-reuse,
release-mismatch, orphan-source-record, two-literal-forms.
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "pinned-binding-3.1" / "tools"))

import common  # noqa: E402

ASSERTED = "urn:ref:atlas:graph:v3:asserted"
ATLAS = "https://refspec.org/ns/atlas/v3#"
XL = "http://www.w3.org/2008/05/skos-xl#"

PREAMBLE = f"""
PREFIX atlas: <{ATLAS}>
PREFIX xl: <{XL}>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""
RESOURCE_TYPES = "VALUES ?rt { atlas:SubjectConcept atlas:EntityResource atlas:ValueResource atlas:LegalIdentityResource }"
ROLES = "VALUES ?role { xl:prefLabel xl:altLabel xl:hiddenLabel }"

# --- the ported check, one query per invariant, each returning the first
# --- offending binding in the canonical (lexicographic-min) order.
QUERIES: dict[str, str] = {
    # (1) resource release must exist and be unique  [_one(..., inRelease)]
    "resource-release-not-one": f"""{PREAMBLE}
SELECT ?r WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  OPTIONAL {{ ?r atlas:inRelease ?rel }}
}} }} GROUP BY ?r HAVING (COUNT(DISTINCT ?rel) != 1) ORDER BY ?r LIMIT 1""",
    # (2) label release differs from its resource
    "label-release-differs": f"""{PREAMBLE}
SELECT ?r ?l WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  ?r ?role ?l . {ROLES}
  ?r atlas:inRelease ?rel
  FILTER ( NOT EXISTS {{ ?l atlas:inRelease ?rel }}
           || EXISTS {{ ?l atlas:inRelease ?other . FILTER (?other != ?rel) }} )
}} }} ORDER BY ?l LIMIT 1""",
    # (3) label shares no SourceRecord with its resource
    "label-shares-no-source-record": f"""{PREAMBLE}
SELECT ?r ?l WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  ?r ?role ?l . {ROLES}
  FILTER NOT EXISTS {{ ?r atlas:sourceRecord ?sr . ?l atlas:sourceRecord ?sr }}
}} }} ORDER BY ?l LIMIT 1""",
    # (4) label literalForm must exist and be unique, and be a literal
    "label-literal-form-not-one": f"""{PREAMBLE}
SELECT ?l WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  ?r ?role ?l . {ROLES}
  OPTIONAL {{ ?l xl:literalForm ?lit }}
}} }} GROUP BY ?l
  HAVING (COUNT(DISTINCT ?lit) != 1 || SUM(IF(isLiteral(?lit), 0, 1)) > 0)
  ORDER BY ?l LIMIT 1""",
    # (5) at most one preferred label per language  <- the named specimen
    "preflabel-language-collision": f"""{PREAMBLE}
SELECT ?r ?lang WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  ?r xl:prefLabel ?l .
  ?l xl:literalForm ?lit
}} }} GROUP BY ?r (LCASE(LANG(?lit)) AS ?lang)
  HAVING (COUNT(DISTINCT ?lit) > 1) ORDER BY ?r LIMIT 1""",
    # (6a) the same label NODE used in two XL roles on one resource
    "role-node-reuse": f"""{PREAMBLE}
SELECT ?r ?l WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  ?r ?role1 ?l . ?r ?role2 ?l .
  VALUES (?role1 ?role2) {{
    (xl:prefLabel xl:altLabel) (xl:prefLabel xl:hiddenLabel) (xl:altLabel xl:hiddenLabel) }}
}} }} ORDER BY ?r LIMIT 1""",
    # (6b) the same LITERAL used in two XL roles on one resource
    "role-literal-reuse": f"""{PREAMBLE}
SELECT ?r ?lit WHERE {{ GRAPH <{ASSERTED}> {{
  ?r rdf:type ?rt . {RESOURCE_TYPES}
  ?r ?role1 ?l1 . ?l1 xl:literalForm ?lit .
  ?r ?role2 ?l2 . ?l2 xl:literalForm ?lit .
  VALUES (?role1 ?role2) {{
    (xl:prefLabel xl:altLabel) (xl:prefLabel xl:hiddenLabel) (xl:altLabel xl:hiddenLabel) }}
}} }} ORDER BY ?r LIMIT 1""",
}

# One injected quad set per failure mode. `R` is a real staging SubjectConcept.
R = "http://eurovoc.europa.eu/c_ff983fb3"
R_LABEL = "urn:ref:atlas-label:afa3809db3bf70735a0d3d26d68ec53128ebc882daded57c1ad68b3857fb8402"
R_RELEASE = "urn:ref:atlas-release:3:eurovoc:4.24"
R_RECORD = "urn:ref:atlas-source-record:873449b02874db70f6c065faacac92836fccb0d2747205cd829ad7d5680bcd27"
NEW = "urn:ref:atlas-label:0000000000000000000000000000000000000000000000000000000000000001"

INJECTIONS = {
    # a second English prefLabel on a resource that already has one
    "preflabel-language": [
        f"<{R}> <{XL}prefLabel> <{NEW}> <{ASSERTED}> .",
        f"<{NEW}> <{ATLAS}inRelease> <{R_RELEASE}> <{ASSERTED}> .",
        f"<{NEW}> <{ATLAS}sourceRecord> <{R_RECORD}> <{ASSERTED}> .",
        f'<{NEW}> <{XL}literalForm> "user authorisation (duplicate)"@en <{ASSERTED}> .',
        f"<{NEW}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{XL}Label> <{ASSERTED}> .",
    ],
    # the resource's existing prefLabel node also hung off altLabel
    "role-node-reuse": [f"<{R}> <{XL}altLabel> <{R_LABEL}> <{ASSERTED}> ."],
}


def injected_file(mode: str) -> Path:
    out = common.SCRATCH / "injected"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{mode}.nq"
    path.write_text("\n".join(sorted(INJECTIONS[mode])) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------ python side


def run_python(extra: Path | None) -> list[str]:
    import validate as V
    from rdflib import Dataset, URIRef

    ds = Dataset()
    for p in sorted(common.decompressed(), key=lambda q: q.stat().st_size):
        with p.open("rb") as fh:
            V._parse_nquads_preserving_lexical_forms(ds, fh)
    if extra is not None:
        with extra.open("rb") as fh:
            V._parse_nquads_preserving_lexical_forms(ds, fh)
    asserted = ds.graph(URIRef(ASSERTED))
    gc.collect()
    with common.Timer("python") as t:
        try:
            V._check_label_integrity(asserted, None)
            issues: list[str] = []
        except V.AtlasValidationError as exc:
            issues = [f"{exc.code}: {exc.detail}"]
    common.emit(
        {
            "q": 4,
            "impl": "python",
            "injected": extra.stem if extra else None,
            "wall_s": round(t.wall, 3),
            "issues": issues,
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )
    return issues


# ----------------------------------------------------------------- sparql side


def run_sparql(extra: Path | None) -> list[str]:
    import pyoxigraph as ox

    store = ox.Store()
    for p in sorted(common.decompressed(), key=lambda q: q.stat().st_size):
        with p.open("rb") as fh:
            store.load(fh, format=ox.RdfFormat.N_QUADS)
    if extra is not None:
        store.load(extra.read_bytes(), format=ox.RdfFormat.N_QUADS)
    gc.collect()
    issues: list[str] = []
    per_query: dict[str, float] = {}
    with common.Timer("sparql") as t:
        for name, query in QUERIES.items():
            with common.Timer(name) as tq:
                rows = list(store.query(query))
            per_query[name] = round(tq.wall, 3)
            if rows:
                binding = " ".join(str(v) for v in rows[0] if v is not None)
                issues.append(f"dataset.label-integrity/{name}: {binding}")
    common.emit(
        {
            "q": 4,
            "impl": "sparql",
            "injected": extra.stem if extra else None,
            "wall_s": round(t.wall, 3),
            "per_query_s": per_query,
            "issues": issues,
            "peak_rss_gb": round(common.peak_rss_gb(), 3),
        }
    )
    return issues


def main() -> None:
    impl = sys.argv[1]
    extra = injected_file(sys.argv[2]) if len(sys.argv) > 2 else None
    (run_python if impl == "python" else run_sparql)(extra)


if __name__ == "__main__":
    main()

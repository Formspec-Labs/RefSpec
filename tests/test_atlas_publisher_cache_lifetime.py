"""Publisher type indexes agree with the old reader without retaining old views."""

import weakref
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import pytest
from rdflib import Graph

from tools import verify_atlas_source_fidelity as v


def _old_subject_types(view, cache):
    # Copied from the former global memo; cache is explicit for test cleanup.
    cached = cache.get(id(view))
    if cached is not None and cached[0] is view:
        return cached[1]
    types = defaultdict(set)
    for subject, predicate, obj in view.iri_claims:
        if predicate == v.RDF_TYPE:
            types[subject].add(obj)
    resolved = {subject: frozenset(values) for subject, values in types.items()}
    cache[id(view)] = (view, resolved)
    return resolved


@pytest.mark.parametrize("mutation", ["none", "missing-type", "extra-type", "wrong-predicate"])
@pytest.mark.reads_built_artifact
def test_type_index_matches_old_oracle_on_retained_publisher(mutation):
    path = Path(__file__).parents[1] / "output/registry-real-data-sources/eurovoc-4.24-metadata.ttl"
    assert path.is_file(), "required retained EuroVoc metadata is unavailable"
    view = v._publisher_view(Graph().parse(path, format="turtle"), "eurovoc-metadata")
    claims = set(view.iri_claims)
    typed = next(row for row in claims if row[1] == v.RDF_TYPE)
    if mutation == "missing-type":
        claims.remove(typed)
    elif mutation == "extra-type":
        claims.add((typed[0], v.RDF_TYPE, "urn:test:extra-type"))
    elif mutation == "wrong-predicate":
        claims.remove(typed)
        claims.add((typed[0], "urn:test:not-type", typed[2]))
    view = replace(view, iri_claims=frozenset(claims))
    assert view.subject_types == _old_subject_types(view, {})
    assert view.subject_types is view.subject_types


def test_cached_index_does_not_keep_publisher_alive_and_replace_recomputes():
    view = v._publisher_view(Graph(), "empty")
    assert view.subject_types == {}
    changed = replace(view, iri_claims=frozenset({("urn:s", v.RDF_TYPE, "urn:type")}))
    assert changed.subject_types == {"urn:s": frozenset({"urn:type"})}
    reference = weakref.ref(changed)
    del changed
    assert reference() is None

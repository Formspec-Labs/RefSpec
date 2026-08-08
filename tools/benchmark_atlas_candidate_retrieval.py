"""Benchmark Atlas candidate finders against expert OAEI references.

The tool is intentionally separate from release assembly.  It measures whether
a deterministic finder puts a possible relation in front of the blind judges;
it never admits a mapping.  Sparse runs need only RefSpec dependencies.  Dense
runs additionally need ``fastembed`` and NumPy, for example:

    uv run --with fastembed tools/benchmark_atlas_candidate_retrieval.py ...

Dense score matrices are evaluated in fixed query blocks.  The default block
contains 128 queries, so exact retrieval does not allocate a full
source-by-target score matrix for large vocabularies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from rdflib import OWL, RDF, RDFS, SKOS, BNode, Graph, URIRef

from refspec.atlas.candidate_retrieval import (
    DEFAULT_SPARSE_VIEWS,
    bidirectional_sparse_neighbors,
    graph_neighborhood_neighbors,
    retrieval_digest,
)
from refspec.atlas.qualification import AtlasConcept, AtlasConceptContext
from refspec.storage import canonical_json

CONFERENCE_REFERENCE_NAMES = (
    "cmt-confOf.rdf",
    "cmt-conference.rdf",
    "cmt-edas.rdf",
    "cmt-ekaw.rdf",
    "cmt-iasted.rdf",
    "cmt-sigkdd.rdf",
    "confOf-edas.rdf",
    "confOf-ekaw.rdf",
    "confOf-iasted.rdf",
    "confOf-sigkdd.rdf",
    "conference-confOf.rdf",
    "conference-edas.rdf",
    "conference-ekaw.rdf",
    "conference-iasted.rdf",
    "conference-sigkdd.rdf",
    "edas-ekaw.rdf",
    "edas-iasted.rdf",
    "edas-sigkdd.rdf",
    "ekaw-iasted.rdf",
    "ekaw-sigkdd.rdf",
    "iasted-sigkdd.rdf",
)
CONFERENCE_ONTOLOGY_NAMES = frozenset(
    {part.casefold() for name in CONFERENCE_REFERENCE_NAMES for part in Path(name).stem.split("-", 1)}
)
CONCEPT_TYPES = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property)
PARENT_PREDICATES = (RDFS.subClassOf, RDFS.subPropertyOf)
ALT_LOCAL_NAMES = {
    "altlabel",
    "exactsynonym",
    "hasexactsynonym",
    "hasrelatedsynonym",
    "relatedsynonym",
    "synonym",
}
DEFINITION_LOCAL_NAMES = {
    "comment",
    "definition",
    "iao_0000115",
    "hasdefinition",
}
VIEWS = (
    "label",
    "structured",
    "natural",
    "definition-first",
    "hierarchy",
)
PREFIXES = {
    "symmetric": ("", ""),
    "bge": ("Represent this sentence for searching relevant passages: ", ""),
    "nomic": ("search_query: ", "search_document: "),
    "relation": (
        "Find a concept in another controlled vocabulary that may be equivalent, broader, narrower, or related: ",
        "Controlled-vocabulary concept: ",
    ),
}
DEFAULT_QUERY_BLOCK_SIZE = 128


@dataclass(frozen=True, slots=True)
class AlignmentCase:
    name: str
    sources: tuple[AtlasConcept, ...]
    targets: tuple[AtlasConcept, ...]
    gold: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _PairLayout:
    """Canonical integer layout for one alignment case."""

    name: str
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    gold_indexes: tuple[tuple[int, int], ...]


@dataclass(slots=True)
class _CompactPairRanks:
    """Minimum retained rank per pair without Python tuple candidates."""

    layouts: tuple[_PairLayout, ...]
    ranks: tuple[Any, ...]
    maximum: int
    sentinel: int

    @classmethod
    def empty(cls, cases: Sequence[AlignmentCase], maximum: int) -> _CompactPairRanks:
        import numpy as np

        dtype, sentinel = _rank_dtype(maximum)
        layouts = []
        ranks = []
        for case in sorted(cases, key=lambda value: value.name):
            sources = tuple(sorted(concept.member for concept in case.sources))
            targets = tuple(sorted(concept.member for concept in case.targets))
            if len(sources) != len(set(sources)) or len(targets) != len(set(targets)):
                raise ValueError(f"duplicate member identifier in alignment case {case.name!r}")
            source_indexes = {member: index for index, member in enumerate(sources)}
            target_indexes = {member: index for index, member in enumerate(targets)}
            gold_indexes = tuple(
                sorted((source_indexes[source], target_indexes[target]) for source, target in case.gold)
            )
            layouts.append(_PairLayout(case.name, sources, targets, gold_indexes))
            ranks.append(np.full((len(sources), len(targets)), sentinel, dtype=dtype))
        return cls(tuple(layouts), tuple(ranks), maximum, sentinel)


def _rank_dtype(maximum: int) -> tuple[Any, int]:
    """Return the smallest unsigned rank type with a distinct sentinel."""

    import numpy as np

    if maximum < 1:
        raise ValueError("top-k maximum must be positive")
    for dtype in (np.uint8, np.uint16, np.uint32, np.uint64):
        if maximum < np.iinfo(dtype).max:
            return dtype, maximum + 1
    raise ValueError("top-k maximum is too large for compact rank storage")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_name(value: object) -> str:
    text = str(value)
    return unquote(re.split(r"[/#]", text.rstrip("/#"))[-1]).casefold()


def _fallback_label(identifier: str) -> str:
    tail = unquote(re.split(r"[/#:]+", identifier.rstrip("/#:"))[-1])
    tail = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tail)
    return re.sub(r"[_-]+", " ", tail).strip() or identifier


def _literal_texts(
    graph: Graph,
    subject: URIRef | BNode,
    predicates: Iterable[URIRef],
) -> tuple[str, ...]:
    values = []
    for predicate in predicates:
        for value in graph.objects(subject, predicate):
            if hasattr(value, "language") and value.language not in (None, "en"):
                continue
            text = str(value).strip()
            if text:
                values.append(text)
    return tuple(sorted(set(values)))


def _predicate_values(graph: Graph, subject: URIRef, local_names: set[str]) -> tuple[str, ...]:
    values = []
    for predicate, value in graph.predicate_objects(subject):
        if _local_name(predicate) not in local_names:
            continue
        if isinstance(value, (URIRef, BNode)):
            # OBO-in-OWL serializations frequently point synonym and
            # definition predicates at a description node whose human text is
            # the node's rdfs:label.  The node IRI is provenance, not concept
            # text, so resolve it instead of embedding strings such as
            # ``http://human.owl#genid473``.
            values.extend(
                _literal_texts(
                    graph,
                    value,
                    (RDFS.label, SKOS.prefLabel, SKOS.altLabel),
                )
            )
            continue
        if hasattr(value, "language") and value.language not in (None, "en"):
            continue
        text = str(value).strip()
        if text:
            values.append(text)
    return tuple(sorted(set(values)))


def _concepts_from_graph(
    path: Path,
    *,
    release: str,
    required: Iterable[str] = (),
) -> tuple[AtlasConcept, ...]:
    graph = Graph()
    graph.parse(path)
    members = {
        str(subject)
        for concept_type in CONCEPT_TYPES
        for subject in graph.subjects(RDF.type, concept_type)
        if isinstance(subject, URIRef)
    }
    members.update(required)
    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    for predicate in PARENT_PREDICATES:
        for child, parent in graph.subject_objects(predicate):
            if not isinstance(child, URIRef) or not isinstance(parent, URIRef):
                continue
            if str(child) in members and str(parent) in members:
                parents[str(child)].add(str(parent))
                children[str(parent)].add(str(child))

    facts: dict[str, dict[str, Any]] = {}
    for member in sorted(members):
        subject = URIRef(member)
        preferred = _literal_texts(graph, subject, (RDFS.label, SKOS.prefLabel))
        alternates = set(_literal_texts(graph, subject, (SKOS.altLabel,)))
        alternates.update(_predicate_values(graph, subject, ALT_LOCAL_NAMES))
        definitions = _predicate_values(graph, subject, DEFINITION_LOCAL_NAMES)
        facts[member] = {
            "label": preferred[0] if preferred else _fallback_label(member),
            "alternates": tuple(sorted(alternates - set(preferred))),
            "definition": definitions[0] if definitions else None,
        }

    def context(member: str) -> AtlasConceptContext:
        fact = facts[member]
        return AtlasConceptContext(
            member=member,
            pref_label=fact["label"],
            alt_labels=fact["alternates"],
            definition=fact["definition"],
        )

    return tuple(
        AtlasConcept(
            member=member,
            release=release,
            pref_label=facts[member]["label"],
            alt_labels=facts[member]["alternates"],
            definition=facts[member]["definition"],
            broader=tuple(sorted(parents[member])),
            parents=tuple(context(value) for value in sorted(parents[member])),
            children=tuple(context(value) for value in sorted(children[member])),
        )
        for member in sorted(members)
    )


def _gold(path: Path) -> frozenset[tuple[str, str]]:
    root = ET.parse(path).getroot()
    resource = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
    pairs = set()
    for cell in root.iter():
        if cell.tag.rsplit("}", 1)[-1] != "Cell":
            continue
        left = next(
            (child.get(resource) for child in cell if child.tag.rsplit("}", 1)[-1] == "entity1"),
            None,
        )
        right = next(
            (child.get(resource) for child in cell if child.tag.rsplit("}", 1)[-1] == "entity2"),
            None,
        )
        if left and right:
            pairs.add((left, right))
    return frozenset(pairs)


def _case_digest(cases: Sequence[AlignmentCase]) -> dict[str, str]:
    corpus = [
        {
            "name": case.name,
            "sources": [_concept_record(value) for value in case.sources],
            "targets": [_concept_record(value) for value in case.targets],
        }
        for case in cases
    ]
    gold = [{"name": case.name, "pairs": [list(pair) for pair in sorted(case.gold)]} for case in cases]
    return {
        "corpus": "sha256:" + hashlib.sha256(canonical_json(corpus).encode()).hexdigest(),
        "gold": "sha256:" + hashlib.sha256(canonical_json(gold).encode()).hexdigest(),
    }


def _concept_record(concept: AtlasConcept) -> dict[str, object]:
    return {
        "member": concept.member,
        "label": concept.pref_label,
        "alternates": list(concept.alt_labels),
        "definition": concept.definition,
        "parents": [value.member for value in concept.parents],
        "children": [value.member for value in concept.children],
    }


def conference_cases(root: Path) -> tuple[AlignmentCase, ...]:
    ontology_paths = {path.stem.casefold(): path for path in (root / "ontologies").glob("*.owl")}
    result = []
    for filename in CONFERENCE_REFERENCE_NAMES:
        reference = root / "references" / filename
        left_name, right_name = reference.stem.split("-", 1)
        gold = _gold(reference)
        left_required = {left for left, _ in gold}
        right_required = {right for _, right in gold}
        sources = _concepts_from_graph(
            ontology_paths[left_name.casefold()],
            release=f"urn:oaei:conference:{left_name}",
            required=left_required,
        )
        targets = _concepts_from_graph(
            ontology_paths[right_name.casefold()],
            release=f"urn:oaei:conference:{right_name}",
            required=right_required,
        )
        result.append(AlignmentCase(reference.stem, sources, targets, gold))
    return tuple(result)


def anatomy_cases(root: Path) -> tuple[AlignmentCase, ...]:
    gold = _gold(root / "anatomy-reference.rdf")
    sources = _concepts_from_graph(
        root / "anatomy-source.owl",
        release="urn:oaei:anatomy:mouse",
        required={left for left, _ in gold},
    )
    targets = _concepts_from_graph(
        root / "anatomy-target.owl",
        release="urn:oaei:anatomy:human",
        required={right for _, right in gold},
    )
    return (AlignmentCase("anatomy", sources, targets, gold),)


def _atlas_context(value: Mapping[str, Any]) -> AtlasConceptContext:
    return AtlasConceptContext(
        member=str(value["member"]),
        pref_label=str(value["prefLabel"]),
        alt_labels=tuple(value.get("altLabels", ())),
        definition=value.get("definition"),
        scope_note=value.get("scopeNote"),
    )


def _atlas_concept(value: Mapping[str, Any]) -> AtlasConcept:
    return AtlasConcept(
        member=str(value["member"]),
        release=str(value["release"]),
        pref_label=str(value["prefLabel"]),
        alt_labels=tuple(value.get("altLabels", ())),
        definition=value.get("definition"),
        scope_note=value.get("scopeNote"),
        broader=tuple(value.get("broader", ())),
        vocabulary=str(value.get("vocabulary", "")),
        parents=tuple(_atlas_context(item) for item in value.get("parents", ())),
        children=tuple(_atlas_context(item) for item in value.get("children", ())),
    )


def atlas_cases(root: Path) -> tuple[AlignmentCase, ...]:
    production = root / "qualification-production"
    baseline = root / "qualification-baseline"
    result = []
    for directory in sorted(path for path in production.iterdir() if path.is_dir()):
        source_payload = json.loads((directory / "concepts-source.json").read_text())
        target_payload = json.loads((directory / "concepts-target.json").read_text())
        gold: set[tuple[str, str]] = set()
        baseline_directory = baseline / directory.name
        if baseline_directory.is_dir():
            receipt = json.loads((baseline_directory / "qualification-receipt.json").read_text())
            admitted = {
                str(row["candidateId"])
                for row in receipt["candidateAccounting"]
                if row.get("disposition") == "admitted"
            }
            bundle = json.loads((baseline_directory / "crosswalk-bundle.json").read_text())
            gold.update(
                (str(row["sourceMember"]), str(row["targetMember"]))
                for row in bundle["mappingCandidates"]
                if row["id"] in admitted
            )
        result.append(
            AlignmentCase(
                directory.name,
                tuple(_atlas_concept(value) for value in source_payload["concepts"]),
                tuple(_atlas_concept(value) for value in target_payload["concepts"]),
                frozenset(gold),
            )
        )
    return tuple(result)


def _normalized_label(value: str) -> str:
    return " ".join(
        token for token in re.split(r"[^0-9a-z]+", unicodedata.normalize("NFKC", value).casefold()) if token
    )


def _exact_label_anchors(case: AlignmentCase) -> set[tuple[str, str]]:
    targets: dict[str, list[str]] = defaultdict(list)
    for concept in case.targets:
        for label in (concept.pref_label, *concept.alt_labels):
            targets[_normalized_label(label)].append(concept.member)
    return {
        (source.member, target)
        for source in case.sources
        for label in (source.pref_label, *source.alt_labels)
        for target in targets.get(_normalized_label(label), ())
    }


def _pair_set_digest(pairs: Iterable[tuple[str, str, str]]) -> str:
    digest = hashlib.sha256()
    for case, source, target in sorted(pairs):
        digest.update(f"{case}\t{source}\t{target}\n".encode())
    return "sha256:" + digest.hexdigest()


def _pair_set_summary(
    pairs: set[tuple[str, str, str]],
    gold: set[tuple[str, str, str]],
    *,
    include_misses: bool = False,
) -> dict[str, object]:
    found = pairs & gold
    result: dict[str, object] = {
        "candidates": len(pairs),
        "found": len(found),
        "recall": round(len(found) / len(gold), 8),
        "pairSetDigest": _pair_set_digest(pairs),
    }
    if include_misses:
        result["missedGold"] = [
            {"case": case, "source": source, "target": target} for case, source, target in sorted(gold - found)
        ]
    return result


def _compact_ranks_from_pairs(
    cases: Sequence[AlignmentCase],
    pair_ranks: Mapping[tuple[str, str, str], int],
    maximum: int,
) -> _CompactPairRanks:
    """Encode retained string triples once as a compact minimum-rank matrix."""

    index = _CompactPairRanks.empty(cases, maximum)
    layouts = {layout.name: (case_index, layout) for case_index, layout in enumerate(index.layouts)}
    source_indexes = {
        layout.name: {member: member_index for member_index, member in enumerate(layout.sources)}
        for layout in index.layouts
    }
    target_indexes = {
        layout.name: {member: member_index for member_index, member in enumerate(layout.targets)}
        for layout in index.layouts
    }
    for (case_name, source, target), rank in pair_ranks.items():
        case_index, _layout = layouts[case_name]
        source_index = source_indexes[case_name][source]
        target_index = target_indexes[case_name][target]
        index.ranks[case_index][source_index, target_index] = rank
    return index


def _compact_pair_summary(
    indexes: Sequence[_CompactPairRanks],
    *,
    top_k: int,
    include_misses: bool = False,
) -> dict[str, object]:
    """Summarize an arm union directly from compact rank matrices."""

    import numpy as np

    if not indexes:
        raise ValueError("at least one compact rank index is required")
    layouts = indexes[0].layouts
    if any(index.layouts != layouts for index in indexes[1:]):
        raise ValueError("compact rank indexes do not share a canonical layout")
    if any(top_k > index.maximum for index in indexes):
        raise ValueError("requested top-k exceeds a compact rank index maximum")

    digest = hashlib.sha256()
    candidate_count = 0
    found_count = 0
    missed: list[tuple[str, str, str]] = []
    gold_count = sum(len(layout.gold_indexes) for layout in layouts)
    for case_index, layout in enumerate(layouts):
        combined = indexes[0].ranks[case_index].copy()
        for index in indexes[1:]:
            np.minimum(combined, index.ranks[case_index], out=combined)
        candidate_count += int(np.count_nonzero(combined <= top_k))
        for source_index, source in enumerate(layout.sources):
            target_indexes = np.flatnonzero(combined[source_index] <= top_k)
            for target_index in target_indexes.tolist():
                digest.update(f"{layout.name}\t{source}\t{layout.targets[target_index]}\n".encode())
        for source_index, target_index in layout.gold_indexes:
            if combined[source_index, target_index] <= top_k:
                found_count += 1
            elif include_misses:
                missed.append((layout.name, layout.sources[source_index], layout.targets[target_index]))

    result: dict[str, object] = {
        "candidates": candidate_count,
        "found": found_count,
        "recall": round(found_count / gold_count, 8),
        "pairSetDigest": "sha256:" + digest.hexdigest(),
    }
    if include_misses:
        result["missedGold"] = [
            {"case": case, "source": source, "target": target} for case, source, target in sorted(missed)
        ]
    return result


def sparse_benchmark(
    cases: Sequence[AlignmentCase],
    top_ks: Sequence[int],
) -> tuple[dict[str, object], dict[tuple[str, str, str], int]]:
    maximum = max(top_ks)
    view_pairs: dict[str, dict[str, set[tuple[str, str]]]] = {view.name: {} for view in DEFAULT_SPARSE_VIEWS}
    view_hits: dict[str, list[Any]] = {view.name: [] for view in DEFAULT_SPARSE_VIEWS}
    exact_graph_pairs: dict[str, set[tuple[str, str]]] = {}
    mutual_graph_pairs: dict[str, set[tuple[str, str]]] = {}
    started = time.monotonic()
    for case in cases:
        exact_anchors = _exact_label_anchors(case)
        mutual_anchors = set(exact_anchors)
        for view in DEFAULT_SPARSE_VIEWS:
            hits = bidirectional_sparse_neighbors(
                case.sources,
                case.targets,
                view=view,
                top_k=maximum,
            )
            view_hits[view.name].extend(hits)
            view_pairs[view.name][case.name] = {hit.key for hit in hits}
            mutual_anchors.update(hit.key for hit in hits if hit.source_rank == 1 and hit.target_rank == 1)
        exact_graph = graph_neighborhood_neighbors(case.sources, case.targets, exact_anchors)
        mutual_graph = graph_neighborhood_neighbors(case.sources, case.targets, mutual_anchors)
        exact_graph_pairs[case.name] = {hit.key for hit in exact_graph}
        mutual_graph_pairs[case.name] = {hit.key for hit in mutual_graph}

    results = []
    retained: dict[tuple[str, str, str], int] = {}
    gold = {(case.name, source, target) for case in cases for source, target in case.gold}
    for top_k in top_ks:
        per_view: dict[str, set[tuple[str, str, str]]] = {}
        for view in DEFAULT_SPARSE_VIEWS:
            selected = {
                (case.name, hit.source_member, hit.target_member)
                for case in cases
                for hit in view_hits[view.name]
                if hit.key in view_pairs[view.name][case.name]
                and ((hit.source_rank or maximum + 1) <= top_k or (hit.target_rank or maximum + 1) <= top_k)
            }
            per_view[view.name] = selected
        sparse_union = set().union(*per_view.values())
        exact_graph_union = set(sparse_union)
        exact_graph_union.update(
            (case.name, source, target) for case in cases for source, target in exact_graph_pairs[case.name]
        )
        mutual_graph_union = set(sparse_union)
        mutual_graph_union.update(
            (case.name, source, target) for case in cases for source, target in mutual_graph_pairs[case.name]
        )
        for pair in mutual_graph_union:
            retained[pair] = min(retained.get(pair, maximum + 1), top_k)
        results.append(
            {
                "topK": top_k,
                "views": {
                    name: {
                        "candidates": len(pairs),
                        "found": len(pairs & gold),
                        "recall": round(len(pairs & gold) / len(gold), 8),
                    }
                    for name, pairs in per_view.items()
                },
                "sparseUnion": _pair_set_summary(sparse_union, gold),
                "unionWithExactAnchorGraph": _pair_set_summary(exact_graph_union, gold),
                "unionWithMutualTop1Graph": _pair_set_summary(mutual_graph_union, gold),
            }
        )
    return (
        {
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "results": results,
            "digests": {name: retrieval_digest(tuple(hits)) for name, hits in view_hits.items()},
        },
        retained,
    )


def _embedding_text(concept: AtlasConcept, view: str) -> str:
    alternates = "; ".join(concept.alt_labels)
    parents = "; ".join(item.pref_label for item in concept.parents)
    children = "; ".join(item.pref_label for item in concept.children)
    definition = concept.definition or ""
    if view == "label":
        return "; ".join(value for value in (concept.pref_label, alternates) if value)
    if view == "definition-first":
        return f"Definition: {definition}\nConcept: {concept.pref_label}\nAlternate labels: {alternates}"
    if view == "hierarchy":
        return f"Concept: {concept.pref_label}\nBroader concepts: {parents}\nNarrower concepts: {children}"
    if view == "natural":
        return (
            f"The controlled-vocabulary concept is {concept.pref_label}. "
            f"Its alternate labels are {alternates or 'not supplied'}. "
            f"Its definition is {definition or 'not supplied'}. "
            f"Its broader concepts are {parents or 'not supplied'}, and its narrower concepts are "
            f"{children or 'not supplied'}. Its local identifier is {_fallback_label(concept.member)}."
        )
    if view == "structured":
        return (
            f"label: {concept.pref_label}\nalternate labels: {alternates}\nidentifier: "
            f"{_fallback_label(concept.member)}\ndefinition: {definition}\nbroader: {parents}\nnarrower: {children}"
        )
    raise ValueError(f"unsupported embedding view {view!r}")


def _normalize_rows(values: Any) -> Any:
    import numpy as np

    matrix = np.asarray(values, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def _matrix_candidate_ranks(
    source_ids: Sequence[str],
    target_ids: Sequence[str],
    source_query: Any,
    target_document: Any,
    target_query: Any,
    source_document: Any,
    top_k: int,
    *,
    query_block_size: int,
) -> Any:
    """Return exact bidirectional ranks with canonical member tie ordering."""

    import numpy as np

    if query_block_size < 1:
        raise ValueError("query block size must be positive")
    source_query = np.asarray(source_query)
    target_document = np.asarray(target_document)
    target_query = np.asarray(target_query)
    source_document = np.asarray(source_document)
    if source_query.shape[0] != len(source_ids) or source_document.shape[0] != len(source_ids):
        raise ValueError("source identifiers and embedding rows differ")
    if target_query.shape[0] != len(target_ids) or target_document.shape[0] != len(target_ids):
        raise ValueError("target identifiers and embedding rows differ")

    dtype, sentinel = _rank_dtype(top_k)
    ranks = np.full((len(source_ids), len(target_ids)), sentinel, dtype=dtype)
    source_canonical_order = np.asarray(
        sorted(range(len(source_ids)), key=lambda index: source_ids[index]),
        dtype=np.intp,
    )
    target_canonical_order = np.asarray(
        sorted(range(len(target_ids)), key=lambda index: target_ids[index]),
        dtype=np.intp,
    )

    forward_limit = min(top_k, len(target_ids))
    for start in range(0, len(source_ids), query_block_size):
        stop = min(start + query_block_size, len(source_ids))
        scores = source_query[start:stop] @ target_document.T
        canonical_scores = scores[:, target_canonical_order]
        canonical_ranks = np.argsort(-canonical_scores, axis=1, kind="stable")[:, :forward_limit]
        target_indexes = target_canonical_order[canonical_ranks]
        for local_source_index, selected_targets in enumerate(target_indexes):
            source_index = start + local_source_index
            ranks[source_index, selected_targets] = np.arange(1, forward_limit + 1, dtype=dtype)

    reverse_limit = min(top_k, len(source_ids))
    for start in range(0, len(target_ids), query_block_size):
        stop = min(start + query_block_size, len(target_ids))
        scores = target_query[start:stop] @ source_document.T
        canonical_scores = scores[:, source_canonical_order]
        canonical_ranks = np.argsort(-canonical_scores, axis=1, kind="stable")[:, :reverse_limit]
        source_indexes = source_canonical_order[canonical_ranks]
        for local_target_index, selected_sources in enumerate(source_indexes):
            target_index = start + local_target_index
            reverse_ranks = np.arange(1, reverse_limit + 1, dtype=dtype)
            ranks[selected_sources, target_index] = np.minimum(ranks[selected_sources, target_index], reverse_ranks)
    return ranks


def _rank_matrix_metrics(ranks: Any, layout: _PairLayout, top_k: int) -> tuple[int, int]:
    import numpy as np

    candidates = int(np.count_nonzero(ranks <= top_k))
    found = sum(1 for source, target in layout.gold_indexes if ranks[source, target] <= top_k)
    return candidates, found


def dense_benchmark(
    cases: Sequence[AlignmentCase],
    *,
    model_name: str,
    views: Sequence[str],
    prefix_mode: str,
    top_ks: Sequence[int],
    query_block_size: int = DEFAULT_QUERY_BLOCK_SIZE,
) -> tuple[dict[str, object], _CompactPairRanks]:
    import numpy as np
    from fastembed import TextEmbedding

    query_prefix, document_prefix = PREFIXES[prefix_mode]
    model = TextEmbedding(model_name=model_name)
    maximum = max(top_ks)
    compact = _CompactPairRanks.empty(cases, maximum)
    case_by_name = {case.name: case for case in cases}
    view_metrics = {view: {top_k: [0, 0] for top_k in top_ks} for view in views}
    query_cache: dict[tuple[str, str], Any] = {}
    document_cache: dict[tuple[str, str], Any] = {}

    def embeddings(texts: Sequence[str], *, view: str, query: bool) -> Any:
        cache = query_cache if query else document_cache
        missing = sorted({text for text in texts if (view, text) not in cache})
        if missing:
            prefix = query_prefix if query else document_prefix
            encoder = model.query_embed if query else model.passage_embed
            encoded = _normalize_rows(list(encoder([prefix + text for text in missing])))
            for text, vector in zip(missing, encoded, strict=True):
                cache[(view, text)] = vector
        return np.stack([cache[(view, text)] for text in texts])

    started = time.monotonic()
    for case_index, layout in enumerate(compact.layouts):
        case = case_by_name[layout.name]
        source_by_member = {concept.member: concept for concept in case.sources}
        target_by_member = {concept.member: concept for concept in case.targets}
        sources = tuple(source_by_member[member] for member in layout.sources)
        targets = tuple(target_by_member[member] for member in layout.targets)
        for view in views:
            source_texts = [_embedding_text(concept, view) for concept in sources]
            target_texts = [_embedding_text(concept, view) for concept in targets]
            source_query = embeddings(source_texts, view=view, query=True)
            target_document = embeddings(target_texts, view=view, query=False)
            target_query = embeddings(target_texts, view=view, query=True)
            source_document = embeddings(source_texts, view=view, query=False)
            ranks = _matrix_candidate_ranks(
                layout.sources,
                layout.targets,
                source_query,
                target_document,
                target_query,
                source_document,
                maximum,
                query_block_size=query_block_size,
            )
            for top_k in top_ks:
                candidates, found = _rank_matrix_metrics(ranks, layout, top_k)
                view_metrics[view][top_k][0] += candidates
                view_metrics[view][top_k][1] += found
            np.minimum(compact.ranks[case_index], ranks, out=compact.ranks[case_index])
    vector_hasher = hashlib.sha256()
    for role, cache in (("query", query_cache), ("document", document_cache)):
        for (view, text), vector in sorted(cache.items()):
            vector_hasher.update(f"{role}\t{view}\t{text}\n".encode())
            vector_hasher.update(np.asarray(vector, dtype="<f4").tobytes(order="C"))
    results = []
    gold_count = sum(len(layout.gold_indexes) for layout in compact.layouts)
    for top_k in top_ks:
        union_candidates = 0
        union_found = 0
        for case_index, layout in enumerate(compact.layouts):
            candidates, found = _rank_matrix_metrics(compact.ranks[case_index], layout, top_k)
            union_candidates += candidates
            union_found += found
        results.append(
            {
                "topK": top_k,
                "views": {
                    view: {
                        "candidates": view_metrics[view][top_k][0],
                        "found": view_metrics[view][top_k][1],
                        "recall": round(view_metrics[view][top_k][1] / gold_count, 8),
                    }
                    for view in views
                },
                "viewUnion": {
                    "candidates": union_candidates,
                    "found": union_found,
                    "recall": round(union_found / gold_count, 8),
                },
            }
        )
    return (
        {
            "model": model_name,
            "prefixMode": prefix_mode,
            "views": list(views),
            "vectorDigest": "sha256:" + vector_hasher.hexdigest(),
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "results": results,
        },
        compact,
    )


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--suite", choices=("conference", "anatomy", "atlas"), required=True)
    parser.add_argument("--top-k", type=int, action="append", dest="top_ks")
    parser.add_argument("--fastembed-model", action="append", default=[])
    parser.add_argument("--view", action="append", choices=VIEWS)
    parser.add_argument("--prefix-mode", choices=tuple(PREFIXES), default="symmetric")
    parser.add_argument(
        "--query-block-size",
        type=_positive_integer,
        default=DEFAULT_QUERY_BLOCK_SIZE,
        help="maximum query rows in each exact dense score block (default: 128)",
    )
    parser.add_argument("--skip-sparse", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    top_ks = tuple(sorted(set(args.top_ks or (1, 2, 3, 5, 10, 20, 50, 100))))
    views = tuple(args.view or ("structured",))
    if args.suite == "conference":
        cases = conference_cases(args.root)
    elif args.suite == "anatomy":
        cases = anatomy_cases(args.root)
    else:
        cases = atlas_cases(args.root)
    result: dict[str, object] = {
        "type": "AtlasRelationCandidateBenchmark",
        "schemaVersion": "1.0",
        "suite": args.suite,
        "cases": len(cases),
        "sourceConcepts": sum(len(case.sources) for case in cases),
        "targetConcepts": sum(len(case.targets) for case in cases),
        "goldRelations": sum(len(case.gold) for case in cases),
        "digests": _case_digest(cases),
        "inputFiles": {
            str(path.relative_to(args.root)): _sha256(path)
            for path in sorted(args.root.rglob("*"))
            if path.is_file()
            and (
                (args.suite == "conference" and path.name in CONFERENCE_REFERENCE_NAMES)
                or (
                    args.suite == "conference"
                    and path.parent.name == "ontologies"
                    and path.stem.casefold() in CONFERENCE_ONTOLOGY_NAMES
                )
                or (args.suite == "anatomy" and path.name.startswith("anatomy-"))
                or (
                    args.suite == "atlas"
                    and path.name
                    in {
                        "concepts-source.json",
                        "concepts-target.json",
                        "crosswalk-bundle.json",
                        "qualification-receipt.json",
                    }
                )
            )
        },
        "topK": list(top_ks),
    }
    sparse_pairs: dict[tuple[str, str, str], int] | None = None
    if not args.skip_sparse:
        sparse_report, sparse_pairs = sparse_benchmark(cases, top_ks)
        result["sparse"] = sparse_report
    compact_indexes: list[_CompactPairRanks] = []
    if sparse_pairs is not None and args.fastembed_model:
        compact_indexes.append(_compact_ranks_from_pairs(cases, sparse_pairs, max(top_ks)))
        sparse_pairs = None
    if args.fastembed_model:
        dense_reports = []
        for model in args.fastembed_model:
            report, pairs = dense_benchmark(
                cases,
                model_name=model,
                views=views,
                prefix_mode=args.prefix_mode,
                top_ks=top_ks,
                query_block_size=args.query_block_size,
            )
            dense_reports.append(report)
            compact_indexes.append(pairs)
        result["dense"] = dense_reports
    if compact_indexes:
        result["combinedUnion"] = [
            {
                "topK": top_k,
                **_compact_pair_summary(compact_indexes, top_k=top_k, include_misses=True),
            }
            for top_k in top_ks
        ]
    elif sparse_pairs is not None:
        gold = {(case.name, source, target) for case in cases for source, target in case.gold}
        result["combinedUnion"] = [
            {
                "topK": top_k,
                **_pair_set_summary(
                    {pair for pair, rank in sparse_pairs.items() if rank <= top_k},
                    gold,
                    include_misses=True,
                ),
            }
            for top_k in top_ks
        ]
    rendered = canonical_json(result) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

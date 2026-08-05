"""Measure typed path evidence for manually reviewed Atlas candidate pairs.

The analyzer reopens the canonical six-release Atlas containing native
relations and the 582 admitted baseline mappings. It reports only paths whose
predicate sequence has a defensible semantic interpretation; arbitrary
undirected graph connectivity is intentionally excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec.storage import canonical_json

try:
    from tools import analyze_atlas_candidate_manual_audit as prefix_audit
    from tools import analyze_atlas_candidate_tail_manual_audit as tail_audit
except ImportError:  # Direct execution places tools/ on sys.path.
    import analyze_atlas_candidate_manual_audit as prefix_audit
    import analyze_atlas_candidate_tail_manual_audit as tail_audit


CANONICAL_JSON_PREDICATE = " <https://refspec.org/ns/vocabulary-atlas/v2#canonicalJson> "
SKOS = "http://www.w3.org/2004/02/skos/core#"
ATLAS = "https://refspec.org/ns/vocabulary-atlas/v2#"
NEUTRAL_SEMANTICS = frozenset({"exact", "alias"})
PATH_MODES = frozenset({"neutral", "close", "broader", "narrower", "related", "broader_close", "narrower_close"})


@dataclass(frozen=True, slots=True, order=True)
class Edge:
    source: str
    target: str
    semantic: str
    predicate: str
    origin: str
    traversal: str


@dataclass(frozen=True, slots=True)
class AtlasGraph:
    labels: Mapping[str, str]
    adjacency: Mapping[str, tuple[Edge, ...]]
    canonical_record_count: int
    concept_count: int
    native_claim_count: int
    mapping_assertion_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _as_ids(value: object) -> tuple[str, ...]:
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("@id"), str):
            result.append(str(item["@id"]))
    return tuple(result)


def _english_literal(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if isinstance(value.get("en"), str):
            return str(value["en"])
        if value.get("@language") in (None, "en") and isinstance(value.get("@value"), str):
            return str(value["@value"])
    if isinstance(value, list):
        for item in value:
            label = _english_literal(item)
            if label:
                return label
    return None


def _source_observation_label(value: Mapping[str, Any]) -> str | None:
    labels = value.get("labels")
    if not isinstance(labels, list):
        return None
    preferred = [
        str(label["value"])
        for label in labels
        if isinstance(label, Mapping)
        and label.get("role") == "preferred"
        and label.get("language") in (None, "en")
        and isinstance(label.get("value"), str)
    ]
    return preferred[0] if preferred else None


def _canonical_objects(path: Path) -> Iterable[Mapping[str, Any]]:
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if CANONICAL_JSON_PREDICATE not in line:
                continue
            literal = line.split(CANONICAL_JSON_PREDICATE, 1)[1]
            try:
                encoded, _end = decoder.raw_decode(literal)
                value = json.loads(encoded)
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid canonical JSON record at N-Quads line {line_number}") from error
            if not isinstance(value, Mapping):
                raise TypeError(f"canonical record at N-Quads line {line_number} is not an object")
            yield value


def _inverse(semantic: str) -> str:
    return {"broader": "narrower", "narrower": "broader"}.get(semantic, semantic)


def _add_claim(
    edges: set[Edge],
    *,
    source: str,
    target: str,
    semantic: str,
    predicate: str,
    origin: str,
) -> None:
    if not source or not target or source == target:
        return
    edges.add(Edge(source, target, semantic, predicate, origin, "forward"))
    edges.add(Edge(target, source, _inverse(semantic), predicate, origin, "inverse"))


def build_graph(objects: Iterable[Mapping[str, Any]]) -> AtlasGraph:
    """Build a typed traversal graph from canonical Atlas records."""

    records = list(objects)
    observations: dict[str, Mapping[str, Any]] = {}
    source_concepts: dict[str, str] = {}
    labels: dict[str, str] = {}
    edges: set[Edge] = set()
    native_claims: set[tuple[str, str, str, str]] = set()
    mapping_count = 0
    concept_ids: set[str] = set()

    for value in records:
        identifier = value.get("id")
        if isinstance(identifier, str) and isinstance(value.get("labels"), list):
            observations[identifier] = value
        if value.get("type") == "SourceScopedConcept" and isinstance(identifier, str):
            observation = value.get("sourceObservation")
            if isinstance(observation, str):
                source_concepts[identifier] = observation

    native_fields = {
        "skos:broader": "broader",
        SKOS + "broader": "broader",
        "skos:narrower": "narrower",
        SKOS + "narrower": "narrower",
        "skos:related": "related",
        SKOS + "related": "related",
        ATLAS + "thesaurusUse": "alias",
        ATLAS + "thesaurusUsedFor": "alias",
    }
    for value in records:
        concept_id = value.get("@id")
        concept_type = value.get("@type")
        is_managed_concept = concept_type in {
            "skos:Concept",
            "https://rulespec.org/ns/v1#RegisteredConcept",
        }
        if isinstance(concept_id, str) and is_managed_concept:
            concept_ids.add(concept_id)
            label = _english_literal(value.get("skos:prefLabel")) or _english_literal(value.get(SKOS + "prefLabel"))
            if label:
                labels[concept_id] = label
            for predicate, semantic in native_fields.items():
                for target in _as_ids(value.get(predicate)) if predicate in value else ():
                    claim = (concept_id, target, semantic, predicate)
                    native_claims.add(claim)
                    _add_claim(
                        edges,
                        source=concept_id,
                        target=target,
                        semantic=semantic,
                        predicate=predicate,
                        origin="native",
                    )
        if value.get("type") == "SourceScopedConcept" and isinstance(value.get("id"), str):
            concept_ids.add(str(value["id"]))
        if value.get("type") == "MappingAssertion":
            mapping_count += 1
            relation = str(value.get("relation", ""))
            semantic = {
                SKOS + "exactMatch": "exact",
                SKOS + "closeMatch": "close",
                SKOS + "broadMatch": "broader",
                SKOS + "narrowMatch": "narrower",
                SKOS + "relatedMatch": "related",
            }.get(relation)
            if semantic is None:
                raise ValueError(f"unsupported baseline mapping predicate: {relation!r}")
            _add_claim(
                edges,
                source=str(value["sourceConcept"]),
                target=str(value["targetConcept"]),
                semantic=semantic,
                predicate=relation,
                origin="baselineMapping",
            )

    for concept, observation_id in source_concepts.items():
        observation = observations.get(observation_id)
        if observation is not None:
            label = _source_observation_label(observation)
            if label:
                labels[concept] = label

    adjacency: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.source].append(edge)
    ordered_adjacency = {
        node: tuple(sorted(values, key=lambda edge: (edge.target, edge.semantic, edge.origin, edge.predicate)))
        for node, values in adjacency.items()
    }
    return AtlasGraph(
        labels=labels,
        adjacency=ordered_adjacency,
        canonical_record_count=len(records),
        concept_count=len(concept_ids),
        native_claim_count=len(native_claims),
        mapping_assertion_count=mapping_count,
    )


def _next_mode(mode: str, semantic: str) -> str | None:
    if semantic in NEUTRAL_SEMANTICS:
        return mode
    if mode == "neutral":
        return semantic if semantic in PATH_MODES else None
    if mode in {"broader", "narrower"} and semantic == mode:
        return mode
    if mode in {"broader", "narrower"} and semantic == "close":
        return mode + "_close"
    if mode == "close" and semantic in {"broader", "narrower"}:
        return semantic + "_close"
    if mode in {"broader_close", "narrower_close"} and semantic == mode.removesuffix("_close"):
        return mode
    return None


def shortest_usable_path(
    graph: AtlasGraph,
    source: str,
    target: str,
    *,
    max_depth: int = 4,
) -> tuple[str, tuple[Edge, ...]] | None:
    """Find the shortest path with a composable typed predicate sequence.

    Exact and source-declared alias links are neutral. Broader-only and
    narrower-only chains compose directionally. One close edge may attenuate a
    consistently directed hierarchy path. A single related edge may be
    surrounded by neutral links. Close-close, related-related, mixed hierarchy
    directions, and associative/hierarchy mixtures are excluded.
    """

    if source == target:
        return "neutral", ()
    queue: deque[tuple[str, str, tuple[Edge, ...]]] = deque([(source, "neutral", ())])
    visited: dict[tuple[str, str], int] = {(source, "neutral"): 0}
    while queue:
        node, mode, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        for edge in graph.adjacency.get(node, ()):
            next_mode = _next_mode(mode, edge.semantic)
            if next_mode is None:
                continue
            next_path = (*path, edge)
            if edge.target == target:
                return next_mode, next_path
            state = (edge.target, next_mode)
            if visited.get(state, max_depth + 1) <= len(next_path):
                continue
            visited[state] = len(next_path)
            queue.append((edge.target, next_mode, next_path))
    return None


def _path_use(mode: str) -> str:
    if mode == "related":
        return "inspectionOnlyAssociative"
    if mode == "close" or mode.endswith("_close"):
        return "cautiousAttenuatedTraversal"
    return "typedTraversal"


def _semantic_class(mode: str) -> str:
    if mode == "neutral":
        return "equivalent"
    return mode.removesuffix("_close")


def _verdict_alignment(verdict: str, mode: str) -> str:
    mode = _semantic_class(mode)
    expected = {
        "exact": "equivalent",
        "close": "close",
        "target_is_broader": "broader",
        "target_is_narrower": "narrower",
        "source_is_broader": "narrower",
        "source_is_narrower": "broader",
        "related": "related",
    }.get(verdict)
    if expected == mode:
        return "sameRelationClass"
    if verdict == "related":
        return "existingTypedPathIsMoreSpecific" if mode != "related" else "sameRelationClass"
    return "differentRelationClass"


def _path_record(graph: AtlasGraph, mode: str, path: Sequence[Edge]) -> dict[str, Any]:
    return {
        "length": len(path),
        "semanticClass": _semantic_class(mode),
        "attenuatedByClose": mode == "close" or mode.endswith("_close"),
        "use": _path_use(mode),
        "edges": [
            {
                "source": edge.source,
                "sourceLabel": graph.labels.get(edge.source),
                "target": edge.target,
                "targetLabel": graph.labels.get(edge.target),
                "semantic": edge.semantic,
                "predicate": edge.predicate,
                "origin": edge.origin,
                "traversal": edge.traversal,
            }
            for edge in path
        ],
        "intermediates": [{"id": edge.target, "label": graph.labels.get(edge.target)} for edge in path[:-1]],
    }


def _review_rows(
    *,
    audit: str,
    sample: Mapping[str, Any],
    decisions: Sequence[str],
) -> list[dict[str, Any]]:
    rows = []
    for row_number, (sample_row, verdict) in enumerate(zip(sample["rows"], decisions, strict=True), start=1):
        if verdict in prefix_audit.NON_POTENTIAL_VERDICTS:
            continue
        rows.append(
            {
                "audit": audit,
                "row": row_number,
                "case": str(sample_row["case"]),
                "verdict": verdict,
                "source": str(sample_row["source"]["member"]),
                "sourceLabel": str(sample_row["source"]["prefLabel"]),
                "target": str(sample_row["target"]["member"]),
                "targetLabel": str(sample_row["target"]["prefLabel"]),
                "selectionDigest": str(sample_row["selectionDigest"]),
            }
        )
    return rows


def analyze(
    *,
    graph: AtlasGraph,
    review_rows: Sequence[Mapping[str, Any]],
    max_depth: int,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    if len(review_rows) != 65:
        raise ValueError(f"expected exactly 65 previously supported rows, found {len(review_rows)}")
    joined = []
    for row in review_rows:
        source = str(row["source"])
        target = str(row["target"])
        if source not in graph.labels or target not in graph.labels:
            raise ValueError(f"review endpoint is absent from canonical Atlas labels: {source} / {target}")
        found = shortest_usable_path(graph, source, target, max_depth=max_depth)
        path = _path_record(graph, *found) if found is not None else None
        joined.append(
            {
                **row,
                "usablePathFound": found is not None,
                "verdictAlignment": _verdict_alignment(str(row["verdict"]), found[0]) if found else None,
                "path": path,
            }
        )

    path_rows = [row for row in joined if row["usablePathFound"]]

    def grouped(field: str) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for key in sorted({str(row[field]) for row in joined}):
            members = [row for row in joined if row[field] == key]
            found = sum(bool(row["usablePathFound"]) for row in members)
            result[key] = {"rows": len(members), "usablePathRows": found, "noUsablePathRows": len(members) - found}
        return result

    summary = {
        "reviewedPotentialRows": len(joined),
        "usablePathRows": len(path_rows),
        "noUsablePathRows": len(joined) - len(path_rows),
        "directEdgeRows": sum(int(row["path"]["length"] == 1) for row in path_rows),
        "multiHopRows": sum(int(row["path"]["length"] > 1) for row in path_rows),
        "byPathClass": dict(sorted(Counter(row["path"]["semanticClass"] for row in path_rows).items())),
        "byVerdictAlignment": dict(sorted(Counter(row["verdictAlignment"] for row in path_rows).items())),
        "byAudit": grouped("audit"),
        "byOriginalVerdict": grouped("verdict"),
    }
    report: dict[str, Any] = {
        "type": "AtlasCandidatePathEvidenceAnalysis",
        "schemaVersion": "1.0",
        "interpretation": (
            "shortest typed path evidence for the 65 rows previously marked as potential relations; "
            "a path informs directness review but does not change a human verdict or prove redundancy"
        ),
        "pathPolicy": {
            "maxDepth": max_depth,
            "neutralEdges": ["exact", "source-declared alias"],
            "allowedCompositions": [
                "neutral-only equivalence",
                "one close edge with neutral edges",
                "one close edge plus a consistently directed hierarchy, with attenuation",
                "one related edge with neutral edges",
                "broader-only hierarchy with neutral edges",
                "narrower-only hierarchy with neutral edges",
            ],
            "excludedCompositions": [
                "arbitrary undirected connectivity",
                "mixed broader and narrower chains",
                "multiple close edges",
                "multiple related edges",
                "associative plus hierarchy mixtures",
            ],
            "relatedPathUse": "inspection only; relatedMatch grants no default traversal",
        },
        "inputs": dict(inputs),
        "graph": {
            "canonicalRecords": graph.canonical_record_count,
            "concepts": graph.concept_count,
            "nativeRelationClaims": graph.native_claim_count,
            "mappingAssertions": graph.mapping_assertion_count,
        },
        "summary": summary,
        "rowsDigest": "sha256:" + hashlib.sha256(canonical_json(joined).encode()).hexdigest(),
        "rows": joined,
    }
    report["analysisDigest"] = "sha256:" + hashlib.sha256(canonical_json(report).encode()).hexdigest()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", type=Path, required=True)
    parser.add_argument("--atlas-manifest", type=Path, required=True)
    parser.add_argument("--prefix-sample", type=Path, required=True)
    parser.add_argument("--prefix-decisions", type=Path, required=True)
    parser.add_argument("--tail-sample", type=Path, required=True)
    parser.add_argument("--tail-decisions", type=Path, required=True)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--expected-native-relations", type=int, default=32_684)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.max_depth <= 8:
        raise ValueError("max-depth must be between 1 and 8")
    atlas_digest = _sha256(args.atlas)
    manifest = json.loads(args.atlas_manifest.read_text(encoding="utf-8"))
    if atlas_digest != manifest.get("output", {}).get("digest"):
        raise ValueError("canonical Atlas digest differs from its manifest")
    if args.atlas.stat().st_size != manifest.get("output", {}).get("byteLength"):
        raise ValueError("canonical Atlas byte length differs from its manifest")

    prefix_sample = json.loads(args.prefix_sample.read_text(encoding="utf-8"))
    tail_sample = json.loads(args.tail_sample.read_text(encoding="utf-8"))
    prefix_audit.validate_sample(prefix_sample)
    tail_audit.validate_tail_sample(tail_sample)
    prefix_text = args.prefix_decisions.read_text(encoding="utf-8")
    tail_text = args.tail_decisions.read_text(encoding="utf-8")
    prefix_decisions = prefix_audit.parse_ordered_decisions(prefix_text, expected_rows=len(prefix_sample["rows"]))
    tail_decisions = prefix_audit.parse_ordered_decisions(tail_text, expected_rows=len(tail_sample["rows"]))
    for sample_path, decisions_text in (
        (args.prefix_sample, prefix_text),
        (args.tail_sample, tail_text),
    ):
        if _sha256(sample_path).removeprefix("sha256:") not in decisions_text:
            raise ValueError(f"decision record does not pin sample bytes: {sample_path}")

    graph = build_graph(_canonical_objects(args.atlas))
    expected_concepts = manifest.get("counts", {}).get("concepts")
    expected_mappings = manifest.get("counts", {}).get("mappingAssertions")
    if graph.concept_count != expected_concepts:
        raise ValueError(
            f"canonical Atlas contains {graph.concept_count}, not manifest-declared {expected_concepts}, concepts"
        )
    if graph.native_claim_count != args.expected_native_relations:
        raise ValueError(
            f"canonical Atlas contains {graph.native_claim_count}, not {args.expected_native_relations}, native claims"
        )
    if graph.mapping_assertion_count != expected_mappings or expected_mappings != 582:
        raise ValueError(
            f"canonical Atlas contains {graph.mapping_assertion_count}, not manifest-declared 582, mapping assertions"
        )
    review_rows = [
        *_review_rows(audit="ranks-1-25", sample=prefix_sample, decisions=prefix_decisions),
        *_review_rows(audit="ranks-26-50", sample=tail_sample, decisions=tail_decisions),
    ]
    input_paths = {
        "analyzerFileSha256": _sha256(Path(__file__).resolve()),
        "atlasFileSha256": atlas_digest,
        "atlasManifestFileSha256": _sha256(args.atlas_manifest),
        "atlasGenerationDigest": manifest.get("generationDigest"),
        "prefixSampleFileSha256": _sha256(args.prefix_sample),
        "prefixDecisionsFileSha256": _sha256(args.prefix_decisions),
        "tailSampleFileSha256": _sha256(args.tail_sample),
        "tailDecisionsFileSha256": _sha256(args.tail_decisions),
    }
    report = analyze(graph=graph, review_rows=review_rows, max_depth=args.max_depth, inputs=input_paths)
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

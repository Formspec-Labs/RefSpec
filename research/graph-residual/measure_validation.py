"""Measure Atlas validation phases and parse-observer memory.

This is a research harness, not part of the portable Atlas binding. It imports
the validator from this checkout, runs one staging distribution in a fresh
process, and prints one JSON result. Run separate processes when comparing
memory modes because ``ru_maxrss`` is a process-lifetime high-water mark.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rdflib import Graph

ROOT = Path(__file__).resolve().parents[2]
BINDING_TOOLS = ROOT / "bindings" / "atlas" / "3.1" / "tools"
sys.path.insert(0, str(BINDING_TOOLS))

import validate as atlas_validate


def _peak_rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return value / divisor


class _PhaseMeasurements:
    """Record elapsed time, store-facing calls, and peak RSS by phase."""

    def __init__(self) -> None:
        self.current = "startup"
        self.started = time.perf_counter()
        self.phase_started = self.started
        self.calls: Counter[str] = Counter()
        self.predicates: dict[str, Counter[str]] = defaultdict(Counter)
        self.rows: list[dict[str, Any]] = []

    def phase(self, phase: str, *, current: str | None = None) -> None:
        del current
        now = time.perf_counter()
        self.rows.append(
            {
                "phase": self.current,
                "wallSeconds": round(now - self.phase_started, 6),
                "graphTriplesCalls": self.calls[self.current],
                "peakRssMiB": round(_peak_rss_mib(), 3),
                "topPredicates": [
                    {"predicate": predicate, "calls": calls}
                    for predicate, calls in self.predicates[self.current].most_common(8)
                ],
            }
        )
        self.current = phase
        self.phase_started = now

    def progress(
        self,
        phase: str,
        completed: int,
        total: int,
        *,
        current: str | None = None,
    ) -> None:
        del phase, completed, total, current

    def finish(self) -> None:
        self.phase("complete")

    @property
    def total_seconds(self) -> float:
        return time.perf_counter() - self.started


def _sample_counts(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "quadCount": sum(row["quadCount"] for row in manifest["graphs"]),
        "graphQuadCounts": {row["role"]: row["quadCount"] for row in manifest["graphs"]},
        "manifestCounts": manifest["counts"],
        "packCount": len(manifest["packs"]),
    }


def _full_measurement(distribution: Path) -> dict[str, Any]:
    manifest = json.loads((distribution / atlas_validate.MANIFEST_FILE).read_text(encoding="utf-8"))
    phases = _PhaseMeasurements()
    original_triples = Graph.triples

    def counted_triples(graph: Graph, triple: tuple[Any, Any, Any]) -> Any:
        phase = phases.current
        phases.calls[phase] += 1
        predicate = triple[1]
        phases.predicates[phase]["*" if predicate is None else str(predicate)] += 1
        return original_triples(graph, triple)

    atlas_validate._STATUS = phases
    Graph.triples = counted_triples
    try:
        result = atlas_validate.validate_distribution(distribution)
        phases.finish()
    finally:
        Graph.triples = original_triples

    rows = [row for row in phases.rows if row["phase"] != "startup"]
    return {
        "mode": "full",
        "distribution": str(distribution),
        "rdfStore": os.environ.get(atlas_validate.RDF_STORE_ENV, atlas_validate.TWO_INDEX_STORE),
        "sample": _sample_counts(manifest),
        "result": result,
        "totalSeconds": round(phases.total_seconds, 6),
        "peakRssMiB": round(_peak_rss_mib(), 3),
        "graphTriplesCalls": sum(row["graphTriplesCalls"] for row in rows),
        "phases": rows,
    }


def _indexed_occurrences(facts: Any) -> int:
    rows = facts._rows
    if rows is None:
        return 0
    return sum(len(value) if type(value) is list else 1 for row in rows.values() for value in row.values()) + sum(
        len(subjects) for subjects in facts._types.values()
    )


def _parse_measurement(distribution: Path, index_mode: str) -> dict[str, Any]:
    manifest = json.loads((distribution / atlas_validate.MANIFEST_FILE).read_text(encoding="utf-8"))
    graph_ids = atlas_validate._check_pack_manifest(manifest)
    if index_mode == "none":
        atlas_validate._INDEXED_ASSERTED_PREDICATES = frozenset()
        atlas_validate._INDEXED_ASSERTED_TYPES = frozenset()

    placement = atlas_validate._AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=atlas_validate._projection_only_predicates(),
    )
    node_digests = atlas_validate._AssertedNodeDigests(graph_ids["asserted"])
    started = time.perf_counter()
    dataset, graphs = atlas_validate._parse_packed_dataset(
        distribution,
        manifest,
        graph_ids,
        asserted_placement=placement,
        node_digests=node_digests,
    )
    elapsed = time.perf_counter() - started
    facts = placement.facts
    result = {
        "mode": "parse",
        "indexMode": index_mode,
        "distribution": str(distribution),
        "rdfStore": os.environ.get(atlas_validate.RDF_STORE_ENV, atlas_validate.TWO_INDEX_STORE),
        "sample": _sample_counts(manifest),
        "parseSeconds": round(elapsed, 6),
        "peakRssMiB": round(_peak_rss_mib(), 3),
        "assertedTriples": len(graphs["asserted"]),
        "indexedPredicateCount": len(atlas_validate._INDEXED_ASSERTED_PREDICATES),
        "indexedTypeCount": len(atlas_validate._INDEXED_ASSERTED_TYPES),
        "indexedOccurrenceCount": _indexed_occurrences(facts),
    }
    del dataset, graphs
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--mode", choices=("full", "parse"), default="full")
    parser.add_argument("--index-mode", choices=("normal", "none"), default="normal")
    parser.add_argument(
        "--store",
        choices=(atlas_validate.TWO_INDEX_STORE, atlas_validate.MEMORY_STORE),
        default=atlas_validate.TWO_INDEX_STORE,
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    os.environ[atlas_validate.RDF_STORE_ENV] = args.store
    result = (
        _full_measurement(args.distribution)
        if args.mode == "full"
        else _parse_measurement(args.distribution, args.index_mode)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

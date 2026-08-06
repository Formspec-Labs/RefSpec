"""E-S2 reachability and E-S10 cross-predicate structural transfer.

**E-S2 reachability.**  A concept with no edges can be tagged but never reached
by graph walk, rolled up, or expanded, so edge recall says nothing about whether
navigation works.  This measures orphan rate, component structure, and how far
traversal actually gets, per predicate and for the union.

**E-S10 cross-predicate transfer.**  Expanding hierarchy candidates through the
hierarchy graph is circular.  Expanding them through the *associative* graph is
not: the predicate used to generate is never the predicate scored.  Two
directions are tested --

* two associative hops as a candidate generator for hierarchy pairs, and
* two hierarchy hops as a candidate generator for associative pairs.

A positive result means publisher structure in one predicate predicts the other,
which would make graph expansion a genuine add-only arm rather than the
hierarchy-reading shortcut the ablation was designed to block.  It also has a
product reading: it is the question of whether "related" neighbourhoods are safe
to traverse when a user is really asking for broader terms.

Read-only.  No provider call, no artifact mutated.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


def load_graphs(test_sets: Path, source: str) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """Return undirected hierarchy adjacency, associative adjacency, and labels."""
    hierarchy: dict[str, set[str]] = defaultdict(set)
    associative: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    with (test_sets / f"{source}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            left, right = row["subject"]["iri"], row["object"]["iri"]
            labels[left] = row["subject"]["label"]
            labels[right] = row["object"]["label"]
            target = hierarchy if row["relationClass"] == "hierarchy" else associative
            if row["relationClass"] in {"hierarchy", "associative"}:
                target[left].add(right)
                target[right].add(left)
    return hierarchy, associative, labels


def components(adjacency: dict[str, set[str]]) -> list[int]:
    seen: set[str] = set()
    sizes: list[int] = []
    for node in adjacency:
        if node in seen:
            continue
        size = 0
        queue = deque([node])
        seen.add(node)
        while queue:
            current = queue.popleft()
            size += 1
            for other in adjacency.get(current, ()):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def reach_within(adjacency: dict[str, set[str]], hops: int) -> int:
    """Count distinct unordered pairs reachable within ``hops`` steps."""
    pairs: set[tuple[str, str]] = set()
    for start in adjacency:
        seen = {start}
        frontier = {start}
        for _ in range(hops):
            nxt: set[str] = set()
            for node in frontier:
                nxt |= adjacency.get(node, set()) - seen
            seen |= nxt
            frontier = nxt
            if not frontier:
                break
        for other in seen - {start}:
            pairs.add((start, other) if start < other else (other, start))
    return len(pairs)


def two_hop_pairs(adjacency: dict[str, set[str]]) -> set[tuple[str, str]]:
    """Pairs joined by exactly two steps but not one."""
    direct = {(a, b) if a < b else (b, a) for a, others in adjacency.items() for b in others}
    result: set[tuple[str, str]] = set()
    for neighbours in adjacency.values():
        ordered = sorted(neighbours)
        for position, left in enumerate(ordered):
            for right in ordered[position + 1 :]:
                key = (left, right) if left < right else (right, left)
                if key not in direct and left != right:
                    result.add(key)
    return result


def gold_pairs(test_sets: Path, source: str, relation_class: str) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    with (test_sets / f"{source}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["relationClass"] != relation_class:
                continue
            left, right = row["subject"]["iri"], row["object"]["iri"]
            pairs.add((left, right) if left < right else (right, left))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-sets", type=Path, required=True)
    parser.add_argument("--source", action="append")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    manifest = json.loads((args.test_sets / "manifest.json").read_text(encoding="utf-8"))
    sizes = {entry["source"]: entry["releaseResources"] for entry in manifest["sources"]}
    sources = args.source or [entry["source"] for entry in manifest["sources"]]
    results = []

    for source in sources:
        hierarchy, associative, _labels = load_graphs(args.test_sets, source)
        union: dict[str, set[str]] = defaultdict(set)
        for graph in (hierarchy, associative):
            for node, others in graph.items():
                union[node] |= others
        total = sizes[source]
        print(f"\n=== {source}   concepts={total:,}")

        entry: dict[str, Any] = {"source": source, "concepts": total, "reachability": {}, "transfer": {}}
        for name, graph in (("hierarchy", hierarchy), ("associative", associative), ("union", union)):
            if not graph:
                print(f"  {name:<12} no edges")
                continue
            sizes_list = components(graph)
            covered = len(graph)
            reach = {hops: reach_within(graph, hops) for hops in (1, 2, 3)}
            entry["reachability"][name] = {
                "conceptsWithEdges": covered,
                "orphanRate": round(1 - covered / total, 4),
                "components": len(sizes_list),
                "largestComponent": sizes_list[0],
                "largestComponentShare": round(sizes_list[0] / covered, 4),
                "pairsWithin": reach,
            }
            print(
                f"  {name:<12} covered={covered:>5,}/{total:,} orphan={1 - covered / total:6.1%} "
                f"components={len(sizes_list):<5} largest={sizes_list[0]:>5,} "
                f"({sizes_list[0] / covered:5.1%})  pairs@1={reach[1]:>7,} @2={reach[2]:>8,} @3={reach[3]:>9,}"
            )

        # ---- E-S10 cross-predicate transfer ---------------------------------
        for generator, scored in (("associative", "hierarchy"), ("hierarchy", "associative")):
            graph = associative if generator == "associative" else hierarchy
            target = gold_pairs(args.test_sets, source, scored)
            if not graph or not target:
                continue
            candidates = two_hop_pairs(graph)
            hits = len(candidates & target)
            entry["transfer"][f"{generator}2hop->{scored}"] = {
                "candidates": len(candidates),
                "goldTargets": len(target),
                "found": hits,
                "recall": round(hits / len(target), 4),
                "candidatesPerHit": round(len(candidates) / hits, 1) if hits else None,
            }
            print(
                f"  transfer  {generator} 2-hop -> {scored:<12} candidates={len(candidates):>9,} "
                f"found={hits:>5,}/{len(target):<6,} ({hits / len(target):5.1%})  "
                f"cost/hit={len(candidates) / hits if hits else float('inf'):>8.1f}"
            )
        results.append(entry)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

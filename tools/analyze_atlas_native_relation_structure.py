"""Structural diagnostics for the native-relation test sets.

Recall figures against publisher relations are only interpretable if the gold
itself is understood.  Three properties matter and none were checked before the
E3 numbers were reported.

**Transitive closure.**  SKOS ``broader`` is transitive in meaning but
thesauri assert it sparsely.  If a publisher states ``A broader B`` and
``B broader C`` but not ``A broader C``, then an arm that retrieves the
``A``/``C`` pair is scored as a miss even though the relation holds.  Every
recall number in E3 is depressed by however often that happens, and pairs
counted as noise may be entailed rather than wrong.

**Cycles and depth.**  A hierarchy with cycles is not a partial order, and
closure over it is meaningless; depth bounds how far entailment can reach.

**Degree concentration.**  If relations cluster on a few hub concepts, per-pair
recall is largely measuring hub retrieval, and the flat per-pair framing
overstates how broadly an arm works.

The tool also cross-checks a retrieval arm: of the pairs it returns that are
*not* in gold, how many are transitively entailed by the gold hierarchy?  Those
are candidates being penalised for the gold's sparseness rather than for being
wrong.

Read-only.  Makes no provider call and changes no artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


def load_directed_hierarchy(path: Path, source: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Return ``narrower -> {broader}`` edges and an IRI-to-label map."""
    edges: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    with (path / f"{source}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            subject, obj = row["subject"], row["object"]
            labels[subject["iri"]] = subject["label"]
            labels[obj["iri"]] = obj["label"]
            if row["relationClass"] == "hierarchy":
                # Rows are broader-oriented: subject is narrower than object.
                edges[subject["iri"]].add(obj["iri"])
    return edges, labels


def find_cycle(edges: dict[str, set[str]]) -> list[str] | None:
    """Return one cycle if the hierarchy is not a DAG."""
    colour: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = 1
        stack.append(node)
        for parent in sorted(edges.get(node, ())):
            state = colour.get(parent, 0)
            if state == 1:
                return stack[stack.index(parent) :] + [parent]
            if state == 0 and (found := visit(parent)) is not None:
                return found
        colour[node] = 2
        stack.pop()
        return None

    sys.setrecursionlimit(100_000)
    for node in sorted(edges):
        if colour.get(node, 0) == 0 and (found := visit(node)) is not None:
            return found
    return None


def ancestors_by_depth(edges: dict[str, set[str]], start: str, max_depth: int) -> dict[str, int]:
    """Breadth-first ancestors of one concept, keyed by shortest hop count."""
    seen: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for parent in edges.get(node, ()):
            if parent not in seen and parent != start:
                seen[parent] = depth + 1
                queue.append((parent, depth + 1))
    return seen


def closure_report(edges: dict[str, set[str]], max_depth: int) -> dict[str, Any]:
    asserted = {(child, parent) for child, parents in edges.items() for parent in parents}
    by_depth: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for child in edges:
        for ancestor, depth in ancestors_by_depth(edges, child, max_depth).items():
            by_depth[depth].add((child, ancestor))
    implied = set().union(*by_depth.values()) if by_depth else set()
    unasserted = implied - asserted
    return {
        "assertedEdges": len(asserted),
        "impliedWithinDepth": len(implied),
        "impliedButNotAsserted": len(unasserted),
        "transitivelyClosed": not unasserted,
        "inflationFactor": round(len(implied) / len(asserted), 3) if asserted else 0.0,
        "byHopCount": {str(depth): len(pairs - asserted) for depth, pairs in sorted(by_depth.items())},
        "_unasserted": unasserted,
    }


def degree_report(edges: dict[str, set[str]], concepts: int) -> dict[str, Any]:
    degree: dict[str, int] = defaultdict(int)
    for child, parents in edges.items():
        degree[child] += len(parents)
        for parent in parents:
            degree[parent] += 1
    counts = sorted(degree.values(), reverse=True)
    total = sum(counts)
    top = max(1, len(counts) // 10)
    return {
        "conceptsWithAnyEdge": len(counts),
        "conceptsInRelease": concepts,
        "maxDegree": counts[0] if counts else 0,
        "medianDegree": int(np.median(counts)) if counts else 0,
        "shareOfEdgesOnTopDecile": round(sum(counts[:top]) / total, 4) if total else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-sets", type=Path, required=True)

    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--source", action="append")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    manifest = json.loads((args.test_sets / "manifest.json").read_text(encoding="utf-8"))
    sizes = {entry["source"]: entry["releaseResources"] for entry in manifest["sources"]}
    sources = args.source or [entry["source"] for entry in manifest["sources"]]
    results = []

    for source in sources:
        edges, labels = load_directed_hierarchy(args.test_sets, source)
        if not edges:
            print(f"\n=== {source}: no hierarchy edges")
            continue
        cycle = find_cycle(edges)
        closure = closure_report(edges, args.depth)
        degrees = degree_report(edges, sizes[source])
        unasserted = closure.pop("_unasserted")

        print(f"\n=== {source}")
        print(f"  asserted hierarchy edges       {closure['assertedEdges']:,}")
        print(f"  implied within {args.depth} hops         {closure['impliedWithinDepth']:,}")
        print(f"  implied but NOT asserted       {closure['impliedButNotAsserted']:,}")
        print(f"  transitively closed            {closure['transitivelyClosed']}")
        print(f"  closure inflation factor       {closure['inflationFactor']}x")
        print(f"  new pairs by hop count         {closure['byHopCount']}")
        print(
            f"  cycle present                  {'YES ' + ' -> '.join(labels.get(n, n) for n in cycle[:4]) if cycle else 'no (is a DAG)'}"
        )
        print(
            f"  degree: max={degrees['maxDegree']} median={degrees['medianDegree']} "
            f"top-decile share={degrees['shareOfEdgesOnTopDecile']:.1%} "
            f"covered={degrees['conceptsWithAnyEdge']}/{degrees['conceptsInRelease']}"
        )

        results.append(
            {
                "source": source,
                "closure": closure,
                "cycle": [labels.get(node, node) for node in cycle] if cycle else None,
                "degrees": degrees,
                "sampleUnassertedEntailments": [
                    [labels.get(child, child), labels.get(parent, parent)] for child, parent in sorted(unasserted)[:8]
                ],
            }
        )
        for child, parent in sorted(unasserted)[:5]:
            print(f"     entailed, unasserted: {labels.get(child, child)!r} -> {labels.get(parent, parent)!r}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

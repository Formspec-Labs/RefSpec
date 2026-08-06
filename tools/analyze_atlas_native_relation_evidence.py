"""Wave 1: closure-scored recall, class mix by depth, and unmatched-pair triage.

Three experiments from the design catalogue share one pass because they need the
same three inputs -- rank artifacts, typed gold, and the hierarchy DAG -- keyed
to one concept index.

**E-S5 closure-scored recall.**  SKOS ``broader`` is transitive in meaning but
asserted sparsely.  ELSST states 3,393 edges and entails 7,608.  An arm that
retrieves ``TRUCKS``/``MOTOR VEHICLES`` is scored as a miss against the asserted
set even though the relation holds, so every recall figure measured against
asserted gold is a lower bound.  Scoring against both golds says how much.  The
effect is not arm-neutral: an encoder that captures taxonomic distance should
gain more under closure than a topical one, so a change in arm *ordering*
between the two golds would invalidate the asserted-gold rankings rather than
merely tighten them.

**E-S6 class mix by depth.**  If hierarchy and equivalence saturate early while
the associative share keeps climbing, deep retrieval is buying candidates the
directness rubric will discard, and the production cutoff should be shallow.

**E-S1a unmatched-pair triage.**  Retrieved pairs absent from gold are not
uniformly noise.  Partitioning them into transitively entailed, sibling (sharing
a parent), and neither turns an undifferentiated false-positive count into a
precision estimate plus a bounded judging queue -- only the third bucket needs
paying for.

Read-only.  No provider call, no artifact mutated.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

POPCOUNT = np.array([value.bit_count() for value in range(256)], dtype=np.uint32)

DEFAULT_DEPTHS = (1, 2, 3, 5, 10, 20, 50, 100)


def _bitmap(codes: np.ndarray | set[int], bits: int) -> np.ndarray:
    flags = np.zeros(bits, dtype=bool)
    array = np.fromiter(codes, dtype=np.int64) if isinstance(codes, set) else codes.astype(np.int64)
    if array.size:
        flags[array] = True
    return np.packbits(flags)


def _count(bitmap: np.ndarray) -> int:
    return int(POPCOUNT[bitmap].sum())


def _code(index: dict[str, int], left: str, right: str, count: int) -> int | None:
    a, b = index.get(left), index.get(right)
    if a is None or b is None or a == b:
        return None
    low, high = (a, b) if a < b else (b, a)
    return low * count + high


def load_index(corpus: dict[str, Any], source: str) -> tuple[dict[str, int], int]:
    entry = next(item for item in corpus["sources"] if item["source"] == source)
    members = [item["member"] for item in entry["concepts"]]
    return {member: position for position, member in enumerate(members)}, len(members)


def load_gold_and_graph(
    test_sets: Path, source: str, index: dict[str, int], count: int
) -> tuple[dict[str, set[int]], dict[str, set[str]]]:
    """Return gold pair codes per relation class and the narrower->broader DAG."""
    gold: dict[str, set[int]] = defaultdict(set)
    edges: dict[str, set[str]] = defaultdict(set)
    with (test_sets / f"{source}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            subject, obj = row["subject"]["iri"], row["object"]["iri"]
            code = _code(index, subject, obj, count)
            if code is not None:
                gold[row["relationClass"]].add(code)
            if row["relationClass"] == "hierarchy":
                edges[subject].add(obj)
    return gold, edges


def closure_codes(edges: dict[str, set[str]], index: dict[str, int], count: int, depth: int) -> set[int]:
    """Every ancestor pair reachable within ``depth`` hops, as pair codes."""
    codes: set[int] = set()
    for child in edges:
        seen: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(child, 0)])
        while queue:
            node, hops = queue.popleft()
            if hops >= depth:
                continue
            for parent in edges.get(node, ()):
                if parent in seen or parent == child:
                    continue
                seen.add(parent)
                queue.append((parent, hops + 1))
                code = _code(index, child, parent, count)
                if code is not None:
                    codes.add(code)
    return codes


def sibling_codes(edges: dict[str, set[str]], index: dict[str, int], count: int) -> set[int]:
    """Pairs sharing at least one asserted parent."""
    children: dict[str, list[str]] = defaultdict(list)
    for child, parents in edges.items():
        for parent in parents:
            children[parent].append(child)
    codes: set[int] = set()
    for group in children.values():
        ordered = sorted(set(group))
        for position, left in enumerate(ordered):
            for right in ordered[position + 1 :]:
                code = _code(index, left, right, count)
                if code is not None:
                    codes.add(code)
    return codes


def arm_options(ranks: Path, source: str, depths: tuple[int, ...], bits: int) -> dict[str, dict[int, np.ndarray]]:
    """Bitmaps per arm per depth, from every rank artifact for one source."""
    options: dict[str, dict[int, np.ndarray]] = {}
    for path in sorted(ranks.glob(f"*.{source}.npz")):
        family = path.name[: -len(f".{source}.npz")]
        bundle = np.load(path)
        for key in bundle.files:
            if not key.endswith(".codes"):
                continue
            view = key[: -len(".codes")]
            codes, values = bundle[key], bundle.get(f"{view}.ranks")
            name = f"{family}.{view}" if family != "sparse" else view
            if values is None:
                options[name] = {depths[-1]: _bitmap(codes, bits)}
                continue
            options[name] = {depth: _bitmap(codes[values <= depth], bits) for depth in depths}
    return options


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--test-sets", type=Path, required=True)
    parser.add_argument("--ranks", type=Path, required=True)
    parser.add_argument("--source", action="append")
    parser.add_argument("--depths", type=int, nargs="+", default=list(DEFAULT_DEPTHS))
    parser.add_argument("--closure-depth", type=int, default=6)
    parser.add_argument("--triage-arm", default="openai-3-large.label")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--export-gold",
        type=Path,
        default=None,
        help="Write closure and sibling gold as extra classes the frontier can score against.",
    )
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    depths = tuple(sorted(set(args.depths)))
    sources = args.source or [entry["source"] for entry in corpus["sources"]]
    results = []

    for source in sources:
        index, count = load_index(corpus, source)
        bits = count * count
        gold, edges = load_gold_and_graph(args.test_sets, source, index, count)
        options = arm_options(args.ranks, source, depths, bits)

        gold_bitmaps = {name: _bitmap(codes, bits) for name, codes in gold.items()}
        gold_sizes = {name: len(codes) for name, codes in gold.items()}
        asserted_hierarchy = gold.get("hierarchy", set())
        closure = closure_codes(edges, index, count, args.closure_depth) if edges else set()
        siblings = sibling_codes(edges, index, count) if edges else set()
        closure_bitmap = _bitmap(closure, bits) if closure else None
        sibling_bitmap = _bitmap(siblings - closure - asserted_hierarchy, bits) if siblings else None
        any_gold = _bitmap(set().union(*gold.values()), bits)

        print(f"\n{'=' * 78}\n=== {source}   concepts={count}   arms={len(options)}")
        entry: dict[str, Any] = {"source": source, "conceptCount": count, "goldSizes": gold_sizes}

        # ---- E-S5: asserted versus closure gold -------------------------------
        if closure_bitmap is not None:
            print(f"\n-- E-S5 hierarchy recall: asserted={len(asserted_hierarchy):,} closure={len(closure):,}")
            rows = []
            for name, by_depth in sorted(options.items()):
                bitmap = by_depth[depths[-1]]
                a = _count(np.bitwise_and(bitmap, gold_bitmaps["hierarchy"]))
                c = _count(np.bitwise_and(bitmap, closure_bitmap))
                rows.append((name, a / len(asserted_hierarchy), c / len(closure), a, c))
            by_asserted = sorted(rows, key=lambda r: -r[1])
            by_closure = sorted(rows, key=lambda r: -r[2])
            print(f"   {'arm':<34}{'asserted':>10}{'closure':>10}   rank shift")
            for position, row in enumerate(by_asserted[:12]):
                shift = by_closure.index(row) - position
                marker = "" if shift == 0 else f"  {shift:+d}"
                print(f"   {row[0][:33]:<34}{row[1]:>9.1%}{row[2]:>10.1%}{marker}")
            top_a = [r[0] for r in by_asserted[:10]]
            top_c = [r[0] for r in by_closure[:10]]
            entry["closure"] = {
                "assertedEdges": len(asserted_hierarchy),
                "closureEdges": len(closure),
                "top10Identical": top_a == top_c,
                "top10SetIdentical": set(top_a) == set(top_c),
                "arms": [
                    {"arm": r[0], "assertedRecall": r[1], "closureRecall": r[2], "asserted": r[3], "closure": r[4]}
                    for r in by_asserted
                ],
            }
            print(
                f"   top-10 ordering preserved: {top_a == top_c}    "
                f"top-10 membership preserved: {set(top_a) == set(top_c)}"
            )

        # ---- E-S6: class mix by depth ----------------------------------------
        arm = args.triage_arm if args.triage_arm in options else min(options)
        print(f"\n-- E-S6 class mix by depth   arm={arm}")
        mix = []
        header = "   " + f"{'depth':>7}" + "".join(f"{name[:11]:>13}" for name in sorted(gold)) + f"{'retained':>12}"
        print(header)
        for depth in depths:
            bitmap = options[arm][depth]
            found = {name: _count(np.bitwise_and(bitmap, gold_bitmaps[name])) for name in sorted(gold)}
            total = sum(found.values())
            cells = "".join(f"{(found[n] / total if total else 0):>12.1%} " for n in sorted(gold))
            print(f"   {depth:>7}{cells}{_count(bitmap):>11,}")
            mix.append(
                {"depth": depth, "found": found, "share": {n: (found[n] / total if total else 0) for n in found}}
            )
        entry["classMix"] = {"arm": arm, "byDepth": mix}

        # ---- E-S1a: unmatched-pair triage ------------------------------------
        print(f"\n-- E-S1a unmatched triage   arm={arm}")
        triage = []
        print(
            f"   {'depth':>7}{'retrieved':>12}{'in gold':>10}{'entailed':>10}{'sibling':>9}{'neither':>12}{'%neither':>10}"
        )
        for depth in depths:
            bitmap = options[arm][depth]
            retrieved = _count(bitmap)
            matched = _count(np.bitwise_and(bitmap, any_gold))
            unmatched = np.bitwise_and(bitmap, np.bitwise_not(any_gold))
            entailed = _count(np.bitwise_and(unmatched, closure_bitmap)) if closure_bitmap is not None else 0
            sibling = _count(np.bitwise_and(unmatched, sibling_bitmap)) if sibling_bitmap is not None else 0
            neither = _count(unmatched) - entailed - sibling
            triage.append(
                {
                    "depth": depth,
                    "retrieved": retrieved,
                    "inGold": matched,
                    "entailed": entailed,
                    "sibling": sibling,
                    "neither": neither,
                }
            )
            print(
                f"   {depth:>7}{retrieved:>12,}{matched:>10,}{entailed:>10,}{sibling:>9,}"
                f"{neither:>12,}{neither / retrieved if retrieved else 0:>10.1%}"
            )
        entry["triage"] = {"arm": arm, "byDepth": triage}

        if args.export_gold and closure:
            # The frontier scores whatever ``gold.*`` classes it finds, so the
            # closure and sibling sets ship as additional classes rather than
            # replacing the asserted hierarchy.
            args.export_gold.mkdir(parents=True, exist_ok=True)
            extra = {"conceptCount": np.asarray([count], dtype=np.uint32)}
            extra["gold.hierarchyClosure"] = np.sort(np.fromiter(closure, dtype=np.uint32, count=len(closure)))
            only_sibling = siblings - closure - asserted_hierarchy
            if only_sibling:
                extra["gold.sibling"] = np.sort(np.fromiter(only_sibling, dtype=np.uint32, count=len(only_sibling)))
            np.savez_compressed(args.export_gold / f"closure.{source}.npz", **extra)
            print(f"\n   exported closure gold: {len(closure):,} pairs, sibling {len(only_sibling):,}")

        results.append(entry)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"results": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

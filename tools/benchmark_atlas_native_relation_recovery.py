"""E3: recover publisher relations from concept text alone, hierarchy ablated.

Every typed-relation recall number in the candidate-retrieval ledger came from
OAEI Conference or OAEI Anatomy.  Conference asserts equivalence only and
Anatomy is biomedical, so no arm has ever been measured against typed
directional relations in the policy and social-science domain the Atlas
actually serves.  The per-source native-relation test sets close that gap.

The task here is deliberately intra-vocabulary: for each concept, rank every
other concept in the same release and ask whether the publisher's own
``broader``/``narrower``, ``related``, and ``use`` partners come back.  Concept
text is built from label, alternate labels, definition, notes, and notations
only.  Hierarchy fields are left empty, so the sparse context view cannot read
the parent and child labels that would otherwise hand it the hierarchy answer.

Scoring reuses ``refspec.atlas.candidate_retrieval`` unchanged so results stay
comparable with the sealed frontier receipts.  Two deterministic hash-join
anchors are added: normalized preferred-label equality, and the exact
shared-alias anchor that the lexical experiment proposed after
``Family planning``/``BIRTH CONTROL`` and ``Motor vehicles``/``CARS`` were
missed at K100, and that was never built.

This tool makes no provider call and changes no release artifact.  Dense arms
are absent from this environment; results are the dependency-free floor.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # Direct execution without an editable install.
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from refspec.atlas import candidate_retrieval as retrieval
from refspec.storage import canonical_json

try:
    from tools import build_atlas_native_relation_testsets as testsets
except ImportError:  # Direct execution places tools/ on sys.path.
    import build_atlas_native_relation_testsets as testsets  # type: ignore[no-redef]


DEFAULT_TEST_SETS = testsets.DEFAULT_OUTPUT
DEFAULT_DEPTHS = (1, 2, 3, 5, 10, 20, 50, 100)

SPARSE_VIEWS = retrieval.DEFAULT_SPARSE_VIEWS

#: Label-overlap bands.  ``disjoint`` shares no normalized token and is the
#: slice where surface matching cannot help, so it is the honest headline for
#: whether an arm recovers a relation from meaning rather than spelling.
OVERLAP_BANDS = ("identical", "high", "low", "disjoint")


@dataclass(frozen=True, slots=True)
class AblatedConcept:
    """A concept exposing only self-description; hierarchy fields stay empty."""

    member: str
    pref_label: str
    alt_labels: tuple[str, ...] = ()
    definition: str | None = None
    scope_note: str | None = None
    broader: tuple[str, ...] = ()
    parents: tuple[Any, ...] = ()
    children: tuple[Any, ...] = ()


@dataclass(slots=True)
class GoldSet:
    """Publisher relations for one source, keyed by unordered endpoint pair."""

    source: str
    by_class: dict[str, set[tuple[str, str]]] = field(default_factory=lambda: defaultdict(set))
    overlap: dict[tuple[str, str], str] = field(default_factory=dict)
    labels: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    def all_pairs(self) -> set[tuple[str, str]]:
        return set().union(*self.by_class.values()) if self.by_class else set()


def _unordered(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(retrieval._normalized_words(value))


def _overlap_band(left: str, right: str) -> str:
    """Classify a pair by normalized token overlap between display labels."""
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return "disjoint"
    if left_tokens == right_tokens:
        return "identical"
    shared = left_tokens & right_tokens
    if not shared:
        return "disjoint"
    jaccard = len(shared) / len(left_tokens | right_tokens)
    return "high" if jaccard >= 0.5 else "low"


def _scope_note(block: Mapping[str, Any]) -> str | None:
    notes = block.get("notes") or ()
    return "\n".join(str(note) for note in notes) if notes else None


def _ablated_concepts(release: Any) -> tuple[AblatedConcept, ...]:
    """Build the retrieval corpus with every hierarchy field empty."""
    concepts = []
    for resource in release.resources:
        block = testsets._concept_block(resource)
        concepts.append(
            AblatedConcept(
                member=str(block["iri"]),
                pref_label=str(block["label"]),
                alt_labels=tuple(str(value) for value in block.get("altLabels", ())),
                definition=block.get("definition"),
                scope_note=_scope_note(block),
            )
        )
    return tuple(sorted(concepts, key=lambda concept: concept.member))


def load_gold(path: Path, source: str) -> GoldSet:
    """Read one emitted test set as unordered gold pairs per relation class."""
    gold = GoldSet(source=source)
    with (path / f"{source}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            subject, obj = row["subject"], row["object"]
            key = _unordered(str(subject["iri"]), str(obj["iri"]))
            gold.by_class[str(row["relationClass"])].add(key)
            gold.overlap[key] = _overlap_band(str(subject["label"]), str(obj["label"]))
            gold.labels[key] = (str(subject["label"]), str(obj["label"]))
    return gold


def _sparse_ranks(concepts: Sequence[AblatedConcept], view: Any, top_k: int) -> dict[tuple[str, str], int]:
    """Best bidirectional rank per unordered pair, excluding self-matches.

    Calls the sealed scoring helpers directly so the feature weighting, rarity
    scaling, and tie-breaking match the frontier receipts exactly.  A concept is
    always its own nearest neighbour, so one extra neighbour is requested and
    self-pairs are dropped before ranks are re-derived.
    """
    vectors, norms = retrieval._weighted_vectors(concepts, (), view)
    postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for concept in concepts:
        for feature, value in vectors[concept.member].items():
            postings[feature].append((concept.member, value))

    best: dict[tuple[str, str], int] = {}
    for query in concepts:
        dots: dict[str, int] = defaultdict(int)
        for feature, query_value in vectors[query.member].items():
            for member, document_value in postings.get(feature, ()):
                dots[member] += query_value * document_value
        scored = []
        for member, dot in dots.items():
            if member == query.member:
                continue
            denominator = retrieval.isqrt(norms[query.member] * norms[member])
            if denominator:
                scored.append((dot * retrieval.SCORE_SCALE // denominator, member))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for rank, (_score, member) in enumerate(scored[:top_k], start=1):
            key = _unordered(query.member, member)
            if rank < best.get(key, top_k + 1):
                best[key] = rank
    return best


def _exact_label_pairs(concepts: Sequence[AblatedConcept]) -> set[tuple[str, str]]:
    buckets: dict[str, list[str]] = defaultdict(list)
    for concept in concepts:
        phrase = retrieval._normalized_phrase(concept.pref_label)
        if phrase:
            buckets[phrase].append(concept.member)
    return {
        _unordered(left, right)
        for members in buckets.values()
        for index, left in enumerate(members)
        for right in members[index + 1 :]
    }


def _exact_alias_pairs(concepts: Sequence[AblatedConcept]) -> set[tuple[str, str]]:
    """Max-over-individual-label anchor: any normalized label shared by two concepts.

    Comparing each label separately is the point.  Concatenating a concept's
    aliases into one bag dilutes an exact shared alias, which is how the lexical
    experiment lost ``Family planning``/``BIRTH CONTROL`` at K100.
    """
    buckets: dict[str, list[str]] = defaultdict(list)
    for concept in concepts:
        for value in (concept.pref_label, *concept.alt_labels):
            phrase = retrieval._normalized_phrase(value)
            if phrase:
                buckets[phrase].append(concept.member)
    return {
        _unordered(left, right)
        for members in buckets.values()
        for index, left in enumerate(sorted(set(members)))
        for right in sorted(set(members))[index + 1 :]
    }


def _recall_row(
    found: Mapping[tuple[str, str], int] | set[tuple[str, str]],
    gold: Iterable[tuple[str, str]],
    depth: int | None,
) -> int:
    gold = set(gold)
    if isinstance(found, set):
        return len(found & gold)
    return sum(1 for pair in gold if (rank := found.get(pair)) is not None and (depth is None or rank <= depth))


def _arm_report(
    name: str,
    found: Mapping[tuple[str, str], int] | set[tuple[str, str]],
    gold: GoldSet,
    depths: Sequence[int],
    seconds: float,
) -> dict[str, Any]:
    ranked = not isinstance(found, set)
    report: dict[str, Any] = {
        "arm": name,
        "ranked": ranked,
        "retainedPairs": len(found),
        "seconds": round(seconds, 3),
        "byRelationClass": {},
    }
    for relation_class in sorted(gold.by_class):
        pairs = gold.by_class[relation_class]
        entry: dict[str, Any] = {"gold": len(pairs), "recallAtDepth": {}}
        for depth in depths if ranked else (depths[-1],):
            entry["recallAtDepth"][str(depth)] = _recall_row(found, pairs, depth if ranked else None)
        bands: dict[str, Any] = {}
        for band in OVERLAP_BANDS:
            band_pairs = {pair for pair in pairs if gold.overlap.get(pair) == band}
            if band_pairs:
                bands[band] = {
                    "gold": len(band_pairs),
                    "found": _recall_row(found, band_pairs, depths[-1] if ranked else None),
                }
        entry["byLabelOverlap"] = bands
        report["byRelationClass"][relation_class] = entry
    return report


def run_source(
    source: str,
    release: Any,
    gold: GoldSet,
    depths: Sequence[int],
) -> dict[str, Any]:
    concepts = _ablated_concepts(release)
    arms: list[dict[str, Any]] = []
    found_by_arm: dict[str, Any] = {}

    started = time.perf_counter()
    exact_label = _exact_label_pairs(concepts)
    arms.append(_arm_report("exactPreferredLabel", exact_label, gold, depths, time.perf_counter() - started))
    found_by_arm["exactPreferredLabel"] = exact_label

    started = time.perf_counter()
    exact_alias = _exact_alias_pairs(concepts)
    arms.append(_arm_report("exactSharedAliasAnchor", exact_alias, gold, depths, time.perf_counter() - started))
    found_by_arm["exactSharedAliasAnchor"] = exact_alias

    for view in SPARSE_VIEWS:
        started = time.perf_counter()
        ranks = _sparse_ranks(concepts, view, depths[-1])
        arms.append(_arm_report(view.name, ranks, gold, depths, time.perf_counter() - started))
        found_by_arm[view.name] = ranks

    union: dict[tuple[str, str], int] = {}
    for name, found in found_by_arm.items():
        pairs = found.items() if not isinstance(found, set) else ((pair, 1) for pair in found)
        for pair, rank in pairs:
            if rank < union.get(pair, depths[-1] + 1):
                union[pair] = rank
    arms.append(_arm_report("unionAllArms", union, gold, depths, 0.0))

    unique: dict[str, int] = {}
    for name, found in found_by_arm.items():
        others: set[tuple[str, str]] = set()
        for other_name, other in found_by_arm.items():
            if other_name != name:
                others |= set(other)
        owned = set(found) - others
        unique[name] = len(owned & gold.all_pairs())

    return {
        "source": source,
        "sourceRelease": release.atlas_release_iri,
        "corpusConcepts": len(concepts),
        "goldByRelationClass": {name: len(pairs) for name, pairs in sorted(gold.by_class.items())},
        "ablation": {
            "hierarchyFieldsSupplied": False,
            "conceptTextFields": ["label", "altLabels", "definition", "notes"],
            "note": "broader, parents, and children are empty so the context view cannot read hierarchy labels",
        },
        "arms": arms,
        "uniqueGoldRescuesByArm": dict(sorted(unique.items())),
    }


def export_ranks(source: str, release: Any, gold: GoldSet, output: Path, depth: int) -> dict[str, Any]:
    """Persist deterministic-arm ranks in the compact form the frontier reads.

    Pair codes are ``low * conceptCount + high`` over the concept list sorted by
    member IRI, which is the same ordering the exported corpus gives the dense
    run, so sparse and dense arms address identical pairs.
    """
    import numpy as np

    concepts = _ablated_concepts(release)
    index = {concept.member: position for position, concept in enumerate(concepts)}
    count = len(concepts)

    def _code(pair: tuple[str, str]) -> int:
        left, right = index[pair[0]], index[pair[1]]
        low, high = (left, right) if left < right else (right, left)
        return low * count + high

    arms: dict[str, dict[tuple[str, str], int]] = {
        "exactPreferredLabel": dict.fromkeys(_exact_label_pairs(concepts), 1),
        "exactSharedAliasAnchor": dict.fromkeys(_exact_alias_pairs(concepts), 1),
    }
    for view in SPARSE_VIEWS:
        arms[view.name] = _sparse_ranks(concepts, view, depth)

    payload: dict[str, Any] = {"conceptCount": np.asarray([count], dtype=np.uint32)}
    summary: dict[str, int] = {}
    for name, found in arms.items():
        codes = np.fromiter((_code(pair) for pair in found), dtype=np.uint32, count=len(found))
        ranks = np.fromiter(found.values(), dtype=np.uint8, count=len(found))
        order = np.argsort(codes, kind="stable")
        payload[f"{name}.codes"] = codes[order]
        payload[f"{name}.ranks"] = ranks[order]
        summary[name] = len(found)

    for relation_class, pairs in gold.by_class.items():
        codes = np.fromiter((_code(pair) for pair in pairs), dtype=np.uint32, count=len(pairs))
        payload[f"gold.{relation_class}"] = np.sort(codes)
    bands: dict[str, list[int]] = defaultdict(list)
    for pair, band in gold.overlap.items():
        bands[band].append(_code(pair))
    for band, codes in bands.items():
        payload[f"band.{band}"] = np.sort(np.asarray(codes, dtype=np.uint32))

    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / f"sparse.{source}.npz", **payload)
    return summary


def export_payload(source: str, release: Any, gold: GoldSet) -> dict[str, Any]:
    """Serialise the ablated corpus and gold so a dense run needs no refspec import.

    The dense arms require ``fastembed`` and run in an isolated environment that
    cannot load this package.  Exporting the exact ablated text keeps both halves
    of E3 scoring the identical corpus.
    """
    concepts = _ablated_concepts(release)
    return {
        "source": source,
        "sourceRelease": release.atlas_release_iri,
        "concepts": [
            {
                "member": concept.member,
                "label": concept.pref_label,
                "altLabels": list(concept.alt_labels),
                "definition": concept.definition,
                "notes": concept.scope_note,
            }
            for concept in concepts
        ],
        "gold": {
            relation_class: sorted(list(pair) for pair in pairs)
            for relation_class, pairs in sorted(gold.by_class.items())
        },
        "overlap": {f"{left}\t{right}": band for (left, right), band in sorted(gold.overlap.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test-sets", type=Path, default=DEFAULT_TEST_SETS)
    parser.add_argument("--source", action="append", choices=list(testsets.TEST_SET_SOURCES))
    parser.add_argument("--depths", type=int, nargs="+", default=list(DEFAULT_DEPTHS))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--export-corpus",
        type=Path,
        default=None,
        help="Write the ablated corpus and gold for the isolated dense run, then exit.",
    )
    parser.add_argument(
        "--export-ranks",
        type=Path,
        default=None,
        help="Write deterministic-arm ranks, gold, and overlap bands for the frontier stage, then exit.",
    )
    args = parser.parse_args()

    if args.export_ranks:
        releases = {release.spec.key: release for release in testsets.load_test_set_releases()}
        selected = tuple(args.source) if args.source else testsets.TEST_SET_SOURCES
        depth = max(sorted(set(args.depths)))
        for source in selected:
            gold = load_gold(args.test_sets, source)
            summary = export_ranks(source, releases[source], gold, args.export_ranks, depth)
            print(f"{source:<34} {summary}")
        print(f"wrote {args.export_ranks}")
        return 0

    if args.export_corpus:
        releases = {release.spec.key: release for release in testsets.load_test_set_releases()}
        selected = tuple(args.source) if args.source else testsets.TEST_SET_SOURCES
        payload = {
            "type": "AtlasNativeRelationAblatedCorpus",
            "ablation": {"hierarchyFieldsSupplied": False},
            "sources": [
                export_payload(source, releases[source], load_gold(args.test_sets, source)) for source in selected
            ],
        }
        args.export_corpus.parent.mkdir(parents=True, exist_ok=True)
        args.export_corpus.write_text(f"{canonical_json(payload)}\n", encoding="utf-8")
        for entry in payload["sources"]:
            counts = {name: len(pairs) for name, pairs in entry["gold"].items()}
            print(f"{entry['source']:<34} concepts={len(entry['concepts']):>5} gold={counts}")
        print(f"wrote {args.export_corpus}")
        return 0

    selected = tuple(args.source) if args.source else testsets.TEST_SET_SOURCES
    depths = tuple(sorted(set(args.depths)))
    releases = {release.spec.key: release for release in testsets.load_test_set_releases()}

    results = []
    for source in selected:
        gold = load_gold(args.test_sets, source)
        result = run_source(source, releases[source], gold, depths)
        results.append(result)
        print(f"\n=== {source}  concepts={result['corpusConcepts']}  gold={result['goldByRelationClass']}")
        for arm in result["arms"]:
            for relation_class, entry in arm["byRelationClass"].items():
                recalls = " ".join(f"@{depth}={count}" for depth, count in entry["recallAtDepth"].items())
                disjoint = entry["byLabelOverlap"].get("disjoint")
                tail = f"  disjoint={disjoint['found']}/{disjoint['gold']}" if disjoint else ""
                print(
                    f"  {arm['arm']:<24} {relation_class:<12} gold={entry['gold']:>5}  "
                    f"pairs={arm['retainedPairs']:>8}  {recalls}{tail}"
                )
        print(f"  unique gold rescues: {result['uniqueGoldRescuesByArm']}")

    payload = {
        "type": "AtlasNativeRelationRecoveryResult",
        "experiment": "E3-directional-discovery-hierarchy-ablated",
        "depths": list(depths),
        "denseArmsAvailable": False,
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{canonical_json(payload)}\n", encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

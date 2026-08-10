"""Experiment with preferred ICPSR endpoints and USE-reachable access terms.

This tool is deliberately outside qualification production code.  It reopens
the sealed 3,760-member ICPSR development release, keeps preferred concepts as
mapping endpoints, follows each functional ``use`` path to a preferred sink,
and attaches the originating access-term label as retrieval-only alternate
text.  It then reruns the exact Atlas lexical and sparse/graph frontier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from refspec.atlas.candidate_retrieval import AtlasConcept, AtlasConceptContext
from refspec.atlas.parquet_artifact import file_sha256 as _sha256
from refspec.storage import canonical_json

try:
    from tools import benchmark_atlas_candidate_retrieval as shared_benchmark
    from tools import benchmark_atlas_sparse_lexical_frontier as frontier
    from tools import benchmark_lexical_candidate_controls as lexical_benchmark
except ImportError:  # Direct execution places tools/ on sys.path.
    import benchmark_atlas_candidate_retrieval as shared_benchmark
    import benchmark_atlas_sparse_lexical_frontier as frontier
    import benchmark_lexical_candidate_controls as lexical_benchmark


EXPECTED_RELEASE_MEMBERS = 3_760
EXPECTED_PREFERRED_ENDPOINTS = 3_280
EXPECTED_ALTERNATE_MEMBERS = 480
BASELINE_FLOOR_CANDIDATES = 210_197
BASELINE_FLOOR_DIGEST = "sha256:24fc3c81f443596181b9bd0e9d2b663992052c19f383ffd2cd222e60d565ede9"


def _normalized_label(value: str) -> str:
    return " ".join(
        token for token in re.split(r"\s+", unicodedata.normalize("NFKC", value).casefold().strip()) if token
    )


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be non-empty trimmed text")
    return value


@dataclass(frozen=True, slots=True)
class IcpsrEndpointProjection:
    """A relation-blind, preferred-endpoint retrieval view of ICPSR."""

    all_members: frozenset[str]
    preferred_members: frozenset[str]
    alternate_members: frozenset[str]
    aliases_by_preferred: Mapping[str, tuple[str, ...]]
    access_paths: tuple[Mapping[str, Any], ...]
    unresolved_alternates: tuple[Mapping[str, Any], ...]
    digest: str


def build_endpoint_projection(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_members: int | None = None,
    expected_preferred: int | None = None,
    expected_alternate: int | None = None,
) -> IcpsrEndpointProjection:
    """Follow unambiguous alternate ``use`` paths to preferred endpoints."""

    by_member: dict[str, Mapping[str, Any]] = {}
    roles: dict[str, str] = {}
    labels: dict[str, str] = {}
    use_targets: dict[str, str] = {}
    for raw in rows:
        member = _require_text(raw.get("conceptIri"), "ICPSR conceptIri")
        if member in by_member:
            raise ValueError("ICPSR endpoint projection repeats a release member")
        role = _require_text(raw.get("officialLabelRole"), "ICPSR officialLabelRole")
        if role not in {"preferred", "alternate"}:
            raise ValueError("ICPSR endpoint projection has an unsupported label role")
        label = _require_text(raw.get("officialLabel"), "ICPSR officialLabel")
        relations = raw.get("relations", ())
        if not isinstance(relations, Sequence) or isinstance(relations, (str, bytes)):
            raise TypeError("ICPSR endpoint projection relations must be an array")
        uses = []
        for relation in relations:
            if not isinstance(relation, Mapping) or relation.get("relation") != "use":
                continue
            if relation.get("resolutionStatus") != "uriVerified":
                raise ValueError("ICPSR use path is not URI verified")
            uses.append(_require_text(relation.get("targetConceptIri"), "ICPSR use target"))
        if len(uses) > 1:
            raise ValueError("ICPSR access term has ambiguous use targets")
        if uses:
            use_targets[member] = uses[0]
        by_member[member] = raw
        roles[member] = role
        labels[member] = label

    preferred = frozenset(member for member, role in roles.items() if role == "preferred")
    alternate = frozenset(member for member, role in roles.items() if role == "alternate")
    for expected, actual, label in (
        (expected_members, len(by_member), "release members"),
        (expected_preferred, len(preferred), "preferred endpoints"),
        (expected_alternate, len(alternate), "alternate members"),
    ):
        if expected is not None and actual != expected:
            raise ValueError(f"ICPSR endpoint projection expected {expected} {label}, found {actual}")

    aliases: dict[str, set[str]] = defaultdict(set)
    paths: list[Mapping[str, Any]] = []
    unresolved: list[Mapping[str, Any]] = []
    normalized_targets: dict[str, str] = {}
    for origin in sorted(alternate):
        current = origin
        visited = [origin]
        while current not in preferred:
            target = use_targets.get(current)
            if target is None:
                unresolved.append(
                    {
                        "member": origin,
                        "label": labels[origin],
                        "reason": "no functional use path to a preferred endpoint",
                        "path": visited,
                    }
                )
                break
            target_row = by_member.get(target)
            if target_row is None:
                raise ValueError("ICPSR use path leaves the sealed release")
            relation = next(
                relation
                for relation in by_member[current].get("relations", ())
                if isinstance(relation, Mapping) and relation.get("relation") == "use"
            )
            if relation.get("targetLabel") != labels[target]:
                raise ValueError("ICPSR use path target label differs from its release member")
            if target in visited:
                raise ValueError("ICPSR use path contains a cycle")
            visited.append(target)
            current = target
        else:
            normalized = _normalized_label(labels[origin])
            prior = normalized_targets.get(normalized)
            if prior is not None and prior != current:
                raise ValueError("ICPSR access-term label reaches two preferred endpoints")
            normalized_targets[normalized] = current
            aliases[current].add(labels[origin])
            paths.append(
                {
                    "accessMember": origin,
                    "accessLabel": labels[origin],
                    "preferredMember": current,
                    "preferredLabel": labels[current],
                    "hops": len(visited) - 1,
                    "path": visited,
                }
            )

    stable = {
        "releaseMembers": len(by_member),
        "preferredEndpoints": len(preferred),
        "alternateMembers": len(alternate),
        "aliasesByPreferred": {member: sorted(values) for member, values in sorted(aliases.items())},
        "accessPaths": paths,
        "unresolvedAlternates": unresolved,
    }
    digest = "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()
    return IcpsrEndpointProjection(
        all_members=frozenset(by_member),
        preferred_members=preferred,
        alternate_members=alternate,
        aliases_by_preferred={member: tuple(sorted(values)) for member, values in sorted(aliases.items())},
        access_paths=tuple(paths),
        unresolved_alternates=tuple(unresolved),
        digest=digest,
    )


def _project_context(
    context: AtlasConceptContext,
    aliases: Mapping[str, tuple[str, ...]],
) -> AtlasConceptContext:
    return replace(
        context,
        alt_labels=tuple(sorted(set(context.alt_labels) | set(aliases.get(context.member, ())))),
    )


def _project_concept(
    concept: AtlasConcept,
    aliases: Mapping[str, tuple[str, ...]],
) -> AtlasConcept:
    return replace(
        concept,
        alt_labels=tuple(sorted(set(concept.alt_labels) | set(aliases.get(concept.member, ())))),
        parents=tuple(_project_context(context, aliases) for context in concept.parents),
        children=tuple(_project_context(context, aliases) for context in concept.children),
    )


def project_alignment_cases(
    cases: Sequence[shared_benchmark.AlignmentCase],
    projection: IcpsrEndpointProjection,
) -> tuple[shared_benchmark.AlignmentCase, ...]:
    """Apply aliases while keeping only complete preferred ICPSR endpoint axes."""

    projected = []
    for case in cases:
        sides = []
        for concepts in (case.sources, case.targets):
            intersecting = [concept for concept in concepts if concept.member in projection.all_members]
            if not intersecting:
                sides.append(concepts)
                continue
            if len(intersecting) != len(concepts):
                raise ValueError("an Atlas alignment side mixes ICPSR with another release")
            endpoints = tuple(
                _project_concept(concept, projection.aliases_by_preferred)
                for concept in concepts
                if concept.member in projection.preferred_members
            )
            if frozenset(concept.member for concept in endpoints) != projection.preferred_members:
                raise ValueError("Atlas ICPSR endpoint axis differs from the complete preferred projection")
            sides.append(endpoints)
        sources, targets = sides
        source_members = {concept.member for concept in sources}
        target_members = {concept.member for concept in targets}
        if any(source not in source_members or target not in target_members for source, target in case.gold):
            raise ValueError("preferred-endpoint projection removes a sealed Atlas mapping")
        projected.append(shared_benchmark.AlignmentCase(case.name, sources, targets, case.gold))
    return tuple(projected)


def _read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise TypeError(f"ICPSR concepts line {line_number} is not an object")
        rows.append(value)
    return rows


def _verify_manifest_artifact(manifest_path: Path, concepts_path: Path) -> Mapping[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = str(concepts_path.resolve().relative_to(manifest_path.parent.resolve()))
    matches = [artifact for artifact in manifest.get("artifacts", ()) if artifact.get("path") == relative]
    if len(matches) != 1:
        raise ValueError("ICPSR manifest does not pin exactly one concepts artifact")
    artifact = matches[0]
    if artifact.get("sha256") != _sha256(concepts_path) or artifact.get("byteLength") != concepts_path.stat().st_size:
        raise ValueError("ICPSR concepts artifact differs from its managed-release manifest")
    return manifest


def _read_baseline_pairs(path: Path, codec: lexical_benchmark.PairCodec) -> frozenset[int]:
    import numpy as np

    values = np.fromfile(path, dtype="<u8")
    if len(values) and not bool(np.all(values[1:] > values[:-1])):
        raise ValueError("baseline pair receipt is not strictly sorted")
    pairs = frozenset(int(value) for value in values)
    if len(pairs) != BASELINE_FLOOR_CANDIDATES or frontier._pair_digest(pairs, codec) != BASELINE_FLOOR_DIGEST:
        raise ValueError("baseline pair receipt differs from the sealed lexical-K3 sparse-K1 floor")
    return pairs


def _deterministic_digest(report: Mapping[str, Any]) -> str:
    stable = json.loads(canonical_json(report))
    stable.pop("elapsedSeconds", None)
    for arm in stable.get("lexicalArms", ()):
        arm.pop("elapsedSeconds", None)
    stable.get("sparseGraphRun", {}).pop("elapsedSeconds", None)
    return "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    manifest = _verify_manifest_artifact(args.icpsr_manifest, args.icpsr_concepts)
    projection = build_endpoint_projection(
        _read_jsonl(args.icpsr_concepts),
        expected_members=EXPECTED_RELEASE_MEMBERS,
        expected_preferred=EXPECTED_PREFERRED_ENDPOINTS,
        expected_alternate=EXPECTED_ALTERNATE_MEMBERS,
    )
    baseline_cases = shared_benchmark.atlas_cases(args.root)
    cases = project_alignment_cases(baseline_cases, projection)
    baseline_codec = lexical_benchmark.PairCodec.from_cases(baseline_cases)
    codec = lexical_benchmark.PairCodec.from_cases(cases)
    if (baseline_codec.case_names, baseline_codec.sources, baseline_codec.targets) != (
        codec.case_names,
        codec.sources,
        codec.targets,
    ):
        raise ValueError("preferred projection changed the existing mapping endpoint axes")
    baseline_pairs = _read_baseline_pairs(args.baseline_pairs, codec)
    gold = lexical_benchmark._gold_codes(cases, codec)
    mapping_relations = lexical_benchmark._mapping_relations(args.root, cases, "atlas")
    relation_by_code = {code: mapping_relations[codec.decode(code)] for code in gold}
    gold_by_relation = {
        relation: frozenset(code for code, value in relation_by_code.items() if value == relation)
        for relation in frontier.RELATION_TYPES
    }
    gold_by_case = tuple(
        frozenset(code for code in gold if code >> frontier.CASE_SHIFT == case_index)
        for case_index in range(len(codec.case_names))
    )

    sparse_report, sparse_string_ranks = shared_benchmark.sparse_benchmark(cases, frontier.DEPTHS)
    sparse_ranks = frontier._encode_sparse_ranks(sparse_string_ranks, codec)
    sparse_sets = frontier._sets_by_depth(sparse_ranks, frontier.DEPTHS)
    lexical_ranks: dict[int, int] = {}
    lexical_arms = []
    for name in frontier.SELECTED_ARM_NAMES:
        arm_report, arm_ranks, _coverage = lexical_benchmark.run_arm(
            cases,
            spec=lexical_benchmark.SCORER_BY_NAME[name],
            top_ks=frontier.DEPTHS,
            codec=codec,
            gold=gold,
            workers=args.workers,
            block_size=args.block_size,
        )
        lexical_benchmark._update_union(lexical_ranks, arm_ranks)
        lexical_arms.append({**arm_report, "pairRankDigest": frontier._rank_digest(arm_ranks)})
    lexical_sets = frontier._sets_by_depth(lexical_ranks, frontier.DEPTHS)
    combinations = [
        frontier.summarize_combination(
            lexical_depth=lexical_depth,
            sparse_depth=sparse_depth,
            lexical_pairs=lexical_sets[lexical_depth],
            sparse_pairs=sparse_sets[sparse_depth],
            gold=gold,
            gold_by_case=gold_by_case,
            gold_by_relation=gold_by_relation,
            codec=codec,
        )
        for lexical_depth in frontier.DEPTHS
        for sparse_depth in frontier.DEPTHS
    ]
    lean = lexical_sets[3] | sparse_sets[1]
    added = lean - baseline_pairs
    removed = baseline_pairs - lean
    by_case = []
    for case_index, case_name in enumerate(codec.case_names):
        baseline_case = frozenset(code for code in baseline_pairs if code >> frontier.CASE_SHIFT == case_index)
        lean_case = frozenset(code for code in lean if code >> frontier.CASE_SHIFT == case_index)
        by_case.append(
            {
                "case": case_name,
                "baselineCandidates": len(baseline_case),
                "projectedCandidates": len(lean_case),
                "delta": len(lean_case) - len(baseline_case),
                "added": len(lean_case - baseline_case),
                "removed": len(baseline_case - lean_case),
            }
        )
    complete = [row for row in combinations if row["found"] == len(gold)]
    minimum = min(row["candidates"] for row in complete)
    hop_counts = Counter(int(row["hops"]) for row in projection.access_paths)
    report: dict[str, Any] = {
        "type": "AtlasIcpsrPreferredEndpointAliasExperiment",
        "schemaVersion": "1.0",
        "productionIntegration": "none",
        "languageScope": "English",
        "inputs": {
            "atlasRoot": str(args.root),
            "icpsrManifest": {"path": str(args.icpsr_manifest), "sha256": _sha256(args.icpsr_manifest)},
            "icpsrConcepts": {"path": str(args.icpsr_concepts), "sha256": _sha256(args.icpsr_concepts)},
            "baselinePairs": {"path": str(args.baseline_pairs), "sha256": _sha256(args.baseline_pairs)},
            "managedReleaseId": manifest.get("id"),
        },
        "projection": {
            "releaseMembers": len(projection.all_members),
            "preferredEndpoints": len(projection.preferred_members),
            "alternateMembers": len(projection.alternate_members),
            "reachableAccessTerms": len(projection.access_paths),
            "preferredEndpointsWithAliases": len(projection.aliases_by_preferred),
            "unresolvedAlternateCount": len(projection.unresolved_alternates),
            "unresolvedAlternates": list(projection.unresolved_alternates),
            "pathHopCounts": {str(key): value for key, value in sorted(hop_counts.items())},
            "projectionDigest": projection.digest,
        },
        "baseline": {
            "candidates": len(baseline_pairs),
            "found": len(baseline_pairs & gold),
            "pairSetDigest": frontier._pair_digest(baseline_pairs, codec),
        },
        "projectedLeanFloor": {
            "lexicalK": 3,
            "sparseGraphK": 1,
            "candidates": len(lean),
            "found": len(lean & gold),
            "pairSetDigest": frontier._pair_digest(lean, codec),
            "delta": len(lean) - len(baseline_pairs),
            "added": len(added),
            "removed": len(removed),
            "addedGold": len(added & gold),
            "removedGold": len(removed & gold),
            "byCase": by_case,
        },
        "minimumComplete": [
            {
                "lexicalK": row["lexicalK"],
                "sparseGraphK": row["sparseGraphK"],
                "candidates": row["candidates"],
                "pairSetDigest": row["pairSetDigest"],
            }
            for row in complete
            if row["candidates"] == minimum
        ],
        "combinations": combinations,
        "lexicalArms": lexical_arms,
        "sparseGraphRun": sparse_report,
        "corpusDigest": shared_benchmark._case_digest(cases)["corpus"],
        "goldDigest": shared_benchmark._case_digest(cases)["gold"],
        "toolDigests": {
            "experiment": _sha256(Path(__file__).resolve()),
            "shared": _sha256(Path(shared_benchmark.__file__).resolve()),
            "lexical": _sha256(Path(lexical_benchmark.__file__).resolve()),
            "frontier": _sha256(Path(frontier.__file__).resolve()),
        },
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    report["deterministicResultDigest"] = _deterministic_digest(report)
    return report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--icpsr-manifest", type=Path, required=True)
    parser.add_argument("--icpsr-concepts", type=Path, required=True)
    parser.add_argument("--baseline-pairs", type=Path, required=True)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=-1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.block_size <= 0:
        parser.error("--block-size must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "deterministicResultDigest": report["deterministicResultDigest"],
                "elapsedSeconds": report["elapsedSeconds"],
                "output": str(args.output),
                "outputDigest": _sha256(args.output),
                "projectedLeanFloor": report["projectedLeanFloor"],
                "projection": report["projection"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

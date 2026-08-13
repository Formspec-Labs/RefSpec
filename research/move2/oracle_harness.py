#!/usr/bin/env python3
"""Differential oracle for compiler-emitted adjudication SHACL-SPARQL.

The Python implementation below is copied and reduced from the four relevant
parts of ``bindings/atlas/3.1/tools/validate.py``. It deliberately imports
neither that module nor RuleSpec compiler code: importing the implementation
being replaced would make agreement circular.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from itertools import combinations
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SH, SKOS

ROOT = Path(__file__).resolve().parents[2]
BINDING = ROOT / "bindings/atlas/3.1"
FIXTURES = BINDING / "fixtures"
SHAPES_PATH = BINDING / "shapes/rulespec-adjudication.shacl.ttl"

RKAF = Namespace("https://rulespec.org/ns/v1#")
CASE = Namespace("urn:ref:move2-oracle:")

RULE_SHAPES = {
    "independence": RKAF.MachineAdjudicationFiveAxisIndependenceShape,
    "complete-support": RKAF.MachineAdjudicationIssuedProofCitationShape,
    "verdict-lattice": RKAF.MachineAdjudicationVerdictLatticeFoldShape,
    "proof-replay": RKAF.MachineAdjudicationProofReplayShape,
}

CORPUS_EXPECTED = {
    "adjudication-single-proof": {"independence"},
    "adjudication-same-validator-actor": {"independence"},
    "adjudication-same-independence-group": {"independence"},
    "adjudication-same-provider": {"independence"},
    "adjudication-same-provider-model": {"independence"},
    "adjudication-same-response-artifact": {"independence"},
    "adjudication-discarded-support": {"complete-support"},
    "adjudication-relation-not-licensed": {"verdict-lattice"},
    "adjudication-verdicts-disagree": {"verdict-lattice"},
    "adjudication-foreign-comparison": {"proof-replay"},
    "all-resource-profiles": set(),
    "qualified-three-machine-support": set(),
    "qualified-lattice-branches": set(),
    "adjudication-refused-comparison-record": set(),
}


def _one(graph: Graph, subject: URIRef, predicate: URIRef) -> object:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        raise AssertionError(
            f"oracle input requires one {predicate} on {subject}; found {len(values)}"
        )
    return values[0]


def _fold_verdicts(verdicts: frozenset[object]) -> URIRef | None:
    """Copied oracle for validate.py::_adjudicated_relation."""
    if verdicts == {RKAF.verdictSame}:
        return SKOS.exactMatch
    if verdicts <= {RKAF.verdictSame, RKAF.verdictNearSame} and (
        RKAF.verdictNearSame in verdicts
    ):
        return SKOS.closeMatch
    if verdicts == {RKAF.verdictTargetBroader}:
        return SKOS.broadMatch
    if verdicts == {RKAF.verdictTargetNarrower}:
        return SKOS.narrowMatch
    if verdicts == {RKAF.verdictRelated}:
        return SKOS.relatedMatch
    return None


def python_oracle(graph: Graph) -> set[str]:
    """Verdicts from the copied old Python behavior for the four rules."""
    violations: set[str] = set()
    comparisons = set(graph.subjects(RDF.type, RKAF.RelationComparisonContext))
    proofs = set(graph.subjects(RDF.type, RKAF.ResolverProofRecord))

    for proof in proofs:
        comparison = _one(graph, proof, RKAF.proofComparisonContext)
        if proof not in set(graph.objects(comparison, RKAF.comparisonProofRecord)):
            violations.add("complete-support")
        citing = {
            subject
            for subject in graph.subjects(RKAF.comparisonProofRecord, proof)
            if subject in comparisons
        }
        if len(citing) > 1:
            violations.add("proof-replay")

    for comparison in comparisons:
        if _one(graph, comparison, RKAF.comparisonOutcome) != RKAF.comparisonSatisfied:
            continue
        cited = set(graph.objects(comparison, RKAF.comparisonProofRecord))
        facts: list[tuple[object, ...]] = []
        for proof in cited:
            issuer = _one(graph, proof, RKAF.proofIssuer)
            lineage = _one(graph, proof, RKAF.hasAILineage)
            facts.append(
                (
                    issuer,
                    _one(graph, proof, RKAF.independenceGroup),
                    _one(graph, issuer, RKAF.proofResolver),
                    str(_one(graph, lineage, RKAF.modelId)),
                    _one(graph, proof, RKAF.sealedResponseArtifact),
                )
            )
        if not any(
            all(left[index] != right[index] for index in range(5))
            for left, right in combinations(facts, 2)
        ):
            violations.add("independence")

        assertion = _one(graph, comparison, RKAF.comparisonExpectedAssertion)
        stated_relation = _one(graph, assertion, RDF.predicate)
        verdicts = frozenset(
            _one(graph, proof, RKAF.adjudicationVerdict) for proof in cited
        )
        if _fold_verdicts(verdicts) != stated_relation:
            violations.add("verdict-lattice")
    return violations


def shape_oracle(graph: Graph) -> set[str]:
    """Run each emitted rule alone so its Boolean verdict has a stable ID."""
    all_shapes = Graph().parse(SHAPES_PATH, format="turtle")
    target_predicates = (
        SH.targetClass,
        SH.targetNode,
        SH.targetSubjectsOf,
        SH.targetObjectsOf,
    )
    violations: set[str] = set()
    for rule, keep in RULE_SHAPES.items():
        shapes = Graph()
        for triple in all_shapes:
            shapes.add(triple)
        for predicate in target_predicates:
            for subject, obj in list(shapes.subject_objects(predicate)):
                if subject != keep:
                    shapes.remove((subject, predicate, obj))
        conforms, _, _ = shacl_validate(
            graph,
            shacl_graph=shapes,
            inference="none",
            advanced=True,
            inplace=False,
            abort_on_first=False,
            meta_shacl=False,
        )
        if not conforms:
            violations.add(rule)
    return violations


def _fixture_path(case_id: str) -> Path:
    corpus = json.loads((FIXTURES / "corpus.json").read_bytes())
    row = next(row for row in corpus["cases"] if row["id"] == case_id)
    return FIXTURES / row["path"]


def _fixture_graph(case_id: str) -> Graph:
    root = _fixture_path(case_id)
    if not root.is_dir():
        raise SystemExit(
            f"fixture {case_id} is not built; run "
            "bindings/atlas/3.1/tools/build_fixtures.py first"
        )
    manifest = json.loads((root / "atlas-manifest.json").read_bytes())
    asserted_id = URIRef(
        next(row["id"] for row in manifest["graphs"] if row["role"] == "asserted")
    )
    dataset = Dataset()
    for pack in manifest["packs"]:
        payload = (root / pack["path"]).read_bytes()
        if pack["transport"]["compression"] == "zstd":
            try:
                from compression import zstd
            except ImportError:
                from backports import zstd
            payload = zstd.decompress(payload)
        dataset.parse(data=payload.decode("utf-8"), format="nquads")
    source = dataset.graph(asserted_id)
    graph = Graph()
    for triple in source:
        graph.add(triple)
    return graph


def _add_proof(graph: Graph, key: str, *, cite: bool = True) -> URIRef:
    proof = CASE[f"proof-{key}"]
    issuer = CASE[f"issuer-{key}"]
    lineage = CASE[f"lineage-{key}"]
    graph.add((proof, RDF.type, RKAF.ResolverProofRecord))
    graph.add((proof, RKAF.proofComparisonContext, CASE.comparison))
    graph.add((proof, RKAF.proofIssuer, issuer))
    graph.add((proof, RKAF.independenceGroup, CASE[f"group-{key}"]))
    graph.add((proof, RKAF.hasAILineage, lineage))
    graph.add((proof, RKAF.sealedResponseArtifact, CASE[f"response-{key}"]))
    graph.add((proof, RKAF.adjudicationVerdict, RKAF.verdictSame))
    graph.add((issuer, RKAF.proofResolver, CASE[f"provider-{key}"]))
    graph.add((lineage, RKAF.modelId, Literal(f"model-{key}")))
    if cite:
        graph.add((CASE.comparison, RKAF.comparisonProofRecord, proof))
    return proof


def _base_graph() -> Graph:
    graph = Graph()
    graph.add((CASE.comparison, RDF.type, RKAF.RelationComparisonContext))
    graph.add((CASE.comparison, RKAF.comparisonOutcome, RKAF.comparisonSatisfied))
    graph.add((CASE.comparison, RKAF.comparisonExpectedAssertion, CASE.assertion))
    graph.add((CASE.assertion, RDF.predicate, SKOS.exactMatch))
    _add_proof(graph, "alpha")
    _add_proof(graph, "beta")
    return graph


def _clone(graph: Graph) -> Graph:
    result = Graph()
    for triple in graph:
        result.add(triple)
    return result


def _replace(graph: Graph, subject: URIRef, predicate: URIRef, value: object) -> None:
    graph.remove((subject, predicate, None))
    graph.add((subject, predicate, value))


def mutation_cases() -> dict[str, tuple[Graph, set[str]]]:
    base = _base_graph()
    cases: dict[str, tuple[Graph, set[str]]] = {"valid-exact": (base, set())}

    single = _clone(base)
    single.remove((CASE["proof-beta"], None, None))
    single.remove((CASE.comparison, RKAF.comparisonProofRecord, CASE["proof-beta"]))
    cases["single-proof"] = (single, {"independence"})

    axis_changes = {
        "same-actor": (CASE["proof-beta"], RKAF.proofIssuer, CASE["issuer-alpha"]),
        "same-group": (
            CASE["proof-beta"],
            RKAF.independenceGroup,
            CASE["group-alpha"],
        ),
        "same-response": (
            CASE["proof-beta"],
            RKAF.sealedResponseArtifact,
            CASE["response-alpha"],
        ),
        "same-provider": (
            CASE["issuer-beta"],
            RKAF.proofResolver,
            CASE["provider-alpha"],
        ),
        "same-model": (
            CASE["lineage-beta"],
            RKAF.modelId,
            Literal("model-alpha"),
        ),
    }
    for name, (subject, predicate, value) in axis_changes.items():
        graph = _clone(base)
        _replace(graph, subject, predicate, value)
        cases[name] = (graph, {"independence"})

    discarded = _clone(base)
    _add_proof(discarded, "gamma", cite=False)
    cases["discarded-support"] = (discarded, {"complete-support"})

    replay = _clone(base)
    replay.add((CASE.otherComparison, RDF.type, RKAF.RelationComparisonContext))
    replay.add((CASE.otherComparison, RKAF.comparisonOutcome, RKAF.comparisonRefused))
    replay.add(
        (CASE.otherComparison, RKAF.comparisonProofRecord, CASE["proof-alpha"])
    )
    cases["proof-replay"] = (replay, {"proof-replay"})

    mixed_exact = _clone(base)
    _replace(
        mixed_exact,
        CASE["proof-beta"],
        RKAF.adjudicationVerdict,
        RKAF.verdictNearSame,
    )
    cases["exact-with-near"] = (mixed_exact, {"verdict-lattice"})

    valid_close = _clone(mixed_exact)
    _replace(valid_close, CASE.assertion, RDF.predicate, SKOS.closeMatch)
    cases["valid-close"] = (valid_close, set())

    close_without_near = _clone(base)
    _replace(close_without_near, CASE.assertion, RDF.predicate, SKOS.closeMatch)
    cases["close-without-near"] = (close_without_near, {"verdict-lattice"})

    branches = (
        ("valid-broad", SKOS.broadMatch, RKAF.verdictTargetBroader, set()),
        ("valid-narrow", SKOS.narrowMatch, RKAF.verdictTargetNarrower, set()),
        ("valid-related", SKOS.relatedMatch, RKAF.verdictRelated, set()),
        ("broad-with-same", SKOS.broadMatch, RKAF.verdictSame, {"verdict-lattice"}),
        ("narrow-with-same", SKOS.narrowMatch, RKAF.verdictSame, {"verdict-lattice"}),
        ("related-with-same", SKOS.relatedMatch, RKAF.verdictSame, {"verdict-lattice"}),
    )
    for name, relation, verdict, expected in branches:
        graph = _clone(base)
        _replace(graph, CASE.assertion, RDF.predicate, relation)
        for key in ("alpha", "beta"):
            _replace(
                graph,
                CASE[f"proof-{key}"],
                RKAF.adjudicationVerdict,
                verdict,
            )
        cases[name] = (graph, expected)

    unknown = _clone(base)
    _replace(unknown, CASE.assertion, RDF.predicate, CASE.unsupportedRelation)
    cases["unsupported-relation"] = (unknown, {"verdict-lattice"})

    refused = _clone(mixed_exact)
    _replace(
        refused,
        CASE.comparison,
        RKAF.comparisonOutcome,
        RKAF.comparisonRefused,
    )
    cases["refused-does-not-fold"] = (refused, set())
    return cases


def _run_case(kind: str, case_id: str, graph: Graph, expected: set[str]) -> dict[str, object]:
    python = python_oracle(graph)
    shacl = shape_oracle(graph)
    if python != shacl or python != expected:
        raise AssertionError(
            f"{kind}/{case_id}: expected={sorted(expected)}, "
            f"python={sorted(python)}, shacl={sorted(shacl)}"
        )
    return {
        "expected": sorted(expected),
        "id": case_id,
        "kind": kind,
        "python": sorted(python),
        "shacl": sorted(shacl),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research/move2/measurements.json",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    results = [
        _run_case("corpus", case_id, _fixture_graph(case_id), expected)
        for case_id, expected in CORPUS_EXPECTED.items()
    ]
    results.extend(
        _run_case("mutation", case_id, graph, expected)
        for case_id, (graph, expected) in mutation_cases().items()
    )
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mib = peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    summary = {
        "corpusCases": sum(row["kind"] == "corpus" for row in results),
        "corpusRuleChecks": 4 * sum(row["kind"] == "corpus" for row in results),
        "elapsedSeconds": round(elapsed, 3),
        "engine": "pySHACL 0.31.0",
        "mutationCases": sum(row["kind"] == "mutation" for row in results),
        "mutationRuleChecks": 4
        * sum(row["kind"] == "mutation" for row in results),
        "peakRssMiB": round(peak_mib, 1),
        "results": results,
        "status": "PASS",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"move-2 oracle PASS: {summary['corpusCases']} corpus + "
        f"{summary['mutationCases']} mutation cases in {summary['elapsedSeconds']}s; "
        f"peak RSS {summary['peakRssMiB']} MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

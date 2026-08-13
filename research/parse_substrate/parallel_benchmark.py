#!/usr/bin/env python3
"""Measure bounded multiprocess pack parsing with read-only shard graphs.

Workers parse independent packs into separate two-index stores and pickle the
store indexes.  The parent reloads each shard without reinserting triples,
unions the shard graphs through ``ReadOnlyGraphAggregate``, merges the parser
observations, and runs the unchanged semantic validator.
"""

from __future__ import annotations

import argparse
import json
import pickle
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from rdflib import Dataset, Graph, URIRef, __version__ as rdflib_version
from rdflib.graph import ReadOnlyGraphAggregate

from benchmark import _install_term_interner, _load_validator, _max_rss_mib
from stores import ProfiledTwoIndexStore, _ContextIndex


def _worker_rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024 if sys.platform == "darwin" else 1024)


def _parse_shard(task: dict[str, Any]) -> dict[str, Any]:
    validator = _load_validator()
    if task["terms"] == "interned":
        _install_term_interner(validator)
    root = Path(task["distribution"])
    graph_ids = {role: URIRef(value) for role, value in task["graph_ids"].items()}
    placement = validator._AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=validator._projection_only_predicates(),
    )
    node_digests = validator._AssertedNodeDigests(graph_ids["asserted"])
    subject_owners: dict[str, dict[Any, str]] = {role: {} for role in graph_ids}
    store = ProfiledTwoIndexStore()
    dataset = Dataset(store=store)
    aggregate_counts: dict[Any, int] = {}
    started = time.perf_counter()
    cpu_started = time.process_time()
    for pack in task["packs"]:
        counts = validator._parse_pack_into_dataset(
            dataset,
            root,
            pack,
            graph_ids,
            subject_owners,
            asserted_placement=placement,
            node_digests=node_digests,
        )
        node_digests.finish()
        for graph_id, count in counts.items():
            aggregate_counts[graph_id] = aggregate_counts.get(graph_id, 0) + count
    parse_wall = time.perf_counter() - started
    parse_cpu = time.process_time() - cpu_started

    payload = {
        "contexts": [
            (identifier, index.spo, index.pos, index.size)
            for identifier, index in store._contexts.items()
        ],
        "subject_owners": subject_owners,
        "placement_types": placement.types,
        "placement_verdicts": placement.verdicts,
        "placement_first_violation": placement.first_violation,
        "node_digests": node_digests._digests,
        "counts": aggregate_counts,
    }
    serialization_started = time.perf_counter()
    output = Path(task["output"])
    with output.open("wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
    serialization_wall = time.perf_counter() - serialization_started
    return {
        "worker": task["worker"],
        "quad_count": sum(pack["content"]["quadCount"] for pack in task["packs"]),
        "pack_count": len(task["packs"]),
        "parse_wall_seconds": parse_wall,
        "parse_cpu_seconds": parse_cpu,
        "serialization_wall_seconds": serialization_wall,
        "max_rss_mib": _worker_rss_mib(),
        "pickle_bytes": output.stat().st_size,
    }


def _balanced_shards(packs: list[dict[str, Any]], workers: int) -> list[list[dict[str, Any]]]:
    """Assign largest packs first to the least-loaded worker."""

    shards: list[list[dict[str, Any]]] = [[] for _ in range(workers)]
    loads = [0] * workers
    for pack in sorted(packs, key=lambda item: item["content"]["quadCount"], reverse=True):
        target = min(range(workers), key=loads.__getitem__)
        shards[target].append(pack)
        loads[target] += pack["content"]["quadCount"]
    return shards


def _restore_store(contexts: list[tuple[Any, Any, Any, int]]) -> ProfiledTwoIndexStore:
    store = ProfiledTwoIndexStore()
    for identifier, spo, pos, size in contexts:
        graph = Graph(store=store, identifier=identifier)
        store._contexts[identifier] = _ContextIndex(graph=graph, spo=spo, pos=pos, size=size)
    return store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--terms", choices=("stock", "interned"), default="stock")
    parser.add_argument("--worker-task", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker_task is not None:
        with args.worker_task.open("rb") as stream:
            task = pickle.load(stream)
        print(json.dumps(_parse_shard(task), sort_keys=True))
        return 0
    if args.distribution is None:
        parser.error("--distribution is required")

    validator = _load_validator()
    manifest = validator._load_json(args.distribution / validator.MANIFEST_FILE, require_canonical=True)
    graph_ids = validator._check_pack_manifest(manifest)
    members = {member["role"]: member for member in manifest["members"]}
    accounting = validator._load_json(
        args.distribution / members["sourceAccounting"]["path"], require_canonical=True
    )
    acceptance = validator._load_json(
        args.distribution / members["acceptance"]["path"], require_canonical=True
    )
    construction = validator._load_json(
        args.distribution / members["constructionSummary"]["path"], require_canonical=True
    )
    member_digests = {member["path"]: member["digest"] for member in manifest["members"]}
    shards = _balanced_shards(manifest["packs"], args.workers)

    started = time.perf_counter()
    cpu_started = time.process_time()
    with tempfile.TemporaryDirectory(prefix="atlas-parse-shards-") as temporary:
        tasks = [
            {
                "worker": position,
                "distribution": str(args.distribution),
                "graph_ids": {role: str(identifier) for role, identifier in graph_ids.items()},
                "packs": shard,
                "terms": args.terms,
                "output": str(Path(temporary) / f"shard-{position}.pickle"),
            }
            for position, shard in enumerate(shards)
            if shard
        ]
        processes = []
        for task in tasks:
            task_path = Path(temporary) / f"task-{task['worker']}.pickle"
            with task_path.open("wb") as stream:
                pickle.dump(task, stream, protocol=pickle.HIGHEST_PROTOCOL)
            processes.append(
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--worker-task", str(task_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        worker_results = []
        for process in processes:
            stdout, stderr = process.communicate()
            if process.returncode:
                raise RuntimeError(f"parallel parser failed: {stderr.strip()}")
            worker_results.append(json.loads(stdout))
        workers_wall = time.perf_counter() - started

        load_started = time.perf_counter()
        payloads = []
        stores = []
        for task in tasks:
            with Path(task["output"]).open("rb") as stream:
                payload = pickle.load(stream)
            payloads.append(payload)
            stores.append(_restore_store(payload["contexts"]))
        load_wall = time.perf_counter() - load_started

        role_graphs: dict[str, Graph] = {}
        for role, identifier in graph_ids.items():
            shard_graphs = [
                Graph(store=store, identifier=identifier)
                for store in stores
                if identifier in store._contexts
            ]
            role_graphs[role] = (
                ReadOnlyGraphAggregate(shard_graphs)
                if shard_graphs
                else Graph(store=ProfiledTwoIndexStore(), identifier=identifier)
            )

        asserted = role_graphs["asserted"]
        placement = validator._AssertedPlacementObservation(
            graph_id=asserted.identifier,
            projection_only_predicates=validator._projection_only_predicates(),
        )
        node_digests = validator._AssertedNodeDigests(graph_ids["asserted"])
        subject_owners: dict[str, dict[Any, str]] = {role: {} for role in graph_ids}
        for payload in payloads:
            for role, owners in payload["subject_owners"].items():
                overlap = subject_owners[role].keys() & owners.keys()
                if overlap:
                    raise RuntimeError(f"cross-shard subject overlap for {role}: {next(iter(overlap))}")
                subject_owners[role].update(owners)
            placement.types.update(payload["placement_types"])
            placement.verdicts.update(payload["placement_verdicts"])
            if placement.first_violation is None:
                placement.first_violation = payload["placement_first_violation"]
            node_digests._digests.update(payload["node_digests"])

        validator._check_asserted_pack_dependencies(asserted, manifest, subject_owners["asserted"])
        parse_and_merge_wall = time.perf_counter() - started
        result = validator._validate_semantics_then_record_ownership(
            manifest,
            accounting,
            acceptance,
            role_graphs,
            construction,
            member_digests=member_digests,
            asserted_placement=placement,
            node_digests=node_digests,
        )

    measurement = {
        "phase": "parallel-semantic",
        "workers": args.workers,
        "terms": args.terms,
        "rdflib": rdflib_version,
        "quad_count": sum(row["quadCount"] for row in manifest["graphs"]),
        "workers_wall_seconds": workers_wall,
        "parent_load_wall_seconds": load_wall,
        "parse_merge_wall_seconds": parse_and_merge_wall,
        "wall_seconds": time.perf_counter() - started,
        "parent_cpu_seconds": time.process_time() - cpu_started,
        "parent_max_rss_mib": _max_rss_mib(),
        "worker_max_rss_mib": [row["max_rss_mib"] for row in worker_results],
        "bounded_peak_rss_mib": max(
            sum(row["max_rss_mib"] for row in worker_results),
            _max_rss_mib(),
        ),
        "worker_results": worker_results,
        "result": result,
    }
    print(json.dumps(measurement, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

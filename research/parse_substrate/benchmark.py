#!/usr/bin/env python3
"""Measure Atlas parsing and validation with interchangeable rdflib stores.

Run this script in a fresh process for each sample because ``ru_maxrss`` and
rdflib caches are process-wide high-water marks.  It prints one JSON object;
validator progress remains on stderr.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

from rdflib import Dataset, Graph, URIRef, __version__ as rdflib_version

from rdflib.plugins.parsers.ntriples import URI, r_literal, r_uriref, unquote, uriquote
from rdflib.plugins.stores.memory import Memory

from stores import (
    ProfiledMemory,
    ProfiledTwoIndexListStore,
    ProfiledTwoIndexStore,
    TwoIndexStore,
)

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "bindings" / "atlas" / "3.1" / "tools" / "validate.py"
VALIDATOR_TOOLS = VALIDATOR_PATH.parent


def _load_validator():
    sys.path.insert(0, str(VALIDATOR_TOOLS))
    spec = importlib.util.spec_from_file_location("atlas_parse_benchmark_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator from {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _max_rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux and most BSDs report KiB.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return value / divisor


def _store_factory(name: str):
    factories = {
        "memory": ProfiledMemory,
        "memory-plain": Memory,
        "two-index": ProfiledTwoIndexStore,
        "two-index-plain": TwoIndexStore,
        "two-index-list": ProfiledTwoIndexListStore,
    }
    return factories[name]


def _query_stats(store: Any) -> dict[str, dict[str, int]]:
    method = getattr(store, "query_stats", None)
    return method() if method is not None else {}


def _install_term_interner(validator: Any) -> dict[str, dict[Any, Any]]:
    """Replace only term construction with a strong per-run term pool."""

    pools: dict[str, dict[Any, Any]] = {"iris": {}, "literals": {}}

    class CachedLiteral(validator.Literal):
        __slots__ = ("_atlas_cached_hash",)

        def __new__(
            cls,
            lexical_or_value: Any,
            lang: str | None = None,
            datatype: str | None = None,
            normalize: bool | None = None,
        ):
            value = super().__new__(
                cls,
                lexical_or_value,
                lang=lang,
                datatype=datatype,
                normalize=normalize,
            )
            value._atlas_cached_hash = validator.Literal.__hash__(value)
            return value

        def __hash__(self) -> int:
            return self._atlas_cached_hash

    class InterningParser(validator._LexicalNQuadsParser):
        def uriref(self):
            if not self.peek("<"):
                return False
            lexical = sys.intern(uriquote(unquote(self.eat(r_uriref).group(1))))
            term = pools["iris"].get(lexical)
            if term is None:
                term = URI(lexical)
                pools["iris"][lexical] = term
            return term

        def literal(self):
            if not self.peek('"'):
                return False
            lexical, language, datatype = self.eat(r_literal).groups()
            if language and datatype:
                raise validator.ParseError("Can't have both a language and a datatype")
            lexical = sys.intern(unquote(lexical))
            language = sys.intern(language) if language else None
            datatype_node = self.uriref_from_lexical(datatype) if datatype else None
            key = (lexical, language, datatype_node)
            term = pools["literals"].get(key)
            if term is None:
                term = CachedLiteral(
                    lexical,
                    lang=language,
                    datatype=datatype_node,
                    normalize=False,
                )
                pools["literals"][key] = term
            return term

        @staticmethod
        def uriref_from_lexical(lexical: str):
            value = sys.intern(uriquote(unquote(lexical)))
            term = pools["iris"].get(value)
            if term is None:
                term = URI(value)
                pools["iris"][value] = term
            return term

    validator._LexicalNQuadsParser = InterningParser
    return pools


def _install_context_cache() -> None:
    """Cache the Graph view returned for repeated N-Quads context IDs."""

    original = Dataset.get_context

    def cached_get_context(
        self: Dataset,
        identifier: Any,
        quoted: bool = False,
        base: str | None = None,
    ) -> Graph:
        cache = self.__dict__.setdefault("_atlas_context_graphs", {})
        key = (identifier, quoted, base)
        graph = cache.get(key)
        if graph is None:
            graph = original(self, identifier, quoted=quoted, base=base)
            cache[key] = graph
        return graph

    Dataset.get_context = cached_get_context


def _patch_dataset(validator: Any, store_factory: Any, stores: list[Any]) -> None:
    def make_dataset(*_args: Any, **_kwargs: Any) -> Dataset:
        store = store_factory()
        stores.append(store)
        return Dataset(store=store)

    validator.Dataset = make_dataset


def _manifest_and_graph_ids(validator: Any, distribution: Path):
    manifest = validator._load_json(distribution / validator.MANIFEST_FILE, require_canonical=True)
    graph_ids = validator._check_pack_manifest(manifest)
    return manifest, graph_ids


def _parse_only(validator: Any, distribution: Path, store_factory: Any):
    manifest, graph_ids = _manifest_and_graph_ids(validator, distribution)
    placement = validator._AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=validator._projection_only_predicates(),
    )
    node_digests = validator._AssertedNodeDigests(graph_ids["asserted"])
    store = store_factory()
    dataset = Dataset(store=store)
    original_dataset = validator.Dataset
    validator.Dataset = lambda *_args, **_kwargs: dataset
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        parsed_dataset, graphs = validator._parse_packed_dataset(
            distribution,
            manifest,
            graph_ids,
            asserted_placement=placement,
            node_digests=node_digests,
        )
    finally:
        validator.Dataset = original_dataset
    elapsed = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    assert parsed_dataset is dataset
    return {
        "phase": "parse",
        "wall_seconds": elapsed,
        "cpu_seconds": cpu,
        "quad_count": sum(len(graph) for graph in graphs.values()),
        "max_rss_mib": _max_rss_mib(),
        "query_stats": _query_stats(store),
    }


def _validate(validator: Any, distribution: Path, store_factory: Any):
    stores: list[Any] = []
    _patch_dataset(validator, store_factory, stores)
    parse_measurement: dict[str, float] = {}
    original_parse = validator._parse_packed_dataset

    def measured_parse(*args: Any, **kwargs: Any):
        started = time.perf_counter()
        cpu_started = time.process_time()
        result = original_parse(*args, **kwargs)
        parse_measurement.update(
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu_started,
            max_rss_mib=_max_rss_mib(),
        )
        return result

    validator._parse_packed_dataset = measured_parse
    started = time.perf_counter()
    cpu_started = time.process_time()
    result = validator.validate_distribution(distribution)
    elapsed = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    if len(stores) != 1:
        raise RuntimeError(f"expected one data store, created {len(stores)}")
    return {
        "phase": "validate",
        "wall_seconds": elapsed,
        "cpu_seconds": cpu,
        "max_rss_mib": _max_rss_mib(),
        "parse": parse_measurement,
        "result": result,
        "query_stats": _query_stats(stores[0]),
    }


def _semantic_validation(validator: Any, distribution: Path, store_factory: Any):
    """Run the complete graph-dependent path, bypassing outer JSON admission.

    This mode is useful when a shared artifact's metadata was minted by a
    different binding revision but its RDF pack digests remain the measured
    ones.  It still runs the real shapes, every semantic check, and compact
    record ownership.
    """

    manifest, graph_ids = _manifest_and_graph_ids(validator, distribution)
    members = {member["role"]: member for member in manifest["members"]}
    accounting = validator._load_json(
        distribution / members["sourceAccounting"]["path"],
        require_canonical=True,
    )
    acceptance = validator._load_json(
        distribution / members["acceptance"]["path"],
        require_canonical=True,
    )
    construction = validator._load_json(
        distribution / members["constructionSummary"]["path"],
        require_canonical=True,
    )
    member_digests = {member["path"]: member["digest"] for member in manifest["members"]}
    placement = validator._AssertedPlacementObservation(
        graph_id=graph_ids["asserted"],
        projection_only_predicates=validator._projection_only_predicates(),
    )
    node_digests = validator._AssertedNodeDigests(graph_ids["asserted"])
    store = store_factory()
    dataset = Dataset(store=store)
    original_dataset = validator.Dataset
    validator.Dataset = lambda *_args, **_kwargs: dataset
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        parse_started = time.perf_counter()
        parse_cpu_started = time.process_time()
        parsed_dataset, graphs = validator._parse_packed_dataset(
            distribution,
            manifest,
            graph_ids,
            asserted_placement=placement,
            node_digests=node_digests,
        )
        parse_measurement = {
            "wall_seconds": time.perf_counter() - parse_started,
            "cpu_seconds": time.process_time() - parse_cpu_started,
            "max_rss_mib": _max_rss_mib(),
        }
        result = validator._validate_semantics_then_record_ownership(
            manifest,
            accounting,
            acceptance,
            graphs,
            construction,
            member_digests=member_digests,
            asserted_placement=placement,
            node_digests=node_digests,
        )
    finally:
        validator.Dataset = original_dataset
    assert parsed_dataset is dataset
    return {
        "phase": "semantic",
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "max_rss_mib": _max_rss_mib(),
        "parse": parse_measurement,
        "result": result,
        "query_stats": _query_stats(store),
    }


def _binding_validation(validator: Any, store_factory: Any):
    stores: list[Any] = []
    _patch_dataset(validator, store_factory, stores)
    started = time.perf_counter()
    cpu_started = time.process_time()
    result = validator.validate_binding()
    aggregate_calls: dict[str, int] = {}
    aggregate_rows: dict[str, int] = {}
    for store in stores:
        for pattern, row in _query_stats(store).items():
            aggregate_calls[pattern] = aggregate_calls.get(pattern, 0) + row["calls"]
            aggregate_rows[pattern] = aggregate_rows.get(pattern, 0) + row["rows"]
    return {
        "phase": "binding",
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "max_rss_mib": _max_rss_mib(),
        "store_count": len(stores),
        "result": result,
        "query_stats": {
            pattern: {"calls": aggregate_calls[pattern], "rows": aggregate_rows[pattern]}
            for pattern in sorted(aggregate_calls.keys() | aggregate_rows.keys())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution", type=Path)
    parser.add_argument(
        "--store",
        choices=(
            "memory",
            "memory-plain",
            "two-index",
            "two-index-plain",
            "two-index-list",
        ),
        required=True,
    )
    parser.add_argument("--terms", choices=("stock", "interned"), default="stock")
    parser.add_argument("--contexts", choices=("stock", "cached"), default="stock")
    parser.add_argument(
        "--phase",
        choices=("binding", "parse", "semantic", "validate"),
        required=True,
    )
    args = parser.parse_args()

    validator = _load_validator()
    pools = _install_term_interner(validator) if args.terms == "interned" else None
    if args.contexts == "cached":
        _install_context_cache()
    store_factory = _store_factory(args.store)
    if args.phase != "binding" and args.distribution is None:
        parser.error("--distribution is required for this phase")
    if args.phase == "binding":
        measurement = _binding_validation(validator, store_factory)
    elif args.phase == "parse":
        measurement = _parse_only(validator, args.distribution, store_factory)
    elif args.phase == "semantic":
        measurement = _semantic_validation(validator, args.distribution, store_factory)
    else:
        measurement = _validate(validator, args.distribution, store_factory)
    measurement.update(
        python=platform.python_version(),
        rdflib=rdflib_version,
        store=args.store,
        terms=args.terms,
        contexts=args.contexts,
        distribution=str(args.distribution) if args.distribution is not None else None,
    )
    if pools is not None:
        measurement["term_pool"] = {name: len(values) for name, values in pools.items()}
    print(json.dumps(measurement, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

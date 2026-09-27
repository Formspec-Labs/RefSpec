"""Write one release set through the whole-graph and the streamed writer, and require the same bytes.

The fast synthetic case (test_generate_atlas_v3_full.py) and the slow bounded
real case (test_producer_prebuild_validation.py) both run this procedure, so
the fast tier exercises the comparison the slow run relies on. They were two
copies until 02ef3971 moved the ledger's identity stamp into the writers
(REF-050): only the fast copy followed, and the slow one went on comparing a
ledger read before its writer stamped it with one read after.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
generator = importlib.import_module("generate_atlas_v3_full")


def files(root: Path) -> dict[str, bytes]:
    """Every file under root, keyed by relative POSIX path."""

    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def write_both_and_compare(
    root: Path,
    releases: Sequence[Any],
    mapping_releases: Sequence[Any],
    prebuild: Any,
    *,
    created_at: str,
    agency_projection: Any = None,
    before_streaming: Callable[[], object] = lambda: None,
) -> tuple[Any, dict[str, Any]]:
    """Write ``root/legacy`` and ``root/streamed``, assert they agree, and return the streamed construction and manifest.

    ``before_streaming`` runs between the two writes, so a caller can instrument
    the streamed path alone.
    """

    legacy_root = root / "legacy"
    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        legacy_validation = generator._validate_compiled_producer_output(
            releases,
            graphs,
            prebuild.compiled_rows,
            mapping_releases,
        )
        legacy_result, legacy_manifest = generator._write_candidate_distribution(
            legacy_root / "distribution",
            graphs,
            releases=prebuild.pack_plans,
            created_at=created_at,
            compiled_validation=legacy_validation,
            construction_seeds=prebuild.construction_seeds,
            parquet_tables=legacy_root / "parquet-view",
            agency_projection=agency_projection,
        )
    finally:
        graphs.release()

    before_streaming()
    streamed = generator._stream_construct_graphs(
        list(releases),
        list(mapping_releases),
        prebuild=prebuild,
        spool_root=root / "stream-spool",
    )
    streamed_root = root / "streamed"
    streamed_result, streamed_manifest = generator._write_streamed_candidate_distribution(
        streamed_root / "distribution",
        streamed,
        prebuild.pack_plans,
        created_at=created_at,
        construction_seeds=prebuild.construction_seeds,
        parquet_tables=streamed_root / "parquet-view",
        agency_projection=agency_projection,
    )

    # Each writer stamps its ledger with the asserted graph's inventory digest
    # and re-derives the id from it (REF-050), and the whole-graph writer then
    # releases its graphs, so the whole-graph ledger is the one it wrote.
    legacy_accounting = json.loads((legacy_root / "distribution" / "atlas-source-accounting.json").read_bytes())
    asserted = next(graph for graph in legacy_manifest["graphs"] if graph["role"] == "asserted")
    assert legacy_accounting["assertedInventoryDigest"] == asserted["inventoryDigest"]
    assert generator._plain(streamed.accounting) == legacy_accounting
    assert streamed.compiled_validation == legacy_validation
    assert streamed_result == legacy_result
    assert streamed_result["status"] == "passed"
    assert streamed_manifest == legacy_manifest
    assert files(streamed_root) == files(legacy_root)
    return streamed, streamed_manifest

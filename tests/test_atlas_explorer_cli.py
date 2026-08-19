from __future__ import annotations

import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from refspec.atlas import explorer_cli
from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.duckdb_view import ATLAS_DUCKDB_TABLES, AtlasDuckDBView
from refspec.atlas.explorer import open_atlas_explorer
from refspec.atlas.parquet_search_view import _SCHEMAS as _COMPACT_SCHEMAS
from refspec.atlas.parquet_search_view import MANIFEST_FILE
from refspec.atlas.parquet_tables import (
    AGENCY_PROJECTION_ROLE,
    AGENCY_PROJECTION_TABLE_NAMES,
    AGENCY_PROJECTION_TABLE_SCHEMAS,
    AGENCY_PROJECTION_UNRESOLVED_ROLE,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest

ROOT = Path(__file__).resolve().parents[1]
# The current sealed compact search view REF-038 shipped before it: it
# predates the agency-projection tables, so it is the real artifact that
# proves the graceful "no agency projection" path end to end.
_SEALED_VIEW = ROOT / "output" / "atlas-3.1-parquet-search-view-2026-08-16"


def test_cli_serves_compact_search_view_directory(tmp_path: Path, monkeypatch) -> None:
    search_view = tmp_path / "search-view"
    search_view.mkdir()
    called: dict[str, object] = {}

    def capture(
        artifact: Path,
        *,
        manifest_digest: str | None,
        host: str,
        port: int,
        open_browser: bool,
    ) -> None:
        called.update(
            artifact=artifact,
            manifest_digest=manifest_digest,
            host=host,
            port=port,
            open_browser=open_browser,
        )

    monkeypatch.setattr(explorer_cli, "serve_explorer", capture)

    assert (
        explorer_cli.main(
            [
                str(search_view),
                "--manifest-digest",
                "sha256:" + "1" * 64,
                "--host",
                "0.0.0.0",
                "--port",
                "8765",
                "--no-browser",
            ]
        )
        == 0
    )
    assert called == {
        "artifact": search_view,
        "manifest_digest": "sha256:" + "1" * 64,
        "host": "0.0.0.0",
        "port": 8765,
        "open_browser": False,
    }


def test_cli_rejects_missing_artifact(tmp_path: Path, capsys) -> None:
    assert explorer_cli.main([str(tmp_path / "missing")]) == 2
    assert "artifact does not exist" in capsys.readouterr().err


class FakeExplorer:
    def __init__(self) -> None:
        self.search_arguments: dict[str, Any] = {}
        self.overview_arguments: dict[str, Any] = {}
        self.release_graph_arguments: dict[str, Any] = {}
        self.resource_arguments: dict[str, Any] = {}
        self.agency_projection_arguments: dict[str, Any] = {}

    def facets(self) -> dict[str, Any]:
        return {}

    def overview(self, *, status: str = "active", relations: str = "asserted") -> dict[str, Any]:
        self.overview_arguments = {"status": status, "relations": relations}
        return {"edges": [], "nodes": [{"id": "urn:test:release"}]}

    def release_graph(
        self, release_id: str, *, status: str = "active", relations: str = "asserted"
    ) -> dict[str, Any]:
        self.release_graph_id = release_id
        self.release_graph_arguments = {
            "release_id": release_id,
            "status": status,
            "relations": relations,
        }
        return {"nodes": [], "edges": [], "release": {"id": release_id}}

    def search(
        self,
        query: str = "",
        *,
        release: str = "",
        releases: tuple[str, ...] = (),
        ring: str = "",
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.search_arguments = {
            "query": query,
            "release": release,
            "releases": releases,
            "ring": ring,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        return [{"id": "urn:test:result"}]

    def resource(
        self, resource_id: str, *, status: str = "active", relations: str = "asserted"
    ) -> dict[str, Any]:
        self.resource_arguments = {
            "resource_id": resource_id,
            "status": status,
            "relations": relations,
        }
        return {"id": resource_id}

    def agency_projection(self, query: str = "") -> dict[str, Any]:
        self.agency_projection_arguments = {"query": query}
        return {
            "available": True,
            "resolved": [{"source_value": "EPA"}],
            "unresolved": [],
        }


def test_api_search_passes_stable_page_offset() -> None:
    view = FakeExplorer()
    server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(
            f"{base_url}/api/search?q=social&release=r1&ring=subject&limit=40&offset=80",
            timeout=5,
        ) as response:
            assert json.loads(response.read()) == [{"id": "urn:test:result"}]
        with urlopen(f"{base_url}/api/overview", timeout=5) as response:
            assert json.loads(response.read()) == {
                "edges": [],
                "nodes": [{"id": "urn:test:release"}],
            }
        with urlopen(
            f"{base_url}/api/release-graph?id=urn%3Atest%3Arelease", timeout=5
        ) as response:
            assert json.loads(response.read()) == {
                "nodes": [],
                "edges": [],
                "release": {"id": "urn:test:release"},
            }
        assert view.release_graph_id == "urn:test:release"
        with urlopen(f"{base_url}/release?id=urn%3Atest%3Arelease", timeout=5) as response:
            assert "Every concept in this vocabulary" in response.read().decode()
        assert view.search_arguments == {
            "query": "social",
            "release": "r1",
            "releases": (),
            "ring": "subject",
            "status": "active",
            "limit": 40,
            "offset": 80,
        }
        # /api/overview and /api/release-graph default to hiding deprecated
        # resources and derived relations; /api/resource does too.
        assert view.overview_arguments == {"status": "active", "relations": "asserted"}
        assert view.release_graph_arguments == {
            "release_id": "urn:test:release",
            "status": "active",
            "relations": "asserted",
        }
        with urlopen(
            f"{base_url}/api/resource?id=urn%3Atest%3Aresource", timeout=5
        ) as response:
            assert json.loads(response.read()) == {"id": "urn:test:resource"}
        assert view.resource_arguments == {
            "resource_id": "urn:test:resource",
            "status": "active",
            "relations": "asserted",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_endpoints_pass_through_a_show_deprecated_status_toggle() -> None:
    view = FakeExplorer()
    server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(f"{base_url}/api/overview?status=all", timeout=5):
            pass
        assert view.overview_arguments == {"status": "all", "relations": "asserted"}

        with urlopen(
            f"{base_url}/api/release-graph?id=urn%3Atest%3Arelease&status=all", timeout=5
        ):
            pass
        assert view.release_graph_arguments == {
            "release_id": "urn:test:release",
            "status": "all",
            "relations": "asserted",
        }

        with urlopen(f"{base_url}/api/search?q=x&status=all", timeout=5):
            pass
        assert view.search_arguments["status"] == "all"

        with urlopen(
            f"{base_url}/api/resource?id=urn%3Atest%3Aresource&status=all", timeout=5
        ):
            pass
        assert view.resource_arguments == {
            "resource_id": "urn:test:resource",
            "status": "all",
            "relations": "asserted",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_endpoints_pass_through_a_show_derived_relations_toggle() -> None:
    view = FakeExplorer()
    server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(f"{base_url}/api/overview?relations=all", timeout=5):
            pass
        assert view.overview_arguments == {"status": "active", "relations": "all"}

        with urlopen(
            f"{base_url}/api/release-graph?id=urn%3Atest%3Arelease&relations=all", timeout=5
        ):
            pass
        assert view.release_graph_arguments == {
            "release_id": "urn:test:release",
            "status": "active",
            "relations": "all",
        }

        with urlopen(
            f"{base_url}/api/resource?id=urn%3Atest%3Aresource&relations=all", timeout=5
        ):
            pass
        assert view.resource_arguments == {
            "resource_id": "urn:test:resource",
            "status": "active",
            "relations": "all",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_agencies_page_and_api_are_served() -> None:
    view = FakeExplorer()
    server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(f"{base_url}/agencies", timeout=5) as response:
            body = response.read().decode()
            assert response.headers["Content-Type"].startswith("text/html")
            assert "<html" in body
        with urlopen(f"{base_url}/api/agency-projection?q=EPA", timeout=5) as response:
            assert json.loads(response.read()) == {
                "available": True,
                "resolved": [{"source_value": "EPA"}],
                "unresolved": [],
            }
        assert view.agency_projection_arguments == {"query": "EPA"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# End-to-end proof: a real HTTP server driving a real AtlasDuckDBView, not
# the FakeExplorer stub above. fix4 review finding 6: `/agencies` and
# `/api/agency-projection` must be reachable through the server this CLI
# actually ships, against real views -- both the graceful "no agency
# projection" path a currently-shipped view takes, and a populated path.
# --------------------------------------------------------------------------


def _build_query_ready_view(root: Path, *, resources: list[dict[str, Any]] = ()) -> AtlasDuckDBView:
    """Build a real, query-ready ``AtlasDuckDBView`` without the digest-verified
    ``.open()`` path -- the same construction tests/test_atlas_duckdb_view.py's
    ``_make_view`` uses to exercise this exact production class directly.

    ``AtlasDuckDBView.open()`` cannot be used for a *populated* agency
    fixture: ``verify_atlas_parquet_search_view`` requires the view
    directory's file membership to be exactly the manifest plus its declared
    members (see parquet_search_view.py's closure check), but the agency
    projection tables ``_prepare_agency_projection`` reads are deliberately
    unmanifested siblings under ``tables/`` (duckdb_view.py's
    ``_agency_projection_paths``) -- present ones would fail that closure
    check. Constructing the view directly is how this codebase already tests
    agency-projection query behavior without a full sealed artifact; what
    finding 6 asks this module to prove -- the HTTP routing and handler
    wiring -- is exercised for real regardless of how the view was opened.
    """

    connection = duckdb.connect(str(root / "test.duckdb"))
    rows_by_role: dict[CompactRecordRole, list[dict[str, Any]]] = {
        CompactRecordRole.RESOURCE: list(resources),
        CompactRecordRole.STATEMENT: [],
        CompactRecordRole.RELEASE: [],
        CompactRecordRole.LABEL: [],
        CompactRecordRole.IDENTIFIER: [],
        CompactRecordRole.EVIDENCE_BINDING: [],
        CompactRecordRole.SOURCE_RECORD: [],
        CompactRecordRole.LIFECYCLE_EVENT: [],
    }
    for role, rows in rows_by_role.items():
        schema = _COMPACT_SCHEMAS[role]
        table = pa.Table.from_pylist(rows, schema=schema) if rows else schema.empty_table()
        connection.from_arrow(table).create_view(ATLAS_DUCKDB_TABLES[role])
    temporary_directory = tempfile.TemporaryDirectory()
    return AtlasDuckDBView(
        root=root,
        manifest_digest="sha256:" + "0" * 64,
        manifest={"input": {"atlas": {}}, "counts": {}},
        tables={},
        temporary_directory=temporary_directory,
        database_path=root / "test.duckdb",
        connection=connection,
    )


def _resource_row(resource_id: str, release: str) -> dict[str, Any]:
    return {
        "id": resource_id,
        "release": release,
        "scheme": release,
        "semantic_ring": "entity",
        "resource_profile": "conceptScheme",
        "source_record": f"{resource_id}:source",
        "definition": None,
        "notes": [],
        "notations": [],
        "record_status": "active",
    }


def _write_agency_projection_fixture(
    root: Path,
    *,
    resolved: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> None:
    tables_dir = root / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(resolved, schema=AGENCY_PROJECTION_TABLE_SCHEMAS[AGENCY_PROJECTION_ROLE]),
        tables_dir / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_ROLE],
    )
    pq.write_table(
        pa.Table.from_pylist(
            unresolved, schema=AGENCY_PROJECTION_TABLE_SCHEMAS[AGENCY_PROJECTION_UNRESOLVED_ROLE]
        ),
        tables_dir / AGENCY_PROJECTION_TABLE_NAMES[AGENCY_PROJECTION_UNRESOLVED_ROLE],
    )


def _resolved_row(source_value: str, org: str, pref_label: str) -> dict[str, Any]:
    return {
        "source_value_kind": "regulationsGovAgencyId",
        "source_value": source_value,
        "org": org,
        "pref_label": pref_label,
        "abbreviations": [source_value],
        "aliases": [pref_label],
        "parent_org": None,
        "relation": "https://refspec.org/ns/atlas/v3#sameEntityAs",
        "evidence_tier": "E4",
        "warrant": "humanReview",
        "basis": "federalRegisterShortNameEqualsRegulationsGovAgencyId",
        "evidence_records": [],
    }


def _unresolved_row(source_value: str, pref_label: str, reason: str) -> dict[str, Any]:
    return {
        "source_value_kind": "regulationsGovAgencyId",
        "source_value": source_value,
        "source_org": f"urn:ref:regulations-gov-agency:{source_value}",
        "pref_label": pref_label,
        "source_parent_org": None,
        "reason": reason,
        "reasoning": f"No held roster contains {pref_label}.",
        "candidate_resources": [],
        "closest_non_adopted_candidate": None,
    }


def _run_against_real_server(view, exercise) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        exercise(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_agencies_gracefully_degrades_against_the_real_sealed_view() -> None:
    """Start the real CLI server (``explorer_cli._handler``) against the real,
    digest-verified sealed compact search view -- not a stub -- and prove
    `/agencies` and `/api/agency-projection` are actually reachable and
    degrade the way the frontend expects when a view lacks REF-038's tables.
    """

    if not _SEALED_VIEW.is_dir():
        pytest.skip("the sealed compact search view is not present locally")
    manifest_digest = sha256_digest((_SEALED_VIEW / MANIFEST_FILE).read_bytes())
    view = open_atlas_explorer(_SEALED_VIEW, trusted_manifest_digest=manifest_digest)
    try:
        assert view.agency_projection_available() is False

        def exercise(base_url: str) -> None:
            with urlopen(f"{base_url}/agencies", timeout=5) as response:
                assert response.status == 200
                assert response.headers["Content-Type"].startswith("text/html")
                body = response.read().decode()
                assert "<html" in body
                assert "Agency projection" in body
            with urlopen(f"{base_url}/api/agency-projection", timeout=30) as response:
                assert response.status == 200
                assert json.loads(response.read()) == {
                    "available": False,
                    "resolved": [],
                    "unresolved": [],
                }

        _run_against_real_server(view, exercise)
    finally:
        view.close()


def test_agencies_populated_path_against_a_small_real_fixture_view(tmp_path: Path) -> None:
    """Same real server, this time against a small real ``AtlasDuckDBView``
    that does carry REF-038's agency-projection tables, proving the
    populated path -- not just the graceful one -- is actually wired.
    """

    _write_agency_projection_fixture(
        tmp_path,
        resolved=[_resolved_row("EPA", "urn:ref:test-org:epa", "Environmental Protection Agency")],
        unresolved=[_unresolved_row("ARCTICGAS", "Alaska Natural Gas office", "noCounterpartInHeldRosters")],
    )
    view = _build_query_ready_view(
        tmp_path,
        resources=[_resource_row("urn:ref:test-org:epa", "urn:r:test-org")],
    )
    try:
        assert view.agency_projection_available() is True

        def exercise(base_url: str) -> None:
            with urlopen(f"{base_url}/agencies", timeout=5) as response:
                assert response.status == 200
                assert "<html" in response.read().decode()
            with urlopen(f"{base_url}/api/agency-projection?q=EPA", timeout=5) as response:
                assert response.status == 200
                payload = json.loads(response.read())
            assert payload["available"] is True
            assert [row["source_value"] for row in payload["resolved"]] == ["EPA"]
            assert payload["resolved"][0]["org_known"] is True
            assert payload["unresolved"] == []

        _run_against_real_server(view, exercise)
    finally:
        view.close()

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.request import urlopen

import pytest

from refspec.atlas import explorer_cli
from refspec.atlas.explorer import AtlasParquetExplorerError


def test_cli_serves_rdf_preview(tmp_path: Path, monkeypatch) -> None:
    preview = tmp_path / "atlas-explorer-preview.html"
    preview.write_text("<html></html>", encoding="utf-8")
    called: dict[str, object] = {}

    def capture(
        artifact: Path,
        *,
        search_view: Path | None,
        manifest_digest: str | None,
        host: str,
        port: int,
        open_browser: bool,
    ) -> None:
        called.update(
            artifact=artifact,
            search_view=search_view,
            manifest_digest=manifest_digest,
            host=host,
            port=port,
            open_browser=open_browser,
        )

    monkeypatch.setattr(explorer_cli, "serve_rdf_preview", capture)

    assert (
        explorer_cli.main(
            [str(preview), "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
        )
        == 0
    )
    assert called == {
        "artifact": preview,
        "search_view": None,
        "manifest_digest": None,
        "host": "0.0.0.0",
        "port": 8765,
        "open_browser": False,
    }


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


def test_api_search_passes_stable_page_offset() -> None:
    class FakeExplorer:
        def __init__(self) -> None:
            self.search_arguments: dict[str, Any] = {}

        def facets(self) -> dict[str, Any]:
            return {}

        def search(
            self,
            query: str = "",
            *,
            release: str = "",
            releases: tuple[str, ...] = (),
            ring: str = "",
            limit: int = 100,
            offset: int = 0,
        ) -> list[dict[str, Any]]:
            self.search_arguments = {
                "query": query,
                "release": release,
                "releases": releases,
                "ring": ring,
                "limit": limit,
                "offset": offset,
            }
            return [{"id": "urn:test:result"}]

        def resource(self, resource_id: str) -> dict[str, Any]:
            return {"id": resource_id}

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
        assert view.search_arguments == {
            "query": "social",
            "release": "r1",
            "releases": (),
            "ring": "subject",
            "limit": 40,
            "offset": 80,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_rdf_preview_handler_serves_html_and_shards(tmp_path: Path) -> None:
    preview = tmp_path / "atlas-explorer-preview.html"
    preview.write_bytes(b"<html>Atlas</html>")
    shards = tmp_path / "atlas-explorer-preview.shards"
    shard = shards / "resources" / "part.json.gz"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b"compressed shard")

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        explorer_cli._rdf_preview_handler(preview),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(f"{base_url}/", timeout=5) as response:
            assert response.headers.get_content_type() == "text/html"
            assert response.read() == b"<html>Atlas</html>"
        with urlopen(
            f"{base_url}/atlas-explorer-preview.shards/resources/part.json.gz",
            timeout=5,
        ) as response:
            assert response.headers.get_content_type() == "application/gzip"
            assert response.read() == b"compressed shard"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_rdf_preview_handler_delegates_ranked_search(tmp_path: Path) -> None:
    class FakeQueryView:
        def __init__(self) -> None:
            self.arguments: dict[str, Any] = {}

        def search(
            self,
            query: str = "",
            *,
            release: str = "",
            releases: tuple[str, ...] | list[str] = (),
            ring: str = "",
            limit: int = 100,
            offset: int = 0,
        ) -> list[dict[str, Any]]:
            self.arguments = {
                "query": query,
                "release": release,
                "releases": list(releases),
                "ring": ring,
                "limit": limit,
                "offset": offset,
            }
            return [{"id": "urn:test:ranked", "score": 2.5}]

    preview = tmp_path / "atlas-explorer-preview.html"
    preview.write_text("<html></html>", encoding="utf-8")
    preview.with_name("atlas-explorer-preview.shards").mkdir()
    view = FakeQueryView()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        explorer_cli._rdf_preview_handler(preview, view),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(f"{base_url}/api/capabilities", timeout=5) as response:
            assert json.loads(response.read())["search"] == {
                "available": True,
                "engine": "duckdb-fts",
            }
        with urlopen(
            f"{base_url}/api/search?q=policy&release=r1&release=r2&ring=subject&limit=40&offset=40",
            timeout=5,
        ) as response:
            assert json.loads(response.read()) == [{"id": "urn:test:ranked", "score": 2.5}]
        assert view.arguments == {
            "query": "policy",
            "release": "",
            "releases": ["r1", "r2"],
            "ring": "subject",
            "limit": 40,
            "offset": 40,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_rdf_preview_requires_matching_query_view_identity() -> None:
    preview = (
        b'<script id="atlas-data" type="application/json">'
        b'{"distribution":{"id":"urn:test:atlas","manifestDigest":"sha256:abc"}}'
        b"</script>"
    )
    matching = SimpleNamespace(
        atlas_input={
            "distributionId": "urn:test:atlas",
            "manifestSha256": "sha256:abc",
        }
    )
    explorer_cli._require_same_atlas(preview, matching)

    mismatched = SimpleNamespace(
        atlas_input={
            "distributionId": "urn:test:other",
            "manifestSha256": "sha256:def",
        }
    )
    with pytest.raises(AtlasParquetExplorerError, match="different Atlas releases"):
        explorer_cli._require_same_atlas(preview, mismatched)

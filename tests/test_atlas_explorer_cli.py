from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from refspec.atlas import explorer_cli


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

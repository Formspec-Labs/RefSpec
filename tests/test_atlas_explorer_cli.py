from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from refspec.atlas import explorer_cli


def test_cli_serves_rdf_preview(tmp_path: Path, monkeypatch) -> None:
    preview = tmp_path / "atlas-explorer-preview.html"
    preview.write_text("<html></html>", encoding="utf-8")
    called: dict[str, object] = {}

    def capture(
        artifact: Path,
        *,
        host: str,
        port: int,
        open_browser: bool,
    ) -> None:
        called.update(
            artifact=artifact,
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
        "host": "0.0.0.0",
        "port": 8765,
        "open_browser": False,
    }


def test_cli_rejects_non_file_artifact(tmp_path: Path, capsys) -> None:
    assert explorer_cli.main([str(tmp_path)]) == 2
    assert "requires the RDF-derived explorer HTML" in capsys.readouterr().err


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

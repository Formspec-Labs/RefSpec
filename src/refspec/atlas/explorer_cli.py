"""Serve the RDF-derived Atlas graph explorer and its verified shards."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from refspec.atlas.explorer import (
    AtlasParquetExplorer,
    AtlasParquetExplorerError,
    atlas_explorer_facets,
    atlas_parquet_resource,
    open_atlas_explorer,
    render_atlas_parquet_explorer,
    search_atlas_parquet,
)
from refspec.atlas.parquet_search_view import MANIFEST_FILE
from refspec.registry.infrastructure.artifact_serialization import sha256_digest


def _handler(view: AtlasParquetExplorer) -> type[BaseHTTPRequestHandler]:
    class AtlasExplorerHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, content_type: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, value: object, status: int = 200) -> None:
            self._send(
                status,
                "application/json; charset=utf-8",
                json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(),
            )

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    self._send(
                        200,
                        "text/html; charset=utf-8",
                        render_atlas_parquet_explorer().encode(),
                    )
                elif parsed.path == "/api/facets":
                    self._json(atlas_explorer_facets(view))
                elif parsed.path == "/api/search":
                    self._json(
                        search_atlas_parquet(
                            view,
                            query.get("q", [""])[0],
                            release=query.get("release", [""])[0],
                            ring=query.get("ring", [""])[0],
                            limit=int(query.get("limit", ["100"])[0]),
                        )
                    )
                elif parsed.path == "/api/resource":
                    self._json(atlas_parquet_resource(view, query.get("id", [""])[0]))
                else:
                    self._json({"error": "not found"}, 404)
            except (AtlasParquetExplorerError, ValueError) as error:
                self._json({"error": str(error)}, 400)

        def log_message(self, format: str, *args: object) -> None:
            print(format % args, file=sys.stderr)

    return AtlasExplorerHandler


def serve_explorer(
    search_view: Path,
    *,
    manifest_digest: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """Serve the explorer until interrupted."""

    search_view = search_view.resolve(strict=True)
    manifest_path = search_view / MANIFEST_FILE
    trusted_digest = manifest_digest or sha256_digest(manifest_path.read_bytes())
    view = open_atlas_explorer(search_view, trusted_manifest_digest=trusted_digest)
    server = ThreadingHTTPServer((host, port), _handler(view))
    url = f"http://{host}:{server.server_address[1]}/"
    print(url)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _rdf_preview_handler(preview: Path) -> type[BaseHTTPRequestHandler]:
    preview_bytes = preview.read_bytes()
    shard_root = preview.with_name(f"{preview.stem}.shards").resolve(strict=True)

    class AtlasRdfPreviewHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"/", f"/{preview.name}"}:
                payload = preview_bytes
                content_type = "text/html; charset=utf-8"
            else:
                prefix = f"/{shard_root.name}/"
                if not parsed.path.startswith(prefix):
                    self.send_error(404)
                    return
                relative = parsed.path.removeprefix(prefix)
                candidate = (shard_root / relative).resolve()
                if (
                    shard_root not in candidate.parents
                    or candidate.is_symlink()
                    or not candidate.is_file()
                ):
                    self.send_error(404)
                    return
                payload = candidate.read_bytes()
                content_type = "application/gzip"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            print(format % args, file=sys.stderr)

    return AtlasRdfPreviewHandler


def serve_rdf_preview(
    preview: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """Serve the original full-graph explorer and its RDF-derived shards."""

    preview = preview.resolve(strict=True)
    server = ThreadingHTTPServer((host, port), _rdf_preview_handler(preview))
    url = f"http://{host}:{server.server_address[1]}/"
    print(url)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifact",
        type=Path,
        help="RDF-derived Atlas explorer HTML",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.artifact.is_file():
        print(
            "The graph explorer requires the RDF-derived explorer HTML; "
            "Parquet remains available through the data API.",
            file=sys.stderr,
        )
        return 2
    serve_rdf_preview(
        args.artifact,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

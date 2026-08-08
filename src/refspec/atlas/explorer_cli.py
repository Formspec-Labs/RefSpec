"""Serve Atlas graph explorers backed by verified RDF shards or Parquet."""

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
    open_atlas_explorer,
    render_atlas_parquet_explorer,
    render_atlas_v3_explorer,
)
from refspec.atlas.explorer_data import AtlasExplorerData
from refspec.atlas.parquet_search_view import MANIFEST_FILE
from refspec.registry.infrastructure.artifact_serialization import sha256_digest


def _handler(view: AtlasExplorerData) -> type[BaseHTTPRequestHandler]:
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
                    self._json(view.facets())
                elif parsed.path == "/api/search":
                    self._json(
                        view.search(
                            query.get("q", [""])[0],
                            release=query.get("release", [""])[0],
                            ring=query.get("ring", [""])[0],
                            limit=int(query.get("limit", ["100"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                elif parsed.path == "/api/resource":
                    self._json(view.resource(query.get("id", [""])[0]))
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
        view.close()


def _rdf_preview_handler(
    preview: Path,
    query_view: AtlasExplorerData | None = None,
) -> type[BaseHTTPRequestHandler]:
    stored_preview_bytes = preview.read_bytes()
    model = _embedded_atlas_model(stored_preview_bytes)
    preview_bytes = (
        render_atlas_v3_explorer(model).encode() if model is not None else stored_preview_bytes
    )
    shard_root = preview.with_name(f"{preview.stem}.shards").resolve(strict=True)

    class AtlasRdfPreviewHandler(BaseHTTPRequestHandler):
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
            if parsed.path == "/api/capabilities":
                self._json(
                    {
                        "search": {
                            "available": query_view is not None,
                            "engine": "duckdb-fts" if query_view is not None else None,
                        }
                    }
                )
                return
            if parsed.path == "/api/search":
                if query_view is None:
                    self._json({"error": "DuckDB search view is not configured"}, 404)
                    return
                try:
                    self._json(
                        query_view.search(
                            query.get("q", [""])[0],
                            releases=query.get("release", []),
                            ring=query.get("ring", [""])[0],
                            limit=int(query.get("limit", ["40"])[0]),
                            offset=int(query.get("offset", ["0"])[0]),
                        )
                    )
                except (AtlasParquetExplorerError, ValueError) as error:
                    self._json({"error": str(error)}, 400)
                return
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
            self._send(200, content_type, payload)

        def log_message(self, format: str, *args: object) -> None:
            print(format % args, file=sys.stderr)

    return AtlasRdfPreviewHandler


def serve_rdf_preview(
    preview: Path,
    *,
    search_view: Path | None = None,
    manifest_digest: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """Serve the original full-graph explorer and its RDF-derived shards."""

    preview = preview.resolve(strict=True)
    view = None
    if search_view is not None:
        search_view = search_view.resolve(strict=True)
        manifest_path = search_view / MANIFEST_FILE
        trusted_digest = manifest_digest or sha256_digest(manifest_path.read_bytes())
        view = open_atlas_explorer(search_view, trusted_manifest_digest=trusted_digest)
        try:
            _require_same_atlas(preview.read_bytes(), view)
        except BaseException:
            view.close()
            raise
    try:
        server = ThreadingHTTPServer((host, port), _rdf_preview_handler(preview, view))
    except BaseException:
        if view is not None:
            view.close()
        raise
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
        if view is not None:
            view.close()


def _require_same_atlas(preview_bytes: bytes, view: AtlasParquetExplorer) -> None:
    model = _embedded_atlas_model(preview_bytes)
    if model is None:
        raise AtlasParquetExplorerError("RDF explorer omits its Atlas data model")
    try:
        distribution = model["distribution"]
        atlas_input = view.atlas_input
    except (KeyError, TypeError, AttributeError) as error:
        raise AtlasParquetExplorerError("RDF explorer Atlas identity is invalid") from error
    if (
        distribution.get("id") != atlas_input.get("distributionId")
        or distribution.get("manifestDigest") != atlas_input.get("manifestSha256")
    ):
        raise AtlasParquetExplorerError("RDF explorer and DuckDB query view describe different Atlas releases")


def _embedded_atlas_model(preview_bytes: bytes) -> dict[str, object] | None:
    marker = b'<script id="atlas-data" type="application/json">'
    start = preview_bytes.find(marker)
    end = preview_bytes.find(b"</script>", start + len(marker))
    if start < 0 or end < 0:
        return None
    try:
        model = json.loads(preview_bytes[start + len(marker) : end])
    except json.JSONDecodeError as error:
        raise AtlasParquetExplorerError("RDF explorer Atlas identity is invalid") from error
    if not isinstance(model, dict):
        raise AtlasParquetExplorerError("RDF explorer Atlas identity is invalid")
    return model


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifact",
        type=Path,
        help="compact Atlas search-view directory or RDF-derived explorer HTML",
    )
    parser.add_argument(
        "--manifest-digest",
        help="trusted compact-view manifest SHA-256; defaults to the local manifest bytes",
    )
    parser.add_argument(
        "--search-view",
        type=Path,
        help="verified compact search view used for DuckDB BM25 with RDF explorer HTML",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.artifact.is_dir():
        if args.search_view is not None:
            print("--search-view applies only to RDF-derived explorer HTML", file=sys.stderr)
            return 2
        serve_explorer(
            args.artifact,
            manifest_digest=args.manifest_digest,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return 0
    if args.artifact.is_file():
        if args.manifest_digest and args.search_view is None:
            print("--manifest-digest requires a compact --search-view", file=sys.stderr)
            return 2
        serve_rdf_preview(
            args.artifact,
            search_view=args.search_view,
            manifest_digest=args.manifest_digest,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return 0
    print("Atlas explorer artifact does not exist", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

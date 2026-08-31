#!/usr/bin/env bash
# Bundle the DuckDB-Wasm engine entry (build/duckdb-engine-entry.js) into a
# single, dependency-free ES module and vendor the wasm/worker binaries
# alongside it, all under precomputed/vendor/duckdb-wasm/ so build/upload.sh
# picks them up.
#
# Why bundle at all: @duckdb/duckdb-wasm's published dist/duckdb-browser.mjs
# leaves `apache-arrow` as an external bare specifier (meant to be resolved
# by a consumer's bundler at build time). Serving that file to the browser
# directly -- there is no bundler at runtime, only the R2-backed static
# file server -- fails with "Failed to resolve module specifier
# 'apache-arrow'". esbuild inlines it into one flat module instead.
#
# Why NOT under public/: the mvp/eh .wasm files are 34-39MB, over the 25MiB
# Workers Static Assets per-file limit. Everything here is served through
# the Worker's /data/* R2 range-proxy instead (see src/worker.js).
set -euo pipefail

cd "$(dirname "$0")/.."

OUT_DIR="precomputed/vendor/duckdb-wasm"
DIST_DIR="node_modules/@duckdb/duckdb-wasm/dist"

mkdir -p "$OUT_DIR"

npx esbuild build/duckdb-engine-entry.js \
  --bundle --format=esm --platform=browser \
  --outfile="$OUT_DIR/duckdb-engine.mjs"

cp "$DIST_DIR/duckdb-mvp.wasm" "$OUT_DIR/"
cp "$DIST_DIR/duckdb-eh.wasm" "$OUT_DIR/"
cp "$DIST_DIR/duckdb-browser-mvp.worker.js" "$OUT_DIR/"
cp "$DIST_DIR/duckdb-browser-eh.worker.js" "$OUT_DIR/"

echo "vendored:"
ls -la "$OUT_DIR"

// Bundling entry point for the DuckDB-Wasm browser engine.
//
// @duckdb/duckdb-wasm's own published ESM build (dist/duckdb-browser.mjs)
// deliberately leaves `apache-arrow` as an external bare specifier -- it
// expects a consumer's bundler to resolve it from node_modules. Serving
// that file to the browser unbundled makes `import * as duckdb from
// "duckdb-browser.mjs"` fail with "Failed to resolve module specifier
// 'apache-arrow'": there is no import map and no bundler at runtime, only
// a static file server (R2, via the Worker's /data/* proxy).
//
// This file re-exports the same public API through esbuild instead, which
// inlines apache-arrow (and duckdb-wasm's own code) into one flat ES
// module with zero bare imports -- see build/bundle-duckdb.sh. It does
// NOT bundle the .wasm binaries or the mvp/eh worker scripts; those stay
// as separate files, fetched at runtime by URL exactly as duckdb-wasm's
// own API expects (db.instantiate(mainModule, ...), new Worker(mainWorker)).
export * from "@duckdb/duckdb-wasm";

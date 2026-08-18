# RefSpec Atlas explorer -- Cloudflare deployment

A DuckDB-Wasm port of the local Atlas explorer (`refspec-atlas-explorer`,
`src/refspec/atlas/{duckdb_view,explorer_frontend,explorer_cli}.py`) that
serves a verified compact Parquet search view from Cloudflare R2 through a
Worker, with no server-side query engine at all: the browser queries
Parquet files over HTTP range requests.

Read-only, no auth. The R2 bucket has no public access (no r2.dev URL, no
custom domain) -- the Worker's R2 binding is the only reader, and never
exposes PUT/DELETE.

## Architecture

```
 browser ──▶ Worker (static assets: html/css/js + vendored duckdb-wasm)
     │
     └──▶ Worker "/data/*" route ──▶ R2 binding (range-proxied) ──▶ bucket
```

- **R2 bucket** (`refspec-atlas-explorer-data`) holds the Parquet tables,
  the prebuilt full-text index, and precomputed JSON aggregates.
- **A Worker** (`src/worker.js`) serves the static frontend via the
  Workers Static Assets binding, and proxies `/data/<key>` reads to R2,
  forwarding `Range`/`If-Range`/`If-None-Match` and returning correct
  `206`/`200`/`304` with `Accept-Ranges`/`Content-Range`/`ETag`. This is
  what lets DuckDB-Wasm read a few row groups out of a 280MB Parquet file
  instead of downloading the whole object.
- **DuckDB-Wasm in the browser** (`public/assets/data-layer.js`) queries
  those files directly with SQL. It is loaded lazily -- not on first
  paint, only on the first search keystroke or the first resource click.

We chose the **Worker proxy** over an R2 public custom domain: this
account has no zone/domain to hang a custom domain off, r2.dev URLs are
explicitly "non-production" with no cache/CORS control, and a same-origin
proxy needs no CORS at all (the app and its data share one origin). It
also keeps the bucket itself unreachable from the public internet --
the binding is Worker-only.

### Why so much is precomputed

A cold browser querying the full compact view can't afford whole-corpus
or whole-release aggregates the way the local explorer's in-process
DuckDB session can. `build/precompute.py` calls the *existing, already
verified* `AtlasDuckDBView` methods (`facets()`, `overview()`,
`release_graph()`, `agency_projection()`) unchanged and writes their
results to static JSON:

| Precomputed | Why |
|---|---|
| `facets.json` | whole-corpus counts + filter lists |
| `overview-{active,all}.json` | whole-Atlas node/edge map |
| `agencies.json` | REF-038 agency projection (tiny anyway: 321+10 rows) |
| `release-graph/<slug>-{active,all}.json` | one vocabulary's full graph |

`release-graph` is additionally **capped to the 4,000 highest-degree
nodes** for any release above that size (LCSH: 514,837 concepts; FAST:
441,127) -- the local explorer's own canvas already does level-of-detail
rendering (a culling grid, a dot fallback, zoom-gated edges) rather than
resolving hundreds of thousands of nodes on screen, so this cap matches
what a human can actually look at, not a new limitation. Capped payloads
carry `truncated: true` and `counts.totalResources`, and the `/release`
page renders that as a visible subtitle -- never a silent truncation.

Search is the one interactive, unbounded-input feature, so it can't be
precomputed exhaustively. Instead `build/precompute.py` builds DuckDB's
own **official `fts` extension index** locally (`INSTALL fts; LOAD fts;
PRAGMA create_fts_index(...)`, the exact call `duckdb_view.py` makes at
request time) and exports its `dict`/`terms`/`docs`/`stats` tables to
Parquet, sorted by their lookup key (`term`, `termid`, `docid`
respectively). The browser never rebuilds this index -- it never scans
label text cold -- it re-evaluates DuckDB's own `match_bm25` SQL macro
(captured verbatim from `duckdb_functions()`) as plain SQL against the
exported tables, so ranking is bit-for-bit the same formula. See
"Search index" below for size and per-query cost.

`resources.parquet` and a new `browse-order.parquet` are re-sorted by
their lookup key (id, and label respectively) for the search/browse path.

### The resource detail inspector does not use DuckDB-Wasm at all

This needed its own fix, discovered empirically against the live
deployment: DuckDB-Wasm's Parquet reader here does not do row-group-level
ranged reads. Touching any remote table -- even just `CREATE VIEW x AS
SELECT * FROM read_parquet(url)`, on files from 0.25MB to 285MB alike --
downloads that whole file once, confirmed via Chrome DevTools network
inspection: the Worker's `/data/*` proxy answers a `HEAD` + `Range:
bytes=0-` probe with a correct `206`, but DuckDB-Wasm's actual reads never
send a `Range` header at all. `SET builtin_httpfs`, `registerFileURL`'s
`directIO` flag both ways, and an explicit `force_download` setting (which
doesn't exist in this build) were all tried and made no difference. If the
detail inspector queried `labels`/`identifiers`/`statements`/
`evidence-bindings`/`source-records` live the way `search()`/`resource()`
do in `duckdb_view.py`, opening one resource would download all five
tables in full -- about 700MB -- on the first click.

The fix routes around it: `build/precompute.py` precomputes every
resource's full detail payload (byte-identical in shape to
`AtlasDuckDBView.resource()`) into newline-delimited JSON. Every relation
carries full IRIs/URNs, so across 1.5M resources the body runs to
several GB. R2's own single-part PUT limit is ~5GiB, but
`wrangler r2 object put` refuses anything over 300MiB regardless
("Wrangler only supports uploading files up to 300 MiB in size" --
confirmed empirically, every larger shard failed outright), so the body
is **sharded** into ~250MB files (`tables/resource-detail/NNN.ndjson`),
plus a small `id -> (shard, offset, length)` index (`tables/resource-
detail-index.parquet`, sorted by id, ~2MB). `data-layer.js`'s
`resource()` looks up the shard/offset for the clicked id in that small
index (via DuckDB-Wasm -- one more small file downloaded once, already
paid for by search) and then issues one plain `fetch()` with an explicit
`Range` header directly against that one shard. That range request goes
through the same Worker proxy already curl-verified to return correct
`206`/`Content-Range` -- so only that one resource's bytes ever cross the
wire, regardless of DuckDB-Wasm's behavior. `search()`'s BM25 path and
the `browse-order`/`resources` point lookups still use DuckDB-Wasm
normally; only the detail-table access pattern changed.

**Only one payload is precomputed per resource, not two.** The first cut
of this fix precomputed a separate body for `status=active` (relations to
a deprecated *other* endpoint dropped) and `status=all` (everything) --
two near-duplicate ~9GB bodies, because "active" is a strict subset of
"all" per resource and the only thing that differs is which relations
survive a one-line filter. That put the R2 bucket at ~17GB for no
information the "all" body didn't already contain -- worth catching
because it's an easy trap: sharding+range-fetching solved the *transfer*
problem, but doesn't excuse shipping redundant storage. Now only the
unfiltered superset is precomputed, with each relation additionally
carrying `subject_status`/`object_status`; `resource()` applies the exact
same "hide relations to a deprecated other endpoint" rule client-side
against that one payload, mirroring `duckdb_view.py`'s
`_status_predicate` exactly. Same two visible toggle states, ~9.5GB
total bucket instead of ~18GB, one precompute pass instead of two.

### Bucket size

None of this affects what a visitor downloads (that's the range-proxy's
job, measured in the deploy report) -- it's what's stored in R2, which is
cheap and egress-free but still worth keeping honest. Current breakdown,
~9.5GB total:

| Path | Size | What |
|---|---|---|
| `tables/resource-detail/` | ~9.26GB | every resource's relations+evidence, one payload each (see above) |
| `vendor/duckdb-wasm/` | ~72MB | both `mvp` and `eh` wasm engine bundles -- only one is ever downloaded per visitor (`selectBundle` feature-detects), the other is a compatibility fallback for older browsers, not waste |
| `search/` | ~38MB | the BM25 index (`fts-dict`/`fts-terms`/`fts-docs`) |
| `release-graph/` | ~21MB | 117 releases, capped per release (see above) |
| `tables/resources.parquet` | ~60MB | id-sorted resources + denormalized label |
| `tables/browse-order.parquet` | ~13MB | label-sorted browse index |
| `tables/resource-detail-index.parquet` | ~2MB | id → (shard, offset, length) |
| everything else | <1MB | facets/overview/agencies/browse-first-page/release-index JSON |

`tables/resource-detail/` is 97%+ of the bucket and is the corpus itself
(1.5M resources' relations, each carrying full IRIs/URNs) -- not
duplicated data. It was reviewed once already (see above: an earlier cut
shipped it twice, once per status, doubling the bucket to ~18GB for
no new information) and is now a single unfiltered copy. Further
reduction below "one full copy of the corpus's relation graph" would mean
dropping fields the inspector actually displays, which is a different
kind of cut than deduplication.

## Deploy

Prerequisites: `export UV_CACHE_DIR=/tmp/uv-cf2` (or any writable dir you
control -- the shared default cache lock kills concurrent builds),
`npx wrangler login` once per machine, Python deps already installed via
`uv sync` at the repo root.

### 1. Precompute the browser artifacts from a verified search view

```bash
cd RefSpec
export UV_CACHE_DIR=/tmp/uv-cf2
uv run python deploy/cloudflare-explorer/build/precompute.py \
  output/atlas-3.1-parquet-search-view-2026-08-17 \
  --out deploy/cloudflare-explorer/precomputed
```

Takes about a minute and prints artifact sizes at the end. Nothing here
mutates the source search view; it only reads it.

### 2. Vendor DuckDB-Wasm (one-time, or when bumping the version)

The `mvp`/`eh` `.wasm` bundles are 34-39MB -- over the 25MiB Workers
**Static Assets** per-file limit -- so they are not static assets. They
live in `precomputed/vendor/duckdb-wasm/` and get uploaded to R2 with
everything else in step 3, served through the same `/data/*` range-proxy
route as the Parquet tables (`data-layer.js` fetches them from
`/data/vendor/duckdb-wasm/...`). Only the small pieces of the page shell
(html/css/js, tens of KB) are real Workers static assets.

`@duckdb/duckdb-wasm`'s own published `dist/duckdb-browser.mjs` leaves
`apache-arrow` as an external bare specifier (meant for a consumer's
bundler to resolve) -- serving it to the browser as-is fails at import
time with `Failed to resolve module specifier "apache-arrow"`, since
there is no bundler or import map at runtime, only the static file
server. `build/bundle-duckdb.sh` runs esbuild to inline it into one flat,
dependency-free ES module (`duckdb-engine.mjs`) and copies the `.wasm`/
worker files alongside it:

```bash
cd deploy/cloudflare-explorer
npm install
bash build/bundle-duckdb.sh
```

### 3. Upload the precomputed artifacts to R2

Every file here is well under `wrangler r2 object put`'s own 300MiB
ceiling (see the "resource detail inspector" section above -- this is
what the resource-detail sharding is sized against, not R2's much higher
~5GiB single-part limit), so plain `wrangler r2 object put` is sufficient
-- no multipart needed. Uploading this much data (~9.5GB, dominated by
the resource-detail shards -- see "Bucket size" below) over a few hundred
objects takes a while; run it detached and watch progress:

```bash
cd deploy/cloudflare-explorer
find precomputed -type f | while read -r f; do
  key="${f#precomputed/}"
  npx wrangler r2 object put "refspec-atlas-explorer-data/$key" --file "$f" --remote -q
done
```

(`build/upload.sh` wraps this with progress logging and is safe to
re-run -- it re-uploads unconditionally, which is what you want after a
new search view changes file contents at the same keys.)

### 4. Deploy the Worker

```bash
npx wrangler deploy
```

### 5. Verify

```bash
curl -sI https://<your-worker>.workers.dev/                       # 200, text/html
curl -sI https://<your-worker>.workers.dev/data/facets.json       # 200, accept-ranges: bytes
curl -sI -H 'Range: bytes=0-1023' \
  https://<your-worker>.workers.dev/data/tables/resources.parquet # 206, content-range
```

Then open the URL: search should return results, clicking a result opens
the resource inspector, the overview map renders on load, `/release?id=`
opens a vocabulary map, and `/agencies?q=EPA` should resolve DHS/DOC/DOD.

## Redeploying a new search view

Repeat steps 1, 3, 4 above against the new
`output/atlas-3.1-parquet-search-view-<date>/` directory -- the R2 keys
are stable filenames (`tables/resources.parquet`, `facets.json`, ...), so
re-uploading overwrites them in place and the next `wrangler deploy` (or
even without redeploying the Worker, since it reads keys by name) picks
up the new content immediately. Bump `search-view-manifest.json`'s digest
in your own notes if you want to track which view is live; the deployed
app itself doesn't pin or verify a manifest digest -- it trusts whatever
is at those R2 keys, the same way the Worker trusts whatever
`wrangler deploy` last pushed.

## What was ported vs. cut

Ported: search (BM25-ranked, same formula, same fields), the resource
inspector with relations + evidence (lazy-loaded), the overview map
(satellite grouping, deprecated-hidden-by-default with toggle), the
per-vocabulary `/release` graph (capped for huge vocabularies, see
above), and `/agencies`.

Cut / degraded, with reasons:
- **Very large `/release` graphs are capped** to the 4,000 highest-degree
  nodes (see above) rather than shipping a 30-50MB JSON per page view.
- **`/api/resource` is precomputed, not a live query** -- see "The resource
  detail inspector does not use DuckDB-Wasm at all" above. The response
  shape and content are unchanged; only how the browser fetches it changed.
- **The `graph` query parameter** the original frontend JS appends to
  `/api/search` and `/api/resource` is silently ignored, exactly as the
  original Python `explorer_cli.py`/`duckdb_view.py` already ignore it --
  nothing was removed, this is describing existing dead-parameter
  behavior this port preserves.

## Search index

Prebuilt from DuckDB's own `fts` extension (see above). Sizes from the
current search view:

- `search/fts-dict.parquet` (term, termid, df; sorted by term)
- `search/fts-terms.parquet` (termid, docid, tf; sorted by termid, docid)
- `search/fts-docs.parquet` (docid, id, len; sorted by docid)

Sizes and measured per-query transfer are in the deploy report below --
the whole index is tens of MB, but a typical query only touches the row
groups for its own handful of query terms, not the whole index.

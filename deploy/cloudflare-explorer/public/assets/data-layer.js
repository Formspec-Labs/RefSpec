// AtlasData -- the browser-side replacement for the Python explorer's
// /api/* HTTP handlers (explorer_cli.py). The three page scripts
// (index.html, release.html, agencies.html) are the *original* frontend
// JS, unmodified except for one line: `get(path)` now calls
// `window.AtlasData.get(path)` instead of `fetch(path)`. Every response
// shape below matches src/refspec/atlas/duckdb_view.py exactly, because
// this file's job is only to answer the same questions from a different
// substrate: precomputed JSON for whole-corpus/whole-release aggregates
// (impractical to compute cold in a browser); a lazy DuckDB-Wasm session
// running BM25 search against a prebuilt index (see search() below); and,
// for the resource detail inspector, a precomputed per-resource JSON
// fetched with a real HTTP Range request rather than a DuckDB-Wasm query
// (see the TABLES comment and resource() below for why).
//
// Nothing here is fetched until it is needed: facets + overview are the
// only requests the app issues before user interaction, and both are
// small precomputed JSON (tens of KB). DuckDB-Wasm (~34MB engine, one of
// the mvp/eh wasm bundles) only loads on the first search keystroke or
// the first resource click.
(() => {
  "use strict";

  const DATA_BASE = "/data";
  const jsonCache = new Map();
  const BM25 = { k: 1.2, b: 0.75 };

  function abs(path) {
    return new URL(path, location.origin).href;
  }

  async function fetchJson(path) {
    if (jsonCache.has(path)) return jsonCache.get(path);
    const promise = fetch(path, { cache: "force-cache" }).then(async (response) => {
      if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
      return response.json();
    });
    jsonCache.set(path, promise);
    try {
      return await promise;
    } catch (error) {
      jsonCache.delete(path);
      throw error;
    }
  }

  // ---- tokenizer: reproduces DuckDB fts_main_*.tokenize() exactly -------
  // SQL macro (captured verbatim from `duckdb_functions()` against a local
  // build of this same index): string_split_regex(regexp_replace(lower(
  // strip_accents(CAST(s AS VARCHAR))), '(\.|[^a-z0-9])+', ' ', 'g'), '\s+')
  function tokenize(text) {
    const normalized = String(text ?? "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "") // strip_accents (combining diacriticals)
      .toLowerCase()
      .replace(/(\.|[^a-z0-9])+/g, " ")
      .trim();
    if (!normalized) return [];
    return [...new Set(normalized.split(/\s+/).filter(Boolean))];
  }

  // ---- release id <-> slug (for /api/release-graph) ----------------------
  let releaseIndexPromise = null;
  function releaseIndex() {
    if (!releaseIndexPromise) releaseIndexPromise = fetchJson(`${DATA_BASE}/release-index.json`);
    return releaseIndexPromise;
  }

  // ---- lazy DuckDB-Wasm engine --------------------------------------------
  //
  // Only search-path tables are registered as DuckDB-Wasm views. Detail data
  // (labels/identifiers/statements/evidence-bindings/source-records) is
  // deliberately NOT queried through DuckDB-Wasm: this deployment's
  // DuckDB-Wasm build downloads a whole touched Parquet file on first use
  // rather than doing row-group-level ranged reads (confirmed against the
  // live Worker -- its /data/* proxy answers ranged HEAD/GET correctly,
  // DuckDB-Wasm's own reads just never send a Range header). For those five
  // tables combined (~700MB) that would mean downloading hundreds of MB on
  // the very first resource click. See resource() below and
  // build/precompute.py's "resource-detail bundles" section for the fix:
  // precomputed per-resource JSON, fetched with a real HTTP Range request
  // this Worker proxy is proven to honor.
  let duckdbPromise = null;
  const TABLES = {
    resources: "tables/resources.parquet",
    browse_order: "tables/browse-order.parquet",
    resource_detail_index: "tables/resource-detail-index.parquet",
    fts_dict: "search/fts-dict.parquet",
    fts_terms: "search/fts-terms.parquet",
    fts_docs: "search/fts-docs.parquet",
  };

  async function ensureDuckDB(onStatus) {
    if (!duckdbPromise) {
      duckdbPromise = initDuckDB(onStatus).catch((error) => {
        duckdbPromise = null;
        throw error;
      });
    }
    return duckdbPromise;
  }

  async function initDuckDB(onStatus) {
    onStatus?.("Loading the query engine…");
    const duckdb = await import("/data/vendor/duckdb-wasm/duckdb-engine.mjs");
    const bundles = {
      mvp: {
        mainModule: abs("/data/vendor/duckdb-wasm/duckdb-mvp.wasm"),
        mainWorker: abs("/data/vendor/duckdb-wasm/duckdb-browser-mvp.worker.js"),
      },
      eh: {
        mainModule: abs("/data/vendor/duckdb-wasm/duckdb-eh.wasm"),
        mainWorker: abs("/data/vendor/duckdb-wasm/duckdb-browser-eh.worker.js"),
      },
    };
    const bundle = await duckdb.selectBundle(bundles);
    const workerScript = `importScripts(${JSON.stringify(bundle.mainWorker)});`;
    const workerUrl = URL.createObjectURL(new Blob([workerScript], { type: "text/javascript" }));
    const worker = new Worker(workerUrl);
    const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
    const db = new duckdb.AsyncDuckDB(logger, worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(workerUrl);
    const conn = await db.connect();
    onStatus?.("Opening the Atlas tables…");
    for (const [name, relativePath] of Object.entries(TABLES)) {
      const url = abs(`${DATA_BASE}/${relativePath}`);
      await conn.query(
        `CREATE VIEW ${name} AS SELECT * FROM read_parquet(${sqlString(url)})`
      );
    }
    const meta = await fetchJson(`${DATA_BASE}/search/fts-meta.json`);
    onStatus?.("");
    return { db, conn, meta };
  }

  function sqlString(value) {
    return `'${String(value).replace(/'/g, "''")}'`;
  }

  function sqlIdent(term) {
    // Tokens are guaranteed to match /^[a-z0-9]+$/ by tokenize(); no
    // quoting hazard is possible, but guard anyway rather than trust it.
    if (!/^[a-z0-9]+$/.test(term)) throw new Error(`unexpected token shape: ${term}`);
    return `'${term}'`;
  }

  // DuckDB-Wasm returns Arrow rows: 64-bit integer columns (df/tf/len/
  // termid/docid and friends) surface as BigInt, and nested list columns
  // can surface as Arrow Vector wrappers rather than plain arrays. Both are
  // safe inside DuckDB SQL (arithmetic there stays in SQL/Arrow space) but
  // need normalizing before the ported frontend JS -- which expects plain
  // JSON shapes identical to what explorer_cli.py returned -- touches them.
  function toPlain(value) {
    if (typeof value === "bigint") {
      const asNumber = Number(value);
      return Number.isSafeInteger(asNumber) ? asNumber : value.toString();
    }
    if (value == null || typeof value !== "object") return value;
    if (value instanceof Uint8Array || value instanceof ArrayBuffer) return value;
    if (Array.isArray(value)) return value.map(toPlain);
    if (typeof value.toArray === "function") return toPlain(value.toArray());
    const out = {};
    for (const key of Object.keys(value)) out[key] = toPlain(value[key]);
    return out;
  }

  function rowsOf(arrowTable) {
    return arrowTable.toArray().map((row) => toPlain(row.toJSON()));
  }

  function statusPredicate(column, status) {
    if (status === "all") return "1=1";
    return `(${column} IS NULL OR lower(${column}) NOT LIKE '%deprecated%')`;
  }

  // The ported frontend calls this exact shape (no query, no filters, the
  // default page size, first page) once, unconditionally, right after
  // load -- before the visitor has done anything. Answering it from a
  // precomputed static file instead of DuckDB-Wasm keeps that unavoidable
  // first call off the "load the whole query engine" path; DuckDB-Wasm
  // only loads once something the visitor actually did needs it.
  function isDefaultFirstPage({ q, release, releases, ring, status, limit, offset }) {
    // The frontend always sends a "release=" and "ring=" pair (empty string
    // when no filter is chosen) via URLSearchParams, so `releases` here is
    // typically [""], not [] -- filter blanks before checking length.
    return (
      !q.trim() &&
      !release &&
      !(releases || []).filter(Boolean).length &&
      !ring &&
      status === "active" &&
      limit === 40 &&
      offset === 0
    );
  }

  // ---- /api/search ---------------------------------------------------------
  async function search(params) {
    const { q = "", release = "", releases = [], ring = "", status = "active", limit = 100, offset = 0 } = params;
    if (isDefaultFirstPage({ q, release, releases, ring, status, limit, offset })) {
      return fetchJson(`${DATA_BASE}/browse-first-page.json`);
    }
    const releaseFilter = [...new Set([...(releases || []), release].filter(Boolean))];
    const { conn, meta } = await ensureDuckDB();
    const filterClause = (alias) =>
      `${releaseFilter.length ? `${alias}.release IN (${releaseFilter.map(sqlString).join(",")})` : "1=1"}` +
      ` AND ${ring ? `${alias}.ring = ${sqlString(ring)}` : "1=1"}` +
      ` AND ${statusPredicate(`${alias}.status`, status)}`;
    const releaseClause = filterClause("r");
    const query = q.trim();

    if (!query) {
      // browse-order.parquet is sorted by (lower(label), label, id) so this
      // ordered, filtered, LIMIT/OFFSET scan only pulls the row groups the
      // page actually needs; resources.parquet (sorted by id) is then
      // touched only for the page's own ids to hydrate display fields.
      const pageIds = rowsOf(
        await conn.query(`
          SELECT id FROM browse_order AS b
          WHERE ${filterClause("b")}
          ORDER BY lower(b.label), b.label, b.id
          LIMIT ${limit} OFFSET ${offset}
        `)
      ).map((row) => row.id);
      if (!pageIds.length) return [];
      const hydrated = rowsOf(
        await conn.query(`
          SELECT id, definition, label, notations, profile, release, ring
          FROM resources
          WHERE id IN (${pageIds.map(sqlString).join(",")})
        `)
      );
      const byId = new Map(hydrated.map((row) => [row.id, row]));
      return pageIds.map((id) => byId.get(id)).filter(Boolean);
    }

    const terms = tokenize(query);
    if (!terms.length) return [];
    const termList = terms.map(sqlIdent).join(",");
    const result = await conn.query(`
      WITH qterms AS (
        SELECT termid, df FROM fts_dict WHERE term IN (${termList})
      ), postings AS (
        SELECT t.termid, t.docid, t.tf, q.df
        FROM fts_terms AS t JOIN qterms AS q USING (termid)
      ), scored AS (
        SELECT
          p.docid,
          sum(
            ln(1 + ((${meta.numDocs} - p.df + 0.5) / (p.df + 0.5))) *
            ((p.tf * (${BM25.k} + 1)) /
             (p.tf + ${BM25.k} * (1 - ${BM25.b} + ${BM25.b} * (d.len / ${meta.avgdl}))))
          ) AS score
        FROM postings AS p JOIN fts_docs AS d ON d.docid = p.docid
        GROUP BY p.docid
      )
      SELECT r.id, r.definition, r.label, r.notations, r.profile, r.release, r.ring, s.score
      FROM scored AS s
      JOIN fts_docs AS d ON d.docid = s.docid
      JOIN resources AS r ON r.id = d.id
      WHERE ${releaseClause}
      ORDER BY s.score DESC, lower(r.label), r.label, r.id
      LIMIT ${limit} OFFSET ${offset}
    `);
    return rowsOf(result);
  }

  // ---- /api/resource ---------------------------------------------------------
  //
  // Precomputed, not queried live: see the TABLES comment above and
  // build/precompute.py's "resource-detail bundles" section. The point
  // lookup below (against the small, already-downloaded-once offset index)
  // finds a (shard, offset, length), and a single real HTTP Range request
  // fetches exactly that resource's precomputed JSON -- the same shape
  // AtlasDuckDBView.resource() returns -- out of its shard.
  //
  // Only one payload is precomputed per resource -- the unfiltered
  // status="all" relation set, each relation carrying its endpoints'
  // statuses -- rather than a second, near-duplicate "active" body (that
  // used to double the whole bucket to ~17GB for no information the
  // "all" body didn't already contain). status="active" is the default
  // view, so it's applied here, mirroring duckdb_view.py's
  // `_status_predicate` exactly: a relation is hidden only when the
  // *other* endpoint (not the resource itself) has a deprecated status.
  function isDeprecatedStatus(value) {
    return typeof value === "string" && value.toLowerCase().includes("deprecated");
  }

  function applyActiveFilter(payload) {
    const resourceId = payload.id;
    const relations = payload.relations.filter((relation) => {
      const otherId = relation.subject === resourceId ? relation.object : relation.subject;
      if (otherId === resourceId) return true; // self-loop: always visible, as in the original
      const otherStatus = relation.subject === resourceId ? relation.object_status : relation.subject_status;
      return !isDeprecatedStatus(otherStatus);
    });
    return { ...payload, relations };
  }

  // REF-042 derived rows are non-authoritative and opt-in, so they are dropped
  // unless the caller asks for them. They travel in the same `relations` array
  // as asserted statements (that is what the local explorer's API does for
  // relations="all"), distinguished only by statement_type, so filtering here
  // is what keeps the default view to publisher-asserted facts alone.
  function applyRelationsFilter(payload, relations) {
    if (relations === "all") return payload;
    return {
      ...payload,
      relations: payload.relations.filter((r) => r.statement_type !== "DerivedRelation"),
    };
  }

  async function resource({ id, status = "active", relations = "asserted" }) {
    const { conn } = await ensureDuckDB();
    const indexRows = rowsOf(
      await conn.query(`
        SELECT shard, offset, length FROM resource_detail_index WHERE id = ${sqlString(id)}
      `)
    );
    if (indexRows.length !== 1) {
      throw new Error("resource is not present in the Parquet view");
    }
    const { shard, offset, length } = indexRows[0];
    // Bodies are sharded (see build/precompute.py) so no single NDJSON file
    // approaches wrangler's 300MiB upload ceiling; the index above records
    // which shard a resource's bytes live in alongside the byte range.
    const shardName = String(shard).padStart(3, "0");
    const url = `${DATA_BASE}/tables/resource-detail/${shardName}.ndjson`;
    const response = await fetch(url, {
      headers: { range: `bytes=${offset}-${offset + length - 1}` },
    });
    if (response.status !== 206 && response.status !== 200) {
      throw new Error(`${url}: HTTP ${response.status}`);
    }
    const text = await response.text();
    const payload = JSON.parse(text);
    const scoped = applyRelationsFilter(payload, relations);
    return status === "all" ? scoped : applyActiveFilter(scoped);
  }

  // ---- /api/agency-projection -----------------------------------------------
  let agenciesPromise = null;
  function agenciesData() {
    if (!agenciesPromise) agenciesPromise = fetchJson(`${DATA_BASE}/agencies.json`);
    return agenciesPromise;
  }

  async function agencyProjection(query) {
    const data = await agenciesData();
    if (!data.available) return data;
    const needle = (query || "").trim().toLowerCase();
    if (!needle) return data;
    const resolved = data.resolved.filter(
      (row) =>
        row.source_value?.toLowerCase().includes(needle) ||
        row.pref_label?.toLowerCase().includes(needle) ||
        (row.aliases || []).some((v) => v.toLowerCase().includes(needle)) ||
        (row.abbreviations || []).some((v) => v.toLowerCase().includes(needle))
    );
    const unresolved = data.unresolved.filter(
      (row) =>
        row.source_value?.toLowerCase().includes(needle) ||
        row.pref_label?.toLowerCase().includes(needle)
    );
    return { available: true, resolved, unresolved };
  }

  // ---- router: window.AtlasData.get(path) mirrors explorer_cli.py's do_GET -
  async function get(path) {
    const url = new URL(path, location.origin);
    const q = url.searchParams;
    switch (url.pathname) {
      case "/api/facets":
        return fetchJson(`${DATA_BASE}/facets.json`);
      case "/api/overview": {
        const status = q.get("status") || "active";
        return fetchJson(`${DATA_BASE}/overview-${status === "all" ? "all" : "active"}.json`);
      }
      case "/api/release-graph": {
        const id = q.get("id") || "";
        const status = q.get("status") || "active";
        const index = await releaseIndex();
        const slug = index[id];
        if (!slug) throw new Error("release is not present in the Parquet view");
        return fetchJson(`${DATA_BASE}/release-graph/${slug}-${status === "all" ? "all" : "active"}.json`);
      }
      case "/api/search":
        return search({
          q: q.get("q") || "",
          release: q.get("release") || "",
          releases: q.getAll("release"),
          ring: q.get("ring") || "",
          status: q.get("status") || "active",
          limit: Number(q.get("limit") || 100),
          offset: Number(q.get("offset") || 0),
        });
      case "/api/resource":
        return resource({
          id: q.get("id") || "",
          status: q.get("status") || "active",
          relations: q.get("relations") || "asserted",
        });
      case "/api/agency-projection":
        return agencyProjection(q.get("q") || "");
      default:
        throw new Error(`not found: ${url.pathname}`);
    }
  }

  window.AtlasData = { get, ensureDuckDB, tokenize };
})();

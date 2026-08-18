/**
 * RefSpec Atlas explorer -- Cloudflare Worker.
 *
 * Two jobs:
 *  1. Serve the static frontend (three pages + vendored DuckDB-Wasm engine
 *     + the data layer) via the Workers Static Assets binding.
 *  2. Proxy GET/HEAD reads of the private R2 bucket under `/data/<key>`,
 *     forwarding Range/If-Range/If-None-Match and returning correct
 *     206/200/304 responses with Accept-Ranges/Content-Range/ETag -- this
 *     is what lets DuckDB-Wasm's HTTP filesystem read a few row groups out
 *     of a multi-hundred-MB Parquet file instead of downloading the whole
 *     object.
 *
 * The bucket has no public access (no r2.dev URL, no custom domain) --
 * this Worker's R2 binding is the only reader, and it never exposes PUT
 * or DELETE. Same-origin also means the app never needs CORS headers: the
 * page and the data it queries are served from the same Worker.
 */

const PAGE_ROUTES = {
  "/": "/index.html",
  "/release": "/release.html",
  "/agencies": "/agencies.html",
};

const DATA_PREFIX = "/data/";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname.startsWith(DATA_PREFIX)) {
      return handleData(request, env, url);
    }

    const rewrite = PAGE_ROUTES[url.pathname];
    if (rewrite) {
      const assetUrl = new URL(request.url);
      assetUrl.pathname = rewrite;
      // Build the sub-request from scratch (method/headers only) instead
      // of `new Request(assetUrl, request)`: the incoming request carries
      // redirect:"manual", and copying that meant a redirect the asset
      // server issued for the rewritten path (observed for "/release" and
      // "/agencies", though not "/") came straight back to the client
      // unfollowed, as a 307 to the same URL it was already at.
      return env.ASSETS.fetch(
        new Request(assetUrl, { method: request.method, headers: request.headers })
      );
    }

    return env.ASSETS.fetch(request);
  },
};

async function handleData(request, env, url) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", { status: 405, headers: { allow: "GET, HEAD" } });
  }

  const key = decodeKey(url.pathname.slice(DATA_PREFIX.length));
  if (!key) {
    return new Response("Not found", { status: 404 });
  }

  if (request.method === "HEAD") {
    const head = await env.BUCKET.head(key);
    if (!head) return new Response(null, { status: 404 });
    const headers = new Headers();
    head.writeHttpMetadata(headers);
    headers.set("etag", head.httpEtag);
    headers.set("accept-ranges", "bytes");
    headers.set("cache-control", "public, max-age=300, must-revalidate");

    // DuckDB-Wasm's HTTP filesystem probes range support with a bare
    // `HEAD` + `Range: bytes=0-` *before* it ever issues a ranged GET, and
    // falls back to downloading the whole file if that probe doesn't come
    // back 206. R2Bucket.head() has no range option (HEAD never has a
    // body to slice), so the partial-content response is computed by hand
    // here from `head.size` -- same math the GET branch below uses.
    const rangeHeader = request.headers.get("range");
    if (rangeHeader) {
      const parsed = parseRange(rangeHeader, head.size);
      if (!parsed) {
        headers.set("content-range", `bytes */${head.size}`);
        return new Response(null, { status: 416, headers });
      }
      headers.set("content-range", `bytes ${parsed.offset}-${parsed.offset + parsed.length - 1}/${head.size}`);
      headers.set("content-length", String(parsed.length));
      return new Response(null, { status: 206, headers });
    }

    headers.set("content-length", String(head.size));
    return new Response(null, { status: 200, headers });
  }

  const object = await env.BUCKET.get(key, {
    range: request.headers,
    onlyIf: request.headers,
  });

  if (!object) {
    return new Response("Not found", { status: 404 });
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("accept-ranges", "bytes");
  headers.set("cache-control", "public, max-age=300, must-revalidate");

  // Conditional GET (If-None-Match / If-Modified-Since) succeeded but the
  // precondition means "not modified": R2 returns the object with no body.
  if (!("body" in object) || object.body === null) {
    return new Response(null, { status: 304, headers });
  }

  // Trust the incoming Range header, not just object.range's presence --
  // R2 populates `.range` with `{offset: 0, length: size}` for a full,
  // unranged GET too, which would otherwise look like a satisfied range.
  const range = object.range;
  if (request.headers.has("range") && range) {
    const size = object.size;
    const offset = range.offset ?? (typeof range.suffix === "number" ? size - range.suffix : 0);
    const length = range.length ?? size - offset;
    headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${size}`);
    headers.set("content-length", String(length));
    return new Response(object.body, { status: 206, headers });
  }

  headers.set("content-length", String(object.size));
  return new Response(object.body, { status: 200, headers });
}

// Parses a single-range `Range: bytes=...` header against a known total
// size. Returns null for anything unsatisfiable or multi-range (multi-range
// isn't needed here -- neither the HEAD probe nor DuckDB-Wasm's actual
// row-group reads send more than one range per request).
function parseRange(header, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match || size <= 0) return null;
  const [, startText, endText] = match;
  if (startText === "" && endText === "") return null;
  let offset;
  let length;
  if (startText === "") {
    // Suffix range: "bytes=-N" -> last N bytes.
    const suffix = Number(endText);
    if (!Number.isFinite(suffix) || suffix <= 0) return null;
    length = Math.min(suffix, size);
    offset = size - length;
  } else {
    offset = Number(startText);
    if (!Number.isFinite(offset) || offset < 0 || offset >= size) return null;
    const end = endText === "" ? size - 1 : Math.min(Number(endText), size - 1);
    if (!Number.isFinite(end) || end < offset) return null;
    length = end - offset + 1;
  }
  return { offset, length };
}

function decodeKey(rawKey) {
  let key;
  try {
    key = decodeURIComponent(rawKey);
  } catch {
    return null;
  }
  if (!key || key.includes("..") || key.startsWith("/")) return null;
  return key;
}

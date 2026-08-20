"""Precompute browser-friendly artifacts for the Cloudflare Atlas explorer.

Run this against the verified compact Parquet search view that already
serves the local explorer (``refspec-atlas-explorer``). It never edits or
reinterprets that view -- every JSON artifact below is produced by calling
the *existing*, already-verified ``AtlasDuckDBView`` methods
(``facets``/``overview``/``release_graph``) unchanged, and every reshaped
Parquet table is produced by SQL copied verbatim (or trivially projected)
from ``src/refspec/atlas/duckdb_view.py``. This script exists only because a
browser cold-querying the full compact view over HTTP range requests cannot
afford whole-corpus aggregates or an unsorted point lookup the way an
in-process local DuckDB session can.

Output layout (all under --out):
  facets.json                          view.facets(), verbatim
  browse-first-page.json               the ported frontend's fixed initial
                                        search() call (q="", no filters,
                                        status=active, limit=40, offset=0)
                                        -- served without loading DuckDB-Wasm
  overview-active.json                 view.overview(status="active")
  overview-all.json                    view.overview(status="all")
  agencies.json                        view.agency_projection(""), verbatim
  release-graph/<slug>-active.json     view.release_graph(id, status="active")
  release-graph/<slug>-all.json        view.release_graph(id, status="all")
  release-index.json                   release id -> slug, for the frontend
  tables/resources.parquet             atlas_resources + a denormalized best
                                        English label, sorted by id (point
                                        lookups for /resource and for
                                        hydrating search-ranked ids)
  tables/browse-order.parquet          id,label,release,ring,status sorted
                                        by (lower(label), label, id) -- the
                                        no-query browse/pagination path
  tables/resource-detail/NNN.ndjson    one JSON line per resource -- the
                                        same shape AtlasDuckDBView.resource()
                                        returns, ALWAYS the unfiltered
                                        status="all" relation set (each
                                        relation additionally carries
                                        subject_status/object_status so the
                                        browser can derive status="active"
                                        by filtering client-side -- see
                                        "resource-detail bundles" below for
                                        why one asymmetric-superset payload
                                        replaces what used to be two
                                        near-duplicate precomputed bodies).
                                        Sharded into ~250MB files (wrangler's
                                        own upload ceiling is 300MiB; the
                                        full corpus, each resource carrying
                                        verbose full IRIs/URNs per relation,
                                        runs to several GB).
  tables/resource-detail-index.parquet id -> (shard,offset,length) into the
                                        shard directory above, sorted by id.
                                        See "resource-detail bundles" below
                                        for *why* this exists instead of
                                        DuckDB-Wasm views over
                                        labels/identifiers/statements/
                                        evidence-bindings/source-records.
  search/fts-dict.parquet              term,termid,df sorted by term
  search/fts-terms.parquet             termid,docid,tf sorted by termid,docid
  search/fts-docs.parquet              docid,id,len sorted by docid
  search/fts-meta.json                 {numDocs, avgdl, k, b, field}

The FTS export mirrors DuckDB's own bundled full-text-search extension: the
`dict`/`terms`/`docs`/`stats` tables `PRAGMA create_fts_index` builds, and
the exact BM25 formula its `match_bm25` SQL macro evaluates (both captured
verbatim below). The browser reimplements that macro in plain SQL against
these exported tables -- it never re-derives the index, so it never scans
label text cold.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from refspec.atlas.duckdb_view import open_atlas_duckdb_view  # noqa: E402
from refspec.registry.infrastructure.artifact_serialization import (  # noqa: E402
    sha256_digest,
)

_COPY_OPTS = "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 19, ROW_GROUP_SIZE 50000)"

# Exact SQL used by AtlasDuckDBView._prepare_search_documents(full_text=True)
# in src/refspec/atlas/duckdb_view.py -- copied verbatim so the FTS index we
# export here scores identically to the one the local explorer builds.
_SEARCH_DOCUMENTS_SQL = """
CREATE TABLE atlas_search_documents AS
WITH label_groups AS (
    SELECT
        resource,
        first(
            value
            ORDER BY
                CASE label_role
                    WHEN 'preferred' THEN 0
                    WHEN 'alternate' THEN 1
                    WHEN 'hidden' THEN 2
                    ELSE 99
                END,
                lower(value),
                value
        ) AS display_label,
        string_agg(value, ' ' ORDER BY lower(value), value) AS aliases
    FROM atlas_labels
    WHERE lower(language) = 'en'
    GROUP BY resource
), identifier_groups AS (
    SELECT
        identifies AS resource,
        string_agg(
            identifier_value,
            ' '
            ORDER BY lower(identifier_value), identifier_value
        ) AS identifiers
    FROM atlas_identifiers
    GROUP BY identifies
)
SELECT
    resource.id,
    coalesce(
        labels.display_label,
        nullif(regexp_extract(resource.id, '([^#/:]+)[/#:]?$', 1), ''),
        resource.id
    ) AS label,
    concat_ws(
        ' ',
        labels.aliases,
        array_to_string(resource.notations, ' '),
        identifiers.identifiers,
        resource.id,
        resource.definition
    ) AS search_text
FROM atlas_resources AS resource
LEFT JOIN label_groups AS labels ON labels.resource = resource.id
LEFT JOIN identifier_groups AS identifiers ON identifiers.resource = resource.id
ORDER BY resource.id
"""

# Exact PRAGMA call AtlasDuckDBView uses -- same stemmer/stopwords/ignore.
_CREATE_FTS_INDEX_SQL = """
PRAGMA create_fts_index(
    'atlas_search_documents',
    'id',
    'search_text',
    stemmer = 'none',
    stopwords = 'none',
    ignore = '(\\.|[^a-z0-9])+'
)
"""

_RANKED_LABEL_SQL = """
CREATE TABLE ranked_labels AS
WITH ranked AS (
    SELECT
        resource,
        value,
        row_number() OVER (
            PARTITION BY resource
            ORDER BY
                CASE label_role
                    WHEN 'preferred' THEN 0
                    WHEN 'alternate' THEN 1
                    WHEN 'hidden' THEN 2
                    ELSE 99
                END,
                lower(value),
                value
        ) AS label_rank
    FROM atlas_labels
    WHERE lower(language) = 'en'
)
SELECT resource AS id, value AS label
FROM ranked
WHERE label_rank = 1
"""


def _slug(release_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", release_id).strip("-").lower()


# The local explorer draws these graphs with a canvas that already does
# level-of-detail rendering (a spatial culling grid, a dot fallback past
# DOT_LIMIT, edges gated off past EDGE_VISIBLE_LIMIT/zoom) -- it never
# actually resolves more than a few thousand nodes on screen at once even
# for a 500k-concept vocabulary. Shipping the *complete* node+edge JSON for
# a release that size would make a single /release page load cost tens of
# megabytes, which fails the same per-page-transfer bar as a cold column
# scan. Cap it to the highest-degree nodes -- the ones actually visible/
# reachable in the local explorer's own default view -- and say so in the
# payload so the frontend can render the truncation, not hide it.
_RELEASE_GRAPH_NODE_CAP = 4000


def _cap_release_graph(data: dict[str, object]) -> dict[str, object]:
    nodes = list(data["nodes"])  # type: ignore[arg-type]
    total = len(nodes)
    if total <= _RELEASE_GRAPH_NODE_CAP:
        return data
    edges = list(data["edges"])  # type: ignore[arg-type]
    degree = [0] * total
    for subject, obj, _predicate, _type in edges:
        degree[subject] += 1
        degree[obj] += 1
    ranked = sorted(range(total), key=lambda i: (-degree[i], i))
    kept = sorted(ranked[:_RELEASE_GRAPH_NODE_CAP])
    keep_set = set(kept)
    remap = {old: new for new, old in enumerate(kept)}
    new_nodes = [nodes[i] for i in kept]
    new_edges = []
    dropped_by_truncation = 0
    for subject, obj, predicate, statement_type in edges:
        if subject in keep_set and obj in keep_set:
            new_edges.append([remap[subject], remap[obj], predicate, statement_type])
        else:
            dropped_by_truncation += 1
    counts = dict(data["counts"])  # type: ignore[arg-type]
    counts["totalResources"] = total
    counts["resources"] = len(new_nodes)
    counts["relations"] = len(new_edges)
    counts["droppedByTruncation"] = dropped_by_truncation
    return {
        **data,
        "nodes": new_nodes,
        "edges": new_edges,
        "counts": counts,
        "truncated": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search_view", type=Path, help="verified compact Parquet search view directory")
    parser.add_argument("--out", type=Path, required=True, help="output directory for precomputed artifacts")
    parser.add_argument("--manifest-digest", help="trusted manifest digest; defaults to the local manifest bytes")
    args = parser.parse_args()

    root = args.search_view.resolve(strict=True)
    out = args.out.resolve()
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "search").mkdir(parents=True, exist_ok=True)
    (out / "release-graph").mkdir(parents=True, exist_ok=True)

    manifest_path = root / "search-view-manifest.json"
    digest = args.manifest_digest or sha256_digest(manifest_path.read_bytes())
    print(f"opening verified view at {root} (manifest {digest[:23]}...)")
    view = open_atlas_duckdb_view(root, trusted_manifest_digest=digest)
    con = view._connection  # noqa: SLF001 -- this build script is part of the
    # deploy project, not the library; it needs raw SQL/COPY access to the
    # same session AtlasDuckDBView already verified and wired up, rather than
    # re-deriving the connection (and re-verifying the artifact) itself.

    t0 = time.time()

    # ---- facets.json ------------------------------------------------
    print("facets ...")
    (out / "facets.json").write_text(json.dumps(view.facets(), ensure_ascii=False))

    # ---- overview-{active,all}.json ---------------------------------
    for status in ("active", "all"):
        print(f"overview status={status} ...")
        data = view.overview(status=status)
        (out / f"overview-{status}.json").write_text(json.dumps(data, ensure_ascii=False))

    # ---- browse-first-page.json ----------------------------------------
    # The ported frontend JS (unmodified from explorer_frontend.py) calls
    # runSearch() once, unconditionally, right after the page loads -- the
    # local Python explorer answers that instantly from its in-process
    # DuckDB session, but the browser would otherwise have to pull down the
    # whole DuckDB-Wasm query engine (~34MB) just to render a page nobody
    # has interacted with yet. That first call's parameters are always the
    # same fixed default (q="", no release/ring filter, status=active,
    # limit=40 -- app.searchLimit in the frontend JS -- offset=0), so it is
    # precomputed here (building atlas_search_documents now, ahead of the
    # FTS export below, which reuses it); the data layer serves this as a
    # static fetch and only loads DuckDB-Wasm once the visitor actually
    # types, filters, or scrolls for more.
    print("browse-first-page (default no-query search(), first 40) ...")
    con.execute(_SEARCH_DOCUMENTS_SQL)
    browse_first_page = view.query_rows(
        """
        SELECT
            resource.definition,
            document.id,
            document.label,
            resource.notations,
            resource.resource_profile AS profile,
            resource.release,
            resource.semantic_ring AS ring
        FROM atlas_search_documents AS document
        JOIN atlas_resources AS resource ON resource.id = document.id
        WHERE resource.record_status IS NULL
           OR lower(resource.record_status) NOT LIKE '%deprecated%'
        ORDER BY lower(document.label), document.label, document.id
        LIMIT 40 OFFSET 0
        """
    )
    (out / "browse-first-page.json").write_text(json.dumps(browse_first_page, ensure_ascii=False))

    # ---- agencies.json ------------------------------------------------
    print("agency projection ...")
    (out / "agencies.json").write_text(json.dumps(view.agency_projection(""), ensure_ascii=False))

    # ---- release-graph/<slug>-{status}.json + release-index.json -----
    releases = view.query_rows(
        "SELECT id, identifier FROM atlas_releases WHERE release_type = 'AtlasRelease' ORDER BY id"
    )
    slugs: dict[str, str] = {}
    total_bytes = 0
    for i, release in enumerate(releases):
        release_id = release["id"]
        slug = _slug(release_id)
        slugs[release_id] = slug
        for status in ("active", "all"):
            data = _cap_release_graph(view.release_graph(release_id, status=status))
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            path = out / "release-graph" / f"{slug}-{status}.json"
            path.write_text(payload)
            total_bytes += len(payload)
        if (i + 1) % 10 == 0 or i + 1 == len(releases):
            print(f"  release-graph {i + 1}/{len(releases)} ({total_bytes / 1e6:.1f} MB so far)")
    (out / "release-index.json").write_text(json.dumps(slugs, ensure_ascii=False))

    # ---- tables/resources.parquet (id-sorted, denormalized label) ----
    print("resources (id-sorted, with denormalized label) ...")
    con.execute(_RANKED_LABEL_SQL)
    con.execute(
        """
        CREATE TABLE resources_out AS
        SELECT
            r.id,
            coalesce(
                l.label,
                nullif(regexp_extract(r.id, '([^#/:]+)[/#:]?$', 1), ''),
                r.id
            ) AS label,
            r.release,
            r.semantic_ring AS ring,
            r.resource_profile AS profile,
            r.notations,
            r.notes,
            r.definition,
            r.record_status AS status,
            r.scheme,
            r.source_record
        FROM atlas_resources AS r
        LEFT JOIN ranked_labels AS l ON l.id = r.id
        ORDER BY r.id
        """
    )
    con.execute(f"COPY resources_out TO '{out / 'tables' / 'resources.parquet'}' {_COPY_OPTS}")

    # ---- tables/browse-order.parquet (label-sorted browse index) -----
    print("browse-order (label-sorted) ...")
    con.execute(
        f"""
        COPY (
            SELECT id, label, release, ring, status
            FROM resources_out
            ORDER BY lower(label), label, id
        ) TO '{out / 'tables' / 'browse-order.parquet'}' {_COPY_OPTS}
        """
    )

    # ---- resource-detail bundles (NDJSON body + byte-offset index) -------
    #
    # DuckDB-Wasm's parquet reader, as deployed here, does not do row-group
    # -level range reads: touching (even just CREATE VIEW-ing) any remote
    # Parquet file downloads that whole file once, with no smaller ranged
    # requests observed for either small (identifiers, 0.25MB) or large
    # (labels, evidence-bindings) tables, confirmed against the live
    # deployment via Chrome DevTools network inspection (HEAD probes with
    # an explicit Range header come back 206 correctly -- the Worker's
    # /data/* proxy is not the bottleneck -- but DuckDB-Wasm's own reads
    # never send a Range header at all). Left as designed, the resource
    # detail inspector -- which needs labels, identifiers, statements,
    # evidence-bindings, and source-records -- would download all five
    # tables (~700MB) on the very first click, which is exactly the
    # "hundreds of MB" failure mode this deployment must avoid.
    #
    # The fix routes around DuckDB-Wasm for this path entirely: every
    # resource's full detail payload (identical in shape to
    # AtlasDuckDBView.resource()) is precomputed here, for both status
    # variants, into one big newline-delimited JSON file per status, plus
    # a small sorted (id -> byte offset, length) index. The browser looks
    # up the offset for the clicked id (in the already-small, already
    # -downloaded-once index) and then issues one plain `fetch()` with an
    # explicit `Range` header directly against the NDJSON body -- the
    # Worker's proxy already proves out correctly for exactly this
    # (curl-verified 206/Content-Range) -- so only that one resource's
    # bytes ever cross the wire, independent of how DuckDB-Wasm behaves.
    print("resource-detail bundles (bulk index, then per-resource assembly) ...")
    t_detail = time.time()

    def _short(value: str | None) -> str:
        if not value:
            return ""
        return value.rsplit("#", 1)[-1].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]

    print("  loading resources ...")
    resources_by_id: dict[str, dict] = {
        row["id"]: row for row in view.query_rows("SELECT * FROM resources_out")
    }

    print("  loading labels (English) ...")
    label_groups: dict[str, list[dict]] = {}
    for row in view.query_rows(
        """
        SELECT resource, label_role AS role, value, language
        FROM atlas_labels
        WHERE lower(language) = 'en'
        ORDER BY resource,
            CASE label_role WHEN 'preferred' THEN 0 WHEN 'alternate' THEN 1 WHEN 'hidden' THEN 2 ELSE 99 END,
            lower(value), value
        """
    ):
        label_groups.setdefault(row.pop("resource"), []).append(row)

    print("  loading identifiers ...")
    identifier_groups: dict[str, list[dict]] = {}
    for row in view.query_rows(
        """
        SELECT identifies, identifier_scheme AS scheme, identifier_value AS value
        FROM atlas_identifiers
        ORDER BY identifies, lower(identifier_value), identifier_value
        """
    ):
        identifier_groups.setdefault(row.pop("identifies"), []).append(row)

    print("  loading statements (building subject/object adjacency) ...")
    adjacency: dict[str, list[dict]] = {}
    for row in view.query_rows("SELECT * FROM atlas_statements ORDER BY id"):
        adjacency.setdefault(row["subject"], []).append(row)
        if row["object"] != row["subject"]:
            adjacency.setdefault(row["object"], []).append(row)

    # REF-042 derived relations. Non-authoritative and opt-in: they ride in the
    # same per-resource `relations` array as asserted statements -- which is what
    # the local explorer's API does for relations="all" -- but carry
    # statement_type "DerivedRelation", so the client can filter them out and
    # does by default. They are NOT evidence-bound: no publisher asserted them,
    # so `evidence` stays empty and `derivation_rule` / `derived_from_assertions`
    # name the rule and the asserted rows it read instead.
    #
    # Read straight from the Parquet rather than through the view's lazily
    # registered atlas_derived_relations, and tolerate its absence: every view
    # sealed before the derived graph existed, and every build whose rules
    # emitted nothing, ships without this table. Missing table => no derived
    # rows => the client's toggle stays hidden, exactly as
    # DuckDBAtlasView.derived_relations_available() intends.
    derived_adjacency: dict[str, list[dict]] = {}
    derived_path = root / "tables" / "derived-relations.parquet"
    if derived_path.is_file():
        print("  loading derived relations (REF-042, non-authoritative) ...")
        for row in view.query_rows(
            f"""
            SELECT id, subject, predicate, object, semantic_ring,
                   derivation_rule, engine, engine_version, derived_from_assertions
            FROM read_parquet('{derived_path.as_posix()}')
            ORDER BY id
            """
        ):
            row["statement_type"] = "DerivedRelation"
            derived_adjacency.setdefault(row["subject"], []).append(row)
            if row["object"] != row["subject"]:
                derived_adjacency.setdefault(row["object"], []).append(row)
        print(
            f"    {sum(len(v) for v in derived_adjacency.values()):,} endpoint attachments"
            f" over {len(derived_adjacency):,} resources"
        )
    else:
        print("  no derived-relations.parquet in this view -- skipping (expected pre-REF-042)")

    print("  loading evidence bindings (joined to source records) ...")
    evidence_by_statement: dict[str, list[dict]] = {}
    for row in view.query_rows(
        """
        SELECT evidence.*, source.source_release, source.source_locator
        FROM atlas_evidence_bindings AS evidence
        LEFT JOIN atlas_source_records AS source ON source.id = evidence.source_record
        ORDER BY evidence.statement, evidence.evidence_id
        """
    ):
        evidence_by_statement.setdefault(row["statement"], []).append(
            {
                "attestedAt": row["attested_at"],
                "decision": row["decision"],
                "id": f"urn:ref:atlas-evidence:{row['evidence_id'].hex()}",
                "attestor": row["attestor"],
                "evidenceRole": row["evidence_role"],
                "sourceLocator": row["source_locator"],
                "sourceRecord": row["source_record"],
                "sourceRelease": row["source_release"],
            }
        )

    # One assembly, not two: earlier this ran once per status ("active"
    # dropping relations to a deprecated *other* endpoint, "all" keeping
    # everything) and shipped both as separate precomputed bodies -- which
    # is exactly why the bucket was ~17GB of near-duplicate resource-detail
    # data (8.4GB "active" + 8.5GB "all", differing only by which relations
    # each resource's JSON happens to include). "all" is a strict superset
    # of "active" per resource, so only it is precomputed now, WITH each
    # relation's endpoint statuses attached; data-layer.js's resource()
    # applies the exact same "hide relations to a deprecated other endpoint"
    # rule client-side against that one payload when status=active (the
    # default). Same two visible states, half the storage, no duplication.
    def _assemble(resource_id: str, resource: dict) -> dict:
        relations = []
        for statement in adjacency.get(resource_id, ()):
            relation = dict(statement)
            evidence = evidence_by_statement.get(relation["id"], [])
            relation["evidence"] = evidence
            relation["evidence_count"] = len(evidence)
            for side in ("subject", "object"):
                endpoint = resources_by_id.get(relation[side], {})
                relation[f"{side}_label"] = endpoint.get("label") or _short(relation[side])
                relation[f"{side}_release"] = endpoint.get("release")
                relation[f"{side}_ring"] = endpoint.get("ring")
                relation[f"{side}_profile"] = endpoint.get("profile")
                relation[f"{side}_status"] = endpoint.get("status")
            relations.append(relation)
        for derived in derived_adjacency.get(resource_id, ()):
            relation = dict(derived)
            # Deliberately empty: a derived row is not evidence-bound, and
            # showing an evidence affordance for one would imply a publisher
            # stood behind it. derivation_rule / derived_from_assertions carry
            # the provenance instead.
            relation["evidence"] = []
            relation["evidence_count"] = 0
            for side in ("subject", "object"):
                endpoint = resources_by_id.get(relation[side], {})
                relation[f"{side}_label"] = endpoint.get("label") or _short(relation[side])
                relation[f"{side}_release"] = endpoint.get("release")
                relation[f"{side}_ring"] = endpoint.get("ring")
                relation[f"{side}_profile"] = endpoint.get("profile")
                relation[f"{side}_status"] = endpoint.get("status")
            relations.append(relation)
        relations.sort(key=lambda r: r["id"])
        return {
            "definition": resource["definition"],
            "id": resource_id,
            "identifiers": identifier_groups.get(resource_id, []),
            "labels": label_groups.get(resource_id, []),
            "notations": resource["notations"] or [],
            "notes": resource["notes"] or [],
            "profile": resource["profile"],
            "relations": relations,
            "release": resource["release"],
            "ring": resource["ring"],
            "scheme": resource["scheme"],
            "sourceRecord": resource["source_record"],
            "status": resource["status"],
        }

    # Every resource's relations carry full IRIs/URNs (subject, object,
    # predicate, source/target release, evidence locators, ...), so even a
    # median-degree-2 resource's JSON runs a few KB -- across 1.497M
    # resources that adds up to a single NDJSON body of several GB. R2's
    # object-size limit is ~5GiB, but `wrangler r2 object put` itself
    # refuses anything over 300MiB ("Wrangler only supports uploading
    # files up to 300 MiB in size") regardless of what the API would
    # accept -- confirmed empirically after a 750MB/shard attempt failed
    # every shard upload. Each shard is its own file, sized with real
    # margin under that 300MiB wrangler ceiling; the offset index below
    # records which shard a resource's bytes live in, alongside the
    # (offset, length) pair -- the range-fetch in data-layer.js just adds
    # the shard number into the URL.
    _SHARD_TARGET_BYTES = 250_000_000  # ~250MB/shard: safe under wrangler's 300MiB cap
    print(f"  indices built in {time.time() - t_detail:.1f}s; assembling {len(resources_by_id):,} resources ...")
    offset_index: list[dict] = []
    shard_dir = out / "tables" / "resource-detail"
    shard_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale shards first. Shard COUNT depends on corpus size and on the
    # target shard byte size, so a re-run against a different search view (or
    # after a shard-size change) can write FEWER shards than the last run left
    # behind. The leftovers are unreachable -- resource-detail-index.parquet is
    # rewritten below and only ever names shards this run produced -- but
    # upload.sh walks the directory, so they would ship to R2 and sit there as
    # orphaned objects carrying a previous build's corpus. That is how this
    # directory reached 265 shards / 16GB when the run had written 38 / 8.8GB.
    for stale in shard_dir.glob("*.ndjson"):
        stale.unlink()
    shard_index = 0
    shard_file = (shard_dir / f"{shard_index:03d}.ndjson").open("wb")
    offset = 0
    shard_bytes_total = 0
    try:
        for i, (resource_id, resource) in enumerate(resources_by_id.items()):
            payload = json.dumps(_assemble(resource_id, resource), ensure_ascii=False)
            # Binary mode, writing pre-encoded bytes: offsets/lengths are
            # computed from those exact bytes, so there is no room for a
            # text-mode newline-translation mismatch to desync the byte
            # index from what's actually on disk.
            encoded = (payload + "\n").encode("utf-8")
            length = len(encoded)
            if offset + length > _SHARD_TARGET_BYTES and offset > 0:
                shard_file.close()
                shard_bytes_total += offset
                shard_index += 1
                shard_file = (shard_dir / f"{shard_index:03d}.ndjson").open("wb")
                offset = 0
            offset_index.append({"id": resource_id, "shard": shard_index, "offset": offset, "length": length})
            shard_file.write(encoded)
            offset += length
            if (i + 1) % 300_000 == 0:
                print(f"    {i + 1:,}/{len(resources_by_id):,} ({time.time() - t_detail:.1f}s elapsed)")
    finally:
        shard_file.close()
        shard_bytes_total += offset
    print(f"  resource-detail/: {shard_index + 1} shard(s), {shard_bytes_total / 1e6:.1f} MB")

    print("  writing resource-detail-index.parquet (id-sorted) ...")
    index_table = pa.Table.from_pylist(offset_index)
    index_table = index_table.sort_by("id")
    pq.write_table(
        index_table,
        out / "tables" / "resource-detail-index.parquet",
        compression="zstd",
        compression_level=19,
        row_group_size=50_000,
    )
    print(f"  resource-detail total: {time.time() - t_detail:.1f}s")

    # ---- FTS index export ------------------------------------------------
    # atlas_search_documents was already built above (browse-first-page.json).
    print("building FTS index (INSTALL/LOAD fts; PRAGMA create_fts_index) ...")
    con.execute("INSTALL fts")
    con.execute("LOAD fts")
    con.execute(_CREATE_FTS_INDEX_SQL)

    print("exporting fts-dict.parquet (term-sorted) ...")
    con.execute(
        f"""
        COPY (
            SELECT term, termid, df
            FROM fts_main_atlas_search_documents.dict
            ORDER BY term
        ) TO '{out / 'search' / 'fts-dict.parquet'}' {_COPY_OPTS}
        """
    )

    print("exporting fts-terms.parquet (termid-sorted, pre-aggregated tf) ...")
    con.execute(
        f"""
        COPY (
            SELECT termid, docid, count(*) AS tf
            FROM fts_main_atlas_search_documents.terms
            GROUP BY termid, docid
            ORDER BY termid, docid
        ) TO '{out / 'search' / 'fts-terms.parquet'}' {_COPY_OPTS}
        """
    )

    print("exporting fts-docs.parquet (docid-sorted) ...")
    con.execute(
        f"""
        COPY (
            SELECT docid, name AS id, len
            FROM fts_main_atlas_search_documents.docs
            ORDER BY docid
        ) TO '{out / 'search' / 'fts-docs.parquet'}' {_COPY_OPTS}
        """
    )

    stats = view.query_rows("SELECT num_docs, avgdl FROM fts_main_atlas_search_documents.stats")[0]
    (out / "search" / "fts-meta.json").write_text(
        json.dumps(
            {
                "numDocs": stats["num_docs"],
                "avgdl": stats["avgdl"],
                "k": 1.2,
                "b": 0.75,
                "field": "search_text",
            }
        )
    )

    view.close()

    # ---- report sizes ---------------------------------------------------
    print(f"\nDone in {time.time() - t0:.1f}s. Artifact sizes:")
    total = 0
    for path in sorted(out.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            total += size
    for sub in ("tables", "search", "release-graph"):
        subtotal = sum(p.stat().st_size for p in (out / sub).rglob("*") if p.is_file())
        print(f"  {sub}/  {subtotal / 1e6:.1f} MB")
    for name in ("facets.json", "overview-active.json", "overview-all.json", "agencies.json", "release-index.json"):
        p = out / name
        if p.is_file():
            print(f"  {name}  {p.stat().st_size / 1e3:.1f} KB")
    print(f"  TOTAL  {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

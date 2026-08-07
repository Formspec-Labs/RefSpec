"""Build the Atlas browser directly from the compact Parquet search view."""

from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.explorer_rdf import (
    _EXPLORER_RECORD_PREFIX_LENGTH,
    _EXPLORER_SHARD_BUNDLE_TYPE,
    _EXPLORER_SHARD_INDEX_TYPE,
    _EXPLORER_SHARD_SCHEMA,
    _EXPLORER_SHARD_VERSION,
    ATLAS_PARQUET_EXPLORER_SHARD_BUILDER_RECIPE,
    ATLAS_V3_EXPLORER_SCHEMA_VERSION,
    ATLAS_V3_EXPLORER_TYPE,
    EXPLORER_FILTER_SEMANTICS,
    EXPLORER_SCHEMA_VERSION,
    EXPLORER_TYPE,
    PLANNING_FILTER_SEMANTICS,
    Atlas3ExplorerError,
    AtlasExplorerError,
    _explorer_hash_prefix,
    _finalize_explorer_page_shards,
    _finalize_explorer_record_shards,
    _finalize_explorer_resource_summaries,
    _JsonlSpool,
    _safe_existing_shard_directory,
    _write_explorer_shard,
    render_atlas_explorer,
    render_atlas_v3_explorer,
)
from refspec.atlas.parquet_search_view import verify_atlas_parquet_search_view

AtlasParquetExplorerError = Atlas3ExplorerError

_ATLAS = "https://refspec.org/ns/atlas/v3#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DEFAULT_RESOURCE_LIMIT = 2_000
_DEFAULT_RELATION_LIMIT = 750


@dataclass(frozen=True)
class AtlasParquetExplorer:
    """One verified compact Parquet view opened for browsing."""

    root: Path
    manifest_digest: str
    manifest: Mapping[str, Any]
    tables: Mapping[CompactRecordRole, Path]

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        trusted_manifest_digest: str,
    ) -> AtlasParquetExplorer:
        resolved = Path(root).resolve(strict=True)
        digest = _digest(trusted_manifest_digest)
        manifest = verify_atlas_parquet_search_view(
            resolved,
            expected_manifest_digest=digest,
        )
        tables = {
            CompactRecordRole(member["role"]): resolved / member["path"]
            for member in manifest["members"]
        }
        return cls(resolved, digest, manifest, tables)

    @property
    def atlas_input(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self.manifest["input"]["atlas"])

    @property
    def counts(self) -> Mapping[str, int]:
        return cast(Mapping[str, int], self.manifest["counts"])


def _digest(value: str) -> str:
    normalized = value if value.startswith("sha256:") else f"sha256:{value}"
    suffix = normalized.removeprefix("sha256:")
    if len(suffix) != 64 or any(character not in "0123456789abcdef" for character in suffix):
        raise AtlasParquetExplorerError("Parquet explorer manifest digest is invalid")
    return normalized


def _short(value: str | None) -> str:
    if not value:
        return ""
    return value.rsplit("#", 1)[-1].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _sha256_text(value: bytes | None) -> str:
    return "" if value is None else f"sha256:{value.hex()}"


def _iri(value: str) -> str:
    return f"<{value}>"


def _literal(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _fact(predicate: str, value: str, *, iri: bool = True) -> list[str]:
    return [predicate, _iri(value) if iri else _literal(value), "asserted"]


def _iter_rows(path: Path, *, columns: Sequence[str] | None = None) -> Iterator[dict[str, Any]]:
    for batch in pq.ParquetFile(path).iter_batches(batch_size=50_000, columns=columns):
        yield from batch.to_pylist()


def _table_rows_for_values(
    path: Path,
    field: str,
    values: set[str],
    *,
    columns: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    if not values:
        return []
    result: list[dict[str, Any]] = []
    for batch in pq.ParquetFile(path).iter_batches(batch_size=50_000, columns=columns):
        mask = pc.is_in(
            batch.column(field),
            value_set=pa.array(sorted(values), type=batch.schema.field(field).type),
        )
        result.extend(batch.filter(mask).to_pylist())
    return result


def _first_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in pq.ParquetFile(path).iter_batches(batch_size=min(50_000, max(1, limit))):
        rows.extend(batch.to_pylist()[: limit - len(rows)])
        if len(rows) >= limit:
            break
    return rows


def _group_counts(path: Path, field: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in _iter_rows(path, columns=[field]):
        value = row[field]
        if value is not None:
            counts[value] += 1
    return counts


def open_atlas_explorer(
    root: str | Path,
    *,
    trusted_manifest_digest: str,
) -> AtlasParquetExplorer:
    """Open the compact Parquet data used by the normal explorer."""

    return AtlasParquetExplorer.open(root, trusted_manifest_digest=trusted_manifest_digest)


def atlas_explorer_facets(view: AtlasParquetExplorer) -> dict[str, Any]:
    """Return release and ring filters without loading RDF or browser shards."""

    member_counts = _group_counts(view.tables[CompactRecordRole.RESOURCE], "release")
    ring_counts = _group_counts(view.tables[CompactRecordRole.RESOURCE], "semantic_ring")
    releases = [
        {
            "count": member_counts[row["id"]],
            "id": row["id"],
            "identifier": row["identifier"],
            "ring": row["semantic_ring"],
        }
        for row in _iter_rows(view.tables[CompactRecordRole.RELEASE])
        if row["release_type"] == "AtlasRelease"
    ]
    return {
        "counts": {
            "resources": view.counts[CompactRecordRole.RESOURCE.value],
            "statements": view.counts[CompactRecordRole.STATEMENT.value],
        },
        "releases": sorted(releases, key=lambda row: (row["identifier"].casefold(), row["id"])),
        "rings": [{"count": count, "id": ring} for ring, count in sorted(ring_counts.items())],
    }


def search_atlas_parquet(
    view: AtlasParquetExplorer,
    query: str = "",
    *,
    release: str = "",
    ring: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Search useful resource text and apply release and ring filters."""

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise AtlasParquetExplorerError("search limit must be between 1 and 500")
    normalized = query.strip()
    candidate_ids: set[str] | None = None
    if normalized:
        candidate_ids = set()
        for batch in pq.ParquetFile(view.tables[CompactRecordRole.LABEL]).iter_batches(
            batch_size=50_000,
            columns=["resource", "value"],
        ):
            matches = batch.filter(pc.match_substring(batch.column("value"), normalized, ignore_case=True))
            candidate_ids.update(matches.column("resource").to_pylist())
        for batch in pq.ParquetFile(view.tables[CompactRecordRole.IDENTIFIER]).iter_batches(
            batch_size=50_000,
            columns=["identifier_value", "identifies"],
        ):
            matches = batch.filter(
                pc.match_substring(batch.column("identifier_value"), normalized, ignore_case=True)
            )
            candidate_ids.update(matches.column("identifies").to_pylist())
        for batch in pq.ParquetFile(view.tables[CompactRecordRole.RESOURCE]).iter_batches(
            batch_size=50_000,
            columns=["id"],
        ):
            matches = batch.filter(pc.match_substring(batch.column("id"), normalized, ignore_case=True))
            candidate_ids.update(matches.column("id").to_pylist())

    rows: list[dict[str, Any]] = []
    for row in _iter_rows(
        view.tables[CompactRecordRole.RESOURCE],
        columns=["id", "release", "semantic_ring", "resource_profile", "definition", "notations"],
    ):
        if candidate_ids is not None and row["id"] not in candidate_ids:
            continue
        if release and row["release"] != release:
            continue
        if ring and row["semantic_ring"] != ring:
            continue
        rows.append(row)
        if candidate_ids is None and len(rows) >= limit * 4:
            break
    labels = _labels_for(view, {row["id"] for row in rows})
    results = [
        {
            "definition": row["definition"],
            "id": row["id"],
            "label": (labels.get(row["id"]) or [{"value": _short(row["id"])}])[0]["value"],
            "notations": row["notations"] or [],
            "profile": row["resource_profile"],
            "release": row["release"],
            "ring": row["semantic_ring"],
        }
        for row in rows
    ]
    query_key = normalized.casefold()

    def result_order(row: Mapping[str, Any]) -> tuple[int, int, str, str]:
        label = cast(str, row["label"])
        label_key = label.casefold()
        if not query_key or label_key == query_key:
            rank = 0
        elif label_key.startswith(query_key):
            rank = 1
        elif any(word.startswith(query_key) for word in label_key.split()):
            rank = 2
        elif query_key in label_key:
            rank = 3
        else:
            rank = 4
        return rank, len(label), label_key, cast(str, row["id"])

    results.sort(key=result_order)
    return results[:limit]


def atlas_parquet_resource(view: AtlasParquetExplorer, resource_id: str) -> dict[str, Any]:
    """Return one resource and its directly useful relations and evidence."""

    resources = _table_rows_for_values(view.tables[CompactRecordRole.RESOURCE], "id", {resource_id})
    if len(resources) != 1:
        raise AtlasParquetExplorerError("resource is not present in the Parquet view")
    resource = resources[0]
    labels = _labels_for(view, {resource_id}).get(resource_id, [])
    identifiers = _table_rows_for_values(
        view.tables[CompactRecordRole.IDENTIFIER],
        "identifies",
        {resource_id},
    )
    relations: list[dict[str, Any]] = []
    for batch in pq.ParquetFile(view.tables[CompactRecordRole.STATEMENT]).iter_batches(batch_size=50_000):
        matches = batch.filter(
            pc.or_(pc.equal(batch.column("subject"), resource_id), pc.equal(batch.column("object"), resource_id))
        )
        relations.extend(matches.to_pylist())
    statement_ids = {row["id"] for row in relations}
    evidence = _table_rows_for_values(
        view.tables[CompactRecordRole.EVIDENCE_BINDING],
        "statement",
        statement_ids,
    )
    evidence_counts = Counter(row["statement"] for row in evidence)
    for row in relations:
        row["evidence_count"] = evidence_counts[row["id"]]
    return {
        "definition": resource["definition"],
        "id": resource_id,
        "identifiers": [
            {"scheme": row["identifier_scheme"], "value": row["identifier_value"]}
            for row in identifiers
        ],
        "labels": labels,
        "notations": resource["notations"] or [],
        "notes": resource["notes"] or [],
        "profile": resource["resource_profile"],
        "relations": relations,
        "release": resource["release"],
        "ring": resource["semantic_ring"],
        "scheme": resource["scheme"],
        "sourceRecord": resource["source_record"],
        "status": resource["record_status"],
    }


_PARQUET_EXPLORER_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RefSpec Atlas explorer</title><style>
:root{color-scheme:dark;font-family:ui-sans-serif,system-ui;background:#09100e;color:#edf4f0}*{box-sizing:border-box}
body{margin:0}header{padding:18px 24px;border-bottom:1px solid #2b3c36}h1{margin:0;font-size:22px}header p{margin:5px 0 0;color:#9caaa4}
main{display:grid;grid-template-columns:minmax(340px,42%) 1fr;min-height:calc(100vh - 82px)}aside,article{padding:20px;overflow:auto}aside{border-right:1px solid #2b3c36}
.filters{display:grid;grid-template-columns:1fr 170px 130px;gap:8px;position:sticky;top:0;background:#09100e;padding-bottom:14px}input,select{width:100%;padding:10px;border:1px solid #3b4f48;border-radius:5px;background:#101a17;color:inherit}
button.result{display:block;width:100%;padding:12px 0;text-align:left;border:0;border-top:1px solid #263530;background:transparent;color:inherit;cursor:pointer}.result b{display:block}.result small,.muted{color:#9caaa4}
h2{margin-top:0}.tag{display:inline-block;margin:0 5px 5px 0;padding:3px 7px;border-radius:10px;background:#1b2b26;color:#99ddd0;font-size:12px}.relation{padding:10px 0;border-top:1px solid #263530}.iri{overflow-wrap:anywhere;font-family:ui-monospace,monospace;font-size:12px;color:#9caaa4}
@media(max-width:800px){main{display:block}.filters{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid #2b3c36}}
</style></head><body><header><h1>RefSpec Atlas explorer</h1><p id="counts">Loading Parquet data…</p></header><main><aside><div class="filters"><input id="q" type="search" placeholder="Search labels, identifiers, or IRIs"><select id="release"><option value="">All releases</option></select><select id="ring"><option value="">All rings</option></select></div><div id="results"></div></aside><article id="detail"><p class="muted">Choose a resource to see its labels, identifiers, and relationships.</p></article></main><script>
const q=document.querySelector('#q'),release=document.querySelector('#release'),ring=document.querySelector('#ring'),results=document.querySelector('#results'),detail=document.querySelector('#detail');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let timer;
async function get(path){const r=await fetch(path);if(!r.ok)throw new Error(await r.text());return r.json()}
async function search(){const p=new URLSearchParams({q:q.value,release:release.value,ring:ring.value,limit:'100'});const rows=await get('/api/search?'+p);results.innerHTML=rows.map((r,i)=>`<button class="result" data-i="${i}"><b>${esc(r.label)}</b><small>${esc(r.ring)} · ${esc(r.profile)}</small></button>`).join('')||'<p class="muted">No matches.</p>';results.querySelectorAll('button').forEach(b=>b.onclick=()=>show(rows[Number(b.dataset.i)].id))}
async function show(id){const r=await get('/api/resource?id='+encodeURIComponent(id)),label=r.labels[0]?.value||r.id;detail.innerHTML=`<h2>${esc(label)}</h2><p class="iri">${esc(r.id)}</p><p>${esc(r.definition||'')}</p><p>${r.labels.map(x=>`<span class="tag">${esc(x.role)}: ${esc(x.value)}</span>`).join('')}</p><p>${r.identifiers.map(x=>`<span class="tag">${esc(x.value)}</span>`).join('')}</p><h3>${r.relations.length} relationships</h3>${r.relations.map(x=>`<div class="relation"><b>${esc(x.subject===r.id?'outgoing':'incoming')} · ${esc(x.predicate.split(/[#/]/).pop())}</b><div class="iri">${esc(x.subject)} → ${esc(x.object)}</div><small>${esc(x.statement_type)} · ${x.evidence_count} evidence record(s)</small></div>`).join('')}`}
q.oninput=()=>{clearTimeout(timer);timer=setTimeout(search,180)};release.onchange=ring.onchange=search;
(async()=>{const f=await get('/api/facets');document.querySelector('#counts').textContent=`${f.counts.resources.toLocaleString()} resources · ${f.counts.statements.toLocaleString()} relationships`;f.releases.forEach(x=>release.add(new Option(`${x.identifier} (${x.count.toLocaleString()})`,x.id)));f.rings.forEach(x=>ring.add(new Option(`${x.id} (${x.count.toLocaleString()})`,x.id)));await search()})().catch(e=>{results.textContent=e.message});
</script></body></html>"""


def render_atlas_parquet_explorer() -> str:
    """Return the small browser application served beside the Parquet API."""

    return _PARQUET_EXPLORER_HTML


def _resource_record(row: Mapping[str, Any]) -> dict[str, Any]:
    facts = [
        _fact(f"{_RDF}type", f"{_ATLAS}AtlasResource"),
        _fact(f"{_ATLAS}inRelease", row["release"]),
        _fact(f"{_ATLAS}inScheme", row["scheme"]),
        _fact(f"{_ATLAS}semanticRing", f"{_ATLAS}{row['semantic_ring']}"),
        _fact(f"{_ATLAS}resourceProfile", f"{_ATLAS}{row['resource_profile']}"),
        _fact(f"{_ATLAS}sourceRecord", row["source_record"]),
    ]
    if row.get("definition"):
        facts.append(_fact(f"{_ATLAS}definition", row["definition"], iri=False))
    facts.extend(_fact(f"{_ATLAS}note", value, iri=False) for value in row.get("notes") or ())
    facts.extend(_fact(f"{_ATLAS}notation", value, iri=False) for value in row.get("notations") or ())
    if row.get("record_status"):
        facts.append(_fact(f"{_ATLAS}recordStatus", f"{_ATLAS}{row['record_status']}"))
    return {"facts": facts, "id": row["id"]}


def _statement_record(row: Mapping[str, Any]) -> dict[str, Any]:
    facts = [
        _fact(f"{_RDF}type", f"{_ATLAS}RelationAssertion"),
        _fact(f"{_RDF}type", f"{_ATLAS}{row['statement_type']}"),
        _fact(f"{_RDF}subject", row["subject"]),
        _fact(f"{_RDF}predicate", row["predicate"]),
        _fact(f"{_RDF}object", row["object"]),
        _fact(f"{_ATLAS}sourceRelease", row["source_release"]),
        _fact(f"{_ATLAS}targetRelease", row["target_release"]),
        _fact(f"{_ATLAS}policy", row["policy"]),
        _fact(f"{_ATLAS}assertedAt", row["asserted_at"], iri=False),
        _fact(f"{_ATLAS}assertionStatus", f"{_ATLAS}{row['assertion_status']}"),
    ]
    if row.get("semantic_ring"):
        facts.append(_fact(f"{_ATLAS}semanticRing", f"{_ATLAS}{row['semantic_ring']}"))
    else:
        facts.extend(
            (
                _fact(f"{_ATLAS}sourceRing", f"{_ATLAS}{row['source_ring']}"),
                _fact(f"{_ATLAS}targetRing", f"{_ATLAS}{row['target_ring']}"),
            )
        )
    if row.get("supersedes"):
        facts.append(_fact(f"{_ATLAS}supersedes", row["supersedes"]))
    return {"facts": facts, "id": row["id"]}


def _evidence_record(row: Mapping[str, Any]) -> dict[str, Any]:
    record_id = f"urn:ref:atlas-evidence:{row['evidence_id'].hex()}"
    facts = [
        _fact(f"{_RDF}type", f"{_ATLAS}EvidenceBinding"),
        _fact(f"{_ATLAS}bindsAssertion", row["statement"]),
        _fact(f"{_ATLAS}evidenceSourceRecord", row["source_record"]),
        _fact(f"{_ATLAS}evidenceSourceDigest", _sha256_text(row["evidence_source_digest"]), iri=False),
        _fact(f"{_ATLAS}reviewedBy", row["reviewed_by"]),
        _fact(f"{_ATLAS}reviewMethod", row["review_method"]),
        _fact(f"{_ATLAS}decisionStatus", row["decision_status"]),
        _fact(f"{_ATLAS}decidedAt", row["decided_at"], iri=False),
    ]
    if row.get("confidence") is not None:
        facts.append(_fact(f"{_ATLAS}confidence", row["confidence"], iri=False))
    return {"facts": facts, "id": record_id}


def _source_record(row: Mapping[str, Any]) -> dict[str, Any]:
    facts = [
        _fact(f"{_RDF}type", f"{_ATLAS}SourceRecord"),
        _fact(f"{_ATLAS}inSourceRelease", row["source_release"]),
        _fact(f"{_ATLAS}sourceDigest", _sha256_text(row["source_digest"]), iri=False),
        _fact(f"{_ATLAS}sourceLocator", row["source_locator"]),
    ]
    if row.get("represents_resource"):
        facts.append(_fact(f"{_ATLAS}representsResource", row["represents_resource"]))
    return {"facts": facts, "id": row["id"]}


def _release_record(row: Mapping[str, Any]) -> dict[str, Any]:
    facts = [
        _fact(f"{_RDF}type", f"{_ATLAS}{row['release_type']}"),
        _fact(f"{_ATLAS}identifier", row["identifier"], iri=False),
        _fact(f"{_ATLAS}issued", row["issued"], iri=False),
    ]
    for field, predicate in (
        ("source_locator", "sourceLocator"),
        ("scheme", "resourceScheme"),
    ):
        if row.get(field):
            facts.append(_fact(f"{_ATLAS}{predicate}", row[field]))
    if row.get("source_digest"):
        facts.append(_fact(f"{_ATLAS}sourceDigest", _sha256_text(row["source_digest"]), iri=False))
    for field, predicate in (
        ("resource_profile", "resourceProfile"),
        ("semantic_ring", "semanticRing"),
        ("membership_mode", "membershipMode"),
    ):
        if row.get(field):
            facts.append(_fact(f"{_ATLAS}{predicate}", f"{_ATLAS}{row[field]}"))
    return {"facts": facts, "id": row["id"]}


def _identifier_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "facts": [
            _fact(f"{_RDF}type", f"{_ATLAS}Identifier"),
            _fact(f"{_ATLAS}identifierValue", row["identifier_value"], iri=False),
            _fact(f"{_ATLAS}identifierScheme", row["identifier_scheme"]),
            _fact(f"{_ATLAS}identifies", row["identifies"]),
            _fact(f"{_ATLAS}sourceRecord", row["source_record"]),
        ],
        "id": row["id"],
    }


def _spool_parquet_records(
    view: AtlasParquetExplorer,
    raw: _JsonlSpool,
    augment: _JsonlSpool,
    summaries: _JsonlSpool,
) -> None:
    release_rings = {
        row["id"]: row["semantic_ring"]
        for row in _iter_rows(view.tables[CompactRecordRole.RELEASE], columns=["id", "semantic_ring"])
        if row["semantic_ring"]
    }
    for row in _iter_rows(view.tables[CompactRecordRole.RESOURCE]):
        record = _resource_record(row)
        raw.append(_explorer_hash_prefix(row["id"], _EXPLORER_RECORD_PREFIX_LENGTH), record)
    for row in _iter_rows(view.tables[CompactRecordRole.LABEL]):
        if row["language"].casefold() != "en":
            continue
        summaries.append(
            _explorer_hash_prefix(row["resource"], _EXPLORER_RECORD_PREFIX_LENGTH),
            {
                "id": row["resource"],
                "label": {
                    "language": row["language"],
                    "role": row["label_role"],
                    "value": row["value"],
                },
                "release": row["release"],
                "ring": release_rings[row["release"]],
            },
        )
    for row in _iter_rows(view.tables[CompactRecordRole.STATEMENT]):
        raw.append(
            _explorer_hash_prefix(row["id"], _EXPLORER_RECORD_PREFIX_LENGTH),
            _statement_record(row),
        )
        for endpoint in {row["subject"], row["object"]}:
            augment.append(
                _explorer_hash_prefix(endpoint, _EXPLORER_RECORD_PREFIX_LENGTH),
                {"id": endpoint, "relations": [row["id"]]},
            )
    for row in _iter_rows(view.tables[CompactRecordRole.EVIDENCE_BINDING]):
        record = _evidence_record(row)
        raw.append(_explorer_hash_prefix(record["id"], _EXPLORER_RECORD_PREFIX_LENGTH), record)
        augment.append(
            _explorer_hash_prefix(row["statement"], _EXPLORER_RECORD_PREFIX_LENGTH),
            {"evidenceBindings": [record["id"]], "id": row["statement"]},
        )
    for row in _iter_rows(view.tables[CompactRecordRole.SOURCE_RECORD]):
        record = _source_record(row)
        raw.append(_explorer_hash_prefix(row["id"], _EXPLORER_RECORD_PREFIX_LENGTH), record)
    for row in _iter_rows(view.tables[CompactRecordRole.RELEASE]):
        record = _release_record(row)
        raw.append(_explorer_hash_prefix(row["id"], _EXPLORER_RECORD_PREFIX_LENGTH), record)
    for row in _iter_rows(view.tables[CompactRecordRole.IDENTIFIER]):
        record = _identifier_record(row)
        raw.append(_explorer_hash_prefix(row["id"], _EXPLORER_RECORD_PREFIX_LENGTH), record)
        augment.append(
            _explorer_hash_prefix(row["identifies"], _EXPLORER_RECORD_PREFIX_LENGTH),
            {"id": row["identifies"], "identifiers": [row["id"]]},
        )
    raw.close()
    augment.close()
    summaries.close()


def build_atlas_explorer_static_shards(
    view: AtlasParquetExplorer,
    target: Path,
    *,
    url_prefix: str,
) -> dict[str, Any]:
    """Build the browser's searchable JSON files from Parquet."""

    if not isinstance(view, AtlasParquetExplorer):
        raise AtlasParquetExplorerError("Atlas explorer shards require an opened Parquet view")
    target = Path(target).resolve()
    normalized_prefix = PurePosixPath(url_prefix.rstrip("/"))
    if normalized_prefix.is_absolute() or not normalized_prefix.parts or any(
        part in {"", ".", ".."} for part in normalized_prefix.parts
    ):
        raise AtlasParquetExplorerError("Atlas explorer shard URL prefix must be safe and relative")
    url_prefix = normalized_prefix.as_posix() + "/"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{target.name}.building-") as temporary_name:
        workspace = Path(temporary_name)
        raw = _JsonlSpool(workspace / "raw")
        augment = _JsonlSpool(workspace / "augment")
        summaries = _JsonlSpool(workspace / "summaries")
        catalog = _JsonlSpool(workspace / "catalog")
        search = _JsonlSpool(workspace / "search")
        published = workspace / "published"
        published.mkdir()
        _spool_parquet_records(view, raw, augment, summaries)
        resource_count = _finalize_explorer_resource_summaries(
            summaries,
            augment,
            catalog,
            search,
        )
        record_shards, record_count = _finalize_explorer_record_shards(
            raw.root,
            augment,
            published,
            view.manifest_digest,
            url_prefix,
        )
        catalog_shards = _finalize_explorer_page_shards(
            catalog,
            published,
            "catalog",
            view.manifest_digest,
            url_prefix,
        )
        search_shards = _finalize_explorer_page_shards(
            search,
            published,
            "search",
            view.manifest_digest,
            url_prefix,
        )
        if resource_count != view.counts[CompactRecordRole.RESOURCE.value]:
            raise AtlasParquetExplorerError("Parquet explorer labels do not cover every resource")
        asserted_digest = view.atlas_input["assertedInventoryDigest"]
        index_payload = {
            "assertedInventoryDigest": asserted_digest,
            "builderRecipe": ATLAS_PARQUET_EXPLORER_SHARD_BUILDER_RECIPE,
            "catalog": {"shards": catalog_shards},
            "counts": {"records": record_count, "resources": resource_count},
            "manifestDigest": view.manifest_digest,
            "records": {"prefixLength": _EXPLORER_RECORD_PREFIX_LENGTH, "shards": record_shards},
            "search": {"keyLength": 2, "shards": search_shards},
            "schema": _EXPLORER_SHARD_SCHEMA,
            "type": _EXPLORER_SHARD_INDEX_TYPE,
            "version": _EXPLORER_SHARD_VERSION,
        }
        index_ref = _write_explorer_shard(published, "index", index_payload, url_prefix=url_prefix)
        generated = {child.name: child.read_bytes() for child in sorted(published.iterdir())}
        existing = _safe_existing_shard_directory(target)
        if target.exists():
            if existing != generated:
                raise AtlasParquetExplorerError("immutable explorer shard directory differs")
        else:
            published.replace(target)
        return {
            "assertedInventoryDigest": asserted_digest,
            "builderRecipe": ATLAS_PARQUET_EXPLORER_SHARD_BUILDER_RECIPE,
            "counts": dict(index_payload["counts"]),
            "index": index_ref,
            "manifestDigest": view.manifest_digest,
            "schema": _EXPLORER_SHARD_SCHEMA,
            "type": _EXPLORER_SHARD_BUNDLE_TYPE,
            "version": _EXPLORER_SHARD_VERSION,
        }


def _labels_for(view: AtlasParquetExplorer, resource_ids: set[str]) -> dict[str, list[dict[str, str]]]:
    rows = _table_rows_for_values(
        view.tables[CompactRecordRole.LABEL],
        "resource",
        resource_ids,
    )
    labels: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["language"].casefold() == "en":
            labels[row["resource"]].append(
                {"language": row["language"], "role": row["label_role"], "value": row["value"]}
            )
    order = {"preferred": 0, "alternate": 1, "hidden": 2}
    for values in labels.values():
        values.sort(key=lambda row: (order.get(row["role"], 99), row["value"].casefold(), row["value"]))
    return labels


def _coverage(view: AtlasParquetExplorer) -> tuple[dict[str, Any], dict[str, int]]:
    resource_rings = _group_counts(view.tables[CompactRecordRole.RESOURCE], "semantic_ring")
    resource_releases = _group_counts(view.tables[CompactRecordRole.RESOURCE], "release")
    source_releases = _group_counts(view.tables[CompactRecordRole.SOURCE_RECORD], "source_release")
    relation_kinds: Counter[str] = Counter()
    relation_rings: Counter[str] = Counter()
    cross_pairs: Counter[tuple[str, str]] = Counter()
    current = 0
    for row in _iter_rows(
        view.tables[CompactRecordRole.STATEMENT],
        columns=["statement_type", "assertion_status", "semantic_ring", "source_ring", "target_ring"],
    ):
        relation_kinds[
            {
                "MappingAssertion": "mapping",
                "NativeRelationAssertion": "native",
                "SourceAssignment": "sourceAssignment",
                "CrossRingRelationAssertion": "crossRing",
            }.get(row["statement_type"], row["statement_type"])
        ] += 1
        if row["assertion_status"] == "current":
            current += 1
        if row["semantic_ring"]:
            relation_rings[row["semantic_ring"]] += 1
        else:
            relation_rings[row["source_ring"]] += 1
            relation_rings[row["target_ring"]] += 1
            cross_pairs[(row["source_ring"], row["target_ring"])] += 1
    return (
        {
            "assertedRelationsByKind": dict(sorted(relation_kinds.items())),
            "assertedRelationsByRing": dict(sorted(relation_rings.items())),
            "crossRingRelationsByPair": [
                {"count": count, "sourceRing": source, "targetRing": target}
                for (source, target), count in sorted(cross_pairs.items())
            ],
            "resourcesByRelease": [
                {"count": count, "release": release} for release, count in sorted(resource_releases.items())
            ],
            "resourcesByRing": dict(sorted(resource_rings.items())),
            "sourceRecordsByRelease": [
                {"sourceRecords": count, "sourceRelease": release}
                for release, count in sorted(source_releases.items())
            ],
        },
        {"current": current},
    )


def build_atlas_explorer_model(
    view: AtlasParquetExplorer,
    *,
    title: str = "RefSpec Atlas explorer",
    full_corpus: Mapping[str, Any] | None = None,
    max_resources: int = _DEFAULT_RESOURCE_LIMIT,
    max_assertions: int = _DEFAULT_RELATION_LIMIT,
) -> dict[str, Any]:
    """Build the small initial browser model; full search stays in static shards."""

    if not isinstance(view, AtlasParquetExplorer):
        raise AtlasParquetExplorerError("Atlas explorer requires an opened Parquet view")
    statement_rows = _first_rows(view.tables[CompactRecordRole.STATEMENT], max_assertions)
    endpoint_ids = {row[field] for row in statement_rows for field in ("subject", "object")}
    resource_rows = _table_rows_for_values(view.tables[CompactRecordRole.RESOURCE], "id", endpoint_ids)
    selected = {row["id"]: row for row in resource_rows}
    if len(selected) < max_resources:
        for row in _first_rows(view.tables[CompactRecordRole.RESOURCE], max_resources):
            selected.setdefault(row["id"], row)
            if len(selected) >= max_resources:
                break
    resource_rows = sorted(selected.values(), key=lambda row: row["id"])
    resource_ids = set(selected)
    labels = _labels_for(view, resource_ids | endpoint_ids)
    display = {
        resource_id: (labels.get(resource_id) or [{"value": _short(resource_id)}])[0]["value"]
        for resource_id in resource_ids | endpoint_ids
    }
    identifier_rows = _table_rows_for_values(
        view.tables[CompactRecordRole.IDENTIFIER],
        "identifies",
        resource_ids,
    )
    identifiers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in identifier_rows:
        identifiers[row["identifies"]].append(
            {
                "id": row["id"],
                "identifies": row["identifies"],
                "scheme": row["identifier_scheme"],
                "schemeLabel": _short(row["identifier_scheme"]),
                "sourceRecord": row["source_record"],
                "sourceRecordCount": 1,
                "value": row["identifier_value"],
            }
        )
    statement_ids = {row["id"] for row in statement_rows}
    evidence_rows = _table_rows_for_values(
        view.tables[CompactRecordRole.EVIDENCE_BINDING],
        "statement",
        statement_ids,
    )
    evidence_by_statement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_record_ids = {row["source_record"] for row in resource_rows} | {
        row["source_record"] for row in evidence_rows
    }
    for row in evidence_rows:
        evidence_by_statement[row["statement"]].append(
            {
                "confidence": row["confidence"],
                "decidedAt": row["decided_at"],
                "decisionStatus": _short(row["decision_status"]),
                "id": f"urn:ref:atlas-evidence:{row['evidence_id'].hex()}",
                "reviewMethod": _short(row["review_method"]),
                "reviewedBy": row["reviewed_by"],
                "sourceDigest": _sha256_text(row["evidence_source_digest"]),
                "sourceRecord": row["source_record"],
            }
        )
    source_rows = _table_rows_for_values(
        view.tables[CompactRecordRole.SOURCE_RECORD],
        "id",
        source_record_ids,
    )
    releases = list(_iter_rows(view.tables[CompactRecordRole.RELEASE]))
    member_counts = _group_counts(view.tables[CompactRecordRole.RESOURCE], "release")
    coverage, relation_totals = _coverage(view)

    relation_kind = {
        "MappingAssertion": "mapping",
        "NativeRelationAssertion": "native",
        "SourceAssignment": "sourceAssignment",
        "CrossRingRelationAssertion": "crossRing",
    }
    relations = []
    for row in statement_rows:
        relation = {
            "assertedAt": row["asserted_at"],
            "authoritative": row["assertion_status"] == "current",
            "authority": (
                "authoritative" if row["assertion_status"] == "current" else "historicalEditorialRecord"
            ),
            "evidence": evidence_by_statement[row["id"]],
            "id": row["id"],
            "kind": relation_kind.get(row["statement_type"], row["statement_type"]),
            "object": row["object"],
            "objectLabel": display.get(row["object"], _short(row["object"])),
            "predicate": row["predicate"],
            "predicateLabel": _short(row["predicate"]),
            "sourceRelease": row["source_release"],
            "status": row["assertion_status"],
            "subject": row["subject"],
            "subjectLabel": display.get(row["subject"], _short(row["subject"])),
            "targetRelease": row["target_release"],
        }
        if row["semantic_ring"]:
            relation.update(semanticRing=row["semantic_ring"], semanticRings=[row["semantic_ring"]])
        else:
            relation.update(
                sourceRing=row["source_ring"],
                targetRing=row["target_ring"],
                semanticRings=[row["source_ring"], row["target_ring"]],
            )
        relations.append(relation)

    atlas_releases = [row for row in releases if row["release_type"] == "AtlasRelease"]
    source_releases = [row for row in releases if row["release_type"] == "SourceRelease"]
    counts = view.counts
    full_counts = {
        "crossRingRelationAssertions": coverage["assertedRelationsByKind"].get("crossRing", 0),
        "derivedRelations": 0,
        "identifiers": counts[CompactRecordRole.IDENTIFIER.value],
        "labels": counts[CompactRecordRole.LABEL.value],
        "mappingAssertions": coverage["assertedRelationsByKind"].get("mapping", 0),
        "nativeRelationAssertions": coverage["assertedRelationsByKind"].get("native", 0),
        "projectedRelations": 0,
        "relationAssertions": counts[CompactRecordRole.STATEMENT.value],
        "releases": len(atlas_releases),
        "resources": counts[CompactRecordRole.RESOURCE.value],
        "sourceAssignments": coverage["assertedRelationsByKind"].get("sourceAssignment", 0),
        "sourceRecords": counts[CompactRecordRole.SOURCE_RECORD.value],
    }
    resource_index = [
        {
            "displayLabel": display[row["id"]],
            "id": row["id"],
            "release": row["release"],
            "semanticRing": row["semantic_ring"],
        }
        for row in resource_rows
    ]
    resources = [
        {
            "definitions": ([{"value": row["definition"]}] if row["definition"] else []),
            "displayLabel": display[row["id"]],
            "displayLabelRole": (labels.get(row["id"]) or [{"role": "generated"}])[0]["role"],
            "id": row["id"],
            "identifiers": identifiers[row["id"]],
            "labels": labels.get(row["id"], []),
            "notations": row["notations"] or [],
            "notes": [{"value": value} for value in row["notes"] or []],
            "release": row["release"],
            "resourceProfile": row["resource_profile"],
            "resourceType": "AtlasResource",
            "scheme": row["scheme"],
            "semanticRing": row["semantic_ring"],
            "sourceRecords": [row["source_record"]],
        }
        for row in resource_rows
    ]
    model: dict[str, Any] = {
        "acceptance": {"receiptVerified": True, "verdict": "verifiedParquetView"},
        "assertedRelations": relations,
        "atlasReleases": [
            {
                "id": row["id"],
                "identifier": row["identifier"],
                "issued": row["issued"],
                "kind": "atlas",
                "memberCount": member_counts[row["id"]],
                "resourceProfile": row["resource_profile"],
                "scheme": row["scheme"],
                "semanticRing": row["semantic_ring"],
            }
            for row in atlas_releases
        ],
        "authority": {
            "asserted": {
                "graph": "urn:ref:atlas:graph:v3:asserted",
                "meaning": "Published Atlas statements with their evidence.",
                "status": "authoritative",
            },
            "projection": {
                "graph": "urn:ref:atlas:graph:v3:projection",
                "meaning": "No projection rows are needed by this explorer.",
                "status": "reproducibleConvenienceView",
            },
            "derived": {
                "graph": "urn:ref:atlas:graph:v3:derived",
                "meaning": "No derived rows are included in this view.",
                "status": "nonAuthoritative",
            },
        },
        "coverage": coverage,
        "derivedRelations": [],
        "distribution": {
            "assertedInventoryDigest": view.atlas_input["assertedInventoryDigest"],
            "counts": full_counts,
            "id": view.atlas_input["distributionId"],
            "manifestDigest": view.manifest_digest,
            "trustedManifestDigestChecked": True,
        },
        "projectedRelations": [],
        "resourceIndex": resource_index,
        "resources": resources,
        "schemaVersion": ATLAS_V3_EXPLORER_SCHEMA_VERSION,
        "sourceAccounting": {},
        "sourceRecords": [
            {
                "id": row["id"],
                "nativePayload": {},
                "nativePayloadMetadataOnly": True,
                "representsResources": ([row["represents_resource"]] if row["represents_resource"] else []),
                "sourceDigest": _sha256_text(row["source_digest"]),
                "sourceLocator": row["source_locator"],
                "sourceRelease": row["source_release"],
            }
            for row in source_rows
        ],
        "sourceReleases": [
            {
                "id": row["id"],
                "identifier": row["identifier"],
                "issued": row["issued"],
                "kind": "source",
                "sourceDigest": _sha256_text(row["source_digest"]),
                "sourceLocator": row["source_locator"],
            }
            for row in source_releases
        ],
        "summary": {
            "availableAssertedRelations": full_counts["relationAssertions"],
            "availableDerivedRelations": 0,
            "availableIdentifiers": full_counts["identifiers"],
            "availableProjectedRelations": 0,
            "availableResources": full_counts["resources"],
            "availableSourceRecords": full_counts["sourceRecords"],
            "currentAuthoritativeRelations": relation_totals["current"],
            "indexedAssertedRelations": len(relations),
            "indexedDerivedRelations": 0,
            "indexedIdentifiers": len(identifier_rows),
            "indexedProjectedRelations": 0,
            "indexedResources": len(resource_index),
            "indexedSourceRecords": len(source_rows),
            "provenanceClosureAssertedRelations": 0,
            "shownAssertedRelations": len(relations),
            "shownDerivedRelations": 0,
            "shownIdentifiers": len(identifier_rows),
            "shownProjectedRelations": 0,
            "shownResources": len(resources),
            "shownSourceRecords": len(source_rows),
            "truncated": len(resources) < full_counts["resources"],
        },
        "title": title,
        "type": ATLAS_V3_EXPLORER_TYPE,
        "visualIndex": {
            "algorithm": "parquet-first-rows-v1",
            "complete": len(resources) == full_counts["resources"],
            "fullDatasetRdfLibParsed": False,
            "limits": {"resources": max_resources, "topicAssertions": max_assertions},
            "materialized": {"assertedRelations": len(relations), "resources": len(resources)},
            "sourceRecordPayloadMode": "metadataOnly",
        },
    }
    if full_corpus is not None:
        model["fullCorpus"] = dict(full_corpus)
    return model


# Compatibility names for callers that only render an already-built model.
build_atlas_v3_explorer_model = build_atlas_explorer_model
build_atlas_v3_explorer_static_shards = build_atlas_explorer_static_shards

__all__ = [
    "ATLAS_PARQUET_EXPLORER_SHARD_BUILDER_RECIPE",
    "EXPLORER_FILTER_SEMANTICS",
    "EXPLORER_SCHEMA_VERSION",
    "EXPLORER_TYPE",
    "PLANNING_FILTER_SEMANTICS",
    "AtlasExplorerError",
    "AtlasParquetExplorer",
    "AtlasParquetExplorerError",
    "build_atlas_explorer_model",
    "build_atlas_explorer_static_shards",
    "open_atlas_explorer",
    "render_atlas_explorer",
    "render_atlas_v3_explorer",
]

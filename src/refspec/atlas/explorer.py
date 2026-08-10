"""Build the Atlas browser directly from the compact Parquet search view."""

from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.duckdb_view import AtlasDuckDBView, AtlasDuckDBViewError
from refspec.atlas.explorer_frontend import render_atlas_explorer_frontend
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

AtlasParquetExplorer = AtlasDuckDBView
AtlasParquetExplorerError = AtlasDuckDBViewError

_ATLAS = "https://refspec.org/ns/atlas/v3#"
_RKAF = "https://rulespec.org/ns/v1#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DEFAULT_RESOURCE_LIMIT = 2_000
_DEFAULT_RELATION_LIMIT = 750

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
    """Return release and ring filters through the reusable query view."""

    return view.facets()


def search_atlas_parquet(
    view: AtlasParquetExplorer,
    query: str = "",
    *,
    release: str = "",
    releases: Sequence[str] = (),
    ring: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search useful resource text with DuckDB BM25 and stable paging."""

    return view.search(
        query,
        release=release,
        releases=releases,
        ring=ring,
        limit=limit,
        offset=offset,
    )


def atlas_parquet_resource(view: AtlasParquetExplorer, resource_id: str) -> dict[str, Any]:
    """Return one resource neighborhood through the reusable query view."""

    return view.resource(resource_id)




def render_atlas_parquet_explorer() -> str:
    """Return the storage-neutral browser served beside the Parquet API."""

    return render_atlas_explorer_frontend()


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
    if row.get("supersedes_assertion"):
        facts.append(_fact(f"{_RKAF}supersedesAssertion", row["supersedes_assertion"]))
    return {"facts": facts, "id": row["id"]}


def _evidence_record(row: Mapping[str, Any]) -> dict[str, Any]:
    record_id = f"urn:ref:atlas-evidence:{row['evidence_id'].hex()}"
    facts = [
        _fact(f"{_RDF}type", f"{_ATLAS}EvidenceBinding"),
        _fact(f"{_ATLAS}bindsAssertion", row["statement"]),
        _fact(f"{_ATLAS}evidenceSourceRecord", row["source_record"]),
        _fact(f"{_ATLAS}evidenceSourceDigest", _sha256_text(row["evidence_source_digest"]), iri=False),
        _fact(f"{_RKAF}attestor", row["attestor"]),
        _fact(f"{_RKAF}evidenceRole", row["evidence_role"]),
        _fact(f"{_RKAF}decision", row["decision"]),
        _fact(f"{_RKAF}attestedAt", row["attested_at"], iri=False),
    ]
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


def _lifecycle_status_ids(view: AtlasParquetExplorer) -> tuple[set[str], set[str]]:
    """Return (supersededIds, rescindedIds): assertions named by an edge.

    An assertion carries no status field. A successor names its predecessor
    via supersedes_assertion (one predecessor per successor, enforced by the
    dataset validator), and a rkaf:rescission lifecycle event names the one
    assertion it applies to. The validator rejects an assertion that is both,
    so the two sets are disjoint.
    """

    superseded_ids = {
        row["supersedes_assertion"]
        for row in _iter_rows(
            view.tables[CompactRecordRole.STATEMENT],
            columns=["supersedes_assertion"],
        )
        if row["supersedes_assertion"]
    }
    rescinded_ids = {
        row["applies_to"]
        for row in _iter_rows(
            view.tables[CompactRecordRole.LIFECYCLE_EVENT],
            columns=["applies_to", "lifecycle_event_kind"],
        )
        if row["lifecycle_event_kind"] == f"{_RKAF}rescission"
    }
    return superseded_ids, rescinded_ids


def _coverage(view: AtlasParquetExplorer) -> tuple[dict[str, Any], dict[str, int]]:
    resource_rings = _group_counts(view.tables[CompactRecordRole.RESOURCE], "semantic_ring")
    resource_releases = _group_counts(view.tables[CompactRecordRole.RESOURCE], "release")
    source_releases = _group_counts(view.tables[CompactRecordRole.SOURCE_RECORD], "source_release")
    relation_kinds: Counter[str] = Counter()
    relation_rings: Counter[str] = Counter()
    cross_pairs: Counter[tuple[str, str]] = Counter()
    superseded_ids, rescinded_ids = _lifecycle_status_ids(view)
    total_relations = 0
    current = 0
    for row in _iter_rows(
        view.tables[CompactRecordRole.STATEMENT],
        columns=["id", "statement_type", "semantic_ring", "source_ring", "target_ring"],
    ):
        total_relations += 1
        relation_kinds[
            {
                "MappingAssertion": "mapping",
                "NativeRelationAssertion": "native",
                "SourceAssignment": "sourceAssignment",
                "CrossRingRelationAssertion": "crossRing",
            }.get(row["statement_type"], row["statement_type"])
        ] += 1
        if row["id"] not in superseded_ids and row["id"] not in rescinded_ids:
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
                "attestedAt": row["attested_at"],
                "decision": _short(row["decision"]),
                "id": f"urn:ref:atlas-evidence:{row['evidence_id'].hex()}",
                "evidenceRole": _short(row["evidence_role"]),
                "attestor": row["attestor"],
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
    superseded_ids, rescinded_ids = _lifecycle_status_ids(view)

    relation_kind = {
        "MappingAssertion": "mapping",
        "NativeRelationAssertion": "native",
        "SourceAssignment": "sourceAssignment",
        "CrossRingRelationAssertion": "crossRing",
    }
    relations = []
    for row in statement_rows:
        if row["id"] in superseded_ids:
            status = "superseded"
        elif row["id"] in rescinded_ids:
            status = "rescinded"
        else:
            status = "current"
        relation = {
            "assertedAt": row["asserted_at"],
            "authoritative": status == "current",
            "authority": ("authoritative" if status == "current" else "historicalEditorialRecord"),
            "evidence": evidence_by_statement[row["id"]],
            "id": row["id"],
            "kind": relation_kind.get(row["statement_type"], row["statement_type"]),
            "object": row["object"],
            "objectLabel": display.get(row["object"], _short(row["object"])),
            "predicate": row["predicate"],
            "predicateLabel": _short(row["predicate"]),
            "sourceRelease": row["source_release"],
            "status": status,
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
    "atlas_explorer_facets",
    "atlas_parquet_resource",
    "build_atlas_explorer_model",
    "build_atlas_explorer_static_shards",
    "open_atlas_explorer",
    "render_atlas_explorer",
    "render_atlas_parquet_explorer",
    "render_atlas_v3_explorer",
    "search_atlas_parquet",
]

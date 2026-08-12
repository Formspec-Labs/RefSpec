"""Atlas explorer render contract, shard writers, and shared JSON primitives.

Moved verbatim out of the retired RDF explorer. Everything here has a live
consumer in :mod:`refspec.atlas.explorer`, which builds the same model from the
compact Parquet search view: the ``@@``-delimited browser template and the
schema contract (:func:`_validate_model`) it is rendered against, the static
shard finalizers and writers, and the JSON accessors those share.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
import stat
import unicodedata
from collections import OrderedDict
from collections.abc import Iterator, Mapping, Sequence
from io import BytesIO
from pathlib import Path, PurePosixPath
from string import Template
from typing import Any, BinaryIO, cast

from rdflib import Namespace

from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

ATLAS_V3_EXPLORER_TYPE = "urn:ref:type:Atlas3ExplorerView"
ATLAS_V3_EXPLORER_SCHEMA_VERSION = "3.0"

# These familiar names now identify Atlas 3.0. They are aliases, not a legacy
# Atlas 2 reader or wire-format compatibility layer.
EXPLORER_TYPE = ATLAS_V3_EXPLORER_TYPE
EXPLORER_SCHEMA_VERSION = ATLAS_V3_EXPLORER_SCHEMA_VERSION

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")


_CROSS_RING_POLICIES = {
    ("entity", "legalIdentity", str(ATLAS.referencesLegalIdentity)),
    ("entity", "subject", str(ATLAS.hasIndexedSubject)),
    ("legalIdentity", "subject", str(ATLAS.hasIndexedSubject)),
}

# Atlas 3 filtering starts from authority role. The reader does not consume the
# Atlas 2 planning-index facets that the retired explorer used.
EXPLORER_FILTER_SEMANTICS: tuple[Mapping[str, object], ...] = (
    {
        "recordKind": "resource",
        "authorityRole": "asserted",
        "filterFields": ("semanticRing", "resourceProfile", "labels"),
    },
    {
        "recordKind": "assertedRelation",
        "authorityRole": "asserted",
        "filterFields": ("kind", "semanticRing", "sourceRing", "targetRing", "predicate", "status"),
    },
    {
        "recordKind": "projectedRelation",
        "authorityRole": "projection",
        "filterFields": ("semanticRing", "sourceRing", "targetRing", "predicate"),
    },
    {
        "recordKind": "derivedRelation",
        "authorityRole": "derived",
        "filterFields": ("semanticRing", "predicate", "rule", "engine"),
    },
)
PLANNING_FILTER_SEMANTICS: tuple[Mapping[str, str], ...] = ()

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXPLORER_RECORD_PREFIX_LENGTH = 3
_EXPLORER_PAGE_SIZE = 500
_EXPLORER_SPOOL_HANDLE_LIMIT = 64
_EXPLORER_SHARD_TYPE = "AtlasExplorerStaticShard"
_EXPLORER_SHARD_INDEX_TYPE = "AtlasExplorerStaticShardIndex"
_EXPLORER_SHARD_BUNDLE_TYPE = "AtlasExplorerStaticShardBundle"
_EXPLORER_SHARD_VERSION = "2"
ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE = "atlas-3-static-full-corpus-shards-gzip-v3"
_ATLAS_V3_EXPLORER_LEGACY_SHARD_BUILDER_RECIPE = (
    "atlas-3-static-full-corpus-shards-gzip-v2"
)
ATLAS_PARQUET_EXPLORER_SHARD_BUILDER_RECIPE = "atlas-parquet-static-full-corpus-shards-gzip-v1"
_EXPLORER_SHARD_BUILDER_RECIPES = frozenset(
    {
        ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE,
        _ATLAS_V3_EXPLORER_LEGACY_SHARD_BUILDER_RECIPE,
        ATLAS_PARQUET_EXPLORER_SHARD_BUILDER_RECIPE,
    }
)
_EXPLORER_SHARD_SCHEMA = "https://refspec.org/schema/atlas-explorer-static-shards/v2"


class Atlas3ExplorerError(ValueError):
    """An Atlas 3.0 distribution or explorer model is unsafe to consume."""


AtlasExplorerError = Atlas3ExplorerError


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Atlas3ExplorerError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise Atlas3ExplorerError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _exact_fields(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise Atlas3ExplorerError(
            f"{label} fields differ; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise Atlas3ExplorerError(f"{label} must be non-empty trimmed text")
    return value


def _digest(value: object, label: str) -> str:
    text_value = _text(value, label)
    if _DIGEST.fullmatch(text_value) is None:
        raise Atlas3ExplorerError(f"{label} must be sha256:<64 lowercase hex>")
    return text_value


def _count(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Atlas3ExplorerError(f"{label} must be a non-negative integer")
    return value


def _iri_text(value: object, label: str) -> str:
    result = _text(value, label)
    if ":" not in result or any(character.isspace() for character in result):
        raise Atlas3ExplorerError(f"{label} must be an absolute IRI")
    return result


def _safe_relative_path(value: object, label: str) -> str:
    result = _text(value, label)
    path = PurePosixPath(result)
    if (
        path.is_absolute()
        or result != path.as_posix()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in result
    ):
        raise Atlas3ExplorerError(f"{label} must be a normalized safe relative path")
    return result


class _JsonlSpool:
    """Bound open files while partitioning deterministic build rows."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._handles: OrderedDict[str, BinaryIO] = OrderedDict()

    def append(self, key: str, value: Mapping[str, Any]) -> None:
        if re.fullmatch(r"[0-9a-z_]+", key) is None:
            raise Atlas3ExplorerError(f"unsafe explorer spool key {key!r}")
        handle = self._handles.pop(key, None)
        if handle is None:
            handle = (self.root / f"{key}.jsonl").open("ab")
        self._handles[key] = handle
        handle.write(canonical_json_bytes(value))
        if len(self._handles) > _EXPLORER_SPOOL_HANDLE_LIMIT:
            _old_key, old_handle = self._handles.popitem(last=False)
            old_handle.close()

    def close(self) -> None:
        while self._handles:
            _key, handle = self._handles.popitem(last=False)
            handle.close()

    def partition_keys(self) -> tuple[str, ...]:
        self.close()
        return tuple(path.stem for path in sorted(self.root.glob("*.jsonl")))


def _explorer_hash_prefix(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _iter_merged_spool_records(path: Path) -> Iterator[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise Atlas3ExplorerError(
                    f"Atlas explorer spool {path.name} line {line_number} is invalid"
                ) from error
            row = _mapping(raw, f"Atlas explorer spool {path.name} row")
            record_id = _iri_text(row.get("id"), "Atlas explorer spool record id")
            merged = rows.setdefault(record_id, {"id": record_id, "facts": []})
            merged["facts"].extend(_sequence(row.get("facts", []), "Atlas explorer facts"))
    for record_id in sorted(rows):
        row = rows[record_id]
        row["facts"] = [list(fact) for fact in sorted({tuple(fact) for fact in row["facts"]})]
        yield row


def _append_record_augmentation(
    spool: _JsonlSpool,
    record_id: str,
    field: str,
    value: object,
) -> None:
    spool.append(
        _explorer_hash_prefix(record_id, _EXPLORER_RECORD_PREFIX_LENGTH),
        {field: value, "id": record_id},
    )


def _normalized_search_words(values: Sequence[str]) -> set[str]:
    words: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKD", value.casefold()).encode(
            "ascii", "ignore"
        ).decode("ascii")
        words.update(re.findall(r"[a-z0-9]+", normalized))
    return words


def _search_key(word: str) -> str:
    return (word + "__")[:2]


def _finalize_explorer_resource_summaries(
    summary_spool: _JsonlSpool,
    augmentation_spool: _JsonlSpool,
    catalog_spool: _JsonlSpool,
    search_spool: _JsonlSpool,
    release_resource_spool: _JsonlSpool | None = None,
) -> int:
    role_order = {"preferred": 0, "alternate": 1, "hidden": 2}
    resource_count = 0
    for prefix in summary_spool.partition_keys():
        rows: dict[str, dict[str, Any]] = {}
        with (summary_spool.root / f"{prefix}.jsonl").open("rb") as stream:
            for line in stream:
                raw = _mapping(json.loads(line), "Atlas explorer resource summary row")
                resource_id = cast(str, raw["id"])
                row = rows.setdefault(
                    resource_id,
                    {
                        "id": resource_id,
                        "labels": [],
                        "release": raw["release"],
                        "ring": raw["ring"],
                    },
                )
                if row["release"] != raw["release"] or row["ring"] != raw["ring"]:
                    raise Atlas3ExplorerError(
                        f"Atlas explorer resource {resource_id} has inconsistent summary facts"
                    )
                row["labels"].append(dict(cast(Mapping[str, Any], raw["label"])))
        for resource_id in sorted(rows):
            row = rows[resource_id]
            labels = sorted(
                {
                    (
                        cast(str, label["role"]),
                        cast(str, label["value"]),
                        cast(str, label.get("language", "")),
                    )
                    for label in row["labels"]
                },
                key=lambda value: (
                    role_order.get(value[0], 99),
                    value[1].casefold(),
                    value,
                ),
            )
            if not labels:
                raise Atlas3ExplorerError(
                    f"Atlas explorer resource {resource_id} has no display label"
                )
            display = labels[0]
            summary = {
                "displayLabel": display[1],
                "displayLabelRole": display[0],
                "id": resource_id,
                "labels": [
                    {
                        **({"language": language} if language else {}),
                        "role": role,
                        "value": value,
                    }
                    for role, value, language in labels
                ],
                "release": row["release"],
                "ring": row["ring"],
                "searchText": " ".join(value for _role, value, _language in labels),
            }
            _append_record_augmentation(
                augmentation_spool,
                resource_id,
                "summary",
                summary,
            )
            normalized_words = _normalized_search_words(
                [value for _role, value, _language in labels]
            )
            display_words = sorted(_normalized_search_words([display[1]]))
            catalog_key = _search_key(display_words[0] if display_words else "_")
            catalog_spool.append(catalog_key, summary)
            if release_resource_spool is not None:
                release_resource_spool.append(
                    _explorer_hash_prefix(cast(str, row["release"]), 64),
                    summary,
                )
            for key in sorted({_search_key(word) for word in normalized_words}):
                search_spool.append(key, summary)
            resource_count += 1
    augmentation_spool.close()
    catalog_spool.close()
    search_spool.close()
    if release_resource_spool is not None:
        release_resource_spool.close()
    return resource_count


def _read_augmentations(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open("rb") as stream:
        for line in stream:
            raw = _mapping(json.loads(line), "Atlas explorer augmentation row")
            record_id = cast(str, raw["id"])
            row = rows.setdefault(record_id, {})
            for field in ("evidenceBindings", "identifiers", "relations"):
                if field in raw:
                    row.setdefault(field, []).extend(
                        _sequence(raw[field], f"Atlas explorer {field}")
                    )
            if "summary" in raw:
                if "summary" in row and row["summary"] != raw["summary"]:
                    raise Atlas3ExplorerError(
                        f"Atlas explorer record {record_id} repeats a different summary"
                    )
                row["summary"] = dict(_mapping(raw["summary"], "Atlas explorer summary"))
    return rows


def _write_explorer_shard(
    root: Path,
    kind: str,
    payload: Mapping[str, Any],
    *,
    url_prefix: str,
) -> dict[str, Any]:
    content = canonical_json_bytes(payload)
    compressed_buffer = BytesIO()
    with gzip.GzipFile(
        fileobj=compressed_buffer,
        mode="wb",
        filename="",
        compresslevel=9,
        mtime=0,
    ) as compressed_stream:
        compressed_stream.write(content)
    transport = compressed_buffer.getvalue()
    transport_digest = sha256_digest(transport)
    filename = f"{kind}-{transport_digest.removeprefix('sha256:')}.json.gz"
    path = root / filename
    path.write_bytes(transport)
    return {
        "count": len(cast(Sequence[Any], payload.get("records", payload.get("entries", ())))),
        "content": {
            "byteLength": len(content),
            "digest": sha256_digest(content),
            "mediaType": "application/json",
        },
        "transport": {
            "byteLength": len(transport),
            "compression": "gzip",
            "digest": transport_digest,
        },
        "url": f"{url_prefix}{filename}",
    }


def _explorer_shard_ref(value: object, label: str) -> Mapping[str, Any]:
    ref = _mapping(value, label)
    _exact_fields(ref, frozenset({"content", "count", "transport", "url"}), label)
    _count(ref.get("count"), f"{label} count")
    url = _safe_relative_path(ref.get("url"), f"{label} URL")
    if not url.endswith(".json.gz"):
        raise Atlas3ExplorerError(f"{label} URL must name a gzip JSON shard")
    content = _mapping(ref.get("content"), f"{label} content")
    _exact_fields(
        content,
        frozenset({"byteLength", "digest", "mediaType"}),
        f"{label} content",
    )
    if (
        content.get("mediaType") != "application/json"
        or _count(content.get("byteLength"), f"{label} content byteLength") <= 0
    ):
        raise Atlas3ExplorerError(f"{label} content receipt is unsupported")
    _digest(content.get("digest"), f"{label} content digest")
    transport = _mapping(ref.get("transport"), f"{label} transport")
    _exact_fields(
        transport,
        frozenset({"byteLength", "compression", "digest"}),
        f"{label} transport",
    )
    if (
        transport.get("compression") != "gzip"
        or _count(transport.get("byteLength"), f"{label} transport byteLength") <= 0
    ):
        raise Atlas3ExplorerError(f"{label} transport receipt is unsupported")
    _digest(transport.get("digest"), f"{label} transport digest")
    return ref


def _finalize_explorer_record_shards(
    merged_root: Path,
    augmentation_spool: _JsonlSpool,
    target_root: Path,
    manifest_digest: str,
    url_prefix: str,
) -> tuple[dict[str, dict[str, Any]], int]:
    result: dict[str, dict[str, Any]] = {}
    record_count = 0
    prefixes = sorted(
        {path.stem for path in merged_root.glob("*.jsonl")}
        | set(augmentation_spool.partition_keys())
    )
    for prefix in prefixes:
        merged_path = merged_root / f"{prefix}.jsonl"
        records = (
            {cast(str, row["id"]): row for row in _iter_merged_spool_records(merged_path)}
            if merged_path.exists()
            else {}
        )
        for record_id, augmentation in _read_augmentations(
            augmentation_spool.root / f"{prefix}.jsonl"
        ).items():
            record = records.setdefault(record_id, {"facts": [], "id": record_id})
            for field in ("evidenceBindings", "identifiers", "relations"):
                if field in augmentation:
                    record[field] = sorted(set(cast(Sequence[str], augmentation[field])))
            if "summary" in augmentation:
                record["summary"] = augmentation["summary"]
        rows = [records[record_id] for record_id in sorted(records)]
        ref = _write_explorer_shard(
            target_root,
            "records",
            {
                "key": prefix,
                "kind": "records",
                "manifestDigest": manifest_digest,
                "records": rows,
                "type": _EXPLORER_SHARD_TYPE,
                "version": _EXPLORER_SHARD_VERSION,
            },
            url_prefix=url_prefix,
        )
        ref["key"] = prefix
        result[prefix] = ref
        record_count += len(rows)
    return result, record_count


def _finalize_explorer_page_shards(
    spool: _JsonlSpool,
    target_root: Path,
    kind: str,
    manifest_digest: str,
    url_prefix: str,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for key in spool.partition_keys():
        entries_by_id: dict[str, dict[str, Any]] = {}
        with (spool.root / f"{key}.jsonl").open("rb") as stream:
            for line in stream:
                row = dict(_mapping(json.loads(line), f"Atlas explorer {kind} row"))
                entries_by_id[cast(str, row["id"])] = row
        entries = sorted(
            entries_by_id.values(),
            key=lambda row: (
                cast(str, row["displayLabel"]).casefold(),
                cast(str, row["displayLabel"]),
                cast(str, row["id"]),
            ),
        )
        refs: list[dict[str, Any]] = []
        for offset in range(0, len(entries), _EXPLORER_PAGE_SIZE):
            page = entries[offset : offset + _EXPLORER_PAGE_SIZE]
            ref = _write_explorer_shard(
                target_root,
                kind,
                {
                    "entries": page,
                    "key": key,
                    "kind": kind,
                    "manifestDigest": manifest_digest,
                    "type": _EXPLORER_SHARD_TYPE,
                    "version": _EXPLORER_SHARD_VERSION,
                },
                url_prefix=url_prefix,
            )
            ref.update(
                {
                    "firstLabel": page[0]["displayLabel"],
                    "key": key,
                    "lastLabel": page[-1]["displayLabel"],
                    "releases": sorted({cast(str, row["release"]) for row in page}),
                    "rings": sorted({cast(str, row["ring"]) for row in page}),
                }
            )
            refs.append(ref)
        result[key] = refs
    return result


def _safe_existing_shard_directory(path: Path) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    if not path.exists():
        return payloads
    status = path.lstat()
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise Atlas3ExplorerError("Atlas explorer shard target is not a real directory")
    for child in path.iterdir():
        child_status = child.lstat()
        if stat.S_ISLNK(child_status.st_mode) or not stat.S_ISREG(child_status.st_mode):
            raise Atlas3ExplorerError("Atlas explorer shard directory has an unsafe member")
        payloads[child.name] = child.read_bytes()
    return payloads


def _validate_model(model: Mapping[str, Any]) -> None:
    if model.get("type") != ATLAS_V3_EXPLORER_TYPE or model.get("schemaVersion") != ATLAS_V3_EXPLORER_SCHEMA_VERSION:
        raise Atlas3ExplorerError("Atlas 3.0 explorer type or schemaVersion is unsupported")
    _text(model.get("title"), "Atlas 3.0 explorer title")
    distribution = _mapping(model.get("distribution"), "Atlas 3.0 explorer distribution")
    manifest_digest = _digest(
        distribution.get("manifestDigest"),
        "Atlas 3.0 explorer manifest digest",
    )
    asserted_inventory_digest = _digest(
        distribution.get("assertedInventoryDigest"),
        "Atlas 3.0 explorer asserted inventory digest",
    )
    if "fullCorpus" in model:
        bundle = _mapping(model["fullCorpus"], "Atlas explorer static shard bundle")
        _exact_fields(
            bundle,
            frozenset(
                {
                    "assertedInventoryDigest",
                    "builderRecipe",
                    "counts",
                    "index",
                    "manifestDigest",
                    "schema",
                    "type",
                    "version",
                }
            ),
            "Atlas explorer static shard bundle",
        )
        if (
            bundle.get("type") != _EXPLORER_SHARD_BUNDLE_TYPE
            or bundle.get("version") != _EXPLORER_SHARD_VERSION
            or bundle.get("manifestDigest") != manifest_digest
            or bundle.get("assertedInventoryDigest") != asserted_inventory_digest
            or bundle.get("builderRecipe") not in _EXPLORER_SHARD_BUILDER_RECIPES
            or bundle.get("schema") != _EXPLORER_SHARD_SCHEMA
        ):
            raise Atlas3ExplorerError("Atlas explorer static shard identity differs")
        _explorer_shard_ref(bundle.get("index"), "Atlas explorer shard index")
    authority = _mapping(model.get("authority"), "Atlas 3.0 explorer authority")
    if set(authority) != {"asserted", "projection", "derived"}:
        raise Atlas3ExplorerError("Atlas 3.0 explorer must keep all three graph roles distinct")
    expected_status = {
        "asserted": "authoritative",
        "projection": "reproducibleConvenienceView",
        "derived": "nonAuthoritative",
    }
    graph_ids: set[str] = set()
    for role, status_value in expected_status.items():
        row = _mapping(authority.get(role), f"Atlas 3.0 explorer {role}")
        if row.get("status") != status_value:
            raise Atlas3ExplorerError(f"Atlas 3.0 explorer {role} authority status differs")
        graph_ids.add(_text(row.get("graph"), f"Atlas 3.0 explorer {role} graph"))
    if len(graph_ids) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 explorer graph role IRIs must be distinct")
    for field in (
        "resourceIndex",
        "resources",
        "sourceRecords",
        "assertedRelations",
        "projectedRelations",
        "derivedRelations",
    ):
        _sequence(model.get(field), f"Atlas 3.0 explorer {field}")
    resource_index_ids = [
        _text(_mapping(row, "Atlas 3.0 resource index row").get("id"), "resource index id")
        for row in model["resourceIndex"]
    ]
    if len(resource_index_ids) != len(set(resource_index_ids)):
        raise Atlas3ExplorerError("Atlas 3.0 resource index repeats an id")
    summary = _mapping(model.get("summary"), "Atlas 3.0 explorer summary")
    if summary.get("indexedResources") != len(resource_index_ids):
        raise Atlas3ExplorerError("Atlas 3.0 resource index count differs")
    available_resources = _count(
        summary.get("availableResources"),
        "Atlas 3.0 explorer availableResources",
    )
    if available_resources < len(resource_index_ids):
        raise Atlas3ExplorerError("Atlas 3.0 resource index exceeds the sealed resource count")
    coverage = _mapping(model.get("coverage"), "Atlas 3.0 explorer coverage")
    resources_by_ring = _mapping(
        coverage.get("resourcesByRing"),
        "Atlas 3.0 explorer resourcesByRing",
    )
    if sum(
        _count(value, f"Atlas 3.0 explorer resourcesByRing.{ring}")
        for ring, value in resources_by_ring.items()
    ) != available_resources:
        raise Atlas3ExplorerError("Atlas 3.0 explorer resource ring counts do not reconcile")
    release_resource_total = sum(
        _count(
            _mapping(row, "Atlas 3.0 explorer release coverage").get("count"),
            "Atlas 3.0 explorer release resource count",
        )
        for row in _sequence(
            coverage.get("resourcesByRelease"),
            "Atlas 3.0 explorer resourcesByRelease",
        )
    )
    if release_resource_total != available_resources:
        raise Atlas3ExplorerError("Atlas 3.0 explorer resource release counts do not reconcile")
    available_assertions = _count(
        summary.get("availableAssertedRelations"),
        "Atlas 3.0 explorer availableAssertedRelations",
    )
    asserted_relations_by_ring = _mapping(
        coverage.get("assertedRelationsByRing"),
        "Atlas 3.0 explorer assertedRelationsByRing",
    )
    ring_touch_count = sum(
        _count(value, f"Atlas 3.0 explorer assertedRelationsByRing.{ring}")
        for ring, value in asserted_relations_by_ring.items()
    )
    cross_ring_relation_count = sum(
        _count(
            _mapping(row, "Atlas 3.0 cross-ring pair coverage").get("count"),
            "Atlas 3.0 explorer cross-ring pair count",
        )
        for row in _sequence(
            coverage.get("crossRingRelationsByPair"),
            "Atlas 3.0 explorer crossRingRelationsByPair",
        )
    )
    if ring_touch_count - cross_ring_relation_count != available_assertions:
        raise Atlas3ExplorerError("Atlas 3.0 explorer assertion ring counts do not reconcile")
    available_source_records = _count(
        summary.get("availableSourceRecords"),
        "Atlas 3.0 explorer availableSourceRecords",
    )
    source_record_total = sum(
        _count(
            _mapping(row, "Atlas 3.0 explorer source coverage").get("sourceRecords"),
            "Atlas 3.0 explorer source-record count",
        )
        for row in _sequence(
            coverage.get("sourceRecordsByRelease"),
            "Atlas 3.0 explorer sourceRecordsByRelease",
        )
    )
    if source_record_total != available_source_records:
        raise Atlas3ExplorerError("Atlas 3.0 explorer source release counts do not reconcile")
    detailed_resource_ids = {
        _text(_mapping(row, "Atlas 3.0 resource").get("id"), "resource id")
        for row in model["resources"]
    }
    if not detailed_resource_ids.issubset(resource_index_ids):
        raise Atlas3ExplorerError("Atlas 3.0 detailed resources are absent from its index")
    available_identifiers = _count(
        summary.get("availableIdentifiers"),
        "Atlas 3.0 explorer availableIdentifiers",
    )
    indexed_identifiers = _count(
        summary.get("indexedIdentifiers"),
        "Atlas 3.0 explorer indexedIdentifiers",
    )
    shown_identifiers = _count(
        summary.get("shownIdentifiers"),
        "Atlas 3.0 explorer shownIdentifiers",
    )
    identifier_ids: set[str] = set()
    observed_shown_identifiers = 0
    for resource_value in model["resources"]:
        resource = _mapping(resource_value, "Atlas 3.0 resource")
        resource_id = _text(resource.get("id"), "Atlas 3.0 resource id")
        for identifier_value in _sequence(
            resource.get("identifiers"),
            f"Atlas 3.0 resource {resource_id} identifiers",
        ):
            identifier = _mapping(identifier_value, "Atlas 3.0 identifier")
            identifier_id = _text(identifier.get("id"), "Atlas 3.0 identifier id")
            _text(identifier.get("value"), f"Atlas 3.0 identifier {identifier_id} value")
            _text(
                identifier.get("schemeLabel"),
                f"Atlas 3.0 identifier {identifier_id} scheme label",
            )
            if identifier.get("identifies") != resource_id:
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 identifier {identifier_id} is attached to the wrong resource"
                )
            if identifier_id in identifier_ids:
                raise Atlas3ExplorerError("Atlas 3.0 explorer repeats an identifier record")
            identifier_ids.add(identifier_id)
            observed_shown_identifiers += 1
    if (
        observed_shown_identifiers != shown_identifiers
        or shown_identifiers > indexed_identifiers
        or indexed_identifiers > available_identifiers
    ):
        raise Atlas3ExplorerError("Atlas 3.0 explorer identifier counts do not reconcile")
    def validate_relation_rings(row: Mapping[str, Any], label: str) -> None:
        rings = list(_sequence(row.get("semanticRings"), f"{label} semanticRings"))
        semantic_ring = row.get("semanticRing")
        source_ring = row.get("sourceRing")
        target_ring = row.get("targetRing")
        if semantic_ring is not None:
            if source_ring is not None or target_ring is not None or rings != [semantic_ring]:
                raise Atlas3ExplorerError(f"{label} has conflicting same-ring fields")
            return
        if (
            not isinstance(source_ring, str)
            or not isinstance(target_ring, str)
            or source_ring == target_ring
            or rings != [source_ring, target_ring]
        ):
            raise Atlas3ExplorerError(f"{label} has invalid cross-ring fields")

    for row in model["assertedRelations"]:
        validate_relation_rings(row, "Atlas 3.0 asserted relation")
        expected_authority = row.get("status") == "current"
        if row.get("authoritative") is not expected_authority or row.get("authority") != (
            "authoritative" if expected_authority else "historicalEditorialRecord"
        ):
            raise Atlas3ExplorerError("Atlas 3.0 asserted relation authority differs from its lifecycle status")
        if row.get("kind") == "crossRing":
            policy = (row.get("sourceRing"), row.get("targetRing"), row.get("predicate"))
            if policy not in _CROSS_RING_POLICIES:
                raise Atlas3ExplorerError("Atlas 3.0 asserted cross-ring relation violates its policy")
        elif row.get("sourceRing") is not None or row.get("targetRing") is not None:
            raise Atlas3ExplorerError("Atlas 3.0 same-ring assertion uses endpoint rings")
    for row in model["projectedRelations"]:
        validate_relation_rings(row, "Atlas 3.0 projected relation")
    if any(row.get("authoritative") is not False for row in model["projectedRelations"]):
        raise Atlas3ExplorerError("Atlas 3.0 projections contain an authoritative row")
    if any(row.get("authority") != "nonAuthoritative" for row in model["derivedRelations"]):
        raise Atlas3ExplorerError("Atlas 3.0 derivations contain an authoritative row")
    assertion_ids = {
        _text(_mapping(row, "Atlas 3.0 asserted relation").get("id"), "asserted relation id")
        for row in model["assertedRelations"]
    }
    for field, rows in (
        ("supportingAssertions", model["projectedRelations"]),
        ("derivedFromAssertions", model["derivedRelations"]),
    ):
        for raw_row in rows:
            row = _mapping(raw_row, f"Atlas 3.0 relation with {field}")
            references = {
                _text(value, f"Atlas 3.0 relation {field}[]")
                for value in _sequence(row.get(field), f"Atlas 3.0 relation {field}")
            }
            if not references.issubset(assertion_ids):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 relation {field} is not provenance-closed"
                )


def _safe_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


class _Atlas3Template(Template):
    delimiter = "@@"


_GRAPH_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <link rel="icon" href="data:,">
  <title>@@title · RefSpec Atlas 3 explorer</title>
  <style>
    :root {
      --ink: #edf4f0; --muted: #9caaa4; --faint: #66756f; --paper: #09100e;
      --raised: #101a17; --rule: #263530; --rule-strong: #3b4f48; --focus: #99ddd0;
      --asserted: #70d29b; --projection: #68a9ff; --derived: #e7ad55;
      --serif: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; }
    body { margin: 0; overflow: hidden; color: var(--ink); background: var(--paper); font: 14px/1.45 var(--sans); }
    button, input, select { font: inherit; }
    button:focus-visible, input:focus-visible, select:focus-visible, canvas:focus-visible {
      outline: 2px solid var(--focus); outline-offset: 2px;
    }
    .shell { display: grid; grid-template-rows: 68px minmax(0, 1fr) 34px; height: 100%; }
    .appbar {
      display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 1rem; align-items: center;
      padding: .75rem 1.1rem; border-bottom: 1px solid var(--rule); background: rgba(9, 16, 14, .96);
    }
    .eyebrow { color: var(--asserted); font: 600 10px/1.2 var(--mono); letter-spacing: .14em; text-transform: uppercase; }
    h1 { margin: .2rem 0 0; overflow: hidden; font: 500 1.35rem/1.1 var(--serif); text-overflow: ellipsis; white-space: nowrap; }
    .metrics { display: flex; gap: 1.2rem; }
    .metric { text-align: right; } .metric b { display: block; font: 600 .95rem/1 var(--mono); }
    .metric span { color: var(--faint); font-size: .65rem; letter-spacing: .08em; text-transform: uppercase; }
    .workspace { display: grid; grid-template-columns: var(--controls-width, 272px) 5px minmax(0, 1fr) 330px; min-height: 0; }
    .panel { min-height: 0; overflow: auto; background: rgba(14, 23, 20, .94); scrollbar-color: var(--rule-strong) transparent; }
    .controls { padding: 1rem; }
    .controls-resizer { position: relative; z-index: 3; background: var(--rule); cursor: col-resize; touch-action: none; }
    .controls-resizer::after { position: absolute; inset: 0 -3px; content: ""; }
    .controls-resizer:hover, .controls-resizer:focus-visible, .workspace.resizing .controls-resizer { background: var(--asserted); }
    .workspace.resizing { cursor: col-resize; user-select: none; }
    .inspector { padding: 1rem 1.05rem 1.5rem; border-left: 1px solid var(--rule); }
    .panel h2, .panel h3 { margin: 0; font-size: .7rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
    .panel h3 { color: var(--faint); }
    .control-section { padding: .9rem 0; border-bottom: 1px solid var(--rule); }
    .control-section:last-child { border-bottom: 0; }
    .control-heading { display: flex; gap: .75rem; align-items: center; justify-content: space-between; }
    .section-action { padding: 0; color: var(--asserted); border: 0; background: transparent; font: 10px/1 var(--mono); cursor: pointer; }
    .section-action:hover { color: var(--ink); }
    .section-action:disabled { color: var(--faint); cursor: default; }
    .search-wrap { position: relative; margin-top: .65rem; }
    #search, #ring-filter, #predicate-filter, #render-limit-number {
      width: 100%; min-height: 38px; padding: .55rem .65rem; color: var(--ink);
      border: 1px solid var(--rule-strong); border-radius: 4px; background: #080e0c;
    }
    #search { padding-right: 2rem; } .key { position: absolute; top: 50%; right: .65rem; color: var(--faint); transform: translateY(-50%); }
    .results { display: grid; max-height: min(42vh, 30rem); margin-top: .35rem; overflow-y: auto; overscroll-behavior: contain; scrollbar-color: var(--rule-strong) transparent; }
    .result { padding: .42rem .3rem; overflow: hidden; color: var(--muted); border: 0; border-bottom: 1px solid var(--rule); background: transparent; text-align: left; cursor: pointer; }
    .result:hover { color: var(--ink); background: rgba(112, 210, 155, .08); }
    .result b, .result small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .result small { color: var(--faint); font-size: .68rem; }
    .filter-list { display: grid; gap: .48rem; margin-top: .65rem; }
    .filter { display: grid; grid-template-columns: 14px 10px minmax(0, 1fr) auto; gap: .5rem; align-items: center; color: var(--muted); cursor: pointer; }
    .filter input { width: 14px; height: 14px; margin: 0; accent-color: var(--asserted); }
    .filter .swatch { width: 9px; height: 9px; border-radius: 50%; background: var(--swatch); }
    .filter .label { overflow: hidden; color: var(--ink); text-overflow: ellipsis; white-space: nowrap; }
    .filter small { color: var(--faint); font: 10px/1 var(--mono); }
    .authority-filter { grid-template-columns: 14px 20px minmax(0, 1fr); }
    .edge-key { width: 20px; height: 0; border-top: 2px solid var(--edge); }
    .edge-key.projection { border-top-style: dashed; } .edge-key.derived { border-top-style: dotted; }
    .hint { margin: .55rem 0 0; color: var(--faint); font-size: .72rem; }
    .hint.error { color: #e89b8a; }
    .render-limit { display: grid; grid-template-columns: 1fr 66px; gap: .5rem; align-items: center; margin-top: .65rem; }
    #render-limit-range { grid-column: 1 / -1; width: 100%; accent-color: var(--asserted); }
    #render-limit-number { min-height: 30px; text-align: right; font: 11px/1 var(--mono); }
    .actions { display: flex; gap: .5rem; margin-top: .75rem; }
    .action { padding: .45rem .6rem; color: var(--muted); border: 1px solid var(--rule-strong); border-radius: 4px; background: transparent; cursor: pointer; }
    .action:hover { color: var(--ink); border-color: var(--asserted); }
    .stage { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: radial-gradient(circle at 50% 42%, rgba(66, 112, 95, .12), transparent 34rem); }
    #graph { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }
    #graph.panning { cursor: grabbing; }
    .graph-tools { position: absolute; top: .7rem; right: .7rem; display: flex; overflow: hidden; border: 1px solid var(--rule-strong); border-radius: 4px; background: rgba(9, 16, 14, .92); }
    .graph-tools button { width: 38px; height: 38px; padding: 0; color: var(--muted); border: 0; border-right: 1px solid var(--rule); background: transparent; cursor: pointer; }
    .graph-tools button:last-child { border-right: 0; } .graph-tools button:hover { color: var(--ink); background: rgba(112, 210, 155, .09); }
    .legend { position: absolute; bottom: .75rem; left: .75rem; display: flex; flex-wrap: wrap; gap: .7rem; padding: .42rem .55rem; color: var(--muted); border: 1px solid var(--rule); border-radius: 4px; background: rgba(9, 16, 14, .9); font-size: .68rem; }
    .legend span { display: flex; gap: .35rem; align-items: center; } .legend i { width: 18px; border-top: 2px solid var(--edge); }
    .legend .projection i { border-top-style: dashed; } .legend .derived i { border-top-style: dotted; }
    .graph-status { position: absolute; top: .75rem; left: .75rem; padding: .38rem .5rem; color: var(--muted); border: 1px solid var(--rule); border-radius: 4px; background: rgba(9, 16, 14, .9); font: 10px/1.3 var(--mono); pointer-events: none; }
    .tooltip { position: absolute; z-index: 5; max-width: 250px; padding: .42rem .55rem; color: var(--ink); border: 1px solid var(--rule-strong); background: rgba(7, 12, 10, .97); box-shadow: 0 10px 28px rgba(0,0,0,.36); pointer-events: none; transform: translate(12px, 12px); }
    .tooltip small { display: block; color: var(--faint); } .tooltip[hidden] { display: none; }
    .empty { margin-top: 1.3rem; color: var(--muted); } .empty b { display: block; margin-bottom: .4rem; color: var(--ink); font: 500 1.15rem/1.2 var(--serif); }
    .inspector-view[hidden], .empty[hidden] { display: none; }
    .kicker { margin: 1rem 0 .25rem; color: var(--asserted); font: 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; }
    .inspector-title { margin: 0 0 .8rem; font: 500 1.25rem/1.2 var(--serif); overflow-wrap: anywhere; }
    .badge { display: inline-block; margin: 0 .3rem .3rem 0; padding: .2rem .42rem; color: var(--muted); border: 1px solid var(--rule-strong); border-radius: 999px; font-size: .66rem; }
    .badge.asserted { color: var(--asserted); } .badge.projection { color: var(--projection); } .badge.derived { color: var(--derived); }
    .facts { display: grid; grid-template-columns: 5.2rem minmax(0, 1fr); gap: .42rem .65rem; margin: .8rem 0; }
    .facts dt { color: var(--faint); font-size: .7rem; } .facts dd { margin: 0; overflow-wrap: anywhere; color: var(--muted); }
    .iri, pre { color: var(--muted); font: 10px/1.45 var(--mono); overflow-wrap: anywhere; white-space: pre-wrap; }
    details { margin-top: .6rem; border-top: 1px solid var(--rule); padding-top: .55rem; } details summary { color: var(--muted); cursor: pointer; }
    .relation-brief { margin-top: .75rem; border-top: 1px solid var(--rule-strong); }
    .brief-block { padding: .68rem 0; border-bottom: 1px solid var(--rule); }
    .brief-block h4, .supporting h4 { margin: 0 0 .32rem; color: var(--faint); font-size: .65rem; letter-spacing: .1em; text-transform: uppercase; }
    .brief-block p { margin: 0; color: var(--muted); line-height: 1.5; }
    .brief-block .brief-lead { color: var(--ink); font: 500 1rem/1.42 var(--serif); }
    .supporting { padding: .78rem 0 .15rem; border-bottom: 1px solid var(--rule); }
    .supporting-intro { margin: 0 0 .55rem; color: var(--muted); font-size: .75rem; line-height: 1.45; }
    .support-list { display: grid; }
    .support-link { width: 100%; padding: .62rem 0; color: var(--muted); border: 0; border-top: 1px solid var(--rule); background: transparent; text-align: left; cursor: pointer; }
    .support-link:hover { color: var(--ink); }
    .support-link b, .support-link span, .support-link small { display: block; }
    .support-link b { color: var(--ink); font-weight: 600; line-height: 1.35; }
    .support-link span { margin-top: .2rem; line-height: 1.42; }
    .support-link small { margin-top: .28rem; color: var(--faint); font: 10px/1.4 var(--mono); }
    .evidence-list { display: grid; }
    .evidence-row { padding: .62rem 0; border-top: 1px solid var(--rule); }
    .evidence-row:first-child { border-top: 0; }
    .evidence-row b { display: block; color: var(--ink); font-size: .78rem; }
    .evidence-row p { margin: .22rem 0 0; color: var(--muted); font-size: .74rem; line-height: 1.45; }
    .inspector-back { margin: .65rem 0 .2rem; padding: .3rem 0; color: var(--asserted); border: 0; background: transparent; cursor: pointer; }
    .inspector-back:hover { color: var(--ink); }
    details.technical { margin-top: .75rem; }
    details.technical summary { color: var(--faint); font-size: .7rem; }
    .connections { display: grid; gap: .35rem; margin-top: .6rem; }
    .connection { width: 100%; padding: .45rem .5rem; color: var(--muted); border: 0; border-left: 2px solid var(--edge); background: rgba(255,255,255,.025); text-align: left; cursor: pointer; }
    .connection:hover { color: var(--ink); background: rgba(255,255,255,.055); }
    .connection small { display: block; margin-top: .2rem; color: var(--faint); font: 10px/1.35 var(--mono); }
    .footer { display: flex; justify-content: space-between; gap: 1rem; align-items: center; padding: 0 1rem; overflow: hidden; color: var(--faint); border-top: 1px solid var(--rule); background: #080e0c; font: 10px/1 var(--mono); }
    .footer span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    @media (max-width: 1000px) { .workspace { grid-template-columns: var(--controls-width, 238px) 5px minmax(0,1fr); } .inspector { position: absolute; z-index: 8; top: 68px; right: 0; bottom: 34px; width: min(340px, 86vw); box-shadow: -12px 0 38px rgba(0,0,0,.4); } }
    @media (max-width: 680px) { .workspace { grid-template-columns: 1fr; } .controls { position: absolute; z-index: 7; top: 68px; bottom: 34px; left: 0; width: min(272px, 88vw); } .controls-resizer { display: none; } .metrics .metric:not(:last-child) { display: none; } }
    @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
  </style>
</head>
<body>
<div class="shell">
  <header class="appbar">
    <div><span class="eyebrow">RefSpec Atlas 3 · graph authority explorer</span><h1>@@title</h1></div>
    <div class="metrics" aria-label="Atlas totals">
      <div class="metric"><b id="metric-resources">—</b><span>resources</span></div>
      <div class="metric"><b id="metric-asserted">—</b><span>asserted</span></div>
      <div class="metric"><b id="metric-derived">—</b><span>derived</span></div>
    </div>
  </header>
  <main class="workspace">
    <aside class="panel controls" id="controls" aria-label="Graph controls">
      <h2>Explore the graph</h2>
      <section class="control-section">
        <h3>Search</h3><div class="search-wrap"><input id="search" type="search" autocomplete="off" placeholder="English label, notation, or IRI" aria-label="Search Atlas resources"><span class="key">/</span></div>
        <div class="results" id="search-results" aria-live="polite"></div>
        <p class="hint" id="search-result-status" aria-live="polite"></p>
        <p class="hint" id="search-coverage"></p>
        <p class="hint" id="corpus-mode" aria-live="polite"></p>
      </section>
      <section class="control-section"><h3>Authority layers</h3><div class="filter-list">
        <label class="filter authority-filter"><input id="authority-asserted" type="checkbox" checked><span class="edge-key" style="--edge:var(--asserted)"></span><span class="label">Asserted</span></label>
        <label class="filter authority-filter"><input id="authority-projection" type="checkbox"><span class="edge-key projection" style="--edge:var(--projection)"></span><span class="label">Projection</span></label>
        <label class="filter authority-filter"><input id="authority-derived" type="checkbox" checked><span class="edge-key derived" style="--edge:var(--derived)"></span><span class="label">Derived</span></label>
        <label class="filter authority-filter"><input id="show-source-assignments" type="checkbox"><span class="edge-key" style="--edge:#8b9792"></span><span class="label">Source assignments</span></label>
      </div><p class="hint">Projection duplicates and source assignments stay hidden until requested.</p></section>
      <section class="control-section"><h3>Semantic ring</h3><select id="ring-filter" aria-label="Filter semantic ring"><option value="">All rings</option></select></section>
      <section class="control-section"><div class="control-heading"><h3>Atlas releases</h3><button class="section-action" id="select-no-releases" type="button">Select none</button></div><div class="filter-list" id="release-filters"></div></section>
      <section class="control-section"><h3>Relation predicate</h3><select id="predicate-filter" aria-label="Filter relation predicate"><option value="">All predicates</option></select></section>
      <section class="control-section"><h3>Rendered resources</h3><div class="render-limit"><span id="render-limit-label">—</span><input id="render-limit-number" type="number" min="1"><input id="render-limit-range" type="range" min="1"></div>
        <p class="hint">Move the slider to load more resources. Search matches and high-degree resources enter the graph first.</p><div class="actions"><button class="action" id="reset-view" type="button">Reset</button><button class="action" id="fit-view" type="button">Fit graph</button></div></section>
    </aside>
    <div class="controls-resizer" id="controls-resizer" role="separator" aria-label="Resize graph controls" aria-orientation="vertical" aria-valuemin="210" aria-valuemax="520" aria-valuenow="272" tabindex="0"></div>
    <section class="stage" id="stage" aria-label="Atlas relation graph">
      <canvas id="graph" tabindex="0" aria-label="Interactive Atlas 3 relation graph"></canvas>
      <div class="graph-status" id="graph-status">Preparing graph…</div>
      <div class="graph-tools"><button id="zoom-in" type="button" aria-label="Zoom in">+</button><button id="zoom-out" type="button" aria-label="Zoom out">−</button><button id="fit-canvas" type="button" aria-label="Fit graph to view">⌂</button></div>
      <div class="legend" aria-label="Relation authority legend"><span style="--edge:var(--asserted)"><i></i>Asserted</span><span class="projection" style="--edge:var(--projection)"><i></i>Projection</span><span class="derived" style="--edge:var(--derived)"><i></i>Derived</span></div>
      <div class="tooltip" id="tooltip" hidden></div>
    </section>
    <aside class="panel inspector" id="inspector" aria-label="Provenance inspector"><h2>Provenance inspector</h2><div class="empty" id="empty-inspector"><b>Select a resource or relation</b>Click a node or relation.</div><div class="inspector-view" id="inspector-view" hidden></div></aside>
  </main>
  <footer class="footer"><span id="distribution-id"></span><span id="manifest-digest"></span></footer>
</div>
<script id="atlas-data" type="application/json">@@atlas_data</script>
<script>
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("atlas-data").textContent);
  const workspace = document.querySelector(".workspace");
  const controlsPanel = document.getElementById("controls");
  const controlsResizer = document.getElementById("controls-resizer");
  const canvas = document.getElementById("graph");
  const stage = document.getElementById("stage");
  const ctx = canvas.getContext("2d", {alpha:true});
  const tooltip = document.getElementById("tooltip");
  const search = document.getElementById("search");
  const searchResults = document.getElementById("search-results");
  const searchResultStatus = document.getElementById("search-result-status");
  const ringFilter = document.getElementById("ring-filter");
  const predicateFilter = document.getElementById("predicate-filter");
  const corpusMode = document.getElementById("corpus-mode");
  const fullBundle = data.fullCorpus||null;
  const gzipStreamSupported = typeof DecompressionStream==="function";
  const fullMode = Boolean(fullBundle)&&location.protocol!=="file:"&&gzipStreamSupported;
  const releaseColors = ["#78c7b6","#d8ad62","#83aee1","#d38fae","#9fca72","#c596e5","#e28b6f","#72c5d8"];
  const layerColors = {asserted:"#70d29b", projection:"#68a9ff", derived:"#e7ad55"};
  const sourceById = new Map(data.sourceRecords.map(row => [row.id, row]));
  const sourceReleaseById = new Map(data.sourceReleases.map(row => [row.id, row]));
  const releaseById = new Map(data.atlasReleases.map((row,index) => [row.id, {...row, color:releaseColors[index%releaseColors.length]}]));
  const nodeById = new Map();
  const nodes = [];
  const assertedById = new Map(data.assertedRelations.map(row => [row.id,row]));
  const allEdges = [];
  const edgeByKey = new Map();
  const predicateLabels = new Map();
  let predicateOptionsReady = false;
  const state = {width:1,height:1,dpr:1,view:{x:0,y:0,k:1},activeReleases:new Set(releaseById.keys()),layers:{asserted:true,projection:false,derived:true},showAssignments:false,ring:"",predicate:"",renderLimit:1,renderedNodes:[],renderedEdges:[],matches:new Set(),query:"",searchRows:[],searchVisible:0,searchOffset:0,searchHasMore:false,searchLoading:false,searchMode:"local",selected:null,inspectorReturn:null,hover:null,panning:false,drag:null,animation:null};
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const short = value => { const text=String(value); const hash=text.lastIndexOf("#"); return hash>=0?text.slice(hash+1):text.replace(/\/$/,"").split(/[/:]/).pop(); };
  const format = value => new Intl.NumberFormat("en-US").format(value);
  const hash = value => { let result=2166136261; for(const char of String(value)){result^=char.codePointAt(0);result=Math.imul(result,16777619);} return result>>>0; };
  const searchText = node => [node.label,node.id,node.release,...node.rings,...(node.detail?.labels||[]).map(row=>row.value),...(node.detail?.notations||[]),...(node.detail?.identifiers||[]).flatMap(row=>[row.value,row.schemeLabel])].join(" ").toLocaleLowerCase("en-US");
  function ensureNode(id,label,release="",ring="",detail=null,isSource=false){let node=nodeById.get(id);if(!node){node={id,label:label||short(id),release,ring,rings:new Set(ring?[ring]:[]),detail,isSource,hasSummary:false,x:0,y:0,tx:0,ty:0,degree:0};nodeById.set(id,node);nodes.push(node);}else{if(!node.release&&release)node.release=release;if(ring){node.rings.add(ring);if(!node.ring)node.ring=ring;}if(detail)node.detail=detail;if(label&&node.label===short(node.id))node.label=label;}return node;}
  data.resourceIndex.forEach(row=>{const node=ensureNode(row.id,row.displayLabel,row.release,row.semanticRing,null,false);node.hasSummary=true;});
  data.resources.forEach(row=>{const node=ensureNode(row.id,row.displayLabel,row.release,row.semanticRing,row,false);node.hasSummary=true;});
  function edgeFrom(row,layer){const sourceRelease=row.sourceRelease||"";const targetRelease=row.targetRelease||"";const rings=row.semanticRings||[row.semanticRing].filter(Boolean);const sourceRing=row.sourceRing||row.semanticRing||"";const targetRing=row.targetRing||row.semanticRing||"";ensureNode(row.subject,row.subjectLabel,sourceRelease,sourceRing,null,row.kind==="sourceAssignment");ensureNode(row.object,row.objectLabel,targetRelease,targetRing);return {...row,semanticRings:rings,layer,color:layerColors[layer]};}
  function addEdge(row,layer){const key=`${layer}|${row.id}`,edge=edgeFrom(row,layer),existing=edgeByKey.get(key);if(existing){Object.assign(existing,edge);if(layer==="asserted")assertedById.set(row.id,row);return existing;}edgeByKey.set(key,edge);allEdges.push(edge);if(layer==="asserted")assertedById.set(row.id,row);if(!predicateLabels.has(row.predicate)){predicateLabels.set(row.predicate,row.predicateLabel);if(predicateOptionsReady){const option=document.createElement("option");option.value=row.predicate;option.textContent=row.predicateLabel;predicateFilter.append(option);}}return edge;}
  data.assertedRelations.forEach(row=>addEdge(row,"asserted"));
  data.projectedRelations.forEach(row=>addEdge(row,"projection"));
  data.derivedRelations.forEach(row=>addEdge(row,"derived"));
  const ringLabels={subject:"Subject",entity:"Entity",value:"Value",legalIdentity:"Legal identity"};
  const ringCounts=data.coverage.resourcesByRing||{};
  const rings=[...new Set([...Object.keys(ringCounts),...nodes.flatMap(node=>[...node.rings])])].sort((a,b)=>(ringLabels[a]||a).localeCompare(ringLabels[b]||b,"en"));
  rings.forEach(value=>{const option=document.createElement("option");option.value=value;option.textContent=`${ringLabels[value]||value} · ${format(ringCounts[value]||0)}`;ringFilter.append(option);});
  const predicates=[...predicateLabels.entries()].sort((a,b)=>a[1].localeCompare(b[1],"en"));
  predicates.forEach(([value,label])=>{const option=document.createElement("option");option.value=value;option.textContent=label;predicateFilter.append(option);});
  predicateOptionsReady=true;
  const shardPayloads=new Map(),recordCache=new Map(),recordShardPromises=new Map(),loadedCatalogShards=new Set(),loadedReleaseResources=new Set(),releaseResourcePromises=new Map(),loadedReleaseGraphs=new Set(),releaseGraphPromises=new Map();
  let fullIndex=null,fullIndexPromise=null,catalogRefs=[],catalogCursor=0,searchEpoch=0;
  const rdf={
    type:"http://www.w3.org/1999/02/22-rdf-syntax-ns#type",subject:"http://www.w3.org/1999/02/22-rdf-syntax-ns#subject",predicate:"http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate",object:"http://www.w3.org/1999/02/22-rdf-syntax-ns#object",
    atlas:"https://refspec.org/ns/atlas/v3#",rkaf:"https://rulespec.org/ns/v1#",skosxl:"http://www.w3.org/2008/05/skos-xl#"
  };
  const textEncoder=new TextEncoder(),textDecoder=new TextDecoder("utf-8",{fatal:true});
  /* atlas-verified-shard-load:start */
  function hex(bytes){return [...bytes].map(value=>value.toString(16).padStart(2,"0")).join("");}
  async function sha256Bytes(bytes){return `sha256:${hex(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)))}`;}
  function shardCacheKey(ref){return `${ref.transport.digest}|${ref.content.digest}`;}
  async function decompressGzip(bytes){
    if(typeof DecompressionStream!=="function")throw new Error("This browser cannot decompress verified Atlas shards");
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).arrayBuffer();
  }
  async function fetchVerifiedShard(ref){
    if(ref.transport?.compression!=="gzip"||ref.content?.mediaType!=="application/json")throw new Error("Shard receipt uses an unsupported transport or content type");
    const cacheKey=shardCacheKey(ref);
    if(shardPayloads.has(cacheKey))return shardPayloads.get(cacheKey);
    const response=await fetch(ref.url,{cache:"force-cache",credentials:"same-origin"});
    if(!response.ok)throw new Error(`Shard request failed (${response.status})`);
    const transportBytes=await response.arrayBuffer();
    if(transportBytes.byteLength!==ref.transport.byteLength)throw new Error("Shard transport byte length does not match its pin");
    const observedTransportDigest=await sha256Bytes(transportBytes);
    if(observedTransportDigest!==ref.transport.digest)throw new Error("Shard transport digest does not match its pin");
    const contentBytes=await decompressGzip(transportBytes);
    if(contentBytes.byteLength!==ref.content.byteLength)throw new Error("Shard content byte length does not match its pin");
    const observedContentDigest=await sha256Bytes(contentBytes);
    if(observedContentDigest!==ref.content.digest)throw new Error("Shard content digest does not match its pin");
    const payload=JSON.parse(textDecoder.decode(contentBytes));
    if(payload.manifestDigest!==data.distribution.manifestDigest)throw new Error("Shard belongs to another Atlas distribution");
    shardPayloads.set(cacheKey,payload);
    return payload;
  }
  /* atlas-verified-shard-load:end */
  async function loadFullIndex(){
    if(fullIndex)return fullIndex;
    if(!fullIndexPromise)fullIndexPromise=(async()=>{
      const index=await fetchVerifiedShard(fullBundle.index);
      if(index.type!=="AtlasExplorerStaticShardIndex"||index.version!=="2"||index.schema!==fullBundle.schema||index.builderRecipe!==fullBundle.builderRecipe||index.assertedInventoryDigest!==fullBundle.assertedInventoryDigest||index.assertedInventoryDigest!==data.distribution.assertedInventoryDigest||index.counts.resources!==data.summary.availableResources)throw new Error("Static shard index identity or counts differ");
      fullIndex=index;
      catalogRefs=Object.values(index.catalog.shards).flat().sort((a,b)=>a.key.localeCompare(b.key,"en")||a.firstLabel.localeCompare(b.firstLabel,"en")||a.transport.digest.localeCompare(b.transport.digest));
      return index;
    })();
    return fullIndexPromise;
  }
  async function recordPrefix(id,length){const digest=await crypto.subtle.digest("SHA-256",textEncoder.encode(id));return hex(new Uint8Array(digest)).slice(0,length);}
  async function loadRecord(id){
    if(recordCache.has(id))return recordCache.get(id);
    const index=await loadFullIndex(),prefix=await recordPrefix(id,index.records.prefixLength),ref=index.records.shards[prefix];
    if(!ref)throw new Error(`No static record shard covers ${id}`);
    const cacheKey=shardCacheKey(ref);if(!recordShardPromises.has(cacheKey))recordShardPromises.set(cacheKey,(async()=>{const shard=await fetchVerifiedShard(ref);if(shard.type!=="AtlasExplorerStaticShard"||shard.version!=="2"||shard.kind!=="records"||shard.key!==prefix)throw new Error("Record shard identity differs");shard.records.forEach(record=>recordCache.set(record.id,record));return shard;})());
    await recordShardPromises.get(cacheKey);
    const record=recordCache.get(id);if(!record)throw new Error(`Static record shard omits ${id}`);return record;
  }
  function rawObject(token){
    if(token.startsWith("<")&&token.endsWith(">"))return {type:"iri",value:token.slice(1,-1)};
    if(!token.startsWith('"'))throw new Error("Unsupported RDF object token");
    let escaped=false,end=-1;for(let index=1;index<token.length;index++){const char=token[index];if(char==='"'&&!escaped){end=index;break;}if(char==='\\'&&!escaped)escaped=true;else escaped=false;}
    if(end<0)throw new Error("Malformed RDF literal token");
    const result={type:"literal",value:JSON.parse(token.slice(0,end+1))},suffix=token.slice(end+1);
    if(suffix.startsWith("@"))result.language=suffix.slice(1);else if(suffix.startsWith("^^<")&&suffix.endsWith(">"))result.datatype=suffix.slice(3,-1);else if(suffix)throw new Error("Malformed RDF literal suffix");
    return result;
  }
  function factObjects(record,predicate,role="asserted"){return (record.facts||[]).filter(fact=>fact[0]===predicate&&fact[2]===role).map(fact=>rawObject(fact[1]));}
  function iriFacts(record,predicate,role="asserted"){return factObjects(record,predicate,role).filter(value=>value.type==="iri").map(value=>value.value);}
  function literalFacts(record,predicate,role="asserted"){return factObjects(record,predicate,role).filter(value=>value.type==="literal");}
  function oneIri(record,predicate,role="asserted"){return iriFacts(record,predicate,role)[0]||"";}
  function oneLiteral(record,predicate,role="asserted"){return literalFacts(record,predicate,role)[0]?.value??"";}
  function recordTypes(record,role="asserted"){return new Set(iriFacts(record,rdf.type,role));}
  function summaryNode(summary){const node=ensureNode(summary.id,summary.displayLabel,summary.release,summary.ring,null,false);node.corpusSearchText=summary.searchText||summary.displayLabel;node.hasSummary=true;return node;}
  function normalizeSourceRecord(record){
    const native=oneLiteral(record,`${rdf.atlas}nativePayload`);let nativePayload={};try{nativePayload=native?JSON.parse(native):{};}catch{nativePayload={unparsed:true};}
    const row={id:record.id,sourceRelease:oneIri(record,`${rdf.atlas}inSourceRelease`),sourceLocator:oneIri(record,`${rdf.atlas}sourceLocator`),sourceDigest:oneLiteral(record,`${rdf.atlas}sourceDigest`),contentDigest:oneLiteral(record,`${rdf.atlas}contentDigest`),nativePayload,representsResources:iriFacts(record,`${rdf.atlas}representsResource`)};
    sourceById.set(row.id,row);return row;
  }
  async function normalizeIdentifier(id){const record=await loadRecord(id),sourceRecords=iriFacts(record,`${rdf.atlas}sourceRecord`);return {id,value:oneLiteral(record,`${rdf.atlas}identifierValue`),scheme:oneIri(record,`${rdf.atlas}identifierScheme`),schemeLabel:short(oneIri(record,`${rdf.atlas}identifierScheme`)),identifies:oneIri(record,`${rdf.atlas}identifies`),contentDigest:oneLiteral(record,`${rdf.atlas}contentDigest`),sourceRecordCount:sourceRecords.length,...(sourceRecords.length===1?{sourceRecord:sourceRecords[0]}:{})};}
  async function normalizeEvidence(id){
    const record=await loadRecord(id),sourceRecord=oneIri(record,`${rdf.atlas}evidenceSourceRecord`),source=normalizeSourceRecord(await loadRecord(sourceRecord));
    return {id,sourceRecord:source.id,sourceRecordContentDigest:source.contentDigest,sourceDigest:oneLiteral(record,`${rdf.atlas}evidenceSourceDigest`),decision:short(oneIri(record,`${rdf.rkaf}decision`)),evidenceRole:short(oneIri(record,`${rdf.rkaf}evidenceRole`)),attestedAt:oneLiteral(record,`${rdf.rkaf}attestedAt`),contentDigest:oneLiteral(record,`${rdf.atlas}contentDigest`),...(oneIri(record,`${rdf.rkaf}attestor`)?{attestor:oneIri(record,`${rdf.rkaf}attestor`)}:{})};
  }
  async function endpointLabel(id){try{return (await loadRecord(id)).summary?.displayLabel||short(id);}catch{return short(id);}}
  async function normalizeRelation(id){
    const record=await loadRecord(id),assertedTypes=recordTypes(record,"asserted"),projectionTypes=recordTypes(record,"projection"),derivedTypes=recordTypes(record,"derived");let types=assertedTypes,layer="asserted",subjectPredicate=rdf.subject,predicatePredicate=rdf.predicate,objectPredicate=rdf.object;
    if(projectionTypes.has(`${rdf.atlas}ProjectedRelation`)){types=projectionTypes;layer="projection";subjectPredicate=`${rdf.atlas}relationSubject`;predicatePredicate=`${rdf.atlas}relationPredicate`;objectPredicate=`${rdf.atlas}relationObject`;}
    else if(derivedTypes.has(`${rdf.atlas}DerivedRelation`)){types=derivedTypes;layer="derived";subjectPredicate=`${rdf.atlas}relationSubject`;predicatePredicate=`${rdf.atlas}relationPredicate`;objectPredicate=`${rdf.atlas}relationObject`;}
    const subject=oneIri(record,subjectPredicate,layer),predicate=oneIri(record,predicatePredicate,layer),object=oneIri(record,objectPredicate,layer);
    const semanticRing=short(oneIri(record,`${rdf.atlas}semanticRing`,layer)),sourceRing=short(oneIri(record,`${rdf.atlas}sourceRing`,layer)),targetRing=short(oneIri(record,`${rdf.atlas}targetRing`,layer));
    const kind=types.has(`${rdf.atlas}MappingAssertion`)?"mapping":types.has(`${rdf.atlas}NativeRelationAssertion`)?"native":types.has(`${rdf.atlas}SourceAssignment`)?"sourceAssignment":types.has(`${rdf.atlas}CrossRingRelationAssertion`)?"crossRing":layer;
    const status=short(oneIri(record,`${rdf.atlas}assertionStatus`));
    const evidence=layer==="asserted"?await Promise.all((record.evidenceBindings||[]).map(normalizeEvidence)):[];
    const row={id,kind,authority:layer==="asserted"?(status==="current"?"authoritative":"historicalEditorialRecord"):layer==="projection"?"reproducibleProjection":"nonAuthoritative",authoritative:layer==="asserted"&&status==="current",subject,subjectLabel:await endpointLabel(subject),predicate,predicateLabel:short(predicate),object,objectLabel:await endpointLabel(object),sourceRelease:oneIri(record,`${rdf.atlas}sourceRelease`)||oneIri(record,`${rdf.atlas}sourceRelease`,layer),targetRelease:oneIri(record,`${rdf.atlas}targetRelease`)||oneIri(record,`${rdf.atlas}targetRelease`,layer),...(semanticRing?{semanticRing,semanticRings:[semanticRing]}:{sourceRing,targetRing,semanticRings:[sourceRing,targetRing]}),...(status?{status}:{}),evidence};
    if(layer==="projection")row.supportingAssertions=iriFacts(record,`${rdf.atlas}supportingAssertion`,layer);if(layer==="derived"){row.derivedFromAssertions=iriFacts(record,`${rdf.atlas}derivedFromAssertion`,layer);row.rule=oneIri(record,`${rdf.atlas}appliedRule`,layer);row.engine=oneIri(record,`${rdf.atlas}reasoningEngine`,layer);}return {layer,row};
  }
  async function addRelationWithSupport(id){const relation=await normalizeRelation(id);addEdge(relation.row,relation.layer);const supporting=[...(relation.row.supportingAssertions||[]),...(relation.row.derivedFromAssertions||[])];for(const assertionId of supporting){const assertion=await normalizeRelation(assertionId);if(assertion.layer!=="asserted")throw new Error("A derived relation cites a non-asserted supporting record");addEdge(assertion.row,assertion.layer);}}
  async function hydrateEdge(edge){
    if(!fullMode||edge.hydrated)return;
    if(edge.hydrating)return edge.hydrating;
    edge.hydrating=(async()=>{try{const relation=await normalizeRelation(edge.id),hydrated=addEdge(relation.row,relation.layer);hydrated.hydrated=true;if(state.selected?.kind==="edge"&&state.selected.id===hydrated.id&&state.selected.layer===hydrated.layer)state.selected.edge=hydrated;renderInspector();draw();}
      catch(error){corpusMode.textContent=`Relation detail unavailable: ${String(error?.message||error)}`;corpusMode.classList.add("error");}
      finally{edge.hydrating=null;}})();
    return edge.hydrating;
  }
  async function hydrateNode(node,more=false){
    if(!fullMode)return;
    if(node.hydrating)return node.hydrating;
    node.hydrating=(async()=>{try{node.loading=true;renderInspector();const record=await loadRecord(node.id);if(record.summary){const identifiers=await Promise.all((record.identifiers||[]).map(normalizeIdentifier));const sourceRecords=iriFacts(record,`${rdf.atlas}sourceRecord`);for(const sourceId of sourceRecords){normalizeSourceRecord(await loadRecord(sourceId));}node.detail={id:record.id,resourceType:short([...recordTypes(record)].find(value=>value!==`${rdf.atlas}AtlasResource`)||"AtlasResource"),release:record.summary.release,scheme:oneIri(record,`${rdf.atlas}inScheme`),semanticRing:record.summary.ring,resourceProfile:short(oneIri(record,`${rdf.atlas}resourceProfile`)),displayLabel:record.summary.displayLabel,displayLabelRole:record.summary.displayLabelRole,labels:record.summary.labels,sourceRecords,contentDigest:oneLiteral(record,`${rdf.atlas}contentDigest`),notations:literalFacts(record,`${rdf.atlas}notation`).map(value=>value.value),definitions:literalFacts(record,`${rdf.atlas}definition`),notes:literalFacts(record,`${rdf.atlas}note`),identifiers};}
      node.relationIds=record.relations||[];const start=more?(node.loadedRelationCount||0):0,end=Math.min(node.relationIds.length,start+100);for(const relationId of node.relationIds.slice(start,end)){await addRelationWithSupport(relationId);}node.loadedRelationCount=end;node.loading=false;syncRenderCapacity();refresh(false);}
      catch(error){node.loading=false;node.loadError=String(error?.message||error);corpusMode.textContent=`Full-corpus detail error: ${node.loadError}`;corpusMode.classList.add("error");renderInspector();}})();try{await node.hydrating;}finally{node.hydrating=null;}}
  function selectedCatalogRef(){
    const activeReleases=activeVisibleReleases();if(!activeReleases.size)return null;
    for(let attempts=0;attempts<catalogRefs.length;attempts++){const ref=catalogRefs[catalogCursor%catalogRefs.length];catalogCursor++;if(loadedCatalogShards.has(shardCacheKey(ref)))continue;if(state.ring&&!ref.rings.includes(state.ring))continue;if(![...activeReleases].some(release=>ref.releases.includes(release)))continue;return ref;}return null;
  }
  async function loadReleaseResources(release){
    if(!fullMode||loadedReleaseResources.has(release))return;
    if(releaseResourcePromises.has(release))return releaseResourcePromises.get(release);
    const promise=(async()=>{
      const index=await loadFullIndex(),collection=index.releaseResources;
      if(!collection){loadedReleaseResources.add(release);return;}
      const refs=collection.shards?.[release]||[],total=collection.counts?.[release]||0,row=releaseById.get(release);let loaded=0;
      for(const ref of refs){
        if(activeVisibleReleases().has(release))corpusMode.textContent=`Loading ${releaseLabel(row||{id:release})} · ${format(loaded)} of ${format(total)} concepts…`;
        const shard=await fetchVerifiedShard(ref);
        if(shard.type!=="AtlasExplorerStaticShard"||shard.version!=="2"||shard.kind!=="releaseResources"||shard.release!==release||ref.release!==release)throw new Error("Release resource shard identity differs");
        for(const entry of shard.entries){if(entry.release!==release)throw new Error("Release resource belongs to another release");summaryNode(entry);}
        loaded+=shard.entries.length;
      }
      if(loaded!==total)throw new Error("Release resource count differs");
      if(Number.isInteger(row?.memberCount)&&loaded!==row.memberCount)throw new Error("Release resource count differs from the Atlas release");
      loadedReleaseResources.add(release);
    })();
    releaseResourcePromises.set(release,promise);try{await promise;}finally{releaseResourcePromises.delete(release);}
  }
  async function loadReleaseGraph(release){
    if(!fullMode||loadedReleaseGraphs.has(release))return;
    if(releaseGraphPromises.has(release))return releaseGraphPromises.get(release);
    const promise=(async()=>{await loadReleaseResources(release);const index=await loadFullIndex(),refs=index.releaseGraphs?.shards?.[release]||[],total=index.releaseGraphs?.counts?.[release]||0,row=releaseById.get(release);if(row)row.relationCount=total;let loaded=0;for(const ref of refs){if(activeVisibleReleases().has(release))corpusMode.textContent=`Loading ${releaseLabel(row||{id:release})} graph · ${format(loaded)} of ${format(total)} relations…`;const shard=await fetchVerifiedShard(ref);if(shard.type!=="AtlasExplorerStaticShard"||shard.version!=="2"||shard.kind!=="releaseGraph"||shard.release!==release||ref.release!==release)throw new Error("Release graph shard identity differs");for(const entry of shard.entries){addEdge({...entry,subjectLabel:entry.subjectLabel||nodeById.get(entry.subject)?.label||short(entry.subject),objectLabel:entry.objectLabel||nodeById.get(entry.object)?.label||short(entry.object)},entry.layer);}loaded+=shard.entries.length;}if(loaded!==total)throw new Error("Release graph relation count differs");loadedReleaseGraphs.add(release);if(activeVisibleReleases().has(release)){corpusMode.textContent=`${releaseLabel(row||{id:release})} · complete graph · ${format(total)} relations`;corpusMode.classList.remove("error");}})();
    releaseGraphPromises.set(release,promise);try{await promise;}finally{releaseGraphPromises.delete(release);}
  }
  let selectedReleaseLoadPromise=null;
  async function loadSelectedReleaseGraphs(){
    if(!fullMode||!activeVisibleReleases().size)return;
    if(selectedReleaseLoadPromise)return selectedReleaseLoadPromise;
    selectedReleaseLoadPromise=(async()=>{
      try{
        while(true){
          const pending=[...activeVisibleReleases()].filter(release=>!loadedReleaseGraphs.has(release));
          if(!pending.length)break;
          let cursor=0;
          const worker=async()=>{while(cursor<pending.length){const release=pending[cursor++];if(activeVisibleReleases().has(release))await loadReleaseGraph(release);}};
          await Promise.all(Array.from({length:Math.min(4,pending.length)},worker));
        }
        if(!fullIndex?.releaseResources)await loadCatalogToLimit();
        const active=activeVisibleReleases();syncRenderCapacity();refresh(true,state.renderLimit<=5000);
        if(!active.size)corpusMode.textContent="Select at least one Atlas release.";
        else if(active.size===1){const release=releaseById.get([...active][0]);corpusMode.textContent=`${releaseLabel(release)} · complete graph · ${format(release.relationCount||0)} relations`;}
        else corpusMode.textContent=`${format(active.size)} selected releases · complete graphs`;
        corpusMode.classList.remove("error");
      }
      catch(error){corpusMode.textContent=`Release graph unavailable: ${String(error?.message||error)}`;corpusMode.classList.add("error");}
      finally{selectedReleaseLoadPromise=null;}
    })();
    return selectedReleaseLoadPromise;
  }
  let catalogLoadPromise=null;
  async function loadCatalogToLimit(){
    if(!fullMode)return;
    if(catalogLoadPromise)return catalogLoadPromise;
    catalogLoadPromise=(async()=>{try{if(!activeVisibleReleases().size){corpusMode.textContent="Select at least one Atlas release.";return;}await loadFullIndex();const target=visibleResourceTarget();let loaded=visibleLoadedResourceCount();while(loaded<target){const ref=selectedCatalogRef();if(!ref){corpusMode.textContent="All matching catalog pages are loaded.";break;}corpusMode.textContent=`Loading verified resources · ${format(loaded)} of ${format(target)} ready…`;const shard=await fetchVerifiedShard(ref);if(shard.version!=="2"||shard.kind!=="catalog"||shard.key!==ref.key)throw new Error("Catalog shard identity differs");loadedCatalogShards.add(shardCacheKey(ref));shard.entries.forEach(summaryNode);loaded=visibleLoadedResourceCount();refresh(false,false);}syncRenderCapacity();corpusMode.textContent=`Full corpus · verified shards · ${format(fullBundle.counts.resources)} resources`;corpusMode.classList.remove("error");refresh(true);}
      catch(error){corpusMode.textContent=`Full corpus unavailable: ${String(error?.message||error)}. Bounded fallback remains.`;corpusMode.classList.add("error");}
      finally{catalogLoadPromise=null;}})();
    return catalogLoadPromise;
  }
  const loadedResourceCount=()=>Math.max(1,nodes.filter(node=>!node.isSource).length);
  let maxLimit=fullMode?Math.max(1,fullBundle.counts.resources):loadedResourceCount();state.renderLimit=Math.min(900,maxLimit);let requestedRenderLimit=state.renderLimit;
  const range=document.getElementById("render-limit-range"), number=document.getElementById("render-limit-number");range.max=number.max=String(maxLimit);range.value=number.value=String(state.renderLimit);
  function syncRenderCapacity(){const selectedCapacity=[...activeVisibleReleases()].reduce((total,id)=>total+(releaseById.get(id)?.memberCount||0),0);maxLimit=fullMode?Math.max(1,Math.min(fullBundle.counts.resources,selectedCapacity||1)):loadedResourceCount();range.max=number.max=String(maxLimit);state.renderLimit=Math.min(maxLimit,Math.max(1,requestedRenderLimit));range.value=number.value=String(state.renderLimit);document.getElementById("render-limit-label").textContent=`${format(state.renderLimit)} of ${format(maxLimit)}`;}
  function releaseLabel(row){return row.title||row.identifier||short(row.id);}
  /* atlas-release-filter-controls:start */
  function releaseMatchesRing(row){return !state.ring||row.semanticRing===state.ring;}
  function visibleReleaseRows(){return [...releaseById.values()].filter(releaseMatchesRing);}
  function activeVisibleReleases(){return new Set(visibleReleaseRows().filter(row=>state.activeReleases.has(row.id)).map(row=>row.id));}
  function visibleResourceTarget(){const active=activeVisibleReleases(),available=[...active].reduce((total,id)=>total+(releaseById.get(id)?.memberCount||0),0);return Math.min(state.renderLimit,available);}
  function visibleLoadedResourceCount(){const active=activeVisibleReleases();return nodes.filter(node=>node.hasSummary&&!node.isSource&&active.has(node.release)&&(!state.ring||node.rings.has(state.ring))).length;}
  function renderReleaseFilters(){const root=document.getElementById("release-filters"),rows=visibleReleaseRows();root.replaceChildren();rows.forEach(row=>{const label=document.createElement("label"),checked=state.activeReleases.has(row.id)?" checked":"";label.className="filter";label.innerHTML=`<input type="checkbox"${checked} data-release="${esc(row.id)}"><span class="swatch" style="--swatch:${row.color}"></span><span class="label">${esc(releaseLabel(row))}</span><small>${format(row.memberCount||0)}</small>`;root.append(label);});root.querySelectorAll("input").forEach(input=>input.addEventListener("change",()=>{input.checked?state.activeReleases.add(input.dataset.release):state.activeReleases.delete(input.dataset.release);syncRenderCapacity();refresh(true,state.renderLimit<=5000);void loadSelectedReleaseGraphs();}));document.getElementById("select-no-releases").disabled=!rows.length;}
  function selectNoReleases(){visibleReleaseRows().forEach(row=>state.activeReleases.delete(row.id));state.selected=null;state.inspectorReturn=null;renderReleaseFilters();syncRenderCapacity();if(search.value)void renderSearch();else refresh(true);}
  /* atlas-release-filter-controls:end */
  /* atlas-edge-ring-filter:start */
  function edgeMatchesRing(edge,ring){return !ring||(edge.semanticRings||[edge.semanticRing].filter(Boolean)).includes(ring);}
  /* atlas-edge-ring-filter:end */
  function layerEnabled(edge){if(edge.layer==="asserted"&&!state.layers.asserted)return false;if(edge.layer==="projection"&&!state.layers.projection)return false;if(edge.layer==="derived"&&!state.layers.derived)return false;if(edge.kind==="sourceAssignment"&&!state.showAssignments)return false;if(!edgeMatchesRing(edge,state.ring))return false;return !state.predicate||edge.predicate===state.predicate;}
  function releaseEnabled(node){return !node.release||!releaseById.has(node.release)||state.activeReleases.has(node.release);}
  function computeGraph(){nodes.forEach(node=>{node.degree=0;});const eligibleEdges=allEdges.filter(edge=>{if(!layerEnabled(edge))return false;const source=nodeById.get(edge.subject),target=nodeById.get(edge.object);if(!source||!target||!releaseEnabled(source)||!releaseEnabled(target))return false;source.degree++;target.degree++;return true;});const selectedNeighbors=selectedNodeNeighborIds(state.selected,eligibleEdges);const ringEndpointIds=new Set(eligibleEdges.flatMap(edge=>[edge.subject,edge.object]));const candidates=nodes.filter(node=>(!state.ring||node.rings.has(state.ring)||ringEndpointIds.has(node.id))&&releaseEnabled(node)&&(!node.isSource||state.showAssignments));candidates.sort((a,b)=>(state.matches.has(b.id)?1:0)-(state.matches.has(a.id)?1:0)||(state.selected?.kind==="node"&&state.selected.id===b.id?1:0)-(state.selected?.kind==="node"&&state.selected.id===a.id?1:0)||(selectedNeighbors.has(b.id)?1:0)-(selectedNeighbors.has(a.id)?1:0)||b.degree-a.degree||a.label.localeCompare(b.label,"en")||a.id.localeCompare(b.id));state.renderedNodes=candidates.slice(0,state.renderLimit);const ids=new Set(state.renderedNodes.map(node=>node.id));state.renderedEdges=eligibleEdges.filter(edge=>ids.has(edge.subject)&&ids.has(edge.object));}
  function layout(animate=true){const groups=new Map();state.renderedNodes.forEach(node=>{const key=node.release||"unreleased";if(!groups.has(key))groups.set(key,[]);groups.get(key).push(node);});const ordered=[...groups.entries()].sort((a,b)=>a[0].localeCompare(b[0]));const orbit=Math.max(220,Math.sqrt(state.renderedNodes.length)*28);const golden=2.399963229728653;ordered.forEach(([key,group],groupIndex)=>{group.sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id));const angle=(Math.PI*2*groupIndex/Math.max(1,ordered.length))+((hash(key)%1000)/1000)*.3;const cx=ordered.length===1?0:Math.cos(angle)*orbit,cy=ordered.length===1?0:Math.sin(angle)*orbit;group.forEach((node,index)=>{const theta=index*golden+(hash(node.id)%628)/100;const radius=18*Math.sqrt(index);node.sx=Number.isFinite(node.x)?node.x:cx;node.sy=Number.isFinite(node.y)?node.y:cy;node.tx=cx+Math.cos(theta)*radius;node.ty=cy+Math.sin(theta)*radius;});});if(!animate||matchMedia("(prefers-reduced-motion: reduce)").matches){state.renderedNodes.forEach(node=>{node.x=node.tx;node.y=node.ty;});draw();return;}const started=performance.now();if(state.animation)cancelAnimationFrame(state.animation);const tick=now=>{const t=Math.min(1,(now-started)/360),ease=1-Math.pow(1-t,3);state.renderedNodes.forEach(node=>{node.x=node.sx+(node.tx-node.sx)*ease;node.y=node.sy+(node.ty-node.sy)*ease;});draw();if(t<1)state.animation=requestAnimationFrame(tick);};state.animation=requestAnimationFrame(tick);}
  function bounds(){if(!state.renderedNodes.length)return{minX:-1,maxX:1,minY:-1,maxY:1};return{minX:Math.min(...state.renderedNodes.map(n=>n.x)),maxX:Math.max(...state.renderedNodes.map(n=>n.x)),minY:Math.min(...state.renderedNodes.map(n=>n.y)),maxY:Math.max(...state.renderedNodes.map(n=>n.y))};}
  function fitView(){const box=bounds(),padding=80,width=Math.max(1,box.maxX-box.minX),height=Math.max(1,box.maxY-box.minY);state.view.k=Math.max(.08,Math.min(2.8,Math.min((state.width-padding*2)/width,(state.height-padding*2)/height)));state.view.x=state.width/2-(box.minX+box.maxX)/2*state.view.k;state.view.y=state.height/2-(box.minY+box.maxY)/2*state.view.k;draw();}
  function selectedReleaseRelationTotal(){const active=activeVisibleReleases();if(active.size!==1)return null;const release=releaseById.get([...active][0]);return Number.isInteger(release?.relationCount)?release.relationCount:null;}
  function refresh(fit=false,animate=true){computeGraph();const useAnimation=animate&&state.renderedNodes.length<=5000;layout(useAnimation);renderInspector();const total=selectedReleaseRelationTotal(),releaseTotal=total===null?"":` · ${format(total)} in selected release`;document.getElementById("graph-status").textContent=`${format(state.renderedNodes.length)} nodes · ${format(state.renderedEdges.length)} visible relations${releaseTotal}`;document.getElementById("render-limit-label").textContent=`${format(state.renderLimit)} of ${format(maxLimit)}`;if(fit)setTimeout(fitView,useAnimation?380:0);}
  function relationSelected(edge){return state.selected?.kind==="edge"&&state.selected.id===edge.id&&state.selected.layer===edge.layer;}
  function nodeConnected(node,edge){return edge.subject===node.id||edge.object===node.id;}
  /* atlas-selected-node-neighbors:start */
  function selectedNodeNeighborIds(selection,edges){const neighbors=new Set();if(selection?.kind!=="node")return neighbors;neighbors.add(selection.id);edges.forEach(edge=>{if(edge.subject===selection.id)neighbors.add(edge.object);else if(edge.object===selection.id)neighbors.add(edge.subject);});return neighbors;}
  /* atlas-selected-node-neighbors:end */
  function drawArrow(source,target,color,alpha,lineWidth){const angle=Math.atan2(target.y-source.y,target.x-source.x),radius=8/state.view.k,tipX=target.x-Math.cos(angle)*radius,tipY=target.y-Math.sin(angle)*radius,len=7/state.view.k,w=3.5/state.view.k;ctx.beginPath();ctx.moveTo(tipX,tipY);ctx.lineTo(tipX-Math.cos(angle)*len+Math.sin(angle)*w,tipY-Math.sin(angle)*len-Math.cos(angle)*w);ctx.lineTo(tipX-Math.cos(angle)*len-Math.sin(angle)*w,tipY-Math.sin(angle)*len+Math.cos(angle)*w);ctx.closePath();ctx.globalAlpha=alpha;ctx.fillStyle=color;ctx.fill();ctx.globalAlpha=1;}
  function drawEdge(edge){const source=nodeById.get(edge.subject),target=nodeById.get(edge.object);if(!source||!target)return;const selected=relationSelected(edge),near=state.selected?.kind==="node"&&(nodeConnected(nodeById.get(state.selected.id),edge)),dim=state.selected&&!selected&&!near;const alpha=selected?.98:near?.82:dim?.08:edge.layer==="projection"?.3:.42;const offset=edge.layer==="projection"?3/state.view.k:0,dx=target.x-source.x,dy=target.y-source.y,length=Math.max(1,Math.hypot(dx,dy)),ox=-dy/length*offset,oy=dx/length*offset;ctx.beginPath();ctx.moveTo(source.x+ox,source.y+oy);ctx.lineTo(target.x+ox,target.y+oy);ctx.strokeStyle=edge.kind==="sourceAssignment"?"#8b9792":edge.color;ctx.globalAlpha=alpha;ctx.lineWidth=(selected?2.8:edge.layer==="asserted"?1.35:1.6)/state.view.k;ctx.setLineDash(edge.layer==="projection"?[7/state.view.k,5/state.view.k]:edge.layer==="derived"?[2/state.view.k,4/state.view.k]:[]);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;drawArrow({x:source.x+ox,y:source.y+oy},{x:target.x+ox,y:target.y+oy},edge.kind==="sourceAssignment"?"#8b9792":edge.color,alpha,ctx.lineWidth);}
  function nodeColor(node){return releaseById.get(node.release)?.color||"#a8b8b1";}
  function drawNode(node,selectedNeighbors){const selected=state.selected?.kind==="node"&&state.selected.id===node.id,hovered=state.hover===node.id,connected=state.selected?.kind==="edge"&&(state.selected.edge.subject===node.id||state.selected.edge.object===node.id),dim=state.selected&&!selected&&!connected&&!selectedNeighbors.has(node.id);ctx.globalAlpha=dim?.18:1;const radius=(selected?8:node.degree>8?6.5:5)/state.view.k;if(selected||hovered){ctx.beginPath();ctx.arc(node.x,node.y,radius+5/state.view.k,0,Math.PI*2);ctx.fillStyle=selected?"rgba(112,210,155,.2)":"rgba(153,221,208,.14)";ctx.fill();}ctx.beginPath();if(node.isSource){ctx.rect(node.x-radius,node.y-radius,radius*2,radius*2);}else{ctx.arc(node.x,node.y,radius,0,Math.PI*2);}ctx.fillStyle=nodeColor(node);ctx.fill();ctx.strokeStyle=selected?"#fff":"rgba(4,8,7,.85)";ctx.lineWidth=(selected?2:1)/state.view.k;ctx.stroke();ctx.globalAlpha=1;if(selected||hovered||state.matches.has(node.id)||(state.view.k>1.15&&state.renderedNodes.length<260)){ctx.font=`${11/state.view.k}px ui-sans-serif,system-ui`;ctx.textBaseline="middle";const x=node.x+radius+5/state.view.k,width=ctx.measureText(node.label).width;ctx.fillStyle="rgba(5,10,8,.88)";ctx.fillRect(x-2/state.view.k,node.y-8/state.view.k,width+4/state.view.k,16/state.view.k);ctx.fillStyle=nodeColor(node);ctx.fillText(node.label,x,node.y);}}
  function draw(){const selectedNeighbors=selectedNodeNeighborIds(state.selected,state.renderedEdges);ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.setTransform(state.dpr*state.view.k,0,0,state.dpr*state.view.k,state.dpr*state.view.x,state.dpr*state.view.y);state.renderedEdges.filter(edge=>!relationSelected(edge)).forEach(drawEdge);state.renderedEdges.filter(relationSelected).forEach(drawEdge);state.renderedNodes.filter(node=>state.selected?.id!==node.id).forEach(node=>drawNode(node,selectedNeighbors));const selected=state.selected?.kind==="node"?nodeById.get(state.selected.id):null;if(selected)drawNode(selected,selectedNeighbors);}
  function screenToWorld(x,y){return{x:(x-state.view.x)/state.view.k,y:(y-state.view.y)/state.view.k};}
  function hitNode(clientX,clientY){const rect=canvas.getBoundingClientRect(),point=screenToWorld(clientX-rect.left,clientY-rect.top);let best=null,distance=Infinity;state.renderedNodes.forEach(node=>{const d=Math.hypot(node.x-point.x,node.y-point.y);if(d<12/state.view.k&&d<distance){best=node;distance=d;}});return best;}
  function segmentDistance(point,a,b){const dx=b.x-a.x,dy=b.y-a.y,l2=dx*dx+dy*dy;if(!l2)return Math.hypot(point.x-a.x,point.y-a.y);const t=Math.max(0,Math.min(1,((point.x-a.x)*dx+(point.y-a.y)*dy)/l2));return Math.hypot(point.x-(a.x+t*dx),point.y-(a.y+t*dy));}
  function hitEdge(clientX,clientY){const rect=canvas.getBoundingClientRect(),point=screenToWorld(clientX-rect.left,clientY-rect.top);let best=null,distance=Infinity;state.renderedEdges.forEach(edge=>{const a=nodeById.get(edge.subject),b=nodeById.get(edge.object),d=segmentDistance(point,a,b);if(d<7/state.view.k&&d<distance){best=edge;distance=d;}});return best;}
  function zoomAt(factor,x=state.width/2,y=state.height/2){const before=screenToWorld(x,y);state.view.k=Math.max(.06,Math.min(8,state.view.k*factor));state.view.x=x-before.x*state.view.k;state.view.y=y-before.y*state.view.k;draw();}
  function sourceDetails(ids){return ids.map(id=>sourceById.get(id)).filter(Boolean);}
  function identifierBrief(detail){
    const identifiers=detail?.identifiers||[];
    if(!identifiers.length)return "";
    const rows=identifiers.map(identifier=>{const source=identifier.sourceRecord?sourceById.get(identifier.sourceRecord):null;const sourceText=source?`<small>Source: ${esc(friendlySource(source))}</small>`:"";return `<div class="evidence-row"><b>${esc(identifier.value)}</b><p>Scheme / authority: ${esc(identifier.schemeLabel)}</p>${sourceText}</div>`;}).join("");
    return `<section class="supporting"><h3>Identifiers</h3><div class="evidence-list">${rows}</div></section>`;
  }
  function friendlySource(record){
    if(!record)return "Pinned source record";
    const token=record.nativePayload?.sourceIdentity?.namespaceToken;
    const tokenNames={"loc-lst":"Library of Congress Legislative Subject Terms","loc-cgpa":"Library of Congress Policy Areas","icpsr-subject-thesaurus":"ICPSR Subject Thesaurus"};
    if(tokenNames[token])return tokenNames[token];
    const locator=String(record.sourceLocator||"").toLocaleLowerCase("en-US");
    if(locator.includes("elsst"))return "ELSST";
    if(locator.includes("icpsr"))return "ICPSR Subject Thesaurus";
    if(locator.includes("federal-register")||locator.includes("federalregister"))return "Federal Register Thesaurus";
    if(locator.includes("congress.gov"))return "Congress.gov / CRS";
    const release=sourceReleaseById.get(record.sourceRelease);
    return release?.title||release?.identifier||short(record.sourceRelease||record.sourceLocator||"source record");
  }
  function warrantLabel(method){
    return ({
      officialSourceMetadata:{title:"Publisher supplied",reason:"Supplied directly by the publisher."},
      structuralEvidence:{title:"Fixed-rule transformation",reason:"Atlas applied a fixed rule to publisher data."},
      reviewedAuthorityChain:{title:"Two-model agreement",reason:"Two independent models agreed."},
      formalAdoptionEvent:{title:"Operator adopted",reason:"An operator accepted it."},
      textualEvidence:{title:"Human approved",reason:"A human reviewer approved it."},
      authorityCitation:{title:"Pipeline approved",reason:"A trusted pipeline approved it."}
    })[method]||{title:String(method||"Reviewed"),reason:"The review method is recorded."};
  }
  /* atlas-mapping-provenance:start */
  function mappingContext(edge){
    if(edge.kind!=="mapping")return null;
    for(const evidence of edge.evidence||[]){
      const record=sourceById.get(evidence.sourceRecord),payload=record?.nativePayload;
      if(payload?.publisherAlignmentVersion)return {evidence,payload};
    }
    return null;
  }
  function mappingEvidenceBrief(edge){
    const context=mappingContext(edge);
    if(!context)return "";
    const {evidence,payload}=context;
    const alignmentIssued=payload.publisherAlignmentIssued?` · issued ${payload.publisherAlignmentIssued}`:"";
    const euroVoc=payload.publisherEuroVocVersion?`EuroVoc ${payload.publisherEuroVocVersion}`:"EuroVoc version not stated";
    const lcsh=payload.publisherLcshRelease==="unspecifiedByPublisher"?"LCSH release not stated":`LCSH ${payload.publisherLcshRelease||"release not stated"}`;
    const method=evidence.evidenceRole==="formalAdoptionEvent"?"Operator adoption":warrantLabel(evidence.evidenceRole).title;
    const adoptionDate=String(evidence.attestedAt||"").slice(0,10)||"date not recorded";
    const caveat=payload.currentMetadataRequalifiesIndividualPairs===false?`<p class="supporting-intro">EuroVoc ${esc(payload.currentEuroVocRelease||"current")} aggregate metadata does not re-review individual pairs.</p>`:"";
    return `<section class="supporting"><h4>Mapping source</h4><div class="evidence-list"><div class="evidence-row"><b>Official alignment ${esc(payload.publisherAlignmentVersion)}${esc(alignmentIssued)}</b><p>${esc(euroVoc)} · ${esc(lcsh)}</p></div><div class="evidence-row"><b>Atlas decision ${esc(adoptionDate)} · ${esc(method)}</b><p>Exact Atlas releases</p><p class="iri">${esc(edge.sourceRelease)} → ${esc(edge.targetRelease)}</p></div></div>${caveat}</section>`;
  }
  /* atlas-mapping-provenance:end */
  function relationMeaning(edge){
    const subject=nodeById.get(edge.subject)?.label||edge.subjectLabel, object=nodeById.get(edge.object)?.label||edge.objectLabel;
    if(edge.kind==="sourceAssignment")return `This source record contributed ${object}. It is provenance, not a topic relation.`;
    return ({
      broader:`${subject} is narrower than ${object}.`,
      narrower:`${object} is narrower than ${subject}.`,
      related:`${subject} ↔ ${object}: directly associated by the publisher.`,
      exactMatch:`${subject} and ${object} are exact matches across vocabularies.`,
      closeMatch:`${subject} and ${object} are similar enough for some cross-vocabulary uses.`,
      broadMatch:`${subject} maps to the broader concept ${object}.`,
      narrowMatch:`${subject} maps to the narrower concept ${object}.`,
      relatedMatch:`${subject} and ${object} are associated across vocabularies.`,
      thesaurusUse:`Use ${object}, the preferred term, instead of ${subject}.`,
      thesaurusUsedFor:`${object} is a non-preferred term for ${subject}.`,
      thesaurusRelated:`${subject} and ${object} are publisher-related despite also sharing a hierarchy.`,
      hasIndexedSubject:`${subject} is indexed under the subject ${object}.`,
      referencesLegalIdentity:`${subject} references the legal identity ${object}.`
    })[edge.predicateLabel]||`${subject} has relation “${edge.predicateLabel}” to ${object}.`;
  }
  function relationWhy(edge){
    if(edge.layer==="projection"){const count=edge.supportingAssertions?.length||0;return `Query-friendly copy of ${format(count)} assertion${count===1?"":"s"}; no new claim.`;}
    if(edge.layer==="derived"){const count=edge.derivedFromAssertions?.length||0;return `Inferred from ${format(count)} cited assertion${count===1?"":"s"}; not editor-approved.`;}
    const mapping=mappingContext(edge);
    if(mapping)return `Official alignment ${mapping.payload.publisherAlignmentVersion}, adopted for these exact releases.`;
    const evidence=edge.evidence||[];
    const sources=[...new Set(evidence.map(item=>friendlySource(sourceById.get(item.sourceRecord))))];
    const reasons=[...new Set(evidence.map(item=>warrantLabel(item.evidenceRole).reason))];
    if(edge.kind==="sourceAssignment")return `Links ${sources.join(" and ")||"a pinned source"} to its Atlas resource.`;
    return `${sources.join(" and ")||"Pinned evidence"}: ${reasons.join(" ")||"Approved source fact."}`;
  }
  function relationGuidance(edge){
    if(edge.layer==="projection")return "Use for queries; audit the supporting assertion.";
    if(edge.layer==="derived")return "Discovery only; review before publishing.";
    if(edge.status&&edge.status!=="current")return "Historical; do not use as current.";
    if(edge.kind==="sourceAssignment")return "Use for provenance only.";
    if(edge.kind==="mapping")return "Apply your local mapping policy.";
    return "";
  }
  function evidenceBrief(edge){
    if(edge.layer!=="asserted"||!edge.evidence?.length)return "";
    if(edge.kind==="mapping"){
      const mapping=mappingEvidenceBrief(edge);
      if(mapping)return mapping;
    }
    const rows=edge.evidence.map(item=>{const method=warrantLabel(item.evidenceRole),source=sourceById.get(item.sourceRecord);return `<div class="evidence-row"><b>${esc(friendlySource(source))} · ${esc(method.title)}</b><p>${esc(item.decision)} · digest pinned</p></div>`;}).join("");
    return `<section class="supporting"><h4>Evidence</h4><div class="evidence-list">${rows}</div></section>`;
  }
  function supportingBrief(edge){
    const ids=edge.layer==="projection"?edge.supportingAssertions:edge.layer==="derived"?edge.derivedFromAssertions:[];
    if(!ids?.length)return "";
    const rows=ids.map(id=>{const assertion=assertedById.get(id);if(!assertion)return `<div class="evidence-row"><b>Supporting assertion</b><p>${esc(id)}</p></div>`;const readable={...assertion,layer:"asserted"};const method=warrantLabel(assertion.evidence?.[0]?.evidenceRole).title;const meaning=edge.layer==="derived"?`<span>${esc(relationMeaning(readable))}</span>`:"";return `<button class="support-link" data-edge="asserted|${esc(id)}"><b>${esc(assertion.subjectLabel)} → ${esc(assertion.objectLabel)}</b>${meaning}<small>${esc(method)} · open</small></button>`;}).join("");
    return `<section class="supporting"><h4>Supporting assertions</h4><div class="support-list">${rows}</div></section>`;
  }
  function technicalRecord(edge){const record={...edge};delete record.color;delete record.layer;return record;}
  function renderInspector(){
    const empty=document.getElementById("empty-inspector"),view=document.getElementById("inspector-view");
    if(!state.selected){empty.hidden=false;view.hidden=true;return;}
    empty.hidden=true;view.hidden=false;
    if(state.selected.kind==="node"){
      const node=nodeById.get(state.selected.id),detail=node.detail,connections=state.renderedEdges.filter(edge=>nodeConnected(node,edge)).slice(0,20);
      const pending=(node.relationIds?.length||0)-(node.loadedRelationCount||0),loading=node.loading?"<p class=\"hint\">Loading verified details…</p>":node.loadError?`<p class="hint error">${esc(node.loadError)}</p>`:"",more=pending>0?`<button class="action" id="more-relations" type="button">Load ${format(Math.min(100,pending))} more relations</button>`:"";
      view.innerHTML=`<p class="kicker">${node.isSource?"Source record":"Atlas resource"}</p><h3 class="inspector-title">${esc(node.label)}</h3><span class="badge">${esc(detail?.displayLabelRole||node.ring||"endpoint")}</span>${loading}${identifierBrief(detail)}<h3 style="margin-top:1rem">Relations</h3><div class="connections">${connections.map(edge=>`<button class="connection" data-edge="${esc(edge.layer+"|"+edge.id)}" style="--edge:${edge.color}">${esc(relationMeaning(edge))}<small>${esc(edge.layer)} · ${esc(edge.predicateLabel)}</small></button>`).join("")||"<span class=\"hint\">No visible relations under current filters.</span>"}</div>${more}<details class="technical"><summary>About this resource</summary><dl class="facts"><dt>IRI</dt><dd class="iri">${esc(node.id)}</dd><dt>Release</dt><dd class="iri">${esc(node.release||"Not available in fallback view")}</dd>${detail?`<dt>Profile</dt><dd>${esc(detail.resourceProfile)}</dd><dt>Type</dt><dd>${esc(detail.resourceType)}</dd>`:""}</dl>${detail?`<details><summary>English labels</summary><pre>${esc(JSON.stringify(detail.labels,null,2))}</pre></details><details><summary>Source records</summary><pre>${esc(JSON.stringify(sourceDetails(detail.sourceRecords),null,2))}</pre></details>`:"<p class=\"hint\">Full details load when served over HTTP.</p>"}</details>`;
    }else{
      const edge=state.selected.edge;
      const guidance=relationGuidance(edge),back=state.inspectorReturn?`<button class="inspector-back" id="inspector-back" type="button">← ${state.inspectorReturn.selection.kind==="node"?"Back to relations":"Back"}</button>`:"";
      view.innerHTML=`${back}<p class="kicker">${esc(edge.layer)} relation</p><h3 class="inspector-title">${esc(edge.subjectLabel)} → ${esc(edge.objectLabel)}</h3><span class="badge ${esc(edge.layer)}">${esc(edge.layer)}</span><span class="badge">${esc(edge.predicateLabel)}</span><div class="relation-brief"><section class="brief-block"><h4>Meaning</h4><p class="brief-lead">${esc(relationMeaning(edge))}</p></section><section class="brief-block"><h4>Why it is here</h4><p>${esc(relationWhy(edge))}</p></section>${guidance?`<section class="brief-block"><h4>Use</h4><p>${esc(guidance)}</p></section>`:""}</div>${evidenceBrief(edge)}${supportingBrief(edge)}<details class="technical"><summary>Technical details</summary><pre>${esc(JSON.stringify(technicalRecord(edge),null,2))}</pre></details>`;
    }
    document.getElementById("inspector-back")?.addEventListener("click",()=>{const target=state.inspectorReturn;state.inspectorReturn=null;state.selected=target.selection;renderInspector();document.getElementById("inspector").scrollTop=target.scrollTop;draw();});
    document.getElementById("more-relations")?.addEventListener("click",()=>{const node=nodeById.get(state.selected.id);void hydrateNode(node,true);});
    view.querySelectorAll("[data-edge]").forEach(button=>button.addEventListener("click",()=>{const [layer,...rest]=button.dataset.edge.split("|");const id=rest.join("|");const edge=allEdges.find(row=>row.layer===layer&&row.id===id);if(edge){if(!state.inspectorReturn)state.inspectorReturn={selection:state.selected,scrollTop:document.getElementById("inspector").scrollTop};state.selected={kind:"edge",id:edge.id,layer:edge.layer,edge};renderInspector();document.getElementById("inspector").scrollTop=0;draw();void hydrateEdge(edge);}}));
  }
  function selectNode(node,center=false){state.inspectorReturn=null;state.selected={kind:"node",id:node.id};refresh(false,false);if(fullMode)void hydrateNode(node);if(center){state.view.x=state.width/2-node.x*state.view.k;state.view.y=state.height/2-node.y*state.view.k;draw();}}
  function normalizedQuery(value){return value.normalize("NFKD").replace(/\p{M}/gu,"").toLocaleLowerCase("en-US").replace(/[^a-z0-9]+/g," ").trim();}
  const searchPageSize=40;
  let duckdbSearch=null,duckdbSearchPromise=null,searchTimer=null;
  async function hasDuckdbSearch(){
    if(duckdbSearch!==null)return duckdbSearch;
    if(location.protocol==="file:"){duckdbSearch=false;return false;}
    if(!duckdbSearchPromise)duckdbSearchPromise=(async()=>{try{const response=await fetch("/api/capabilities",{cache:"no-store"});if(!response.ok)return false;const capabilities=await response.json();return capabilities.search?.available===true&&capabilities.search?.engine==="duckdb-fts";}catch{return false;}})();
    duckdbSearch=await duckdbSearchPromise;return duckdbSearch;
  }
  function showSearchResults(){
    const rows=state.searchRows.slice(0,state.searchVisible);
    const priorScroll=searchResults.scrollTop;
    searchResults.replaceChildren();
    rows.forEach(node=>{const button=document.createElement("button");button.className="result";button.innerHTML=`<b>${esc(node.label)}</b><small>${esc(node.release||node.id)}</small>`;button.addEventListener("click",()=>selectNode(node,true));searchResults.append(button);});
    searchResults.scrollTop=priorScroll;
    if(!state.query)searchResultStatus.textContent="";
    else if(!rows.length&&!state.searchLoading)searchResultStatus.textContent="No matching resources.";
    else searchResultStatus.textContent=`${format(rows.length)} loaded${state.searchHasMore||state.searchVisible<state.searchRows.length?" · keep scrolling":""}`;
  }
  function orderedLocalSearchRows(ids){return[...ids].map(id=>nodeById.get(id)).filter(Boolean).sort((a,b)=>a.label.localeCompare(b.label,"en")||a.id.localeCompare(b.id));}
  async function loadMoreSearch(epoch=searchEpoch){
    if(state.searchLoading||!state.query)return;
    if(state.searchMode!=="duckdb"){
      if(state.searchVisible<state.searchRows.length){state.searchVisible=Math.min(state.searchRows.length,state.searchVisible+searchPageSize);state.searchHasMore=state.searchVisible<state.searchRows.length;showSearchResults();}
      return;
    }
    if(!state.searchHasMore)return;
    state.searchLoading=true;searchResultStatus.textContent=state.searchOffset?`${format(state.searchOffset)} loaded · loading more…`:"Ranking results with DuckDB BM25…";
    try{
      const active=activeVisibleReleases(),visible=visibleReleaseRows();
      const params=new URLSearchParams({q:search.value.trim(),ring:state.ring,limit:String(searchPageSize),offset:String(state.searchOffset)});
      if(active.size<visible.length)for(const release of active)params.append("release",release);
      const response=await fetch(`/api/search?${params}`,{cache:"no-store"});if(!response.ok){const payload=await response.json().catch(()=>({}));throw new Error(payload.error||`Search request failed (${response.status})`);}
      const rows=await response.json();if(epoch!==searchEpoch)return;
      const known=new Set(state.searchRows.map(node=>node.id));
      for(const row of rows){if(known.has(row.id))continue;const node=summaryNode({id:row.id,displayLabel:row.label,release:row.release,ring:row.ring,searchText:[row.label,...(row.notations||[]),row.id].join(" ")});state.searchRows.push(node);state.matches.add(node.id);known.add(node.id);}
      state.searchOffset+=rows.length;state.searchVisible=state.searchRows.length;state.searchHasMore=rows.length===searchPageSize;syncRenderCapacity();showSearchResults();refresh(false);
    }finally{if(epoch===searchEpoch)state.searchLoading=false;}
  }
  async function renderSearch(){
    const epoch=++searchEpoch,activeReleases=activeVisibleReleases(),query=normalizedQuery(search.value);state.query=query;state.searchRows=[];state.searchVisible=0;state.searchOffset=0;state.searchHasMore=false;state.searchLoading=false;state.searchMode="local";searchResults.scrollTop=0;const localMatches=new Set(state.query?nodes.filter(node=>activeReleases.has(node.release)&&(!state.ring||node.rings.has(state.ring))&&normalizedQuery(`${node.corpusSearchText||""} ${searchText(node)}`).includes(state.query)).map(node=>node.id):[]);state.matches=localMatches;state.searchRows=orderedLocalSearchRows(localMatches);state.searchVisible=Math.min(searchPageSize,state.searchRows.length);state.searchHasMore=state.searchVisible<state.searchRows.length;showSearchResults();refresh(false);
    if(!state.query)return;
    if(!activeReleases.size){corpusMode.textContent="Select at least one Atlas release.";return;}
    if(await hasDuckdbSearch()){if(epoch!==searchEpoch)return;state.searchMode="duckdb";state.searchRows=[];state.searchVisible=0;state.searchOffset=0;state.searchHasMore=true;state.matches.clear();showSearchResults();try{await loadMoreSearch(epoch);corpusMode.textContent=`Full graph · DuckDB BM25 search · ${format(data.summary.availableResources)} resources`;corpusMode.classList.remove("error");return;}catch(error){if(epoch!==searchEpoch)return;duckdbSearch=false;state.searchMode="local";corpusMode.textContent=`DuckDB search unavailable; using verified label shards. ${String(error?.message||error)}`;corpusMode.classList.add("error");}}
    if(!fullMode)return;
    try{const index=await loadFullIndex(),firstWord=state.query.split(" ")[0],key=(firstWord+"__").slice(0,2),refs=firstWord.length===1?Object.entries(index.search.shards).filter(([candidate])=>candidate.startsWith(firstWord)).flatMap(([,rows])=>rows):index.search.shards[key]||[];corpusMode.textContent="Searching verified shards…";
      for(const ref of refs){const shard=await fetchVerifiedShard(ref);if(epoch!==searchEpoch)return;if(shard.version!=="2"||shard.kind!=="search"||shard.key!==ref.key)throw new Error("Search shard identity differs");for(const summary of shard.entries){if(normalizedQuery(summary.searchText).includes(state.query)&&(!state.ring||summary.ring===state.ring)&&activeReleases.has(summary.release))localMatches.add(summaryNode(summary).id);}}
      if(epoch!==searchEpoch)return;state.matches=localMatches;state.searchRows=orderedLocalSearchRows(localMatches);state.searchVisible=Math.min(searchPageSize,state.searchRows.length);state.searchHasMore=state.searchVisible<state.searchRows.length;syncRenderCapacity();showSearchResults();corpusMode.textContent=`Full corpus · verified search · ${format(fullBundle.counts.resources)} resources`;corpusMode.classList.remove("error");refresh(false);
    }catch(error){if(epoch!==searchEpoch)return;corpusMode.textContent=`Full-corpus search error: ${String(error?.message||error)}`;corpusMode.classList.add("error");}
  }
  searchResults.addEventListener("scroll",()=>{if(searchResults.scrollHeight-searchResults.scrollTop-searchResults.clientHeight<80)void loadMoreSearch();});
  /* atlas-controls-resize:start */
  const controlsWidthMinimum=210,controlsWidthMaximum=520;
  let controlsResize=null;
  function controlsWidthBounds(){const reserved=innerWidth<=1000?325:655;return{min:controlsWidthMinimum,max:Math.max(controlsWidthMinimum,Math.min(controlsWidthMaximum,workspace.clientWidth-reserved))};}
  function setControlsWidth(value){const bounds=controlsWidthBounds(),width=Math.round(Math.max(bounds.min,Math.min(bounds.max,Number(value)||bounds.min)));workspace.style.setProperty("--controls-width",`${width}px`);controlsResizer.setAttribute("aria-valuemax",String(bounds.max));controlsResizer.setAttribute("aria-valuenow",String(width));return width;}
  function finishControlsResize(event){if(!controlsResize||event.pointerId!==controlsResize.pointerId)return;if(controlsResizer.hasPointerCapture(event.pointerId))controlsResizer.releasePointerCapture(event.pointerId);controlsResize=null;workspace.classList.remove("resizing");}
  controlsResizer.addEventListener("pointerdown",event=>{if(event.button!==0||innerWidth<=680)return;controlsResize={pointerId:event.pointerId,startX:event.clientX,startWidth:controlsPanel.getBoundingClientRect().width};controlsResizer.setPointerCapture(event.pointerId);workspace.classList.add("resizing");event.preventDefault();});
  controlsResizer.addEventListener("pointermove",event=>{if(!controlsResize||event.pointerId!==controlsResize.pointerId)return;setControlsWidth(controlsResize.startWidth+event.clientX-controlsResize.startX);});
  controlsResizer.addEventListener("pointerup",finishControlsResize);controlsResizer.addEventListener("pointercancel",finishControlsResize);
  controlsResizer.addEventListener("dblclick",()=>setControlsWidth(272));
  controlsResizer.addEventListener("keydown",event=>{const current=controlsPanel.getBoundingClientRect().width,bounds=controlsWidthBounds();let next;if(event.key==="ArrowLeft")next=current-16;else if(event.key==="ArrowRight")next=current+16;else if(event.key==="Home")next=bounds.min;else if(event.key==="End")next=bounds.max;else return;setControlsWidth(next);event.preventDefault();});
  /* atlas-controls-resize:end */
  function resize(){if(innerWidth>680)setControlsWidth(controlsPanel.getBoundingClientRect().width);const rect=stage.getBoundingClientRect();state.width=Math.max(1,rect.width);state.height=Math.max(1,rect.height);state.dpr=Math.min(2,devicePixelRatio||1);canvas.width=Math.round(state.width*state.dpr);canvas.height=Math.round(state.height*state.dpr);canvas.style.width=`${state.width}px`;canvas.style.height=`${state.height}px`;fitView();}
  canvas.addEventListener("pointerdown",event=>{canvas.setPointerCapture(event.pointerId);const node=hitNode(event.clientX,event.clientY);if(node){selectNode(node);return;}const edge=hitEdge(event.clientX,event.clientY);if(edge){state.inspectorReturn=null;state.selected={kind:"edge",id:edge.id,layer:edge.layer,edge};renderInspector();draw();void hydrateEdge(edge);return;}state.panning=true;state.drag={x:event.clientX,y:event.clientY,viewX:state.view.x,viewY:state.view.y};canvas.classList.add("panning");});
  canvas.addEventListener("pointermove",event=>{if(state.panning){state.view.x=state.drag.viewX+event.clientX-state.drag.x;state.view.y=state.drag.viewY+event.clientY-state.drag.y;draw();return;}const node=hitNode(event.clientX,event.clientY);state.hover=node?.id||null;if(node){const rect=stage.getBoundingClientRect();tooltip.innerHTML=`${esc(node.label)}<small>${esc(node.release||node.id)}</small>`;tooltip.style.left=`${event.clientX-rect.left}px`;tooltip.style.top=`${event.clientY-rect.top}px`;tooltip.hidden=false;}else tooltip.hidden=true;draw();});
  canvas.addEventListener("pointerup",event=>{if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);state.panning=false;state.drag=null;canvas.classList.remove("panning");});canvas.addEventListener("pointerleave",()=>{state.hover=null;tooltip.hidden=true;draw();});
  canvas.addEventListener("wheel",event=>{event.preventDefault();const rect=canvas.getBoundingClientRect();zoomAt(event.deltaY<0?1.12:.89,event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
  canvas.addEventListener("keydown",event=>{if(event.key==="+"||event.key==="=")zoomAt(1.2);else if(event.key==="-")zoomAt(.83);else if(event.key==="ArrowLeft")state.view.x+=32;else if(event.key==="ArrowRight")state.view.x-=32;else if(event.key==="ArrowUp")state.view.y+=32;else if(event.key==="ArrowDown")state.view.y-=32;else return;event.preventDefault();draw();});
  document.getElementById("authority-asserted").addEventListener("change",event=>{state.layers.asserted=event.currentTarget.checked;refresh(false);});document.getElementById("authority-projection").addEventListener("change",event=>{state.layers.projection=event.currentTarget.checked;refresh(false);});document.getElementById("authority-derived").addEventListener("change",event=>{state.layers.derived=event.currentTarget.checked;refresh(false);});document.getElementById("show-source-assignments").addEventListener("change",event=>{state.showAssignments=event.currentTarget.checked;refresh(false);});
  ringFilter.addEventListener("change",event=>{state.ring=event.currentTarget.value;state.selected=null;state.inspectorReturn=null;renderReleaseFilters();syncRenderCapacity();void loadSelectedReleaseGraphs();if(search.value)void renderSearch();else refresh(true);});predicateFilter.addEventListener("change",event=>{state.predicate=event.currentTarget.value;refresh(true);});search.addEventListener("input",()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{void renderSearch();},180);});window.addEventListener("keydown",event=>{if(event.key==="/"&&document.activeElement!==search){event.preventDefault();search.focus();}if(event.key==="Escape"){state.inspectorReturn=null;state.selected=null;search.value="";void renderSearch();}});
  let limitLoadTimer=null;
  function applyRenderLimit(){refresh(true,state.renderLimit<=5000);if(fullMode)void loadSelectedReleaseGraphs();}
  function setLimit(value,defer=false){requestedRenderLimit=Math.max(1,Number(value)||1);state.renderLimit=Math.min(maxLimit,requestedRenderLimit);range.value=number.value=String(state.renderLimit);document.getElementById("render-limit-label").textContent=`${format(state.renderLimit)} of ${format(maxLimit)}`;clearTimeout(limitLoadTimer);if(defer)limitLoadTimer=setTimeout(applyRenderLimit,140);else applyRenderLimit();}range.addEventListener("input",event=>setLimit(event.currentTarget.value,true));number.addEventListener("change",event=>setLimit(event.currentTarget.value));
  function reset(){state.activeReleases=new Set(releaseById.keys());state.layers={asserted:true,projection:false,derived:true};state.showAssignments=false;state.ring="";state.predicate="";state.selected=null;state.inspectorReturn=null;state.query="";state.matches.clear();state.searchRows=[];state.searchVisible=0;state.searchOffset=0;state.searchHasMore=false;search.value="";ringFilter.value="";predicateFilter.value="";document.getElementById("authority-asserted").checked=true;document.getElementById("authority-projection").checked=false;document.getElementById("authority-derived").checked=true;document.getElementById("show-source-assignments").checked=false;renderReleaseFilters();showSearchResults();syncRenderCapacity();refresh(true);void loadSelectedReleaseGraphs();}
  document.getElementById("select-no-releases").addEventListener("click",selectNoReleases);document.getElementById("reset-view").addEventListener("click",reset);document.getElementById("fit-view").addEventListener("click",fitView);document.getElementById("fit-canvas").addEventListener("click",fitView);document.getElementById("zoom-in").addEventListener("click",()=>zoomAt(1.25));document.getElementById("zoom-out").addEventListener("click",()=>zoomAt(.8));new ResizeObserver(resize).observe(stage);
  document.getElementById("metric-resources").textContent=format(data.summary.availableResources);document.getElementById("metric-asserted").textContent=format(data.summary.availableAssertedRelations);document.getElementById("metric-derived").textContent=format(data.summary.availableDerivedRelations);document.getElementById("search-coverage").textContent=fullMode?"English search pages load only when queried.":`English search covers ${format(data.summary.indexedResources)} fallback resources out of ${format(data.summary.availableResources)} sealed resources.`;document.getElementById("distribution-id").textContent=data.distribution.id;document.getElementById("manifest-digest").textContent=data.distribution.manifestDigest;
  if(fullMode)corpusMode.textContent="Full corpus · move the slider to load verified resources.";else if(fullBundle&&location.protocol==="file:")corpusMode.textContent="Bounded local view · serve this folder over HTTP for the full corpus.";else if(fullBundle&&!gzipStreamSupported)corpusMode.textContent="Bounded fallback · this browser cannot open verified gzip shards.";else corpusMode.textContent="Bounded fallback view.";
  renderReleaseFilters();syncRenderCapacity();refresh(false);resize();
})();
</script>
</body>
</html>
"""


def render_atlas_v3_explorer(model: Mapping[str, Any]) -> str:
    """Render one self-contained Atlas 3.0 explorer."""

    if not isinstance(model, Mapping):
        raise Atlas3ExplorerError("Atlas 3.0 explorer must be an object")
    _validate_model(model)
    return _Atlas3Template(_GRAPH_HTML).substitute(
        title=html.escape(cast(str, model["title"]), quote=True),
        atlas_data=_safe_json(model),
    )


def render_atlas_explorer(model: Mapping[str, Any]) -> str:
    """Render Atlas 3.0; the unversioned name no longer accepts Atlas 2 models."""

    return render_atlas_v3_explorer(model)

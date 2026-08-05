"""Publish one authorized Atlas 2.0 distribution as static files.

The canonical atlas or a closed projection remains the semantic authority.
Publication preserves that distribution's exact manifest bytes, compresses its
exact N-Quads deterministically, carries the exact publication decision, and
adds a complete searchable explorer index with bounded client-side graph
rendering.  Every published byte is pinned by a content-derived publication
manifest.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)

from .explorer import (
    EXPLORER_SCHEMA_VERSION,
    EXPLORER_TYPE,
    render_atlas_explorer,
)
from .model import (
    ATLAS_FILE,
    MANIFEST_FILE,
    SCOPE_FILE,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
)
from .projection import (
    VocabularyAtlasProjection,
    build_atlas_projection,
    distribution_kind,
)
from .publication_decision import (
    PublicationDecisionError,
    VocabularyAtlasPublicationDecision,
    read_vocabulary_atlas_publication_decision,
)
from .queries import (
    ConceptLabel,
    ConceptVersion,
    VocabularyAtlasDistribution,
    VocabularyAtlasQueries,
)

PUBLICATION_MANIFEST = "publication-manifest.json"
EXPLORER_DATA = "atlas-explorer.json"
EXPLORER_HTML = "index.html"
COMPRESSED_ATLAS = "atlas.nq.gz"
ATLAS_MANIFEST = MANIFEST_FILE
ATLAS_SCOPE = SCOPE_FILE
PUBLICATION_DECISION = "publication-decision.json"
PUBLICATION_SCHEMA_VERSION = "2.1"

_PUBLICATION_TYPE = "urn:ref:type:VocabularyAtlasPublicationManifest"
_PUBLICATION_ID_PREFIX = "urn:ref:vocabulary-atlas-publication:"
_SELECTION_POLICY_ID = "https://refspec.org/policies/vocabulary-atlas-explorer-bounded-view/2.1"
_DEFAULT_MAX_CONCEPTS: int | None = None
_DEFAULT_MAX_MAPPING_ASSERTIONS: int | None = None
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLICATION_CONSTRUCTION_TOKEN = object()
_READ_CHUNK_SIZE = 1024 * 1024
_DESCRIPTOR_RELATIVE_READS_SUPPORTED = os.open in os.supports_dir_fd and os.listdir in os.supports_fd

_PUBLICATION_FIELDS = frozenset(
    {
        "id",
        "type",
        "schemaVersion",
        "publicationDigest",
        "title",
        "distribution",
        "decision",
        "selectionPolicy",
        "summary",
        "artifacts",
        "canonicalPayloadDigest",
    }
)
_PUBLICATION_BASIS_FIELDS = (
    "type",
    "schemaVersion",
    "title",
    "distribution",
    "decision",
    "selectionPolicy",
    "summary",
    "artifacts",
)
_ATLAS_DISTRIBUTION_FIELDS = frozenset({"kind", "assetId", "manifestDigest", "distributionDigest"})
_PROJECTION_DISTRIBUTION_FIELDS = _ATLAS_DISTRIBUTION_FIELDS | {"parent"}
_PARENT_FIELDS = frozenset({"assetId", "manifestDigest", "distributionDigest"})
_DECISION_FIELDS = frozenset({"id", "recordDigest", "fileDigest"})
_SELECTION_FIELDS = frozenset({"id", "type", "version", "maxConcepts", "maxMappingAssertions"})
_SUMMARY_FIELDS = frozenset(
    {
        "shownConceptCount",
        "shownNativeRelationCount",
        "shownMappingAssertionCount",
        "availableConceptCount",
        "availableNativeRelationCount",
        "availableMappingAssertionCount",
        "truncated",
    }
)
_ARTIFACT_FIELDS = frozenset({"path", "role", "mediaType", "fileDigest", "byteLength"})
_COMPRESSED_ARTIFACT_FIELDS = _ARTIFACT_FIELDS | {
    "contentEncoding",
    "uncompressedDigest",
    "uncompressedByteLength",
}
_ARTIFACT_SPEC = {
    ATLAS_MANIFEST: ("sourceDistributionManifest", "application/json"),
    ATLAS_SCOPE: ("canonicalScope", "application/json"),
    COMPRESSED_ATLAS: ("compressedDistribution", "application/n-quads"),
    PUBLICATION_DECISION: ("publicationDecision", "application/json"),
    EXPLORER_DATA: ("derivedExplorerData", "application/json"),
    EXPLORER_HTML: ("offlineExplorer", "text/html; charset=utf-8"),
}
_RING_ORDER = {"subject": 0, "entity": 1, "value": 2, "legalIdentity": 3}


class AtlasPublicationError(VocabularyAtlasError):
    """A publication is unauthorized, malformed, stale, or tampered with."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    try:
        binding.validate_canonical_value(_plain(value))
    except (TypeError, ValueError) as error:
        raise AtlasPublicationError(str(error)) from error
    return canonical_json_bytes(value)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AtlasPublicationError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AtlasPublicationError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise AtlasPublicationError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AtlasPublicationError(f"{label} must be non-empty trimmed text")
    return value


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AtlasPublicationError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_count(value: object, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise AtlasPublicationError(f"{label} must be a {qualifier} integer")
    return value


def _load_canonical_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AtlasPublicationError(f"{label} must be valid canonical UTF-8 JSON") from error
    if not isinstance(value, dict) or _canonical_bytes(value) != payload:
        raise AtlasPublicationError(f"{label} bytes are not canonical")
    return value


def _gzip_bytes(payload: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=output,
        compresslevel=9,
        mtime=0,
    ) as stream:
        stream.write(payload)
    return output.getvalue()


def _iri_tail(value: str) -> str:
    parsed = urlparse(value)
    if parsed.fragment:
        tail = parsed.fragment
    elif parsed.scheme in {"http", "https"}:
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.netloc
    else:
        tail = value.rstrip(":/").rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return " ".join(unquote(tail).replace("_", " ").replace("-", " ").split()) or value


def _default_release_label(release_id: str) -> str:
    parsed = urlparse(release_id)
    tail = _iri_tail(release_id)
    if parsed.scheme in {"http", "https"} and tail != parsed.netloc:
        return f"{parsed.netloc} · {tail}"
    return tail


def _relation_label(relation: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", _iri_tail(relation)).casefold()


def _concept_view_id(version: ConceptVersion, repeated_ids: Counter[str]) -> str:
    if repeated_ids[version.concept_id] == 1:
        return version.concept_id
    digest = hashlib.sha256(f"{version.release_id}\x1f{version.concept_id}\x1f{version.record_id}".encode()).hexdigest()
    return f"urn:ref:vocabulary-atlas-explorer-node:{digest}"


def _language_values(value: object) -> tuple[tuple[str, str | None], ...]:
    if isinstance(value, str):
        return ((value, None),)
    if isinstance(value, Mapping):
        literal = value.get("@value")
        if isinstance(literal, str):
            language = value.get("@language")
            return ((literal, language if isinstance(language, str) else None),)
        result: list[tuple[str, str | None]] = []
        for language, child in value.items():
            normalized = language if isinstance(language, str) and language not in {"", "@none"} else None
            if isinstance(child, str):
                result.append((child, normalized))
            elif isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                result.extend((item, normalized) for item in child if isinstance(item, str))
        return tuple(result)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item for child in value for item in _language_values(child))
    return ()


def _first_text(record: Mapping[str, Any], *fields: str) -> str | None:
    choices: list[tuple[int, str, str]] = []
    for field in fields:
        for text, language in _language_values(record.get(field)):
            stripped = text.strip()
            if stripped:
                normalized = (language or "").casefold()
                priority = 0 if normalized == "en" else 1 if not normalized else 2
                choices.append((priority, normalized, stripped))
    if not choices:
        return None
    return min(choices, key=lambda item: (item[0], item[1], item[2].casefold(), item[2]))[2]


def _preferred_label(
    version: ConceptVersion,
    labels: Sequence[ConceptLabel],
) -> str:
    usable_labels = tuple(label for label in labels if label.value.strip())
    if usable_labels:
        role_order = {"preferred": 0, "alternate": 1, "hidden": 2}
        selected = min(
            usable_labels,
            key=lambda value: (
                role_order[value.role],
                0 if (value.language or "").casefold() == "en" else 1 if not value.language else 2,
                (value.language or "").casefold(),
                value.value.casefold(),
                value.value,
                value.evidence_record_id,
            ),
        )
        return selected.value.strip()
    return _iri_tail(version.concept_id)


def _verified_distribution(distribution: VocabularyAtlasDistribution) -> None:
    if not isinstance(distribution, (VocabularyAtlasAsset, VocabularyAtlasProjection)):
        raise AtlasPublicationError("publication requires a verified Atlas 2.0 distribution")
    try:
        distribution._require_verified()
    except VocabularyAtlasError as error:
        raise AtlasPublicationError(str(error)) from error


def _fits_concept_budget(
    selected: Mapping[tuple[str, str], ConceptVersion],
    endpoints: tuple[tuple[str, str], tuple[str, str]],
    *,
    max_concepts: int,
) -> bool:
    new_endpoint_count = sum(key not in selected for key in set(endpoints))
    return len(selected) + new_endpoint_count <= max_concepts


def _distribution_descriptor(
    distribution: VocabularyAtlasDistribution,
) -> dict[str, Any]:
    _verified_distribution(distribution)
    result: dict[str, Any] = {
        "kind": "atlas" if isinstance(distribution, VocabularyAtlasAsset) else "projection",
        "assetId": str(distribution.manifest["id"]),
        "manifestDigest": distribution.manifest_digest,
        "distributionDigest": distribution.output_digest,
    }
    if isinstance(distribution, VocabularyAtlasProjection):
        result["parent"] = distribution.parent_pin
    return result


def _selection_policy(
    *,
    max_concepts: int,
    max_mapping_assertions: int,
) -> dict[str, Any]:
    return {
        "id": _SELECTION_POLICY_ID,
        "type": "boundedExplorerView",
        "version": EXPLORER_SCHEMA_VERSION,
        "maxConcepts": max_concepts,
        "maxMappingAssertions": max_mapping_assertions,
    }


def build_explorer_model(
    distribution: VocabularyAtlasDistribution,
    *,
    title: str = "RefSpec vocabulary atlas",
    release_labels: Mapping[str, str] | None = None,
    max_concepts: int | None = _DEFAULT_MAX_CONCEPTS,
    max_mapping_assertions: int | None = _DEFAULT_MAX_MAPPING_ASSERTIONS,
) -> dict[str, Any]:
    """Build one deterministic search index through generic Atlas 2.0 queries.

    By default, every concept and assertion is indexed. Explicit limits remain
    available for small demonstrations and compatibility fixtures; the browser
    independently bounds how many indexed concepts it draws at once.
    """

    _verified_distribution(distribution)
    clean_title = _require_text(title, "atlas publication title")
    if max_concepts is not None:
        _require_count(max_concepts, "atlas explorer max_concepts", positive=True)
    if max_mapping_assertions is not None:
        _require_count(
            max_mapping_assertions,
            "atlas explorer max_mapping_assertions",
        )
    labels = dict(release_labels or {})
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not key.strip()
        or not value.strip()
        or key != key.strip()
        or value != value.strip()
        for key, value in labels.items()
    ):
        raise AtlasPublicationError("atlas explorer release labels must be trimmed non-empty text")

    queries = VocabularyAtlasQueries(distribution)
    snapshots = queries.release_snapshots()
    release_ids = {snapshot.release_id for snapshot in snapshots}
    unknown_labels = sorted(set(labels) - release_ids)
    if unknown_labels:
        raise AtlasPublicationError(f"atlas explorer release labels name unknown releases: {unknown_labels}")

    concepts = queries.concepts()
    concept_by_key = {(value.release_id, value.concept_id): value for value in concepts}
    repeated_ids = Counter(value.concept_id for value in concepts)
    mappings = queries.mapping_assertions()
    native_relations = queries.native_relations()
    concept_limit = len(concepts) if max_concepts is None else max_concepts
    mapping_limit = len(mappings) if max_mapping_assertions is None else max_mapping_assertions
    selected: dict[tuple[str, str], ConceptVersion] = {}
    selected_assertions = []

    for view in mappings:
        if len(selected_assertions) >= mapping_limit:
            break
        assertion = view.assertion
        source_key = (assertion.source_release, assertion.source_concept)
        target_key = (assertion.target_release, assertion.target_concept)
        endpoints = (concept_by_key.get(source_key), concept_by_key.get(target_key))
        if any(endpoint is None for endpoint in endpoints):
            raise AtlasPublicationError("atlas mapping endpoint is absent from the verified concept records")
        if not _fits_concept_budget(
            selected,
            (source_key, target_key),
            max_concepts=concept_limit,
        ):
            continue
        selected[source_key] = cast(ConceptVersion, endpoints[0])
        selected[target_key] = cast(ConceptVersion, endpoints[1])
        selected_assertions.append(view)

    representative_keys: set[tuple[str, str]] = set()
    for snapshot in snapshots:
        candidates = queries.concepts(release_id=snapshot.release_id)
        if candidates and len(selected) < concept_limit:
            representative = candidates[0]
            key = (representative.release_id, representative.concept_id)
            selected.setdefault(key, representative)
            representative_keys.add(key)
    for relation in native_relations:
        subject_key = (relation.release_id, relation.subject_concept)
        object_key = (relation.release_id, relation.object_concept)
        endpoints = (
            concept_by_key.get(subject_key),
            concept_by_key.get(object_key),
        )
        if any(endpoint is None for endpoint in endpoints):
            raise AtlasPublicationError("atlas native relation endpoint is absent from the verified concept records")
        if not _fits_concept_budget(
            selected,
            (subject_key, object_key),
            max_concepts=concept_limit,
        ):
            continue
        selected[subject_key] = cast(ConceptVersion, endpoints[0])
        selected[object_key] = cast(ConceptVersion, endpoints[1])
    for version in concepts:
        if len(selected) >= concept_limit:
            break
        selected.setdefault((version.release_id, version.concept_id), version)

    view_id_by_key = {key: _concept_view_id(version, repeated_ids) for key, version in selected.items()}
    mapping_endpoint_keys = {
        key
        for view in selected_assertions
        for key in (
            (view.assertion.source_release, view.assertion.source_concept),
            (view.assertion.target_release, view.assertion.target_concept),
        )
    }
    selected_native_relations = tuple(
        relation
        for relation in native_relations
        if (relation.release_id, relation.subject_concept) in selected
        and (relation.release_id, relation.object_concept) in selected
    )
    native_relation_endpoint_keys = {
        key
        for relation in selected_native_relations
        for key in (
            (relation.release_id, relation.subject_concept),
            (relation.release_id, relation.object_concept),
        )
    }
    concept_rows: list[dict[str, Any]] = []
    for key, version in sorted(
        selected.items(),
        key=lambda item: (
            _RING_ORDER[item[1].semantic_ring],
            item[1].release_id,
            item[1].concept_id,
            item[1].record_id,
        ),
    ):
        concept_labels = queries.concept_labels(
            version.concept_id,
            release_id=version.release_id,
        )
        selection_reasons: list[str] = []
        if key in mapping_endpoint_keys:
            selection_reasons.append("mappingEndpoint")
        if key in native_relation_endpoint_keys:
            selection_reasons.append("nativeRelationEndpoint")
        if key in representative_keys:
            selection_reasons.append("releaseRepresentative")
        concept_row: dict[str, Any] = {
            "viewId": view_id_by_key[key],
            "conceptId": version.concept_id,
            "releaseId": version.release_id,
            "semanticRing": version.semantic_ring,
            "recordId": version.record_id,
            "recordDigest": version.record_digest,
            "label": _preferred_label(version, concept_labels),
            "searchLabels": sorted(
                {
                    value
                    for label in concept_labels
                    if (value := label.value.strip())
                },
                key=lambda value: (value.casefold(), value),
            ),
            "selectionReasons": selection_reasons,
        }
        notation = _first_text(version.record, "skos:notation", "http://www.w3.org/2004/02/skos/core#notation")
        definition = _first_text(
            version.record,
            "skos:definition",
            "http://www.w3.org/2004/02/skos/core#definition",
        )
        scope_note = _first_text(
            version.record,
            "skos:scopeNote",
            "http://www.w3.org/2004/02/skos/core#scopeNote",
        )
        if notation is not None:
            concept_row["notation"] = notation
        if definition is not None:
            concept_row["definition"] = definition
        if scope_note is not None:
            concept_row["scopeNote"] = scope_note
        concept_rows.append(concept_row)

    native_relation_rows = [
        {
            "id": relation.relation_id,
            "subjectViewId": view_id_by_key[(relation.release_id, relation.subject_concept)],
            "objectViewId": view_id_by_key[(relation.release_id, relation.object_concept)],
            "subjectConcept": relation.subject_concept,
            "objectConcept": relation.object_concept,
            "releaseId": relation.release_id,
            "semanticRing": relation.semantic_ring,
            "predicate": relation.predicate_iri,
            "predicateLabel": _relation_label(relation.predicate_iri),
            "sourceRecordId": relation.source_record_id,
            "sourceRecordDigest": relation.source_record_digest,
        }
        for relation in selected_native_relations
    ]

    mapping_rows: list[dict[str, Any]] = []
    for view in selected_assertions:
        assertion = view.assertion
        source_key = (assertion.source_release, assertion.source_concept)
        target_key = (assertion.target_release, assertion.target_concept)
        mapping_row: dict[str, Any] = {
            "id": view.mapping_id,
            "sourceViewId": view_id_by_key[source_key],
            "targetViewId": view_id_by_key[target_key],
            "sourceConcept": assertion.source_concept,
            "targetConcept": assertion.target_concept,
            "sourceRelease": assertion.source_release,
            "targetRelease": assertion.target_release,
            "semanticRing": assertion.semantic_ring,
            "relation": assertion.relation,
            "relationLabel": _relation_label(assertion.relation),
            "directEvidenceAssertions": list(assertion.evidence),
            "evidenceAssertions": sorted({item.assertion.identifier for item in view.evidence_assertions}),
            "evidenceClasses": sorted({item.assertion.evidence_class for item in view.evidence_assertions}),
            "externalEvidence": list(view.external_evidence_ids),
            "candidateIds": list(view.candidate_ids),
            "validationReceiptIds": list(view.validation_receipt_ids),
            "machineProofs": [item.proof_id for item in view.machine_proofs],
        }
        if assertion.context is not None:
            mapping_row["context"] = _plain(assertion.context)
        mapping_rows.append(mapping_row)
    mapping_rows.sort(key=lambda value: (_RING_ORDER[value["semanticRing"]], value["id"]))

    release_rows = []
    for snapshot in snapshots:
        members = queries.concepts(release_id=snapshot.release_id)
        release_rows.append(
            {
                "releaseId": snapshot.release_id,
                "label": labels.get(snapshot.release_id, _default_release_label(snapshot.release_id)),
                "semanticRing": snapshot.semantic_ring,
                "conceptCount": len(members),
                "shownConceptCount": sum(concept["releaseId"] == snapshot.release_id for concept in concept_rows),
            }
        )

    source_counts = _plain(distribution.manifest["counts"])
    if not isinstance(source_counts, dict):
        raise AtlasPublicationError("verified atlas manifest counts must be an object")
    output = _require_mapping(distribution.manifest.get("output"), "verified atlas output")
    quad_count = _require_count(output.get("quadCount"), "verified atlas output.quadCount", positive=True)
    summary = {
        "shownConceptCount": len(concept_rows),
        "shownNativeRelationCount": len(native_relation_rows),
        "shownMappingAssertionCount": len(mapping_rows),
        "availableConceptCount": len(concepts),
        "availableNativeRelationCount": len(native_relations),
        "availableMappingAssertionCount": len(mappings),
        "truncated": (
            len(concept_rows) < len(concepts)
            or len(native_relation_rows) < len(native_relations)
            or len(mapping_rows) < len(mappings)
        ),
    }
    atlas_row: dict[str, Any] = {
        "kind": "atlas" if isinstance(distribution, VocabularyAtlasAsset) else "projection",
        "assetId": str(distribution.manifest["id"]),
        "manifestDigest": distribution.manifest_digest,
        "distributionDigest": distribution.output_digest,
        "counts": source_counts,
        "quadCount": quad_count,
    }
    if isinstance(distribution, VocabularyAtlasProjection):
        atlas_row["parent"] = distribution.parent_pin
    return {
        "type": EXPLORER_TYPE,
        "schemaVersion": EXPLORER_SCHEMA_VERSION,
        "title": clean_title,
        "atlas": atlas_row,
        "selectionPolicy": _selection_policy(
            max_concepts=concept_limit,
            max_mapping_assertions=mapping_limit,
        ),
        "summary": summary,
        "conceptReleases": release_rows,
        "concepts": concept_rows,
        "nativeRelations": native_relation_rows,
        "mappingAssertions": mapping_rows,
    }


def _artifact_row(
    path: str,
    payload: bytes,
    *,
    uncompressed: bytes | None = None,
) -> dict[str, Any]:
    role, media_type = _ARTIFACT_SPEC[path]
    result: dict[str, Any] = {
        "path": path,
        "role": role,
        "mediaType": media_type,
        "fileDigest": sha256_digest(payload),
        "byteLength": len(payload),
    }
    if uncompressed is not None:
        result.update(
            {
                "contentEncoding": "gzip",
                "uncompressedDigest": sha256_digest(uncompressed),
                "uncompressedByteLength": len(uncompressed),
            }
        )
    return result


def _publication_manifest(
    *,
    title: str,
    distribution: VocabularyAtlasDistribution,
    decision: VocabularyAtlasPublicationDecision,
    explorer: Mapping[str, Any],
    payloads: Mapping[str, bytes],
) -> dict[str, Any]:
    rows = [
        _artifact_row(
            path,
            payloads[path],
            uncompressed=distribution.payload if path == COMPRESSED_ATLAS else None,
        )
        for path in sorted(payloads)
    ]
    basis = {
        "type": _PUBLICATION_TYPE,
        "schemaVersion": PUBLICATION_SCHEMA_VERSION,
        "title": title,
        "distribution": _distribution_descriptor(distribution),
        "decision": {
            "id": decision.identifier,
            "recordDigest": decision.record_digest,
            "fileDigest": sha256_digest(decision.artifact_bytes()),
        },
        "selectionPolicy": _plain(explorer["selectionPolicy"]),
        "summary": _plain(explorer["summary"]),
        "artifacts": rows,
    }
    publication_digest = binding.canonical_sha256(basis)
    result = {
        **basis,
        "id": _PUBLICATION_ID_PREFIX + publication_digest.removeprefix("sha256:"),
        "publicationDigest": publication_digest,
    }
    result["canonicalPayloadDigest"] = binding.canonical_payload_digest(result)
    return result


def _write_publication(directory: Path | str, payloads: Mapping[str, bytes]) -> Path:
    target = Path(directory)
    if target.exists() or target.is_symlink():
        raise AtlasPublicationError(f"atlas publication destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        for name, payload in payloads.items():
            (staged / name).write_bytes(payload)
        if target.exists() or target.is_symlink():
            raise AtlasPublicationError(f"atlas publication destination already exists: {target}")
        os.replace(staged, target)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return target.resolve()


def _validate_decision(
    distribution: VocabularyAtlasDistribution,
    decision: VocabularyAtlasPublicationDecision,
    *,
    parent: VocabularyAtlasAsset | None,
) -> None:
    if not isinstance(decision, VocabularyAtlasPublicationDecision):
        raise AtlasPublicationError("publication requires a VocabularyAtlasPublicationDecision")
    try:
        decision.validate_distribution(distribution, parent=parent)
    except PublicationDecisionError as error:
        raise AtlasPublicationError(str(error)) from error


def _validate_projection_reproduction(
    distribution: VocabularyAtlasProjection,
    parent: VocabularyAtlasAsset,
) -> None:
    """Require one projection to be the exact registered cut of its parent."""

    try:
        rebuilt = build_atlas_projection(
            parent,
            policy=cast(Mapping[str, Any], distribution.manifest["projectionPolicy"]),
        )
    except (KeyError, VocabularyAtlasError) as error:
        raise AtlasPublicationError("atlas projection cannot be reproduced from its verified parent") from error
    if rebuilt.manifest_bytes() != distribution.manifest_bytes() or rebuilt.payload != distribution.payload:
        raise AtlasPublicationError("atlas projection does not reproduce from its verified parent")


@dataclass(frozen=True, slots=True, init=False)
class AtlasPublication:
    """One verified, path-backed Atlas 2.0 static publication."""

    directory: Path
    manifest: Mapping[str, Any]
    distribution: VocabularyAtlasDistribution
    decision: VocabularyAtlasPublicationDecision
    _verification_token: object

    def __init__(
        self,
        directory: Path,
        manifest: Mapping[str, Any],
        distribution: VocabularyAtlasDistribution,
        decision: VocabularyAtlasPublicationDecision,
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _PUBLICATION_CONSTRUCTION_TOKEN:
            raise TypeError("AtlasPublication must come from AtlasPublication.open()")
        object.__setattr__(self, "directory", directory)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "distribution", distribution)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "_verification_token", _PUBLICATION_CONSTRUCTION_TOKEN)

    @classmethod
    def _verified(
        cls,
        *,
        directory: Path,
        manifest: Mapping[str, Any],
        distribution: VocabularyAtlasDistribution,
        decision: VocabularyAtlasPublicationDecision,
    ) -> AtlasPublication:
        return cls(
            directory,
            manifest,
            distribution,
            decision,
            _construction_token=_PUBLICATION_CONSTRUCTION_TOKEN,
        )

    def _require_verified(self) -> None:
        if (
            getattr(self, "_verification_token", None) is not _PUBLICATION_CONSTRUCTION_TOKEN
            or not isinstance(self.directory, Path)
            or not isinstance(self.manifest, Mapping)
            or not isinstance(self.distribution, (VocabularyAtlasAsset, VocabularyAtlasProjection))
            or not isinstance(self.decision, VocabularyAtlasPublicationDecision)
        ):
            raise AtlasPublicationError("atlas publication is not a verified 2.0 publication")

    @property
    def manifest_digest(self) -> str:
        self._require_verified()
        return sha256_digest(_canonical_bytes(self.manifest))

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
        parent: VocabularyAtlasAsset | None = None,
    ) -> AtlasPublication:
        """Verify exact files, optionally reproducing a projection from its parent."""

        trusted_digest = _require_digest(
            expected_manifest_digest,
            "expected publication manifest digest",
        )
        root, payloads = _read_publication_files(directory)
        manifest_payload = payloads[PUBLICATION_MANIFEST]
        if sha256_digest(manifest_payload) != trusted_digest:
            raise AtlasPublicationError("publication external manifest digest differs")
        manifest = _load_canonical_json(manifest_payload, "publication manifest")
        _validate_publication_manifest(manifest, payloads)

        compressed = payloads[COMPRESSED_ATLAS]
        try:
            raw_atlas = gzip.decompress(compressed)
        except (OSError, EOFError) as error:
            raise AtlasPublicationError("published atlas gzip is invalid") from error
        if _gzip_bytes(raw_atlas) != compressed:
            raise AtlasPublicationError("published atlas gzip is not deterministic")
        compressed_row = next(
            cast(Mapping[str, Any], row)
            for row in cast(Sequence[Mapping[str, Any]], manifest["artifacts"])
            if row["path"] == COMPRESSED_ATLAS
        )
        if compressed_row["uncompressedDigest"] != sha256_digest(raw_atlas) or compressed_row[
            "uncompressedByteLength"
        ] != len(raw_atlas):
            raise AtlasPublicationError("published atlas uncompressed descriptor differs")

        descriptor = cast(Mapping[str, Any], manifest["distribution"])
        distribution = _open_published_distribution(
            descriptor,
            manifest_bytes=payloads[ATLAS_MANIFEST],
            scope_bytes=payloads.get(ATLAS_SCOPE),
            atlas_bytes=raw_atlas,
        )
        decision_record = _load_canonical_json(
            payloads[PUBLICATION_DECISION],
            "publication decision",
        )
        try:
            decision = VocabularyAtlasPublicationDecision.from_record(decision_record)
        except PublicationDecisionError as error:
            raise AtlasPublicationError(str(error)) from error
        _validate_opened_decision(
            distribution,
            decision,
            manifest,
            parent=parent,
        )

        explorer = _load_canonical_json(payloads[EXPLORER_DATA], "atlas explorer data")
        if (
            explorer.get("title") != manifest["title"]
            or _plain(explorer.get("selectionPolicy")) != _plain(manifest["selectionPolicy"])
            or _plain(explorer.get("summary")) != _plain(manifest["summary"])
        ):
            raise AtlasPublicationError("publication manifest differs from its exact explorer data")
        _validate_explorer(distribution, explorer)
        expected_html = render_atlas_explorer(explorer).encode("utf-8")
        if payloads[EXPLORER_HTML] != expected_html:
            raise AtlasPublicationError("offline explorer HTML differs from its exact explorer data")

        return cls._verified(
            directory=root,
            manifest=cast(Mapping[str, Any], deep_freeze_json(manifest)),
            distribution=distribution,
            decision=decision,
        )


def _descriptor_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode))


def _descriptor_state(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        *_descriptor_identity(metadata),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _no_follow_flags(*, directory: bool = False) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None or not _DESCRIPTOR_RELATIVE_READS_SUPPORTED:
        raise AtlasPublicationError(
            "secure descriptor-relative no-follow publication reads are unsupported on this platform"
        )
    flags = os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if directory:
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if directory_flag is None:
            raise AtlasPublicationError("secure no-follow publication directory reads are unsupported on this platform")
        flags |= directory_flag
    return flags


def _read_regular_file_at(
    root_descriptor: int,
    name: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int, int]]:
    try:
        descriptor = os.open(
            name,
            _no_follow_flags(),
            dir_fd=root_descriptor,
        )
    except OSError as error:
        raise AtlasPublicationError("atlas publication must contain regular files and no symlinks") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AtlasPublicationError("atlas publication must contain regular files and no symlinks")
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, _READ_CHUNK_SIZE))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        extra = os.read(descriptor, 1)
        after = os.fstat(descriptor)
    except OSError as error:
        raise AtlasPublicationError("atlas publication changed while opening") from error
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if remaining or extra or _descriptor_state(before) != _descriptor_state(after):
        raise AtlasPublicationError("atlas publication changed while opening")
    return payload, _descriptor_state(after)


def _read_publication_files(directory: Path | str) -> tuple[Path, dict[str, bytes]]:
    selected = Path(directory).absolute()
    try:
        root_descriptor = os.open(selected, _no_follow_flags(directory=True))
    except OSError as error:
        raise AtlasPublicationError("atlas publication path must be an existing non-symlink directory") from error
    try:
        root_before = os.fstat(root_descriptor)
        if not stat.S_ISDIR(root_before.st_mode):
            raise AtlasPublicationError("atlas publication path must be a directory")
        entries = set(os.listdir(root_descriptor))
        if PUBLICATION_MANIFEST not in entries:
            raise AtlasPublicationError("atlas publication has no publication manifest")
        payloads: dict[str, bytes] = {}
        states: dict[str, tuple[int, int, int, int, int, int, int]] = {}
        for name in entries:
            payloads[name], states[name] = _read_regular_file_at(root_descriptor, name)

        manifest = _load_canonical_json(payloads[PUBLICATION_MANIFEST], "publication manifest")
        artifacts = _require_sequence(manifest.get("artifacts"), "publication manifest artifacts")
        declared_paths = {
            _require_text(_require_mapping(row, "publication artifact").get("path"), "publication artifact.path")
            for row in artifacts
        }
        expected = declared_paths | {PUBLICATION_MANIFEST}
        if entries != expected:
            raise AtlasPublicationError("atlas publication file set differs from its manifest")

        final_entries = set(os.listdir(root_descriptor))
        if final_entries != expected:
            raise AtlasPublicationError("atlas publication changed while opening")
        for name in expected:
            final_payload, final_state = _read_regular_file_at(root_descriptor, name)
            if final_state != states[name] or final_payload != payloads[name]:
                raise AtlasPublicationError("atlas publication changed while opening")
        if _descriptor_state(os.fstat(root_descriptor)) != _descriptor_state(root_before):
            raise AtlasPublicationError("atlas publication changed while opening")

        try:
            current = os.stat(selected, follow_symlinks=False)
            resolved = selected.resolve(strict=True)
            resolved_metadata = os.stat(resolved, follow_symlinks=False)
        except OSError as error:
            raise AtlasPublicationError("atlas publication changed while opening") from error
        root_identity = _descriptor_identity(root_before)
        if (
            not stat.S_ISDIR(current.st_mode)
            or _descriptor_identity(current) != root_identity
            or _descriptor_identity(resolved_metadata) != root_identity
        ):
            raise AtlasPublicationError("atlas publication changed while opening")
        return resolved, payloads
    finally:
        os.close(root_descriptor)


def _validate_parent(value: object, label: str) -> dict[str, str]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _PARENT_FIELDS, label)
    return {
        "assetId": _require_text(row.get("assetId"), f"{label}.assetId"),
        "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
        "distributionDigest": _require_digest(
            row.get("distributionDigest"),
            f"{label}.distributionDigest",
        ),
    }


def _validate_distribution_descriptor(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "publication distribution")
    kind = row.get("kind")
    expected = _ATLAS_DISTRIBUTION_FIELDS if kind == "atlas" else _PROJECTION_DISTRIBUTION_FIELDS
    if kind not in {"atlas", "projection"}:
        raise AtlasPublicationError("publication distribution kind must be atlas or projection")
    _require_exact_fields(row, expected, "publication distribution")
    result: dict[str, Any] = {
        "kind": kind,
        "assetId": _require_text(row.get("assetId"), "publication distribution.assetId"),
        "manifestDigest": _require_digest(
            row.get("manifestDigest"),
            "publication distribution.manifestDigest",
        ),
        "distributionDigest": _require_digest(
            row.get("distributionDigest"),
            "publication distribution.distributionDigest",
        ),
    }
    if kind == "projection":
        result["parent"] = _validate_parent(row.get("parent"), "publication distribution.parent")
    return result


def _validate_selection(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "publication selectionPolicy")
    _require_exact_fields(row, _SELECTION_FIELDS, "publication selectionPolicy")
    if (
        row.get("id") != _SELECTION_POLICY_ID
        or row.get("type") != "boundedExplorerView"
        or row.get("version") != EXPLORER_SCHEMA_VERSION
    ):
        raise AtlasPublicationError("publication selectionPolicy is unsupported")
    return {
        "id": _SELECTION_POLICY_ID,
        "type": "boundedExplorerView",
        "version": EXPLORER_SCHEMA_VERSION,
        "maxConcepts": _require_count(
            row.get("maxConcepts"),
            "publication selectionPolicy.maxConcepts",
            positive=True,
        ),
        "maxMappingAssertions": _require_count(
            row.get("maxMappingAssertions"),
            "publication selectionPolicy.maxMappingAssertions",
        ),
    }


def _validate_summary(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "publication summary")
    _require_exact_fields(row, _SUMMARY_FIELDS, "publication summary")
    result = {
        field: _require_count(row.get(field), f"publication summary.{field}")
        for field in _SUMMARY_FIELDS - {"truncated"}
    }
    if not isinstance(row.get("truncated"), bool):
        raise AtlasPublicationError("publication summary.truncated must be boolean")
    result["truncated"] = row["truncated"]
    if cast(int, result["shownConceptCount"]) > cast(int, result["availableConceptCount"]) or cast(
        int, result["shownMappingAssertionCount"]
    ) > cast(int, result["availableMappingAssertionCount"]):
        raise AtlasPublicationError("publication summary shown counts exceed available counts")
    return result


def _validate_publication_manifest(
    manifest: Mapping[str, Any],
    payloads: Mapping[str, bytes],
) -> None:
    _require_exact_fields(manifest, _PUBLICATION_FIELDS, "publication manifest")
    if manifest.get("type") != _PUBLICATION_TYPE or manifest.get("schemaVersion") != PUBLICATION_SCHEMA_VERSION:
        raise AtlasPublicationError("publication manifest version or type is unsupported")
    _require_text(manifest.get("title"), "publication manifest.title")
    distribution = _validate_distribution_descriptor(manifest.get("distribution"))
    decision = _require_mapping(manifest.get("decision"), "publication decision descriptor")
    _require_exact_fields(decision, _DECISION_FIELDS, "publication decision descriptor")
    _require_text(decision.get("id"), "publication decision descriptor.id")
    _require_digest(decision.get("recordDigest"), "publication decision descriptor.recordDigest")
    _require_digest(decision.get("fileDigest"), "publication decision descriptor.fileDigest")
    selection = _validate_selection(manifest.get("selectionPolicy"))
    summary = _validate_summary(manifest.get("summary"))

    rows = _require_sequence(manifest.get("artifacts"), "publication manifest artifacts")
    expected_paths = set(_ARTIFACT_SPEC) if distribution["kind"] == "atlas" else set(_ARTIFACT_SPEC) - {ATLAS_SCOPE}
    normalized_rows = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(rows):
        label = f"publication manifest artifacts[{index}]"
        row = _require_mapping(raw, label)
        path = _require_text(row.get("path"), f"{label}.path")
        expected_spec = _ARTIFACT_SPEC.get(path)
        if expected_spec is None or path in seen_paths:
            raise AtlasPublicationError("publication artifact paths must be unique supported files")
        seen_paths.add(path)
        fields = _COMPRESSED_ARTIFACT_FIELDS if path == COMPRESSED_ATLAS else _ARTIFACT_FIELDS
        _require_exact_fields(row, fields, label)
        role, media_type = expected_spec
        if row.get("role") != role or row.get("mediaType") != media_type:
            raise AtlasPublicationError(f"{label} role or media type differs")
        file_digest = _require_digest(row.get("fileDigest"), f"{label}.fileDigest")
        byte_length = _require_count(row.get("byteLength"), f"{label}.byteLength")
        payload = payloads.get(path)
        if payload is None or sha256_digest(payload) != file_digest or len(payload) != byte_length:
            raise AtlasPublicationError(f"{label} differs from the published bytes")
        normalized = dict(row)
        if path == COMPRESSED_ATLAS:
            if row.get("contentEncoding") != "gzip":
                raise AtlasPublicationError("compressed atlas contentEncoding must be gzip")
            _require_digest(row.get("uncompressedDigest"), f"{label}.uncompressedDigest")
            _require_count(row.get("uncompressedByteLength"), f"{label}.uncompressedByteLength")
        normalized_rows.append(normalized)
    if seen_paths != expected_paths:
        raise AtlasPublicationError("publication artifact set differs from its distribution kind")
    if normalized_rows != sorted(normalized_rows, key=lambda row: row["path"]):
        raise AtlasPublicationError("publication artifacts must be ordered by path")

    basis = {field: _plain(manifest[field]) for field in _PUBLICATION_BASIS_FIELDS}
    publication_digest = binding.canonical_sha256(basis)
    if manifest.get("publicationDigest") != publication_digest or manifest.get(
        "id"
    ) != _PUBLICATION_ID_PREFIX + publication_digest.removeprefix("sha256:"):
        raise AtlasPublicationError("publication manifest content-derived identity differs")
    if manifest.get("canonicalPayloadDigest") != binding.canonical_payload_digest(dict(manifest)):
        raise AtlasPublicationError("publication manifest canonicalPayloadDigest differs")
    if _plain(manifest["selectionPolicy"]) != selection or _plain(manifest["summary"]) != summary:
        raise AtlasPublicationError("publication manifest normalized fields differ")


def _open_published_distribution(
    descriptor: Mapping[str, Any],
    *,
    manifest_bytes: bytes,
    scope_bytes: bytes | None,
    atlas_bytes: bytes,
) -> VocabularyAtlasDistribution:
    manifest_digest = cast(str, descriptor["manifestDigest"])
    if sha256_digest(manifest_bytes) != manifest_digest:
        raise AtlasPublicationError("source distribution manifest digest differs")
    if sha256_digest(atlas_bytes) != descriptor["distributionDigest"]:
        raise AtlasPublicationError("source distribution N-Quads digest differs")
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-publication-open-") as temporary_name:
        temporary = Path(temporary_name)
        (temporary / MANIFEST_FILE).write_bytes(manifest_bytes)
        (temporary / ATLAS_FILE).write_bytes(atlas_bytes)
        try:
            if descriptor["kind"] == "atlas":
                if scope_bytes is None:
                    raise AtlasPublicationError("canonical atlas publication has no exact scope bytes")
                (temporary / SCOPE_FILE).write_bytes(scope_bytes)
                distribution: VocabularyAtlasDistribution = VocabularyAtlasAsset.open(
                    temporary,
                    expected_manifest_digest=manifest_digest,
                )
            else:
                if scope_bytes is not None:
                    raise AtlasPublicationError("atlas projection publication must not carry a canonical scope")
                distribution = VocabularyAtlasProjection.open(
                    temporary,
                    expected_manifest_digest=manifest_digest,
                )
        except VocabularyAtlasError as error:
            raise AtlasPublicationError(str(error)) from error
    if _distribution_descriptor(distribution) != _plain(descriptor):
        raise AtlasPublicationError("published distribution descriptor differs from its exact files")
    return distribution


def _validate_opened_decision(
    distribution: VocabularyAtlasDistribution,
    decision: VocabularyAtlasPublicationDecision,
    manifest: Mapping[str, Any],
    *,
    parent: VocabularyAtlasAsset | None,
) -> None:
    descriptor = _require_mapping(manifest["decision"], "publication decision descriptor")
    if (
        decision.identifier != descriptor["id"]
        or decision.record_digest != descriptor["recordDigest"]
        or sha256_digest(decision.artifact_bytes()) != descriptor["fileDigest"]
    ):
        raise AtlasPublicationError("publication decision descriptor differs from its exact bytes")
    expected_kind = "atlas" if isinstance(distribution, VocabularyAtlasAsset) else "projection"
    if decision.artifact_kind != expected_kind:
        raise AtlasPublicationError("publication decision artifact kind differs from the distribution")
    result: dict[str, Any] = {
        "role": "VocabularyAtlas" if expected_kind == "atlas" else "VocabularyAtlasProjection",
        "id": str(distribution.manifest["id"]),
        "manifestDigest": distribution.manifest_digest,
        "distributionDigest": distribution.output_digest,
    }
    if isinstance(distribution, VocabularyAtlasProjection):
        result["parent"] = distribution.parent_pin
    try:
        decision.validate_result(result)
        if isinstance(distribution, VocabularyAtlasAsset) or parent is not None:
            decision.validate_distribution(distribution, parent=parent)
    except PublicationDecisionError as error:
        raise AtlasPublicationError(str(error)) from error
    if isinstance(distribution, VocabularyAtlasProjection):
        policy = _plain(distribution.manifest["projectionPolicy"])
        expected_pin = {
            "role": "projectionPolicy",
            "id": policy["id"],
            "version": policy["version"],
            "contentDigest": sha256_digest(canonical_json_bytes(policy)),
        }
        decision_policies = cast(Sequence[Mapping[str, Any]], decision.record["policies"])
        actual = [dict(row) for row in decision_policies if row.get("role") == "projectionPolicy"]
        if actual != [expected_pin]:
            raise AtlasPublicationError("publication decision projection policy differs from the distribution")
        if parent is not None:
            _validate_projection_reproduction(distribution, parent)


def _validate_explorer(
    distribution: VocabularyAtlasDistribution,
    explorer: Mapping[str, Any],
) -> None:
    if explorer.get("type") != EXPLORER_TYPE or explorer.get("schemaVersion") != EXPLORER_SCHEMA_VERSION:
        raise AtlasPublicationError("atlas explorer type or version is unsupported")
    title = _require_text(explorer.get("title"), "atlas explorer title")
    selection = _validate_selection(explorer.get("selectionPolicy"))
    releases = _require_sequence(
        explorer.get("conceptReleases"),
        "atlas explorer conceptReleases",
    )
    release_labels: dict[str, str] = {}
    for index, raw in enumerate(releases):
        row = _require_mapping(raw, f"atlas explorer conceptReleases[{index}]")
        identifier = _require_text(
            row.get("releaseId"),
            f"atlas explorer conceptReleases[{index}].releaseId",
        )
        label = _require_text(
            row.get("label"),
            f"atlas explorer conceptReleases[{index}].label",
        )
        if identifier in release_labels:
            raise AtlasPublicationError("atlas explorer repeats a release")
        release_labels[identifier] = label
    rebuilt = build_explorer_model(
        distribution,
        title=title,
        release_labels=release_labels,
        max_concepts=selection["maxConcepts"],
        max_mapping_assertions=selection["maxMappingAssertions"],
    )
    if _plain(explorer) != rebuilt:
        raise AtlasPublicationError("atlas explorer data differs from the verified distribution")


def publish_vocabulary_atlas(
    distribution: VocabularyAtlasDistribution,
    directory: Path | str,
    *,
    decision: VocabularyAtlasPublicationDecision,
    parent: VocabularyAtlasAsset | None = None,
    title: str = "RefSpec vocabulary atlas",
    release_labels: Mapping[str, str] | None = None,
    max_concepts: int | None = _DEFAULT_MAX_CONCEPTS,
    max_mapping_assertions: int | None = _DEFAULT_MAX_MAPPING_ASSERTIONS,
) -> AtlasPublication:
    """Publish one verified, explicitly authorized Atlas 2.0 distribution."""

    _verified_distribution(distribution)
    _validate_decision(distribution, decision, parent=parent)
    if isinstance(distribution, VocabularyAtlasProjection):
        if parent is None:  # The decision check above normally supplies the specific error.
            raise AtlasPublicationError("atlas projection publication requires its verified atlas parent")
        _validate_projection_reproduction(distribution, parent)
    explorer = build_explorer_model(
        distribution,
        title=title,
        release_labels=release_labels,
        max_concepts=max_concepts,
        max_mapping_assertions=max_mapping_assertions,
    )
    explorer_bytes = _canonical_bytes(explorer)
    payloads: dict[str, bytes] = {
        ATLAS_MANIFEST: distribution.manifest_bytes(),
        COMPRESSED_ATLAS: _gzip_bytes(distribution.payload),
        PUBLICATION_DECISION: decision.artifact_bytes(),
        EXPLORER_DATA: explorer_bytes,
        EXPLORER_HTML: render_atlas_explorer(explorer).encode("utf-8"),
    }
    if isinstance(distribution, VocabularyAtlasAsset):
        payloads[ATLAS_SCOPE] = distribution.scope_payload
    manifest = _publication_manifest(
        title=cast(str, explorer["title"]),
        distribution=distribution,
        decision=decision,
        explorer=explorer,
        payloads=payloads,
    )
    payloads[PUBLICATION_MANIFEST] = _canonical_bytes(manifest)
    target = _write_publication(directory, payloads)
    return AtlasPublication.open(
        target,
        expected_manifest_digest=sha256_digest(payloads[PUBLICATION_MANIFEST]),
        parent=parent,
    )


def _release_label_values(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        identifier, separator, label = value.partition("=")
        if not separator or not identifier.strip() or not label.strip():
            raise AtlasPublicationError("--release-label must be RELEASE_ID=LABEL")
        identifier = identifier.strip()
        label = label.strip()
        if identifier in result:
            raise AtlasPublicationError("--release-label repeats a release id")
        result[identifier] = label
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m refspec.atlas.publication",
        description="Publish an exact, authorized Atlas 2.0 distribution.",
    )
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--distribution-manifest-digest", required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--decision-file-digest", required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--parent-manifest-digest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="RefSpec vocabulary atlas")
    parser.add_argument(
        "--max-concepts",
        type=int,
        default=_DEFAULT_MAX_CONCEPTS,
        help="optional explorer index limit; omitted indexes every concept",
    )
    parser.add_argument(
        "--max-mapping-assertions",
        type=int,
        default=_DEFAULT_MAX_MAPPING_ASSERTIONS,
        help="optional explorer index limit; omitted indexes every mapping assertion",
    )
    parser.add_argument("--release-label", action="append", default=[], metavar="RELEASE_ID=LABEL")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        kind = distribution_kind(args.distribution)
        parent: VocabularyAtlasAsset | None = None
        if kind == "vocabularyAtlas":
            if args.parent is not None or args.parent_manifest_digest is not None:
                raise AtlasPublicationError("canonical atlas publication does not accept --parent")
            distribution: VocabularyAtlasDistribution = VocabularyAtlasAsset.open(
                args.distribution,
                expected_manifest_digest=args.distribution_manifest_digest,
            )
        else:
            if args.parent is None or args.parent_manifest_digest is None:
                raise AtlasPublicationError(
                    "atlas projection publication requires --parent and --parent-manifest-digest"
                )
            distribution = VocabularyAtlasProjection.open(
                args.distribution,
                expected_manifest_digest=args.distribution_manifest_digest,
            )
            parent = VocabularyAtlasAsset.open(
                args.parent,
                expected_manifest_digest=args.parent_manifest_digest,
            )
        decision = read_vocabulary_atlas_publication_decision(
            args.decision,
            expected_file_digest=args.decision_file_digest,
        )
        publication = publish_vocabulary_atlas(
            distribution,
            args.output,
            decision=decision,
            parent=parent,
            title=args.title,
            release_labels=_release_label_values(args.release_label),
            max_concepts=args.max_concepts,
            max_mapping_assertions=args.max_mapping_assertions,
        )
    except (AtlasPublicationError, PublicationDecisionError, VocabularyAtlasError) as error:
        parser.error(str(error))
    print(publication.manifest_digest)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ATLAS_MANIFEST",
    "ATLAS_SCOPE",
    "COMPRESSED_ATLAS",
    "EXPLORER_DATA",
    "EXPLORER_HTML",
    "EXPLORER_SCHEMA_VERSION",
    "PUBLICATION_DECISION",
    "PUBLICATION_MANIFEST",
    "PUBLICATION_SCHEMA_VERSION",
    "AtlasPublication",
    "AtlasPublicationError",
    "build_explorer_model",
    "main",
    "publish_vocabulary_atlas",
]

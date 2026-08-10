"""Legacy RDF-backed Atlas explorer and shared browser renderer."""

from __future__ import annotations

import gzip
import hashlib
import heapq
import html
import json
import os
import re
import stat
import tempfile
import unicodedata
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from string import Template
from typing import Any, BinaryIO, TypeVar, cast

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - exercised on supported Python 3.10-3.13
    from backports import zstd

from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS
from rdflib.util import from_n3

from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import SEMANTIC_RINGS as _RINGS

ATLAS_V3_EXPLORER_TYPE = "urn:ref:type:Atlas3ExplorerView"
ATLAS_V3_EXPLORER_SCHEMA_VERSION = "3.0"

# These familiar names now identify Atlas 3.0. They are aliases, not a legacy
# Atlas 2 reader or wire-format compatibility layer.
EXPLORER_TYPE = ATLAS_V3_EXPLORER_TYPE
EXPLORER_SCHEMA_VERSION = ATLAS_V3_EXPLORER_SCHEMA_VERSION

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")

_ROOT_MANIFEST = "atlas-manifest.json"
_SOURCE_ACCOUNTING_MEMBER = "atlas-source-accounting.json"
_ACCEPTANCE_MEMBER = "atlas-acceptance.json"
_PRODUCER_VALIDATION_MEMBER = "atlas-producer-validation.json"
_CONSTRUCTION_SUMMARY_MEMBER = "atlas-construction-summary.json"
REQUIRED_ACCEPTANCE_GATES = frozenset(
    {
        "canonical-json",
        "json-schema",
        "rdf-syntax",
        "ontology-profile",
        "shacl-meta",
        "shacl-data",
        "dataset-closure",
        "source-accounting",
        "projection-parity",
        "reasoning-isolation",
        "profile-conformance",
    }
)
RESOURCE_TYPES = frozenset(
    {
        ATLAS.SubjectConcept,
        ATLAS.EntityResource,
        ATLAS.ValueResource,
        ATLAS.LegalIdentityResource,
    }
)
RELATION_TYPES = (
    (ATLAS.MappingAssertion, "mapping"),
    (ATLAS.NativeRelationAssertion, "native"),
    (ATLAS.SourceAssignment, "sourceAssignment"),
    (ATLAS.CrossRingRelationAssertion, "crossRing"),
)
LABEL_ROLES = (
    (SKOSXL.prefLabel, "preferred"),
    (SKOSXL.altLabel, "alternate"),
    (SKOSXL.hiddenLabel, "hidden"),
)
PREDICATE_MEANINGS = {
    str(SKOS.broader): "The subject is narrower than the object in the publisher's hierarchy.",
    str(SKOS.narrower): "The subject is broader than the object in the publisher's hierarchy.",
    str(SKOS.related): "The publisher asserted a direct associative SKOS relationship.",
    str(SKOS.exactMatch): "The concepts have an exact match across two exact releases.",
    str(SKOS.closeMatch): "The concepts are similar enough for some cross-vocabulary retrieval uses.",
    str(SKOS.broadMatch): "The subject maps to a broader concept in another exact release.",
    str(SKOS.narrowMatch): "The subject maps to a narrower concept in another exact release.",
    str(SKOS.relatedMatch): "The subject maps associatively to a concept in another exact release.",
    str(ATLAS.thesaurusUse): (
        "Use the object as the publisher's preferred term for the non-preferred subject term."
    ),
    str(ATLAS.thesaurusUsedFor): (
        "The preferred subject term is used for the non-preferred object term."
    ),
    str(ATLAS.thesaurusRelated): (
        "The publisher asserted this direct associative link. Atlas preserves it outside skos:related "
        "when a hierarchy path makes that SKOS projection unsafe; the link remains directly relevant."
    ),
    str(ATLAS.hasIndexedSubject): (
        "The entity or legal identity is indexed under the subject concept."
    ),
    str(ATLAS.referencesLegalIdentity): (
        "The entity record explicitly references the legal identity."
    ),
}

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
_SAFE_INTEGER = 9_007_199_254_740_991
_NQUADS_MAX_LINE_BYTES = 16 * 1024 * 1024
_SOURCE_ACCOUNTING_INLINE_MAX_BYTES = 16 * 1024 * 1024

_MAPPING_PROVENANCE_PAYLOAD_FIELDS = frozenset(
    {
        "currentEuroVocRelease",
        "currentMetadataRequalifiesIndividualPairs",
        "objectIri",
        "predicateIri",
        "publisherAlignmentDigest",
        "publisherAlignmentIssued",
        "publisherAlignmentRelease",
        "publisherAlignmentVersion",
        "publisherEuroVocRelease",
        "publisherEuroVocVersion",
        "publisherLcshRelease",
        "subjectIri",
    }
)

# The HTML keeps a small, self-contained visual fallback for file:// review.
# Full-corpus HTTP browsing uses verified static shards and is not bounded by
# these fallback materialization limits.
_VISUAL_RESOURCE_LIMIT = 2_000
_VISUAL_IDENTIFIER_LIMIT = 500
_VISUAL_TOPIC_ASSERTION_LIMIT = 2_000
_VISUAL_SOURCE_ASSIGNMENT_LIMIT = 200
_VISUAL_PROJECTED_RELATION_LIMIT = 500
_VISUAL_DERIVED_RELATION_LIMIT = 100
_VISUAL_RELATION_RESOURCE_BUDGET = 1_500
_VISUAL_PROVENANCE_ASSERTION_LIMIT = 4_000
_VISUAL_CANDIDATE_MULTIPLIER = 4
_VISUAL_MAX_RELATION_REFERENCES = 64
_EXPLORER_RECORD_PREFIX_LENGTH = 3
_EXPLORER_JOIN_PREFIX_LENGTH = 3
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
_MANIFEST_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "format",
        "distributionId",
        "createdAt",
        "binding",
        "graphs",
        "packs",
        "members",
        "counts",
        "canonicalPayloadDigest",
    }
)
_GRAPH_FIELDS = frozenset(
    {"role", "id", "quadCount", "packCount", "inventoryDigest"}
)
_PRODUCER_VALIDATION_FIELDS = frozenset(
    {
        "assertedInventoryDigest",
        "binding",
        "checks",
        "constructionSummary",
        "constructorProfile",
        "counts",
        "implementationDigest",
        "mode",
        "shaclDataProof",
        "shaclMetaValidation",
        "sourceAccountingDigest",
        "sourceReleaseCount",
        "status",
        "type",
        "version",
    }
)
_CONSTRUCTION_SUMMARY_FIELDS = frozenset(
    {
        "assertedInventoryDigest",
        "bindingBundleDigest",
        "canonicalPayloadDigest",
        "catalog",
        "compactPackCount",
        "compactPackInventoryDigest",
        "compactPacks",
        "distributionId",
        "profile",
        "recipeDigest",
        "releaseCount",
        "releaseInventoryDigest",
        "releases",
        "sourceAccountingDigest",
        "type",
        "version",
    }
)
_COMPACT_PACK_FIELDS = frozenset(
    {
        "packId",
        "role",
        "path",
        "dependencies",
        "defaults",
        "logicalRowsDigest",
        "recordSchemaVersion",
        "globalInvariantSummary",
        "content",
        "transport",
        "partition",
    }
)
_COMPACT_PACK_REQUIRED_FIELDS = _COMPACT_PACK_FIELDS - {"partition"}
_COMPACT_RECORD_ROLES = frozenset(
    {
        "Resource",
        "Label",
        "Statement",
        "EvidenceBinding",
        "SourceRecord",
        "Release",
        "Identifier",
        "LifecycleEvent",
    }
)
_PACK_FIELDS = frozenset(
    {
        "packId",
        "kind",
        "path",
        "transport",
        "content",
        "graphCounts",
        "dependencies",
        "sourceReleases",
        "rings",
        "partition",
        "inputAssertedDigest",
    }
)
_PACK_REQUIRED_FIELDS = frozenset(
    {
        "packId",
        "kind",
        "path",
        "transport",
        "content",
        "graphCounts",
        "dependencies",
        "sourceReleases",
        "rings",
    }
)
_PACK_KINDS = frozenset({"catalog", "sourceRelease", "mapping", "view", "aggregate"})
_BINDING_FIELDS = frozenset(
    {
        "version",
        "bindingBundleDigest",
        "ontologyDigest",
        "shapesDigest",
        "manifestSchemaDigest",
        "sourceAccountingSchemaDigest",
        "acceptanceSchemaDigest",
        "validatorVersion",
    }
)
_COUNT_FIELDS = frozenset(
    {
        "releases",
        "resources",
        "identifiers",
        "labels",
        "sourceRecords",
        "relationAssertions",
        "crossRingRelationAssertions",
        "mappingAssertions",
        "nativeRelationAssertions",
        "sourceAssignments",
        "projectedRelations",
        "derivedRelations",
    }
)
_BINDING_ROOT = Path(__file__).resolve().parents[3] / "bindings" / "atlas" / "3.0"
_BINDING_BUNDLE_PATHS = (
    Path("README.md"),
    Path("fixtures/corpus.json"),
    Path("ontology/atlas.ttl"),
    Path("registry-resource-profiles.json"),
    Path("requirements.txt"),
    Path("shapes/atlas.shacl.ttl"),
    Path("tests/registry-coverage.json"),
    Path("tests/registry-descriptors.json"),
    Path("tests/registry-descriptors.nq"),
    Path("tools/build_fixtures.py"),
    Path("tools/rdf_canonical.py"),
    Path("tools/validate.py"),
)


class Atlas3ExplorerError(ValueError):
    """An Atlas 3.0 distribution or explorer model is unsafe to consume."""


AtlasExplorerError = Atlas3ExplorerError

_LimitedRow = TypeVar("_LimitedRow")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Atlas3ExplorerError(f"Atlas 3.0 JSON repeats key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise Atlas3ExplorerError(f"Atlas 3.0 JSON contains non-finite number {token}")


def _validate_json_value(value: object, label: str) -> None:
    if value is None or isinstance(value, float):
        raise Atlas3ExplorerError(f"{label} uses a forbidden null or floating-point value")
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > _SAFE_INTEGER:
        raise Atlas3ExplorerError(f"{label} contains an unsafe integer")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise Atlas3ExplorerError(f"{label} contains a non-text object key")
            _validate_json_value(child, f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{label}[{index}]")


def _read_canonical_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Atlas3ExplorerError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise Atlas3ExplorerError(f"{label} must be a JSON object")
    _validate_json_value(value, label)
    if canonical_json_bytes(value) != payload:
        raise Atlas3ExplorerError(f"{label} is not canonical JSON")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Atlas3ExplorerError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise Atlas3ExplorerError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _json_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_copy(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_copy(child) for child in value]
    return value


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


def _iri_name(value: object) -> str:
    text_value = str(value)
    if "#" in text_value:
        return text_value.rsplit("#", 1)[-1]
    return text_value.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _one(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    label: str,
    required: bool = True,
) -> object | None:
    values = tuple(graph.objects(subject, predicate))
    if len(values) > 1 or (required and not values):
        qualifier = "exactly one" if required else "at most one"
        raise Atlas3ExplorerError(f"{label} must have {qualifier} {predicate}")
    return values[0] if values else None


def _json_literal(value: object | None, label: str) -> object | None:
    if value is None:
        return None
    if not isinstance(value, Literal):
        raise Atlas3ExplorerError(f"{label} must be an RDF JSON literal")
    try:
        return json.loads(str(value), object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise Atlas3ExplorerError(f"{label} must contain valid JSON") from error


def _literal_view(value: Literal) -> dict[str, str]:
    result = {"value": str(value)}
    if value.language:
        result["language"] = value.language
    if value.datatype:
        result["datatype"] = str(value.datatype)
    return result


def _english_display_literal(value: Literal) -> bool:
    """Treat explicit English and language-neutral publisher text as displayable."""

    return value.language is None or value.language.casefold() == "en"


def atlas_v3_predicate_meaning(predicate_iri: str) -> str:
    """Explain a relation without weakening or changing its source semantics."""

    return PREDICATE_MEANINGS.get(
        predicate_iri,
        "A relation preserved with its exact publisher or editorial predicate.",
    )


def _canonical_digest_without_lf(value: object) -> str:
    payload = canonical_json_bytes(value)
    if not payload.endswith(b"\n"):
        raise Atlas3ExplorerError("canonical JSON encoder omitted its expected terminal LF")
    return sha256_digest(payload[:-1])


def _canonical_digest(value: object) -> str:
    """Digest the binding's newline-terminated canonical JSON form."""

    return sha256_digest(canonical_json_bytes(value))


def _nquad_iri_token(value: object) -> bytes:
    return f"<{value}>".encode()


_RDF_TYPE_TOKEN = _nquad_iri_token(RDF.type)
_PROV_HAD_MEMBER_TOKEN = _nquad_iri_token(PROV.hadMember)
_DCTERMS_TITLE_TOKEN = _nquad_iri_token(DCTERMS.title)
_ATLAS_IN_RELEASE_TOKEN = _nquad_iri_token(ATLAS.inRelease)
_ATLAS_IN_SOURCE_RELEASE_TOKEN = _nquad_iri_token(ATLAS.inSourceRelease)
_ATLAS_SEMANTIC_RING_TOKEN = _nquad_iri_token(ATLAS.semanticRing)
_ATLAS_SOURCE_RING_TOKEN = _nquad_iri_token(ATLAS.sourceRing)
_ATLAS_TARGET_RING_TOKEN = _nquad_iri_token(ATLAS.targetRing)
_ATLAS_IDENTIFIER_SCHEME_TOKEN = _nquad_iri_token(ATLAS.identifierScheme)
_ATLAS_IDENTIFIES_TOKEN = _nquad_iri_token(ATLAS.identifies)
_ATLAS_ASSERTION_STATUS_TOKEN = _nquad_iri_token(ATLAS.assertionStatus)
_ATLAS_REPRESENTS_RESOURCE_TOKEN = _nquad_iri_token(ATLAS.representsResource)
_RDF_SUBJECT_TOKEN = _nquad_iri_token(RDF.subject)
_RDF_PREDICATE_TOKEN = _nquad_iri_token(RDF.predicate)
_RDF_OBJECT_TOKEN = _nquad_iri_token(RDF.object)
_ATLAS_RELATION_SUBJECT_TOKEN = _nquad_iri_token(ATLAS.relationSubject)
_ATLAS_RELATION_PREDICATE_TOKEN = _nquad_iri_token(ATLAS.relationPredicate)
_ATLAS_RELATION_OBJECT_TOKEN = _nquad_iri_token(ATLAS.relationObject)
_ATLAS_SUPPORTING_ASSERTION_TOKEN = _nquad_iri_token(ATLAS.supportingAssertion)
_ATLAS_DERIVED_FROM_ASSERTION_TOKEN = _nquad_iri_token(ATLAS.derivedFromAssertion)
_ATLAS_GOVERNED_BY_POLICY_TOKEN = _nquad_iri_token(ATLAS.governedByPolicy)
_ATLAS_BINDS_ASSERTION_TOKEN = _nquad_iri_token(RKAF.bindsAssertion)
_ATLAS_EVIDENCE_SOURCE_RECORD_TOKEN = _nquad_iri_token(ATLAS.evidenceSourceRecord)
_ATLAS_SOURCE_RECORD_TOKEN = _nquad_iri_token(ATLAS.sourceRecord)
_SKOSXL_LITERAL_FORM_TOKEN = _nquad_iri_token(SKOSXL.literalForm)
_LABEL_PREDICATE_TOKENS = frozenset(_nquad_iri_token(predicate) for predicate, _role in LABEL_ROLES)

_ATLAS_RELEASE_TYPE_TOKEN = _nquad_iri_token(ATLAS.AtlasRelease)
_SOURCE_RELEASE_TYPE_TOKEN = _nquad_iri_token(ATLAS.SourceRelease)
_ATLAS_RESOURCE_TYPE_TOKEN = _nquad_iri_token(ATLAS.AtlasResource)
_IDENTIFIER_TYPE_TOKEN = _nquad_iri_token(ATLAS.Identifier)
_LABEL_TYPE_TOKEN = _nquad_iri_token(SKOSXL.Label)
_SOURCE_RECORD_TYPE_TOKEN = _nquad_iri_token(ATLAS.SourceRecord)
_RELATION_ASSERTION_TYPE_TOKEN = _nquad_iri_token(ATLAS.RelationAssertion)
_MAPPING_ASSERTION_TYPE_TOKEN = _nquad_iri_token(ATLAS.MappingAssertion)
_NATIVE_ASSERTION_TYPE_TOKEN = _nquad_iri_token(ATLAS.NativeRelationAssertion)
_SOURCE_ASSIGNMENT_TYPE_TOKEN = _nquad_iri_token(ATLAS.SourceAssignment)
_CROSS_RING_ASSERTION_TYPE_TOKEN = _nquad_iri_token(ATLAS.CrossRingRelationAssertion)
_PROJECTED_RELATION_TYPE_TOKEN = _nquad_iri_token(ATLAS.ProjectedRelation)
_DERIVED_RELATION_TYPE_TOKEN = _nquad_iri_token(ATLAS.DerivedRelation)
_CURRENT_STATUS_TOKEN = _nquad_iri_token(ATLAS.current)
_SOURCE_ASSIGNMENT_PREDICATE_TOKENS = frozenset(
    {
        _nquad_iri_token(ATLAS.assignedSubject),
        _nquad_iri_token(ATLAS.assignedEntity),
        _nquad_iri_token(ATLAS.assignedValue),
        _nquad_iri_token(ATLAS.assignedLegalIdentity),
    }
)

_COUNT_TYPE_TOKENS = {
    _ATLAS_RELEASE_TYPE_TOKEN: "releases",
    _ATLAS_RESOURCE_TYPE_TOKEN: "resources",
    _IDENTIFIER_TYPE_TOKEN: "identifiers",
    _LABEL_TYPE_TOKEN: "labels",
    _SOURCE_RECORD_TYPE_TOKEN: "sourceRecords",
    _RELATION_ASSERTION_TYPE_TOKEN: "relationAssertions",
    _CROSS_RING_ASSERTION_TYPE_TOKEN: "crossRingRelationAssertions",
    _MAPPING_ASSERTION_TYPE_TOKEN: "mappingAssertions",
    _NATIVE_ASSERTION_TYPE_TOKEN: "nativeRelationAssertions",
    _SOURCE_ASSIGNMENT_TYPE_TOKEN: "sourceAssignments",
    _PROJECTED_RELATION_TYPE_TOKEN: "projectedRelations",
    _DERIVED_RELATION_TYPE_TOKEN: "derivedRelations",
}
_FIRST_PASS_VALUE_PREDICATES = frozenset(
    {
        _ATLAS_IN_RELEASE_TOKEN,
        _ATLAS_IN_SOURCE_RELEASE_TOKEN,
        _ATLAS_SEMANTIC_RING_TOKEN,
        _ATLAS_SOURCE_RING_TOKEN,
        _ATLAS_TARGET_RING_TOKEN,
        _ATLAS_IDENTIFIER_SCHEME_TOKEN,
        _ATLAS_IDENTIFIES_TOKEN,
        _ATLAS_ASSERTION_STATUS_TOKEN,
        _RDF_SUBJECT_TOKEN,
        _RDF_PREDICATE_TOKEN,
        _RDF_OBJECT_TOKEN,
        _ATLAS_RELATION_SUBJECT_TOKEN,
        _ATLAS_RELATION_PREDICATE_TOKEN,
        _ATLAS_RELATION_OBJECT_TOKEN,
    }
)


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    record_id: bytes
    kind: str
    release: bytes | None = None
    ring: bytes | None = None
    source_ring: bytes | None = None
    target_ring: bytes | None = None
    subject: bytes | None = None
    predicate: bytes | None = None
    object_value: bytes | None = None
    references: tuple[bytes, ...] = ()


class _CandidatePool:
    """Retain stable low-hash candidates plus one representative per stratum."""

    def __init__(self, *, category: bytes, limit: int) -> None:
        self._category = category
        self._limit = limit
        self._heap: list[tuple[int, bytes, _RawCandidate]] = []
        self._strata: dict[tuple[bytes, ...], tuple[int, bytes, _RawCandidate]] = {}

    def _score(self, key: bytes) -> int:
        payload = b"refspec-atlas-explorer-sample-v1\0" + self._category + b"\0" + key
        return int.from_bytes(hashlib.sha256(payload).digest(), "big")

    def offer(
        self,
        candidate: _RawCandidate,
        *,
        stratum: tuple[bytes, ...],
        score_key: bytes | None = None,
    ) -> None:
        score = self._score(score_key or candidate.record_id)
        entry = (score, candidate.record_id, candidate)
        previous = self._strata.get(stratum)
        if previous is None or entry[:2] < previous[:2]:
            self._strata[stratum] = entry
        heap_entry = (-score, candidate.record_id, candidate)
        if len(self._heap) < self._limit:
            heapq.heappush(self._heap, heap_entry)
        elif score < -self._heap[0][0]:
            heapq.heapreplace(self._heap, heap_entry)

    def sample(self, limit: int) -> list[_RawCandidate]:
        if limit <= 0:
            return []
        result: list[_RawCandidate] = []
        seen: set[bytes] = set()
        stratum_rows = sorted(self._strata.values(), key=lambda row: row[:2])
        heap_rows = sorted(
            ((-negative_score, record_id, candidate) for negative_score, record_id, candidate in self._heap),
            key=lambda row: row[:2],
        )
        for _score, record_id, candidate in (*stratum_rows, *heap_rows):
            if record_id in seen:
                continue
            result.append(candidate)
            seen.add(record_id)
            if len(result) == limit:
                break
        return result


@dataclass(frozen=True, slots=True)
class _StreamedAtlasIndex:
    byte_length: int
    digest: str
    graph_quad_counts: Mapping[str, int]
    record_counts: Mapping[str, int]
    resources_by_ring: Mapping[bytes, int]
    resources_by_release: Mapping[bytes, int]
    resources_by_release_ring: Mapping[tuple[bytes, bytes], int]
    asserted_relations_by_ring: Mapping[bytes, int]
    cross_ring_relations_by_pair: Mapping[tuple[bytes, bytes], int]
    asserted_relations_by_kind: Mapping[str, int]
    source_records_by_release: Mapping[bytes, int]
    represented_source_records_by_release: Mapping[bytes, int]
    release_member_counts: Mapping[bytes, int]
    atlas_release_ids: tuple[bytes, ...]
    source_release_ids: tuple[bytes, ...]
    resource_ids: tuple[bytes, ...]
    identifier_ids: tuple[bytes, ...]
    assertion_ids: tuple[bytes, ...]
    projected_relation_ids: tuple[bytes, ...]
    derived_relation_ids: tuple[bytes, ...]
    current_authoritative_relations: int
    oversized_relations_skipped: int


@dataclass(frozen=True, slots=True)
class _PackContentEvidence:
    """Exact uncompressed identity and graph counts observed for one pack."""

    byte_length: int
    digest: str
    quad_count: int
    graph_quad_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _PackPlan:
    """One verified physical pack and the metadata needed to reopen it safely."""

    pack_id: str
    path: Path
    relative_path: str
    compression: str
    identity: tuple[int, int, int, int, int, int]
    manifest_row: Mapping[str, Any]


def _binding_digests() -> dict[str, str]:
    try:
        root_status = _BINDING_ROOT.lstat()
    except OSError as error:
        raise Atlas3ExplorerError("the authoritative Atlas 3.0 binding is unavailable") from error
    if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
        raise Atlas3ExplorerError("the authoritative Atlas 3.0 binding root is unsafe")
    relative_paths = {
        *_BINDING_BUNDLE_PATHS,
        *(path.relative_to(_BINDING_ROOT) for path in (_BINDING_ROOT / "schemas").glob("*.schema.json")),
    }
    payloads: dict[Path, bytes] = {}
    for relative in sorted(relative_paths, key=lambda path: path.as_posix()):
        path = _BINDING_ROOT / relative
        try:
            file_status = path.lstat()
            payload = path.read_bytes()
        except OSError as error:
            raise Atlas3ExplorerError(f"cannot read Atlas 3.0 binding asset {relative}") from error
        if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(file_status.st_mode):
            raise Atlas3ExplorerError(f"Atlas 3.0 binding asset {relative} is unsafe")
        payloads[relative] = payload
    bundle_rows = [
        {
            "byteLength": len(payload),
            "digest": sha256_digest(payload),
            "path": relative.as_posix(),
        }
        for relative, payload in payloads.items()
    ]
    return {
        "bindingBundleDigest": _canonical_digest_without_lf(bundle_rows),
        "ontologyDigest": sha256_digest(payloads[Path("ontology/atlas.ttl")]),
        "shapesDigest": sha256_digest(payloads[Path("shapes/atlas.shacl.ttl")]),
        "manifestSchemaDigest": sha256_digest(
            payloads[Path("schemas/atlas-manifest.schema.json")]
        ),
        "sourceAccountingSchemaDigest": sha256_digest(
            payloads[Path("schemas/atlas-source-accounting.schema.json")]
        ),
        "acceptanceSchemaDigest": sha256_digest(
            payloads[Path("schemas/atlas-acceptance.schema.json")]
        ),
    }


def _verify_binding_evidence(
    manifest: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> None:
    binding = _mapping(manifest.get("binding"), "Atlas 3.0 manifest binding")
    inputs = _mapping(acceptance.get("inputs"), "Atlas 3.0 acceptance inputs")
    for field, expected in _binding_digests().items():
        if binding.get(field) != expected or inputs.get(field) != expected:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 {field} does not match the authoritative v3 binding"
            )


def _require_raw_value(
    values: Mapping[bytes, bytes],
    predicate: bytes,
    label: str,
) -> bytes:
    value = values.get(predicate)
    if value is None:
        raise Atlas3ExplorerError(f"streamed Atlas 3.0 {label} is missing")
    return value


def _raw_iri_text(token: bytes, label: str) -> str:
    try:
        value = from_n3(token.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise Atlas3ExplorerError(f"streamed Atlas 3.0 {label} is not an IRI") from error
    if not isinstance(value, URIRef):
        raise Atlas3ExplorerError(f"streamed Atlas 3.0 {label} is not an IRI")
    return str(value)


class _StreamingIndexBuilder:
    def __init__(self) -> None:
        self.record_counts: Counter[str] = Counter()
        self.resources_by_ring: Counter[bytes] = Counter()
        self.resources_by_release: Counter[bytes] = Counter()
        self.resources_by_release_ring: Counter[tuple[bytes, bytes]] = Counter()
        self.asserted_relations_by_ring: Counter[bytes] = Counter()
        self.cross_ring_relations_by_pair: Counter[tuple[bytes, bytes]] = Counter()
        self.asserted_relations_by_kind: Counter[str] = Counter()
        self.source_records_by_release: Counter[bytes] = Counter()
        self.represented_source_records_by_release: Counter[bytes] = Counter()
        self.release_member_counts: dict[bytes, int] = {}
        self.atlas_release_ids: set[bytes] = set()
        self.source_release_ids: set[bytes] = set()
        self.current_authoritative_relations = 0
        self.oversized_relations_skipped = 0
        self.resources = _CandidatePool(
            category=b"resource",
            limit=_VISUAL_RESOURCE_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER,
        )
        self.identifiers = _CandidatePool(
            category=b"identifier",
            limit=_VISUAL_IDENTIFIER_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER,
        )
        self.topic_assertions = _CandidatePool(
            category=b"topic-assertion",
            limit=_VISUAL_TOPIC_ASSERTION_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER,
        )
        self.source_assignments = _CandidatePool(
            category=b"source-assignment",
            limit=_VISUAL_SOURCE_ASSIGNMENT_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER,
        )
        self.projected_relations = _CandidatePool(
            category=b"projected-relation",
            limit=_VISUAL_PROJECTED_RELATION_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER,
        )
        self.derived_relations = _CandidatePool(
            category=b"derived-relation",
            limit=_VISUAL_DERIVED_RELATION_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER,
        )

    def consume(
        self,
        subject: bytes,
        types: set[bytes],
        values: Mapping[bytes, bytes],
        supporting_assertions: Sequence[bytes],
        supporting_assertion_count: int,
        derived_from_assertions: Sequence[bytes],
        derived_from_assertion_count: int,
        had_member_count: int,
        represents_resource_count: int,
    ) -> None:
        for type_token in types:
            count_name = _COUNT_TYPE_TOKENS.get(type_token)
            if count_name is not None:
                self.record_counts[count_name] += 1

        if _ATLAS_RELEASE_TYPE_TOKEN in types:
            self.atlas_release_ids.add(subject)
            self.release_member_counts[subject] = had_member_count
        if _SOURCE_RELEASE_TYPE_TOKEN in types:
            self.source_release_ids.add(subject)

        if _ATLAS_RESOURCE_TYPE_TOKEN in types:
            release = _require_raw_value(values, _ATLAS_IN_RELEASE_TOKEN, f"resource {subject!r} release")
            ring = _require_raw_value(values, _ATLAS_SEMANTIC_RING_TOKEN, f"resource {subject!r} ring")
            self.resources_by_release[release] += 1
            self.resources_by_ring[ring] += 1
            self.resources_by_release_ring[(release, ring)] += 1
            self.resources.offer(
                _RawCandidate(subject, "resource", release=release, ring=ring),
                stratum=(release, ring),
            )

        if _SOURCE_RECORD_TYPE_TOKEN in types:
            release = _require_raw_value(
                values,
                _ATLAS_IN_SOURCE_RELEASE_TOKEN,
                f"source record {subject!r} release",
            )
            self.source_records_by_release[release] += 1
            if represents_resource_count:
                self.represented_source_records_by_release[release] += 1

        if _IDENTIFIER_TYPE_TOKEN in types:
            scheme = _require_raw_value(
                values,
                _ATLAS_IDENTIFIER_SCHEME_TOKEN,
                f"identifier {subject!r} scheme",
            )
            identified_resource = _require_raw_value(
                values,
                _ATLAS_IDENTIFIES_TOKEN,
                f"identifier {subject!r} resource",
            )
            self.identifiers.offer(
                _RawCandidate(
                    subject,
                    "identifier",
                    object_value=identified_resource,
                ),
                stratum=(scheme,),
            )

        if _RELATION_ASSERTION_TYPE_TOKEN in types:
            kinds = [
                name
                for type_token, name in (
                    (_MAPPING_ASSERTION_TYPE_TOKEN, "mapping"),
                    (_NATIVE_ASSERTION_TYPE_TOKEN, "native"),
                    (_SOURCE_ASSIGNMENT_TYPE_TOKEN, "sourceAssignment"),
                    (_CROSS_RING_ASSERTION_TYPE_TOKEN, "crossRing"),
                )
                if type_token in types
            ]
            if len(kinds) != 1:
                raise Atlas3ExplorerError(
                    f"streamed Atlas 3.0 assertion {subject!r} has an invalid specialization"
                )
            kind = kinds[0]
            ring = values.get(_ATLAS_SEMANTIC_RING_TOKEN)
            source_ring = values.get(_ATLAS_SOURCE_RING_TOKEN)
            target_ring = values.get(_ATLAS_TARGET_RING_TOKEN)
            if kind == "crossRing":
                if ring is not None:
                    raise Atlas3ExplorerError(
                        f"streamed Atlas 3.0 cross-ring assertion {subject!r} has semanticRing"
                    )
                source_ring = _require_raw_value(
                    values, _ATLAS_SOURCE_RING_TOKEN, f"assertion {subject!r} source ring"
                )
                target_ring = _require_raw_value(
                    values, _ATLAS_TARGET_RING_TOKEN, f"assertion {subject!r} target ring"
                )
                if source_ring == target_ring:
                    raise Atlas3ExplorerError(
                        f"streamed Atlas 3.0 cross-ring assertion {subject!r} uses one ring"
                    )
            else:
                ring = _require_raw_value(
                    values, _ATLAS_SEMANTIC_RING_TOKEN, f"assertion {subject!r} ring"
                )
                if source_ring is not None or target_ring is not None:
                    raise Atlas3ExplorerError(
                        f"streamed Atlas 3.0 same-ring assertion {subject!r} has endpoint rings"
                    )
            predicate = _require_raw_value(values, _RDF_PREDICATE_TOKEN, f"assertion {subject!r} predicate")
            assertion = _RawCandidate(
                subject,
                kind,
                ring=ring,
                source_ring=source_ring,
                target_ring=target_ring,
                subject=_require_raw_value(values, _RDF_SUBJECT_TOKEN, f"assertion {subject!r} subject"),
                predicate=predicate,
                object_value=_require_raw_value(values, _RDF_OBJECT_TOKEN, f"assertion {subject!r} object"),
            )
            relation_rings = (source_ring, target_ring) if kind == "crossRing" else (ring,)
            for relation_ring in relation_rings:
                self.asserted_relations_by_ring[cast(bytes, relation_ring)] += 1
            if kind == "crossRing":
                self.cross_ring_relations_by_pair[
                    (cast(bytes, source_ring), cast(bytes, target_ring))
                ] += 1
            self.asserted_relations_by_kind[kind] += 1
            if values.get(_ATLAS_ASSERTION_STATUS_TOKEN) == _CURRENT_STATUS_TOKEN:
                self.current_authoritative_relations += 1
            pool = self.source_assignments if kind == "sourceAssignment" else self.topic_assertions
            pool.offer(
                assertion,
                stratum=tuple(
                    cast(bytes, value)
                    for value in (kind.encode("ascii"), source_ring or ring, target_ring or ring, predicate)
                ),
            )

        if _PROJECTED_RELATION_TYPE_TOKEN in types:
            if supporting_assertion_count > _VISUAL_MAX_RELATION_REFERENCES:
                self.oversized_relations_skipped += 1
            else:
                ring = values.get(_ATLAS_SEMANTIC_RING_TOKEN)
                source_ring = values.get(_ATLAS_SOURCE_RING_TOKEN)
                target_ring = values.get(_ATLAS_TARGET_RING_TOKEN)
                if ring is None:
                    source_ring = _require_raw_value(
                        values, _ATLAS_SOURCE_RING_TOKEN, f"projection {subject!r} source ring"
                    )
                    target_ring = _require_raw_value(
                        values, _ATLAS_TARGET_RING_TOKEN, f"projection {subject!r} target ring"
                    )
                    if source_ring == target_ring:
                        raise Atlas3ExplorerError(
                            f"streamed Atlas 3.0 cross-ring projection {subject!r} uses one ring"
                        )
                elif source_ring is not None or target_ring is not None:
                    raise Atlas3ExplorerError(
                        f"streamed Atlas 3.0 same-ring projection {subject!r} has endpoint rings"
                    )
                predicate = _require_raw_value(
                    values,
                    _ATLAS_RELATION_PREDICATE_TOKEN,
                    f"projection {subject!r} predicate",
                )
                projection = _RawCandidate(
                    subject,
                    "projection",
                    ring=ring,
                    source_ring=source_ring,
                    target_ring=target_ring,
                    subject=_require_raw_value(
                        values,
                        _ATLAS_RELATION_SUBJECT_TOKEN,
                        f"projection {subject!r} subject",
                    ),
                    predicate=predicate,
                    object_value=_require_raw_value(
                        values,
                        _ATLAS_RELATION_OBJECT_TOKEN,
                        f"projection {subject!r} object",
                    ),
                    references=tuple(supporting_assertions),
                )
                score_key = projection.references[0] if projection.references else projection.record_id
                self.projected_relations.offer(
                    projection,
                    stratum=(source_ring or cast(bytes, ring), target_ring or cast(bytes, ring), predicate),
                    score_key=score_key,
                )

        if _DERIVED_RELATION_TYPE_TOKEN in types:
            if derived_from_assertion_count > _VISUAL_MAX_RELATION_REFERENCES:
                self.oversized_relations_skipped += 1
            else:
                ring = _require_raw_value(values, _ATLAS_SEMANTIC_RING_TOKEN, f"derivation {subject!r} ring")
                predicate = _require_raw_value(
                    values,
                    _ATLAS_RELATION_PREDICATE_TOKEN,
                    f"derivation {subject!r} predicate",
                )
                derived = _RawCandidate(
                    subject,
                    "derived",
                    ring=ring,
                    subject=_require_raw_value(
                        values,
                        _ATLAS_RELATION_SUBJECT_TOKEN,
                        f"derivation {subject!r} subject",
                    ),
                    predicate=predicate,
                    object_value=_require_raw_value(
                        values,
                        _ATLAS_RELATION_OBJECT_TOKEN,
                        f"derivation {subject!r} object",
                    ),
                    references=tuple(derived_from_assertions),
                )
                self.derived_relations.offer(derived, stratum=(ring, predicate))

    def finish(
        self,
        *,
        byte_length: int,
        digest: str,
        graph_quad_counts: Mapping[str, int],
    ) -> _StreamedAtlasIndex:
        selected_resources: set[bytes] = set()
        selected_assertions: list[_RawCandidate] = []

        assignment_candidates = self.source_assignments.sample(
            _VISUAL_SOURCE_ASSIGNMENT_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER
        )
        for candidate in assignment_candidates:
            if len(selected_assertions) >= _VISUAL_SOURCE_ASSIGNMENT_LIMIT:
                break
            endpoints = {cast(bytes, candidate.object_value)}
            if len(selected_resources | endpoints) > _VISUAL_RELATION_RESOURCE_BUDGET:
                continue
            selected_resources.update(endpoints)
            selected_assertions.append(candidate)

        topic_count = 0
        topic_candidates = self.topic_assertions.sample(
            _VISUAL_TOPIC_ASSERTION_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER
        )
        for candidate in topic_candidates:
            if topic_count >= _VISUAL_TOPIC_ASSERTION_LIMIT:
                break
            endpoints = {cast(bytes, candidate.subject), cast(bytes, candidate.object_value)}
            if len(selected_resources | endpoints) > _VISUAL_RELATION_RESOURCE_BUDGET:
                continue
            selected_resources.update(endpoints)
            selected_assertions.append(candidate)
            topic_count += 1

        selected_assertion_ids = {candidate.record_id for candidate in selected_assertions}
        selected_projected: list[_RawCandidate] = []
        projection_candidates = self.projected_relations.sample(
            _VISUAL_PROJECTED_RELATION_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER
        )
        projection_candidates.sort(
            key=lambda candidate: (
                not bool(selected_assertion_ids.intersection(candidate.references)),
                candidate.record_id,
            )
        )
        for candidate in projection_candidates:
            if len(selected_projected) >= _VISUAL_PROJECTED_RELATION_LIMIT:
                break
            endpoints = (
                {cast(bytes, candidate.object_value)}
                if candidate.predicate in _SOURCE_ASSIGNMENT_PREDICATE_TOKENS
                else {cast(bytes, candidate.subject), cast(bytes, candidate.object_value)}
            )
            references = set(candidate.references)
            if (
                len(selected_resources | endpoints) > _VISUAL_RELATION_RESOURCE_BUDGET
                or len(selected_assertion_ids | references) > _VISUAL_PROVENANCE_ASSERTION_LIMIT
            ):
                continue
            selected_resources.update(endpoints)
            selected_assertion_ids.update(references)
            selected_projected.append(candidate)

        selected_derived: list[_RawCandidate] = []
        for candidate in self.derived_relations.sample(
            _VISUAL_DERIVED_RELATION_LIMIT * _VISUAL_CANDIDATE_MULTIPLIER
        ):
            if len(selected_derived) >= _VISUAL_DERIVED_RELATION_LIMIT:
                break
            endpoints = {cast(bytes, candidate.subject), cast(bytes, candidate.object_value)}
            references = set(candidate.references)
            if (
                len(selected_resources | endpoints) > _VISUAL_RELATION_RESOURCE_BUDGET
                or len(selected_assertion_ids | references) > _VISUAL_PROVENANCE_ASSERTION_LIMIT
            ):
                continue
            selected_resources.update(endpoints)
            selected_assertion_ids.update(references)
            selected_derived.append(candidate)

        selected_identifier_ids: set[bytes] = set()
        for candidate in self.identifiers.sample(_VISUAL_IDENTIFIER_LIMIT):
            identified_resource = cast(bytes, candidate.object_value)
            if (
                identified_resource not in selected_resources
                and len(selected_resources) >= _VISUAL_RESOURCE_LIMIT
            ):
                continue
            selected_resources.add(identified_resource)
            selected_identifier_ids.add(candidate.record_id)

        for candidate in self.resources.sample(_VISUAL_RESOURCE_LIMIT):
            if len(selected_resources) == _VISUAL_RESOURCE_LIMIT:
                break
            selected_resources.add(candidate.record_id)

        return _StreamedAtlasIndex(
            byte_length=byte_length,
            digest=digest,
            graph_quad_counts={
                role: graph_quad_counts.get(role, 0)
                for role in ("asserted", "projection", "derived")
            },
            record_counts=dict(self.record_counts),
            resources_by_ring=dict(self.resources_by_ring),
            resources_by_release=dict(self.resources_by_release),
            resources_by_release_ring=dict(self.resources_by_release_ring),
            asserted_relations_by_ring=dict(self.asserted_relations_by_ring),
            cross_ring_relations_by_pair=dict(self.cross_ring_relations_by_pair),
            asserted_relations_by_kind=dict(self.asserted_relations_by_kind),
            source_records_by_release=dict(self.source_records_by_release),
            represented_source_records_by_release=dict(self.represented_source_records_by_release),
            release_member_counts=dict(self.release_member_counts),
            atlas_release_ids=tuple(sorted(self.atlas_release_ids)),
            source_release_ids=tuple(sorted(self.source_release_ids)),
            resource_ids=tuple(sorted(selected_resources)),
            identifier_ids=tuple(sorted(selected_identifier_ids)),
            assertion_ids=tuple(sorted(selected_assertion_ids)),
            projected_relation_ids=tuple(sorted(candidate.record_id for candidate in selected_projected)),
            derived_relation_ids=tuple(sorted(candidate.record_id for candidate in selected_derived)),
            current_authoritative_relations=self.current_authoritative_relations,
            oversized_relations_skipped=self.oversized_relations_skipped,
        )


def _scan_pack_content(
    stream: BinaryIO,
    graph_ids: Mapping[str, URIRef],
    builder: _StreamingIndexBuilder,
    *,
    label: str,
) -> _PackContentEvidence:
    """Verify and index one canonical uncompressed pack in bounded memory."""

    digest = hashlib.sha256()
    byte_length = 0
    previous: bytes | None = None
    line_count = 0
    graph_suffixes = {
        role: b" " + _nquad_iri_token(graph_id) + b" .\n"
        for role, graph_id in graph_ids.items()
    }
    graph_counts: Counter[str] = Counter()
    current_subject: bytes | None = None
    types: set[bytes] = set()
    values: dict[bytes, bytes] = {}
    supporting_assertions: list[bytes] = []
    supporting_assertion_count = 0
    derived_from_assertions: list[bytes] = []
    derived_from_assertion_count = 0
    had_member_count = 0
    represents_resource_count = 0

    def finish_subject() -> None:
        nonlocal current_subject
        if current_subject is None:
            return
        builder.consume(
            current_subject,
            types,
            values,
            supporting_assertions,
            supporting_assertion_count,
            derived_from_assertions,
            derived_from_assertion_count,
            had_member_count,
            represents_resource_count,
        )

    while line := stream.readline(_NQUADS_MAX_LINE_BYTES + 1):
        line_count += 1
        if len(line) > _NQUADS_MAX_LINE_BYTES:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 {label} line {line_count} exceeds {_NQUADS_MAX_LINE_BYTES} bytes"
            )
        digest.update(line)
        byte_length += len(line)
        if not line.endswith(b"\n") or b"\r" in line:
            raise Atlas3ExplorerError(f"Atlas 3.0 {label} must use canonical LF lines")
        if (
            len(line) <= 1
            or line[0] != ord("<")
            or line[-2] != ord(".")
            or (previous is not None and line <= previous)
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 {label} lines must be non-empty, unique, sorted IRI-subject N-Quads"
            )
        previous = line

        role = next((name for name, suffix in graph_suffixes.items() if line.endswith(suffix)), None)
        if role is None:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 {label} uses an undeclared or malformed graph"
            )
        graph_counts[role] += 1

        if current_subject is None or not (
            line.startswith(current_subject) and line[len(current_subject) : len(current_subject) + 1] == b" "
        ):
            finish_subject()
            subject_end = line.find(b"> ", 1)
            if subject_end < 0:
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 {label} line {line_count} has a malformed subject"
                )
            current_subject = line[: subject_end + 1]
            types = set()
            values = {}
            supporting_assertions = []
            supporting_assertion_count = 0
            derived_from_assertions = []
            derived_from_assertion_count = 0
            had_member_count = 0
            represents_resource_count = 0

        predicate_start = len(cast(bytes, current_subject)) + 1
        predicate_end = line.find(b"> ", predicate_start + 1)
        graph_start = line.rfind(b" <") + 1
        if (
            predicate_end < predicate_start
            or graph_start <= predicate_end + 2
            or line[predicate_start : predicate_start + 1] != b"<"
        ):
            raise Atlas3ExplorerError(f"Atlas 3.0 {label} line {line_count} is malformed")
        predicate = line[predicate_start : predicate_end + 1]
        object_value = line[predicate_end + 2 : graph_start - 1]
        if not object_value or object_value.startswith(b"_:"):
            raise Atlas3ExplorerError(f"Atlas 3.0 {label} must not contain blank nodes")
        if predicate == _RDF_TYPE_TOKEN:
            types.add(object_value)
        elif predicate in _FIRST_PASS_VALUE_PREDICATES:
            values.setdefault(predicate, object_value)
        elif predicate == _ATLAS_SUPPORTING_ASSERTION_TOKEN:
            supporting_assertion_count += 1
            if len(supporting_assertions) < _VISUAL_MAX_RELATION_REFERENCES:
                supporting_assertions.append(object_value)
        elif predicate == _ATLAS_DERIVED_FROM_ASSERTION_TOKEN:
            derived_from_assertion_count += 1
            if len(derived_from_assertions) < _VISUAL_MAX_RELATION_REFERENCES:
                derived_from_assertions.append(object_value)
        elif predicate == _PROV_HAD_MEMBER_TOKEN:
            had_member_count += 1
        elif predicate == _ATLAS_REPRESENTS_RESOURCE_TOKEN:
            represents_resource_count += 1

    finish_subject()
    if line_count == 0:
        raise Atlas3ExplorerError(f"Atlas 3.0 {label} must not be empty")
    return _PackContentEvidence(
        byte_length=byte_length,
        digest="sha256:" + digest.hexdigest(),
        quad_count=line_count,
        graph_quad_counts=graph_counts,
    )


def _scan_dataset_member(
    stream: BinaryIO,
    graph_ids: Mapping[str, URIRef],
) -> _StreamedAtlasIndex:
    """Compatibility helper for tests and one-pack callers."""

    builder = _StreamingIndexBuilder()
    evidence = _scan_pack_content(stream, graph_ids, builder, label="dataset")
    return builder.finish(
        byte_length=evidence.byte_length,
        digest=evidence.digest,
        graph_quad_counts=evidence.graph_quad_counts,
    )


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


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


def _sorted_unique_texts(
    value: object,
    label: str,
    *,
    iri: bool = False,
) -> list[str]:
    rows = [
        _iri_text(item, f"{label} item") if iri else _text(item, f"{label} item")
        for item in _sequence(value, label)
    ]
    if rows != sorted(rows) or len(rows) != len(set(rows)):
        raise Atlas3ExplorerError(f"{label} must be sorted and unique")
    return rows


def _graph_inventory_digest(
    packs: Sequence[Mapping[str, Any]],
    role: str,
) -> str:
    rows = sorted(
        (
            {
                "contentDigest": cast(Mapping[str, Any], pack["content"])["digest"],
                "packId": pack["packId"],
                "quadCount": cast(Mapping[str, Any], pack["graphCounts"])[role],
            }
            for pack in packs
            if cast(Mapping[str, Any], pack["graphCounts"])[role]
        ),
        key=lambda row: cast(str, row["packId"]),
    )
    return _canonical_digest_without_lf(rows)


def _verify_pack_rows(
    manifest: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    graph_rows = _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")
    if not graph_rows:
        raise Atlas3ExplorerError("Atlas 3.0 manifest has no asserted graph")
    asserted_inventory_digest = _digest(
        _mapping(graph_rows[0], "Atlas 3.0 asserted graph").get("inventoryDigest"),
        "Atlas 3.0 asserted graph inventoryDigest",
    )
    raw_packs = _sequence(manifest.get("packs"), "Atlas 3.0 manifest packs")
    if not raw_packs:
        raise Atlas3ExplorerError("Atlas 3.0 manifest must declare at least one pack")
    packs: list[Mapping[str, Any]] = []
    pack_ids: list[str] = []
    paths: list[str] = []
    for position, raw_pack in enumerate(raw_packs):
        label = f"Atlas 3.0 pack {position}"
        pack = _mapping(raw_pack, label)
        fields = frozenset(pack)
        if not _PACK_REQUIRED_FIELDS.issubset(fields) or not fields.issubset(_PACK_FIELDS):
            raise Atlas3ExplorerError(
                f"{label} fields differ; missing={sorted(_PACK_REQUIRED_FIELDS - fields)}, "
                f"extra={sorted(fields - _PACK_FIELDS)}"
            )
        pack_id = _iri_text(pack.get("packId"), f"{label} packId")
        kind = _text(pack.get("kind"), f"{label} kind")
        if kind not in _PACK_KINDS:
            raise Atlas3ExplorerError(f"{label} kind is unsupported")
        path = _safe_relative_path(pack.get("path"), f"{label} path")

        transport = _mapping(pack.get("transport"), f"{label} transport")
        _exact_fields(
            transport,
            frozenset({"compression", "mediaType", "digest", "byteLength"}),
            f"{label} transport",
        )
        compression = _text(transport.get("compression"), f"{label} compression")
        expected_media_type = {
            "none": "application/n-quads",
            "zstd": "application/zstd",
        }.get(compression)
        if expected_media_type is None or transport.get("mediaType") != expected_media_type:
            raise Atlas3ExplorerError(f"{label} transport compression or media type is unsupported")
        if not path.endswith(".nq.zst" if compression == "zstd" else ".nq"):
            raise Atlas3ExplorerError(f"{label} path does not match its compression")
        _digest(transport.get("digest"), f"{label} transport digest")
        if _count(transport.get("byteLength"), f"{label} transport byteLength") <= 0:
            raise Atlas3ExplorerError(f"{label} transport must not be empty")

        content = _mapping(pack.get("content"), f"{label} content")
        _exact_fields(
            content,
            frozenset({"mediaType", "digest", "byteLength", "quadCount"}),
            f"{label} content",
        )
        if content.get("mediaType") != "application/n-quads":
            raise Atlas3ExplorerError(f"{label} content media type is unsupported")
        _digest(content.get("digest"), f"{label} content digest")
        if (
            _count(content.get("byteLength"), f"{label} content byteLength") <= 0
            or _count(content.get("quadCount"), f"{label} content quadCount") <= 0
        ):
            raise Atlas3ExplorerError(f"{label} content must not be empty")

        graph_counts = _mapping(pack.get("graphCounts"), f"{label} graphCounts")
        _exact_fields(
            graph_counts,
            frozenset({"asserted", "projection", "derived"}),
            f"{label} graphCounts",
        )
        for role in ("asserted", "projection", "derived"):
            _count(graph_counts.get(role), f"{label} graphCounts.{role}")
        if sum(cast(int, graph_counts[role]) for role in graph_counts) != content["quadCount"]:
            raise Atlas3ExplorerError(f"{label} graph counts do not reconcile with content")

        dependencies = _sorted_unique_texts(
            pack.get("dependencies"), f"{label} dependencies", iri=True
        )
        source_releases = _sorted_unique_texts(
            pack.get("sourceReleases"), f"{label} sourceReleases", iri=True
        )
        rings = _sorted_unique_texts(pack.get("rings"), f"{label} rings")
        if not set(rings).issubset(_RINGS):
            raise Atlas3ExplorerError(f"{label} declares an unsupported semantic ring")

        has_view_quads = bool(graph_counts["projection"] or graph_counts["derived"])
        if kind == "sourceRelease":
            if len(source_releases) != 1 or graph_counts["asserted"] <= 0 or has_view_quads:
                raise Atlas3ExplorerError(f"{label} is not a valid source-release pack")
        elif kind in {"catalog", "mapping"}:
            if graph_counts["asserted"] <= 0 or has_view_quads:
                raise Atlas3ExplorerError(f"{label} is not a valid asserted pack")
            if kind == "mapping" and not dependencies:
                raise Atlas3ExplorerError(f"{label} mapping pack has no dependency")
        elif kind == "view" and (
            graph_counts["asserted"] or not has_view_quads or not dependencies
        ):
            raise Atlas3ExplorerError(f"{label} is not a valid view pack")
        if has_view_quads:
            if (
                _digest(pack.get("inputAssertedDigest"), f"{label} inputAssertedDigest")
                != asserted_inventory_digest
            ):
                raise Atlas3ExplorerError(f"{label} view pins the wrong asserted inventory")
        elif "inputAssertedDigest" in pack:
            raise Atlas3ExplorerError(f"{label} has an unnecessary asserted-input pin")

        partition = pack.get("partition")
        if partition is not None:
            partition_row = _mapping(partition, f"{label} partition")
            _exact_fields(
                partition_row,
                frozenset({"strategy", "prefix"}),
                f"{label} partition",
            )
            prefix = _text(partition_row.get("prefix"), f"{label} partition prefix")
            if (
                kind != "sourceRelease"
                or partition_row.get("strategy") != "sha256-subject-iri-prefix"
                or re.fullmatch(r"[0-9a-f]{1,8}", prefix) is None
            ):
                raise Atlas3ExplorerError(f"{label} has an invalid partition")

        packs.append(pack)
        pack_ids.append(pack_id)
        paths.append(path)

    if pack_ids != sorted(pack_ids) or len(pack_ids) != len(set(pack_ids)):
        raise Atlas3ExplorerError("Atlas 3.0 packs must be ordered by unique packId")
    if len(paths) != len(set(paths)):
        raise Atlas3ExplorerError("Atlas 3.0 pack paths must be unique")
    known_pack_ids = set(pack_ids)
    for pack in packs:
        dependencies = cast(Sequence[str], pack["dependencies"])
        if pack["packId"] in dependencies or not set(dependencies).issubset(known_pack_ids):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 pack {pack['packId']} has an invalid dependency"
            )
    return tuple(packs)


def _verify_construction_summary(
    manifest: Mapping[str, Any],
    construction_summary: Mapping[str, Any],
    member_digests: Mapping[str, str],
) -> tuple[Mapping[str, Any], ...]:
    """Authenticate the compact-pack inventory without decoding logical rows."""

    _exact_fields(
        construction_summary,
        _CONSTRUCTION_SUMMARY_FIELDS,
        "Atlas 3.0 construction summary",
    )
    if (
        construction_summary.get("type") != "AtlasConstructionSummary"
        or construction_summary.get("version") != "3.0"
        or construction_summary.get("profile")
        != "atlas-3-release-local-construction-v1"
    ):
        raise Atlas3ExplorerError("Atlas 3.0 construction summary identity differs")
    payload = dict(construction_summary)
    declared_payload_digest = _digest(
        payload.pop("canonicalPayloadDigest"),
        "Atlas 3.0 construction summary canonicalPayloadDigest",
    )
    if declared_payload_digest != _canonical_digest_without_lf(payload):
        raise Atlas3ExplorerError(
            "Atlas 3.0 construction summary canonicalPayloadDigest is stale"
        )
    asserted_inventory = _mapping(
        _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")[0],
        "Atlas 3.0 asserted graph",
    )["inventoryDigest"]
    expected_identity = {
        "assertedInventoryDigest": asserted_inventory,
        "bindingBundleDigest": _mapping(
            manifest.get("binding"), "Atlas 3.0 manifest binding"
        )["bindingBundleDigest"],
        "distributionId": manifest.get("distributionId"),
        "sourceAccountingDigest": member_digests[_SOURCE_ACCOUNTING_MEMBER],
    }
    if any(
        construction_summary.get(field) != expected
        for field, expected in expected_identity.items()
    ):
        raise Atlas3ExplorerError(
            "Atlas 3.0 construction summary does not describe this distribution"
        )
    _digest(
        construction_summary.get("recipeDigest"),
        "Atlas 3.0 construction summary recipeDigest",
    )

    releases = [
        _mapping(raw, "Atlas 3.0 construction release")
        for raw in _sequence(
            construction_summary.get("releases"),
            "Atlas 3.0 construction releases",
        )
    ]
    release_keys = [
        _text(release.get("key"), "Atlas 3.0 construction release key")
        for release in releases
    ]
    if (
        not releases
        or release_keys != sorted(release_keys)
        or len(release_keys) != len(set(release_keys))
        or _count(
            construction_summary.get("releaseCount"),
            "Atlas 3.0 construction releaseCount",
        )
        != len(releases)
        or _digest(
            construction_summary.get("releaseInventoryDigest"),
            "Atlas 3.0 construction releaseInventoryDigest",
        )
        != _canonical_digest(releases)
    ):
        raise Atlas3ExplorerError(
            "Atlas 3.0 construction release inventory does not reconcile"
        )

    compact_packs = [
        _mapping(raw, "Atlas 3.0 compact pack")
        for raw in _sequence(
            construction_summary.get("compactPacks"),
            "Atlas 3.0 compact packs",
        )
    ]
    paths: list[str] = []
    pack_ids: list[str] = []
    for pack in compact_packs:
        fields = frozenset(pack)
        if fields not in {
            _COMPACT_PACK_REQUIRED_FIELDS,
            _COMPACT_PACK_FIELDS,
        }:
            expected = (
                _COMPACT_PACK_FIELDS
                if "partition" in fields
                else _COMPACT_PACK_REQUIRED_FIELDS
            )
            raise Atlas3ExplorerError(
                "Atlas 3.0 compact pack fields differ; "
                f"missing={sorted(expected - fields)}, extra={sorted(fields - expected)}"
            )
        content = _mapping(pack.get("content"), "Atlas 3.0 compact pack content")
        _exact_fields(
            content,
            frozenset({"byteLength", "digest", "mediaType", "recordCount"}),
            "Atlas 3.0 compact pack content",
        )
        content_digest = _digest(
            content.get("digest"), "Atlas 3.0 compact pack content digest"
        )
        if (
            content.get("mediaType") != "application/x-ndjson"
            or _count(
                content.get("byteLength"),
                "Atlas 3.0 compact pack content byteLength",
            )
            < 1
        ):
            raise Atlas3ExplorerError("Atlas 3.0 compact pack content identity differs")
        record_count = _count(
            content.get("recordCount"), "Atlas 3.0 compact pack recordCount"
        )
        pack_id = _text(pack.get("packId"), "Atlas 3.0 compact pack packId")
        if pack_id != (
            "urn:ref:atlas:compact-pack:" + content_digest.removeprefix("sha256:")
        ):
            raise Atlas3ExplorerError(
                "Atlas 3.0 compact pack ID does not derive from its content"
            )
        role = _text(pack.get("role"), "Atlas 3.0 compact pack role")
        if role not in _COMPACT_RECORD_ROLES:
            raise Atlas3ExplorerError("Atlas 3.0 compact pack role is unsupported")
        path = _safe_relative_path(pack.get("path"), "Atlas 3.0 compact pack path")
        if not path.startswith("packs/compact/") or not path.endswith(".jsonl.zst"):
            raise Atlas3ExplorerError("Atlas 3.0 compact pack path is unsupported")
        _sorted_unique_texts(
            pack.get("dependencies"),
            f"Atlas 3.0 compact pack {path} dependencies",
            iri=True,
        )
        _mapping(pack.get("defaults"), f"Atlas 3.0 compact pack {path} defaults")
        _digest(
            pack.get("logicalRowsDigest"),
            f"Atlas 3.0 compact pack {path} logicalRowsDigest",
        )
        if pack.get("recordSchemaVersion") != "1.0":
            raise Atlas3ExplorerError(
                f"Atlas 3.0 compact pack {path} record schema is unsupported"
            )
        summary = _mapping(
            pack.get("globalInvariantSummary"),
            f"Atlas 3.0 compact pack {path} globalInvariantSummary",
        )
        _exact_fields(
            summary,
            frozenset(
                {"schemaVersion", "recordRole", "recordCount", "fieldCounts", "digest"}
            ),
            f"Atlas 3.0 compact pack {path} globalInvariantSummary",
        )
        if (
            summary.get("schemaVersion") != "1.0"
            or summary.get("recordRole") != role
            or _count(
                summary.get("recordCount"),
                f"Atlas 3.0 compact pack {path} summary recordCount",
            )
            != record_count
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 compact pack {path} summary identity differs"
            )
        _mapping(
            summary.get("fieldCounts"),
            f"Atlas 3.0 compact pack {path} summary fieldCounts",
        )
        _digest(
            summary.get("digest"),
            f"Atlas 3.0 compact pack {path} summary digest",
        )
        transport = _mapping(
            pack.get("transport"), f"Atlas 3.0 compact pack {path} transport"
        )
        _exact_fields(
            transport,
            frozenset({"compression", "mediaType", "digest", "byteLength"}),
            f"Atlas 3.0 compact pack {path} transport",
        )
        if (
            transport.get("compression") != "zstd"
            or transport.get("mediaType") != "application/zstd"
            or _count(
                transport.get("byteLength"),
                f"Atlas 3.0 compact pack {path} transport byteLength",
            )
            < 1
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 compact pack {path} transport identity differs"
            )
        _digest(
            transport.get("digest"),
            f"Atlas 3.0 compact pack {path} transport digest",
        )
        if "partition" in pack:
            partition = _mapping(
                pack["partition"], f"Atlas 3.0 compact pack {path} partition"
            )
            _exact_fields(
                partition,
                frozenset({"strategy", "prefix"}),
                f"Atlas 3.0 compact pack {path} partition",
            )
            if (
                partition.get("strategy") != "sha256-subject-iri-prefix"
                or re.fullmatch(
                    r"[0-9a-f]+",
                    _text(
                        partition.get("prefix"),
                        f"Atlas 3.0 compact pack {path} partition prefix",
                    ),
                )
                is None
            ):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 compact pack {path} partition differs"
                )
        paths.append(path)
        pack_ids.append(pack_id)

    if (
        not compact_packs
        or paths != sorted(paths)
        or len(paths) != len(set(paths))
        or len(pack_ids) != len(set(pack_ids))
        or _count(
            construction_summary.get("compactPackCount"),
            "Atlas 3.0 construction compactPackCount",
        )
        != len(compact_packs)
        or _digest(
            construction_summary.get("compactPackInventoryDigest"),
            "Atlas 3.0 construction compactPackInventoryDigest",
        )
        != _canonical_digest(compact_packs)
    ):
        raise Atlas3ExplorerError(
            "Atlas 3.0 compact pack inventory does not reconcile"
        )
    known_pack_ids = set(pack_ids)
    for pack in compact_packs:
        dependencies = cast(Sequence[str], pack["dependencies"])
        if pack["packId"] in dependencies or not set(dependencies).issubset(
            known_pack_ids
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 compact pack {pack['path']} has an invalid dependency"
            )

    owned_paths: list[str] = []
    known_paths = set(paths)
    for release in releases:
        release_paths = [
            _safe_relative_path(
                raw,
                f"Atlas 3.0 construction release {release['key']} compact path",
            )
            for raw in _sequence(
                release.get("compactPackPaths"),
                f"Atlas 3.0 construction release {release['key']} compactPackPaths",
            )
        ]
        if (
            not release_paths
            or release_paths != sorted(release_paths)
            or len(release_paths) != len(set(release_paths))
            or not set(release_paths).issubset(known_paths)
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 construction release {release['key']} compact ownership differs"
            )
        owned_paths.extend(release_paths)
    if len(owned_paths) != len(set(owned_paths)) or set(owned_paths) != known_paths:
        raise Atlas3ExplorerError(
            "Atlas 3.0 construction compact-pack ownership is not exact"
        )
    return tuple(compact_packs)


def _verify_manifest(
    manifest: Mapping[str, Any],
    manifest_payload: bytes,
    member_evidence: Mapping[str, tuple[int, str]],
    trusted_manifest_digest: str | None,
) -> tuple[str, dict[str, URIRef]]:
    _exact_fields(manifest, _MANIFEST_FIELDS, "Atlas 3.0 manifest")
    if (
        manifest.get("type") != "AtlasManifest"
        or manifest.get("schemaVersion") != "3.0"
        or manifest.get("format") != "refspec-atlas-packed-nquads-3.0"
    ):
        raise Atlas3ExplorerError("Atlas 3.0 manifest type, schemaVersion, or format is unsupported")
    _text(manifest.get("distributionId"), "Atlas 3.0 manifest distributionId")
    _text(manifest.get("createdAt"), "Atlas 3.0 manifest createdAt")

    manifest_digest = sha256_digest(manifest_payload)
    if trusted_manifest_digest is not None and (
        _digest(trusted_manifest_digest, "trusted Atlas 3.0 manifest digest") != manifest_digest
    ):
        raise Atlas3ExplorerError("Atlas 3.0 manifest differs from the trusted digest")
    basis = dict(manifest)
    expected_payload_digest = _digest(
        basis.pop("canonicalPayloadDigest"),
        "Atlas 3.0 manifest canonicalPayloadDigest",
    )
    if _canonical_digest_without_lf(basis) != expected_payload_digest:
        raise Atlas3ExplorerError("Atlas 3.0 manifest canonicalPayloadDigest is stale")

    binding = _mapping(manifest.get("binding"), "Atlas 3.0 manifest binding")
    _exact_fields(binding, _BINDING_FIELDS, "Atlas 3.0 manifest binding")
    if binding.get("version") != "3.0" or binding.get("validatorVersion") != "3.0":
        raise Atlas3ExplorerError("Atlas 3.0 manifest binding version is unsupported")
    for key in _BINDING_FIELDS - {"version", "validatorVersion"}:
        _digest(binding.get(key), f"Atlas 3.0 manifest binding.{key}")

    graph_rows = _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")
    if len(graph_rows) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 manifest must declare exactly three graph roles")
    graph_ids: dict[str, URIRef] = {}
    for position, role in enumerate(("asserted", "projection", "derived")):
        row = _mapping(graph_rows[position], f"Atlas 3.0 {role} graph")
        _exact_fields(row, _GRAPH_FIELDS, f"Atlas 3.0 {role} graph")
        if row.get("role") != role:
            raise Atlas3ExplorerError("Atlas 3.0 manifest graph roles are out of order")
        graph_ids[role] = URIRef(_text(row.get("id"), f"Atlas 3.0 {role} graph id"))
        _count(row.get("quadCount"), f"Atlas 3.0 {role} graph quadCount")
        _count(row.get("packCount"), f"Atlas 3.0 {role} graph packCount")
        _digest(row.get("inventoryDigest"), f"Atlas 3.0 {role} graph inventoryDigest")
    if len(set(graph_ids.values())) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 graph role IRIs must be distinct")

    expected_members = [
        ("sourceAccounting", _SOURCE_ACCOUNTING_MEMBER, "application/json"),
        ("acceptance", _ACCEPTANCE_MEMBER, "application/json"),
        ("producerValidation", _PRODUCER_VALIDATION_MEMBER, "application/json"),
        ("constructionSummary", _CONSTRUCTION_SUMMARY_MEMBER, "application/json"),
    ]
    members = _sequence(manifest.get("members"), "Atlas 3.0 manifest members")
    if len(members) != len(expected_members):
        raise Atlas3ExplorerError(
            "Atlas 3.0 manifest must pin source accounting, acceptance, producer "
            "validation, and the construction summary"
        )
    for position, (role, path, media_type) in enumerate(expected_members):
        row = _mapping(members[position], f"Atlas 3.0 member {path}")
        _exact_fields(
            row,
            frozenset({"role", "path", "mediaType", "digest", "byteLength"}),
            f"Atlas 3.0 member {path}",
        )
        if row.get("role") != role or row.get("path") != path or row.get("mediaType") != media_type:
            raise Atlas3ExplorerError(f"Atlas 3.0 member {path} role, path, or media type differs")
        byte_length, digest = member_evidence[path]
        if _digest(row.get("digest"), f"Atlas 3.0 member {path} digest") != digest:
            raise Atlas3ExplorerError(f"Atlas 3.0 member {path} digest differs")
        if _count(row.get("byteLength"), f"Atlas 3.0 member {path} byteLength") != byte_length:
            raise Atlas3ExplorerError(f"Atlas 3.0 member {path} byte length differs")

    packs = _verify_pack_rows(manifest)
    for graph_row in cast(Sequence[Mapping[str, Any]], graph_rows):
        role = cast(str, graph_row["role"])
        role_packs = [pack for pack in packs if cast(Mapping[str, int], pack["graphCounts"])[role]]
        if (
            graph_row["quadCount"]
            != sum(cast(Mapping[str, int], pack["graphCounts"])[role] for pack in role_packs)
            or graph_row["packCount"] != len(role_packs)
            or graph_row["inventoryDigest"] != _graph_inventory_digest(packs, role)
        ):
            raise Atlas3ExplorerError(f"Atlas 3.0 {role} graph inventory does not reconcile")

    counts = _mapping(manifest.get("counts"), "Atlas 3.0 manifest counts")
    _exact_fields(counts, _COUNT_FIELDS, "Atlas 3.0 manifest counts")
    for key, value in counts.items():
        _count(value, f"Atlas 3.0 manifest counts.{key}")
    return manifest_digest, graph_ids


def _verify_acceptance(
    manifest: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    member_digests: Mapping[str, str],
) -> None:
    if (
        acceptance.get("type") != "AtlasAcceptance"
        or acceptance.get("version") != "3.0"
        or acceptance.get("distributionId") != manifest.get("distributionId")
        or acceptance.get("verdict") != "passed"
    ):
        raise Atlas3ExplorerError("Atlas 3.0 acceptance does not certify this distribution")
    validator = _mapping(acceptance.get("validator"), "Atlas 3.0 acceptance validator")
    if dict(validator) != {"name": "refspec-atlas-conformance", "version": "3.0"}:
        raise Atlas3ExplorerError("Atlas 3.0 acceptance validator identity is unsupported")
    gate_names: list[str] = []
    for raw in _sequence(acceptance.get("gates"), "Atlas 3.0 acceptance gates"):
        row = _mapping(raw, "Atlas 3.0 acceptance gate")
        if row.get("status") != "passed":
            raise Atlas3ExplorerError("Every Atlas 3.0 acceptance gate must have passed")
        gate_names.append(_text(row.get("name"), "Atlas 3.0 acceptance gate name"))
        _digest(row.get("evidenceDigest"), "Atlas 3.0 acceptance gate evidenceDigest")
    if frozenset(gate_names) != REQUIRED_ACCEPTANCE_GATES or len(gate_names) != len(set(gate_names)):
        raise Atlas3ExplorerError("Atlas 3.0 acceptance gate set is incomplete or duplicated")

    inputs = _mapping(acceptance.get("inputs"), "Atlas 3.0 acceptance inputs")
    binding = _mapping(manifest.get("binding"), "Atlas 3.0 manifest binding")
    asserted_graph = _mapping(
        _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")[0],
        "Atlas 3.0 asserted graph",
    )
    expected = {
        "atlasDigest": asserted_graph["inventoryDigest"],
        "sourceAccountingDigest": member_digests[_SOURCE_ACCOUNTING_MEMBER],
        "bindingBundleDigest": binding["bindingBundleDigest"],
        "ontologyDigest": binding["ontologyDigest"],
        "shapesDigest": binding["shapesDigest"],
        "manifestSchemaDigest": binding["manifestSchemaDigest"],
        "sourceAccountingSchemaDigest": binding["sourceAccountingSchemaDigest"],
        "acceptanceSchemaDigest": binding["acceptanceSchemaDigest"],
    }
    if _PRODUCER_VALIDATION_MEMBER in member_digests:
        expected["producerValidationDigest"] = member_digests[
            _PRODUCER_VALIDATION_MEMBER
        ]
    if dict(inputs) != expected:
        raise Atlas3ExplorerError("Atlas 3.0 acceptance inputs differ from the sealed distribution")
    for raw in cast(Sequence[Mapping[str, Any]], acceptance["gates"]):
        expected_gate_digest = _canonical_digest_without_lf(
            {
                "inputs": dict(inputs),
                "name": raw["name"],
                "status": "passed",
                "validator": dict(validator),
            }
        )
        if raw["evidenceDigest"] != expected_gate_digest:
            raise Atlas3ExplorerError(f"Atlas 3.0 gate {raw['name']} evidenceDigest differs")


def _verify_producer_validation(
    manifest: Mapping[str, Any],
    producer_validation: Mapping[str, Any],
    construction_summary: Mapping[str, Any],
    member_digests: Mapping[str, str],
    source_release_count: int,
) -> None:
    """Verify the required compiled proof and its construction-summary receipt."""

    producer_fields = frozenset(producer_validation)
    allowed_field_sets = {
        _PRODUCER_VALIDATION_FIELDS,
        _PRODUCER_VALIDATION_FIELDS | {"semanticConstruction"},
    }
    if producer_fields not in allowed_field_sets:
        expected = (
            _PRODUCER_VALIDATION_FIELDS
            if "semanticConstruction" not in producer_fields
            else _PRODUCER_VALIDATION_FIELDS | {"semanticConstruction"}
        )
        raise Atlas3ExplorerError(
            "Atlas 3.0 producer validation fields differ; "
            f"missing={sorted(expected - producer_fields)}, "
            f"extra={sorted(producer_fields - expected)}"
        )
    expected_identity = {
        "constructorProfile": (
            "atlas-3-source-and-evidence-backed-mapping-compiled-shacl-v1"
        ),
        "mode": "compiledSourceAndEvidenceBackedMappingProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "status": "passed",
        "type": "AtlasProducerValidation",
        "version": "3.0",
    }
    if any(
        producer_validation.get(field) != value
        for field, value in expected_identity.items()
    ):
        raise Atlas3ExplorerError("Atlas 3.0 producer validation identity differs")
    _digest(
        producer_validation.get("implementationDigest"),
        "Atlas 3.0 producer implementationDigest",
    )
    if producer_validation.get("binding") != manifest.get("binding"):
        raise Atlas3ExplorerError("Atlas 3.0 producer validation binding differs")
    asserted_graph = _mapping(
        _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")[0],
        "Atlas 3.0 asserted graph",
    )
    if (
        producer_validation.get("assertedInventoryDigest")
        != asserted_graph.get("inventoryDigest")
        or producer_validation.get("counts") != manifest.get("counts")
        or producer_validation.get("sourceReleaseCount")
        != source_release_count
        or producer_validation.get("sourceAccountingDigest")
        != member_digests.get(_SOURCE_ACCOUNTING_MEMBER)
    ):
        raise Atlas3ExplorerError(
            "Atlas 3.0 producer validation does not describe this distribution"
        )
    checks = [
        _text(row, "Atlas 3.0 producer validation check")
        for row in _sequence(
            producer_validation.get("checks"),
            "Atlas 3.0 producer validation checks",
        )
    ]
    if not checks or len(checks) != len(set(checks)):
        raise Atlas3ExplorerError(
            "Atlas 3.0 producer validation checks are empty or duplicated"
        )
    expected_construction_receipt = {
        "compactPackCount": construction_summary["compactPackCount"],
        "compactPackInventoryDigest": construction_summary[
            "compactPackInventoryDigest"
        ],
        "digest": member_digests[_CONSTRUCTION_SUMMARY_MEMBER],
        "path": _CONSTRUCTION_SUMMARY_MEMBER,
        "profile": "atlas-3-authenticated-construction-summary-v1",
        "releaseCount": construction_summary["releaseCount"],
        "releaseInventoryDigest": construction_summary["releaseInventoryDigest"],
    }
    if producer_validation.get("constructionSummary") != expected_construction_receipt:
        raise Atlas3ExplorerError(
            "Atlas 3.0 producer construction-summary receipt differs"
        )
    if "semanticConstruction" in producer_validation:
        construction = _mapping(
            producer_validation["semanticConstruction"],
            "Atlas 3.0 producer semanticConstruction",
        )
        _exact_fields(
            construction,
            frozenset(
                {
                    "inputFileCount",
                    "inputInventoryDigest",
                    "profile",
                    "recipeDigest",
                    "reuseScope",
                }
            ),
            "Atlas 3.0 producer semanticConstruction",
        )
        if (
            _count(
                construction.get("inputFileCount"),
                "Atlas 3.0 producer semanticConstruction inputFileCount",
            )
            < 1
        ):
            raise Atlas3ExplorerError(
                "Atlas 3.0 producer semanticConstruction inputFileCount must be positive"
            )
        _digest(
            construction.get("inputInventoryDigest"),
            "Atlas 3.0 producer semanticConstruction inputInventoryDigest",
        )
        _digest(
            construction.get("recipeDigest"),
            "Atlas 3.0 producer semanticConstruction recipeDigest",
        )
        expected_semantic_recipe = _canonical_digest(
            {
                "adapterRecipes": [
                    {
                        "adapterRecipeDigest": release["adapterRecipeDigest"],
                        "key": release["key"],
                    }
                    for release in _sequence(
                        construction_summary.get("releases"),
                        "Atlas 3.0 construction releases",
                    )
                ],
                "profile": construction["profile"],
                "sharedRecipeDigest": construction_summary["recipeDigest"],
            }
        )
        if (
            construction.get("profile")
            != "atlas-3-exact-input-whole-distribution-reuse-v1"
            or construction.get("reuseScope")
            != "wholeDistributionExactInputsOnly"
            or construction.get("recipeDigest")
            != expected_semantic_recipe
        ):
            raise Atlas3ExplorerError(
                "Atlas 3.0 producer semanticConstruction identity differs"
            )


def _verify_streamed_dataset(
    manifest: Mapping[str, Any],
    index: _StreamedAtlasIndex,
) -> None:
    expected_graph_counts = {
        cast(str, row["role"]): cast(int, row["quadCount"])
        for row in cast(Sequence[Mapping[str, Any]], manifest["graphs"])
    }
    observed_graph_counts = {
        role: index.graph_quad_counts.get(role, 0)
        for role in expected_graph_counts
    }
    if observed_graph_counts != expected_graph_counts:
        raise Atlas3ExplorerError("Atlas 3.0 graph quad counts differ from the manifest")
    observed_record_counts = {
        field: index.record_counts.get(field, 0)
        for field in _COUNT_FIELDS
    }
    if observed_record_counts != dict(cast(Mapping[str, int], manifest["counts"])):
        raise Atlas3ExplorerError("Atlas 3.0 RDF record counts differ from the manifest")
    if sum(index.resources_by_ring.values()) != manifest["counts"]["resources"]:
        raise Atlas3ExplorerError("Atlas 3.0 resource ring counts do not reconcile")
    if sum(index.resources_by_release.values()) != manifest["counts"]["resources"]:
        raise Atlas3ExplorerError("Atlas 3.0 resource release counts do not reconcile")
    if sum(index.asserted_relations_by_kind.values()) != manifest["counts"]["relationAssertions"]:
        raise Atlas3ExplorerError("Atlas 3.0 asserted relation-kind counts do not reconcile")
    if sum(index.source_records_by_release.values()) != manifest["counts"]["sourceRecords"]:
        raise Atlas3ExplorerError("Atlas 3.0 source-record release counts do not reconcile")
    if not set(index.source_records_by_release).issubset(index.source_release_ids):
        raise Atlas3ExplorerError("Atlas 3.0 source records name an undeclared source release")


def _parse_nquad_term(token: bytes, label: str) -> URIRef | Literal:
    try:
        value = from_n3(token.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise Atlas3ExplorerError(f"sampled Atlas 3.0 {label} is malformed") from error
    if not isinstance(value, (URIRef, Literal)):
        raise Atlas3ExplorerError(f"sampled Atlas 3.0 {label} uses an unsupported RDF term")
    return value


def _nquad_fields(
    line: bytes,
    graph_suffixes: Mapping[str, bytes],
) -> tuple[bytes, bytes, bytes, str]:
    subject_end = line.find(b"> ", 1)
    if subject_end < 0:
        raise Atlas3ExplorerError("sampled Atlas 3.0 N-Quad has a malformed subject")
    subject = line[: subject_end + 1]
    predicate_start = subject_end + 2
    predicate_end = line.find(b"> ", predicate_start + 1)
    graph_start = line.rfind(b" <") + 1
    if predicate_end < predicate_start or graph_start <= predicate_end + 2:
        raise Atlas3ExplorerError("sampled Atlas 3.0 N-Quad is malformed")
    role = next((name for name, suffix in graph_suffixes.items() if line.endswith(suffix)), None)
    if role is None:
        raise Atlas3ExplorerError("sampled Atlas 3.0 N-Quad uses an undeclared graph")
    return (
        subject,
        line[predicate_start : predicate_end + 1],
        line[predicate_end + 2 : graph_start - 1],
        role,
    )


def _add_sample_quad(
    dataset: Dataset,
    graph_ids: Mapping[str, URIRef],
    subject: bytes,
    predicate: bytes,
    object_value: bytes,
    role: str,
) -> None:
    subject_term = _parse_nquad_term(subject, "subject")
    predicate_term = _parse_nquad_term(predicate, "predicate")
    object_term = _parse_nquad_term(object_value, "object")
    if not isinstance(subject_term, URIRef) or not isinstance(predicate_term, URIRef):
        raise Atlas3ExplorerError("sampled Atlas 3.0 subject and predicate must be IRIs")
    dataset.graph(graph_ids[role]).add((subject_term, predicate_term, object_term))


def _visual_index_is_complete(index: _StreamedAtlasIndex) -> bool:
    return (
        index.record_counts.get("resources", 0) <= _VISUAL_RELATION_RESOURCE_BUDGET
        and index.record_counts.get("identifiers", 0) <= _VISUAL_IDENTIFIER_LIMIT
        and index.record_counts.get("mappingAssertions", 0)
        + index.record_counts.get("nativeRelationAssertions", 0)
        + index.record_counts.get("crossRingRelationAssertions", 0)
        <= _VISUAL_TOPIC_ASSERTION_LIMIT
        and index.record_counts.get("sourceAssignments", 0) <= _VISUAL_SOURCE_ASSIGNMENT_LIMIT
        and index.record_counts.get("projectedRelations", 0) <= _VISUAL_PROJECTED_RELATION_LIMIT
        and index.record_counts.get("derivedRelations", 0) <= _VISUAL_DERIVED_RELATION_LIMIT
    )


def _iter_pack_content_lines(plans: Sequence[_PackPlan]) -> Iterator[bytes]:
    for plan in plans:
        with _open_pack_content(plan) as stream:
            while line := stream.readline(_NQUADS_MAX_LINE_BYTES + 1):
                if len(line) > _NQUADS_MAX_LINE_BYTES:
                    raise Atlas3ExplorerError(
                        f"Atlas 3.0 pack {plan.relative_path} line exceeds "
                        f"{_NQUADS_MAX_LINE_BYTES} bytes"
                    )
                yield line


def _materialize_visual_dataset(
    plans: Sequence[_PackPlan],
    index: _StreamedAtlasIndex,
    graph_ids: Mapping[str, URIRef],
) -> Dataset:
    """Read only selected records into RDFLib; never construct the full dataset."""

    dataset = Dataset(default_union=False)
    graph_suffixes = {
        role: b" " + _nquad_iri_token(graph_id) + b" .\n"
        for role, graph_id in graph_ids.items()
    }
    complete_small_distribution = _visual_index_is_complete(index)
    assertion_ids = set(index.assertion_ids)
    selected_subjects = {
        *index.atlas_release_ids,
        *index.source_release_ids,
        *index.resource_ids,
        *index.identifier_ids,
        *index.assertion_ids,
        *index.projected_relation_ids,
        *index.derived_relation_ids,
    }
    label_ids: set[bytes] = set()
    evidence_ids: set[bytes] = set()
    policy_ids: set[bytes] = set()
    source_record_ids: set[bytes] = set()
    scheme_ids: set[bytes] = set()
    for line in _iter_pack_content_lines(plans):
        subject, predicate, object_value, role = _nquad_fields(line, graph_suffixes)
        if predicate == _ATLAS_BINDS_ASSERTION_TOKEN and object_value in assertion_ids:
            evidence_ids.add(subject)
        include = (
            complete_small_distribution
            or subject in selected_subjects
            or subject in label_ids
            or subject in evidence_ids
            or subject in policy_ids
            or subject in source_record_ids
        )
        if not include or predicate == _PROV_HAD_MEMBER_TOKEN:
            continue
        _add_sample_quad(dataset, graph_ids, subject, predicate, object_value, role)
        if predicate in _LABEL_PREDICATE_TOKENS:
            label_ids.add(object_value)
        elif predicate == _ATLAS_GOVERNED_BY_POLICY_TOKEN:
            policy_ids.add(object_value)
        elif predicate in {_ATLAS_SOURCE_RECORD_TOKEN, _ATLAS_EVIDENCE_SOURCE_RECORD_TOKEN}:
            source_record_ids.add(object_value)
        elif predicate == _ATLAS_IDENTIFIER_SCHEME_TOKEN:
            scheme_ids.add(object_value)

    if complete_small_distribution:
        return dataset

    processed_dependencies: set[bytes] = set()
    for _pass in range(3):
        dependency_ids = label_ids | evidence_ids | policy_ids | source_record_ids | scheme_ids
        pending_ids = dependency_ids - processed_dependencies
        if not pending_ids:
            break
        seen_ids: set[bytes] = set()
        for line in _iter_pack_content_lines(plans):
            subject, predicate, object_value, role = _nquad_fields(line, graph_suffixes)
            if subject not in pending_ids:
                continue
            seen_ids.add(subject)
            _add_sample_quad(dataset, graph_ids, subject, predicate, object_value, role)
            if predicate in _LABEL_PREDICATE_TOKENS:
                label_ids.add(object_value)
            elif predicate == _ATLAS_GOVERNED_BY_POLICY_TOKEN:
                policy_ids.add(object_value)
            elif predicate in {_ATLAS_SOURCE_RECORD_TOKEN, _ATLAS_EVIDENCE_SOURCE_RECORD_TOKEN}:
                source_record_ids.add(object_value)
        missing_ids = pending_ids - seen_ids
        if missing_ids:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 visual sample has {len(missing_ids)} unresolved dependency records"
            )
        processed_dependencies.update(seen_ids)
    unresolved_dependencies = (
        label_ids | evidence_ids | policy_ids | source_record_ids
    ) - processed_dependencies
    if unresolved_dependencies:
        raise Atlas3ExplorerError(
            f"Atlas 3.0 visual sample dependency closure exceeds three streaming passes: "
            f"{len(unresolved_dependencies)} records remain"
        )
    return dataset


def _verify_source_accounting(
    manifest: Mapping[str, Any],
    accounting: Mapping[str, Any],
    asserted: Graph,
) -> None:
    if (
        accounting.get("type") != "AtlasSourceAccounting"
        or accounting.get("version") != "3.0"
        or accounting.get("distributionId") != manifest.get("distributionId")
    ):
        raise Atlas3ExplorerError("Atlas 3.0 source accounting belongs to another distribution")
    graph_records = {str(value) for value in asserted.subjects(RDF.type, ATLAS.SourceRecord)}
    graph_releases = {str(value) for value in asserted.subjects(RDF.type, ATLAS.SourceRelease)}
    input_releases: set[str] = set()
    dispositions: dict[str, Mapping[str, Any]] = {}
    status_counts = {"represented": 0, "excluded": 0, "unresolved": 0}
    inputs = _sequence(accounting.get("inputs"), "Atlas 3.0 source accounting inputs")
    for raw_input in inputs:
        source = _mapping(raw_input, "Atlas 3.0 source accounting input")
        source_release = _text(source.get("sourceRelease"), "Atlas 3.0 source release")
        if source_release in input_releases or source_release not in graph_releases:
            raise Atlas3ExplorerError("Atlas 3.0 source accounting repeats or invents a source release")
        input_releases.add(source_release)
        rows = _sequence(source.get("dispositions"), "Atlas 3.0 source dispositions")
        if source.get("membershipMode") in {"complete", "partial"} and source.get("declaredMemberCount") != len(rows):
            raise Atlas3ExplorerError("Atlas 3.0 source declaredMemberCount differs from its dispositions")
        for raw_disposition in rows:
            disposition = _mapping(raw_disposition, "Atlas 3.0 source disposition")
            record = _text(disposition.get("sourceRecord"), "Atlas 3.0 disposition sourceRecord")
            status_value = disposition.get("status")
            if record in dispositions or record not in graph_records or status_value not in status_counts:
                raise Atlas3ExplorerError("Atlas 3.0 source accounting repeats or invents a source record")
            if URIRef(source_release) not in asserted.objects(URIRef(record), ATLAS.inSourceRelease):
                raise Atlas3ExplorerError("Atlas 3.0 source record is assigned to the wrong source release")
            atlas_resources = _sequence(
                disposition.get("atlasResources", []),
                f"Atlas 3.0 disposition {record} atlasResources",
            )
            ledger_resources = {str(value) for value in atlas_resources}
            if len(ledger_resources) != len(atlas_resources):
                raise Atlas3ExplorerError(f"Atlas 3.0 disposition {record} repeats an Atlas resource")
            graph_resources = {
                str(value)
                for value in asserted.objects(URIRef(record), ATLAS.representsResource)
            }
            inverse_resources = {
                str(resource)
                for resource in asserted.subjects(ATLAS.sourceRecord, URIRef(record))
                if any((resource, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES)
            }
            if not (ledger_resources == graph_resources == inverse_resources):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 disposition {record} differs from its bidirectional RDF resource links"
                )
            atlas_assertions = _sequence(
                disposition.get("atlasAssertions", []),
                f"Atlas 3.0 disposition {record} atlasAssertions",
            )
            ledger_assertions = {str(value) for value in atlas_assertions}
            if len(ledger_assertions) != len(atlas_assertions):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 disposition {record} repeats an Atlas assertion"
                )
            evidence_bindings = set(
                asserted.subjects(ATLAS.evidenceSourceRecord, URIRef(record))
            )
            graph_assertions = {
                str(assertion)
                for evidence in evidence_bindings
                for assertion in asserted.objects(evidence, RKAF.bindsAssertion)
            }
            mapping_assertions = {
                assertion
                for assertion in graph_assertions
                if (
                    URIRef(assertion),
                    RDF.type,
                    ATLAS.MappingAssertion,
                ) in asserted
            }
            if "atlasAssertions" in disposition and ledger_assertions != graph_assertions:
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 disposition {record} differs from its evidence-backed assertions"
                )
            if (
                mapping_assertions
                and not ledger_resources
                and ledger_assertions != mapping_assertions
            ):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 disposition {record} does not exactly account for its mappings"
                )
            for assertion in ledger_assertions:
                if (
                    URIRef(assertion),
                    RDF.type,
                    ATLAS.RelationAssertion,
                ) not in asserted:
                    raise Atlas3ExplorerError(
                        f"Atlas 3.0 disposition {record} names an unknown assertion"
                    )
            if status_value == "represented":
                if not (ledger_resources or ledger_assertions) or "reason" in disposition:
                    raise Atlas3ExplorerError(
                        f"represented Atlas 3.0 disposition {record} needs resources or assertions and no reason"
                    )
            else:
                if (
                    ledger_resources
                    or ledger_assertions
                    or "atlasResources" in disposition
                    or "atlasAssertions" in disposition
                    or "reason" not in disposition
                ):
                    raise Atlas3ExplorerError(
                        f"{status_value} Atlas 3.0 disposition {record} needs a reason and no resources or assertions"
                    )
                _text(disposition["reason"], f"Atlas 3.0 disposition {record} reason")
            for resource in ledger_resources:
                resource_iri = URIRef(resource)
                if not any((resource_iri, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
                    raise Atlas3ExplorerError(f"Atlas 3.0 disposition {record} names an unknown resource")
            dispositions[record] = disposition
            status_counts[cast(str, status_value)] += 1
    if set(dispositions) != graph_records or input_releases != graph_releases:
        raise Atlas3ExplorerError("Atlas 3.0 source accounting is not complete for the asserted graph")
    expected_totals = {
        "sourceReleases": len(input_releases),
        "sourceRecords": len(dispositions),
        **status_counts,
    }
    if accounting.get("totals") != expected_totals:
        raise Atlas3ExplorerError("Atlas 3.0 source-accounting totals do not reconcile")


def _source_accounting_summary(
    manifest: Mapping[str, Any],
    index: _StreamedAtlasIndex,
    accounting: Mapping[str, Any] | None,
    *,
    directly_verified: bool,
) -> dict[str, Any]:
    if accounting is None:
        inputs = [
            {
                "sourceRelease": _raw_iri_text(release, "source release"),
                "sourceRecords": count,
                "represented": index.represented_source_records_by_release.get(release, 0),
                "unrepresented": count - index.represented_source_records_by_release.get(release, 0),
            }
            for release in sorted(index.source_release_ids)
            for count in (index.source_records_by_release.get(release, 0),)
        ]
        return {
            "type": "AtlasSourceAccountingSummary",
            "version": "3.0",
            "distributionId": manifest["distributionId"],
            "verification": "sealedAcceptanceReceiptAndStreamedRdfCounts",
            "inputs": inputs,
            "totals": {
                "sourceReleases": len(index.source_release_ids),
                "sourceRecords": sum(index.source_records_by_release.values()),
                "represented": sum(index.represented_source_records_by_release.values()),
                "unrepresented": (
                    sum(index.source_records_by_release.values())
                    - sum(index.represented_source_records_by_release.values())
                ),
            },
        }

    input_summaries: list[dict[str, Any]] = []
    for raw_source in _sequence(accounting.get("inputs"), "Atlas 3.0 source accounting inputs"):
        source = _mapping(raw_source, "Atlas 3.0 source accounting input")
        status_counts: Counter[str] = Counter()
        represented_resources = 0
        represented_assertions = 0
        dispositions = _sequence(source.get("dispositions"), "Atlas 3.0 source dispositions")
        for raw_disposition in dispositions:
            disposition = _mapping(raw_disposition, "Atlas 3.0 source disposition")
            status_counts[_text(disposition.get("status"), "Atlas 3.0 source status")] += 1
            represented_resources += len(
                _sequence(
                    disposition.get("atlasResources", []),
                    "Atlas 3.0 disposition resources",
                )
            )
            represented_assertions += len(
                _sequence(
                    disposition.get("atlasAssertions", []),
                    "Atlas 3.0 disposition assertions",
                )
            )
        input_summaries.append(
            {
                "sourceRelease": _text(source.get("sourceRelease"), "Atlas 3.0 source release"),
                "membershipMode": source.get("membershipMode"),
                "declaredMemberCount": source.get("declaredMemberCount"),
                "sourceRecords": len(dispositions),
                "representedResources": represented_resources,
                "representedAssertions": represented_assertions,
                "statusCounts": dict(sorted(status_counts.items())),
            }
        )
    return {
        "type": "AtlasSourceAccountingSummary",
        "version": "3.0",
        "distributionId": manifest["distributionId"],
        "verification": (
            "directForCompleteVisualIndex"
            if directly_verified
            else "canonicalAccountingAndSealedAcceptanceReceipt"
        ),
        "inputs": input_summaries,
        "totals": dict(_mapping(accounting.get("totals"), "Atlas 3.0 source totals")),
    }


def _coverage_view(index: _StreamedAtlasIndex) -> dict[str, Any]:
    def iri(token: bytes, label: str) -> str:
        return _raw_iri_text(token, label)

    return {
        "resourcesByRing": {
            _iri_name(iri(ring, "resource ring")): count
            for ring, count in sorted(index.resources_by_ring.items())
        },
        "resourcesByRelease": [
            {
                "release": iri(release, "Atlas release"),
                "count": index.resources_by_release.get(release, 0),
            }
            for release in sorted(index.atlas_release_ids)
        ],
        "resourcesByReleaseAndRing": [
            {
                "release": iri(release, "Atlas release"),
                "ring": _iri_name(iri(ring, "resource ring")),
                "count": count,
            }
            for (release, ring), count in sorted(index.resources_by_release_ring.items())
        ],
        "assertedRelationsByRing": {
            _iri_name(iri(ring, "assertion ring")): count
            for ring, count in sorted(index.asserted_relations_by_ring.items())
        },
        "crossRingRelationsByPair": [
            {
                "sourceRing": _iri_name(iri(source_ring, "assertion source ring")),
                "targetRing": _iri_name(iri(target_ring, "assertion target ring")),
                "count": count,
            }
            for (source_ring, target_ring), count in sorted(
                index.cross_ring_relations_by_pair.items()
            )
        ],
        "assertedRelationsByKind": dict(sorted(index.asserted_relations_by_kind.items())),
        "sourceRecordsByRelease": [
            {
                "sourceRelease": iri(release, "source release"),
                "sourceRecords": count,
                "represented": index.represented_source_records_by_release.get(release, 0),
                "unrepresented": count - index.represented_source_records_by_release.get(release, 0),
            }
            for release in sorted(index.source_release_ids)
            for count in (index.source_records_by_release.get(release, 0),)
        ],
    }


def _scan_binary_member(path: Path) -> tuple[int, str]:
    with path.open("rb") as stream:
        return _scan_binary_stream(stream)


def _scan_binary_stream(stream: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_length = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        byte_length += len(chunk)
    return byte_length, "sha256:" + digest.hexdigest()


class _DigestingReader:
    """Hash compressed bytes while the decoder consumes them."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._digest = hashlib.sha256()
        self._byte_length = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if chunk:
            self._digest.update(chunk)
            self._byte_length += len(chunk)
        return chunk

    def readable(self) -> bool:
        return True

    def finish(self) -> tuple[tuple[int, str], bool]:
        trailing = self.read(1024 * 1024)
        had_trailing = bool(trailing)
        while trailing:
            trailing = self.read(1024 * 1024)
        return (
            (self._byte_length, "sha256:" + self._digest.hexdigest()),
            had_trailing,
        )


@contextmanager
def _open_pack_raw(plan: _PackPlan) -> Iterator[BinaryIO]:
    """Open one exact transport and reject path replacement around the read."""

    try:
        with plan.path.open("rb") as raw_stream:
            opened_status = os.fstat(raw_stream.fileno())
            if not stat.S_ISREG(opened_status.st_mode) or _file_identity(opened_status) != plan.identity:
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 pack {plan.relative_path} changed while it was being opened"
                )
            yield raw_stream
            final_status = os.fstat(raw_stream.fileno())
        current_status = plan.path.lstat()
    except Atlas3ExplorerError:
        raise
    except OSError as error:
        raise Atlas3ExplorerError(
            f"Atlas 3.0 pack {plan.relative_path} changed while it was being read"
        ) from error
    if (
        _file_identity(final_status) != plan.identity
        or stat.S_ISLNK(current_status.st_mode)
        or _file_identity(current_status) != plan.identity
    ):
        raise Atlas3ExplorerError(
            f"Atlas 3.0 pack {plan.relative_path} changed while it was being read"
        )


@contextmanager
def _open_pack_content(plan: _PackPlan) -> Iterator[BinaryIO]:
    """Yield one uncompressed pack stream without materializing its bytes."""

    with _open_pack_raw(plan) as raw_stream:
        if plan.compression == "none":
            yield raw_stream
            return
        try:
            with zstd.open(raw_stream, "rb") as content_stream:
                yield cast(BinaryIO, content_stream)
        except (OSError, EOFError, zstd.ZstdError) as error:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 pack {plan.relative_path} is not valid Zstandard content"
            ) from error


def _distribution_pack_plans(
    root: Path,
    manifest: Mapping[str, Any],
    compact_packs: Sequence[Mapping[str, Any]],
) -> tuple[tuple[_PackPlan, ...], tuple[_PackPlan, ...]]:
    """Close the transitive inventory and freeze RDF and compact transports."""

    pack_rows = tuple(
        _mapping(raw, "Atlas 3.0 manifest pack")
        for raw in _sequence(manifest.get("packs"), "Atlas 3.0 manifest packs")
    )
    expected_files = {
        _ROOT_MANIFEST,
    }
    for raw_member in _sequence(
        manifest.get("members"),
        "Atlas 3.0 manifest members",
    ):
        member = _mapping(raw_member, "Atlas 3.0 manifest member")
        expected_files.add(
            _safe_relative_path(
                member.get("path"),
                "Atlas 3.0 manifest member path",
            )
        )
    for pack in pack_rows:
        expected_files.add(_safe_relative_path(pack.get("path"), "Atlas 3.0 pack path"))
    compact_paths = {
        _safe_relative_path(
            pack.get("path"),
            "Atlas 3.0 compact pack path",
        )
        for pack in compact_packs
    }
    rdf_paths = {cast(str, pack["path"]) for pack in pack_rows}
    if compact_paths & expected_files:
        raise Atlas3ExplorerError(
            "Atlas 3.0 compact paths overlap manifest-owned files"
        )
    expected_files.update(compact_paths)
    expected_directories = {
        parent.as_posix()
        for relative in expected_files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }

    observed_files: set[str] = set()
    observed_directories: set[str] = set()
    statuses: dict[str, os.stat_result] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            path_status = path.lstat()
            if stat.S_ISLNK(path_status.st_mode) or not stat.S_ISDIR(path_status.st_mode):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 distribution member {relative} is an unsafe directory"
                )
            observed_directories.add(relative)
        for name in file_names:
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            path_status = path.lstat()
            if stat.S_ISLNK(path_status.st_mode) or not stat.S_ISREG(path_status.st_mode):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 distribution member {relative} must be a regular non-symlink file"
                )
            observed_files.add(relative)
            statuses[relative] = path_status
    if observed_files != expected_files or observed_directories != expected_directories:
        raise Atlas3ExplorerError(
            "Atlas 3.0 distribution paths differ; "
            f"missingFiles={sorted(expected_files - observed_files)}, "
            f"extraFiles={sorted(observed_files - expected_files)}, "
            f"missingDirectories={sorted(expected_directories - observed_directories)}, "
            f"extraDirectories={sorted(observed_directories - expected_directories)}"
        )

    plans: list[_PackPlan] = []
    for pack in pack_rows:
        relative = cast(str, pack["path"])
        transport = _mapping(pack.get("transport"), f"Atlas 3.0 pack {relative} transport")
        plans.append(
            _PackPlan(
                pack_id=cast(str, pack["packId"]),
                path=root / PurePosixPath(relative),
                relative_path=relative,
                compression=cast(str, transport["compression"]),
                identity=_file_identity(statuses[relative]),
                manifest_row=pack,
            )
        )
    compact_plans = tuple(
        _PackPlan(
            pack_id=cast(str, pack["packId"]),
            path=root / PurePosixPath(cast(str, pack["path"])),
            relative_path=cast(str, pack["path"]),
            compression="zstd",
            identity=_file_identity(statuses[cast(str, pack["path"])]),
            manifest_row=pack,
        )
        for pack in compact_packs
    )
    if rdf_paths & {plan.relative_path for plan in compact_plans}:
        raise Atlas3ExplorerError("Atlas 3.0 RDF and compact pack paths overlap")
    return tuple(plans), compact_plans


def _verify_compact_transports(plans: Sequence[_PackPlan]) -> None:
    """Hash each compact transport without decoding or parsing its JSONL rows."""

    for plan in plans:
        transport = _mapping(
            plan.manifest_row.get("transport"),
            f"Atlas 3.0 compact pack {plan.relative_path} transport",
        )
        with _open_pack_raw(plan) as stream:
            evidence = _scan_binary_stream(stream)
        if evidence != (transport["byteLength"], transport["digest"]):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 compact pack {plan.relative_path} transport pin differs"
            )


def _scan_packs(
    plans: Sequence[_PackPlan],
    graph_ids: Mapping[str, URIRef],
    manifest: Mapping[str, Any],
) -> _StreamedAtlasIndex:
    """Verify all pack pins and build one deterministic bounded global index."""

    builder = _StreamingIndexBuilder()
    graph_quad_counts: Counter[str] = Counter()
    total_content_bytes = 0
    for plan in plans:
        row = plan.manifest_row
        transport = _mapping(row["transport"], f"Atlas 3.0 pack {plan.relative_path} transport")
        content = _mapping(row["content"], f"Atlas 3.0 pack {plan.relative_path} content")
        with _open_pack_raw(plan) as raw_stream:
            if plan.compression == "zstd":
                transport_reader = _DigestingReader(raw_stream)
                try:
                    with zstd.open(transport_reader, "rb") as content_stream:
                        content_evidence = _scan_pack_content(
                            cast(BinaryIO, content_stream),
                            graph_ids,
                            builder,
                            label=f"pack {plan.relative_path}",
                        )
                except (OSError, EOFError, zstd.ZstdError) as error:
                    transport_evidence, _ = transport_reader.finish()
                    if transport_evidence != (
                        transport["byteLength"],
                        transport["digest"],
                    ):
                        raise Atlas3ExplorerError(
                            f"Atlas 3.0 pack {plan.relative_path} transport pin differs"
                        ) from error
                    raise Atlas3ExplorerError(
                        f"Atlas 3.0 pack {plan.relative_path} is not valid Zstandard content"
                    ) from error
                transport_evidence, had_trailing = transport_reader.finish()
                if had_trailing:
                    raise Atlas3ExplorerError(
                        f"Atlas 3.0 pack {plan.relative_path} contains bytes not consumed by its decoder"
                    )
            else:
                content_evidence = _scan_pack_content(
                    raw_stream,
                    graph_ids,
                    builder,
                    label=f"pack {plan.relative_path}",
                )
                transport_evidence = (
                    content_evidence.byte_length,
                    content_evidence.digest,
                )
        if transport_evidence != (
            transport["byteLength"],
            transport["digest"],
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 pack {plan.relative_path} transport pin differs"
            )
        observed_graph_counts = {
            role: content_evidence.graph_quad_counts.get(role, 0)
            for role in ("asserted", "projection", "derived")
        }
        if (
            content_evidence.byte_length != content["byteLength"]
            or content_evidence.digest != content["digest"]
            or content_evidence.quad_count != content["quadCount"]
            or observed_graph_counts != dict(cast(Mapping[str, int], row["graphCounts"]))
        ):
            raise Atlas3ExplorerError(
                f"Atlas 3.0 pack {plan.relative_path} content pin or counts differ"
            )
        total_content_bytes += content_evidence.byte_length
        graph_quad_counts.update(observed_graph_counts)

    asserted_graph = _mapping(
        _sequence(manifest["graphs"], "Atlas 3.0 manifest graphs")[0],
        "Atlas 3.0 asserted graph",
    )
    return builder.finish(
        byte_length=total_content_bytes,
        digest=cast(str, asserted_graph["inventoryDigest"]),
        graph_quad_counts=graph_quad_counts,
    )


def _provisional_graph_ids(manifest: Mapping[str, Any]) -> dict[str, URIRef]:
    rows = _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")
    if len(rows) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 manifest must declare exactly three graph roles")
    result: dict[str, URIRef] = {}
    for expected_role, raw_row in zip(("asserted", "projection", "derived"), rows, strict=True):
        row = _mapping(raw_row, f"Atlas 3.0 {expected_role} graph")
        if row.get("role") != expected_role:
            raise Atlas3ExplorerError("Atlas 3.0 manifest graph roles are out of order")
        result[expected_role] = URIRef(_text(row.get("id"), f"Atlas 3.0 {expected_role} graph id"))
    if len(set(result.values())) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 graph role IRIs must be distinct")
    return result


@dataclass(frozen=True, slots=True)
class Atlas3ExplorerDistribution:
    """A verified distribution with an exact summary and local fallback graph."""

    root: Path
    manifest_digest: str
    manifest: Mapping[str, Any]
    source_accounting: Mapping[str, Any]
    acceptance: Mapping[str, Any]
    construction_summary: Mapping[str, Any]
    trusted_manifest: bool
    binding_verified: bool
    coverage: Mapping[str, Any]
    visual_index: Mapping[str, Any]
    _dataset: Dataset
    _graph_ids: Mapping[str, URIRef]
    _streamed_index: _StreamedAtlasIndex
    _plans: tuple[_PackPlan, ...]

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        trusted_manifest_digest: str,
    ) -> Atlas3ExplorerDistribution:
        """Verify exact packed members and materialize a bounded visual index."""

        requested_root = Path(root)
        try:
            root_status = requested_root.lstat()
        except OSError as error:
            raise Atlas3ExplorerError(f"cannot open Atlas 3.0 distribution {requested_root}") from error
        if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
            raise Atlas3ExplorerError("Atlas 3.0 distribution root must be a real directory")
        resolved_root = requested_root.resolve(strict=True)
        manifest_path = resolved_root / _ROOT_MANIFEST
        try:
            manifest_status = manifest_path.lstat()
            manifest_payload = manifest_path.read_bytes()
        except OSError as error:
            raise Atlas3ExplorerError("Atlas 3.0 manifest is unavailable") from error
        if stat.S_ISLNK(manifest_status.st_mode) or not stat.S_ISREG(manifest_status.st_mode):
            raise Atlas3ExplorerError("Atlas 3.0 manifest must be a regular non-symlink file")
        if sha256_digest(manifest_payload) != _digest(
            trusted_manifest_digest,
            "trusted Atlas 3.0 manifest digest",
        ):
            raise Atlas3ExplorerError("Atlas 3.0 manifest differs from the trusted digest")
        manifest = _read_canonical_json(manifest_payload, "Atlas 3.0 manifest")
        graph_ids = _provisional_graph_ids(manifest)
        _verify_pack_rows(manifest)

        construction_summary_path = resolved_root / _CONSTRUCTION_SUMMARY_MEMBER
        try:
            construction_summary_status = construction_summary_path.lstat()
            construction_summary_payload = construction_summary_path.read_bytes()
        except OSError as error:
            raise Atlas3ExplorerError(
                "Atlas 3.0 construction summary is unavailable"
            ) from error
        if stat.S_ISLNK(construction_summary_status.st_mode) or not stat.S_ISREG(
            construction_summary_status.st_mode
        ):
            raise Atlas3ExplorerError(
                "Atlas 3.0 construction summary must be a regular non-symlink file"
            )
        construction_summary = _read_canonical_json(
            construction_summary_payload,
            "Atlas 3.0 construction summary",
        )
        provisional_compact_packs = tuple(
            _mapping(raw, "Atlas 3.0 compact pack")
            for raw in _sequence(
                construction_summary.get("compactPacks"),
                "Atlas 3.0 compact packs",
            )
        )
        plans, compact_plans = _distribution_pack_plans(
            resolved_root,
            manifest,
            provisional_compact_packs,
        )

        acceptance_path = resolved_root / _ACCEPTANCE_MEMBER
        accounting_path = resolved_root / _SOURCE_ACCOUNTING_MEMBER
        acceptance_payload = acceptance_path.read_bytes()
        acceptance = _read_canonical_json(acceptance_payload, "Atlas 3.0 acceptance")

        accounting_payload: bytes | None = None
        source_accounting: Mapping[str, Any] | None = None
        if accounting_path.stat().st_size <= _SOURCE_ACCOUNTING_INLINE_MAX_BYTES:
            accounting_payload = accounting_path.read_bytes()
            accounting_evidence = (len(accounting_payload), sha256_digest(accounting_payload))
            source_accounting = _read_canonical_json(accounting_payload, "Atlas 3.0 source accounting")
        else:
            accounting_evidence = _scan_binary_member(accounting_path)
        member_evidence = {
            _SOURCE_ACCOUNTING_MEMBER: accounting_evidence,
            _ACCEPTANCE_MEMBER: (len(acceptance_payload), sha256_digest(acceptance_payload)),
            _CONSTRUCTION_SUMMARY_MEMBER: (
                len(construction_summary_payload),
                sha256_digest(construction_summary_payload),
            ),
        }
        producer_validation_path = resolved_root / _PRODUCER_VALIDATION_MEMBER
        try:
            producer_validation_payload = producer_validation_path.read_bytes()
        except OSError as error:
            raise Atlas3ExplorerError(
                "Atlas 3.0 producer validation is unavailable"
            ) from error
        producer_validation = _read_canonical_json(
            producer_validation_payload,
            "Atlas 3.0 producer validation",
        )
        member_evidence[_PRODUCER_VALIDATION_MEMBER] = (
            len(producer_validation_payload),
            sha256_digest(producer_validation_payload),
        )
        manifest_digest, verified_graph_ids = _verify_manifest(
            manifest,
            manifest_payload,
            member_evidence,
            trusted_manifest_digest,
        )
        _verify_acceptance(
            manifest,
            acceptance,
            {name: digest for name, (_size, digest) in member_evidence.items()},
        )
        _verify_binding_evidence(manifest, acceptance)
        if verified_graph_ids != graph_ids:
            raise Atlas3ExplorerError("Atlas 3.0 graph roles changed during verification")

        verified_compact_packs = _verify_construction_summary(
            manifest,
            construction_summary,
            {name: digest for name, (_size, digest) in member_evidence.items()},
        )
        if verified_compact_packs != provisional_compact_packs:
            raise Atlas3ExplorerError(
                "Atlas 3.0 compact-pack inventory changed during verification"
            )
        _verify_compact_transports(compact_plans)

        streamed_index = _scan_packs(plans, graph_ids, manifest)
        _verify_streamed_dataset(manifest, streamed_index)
        dataset = _materialize_visual_dataset(plans, streamed_index, graph_ids)
        complete_small_distribution = _visual_index_is_complete(streamed_index)
        if source_accounting is not None and complete_small_distribution:
            _verify_source_accounting(
                manifest,
                source_accounting,
                dataset.graph(graph_ids["asserted"]),
            )
        accounting_summary = _source_accounting_summary(
            manifest,
            streamed_index,
            source_accounting,
            directly_verified=source_accounting is not None and complete_small_distribution,
        )
        accounting_totals = _mapping(
            accounting_summary.get("totals"),
            "Atlas 3.0 source accounting summary totals",
        )
        _verify_producer_validation(
            manifest,
            producer_validation,
            construction_summary,
            {name: digest for name, (_size, digest) in member_evidence.items()},
            _count(
                accounting_totals.get("sourceReleases"),
                "Atlas 3.0 source accounting summary sourceReleases",
            ),
        )
        coverage = _coverage_view(streamed_index)
        visual_index = {
            "algorithm": "sha256-lowest-stratified-relation-coherent-v1",
            "complete": _visual_index_is_complete(streamed_index),
            "limits": {
                "resources": _VISUAL_RESOURCE_LIMIT,
                "identifiers": _VISUAL_IDENTIFIER_LIMIT,
                "topicAssertions": _VISUAL_TOPIC_ASSERTION_LIMIT,
                "sourceAssignments": _VISUAL_SOURCE_ASSIGNMENT_LIMIT,
                "projectedRelations": _VISUAL_PROJECTED_RELATION_LIMIT,
                "derivedRelations": _VISUAL_DERIVED_RELATION_LIMIT,
                "provenanceAssertions": _VISUAL_PROVENANCE_ASSERTION_LIMIT,
            },
            "materialized": {
                "resources": len(streamed_index.resource_ids),
                "identifiers": len(streamed_index.identifier_ids),
                "assertedRelations": len(streamed_index.assertion_ids),
                "projectedRelations": len(streamed_index.projected_relation_ids),
                "derivedRelations": len(streamed_index.derived_relation_ids),
            },
            "oversizedRelationsSkipped": streamed_index.oversized_relations_skipped,
            "packCount": len(plans),
            "fullDatasetRdfLibParsed": False,
            "sourceRecordPayloadMode": (
                "complete" if _visual_index_is_complete(streamed_index) else "metadataOnly"
            ),
        }
        return cls(
            root=resolved_root,
            manifest_digest=manifest_digest,
            manifest=cast(Mapping[str, Any], deep_freeze_json(manifest)),
            source_accounting=cast(Mapping[str, Any], deep_freeze_json(accounting_summary)),
            acceptance=cast(Mapping[str, Any], deep_freeze_json(acceptance)),
            construction_summary=cast(
                Mapping[str, Any], deep_freeze_json(construction_summary)
            ),
            trusted_manifest=True,
            binding_verified=True,
            coverage=cast(Mapping[str, Any], deep_freeze_json(coverage)),
            visual_index=cast(Mapping[str, Any], deep_freeze_json(visual_index)),
            _dataset=dataset,
            _graph_ids=cast(Mapping[str, URIRef], deep_freeze_json(graph_ids)),
            _streamed_index=streamed_index,
            _plans=plans,
        )

    def graph(self, role: str) -> Graph:
        """Return the bounded visual materialization for one graph role."""

        graph_id = self._graph_ids.get(role)
        if graph_id is None:
            raise Atlas3ExplorerError(f"unknown Atlas 3.0 graph role {role!r}")
        return self._dataset.graph(graph_id)

    @property
    def dataset_quad_counts(self) -> Mapping[str, int]:
        """Return exact full-distribution quad counts by graph role."""

        return self._streamed_index.graph_quad_counts

    @property
    def asserted_graph(self) -> Graph:
        return self.graph("asserted")

    @property
    def projection_graph(self) -> Graph:
        return self.graph("projection")

    @property
    def derived_graph(self) -> Graph:
        return self.graph("derived")


def open_atlas_v3_explorer_distribution(
    root: str | Path,
    *,
    trusted_manifest_digest: str,
) -> Atlas3ExplorerDistribution:
    """Open one Atlas 3.0 distribution for evidence-aware exploration."""

    return Atlas3ExplorerDistribution.open(root, trusted_manifest_digest=trusted_manifest_digest)


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


def _nquad_iri_text_fast(token: bytes, label: str) -> str:
    if len(token) < 3 or not token.startswith(b"<") or not token.endswith(b">"):
        raise Atlas3ExplorerError(f"Atlas explorer {label} must be an IRI token")
    try:
        value = token[1:-1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise Atlas3ExplorerError(f"Atlas explorer {label} is not UTF-8") from error
    if not value or any(character.isspace() for character in value):
        raise Atlas3ExplorerError(f"Atlas explorer {label} is not an absolute IRI")
    return value


def _raw_object_iri(value: str, label: str) -> str:
    if len(value) < 3 or not value.startswith("<") or not value.endswith(">"):
        raise Atlas3ExplorerError(f"Atlas explorer {label} must be an IRI")
    return value[1:-1]


def _raw_object_literal(value: str, label: str) -> Literal:
    try:
        parsed = from_n3(value)
    except ValueError as error:
        raise Atlas3ExplorerError(f"Atlas explorer {label} is not an RDF literal") from error
    if not isinstance(parsed, Literal):
        raise Atlas3ExplorerError(f"Atlas explorer {label} is not an RDF literal")
    return parsed


def _record_fact_values(
    record: Mapping[str, Any],
    predicate: str,
    *,
    role: str = "asserted",
) -> list[str]:
    return [
        cast(str, fact[1])
        for fact in cast(Sequence[Sequence[str]], record.get("facts", ()))
        if len(fact) == 3 and fact[0] == predicate and fact[2] == role
    ]


def _record_iri_values(
    record: Mapping[str, Any],
    predicate: str,
    *,
    role: str = "asserted",
) -> list[str]:
    return [
        _raw_object_iri(value, f"{record['id']} {predicate}")
        for value in _record_fact_values(record, predicate, role=role)
    ]


def _one_record_iri(
    record: Mapping[str, Any],
    predicate: str,
    *,
    role: str = "asserted",
) -> str:
    values = _record_iri_values(record, predicate, role=role)
    if len(values) != 1:
        raise Atlas3ExplorerError(
            f"Atlas explorer record {record['id']} needs one {predicate} value"
        )
    return values[0]


def _record_types(record: Mapping[str, Any], *, role: str = "asserted") -> set[str]:
    return set(_record_iri_values(record, str(RDF.type), role=role))


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


def _spool_raw_explorer_records(
    distribution: Atlas3ExplorerDistribution,
    spool: _JsonlSpool,
) -> None:
    graph_suffixes = {
        role: b" " + _nquad_iri_token(graph_id) + b" .\n"
        for role, graph_id in distribution._graph_ids.items()
    }
    for plan in distribution._plans:
        current_subject: bytes | None = None
        facts: list[list[str]] = []

        with _open_pack_content(plan) as stream:
            while line := stream.readline(_NQUADS_MAX_LINE_BYTES + 1):
                if len(line) > _NQUADS_MAX_LINE_BYTES:
                    raise Atlas3ExplorerError(
                        f"Atlas explorer pack {plan.relative_path} has an oversized line"
                    )
                subject, predicate, object_value, role = _nquad_fields(
                    line,
                    graph_suffixes,
                )
                if current_subject != subject:
                    if current_subject is not None:
                        record_id = _nquad_iri_text_fast(
                            current_subject,
                            "record id",
                        )
                        spool.append(
                            _explorer_hash_prefix(
                                record_id,
                                _EXPLORER_RECORD_PREFIX_LENGTH,
                            ),
                            {"facts": facts, "id": record_id},
                        )
                    current_subject = subject
                    facts = []
                try:
                    object_text = object_value.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise Atlas3ExplorerError(
                        f"Atlas explorer pack {plan.relative_path} has a non-UTF-8 object"
                    ) from error
                facts.append(
                    [
                        _nquad_iri_text_fast(predicate, "predicate"),
                        object_text,
                        role,
                    ]
                )
        if current_subject is not None:
            record_id = _nquad_iri_text_fast(current_subject, "record id")
            spool.append(
                _explorer_hash_prefix(
                    record_id,
                    _EXPLORER_RECORD_PREFIX_LENGTH,
                ),
                {"facts": facts, "id": record_id},
            )
    spool.close()


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


def _optional_record_iri(
    record: Mapping[str, Any],
    predicate: str,
    *,
    role: str = "asserted",
) -> str:
    values = _record_iri_values(record, predicate, role=role)
    if len(values) > 1:
        raise Atlas3ExplorerError(
            f"Atlas explorer record {record['id']} repeats {predicate}"
        )
    return values[0] if values else ""


def _explorer_relation_ring_summary(
    record: Mapping[str, Any],
    *,
    role: str,
) -> dict[str, str]:
    semantic_ring = _optional_record_iri(record, str(ATLAS.semanticRing), role=role)
    source_ring = _optional_record_iri(record, str(ATLAS.sourceRing), role=role)
    target_ring = _optional_record_iri(record, str(ATLAS.targetRing), role=role)
    if semantic_ring and not source_ring and not target_ring:
        return {
            "semanticRing": semantic_ring.rsplit("#", 1)[-1],
        }
    if not semantic_ring and source_ring and target_ring:
        return {
            "sourceRing": source_ring.rsplit("#", 1)[-1],
            "targetRing": target_ring.rsplit("#", 1)[-1],
        }
    raise Atlas3ExplorerError(
        f"Atlas explorer relation {record['id']} has invalid ring facts"
    )


def _explorer_relation_summary(
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    asserted_types = _record_types(record)
    projection_types = _record_types(record, role="projection")
    derived_types = _record_types(record, role="derived")
    if str(ATLAS.RelationAssertion) in asserted_types:
        kinds = [
            label
            for relation_type, label in RELATION_TYPES
            if str(relation_type) in asserted_types
        ]
        if len(kinds) != 1:
            raise Atlas3ExplorerError(
                f"Atlas explorer relation {record['id']} needs one specialization"
            )
        status = _one_record_iri(record, str(ATLAS.assertionStatus)).rsplit(
            "#", 1
        )[-1]
        predicate = _one_record_iri(record, str(RDF.predicate))
        return {
            "authoritative": status == "current",
            "authority": (
                "authoritative"
                if status == "current"
                else "historicalEditorialRecord"
            ),
            "id": record["id"],
            "kind": kinds[0],
            "layer": "asserted",
            "object": _one_record_iri(record, str(RDF.object)),
            "predicate": predicate,
            "predicateLabel": predicate.rstrip("/").rsplit("/", 1)[-1].rsplit(
                "#", 1
            )[-1],
            "sourceRelease": _one_record_iri(record, str(ATLAS.sourceRelease)),
            "status": status,
            "subject": _one_record_iri(record, str(RDF.subject)),
            "targetRelease": _one_record_iri(record, str(ATLAS.targetRelease)),
            **_explorer_relation_ring_summary(record, role="asserted"),
        }
    if str(ATLAS.ProjectedRelation) in projection_types:
        role = "projection"
        predicate = _one_record_iri(
            record,
            str(ATLAS.relationPredicate),
            role=role,
        )
        return {
            "authoritative": False,
            "authority": "reproducibleProjection",
            "id": record["id"],
            "kind": "projection",
            "layer": role,
            "object": _one_record_iri(
                record,
                str(ATLAS.relationObject),
                role=role,
            ),
            "predicate": predicate,
            "predicateLabel": predicate.rstrip("/").rsplit("/", 1)[-1].rsplit(
                "#", 1
            )[-1],
            "subject": _one_record_iri(
                record,
                str(ATLAS.relationSubject),
                role=role,
            ),
            "supportingAssertions": _record_iri_values(
                record,
                str(ATLAS.supportingAssertion),
                role=role,
            ),
            **_explorer_relation_ring_summary(record, role=role),
        }
    if str(ATLAS.DerivedRelation) in derived_types:
        role = "derived"
        predicate = _one_record_iri(
            record,
            str(ATLAS.relationPredicate),
            role=role,
        )
        return {
            "authoritative": False,
            "authority": "nonAuthoritative",
            "id": record["id"],
            "kind": "derived",
            "layer": role,
            "object": _one_record_iri(
                record,
                str(ATLAS.relationObject),
                role=role,
            ),
            "predicate": predicate,
            "predicateLabel": predicate.rstrip("/").rsplit("/", 1)[-1].rsplit(
                "#", 1
            )[-1],
            "subject": _one_record_iri(
                record,
                str(ATLAS.relationSubject),
                role=role,
            ),
            "derivedFromAssertions": _record_iri_values(
                record,
                str(ATLAS.derivedFromAssertion),
                role=role,
            ),
            **_explorer_relation_ring_summary(record, role=role),
        }
    return None


def _derive_explorer_record_joins(
    raw_spool: _JsonlSpool,
    merged_root: Path,
    augmentation_spool: _JsonlSpool,
    label_join_spool: _JsonlSpool,
    relation_spool: _JsonlSpool,
) -> None:
    merged_root.mkdir(parents=True, exist_ok=True)
    relation_types = {
        str(ATLAS.RelationAssertion): (
            "asserted",
            str(RDF.subject),
            str(RDF.object),
        ),
        str(ATLAS.ProjectedRelation): (
            "projection",
            str(ATLAS.relationSubject),
            str(ATLAS.relationObject),
        ),
        str(ATLAS.DerivedRelation): (
            "derived",
            str(ATLAS.relationSubject),
            str(ATLAS.relationObject),
        ),
    }
    for prefix in raw_spool.partition_keys():
        merged_path = merged_root / f"{prefix}.jsonl"
        with merged_path.open("wb") as output:
            for record in _iter_merged_spool_records(raw_spool.root / f"{prefix}.jsonl"):
                output.write(canonical_json_bytes(record))
                types = _record_types(record)
                record_id = cast(str, record["id"])
                if str(ATLAS.AtlasResource) in types:
                    release = _one_record_iri(record, str(ATLAS.inRelease))
                    ring = _one_record_iri(record, str(ATLAS.semanticRing)).rsplit("#", 1)[-1]
                    for predicate, role in LABEL_ROLES:
                        for label_id in _record_iri_values(record, str(predicate)):
                            label_join_spool.append(
                                _explorer_hash_prefix(
                                    label_id,
                                    _EXPLORER_JOIN_PREFIX_LENGTH,
                                ),
                                {
                                    "id": label_id,
                                    "kind": "reference",
                                    "release": release,
                                    "resource": record_id,
                                    "ring": ring,
                                    "role": role,
                                },
                            )
                if str(SKOSXL.Label) in types:
                    literals = _record_fact_values(record, str(SKOSXL.literalForm))
                    if len(literals) != 1:
                        raise Atlas3ExplorerError(
                            f"Atlas explorer label {record_id} needs one literal form"
                        )
                    literal = _raw_object_literal(literals[0], f"label {record_id}")
                    if not _english_display_literal(literal):
                        continue
                    label_row: dict[str, Any] = {
                        "id": record_id,
                        "kind": "label",
                        "value": str(literal),
                    }
                    if literal.language:
                        label_row["language"] = literal.language
                    label_join_spool.append(
                        _explorer_hash_prefix(
                            record_id,
                            _EXPLORER_JOIN_PREFIX_LENGTH,
                        ),
                        label_row,
                    )
                if str(RKAF.EvidenceBinding) in types:
                    assertion_id = _one_record_iri(record, str(RKAF.bindsAssertion))
                    _append_record_augmentation(
                        augmentation_spool,
                        assertion_id,
                        "evidenceBindings",
                        [record_id],
                    )
                if str(ATLAS.Identifier) in types:
                    resource_id = _one_record_iri(record, str(ATLAS.identifies))
                    _append_record_augmentation(
                        augmentation_spool,
                        resource_id,
                        "identifiers",
                        [record_id],
                    )
                for relation_type, relation_config in relation_types.items():
                    role, subject_predicate, object_predicate = relation_config
                    if relation_type not in _record_types(record, role=role):
                        continue
                    endpoint_ids = {
                        _one_record_iri(record, subject_predicate, role=role),
                        _one_record_iri(record, object_predicate, role=role),
                    }
                    for endpoint_id in endpoint_ids:
                        _append_record_augmentation(
                            augmentation_spool,
                            endpoint_id,
                            "relations",
                            [record_id],
                        )
                    relation_summary = _explorer_relation_summary(record)
                    if relation_summary is not None:
                        relation_spool.append(
                            _explorer_hash_prefix(record_id, 2),
                            relation_summary,
                        )
                    break
    augmentation_spool.close()
    label_join_spool.close()
    relation_spool.close()


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


def _derive_explorer_resource_summaries(
    label_join_spool: _JsonlSpool,
    summary_spool: _JsonlSpool,
) -> None:
    for prefix in label_join_spool.partition_keys():
        labels: dict[str, dict[str, Any]] = {}
        references: list[Mapping[str, Any]] = []
        with (label_join_spool.root / f"{prefix}.jsonl").open("rb") as stream:
            for line in stream:
                row = _mapping(json.loads(line), "Atlas explorer label join row")
                if row.get("kind") == "label":
                    labels[cast(str, row["id"])] = dict(row)
                elif row.get("kind") == "reference":
                    references.append(row)
                else:
                    raise Atlas3ExplorerError("Atlas explorer label join kind is invalid")
        for reference in references:
            label = labels.get(cast(str, reference["id"]))
            if label is None:
                raise Atlas3ExplorerError(
                    f"Atlas explorer resource {reference['resource']} has no English label record"
                )
            row = {
                "id": reference["resource"],
                "label": {
                    **({"language": label["language"]} if "language" in label else {}),
                    "role": reference["role"],
                    "value": label["value"],
                },
                "release": reference["release"],
                "ring": reference["ring"],
            }
            summary_spool.append(
                _explorer_hash_prefix(
                    cast(str, reference["resource"]),
                    _EXPLORER_RECORD_PREFIX_LENGTH,
                ),
                row,
            )
    summary_spool.close()


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


def _explorer_resource_metadata(
    augmentation_spool: _JsonlSpool,
) -> dict[str, dict[str, str]]:
    resources: dict[str, dict[str, str]] = {}
    for prefix in augmentation_spool.partition_keys():
        for resource_id, augmentation in _read_augmentations(
            augmentation_spool.root / f"{prefix}.jsonl"
        ).items():
            summary = augmentation.get("summary")
            if isinstance(summary, Mapping):
                resources[resource_id] = {
                    "displayLabel": _text(
                        summary.get("displayLabel"),
                        f"Atlas explorer resource {resource_id} display label",
                    ),
                    "release": _iri_text(
                        summary.get("release"),
                        f"Atlas explorer resource {resource_id} release",
                    ),
                    "ring": _text(
                        summary.get("ring"),
                        f"Atlas explorer resource {resource_id} ring",
                    ),
                }
    return resources


def _route_explorer_release_relations(
    relation_spool: _JsonlSpool,
    release_graph_spool: _JsonlSpool,
    resource_metadata: Mapping[str, Mapping[str, str]],
) -> None:
    atlas_releases = {
        metadata["release"]
        for metadata in resource_metadata.values()
        if metadata.get("release")
    }
    for key in relation_spool.partition_keys():
        with (relation_spool.root / f"{key}.jsonl").open("rb") as stream:
            for line in stream:
                row = dict(
                    _mapping(json.loads(line), "Atlas explorer relation summary row")
                )
                subject = cast(str, row["subject"])
                object_id = cast(str, row["object"])
                subject_resource = resource_metadata.get(subject)
                object_resource = resource_metadata.get(object_id)
                subject_release = (subject_resource or {}).get("release")
                object_release = (object_resource or {}).get("release")
                source_release = cast(
                    str,
                    row.get("sourceRelease")
                    or subject_release
                    or object_release,
                )
                target_release = cast(
                    str,
                    row.get("targetRelease")
                    or object_release
                    or subject_release,
                )
                if not source_release or not target_release:
                    raise Atlas3ExplorerError(
                        f"Atlas explorer relation {row['id']} has an endpoint without a release"
                    )
                enriched = {
                    **row,
                    "objectLabel": (object_resource or {}).get(
                        "displayLabel", object_id
                    ),
                    "sourceRelease": source_release,
                    "subjectLabel": (subject_resource or {}).get(
                        "displayLabel", subject
                    ),
                    "targetRelease": target_release,
                }
                releases = {source_release, target_release} & atlas_releases
                if not releases:
                    raise Atlas3ExplorerError(
                        f"Atlas explorer relation {row['id']} does not belong to an Atlas release"
                    )
                for release in releases:
                    release_graph_spool.append(
                        _explorer_hash_prefix(release, 64),
                        {"release": release, **enriched},
                    )
    release_graph_spool.close()


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


def _finalize_explorer_release_graph_shards(
    spool: _JsonlSpool,
    target_root: Path,
    manifest_digest: str,
    url_prefix: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    result: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for key in spool.partition_keys():
        entries_by_release: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        with (spool.root / f"{key}.jsonl").open("rb") as stream:
            for line in stream:
                row = dict(_mapping(json.loads(line), "Atlas explorer release graph row"))
                release = cast(str, row.pop("release"))
                entries_by_release[release][cast(str, row["id"])] = row
        for release in sorted(entries_by_release):
            entries = [
                entries_by_release[release][relation_id]
                for relation_id in sorted(entries_by_release[release])
            ]
            refs: list[dict[str, Any]] = []
            for offset in range(0, len(entries), _EXPLORER_PAGE_SIZE):
                page = entries[offset : offset + _EXPLORER_PAGE_SIZE]
                ref = _write_explorer_shard(
                    target_root,
                    "release-graph",
                    {
                        "entries": page,
                        "kind": "releaseGraph",
                        "manifestDigest": manifest_digest,
                        "release": release,
                        "type": _EXPLORER_SHARD_TYPE,
                        "version": _EXPLORER_SHARD_VERSION,
                    },
                    url_prefix=url_prefix,
                )
                ref["release"] = release
                refs.append(ref)
            result[release] = refs
            counts[release] = len(entries)
    return result, counts


def _finalize_explorer_release_resource_shards(
    spool: _JsonlSpool,
    target_root: Path,
    manifest_digest: str,
    url_prefix: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    result: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for key in spool.partition_keys():
        entries_by_release: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(
            dict
        )
        with (spool.root / f"{key}.jsonl").open("rb") as stream:
            for line in stream:
                row = dict(
                    _mapping(json.loads(line), "Atlas explorer release resource row")
                )
                release = cast(str, row["release"])
                entries_by_release[release][cast(str, row["id"])] = row
        for release in sorted(entries_by_release):
            entries = sorted(
                entries_by_release[release].values(),
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
                    "release-resources",
                    {
                        "entries": page,
                        "kind": "releaseResources",
                        "manifestDigest": manifest_digest,
                        "release": release,
                        "type": _EXPLORER_SHARD_TYPE,
                        "version": _EXPLORER_SHARD_VERSION,
                    },
                    url_prefix=url_prefix,
                )
                ref["release"] = release
                refs.append(ref)
            result[release] = refs
            counts[release] = len(entries)
    return result, counts


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


def _asserted_inventory_digest(manifest: Mapping[str, Any]) -> str:
    graph_rows = _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")
    asserted = next(
        (
            _mapping(row, "Atlas 3.0 asserted graph")
            for row in graph_rows
            if isinstance(row, Mapping) and row.get("role") == "asserted"
        ),
        None,
    )
    if asserted is None:
        raise Atlas3ExplorerError("Atlas 3.0 manifest has no asserted graph")
    return _digest(
        asserted.get("inventoryDigest"),
        "Atlas 3.0 asserted graph inventoryDigest",
    )


def build_atlas_v3_explorer_static_shards(
    distribution: Atlas3ExplorerDistribution,
    target: Path,
    *,
    url_prefix: str,
) -> dict[str, Any]:
    """Build immutable, digest-pinned JSON shards for complete HTTP browsing."""

    if not isinstance(distribution, Atlas3ExplorerDistribution):
        raise Atlas3ExplorerError("Atlas explorer shards require an opened distribution")
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized_prefix = PurePosixPath(url_prefix.rstrip("/"))
    if (
        normalized_prefix.is_absolute()
        or not normalized_prefix.parts
        or any(part in {"", ".", ".."} for part in normalized_prefix.parts)
    ):
        raise Atlas3ExplorerError("Atlas explorer shard URL prefix must be safe and relative")
    url_prefix = normalized_prefix.as_posix() + "/"
    manifest_digest = distribution.manifest_digest
    asserted_inventory_digest = _asserted_inventory_digest(distribution.manifest)
    with tempfile.TemporaryDirectory(
        dir=target.parent,
        prefix=f".{target.name}.building-",
    ) as temporary_name:
        workspace = Path(temporary_name)
        raw_spool = _JsonlSpool(workspace / "raw")
        merged_root = workspace / "merged"
        augmentation_spool = _JsonlSpool(workspace / "augment")
        label_join_spool = _JsonlSpool(workspace / "labels")
        summary_spool = _JsonlSpool(workspace / "summaries")
        catalog_spool = _JsonlSpool(workspace / "catalog")
        search_spool = _JsonlSpool(workspace / "search")
        relation_spool = _JsonlSpool(workspace / "relations")
        release_graph_spool = _JsonlSpool(workspace / "release-graphs")
        release_resource_spool = _JsonlSpool(workspace / "release-resources")
        published = workspace / "published"
        published.mkdir()

        _spool_raw_explorer_records(distribution, raw_spool)
        _derive_explorer_record_joins(
            raw_spool,
            merged_root,
            augmentation_spool,
            label_join_spool,
            relation_spool,
        )
        _derive_explorer_resource_summaries(label_join_spool, summary_spool)
        resource_count = _finalize_explorer_resource_summaries(
            summary_spool,
            augmentation_spool,
            catalog_spool,
            search_spool,
            release_resource_spool,
        )
        resource_metadata = _explorer_resource_metadata(augmentation_spool)
        _route_explorer_release_relations(
            relation_spool,
            release_graph_spool,
            resource_metadata,
        )
        record_shards, record_count = _finalize_explorer_record_shards(
            merged_root,
            augmentation_spool,
            published,
            manifest_digest,
            url_prefix,
        )
        catalog_shards = _finalize_explorer_page_shards(
            catalog_spool,
            published,
            "catalog",
            manifest_digest,
            url_prefix,
        )
        search_shards = _finalize_explorer_page_shards(
            search_spool,
            published,
            "search",
            manifest_digest,
            url_prefix,
        )
        release_resource_shards, release_resource_counts = (
            _finalize_explorer_release_resource_shards(
                release_resource_spool,
                published,
                manifest_digest,
                url_prefix,
            )
        )
        release_graph_shards, release_graph_counts = (
            _finalize_explorer_release_graph_shards(
                release_graph_spool,
                published,
                manifest_digest,
                url_prefix,
            )
        )
        expected_resources = _count(
            _mapping(distribution.manifest["counts"], "Atlas manifest counts").get(
                "resources"
            ),
            "Atlas manifest resource count",
        )
        if resource_count != expected_resources:
            raise Atlas3ExplorerError(
                "Atlas explorer resource summaries do not cover the full corpus"
            )
        if sum(release_resource_counts.values()) != resource_count:
            raise Atlas3ExplorerError(
                "Atlas explorer release resource pages do not cover the full corpus"
            )
        index_payload = {
            "assertedInventoryDigest": asserted_inventory_digest,
            "builderRecipe": ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE,
            "catalog": {"shards": catalog_shards},
            "counts": {
                "records": record_count,
                "releaseGraphEntries": sum(release_graph_counts.values()),
                "releaseResourceEntries": sum(release_resource_counts.values()),
                "resources": resource_count,
            },
            "manifestDigest": manifest_digest,
            "records": {
                "prefixLength": _EXPLORER_RECORD_PREFIX_LENGTH,
                "shards": record_shards,
            },
            "releaseGraphs": {
                "counts": release_graph_counts,
                "shards": release_graph_shards,
            },
            "releaseResources": {
                "counts": release_resource_counts,
                "shards": release_resource_shards,
            },
            "search": {"keyLength": 2, "shards": search_shards},
            "schema": _EXPLORER_SHARD_SCHEMA,
            "type": _EXPLORER_SHARD_INDEX_TYPE,
            "version": _EXPLORER_SHARD_VERSION,
        }
        index_ref = _write_explorer_shard(
            published,
            "index",
            index_payload,
            url_prefix=url_prefix,
        )
        generated = {
            child.name: child.read_bytes()
            for child in sorted(published.iterdir())
        }
        target_exists = target.exists()
        existing = _safe_existing_shard_directory(target)
        if target_exists:
            if existing != generated:
                raise Atlas3ExplorerError(
                    "immutable Atlas explorer shard directory differs for this manifest"
                )
        else:
            published.replace(target)
        return {
            "assertedInventoryDigest": asserted_inventory_digest,
            "builderRecipe": ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE,
            "counts": dict(index_payload["counts"]),
            "index": index_ref,
            "manifestDigest": manifest_digest,
            "schema": _EXPLORER_SHARD_SCHEMA,
            "type": _EXPLORER_SHARD_BUNDLE_TYPE,
            "version": _EXPLORER_SHARD_VERSION,
        }


def _compact_native_payload_metadata(value: object | None) -> object | None:
    if not isinstance(value, Mapping):
        return value
    selected: dict[str, Any] = {}
    for key in sorted(value):
        normalized = key.casefold()
        if not (
            key == "sourceIdentity"
            or key in _MAPPING_PROVENANCE_PAYLOAD_FIELDS
            or "status" in normalized
            or "tombstone" in normalized
            or "replacement" in normalized
            or normalized in {"deprecated", "deleted", "active"}
        ):
            continue
        child = value[key]
        encoded = json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) <= 2_048:
            selected[key] = child
        else:
            selected[key] = {
                "omittedFromVisualIndex": True,
                "itemCount": len(child) if isinstance(child, (Mapping, Sequence)) else 1,
            }
        if len(selected) == 32:
            break
    return selected


def _source_record_view(
    graph: Graph,
    record: URIRef,
    *,
    compact_native_payload: bool = False,
) -> dict[str, Any]:
    native_payload = _json_literal(
        _one(graph, record, ATLAS.nativePayload, label=f"source record {record}"),
        f"source record {record} nativePayload",
    )
    result = {
        "id": str(record),
        "sourceRelease": str(_one(graph, record, ATLAS.inSourceRelease, label=f"source record {record}")),
        "sourceLocator": str(_one(graph, record, ATLAS.sourceLocator, label=f"source record {record}")),
        "sourceDigest": str(_one(graph, record, ATLAS.sourceDigest, label=f"source record {record}")),
        "contentDigest": str(_one(graph, record, ATLAS.contentDigest, label=f"source record {record}")),
        "nativePayload": (
            _compact_native_payload_metadata(native_payload)
            if compact_native_payload
            else native_payload
        ),
        "representsResources": sorted(str(value) for value in graph.objects(record, ATLAS.representsResource)),
    }
    if compact_native_payload:
        result["nativePayloadMetadataOnly"] = True
    return result


def _label_view(graph: Graph, label: URIRef, role: str) -> dict[str, Any]:
    literal = _one(graph, label, SKOSXL.literalForm, label=f"label {label}")
    if not isinstance(literal, Literal) or not _english_display_literal(literal):
        raise Atlas3ExplorerError(f"label {label} literalForm must be English or language-neutral")
    return {
        "id": str(label),
        "role": role,
        **_literal_view(literal),
        "sourceRecord": str(_one(graph, label, ATLAS.sourceRecord, label=f"label {label}")),
        "contentDigest": str(_one(graph, label, ATLAS.contentDigest, label=f"label {label}")),
    }


def _resource_display_label(graph: Graph, resource: URIRef) -> str:
    candidates: list[tuple[int, str, str, str, str]] = []
    for role_order, (predicate, _role) in enumerate(LABEL_ROLES):
        for label in graph.objects(resource, predicate):
            if not isinstance(label, URIRef):
                continue
            literal = _one(graph, label, SKOSXL.literalForm, label=f"label {label}")
            if not isinstance(literal, Literal):
                raise Atlas3ExplorerError(f"label {label} literalForm must be a literal")
            if not _english_display_literal(literal):
                continue
            literal_view = _literal_view(literal)
            value = literal_view["value"]
            candidates.append(
                (
                    role_order,
                    literal_view.get("language", ""),
                    value.casefold(),
                    value,
                    str(label),
                )
            )
    if not candidates:
        raise Atlas3ExplorerError(f"resource {resource} has no asserted SKOS-XL label")
    return min(candidates)[3]


def _resource_view(
    graph: Graph,
    resource: URIRef,
    *,
    identifiers: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    labels: list[dict[str, Any]] = []
    for predicate, role in LABEL_ROLES:
        for value in graph.objects(resource, predicate):
            if not isinstance(value, URIRef):
                continue
            literal = _one(graph, value, SKOSXL.literalForm, label=f"label {value}")
            if isinstance(literal, Literal) and _english_display_literal(literal):
                labels.append(_label_view(graph, value, role))
    role_order = {role: position for position, (_predicate, role) in enumerate(LABEL_ROLES)}
    labels.sort(
        key=lambda row: (
            role_order[row["role"]],
            row.get("language", ""),
            cast(str, row["value"]).casefold(),
            row["value"],
            row["id"],
        )
    )
    if not labels:
        raise Atlas3ExplorerError(f"resource {resource} has no asserted SKOS-XL label")
    resource_types = [value for value in RESOURCE_TYPES if (resource, RDF.type, value) in graph]
    if len(resource_types) != 1:
        raise Atlas3ExplorerError(f"resource {resource} must have one Atlas 3.0 resource type")
    return {
        "id": str(resource),
        "resourceType": _iri_name(resource_types[0]),
        "release": str(_one(graph, resource, ATLAS.inRelease, label=f"resource {resource}")),
        "scheme": str(_one(graph, resource, ATLAS.inScheme, label=f"resource {resource}")),
        "semanticRing": _iri_name(_one(graph, resource, ATLAS.semanticRing, label=f"resource {resource}")),
        "resourceProfile": _iri_name(_one(graph, resource, ATLAS.resourceProfile, label=f"resource {resource}")),
        "displayLabel": labels[0]["value"],
        "displayLabelRole": labels[0]["role"],
        "labels": labels,
        "sourceRecords": sorted(str(value) for value in graph.objects(resource, ATLAS.sourceRecord)),
        "contentDigest": str(_one(graph, resource, ATLAS.contentDigest, label=f"resource {resource}")),
        "notations": sorted(str(value) for value in graph.objects(resource, ATLAS.notation)),
        "definitions": [
            _literal_view(value)
            for value in graph.objects(resource, ATLAS.definition)
            if isinstance(value, Literal) and _english_display_literal(value)
        ],
        "notes": [
            _literal_view(value)
            for value in graph.objects(resource, ATLAS.note)
            if isinstance(value, Literal) and _english_display_literal(value)
        ],
        "identifiers": [dict(row) for row in identifiers],
    }


def _resource_index_view(
    graph: Graph,
    resource: URIRef,
    display_label: str,
) -> dict[str, str]:
    """Return the small, complete resource row used by search and filtering."""

    return {
        "id": str(resource),
        "displayLabel": display_label,
        "release": str(_one(graph, resource, ATLAS.inRelease, label=f"resource {resource}")),
        "semanticRing": _iri_name(
            _one(graph, resource, ATLAS.semanticRing, label=f"resource {resource}")
        ),
    }


def _identifier_scheme_label(graph: Graph, scheme: URIRef) -> str:
    candidates: list[str] = []
    for predicate in (DCTERMS.title, DCTERMS.identifier):
        candidates.extend(
            str(value)
            for value in graph.objects(scheme, predicate)
            if isinstance(value, Literal) and str(value).strip()
        )
    for release in graph.subjects(ATLAS.inScheme, scheme):
        if not isinstance(release, URIRef) or (release, RDF.type, ATLAS.AtlasRelease) not in graph:
            continue
        for predicate in (DCTERMS.title, DCTERMS.identifier):
            candidates.extend(
                str(value)
                for value in graph.objects(release, predicate)
                if isinstance(value, Literal) and str(value).strip()
            )
    if candidates:
        return min(candidates, key=lambda value: (value.casefold(), value))
    return _iri_name(scheme)


def _identifier_view(graph: Graph, identifier: URIRef) -> dict[str, Any]:
    value = _one(graph, identifier, ATLAS.identifierValue, label=f"identifier {identifier}")
    scheme = _one(graph, identifier, ATLAS.identifierScheme, label=f"identifier {identifier}")
    identified_resource = _one(
        graph,
        identifier,
        ATLAS.identifies,
        label=f"identifier {identifier}",
    )
    if (
        not isinstance(value, Literal)
        or not str(value)
        or not isinstance(scheme, URIRef)
        or not isinstance(identified_resource, URIRef)
    ):
        raise Atlas3ExplorerError(f"identifier {identifier} has an invalid value, scheme, or target")
    source_records = sorted(
        str(record)
        for record in graph.objects(identifier, ATLAS.sourceRecord)
        if isinstance(record, URIRef)
    )
    result: dict[str, Any] = {
        "id": str(identifier),
        "value": str(value),
        "scheme": str(scheme),
        "schemeLabel": _identifier_scheme_label(graph, scheme),
        "identifies": str(identified_resource),
        "contentDigest": str(
            _one(graph, identifier, ATLAS.contentDigest, label=f"identifier {identifier}")
        ),
        "sourceRecordCount": len(source_records),
    }
    scheme_profile = _one(
        graph,
        scheme,
        ATLAS.resourceProfile,
        label=f"identifier scheme {scheme}",
        required=False,
    )
    if scheme_profile is not None:
        result["schemeProfile"] = _iri_name(scheme_profile)
    if len(source_records) == 1:
        result["sourceRecord"] = source_records[0]
    return result


def _policy_view(graph: Graph, policy: URIRef) -> dict[str, Any]:
    return {
        "id": str(policy),
        "contentDigest": str(_one(graph, policy, ATLAS.contentDigest, label=f"policy {policy}")),
        "payload": _json_literal(
            _one(graph, policy, ATLAS.policyPayload, label=f"policy {policy}"),
            f"policy {policy} payload",
        ),
    }


def _evidence_view(
    graph: Graph,
    binding: URIRef,
    source_record_content_digests: Mapping[str, str],
) -> dict[str, Any]:
    record = _one(graph, binding, ATLAS.evidenceSourceRecord, label=f"evidence {binding}")
    record_id = str(record)
    if not isinstance(record, URIRef) or record_id not in source_record_content_digests:
        raise Atlas3ExplorerError(f"evidence {binding} names an unavailable source record")
    result: dict[str, Any] = {
        "id": str(binding),
        "sourceRecord": record_id,
        "sourceRecordContentDigest": source_record_content_digests[record_id],
        "sourceDigest": str(_one(graph, binding, ATLAS.evidenceSourceDigest, label=f"evidence {binding}")),
        "decisionStatus": _iri_name(_one(graph, binding, RKAF.decision, label=f"evidence {binding}")),
        "reviewMethod": _iri_name(_one(graph, binding, ATLAS.reviewMethod, label=f"evidence {binding}")),
        "decidedAt": str(_one(graph, binding, RKAF.attestedAt, label=f"evidence {binding}")),
        "contentDigest": str(_one(graph, binding, ATLAS.contentDigest, label=f"evidence {binding}")),
    }
    for predicate, field in ((RKAF.attestor, "reviewedBy"),):
        value = _one(graph, binding, predicate, label=f"evidence {binding}", required=False)
        if value is not None:
            result[field] = str(value)
    return result


def _assertion_view(
    graph: Graph,
    assertion: URIRef,
    source_record_content_digests: Mapping[str, str],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    kinds = [label for relation_type, label in RELATION_TYPES if (assertion, RDF.type, relation_type) in graph]
    if len(kinds) != 1:
        raise Atlas3ExplorerError(f"assertion {assertion} must have one Atlas 3.0 specialization")
    subject = _one(graph, assertion, RDF.subject, label=f"assertion {assertion}")
    predicate = _one(graph, assertion, RDF.predicate, label=f"assertion {assertion}")
    object_value = _one(graph, assertion, RDF.object, label=f"assertion {assertion}")
    policy = _one(graph, assertion, ATLAS.governedByPolicy, label=f"assertion {assertion}")
    if not all(isinstance(value, URIRef) for value in (subject, predicate, object_value, policy)):
        raise Atlas3ExplorerError(f"assertion {assertion} endpoints, predicate, and policy must be IRIs")
    evidence = sorted(
        (
            _evidence_view(graph, binding, source_record_content_digests)
            for binding in graph.subjects(RKAF.bindsAssertion, assertion)
            if isinstance(binding, URIRef)
        ),
        key=lambda row: row["id"],
    )
    if not evidence:
        raise Atlas3ExplorerError(f"assertion {assertion} has no evidence binding")
    status = _iri_name(_one(graph, assertion, ATLAS.assertionStatus, label=f"assertion {assertion}"))
    ring_fields = _relation_ring_view(graph, assertion, label=f"assertion {assertion}")
    result: dict[str, Any] = {
        "id": str(assertion),
        "kind": kinds[0],
        "authority": "authoritative" if status == "current" else "historicalEditorialRecord",
        "authoritative": status == "current",
        "subject": str(subject),
        "subjectLabel": labels.get(str(subject), _iri_name(subject)),
        "predicate": str(predicate),
        "predicateLabel": _iri_name(predicate),
        "predicateMeaning": atlas_v3_predicate_meaning(str(predicate)),
        "object": str(object_value),
        "objectLabel": labels.get(str(object_value), _iri_name(object_value)),
        **ring_fields,
        "sourceRelease": str(_one(graph, assertion, ATLAS.sourceRelease, label=f"assertion {assertion}")),
        "targetRelease": str(_one(graph, assertion, ATLAS.targetRelease, label=f"assertion {assertion}")),
        "assertedAt": str(_one(graph, assertion, RKAF.assertedAt, label=f"assertion {assertion}")),
        "status": status,
        "identityDigest": str(
            _one(graph, assertion, ATLAS.assertionIdentityDigest, label=f"assertion {assertion}")
        ),
        "contentDigest": str(_one(graph, assertion, ATLAS.contentDigest, label=f"assertion {assertion}")),
        "policy": _policy_view(graph, cast(URIRef, policy)),
        "evidence": evidence,
    }
    supersedes = _one(graph, assertion, ATLAS.supersedes, label=f"assertion {assertion}", required=False)
    if supersedes is not None:
        result["supersedes"] = str(supersedes)
    return result


def _relation_ring_view(graph: Graph, relation: URIRef, *, label: str) -> dict[str, Any]:
    semantic_ring = _one(graph, relation, ATLAS.semanticRing, label=label, required=False)
    source_ring = _one(graph, relation, ATLAS.sourceRing, label=label, required=False)
    target_ring = _one(graph, relation, ATLAS.targetRing, label=label, required=False)
    if semantic_ring is not None and source_ring is None and target_ring is None:
        ring = _iri_name(semantic_ring)
        return {"semanticRing": ring, "semanticRings": [ring]}
    if semantic_ring is None and source_ring is not None and target_ring is not None:
        source = _iri_name(source_ring)
        target = _iri_name(target_ring)
        if source == target:
            raise Atlas3ExplorerError(f"{label} does not cross semantic rings")
        return {
            "sourceRing": source,
            "targetRing": target,
            "semanticRings": [source, target],
        }
    raise Atlas3ExplorerError(f"{label} has incomplete or conflicting ring fields")


def _projected_view(graph: Graph, relation: URIRef, labels: Mapping[str, str]) -> dict[str, Any]:
    subject = _one(graph, relation, ATLAS.relationSubject, label=f"projection {relation}")
    predicate = _one(graph, relation, ATLAS.relationPredicate, label=f"projection {relation}")
    object_value = _one(graph, relation, ATLAS.relationObject, label=f"projection {relation}")
    supporting_assertions = sorted(str(value) for value in graph.objects(relation, ATLAS.supportingAssertion))
    if not supporting_assertions:
        raise Atlas3ExplorerError(f"projection {relation} has no supporting assertion")
    return {
        "id": str(relation),
        "authority": "reproducibleProjection",
        "authoritative": False,
        "subject": str(subject),
        "subjectLabel": labels.get(str(subject), _iri_name(subject)),
        "predicate": str(predicate),
        "predicateLabel": _iri_name(predicate),
        "predicateMeaning": atlas_v3_predicate_meaning(str(predicate)),
        "object": str(object_value),
        "objectLabel": labels.get(str(object_value), _iri_name(object_value)),
        **_relation_ring_view(graph, relation, label=f"projection {relation}"),
        "supportingAssertions": supporting_assertions,
        "contentDigest": str(_one(graph, relation, ATLAS.contentDigest, label=f"projection {relation}")),
    }


def _derived_view(graph: Graph, relation: URIRef, labels: Mapping[str, str]) -> dict[str, Any]:
    subject = _one(graph, relation, ATLAS.relationSubject, label=f"derived relation {relation}")
    predicate = _one(graph, relation, ATLAS.relationPredicate, label=f"derived relation {relation}")
    object_value = _one(graph, relation, ATLAS.relationObject, label=f"derived relation {relation}")
    authority_status = _one(graph, relation, ATLAS.authorityStatus, label=f"derived relation {relation}")
    if authority_status != ATLAS.nonAuthoritative:
        raise Atlas3ExplorerError(f"derived relation {relation} is not explicitly non-authoritative")
    return {
        "id": str(relation),
        "authority": "nonAuthoritative",
        "authorityStatus": _iri_name(authority_status),
        "authoritative": False,
        "subject": str(subject),
        "subjectLabel": labels.get(str(subject), _iri_name(subject)),
        "predicate": str(predicate),
        "predicateLabel": _iri_name(predicate),
        "predicateMeaning": atlas_v3_predicate_meaning(str(predicate)),
        "object": str(object_value),
        "objectLabel": labels.get(str(object_value), _iri_name(object_value)),
        "semanticRing": _iri_name(
            _one(graph, relation, ATLAS.semanticRing, label=f"derived relation {relation}")
        ),
        "derivedFromAssertions": sorted(str(value) for value in graph.objects(relation, ATLAS.derivedFromAssertion)),
        "rule": str(_one(graph, relation, ATLAS.derivationRule, label=f"derived relation {relation}")),
        "engine": str(_one(graph, relation, ATLAS.engine, label=f"derived relation {relation}")),
        "engineVersion": str(_one(graph, relation, ATLAS.engineVersion, label=f"derived relation {relation}")),
        "inputDigest": str(_one(graph, relation, RKAF.inputDigest, label=f"derived relation {relation}")),
        "generatedAt": str(_one(graph, relation, ATLAS.generatedAt, label=f"derived relation {relation}")),
        "contentDigest": str(_one(graph, relation, ATLAS.contentDigest, label=f"derived relation {relation}")),
    }


def _release_view(
    graph: Graph,
    release: URIRef,
    *,
    source: bool,
    member_count: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(release),
        "kind": "source" if source else "atlas",
        "contentDigest": str(_one(graph, release, ATLAS.contentDigest, label=f"release {release}")),
    }
    optional_fields = (
        (DCTERMS.title, "title", False),
        (DCTERMS.identifier, "identifier", False),
        (DCTERMS.issued, "issued", False),
        (ATLAS.sourceLocator, "sourceLocator", False),
        (ATLAS.sourceDigest, "sourceDigest", False),
        (ATLAS.inScheme, "scheme", False),
        (ATLAS.sourceRelease, "sourceRelease", False),
        (ATLAS.resourceProfile, "resourceProfile", True),
        (ATLAS.semanticRing, "semanticRing", True),
    )
    for predicate, field, short_iri in optional_fields:
        value = _one(graph, release, predicate, label=f"release {release}", required=False)
        if value is not None:
            result[field] = _iri_name(value) if short_iri else str(value)
    if not source:
        result["memberCount"] = (
            member_count
            if member_count is not None
            else len(set(graph.objects(release, PROV.hadMember)))
        )
    return result


def _limit(rows: list[_LimitedRow], limit: int | None, label: str) -> list[_LimitedRow]:
    if limit is None:
        return rows
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise Atlas3ExplorerError(f"{label} must be a non-negative integer or None")
    return rows[:limit]


def build_atlas_v3_explorer_model(
    distribution: Atlas3ExplorerDistribution,
    *,
    title: str = "RefSpec Atlas 3.0 explorer",
    full_corpus: Mapping[str, Any] | None = None,
    max_resources: int | None = None,
    max_assertions: int | None = None,
    max_projected_relations: int | None = None,
    max_derived_relations: int | None = None,
) -> dict[str, Any]:
    """Build a JSON view whose relation collections retain their authority roles."""

    if not isinstance(distribution, Atlas3ExplorerDistribution):
        raise Atlas3ExplorerError("Atlas 3.0 explorer requires an opened distribution")
    _text(title, "Atlas 3.0 explorer title")
    for limit, label in (
        (max_resources, "max_resources"),
        (max_assertions, "max_assertions"),
        (max_projected_relations, "max_projected_relations"),
        (max_derived_relations, "max_derived_relations"),
    ):
        _limit([], limit, label)
    asserted = distribution.asserted_graph
    projection = distribution.projection_graph
    derived = distribution.derived_graph
    full_counts = cast(Mapping[str, int], distribution.manifest["counts"])
    release_member_counts = {
        _raw_iri_text(release, "Atlas release"): count
        for release, count in distribution._streamed_index.release_member_counts.items()
    }

    source_record_ids = sorted(
        (
            record
            for record in set(asserted.subjects(RDF.type, ATLAS.SourceRecord))
            if isinstance(record, URIRef)
        ),
        key=str,
    )
    source_record_by_id = {str(record): record for record in source_record_ids}
    source_record_content_digests = {
        str(record): str(_one(asserted, record, ATLAS.contentDigest, label=f"source record {record}"))
        for record in source_record_ids
    }
    resource_ids = [
        resource
        for resource in set(asserted.subjects(RDF.type, ATLAS.AtlasResource))
        if isinstance(resource, URIRef)
    ]
    labels = {
        str(resource): _resource_display_label(asserted, resource)
        for resource in resource_ids
    }
    resource_ids.sort(
        key=lambda resource: (
            labels[str(resource)].casefold(),
            labels[str(resource)],
            str(resource),
        )
    )
    resource_index = [
        _resource_index_view(asserted, resource, labels[str(resource)])
        for resource in resource_ids
    ]
    identifier_ids = sorted(
        (
            identifier
            for identifier in set(asserted.subjects(RDF.type, ATLAS.Identifier))
            if isinstance(identifier, URIRef)
        ),
        key=str,
    )
    identifier_rows = [_identifier_view(asserted, identifier) for identifier in identifier_ids]
    identifiers_by_resource: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for identifier in identifier_rows:
        target = cast(str, identifier["identifies"])
        if target not in labels:
            raise Atlas3ExplorerError(f"identifier {identifier['id']} names an unavailable resource")
        identifiers_by_resource[target].append(identifier)
    shown_resource_ids = _limit(resource_ids, max_resources, "max_resources")
    resources = [
        _resource_view(
            asserted,
            resource,
            identifiers=identifiers_by_resource.get(str(resource), ()),
        )
        for resource in shown_resource_ids
    ]
    assertion_ids = sorted(
        (
            assertion
            for assertion in set(asserted.subjects(RDF.type, ATLAS.RelationAssertion))
            if isinstance(assertion, URIRef)
        ),
        key=str,
    )
    primary_assertion_ids = _limit(assertion_ids, max_assertions, "max_assertions")
    projected_ids = sorted(
        (
            relation
            for relation in set(projection.subjects(RDF.type, ATLAS.ProjectedRelation))
            if isinstance(relation, URIRef)
        ),
        key=str,
    )
    shown_projected_ids = _limit(
        projected_ids,
        max_projected_relations,
        "max_projected_relations",
    )
    projected = [
        _projected_view(projection, relation, labels)
        for relation in shown_projected_ids
    ]
    derived_ids = sorted(
        (
            relation
            for relation in set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
            if isinstance(relation, URIRef)
        ),
        key=str,
    )
    shown_derived_ids = _limit(
        derived_ids,
        max_derived_relations,
        "max_derived_relations",
    )
    derived_rows = [
        _derived_view(derived, relation, labels)
        for relation in shown_derived_ids
    ]
    referenced_assertion_ids = {
        assertion_id
        for relation in (*projected, *derived_rows)
        for field in ("supportingAssertions", "derivedFromAssertions")
        for assertion_id in cast(Sequence[str], relation.get(field, ()))
    }
    assertion_by_id = {str(assertion): assertion for assertion in assertion_ids}
    unavailable_assertions = referenced_assertion_ids - set(assertion_by_id)
    if unavailable_assertions:
        raise Atlas3ExplorerError(
            "bounded Atlas 3.0 relations cite unavailable assertions: "
            f"{sorted(unavailable_assertions)}"
        )
    selected_assertion_ids = {str(assertion) for assertion in primary_assertion_ids}
    selected_assertion_ids.update(referenced_assertion_ids)
    shown_assertion_ids = [
        assertion_by_id[assertion_id]
        for assertion_id in sorted(selected_assertion_ids)
    ]
    assertions = [
        _assertion_view(
            asserted,
            assertion,
            source_record_content_digests,
            labels,
        )
        for assertion in shown_assertion_ids
    ]
    current_authoritative_relations = distribution._streamed_index.current_authoritative_relations
    shown_source_record_ids = {
        cast(str, record)
        for resource in resources
        for record in cast(Sequence[str], resource["sourceRecords"])
    } | {
        cast(str, evidence["sourceRecord"])
        for assertion in assertions
        for evidence in cast(Sequence[Mapping[str, Any]], assertion["evidence"])
    }
    shown_source_records = [
        _source_record_view(
            asserted,
            source_record_by_id[record_id],
            compact_native_payload=not cast(bool, distribution.visual_index["complete"]),
        )
        for record_id in sorted(shown_source_record_ids)
    ]
    graph_by_role = {
        cast(str, row["role"]): cast(str, row["id"])
        for row in cast(Sequence[Mapping[str, Any]], distribution.manifest["graphs"])
    }
    model = {
        "type": ATLAS_V3_EXPLORER_TYPE,
        "schemaVersion": ATLAS_V3_EXPLORER_SCHEMA_VERSION,
        "title": title,
        "distribution": {
            "id": distribution.manifest["distributionId"],
            "manifestDigest": distribution.manifest_digest,
            "assertedInventoryDigest": _asserted_inventory_digest(distribution.manifest),
            "trustedManifestDigestChecked": distribution.trusted_manifest,
            "createdAt": distribution.manifest["createdAt"],
            "counts": dict(cast(Mapping[str, Any], distribution.manifest["counts"])),
        },
        "visualIndex": _json_copy(distribution.visual_index),
        "coverage": _json_copy(distribution.coverage),
        "sourceAccounting": _json_copy(distribution.source_accounting),
        "acceptance": {
            "verdict": distribution.acceptance["verdict"],
            "receiptVerified": True,
            "bindingDigestChecked": distribution.binding_verified,
            "gatesReexecutedByExplorer": False,
            "evaluatedAt": distribution.acceptance["evaluatedAt"],
            "validator": dict(cast(Mapping[str, Any], distribution.acceptance["validator"])),
            "gates": [dict(cast(Mapping[str, Any], row)) for row in distribution.acceptance["gates"]],
        },
        "authority": {
            "asserted": {
                "graph": graph_by_role["asserted"],
                "status": "authoritative",
                "meaning": (
                    "Evidence-bearing current assertion records are editorial authority. "
                    "Every displayed assertion links to its policy and source-record evidence."
                ),
            },
            "projection": {
                "graph": graph_by_role["projection"],
                "status": "reproducibleConvenienceView",
                "meaning": (
                    "Bare relation triples and plain SKOS labels are generated from asserted records; "
                    "they are not independent editorial facts."
                ),
            },
            "derived": {
                "graph": graph_by_role["derived"],
                "status": "nonAuthoritative",
                "meaning": (
                    "Reasoner output is useful for search and analysis but is never an editorial assertion."
                ),
            },
        },
        "summary": {
            "availableResources": full_counts["resources"],
            "indexedResources": len(resource_index),
            "shownResources": len(resources),
            "availableIdentifiers": full_counts["identifiers"],
            "indexedIdentifiers": len(identifier_rows),
            "shownIdentifiers": sum(len(resource["identifiers"]) for resource in resources),
            "availableSourceRecords": full_counts["sourceRecords"],
            "indexedSourceRecords": len(source_record_ids),
            "shownSourceRecords": len(shown_source_records),
            "availableAssertedRelations": full_counts["relationAssertions"],
            "indexedAssertedRelations": len(assertion_ids),
            "shownAssertedRelations": len(assertions),
            "provenanceClosureAssertedRelations": (
                len(assertions) - len(primary_assertion_ids)
            ),
            "currentAuthoritativeRelations": current_authoritative_relations,
            "availableProjectedRelations": full_counts["projectedRelations"],
            "indexedProjectedRelations": len(projected_ids),
            "shownProjectedRelations": len(projected),
            "availableDerivedRelations": full_counts["derivedRelations"],
            "indexedDerivedRelations": len(derived_ids),
            "shownDerivedRelations": len(derived_rows),
            "truncated": any(
                (
                    len(resources) < full_counts["resources"],
                    len(identifier_rows) < full_counts["identifiers"],
                    len(assertions) < full_counts["relationAssertions"],
                    len(projected) < full_counts["projectedRelations"],
                    len(derived_rows) < full_counts["derivedRelations"],
                )
            ),
        },
        "atlasReleases": sorted(
            (
                _release_view(
                    asserted,
                    release,
                    source=False,
                    member_count=release_member_counts.get(str(release)),
                )
                for release in set(asserted.subjects(RDF.type, ATLAS.AtlasRelease))
                if isinstance(release, URIRef)
            ),
            key=lambda row: row["id"],
        ),
        "sourceReleases": sorted(
            (
                _release_view(asserted, release, source=True)
                for release in set(asserted.subjects(RDF.type, ATLAS.SourceRelease))
                if isinstance(release, URIRef)
            ),
            key=lambda row: row["id"],
        ),
        "sourceRecords": shown_source_records,
        "resourceIndex": resource_index,
        "resources": resources,
        "assertedRelations": assertions,
        "projectedRelations": projected,
        "derivedRelations": derived_rows,
    }
    if full_corpus is not None:
        bundle = _mapping(full_corpus, "Atlas explorer static shard bundle")
        expected_fields = frozenset(
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
        )
        _exact_fields(bundle, expected_fields, "Atlas explorer static shard bundle")
        if (
            bundle.get("type") != _EXPLORER_SHARD_BUNDLE_TYPE
            or bundle.get("version") != _EXPLORER_SHARD_VERSION
            or bundle.get("manifestDigest") != distribution.manifest_digest
            or bundle.get("assertedInventoryDigest")
            != _asserted_inventory_digest(distribution.manifest)
            or bundle.get("builderRecipe") != ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE
            or bundle.get("schema") != _EXPLORER_SHARD_SCHEMA
            or _mapping(bundle.get("counts"), "Atlas explorer shard counts").get(
                "resources"
            )
            != full_counts["resources"]
        ):
            raise Atlas3ExplorerError(
                "Atlas explorer static shards describe a different corpus"
            )
        _explorer_shard_ref(bundle.get("index"), "Atlas explorer shard index")
        model["fullCorpus"] = _json_copy(bundle)
    return model


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
    atlas:"https://refspec.org/ns/atlas/v3#",skosxl:"http://www.w3.org/2008/05/skos-xl#"
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
    return {id,sourceRecord:source.id,sourceRecordContentDigest:source.contentDigest,sourceDigest:oneLiteral(record,`${rdf.atlas}evidenceSourceDigest`),decisionStatus:short(oneIri(record,`${rdf.atlas}decisionStatus`)),reviewMethod:short(oneIri(record,`${rdf.atlas}reviewMethod`)),decidedAt:oneLiteral(record,`${rdf.atlas}decidedAt`),contentDigest:oneLiteral(record,`${rdf.atlas}contentDigest`),...(oneIri(record,`${rdf.atlas}reviewedBy`)?{reviewedBy:oneIri(record,`${rdf.atlas}reviewedBy`)}:{})};
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
  function reviewMethod(method){
    return ({
      publisherAssertion:{title:"Publisher supplied",reason:"Supplied directly by the publisher."},
      deterministicTransformation:{title:"Fixed-rule transformation",reason:"Atlas applied a fixed rule to publisher data."},
      twoMachineAdjudication:{title:"Two-model agreement",reason:"Two independent models agreed."},
      operatorAdoption:{title:"Operator adopted",reason:"An operator accepted it."},
      humanReview:{title:"Human approved",reason:"A human reviewer approved it."},
      trustedPipelineReview:{title:"Pipeline approved",reason:"A trusted pipeline approved it."}
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
    const method=evidence.reviewMethod==="operatorAdoption"?"Operator adoption":reviewMethod(evidence.reviewMethod).title;
    const adoptionDate=String(evidence.decidedAt||"").slice(0,10)||"date not recorded";
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
    const reasons=[...new Set(evidence.map(item=>reviewMethod(item.reviewMethod).reason))];
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
    const rows=edge.evidence.map(item=>{const method=reviewMethod(item.reviewMethod),source=sourceById.get(item.sourceRecord);return `<div class="evidence-row"><b>${esc(friendlySource(source))} · ${esc(method.title)}</b><p>${esc(item.decisionStatus)} · digest pinned</p></div>`;}).join("");
    return `<section class="supporting"><h4>Evidence</h4><div class="evidence-list">${rows}</div></section>`;
  }
  function supportingBrief(edge){
    const ids=edge.layer==="projection"?edge.supportingAssertions:edge.layer==="derived"?edge.derivedFromAssertions:[];
    if(!ids?.length)return "";
    const rows=ids.map(id=>{const assertion=assertedById.get(id);if(!assertion)return `<div class="evidence-row"><b>Supporting assertion</b><p>${esc(id)}</p></div>`;const readable={...assertion,layer:"asserted"};const method=reviewMethod(assertion.evidence?.[0]?.reviewMethod).title;const meaning=edge.layer==="derived"?`<span>${esc(relationMeaning(readable))}</span>`:"";return `<button class="support-link" data-edge="asserted|${esc(id)}"><b>${esc(assertion.subjectLabel)} → ${esc(assertion.objectLabel)}</b>${meaning}<small>${esc(method)} · open</small></button>`;}).join("");
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


__all__ = [
    "ATLAS_V3_EXPLORER_SCHEMA_VERSION",
    "ATLAS_V3_EXPLORER_SHARD_BUILDER_RECIPE",
    "ATLAS_V3_EXPLORER_TYPE",
    "EXPLORER_FILTER_SEMANTICS",
    "EXPLORER_SCHEMA_VERSION",
    "EXPLORER_TYPE",
    "PLANNING_FILTER_SEMANTICS",
    "Atlas3ExplorerDistribution",
    "Atlas3ExplorerError",
    "AtlasExplorerError",
    "atlas_v3_predicate_meaning",
    "build_atlas_v3_explorer_model",
    "build_atlas_v3_explorer_static_shards",
    "open_atlas_v3_explorer_distribution",
    "render_atlas_explorer",
    "render_atlas_v3_explorer",
]

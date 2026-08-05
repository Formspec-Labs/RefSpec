"""Closed acceptance evidence for one exact vocabulary-atlas release.

The acceptance record is downstream of every artifact it checks. It does not
change Atlas identity or grant source-use permission. It proves the exact
planning index, scope, canonical Atlas, publication decision, and complete
explorer agree, then records content-derived counts and explicit passing checks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from typing_extensions import Self

from refspec import binding
from refspec.atlas_index import AtlasIndexError, PinnedAtlasIndex, atlas_index_rows
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import (
    absolute_uri_issue,
    is_sha256_digest,
)

from .atlas_scope import AtlasScopeError, PinnedVocabularyAtlasScope
from .explorer import EXPLORER_SCHEMA_VERSION, EXPLORER_TYPE
from .model import VocabularyAtlasAsset, VocabularyAtlasError, build_vocabulary_atlas
from .publication_decision import (
    PublicationDecisionError,
    VocabularyAtlasPublicationDecision,
)
from .queries import VocabularyAtlasQueries

RELEASE_ACCEPTANCE_TYPE = "VocabularyAtlasReleaseAcceptance"
RELEASE_ACCEPTANCE_VERSION = "1.0"

AcceptanceCheckStatus = Literal["passed"]
ReproducibilityStatus = Literal[
    "reproduced",
    "pinnedNonReproducible",
    "notApplicable",
]

_RINGS = ("subject", "entity", "value", "legalIdentity")
_RING_ORDER = {ring: index for index, ring in enumerate(_RINGS)}
_ACCEPTANCE_ID_PREFIX = "urn:ref:vocabulary-atlas-release-acceptance:"

_ATLAS_PIN_FIELDS = frozenset({"role", "id", "manifestDigest", "distributionDigest"})
_SCOPE_PIN_FIELDS = frozenset({"role", "id", "contentDigest", "fileDigest"})
_INDEX_PIN_FIELDS = frozenset({"role", "id", "indexDigest", "fileDigest"})
_DECISION_PIN_FIELDS = frozenset({"role", "id", "recordDigest", "fileDigest"})
_EXPLORER_PIN_FIELDS = frozenset({"role", "type", "schemaVersion", "fileDigest", "byteLength"})
_CHECK_FIELDS = frozenset({"id", "statement", "status", "evidence"})
_REPRODUCIBILITY_FIELDS = frozenset({"layer", "status", "artifactDigest"})
_COUNTS_FIELDS = frozenset(
    {
        "concepts",
        "nativeRelations",
        "mappingAssertions",
        "evidence",
        "facets",
    }
)
_CONCEPT_COUNT_FIELDS = frozenset({"total", "byRelease", "byRing"})
_NATIVE_COUNT_FIELDS = frozenset({"total", "byRelease", "byRing", "byPredicate"})
_MAPPING_COUNT_FIELDS = frozenset({"total", "byRing", "byRelation"})
_EVIDENCE_COUNT_FIELDS = frozenset({"assertionTotal", "machineProofTotal", "byClass", "byRing"})
_FACET_COUNT_FIELDS = frozenset(
    {
        "rowCount",
        "exactReleaseRowCount",
        "includedReleaseRowCount",
        "resourceCount",
        "sourceModuleCount",
        "byFacet",
        "byRing",
        "byPlanningStatus",
        "bySubjectParticipation",
        "byIntendedUse",
    }
)
_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "atlas",
        "scope",
        "planningIndex",
        "publicationDecision",
        "explorer",
        "counts",
        "reproducibility",
        "checks",
    }
)
_RECORD_FIELDS = _BASIS_FIELDS | {"id", "recordDigest"}
_REPRODUCIBILITY_LAYERS = (
    "planningIndex",
    "sourceConceptReleases",
    "scope",
    "atlas",
    "explorer",
    "machineQualificationEvidence",
)


class ReleaseAcceptanceError(ValueError):
    """Acceptance inputs are incomplete, stale, inconsistent, or malformed."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise ReleaseAcceptanceError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseAcceptanceError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReleaseAcceptanceError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ReleaseAcceptanceError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ReleaseAcceptanceError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise ReleaseAcceptanceError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise ReleaseAcceptanceError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not is_sha256_digest(value):
        raise ReleaseAcceptanceError(f"{label} must be sha256:<64 lowercase hex>")
    return cast(str, value)


def _require_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReleaseAcceptanceError(f"{label} must be a non-negative integer")
    return value


def _normalize_atlas_pin(value: object) -> dict[str, str]:
    label = "release acceptance atlas"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _ATLAS_PIN_FIELDS, label)
    if row.get("role") != "VocabularyAtlas":
        raise ReleaseAcceptanceError("release acceptance atlas.role must be VocabularyAtlas")
    return {
        "role": "VocabularyAtlas",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
        "distributionDigest": _require_digest(row.get("distributionDigest"), f"{label}.distributionDigest"),
    }


def _normalize_scope_pin(value: object) -> dict[str, str]:
    label = "release acceptance scope"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _SCOPE_PIN_FIELDS, label)
    if row.get("role") != "VocabularyAtlasScope":
        raise ReleaseAcceptanceError("release acceptance scope.role must be VocabularyAtlasScope")
    return {
        "role": "VocabularyAtlasScope",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "contentDigest": _require_digest(row.get("contentDigest"), f"{label}.contentDigest"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
    }


def _normalize_index_pin(value: object) -> dict[str, str]:
    label = "release acceptance planningIndex"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _INDEX_PIN_FIELDS, label)
    if row.get("role") != "AtlasIndex":
        raise ReleaseAcceptanceError("release acceptance planningIndex.role must be AtlasIndex")
    return {
        "role": "AtlasIndex",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "indexDigest": _require_digest(row.get("indexDigest"), f"{label}.indexDigest"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
    }


def _normalize_decision_pin(value: object) -> dict[str, str]:
    label = "release acceptance publicationDecision"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _DECISION_PIN_FIELDS, label)
    if row.get("role") != "VocabularyAtlasPublicationDecision":
        raise ReleaseAcceptanceError(
            "release acceptance publicationDecision.role must be VocabularyAtlasPublicationDecision"
        )
    return {
        "role": "VocabularyAtlasPublicationDecision",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "recordDigest": _require_digest(row.get("recordDigest"), f"{label}.recordDigest"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
    }


def _normalize_explorer_pin(value: object) -> dict[str, Any]:
    label = "release acceptance explorer"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _EXPLORER_PIN_FIELDS, label)
    if row.get("role") != "VocabularyAtlasExplorer":
        raise ReleaseAcceptanceError("release acceptance explorer.role must be VocabularyAtlasExplorer")
    if row.get("type") != EXPLORER_TYPE:
        raise ReleaseAcceptanceError("release acceptance explorer.type is unsupported")
    if row.get("schemaVersion") != EXPLORER_SCHEMA_VERSION:
        raise ReleaseAcceptanceError("release acceptance explorer.schemaVersion is unsupported")
    return {
        "role": "VocabularyAtlasExplorer",
        "type": EXPLORER_TYPE,
        "schemaVersion": EXPLORER_SCHEMA_VERSION,
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
        "byteLength": _require_count(row.get("byteLength"), f"{label}.byteLength"),
    }


def _normalize_ring_counts(value: object, label: str) -> list[dict[str, Any]]:
    values = _require_array(value, label)
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        row_label = f"{label}[{index}]"
        row = _require_mapping(raw, row_label)
        _require_exact_fields(row, frozenset({"semanticRing", "count"}), row_label)
        ring = row.get("semanticRing")
        if ring not in _RING_ORDER:
            raise ReleaseAcceptanceError(f"{row_label}.semanticRing is unsupported")
        result.append(
            {
                "semanticRing": cast(str, ring),
                "count": _require_count(row.get("count"), f"{row_label}.count"),
            }
        )
    if [row["semanticRing"] for row in result] != list(_RINGS):
        raise ReleaseAcceptanceError(f"{label} must contain the four rings in canonical order")
    return result


def _normalize_release_counts(value: object, label: str) -> list[dict[str, Any]]:
    values = _require_array(value, label)
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        row_label = f"{label}[{index}]"
        row = _require_mapping(raw, row_label)
        _require_exact_fields(
            row,
            frozenset({"releaseId", "semanticRing", "count"}),
            row_label,
        )
        ring = row.get("semanticRing")
        if ring not in _RING_ORDER:
            raise ReleaseAcceptanceError(f"{row_label}.semanticRing is unsupported")
        result.append(
            {
                "releaseId": _require_iri(row.get("releaseId"), f"{row_label}.releaseId"),
                "semanticRing": cast(str, ring),
                "count": _require_count(row.get("count"), f"{row_label}.count"),
            }
        )
    keys = [(row["semanticRing"], row["releaseId"]) for row in result]
    if len(keys) != len(set(keys)):
        raise ReleaseAcceptanceError(f"{label} repeats a release")
    if keys != sorted(keys, key=lambda item: (_RING_ORDER[item[0]], item[1])):
        raise ReleaseAcceptanceError(f"{label} is not in canonical order")
    return result


def _normalize_value_counts(value: object, label: str) -> list[dict[str, Any]]:
    values = _require_array(value, label)
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        row_label = f"{label}[{index}]"
        row = _require_mapping(raw, row_label)
        _require_exact_fields(row, frozenset({"value", "count"}), row_label)
        result.append(
            {
                "value": _require_text(row.get("value"), f"{row_label}.value"),
                "count": _require_count(row.get("count"), f"{row_label}.count"),
            }
        )
    keys = [row["value"] for row in result]
    if len(keys) != len(set(keys)):
        raise ReleaseAcceptanceError(f"{label} repeats a value")
    if keys != sorted(keys):
        raise ReleaseAcceptanceError(f"{label} is not in canonical order")
    return result


def _require_partition_total(
    rows: Sequence[Mapping[str, Any]],
    total: int,
    label: str,
) -> None:
    if sum(cast(int, row["count"]) for row in rows) != total:
        raise ReleaseAcceptanceError(f"{label} does not sum to its total")


def _normalize_counts(value: object) -> dict[str, Any]:
    label = "release acceptance counts"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _COUNTS_FIELDS, label)

    concept_row = _require_mapping(row.get("concepts"), f"{label}.concepts")
    _require_exact_fields(concept_row, _CONCEPT_COUNT_FIELDS, f"{label}.concepts")
    concept_total = _require_count(concept_row.get("total"), f"{label}.concepts.total")
    concept_releases = _normalize_release_counts(concept_row.get("byRelease"), f"{label}.concepts.byRelease")
    concept_rings = _normalize_ring_counts(concept_row.get("byRing"), f"{label}.concepts.byRing")
    _require_partition_total(concept_releases, concept_total, f"{label}.concepts.byRelease")
    _require_partition_total(concept_rings, concept_total, f"{label}.concepts.byRing")

    native_row = _require_mapping(row.get("nativeRelations"), f"{label}.nativeRelations")
    _require_exact_fields(native_row, _NATIVE_COUNT_FIELDS, f"{label}.nativeRelations")
    native_total = _require_count(native_row.get("total"), f"{label}.nativeRelations.total")
    native_releases = _normalize_release_counts(native_row.get("byRelease"), f"{label}.nativeRelations.byRelease")
    native_rings = _normalize_ring_counts(native_row.get("byRing"), f"{label}.nativeRelations.byRing")
    native_predicates = _normalize_value_counts(native_row.get("byPredicate"), f"{label}.nativeRelations.byPredicate")
    for partition_name, partition in (
        ("byRelease", native_releases),
        ("byRing", native_rings),
        ("byPredicate", native_predicates),
    ):
        _require_partition_total(
            partition,
            native_total,
            f"{label}.nativeRelations.{partition_name}",
        )

    mapping_row = _require_mapping(row.get("mappingAssertions"), f"{label}.mappingAssertions")
    _require_exact_fields(mapping_row, _MAPPING_COUNT_FIELDS, f"{label}.mappingAssertions")
    mapping_total = _require_count(mapping_row.get("total"), f"{label}.mappingAssertions.total")
    mapping_rings = _normalize_ring_counts(mapping_row.get("byRing"), f"{label}.mappingAssertions.byRing")
    mapping_relations = _normalize_value_counts(mapping_row.get("byRelation"), f"{label}.mappingAssertions.byRelation")
    _require_partition_total(mapping_rings, mapping_total, f"{label}.mappingAssertions.byRing")
    _require_partition_total(mapping_relations, mapping_total, f"{label}.mappingAssertions.byRelation")

    evidence_row = _require_mapping(row.get("evidence"), f"{label}.evidence")
    _require_exact_fields(evidence_row, _EVIDENCE_COUNT_FIELDS, f"{label}.evidence")
    evidence_total = _require_count(evidence_row.get("assertionTotal"), f"{label}.evidence.assertionTotal")
    machine_total = _require_count(
        evidence_row.get("machineProofTotal"),
        f"{label}.evidence.machineProofTotal",
    )
    evidence_classes = _normalize_value_counts(evidence_row.get("byClass"), f"{label}.evidence.byClass")
    evidence_rings = _normalize_ring_counts(evidence_row.get("byRing"), f"{label}.evidence.byRing")
    _require_partition_total(evidence_classes, evidence_total, f"{label}.evidence.byClass")
    _require_partition_total(evidence_rings, evidence_total, f"{label}.evidence.byRing")

    facet_row = _require_mapping(row.get("facets"), f"{label}.facets")
    _require_exact_fields(facet_row, _FACET_COUNT_FIELDS, f"{label}.facets")
    facet_total = _require_count(facet_row.get("rowCount"), f"{label}.facets.rowCount")
    exact_release_rows = _require_count(
        facet_row.get("exactReleaseRowCount"),
        f"{label}.facets.exactReleaseRowCount",
    )
    included_release_rows = _require_count(
        facet_row.get("includedReleaseRowCount"),
        f"{label}.facets.includedReleaseRowCount",
    )
    if exact_release_rows > facet_total or included_release_rows > exact_release_rows:
        raise ReleaseAcceptanceError("release acceptance facet release-row counts are inconsistent")
    resource_count = _require_count(facet_row.get("resourceCount"), f"{label}.facets.resourceCount")
    source_module_count = _require_count(
        facet_row.get("sourceModuleCount"),
        f"{label}.facets.sourceModuleCount",
    )
    if resource_count > facet_total or source_module_count > facet_total:
        raise ReleaseAcceptanceError("release acceptance facet distinct counts exceed the row count")
    facet_counts = _normalize_value_counts(facet_row.get("byFacet"), f"{label}.facets.byFacet")
    facet_rings = _normalize_ring_counts(facet_row.get("byRing"), f"{label}.facets.byRing")
    planning_statuses = _normalize_value_counts(
        facet_row.get("byPlanningStatus"),
        f"{label}.facets.byPlanningStatus",
    )
    participations = _normalize_value_counts(
        facet_row.get("bySubjectParticipation"),
        f"{label}.facets.bySubjectParticipation",
    )
    intended_uses = _normalize_value_counts(facet_row.get("byIntendedUse"), f"{label}.facets.byIntendedUse")
    for partition_name, partition in (
        ("byFacet", facet_counts),
        ("byRing", facet_rings),
        ("byPlanningStatus", planning_statuses),
        ("bySubjectParticipation", participations),
    ):
        _require_partition_total(
            partition,
            facet_total,
            f"{label}.facets.{partition_name}",
        )

    return {
        "concepts": {
            "total": concept_total,
            "byRelease": concept_releases,
            "byRing": concept_rings,
        },
        "nativeRelations": {
            "total": native_total,
            "byRelease": native_releases,
            "byRing": native_rings,
            "byPredicate": native_predicates,
        },
        "mappingAssertions": {
            "total": mapping_total,
            "byRing": mapping_rings,
            "byRelation": mapping_relations,
        },
        "evidence": {
            "assertionTotal": evidence_total,
            "machineProofTotal": machine_total,
            "byClass": evidence_classes,
            "byRing": evidence_rings,
        },
        "facets": {
            "rowCount": facet_total,
            "exactReleaseRowCount": exact_release_rows,
            "includedReleaseRowCount": included_release_rows,
            "resourceCount": resource_count,
            "sourceModuleCount": source_module_count,
            "byFacet": facet_counts,
            "byRing": facet_rings,
            "byPlanningStatus": planning_statuses,
            "bySubjectParticipation": participations,
            "byIntendedUse": intended_uses,
        },
    }


def _normalize_checks(value: object) -> list[dict[str, Any]]:
    values = _require_array(value, "release acceptance checks")
    if not values:
        raise ReleaseAcceptanceError("release acceptance requires at least one check")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        label = f"release acceptance checks[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _CHECK_FIELDS, label)
        if row.get("status") != "passed":
            raise ReleaseAcceptanceError(f"{label}.status must be passed")
        evidence_values = _require_array(row.get("evidence"), f"{label}.evidence")
        if not evidence_values:
            raise ReleaseAcceptanceError(f"{label}.evidence must not be empty")
        evidence = [
            _require_iri(item, f"{label}.evidence[{position}]") for position, item in enumerate(evidence_values)
        ]
        if len(evidence) != len(set(evidence)) or evidence != sorted(evidence):
            raise ReleaseAcceptanceError(f"{label}.evidence must be unique and in canonical order")
        result.append(
            {
                "id": _require_iri(row.get("id"), f"{label}.id"),
                "statement": _require_text(row.get("statement"), f"{label}.statement"),
                "status": "passed",
                "evidence": evidence,
            }
        )
    identifiers = [row["id"] for row in result]
    if len(identifiers) != len(set(identifiers)):
        raise ReleaseAcceptanceError("release acceptance checks repeat an id")
    if identifiers != sorted(identifiers):
        raise ReleaseAcceptanceError("release acceptance checks are not in canonical order")
    return result


def _normalize_reproducibility(value: object) -> list[dict[str, str]]:
    values = _require_array(value, "release acceptance reproducibility")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(values):
        label = f"release acceptance reproducibility[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _REPRODUCIBILITY_FIELDS, label)
        layer = _require_text(row.get("layer"), f"{label}.layer")
        status = row.get("status")
        if status not in {"reproduced", "pinnedNonReproducible", "notApplicable"}:
            raise ReleaseAcceptanceError(f"{label}.status is unsupported")
        if layer != "machineQualificationEvidence" and status != "reproduced":
            raise ReleaseAcceptanceError(f"{label}.status must be reproduced for deterministic layers")
        if layer == "machineQualificationEvidence" and status not in {
            "pinnedNonReproducible",
            "notApplicable",
        }:
            raise ReleaseAcceptanceError(f"{label}.status must state how machine evidence is pinned")
        result.append(
            {
                "layer": layer,
                "status": cast(str, status),
                "artifactDigest": _require_digest(row.get("artifactDigest"), f"{label}.artifactDigest"),
            }
        )
    if [row["layer"] for row in result] != list(_REPRODUCIBILITY_LAYERS):
        raise ReleaseAcceptanceError("release acceptance reproducibility layers differ from v1")
    return result


def _normalize_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseAcceptanceError("release acceptance must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, _RECORD_FIELDS, "release acceptance")
    if row.get("type") != RELEASE_ACCEPTANCE_TYPE:
        raise ReleaseAcceptanceError("release acceptance type is unsupported")
    if row.get("schemaVersion") != RELEASE_ACCEPTANCE_VERSION:
        raise ReleaseAcceptanceError("release acceptance schemaVersion is unsupported")
    basis = {
        "type": RELEASE_ACCEPTANCE_TYPE,
        "schemaVersion": RELEASE_ACCEPTANCE_VERSION,
        "atlas": _normalize_atlas_pin(row.get("atlas")),
        "scope": _normalize_scope_pin(row.get("scope")),
        "planningIndex": _normalize_index_pin(row.get("planningIndex")),
        "publicationDecision": _normalize_decision_pin(row.get("publicationDecision")),
        "explorer": _normalize_explorer_pin(row.get("explorer")),
        "counts": _normalize_counts(row.get("counts")),
        "reproducibility": _normalize_reproducibility(row.get("reproducibility")),
        "checks": _normalize_checks(row.get("checks")),
    }
    record_digest = sha256_digest(_canonical_bytes(basis))
    expected = {
        **basis,
        "id": _ACCEPTANCE_ID_PREFIX + record_digest.removeprefix("sha256:"),
        "recordDigest": record_digest,
    }
    if row != expected:
        raise ReleaseAcceptanceError("release acceptance identity, inputs, counts, or canonical order differs")
    return expected


def _ring_count_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"semanticRing": ring, "count": counter[ring]} for ring in _RINGS]


def _value_count_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"value": value, "count": counter[value]} for value in sorted(counter)]


def _derived_counts(
    queries: VocabularyAtlasQueries,
    planning_index: Mapping[str, Any],
) -> dict[str, Any]:
    snapshots = queries.release_snapshots()
    concepts = queries.concepts()
    native_relations = queries.native_relations()
    mappings = queries.mapping_assertions()
    evidence_records = queries.records(role="evidenceAssertion")
    machine_records = queries.records(role="machineProof")
    classifications = queries.index_classifications()
    planning_rows = atlas_index_rows(planning_index)

    concept_by_release = Counter(value.release_id for value in concepts)
    concept_by_ring = Counter(value.semantic_ring for value in concepts)
    native_by_release = Counter(value.release_id for value in native_relations)
    native_by_ring = Counter(value.semantic_ring for value in native_relations)
    native_by_predicate = Counter(value.predicate_iri for value in native_relations)
    mapping_by_ring = Counter(value.assertion.semantic_ring for value in mappings)
    mapping_by_relation = Counter(value.assertion.relation for value in mappings)

    evidence_by_class: Counter[str] = Counter()
    evidence_by_ring: Counter[str] = Counter()
    for record in evidence_records:
        evidence_class = record.record.get("evidenceClass")
        semantic_ring = record.record.get("semanticRing")
        if not isinstance(evidence_class, str) or semantic_ring not in _RING_ORDER:
            raise ReleaseAcceptanceError("canonical evidence record has invalid class or semantic ring")
        evidence_by_class[evidence_class] += 1
        evidence_by_ring[cast(str, semantic_ring)] += 1

    facet_counts: Counter[str] = Counter()
    planning_ring_counts: Counter[str] = Counter()
    planning_status_counts: Counter[str] = Counter()
    participation_counts: Counter[str] = Counter()
    intended_use_counts: Counter[str] = Counter()
    resource_ids: set[str] = set()
    source_modules: set[str] = set()
    exact_release_rows = 0
    for index, raw in enumerate(planning_rows):
        row = _require_mapping(raw, f"verified planning index rows[{index}]")
        facet = _require_iri(row.get("facet"), f"verified planning index rows[{index}].facet")
        ring = row.get("semanticRing")
        if ring not in _RING_ORDER:
            raise ReleaseAcceptanceError(f"verified planning index rows[{index}].semanticRing is unsupported")
        planning_status = _require_text(
            row.get("planningStatus"),
            f"verified planning index rows[{index}].planningStatus",
        )
        participation = row.get("atlasParticipation")
        if participation is None:
            participation_value = "unassigned"
        else:
            participation_value = _require_text(
                participation,
                f"verified planning index rows[{index}].atlasParticipation",
            )
        resource_ids.add(
            _require_text(
                row.get("resourceId"),
                f"verified planning index rows[{index}].resourceId",
            )
        )
        source_modules.add(
            _require_text(
                row.get("sourceModule"),
                f"verified planning index rows[{index}].sourceModule",
            )
        )
        uses = _require_array(
            row.get("intendedUses"),
            f"verified planning index rows[{index}].intendedUses",
        )
        facet_counts[facet] += 1
        planning_ring_counts[cast(str, ring)] += 1
        planning_status_counts[planning_status] += 1
        participation_counts[participation_value] += 1
        intended_use_counts.update(
            _require_text(
                use,
                f"verified planning index rows[{index}].intendedUses[{position}]",
            )
            for position, use in enumerate(uses)
        )
        if row.get("release") is not None:
            exact_release_rows += 1

    release_count_rows = [
        {
            "releaseId": snapshot.release_id,
            "semanticRing": snapshot.semantic_ring,
            "count": concept_by_release[snapshot.release_id],
        }
        for snapshot in snapshots
    ]
    native_release_count_rows = [
        {
            "releaseId": snapshot.release_id,
            "semanticRing": snapshot.semantic_ring,
            "count": native_by_release[snapshot.release_id],
        }
        for snapshot in snapshots
    ]
    return {
        "concepts": {
            "total": len(concepts),
            "byRelease": release_count_rows,
            "byRing": _ring_count_rows(concept_by_ring),
        },
        "nativeRelations": {
            "total": len(native_relations),
            "byRelease": native_release_count_rows,
            "byRing": _ring_count_rows(native_by_ring),
            "byPredicate": _value_count_rows(native_by_predicate),
        },
        "mappingAssertions": {
            "total": len(mappings),
            "byRing": _ring_count_rows(mapping_by_ring),
            "byRelation": _value_count_rows(mapping_by_relation),
        },
        "evidence": {
            "assertionTotal": len(evidence_records),
            "machineProofTotal": len(machine_records),
            "byClass": _value_count_rows(evidence_by_class),
            "byRing": _ring_count_rows(evidence_by_ring),
        },
        "facets": {
            "rowCount": len(planning_rows),
            "exactReleaseRowCount": exact_release_rows,
            "includedReleaseRowCount": len(classifications),
            "resourceCount": len(resource_ids),
            "sourceModuleCount": len(source_modules),
            "byFacet": _value_count_rows(facet_counts),
            "byRing": _ring_count_rows(planning_ring_counts),
            "byPlanningStatus": _value_count_rows(planning_status_counts),
            "bySubjectParticipation": _value_count_rows(participation_counts),
            "byIntendedUse": _value_count_rows(intended_use_counts),
        },
    }


def _explorer_rows(value: object, label: str) -> Sequence[Mapping[str, Any]]:
    rows = _require_array(value, label)
    result: list[Mapping[str, Any]] = []
    for index, raw in enumerate(rows):
        result.append(_require_mapping(raw, f"{label}[{index}]"))
    return result


def _verified_explorer_bytes(
    atlas: VocabularyAtlasAsset,
    explorer: Mapping[str, Any],
    queries: VocabularyAtlasQueries,
) -> bytes:
    if explorer.get("type") != EXPLORER_TYPE:
        raise ReleaseAcceptanceError("explorer type is unsupported")
    if explorer.get("schemaVersion") != EXPLORER_SCHEMA_VERSION:
        raise ReleaseAcceptanceError("explorer schemaVersion is unsupported")
    atlas_row = _require_mapping(explorer.get("atlas"), "explorer atlas")
    expected_atlas = {
        "kind": "atlas",
        "assetId": _require_iri(atlas.manifest.get("id"), "atlas manifest id"),
        "manifestDigest": atlas.manifest_digest,
        "distributionDigest": atlas.output_digest,
    }
    if any(atlas_row.get(key) != value for key, value in expected_atlas.items()):
        raise ReleaseAcceptanceError("explorer names another canonical Atlas")

    summary = _require_mapping(explorer.get("summary"), "explorer summary")
    concepts = queries.concepts()
    native_relations = queries.native_relations()
    mappings = queries.mapping_assertions()
    expected_summary = {
        "availableConceptCount": len(concepts),
        "availableNativeRelationCount": len(native_relations),
        "availableMappingAssertionCount": len(mappings),
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        raise ReleaseAcceptanceError("explorer available counts differ from the canonical Atlas")
    if summary.get("truncated") is not False:
        raise ReleaseAcceptanceError("release acceptance requires a complete explorer")

    concept_rows = _explorer_rows(explorer.get("concepts"), "explorer concepts")
    native_rows = _explorer_rows(explorer.get("nativeRelations"), "explorer nativeRelations")
    mapping_rows = _explorer_rows(explorer.get("mappingAssertions"), "explorer mappingAssertions")
    release_rows = _explorer_rows(explorer.get("conceptReleases"), "explorer conceptReleases")
    shown = {
        "shownConceptCount": len(concept_rows),
        "shownNativeRelationCount": len(native_rows),
        "shownMappingAssertionCount": len(mapping_rows),
    }
    if any(summary.get(key) != value for key, value in shown.items()):
        raise ReleaseAcceptanceError("explorer shown counts differ from its rows")

    expected_concepts = {(value.release_id, value.concept_id, value.record_id) for value in concepts}
    actual_concepts = {
        (
            row.get("releaseId"),
            row.get("conceptId"),
            row.get("recordId"),
        )
        for row in concept_rows
    }
    if len(actual_concepts) != len(concept_rows) or actual_concepts != expected_concepts:
        raise ReleaseAcceptanceError("explorer concept rows differ from the canonical Atlas")
    expected_native = {value.relation_id for value in native_relations}
    actual_native = {row.get("id") for row in native_rows}
    if len(actual_native) != len(native_rows) or actual_native != expected_native:
        raise ReleaseAcceptanceError("explorer native relation rows differ from the canonical Atlas")
    expected_mappings = {value.mapping_id for value in mappings}
    actual_mappings = {row.get("id") for row in mapping_rows}
    if len(actual_mappings) != len(mapping_rows) or actual_mappings != expected_mappings:
        raise ReleaseAcceptanceError("explorer mapping rows differ from the canonical Atlas")
    expected_releases = {
        (
            snapshot.release_id,
            snapshot.semantic_ring,
            len(queries.concepts(release_id=snapshot.release_id)),
        )
        for snapshot in queries.release_snapshots()
    }
    actual_releases = {
        (
            row.get("releaseId"),
            row.get("semanticRing"),
            row.get("conceptCount"),
        )
        for row in release_rows
    }
    if len(actual_releases) != len(release_rows) or actual_releases != expected_releases:
        raise ReleaseAcceptanceError("explorer release rows differ from the canonical Atlas")

    title = _require_text(explorer.get("title"), "explorer title")
    selection = _require_mapping(explorer.get("selectionPolicy"), "explorer selectionPolicy")
    max_concepts = _require_count(selection.get("maxConcepts"), "explorer selectionPolicy.maxConcepts")
    max_mappings = _require_count(
        selection.get("maxMappingAssertions"),
        "explorer selectionPolicy.maxMappingAssertions",
    )
    labels = {
        _require_iri(row.get("releaseId"), f"explorer conceptReleases[{index}].releaseId"): _require_text(
            row.get("label"), f"explorer conceptReleases[{index}].label"
        )
        for index, row in enumerate(release_rows)
    }

    # Import at validation time so publication can include this module without
    # creating a module-import cycle.
    from .publication import build_explorer_model

    rebuilt = build_explorer_model(
        atlas,
        title=title,
        release_labels=labels,
        max_concepts=max_concepts,
        max_mapping_assertions=max_mappings,
    )
    payload = _canonical_bytes(explorer)
    if _canonical_bytes(rebuilt) != payload:
        raise ReleaseAcceptanceError("explorer does not reproduce from the canonical Atlas and its stated policy")
    return payload


def _acceptance_basis(
    atlas: VocabularyAtlasAsset,
    *,
    scope: PinnedVocabularyAtlasScope,
    planning_index: PinnedAtlasIndex,
    publication_decision: VocabularyAtlasPublicationDecision,
    explorer: Mapping[str, Any],
    checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(atlas, VocabularyAtlasAsset):
        raise ReleaseAcceptanceError("release acceptance requires a verified canonical VocabularyAtlasAsset")
    if not isinstance(scope, PinnedVocabularyAtlasScope):
        raise ReleaseAcceptanceError("release acceptance requires a path-backed exact atlas scope")
    if not isinstance(planning_index, PinnedAtlasIndex):
        raise ReleaseAcceptanceError("release acceptance requires a pinned planning index")
    if not isinstance(publication_decision, VocabularyAtlasPublicationDecision):
        raise ReleaseAcceptanceError("release acceptance requires a publication decision")
    if not isinstance(explorer, Mapping):
        raise ReleaseAcceptanceError("release acceptance explorer must be an object")

    atlas._require_verified()
    verified_scope = scope.verified_scope()
    verified_index = planning_index.verified_index()
    scope_index_pin = verified_scope.atlas_index.pin()
    index_pin = planning_index.pin()
    if scope_index_pin != index_pin:
        raise ReleaseAcceptanceError("release acceptance planning index differs from the scope input")
    if verified_scope.artifact_bytes() != atlas.scope_payload:
        raise ReleaseAcceptanceError("release acceptance scope differs from the canonical Atlas scope bytes")

    rebuilt = build_vocabulary_atlas(scope)
    if (
        rebuilt.payload != atlas.payload
        or rebuilt.scope_payload != atlas.scope_payload
        or rebuilt.manifest_bytes() != atlas.manifest_bytes()
    ):
        raise ReleaseAcceptanceError("canonical Atlas does not reproduce from the exact pinned scope")
    publication_decision.validate_distribution(atlas)

    queries = VocabularyAtlasQueries(atlas)
    explorer_payload = _verified_explorer_bytes(atlas, explorer, queries)
    counts = _derived_counts(queries, verified_index)
    normalized_checks = _normalize_checks(checks)

    scope_record = verified_scope.as_record()
    release_pins = _require_array(scope_record.get("releases"), "verified atlas scope releases")
    machine_records = queries.records(role="machineProof")
    machine_pin_rows = [{"id": value.record_id, "recordDigest": value.record_digest} for value in machine_records]
    machine_status: ReproducibilityStatus = "pinnedNonReproducible" if machine_records else "notApplicable"

    atlas_id = _require_iri(atlas.manifest.get("id"), "atlas manifest id")
    decision_payload = publication_decision.artifact_bytes()
    reproducibility = [
        {
            "layer": "planningIndex",
            "status": "reproduced",
            "artifactDigest": planning_index.file_digest,
        },
        {
            "layer": "sourceConceptReleases",
            "status": "reproduced",
            "artifactDigest": sha256_digest(_canonical_bytes(release_pins)),
        },
        {
            "layer": "scope",
            "status": "reproduced",
            "artifactDigest": scope.file_digest,
        },
        {
            "layer": "atlas",
            "status": "reproduced",
            "artifactDigest": atlas.manifest_digest,
        },
        {
            "layer": "explorer",
            "status": "reproduced",
            "artifactDigest": sha256_digest(explorer_payload),
        },
        {
            "layer": "machineQualificationEvidence",
            "status": machine_status,
            "artifactDigest": sha256_digest(_canonical_bytes(machine_pin_rows)),
        },
    ]
    return {
        "type": RELEASE_ACCEPTANCE_TYPE,
        "schemaVersion": RELEASE_ACCEPTANCE_VERSION,
        "atlas": {
            "role": "VocabularyAtlas",
            "id": atlas_id,
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
        },
        "scope": scope.pin(),
        "planningIndex": index_pin,
        "publicationDecision": {
            "role": "VocabularyAtlasPublicationDecision",
            "id": publication_decision.identifier,
            "recordDigest": publication_decision.record_digest,
            "fileDigest": sha256_digest(decision_payload),
        },
        "explorer": {
            "role": "VocabularyAtlasExplorer",
            "type": EXPLORER_TYPE,
            "schemaVersion": EXPLORER_SCHEMA_VERSION,
            "fileDigest": sha256_digest(explorer_payload),
            "byteLength": len(explorer_payload),
        },
        "counts": counts,
        "reproducibility": reproducibility,
        "checks": normalized_checks,
    }


@dataclass(frozen=True, slots=True)
class VocabularyAtlasReleaseAcceptance:
    """One immutable, content-derived v1 release acceptance record."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        normalized = _normalize_record(self.record)
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(normalized)),
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> Self:
        return cls(record=value)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    @property
    def reference(self) -> Mapping[str, str]:
        return {"id": self.identifier, "recordDigest": self.record_digest}

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def validate_inputs(
        self,
        atlas: VocabularyAtlasAsset,
        *,
        scope: PinnedVocabularyAtlasScope,
        planning_index: PinnedAtlasIndex,
        publication_decision: VocabularyAtlasPublicationDecision,
        explorer: Mapping[str, Any],
    ) -> None:
        """Re-run every acceptance derivation against the supplied artifacts."""

        expected = build_vocabulary_atlas_release_acceptance(
            atlas,
            scope=scope,
            planning_index=planning_index,
            publication_decision=publication_decision,
            explorer=explorer,
            checks=cast(Sequence[Mapping[str, Any]], self.record["checks"]),
        )
        if expected.as_record() != self.as_record():
            raise ReleaseAcceptanceError("release acceptance record differs from the supplied exact artifacts")


def build_vocabulary_atlas_release_acceptance(
    atlas: VocabularyAtlasAsset,
    *,
    scope: PinnedVocabularyAtlasScope,
    planning_index: PinnedAtlasIndex,
    publication_decision: VocabularyAtlasPublicationDecision,
    explorer: Mapping[str, Any],
    checks: Sequence[Mapping[str, Any]],
) -> VocabularyAtlasReleaseAcceptance:
    """Verify one complete release and seal its exact acceptance evidence."""

    try:
        basis = _acceptance_basis(
            atlas,
            scope=scope,
            planning_index=planning_index,
            publication_decision=publication_decision,
            explorer=explorer,
            checks=checks,
        )
    except ReleaseAcceptanceError:
        raise
    except (
        AtlasIndexError,
        AtlasScopeError,
        PublicationDecisionError,
        VocabularyAtlasError,
        TypeError,
        ValueError,
    ) as error:
        raise ReleaseAcceptanceError(str(error)) from error
    record_digest = sha256_digest(_canonical_bytes(basis))
    return VocabularyAtlasReleaseAcceptance(
        {
            **basis,
            "id": _ACCEPTANCE_ID_PREFIX + record_digest.removeprefix("sha256:"),
            "recordDigest": record_digest,
        }
    )


__all__ = [
    "RELEASE_ACCEPTANCE_TYPE",
    "RELEASE_ACCEPTANCE_VERSION",
    "AcceptanceCheckStatus",
    "ReleaseAcceptanceError",
    "ReproducibilityStatus",
    "VocabularyAtlasReleaseAcceptance",
    "build_vocabulary_atlas_release_acceptance",
]
